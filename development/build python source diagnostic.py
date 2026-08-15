#!/usr/bin/env python3
"""Build and inspect a non-promotable CPython source reconstruction for T1OS."""

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
import urllib.request


REPO = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO / "source" / "python" / "locks" / "source-rebuild.json"
CONFIG_PATH = REPO / "source" / "python" / "build" / "portable-python-source.yml"
DEVELOPMENT = REPO / "development" / "python source diagnostic"
CACHE = DEVELOPMENT / "cache"
OUTPUT = DEVELOPMENT / "output"
REPORT = DEVELOPMENT / "source-rebuild-report.json"
LOG = DEVELOPMENT / "source-rebuild.log"
SCRATCH = Path("/tmp/t1os-python-source")


class DiagnosticFailure(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_lock() -> dict:
    try:
        value = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DiagnosticFailure(f"Could not load {LOCK_PATH}: {error}") from error
    if value.get("promotable") is not False:
        raise DiagnosticFailure("Source diagnostic lock must explicitly forbid promotion")
    return value


def require_child(path: Path, parent: Path) -> None:
    path = path.resolve()
    parent = parent.resolve()
    if path == parent or parent not in path.parents:
        raise DiagnosticFailure(f"Refusing to modify {path}; expected a child of {parent}")


def reset_directory(path: Path, parent: Path) -> None:
    require_child(path, parent)
    if path.exists():
        if path.is_symlink():
            raise DiagnosticFailure(f"Refusing to remove symbolic link {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True)


def download_locked(item: dict, *, offline: bool) -> Path:
    filename = str(item.get("filename", ""))
    if not filename or Path(filename).name != filename or "/" in filename or "\\" in filename:
        raise DiagnosticFailure(f"Unsafe locked filename: {filename!r}")
    digest = str(item.get("sha256", "")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise DiagnosticFailure(f"Invalid SHA-256 lock for {filename}")
    if not str(item.get("url", "")).startswith("https://"):
        raise DiagnosticFailure(f"Source URL is not HTTPS: {filename}")
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / filename
    require_child(target, CACHE)
    if target.is_file() and target.stat().st_size == item["size"] and sha256_file(target) == digest:
        return target
    if target.exists():
        target.unlink()
    if offline:
        raise DiagnosticFailure(f"Locked source is not cached for offline use: {filename}")
    partial = target.with_suffix(target.suffix + ".partial")
    if partial.exists():
        partial.unlink()
    request = urllib.request.Request(item["url"], headers={"User-Agent": "T1OS-Source-Diagnostic/1"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
    except Exception as error:
        if partial.exists():
            partial.unlink()
        raise DiagnosticFailure(f"Could not download {item['url']}: {error}") from error
    if partial.stat().st_size != item["size"] or sha256_file(partial) != digest:
        partial.unlink()
        raise DiagnosticFailure(f"Downloaded artifact differs from its lock: {filename}")
    partial.replace(target)
    return target


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
        raise DiagnosticFailure(
            f"Command failed ({result.returncode}): {' '.join(command)}\n{result.stdout.strip()}"
        )
    return result.stdout


def verify_openpgp(lock: dict, artifacts: dict[str, Path]) -> dict:
    gpg = shutil.which("gpg")
    if not gpg:
        raise DiagnosticFailure("gpg is required for the CPython source signature gate")
    signature = artifacts["cpython-openpgp-signature"]
    source = artifacts["cpython"]
    key_item = next(item for item in lock["sources"] if item["name"] == "cpython-release-manager-key")
    key = artifacts[key_item["name"]]
    gnupg = SCRATCH / "gnupg"
    gnupg.mkdir(mode=0o700)
    environment = os.environ.copy()
    environment["GNUPGHOME"] = str(gnupg)
    run([gpg, "--batch", "--import", str(key)], env=environment)
    fingerprint_output = run(
        [gpg, "--batch", "--with-colons", "--fingerprint", key_item["fingerprint"][-16:]],
        env=environment,
    )
    fingerprints = [
        line.split(":")[9] for line in fingerprint_output.splitlines() if line.startswith("fpr:")
    ]
    if key_item["fingerprint"] not in fingerprints:
        raise DiagnosticFailure("Imported CPython release key has an unexpected fingerprint")
    status = run(
        [gpg, "--batch", "--status-fd", "1", "--verify", str(signature), str(source)],
        env=environment,
    )
    if f"[GNUPG:] VALIDSIG {key_item['fingerprint']} " not in status:
        raise DiagnosticFailure("CPython detached signature did not validate with the locked key")
    return {
        "method": "OpenPGP detached signature",
        "fingerprint": key_item["fingerprint"],
        "verified": True,
        "sigstore_bundle_sha256_verified": True,
    }


def host_facts() -> dict:
    if os.name != "posix" or platform.machine() != "x86_64":
        raise DiagnosticFailure("Source reconstruction requires x86_64 Linux/WSL")
    gcc = run(["gcc", "--version"]).splitlines()[0]
    glibc = run(["ldd", "--version"]).splitlines()[0]
    if sys.version_info[:2] != (3, 12):
        raise DiagnosticFailure("The locked diagnostic wheelhouse requires host Python 3.12")
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "host_python": sys.version.split()[0],
        "gcc": gcc,
        "glibc": glibc,
    }


def install_toolchain(lock: dict, wheel_paths: list[Path]) -> tuple[Path, dict]:
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
            *map(str, wheel_paths),
        ]
    )
    expected = {item["name"]: item["version"] for item in lock["tool_wheels"]}
    script = (
        "import importlib.metadata,json; "
        "names=json.loads(__import__('sys').argv[1]); "
        "print(json.dumps({n:importlib.metadata.version(n) for n in names},sort_keys=True))"
    )
    installed = json.loads(run([str(python), "-c", script, json.dumps(sorted(expected))]).strip())
    if {name.lower(): value for name, value in installed.items()} != {
        name.lower(): value for name, value in expected.items()
    }:
        raise DiagnosticFailure(f"Source-build tool versions differ from their lock: {installed}")
    return venv / "bin" / "portable-python", installed


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
        raise DiagnosticFailure(f"Portable Python source build failed with exit code {returncode}")


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
                raise DiagnosticFailure("Unexpected hard link in source candidate archive")
    return counts


def inspect_candidate(archive_path: Path) -> dict:
    inspect_root = SCRATCH / "inspect"
    inspect_root.mkdir()
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(inspect_root, filter="data")
    roots = [path for path in inspect_root.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise DiagnosticFailure("Source candidate archive has an unexpected root layout")
    root = roots[0]
    python = root / "bin" / "python3.13"
    if not python.is_file():
        raise DiagnosticFailure("Source candidate has no Python 3.13 interpreter")
    sources: list[Path] = []
    for pattern in (
        "source/build software/**/*.py",
        "source/boot/**/*.py",
        "source/software/virtualbox/guestadditions.py",
    ):
        sources.extend(path for path in REPO.glob(pattern) if path.is_file())
    source_names = sorted({str(path) for path in sources})
    script = r'''
import importlib
import json
from pathlib import Path
import ssl
import sqlite3
import sys
import sysconfig

modules = json.loads(sys.argv[1])
sources = json.loads(sys.argv[2])
results = {}
for name in modules:
    try:
        importlib.import_module(name)
        results[name] = True
    except Exception as error:
        results[name] = f"{type(error).__name__}: {error}"
for value in sources:
    compile(Path(value).read_bytes(), value, "exec", dont_inherit=True)
print(json.dumps({
    "python": sys.version.split()[0],
    "soabi": sysconfig.get_config_var("SOABI"),
    "openssl": ssl.OPENSSL_VERSION,
    "sqlite": sqlite3.sqlite_version,
    "modules": results,
    "t1os_sources_compiled": len(sources),
}, sort_keys=True))
'''
    modules = ["bz2", "ctypes", "curses", "lzma", "readline", "sqlite3", "ssl", "uuid", "zlib"]
    environment = os.environ.copy()
    environment.update(
        {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONPATH": ""}
    )
    output = run(
        [str(python), "-B", "-S", "-I", "-c", script, json.dumps(modules), json.dumps(source_names)],
        env=environment,
    )
    result = json.loads(output.strip().splitlines()[-1])
    if result["python"] != "3.13.5" or result["soabi"] != "cpython-313-x86_64-linux-gnu":
        raise DiagnosticFailure(f"Source candidate has an unexpected ABI: {result}")
    if any(value is not True for value in result["modules"].values()):
        raise DiagnosticFailure(f"Source candidate is missing required modules: {result['modules']}")
    if result["t1os_sources_compiled"] != 37:
        raise DiagnosticFailure("Source candidate did not compile all active T1OS sources")
    manifests = {}
    for name in (".manifest.yml", ".inspection-report.yml"):
        path = root / name
        if not path.is_file():
            raise DiagnosticFailure(f"Portable Python did not emit {name}")
        manifests[name] = {"size": path.stat().st_size, "sha256": sha256_file(path)}
    return {
        **result,
        "python_sha256": sha256_file(python),
        "portable_python_reports": manifests,
    }


def build(*, offline: bool) -> dict:
    lock = load_lock()
    facts = host_facts()
    scratch = SCRATCH.resolve()
    if str(scratch) != "/tmp/t1os-python-source":
        raise DiagnosticFailure(f"Unexpected source diagnostic scratch path: {scratch}")
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(mode=0o755)
    artifacts: dict[str, Path] = {}
    for item in [*lock["sources"], *lock["tool_wheels"]]:
        artifacts[item["name"]] = download_locked(item, offline=offline)
    signature = verify_openpgp(lock, artifacts)
    source_cache = SCRATCH / "cache"
    source_cache.mkdir()
    for item in lock["sources"]:
        if "cache_filename" in item:
            shutil.copy2(artifacts[item["name"]], source_cache / item["cache_filename"])
    wheel_paths = [artifacts[item["name"]] for item in lock["tool_wheels"]]
    portable_python, installed_tools = install_toolchain(lock, wheel_paths)
    config = SCRATCH / "portable-python.yml"
    shutil.copy2(CONFIG_PATH, config)
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
            "SOURCE_DATE_EPOCH": "1752986362",
            "PYTHONHASHSEED": "0",
        }
    )
    stream_build(
        [str(portable_python), "--config", str(config), "build", lock["python_version"]],
        environment,
    )
    archives = sorted((SCRATCH / "dist").glob("*.tar.gz"))
    if len(archives) != 1:
        raise DiagnosticFailure(f"Expected one Portable Python result, found {archives}")
    reset_directory(OUTPUT, DEVELOPMENT)
    destination = OUTPUT / archives[0].name
    shutil.copy2(archives[0], destination)
    candidate = inspect_candidate(destination)
    report = {
        "format": 1,
        "component": "python-source-rebuild-diagnostic",
        "python_version": lock["python_version"],
        "promotable": False,
        "reproduction_boundary": lock["reason"],
        "host": facts,
        "signature": signature,
        "tool_versions": installed_tools,
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
    except DiagnosticFailure as error:
        print(f"python source diagnostic: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
