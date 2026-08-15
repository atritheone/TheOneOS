#!/usr/bin/env python3
"""Qualify ordinary NTFS root-index, view-index, and MFT-tail log actions."""

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
TX = 24
NOOP = 0
WRITE_END_MFT = 4
ADD_ROOT = 12
DELETE_ROOT = 13
SET_VCN_ROOT = 17
UPDATE_FILENAME_ROOT = 19
UPDATE_FILENAME_ALLOCATION = 20
SET_BITS = 21
CLEAR_BITS = 22
FORGET = 27
OPEN_NONRESIDENT = 28
UPDATE_RECORD_ROOT = 33
ZERO_END_MFT = 37
ACTS_ON_MFT = 2
ACTS_ON_INDX = 8
MFT_KEY = 24
I30_KEY = 64
BITMAP_KEY = 104
AT_DATA = 0x80
AT_INDEX_ROOT = 0x90
AT_INDEX_ALLOCATION = 0xA0


PROBE_C = r"""
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "roothealth_recover.h"
#include "roothealth_write.h"

static const struct rh_write_backend_ops persistent_backend = {
	.persistent_undo = 1
};

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_log_result result;
	size_t i;
	int rc;

	if (argc != 2)
		return 64;
	if (rh_writer_open(&writer, argv[1]) ||
		rh_writer_set_backend(&writer, &persistent_backend, NULL))
		return 65;
	rc = roothealth_log_replay_plan(argv[1], &writer, &result);
	printf("plan_rc=%d state=%d checked=%d actions=%u control=%u mutation=%u "
		"redo=%u undo=%u restart=%u unsupported=%u io_errors=%u "
		"parse_errors=%u operations=%zu bytes=%" PRIu64 "\n",
		rc, (int)result.state, result.checked, result.actions_seen,
		result.control_records_examined, result.mutation_records_examined,
		result.redo_actions, result.undo_actions,
		result.restart_pages_planned, result.unsupported_actions,
		result.io_errors, result.parse_errors, writer.operation_count,
		writer.planned_bytes);
	if (rc || result.state != RH_NATIVE_LOG_REPLAY_PLANNED || !result.checked ||
		result.actions_seen != 13 || result.control_records_examined != 4 ||
		result.mutation_records_examined != 9 || result.redo_actions != 9 ||
		result.undo_actions || result.restart_pages_planned != 2 ||
		result.unsupported_actions || result.io_errors || result.parse_errors ||
		result.planned_io_operations != 10 ||
		result.planned_io_bytes != UINT64_C(22528) ||
		writer.operation_count != 10 || writer.planned_bytes != UINT64_C(22528)) {
		fprintf(stderr, "unexpected common-op summary\n");
		rh_writer_close(&writer);
		return 66;
	}
	for (i = 0; i < 8; ++i)
		if (writer.operations[i].kind != RH_WRITE_LOGFILE_REDO ||
			(writer.operations[i].length != 1024 &&
			 writer.operations[i].length != 4096)) {
			fprintf(stderr, "mutation %zu was not a full MFT-record/cluster WAL action\n", i);
			rh_writer_close(&writer);
			return 67;
		}
	if (writer.operations[8].kind != RH_WRITE_LOGFILE_RESTART ||
		writer.operations[9].kind != RH_WRITE_LOGFILE_RESTART) {
		fprintf(stderr, "restart actions were not ordered last\n");
		rh_writer_close(&writer);
		return 68;
	}
	rh_writer_close(&writer);
	return 0;
}
"""


def require(condition: bool, message: str):
    if not condition:
        raise ValueError(message)


def align8(value: int) -> int:
    return (value + 7) & ~7


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


def find_attr(record: bytes, attr_type: int, name: str, resident: bool):
    for offset, kind, nonresident, length in helper.iter_attributes(record):
        name_length = record[offset + 9]
        name_offset = helper.u16(record, offset + 10)
        found_name = bytes(record[
            offset + name_offset:offset + name_offset + name_length * 2
        ]).decode("utf-16le") if name_length else ""
        if kind == attr_type and found_name == name and nonresident != resident:
            return offset, length
    raise ValueError(f"missing attribute 0x{attr_type:x}:{name}")


