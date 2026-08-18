#!/usr/bin/env python3
"""Build the mutable T1OS boot policy independently of the Python release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat


EXPECTED_ROOTS = (
    ("image_catalogue", "source/catalogue/image", "/the one/catalogue/image", False),
    ("build_software", "source/build software", "/the one/build", True),
    ("boot", "source/boot", "/boot", True),
    (
        "virtualbox_software",
        "source/software/virtualbox",
        "/the one/software/virtualbox",
        True,
    ),
)
EXPECTED_SHEBANG = b'#!"/the one/software/python/bin/python" -B\n'
TREE_ALGORITHM = "t1os-install-tree-sha256-v2"


class PolicyFailure(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_elf(path: Path) -> bool:
    with path.open("rb") as stream:
        return stream.read(4) == b"\x7fELF"


def ignored_generated(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}


def tree_summary(directories: list[dict], files: list[dict]) -> dict:
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
        "algorithm": TREE_ALGORITHM,
        "directories": len(directories),
        "files": len(files),
        "bytes": sum(int(item["size"]) for item in files),
        "sha256": digest.hexdigest(),
    }


def load_contract(repo: Path) -> tuple[dict, list[dict], set[tuple[str, str]]]:
    config_path = repo / "source" / "python" / "build" / "runtime.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PolicyFailure(f"could not read boot policy config: {error}") from error
    configured = config.get("protected_external_roots")
    if not isinstance(configured, list) or len(configured) != len(EXPECTED_ROOTS):
        raise PolicyFailure("boot protected-root contract must contain four roots")
    roots = []
    for item, expected in zip(configured, EXPECTED_ROOTS, strict=True):
        name, source, destination, exclude_generated = expected
        if not isinstance(item, dict) or item != {
            "name": name,
            "source": source,
            "destination": destination,
            "exclude_generated_bytecode": exclude_generated,
        }:
            raise PolicyFailure(f"boot protected-root contract differs: {name}")
        roots.append(dict(item))

    policy = config.get("profiled_python_entrypoints")
    if not isinstance(policy, dict) or set(policy) != {
        "format", "owner", "group", "install_mode", "shebang", "entries"
    }:
        raise PolicyFailure("profiled Python boot policy has an unexpected schema")
    if (
        policy.get("format") != 1
        or policy.get("owner") != 0
        or policy.get("group") != 0
        or policy.get("install_mode") != "0555"
        or policy.get("shebang") != EXPECTED_SHEBANG.decode("ascii")
        or not isinstance(policy.get("entries"), list)
        or not policy["entries"]
    ):
        raise PolicyFailure("profiled Python boot policy is not fail-closed")

    roots_by_name = {item["name"]: item for item in roots}
    profiled: set[tuple[str, str]] = set()
    destinations: list[str] = []
    for entry in policy["entries"]:
        if not isinstance(entry, dict) or set(entry) != {
            "root", "path", "destination"
        }:
            raise PolicyFailure("profiled Python boot entry is malformed")
        name = entry["root"]
        relative_text = entry["path"]
        destination = entry["destination"]
        if name not in roots_by_name or not isinstance(relative_text, str):
            raise PolicyFailure("profiled Python boot entry has an unknown root")
        relative = PurePosixPath(relative_text)
        if (
            not relative_text
            or relative.is_absolute()
            or relative.as_posix() != relative_text
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.suffix != ".py"
        ):
            raise PolicyFailure(f"unsafe profiled Python path: {relative_text!r}")
        expected_destination = roots_by_name[name]["destination"].rstrip("/") + "/" + relative_text
        identity = (name, relative_text)
        if (
            destination != expected_destination
            or identity in profiled
            or destination in destinations
        ):
            raise PolicyFailure(f"non-canonical profiled Python entry: {destination}")
        source_path = repo / roots_by_name[name]["source"] / Path(*relative.parts)
        try:
            status = source_path.lstat()
            payload = source_path.read_bytes()
        except OSError as error:
            raise PolicyFailure(f"could not inspect {source_path}: {error}") from error
        if source_path.is_symlink() or not stat.S_ISREG(status.st_mode):
            raise PolicyFailure(f"profiled Python source is not regular: {source_path}")
        if payload.startswith(b"\xef\xbb\xbf") or not payload.startswith(EXPECTED_SHEBANG):
            raise PolicyFailure(f"profiled Python source has the wrong shebang: {source_path}")
        profiled.add(identity)
        destinations.append(destination)
    if destinations != sorted(destinations):
        raise PolicyFailure("profiled Python boot entries are not canonically ordered")
    return policy, roots, profiled


def inventory_root(
    repo: Path, contract: dict, profiled: set[tuple[str, str]]
) -> dict:
    root = repo / contract["source"]
    if not root.is_dir() or root.is_symlink():
        raise PolicyFailure(f"boot protected root is missing or redirected: {root}")
    directories = [{"path": ".", "install_mode": "0755"}]
    files = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative_path = path.relative_to(root)
        relative = relative_path.as_posix()
        if any(character in relative for character in "\x00\t\r\n"):
            raise PolicyFailure(f"unrepresentable boot policy path: {path}")
        status = path.lstat()
        if stat.S_ISLNK(status.st_mode):
            raise PolicyFailure(f"symbolic link entered boot policy: {path}")
        if contract["exclude_generated_bytecode"] and ignored_generated(relative_path):
            continue
        if stat.S_ISDIR(status.st_mode):
            directories.append({"path": relative, "install_mode": "0755"})
            continue
        if not stat.S_ISREG(status.st_mode):
            raise PolicyFailure(f"special file entered boot policy: {path}")
        executable = (contract["name"], relative) in profiled or (
            not relative.endswith(".py") and is_elf(path)
        )
        files.append(
            {
                "path": relative,
                "size": status.st_size,
                "sha256": sha256_file(path),
                "install_mode": "0555" if executable else "0444",
            }
        )
    directories.sort(key=lambda item: item["path"])
    files.sort(key=lambda item: item["path"])
    return {
        **contract,
        "directories": directories,
        "files": files,
        "tree": tree_summary(directories, files),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    repo = arguments.repo.resolve()
    policy, roots, profiled = load_contract(repo)
    document = {
        "format": 1,
        "component": "t1os-boot-protected-roots",
        "profiled_python_entrypoints": policy,
        "roots": [inventory_root(repo, item, profiled) for item in roots],
    }
    output = arguments.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".new")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, output)
    print(
        json.dumps(
            {
                "component": document["component"],
                "roots": len(document["roots"]),
                "profiled_python_entrypoints": len(policy["entries"]),
                "sha256": sha256_file(output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PolicyFailure as error:
        print(f"boot protected-root policy failed: {error}")
        raise SystemExit(1) from error
