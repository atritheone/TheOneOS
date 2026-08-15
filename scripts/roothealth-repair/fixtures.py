#!/usr/bin/env python3
"""Create and inspect deterministic NTFS repair fixtures without Windows.

The helper intentionally supports only the mkfs.ntfs images created by the
roothealth repair qualification harness.  Every raw mutation checks the
structure it expects before changing bytes, so a tool or layout change fails
fixture construction instead of silently producing a different corruption.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
import sys
from typing import BinaryIO, Iterable


AT_STANDARD_INFORMATION = 0x10
AT_ATTRIBUTE_LIST = 0x20
AT_FILE_NAME = 0x30
AT_VOLUME_NAME = 0x60
AT_VOLUME_INFORMATION = 0x70
AT_DATA = 0x80
AT_INDEX_ROOT = 0x90
AT_INDEX_ALLOCATION = 0xA0
AT_BITMAP = 0xB0
AT_REPARSE_POINT = 0xC0
AT_FIRST_USER_DEFINED_ATTRIBUTE = 0x1000
AT_END = 0xFFFFFFFF

ATTR_IS_COMPRESSED = 0x0001
ATTR_IS_SPARSE = 0x8000

FILE_NAME_CACHED_FIELDS = {
    "timestamps": (8, 32),
    "allocated-size": (40, 8),
    "data-size": (48, 8),
    "file-attributes": (56, 4),
    "ea-reparse": (60, 4),
}
FILE_NAME_CACHED_KINDS = tuple(
    f"file-name-cached-{name}" for name in FILE_NAME_CACHED_FIELDS
)
FILE_NAME_STABLE_KINDS = (
    "file-name-stable-parent",
    "file-name-stable-sequence",
    "file-name-stable-flags",
)
POSIX_COLLISION_KINDS = (
    "posix-collision-exact-duplicate",
    "posix-collision-mixed-namespace",
    "posix-collision-duplicate-reference",
    "posix-collision-required-anchor",
)

FILE_MFT = 0
FILE_LOGFILE = 2
FILE_VOLUME = 3
FILE_ATTRDEF = 4
FILE_BITMAP = 6
FILE_SECURE = 9
FILE_UPCASE = 10
FILE_REPARSE = 26


class FixtureError(RuntimeError):
    pass


@dataclass(frozen=True)
class Geometry:
    sector_size: int
    sectors_per_cluster: int
    cluster_size: int
    total_sectors: int
    total_clusters: int
    mft_lcn: int
    mftmirr_lcn: int
    record_size: int

    @property
    def primary_mft_offset(self) -> int:
        return self.mft_lcn * self.cluster_size

    @property
    def mirror_mft_offset(self) -> int:
        return self.mftmirr_lcn * self.cluster_size

    @property
    def backup_boot_offset(self) -> int:
        return self.total_sectors * self.sector_size

    @property
    def mirror_records(self) -> int:
        return max(4, self.cluster_size // self.record_size)


@dataclass(frozen=True)
class Attribute:
    type: int
    name: str
    nonresident: bool
    record_offset: int
    record_length: int
    value_offset: int | None
    value_length: int | None
    data_size: int
    initialized_size: int
    runs: tuple[tuple[int, int | None, int], ...]
    instance: int
    flags: int
    lowest_vcn: int
    mapping_offset: int | None
    allocated_size: int
    compressed_size: int
    compression_unit: int


def _read_exact(handle: BinaryIO, offset: int, length: int) -> bytes:
    handle.seek(offset)
    data = handle.read(length)
    if len(data) != length:
        raise FixtureError(
            f"short fixture read at byte {offset}: wanted {length}, got {len(data)}"
        )
    return data


def _write_exact(handle: BinaryIO, offset: int, data: bytes) -> None:
    handle.seek(offset)
    written = handle.write(data)
    if written != len(data):
        raise FixtureError(
            f"short fixture write at byte {offset}: wanted {len(data)}, got {written}"
        )


def geometry(handle: BinaryIO) -> Geometry:
    boot = _read_exact(handle, 0, 512)
    if boot[3:11] != b"NTFS    " or boot[510:512] != b"\x55\xaa":
        raise FixtureError("fixture does not have a valid primary NTFS boot sector")
    sector_size = struct.unpack_from("<H", boot, 11)[0]
    sectors_per_cluster = boot[13]
    total_sectors = struct.unpack_from("<Q", boot, 40)[0]
    mft_lcn = struct.unpack_from("<Q", boot, 48)[0]
    mftmirr_lcn = struct.unpack_from("<Q", boot, 56)[0]
    record_code = struct.unpack_from("<b", boot, 64)[0]
    if sector_size not in (512, 1024, 2048, 4096):
        raise FixtureError(f"unsupported fixture sector size {sector_size}")
    if not sectors_per_cluster:
        raise FixtureError("fixture has zero sectors per cluster")
    cluster_size = sector_size * sectors_per_cluster
    record_size = 1 << -record_code if record_code < 0 else record_code * cluster_size
    if record_size < sector_size or record_size > 65536:
        raise FixtureError(f"unsupported fixture MFT record size {record_size}")
    if total_sectors < sectors_per_cluster:
        raise FixtureError("fixture reports an empty NTFS volume")
    return Geometry(
        sector_size=sector_size,
        sectors_per_cluster=sectors_per_cluster,
        cluster_size=cluster_size,
        total_sectors=total_sectors,
        total_clusters=total_sectors // sectors_per_cluster,
        mft_lcn=mft_lcn,
        mftmirr_lcn=mftmirr_lcn,
        record_size=record_size,
    )


def mst_decode(raw: bytes, sector_size: int, magic: bytes) -> bytearray:
    logical = bytearray(raw)
    if logical[:4] != magic:
        raise FixtureError(f"expected {magic!r} record, found {bytes(logical[:4])!r}")
    usa_offset, usa_count = struct.unpack_from("<HH", logical, 4)
    if (
        usa_offset < 8
        or usa_count < 2
        or usa_offset + usa_count * 2 > len(logical)
        or (usa_count - 1) * sector_size != len(logical)
    ):
        raise FixtureError("invalid update-sequence array")
    sequence = logical[usa_offset : usa_offset + 2]
    for index in range(1, usa_count):
        trailer = index * sector_size - 2
        if logical[trailer : trailer + 2] != sequence:
            raise FixtureError("update-sequence trailer mismatch")
        replacement = usa_offset + index * 2
        logical[trailer : trailer + 2] = logical[replacement : replacement + 2]
    return logical


def mst_encode(logical: bytes, sector_size: int) -> bytes:
    protected = bytearray(logical)
    usa_offset, usa_count = struct.unpack_from("<HH", protected, 4)
    if (
        usa_offset < 8
        or usa_count < 2
        or usa_offset + usa_count * 2 > len(protected)
        or (usa_count - 1) * sector_size != len(protected)
    ):
        raise FixtureError("cannot protect record with invalid update-sequence array")
    sequence = (struct.unpack_from("<H", protected, usa_offset)[0] + 1) & 0xFFFF
    if not sequence:
        sequence = 1
    struct.pack_into("<H", protected, usa_offset, sequence)
    sequence_bytes = struct.pack("<H", sequence)
    for index in range(1, usa_count):
        trailer = index * sector_size - 2
        replacement = usa_offset + index * 2
        protected[replacement : replacement + 2] = protected[trailer : trailer + 2]
        protected[trailer : trailer + 2] = sequence_bytes
    return bytes(protected)


def _decode_runlist(
    record: bytes, mapping_offset: int, lowest_vcn: int
) -> tuple[tuple[int, int | None, int], ...]:
    cursor = mapping_offset
    current_vcn = lowest_vcn
    current_lcn = 0
    runs: list[tuple[int, int | None, int]] = []
    while True:
        if cursor >= len(record):
            raise FixtureError("unterminated mapping-pairs array")
        header = record[cursor]
        cursor += 1
        if not header:
            break
        length_width = header & 0x0F
        offset_width = header >> 4
        if not length_width or length_width > 8 or offset_width > 8:
            raise FixtureError("invalid mapping-pair widths")
        if cursor + length_width + offset_width > len(record):
            raise FixtureError("mapping pair exceeds attribute record")
        run_length = int.from_bytes(
            record[cursor : cursor + length_width], "little", signed=False
        )
        cursor += length_width
        if not run_length:
            raise FixtureError("zero-length mapping pair")
        lcn: int | None
        if offset_width:
            delta = int.from_bytes(
                record[cursor : cursor + offset_width], "little", signed=True
            )
            current_lcn += delta
            if current_lcn < 0:
                raise FixtureError("negative fixture LCN")
            lcn = current_lcn
        else:
            lcn = None
        cursor += offset_width
        runs.append((current_vcn, lcn, run_length))
        current_vcn += run_length
    if not runs:
        raise FixtureError("fixture attribute has an empty runlist")
    return tuple(runs)


def attributes(record: bytes) -> Iterable[Attribute]:
    offset = struct.unpack_from("<H", record, 20)[0]
    while offset + 4 <= len(record):
        attr_type = struct.unpack_from("<I", record, offset)[0]
        if attr_type == 0xFFFFFFFF:
            return
        if offset + 24 > len(record):
            raise FixtureError("truncated MFT attribute header")
        length = struct.unpack_from("<I", record, offset + 4)[0]
        if length < 24 or offset + length > len(record):
            raise FixtureError("attribute record exceeds MFT record")
        nonresident = bool(record[offset + 8])
        name_length = record[offset + 9]
        name_offset = struct.unpack_from("<H", record, offset + 10)[0]
        name = ""
        if name_length:
            name_end = name_offset + name_length * 2
            if name_offset < 24 or name_end > length:
                raise FixtureError("attribute name exceeds attribute record")
            name = record[
                offset + name_offset : offset + name_end
            ].decode("utf-16-le")
        if nonresident:
            if length < 64:
                raise FixtureError("nonresident attribute record is too short")
            lowest_vcn = struct.unpack_from("<Q", record, offset + 16)[0]
            mapping_pairs = struct.unpack_from("<H", record, offset + 32)[0]
            if mapping_pairs < 64 or mapping_pairs >= length:
                raise FixtureError("invalid mapping-pairs offset")
            data_size = struct.unpack_from("<Q", record, offset + 48)[0]
            initialized_size = struct.unpack_from("<Q", record, offset + 56)[0]
            allocated_size = struct.unpack_from("<Q", record, offset + 40)[0]
            flags = struct.unpack_from("<H", record, offset + 12)[0]
            compression_unit = record[offset + 34]
            if flags & (ATTR_IS_COMPRESSED | ATTR_IS_SPARSE):
                if length < 72:
                    raise FixtureError(
                        "compressed or sparse attribute record is too short"
                    )
                compressed_size = struct.unpack_from("<Q", record, offset + 64)[0]
            else:
                compressed_size = allocated_size
            runs = _decode_runlist(
                record[offset : offset + length], mapping_pairs, lowest_vcn
            )
            value_offset = None
            value_length = None
            mapping_offset: int | None = offset + mapping_pairs
        else:
            value_length = struct.unpack_from("<I", record, offset + 16)[0]
            relative_value_offset = struct.unpack_from("<H", record, offset + 20)[0]
            if relative_value_offset < 24 or relative_value_offset + value_length > length:
                raise FixtureError("resident attribute value exceeds attribute record")
            value_offset = offset + relative_value_offset
            data_size = value_length
            initialized_size = value_length
            runs = ()
            flags = struct.unpack_from("<H", record, offset + 12)[0]
            lowest_vcn = 0
            mapping_offset = None
            allocated_size = value_length
            compressed_size = value_length
            compression_unit = 0
        yield Attribute(
            type=attr_type,
            name=name,
            nonresident=nonresident,
            record_offset=offset,
            record_length=length,
            value_offset=value_offset,
            value_length=value_length,
            data_size=data_size,
            initialized_size=initialized_size,
            runs=runs,
            instance=struct.unpack_from("<H", record, offset + 14)[0],
            flags=flags,
            lowest_vcn=lowest_vcn,
            mapping_offset=mapping_offset,
            allocated_size=allocated_size,
            compressed_size=compressed_size,
            compression_unit=compression_unit,
        )
        offset += length
    raise FixtureError("MFT attribute list has no end marker")


def find_attribute(record: bytes, attr_type: int, name: str = "") -> Attribute:
    for attr in attributes(record):
        if attr.type == attr_type and attr.name == name:
            return attr
    raise FixtureError(f"attribute 0x{attr_type:x} {name!r} is absent")


def _stream_segments(
    attr: Attribute, geometry_: Geometry, offset: int, length: int
) -> Iterable[tuple[int | None, int]]:
    if not attr.nonresident:
        raise FixtureError("fixture operation requires a nonresident attribute")
    if offset < 0 or length < 0 or offset + length > attr.data_size:
        raise FixtureError("attribute stream range is out of bounds")
    cursor = offset
    remaining = length
    for vcn, lcn, run_length in attr.runs:
        run_start = vcn * geometry_.cluster_size
        run_end = run_start + run_length * geometry_.cluster_size
        if cursor >= run_end:
            continue
        if cursor < run_start:
            raise FixtureError("attribute runlist has a gap")
        amount = min(remaining, run_end - cursor)
        disk_offset = None
        if lcn is not None:
            disk_offset = lcn * geometry_.cluster_size + (cursor - run_start)
        yield disk_offset, amount
        cursor += amount
        remaining -= amount
        if not remaining:
            return
    raise FixtureError("attribute runlist does not cover requested range")


def read_stream(
    handle: BinaryIO, geometry_: Geometry, attr: Attribute, offset: int, length: int
) -> bytes:
    parts: list[bytes] = []
    for disk_offset, amount in _stream_segments(attr, geometry_, offset, length):
        parts.append(
            bytes(amount) if disk_offset is None else _read_exact(handle, disk_offset, amount)
        )
    return b"".join(parts)


def write_stream(
    handle: BinaryIO, geometry_: Geometry, attr: Attribute, offset: int, data: bytes
) -> None:
    consumed = 0
    for disk_offset, amount in _stream_segments(attr, geometry_, offset, len(data)):
        if disk_offset is None:
            raise FixtureError("refusing to write a sparse fixture run")
        _write_exact(handle, disk_offset, data[consumed : consumed + amount])
        consumed += amount
    if consumed != len(data):
        raise FixtureError("fixture attribute write was incomplete")


def _raw_record_zero(handle: BinaryIO, geometry_: Geometry) -> bytes:
    return _read_exact(handle, geometry_.primary_mft_offset, geometry_.record_size)


def _primary_record_offset(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> int:
    if inode < 0:
        raise FixtureError("negative MFT record number")
    record_zero = mst_decode(
        _raw_record_zero(handle, geometry_), geometry_.sector_size, b"FILE"
    )
    mft_data = find_attribute(record_zero, AT_DATA)
    logical_offset = inode * geometry_.record_size
    segments = list(
        _stream_segments(mft_data, geometry_, logical_offset, geometry_.record_size)
    )
    if len(segments) != 1 or segments[0][0] is None or segments[0][1] != geometry_.record_size:
        raise FixtureError("fixture MFT record is not physically contiguous")
    return int(segments[0][0])


def read_record(
    handle: BinaryIO, geometry_: Geometry, inode: int, *, mirror: bool = False
) -> tuple[int, bytes, bytearray]:
    if mirror:
        if inode >= geometry_.mirror_records:
            raise FixtureError("requested MFT record is outside $MFTMirr")
        offset = geometry_.mirror_mft_offset + inode * geometry_.record_size
    else:
        offset = _primary_record_offset(handle, geometry_, inode)
    raw = _read_exact(handle, offset, geometry_.record_size)
    logical = mst_decode(raw, geometry_.sector_size, b"FILE")
    return offset, raw, logical


def write_record(
    handle: BinaryIO,
    geometry_: Geometry,
    inode: int,
    logical: bytes,
    *,
    mirror: bool = False,
) -> None:
    if mirror:
        if inode >= geometry_.mirror_records:
            raise FixtureError("requested MFT record is outside $MFTMirr")
        offset = geometry_.mirror_mft_offset + inode * geometry_.record_size
    else:
        offset = _primary_record_offset(handle, geometry_, inode)
    _write_exact(handle, offset, mst_encode(logical, geometry_.sector_size))


def _system_stream(
    handle: BinaryIO,
    geometry_: Geometry,
    inode: int,
    attr_type: int,
    name: str = "",
) -> Attribute:
    _, _, record = read_record(handle, geometry_, inode)
    return find_attribute(record, attr_type, name)


def _read_bitmap_bit(
    handle: BinaryIO, geometry_: Geometry, attr: Attribute, bit: int
) -> bool:
    byte = read_stream(handle, geometry_, attr, bit // 8, 1)[0]
    return bool(byte & (1 << (bit % 8)))


def _write_bitmap_bit(
    handle: BinaryIO, geometry_: Geometry, attr: Attribute, bit: int, value: bool
) -> None:
    byte_offset = bit // 8
    current = read_stream(handle, geometry_, attr, byte_offset, 1)[0]
    mask = 1 << (bit % 8)
    changed = current | mask if value else current & ~mask
    if changed == current:
        raise FixtureError(
            f"fixture bitmap bit {bit} is already {'set' if value else 'clear'}"
        )
    write_stream(handle, geometry_, attr, byte_offset, bytes((changed,)))


def set_dirty_and_unclean_log(handle: BinaryIO, geometry_: Geometry) -> dict[str, object]:
    set_volume_dirty(handle, geometry_)

    logfile = _system_stream(handle, geometry_, FILE_LOGFILE, AT_DATA)
    page_size = 4096
    if logfile.data_size < page_size * 50:
        raise FixtureError("$LogFile is too small for a valid restart area")

    def restart_page(sequence: int) -> bytes:
        page = bytearray(page_size)
        usa_offset = 32
        usa_count = 1 + page_size // 512
        restart_offset = 56
        client_offset = 64
        client_size = 160
        restart_length = client_offset + client_size
        page[0:4] = b"RSTR"
        struct.pack_into(
            "<HHQIIHhhH",
            page,
            4,
            usa_offset,
            usa_count,
            0,
            page_size,
            page_size,
            restart_offset,
            1,
            1,
            0,
        )
        seq_bits = 67 - logfile.data_size.bit_length()
        struct.pack_into(
            "<QHHHHIHHQIH HII",
            page,
            restart_offset,
            0,
            1,
            0xFFFF,
            0,
            0,
            seq_bits,
            restart_length,
            client_offset,
            logfile.data_size,
            0,
            48,
            64,
            1,
            0,
        )
        client = restart_offset + client_offset
        struct.pack_into("<QQHHH6xI", page, client, 0, 0, 0xFFFF, 0xFFFF, 0, 8)
        page[client + 32 : client + 40] = "NTFS".encode("utf-16-le")
        struct.pack_into("<H", page, usa_offset, sequence)
        for index in range(1, usa_count):
            trailer = index * 512 - 2
            struct.pack_into(
                "<H", page, usa_offset + index * 2, struct.unpack_from("<H", page, trailer)[0]
            )
            struct.pack_into("<H", page, trailer, sequence)
        return bytes(page)

    write_stream(handle, geometry_, logfile, 0, restart_page(0xA101))
    write_stream(handle, geometry_, logfile, page_size, restart_page(0xA102))
    return {
        "kind": "dirty-log",
        "logfile_size": logfile.data_size,
        "restart_page_size": page_size,
        "transactions": 0,
        "redo_actions": 0,
    }


def set_volume_dirty(handle: BinaryIO, geometry_: Geometry) -> dict[str, object]:
    changed_flags: int | None = None
    for mirror in (False, True):
        _, _, volume_record = read_record(
            handle, geometry_, FILE_VOLUME, mirror=mirror
        )
        volume_information = find_attribute(volume_record, AT_VOLUME_INFORMATION)
        assert volume_information.value_offset is not None
        assert volume_information.value_length is not None
        if volume_information.value_length < 12:
            raise FixtureError("$VOLUME_INFORMATION is too short")
        flags_offset = volume_information.value_offset + 10
        flags = struct.unpack_from("<H", volume_record, flags_offset)[0]
        if flags & 1:
            raise FixtureError("fixture volume is already dirty")
        struct.pack_into("<H", volume_record, flags_offset, flags | 1)
        write_record(
            handle, geometry_, FILE_VOLUME, volume_record, mirror=mirror
        )
        changed_flags = flags | 1
    return {
        "kind": "volume-dirty-only",
        "flags": changed_flags,
    }


def set_dirty_with_wiped_log(handle: BinaryIO, geometry_: Geometry) -> dict[str, object]:
    state = set_volume_dirty(handle, geometry_)
    _, _, logfile_record = read_record(handle, geometry_, FILE_LOGFILE)
    logfile = find_attribute(logfile_record, AT_DATA)
    if not logfile.nonresident or logfile.data_size <= 0:
        raise FixtureError("$LogFile fixture is not a nonresident stream")
    chunk_size = 1024 * 1024
    offset = 0
    while offset < logfile.data_size:
        amount = min(chunk_size, logfile.data_size - offset)
        write_stream(handle, geometry_, logfile, offset, b"\xff" * amount)
        offset += amount
    state.update(
        {
            "kind": "volume-dirty-wiped-log",
            "logfile_size": logfile.data_size,
            "logfile_fill": "ff",
        }
    )
    return state


def corrupt_boot(handle: BinaryIO, geometry_: Geometry, primary: bool) -> dict[str, object]:
    offset = 0 if primary else geometry_.backup_boot_offset
    sector = bytearray(_read_exact(handle, offset, geometry_.sector_size))
    if sector[3:11] != b"NTFS    " or sector[510:512] != b"\x55\xaa":
        raise FixtureError("target boot sector is not pristine NTFS")
    changed_offset = 3 if primary else 72
    sector[changed_offset] ^= 0x5A
    _write_exact(handle, offset, sector)
    return {
        "kind": "boot-primary" if primary else "boot-backup",
        "offset": offset + changed_offset,
        "length": 1,
    }


def corrupt_mft_copy(handle: BinaryIO, geometry_: Geometry, primary: bool) -> dict[str, object]:
    base = geometry_.primary_mft_offset if primary else geometry_.mirror_mft_offset
    raw = bytearray(_read_exact(handle, base, geometry_.record_size))
    mst_decode(raw, geometry_.sector_size, b"FILE")
    changed_offset = geometry_.sector_size - 2
    raw[changed_offset] ^= 0x5A
    _write_exact(handle, base, raw)
    return {
        "kind": "mft-primary" if primary else "mft-mirror",
        "record": 0,
        "offset": base + changed_offset,
        "length": 1,
    }


def corrupt_bitmaps(
    handle: BinaryIO, geometry_: Geometry, allocated_inode: int, live_inode: int
) -> dict[str, object]:
    if allocated_inode < 24 or live_inode < 24:
        raise FixtureError("bitmap fixture refuses bootstrap/system MFT records")
    _, _, allocated_record = read_record(handle, geometry_, allocated_inode)
    data = find_attribute(allocated_record, AT_DATA)
    allocated_clusters = [
        lcn
        for _, start_lcn, length in data.runs
        if start_lcn is not None
        for lcn in range(start_lcn, start_lcn + length)
    ]
    if not allocated_clusters:
        raise FixtureError("allocated fixture file has no nonresident data clusters")
    cluster_bitmap = _system_stream(handle, geometry_, FILE_BITMAP, AT_DATA)
    cluster_pair = None
    for allocated_cluster in allocated_clusters:
        if not _read_bitmap_bit(handle, geometry_, cluster_bitmap, allocated_cluster):
            raise FixtureError("fixture payload cluster is not allocated in $Bitmap")
        byte_first = allocated_cluster & ~7
        for free_cluster in range(byte_first, min(byte_first + 8, geometry_.total_clusters)):
            if free_cluster != allocated_cluster and not _read_bitmap_bit(
                handle, geometry_, cluster_bitmap, free_cluster
            ):
                cluster_pair = (allocated_cluster, free_cluster)
                break
        if cluster_pair is not None:
            break
    if cluster_pair is None:
        raise FixtureError(
            "fixture has no referenced/free cluster pair in one bitmap byte"
        )
    allocated_cluster, free_cluster = cluster_pair
    cluster_byte = allocated_cluster // 8
    cluster_before = read_stream(
        handle, geometry_, cluster_bitmap, cluster_byte, 1
    )[0]
    cluster_set_mask = 1 << (allocated_cluster & 7)
    cluster_clear_mask = 1 << (free_cluster & 7)
    if cluster_before & cluster_set_mask == 0 or cluster_before & cluster_clear_mask:
        raise FixtureError("cluster bitmap pair does not have exact live/free truth")
    cluster_corrupt = (cluster_before & ~cluster_set_mask) | cluster_clear_mask
    cluster_segments = list(
        _stream_segments(cluster_bitmap, geometry_, cluster_byte, 1)
    )
    if len(cluster_segments) != 1 or cluster_segments[0][0] is None:
        raise FixtureError("cluster bitmap byte is not one physical byte")
    cluster_physical = int(cluster_segments[0][0])
    write_stream(
        handle, geometry_, cluster_bitmap, cluster_byte, bytes((cluster_corrupt,))
    )

    _, _, mft_record_zero = read_record(handle, geometry_, FILE_MFT)
    mft_bitmap = find_attribute(mft_record_zero, AT_BITMAP)
    mft_data = find_attribute(mft_record_zero, AT_DATA)
    mft_records = mft_data.initialized_size // geometry_.record_size
    if not _read_bitmap_bit(handle, geometry_, mft_bitmap, live_inode):
        raise FixtureError("live fixture inode is not allocated in the MFT bitmap")
    mft_pair = None
    preferred_bytes = [live_inode // 8] + [
        byte for byte in range((mft_records + 7) // 8) if byte != live_inode // 8
    ]
    for byte in preferred_bytes:
        live_candidates: list[int] = []
        free_candidates: list[int] = []
        for inode in range(max(byte * 8, 24), min(byte * 8 + 8, mft_records)):
            try:
                _, _, candidate = read_record(handle, geometry_, inode)
            except FixtureError:
                continue
            in_use = bool(struct.unpack_from("<H", candidate, 22)[0] & 1)
            bitmap_set = _read_bitmap_bit(handle, geometry_, mft_bitmap, inode)
            if bitmap_set and in_use:
                live_candidates.append(inode)
            elif not bitmap_set and not in_use:
                free_candidates.append(inode)
        if live_candidates and free_candidates:
            selected_live = (
                live_inode if live_inode in live_candidates else live_candidates[0]
            )
            mft_pair = (selected_live, free_candidates[0])
            break
    if mft_pair is None:
        raise FixtureError("fixture has no live/free MFT pair in one bitmap byte")
    selected_live, unused_inode = mft_pair
    mft_byte = selected_live // 8
    mft_before = read_stream(handle, geometry_, mft_bitmap, mft_byte, 1)[0]
    mft_set_mask = 1 << (selected_live & 7)
    mft_clear_mask = 1 << (unused_inode & 7)
    if mft_before & mft_set_mask == 0 or mft_before & mft_clear_mask:
        raise FixtureError("MFT bitmap pair does not have exact live/free truth")
    mft_corrupt = (mft_before & ~mft_set_mask) | mft_clear_mask
    mft_segments = list(_stream_segments(mft_bitmap, geometry_, mft_byte, 1))
    if len(mft_segments) != 1 or mft_segments[0][0] is None:
        raise FixtureError("MFT bitmap byte is not one physical byte")
    mft_physical = int(mft_segments[0][0])
    write_stream(handle, geometry_, mft_bitmap, mft_byte, bytes((mft_corrupt,)))
    return {
        "kind": "bitmaps",
        "allocated_cluster_cleared": allocated_cluster,
        "free_cluster_set": free_cluster,
        "cluster_bitmap_byte": cluster_byte,
        "cluster_bitmap_physical_offset": cluster_physical,
        "cluster_bitmap_before": cluster_before,
        "cluster_bitmap_corrupt": cluster_corrupt,
        "cluster_set_mask": cluster_set_mask,
        "cluster_clear_mask": cluster_clear_mask,
        "live_inode_cleared": selected_live,
        "unused_inode_set": unused_inode,
        "mft_bitmap_byte": mft_byte,
        "mft_bitmap_physical_offset": mft_physical,
        "mft_bitmap_before": mft_before,
        "mft_bitmap_corrupt": mft_corrupt,
        "mft_set_mask": mft_set_mask,
        "mft_clear_mask": mft_clear_mask,
    }


def _journal_layout(
    handle: BinaryIO, geometry_: Geometry, layout_path: Path
) -> tuple[dict[str, object], int, int, tuple[tuple[int, int | None, int], ...]]:
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    if layout.get("format") != 1 or layout.get("state") != "structurally-valid":
        raise FixtureError("journal layout is not a validated format-1 report")
    device = layout.get("device")
    journal = layout.get("journal")
    if not isinstance(device, dict) or not isinstance(journal, dict):
        raise FixtureError("journal layout lacks device/journal objects")
    if (
        device.get("cluster_size") != geometry_.cluster_size
        or device.get("total_clusters") != geometry_.total_clusters
    ):
        raise FixtureError("journal layout geometry differs from the target")
    boot = _read_exact(handle, 0, geometry_.sector_size)
    serial = f"{struct.unpack_from('<Q', boot, 72)[0]:016X}"
    if device.get("serial") != serial:
        raise FixtureError("journal layout serial differs from the target")
    record_number = journal.get("mft_record")
    sequence = journal.get("mft_sequence")
    raw_runs = journal.get("runs")
    if (
        not isinstance(record_number, int)
        or isinstance(record_number, bool)
        or record_number < 24
        or not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or sequence <= 0
        or not isinstance(raw_runs, list)
        or not raw_runs
    ):
        raise FixtureError("journal layout record identity is invalid")
    expected_runs: list[tuple[int, int | None, int]] = []
    for item in raw_runs:
        if not isinstance(item, dict):
            raise FixtureError("journal layout run is not an object")
        vcn, lcn, clusters = item.get("vcn"), item.get("lcn"), item.get("clusters")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (vcn, lcn, clusters)
        ) or clusters == 0:
            raise FixtureError("journal layout run is invalid")
        expected_runs.append((vcn, lcn, clusters))
    _, _, record = read_record(handle, geometry_, record_number)
    if struct.unpack_from("<H", record, 16)[0] != sequence:
        raise FixtureError("journal MFT sequence differs from the attested locator")
    data = find_attribute(record, AT_DATA)
    if not data.nonresident or data.name or data.runs != tuple(expected_runs):
        raise FixtureError("journal raw runlist differs from the validated layout")
    return layout, record_number, sequence, tuple(expected_runs)


def _journal_cluster_owners(
    handle: BinaryIO,
    geometry_: Geometry,
    journal_record: int,
    journal_runs: tuple[tuple[int, int | None, int], ...],
) -> tuple[dict[int, list[dict[str, object]]], int]:
    journal_clusters = {
        cluster
        for _, lcn, length in journal_runs
        if lcn is not None
        for cluster in range(lcn, lcn + length)
    }
    _, _, mft_zero = read_record(handle, geometry_, FILE_MFT)
    mft_data = find_attribute(mft_zero, AT_DATA)
    mft_bitmap = find_attribute(mft_zero, AT_BITMAP)
    record_count = mft_data.initialized_size // geometry_.record_size
    owners: dict[int, list[dict[str, object]]] = {
        cluster: [] for cluster in journal_clusters
    }
    examined = 0
    for inode in range(record_count):
        allocated = _read_bitmap_bit(handle, geometry_, mft_bitmap, inode)
        if not allocated and inode != journal_record:
            continue
        try:
            _, _, record = read_record(handle, geometry_, inode)
        except FixtureError as error:
            raise FixtureError(
                f"full MFT ownership census cannot read allocated record {inode}: {error}"
            ) from error
        examined += 1
        for attr in attributes(record):
            if not attr.nonresident:
                continue
            for _, lcn, length in attr.runs:
                if lcn is None:
                    continue
                for cluster in range(lcn, lcn + length):
                    if cluster in owners:
                        owners[cluster].append(
                            {
                                "inode": inode,
                                "type": attr.type,
                                "name": attr.name,
                            }
                        )
    return owners, examined


def _require_unique_journal_owner(
    owners: dict[int, list[dict[str, object]]], journal_record: int
) -> None:
    for cluster, cluster_owners in owners.items():
        if cluster_owners != [
            {"inode": journal_record, "type": AT_DATA, "name": ""}
        ]:
            raise FixtureError(
                f"journal cluster {cluster} does not have one exact owner: {cluster_owners!r}"
            )


def corrupt_journal_allocation(
    handle: BinaryIO,
    geometry_: Geometry,
    layout_path: Path,
    allocation: str,
) -> dict[str, object]:
    _, record_number, sequence, runs = _journal_layout(
        handle, geometry_, layout_path
    )
    owners, examined = _journal_cluster_owners(
        handle, geometry_, record_number, runs
    )
    _require_unique_journal_owner(owners, record_number)
    _, _, mft_zero = read_record(handle, geometry_, FILE_MFT)
    mft_bitmap = find_attribute(mft_zero, AT_BITMAP)
    cluster_bitmap = _system_stream(handle, geometry_, FILE_BITMAP, AT_DATA)
    journal_cluster = next(
        lcn for _, lcn, _ in runs if lcn is not None
    )
    if allocation == "mft":
        if not _read_bitmap_bit(handle, geometry_, mft_bitmap, record_number):
            raise FixtureError("journal MFT bitmap bit is already clear")
        _write_bitmap_bit(handle, geometry_, mft_bitmap, record_number, False)
    elif allocation == "cluster":
        if not _read_bitmap_bit(handle, geometry_, cluster_bitmap, journal_cluster):
            raise FixtureError("journal cluster bitmap bit is already clear")
        _write_bitmap_bit(handle, geometry_, cluster_bitmap, journal_cluster, False)
    else:
        raise FixtureError(f"unsupported journal allocation class {allocation}")
    return {
        "kind": f"journal-{allocation}-false-free",
        "allocation": allocation,
        "journal_record": record_number,
        "journal_sequence": sequence,
        "journal_cluster": journal_cluster,
        "journal_runs": runs,
        "ownership_records_examined": examined,
        "unique_owner": True,
    }


def overlap_file_with_journal(
    handle: BinaryIO,
    geometry_: Geometry,
    layout_path: Path,
    inode: int,
) -> dict[str, object]:
    _, journal_record, _, journal_runs = _journal_layout(
        handle, geometry_, layout_path
    )
    owners, examined = _journal_cluster_owners(
        handle, geometry_, journal_record, journal_runs
    )
    _require_unique_journal_owner(owners, journal_record)
    journal_lcn = next(lcn for _, lcn, _ in journal_runs if lcn is not None)
    _, _, record = read_record(handle, geometry_, inode)
    data = find_attribute(record, AT_DATA)
    if (
        not data.nonresident
        or data.name
        or data.mapping_offset is None
        or len(data.runs) != 1
        or data.runs[0][1] is None
        or data.runs[0][2] != 1
    ):
        raise FixtureError("journal overlap file is not one exact allocated run")
    original_lcn = data.runs[0][1]
    assert original_lcn is not None
    encoded = encode_mapping_pairs(
        ((data.runs[0][0], journal_lcn, 1),), data.lowest_vcn
    )
    attribute_end = data.record_offset + data.record_length
    capacity = attribute_end - data.mapping_offset
    if len(encoded) > capacity:
        raise FixtureError("journal overlap mapping pairs do not fit the attribute")
    record[data.mapping_offset:attribute_end] = bytes(capacity)
    record[data.mapping_offset:data.mapping_offset + len(encoded)] = encoded
    write_record(handle, geometry_, inode, record)
    return {
        "overlap_inode": inode,
        "overlap_original_lcn": original_lcn,
        "overlap_journal_lcn": journal_lcn,
        "ownership_records_examined": examined,
    }


def corrupt_index(
    handle: BinaryIO,
    geometry_: Geometry,
    inode: int,
    allocation_inode: int | None = None,
) -> dict[str, object]:
    _, _, record = read_record(handle, geometry_, inode)
    index_root = find_attribute(record, AT_INDEX_ROOT, "$I30")
    assert index_root.value_offset is not None
    assert index_root.value_length is not None
    if index_root.value_length < 16:
        raise FixtureError("$INDEX_ROOT value is too short")
    index_block_size = struct.unpack_from("<I", record, index_root.value_offset + 8)[0]
    if index_block_size < 512 or index_block_size > 65536:
        raise FixtureError("fixture index block size is invalid before mutation")
    allocation_record_number = inode if allocation_inode is None else allocation_inode
    _, _, allocation_record = read_record(
        handle, geometry_, allocation_record_number
    )
    allocation = find_attribute(allocation_record, AT_INDEX_ALLOCATION, "$I30")
    first = read_stream(handle, geometry_, allocation, 0, index_block_size)
    mst_decode(first, geometry_.sector_size, b"INDX")
    changed_offset = geometry_.sector_size - 2
    changed = bytes((first[changed_offset] ^ 0x5A,))
    write_stream(handle, geometry_, allocation, changed_offset, changed)
    return {
        "kind": "index-i30",
        "inode": inode,
        "allocation_inode": allocation_record_number,
        "block": 0,
        "index_block_size": index_block_size,
        "changed_stream_offset": changed_offset,
    }


def corrupt_index_bitmap_set(
    handle: BinaryIO,
    geometry_: Geometry,
    inode: int,
) -> dict[str, object]:
    _, _, record = read_record(handle, geometry_, inode)
    bitmap = find_attribute(record, AT_BITMAP, "$I30")
    if bitmap.nonresident:
        bitmap_size = bitmap.initialized_size
        value = bytearray(read_stream(handle, geometry_, bitmap, 0, bitmap_size))
    else:
        if bitmap.value_offset is None or bitmap.value_length is None:
            raise FixtureError("resident $I30 bitmap has no bounded value")
        bitmap_size = bitmap.value_length
        value = bytearray(
            record[bitmap.value_offset : bitmap.value_offset + bitmap.value_length]
        )
    selected_byte = selected_mask = None
    for byte_offset, byte in enumerate(value):
        if byte:
            selected_byte = byte_offset
            selected_mask = byte & -byte
            break
    if selected_byte is None or selected_mask is None:
        raise FixtureError("$I30 bitmap has no allocated block to false-clear")
    before = value[selected_byte]
    value[selected_byte] &= ~selected_mask
    if bitmap.nonresident:
        write_stream(
            handle,
            geometry_,
            bitmap,
            selected_byte,
            bytes((value[selected_byte],)),
        )
    else:
        assert bitmap.value_offset is not None
        record[bitmap.value_offset + selected_byte] = value[selected_byte]
        write_record(handle, geometry_, inode, record)
    return {
        "kind": "index-bitmap-set",
        "inode": inode,
        "bitmap_byte": selected_byte,
        "set_mask": selected_mask,
        "before": before,
        "corrupt": value[selected_byte],
        "resident": not bitmap.nonresident,
    }


def index_entries(index: bytes | bytearray, header_offset: int) -> Iterable[dict[str, object]]:
    if header_offset < 0 or header_offset + 16 > len(index):
        raise FixtureError("$I30 index header is out of bounds")
    entries_offset, index_length, allocated_size = struct.unpack_from(
        "<III", index, header_offset
    )
    if (
        entries_offset < 16
        or index_length < entries_offset
        or index_length > allocated_size
        or header_offset + index_length > len(index)
    ):
        raise FixtureError("$I30 index entry bounds are invalid")
    cursor = header_offset + entries_offset
    end = header_offset + index_length
    while cursor + 16 <= end:
        reference = struct.unpack_from("<Q", index, cursor)[0]
        length, key_length, flags = struct.unpack_from("<HHH", index, cursor + 8)
        if length < 16 or length % 8 or cursor + length > end:
            raise FixtureError("$I30 entry length is invalid")
        if flags & 2:
            return
        if key_length < 66 or 16 + key_length > length:
            raise FixtureError("$I30 FILE_NAME key is invalid")
        key = cursor + 16
        name_length = index[key + 64]
        name_end = key + 66 + name_length * 2
        if name_end > cursor + 16 + key_length:
            raise FixtureError("$I30 filename exceeds its key")
        try:
            name = bytes(index[key + 66 : name_end]).decode("utf-16le")
        except UnicodeDecodeError as error:
            raise FixtureError("$I30 filename is invalid UTF-16") from error
        key_bytes = bytes(index[key : cursor + 16 + key_length])
        child_vcn_present = bool(flags & 1)
        child_vcn_bound = (
            not child_vcn_present or length >= 16 + key_length + 8
        )
        yield {
            "offset": cursor,
            "reference": reference,
            "name": name,
            "entry_length": length,
            "entry_flags": flags,
            "entry_flags_valid": not (flags & ~1) and child_vcn_bound,
            "child_vcn_present": child_vcn_present,
            "key_length": key_length,
            "key_parent_reference": struct.unpack_from("<Q", key_bytes, 0)[0],
            "key_namespace": key_bytes[65],
            "cached_timestamps_hex": key_bytes[8:40].hex(),
            "cached_allocated_size": struct.unpack_from("<Q", key_bytes, 40)[0],
            "cached_data_size": struct.unpack_from("<Q", key_bytes, 48)[0],
            "cached_file_attributes": struct.unpack_from("<I", key_bytes, 56)[0],
            "cached_ea_reparse": struct.unpack_from("<I", key_bytes, 60)[0],
            "key_hex": key_bytes.hex(),
            "key_sha256": hashlib.sha256(key_bytes).hexdigest(),
        }
        cursor += length
    raise FixtureError("$I30 index has no terminal entry")


def child_filename_valid(
    record: bytes, parent_inode: int, target_name: str
) -> bool:
    for attr in attributes(record):
        if attr.type != AT_FILE_NAME or attr.nonresident:
            continue
        assert attr.value_offset is not None and attr.value_length is not None
        value = record[attr.value_offset : attr.value_offset + attr.value_length]
        if len(value) < 66:
            continue
        name_length = value[64]
        if 66 + name_length * 2 > len(value):
            continue
        try:
            name = value[66 : 66 + name_length * 2].decode("utf-16le")
        except UnicodeDecodeError:
            continue
        parent = struct.unpack_from("<Q", value, 0)[0] & ((1 << 48) - 1)
        if parent == parent_inode and name == target_name:
            return True
    return False


def locate_index_reference(
    handle: BinaryIO,
    geometry_: Geometry,
    parent_inode: int,
    target_name: str,
    target_inode: int,
    allocation_inode: int | None,
    require_reference_valid: bool = True,
) -> dict[str, object]:
    _, _, parent_record = read_record(handle, geometry_, parent_inode)
    root = find_attribute(parent_record, AT_INDEX_ROOT, "$I30")
    if root.value_offset is None or root.value_length is None or root.value_length < 32:
        raise FixtureError("target parent has no usable resident $I30 root")
    matches: list[dict[str, object]] = []
    for item in index_entries(parent_record, root.value_offset + 16):
        if item["name"] == target_name:
            matches.append(
                {"kind": "record", "buffer": parent_record, "entry": item}
            )
    if allocation_inode is not None:
        _, _, allocation_record = read_record(handle, geometry_, allocation_inode)
        allocation = find_attribute(allocation_record, AT_INDEX_ALLOCATION, "$I30")
        index_block_size = struct.unpack_from("<I", parent_record, root.value_offset + 8)[0]
        if index_block_size < geometry_.sector_size or index_block_size > 65536:
            raise FixtureError("target parent has an invalid $I30 block size")
        for block_offset in range(0, allocation.data_size, index_block_size):
            raw = read_stream(
                handle, geometry_, allocation, block_offset, index_block_size
            )
            logical = mst_decode(raw, geometry_.sector_size, b"INDX")
            for item in index_entries(logical, 0x18):
                if item["name"] == target_name:
                    matches.append(
                        {
                            "kind": "allocation",
                            "buffer": logical,
                            "entry": item,
                            "attribute": allocation,
                            "block_offset": block_offset,
                        }
                    )
    if len(matches) != 1:
        raise FixtureError(
            f"$I30 has {len(matches)} entries named {target_name!r}"
        )
    location = matches[0]
    entry = location["entry"]
    assert isinstance(entry, dict)
    reference = int(entry["reference"])
    if reference & ((1 << 48) - 1) != target_inode:
        raise FixtureError("target $I30 entry does not reference the expected MFT record")
    _, _, target_record = read_record(handle, geometry_, target_inode)
    target_sequence = struct.unpack_from("<H", target_record, 16)[0]
    if not target_sequence or (
        require_reference_valid and reference >> 48 != target_sequence
    ):
        raise FixtureError("target $I30 reference sequence is not initially valid")
    if not child_filename_valid(target_record, parent_inode, target_name):
        raise FixtureError("target child lacks its valid parent FILE_NAME chain")
    location["reference"] = reference
    location["target_sequence"] = target_sequence
    return location


def _file_name_value(record: bytes, attr: Attribute) -> dict[str, object]:
    if attr.type != AT_FILE_NAME or attr.nonresident:
        raise FixtureError("fixture FILE_NAME value is not resident")
    if attr.value_offset is None or attr.value_length is None:
        raise FixtureError("fixture FILE_NAME value has no resident bounds")
    value = bytes(record[attr.value_offset : attr.value_offset + attr.value_length])
    if len(value) < 66:
        raise FixtureError("fixture FILE_NAME value is truncated")
    name_length = value[64]
    expected_length = 66 + name_length * 2
    if expected_length != len(value):
        raise FixtureError("fixture FILE_NAME value has noncanonical trailing bytes")
    try:
        name = value[66:].decode("utf-16le")
    except UnicodeDecodeError as error:
        raise FixtureError("fixture FILE_NAME value is not valid UTF-16") from error
    parent_reference = struct.unpack_from("<Q", value, 0)[0]
    return {
        "attribute_offset": attr.record_offset,
        "attribute_length": attr.record_length,
        "attribute_instance": attr.instance,
        "parent_reference": parent_reference,
        "parent_inode": parent_reference & ((1 << 48) - 1),
        "parent_sequence": parent_reference >> 48,
        "namespace": value[65],
        "name": name,
        "cached_timestamps_hex": value[8:40].hex(),
        "cached_allocated_size": struct.unpack_from("<Q", value, 40)[0],
        "cached_data_size": struct.unpack_from("<Q", value, 48)[0],
        "cached_file_attributes": struct.unpack_from("<I", value, 56)[0],
        "cached_ea_reparse": struct.unpack_from("<I", value, 60)[0],
        "value": value,
        "value_hex": value.hex(),
        "value_sha256": hashlib.sha256(value).hexdigest(),
    }


def inspect_hardlink_collation(
    handle: BinaryIO,
    geometry_: Geometry,
    inode: int,
    parent_inodes: tuple[int, int],
    target_name: str,
) -> dict[str, object]:
    if len(set(parent_inodes)) != 2:
        raise FixtureError("hard-link collation fixture requires two distinct parents")
    _, _, record = read_record(handle, geometry_, inode)
    target_sequence = struct.unpack_from("<H", record, 16)[0]
    selected: list[dict[str, object]] = []
    file_name_count = 0
    for attr in attributes(record):
        if attr.type != AT_FILE_NAME:
            continue
        file_name_count += 1
        value = _file_name_value(record, attr)
        if (
            value["name"] == target_name
            and int(value["parent_inode"]) in parent_inodes
        ):
            selected.append(value)
    if len(selected) != 2 or file_name_count != 2:
        raise FixtureError(
            "hard-link collation fixture lacks exactly two resident FILE_NAME values"
        )
    if {int(item["parent_inode"]) for item in selected} != set(parent_inodes):
        raise FixtureError("hard-link collation fixture does not cover both parents")

    index_copies: list[dict[str, object]] = []
    all_reciprocal = True
    for parent_inode in parent_inodes:
        _, _, parent_record = read_record(handle, geometry_, parent_inode)
        parent_sequence = struct.unpack_from("<H", parent_record, 16)[0]
        value = next(
            item for item in selected if int(item["parent_inode"]) == parent_inode
        )
        location = locate_index_reference(
            handle,
            geometry_,
            parent_inode,
            target_name,
            inode,
            None,
            False,
        )
        entry = location["entry"]
        assert isinstance(entry, dict)
        key_hex = str(entry["key_hex"])
        semantic_key_match = (
            int(entry["key_parent_reference"]) == int(value["parent_reference"])
            and entry["name"] == target_name
            and int(entry["key_namespace"]) == int(value["namespace"])
            and int(entry["key_length"]) == len(bytes(value["value"]))
        )
        cached_differences = [
            name
            for name, entry_key, value_key in (
                ("timestamps", "cached_timestamps_hex", "cached_timestamps_hex"),
                ("allocated-size", "cached_allocated_size", "cached_allocated_size"),
                ("data-size", "cached_data_size", "cached_data_size"),
                ("file-attributes", "cached_file_attributes", "cached_file_attributes"),
                ("ea-reparse", "cached_ea_reparse", "cached_ea_reparse"),
            )
            if entry[entry_key] != value[value_key]
        ]
        reciprocal = (
            int(value["parent_sequence"]) == parent_sequence
            and int(location["target_sequence"]) == target_sequence
            and int(location["reference"]) >> 48 == target_sequence
            and semantic_key_match
            and entry["entry_flags_valid"] is True
        )
        all_reciprocal = all_reciprocal and reciprocal
        index_copies.append(
            {
                "parent_inode": parent_inode,
                "parent_sequence": parent_sequence,
                "reference": int(location["reference"]),
                "key_parent_reference": entry["key_parent_reference"],
                "key_namespace": entry["key_namespace"],
                "key_length": entry["key_length"],
                "key_sha256": entry["key_sha256"],
                "file_name_value_sha256": value["value_sha256"],
                "exact_value_match": key_hex == value["value_hex"],
                "semantic_key_match": semantic_key_match,
                "entry_flags": entry["entry_flags"],
                "entry_flags_valid": entry["entry_flags_valid"],
                "cached_differences": cached_differences,
                "cached_difference_count": len(cached_differences),
                "reciprocal": reciprocal,
            }
        )

    values = [bytes(item["value"]) for item in selected]
    return {
        "inode": inode,
        "target_sequence": target_sequence,
        "target_name": target_name,
        "link_count": struct.unpack_from("<H", record, 18)[0],
        "file_name_count": file_name_count,
        "resident_parent_order": [int(item["parent_inode"]) for item in selected],
        "attribute_instances": [int(item["attribute_instance"]) for item in selected],
        "value_sha256": [str(item["value_sha256"]) for item in selected],
        "values_distinct": values[0] != values[1],
        "values_collated": values == sorted(values),
        "all_reciprocal": all_reciprocal,
        "index_copies": index_copies,
    }


def mutate_file_name_index_field(
    handle: BinaryIO,
    geometry_: Geometry,
    kind: str,
    inode: int,
    parent_inodes: tuple[int, int],
    target_name: str,
) -> dict[str, object]:
    if kind not in FILE_NAME_CACHED_KINDS + FILE_NAME_STABLE_KINDS:
        raise FixtureError(f"unsupported FILE_NAME index-field fixture {kind}")
    before = inspect_hardlink_collation(
        handle, geometry_, inode, parent_inodes, target_name
    )
    if before["all_reciprocal"] is not True:
        raise FixtureError("FILE_NAME index-field fixture is not initially reciprocal")
    parent_inode = parent_inodes[0]
    location = locate_index_reference(
        handle, geometry_, parent_inode, target_name, inode, None, True
    )
    if location["kind"] != "record":
        raise FixtureError(
            "FILE_NAME index-field fixture requires a resident parent $I30 root"
        )
    buffer = location["buffer"]
    entry = location["entry"]
    assert isinstance(buffer, bytearray) and isinstance(entry, dict)
    entry_offset = int(entry["offset"])
    key_offset = entry_offset + 16
    key_length = int(entry["key_length"])
    key_before = bytes(buffer[key_offset : key_offset + key_length])
    entry_flags_before = int(entry["entry_flags"])
    reference_before = int(entry["reference"])

    if kind.startswith("file-name-cached-"):
        field = kind.removeprefix("file-name-cached-")
        field_offset, field_length = FILE_NAME_CACHED_FIELDS[field]
        before_bytes = bytes(
            buffer[
                key_offset + field_offset:
                key_offset + field_offset + field_length
            ]
        )
        after_bytes = bytearray(before_bytes)
        after_bytes[0] ^= 0x5A
        buffer[
            key_offset + field_offset:
            key_offset + field_offset + field_length
        ] = after_bytes
        mutation_class = "cached"
    elif kind == "file-name-stable-parent":
        field = "parent-reference"
        before_bytes = bytes(buffer[key_offset : key_offset + 8])
        parent_reference = struct.unpack_from("<Q", before_bytes)[0]
        wrong_sequence = ((parent_reference >> 48) % 0xFFFF) + 1
        if wrong_sequence == parent_reference >> 48:
            wrong_sequence = 1 if wrong_sequence == 0xFFFF else wrong_sequence + 1
        changed = (wrong_sequence << 48) | (parent_reference & ((1 << 48) - 1))
        after_bytes = changed.to_bytes(8, "little")
        buffer[key_offset : key_offset + 8] = after_bytes
        mutation_class = "stable"
    elif kind == "file-name-stable-sequence":
        field = "child-reference-sequence"
        before_bytes = bytes(buffer[entry_offset : entry_offset + 8])
        wrong_sequence = ((reference_before >> 48) % 0xFFFF) + 1
        if wrong_sequence == reference_before >> 48:
            wrong_sequence = 1 if wrong_sequence == 0xFFFF else wrong_sequence + 1
        changed = (wrong_sequence << 48) | (reference_before & ((1 << 48) - 1))
        after_bytes = changed.to_bytes(8, "little")
        buffer[entry_offset : entry_offset + 8] = after_bytes
        mutation_class = "stable"
    else:
        field = "entry-flags"
        if entry_flags_before & ~1:
            raise FixtureError("FILE_NAME index entry already has unknown flag bits")
        before_bytes = entry_flags_before.to_bytes(2, "little")
        after_bytes = (entry_flags_before | 4).to_bytes(2, "little")
        buffer[entry_offset + 12 : entry_offset + 14] = after_bytes
        mutation_class = "stable"

    write_record(handle, geometry_, parent_inode, buffer)
    after = inspect_hardlink_collation(
        handle, geometry_, inode, parent_inodes, target_name
    )
    mutated = next(
        item
        for item in after["index_copies"]
        if int(item["parent_inode"]) == parent_inode
    )
    if mutation_class == "cached":
        if (
            after["all_reciprocal"] is not True
            or mutated["semantic_key_match"] is not True
            or field not in mutated["cached_differences"]
        ):
            raise FixtureError("cached FILE_NAME mutation changed stable reciprocity")
    elif after["all_reciprocal"] is not False or mutated["reciprocal"] is not False:
        raise FixtureError("stable FILE_NAME mutation remained reciprocal")

    key_after = bytes(buffer[key_offset : key_offset + key_length])
    if kind == "file-name-stable-sequence":
        key_after = key_before
    if kind == "file-name-stable-flags":
        key_after = key_before
    return {
        "kind": kind,
        "mutation_class": mutation_class,
        "field": field,
        "inode": inode,
        "parent_inodes": list(parent_inodes),
        "mutated_parent_inode": parent_inode,
        "target_name": target_name,
        "entry_offset": entry_offset,
        "key_length": key_length,
        "before_hex": before_bytes.hex(),
        "after_hex": bytes(after_bytes).hex(),
        "key_before_sha256": hashlib.sha256(key_before).hexdigest(),
        "key_after_sha256": hashlib.sha256(key_after).hexdigest(),
        "file_name_value_sha256": mutated["file_name_value_sha256"],
        "expected_semantic_key_match": mutation_class == "cached"
        or kind != "file-name-stable-parent",
        "expected_entry_flags_valid": kind != "file-name-stable-flags",
        "expected_reciprocal": mutation_class == "cached",
    }


def _resident_i30_context(
    handle: BinaryIO, geometry_: Geometry, parent_inode: int
) -> tuple[bytearray, list[dict[str, object]]]:
    _, _, parent = read_record(handle, geometry_, parent_inode)
    root = find_attribute(parent, AT_INDEX_ROOT, "$I30")
    if root.value_offset is None or root.value_length is None or root.value_length < 32:
        raise FixtureError("POSIX collision parent has no resident $I30 root")
    return parent, list(index_entries(parent, root.value_offset + 16))


def _child_file_name(
    record: bytes, parent_inode: int, target_name: str
) -> dict[str, object]:
    matches: list[dict[str, object]] = []
    for attr in attributes(record):
        if attr.type != AT_FILE_NAME or attr.nonresident:
            continue
        value = _file_name_value(record, attr)
        if (
            int(value["parent_inode"]) == parent_inode
            and value["name"] == target_name
        ):
            matches.append(value)
    if len(matches) != 1:
        raise FixtureError(
            f"child has {len(matches)} FILE_NAME values for {target_name!r}"
        )
    return matches[0]


def inspect_posix_collision(
    handle: BinaryIO, geometry_: Geometry, state: dict[str, object]
) -> dict[str, object]:
    parent_inode = int(state["parent_inode"])
    inodes = [int(value) for value in state["inodes"]]
    names = [str(value) for value in state["final_names"]]
    if len(inodes) != 2 or len(names) != 2 or inodes[0] == inodes[1]:
        raise FixtureError("POSIX collision state does not name two distinct children")
    parent, entries = _resident_i30_context(handle, geometry_, parent_inode)
    parent_sequence = struct.unpack_from("<H", parent, 16)[0]
    raw_offsets = state.get("entry_offsets")
    selected_entries: list[dict[str, object]] = []
    if raw_offsets is not None:
        offsets = [int(value) for value in raw_offsets]
        if len(offsets) != 2 or len(set(offsets)) != 2:
            raise FixtureError("POSIX collision entry offsets are invalid")
        for offset in offsets:
            matches = [entry for entry in entries if int(entry["offset"]) == offset]
            if len(matches) != 1:
                raise FixtureError("POSIX collision entry offset is no longer unique")
            selected_entries.append(matches[0])
    else:
        for inode, name in zip(inodes, names, strict=True):
            matches = [
                entry
                for entry in entries
                if int(entry["reference"]) & ((1 << 48) - 1) == inode
                and entry["name"] == name
            ]
            if len(matches) != 1:
                raise FixtureError(
                    f"POSIX collision has {len(matches)} entries for {name!r}/{inode}"
                )
            selected_entries.append(matches[0])

    members: list[dict[str, object]] = []
    for inode, name, entry in zip(inodes, names, selected_entries, strict=True):
        _, _, record = read_record(handle, geometry_, inode)
        sequence = struct.unpack_from("<H", record, 16)[0]
        value = _child_file_name(record, parent_inode, name)
        reference = int(entry["reference"])
        stable_key_match = (
            int(entry["key_parent_reference"]) == int(value["parent_reference"])
            and entry["name"] == value["name"]
            and int(entry["key_namespace"]) == int(value["namespace"])
            and int(entry["key_length"]) == len(bytes(value["value"]))
        )
        reciprocal = (
            reference & ((1 << 48) - 1) == inode
            and reference >> 48 == sequence
            and int(value["parent_inode"]) == parent_inode
            and int(value["parent_sequence"]) == parent_sequence
            and entry["entry_flags_valid"] is True
            and stable_key_match
        )
        members.append(
            {
                "inode": inode,
                "sequence": sequence,
                "entry_offset": int(entry["offset"]),
                "entry_reference": reference,
                "entry_name": entry["name"],
                "entry_namespace": int(entry["key_namespace"]),
                "entry_flags": int(entry["entry_flags"]),
                "entry_flags_valid": entry["entry_flags_valid"],
                "entry_key_sha256": entry["key_sha256"],
                "file_name": value["name"],
                "file_name_namespace": int(value["namespace"]),
                "file_name_sha256": value["value_sha256"],
                "stable_key_match": stable_key_match,
                "reciprocal": reciprocal,
            }
        )
    entry_names = [str(member["entry_name"]) for member in members]
    references = [int(member["entry_reference"]) for member in members]
    return {
        "parent_inode": parent_inode,
        "parent_sequence": parent_sequence,
        "members": members,
        "canonical_names": [name.upper() for name in entry_names],
        "canonical_collision": entry_names[0].upper() == entry_names[1].upper(),
        "exact_utf16_duplicate": entry_names[0] == entry_names[1],
        "all_posix": all(
            member["entry_namespace"] == 0
            and member["file_name_namespace"] == 0
            for member in members
        ),
        "unique_entry_references": len(set(references)) == 2,
        "all_reciprocal": all(member["reciprocal"] for member in members),
        "required_anchor": state.get("required_anchor") is True,
    }


def mutate_posix_collision(
    handle: BinaryIO,
    geometry_: Geometry,
    kind: str,
    parent_inode: int,
    inodes: tuple[int, int],
    names: tuple[str, str],
) -> dict[str, object]:
    if kind not in POSIX_COLLISION_KINDS:
        raise FixtureError(f"unsupported POSIX collision fixture {kind}")
    before_state = {
        "parent_inode": parent_inode,
        "inodes": list(inodes),
        "final_names": list(names),
    }
    before = inspect_posix_collision(handle, geometry_, before_state)
    if before["all_reciprocal"] is not True or before["all_posix"] is not True:
        raise FixtureError("POSIX collision source is not reciprocal POSIX namespace")
    if kind != "posix-collision-required-anchor" and (
        before["canonical_collision"] is not True
        or before["exact_utf16_duplicate"] is not False
    ):
        raise FixtureError("POSIX collision source lacks a distinct case collision")

    parent, entries = _resident_i30_context(handle, geometry_, parent_inode)
    selected: list[dict[str, object]] = []
    for inode, name in zip(inodes, names, strict=True):
        matches = [
            entry
            for entry in entries
            if int(entry["reference"]) & ((1 << 48) - 1) == inode
            and entry["name"] == name
        ]
        if len(matches) != 1:
            raise FixtureError("POSIX collision source entry is not unique")
        selected.append(matches[0])
    second_entry = selected[1]
    second_entry_offset = int(second_entry["offset"])
    second_key_offset = second_entry_offset + 16
    _, _, second_record = read_record(handle, geometry_, inodes[1])
    second_value = _child_file_name(second_record, parent_inode, names[1])
    value_offset = int(second_value["attribute_offset"])
    value_attr = next(
        attr
        for attr in attributes(second_record)
        if attr.record_offset == value_offset
    )
    assert value_attr.value_offset is not None
    final_names = list(names)

    if kind in (
        "posix-collision-exact-duplicate",
        "posix-collision-required-anchor",
    ):
        final_name = names[0] if kind.endswith("exact-duplicate") else names[0].upper()
        old_name_bytes = names[1].encode("utf-16le")
        new_name_bytes = final_name.encode("utf-16le")
        if len(new_name_bytes) > len(old_name_bytes) or final_name == names[1]:
            raise FixtureError("POSIX collision rename does not fit its source value")
        new_value_length = 66 + len(new_name_bytes)
        struct.pack_into("<I", second_record, value_offset + 16, new_value_length)
        struct.pack_into("<H", parent, second_entry_offset + 10, new_value_length)
        second_record[value_attr.value_offset + 64] = len(final_name)
        parent[second_key_offset + 64] = len(final_name)
        second_record[
            value_attr.value_offset + 66:
            value_attr.value_offset + 66 + len(old_name_bytes)
        ] = bytes(len(old_name_bytes))
        parent[
            second_key_offset + 66:
            second_key_offset + 66 + len(old_name_bytes)
        ] = bytes(len(old_name_bytes))
        second_record[
            value_attr.value_offset + 66:
            value_attr.value_offset + 66 + len(new_name_bytes)
        ] = new_name_bytes
        parent[
            second_key_offset + 66:
            second_key_offset + 66 + len(new_name_bytes)
        ] = new_name_bytes
        final_names[1] = final_name
        write_record(handle, geometry_, inodes[1], second_record)
    elif kind == "posix-collision-mixed-namespace":
        if second_record[value_attr.value_offset + 65] != 0 or parent[second_key_offset + 65] != 0:
            raise FixtureError("POSIX collision member is not namespace zero")
        second_record[value_attr.value_offset + 65] = 1
        parent[second_key_offset + 65] = 1
        write_record(handle, geometry_, inodes[1], second_record)
    else:
        first_reference = int(selected[0]["reference"])
        struct.pack_into("<Q", parent, second_entry_offset, first_reference)
    write_record(handle, geometry_, parent_inode, parent)

    state = {
        "kind": kind,
        "parent_inode": parent_inode,
        "inodes": list(inodes),
        "original_names": list(names),
        "final_names": final_names,
        "entry_offsets": [int(entry["offset"]) for entry in selected],
        "required_anchor": kind == "posix-collision-required-anchor",
    }
    after = inspect_posix_collision(handle, geometry_, state)
    expected = {
        "posix-collision-exact-duplicate": (True, True, True, True),
        "posix-collision-mixed-namespace": (True, False, False, True),
        "posix-collision-duplicate-reference": (True, False, True, False),
        "posix-collision-required-anchor": (True, False, True, True),
    }[kind]
    observed = (
        after["canonical_collision"],
        after["exact_utf16_duplicate"],
        after["all_posix"],
        after["all_reciprocal"],
    )
    if observed != expected:
        raise FixtureError(
            f"POSIX collision mutation produced {observed!r}, expected {expected!r}"
        )
    if kind == "posix-collision-duplicate-reference" and after["unique_entry_references"]:
        raise FixtureError("duplicate-reference fixture retained unique owners")
    return state


def inspect_sparse_stream(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> dict[str, object]:
    _, _, record = read_record(handle, geometry_, inode)
    data = find_attribute(record, AT_DATA)
    if not data.nonresident or data.name:
        raise FixtureError("sparse census fixture DATA is not unnamed and nonresident")
    logical_clusters = (
        data.data_size + geometry_.cluster_size - 1
    ) // geometry_.cluster_size
    expected_vcn = 0
    runlist_complete = data.lowest_vcn == 0
    mapped_lcns: list[int] = []
    sparse_clusters = 0
    for vcn, lcn, length in data.runs:
        if vcn != expected_vcn or length <= 0:
            runlist_complete = False
        expected_vcn = vcn + length
        if lcn is None:
            sparse_clusters += length
        else:
            if lcn < 0 or lcn + length > geometry_.total_clusters:
                runlist_complete = False
            mapped_lcns.extend(range(lcn, lcn + length))
    runlist_complete = runlist_complete and expected_vcn == logical_clusters
    cluster_bitmap = _system_stream(handle, geometry_, FILE_BITMAP, AT_DATA)
    _, _, mft_record = read_record(handle, geometry_, FILE_MFT)
    mft_bitmap = find_attribute(mft_record, AT_BITMAP)
    content = read_stream(handle, geometry_, data, 0, data.data_size)
    _, terminator = mapping_pair_bounds(record, data)
    attribute_end = data.record_offset + data.record_length
    tail = bytes(record[terminator + 1 : attribute_end])
    physical_bytes = len(mapped_lcns) * geometry_.cluster_size
    pinned_producer_slack = bool(tail) and tail == b"\xff" + bytes(len(tail) - 1)
    return {
        "inode": inode,
        "record_attrs_offset": struct.unpack_from("<H", record, 20)[0],
        "record_bytes_in_use": struct.unpack_from("<I", record, 24)[0],
        "record_next_attr_instance": struct.unpack_from("<H", record, 40)[0],
        "attribute_record_offset": data.record_offset,
        "attribute_record_length": data.record_length,
        "attribute_flags": data.flags,
        "attribute_instance": data.instance,
        "compression_unit": data.compression_unit,
        "data_size": data.data_size,
        "initialized_size": data.initialized_size,
        "allocated_size": data.allocated_size,
        "compressed_size": data.compressed_size,
        "cluster_size": geometry_.cluster_size,
        "logical_clusters": logical_clusters,
        "mapped_clusters": len(mapped_lcns),
        "sparse_clusters": sparse_clusters,
        "physical_bytes": physical_bytes,
        "runs": data.runs,
        "runlist_complete": runlist_complete,
        "tail_run_mapped": bool(
            data.runs
            and data.runs[-1][1] is not None
            and data.runs[-1][0] + data.runs[-1][2] == logical_clusters
        ),
        "mapped_lcns": mapped_lcns,
        "mapped_lcns_distinct": len(mapped_lcns) == len(set(mapped_lcns)),
        "mapped_cluster_bits": [
            _read_bitmap_bit(handle, geometry_, cluster_bitmap, lcn)
            for lcn in mapped_lcns
        ],
        "mft_bitmap_bit": _read_bitmap_bit(
            handle, geometry_, mft_bitmap, inode
        ),
        "logical_sha256": hashlib.sha256(content).hexdigest(),
        "head_sha256": hashlib.sha256(content[: geometry_.cluster_size]).hexdigest(),
        "hole_all_zero": all(
            content[vcn * geometry_.cluster_size : (vcn + length) * geometry_.cluster_size]
            == bytes(length * geometry_.cluster_size)
            for vcn, lcn, length in data.runs
            if lcn is None
        ),
        "tail_sha256": hashlib.sha256(
            content[-geometry_.cluster_size :]
        ).hexdigest(),
        "mapping_hex": bytes(
            record[data.mapping_offset : terminator + 1]
        ).hex() if data.mapping_offset is not None else None,
        "mapping_pairs_offset": (
            data.mapping_offset - data.record_offset
            if data.mapping_offset is not None else None
        ),
        "mapping_pairs_record_offset": data.mapping_offset,
        "terminator_attribute_offset": terminator - data.record_offset,
        "terminator_record_offset": terminator,
        "mapping_tail_record_offset": terminator + 1,
        "mapping_tail_length": len(tail),
        "mapping_tail_hex": tail.hex(),
        "mapping_tail_all_zero": not any(tail),
        "mapping_tail_pinned_producer_slack": pinned_producer_slack,
        "mapping_tail_opaque_slack": True,
        "mapping_tail_accepted_slack": True,
    }


def corrupt_index_reference(
    handle: BinaryIO,
    geometry_: Geometry,
    parent_inode: int,
    target_name: str,
    target_inode: int,
    allocation_inode: int | None = None,
) -> dict[str, object]:
    location = locate_index_reference(
        handle,
        geometry_,
        parent_inode,
        target_name,
        target_inode,
        allocation_inode,
        True,
    )
    buffer = location["buffer"]
    entry = location["entry"]
    assert isinstance(buffer, bytearray) and isinstance(entry, dict)
    reference = int(location["reference"])
    target_sequence = int(location["target_sequence"])
    wrong_sequence = 1 if target_sequence == 0xFFFF else target_sequence + 1
    changed_reference = (wrong_sequence << 48) | (reference & ((1 << 48) - 1))
    struct.pack_into("<Q", buffer, int(entry["offset"]), changed_reference)
    if location["kind"] == "record":
        write_record(handle, geometry_, parent_inode, buffer)
    else:
        allocation = location["attribute"]
        assert isinstance(allocation, Attribute)
        write_stream(
            handle,
            geometry_,
            allocation,
            int(location["block_offset"]),
            mst_encode(buffer, geometry_.sector_size),
        )
    return {
        "kind": "index-reference",
        "parent_inode": parent_inode,
        "target_inode": target_inode,
        "target_name": target_name,
        "expected_sequence": target_sequence,
        "wrong_sequence": wrong_sequence,
        "allocation_inode": allocation_inode,
        "location": location["kind"],
    }


def inspect_index_reference(
    handle: BinaryIO, geometry_: Geometry, state: dict[str, object]
) -> dict[str, object]:
    parent_inode = int(state["parent_inode"])
    target_inode = int(state["target_inode"])
    target_name = str(state["target_name"])
    location = locate_index_reference(
        handle,
        geometry_,
        parent_inode,
        target_name,
        target_inode,
        (
            None
            if state.get("allocation_inode") is None
            else int(state["allocation_inode"])
        ),
        False,
    )
    reference = int(location["reference"])
    _, _, target_record = read_record(handle, geometry_, target_inode)
    target_sequence = struct.unpack_from("<H", target_record, 16)[0]
    return {
        "valid": (
            reference & ((1 << 48) - 1) == target_inode
            and reference >> 48 == target_sequence
            and child_filename_valid(target_record, parent_inode, target_name)
        ),
        "record": reference & ((1 << 48) - 1),
        "reference_sequence": reference >> 48,
        "target_sequence": target_sequence,
    }


def attribute_value(
    handle: BinaryIO, geometry_: Geometry, record: bytes, attr: Attribute
) -> bytes:
    if attr.nonresident:
        return read_stream(handle, geometry_, attr, 0, attr.data_size)
    assert attr.value_offset is not None and attr.value_length is not None
    return bytes(record[attr.value_offset : attr.value_offset + attr.value_length])


def write_attribute_value(
    handle: BinaryIO,
    geometry_: Geometry,
    inode: int,
    record: bytearray,
    attr: Attribute,
    value: bytes,
) -> None:
    if len(value) != attr.data_size:
        raise FixtureError("fixture attribute value length changed")
    if attr.nonresident:
        write_stream(handle, geometry_, attr, 0, value)
    else:
        assert attr.value_offset is not None and attr.value_length is not None
        record[attr.value_offset : attr.value_offset + attr.value_length] = value
        write_record(handle, geometry_, inode, record)


def attribute_list_entries(value: bytes) -> Iterable[dict[str, object]]:
    cursor = 0
    while cursor < len(value):
        if not any(value[cursor:]):
            return
        if cursor + 26 > len(value):
            raise FixtureError("$ATTRIBUTE_LIST entry header is truncated")
        attr_type = struct.unpack_from("<I", value, cursor)[0]
        length = struct.unpack_from("<H", value, cursor + 4)[0]
        name_length = value[cursor + 6]
        name_offset = value[cursor + 7]
        if (
            attr_type in (0, 0xFFFFFFFF)
            or length < 26
            or length % 8
            or cursor + length > len(value)
        ):
            raise FixtureError("$ATTRIBUTE_LIST entry bounds are invalid")
        name_end = name_offset + name_length * 2
        if name_length and (name_offset < 26 or name_end > length):
            raise FixtureError("$ATTRIBUTE_LIST entry name is out of bounds")
        try:
            name = value[
                cursor + name_offset : cursor + name_end
            ].decode("utf-16-le") if name_length else ""
        except UnicodeDecodeError as error:
            raise FixtureError("$ATTRIBUTE_LIST entry name is invalid UTF-16") from error
        yield {
            "offset": cursor,
            "length": length,
            "type": attr_type,
            "name": name,
            "lowest_vcn": struct.unpack_from("<Q", value, cursor + 8)[0],
            "reference": struct.unpack_from("<Q", value, cursor + 16)[0],
            "instance": struct.unpack_from("<H", value, cursor + 24)[0],
        }
        cursor += length


def validate_attribute_list_extent(
    handle: BinaryIO,
    geometry_: Geometry,
    base_inode: int,
    base_sequence: int,
    entry: dict[str, object],
    *,
    require_reference_sequence: bool,
) -> dict[str, int]:
    reference = int(entry["reference"])
    extent_inode = reference & ((1 << 48) - 1)
    reference_sequence = reference >> 48
    _, _, extent = read_record(handle, geometry_, extent_inode)
    extent_sequence = struct.unpack_from("<H", extent, 16)[0]
    base_reference = struct.unpack_from("<Q", extent, 32)[0]
    if (
        base_reference & ((1 << 48) - 1) != base_inode
        or base_reference >> 48 != base_sequence
        or (require_reference_sequence and reference_sequence != extent_sequence)
    ):
        raise FixtureError("$ATTRIBUTE_LIST extent/base reference is not authoritative")
    matches = [
        attr
        for attr in attributes(extent)
        if attr.type == entry["type"]
        and attr.name == entry["name"]
        and attr.instance == entry["instance"]
        and attr.lowest_vcn == entry["lowest_vcn"]
    ]
    if len(matches) != 1:
        raise FixtureError("$ATTRIBUTE_LIST entry has no unique extent attribute")
    return {
        "extent_inode": extent_inode,
        "extent_sequence": extent_sequence,
        "reference_sequence": reference_sequence,
    }


def corrupt_attribute_list(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> dict[str, object]:
    _, _, record = read_record(handle, geometry_, inode)
    attr_list = find_attribute(record, AT_ATTRIBUTE_LIST)
    value = bytearray(attribute_value(handle, geometry_, record, attr_list))
    base_sequence = struct.unpack_from("<H", record, 16)[0]
    candidates: list[tuple[dict[str, object], dict[str, int]]] = []
    for entry in attribute_list_entries(value):
        reference = int(entry["reference"])
        if reference & ((1 << 48) - 1) == inode:
            continue
        details = validate_attribute_list_extent(
            handle, geometry_, inode, base_sequence, entry,
            require_reference_sequence=True,
        )
        candidates.append((entry, details))
    if not candidates:
        raise FixtureError("fixture has no authoritative attribute-list extent entry")
    entry, details = candidates[0]
    wrong_sequence = 1 if details["extent_sequence"] == 0xFFFF else details["extent_sequence"] + 1
    changed_reference = (wrong_sequence << 48) | details["extent_inode"]
    struct.pack_into("<Q", value, int(entry["offset"]) + 16, changed_reference)
    write_attribute_value(handle, geometry_, inode, record, attr_list, bytes(value))
    return {
        "kind": "attribute-list",
        "inode": inode,
        "entry_offset": int(entry["offset"]),
        "entry_type": int(entry["type"]),
        "entry_name": str(entry["name"]),
        "entry_instance": int(entry["instance"]),
        "extent_inode": details["extent_inode"],
        "expected_sequence": details["extent_sequence"],
        "wrong_sequence": wrong_sequence,
    }


def inspect_attribute_list(
    handle: BinaryIO, geometry_: Geometry, state: dict[str, object]
) -> dict[str, object]:
    inode = int(state["inode"])
    _, _, record = read_record(handle, geometry_, inode)
    attr_list = find_attribute(record, AT_ATTRIBUTE_LIST)
    value = attribute_value(handle, geometry_, record, attr_list)
    entries = list(attribute_list_entries(value))
    matches = [entry for entry in entries if int(entry["offset"]) == state["entry_offset"]]
    if len(matches) != 1:
        raise FixtureError("mutated $ATTRIBUTE_LIST entry is no longer unique")
    entry = matches[0]
    details = validate_attribute_list_extent(
        handle,
        geometry_,
        inode,
        struct.unpack_from("<H", record, 16)[0],
        entry,
        require_reference_sequence=False,
    )
    return {
        "valid": details["reference_sequence"] == details["extent_sequence"],
        "extent_valid": True,
        "extent_inode": details["extent_inode"],
        "reference_sequence": details["reference_sequence"],
        "extent_sequence": details["extent_sequence"],
        "entry_count": len(entries),
    }


def _attribute_list_bindings(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> tuple[bytearray, list[dict[str, object]]]:
    _, _, base = read_record(handle, geometry_, inode)
    base_sequence = struct.unpack_from("<H", base, 16)[0]
    attr_list = find_attribute(base, AT_ATTRIBUTE_LIST)
    entries = list(
        attribute_list_entries(attribute_value(handle, geometry_, base, attr_list))
    )
    bindings: list[dict[str, object]] = []
    for entry in entries:
        reference = int(entry["reference"])
        record_inode = reference & ((1 << 48) - 1)
        reference_sequence = reference >> 48
        _, _, record = read_record(handle, geometry_, record_inode)
        record_sequence = struct.unpack_from("<H", record, 16)[0]
        if reference_sequence != record_sequence:
            raise FixtureError("$ATTRIBUTE_LIST binding sequence is stale")
        if record_inode == inode:
            if struct.unpack_from("<Q", record, 32)[0] != 0:
                raise FixtureError("base ATTRIBUTE_LIST record has an extent reference")
        else:
            base_reference = struct.unpack_from("<Q", record, 32)[0]
            if (
                base_reference & ((1 << 48) - 1) != inode
                or base_reference >> 48 != base_sequence
            ):
                raise FixtureError("ATTRIBUTE_LIST extension does not bind its base")
        matches = [
            attr
            for attr in attributes(record)
            if attr.type == int(entry["type"])
            and attr.name == str(entry["name"])
            and attr.instance == int(entry["instance"])
            and attr.lowest_vcn == int(entry["lowest_vcn"])
        ]
        if len(matches) != 1:
            raise FixtureError("ATTRIBUTE_LIST entry does not resolve uniquely")
        bindings.append(
            {
                "entry": entry,
                "record_inode": record_inode,
                "record_sequence": record_sequence,
                "record": record,
                "attribute": matches[0],
            }
        )
    return base, bindings


def inspect_attribute_list_hardlinks(
    handle: BinaryIO,
    geometry_: Geometry,
    inode: int,
    parent_inodes: tuple[int, int],
    target_name: str,
) -> dict[str, object]:
    if len(set(parent_inodes)) != 2:
        raise FixtureError("ATTRIBUTE_LIST hard-link fixture needs two parents")
    base, bindings = _attribute_list_bindings(handle, geometry_, inode)
    selected: list[dict[str, object]] = []
    file_name_entry_count = 0
    for binding in bindings:
        attr = binding["attribute"]
        record = binding["record"]
        assert isinstance(attr, Attribute) and isinstance(record, bytearray)
        if attr.type != AT_FILE_NAME:
            continue
        file_name_entry_count += 1
        value = _file_name_value(record, attr)
        if (
            value["name"] == target_name
            and int(value["parent_inode"]) in parent_inodes
        ):
            selected.append({**binding, "value": value})
    if len(selected) != 2:
        raise FixtureError("ATTRIBUTE_LIST does not bind both hard-link FILE_NAME values")
    if {int(item["value"]["parent_inode"]) for item in selected} != set(parent_inodes):
        raise FixtureError("ATTRIBUTE_LIST hard links do not cover the expected parents")

    values_in_ale_order = [bytes(item["value"]["value"]) for item in selected]
    parents_in_ale_order = [int(item["value"]["parent_inode"]) for item in selected]
    instances_in_ale_order = [
        int(item["entry"]["instance"]) for item in selected
    ]
    storage_order = sorted(
        selected,
        key=lambda item: (
            int(item["record_inode"]),
            int(item["attribute"].record_offset),
        ),
    )
    index_copies: list[dict[str, object]] = []
    target_sequence = struct.unpack_from("<H", base, 16)[0]
    for parent_inode in parent_inodes:
        value = next(
            item["value"]
            for item in selected
            if int(item["value"]["parent_inode"]) == parent_inode
        )
        _, _, parent_record = read_record(handle, geometry_, parent_inode)
        parent_sequence = struct.unpack_from("<H", parent_record, 16)[0]
        location = locate_index_reference(
            handle, geometry_, parent_inode, target_name, inode, None
        )
        entry = location["entry"]
        assert isinstance(entry, dict)
        reciprocal = (
            int(value["parent_sequence"]) == parent_sequence
            and int(location["target_sequence"]) == target_sequence
            and int(location["reference"]) >> 48 == target_sequence
            and int(entry["key_parent_reference"]) == int(value["parent_reference"])
            and entry["name"] == target_name
            and int(entry["key_namespace"]) == int(value["namespace"])
            and int(entry["key_length"]) == len(bytes(value["value"]))
        )
        index_copies.append(
            {
                "parent_inode": parent_inode,
                "parent_sequence": parent_sequence,
                "key_sha256": entry["key_sha256"],
                "file_name_value_sha256": value["value_sha256"],
                "semantic_key_match": reciprocal,
                "reciprocal": reciprocal,
            }
        )
    return {
        "inode": inode,
        "target_sequence": target_sequence,
        "target_name": target_name,
        "link_count": struct.unpack_from("<H", base, 18)[0],
        "attribute_list_entry_count": len(bindings),
        "file_name_entry_count": file_name_entry_count,
        "selected_file_name_count": len(selected),
        "ale_parent_order": parents_in_ale_order,
        "ale_instance_order": instances_in_ale_order,
        "ale_record_order": [int(item["record_inode"]) for item in selected],
        "storage_parent_order": [
            int(item["value"]["parent_inode"]) for item in storage_order
        ],
        "value_sha256_in_ale_order": [
            str(item["value"]["value_sha256"]) for item in selected
        ],
        "resolved_values_distinct": values_in_ale_order[0] != values_in_ale_order[1],
        "resolved_values_collated": values_in_ale_order == sorted(values_in_ale_order),
        "instances_nonmonotonic": instances_in_ale_order != sorted(instances_in_ale_order),
        "all_entries_resolved": len(bindings) > 0,
        "all_reciprocal": all(item["reciprocal"] for item in index_copies),
        "index_copies": index_copies,
    }


def permute_attribute_list_equal_triple_values(
    handle: BinaryIO,
    geometry_: Geometry,
    inode: int,
    parent_inodes: tuple[int, int],
    target_name: str,
) -> dict[str, object]:
    before = inspect_attribute_list_hardlinks(
        handle, geometry_, inode, parent_inodes, target_name
    )
    if (
        before["link_count"] < 3
        or before["resolved_values_collated"] is not True
        or before["instances_nonmonotonic"] is not True
        or before["all_reciprocal"] is not True
    ):
        raise FixtureError(
            "clean ATTRIBUTE_LIST hard-link ordering oracle is absent: "
            f"{before!r}"
        )
    _, bindings = _attribute_list_bindings(handle, geometry_, inode)
    selected: list[dict[str, object]] = []
    for binding in bindings:
        attr = binding["attribute"]
        record = binding["record"]
        assert isinstance(attr, Attribute) and isinstance(record, bytearray)
        if attr.type != AT_FILE_NAME:
            continue
        value = _file_name_value(record, attr)
        if value["name"] == target_name and int(value["parent_inode"]) in parent_inodes:
            selected.append({**binding, "value": value})
    if len(selected) != 2:
        raise FixtureError("ATTRIBUTE_LIST equal-triple fixture lacks two FILE_NAME values")
    first, second = selected
    first_attr = first["attribute"]
    second_attr = second["attribute"]
    assert isinstance(first_attr, Attribute) and isinstance(second_attr, Attribute)
    if first_attr.value_length != second_attr.value_length:
        raise FixtureError("ATTRIBUTE_LIST hard-link values are not equal length")
    first_value = bytes(first["value"]["value"])
    second_value = bytes(second["value"]["value"])
    records: dict[int, bytearray] = {}
    for item in selected:
        record_inode = int(item["record_inode"])
        records.setdefault(record_inode, bytearray(item["record"]))
    assert first_attr.value_offset is not None and second_attr.value_offset is not None
    records[int(first["record_inode"])][
        first_attr.value_offset : first_attr.value_offset + len(second_value)
    ] = second_value
    records[int(second["record_inode"])][
        second_attr.value_offset : second_attr.value_offset + len(first_value)
    ] = first_value
    for record_inode, record in records.items():
        write_record(handle, geometry_, record_inode, record)
    after = inspect_attribute_list_hardlinks(
        handle, geometry_, inode, parent_inodes, target_name
    )
    if (
        after["resolved_values_collated"] is not False
        or after["all_reciprocal"] is not True
        or after["ale_instance_order"] != before["ale_instance_order"]
        or sorted(after["value_sha256_in_ale_order"])
        != sorted(before["value_sha256_in_ale_order"])
    ):
        raise FixtureError("ATTRIBUTE_LIST equal-triple permutation changed link authority")
    return {
        "kind": "attribute-list-equal-triple-order",
        "inode": inode,
        "parent_inodes": list(parent_inodes),
        "target_name": target_name,
        "original_ale_parent_order": before["ale_parent_order"],
        "permuted_ale_parent_order": after["ale_parent_order"],
        "ale_instance_order": before["ale_instance_order"],
        "ale_record_order": before["ale_record_order"],
        "value_sha256": sorted(before["value_sha256_in_ale_order"]),
        "permitted_equal_triple_order": True,
    }


LARGE_ATTRIBUTE_LIST_BOUNDARY = 256 * 1024


def _large_attribute_list_context(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> dict[str, object]:
    _, _, base = read_record(handle, geometry_, inode)
    attr_list = find_attribute(base, AT_ATTRIBUTE_LIST)
    if not attr_list.nonresident or attr_list.mapping_offset is None:
        raise FixtureError("large $ATTRIBUTE_LIST is not nonresident")
    value = attribute_value(handle, geometry_, base, attr_list)
    entries = list(attribute_list_entries(value))
    _, bindings = _attribute_list_bindings(handle, geometry_, inode)
    if len(entries) != len(bindings):
        raise FixtureError("large $ATTRIBUTE_LIST binding inventory is incomplete")
    if attr_list.data_size != LARGE_ATTRIBUTE_LIST_BOUNDARY or not entries:
        raise FixtureError("large $ATTRIBUTE_LIST is not at the exact 0x40000 ceiling")
    boundary_index = len(entries) - 1
    boundary_entry = entries[boundary_index]
    if (
        int(boundary_entry["offset"]) + int(boundary_entry["length"])
        != LARGE_ATTRIBUTE_LIST_BOUNDARY
    ):
        raise FixtureError("large $ATTRIBUTE_LIST final entry does not end at 0x40000")
    fault_logical_offset = attr_list.data_size - 1
    fault_segments = list(
        _stream_segments(attr_list, geometry_, fault_logical_offset, 1)
    )
    if (
        len(fault_segments) != 1
        or fault_segments[0][0] is None
        or fault_segments[0][1] != 1
    ):
        raise FixtureError("large $ATTRIBUTE_LIST fault byte is not physically bound")
    return {
        "base": base,
        "attribute": attr_list,
        "value": value,
        "entries": entries,
        "bindings": bindings,
        "boundary_index": boundary_index,
        "boundary_entry": boundary_entry,
        "fault_logical_offset": fault_logical_offset,
        "fault_physical_offset": int(fault_segments[0][0]),
    }


def inspect_large_attribute_list(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> dict[str, object]:
    context = _large_attribute_list_context(handle, geometry_, inode)
    attr_list = context["attribute"]
    value = context["value"]
    entries = context["entries"]
    bindings = context["bindings"]
    boundary = context["boundary_entry"]
    assert isinstance(attr_list, Attribute)
    assert isinstance(value, bytes)
    assert isinstance(entries, list) and isinstance(bindings, list)
    assert isinstance(boundary, dict)
    unique_binding_keys = {
        (
            int(binding["record_inode"]),
            int(binding["entry"]["instance"]),
            int(binding["entry"]["type"]),
            str(binding["entry"]["name"]),
            int(binding["entry"]["lowest_vcn"]),
        )
        for binding in bindings
    }
    full_length_named = [
        binding
        for binding in bindings
        if int(binding["entry"]["type"]) == AT_DATA
        and str(binding["entry"]["name"]).startswith("s")
        and len(str(binding["entry"]["name"])) == 255
    ]
    cap_tail_named = [
        binding
        for binding in bindings
        if int(binding["entry"]["type"]) == AT_DATA
        and str(binding["entry"]["name"]).startswith("z0489")
        and len(str(binding["entry"]["name"])) == 208
    ]
    extent_records = {int(binding["record_inode"]) for binding in bindings}
    boundary_offset = int(boundary["offset"])
    boundary_end = boundary_offset + int(boundary["length"])
    return {
        "inode": inode,
        "nonresident": attr_list.nonresident,
        "logical_size": attr_list.data_size,
        "initialized_size": attr_list.initialized_size,
        "allocated_size": attr_list.allocated_size,
        "run_count": len(attr_list.runs),
        "runs": attr_list.runs,
        "stream_sha256": hashlib.sha256(value).hexdigest(),
        "entry_count": len(entries),
        "bound_entry_count": len(bindings),
        "unique_binding_count": len(unique_binding_keys),
        "storage_record_count": len(extent_records),
        "extension_record_count": len(extent_records - {inode}),
        "full_length_named_data_count": len(full_length_named),
        "cap_tail_named_data_count": len(cap_tail_named),
        "max_name_length": max(len(str(entry["name"])) for entry in entries),
        "all_entries_bound": len(entries) == len(bindings) == len(unique_binding_keys),
        "boundary_limit": LARGE_ATTRIBUTE_LIST_BOUNDARY,
        "boundary_entry_index": int(context["boundary_index"]),
        "boundary_entry_offset": boundary_offset,
        "boundary_entry_length": int(boundary["length"]),
        "boundary_entry_end": boundary_end,
        "boundary_entry_relation": "ENDS_AT_LIMIT",
        "boundary_entry_type": int(boundary["type"]),
        "boundary_entry_name_sha256": hashlib.sha256(
            str(boundary["name"]).encode("utf-16-le")
        ).hexdigest(),
        "read_fault_logical_offset": int(context["fault_logical_offset"]),
        "read_fault_physical_offset": int(context["fault_physical_offset"]),
    }


def corrupt_large_attribute_list_boundary(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> dict[str, object]:
    context = _large_attribute_list_context(handle, geometry_, inode)
    base = context["base"]
    attr_list = context["attribute"]
    value = bytearray(context["value"])
    entry = context["boundary_entry"]
    bindings = context["bindings"]
    assert isinstance(base, bytearray) and isinstance(attr_list, Attribute)
    assert isinstance(entry, dict) and isinstance(bindings, list)
    binding = bindings[int(context["boundary_index"])]
    record_sequence = int(binding["record_sequence"])
    wrong_sequence = 1 if record_sequence == 0xFFFF else record_sequence + 1
    reference_offset = int(entry["offset"]) + 16
    reference = struct.unpack_from("<Q", value, reference_offset)[0]
    struct.pack_into(
        "<Q",
        value,
        reference_offset,
        (wrong_sequence << 48) | (reference & ((1 << 48) - 1)),
    )
    write_attribute_value(handle, geometry_, inode, base, attr_list, bytes(value))
    return {
        "kind": "large-attribute-list-boundary",
        "inode": inode,
        "logical_size": attr_list.data_size,
        "entry_count": len(context["entries"]),
        "entry_offset": int(entry["offset"]),
        "entry_length": int(entry["length"]),
        "entry_index": int(context["boundary_index"]),
        "reference_value_offset": reference_offset,
        "extent_inode": reference & ((1 << 48) - 1),
        "expected_sequence": record_sequence,
        "wrong_sequence": wrong_sequence,
        "stream_before_sha256": hashlib.sha256(context["value"]).hexdigest(),
        "stream_after_sha256": hashlib.sha256(value).hexdigest(),
    }


def corrupt_large_attribute_list_boundary_overrun(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> dict[str, object]:
    context = _large_attribute_list_context(handle, geometry_, inode)
    base = context["base"]
    attr_list = context["attribute"]
    value = bytearray(context["value"])
    entry = context["boundary_entry"]
    assert isinstance(base, bytearray) and isinstance(attr_list, Attribute)
    assert isinstance(entry, dict)
    entry_offset = int(entry["offset"])
    entry_length = int(entry["length"])
    wrong_length = entry_length + 8
    if entry_offset + entry_length != LARGE_ATTRIBUTE_LIST_BOUNDARY:
        raise FixtureError("boundary-overrun ALE is not the exact final entry")
    struct.pack_into("<H", value, entry_offset + 4, wrong_length)
    write_attribute_value(handle, geometry_, inode, base, attr_list, bytes(value))
    return {
        "kind": "large-attribute-list-boundary-overrun",
        "inode": inode,
        "logical_size": attr_list.data_size,
        "entry_offset": entry_offset,
        "expected_entry_length": entry_length,
        "wrong_entry_length": wrong_length,
        "claimed_entry_end": entry_offset + wrong_length,
        "stream_before_sha256": hashlib.sha256(context["value"]).hexdigest(),
        "stream_after_sha256": hashlib.sha256(value).hexdigest(),
        "tail_hex": bytes(value[-16:]).hex(),
    }


def corrupt_large_attribute_list_truncation(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> dict[str, object]:
    context = _large_attribute_list_context(handle, geometry_, inode)
    base = context["base"]
    attr_list = context["attribute"]
    value = context["value"]
    entry = context["boundary_entry"]
    assert isinstance(base, bytearray) and isinstance(attr_list, Attribute)
    assert isinstance(value, bytes) and isinstance(entry, dict)
    entry_offset = int(entry["offset"])
    entry_length = int(entry["length"])
    truncated_size = LARGE_ATTRIBUTE_LIST_BOUNDARY - 1
    if (
        truncated_size <= entry_offset
        or truncated_size >= entry_offset + entry_length
        or truncated_size >= attr_list.data_size
    ):
        raise FixtureError("large $ATTRIBUTE_LIST truncation is not inside its boundary entry")
    struct.pack_into("<Q", base, attr_list.record_offset + 48, truncated_size)
    struct.pack_into("<Q", base, attr_list.record_offset + 56, truncated_size)
    write_record(handle, geometry_, inode, base)
    return {
        "kind": "large-attribute-list-truncated",
        "inode": inode,
        "attribute_record_offset": attr_list.record_offset,
        "original_logical_size": attr_list.data_size,
        "original_initialized_size": attr_list.initialized_size,
        "allocated_size": attr_list.allocated_size,
        "truncated_size": truncated_size,
        "boundary_entry_offset": entry_offset,
        "boundary_entry_length": entry_length,
        "prefix_sha256": hashlib.sha256(value[:truncated_size]).hexdigest(),
        "truncated_tail_hex": value[truncated_size - 16 : truncated_size].hex(),
    }


def corrupt_large_attribute_list_over_limit(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> dict[str, object]:
    context = _large_attribute_list_context(handle, geometry_, inode)
    base = context["base"]
    attr_list = context["attribute"]
    value = bytearray(context["value"])
    entries = context["entries"]
    assert isinstance(base, bytearray) and isinstance(attr_list, Attribute)
    assert isinstance(entries, list)
    if (
        not attr_list.runs
        or attr_list.mapping_offset is None
        or attr_list.allocated_size != LARGE_ATTRIBUTE_LIST_BOUNDARY
    ):
        raise FixtureError("exact-cap ATTRIBUTE_LIST lacks expandable mapped storage")
    last_vcn, last_lcn, last_length = attr_list.runs[-1]
    if last_lcn is None:
        raise FixtureError("exact-cap ATTRIBUTE_LIST ends in a sparse run")
    appended_lcn = last_lcn + last_length
    if appended_lcn >= geometry_.total_clusters:
        raise FixtureError("exact-cap ATTRIBUTE_LIST has no adjacent cluster")
    cluster_bitmap = _system_stream(handle, geometry_, FILE_BITMAP, AT_DATA)
    if _read_bitmap_bit(handle, geometry_, cluster_bitmap, appended_lcn):
        raise FixtureError("exact-cap ATTRIBUTE_LIST adjacent cluster is not free")
    _, old_terminator = mapping_pair_bounds(base, attr_list)
    attribute_end = attr_list.record_offset + attr_list.record_length
    old_encoded = bytes(base[attr_list.mapping_offset : old_terminator + 1])
    opaque_slack = bytes(base[old_terminator + 1 : attribute_end])
    expanded_runs = attr_list.runs[:-1] + (
        (last_vcn, last_lcn, last_length + 1),
    )
    new_encoded = encode_mapping_pairs(expanded_runs, attr_list.lowest_vcn)
    if len(new_encoded) != len(old_encoded):
        raise FixtureError("over-limit ATTRIBUTE_LIST mapping footprint changed")
    base[attr_list.mapping_offset : old_terminator + 1] = new_encoded
    if bytes(base[old_terminator + 1 : attribute_end]) != opaque_slack:
        raise FixtureError("over-limit ATTRIBUTE_LIST changed opaque mapping slack")
    over_limit_size = LARGE_ATTRIBUTE_LIST_BOUNDARY + 8
    last_entry = entries[-1]
    last_entry_offset = int(last_entry["offset"])
    last_entry_length = int(last_entry["length"])
    if last_entry_offset + last_entry_length != LARGE_ATTRIBUTE_LIST_BOUNDARY:
        raise FixtureError("exact-cap ATTRIBUTE_LIST final ALE does not end at the ceiling")
    struct.pack_into("<H", value, last_entry_offset + 4, last_entry_length + 8)
    write_attribute_value(handle, geometry_, inode, base, attr_list, bytes(value))
    _write_exact(
        handle,
        appended_lcn * geometry_.cluster_size,
        bytes(geometry_.cluster_size),
    )
    _write_bitmap_bit(handle, geometry_, cluster_bitmap, appended_lcn, True)
    struct.pack_into(
        "<Q",
        base,
        attr_list.record_offset + 24,
        last_vcn + last_length,
    )
    struct.pack_into(
        "<Q",
        base,
        attr_list.record_offset + 40,
        attr_list.allocated_size + geometry_.cluster_size,
    )
    struct.pack_into("<Q", base, attr_list.record_offset + 48, over_limit_size)
    struct.pack_into("<Q", base, attr_list.record_offset + 56, over_limit_size)
    write_record(handle, geometry_, inode, base)

    _, _, verified_base = read_record(handle, geometry_, inode)
    verified_attr = find_attribute(verified_base, AT_ATTRIBUTE_LIST)
    verified_value = attribute_value(handle, geometry_, verified_base, verified_attr)
    verified_entries = list(attribute_list_entries(verified_value))
    _, verified_bindings = _attribute_list_bindings(handle, geometry_, inode)
    _, verified_terminator = mapping_pair_bounds(verified_base, verified_attr)
    verified_slack = bytes(
        verified_base[
            verified_terminator + 1 :
            verified_attr.record_offset + verified_attr.record_length
        ]
    )
    if (
        verified_attr.runs != expanded_runs
        or verified_attr.data_size != over_limit_size
        or verified_attr.initialized_size != over_limit_size
        or verified_attr.allocated_size
        != attr_list.allocated_size + geometry_.cluster_size
        or len(verified_entries) != len(entries)
        or len(verified_bindings) != len(entries)
        or int(verified_entries[-1]["offset"])
        + int(verified_entries[-1]["length"])
        != over_limit_size
        or verified_slack != opaque_slack
        or not _read_bitmap_bit(handle, geometry_, cluster_bitmap, appended_lcn)
    ):
        raise FixtureError("over-limit ATTRIBUTE_LIST did not round-trip structurally")
    return {
        "kind": "large-attribute-list-over-limit",
        "inode": inode,
        "attribute_record_offset": attr_list.record_offset,
        "maximum_valid_size": LARGE_ATTRIBUTE_LIST_BOUNDARY,
        "over_limit_size": over_limit_size,
        "allocated_size": verified_attr.allocated_size,
        "highest_vcn": last_vcn + last_length,
        "entry_count": len(verified_entries),
        "bound_entry_count": len(verified_bindings),
        "last_entry_offset": int(verified_entries[-1]["offset"]),
        "last_entry_length": int(verified_entries[-1]["length"]),
        "original_runs": attr_list.runs,
        "expanded_runs": expanded_runs,
        "appended_lcn": appended_lcn,
        "appended_cluster_bitmap_set": True,
        "mapping_before_hex": old_encoded.hex(),
        "mapping_after_hex": new_encoded.hex(),
        "opaque_mapping_slack_hex": opaque_slack.hex(),
        "valid_prefix_sha256": hashlib.sha256(verified_value[:0x40000]).hexdigest(),
        "stream_sha256": hashlib.sha256(verified_value).hexdigest(),
    }


def corrupt_runlist_size(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> dict[str, object]:
    _, _, record = read_record(handle, geometry_, inode)
    data = find_attribute(record, AT_DATA)
    if (
        not data.nonresident
        or not data.runs
        or data.initialized_size != data.data_size
        or data.data_size + 1 > data.allocated_size
    ):
        raise FixtureError("runlist-size fixture lacks safe initialized-size slack")
    content = read_stream(handle, geometry_, data, 0, data.data_size)
    changed = data.data_size + 1
    struct.pack_into("<Q", record, data.record_offset + 56, changed)
    write_record(handle, geometry_, inode, record)
    return {
        "kind": "runlist-size",
        "inode": inode,
        "data_size": data.data_size,
        "allocated_size": data.allocated_size,
        "expected_initialized_size": data.initialized_size,
        "wrong_initialized_size": changed,
        "runs": data.runs,
        "content_sha256": hashlib.sha256(content).hexdigest(),
    }


def corrupt_index_reserved(
    record: bytearray, attr: Attribute, description: str
) -> int:
    if attr.nonresident or attr.value_offset is None or attr.value_length is None:
        raise FixtureError(f"{description} index root is not resident")
    if attr.value_length < 32:
        raise FixtureError(f"{description} index root is too short")
    reserved_offset = attr.value_offset + 16 + 13
    if any(record[reserved_offset : reserved_offset + 3]):
        raise FixtureError(f"{description} index reserved bytes are not pristine")
    record[reserved_offset] = 0x5A
    return reserved_offset


def corrupt_reparse_index(handle: BinaryIO, geometry_: Geometry) -> dict[str, object]:
    _, _, record = read_record(handle, geometry_, FILE_REPARSE)
    index = find_attribute(record, AT_INDEX_ROOT, "$R")
    changed_offset = corrupt_index_reserved(record, index, "$Reparse/$R")
    write_record(handle, geometry_, FILE_REPARSE, record)
    return {
        "kind": "reparse-index",
        "inode": FILE_REPARSE,
        "changed_record_offset": changed_offset,
        "index_name": "$R",
    }


def corrupt_secure(handle: BinaryIO, geometry_: Geometry) -> dict[str, object]:
    _, _, record = read_record(handle, geometry_, FILE_SECURE)
    sds = find_attribute(record, AT_DATA, "$SDS")
    if not sds.nonresident or sds.data_size <= 0x40000:
        raise FixtureError("$Secure/$SDS lacks its redundant descriptor region")
    mirror_length = sds.data_size - 0x40000
    primary = read_stream(handle, geometry_, sds, 0, mirror_length)
    mirror = read_stream(handle, geometry_, sds, 0x40000, mirror_length)
    if primary != mirror or mirror_length <= 0x20:
        raise FixtureError("$Secure/$SDS copies are not pristine and redundant")
    changed_stream_offset = 0x40000 + 0x20
    write_stream(
        handle,
        geometry_,
        sds,
        changed_stream_offset,
        bytes((mirror[0x20] ^ 0x5A,)),
    )
    sdh = find_attribute(record, AT_INDEX_ROOT, "$SDH")
    sii = find_attribute(record, AT_INDEX_ROOT, "$SII")
    sdh_offset = corrupt_index_reserved(record, sdh, "$Secure/$SDH")
    sii_offset = corrupt_index_reserved(record, sii, "$Secure/$SII")
    write_record(handle, geometry_, FILE_SECURE, record)
    return {
        "kind": "secure-derived",
        "inode": FILE_SECURE,
        "sds_mirror_length": mirror_length,
        "sds_primary_sha256": hashlib.sha256(primary).hexdigest(),
        "sds_changed_stream_offset": changed_stream_offset,
        "sdh_changed_record_offset": sdh_offset,
        "sii_changed_record_offset": sii_offset,
    }


def corrupt_upcase_attrdef(handle: BinaryIO, geometry_: Geometry) -> dict[str, object]:
    _, _, upcase_record = read_record(handle, geometry_, FILE_UPCASE)
    upcase = find_attribute(upcase_record, AT_DATA)
    upcase_value = bytearray(attribute_value(handle, geometry_, upcase_record, upcase))
    upcase_offset = ord("a") * 2
    if len(upcase_value) != 65536 * 2 or struct.unpack_from("<H", upcase_value, upcase_offset)[0] != ord("A"):
        raise FixtureError("$UpCase fixture is not the canonical ASCII mapping")
    struct.pack_into("<H", upcase_value, upcase_offset, ord("b"))
    write_attribute_value(
        handle, geometry_, FILE_UPCASE, upcase_record, upcase, bytes(upcase_value)
    )

    _, _, attrdef_record = read_record(handle, geometry_, FILE_ATTRDEF)
    attrdef = find_attribute(attrdef_record, AT_DATA)
    attrdef_value = bytearray(attribute_value(handle, geometry_, attrdef_record, attrdef))
    entry_offset = None
    for offset in range(0, len(attrdef_value), 160):
        if offset + 160 > len(attrdef_value):
            break
        raw_name = bytes(attrdef_value[offset : offset + 128])
        name = raw_name.decode("utf-16-le").split("\0", 1)[0]
        if name == "$DATA":
            entry_offset = offset
            break
    if entry_offset is None or struct.unpack_from("<I", attrdef_value, entry_offset + 128)[0] != AT_DATA:
        raise FixtureError("$AttrDef lacks its canonical $DATA definition")
    struct.pack_into("<I", attrdef_value, entry_offset + 128, AT_DATA + 1)
    write_attribute_value(
        handle, geometry_, FILE_ATTRDEF, attrdef_record, attrdef, bytes(attrdef_value)
    )
    return {
        "kind": "upcase-attrdef",
        "upcase_inode": FILE_UPCASE,
        "upcase_stream_offset": upcase_offset,
        "upcase_expected": ord("A"),
        "upcase_wrong": ord("b"),
        "attrdef_inode": FILE_ATTRDEF,
        "attrdef_stream_offset": entry_offset + 128,
        "attrdef_expected_type": AT_DATA,
        "attrdef_wrong_type": AT_DATA + 1,
    }


def corrupt_upcase_nonascii(handle: BinaryIO, geometry_: Geometry) -> dict[str, object]:
    """Change one non-ASCII mapping without changing $UpCase stream size."""

    _, _, record = read_record(handle, geometry_, FILE_UPCASE)
    upcase = find_attribute(record, AT_DATA)
    value = bytearray(attribute_value(handle, geometry_, record, upcase))
    if len(value) != 65536 * 2:
        raise FixtureError("$UpCase fixture is not the canonical fixed-size table")
    codepoint = None
    expected = None
    for candidate in (0x00E0, 0x00E1, 0x03B1, 0x0430, 0x0561):
        mapped = struct.unpack_from("<H", value, candidate * 2)[0]
        if mapped != candidate and mapped >= 0x80:
            codepoint = candidate
            expected = mapped
            break
    if codepoint is None or expected is None:
        raise FixtureError("$UpCase fixture has no deterministic non-ASCII case mapping")
    wrong = codepoint
    struct.pack_into("<H", value, codepoint * 2, wrong)
    write_attribute_value(handle, geometry_, FILE_UPCASE, record, upcase, bytes(value))
    return {
        "kind": "upcase-nonascii",
        "inode": FILE_UPCASE,
        "stream_size": len(value),
        "codepoint": codepoint,
        "stream_offset": codepoint * 2,
        "expected_mapping": expected,
        "wrong_mapping": wrong,
    }


def corrupt_user_defined_runlist(
    handle: BinaryIO, geometry_: Geometry, inode: int, stream_name: str
) -> dict[str, object]:
    """Turn an ADS into a user-defined nonresident attr with a bad run length."""

    _, _, record = read_record(handle, geometry_, inode)
    stream = find_attribute(record, AT_DATA, stream_name)
    if not stream.nonresident or stream.mapping_offset is None or not stream.runs:
        raise FixtureError("user-defined fixture ADS is not a nonresident mapped stream")
    mapping = stream.mapping_offset
    header = record[mapping]
    length_width = header & 0x0F
    offset_width = header >> 4
    if (
        not length_width
        or not offset_width
        or mapping + 1 + length_width + offset_width >= stream.record_offset + stream.record_length
    ):
        raise FixtureError("user-defined fixture has no bounded first mapping pair")
    before_mapping = bytes(record[mapping : mapping + 1 + length_width + offset_width])
    if not any(record[mapping + 1 : mapping + 1 + length_width]):
        raise FixtureError("user-defined fixture run length is already zero")
    struct.pack_into("<I", record, stream.record_offset, AT_FIRST_USER_DEFINED_ATTRIBUTE)
    record[mapping + 1 : mapping + 1 + length_width] = b"\0" * length_width
    after_mapping = bytes(record[mapping : mapping + 1 + length_width + offset_width])
    write_record(handle, geometry_, inode, record)
    return {
        "kind": "user-defined-runlist",
        "inode": inode,
        "stream_name": stream_name,
        "attribute_record_offset": stream.record_offset,
        "mapping_record_offset": mapping,
        "mapping_length": len(before_mapping),
        "original_type": AT_DATA,
        "user_defined_type": AT_FIRST_USER_DEFINED_ATTRIBUTE,
        "before_mapping_hex": before_mapping.hex(),
        "after_mapping_hex": after_mapping.hex(),
    }


def mapping_pair_bounds(
    record: bytes, attribute: Attribute
) -> tuple[list[tuple[int, int, int]], int]:
    """Return raw mapping-pair (offset,length-width,offset-width) entries."""

    if not attribute.nonresident or attribute.mapping_offset is None:
        raise FixtureError("fixture attribute has no nonresident mapping pairs")
    cursor = attribute.mapping_offset
    end = attribute.record_offset + attribute.record_length
    entries: list[tuple[int, int, int]] = []
    while cursor < end:
        header = record[cursor]
        if header == 0:
            return entries, cursor
        length_width = header & 0x0F
        offset_width = header >> 4
        if (
            length_width == 0
            or length_width > 8
            or offset_width > 8
            or cursor + 1 + length_width + offset_width >= end
        ):
            raise FixtureError("fixture mapping-pair stream is not bounded")
        entries.append((cursor, length_width, offset_width))
        cursor += 1 + length_width + offset_width
    raise FixtureError("fixture mapping-pair stream lacks a terminator")


def attribute_end_offset(record: bytes) -> tuple[int, int]:
    """Return the AT_END offset and bounded FILE bytes-in-use value."""

    bytes_in_use = struct.unpack_from("<I", record, 24)[0]
    cursor = struct.unpack_from("<H", record, 20)[0]
    if (
        cursor < 24
        or bytes_in_use > len(record)
        or cursor + 4 > bytes_in_use
    ):
        raise FixtureError("attribute-tail fixture has invalid FILE bounds")
    while cursor + 4 <= bytes_in_use:
        attribute_type = struct.unpack_from("<I", record, cursor)[0]
        if attribute_type == AT_END:
            return cursor, bytes_in_use
        if cursor + 8 > bytes_in_use:
            raise FixtureError("attribute-tail fixture chain is truncated")
        length = struct.unpack_from("<I", record, cursor + 4)[0]
        if length < 24 or cursor + length > bytes_in_use:
            raise FixtureError("attribute-tail fixture chain is invalid")
        cursor += length
    raise FixtureError("attribute-tail fixture lacks AT_END inside bytes-in-use")


def _minimal_unsigned(value: int) -> bytes:
    if value <= 0:
        raise FixtureError("mapping-pair run length is not positive")
    width = max(1, (value.bit_length() + 7) // 8)
    if width > 8:
        raise FixtureError("mapping-pair run length exceeds 64 bits")
    return value.to_bytes(width, "little")


def _minimal_signed(value: int) -> bytes:
    for width in range(1, 9):
        minimum = -(1 << (width * 8 - 1))
        maximum = (1 << (width * 8 - 1)) - 1
        if minimum <= value <= maximum:
            return value.to_bytes(width, "little", signed=True)
    raise FixtureError("mapping-pair LCN delta exceeds signed 64 bits")


def encode_mapping_pairs(
    runs: tuple[tuple[int, int | None, int], ...], lowest_vcn: int
) -> bytes:
    cursor_vcn = lowest_vcn
    cursor_lcn = 0
    encoded = bytearray()
    for vcn, lcn, length in runs:
        if vcn != cursor_vcn:
            raise FixtureError("mapping-pair encoder received a VCN gap")
        length_bytes = _minimal_unsigned(length)
        offset_bytes = b""
        if lcn is not None:
            offset_bytes = _minimal_signed(lcn - cursor_lcn)
            cursor_lcn = lcn
        if len(length_bytes) > 8 or len(offset_bytes) > 8:
            raise FixtureError("mapping-pair encoder width is invalid")
        encoded.append((len(offset_bytes) << 4) | len(length_bytes))
        encoded.extend(length_bytes)
        encoded.extend(offset_bytes)
        cursor_vcn += length
    encoded.append(0)
    return bytes(encoded)


def ensure_fragmented_data(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> dict[str, object]:
    """Relocate one initialized cluster to make a clean ordinary DATA run split."""

    _, _, record = read_record(handle, geometry_, inode)
    data = find_attribute(record, AT_DATA)
    if (
        not data.nonresident
        or data.flags != 0
        or data.mapping_offset is None
        or not data.runs
        or any(lcn is None for _, lcn, _ in data.runs)
    ):
        raise FixtureError("fragment preparation needs fully mapped ordinary DATA")
    content_before = read_stream(handle, geometry_, data, 0, data.data_size)
    if len(data.runs) >= 2:
        return {
            "kind": "fragment-data",
            "inode": inode,
            "changed": False,
            "runs": data.runs,
            "content_sha256": hashlib.sha256(content_before).hexdigest(),
        }
    vcn, start_lcn, run_length = data.runs[0]
    assert start_lcn is not None
    if run_length < 2:
        raise FixtureError("fragment preparation DATA run has fewer than two clusters")

    cluster_bitmap = _system_stream(handle, geometry_, FILE_BITMAP, AT_DATA)
    bitmap_bytes = read_stream(
        handle, geometry_, cluster_bitmap, 0, (geometry_.total_clusters + 7) // 8
    )
    old_lcn = start_lcn + run_length - 1
    if not _read_bitmap_bit(handle, geometry_, cluster_bitmap, old_lcn):
        raise FixtureError("fragment preparation source cluster is not allocated")
    free_clusters = [
        candidate
        for candidate in range(24, geometry_.total_clusters)
        if not bitmap_bytes[candidate // 8] & (1 << (candidate & 7))
    ]
    if not free_clusters:
        raise FixtureError("fragment preparation found no free target cluster")
    new_lcn = min(free_clusters, key=lambda candidate: abs(candidate - old_lcn))
    relocated_runs = (
        (vcn, start_lcn, run_length - 1),
        (vcn + run_length - 1, new_lcn, 1),
    )
    encoded = encode_mapping_pairs(relocated_runs, data.lowest_vcn)
    attribute_end = data.record_offset + data.record_length
    capacity = attribute_end - data.mapping_offset
    if len(encoded) > capacity:
        at_end, bytes_in_use = attribute_end_offset(record)
        if at_end != attribute_end:
            raise FixtureError(
                "fragment preparation cannot grow a non-final DATA attribute"
            )
        extra = ((len(encoded) - capacity + 7) // 8) * 8
        if bytes_in_use + extra > len(record):
            raise FixtureError("fragment preparation MFT record lacks slack")
        record[at_end + extra : bytes_in_use + extra] = record[at_end:bytes_in_use]
        record[at_end : at_end + extra] = bytes(extra)
        struct.pack_into(
            "<I", record, data.record_offset + 4, data.record_length + extra
        )
        struct.pack_into("<I", record, 24, bytes_in_use + extra)
        attribute_end += extra
        capacity += extra
    if len(encoded) > capacity:
        raise FixtureError("fragment preparation runlist still does not fit")

    old_cluster = _read_exact(
        handle, old_lcn * geometry_.cluster_size, geometry_.cluster_size
    )
    _write_exact(handle, new_lcn * geometry_.cluster_size, old_cluster)
    _write_bitmap_bit(handle, geometry_, cluster_bitmap, new_lcn, True)
    _write_bitmap_bit(handle, geometry_, cluster_bitmap, old_lcn, False)

    record[data.mapping_offset:attribute_end] = bytes(capacity)
    record[data.mapping_offset : data.mapping_offset + len(encoded)] = encoded
    changed = find_attribute(record, AT_DATA)
    if changed.runs != relocated_runs or changed.flags != 0:
        raise FixtureError("fragment preparation runlist did not round-trip")
    write_record(handle, geometry_, inode, record)

    _, _, verified_record = read_record(handle, geometry_, inode)
    verified = find_attribute(verified_record, AT_DATA)
    content_after = read_stream(handle, geometry_, verified, 0, verified.data_size)
    if (
        verified.runs != relocated_runs
        or content_after != content_before
        or _read_bitmap_bit(handle, geometry_, cluster_bitmap, old_lcn)
        or not _read_bitmap_bit(handle, geometry_, cluster_bitmap, new_lcn)
    ):
        raise FixtureError("fragment preparation failed content/allocation verification")
    return {
        "kind": "fragment-data",
        "inode": inode,
        "changed": True,
        "original_runs": data.runs,
        "runs": relocated_runs,
        "old_lcn_released": old_lcn,
        "new_lcn_allocated": new_lcn,
        "content_sha256": hashlib.sha256(content_after).hexdigest(),
    }


def corrupt_unflagged_sparse_run(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> dict[str, object]:
    """Turn the last of multiple DATA runs into a valid but unflagged hole."""

    _, _, record = read_record(handle, geometry_, inode)
    data = find_attribute(record, AT_DATA)
    if not data.nonresident or data.flags != 0 or len(data.runs) < 2:
        raise FixtureError(
            "unflagged sparse fixture needs a multi-run ordinary DATA stream"
        )
    if any(lcn is None for _, lcn, _ in data.runs):
        raise FixtureError("unflagged sparse fixture already contains a sparse run")
    entries, terminator = mapping_pair_bounds(record, data)
    if len(entries) != len(data.runs):
        raise FixtureError("mapping-pair/run census differs before sparse mutation")
    pair_offset, length_width, offset_width = entries[-1]
    if offset_width == 0 or data.runs[-1][1] is None:
        raise FixtureError("last fixture run is already sparse")
    attribute_end = data.record_offset + data.record_length
    original_tail = bytes(record[terminator + 1 : attribute_end])
    before_mapping = bytes(record[data.mapping_offset:attribute_end])
    remainder_start = pair_offset + 1 + length_width + offset_width
    destination = pair_offset + 1 + length_width
    remainder = bytes(record[remainder_start:attribute_end])
    record[pair_offset] = length_width
    record[destination:destination + len(remainder)] = remainder
    record[attribute_end - offset_width:attribute_end] = bytes(offset_width)
    mutated = find_attribute(record, AT_DATA)
    if (
        mutated.flags != data.flags
        or mutated.instance != data.instance
        or len(mutated.runs) != len(data.runs)
        or mutated.runs[:-1] != data.runs[:-1]
        or mutated.runs[-1][0] != data.runs[-1][0]
        or mutated.runs[-1][1] is not None
        or mutated.runs[-1][2] != data.runs[-1][2]
    ):
        raise FixtureError("unflagged sparse mutation changed more than the last LCN")
    after_mapping = bytes(record[data.mapping_offset:attribute_end])
    mutated_terminator = terminator - offset_width
    mutated_tail = bytes(record[mutated_terminator + 1 : attribute_end])
    if after_mapping == before_mapping or record[terminator - offset_width] != 0:
        raise FixtureError("unflagged sparse mutation did not move its terminator")
    write_record(handle, geometry_, inode, record)
    return {
        "kind": "unflagged-sparse-run",
        "inode": inode,
        "attribute_instance": data.instance,
        "attribute_flags": data.flags,
        "mapping_record_offset": data.mapping_offset,
        "mapping_length": data.record_length - (data.mapping_offset - data.record_offset),
        "original_terminator_record_offset": terminator,
        "mutated_terminator_record_offset": terminator - offset_width,
        "original_tail_length": len(original_tail),
        "original_tail_hex": original_tail.hex(),
        "mutated_tail_hex": mutated_tail.hex(),
        "opaque_post_terminator_slack": True,
        "original_runs": data.runs,
        "mutated_runs": mutated.runs,
        "before_mapping_hex": before_mapping.hex(),
        "after_mapping_hex": after_mapping.hex(),
    }


def corrupt_mapping_pair_tail(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> dict[str, object]:
    """Vary opaque post-terminator slack without touching encoded pairs."""

    _, _, record = read_record(handle, geometry_, inode)
    data = find_attribute(record, AT_DATA)
    _, terminator = mapping_pair_bounds(record, data)
    attribute_end = data.record_offset + data.record_length
    original_tail = bytes(record[terminator + 1 : attribute_end])
    if not original_tail or any(original_tail):
        raise FixtureError("mapping-pair fixture tail is not wholly zero")
    assert data.mapping_offset is not None
    encoded = bytes(record[data.mapping_offset : terminator + 1])
    tail_offset = terminator + 1
    record[tail_offset] = 0xA5
    write_record(handle, geometry_, inode, record)
    return {
        "kind": "mapping-pair-tail",
        "inode": inode,
        "attribute_instance": data.instance,
        "attribute_flags": data.flags,
        "runs": data.runs,
        "encoded_mapping_hex": encoded.hex(),
        "encoded_mapping_sha256": hashlib.sha256(encoded).hexdigest(),
        "terminator_record_offset": terminator,
        "tail_record_offset": tail_offset,
        "tail_length": len(original_tail),
        "before_tail_hex": original_tail.hex(),
        "tail_value": 0xA5,
    }


LAYOUT_CANDIDATE_KINDS = (
    "layout-attrs-offset-candidate",
    "layout-attrs-offset-ambiguous",
    "layout-bytes-in-use-candidate",
    "layout-bytes-in-use-ambiguous",
    "layout-bytes-in-use-dual-chain",
    "layout-next-instance-candidate",
    "layout-next-instance-wrap-candidate",
    "layout-resident-value-candidate",
    "layout-resident-name-candidate",
    "layout-resident-length-candidate",
    "layout-resident-ambiguous",
)


def _normalize_mft_sequence(record: bytes) -> bytes:
    """Remove the expected MST sequence-number write side effect from a record."""

    normalized = bytearray(record)
    usa_offset = struct.unpack_from("<H", normalized, 4)[0]
    if usa_offset < 8 or usa_offset + 2 > len(normalized):
        raise FixtureError("layout candidate has an invalid USA offset")
    normalized[usa_offset : usa_offset + 2] = b"\0\0"
    return bytes(normalized)


def _changed_ranges(before: bytes, after: bytes) -> list[dict[str, object]]:
    if len(before) != len(after):
        raise FixtureError("layout candidate changed the MFT record size")
    ranges: list[dict[str, object]] = []
    cursor = 0
    while cursor < len(before):
        if before[cursor] == after[cursor]:
            cursor += 1
            continue
        start = cursor
        while cursor < len(before) and before[cursor] != after[cursor]:
            cursor += 1
        ranges.append(
            {
                "record_offset": start,
                "length": cursor - start,
                "before_hex": before[start:cursor].hex(),
                "after_hex": after[start:cursor].hex(),
            }
        )
    if not ranges:
        raise FixtureError("layout candidate mutation changed no logical bytes")
    return ranges


def _bytes_outside_ranges(
    value: bytes, ranges: list[dict[str, object]]
) -> bytes:
    parts: list[bytes] = []
    cursor = 0
    for changed in ranges:
        start = int(changed["record_offset"])
        length = int(changed["length"])
        if start < cursor or start + length > len(value):
            raise FixtureError("layout candidate change ranges overlap or exceed record")
        parts.append(value[cursor:start])
        cursor = start + length
    parts.append(value[cursor:])
    return b"".join(parts)


def _layout_candidate_context(record: bytes) -> dict[str, object]:
    attrs = list(attributes(record))
    attrs_offset = struct.unpack_from("<H", record, 20)[0]
    bytes_in_use = struct.unpack_from("<I", record, 24)[0]
    next_instance = struct.unpack_from("<H", record, 40)[0]
    at_end, bounded_used = attribute_end_offset(record)
    if bounded_used != bytes_in_use or at_end + 8 != bytes_in_use:
        raise FixtureError("layout fixture is not in exact packed FILE-record form")
    if not attrs or attrs[0].record_offset != attrs_offset:
        raise FixtureError("layout fixture does not begin with a parsed attribute")
    if any(attr.record_length % 8 for attr in attrs):
        raise FixtureError("layout fixture has a noncanonical attribute length")
    instances = [attr.instance for attr in attrs]
    if len(instances) != len(set(instances)) or next_instance <= max(instances):
        raise FixtureError("layout fixture instance counter is not initially valid")
    resident = next(
        (
            attr
            for attr in attrs
            if attr.type == AT_DATA
            and attr.name == "layoutResident"
            and not attr.nonresident
        ),
        None,
    )
    if resident is None or resident.value_offset is None or resident.value_length is None:
        raise FixtureError("layout fixture lacks its named resident DATA authority")
    name_length = record[resident.record_offset + 9]
    name_offset = struct.unpack_from("<H", record, resident.record_offset + 10)[0]
    value_relative = resident.value_offset - resident.record_offset
    name_start = resident.record_offset + name_offset
    name_end = name_start + name_length * 2
    value_end = resident.value_offset + resident.value_length
    if (
        name_length != len("layoutResident")
        or bytes(record[name_start:name_end]).decode("utf-16-le") != "layoutResident"
        or value_relative % 8
        or resident.record_length % 8
        or name_end > resident.value_offset
        or value_end > resident.record_offset + resident.record_length
    ):
        raise FixtureError("layout fixture named resident DATA is not canonically packed")
    return {
        "attrs_offset": attrs_offset,
        "bytes_in_use": bytes_in_use,
        "next_attr_instance": next_instance,
        "at_end_offset": at_end,
        "attribute_count": len(attrs),
        "attribute_instances": instances,
        "max_attribute_instance": max(instances),
        "attribute_chain_sha256": hashlib.sha256(
            record[attrs_offset:bytes_in_use]
        ).hexdigest(),
        "resident_record_offset": resident.record_offset,
        "resident_record_length": resident.record_length,
        "resident_instance": resident.instance,
        "resident_name_length": name_length,
        "resident_name_offset": name_offset,
        "resident_name_record_offset": name_start,
        "resident_name_hex": bytes(record[name_start:name_end]).hex(),
        "resident_name_sha256": hashlib.sha256(
            record[name_start:name_end]
        ).hexdigest(),
        "resident_value_offset": value_relative,
        "resident_value_record_offset": resident.value_offset,
        "resident_value_length": resident.value_length,
        "resident_value_hex": bytes(record[resident.value_offset:value_end]).hex(),
        "resident_value_sha256": hashlib.sha256(
            record[resident.value_offset:value_end]
        ).hexdigest(),
    }


def corrupt_layout_candidate(
    handle: BinaryIO, geometry_: Geometry, inode: int, kind: str
) -> dict[str, object]:
    """Create one raw FILE/ATTR_RECORD layout candidate without applying ID7."""

    if kind not in LAYOUT_CANDIDATE_KINDS:
        raise FixtureError(f"unknown raw-MFT layout candidate {kind!r}")
    record_offset, raw_before, before = read_record(handle, geometry_, inode)
    canonical = _layout_candidate_context(before)
    after = bytearray(before)
    attrs_offset = int(canonical["attrs_offset"])
    bytes_in_use = int(canonical["bytes_in_use"])
    at_end = int(canonical["at_end_offset"])
    resident_offset = int(canonical["resident_record_offset"])
    resident_length = int(canonical["resident_record_length"])
    resident_name_offset = int(canonical["resident_name_offset"])
    resident_value_offset = int(canonical["resident_value_offset"])
    name_start = int(canonical["resident_name_record_offset"])
    name_length = len(bytes.fromhex(str(canonical["resident_name_hex"])))
    value_start = int(canonical["resident_value_record_offset"])
    value_length = int(canonical["resident_value_length"])
    authority = "DERIVABLE_LAYOUT_CANDIDATE"
    reason: str
    plausible_bytes_in_use_candidates: list[int] = []
    second_at_end_record_offset: int | None = None

    if kind == "layout-attrs-offset-candidate":
        struct.pack_into("<H", after, 20, attrs_offset + 8)
        reason = "intact strict attribute chain begins at the sole canonical offset"
    elif kind == "layout-attrs-offset-ambiguous":
        struct.pack_into("<H", after, 20, attrs_offset + 8)
        after[attrs_offset : attrs_offset + 16] = b"\xa6" * 16
        authority = "AMBIGUOUS_NO_LAYOUT_AUTHORITY"
        reason = "the declared start and the only original first header are both invalid"
    elif kind == "layout-bytes-in-use-candidate":
        struct.pack_into("<I", after, 24, bytes_in_use - 8)
        reason = "the intact unique AT_END plus its zero length dword bounds the packed chain"
    elif kind == "layout-bytes-in-use-ambiguous":
        struct.pack_into("<I", after, 24, bytes_in_use - 8)
        after[at_end : at_end + 8] = b"\xa7" * 8
        authority = "AMBIGUOUS_NO_LAYOUT_AUTHORITY"
        reason = "bytes_in_use excludes the chain end and the original AT_END is destroyed"
    elif kind == "layout-bytes-in-use-dual-chain":
        if bytes_in_use + 8 > len(after) or any(after[bytes_in_use : bytes_in_use + 8]):
            raise FixtureError("layout dual-chain fixture lacks pristine record slack")
        struct.pack_into("<I", after, 24, bytes_in_use - 8)
        struct.pack_into("<II", after, bytes_in_use, AT_END, 0)
        authority = "AMBIGUOUS_MULTIPLE_PACKED_ENDS"
        reason = (
            "the intact original AT_END and a second exact AT_END at the old "
            "bytes_in_use position admit two syntactically packed candidates"
        )
        plausible_bytes_in_use_candidates = [bytes_in_use, bytes_in_use + 8]
        second_at_end_record_offset = bytes_in_use
    elif kind == "layout-next-instance-candidate":
        struct.pack_into("<H", after, 40, int(canonical["max_attribute_instance"]))
        authority = "DERIVABLE_ALLOCATOR_CURSOR"
        reason = "d4 derives the allocator cursor as (max live instance + 1) modulo 65536"
    elif kind == "layout-next-instance-wrap-candidate":
        struct.pack_into("<H", after, resident_offset + 14, 0xFFFF)
        struct.pack_into("<H", after, 40, 1)
        authority = "DERIVABLE_ALLOCATOR_CURSOR"
        reason = "a live instance 65535 derives the wrapped allocator cursor exactly as zero"
    elif kind == "layout-resident-value-candidate":
        struct.pack_into("<H", after, resident_offset + 20, resident_value_offset + 1)
        reason = "the exact resident value and zero alignment gap remain at one aligned offset"
    elif kind == "layout-resident-name-candidate":
        struct.pack_into("<H", after, resident_offset + 10, resident_name_offset + 1)
        reason = "the exact UTF-16LE attribute name remains at one bounded header offset"
    elif kind == "layout-resident-length-candidate":
        struct.pack_into("<I", after, resident_offset + 4, resident_length + 1)
        reason = "the following exact attribute boundary fixes the sole aligned record length"
    else:
        struct.pack_into("<I", after, resident_offset + 4, resident_length + 1)
        struct.pack_into("<H", after, resident_offset + 10, resident_name_offset + 1)
        struct.pack_into("<H", after, resident_offset + 20, resident_value_offset + 1)
        after[name_start : name_start + name_length] = b"\xd1" * name_length
        after[value_start : value_start + value_length] = b"\xd2" * value_length
        authority = "AMBIGUOUS_NO_SEMANTIC_AUTHORITY"
        reason = "resident packing fields and both name/value semantic bytes are destroyed"

    normalized_before = _normalize_mft_sequence(before)
    normalized_planned = _normalize_mft_sequence(after)
    planned_ranges = _changed_ranges(normalized_before, normalized_planned)
    write_record(handle, geometry_, inode, after)
    observed_offset, raw_after, observed = read_record(handle, geometry_, inode)
    if observed_offset != record_offset:
        raise FixtureError("layout candidate MFT record moved during raw mutation")
    normalized_after = _normalize_mft_sequence(observed)
    if normalized_after != normalized_planned:
        raise FixtureError("layout candidate mutation changed unintended logical bytes")
    changed = _changed_ranges(normalized_before, normalized_after)
    if changed != planned_ranges:
        raise FixtureError("layout candidate changed-range inventory is unstable")
    for item in changed:
        item["device_offset"] = record_offset + int(item["record_offset"])
    repair_required = kind in (
        "layout-next-instance-candidate",
        "layout-next-instance-wrap-candidate",
    )
    candidate_max_instance = (
        0xFFFF
        if kind == "layout-next-instance-wrap-candidate"
        else int(canonical["max_attribute_instance"])
    )
    return {
        "kind": kind,
        "inode": inode,
        "record_device_offset": record_offset,
        "record_size": len(before),
        "typed_action_id": 7,
        "typed_apply_required": True,
        "expected_check_result": "unsafe",
        "expected_repair_result": (
            "success-after-fresh-rescan"
            if repair_required
            else "refused-no-write-until-ID7"
        ),
        "repair_required": repair_required,
        "evidence_class": authority,
        "evidence_reason": reason,
        "candidate_max_attribute_instance": candidate_max_instance,
        "expected_repaired_next_attr_instance": (
            (candidate_max_instance + 1) & 0xFFFF
            if repair_required
            else None
        ),
        "prepared_instance_record_offset": (
            resident_offset + 14
            if kind == "layout-next-instance-wrap-candidate"
            else None
        ),
        "prepared_instance_value": (
            0xFFFF if kind == "layout-next-instance-wrap-candidate" else None
        ),
        "plausible_bytes_in_use_candidates": plausible_bytes_in_use_candidates,
        "second_at_end_record_offset": second_at_end_record_offset,
        "canonical": canonical,
        "changed_ranges": changed,
        "before_record_sha256": hashlib.sha256(normalized_before).hexdigest(),
        "after_record_sha256": hashlib.sha256(normalized_after).hexdigest(),
        "before_raw_record_sha256": hashlib.sha256(raw_before).hexdigest(),
        "after_raw_record_sha256": hashlib.sha256(raw_after).hexdigest(),
        "unchanged_bytes_sha256": hashlib.sha256(
            _bytes_outside_ranges(normalized_after, changed)
        ).hexdigest(),
        "resident_name_after_sha256": hashlib.sha256(
            normalized_after[name_start : name_start + name_length]
        ).hexdigest(),
        "resident_value_after_sha256": hashlib.sha256(
            normalized_after[value_start : value_start + value_length]
        ).hexdigest(),
    }


def corrupt_attribute_end_tail(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> dict[str, object]:
    """Place a nonzero byte after the FILE record's AT_END marker."""

    _, _, record = read_record(handle, geometry_, inode)
    cursor, bytes_in_use = attribute_end_offset(record)
    original_tail = bytes(record[cursor + 4 : bytes_in_use])
    if bytes_in_use != cursor + 8 or original_tail != bytes(4):
        raise FixtureError(
            "attribute-tail fixture lacks the exact zero AT_END length dword"
        )
    tail_offset = cursor + 4
    record[tail_offset] = 0x5A
    write_record(handle, geometry_, inode, record)
    return {
        "kind": "attribute-end-tail",
        "inode": inode,
        "at_end_record_offset": cursor,
        "tail_record_offset": tail_offset,
        "tail_length": len(original_tail),
        "before_tail_hex": original_tail.hex(),
        "tail_value": 0x5A,
        "bytes_in_use": bytes_in_use,
    }


