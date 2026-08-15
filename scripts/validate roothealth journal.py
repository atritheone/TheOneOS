#!/usr/bin/env python3
"""Validate the raw NTFS allocation contract for $Extend/$RootHealth.

This helper is intentionally independent of roothealth.  It reads the NTFS
boot sector, walks the raw $MFT data stream and $Extend::$I30, locates the
journal by its FILE_NAME parent reference, decodes its non-resident runlist,
and proves its clusters in $Bitmap.  Validation never mounts or writes the
target.  The explicit provision-flags command is builder/test-only and must
only be used on a fresh, unmounted, build-owned image.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import struct
import sys
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable


AT_END = 0xFFFFFFFF
AT_STANDARD_INFORMATION = 0x10
AT_ATTRIBUTE_LIST = 0x20
AT_FILE_NAME = 0x30
AT_DATA = 0x80
AT_INDEX_ROOT = 0x90
AT_INDEX_ALLOCATION = 0xA0
AT_BITMAP = 0xB0

FILE_RECORD_IN_USE = 0x0001
FILE_RECORD_IS_DIRECTORY = 0x0002

FILE_ATTRIBUTE_READONLY = 0x0001
FILE_ATTRIBUTE_HIDDEN = 0x0002
FILE_ATTRIBUTE_SYSTEM = 0x0004
FILE_ATTRIBUTE_ARCHIVE = 0x0020
FILE_ATTRIBUTE_NOT_CONTENT_INDEXED = 0x2000
FILE_ATTRIBUTE_COMPRESSED = 0x0800
FILE_ATTRIBUTE_ENCRYPTED = 0x4000
FILE_ATTRIBUTE_SPARSE = 0x0200
REQUIRED_PROTECTED_FLAGS = (
    FILE_ATTRIBUTE_READONLY
    | FILE_ATTRIBUTE_HIDDEN
    | FILE_ATTRIBUTE_SYSTEM
    | FILE_ATTRIBUTE_NOT_CONTENT_INDEXED
)

ROOT_RECORD = 5
BITMAP_RECORD = 6
BOOT_RECORD = 7
EXTEND_RECORD = 11
METADATA_STREAM_RECORDS = {
    0: "$MFT",
    1: "$MFTMirr",
    2: "$LogFile",
    6: "$Bitmap",
    7: "$Boot",
}

JOURNAL_SIZE = 128 * 1024 * 1024
JOURNAL_MAX_TARGET_BYTES = 100 * 1024 * 1024
JOURNAL_MAX_ENTRY_COUNT = 4096
ROOTHEALTH_MAX_VOLUME_BYTES = 256 * 1024 * 1024 * 1024
PINNED_NTFS_NEXT_COMMIT = "d4f481df6926557f7b18b471a43313652dec6f7e"
PINNED_NTFS_NEXT_ARCHIVE_SHA256 = (
    "13dc944f477997ae4ecd89e3d0fdaa34b74ebbc1f7beb675657624ed6289eff5"
)
SUPERBLOCK_SIZE = 4096
ENTRY_AREA_START = 8192
SUPERBLOCK_DIGEST_OFFSET = 0xFE0
SUPERBLOCK_MAGIC = b"T1ROOTHEALTHWAL\0"


class ValidationError(RuntimeError):
    """A fail-closed journal or NTFS structural validation error."""


def u16(data: bytes | bytearray | memoryview, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes | bytearray | memoryview, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def u64(data: bytes | bytearray | memoryview, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def decode_mst(raw: bytes, sector_size: int, magic: bytes) -> bytearray:
    logical = bytearray(raw)
    if len(magic) != 4 or logical[:4] != magic:
        raise ValidationError(f"invalid {magic!r} multi-sector record signature")
    if len(logical) < sector_size or len(logical) % sector_size:
        raise ValidationError("multi-sector record has an invalid byte length")
    usa_offset = u16(logical, 4)
    usa_count = u16(logical, 6)
    expected_count = len(logical) // sector_size + 1
    if usa_count != expected_count:
        raise ValidationError("multi-sector record has an invalid fixup count")
    if usa_offset < 8 or usa_offset + usa_count * 2 > len(logical):
        raise ValidationError("multi-sector record fixup array is out of bounds")
    update_sequence = logical[usa_offset : usa_offset + 2]
    for index in range(1, usa_count):
        tail = index * sector_size - 2
        if logical[tail : tail + 2] != update_sequence:
            raise ValidationError("multi-sector record fixup sequence does not match")
        replacement = usa_offset + index * 2
        logical[tail : tail + 2] = logical[replacement : replacement + 2]
    return logical


def encode_mst(logical: bytes | bytearray, sector_size: int, magic: bytes) -> bytes:
    protected = bytearray(logical)
    if len(magic) != 4 or protected[:4] != magic:
        raise ValidationError(f"invalid {magic!r} multi-sector record signature")
    if len(protected) < sector_size or len(protected) % sector_size:
        raise ValidationError("multi-sector record has an invalid byte length")
    usa_offset = u16(protected, 4)
    usa_count = u16(protected, 6)
    expected_count = len(protected) // sector_size + 1
    if usa_count != expected_count:
        raise ValidationError("multi-sector record has an invalid fixup count")
    if usa_offset < 8 or usa_offset + usa_count * 2 > len(protected):
        raise ValidationError("multi-sector record fixup array is out of bounds")
    sequence = (u16(protected, usa_offset) + 1) & 0xFFFF
    if sequence == 0:
        sequence = 1
    sequence_bytes = struct.pack("<H", sequence)
    protected[usa_offset : usa_offset + 2] = sequence_bytes
    for index in range(1, usa_count):
        tail = index * sector_size - 2
        replacement = usa_offset + index * 2
        protected[replacement : replacement + 2] = protected[tail : tail + 2]
        protected[tail : tail + 2] = sequence_bytes
    return bytes(protected)


@dataclass(frozen=True)
class Run:
    vcn: int
    length: int
    lcn: int | None

    @property
    def vcn_end(self) -> int:
        return self.vcn + self.length

    @property
    def lcn_end(self) -> int | None:
        return None if self.lcn is None else self.lcn + self.length


@dataclass(frozen=True)
class Attribute:
    type_code: int
    raw: bytes
    nonresident: bool
    name: str
    flags: int
    record_offset: int

    def resident_value(self) -> bytes:
        if self.nonresident:
            raise ValidationError("expected a resident NTFS attribute")
        value_length = u32(self.raw, 16)
        value_offset = u16(self.raw, 20)
        if value_offset < 24 or value_offset + value_length > len(self.raw):
            raise ValidationError("resident NTFS attribute value is out of bounds")
        return self.raw[value_offset : value_offset + value_length]

    def stream_sizes(self) -> tuple[int, int, int]:
        if not self.nonresident or len(self.raw) < 64:
            raise ValidationError("expected a non-resident NTFS stream")
        return u64(self.raw, 40), u64(self.raw, 48), u64(self.raw, 56)

    def runs(self) -> list[Run]:
        if not self.nonresident:
            raise ValidationError("resident attribute has no runlist")
        run_offset = u16(self.raw, 32)
        if run_offset < 64 or run_offset >= len(self.raw):
            raise ValidationError("NTFS runlist offset is out of bounds")
        allocated, logical, initialized = self.stream_sizes()
        empty = (
            self.flags == 0
            and u64(self.raw, 16) == 0
            and u64(self.raw, 24) == 0xFFFFFFFFFFFFFFFF
            and allocated == logical == initialized == 0
        )
        return decode_runlist(self.raw[run_offset:], allow_empty=empty)


@dataclass(frozen=True)
class FileRecord:
    number: int
    sequence: int
    link_count: int
    flags: int
    base_reference: int
    attributes: tuple[Attribute, ...]

    @property
    def in_use(self) -> bool:
        return bool(self.flags & FILE_RECORD_IN_USE)

    @property
    def is_directory(self) -> bool:
        return bool(self.flags & FILE_RECORD_IS_DIRECTORY)


def decode_runlist(mapping_pairs: bytes, *, allow_empty: bool = False) -> list[Run]:
    runs: list[Run] = []
    cursor = 0
    current_vcn = 0
    current_lcn = 0
    while cursor < len(mapping_pairs):
        header = mapping_pairs[cursor]
        cursor += 1
        if header == 0:
            break
        length_bytes = header & 0x0F
        offset_bytes = header >> 4
        if length_bytes == 0 or length_bytes > 8 or offset_bytes > 8:
            raise ValidationError("NTFS runlist uses an invalid mapping-pair width")
        if cursor + length_bytes + offset_bytes > len(mapping_pairs):
            raise ValidationError("NTFS runlist mapping pair is truncated")
        length = int.from_bytes(
            mapping_pairs[cursor : cursor + length_bytes], "little", signed=False
        )
        cursor += length_bytes
        if length <= 0:
            raise ValidationError("NTFS runlist contains a zero-length run")
        if offset_bytes:
            delta = int.from_bytes(
                mapping_pairs[cursor : cursor + offset_bytes], "little", signed=True
            )
            current_lcn += delta
            if current_lcn < 0:
                raise ValidationError("NTFS runlist resolves to a negative LCN")
            lcn: int | None = current_lcn
        else:
            lcn = None
        cursor += offset_bytes
        runs.append(Run(current_vcn, length, lcn))
        current_vcn += length
    else:
        raise ValidationError("NTFS runlist has no terminator")
    if not runs and not allow_empty:
        raise ValidationError("NTFS stream has an empty runlist")
    return runs


class NtfsVolume:
    def __init__(self, handle: BinaryIO):
        self.handle = handle
        self.device_size = self._size()
        boot = self.read_at(0, 512)
        if boot[3:11] != b"NTFS    ":
            raise ValidationError("target does not have an NTFS boot sector")
        self.sector_size = u16(boot, 11)
        sectors_per_cluster = boot[13]
        if self.sector_size != 512:
            raise ValidationError("roothealth release NTFS sector size must be 512")
        if sectors_per_cluster == 0 or sectors_per_cluster & (sectors_per_cluster - 1):
            raise ValidationError("invalid NTFS sectors-per-cluster value")
        self.cluster_size = self.sector_size * sectors_per_cluster
        if self.cluster_size != 4096:
            raise ValidationError("roothealth release NTFS cluster size must be 4096")
        self.total_sectors = u64(boot, 40)
        self.total_clusters = self.total_sectors // sectors_per_cluster
        self.mft_lcn = u64(boot, 48)
        self.mftmirr_lcn = u64(boot, 56)
        record_code = struct.unpack_from("<b", boot, 64)[0]
        self.record_size = (
            1 << -record_code if record_code < 0 else record_code * self.cluster_size
        )
        self.serial = u64(boot, 72)
        if self.record_size < 512 or self.record_size > 65536:
            raise ValidationError("unsupported NTFS FILE record size")
        if self.total_sectors * self.sector_size > self.device_size:
            raise ValidationError("NTFS geometry extends beyond the target")
        if self.total_sectors * self.sector_size > ROOTHEALTH_MAX_VOLUME_BYTES:
            raise ValidationError("NTFS root exceeds the 256 GiB release profile")
        if self.mft_lcn >= self.total_clusters or self.mftmirr_lcn >= self.total_clusters:
            raise ValidationError("NTFS MFT bootstrap LCN is out of bounds")

        raw_record_zero = self.read_at(
            self.mft_lcn * self.cluster_size, self.record_size
        )
        record_zero = self.parse_file_record(raw_record_zero, 0)
        mft_data = self.unnamed_data(record_zero)
        if not mft_data.nonresident:
            raise ValidationError("$MFT data stream is unexpectedly resident")
        self.mft_runs = mft_data.runs()
        _, self.mft_data_size, _ = mft_data.stream_sizes()
        self._validate_runs(self.mft_runs, "$MFT")
        if self.mft_data_size < self.record_size * 16:
            raise ValidationError("$MFT data stream is implausibly short")

    def _size(self) -> int:
        current = self.handle.tell()
        self.handle.seek(0, os.SEEK_END)
        size = self.handle.tell()
        self.handle.seek(current)
        return size

    def read_at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or offset + length > self.device_size:
            raise ValidationError("raw target read is out of bounds")
        self.handle.seek(offset)
        data = self.handle.read(length)
        if len(data) != length:
            raise ValidationError("short raw target read")
        return data

    def _validate_runs(self, runs: Iterable[Run], description: str) -> None:
        expected_vcn = 0
        for run in runs:
            if run.vcn != expected_vcn:
                raise ValidationError(f"{description} runlist has a VCN gap or overlap")
            if run.lcn is not None and run.lcn + run.length > self.total_clusters:
                raise ValidationError(f"{description} runlist extends beyond the volume")
            expected_vcn += run.length

    def read_stream(self, runs: list[Run], offset: int, length: int) -> bytes:
        if offset < 0 or length < 0:
            raise ValidationError("negative stream read")
        result = bytearray()
        cursor = offset
        end = offset + length
        for run in runs:
            run_start = run.vcn * self.cluster_size
            run_end = run.vcn_end * self.cluster_size
            if cursor >= run_end:
                continue
            if cursor < run_start:
                raise ValidationError("stream read crosses an unmapped VCN")
            take = min(end, run_end) - cursor
            if take <= 0:
                break
            if run.lcn is None:
                result.extend(b"\0" * take)
            else:
                physical = run.lcn * self.cluster_size + (cursor - run_start)
                result.extend(self.read_at(physical, take))
            cursor += take
            if cursor == end:
                return bytes(result)
        raise ValidationError("stream read extends beyond its runlist")

    def stream_physical_ranges(
        self, runs: list[Run], offset: int, length: int
    ) -> list[dict[str, int]]:
        if offset < 0 or length <= 0:
            raise ValidationError("invalid physical-range request")
        result: list[dict[str, int]] = []
        cursor = offset
        end = offset + length
        for run in runs:
            run_start = run.vcn * self.cluster_size
            run_end = run.vcn_end * self.cluster_size
            if cursor >= run_end:
                continue
            if cursor < run_start:
                raise ValidationError("physical-range request crosses an unmapped VCN")
            take = min(end, run_end) - cursor
            if take <= 0:
                break
            if run.lcn is None:
                raise ValidationError("physical-range request crosses a sparse run")
            result.append(
                {
                    "stream_offset": cursor,
                    "device_offset": run.lcn * self.cluster_size + (cursor - run_start),
                    "bytes": take,
                }
            )
            cursor += take
            if cursor == end:
                return result
        raise ValidationError("physical-range request extends beyond its runlist")

    def apply_fixups(self, raw: bytes) -> bytes:
        if len(raw) != self.record_size or raw[:4] != b"FILE":
            raise ValidationError("invalid NTFS FILE record signature or length")
        return bytes(decode_mst(raw, self.sector_size, b"FILE"))

    def parse_attributes(self, fixed_record: bytes) -> tuple[Attribute, ...]:
        first = u16(fixed_record, 20)
        used = u32(fixed_record, 24)
        if first < 48 or used > len(fixed_record) or first >= used:
            raise ValidationError("NTFS FILE record attribute bounds are invalid")
        attributes: list[Attribute] = []
        cursor = first
        while cursor + 4 <= used:
            type_code = u32(fixed_record, cursor)
            if type_code == AT_END:
                return tuple(attributes)
            if cursor + 16 > used:
                raise ValidationError("truncated NTFS attribute header")
            length = u32(fixed_record, cursor + 4)
            if length < 24 or length % 8 or cursor + length > used:
                raise ValidationError("invalid NTFS attribute length")
            raw = fixed_record[cursor : cursor + length]
            nonresident_value = raw[8]
            if nonresident_value not in (0, 1):
                raise ValidationError("invalid NTFS attribute residency flag")
            name_length = raw[9]
            name_offset = u16(raw, 10)
            if name_length:
                name_bytes = name_length * 2
                if name_offset < 16 or name_offset + name_bytes > len(raw):
                    raise ValidationError("NTFS attribute name is out of bounds")
                try:
                    name = raw[name_offset : name_offset + name_bytes].decode("utf-16le")
                except UnicodeDecodeError as error:
                    raise ValidationError("NTFS attribute name is invalid UTF-16") from error
            else:
                name = ""
            attributes.append(
                Attribute(
                    type_code=type_code,
                    raw=raw,
                    nonresident=bool(nonresident_value),
                    name=name,
                    flags=u16(raw, 12),
                    record_offset=cursor,
                )
            )
            cursor += length
        raise ValidationError("NTFS FILE record has no attribute terminator")

    def parse_file_record(self, raw: bytes, number: int) -> FileRecord:
        fixed = self.apply_fixups(raw)
        return FileRecord(
            number=number,
            sequence=u16(fixed, 16),
            link_count=u16(fixed, 18),
            flags=u16(fixed, 22),
            base_reference=u64(fixed, 32),
            attributes=self.parse_attributes(fixed),
        )

    def record(self, number: int) -> FileRecord:
        if number < 0 or (number + 1) * self.record_size > self.mft_data_size:
            raise ValidationError("MFT record number is outside $MFT data size")
        raw = self.read_stream(
            self.mft_runs, number * self.record_size, self.record_size
        )
        return self.parse_file_record(raw, number)

    @staticmethod
    def unnamed_data(record: FileRecord) -> Attribute:
        streams = [
            item
            for item in record.attributes
            if item.type_code == AT_DATA and item.name == ""
        ]
        if len(streams) != 1:
            raise ValidationError(
                f"MFT record {record.number} does not have exactly one unnamed $DATA"
            )
        return streams[0]


def write_stream_exact(
    handle: BinaryIO,
    volume: NtfsVolume,
    runs: list[Run],
    offset: int,
    payload: bytes,
) -> None:
    consumed = 0
    for item in volume.stream_physical_ranges(runs, offset, len(payload)):
        amount = item["bytes"]
        handle.seek(item["device_offset"])
        written = handle.write(payload[consumed : consumed + amount])
        if written != amount:
            raise OSError(
                f"short raw target write: wanted {amount}, wrote {written}"
            )
        consumed += amount
    if consumed != len(payload):
        raise OSError("raw target write did not cover the requested stream range")


def read_file_record_logical(volume: NtfsVolume, number: int) -> bytearray:
    if number < 0 or (number + 1) * volume.record_size > volume.mft_data_size:
        raise ValidationError("MFT record number is outside $MFT data size")
    raw = volume.read_stream(
        volume.mft_runs, number * volume.record_size, volume.record_size
    )
    return decode_mst(raw, volume.sector_size, b"FILE")


def write_file_record_logical(
    handle: BinaryIO, volume: NtfsVolume, number: int, logical: bytearray
) -> None:
    if len(logical) != volume.record_size:
        raise ValidationError("builder FILE record write has the wrong byte length")
    protected = encode_mst(logical, volume.sector_size, b"FILE")
    write_stream_exact(
        handle,
        volume,
        volume.mft_runs,
        number * volume.record_size,
        protected,
    )


def exact_attribute(record: FileRecord, type_code: int, name: str = "") -> Attribute:
    matches = [
        item
        for item in record.attributes
        if item.type_code == type_code and item.name == name
    ]
    if len(matches) != 1:
        raise ValidationError(
            f"MFT record {record.number} lacks one attribute 0x{type_code:x} {name!r}"
        )
    return matches[0]


def attribute_value_start(attribute: Attribute) -> int:
    if attribute.nonresident:
        raise ValidationError("expected a resident NTFS attribute")
    value_length = u32(attribute.raw, 16)
    value_offset = u16(attribute.raw, 20)
    if value_offset < 24 or value_offset + value_length > len(attribute.raw):
        raise ValidationError("resident NTFS attribute value is out of bounds")
    return attribute.record_offset + value_offset


def read_attribute_stream(volume: NtfsVolume, attribute: Attribute) -> bytes:
    if not attribute.nonresident:
        return attribute.resident_value()
    _, data_size, initialized_size = attribute.stream_sizes()
    if initialized_size < data_size:
        raise ValidationError("NTFS attribute stream is not fully initialized")
    runs = attribute.runs()
    volume._validate_runs(runs, f"attribute 0x{attribute.type_code:x} {attribute.name!r}")
    return volume.read_stream(runs, 0, data_size)


@dataclass
class IndexKeyLocation:
    source: str
    buffer: bytearray
    flags_offset: int
    reference: int
    record_number: int | None = None
    stream_runs: list[Run] | None = None
    stream_offset: int | None = None

    @property
    def flags(self) -> int:
        return u32(self.buffer, self.flags_offset)


def index_entries(
    index: bytes | bytearray, header_offset: int
) -> Iterable[dict[str, int | str]]:
    if header_offset < 0 or header_offset + 16 > len(index):
        raise ValidationError("$I30 index header is out of bounds")
    entries_offset, index_length, allocated_size = struct.unpack_from(
        "<III", index, header_offset
    )
    if (
        entries_offset < 16
        or index_length < entries_offset
        or index_length > allocated_size
        or header_offset + index_length > len(index)
    ):
        raise ValidationError("$I30 index header bounds are invalid")
    cursor = header_offset + entries_offset
    end = header_offset + index_length
    while cursor + 16 <= end:
        reference = u64(index, cursor)
        length, key_length, flags = struct.unpack_from("<HHH", index, cursor + 8)
        if length < 16 or length % 8 or cursor + length > end:
            raise ValidationError("$I30 index entry length is invalid")
        if flags & ~3:
            raise ValidationError("$I30 index entry has unknown flags")
        if flags & 2:
            if key_length != 0 or cursor + length != end:
                raise ValidationError("$I30 terminal entry is malformed")
            return
        if key_length < 66 or 16 + key_length > length:
            raise ValidationError("$I30 FILE_NAME key is invalid")
        key = cursor + 16
        name_length = index[key + 64]
        name_end = key + 66 + name_length * 2
        if name_end > cursor + 16 + key_length:
            raise ValidationError("$I30 FILE_NAME text exceeds its key")
        try:
            name = bytes(index[key + 66 : name_end]).decode("utf-16le")
        except UnicodeDecodeError as error:
            raise ValidationError("$I30 FILE_NAME text is invalid UTF-16") from error
        yield {
            "offset": cursor,
            "reference": reference,
            "name": name,
            "parent_reference": u64(index, key),
            "flags_offset": key + 56,
            "file_attributes": u32(index, key + 56),
        }
        cursor += length
    raise ValidationError("$I30 index has no terminal entry")


def filename_details(attribute: Attribute) -> dict[str, int | str]:
    value = attribute.resident_value()
    if len(value) < 66:
        raise ValidationError("$FILE_NAME value is too short")
    name_length = value[64]
    name_bytes = name_length * 2
    if 66 + name_bytes > len(value):
        raise ValidationError("$FILE_NAME text is out of bounds")
    try:
        name = value[66 : 66 + name_bytes].decode("utf-16le")
    except UnicodeDecodeError as error:
        raise ValidationError("$FILE_NAME text is invalid UTF-16") from error
    parent_reference = u64(value, 0)
    return {
        "name": name,
        "parent_record": parent_reference & ((1 << 48) - 1),
        "parent_sequence": parent_reference >> 48,
        "namespace": value[65],
        "file_attributes": u32(value, 56),
    }


def standard_flags(record: FileRecord) -> int:
    values = [
        item
        for item in record.attributes
        if item.type_code == AT_STANDARD_INFORMATION
    ]
    if len(values) != 1:
        raise ValidationError("journal FILE record lacks one $STANDARD_INFORMATION")
    value = values[0].resident_value()
    if len(value) < 36:
        raise ValidationError("journal $STANDARD_INFORMATION is too short")
    return u32(value, 32)


def interval_overlap(first: Run, second: Run) -> bool:
    if first.lcn is None or second.lcn is None:
        return False
    return first.lcn < second.lcn_end and second.lcn < first.lcn_end  # type: ignore[operator]


def build_empty_superblock(
    *, generation: int, sector_size: int, serial: int, journal_uuid: uuid.UUID
) -> bytes:
    block = bytearray(SUPERBLOCK_SIZE)
    block[0x000:0x010] = SUPERBLOCK_MAGIC
    struct.pack_into("<I", block, 0x010, 1)
    struct.pack_into("<I", block, 0x014, SUPERBLOCK_SIZE)
    struct.pack_into("<I", block, 0x018, sector_size)
    struct.pack_into("<I", block, 0x01C, 0)
    struct.pack_into("<Q", block, 0x020, generation)
    struct.pack_into("<Q", block, 0x028, serial)
    block[0x030:0x040] = journal_uuid.bytes
    block[0x040:0x050] = b"\0" * 16
    struct.pack_into("<Q", block, 0x050, JOURNAL_SIZE)
    struct.pack_into("<Q", block, 0x058, ENTRY_AREA_START)
    struct.pack_into("<Q", block, 0x060, 0)
    struct.pack_into("<Q", block, 0x068, 0)
    struct.pack_into("<Q", block, 0x070, 0)
    block[0x078:0x098] = b"\0" * 32
    struct.pack_into("<Q", block, 0x098, JOURNAL_MAX_TARGET_BYTES)
    struct.pack_into("<I", block, 0x0A0, 0)
    struct.pack_into("<I", block, 0x0A4, JOURNAL_MAX_ENTRY_COUNT)
    digest = hashlib.sha256(block[:SUPERBLOCK_DIGEST_OFFSET]).digest()
    block[SUPERBLOCK_DIGEST_OFFSET:] = digest
    return bytes(block)


def parse_empty_superblock(
    block: bytes, *, volume: NtfsVolume, expected_generation: int
) -> dict[str, object]:
    if len(block) != SUPERBLOCK_SIZE:
        raise ValidationError("journal superblock is not 4096 bytes")
    if block[:0x10] != SUPERBLOCK_MAGIC:
        raise ValidationError("journal superblock magic is invalid")
    if u32(block, 0x010) != 1 or u32(block, 0x014) != SUPERBLOCK_SIZE:
        raise ValidationError("journal superblock version or header size is invalid")
    if u32(block, 0x018) != volume.sector_size:
        raise ValidationError("journal superblock sector size is misbound")
    if u32(block, 0x01C) != 0:
        raise ValidationError("release journal superblock is not EMPTY")
    generation = u64(block, 0x020)
    if generation != expected_generation:
        raise ValidationError("release journal superblock generation is invalid")
    if u64(block, 0x028) != volume.serial:
        raise ValidationError("journal superblock volume serial is misbound")
    try:
        journal_id = uuid.UUID(bytes=block[0x030:0x040])
    except ValueError as error:
        raise ValidationError("journal superblock UUID is invalid") from error
    if journal_id.int == 0:
        raise ValidationError("journal UUID must be nonzero")
    if any(block[0x040:0x050]):
        raise ValidationError("EMPTY journal has a transaction UUID")
    if u64(block, 0x050) != JOURNAL_SIZE:
        raise ValidationError("journal superblock capacity is invalid")
    if u64(block, 0x058) != ENTRY_AREA_START:
        raise ValidationError("journal entry-area start is invalid")
    if any(u64(block, offset) for offset in (0x060, 0x068, 0x070)):
        raise ValidationError("EMPTY journal has committed entry counters")
    if any(block[0x078:0x098]):
        raise ValidationError("EMPTY journal has a transaction plan hash")
    if u64(block, 0x098) != JOURNAL_MAX_TARGET_BYTES:
        raise ValidationError("journal maximum target-byte policy is invalid")
    if u32(block, 0x0A0) != 0:
        raise ValidationError("EMPTY journal has a transaction kind")
    if u32(block, 0x0A4) != JOURNAL_MAX_ENTRY_COUNT:
        raise ValidationError("journal maximum entry-count policy is invalid")
    if any(block[0x0A8:SUPERBLOCK_DIGEST_OFFSET]):
        raise ValidationError("journal superblock reserved fields are nonzero")
    expected_digest = hashlib.sha256(block[:SUPERBLOCK_DIGEST_OFFSET]).digest()
    if block[SUPERBLOCK_DIGEST_OFFSET:] != expected_digest:
        raise ValidationError("journal superblock SHA-256 is invalid")
    return {
        "generation": generation,
        "state": "EMPTY",
        "journal_uuid": str(journal_id),
        "max_entry_count": JOURNAL_MAX_ENTRY_COUNT,
        "sha256": hashlib.sha256(block).hexdigest(),
    }


def validate_empty_headers(
    volume: NtfsVolume, runs: list[Run], *, require_zero_entry_area: bool
) -> dict[str, object]:
    headers = volume.read_stream(runs, 0, ENTRY_AREA_START)
    first = parse_empty_superblock(
        headers[:SUPERBLOCK_SIZE], volume=volume, expected_generation=1
    )
    second = parse_empty_superblock(
        headers[SUPERBLOCK_SIZE:ENTRY_AREA_START],
        volume=volume,
        expected_generation=2,
    )
    if first["journal_uuid"] != second["journal_uuid"]:
        raise ValidationError("journal superblock UUIDs disagree")
    if require_zero_entry_area:
        digest = hashlib.sha256()
        cursor = ENTRY_AREA_START
        chunk_size = 4 * 1024 * 1024
        while cursor < JOURNAL_SIZE:
            take = min(chunk_size, JOURNAL_SIZE - cursor)
            payload = volume.read_stream(runs, cursor, take)
            if any(payload):
                raise ValidationError("release journal entry area is not zero-filled")
            digest.update(payload)
            cursor += take
        zero_entry_sha256 = digest.hexdigest()
    else:
        zero_entry_sha256 = None
    return {
        "selected_generation": 2,
        "journal_uuid": first["journal_uuid"],
        "max_entry_count": JOURNAL_MAX_ENTRY_COUNT,
        "slots": [first, second],
        "entry_area_zero_sha256": zero_entry_sha256,
    }


def mft_allocation_bitmap(volume: NtfsVolume) -> tuple[int, bytes]:
    record_count = volume.mft_data_size // volume.record_size
    mft = volume.record(0)
    mft_bitmaps = [
        item
        for item in mft.attributes
        if item.type_code == AT_BITMAP and item.name == ""
    ]
    if len(mft_bitmaps) != 1:
        raise ValidationError("$MFT does not have exactly one unnamed $BITMAP")
    mft_bitmap = mft_bitmaps[0]
    if mft_bitmap.nonresident:
        _, bitmap_size, bitmap_initialized = mft_bitmap.stream_sizes()
        if bitmap_initialized < bitmap_size:
            raise ValidationError("$MFT bitmap stream is not fully initialized")
        bitmap_runs = mft_bitmap.runs()
        volume._validate_runs(bitmap_runs, "$MFT/$BITMAP")
        bitmap_bytes = volume.read_stream(bitmap_runs, 0, bitmap_size)
    else:
        bitmap_bytes = mft_bitmap.resident_value()
    required_bitmap_bytes = (record_count + 7) // 8
    if len(bitmap_bytes) < required_bitmap_bytes:
        raise ValidationError("$MFT bitmap does not cover the complete data stream")
    return record_count, bitmap_bytes


def iter_mft_records(volume: NtfsVolume) -> Iterable[tuple[FileRecord, bool]]:
    record_count, bitmap_bytes = mft_allocation_bitmap(volume)

    for number in range(record_count):
        allocated = bool(bitmap_bytes[number >> 3] & (1 << (number & 7)))
        try:
            record = volume.record(number)
        except ValidationError as error:
            if allocated:
                raise ValidationError(
                    f"allocated MFT record {number} is unreadable during journal scan"
                ) from error
            continue
        if record.in_use != allocated:
            raise ValidationError(
                f"MFT record {number} in-use state disagrees with $MFT/$BITMAP"
            )
        yield record, allocated


def find_journal(volume: NtfsVolume) -> tuple[FileRecord, dict[str, int | str]]:
    extend = volume.record(EXTEND_RECORD)
    if not extend.in_use or not extend.is_directory:
        raise ValidationError("MFT record 11 is not the live $Extend directory")

    matches: list[tuple[FileRecord, dict[str, int | str]]] = []
    root_pollution: list[int] = []
    for record, allocated in iter_mft_records(volume):
        if not record.in_use:
            continue
        for attribute in record.attributes:
            if attribute.type_code != AT_FILE_NAME:
                continue
            details = filename_details(attribute)
            if details["name"] != "$RootHealth":
                continue
            if details["parent_record"] == ROOT_RECORD:
                root_pollution.append(number)
            if details["parent_record"] == EXTEND_RECORD:
                matches.append((record, details))
    if root_pollution:
        raise ValidationError(
            f"visible root namespace contains $RootHealth records: {root_pollution}"
        )
    unique_records = {item[0].number for item in matches}
    if len(matches) != 1 or len(unique_records) != 1:
        raise ValidationError(
            "$Extend must contain exactly one raw FILE_NAME for $RootHealth"
        )
    record, details = matches[0]
    if details["parent_sequence"] != extend.sequence:
        raise ValidationError("journal parent sequence does not match $Extend")
    return record, details


def validate_journal_ownership(
    volume: NtfsVolume,
    journal_record: FileRecord,
    journal_runs: list[Run],
) -> dict[str, int | bool]:
    journal_extents = sorted(
        (run.lcn, run.lcn + run.length)
        for run in journal_runs
        if run.lcn is not None
    )
    if len(journal_extents) != len(journal_runs):
        raise ValidationError("journal ownership census saw a sparse journal run")
    for previous, current in zip(journal_extents, journal_extents[1:]):
        if current[0] < previous[1]:
            raise ValidationError("journal physical runs overlap each other")

    allocated_records = 0
    nonresident_attributes = 0
    physical_runs = 0
    for record, allocated in iter_mft_records(volume):
        if not allocated:
            continue
        allocated_records += 1
        for attribute in record.attributes:
            if not attribute.nonresident:
                continue
            nonresident_attributes += 1
            runs = attribute.runs()
            for run in runs:
                if run.lcn is None:
                    continue
                physical_runs += 1
                if run.lcn + run.length > volume.total_clusters:
                    raise ValidationError(
                        f"MFT record {record.number} attribute run exceeds the volume"
                    )
                if (
                    record.number == journal_record.number
                    and attribute.type_code == AT_DATA
                    and attribute.name == ""
                ):
                    continue
                other_start = run.lcn
                other_end = run.lcn + run.length
                for journal_start, journal_end in journal_extents:
                    if other_start < journal_end and journal_start < other_end:
                        raise ValidationError(
                            "journal allocation has another owner: "
                            f"record={record.number} type=0x{attribute.type_code:x} "
                            f"name={attribute.name!r} lcn={run.lcn} clusters={run.length}"
                        )

    return {
        "complete": True,
        "allocated_mft_records": allocated_records,
        "nonresident_attributes_examined": nonresident_attributes,
        "physical_runs_examined": physical_runs,
        "journal_clusters": sum(run.length for run in journal_runs),
        "unique_owner": True,
        "self_nonoverlap": True,
    }


def find_journal_index_key(
    volume: NtfsVolume, journal_record: FileRecord
) -> IndexKeyLocation:
    extend = volume.record(EXTEND_RECORD)
    if not extend.in_use or not extend.is_directory or extend.base_reference != 0:
        raise ValidationError("$Extend is not one in-use base directory record")
    if any(item.type_code == AT_ATTRIBUTE_LIST for item in extend.attributes):
        raise ValidationError("fresh $Extend::$I30 unexpectedly uses an attribute list")
    if any(
        item.type_code in (AT_INDEX_ALLOCATION, AT_BITMAP) and item.name == "$I30"
        for item in extend.attributes
    ):
        raise ValidationError("fresh $Extend::$I30 unexpectedly uses allocation blocks")
    root = exact_attribute(extend, AT_INDEX_ROOT, "$I30")
    if root.nonresident:
        raise ValidationError("$Extend::$I30 root is unexpectedly nonresident")
    value_start = attribute_value_start(root)
    value_length = u32(root.raw, 16)
    if value_length < 32:
        raise ValidationError("$Extend::$I30 root value is too short")
    logical = read_file_record_logical(volume, EXTEND_RECORD)
    if u32(logical, value_start) != AT_FILE_NAME or u32(logical, value_start + 4) != 1:
        raise ValidationError("$Extend::$I30 uses an unexpected key or collation rule")
    block_size = u32(logical, value_start + 8)
    if block_size < volume.sector_size or block_size > 65536:
        raise ValidationError("$Extend::$I30 declares an invalid index block size")
    expected_parent = (extend.sequence << 48) | EXTEND_RECORD
    expected_child = (journal_record.sequence << 48) | journal_record.number
    matches: list[IndexKeyLocation] = []
    for item in index_entries(logical, value_start + 16):
        if item["name"] != "$RootHealth":
            continue
        if item["parent_reference"] != expected_parent:
            raise ValidationError("$Extend::$I30 journal key has the wrong parent reference")
        if item["reference"] != expected_child:
            raise ValidationError("$Extend::$I30 journal key has the wrong child reference")
        matches.append(
            IndexKeyLocation(
                source="$Extend::$I30/$INDEX_ROOT",
                buffer=logical,
                flags_offset=int(item["flags_offset"]),
                reference=int(item["reference"]),
                record_number=EXTEND_RECORD,
            )
        )
    if len(matches) != 1:
        raise ValidationError(
            f"$Extend::$I30 contains {len(matches)} exact $RootHealth keys"
        )
    return matches[0]


def journal_record_flag_offsets(
    volume: NtfsVolume, journal_record: FileRecord
) -> tuple[bytearray, int, int]:
    logical = read_file_record_logical(volume, journal_record.number)
    standard = exact_attribute(journal_record, AT_STANDARD_INFORMATION)
    names = [
        item
        for item in journal_record.attributes
        if item.type_code == AT_FILE_NAME
        and not item.nonresident
        and filename_details(item)["name"] == "$RootHealth"
        and filename_details(item)["parent_record"] == EXTEND_RECORD
    ]
    if len(names) != 1:
        raise ValidationError("journal record lacks one exact resident FILE_NAME")
    standard_offset = attribute_value_start(standard) + 32
    name_offset = attribute_value_start(names[0]) + 56
    if standard_offset + 4 > len(logical) or name_offset + 4 > len(logical):
        raise ValidationError("journal flag field exceeds its FILE record")
    return logical, standard_offset, name_offset


def rewrite_journal_flag_copies(
    handle: BinaryIO,
    volume: NtfsVolume,
    journal_record: FileRecord,
    *,
    expected_flags: tuple[int, int, int],
    desired_flags: int,
    copies: frozenset[str],
) -> dict[str, int]:
    valid_copies = frozenset(("standard", "file_name", "index"))
    if not copies or not copies <= valid_copies:
        raise ValidationError("builder flag rewrite selected an invalid copy set")
    logical, standard_offset, name_offset = journal_record_flag_offsets(
        volume, journal_record
    )
    index = find_journal_index_key(volume, journal_record)
    current = (
        u32(logical, standard_offset),
        u32(logical, name_offset),
        index.flags,
    )
    if current != expected_flags:
        raise ValidationError(
            "builder flag rewrite source changed: "
            f"SI=0x{current[0]:08X}, FILE_NAME=0x{current[1]:08X}, "
            f"I30=0x{current[2]:08X}"
        )
    if not 0 <= desired_flags <= 0xFFFFFFFF:
        raise ValidationError("builder flag rewrite value is outside uint32")
    if "standard" in copies:
        struct.pack_into("<I", logical, standard_offset, desired_flags)
    if "file_name" in copies:
        struct.pack_into("<I", logical, name_offset, desired_flags)
    if "index" in copies:
        struct.pack_into("<I", index.buffer, index.flags_offset, desired_flags)
    if copies & frozenset(("standard", "file_name")):
        write_file_record_logical(handle, volume, journal_record.number, logical)
    if "index" in copies:
        if index.record_number != EXTEND_RECORD:
            raise ValidationError("builder only supports resident $Extend::$I30")
        write_file_record_logical(handle, volume, EXTEND_RECORD, index.buffer)
    return {
        "standard_before": current[0],
        "file_name_before": current[1],
        "index_before": current[2],
        "desired": desired_flags,
    }


def parse_device_number(text: str, description: str) -> tuple[int, int]:
    match = re.fullmatch(r"([0-9]+):([0-9]+)\n?", text)
    if match is None:
        raise ValidationError(f"{description} has an invalid major:minor value")
    return int(match.group(1)), int(match.group(2))


def path_uses_synthesized_drvfs_ownership(path: Path) -> bool:
    """Return true only for a WSL DrvFS mount whose uid/gid are synthetic."""
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    absolute = str(path)
    selected: tuple[int, str, str] | None = None
    for line in lines:
        fields = line.split()
        try:
            separator = fields.index("-")
        except ValueError:
            continue
        if separator < 6 or separator + 3 >= len(fields):
            continue
        mount_point = re.sub(
            r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), fields[4]
        )
        if absolute != mount_point and not absolute.startswith(mount_point.rstrip("/") + "/"):
            continue
        filesystem = fields[separator + 1]
        super_options = " ".join(fields[separator + 3 :])
        candidate = (len(mount_point), filesystem, super_options)
        if selected is None or candidate[0] > selected[0]:
            selected = candidate
    return bool(
        selected
        and selected[1] == "9p"
        and re.search(r"(?:^|,)aname=drvfs(?:;|,|$)", selected[2]) is not None
        and re.search(r"(?:^|[;,])uid=[0-9]+(?:[;,]|$)", selected[2]) is not None
        and re.search(r"(?:^|[;,])gid=[0-9]+(?:[;,]|$)", selected[2]) is not None
    )


def canonical_builder_image(target: Path) -> tuple[Path, os.stat_result]:
    if not target.name.endswith(".building"):
        raise ValidationError(
            "provision-flags requires a fresh builder/test path ending in .building"
        )
    absolute = Path(os.path.abspath(target))
    try:
        target_stat = absolute.lstat()
    except OSError as error:
        raise ValidationError("builder image cannot be inspected") from error
    if not stat.S_ISREG(target_stat.st_mode) or stat.S_ISLNK(target_stat.st_mode):
        raise ValidationError(
            "provision-flags accepts only a non-symlink regular build-owned image"
        )
    if (
        target_stat.st_uid != os.geteuid()
        and not path_uses_synthesized_drvfs_ownership(absolute)
    ):
        raise ValidationError("builder image is not owned by the provisioning user")
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as error:
        raise ValidationError("builder image cannot be resolved") from error
    if resolved != absolute:
        raise ValidationError("builder image path contains a symbolic-link component")
    return resolved, target_stat


def open_locked_builder_image(
    target: Path,
) -> tuple[Path, int, os.stat_result]:
    builder, expected = canonical_builder_image(target)
    flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(builder, flags)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != expected.st_dev
            or opened.st_ino != expected.st_ino
            or opened.st_size != expected.st_size
        ):
            raise ValidationError("regular builder image identity changed during open")
        return builder, descriptor, opened
    except BaseException:
        os.close(descriptor)
        raise


def require_builder_path_identity(
    builder: Path, expected: os.stat_result, description: str
) -> None:
    try:
        observed = builder.stat()
    except OSError as error:
        raise ValidationError(f"builder image {description} cannot be inspected") from error
    if (
        observed.st_dev != expected.st_dev
        or observed.st_ino != expected.st_ino
        or observed.st_size != expected.st_size
    ):
        raise ValidationError(f"builder image identity changed {description}")


def decoded_loop_backing(path: Path) -> Path:
    try:
        encoded = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ValidationError("loop backing-file identity cannot be read") from error
    decoded = re.sub(
        r"\\([0-7]{3})",
        lambda match: chr(int(match.group(1), 8)),
        encoded,
    )
    if not decoded.startswith("/") or decoded.endswith(" (deleted)"):
        raise ValidationError("loop backing-file identity is not a live absolute path")
    return Path(decoded)


def reject_attached_regular_builder(
    builder: Path, builder_stat: os.stat_result
) -> None:
    for loop in sorted(Path("/sys/class/block").glob("loop*")):
        backing_file = loop / "loop" / "backing_file"
        if not backing_file.is_file():
            continue
        backing = decoded_loop_backing(backing_file)
        try:
            backing_stat = backing.stat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ValidationError("attached loop backing file cannot be inspected") from error
        if (
            backing_stat.st_dev == builder_stat.st_dev
            and backing_stat.st_ino == builder_stat.st_ino
        ):
            raise ValidationError(
                f"regular builder image remains attached through {loop.name}"
            )


def sysfs_device_node(device: tuple[int, int]) -> Path:
    link = Path("/sys/dev/block") / f"{device[0]}:{device[1]}"
    try:
        node = link.resolve(strict=True)
        observed = parse_device_number(
            (node / "dev").read_text(encoding="ascii"), "sysfs block node"
        )
    except OSError as error:
        raise ValidationError("block-device sysfs identity cannot be resolved") from error
    if observed != device:
        raise ValidationError("block-device sysfs identity changed")
    return node


def block_backing_chain(
    target_device: tuple[int, int],
    builder: Path,
    builder_stat: os.stat_result,
    root_partition_number: int,
) -> tuple[list[dict[str, int | str]], Path, Path, list[Path]]:
    chain: list[dict[str, int | str]] = []
    nodes: list[Path] = []
    seen: set[tuple[int, int]] = set()
    partition_node: Path | None = None
    current = target_device
    while True:
        if current in seen:
            raise ValidationError("block-device ancestry contains a cycle")
        seen.add(current)
        node = sysfs_device_node(current)
        nodes.append(node)
        chain.append(
            {"major": current[0], "minor": current[1], "name": node.name}
        )
        backing_file = node / "loop" / "backing_file"
        if backing_file.is_file():
            backing = decoded_loop_backing(backing_file)
            try:
                backing_stat = backing.stat()
                loop_sectors = int((node / "size").read_text(encoding="ascii").strip())
            except (OSError, ValueError) as error:
                raise ValidationError("loop backing identity or size cannot be proved") from error
            if (
                backing_stat.st_dev != builder_stat.st_dev
                or backing_stat.st_ino != builder_stat.st_ino
                or loop_sectors * 512 != builder_stat.st_size
            ):
                raise ValidationError(
                    "block target is not backed by the exact declared .building image"
                )
            if partition_node is None:
                raise ValidationError(
                    f"builder target is not rooted in GPT partition {root_partition_number}"
                )
            return chain, backing, partition_node, nodes

        slaves_dir = node / "slaves"
        slaves = sorted(slaves_dir.iterdir()) if slaves_dir.is_dir() else []
        if slaves:
            if len(slaves) != 1:
                raise ValidationError("builder block target has ambiguous slave ancestry")
            if len(nodes) != 1 or not (node / "dm").is_dir():
                raise ValidationError("builder target has an unsupported stacked block layer")
            try:
                current = parse_device_number(
                    (slaves[0].resolve(strict=True) / "dev").read_text(encoding="ascii"),
                    "block-device slave",
                )
            except OSError as error:
                raise ValidationError("block-device slave identity cannot be read") from error
            continue

        if (node / "partition").is_file():
            if partition_node is not None:
                raise ValidationError("builder target has more than one partition layer")
            try:
                partition_number = int(
                    (node / "partition").read_text(encoding="ascii").strip()
                )
            except (OSError, ValueError) as error:
                raise ValidationError("partition number cannot be read") from error
            if partition_number != root_partition_number:
                raise ValidationError(
                    f"builder target is not exact GPT partition {root_partition_number}"
                )
            partition_node = node
            try:
                current = parse_device_number(
                    (node.parent / "dev").read_text(encoding="ascii"),
                    "block-device partition parent",
                )
            except OSError as error:
                raise ValidationError("partition parent identity cannot be read") from error
            continue
        raise ValidationError("builder block target does not terminate at a loop image")


def node_holder_names(node: Path) -> set[str]:
    holders = node / "holders"
    try:
        return {item.name for item in holders.iterdir()} if holders.is_dir() else set()
    except OSError as error:
        raise ValidationError("block-device holder graph cannot be inspected") from error


def validate_block_stack(
    nodes: list[Path], root_kind: str, expected_mapper_name: str | None
) -> dict[str, str | None]:
    if root_kind == "plain":
        if expected_mapper_name is not None:
            raise ValidationError("plain builder root cannot name a dm-crypt mapper")
        if len(nodes) != 2 or not (nodes[0] / "partition").is_file():
            raise ValidationError("plain builder root is not partition-2 -> loop")
        if node_holder_names(nodes[0]) or node_holder_names(nodes[1]):
            raise ValidationError("plain builder root has an unexpected holder")
        return {"dm_name": None, "dm_uuid": None}
    if root_kind != "luks":
        raise ValidationError("unknown builder root kind")
    if not expected_mapper_name:
        raise ValidationError("encrypted builder root requires an exact mapper name")
    if (
        len(nodes) != 3
        or not (nodes[0] / "dm").is_dir()
        or not (nodes[1] / "partition").is_file()
    ):
        raise ValidationError("encrypted builder root is not dm-crypt -> partition-2 -> loop")
    if node_holder_names(nodes[0]) or node_holder_names(nodes[2]):
        raise ValidationError("encrypted builder root has an unexpected outer holder")
    if node_holder_names(nodes[1]) != {nodes[0].name}:
        raise ValidationError("encrypted partition holder is not the exact selected dm target")
    try:
        dm_name = (nodes[0] / "dm" / "name").read_text(encoding="utf-8").strip()
        dm_uuid = (nodes[0] / "dm" / "uuid").read_text(encoding="ascii").strip()
    except OSError as error:
        raise ValidationError("dm-crypt identity cannot be read") from error
    if dm_name != expected_mapper_name:
        raise ValidationError("dm-crypt mapper name is not the exact builder mapping")
    if re.fullmatch(r"CRYPT-LUKS2-[0-9a-fA-F]{32}-.+", dm_uuid) is None:
        raise ValidationError("single-slave dm target is not a LUKS2 crypt mapping")
    return {"dm_name": dm_name, "dm_uuid": dm_uuid}


def pread_exact(descriptor: int, offset: int, length: int) -> bytes:
    payload = os.pread(descriptor, length, offset)
    if len(payload) != length:
        raise ValidationError("short read from retained builder image")
    return payload


def validate_gpt_root_partition(
    builder_descriptor: int,
    builder_stat: os.stat_result,
    partition_node: Path,
    root_kind: str,
    expected_name: str,
    root_partition_number: int,
) -> dict[str, int | str]:
    if builder_stat.st_size < 34 * 512 or builder_stat.st_size % 512:
        raise ValidationError("builder image size is incompatible with GPT")
    disk_sectors = builder_stat.st_size // 512
    header = bytearray(pread_exact(builder_descriptor, 512, 512))
    if header[:8] != b"EFI PART":
        raise ValidationError("builder image lacks a primary GPT header")
    header_size = u32(header, 12)
    if header_size < 92 or header_size > 512:
        raise ValidationError("builder GPT header size is invalid")
    expected_header_crc = u32(header, 16)
    struct.pack_into("<I", header, 16, 0)
    if zlib.crc32(header[:header_size]) & 0xFFFFFFFF != expected_header_crc:
        raise ValidationError("builder GPT header CRC is invalid")
    backup_lba = u64(header, 32)
    if u64(header, 24) != 1 or backup_lba != disk_sectors - 1:
        raise ValidationError("builder GPT header geometry is invalid")
    primary_first_usable = u64(header, 40)
    primary_last_usable = u64(header, 48)
    disk_guid_bytes = bytes(header[56:72])
    if uuid.UUID(bytes_le=disk_guid_bytes).int == 0:
        raise ValidationError("builder GPT disk GUID is zero")
    entry_lba = u64(header, 72)
    entry_count = u32(header, 80)
    entry_size = u32(header, 84)
    entry_crc = u32(header, 88)
    if (
        entry_lba < 2
        or entry_count < 2
        or entry_count > 4096
        or entry_size < 128
        or entry_size > 4096
        or entry_size % 8
        or entry_count * entry_size > 16 * 1024 * 1024
    ):
        raise ValidationError("builder GPT partition-array geometry is invalid")
    entries = pread_exact(
        builder_descriptor, entry_lba * 512, entry_count * entry_size
    )
    if zlib.crc32(entries) & 0xFFFFFFFF != entry_crc:
        raise ValidationError("builder GPT partition-array CRC is invalid")

    backup = bytearray(
        pread_exact(builder_descriptor, backup_lba * 512, 512)
    )
    if backup[:8] != b"EFI PART":
        raise ValidationError("builder image lacks a backup GPT header")
    backup_header_size = u32(backup, 12)
    if backup_header_size != header_size:
        raise ValidationError("primary and backup GPT header sizes disagree")
    expected_backup_crc = u32(backup, 16)
    struct.pack_into("<I", backup, 16, 0)
    if zlib.crc32(backup[:backup_header_size]) & 0xFFFFFFFF != expected_backup_crc:
        raise ValidationError("builder backup GPT header CRC is invalid")
    if (
        u64(backup, 24) != backup_lba
        or u64(backup, 32) != 1
        or u64(backup, 40) != primary_first_usable
        or u64(backup, 48) != primary_last_usable
        or bytes(backup[56:72]) != disk_guid_bytes
        or u32(backup, 80) != entry_count
        or u32(backup, 84) != entry_size
        or u32(backup, 88) != entry_crc
    ):
        raise ValidationError("primary and backup GPT bindings disagree")
    backup_entry_lba = u64(backup, 72)
    if (
        backup_entry_lba < primary_last_usable + 1
        or backup_entry_lba * 512 + len(entries) > backup_lba * 512
    ):
        raise ValidationError("backup GPT partition array is out of bounds")
    backup_entries = pread_exact(
        builder_descriptor, backup_entry_lba * 512, len(entries)
    )
    if (
        zlib.crc32(backup_entries) & 0xFFFFFFFF != entry_crc
        or backup_entries != entries
    ):
        raise ValidationError("primary and backup GPT partition arrays disagree")
    if root_partition_number < 1 or root_partition_number > entry_count:
        raise ValidationError("builder GPT root partition number is out of bounds")
    entry_offset = (root_partition_number - 1) * entry_size
    entry = entries[entry_offset : entry_offset + entry_size]
    if len(entry) < 128:
        raise ValidationError(f"builder GPT partition {root_partition_number} is truncated")
    type_guid = str(uuid.UUID(bytes_le=entry[:16]))
    unique_guid = str(uuid.UUID(bytes_le=entry[16:32]))
    first_lba = u64(entry, 32)
    last_lba = u64(entry, 40)
    if (
        first_lba < primary_first_usable
        or last_lba > primary_last_usable
        or last_lba < first_lba
    ):
        raise ValidationError(f"builder GPT partition {root_partition_number} bounds are invalid")
    if uuid.UUID(unique_guid).int == 0:
        raise ValidationError(f"builder GPT partition {root_partition_number} has a zero unique GUID")
    name_bytes = entry[56:128]
    try:
        partition_name = name_bytes.decode("utf-16le").split("\0", 1)[0]
    except UnicodeDecodeError as error:
        raise ValidationError(
            f"builder GPT partition {root_partition_number} name is invalid UTF-16"
        ) from error
    expected_type = {
        "plain": "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7",
        "luks": "ca7d7ccb-63ed-4c53-861c-1742536059cc",
    }.get(root_kind)
    if expected_type is None or type_guid != expected_type:
        raise ValidationError(
            f"builder GPT partition {root_partition_number} type does not match root kind"
        )
    if partition_name != expected_name:
        raise ValidationError(
            f"builder GPT partition {root_partition_number} name is not the expected root name"
        )
    try:
        sysfs_start = int((partition_node / "start").read_text(encoding="ascii").strip())
        sysfs_size = int((partition_node / "size").read_text(encoding="ascii").strip())
    except (OSError, ValueError) as error:
        raise ValidationError("root-partition sysfs geometry cannot be read") from error
    if sysfs_start != first_lba or sysfs_size != last_lba - first_lba + 1:
        raise ValidationError("root-partition sysfs geometry disagrees with retained GPT")
    return {
        "number": root_partition_number,
        "disk_guid": str(uuid.UUID(bytes_le=disk_guid_bytes)),
        "type_guid": type_guid,
        "unique_guid": unique_guid,
        "name": partition_name,
        "start_lba": first_lba,
        "sector_count": last_lba - first_lba + 1,
    }


def mounted_device_numbers() -> set[tuple[int, int]]:
    mounted: set[tuple[int, int]] = set()
    for process in sorted(Path("/proc").iterdir(), key=lambda item: item.name):
        if not process.name.isdecimal():
            continue
        mountinfo = process / "mountinfo"
        try:
            lines = mountinfo.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            continue
        except PermissionError as error:
            raise ValidationError("cannot prove all-process mount state") from error
        except OSError as error:
            if error.errno == errno.ENOENT:
                continue
            raise ValidationError("cannot read all-process mount state") from error
        for line in lines:
            fields = line.split()
            if len(fields) < 3:
                raise ValidationError("kernel mountinfo record is truncated")
            mounted.add(parse_device_number(fields[2], "kernel mountinfo record"))
    return mounted


def attest_builder_block_binding(
    target_device: tuple[int, int],
    builder: Path,
    builder_descriptor: int,
    builder_stat: os.stat_result,
    root_kind: str,
    expected_partition_name: str,
    expected_mapper_name: str | None,
    root_partition_number: int,
) -> dict[str, object]:
    ancestry, backing, partition_node, nodes = block_backing_chain(
        target_device, builder, builder_stat, root_partition_number
    )
    dm = validate_block_stack(nodes, root_kind, expected_mapper_name)
    gpt = validate_gpt_root_partition(
        builder_descriptor,
        builder_stat,
        partition_node,
        root_kind,
        expected_partition_name,
        root_partition_number,
    )
    ancestry_devices = {
        (int(item["major"]), int(item["minor"])) for item in ancestry
    }
    if mounted_device_numbers() & ancestry_devices:
        raise ValidationError("builder block target or its ancestry remains mounted")
    return {
        "root_kind": root_kind,
        "gpt_partition": gpt,
        "dm": dm,
        "ancestry": ancestry,
        "loop_backing_path": str(backing),
        "unmounted_all_process_namespaces": True,
    }


def provision_flags_on_handle(
    handle: BinaryIO,
    target_text: str,
    builder_binding: dict[str, object],
) -> dict[str, object]:
    handle.seek(0)
    volume = NtfsVolume(handle)
    validate_journal(
        volume,
        JOURNAL_SIZE,
        True,
        True,
        allow_provisional_flags=True,
    )
    record, _ = find_journal(volume)
    logical, standard_offset, name_offset = journal_record_flag_offsets(volume, record)
    index = find_journal_index_key(volume, record)
    current = (
        u32(logical, standard_offset),
        u32(logical, name_offset),
        index.flags,
    )
    if current[0] != REQUIRED_PROTECTED_FLAGS:
        raise ValidationError(
            "provision-flags requires the mounted xattr step to set "
            "$STANDARD_INFORMATION to exact 0x00002007 first"
        )
    if current[2] != REQUIRED_PROTECTED_FLAGS:
        raise ValidationError(
            "provision-flags requires the mounted xattr step to set the "
            "$Extend::$I30 cached key to exact 0x00002007 first"
        )
    forbidden = (
        FILE_ATTRIBUTE_COMPRESSED | FILE_ATTRIBUTE_ENCRYPTED | FILE_ATTRIBUTE_SPARSE
    )
    if current[1] & forbidden:
        raise ValidationError("journal namespace flags contain a forbidden data mode")
    details = rewrite_journal_flag_copies(
        handle,
        volume,
        record,
        expected_flags=current,
        desired_flags=REQUIRED_PROTECTED_FLAGS,
        copies=frozenset(("file_name", "index")),
    )
    handle.flush()
    os.fsync(handle.fileno())
    handle.seek(0)
    volume = NtfsVolume(handle)
    report = validate_journal(volume, JOURNAL_SIZE, True, True)
    return {
        "format": 1,
        "state": "protected-flags-provisioned",
        "target": target_text,
        "builder_binding": builder_binding,
        "required_flags": f"0x{REQUIRED_PROTECTED_FLAGS:08X}",
        "mft_record": report["journal"]["mft_record"],  # type: ignore[index]
        "mft_sequence": report["journal"]["mft_sequence"],  # type: ignore[index]
        "before": {
            "standard_information": f"0x{details['standard_before']:08X}",
            "file_name": f"0x{details['file_name_before']:08X}",
            "extend_i30": f"0x{details['index_before']:08X}",
        },
    }


def provision_protected_flags(target: Path) -> dict[str, object]:
    builder, descriptor, builder_stat = open_locked_builder_image(target)
    try:
        reject_attached_regular_builder(builder, builder_stat)
        with os.fdopen(descriptor, "r+b", buffering=0, closefd=False) as handle:
            report = provision_flags_on_handle(
                handle,
                str(builder),
                {
                    "mode": "REGULAR_BUILDING_IMAGE",
                    "path": str(builder),
                    "device": str(builder_stat.st_dev),
                    "inode": str(builder_stat.st_ino),
                    "bytes": builder_stat.st_size,
                },
            )
        require_builder_path_identity(builder, builder_stat, "after provisioning")
        return report
    finally:
        os.close(descriptor)


def provision_protected_flags_device(
    target: Path,
    builder_image: Path,
    root_kind: str,
    expected_partition_name: str,
    expected_mapper_name: str | None,
    root_partition_number: int = 2,
) -> dict[str, object]:
    builder, builder_descriptor, builder_stat = open_locked_builder_image(
        builder_image
    )
    try:
        requested = Path(os.path.abspath(target))
        try:
            requested_lstat = requested.lstat()
            resolved = requested.resolve(strict=True)
            target_stat = resolved.stat()
        except OSError as error:
            raise ValidationError("builder block target cannot be resolved") from error
        if stat.S_ISLNK(requested_lstat.st_mode):
            if requested.parent != Path("/dev/mapper"):
                raise ValidationError(
                    "only an exact /dev/mapper final-component symlink is supported"
                )
        elif requested != resolved:
            raise ValidationError("builder block target path contains a symbolic link")
        if not stat.S_ISBLK(target_stat.st_mode):
            raise ValidationError("provision-flags-device requires a block target")
        target_device = (os.major(target_stat.st_rdev), os.minor(target_stat.st_rdev))
        binding = attest_builder_block_binding(
            target_device,
            builder,
            builder_descriptor,
            builder_stat,
            root_kind,
            expected_partition_name,
            expected_mapper_name,
            root_partition_number,
        )
        require_builder_path_identity(builder, builder_stat, "before block open")

        flags = (
            os.O_RDWR
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(resolved, flags)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISBLK(opened.st_mode)
                or opened.st_rdev != target_stat.st_rdev
            ):
                raise ValidationError("builder block identity changed during exclusive open")
            if requested.resolve(strict=True) != resolved:
                raise ValidationError("builder block request retargeted before provisioning")
            opened_binding = attest_builder_block_binding(
                target_device,
                builder,
                builder_descriptor,
                builder_stat,
                root_kind,
                expected_partition_name,
                expected_mapper_name,
                root_partition_number,
            )
            if opened_binding != binding:
                raise ValidationError("builder block binding changed during exclusive open")
            with os.fdopen(descriptor, "r+b", buffering=0, closefd=False) as handle:
                report = provision_flags_on_handle(
                    handle,
                    str(requested),
                    {
                        "mode": "LOOP_BACKED_BUILDING_BLOCK",
                        "image_path": str(builder),
                        "image_device": str(builder_stat.st_dev),
                        "image_inode": str(builder_stat.st_ino),
                        "image_bytes": builder_stat.st_size,
                        "requested_target": str(requested),
                        "resolved_target": str(resolved),
                        "target_major": target_device[0],
                        "target_minor": target_device[1],
                        "binding": binding,
                        "exclusive_builder_lock": True,
                        "exclusive_target_open": True,
                    },
                )
            if requested.resolve(strict=True) != resolved:
                raise ValidationError("builder block request retargeted during provisioning")
            final_binding = attest_builder_block_binding(
                target_device,
                builder,
                builder_descriptor,
                builder_stat,
                root_kind,
                expected_partition_name,
                expected_mapper_name,
                root_partition_number,
            )
            if final_binding != binding:
                raise ValidationError("builder block binding changed during provisioning")
            require_builder_path_identity(builder, builder_stat, "after provisioning")
            return report
        finally:
            os.close(descriptor)
    finally:
        os.close(builder_descriptor)


def validate_journal(
    volume: NtfsVolume,
    expected_size: int,
    require_one_run: bool,
    require_zero_entry_area: bool,
    *,
    allow_provisional_flags: bool = False,
) -> dict[str, object]:
    record, name = find_journal(volume)
    if record.is_directory or record.base_reference != 0 or record.link_count != 1:
        raise ValidationError("journal is not one standalone base file record")
    if any(item.type_code == AT_ATTRIBUTE_LIST for item in record.attributes):
        raise ValidationError("journal FILE record uses a forbidden $ATTRIBUTE_LIST")
    data_attributes = [item for item in record.attributes if item.type_code == AT_DATA]
    if len(data_attributes) != 1 or data_attributes[0].name:
        raise ValidationError("journal must have only one unnamed $DATA stream")
    data = data_attributes[0]
    if not data.nonresident:
        raise ValidationError("journal $DATA stream is resident")
    if data.flags:
        raise ValidationError("journal $DATA is compressed, sparse, or encrypted")
    allocated, logical, initialized = data.stream_sizes()
    if logical != expected_size or initialized != logical or allocated != logical:
        raise ValidationError(
            "journal allocated, logical, and initialized sizes are not the required size"
        )
    if expected_size % volume.cluster_size:
        raise ValidationError("required journal size is not cluster-aligned")
    runs = data.runs()
    volume._validate_runs(runs, "$Extend/$RootHealth")
    if any(run.lcn is None for run in runs):
        raise ValidationError("journal runlist contains a sparse run")
    if sum(run.length for run in runs) * volume.cluster_size != allocated:
        raise ValidationError("journal runlist does not cover its allocation")
    if require_one_run and len(runs) != 1:
        raise ValidationError("new release journal is not one contiguous run")
    ownership = validate_journal_ownership(volume, record, runs)

    system_runs: dict[str, list[Run]] = {}
    for number, name_text in METADATA_STREAM_RECORDS.items():
        metadata = volume.record(number)
        if not metadata.in_use:
            raise ValidationError(f"required NTFS metadata record {name_text} is unused")
        stream = volume.unnamed_data(metadata)
        if stream.nonresident:
            metadata_runs = stream.runs()
            volume._validate_runs(metadata_runs, name_text)
            system_runs[name_text] = metadata_runs
            for journal_run in runs:
                for metadata_run in metadata_runs:
                    if interval_overlap(journal_run, metadata_run):
                        raise ValidationError(
                            f"journal allocation overlaps {name_text}"
                        )

    bitmap = volume.record(BITMAP_RECORD)
    bitmap_stream = volume.unnamed_data(bitmap)
    if not bitmap_stream.nonresident:
        raise ValidationError("$Bitmap data stream is unexpectedly resident")
    bitmap_allocated, bitmap_size, bitmap_initialized = bitmap_stream.stream_sizes()
    if bitmap_initialized < bitmap_size or bitmap_allocated < bitmap_size:
        raise ValidationError("$Bitmap stream sizes are inconsistent")
    bitmap_bytes = volume.read_stream(bitmap_stream.runs(), 0, bitmap_size)
    for run in runs:
        assert run.lcn is not None
        for cluster in range(run.lcn, run.lcn + run.length):
            byte_index = cluster >> 3
            bit = cluster & 7
            if byte_index >= len(bitmap_bytes) or not (bitmap_bytes[byte_index] & (1 << bit)):
                raise ValidationError(
                    f"journal cluster {cluster} is not allocated in $Bitmap"
                )

    standard = standard_flags(record)
    name_flags = int(name["file_attributes"])
    index_key = find_journal_index_key(volume, record)
    index_flags = index_key.flags
    flags_protected = (
        standard == REQUIRED_PROTECTED_FLAGS
        and name_flags == REQUIRED_PROTECTED_FLAGS
        and index_flags == REQUIRED_PROTECTED_FLAGS
    )
    if standard != REQUIRED_PROTECTED_FLAGS:
        raise ValidationError(
            "journal STANDARD_INFORMATION flags are not exact "
            f"0x{REQUIRED_PROTECTED_FLAGS:08X}"
        )
    if index_flags != REQUIRED_PROTECTED_FLAGS:
        raise ValidationError(
            "$Extend::$I30 cached FILE_NAME flags are not exact "
            f"0x{REQUIRED_PROTECTED_FLAGS:08X}"
        )
    if allow_provisional_flags:
        if name_flags != FILE_ATTRIBUTE_ARCHIVE:
            raise ValidationError(
                "provisional journal base FILE_NAME flags are not exact "
                f"0x{FILE_ATTRIBUTE_ARCHIVE:08X}"
            )
    elif name_flags != REQUIRED_PROTECTED_FLAGS:
        raise ValidationError(
            "journal base FILE_NAME flags are not exact "
            f"0x{REQUIRED_PROTECTED_FLAGS:08X}"
        )
    forbidden_file_flags = (
        FILE_ATTRIBUTE_COMPRESSED | FILE_ATTRIBUTE_ENCRYPTED | FILE_ATTRIBUTE_SPARSE
    )
    if (
        standard & forbidden_file_flags
        or name_flags & forbidden_file_flags
        or index_flags & forbidden_file_flags
    ):
        raise ValidationError("journal FILE flags enable compression, encryption, or sparseness")
    if not allow_provisional_flags and (
        standard != name_flags or standard != index_flags
    ):
        raise ValidationError(
            "journal STANDARD_INFORMATION, base FILE_NAME, and $I30 flags disagree"
        )

    headers = validate_empty_headers(
        volume, runs, require_zero_entry_area=require_zero_entry_area
    )
    journal_data_ranges = volume.stream_physical_ranges(runs, 0, logical)
    journal_record_ranges = volume.stream_physical_ranges(
        volume.mft_runs, record.number * volume.record_size, volume.record_size
    )

    return {
        "format": 1,
        "state": "structurally-valid",
        "device": {
            "bytes": volume.device_size,
            "sector_size": volume.sector_size,
            "cluster_size": volume.cluster_size,
            "total_clusters": volume.total_clusters,
            "serial": f"{volume.serial:016X}",
        },
        "journal": {
            "path": "$Extend/$RootHealth",
            "mft_record": record.number,
            "mft_sequence": record.sequence,
            "parent_record": name["parent_record"],
            "parent_sequence": name["parent_sequence"],
            "namespace": name["namespace"],
            "logical_bytes": logical,
            "allocated_bytes": allocated,
            "initialized_bytes": initialized,
            "run_count": len(runs),
            "runs": [
                {"vcn": run.vcn, "lcn": run.lcn, "clusters": run.length}
                for run in runs
            ],
            "standard_information_flags": f"0x{standard:08X}",
            "file_name_flags": f"0x{name_flags:08X}",
            "extend_i30_file_name_flags": f"0x{index_flags:08X}",
            "required_protected_flags": f"0x{REQUIRED_PROTECTED_FLAGS:08X}",
            "protected_flags_present": flags_protected,
            "header": headers,
            "ownership": ownership,
            "write_exclusion": {
                "data_stream": journal_data_ranges,
                "base_file_record": journal_record_ranges,
            },
        },
        "checks": {
            "unique_parent_name": True,
            "no_root_namespace_entry": True,
            "base_record_without_attribute_list": True,
            "nonresident_initialized_nonsparse_data": True,
            "runlist_in_bounds": True,
            "runlist_nonoverlap": True,
            "bitmap_allocated": True,
            "complete_owner_census": ownership["complete"],
            "unique_cluster_owner": ownership["unique_owner"],
            "file_flags_consistent": True,
            "protected_file_flags": flags_protected,
            "extend_i30_flags_consistent": standard == index_flags,
        },
    }


def parse_size(text: str) -> int:
    try:
        value = int(text, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("size must be an integer byte count") from error
    if value < 16384 or value % 4096:
        raise argparse.ArgumentTypeError("size must be at least 16384 and 4096-byte aligned")
    return value


def sha256_opened_regular(path: Path) -> tuple[str, int, bytes, int]:
    absolute = Path(os.path.abspath(path))
    try:
        lstat_result = absolute.lstat()
        resolved = absolute.resolve(strict=True)
    except OSError as error:
        raise ValidationError(f"cannot inspect provenance input {path}") from error
    if (
        not stat.S_ISREG(lstat_result.st_mode)
        or stat.S_ISLNK(lstat_result.st_mode)
        or resolved != absolute
    ):
        raise ValidationError("provenance input must be a non-symlink regular file")
    descriptor = os.open(
        resolved,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if (
            opened.st_dev != lstat_result.st_dev
            or opened.st_ino != lstat_result.st_ino
            or opened.st_size != lstat_result.st_size
        ):
            raise ValidationError("provenance input identity changed during open")
        digest = hashlib.sha256()
        prefix = b""
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            if len(prefix) < 16:
                prefix += block[: 16 - len(prefix)]
            digest.update(block)
        return digest.hexdigest(), opened.st_size, prefix, opened.st_mode
    finally:
        os.close(descriptor)


def read_small_opened_regular(path: Path, maximum_bytes: int) -> tuple[str, bytes]:
    absolute = Path(os.path.abspath(path))
    try:
        lstat_result = absolute.lstat()
        resolved = absolute.resolve(strict=True)
    except OSError as error:
        raise ValidationError(f"cannot inspect provenance input {path}") from error
    if (
        not stat.S_ISREG(lstat_result.st_mode)
        or stat.S_ISLNK(lstat_result.st_mode)
        or resolved != absolute
    ):
        raise ValidationError("provenance input must be a non-symlink regular file")
    descriptor = os.open(
        resolved,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if (
            opened.st_dev != lstat_result.st_dev
            or opened.st_ino != lstat_result.st_ino
            or opened.st_size != lstat_result.st_size
            or opened.st_size > maximum_bytes
        ):
            raise ValidationError("small provenance input changed or exceeds its bound")
        payload = b""
        while len(payload) <= maximum_bytes:
            block = os.read(descriptor, min(65536, maximum_bytes + 1 - len(payload)))
            if not block:
                break
            payload += block
        if len(payload) != opened.st_size:
            raise ValidationError("small provenance input read is incomplete")
        return hashlib.sha256(payload).hexdigest(), payload
    finally:
        os.close(descriptor)


def exact_object(value: object, fields: set[str], description: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError(f"{description} does not have the exact field set")
    return value


def lowercase_sha256(value: object, description: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValidationError(f"{description} is not a lowercase SHA-256")
    return value


def validate_ntfscp_provenance(
    binary_path: Path,
    manifest_path: Path,
    *,
    allow_proposed_test_tool: bool,
) -> dict[str, object]:
    manifest_sha256, encoded = read_small_opened_regular(manifest_path, 64 * 1024)
    try:
        manifest = json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValidationError("ntfscp provenance manifest is not canonical UTF-8 JSON") from error
    if not isinstance(manifest, dict):
        raise ValidationError("ntfscp provenance manifest is not an object")
    format_version = manifest.get("format_version")
    if format_version not in {1, 2}:
        raise ValidationError("ntfscp provenance manifest version is unsupported")
    common_fields = {"format", "format_version", "state", "tool", "upstream", "binary"}
    version_field = "build" if format_version == 1 else "artifacts"
    top = exact_object(manifest, common_fields | {version_field}, "ntfscp provenance manifest")
    if top["format"] != "roothealth-ntfscp-provenance" or top["tool"] != "ntfscp":
        raise ValidationError("ntfscp provenance manifest identity is invalid")
    state = top["state"]
    permitted_states = {"release-qualified"}
    if allow_proposed_test_tool and format_version == 1:
        permitted_states.add("proposed-test-only")
    if state not in permitted_states:
        raise ValidationError("ntfscp provenance state is not permitted in this mode")
    if format_version == 2 and state != "release-qualified":
        raise ValidationError("v2 ntfscp provenance must be release-qualified")
    upstream = exact_object(
        top["upstream"], {"project", "commit", "archive_sha256"}, "upstream binding"
    )
    if (
        upstream["project"] != "ntfs-next"
        or upstream["commit"] != PINNED_NTFS_NEXT_COMMIT
        or upstream["archive_sha256"] != PINNED_NTFS_NEXT_ARCHIVE_SHA256
    ):
        raise ValidationError("ntfscp provenance is not bound to pinned ntfs-next d4")
    binary = exact_object(top["binary"], {"sha256", "bytes"}, "binary binding")
    expected_binary_sha256 = lowercase_sha256(binary["sha256"], "binary binding")
    if not isinstance(binary["bytes"], int) or isinstance(binary["bytes"], bool) or binary["bytes"] <= 0:
        raise ValidationError("ntfscp binary byte count is invalid")
    provenance_details: dict[str, object]
    if format_version == 1:
        build = exact_object(
            top["build"],
            {"source_manifest_sha256", "link_manifest_sha256", "qualification_sha256"},
            "build binding",
        )
        build_hashes = {
            key: lowercase_sha256(
                build[key], f"build binding {key}", nullable=state == "proposed-test-only"
            )
            for key in sorted(build)
        }
        if state == "release-qualified" and any(value is None for value in build_hashes.values()):
            raise ValidationError("release-qualified ntfscp lacks complete build provenance")
        provenance_details = {"build": build_hashes}
    else:
        artifacts = exact_object(
            top["artifacts"],
            {
                "archive", "source_manifest", "link_manifest", "runtime_manifest",
                "build_recipe", "qualification",
            },
            "artifact bindings",
        )
        artifact_hashes: dict[str, str] = {}
        artifact_payloads: dict[str, bytes] = {}
        manifest_directory = Path(os.path.abspath(manifest_path)).parent
        for name in sorted(artifacts):
            required_fields = {"path", "sha256", "bytes"}
            if name in {"source_manifest", "link_manifest"}:
                required_fields.add("records")
            binding = exact_object(artifacts[name], required_fields, f"{name} artifact binding")
            relative = binding["path"]
            if (
                not isinstance(relative, str)
                or not relative
                or Path(relative).name != relative
                or "/" in relative
                or "\\" in relative
            ):
                raise ValidationError(f"{name} artifact path is not a simple sibling name")
            expected_hash = lowercase_sha256(binding["sha256"], f"{name} artifact binding")
            expected_bytes = binding["bytes"]
            if (
                not isinstance(expected_bytes, int)
                or isinstance(expected_bytes, bool)
                or expected_bytes <= 0
            ):
                raise ValidationError(f"{name} artifact byte count is invalid")
            if "records" in binding and (
                not isinstance(binding["records"], int)
                or isinstance(binding["records"], bool)
                or binding["records"] <= 0
            ):
                raise ValidationError(f"{name} artifact record count is invalid")
            artifact_path = manifest_directory / relative
            actual_hash, actual_bytes, _, _ = sha256_opened_regular(artifact_path)
            if actual_hash != expected_hash or actual_bytes != expected_bytes:
                raise ValidationError(f"{name} artifact does not match its provenance binding")
            artifact_hashes[name] = actual_hash
            if name in {"runtime_manifest", "qualification"}:
                _, artifact_payloads[name] = read_small_opened_regular(artifact_path, 64 * 1024)
        if artifact_hashes["archive"] != PINNED_NTFS_NEXT_ARCHIVE_SHA256:
            raise ValidationError("ntfscp source archive artifact is not the pinned ntfs-next d4 archive")
        try:
            runtime = json.loads(artifact_payloads["runtime_manifest"].decode("utf-8"))
            qualification = json.loads(artifact_payloads["qualification"].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValidationError("ntfscp v2 JSON artifact is malformed") from error
        if (
            not isinstance(runtime, dict)
            or runtime.get("format") != "roothealth-ntfscp-runtime"
            or runtime.get("format_version") != 1
            or runtime.get("binary_sha256") != expected_binary_sha256
            or not isinstance(runtime.get("elf"), dict)
            or runtime["elf"].get("needed") != ["libc.so.6"]
            or runtime["elf"].get("pie") is not True
            or runtime["elf"].get("gnu_stack_executable") is not False
            or runtime["elf"].get("gnu_relro") is not True
            or runtime["elf"].get("bind_now") is not True
        ):
            raise ValidationError("ntfscp runtime artifact does not attest the selected hardened binary")
        qualification_artifacts = qualification.get("artifacts", {}) if isinstance(qualification, dict) else {}
        qualification_checks = qualification.get("checks", {}) if isinstance(qualification, dict) else {}
        reproducibility = qualification.get("reproducibility", {}) if isinstance(qualification, dict) else {}
        if (
            qualification.get("format") != "roothealth-ntfscp-qualification"
            or qualification.get("format_version") != 1
            or qualification.get("state") != "RELEASE_QUALIFIED"
            or qualification.get("upstream_commit") != PINNED_NTFS_NEXT_COMMIT
            or qualification.get("archive_sha256") != PINNED_NTFS_NEXT_ARCHIVE_SHA256
            or qualification.get("binary_sha256") != expected_binary_sha256
            or qualification.get("binary_bytes") != binary["bytes"]
            or qualification_artifacts.get("source_manifest_sha256") != artifact_hashes["source_manifest"]
            or qualification_artifacts.get("link_manifest_sha256") != artifact_hashes["link_manifest"]
            or qualification_artifacts.get("runtime_manifest_sha256") != artifact_hashes["runtime_manifest"]
            or qualification_artifacts.get("build_recipe_sha256") != artifact_hashes["build_recipe"]
            or not qualification_checks
            or not all(value is True for value in qualification_checks.values())
            or reproducibility.get("independent_clean_builds", 0) < 2
            or reproducibility.get("binary_byte_identical") is not True
        ):
            raise ValidationError("ntfscp qualification artifact is incomplete or not cross-bound")
        provenance_details = {"artifacts": artifact_hashes}
    actual_sha256, actual_bytes, prefix, binary_mode = sha256_opened_regular(binary_path)
    if prefix[:4] != b"\x7fELF":
        raise ValidationError("selected ntfscp is not an ELF executable")
    if binary_mode & 0o111 == 0:
        raise ValidationError("selected ntfscp is not executable")
    if actual_sha256 != expected_binary_sha256 or actual_bytes != binary["bytes"]:
        raise ValidationError("selected ntfscp does not match its provenance manifest")
    return {
        "format": format_version,
        "state": state,
        "tool": "ntfscp",
        "binary_path": str(Path(os.path.abspath(binary_path))),
        "binary_sha256": actual_sha256,
        "binary_bytes": actual_bytes,
        "manifest_path": str(Path(os.path.abspath(manifest_path))),
        "manifest_sha256": manifest_sha256,
        "upstream_commit": PINNED_NTFS_NEXT_COMMIT,
        "upstream_archive_sha256": PINNED_NTFS_NEXT_ARCHIVE_SHA256,
        **provenance_details,
    }


def create_seed(target: Path, output: Path, report_path: Path | None) -> dict[str, object]:
    with target.open("rb", buffering=0) as handle:
        volume = NtfsVolume(handle)
        journal_id = uuid.uuid4()
        first = build_empty_superblock(
            generation=1,
            sector_size=volume.sector_size,
            serial=volume.serial,
            journal_uuid=journal_id,
        )
        second = build_empty_superblock(
            generation=2,
            sector_size=volume.sector_size,
            serial=volume.serial,
            journal_uuid=journal_id,
        )
        serial = volume.serial
        sector_size = volume.sector_size

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(output, flags, 0o600)
    try:
        os.ftruncate(descriptor, JOURNAL_SIZE)
        if os.pwrite(descriptor, first, 0) != len(first):
            raise OSError("short first-superblock seed write")
        if os.pwrite(descriptor, second, SUPERBLOCK_SIZE) != len(second):
            raise OSError("short second-superblock seed write")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    result = {
        "format": 1,
        "state": "empty-seed-created",
        "output": str(output),
        "bytes": JOURNAL_SIZE,
        "sector_size": sector_size,
        "volume_serial": f"{serial:016X}",
        "journal_uuid": str(journal_id),
        "generations": [1, 2],
        "maximum_target_bytes": JOURNAL_MAX_TARGET_BYTES,
    }
    if report_path:
        write_new_report(report_path, result)
    return result


def write_new_report(path: Path, report: dict[str, object]) -> None:
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(encoded)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    seed = subparsers.add_parser("seed", help="create an EMPTY release journal seed")
    seed.add_argument("target", type=Path, help="unmounted NTFS image or block device")
    seed.add_argument("output", type=Path, help="new 128 MiB seed file")
    seed.add_argument("--report", type=Path, help="create a new JSON seed report")

    tool = subparsers.add_parser(
        "verify-ntfscp",
        help="verify the exact selected d4 ntfscp binary and provenance manifest",
    )
    tool.add_argument("binary", type=Path, help="selected non-symlink ntfscp ELF")
    tool.add_argument("manifest", type=Path, help="exact v1 provenance JSON")
    tool.add_argument(
        "--allow-proposed-test-tool",
        action="store_true",
        help="test-only acceptance of a manifest explicitly marked proposed-test-only",
    )
    tool.add_argument("--report", type=Path, help="create a new JSON report")

    provision = subparsers.add_parser(
        "provision-flags",
        help="builder/test-only synchronization of protected journal namespace flags",
    )
    provision.add_argument(
        "target",
        type=Path,
        help="fresh unmounted regular build-owned NTFS image ending in .building",
    )
    provision.add_argument("--report", type=Path, help="create a new JSON report")

    provision_device = subparsers.add_parser(
        "provision-flags-device",
        help="builder-only synchronization on a block node bound to a .building image",
    )
    provision_device.add_argument(
        "target",
        type=Path,
        help="unmounted loop partition or mapper holding the fresh NTFS root",
    )
    provision_device.add_argument(
        "--builder-image",
        type=Path,
        required=True,
        help="exact non-symlink regular full-disk backing image ending in .building",
    )
    provision_device.add_argument(
        "--root-kind",
        choices=("plain", "luks"),
        required=True,
        help="exact GPT partition-2 profile and permitted block-stack shape",
    )
    provision_device.add_argument(
        "--expected-partition-name",
        required=True,
        help="exact UTF-16 GPT name required for the selected root partition",
    )
    provision_device.add_argument(
        "--root-partition-number",
        type=int,
        choices=range(1, 129),
        default=2,
        help="exact GPT partition number holding the root (default: 2)",
    )
    provision_device.add_argument(
        "--expected-mapper-name",
        help="exact dm-crypt mapper name (required for luks, forbidden for plain)",
    )
    provision_device.add_argument(
        "--report", type=Path, help="create a new JSON report"
    )

    validate = subparsers.add_parser("validate", help="validate a provisioned journal")
    validate.add_argument("target", type=Path, help="unmounted NTFS image or block device")
    validate.add_argument(
        "--expected-size",
        type=parse_size,
        default=JOURNAL_SIZE,
        help="required journal data-stream size in bytes (default: 128 MiB)",
    )
    validate.add_argument(
        "--require-one-run",
        action="store_true",
        help="require the freshly provisioned journal to be physically contiguous",
    )
    validate.add_argument(
        "--require-zero-entry-area",
        action="store_true",
        help="read and prove that every release entry-area byte is zero",
    )
    validate.add_argument("--report", type=Path, help="create a new JSON report")
    arguments = parser.parse_args()

    try:
        if arguments.command == "seed":
            report = create_seed(arguments.target, arguments.output, arguments.report)
            if not arguments.report:
                sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
            return 0
        if arguments.command == "verify-ntfscp":
            report = validate_ntfscp_provenance(
                arguments.binary,
                arguments.manifest,
                allow_proposed_test_tool=arguments.allow_proposed_test_tool,
            )
            if arguments.report:
                write_new_report(arguments.report, report)
            else:
                sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
            return 0
        if arguments.command == "provision-flags":
            report = provision_protected_flags(arguments.target)
            if arguments.report:
                write_new_report(arguments.report, report)
            else:
                sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
            return 0
        if arguments.command == "provision-flags-device":
            report = provision_protected_flags_device(
                arguments.target,
                arguments.builder_image,
                arguments.root_kind,
                arguments.expected_partition_name,
                arguments.expected_mapper_name,
                arguments.root_partition_number,
            )
            if arguments.report:
                write_new_report(arguments.report, report)
            else:
                sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
            return 0
        with arguments.target.open("rb", buffering=0) as handle:
            volume = NtfsVolume(handle)
            report = validate_journal(
                volume,
                arguments.expected_size,
                arguments.require_one_run,
                arguments.require_zero_entry_area,
            )
        encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if arguments.report:
            write_new_report(arguments.report, report)
        else:
            sys.stdout.write(encoded)
        return 0
    except (OSError, ValidationError) as error:
        print(f"roothealth journal validation failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