def lcn_for_vcn(runs, vcn: int) -> int:
    for run in runs:
        if run["vcn"] <= vcn < run["vcn"] + run["clusters"]:
            return run["lcn"] + vcn - run["vcn"]
    raise ValueError(f"unmapped VCN {vcn}")


def mft_target(geometry, mft_runs, record_number: int):
    byte_offset = record_number * geometry["mft_record_size"]
    vcn = byte_offset // PAGE
    within = byte_offset % PAGE
    require(within % geometry["mft_record_size"] == 0,
            "MFT record boundary")
    return lcn_for_vcn(mft_runs, vcn), vcn, within // 512


def index_entries(record: bytes, attr_offset: int):
    value_length = helper.u32(record, attr_offset + 16)
    value_offset = helper.u16(record, attr_offset + 20)
    root = attr_offset + value_offset
    header = root + 16
    cursor = header + helper.u32(record, header)
    end = header + helper.u32(record, header + 4)
    require(value_length == 16 + helper.u32(record, header + 4),
            "INDEX_ROOT exact value length")
    entries = []
    while cursor < end:
        length = helper.u16(record, cursor + 8)
        require(length >= 16 and not length % 8 and cursor + length <= end,
                "INDEX_ROOT entry bounds")
        entries.append((cursor, length, helper.u16(record, cursor + 12)))
        cursor += length
    require(cursor == end and entries and entries[-1][2] & 2,
            "INDEX_ROOT terminator")
    return entries


def filename_entry() -> bytes:
    entry = bytearray(88)
    struct.pack_into("<QHHHH", entry, 0, (1 << 48), 88, 68, 0, 0)
    struct.pack_into("<Q", entry, 16, (5 << 48) | 5)
    entry[80] = 1
    entry[81] = 1
    entry[82:84] = "X".encode("utf-16le")
    return bytes(entry)


def encode_open(this_lsn: int, previous_lsn: int, key: int,
                reference: int, attr_type: int, name: str,
                bytes_per_index: int) -> bytes:
    name_bytes = name.encode("utf-16le")
    size = align8(120 + len(name_bytes))
    record = helper.encode_common_record(
        size, this_lsn, previous_lsn, previous_lsn, TX
    )
    struct.pack_into("<HHHHHH", record, 48, OPEN_NONRESIDENT, NOOP,
                     0x28, 40, 0x50 if name_bytes else 0, len(name_bytes))
    struct.pack_into("<H", record, 60, key)
    entry = bytearray(40)
    struct.pack_into("<III", entry, 0, 0xFFFFFFFF, bytes_per_index,
                     attr_type)
    entry[13] = int(bool(name_bytes))
    entry[14] = len(name_bytes) // 2
    struct.pack_into("<Q", entry, 16, reference)
    record[80:120] = entry
    record[120:120 + len(name_bytes)] = name_bytes
    return bytes(record)


def encode_action(*, this_lsn: int, previous_lsn: int, operation: int,
                  undo_operation: int, lcn: int, target_vcn: int,
                  cluster_index: int, record_offset: int,
                  attribute_offset: int, attribute_flags: int,
                  target_attribute: int, redo: bytes, undo: bytes) -> bytes:
    redo_at = 88
    undo_at = align8(redo_at + len(redo)) if undo else 0
    end = undo_at + len(undo) if undo else redo_at + len(redo)
    size = align8(end)
    record = helper.encode_common_record(
        size, this_lsn, previous_lsn, previous_lsn, TX
    )
    struct.pack_into("<H", record, 40, 2)
    struct.pack_into("<HHHHHH", record, 48, operation, undo_operation,
                     redo_at - 48 if redo else 0, len(redo),
                     undo_at - 48 if undo else 0, len(undo))
    struct.pack_into("<HH", record, 60, target_attribute, 1)
    struct.pack_into("<HHHHQ", record, 64, record_offset, attribute_offset,
                     cluster_index, attribute_flags, target_vcn)
    struct.pack_into("<Q", record, 80, lcn)
    record[redo_at:redo_at + len(redo)] = redo
    if undo:
        record[undo_at:undo_at + len(undo)] = undo
    return bytes(record)