def corrupt_secure_sii_stale(handle: BinaryIO, geometry_: Geometry) -> dict[str, object]:
    """Keep an ordered $SII key but make its $SDS offset reference stale."""

    _, _, record = read_record(handle, geometry_, FILE_SECURE)
    sii = find_attribute(record, AT_INDEX_ROOT, "$SII")
    if sii.nonresident or sii.value_offset is None or sii.value_length is None:
        raise FixtureError("$Secure/$SII fixture root is not resident")
    header = sii.value_offset + 16
    if header + 16 > sii.value_offset + sii.value_length:
        raise FixtureError("$Secure/$SII index header is truncated")
    entries_offset, index_length, allocated_size = struct.unpack_from("<III", record, header)
    if (
        entries_offset < 16
        or index_length < entries_offset
        or index_length > allocated_size
        or header + index_length > sii.value_offset + sii.value_length
    ):
        raise FixtureError("$Secure/$SII index bounds are invalid")
    cursor = header + entries_offset
    end = header + index_length
    selected = None
    while cursor + 16 <= end:
        data_offset, data_length = struct.unpack_from("<HH", record, cursor)
        length, key_length, flags = struct.unpack_from("<HHH", record, cursor + 8)
        if length < 16 or cursor + length > end:
            raise FixtureError("$Secure/$SII entry bounds are invalid")
        if not (flags & 0x0002):
            data_start = cursor + data_offset
            if (
                key_length >= 4
                and data_offset >= 16 + key_length
                and data_length >= 20
                and data_start + data_length <= cursor + length
            ):
                selected = (cursor, data_start, data_length)
                break
        cursor += length
    if selected is None:
        raise FixtureError("$Secure/$SII has no bounded descriptor entry")
    entry_offset, data_start, data_length = selected
    key_security_id = struct.unpack_from("<I", record, entry_offset + 16)[0]
    data_security_id = struct.unpack_from("<I", record, data_start + 4)[0]
    sds_offset = struct.unpack_from("<Q", record, data_start + 8)[0]
    sds_length = struct.unpack_from("<I", record, data_start + 16)[0]
    if not key_security_id or data_security_id != key_security_id or not sds_length:
        raise FixtureError("$Secure/$SII entry is not pristine")
    stale_offset = sds_offset + 1
    struct.pack_into("<Q", record, data_start + 8, stale_offset)
    write_record(handle, geometry_, FILE_SECURE, record)
    return {
        "kind": "secure-sii-stale",
        "inode": FILE_SECURE,
        "entry_record_offset": entry_offset,
        "data_record_offset": data_start,
        "data_length": data_length,
        "security_id": key_security_id,
        "expected_sds_offset": sds_offset,
        "stale_sds_offset": stale_offset,
        "sds_length": sds_length,
    }


