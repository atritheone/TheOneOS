#!/usr/bin/env python3
"""Fail closed unless every ntfs-next problem code has a roothealth policy."""

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
import json
from pathlib import Path
import re
import sys


class PolicyError(RuntimeError):
    pass


DECISIONS = {"ALLOW", "CONDITIONAL", "DENY"}
POLICY_PATTERN = re.compile(
    r"ROOTHEALTH_PROBLEM_POLICY\s*\(\s*"
    r"(?P<code>PR_[A-Z0-9_]+)\s*,\s*"
    r"(?P<decision>[A-Z0-9_]+)\s*\)",
    re.MULTILINE,
)
AGGREGATE_PATTERN = re.compile(
    r"ROOTHEALTH_AGGREGATE_POLICY\s*\(\s*"
    r"(?P<name>[A-Z0-9_]+)\s*,\s*"
    r"(?P<decision>[A-Z0-9_]+)\s*\)",
    re.MULTILINE,
)
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


def without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def parse_problem_codes(source: str, description: str) -> list[str]:
    source = without_comments(source)
    matches = re.findall(
        r"typedef\s+enum\s*\{(?P<body>[^}]*)\}\s*problem_code_t\s*;",
        source,
        flags=re.DOTALL,
    )
    if len(matches) != 1:
        raise PolicyError(
            f"expected exactly one problem_code_t enum in {description}, found {len(matches)}"
        )
    codes = re.findall(r"\bPR_[A-Z0-9_]+\b", matches[0])
    if not codes:
        raise PolicyError(f"problem_code_t in {description} contains no problem codes")
    if codes[0] != "PR_PRE_SCAN_MFT":
        raise PolicyError(
            "problem_code_t parser did not select the expected enum: "
            f"first member is {codes[0]!r}, not PR_PRE_SCAN_MFT"
        )
    flag_constants = {"PR_PREEN_NOMSG", "PR_NO_NOMSG", "PR_FLAG_MAX"}
    leaked_flags = sorted(flag_constants.intersection(codes))
    if leaked_flags:
        raise PolicyError(
            "problem_flag_t constants leaked into problem_code_t: "
            + ", ".join(leaked_flags)
        )
    duplicates = sorted({code for code in codes if codes.count(code) > 1})
    if duplicates:
        raise PolicyError(f"duplicate problem_code_t members: {', '.join(duplicates)}")
    return codes


def problem_codes(header: Path) -> list[str]:
    return parse_problem_codes(header.read_text(encoding="utf-8"), str(header))


def self_test() -> None:
    source = """
typedef enum {
    PR_PREEN_NOMSG = 1,
    PR_NO_NOMSG = 2,
    PR_FLAG_MAX = 4
} problem_flag_t;
typedef enum {
    PR_PRE_SCAN_MFT = 0,
    PR_SAMPLE_PROBLEM
} problem_code_t;
"""
    if parse_problem_codes(source, "embedded parser self-test") != [
        "PR_PRE_SCAN_MFT",
        "PR_SAMPLE_PROBLEM",
    ]:
        raise PolicyError("problem_code_t parser self-test failed")
    if len(REQUIRED_AGGREGATES) != 14:
        raise PolicyError(
            f"aggregate policy self-test expected 14 IDs, found {len(REQUIRED_AGGREGATES)}"
        )


def expanded_policy_source(source_path: Path) -> str:
    source = source_path.read_text(encoding="utf-8")
    definition = source_path.with_name("roothealth_problem_policy.def")
    if definition.is_file():
        source += "\n" + definition.read_text(encoding="utf-8")
    return without_comments(source)


