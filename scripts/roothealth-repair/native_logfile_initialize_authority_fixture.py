#!/usr/bin/env python3
"""Prove stale InitializeFileRecordSegment remains fail-closed.

The positive image contains an arbitrary, valid stale FILE record whose raw
header says IN_USE while the authoritative $MFT bitmap bit remains clear.  A
test-only provider can describe the provisional pre-transaction seal, but the
entry point must reject it before callback because the outer post-overlay seal
and WAL recovery verifier ABI are not frozen.  Provider-free and bitmap-
conflicting variants must also reject the whole native plan with no writes.
This is a blocker fixture, not an op2 qualification.
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
AT_BITMAP = 0xB0
TARGET_RECORD = 27


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


matrix = load("roothealth_initialize_matrix", "native_logfile_mutation_matrix_fixture.py")
helper = matrix.helper


PROBE_C = r"""
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_recover.h"
#include "roothealth_write.h"

static int callback_calls;

static const struct rh_write_backend_ops persistent_backend = {
	.persistent_undo = 1
};

static int authorize_initialize(void *opaque,
		const struct rh_replay_initialize_intent *intent,
		struct rh_replay_slot_authority_seal *seal)
{
	unsigned char *fill;

	(void)opaque;
	callback_calls++;
	if (!intent || !seal || intent->version !=
			RH_REPLAY_SLOT_AUTHORITY_SEAL_VERSION)
		return -1;
	memset(seal, 0, sizeof(*seal));
	seal->version = RH_REPLAY_SLOT_AUTHORITY_SEAL_VERSION;
	seal->generation = UINT64_C(7);
	seal->volume_serial = intent->volume_serial;
	seal->record_number = intent->record_number;
	seal->physical_offset = intent->physical_offset;
	seal->mft_vcn = intent->mft_vcn;
	seal->mft_lcn = intent->mft_lcn;
	seal->owner_sequence = intent->owner_sequence;
	memcpy(seal->journal_uuid, intent->journal_uuid,
		sizeof(seal->journal_uuid));
	memcpy(seal->raw_before_hash, intent->raw_before_hash,
		sizeof(seal->raw_before_hash));
	memcpy(seal->redo_payload_hash, intent->redo_payload_hash,
		sizeof(seal->redo_payload_hash));
	fill = seal->mft_bitmap_census_hash;
	memset(fill, 0x31, sizeof(seal->mft_bitmap_census_hash));
	memset(seal->namespace_census_hash, 0x52,
		sizeof(seal->namespace_census_hash));
	memset(seal->mft_extent_mapping_hash, 0x73,
		sizeof(seal->mft_extent_mapping_hash));
	seal->mft_slots_completed = intent->record_number + 1U;
	seal->namespace_entries_examined = UINT64_C(64);
	seal->identity_bound = 1U;
	seal->mft_bitmap_bit_clear = 1U;
	seal->namespace_census_complete = 1U;
	seal->slot_unreferenced = 1U;
	seal->extent_mapping_exact = 1U;
	seal->target_outside_wal = 1U;
	seal->target_outside_protected = 1U;
	return 0;
}

