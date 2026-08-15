#!/usr/bin/env python3
"""Deterministic native $LogFile checkpoint/table qualification fixture.

Builds a real NTFS image whose v1.1 log contains all four restart analysis
controls (open attributes, attribute names, dirty pages, transactions), one
client-restart checkpoint, and one committed resident MFT update.  The probe
calls only the plan API and proves the source image hash is unchanged.
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
HELPER_PATH = HERE / "native_logfile_redo_fixture.py"
SPEC = importlib.util.spec_from_file_location("roothealth_redo_helper", HELPER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {HELPER_PATH}")
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)

PAGE = 4096
DATA_OFFSET = 0x40
TARGET_PAGE = 5
PREVIOUS_PAGE = 4
CHECKPOINT_TX = 24
UPDATE_TX = 64
OPEN_TABLE_DUMP = 29
ATTRIBUTE_NAMES_DUMP = 30
DIRTY_PAGE_TABLE_DUMP = 31
TRANSACTION_TABLE_DUMP = 32
FORGET = 27
LOG_CHECKPOINT = 2
ACTS_ON_MFT = 2
TABLE_HEADER = 24
TABLE_ENTRY = 40
ALLOCATED = 0xFFFFFFFF


PROBE_C = r"""
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_recover.h"
#include "roothealth_write.h"

static int value_mismatch(const struct rh_write_operation *op, size_t at,
		const unsigned char before[2], const unsigned char after[2])
{
	return at > op->length || 2 > op->length - at ||
		memcmp(op->before + at, before, 2) ||
		memcmp(op->after + at, after, 2);
}