def encode_forget(this_lsn: int, previous_lsn: int) -> bytes:
    record = helper.encode_common_record(
        88, this_lsn, previous_lsn, previous_lsn, TX
    )
    struct.pack_into("<HH", record, 48, FORGET, NOOP)
    return bytes(record)


def mutate_log_page(path: Path, page_number: int, mutate):
    with path.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        _, runs = helper.find_logfile(image, geometry)
        raw = helper.stream_read(image, runs, PAGE, page_number * PAGE, PAGE)
        page = helper.mst_unprotect(raw, PAGE)
        mutate(page)
        usa_offset = helper.u16(page, 4)
        usn = (helper.u16(page, usa_offset) + 1) & 0xFFFF or 1
        helper.stream_write(
            image, runs, PAGE, page_number * PAGE,
            helper.mst_protect(page, usa_offset, usn),
        )
        image.flush()
        os.fsync(image.fileno())


def build(base: Path, fixture: Path, manifest_path: Path):
    require(base.resolve() != fixture.resolve(), "base and fixture differ")
    require(not fixture.exists(), f"refusing to overwrite {fixture}")
    shutil.copyfile(base, fixture)
    with fixture.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        logfile_size, logfile_runs = helper.find_logfile(image, geometry)
        require(helper.stream_read(image, logfile_runs, PAGE, 0, 7 * PAGE) ==
                b"\xff" * (7 * PAGE), "wiped logfile seed")

        _, mft_record = helper.read_mft_record(image, geometry, 0)
        mft_attr, _ = find_attr(mft_record, AT_DATA, "", False)
        mft_runs = helper.decode_mapping_pairs(mft_record, mft_attr)
        mft_reference = (helper.u16(mft_record, 16) << 48)

        bitmap = multi.find_data_stream(image, geometry, 6, AT_DATA, "")
        bitmap_lcn = lcn_for_vcn(bitmap["runs"], 0)
        image.seek(bitmap_lcn * PAGE)
        bitmap_page = image.read(PAGE)
        require(len(bitmap_page) == PAGE, "$Bitmap first cluster")
        bitmap_bit = next(
            (bit for bit in range(fixture.stat().st_size // PAGE)
             if not (bitmap_page[bit // 8] & (1 << (bit & 7)))),
            None,
        )
        require(bitmap_bit is not None, "a clear in-volume $Bitmap bit")
        bitmap_payload = struct.pack("<II", bitmap_bit, 1)

        _, root_record = helper.read_mft_record(image, geometry, 5)
        root_attr, _ = find_attr(root_record, AT_INDEX_ROOT, "$I30", True)
        root_entries = index_entries(root_record, root_attr)
        end_at, end_length, end_flags = root_entries[-1]
        require(end_length == 24 and end_flags == 3,
                "large root has a node terminator")
        old_vcn = bytes(root_record[end_at + 16:end_at + 24])
        new_vcn = struct.pack("<Q", helper.u64(old_vcn, 0) + 1)
        inserted = filename_entry()
        modified = bytearray(inserted)
        modified[24] ^= 1
        root_lcn, root_vcn, root_cluster_index = mft_target(
            geometry, mft_runs, 5
        )

        _, view_record = helper.read_mft_record(image, geometry, 24)
        view_attr, _ = find_attr(view_record, AT_INDEX_ROOT, "$O", True)
        view_entries = index_entries(view_record, view_attr)
        view_entry, view_length, view_flags = view_entries[0]
        require(not view_flags and view_length >= 36 and
                helper.u16(view_record, view_entry) == 32 and
                helper.u16(view_record, view_entry + 2) >= 4,
                "view entry data window")
        old_view_data = bytes(view_record[view_entry + 32:view_entry + 36])
        new_view_data = bytearray(old_view_data)
        new_view_data[0] ^= 1
        view_lcn, view_vcn, view_cluster_index = mft_target(
            geometry, mft_runs, 24
        )
        view_used = helper.u32(view_record, 24)
        require(helper.u32(view_record, view_used - 8) == 0xFFFFFFFF,
                "view record terminator")
        terminator = bytes(view_record[view_used - 8:view_used])
        zero_length = geometry["mft_record_size"] - view_used
        require(zero_length > 0, "view record unused tail")

        i30 = multi.find_data_stream(
            image, geometry, 5, AT_INDEX_ALLOCATION, "$I30"
        )
        i30_lcn = lcn_for_vcn(i30["runs"], 0)
        image.seek(i30_lcn * PAGE)
        index = helper.mst_unprotect(image.read(PAGE), PAGE)
        cursor = 24 + helper.u32(index, 24)
        end = 24 + helper.u32(index, 28)
        filename_at = None
        while cursor < end:
            length = helper.u16(index, cursor + 8)
            flags = helper.u16(index, cursor + 12)
            key_length = helper.u16(index, cursor + 10)
            if not flags & 2 and key_length >= 66:
                filename_at = cursor
                break
            cursor += length
        require(filename_at is not None, "I30 allocation filename entry")
        old_allocation_dup = bytes(index[filename_at + 24:filename_at + 80])
        new_allocation_dup = bytearray(old_allocation_dup)
        new_allocation_dup[0] ^= 1

        sizes = [120, 128, 120, 176, 200, 104, 176, 104, 200, 104,
                 align8(88 + zero_length), 104, 88]
        offsets = []
        cursor = DATA_OFFSET
        for size in sizes:
            offsets.append(cursor)
            cursor += size
        require(cursor <= PAGE, "common-op records fit one RCRD page")
        sequence_bits = 67 - logfile_size.bit_length()
        lsns = [helper.make_lsn(sequence_bits, TARGET_PAGE, offset)
                for offset in offsets]

        actions = [
            encode_open(lsns[0], 0, MFT_KEY, mft_reference,
                        AT_DATA, "", 0),
            encode_open(lsns[1], lsns[0], I30_KEY, i30["reference"],
                        AT_INDEX_ALLOCATION, "$I30", PAGE),
            encode_open(lsns[2], lsns[1], BITMAP_KEY, bitmap["reference"],
                        AT_DATA, "", 0),
        ]
        previous = lsns[2]
        specs = [
            (ADD_ROOT, DELETE_ROOT, root_lcn, root_vcn, root_cluster_index,
             root_attr, end_at - root_attr, ACTS_ON_MFT, MFT_KEY,
             inserted, b""),
            (UPDATE_FILENAME_ROOT, UPDATE_FILENAME_ROOT, root_lcn, root_vcn,
             root_cluster_index, root_attr, end_at - root_attr,
             ACTS_ON_MFT, MFT_KEY, bytes(modified[24:80]),
             inserted[24:80]),
            (SET_VCN_ROOT, SET_VCN_ROOT, root_lcn, root_vcn,
             root_cluster_index, root_attr,
             end_at + len(inserted) - root_attr, ACTS_ON_MFT, MFT_KEY,
             new_vcn, old_vcn),
            (DELETE_ROOT, ADD_ROOT, root_lcn, root_vcn, root_cluster_index,
             root_attr, end_at - root_attr, ACTS_ON_MFT, MFT_KEY,
             b"", bytes(modified)),
            (UPDATE_RECORD_ROOT, UPDATE_RECORD_ROOT, view_lcn, view_vcn,
             view_cluster_index, view_attr, view_entry - view_attr,
             ACTS_ON_MFT, MFT_KEY, bytes(new_view_data), old_view_data),
            (UPDATE_FILENAME_ALLOCATION, UPDATE_FILENAME_ALLOCATION,
             i30_lcn, 0, 0, 0, filename_at, ACTS_ON_INDX, I30_KEY,
             bytes(new_allocation_dup), old_allocation_dup),
            (WRITE_END_MFT, WRITE_END_MFT, view_lcn, view_vcn,
             view_cluster_index, view_used - 8, 0, ACTS_ON_MFT, MFT_KEY,
             terminator, terminator),
            (ZERO_END_MFT, NOOP, view_lcn, view_vcn, view_cluster_index,
             view_used, 0, ACTS_ON_MFT, MFT_KEY,
             bytes(zero_length), b""),
            (SET_BITS, CLEAR_BITS, bitmap_lcn, 0, 0, 0, 0, 0,
             BITMAP_KEY, bitmap_payload, bitmap_payload),
        ]
        for index_no, spec in enumerate(specs, start=3):
            operation, undo_operation, lcn, target_vcn, cluster_index, \
                record_offset, attribute_offset, attribute_flags, \
                target_attribute, redo, undo = spec
            action = encode_action(
                this_lsn=lsns[index_no], previous_lsn=previous,
                operation=operation, undo_operation=undo_operation,
                lcn=lcn, target_vcn=target_vcn,
                cluster_index=cluster_index, record_offset=record_offset,
                attribute_offset=attribute_offset,
                attribute_flags=attribute_flags,
                target_attribute=target_attribute, redo=redo, undo=undo,
            )
            require(len(action) == sizes[index_no],
                    f"action {operation} exact size")
            actions.append(action)
            previous = lsns[index_no]
        actions.append(encode_forget(lsns[-1], previous))
        require(len(actions[-1]) == sizes[-1], "forget exact size")
        records = b"".join(actions)
        pages = {
            0: helper.encode_restart_page(
                lsns[-1], lsns[0], lsns[-1], logfile_size,
                sequence_bits, 0xC001,
            ),
            1: helper.encode_restart_page(
                lsns[-1], lsns[0], lsns[-1], logfile_size,
                sequence_bits, 0xC002,
            ),
            2: helper.encode_record_page(
                2, TARGET_PAGE * PAGE, lsns[0], DATA_OFFSET, usn=0xC100,
            ),
            3: helper.encode_record_page(
                3, TARGET_PAGE * PAGE, lsns[0] - 1, DATA_OFFSET, usn=0xC100,
            ),
            PREVIOUS_PAGE: helper.encode_record_page(
                PREVIOUS_PAGE, lsns[0] - 1, lsns[0] - 1,
                PAGE - 16, usn=0xC100,
            ),
            TARGET_PAGE: helper.encode_record_page(
                TARGET_PAGE, lsns[-1], lsns[-1], DATA_OFFSET + len(records),
                records=records, usn=0xC100,
            ),
        }
        for number, page in pages.items():
            helper.stream_write(image, logfile_runs, PAGE, number * PAGE, page)
        image.flush()
        os.fsync(image.fileno())

    manifest = {
        "format": "roothealth-native-common-ops-v1",
        "actions": 13,
        "mutations": [
            "AddIndexEntryRoot", "UpdateFileNameRoot",
            "SetIndexEntryVcnRoot", "DeleteIndexEntryRoot",
            "UpdateRecordDataRoot", "UpdateFileNameAllocation",
            "WriteEndOfFileRecordSegment", "ZeroEndOfFileRecord",
            "SetBitsInNonResidentBitMap",
        ],
        "bitmap_bit": bitmap_bit,
        "record_offsets": offsets,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def compile_probe(tree: Path, work: Path, cc: str) -> Path:
    source = work / "common_ops_probe.c"
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
    probe = work / "common-ops-probe"
    run(common + [source, *objects, tree / "src" / "utils.o",
                  tree / "libntfs" / ".libs" / "libntfs.a", "-o", probe],
        "common-op probe link")
    return probe


def self_test(tree: Path, cc: str, work_dir: Path | None):
    context = tempfile.TemporaryDirectory(prefix="roothealth-native-common.")
    work = work_dir.resolve() if work_dir else Path(context.name)
    if work_dir:
        require(not work.exists() or not any(work.iterdir()),
                "work directory must be empty")
        work.mkdir(parents=True, exist_ok=True)
    base = work / "base.img"
    fixture = work / "common-ops.img"
    manifest_path = work / "common-ops.json"
    with base.open("wb") as image:
        image.truncate(64 * 1024 * 1024)
    run([tree / "src" / "mkntfs", "-F", "-q", "-T", "-L", "RHREDO", base],
        "mkntfs fixture base")
    manifest = build(base, fixture, manifest_path)
    before = file_sha(fixture)
    probe = compile_probe(tree, work, cc)
    output = run([probe, fixture], "common-op plan-only probe")
    after = file_sha(fixture)
    require(before == after, "parser modified common-op image")

    negative_tests = []

    def reject(name: str, mutations, unsupported: bool = False):
        candidate = work / f"negative-{name}.img"
        shutil.copyfile(fixture, candidate)
        for page_number, mutate in mutations:
            mutate_log_page(candidate, page_number, mutate)
        candidate_before = file_sha(candidate)
        rejected = subprocess.run(
            [str(probe), str(candidate)], text=True, capture_output=True
        )
        require(rejected.returncode == 66 and "plan_rc=-1" in rejected.stdout and
                "operations=0" in rejected.stdout and
                ("unsupported=1" if unsupported else "unsupported=0")
                in rejected.stdout and
                ("parse_errors=0" if unsupported else "parse_errors=1")
                in rejected.stdout,
                f"negative {name} was not a whole-plan refusal")
        require(file_sha(candidate) == candidate_before,
                f"negative {name} modified its source image")
        negative_tests.append(name)

    first_mutation = manifest["record_offsets"][3]
    view_mutation = manifest["record_offsets"][7]
    # Opcode 3 now has its own qualified positive/negative fixture.  The
    # shipped-kernel-only 35/36 paths remain whole-plan fail-closed cases;
    # their exact support classification is source-audit evidence, not an
    # invented generic "unsupported" counter in this mutation fixture.
    for operation in (35, 36):
        reject(f"unqualified-op-{operation}", [
            (TARGET_PAGE, lambda page, op=operation: struct.pack_into(
                "<H", page, first_mutation + 48, op
            )),
        ])
    reject("root-entry-target-interior", [
        (TARGET_PAGE, lambda page: struct.pack_into(
            "<H", page, first_mutation + 66,
            struct.unpack_from("<H", page, first_mutation + 66)[0] + 8,
        )),
    ])
    reject("mft-record-half-boundary", [
        (TARGET_PAGE, lambda page: struct.pack_into(
            "<H", page, view_mutation + 68,
            struct.unpack_from("<H", page, view_mutation + 68)[0] + 1,
        )),
    ])
    # Multi-page RCRD is covered positively and with bounded negatives by the
    # dedicated v2 fixture; page_count=2 is no longer itself corruption.
    reject("rcrd-copy-lsn-mismatch", [
        (TARGET_PAGE, lambda page: struct.pack_into(
            "<Q", page, 8, struct.unpack_from("<Q", page, 8)[0] + 1,
        )),
    ])
    # Restart version 2 is a supported profile and has its own multipage
    # qualification fixture; changing only the version is not a corruption.
    print(output, end="")
    print(json.dumps({
        "result": "PASS", "actions": 13, "redo": 9,
        "mutation_pair_rows": 9, "typed_operations": 10,
        "source_image_unchanged": True,
        "negative_preflight_tests": negative_tests,
        "fixture_sha256_before": before,
        "fixture_sha256_after": after,
        "mutations": manifest["mutations"],
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
