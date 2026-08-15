#!/usr/bin/env python3
"""Build a deterministic, format-valid NTFS v1.1 $LogFile redo stream.

The input must be a freshly formatted NTFS image with a non-empty label whose
$LogFile is still wiped (all 0xff).  The output is a copy with two valid RSTR
pages, two stale base RCRD pages, one predecessor RCRD page, and one current
RCRD page containing a committed UpdateResidentValue/ForgetTransaction pair.

The redo changes one UTF-16 code unit of $Volume:$VOLUME_NAME.  For a T1OS
label it changes only the final code unit so the required ``T1OS `` identity
prefix remains valid before and after replay.  The encoder does not apply that
change; it only places it in the native journal so a replay planner can prove
a nonzero, bounded redo plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


SECTOR_SIZE = 512
LOG_PAGE_SIZE = 4096
MFT_RECORD_SIZE = 1024
LOG_RECORD_HEADER_SIZE = 0x30
RESTART_AREA_OFFSET = 0x40
CLIENT_ARRAY_OFFSET = 0x40
RESTART_AREA_LENGTH = CLIENT_ARRAY_OFFSET + 0xA0
RCRD_DATA_OFFSET = 0x40
LOGFILE_INODE = 2
VOLUME_INODE = 3
TARGET_LOG_PAGE = 5
PREVIOUS_LOG_PAGE = 4
UPDATE_RESIDENT_VALUE = 7
FORGET_TRANSACTION = 27
OPEN_NONRESIDENT_ATTRIBUTE = 28
ACTS_ON_MFT = 2
LOG_STANDARD = 1
TRANSACTION_ID = 0x11223344
CLIENT_SEQUENCE = 1
LSN_SEQUENCE = 1
EXPECTED_FIXTURE_SHA256 = (
    "3a535e16b8f66c1b1952b61b00b8a1463bf5f4c1fb806559fdaa499eba6ffab5"
)

PROBE_C = r"""
#include "config.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_recover.h"
#include "roothealth_write.h"

enum {
	FIXTURE_CLUSTER_SIZE = 4096,
	FIXTURE_MFT_RECORD_SIZE = 1024,
	FIXTURE_TARGET_VALUE = 0x180,
	FIXTURE_RECORD_LSN = 8,
	FIXTURE_RECORD_USA = 0x30,
	FIXTURE_EXPECTED_OPERATIONS = 4,
};

static int range_contains(size_t offset, size_t first, size_t length)
{
	return offset >= first && offset < first + length;
}

