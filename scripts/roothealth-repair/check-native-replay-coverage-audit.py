#!/usr/bin/env python3
"""Validate the pinned native replay coverage audit and its source binding."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def fail(message: str):
    raise SystemExit(f"native replay coverage audit: FAIL: {message}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def parse_actions(header: str):
    match = re.search(r"enum\s+ACTIONS\s*\{(?P<body>.*?)\}\s*;", header, re.S)
    if not match:
        fail("enum ACTIONS not found")
    body = re.sub(r"/\*.*?\*/", "", match.group("body"), flags=re.S)
    names = []
    next_value = 0
    last_value = None
    for item in body.split(","):
        item = item.strip()
        if not item:
            continue
        token = re.match(r"([A-Za-z_][A-Za-z0-9_]*)(?:\s*=\s*([0-9]+))?", item)
        if not token:
            fail(f"cannot parse ACTIONS entry: {item!r}")
        name, explicit = token.groups()
        if explicit is not None:
            next_value = int(explicit)
        if name == "LastAction":
            last_value = next_value
        else:
            names.append((next_value, name))
        next_value += 1
    if last_value is None:
        fail("LastAction sentinel missing")
    return names, last_value


def validate_table(report, tree: Path):
    expected_hashes = report["generated_for"]["source_sha256"]
    for relative, expected in expected_hashes.items():
        source = tree / relative
        if not source.is_file():
            fail(f"missing bound source: {source}")
        actual = sha256(source)
        if actual != expected:
            fail(
                f"source drift for {relative}: expected {expected}, got {actual}; "
                "refresh the independent audit before accepting replay changes"
            )

    enum, last_action = parse_actions(
        (tree / "src" / "roothealth_recover.h").read_text(encoding="utf-8")
    )
    table = report["action_table"]
    mapped = [(entry["code"], entry["name"]) for entry in table]
    if enum != mapped:
        fail("the 0..37 action table does not exactly match enum ACTIONS")
    if last_action != len(table) or last_action != 38:
        fail(f"LastAction/table cardinality mismatch: {last_action}/{len(table)}")

    finding_ids = {finding["id"] for finding in report["findings"]}
    if len(finding_ids) != len(report["findings"]):
        fail("duplicate finding id")
    statuses = {}
    handler_count = 0
    conditional_count = 0
    dynamic_count = 0
    ignored_count = 0
    error_count = 0
    playlog = (tree / "src" / "roothealth_playlog.c").read_text(
        encoding="utf-8"
    )
    for expected_code, entry in enumerate(table):
        if entry["code"] != expected_code:
            fail(f"non-contiguous action code at table index {expected_code}")
        unknown = set(entry["gap_ids"]) - finding_ids
        if unknown:
            fail(f"action {expected_code} references unknown gaps: {sorted(unknown)}")
        status = entry["dispatch_status"]
        statuses[status] = statuses.get(status, 0) + 1
        if entry["handler"]:
            handler_count += 1
            for handler in entry["handler"]:
                if not re.search(rf"\b{re.escape(handler)}\s*\(", playlog):
                    fail(f"action {expected_code} handler missing from source: {handler}")
        accepted = entry["accepted_undo"]
        if status == "HANDLER_CONDITIONAL_PAIR":
            conditional_count += 1
            if accepted.get("mode") != "EXACT_SET" or not accepted.get("codes"):
                fail(f"action {expected_code} lacks an exact nonempty undo-pair set")
            names = [table[code]["name"] for code in accepted["codes"]]
            if names != accepted.get("names"):
                fail(f"action {expected_code} undo code/name mapping drift")
            if "returns success" not in entry["mismatch_or_unhandled_behavior"]:
                fail(f"action {expected_code} does not record silent mismatch behavior")
        elif status == "HANDLER_DYNAMIC_UNDO_UNCHECKED":
            dynamic_count += 1
            if accepted.get("mode") != "ANY_ENUM_VALUE":
                fail("dynamic UpdateNonResidentValue must record unchecked undo coverage")
        elif status in {
            "CONTROL_NO_TARGET_MUTATION",
            "SEMANTIC_DUMP_IGNORED_AFTER_REFRESH",
        }:
            ignored_count += 1
        elif status in {
            "FAIL_CLOSED_UNSUPPORTED",
            "DISPATCH_ERROR_INCONSISTENT_WITH_PREFLIGHT_COMMENT",
        }:
            error_count += 1

    summary = report["summary"]
    expected_summary = {
        "enum_actions": len(table),
        "actions_with_handler_path": handler_count,
        "conditional_dispatches_with_silent_pair_mismatch": conditional_count,
        "undo_unchecked_dynamic_dispatches": dynamic_count,
        "control_or_ignored_success_actions": ignored_count,
        "fail_closed_or_dispatch_error_actions": error_count,
    }
    for key, expected in expected_summary.items():
        if summary.get(key) != expected:
            fail(f"summary {key} is {summary.get(key)}, expected {expected}")
    if summary.get("generically_qualification_safe_mutating_actions") != 0:
        fail("audit must remain blocking until a new independent audit qualifies actions")
    return statuses


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", required=True, type=Path)
    parser.add_argument(
        "--audit",
        type=Path,
        default=Path(__file__).with_name("native-replay-coverage-audit.json"),
    )
    args = parser.parse_args()
    report = json.loads(args.audit.read_text(encoding="utf-8"))
    statuses = validate_table(report, args.tree.resolve())
    print(
        json.dumps(
            {
                "result": "PASS",
                "verdict": report["verdict"],
                "actions": len(report["action_table"]),
                "findings": len(report["findings"]),
                "statuses": statuses,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
