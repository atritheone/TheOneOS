#!/usr/bin/env python3
"""Fail closed on policy-decision drift and uncontained repair hazards."""

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
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


PINNED_COMMIT = "d4f481df6926557f7b18b471a43313652dec6f7e"
DECISIONS = {"CONDITIONAL", "DENY"}
ROLE = re.compile(
    r"ROOTHEALTH_REPAIR_ROLE\s*\(\s*"
    r"(?P<role>DIAGNOSTIC|TYPED_WAL_ADAPTER)\s*\)"
)
PROBLEM_POLICY = re.compile(
    r"ROOTHEALTH_PROBLEM_POLICY\s*\(\s*"
    r"(?P<name>PR_[A-Z0-9_]+)\s*,\s*"
    r"(?P<decision>[A-Z0-9_]+)\s*\)",
    re.MULTILINE,
)
AGGREGATE_POLICY = re.compile(
    r"ROOTHEALTH_AGGREGATE_POLICY\s*\(\s*"
    r"(?P<name>[A-Z0-9_]+)\s*,\s*"
    r"(?P<decision>[A-Z0-9_]+)\s*\)",
    re.MULTILINE,
)

# Audit write-family names deliberately differ from a few internal enum names.
# Keep this translation exhaustive so a renamed/unknown enum can never silently
# collapse onto a nearby family.
WRITE_KIND_TO_AUDIT_FAMILY = {
    "RH_WRITE_BOOT_PRIMARY": "BOOT_PRIMARY",
    "RH_WRITE_BOOT_BACKUP": "BOOT_BACKUP",
    "RH_WRITE_MFT_PRIMARY": "MFT_PRIMARY_BOOTSTRAP",
    "RH_WRITE_MFT_MIRROR": "MFT_MIRROR",
    "RH_WRITE_LOGFILE_REDO": "LOGFILE_REDO",
    "RH_WRITE_LOGFILE_RESTART": "LOGFILE_RESTART",
    "RH_WRITE_MFT_RECORD": "MFT_RECORD",
    "RH_WRITE_ATTRIBUTE_LIST": "ATTRIBUTE_LIST",
    "RH_WRITE_RUNLIST_MAPPING_PAIRS": "RUNLIST_MAPPING_PAIRS",
    "RH_WRITE_ATTRIBUTE_DATA": "ATTRIBUTE_DATA",
    "RH_WRITE_INDEX_ROOT": "INDEX_ROOT",
    "RH_WRITE_INDEX_ALLOCATION": "INDEX_ALLOCATION",
    "RH_WRITE_INDEX_BITMAP": "INDEX_BITMAP",
    "RH_WRITE_CLUSTER_DATA": "CLUSTER_DATA",
    "RH_WRITE_RECOVERY_NAMESPACE": "RECOVERY_NAMESPACE",
    "RH_WRITE_REPARSE_INDEX": "REPARSE_INDEX",
    "RH_WRITE_SECURE_SDS": "SECURE_SDS",
    "RH_WRITE_SECURE_SDH": "SECURE_SDH",
    "RH_WRITE_SECURE_SII": "SECURE_SII",
    "RH_WRITE_UPCASE_DATA": "UPCASE_DATA",
    "RH_WRITE_ATTRDEF_DATA": "ATTRDEF_DATA",
    "RH_WRITE_BITMAP_MFT": "MFT_BITMAP",
    "RH_WRITE_BITMAP_CLUSTER": "CLUSTER_BITMAP",
    "RH_WRITE_VOLUME_DIRTY_SET": "VOLUME_DIRTY_SET",
    "RH_WRITE_VOLUME_DIRTY_CLEAR": "VOLUME_DIRTY_CLEAR",
}
AUDIT_WRITE_FAMILIES = set(WRITE_KIND_TO_AUDIT_FAMILY.values())
FACT_TOKEN = re.compile(r"^RH_FACT_[A-Z0-9_]+$")
IMPLEMENTATION_TABLES = {
    "rh_problem_implementations": "problem",
    "rh_aggregate_implementations": "aggregate",
}

# These operations violate the product contract even if their bytes would pass
# through the WAL.  Definitions/prototypes may remain in a linked libntfs object,
# but no linked roothealth call site may invoke them.
ABSOLUTE_FORBIDDEN_CALLS = {
    "ntfs_ask_repair": "interactive/raw repair decision",
    "ntfs_logfile_reset": "$LogFile reset",
    "ntfs_delete": "file/content deletion",
    "ntfs_rl_punch_hole": "runlist hole punching",
    "ntfs_remove_ntfs_reparse_data": "reparse payload removal",
    "ntfsck_empty_deleted_dir": "$Deleted purge",
    "ntfsck_purge_deleted_dir": "$Deleted recursive purge",
    "ntfsck_create_lost_found": "lost+found creation",
    "ntfsck_add_inode_to_lostfound": "lost+found relink",
    "ntfsck_add_nameless_inode_to_lostfound": "lost+found synthesized name",
    "ntfsck_delete_orphaned_mft": "orphaned-record deletion",
    "ntfsck_check_mft_record_unused": "MFT record deallocation",
    "ntfsck_sparse_compression_unit": "compressed-content sparsification",
    "ntfsck_remove_filename": "unproved filename removal",
}

