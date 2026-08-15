#!/usr/bin/env python3
"""Audit, build, and verify the T1OS CPython 3.13 release-zero runtime.

This program intentionally uses only the host Python standard library.  Build
and runtime verification require Linux plus readelf and patchelf.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import csv
import functools
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile


REPO = Path(__file__).resolve().parents[1]
PYTHON_SOURCE = REPO / "source" / "python"
RUNTIME_CONFIG = PYTHON_SOURCE / "build" / "runtime.json"
INPUT_LOCK = PYTHON_SOURCE / "locks" / "inputs.json"
MODULE_LOCK = PYTHON_SOURCE / "locks" / "system-modules.json"
IMPORT_CONTRACT = PYTHON_SOURCE / "contracts" / "imports.json"
PROVENANCE_REPORT = PYTHON_SOURCE / "provenance" / "legacy-evidence.json"
NATIVE_LOCK = PYTHON_SOURCE / "locks" / "native-catalogue.json"
RELEASE_LOCK = PYTHON_SOURCE / "locks" / "release-zero.json"
TLS_FIXTURE_ROOT = PYTHON_SOURCE / "tests" / "tls"
TLS_FIXTURE_CA = TLS_FIXTURE_ROOT / "ca.pem"
TLS_FIXTURE_CERTIFICATE = TLS_FIXTURE_ROOT / "server-cert.pem"
TLS_FIXTURE_KEY = TLS_FIXTURE_ROOT / "server-key.pem"
PROMOTION_JOURNAL = PYTHON_SOURCE / "promotion-journal.json"
DEVELOPMENT_ROOT = REPO / "development" / "python runtime"
STAGE_ROOT = DEVELOPMENT_ROOT / "stage"
CACHE_ROOT = DEVELOPMENT_ROOT / "cache"
BUILD_REPORT = DEVELOPMENT_ROOT / "build-report.json"
SOFTWARE_DESTINATION = REPO / "source" / "software" / "python"
CATALOGUE_DESTINATION = REPO / "source" / "catalogue" / "python"
MANIFEST_NAME = "manifest.json"
TREE_ALGORITHM = "t1os-tree-sha256-v1"
INSTALL_TREE_ALGORITHM = "t1os-install-tree-sha256-v2"
PROFILED_SHEBANG = b'#!"/the one/software/python/bin/python" -B\n'
EXPECTED_PROTECTED_EXTERNAL_ROOTS = [
    {
        "name": "image_catalogue",
        "source": "source/catalogue/image",
        "destination": "/the one/catalogue/image",
        "exclude_generated_bytecode": False,
    },
    {
        "name": "build_software",
        "source": "source/build software",
        "destination": "/the one/build",
        "exclude_generated_bytecode": True,
    },
    {
        "name": "boot",
        "source": "source/boot",
        "destination": "/boot",
        "exclude_generated_bytecode": True,
    },
    {
        "name": "virtualbox_software",
        "source": "source/software/virtualbox",
        "destination": "/the one/software/virtualbox",
        "exclude_generated_bytecode": True,
    },
]


class BuildFailure(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildFailure(f"Could not read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise BuildFailure(f"Expected a JSON object in {path}")
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_text(payload, encoding="utf-8", newline="\n")


def relative_to_repo(path: Path) -> str:
    return path.resolve().relative_to(REPO).as_posix()


def resolve_repo_path(value: str) -> Path:
    path = (REPO / value).resolve()
    try:
        path.relative_to(REPO)
    except ValueError as error:
        raise BuildFailure(f"Path leaves the T1OS project: {value}") from error
    return path


def validate_protected_external_root_config(config: dict) -> list[dict]:
    roots = config.get("protected_external_roots")
    if roots != EXPECTED_PROTECTED_EXTERNAL_ROOTS:
        raise BuildFailure(
            "Protected external-root configuration must exactly describe the "
            "image catalogue, build software, boot, and VirtualBox roots"
        )
    for item in roots:
        declared_source = REPO
        for part in Path(item["source"]).parts:
            declared_source /= part
            if declared_source.is_symlink():
                raise BuildFailure(
                    f"Protected external root traverses a symbolic link: {declared_source}"
                )
        source = resolve_repo_path(item["source"])
        if not source.is_dir():
            raise BuildFailure(f"Protected external root is missing: {source}")
        destination = str(item["destination"])
        if not destination.startswith("/") or ".." in Path(destination).parts:
            raise BuildFailure(
                f"Protected external destination is not canonical: {destination}"
            )
    return roots


def profiled_python_policy(config: dict) -> tuple[dict, set[tuple[str, str]]]:
    policy = config.get("profiled_python_entrypoints")
    if not isinstance(policy, dict) or set(policy) != {
        "format", "owner", "group", "install_mode", "shebang", "entries"
    }:
        raise BuildFailure("Profiled Python entrypoint policy is malformed")
    if (
        policy["format"] != 1
        or policy["owner"] != 0
        or policy["group"] != 0
        or policy["install_mode"] != "0555"
        or policy["shebang"] != PROFILED_SHEBANG.decode("ascii")
        or not isinstance(policy["entries"], list)
        or not policy["entries"]
    ):
        raise BuildFailure("Profiled Python entrypoint policy is not fail-closed")
    roots = {item["name"]: item for item in validate_protected_external_root_config(config)}
    identities: set[tuple[str, str]] = set()
    destinations: set[str] = set()
    ordered_destinations: list[str] = []
    for entry in policy["entries"]:
        if not isinstance(entry, dict) or set(entry) != {"root", "path", "destination"}:
            raise BuildFailure("Profiled Python entrypoint record is malformed")
        root_name = entry["root"]
        relative = entry["path"]
        destination = entry["destination"]
        if root_name not in roots or not isinstance(relative, str) or not isinstance(destination, str):
            raise BuildFailure("Profiled Python entrypoint identity is malformed")
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
            raise BuildFailure(f"Unsafe profiled Python entrypoint: {relative!r}")
        expected_destination = roots[root_name]["destination"].rstrip("/") + "/" + relative
        if destination != expected_destination:
            raise BuildFailure(f"Profiled Python destination differs: {destination}")
        identity = (root_name, relative)
        if identity in identities or destination in destinations:
            raise BuildFailure(f"Duplicate profiled Python entrypoint: {destination}")
        source = REPO / roots[root_name]["source"] / Path(*parsed.parts)
        try:
            mode = source.lstat().st_mode
            payload = source.read_bytes()
        except OSError as error:
            raise BuildFailure(
                f"Could not inspect profiled Python entrypoint {source}: {error}"
            ) from error
        if source.is_symlink() or not stat.S_ISREG(mode):
            raise BuildFailure(f"Profiled Python entrypoint is not regular: {source}")
        if payload.startswith(b"\xef\xbb\xbf") or not payload.startswith(PROFILED_SHEBANG):
            raise BuildFailure(
                f"Profiled Python entrypoint lacks the exact byte-0 LF shebang: {source}"
            )
        identities.add(identity)
        destinations.add(destination)
        ordered_destinations.append(destination)
    if ordered_destinations != sorted(ordered_destinations):
        raise BuildFailure("Profiled Python entrypoint inventory is not ordered")
    return policy, identities


def require_within(path: Path, parent: Path) -> None:
    path = path.resolve()
    parent = parent.resolve()
    try:
        path.relative_to(parent)
    except ValueError as error:
        raise BuildFailure(f"Refusing to modify {path}; expected it below {parent}") from error
    if path == parent:
        raise BuildFailure(f"Refusing to modify the complete root {parent}")


def remove_tree(path: Path, parent: Path) -> None:
    require_within(path, parent)
    if path.is_symlink():
        raise BuildFailure(f"Refusing to recursively remove a symlink: {path}")
    if path.exists():
        def ignore_already_removed(function, failed_path, error):
            del function, failed_path
            if isinstance(error, FileNotFoundError):
                return
            raise error

        shutil.rmtree(path, onexc=ignore_already_removed)


@functools.lru_cache(maxsize=None)
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_stream(stream: io.BufferedReader) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        size += len(block)
        digest.update(block)
    return digest.hexdigest(), size


def verify_locked_file(item: dict, label: str) -> Path:
    path = resolve_repo_path(str(item["path"]))
    if not path.is_file():
        raise BuildFailure(f"Locked {label} is missing: {path}")
    size = path.stat().st_size
    expected_size = int(item["size"])
    if size != expected_size:
        raise BuildFailure(
            f"Locked {label} size mismatch: expected {expected_size}, received {size}"
        )
    actual = sha256_file(path)
    expected = str(item["sha256"]).lower()
    if actual != expected:
        raise BuildFailure(
            f"Locked {label} SHA-256 mismatch: expected {expected}, received {actual}"
        )
    return path


def ignored_generated(path: Path) -> bool:
    return path.suffix in {".pyc", ".pyo"} or "__pycache__" in path.parts


def file_records(root: Path, *, ignore_generated: bool = False) -> list[dict]:
    if not root.is_dir():
        raise BuildFailure(f"Directory is missing: {root}")
    records: list[dict] = []
    for path in sorted(root.rglob("*"), key=lambda candidate: candidate.as_posix()):
        if path.is_symlink():
            raise BuildFailure(f"Symbolic link is forbidden in a T1OS payload: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if ignore_generated and ignored_generated(relative):
            continue
        records.append(
            {
                "path": relative.as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return records


def install_tree_summary(directories: list[dict], files: list[dict]) -> dict:
    """Hash an exact, ordered install topology including its normalized modes."""
    digest = hashlib.sha256()
    for item in directories:
        digest.update(
            f"directory\t{item['path']}\t{item['install_mode']}\n".encode("utf-8")
        )
    for item in files:
        digest.update(
            (
                f"file\t{item['path']}\t{item['size']}\t{item['sha256']}\t"
                f"{item['install_mode']}\n"
            ).encode("utf-8")
        )
    return {
        "algorithm": INSTALL_TREE_ALGORITHM,
        "directories": len(directories),
        "files": len(files),
        "bytes": sum(int(item["size"]) for item in files),
        "sha256": digest.hexdigest(),
    }


def payload_inventory(
    root: Path,
    *,
    skip_files: set[str] | None = None,
    executable_prefixes: tuple[str, ...] = (),
    exclude_generated_bytecode: bool = False,
    root_name: str | None = None,
    profiled: set[tuple[str, str]] | None = None,
) -> dict:
    """Return the complete normalized install topology below ``root``.

    DrvFS/OneDrive checkout modes are not trustworthy POSIX metadata.  The
    records therefore carry the modes the image installer must apply.  A
    payload may contain only ordinary directories and regular files; refusing
    links and special nodes makes an inventory comparison topology-complete.
    """
    skip_files = set() if skip_files is None else set(skip_files)
    try:
        root_mode = root.lstat().st_mode
    except OSError as error:
        raise BuildFailure(f"Could not inspect payload root {root}: {error}") from error
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        raise BuildFailure(f"Payload root is not an ordinary directory: {root}")

    # Protected roots remain owner-writable while the system is offline so the
    # unprivileged, ACL-preserving USB updater can replace payloads atomically.
    # PID 1 verifies the complete inventory before userspace starts; the T1OS
    # LSM then restricts runtime mutation to the Architect role.
    directories = [{"path": ".", "install_mode": "0755"}]
    files: list[dict] = []
    for path in sorted(root.rglob("*"), key=lambda candidate: candidate.as_posix()):
        relative_path = path.relative_to(root)
        relative = relative_path.as_posix()
        if any(character in relative for character in "\t\r\n"):
            raise BuildFailure(f"Payload path contains a forbidden control character: {path}")
        try:
            mode = path.lstat().st_mode
        except OSError as error:
            raise BuildFailure(f"Could not inspect payload entry {path}: {error}") from error
        if stat.S_ISLNK(mode):
            raise BuildFailure(f"Symbolic link is forbidden in a T1OS payload: {path}")
        if exclude_generated_bytecode and (
            "__pycache__" in relative_path.parts
            or (
                stat.S_ISREG(mode)
                and relative_path.suffix in {".pyc", ".pyo"}
            )
        ):
            continue
        if stat.S_ISDIR(mode):
            directories.append({"path": relative, "install_mode": "0755"})
            continue
        if not stat.S_ISREG(mode):
            raise BuildFailure(f"Special file is forbidden in a T1OS payload: {path}")
        if relative in skip_files:
            continue
        is_profiled = (
            root_name is not None
            and profiled is not None
            and (root_name, relative) in profiled
        )
        executable = is_profiled or (
            not relative.endswith(".py")
            and (
                is_elf(path)
                or any(relative.startswith(prefix) for prefix in executable_prefixes)
            )
        )
        files.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
                "install_mode": "0555" if executable else "0444",
            }
        )
    directories.sort(key=lambda item: item["path"])
    files.sort(key=lambda item: item["path"])
    return {
        "directories": directories,
        "files": files,
        "tree": install_tree_summary(directories, files),
    }


def protected_external_root_inventories(config: dict) -> list[dict]:
    inventories = []
    _, profiled = profiled_python_policy(config)
    for item in validate_protected_external_root_config(config):
        inventory = payload_inventory(
            resolve_repo_path(item["source"]),
            exclude_generated_bytecode=item["exclude_generated_bytecode"],
            root_name=item["name"],
            profiled=profiled,
        )
        inventories.append({**item, **inventory})
    return inventories


def protected_root_for_source(path: Path, config: dict) -> tuple[dict, Path]:
    matches = []
    resolved = path.resolve()
    for item in validate_protected_external_root_config(config):
        source_root = resolve_repo_path(item["source"])
        try:
            relative = resolved.relative_to(source_root)
        except ValueError:
            continue
        matches.append((item, relative))
    if len(matches) != 1:
        raise BuildFailure(
            f"Active T1OS source must belong to exactly one protected root: {path}"
        )
    return matches[0]


def tree_summary(root: Path, *, ignore_generated: bool = False) -> dict:
    records = file_records(root, ignore_generated=ignore_generated)
    digest = hashlib.sha256()
    for item in records:
        digest.update(
            (
                f"file\t{item['path']}\t{item['size']}\t{item['sha256']}\n"
            ).encode("utf-8")
        )
    return {
        "algorithm": TREE_ALGORITHM,
        "files": len(records),
        "bytes": sum(int(item["size"]) for item in records),
        "sha256": digest.hexdigest(),
        "generated_bytecode_excluded": ignore_generated,
    }


def records_by_path(root: Path, *, ignore_generated: bool = False) -> dict[str, dict]:
    return {
        item["path"]: item
        for item in file_records(root, ignore_generated=ignore_generated)
    }


def tree_delta(before: Path, after: Path) -> dict:
    left = records_by_path(before, ignore_generated=True)
    right = records_by_path(after, ignore_generated=True)
    left_paths = set(left)
    right_paths = set(right)
    changed = sorted(
        path
        for path in left_paths & right_paths
        if left[path]["size"] != right[path]["size"]
        or left[path]["sha256"] != right[path]["sha256"]
    )
    return {
        "added": sorted(right_paths - left_paths),
        "removed": sorted(left_paths - right_paths),
        "changed": changed,
    }


def archive_topology(path: Path) -> dict:
    regular_files = 0
    regular_bytes = 0
    directories = 0
    symbolic_links = 0
    hard_links = 0
    with tarfile.open(path, "r:*") as archive:
        for member in archive:
            if member.isfile():
                regular_files += 1
                regular_bytes += member.size
            elif member.isdir():
                directories += 1
            elif member.issym():
                symbolic_links += 1
            elif member.islnk():
                hard_links += 1
    return {
        "regular_files": regular_files,
        "regular_bytes": regular_bytes,
        "directories": directories,
        "symbolic_links": symbolic_links,
        "hard_links": hard_links,
    }


def compare_source_tree(archive_path: Path, dirty_root: Path) -> dict:
    prefix = "Python-3.13.5/"
    archive_files: dict[str, dict] = {}
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive:
            if not member.isfile() or not member.name.startswith(prefix):
                continue
            relative = member.name[len(prefix) :]
            extracted = archive.extractfile(member)
            if extracted is None:
                raise BuildFailure(f"Could not read archive member {member.name}")
            digest, size = sha256_stream(extracted)
            archive_files[relative] = {"size": size, "sha256": digest}

    dirty_files = records_by_path(dirty_root)
    missing = sorted(set(archive_files) - set(dirty_files))
    generated = sorted(set(dirty_files) - set(archive_files))
    generated_digest = hashlib.sha256()
    for path in generated:
        item = dirty_files[path]
        generated_digest.update(
            f"file\t{path}\t{item['size']}\t{item['sha256']}\n".encode("utf-8")
        )
    changed = []
    for path in sorted(set(archive_files) & set(dirty_files)):
        original = archive_files[path]
        working = dirty_files[path]
        if original["size"] != working["size"] or original["sha256"] != working["sha256"]:
            changed.append(
                {
                    "path": path,
                    "upstream_size": original["size"],
                    "upstream_sha256": original["sha256"],
                    "working_size": working["size"],
                    "working_sha256": working["sha256"],
                }
            )
    return {
        "archive_files": len(archive_files),
        "archive_bytes": sum(item["size"] for item in archive_files.values()),
        "working_files": len(dirty_files),
        "working_bytes": sum(item["size"] for item in dirty_files.values()),
        "missing_archive_members": missing,
        "content_changes": changed,
        "generated_files": {
            "count": len(generated),
            "bytes": sum(dirty_files[path]["size"] for path in generated),
            "sha256": generated_digest.hexdigest(),
            "suffixes": count_suffixes(generated),
        },
    }


def count_suffixes(paths: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in paths:
        suffix = Path(value).suffix or "<none>"
        counts[suffix] = counts.get(suffix, 0) + 1
    return dict(sorted(counts.items()))


def download_locked(item: dict, *, offline: bool) -> Path:
    filename = str(item.get("filename", ""))
    if not filename or Path(filename).name != filename or "/" in filename or "\\" in filename:
        raise BuildFailure(f"Locked artifact filename is not a basename: {filename!r}")
    digest = str(item.get("sha256", "")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise BuildFailure(f"Locked artifact has an invalid SHA-256: {filename}")
    if not str(item.get("url", "")).startswith("https://"):
        raise BuildFailure(f"Locked artifact URL must use HTTPS: {filename}")
    if int(item.get("size", 0)) <= 0:
        raise BuildFailure(f"Locked artifact has an invalid size: {filename}")
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    target = CACHE_ROOT / filename
    require_within(target, CACHE_ROOT)
    if target.is_file():
        if target.stat().st_size == int(item["size"]) and sha256_file(target) == digest:
            return target
        target.unlink()
        sha256_file.cache_clear()
    if offline:
        raise BuildFailure(f"Locked cache artifact is unavailable in offline mode: {target}")
    partial = target.with_name(target.name + ".partial")
    if partial.exists():
        partial.unlink()
    request = urllib.request.Request(
        str(item["url"]), headers={"User-Agent": "T1OS-Python-Builder/1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
    except Exception as error:
        with contextlib.suppress(OSError):
            partial.unlink()
        raise BuildFailure(f"Could not download {item['url']}: {error}") from error
    if partial.stat().st_size != int(item["size"]) or sha256_file(partial) != digest:
        partial.unlink()
        sha256_file.cache_clear()
        raise BuildFailure(f"Downloaded artifact failed its lock: {item['filename']}")
    partial.replace(target)
    sha256_file.cache_clear()
    return target


def wheel_package_records(wheel: Path, package: str) -> dict[str, dict]:
    prefix = package.rstrip("/") + "/"
    records: dict[str, dict] = {}
    with zipfile.ZipFile(wheel) as archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.startswith(prefix):
                continue
            relative = info.filename[len(prefix) :]
            with archive.open(info) as stream:
                digest, size = sha256_stream(stream)
            records[relative] = {"size": size, "sha256": digest}
    return records


def local_package_records(root: Path) -> dict[str, dict]:
    return {
        item["path"]: item
        for item in file_records(root, ignore_generated=True)
    }


def compare_record_maps(expected: dict[str, dict], actual: dict[str, dict]) -> dict:
    expected_paths = set(expected)
    actual_paths = set(actual)
    changed = sorted(
        path
        for path in expected_paths & actual_paths
        if expected[path]["size"] != actual[path]["size"]
        or expected[path]["sha256"] != actual[path]["sha256"]
    )
    return {
        "match": not changed and expected_paths == actual_paths,
        "expected_files": len(expected),
        "actual_files": len(actual),
        "missing": sorted(expected_paths - actual_paths),
        "extra": sorted(actual_paths - expected_paths),
        "changed": changed,
    }


def recover_pyroute2_from_image(image: Path, destination: Path) -> Path:
    debugfs = shutil.which("debugfs")
    if not debugfs:
        raise BuildFailure("debugfs is required to verify the disk-image pyroute2 package")
    destination.mkdir(parents=True, exist_ok=True)
    command = (
        'rdump "/the one/software/python/lib/python3.13/site-packages/pyroute2" '
        f'"{destination}"'
    )
    result = subprocess.run(
        [debugfs, "-R", command, str(image)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise BuildFailure(f"debugfs could not recover pyroute2: {result.stderr.strip()}")
    package = destination / "pyroute2"
    if not package.is_dir():
        raise BuildFailure("debugfs did not recover the pyroute2 package")
    return package


def verify_native_catalogue_lock(inputs: dict) -> dict:
    native = load_json(NATIVE_LOCK)
    source = resolve_repo_path(inputs["legacy"]["native_catalogue"])
    if native.get("source") != inputs["legacy"]["native_catalogue"]:
        raise BuildFailure("Native catalogue lock names a different legacy source")
    expected = [
        {key: item[key] for key in ("path", "size", "sha256")}
        for item in native.get("files", [])
    ]
    actual = file_records(source)
    if actual != expected:
        delta = compare_record_maps(
            {item["path"]: item for item in expected},
            {item["path"]: item for item in actual},
        )
        raise BuildFailure("Legacy native catalogue differs from its lock: " + json.dumps(delta))
    actual_tree = tree_summary(source)
    if actual_tree != native.get("tree"):
        raise BuildFailure("Legacy native catalogue tree digest differs from its lock")
    return native


def verify_inputs() -> tuple[dict, dict, dict, dict]:
    runtime = load_json(RUNTIME_CONFIG)
    validate_protected_external_root_config(runtime)
    if runtime.get("ssl") != {
        "default_ca_file": "/the one/settings/network/cacerts.pem"
    }:
        raise BuildFailure("Python SSL configuration must use the managed T1OS CA bundle")
    inputs = load_json(INPUT_LOCK)
    modules = load_json(MODULE_LOCK)
    imports = load_json(IMPORT_CONTRACT)
    verify_locked_file(inputs["upstream"]["cpython"], "CPython source archive")
    verify_locked_file(inputs["upstream"]["portable_runtime"], "Portable Python runtime")
    for name, item in inputs["unmodified_glibc_base"].items():
        verify_locked_file(item, f"unmodified glibc base {name}")
    legacy = inputs["legacy"]
    for key in (
        "portable_extracted",
        "duplicate_portable_extracted",
        "dirty_cpython_tree",
        "readline_stage",
        "final_runtime",
        "native_catalogue",
        "freetype_tree",
    ):
        path = resolve_repo_path(str(legacy[key]))
        if not path.is_dir():
            raise BuildFailure(f"Legacy evidence directory is missing: {path}")
    sitecustomize = resolve_repo_path(
        next(item for item in modules["t1os_components"] if item["name"] == "sitecustomize")["path"]
    )
    if sha256_file(sitecustomize) != legacy["sitecustomize_sha256"]:
        raise BuildFailure("Managed sitecustomize no longer matches the recovered final source")
    copy_script = resolve_repo_path(legacy["copy_script"])
    if sha256_file(copy_script) != legacy["copy_script_sha256"]:
        raise BuildFailure("Legacy native-library copy script differs from its lock")
    historical = legacy["dirty_getpath"]
    patch = resolve_repo_path(historical["historical_patch"])
    if (
        patch.stat().st_size != historical["historical_patch_size"]
        or sha256_file(patch) != historical["historical_patch_sha256"]
    ):
        raise BuildFailure("Historical getpath patch differs from its evidence lock")
    verify_native_catalogue_lock(inputs)
    return runtime, inputs, modules, imports


def verify_provenance_release(runtime: dict) -> None:
    if not PROVENANCE_REPORT.is_file():
        raise BuildFailure(
            "Python provenance report is missing; run the evidence audit with --write"
        )
    provenance = load_json(PROVENANCE_REPORT)
    if (
        provenance.get("format") != 1
        or provenance.get("component") != "python-legacy-evidence"
        or provenance.get("release") != runtime["release"]
    ):
        raise BuildFailure(
            "Python provenance report does not match the configured release; "
            "run the evidence audit with --write before building"
        )


def audit_evidence(*, write: bool, offline: bool) -> dict:
    runtime, inputs, modules, _ = verify_inputs()
    upstream = inputs["upstream"]
    legacy = inputs["legacy"]
    cpython_archive = resolve_repo_path(upstream["cpython"]["path"])
    portable_archive = resolve_repo_path(upstream["portable_runtime"]["path"])
    portable = resolve_repo_path(legacy["portable_extracted"])
    duplicate = resolve_repo_path(legacy["duplicate_portable_extracted"])
    readline = resolve_repo_path(legacy["readline_stage"])
    final = resolve_repo_path(legacy["final_runtime"])
    catalogue = resolve_repo_path(legacy["native_catalogue"])

    package_items = {item["name"]: item for item in modules["packages"]}
    freetype_wheel = download_locked(package_items["freetype-py"], offline=offline)
    pyroute_wheel = download_locked(package_items["pyroute2"], offline=offline)
    freetype_match = compare_record_maps(
        wheel_package_records(freetype_wheel, "freetype"),
        local_package_records(resolve_repo_path(legacy["freetype_tree"])),
    )

    pyroute_match: dict
    storage = REPO / "environment" / "storage.img"
    if os.name == "posix" and storage.is_file():
        with tempfile.TemporaryDirectory(prefix="t1os-python-audit-") as temporary:
            recovered = recover_pyroute2_from_image(storage, Path(temporary))
            pyroute_match = compare_record_maps(
                wheel_package_records(pyroute_wheel, "pyroute2"),
                local_package_records(recovered),
            )
    else:
        pyroute_match = {
            "match": None,
            "reason": "disk-image package comparison requires Linux and debugfs",
        }

    source_comparison = compare_source_tree(
        cpython_archive, resolve_repo_path(legacy["dirty_cpython_tree"])
    )
    changed = source_comparison["content_changes"]
    expected_getpath = legacy["dirty_getpath"]
    if len(changed) != 1 or changed[0] != {
        "path": expected_getpath["path"],
        "upstream_size": 27291,
        "upstream_sha256": upstream["cpython"]["pristine_getpath_sha256"],
        "working_size": expected_getpath["size"],
        "working_sha256": expected_getpath["sha256"],
    }:
        raise BuildFailure("The dirty CPython getpath evidence differs from its exact lock")
    if source_comparison["missing_archive_members"]:
        raise BuildFailure("The dirty CPython tree is missing upstream source members")
    generated = source_comparison["generated_files"]
    expected_generated = legacy["dirty_generated_files"]
    for key in ("count", "bytes", "sha256"):
        if generated[key] != expected_generated[key]:
            raise BuildFailure("The dirty CPython generated-artifact set differs from its lock")
    if not freetype_match["match"]:
        raise BuildFailure("Recovered freetype does not match the locked wheel")
    if pyroute_match.get("match") is False:
        raise BuildFailure("Installed pyroute2 does not match the locked wheel")

    portable_summary = tree_summary(portable, ignore_generated=True)
    duplicate_summary = tree_summary(duplicate, ignore_generated=True)
    if portable_summary != duplicate_summary:
        raise BuildFailure("pythonofficial/3.13.5 is no longer identical to Portable Python")
    stage_summaries = {
        "portable": portable_summary,
        "readline": tree_summary(readline, ignore_generated=True),
        "final": tree_summary(final, ignore_generated=True),
    }
    for name, expected in legacy["normalized_stage_locks"].items():
        if stage_summaries[name] != expected:
            raise BuildFailure(f"Normalized legacy {name} stage differs from its lock")

    report = {
        "format": 1,
        "component": "python-legacy-evidence",
        "release": runtime["release"],
        "tree_algorithm": TREE_ALGORITHM,
        "conclusions": {
            "authoritative_binary_input": upstream["portable_runtime"]["path"],
            "duplicate_runtime_is_not_an_official_build": True,
            "getpath_patch_is_historical_and_not_applied": True,
            "byte_identical_source_rebuild_claimed": False,
            "reproducible_recovered_artifact_transformation_claimed": True,
        },
        "upstream": {
            "cpython_archive": {
                "path": upstream["cpython"]["path"],
                "size": upstream["cpython"]["size"],
                "sha256": upstream["cpython"]["sha256"],
            },
            "portable_archive": {
                "path": upstream["portable_runtime"]["path"],
                "size": upstream["portable_runtime"]["size"],
                "sha256": upstream["portable_runtime"]["sha256"],
                "topology": archive_topology(portable_archive),
            },
        },
        "source_tree": source_comparison,
        "stages": {
            "portable": portable_summary,
            "duplicate_portable": duplicate_summary,
            "readline": stage_summaries["readline"],
            "final": stage_summaries["final"],
            "native_catalogue": tree_summary(catalogue),
        },
        "deltas": {
            "portable_to_readline": tree_delta(portable, readline),
            "readline_to_final": tree_delta(readline, final),
        },
        "module_recovery": {
            "freetype_py_2_5_1": freetype_match,
            "pyroute2_0_9_4": pyroute_match,
        },
        "known_unknowns": [
            "the exact historical patchelf version and command sequence",
            "the exact Portable Python 1.9.9 transitive Python dependencies",
            "the complete package provenance of the 90-file shared native catalogue",
            "the complete build-host package set and environment",
        ],
        "volatile_legacy_bytecode": {
            "excluded_from_normalized_stage_trees": True,
            "reason": "legacy pyc files embed build/install paths and can be rewritten on import",
        },
    }
    if write:
        write_json(PROVENANCE_REPORT, report)
    return report


def create_native_catalogue_lock(
    catalogue: Path,
    legacy_runtime: Path,
    runtime_config: dict,
    inputs: dict,
    tools: dict,
) -> dict:
    files = file_records(catalogue)
    provided = {item["path"] for item in files}
    entries = []
    unresolved = []
    needed_edges = 0
    catalogue_metadata: dict[str, dict] = {}
    for item in files:
        path = catalogue / item["path"]
        record = dict(item)
        record["provenance"] = "legacy-recovered; original distribution package not recorded"
        if is_elf(path):
            metadata = elf_metadata(path, tools)
            record["elf"] = metadata
            catalogue_metadata[item["path"]] = metadata
            if metadata["package"]:
                record["provenance"] = "legacy-recovered with embedded distribution package note"
            needed_edges += len(metadata["needed"])
            missing = sorted(set(metadata["needed"]) - provided)
            if missing:
                unresolved.append({"path": item["path"], "needed": missing})
        entries.append(record)

    dynload = legacy_runtime / "lib" / "python3.13" / "lib-dynload"
    unsupported = set(runtime_config["unsupported_extensions"])
    consumers = [legacy_runtime / "bin" / "python3.13"]
    consumers.extend(
        path for path in sorted(dynload.glob("*.so")) if path.name not in unsupported
    )
    closure = {"ld-linux-x86-64.so.2"}
    for consumer in consumers:
        closure.update(elf_metadata(consumer, tools)["needed"])
    closure = expand_native_closure(closure, catalogue_metadata)
    missing_closure = sorted(closure - provided)
    if unresolved:
        raise BuildFailure(f"Legacy catalogue internal closure changed: {unresolved}")
    if missing_closure:
        raise BuildFailure(f"Supported Python native closure is incomplete: {missing_closure}")

    return {
        "format": 1,
        "component": "python-native-catalogue-legacy-lock",
        "role": "shared T1OS platform base consumed by Python, graphics, audio, image and VirtualBox",
        "source": inputs["legacy"]["native_catalogue"],
        "source_script": {
            "path": inputs["legacy"]["copy_script"],
            "sha256": inputs["legacy"]["copy_script_sha256"],
            "declared_names": inputs["legacy"]["native_catalogue_facts"]["copy_script_declared_names"],
            "undeclared_files": inputs["legacy"]["native_catalogue_facts"]["undeclared_files"],
        },
        "tree": tree_summary(catalogue),
        "files": entries,
        "closure": {
            "provided_filenames": sorted(provided),
            "needed_edges": needed_edges,
            "unresolved": unresolved,
            "supported_python_consumers": len(consumers),
            "supported_python_filenames": sorted(closure),
            "supported_python_bytes": sum((catalogue / name).stat().st_size for name in closure),
        },
        "known_unknowns": [
            "distribution package and version for most files",
            "original pre-patchelf hashes for non-glibc libraries",
            "the commands that added 49 files not named by copylibs.sh",
        ],
    }


def expand_native_closure(
    initial: set[str], catalogue_metadata: dict[str, dict]
) -> set[str]:
    closure = set(initial)
    pending = list(initial)
    while pending:
        name = pending.pop()
        metadata = catalogue_metadata.get(name)
        if not metadata:
            continue
        for dependency in metadata["needed"]:
            if dependency not in closure:
                closure.add(dependency)
                pending.append(dependency)
    return closure


def safe_extract_runtime(archive_path: Path, root_name: str, destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    prefix = root_name.rstrip("/") + "/"
    ignored_links: list[str] = []
    extracted = 0
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive:
            if member.name == root_name and member.isdir():
                continue
            if not member.name.startswith(prefix):
                raise BuildFailure(f"Portable archive member leaves expected root: {member.name}")
            relative_text = member.name[len(prefix) :]
            if not relative_text:
                continue
            relative = Path(relative_text)
            if relative.is_absolute() or ".." in relative.parts:
                raise BuildFailure(f"Unsafe portable archive member: {member.name}")
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.issym() or member.islnk():
                ignored_links.append(relative.as_posix())
                continue
            if not member.isfile():
                raise BuildFailure(f"Unsupported portable archive member type: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise BuildFailure(f"Could not extract portable archive member: {member.name}")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            with contextlib.suppress(OSError):
                target.chmod(member.mode & 0o777)
            extracted += 1
    return {"regular_files": extracted, "ignored_links": sorted(ignored_links)}


def remove_generated_bytecode(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            raise BuildFailure(f"Unexpected symlink while cleaning bytecode: {path}")
        if path.is_file() and path.suffix in {".pyc", ".pyo"}:
            # OneDrive can remove a generated file after rglob() has returned
            # it. That already satisfies this cleanup operation and must not
            # make an otherwise deterministic build fail.
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        elif path.is_dir() and path.name == "__pycache__":
            remove_tree(path, root)


def slim_runtime(root: Path, config: dict) -> None:
    slim = config["slim_runtime"]
    for relative in slim["remove_directories"]:
        path = root / relative
        if path.exists():
            remove_tree(path, root)
    for relative in slim["remove_files"]:
        path = root / relative
        require_within(path, root)
        if path.exists():
            path.unlink()
    keep = set(slim["keep_bin_files"])
    bin_root = root / "bin"
    for path in bin_root.iterdir():
        if path.name not in keep:
            if path.is_dir():
                remove_tree(path, root)
            else:
                path.unlink()
    dynload = root / "lib" / "python3.13" / "lib-dynload"
    for filename in config["unsupported_extensions"]:
        path = dynload / filename
        if not path.is_file():
            raise BuildFailure(f"Expected unsupported extension is missing from input: {filename}")
        path.unlink()
    for relative in config["unsupported_python_paths"]:
        path = root / relative
        if path.exists():
            if path.is_dir():
                remove_tree(path, root)
            else:
                require_within(path, root)
                path.unlink()


def run(command: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if result.returncode:
        rendered = " ".join(command)
        detail = (result.stderr or result.stdout).strip()
        raise BuildFailure(f"Command failed ({result.returncode}): {rendered}\n{detail}")
    return result


def require_linux_tools() -> dict:
    if os.name != "posix":
        raise BuildFailure("Runtime construction must run under Linux/WSL")
    tools = {}
    for name in ("patchelf", "readelf"):
        path = shutil.which(name)
        if not path:
            raise BuildFailure(f"Required Linux build command is missing: {name}")
        tools[name] = path
    tools["patchelf_version"] = run([tools["patchelf"], "--version"]).stdout.strip()
    tools["readelf_version"] = run([tools["readelf"], "--version"]).stdout.splitlines()[0]
    return tools


def build_definition_records() -> list[dict]:
    paths = [
        Path(__file__).resolve(),
        RUNTIME_CONFIG,
        INPUT_LOCK,
        MODULE_LOCK,
        IMPORT_CONTRACT,
        NATIVE_LOCK,
        PROVENANCE_REPORT,
        PYTHON_SOURCE / "packages" / "sitecustomize.py",
        PYTHON_SOURCE / "packages" / "t1os-ca-certificates.pth",
        TLS_FIXTURE_CA,
        TLS_FIXTURE_CERTIFICATE,
        TLS_FIXTURE_KEY,
        PYTHON_SOURCE / "patches" / "historical" / "0001-force-the-one-python-prefix.patch",
        REPO / "scripts" / "audit python provenance.ps1",
        REPO / "scripts" / "build python runtime.ps1",
        REPO / "scripts" / "test python runtime.ps1",
        REPO / "scripts" / "validate profiled python entrypoints.py",
        REPO / "scripts" / "validate profiled python entrypoints.ps1",
        REPO / "scripts" / "push to disk.ps1",
        REPO / "scripts" / "push managed python to usb.ps1",
        REPO / "resource" / "entry" / "init" / "init hardware.sh",
        REPO / "resource" / "entry" / "kernel" / "t1os_lsm.c",
        REPO / "scripts" / "build hardware initramfs.ps1",
        REPO / "scripts" / "test hardware build.ps1",
    ]
    optional = [
        PYTHON_SOURCE / "build" / "portable-python-source.yml",
        PYTHON_SOURCE / "locks" / "source-rebuild.json",
        REPO / "development" / "build python source diagnostic.py",
        REPO / "scripts" / "build python source diagnostic.ps1",
    ]
    paths.extend(path for path in optional if path.is_file())
    records = []
    for path in paths:
        if not path.is_file():
            raise BuildFailure(f"Build-definition file is missing: {path}")
        records.append(
            {
                "path": relative_to_repo(path),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return sorted(records, key=lambda item: item["path"])


def verify_release_lock_sources(config: dict, tools: dict) -> dict:
    release = load_json(RELEASE_LOCK)
    if release.get("release") != config["release"] or not release.get("immutable"):
        raise BuildFailure("Release-zero lock does not match the configured immutable release")
    expected_tools = release["toolchain"]
    actual_tools = {
        "patchelf": tools["patchelf_version"],
        "builder_python": sys.version.split()[0],
    }
    if actual_tools != expected_tools:
        raise BuildFailure(
            f"Release toolchain differs from its lock: expected {expected_tools}, found {actual_tools}"
        )
    actual_definitions = build_definition_records()
    if actual_definitions != release["build_definitions"]:
        delta = compare_record_maps(
            {item["path"]: item for item in release["build_definitions"]},
            {item["path"]: item for item in actual_definitions},
        )
        raise BuildFailure("Build definitions differ from release zero: " + json.dumps(delta))
    return release


def create_release_lock(
    config: dict,
    tools: dict,
    manifest: dict,
    patching: dict,
    manifest_sha256: str,
) -> dict:
    return {
        "format": 1,
        "component": "python-release-zero",
        "release": config["release"],
        "immutable": True,
        "rebuild_policy": "change the release identifier before replacing this lock",
        "toolchain": {
            "patchelf": tools["patchelf_version"],
            "builder_python": sys.version.split()[0],
        },
        "build_definitions": build_definition_records(),
        "outputs": {
            "software_tree": manifest["software"]["tree"],
            "catalogue_tree": manifest["catalogue"]["tree"],
            "python_sha256": patching["python_sha256"],
            "manifest_sha256": manifest_sha256,
        },
        "protected_external_roots": [
            {
                key: item[key]
                for key in (
                    "name",
                    "source",
                    "destination",
                    "exclude_generated_bytecode",
                    "tree",
                )
            }
            for item in manifest["protected_external_roots"]
        ],
    }


def verify_release_outputs(
    manifest: dict, runtime: Path, release: dict
) -> None:
    expected = release["outputs"]
    if manifest["software"]["tree"] != expected["software_tree"]:
        raise BuildFailure("Software payload differs from the immutable release-zero tree")
    if manifest["catalogue"]["tree"] != expected["catalogue_tree"]:
        raise BuildFailure("Native catalogue differs from the immutable release-zero tree")
    python_hash = sha256_file(runtime / "bin" / "python3.13")
    if python_hash != expected["python_sha256"]:
        raise BuildFailure("Python executable differs from the immutable release-zero lock")
    manifest_hash = sha256_file(runtime / MANIFEST_NAME)
    if manifest_hash != expected.get("manifest_sha256"):
        raise BuildFailure("Python manifest differs from the immutable release-zero lock")
    protected_roots = [
        {
            key: item[key]
            for key in (
                "name",
                "source",
                "destination",
                "exclude_generated_bytecode",
                "tree",
            )
        }
        for item in manifest["protected_external_roots"]
    ]
    if protected_roots != release.get("protected_external_roots"):
        raise BuildFailure(
            "Protected external roots differ from the immutable release-zero lock"
        )
    compare_protected_external_roots(manifest)


def patch_runtime(root: Path, config: dict, tools: dict) -> dict:
    python = root / "bin" / "python3.13"
    dynload = root / "lib" / "python3.13" / "lib-dynload"
    run([tools["patchelf"], "--set-interpreter", config["interpreter"], str(python)])
    run([tools["patchelf"], "--set-rpath", config["runpath"], str(python)])
    extensions = sorted(dynload.glob("*.so"))
    for extension in extensions:
        run([tools["patchelf"], "--set-rpath", config["runpath"], str(extension)])
    return {
        "python": relative_to_repo(python),
        "extensions_patched": len(extensions),
        "python_sha256": sha256_file(python),
    }


def copy_materialized_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        raise BuildFailure(f"Staging destination unexpectedly exists: {destination}")
    for path in source.rglob("*"):
        if path.is_symlink():
            raise BuildFailure(f"Legacy input contains an unmanaged symlink: {path}")
    shutil.copytree(source, destination, copy_function=shutil.copy2)


def build_catalogue(destination: Path, config: dict, inputs: dict) -> dict:
    source = resolve_repo_path(inputs["legacy"]["native_catalogue"])
    copy_materialized_tree(source, destination)
    replacements = []
    if config["normalise_unmodified_glibc_base"]:
        names = {
            "loader": "ld-linux-x86-64.so.2",
            "libc": "libc.so.6",
            "libm": "libm.so.6",
        }
        for key, filename in names.items():
            locked = inputs["unmodified_glibc_base"][key]
            source_file = verify_locked_file(locked, f"unmodified glibc base {key}")
            shutil.copy2(source_file, destination / filename)
            replacements.append(
                {
                    "path": filename,
                    "sha256": locked["sha256"],
                    "reason": "restore unmodified file from recovered base set",
                }
            )
    return {"source": relative_to_repo(source), "base_replacements": replacements}


def extract_wheel(wheel: Path, site_packages: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        for info in archive.infolist():
            relative = Path(info.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise BuildFailure(f"Unsafe wheel member: {info.filename}")
            target = site_packages / relative
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise BuildFailure(f"Wheel member collides with the runtime: {relative}")
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def install_system_modules(
    runtime_root: Path, modules: dict, config: dict, *, offline: bool
) -> list[dict]:
    site_packages = runtime_root / "lib" / "python3.13" / "site-packages"
    installed = []
    for item in modules["packages"]:
        if item["placement"] != "runtime-site-packages":
            continue
        wheel = download_locked(item, offline=offline)
        extract_wheel(wheel, site_packages)
        installed.append(
            {
                "name": item["name"],
                "version": item["version"],
                "filename": item["filename"],
                "sha256": item["sha256"],
            }
        )
    for relative in config["post_install"]["remove_empty_directories"]:
        target = runtime_root / relative
        require_within(target, runtime_root)
        if not target.is_dir() or target.is_symlink():
            raise BuildFailure(f"Configured post-install directory is missing: {target}")
        if any(target.iterdir()):
            raise BuildFailure(
                f"Refusing to remove non-empty post-install directory: {target}"
            )
        target.rmdir()
    return installed


def install_t1os_files(runtime_root: Path, modules: dict) -> list[dict]:
    site_packages = runtime_root / "lib" / "python3.13" / "site-packages"
    installed = []
    for item in modules["t1os_components"]:
        source = resolve_repo_path(item["path"])
        actual = sha256_file(source)
        if actual != item["sha256"]:
            raise BuildFailure(f"T1OS component hash mismatch: {item['name']}")
        target = site_packages / ("sitecustomize.py" if item["name"] == "sitecustomize" else source.name)
        shutil.copy2(source, target)
        installed.append(
            {
                "name": item["name"],
                "version": item["version"],
                "path": target.relative_to(runtime_root).as_posix(),
                "sha256": actual,
            }
        )
    marker = runtime_root / "lib" / "python3.13" / "EXTERNALLY-MANAGED"
    marker.write_text(
        "[externally-managed]\n"
        "Error=This Python installation is managed by T1OS. Install user modules "
        "through the T1OS Python manager, not into the system runtime.\n",
        encoding="utf-8",
        newline="\n",
    )
    return installed


def loader_command(runtime: Path, catalogue: Path, *arguments: str) -> list[str]:
    return [
        str(catalogue / "ld-linux-x86-64.so.2"),
        "--library-path",
        str(catalogue),
        str(runtime / "bin" / "python3.13"),
        *arguments,
    ]


def compile_checked_hash_bytecode(runtime: Path, catalogue: Path, config: dict) -> None:
    bytecode = config["bytecode"]
    if not bytecode["enabled"]:
        return
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONNOUSERSITE": "1",
            "SOURCE_DATE_EPOCH": str(config["source_date_epoch"]),
        }
    )
    target = runtime / "lib" / "python3.13"
    command = loader_command(
        runtime,
        catalogue,
        "-S",
        "-m",
        "compileall",
        "-q",
        "-f",
        "--invalidation-mode",
        bytecode["invalidation_mode"],
        "-s",
        str(runtime),
        "-p",
        bytecode["embedded_prefix"],
        str(target),
    )
    run(command, env=environment)


def is_elf(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 4:
        return False
    with path.open("rb") as stream:
        return stream.read(4) == b"\x7fELF"


def elf_metadata(path: Path, tools: dict) -> dict:
    header = run([tools["readelf"], "-h", str(path)]).stdout
    machine_match = re.search(r"^\s*Machine:\s*(.+)$", header, re.MULTILINE)
    machine = machine_match.group(1).strip() if machine_match else None
    dynamic_result = subprocess.run(
        [tools["readelf"], "-d", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    dynamic = dynamic_result.stdout if dynamic_result.returncode == 0 else ""
    needed = re.findall(r"\(NEEDED\).*?\[(.+?)\]", dynamic)
    soname_match = re.search(r"\(SONAME\).*?\[(.+?)\]", dynamic)
    runpath_match = re.search(r"\((?:RUNPATH|RPATH)\).*?\[(.*?)\]", dynamic)
    program = run([tools["readelf"], "-l", str(path)]).stdout
    interpreter_match = re.search(r"Requesting program interpreter:\s*(.+?)\]", program)
    notes_result = subprocess.run(
        [tools["readelf"], "-n", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    notes = notes_result.stdout
    build_id_match = re.search(r"Build ID:\s*([0-9a-fA-F]+)", notes)
    package_match = re.search(r"Packaging Metadata:\s*(\{.*\})", notes)
    package = None
    if package_match:
        with contextlib.suppress(json.JSONDecodeError):
            package = json.loads(package_match.group(1))
    return {
        "machine": machine,
        "needed": sorted(set(needed)),
        "soname": soname_match.group(1) if soname_match else None,
        "runpath": runpath_match.group(1) if runpath_match else None,
        "interpreter": interpreter_match.group(1) if interpreter_match else None,
        "build_id": build_id_match.group(1).lower() if build_id_match else None,
        "package": package,
    }


def validate_elf_closure(runtime: Path, catalogue: Path, config: dict, tools: dict) -> dict:
    catalogue_files = sorted(path for path in catalogue.rglob("*") if path.is_file())
    runtime_files = sorted(path for path in runtime.rglob("*") if path.is_file())
    provided = {path.name for path in catalogue_files}
    unresolved = []
    forbidden = []
    elf_entries = []
    python_closure: set[str] = {"ld-linux-x86-64.so.2"}
    catalogue_metadata: dict[str, dict] = {}
    for area, root, paths in (
        ("software", runtime, runtime_files),
        ("catalogue", catalogue, catalogue_files),
    ):
        for path in paths:
            if not is_elf(path):
                continue
            metadata = elf_metadata(path, tools)
            if "X86-64" not in str(metadata["machine"]):
                raise BuildFailure(f"Unexpected ELF architecture in {path}: {metadata['machine']}")
            missing = sorted(set(metadata["needed"]) - provided)
            if missing:
                unresolved.append(
                    {
                        "area": area,
                        "path": path.relative_to(root).as_posix(),
                        "needed": missing,
                    }
                )
            disallowed = sorted(set(metadata["needed"]) & set(config["forbidden_needed"]))
            if disallowed:
                forbidden.append(
                    {
                        "area": area,
                        "path": path.relative_to(root).as_posix(),
                        "needed": disallowed,
                    }
                )
            if area == "software" and (
                path == runtime / "bin" / "python3.13"
                or "lib-dynload" in path.parts
            ):
                python_closure.update(metadata["needed"])
            if area == "catalogue":
                catalogue_metadata[path.relative_to(root).as_posix()] = metadata
            elf_entries.append(
                {
                    "area": area,
                    "path": path.relative_to(root).as_posix(),
                    **metadata,
                }
            )
    if unresolved:
        raise BuildFailure("Unresolved native dependencies: " + json.dumps(unresolved))
    if forbidden:
        raise BuildFailure("Legacy split-glibc dependencies remain: " + json.dumps(forbidden))

    main = next(
        item for item in elf_entries if item["area"] == "software" and item["path"] == "bin/python3.13"
    )
    if main["interpreter"] != config["interpreter"]:
        raise BuildFailure(f"Python interpreter is {main['interpreter']}, expected {config['interpreter']}")
    if main["runpath"] != config["runpath"]:
        raise BuildFailure(f"Python RUNPATH is {main['runpath']}, expected {config['runpath']}")
    for item in elf_entries:
        if item["area"] == "software" and "lib-dynload/" in item["path"]:
            if item["runpath"] != config["runpath"]:
                raise BuildFailure(f"Extension has unexpected RUNPATH: {item['path']}")
    if any("$/the one" in str(item["runpath"]) for item in elf_entries):
        raise BuildFailure("An invalid legacy '$/the one' RUNPATH remains")

    python_closure = expand_native_closure(python_closure, catalogue_metadata)
    closure_bytes = sum(
        (catalogue / name).stat().st_size
        for name in python_closure
        if (catalogue / name).is_file()
    )
    return {
        "elf_files": len(elf_entries),
        "unresolved": [],
        "forbidden_needed": [],
        "python_native_closure": sorted(python_closure),
        "python_native_closure_bytes": closure_bytes,
        "entries": elf_entries,
    }


def verify_pillow_contract(modules: dict, catalogue: Path, tools: dict) -> dict:
    sha256_file.cache_clear()
    package = next(item for item in modules["packages"] if item["name"] == "Pillow")
    root = REPO / "source" / "catalogue" / "image"
    version_path = root / "PIL" / "_version.py"
    if not version_path.is_file():
        raise BuildFailure("The Pillow image catalogue is missing PIL/_version.py")
    text = version_path.read_text(encoding="utf-8")
    if package["version"] not in text:
        raise BuildFailure(f"Pillow catalogue is not version {package['version']}")
    native = sorted((root / "PIL").glob("*.cpython-313-*.so"))
    if not native:
        raise BuildFailure("The Pillow image catalogue has no cp313 native extensions")
    provided = {path.name for path in root.rglob("*") if path.is_file()}
    provided.update(path.name for path in catalogue.rglob("*") if path.is_file())
    elf_files = [path for path in root.rglob("*") if path.is_file() and is_elf(path)]
    unresolved = []
    needed_edges = 0
    for path in elf_files:
        metadata = elf_metadata(path, tools)
        if "X86-64" not in str(metadata["machine"]):
            raise BuildFailure(f"Unexpected Pillow ELF architecture: {path}")
        missing = sorted(set(metadata["needed"]) - provided)
        if missing:
            unresolved.append(
                {"path": path.relative_to(root).as_posix(), "needed": missing}
            )
        needed_edges += len(metadata["needed"])
    if unresolved:
        raise BuildFailure("Pillow native dependency closure is incomplete: " + json.dumps(unresolved))
    return {
        "version": package["version"],
        "path": relative_to_repo(root),
        "cp313_native_extensions": len(native),
        "tree": payload_inventory(root)["tree"],
        "elf": {
            "files": len(elf_files),
            "needed_edges": needed_edges,
            "unresolved": [],
        },
    }


def verify_distribution_records(runtime: Path) -> dict:
    site_packages = runtime / "lib" / "python3.13" / "site-packages"
    records = sorted(site_packages.glob("*.dist-info/RECORD"))
    expected = {"freetype_py-2.5.1", "pyroute2-0.9.4"}
    found = {record.parent.name.removesuffix(".dist-info") for record in records}
    if found != expected:
        raise BuildFailure(
            f"Installed distribution metadata changed: expected {sorted(expected)}, found {sorted(found)}"
        )
    hashed_entries = 0
    listed_entries = 0
    for record in records:
        with record.open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.reader(stream))
        for row in rows:
            if len(row) != 3:
                raise BuildFailure(f"Malformed wheel RECORD row in {record}: {row}")
            relative, digest_field, size_field = row
            target = (site_packages / relative).resolve()
            require_within(target, runtime)
            if not target.is_file():
                raise BuildFailure(f"Wheel RECORD references a missing file: {relative}")
            listed_entries += 1
            if digest_field:
                algorithm, separator, expected_digest = digest_field.partition("=")
                if separator != "=" or algorithm != "sha256":
                    raise BuildFailure(f"Unsupported wheel RECORD digest: {digest_field}")
                actual_digest = base64.urlsafe_b64encode(
                    bytes.fromhex(sha256_file(target))
                ).rstrip(b"=").decode("ascii")
                if actual_digest != expected_digest:
                    raise BuildFailure(f"Wheel RECORD hash mismatch: {relative}")
                if not size_field or target.stat().st_size != int(size_field):
                    raise BuildFailure(f"Wheel RECORD size mismatch: {relative}")
                hashed_entries += 1
    return {
        "distributions": sorted(found),
        "record_files": len(records),
        "listed_entries": listed_entries,
        "hashed_entries": hashed_entries,
    }


def compile_active_t1os_sources(
    runtime: Path, catalogue: Path, imports: dict, config: dict
) -> dict:
    sha256_file.cache_clear()
    contract = imports["active_t1os_sources"]
    paths: set[Path] = set()
    for pattern in contract["globs"]:
        paths.update(path for path in REPO.glob(pattern) if path.is_file())
    ordered = sorted(paths, key=lambda path: path.relative_to(REPO).as_posix())
    if len(ordered) != contract["expected_files"]:
        raise BuildFailure(
            f"Active T1OS Python source count changed: expected {contract['expected_files']}, "
            f"found {len(ordered)}"
        )
    source_records = []
    for path in ordered:
        root, relative = protected_root_for_source(path, config)
        source_records.append(
            {
                "source_path": path.relative_to(REPO).as_posix(),
                "deployed_path": (
                    root["destination"].rstrip("/") + "/" + relative.as_posix()
                ),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    script = r'''
import json
from pathlib import Path
import sys

records = json.loads(sys.argv[1])
for item in records:
    path = Path(item["source_path"])
    compile(path.read_bytes(), item["deployed_path"], "exec", dont_inherit=True)
print(len(records))
'''
    compile_records = [
        {
            "source_path": str(REPO / item["source_path"]),
            "deployed_path": item["deployed_path"],
        }
        for item in source_records
    ]
    environment = os.environ.copy()
    environment.update(
        {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONPATH": ""}
    )
    result = run(
        loader_command(
            runtime,
            catalogue,
            "-S",
            "-B",
            "-I",
            "-c",
            script,
            json.dumps(compile_records),
        ),
        env=environment,
    )
    if result.stdout.strip() != str(len(ordered)):
        raise BuildFailure("Target-Python source compilation returned unexpected output")
    digest = hashlib.sha256()
    for item in source_records:
        digest.update(
            (
                f"file\t{item['deployed_path']}\t{item['size']}\t{item['sha256']}\n"
            ).encode("utf-8")
        )
    return {
        "files": len(ordered),
        "records": source_records,
        "tree": {
            "algorithm": TREE_ALGORITHM,
            "files": len(source_records),
            "bytes": sum(item["size"] for item in source_records),
            "sha256": digest.hexdigest(),
        },
    }


def run_runtime_smoke(
    runtime: Path, catalogue: Path, config: dict, imports: dict, modules: dict
) -> dict:
    image_root = REPO / "source" / "catalogue" / "image"
    font = REPO / "resource" / "fonts" / "atkinsonhyperlegiblenext.ttf"
    if not font.is_file():
        raise BuildFailure(f"Smoke-test font is missing: {font}")
    direct = (
        imports["direct_standard_library"]
        + imports.get("supported_optional_standard_library", [])
    )
    required_packages = imports["required_system_packages"]
    absent = imports["intentionally_absent_modules"]
    expected_versions = {
        item["name"]: item["version"]
        for item in modules["packages"]
        if item["name"] in {"freetype-py", "pyroute2", "Pillow"}
    }
    script = r'''
import contextlib
import importlib
import importlib.metadata
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sys
import threading
import urllib.request

direct = json.loads(sys.argv[1])
required_packages = json.loads(sys.argv[2])
absent = json.loads(sys.argv[3])
expected_versions = json.loads(sys.argv[4])
image_root = Path(sys.argv[5])
font_path = sys.argv[6]
runtime_root = Path(sys.argv[7]).resolve()
expected_ca_file = sys.argv[8]
tls_fixture_ca = sys.argv[9]
tls_fixture_certificate = sys.argv[10]
tls_fixture_key = sys.argv[11]

for name in direct:
    importlib.import_module(name)
for name in required_packages:
    module = importlib.import_module(name)
    origin = Path(module.__file__).resolve()
    if runtime_root not in origin.parents:
        raise RuntimeError(f"{name} escaped the staged runtime: {origin}")
for name in absent:
    if importlib.util.find_spec(name) is not None:
        raise RuntimeError(f"unsupported extension is still importable: {name}")

if importlib.metadata.version("freetype-py") != expected_versions["freetype-py"]:
    raise RuntimeError("unexpected freetype-py version")
if importlib.metadata.version("pyroute2") != expected_versions["pyroute2"]:
    raise RuntimeError("unexpected pyroute2 version")

import ctypes
ctypes.CDLL(None)
import decimal
assert decimal.Decimal("1.25") * 2 == decimal.Decimal("2.50")
import hashlib
assert len(hashlib.pbkdf2_hmac("sha256", b"t1os", b"python", 2)) == 32
import ssl
configured_ca_file = os.environ.get("SSL_CERT_FILE")
if configured_ca_file != expected_ca_file:
    raise RuntimeError(
        f"unexpected default CA file: {configured_ca_file!r}; "
        f"expected {expected_ca_file!r}"
    )

# Exercise the same default HTTPS path used by urllib.request without relying
# on external DNS, networking, or a public certificate. The system default is
# first proved above, then replaced inside this smoke-test process by a private
# fixture CA so the target runtime must validate a real local certificate chain
# and hostname before accepting the response.
os.environ["SSL_CERT_FILE"] = tls_fixture_ca
server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
server_context.load_cert_chain(tls_fixture_certificate, tls_fixture_key)
listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("127.0.0.1", 0))
listener.listen(1)
listener.settimeout(5)
tls_server_errors = []

def serve_tls_fixture():
    try:
        connection, _ = listener.accept()
        with connection:
            with server_context.wrap_socket(connection, server_side=True) as tls:
                request = bytearray()
                while b"\r\n\r\n" not in request and len(request) < 16384:
                    block = tls.recv(4096)
                    if not block:
                        break
                    request.extend(block)
                if not request.startswith(b"GET "):
                    raise RuntimeError("TLS fixture did not receive an HTTP GET")
                payload = b"t1os-ca-verified"
                tls.sendall(
                    b"HTTP/1.1 200 OK\r\n"
                    + b"Content-Type: text/plain\r\n"
                    + b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n"
                    + b"Connection: close\r\n\r\n"
                    + payload
                )
    except BaseException as error:
        tls_server_errors.append(f"{type(error).__name__}: {error}")
    finally:
        listener.close()

tls_server = threading.Thread(target=serve_tls_fixture, daemon=True)
tls_server.start()
try:
    port = listener.getsockname()[1]
    with urllib.request.urlopen(f"https://localhost:{port}/", timeout=5) as response:
        tls_payload = response.read()
        if response.status != 200 or tls_payload != b"t1os-ca-verified":
            raise RuntimeError("verified TLS fixture returned an unexpected response")
finally:
    tls_server.join(5)
    with contextlib.suppress(OSError):
        listener.close()
if tls_server.is_alive():
    raise RuntimeError("verified TLS fixture server did not stop")
if tls_server_errors:
    raise RuntimeError("verified TLS fixture failed: " + "; ".join(tls_server_errors))

import uuid
assert uuid.UUID(str(uuid.uuid4())).version == 4
import zlib
assert zlib.decompress(zlib.compress(b"t1os")) == b"t1os"

import freetype
face = freetype.Face(font_path)
face.set_pixel_sizes(0, 20)
face.load_char("A", freetype.FT_LOAD_DEFAULT)
face.glyph.render(freetype.FT_RENDER_MODE_NORMAL)
if face.glyph.bitmap.width <= 0 or face.glyph.bitmap.rows <= 0:
    raise RuntimeError("freetype did not render a glyph")
freetype_version = ".".join(map(str, freetype.version()))

from pyroute2 import IPRoute
with IPRoute() as route:
    links = route.get_links()
    if not links or not route.link_lookup(ifname="lo"):
        raise RuntimeError("pyroute2 could not inspect the loopback link")
    route.get_addr()
    route.get_default_routes()

sys.path.insert(0, str(image_root))
from PIL import Image, features
if Image.__version__ != expected_versions["Pillow"]:
    raise RuntimeError(f"unexpected Pillow version: {Image.__version__}")
for image_format in ("PNG", "JPEG", "GIF", "BMP", "WEBP"):
    if image_format == "WEBP" and not features.check("webp"):
        raise RuntimeError("Pillow lacks required WebP support")
    output = io.BytesIO()
    Image.new("RGB", (3, 2), (12, 34, 56)).save(output, image_format)
    output.seek(0)
    with Image.open(output) as decoded:
        decoded.load()
        if decoded.size != (3, 2):
            raise RuntimeError(f"Pillow {image_format} round trip failed")

import datetime
if datetime.datetime.__name__ != "atreyandatetime":
    raise RuntimeError("legacy AE sitecustomize was not loaded")

print(json.dumps({
    "python": sys.version.split()[0],
    "openssl": ssl.OPENSSL_VERSION,
    "default_ca_file": configured_ca_file,
    "verified_tls": True,
    "sqlite": importlib.import_module("sqlite3").sqlite_version,
    "freetype": freetype_version,
    "pyroute_links": len(links),
    "pillow": Image.__version__,
    "sitecustomize": datetime.datetime.__name__,
}, sort_keys=True))
'''
    library_path = os.pathsep.join(
        [str(catalogue), str(image_root), str(image_root / "pillow.libs")]
    )
    command = [
        str(catalogue / "ld-linux-x86-64.so.2"),
        "--library-path",
        library_path,
        str(runtime / "bin" / "python3.13"),
        "-B",
        "-I",
        "-c",
        script,
        json.dumps(direct),
        json.dumps(required_packages),
        json.dumps(absent),
        json.dumps(expected_versions),
        str(image_root),
        str(font),
        str(runtime),
        config["ssl"]["default_ca_file"],
        str(TLS_FIXTURE_CA),
        str(TLS_FIXTURE_CERTIFICATE),
        str(TLS_FIXTURE_KEY),
    ]
    environment = os.environ.copy()
    environment.pop("SSL_CERT_FILE", None)
    environment.pop("SSL_CERT_DIR", None)
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": "",
            "NO_PROXY": "localhost,127.0.0.1",
            "no_proxy": "localhost,127.0.0.1",
        }
    )
    result = run(command, env=environment)
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise BuildFailure(f"Runtime smoke test returned invalid output: {result.stdout}") from error


def validate_runtime(
    runtime: Path,
    catalogue: Path,
    config: dict,
    imports: dict,
    modules: dict,
    tools: dict,
) -> dict:
    for root in (runtime, catalogue):
        for path in root.rglob("*"):
            if path.is_symlink():
                raise BuildFailure(f"Runtime payload contains a symbolic link: {path}")
    python = runtime / "bin" / "python3.13"
    if not is_elf(python):
        raise BuildFailure("Staged Python executable is missing or not ELF")
    for extension in config["unsupported_extensions"]:
        if (runtime / "lib" / "python3.13" / "lib-dynload" / extension).exists():
            raise BuildFailure(f"Unsupported extension remains: {extension}")
    closure = validate_elf_closure(runtime, catalogue, config, tools)
    pillow = verify_pillow_contract(modules, catalogue, tools)
    distributions = verify_distribution_records(runtime)
    t1os_sources = compile_active_t1os_sources(runtime, catalogue, imports, config)
    smoke = run_runtime_smoke(runtime, catalogue, config, imports, modules)
    return {
        "elf": closure,
        "pillow": pillow,
        "distributions": distributions,
        "t1os_sources": t1os_sources,
        "smoke": smoke,
    }


def build_manifest(
    runtime: Path,
    catalogue: Path,
    config: dict,
    inputs: dict,
    modules: dict,
    tools: dict,
    extraction: dict,
    patching: dict,
    catalogue_build: dict,
    installed_packages: list[dict],
    installed_t1os: list[dict],
    verification: dict,
) -> dict:
    policy, _ = profiled_python_policy(config)
    software = payload_inventory(
        runtime,
        skip_files={MANIFEST_NAME},
        executable_prefixes=("bin/",),
    )
    catalogue_inventory = payload_inventory(catalogue)
    protected_roots = protected_external_root_inventories(config)
    image_catalogue = next(
        item for item in protected_roots if item["name"] == "image_catalogue"
    )
    if image_catalogue["tree"] != verification["pillow"]["tree"]:
        raise BuildFailure(
            "Pillow verification and protected image-catalogue inventory disagree"
        )
    deployed_files = {}
    for root in protected_roots:
        for item in root["files"]:
            deployed_path = root["destination"].rstrip("/") + "/" + item["path"]
            if deployed_path in deployed_files:
                raise BuildFailure(
                    f"Protected external roots overlap at deployed path {deployed_path}"
                )
            deployed_files[deployed_path] = item
    for item in verification["t1os_sources"]["records"]:
        deployed = deployed_files.get(item["deployed_path"])
        if deployed is None or any(
            item[field] != deployed[field] for field in ("size", "sha256")
        ):
            raise BuildFailure(
                "Compiled T1OS source identities disagree with the protected-root inventory: "
                + item["deployed_path"]
            )
    return {
        "format": 1,
        "state": "verified",
        "component": "python",
        "release": config["release"],
        "python_version": config["python_version"],
        "python_abi": config["python_abi"],
        "architecture": config["architecture"],
        "build_mode": config["source_mode"],
        "runtime_path": config["runtime_path"],
        "catalogue_path": config["catalogue_path"],
        "source": {
            "cpython_evidence": inputs["upstream"]["cpython"],
            "portable_runtime": inputs["upstream"]["portable_runtime"],
            "legacy_native_catalogue": inputs["legacy"]["native_catalogue"],
            "build_definitions": build_definition_records(),
            "release_lock": relative_to_repo(RELEASE_LOCK),
        },
        "tools": {
            "patchelf": tools["patchelf_version"],
            "readelf": tools["readelf_version"],
            "builder_python": sys.version.split()[0],
        },
        "transformations": {
            "archive_extraction": extraction,
            "slim_runtime": config["slim_runtime"],
            "unsupported_extensions_removed": config["unsupported_extensions"],
            "unsupported_python_paths_removed": config["unsupported_python_paths"],
            "elf_relocation": patching,
            "catalogue": catalogue_build,
            "bytecode": config["bytecode"],
            "post_install": config["post_install"],
        },
        "system_packages": installed_packages,
        "t1os_components": installed_t1os,
        "install_policy": {
            "owner": 0,
            "group": 0,
            "directory_mode": "0755",
            "regular_file_mode": "0444",
            "executable_and_elf_mode": "0555",
            "profiled_python_mode": "0555",
            "runtime_mutation_policy": "T1OS LSM denies protected system-tree writes in Master role and permits deliberate maintenance in Architect role",
            "timestamps": "not security-significant; deployment normalizes them",
        },
        "profiled_python_entrypoints": policy,
        "software": {"destination": config["runtime_path"], **software},
        "catalogue": {"destination": config["catalogue_path"], **catalogue_inventory},
        "protected_external_roots": protected_roots,
        "verification": verification,
    }


def promotion_entries() -> list[dict]:
    return [
        {
            "name": "software",
            "destination": SOFTWARE_DESTINATION,
            "new": SOFTWARE_DESTINATION.parent / ".python.release-new",
            "old": SOFTWARE_DESTINATION.parent / ".python.release-old",
        },
        {
            "name": "catalogue",
            "destination": CATALOGUE_DESTINATION,
            "new": CATALOGUE_DESTINATION.parent / ".python.release-new",
            "old": CATALOGUE_DESTINATION.parent / ".python.release-old",
        },
    ]


def clear_promotion_journal() -> None:
    if PROMOTION_JOURNAL.exists():
        require_within(PROMOTION_JOURNAL, PYTHON_SOURCE)
        PROMOTION_JOURNAL.unlink()


def recover_incomplete_promotion() -> None:
    entries = promotion_entries()
    if not PROMOTION_JOURNAL.is_file():
        leftovers = [
            path for item in entries for path in (item["new"], item["old"]) if path.exists()
        ]
        if leftovers:
            raise BuildFailure(
                "Unjournaled Python promotion remnants require manual inspection: "
                + ", ".join(map(str, leftovers))
            )
        return
    journal = load_json(PROMOTION_JOURNAL)
    state = journal.get("state")
    if state == "committed":
        for item in entries:
            if item["old"].exists():
                remove_tree(item["old"], item["old"].parent)
            if item["new"].exists():
                remove_tree(item["new"], item["new"].parent)
        clear_promotion_journal()
        return
    existed = journal.get("destinations_existed", {})
    for item in entries:
        destination, new, old = item["destination"], item["new"], item["old"]
        if old.exists():
            if destination.exists():
                remove_tree(destination, destination.parent)
            old.rename(destination)
        elif state == "backup_started" and not existed.get(item["name"], False):
            if destination.exists():
                remove_tree(destination, destination.parent)
        if new.exists():
            remove_tree(new, new.parent)
    clear_promotion_journal()


def promote_release_pair(runtime_stage: Path, catalogue_stage: Path) -> None:
    recover_incomplete_promotion()
    stages = {"software": runtime_stage, "catalogue": catalogue_stage}
    entries = promotion_entries()
    journal = {
        "format": 1,
        "component": "python-promotion",
        "state": "preparing",
        "destinations_existed": {
            item["name"]: item["destination"].exists() for item in entries
        },
    }
    write_json(PROMOTION_JOURNAL, journal)
    try:
        for item in entries:
            shutil.copytree(stages[item["name"]], item["new"], copy_function=shutil.copy2)
        journal["state"] = "backup_started"
        write_json(PROMOTION_JOURNAL, journal)
        for item in entries:
            if item["destination"].exists():
                item["destination"].rename(item["old"])
        for item in entries:
            item["new"].rename(item["destination"])
        manifest_path = SOFTWARE_DESTINATION / MANIFEST_NAME
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise BuildFailure("Promoted Python manifest is not a regular file")
        manifest = load_json(manifest_path)
        compare_manifest_inventory(
            SOFTWARE_DESTINATION,
            manifest["software"],
            skip_manifest=True,
            executable_prefixes=("bin/",),
        )
        compare_manifest_inventory(CATALOGUE_DESTINATION, manifest["catalogue"])
        release = load_json(RELEASE_LOCK)
        verify_release_outputs(manifest, SOFTWARE_DESTINATION, release)
        journal["state"] = "committed"
        write_json(PROMOTION_JOURNAL, journal)
    except Exception:
        recover_incomplete_promotion()
        raise
    recover_incomplete_promotion()


def build_runtime(*, offline: bool, stage_only: bool, refresh_release_lock: bool) -> dict:
    sha256_file.cache_clear()
    runtime_config, inputs, modules, imports = verify_inputs()
    verify_provenance_release(runtime_config)
    tools = require_linux_tools()
    if refresh_release_lock:
        if not stage_only:
            raise BuildFailure("A release lock may only be created from a stage-only build")
        if RELEASE_LOCK.is_file() and load_json(RELEASE_LOCK).get("release") == runtime_config["release"]:
            raise BuildFailure("Refusing to replace the lock for an existing release identifier")
        release_lock = None
    else:
        release_lock = verify_release_lock_sources(runtime_config, tools)
    recover_incomplete_promotion()
    remove_tree(STAGE_ROOT, DEVELOPMENT_ROOT) if STAGE_ROOT.exists() else None
    runtime_stage = STAGE_ROOT / "software" / "python"
    catalogue_stage = STAGE_ROOT / "catalogue" / "python"
    runtime_stage.mkdir(parents=True)
    portable = verify_locked_file(
        inputs["upstream"]["portable_runtime"], "Portable Python runtime"
    )
    extraction = safe_extract_runtime(
        portable,
        runtime_config["portable_archive_root"],
        runtime_stage,
    )
    remove_generated_bytecode(runtime_stage)
    slim_runtime(runtime_stage, runtime_config)
    patching = patch_runtime(runtime_stage, runtime_config, tools)
    catalogue_build = build_catalogue(catalogue_stage, runtime_config, inputs)
    installed_packages = install_system_modules(
        runtime_stage, modules, runtime_config, offline=offline
    )
    installed_t1os = install_t1os_files(runtime_stage, modules)
    remove_generated_bytecode(runtime_stage)
    compile_checked_hash_bytecode(runtime_stage, catalogue_stage, runtime_config)
    verification = validate_runtime(
        runtime_stage,
        catalogue_stage,
        runtime_config,
        imports,
        modules,
        tools,
    )
    manifest = build_manifest(
        runtime_stage,
        catalogue_stage,
        runtime_config,
        inputs,
        modules,
        tools,
        extraction,
        patching,
        catalogue_build,
        installed_packages,
        installed_t1os,
        verification,
    )
    write_json(runtime_stage / MANIFEST_NAME, manifest)
    if refresh_release_lock:
        release_lock = create_release_lock(
            runtime_config,
            tools,
            manifest,
            patching,
            sha256_file(runtime_stage / MANIFEST_NAME),
        )
        write_json(RELEASE_LOCK, release_lock)
        sha256_file.cache_clear()
        verify_release_outputs(manifest, runtime_stage, release_lock)
    else:
        verify_release_outputs(manifest, runtime_stage, release_lock)
    report = {
        "format": 1,
        "component": "python-build",
        "release": runtime_config["release"],
        "stage_only": stage_only,
        "software_tree": manifest["software"]["tree"],
        "catalogue_tree": manifest["catalogue"]["tree"],
        "protected_external_roots": {
            item["name"]: item["tree"]
            for item in manifest["protected_external_roots"]
        },
        "python_sha256": patching["python_sha256"],
        "verification": verification["smoke"],
        "release_lock_created": refresh_release_lock,
    }
    write_json(BUILD_REPORT, report)
    if not stage_only:
        promote_release_pair(runtime_stage, catalogue_stage)
    return report


def inventory_record_delta(expected: list[dict], actual: list[dict]) -> dict:
    expected_map = {item["path"]: item for item in expected}
    actual_map = {item["path"]: item for item in actual}
    if len(expected_map) != len(expected) or len(actual_map) != len(actual):
        raise BuildFailure("An install inventory contains duplicate paths")
    expected_paths = set(expected_map)
    actual_paths = set(actual_map)
    return {
        "missing": sorted(expected_paths - actual_paths),
        "extra": sorted(actual_paths - expected_paths),
        "changed": sorted(
            path
            for path in expected_paths & actual_paths
            if expected_map[path] != actual_map[path]
        ),
    }


def compare_manifest_inventory(
    root: Path,
    expected: dict,
    *,
    skip_manifest: bool = False,
    executable_prefixes: tuple[str, ...] = (),
    exclude_generated_bytecode: bool = False,
    root_name: str | None = None,
    profiled: set[tuple[str, str]] | None = None,
) -> None:
    actual = payload_inventory(
        root,
        skip_files={MANIFEST_NAME} if skip_manifest else set(),
        executable_prefixes=executable_prefixes,
        exclude_generated_bytecode=exclude_generated_bytecode,
        root_name=root_name,
        profiled=profiled,
    )
    for field in ("directories", "files"):
        if actual[field] != expected.get(field):
            delta = inventory_record_delta(expected.get(field, []), actual[field])
            raise BuildFailure(
                f"Canonical {field} below {root} differ from manifest: {json.dumps(delta)}"
            )
    if actual["tree"] != expected.get("tree"):
        raise BuildFailure(f"Canonical install tree below {root} differs from manifest")


def compare_protected_external_roots(manifest: dict) -> None:
    sha256_file.cache_clear()
    config = load_json(RUNTIME_CONFIG)
    _, profiled = profiled_python_policy(config)
    roots = manifest.get("protected_external_roots")
    if not isinstance(roots, list):
        raise BuildFailure("Python manifest has no protected external-root inventories")
    metadata = [
        {
            key: item.get(key)
            for key in (
                "name",
                "source",
                "destination",
                "exclude_generated_bytecode",
            )
        }
        for item in roots
    ]
    if metadata != EXPECTED_PROTECTED_EXTERNAL_ROOTS:
        raise BuildFailure("Python manifest protected-root mapping is not canonical")
    for item in roots:
        compare_manifest_inventory(
            resolve_repo_path(item["source"]),
            item,
            exclude_generated_bytecode=item["exclude_generated_bytecode"],
            root_name=item["name"],
            profiled=profiled,
        )


def verify_canonical(*, full: bool = True) -> dict:
    recover_incomplete_promotion()
    sha256_file.cache_clear()
    runtime_config, _, modules, imports = verify_inputs()
    tools = require_linux_tools()
    release_lock = verify_release_lock_sources(runtime_config, tools)
    manifest_path = SOFTWARE_DESTINATION / MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise BuildFailure(f"Canonical Python manifest is missing: {manifest_path}")
    manifest = load_json(manifest_path)
    if manifest.get("state") != "verified" or manifest.get("release") != runtime_config["release"]:
        raise BuildFailure("Canonical Python manifest does not describe the configured verified release")
    if (
        manifest.get("software", {}).get("destination") != runtime_config["runtime_path"]
        or manifest.get("catalogue", {}).get("destination")
        != runtime_config["catalogue_path"]
    ):
        raise BuildFailure("Canonical Python manifest has non-canonical install destinations")
    compare_manifest_inventory(
        SOFTWARE_DESTINATION,
        manifest["software"],
        skip_manifest=True,
        executable_prefixes=("bin/",),
    )
    compare_manifest_inventory(CATALOGUE_DESTINATION, manifest["catalogue"])
    verify_release_outputs(manifest, SOFTWARE_DESTINATION, release_lock)
    verification = (
        validate_runtime(
            SOFTWARE_DESTINATION,
            CATALOGUE_DESTINATION,
            runtime_config,
            imports,
            modules,
            tools,
        )
        if full
        else manifest["verification"]
    )
    if full:
        for field, label in (
            ("t1os_sources", "active T1OS source compilation"),
            ("pillow", "Pillow ABI verification"),
        ):
            if verification[field] != manifest["verification"][field]:
                raise BuildFailure(f"Fresh {label} differs from the frozen manifest")
    return {
        "release": manifest["release"],
        "software_files": len(manifest["software"]["files"]),
        "catalogue_files": len(manifest["catalogue"]["files"]),
        "protected_external_roots": len(manifest["protected_external_roots"]),
        "smoke": verification["smoke"],
    }


def verify_frozen_deployment_payload() -> dict:
    """Verify only bytes owned by the managed-Python deployment.

    Active T1OS applications, boot sources, and VirtualBox helpers are recorded
    as release-time compatibility evidence, but they are not Python payloads
    and must not prevent a later deployment of an already-frozen release.
    """

    recover_incomplete_promotion()
    sha256_file.cache_clear()
    release = load_json(RELEASE_LOCK)
    if not release.get("immutable"):
        raise BuildFailure("The managed Python release lock is not immutable")
    manifest_path = SOFTWARE_DESTINATION / MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise BuildFailure(f"Canonical Python manifest is missing: {manifest_path}")
    manifest = load_json(manifest_path)
    if (
        manifest.get("state") != "verified"
        or manifest.get("release") != release.get("release")
    ):
        raise BuildFailure("Canonical Python manifest and frozen release disagree")

    compare_manifest_inventory(
        SOFTWARE_DESTINATION,
        manifest["software"],
        skip_manifest=True,
        executable_prefixes=("bin/",),
    )
    compare_manifest_inventory(CATALOGUE_DESTINATION, manifest["catalogue"])

    expected = release.get("outputs", {})
    if manifest["software"]["tree"] != expected.get("software_tree"):
        raise BuildFailure("Managed Python software differs from the frozen release")
    if manifest["catalogue"]["tree"] != expected.get("catalogue_tree"):
        raise BuildFailure("Managed Python catalogue differs from the frozen release")
    if sha256_file(SOFTWARE_DESTINATION / "bin" / "python3.13") != expected.get(
        "python_sha256"
    ):
        raise BuildFailure("Managed Python executable differs from the frozen release")
    if sha256_file(manifest_path) != expected.get("manifest_sha256"):
        raise BuildFailure("Managed Python manifest differs from the frozen release")

    manifest_external = [
        {
            key: item[key]
            for key in (
                "name",
                "source",
                "destination",
                "exclude_generated_bytecode",
                "tree",
            )
        }
        for item in manifest.get("protected_external_roots", [])
    ]
    if manifest_external != release.get("protected_external_roots"):
        raise BuildFailure("Frozen external compatibility evidence differs")
    image_entries = [
        item
        for item in manifest.get("protected_external_roots", [])
        if item.get("name") == "image_catalogue"
    ]
    if len(image_entries) != 1:
        raise BuildFailure("Managed Python has no unique image-package catalogue")
    image_entry = image_entries[0]
    if (
        image_entry.get("source") != "source/catalogue/image"
        or image_entry.get("destination") != "/the one/catalogue/image"
        or image_entry.get("exclude_generated_bytecode") is not False
    ):
        raise BuildFailure("Managed Python image-package mapping is not canonical")
    compare_manifest_inventory(resolve_repo_path(image_entry["source"]), image_entry)

    return {
        "release": manifest["release"],
        "software_files": len(manifest["software"]["files"]),
        "catalogue_files": len(manifest["catalogue"]["files"]),
        "image_package_files": len(image_entry["files"]),
        "python_sha256": expected["python_sha256"],
        "manifest_sha256": expected["manifest_sha256"],
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="verify and normalize legacy evidence")
    audit.add_argument("--write", action="store_true", help="write the canonical provenance report")
    audit.add_argument("--offline", action="store_true", help="do not download missing locked wheels")

    build = subparsers.add_parser("build", help="construct and validate release zero")
    build.add_argument("--offline", action="store_true", help="do not download missing locked wheels")
    build.add_argument("--stage-only", action="store_true", help="do not promote the verified stage")
    build.add_argument(
        "--refresh-release-lock",
        action="store_true",
        help="create the immutable output lock; requires --stage-only and a new release identifier",
    )

    subparsers.add_parser("verify", help="verify the canonical source payload")
    subparsers.add_parser(
        "verify-deployment",
        help="verify only the frozen managed-Python deployment payload",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        if arguments.command == "audit":
            result = audit_evidence(write=arguments.write, offline=arguments.offline)
        elif arguments.command == "build":
            result = build_runtime(
                offline=arguments.offline,
                stage_only=arguments.stage_only,
                refresh_release_lock=arguments.refresh_release_lock,
            )
        elif arguments.command == "verify":
            result = verify_canonical()
        else:
            result = verify_frozen_deployment_payload()
    except BuildFailure as error:
        print(f"python runtime: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
