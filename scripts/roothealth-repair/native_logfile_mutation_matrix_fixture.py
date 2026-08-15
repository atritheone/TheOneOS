#!/usr/bin/env python3
"""Deterministic native $LogFile mutation-pair qualification fixture.

This builds a real 64 MiB NTFS image and injects a v1.1 log containing a
committed winner plus an active loser.  It exercises initialization, resident
attribute creation, mapping-pair and size updates, and three INDX operations.
The linked probe uses a persistent-undo writer backend but never commits.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helper = load("roothealth_redo_helper", "native_logfile_redo_fixture.py")
multi = load("roothealth_multitx_helper", "native_logfile_multitx_fixture.py")

PAGE = 4096
DATA_OFFSET = 0x40
TARGET_PAGE = 5
PREVIOUS_PAGE = 4
WINNER_TX = 24
LOSER_TX = 64
NOOP = 0
INITIALIZE_MFT = 2
CREATE_ATTRIBUTE = 5
DELETE_ATTRIBUTE = 6
UPDATE_MAPPING = 9
SET_SIZES = 11
ADD_INDEX_ALLOCATION = 14
DELETE_INDEX_ALLOCATION = 15
SET_VCN_ALLOCATION = 18
FORGET = 27
OPEN_NONRESIDENT = 28
UPDATE_RECORD_DATA_ALLOCATION = 34
ACTS_ON_MFT = 2
ACTS_ON_INDX = 8
INDEX_ATTRIBUTE = 24
MFT_ATTRIBUTE = 64
LOG_DELETING = 2
AT_DATA = 0x80
AT_BITMAP = 0xB0
AT_END = 0xFFFFFFFF
MFT_RECORD = 27
INDEX_OWNER_RECORD = 24


PROBE_C = r"""
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_recover.h"
#include "roothealth_write.h"


static const struct rh_write_backend_ops persistent_backend = {
	.persistent_undo = 1
};

static int operation_is(const struct rh_write_operation *op,
		enum rh_write_kind kind, uint64_t offset, size_t length)
{
	return op->kind == kind && op->offset == offset && op->length == length;
}