static uint16_t load_le16(const unsigned char *p)
{
	return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

static uint64_t load_le64(const unsigned char *p)
{
	uint64_t value = 0;
	unsigned int i;

	for (i = 0; i < 8; i++)
		value |= (uint64_t)p[i] << (8 * i);
	return value;
}

static int verify_mft_redo(const struct rh_write_operation *op,
		uint64_t expected_lsn)
{
	size_t record = 0;
	size_t lsn = record + FIXTURE_RECORD_LSN;
	size_t usa = record + FIXTURE_RECORD_USA;
	size_t value = record + FIXTURE_TARGET_VALUE;
	size_t tail1 = record + 510;
	size_t tail2 = record + 1022;
	size_t i;
	uint16_t before_usn;
	uint16_t after_usn;

	if (op->kind != RH_WRITE_LOGFILE_REDO ||
		op->length != FIXTURE_MFT_RECORD_SIZE ||
		memcmp(op->before + record, "FILE", 4) ||
		memcmp(op->after + record, "FILE", 4))
		return -1;
	if (load_le64(op->before + lsn) != 0 ||
		load_le64(op->after + lsn) != expected_lsn)
		return -1;
	if (op->before[value] != 'R' || op->before[value + 1] != 0 ||
		op->after[value] != 'S' || op->after[value + 1] != 0)
		return -1;
	before_usn = load_le16(op->before + usa);
	after_usn = load_le16(op->after + usa);
	if ((uint16_t)(before_usn + 1) != after_usn ||
		load_le16(op->after + tail1) != after_usn ||
		load_le16(op->after + tail2) != after_usn)
		return -1;
	for (i = 0; i < op->length; i++) {
		if (op->before[i] == op->after[i])
			continue;
		if (!range_contains(i, lsn, 8) &&
			!range_contains(i, usa, 2) &&
			!range_contains(i, value, 2) &&
			!range_contains(i, tail1, 2) &&
			!range_contains(i, tail2, 2)) {
			fprintf(stderr, "unexpected MFT redo byte at 0x%zx\n", i);
			return -1;
		}
	}
	return 0;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_log_result result;
	size_t i;
	int rc;

	if (argc != 2) {
		fprintf(stderr, "usage: %s NTFS_IMAGE\n", argv[0]);
		return 64;
	}
	memset(&writer, 0, sizeof(writer));
	memset(&result, 0, sizeof(result));
	if (rh_writer_open(&writer, argv[1])) {
		perror("rh_writer_open");
		return 65;
	}
	rc = roothealth_log_replay_plan(argv[1], &writer, &result);
	printf("plan_rc=%d major=%d minor=%d actions=%u redo=%u "
	       "restart_pages=%u synced=0x%016" PRIx64 " "
	       "committed=0x%016" PRIx64 " latest=0x%016" PRIx64 " "
	       "operations=%zu planned_bytes=%" PRIu64 "\n",
	       rc, result.major_version, result.minor_version,
	       result.actions_seen, result.redo_actions,
	       result.restart_pages_planned,
	       (uint64_t)result.synced_lsn,
	       (uint64_t)result.committed_lsn,
	       (uint64_t)result.latest_lsn,
	       writer.operation_count, writer.planned_bytes);
	for (i = 0; i < writer.operation_count; i++) {
		const struct rh_write_operation *op = &writer.operations[i];
		printf("op[%zu]=%s offset=%" PRIu64 " length=%zu "
		       "before=%s after=%s\n", i,
		       rh_write_kind_name(op->kind), op->offset, op->length,
		       op->before_sha256, op->after_sha256);
	}
	if (rc || result.major_version != 1 || result.minor_version != 1 ||
		result.redo_actions != 1 || result.actions_seen != 3 ||
		result.synced_lsn != UINT64_C(0x80a08) ||
		result.committed_lsn != UINT64_C(0x80a24) ||
		result.latest_lsn != UINT64_C(0x80a24) ||
		result.restart_pages_planned != 2 ||
		writer.operation_count != FIXTURE_EXPECTED_OPERATIONS ||
		writer.planned_bytes != UINT64_C(10240) ||
		verify_mft_redo(&writer.operations[0], UINT64_C(0x80a17)) ||
		verify_mft_redo(&writer.operations[1], UINT64_C(0x80a17)) ||
		writer.operations[0].offset != UINT64_C(19456) ||
		writer.operations[1].offset != UINT64_C(33553408) ||
		memcmp(writer.operations[0].before, writer.operations[1].before,
			FIXTURE_MFT_RECORD_SIZE) ||
		memcmp(writer.operations[0].after, writer.operations[1].after,
			FIXTURE_MFT_RECORD_SIZE) ||
		writer.operations[2].kind != RH_WRITE_LOGFILE_RESTART ||
		writer.operations[3].kind != RH_WRITE_LOGFILE_RESTART ||
		writer.operations[2].offset != UINT64_C(33554432) ||
		writer.operations[3].offset != UINT64_C(33558528) ||
		writer.operations[2].length != FIXTURE_CLUSTER_SIZE ||
		writer.operations[3].length != FIXTURE_CLUSTER_SIZE ||
		memcmp(writer.operations[2].after, writer.operations[3].after,
			FIXTURE_CLUSTER_SIZE)) {
		fprintf(stderr, "nonzero native redo plan was not proven\n");
		rh_writer_close(&writer);
		return 66;
	}
	/* Deliberately no rh_writer_commit() call. */
	rh_writer_close(&writer);
	return 0;
}

"""


def u16(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def u64(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def mst_unprotect(raw: bytes, record_size: int) -> bytearray:
    if len(raw) != record_size:
        raise ValueError("short MST record")
    data = bytearray(raw)
    usa_offset = u16(data, 4)
    usa_count = u16(data, 6)
    expected_count = 1 + record_size // SECTOR_SIZE
    if usa_count != expected_count:
        raise ValueError(
            f"bad USA count {usa_count}, expected {expected_count}"
        )
    if usa_offset + usa_count * 2 > record_size:
        raise ValueError("USA is outside record")
    usn = data[usa_offset : usa_offset + 2]
    for index in range(1, usa_count):
        tail = index * SECTOR_SIZE - 2
        if data[tail : tail + 2] != usn:
            raise ValueError(f"MST sequence mismatch in sector {index}")
        replacement = usa_offset + index * 2
        data[tail : tail + 2] = data[replacement : replacement + 2]
    return data


def mst_protect(page: bytearray, usa_offset: int, usn: int) -> bytes:
    if len(page) != LOG_PAGE_SIZE:
        raise ValueError("MST page is not 4096 bytes")
    usa_count = 1 + len(page) // SECTOR_SIZE
    if u16(page, 4) != usa_offset or u16(page, 6) != usa_count:
        raise ValueError("MST header disagrees with requested USA")
    struct.pack_into("<H", page, usa_offset, usn)
    for index in range(1, usa_count):
        tail = index * SECTOR_SIZE - 2
        replacement = usa_offset + index * 2
        page[replacement : replacement + 2] = page[tail : tail + 2]
        struct.pack_into("<H", page, tail, usn)
    return bytes(page)


def iter_attributes(record: bytes | bytearray):
    offset = u16(record, 20)
    bytes_in_use = u32(record, 24)
    while offset + 16 <= bytes_in_use:
        attr_type = u32(record, offset)
        if attr_type == 0xFFFFFFFF:
            return
        length = u32(record, offset + 4)
        if length < 24 or length % 8 or offset + length > bytes_in_use:
            raise ValueError(f"malformed attribute at 0x{offset:x}")
        yield offset, attr_type, bool(record[offset + 8]), length
        offset += length
    raise ValueError("attribute terminator missing")


def decode_mapping_pairs(attr: bytes | bytearray, attr_offset: int):
    mapping_offset = u16(attr, attr_offset + 32)
    cursor = attr_offset + mapping_offset
    current_lcn = 0
    current_vcn = u64(attr, attr_offset + 16)
    runs = []
    while True:
        header = attr[cursor]
        cursor += 1
        if header == 0:
            break
        length_bytes = header & 0x0F
        offset_bytes = header >> 4
        if not length_bytes or length_bytes > 8 or offset_bytes > 8:
            raise ValueError("invalid mapping-pairs header")
        run_length = int.from_bytes(
            attr[cursor : cursor + length_bytes], "little", signed=False
        )
        cursor += length_bytes
        if not offset_bytes:
            raise ValueError("sparse $LogFile run is not supported")
        delta_raw = bytes(attr[cursor : cursor + offset_bytes])
        cursor += offset_bytes
        delta = int.from_bytes(delta_raw, "little", signed=True)
        current_lcn += delta
        runs.append(
            {
                "vcn": current_vcn,
                "lcn": current_lcn,
                "clusters": run_length,
            }
        )
        current_vcn += run_length
    return runs


def parse_geometry(image):
    image.seek(0)
    boot = image.read(SECTOR_SIZE)
    if len(boot) != SECTOR_SIZE or boot[3:11] != b"NTFS    ":
        raise ValueError("input is not an NTFS image")
    bytes_per_sector = u16(boot, 11)
    sectors_per_cluster = boot[13]
    cluster_size = bytes_per_sector * sectors_per_cluster
    mft_lcn = u64(boot, 48)
    record_code = struct.unpack_from("<b", boot, 64)[0]
    record_size = (
        cluster_size * record_code if record_code > 0 else 1 << -record_code
    )
    if bytes_per_sector != SECTOR_SIZE:
        raise ValueError("fixture requires 512-byte NTFS sectors")
    if cluster_size != LOG_PAGE_SIZE:
        raise ValueError("fixture requires 4096-byte clusters")
    if record_size != MFT_RECORD_SIZE:
        raise ValueError("fixture requires 1024-byte MFT records")
    return {
        "bytes_per_sector": bytes_per_sector,
        "cluster_size": cluster_size,
        "mft_lcn": mft_lcn,
        "mft_record_size": record_size,
    }


def read_mft_record(image, geometry, inode):
    offset = (
        geometry["mft_lcn"] * geometry["cluster_size"]
        + inode * geometry["mft_record_size"]
    )
    image.seek(offset)
    raw = image.read(geometry["mft_record_size"])
    record = mst_unprotect(raw, geometry["mft_record_size"])
    if record[:4] != b"FILE":
        raise ValueError(f"MFT record {inode} is not FILE")
    if u32(record, 44) != inode:
        raise ValueError(f"MFT record number mismatch for inode {inode}")
    return offset, record


def find_logfile(image, geometry):
    _, record = read_mft_record(image, geometry, LOGFILE_INODE)
    for offset, attr_type, nonresident, _ in iter_attributes(record):
        if attr_type == 0x80 and nonresident:
            data_size = u64(record, offset + 48)
            runs = decode_mapping_pairs(record, offset)
            if data_size < 2 * LOG_PAGE_SIZE + 48 * LOG_PAGE_SIZE:
                raise ValueError("$LogFile is below the NTFS minimum size")
            return data_size, runs
    raise ValueError("nonresident $LogFile::$DATA is missing")


def find_volume_name(image, geometry):
    _, record = read_mft_record(image, geometry, VOLUME_INODE)
    for offset, attr_type, nonresident, _ in iter_attributes(record):
        if attr_type != 0x60:
            continue
        if nonresident:
            raise ValueError("$VOLUME_NAME unexpectedly nonresident")
        value_length = u32(record, offset + 16)
        value_offset = u16(record, offset + 20)
        value = bytes(record[offset + value_offset : offset + value_offset + value_length])
        label = value.decode("utf-16le")
        if not label:
            raise ValueError("fixture base image must have a non-empty label")
        code_unit_index = len(label) - 1 if label.startswith("T1OS ") else 0
        old_character = label[code_unit_index]
        if ord(old_character) >= 0x7e:
            raise ValueError("fixture label target is outside the bounded ASCII profile")
        new_character = chr(ord(old_character) + 1)
        after_label = (
            label[:code_unit_index] + new_character + label[code_unit_index + 1 :]
        )
        return {
            "record_offset": offset,
            "attribute_offset": value_offset + code_unit_index * 2,
            "old_code_unit": old_character.encode("utf-16le"),
            "new_code_unit": new_character.encode("utf-16le"),
            "volume_name_before": label,
            "volume_name_after": after_label,
        }
    raise ValueError("$Volume:$VOLUME_NAME is missing")


def map_stream_range(runs, cluster_size, logical_offset, length):
    remaining = length
    cursor = logical_offset
    while remaining:
        vcn = cursor // cluster_size
        within = cursor % cluster_size
        for run in runs:
            if run["vcn"] <= vcn < run["vcn"] + run["clusters"]:
                available_clusters = run["vcn"] + run["clusters"] - vcn
                available = available_clusters * cluster_size - within
                take = min(remaining, available)
                physical = (
                    (run["lcn"] + vcn - run["vcn"]) * cluster_size + within
                )
                yield physical, take
                cursor += take
                remaining -= take
                break
        else:
            raise ValueError(f"unmapped $LogFile VCN {vcn}")


def stream_read(image, runs, cluster_size, offset, length):
    chunks = []
    for physical, take in map_stream_range(runs, cluster_size, offset, length):
        image.seek(physical)
        chunk = image.read(take)
        if len(chunk) != take:
            raise ValueError("short image read")
        chunks.append(chunk)
    return b"".join(chunks)


def stream_write(image, runs, cluster_size, offset, data):
    copied = 0
    for physical, take in map_stream_range(runs, cluster_size, offset, len(data)):
        image.seek(physical)
        if image.write(data[copied : copied + take]) != take:
            raise ValueError("short image write")
        copied += take
    if copied != len(data):
        raise ValueError("incomplete stream write")


def make_lsn(sequence_bits, page_number, record_offset):
    offset_bits = 64 - sequence_bits
    byte_offset = page_number * LOG_PAGE_SIZE + record_offset
    if byte_offset % 8:
        raise ValueError("LSN target is not 8-byte aligned")
    offset_part = byte_offset // 8
    if offset_part >= 1 << offset_bits:
        raise ValueError("LSN offset exceeds restart-area geometry")
    return (LSN_SEQUENCE << offset_bits) | offset_part


def encode_common_record(
    total_size, this_lsn, previous_lsn, undo_next_lsn, transaction_id
):
    if total_size < 88 or total_size % 8:
        raise ValueError("invalid log-record size")
    record = bytearray(total_size)
    struct.pack_into("<Q", record, 0, this_lsn)
    struct.pack_into("<Q", record, 8, previous_lsn)
    struct.pack_into("<Q", record, 16, undo_next_lsn)
    struct.pack_into("<I", record, 24, total_size - LOG_RECORD_HEADER_SIZE)
    struct.pack_into("<HH", record, 28, CLIENT_SEQUENCE, 0)
    struct.pack_into("<I", record, 32, LOG_STANDARD)
    struct.pack_into("<I", record, 36, transaction_id)
    return record


def encode_update_record(
    this_lsn, target_lcn, target_vcn, cluster_index, volume_name,
    previous_lsn=0,
):
    record = encode_common_record(
        104, this_lsn, previous_lsn, previous_lsn, TRANSACTION_ID
    )
    struct.pack_into("<HHHH", record, 48, UPDATE_RESIDENT_VALUE,
                     UPDATE_RESIDENT_VALUE, 0x28, 2)
    struct.pack_into("<HHHH", record, 56, 0x30, 2, 24, 1)
    struct.pack_into(
        "<HHHHQ",
        record,
        64,
        volume_name["record_offset"],
        volume_name["attribute_offset"],
        cluster_index,
        ACTS_ON_MFT,
        target_vcn,
    )
    struct.pack_into("<Q", record, 80, target_lcn)
    record[88:90] = volume_name["new_code_unit"]
    record[96:98] = volume_name["old_code_unit"]
    return bytes(record)


def encode_open_mft_record(this_lsn, mft_reference):
    record = encode_common_record(120, this_lsn, 0, 0, TRANSACTION_ID)
    struct.pack_into("<HHHHHH", record, 48,
                     OPEN_NONRESIDENT_ATTRIBUTE, 0, 0x28, 40, 0, 0)
    struct.pack_into("<H", record, 60, 24)
    entry = bytearray(40)
    struct.pack_into("<III", entry, 0, 0xFFFFFFFF, 0, 0x80)
    struct.pack_into("<Q", entry, 16, mft_reference)
    record[80:120] = entry
    return bytes(record)


def encode_forget_record(this_lsn, previous_lsn):
    record = encode_common_record(
        88, this_lsn, previous_lsn, previous_lsn, TRANSACTION_ID
    )
    struct.pack_into("<HH", record, 48, FORGET_TRANSACTION, 0)
    return bytes(record)


def encode_restart_page(
    current_lsn, synced_lsn, committed_lsn, logfile_size, sequence_bits, usn
):
    page = bytearray(LOG_PAGE_SIZE)
    page[0:4] = b"RSTR"
    struct.pack_into("<HH", page, 4, 0x20, 9)
    struct.pack_into("<Q", page, 8, 0)
    struct.pack_into("<II", page, 16, LOG_PAGE_SIZE, LOG_PAGE_SIZE)
    struct.pack_into("<HhhH", page, 24, RESTART_AREA_OFFSET, 1, 1, usn)

    area = RESTART_AREA_OFFSET
    struct.pack_into("<Q", page, area + 0, current_lsn)
    struct.pack_into("<HHHH", page, area + 8, 1, 0xFFFF, 0, 0)
    struct.pack_into("<I", page, area + 16, sequence_bits)
    struct.pack_into(
        "<HH", page, area + 20, RESTART_AREA_LENGTH, CLIENT_ARRAY_OFFSET
    )
    struct.pack_into("<Q", page, area + 24, logfile_size)
    struct.pack_into("<IHHII", page, area + 32, 40, 0x30, 0x40, 1, 0)

    client = area + CLIENT_ARRAY_OFFSET
    struct.pack_into("<QQHHH", page, client, synced_lsn, committed_lsn,
                     0xFFFF, 0xFFFF, CLIENT_SEQUENCE)
    struct.pack_into("<I", page, client + 28, 8)
    page[client + 32 : client + 40] = "NTFS".encode("utf-16le")
    return mst_protect(page, 0x20, usn)


def encode_record_page(
    page_number,
    copy_value,
    last_end_lsn,
    next_record_offset,
    records=b"",
    usn=0xB000,
):
    page = bytearray(LOG_PAGE_SIZE)
    page[0:4] = b"RCRD"
    struct.pack_into("<HHQ", page, 4, 0x28, 9, copy_value)
    struct.pack_into("<IHHH", page, 16, 1, 1, 1, next_record_offset)
    struct.pack_into("<Q", page, 32, last_end_lsn)
    if records:
        expected_end = RCRD_DATA_OFFSET + len(records)
        if next_record_offset != expected_end:
            raise ValueError("record page next offset disagrees with payload")
        page[RCRD_DATA_OFFSET:expected_end] = records
    return mst_protect(page, 0x28, usn + page_number)


def require(condition: bool, message: str):
    if not condition:
        raise ValueError(f"strict fixture validation failed: {message}")


def validate_common_action(record: bytes, expected_size: int):
    require(len(record) == expected_size, "action size")
    require(u32(record, 24) + LOG_RECORD_HEADER_SIZE == expected_size,
            "client_data_length")
    require(u16(record, 28) == CLIENT_SEQUENCE, "client sequence")
    require(u16(record, 30) == 0, "client index")
    require(u32(record, 32) == LOG_STANDARD, "record type")
    require(u32(record, 36) == TRANSACTION_ID, "transaction id")
    require(record[40:48] == b"\0" * 8, "record flags/reserved bytes")


def validate_encoded_layout(
    encoded: bytes,
    logfile_size: int,
    sequence_bits: int,
    open_lsn: int,
    update_lsn: int,
    forget_lsn: int,
    predecessor_lsn: int,
    target_lcn: int,
    target_vcn: int,
    cluster_index: int,
    volume_name,
):
    """Strictly parse our output without relying on replay-parser recovery.

    This deliberately accepts one layout only. It prevents a malformed page,
    an unbounded record scan, or the parser's stale-record recovery heuristics
    from turning a structurally invalid encoder result into a passing test.
    """
    require(len(encoded) == 6 * LOG_PAGE_SIZE, "six-page encoded prefix")
    protected = [
        encoded[index * LOG_PAGE_SIZE : (index + 1) * LOG_PAGE_SIZE]
        for index in range(6)
    ]
    pages = []
    for index, raw in enumerate(protected):
        expected_magic = b"RSTR" if index < 2 else b"RCRD"
        expected_usa = 0x20 if index < 2 else 0x28
        require(raw[:4] == expected_magic, f"page {index} protected magic")
        require(u16(raw, 4) == expected_usa, f"page {index} USA offset")
        require(u16(raw, 6) == 9, f"page {index} USA count")
        page = mst_unprotect(raw, LOG_PAGE_SIZE)
        require(page[:4] == expected_magic, f"page {index} magic")
        pages.append(page)

    for index in (0, 1):
        page = pages[index]
        area = RESTART_AREA_OFFSET
        client = area + CLIENT_ARRAY_OFFSET
        require(u64(page, 8) == 0, f"restart {index} chkdsk_lsn")
        require(u32(page, 16) == LOG_PAGE_SIZE,
                f"restart {index} system page size")
        require(u32(page, 20) == LOG_PAGE_SIZE,
                f"restart {index} log page size")
        require(u16(page, 24) == area, f"restart {index} area offset")
        require(u16(page, 26) == 1 and u16(page, 28) == 1,
                f"restart {index} NTFS version 1.1")
        require(u64(page, area) == forget_lsn,
                f"restart {index} current_lsn")
        require(u16(page, area + 8) == 1, f"restart {index} client count")
        require(u16(page, area + 10) == 0xFFFF,
                f"restart {index} free list")
        require(u16(page, area + 12) == 0,
                f"restart {index} in-use list")
        require(u16(page, area + 14) == 0,
                f"restart {index} dirty flag")
        require(u32(page, area + 16) == sequence_bits,
                f"restart {index} sequence bits")
        require(u16(page, area + 20) == RESTART_AREA_LENGTH,
                f"restart {index} area length")
        require(u16(page, area + 22) == CLIENT_ARRAY_OFFSET,
                f"restart {index} client offset")
        require(u64(page, area + 24) == logfile_size,
                f"restart {index} logfile size")
        require(u32(page, area + 32) == 40,
                f"restart {index} final client-data length")
        require(u16(page, area + 36) == LOG_RECORD_HEADER_SIZE,
                f"restart {index} record header size")
        require(u16(page, area + 38) == RCRD_DATA_OFFSET,
                f"restart {index} record data offset")
        require(u64(page, client) == open_lsn,
                f"restart {index} oldest_lsn")
        require(u64(page, client + 8) == forget_lsn,
                f"restart {index} client_restart_lsn")
        require(u16(page, client + 16) == 0xFFFF and
                u16(page, client + 18) == 0xFFFF,
                f"restart {index} client links")
        require(u16(page, client + 20) == CLIENT_SEQUENCE,
                f"restart {index} client sequence")
        require(u32(page, client + 28) == 8,
                f"restart {index} client name length")
        require(page[client + 32 : client + 40] ==
                "NTFS".encode("utf-16le"),
                f"restart {index} client name")

    expected_headers = {
        2: (TARGET_LOG_PAGE * LOG_PAGE_SIZE, open_lsn, RCRD_DATA_OFFSET),
        3: (TARGET_LOG_PAGE * LOG_PAGE_SIZE, open_lsn - 1,
            RCRD_DATA_OFFSET),
        4: (predecessor_lsn, predecessor_lsn, LOG_PAGE_SIZE - 16),
        5: (forget_lsn, forget_lsn,
            RCRD_DATA_OFFSET + 120 + 104 + 88),
    }
    for index, (copy_value, last_end, next_offset) in expected_headers.items():
        page = pages[index]
        require(u64(page, 8) == copy_value, f"record {index} copy field")
        require(u32(page, 16) == 1, f"record {index} flags")
        require(u16(page, 20) == 1 and u16(page, 22) == 1,
                f"record {index} page position")
        require(u16(page, 24) == next_offset,
                f"record {index} next offset")
        require(page[26:32] == b"\0" * 6,
                f"record {index} reserved header")
        require(u64(page, 32) == last_end,
                f"record {index} last_end_lsn")

    require(pages[2][RCRD_DATA_OFFSET:] ==
            b"\0" * (LOG_PAGE_SIZE - RCRD_DATA_OFFSET),
            "base record page 2 has no hidden actions")
    require(pages[3][RCRD_DATA_OFFSET:] ==
            b"\0" * (LOG_PAGE_SIZE - RCRD_DATA_OFFSET),
            "base record page 3 has no hidden actions")
    require(pages[4][RCRD_DATA_OFFSET:] ==
            b"\0" * (LOG_PAGE_SIZE - RCRD_DATA_OFFSET),
            "predecessor page has no hidden actions")

    target = pages[TARGET_LOG_PAGE]
    opened = bytes(target[RCRD_DATA_OFFSET : RCRD_DATA_OFFSET + 120])
    update_at = RCRD_DATA_OFFSET + 120
    update = bytes(target[update_at:update_at + 104])
    forget_at = update_at + 104
    forget = bytes(target[forget_at:forget_at + 88])
    require(target[forget_at + 88:] ==
            b"\0" * (LOG_PAGE_SIZE - forget_at - 88),
            "target page has trailing or hidden actions")

    validate_common_action(opened, 120)
    require(u64(opened, 0) == open_lsn and
            u64(opened, 8) == 0 and u64(opened, 16) == 0,
            "open-attribute transaction start")
    require(u16(opened, 48) == OPEN_NONRESIDENT_ATTRIBUTE and
            u16(opened, 50) == 0 and u16(opened, 52) == 0x28 and
            u16(opened, 54) == 40 and not u16(opened, 58),
            "open-attribute payload window")
    require(u16(opened, 60) == 24 and not u16(opened, 62),
            "open-attribute key and no LCNs")
    require(u32(opened, 80) == 0xFFFFFFFF and
            u32(opened, 88) == 0x80 and
            u64(opened, 96) == ((1 << 48) | 0),
            "open-attribute binds $MFT::$DATA")

    validate_common_action(update, 104)
    require(u64(update, 0) == update_lsn, "update this_lsn")
    require(u64(update, 8) == open_lsn and u64(update, 16) == open_lsn,
            "update previous/undo LSN")
    require(u16(update, 48) == UPDATE_RESIDENT_VALUE and
            u16(update, 50) == UPDATE_RESIDENT_VALUE,
            "update redo/undo operation")
    require(u16(update, 52) == 0x28 and u16(update, 54) == 2,
            "update redo window")
    require(u16(update, 56) == 0x30 and u16(update, 58) == 2,
            "update undo window")
    require(u16(update, 60) == 24 and u16(update, 62) == 1,
            "update attribute key/LCN count")
    require(u16(update, 64) == volume_name["record_offset"] and
            u16(update, 66) == volume_name["attribute_offset"],
            "update target offsets")
    require(u16(update, 68) == cluster_index and
            u16(update, 70) == ACTS_ON_MFT,
            "update MFT target geometry")
    require(u64(update, 72) == target_vcn and u64(update, 80) == target_lcn,
            "update target VCN/LCN")
    require(update[88:90] == volume_name["new_code_unit"] and
            update[96:98] == volume_name["old_code_unit"],
            "update redo/undo payload")
    require(update[90:96] == b"\0" * 6 and update[98:104] == b"\0" * 6,
            "update payload padding")

    validate_common_action(forget, 88)
    require(u64(forget, 0) == forget_lsn, "forget this_lsn")
    require(u64(forget, 8) == update_lsn and u64(forget, 16) == update_lsn,
            "forget transaction chain")
    require(u16(forget, 48) == FORGET_TRANSACTION and u16(forget, 50) == 0,
            "forget operation")
    require(forget[52:88] == b"\0" * 36, "forget payload")

    offset_bits = 64 - sequence_bits
    offset_mask = (1 << offset_bits) - 1
    require((update_lsn & offset_mask) * 8 ==
            TARGET_LOG_PAGE * LOG_PAGE_SIZE + RCRD_DATA_OFFSET + 120,
            "update LSN byte address")
    require((open_lsn & offset_mask) * 8 ==
            TARGET_LOG_PAGE * LOG_PAGE_SIZE + RCRD_DATA_OFFSET,
            "open LSN byte address")
    require((forget_lsn & offset_mask) * 8 ==
            TARGET_LOG_PAGE * LOG_PAGE_SIZE + RCRD_DATA_OFFSET + 224,
            "forget LSN byte address")
    require(forget_lsn - update_lsn == 104 // 8,
            "contiguous action LSNs")


def prove_strict_rejections(encoded: bytes, validate):
    """Prove three boundedness failures are rejected before parser use."""
    checks = []

    def mutate_target(mutator, usn):
        changed = bytearray(encoded)
        begin = TARGET_LOG_PAGE * LOG_PAGE_SIZE
        page = mst_unprotect(
            bytes(changed[begin : begin + LOG_PAGE_SIZE]), LOG_PAGE_SIZE
        )
        mutator(page)
        changed[begin : begin + LOG_PAGE_SIZE] = mst_protect(page, 0x28, usn)
        return bytes(changed)

    def must_reject(name, changed, expected_message):
        try:
            validate(changed)
        except ValueError as error:
            require(expected_message in str(error),
                    f"negative test {name} failed for the expected reason")
            checks.append(name)
            return
        raise ValueError(
            f"strict fixture validation failed: negative test {name} passed"
        )

    must_reject(
        "unbounded-next-record-offset",
        mutate_target(lambda page: struct.pack_into("<H", page, 24, 0xFFFF),
                      0xD501),
        "record 5 next offset",
    )
    must_reject(
        "oversized-client-data-length",
        mutate_target(
            lambda page: struct.pack_into(
                "<I", page, RCRD_DATA_OFFSET + 24, 0xFFF8
            ),
            0xD502,
        ),
        "client_data_length",
    )
    must_reject(
        "hidden-third-action",
        mutate_target(
            lambda page: page.__setitem__(RCRD_DATA_OFFSET + 312, 1),
            0xD503,
        ),
        "target page has trailing or hidden actions",
    )
    require(len(checks) == 3, "all negative boundedness tests ran")
    return checks


def build(base_path: Path, output_path: Path, manifest_path: Path):
    if base_path.resolve() == output_path.resolve():
        raise ValueError("base and output paths must differ")
    if output_path.exists():
        raise ValueError(f"refusing to overwrite {output_path}")
    shutil.copyfile(base_path, output_path)

    try:
        with output_path.open("r+b", buffering=0) as image:
            geometry = parse_geometry(image)
            logfile_size, logfile_runs = find_logfile(image, geometry)
            volume_name = find_volume_name(image, geometry)
            # Page 6 is an explicit all-0xff sentinel. The strict validator
            # checks it so the parser cannot pass by scanning unbounded data.
            required = 7 * LOG_PAGE_SIZE
            wiped = stream_read(
                image, logfile_runs, geometry["cluster_size"], 0, required
            )
            if wiped != b"\xff" * required:
                raise ValueError("base $LogFile first six pages are not wiped")

            sequence_bits = 67 - logfile_size.bit_length()
            _, mft_record = read_mft_record(image, geometry, 0)
            mft_reference = (u16(mft_record, 16) << 48) | 0
            open_offset = RCRD_DATA_OFFSET
            open_lsn = make_lsn(sequence_bits, TARGET_LOG_PAGE, open_offset)
            predecessor_lsn = make_lsn(
                sequence_bits, PREVIOUS_LOG_PAGE, LOG_PAGE_SIZE - 16
            )
            open_record = encode_open_mft_record(open_lsn, mft_reference)
            update_offset = open_offset + len(open_record)
            update_lsn = make_lsn(sequence_bits, TARGET_LOG_PAGE, update_offset)
            target_byte = VOLUME_INODE * geometry["mft_record_size"]
            target_vcn = target_byte // geometry["cluster_size"]
            cluster_index = (
                target_byte % geometry["cluster_size"]
            ) // SECTOR_SIZE
            target_lcn = geometry["mft_lcn"] + target_vcn

            update_record = encode_update_record(
                update_lsn,
                target_lcn,
                target_vcn,
                cluster_index,
                volume_name,
                previous_lsn=open_lsn,
            )
            forget_offset = update_offset + len(update_record)
            forget_lsn = make_lsn(
                sequence_bits, TARGET_LOG_PAGE, forget_offset
            )
            forget_record = encode_forget_record(forget_lsn, update_lsn)
            records = open_record + update_record + forget_record

            pages = {
                0: encode_restart_page(
                    forget_lsn, open_lsn, forget_lsn,
                    logfile_size, sequence_bits, 0xA001
                ),
                1: encode_restart_page(
                    forget_lsn, open_lsn, forget_lsn,
                    logfile_size, sequence_bits, 0xA002
                ),
                2: encode_record_page(
                    2,
                    TARGET_LOG_PAGE * LOG_PAGE_SIZE,
                    open_lsn,
                    RCRD_DATA_OFFSET,
                    usn=0xB100,
                ),
                3: encode_record_page(
                    3,
                    TARGET_LOG_PAGE * LOG_PAGE_SIZE,
                    open_lsn - 1,
                    RCRD_DATA_OFFSET,
                    usn=0xB100,
                ),
                PREVIOUS_LOG_PAGE: encode_record_page(
                    PREVIOUS_LOG_PAGE,
                    predecessor_lsn,
                    predecessor_lsn,
                    LOG_PAGE_SIZE - 16,
                    usn=0xB100,
                ),
                TARGET_LOG_PAGE: encode_record_page(
                    TARGET_LOG_PAGE,
                    forget_lsn,
                    forget_lsn,
                    RCRD_DATA_OFFSET + len(records),
                    records=records,
                    usn=0xB100,
                ),
            }
            encoded_pages = b"".join(pages[index] for index in range(6))

            def strict_validate(payload):
                validate_encoded_layout(
                    payload,
                    logfile_size,
                    sequence_bits,
                    open_lsn,
                    update_lsn,
                    forget_lsn,
                    predecessor_lsn,
                    target_lcn,
                    target_vcn,
                    cluster_index,
                    volume_name,
                )

            strict_validate(encoded_pages)
            negative_layout_tests = prove_strict_rejections(
                encoded_pages, strict_validate
            )
            for page_number, page in pages.items():
                stream_write(
                    image,
                    logfile_runs,
                    geometry["cluster_size"],
                    page_number * LOG_PAGE_SIZE,
                    page,
                )
            image.flush()
            os.fsync(image.fileno())

            encoded_with_sentinel = stream_read(
                image, logfile_runs, geometry["cluster_size"], 0, required
            )
            encoded = encoded_with_sentinel[: 6 * LOG_PAGE_SIZE]
            require(encoded_with_sentinel[6 * LOG_PAGE_SIZE:] ==
                    b"\xff" * LOG_PAGE_SIZE,
                    "page 6 all-0xff scan sentinel")
            for page_number, page in pages.items():
                actual = encoded[
                    page_number * LOG_PAGE_SIZE : (page_number + 1) * LOG_PAGE_SIZE
                ]
                if actual != page:
                    raise ValueError(f"page {page_number} did not verify")
            validate_encoded_layout(
                encoded,
                logfile_size,
                sequence_bits,
                open_lsn,
                update_lsn,
                forget_lsn,
                predecessor_lsn,
                target_lcn,
                target_vcn,
                cluster_index,
                volume_name,
            )

        manifest = {
            "format": "roothealth-native-logfile-redo-v1",
            "base": str(base_path),
            "fixture": str(output_path),
            "geometry": geometry,
            "logfile_size": logfile_size,
            "logfile_runs": logfile_runs,
            "restart": {
                "version": "1.1",
                "sequence_number_bits": sequence_bits,
                "synced_lsn": f"0x{open_lsn:016x}",
                "committed_lsn": f"0x{forget_lsn:016x}",
                "current_lsn": f"0x{forget_lsn:016x}",
            },
            "transaction": {
                "id": f"0x{TRANSACTION_ID:08x}",
                "open_operation": "OpenNonResidentAttribute",
                "open_lsn": f"0x{open_lsn:016x}",
                "update_operation": "UpdateResidentValue",
                "update_lsn": f"0x{update_lsn:016x}",
                "forget_lsn": f"0x{forget_lsn:016x}",
                "target_inode": VOLUME_INODE,
                "target_attribute": "$VOLUME_NAME",
                "record_offset": volume_name["record_offset"],
                "attribute_offset": volume_name["attribute_offset"],
                "before_utf16le": volume_name["old_code_unit"].hex(),
                "after_utf16le": volume_name["new_code_unit"].hex(),
                "volume_name_before": volume_name["volume_name_before"],
                "volume_name_after": volume_name["volume_name_after"],
            },
            "pages": {
                str(number): {
                    "logical_offset": number * LOG_PAGE_SIZE,
                    "sha256": sha256(page),
                }
                for number, page in pages.items()
            },
            "first_six_pages_sha256": sha256(encoded),
            "page_6_ff_sentinel_sha256": sha256(
                encoded_with_sentinel[6 * LOG_PAGE_SIZE:]
            ),
            "strict_layout_validation": True,
            "negative_layout_tests": negative_layout_tests,
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest
    except Exception:
        output_path.unlink(missing_ok=True)
        raise


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def run_checked(command, description: str):
    completed = subprocess.run(
        [str(item) for item in command],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"{description} failed ({completed.returncode})\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


def require_tree_artifacts(tree: Path):
    required = [
        tree / "config.h",
        tree / "src" / "roothealth_recover.o",
        tree / "src" / "roothealth_playlog.o",
        tree / "src" / "roothealth_write.o",
        tree / "src" / "utils.o",
        tree / "libntfs" / ".libs" / "libntfs.a",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ValueError(
            "pinned RootHealth tree is not built; missing: " + ", ".join(missing)
        )
    return required


def run_self_test_in(tree: Path, cc: str, work: Path):
    require_tree_artifacts(tree)
    if work.exists():
        require(work.is_dir(), f"self-test work path is not a directory: {work}")
        require(not any(work.iterdir()), f"self-test work directory is not empty: {work}")
    else:
        work.mkdir(parents=True)

    base = work / "base.img"
    fixture = work / "native-redo.img"
    manifest_path = work / "native-redo.json"
    probe_source = work / "replay_probe.c"
    probe = work / "replay-probe"
    mkntfs = shutil.which("mkfs.ntfs") or shutil.which("mkntfs")
    require(mkntfs is not None, "system mkfs.ntfs is unavailable")

    with base.open("wb") as image:
        image.truncate(64 * 1024 * 1024)
    run_checked(
        [mkntfs, "-F", "-q", "-T", "-L", "RHREDO", base],
        "deterministic mkntfs",
    )
    base_before = file_sha256(base)
    manifest = build(base, fixture, manifest_path)
    base_after = file_sha256(base)
    require(base_before == base_after, "encoder changed its source/base image")
    require(manifest["strict_layout_validation"] is True,
            "strict independent layout validation")

    fixture_before = file_sha256(fixture)
    if EXPECTED_FIXTURE_SHA256 is not None:
        require(fixture_before == EXPECTED_FIXTURE_SHA256,
                "deterministic whole-fixture SHA-256")
    probe_source.write_text(PROBE_C.lstrip(), encoding="utf-8")
    common = [
        cc, "-std=c11", "-D_GNU_SOURCE", "-D_FORTIFY_SOURCE=3",
        "-DHAVE_CONFIG_H", "-Wall", "-Wextra", "-Werror",
        f"-I{tree}", f"-I{tree / 'include'}", f"-I{tree / 'libntfs'}",
        f"-I{tree / 'src'}",
    ]
    objects = []
    for name in (
        "roothealth_replay_guard", "roothealth_replay_analysis",
        "roothealth_recover", "roothealth_playlog", "roothealth_write",
    ):
        obj = work / f"{name}.o"
        run_checked(
            common + ["-Wno-address-of-packed-member", "-c",
                      tree / "src" / f"{name}.c", "-o", obj],
            f"strict compile {name}",
        )
        objects.append(obj)
    run_checked(
        common + [probe_source, *objects, tree / "src" / "utils.o",
                  tree / "libntfs" / ".libs" / "libntfs.a",
                  "-o", probe],
        "plan-only probe compile",
    )
    planned = run_checked([probe, fixture], "plan-only native replay probe")
    fixture_after = file_sha256(fixture)
    require(fixture_before == fixture_after,
            "plan-only parser changed its source image")

    lines = planned.stdout.splitlines()
    summary = [line for line in lines if line.startswith("plan_rc=")]
    operations = [line for line in lines if line.startswith("op[")]
    require(len(summary) == 1, "one parser result line")
    for fragment in (
        "plan_rc=0",
        "major=1 minor=1",
        "actions=3 redo=1 restart_pages=2",
        "operations=4 planned_bytes=10240",
    ):
        require(fragment in summary[0], f"parser result contains {fragment!r}")
    require(len(operations) == 4, "exactly four typed operations")
    require("op[0]=logfile-redo" in operations[0], "primary MFT redo type")
    require("op[1]=logfile-redo" in operations[1], "$MFTMirr redo type")
    require("op[2]=logfile-restart" in operations[2], "first RSTR type")
    require("op[3]=logfile-restart" in operations[3], "second RSTR type")

    if planned.stdout:
        print(planned.stdout, end="" if planned.stdout.endswith("\n") else "\n")
    if planned.stderr:
        print(planned.stderr, file=sys.stderr,
              end="" if planned.stderr.endswith("\n") else "\n")
    result = {
        "result": "PASS",
        "strict_layout_validation": True,
        "negative_layout_tests": manifest["negative_layout_tests"],
        "base_sha256_before": base_before,
        "base_sha256_after": base_after,
        "fixture_sha256_before_parser": fixture_before,
        "fixture_sha256_after_parser": fixture_after,
        "actions": 3,
        "redo_actions": 1,
        "restart_pages": 2,
        "typed_operations": 4,
        "planned_bytes": 10240,
        "work_directory": str(work),
    }
    print(json.dumps(result, sort_keys=True))
    return result


def run_self_test(tree: Path, cc: str, work_dir: Path | None):
    tree = tree.resolve()
    if work_dir is not None:
        return run_self_test_in(tree, cc, work_dir.resolve())
    with tempfile.TemporaryDirectory(
        prefix="roothealth-native-redo.", dir="/var/tmp"
    ) as temporary:
        return run_self_test_in(tree, cc, Path(temporary))


def make_parser():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Assumptions: NTFS 1.1, 512-byte sectors, 4096-byte clusters/pages, "
            "1024-byte MFT records, a freshly wiped $LogFile, and label RHREDO. "
            "The strict encoder validator accepts exactly two bounded actions and "
            "an all-0xff page-6 sentinel before the RootHealth parser is invoked."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    encoder = subparsers.add_parser("encode", help="encode a fixture image")
    encoder.add_argument("base", type=Path)
    encoder.add_argument("output", type=Path)
    encoder.add_argument("--manifest", type=Path)

    self_test = subparsers.add_parser(
        "self-test", help="build and prove a parser plan-only fixture"
    )
    self_test.add_argument("--tree", required=True, type=Path,
                           help="built pinned ntfs-next/RootHealth source tree")
    self_test.add_argument("--cc", default=os.environ.get("CC", "cc"))
    self_test.add_argument(
        "--work-dir", type=Path,
        help="new or empty directory to retain self-test artifacts",
    )
    return parser


def main():
    args = make_parser().parse_args()
    if args.command == "encode":
        manifest_path = args.manifest or args.output.with_suffix(".json")
        manifest = build(args.base, args.output, manifest_path)
        print(json.dumps(manifest, sort_keys=True))
        return 0
    run_self_test(args.tree, args.cc, args.work_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
