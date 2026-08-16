#!/usr/bin/env python3
"""Statically verify the exact Python scripts eligible for a T1OS LSM profile."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys


EXPECTED_SHEBANG = b'#!"/the one/software/python/bin/python" -B\n'
POLICY_KEYS = {"format", "owner", "group", "install_mode", "shebang", "entries"}
ENTRY_KEYS = {"root", "path", "destination"}
LSM_PROFILE_FUNCTIONS = (
    "t1os_service_launch",
    "t1os_catalogue_launch",
    "t1os_window_launch",
    "t1os_transition_allowed",
)


class ValidationFailure(RuntimeError):
    pass


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValidationFailure(f"could not read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValidationFailure(f"expected a JSON object in {path}")
    return value


def function_body(source: str, name: str) -> str:
    match = re.search(rf"\b{name}\s*\([^;]*?\)\s*\{{", source, re.DOTALL)
    if match is None:
        raise ValidationFailure(f"active LSM function is missing: {name}")
    opening = source.find("{", match.start())
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1:index]
    raise ValidationFailure(f"active LSM function is unterminated: {name}")


def active_lsm_script_paths(lsm_path: Path) -> set[str]:
    try:
        source = lsm_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValidationFailure(f"could not read active LSM {lsm_path}: {error}") from error
    macros: dict[str, str] = {}
    for name, value in re.findall(
        r"^\s*#define\s+(T1OS_[A-Z0-9_]+)\s+(\"[^\"\n]+\"|T1OS_[A-Z0-9_]+)\s*$",
        source,
        re.MULTILINE,
    ):
        macros[name] = value[1:-1] if value.startswith('"') else value

    def resolve(name: str, seen: set[str] | None = None) -> str:
        seen = set() if seen is None else set(seen)
        if name in seen or name not in macros:
            raise ValidationFailure(f"active LSM script macro is unresolved: {name}")
        seen.add(name)
        value = macros[name]
        return resolve(value, seen) if value.startswith("T1OS_") else value

    symbols: set[str] = set()
    for name in LSM_PROFILE_FUNCTIONS:
        symbols.update(re.findall(r"\bT1OS_[A-Z0-9_]+_SCRIPT\b", function_body(source, name)))
    if not symbols:
        raise ValidationFailure("active LSM exposes no profiled Python script symbols")
    return {resolve(symbol) for symbol in symbols}


def load_policy(repo: Path) -> tuple[dict, dict[str, dict], set[tuple[str, str]]]:
    config_path = repo / "source" / "python" / "build" / "runtime.json"
    config = read_json(config_path)
    roots = {
        item.get("name"): item
        for item in config.get("protected_external_roots", [])
        if isinstance(item, dict)
    }
    policy = config.get("profiled_python_entrypoints")
    if not isinstance(policy, dict) or set(policy) != POLICY_KEYS:
        raise ValidationFailure("profiled Python policy has an unexpected schema")
    if (
        policy["format"] != 1
        or policy["owner"] != 0
        or policy["group"] != 0
        or policy["install_mode"] != "0555"
        or policy["shebang"] != EXPECTED_SHEBANG.decode("ascii")
        or not isinstance(policy["entries"], list)
        or not policy["entries"]
    ):
        raise ValidationFailure("profiled Python policy is not the root-owned 0555 contract")
    identities: set[tuple[str, str]] = set()
    destinations: set[str] = set()
    ordered: list[str] = []
    for entry in policy["entries"]:
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise ValidationFailure("profiled Python entrypoint has an unexpected schema")
        root_name = entry["root"]
        relative = entry["path"]
        destination = entry["destination"]
        if root_name not in roots or not all(
            isinstance(value, str) for value in (relative, destination)
        ):
            raise ValidationFailure("profiled Python entrypoint identity is malformed")
        parsed = PurePosixPath(relative)
        if (
            parsed.is_absolute()
            or parsed.as_posix() != relative
            or relative == "."
            or ".." in parsed.parts
            or "\\" in relative
            or any(character in relative for character in "\x00\t\r\n")
            or parsed.suffix != ".py"
        ):
            raise ValidationFailure(f"unsafe profiled Python path: {relative!r}")
        expected = roots[root_name]["destination"].rstrip("/") + "/" + relative
        if destination != expected:
            raise ValidationFailure(f"non-canonical profiled destination: {destination}")
        identity = (root_name, relative)
        if identity in identities or destination in destinations:
            raise ValidationFailure(f"duplicate profiled Python entrypoint: {destination}")
        source_path = repo / roots[root_name]["source"] / Path(*parsed.parts)
        try:
            source_mode = source_path.lstat().st_mode
            source_bytes = source_path.read_bytes()
        except OSError as error:
            raise ValidationFailure(f"could not inspect {source_path}: {error}") from error
        if source_path.is_symlink() or not stat.S_ISREG(source_mode):
            raise ValidationFailure(f"profiled source is not a regular file: {source_path}")
        if source_bytes.startswith(b"\xef\xbb\xbf") or not source_bytes.startswith(EXPECTED_SHEBANG):
            raise ValidationFailure(
                f"profiled source lacks the exact byte-0 LF shebang: {source_path}"
            )
        identities.add(identity)
        destinations.add(destination)
        ordered.append(destination)
    if ordered != sorted(ordered):
        raise ValidationFailure("profiled Python inventory is not canonically ordered")
    lsm_paths = active_lsm_script_paths(
        repo / "source" / "entry" / "kernel" / "t1os_lsm.c"
    )
    if destinations != lsm_paths:
        missing = sorted(lsm_paths - destinations)
        extra = sorted(destinations - lsm_paths)
        raise ValidationFailure(
            f"profiled Python inventory differs from the active LSM; missing={missing}, extra={extra}"
        )
    return policy, roots, identities


def manifest_records(manifest: dict, manifest_path: Path) -> tuple[dict, dict[str, list[dict]]]:
    policy = manifest.get("profiled_python_entrypoints")
    install = manifest.get("install_policy")
    if not isinstance(install, dict) or (
        install.get("owner") != 0
        or install.get("group") != 0
        or install.get("profiled_python_mode") != "0555"
    ):
        raise ValidationFailure(f"manifest lacks root-owned profiled intent: {manifest_path}")
    if isinstance(manifest.get("payloads"), dict):
        areas = manifest["payloads"]
    else:
        external = manifest.get("protected_external_roots")
        if not isinstance(external, list):
            raise ValidationFailure(f"manifest lacks protected roots: {manifest_path}")
        areas = {
            item.get("name"): item.get("files")
            for item in external
            if isinstance(item, dict)
        }
    return policy, areas


def validate_manifest(
    path: Path, canonical_policy: dict, profiled: set[tuple[str, str]]
) -> None:
    manifest = read_json(path)
    policy, areas = manifest_records(manifest, path)
    if policy != canonical_policy:
        raise ValidationFailure(f"manifest profiled inventory differs: {path}")
    seen: set[tuple[str, str]] = set()
    for root_name in ("build_software", "boot", "virtualbox_software"):
        records = areas.get(root_name)
        if not isinstance(records, list):
            raise ValidationFailure(f"manifest root is missing: {path}: {root_name}")
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                raise ValidationFailure(f"manifest file record is malformed: {path}: {root_name}")
            identity = (root_name, record["path"])
            if identity in profiled:
                seen.add(identity)
                expected_mode = "0555"
            elif record["path"].endswith(".py"):
                expected_mode = "0444"
            else:
                continue
            if record.get("install_mode") != expected_mode:
                raise ValidationFailure(
                    f"manifest mode differs for {root_name}/{record['path']}: "
                    f"expected {expected_mode}, found {record.get('install_mode')}"
                )
    if seen != profiled:
        missing = sorted(profiled - seen)
        raise ValidationFailure(f"manifest omits profiled Python entries: {path}: {missing}")


def validate_staged_root(root: Path, policy: dict) -> None:
    for entry in policy["entries"]:
        path = root / entry["destination"].lstrip("/")
        try:
            status = path.lstat()
            payload = path.read_bytes()
        except OSError as error:
            raise ValidationFailure(f"could not inspect staged entrypoint {path}: {error}") from error
        if (
            path.is_symlink()
            or not stat.S_ISREG(status.st_mode)
            or status.st_uid != 0
            or status.st_gid != 0
            or stat.S_IMODE(status.st_mode) != 0o555
            or status.st_nlink != 1
        ):
            raise ValidationFailure(f"staged entrypoint lacks root-owned 0555 identity: {path}")
        if payload.startswith(b"\xef\xbb\xbf") or not payload.startswith(EXPECTED_SHEBANG):
            raise ValidationFailure(f"staged entrypoint shebang differs: {path}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="T1OS source root",
    )
    parser.add_argument("--manifest", type=Path, action="append", default=[])
    parser.add_argument("--staged-root", type=Path)
    return parser.parse_args()


def main() -> int:
    if os.name != "posix":
        raise ValidationFailure("run this static validator with the WSL host Python")
    arguments = parse_arguments()
    repo = arguments.repo.resolve()
    policy, _, profiled = load_policy(repo)
    manifests = list(arguments.manifest)
    if not manifests:
        defaults = (
            repo / "source" / "software" / "python" / "manifest.json",
            repo / "development" / "python 3.14 candidate" / "t1os" / "manifest.json",
        )
        manifests = [path for path in defaults if path.is_file()]
    if not manifests:
        raise ValidationFailure("no candidate or canonical manifest was supplied")
    for manifest in manifests:
        validate_manifest(manifest.resolve(), policy, profiled)
    if arguments.staged_root is not None:
        validate_staged_root(arguments.staged_root.resolve(), policy)
    print(
        json.dumps(
            {
                "state": "verified",
                "profiled_python_entrypoints": len(profiled),
                "manifests": [str(path) for path in manifests],
                "staged_root": str(arguments.staged_root) if arguments.staged_root else None,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationFailure as error:
        print(f"profiled Python validation: {error}", file=sys.stderr)
        raise SystemExit(1)