static int staged_chain(const struct rh_write_operation *ops, size_t first,
		size_t last)
{
	size_t i;
	for (i = first + 1; i <= last; ++i)
		if (memcmp(ops[i].before, ops[i - 1].after, ops[i].length))
			return -1;
	return 0;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_log_result result;
	uint64_t created, mft, mirror, index;
	size_t i;
	int rc;

	if (argc != 6)
		return 64;
	created = strtoull(argv[2], NULL, 0);
	(void)created;
	mft = strtoull(argv[3], NULL, 0);
	mirror = strtoull(argv[4], NULL, 0);
	index = strtoull(argv[5], NULL, 0);
	if (rh_writer_open(&writer, argv[1]) ||
		rh_writer_set_backend(&writer, &persistent_backend, NULL))
		return 65;
	rc = roothealth_log_replay_plan(argv[1], &writer, &result);
	printf("plan_rc=%d actions=%u redo=%u undo=%u restart=%u operations=%zu bytes=%" PRIu64 "\n",
		rc, result.actions_seen, result.redo_actions, result.undo_actions,
		result.restart_pages_planned, writer.operation_count,
		writer.planned_bytes);
	if (rc || result.actions_seen != 8 || result.redo_actions != 5 ||
		result.undo_actions != 3 || result.restart_pages_planned != 2 ||
		writer.operation_count != 10 || writer.planned_bytes != UINT64_C(34816)) {
		fprintf(stderr, "unexpected mutation-matrix summary\n");
		rh_writer_close(&writer);
		return 66;
	}
	if (!operation_is(&writer.operations[0], RH_WRITE_LOGFILE_REDO, mft, 1024) ||
		!operation_is(&writer.operations[1], RH_WRITE_LOGFILE_REDO, mirror, 1024)) {
		fprintf(stderr, "MFT primary/mirror or staged-before order failed\n");
		rh_writer_close(&writer);
		return 67;
	}
	for (i = 2; i < 8; ++i)
		if (!operation_is(&writer.operations[i], RH_WRITE_LOGFILE_REDO, index, 4096)) {
			fprintf(stderr, "INDX mutation %zu was not WAL-routed\n", i - 2);
			rh_writer_close(&writer);
			return 68;
		}
	if (staged_chain(writer.operations, 2, 7) ||
		writer.operations[8].kind != RH_WRITE_LOGFILE_RESTART ||
		writer.operations[9].kind != RH_WRITE_LOGFILE_RESTART) {
		fprintf(stderr, "INDX staged-before or restart ordering failed\n");
		rh_writer_close(&writer);
		return 69;
	}
	rh_writer_close(&writer);
	return 0;
}
"""


def require(condition: bool, message: str):
    if not condition:
        raise ValueError(message)


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command, description: str) -> str:
    completed = subprocess.run(
        [str(value) for value in command], text=True, capture_output=True
    )
    if completed.returncode:
        raise RuntimeError(
            f"{description} failed ({completed.returncode})\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout


def align8(value: int) -> int:
    return (value + 7) & ~7


def encode_action(
    *, this_lsn: int, previous_lsn: int, undo_lsn: int, transaction: int,
    redo_operation: int, undo_operation: int, lcn: int, target_vcn: int,
    cluster_index: int, record_offset: int, attribute_offset: int,
    attribute_flags: int, target_attribute: int, redo: bytes, undo: bytes,
) -> bytes:
    fixed = 88
    redo_at = fixed
    undo_at = align8(redo_at + len(redo)) if undo else 0
    end = undo_at + len(undo) if undo else redo_at + len(redo)
    size = align8(end)
    record = helper.encode_common_record(
        size, this_lsn, previous_lsn, undo_lsn, transaction
    )
    struct.pack_into("<H", record, 40, LOG_DELETING)
    struct.pack_into(
        "<HHHHHH", record, 48, redo_operation, undo_operation,
        redo_at - 48, len(redo), undo_at - 48 if undo else 0, len(undo),
    )
    struct.pack_into("<HH", record, 60, target_attribute, 1)
    struct.pack_into(
        "<HHHHQ", record, 64, record_offset, attribute_offset,
        cluster_index, attribute_flags, target_vcn,
    )
    struct.pack_into("<Q", record, 80, lcn)
    record[redo_at:redo_at + len(redo)] = redo
    if undo:
        record[undo_at:undo_at + len(undo)] = undo
    return bytes(record)


def encode_forget(this_lsn: int, previous_lsn: int) -> bytes:
    record = helper.encode_common_record(
        88, this_lsn, previous_lsn, previous_lsn, WINNER_TX
    )
    struct.pack_into("<HH", record, 48, FORGET, NOOP)
    return bytes(record)


def encode_open(this_lsn: int, previous_lsn: int, reference: int,
                key: int, attr_type: int, name_text: str,
                bytes_per_index: int) -> bytes:
    name = name_text.encode("utf-16le")
    size = align8(120 + len(name))
    record = helper.encode_common_record(
        size, this_lsn, previous_lsn, previous_lsn, WINNER_TX
    )
    struct.pack_into("<HHHHHH", record, 48, OPEN_NONRESIDENT, NOOP,
                     0x28, 40, 0x50 if name else 0, len(name))
    struct.pack_into("<H", record, 60, key)
    entry = bytearray(40)
    struct.pack_into("<III", entry, 0, 0xFFFFFFFF, bytes_per_index,
                     attr_type)
    entry[13] = int(bool(name))
    entry[14] = len(name) // 2
    struct.pack_into("<Q", entry, 16, reference)
    record[80:120] = entry
    if name:
        record[120:120 + len(name)] = name
    return bytes(record)


def find_attr(image, geometry, inode: int, attr_type: int):
    _, record = helper.read_mft_record(image, geometry, inode)
    for offset, kind, nonresident, length in helper.iter_attributes(record):
        if kind == attr_type and nonresident:
            return record, offset, length, helper.decode_mapping_pairs(record, offset)
    raise ValueError(f"inode {inode} has no nonresident 0x{attr_type:x}")


def lcn_for_vcn(runs, vcn: int) -> int:
    for run in runs:
        if run["vcn"] <= vcn < run["vcn"] + run["clusters"]:
            return run["lcn"] + vcn - run["vcn"]
    raise ValueError(f"unmapped VCN {vcn}")


def minimal_file_record(image, geometry) -> bytes:
    _, template = helper.read_mft_record(image, geometry, 24)
    record = bytearray(PAGE // 4)
    record[:48] = template[:48]
    usa_offset = helper.u16(template, 4)
    usa_count = helper.u16(template, 6)
    require(usa_offset == 48 and usa_count == 3, "fixture MFT USA geometry")
    record[usa_offset:usa_offset + usa_count * 2] = \
        template[usa_offset:usa_offset + usa_count * 2]
    record[:4] = b"FILE"
    struct.pack_into("<QHHHHIIQHHI", record, 8, 0, 1, 0, 56, 0,
                     64, PAGE // 4, 0, 0, 0, MFT_RECORD)
    struct.pack_into("<I", record, 56, AT_END)
    return bytes(record)


def materialize_initialized_target(image, geometry, target_lcn: int,
                                   cluster_index: int,
                                   with_created_attribute: bool):
    record = bytearray(minimal_file_record(image, geometry))
    struct.pack_into("<H", record, 22, 1)
    if with_created_attribute:
        record[56:80] = resident_data_attribute()
        struct.pack_into("<I", record, 80, AT_END)
        struct.pack_into("<I", record, 24, 88)
        struct.pack_into("<H", record, 40, 1)
    protected = mst_protect_record(record, helper.u16(record, 4), 0xE271)
    physical = target_lcn * PAGE + cluster_index * 512
    image.seek(physical)
    require(image.write(protected) == len(protected),
            "materialize initialized target record")
    _, _, _, bitmap_runs = find_attr(image, geometry, 0, AT_BITMAP)
    bitmap_byte = MFT_RECORD >> 3
    observed = helper.stream_read(image, bitmap_runs, PAGE, bitmap_byte, 1)[0]
    require(not observed & (1 << (MFT_RECORD & 7)),
            "target MFT bitmap bit starts free")
    helper.stream_write(
        image, bitmap_runs, PAGE, bitmap_byte,
        bytes((observed | (1 << (MFT_RECORD & 7)),)),
    )


def resident_data_attribute() -> bytes:
    attr = bytearray(24)
    struct.pack_into("<IIBBHHH", attr, 0, AT_DATA, 24, 0, 0, 0, 0, 0)
    struct.pack_into("<IHBb", attr, 16, 0, 24, 0, 0)
    return bytes(attr)


def mst_protect_record(record: bytes, usa_offset: int, usn: int) -> bytes:
    """Apply NTFS MST fixups to one 1 KiB FILE record."""
    protected = bytearray(record)
    require(len(protected) == PAGE // 4, "one-kibibyte FILE record")
    usa_count = helper.u16(protected, 6)
    require(usa_count == len(protected) // 512 + 1, "FILE USA count")
    require(usa_offset >= 8 and usa_offset + usa_count * 2 <= len(protected),
            "FILE USA bounds")
    struct.pack_into("<H", protected, usa_offset, usn)
    for sector in range(1, usa_count):
        tail = sector * 512 - 2
        protected[usa_offset + sector * 2:usa_offset + sector * 2 + 2] = \
            protected[tail:tail + 2]
        struct.pack_into("<H", protected, tail, usn)
    return bytes(protected)


def synthetic_index_owner(image, geometry, target_lcn: int) -> int:
    _, unprotected = helper.read_mft_record(
        image, geometry, INDEX_OWNER_RECORD
    )
    record = bytearray(unprotected)
    usa_offset = helper.u16(record, 4)
    usa_count = helper.u16(record, 6)
    require(usa_count == 3, "synthetic owner FILE USA count")
    old_bytes_in_use = helper.u32(record, 24)
    require(old_bytes_in_use >= 8 and
            helper.u32(record, old_bytes_in_use - 8) == AT_END,
            "synthetic owner has an attribute terminator")
    attr = old_bytes_in_use - 8
    require(attr + 224 <= len(record), "synthetic owner has attribute space")
    instance = helper.u16(record, 40)
    # libntfs resolves an INDEX_ALLOCATION only when its matching INDEX_ROOT
    # exists.  Clone the valid $O root value, but give both new attributes a
    # private $TEST name so the physical run can be controlled exactly.
    source_root = 0x100
    require(helper.u32(record, source_root) == 0x90 and
            record[source_root + 8] == 0,
            "synthetic owner source INDEX_ROOT")
    root_value_length = helper.u32(record, source_root + 16)
    root_value_at = helper.u16(record, source_root + 20)
    require(root_value_length == 88 and
            root_value_at + root_value_length <=
            helper.u32(record, source_root + 4),
            "synthetic owner INDEX_ROOT value")
    struct.pack_into("<IIBBHHH", record, attr, 0x90, 128, 0, 5, 24, 0,
                     instance)
    struct.pack_into("<IHBb", record, attr + 16, root_value_length, 40, 0, 0)
    record[attr + 24:attr + 34] = "$TEST".encode("utf-16le")
    record[attr + 40:attr + 40 + root_value_length] = \
        record[source_root + root_value_at:
               source_root + root_value_at + root_value_length]
    allocation = attr + 128
    struct.pack_into("<IIBBHHH", record, allocation,
                     0xA0, 88, 1, 5, 64, 0, instance + 1)
    struct.pack_into("<QQH", record, allocation + 16, 0, 0, 80)
    struct.pack_into("<QQQ", record, allocation + 40, PAGE, PAGE, PAGE)
    record[allocation + 64:allocation + 74] = "$TEST".encode("utf-16le")
    require(target_lcn < 0x8000, "two-byte positive mapping delta")
    record[allocation + 80:allocation + 84] = bytes((0x21, 1)) + \
        target_lcn.to_bytes(2, "little")
    record[allocation + 84] = 0
    struct.pack_into("<I", record, allocation + 88, AT_END)
    struct.pack_into("<I", record, 24, old_bytes_in_use + 216)
    struct.pack_into("<H", record, 40, instance + 2)
    usn = (helper.u16(record, usa_offset) + 1) & 0xFFFF or 1
    protected = mst_protect_record(record, usa_offset, usn)
    target_byte = INDEX_OWNER_RECORD * geometry["mft_record_size"]
    owner_lcn = geometry["mft_lcn"] + target_byte // PAGE
    owner_at = target_byte % PAGE
    image.seek(owner_lcn * PAGE)
    cluster = bytearray(image.read(PAGE))
    cluster[owner_at:owner_at + PAGE // 4] = protected
    image.seek(owner_lcn * PAGE)
    require(image.write(cluster) == PAGE, "write synthetic index owner")
    return (1 << 48) | INDEX_OWNER_RECORD


def tamper_index_owner_mapping(path: Path):
    """Move only the owner runlist, leaving logged LCNs unchanged."""
    with path.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        _, unprotected = helper.read_mft_record(
            image, geometry, INDEX_OWNER_RECORD
        )
        record = bytearray(unprotected)
        allocation = None
        for offset, kind, nonresident, _ in helper.iter_attributes(record):
            if kind == 0xA0 and nonresident and record[offset + 9] == 5:
                name_at = helper.u16(record, offset + 10)
                if bytes(record[offset + name_at:offset + name_at + 10]) == \
                        "$TEST".encode("utf-16le"):
                    allocation = offset
                    break
        require(allocation is not None, "tamper target INDEX_ALLOCATION")
        mapping_at = helper.u16(record, allocation + 32)
        require(record[allocation + mapping_at] == 0x21 and
                record[allocation + mapping_at + 1] == 1,
                "tamper target direct one-cluster mapping")
        delta_at = allocation + mapping_at + 2
        delta = int.from_bytes(record[delta_at:delta_at + 2],
                               "little", signed=True)
        require(0 < delta < 0x7FFE, "tamper target positive mapping delta")
        record[delta_at:delta_at + 2] = (delta + 1).to_bytes(
            2, "little", signed=True
        )
        usa_offset = helper.u16(record, 4)
        usn = (helper.u16(record, usa_offset) + 1) & 0xFFFF or 1
        protected = mst_protect_record(record, usa_offset, usn)
        target_byte = INDEX_OWNER_RECORD * geometry["mft_record_size"]
        image.seek(geometry["mft_lcn"] * PAGE + target_byte)
        require(image.write(protected) == len(protected),
                "write tampered synthetic owner")
        image.flush()
        os.fsync(image.fileno())


def tamper_last_undo_link(path: Path, record_offset: int):
    with path.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        _, runs = helper.find_logfile(image, geometry)
        raw = helper.stream_read(image, runs, PAGE, TARGET_PAGE * PAGE, PAGE)
        page = helper.mst_unprotect(raw, PAGE)
        require(record_offset + 24 <= PAGE, "undo-link tamper record bound")
        struct.pack_into("<Q", page, record_offset + 16, 0)
        usa_offset = helper.u16(page, 4)
        usn = (helper.u16(page, usa_offset) + 1) & 0xFFFF or 1
        protected = helper.mst_protect(page, usa_offset, usn)
        helper.stream_write(image, runs, PAGE, TARGET_PAGE * PAGE, protected)
        image.flush()
        os.fsync(image.fileno())


def tamper_target_attribute(path: Path, record_offset: int, target: int):
    """Retarget one cached physical action to an unrelated open attribute."""
    with path.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        _, runs = helper.find_logfile(image, geometry)
        raw = helper.stream_read(image, runs, PAGE, TARGET_PAGE * PAGE, PAGE)
        page = helper.mst_unprotect(raw, PAGE)
        require(record_offset + 62 <= PAGE,
                "target-attribute tamper record bound")
        struct.pack_into("<H", page, record_offset + 60, target)
        usa_offset = helper.u16(page, 4)
        usn = (helper.u16(page, usa_offset) + 1) & 0xFFFF or 1
        protected = helper.mst_protect(page, usa_offset, usn)
        helper.stream_write(image, runs, PAGE, TARGET_PAGE * PAGE, protected)
        image.flush()
        os.fsync(image.fileno())


def build_index_fixture(image, geometry, logfile_runs):
    _, source_lcn, _, _ = multi.find_index_block(image, geometry)
    excluded = {source_lcn}
    for run in logfile_runs:
        excluded.update(range(run["lcn"], run["lcn"] + run["clusters"]))
    target_lcn, _ = multi.choose_free_clusters(image, geometry, excluded)
    image.seek(source_lcn * PAGE)
    index = helper.mst_unprotect(image.read(PAGE), PAGE)
    require(index[:4] == b"INDX", "source INDX magic")
    entries_offset = helper.u32(index, 24)
    entries_at = 24 + entries_offset
    require(64 <= entries_at <= PAGE - 48 and not (entries_at & 7),
            "bounded INDX entry offset")
    index[entries_at:] = bytes(PAGE - entries_at)
    end = bytearray(24)
    struct.pack_into("<HH", end, 8, 24, 0)
    struct.pack_into("<H", end, 12, 3)  # END | NODE
    struct.pack_into("<Q", end, 16, 7)
    index[entries_at:entries_at + 24] = end
    struct.pack_into("<I", index, 28, entries_offset + 24)
    usa_offset = helper.u16(index, 4)
    usn = (helper.u16(index, usa_offset) + 1) & 0xFFFF or 1
    protected = helper.mst_protect(index, usa_offset, usn)
    image.seek(target_lcn * PAGE)
    require(image.write(protected) == PAGE, "write custom INDX page")
    inserted = bytearray(24)
    struct.pack_into("<HHI", inserted, 0, 16, 8, 0)
    struct.pack_into("<HHHH", inserted, 8, 24, 0, 0, 0)
    inserted[16:24] = b"ENTRYOLD"
    reference = synthetic_index_owner(image, geometry, target_lcn)
    return target_lcn, entries_at, bytes(inserted), bytes(end[16:24]), reference


def build(base: Path, fixture: Path, manifest_path: Path,
          include_initialize: bool = True, include_create: bool = True):
    require(base.resolve() != fixture.resolve(), "base and fixture differ")
    require(not fixture.exists(), f"refusing to overwrite {fixture}")
    shutil.copyfile(base, fixture)
    with fixture.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        logfile_size, logfile_runs = helper.find_logfile(image, geometry)
        require(helper.stream_read(image, logfile_runs, PAGE, 0, 7 * PAGE) ==
                b"\xff" * (7 * PAGE), "wiped logfile seed")
        mft_record, mft_attr, _, mft_runs = find_attr(
            image, geometry, 0, AT_DATA
        )
        mft_reference = (helper.u16(mft_record, 16) << 48) | 0
        target_byte = MFT_RECORD * geometry["mft_record_size"]
        target_vcn = target_byte // PAGE
        cluster_index = (target_byte % PAGE) // 512
        target_lcn = lcn_for_vcn(mft_runs, target_vcn)
        image.seek(target_lcn * PAGE + cluster_index * 512)
        require(image.read(geometry["mft_record_size"]) ==
                bytes(geometry["mft_record_size"]), "blank MFT target")
        if not include_initialize:
            materialize_initialized_target(
                image, geometry, target_lcn, cluster_index,
                with_created_attribute=not include_create,
            )
        mft_cluster_lcn = lcn_for_vcn(mft_runs, 0)
        image.seek(0)
        mftmirr_lcn = helper.u64(image.read(512), 56)

        logfile_record, logfile_attr, logfile_attr_length, _ = find_attr(
            image, geometry, 2, AT_DATA
        )
        mapping_at = helper.u16(logfile_record, logfile_attr + 32)
        mapping_length = min(8, logfile_attr_length - mapping_at)
        require(mapping_length == 8, "eight-byte mapping qualification slice")
        mapping = bytes(logfile_record[
            logfile_attr + mapping_at:logfile_attr + mapping_at + mapping_length
        ])
        old_sizes = bytes(logfile_record[logfile_attr + 40:logfile_attr + 64])
        new_sizes = bytearray(old_sizes)
        initialized = helper.u64(old_sizes, 16)
        require(initialized >= PAGE, "$LogFile initialized size")
        struct.pack_into("<Q", new_sizes, 16, initialized - PAGE)

        index_lcn, entries_at, inserted, old_vcn, index_reference = build_index_fixture(
            image, geometry, logfile_runs
        )
        new_vcn = struct.pack("<Q", helper.u64(old_vcn, 0) + 1)

        sequence_bits = 67 - logfile_size.bit_length()
        specs = []
        if include_initialize:
            specs.append(
                (INITIALIZE_MFT, NOOP, target_lcn, target_vcn, cluster_index,
                 0, 0, ACTS_ON_MFT, MFT_ATTRIBUTE,
                 minimal_file_record(image, geometry), b"")
            )
        if include_create:
            specs.append(
                (CREATE_ATTRIBUTE, DELETE_ATTRIBUTE, target_lcn, target_vcn,
                 cluster_index, 56, 0, ACTS_ON_MFT, MFT_ATTRIBUTE,
                 resident_data_attribute(), b"")
            )
        specs.extend([
            (UPDATE_MAPPING, UPDATE_MAPPING, mft_cluster_lcn, 0, 4,
             logfile_attr, mapping_at, ACTS_ON_MFT, MFT_ATTRIBUTE,
             mapping, mapping),
            (SET_SIZES, SET_SIZES, mft_cluster_lcn, 0, 4,
             logfile_attr, 0, ACTS_ON_MFT, MFT_ATTRIBUTE,
             bytes(new_sizes), old_sizes),
        ])
        loser_specs = [
            (ADD_INDEX_ALLOCATION, DELETE_INDEX_ALLOCATION,
             entries_at, inserted, b""),
            (SET_VCN_ALLOCATION, SET_VCN_ALLOCATION,
             entries_at + 24, new_vcn, old_vcn),
            (UPDATE_RECORD_DATA_ALLOCATION, UPDATE_RECORD_DATA_ALLOCATION,
             entries_at, b"ENTRYNEW", b"ENTRYOLD"),
        ]

        sizes = [136, 120]
        for _, _, _, _, _, _, _, _, _, redo, undo in specs:
            sizes.append(align8(88 + len(redo) + (align8(len(redo)) - len(redo)) + len(undo)))
        sizes.append(88)
        for _, _, _, redo, undo in loser_specs:
            sizes.append(align8(88 + len(redo) + (align8(len(redo)) - len(redo)) + len(undo)))
        offsets = []
        cursor = DATA_OFFSET
        for size in sizes:
            offsets.append(cursor)
            cursor += size
        require(cursor <= PAGE, "matrix records fit one RCRD page")
        lsns = [helper.make_lsn(sequence_bits, TARGET_PAGE, value)
                for value in offsets]

        actions = [
            encode_open(lsns[0], 0, index_reference, INDEX_ATTRIBUTE,
                        0xA0, "$TEST", PAGE),
            encode_open(lsns[1], lsns[0], mft_reference, MFT_ATTRIBUTE,
                        AT_DATA, "", 0),
        ]
        previous = lsns[1]
        for index, spec in enumerate(specs, start=2):
            rop, uop, lcn, vcn, cindex, roff, aoff, aflags, target_attr, \
                redo, undo = spec
            actions.append(encode_action(
                this_lsn=lsns[index], previous_lsn=previous,
                undo_lsn=previous, transaction=WINNER_TX,
                redo_operation=rop, undo_operation=uop, lcn=lcn,
                target_vcn=vcn, cluster_index=cindex,
                record_offset=roff, attribute_offset=aoff,
                attribute_flags=aflags, target_attribute=target_attr,
                redo=redo, undo=undo,
            ))
            previous = lsns[index]
        forget_index = 2 + len(specs)
        actions.append(encode_forget(lsns[forget_index], previous))
        previous = 0
        for position, spec in enumerate(loser_specs, start=forget_index + 1):
            rop, uop, aoff, redo, undo = spec
            actions.append(encode_action(
                this_lsn=lsns[position], previous_lsn=previous,
                undo_lsn=previous, transaction=LOSER_TX,
                redo_operation=rop, undo_operation=uop, lcn=index_lcn,
                target_vcn=0, cluster_index=0, record_offset=0,
                attribute_offset=aoff, attribute_flags=ACTS_ON_INDX,
                target_attribute=INDEX_ATTRIBUTE, redo=redo, undo=undo,
            ))
            previous = lsns[position]
        records = b"".join(actions)
        require([len(action) for action in actions] == sizes,
                "exact encoded action sizes")
        pages = {
            0: helper.encode_restart_page(
                lsns[-1], lsns[0], lsns[forget_index], logfile_size,
                sequence_bits, 0xE001,
            ),
            1: helper.encode_restart_page(
                lsns[-1], lsns[0], lsns[forget_index], logfile_size,
                sequence_bits, 0xE002,
            ),
            2: helper.encode_record_page(
                2, TARGET_PAGE * PAGE, lsns[0], DATA_OFFSET, usn=0xE100,
            ),
            3: helper.encode_record_page(
                3, TARGET_PAGE * PAGE, lsns[0] - 1, DATA_OFFSET, usn=0xE100,
            ),
            PREVIOUS_PAGE: helper.encode_record_page(
                PREVIOUS_PAGE, lsns[0] - 1, lsns[0] - 1,
                PAGE - 16, usn=0xE100,
            ),
            TARGET_PAGE: helper.encode_record_page(
                TARGET_PAGE, lsns[-1], lsns[-1], DATA_OFFSET + len(records),
                records=records, usn=0xE100,
            ),
        }
        for number, page in pages.items():
            helper.stream_write(image, logfile_runs, PAGE, number * PAGE, page)
        image.flush()
        os.fsync(image.fileno())

    manifest = {
        "format": "roothealth-native-logfile-mutation-matrix-v1",
        "actions": len(actions) - 1,
        "winner_mutations": (
            ["InitializeFileRecordSegment"] if include_initialize else []
        ) + (["CreateAttribute"] if include_create else []) +
        ["UpdateMappingPairs", "SetNewAttributeSizes"],
        "include_initialize": include_initialize,
        "include_create": include_create,
        "loser_mutations": [
            "AddIndexEntryAllocation", "SetIndexEntryVcnAllocation",
            "UpdateRecordDataAllocation",
        ],
        "created_offset": target_lcn * PAGE,
        "mft_offset": mft_cluster_lcn * PAGE + 2 * geometry["mft_record_size"],
        "mirror_offset": mftmirr_lcn * PAGE + 2 * geometry["mft_record_size"],
        "index_offset": index_lcn * PAGE,
        "record_offsets": offsets,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def compile_probe(tree: Path, work: Path, cc: str) -> Path:
    source = work / "mutation_matrix_probe.c"
    source.write_text(PROBE_C.lstrip())
    common = [
        cc, "-std=c11", "-D_GNU_SOURCE", "-D_FORTIFY_SOURCE=3",
        "-DHAVE_CONFIG_H", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
        f"-I{tree}", f"-I{tree / 'include'}", f"-I{tree / 'libntfs'}",
        f"-I{tree / 'src'}",
    ]
    objects = []
    for name in (
        "roothealth_replay_guard", "roothealth_replay_analysis",
        "roothealth_recover", "roothealth_playlog", "roothealth_write",
    ):
        obj = work / f"{name}.o"
        run(common + ["-Wno-address-of-packed-member", "-c",
                      tree / "src" / f"{name}.c", "-o", obj],
            f"strict compile {name}")
        objects.append(obj)
    probe = work / "mutation-matrix-probe"
    run(common + [source, *objects, tree / "src" / "utils.o",
                  tree / "libntfs" / ".libs" / "libntfs.a", "-o", probe],
        "mutation matrix probe link")
    return probe


def self_test(tree: Path, cc: str, work_dir: Path | None):
    context = tempfile.TemporaryDirectory(prefix="roothealth-native-matrix.")
    work = work_dir.resolve() if work_dir else Path(context.name)
    if work_dir:
        require(not work.exists() or not any(work.iterdir()),
                "work directory must be empty")
        work.mkdir(parents=True, exist_ok=True)
    base = work / "base.img"
    fixture = work / "mutation-matrix.img"
    manifest_path = work / "mutation-matrix.json"
    initialize_blocker = work / "initialize-blocker.img"
    initialize_manifest = work / "initialize-blocker.json"
    create_blocker = work / "create-blocker.img"
    create_manifest = work / "create-blocker.json"
    with base.open("wb") as image:
        image.truncate(64 * 1024 * 1024)
    run([tree / "src" / "mkntfs", "-F", "-q", "-T", "-L", "RHREDO", base],
        "mkntfs fixture base")
    manifest = build(
        base, fixture, manifest_path,
        include_initialize=False, include_create=False,
    )
    before = file_sha(fixture)
    probe = compile_probe(tree, work, cc)
    output = run([
        probe, fixture, manifest["created_offset"], manifest["mft_offset"],
        manifest["mirror_offset"], manifest["index_offset"],
    ], "mutation matrix plan-only probe")
    after = file_sha(fixture)
    require(before == after, "parser modified mutation matrix image")
    blocker_manifest = build(
        base, initialize_blocker, initialize_manifest, include_initialize=True
    )
    blocker_before = file_sha(initialize_blocker)
    blocked = subprocess.run([
        str(probe), str(initialize_blocker), str(blocker_manifest["created_offset"]),
        str(blocker_manifest["mft_offset"]), str(blocker_manifest["mirror_offset"]),
        str(blocker_manifest["index_offset"]),
    ], text=True, capture_output=True)
    require(
        blocked.returncode == 66
        and "plan_rc=-1" in blocked.stdout
        and "operations=0" in blocked.stdout,
        "InitializeFileRecordSegment blocker was not a zero-plan refusal",
    )
    require(file_sha(initialize_blocker) == blocker_before,
            "InitializeFileRecordSegment refusal changed source image")
    create_blocker_manifest = build(
        base, create_blocker, create_manifest,
        include_initialize=False, include_create=True,
    )
    create_before = file_sha(create_blocker)
    blocked_create = subprocess.run([
        str(probe), str(create_blocker),
        str(create_blocker_manifest["created_offset"]),
        str(create_blocker_manifest["mft_offset"]),
        str(create_blocker_manifest["mirror_offset"]),
        str(create_blocker_manifest["index_offset"]),
    ], text=True, capture_output=True)
    require(
        blocked_create.returncode == 66
        and "plan_rc=-1" in blocked_create.stdout
        and "operations=0" in blocked_create.stdout,
        "CreateAttribute blocker was not a zero-plan refusal",
    )
    require(file_sha(create_blocker) == create_before,
            "CreateAttribute refusal changed source image")
    mismatch = work / "mapping-mismatch.img"
    shutil.copyfile(fixture, mismatch)
    tamper_index_owner_mapping(mismatch)
    mismatch_before = file_sha(mismatch)
    rejected = subprocess.run([
        str(probe), str(mismatch), str(manifest["created_offset"]),
        str(manifest["mft_offset"]), str(manifest["mirror_offset"]),
        str(manifest["index_offset"]),
    ], text=True, capture_output=True)
    require(rejected.returncode == 66 and "plan_rc=-1" in rejected.stdout and
            "operations=0" in rejected.stdout,
            "owner-runlist/logged-LCN mismatch was not rejected")
    require(file_sha(mismatch) == mismatch_before,
            "rejected mapping mismatch image changed")
    wrong_owner = work / "cached-target-attribute-mismatch.img"
    shutil.copyfile(fixture, wrong_owner)
    tamper_target_attribute(wrong_owner, manifest["record_offsets"][3],
                            INDEX_ATTRIBUTE)
    wrong_owner_before = file_sha(wrong_owner)
    rejected = subprocess.run([
        str(probe), str(wrong_owner), str(manifest["created_offset"]),
        str(manifest["mft_offset"]), str(manifest["mirror_offset"]),
        str(manifest["index_offset"]),
    ], text=True, capture_output=True)
    require(rejected.returncode == 66 and "plan_rc=-1" in rejected.stdout and
            "operations=0" in rejected.stdout,
            "cached MFT target-attribute mismatch was not rejected")
    require(file_sha(wrong_owner) == wrong_owner_before,
            "rejected target-attribute mismatch image changed")
    skipped = work / "undo-chain-skip.img"
    shutil.copyfile(fixture, skipped)
    tamper_last_undo_link(skipped, manifest["record_offsets"][-1])
    skipped_before = file_sha(skipped)
    rejected = subprocess.run([
        str(probe), str(skipped), str(manifest["created_offset"]),
        str(manifest["mft_offset"]), str(manifest["mirror_offset"]),
        str(manifest["index_offset"]),
    ], text=True, capture_output=True)
    require(rejected.returncode == 66 and "plan_rc=-1" in rejected.stdout and
            "operations=0" in rejected.stdout,
            "active transaction with a skipped undo link was not rejected")
    require(file_sha(skipped) == skipped_before,
            "rejected undo-chain image changed")
    print(output, end="")
    print(json.dumps({
        "result": "PASS", "actions": 8, "redo": 5, "undo": 3,
        "mutation_pair_rows": 5, "typed_operations": 10,
        "persistent_undo_backend": True,
        "negative_mapping_tests": [
            "owner-runlist-lcn-mismatch",
            "cached-mft-target-attribute-mismatch",
        ],
        "negative_transaction_tests": ["active-undo-chain-skip"],
        "blocked_unqualified_actions": [
            "InitializeFileRecordSegment", "CreateAttribute",
        ],
        "blocked_unqualified_plan_operations": 0,
        "fixture_sha256_before": before,
        "fixture_sha256_after": after,
        "work_directory": str(work),
    }, sort_keys=True))
    if not work_dir:
        context.cleanup()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("self-test",))
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args()
    self_test(args.tree.resolve(), args.cc, args.work_dir)


if __name__ == "__main__":
    raise SystemExit(main())
