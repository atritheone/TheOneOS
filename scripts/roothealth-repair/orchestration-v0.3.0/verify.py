#!/usr/bin/env python3
"""Read-only verifier for the frozen roothealth orchestration proposal."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys


HEX64 = re.compile(r"^[0-9a-f]{64}$")
PATCH_HEADER = re.compile(r"^diff --git a/([^\n]+) b/([^\n]+)$", re.MULTILINE)


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"roothealth orchestration package invalid: {message}")


def package_manifest(root: pathlib.Path) -> None:
    manifest = root / "PACKAGE.sha256"
    lines = manifest.read_text(encoding="ascii").splitlines()
    expected_names = sorted(
        path.name
        for path in root.iterdir()
        if path.is_file() and path.name != manifest.name
    )
    observed_names: list[str] = []
    for line in lines:
        if "  " not in line:
            fail("malformed PACKAGE.sha256 line")
        digest, name = line.split("  ", 1)
        if not HEX64.fullmatch(digest) or pathlib.PurePath(name).name != name:
            fail("unsafe or malformed package manifest entry")
        path = root / name
        if not path.is_file() or sha256(path) != digest:
            fail(f"package hash mismatch: {name}")
        observed_names.append(name)
    if observed_names != expected_names:
        fail("PACKAGE.sha256 is not sorted, unique, and complete")


def linked_manifests(root: pathlib.Path) -> None:
    sources = (root / "roothealth-linked-inputs.manifest").read_text(
        encoding="ascii"
    ).splitlines()
    if sources[:1] != ["# roothealth-linked-inputs-v1 complete-link-inputs=true"]:
        fail("linked-source manifest header")
    if len(sources) != 50 or sources[1:] != sorted(set(sources[1:])):
        fail("linked-source closure is not exactly 49 sorted unique entries")
    if any(not value.endswith(".c") or value.startswith(("/", "../")) for value in sources[1:]):
        fail("linked-source manifest contains a non-C or unsafe path")

    objects = (root / "roothealth-linked-objects.tsv").read_text(
        encoding="ascii"
    ).splitlines()
    if objects[:2] != [
        "# roothealth-linked-objects-v1 complete-link-inputs=true",
        "source\tsource_sha256\tobject\tobject_sha256",
    ] or len(objects) != 51:
        fail("linked-object manifest shape")
    object_sources: list[str] = []
    for line in objects[2:]:
        fields = line.split("\t")
        if len(fields) != 4 or not HEX64.fullmatch(fields[1]) or not HEX64.fullmatch(fields[3]):
            fail("linked-object manifest record")
        object_sources.append(fields[0])
    if object_sources != sources[1:]:
        fail("source/object closure disagreement")


def complete_source_manifest(root: pathlib.Path) -> None:
    lines = (root / "complete-source.sha256").read_text(encoding="ascii").splitlines()
    if len(lines) != 524:
        fail("complete-source manifest must contain 524 records")
    paths: list[str] = []
    for line in lines:
        if "  " not in line:
            fail("malformed complete-source record")
        digest, name = line.split("  ", 1)
        if not HEX64.fullmatch(digest) or not name.startswith("./"):
            fail("malformed complete-source hash/path")
        paths.append(name)
    if paths != sorted(set(paths)):
        fail("complete-source records are not sorted and unique")


def proposal(root: pathlib.Path, qualification: dict[str, object]) -> None:
    if qualification.get("status") != "PROPOSED_FAIL_CLOSED":
        fail("status is not PROPOSED_FAIL_CLOSED")
    safety = qualification.get("safety")
    if not isinstance(safety, dict) or safety != {
        "production_binary_in_package": False,
        "production_source_integrated": False,
        "target_commit_primitive_reachable": False,
        "repair_success_claimed": False,
        "unsupported_repairs_exit_fail_closed": True,
    }:
        fail("safety posture drift")
    artifacts = qualification.get("artifacts")
    if not isinstance(artifacts, dict):
        fail("missing artifact hashes")
    for name, expected in artifacts.items():
        if not isinstance(name, str) or not isinstance(expected, str) or not HEX64.fullmatch(expected):
            fail("malformed qualification artifact hash")
        path = root / name
        if not path.is_file() or sha256(path) != expected:
            fail(f"qualification artifact mismatch: {name}")

    patch = (root / "roothealth-v0.3.0-proposal.patch").read_text(
        encoding="utf-8"
    )
    changed = qualification.get("changed_files")
    if not isinstance(changed, dict):
        fail("missing changed-file map")
    patch_paths = PATCH_HEADER.findall(patch)
    if any(left != right for left, right in patch_paths):
        fail("patch renames are forbidden")
    if sorted(left for left, _ in patch_paths) != sorted(changed):
        fail("patch path set disagrees with qualification")
    added_lines = [
        line[1:]
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    if "GIT binary patch" in patch or any(
        "rh_writer_commit(" in line for line in added_lines
    ):
        fail("proposal contains binary content or adds a target commit call")

    for path in root.iterdir():
        if path.is_file() and path.read_bytes()[:4] == b"\x7fELF":
            fail(f"production binary present: {path.name}")


def external_hash(path: pathlib.Path | None, expected: str, label: str) -> None:
    if path is not None and sha256(path.resolve(strict=True)) != expected:
        fail(f"{label} hash mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=pathlib.Path)
    parser.add_argument("--baseline-manifest", type=pathlib.Path)
    parser.add_argument("--validator", type=pathlib.Path)
    parser.add_argument("--contract", type=pathlib.Path)
    args = parser.parse_args()

    root = pathlib.Path(__file__).resolve().parent
    qualification = json.loads((root / "qualification.json").read_text(encoding="utf-8"))
    package_manifest(root)
    linked_manifests(root)
    complete_source_manifest(root)
    proposal(root, qualification)

    baseline = qualification["baseline"]
    workspace = qualification["workspace_inputs"]
    external_hash(args.baseline_manifest, baseline["manifest_sha256"], "baseline manifest")
    external_hash(
        args.validator,
        workspace["scripts/roothealth-repair/validate-report.py"],
        "validator",
    )
    external_hash(
        args.contract,
        workspace["source/entry/roothealth/REPAIR-CONTRACT.md"],
        "contract",
    )
    if args.baseline is not None:
        baseline_path = args.baseline.resolve(strict=True)
        result = subprocess.run(
            [
                "git",
                "apply",
                "--check",
                "--whitespace=error-all",
                str(root / "roothealth-v0.3.0-proposal.patch"),
            ],
            cwd=baseline_path,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode:
            fail(f"patch does not apply to baseline: {result.stderr.strip()}")
    print("roothealth orchestration proposal verified: PROPOSED_FAIL_CLOSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