int main(int argc, char **argv)
{
	static const unsigned char journal_uuid[16] = {
		0x10, 0x21, 0x32, 0x43, 0x54, 0x65, 0x76, 0x87,
		0x98, 0xa9, 0xba, 0xcb, 0xdc, 0xed, 0xfe, 0x0f
	};
	struct rh_replay_slot_authority_provider provider;
	struct rh_writer writer;
	struct rh_log_result result;
	uint64_t serial;
	int provider_mode;
	int rc;

	if (argc != 4)
		return 64;
	serial = strtoull(argv[2], NULL, 0);
	provider_mode = !strcmp(argv[3], "provider");
	if (!provider_mode && strcmp(argv[3], "legacy") &&
			strcmp(argv[3], "bitmap-conflict"))
		return 64;
	memset(&provider, 0, sizeof(provider));
	provider.version = RH_REPLAY_SLOT_AUTHORITY_PROVIDER_VERSION;
	provider.expected_volume_serial = serial;
	memcpy(provider.expected_journal_uuid, journal_uuid,
		sizeof(provider.expected_journal_uuid));
	provider.authorize_initialize = authorize_initialize;
	if (rh_writer_open(&writer, argv[1]) ||
		rh_writer_set_backend(&writer, &persistent_backend, NULL))
		return 65;
	rc = provider_mode ? roothealth_log_replay_plan_authorized(argv[1],
		&writer, &provider, &result) :
		roothealth_log_replay_plan(argv[1], &writer, &result);
	printf("plan_rc=%d state=%d actions=%u redo=%u undo=%u restart=%u "
	       "unsupported=%u parse_errors=%u callback_calls=%d "
	       "operations=%zu bytes=%" PRIu64 "\n", rc, result.state,
	       result.actions_seen, result.redo_actions, result.undo_actions,
	       result.restart_pages_planned, result.unsupported_actions,
	       result.parse_errors, callback_calls, writer.operation_count,
	       writer.planned_bytes);
	if (rc != -1 || result.state != RH_NATIVE_LOG_UNKNOWN ||
		writer.operation_count || writer.planned_bytes || callback_calls ||
		(provider_mode && errno != EOPNOTSUPP)) {
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


def protect_record(record: bytes, usn: int) -> bytes:
    changed = bytearray(record)
    usa_offset = helper.u16(changed, 4)
    usa_count = helper.u16(changed, 6)
    require(len(changed) == 1024 and usa_count == 3, "stale FILE MST geometry")
    struct.pack_into("<H", changed, usa_offset, usn)
    for sector in range(1, usa_count):
        tail = sector * 512 - 2
        replacement = usa_offset + sector * 2
        changed[replacement:replacement + 2] = changed[tail:tail + 2]
        struct.pack_into("<H", changed, tail, usn)
    return bytes(changed)


def prepare_stale_file(path: Path):
    with path.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        stale = bytearray(matrix.minimal_file_record(image, geometry))
        struct.pack_into("<Q", stale, 8, 0)
        struct.pack_into("<H", stale, 16, 7)
        struct.pack_into("<H", stale, 22, 1)
        struct.pack_into("<I", stale, 44, TARGET_RECORD)
        physical = geometry["mft_lcn"] * PAGE + TARGET_RECORD * 1024
        image.seek(physical)
        require(image.write(protect_record(stale, 0x7A11)) == 1024,
                "write arbitrary stale FILE record")
        _, _, _, bitmap_runs = matrix.find_attr(image, geometry, 0, AT_BITMAP)
        bitmap_byte = TARGET_RECORD >> 3
        observed = helper.stream_read(image, bitmap_runs, PAGE, bitmap_byte, 1)[0]
        require(not observed & (1 << (TARGET_RECORD & 7)),
                "positive target MFT bitmap bit is clear")
        image.seek(72)
        serial = struct.unpack("<Q", image.read(8))[0]
        image.flush()
        os.fsync(image.fileno())
    return serial, bitmap_runs


def set_bitmap_conflict(path: Path):
    with path.open("r+b", buffering=0) as image:
        geometry = helper.parse_geometry(image)
        _, _, _, runs = matrix.find_attr(image, geometry, 0, AT_BITMAP)
        byte_at = TARGET_RECORD >> 3
        observed = helper.stream_read(image, runs, PAGE, byte_at, 1)[0]
        changed = observed | (1 << (TARGET_RECORD & 7))
        helper.stream_write(image, runs, PAGE, byte_at, bytes((changed,)))
        image.flush()
        os.fsync(image.fileno())


def compile_probe(tree: Path, work: Path, cc: str) -> Path:
    source = work / "initialize_authority_probe.c"
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
    probe = work / "initialize-authority-probe"
    run(common + [source, *objects, tree / "src" / "utils.o",
                  tree / "libntfs" / ".libs" / "libntfs.a", "-o", probe],
        "initialize authority probe link")
    return probe


def self_test(tree: Path, cc: str, work_dir: Path | None):
    context = tempfile.TemporaryDirectory(prefix="roothealth-init-authority.")
    work = work_dir.resolve() if work_dir else Path(context.name)
    if work_dir:
        require(not work.exists() or not any(work.iterdir()),
                "work directory must be empty")
        work.mkdir(parents=True, exist_ok=True)
    base = work / "base.img"
    positive = work / "stale-free.img"
    manifest = work / "matrix.json"
    with base.open("wb") as image:
        image.truncate(64 * 1024 * 1024)
    run([tree / "src" / "mkntfs", "-F", "-q", "-T", "-L", "RHREDO", base],
        "mkntfs initialize-authority base")
    matrix.build(base, positive, manifest)
    serial, _ = prepare_stale_file(positive)
    before = sha256(positive)
    probe = compile_probe(tree, work, cc)
    provider_output = run([probe, positive, serial, "provider"],
                          "provisional provider is unreachable")
    require(sha256(positive) == before, "provider refusal changed source image")

    legacy_output = run([probe, positive, serial, "legacy"],
                        "provider-free stale-FILE refusal")
    require(sha256(positive) == before, "legacy refusal changed source image")

    bitmap = work / "bitmap-conflict.img"
    shutil.copyfile(positive, bitmap)
    set_bitmap_conflict(bitmap)
    bitmap_before = sha256(bitmap)
    bitmap_output = run([probe, bitmap, serial, "bitmap-conflict"],
                        "MFT bitmap conflict refusal")
    require(sha256(bitmap) == bitmap_before, "bitmap refusal changed source image")

    print(provider_output, end="")
    print(json.dumps({
        "result": "PASS",
        "fixture_sha256_before": before,
        "fixture_sha256_after": sha256(positive),
        "stale_fixture": "arbitrary-stale-FILE-in-use-header-bitmap-clear",
        "negative_tests": [
            "provisional-provider-entrypoint-unreachable",
            "provider-free",
            "mft-bitmap-bit-set",
        ],
        "provider_probe": provider_output.strip(),
        "legacy_probe": legacy_output.strip(),
        "bitmap_probe": bitmap_output.strip(),
        "source_image_unchanged": True,
        "qualification_scope": "fail-closed-op2-blocker-only",
        "outer_namespace_census_pending": True,
        "wal_id5_verifier_pending": True,
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
