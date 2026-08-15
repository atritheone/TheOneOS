#!/usr/bin/env python3
"""Deterministic native-log winner/loser qualification fixture.

The fixture contains one committed transaction (raw nonresident update,
bounded INDX action, ForgetTransaction) and one active transaction whose raw
update is already present on disk and therefore has to be undone.  The probe
uses roothealth_log_replay_plan only; it never commits the typed writer.
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
SECTOR = 512
DATA_OFFSET = 0x40
TARGET_PAGE = 5
PREVIOUS_PAGE = 4
WINNER_TX = 0x10203040
LOSER_TX = 0x50607080
UPDATE_NONRESIDENT = 8
WRITE_END_INDEX = 16
FORGET = 27
OPEN_NONRESIDENT = 28
LOG_DELETING = 2
ACTS_ON_INDX = 8
AT_DATA = 0x80
AT_INDEX_ALLOCATION = 0xA0
WINNER_ATTRIBUTE = 24
LOSER_ATTRIBUTE = 64
INDEX_ATTRIBUTE = 104
TARGET_VALUE_OFFSET = 128
LOSER_VALUE_OFFSET = 256
WINNER_OLD = b"WIN-OLD!"
WINNER_NEW = b"WIN-NEW!"
LOSER_OLD = b"LOSE-OLD"
LOSER_NEW = b"LOSE-NEW"


PROBE_C = r"""
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_recover.h"
#include "roothealth_write.h"

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_log_result result;
	uint64_t winner_offset, loser_offset;
	int rc;

	if (argc != 4) {
		fprintf(stderr, "usage: %s IMAGE WINNER_OFFSET LOSER_OFFSET\n", argv[0]);
		return 64;
	}
	winner_offset = strtoull(argv[2], NULL, 0);
	loser_offset = strtoull(argv[3], NULL, 0);
	if (rh_writer_open(&writer, argv[1])) {
		perror("rh_writer_open");
		return 65;
	}
	rc = roothealth_log_replay_plan(argv[1], &writer, &result);
	printf("plan_rc=%d actions=%u redo=%u undo=%u restart=%u operations=%zu bytes=%" PRIu64 "\n",
		rc, result.actions_seen, result.redo_actions, result.undo_actions,
		result.restart_pages_planned, writer.operation_count,
		writer.planned_bytes);
	if (rc != -1 || result.actions_seen != 7 || result.redo_actions ||
		result.undo_actions || result.restart_pages_planned ||
		writer.operation_count || writer.planned_bytes ||
		winner_offset != loser_offset) {
		fprintf(stderr, "unowned raw target was not refused as one zero plan\n");
		rh_writer_close(&writer);
		return 66;
	}
	/* Deliberately no rh_writer_commit(). */
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


def find_data_stream(image, geometry, inode: int, attr_type: int,
                     name: str = ""):
    _, record = helper.read_mft_record(image, geometry, inode)
    encoded_name = name.encode("utf-16le")
    for offset, kind, nonresident, _ in helper.iter_attributes(record):
        name_length = record[offset + 9]
        name_offset = helper.u16(record, offset + 10)
        candidate = bytes(record[
            offset + name_offset:offset + name_offset + name_length * 2
        ]) if name_length else b""
        if kind == attr_type and nonresident and candidate == encoded_name:
            reference = (helper.u16(record, 16) << 48) | inode
            return {
                "size": helper.u64(record, offset + 48),
                "runs": helper.decode_mapping_pairs(record, offset),
                "reference": reference,
                "type": attr_type,
                "name": name,
            }
    raise ValueError(f"inode {inode} has no nonresident 0x{attr_type:x} stream")


