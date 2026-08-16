#!/usr/bin/env python3
"""Promote and verify the verified CPython 3.14.7 payload used by T1OS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys


REPO = Path(__file__).resolve().parents[1]
CANDIDATE_ROOT = REPO / "development" / "python 3.14 candidate" / "t1os"
CANDIDATE_MANIFEST = CANDIDATE_ROOT / "manifest.json"
CANDIDATE_BOOT_LOCK = CANDIDATE_ROOT / "boot-release.json"
RUNTIME_CONFIG = REPO / "source" / "python" / "build" / "runtime.json"
SOFTWARE_DESTINATION = REPO / "source" / "software" / "python"
CATALOGUE_DESTINATION = REPO / "source" / "catalogue" / "python"
IMAGE_DESTINATION = REPO / "source" / "catalogue" / "image"
RELEASE_LOCK = REPO / "source" / "python" / "locks" / "release.json"
PROMOTION_ROOT = REPO / "development" / "python 3.14 promotion"
STAGE_ROOT = PROMOTION_ROOT / "stage"
ARCHIVE_ROOT = PROMOTION_ROOT / "archived-3.14.7-t1os.61"
JOURNAL = PROMOTION_ROOT / "promotion-journal.json"
RELEASE = "3.14.7-t1os.62"
VERSION = "3.14.7"
ABI = "cp314"
MAX_RETAINED_CANDIDATES = 2
INSTALL_TREE_ALGORITHM = "t1os-install-tree-sha256-v2"
PROFILED_SHEBANG = b'#!"/the one/software/python/bin/python" -B\n'


class PromotionFailure(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PromotionFailure(f"Could not read JSON {path}: {error}") from error


def write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def candidate_archive_key(path: Path) -> tuple[int, int, int, int]:
    match = re.fullmatch(
        r"archived-(\d+)\.(\d+)\.(\d+)-t1os\.(\d+)", path.name
    )
    if match is None or not path.is_dir() or path.is_symlink():
        raise PromotionFailure(f"Unsafe Python candidate archive: {path}")
    expected_release = path.name.removeprefix("archived-")
    release = read_json(path / "release.json")
    if release.get("release") != expected_release:
        raise PromotionFailure(
            f"Python candidate archive identity differs: {path}"
        )
    return tuple(int(part) for part in match.groups())


def prune_candidate_archives(retain: int) -> None:
    if retain < 0:
        raise PromotionFailure("Python candidate retention cannot be negative")
    if not PROMOTION_ROOT.exists():
        return
    archives = [
        path
        for path in PROMOTION_ROOT.iterdir()
        if path.name.startswith("archived-")
    ]
    ordered = sorted(archives, key=candidate_archive_key, reverse=True)
    for archive in ordered[retain:]:
        def remove_readonly(function, blocked_path, _error) -> None:
            blocked = Path(blocked_path)
            mode = blocked.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise PromotionFailure(
                    f"Symbolic link entered Python candidate archive: {blocked}"
                )
            writable_mode = mode | stat.S_IWUSR
            if stat.S_ISDIR(mode):
                writable_mode |= stat.S_IXUSR
            os.chmod(blocked, writable_mode)
            function(blocked)

        try:
            shutil.rmtree(archive, onexc=remove_readonly)
        except OSError as error:
            raise PromotionFailure(
                f"Could not prune Python candidate archive {archive}: {error}"
            ) from error


def is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"\x7fELF"
    except OSError as error:
        raise PromotionFailure(f"Could not inspect {path}: {error}") from error


def ignored_generated(relative: Path) -> bool:
    return (
        "__pycache__" in relative.parts
        or relative.suffix in {".pyc", ".pyo"}
    )


def profiled_python_policy(config: dict) -> tuple[dict, set[tuple[str, str]]]:
    policy = config.get("profiled_python_entrypoints")
    if not isinstance(policy, dict) or set(policy) != {
        "format", "owner", "group", "install_mode", "shebang", "entries"
    }:
        raise PromotionFailure("Profiled Python entrypoint policy is malformed")
    if (
        policy["format"] != 1
        or policy["owner"] != 0
        or policy["group"] != 0
        or policy["install_mode"] != "0555"
        or policy["shebang"] != PROFILED_SHEBANG.decode("ascii")
        or not isinstance(policy["entries"], list)
        or not policy["entries"]
    ):
        raise PromotionFailure("Profiled Python entrypoint policy is not fail-closed")
    roots = {
        item["name"]: item
        for item in config.get("protected_external_roots", [])
        if isinstance(item, dict)
    }
    identities: set[tuple[str, str]] = set()
    destinations: set[str] = set()
    ordered_destinations: list[str] = []
    for entry in policy["entries"]:
        if not isinstance(entry, dict) or set(entry) != {"root", "path", "destination"}:
            raise PromotionFailure("Profiled Python entrypoint record is malformed")
        root_name = entry["root"]
        relative = entry["path"]
        destination = entry["destination"]
        if root_name not in roots or not isinstance(relative, str) or not isinstance(destination, str):
            raise PromotionFailure("Profiled Python entrypoint identity is malformed")
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
            raise PromotionFailure(f"Unsafe profiled Python entrypoint: {relative!r}")
        expected_destination = roots[root_name]["destination"].rstrip("/") + "/" + relative
        if destination != expected_destination:
            raise PromotionFailure(f"Profiled Python destination differs: {destination}")
        identity = (root_name, relative)
        if identity in identities or destination in destinations:
            raise PromotionFailure(f"Duplicate profiled Python entrypoint: {destination}")
        source = REPO / roots[root_name]["source"] / Path(*parsed.parts)
        try:
            mode = source.lstat().st_mode
            payload = source.read_bytes()
        except OSError as error:
            raise PromotionFailure(
                f"Could not inspect profiled Python entrypoint {source}: {error}"
            ) from error
        if source.is_symlink() or not stat.S_ISREG(mode):
            raise PromotionFailure(f"Profiled Python entrypoint is not regular: {source}")
        if payload.startswith(b"\xef\xbb\xbf") or not payload.startswith(PROFILED_SHEBANG):
            raise PromotionFailure(
                f"Profiled Python entrypoint lacks the exact byte-0 LF shebang: {source}"
            )
        identities.add(identity)
        destinations.add(destination)
        ordered_destinations.append(destination)
    if ordered_destinations != sorted(ordered_destinations):
        raise PromotionFailure("Profiled Python entrypoint inventory is not ordered")
    return policy, identities


def install_tree_summary(directories: list[dict], files: list[dict]) -> dict:
    digest = hashlib.sha256()
    for item in directories:
        digest.update(
            f"directory\t{item['path']}\t{item['install_mode']}\n".encode()
        )
    for item in files:
        digest.update(
            (
                f"file\t{item['path']}\t{item['size']}\t{item['sha256']}\t"
                f"{item['install_mode']}\n"
            ).encode()
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
    exclude_generated_bytecode: bool = False,
    root_name: str | None = None,
    profiled: set[tuple[str, str]] | None = None,
) -> dict:
    if not root.is_dir():
        raise PromotionFailure(f"Payload directory is missing: {root}")
    skip_files = set() if skip_files is None else set(skip_files)
    directories = [{"path": ".", "install_mode": "0755"}]
    files: list[dict] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative_path = path.relative_to(root)
        relative = relative_path.as_posix()
        if any(character in relative for character in "\t\r\n"):
            raise PromotionFailure(f"Forbidden payload path: {path}")
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise PromotionFailure(f"Symbolic links are forbidden: {path}")
        if exclude_generated_bytecode and ignored_generated(relative_path):
            continue
        if stat.S_ISDIR(mode):
            directories.append({"path": relative, "install_mode": "0755"})
            continue
        if not stat.S_ISREG(mode):
            raise PromotionFailure(f"Special payload file is forbidden: {path}")
        if relative in skip_files:
            continue
        is_profiled = (
            root_name is not None
            and profiled is not None
            and (root_name, relative) in profiled
        )
        executable = is_profiled or (
            not relative.endswith(".py") and is_elf(path)
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


def verify_candidate_inventory(
    candidate: dict, profiled: set[tuple[str, str]]
) -> None:
    payloads = candidate.get("payloads")
    if not isinstance(payloads, dict):
        raise PromotionFailure("Candidate payload inventories are missing")
    areas = {
        "software": CANDIDATE_ROOT / "software" / "python",
        "catalogue": CANDIDATE_ROOT / "catalogue" / "python",
        "image": CANDIDATE_ROOT / "catalogue" / "image",
        "build_software": CANDIDATE_ROOT / "build",
        "boot": CANDIDATE_ROOT / "boot",
        "virtualbox_software": CANDIDATE_ROOT / "software" / "virtualbox",
    }
    for name, root in areas.items():
        records = payloads.get(name)
        if not isinstance(records, list) or not records:
            raise PromotionFailure(f"Candidate inventory is missing: {name}")
        expected = {str(item.get("path")): item for item in records}
        actual = {
            path.relative_to(root).as_posix(): path
            for path in root.rglob("*")
            if path.is_file()
            and not (name == "software" and path.relative_to(root).as_posix() == "manifest.json")
        }
        if set(actual) != set(expected):
            missing = sorted(set(expected) - set(actual))[:5]
            extra = sorted(set(actual) - set(expected))[:5]
            raise PromotionFailure(
                f"Candidate topology differs for {name}; missing={missing}, extra={extra}"
            )
        for relative, path in actual.items():
            record = expected[relative]
            is_profiled = (name, relative) in profiled
            executable = is_profiled or (
                not relative.endswith(".py")
                and ((name == "software" and relative.startswith("bin/")) or is_elf(path))
            )
            expected_mode = "0555" if executable else "0444"
            if (
                path.stat().st_size != int(record.get("size", -1))
                or sha256_file(path) != record.get("sha256")
                or record.get("install_mode") != expected_mode
            ):
                raise PromotionFailure(f"Candidate file differs: {name}/{relative}")


def load_verified_candidate() -> tuple[dict, str]:
    candidate = read_json(CANDIDATE_MANIFEST)
    boot_lock = read_json(CANDIDATE_BOOT_LOCK)
    config = read_json(RUNTIME_CONFIG)
    policy, profiled = profiled_python_policy(config)
    digest = sha256_file(CANDIDATE_MANIFEST)
    if (
        candidate.get("component") != "t1os-python-candidate"
        or candidate.get("candidate_release") != "3.14.7-t1os-candidate.37"
        or candidate.get("python_version") != VERSION
        or candidate.get("python_abi") != ABI
        or candidate.get("promotable") is not False
        or candidate.get("profiled_python_entrypoints") != policy
        or candidate.get("install_policy", {}).get("owner") != 0
        or candidate.get("install_policy", {}).get("group") != 0
        or candidate.get("install_policy", {}).get("directory_mode") != "0755"
        or candidate.get("install_policy", {}).get("regular_file_mode") != "0444"
        or candidate.get("install_policy", {}).get("profiled_python_mode") != "0555"
        or boot_lock.get("component") != "t1os-python-candidate-boot"
        or boot_lock.get("release") != candidate.get("candidate_release")
        or boot_lock.get("manifest_sha256") != digest
        or candidate.get("verification", {}).get("smoke", {}).get("python") != VERSION
    ):
        raise PromotionFailure("The Python 3.14.7 candidate is not the verified input")
    verify_candidate_inventory(candidate, profiled)
    return candidate, digest


def protected_external_roots(
    config: dict, *, source_overrides: dict[str, Path] | None = None
) -> list[dict]:
    source_overrides = {} if source_overrides is None else source_overrides
    _, profiled = profiled_python_policy(config)
    result = []
    for item in config.get("protected_external_roots", []):
        source = source_overrides.get(item["name"], REPO / str(item["source"]))
        inventory = payload_inventory(
            source,
            exclude_generated_bytecode=bool(item["exclude_generated_bytecode"]),
            root_name=item["name"],
            profiled=profiled,
        )
        result.append({**item, **inventory})
    if len(result) != 4:
        raise PromotionFailure("Exactly four protected external roots are required")
    return result


def build_definition_records() -> list[dict]:
    relative_paths = [
        "development/promote python 3.14 runtime.py",
        "development/package python 3.14 candidate.py",
        "scripts/build python runtime.ps1",
        "scripts/build python 3.14 candidate.ps1",
        "scripts/package python 3.14 candidate.ps1",
        "source/entry/init/init hardware.sh",
        "source/entry/init/angel recovery.sh",
        "source/entry/kernel/t1os_lsm.c",
        "scripts/build hardware initramfs.ps1",
        "scripts/test hardware build.ps1",
        "scripts/test python runtime.ps1",
        "scripts/validate profiled python entrypoints.py",
        "scripts/validate profiled python entrypoints.ps1",
        "source/python/tests/test_python_packages.py",
        "source/python/packages/python-command.c",
        "source/python/build/runtime.json",
        "source/python/locks/python-3.14.7-candidate.json",
    ]
    records = []
    for relative in relative_paths:
        path = REPO / relative
        if not path.is_file():
            raise PromotionFailure(f"Build definition is missing: {relative}")
        records.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return records


def build_manifest(
    candidate: dict,
    candidate_digest: str,
    software_root: Path,
    catalogue_root: Path,
    image_root: Path,
) -> dict:
    config = read_json(RUNTIME_CONFIG)
    policy, _ = profiled_python_policy(config)
    software = payload_inventory(software_root, skip_files={"manifest.json"})
    catalogue = payload_inventory(catalogue_root)
    software["destination"] = "/the one/software/python"
    catalogue["destination"] = "/the one/catalogue/python"
    source_archive = candidate.get("source_archive", {})
    return {
        "format": 1,
        "state": "verified",
        "component": "python",
        "release": RELEASE,
        "python_version": VERSION,
        "python_abi": ABI,
        "architecture": "x86_64",
        "build_mode": "verified-source-build",
        "runtime_path": "/the one/software/python",
        "catalogue_path": "/the one/catalogue/python",
        "release_lock": "source/python/locks/release.json",
        "source": {
            "archive": source_archive,
            "candidate_release": candidate["candidate_release"],
            "candidate_manifest_sha256": candidate_digest,
            "signature_verified": True,
            "build_definitions": build_definition_records(),
        },
        "tools": candidate.get("verification", {}).get("smoke", {}),
        "transformations": [
            "promoted verified CPython 3.14.7 candidate without rebuilding binaries",
            "retained versionless python and temporary python3.13 compatibility entrypoints",
            "bound recovery-enabled build, boot, image, and VirtualBox protected roots",
        ],
        "system_packages": [],
        "t1os_components": candidate.get("verification", {}).get(
            "critical_t1os_consumers", {}
        ),
        "install_policy": {
            "owner": 0,
            "group": 0,
            "stable_entrypoint": "/the one/software/python/bin/python",
            "versioned_entrypoint": "/the one/software/python/bin/python3.14",
            "compatibility_entrypoint": "/the one/software/python/bin/python3.13",
            "bytecode": "checked-hash",
            "regular_file_mode": "0444",
            "profiled_python_mode": "0555",
        },
        "profiled_python_entrypoints": policy,
        "software": software,
        "catalogue": catalogue,
        "protected_external_roots": protected_external_roots(
            config, source_overrides={"image_catalogue": image_root}
        ),
        "verification": candidate.get("verification", {}),
    }


def build_release_lock(manifest: dict, manifest_digest: str) -> dict:
    return {
        "format": 1,
        "component": "python-release",
        "release": RELEASE,
        "immutable": True,
        "rebuild_policy": "change the release identifier before replacing this lock",
        "python_version": VERSION,
        "python_abi": ABI,
        "build_definitions": manifest["source"]["build_definitions"],
        "outputs": {
            "software_tree": manifest["software"]["tree"],
            "catalogue_tree": manifest["catalogue"]["tree"],
            "python_sha256": sha256_file(SOFTWARE_DESTINATION / "bin" / "python")
            if SOFTWARE_DESTINATION.is_dir()
            else manifest["software"]["files"][0]["sha256"],
            "manifest_sha256": manifest_digest,
        },
        "protected_external_roots": [
            {
                "name": item["name"],
                "source": item["source"],
                "destination": item["destination"],
                "exclude_generated_bytecode": item["exclude_generated_bytecode"],
                "tree": item["tree"],
            }
            for item in manifest["protected_external_roots"]
        ],
    }


def compare_inventory(label: str, actual: dict, expected: dict) -> None:
    for key in ("directories", "files", "tree"):
        if actual.get(key) != expected.get(key):
            raise PromotionFailure(f"{label} inventory differs: {key}")


def verify(deployment_only: bool) -> dict:
    manifest_path = SOFTWARE_DESTINATION / "manifest.json"
    manifest = read_json(manifest_path)
    release = read_json(RELEASE_LOCK)
    config = read_json(RUNTIME_CONFIG)
    policy, _ = profiled_python_policy(config)
    manifest_digest = sha256_file(manifest_path)
    if (
        manifest.get("state") != "verified"
        or manifest.get("release") != RELEASE
        or manifest.get("python_version") != VERSION
        or manifest.get("python_abi") != ABI
        or release.get("component") != "python-release"
        or release.get("release") != RELEASE
        or release.get("outputs", {}).get("manifest_sha256") != manifest_digest
        or manifest.get("profiled_python_entrypoints") != policy
        or manifest.get("install_policy", {}).get("owner") != 0
        or manifest.get("install_policy", {}).get("group") != 0
        or manifest.get("install_policy", {}).get("profiled_python_mode") != "0555"
    ):
        raise PromotionFailure("Canonical Python identity differs from its release lock")
    software = payload_inventory(SOFTWARE_DESTINATION, skip_files={"manifest.json"})
    catalogue = payload_inventory(CATALOGUE_DESTINATION)
    forbidden_pip_paths = (
        SOFTWARE_DESTINATION / "bin" / "pip",
        SOFTWARE_DESTINATION / "bin" / "pip3",
        SOFTWARE_DESTINATION / "bin" / "pip3.14",
        SOFTWARE_DESTINATION / "lib" / "python3.14" / "site-packages" / "pip",
    )
    if any(path.exists() for path in forbidden_pip_paths):
        raise PromotionFailure("Canonical Python exposes a forbidden userspace pip interface")
    compare_inventory("software", software, manifest["software"])
    compare_inventory("catalogue", catalogue, manifest["catalogue"])
    if software["tree"] != release["outputs"]["software_tree"]:
        raise PromotionFailure("Software tree differs from its release lock")
    if catalogue["tree"] != release["outputs"]["catalogue_tree"]:
        raise PromotionFailure("Catalogue tree differs from its release lock")
    python_hash = sha256_file(SOFTWARE_DESTINATION / "bin" / "python")
    if python_hash != release["outputs"]["python_sha256"]:
        raise PromotionFailure("Versionless Python executable differs from its release lock")
    if not deployment_only:
        definitions = build_definition_records()
        if manifest.get("source", {}).get("build_definitions") != definitions:
            raise PromotionFailure("Build definitions differ from the canonical manifest")
        if release.get("build_definitions") != definitions:
            raise PromotionFailure("Build definitions differ from the release lock")
        external = protected_external_roots(config)
        if external != manifest.get("protected_external_roots"):
            raise PromotionFailure("Protected external roots differ from the manifest")
        locked = [
            {
                "name": item["name"],
                "source": item["source"],
                "destination": item["destination"],
                "exclude_generated_bytecode": item["exclude_generated_bytecode"],
                "tree": item["tree"],
            }
            for item in external
        ]
        if locked != release.get("protected_external_roots"):
            raise PromotionFailure("Protected external roots differ from the release lock")
    return {
        "release": RELEASE,
        "python_version": VERSION,
        "python_abi": ABI,
        "manifest_sha256": manifest_digest,
        "software_files": software["tree"]["files"],
        "catalogue_files": catalogue["tree"]["files"],
        "software_tree": software["tree"],
        "catalogue_tree": catalogue["tree"],
        "protected_external_roots": len(manifest.get("protected_external_roots", [])),
        "scope": "deployment" if deployment_only else "full",
    }


def recover_promotion() -> None:
    if not JOURNAL.exists():
        return
    journal = read_json(JOURNAL)
    if journal.get("state") == "complete":
        JOURNAL.unlink()
        return
    software_backup = ARCHIVE_ROOT / "software-python"
    catalogue_backup = ARCHIVE_ROOT / "catalogue-python"
    image_backup = ARCHIVE_ROOT / "catalogue-image"
    if not SOFTWARE_DESTINATION.exists() and software_backup.exists():
        os.replace(software_backup, SOFTWARE_DESTINATION)
    if not CATALOGUE_DESTINATION.exists() and catalogue_backup.exists():
        os.replace(catalogue_backup, CATALOGUE_DESTINATION)
    if not IMAGE_DESTINATION.exists() and image_backup.exists():
        os.replace(image_backup, IMAGE_DESTINATION)
    if (
        SOFTWARE_DESTINATION.exists()
        and CATALOGUE_DESTINATION.exists()
        and IMAGE_DESTINATION.exists()
        and not software_backup.exists()
        and not catalogue_backup.exists()
        and not image_backup.exists()
    ):
        # A failed swap can restore every canonical tree in its exception
        # handler but leave the moving journal behind. That is a complete
        # rollback, not an ambiguous mixed generation; clear the stale journal
        # so the same release can be staged and attempted again.
        JOURNAL.unlink()
        return
    raise PromotionFailure("Recovered an interrupted promotion; rerun the command")


def promote() -> dict:
    recover_promotion()
    if SOFTWARE_DESTINATION.is_dir() and RELEASE_LOCK.is_file():
        current = read_json(SOFTWARE_DESTINATION / "manifest.json")
        if current.get("release") == RELEASE:
            prune_candidate_archives(MAX_RETAINED_CANDIDATES)
            return verify(False)
    candidate, candidate_digest = load_verified_candidate()
    if STAGE_ROOT.exists():
        shutil.rmtree(STAGE_ROOT)
    STAGE_ROOT.mkdir(parents=True)
    stage_software = STAGE_ROOT / "software-python"
    stage_catalogue = STAGE_ROOT / "catalogue-python"
    stage_image = STAGE_ROOT / "catalogue-image"
    shutil.copytree(CANDIDATE_ROOT / "software" / "python", stage_software)
    shutil.copytree(CANDIDATE_ROOT / "catalogue" / "python", stage_catalogue)
    shutil.copytree(CANDIDATE_ROOT / "catalogue" / "image", stage_image)
    manifest = build_manifest(
        candidate, candidate_digest, stage_software, stage_catalogue, stage_image
    )
    manifest_path = stage_software / "manifest.json"
    write_json_atomic(manifest_path, manifest)
    manifest_digest = sha256_file(manifest_path)

    versionless = stage_software / "bin" / "python"
    versioned = stage_software / "bin" / "python3.14"
    compatibility = stage_software / "bin" / "python3.13"
    if not all(path.is_file() for path in (versionless, versioned, compatibility)):
        raise PromotionFailure("The promoted runtime lacks a required Python entrypoint")
    hashes = {sha256_file(path) for path in (versionless, versioned, compatibility)}
    if len(hashes) != 1:
        raise PromotionFailure("Python entrypoints do not resolve to the same 3.14.7 binary")

    release = {
        "format": 1,
        "component": "python-release",
        "release": RELEASE,
        "immutable": True,
        "rebuild_policy": "change the release identifier before replacing this lock",
        "python_version": VERSION,
        "python_abi": ABI,
        "build_definitions": manifest["source"]["build_definitions"],
        "outputs": {
            "software_tree": manifest["software"]["tree"],
            "catalogue_tree": manifest["catalogue"]["tree"],
            "python_sha256": hashes.pop(),
            "manifest_sha256": manifest_digest,
        },
        "protected_external_roots": [
            {
                "name": item["name"],
                "source": item["source"],
                "destination": item["destination"],
                "exclude_generated_bytecode": item["exclude_generated_bytecode"],
                "tree": item["tree"],
            }
            for item in manifest["protected_external_roots"]
        ],
    }

    PROMOTION_ROOT.mkdir(parents=True, exist_ok=True)
    # Reserve one retention slot before moving the current verified release
    # into the archive, so there are never more than two candidate generations.
    prune_candidate_archives(MAX_RETAINED_CANDIDATES - 1)
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    software_backup = ARCHIVE_ROOT / "software-python"
    catalogue_backup = ARCHIVE_ROOT / "catalogue-python"
    image_backup = ARCHIVE_ROOT / "catalogue-image"
    if software_backup.exists() or catalogue_backup.exists() or image_backup.exists():
        raise PromotionFailure("The immutable previous-release archive already exists")
    write_json_atomic(
        JOURNAL,
        {"format": 1, "component": "python-promotion", "state": "moving"},
    )
    try:
        os.replace(SOFTWARE_DESTINATION, software_backup)
        os.replace(CATALOGUE_DESTINATION, catalogue_backup)
        os.replace(IMAGE_DESTINATION, image_backup)
        os.replace(stage_software, SOFTWARE_DESTINATION)
        os.replace(stage_catalogue, CATALOGUE_DESTINATION)
        os.replace(stage_image, IMAGE_DESTINATION)
        shutil.copy2(RELEASE_LOCK, ARCHIVE_ROOT / "release.json")
        write_json_atomic(RELEASE_LOCK, release)
        write_json_atomic(
            JOURNAL,
            {"format": 1, "component": "python-promotion", "state": "complete"},
        )
    except Exception:
        if not SOFTWARE_DESTINATION.exists() and software_backup.exists():
            os.replace(software_backup, SOFTWARE_DESTINATION)
        if not CATALOGUE_DESTINATION.exists() and catalogue_backup.exists():
            os.replace(catalogue_backup, CATALOGUE_DESTINATION)
        if not IMAGE_DESTINATION.exists() and image_backup.exists():
            os.replace(image_backup, IMAGE_DESTINATION)
        raise
    JOURNAL.unlink()
    if STAGE_ROOT.exists():
        shutil.rmtree(STAGE_ROOT)
    prune_candidate_archives(MAX_RETAINED_CANDIDATES)
    return verify(False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("promote", "verify", "verify-deployment"))
    args = parser.parse_args()
    try:
        if args.command == "promote":
            result = promote()
        else:
            result = verify(args.command == "verify-deployment")
    except PromotionFailure as error:
        print(f"Python 3.14 promotion failure: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