def corrupt_link_reciprocity(
    handle: BinaryIO,
    geometry_: Geometry,
    inode: int,
    parent_inode: int,
    target_name: str,
) -> dict[str, object]:
    _, _, record = read_record(handle, geometry_, inode)
    link_count = struct.unpack_from("<H", record, 18)[0]
    if link_count < 2:
        raise FixtureError("link fixture has fewer than two hard links")
    matches: list[Attribute] = []
    for attr in attributes(record):
        if attr.type != AT_FILE_NAME or attr.nonresident:
            continue
        assert attr.value_offset is not None and attr.value_length is not None
        value = record[attr.value_offset : attr.value_offset + attr.value_length]
        if len(value) < 66:
            continue
        name_length = value[64]
        name = value[66 : 66 + name_length * 2].decode("utf-16-le")
        parent_reference = struct.unpack_from("<Q", value, 0)[0]
        if name == target_name and parent_reference & ((1 << 48) - 1) == parent_inode:
            matches.append(attr)
    if len(matches) != 1:
        raise FixtureError("hard-link fixture FILE_NAME is not unique")
    target = matches[0]
    assert target.value_offset is not None
    parent_reference = struct.unpack_from("<Q", record, target.value_offset)[0]
    parent_sequence = parent_reference >> 48
    if not parent_sequence:
        raise FixtureError("hard-link fixture parent sequence is already zero")
    struct.pack_into("<H", record, 18, link_count - 1)
    struct.pack_into(
        "<Q", record, target.value_offset,
        parent_reference & ((1 << 48) - 1),
    )
    write_record(handle, geometry_, inode, record)
    return {
        "kind": "link-reciprocity",
        "inode": inode,
        "parent_inode": parent_inode,
        "target_name": target_name,
        "expected_link_count": link_count,
        "wrong_link_count": link_count - 1,
        "expected_parent_sequence": parent_sequence,
    }