def policy_entries(source_path: Path) -> dict[str, str]:
    source = expanded_policy_source(source_path)
    entries: dict[str, str] = {}
    for match in POLICY_PATTERN.finditer(source):
        code = match.group("code")
        decision = match.group("decision")
        if decision not in DECISIONS:
            raise PolicyError(
                f"{code} uses forbidden/unknown decision {decision}; "
                "only ALLOW, CONDITIONAL, or DENY are explicit"
            )
        if code in entries:
            raise PolicyError(f"duplicate roothealth policy entry for {code}")
        entries[code] = decision
    if not entries:
        raise PolicyError(
            f"{source_path} has no ROOTHEALTH_PROBLEM_POLICY(code, decision) entries"
        )
    return entries


def aggregate_entries(source_path: Path) -> dict[str, str]:
    source = expanded_policy_source(source_path)
    entries: dict[str, str] = {}
    for match in AGGREGATE_PATTERN.finditer(source):
        name = match.group("name")
        decision = match.group("decision")
        if decision not in {"CONDITIONAL", "DENY"}:
            raise PolicyError(
                f"aggregate {name} uses forbidden decision {decision}; "
                "aggregate AUTO/ALLOW is not permitted"
            )
        if name in entries:
            raise PolicyError(f"duplicate roothealth aggregate policy entry for {name}")
        entries[name] = decision
    missing = sorted(REQUIRED_AGGREGATES - set(entries))
    unknown = sorted(set(entries) - REQUIRED_AGGREGATES)
    if missing:
        raise PolicyError(
            "roothealth policy has no explicit aggregate decision for: "
            + ", ".join(missing)
        )
    if unknown:
        raise PolicyError(
            "roothealth policy contains unknown aggregate IDs: " + ", ".join(unknown)
        )
    return entries


def engine_source_files(paths: list[Path], manifest: Path | None) -> list[Path]:
    if manifest is not None:
        if len(paths) != 1 or not paths[0].is_dir():
            raise PolicyError(
                "translation-unit manifest requires one engine source directory"
            )
        root = paths[0].resolve()
        entries: list[Path] = []
        for line_number, raw_line in enumerate(
            manifest.read_text(encoding="utf-8").splitlines(), 1
        ):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            relative = Path(line)
            if relative.is_absolute() or relative.suffix != ".c" or ".." in relative.parts:
                raise PolicyError(
                    f"translation-unit manifest line {line_number} is not a safe relative C path"
                )
            resolved = (root / relative).resolve()
            try:
                resolved.relative_to(root)
            except ValueError as error:
                raise PolicyError(f"translation unit escapes engine source: {line}") from error
            if not resolved.is_file():
                raise PolicyError(f"linked translation unit is absent: {line}")
            if resolved in entries:
                raise PolicyError(f"duplicate linked translation unit: {line}")
            entries.append(resolved)
        if not entries:
            raise PolicyError("translation-unit manifest contains no C files")
        return entries
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.c")))
        elif path.is_file() and path.suffix == ".c":
            files.append(path)
        else:
            raise PolicyError(f"engine source input is not a C file/directory: {path}")
    if not files:
        raise PolicyError("no engine C source files were supplied")
    return files


def reject_raw_ask_repair(paths: list[Path], manifest: Path | None) -> None:
    violations: list[str] = []
    call = re.compile(r"\bntfs_ask_repair\s*\(")
    definition = re.compile(
        r"^\s*(?:(?:static|inline)\s+)*(?:BOOL|bool|int)\s+"
        r"ntfs_ask_repair\s*\("
    )
    files = engine_source_files(paths, manifest)
    problem_sources = [path for path in files if path.as_posix().endswith("libntfs/problem.c")]
    libntfs_gate = False
    if len(problem_sources) == 1:
        problem_source = without_comments(problem_sources[0].read_text(encoding="utf-8"))
        libntfs_gate = bool(
            re.search(
                r"if\s*\(\s*NVolFsNoRepair\s*\(\s*vol\s*\)\s*\|\|\s*"
                r"!\s*NVolFsck\s*\(\s*vol\s*\)\s*\)\s*\{[^{}]*return\s+FALSE\s*;",
                problem_source,
                re.DOTALL,
            )
        )
    for path in files:
        source = without_comments(path.read_text(encoding="utf-8"))
        for line_number, line in enumerate(source.splitlines(), 1):
            if call.search(line) and not definition.search(line):
                # Upstream libntfs retains interactive fsck call sites. They are
                # unreachable as mutation authority in RootHealth because the
                # single implementation hard-denies every FS_NO_REPAIR or
                # non-fsck volume before consulting any repair mode.
                if libntfs_gate and "/libntfs/" in path.as_posix():
                    continue
                violations.append(f"{path}:{line_number}")
    if violations:
        raise PolicyError(
            "raw ntfs_ask_repair() remains reachable outside the explicit "
            "roothealth policy: " + ", ".join(violations)
        )