int main(int argc, char **argv)
{
	static const unsigned char before[2] = { 'R', 0 };
	static const unsigned char after[2] = { 'S', 0 };
	struct rh_writer writer;
	struct rh_log_result result;
	uint64_t primary, mirror;
	size_t value_at;
	int rc;

	if (argc == 2) {
		if (rh_writer_open(&writer, argv[1]))
			return 65;
		rc = roothealth_log_replay_plan(argv[1], &writer, &result);
		printf("windows_plan_rc=%d actions=%u checkpoints=%u controls=%u "
			"mutations=%u restart=%u operations=%zu bytes=%" PRIu64 "\n",
			rc, result.actions_seen, result.checkpoint_records_examined,
			result.control_records_examined, result.mutation_records_examined,
			result.restart_pages_planned, writer.operation_count,
			writer.planned_bytes);
		if (rc || result.actions_seen != 4 ||
			result.checkpoint_records_examined != 2 ||
			result.mutation_records_examined != 0 ||
			result.open_attribute_tables != 1 ||
			result.attribute_name_tables != 1 ||
			result.restart_pages_planned != 2 ||
			writer.operation_count != 2 || writer.planned_bytes != 8192 ||
			writer.operations[0].kind != RH_WRITE_LOGFILE_RESTART ||
			writer.operations[1].kind != RH_WRITE_LOGFILE_RESTART) {
			fprintf(stderr, "Windows control-only checkpoint was not proven\n");
			rh_writer_close(&writer);
			return 67;
		}
		rh_writer_close(&writer);
		return 0;
	}
	if (argc != 5)
		return 64;
	primary = strtoull(argv[2], NULL, 0);
	mirror = strtoull(argv[3], NULL, 0);
	value_at = (size_t)strtoull(argv[4], NULL, 0);
	if (rh_writer_open(&writer, argv[1]))
		return 65;
	rc = roothealth_log_replay_plan(argv[1], &writer, &result);
	printf("plan_rc=%d actions=%u redo=%u undo=%u restart=%u operations=%zu bytes=%" PRIu64 "\n",
		rc, result.actions_seen, result.redo_actions, result.undo_actions,
		result.restart_pages_planned, writer.operation_count,
		writer.planned_bytes);
	if (rc || result.actions_seen != 7 || result.redo_actions != 1 ||
		result.undo_actions != 0 || result.restart_pages_planned != 2 ||
		writer.operation_count != 4 || writer.planned_bytes != UINT64_C(10240) ||
		writer.operations[0].kind != RH_WRITE_LOGFILE_REDO ||
		writer.operations[0].offset != primary ||
		value_mismatch(&writer.operations[0], value_at, before, after) ||
		writer.operations[1].kind != RH_WRITE_LOGFILE_REDO ||
		writer.operations[1].offset != mirror ||
		value_mismatch(&writer.operations[1], value_at, before, after) ||
		writer.operations[2].kind != RH_WRITE_LOGFILE_RESTART ||
		writer.operations[3].kind != RH_WRITE_LOGFILE_RESTART) {
		fprintf(stderr, "checkpoint analysis plan was not proven\n");
		rh_writer_close(&writer);
		return 66;
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


def restart_table(entry: bytes, allocated: bool) -> bytes:
    require(len(entry) == TABLE_ENTRY, "restart-table entry size")
    table = bytearray(TABLE_HEADER + TABLE_ENTRY)
    struct.pack_into("<HHH", table, 0, TABLE_ENTRY, 1, int(allocated))
    if allocated:
        struct.pack_into("<II", table, 16, 0, 0)
    else:
        struct.pack_into("<II", table, 16, TABLE_HEADER, TABLE_HEADER)
    table[TABLE_HEADER:] = entry
    return bytes(table)


def open_attribute_table(open_lsn: int) -> bytes:
    entry = bytearray(TABLE_ENTRY)
    struct.pack_into("<III", entry, 0, ALLOCATED, 0, 0x80)
    # MFT-class log actions are owned by $MFT::$DATA, not by the resident
    # attribute they alter inside the selected FILE record.
    struct.pack_into("<Q", entry, 16, (1 << 48) | 0)
    struct.pack_into("<Q", entry, 24, open_lsn)
    return restart_table(entry, True)


def dirty_page_table(target_vcn: int, target_lcn: int, oldest_lsn: int) -> bytes:
    entry = bytearray(TABLE_ENTRY)
    struct.pack_into("<IIII", entry, 0, ALLOCATED, TABLE_HEADER, PAGE, 1)
    struct.pack_into("<QQQ", entry, 16, target_vcn, oldest_lsn, target_lcn)
    return restart_table(entry, True)


def transaction_table() -> bytes:
    return restart_table(bytes(TABLE_ENTRY), False)


def encode_dump(
    total_size: int, this_lsn: int, previous_lsn: int, operation: int,
    payload: bytes,
) -> bytes:
    record = helper.encode_common_record(
        total_size, this_lsn, previous_lsn, previous_lsn, CHECKPOINT_TX
    )
    struct.pack_into("<HHHH", record, 48, operation, 0, 0x28, len(payload))
    record[80:80 + len(payload)] = payload
    return bytes(record)


def encode_names(this_lsn: int, previous_lsn: int) -> bytes:
    record = helper.encode_common_record(
        88, this_lsn, previous_lsn, previous_lsn, CHECKPOINT_TX
    )
    struct.pack_into("<HH", record, 48, ATTRIBUTE_NAMES_DUMP, 0)
    # A zero key terminates the list; the remaining four bytes are canonical pad.
    record[80:88] = bytes(8)
    return bytes(record)


def encode_checkpoint(this_lsn: int, previous_lsn: int, table_lsns, lengths):
    record = bytearray(152)
    struct.pack_into("<QQQI", record, 0, this_lsn, previous_lsn, 0, 104)
    struct.pack_into("<HH", record, 28, 1, 0)
    struct.pack_into("<I", record, 32, LOG_CHECKPOINT)
    struct.pack_into("<IIQ", record, 48, 1, 1, this_lsn)
    for index, lsn in enumerate(table_lsns):
        struct.pack_into("<Q", record, 64 + 8 * index, lsn)
        struct.pack_into("<I", record, 96 + 4 * index, lengths[index])
    return bytes(record)


def windows_open_attribute_table(open_lsn: int) -> bytes:
    table = bytearray(TABLE_HEADER + 8 * TABLE_ENTRY)
    struct.pack_into("<HHH", table, 0, TABLE_ENTRY, 8, 2)
    struct.pack_into("<II", table, 16, TABLE_HEADER + 2 * TABLE_ENTRY,
                     TABLE_HEADER + 7 * TABLE_ENTRY)
    first = TABLE_HEADER
    second = first + TABLE_ENTRY
    struct.pack_into("<III", table, first, ALLOCATED, 0, 0x80)
    struct.pack_into("<Q", table, first + 16, (1 << 48) | 0)
    struct.pack_into("<Q", table, first + 24, open_lsn)
    struct.pack_into("<III", table, second, ALLOCATED, 4096, 0xA0)
    struct.pack_into("<Q", table, second + 16, (5 << 48) | 5)
    struct.pack_into("<Q", table, second + 24, open_lsn)
    for slot in range(2, 8):
        entry = TABLE_HEADER + slot * TABLE_ENTRY
        following = TABLE_HEADER + (slot + 1) * TABLE_ENTRY if slot < 7 else 0
        struct.pack_into("<I", table, entry, following)
    return bytes(table)


def windows_names_table() -> bytes:
    payload = bytearray()
    payload += struct.pack("<HH", TABLE_HEADER + TABLE_ENTRY, 8)
    payload += "$I30".encode("utf-16le")
    payload += struct.pack("<HH", 0, 0)
    payload += bytes(2)
    return bytes(payload)


def encode_windows_dump(this_lsn: int, previous_lsn: int, operation: int,
                        payload: bytes) -> bytes:
    total = (88 + len(payload) + 7) & ~7
    record = helper.encode_common_record(
        total, this_lsn, previous_lsn, previous_lsn, CHECKPOINT_TX
    )
    struct.pack_into("<H", record, 28, 0)
    struct.pack_into("<I", record, 40, 4)
    struct.pack_into("<HHHH", record, 48, operation, 0, 0x28, len(payload))
    struct.pack_into("<HH", record, 60, TABLE_HEADER, 0)
    struct.pack_into("<H", record, 70, ACTS_ON_MFT)
    record[80:88] = b"\xff" * 8
    record[88:88 + len(payload)] = payload
    return bytes(record)


def encode_windows_checkpoint(this_lsn: int, previous_lsn: int,
                              analysis_start: int, table_lsns, lengths):
    record = bytearray(160)
    struct.pack_into("<QQQI", record, 0, this_lsn, previous_lsn, 0, 112)
    struct.pack_into("<HH", record, 28, 0, 0)
    struct.pack_into("<II", record, 32, LOG_CHECKPOINT, 0)
    struct.pack_into("<IIQ", record, 48, 1, 0, analysis_start)
    for index, lsn in enumerate(table_lsns):
        struct.pack_into("<Q", record, 64 + 8 * index, lsn)
        struct.pack_into("<I", record, 96 + 4 * index, lengths[index])
    struct.pack_into("<Q", record, 120, this_lsn)
    struct.pack_into("<Q", record, 128, PAGE)
    struct.pack_into("<Q", record, 152, this_lsn)
    return bytes(record)


def encode_windows_restart_page(current_lsn: int, synced_lsn: int,
                                committed_lsn: int, logfile_size: int,
                                sequence_bits: int, usn: int) -> bytes:
    page = bytearray(helper.encode_restart_page(
        current_lsn, synced_lsn, committed_lsn, logfile_size,
        sequence_bits, usn
    ))
    page = helper.mst_unprotect(page, PAGE)
    struct.pack_into("<H", page, 4, 0x1E)
    client = helper.RESTART_AREA_OFFSET + helper.CLIENT_ARRAY_OFFSET
    struct.pack_into("<H", page, client + 20, 0)
    return helper.mst_protect(page, 0x1E, usn)


def build_windows_control_only(base: Path, fixture: Path):
    require(not fixture.exists(), f"refusing to overwrite {fixture}")
    shutil.copyfile(base, fixture)
    with fixture.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        logfile_size, logfile_runs = helper.find_logfile(image, geometry)
        sequence_bits = 67 - logfile_size.bit_length()
        sizes = [160, 432, 112, 160]
        offsets, cursor = [], DATA_OFFSET
        for size in sizes:
            offsets.append(cursor)
            cursor += size
        lsns = [helper.make_lsn(sequence_bits, TARGET_PAGE, value)
                for value in offsets]
        open_table = windows_open_attribute_table(lsns[0])
        names_table = windows_names_table()
        records = b"".join([
            encode_windows_checkpoint(lsns[0], 0, lsns[0], [0, 0, 0, 0],
                                      [0, 0, 0, 0]),
            encode_windows_dump(lsns[1], lsns[0], OPEN_TABLE_DUMP, open_table),
            encode_windows_dump(lsns[2], lsns[1], ATTRIBUTE_NAMES_DUMP,
                                names_table),
            encode_windows_checkpoint(
                lsns[3], lsns[2], lsns[0], [lsns[1], lsns[2], 0, 0],
                [len(open_table), len(names_table), 0, 0]
            ),
        ])
        require(len(records) == sum(sizes), "Windows record sizes")
        pages = {
            0: encode_windows_restart_page(
                lsns[3], lsns[0], lsns[3], logfile_size, sequence_bits, 0xE001
            ),
            1: encode_windows_restart_page(
                lsns[0], lsns[0], lsns[0], logfile_size, sequence_bits, 0xE002
            ),
            2: helper.encode_record_page(
                2, TARGET_PAGE * PAGE, lsns[0], DATA_OFFSET, usn=0xE100
            ),
            3: helper.encode_record_page(
                3, TARGET_PAGE * PAGE, lsns[0] - 1, DATA_OFFSET, usn=0xE100
            ),
            PREVIOUS_PAGE: helper.encode_record_page(
                PREVIOUS_PAGE, lsns[0] - 1, lsns[0] - 1, PAGE - 16,
                usn=0xE100,
            ),
            TARGET_PAGE: helper.encode_record_page(
                TARGET_PAGE, lsns[3], lsns[3], DATA_OFFSET + len(records),
                records=records, usn=0xE100,
            ),
        }
        for number, page in pages.items():
            helper.stream_write(image, logfile_runs, PAGE, number * PAGE, page)
        image.flush()
        os.fsync(image.fileno())


def encode_update(
    this_lsn: int, target_lcn: int, target_vcn: int, cluster_index: int,
    volume_name,
) -> bytes:
    record = bytearray(helper.encode_update_record(
        this_lsn, target_lcn, target_vcn, cluster_index, volume_name
    ))
    struct.pack_into("<I", record, 36, UPDATE_TX)
    struct.pack_into("<H", record, 60, TABLE_HEADER)
    return bytes(record)


def encode_forget(this_lsn: int, previous_lsn: int) -> bytes:
    record = helper.encode_common_record(
        88, this_lsn, previous_lsn, previous_lsn, UPDATE_TX
    )
    struct.pack_into("<HH", record, 48, FORGET, 0)
    return bytes(record)


def compile_probe(tree: Path, work: Path, cc: str) -> Path:
    source = work / "checkpoint_probe.c"
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
    probe = work / "checkpoint-probe"
    run(common + [source, *objects, tree / "src" / "utils.o",
                  tree / "libntfs" / ".libs" / "libntfs.a", "-o", probe],
        "checkpoint probe link")
    return probe


def build(base: Path, fixture: Path, manifest_path: Path):
    require(base.resolve() != fixture.resolve(), "base and fixture differ")
    require(not fixture.exists(), f"refusing to overwrite {fixture}")
    shutil.copyfile(base, fixture)
    with fixture.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        # $MFTMirr LCN is an exact boot-sector field, separate from helper geometry.
        image.seek(0)
        mftmirr_lcn = helper.u64(image.read(512), 56)
        logfile_size, logfile_runs = helper.find_logfile(image, geometry)
        volume_name = helper.find_volume_name(image, geometry)
        require(helper.stream_read(image, logfile_runs, PAGE, 0, 7 * PAGE) ==
                b"\xff" * (7 * PAGE), "wiped logfile seed")
        sequence_bits = 67 - logfile_size.bit_length()
        target_byte = 3 * geometry["mft_record_size"]
        target_vcn = target_byte // PAGE
        cluster_index = (target_byte % PAGE) // 512
        target_lcn = geometry["mft_lcn"] + target_vcn
        offsets = []
        cursor = DATA_OFFSET
        sizes = [144, 88, 144, 144, 152, 104, 88]
        for size in sizes:
            offsets.append(cursor)
            cursor += size
        lsns = [helper.make_lsn(sequence_bits, TARGET_PAGE, value)
                for value in offsets]
        open_table = open_attribute_table(0)
        names_table = bytes(8)
        dirty_table = dirty_page_table(target_vcn, target_lcn, lsns[0])
        tx_table = transaction_table()
        actions = [
            encode_dump(144, lsns[0], 0, OPEN_TABLE_DUMP, open_table),
            encode_names(lsns[1], lsns[0]),
            encode_dump(144, lsns[2], lsns[1], DIRTY_PAGE_TABLE_DUMP,
                        dirty_table),
            encode_dump(144, lsns[3], lsns[2], TRANSACTION_TABLE_DUMP,
                        tx_table),
            encode_checkpoint(lsns[4], lsns[3], lsns[:4],
                              [len(open_table), len(names_table),
                               len(dirty_table), len(tx_table)]),
            encode_update(lsns[5], target_lcn, target_vcn, cluster_index,
                          volume_name),
            encode_forget(lsns[6], lsns[5]),
        ]
        records = b"".join(actions)
        require(len(records) == sum(sizes), "exact record sizes")
        pages = {
            0: helper.encode_restart_page(
                lsns[6], lsns[0], lsns[4], logfile_size, sequence_bits, 0xD001
            ),
            1: helper.encode_restart_page(
                lsns[6], lsns[0], lsns[4], logfile_size, sequence_bits, 0xD002
            ),
            2: helper.encode_record_page(
                2, TARGET_PAGE * PAGE, lsns[0], DATA_OFFSET, usn=0xD100
            ),
            3: helper.encode_record_page(
                3, TARGET_PAGE * PAGE, lsns[0] - 1, DATA_OFFSET, usn=0xD100
            ),
            PREVIOUS_PAGE: helper.encode_record_page(
                PREVIOUS_PAGE, lsns[0] - 1, lsns[0] - 1, PAGE - 16,
                usn=0xD100,
            ),
            TARGET_PAGE: helper.encode_record_page(
                TARGET_PAGE, lsns[6], lsns[6], DATA_OFFSET + len(records),
                records=records, usn=0xD100,
            ),
        }
        for number, page in pages.items():
            helper.stream_write(image, logfile_runs, PAGE, number * PAGE, page)
        image.flush()
        os.fsync(image.fileno())
    manifest = {
        "analysis_controls": [
            "OpenAttributeTableDump", "AttributeNamesDump",
            "DirtyPageTableDump", "TransactionTableDump", "LOG_CHECKPOINT",
        ],
        "actions": 7,
        "primary_offset": target_lcn * PAGE + target_byte % PAGE,
        "mirror_offset": mftmirr_lcn * PAGE + target_byte % PAGE,
        "value_at": volume_name["record_offset"] +
                    volume_name["attribute_offset"],
        "table_lengths": [64, 8, 64, 64],
        "record_offsets": offsets,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def mutate_log_page(source: Path, output: Path, mutate):
    shutil.copyfile(source, output)
    with output.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        _, runs = helper.find_logfile(image, geometry)
        raw = helper.stream_read(image, runs, PAGE, TARGET_PAGE * PAGE, PAGE)
        page = helper.mst_unprotect(raw, PAGE)
        mutate(page)
        protected = helper.mst_protect(page, helper.u16(page, 4),
                                       helper.u16(page, helper.u16(page, 4)))
        helper.stream_write(image, runs, PAGE, TARGET_PAGE * PAGE, protected)
        image.flush()
        os.fsync(image.fileno())


def negative_tests(probe: Path, fixture: Path, manifest, work: Path):
    arguments = [manifest["primary_offset"], manifest["mirror_offset"],
                 manifest["value_at"]]
    open_offset, _, dirty_offset, tx_offset, checkpoint_offset, _, _ = \
        manifest["record_offsets"]
    mutations = [
        ("open-attribute-type", lambda page: struct.pack_into(
            "<I", page, open_offset + 80 + TABLE_HEADER + 8, 0x81)),
        ("mft-open-owner", lambda page: struct.pack_into(
            "<Q", page, open_offset + 80 + TABLE_HEADER + 16,
            (1 << 48) | 3)),
        ("dirty-page-lcn", lambda page: struct.pack_into(
            "<Q", page, dirty_offset + 80 + TABLE_HEADER + 32,
            0xFFFFFFFFFFFFFFFF)),
        ("transaction-free-cycle", lambda page: struct.pack_into(
            "<I", page, tx_offset + 80 + TABLE_HEADER, TABLE_HEADER)),
        ("checkpoint-length-mismatch", lambda page: struct.pack_into(
            "<I", page, checkpoint_offset + 96, 63)),
    ]
    completed = []
    for name, mutate in mutations:
        candidate = work / f"negative-{name}.img"
        mutate_log_page(fixture, candidate, mutate)
        before = file_sha(candidate)
        result = subprocess.run(
            [str(probe), str(candidate), *[str(value) for value in arguments]],
            text=True, capture_output=True,
        )
        require(result.returncode != 0, f"negative {name} was accepted")
        require(file_sha(candidate) == before, f"negative {name} was modified")
        completed.append(name)
    return completed


def self_test(tree: Path, cc: str, work_dir: Path | None,
              mkntfs: Path | None):
    context = tempfile.TemporaryDirectory(prefix="roothealth-native-checkpoint.")
    work = work_dir.resolve() if work_dir else Path(context.name)
    if work_dir:
        require(not work.exists() or not any(work.iterdir()),
                "work directory must be empty")
        work.mkdir(parents=True, exist_ok=True)
    base = work / "base.img"
    fixture = work / "checkpoint.img"
    windows_fixture = work / "windows-checkpoint.img"
    manifest_path = work / "checkpoint.json"
    with base.open("wb") as image:
        image.truncate(64 * 1024 * 1024)
    run([mkntfs or tree / "src" / "mkntfs", "-F", "-q", "-T", "-L",
         "RHREDO", base],
        "mkntfs fixture base")
    before = file_sha(base)
    manifest = build(base, fixture, manifest_path)
    build_windows_control_only(base, windows_fixture)
    fixture_before = file_sha(fixture)
    probe = compile_probe(tree, work, cc)
    output = run([
        probe, fixture, manifest["primary_offset"], manifest["mirror_offset"],
        manifest["value_at"],
    ], "checkpoint plan-only probe")
    windows_before = file_sha(windows_fixture)
    windows_output = run([probe, windows_fixture],
                         "Windows checkpoint plan-only probe")
    require(file_sha(windows_fixture) == windows_before,
            "parser modified Windows checkpoint image")
    negatives = negative_tests(probe, fixture, manifest, work)
    fixture_after = file_sha(fixture)
    require(fixture_before == fixture_after, "parser modified checkpoint image")
    result = {
        "result": "PASS",
        "actions": 7,
        "analysis_controls": 5,
        "mutation_pairs": 1,
        "fixture_sha256_before": fixture_before,
        "fixture_sha256_after": fixture_after,
        "base_sha256": before,
        "typed_operations": 4,
        "negative_table_tests": negatives,
        "windows_checkpoint_sha256": windows_before,
        "windows_control_only_operations": 2,
        "work_directory": str(work),
    }
    print(output, end="")
    print(windows_output, end="")
    print(json.dumps(result, sort_keys=True))
    if not work_dir:
        context.cleanup()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("self-test",))
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--mkntfs", type=Path)
    args = parser.parse_args()
    self_test(args.tree.resolve(), args.cc, args.work_dir, args.mkntfs)


if __name__ == "__main__":
    raise SystemExit(main())