# These can be part of an approved data-preserving action, but only in a small,
# explicitly reviewed adapter that converts typed policy actions into WAL-backed
# mutations.  Ordinary diagnosis and traversal translation units cannot call them.
TYPED_WAL_ONLY_CALLS = {
    "ntfs_pwrite": "raw target write",
    "ntfs_attr_pwrite": "attribute write",
    "ntfs_attr_mst_pwrite": "MST attribute write",
    "ntfs_mft_record_write": "MFT record write",
    "ntfs_mft_records_write": "MFT record write",
    "ntfs_ib_write": "INDX block write",
    "ntfs_attr_rm": "attribute removal",
    "ntfs_attr_add": "attribute creation",
    "ntfs_attr_truncate": "attribute resize",
    "ntfs_attr_update_mapping_pairs": "mapping-pair rewrite",
    "ntfs_index_rm": "index-entry removal",
    "ntfs_index_add_filename": "index-entry insertion",
    "ntfs_bitmap_clear_bit": "on-disk allocation-bit clear",
    "ntfs_bitmap_set_bit": "on-disk allocation-bit set",
    "ntfs_fsck_mftbmp_clear": "computed MFT allocation-bit clear",
    "ntfs_fsck_mftbmp_set": "computed MFT allocation-bit set",
    "ntfs_cluster_free": "cluster release",
    "ntfs_cluster_free_from_rl": "runlist cluster release",
    "ntfs_cluster_alloc": "cluster allocation",
    "ntfs_inode_mark_dirty": "deferred inode write",
    "ntfs_volume_write_flags": "volume-flag write",
    "ntfs_upcase_repair": "$UpCase replacement",
    "ntfs_attrdef_repair": "$AttrDef replacement",
    "ntfs_recover_mft": "MFT redundant-copy restore",
    "ntfs_recover_mft_from_mftmirr": "MFT bootstrap restore",
}

# Function declarations and definitions are not call sites.  This deliberately
# accepts common ntfs-next return types while rejecting statement keywords.
DECLARATION = re.compile(
    r"(?m)^[ \t]*(?:(?:static|extern|inline|const|__attribute__\s*\(\([^\n]*\)\))\s+)*"
    r"(?:void|int|long|s64|u64|BOOL|bool|ssize_t|size_t|struct\s+[A-Za-z_]\w*|"
    r"[A-Za-z_]\w*\s*\*)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:;|\{)",
    re.DOTALL,
)


class GateError(RuntimeError):
    pass


def mask_comments_and_literals(source: str) -> str:
    """Replace comments/literals with spaces while retaining offsets/newlines."""

    pattern = re.compile(
        r"/\*.*?\*/|//[^\n]*|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'",
        re.DOTALL,
    )

    def mask(match: re.Match[str]) -> str:
        return "".join("\n" if char == "\n" else " " for char in match.group(0))

    return pattern.sub(mask, source)


def strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", source)