def corrupt_hardlink_value_order(
    handle: BinaryIO,
    geometry_: Geometry,
    inode: int,
    parent_inodes: tuple[int, int],
    target_name: str,
) -> dict[str, object]:
    """Reverse two equal-type resident FILE_NAME values without changing them."""

    before = inspect_hardlink_collation(
        handle, geometry_, inode, parent_inodes, target_name
    )
    if (
        before["link_count"] != 2
        or before["values_distinct"] is not True
        or before["values_collated"] is not True
        or before["all_reciprocal"] is not True
    ):
        raise FixtureError(
            "hard-link fixture is not canonically collated and reciprocal: "
            f"{before!r}"
        )
    _, _, record = read_record(handle, geometry_, inode)
    matches: list[tuple[Attribute, bytes]] = []
    for attr in attributes(record):
        if attr.type != AT_FILE_NAME:
            continue
        value = _file_name_value(record, attr)
        if (
            value["name"] == target_name
            and int(value["parent_inode"]) in parent_inodes
        ):
            matches.append(
                (
                    attr,
                    bytes(record[attr.record_offset : attr.record_offset + attr.record_length]),
                )
            )
    if len(matches) != 2:
        raise FixtureError("hard-link order fixture lacks its two FILE_NAME records")
    first, second = matches
    if (
        first[0].record_length != second[0].record_length
        or first[0].record_offset + first[0].record_length
        != second[0].record_offset
    ):
        raise FixtureError("hard-link FILE_NAME records are not equal-size and adjacent")
    record[
        first[0].record_offset : second[0].record_offset + second[0].record_length
    ] = second[1] + first[1]
    write_record(handle, geometry_, inode, record)
    after = inspect_hardlink_collation(
        handle, geometry_, inode, parent_inodes, target_name
    )
    if (
        after["resident_parent_order"]
        != list(reversed(before["resident_parent_order"]))
        or after["values_collated"] is not False
        or after["all_reciprocal"] is not True
        or sorted(after["value_sha256"]) != sorted(before["value_sha256"])
    ):
        raise FixtureError("hard-link value-order mutation changed semantic link data")
    return {
        "kind": "hardlink-value-order",
        "inode": inode,
        "parent_inodes": list(parent_inodes),
        "target_name": target_name,
        "expected_parent_order": before["resident_parent_order"],
        "wrong_parent_order": after["resident_parent_order"],
        "expected_attribute_instances": before["attribute_instances"],
        "wrong_attribute_instances": after["attribute_instances"],
        "value_sha256": sorted(before["value_sha256"]),
    }