def destructive(code: str) -> bool:
    exact = {
        "PR_RESET_LOG_FILE",
        "PR_ORPHANED_MFT_OPEN_FAILURE",
        "PR_ORPHANED_MFT_CHECK_FAILURE",
    }
    patterns = (
        r"COMPRESS.*SPARS|SPARS.*COMPRESS",
        r"UNREADABLE.*(?:MFT|RECORD)|(?:MFT|RECORD).*UNREADABLE",
        r"DELETE.*(?:MFT|RECORD)|(?:MFT|RECORD).*DELETE",
        r"(?:FN|FILENAME).*CORRUPT.*DELETE|DELETE.*(?:FN|FILENAME).*CORRUPT",
        r"DELETED.*(?:REMOVE|DELETE)|(?:REMOVE|DELETE).*DELETED",
        r"ORPHAN.*(?:EXTENT|RELEASE)|(?:EXTENT|RELEASE).*ORPHAN",
    )
    return code in exact or any(re.search(pattern, code) for pattern in patterns)


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        try:
            self_test()
            print(
                "roothealth repair policy self-test passed: "
                "enum_isolated=true aggregate_ids=14"
            )
            return 0
        except PolicyError as error:
            print(f"roothealth repair policy self-test failed: {error}", file=sys.stderr)
            return 1
    parser = argparse.ArgumentParser()
    parser.add_argument("problem_header", type=Path)
    parser.add_argument("policy_source", type=Path)
    parser.add_argument("--translation-unit-manifest", type=Path)
    parser.add_argument("engine_source", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        self_test()
        codes = problem_codes(args.problem_header)
        entries = policy_entries(args.policy_source)
        aggregates = aggregate_entries(args.policy_source)
        reject_raw_ask_repair(args.engine_source, args.translation_unit_manifest)
        code_set = set(codes)
        entry_set = set(entries)
        missing = sorted(code_set - entry_set)
        unknown = sorted(entry_set - code_set)
        if missing:
            raise PolicyError(
                "roothealth policy has no explicit decision for: " + ", ".join(missing)
            )
        if unknown:
            raise PolicyError(
                "roothealth policy names codes absent from ntfs-next: "
                + ", ".join(unknown)
            )
        unsafe_allow = sorted(
            code for code, decision in entries.items()
            if destructive(code) and decision == "ALLOW"
        )
        if unsafe_allow:
            raise PolicyError(
                "destructive problems require DENY or CONDITIONAL handling: "
                + ", ".join(unsafe_allow)
            )
        counts = {decision.lower(): list(entries.values()).count(decision) for decision in DECISIONS}
        print(
            json.dumps(
                {
                    "format": 1,
                    "problem_codes": len(codes),
                    "decisions": counts,
                    "aggregate_decisions": {
                        decision.lower(): list(aggregates.values()).count(decision)
                        for decision in ("CONDITIONAL", "DENY")
                    },
                    "destructive_guarded": sorted(code for code in codes if destructive(code)),
                    "raw_ntfs_ask_repair_calls": 0,
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, UnicodeError, PolicyError) as error:
        print(f"roothealth repair policy check failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
