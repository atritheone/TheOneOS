#!/usr/bin/env python3
"""Qualify the exact all-0xff T1OS $LogFile state without planning writes.

The shipped ntfs3 lifecycle wipes $LogFile to 0xff after successful replay.  A
dirty volume with that exact bounded state is not native replay work: RootHealth
must report RH_NATIVE_LOG_EMPTY_T1OS, preserve the dirty bit, and plan no ID5/6
operation.  Partially wiped or fabricated restart pages are whole-log refusals.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
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


fixture = load_module("roothealth_fixture_helpers", "fixtures.py")
redo_fixture = load_module(
    "roothealth_redo_evidence_helper", "native_logfile_redo_fixture.py"
)


PROBE_C = r"""
#include <inttypes.h>
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
	int rc;
	int ok;

	if (argc != 3)
		return 64;
	if (rh_writer_open(&writer, argv[1]) ||
		rh_writer_set_backend(&writer, &persistent_backend, NULL))
		return 65;
	rc = roothealth_log_replay_plan(argv[1], &writer, &result);
	printf("plan_rc=%d state=%d checked=%d logfile_bytes=%" PRIu64
		" pages_expected=%u pages_examined=%u wiped_pages=%u "
		"checkpoint=%u control=%u mutation=%u actions=%u redo=%u undo=%u "
		"restart=%u unsupported=%u "
		"io_errors=%u parse_errors=%u operations=%zu bytes=%" PRIu64 "\n",
		rc, (int)result.state, result.checked, result.logfile_bytes,
		result.pages_expected, result.pages_examined,
		result.wiped_pages_scanned, result.checkpoint_records_examined,
		result.control_records_examined, result.mutation_records_examined,
		result.actions_seen, result.redo_actions,
		result.undo_actions, result.restart_pages_planned,
		result.unsupported_actions, result.io_errors, result.parse_errors,
		writer.operation_count, writer.planned_bytes);
	if (!strcmp(argv[2], "empty"))
		ok = !rc && result.state == RH_NATIVE_LOG_EMPTY_T1OS && result.checked &&
			result.logfile_bytes && !(result.logfile_bytes % 4096U) &&
			result.pages_expected == result.logfile_bytes / 4096U &&
			result.pages_examined == result.pages_expected &&
			result.wiped_pages_scanned == result.pages_expected &&
			!result.actions_seen && !result.redo_actions &&
			!result.undo_actions && !result.restart_pages_planned &&
			!result.unsupported_actions && !result.io_errors &&
			!result.parse_errors && !result.planned_io_operations &&
			!result.planned_io_bytes &&
			!writer.operation_count && !writer.planned_bytes;
	else if (!strcmp(argv[2], "reject"))
		ok = rc == -1 && result.state == RH_NATIVE_LOG_UNKNOWN &&
			result.checked && result.pages_expected &&
			result.pages_examined <= result.pages_expected &&
			!result.unsupported_actions && !result.io_errors &&
			result.parse_errors && !result.planned_io_operations &&
			!result.planned_io_bytes &&
			!writer.operation_count && !writer.planned_bytes;
	else if (!strcmp(argv[2], "replay"))
		ok = !rc && result.state == RH_NATIVE_LOG_REPLAY_PLANNED &&
			result.checked && result.major_version == 1 &&
			result.minor_version == 1 && result.logfile_bytes &&
			result.pages_expected == result.logfile_bytes / 4096U &&
			result.pages_examined == 7 && result.wiped_pages_scanned == 1 &&
			!result.checkpoint_records_examined &&
			result.control_records_examined == 2 &&
			result.mutation_records_examined == 1 &&
			!result.open_attribute_tables && !result.attribute_name_tables &&
			!result.dirty_page_tables && !result.transaction_tables &&
			result.actions_seen == 3 && result.redo_actions == 1 &&
			!result.undo_actions && result.restart_pages_planned == 2 &&
			!result.unsupported_actions && !result.io_errors &&
			!result.parse_errors && result.planned_io_operations == 4 &&
			result.planned_io_bytes == 10240 &&
			writer.operation_count == 4 && writer.planned_bytes == 10240;
	else
		ok = 0;
	rh_writer_close(&writer);
	return ok ? 0 : 66;
}
"""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def run(command, description: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.setdefault("ASAN_OPTIONS", "detect_leaks=1:halt_on_error=1")
    environment.setdefault("UBSAN_OPTIONS", "halt_on_error=1:print_stacktrace=1")
    completed = subprocess.run(
        [str(item) for item in command], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=environment, check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"{description} failed ({completed.returncode})\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def compile_probe(tree: Path, work: Path, cc: str) -> Path:
    source = work / "empty_t1os_probe.c"
    source.write_text(PROBE_C.lstrip(), encoding="utf-8")
    common = [
        cc, "-std=c11", "-D_GNU_SOURCE", "-D_FORTIFY_SOURCE=3",
        "-DHAVE_CONFIG_H", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
        f"-I{tree}", f"-I{tree / 'include'}", f"-I{tree / 'libntfs'}",
        f"-I{tree / 'src'}",
    ]
    objects: list[Path] = []
    for name in (
        "roothealth_replay_guard", "roothealth_replay_analysis",
        "roothealth_recover", "roothealth_playlog", "roothealth_write",
    ):
        output = work / f"{name}.o"
        run(common + ["-Wno-address-of-packed-member", "-c",
                      tree / "src" / f"{name}.c", "-o", output],
            f"strict compile {name}")
        objects.append(output)
    probe = work / "empty-t1os-probe"
    run(common + [source, *objects, tree / "src" / "utils.o",
                  tree / "libntfs" / ".libs" / "libntfs.a",
                  "-o", probe], "empty T1OS probe link")
    return probe


def logfile_attribute(handle):
    geometry = fixture.geometry(handle)
    _, _, record = fixture.read_record(handle, geometry, fixture.FILE_LOGFILE)
    attribute = fixture.find_attribute(record, fixture.AT_DATA)
    require(attribute.nonresident and attribute.data_size > 0,
            "$LogFile must be a nonresident stream")
    return geometry, attribute


def mutate_log(path: Path, offset: int, data: bytes) -> None:
    with path.open("r+b") as image:
        geometry, attribute = logfile_attribute(image)
        require(offset >= 0 and offset + len(data) <= attribute.data_size,
                "test mutation lies inside $LogFile")
        fixture.write_stream(image, geometry, attribute, offset, data)
        image.flush()
        os.fsync(image.fileno())


def self_test(tree: Path, cc: str, work_dir: Path | None) -> None:
    context = tempfile.TemporaryDirectory(prefix="roothealth-empty-t1os.")
    work = work_dir.resolve() if work_dir else Path(context.name)
    if work_dir:
        require(not work.exists() or not any(work.iterdir()),
                "work directory must be empty")
        work.mkdir(parents=True, exist_ok=True)

    base = work / "base.img"
    exact = work / "empty-t1os.img"
    replay_base = work / "replay-base.img"
    replay = work / "replay-planned.img"
    replay_manifest = work / "replay-planned.json"
    mkntfs = shutil.which("mkfs.ntfs") or shutil.which("mkntfs")
    require(mkntfs is not None, "system mkfs.ntfs is unavailable")
    with base.open("wb") as image:
        image.truncate(64 * 1024 * 1024)
    run([mkntfs, "-F", "-q", "-T", "-L", "RHEMPTY", base],
        "deterministic mkntfs")
    shutil.copyfile(base, exact)
    with exact.open("r+b") as image:
        geometry = fixture.geometry(image)
        state = fixture.set_dirty_with_wiped_log(image, geometry)
        image.flush()
        os.fsync(image.fileno())
        _, attribute = logfile_attribute(image)
        require(attribute.data_size == state["logfile_size"],
                "fixture helper reported exact $LogFile size")
        for offset in range(0, attribute.data_size, 1024 * 1024):
            amount = min(1024 * 1024, attribute.data_size - offset)
            require(fixture.read_stream(image, geometry, attribute, offset, amount)
                    == b"\xff" * amount,
                    "fixture contains only 0xff across bounded $LogFile")

    probe = compile_probe(tree, work, cc)
    exact_before = sha256(exact)
    positive = run([probe, exact, "empty"], "exact empty T1OS plan")
    require(sha256(exact) == exact_before,
            "exact empty T1OS parser modified source image")

    with replay_base.open("wb") as image:
        image.truncate(64 * 1024 * 1024)
    run([mkntfs, "-F", "-q", "-T", "-L", "RHREDO",
         replay_base], "deterministic replay evidence mkntfs")
    redo_fixture.build(replay_base, replay, replay_manifest)
    replay_before = sha256(replay)
    replay_probe = run([probe, replay, "replay"],
                       "replay-planned evidence reconciliation")
    require(sha256(replay) == replay_before,
            "replay evidence parser modified source image")

    negatives: list[dict[str, object]] = []
    for name, offset, data in (
        ("partially-wiped-interior", state["logfile_size"] // 2, b"\x00"),
        ("fabricated-rstr-magic", 0, b"RSTR"),
    ):
        candidate = work / f"negative-{name}.img"
        shutil.copyfile(exact, candidate)
        mutate_log(candidate, int(offset), data)
        before = sha256(candidate)
        rejected = run([probe, candidate, "reject"], f"negative {name}")
        require(sha256(candidate) == before,
                f"negative {name} parser modified source image")
        negatives.append({
            "name": name,
            "sha256_before": before,
            "sha256_after": sha256(candidate),
            "probe": rejected.stdout.strip(),
        })

    print(positive.stdout, end="" if positive.stdout.endswith("\n") else "\n")
    print(replay_probe.stdout,
          end="" if replay_probe.stdout.endswith("\n") else "\n")
    print(json.dumps({
        "result": "PASS",
        "native_log_state": "RH_NATIVE_LOG_EMPTY_T1OS",
        "logfile_fill": "ff",
        "logfile_size": state["logfile_size"],
        "actions": 0,
        "redo": 0,
        "undo": 0,
        "restart_pages": 0,
        "typed_operations": 0,
        "planned_bytes": 0,
        "dirty_bit_preserved": True,
        "source_image_unchanged": True,
        "fixture_sha256_before": exact_before,
        "fixture_sha256_after": sha256(exact),
        "replay_fixture_sha256_before": replay_before,
        "replay_fixture_sha256_after": sha256(replay),
        "replay_evidence_reconciled": True,
        "negative_preflight_tests": negatives,
        "work_directory": str(work),
    }, sort_keys=True))
    if not work_dir:
        context.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("self-test",))
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args()
    self_test(args.tree.resolve(), args.cc, args.work_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
