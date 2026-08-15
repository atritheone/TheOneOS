#!/usr/bin/env python3
"""Source-bound gate for the fail-closed v1.1/v2 native replay proposal."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE / "native-replay-v1_1-v2-proposal-qualification.json"
EXPECTED_BLOCKERS = {
    "NATIVE_ID5_ID6_WAL_REDERIVATION_NOT_MERGED",
    "OP2_IMMUTABLE_SLOT_AUTHORITY_NOT_MERGED",
}
EVIDENCE_SCHEMA = {
    "checked": "bool",
    "state": "null|CLEAN_RESTART|REPLAY_PLANNED|EMPTY_T1OS|UNSAFE|IO_ERROR",
    "logfile_bytes": "uint64|null",
    "pages_expected": "uint32|null",
    "pages_examined": "uint32",
    "wiped_pages_scanned": "uint32",
    "version_major": "uint16|null",
    "version_minor": "uint16|null",
    "restart_lsn": "uint64|null",
    "synced_lsn": "uint64|null",
    "committed_lsn": "uint64|null",
    "latest_lsn": "uint64|null",
    "checkpoint_records_examined": "uint32",
    "control_records_examined": "uint32",
    "mutation_records_examined": "uint32",
    "open_attribute_tables": "uint32",
    "attribute_name_tables": "uint32",
    "dirty_page_tables": "uint32",
    "transaction_tables": "uint32",
    "actions_seen": "uint32",
    "redo_actions": "uint32",
    "undo_actions": "uint32",
    "restart_pages_planned": "uint32",
    "unsupported_actions": "uint32",
    "io_errors": "uint32",
    "parse_errors": "uint32",
    "planned_io_operations": "uint64",
    "planned_io_bytes": "uint64",
}
RESULT_FIELDS = (
    "state", "checked", "major_version", "minor_version", "logfile_bytes",
    "restart_lsn", "synced_lsn", "committed_lsn", "latest_lsn",
    "pages_expected", "pages_examined", "wiped_pages_scanned",
    "checkpoint_records_examined", "control_records_examined",
    "mutation_records_examined", "open_attribute_tables",
    "attribute_name_tables", "dirty_page_tables", "transaction_tables",
    "actions_seen", "redo_actions", "undo_actions", "restart_pages_planned",
    "unsupported_actions", "io_errors", "parse_errors",
    "planned_io_operations", "planned_io_bytes",
)
PLANNER_FILES = (
    "src/roothealth_recover.c", "src/roothealth_playlog.c",
    "src/roothealth_replay_guard.c", "src/roothealth_replay_analysis.c",
)
FORBIDDEN = {
    "ntfs_pwrite": re.compile(r"\bntfs_pwrite\s*\("),
    "ntfs_attr_pwrite": re.compile(r"\bntfs_attr_pwrite\s*\("),
    "raw_pwrite": re.compile(r"(?<![A-Za-z0-9_])pwrite\s*\("),
    "writer_raw_pwrite": re.compile(r"\brh_writer_raw_pwrite\s*\("),
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def run(command: list[str | Path], label: str, *, cwd: Path | None = None,
        env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        [str(item) for item in command], cwd=cwd, env=env, text=True,
        capture_output=True, check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"{label} failed ({completed.returncode})\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout


def parse_action_table(source: str) -> list[dict[str, object]]:
    pattern = re.compile(
        r'\{\s*"([^"]+)",\s*(UBIT\((\d+)\)|0),\s*'
        r'RH_REPLAY_ACTION_([A-Z_]+),\s*(NULL|"([^"]*)")\s*\}'
    )
    rows: list[dict[str, object]] = []
    for code, match in enumerate(pattern.finditer(source)):
        rows.append({
            "code": code,
            "name": match.group(1),
            "class": match.group(4),
            "allowed_undo_codes": [] if match.group(2) == "0" else
                [int(match.group(3))],
            "deny_reason": match.group(6),
        })
    return rows


def validate(tree: Path, baseline: Path | None, manifest: dict) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if manifest.get("status") != "PROPOSED_FAIL_CLOSED":
        errors.append("status must be PROPOSED_FAIL_CLOSED")
    if manifest.get("verdict") != "PASS_MERGEABLE_NATIVE_REPLAY_PROPOSAL":
        errors.append("proposal verdict drift")
    if manifest.get("release_qualified") is not False:
        errors.append("proposal must not claim release qualification")
    blocker_ids = {item.get("id") for item in manifest.get("blockers", [])}
    if blocker_ids != EXPECTED_BLOCKERS:
        errors.append("exact blocker set drift")
    if manifest.get("native_log_evidence_schema") != EVIDENCE_SCHEMA:
        errors.append("native_log public evidence schema drift")

    for relative, expected in manifest.get("result_sources", {}).items():
        path = tree / relative
        if not path.is_file():
            errors.append(f"missing result source: {relative}")
        elif digest(path) != expected:
            errors.append(f"result source hash drift: {relative}")
    if baseline is not None:
        for relative, expected in manifest.get("baseline_sources", {}).items():
            path = baseline / relative
            if not path.is_file():
                errors.append(f"missing baseline source: {relative}")
            elif digest(path) != expected:
                errors.append(f"baseline source hash drift: {relative}")

    for relative, expected in manifest.get("assets", {}).items():
        path = HERE / relative
        if not path.is_file():
            errors.append(f"missing qualification asset: {relative}")
        elif digest(path) != expected:
            errors.append(f"qualification asset hash drift: {relative}")

    patch_info = manifest.get("patch", {})
    patch_path = HERE / patch_info.get("file", "")
    if not patch_path.is_file():
        errors.append("mechanical patch missing")
    else:
        if digest(patch_path) != patch_info.get("sha256"):
            errors.append("mechanical patch hash drift")
        if patch_path.stat().st_size != patch_info.get("bytes"):
            errors.append("mechanical patch byte count drift")
        changed = re.findall(
            r"^diff --git a/([^ ]+) b/([^\n]+)$",
            patch_path.read_text(encoding="utf-8"), re.M,
        )
        paths = [left if left == right else f"{left}->{right}"
                 for left, right in changed]
        if paths != patch_info.get("paths"):
            errors.append("mechanical patch path set/order drift")
        if baseline is not None:
            completed = subprocess.run(
                ["git", "apply", "--check", str(patch_path)], cwd=baseline,
                text=True, capture_output=True, check=False,
            )
            if completed.returncode:
                errors.append("mechanical patch no longer clean-applies")

    guard = tree / "src/roothealth_replay_guard.c"
    if guard.is_file():
        parsed = parse_action_table(guard.read_text(encoding="utf-8"))
        if len(parsed) != 38:
            errors.append("action policy must classify exactly 38 opcodes")
        if parsed != manifest.get("action_table"):
            errors.append("action table decision drift")

    profile = manifest.get("profile", {})
    if profile.get("accepted_versions") != [[1, 1], [2, 0]] or \
            profile.get("legacy_v1_0") != "WHOLE_LOG_REFUSAL" or \
            profile.get("page_size") != 4096 or \
            profile.get("max_logfile_bytes") != 67108864 or \
            profile.get("max_actions") != 4096 or \
            profile.get("max_record_pages") != 18:
        errors.append("accepted native profile drift")
    capacity = manifest.get("capacity", {})
    if capacity.get("accepted_entries") != 4096 or \
            capacity.get("accepted_id5") != 4094 or \
            capacity.get("final_id6") != 2 or \
            capacity.get("accepted_target_bytes") != 4200448 or \
            capacity.get("refused_entries") != 4097:
        errors.append("atomic WAL capacity proof drift")

    header = tree / "src/roothealth_recover.h"
    if header.is_file():
        source = header.read_text(encoding="utf-8")
        match = re.search(r"struct rh_log_result\s*\{(.*?)\n\};", source, re.S)
        if not match:
            errors.append("rh_log_result is missing")
        else:
            body = match.group(1)
            positions = [body.find(field) for field in RESULT_FIELDS]
            if any(position < 0 for position in positions) or \
                    positions != sorted(positions):
                errors.append("rh_log_result fields missing or reordered")

    required = {
        "src/roothealth_recover.c": (
            "major == 1U && minor == 1U", "major == 2U && minor == 0U",
            "ROOTHEALTH_NATIVE_WAL_MAX_OPERATIONS 4096U",
            "ROOTHEALTH_NATIVE_WAL_MAX_TARGET_BYTES",
            "if (provider) {", "errno = EOPNOTSUPP;",
            "RH_REPLAY_MAX_RECORD_PAGES", "rh_writer_reset_plan",
        ),
        "src/roothealth_playlog.c": (
            "roothealth_attribute_target_matches", "roothealth_semantic_cycle",
            "pre-transaction slot authority",
            "roothealth_authorize_initialize_slot",
        ),
        "src/roothealth_wal.c": (
            "rh_wal_dispatch_action_verifiers",
            "RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_REDO)",
            "RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_RESTART)",
            "Native replay cannot be enabled",
        ),
    }
    for relative, tokens in required.items():
        path = tree / relative
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        for token in tokens:
            if token not in source:
                errors.append(f"required fail-closed token missing: {relative}:{token}")

    for relative in PLANNER_FILES:
        path = tree / relative
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in FORBIDDEN.items():
            if pattern.search(source):
                errors.append(f"forbidden {label} in planner: {relative}")
    return errors


def run_native_gates(tree: Path, manifest: dict, cc: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="rh-native-v2-gate.") as temp:
        work = Path(temp)
        includes = [
            f"-I{tree}", f"-I{tree / 'include'}", f"-I{tree / 'libntfs'}",
            f"-I{tree / 'src'}",
        ]
        strict = [
            cc, "-std=c11", "-D_GNU_SOURCE", "-D_FORTIFY_SOURCE=3",
            "-DHAVE_CONFIG_H", "-Wall", "-Wextra", "-Werror",
            "-Wno-address-of-packed-member", *includes,
        ]
        owned = (
            "roothealth_replay_guard", "roothealth_replay_analysis",
            "roothealth_recover", "roothealth_playlog", "roothealth_write",
            "roothealth_wal",
        )
        for name in owned:
            source = tree / "src" / f"{name}.c"
            run(strict + ["-c", source, "-o", work / f"{name}.strict.o"],
                f"strict compile {name}")
            run(strict + ["-fanalyzer", "-c", source,
                          "-o", work / f"{name}.analyzer.o"],
                f"static analyzer {name}")

        sanitizer = strict + [
            "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
        ]
        guard_binary = work / "guard-corpus"
        analysis_binary = work / "analysis-corpus"
        run(sanitizer + [
            tree / "tests/roothealth_replay_guard_malformed.c",
            tree / "src/roothealth_replay_guard.c", "-o", guard_binary,
        ], "guard malformed corpus compile")
        run(sanitizer + [
            tree / "tests/roothealth_replay_analysis_malformed.c",
            tree / "src/roothealth_replay_analysis.c",
            tree / "src/roothealth_replay_guard.c", "-o", analysis_binary,
        ], "analysis malformed corpus compile")
        environment = os.environ.copy()
        environment["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
        environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
        guard_output = run([guard_binary], "guard malformed corpus", env=environment)
        analysis_output = run(
            [analysis_binary], "analysis malformed corpus", env=environment
        )

    fixture_results: dict[str, str] = {}
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for fixture in manifest.get("fixture_matrix", []):
        script = HERE / fixture["script"]
        output = run(
            [sys.executable, "-B", script, "self-test", "--tree", tree],
            f"fixture {fixture['id']}", env=environment,
        )
        if fixture["expect_token"] not in output:
            raise RuntimeError(f"fixture {fixture['id']} evidence token missing")
        fixture_results[fixture["id"]] = "PASS"
    registry_output = run(
        [sys.executable, "-B", HERE / "check-wal-action-verifier-registry.py",
         "--tree", tree], "WAL verifier registry gate", env=environment,
    )
    return {
        "strict_werror_translation_units": 6,
        "fanalyzer_translation_units": 6,
        "guard_corpus": guard_output.strip(),
        "analysis_corpus": analysis_output.strip(),
        "fixtures": fixture_results,
        "registry": registry_output.strip(),
    }


def self_test(tree: Path, manifest: dict) -> dict[str, bool]:
    drift = copy.deepcopy(manifest)
    drift["action_table"][7]["allowed_undo_codes"] = [6]
    decision = any("action table decision drift" in item
                   for item in validate(tree, None, drift))
    with tempfile.TemporaryDirectory(prefix="rh-native-v2-selftest.") as temp:
        clone = Path(temp)
        for relative in manifest["result_sources"]:
            source = tree / relative
            target = clone / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        target = clone / "src/roothealth_recover.c"
        target.write_text(
            target.read_text(encoding="utf-8") +
            "\nvoid rh_forbidden_probe(void) { pwrite(0, 0, 0, 0); }\n",
            encoding="utf-8",
        )
        changed = copy.deepcopy(manifest)
        changed["result_sources"]["src/roothealth_recover.c"] = digest(target)
        forbidden = any("forbidden raw_pwrite" in item
                        for item in validate(clone, None, changed))
    if not decision or not forbidden:
        raise RuntimeError("proposal checker self-test failed")
    return {"decision_drift_rejected": decision,
            "forbidden_primitive_rejected": forbidden}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run-gates", action="store_true")
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.resolve().read_text(encoding="utf-8"))
    tree = args.tree.resolve()
    baseline = args.baseline.resolve() if args.baseline else None
    errors = validate(tree, baseline, manifest)
    result: dict[str, object] = {
        "verdict": "PASS" if not errors else "FAIL",
        "status": manifest.get("status"),
        "release_qualified": manifest.get("release_qualified"),
        "source_files": len(manifest.get("result_sources", {})),
        "opcodes": len(manifest.get("action_table", [])),
        "findings": errors,
    }
    if args.self_test:
        result["self_test"] = self_test(tree, manifest)
    if args.run_gates and not errors:
        result["gates"] = run_native_gates(tree, manifest, args.cc)
    print(json.dumps(result, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
