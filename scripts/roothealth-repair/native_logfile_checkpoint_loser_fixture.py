#!/usr/bin/env python3
"""Checkpoint-seeded active-loser native $LogFile fixture.

The dirty on-disk bitmap page contains an active transaction's after-image.
The checkpoint transaction table seeds its undo chain. DeleteDirtyClusters
invalidates the checkpoint DPT location and HotFix restores its exact physical
location before a later committed MFT winner is redone and the loser before-
image is restored. The plan uses a persistent-undo backend and is never
committed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
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


helper = load("redo_helper", "native_logfile_redo_fixture.py")
checkpoint = load("checkpoint_helper", "native_logfile_checkpoint_fixture.py")
multi = load("multitx_helper", "native_logfile_multitx_fixture.py")
owned = load("owned_stream_helper", "native_logfile_multitx_owned_fixture.py")

PAGE = 4096
DATA_OFFSET = 0x40
TARGET_PAGE = 5
PREVIOUS_PAGE = 4
ALLOCATED = 0xFFFFFFFF
TABLE_HEADER = 24
TABLE_ENTRY = 40
LOSER_TX = 24
WINNER_TX = 64
UPDATE_NONRESIDENT = 8
DELETE_DIRTY = 10
UPDATE_RESIDENT = 7
HOTFIX = 23
FORGET = 27
OPEN_DUMP = 29
NAMES_DUMP = 30
DIRTY_DUMP = 31
TX_DUMP = 32
LOG_CHECKPOINT = 2
BITMAP_VALUE_AT = 512


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

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_log_result result;
	uint64_t primary, mirror, bitmap;
	int rc;

	if (argc != 5)
		return 64;
	primary = strtoull(argv[2], NULL, 0);
	mirror = strtoull(argv[3], NULL, 0);
	bitmap = strtoull(argv[4], NULL, 0);
	if (rh_writer_open(&writer, argv[1]) ||
		rh_writer_set_backend(&writer, &persistent_backend, NULL))
		return 65;
	rc = roothealth_log_replay_plan(argv[1], &writer, &result);
	printf("plan_rc=%d actions=%u redo=%u undo=%u restart=%u operations=%zu bytes=%" PRIu64 "\n",
		rc, result.actions_seen, result.redo_actions, result.undo_actions,
		result.restart_pages_planned, writer.operation_count,
		writer.planned_bytes);
	if (rc || result.actions_seen != 10 || result.redo_actions != 2 ||
		result.undo_actions != 1 || result.restart_pages_planned != 2 ||
		writer.operation_count != 5 || writer.planned_bytes != UINT64_C(14336) ||
		writer.operations[0].kind != RH_WRITE_LOGFILE_REDO ||
		writer.operations[0].offset != primary ||
		writer.operations[1].kind != RH_WRITE_LOGFILE_REDO ||
		writer.operations[1].offset != mirror ||
		writer.operations[2].kind != RH_WRITE_LOGFILE_REDO ||
		writer.operations[2].offset != bitmap ||
		writer.operations[3].kind != RH_WRITE_LOGFILE_RESTART ||
		writer.operations[4].kind != RH_WRITE_LOGFILE_RESTART) {
		fprintf(stderr, "checkpoint winner/loser WAL plan not proven\n");
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


def restart_table(entries: list[bytes]) -> bytes:
    require(entries and all(len(entry) == TABLE_ENTRY for entry in entries),
            "restart-table entries")
    table = bytearray(TABLE_HEADER + TABLE_ENTRY * len(entries))
    struct.pack_into("<HHH", table, 0, TABLE_ENTRY, len(entries), len(entries))
    for index, entry in enumerate(entries):
        table[TABLE_HEADER + index * TABLE_ENTRY:
              TABLE_HEADER + (index + 1) * TABLE_ENTRY] = entry
    return bytes(table)


def open_entry(reference: int, attr_type: int, bytes_per_index: int = 0) -> bytes:
    entry = bytearray(TABLE_ENTRY)
    struct.pack_into("<III", entry, 0, ALLOCATED, bytes_per_index, attr_type)
    struct.pack_into("<Q", entry, 16, reference)
    return bytes(entry)


def dirty_entry(key: int, vcn: int, oldest_lsn: int, lcn: int) -> bytes:
    entry = bytearray(TABLE_ENTRY)
    struct.pack_into("<IIII", entry, 0, ALLOCATED, key, PAGE, 1)
    struct.pack_into("<QQQ", entry, 16, vcn, oldest_lsn, lcn)
    return bytes(entry)


def transaction_entry(first_lsn: int) -> bytes:
    entry = bytearray(TABLE_ENTRY)
    struct.pack_into("<IB", entry, 0, ALLOCATED, 1)
    struct.pack_into("<QQQII", entry, 8, first_lsn, first_lsn, first_lsn, 1, 8)
    return bytes(entry)


def encode_dump(total_size: int, this_lsn: int, previous_lsn: int,
                operation: int, payload: bytes) -> bytes:
    record = helper.encode_common_record(
        total_size, this_lsn, previous_lsn, previous_lsn, LOSER_TX
    )
    struct.pack_into("<HHHH", record, 48, operation, 0, 0x28, len(payload))
    record[80:80 + len(payload)] = payload
    return bytes(record)


def encode_names(this_lsn: int, previous_lsn: int) -> bytes:
    record = helper.encode_common_record(
        88, this_lsn, previous_lsn, previous_lsn, LOSER_TX
    )
    struct.pack_into("<HH", record, 48, NAMES_DUMP, 0)
    return bytes(record)


def encode_checkpoint(this_lsn: int, previous_lsn: int, analysis_start: int,
                      table_lsns: list[int], lengths: list[int]) -> bytes:
    record = bytearray(152)
    struct.pack_into("<QQQI", record, 0, this_lsn, previous_lsn, 0, 104)
    struct.pack_into("<HH", record, 28, 1, 0)
    struct.pack_into("<I", record, 32, LOG_CHECKPOINT)
    struct.pack_into("<IIQ", record, 48, 1, 1, analysis_start)
    for index, lsn in enumerate(table_lsns):
        struct.pack_into("<Q", record, 64 + 8 * index, lsn)
        struct.pack_into("<I", record, 96 + 4 * index, lengths[index])
    return bytes(record)


def encode_mutation(*, this_lsn: int, previous_lsn: int, undo_lsn: int,
                    transaction: int, operation: int, target_attribute: int,
                    lcn: int, vcn: int, cluster_index: int, record_offset: int,
                    attribute_offset: int, flags: int, redo: bytes,
                    undo: bytes) -> bytes:
    require(len(redo) == len(undo) == 8, "eight-byte mutation")
    record = helper.encode_common_record(
        104, this_lsn, previous_lsn, undo_lsn, transaction
    )
    struct.pack_into("<H", record, 40, 2)
    struct.pack_into("<HHHHHH", record, 48, operation, operation,
                     0x28, 8, 0x30, 8)
    struct.pack_into("<HH", record, 60, target_attribute, 1)
    struct.pack_into("<HHHHQ", record, 64, record_offset, attribute_offset,
                     cluster_index, flags, vcn)
    struct.pack_into("<Q", record, 80, lcn)
    record[88:96] = redo
    record[96:104] = undo
    return bytes(record)


def encode_forget(this_lsn: int, previous_lsn: int) -> bytes:
    record = helper.encode_common_record(
        88, this_lsn, previous_lsn, previous_lsn, WINNER_TX
    )
    struct.pack_into("<HH", record, 48, FORGET, 0)
    return bytes(record)


def encode_delete_dirty(this_lsn: int, first_lcn: int, count: int) -> bytes:
    record = helper.encode_common_record(96, this_lsn, 0, 0, WINNER_TX)
    struct.pack_into("<HHHH", record, 48, DELETE_DIRTY, 0, 0x28, 16)
    struct.pack_into("<QQ", record, 80, first_lcn, count)
    return bytes(record)


def encode_hotfix(this_lsn: int, previous_lsn: int, target_attribute: int,
                  vcn: int, lcn: int) -> bytes:
    record = helper.encode_common_record(
        88, this_lsn, previous_lsn, previous_lsn, WINNER_TX
    )
    struct.pack_into("<HH", record, 48, HOTFIX, 0)
    struct.pack_into("<HH", record, 60, target_attribute, 1)
    struct.pack_into("<Q", record, 72, vcn)
    struct.pack_into("<Q", record, 80, lcn)
    return bytes(record)


def find_stream(image, geometry, inode: int):
    _, record = helper.read_mft_record(image, geometry, inode)
    for offset, kind, nonresident, _ in helper.iter_attributes(record):
        if kind == 0x80 and nonresident:
            return record, helper.decode_mapping_pairs(record, offset)
    raise ValueError(f"inode {inode} data stream missing")


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


def build(base: Path, fixture: Path, manifest_path: Path, raw_inode: int):
    require(not fixture.exists(), f"refusing to overwrite {fixture}")
    shutil.copyfile(base, fixture)
    with fixture.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        logfile_size, logfile_runs = helper.find_logfile(image, geometry)
        require(helper.stream_read(image, logfile_runs, PAGE, 0, 7 * PAGE) ==
                b"\xff" * (7 * PAGE), "wiped logfile seed")
        bitmap_record, bitmap_runs = find_stream(image, geometry, raw_inode)
        bitmap_lcn = bitmap_runs[0]["lcn"]
        image.seek(bitmap_lcn * PAGE)
        bitmap_page = bytearray(image.read(PAGE))
        old_bitmap = bytes(bitmap_page[BITMAP_VALUE_AT:BITMAP_VALUE_AT + 8])
        new_bitmap = bytearray(old_bitmap)
        new_bitmap[0] ^= 0x80
        bitmap_page[BITMAP_VALUE_AT:BITMAP_VALUE_AT + 8] = new_bitmap
        image.seek(bitmap_lcn * PAGE)
        image.write(bitmap_page)

        volume_name = helper.find_volume_name(image, geometry)
        _, volume_record = helper.read_mft_record(image, geometry, 3)
        volume_value_at = volume_name["record_offset"] + \
            volume_name["attribute_offset"]
        old_volume = bytes(volume_record[volume_value_at:volume_value_at + 8])
        new_volume = bytearray(old_volume)
        new_volume[:2] = volume_name["new_code_unit"]
        target_byte = 3 * geometry["mft_record_size"]
        mft_vcn = target_byte // PAGE
        cluster_index = (target_byte % PAGE) // 512
        mft_lcn = geometry["mft_lcn"] + mft_vcn
        image.seek(0)
        mftmirr_lcn = helper.u64(image.read(512), 56)
        _, mft_record = helper.read_mft_record(image, geometry, 0)
        bitmap_sequence = helper.u16(bitmap_record, 16)
        mft_sequence = helper.u16(mft_record, 16)

        sizes = [104, 184, 88, 184, 144, 152, 96, 88, 104, 88]
        offsets = []
        cursor = DATA_OFFSET
        for size in sizes:
            offsets.append(cursor)
            cursor += size
        sequence_bits = 67 - logfile_size.bit_length()
        lsns = [helper.make_lsn(sequence_bits, TARGET_PAGE, value)
                for value in offsets]
        open_table = restart_table([
            open_entry((bitmap_sequence << 48) | raw_inode, 0x80),
            open_entry((mft_sequence << 48) | 0, 0x80),
        ])
        names_table = bytes(8)
        stale_bitmap_lcn = bitmap_lcn + 1
        require(stale_bitmap_lcn < fixture.stat().st_size // PAGE,
                "stale DPT LCN is in volume")
        dirty_table = restart_table([
            dirty_entry(TABLE_HEADER, 0, lsns[0], stale_bitmap_lcn),
            dirty_entry(TABLE_HEADER + TABLE_ENTRY, mft_vcn, lsns[0], mft_lcn),
        ])
        tx_table = restart_table([transaction_entry(lsns[0])])
        actions = [
            encode_mutation(
                this_lsn=lsns[0], previous_lsn=0, undo_lsn=0,
                transaction=LOSER_TX, operation=UPDATE_NONRESIDENT,
                target_attribute=TABLE_HEADER, lcn=bitmap_lcn, vcn=0,
                cluster_index=0, record_offset=0,
                attribute_offset=BITMAP_VALUE_AT, flags=0,
                redo=bytes(new_bitmap), undo=old_bitmap,
            ),
            encode_dump(184, lsns[1], lsns[0], OPEN_DUMP, open_table),
            encode_names(lsns[2], lsns[1]),
            encode_dump(184, lsns[3], lsns[2], DIRTY_DUMP, dirty_table),
            encode_dump(144, lsns[4], lsns[3], TX_DUMP, tx_table),
            encode_checkpoint(lsns[5], lsns[4], lsns[0], lsns[1:5],
                              [len(open_table), len(names_table),
                               len(dirty_table), len(tx_table)]),
            encode_delete_dirty(lsns[6], stale_bitmap_lcn, 1),
            encode_hotfix(lsns[7], lsns[6], TABLE_HEADER, 0, bitmap_lcn),
            encode_mutation(
                this_lsn=lsns[8], previous_lsn=lsns[7], undo_lsn=lsns[7],
                transaction=WINNER_TX, operation=UPDATE_RESIDENT,
                target_attribute=TABLE_HEADER + TABLE_ENTRY,
                lcn=mft_lcn, vcn=mft_vcn, cluster_index=cluster_index,
                record_offset=volume_name["record_offset"],
                attribute_offset=volume_name["attribute_offset"],
                flags=2, redo=bytes(new_volume), undo=old_volume,
            ),
            encode_forget(lsns[9], lsns[8]),
        ]
        require([len(action) for action in actions] == sizes,
                "exact checkpoint-loser action sizes")
        records = b"".join(actions)
        pages = {
            0: helper.encode_restart_page(
                lsns[-1], lsns[0], lsns[-1], logfile_size,
                sequence_bits, 0xF001,
            ),
            1: helper.encode_restart_page(
                lsns[-1], lsns[0], lsns[-1], logfile_size,
                sequence_bits, 0xF002,
            ),
            2: helper.encode_record_page(
                2, TARGET_PAGE * PAGE, lsns[0], DATA_OFFSET, usn=0xF100,
            ),
            3: helper.encode_record_page(
                3, TARGET_PAGE * PAGE, lsns[0] - 1, DATA_OFFSET, usn=0xF100,
            ),
            PREVIOUS_PAGE: helper.encode_record_page(
                PREVIOUS_PAGE, lsns[0] - 1, lsns[0] - 1,
                PAGE - 16, usn=0xF100,
            ),
            TARGET_PAGE: helper.encode_record_page(
                TARGET_PAGE, lsns[-1], lsns[-1], DATA_OFFSET + len(records),
                records=records, usn=0xF100,
            ),
        }
        for number, page in pages.items():
            helper.stream_write(image, logfile_runs, PAGE, number * PAGE, page)
        image.flush()
        os.fsync(image.fileno())
    manifest = {
        "actions": 10,
        "primary_offset": mft_lcn * PAGE + target_byte % PAGE,
        "mirror_offset": mftmirr_lcn * PAGE + target_byte % PAGE,
        "bitmap_offset": bitmap_lcn * PAGE,
        "record_offsets": offsets,
        "loser_lsn": lsns[0],
        "table_lsns": lsns[1:5],
        "dpt_control_ops": ["DeleteDirtyClusters", "HotFix"],
        "owned_inode": raw_inode,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def compile_probe(tree: Path, work: Path, cc: str) -> Path:
    source = work / "checkpoint_loser_probe.c"
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
    probe = work / "checkpoint-loser-probe"
    run(common + [source, *objects, tree / "src" / "utils.o",
                  tree / "libntfs" / ".libs" / "libntfs.a", "-o", probe],
        "checkpoint loser probe link")
    return probe


def self_test(tree: Path, cc: str, work_dir: Path | None):
    context = tempfile.TemporaryDirectory(prefix="roothealth-checkpoint-loser.")
    work = work_dir.resolve() if work_dir else Path(context.name)
    if work_dir:
        require(not work.exists() or not any(work.iterdir()),
                "work directory must be empty")
        work.mkdir(parents=True, exist_ok=True)
    base = work / "base.img"
    fixture = work / "checkpoint-loser.img"
    manifest_path = work / "checkpoint-loser.json"
    with base.open("wb") as image:
        image.truncate(64 * 1024 * 1024)
    run([tree / "src" / "mkntfs", "-F", "-q", "-T", "-L", "RHREDO", base],
        "mkntfs fixture base")
    payload = work / "checkpoint-loser-owned.bin"
    payload.write_bytes((b"ROOTHEALTH-CHECKPOINT-LOSER\x00" * 512)[:8192])
    os.utime(payload, (946684800, 946684800))
    run([tree / "src" / "ntfscp", "-f", "-q", "-t", base, payload,
         "/rh-checkpoint-loser.bin"], "create owned nonresident stream")
    listing = run([tree / "src" / "ntfsls", "-f", "-i", "-l", "-p", "/", base],
                  "locate owned nonresident stream")
    inodes = [
        int(match.group(1)) for line in listing.splitlines()
        if (match := re.match(
            r"^\s*(\d+)\s+.*\brh-checkpoint-loser\.bin\s*$", line
        ))
    ]
    require(len(inodes) == 1 and inodes[0] >= 24,
            "one non-fixed owned stream inode")
    owned.normalize_owned_timestamps(base, inodes[0], "rh-checkpoint-loser.bin")
    manifest = build(base, fixture, manifest_path, inodes[0])
    before = file_sha(fixture)
    probe = compile_probe(tree, work, cc)
    output = run([
        probe, fixture, manifest["primary_offset"], manifest["mirror_offset"],
        manifest["bitmap_offset"],
    ], "checkpoint winner/loser plan-only probe")
    after = file_sha(fixture)
    require(before == after, "parser modified checkpoint-loser image")

    negative_controls = []
    bad_hotfix = work / "negative-hotfix-retarget.img"
    shutil.copyfile(fixture, bad_hotfix)
    hotfix_offset = manifest["record_offsets"][7]
    mutate_log_page(bad_hotfix, TARGET_PAGE, lambda page: struct.pack_into(
        "<Q", page, hotfix_offset + 80,
        struct.unpack_from("<Q", page, hotfix_offset + 80)[0] + 1,
    ))
    bad_before = file_sha(bad_hotfix)
    rejected = subprocess.run([
        str(probe), str(bad_hotfix), str(manifest["primary_offset"]),
        str(manifest["mirror_offset"]), str(manifest["bitmap_offset"]),
    ], text=True, capture_output=True)
    require(rejected.returncode == 66 and "plan_rc=-1" in rejected.stdout and
            "operations=0" in rejected.stdout,
            "HotFix physical retarget was not rejected")
    require(file_sha(bad_hotfix) == bad_before,
            "rejected HotFix retarget image changed")
    negative_controls.append("hotfix-physical-retarget")

    bad_restart = work / "negative-alternate-restart-bounds.img"
    shutil.copyfile(fixture, bad_restart)
    mutate_log_page(bad_restart, 1, lambda page: struct.pack_into(
        "<H", page, 24, PAGE - 4,
    ))
    bad_before = file_sha(bad_restart)
    rejected = subprocess.run([
        str(probe), str(bad_restart), str(manifest["primary_offset"]),
        str(manifest["mirror_offset"]), str(manifest["bitmap_offset"]),
    ], text=True, capture_output=True)
    require(rejected.returncode == 66 and "plan_rc=-1" in rejected.stdout and
            "operations=0" in rejected.stdout,
            "malformed alternate restart page was not rejected")
    require(file_sha(bad_restart) == bad_before,
            "rejected alternate restart image changed")
    negative_controls.append("alternate-restart-area-bounds")
    print(output, end="")
    print(json.dumps({
        "result": "PASS", "actions": 10, "analysis_controls": 7,
        "dpt_controls": manifest["dpt_control_ops"],
        "negative_control_tests": negative_controls,
        "winner_redos": 1, "loser_redos": 1, "loser_undos": 1,
        "typed_operations": 5, "persistent_undo_backend": True,
        "owned_inode": manifest["owned_inode"],
        "fixed_metadata_raw_target_refused": True,
        "fixture_sha256_before": before, "fixture_sha256_after": after,
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
