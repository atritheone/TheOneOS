#!/usr/bin/env python3
"""Mutate and independently inspect runtime $RootHealth WAL superblocks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import uuid


BLOCK_SIZE = 4096
DIGEST_OFFSET = 0xFE0
MAGIC = b"T1ROOTHEALTHWAL\0"
JOURNAL_SIZE = 128 * 1024 * 1024
ENTRY_START = 8192
MAX_TARGET_BYTES = 100 * 1024 * 1024
MAX_ENTRY_COUNT = 4096
STATES = {0: "EMPTY", 1: "PREPARING", 2: "APPLYING", 3: "COMMITTED", 4: "ROLLBACK"}
TRANSACTION_KINDS = {0: "NONE", 1: "METADATA_REPAIR", 2: "DIRTY_CLEAR"}
ENTRY_MAGIC = b"RHENTRY1"
ENTRY_SIZE = 512
ENTRY_DIGEST_OFFSET = 0x1E0
ENTRY_RESERVED_OFFSET = 0x180
SEMANTIC_SEAL_VERSION = 1
SEMANTIC_EVIDENCE_VERSION = 1
SEMANTIC_TARGETS = {
    1: "BOOT_PRIMARY",
    2: "BOOT_BACKUP",
    3: "MFT_RECORD_PRIMARY",
    4: "MFT_RECORD_MIRROR",
    5: "NONRESIDENT_ATTRIBUTE",
    6: "PROVEN_FREE_ALLOCATION",
}
TARGET_PRIMARY = 0x0001
TARGET_MIRROR = 0x0002
TARGET_RESIDENT = 0x0004
TARGET_NONRESIDENT = 0x0008
TARGET_PRETRANSACTION_FREE = 0x0010
TARGET_SET_ONLY = 0x0020
TARGET_CLEAR_ONLY = 0x0040
TARGET_NATIVE_LOG_DERIVED = 0x0080
TARGET_FLAGS_MASK = 0x00FF
RECOVERY_REDERIVATION_ACTIONS = {23, 24, 25}
NTFS_OEM_ID = b"NTFS    "
AT_VOLUME_INFORMATION = 0x70
AT_END = 0xFFFFFFFF
VOLUME_RECORD = 3
ACTION_KINDS = {
    1: "boot-primary",
    2: "boot-backup",
    3: "mft-primary",
    4: "mft-mirror",
    5: "logfile-redo",
    6: "logfile-restart",
    7: "mft-record",
    8: "attribute-list",
    9: "runlist-mapping-pairs",
    10: "attribute-data",
    11: "index-root",
    12: "index-allocation",
    13: "index-bitmap",
    14: "cluster-data",
    15: "recovery-namespace",
    16: "reparse-index",
    17: "secure-sds",
    18: "secure-sdh",
    19: "secure-sii",
    20: "upcase-data",
    21: "attrdef-data",
    22: "bitmap-mft",
    23: "bitmap-cluster",
    24: "volume-dirty-set",
    25: "volume-dirty-clear",
}


class WalFixtureError(RuntimeError):
    pass


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def u16(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def s64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<q", data, offset)[0]


def layout(path: Path) -> dict[str, object]:
    report = json.loads(path.read_text(encoding="utf-8"))
    device = report.get("device")
    journal = report.get("journal")
    if not isinstance(device, dict) or not isinstance(journal, dict):
        raise WalFixtureError("canonical journal layout report is incomplete")
    runs = journal.get("runs")
    if (
        journal.get("run_count") != 1
        or not isinstance(runs, list)
        or len(runs) != 1
        or runs[0].get("vcn") != 0
    ):
        raise WalFixtureError("qualification WAL must use its validated one-run layout")
    cluster_size = device.get("cluster_size")
    lcn = runs[0].get("lcn")
    serial_text = device.get("serial")
    device_bytes = device.get("bytes")
    sector_size = device.get("sector_size")
    allocated_bytes = journal.get("allocated_bytes")
    if (
        type(cluster_size) is not int
        or type(lcn) is not int
        or type(device_bytes) is not int
        or type(sector_size) is not int
        or type(allocated_bytes) is not int
    ):
        raise WalFixtureError("qualification WAL layout has invalid geometry")
    if (
        cluster_size <= 0
        or sector_size <= 0
        or cluster_size % sector_size
        or allocated_bytes != JOURNAL_SIZE
        or lcn < 0
        or lcn * cluster_size + allocated_bytes > device_bytes
    ):
        raise WalFixtureError("qualification WAL layout geometry is out of bounds")
    if not isinstance(serial_text, str) or len(serial_text) != 16:
        raise WalFixtureError("qualification WAL layout has invalid serial")
    header = journal.get("header")
    exclusions = journal.get("write_exclusion")
    if not isinstance(header, dict) or not isinstance(exclusions, dict):
        raise WalFixtureError("qualification WAL binding/exclusions are absent")
    journal_uuid = header.get("journal_uuid")
    try:
        parsed_journal_uuid = str(uuid.UUID(str(journal_uuid)))
    except (ValueError, AttributeError) as error:
        raise WalFixtureError("qualification WAL UUID is invalid") from error
    exclusion_ranges: list[dict[str, int]] = []
    for field in ("data_stream", "base_file_record"):
        ranges = exclusions.get(field)
        if not isinstance(ranges, list) or not ranges:
            raise WalFixtureError(f"qualification WAL {field} exclusion is absent")
        for raw_range in ranges:
            if not isinstance(raw_range, dict):
                raise WalFixtureError(f"qualification WAL {field} exclusion is invalid")
            offset = raw_range.get("device_offset")
            length = raw_range.get("bytes")
            if (
                type(offset) is not int
                or type(length) is not int
                or offset < 0
                or length <= 0
                or offset + length > device_bytes
            ):
                raise WalFixtureError(
                    f"qualification WAL {field} exclusion is out of bounds"
                )
            exclusion_ranges.append(
                {"offset": offset, "length": length, "source": field}
            )
    return {
        "offset": lcn * cluster_size,
        "sector_size": sector_size,
        "cluster_size": cluster_size,
        "device_bytes": device_bytes,
        "allocated_bytes": allocated_bytes,
        "serial": int(serial_text, 16),
        "journal_uuid": parsed_journal_uuid,
        "write_exclusion": exclusion_ranges,
    }


def read_headers(image: Path, base: int) -> tuple[bytes, bytes]:
    with image.open("rb", buffering=0) as handle:
        first = os.pread(handle.fileno(), BLOCK_SIZE, base)
        second = os.pread(handle.fileno(), BLOCK_SIZE, base + BLOCK_SIZE)
    if len(first) != BLOCK_SIZE or len(second) != BLOCK_SIZE:
        raise WalFixtureError("short WAL superblock read")
    return first, second


def parse_header(block: bytes, expected_sector: int) -> dict[str, object]:
    if len(block) != BLOCK_SIZE or block[:16] != MAGIC:
        raise WalFixtureError("invalid magic or superblock size")
    if u32(block, 0x10) != 1 or u32(block, 0x14) != BLOCK_SIZE:
        raise WalFixtureError("invalid WAL version/header size")
    if u32(block, 0x18) != expected_sector:
        raise WalFixtureError("WAL sector-size binding differs")
    state_value = u32(block, 0x1C)
    if state_value not in STATES:
        raise WalFixtureError("invalid WAL state")
    generation = u64(block, 0x20)
    if generation == 0:
        raise WalFixtureError("zero WAL generation")
    serial = u64(block, 0x28)
    journal_id = uuid.UUID(bytes=block[0x30:0x40])
    transaction_id = uuid.UUID(bytes=block[0x40:0x50])
    if journal_id.int == 0:
        raise WalFixtureError("zero WAL journal UUID")
    if u64(block, 0x50) != JOURNAL_SIZE or u64(block, 0x58) != ENTRY_START:
        raise WalFixtureError("invalid WAL capacity/entry offset")
    data_used = u64(block, 0x60)
    entries = u64(block, 0x68)
    target_bytes = u64(block, 0x70)
    if (
        data_used > JOURNAL_SIZE - ENTRY_START
        or entries > MAX_ENTRY_COUNT
        or target_bytes > MAX_TARGET_BYTES
    ):
        raise WalFixtureError("WAL committed bounds are invalid")
    transaction_kind_value = u32(block, 0xA0)
    if transaction_kind_value not in TRANSACTION_KINDS:
        raise WalFixtureError("WAL transaction kind is invalid")
    if u64(block, 0x98) != MAX_TARGET_BYTES or u32(block, 0xA4) != MAX_ENTRY_COUNT:
        raise WalFixtureError("WAL policy bounds are invalid")
    if any(block[0xA8:DIGEST_OFFSET]):
        raise WalFixtureError("WAL reserved bytes are nonzero")
    if block[DIGEST_OFFSET:] != hashlib.sha256(block[:DIGEST_OFFSET]).digest():
        raise WalFixtureError("WAL header digest differs")
    state = STATES[state_value]
    if state == "EMPTY":
        if (
            transaction_id.int
            or transaction_kind_value
            or data_used
            or entries
            or target_bytes
            or any(block[0x78:0x98])
        ):
            raise WalFixtureError("EMPTY WAL contains transaction state")
    elif (
        transaction_id.int == 0
        or transaction_kind_value == 0
        or not any(block[0x78:0x98])
    ):
        raise WalFixtureError(
            "non-EMPTY WAL lacks transaction UUID, kind, or complete plan hash"
        )
    return {
        "generation": generation,
        "state": state,
        "serial": f"0x{serial:016x}",
        "journal_uuid": str(journal_id),
        "transaction_uuid": str(transaction_id),
        "transaction_kind": TRANSACTION_KINDS[transaction_kind_value],
        "data_used": data_used,
        "entry_count": entries,
        "target_bytes": target_bytes,
        "plan_sha256": block[0x78:0x98].hex(),
        "max_target_bytes": u64(block, 0x98),
        "max_entry_count": u32(block, 0xA4),
        "sha256": hashlib.sha256(block).hexdigest(),
    }


def read_exact(handle: object, length: int, offset: int, description: str) -> bytes:
    payload = os.pread(handle.fileno(), length, offset)  # type: ignore[attr-defined]
    if len(payload) != length:
        raise WalFixtureError(f"short {description} read")
    return payload


def overlaps(first_offset: int, first_length: int, second_offset: int, second_length: int) -> bool:
    return first_offset < second_offset + second_length and second_offset < first_offset + first_length


def parse_ntfs_boot_geometry(
    boot: bytes, details: dict[str, object]
) -> dict[str, int]:
    sector_size = int(details["sector_size"])
    cluster_size = int(details["cluster_size"])
    device_bytes = int(details["device_bytes"])
    if (
        len(boot) != sector_size
        or sector_size < 512
        or boot[3:11] != NTFS_OEM_ID
        or boot[510:512] != b"\x55\xaa"
        or u16(boot, 11) != sector_size
    ):
        raise WalFixtureError("NTFS boot geometry is not independently readable")
    sectors_per_cluster = boot[13]
    if (
        sectors_per_cluster == 0
        or sectors_per_cluster & (sectors_per_cluster - 1)
        or sectors_per_cluster * sector_size != cluster_size
    ):
        raise WalFixtureError("NTFS boot cluster geometry differs from layout")
    total_sectors = u64(boot, 40)
    total_clusters = total_sectors // sectors_per_cluster
    mft_lcn = u64(boot, 48)
    mftmirr_lcn = u64(boot, 56)
    record_code = struct.unpack_from("<b", boot, 64)[0]
    if record_code == 0:
        raise WalFixtureError("NTFS FILE-record size code is zero")
    record_size = (
        1 << -record_code if record_code < 0 else record_code * cluster_size
    )
    if (
        total_sectors <= 0
        or total_sectors * sector_size > device_bytes
        or total_clusters <= 0
        or mft_lcn >= total_clusters
        or mftmirr_lcn >= total_clusters
        or record_size < sector_size
        or record_size > 65536
        or record_size % sector_size
        or u64(boot, 72) != int(details["serial"])
    ):
        raise WalFixtureError("NTFS mirrored-record geometry is invalid or misbound")
    return {
        "cluster_size": cluster_size,
        "mft_lcn": mft_lcn,
        "mftmirr_lcn": mftmirr_lcn,
        "record_size": record_size,
    }


def mirrored_mft_geometry(
    image: Path, details: dict[str, object]
) -> dict[str, int] | None:
    sector_size = int(details["sector_size"])
    device_bytes = int(details["device_bytes"])
    candidates: list[dict[str, int]] = []
    with image.open("rb", buffering=0) as handle:
        for offset in dict.fromkeys((0, device_bytes - sector_size)):
            try:
                boot = read_exact(handle, sector_size, offset, "NTFS boot sector")
                candidate = parse_ntfs_boot_geometry(boot, details)
            except WalFixtureError:
                continue
            if candidate not in candidates:
                candidates.append(candidate)
    if not candidates:
        return None
    if len(candidates) != 1:
        raise WalFixtureError("primary and backup NTFS mirrored-record geometry differs")
    geometry = candidates[0]
    record_size = geometry["record_size"]
    cluster_size = geometry["cluster_size"]
    if record_size * 4 > cluster_size:
        return None
    primary = geometry["mft_lcn"] * cluster_size
    mirror = geometry["mftmirr_lcn"] * cluster_size
    mirrored_bytes = record_size * 4
    if (
        primary + mirrored_bytes > device_bytes
        or mirror + mirrored_bytes > device_bytes
        or overlaps(primary, mirrored_bytes, mirror, mirrored_bytes)
    ):
        raise WalFixtureError("NTFS mirrored-record physical ranges are invalid")
    return {
        "primary": primary,
        "mirror": mirror,
        "record_size": record_size,
    }


def classify_mirrored_mft_entry(
    entry: dict[str, object], geometry: dict[str, int]
) -> tuple[str, int, int] | None:
    target_offset = int(entry["target_offset"])
    target_length = int(entry["target_length"])
    target_end = target_offset + target_length
    record_size = geometry["record_size"]
    overlap_found = False
    for copy in ("primary", "mirror"):
        copy_base = geometry[copy]
        for record in range(4):
            record_base = copy_base + record * record_size
            record_end = record_base + record_size
            if target_offset >= record_base and target_end <= record_end:
                return copy, record, target_offset - record_base
            if overlaps(target_offset, target_length, record_base, record_size):
                overlap_found = True
    if overlap_found:
        raise WalFixtureError(
            "WAL entry crosses a mirrored MFT record physical boundary"
        )
    return None


def validate_physical_mft_pair(
    first: dict[str, object],
    second: dict[str, object],
    geometry: dict[str, int],
    *,
    description: str,
) -> tuple[tuple[str, int, int], tuple[str, int, int]]:
    first_location = classify_mirrored_mft_entry(first, geometry)
    second_location = classify_mirrored_mft_entry(second, geometry)
    if first_location is None or second_location is None:
        raise WalFixtureError(f"{description} does not name both mirrored MFT copies")
    if first_location[0] != "primary" or second_location[0] != "mirror":
        raise WalFixtureError(f"{description} is not ordered primary then mirror")
    if (
        first_location[1:] != second_location[1:]
        or first["action"] != second["action"]
        or first["target_length"] != second["target_length"]
    ):
        raise WalFixtureError(f"{description} physical entries do not match")
    return first_location, second_location


def apply_file_fixups(raw: bytes, sector_size: int) -> bytes:
    if len(raw) < sector_size or len(raw) % sector_size or raw[:4] != b"FILE":
        raise WalFixtureError("dirty-action payload is not an NTFS FILE record")
    fixed = bytearray(raw)
    usa_offset = u16(fixed, 4)
    usa_count = u16(fixed, 6)
    if (
        usa_count != len(fixed) // sector_size + 1
        or usa_offset < 8
        or usa_offset + usa_count * 2 > len(fixed)
    ):
        raise WalFixtureError("dirty-action FILE record has invalid fixup bounds")
    update_sequence = fixed[usa_offset : usa_offset + 2]
    for index in range(1, usa_count):
        tail = index * sector_size - 2
        if fixed[tail : tail + 2] != update_sequence:
            raise WalFixtureError("dirty-action FILE record fixup sequence differs")
        replacement = usa_offset + index * 2
        fixed[tail : tail + 2] = fixed[replacement : replacement + 2]
    return bytes(fixed)


def volume_information_flags(raw: bytes, sector_size: int) -> tuple[int, int]:
    fixed = apply_file_fixups(raw, sector_size)
    if len(fixed) < 48 or u32(fixed, 44) != VOLUME_RECORD:
        raise WalFixtureError("dirty-action payload is not $Volume record 3")
    first_attribute = u16(fixed, 20)
    used = u32(fixed, 24)
    if first_attribute < 48 or used > len(fixed) or first_attribute >= used:
        raise WalFixtureError("dirty-action $Volume attribute bounds are invalid")
    found: list[tuple[int, int]] = []
    cursor = first_attribute
    while cursor + 4 <= used:
        attribute_type = u32(fixed, cursor)
        if attribute_type == AT_END:
            break
        if cursor + 24 > used:
            raise WalFixtureError("dirty-action $Volume attribute is truncated")
        attribute_length = u32(fixed, cursor + 4)
        if (
            attribute_length < 24
            or attribute_length % 8
            or cursor + attribute_length > used
        ):
            raise WalFixtureError("dirty-action $Volume attribute length is invalid")
        if attribute_type == AT_VOLUME_INFORMATION:
            if fixed[cursor + 8] != 0:
                raise WalFixtureError("$VOLUME_INFORMATION is unexpectedly nonresident")
            value_length = u32(fixed, cursor + 16)
            value_offset = u16(fixed, cursor + 20)
            if (
                value_length < 12
                or value_offset < 24
                or value_offset + value_length > attribute_length
            ):
                raise WalFixtureError("$VOLUME_INFORMATION value bounds are invalid")
            flags_offset = cursor + value_offset + 10
            found.append((u16(fixed, flags_offset), flags_offset))
        cursor += attribute_length
    if len(found) != 1:
        raise WalFixtureError(
            "dirty-action $Volume record lacks one $VOLUME_INFORMATION"
        )
    return found[0]


def dirty_record_evidence(
    image: Path,
    entry: dict[str, object],
    evidence: dict[str, object],
    location: tuple[str, int, int],
    geometry: dict[str, int],
    sector_size: int,
) -> tuple[int, int | None]:
    copy, record, relative_offset = location
    if record != VOLUME_RECORD:
        raise WalFixtureError("dirty-action pair does not target $Volume record 3")
    record_base = geometry[copy] + record * geometry["record_size"]
    with image.open("rb", buffering=0) as handle:
        current_record = bytearray(
            read_exact(
                handle,
                geometry["record_size"],
                record_base,
                f"{copy} $Volume record",
            )
        )
    old_payload = evidence["old_payload"]
    if not isinstance(old_payload, bytes):
        raise WalFixtureError("dirty-action payload evidence is absent")
    old_record = bytearray(current_record)
    old_record[relative_offset : relative_offset + len(old_payload)] = old_payload
    old_flags, flags_offset = volume_information_flags(bytes(old_record), sector_size)
    target_length = int(entry["target_length"])
    if not (
        relative_offset <= flags_offset
        and flags_offset + 2 <= relative_offset + target_length
    ):
        raise WalFixtureError("dirty-action target does not cover the NTFS dirty flag")
    current_payload = evidence["current_payload"]
    new_hash = evidence["new_hash"]
    new_flags: int | None = None
    if (
        isinstance(current_payload, bytes)
        and isinstance(new_hash, bytes)
        and hashlib.sha256(current_payload).digest() == new_hash
    ):
        new_flags, new_flags_offset = volume_information_flags(
            bytes(current_record), sector_size
        )
        if new_flags_offset != flags_offset:
            raise WalFixtureError("dirty-action changed $VOLUME_INFORMATION layout")
    return old_flags, new_flags


def validate_dirty_action_pair(
    image: Path,
    entries: list[dict[str, object]],
    evidence: list[dict[str, object]],
    geometry: dict[str, int] | None,
    action: str,
    sector_size: int,
) -> None:
    if geometry is None:
        raise WalFixtureError(
            f"{action} pair cannot be bound to mirrored NTFS geometry"
        )
    first, second = entries
    first_location, second_location = validate_physical_mft_pair(
        first, second, geometry, description=f"{action} pair"
    )
    if (
        first_location[1] != VOLUME_RECORD
        or evidence[0]["old_payload"] != evidence[1]["old_payload"]
        or evidence[0]["new_hash"] != evidence[1]["new_hash"]
    ):
        raise WalFixtureError(f"{action} pair encodes mismatched physical transitions")
    old_first, new_first = dirty_record_evidence(
        image, first, evidence[0], first_location, geometry, sector_size
    )
    old_second, new_second = dirty_record_evidence(
        image, second, evidence[1], second_location, geometry, sector_size
    )
    expected_old_dirty = action == "volume-dirty-clear"
    if (
        old_first != old_second
        or bool(old_first & 1) != expected_old_dirty
    ):
        raise WalFixtureError(f"{action} pair has a mismatched semantic source flag")
    observed_new = [value for value in (new_first, new_second) if value is not None]
    for new_flags in observed_new:
        if (new_flags ^ old_first) != 1 or bool(new_flags & 1) == expected_old_dirty:
            raise WalFixtureError(f"{action} semantic flag delta differs")
    if len(observed_new) == 2 and observed_new[0] != observed_new[1]:
        raise WalFixtureError(f"{action} pair has mismatched semantic flag deltas")


def validate_dirty_action_primary_prefix(
    image: Path,
    entry: dict[str, object],
    evidence: dict[str, object],
    geometry: dict[str, int] | None,
    action: str,
    sector_size: int,
) -> None:
    """Validate the primary half of an interrupted mirrored dirty pair."""
    if geometry is None:
        raise WalFixtureError(
            f"{action} prefix cannot be bound to mirrored NTFS geometry"
        )
    location = classify_mirrored_mft_entry(entry, geometry)
    if location is None or location[0] != "primary" or location[1] != VOLUME_RECORD:
        raise WalFixtureError(
            f"{action} interrupted prefix is not the primary $Volume entry"
        )
    old_flags, new_flags = dirty_record_evidence(
        image, entry, evidence, location, geometry, sector_size
    )
    expected_old_dirty = action == "volume-dirty-clear"
    if bool(old_flags & 1) != expected_old_dirty:
        raise WalFixtureError(f"{action} prefix has a mismatched semantic source flag")
    if new_flags is not None and (
        (new_flags ^ old_flags) != 1
        or bool(new_flags & 1) == expected_old_dirty
    ):
        raise WalFixtureError(f"{action} prefix semantic flag delta differs")


def validate_general_mft_pairs(
    entries: list[dict[str, object]],
    geometry: dict[str, int] | None,
    *,
    allow_trailing_primary: bool = False,
) -> None:
    if geometry is None:
        return
    foundation_actions = {"mft-primary", "mft-mirror"}
    index = 0
    while index < len(entries):
        entry = entries[index]
        location = classify_mirrored_mft_entry(entry, geometry)
        if location is None or entry["action"] in foundation_actions:
            index += 1
            continue
        if location[0] == "mirror":
            raise WalFixtureError(
                "mirrored MFT mirror entry precedes or lacks its primary pair"
            )
        if index + 1 >= len(entries):
            if allow_trailing_primary:
                return
            raise WalFixtureError(
                "mirrored MFT primary entry lacks an adjacent mirror pair"
            )
        try:
            validate_physical_mft_pair(
                entry,
                entries[index + 1],
                geometry,
                description="adjacent mirrored MFT pair",
            )
        except WalFixtureError as error:
            raise WalFixtureError(
                f"mirrored MFT primary entry has no matching adjacent mirror: {error}"
            ) from error
        index += 2


def validate_semantic_seal(
    descriptor: bytes,
    action_value: int,
    target_offset: int,
    target_length: int,
    old_payload: bytes,
    ordinal: int,
) -> dict[str, object]:
    seal_version = u32(descriptor, 0x080)
    target_object = u32(descriptor, 0x084)
    owner_record = u64(descriptor, 0x088)
    owner_sequence = u16(descriptor, 0x090)
    attribute_instance = u16(descriptor, 0x092)
    attribute_type = u32(descriptor, 0x094)
    name_length = u16(descriptor, 0x098)
    flags = u16(descriptor, 0x09A)
    evidence_version = u32(descriptor, 0x09C)
    name_hash = descriptor[0x0A0:0x0C0]
    lowest_vcn = s64(descriptor, 0x0C0)
    logical_vcn = s64(descriptor, 0x0C8)
    logical_offset = u64(descriptor, 0x0D0)
    logical_length = u64(descriptor, 0x0D8)
    semantic_offset = u64(descriptor, 0x0E0)
    semantic_length = u64(descriptor, 0x0E8)
    lcn = s64(descriptor, 0x0F0)
    evidence_generation = u64(descriptor, 0x0F8)
    evidence_hash = descriptor[0x100:0x120]
    staged_view_hash = descriptor[0x120:0x140]
    semantic_before_hash = descriptor[0x140:0x160]
    semantic_after_hash = descriptor[0x160:0x180]
    action = ACTION_KINDS[action_value]

    if action_value < 5:
        raise WalFixtureError(
            f"WAL descriptor {ordinal} uses foundation-only action {action}"
        )
    if seal_version != SEMANTIC_SEAL_VERSION or target_object not in SEMANTIC_TARGETS:
        raise WalFixtureError(f"WAL descriptor {ordinal} semantic target header differs")
    if flags & ~TARGET_FLAGS_MASK:
        raise WalFixtureError(f"WAL descriptor {ordinal} semantic flags are unknown")
    if name_length > 255:
        raise WalFixtureError(f"WAL descriptor {ordinal} attribute name is too long")
    if (
        not logical_length
        or logical_length != semantic_length
        or not semantic_length
        or semantic_offset < target_offset
        or semantic_offset - target_offset > target_length
        or semantic_length > target_length - (semantic_offset - target_offset)
    ):
        raise WalFixtureError(f"WAL descriptor {ordinal} semantic range is invalid")
    if (
        evidence_version != SEMANTIC_EVIDENCE_VERSION
        or not evidence_generation
        or not any(evidence_hash)
        or not any(staged_view_hash)
        or not any(semantic_before_hash)
        or not any(semantic_after_hash)
    ):
        raise WalFixtureError(f"WAL descriptor {ordinal} semantic evidence is incomplete")
    semantic_relative = semantic_offset - target_offset
    if hashlib.sha256(
        old_payload[semantic_relative : semantic_relative + semantic_length]
    ).digest() != semantic_before_hash:
        raise WalFixtureError(
            f"WAL descriptor {ordinal} semantic before-image hash differs"
        )

    location = flags & (TARGET_PRIMARY | TARGET_MIRROR)
    residency = flags & (TARGET_RESIDENT | TARGET_NONRESIDENT)
    mode = flags & (TARGET_SET_ONLY | TARGET_CLEAR_ONLY)
    if location == TARGET_PRIMARY | TARGET_MIRROR:
        raise WalFixtureError(f"WAL descriptor {ordinal} has two semantic locations")
    if residency == TARGET_RESIDENT | TARGET_NONRESIDENT:
        raise WalFixtureError(f"WAL descriptor {ordinal} has two residency flags")
    if mode == TARGET_SET_ONLY | TARGET_CLEAR_ONLY:
        raise WalFixtureError(f"WAL descriptor {ordinal} has two mutation modes")
    if bool(flags & TARGET_NATIVE_LOG_DERIVED) != (action_value in (5, 6)):
        raise WalFixtureError(f"WAL descriptor {ordinal} native-log flag differs")
    if action_value not in (22, 23, 24, 25) and mode:
        raise WalFixtureError(f"WAL descriptor {ordinal} has an inapplicable mutation mode")

    base_flags = flags & (
        TARGET_PRIMARY
        | TARGET_MIRROR
        | TARGET_RESIDENT
        | TARGET_NONRESIDENT
        | TARGET_PRETRANSACTION_FREE
    )
    if target_object == 1:
        expected_base = TARGET_PRIMARY
        object_valid = (
            not owner_record and not owner_sequence and not attribute_type
            and lowest_vcn == logical_vcn == lcn == -1 and logical_offset == 0
        )
    elif target_object == 2:
        expected_base = TARGET_MIRROR
        object_valid = (
            not owner_record and not owner_sequence and not attribute_type
            and lowest_vcn == logical_vcn == lcn == -1 and logical_offset == 0
        )
    elif target_object in (3, 4):
        expected_base = (
            TARGET_PRIMARY if target_object == 3 else TARGET_MIRROR
        ) | TARGET_RESIDENT
        object_valid = (
            owner_sequence != 0 and lowest_vcn == logical_vcn == lcn == -1
            and (target_object != 4 or owner_record <= 3)
        )
    elif target_object in (5, 6):
        expected_base = TARGET_NONRESIDENT | (
            TARGET_PRETRANSACTION_FREE if target_object == 6 else 0
        )
        object_valid = (
            owner_sequence != 0 and attribute_type != 0 and lowest_vcn >= 0
            and logical_vcn >= lowest_vcn and lcn >= 0
        )
    else:
        raise AssertionError("semantic target object table differs")
    if base_flags != expected_base or not object_valid:
        raise WalFixtureError(f"WAL descriptor {ordinal} semantic object fields differ")

    empty_name_hash = hashlib.sha256(b"").digest()
    if attribute_type:
        if not any(name_hash) or (name_length == 0 and name_hash != empty_name_hash):
            raise WalFixtureError(f"WAL descriptor {ordinal} attribute-name seal differs")
    elif attribute_instance or name_length or any(name_hash):
        raise WalFixtureError(f"WAL descriptor {ordinal} fabricated attribute identity")

    if action_value == 23:
        if not (
            target_object == 5
            and owner_record == 6
            and attribute_type == 0x80
            and name_length == 0
            and name_hash == empty_name_hash
            and flags == TARGET_NONRESIDENT
            and lowest_vcn == 0
            and logical_vcn >= 0
            and logical_length == 1
            and semantic_length == 1
            and lcn >= 0
        ):
            raise WalFixtureError(
                f"WAL descriptor {ordinal} cluster-bitmap semantic profile differs"
            )
    elif action_value in (24, 25):
        expected_mode = TARGET_SET_ONLY if action_value == 24 else TARGET_CLEAR_ONLY
        expected_location = TARGET_PRIMARY if target_object == 3 else TARGET_MIRROR
        if not (
            target_object in (3, 4)
            and owner_record == VOLUME_RECORD
            and attribute_type == AT_VOLUME_INFORMATION
            and name_length == 0
            and name_hash == empty_name_hash
            and flags == expected_location | TARGET_RESIDENT | expected_mode
            and lowest_vcn == logical_vcn == lcn == -1
            and logical_offset == 10
            and logical_length == semantic_length == 2
        ):
            raise WalFixtureError(
                f"WAL descriptor {ordinal} dirty-flag semantic profile differs"
            )

    return {
        "seal_version": seal_version,
        "target_object": SEMANTIC_TARGETS[target_object],
        "owner_mft_record": owner_record,
        "owner_sequence": owner_sequence,
        "attribute_instance": attribute_instance,
        "attribute_type": attribute_type,
        "attribute_name_length": name_length,
        "attribute_name_sha256": name_hash.hex(),
        "flags": flags,
        "lowest_vcn": lowest_vcn,
        "logical_vcn": logical_vcn,
        "logical_offset": logical_offset,
        "logical_length": logical_length,
        "semantic_target_offset": semantic_offset,
        "semantic_target_length": semantic_length,
        "lcn": lcn,
        "evidence_version": evidence_version,
        "evidence_generation": evidence_generation,
        "evidence_sha256": evidence_hash.hex(),
        "staged_view_sha256": staged_view_hash.hex(),
        "semantic_before_sha256": semantic_before_hash.hex(),
        "semantic_after_sha256": semantic_after_hash.hex(),
    }


def inspect_entries(
    image: Path, details: dict[str, object], header: dict[str, object]
) -> dict[str, object]:
    state = header["state"]
    entry_count = int(header["entry_count"])
    data_used = int(header["data_used"])
    target_bytes = int(header["target_bytes"])
    if state == "EMPTY":
        return {
            "valid": True,
            "entry_count": 0,
            "data_used": 0,
            "target_bytes": 0,
            "plan_sha256": "0" * 64,
            "actions": {},
            "entries": [],
            "complete_plan_verified": True,
            "semantic_seals_valid": True,
            "evidence_generation": None,
            "recovery_rederivation_supported": True,
        }
    empty_prefix = entry_count == 0 and data_used == 0 and target_bytes == 0
    if empty_prefix:
        if state not in ("PREPARING", "ROLLBACK"):
            raise WalFixtureError(
                f"{state} WAL has an impermissible zero-entry durable prefix"
            )
        return {
            "valid": True,
            "entry_count": 0,
            "data_used": 0,
            "target_bytes": 0,
            "plan_sha256": header["plan_sha256"],
            "prefix_sha256": hashlib.sha256().hexdigest(),
            "actions": {},
            "entries": [],
            "complete_plan_verified": False,
            "semantic_seals_valid": True,
            "evidence_generation": None,
            "recovery_rederivation_supported": True,
        }
    if state == "PREPARING":
        raise WalFixtureError("PREPARING WAL has a nonzero durable prefix")
    if entry_count <= 0 or data_used <= 0 or target_bytes <= 0:
        raise WalFixtureError("non-EMPTY WAL durable-prefix counters disagree")

    sector_size = int(details["sector_size"])
    journal_base = int(details["offset"])
    committed_end = ENTRY_START + data_used
    if data_used % sector_size or committed_end > JOURNAL_SIZE:
        raise WalFixtureError("WAL committed entry-area length is not sector bounded")

    plan = hashlib.sha256()
    cursor = ENTRY_START
    total_target_bytes = 0
    entries: list[dict[str, object]] = []
    entry_evidence: list[dict[str, object]] = []
    action_counts: dict[str, int] = {}
    with image.open("rb", buffering=0) as handle:
        for expected_ordinal in range(entry_count):
            if cursor + ENTRY_SIZE > committed_end:
                raise WalFixtureError("WAL descriptor extends beyond committed data_used")
            descriptor = read_exact(
                handle,
                ENTRY_SIZE,
                journal_base + cursor,
                f"WAL descriptor {expected_ordinal}",
            )
            if descriptor[:8] != ENTRY_MAGIC:
                raise WalFixtureError(f"WAL descriptor {expected_ordinal} magic differs")
            if u32(descriptor, 0x08) != 1 or u32(descriptor, 0x0C) != ENTRY_SIZE:
                raise WalFixtureError(
                    f"WAL descriptor {expected_ordinal} version/size differs"
                )
            ordinal = u64(descriptor, 0x10)
            if ordinal != expected_ordinal:
                raise WalFixtureError(
                    f"WAL descriptor ordinal {ordinal} is not contiguous at {expected_ordinal}"
                )
            target_offset = u64(descriptor, 0x18)
            target_length = u64(descriptor, 0x20)
            payload_offset = u64(descriptor, 0x28)
            padded_length = u64(descriptor, 0x30)
            action_value = u32(descriptor, 0x38)
            flags = u32(descriptor, 0x3C)
            if action_value not in ACTION_KINDS:
                raise WalFixtureError(
                    f"WAL descriptor {expected_ordinal} action kind is unknown"
                )
            action = ACTION_KINDS[action_value]
            if flags:
                raise WalFixtureError(f"WAL descriptor {expected_ordinal} flags are nonzero")
            if target_length <= 0 or target_offset + target_length > int(details["device_bytes"]):
                raise WalFixtureError(
                    f"WAL descriptor {expected_ordinal} target range is out of bounds"
                )
            if target_offset % sector_size or target_length % sector_size:
                raise WalFixtureError(
                    f"WAL descriptor {expected_ordinal} target range is not sector aligned"
                )
            expected_padded = (
                (target_length + sector_size - 1) // sector_size * sector_size
            )
            if (
                payload_offset != cursor + ENTRY_SIZE
                or padded_length != expected_padded
                or payload_offset + padded_length > committed_end
            ):
                raise WalFixtureError(
                    f"WAL descriptor {expected_ordinal} payload bounds/padding differ"
                )
            if any(descriptor[ENTRY_RESERVED_OFFSET:ENTRY_DIGEST_OFFSET]):
                raise WalFixtureError(
                    f"WAL descriptor {expected_ordinal} reserved bytes are nonzero"
                )
            expected_descriptor_hash = hashlib.sha256(
                descriptor[:ENTRY_DIGEST_OFFSET]
            ).digest()
            if descriptor[ENTRY_DIGEST_OFFSET:] != expected_descriptor_hash:
                raise WalFixtureError(
                    f"WAL descriptor {expected_ordinal} digest differs"
                )
            old_hash = descriptor[0x40:0x60]
            new_hash = descriptor[0x60:0x80]
            if not any(old_hash) or not any(new_hash) or old_hash == new_hash:
                raise WalFixtureError(
                    f"WAL descriptor {expected_ordinal} old/new hashes are invalid"
                )
            payload = read_exact(
                handle,
                padded_length,
                journal_base + payload_offset,
                f"WAL old payload {expected_ordinal}",
            )
            if any(payload[target_length:]):
                raise WalFixtureError(
                    f"WAL old payload {expected_ordinal} padding is nonzero"
                )
            if hashlib.sha256(payload[:target_length]).digest() != old_hash:
                raise WalFixtureError(
                    f"WAL old payload {expected_ordinal} hash differs"
                )
            semantic = validate_semantic_seal(
                descriptor,
                action_value,
                target_offset,
                target_length,
                payload[:target_length],
                expected_ordinal,
            )
            if action in ("volume-dirty-set", "volume-dirty-clear"):
                current_payload: bytes | None = read_exact(
                    handle,
                    target_length,
                    target_offset,
                    f"WAL current dirty-action target {expected_ordinal}",
                )
                old_payload: bytes | None = payload[:target_length]
            else:
                current_payload = None
                old_payload = None
            for exclusion in details["write_exclusion"]:  # type: ignore[union-attr]
                if overlaps(
                    target_offset,
                    target_length,
                    int(exclusion["offset"]),
                    int(exclusion["length"]),
                ):
                    raise WalFixtureError(
                        f"WAL descriptor {expected_ordinal} target intersects "
                        f"{exclusion['source']} exclusion"
                    )
            plan.update(descriptor[:ENTRY_DIGEST_OFFSET])
            total_target_bytes += target_length
            action_counts[action] = action_counts.get(action, 0) + 1
            entries.append(
                {
                    "ordinal": ordinal,
                    "action_id": action_value,
                    "action": action,
                    "target_offset": target_offset,
                    "target_length": target_length,
                    "payload_offset": payload_offset,
                    "padded_length": padded_length,
                    "old_sha256": old_hash.hex(),
                    "new_sha256": new_hash.hex(),
                    "semantic": semantic,
                }
            )
            entry_evidence.append(
                {
                    "old_payload": old_payload,
                    "current_payload": current_payload,
                    "new_hash": new_hash,
                }
            )
            cursor = payload_offset + padded_length

    if cursor != committed_end:
        raise WalFixtureError("WAL data_used contains unparsed trailing bytes")
    if total_target_bytes != target_bytes:
        raise WalFixtureError("WAL target-byte total differs from committed header")
    plan_hash = plan.hexdigest()
    complete_plan_verified = state == "COMMITTED"
    if complete_plan_verified and plan_hash != header["plan_sha256"]:
        raise WalFixtureError("WAL canonical descriptor plan hash differs")
    transaction_kind = header["transaction_kind"]
    evidence_generations = {
        int(entry["semantic"]["evidence_generation"])
        for entry in entries
        if isinstance(entry.get("semantic"), dict)
    }
    if len(evidence_generations) != 1:
        raise WalFixtureError("WAL semantic evidence generations differ within transaction")
    geometry = mirrored_mft_geometry(image, details)
    if transaction_kind == "DIRTY_CLEAR":
        if entry_count != 2 or action_counts != {"volume-dirty-clear": 2}:
            raise WalFixtureError(
                "DIRTY_CLEAR WAL is not exactly one ordered volume-dirty-clear pair"
            )
        validate_dirty_action_pair(
            image,
            entries,
            entry_evidence,
            geometry,
            "volume-dirty-clear",
            sector_size,
        )
    elif transaction_kind == "METADATA_REPAIR":
        if "volume-dirty-clear" in action_counts:
            raise WalFixtureError(
                "METADATA_REPAIR WAL contains forbidden volume-dirty-clear action"
            )
        dirty_set_count = action_counts.get("volume-dirty-set", 0)
        if dirty_set_count not in (0, 2):
            if dirty_set_count != 1 or state not in ("APPLYING", "ROLLBACK"):
                if dirty_set_count == 1:
                    raise WalFixtureError(
                        "METADATA_REPAIR WAL contains a singleton volume-dirty-set entry"
                    )
                raise WalFixtureError(
                    "METADATA_REPAIR WAL contains more than one semantic volume-dirty-set pair"
                )
            validate_dirty_action_primary_prefix(
                image,
                entries[0],
                entry_evidence[0],
                geometry,
                "volume-dirty-set",
                sector_size,
            )
        if dirty_set_count == 2:
            if [entry["action"] for entry in entries[:2]] != [
                "volume-dirty-set",
                "volume-dirty-set",
            ]:
                raise WalFixtureError(
                    "METADATA_REPAIR volume-dirty-set pair is not at ordinals zero and one"
                )
            validate_dirty_action_pair(
                image,
                entries[:2],
                entry_evidence[:2],
                geometry,
                "volume-dirty-set",
                sector_size,
            )
    else:
        raise WalFixtureError("non-EMPTY WAL has an invalid transaction kind")
    validate_general_mft_pairs(
        entries,
        geometry,
        allow_trailing_primary=state in ("APPLYING", "ROLLBACK"),
    )
    return {
        "valid": True,
        "entry_count": entry_count,
        "data_used": data_used,
        "target_bytes": total_target_bytes,
        "plan_sha256": header["plan_sha256"],
        "prefix_sha256": plan_hash,
        "complete_plan_verified": complete_plan_verified,
        "semantic_seals_valid": True,
        "evidence_generation": next(iter(evidence_generations)),
        "recovery_rederivation_supported": all(
            int(entry["action_id"]) in RECOVERY_REDERIVATION_ACTIONS
            for entry in entries
        ),
        "actions": dict(sorted(action_counts.items())),
        "entries": entries,
    }


def validate_adjacent_pair(
    first: tuple[int, dict[str, object], bytes],
    second: tuple[int, dict[str, object], bytes],
) -> None:
    older, newer = sorted(
        (first, second), key=lambda item: int(item[1]["generation"])
    )
    older_header, newer_header = older[1], newer[1]
    older_generation = int(older_header["generation"])
    newer_generation = int(newer_header["generation"])
    if older_generation == newer_generation:
        if older[2] != newer[2]:
            raise WalFixtureError("equal-generation WAL headers differ")
        return
    if newer_generation != older_generation + 1:
        raise WalFixtureError("WAL header generations are not adjacent")
    for field in (
        "serial",
        "journal_uuid",
        "max_target_bytes",
        "max_entry_count",
    ):
        if older_header[field] != newer_header[field]:
            raise WalFixtureError(f"adjacent WAL headers differ in {field}")

    older_state = str(older_header["state"])
    newer_state = str(newer_header["state"])
    transitions = {
        "EMPTY": {"EMPTY", "PREPARING"},
        "PREPARING": {"APPLYING", "ROLLBACK"},
        "APPLYING": {"APPLYING", "COMMITTED", "ROLLBACK"},
        "COMMITTED": {"EMPTY", "ROLLBACK"},
        "ROLLBACK": {"EMPTY"},
    }
    if newer_state not in transitions[older_state]:
        raise WalFixtureError(
            f"illegal adjacent WAL transition {older_state}->{newer_state}"
        )

    prefix_fields = ("entry_count", "data_used", "target_bytes")
    older_prefix = tuple(int(older_header[field]) for field in prefix_fields)
    newer_prefix = tuple(int(newer_header[field]) for field in prefix_fields)
    if older_state != "EMPTY" and newer_state != "EMPTY":
        for field in ("transaction_uuid", "transaction_kind", "plan_sha256"):
            if older_header[field] != newer_header[field]:
                raise WalFixtureError(
                    f"adjacent non-EMPTY WAL headers differ in {field}"
                )
    if newer_state == "APPLYING":
        if newer_prefix[0] != older_prefix[0] + 1:
            raise WalFixtureError(
                "adjacent APPLYING WAL header did not add exactly one entry"
            )
        if newer_prefix[1] <= older_prefix[1] or newer_prefix[2] <= older_prefix[2]:
            raise WalFixtureError("adjacent APPLYING WAL prefix did not advance")
    elif older_state != "EMPTY" and newer_state != "EMPTY":
        if newer_prefix != older_prefix:
            raise WalFixtureError(
                f"{older_state}->{newer_state} did not preserve the durable prefix"
            )
    elif newer_state == "PREPARING" and newer_prefix != (0, 0, 0):
        raise WalFixtureError("new PREPARING WAL has a nonzero durable prefix")


def inspection(image: Path, layout_path: Path) -> dict[str, object]:
    details = layout(layout_path)
    headers = read_headers(image, int(details["offset"]))
    slots: list[dict[str, object]] = []
    parsed: list[tuple[int, dict[str, object], bytes]] = []
    for slot, block in enumerate(headers):
        try:
            header = parse_header(block, int(details["sector_size"]))
            slots.append({"slot": slot, "valid": True, **header})
            parsed.append((slot, header, block))
        except (ValueError, WalFixtureError) as error:
            slots.append({"slot": slot, "valid": False, "error": str(error)})
    for slot, header, _ in parsed:
        try:
            entry_oracle = inspect_entries(image, details, header)
        except WalFixtureError as error:
            entry_oracle = {"valid": False, "error": str(error)}
        header["entry_oracle"] = entry_oracle
        slots[slot]["entry_oracle"] = entry_oracle
    selected_item: tuple[int, dict[str, object], bytes] | None
    if not parsed:
        verdict = "invalid"
        selected = None
        selected_item = None
    elif len(parsed) == 1:
        verdict = "degraded"
        selected = parsed[0][1]
        selected_item = parsed[0]
    else:
        first, second = parsed
        try:
            validate_adjacent_pair(first, second)
        except WalFixtureError as error:
            verdict = "ambiguous"
            selected = None
            selected_item = None
            pair_error = str(error)
        else:
            verdict = "healthy"
            selected_item = max(parsed, key=lambda item: int(item[1]["generation"]))
            selected = selected_item[1]
    if selected_item is not None:
        if selected["serial"] != f"0x{int(details['serial']):016x}":
            raise WalFixtureError("selected WAL serial differs from canonical layout")
        if selected["journal_uuid"] != details["journal_uuid"]:
            raise WalFixtureError("selected WAL UUID differs from canonical layout")
    result = {"verdict": verdict, "slots": slots, "selected": selected, "layout": details}
    if verdict == "ambiguous":
        result["pair_error"] = pair_error
    return result


def rewrite_digest(block: bytearray) -> None:
    block[DIGEST_OFFSET:] = hashlib.sha256(block[:DIGEST_OFFSET]).digest()


def mutate(image: Path, layout_path: Path, kind: str) -> dict[str, object]:
    details = layout(layout_path)
    base = int(details["offset"])
    first, second = read_headers(image, base)
    changed: list[int]
    if kind == "one-torn":
        first_block = bytearray(first)
        first_block[DIGEST_OFFSET] ^= 0x01
        output = (bytes(first_block), second)
        changed = [0]
    elif kind == "both-torn":
        first_block = bytearray(first)
        second_block = bytearray(second)
        first_block[DIGEST_OFFSET] ^= 0x01
        second_block[DIGEST_OFFSET] ^= 0x01
        output = (bytes(first_block), bytes(second_block))
        changed = [0, 1]
    elif kind == "equal-generation-divergent":
        first_block = bytearray(second)
        replacement = uuid.uuid4()
        while str(replacement) == details["journal_uuid"]:
            replacement = uuid.uuid4()
        first_block[0x30:0x40] = replacement.bytes
        rewrite_digest(first_block)
        output = (bytes(first_block), second)
        changed = [0]
    elif kind == "preparing-zero":
        first_header = parse_header(first, int(details["sector_size"]))
        second_header = parse_header(second, int(details["sector_size"]))
        if first_header["state"] != "EMPTY" or second_header["state"] != "EMPTY":
            raise WalFixtureError("preparing-zero requires two EMPTY headers")
        older_slot = 0 if int(first_header["generation"]) < int(second_header["generation"]) else 1
        newer_slot = 1 - older_slot
        older = (first, second)[older_slot]
        newer = bytearray((first, second)[newer_slot])
        transaction = uuid.uuid5(
            uuid.UUID(str(details["journal_uuid"])),
            "roothealth-runtime-preparing-zero",
        )
        struct.pack_into("<I", newer, 0x1C, 1)
        newer[0x40:0x50] = transaction.bytes
        newer[0x78:0x98] = hashlib.sha256(
            b"roothealth-runtime-preparing-zero-plan-v1"
        ).digest()
        struct.pack_into("<I", newer, 0xA0, 1)
        rewrite_digest(newer)
        output_list = [first, second]
        output_list[older_slot] = older
        output_list[newer_slot] = bytes(newer)
        output = (output_list[0], output_list[1])
        changed = [newer_slot]
    else:
        raise WalFixtureError(f"unknown WAL mutation {kind}")
    with image.open("r+b", buffering=0) as handle:
        for slot in changed:
            payload = output[slot]
            if os.pwrite(handle.fileno(), payload, base + slot * BLOCK_SIZE) != BLOCK_SIZE:
                raise WalFixtureError("short WAL mutation write")
        os.fsync(handle.fileno())
    result = inspection(image, layout_path)
    result["mutation"] = kind
    return result


def self_test() -> None:
    serial = 0x0123456789ABCDEF
    journal_id = uuid.UUID("11111111-2222-4333-8444-555555555555")
    transaction_id = uuid.UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
    sector_size = 512
    cluster_size = 4096
    journal_base = 16 * 1024 * 1024
    target_offset = 4 * 1024 * 1024
    mft_base = 1 * 1024 * 1024
    mftmirr_base = 2 * 1024 * 1024
    record_size = sector_size
    volume_primary = mft_base + VOLUME_RECORD * record_size
    volume_mirror = mftmirr_base + VOLUME_RECORD * record_size
    old_bytes = (b"roothealth-old-byte-oracle-" * 32)[:sector_size]
    new_buffer = bytearray(old_bytes)
    new_buffer[7] ^= 1
    new_bytes = bytes(new_buffer)
    if len(old_bytes) != len(new_bytes):
        raise WalFixtureError("WAL self-test payloads differ in length")

    def descriptor(
        action: int,
        offset: int = target_offset,
        ordinal: int = 0,
        *,
        old: bytes = old_bytes,
        new: bytes = new_bytes,
    ) -> bytes:
        if len(old) != sector_size or len(new) != len(old) or old == new:
            raise WalFixtureError("WAL self-test descriptor payloads are invalid")
        payload_offset = (
            ENTRY_START + ordinal * (ENTRY_SIZE + sector_size) + ENTRY_SIZE
        )
        padded_length = sector_size
        block = bytearray(ENTRY_SIZE)
        block[:8] = ENTRY_MAGIC
        struct.pack_into("<IIQQQQQII", block, 0x08, 1, ENTRY_SIZE, ordinal, offset,
                         len(old), payload_offset, padded_length, action, 0)
        block[0x40:0x60] = hashlib.sha256(old).digest()
        block[0x60:0x80] = hashlib.sha256(new).digest()

        name_hash = hashlib.sha256(b"").digest()
        target_object = 5
        owner_record = 8
        owner_sequence = 1
        attribute_instance = 1
        attribute_type = 0x80
        name_length = 0
        semantic_flags = TARGET_NONRESIDENT
        lowest_vcn = 0
        logical_vcn = offset // cluster_size
        logical_offset = 0
        semantic_offset = offset
        semantic_length = len(old)
        lcn = offset // cluster_size
        if action == 23:
            differences = [
                index for index, (before, after) in enumerate(zip(old, new))
                if before != after
            ]
            if len(differences) != 1:
                raise WalFixtureError(
                    "WAL bitmap self-test operation is not one semantic byte"
                )
            relative = differences[0]
            owner_record = 6
            semantic_offset = offset + relative
            semantic_length = 1
            logical_offset = relative
            logical_vcn = offset // cluster_size
            name_hash = hashlib.sha256(b"").digest()
        elif action in (24, 25):
            _, relative = volume_information_flags(old, sector_size)
            target_object = 4 if offset == volume_mirror else 3
            owner_record = VOLUME_RECORD
            owner_sequence = 1
            attribute_instance = 0
            attribute_type = AT_VOLUME_INFORMATION
            semantic_flags = (
                TARGET_MIRROR if target_object == 4 else TARGET_PRIMARY
            ) | TARGET_RESIDENT | (
                TARGET_SET_ONLY if action == 24 else TARGET_CLEAR_ONLY
            )
            lowest_vcn = logical_vcn = lcn = -1
            logical_offset = 10
            semantic_offset = offset + relative
            semantic_length = 2
            name_hash = hashlib.sha256(b"").digest()
        elif action == 7:
            if mftmirr_base <= offset < mftmirr_base + 4 * record_size:
                target_object = 4
                owner_record = (offset - mftmirr_base) // record_size
                semantic_flags = TARGET_MIRROR | TARGET_RESIDENT
            else:
                target_object = 3
                owner_record = (offset - mft_base) // record_size
                semantic_flags = TARGET_PRIMARY | TARGET_RESIDENT
            attribute_instance = 0
            attribute_type = 0
            name_hash = b"\0" * 32
            lowest_vcn = logical_vcn = lcn = -1
            semantic_offset = offset
            semantic_length = len(old)
            logical_offset = 0
        block[0x080:0x180] = b"\0" * 0x100
        struct.pack_into("<IIQHHIHHI", block, 0x080,
                         SEMANTIC_SEAL_VERSION, target_object, owner_record,
                         owner_sequence, attribute_instance, attribute_type,
                         name_length, semantic_flags, SEMANTIC_EVIDENCE_VERSION)
        block[0x0A0:0x0C0] = name_hash
        struct.pack_into("<qqQQQQqQ", block, 0x0C0,
                         lowest_vcn, logical_vcn, logical_offset,
                         semantic_length, semantic_offset, semantic_length,
                         lcn, 0x1001)
        semantic_relative = semantic_offset - offset
        semantic_old = old[
            semantic_relative : semantic_relative + semantic_length
        ]
        semantic_new = new[
            semantic_relative : semantic_relative + semantic_length
        ]
        block[0x100:0x120] = hashlib.sha256(b"selftest-evidence-v1").digest()
        block[0x120:0x140] = hashlib.sha256(b"selftest-staged-view-v1").digest()
        block[0x140:0x160] = hashlib.sha256(semantic_old).digest()
        block[0x160:0x180] = hashlib.sha256(semantic_new).digest()
        block[ENTRY_DIGEST_OFFSET:] = hashlib.sha256(
            block[:ENTRY_DIGEST_OFFSET]
        ).digest()
        return bytes(block)

    def volume_record(flags: int, marker: int = 0) -> bytes:
        block = bytearray(record_size)
        block[:4] = b"FILE"
        usa_offset = 0x30
        usa_count = record_size // sector_size + 1
        first_attribute = 0x38
        attribute_length = 0x28
        used = first_attribute + attribute_length + 8
        struct.pack_into("<HH", block, 4, usa_offset, usa_count)
        struct.pack_into("<HH", block, 16, 1, 1)
        struct.pack_into("<H", block, 20, first_attribute)
        struct.pack_into("<H", block, 22, 1)
        struct.pack_into("<II", block, 24, used, record_size)
        struct.pack_into("<I", block, 44, VOLUME_RECORD)
        struct.pack_into(
            "<IIBBHHH",
            block,
            first_attribute,
            AT_VOLUME_INFORMATION,
            attribute_length,
            0,
            0,
            0,
            0,
            0,
        )
        struct.pack_into("<IH", block, first_attribute + 16, 12, 24)
        value = first_attribute + 24
        block[value] = marker
        struct.pack_into("<H", block, value + 10, flags)
        struct.pack_into("<I", block, first_attribute + attribute_length, AT_END)
        update_sequence = b"\x31\xa7"
        block[usa_offset : usa_offset + 2] = update_sequence
        block[usa_offset + 2 : usa_offset + 4] = block[-2:]
        block[-2:] = update_sequence
        return bytes(block)

    def header(
        *, generation: int, state: int, kind: int,
        plan_entries: list[bytes] | None,
        prefix_entries: list[bytes] | None,
        transaction: uuid.UUID = transaction_id,
    ) -> bytes:
        block = bytearray(BLOCK_SIZE)
        block[:16] = MAGIC
        struct.pack_into("<III", block, 0x10, 1, BLOCK_SIZE, sector_size)
        struct.pack_into("<IQQ", block, 0x1C, state, generation, serial)
        block[0x30:0x40] = journal_id.bytes
        if state:
            block[0x40:0x50] = transaction.bytes
        struct.pack_into("<QQ", block, 0x50, JOURNAL_SIZE, ENTRY_START)
        if prefix_entries:
            data_used = len(prefix_entries) * (ENTRY_SIZE + sector_size)
            struct.pack_into(
                "<QQQ", block, 0x60, data_used, len(prefix_entries),
                len(prefix_entries) * len(old_bytes)
            )
        if plan_entries:
            plan = hashlib.sha256()
            for entry in plan_entries:
                plan.update(entry[:ENTRY_DIGEST_OFFSET])
            block[0x78:0x98] = plan.digest()
        struct.pack_into("<QII", block, 0x98, MAX_TARGET_BYTES, kind, MAX_ENTRY_COUNT)
        block[DIGEST_OFFSET:] = hashlib.sha256(block[:DIGEST_OFFSET]).digest()
        return bytes(block)

    def expect_failure(image: Path, report: Path, phrase: str) -> None:
        try:
            result = inspection(image, report)
        except WalFixtureError as error:
            observed = str(error)
        else:
            observed_parts = []
            pair_error = result.get("pair_error")
            if isinstance(pair_error, str):
                observed_parts.append(pair_error)
            for slot in result.get("slots", []):
                if not isinstance(slot, dict):
                    continue
                entry_oracle = slot.get("entry_oracle")
                if isinstance(entry_oracle, dict) and entry_oracle.get("valid") is False:
                    error = entry_oracle.get("error")
                    if isinstance(error, str):
                        observed_parts.append(error)
            observed = "; ".join(observed_parts)
        if phrase not in observed:
            raise WalFixtureError(
                f"WAL self-test expected {phrase!r}, got {observed!r}"
            )

    with tempfile.TemporaryDirectory(prefix="roothealth-wal-oracle-") as directory:
        root = Path(directory)
        image = root / "volume.ntfs"
        report = root / "layout.json"
        device_bytes = 160 * 1024 * 1024
        with image.open("wb") as handle:
            handle.truncate(device_bytes)
        boot = bytearray(sector_size)
        boot[3:11] = NTFS_OEM_ID
        struct.pack_into("<H", boot, 11, sector_size)
        boot[13] = cluster_size // sector_size
        struct.pack_into("<Q", boot, 40, device_bytes // sector_size)
        struct.pack_into("<Q", boot, 48, mft_base // cluster_size)
        struct.pack_into("<Q", boot, 56, mftmirr_base // cluster_size)
        struct.pack_into("<b", boot, 64, -9)
        struct.pack_into("<Q", boot, 72, serial)
        boot[510:512] = b"\x55\xaa"
        with image.open("r+b", buffering=0) as handle:
            os.pwrite(handle.fileno(), boot, 0)
            os.pwrite(handle.fileno(), boot, device_bytes - sector_size)
        report.write_text(
            json.dumps(
                {
                    "device": {
                        "bytes": device_bytes,
                        "sector_size": sector_size,
                        "cluster_size": cluster_size,
                        "serial": f"{serial:016X}",
                    },
                    "journal": {
                        "allocated_bytes": JOURNAL_SIZE,
                        "run_count": 1,
                        "runs": [
                            {
                                "vcn": 0,
                                "lcn": journal_base // cluster_size,
                                "clusters": JOURNAL_SIZE // cluster_size,
                            }
                        ],
                        "header": {"journal_uuid": str(journal_id)},
                        "write_exclusion": {
                            "data_stream": [
                                {
                                    "stream_offset": 0,
                                    "device_offset": journal_base,
                                    "bytes": JOURNAL_SIZE,
                                }
                            ],
                            "base_file_record": [
                                {
                                    "stream_offset": 0,
                                    "device_offset": 8 * 1024 * 1024,
                                    "bytes": 1024,
                                }
                            ],
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        def publish(
            entry: bytes | list[bytes],
            *,
            kind: int = 1,
            old_payloads: list[bytes] | None = None,
            current_payloads: list[bytes] | None = None,
            committed: bool = False,
        ) -> None:
            entries = [entry] if isinstance(entry, bytes) else entry
            if old_payloads is None:
                old_payloads = [old_bytes] * len(entries)
            if current_payloads is None:
                current_payloads = list(old_payloads)
            if len(old_payloads) != len(entries) or len(current_payloads) != len(entries):
                raise WalFixtureError("WAL self-test publish payload count differs")
            with image.open("r+b", buffering=0) as handle:
                os.pwrite(
                    handle.fileno(),
                    header(
                        generation=1, state=2 if committed else 1, kind=kind,
                        plan_entries=entries,
                        prefix_entries=entries if committed else None,
                    ),
                    journal_base,
                )
                os.pwrite(
                    handle.fileno(),
                    header(
                        generation=2, state=3 if committed else 2, kind=kind,
                        plan_entries=entries, prefix_entries=entries,
                    ),
                    journal_base + BLOCK_SIZE,
                )
                for ordinal, (item, old_payload, current_payload) in enumerate(
                    zip(entries, old_payloads, current_payloads)
                ):
                    if (
                        len(old_payload) != u64(item, 0x30)
                        or len(current_payload) < u64(item, 0x20)
                    ):
                        raise WalFixtureError("WAL self-test publish payload size differs")
                    cursor = journal_base + ENTRY_START + ordinal * (ENTRY_SIZE + sector_size)
                    os.pwrite(handle.fileno(), item, cursor)
                    os.pwrite(handle.fileno(), old_payload, cursor + ENTRY_SIZE)
                    os.pwrite(handle.fileno(), current_payload, u64(item, 0x18))

        valid_entry = descriptor(23)

        # A planned transaction is durable before its first descriptor.  Both
        # PREPARING and a ROLLBACK derived directly from that state therefore
        # have a valid zero-entry prefix whose complete plan hash cannot yet be
        # recomputed from disk.
        with image.open("r+b", buffering=0) as handle:
            os.pwrite(
                handle.fileno(),
                header(
                    generation=1, state=0, kind=0,
                    plan_entries=None, prefix_entries=None,
                ),
                journal_base,
            )
            os.pwrite(
                handle.fileno(),
                header(
                    generation=2, state=1, kind=1,
                    plan_entries=[valid_entry], prefix_entries=None,
                ),
                journal_base + BLOCK_SIZE,
            )
        preparing = inspection(image, report)["selected"]
        if (
            not isinstance(preparing, dict)
            or preparing.get("state") != "PREPARING"
            or preparing.get("entry_oracle", {}).get("entry_count") != 0
            or preparing.get("entry_oracle", {}).get("complete_plan_verified") is not False
        ):
            raise WalFixtureError(
                "WAL self-test did not accept a zero-entry PREPARING prefix"
            )
        with image.open("r+b", buffering=0) as handle:
            os.pwrite(
                handle.fileno(),
                header(
                    generation=2, state=1, kind=1,
                    plan_entries=[valid_entry], prefix_entries=None,
                ),
                journal_base,
            )
            os.pwrite(
                handle.fileno(),
                header(
                    generation=3, state=4, kind=1,
                    plan_entries=[valid_entry], prefix_entries=None,
                ),
                journal_base + BLOCK_SIZE,
            )
        rollback = inspection(image, report)["selected"]
        if (
            not isinstance(rollback, dict)
            or rollback.get("state") != "ROLLBACK"
            or rollback.get("entry_oracle", {}).get("entry_count") != 0
        ):
            raise WalFixtureError(
                "WAL self-test did not accept a zero-entry ROLLBACK prefix"
            )

        def expect_ambiguous_pair(
            older_header: bytes, newer_header: bytes, phrase: str
        ) -> None:
            with image.open("r+b", buffering=0) as handle:
                os.pwrite(handle.fileno(), older_header, journal_base)
                os.pwrite(handle.fileno(), newer_header, journal_base + BLOCK_SIZE)
                os.pwrite(handle.fileno(), valid_entry, journal_base + ENTRY_START)
                os.pwrite(
                    handle.fileno(), old_bytes,
                    journal_base + ENTRY_START + ENTRY_SIZE,
                )
            result = inspection(image, report)
            if result.get("verdict") != "ambiguous" or phrase not in str(
                result.get("pair_error")
            ):
                raise WalFixtureError(
                    f"WAL self-test expected ambiguous pair {phrase!r}, got {result!r}"
                )

        expect_ambiguous_pair(
            header(
                generation=1, state=1, kind=1,
                plan_entries=[valid_entry], prefix_entries=None,
            ),
            header(
                generation=3, state=2, kind=1,
                plan_entries=[valid_entry], prefix_entries=[valid_entry],
            ),
            "not adjacent",
        )
        expect_ambiguous_pair(
            header(
                generation=1, state=1, kind=1,
                plan_entries=[valid_entry], prefix_entries=None,
            ),
            header(
                generation=2, state=2, kind=1,
                plan_entries=[valid_entry], prefix_entries=[valid_entry],
                transaction=uuid.UUID("bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"),
            ),
            "transaction_uuid",
        )
        expect_ambiguous_pair(
            header(
                generation=1, state=2, kind=1,
                plan_entries=[valid_entry], prefix_entries=[valid_entry],
            ),
            header(
                generation=2, state=2, kind=1,
                plan_entries=[valid_entry], prefix_entries=[valid_entry],
            ),
            "exactly one entry",
        )

        zero_transaction = bytearray(
            header(
                generation=1, state=1, kind=1,
                plan_entries=[valid_entry], prefix_entries=None,
            )
        )
        zero_transaction[0x40:0x50] = b"\0" * 16
        rewrite_digest(zero_transaction)
        try:
            parse_header(bytes(zero_transaction), sector_size)
        except WalFixtureError as error:
            if "transaction UUID" not in str(error):
                raise
        else:
            raise WalFixtureError(
                "WAL self-test accepted a non-EMPTY zero transaction UUID"
            )

        committed_descriptor = bytearray(valid_entry)
        committed_descriptor[0x60] ^= 0x5A
        committed_descriptor[ENTRY_DIGEST_OFFSET:] = hashlib.sha256(
            committed_descriptor[:ENTRY_DIGEST_OFFSET]
        ).digest()
        with image.open("r+b", buffering=0) as handle:
            os.pwrite(
                handle.fileno(),
                header(
                    generation=1, state=2, kind=1,
                    plan_entries=[valid_entry], prefix_entries=[valid_entry],
                ),
                journal_base,
            )
            os.pwrite(
                handle.fileno(),
                header(
                    generation=2, state=3, kind=1,
                    plan_entries=[valid_entry], prefix_entries=[valid_entry],
                ),
                journal_base + BLOCK_SIZE,
            )
            os.pwrite(
                handle.fileno(), bytes(committed_descriptor),
                journal_base + ENTRY_START,
            )
            os.pwrite(
                handle.fileno(), old_bytes,
                journal_base + ENTRY_START + ENTRY_SIZE,
            )
        expect_failure(image, report, "canonical descriptor plan hash differs")

        publish(valid_entry)
        selected = inspection(image, report)["selected"]
        if (
            not isinstance(selected, dict)
            or selected.get("state") != "APPLYING"
            or selected.get("entry_oracle", {}).get("actions")
            != {"bitmap-cluster": 1}
            or selected.get("entry_oracle", {}).get("semantic_seals_valid") is not True
            or selected.get("entry_oracle", {}).get("recovery_rederivation_supported") is not True
        ):
            raise WalFixtureError("WAL self-test did not validate its committed entry")

        invalid_seal = bytearray(valid_entry)
        struct.pack_into("<I", invalid_seal, 0x080, 2)
        invalid_seal[ENTRY_DIGEST_OFFSET:] = hashlib.sha256(
            invalid_seal[:ENTRY_DIGEST_OFFSET]
        ).digest()
        publish(bytes(invalid_seal))
        expect_failure(image, report, "semantic target header differs")

        invalid_reserved = bytearray(valid_entry)
        invalid_reserved[ENTRY_RESERVED_OFFSET] = 1
        invalid_reserved[ENTRY_DIGEST_OFFSET:] = hashlib.sha256(
            invalid_reserved[:ENTRY_DIGEST_OFFSET]
        ).digest()
        publish(bytes(invalid_reserved))
        expect_failure(image, report, "reserved bytes are nonzero")

        invalid_generation = bytearray(valid_entry)
        struct.pack_into("<Q", invalid_generation, 0x0F8, 0)
        invalid_generation[ENTRY_DIGEST_OFFSET:] = hashlib.sha256(
            invalid_generation[:ENTRY_DIGEST_OFFSET]
        ).digest()
        publish(bytes(invalid_generation))
        expect_failure(image, report, "semantic evidence is incomplete")

        invalid_before = bytearray(valid_entry)
        invalid_before[0x140] ^= 0x80
        invalid_before[ENTRY_DIGEST_OFFSET:] = hashlib.sha256(
            invalid_before[:ENTRY_DIGEST_OFFSET]
        ).digest()
        publish(bytes(invalid_before))
        expect_failure(image, report, "semantic before-image hash differs")

        unsupported_entry = descriptor(14, target_offset, 0)
        publish(unsupported_entry, kind=1, committed=True)
        unsupported_selected = inspection(image, report)["selected"]
        if (
            not isinstance(unsupported_selected, dict)
            or unsupported_selected.get("entry_oracle", {}).get(
                "recovery_rederivation_supported"
            ) is not False
        ):
            raise WalFixtureError(
                "WAL self-test did not fail closed on an unqualified action profile"
            )

        unaligned_offset_entry = descriptor(23, target_offset + 1)
        publish(unaligned_offset_entry)
        expect_failure(image, report, "not sector aligned")

        unaligned_length_entry = bytearray(valid_entry)
        struct.pack_into("<Q", unaligned_length_entry, 0x20, sector_size - 1)
        unaligned_length_entry[ENTRY_DIGEST_OFFSET:] = hashlib.sha256(
            unaligned_length_entry[:ENTRY_DIGEST_OFFSET]
        ).digest()
        publish(bytes(unaligned_length_entry))
        expect_failure(image, report, "not sector aligned")

        excluded_entry = descriptor(23, journal_base)
        publish(excluded_entry)
        expect_failure(image, report, "data_stream exclusion")

        dirty_clear_old = volume_record(1)
        dirty_clear_new = volume_record(0)
        dirty_set_old = volume_record(0)
        dirty_set_new = volume_record(1)

        dirty_clear_pair = [
            descriptor(
                25,
                volume_primary,
                0,
                old=dirty_clear_old,
                new=dirty_clear_new,
            ),
            descriptor(
                25,
                volume_mirror,
                1,
                old=dirty_clear_old,
                new=dirty_clear_new,
            ),
        ]
        mismatched_evidence_generation = bytearray(dirty_clear_pair[1])
        struct.pack_into("<Q", mismatched_evidence_generation, 0x0F8, 0x1002)
        mismatched_evidence_generation[ENTRY_DIGEST_OFFSET:] = hashlib.sha256(
            mismatched_evidence_generation[:ENTRY_DIGEST_OFFSET]
        ).digest()
        publish(
            [dirty_clear_pair[0], bytes(mismatched_evidence_generation)],
            kind=2,
            old_payloads=[dirty_clear_old, dirty_clear_old],
        )
        expect_failure(image, report, "evidence generations differ")
        publish(
            dirty_clear_pair,
            kind=1,
            old_payloads=[dirty_clear_old, dirty_clear_old],
        )
        expect_failure(image, report, "forbidden volume-dirty-clear")
        publish(
            dirty_clear_pair,
            kind=2,
            old_payloads=[dirty_clear_old, dirty_clear_old],
            current_payloads=[dirty_clear_new, dirty_clear_new],
            committed=True,
        )
        dirty_selected = inspection(image, report)["selected"]
        if (
            not isinstance(dirty_selected, dict)
            or dirty_selected.get("entry_oracle", {}).get("actions")
            != {"volume-dirty-clear": 2}
        ):
            raise WalFixtureError("WAL self-test did not validate DIRTY_CLEAR pair")

        dirty_clear_singleton = descriptor(
            25,
            volume_primary,
            0,
            old=dirty_clear_old,
            new=dirty_clear_new,
        )
        publish(
            dirty_clear_singleton,
            kind=2,
            old_payloads=[dirty_clear_old],
        )
        expect_failure(image, report, "exactly one ordered volume-dirty-clear pair")

        reversed_dirty_clear = [
            descriptor(
                25,
                volume_mirror,
                0,
                old=dirty_clear_old,
                new=dirty_clear_new,
            ),
            descriptor(
                25,
                volume_primary,
                1,
                old=dirty_clear_old,
                new=dirty_clear_new,
            ),
        ]
        publish(
            reversed_dirty_clear,
            kind=2,
            old_payloads=[dirty_clear_old, dirty_clear_old],
        )
        expect_failure(image, report, "not ordered primary then mirror")

        mismatched_dirty_clear = [
            dirty_clear_pair[0],
            descriptor(
                25,
                mftmirr_base + 2 * record_size,
                1,
                old=dirty_clear_old,
                new=dirty_clear_new,
            ),
        ]
        publish(
            mismatched_dirty_clear,
            kind=2,
            old_payloads=[dirty_clear_old, dirty_clear_old],
        )
        expect_failure(image, report, "physical entries do not match")

        mismatched_dirty_clear_transition = [
            dirty_clear_pair[0],
            descriptor(
                25,
                volume_mirror,
                1,
                old=volume_record(1, marker=1),
                new=volume_record(0, marker=1),
            ),
        ]
        publish(
            mismatched_dirty_clear_transition,
            kind=2,
            old_payloads=[dirty_clear_old, volume_record(1, marker=1)],
        )
        expect_failure(image, report, "mismatched physical transitions")

        wrong_clear_new = volume_record(3)
        wrong_semantic_dirty_clear = [
            descriptor(
                25,
                volume_primary,
                0,
                old=dirty_clear_old,
                new=wrong_clear_new,
            ),
            descriptor(
                25,
                volume_mirror,
                1,
                old=dirty_clear_old,
                new=wrong_clear_new,
            ),
        ]
        publish(
            wrong_semantic_dirty_clear,
            kind=2,
            old_payloads=[dirty_clear_old, dirty_clear_old],
            current_payloads=[wrong_clear_new, wrong_clear_new],
        )
        expect_failure(image, report, "semantic flag delta differs")

        dirty_set_pair = [
            descriptor(
                24,
                volume_primary,
                0,
                old=dirty_set_old,
                new=dirty_set_new,
            ),
            descriptor(
                24,
                volume_mirror,
                1,
                old=dirty_set_old,
                new=dirty_set_new,
            ),
        ]
        publish(
            dirty_set_pair,
            kind=1,
            old_payloads=[dirty_set_old, dirty_set_old],
            current_payloads=[dirty_set_new, dirty_set_new],
            committed=True,
        )
        dirty_set_selected = inspection(image, report)["selected"]
        if (
            not isinstance(dirty_set_selected, dict)
            or dirty_set_selected.get("entry_oracle", {}).get("actions")
            != {"volume-dirty-set": 2}
        ):
            raise WalFixtureError(
                "WAL self-test did not validate ordinal-zero dirty-set pair"
            )

        dirty_set_singleton = descriptor(
            24,
            volume_primary,
            0,
            old=dirty_set_old,
            new=dirty_set_new,
        )
        publish(
            dirty_set_singleton,
            kind=1,
            old_payloads=[dirty_set_old],
        )
        dirty_set_prefix = inspection(image, report)["selected"]
        if (
            not isinstance(dirty_set_prefix, dict)
            or dirty_set_prefix.get("state") != "APPLYING"
            or dirty_set_prefix.get("entry_oracle", {}).get("actions")
            != {"volume-dirty-set": 1}
            or dirty_set_prefix.get("entry_oracle", {}).get(
                "complete_plan_verified"
            )
            is not False
        ):
            raise WalFixtureError(
                "WAL self-test did not accept the interrupted dirty-set primary prefix"
            )
        publish(
            dirty_set_singleton,
            kind=1,
            old_payloads=[dirty_set_old],
            committed=True,
        )
        expect_failure(image, report, "singleton volume-dirty-set")

        reversed_dirty_set = [
            descriptor(
                24,
                volume_mirror,
                0,
                old=dirty_set_old,
                new=dirty_set_new,
            ),
            descriptor(
                24,
                volume_primary,
                1,
                old=dirty_set_old,
                new=dirty_set_new,
            ),
        ]
        publish(
            reversed_dirty_set,
            kind=1,
            old_payloads=[dirty_set_old, dirty_set_old],
        )
        expect_failure(image, report, "not ordered primary then mirror")

        mismatched_dirty_set = [
            dirty_set_pair[0],
            descriptor(
                24,
                mftmirr_base + 2 * record_size,
                1,
                old=dirty_set_old,
                new=dirty_set_new,
            ),
        ]
        publish(
            mismatched_dirty_set,
            kind=1,
            old_payloads=[dirty_set_old, dirty_set_old],
        )
        expect_failure(image, report, "physical entries do not match")

        mismatched_dirty_set_transition = [
            dirty_set_pair[0],
            descriptor(
                24,
                volume_mirror,
                1,
                old=volume_record(0, marker=1),
                new=volume_record(1, marker=1),
            ),
        ]
        publish(
            mismatched_dirty_set_transition,
            kind=1,
            old_payloads=[dirty_set_old, volume_record(0, marker=1)],
        )
        expect_failure(image, report, "mismatched physical transitions")

        wrong_set_new = volume_record(2)
        wrong_semantic_dirty_set = [
            descriptor(
                24,
                volume_primary,
                0,
                old=dirty_set_old,
                new=wrong_set_new,
            ),
            descriptor(
                24,
                volume_mirror,
                1,
                old=dirty_set_old,
                new=wrong_set_new,
            ),
        ]
        publish(
            wrong_semantic_dirty_set,
            kind=1,
            old_payloads=[dirty_set_old, dirty_set_old],
            current_payloads=[wrong_set_new, wrong_set_new],
        )
        expect_failure(image, report, "semantic flag delta differs")

        publish(
            dirty_set_pair,
            kind=2,
            old_payloads=[dirty_set_old, dirty_set_old],
        )
        expect_failure(image, report, "ordered volume-dirty-clear pair")

        misplaced_dirty_set = [
            descriptor(23, target_offset, 0),
            descriptor(
                24,
                volume_primary,
                1,
                old=dirty_set_old,
                new=dirty_set_new,
            ),
            descriptor(
                24,
                volume_mirror,
                2,
                old=dirty_set_old,
                new=dirty_set_new,
            ),
        ]
        publish(
            misplaced_dirty_set,
            kind=1,
            old_payloads=[old_bytes, dirty_set_old, dirty_set_old],
        )
        expect_failure(image, report, "not at ordinals zero and one")

        duplicate_dirty_set = [
            descriptor(
                24,
                volume_primary,
                0,
                old=dirty_set_old,
                new=dirty_set_new,
            ),
            descriptor(
                24,
                volume_mirror,
                1,
                old=dirty_set_old,
                new=dirty_set_new,
            ),
            descriptor(
                24,
                volume_primary,
                2,
                old=dirty_set_old,
                new=dirty_set_new,
            ),
            descriptor(
                24,
                volume_mirror,
                3,
                old=dirty_set_old,
                new=dirty_set_new,
            ),
        ]
        publish(
            duplicate_dirty_set,
            kind=1,
            old_payloads=[dirty_set_old] * 4,
        )
        expect_failure(image, report, "more than one semantic volume-dirty-set pair")

        general_pair = [
            descriptor(7, mft_base + record_size, 0),
            descriptor(7, mftmirr_base + record_size, 1),
        ]
        publish(general_pair, kind=1, committed=True)
        general_selected = inspection(image, report)["selected"]
        if (
            not isinstance(general_selected, dict)
            or general_selected.get("entry_oracle", {}).get("actions")
            != {"mft-record": 2}
        ):
            raise WalFixtureError("WAL self-test did not validate a general MFT pair")

        publish(general_pair[0], kind=1)
        general_prefix = inspection(image, report)["selected"]
        if (
            not isinstance(general_prefix, dict)
            or general_prefix.get("state") != "APPLYING"
            or general_prefix.get("entry_oracle", {}).get("actions")
            != {"mft-record": 1}
        ):
            raise WalFixtureError(
                "WAL self-test did not accept an interrupted primary MFT prefix"
            )
        publish(general_pair[0], kind=1, committed=True)
        expect_failure(image, report, "lacks an adjacent mirror pair")

        reversed_general_pair = [
            descriptor(7, mftmirr_base + record_size, 0),
            descriptor(7, mft_base + record_size, 1),
        ]
        publish(reversed_general_pair, kind=1)
        expect_failure(image, report, "mirror entry precedes")

        mismatched_general_pair = [
            general_pair[0],
            descriptor(7, mftmirr_base + 2 * record_size, 1),
        ]
        publish(mismatched_general_pair, kind=1)
        expect_failure(image, report, "no matching adjacent mirror")

        unknown_entry = descriptor(max(ACTION_KINDS) + 1)
        publish(unknown_entry, kind=1)
        expect_failure(image, report, "action kind is unknown")


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        try:
            self_test()
            print(
                "roothealth WAL entry-oracle self-test passed: "
                "descriptor_hash=true payload_hash=true exclusions=true "
                "plan_hash=true transaction_kinds=true aligned_targets=true "
                "zero_prefix=true adjacent_transitions=true "
                "mirrored_mft_pairs=true dirty_flag_delta=true "
                "semantic_seals=true plan_bytes=0x1e0 "
                "qualified_rederivation_actions=23,24,25"
            )
            return 0
        except (OSError, ValueError, KeyError, json.JSONDecodeError, WalFixtureError) as error:
            print(f"roothealth WAL entry-oracle self-test failed: {error}", file=sys.stderr)
            return 1
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    mutate_parser = subparsers.add_parser("mutate")
    mutate_parser.add_argument(
        "kind", choices=(
            "one-torn",
            "both-torn",
            "equal-generation-divergent",
            "preparing-zero",
        )
    )
    mutate_parser.add_argument("image", type=Path)
    mutate_parser.add_argument("layout", type=Path)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("image", type=Path)
    inspect_parser.add_argument("layout", type=Path)
    inspect_parser.add_argument(
        "--expect", choices=("healthy", "degraded", "invalid", "ambiguous")
    )
    inspect_parser.add_argument("--expected-journal-uuid")
    inspect_parser.add_argument("--expected-volume-serial")
    args = parser.parse_args()
    try:
        if args.command == "mutate":
            result = mutate(args.image, args.layout, args.kind)
        else:
            result = inspection(args.image, args.layout)
            if args.expect and result["verdict"] != args.expect:
                raise WalFixtureError(
                    f"WAL verdict {result['verdict']!r} differs from {args.expect!r}"
                )
            selected = result.get("selected")
            if args.expected_journal_uuid or args.expected_volume_serial:
                if not isinstance(selected, dict):
                    raise WalFixtureError("WAL has no unique selected superblock")
                if (
                    args.expected_journal_uuid
                    and selected.get("journal_uuid") != args.expected_journal_uuid
                ):
                    raise WalFixtureError("selected WAL UUID differs from expected UUID")
                if (
                    args.expected_volume_serial
                    and selected.get("serial") != args.expected_volume_serial
                ):
                    raise WalFixtureError("selected WAL serial differs from expected serial")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, WalFixtureError) as error:
        print(f"roothealth runtime WAL fixture failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
