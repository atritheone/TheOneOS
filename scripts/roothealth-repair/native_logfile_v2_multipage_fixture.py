#!/usr/bin/env python3
"""Deterministic NTFS $LogFile v2.0 tail-copy and multi-page replay fixture.

The selected v2 tail-bank transfer contains a checkpoint, all four analysis
tables, one committed resident winner and one active nonresident loser.  Its
AttributeNamesDump begins in logical page 35 and ends in page 36, so both the
LFS multi-page-record flag and the two-page RCRD transfer must be honored.
The parser is invoked plan-only through RootHealth's typed persistent-WAL
backend; neither the image nor the planned target bytes are committed.
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
PAGE = 4096
DATA = 0x40
FIRST_V2_PAGE = 34
TRANSFER_FIRST = 35
TRANSFER_SECOND = 36
NAMES_SIZE = 3904
OLD_SIZES = [104, 184, 88, 184, 144, 152, 96, 88, 104, 88]
NEW_SIZES = [104, 184, NAMES_SIZE, 184, 144, 152, 96, 88, 104, 88]
EXPECTED_ACTIONS = 10
LOG_MULTI_PAGE = 1


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helper = load("v2_redo_helper", "native_logfile_redo_fixture.py")
checkpoint = load("v2_checkpoint_helper", "native_logfile_checkpoint_loser_fixture.py")
owned = load("v2_owned_helper", "native_logfile_multitx_owned_fixture.py")


PROBE_C = r"""
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_recover.h"
#include "roothealth_replay_guard.h"
#include "roothealth_write.h"

