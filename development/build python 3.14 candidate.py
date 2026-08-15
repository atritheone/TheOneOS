#!/usr/bin/env python3
"""Build and inspect a source-authenticated CPython 3.14 candidate for T1OS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request


REPO = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO / "source" / "python" / "locks" / "python-3.14.7-candidate.json"
CONFIG_PATH = REPO / "source" / "python" / "build" / "portable-python-3.14.yml"
DEVELOPMENT = REPO / "development" / "python 3.14 candidate"
CACHE = DEVELOPMENT / "cache"
OUTPUT = DEVELOPMENT / "output"
REPORT = DEVELOPMENT / "candidate-report.json"
LOG = DEVELOPMENT / "candidate-build.log"
SCRATCH = Path("/tmp/t1os-python-3.14.7")


class CandidateFailure(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def run(command: list[str], *, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        check=False,
    )
    if result.returncode:
        raise CandidateFailure(
            f"Command failed ({result.returncode}): {' '.join(command)}\n{result.stdout.strip()}"
        )
    return result.stdout


def load_lock() -> dict:
    try:
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateFailure(f"Could not load {LOCK_PATH}: {error}") from error
    if lock.get("python_version") != "3.14.7" or lock.get("python_abi") != "cp314":
        raise CandidateFailure("The candidate lock does not describe CPython 3.14.7/cp314")
    if lock.get("promotable") is not False:
        raise CandidateFailure("An unverified candidate must not be marked promotable")
    return lock


def require_child(path: Path, parent: Path) -> None:
    resolved = path.resolve()
    root = parent.resolve()
    if resolved == root or root not in resolved.parents:
        raise CandidateFailure(f"Refusing to modify {resolved}; expected a child of {root}")


def reset_directory(path: Path, parent: Path) -> None:
    require_child(path, parent)
    if path.exists():
        if path.is_symlink():
            raise CandidateFailure(f"Refusing to remove symbolic link {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True)


def validate_artifact(path: Path, *, size: int, digest: str) -> bool:
    return path.is_file() and path.stat().st_size == size and sha256_file(path) == digest


def download_locked(item: dict, *, offline: bool) -> Path:
    filename = str(item.get("filename", ""))
    digest = str(item.get("sha256", "")).lower()
    if not filename or Path(filename).name != filename or "/" in filename or "\\" in filename:
        raise CandidateFailure(f"Unsafe locked filename: {filename!r}")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise CandidateFailure(f"Invalid SHA-256 lock for {filename}")
    if not str(item.get("url", "")).startswith("https://"):
        raise CandidateFailure(f"Artifact URL is not HTTPS: {filename}")
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / filename
    require_child(target, CACHE)
    if validate_artifact(target, size=int(item["size"]), digest=digest):
        return target
    if target.exists():
        target.unlink()
    if offline:
        raise CandidateFailure(f"Locked artifact is not cached for offline use: {filename}")
    partial = CACHE / f".{filename}.partial"
    if partial.exists():
        partial.unlink()
    request = urllib.request.Request(item["url"], headers={"User-Agent": "T1OS-Python/2"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
    except Exception as error:
        partial.unlink(missing_ok=True)
        raise CandidateFailure(f"Could not download {item['url']}: {error}") from error
    if not validate_artifact(partial, size=int(item["size"]), digest=digest):
        partial.unlink(missing_ok=True)
        raise CandidateFailure(f"Downloaded artifact differs from its lock: {filename}")
    partial.replace(target)
    return target


def tool_item(row: list) -> dict:
    if not isinstance(row, list) or len(row) != 5:
        raise CandidateFailure(f"Malformed tool wheel lock row: {row!r}")
    name, version, filename, size, digest = row
    return {
        "name": str(name),
        "version": str(version),
        "filename": str(filename),
        "size": int(size),
        "sha256": str(digest).lower(),
    }


def acquire_tool_wheels(lock: dict, *, offline: bool) -> list[Path]:
    items = [tool_item(row) for row in lock["tool_wheels"]]
    if len({normalized_name(item["name"]) for item in items}) != len(items):
        raise CandidateFailure("Tool wheel lock contains duplicate projects")
    CACHE.mkdir(parents=True, exist_ok=True)
    missing = [
        item
        for item in items
        if not validate_artifact(
            CACHE / item["filename"], size=item["size"], digest=item["sha256"]
        )
    ]
    if missing and offline:
        raise CandidateFailure(
            "Locked tool wheels are not cached for offline use: "
            + ", ".join(item["filename"] for item in missing)
        )
    if missing:
        download_root = SCRATCH / "tool-download"
        download_root.mkdir(parents=True)
        requirements = SCRATCH / "tool-requirements.txt"
        requirements.write_text(
            "".join(
                f"{item['name']}=={item['version']} --hash=sha256:{item['sha256']}\n"
                for item in items
            ),
            encoding="utf-8",
            newline="\n",
        )
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "--disable-pip-version-check",
                "download",
                "--only-binary=:all:",
                "--no-deps",
                "--require-hashes",
                "--index-url",
                lock["tool_index"],
                "--dest",
                str(download_root),
                "--requirement",
                str(requirements),
            ]
        )
        for item in items:
            downloaded = download_root / item["filename"]
            if not validate_artifact(
                downloaded, size=item["size"], digest=item["sha256"]
            ):
                raise CandidateFailure(f"pip did not produce the locked wheel {item['filename']}")
            shutil.copy2(downloaded, CACHE / item["filename"])
    paths = [CACHE / item["filename"] for item in items]
    for item, path in zip(items, paths, strict=True):
        if not validate_artifact(path, size=item["size"], digest=item["sha256"]):
            raise CandidateFailure(f"Cached tool wheel differs from lock: {path.name}")
    return paths


def host_facts() -> dict:
    if os.name != "posix" or platform.machine() != "x86_64":
        raise CandidateFailure("The candidate build requires x86_64 Linux/WSL")
    if sys.version_info[:2] != (3, 12):
        raise CandidateFailure("The locked tool wheels require host Python 3.12")
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "host_python": sys.version.split()[0],
        "gcc": run(["gcc", "--version"]).splitlines()[0],
        "glibc": run(["ldd", "--version"]).splitlines()[0],
        "patchelf": run(["patchelf", "--version"]).strip(),
    }


def install_tools(lock: dict, wheels: list[Path]) -> tuple[Path, dict]:
    venv = SCRATCH / "venv"
    run([sys.executable, "-m", "venv", str(venv)])
    python = venv / "bin" / "python"
    run(
        [
            str(python),
            "-m",
            "pip",
            "--disable-pip-version-check",
            "install",
            "--no-index",
            "--no-deps",
            *map(str, wheels),
        ]
    )
    run([str(python), "-m", "pip", "check"])
    for item in lock.get("tool_patches", []):
        patch_path = REPO / item["path"]
        if not validate_artifact(
            patch_path, size=int(item["size"]), digest=str(item["sha256"])
        ):
            raise CandidateFailure(f"Build-tool patch differs from lock: {item['path']}")
        site_packages = run(
            [str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"]
        ).strip()
        run(
            [
                "patch", "--batch", "--forward", "--directory", site_packages,
                "-p1", "-i", str(patch_path),
            ],
            env={**os.environ, "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        )
    expected = {
        normalized_name(tool_item(row)["name"]): tool_item(row)["version"]
        for row in lock["tool_wheels"]
    }
    script = (
        "import importlib.metadata,json; names=json.loads(__import__('sys').argv[1]); "
        "print(json.dumps({n:importlib.metadata.version(n) for n in names},sort_keys=True))"
    )
    installed = json.loads(run([str(python), "-c", script, json.dumps(sorted(expected))]))
    if {normalized_name(k): v for k, v in installed.items()} != expected:
        raise CandidateFailure("Installed source-build tools differ from their lock")
    return venv, installed


def verify_sigstore(lock: dict, venv: Path, artifacts: dict[str, Path]) -> dict:
    policy = lock["signature_policy"]
    output = run(
        [
            str(venv / "bin" / "sigstore"),
            "verify",
            "identity",
            "--bundle",
            str(artifacts["cpython-sigstore-bundle"]),
            "--cert-identity",
            policy["identity"],
            "--cert-oidc-issuer",
            policy["oidc_issuer"],
            str(artifacts["cpython"]),
        ]
    )
    if "OK:" not in output:
        raise CandidateFailure("Sigstore did not confirm the CPython source artifact")
    return {
        "method": policy["method"],
        "identity": policy["identity"],
        "oidc_issuer": policy["oidc_issuer"],
        "verifier": policy["verifier"],
        "verified": True,
    }


def stream_build(command: list[str], environment: dict[str, str]) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("w", encoding="utf-8", newline="\n") as log:
        process = subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=environment,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
        returncode = process.wait()
    if returncode:
        raise CandidateFailure(f"Portable Python build failed with exit code {returncode}")


def active_python_sources() -> list[Path]:
    sources: set[Path] = set()
    for pattern in (
        "source/build software/**/*.py",
        "source/boot/**/*.py",
        "source/software/virtualbox/guestadditions.py",
    ):
        sources.update(path for path in REPO.glob(pattern) if path.is_file())
    return sorted(sources, key=lambda path: path.as_posix())


def archive_topology(path: Path) -> dict:
    counts = {"regular_files": 0, "regular_bytes": 0, "directories": 0, "symbolic_links": 0}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            if member.isfile():
                counts["regular_files"] += 1
                counts["regular_bytes"] += member.size
            elif member.isdir():
                counts["directories"] += 1
            elif member.issym():
                counts["symbolic_links"] += 1
            elif member.islnk():
                raise CandidateFailure("Unexpected hard link in candidate archive")
    return counts


def inspect_candidate(archive_path: Path, lock: dict) -> dict:
    inspect_root = SCRATCH / "inspect"
    inspect_root.mkdir()
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(inspect_root, filter="data")
    roots = [path for path in inspect_root.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise CandidateFailure("Candidate archive has an unexpected root layout")
    root = roots[0]
    python = root / "bin" / "python3.14"
    if not python.is_file():
        raise CandidateFailure("Candidate archive has no Python 3.14 interpreter")
    sources = active_python_sources()
    script = r'''
import importlib, json, pathlib, ssl, sqlite3, sys, sysconfig
modules=json.loads(sys.argv[1]); sources=json.loads(sys.argv[2]); results={}
for name in modules:
    try: importlib.import_module(name); results[name]=True
    except Exception as error: results[name]=f"{type(error).__name__}: {error}"
for value in sources: compile(pathlib.Path(value).read_bytes(), value, "exec", dont_inherit=True)
print(json.dumps({"python":sys.version.split()[0],"soabi":sysconfig.get_config_var("SOABI"),
"openssl":ssl.OPENSSL_VERSION,"sqlite":sqlite3.sqlite_version,"modules":results,
"t1os_sources_compiled":len(sources),"safe_path":sys.flags.safe_path},sort_keys=True))
'''
    modules = [
        "bz2", "ctypes", "curses", "decimal", "lzma", "readline", "sqlite3", "ssl",
        "uuid", "zlib",
    ]
    environment = os.environ.copy()
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONPATH": ""})
    output = run(
        [str(python), "-B", "-S", "-I", "-c", script, json.dumps(modules),
         json.dumps([str(path) for path in sources])],
        env=environment,
    )
    result = json.loads(output.strip().splitlines()[-1])
    if result["python"] != lock["python_version"]:
        raise CandidateFailure(f"Candidate has unexpected Python version: {result}")
    if result["soabi"] != "cpython-314-x86_64-linux-gnu":
        raise CandidateFailure(f"Candidate has unexpected ABI: {result}")
    if any(value is not True for value in result["modules"].values()):
        raise CandidateFailure(f"Candidate is missing required modules: {result['modules']}")
    if result["t1os_sources_compiled"] != len(sources):
        raise CandidateFailure("Candidate did not compile every active T1OS Python source")
    manifests = {}
    for name in (".manifest.yml", ".inspection-report.yml"):
        path = root / name
        if not path.is_file():
            raise CandidateFailure(f"Portable Python did not emit {name}")
        manifests[name] = {"size": path.stat().st_size, "sha256": sha256_file(path)}
    return {
        **result,
        "python_sha256": sha256_file(python),
        "elf": {
            "interpreter": run(["patchelf", "--print-interpreter", str(python)]).strip(),
            "runpath": run(["patchelf", "--print-rpath", str(python)]).strip(),
            "ldd": run(["ldd", str(python)]).splitlines(),
        },
        "portable_python_reports": manifests,
    }


def build(*, offline: bool) -> dict:
    lock = load_lock()
    facts = host_facts()
    if SCRATCH.resolve() != Path(lock["scratch_path"]):
        raise CandidateFailure("Candidate scratch path differs from its lock")
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    SCRATCH.mkdir(mode=0o755)
    artifacts = {
        item["name"]: download_locked(item, offline=offline)
        for item in [*lock["sources"], *lock["runtime_wheels"]]
    }
    tool_wheels = acquire_tool_wheels(lock, offline=offline)
    venv, installed_tools = install_tools(lock, tool_wheels)
    signature = verify_sigstore(lock, venv, artifacts)
    source_cache = SCRATCH / "cache"
    source_cache.mkdir()
    for item in lock["sources"]:
        if item.get("cache_filename"):
            shutil.copy2(artifacts[item["name"]], source_cache / item["cache_filename"])
    config = SCRATCH / "portable-python.yml"
    shutil.copy2(CONFIG_PATH, config)
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
            "SOURCE_DATE_EPOCH": "1785928907",
            "PYTHONHASHSEED": "0",
        }
    )
    stream_build(
        [str(venv / "bin" / "portable-python"), "--config", str(config), "build", lock["python_version"]],
        environment,
    )
    archives = sorted((SCRATCH / "dist").glob("*.tar.gz"))
    if len(archives) != 1:
        raise CandidateFailure(f"Expected one candidate archive, found {archives}")
    reset_directory(OUTPUT, DEVELOPMENT)
    destination = OUTPUT / archives[0].name
    shutil.copy2(archives[0], destination)
    candidate = inspect_candidate(destination, lock)
    report = {
        "format": 1,
        "component": lock["component"],
        "candidate_release": lock["candidate_release"],
        "python_version": lock["python_version"],
        "python_abi": lock["python_abi"],
        "promotable": False,
        "host": facts,
        "signature": signature,
        "tool_versions": installed_tools,
        "runtime_wheels": [
            {key: item[key] for key in ("name", "version", "filename", "size", "sha256")}
            for item in lock["runtime_wheels"]
        ],
        "artifact": {
            "path": destination.relative_to(REPO).as_posix(),
            "size": destination.stat().st_size,
            "sha256": sha256_file(destination),
            "topology": archive_topology(destination),
        },
        "candidate": candidate,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    arguments = parser.parse_args()
    try:
        result = build(offline=arguments.offline)
    except CandidateFailure as error:
        print(f"python 3.14 candidate: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
