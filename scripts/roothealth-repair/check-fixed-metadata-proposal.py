#!/usr/bin/env python3
"""Exact-source gate for the fail-closed $UpCase/$AttrDef proposal."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE / "fixed-metadata-current-proposal-qualification.json"
EXPECTED_BLOCKERS = {
    "RHCOV3_FIXED_AUTHORITY_PUBLISHER_NOT_MERGED",
    "ID20_ID21_VIRTUAL_PREIMAGE_FULL_LEDGER_REDERIVATION_NOT_MERGED",
}
EXPECTED_PATCH_PATHS = [
    "FIXED-METADATA-SLICE.md",
    "src/roothealth_fixed_metadata.c",
    "src/roothealth_fixed_metadata.h",
    "src/roothealth_overlay.c",
    "src/roothealth_overlay.h",
    "tests/roothealth_fixed_metadata_mutate.c",
    "tests/roothealth_fixed_metadata_plan.c",
    "tests/roothealth_fixed_metadata_qualification.sh",
]


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


def patch_paths(path: Path) -> list[str]:
    return [
        left if left == right else f"{left}->{right}"
        for left, right in re.findall(
            r"^diff --git a/([^ ]+) b/([^\n]+)$",
            path.read_text(encoding="utf-8"), re.M,
        )
    ]


def source_policy_errors(fixed_c: str, fixed_h: str, policy_c: str,
                         wal_c: str) -> list[str]:
    errors: list[str] = []
    guarded_c = re.search(
        r"#ifdef ROOTHEALTH_REPAIR_TESTING\s+"
        r"int rh_fixed_metadata_authority_seal\(.*?\n}\s*#endif",
        fixed_c, re.S,
    )
    guarded_h = re.search(
        r"#ifdef ROOTHEALTH_REPAIR_TESTING\s+.*?"
        r"rh_fixed_metadata_authority_seal\(.*?;\s*#endif",
        fixed_h, re.S,
    )
    if not guarded_c or not guarded_h:
        errors.append("generic authority sealer escaped the test-only guard")
    fixed_without_test_sealer = fixed_c
    if guarded_c:
        fixed_without_test_sealer = fixed_c.replace(guarded_c.group(0), "")
    if "rh_fixed_metadata_authority_seal(" in fixed_without_test_sealer:
        errors.append("production source calls or exports the generic sealer")
    required_fixed = (
        "int rh_fixed_metadata_authority_build(",
        "rh_coverage_is_clean(&normalized)",
        "rh_raw_mft_census",
        "rh_namespace_census",
        "rh_cluster_bitmap_census",
        "namespace_census->identity != RH_T1OS_IDENTITY_MATCH",
        "namespace_census->i30_bitmap_changes",
        "cluster_census->ownership_exact",
        "rh_writer_range_excluded",
        "writer->raw_wal_allowed_count",
        "raw->census_hash",
        "target->mapping_hash",
        "cluster_census->allocation_hash",
        "rh_fixed_metadata_attrdef_type_census",
        "slice_count != 1U",
        "RH_UPCASE_CANONICAL_SIZE",
        "RH_ATTRDEF_CANONICAL_SIZE",
    )
    for token in required_fixed:
        if token not in fixed_c and token not in fixed_h:
            errors.append(f"required fixed-metadata predicate missing: {token}")
    if "cached_file_name_differences" in fixed_c:
        errors.append("cached FILE_NAME value drift must not masquerade as collation authority")
    if "PR_UPCASE_CORRUPTED" in policy_c or "PR_ATTRDEF_CORRUPTED" in policy_c:
        errors.append("central repair policy is no longer closed for fixed metadata")
    if wal_c.count("rh_wal_register_action_verifier(") != 1:
        errors.append("a product action-verifier registration call appeared")
    if "RH_WRITE_UPCASE_DATA" in wal_c or "RH_WRITE_ATTRDEF_DATA" in wal_c:
        errors.append("ID20/21 appeared in WAL without a qualified rederiver")
    builtin_match = re.search(
        r"static const enum rh_write_kind kinds\[\]\s*=\s*\{(.*?)\};",
        wal_c, re.S,
    )
    if not builtin_match:
        errors.append("builtin action-verifier table is missing")
    else:
        builtins = set(re.findall(r"RH_WRITE_[A-Z0-9_]+", builtin_match.group(1)))
        if builtins != {
            "RH_WRITE_BITMAP_CLUSTER", "RH_WRITE_VOLUME_DIRTY_SET",
            "RH_WRITE_VOLUME_DIRTY_CLEAR",
        }:
            errors.append("builtin action-verifier table drift")
    return errors


def validate(tree: Path, baseline: Path | None, manifest: dict) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if manifest.get("status") != "PROPOSED_FAIL_CLOSED":
        errors.append("status must be PROPOSED_FAIL_CLOSED")
    if manifest.get("verdict") != "PASS_SAFE_CLOSED_FIXED_METADATA_PROPOSAL":
        errors.append("proposal verdict drift")
    if manifest.get("release_qualified") is not False:
        errors.append("proposal must not claim release qualification")
    if manifest.get("repair_enabled") is not False:
        errors.append("fixed-metadata repair must remain disabled")
    if manifest.get("registered_wal_action_ids") != [23, 24, 25]:
        errors.append("registered WAL action set drift")
    blocker_ids = {item.get("id") for item in manifest.get("blockers", [])}
    if blocker_ids != EXPECTED_BLOCKERS:
        errors.append("exact blocker set drift")

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
    checker = manifest.get("checker", {})
    checker_path = HERE / checker.get("file", "")
    if checker_path.name != "check-fixed-metadata-proposal.py" or \
            not checker_path.is_file() or \
            digest(checker_path) != checker.get("sha256"):
        errors.append("proposal checker hash drift")

    patch_info = manifest.get("patch", {})
    patch = HERE / patch_info.get("file", "")
    if not patch.is_file():
        errors.append("mechanical proposal patch is missing")
    else:
        if digest(patch) != patch_info.get("sha256"):
            errors.append("mechanical patch hash drift")
        if patch.stat().st_size != patch_info.get("bytes"):
            errors.append("mechanical patch byte-count drift")
        paths = patch_paths(patch)
        if paths != EXPECTED_PATCH_PATHS or paths != patch_info.get("paths"):
            errors.append("mechanical patch path set/order drift")
        if baseline is not None:
            completed = subprocess.run(
                ["git", "apply", "--check", str(patch)], cwd=baseline,
                text=True, capture_output=True, check=False,
            )
            if completed.returncode:
                errors.append("mechanical patch no longer clean-applies")

    required_paths = {
        "src/roothealth_fixed_metadata.c", "src/roothealth_fixed_metadata.h",
        "src/roothealth_overlay.c", "src/roothealth_overlay.h",
    }
    if required_paths.issubset({p for p in manifest.get("result_sources", {})}):
        fixed_c = (tree / "src/roothealth_fixed_metadata.c").read_text()
        fixed_h = (tree / "src/roothealth_fixed_metadata.h").read_text()
        policy_c = (tree / "src/roothealth_policy.c").read_text()
        wal_c = (tree / "src/roothealth_wal.c").read_text()
        errors.extend(source_policy_errors(fixed_c, fixed_h, policy_c, wal_c))

    batch = manifest.get("bounded_batch", {})
    if batch != {
        "max_actions": 2,
        "upcase_action_id": 20,
        "upcase_bytes": 131072,
        "attrdef_action_id": 21,
        "attrdef_bytes": 2560,
        "max_target_bytes": 133632,
        "wal_transactions": 1,
        "requires_batching": False,
        "partial_commit_allowed": False,
    }:
        errors.append("bounded one-transaction proof drift")
    hardware = manifest.get("hardware_release_evidence", {})
    if hardware.get("result") != "PASS" or hardware.get("source_writes") != 0 or \
            hardware.get("disk_sha256_before") != hardware.get("disk_sha256_after") or \
            hardware.get("partition", {}).get("first_lba") != 1050624 or \
            hardware.get("partition", {}).get("last_lba") != 20969471 or \
            hardware.get("partition", {}).get("bytes") != 10198450176 or \
            hardware.get("partition", {}).get("sha256") != \
            "f89363dacb77c1227d74dc82e180238b7a4be10767ccb86ab5376bf4ff6a3685":
        errors.append("hardware release evidence drift")
    return errors


def run_core_gates(tree: Path, cc: str) -> dict[str, object]:
    qualification = run(
        ["bash", tree / "tests/roothealth_fixed_metadata_qualification.sh"],
        "fixed-metadata qualification", cwd=tree,
    )
    if "recovery_negative_cases=42" not in qualification or \
            "asan_ubsan=1 passed=1" not in qualification:
        raise RuntimeError("fixed-metadata qualification count drift")
    with tempfile.TemporaryDirectory(prefix="rh-fixed-proposal-gate.") as tmp:
        work = Path(tmp)
        includes = [
            f"-I{tree}", f"-I{tree / 'include'}", f"-I{tree / 'src'}",
            f"-I{tree / 'libntfs'}",
        ]
        strict = [
            cc, "-std=gnu11", "-DHAVE_CONFIG_H", "-D_GNU_SOURCE",
            "-D_FORTIFY_SOURCE=3", "-Wall", "-Wextra", "-Werror",
            "-Wformat=2", "-Wshadow", "-Wno-address-of-packed-member",
            "-fno-common", *includes,
        ]
        fixed_object = work / "fixed.production.o"
        run(strict + ["-c", tree / "src/roothealth_fixed_metadata.c", "-o",
                      fixed_object], "strict production fixed-metadata compile")
        run(strict + ["-fanalyzer", "-c",
                      tree / "src/roothealth_fixed_metadata.c", "-o",
                      work / "fixed.analyzer.o"], "fixed-metadata fanalyzer")
        symbols = run(["nm", "-g", fixed_object], "inspect production symbols")
        if "rh_fixed_metadata_authority_seal" in symbols:
            raise RuntimeError("test-only generic sealer exported in production object")

        dependencies = [
            tree / "src/roothealth_bitmap.o", tree / "src/roothealth_overlay.o",
            tree / "src/roothealth_dirty.o", tree / "src/roothealth_policy.o",
            tree / "libntfs/.libs/libntfs.a",
        ]
        for dependency in dependencies:
            if not dependency.is_file():
                raise RuntimeError(f"configured dependency missing: {dependency}")
        sanitizer = strict + [
            "-DROOTHEALTH_WAL_TEST_HOOKS", "-ffunction-sections",
            "-fdata-sections", "-fsanitize=address,undefined",
            "-fno-omit-frame-pointer",
        ]
        wal_object = work / "wal.o"
        write_object = work / "write.o"
        run(sanitizer + ["-c", tree / "src/roothealth_wal.c", "-o", wal_object],
            "sanitized WAL compile")
        run(sanitizer + ["-c", tree / "src/roothealth_write.c", "-o",
                         write_object], "sanitized writer compile")
        selftest = work / "wal-closed-selftest"
        run(sanitizer + [
            HERE / "fixed_metadata_wal_closed_selftest.c", wal_object,
            write_object, *dependencies, "-Wl,--gc-sections", "-o", selftest,
        ], "link WAL closed-state self-test")
        environment = os.environ.copy()
        environment["ASAN_OPTIONS"] = "detect_leaks=1:abort_on_error=1"
        environment["UBSAN_OPTIONS"] = "halt_on_error=1"
        wal_output = run([selftest], "WAL closed-state self-test", env=environment)
        if "PASS (3/3 crash states)" not in wal_output:
            raise RuntimeError("WAL closed-state matrix count drift")
    return {
        "canonical_artifacts": 2,
        "clean_noops": 2,
        "corrupt_plans": 5,
        "recovery_negative_cases": 42,
        "strict_werror": True,
        "fanalyzer": True,
        "asan_ubsan": True,
        "wal_closed_crash_states": 3,
    }


def run_self_tests(tree: Path, baseline: Path | None, manifest: dict) -> None:
    drift = copy.deepcopy(manifest)
    first = next(iter(drift["result_sources"]))
    drift["result_sources"][first] = "0" * 64
    if not any("result source hash drift" in error
               for error in validate(tree, baseline, drift)):
        raise RuntimeError("self-test: source decision drift was accepted")
    fixed_c = (tree / "src/roothealth_fixed_metadata.c").read_text()
    fixed_h = (tree / "src/roothealth_fixed_metadata.h").read_text()
    policy_c = (tree / "src/roothealth_policy.c").read_text()
    wal_c = (tree / "src/roothealth_wal.c").read_text()
    authority_bypass = fixed_c.replace(
        "#ifdef ROOTHEALTH_REPAIR_TESTING\nint rh_fixed_metadata_authority_seal(",
        "int rh_fixed_metadata_authority_seal(", 1,
    ).replace("\n#endif\n\nint rh_fixed_metadata_authority_valid", 
              "\n\nint rh_fixed_metadata_authority_valid", 1)
    if not any("generic authority sealer" in error
               for error in source_policy_errors(
                   authority_bypass, fixed_h, policy_c, wal_c)):
        raise RuntimeError("self-test: production generic sealer bypass was accepted")
    registration = wal_c + "\n/* mutation */ rh_wal_register_action_verifier(wal, 20, verify);\n"
    if not any("registration call" in error
               for error in source_policy_errors(
                   fixed_c, fixed_h, policy_c, registration)):
        raise RuntimeError("self-test: unqualified ID20 registration was accepted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--run-gates", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--hardware-disk", type=Path)
    parser.add_argument("--hardware-partition-copy", type=Path)
    parser.add_argument("--cc", default=os.environ.get("CC", "gcc"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    tree = args.tree.resolve()
    baseline = args.baseline.resolve() if args.baseline else None
    errors = validate(tree, baseline, manifest)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=os.sys.stderr)
        return 1
    if args.self_test:
        run_self_tests(tree, baseline, manifest)
    core = run_core_gates(tree, args.cc) if args.run_gates else None
    hardware = None
    if args.hardware_disk:
        command: list[str | Path] = [
            os.sys.executable, "-B", HERE / "check-fixed-metadata-hardware-release.py",
            "--tree", tree, "--disk", args.hardware_disk, "--cc", args.cc,
        ]
        if args.hardware_partition_copy:
            command += ["--partition-copy", args.hardware_partition_copy]
        hardware = json.loads(run(command, "hardware release gate"))
    print(json.dumps({
        "status": "PROPOSED_FAIL_CLOSED",
        "release_qualified": False,
        "repair_enabled": False,
        "findings": 0,
        "blockers": sorted(EXPECTED_BLOCKERS),
        "core_gates": core,
        "hardware_gate": hardware,
        "result": "PASS",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