static const struct rh_write_backend_ops persistent_backend = {
	.persistent_undo = 1
};

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_log_result result;
	struct rh_replay_geometry large_geometry;
	uint64_t primary, mirror, raw, owner;
	size_t i;
	int rc;

	if (argc != 6)
		return 64;
	memset(&large_geometry, 0, sizeof(large_geometry));
	large_geometry.page_size = 4096U;
	large_geometry.cluster_size = 4096U;
	large_geometry.mft_record_size = 1024U;
	large_geometry.index_record_size = 4096U;
	large_geometry.logfile_size = RH_REPLAY_MAX_LOGFILE_SIZE;
	large_geometry.volume_clusters = UINT64_C(1024) * 1024U;
	large_geometry.sequence_bits = 40U;
	large_geometry.client_sequence = 1U;
	large_geometry.client_index = 0U;
	if (rh_replay_guard_profile(&large_geometry))
		return 68;
	large_geometry.logfile_size = UINT64_C(128) * 1024U * 1024U;
	large_geometry.sequence_bits = 39U;
	if (!rh_replay_guard_profile(&large_geometry))
		return 68;
	primary = strtoull(argv[2], NULL, 0);
	mirror = strtoull(argv[3], NULL, 0);
	raw = strtoull(argv[4], NULL, 0);
	owner = strtoull(argv[5], NULL, 0);
	if (rh_writer_open(&writer, argv[1]) ||
		rh_writer_set_backend(&writer, &persistent_backend, NULL))
		return 65;
	rc = roothealth_log_replay_plan(argv[1], &writer, &result);
	printf("plan_rc=%d state=%d version=%d.%d pages=%u/%u actions=%u "
	       "checkpoint=%u controls=%u mutations=%u redo=%u undo=%u "
	       "restart=%u unsupported=%u io_errors=%u parse_errors=%u "
	       "operations=%zu bytes=%" PRIu64 "\n",
	       rc, result.state, result.major_version, result.minor_version,
	       result.pages_examined, result.pages_expected, result.actions_seen,
	       result.checkpoint_records_examined,
	       result.control_records_examined,
	       result.mutation_records_examined, result.redo_actions,
	       result.undo_actions, result.restart_pages_planned,
	       result.unsupported_actions, result.io_errors, result.parse_errors,
	       writer.operation_count, writer.planned_bytes);
	if (rc || result.state != RH_NATIVE_LOG_REPLAY_PLANNED ||
		result.major_version != 2 || result.minor_version != 0 ||
		result.pages_expected != result.pages_examined ||
		result.actions_seen != 10 ||
		result.checkpoint_records_examined != 1 ||
		result.open_attribute_tables != 1 ||
		result.attribute_name_tables != 1 ||
		result.dirty_page_tables != 1 || result.transaction_tables != 1 ||
		result.redo_actions != 2 || result.undo_actions != 1 ||
		result.restart_pages_planned != 2 || result.unsupported_actions ||
		result.io_errors || result.parse_errors ||
		writer.operation_count != 5 || writer.planned_bytes != UINT64_C(14336) ||
		writer.operations[0].kind != RH_WRITE_LOGFILE_REDO ||
		writer.operations[0].offset != primary ||
		writer.operations[0].length != 1024U ||
		writer.operations[0].target.object !=
			RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
		writer.operations[0].target.owner_mft_record != 3U ||
		writer.operations[0].target.flags != (RH_WRITE_TARGET_PRIMARY |
			RH_WRITE_TARGET_RESIDENT | RH_WRITE_TARGET_NATIVE_LOG_DERIVED) ||
		writer.operations[1].kind != RH_WRITE_LOGFILE_REDO ||
		writer.operations[1].offset != mirror ||
		writer.operations[1].length != 1024U ||
		writer.operations[1].target.object !=
			RH_WRITE_TARGET_MFT_RECORD_MIRROR ||
		writer.operations[1].target.owner_mft_record != 3U ||
		writer.operations[1].target.owner_sequence !=
			writer.operations[0].target.owner_sequence ||
		writer.operations[1].target.flags != (RH_WRITE_TARGET_MIRROR |
			RH_WRITE_TARGET_RESIDENT | RH_WRITE_TARGET_NATIVE_LOG_DERIVED) ||
		writer.operations[2].kind != RH_WRITE_LOGFILE_REDO ||
		writer.operations[2].offset != raw ||
		writer.operations[2].length != 4096U ||
		writer.operations[2].target.object !=
			RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE ||
		writer.operations[2].target.owner_mft_record != owner ||
		writer.operations[2].target.attribute_type != 0x80U ||
		writer.operations[2].target.logical_vcn != 0 ||
		writer.operations[2].target.lcn != (int64_t)(raw / 4096U) ||
		writer.operations[2].target.flags != (RH_WRITE_TARGET_NONRESIDENT |
			RH_WRITE_TARGET_NATIVE_LOG_DERIVED) ||
		writer.operations[3].kind != RH_WRITE_LOGFILE_RESTART ||
		writer.operations[3].target.owner_mft_record != 2U ||
		writer.operations[3].target.attribute_type != 0x80U ||
		writer.operations[3].target.flags != (RH_WRITE_TARGET_NONRESIDENT |
			RH_WRITE_TARGET_NATIVE_LOG_DERIVED) ||
		writer.operations[4].kind != RH_WRITE_LOGFILE_RESTART ||
		writer.operations[4].target.owner_mft_record != 2U ||
		writer.operations[4].target.attribute_type != 0x80U ||
		writer.operations[4].target.flags != (RH_WRITE_TARGET_NONRESIDENT |
			RH_WRITE_TARGET_NATIVE_LOG_DERIVED)) {
		fprintf(stderr, "v2 multi-page winner/loser plan not proven\n");
		rh_writer_close(&writer);
		return 66;
	}
	for (i = 0; i < writer.operation_count; ++i) {
		if (!rh_write_operation_semantics_valid(&writer.operations[i], 0)) {
			fprintf(stderr, "typed semantic operation %zu is invalid\n", i);
			rh_writer_close(&writer);
			return 67;
		}
	}
	rh_writer_close(&writer);
	return 0;
}
"""


def require(condition: bool, message: str):
    if not condition:
        raise ValueError(message)


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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def action_starts(sizes: list[int]) -> list[tuple[int, int]]:
    starts = []
    page = TRANSFER_FIRST
    offset = DATA
    for size in sizes:
        require(offset <= PAGE - 80, "record header fits its first page")
        starts.append((page, offset))
        remaining = size
        available = PAGE - offset
        if remaining <= available:
            offset += remaining
            if offset == PAGE:
                page += 1
                offset = DATA
            continue
        remaining -= available
        while remaining > PAGE - DATA:
            page += 1
            remaining -= PAGE - DATA
        page += 1
        offset = DATA + remaining
    return starts


def restart_v2(current_lsn: int, oldest_lsn: int, restart_lsn: int,
               logfile_size: int, sequence_bits: int, usn: int) -> bytes:
    page = bytearray(PAGE)
    page[:4] = b"RSTR"
    struct.pack_into("<HHQIIHhhH", page, 4, 0x20, 9, 0, PAGE, PAGE,
                     0x40, 0, 2, usn)
    area = 0x40
    struct.pack_into("<QHHHHIHHQ", page, area, current_lsn, 1,
                     0xFFFF, 0, 0, sequence_bits, 0xE0, 0x40,
                     logfile_size)
    struct.pack_into("<IHHII", page, area + 32, 40, 0x30, 0x40, 1, 0)
    client = area + 0x40
    struct.pack_into("<QQHHH", page, client, oldest_lsn, restart_lsn,
                     0xFFFF, 0xFFFF, 1)
    struct.pack_into("<I", page, client + 28, 8)
    page[client + 32:client + 40] = "NTFS".encode("utf-16le")
    return helper.mst_protect(page, 0x20, usn)


def record_page_v2(*, physical: int, header_lsn: int, last_end_lsn: int,
                   next_offset: int, count: int, position: int,
                   file_offset: int, payload: bytes = b"",
                   flags: int = 1, usn: int = 0xD000) -> bytes:
    require(1 <= position <= count <= 16, "bounded v2 transfer geometry")
    require(next_offset == 0 or DATA <= next_offset <= PAGE,
            "bounded next-record offset")
    require(len(payload) <= PAGE - DATA, "page payload bound")
    page = bytearray(PAGE)
    page[:4] = b"RCRD"
    struct.pack_into("<HHQ", page, 4, 0x28, 9, header_lsn)
    struct.pack_into("<IHHH", page, 16, flags, count, position, next_offset)
    struct.pack_into("<Q", page, 32, last_end_lsn)
    struct.pack_into("<I", page, 60, file_offset)
    page[DATA:DATA + len(payload)] = payload
    return helper.mst_protect(page, 0x28, (usn + physical) & 0xFFFF or 1)


def extract_actions(image, runs) -> list[bytearray]:
    page = helper.mst_unprotect(
        helper.stream_read(image, runs, PAGE, 5 * PAGE, PAGE), PAGE
    )
    actions = []
    offset = DATA
    for size in OLD_SIZES:
        action = bytearray(page[offset:offset + size])
        require(len(action) == size and helper.u32(action, 24) + 48 == size,
                "source v1.1 action layout")
        actions.append(action)
        offset += size
    return actions


def rewrite_actions(actions: list[bytearray], logfile_size: int):
    starts = action_starts(NEW_SIZES)
    require(starts[0] == (35, 64) and starts[2] == (35, 352) and
            starts[3] == (36, 224) and starts[-1][0] == 36,
            "fixed two-page action placement")
    sequence_bits = 67 - logfile_size.bit_length()
    lsns = [helper.make_lsn(sequence_bits, page, offset)
            for page, offset in starts]

    names = bytearray(NAMES_SIZE)
    names[:80] = actions[2][:80]
    struct.pack_into("<I", names, 24, NAMES_SIZE - 48)
    struct.pack_into("<H", names, 40, LOG_MULTI_PAGE)
    actions[2] = names
    require([len(action) for action in actions] == NEW_SIZES,
            "expanded AttributeNamesDump")

    for index, action in enumerate(actions):
        previous = 0 if index in (0, 6) else lsns[index - 1]
        undo_next = 0 if index in (0, 5, 6) else previous
        struct.pack_into("<QQQ", action, 0, lsns[index], previous, undo_next)
    # Dirty-page table: both allocated entries bind their oldest LSN.
    struct.pack_into("<Q", actions[3], 128, lsns[0])
    struct.pack_into("<Q", actions[3], 168, lsns[0])
    # Transaction table: active loser's first/previous/undo-next chain.
    struct.pack_into("<QQQ", actions[4], 112, lsns[0], lsns[0], lsns[0])
    # NTFS_RESTART checkpoint and all four exact table references/lengths.
    struct.pack_into("<Q", actions[5], 56, lsns[0])
    for index in range(4):
        struct.pack_into("<Q", actions[5], 64 + 8 * index, lsns[1 + index])
    struct.pack_into("<I", actions[5], 100, NAMES_SIZE - 80)
    return starts, lsns, sequence_bits


def convert_to_v2(fixture: Path, manifest: dict) -> dict:
    with fixture.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        logfile_size, logfile_runs = helper.find_logfile(image, geometry)
        actions = extract_actions(image, logfile_runs)
        starts, lsns, sequence_bits = rewrite_actions(actions, logfile_size)
        page35 = b"".join(bytes(action) for action in actions[:2])
        first_names = PAGE - DATA - len(page35)
        require(first_names == 3744, "first cross-page fragment")
        page35 += bytes(actions[2][:first_names])
        page36 = bytes(actions[2][first_names:]) + b"".join(
            bytes(action) for action in actions[3:]
        )
        require(len(page35) == PAGE - DATA and len(page36) == 1016,
                "exact two-page payload lengths")
        pre_lsn = helper.make_lsn(sequence_bits, FIRST_V2_PAGE, DATA)
        stale35 = helper.make_lsn(sequence_bits, TRANSFER_FIRST, DATA)
        stale36 = helper.make_lsn(sequence_bits, TRANSFER_SECOND, DATA)

        helper.stream_write(image, logfile_runs, PAGE, 0,
                            b"\xff" * logfile_size)
        pages = {
            0: restart_v2(lsns[-1], lsns[0], lsns[-1], logfile_size,
                          sequence_bits, 0xC001),
            1: restart_v2(lsns[-1], lsns[0], lsns[-1], logfile_size,
                          sequence_bits, 0xC002),
            2: record_page_v2(
                physical=2, header_lsn=lsns[0], last_end_lsn=lsns[1],
                next_offset=starts[2][1], count=2, position=1,
                file_offset=TRANSFER_FIRST * PAGE, payload=page35,
            ),
            3: record_page_v2(
                physical=3, header_lsn=lsns[3], last_end_lsn=lsns[-1],
                next_offset=DATA + len(page36), count=2, position=2,
                file_offset=TRANSFER_SECOND * PAGE, payload=page36,
            ),
            FIRST_V2_PAGE: record_page_v2(
                physical=FIRST_V2_PAGE, header_lsn=pre_lsn,
                last_end_lsn=pre_lsn, next_offset=PAGE - 16,
                count=1, position=1, file_offset=0,
            ),
            TRANSFER_FIRST: record_page_v2(
                physical=TRANSFER_FIRST, header_lsn=stale35,
                last_end_lsn=stale35, next_offset=DATA,
                count=2, position=1, file_offset=0,
            ),
            TRANSFER_SECOND: record_page_v2(
                physical=TRANSFER_SECOND, header_lsn=stale36,
                last_end_lsn=stale36, next_offset=DATA,
                count=2, position=2, file_offset=0,
            ),
        }
        for number, page in pages.items():
            helper.stream_write(image, logfile_runs, PAGE,
                                number * PAGE, page)
        image.flush()
        os.fsync(image.fileno())
    manifest.update({
        "version": [2, 0],
        "first_data_page": FIRST_V2_PAGE,
        "tail_bank_pages": [2, 3],
        "tail_targets": [TRANSFER_FIRST, TRANSFER_SECOND],
        "multi_page_action": 2,
        "multi_page_action_size": NAMES_SIZE,
        "action_starts": starts,
        "action_lsns": lsns,
        "actions": EXPECTED_ACTIONS,
    })
    return manifest


def mutate_page(path: Path, number: int, mutate):
    with path.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        _, runs = helper.find_logfile(image, geometry)
        raw = helper.stream_read(image, runs, PAGE, number * PAGE, PAGE)
        page = helper.mst_unprotect(raw, PAGE)
        mutate(page)
        usn = (helper.u16(page, 0x28) + 1) & 0xFFFF or 1
        helper.stream_write(image, runs, PAGE, number * PAGE,
                            helper.mst_protect(page, 0x28, usn))
        image.flush()
        os.fsync(image.fileno())


def mutate_restart(path: Path, mutate):
    with path.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        _, runs = helper.find_logfile(image, geometry)
        for number in (0, 1):
            raw = helper.stream_read(image, runs, PAGE, number * PAGE, PAGE)
            page = helper.mst_unprotect(raw, PAGE)
            mutate(page)
            usn = (helper.u16(page, 0x20) + 1) & 0xFFFF or 1
            helper.stream_write(image, runs, PAGE, number * PAGE,
                                helper.mst_protect(page, 0x20, usn))
        image.flush()
        os.fsync(image.fileno())


def compile_probe(tree: Path, work: Path, cc: str) -> Path:
    source = work / "v2_multipage_probe.c"
    source.write_text(PROBE_C.lstrip())
    common = [
        cc, "-std=c11", "-D_GNU_SOURCE", "-D_FORTIFY_SOURCE=3",
        "-DHAVE_CONFIG_H", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
        f"-I{tree}", f"-I{tree / 'include'}", f"-I{tree / 'libntfs'}",
        f"-I{tree / 'src'}",
    ]
    objects = []
    for name in ("roothealth_replay_guard", "roothealth_replay_analysis",
                 "roothealth_recover", "roothealth_playlog",
                 "roothealth_write"):
        obj = work / f"{name}.o"
        run(common + ["-Wno-address-of-packed-member", "-c",
                      tree / "src" / f"{name}.c", "-o", obj],
            f"strict compile {name}")
        objects.append(obj)
    probe = work / "v2-multipage-probe"
    run(common + [source, *objects, tree / "src" / "utils.o",
                  tree / "libntfs" / ".libs" / "libntfs.a", "-o", probe],
        "v2 multi-page probe link")
    return probe


def expect_refusal(probe: Path, image: Path, manifest: dict, label: str):
    before = sha256(image)
    completed = subprocess.run([
        str(probe), str(image), str(manifest["primary_offset"]),
        str(manifest["mirror_offset"]), str(manifest["bitmap_offset"]),
        str(manifest["owned_inode"]),
    ], text=True, capture_output=True)
    require(completed.returncode == 66 and "plan_rc=-1" in completed.stdout and
            "operations=0" in completed.stdout,
            f"{label} did not fail closed\n{completed.stdout}\n{completed.stderr}")
    require(sha256(image) == before, f"{label} refusal modified image")


def prepare_base(tree: Path, work: Path) -> tuple[Path, int]:
    base = work / "base.img"
    with base.open("wb") as image:
        image.truncate(64 * 1024 * 1024)
    run([tree / "src" / "mkntfs", "-F", "-q", "-T", "-L", "RHREDO", base],
        "mkntfs v2 fixture base")
    payload = work / "v2-owned.bin"
    payload.write_bytes((b"ROOTHEALTH-V2-MULTIPAGE\0" * 512)[:8192])
    os.utime(payload, (946684800, 946684800))
    run([tree / "src" / "ntfscp", "-f", "-q", "-t", base, payload,
         "/rh-v2-owned.bin"], "create v2 owned stream")
    listing = run([tree / "src" / "ntfsls", "-f", "-i", "-l", "-p", "/",
                   base], "locate v2 owned stream")
    inodes = [int(match.group(1)) for line in listing.splitlines()
              if (match := re.match(
                  r"^\s*(\d+)\s+.*\brh-v2-owned\.bin\s*$", line))]
    require(len(inodes) == 1 and inodes[0] >= 24, "one v2 owned inode")
    owned.normalize_owned_timestamps(base, inodes[0], "rh-v2-owned.bin")
    return base, inodes[0]


def build_from_base(base: Path, inode: int, fixture: Path,
                    manifest_path: Path) -> dict:
    manifest = checkpoint.build(base, fixture, manifest_path, inode)
    manifest = convert_to_v2(fixture, manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def self_test(tree: Path, cc: str, work_dir: Path | None):
    context = tempfile.TemporaryDirectory(prefix="roothealth-v2-multipage.")
    work = work_dir.resolve() if work_dir else Path(context.name)
    if work_dir:
        require(not work.exists() or not any(work.iterdir()),
                "work directory must be empty")
        work.mkdir(parents=True, exist_ok=True)
    base, inode = prepare_base(tree, work)
    fixture = work / "v2-multipage.img"
    manifest_path = work / "v2-multipage.json"
    manifest = build_from_base(base, inode, fixture, manifest_path)
    before = sha256(fixture)
    probe = compile_probe(tree, work, cc)
    output = run([
        probe, fixture, manifest["primary_offset"], manifest["mirror_offset"],
        manifest["bitmap_offset"], manifest["owned_inode"],
    ], "v2 checkpoint winner/loser plan-only probe")
    require(sha256(fixture) == before, "v2 parser modified source image")

    negatives = []
    cases = [
        ("missing-multipage-flag", 2,
         lambda page: struct.pack_into("<H", page, 352 + 40, 0)),
        ("bad-transfer-position", 3,
         lambda page: struct.pack_into("<H", page, 22, 1)),
        ("unbounded-transfer-count", 2,
         lambda page: struct.pack_into("<H", page, 20, 17)),
        ("tail-file-offset-retarget", 2,
         lambda page: struct.pack_into("<I", page, 60, 37 * PAGE)),
        ("continuation-without-end", 3,
         lambda page: struct.pack_into("<I", page, 16, 0)),
        ("continuation-next-before-fragment", 3,
         lambda page: struct.pack_into("<H", page, 24, DATA + 8)),
    ]
    for label, page, mutate in cases:
        bad = work / f"negative-{label}.img"
        shutil.copyfile(fixture, bad)
        mutate_page(bad, page, mutate)
        expect_refusal(probe, bad, manifest, label)
        negatives.append(label)

    bad = work / "negative-spurious-multipage-flag.img"
    shutil.copyfile(fixture, bad)
    mutate_page(bad, 2, lambda page: struct.pack_into("<H", page, DATA + 40, 1))
    expect_refusal(probe, bad, manifest, "spurious-multipage-flag")
    negatives.append("spurious-multipage-flag")

    for label, version in (("legacy-v1.0", (0, 1)),
                           ("unknown-v2.1", (1, 2))):
        bad = work / f"negative-{label}.img"
        shutil.copyfile(fixture, bad)
        mutate_restart(bad, lambda page, pair=version:
                       struct.pack_into("<hh", page, 26, pair[0], pair[1]))
        expect_refusal(probe, bad, manifest, label)
        negatives.append(label)

    second = work / "v2-multipage-second.img"
    second_manifest = work / "v2-multipage-second.json"
    build_from_base(base, inode, second, second_manifest)
    require(sha256(second) == before, "v2 encoder is not byte deterministic")
    summary = {
        "result": "PASS",
        "version": "2.0",
        "actions": EXPECTED_ACTIONS,
        "redo_actions": 2,
        "undo_actions": 1,
        "restart_pages": 2,
        "typed_operations": 5,
        "planned_bytes": 14336,
        "profile_logfile_max_bytes": 64 * 1024 * 1024,
        "over_profile_logfile_bytes_rejected": 128 * 1024 * 1024,
        "rcrd_transfer_pages": 2,
        "multi_page_action_bytes": NAMES_SIZE,
        "negative_tests": negatives,
        "fixture_sha256_before_parser": before,
        "fixture_sha256_after_parser": sha256(fixture),
        "source_image_unchanged": True,
        "deterministic_double_build": True,
        "probe_output": output.strip(),
        "work_directory": str(work),
    }
    print(json.dumps(summary, sort_keys=True))
    if work_dir:
        context.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("self-test",))
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args()
    self_test(args.tree.resolve(), args.cc, args.work_dir)


if __name__ == "__main__":
    main()
