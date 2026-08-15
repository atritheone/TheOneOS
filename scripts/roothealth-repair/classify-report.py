#!/usr/bin/env python3
"""Summarise one or more RootHealth format-3 refusal reports without writing."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


CLASSES = {
    "REPAIR_POST_RESCAN_FAILED": "repairable",
    "VOLUME_DIRTY": "repairable",
    "WAL_RECOVERY_REQUIRED": "recovery-required",
    "NATIVE_LOG_REPLAY_REQUIRED": "recovery-required",
    "CENSUS_INCOMPLETE": "unsupported",
    "NATIVE_LOG_UNSUPPORTED_ACTION": "unsupported",
    "UNSUPPORTED_VALID_METADATA": "unsupported",
    "MFT_MIRROR_UNSUPPORTED_LAYOUT": "unsupported",
    "TARGET_IO_ERROR": "io",
    "IDENTITY_MISMATCH": "wrong-root",
    "ORCHESTRATION_INTERNAL_ERROR": "internal",
}


def refusal_class(code: str) -> str:
    if code in CLASSES:
        return CLASSES[code]
    if code in {
        "WAL_UNSAFE",
        "MFT_MIRROR_DIVERGENCE",
        "MFT_BITMAP_MISMATCH",
        "INDEX_BITMAP_MISMATCH",
        "CLUSTER_BITMAP_MISMATCH",
        "NAMESPACE_RECIPROCITY_MISMATCH",
        "FIXED_SYSTEM_CHECK_FAILED",
        "FOUNDATION_REPAIR_DEFERRED",
        "METADATA_UNRESOLVED",
    }:
        return "ambiguous-corruption"
    return "unclassified"


def require_object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} is not an object")
    return value


def summarise(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    report = require_object(json.loads(raw), "report")
    if report.get("format") != 3 or report.get("checker") != "roothealth":
        raise ValueError("not a RootHealth format-3 report")
    issues = report.get("issues")
    if not isinstance(issues, list):
        raise ValueError("issues is not an array")
    issue = require_object(issues[0], "issues[0]") if issues else {}
    code = str(issue.get("code", "CLEAN" if report.get("exit_code") == 0 else "UNCLASSIFIED"))
    initial = require_object(report.get("initial"), "initial")
    coverage = require_object(initial.get("coverage"), "initial.coverage")
    ledger = require_object(report.get("issue_ledger"), "issue_ledger")
    native = require_object(report.get("native_log"), "native_log")
    wal = require_object(report.get("wal"), "wal")
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "exit_code": report.get("exit_code"),
        "result": report.get("result"),
        "code": code,
        "class": "clean" if code == "CLEAN" else refusal_class(code),
        "pass": issue.get("pass"),
        "message": issue.get("message"),
        "failed_predicates": issue.get("failed_predicates", []),
        "issue_ledger_hash": ledger.get("ledger_hash"),
        "coverage_complete": coverage.get("complete"),
        "coverage_ledger_hash": coverage.get("ledger_hash"),
        "dirty": initial.get("dirty"),
        "native_log_state": native.get("state"),
        "native_log_parse_errors": native.get("parse_errors"),
        "native_log_unsupported_actions": native.get("unsupported_actions"),
        "wal_state": wal.get("state"),
        "wal_recovery_required": wal.get("recovery_required"),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: classify-report.py ROOTHEALTH.json [...]", file=sys.stderr)
        return 2
    summaries = []
    try:
        summaries = [summarise(Path(argument)) for argument in sys.argv[1:]]
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"roothealth report classification failed: {error}", file=sys.stderr)
        return 1
    signatures = {
        (item["code"], item["coverage_ledger_hash"], item["native_log_state"], item["wal_state"])
        for item in summaries
    }
    output = {
        "format": 1,
        "reports": summaries,
        "recurrence": (
            "single" if len(summaries) == 1 else
            "exact" if len(signatures) == 1 else
            "varying"
        ),
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
