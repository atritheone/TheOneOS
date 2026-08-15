import hashlib
import importlib.util
import os
import pathlib
import sys

validator_path = pathlib.Path(sys.argv[1])
image_path = pathlib.Path(sys.argv[2])
mode = sys.argv[3]
spec = importlib.util.spec_from_file_location('t1os_journal_validator', validator_path)
if spec is None or spec.loader is None:
    raise SystemExit('could not load the journal validator')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def write_ranges(handle, ranges, payload):
    cursor = 0
    for item in ranges:
        take = item['bytes']
        handle.seek(item['device_offset'])
        if handle.write(payload[cursor:cursor + take]) != take:
            raise SystemExit('short negative-fixture write')
        cursor += take
    if cursor != len(payload):
        raise SystemExit('negative-fixture physical mapping is incomplete')


def write_stream(handle, volume, runs, offset, payload):
    ranges = volume.stream_physical_ranges(runs, offset, len(payload))
    write_ranges(handle, ranges, payload)


def rewrite_digest(block):
    block[module.SUPERBLOCK_DIGEST_OFFSET:] = hashlib.sha256(
        block[:module.SUPERBLOCK_DIGEST_OFFSET]
    ).digest()


def locate_named_record(volume, expected):
    matches = []
    count = volume.mft_data_size // volume.record_size
    for number in range(count):
        try:
            record = volume.record(number)
        except module.ValidationError:
            continue
        if not record.in_use:
            continue
        for attribute in record.attributes:
            if attribute.type_code != module.AT_FILE_NAME:
                continue
            details = module.filename_details(attribute)
            if details['name'] == expected and details['parent_record'] == module.EXTEND_RECORD:
                matches.append(record)
    if len({record.number for record in matches}) != 1:
        raise SystemExit(f'could not uniquely find negative-fixture record {expected!r}')
    return matches[0]


def locate_attribute_offset(fixed, type_code, attribute_name=''):
    cursor = module.u16(fixed, 20)
    used = module.u32(fixed, 24)
    while cursor + 4 <= used:
        actual = module.u32(fixed, cursor)
        if actual == module.AT_END:
            break
        length = module.u32(fixed, cursor + 4)
        name_length = fixed[cursor + 9]
        name_offset = module.u16(fixed, cursor + 10)
        name = ''
        if name_length:
            name = fixed[
                cursor + name_offset:cursor + name_offset + name_length * 2
            ].decode('utf-16le')
        if actual == type_code and name == attribute_name:
            return cursor
        cursor += length
    raise SystemExit('could not locate negative-fixture attribute')


def assert_not_fixup_tail(volume, offsets):
    for offset in offsets:
        if offset % volume.sector_size in (volume.sector_size - 2, volume.sector_size - 1):
            raise SystemExit('negative-fixture patch would overwrite an MFT fixup tail')


