#!/usr/bin/env python3
"""Qualify native operations 3, 35 and 36 with exact typed-WAL plans.

The relative-index semantics are bound to the public
NtOfsRestartUpdateRelativeDataInIndex symbol in Windows 10 ntfs.sys
10.0.19041.5607 (SHA-256 4df3be53bc3048aed67dacfc3ea1be61c3d8fe2755669710c8ce604ce39884f1)
and ntfs.pdb GUID/age 1B07DFAFAF77AA5C245DF500C498DAB8/1.  Its 48-byte body reads a u16
relative offset from the selected entry and adds an unsigned 32- or 64-bit
delta at that location.  The fixture requires the undo delta to be the exact
modular inverse.  DeallocateFileRecordSegment follows the shipped T1OS ntfs3
fslog.c oracle: clear FILE IN_USE, increment sequence, and restore the logged
24-byte FILE header for loser undo.
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


matrix = load("roothealth_matrix_helper", "native_logfile_mutation_matrix_fixture.py")
helper = matrix.helper
legacy_multitx = load(
    "roothealth_legacy_multitx_helper", "native_logfile_multitx_fixture.py"
)

PAGE = 4096
DEALLOCATE_FILE_RECORD = 3
INITIALIZE_FILE_RECORD = 2
UPDATE_RELATIVE_ROOT = 35
UPDATE_RELATIVE_ALLOCATION = 36
MFT_ATTRIBUTE = matrix.MFT_ATTRIBUTE
INDEX_ATTRIBUTE = matrix.INDEX_ATTRIBUTE
ACTS_ON_MFT = matrix.ACTS_ON_MFT
ACTS_ON_INDX = matrix.ACTS_ON_INDX
TARGET_MFT_RECORD = 26


PROBE_C = r"""
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "roothealth_recover.h"
#include "roothealth_write.h"

extern int optv;

static const struct rh_write_backend_ops persistent_backend = {
	.persistent_undo = 1
};

