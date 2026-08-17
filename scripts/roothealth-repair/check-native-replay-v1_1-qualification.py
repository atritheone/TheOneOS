#!/usr/bin/env python3
"""Exact source-bound gate for the qualified RootHealth v1.1 replay subset."""

from __future__ import annotations

import sys as _t1os_incremental_sys
from pathlib import Path as _T1OSIncrementalPath

if __name__ == "__main__":
    _t1os_incremental_scripts = next(
        (parent for parent in _T1OSIncrementalPath(__file__).resolve().parents
         if (parent / "incremental_test.py").is_file()),
        None,
    )
    if _t1os_incremental_scripts is not None:
        _t1os_incremental_sys.path.insert(0, str(_t1os_incremental_scripts))
        from _incremental_test import guard as _t1os_incremental_guard
        if _t1os_incremental_guard(__file__, _t1os_incremental_sys.argv[1:]):
            raise SystemExit(0)

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile


HERE = Path(__file__).resolve().parent
DEFAULT_AUDIT = HERE / "native-replay-v1_1-qualification.json"
WORKSPACE = HERE.parents[1]

EVIDENCE_FIELDS = {
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

RESULT_STRUCT_FIELDS = [
    "checked", "major_version", "minor_version", "logfile_bytes",
    "restart_lsn", "synced_lsn", "committed_lsn", "latest_lsn",
    "pages_expected", "pages_examined", "wiped_pages_scanned",
    "checkpoint_records_examined", "control_records_examined",
    "mutation_records_examined", "open_attribute_tables",
    "attribute_name_tables", "dirty_page_tables", "transaction_tables",
    "actions_seen", "redo_actions", "undo_actions", "restart_pages_planned",
    "unsupported_actions", "io_errors", "parse_errors",
    "planned_io_operations", "planned_io_bytes",
]

FORBIDDEN = {
    "ntfs_pwrite": re.compile(r"\bntfs_pwrite\s*\("),
    "ntfs_attr_pwrite": re.compile(r"\bntfs_attr_pwrite\s*\("),
    "pwrite": re.compile(r"(?<![A-Za-z0-9_])pwrite\s*\("),
    "rh_writer_raw_pwrite": re.compile(r"\brh_writer_raw_pwrite\s*\("),
    "debug_marker": re.compile(r"RHDBG|Win10Action"),
}

PLANNER_FILES = (
    "src/roothealth_recover.c",
    "src/roothealth_playlog.c",
    "src/roothealth_replay_guard.c",
    "src/roothealth_replay_analysis.c",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_audit(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError("audit root must be an object")
    return value


def parse_action_policy(source: str) -> list[dict]:
    pattern = re.compile(
        r'\{\s*"([^"]+)",\s*(UBIT\((\d+)\)|0),\s*'
        r'RH_REPLAY_ACTION_([A-Z_]+),\s*(NULL|"([^"]*)")\s*\}'
    )
    rows = []
    for code, match in enumerate(pattern.finditer(source)):
        action_class = match.group(4)
        rows.append({
            "code": code,
            "name": match.group(1),
            "class": action_class,
            "allowed_undo_codes": [] if match.group(2) == "0" else
                [int(match.group(3))],
            "decision": "REFUSED_WHOLE_LOG" if action_class == "DENY" else
                ("SUPPORTED_CONTROL" if action_class in
                 ("CONTROL", "TRANSACTION_END") else "SUPPORTED_MUTATION"),
            "reason": match.group(6),
        })
    return rows


def action_projection(row: dict) -> dict:
    return {
        key: row.get(key) for key in
        ("code", "name", "class", "allowed_undo_codes", "decision", "reason")
    }


def validate(tree: Path, audit: dict, workspace: Path = WORKSPACE) -> list[str]:
    errors: list[str] = []
    if audit.get("schema_version") != 3:
        errors.append("schema_version must be 3")
    if audit.get("verdict") != "QUALIFIED_NATIVE_REPLAY_V1_1_PROFILE":
        errors.append("verdict is not the bounded qualified v1.1 profile")
    if audit.get("findings") != []:
        errors.append("qualified audit findings must be empty")
    if audit.get("product_release_complete") is not False:
        errors.append("v1.1 subset must not claim complete product coverage")

    frozen = audit.get("frozen_sources")
    if not isinstance(frozen, dict) or not frozen:
        errors.append("frozen_sources is missing")
        frozen = {}
    for relative, expected in frozen.items():
        path = tree / relative
        if not path.is_file():
            errors.append(f"missing frozen source {relative}")
        elif sha256(path) != expected:
            errors.append(f"source hash drift: {relative}")

    patch_info = audit.get("patch", {})
    patch_path = workspace / patch_info.get("path", "")
    if not patch_path.is_file():
        errors.append("mechanical patch is missing")
    elif sha256(patch_path) != patch_info.get("sha256"):
        errors.append("mechanical patch hash drift")
    elif patch_path.stat().st_size != patch_info.get("bytes"):
        errors.append("mechanical patch byte count drift")

    fixtures = audit.get("fixtures", [])
    if len(fixtures) != 7:
        errors.append("exactly seven fixture profiles are required")
    for entry in fixtures:
        path = HERE / entry.get("script", "")
        if not path.is_file():
            errors.append(f"missing fixture {entry.get('script')}")
        elif sha256(path) != entry.get("script_sha256"):
            errors.append(f"fixture hash drift: {entry.get('script')}")

    guard_path = tree / "src/roothealth_replay_guard.c"
    if guard_path.is_file():
        parsed = parse_action_policy(guard_path.read_text(encoding="utf-8"))
        expected = audit.get("action_table", [])
        if len(parsed) != 38 or len(expected) != 38:
            errors.append("action table must classify exactly all 38 opcodes")
        elif [action_projection(row) for row in parsed] != [
                action_projection(row) for row in expected]:
            errors.append("action table decision drift")
    coverage = audit.get("coverage", {})
    if coverage.get("opcodes_classified") != 38 or \
            coverage.get("control_opcodes") != 13 or \
            coverage.get("mutation_directional_pairs") != 22 or \
            coverage.get("refused_codes") != [3, 35, 36]:
        errors.append("coverage cardinality or refused set drift")
    supported_pairs = audit.get("coverage", {}).get("supported_mutation_pairs", [])
    action_pairs = [
        [row["code"], row["allowed_undo_codes"][0]]
        for row in audit.get("action_table", [])
        if row.get("decision") == "SUPPORTED_MUTATION"
    ]
    if supported_pairs != action_pairs:
        errors.append("supported mutation-pair list differs from action table")

    if audit.get("native_log_evidence_schema") != EVIDENCE_FIELDS:
        errors.append("native_log evidence schema field/type/nullability drift")
    header = tree / "src/roothealth_recover.h"
    if header.is_file():
        text = header.read_text(encoding="utf-8")
        result_match = re.search(
            r"struct rh_log_result\s*\{(?P<body>.*?)\n\};", text, re.S
        )
        if not result_match:
            errors.append("rh_log_result is missing")
        else:
            body = result_match.group("body")
            positions = [body.find(field) for field in RESULT_STRUCT_FIELDS]
            if any(position < 0 for position in positions) or positions != sorted(positions):
                errors.append("rh_log_result evidence fields missing or reordered")
        for token in (
            "RH_NATIVE_LOG_UNKNOWN", "RH_NATIVE_LOG_CLEAN_RESTART",
            "RH_NATIVE_LOG_REPLAY_PLANNED", "RH_NATIVE_LOG_EMPTY_T1OS",
        ):
            if token not in text:
                errors.append(f"internal native state missing: {token}")

    for relative in PLANNER_FILES:
        path = tree / relative
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in FORBIDDEN.items():
            if pattern.search(source):
                errors.append(f"forbidden {label} in planner source {relative}")
    writer = tree / "src/roothealth_write.c"
    if writer.is_file():
        source = writer.read_text(encoding="utf-8", errors="replace")
        if not source.startswith(
                "/* ROOTHEALTH_REPAIR_ROLE(TYPED_WAL_ADAPTER) "
                "ROOTHEALTH_IO_ROLE(TYPED_WRITER) */"):
            errors.append("raw pwrite adapter lacks exact typed-WAL annotation")
        for label in ("ntfs_pwrite", "ntfs_attr_pwrite"):
            if FORBIDDEN[label].search(source):
                errors.append(f"forbidden {label} in typed writer")

    required_tokens = {
        "src/roothealth_recover.c": (
            "roothealth_prepare_log_evidence", "roothealth_logfile_is_wiped",
            "RH_NATIVE_LOG_EMPTY_T1OS", "roothealth_plan_clean_restart_pages",
            "roothealth_analyze_transactions", "rh_writer_reset_plan",
        ),
        "src/roothealth_playlog.c": (
            "roothealth_preflight_redos", "roothealth_preflight_sequence",
            "roothealth_attribute_target_matches", "roothealth_semantic_cycle",
            "ZeroEndOfFileRecord has no native before-image",
        ),
        "src/roothealth_replay_analysis.c": (
            "parse_open_attribute_table", "parse_dirty_page_table",
            "parse_transaction_table", "RH_REPLAY_PLAN_UNDO",
        ),
    }
    for relative, tokens in required_tokens.items():
        path = tree / relative
        if path.is_file():
            source = path.read_text(encoding="utf-8", errors="replace")
            for token in tokens:
                if token not in source:
                    errors.append(f"required fail-closed token missing: {relative}:{token}")
    return errors


def self_test(tree: Path, audit: dict) -> dict:
    drifted = copy.deepcopy(audit)
    drifted["action_table"][7]["allowed_undo_codes"] = [6]
    decision_errors = validate(tree, drifted)
    decision_pass = any("action table decision drift" in item for item in decision_errors)

    with tempfile.TemporaryDirectory(prefix="roothealth-native-audit-selftest.") as tmp:
        clone = Path(tmp)
        for relative in audit["frozen_sources"]:
            source = tree / relative
            target = clone / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        target = clone / "src/roothealth_recover.c"
        target.write_text(
            target.read_text(encoding="utf-8") +
            "\nvoid rh_forbidden_selftest(void) { ntfs_pwrite(0, 0, 0, 0); }\n",
            encoding="utf-8",
        )
        forbidden_audit = copy.deepcopy(audit)
        forbidden_audit["frozen_sources"]["src/roothealth_recover.c"] = sha256(target)
        forbidden_errors = validate(clone, forbidden_audit)
        forbidden_pass = any(
            "forbidden ntfs_pwrite" in item for item in forbidden_errors
        )
    if not decision_pass or not forbidden_pass:
        raise RuntimeError("audit self-test failed")
    return {
        "decision_drift_rejected": decision_pass,
        "forbidden_primitive_rejected": forbidden_pass,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    audit = load_audit(args.audit.resolve())
    tree = args.tree.resolve()
    errors = validate(tree, audit)
    result = {
        "verdict": "PASS" if not errors else "FAIL",
        "qualified_profile": audit.get("qualification_scope"),
        "source_files": len(audit.get("frozen_sources", {})),
        "opcodes": len(audit.get("action_table", [])),
        "findings": errors,
    }
    if args.self_test:
        result["self_test"] = self_test(tree, audit)
    print(json.dumps(result, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