with image_path.open('r+b', buffering=0) as handle:
    volume = module.NtfsVolume(handle)
    journal_record, _ = module.find_journal(volume)
    journal_data = volume.unnamed_data(journal_record)
    journal_runs = journal_data.runs()

    if mode in {
        'torn-one', 'torn-both', 'misbound-serial', 'uuid-disagreement',
        'nonempty-transaction-kind', 'invalid-entry-cap',
    }:
        headers = bytearray(volume.read_stream(journal_runs, 0, module.ENTRY_AREA_START))
        slots = [0] if mode in {'torn-one', 'uuid-disagreement'} else [
            0, module.SUPERBLOCK_SIZE
        ]
        if mode in {'torn-one', 'torn-both'}:
            for slot in slots:
                headers[slot] ^= 0x80
        elif mode == 'misbound-serial':
            for slot in slots:
                block = bytearray(headers[slot:slot + module.SUPERBLOCK_SIZE])
                wrong = module.u64(block, 0x028) ^ 1
                block[0x028:0x030] = wrong.to_bytes(8, 'little')
                rewrite_digest(block)
                headers[slot:slot + module.SUPERBLOCK_SIZE] = block
        elif mode == 'uuid-disagreement':
            slot = module.SUPERBLOCK_SIZE
            block = bytearray(headers[slot:slot + module.SUPERBLOCK_SIZE])
            block[0x030] ^= 0x01
            rewrite_digest(block)
            headers[slot:slot + module.SUPERBLOCK_SIZE] = block
        else:
            for slot in slots:
                block = bytearray(headers[slot:slot + module.SUPERBLOCK_SIZE])
                if mode == 'nonempty-transaction-kind':
                    block[0x0A0:0x0A4] = (1).to_bytes(4, 'little')
                else:
                    block[0x0A4:0x0A8] = (0).to_bytes(4, 'little')
                rewrite_digest(block)
                headers[slot:slot + module.SUPERBLOCK_SIZE] = block
        write_stream(handle, volume, journal_runs, 0, headers)
    elif mode == 'nonzero-entry':
        write_stream(handle, volume, journal_runs, module.ENTRY_AREA_START, b'X')
    elif mode.startswith('missing-protected-'):
        selected = mode.removeprefix('missing-protected-')
        copy_sets = {
            'standard': frozenset(('standard',)),
            'file-name': frozenset(('file_name',)),
            'index': frozenset(('index',)),
            'all': frozenset(('standard', 'file_name', 'index')),
        }
        if selected not in copy_sets:
            raise SystemExit(f'unknown protected-flag copy: {selected}')
        required = module.REQUIRED_PROTECTED_FLAGS
        module.rewrite_journal_flag_copies(
            handle,
            volume,
            journal_record,
            expected_flags=(required, required, required),
            desired_flags=required & ~module.FILE_ATTRIBUTE_NOT_CONTENT_INDEXED,
            copies=copy_sets[selected],
        )
    elif mode == 'clear-bitmap':
        first_lcn = journal_runs[0].lcn
        if first_lcn is None:
            raise SystemExit('journal fixture unexpectedly begins with a sparse run')
        bitmap = volume.unnamed_data(volume.record(module.BITMAP_RECORD))
        bitmap_runs = bitmap.runs()
        byte_offset = first_lcn >> 3
        original = volume.read_stream(bitmap_runs, byte_offset, 1)[0]
        changed = bytes([original & ~(1 << (first_lcn & 7))])
        if changed[0] == original:
            raise SystemExit('journal fixture bitmap bit was already clear')
        write_stream(handle, volume, bitmap_runs, byte_offset, changed)
    elif mode == 'clear-mft-bitmap':
        mft = volume.record(0)
        bitmap_attributes = [
            item for item in mft.attributes
            if item.type_code == module.AT_BITMAP and item.name == ''
        ]
        if len(bitmap_attributes) != 1:
            raise SystemExit('fixture lacks one exact $MFT/$BITMAP')
        bitmap_attribute = bitmap_attributes[0]
        byte_offset = journal_record.number >> 3
        bit = journal_record.number & 7
        if bitmap_attribute.nonresident:
            bitmap_runs = bitmap_attribute.runs()
            original = volume.read_stream(bitmap_runs, byte_offset, 1)[0]
            changed = bytes([original & ~(1 << bit)])
            write_stream(handle, volume, bitmap_runs, byte_offset, changed)
        else:
            logical = module.read_file_record_logical(volume, 0)
            value_offset = module.attribute_value_start(bitmap_attribute)
            original = logical[value_offset + byte_offset]
            logical[value_offset + byte_offset] = original & ~(1 << bit)
            module.write_file_record_logical(handle, volume, 0, logical)
        if not (original & (1 << bit)):
            raise SystemExit('journal fixture MFT bitmap bit was already clear')
    elif mode == 'self-overlap':
        record_offset = journal_record.number * volume.record_size
        raw = volume.read_stream(volume.mft_runs, record_offset, volume.record_size)
        fixed = bytearray(volume.apply_fixups(raw))
        attribute = locate_attribute_offset(fixed, module.AT_DATA)
        attribute_length = module.u32(fixed, attribute + 4)
        mapping_offset = module.u16(fixed, attribute + 32)
        mapping = attribute + mapping_offset
        available = attribute_length - mapping_offset
        first_lcn = journal_runs[0].lcn
        clusters = journal_runs[0].length
        if first_lcn is None or clusters < 4 or len(journal_runs) != 1:
            raise SystemExit('self-overlap fixture requires one mapped journal run')

        def unsigned(value):
            width = max(1, (value.bit_length() + 7) // 8)
            return value.to_bytes(width, 'little')

        def signed(value):
            for width in range(1, 9):
                try:
                    return value.to_bytes(width, 'little', signed=True)
                except OverflowError:
                    pass
            raise SystemExit('self-overlap delta exceeds signed 64-bit')

        first_length = clusters // 2
        second_length = clusters - first_length
        first_length_bytes = unsigned(first_length)
        first_offset_bytes = signed(first_lcn)
        second_length_bytes = unsigned(second_length)
        second_offset_bytes = signed(1)
        encoded = (
            bytes([(len(first_offset_bytes) << 4) | len(first_length_bytes)])
            + first_length_bytes + first_offset_bytes
            + bytes([(len(second_offset_bytes) << 4) | len(second_length_bytes)])
            + second_length_bytes + second_offset_bytes + b'\0'
        )
        if len(encoded) > available:
            old_end = attribute + attribute_length
            used = module.u32(fixed, 24)
            if (
                old_end + 8 != used
                or module.u32(fixed, old_end) != module.AT_END
                or used + 8 > len(fixed)
                or len(encoded) > available + 8
            ):
                raise SystemExit('journal mapping-pairs record has no safe tail expansion')
            fixed[old_end + 8:old_end + 16] = fixed[old_end:old_end + 8]
            fixed[old_end:old_end + 8] = b'\0' * 8
            attribute_length += 8
            available += 8
            fixed[attribute + 4:attribute + 8] = attribute_length.to_bytes(4, 'little')
            fixed[24:28] = (used + 8).to_bytes(4, 'little')
        fixed[mapping:mapping + len(encoded)] = encoded
        module.write_file_record_logical(handle, volume, journal_record.number, fixed)
    elif mode == 'duplicate-owner':
        ordinary = locate_named_record(volume, '$Ordinary0')
        logical = module.read_file_record_logical(volume, ordinary.number)
        attribute = locate_attribute_offset(logical, module.AT_DATA)
        mapping = attribute + module.u16(logical, attribute + 32)
        header = logical[mapping]
        length_width = header & 0x0F
        offset_width = header >> 4
        first_lcn = journal_runs[0].lcn
        if offset_width == 0 or first_lcn is None:
            raise SystemExit('ordinary owner fixture lacks a mapped first run')
        patch_start = mapping + 1 + length_width
        patch = int(first_lcn).to_bytes(offset_width, 'little', signed=True)
        logical[patch_start:patch_start + len(patch)] = patch
        module.write_file_record_logical(handle, volume, ordinary.number, logical)
    elif mode == 'overlap-protected':
        record_offset = journal_record.number * volume.record_size
        raw = volume.read_stream(volume.mft_runs, record_offset, volume.record_size)
        fixed = volume.apply_fixups(raw)
        attribute = locate_attribute_offset(fixed, module.AT_DATA)
        mapping = attribute + module.u16(fixed, attribute + 32)
        header = fixed[mapping]
        length_width = header & 0x0F
        offset_width = header >> 4
        if offset_width == 0:
            raise SystemExit('journal fixture has a sparse first run')
        patch_start = mapping + 1 + length_width
        patch = int(volume.mft_lcn).to_bytes(offset_width, 'little', signed=True)
        assert_not_fixup_tail(volume, range(patch_start, patch_start + len(patch)))
        write_stream(
            handle,
            volume,
            volume.mft_runs,
            record_offset + patch_start,
            patch,
        )
    elif mode == 'duplicate-name':
        duplicate = locate_named_record(volume, '$Duplicate0')
        record_offset = duplicate.number * volume.record_size
        raw = volume.read_stream(volume.mft_runs, record_offset, volume.record_size)
        fixed = volume.apply_fixups(raw)
        attribute = locate_attribute_offset(fixed, module.AT_FILE_NAME)
        value_offset = module.u16(fixed, attribute + 20)
        name_length_offset = attribute + value_offset + 64
        name_offset = attribute + value_offset + 66
        old_length = fixed[name_length_offset]
        replacement = '$RootHealth'.encode('utf-16le')
        if old_length * 2 != len(replacement):
            raise SystemExit('duplicate-name fixture does not have an equal-length source')
        assert_not_fixup_tail(volume, range(name_offset, name_offset + len(replacement)))
        write_stream(
            handle,
            volume,
            volume.mft_runs,
            record_offset + name_offset,
            replacement,
        )
    else:
        raise SystemExit(f'unknown negative-fixture mutation: {mode}')
    handle.flush()
    os.fsync(handle.fileno())