def corrupt_sparse_unit_header(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> dict[str, object]:
    """Change only the canonical compression-unit byte of a genuine sparse DATA."""

    before = inspect_sparse_stream(handle, geometry_, inode)
    if (
        before["attribute_flags"] != ATTR_IS_SPARSE
        or before["compression_unit"] != 4
        or before["runlist_complete"] is not True
        or before["tail_run_mapped"] is not True
        or before["mapped_lcns_distinct"] is not True
        or before["mapped_cluster_bits"] != [True] * before["mapped_clusters"]
        or before["mft_bitmap_bit"] is not True
        or before["hole_all_zero"] is not True
        or before["compressed_size"] != before["physical_bytes"]
        or before["mapping_tail_opaque_slack"] is not True
        or before["mapping_tail_accepted_slack"] is not True
    ):
        raise FixtureError(
            "sparse fixture lacks complete canonical run/size authority: "
            f"{before!r}"
        )
    _, _, record = read_record(handle, geometry_, inode)
    data = find_attribute(record, AT_DATA)
    if data.record_length < 72:
        raise FixtureError("sparse attribute header cannot carry compressed_size")
    wrong_unit = 3
    record[data.record_offset + 34] = wrong_unit
    write_record(handle, geometry_, inode, record)
    after = inspect_sparse_stream(handle, geometry_, inode)
    for key in (
        "attribute_flags",
        "attribute_instance",
        "data_size",
        "initialized_size",
        "allocated_size",
        "compressed_size",
        "runs",
        "mapped_lcns",
        "logical_sha256",
        "mapping_hex",
        "mapping_tail_hex",
    ):
        if after[key] != before[key]:
            raise FixtureError(f"sparse unit mutation unexpectedly changed {key}")
    if after["compression_unit"] != wrong_unit:
        raise FixtureError("sparse unit mutation did not persist")
    return {
        "kind": "sparse-unit-header",
        "inode": inode,
        "expected_compression_unit": 4,
        "wrong_compression_unit": wrong_unit,
        "attribute_flags": before["attribute_flags"],
        "attribute_instance": before["attribute_instance"],
        "data_size": before["data_size"],
        "initialized_size": before["initialized_size"],
        "allocated_size": before["allocated_size"],
        "compressed_size": before["compressed_size"],
        "runs": before["runs"],
        "mapped_lcns": before["mapped_lcns"],
        "logical_sha256": before["logical_sha256"],
        "mapping_hex": before["mapping_hex"],
        "attribute_record_offset": before["attribute_record_offset"],
        "attribute_record_length": before["attribute_record_length"],
        "mapping_pairs_offset": before["mapping_pairs_offset"],
        "terminator_attribute_offset": before["terminator_attribute_offset"],
        "mapping_tail_length": before["mapping_tail_length"],
        "mapping_tail_hex": before["mapping_tail_hex"],
    }


def corrupt_duplicate_cluster(
    handle: BinaryIO, geometry_: Geometry, first_inode: int, second_inode: int
) -> dict[str, object]:
    _, _, first_record = read_record(handle, geometry_, first_inode)
    _, _, second_record = read_record(handle, geometry_, second_inode)
    first = find_attribute(first_record, AT_DATA)
    second = find_attribute(second_record, AT_DATA)
    if (
        not first.nonresident
        or not second.nonresident
        or len(first.runs) != 1
        or len(second.runs) != 1
        or first.runs[0][1] is None
        or second.runs[0][1] is None
        or first.runs[0][2] != second.runs[0][2]
        or first.data_size != second.data_size
        or first.initialized_size != second.initialized_size
    ):
        raise FixtureError("duplicate-cluster fixture needs two equal contiguous streams")
    first_content = read_stream(handle, geometry_, first, 0, first.data_size)
    second_content = read_stream(handle, geometry_, second, 0, second.data_size)
    if first_content != second_content:
        raise FixtureError("duplicate-cluster fixture contents are not identical")
    assert second.mapping_offset is not None
    mapping = second.mapping_offset
    header = second_record[mapping]
    length_width = header & 0x0F
    offset_width = header >> 4
    if not length_width or not offset_width or mapping + 1 + length_width + offset_width > second.record_offset + second.record_length:
        raise FixtureError("duplicate-cluster mapping pair is not patchable")
    run_length = int.from_bytes(
        second_record[mapping + 1 : mapping + 1 + length_width], "little"
    )
    if run_length != second.runs[0][2] or second_record[mapping + 1 + length_width + offset_width] != 0:
        raise FixtureError("duplicate-cluster fixture has multiple mapping pairs")
    first_lcn = int(first.runs[0][1])
    second_lcn = int(second.runs[0][1])
    minimum = -(1 << (offset_width * 8 - 1))
    maximum = (1 << (offset_width * 8 - 1)) - 1
    if not minimum <= first_lcn <= maximum:
        raise FixtureError("duplicate-cluster target LCN does not fit mapping-pair width")
    second_record[
        mapping + 1 + length_width : mapping + 1 + length_width + offset_width
    ] = first_lcn.to_bytes(offset_width, "little", signed=True)
    write_record(handle, geometry_, second_inode, second_record)
    return {
        "kind": "duplicate-cluster",
        "first_inode": first_inode,
        "second_inode": second_inode,
        "first_lcn": first_lcn,
        "second_original_lcn": second_lcn,
        "clusters": run_length,
        "data_size": first.data_size,
        "content_sha256": hashlib.sha256(first_content).hexdigest(),
    }


def corrupt_compressed_metadata(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> dict[str, object]:
    _, _, record = read_record(handle, geometry_, inode)
    data = find_attribute(record, AT_DATA)
    if (
        not data.nonresident
        or not (data.flags & 0x0001)
        or data.compression_unit != 4
        or data.compressed_size <= 0
        or data.compressed_size + geometry_.cluster_size > data.allocated_size
    ):
        raise FixtureError("compressed fixture lacks supported canonical metadata/slack")
    struct.pack_into("<B", record, data.record_offset + 34, 3)
    wrong_compressed_size = data.compressed_size + geometry_.cluster_size
    struct.pack_into("<Q", record, data.record_offset + 64, wrong_compressed_size)
    write_record(handle, geometry_, inode, record)
    return {
        "kind": "compressed-metadata",
        "inode": inode,
        "flags": data.flags,
        "runs": data.runs,
        "expected_compression_unit": data.compression_unit,
        "wrong_compression_unit": 3,
        "expected_compressed_size": data.compressed_size,
        "wrong_compressed_size": wrong_compressed_size,
        "data_size": data.data_size,
    }


def corrupt_compressed_payload(
    handle: BinaryIO, geometry_: Geometry, inode: int
) -> dict[str, object]:
    """Corrupt the on-disk LZNT1 block header, not merely attr metadata."""

    _, _, record = read_record(handle, geometry_, inode)
    data = find_attribute(record, AT_DATA)
    if (
        not data.nonresident
        or not (data.flags & 0x0001)
        or data.compression_unit != 4
        or data.initialized_size <= 0
    ):
        raise FixtureError("compressed payload fixture is not a supported compressed stream")
    allocated = next(
        ((vcn, int(lcn), length) for vcn, lcn, length in data.runs if lcn is not None),
        None,
    )
    if allocated is None:
        raise FixtureError("compressed payload fixture has no allocated run")
    vcn, lcn, run_length = allocated
    physical_offset = lcn * geometry_.cluster_size
    before = _read_exact(handle, physical_offset, 2)
    if before == b"\xff\xff":
        raise FixtureError("compressed payload header is already corrupt")
    _write_exact(handle, physical_offset, b"\xff\xff")
    return {
        "kind": "compressed-payload",
        "inode": inode,
        "logical_vcn": vcn,
        "lcn": lcn,
        "run_clusters": run_length,
        "physical_offset": physical_offset,
        "before_header_hex": before.hex(),
        "after_header_hex": "ffff",
        "data_size": data.data_size,
        "initialized_size": data.initialized_size,
    }


def apply_native_redo_primary_only(
    handle: BinaryIO, geometry_: Geometry, manifest_path: Path
) -> dict[str, object]:
    """Apply the fixture's resident redo to primary record 3, not its mirror."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != "roothealth-native-logfile-redo-v1":
        raise FixtureError("native redo manifest format is invalid")
    transaction = manifest.get("transaction")
    if not isinstance(transaction, dict) or transaction.get("target_inode") != FILE_VOLUME:
        raise FixtureError("native redo manifest does not target $Volume")
    if transaction.get("target_attribute") != "$VOLUME_NAME":
        raise FixtureError("native redo manifest does not target $VOLUME_NAME")
    before = bytes.fromhex(str(transaction.get("before_utf16le", "")))
    after = bytes.fromhex(str(transaction.get("after_utf16le", "")))
    if len(before) != 2 or len(after) != 2 or before == after:
        raise FixtureError("native redo manifest has no exact UTF-16 code-unit delta")
    _, _, primary = read_record(handle, geometry_, FILE_VOLUME)
    volume_name = find_attribute(primary, AT_VOLUME_NAME)
    if volume_name.nonresident or volume_name.value_offset is None:
        raise FixtureError("$Volume:$VOLUME_NAME is not resident")
    try:
        semantic_offset = int(transaction["record_offset"]) + int(
            transaction["attribute_offset"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise FixtureError("native redo manifest target offset is invalid") from error
    value_end = volume_name.value_offset + volume_name.value_length
    if semantic_offset < volume_name.value_offset or semantic_offset + 2 > value_end:
        raise FixtureError("native redo target falls outside $VOLUME_NAME")
    if bytes(primary[semantic_offset : semantic_offset + 2]) != before:
        raise FixtureError("primary $VOLUME_NAME does not contain the redo before-image")
    _, _, mirror = read_record(handle, geometry_, FILE_VOLUME, mirror=True)
    mirror_name = find_attribute(mirror, AT_VOLUME_NAME)
    assert mirror_name.value_offset is not None
    if bytes(mirror[semantic_offset : semantic_offset + 2]) != before:
        raise FixtureError("mirror $VOLUME_NAME does not contain the redo before-image")
    primary[semantic_offset : semantic_offset + 2] = after
    write_record(handle, geometry_, FILE_VOLUME, primary)
    return {
        "kind": "native-redo-primary-applied",
        "inode": FILE_VOLUME,
        "primary_before_hex": before.hex(),
        "primary_after_hex": after.hex(),
        "semantic_record_offset": semantic_offset,
    }


def inspect_deep_fixture(
    handle: BinaryIO, geometry_: Geometry, state: dict[str, object]
) -> dict[str, object]:
    kind = state.get("kind")
    if isinstance(kind, str) and kind.startswith("journal-"):
        record_number = int(state["journal_record"])
        journal_cluster = int(state["journal_cluster"])
        journal_runs = tuple(
            (int(item[0]), int(item[1]), int(item[2]))
            for item in state["journal_runs"]
        )
        _, _, mft_zero = read_record(handle, geometry_, FILE_MFT)
        mft_bitmap = find_attribute(mft_zero, AT_BITMAP)
        cluster_bitmap = _system_stream(handle, geometry_, FILE_BITMAP, AT_DATA)
        owners, examined = _journal_cluster_owners(
            handle, geometry_, record_number, journal_runs
        )
        overlap_inode = state.get("overlap_inode")
        overlap_lcn = None
        if isinstance(overlap_inode, int):
            _, _, overlap_record = read_record(handle, geometry_, overlap_inode)
            overlap_data = find_attribute(overlap_record, AT_DATA)
            overlap_lcn = overlap_data.runs[0][1] if overlap_data.runs else None
        return {
            "journal_allocation": {
                "mft_bit": _read_bitmap_bit(
                    handle, geometry_, mft_bitmap, record_number
                ),
                "cluster_bit": _read_bitmap_bit(
                    handle, geometry_, cluster_bitmap, journal_cluster
                ),
                "journal_cluster_owner_count": len(owners[journal_cluster]),
                "journal_cluster_owners": owners[journal_cluster],
                "ownership_records_examined": examined,
                "overlap_lcn": overlap_lcn,
            }
        }
    if kind == "volume-dirty-wiped-log":
        flags = []
        for mirror in (False, True):
            _, _, record = read_record(handle, geometry_, FILE_VOLUME, mirror=mirror)
            information = find_attribute(record, AT_VOLUME_INFORMATION)
            assert information.value_offset is not None
            flags.append(struct.unpack_from("<H", record, information.value_offset + 10)[0])
        _, _, logfile_record = read_record(handle, geometry_, FILE_LOGFILE)
        logfile = find_attribute(logfile_record, AT_DATA)
        all_ff = True
        offset = 0
        while offset < logfile.data_size:
            amount = min(1024 * 1024, logfile.data_size - offset)
            if read_stream(handle, geometry_, logfile, offset, amount) != b"\xff" * amount:
                all_ff = False
                break
            offset += amount
        return {
            "volume_dirty_wiped_log": {
                "primary_flags": flags[0],
                "mirror_flags": flags[1],
                "logfile_size": logfile.data_size,
                "logfile_all_ff": all_ff,
            }
        }
    if kind == "dirty-log":
        flags = []
        for mirror in (False, True):
            _, _, record = read_record(handle, geometry_, FILE_VOLUME, mirror=mirror)
            information = find_attribute(record, AT_VOLUME_INFORMATION)
            assert information.value_offset is not None
            flags.append(
                struct.unpack_from("<H", record, information.value_offset + 10)[0]
            )
        _, _, logfile_record = read_record(handle, geometry_, FILE_LOGFILE)
        logfile = find_attribute(logfile_record, AT_DATA)
        pages = [
            read_stream(handle, geometry_, logfile, index * 4096, 4096)
            for index in range(2)
        ]
        return {
            "dirty_log": {
                "primary_flags": flags[0],
                "mirror_flags": flags[1],
                "logfile_size": logfile.data_size,
                "restart_magic": [page[:4].decode("ascii", "replace") for page in pages],
                "restart_usa": [struct.unpack_from("<H", page, 32)[0] for page in pages],
                "restart_page_sha256": [
                    hashlib.sha256(page).hexdigest() for page in pages
                ],
            }
        }
    if kind == "attribute-list":
        return {"attribute_list": inspect_attribute_list(handle, geometry_, state)}
    if kind == "large-attribute-list":
        return {
            "large_attribute_list": inspect_large_attribute_list(
                handle, geometry_, int(state["inode"])
            )
        }
    if kind == "large-attribute-list-boundary":
        inode = int(state["inode"])
        _, _, base = read_record(handle, geometry_, inode)
        attr_list = find_attribute(base, AT_ATTRIBUTE_LIST)
        value = attribute_value(handle, geometry_, base, attr_list)
        entries = list(attribute_list_entries(value))
        matches = [
            entry
            for entry in entries
            if int(entry["offset"]) == int(state["entry_offset"])
        ]
        if len(matches) != 1:
            raise FixtureError("large boundary entry is no longer unique")
        entry = matches[0]
        reference = int(entry["reference"])
        extent_inode = reference & ((1 << 48) - 1)
        _, _, extent = read_record(handle, geometry_, extent_inode)
        extent_sequence = struct.unpack_from("<H", extent, 16)[0]
        return {
            "large_attribute_list_boundary": {
                "nonresident": attr_list.nonresident,
                "logical_size": attr_list.data_size,
                "entry_count": len(entries),
                "entry_offset": int(entry["offset"]),
                "entry_length": int(entry["length"]),
                "reference_sequence": reference >> 48,
                "extent_inode": extent_inode,
                "extent_sequence": extent_sequence,
                "stream_sha256": hashlib.sha256(value).hexdigest(),
            }
        }
    if kind == "large-attribute-list-boundary-overrun":
        inode = int(state["inode"])
        _, _, base = read_record(handle, geometry_, inode)
        attr_list = find_attribute(base, AT_ATTRIBUTE_LIST)
        value = attribute_value(handle, geometry_, base, attr_list)
        entry_offset = int(state["entry_offset"])
        entry_length = struct.unpack_from("<H", value, entry_offset + 4)[0]
        parse_rejected = False
        parsed_entries = 0
        try:
            parsed_entries = len(list(attribute_list_entries(value)))
        except FixtureError:
            parse_rejected = True
        return {
            "large_attribute_list_boundary_overrun": {
                "nonresident": attr_list.nonresident,
                "logical_size": attr_list.data_size,
                "initialized_size": attr_list.initialized_size,
                "allocated_size": attr_list.allocated_size,
                "entry_offset": entry_offset,
                "entry_length": entry_length,
                "claimed_entry_end": entry_offset + entry_length,
                "stream_sha256": hashlib.sha256(value).hexdigest(),
                "tail_hex": value[-16:].hex(),
                "parse_rejected": parse_rejected,
                "parsed_entries": parsed_entries,
            }
        }
    if kind == "large-attribute-list-truncated":
        inode = int(state["inode"])
        _, _, base = read_record(handle, geometry_, inode)
        attr_list = find_attribute(base, AT_ATTRIBUTE_LIST)
        value = attribute_value(handle, geometry_, base, attr_list)
        parse_rejected = False
        parsed_entries = 0
        try:
            parsed_entries = len(list(attribute_list_entries(value)))
        except FixtureError:
            parse_rejected = True
        return {
            "large_attribute_list_truncated": {
                "nonresident": attr_list.nonresident,
                "logical_size": attr_list.data_size,
                "initialized_size": attr_list.initialized_size,
                "allocated_size": attr_list.allocated_size,
                "prefix_sha256": hashlib.sha256(value).hexdigest(),
                "tail_hex": value[-16:].hex(),
                "parse_rejected": parse_rejected,
                "parsed_entries": parsed_entries,
            }
        }
    if kind == "large-attribute-list-over-limit":
        inode = int(state["inode"])
        _, _, base = read_record(handle, geometry_, inode)
        attr_list = find_attribute(base, AT_ATTRIBUTE_LIST)
        value = attribute_value(handle, geometry_, base, attr_list)
        entries = list(attribute_list_entries(value))
        _, bindings = _attribute_list_bindings(handle, geometry_, inode)
        _, terminator = mapping_pair_bounds(base, attr_list)
        attribute_end = attr_list.record_offset + attr_list.record_length
        cluster_bitmap = _system_stream(handle, geometry_, FILE_BITMAP, AT_DATA)
        return {
            "large_attribute_list_over_limit": {
                "nonresident": attr_list.nonresident,
                "logical_size": attr_list.data_size,
                "initialized_size": attr_list.initialized_size,
                "allocated_size": attr_list.allocated_size,
                "maximum_valid_size": int(state["maximum_valid_size"]),
                "highest_vcn": struct.unpack_from(
                    "<Q", base, attr_list.record_offset + 24
                )[0],
                "run_count": len(attr_list.runs),
                "runs": attr_list.runs,
                "entry_count": len(entries),
                "bound_entry_count": len(bindings),
                "last_entry_offset": int(entries[-1]["offset"]),
                "last_entry_length": int(entries[-1]["length"]),
                "last_entry_end": int(entries[-1]["offset"])
                + int(entries[-1]["length"]),
                "appended_lcn": int(state["appended_lcn"]),
                "appended_cluster_bitmap_set": _read_bitmap_bit(
                    handle,
                    geometry_,
                    cluster_bitmap,
                    int(state["appended_lcn"]),
                ),
                "mapping_hex": bytes(
                    base[attr_list.mapping_offset : terminator + 1]
                ).hex() if attr_list.mapping_offset is not None else None,
                "opaque_mapping_slack_hex": bytes(
                    base[terminator + 1 : attribute_end]
                ).hex(),
                "valid_prefix_sha256": hashlib.sha256(
                    value[: int(state["maximum_valid_size"])]
                ).hexdigest(),
                "stream_sha256": hashlib.sha256(value).hexdigest(),
            }
        }
    if kind in ("attribute-list-hardlink", "attribute-list-equal-triple-order"):
        parent_inodes = tuple(int(value) for value in state["parent_inodes"])
        if len(parent_inodes) != 2:
            raise FixtureError("ATTRIBUTE_LIST hard-link state needs two parents")
        return {
            "attribute_list_hardlink": inspect_attribute_list_hardlinks(
                handle,
                geometry_,
                int(state["inode"]),
                (parent_inodes[0], parent_inodes[1]),
                str(state["target_name"]),
            )
        }
    if kind == "runlist-size":
        _, _, record = read_record(handle, geometry_, int(state["inode"]))
        data = find_attribute(record, AT_DATA)
        content = read_stream(handle, geometry_, data, 0, data.data_size)
        return {
            "runlist_size": {
                "data_size": data.data_size,
                "initialized_size": data.initialized_size,
                "allocated_size": data.allocated_size,
                "runs": data.runs,
                "content_sha256": hashlib.sha256(content).hexdigest(),
            }
        }
    if kind == "unflagged-sparse-run":
        _, _, record = read_record(handle, geometry_, int(state["inode"]))
        data = find_attribute(record, AT_DATA)
        _, terminator = mapping_pair_bounds(record, data)
        attribute_end = data.record_offset + data.record_length
        return {
            "unflagged_sparse_run": {
                "attribute_flags": data.flags,
                "attribute_instance": data.instance,
                "runs": data.runs,
                "sparse_run_count": sum(
                    1 for _, lcn, _ in data.runs if lcn is None
                ),
                "terminator_record_offset": terminator,
                "tail_hex": bytes(record[terminator + 1 : attribute_end]).hex(),
                "mapping_hex": bytes(
                    record[
                        data.mapping_offset:
                        data.record_offset + data.record_length
                    ]
                ).hex(),
            }
        }
    if kind == "mapping-pair-tail":
        _, _, record = read_record(handle, geometry_, int(state["inode"]))
        data = find_attribute(record, AT_DATA)
        _, terminator = mapping_pair_bounds(record, data)
        attribute_end = data.record_offset + data.record_length
        tail = bytes(record[terminator + 1 : attribute_end])
        return {
            "mapping_pair_tail": {
                "attribute_flags": data.flags,
                "attribute_instance": data.instance,
                "runs": data.runs,
                "encoded_mapping_hex": bytes(
                    record[data.mapping_offset : terminator + 1]
                ).hex() if data.mapping_offset is not None else None,
                "encoded_mapping_sha256": hashlib.sha256(
                    bytes(record[data.mapping_offset : terminator + 1])
                ).hexdigest() if data.mapping_offset is not None else None,
                "terminator_record_offset": terminator,
                "tail_record_offset": terminator + 1,
                "tail_hex": tail.hex(),
                "tail_nonzero_record_offsets": [
                    terminator + 1 + index
                    for index, value in enumerate(tail)
                    if value
                ],
                "opaque_ignored_slack": True,
            }
        }
    if kind in LAYOUT_CANDIDATE_KINDS:
        record_offset, raw, record = read_record(
            handle, geometry_, int(state["inode"])
        )
        normalized = _normalize_mft_sequence(record)
        changed = state.get("changed_ranges")
        canonical = state.get("canonical")
        if not isinstance(changed, list) or not isinstance(canonical, dict):
            raise FixtureError("layout candidate state lacks its raw evidence")
        reconstructed = bytearray(normalized)
        observed_ranges: list[dict[str, object]] = []
        ranges_match = True
        for item in changed:
            if not isinstance(item, dict):
                raise FixtureError("layout candidate state has a malformed range")
            offset = int(item["record_offset"])
            length = int(item["length"])
            current = bytes(normalized[offset : offset + length])
            after = bytes.fromhex(str(item["after_hex"]))
            before = bytes.fromhex(str(item["before_hex"]))
            if len(current) != length or len(after) != length or len(before) != length:
                raise FixtureError("layout candidate range length is inconsistent")
            ranges_match = ranges_match and current == after
            reconstructed[offset : offset + length] = before
            observed_ranges.append(
                {
                    "record_offset": offset,
                    "device_offset": record_offset + offset,
                    "length": length,
                    "current_hex": current.hex(),
                    "matches_after": current == after,
                }
            )
        resident_offset = int(canonical["resident_record_offset"])
        name_start = int(canonical["resident_name_record_offset"])
        name_length = len(bytes.fromhex(str(canonical["resident_name_hex"])))
        value_start = int(canonical["resident_value_record_offset"])
        value_length = int(canonical["resident_value_length"])
        return {
            "layout_candidate": {
                "kind": kind,
                "inode": int(state["inode"]),
                "record_device_offset": record_offset,
                "record_size": len(record),
                "evidence_class": state["evidence_class"],
                "typed_action_id": state["typed_action_id"],
                "typed_apply_required": state["typed_apply_required"],
                "repair_required": state["repair_required"],
                "candidate_max_attribute_instance": state[
                    "candidate_max_attribute_instance"
                ],
                "expected_repaired_next_attr_instance": state[
                    "expected_repaired_next_attr_instance"
                ],
                "prepared_instance_value": (
                    struct.unpack_from(
                        "<H", record, int(state["prepared_instance_record_offset"])
                    )[0]
                    if state["prepared_instance_record_offset"] is not None
                    else None
                ),
                "plausible_bytes_in_use_candidates": state[
                    "plausible_bytes_in_use_candidates"
                ],
                "second_at_end_hex": (
                    bytes(
                        record[
                            int(state["second_at_end_record_offset"]):
                            int(state["second_at_end_record_offset"]) + 8
                        ]
                    ).hex()
                    if state["second_at_end_record_offset"] is not None
                    else None
                ),
                "attrs_offset": struct.unpack_from("<H", record, 20)[0],
                "bytes_in_use": struct.unpack_from("<I", record, 24)[0],
                "next_attr_instance": struct.unpack_from("<H", record, 40)[0],
                "resident_record_length": struct.unpack_from(
                    "<I", record, resident_offset + 4
                )[0],
                "resident_name_offset": struct.unpack_from(
                    "<H", record, resident_offset + 10
                )[0],
                "resident_value_offset": struct.unpack_from(
                    "<H", record, resident_offset + 20
                )[0],
                "resident_name_sha256": hashlib.sha256(
                    normalized[name_start : name_start + name_length]
                ).hexdigest(),
                "resident_value_sha256": hashlib.sha256(
                    normalized[value_start : value_start + value_length]
                ).hexdigest(),
                "record_sha256": hashlib.sha256(normalized).hexdigest(),
                "raw_record_sha256": hashlib.sha256(raw).hexdigest(),
                "reconstructed_before_sha256": hashlib.sha256(
                    reconstructed
                ).hexdigest(),
                "unchanged_bytes_sha256": hashlib.sha256(
                    _bytes_outside_ranges(normalized, changed)
                ).hexdigest(),
                "changed_ranges": observed_ranges,
                "changed_ranges_match": ranges_match,
            }
        }
    if kind == "attribute-end-tail":
        _, _, record = read_record(handle, geometry_, int(state["inode"]))
        at_end, bytes_in_use = attribute_end_offset(record)
        tail = bytes(record[at_end + 4 : bytes_in_use])
        return {
            "attribute_end_tail": {
                "at_end_record_offset": at_end,
                "at_end_value": struct.unpack_from("<I", record, at_end)[0],
                "tail_record_offset": at_end + 4,
                "tail_hex": tail.hex(),
                "tail_nonzero_record_offsets": [
                    at_end + 4 + index
                    for index, value in enumerate(tail)
                    if value
                ],
                "bytes_in_use": bytes_in_use,
            }
        }
    if kind == "reparse-index":
        _, _, record = read_record(handle, geometry_, FILE_REPARSE)
        index = find_attribute(record, AT_INDEX_ROOT, "$R")
        assert index.value_offset is not None
        return {
            "reparse_index": {
                "reserved": bytes(
                    record[index.value_offset + 16 + 13 : index.value_offset + 16 + 16]
                ).hex()
            }
        }
    if kind == "secure-derived":
        _, _, record = read_record(handle, geometry_, FILE_SECURE)
        sds = find_attribute(record, AT_DATA, "$SDS")
        mirror_length = int(state["sds_mirror_length"])
        primary = read_stream(handle, geometry_, sds, 0, mirror_length)
        mirror = read_stream(handle, geometry_, sds, 0x40000, mirror_length)
        roots: dict[str, str] = {}
        for name in ("$SDH", "$SII"):
            index = find_attribute(record, AT_INDEX_ROOT, name)
            assert index.value_offset is not None
            roots[name] = bytes(
                record[index.value_offset + 16 + 13 : index.value_offset + 16 + 16]
            ).hex()
        return {
            "secure_derived": {
                "sds_equal": primary == mirror,
                "sds_primary_sha256": hashlib.sha256(primary).hexdigest(),
                "sds_mirror_sha256": hashlib.sha256(mirror).hexdigest(),
                "index_reserved": roots,
            }
        }
    if kind == "upcase-attrdef":
        _, _, upcase_record = read_record(handle, geometry_, FILE_UPCASE)
        upcase = find_attribute(upcase_record, AT_DATA)
        upcase_value = attribute_value(handle, geometry_, upcase_record, upcase)
        _, _, attrdef_record = read_record(handle, geometry_, FILE_ATTRDEF)
        attrdef = find_attribute(attrdef_record, AT_DATA)
        attrdef_value = attribute_value(handle, geometry_, attrdef_record, attrdef)
        return {
            "upcase_attrdef": {
                "upcase_value": struct.unpack_from(
                    "<H", upcase_value, int(state["upcase_stream_offset"])
                )[0],
                "attrdef_type": struct.unpack_from(
                    "<I", attrdef_value, int(state["attrdef_stream_offset"])
                )[0],
            }
        }
    if kind == "upcase-nonascii":
        _, _, record = read_record(handle, geometry_, FILE_UPCASE)
        upcase = find_attribute(record, AT_DATA)
        value = attribute_value(handle, geometry_, record, upcase)
        return {
            "upcase_nonascii": {
                "stream_size": len(value),
                "codepoint": state["codepoint"],
                "mapping": struct.unpack_from(
                    "<H", value, int(state["stream_offset"])
                )[0],
            }
        }
    if kind == "user-defined-runlist":
        _, _, record = read_record(handle, geometry_, int(state["inode"]))
        attribute_offset = int(state["attribute_record_offset"])
        mapping_offset = int(state["mapping_record_offset"])
        mapping_length = int(state["mapping_length"])
        return {
            "user_defined_runlist": {
                "type": struct.unpack_from("<I", record, attribute_offset)[0],
                "mapping_hex": bytes(
                    record[mapping_offset : mapping_offset + mapping_length]
                ).hex(),
            }
        }
    if kind == "secure-sii-stale":
        _, _, record = read_record(handle, geometry_, FILE_SECURE)
        data_offset = int(state["data_record_offset"])
        return {
            "secure_sii_stale": {
                "security_id": struct.unpack_from("<I", record, data_offset + 4)[0],
                "sds_offset": struct.unpack_from("<Q", record, data_offset + 8)[0],
                "sds_length": struct.unpack_from("<I", record, data_offset + 16)[0],
            }
        }
    if kind == "link-reciprocity":
        _, _, record = read_record(handle, geometry_, int(state["inode"]))
        parent_sequence = None
        file_name_count = 0
        for attr in attributes(record):
            if attr.type != AT_FILE_NAME or attr.nonresident:
                continue
            file_name_count += 1
            assert attr.value_offset is not None and attr.value_length is not None
            value = record[attr.value_offset : attr.value_offset + attr.value_length]
            name_length = value[64] if len(value) >= 66 else 0
            name = value[66 : 66 + name_length * 2].decode("utf-16-le")
            reference = struct.unpack_from("<Q", value, 0)[0]
            if (
                name == state["target_name"]
                and reference & ((1 << 48) - 1) == state["parent_inode"]
            ):
                parent_sequence = reference >> 48
        return {
            "link_reciprocity": {
                "link_count": struct.unpack_from("<H", record, 18)[0],
                "file_name_count": file_name_count,
                "target_parent_sequence": parent_sequence,
            }
        }
    if kind in ("hardlink-collation", "hardlink-value-order"):
        parent_inodes = tuple(int(value) for value in state["parent_inodes"])
        if len(parent_inodes) != 2:
            raise FixtureError("hard-link state does not name exactly two parents")
        return {
            "hardlink_collation": inspect_hardlink_collation(
                handle,
                geometry_,
                int(state["inode"]),
                (parent_inodes[0], parent_inodes[1]),
                str(state["target_name"]),
            )
        }
    if kind in FILE_NAME_CACHED_KINDS + FILE_NAME_STABLE_KINDS:
        parent_inodes = tuple(int(value) for value in state["parent_inodes"])
        if len(parent_inodes) != 2:
            raise FixtureError("FILE_NAME index-field state needs two parents")
        collation = inspect_hardlink_collation(
            handle,
            geometry_,
            int(state["inode"]),
            (parent_inodes[0], parent_inodes[1]),
            str(state["target_name"]),
        )
        mutated = next(
            item
            for item in collation["index_copies"]
            if int(item["parent_inode"]) == int(state["mutated_parent_inode"])
        )
        return {
            "file_name_index_field": {
                "kind": kind,
                "mutation_class": state["mutation_class"],
                "field": state["field"],
                "inode": collation["inode"],
                "link_count": collation["link_count"],
                "file_name_count": collation["file_name_count"],
                "all_reciprocal": collation["all_reciprocal"],
                "mutated_copy": mutated,
                "all_index_copies": collation["index_copies"],
            }
        }
    if kind == "posix-collision-clean" or kind in POSIX_COLLISION_KINDS:
        return {"posix_collision": inspect_posix_collision(handle, geometry_, state)}
    if kind in ("sparse-stream", "sparse-unit-header"):
        return {
            "sparse_stream": inspect_sparse_stream(
                handle, geometry_, int(state["inode"])
            )
        }
    if kind == "duplicate-cluster":
        _, _, first_record = read_record(handle, geometry_, int(state["first_inode"]))
        _, _, second_record = read_record(handle, geometry_, int(state["second_inode"]))
        first = find_attribute(first_record, AT_DATA)
        second = find_attribute(second_record, AT_DATA)
        first_content = read_stream(handle, geometry_, first, 0, first.data_size)
        second_content = read_stream(handle, geometry_, second, 0, second.data_size)
        bitmap = _system_stream(handle, geometry_, FILE_BITMAP, AT_DATA)
        original_start = int(state["second_original_lcn"])
        cluster_count = int(state["clusters"])
        return {
            "duplicate_cluster": {
                "same_runs": first.runs == second.runs,
                "first_runs": first.runs,
                "second_runs": second.runs,
                "first_sha256": hashlib.sha256(first_content).hexdigest(),
                "second_sha256": hashlib.sha256(second_content).hexdigest(),
                "original_second_all_allocated": all(
                    _read_bitmap_bit(handle, geometry_, bitmap, cluster)
                    for cluster in range(original_start, original_start + cluster_count)
                ),
            }
        }
    if kind == "compressed-metadata":
        _, _, record = read_record(handle, geometry_, int(state["inode"]))
        data = find_attribute(record, AT_DATA)
        return {
            "compressed_metadata": {
                "flags": data.flags,
                "compression_unit": data.compression_unit,
                "compressed_size": data.compressed_size,
                "data_size": data.data_size,
                "runs": data.runs,
            }
        }
    if kind == "compressed-payload":
        physical_offset = int(state["physical_offset"])
        return {
            "compressed_payload": {
                "header_hex": _read_exact(handle, physical_offset, 2).hex(),
                "physical_offset": physical_offset,
            }
        }
    if kind == "native-redo-primary-applied":
        values = []
        for mirror in (False, True):
            _, _, record = read_record(
                handle, geometry_, FILE_VOLUME, mirror=mirror
            )
            volume_name = find_attribute(record, AT_VOLUME_NAME)
            values.append(attribute_value(handle, geometry_, record, volume_name))
        return {
            "native_redo_primary_applied": {
                "primary_utf16le": values[0].hex(),
                "mirror_utf16le": values[1].hex(),
                "primary_name": values[0].decode("utf-16-le"),
                "mirror_name": values[1].decode("utf-16-le"),
                "differ": values[0] != values[1],
            }
        }
    raise FixtureError(f"unsupported deep-fixture inspection kind {kind!r}")


def snapshot_orphan(
    handle: BinaryIO, geometry_: Geometry, inode: int, output: Path
) -> None:
    _, raw, logical = read_record(handle, geometry_, inode)
    clusters: list[int] = []
    for attr in attributes(logical):
        if attr.type != AT_DATA or attr.name:
            continue
        clusters.extend(
            lcn
            for _, start_lcn, length in attr.runs
            if start_lcn is not None
            for lcn in range(start_lcn, start_lcn + length)
        )
    state = {
        "format": 1,
        "inode": inode,
        "raw_record": base64.b64encode(raw).decode("ascii"),
        "clusters": clusters,
        "record_sha256": hashlib.sha256(raw).hexdigest(),
    }
    output.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def restore_orphan(
    handle: BinaryIO, geometry_: Geometry, snapshot: Path, bad_parent: bool
) -> dict[str, object]:
    state = json.loads(snapshot.read_text(encoding="utf-8"))
    if state.get("format") != 1 or not isinstance(state.get("inode"), int):
        raise FixtureError("orphan snapshot has an unsupported format")
    inode = state["inode"]
    raw = base64.b64decode(state["raw_record"], validate=True)
    if len(raw) != geometry_.record_size:
        raise FixtureError("orphan snapshot record size differs from the fixture")
    if hashlib.sha256(raw).hexdigest() != state.get("record_sha256"):
        raise FixtureError("orphan snapshot record digest differs")
    logical = mst_decode(raw, geometry_.sector_size, b"FILE")
    if bad_parent:
        changed = 0
        for attr in attributes(logical):
            if attr.type != AT_FILE_NAME or attr.nonresident:
                continue
            assert attr.value_offset is not None
            assert attr.value_length is not None
            if attr.value_length < 66:
                raise FixtureError("orphan $FILE_NAME value is too short")
            bad_reference = (1 << 48) | 0x00FFFF
            struct.pack_into("<Q", logical, attr.value_offset, bad_reference)
            changed += 1
        if not changed:
            raise FixtureError("orphan snapshot has no $FILE_NAME attributes")
        raw = mst_encode(logical, geometry_.sector_size)
    record_offset = _primary_record_offset(handle, geometry_, inode)
    _write_exact(handle, record_offset, raw)

    _, _, mft_record_zero = read_record(handle, geometry_, FILE_MFT)
    mft_bitmap = find_attribute(mft_record_zero, AT_BITMAP)
    if _read_bitmap_bit(handle, geometry_, mft_bitmap, inode):
        raise FixtureError("deleted orphan inode is unexpectedly still allocated")
    _write_bitmap_bit(handle, geometry_, mft_bitmap, inode, True)
    cluster_bitmap = _system_stream(handle, geometry_, FILE_BITMAP, AT_DATA)
    for cluster in state.get("clusters", []):
        if not isinstance(cluster, int) or cluster < 0:
            raise FixtureError("orphan snapshot contains an invalid cluster")
        if _read_bitmap_bit(handle, geometry_, cluster_bitmap, cluster):
            raise FixtureError("deleted orphan cluster is unexpectedly allocated")
        _write_bitmap_bit(handle, geometry_, cluster_bitmap, cluster, True)
    return {
        "kind": "orphan-recovery" if bad_parent else "orphan-parent",
        "inode": inode,
        "clusters": state.get("clusters", []),
    }


def inspect(handle: BinaryIO, geometry_: Geometry, state_path: Path | None) -> dict[str, object]:
    primary_boot = _read_exact(handle, 0, geometry_.sector_size)
    backup_boot = _read_exact(
        handle, geometry_.backup_boot_offset, geometry_.sector_size
    )
    mirror_equal = True
    for inode in range(geometry_.mirror_records):
        primary_offset = _primary_record_offset(handle, geometry_, inode)
        primary = _read_exact(handle, primary_offset, geometry_.record_size)
        mirror = _read_exact(
            handle,
            geometry_.mirror_mft_offset + inode * geometry_.record_size,
            geometry_.record_size,
        )
        if primary != mirror:
            mirror_equal = False
            break
    result: dict[str, object] = {
        "boot_equal": primary_boot == backup_boot,
        "primary_boot_ntfs": primary_boot[3:11] == b"NTFS    ",
        "backup_boot_ntfs": backup_boot[3:11] == b"NTFS    ",
        "primary_serial": f"{struct.unpack_from('<Q', primary_boot, 72)[0]:016X}",
        "backup_serial": f"{struct.unpack_from('<Q', backup_boot, 72)[0]:016X}",
        "mft_mirror_equal": mirror_equal,
    }
    _, _, volume_record = read_record(handle, geometry_, FILE_VOLUME)
    volume_name = find_attribute(volume_record, AT_VOLUME_NAME)
    label = attribute_value(handle, geometry_, volume_record, volume_name)
    try:
        result["volume_name"] = label.decode("utf-16-le")
    except UnicodeDecodeError as error:
        raise FixtureError("$VOLUME_NAME is invalid UTF-16") from error
    if state_path:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("kind") == "bitmaps":
            cluster_bitmap = _system_stream(handle, geometry_, FILE_BITMAP, AT_DATA)
            _, _, mft_zero = read_record(handle, geometry_, FILE_MFT)
            mft_bitmap = find_attribute(mft_zero, AT_BITMAP)
            result["bitmap_state"] = {
                "allocated_cluster": _read_bitmap_bit(
                    handle, geometry_, cluster_bitmap, state["allocated_cluster_cleared"]
                ),
                "free_cluster": _read_bitmap_bit(
                    handle, geometry_, cluster_bitmap, state["free_cluster_set"]
                ),
                "live_inode": _read_bitmap_bit(
                    handle, geometry_, mft_bitmap, state["live_inode_cleared"]
                ),
                "unused_inode": _read_bitmap_bit(
                    handle, geometry_, mft_bitmap, state["unused_inode_set"]
                ),
                "cluster_byte": read_stream(
                    handle,
                    geometry_,
                    cluster_bitmap,
                    state["cluster_bitmap_byte"],
                    1,
                )[0],
                "cluster_expected_byte": state["cluster_bitmap_before"],
                "cluster_corrupt_byte": state["cluster_bitmap_corrupt"],
                "cluster_set_mask": state["cluster_set_mask"],
                "cluster_clear_mask": state["cluster_clear_mask"],
                "mft_byte": read_stream(
                    handle,
                    geometry_,
                    mft_bitmap,
                    state["mft_bitmap_byte"],
                    1,
                )[0],
                "mft_expected_byte": state["mft_bitmap_before"],
                "mft_corrupt_byte": state["mft_bitmap_corrupt"],
                "mft_set_mask": state["mft_set_mask"],
                "mft_clear_mask": state["mft_clear_mask"],
            }
        elif state.get("kind") == "index-reference":
            result["index_reference"] = inspect_index_reference(
                handle, geometry_, state
            )
        else:
            result.update(inspect_deep_fixture(handle, geometry_, state))
    return result


def write_state(path: Path | None, state: dict[str, object]) -> None:
    if path:
        path.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(state, sort_keys=True))


def snapshot_record(
    handle: BinaryIO, geometry_: Geometry, inode: int, output: Path
) -> None:
    _, _, record = read_record(handle, geometry_, inode)
    output.write_text(
        json.dumps(
            {"format": 1, "inode": inode, "record_hex": bytes(record).hex()},
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def restore_record(
    handle: BinaryIO, geometry_: Geometry, snapshot: Path
) -> dict[str, object]:
    state = json.loads(snapshot.read_text(encoding="utf-8"))
    if state.get("format") != 1 or not isinstance(state.get("inode"), int):
        raise FixtureError("record snapshot format is invalid")
    record = bytearray.fromhex(str(state.get("record_hex", "")))
    if len(record) != geometry_.record_size:
        raise FixtureError("record snapshot length differs from MFT geometry")
    inode = int(state["inode"])
    write_record(handle, geometry_, inode, record)
    return {"kind": "record-restore", "inode": inode}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    mutate = subparsers.add_parser("mutate")
    mutate.add_argument("kind", choices=(
        "dirty-log",
        "volume-dirty-only",
        "volume-dirty-wiped-log",
        "boot-primary",
        "boot-backup",
        "mft-primary",
        "mft-mirror",
        "bitmaps",
        "index-i30",
        "index-bitmap-set",
        "index-reference",
        "attribute-list",
        "attribute-list-equal-triple-order",
        "large-attribute-list-boundary",
        "large-attribute-list-boundary-overrun",
        "large-attribute-list-truncated",
        "large-attribute-list-over-limit",
        "runlist-size",
        "reparse-index",
        "secure-derived",
        "secure-sii-stale",
        "upcase-attrdef",
        "upcase-nonascii",
        "user-defined-runlist",
        "fragment-data",
        "unflagged-sparse-run",
        "mapping-pair-tail",
        *LAYOUT_CANDIDATE_KINDS,
        "attribute-end-tail",
        "link-reciprocity",
        "hardlink-value-order",
        *FILE_NAME_CACHED_KINDS,
        *FILE_NAME_STABLE_KINDS,
        *POSIX_COLLISION_KINDS,
        "sparse-unit-header",
        "duplicate-cluster",
        "compressed-metadata",
        "compressed-payload",
        "native-redo-primary-applied",
        "journal-mft-false-free",
        "journal-cluster-false-free",
        "journal-duplicate-owner",
        "journal-mft-false-free-duplicate",
        "journal-cluster-false-free-duplicate",
    ))
    mutate.add_argument("image", type=Path)
    mutate.add_argument("--allocated-inode", type=int)
    mutate.add_argument("--live-inode", type=int)
    mutate.add_argument("--index-inode", type=int)
    mutate.add_argument("--index-allocation-inode", type=int)
    mutate.add_argument("--target-name")
    mutate.add_argument("--second-target-name")
    mutate.add_argument("--stream-name")
    mutate.add_argument("--target-inode", type=int)
    mutate.add_argument("--inode", type=int)
    mutate.add_argument("--parent-inode", type=int)
    mutate.add_argument("--second-parent-inode", type=int)
    mutate.add_argument("--first-inode", type=int)
    mutate.add_argument("--second-inode", type=int)
    mutate.add_argument("--state", type=Path)
    mutate.add_argument("--manifest", type=Path)
    mutate.add_argument("--layout", type=Path)
    mutate.add_argument("--overlap-inode", type=int)

    snapshot = subparsers.add_parser("snapshot-orphan")
    snapshot.add_argument("image", type=Path)
    snapshot.add_argument("inode", type=int)
    snapshot.add_argument("output", type=Path)

    snapshot_record_parser = subparsers.add_parser("snapshot-record")
    snapshot_record_parser.add_argument("image", type=Path)
    snapshot_record_parser.add_argument("inode", type=int)
    snapshot_record_parser.add_argument("output", type=Path)

    restore_record_parser = subparsers.add_parser("restore-record")
    restore_record_parser.add_argument("image", type=Path)
    restore_record_parser.add_argument("snapshot", type=Path)
    restore_record_parser.add_argument("--state", type=Path)

    restore = subparsers.add_parser("restore-orphan")
    restore.add_argument("image", type=Path)
    restore.add_argument("snapshot", type=Path)
    restore.add_argument("--bad-parent", action="store_true")
    restore.add_argument("--state", type=Path)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("image", type=Path)
    inspect_parser.add_argument("--state", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "snapshot-record":
            with args.image.open("rb") as handle:
                geometry_ = geometry(handle)
                snapshot_record(handle, geometry_, args.inode, args.output)
            return 0
        if args.command == "restore-record":
            with args.image.open("r+b") as handle:
                geometry_ = geometry(handle)
                state = restore_record(handle, geometry_, args.snapshot)
            write_state(args.state, state)
            return 0
        if args.command == "snapshot-orphan":
            with args.image.open("rb") as handle:
                geometry_ = geometry(handle)
                snapshot_orphan(handle, geometry_, args.inode, args.output)
            return 0
        mode = "rb" if args.command == "inspect" else "r+b"
        with args.image.open(mode) as handle:
            geometry_ = geometry(handle)
            if args.command == "inspect":
                print(json.dumps(inspect(handle, geometry_, args.state), sort_keys=True))
                return 0
            if args.command == "restore-orphan":
                state = restore_orphan(handle, geometry_, args.snapshot, args.bad_parent)
                write_state(args.state, state)
                return 0
            if args.kind == "dirty-log":
                state = set_dirty_and_unclean_log(handle, geometry_)
            elif args.kind == "volume-dirty-only":
                state = set_volume_dirty(handle, geometry_)
            elif args.kind == "volume-dirty-wiped-log":
                state = set_dirty_with_wiped_log(handle, geometry_)
            elif args.kind == "boot-primary":
                state = corrupt_boot(handle, geometry_, True)
            elif args.kind == "boot-backup":
                state = corrupt_boot(handle, geometry_, False)
            elif args.kind == "mft-primary":
                state = corrupt_mft_copy(handle, geometry_, True)
            elif args.kind == "mft-mirror":
                state = corrupt_mft_copy(handle, geometry_, False)
            elif args.kind == "bitmaps":
                if args.allocated_inode is None or args.live_inode is None:
                    raise FixtureError("bitmaps requires --allocated-inode and --live-inode")
                state = corrupt_bitmaps(
                    handle, geometry_, args.allocated_inode, args.live_inode
                )
            elif args.kind == "index-i30":
                if args.index_inode is None:
                    raise FixtureError("index-i30 requires --index-inode")
                state = corrupt_index(
                    handle,
                    geometry_,
                    args.index_inode,
                    args.index_allocation_inode,
                )
            elif args.kind == "index-bitmap-set":
                if args.index_inode is None:
                    raise FixtureError("index-bitmap-set requires --index-inode")
                state = corrupt_index_bitmap_set(
                    handle,
                    geometry_,
                    args.index_inode,
                )
            elif args.kind == "index-reference":
                if (
                    args.index_inode is None
                    or args.target_inode is None
                    or args.target_name is None
                ):
                    raise FixtureError(
                        "index-reference requires --index-inode, --target-inode, and --target-name"
                    )
                state = corrupt_index_reference(
                    handle,
                    geometry_,
                    args.index_inode,
                    args.target_name,
                    args.target_inode,
                    args.index_allocation_inode,
                )
            elif args.kind == "attribute-list":
                if args.inode is None:
                    raise FixtureError("attribute-list requires --inode")
                state = corrupt_attribute_list(handle, geometry_, args.inode)
            elif args.kind == "attribute-list-equal-triple-order":
                if (
                    args.inode is None
                    or args.parent_inode is None
                    or args.second_parent_inode is None
                    or not args.target_name
                ):
                    raise FixtureError(
                        "attribute-list-equal-triple-order requires inode, both parents, and target name"
                    )
                state = permute_attribute_list_equal_triple_values(
                    handle,
                    geometry_,
                    args.inode,
                    (args.parent_inode, args.second_parent_inode),
                    args.target_name,
                )
            elif args.kind == "large-attribute-list-boundary":
                if args.inode is None:
                    raise FixtureError(
                        "large-attribute-list-boundary requires --inode"
                    )
                state = corrupt_large_attribute_list_boundary(
                    handle, geometry_, args.inode
                )
            elif args.kind == "large-attribute-list-boundary-overrun":
                if args.inode is None:
                    raise FixtureError(
                        "large-attribute-list-boundary-overrun requires --inode"
                    )
                state = corrupt_large_attribute_list_boundary_overrun(
                    handle, geometry_, args.inode
                )
            elif args.kind == "large-attribute-list-truncated":
                if args.inode is None:
                    raise FixtureError(
                        "large-attribute-list-truncated requires --inode"
                    )
                state = corrupt_large_attribute_list_truncation(
                    handle, geometry_, args.inode
                )
            elif args.kind == "large-attribute-list-over-limit":
                if args.inode is None:
                    raise FixtureError(
                        "large-attribute-list-over-limit requires --inode"
                    )
                state = corrupt_large_attribute_list_over_limit(
                    handle, geometry_, args.inode
                )
            elif args.kind == "runlist-size":
                if args.inode is None:
                    raise FixtureError("runlist-size requires --inode")
                state = corrupt_runlist_size(handle, geometry_, args.inode)
            elif args.kind == "reparse-index":
                state = corrupt_reparse_index(handle, geometry_)
            elif args.kind == "secure-derived":
                state = corrupt_secure(handle, geometry_)
            elif args.kind == "secure-sii-stale":
                state = corrupt_secure_sii_stale(handle, geometry_)
            elif args.kind == "upcase-attrdef":
                state = corrupt_upcase_attrdef(handle, geometry_)
            elif args.kind == "upcase-nonascii":
                state = corrupt_upcase_nonascii(handle, geometry_)
            elif args.kind == "user-defined-runlist":
                if args.inode is None or not args.stream_name:
                    raise FixtureError(
                        "user-defined-runlist requires --inode and --stream-name"
                    )
                state = corrupt_user_defined_runlist(
                    handle, geometry_, args.inode, args.stream_name
                )
            elif args.kind == "fragment-data":
                if args.inode is None:
                    raise FixtureError("fragment-data requires --inode")
                state = ensure_fragmented_data(handle, geometry_, args.inode)
            elif args.kind == "unflagged-sparse-run":
                if args.inode is None:
                    raise FixtureError("unflagged-sparse-run requires --inode")
                state = corrupt_unflagged_sparse_run(
                    handle, geometry_, args.inode
                )
            elif args.kind == "mapping-pair-tail":
                if args.inode is None:
                    raise FixtureError("mapping-pair-tail requires --inode")
                state = corrupt_mapping_pair_tail(
                    handle, geometry_, args.inode
                )
            elif args.kind in LAYOUT_CANDIDATE_KINDS:
                if args.inode is None:
                    raise FixtureError(f"{args.kind} requires --inode")
                state = corrupt_layout_candidate(
                    handle, geometry_, args.inode, args.kind
                )
            elif args.kind == "attribute-end-tail":
                if args.inode is None:
                    raise FixtureError("attribute-end-tail requires --inode")
                state = corrupt_attribute_end_tail(
                    handle, geometry_, args.inode
                )
            elif args.kind == "link-reciprocity":
                if (
                    args.inode is None
                    or args.parent_inode is None
                    or args.target_name is None
                ):
                    raise FixtureError(
                        "link-reciprocity requires --inode, --parent-inode, and --target-name"
                    )
                state = corrupt_link_reciprocity(
                    handle,
                    geometry_,
                    args.inode,
                    args.parent_inode,
                    args.target_name,
                )
            elif args.kind == "hardlink-value-order":
                if (
                    args.inode is None
                    or args.parent_inode is None
                    or args.second_parent_inode is None
                    or args.target_name is None
                ):
                    raise FixtureError(
                        "hardlink-value-order requires --inode, both parent inodes, and --target-name"
                    )
                state = corrupt_hardlink_value_order(
                    handle,
                    geometry_,
                    args.inode,
                    (args.parent_inode, args.second_parent_inode),
                    args.target_name,
                )
            elif args.kind in FILE_NAME_CACHED_KINDS + FILE_NAME_STABLE_KINDS:
                if (
                    args.inode is None
                    or args.parent_inode is None
                    or args.second_parent_inode is None
                    or args.target_name is None
                ):
                    raise FixtureError(
                        f"{args.kind} requires --inode, both parent inodes, "
                        "and --target-name"
                    )
                state = mutate_file_name_index_field(
                    handle,
                    geometry_,
                    args.kind,
                    args.inode,
                    (args.parent_inode, args.second_parent_inode),
                    args.target_name,
                )
            elif args.kind in POSIX_COLLISION_KINDS:
                if (
                    args.parent_inode is None
                    or args.inode is None
                    or args.second_inode is None
                    or args.target_name is None
                    or args.second_target_name is None
                ):
                    raise FixtureError(
                        f"{args.kind} requires --parent-inode, both child inodes, "
                        "and both target names"
                    )
                state = mutate_posix_collision(
                    handle,
                    geometry_,
                    args.kind,
                    args.parent_inode,
                    (args.inode, args.second_inode),
                    (args.target_name, args.second_target_name),
                )
            elif args.kind == "sparse-unit-header":
                if args.inode is None:
                    raise FixtureError("sparse-unit-header requires --inode")
                state = corrupt_sparse_unit_header(
                    handle, geometry_, args.inode
                )
            elif args.kind == "duplicate-cluster":
                if args.first_inode is None or args.second_inode is None:
                    raise FixtureError(
                        "duplicate-cluster requires --first-inode and --second-inode"
                    )
                state = corrupt_duplicate_cluster(
                    handle, geometry_, args.first_inode, args.second_inode
                )
            elif args.kind == "compressed-metadata":
                if args.inode is None:
                    raise FixtureError("compressed-metadata requires --inode")
                state = corrupt_compressed_metadata(handle, geometry_, args.inode)
            elif args.kind == "compressed-payload":
                if args.inode is None:
                    raise FixtureError("compressed-payload requires --inode")
                state = corrupt_compressed_payload(handle, geometry_, args.inode)
            elif args.kind == "native-redo-primary-applied":
                if args.manifest is None:
                    raise FixtureError(
                        "native-redo-primary-applied requires --manifest"
                    )
                state = apply_native_redo_primary_only(
                    handle, geometry_, args.manifest
                )
            elif args.kind in (
                "journal-mft-false-free",
                "journal-cluster-false-free",
                "journal-duplicate-owner",
                "journal-mft-false-free-duplicate",
                "journal-cluster-false-free-duplicate",
            ):
                if args.layout is None:
                    raise FixtureError(f"{args.kind} requires --layout")
                allocation = (
                    "mft" if "mft-false-free" in args.kind
                    else "cluster" if "cluster-false-free" in args.kind
                    else None
                )
                if allocation is not None:
                    state = corrupt_journal_allocation(
                        handle, geometry_, args.layout, allocation
                    )
                else:
                    _, record_number, sequence, runs = _journal_layout(
                        handle, geometry_, args.layout
                    )
                    state = {
                        "kind": args.kind,
                        "allocation": None,
                        "journal_record": record_number,
                        "journal_sequence": sequence,
                        "journal_cluster": next(
                            lcn for _, lcn, _ in runs if lcn is not None
                        ),
                        "journal_runs": runs,
                    }
                if "duplicate" in args.kind:
                    if args.overlap_inode is None:
                        raise FixtureError(
                            f"{args.kind} requires --overlap-inode"
                        )
                    state.update(
                        overlap_file_with_journal(
                            handle,
                            geometry_,
                            args.layout,
                            args.overlap_inode,
                        )
                    )
                state["kind"] = args.kind
            else:
                raise FixtureError(f"unsupported mutation {args.kind}")
            handle.flush()
            write_state(args.state, state)
        return 0
    except (FixtureError, OSError, ValueError, KeyError, struct.error) as error:
        print(f"roothealth repair fixture failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
