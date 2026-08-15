#!/usr/bin/env python3
"""Prove the exact native replay/WAL operation-count boundary.

The accepted log has 4,094 committed MFT mutations plus two restart-page
operations: exactly 4,096 typed WAL entries.  The refused log has 4,095 active
MFT mutations whose loser undo plus two restart pages would require 4,097
entries.  Both logs contain 4,096 structurally valid actions; the latter must
reset the complete plan and report an unsupported capacity issue before any
write.
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
PAGE = 4096
DATA = 0x40
FIRST_PAGE = 5
TARGET_RECORD = 24
AT_DATA = 0x80
AT_END = 0xFFFFFFFF


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helper = load("roothealth_capacity_helper", "native_logfile_redo_fixture.py")
matrix = load("roothealth_capacity_matrix", "native_logfile_mutation_matrix_fixture.py")


PROBE_C = r"""
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
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
	int accept;
	int rc;

	if (argc != 3 || (strcmp(argv[2], "accept") &&
			strcmp(argv[2], "refuse")))
		return 64;
	accept = !strcmp(argv[2], "accept");
	if (rh_writer_open(&writer, argv[1]) ||
		rh_writer_set_backend(&writer, &persistent_backend, NULL))
		return 65;
	rc = roothealth_log_replay_plan(argv[1], &writer, &result);
	printf("plan_rc=%d errno=%d state=%d latest=0x%016" PRIx64 " actions=%u "
	       "redo=%u undo=%u restart=%u "
	       "unsupported=%u io_errors=%u parse_errors=%u operations=%zu "
	       "bytes=%" PRIu64 "\n", rc, errno, result.state, result.latest_lsn,
	       result.actions_seen,
	       result.redo_actions, result.undo_actions,
	       result.restart_pages_planned, result.unsupported_actions,
	       result.io_errors, result.parse_errors, writer.operation_count,
	       writer.planned_bytes);
	if (accept) {
		if (rc || result.state != RH_NATIVE_LOG_REPLAY_PLANNED ||
			result.actions_seen != 4096U || result.redo_actions != 4094U ||
			result.undo_actions || result.restart_pages_planned != 2U ||
			result.unsupported_actions || result.io_errors ||
			result.parse_errors || writer.operation_count != 4096U ||
			writer.planned_bytes != UINT64_C(4200448)) {
			rh_writer_close(&writer);
			return 66;
		}
	} else if (rc != -1 || errno != EOPNOTSUPP ||
		result.state != RH_NATIVE_LOG_UNKNOWN ||
		result.actions_seen != 4096U || result.redo_actions ||
		result.undo_actions != 4095U || result.restart_pages_planned != 2U ||
		result.unsupported_actions != 1U || result.io_errors ||
		result.parse_errors || writer.operation_count || writer.planned_bytes) {
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


def positions(sizes: list[int]) -> list[tuple[int, int]]:
    output = []
    page = FIRST_PAGE
    offset = DATA
    for size in sizes:
        require(size % 8 == 0 and size <= PAGE - DATA, "bounded record size")
        if offset + size > PAGE:
            page += 1
            offset = DATA
        output.append((page, offset))
        offset += size
    return output


def bounded_page_sizes(base_sizes: list[int]) -> list[int]:
    sizes = list(base_sizes)
    starts = positions(sizes)
    final_page = starts[-1][0]
    for page in range(FIRST_PAGE, final_page):
        indexes = [index for index, start in enumerate(starts) if start[0] == page]
        last = indexes[-1]
        remaining = PAGE - (starts[last][1] + sizes[last])
        extension = ((remaining - 47 + 15) // 16) * 16
        require(extension in (32, 48) and sizes[last] == 104,
                "page tail is filled by one bounded update payload")
        sizes[last] += extension
    adjusted = positions(sizes)
    require([start[0] for start in adjusted] == [start[0] for start in starts],
            "tail padding does not move an action between pages")
    for page in range(FIRST_PAGE, final_page):
        indexes = [index for index, start in enumerate(adjusted)
                   if start[0] == page]
        last = indexes[-1]
        require(PAGE - (adjusted[last][1] + sizes[last]) < 48,
                "nonfinal page has no fake record-header space")
    return sizes


def resident_slice(record: bytes) -> tuple[int, int, bytes]:
    for offset, kind, nonresident, length in helper.iter_attributes(record):
        if kind == AT_END:
            break
        if nonresident or length < 32:
            continue
        value_length = helper.u32(record, offset + 16)
        value_offset = helper.u16(record, offset + 20)
        if value_length >= 25 and value_offset >= 24 and \
                value_offset + value_length <= length:
            within = value_offset + value_length - 25
            return offset, within, bytes(record[offset + within:offset + within + 25])
    raise ValueError("target record has no bounded resident 25-byte slice")


def encode_update(this_lsn: int, previous_lsn: int, target_lcn: int,
                  target_vcn: int, cluster_index: int, record_offset: int,
                  attribute_offset: int, redo: bytes, undo: bytes,
                  total_size: int) -> bytes:
    require(len(redo) == len(undo) and len(redo) in (2, 17, 25),
            "capacity update payload length")
    redo_padded = (len(redo) + 7) & ~7
    expected = (88 + redo_padded + len(undo) + 7) & ~7
    require(total_size == expected, "capacity update encoded size")
    record = helper.encode_common_record(
        total_size, this_lsn, previous_lsn, previous_lsn,
        helper.TRANSACTION_ID,
    )
    struct.pack_into("<HHHH", record, 48, helper.UPDATE_RESIDENT_VALUE,
                     helper.UPDATE_RESIDENT_VALUE, 0x28, len(redo))
    struct.pack_into("<HHHH", record, 56, 0x28 + redo_padded,
                     len(undo), 24, 1)
    struct.pack_into("<HHHHQ", record, 64, record_offset, attribute_offset,
                     cluster_index, helper.ACTS_ON_MFT, target_vcn)
    struct.pack_into("<Q", record, 80, target_lcn)
    record[88:88 + len(redo)] = redo
    undo_at = 88 + redo_padded
    record[undo_at:undo_at + len(undo)] = undo
    return bytes(record)


def protect_record(record: bytes, usn: int) -> bytes:
    changed = bytearray(record)
    usa_offset = helper.u16(changed, 4)
    usa_count = helper.u16(changed, 6)
    require(len(changed) == 1024 and usa_count == 3, "target FILE MST")
    struct.pack_into("<H", changed, usa_offset, usn)
    for sector in range(1, usa_count):
        tail = sector * 512 - 2
        replacement = usa_offset + sector * 2
        changed[replacement:replacement + 2] = changed[tail:tail + 2]
        struct.pack_into("<H", changed, tail, usn)
    return bytes(changed)


def build(base: Path, output: Path, loser: bool):
    shutil.copyfile(base, output)
    with output.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        logfile_size, logfile_runs = helper.find_logfile(image, geometry)
        require(helper.stream_read(image, logfile_runs, PAGE, 0, 120 * PAGE) ==
                b"\xff" * (120 * PAGE), "capacity seed log pages are wiped")
        _, mft_zero = helper.read_mft_record(image, geometry, 0)
        mft_reference = (helper.u16(mft_zero, 16) << 48) | 0
        _, target = helper.read_mft_record(image, geometry, TARGET_RECORD)
        record_offset, attribute_offset, first_value = resident_slice(target)
        _, _, _, mft_runs = matrix.find_attr(image, geometry, 0, AT_DATA)
        target_byte = TARGET_RECORD * 1024
        target_vcn = target_byte // PAGE
        cluster_index = (target_byte % PAGE) // 512
        target_lcn = matrix.lcn_for_vcn(mft_runs, target_vcn)
        mutations = 4095 if loser else 4094
        sizes = bounded_page_sizes(
            [120] + [104] * mutations + ([] if loser else [88])
        )
        starts = positions(sizes)
        sequence_bits = 67 - logfile_size.bit_length()
        lsns = [helper.make_lsn(sequence_bits, page, offset)
                for page, offset in starts]
        records = [helper.encode_open_mft_record(lsns[0], mft_reference)]
        previous = lsns[0]
        value = first_value
        for index in range(mutations):
            total_size = sizes[index + 1]
            payload_length = {104: 2, 136: 17, 152: 25}[total_size]
            # The widened tail records consume page slack without changing
            # additional semantic bytes; only the same two-byte value toggles
            # in every action.  This keeps every preapplied action at one of
            # its two exact endpoints even after later overlapping updates.
            after = bytes(
                value[position] ^ 0x5A if position < 2 else value[position]
                for position in range(payload_length)
            )
            records.append(encode_update(
                lsns[index + 1], previous, target_lcn, target_vcn,
                cluster_index, record_offset, attribute_offset,
                after, value[:payload_length], total_size,
            ))
            previous = lsns[index + 1]
            value = after + value[payload_length:]
        if not loser:
            records.append(helper.encode_forget_record(lsns[-1], previous))
        require([len(item) for item in records] == sizes,
                "capacity action sizes")

        by_page: dict[int, bytearray] = {}
        last_lsn: dict[int, int] = {}
        for (page, offset), lsn, record in zip(starts, lsns, records):
            payload = by_page.setdefault(page, bytearray())
            require(DATA + len(payload) == offset, "contiguous page records")
            payload.extend(record)
            last_lsn[page] = lsn
        final_page = starts[-1][0]
        pages = {
            0: helper.encode_restart_page(
                lsns[-1], lsns[0], 0 if loser else lsns[-1],
                logfile_size, sequence_bits, 0x6A01,
            ),
            1: helper.encode_restart_page(
                lsns[-1], lsns[0], 0 if loser else lsns[-1],
                logfile_size, sequence_bits, 0x6A02,
            ),
            2: helper.encode_record_page(
                2, FIRST_PAGE * PAGE, lsns[0], DATA, usn=0x6B00,
            ),
            3: helper.encode_record_page(
                3, FIRST_PAGE * PAGE, lsns[0] - 1, DATA, usn=0x6B00,
            ),
            4: helper.encode_record_page(
                4, lsns[0] - 1, lsns[0] - 1, PAGE - 16, usn=0x6B00,
            ),
        }
        for page in range(FIRST_PAGE, final_page + 1):
            payload = bytes(by_page[page])
            pages[page] = helper.encode_record_page(
                page, last_lsn[page], last_lsn[page], DATA + len(payload),
                records=payload, usn=0x6B00,
            )
        for page, encoded in pages.items():
            helper.stream_write(image, logfile_runs, PAGE, page * PAGE, encoded)

        if loser:
            changed = bytearray(target)
            changed[record_offset + attribute_offset:
                    record_offset + attribute_offset + 25] = value
            struct.pack_into("<Q", changed, 8, lsns[-1])
            physical = target_lcn * PAGE + (target_byte % PAGE)
            image.seek(physical)
            require(image.write(protect_record(changed, 0x6C01)) == 1024,
                    "materialize active loser after-image")
        image.flush()
        os.fsync(image.fileno())
    return {
        "actions": len(records),
        "mutations": mutations,
        "last_page": final_page,
        "latest_lsn": f"0x{lsns[-1]:016x}",
    }


def compile_probe(tree: Path, work: Path, cc: str) -> Path:
    source = work / "wal_capacity_probe.c"
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
    probe = work / "wal-capacity-probe"
    run(common + [source, *objects, tree / "src" / "utils.o",
                  tree / "libntfs" / ".libs" / "libntfs.a", "-o", probe],
        "WAL capacity probe link")
    return probe


def self_test(tree: Path, cc: str, work_dir: Path | None):
    context = tempfile.TemporaryDirectory(prefix="roothealth-wal-capacity.")
    work = work_dir.resolve() if work_dir else Path(context.name)
    if work_dir:
        require(not work.exists() or not any(work.iterdir()),
                "work directory must be empty")
        work.mkdir(parents=True, exist_ok=True)
    base = work / "base.img"
    accepted = work / "accepted-4096.img"
    refused = work / "refused-4097.img"
    with base.open("wb") as image:
        image.truncate(64 * 1024 * 1024)
    run([tree / "src" / "mkntfs", "-F", "-q", "-T", "-L", "RHCAP", base],
        "mkntfs capacity base")
    accepted_manifest = build(base, accepted, False)
    refused_manifest = build(base, refused, True)
    accepted_before = sha256(accepted)
    refused_before = sha256(refused)
    probe = compile_probe(tree, work, cc)
    accepted_output = run([probe, accepted, "accept"], "4096-entry acceptance")
    refused_output = run([probe, refused, "refuse"], "4097-entry refusal")
    require(sha256(accepted) == accepted_before, "accepted image changed")
    require(sha256(refused) == refused_before, "refused image changed")
    print(accepted_output, end="")
    print(refused_output, end="")
    print(json.dumps({
        "result": "PASS",
        "accepted": accepted_manifest,
        "accepted_operations": 4096,
        "accepted_target_bytes": 4200448,
        "refused": refused_manifest,
        "refused_operations_before_reset": 4097,
        "refused_reported_operations": 0,
        "refused_reported_bytes": 0,
        "wal_untouched": True,
        "source_images_unchanged": True,
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
