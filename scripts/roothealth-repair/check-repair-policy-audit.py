#!/usr/bin/env python3
"""Validate the exhaustive, pinned roothealth repair-policy audit."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
from typing import Any


PINNED_COMMIT = "d4f481df6926557f7b18b471a43313652dec6f7e"
PINNED_ARCHIVE_SHA256 = (
    "13dc944f477997ae4ecd89e3d0fdaa34b74ebbc1f7beb675657624ed6289eff5"
)
DECISIONS = {"CONDITIONAL", "DENY"}
PHASES = {"DIAGNOSTIC_ONLY", "BOOTSTRAP_REDUNDANCY", "IDENTITY_BOUND_UNIQUE"}
REQUIRED_AGGREGATES = {
    "FILE_NAME_SIZES",
    "STALE_REPARSE",
    "UNOPENABLE_MFT_BITMAP",
    "CLUSTER_BITMAP",
    "MFT_BITMAP",
    "ORPHANS",
    "INDEX_BITMAP",
    "INDEX_CORRUPT_ENTRIES",
    "INDEX_RESERVED",
    "MISSING_REPARSE",
    "DUPLICATE_CLUSTER_RUNLIST",
    "FIXUP_SALVAGE",
    "SYSTEM_FILE_IN_USE",
    "MFT_ATTR_OFFSET_ALIGNMENT",
}
REQUIRED_HAZARDS = {
    "RESET_LOGFILE",
    "DISCARD_CONTENT",
    "LOST_FOUND",
    "CLEAR_MFT_ALLOCATION",
    "CLEAR_CLUSTER_ALLOCATION",
    "UNPOLICIED_WRITE",
    "CONFLICTING_AUTHORITY",
    "PRE_IDENTITY",
    "DIRTY_FLAG_IS_NOT_WAL",
    "PWRITE_BYPASS",
}
SOURCE_REF = re.compile(r"^[A-Za-z0-9_./+-]+:\d+(?:-\d+)?$")


class AuditError(RuntimeError):
    pass


def without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def parse_problem_codes(text: str) -> list[str]:
    matches = re.findall(
        r"typedef\s+enum\s*\{(?P<body>[^}]*)\}\s*problem_code_t\s*;",
        without_comments(text),
        flags=re.DOTALL,
    )
    if len(matches) != 1:
        raise AuditError(
            f"expected one problem_code_t declaration, found {len(matches)}"
        )
    codes = re.findall(r"\bPR_[A-Z0-9_]+\b", matches[0])
    if not codes or codes[0] != "PR_PRE_SCAN_MFT":
        raise AuditError("problem_code_t did not start with PR_PRE_SCAN_MFT")
    if len(codes) != len(set(codes)):
        raise AuditError("problem_code_t contains a duplicate member")
    return codes


def require_text(value: Any, where: str) -> None:
    if not isinstance(value, str) or len(value.strip()) < 12:
        raise AuditError(f"{where} must be an explicit non-empty explanation")


def unique_entries(entries: Any, key: str, where: str) -> list[dict[str, Any]]:
    if not isinstance(entries, list) or not entries:
        raise AuditError(f"{where} must be a non-empty list")
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for offset, raw in enumerate(entries):
        if not isinstance(raw, dict):
            raise AuditError(f"{where}[{offset}] is not an object")
        name = raw.get(key)
        if not isinstance(name, str) or not name:
            raise AuditError(f"{where}[{offset}] has no {key}")
        if name in seen:
            raise AuditError(f"duplicate {where} entry {name}")
        seen.add(name)
        result.append(raw)
    return result


def validate_action(
    action: dict[str, Any], name: str, families: set[str], *, aggregate: bool
) -> None:
    decision = action.get("decision")
    if decision not in DECISIONS:
        raise AuditError(
            f"{name} decision must be CONDITIONAL or DENY; blanket ALLOW is forbidden"
        )
    writes = action.get("writes")
    if not isinstance(writes, list) or any(not isinstance(x, str) for x in writes):
        raise AuditError(f"{name} writes must be a string list")
    unknown = sorted(set(writes) - families)
    if unknown:
        raise AuditError(f"{name} names unknown write families: {', '.join(unknown)}")
    if len(writes) != len(set(writes)):
        raise AuditError(f"{name} repeats a write family")

    if decision == "DENY":
        require_text(action.get("reason"), f"{name} deny reason")
        if writes:
            raise AuditError(f"{name} is DENY but advertises physical writes")
        if "phase" in action or "predicate" in action:
            raise AuditError(f"{name} DENY must not carry an executable predicate")
        return

    phase = action.get("phase")
    if phase not in PHASES:
        raise AuditError(f"{name} has unknown/missing conditional phase {phase!r}")
    require_text(action.get("predicate"), f"{name} predicate")
    if not writes and phase != "DIAGNOSTIC_ONLY":
        raise AuditError(f"{name} conditional action has no physical write family")
    if writes and phase == "DIAGNOSTIC_ONLY":
        raise AuditError(f"{name} diagnostic-only action advertises writes")
    if aggregate and phase == "DIAGNOSTIC_ONLY":
        raise AuditError(f"aggregate {name} cannot be diagnostic-only")


def validate_manifest(data: Any, problem_codes: list[str] | None) -> dict[str, int]:
    if not isinstance(data, dict) or data.get("format") != 1:
        raise AuditError("audit format must be 1")
    upstream = data.get("upstream")
    if not isinstance(upstream, dict):
        raise AuditError("missing upstream identity")
    if upstream.get("commit") != PINNED_COMMIT:
        raise AuditError("audit is not bound to the pinned ntfs-next commit")
    if upstream.get("archive_sha256") != PINNED_ARCHIVE_SHA256:
        raise AuditError("audit is not bound to the independently hashed archive")
    if data.get("contract") != "resource/entry/roothealth/REPAIR-CONTRACT.md":
        raise AuditError("audit does not name the normative repair contract")

    gates = data.get("global_gates")
    if not isinstance(gates, dict) or set(PHASES) - set(gates):
        raise AuditError("audit omits a conditional phase gate")
    require_text(gates.get("PREIDENTITY_WAL_RECOVERY"), "pre-identity WAL gate")
    for phase in PHASES:
        require_text(gates.get(phase), f"{phase} gate")

    raw_families = data.get("write_families")
    if not isinstance(raw_families, dict) or not raw_families:
        raise AuditError("write_families must be a non-empty object")
    families = set(raw_families)
    for family, description in raw_families.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]+", family):
            raise AuditError(f"invalid write-family ID {family!r}")
        require_text(description, f"write family {family}")

    problems = unique_entries(data.get("problems"), "code", "problems")
    for action in problems:
        name = action["code"]
        if not re.fullmatch(r"PR_[A-Z0-9_]+", name):
            raise AuditError(f"invalid problem code {name!r}")
        validate_action(action, name, families, aggregate=False)
    manifest_codes = [action["code"] for action in problems]
    if problem_codes is not None:
        missing = sorted(set(problem_codes) - set(manifest_codes))
        unknown = sorted(set(manifest_codes) - set(problem_codes))
        if missing:
            raise AuditError("unclassified problem codes: " + ", ".join(missing))
        if unknown:
            raise AuditError("unknown problem codes: " + ", ".join(unknown))
        if manifest_codes != problem_codes:
            raise AuditError("problem classifications are not in pinned enum order")

    aggregates = unique_entries(data.get("aggregates"), "id", "aggregates")
    aggregate_ids = {action["id"] for action in aggregates}
    if aggregate_ids != REQUIRED_AGGREGATES:
        missing = sorted(REQUIRED_AGGREGATES - aggregate_ids)
        unknown = sorted(aggregate_ids - REQUIRED_AGGREGATES)
        raise AuditError(
            "aggregate set mismatch; missing="
            + ",".join(missing)
            + " unknown="
            + ",".join(unknown)
        )
    for action in aggregates:
        validate_action(action, action["id"], families, aggregate=True)

    hazards = unique_entries(data.get("hazards"), "category", "hazards")
    hazard_ids = {item["category"] for item in hazards}
    if hazard_ids != REQUIRED_HAZARDS:
        raise AuditError("hazard inventory is incomplete or contains an unknown category")
    for hazard in hazards:
        status = hazard.get("status")
        if not isinstance(status, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]+", status):
            raise AuditError(f"{hazard['category']} has an invalid status")
        require_text(hazard.get("finding"), f"{hazard['category']} finding")
        refs = hazard.get("sources")
        if not isinstance(refs, list) or not refs:
            raise AuditError(f"{hazard['category']} has no source evidence")
        bad = [ref for ref in refs if not isinstance(ref, str) or not SOURCE_REF.fullmatch(ref)]
        if bad:
            raise AuditError(f"{hazard['category']} has malformed source reference")

    counts = Counter(action["decision"] for action in problems)
    aggregate_counts = Counter(action["decision"] for action in aggregates)
    return {
        "problems": len(problems),
        "conditional": counts["CONDITIONAL"],
        "deny": counts["DENY"],
        "aggregates": len(aggregates),
        "aggregate_conditional": aggregate_counts["CONDITIONAL"],
        "aggregate_deny": aggregate_counts["DENY"],
        "write_families": len(families),
        "hazards": len(hazards),
    }


def expect_failure(data: dict[str, Any], needle: str) -> None:
    try:
        validate_manifest(data, None)
    except AuditError as error:
        if needle not in str(error):
            raise AuditError(
                f"self-test expected {needle!r}, received {str(error)!r}"
            ) from error
    else:
        raise AuditError(f"self-test mutation {needle!r} unexpectedly passed")


def self_test(audit_path: Path) -> dict[str, int]:
    data = json.loads(audit_path.read_text(encoding="utf-8"))
    counts = validate_manifest(data, None)

    mutation = deepcopy(data)
    mutation["aggregates"].pop()
    expect_failure(mutation, "aggregate set mismatch")

    mutation = deepcopy(data)
    mutation["problems"][0]["decision"] = "ALLOW"
    expect_failure(mutation, "blanket ALLOW")

    mutation = deepcopy(data)
    conditional = next(x for x in mutation["problems"] if x["decision"] == "CONDITIONAL")
    conditional["writes"] = ["RAW_UNTRACKED_WRITE"]
    expect_failure(mutation, "unknown write families")

    mutation = deepcopy(data)
    denied = next(x for x in mutation["problems"] if x["decision"] == "DENY")
    denied["writes"] = ["MFT_RECORD"]
    expect_failure(mutation, "DENY but advertises")

    mutation = deepcopy(data)
    mutation["hazards"].pop()
    expect_failure(mutation, "hazard inventory")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "audit",
        nargs="?",
        type=Path,
        default=Path(__file__).with_name("repair-policy-audit.json"),
    )
    parser.add_argument("problem_header", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            counts = self_test(args.audit)
        else:
            if args.problem_header is None:
                raise AuditError("problem_header is required unless --self-test is used")
            data = json.loads(args.audit.read_text(encoding="utf-8"))
            codes = parse_problem_codes(args.problem_header.read_text(encoding="utf-8"))
            counts = validate_manifest(data, codes)
        print(json.dumps(counts, sort_keys=True))
        return 0
    except (AuditError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"roothealth repair-policy audit check failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