def choose_free_clusters(image, geometry, excluded: set[int]) -> tuple[int, int]:
    bitmap = find_data_stream(image, geometry, 6, AT_DATA)
    bitmap = helper.stream_read(
        image, bitmap["runs"], geometry["cluster_size"], 0, bitmap["size"]
    )
    chosen = []
    for lcn in range(2100, len(bitmap) * 8):
        if lcn not in excluded and not ((bitmap[lcn // 8] >> (lcn % 8)) & 1):
            chosen.append(lcn)
            if len(chosen) == 2:
                return chosen[0], chosen[1]
    raise ValueError("could not find two deterministic free fixture clusters")


def find_index_block(image, geometry):
    stream = find_data_stream(image, geometry, 5, AT_INDEX_ALLOCATION, "$I30")
    runs = stream["runs"]
    require(len(runs) == 1 and runs[0]["clusters"] >= 1,
            "root index allocation must have a direct run")
    lcn = runs[0]["lcn"]
    image.seek(lcn * PAGE)
    protected = image.read(PAGE)
    unprotected = helper.mst_unprotect(protected, PAGE)
    require(unprotected[:4] == b"INDX", "root index block magic")
    index_length = helper.u32(unprotected, 28)
    target = 24 + index_length - 8
    require(target >= 64 and target + 8 <= PAGE and target % 8 == 0,
            "bounded aligned index tail target")
    return stream, lcn, target, bytes(unprotected[target:target + 8])


def encode_open(*, this_lsn: int, previous_lsn: int, transaction: int,
                key: int, stream: dict, bytes_per_index: int = 0) -> bytes:
    name = stream["name"].encode("utf-16le")
    size = (120 + len(name) + 7) & ~7
    record = helper.encode_common_record(
        size, this_lsn, previous_lsn, previous_lsn, transaction
    )
    struct.pack_into("<HHHHHH", record, 48, OPEN_NONRESIDENT, 0,
                     0x28, 40, 0x50 if name else 0, len(name))
    struct.pack_into("<H", record, 60, key)
    entry = bytearray(40)
    struct.pack_into("<III", entry, 0, 0xFFFFFFFF, bytes_per_index,
                     stream["type"])
    entry[13] = int(bool(name))
    entry[14] = len(name) // 2
    struct.pack_into("<Q", entry, 16, stream["reference"])
    record[80:120] = entry
    if name:
        record[120:120 + len(name)] = name
    return bytes(record)


def encode_action(
    *, this_lsn: int, previous_lsn: int, undo_lsn: int, transaction: int,
    operation: int, target_attribute: int, lcn: int, record_offset: int,
    attribute_offset: int,
    attribute_flags: int, redo: bytes, undo: bytes,
) -> bytes:
    require(len(redo) == len(undo) == 8, "fixture action payload size")
    record = helper.encode_common_record(
        104, this_lsn, previous_lsn, undo_lsn, transaction
    )
    struct.pack_into("<H", record, 40, LOG_DELETING)
    struct.pack_into("<HHHH", record, 48, operation, operation, 0x28, 8)
    struct.pack_into("<HHHH", record, 56, 0x30, 8,
                     target_attribute, 1)
    struct.pack_into(
        "<HHHHQ", record, 64, record_offset, attribute_offset, 0,
        attribute_flags, 0,
    )
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


def strict_validate(encoded: bytes, sequence_bits: int, expected):
    require(len(encoded) == 6 * PAGE, "six-page log prefix")
    pages = []
    for number in range(6):
        raw = encoded[number * PAGE:(number + 1) * PAGE]
        require(raw[:4] == (b"RSTR" if number < 2 else b"RCRD"),
                f"page {number} magic")
        pages.append(helper.mst_unprotect(raw, PAGE))
    page = pages[TARGET_PAGE]
    sizes = (120, 120, 128, 104, 104, 88, 104)
    require(helper.u16(page, 24) == DATA_OFFSET + sum(sizes),
            "target next-record offset")
    offset = DATA_OFFSET
    parsed = []
    for size in sizes:
        record = bytes(page[offset:offset + size])
        require(helper.u32(record, 24) + 48 == size, "record size")
        lsn = helper.u64(record, 0)
        require(lsn == helper.make_lsn(sequence_bits, TARGET_PAGE, offset),
                "record LSN address")
        parsed.append(record)
        offset += size
    require(offset == DATA_OFFSET + sum(sizes), "exact record extent")
    require([helper.u16(record, 48) for record in parsed] ==
            [OPEN_NONRESIDENT, OPEN_NONRESIDENT, OPEN_NONRESIDENT,
             UPDATE_NONRESIDENT, WRITE_END_INDEX, FORGET,
             UPDATE_NONRESIDENT], "operation sequence")
    require(helper.u32(parsed[0], 36) == WINNER_TX and
            helper.u64(parsed[0], 8) == 0,
            "winner chain start")
    for index in range(1, 6):
        require(helper.u64(parsed[index], 8) ==
                helper.u64(parsed[index - 1], 0),
                f"winner action {index} chain")
    require(helper.u32(parsed[6], 36) == LOSER_TX and
            helper.u64(parsed[6], 8) == 0 and
            helper.u64(parsed[6], 16) == 0,
            "self-contained loser chain")
    require(helper.u64(page, 32) == helper.u64(parsed[6], 0),
            "last-end LSN")
    require(helper.u64(parsed[3], 80) == expected["winner_lcn"] and
            helper.u64(parsed[4], 80) == expected["index_lcn"] and
            helper.u64(parsed[6], 80) == expected["loser_lcn"],
            "exact action LCNs")


def build(base: Path, fixture: Path, manifest_path: Path):
    require(base.resolve() != fixture.resolve(), "base and fixture differ")
    require(not fixture.exists(), f"refusing to overwrite {fixture}")
    shutil.copyfile(base, fixture)
    with fixture.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        logfile_size, logfile_runs = helper.find_logfile(image, geometry)
        required = 7 * PAGE
        require(helper.stream_read(image, logfile_runs, PAGE, 0, required) ==
                b"\xff" * required, "wiped logfile seed")
        index_stream, index_lcn, index_target, index_payload = \
            find_index_block(image, geometry)
        winner_stream = find_data_stream(image, geometry, 6, AT_DATA)
        loser_stream = winner_stream
        winner_lcn = winner_stream["runs"][0]["lcn"]
        loser_lcn = loser_stream["runs"][0]["lcn"]
        require(winner_lcn != index_lcn,
                "raw and index targets use distinct owned physical clusters")

        image.seek(winner_lcn * PAGE)
        winner_cluster = bytearray(image.read(PAGE))
        require(len(winner_cluster) == PAGE, "winner stream cluster")
        winner_cluster[TARGET_VALUE_OFFSET:TARGET_VALUE_OFFSET + 8] = WINNER_OLD
        loser_cluster = winner_cluster
        loser_cluster[LOSER_VALUE_OFFSET:LOSER_VALUE_OFFSET + 8] = LOSER_NEW
        image.seek(winner_lcn * PAGE)
        image.write(winner_cluster)
        image.seek(loser_lcn * PAGE)
        image.write(loser_cluster)

        sequence_bits = 67 - logfile_size.bit_length()
        sizes = [120, 120, 128, 104, 104, 88, 104]
        offsets = []
        cursor = DATA_OFFSET
        for size in sizes:
            offsets.append(cursor)
            cursor += size
        lsns = [helper.make_lsn(sequence_bits, TARGET_PAGE, value)
                for value in offsets]
        actions = [
            encode_open(
                this_lsn=lsns[0], previous_lsn=0,
                transaction=WINNER_TX, key=WINNER_ATTRIBUTE,
                stream=winner_stream,
            ),
            encode_open(
                this_lsn=lsns[1], previous_lsn=lsns[0],
                transaction=WINNER_TX, key=LOSER_ATTRIBUTE,
                stream=loser_stream,
            ),
            encode_open(
                this_lsn=lsns[2], previous_lsn=lsns[1],
                transaction=WINNER_TX, key=INDEX_ATTRIBUTE,
                stream=index_stream, bytes_per_index=PAGE,
            ),
            encode_action(
                this_lsn=lsns[3], previous_lsn=lsns[2],
                undo_lsn=lsns[2],
                transaction=WINNER_TX, operation=UPDATE_NONRESIDENT,
                target_attribute=WINNER_ATTRIBUTE,
                lcn=winner_lcn, record_offset=0,
                attribute_offset=TARGET_VALUE_OFFSET, attribute_flags=0,
                redo=WINNER_NEW, undo=WINNER_OLD,
            ),
            encode_action(
                this_lsn=lsns[4], previous_lsn=lsns[3],
                undo_lsn=lsns[3],
                transaction=WINNER_TX, operation=WRITE_END_INDEX,
                target_attribute=INDEX_ATTRIBUTE,
                lcn=index_lcn, record_offset=0,
                attribute_offset=index_target, attribute_flags=ACTS_ON_INDX,
                redo=index_payload, undo=index_payload,
            ),
            encode_forget(lsns[5], lsns[4]),
            encode_action(
                this_lsn=lsns[6], previous_lsn=0, undo_lsn=0,
                transaction=LOSER_TX, operation=UPDATE_NONRESIDENT,
                target_attribute=LOSER_ATTRIBUTE,
                lcn=loser_lcn, record_offset=0,
                attribute_offset=LOSER_VALUE_OFFSET, attribute_flags=0,
                redo=LOSER_NEW, undo=LOSER_OLD,
            ),
        ]
        records = b"".join(actions)
        pages = {
            0: helper.encode_restart_page(
                lsns[6], lsns[0], lsns[5], logfile_size, sequence_bits, 0xC001
            ),
            1: helper.encode_restart_page(
                lsns[6], lsns[0], lsns[5], logfile_size, sequence_bits, 0xC002
            ),
            2: helper.encode_record_page(
                2, TARGET_PAGE * PAGE, lsns[0], DATA_OFFSET, usn=0xC100
            ),
            3: helper.encode_record_page(
                3, TARGET_PAGE * PAGE, lsns[0] - 1, DATA_OFFSET, usn=0xC100
            ),
            PREVIOUS_PAGE: helper.encode_record_page(
                PREVIOUS_PAGE, lsns[0] - 1, lsns[0] - 1, PAGE - 16,
                usn=0xC100,
            ),
            TARGET_PAGE: helper.encode_record_page(
                TARGET_PAGE, lsns[6], lsns[6], DATA_OFFSET + len(records),
                records=records, usn=0xC100,
            ),
        }
        for number, page in pages.items():
            helper.stream_write(image, logfile_runs, PAGE, number * PAGE, page)
        image.flush()
        os.fsync(image.fileno())
        encoded = helper.stream_read(image, logfile_runs, PAGE, 0, 6 * PAGE)
        require(helper.stream_read(image, logfile_runs, PAGE, 6 * PAGE, PAGE) ==
                b"\xff" * PAGE, "page-six scan sentinel")
        expected = {
            "winner_lcn": winner_lcn,
            "loser_lcn": loser_lcn,
            "index_lcn": index_lcn,
        }
        strict_validate(encoded, sequence_bits, expected)

    manifest = {
        "format": "roothealth-native-logfile-multitx-v1",
        "base": str(base),
        "fixture": str(fixture),
        "fixture_sha256": file_sha(fixture),
        "sequence_bits": sequence_bits,
        "synced_lsn": f"0x{lsns[0]:016x}",
        "committed_lsn": f"0x{lsns[5]:016x}",
        "latest_lsn": f"0x{lsns[6]:016x}",
        "winner": {
            "transaction_id": f"0x{WINNER_TX:08x}",
            "raw_lcn": winner_lcn,
            "index_lcn": index_lcn,
            "actions": ["UpdateNonResidentValue", "WriteEndOfIndexBuffer",
                        "ForgetTransaction"],
        },
        "loser": {
            "transaction_id": f"0x{LOSER_TX:08x}",
            "raw_lcn": loser_lcn,
            "actions": ["UpdateNonResidentValue"],
            "on_disk": LOSER_NEW.decode("ascii"),
            "required_undo": LOSER_OLD.decode("ascii"),
        },
        "strict_layout_validation": True,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def compile_probe(tree: Path, work: Path, cc: str) -> Path:
    source = work / "multitx_probe.c"
    source.write_text(PROBE_C.lstrip())
    common = [
        cc, "-std=c11", "-D_GNU_SOURCE", "-D_FORTIFY_SOURCE=3",
        "-DHAVE_CONFIG_H", "-Wall", "-Wextra", "-Werror",
        f"-I{tree}", f"-I{tree / 'include'}", f"-I{tree / 'libntfs'}",
        f"-I{tree / 'src'}",
    ]
    objects = []
    for name in ("roothealth_replay_guard", "roothealth_replay_analysis",
                 "roothealth_recover",
                 "roothealth_playlog", "roothealth_write"):
        obj = work / f"{name}.o"
        run(common + ["-Wno-address-of-packed-member", "-c",
                      tree / "src" / f"{name}.c", "-o", obj],
            f"strict compile {name}")
        objects.append(obj)
    probe = work / "multitx-probe"
    run(common + [source, *objects, tree / "src" / "utils.o",
                  tree / "libntfs" / ".libs" / "libntfs.a", "-o", probe],
        "multitx probe link")
    return probe


def self_test(tree: Path, cc: str, work_dir: Path | None):
    require((tree / "src" / "mkntfs").is_file(), "tree mkntfs is missing")
    require((tree / "src" / "roothealth_replay_guard.c").is_file(),
            "hardened replay guard is missing")
    context = tempfile.TemporaryDirectory(prefix="roothealth-native-multitx.")
    work = work_dir.resolve() if work_dir else Path(context.name)
    if work_dir:
        require(not work.exists() or not any(work.iterdir()),
                "work directory must be empty")
        work.mkdir(parents=True, exist_ok=True)
    base = work / "base.img"
    fixture = work / "multitx.img"
    manifest_path = work / "multitx.json"
    with base.open("wb") as image:
        image.truncate(64 * 1024 * 1024)
    run([tree / "src" / "mkntfs", "-F", "-q", "-T", "-L", "RHREDO", base],
        "deterministic mkntfs")
    base_before = file_sha(base)
    manifest = build(base, fixture, manifest_path)
    require(file_sha(base) == base_before, "encoder changed base image")
    fixture_before = file_sha(fixture)
    probe = compile_probe(tree, work, cc)
    output = run([
        probe, fixture, manifest["winner"]["raw_lcn"] * PAGE,
        manifest["loser"]["raw_lcn"] * PAGE,
    ], "winner/loser plan-only probe")
    require(file_sha(fixture) == fixture_before,
            "plan-only replay changed fixture image")
    print(output.strip())
    print(json.dumps({
        "result": "PASS_REFUSAL",
        "actions": 7,
        "analysis_controls": 3,
        "winner_redo_actions": 0,
        "loser_undo_actions": 0,
        "typed_operations": 0,
        "fixture_sha256_before": fixture_before,
        "fixture_sha256_after": file_sha(fixture),
        "strict_layout_validation": True,
        "work_directory": str(work),
    }, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("self-test")
    check.add_argument("--tree", type=Path, required=True)
    check.add_argument("--cc", default="cc")
    check.add_argument("--work-dir", type=Path)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test(args.tree.resolve(), args.cc, args.work_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