int main(int argc, char **argv)
{
	static const unsigned int expected_kind[9] = {
		4U, 4U, 4U, 4U, 4U, 4U, 4U, 5U, 5U
	};
	static const uint64_t expected_offset[9] = {
		UINT64_C(44032), UINT64_C(40960), UINT64_C(18432),
		UINT64_C(33552384), UINT64_C(8818688), UINT64_C(8818688),
		UINT64_C(43008), UINT64_C(33554432), UINT64_C(33558528)
	};
	static const size_t expected_length[9] = {
		1024U, 1024U, 1024U, 1024U, 4096U, 4096U, 1024U, 4096U, 4096U
	};
	struct rh_writer writer;
	struct rh_log_result result;
	size_t i, j;
	int rc;

	if (argc != 2 && argc != 3)
		return 64;
	optv = 2;
	if (rh_writer_open(&writer, argv[1]) ||
		rh_writer_set_backend(&writer, &persistent_backend, NULL))
		return 65;
	if (argc == 3) {
		if (strcmp(argv[2], "--exclude-first-target") ||
			rh_writer_exclude(&writer, UINT64_C(44032), UINT64_C(1024))) {
			rh_writer_close(&writer);
			return 65;
		}
	}
	rc = roothealth_log_replay_plan(argv[1], &writer, &result);
	printf("plan_rc=%d actions=%u redo=%u undo=%u restart=%u "
	       "unsupported=%u parse_errors=%u operations=%zu bytes=%" PRIu64 "\n",
	       rc, result.actions_seen, result.redo_actions, result.undo_actions,
	       result.restart_pages_planned, result.unsupported_actions,
	       result.parse_errors, writer.operation_count, writer.planned_bytes);
	for (i = 0; i < writer.operation_count; ++i)
		printf("op=%zu kind=%u offset=%" PRIu64 " length=%" PRIu64 "\n",
		       i, (unsigned int)writer.operations[i].kind,
		       writer.operations[i].offset, writer.operations[i].length);
	if (rc || result.actions_seen != 10U || result.redo_actions != 3U ||
		result.undo_actions != 3U || result.restart_pages_planned != 2U ||
		result.unsupported_actions || result.parse_errors ||
		writer.operation_count != 9U || writer.planned_bytes != UINT64_C(21504)) {
		rh_writer_close(&writer);
		return 66;
	}
	for (i = 0; i < writer.operation_count; ++i) {
		if ((unsigned int)writer.operations[i].kind != expected_kind[i] ||
			writer.operations[i].offset != expected_offset[i] ||
			writer.operations[i].length != expected_length[i] ||
			!rh_write_operation_semantics_valid(&writer.operations[i], 0)) {
			rh_writer_close(&writer);
			return 67;
		}
		/* Every repeated target must capture the previously staged image. */
		for (j = i; j-- > 0U;) {
			if (writer.operations[j].kind == writer.operations[i].kind &&
				writer.operations[j].offset == writer.operations[i].offset &&
				writer.operations[j].length == writer.operations[i].length) {
				if (memcmp(writer.operations[i].before,
						writer.operations[j].after,
						writer.operations[i].length)) {
					rh_writer_close(&writer);
					return 68;
				}
				break;
			}
		}
	}
	if (writer.operations[0].target.owner_mft_record != 27U ||
		writer.operations[1].target.owner_mft_record != 24U ||
		writer.operations[2].target.owner_mft_record != 2U ||
		writer.operations[2].target.object !=
			RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
		writer.operations[3].target.owner_mft_record != 2U ||
		writer.operations[3].target.object !=
			RH_WRITE_TARGET_MFT_RECORD_MIRROR ||
		writer.operations[2].target.owner_sequence !=
			writer.operations[3].target.owner_sequence ||
		writer.operations[4].target.object !=
			RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE ||
		writer.operations[4].target.attribute_type != 0xa0U ||
		writer.operations[4].target.flags != (RH_WRITE_TARGET_NONRESIDENT |
			RH_WRITE_TARGET_NATIVE_LOG_DERIVED) ||
		writer.operations[6].target.owner_mft_record != 26U ||
		writer.operations[7].target.owner_mft_record != 2U ||
		writer.operations[8].target.owner_mft_record != 2U) {
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


def write_mft_record(image, geometry, number: int, record: bytes):
    require(len(record) == geometry["mft_record_size"], "MFT record size")
    usa_offset = helper.u16(record, 4)
    usn = (helper.u16(record, usa_offset) + 1) & 0xFFFF or 1
    protected = matrix.mst_protect_record(record, usa_offset, usn)
    image.seek(geometry["mft_lcn"] * PAGE + number * len(record))
    require(image.write(protected) == len(protected), "write MFT record")


def read_deallocation_target(image, geometry) -> bytes:
    _, record = helper.read_mft_record(image, geometry, TARGET_MFT_RECORD)
    require(helper.u16(record, 16), "deallocation target sequence")
    require(helper.u16(record, 22) & 1, "deallocation target is in use")
    return bytes(record)


def write_deallocation_after_image(image, geometry, before: bytes, lsn: int):
    after = bytearray(before)
    sequence = helper.u16(after, 16)
    require(sequence and sequence != 0xFFFF, "deallocation sequence increment")
    struct.pack_into("<Q", after, 8, lsn)
    struct.pack_into("<H", after, 16, sequence + 1)
    struct.pack_into("<H", after, 22, helper.u16(after, 22) & ~1)
    write_mft_record(image, geometry, TARGET_MFT_RECORD, bytes(after))


def prepare_allocation_view_entries(image, lcn: int, latest_lsn: int) -> int:
    image.seek(lcn * PAGE)
    index = bytearray(helper.mst_unprotect(image.read(PAGE), PAGE))
    require(index[:4] == b"INDX", "allocation view INDX")
    entries_offset = helper.u32(index, 24)
    entries_at = 24 + entries_offset
    require(entries_at <= PAGE - 64 and not (entries_at & 7),
            "allocation view entry capacity")
    index[entries_at:] = bytes(PAGE - entries_at)
    struct.pack_into("<HHI", index, entries_at, 16, 8, 0)
    struct.pack_into("<HHHH", index, entries_at + 8, 24, 0, 0, 0)
    index[entries_at + 16:entries_at + 24] = b"ENTRYNEW"
    second = entries_at + 24
    struct.pack_into("<HHI", index, second, 16, 8, 0)
    struct.pack_into("<HHHH", index, second + 8, 24, 0, 0, 0)
    struct.pack_into("<Q", index, second + 16, 105)
    end = second + 24
    struct.pack_into("<HHH", index, end + 8, 16, 0, 2)
    struct.pack_into("<I", index, 28, entries_offset + 64)
    struct.pack_into("<Q", index, 8, latest_lsn)
    usa_offset = helper.u16(index, 4)
    usn = (helper.u16(index, usa_offset) + 1) & 0xFFFF or 1
    protected = helper.mst_protect(index, usa_offset, usn)
    image.seek(lcn * PAGE)
    require(image.write(protected) == PAGE, "write allocation view INDX")
    return second


def prepare_root_view_entry(image, geometry):
    _, original = helper.read_mft_record(image, geometry, matrix.INDEX_OWNER_RECORD)
    record = bytearray(original)
    root_attr = None
    for offset, kind, nonresident, _ in helper.iter_attributes(record):
        if kind != 0x90 or nonresident or record[offset + 9] != 5:
            continue
        name_at = helper.u16(record, offset + 10)
        if bytes(record[offset + name_at:offset + name_at + 10]) == \
                "$TEST".encode("utf-16le"):
            root_attr = offset
            break
    require(root_attr is not None, "synthetic $TEST INDEX_ROOT")
    value_at = root_attr + helper.u16(record, root_attr + 20)
    value_length = helper.u32(record, root_attr + 16)
    require(helper.u32(record, value_at) == 0, "view-index indexed type")
    header_at = value_at + 16
    entries_offset = helper.u32(record, header_at)
    index_length = helper.u32(record, header_at + 4)
    allocated = helper.u32(record, header_at + 8)
    require(index_length == allocated and value_length == 16 + index_length,
            "packed INDEX_ROOT geometry")
    entries_at = header_at + entries_offset
    available = index_length - entries_offset
    require(available >= 40 and not (available & 7), "root entry capacity")
    record[entries_at:entries_at + available] = bytes(available)
    struct.pack_into("<HHI", record, entries_at, 16, 8, 0)
    struct.pack_into("<HHHH", record, entries_at + 8, 24, 0, 0, 0)
    struct.pack_into("<Q", record, entries_at + 16, 100)
    end_at = entries_at + 24
    struct.pack_into("<HHH", record, end_at + 8, available - 24, 0, 2)
    write_mft_record(image, geometry, matrix.INDEX_OWNER_RECORD, bytes(record))
    return root_attr, entries_at - root_attr


def replace_action(page: bytearray, offset: int, size: int, **values):
    previous = bytes(page[offset:offset + size])
    action = matrix.encode_action(
        this_lsn=helper.u64(previous, 0),
        previous_lsn=helper.u64(previous, 8),
        undo_lsn=helper.u64(previous, 16),
        transaction=helper.u32(previous, 36),
        **values,
    )
    require(len(action) == size, "replacement action preserves record size")
    page[offset:offset + size] = action


def transform(fixture: Path, manifest: dict):
    with fixture.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        logfile_size, logfile_runs = helper.find_logfile(image, geometry)
        mft_record, _, _, mft_runs = matrix.find_attr(image, geometry, 0, 0x80)
        mft_reference = (helper.u16(mft_record, 16) << 48) | 0
        require(mft_reference, "$MFT reference")
        deallocation = read_deallocation_target(image, geometry)
        root_attr, root_entry_relative = prepare_root_view_entry(image, geometry)
        raw = helper.stream_read(
            image, logfile_runs, PAGE, matrix.TARGET_PAGE * PAGE, PAGE
        )
        page = bytearray(helper.mst_unprotect(raw, PAGE))
        offsets = manifest["record_offsets"]
        sizes = [offsets[i + 1] - offsets[i] for i in range(len(offsets) - 1)]
        sizes.append(helper.u16(page, 24) - offsets[-1])

        target_byte = TARGET_MFT_RECORD * geometry["mft_record_size"]
        target_vcn = target_byte // PAGE
        target_index = (target_byte % PAGE) // 512
        target_lcn = matrix.lcn_for_vcn(mft_runs, target_vcn)
        write_deallocation_after_image(
            image, geometry, deallocation, helper.u64(page, offsets[7])
        )
        replace_action(
            page, offsets[7], sizes[7], redo_operation=DEALLOCATE_FILE_RECORD,
            undo_operation=INITIALIZE_FILE_RECORD, lcn=target_lcn,
            target_vcn=target_vcn, cluster_index=target_index,
            record_offset=0, attribute_offset=0,
            attribute_flags=ACTS_ON_MFT, target_attribute=MFT_ATTRIBUTE,
            redo=b"", undo=deallocation[:24],
        )

        root_byte = matrix.INDEX_OWNER_RECORD * geometry["mft_record_size"]
        root_vcn = root_byte // PAGE
        root_index = (root_byte % PAGE) // 512
        root_lcn = matrix.lcn_for_vcn(mft_runs, root_vcn)
        replace_action(
            page, offsets[4], sizes[4], redo_operation=UPDATE_RELATIVE_ROOT,
            undo_operation=UPDATE_RELATIVE_ROOT, lcn=root_lcn,
            target_vcn=root_vcn, cluster_index=root_index,
            record_offset=root_attr, attribute_offset=root_entry_relative,
            attribute_flags=ACTS_ON_MFT, target_attribute=MFT_ATTRIBUTE,
            redo=struct.pack("<Q", 3), undo=struct.pack("<Q", (-3) & ((1 << 64) - 1)),
        )

        old_allocation = bytes(page[offsets[8]:offsets[8] + sizes[8]])
        allocation_lcn = helper.u64(old_allocation, 80)
        allocation_vcn = helper.u64(old_allocation, 72)
        allocation_entry = prepare_allocation_view_entries(
            image, allocation_lcn, helper.u64(page, offsets[9])
        )
        replace_action(
            page, offsets[8], sizes[8],
            redo_operation=UPDATE_RELATIVE_ALLOCATION,
            undo_operation=UPDATE_RELATIVE_ALLOCATION,
            lcn=allocation_lcn, target_vcn=allocation_vcn, cluster_index=0,
            record_offset=0, attribute_offset=allocation_entry,
            attribute_flags=ACTS_ON_INDX, target_attribute=INDEX_ATTRIBUTE,
            redo=struct.pack("<Q", 5), undo=struct.pack("<Q", (-5) & ((1 << 64) - 1)),
        )

        # This fixture qualifies operations 3/35/36, not allocation authority.
        # Materialize the preceding Initialize action's exact after-image and
        # LSN so replay proves it already applied and reaches the three target
        # actions without weakening the typed writer's free-slot gate.
        initialize_at = offsets[2]
        initialize_length = helper.u16(page, initialize_at + 54)
        require(initialize_length == geometry["mft_record_size"],
                "full Initialize after-image")
        initialize = bytearray(page[
            initialize_at + 88:initialize_at + 88 + initialize_length
        ])
        struct.pack_into("<Q", initialize, 8, helper.u64(page, initialize_at))
        struct.pack_into("<H", initialize, 22, helper.u16(initialize, 22) | 1)
        write_mft_record(image, geometry, matrix.MFT_RECORD, bytes(initialize))
        _, materialized_initialize = helper.read_mft_record(
            image, geometry, matrix.MFT_RECORD
        )
        page[initialize_at + 88:initialize_at + 88 + initialize_length] = \
            materialized_initialize
        usa_offset = helper.u16(page, 4)
        usn = (helper.u16(page, usa_offset) + 1) & 0xFFFF or 1
        protected = helper.mst_protect(page, usa_offset, usn)
        helper.stream_write(
            image, logfile_runs, PAGE, matrix.TARGET_PAGE * PAGE, protected
        )
        image.flush()
        os.fsync(image.fileno())
    manifest.update({
        "deallocation_offset": target_lcn * PAGE + target_index * 512,
        "relative_root_offset": root_lcn * PAGE + root_index * 512,
        "relative_allocation_offset": allocation_lcn * PAGE,
        "standard_action_offsets": [offsets[7], offsets[4], offsets[8]],
        "logfile_size": logfile_size,
        "preapplied_initialize": True,
    })


def tamper_action(path: Path, action_offset: int, mutate):
    with path.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        _, runs = helper.find_logfile(image, geometry)
        raw = helper.stream_read(image, runs, PAGE, matrix.TARGET_PAGE * PAGE, PAGE)
        page = bytearray(helper.mst_unprotect(raw, PAGE))
        mutate(page, action_offset)
        usa_offset = helper.u16(page, 4)
        usn = (helper.u16(page, usa_offset) + 1) & 0xFFFF or 1
        helper.stream_write(
            image, runs, PAGE, matrix.TARGET_PAGE * PAGE,
            helper.mst_protect(page, usa_offset, usn),
        )
        image.flush()
        os.fsync(image.fileno())


def compile_probe(tree: Path, work: Path, cc: str) -> Path:
    source = work / "standard_ops_probe.c"
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
    probe = work / "standard-ops-probe"
    run(common + [source, *objects, tree / "src" / "utils.o",
                  tree / "libntfs" / ".libs" / "libntfs.a", "-o", probe],
        "standard operations probe link")
    return probe


def build_fixture(tree: Path, work: Path, name: str):
    base = work / f"{name}-base.img"
    fixture = work / f"{name}.img"
    seed_manifest = work / f"{name}-seed.json"
    with base.open("wb") as image:
        image.truncate(64 * 1024 * 1024)
    run([tree / "src" / "mkntfs", "-F", "-q", "-T", "-L", "RHSTD", base],
        "mkntfs standard-op base")
    manifest = matrix.build(base, fixture, seed_manifest)
    transform(fixture, manifest)
    return fixture, manifest


def rejected_zero_plan(
    probe: Path, image: Path, description: str, extra_args: tuple[str, ...] = ()
):
    before = file_sha(image)
    result = subprocess.run(
        [str(probe), str(image), *extra_args], text=True, capture_output=True
    )
    require(result.returncode == 66 and "plan_rc=-1" in result.stdout and
            "operations=0" in result.stdout, description)
    require(file_sha(image) == before, f"{description}: image changed")


def self_test(tree: Path, cc: str, work_dir: Path | None):
    context = tempfile.TemporaryDirectory(prefix="roothealth-standard-ops.")
    work = work_dir.resolve() if work_dir else Path(context.name)
    if work_dir:
        require(not work.exists() or not any(work.iterdir()),
                "work directory must be empty")
        work.mkdir(parents=True, exist_ok=True)
    fixture, manifest = build_fixture(tree, work, "standard-ops")
    second, _ = build_fixture(tree, work, "standard-ops-repeat")
    before = file_sha(fixture)
    require(file_sha(second) == before, "deterministic double build")
    probe = compile_probe(tree, work, cc)
    output = run([probe, fixture], "standard operations plan-only probe")
    require(file_sha(fixture) == before, "parser modified standard-op image")

    bad_header = work / "bad-deallocation-header.img"
    shutil.copyfile(fixture, bad_header)
    tamper_action(
        bad_header, manifest["standard_action_offsets"][0],
        lambda page, at: struct.pack_into("<H", page, at + 88 + 16, 0),
    )
    rejected_zero_plan(probe, bad_header, "zero FILE before-image sequence")

    bad_inverse = work / "bad-relative-inverse.img"
    shutil.copyfile(fixture, bad_inverse)
    tamper_action(
        bad_inverse, manifest["standard_action_offsets"][2],
        lambda page, at: struct.pack_into("<Q", page, at + 96, 7),
    )
    rejected_zero_plan(probe, bad_inverse, "non-inverse relative delta")

    bad_target = work / "bad-relative-target.img"
    shutil.copyfile(fixture, bad_target)
    with bad_target.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        _, record = helper.read_mft_record(image, geometry, matrix.INDEX_OWNER_RECORD)
        changed = bytearray(record)
        action_at = manifest["standard_action_offsets"][1]
        _, runs = helper.find_logfile(image, geometry)
        page = helper.mst_unprotect(helper.stream_read(
            image, runs, PAGE, matrix.TARGET_PAGE * PAGE, PAGE
        ), PAGE)
        entry_at = helper.u16(page, action_at + 64) + helper.u16(page, action_at + 66)
        struct.pack_into("<H", changed, entry_at, 0xFFF8)
        write_mft_record(image, geometry, matrix.INDEX_OWNER_RECORD, bytes(changed))
        image.flush()
        os.fsync(image.fileno())
    rejected_zero_plan(probe, bad_target, "out-of-entry relative target")

    rejected_zero_plan(
        probe, fixture, "semantic target exclusion",
        ("--exclude-first-target",),
    )

    legacy_base = work / "legacy-bitmap-raw-base.img"
    legacy_fixture = work / "legacy-bitmap-raw.img"
    legacy_manifest = work / "legacy-bitmap-raw.json"
    with legacy_base.open("wb") as image:
        image.truncate(64 * 1024 * 1024)
    run([tree / "src" / "mkntfs", "-F", "-q", "-T", "-L", "RHBRAW",
         legacy_base], "mkntfs legacy raw-bitmap base")
    legacy_multitx.build(legacy_base, legacy_fixture, legacy_manifest)
    rejected_zero_plan(
        probe, legacy_fixture, "arbitrary raw $Bitmap target",
    )

    print(output, end="")
    print(json.dumps({
        "result": "PASS",
        "fixture_sha256_before": before,
        "fixture_sha256_after": file_sha(fixture),
        "deterministic_double_build": True,
        "actions": 10,
        "redo": 3,
        "undo": 3,
        "qualified_operations": [
            "DeallocateFileRecordSegment",
            "UpdateRelativeDataInIndex",
            "UpdateRelativeDataInIndex2",
        ],
        "negative_tests": [
            "zero-file-before-image-sequence",
            "non-inverse-relative-delta",
            "out-of-entry-relative-target",
            "semantic-target-exclusion",
            "arbitrary-raw-$Bitmap-target",
        ],
        "source_image_unchanged": True,
        "work_directory": str(work),
    }, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    test = sub.add_parser("self-test")
    test.add_argument("--tree", type=Path, required=True)
    test.add_argument("--cc", default="cc")
    test.add_argument("--work-dir", type=Path)
    args = parser.parse_args()
    self_test(args.tree.resolve(), args.cc, args.work_dir)


if __name__ == "__main__":
    main()