def line_number(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def manifest_entries(text: str) -> list[Path]:
    entries: list[Path] = []
    for number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        entry = Path(line)
        if entry.is_absolute() or entry.suffix != ".c" or ".." in entry.parts:
            raise GateError(
                f"translation-unit manifest line {number} is not a safe relative C path: {line!r}"
            )
        if entry in entries:
            raise GateError(f"duplicate linked translation unit: {line}")
        entries.append(entry)
    if not entries:
        raise GateError("translation-unit manifest contains no C files")
    return entries


def linked_sources(root: Path, manifest: Path) -> list[Path]:
    if not root.is_dir():
        raise GateError(f"engine source is not a directory: {root}")
    root = root.resolve()
    paths: list[Path] = []
    for relative in manifest_entries(manifest.read_text(encoding="utf-8")):
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise GateError(f"translation unit escapes engine source: {relative}") from error
        if not candidate.is_file():
            raise GateError(f"linked translation unit is absent: {relative}")
        paths.append(candidate)
    return paths


def audit_entries(data: Any, field: str, key: str) -> list[tuple[str, str]]:
    if not isinstance(data, dict) or data.get("format") != 1:
        raise GateError("repair-policy audit format must be 1")
    upstream = data.get("upstream")
    if not isinstance(upstream, dict) or upstream.get("commit") != PINNED_COMMIT:
        raise GateError("repair-policy audit is not bound to the pinned ntfs-next commit")
    raw_entries = data.get(field)
    if not isinstance(raw_entries, list) or not raw_entries:
        raise GateError(f"audit {field} must be a non-empty list")
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for offset, item in enumerate(raw_entries):
        if not isinstance(item, dict):
            raise GateError(f"audit {field}[{offset}] is not an object")
        name = item.get(key)
        decision = item.get("decision")
        if not isinstance(name, str) or not name:
            raise GateError(f"audit {field}[{offset}] has no {key}")
        if name in seen:
            raise GateError(f"audit {field} repeats {name}")
        if decision not in DECISIONS:
            raise GateError(f"audit decision for {name} is not CONDITIONAL or DENY")
        seen.add(name)
        entries.append((name, decision))
    return entries


def audit_implementation_contracts(
    data: Any, field: str, key: str, known_facts: set[str]
) -> dict[str, dict[str, object]]:
    """Return only entries explicitly approved for product implementation."""

    # Reuse the cardinality/commit/decision validation before consuming the
    # richer fields.  This also makes this parser fail in the same way as the
    # definition comparison if the audit envelope drifts.
    audit_entries(data, field, key)
    contracts: dict[str, dict[str, object]] = {}
    for offset, item in enumerate(data[field]):
        assert isinstance(item, dict)
        name = item[key]
        writes = item.get("writes")
        if not isinstance(writes, list):
            raise GateError(f"audit {field}[{offset}].writes must be an array")
        if any(not isinstance(value, str) for value in writes):
            raise GateError(f"audit writes for {name} contain a non-string family")
        if len(set(writes)) != len(writes):
            raise GateError(f"audit writes for {name} contain a duplicate family")
        unknown_writes = sorted(set(writes) - AUDIT_WRITE_FAMILIES)
        if unknown_writes:
            raise GateError(
                f"audit writes for {name} contain unknown families: "
                f"{', '.join(unknown_writes)}"
            )

        facts = item.get("required_facts")
        if facts is None:
            continue
        if item.get("decision") != "CONDITIONAL":
            raise GateError(f"DENY policy {name} cannot carry an implementation contract")
        if not writes:
            raise GateError(f"implemented policy {name} has no audited write family")
        if not isinstance(facts, list) or not facts:
            raise GateError(f"audit required_facts for {name} must be a nonempty array")
        if any(not isinstance(value, str) or not FACT_TOKEN.fullmatch(value) for value in facts):
            raise GateError(f"audit required_facts for {name} contain an invalid token")
        if len(set(facts)) != len(facts):
            raise GateError(f"audit required_facts for {name} contain a duplicate token")
        unknown_facts = sorted(set(facts) - known_facts)
        if unknown_facts:
            raise GateError(
                f"audit required_facts for {name} are unknown to the product enum: "
                f"{', '.join(unknown_facts)}"
            )
        contracts[name] = {
            "decision": item["decision"],
            "writes": writes,
            "required_facts": facts,
        }
    return contracts


def policy_entries(source: str, pattern: re.Pattern[str], label: str) -> list[tuple[str, str]]:
    source = strip_comments(source)
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in pattern.finditer(source):
        name = match.group("name")
        decision = match.group("decision")
        if name in seen:
            raise GateError(f"policy source repeats {label} {name}")
        if decision not in DECISIONS:
            raise GateError(
                f"policy {label} {name} uses {decision}; only audited CONDITIONAL/DENY are valid"
            )
        seen.add(name)
        entries.append((name, decision))
    if not entries:
        raise GateError(f"policy source has no {label} entries")
    return entries


def compare_entries(
    expected: list[tuple[str, str]], actual: list[tuple[str, str]], label: str
) -> None:
    expected_map = dict(expected)
    actual_map = dict(actual)
    missing = sorted(set(expected_map) - set(actual_map))
    unknown = sorted(set(actual_map) - set(expected_map))
    drift = sorted(
        name
        for name in set(expected_map).intersection(actual_map)
        if expected_map[name] != actual_map[name]
    )
    if missing:
        raise GateError(f"policy is missing audited {label} entries: {', '.join(missing)}")
    if unknown:
        raise GateError(f"policy has unaudited {label} entries: {', '.join(unknown)}")
    if drift:
        details = ", ".join(
            f"{name}={actual_map[name]} (audit {expected_map[name]})" for name in drift
        )
        raise GateError(f"policy decision drift for {label}: {details}")
    if actual != expected:
        raise GateError(f"policy {label} entries are not in audited order")


def matching_delimiter(masked: str, opening: int, left: str, right: str) -> int:
    depth = 0
    for offset in range(opening, len(masked)):
        value = masked[offset]
        if value == left:
            depth += 1
        elif value == right:
            depth -= 1
            if depth == 0:
                return offset
            if depth < 0:
                break
    raise GateError(f"unterminated {left}{right} expression in policy implementation")


def split_c_arguments(source: str) -> list[str]:
    masked = mask_comments_and_literals(source)
    arguments: list[str] = []
    start = 0
    round_depth = square_depth = brace_depth = 0
    for offset, value in enumerate(masked):
        if value == "(":
            round_depth += 1
        elif value == ")":
            round_depth -= 1
        elif value == "[":
            square_depth += 1
        elif value == "]":
            square_depth -= 1
        elif value == "{":
            brace_depth += 1
        elif value == "}":
            brace_depth -= 1
        elif value == "," and not (round_depth or square_depth or brace_depth):
            arguments.append(source[start:offset].strip())
            start = offset + 1
        if min(round_depth, square_depth, brace_depth) < 0:
            raise GateError("unbalanced implementation macro arguments")
    if round_depth or square_depth or brace_depth:
        raise GateError("unbalanced implementation macro arguments")
    arguments.append(source[start:].strip())
    return arguments


def policy_fact_enum(engine_root: Path) -> set[str]:
    header = engine_root / "src" / "roothealth_policy.h"
    if not header.is_file():
        raise GateError(f"product policy header is absent: {header}")
    source = strip_comments(header.read_text(encoding="utf-8"))
    match = re.search(r"\benum\s+rh_policy_fact\s*\{(?P<body>[^}]*)\}", source)
    if not match:
        raise GateError("product policy header has no bounded rh_policy_fact enum")
    facts = re.findall(r"\bRH_FACT_[A-Z0-9_]+\b", match.group("body"))
    if not facts or len(facts) != len(set(facts)):
        raise GateError("rh_policy_fact contains no facts or repeats a fact token")
    if "RH_POLICY_FACT_COUNT" not in match.group("body"):
        raise GateError("rh_policy_fact has no terminal RH_POLICY_FACT_COUNT")
    return set(facts)


def implementation_fact_macros(
    paths: list[Path], known_facts: set[str]
) -> dict[str, list[str]]:
    definitions: dict[str, list[str]] = {}
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        offset = 0
        while offset < len(lines):
            match = re.match(
                r"^\s*#define\s+(?P<name>RH_[A-Z0-9_]+_FACTS)\s+(?P<body>.*)$",
                lines[offset],
            )
            if not match:
                offset += 1
                continue
            name = match.group("name")
            body_lines = [match.group("body")]
            while lines[offset].rstrip().endswith("\\"):
                offset += 1
                if offset >= len(lines):
                    raise GateError(f"unterminated fact macro {name} in {path}")
                body_lines.append(lines[offset])
            body = "\n".join(body_lines)
            calls = re.findall(
                r"\bRH_FACT_MASK\s*\(\s*(RH_FACT_[A-Z0-9_]+)\s*\)", body
            )
            if not calls or body.count("RH_FACT_MASK") != len(calls):
                raise GateError(f"fact macro {name} has an unparsed or empty fact mask")
            mentioned = [
                token
                for token in re.findall(r"\bRH_FACT_[A-Z0-9_]+\b", body)
                if token != "RH_FACT_MASK"
            ]
            if mentioned != calls:
                raise GateError(f"fact macro {name} contains a fact outside RH_FACT_MASK")
            if len(calls) != len(set(calls)):
                raise GateError(f"fact macro {name} repeats a required fact")
            unknown = sorted(set(calls) - known_facts)
            if unknown:
                raise GateError(
                    f"fact macro {name} uses unknown facts: {', '.join(unknown)}"
                )
            if name in definitions:
                raise GateError(f"linked closure repeats fact macro {name}")
            definitions[name] = calls
            offset += 1
    if not definitions:
        raise GateError("linked closure has no explicit implementation fact macros")
    return definitions


def implementation_array_body(source: str, table: str) -> tuple[str, str]:
    masked = mask_comments_and_literals(source)
    match = re.search(
        rf"\bstatic\s+const\s+struct\s+rh_policy_implementation\s+"
        rf"\b{re.escape(table)}\s*\[\s*(?P<size>[^]]+)\s*\]\s*=\s*\{{",
        masked,
        re.DOTALL,
    )
    if not match:
        raise GateError(f"linked policy source has no immutable enum-indexed {table}")
    opening = match.end() - 1
    closing = matching_delimiter(masked, opening, "{", "}")
    return source[opening + 1 : closing], match.group("size").strip()


def parse_implementation_table(
    body: str,
    scope: str,
    fact_macros: dict[str, list[str]],
) -> dict[str, dict[str, object]]:
    masked = mask_comments_and_literals(body)
    entry = re.compile(
        r"\[\s*(?P<name>PR_[A-Z0-9_]+|RH_POLICY_AGGREGATE_[A-Z0-9_]+)\s*\]"
        r"\s*=\s*RH_IMPLEMENTATION\s*\("
    )
    implementations: dict[str, dict[str, object]] = {}
    parsed_calls = 0
    for match in entry.finditer(masked):
        opening = match.end() - 1
        closing = matching_delimiter(masked, opening, "(", ")")
        arguments = split_c_arguments(body[opening + 1 : closing])
        if len(arguments) != 5:
            raise GateError(
                f"{scope} implementation {match.group('name')} does not have 5 sealed fields"
            )
        raw_name = match.group("name")
        if scope == "problem":
            if not raw_name.startswith("PR_"):
                raise GateError(f"problem implementation uses aggregate designator {raw_name}")
            name = raw_name
        else:
            prefix = "RH_POLICY_AGGREGATE_"
            if not raw_name.startswith(prefix):
                raise GateError(f"aggregate implementation uses problem designator {raw_name}")
            name = raw_name[len(prefix) :]
        if name in implementations:
            raise GateError(f"implementation table repeats {scope} {name}")

        profile, evidence, source_pass, action, fact_macro = arguments
        if not re.fullmatch(r"RH_POLICY_PROFILE_[A-Z0-9_]+", profile):
            raise GateError(f"implementation {name} has an invalid profile token")
        text_fields: list[str] = []
        for label, value in (("evidence", evidence), ("source pass", source_pass)):
            text_match = re.fullmatch(r'"([a-z0-9][a-z0-9-]*)"', value)
            if not text_match:
                raise GateError(f"implementation {name} has a noncanonical {label} id")
            text_fields.append(text_match.group(1))
        if not re.fullmatch(r"RH_WRITE_[A-Z0-9_]+", action):
            raise GateError(f"implementation {name} has an unparsed action mask")
        if action not in WRITE_KIND_TO_AUDIT_FAMILY:
            raise GateError(f"implementation {name} uses unknown action kind {action}")
        if not re.fullmatch(r"RH_[A-Z0-9_]+_FACTS", fact_macro):
            raise GateError(f"implementation {name} has an unparsed fact mask")
        if fact_macro not in fact_macros:
            raise GateError(f"implementation {name} uses undefined fact macro {fact_macro}")
        implementations[name] = {
            "scope": scope,
            "profile": profile,
            "evidence_id": text_fields[0],
            "source_pass": text_fields[1],
            "writes": [WRITE_KIND_TO_AUDIT_FAMILY[action]],
            "write_kinds": [action],
            "required_facts": fact_macros[fact_macro],
            "fact_macro": fact_macro,
        }
        parsed_calls += 1

    all_calls = len(re.findall(r"\bRH_IMPLEMENTATION\s*\(", masked))
    if all_calls != parsed_calls:
        raise GateError(
            f"{scope} implementation table has {all_calls - parsed_calls} unparsed entries"
        )
    return implementations


def product_implementations(
    engine_root: Path, paths: list[Path], known_facts: set[str]
) -> dict[str, dict[str, dict[str, object]]]:
    fact_macros = implementation_fact_macros(paths, known_facts)
    tables: dict[str, dict[str, dict[str, object]]] = {}
    for table, scope in IMPLEMENTATION_TABLES.items():
        matches: list[tuple[Path, str, str]] = []
        for path in paths:
            source = path.read_text(encoding="utf-8")
            if re.search(rf"\b{re.escape(table)}\s*\[", source):
                body, size = implementation_array_body(source, table)
                matches.append((path, body, size))
        if len(matches) != 1:
            raise GateError(
                f"linked closure must define {table} exactly once; found {len(matches)}"
            )
        _, body, size = matches[0]
        expected_size = (
            "RH_PROBLEM_ARRAY_SIZE"
            if scope == "problem"
            else "RH_POLICY_AGGREGATE_COUNT"
        )
        if size != expected_size:
            raise GateError(f"{table} is not sized by {expected_size}")
        tables[scope] = parse_implementation_table(body, scope, fact_macros)

    profiles: dict[str, tuple[object, ...]] = {}
    for implementations in tables.values():
        for name, implementation in implementations.items():
            profile = str(implementation["profile"])
            signature = (
                tuple(implementation["writes"]),
                tuple(implementation["required_facts"]),
                implementation["evidence_id"],
                implementation["source_pass"],
            )
            if profile in profiles and profiles[profile] != signature:
                raise GateError(
                    f"implementation profile {profile} has inconsistent action/fact/evidence mapping"
                )
            profiles[profile] = signature
    return tables


def compare_implementation_contracts(
    expected: dict[str, dict[str, object]],
    actual: dict[str, dict[str, object]],
    label: str,
) -> None:
    missing = sorted(set(expected) - set(actual))
    unknown = sorted(set(actual) - set(expected))
    if missing:
        raise GateError(f"product is missing audited {label} implementations: {', '.join(missing)}")
    if unknown:
        raise GateError(f"product has unaudited {label} implementations: {', '.join(unknown)}")
    for name in expected:
        expected_writes = expected[name]["writes"]
        actual_writes = actual[name]["writes"]
        if actual_writes != expected_writes:
            raise GateError(
                f"implementation write-family drift for {label} {name}: "
                f"product {actual_writes}, audit {expected_writes}"
            )
        expected_facts = expected[name]["required_facts"]
        actual_facts = actual[name]["required_facts"]
        if actual_facts != expected_facts:
            raise GateError(
                f"implementation required-fact drift for {label} {name}: "
                f"product {actual_facts}, audit {expected_facts}"
            )


def declaration_name_offsets(source: str) -> set[int]:
    return {match.start("name") for match in DECLARATION.finditer(source)}


def call_sites(source: str, symbols: set[str]) -> list[tuple[str, int]]:
    masked = mask_comments_and_literals(source)
    declarations = declaration_name_offsets(masked)
    names = "|".join(sorted((re.escape(name) for name in symbols), key=len, reverse=True))
    call = re.compile(rf"\b(?P<name>{names})\s*\(")
    return [
        (match.group("name"), line_number(masked, match.start("name")))
        for match in call.finditer(masked)
        if match.start("name") not in declarations
    ]


def source_role(path: Path, source: str) -> str | None:
    roles = [match.group("role") for match in ROLE.finditer(source)]
    if len(roles) > 1:
        raise GateError(f"multiple ROOTHEALTH_REPAIR_ROLE declarations in {path}")
    return roles[0] if roles else None


def scan_linked_sources(paths: list[Path]) -> dict[str, int]:
    roles: Counter[str] = Counter()
    violations: list[str] = []
    all_symbols = set(ABSOLUTE_FORBIDDEN_CALLS) | set(TYPED_WAL_ONLY_CALLS)
    for path in paths:
        source = path.read_text(encoding="utf-8")
        # libntfs is a linked parser/runtime dependency, not RootHealth repair
        # authority. Its ordinary mutation API remains present for other
        # ntfsprogs utilities, while RootHealth mounts it FS_NO_REPAIR and all
        # product writes are constrained by the typed device adapter. Audit the
        # RootHealth-owned call graph here; runtime/strace tests separately prove
        # that the upstream library cannot escape that device boundary.
        if "/libntfs/" in path.as_posix():
            continue
        role = source_role(path, source)
        if role:
            roles[role] += 1

        # Merely retaining the forbidden recovery namespace in production source
        # is unsafe: it was previously created before aggregate approval.
        no_comments = strip_comments(source)
        for pattern, description in (
            (r"\bFILENAME_LOST_FOUND\b", "lost+found namespace macro"),
            (r"[\"']lost\+found[\"']", "lost+found namespace literal"),
        ):
            for match in re.finditer(pattern, no_comments):
                violations.append(
                    f"{path}:{line_number(no_comments, match.start())}: forbidden {description}"
                )

        masked = mask_comments_and_literals(source)
        declarations = declaration_name_offsets(masked)
        ask_definitions = [
            offset
            for offset in declarations
            if masked.startswith("ntfs_ask_repair", offset)
        ]
        if ask_definitions and role != "DIAGNOSTIC":
            for offset in ask_definitions:
                violations.append(
                    f"{path}:{line_number(masked, offset)}: ntfs_ask_repair declaration/definition "
                    "outside DIAGNOSTIC adapter"
                )

        for symbol, number in call_sites(source, all_symbols):
            if symbol in ABSOLUTE_FORBIDDEN_CALLS:
                violations.append(
                    f"{path}:{number}: forbidden {ABSOLUTE_FORBIDDEN_CALLS[symbol]} "
                    f"call {symbol}()"
                )
            elif role != "TYPED_WAL_ADAPTER":
                violations.append(
                    f"{path}:{number}: {TYPED_WAL_ONLY_CALLS[symbol]} call {symbol}() "
                    "outside TYPED_WAL_ADAPTER"
                )

    if roles["DIAGNOSTIC"] < 1:
        violations.append("linked closure has no explicitly annotated DIAGNOSTIC adapter")
    if roles["TYPED_WAL_ADAPTER"] < 1:
        violations.append("linked closure has no explicitly annotated TYPED_WAL_ADAPTER")
    if violations:
        raise GateError("linked repair hazard closure failed:\n" + "\n".join(violations))
    return {
        "linked_translation_units": len(paths),
        "diagnostic_adapters": roles["DIAGNOSTIC"],
        "typed_wal_adapters": roles["TYPED_WAL_ADAPTER"],
        "raw_ask_repair_calls": 0,
        "uncontained_hazard_calls": 0,
    }


def run_gate(
    audit: dict[str, Any], policy_source: str, engine_root: Path, manifest: Path
) -> dict[str, int]:
    expected_problems = audit_entries(audit, "problems", "code")
    expected_aggregates = audit_entries(audit, "aggregates", "id")
    actual_problems = policy_entries(policy_source, PROBLEM_POLICY, "problem")
    actual_aggregates = policy_entries(policy_source, AGGREGATE_POLICY, "aggregate")
    compare_entries(expected_problems, actual_problems, "problem")
    compare_entries(expected_aggregates, actual_aggregates, "aggregate")
    paths = linked_sources(engine_root, manifest)
    known_facts = policy_fact_enum(engine_root)
    expected_problem_implementations = audit_implementation_contracts(
        audit, "problems", "code", known_facts
    )
    expected_aggregate_implementations = audit_implementation_contracts(
        audit, "aggregates", "id", known_facts
    )
    implementations = product_implementations(engine_root, paths, known_facts)
    compare_implementation_contracts(
        expected_problem_implementations,
        implementations["problem"],
        "problem",
    )
    compare_implementation_contracts(
        expected_aggregate_implementations,
        implementations["aggregate"],
        "aggregate",
    )
    closure = scan_linked_sources(paths)
    implemented_actions = sum(
        len(implementation["writes"])
        for table in implementations.values()
        for implementation in table.values()
    )
    implemented_facts = sum(
        len(implementation["required_facts"])
        for table in implementations.values()
        for implementation in table.values()
    )
    return {
        "problem_decisions": len(expected_problems),
        "aggregate_decisions": len(expected_aggregates),
        "implemented_problems": len(implementations["problem"]),
        "implemented_aggregates": len(implementations["aggregate"]),
        "implemented_action_bindings": implemented_actions,
        "implemented_fact_bindings": implemented_facts,
        **closure,
    }


def expect_failure(action: Any, needle: str) -> None:
    try:
        action()
    except GateError as error:
        if needle not in str(error):
            raise GateError(
                f"self-test expected {needle!r}, received {str(error)!r}"
            ) from error
    else:
        raise GateError(f"self-test mutation {needle!r} unexpectedly passed")


def self_test() -> None:
    audit = {
        "format": 1,
        "upstream": {"commit": PINNED_COMMIT},
        "problems": [
            {
                "code": "PR_PRE_SCAN_MFT",
                "decision": "CONDITIONAL",
                "writes": ["CLUSTER_BITMAP"],
                "required_facts": ["RH_FACT_IDENTITY_BOUND"],
            },
            {"code": "PR_RESET_LOG_FILE", "decision": "DENY", "writes": []},
        ],
        "aggregates": [
            {
                "id": "ORPHANS",
                "decision": "CONDITIONAL",
                "writes": ["INDEX_BITMAP"],
                "required_facts": [
                    "RH_FACT_IDENTITY_BOUND",
                    "RH_FACT_FINAL_OVERLAY_VALID",
                ],
            },
            {
                "id": "UNOPENABLE_MFT_BITMAP",
                "decision": "DENY",
                "writes": [],
            },
        ],
    }
    policy = """
ROOTHEALTH_PROBLEM_POLICY(PR_PRE_SCAN_MFT, CONDITIONAL)
ROOTHEALTH_PROBLEM_POLICY(PR_RESET_LOG_FILE, DENY)
ROOTHEALTH_AGGREGATE_POLICY(ORPHANS, CONDITIONAL)
ROOTHEALTH_AGGREGATE_POLICY(UNOPENABLE_MFT_BITMAP, DENY)
"""
    with tempfile.TemporaryDirectory(prefix="roothealth-policy-gate-") as directory:
        root = Path(directory)
        source_root = root / "src"
        source_root.mkdir()
        manifest = root / "linked.units"
        diagnostic = source_root / "diagnostic.c"
        typed = source_root / "typed-wal.c"
        engine = source_root / "engine.c"
        header = source_root / "roothealth_policy.h"
        header.write_text(
            "enum rh_policy_fact {\n"
            " RH_FACT_IDENTITY_BOUND = 0,\n"
            " RH_FACT_FINAL_OVERLAY_VALID,\n"
            " RH_POLICY_FACT_COUNT\n"
            "};\n",
            encoding="utf-8",
        )
        diagnostic.write_text(
            "/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */\n"
            "#define RH_CLUSTER_FACTS (RH_FACT_MASK(RH_FACT_IDENTITY_BOUND))\n"
            "#define RH_INDEX_FACTS (RH_FACT_MASK(RH_FACT_IDENTITY_BOUND) | "
            "RH_FACT_MASK(RH_FACT_FINAL_OVERLAY_VALID))\n"
            "static const struct rh_policy_implementation\n"
            "rh_problem_implementations[RH_PROBLEM_ARRAY_SIZE] = {\n"
            " [PR_PRE_SCAN_MFT] = RH_IMPLEMENTATION(\n"
            "  RH_POLICY_PROFILE_CLUSTER_BITMAP, \"cluster-bitmap-v1\",\n"
            "  \"bitmap-census\", RH_WRITE_BITMAP_CLUSTER, RH_CLUSTER_FACTS),\n"
            "};\n"
            "static const struct rh_policy_implementation\n"
            "rh_aggregate_implementations[RH_POLICY_AGGREGATE_COUNT] = {\n"
            " [RH_POLICY_AGGREGATE_ORPHANS] = RH_IMPLEMENTATION(\n"
            "  RH_POLICY_PROFILE_INDEX_BITMAP, \"index-bitmap-v1\",\n"
            "  \"i30-census\", RH_WRITE_INDEX_BITMAP, RH_INDEX_FACTS),\n"
            "};\n"
            "BOOL ntfs_ask_repair(const void *v) { return 0; }\n",
            encoding="utf-8",
        )
        typed.write_text(
            "/* ROOTHEALTH_REPAIR_ROLE(TYPED_WAL_ADAPTER) */\n"
            "int typed_write(void *a) { return ntfs_attr_pwrite(a, 0, 1, a); }\n",
            encoding="utf-8",
        )
        engine.write_text("int diagnose(void) { return 0; }\n", encoding="utf-8")
        manifest.write_text(
            "src/diagnostic.c\nsrc/typed-wal.c\nsrc/engine.c\n", encoding="utf-8"
        )

        result = run_gate(audit, policy, root, manifest)
        if (
            result["problem_decisions"] != 2
            or result["implemented_problems"] != 1
            or result["implemented_aggregates"] != 1
            or result["implemented_action_bindings"] != 2
            or result["implemented_fact_bindings"] != 3
            or result["uncontained_hazard_calls"] != 0
        ):
            raise GateError("self-test clean implementation did not pass")

        # Exercise the real audited cardinality and every audited decision, not
        # only the small mutation fixture above.
        full_audit_path = Path(__file__).with_name("repair-policy-audit.json")
        full_audit = json.loads(full_audit_path.read_text(encoding="utf-8"))
        full_policy = "\n".join(
            [
                f"ROOTHEALTH_PROBLEM_POLICY({item['code']}, {item['decision']})"
                for item in full_audit["problems"]
            ]
            + [
                f"ROOTHEALTH_AGGREGATE_POLICY({item['id']}, {item['decision']})"
                for item in full_audit["aggregates"]
            ]
        )
        full_expected_problems = audit_entries(full_audit, "problems", "code")
        full_expected_aggregates = audit_entries(full_audit, "aggregates", "id")
        compare_entries(
            full_expected_problems,
            policy_entries(full_policy, PROBLEM_POLICY, "problem"),
            "problem",
        )
        compare_entries(
            full_expected_aggregates,
            policy_entries(full_policy, AGGREGATE_POLICY, "aggregate"),
            "aggregate",
        )
        full_contract_names = {
            item.get("code", item.get("id"))
            for field in ("problems", "aggregates")
            for item in full_audit[field]
            if item.get("required_facts") is not None
        }
        if (
            len(full_expected_problems) != 98
            or len(full_expected_aggregates) != 14
            or len(full_contract_names) != 6
        ):
            raise GateError("self-test did not exercise all 98/14 audited decisions")

        drifted = policy.replace(
            "ROOTHEALTH_PROBLEM_POLICY(PR_PRE_SCAN_MFT, CONDITIONAL)",
            "ROOTHEALTH_PROBLEM_POLICY(PR_PRE_SCAN_MFT, DENY)",
        )
        expect_failure(
            lambda: run_gate(audit, drifted, root, manifest), "policy decision drift"
        )

        clean_diagnostic = diagnostic.read_text(encoding="utf-8")
        diagnostic.write_text(
            clean_diagnostic.replace(
                "RH_WRITE_BITMAP_CLUSTER, RH_CLUSTER_FACTS",
                "RH_WRITE_BITMAP_MFT, RH_CLUSTER_FACTS",
            ),
            encoding="utf-8",
        )
        expect_failure(
            lambda: run_gate(audit, policy, root, manifest),
            "implementation write-family drift",
        )

        diagnostic.write_text(
            clean_diagnostic.replace(
                "RH_FACT_MASK(RH_FACT_IDENTITY_BOUND) | "
                "RH_FACT_MASK(RH_FACT_FINAL_OVERLAY_VALID)",
                "RH_FACT_MASK(RH_FACT_IDENTITY_BOUND)",
            ),
            encoding="utf-8",
        )
        expect_failure(
            lambda: run_gate(audit, policy, root, manifest),
            "implementation required-fact drift",
        )

        diagnostic.write_text(
            clean_diagnostic.replace(
                "RH_WRITE_BITMAP_CLUSTER, RH_CLUSTER_FACTS",
                "RH_WRITE_BITMAP_CLUSTRE, RH_CLUSTER_FACTS",
            ),
            encoding="utf-8",
        )
        expect_failure(
            lambda: run_gate(audit, policy, root, manifest), "unknown action kind"
        )

        duplicate_writes = deepcopy(audit)
        duplicate_writes["problems"][0]["writes"] = [
            "CLUSTER_BITMAP",
            "CLUSTER_BITMAP",
        ]
        diagnostic.write_text(clean_diagnostic, encoding="utf-8")
        expect_failure(
            lambda: run_gate(duplicate_writes, policy, root, manifest),
            "duplicate family",
        )

        unknown_fact = deepcopy(audit)
        unknown_fact["problems"][0]["required_facts"] = ["RH_FACT_TYPO"]
        expect_failure(
            lambda: run_gate(unknown_fact, policy, root, manifest),
            "unknown to the product enum",
        )

        engine.write_text(
            "int raw_prompt(void *v) { return ntfs_ask_repair(v); }\n",
            encoding="utf-8",
        )
        expect_failure(
            lambda: run_gate(audit, policy, root, manifest),
            "interactive/raw repair decision",
        )

        engine.write_text(
            "int raw_clear(void *b) { return ntfs_bitmap_clear_bit(b, 1); }\n",
            encoding="utf-8",
        )
        expect_failure(
            lambda: run_gate(audit, policy, root, manifest),
            "outside TYPED_WAL_ADAPTER",
        )


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        try:
            self_test()
            print(
                "roothealth policy implementation self-test passed: "
                "decision_drift_rejected=true raw_ask_rejected=true "
                "uncontained_hazard_rejected=true exact_actions=true "
                "exact_facts=true implementation_names_and_counts=true"
            )
            return 0
        except (GateError, OSError, UnicodeError, json.JSONDecodeError) as error:
            print(f"roothealth policy implementation self-test failed: {error}", file=sys.stderr)
            return 1

    parser = argparse.ArgumentParser()
    parser.add_argument("audit", type=Path)
    parser.add_argument("policy_source", type=Path)
    parser.add_argument("engine_source", type=Path)
    parser.add_argument("translation_unit_manifest", type=Path)
    args = parser.parse_args()
    try:
        self_test()
        audit = json.loads(args.audit.read_text(encoding="utf-8"))
        policy = args.policy_source.read_text(encoding="utf-8")
        policy_def = args.policy_source.with_name("roothealth_problem_policy.def")
        if policy_def.is_file():
            policy += "\n" + policy_def.read_text(encoding="utf-8")
        result = run_gate(audit, policy, args.engine_source, args.translation_unit_manifest)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (GateError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"roothealth policy implementation gate failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
