#!/usr/bin/env python3
"""Run the mixed winner/loser replay fixture against an owned user stream.

The historical fixture used record 6 ($Bitmap) as convenient nonresident test
storage.  RootHealth now correctly rejects generic raw mutations of that fixed
metadata stream.  This wrapper creates a deterministic nonresident user file,
redirects only the fixture's raw target to that owned stream, and retains the
original seven-action winner/active-loser log and plan-only assertions.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile


HERE = Path(__file__).resolve().parent


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mixed = load_module("roothealth_native_multitx", "native_logfile_multitx_fixture.py")


OWNED_PROBE_C = r"""
#include "config.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_recover.h"
#include "roothealth_write.h"

static int bytes_at(const struct rh_write_operation *op, size_t at,
		const char expected[8], int after)
{
	const unsigned char *data = after ? op->after : op->before;

	return at > op->length || 8 > op->length - at ||
		memcmp(data + at, expected, 8);
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_log_result result;
	uint64_t winner_offset, loser_offset;
	int rc;

	if (argc != 4)
		return 64;
	winner_offset = strtoull(argv[2], NULL, 0);
	loser_offset = strtoull(argv[3], NULL, 0);
	if (rh_writer_open(&writer, argv[1]))
		return 65;
	rc = roothealth_log_replay_plan(argv[1], &writer, &result);
	printf("plan_rc=%d actions=%u redo=%u undo=%u restart=%u operations=%zu bytes=%" PRIu64 "\n",
		rc, result.actions_seen, result.redo_actions, result.undo_actions,
		result.restart_pages_planned, writer.operation_count,
		writer.planned_bytes);
	if (rc || result.major_version != 1 || result.minor_version != 1 ||
		result.actions_seen != 7 || result.redo_actions != 3 ||
		result.undo_actions != 1 || result.restart_pages_planned != 2 ||
		writer.operation_count != 4 || writer.planned_bytes != UINT64_C(16384) ||
		winner_offset != loser_offset ||
		writer.operations[0].kind != RH_WRITE_LOGFILE_REDO ||
		writer.operations[0].offset != winner_offset ||
		writer.operations[0].length != 4096 ||
		bytes_at(&writer.operations[0], 128, "WIN-OLD!", 0) ||
		bytes_at(&writer.operations[0], 128, "WIN-NEW!", 1) ||
		writer.operations[1].kind != RH_WRITE_LOGFILE_REDO ||
		writer.operations[1].offset != loser_offset ||
		writer.operations[1].length != 4096 ||
		memcmp(writer.operations[1].before, writer.operations[0].after, 4096) ||
		bytes_at(&writer.operations[1], 128, "WIN-NEW!", 0) ||
		bytes_at(&writer.operations[1], 128, "WIN-NEW!", 1) ||
		bytes_at(&writer.operations[1], 256, "LOSE-NEW", 0) ||
		bytes_at(&writer.operations[1], 256, "LOSE-OLD", 1) ||
		writer.operations[2].kind != RH_WRITE_LOGFILE_RESTART ||
		writer.operations[2].offset != UINT64_C(33554432) ||
		writer.operations[2].length != 4096 ||
		writer.operations[3].kind != RH_WRITE_LOGFILE_RESTART ||
		writer.operations[3].offset != UINT64_C(33558528) ||
		writer.operations[3].length != 4096) {
		fprintf(stderr, "owned winner/loser staged plan was not proven\n");
		rh_writer_close(&writer);
		return 66;
	}
	rh_writer_close(&writer);
	return 0;
}
"""


def protect_mst(page: bytearray, usn: int) -> bytes:
    sector_size = 512
    usa_offset = mixed.helper.u16(page, 4)
    usa_count = mixed.helper.u16(page, 6)
    mixed.require(usa_count == 1 + len(page) // sector_size,
                  "owned object has exact MST geometry")
    mixed.require(usa_offset >= 8 and usa_offset + 2 * usa_count <= len(page),
                  "owned object USA lies inside object")
    struct.pack_into("<H", page, usa_offset, usn)
    for sector in range(1, usa_count):
        tail = sector * sector_size - 2
        replacement = usa_offset + 2 * sector
        page[replacement:replacement + 2] = page[tail:tail + 2]
        struct.pack_into("<H", page, tail, usn)
    return bytes(page)


def normalize_owned_timestamps(image_path: Path, inode: int, name: str) -> None:
    encoded_name = name.encode("utf-16le")
    with image_path.open("r+b", buffering=0) as image:
        geometry = mixed.helper.parse_geometry(image)
        record_offset, record = mixed.helper.read_mft_record(image, geometry, inode)
        normalized = 0
        for offset, attr_type, nonresident, length in mixed.helper.iter_attributes(record):
            if nonresident or attr_type not in (0x10, 0x30):
                continue
            value_offset = offset + mixed.helper.u16(record, offset + 20)
            value_length = mixed.helper.u32(record, offset + 16)
            first_timestamp = value_offset if attr_type == 0x10 else value_offset + 8
            mixed.require(first_timestamp + 32 <= value_offset + value_length and
                          value_offset + value_length <= offset + length,
                          "owned timestamp fields lie inside resident attribute")
            record[first_timestamp:first_timestamp + 32] = bytes(32)
            normalized += 1
            if normalized == 2:
                break
        mixed.require(normalized == 2,
                      "owned FILE record has standard-information and file-name times")
        image.seek(record_offset)
        image.write(protect_mst(record, 0xA501))

        index = mixed.find_data_stream(
            image, geometry, 5, mixed.AT_INDEX_ALLOCATION, "$I30"
        )
        found = 0
        for stream_offset in range(0, index["size"], mixed.PAGE):
            raw = mixed.helper.stream_read(
                image, index["runs"], mixed.PAGE, stream_offset, mixed.PAGE
            )
            if raw == bytes(mixed.PAGE):
                continue
            block = mixed.helper.mst_unprotect(raw, mixed.PAGE)
            mixed.require(block[:4] == b"INDX", "owned root index block magic")
            cursor = 24 + mixed.helper.u32(block, 24)
            end = 24 + mixed.helper.u32(block, 28)
            mixed.require(24 <= cursor <= end <= mixed.PAGE,
                          "owned root index entry bounds")
            while cursor + 16 <= end:
                entry_length = mixed.helper.u16(block, cursor + 8)
                key_length = mixed.helper.u16(block, cursor + 10)
                flags = mixed.helper.u16(block, cursor + 12)
                mixed.require(entry_length >= 16 and cursor + entry_length <= end,
                              "owned root index entry length")
                if key_length >= 66 and key_length <= entry_length - 16:
                    key = cursor + 16
                    name_length = block[key + 64]
                    candidate = bytes(block[key + 66:key + 66 + 2 * name_length])
                    if candidate == encoded_name:
                        mixed.require(key + 40 <= cursor + 16 + key_length,
                                      "owned index timestamp fields in key")
                        block[key + 8:key + 40] = bytes(32)
                        found += 1
                cursor += entry_length
                if flags & 2:
                    break
            if found:
                mixed.helper.stream_write(
                    image, index["runs"], mixed.PAGE, stream_offset,
                    protect_mst(block, 0xA502),
                )
        mixed.require(found == 1, "exactly one owned root index entry normalized")


def user_inode(tree: Path, image: Path, work: Path) -> int:
    payload = work / "rh-native-payload.bin"
    payload.write_bytes((b"ROOTHEALTH-NATIVE-REPLAY\x00" * 512)[:8192])
    os.utime(payload, (946684800, 946684800))
    mixed.run([
        tree / "src" / "ntfscp", "-f", "-q", "-t", image, payload,
        "/rh-native.bin",
    ], "create deterministic owned nonresident stream")
    listing = mixed.run([
        tree / "src" / "ntfsls", "-f", "-i", "-l", "-p", "/", image,
    ], "locate deterministic owned stream")
    matches = [
        int(match.group(1)) for line in listing.splitlines()
        if (match := re.match(r"^\s*(\d+)\s+.*\brh-native\.bin\s*$", line))
    ]
    mixed.require(len(matches) == 1, "exactly one owned stream inode")
    mixed.require(matches[0] >= 24, "owned stream is outside fixed metadata records")
    normalize_owned_timestamps(image, matches[0], "rh-native.bin")
    return matches[0]


def self_test(tree: Path, cc: str, work_dir: Path | None) -> None:
    for tool in ("mkntfs", "ntfscp", "ntfsls"):
        mixed.require((tree / "src" / tool).is_file(), f"tree {tool} is missing")
    context = tempfile.TemporaryDirectory(prefix="roothealth-native-owned-multitx.")
    work = work_dir.resolve() if work_dir else Path(context.name)
    if work_dir:
        mixed.require(not work.exists() or not any(work.iterdir()),
                      "work directory must be empty")
        work.mkdir(parents=True, exist_ok=True)
    base = work / "base.img"
    output = work / "multitx-owned.img"
    manifest_path = work / "multitx-owned.json"
    with base.open("wb") as image:
        image.truncate(64 * 1024 * 1024)
    mixed.run([
        tree / "src" / "mkntfs", "-F", "-q", "-T", "-L", "RHOWNED", base,
    ], "deterministic mkntfs")
    inode = user_inode(tree, base, work)
    base_before = mixed.file_sha(base)

    original_find = mixed.find_data_stream

    def owned_find(image, geometry, target_inode: int, attr_type: int,
                   name: str = ""):
        if target_inode == 6 and attr_type == mixed.AT_DATA and not name:
            return original_find(image, geometry, inode, attr_type, name)
        return original_find(image, geometry, target_inode, attr_type, name)

    mixed.find_data_stream = owned_find
    try:
        manifest = mixed.build(base, output, manifest_path)
    finally:
        mixed.find_data_stream = original_find
    mixed.require(mixed.file_sha(base) == base_before,
                  "encoder changed its owned-stream base")
    before = mixed.file_sha(output)
    original_probe = mixed.PROBE_C
    mixed.PROBE_C = OWNED_PROBE_C
    try:
        probe = mixed.compile_probe(tree, work, cc)
    finally:
        mixed.PROBE_C = original_probe
    planned = mixed.run([
        probe, output,
        manifest["winner"]["raw_lcn"] * mixed.PAGE,
        manifest["loser"]["raw_lcn"] * mixed.PAGE,
    ], "owned winner/loser plan-only probe")
    mixed.require(mixed.file_sha(output) == before,
                  "plan-only replay changed owned-stream fixture")
    print(planned.strip())
    print(json.dumps({
        "result": "PASS",
        "profile": "owned-user-stream",
        "owned_inode": inode,
        "actions": 7,
        "analysis_controls": 3,
        "winner_redo_actions": 3,
        "loser_undo_actions": 1,
        "typed_operations": 4,
        "planned_bytes": 16384,
        "fixture_sha256_before": before,
        "fixture_sha256_after": mixed.file_sha(output),
        "strict_layout_validation": True,
        "fixed_metadata_raw_target_refused": True,
        "work_directory": str(work),
    }, sort_keys=True))
    if not work_dir:
        context.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("self-test",))
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args()
    self_test(args.tree.resolve(), args.cc, args.work_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
