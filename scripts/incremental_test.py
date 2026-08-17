#!/usr/bin/env python3
"""Content-addressed execution for T1OS test, validation, and audit scripts."""

from __future__ import annotations

import argparse
import ast
import contextlib
import fnmatch
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Iterable


SCHEMA = 1
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
REGISTRY_PATH = SCRIPT_DIR / "incremental tests.json"
STATE_ROOT = PROJECT_ROOT / "environment" / ".test-state"
RESULT_ROOT = STATE_ROOT / "results"
LOCK_ROOT = STATE_ROOT / "locks"
DIGEST_DB = STATE_ROOT / "digests.sqlite3"
ACTIVE_SCRIPT = "T1OS_INCREMENTAL_ACTIVE_SCRIPT"


def canonical_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def ensure_state() -> None:
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    LOCK_ROOT.mkdir(parents=True, exist_ok=True)


def digest_connection() -> sqlite3.Connection:
    ensure_state()
    connection = sqlite3.connect(DIGEST_DB, timeout=30)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS file_digest (
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            ctime_ns INTEGER NOT NULL,
            device INTEGER NOT NULL,
            inode INTEGER NOT NULL,
            sha256 TEXT NOT NULL
        )
        """
    )
    return connection


def file_digest(path: Path, connection: sqlite3.Connection) -> str:
    resolved = path.resolve()
    stat = resolved.stat()
    identity = (
        int(stat.st_size),
        int(stat.st_mtime_ns),
        int(stat.st_ctime_ns),
        int(stat.st_dev),
        int(stat.st_ino),
    )
    key = canonical_relative(resolved)
    row = connection.execute(
        "SELECT size,mtime_ns,ctime_ns,device,inode,sha256 FROM file_digest WHERE path=?",
        (key,),
    ).fetchone()
    if row and tuple(row[:5]) == identity:
        return str(row[5])

    hasher = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    connection.execute(
        """
        INSERT INTO file_digest(path,size,mtime_ns,ctime_ns,device,inode,sha256)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(path) DO UPDATE SET
          size=excluded.size,mtime_ns=excluded.mtime_ns,ctime_ns=excluded.ctime_ns,
          device=excluded.device,inode=excluded.inode,sha256=excluded.sha256
        """,
        (key, *identity, digest),
    )
    connection.commit()
    return digest


def load_registry() -> dict:
    with REGISTRY_PATH.open("r", encoding="utf-8") as stream:
        registry = json.load(stream)
    if int(registry.get("format", 0)) != 1:
        raise RuntimeError("unsupported incremental test registry format")
    return registry


def registry_task(script: Path, registry: dict) -> dict:
    relative = canonical_relative(script)
    matches = [task for task in registry["tasks"] if task["script"] == relative]
    if len(matches) != 1:
        raise RuntimeError(
            f"incremental test registry must contain exactly one task for {relative}; "
            f"found {len(matches)}"
        )
    return matches[0]


def tracked_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "-c", f"safe.directory={PROJECT_ROOT}", "ls-files", "-z"],
        cwd=PROJECT_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    return [
        PROJECT_ROOT / item.decode("utf-8", "surrogateescape")
        for item in completed.stdout.split(b"\0")
        if item
    ]


PATH_LITERAL = re.compile(
    r"(?P<value>(?:source|scripts|development|resource|environment)[\\/][^\r\n'\"`]+)",
    re.IGNORECASE,
)
FILE_LITERAL = re.compile(
    r"(?P<value>[^\r\n'\"`\\/]+\.(?:ps1|psm1|py|sh|c|h|json|yml|yaml|md|cfg|txt|patch))",
    re.IGNORECASE,
)
POWERSHELL_JOIN = re.compile(
    r"(?im)^\s*\$(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*Join-Path\s+"
    r"\$(?P<base>[A-Za-z_][A-Za-z0-9_]*)\s+['\"](?P<child>[^'\"]+)['\"]"
)


def clean_literal(value: str) -> str:
    value = value.strip().rstrip(".,;:)]}")
    value = value.replace("\\", "/")
    return value


def discover_inputs(script: Path, all_tracked: list[Path]) -> set[Path]:
    """Discover concrete repository files named directly by a script.

    Referenced scripts are inputs, but are deliberately not scanned transitively:
    tests frequently read other scripts as contract text without executing them.
    Aggregate entrypoints declare their wider case inputs in the registry.
    """
    support_files = {
        (SCRIPT_DIR / "incremental_test.py").resolve(),
        (SCRIPT_DIR / "_incremental_test.py").resolve(),
        (SCRIPT_DIR / "incremental test.ps1").resolve(),
    }
    discovered: set[Path] = {script.resolve(), *support_files}
    pending = [script.resolve()]
    by_name: dict[str, list[Path]] = {}
    for candidate in all_tracked:
        by_name.setdefault(candidate.name.casefold(), []).append(candidate.resolve())

    while pending:
        current = pending.pop()
        try:
            text = current.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeError):
            continue

        candidates: set[Path] = set()
        if current.suffix.casefold() in {".ps1", ".psm1"}:
            variables: dict[str, Path] = {
                "projectroot": PROJECT_ROOT,
                "psscriptroot": current.parent,
            }
            unresolved = list(POWERSHELL_JOIN.finditer(text))
            for _ in range(len(unresolved) + 1):
                changed = False
                for match in unresolved:
                    name = match.group("name").casefold()
                    base = variables.get(match.group("base").casefold())
                    if name in variables or base is None:
                        continue
                    variables[name] = (base / clean_literal(match.group("child"))).resolve()
                    changed = True
                if not changed:
                    break
            candidates.update(path for path in variables.values() if path.is_file())

        if current.suffix.casefold() == ".py":
            try:
                tree = ast.parse(text, filename=str(current))
            except SyntaxError:
                tree = None

            def path_parts(node: ast.AST) -> list[str] | None:
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                    left = path_parts(node.left)
                    right = path_parts(node.right)
                    if left is not None and right is not None:
                        return left + right
                    return None
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    return [node.value]
                if isinstance(node, (ast.Name, ast.Attribute, ast.Call)):
                    return []
                return None

            if tree is not None:
                for node in ast.walk(tree):
                    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
                        continue
                    parts = path_parts(node)
                    if not parts:
                        continue
                    candidate = PROJECT_ROOT.joinpath(*parts).resolve()
                    if candidate.is_file():
                        candidates.add(candidate)
        for match in PATH_LITERAL.finditer(text):
            literal = clean_literal(match.group("value"))
            candidate = PROJECT_ROOT / literal
            if candidate.exists():
                if candidate.is_file():
                    candidates.add(candidate.resolve())

        for match in FILE_LITERAL.finditer(text):
            name = clean_literal(match.group("value")).split("/")[-1]
            matches = by_name.get(name.casefold(), [])
            if len(matches) == 1:
                candidates.add(matches[0])
            for base in (current.parent, SCRIPT_DIR, PROJECT_ROOT):
                candidate = (base / clean_literal(match.group("value"))).resolve()
                if candidate.is_file():
                    candidates.add(candidate)

        for candidate in candidates:
            if candidate in discovered:
                continue
            discovered.add(candidate)
    return discovered


def expand_patterns(patterns: Iterable[str]) -> set[Path]:
    expanded: set[Path] = set()
    for pattern in patterns:
        normalized = pattern.replace("\\", "/")
        if any(character in normalized for character in "*?["):
            for path in PROJECT_ROOT.glob(normalized):
                if path.is_file():
                    expanded.add(path.resolve())
            continue
        path = (PROJECT_ROOT / normalized).resolve()
        if path.is_dir():
            expanded.update(item.resolve() for item in path.rglob("*") if item.is_file())
        elif path.is_file():
            expanded.add(path)
        else:
            # Missing declared inputs are part of the identity and must not silently vanish.
            expanded.add(path)
    return expanded


def command_output(command: list[str], timeout: int = 20) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"unavailable:{type(error).__name__}:{error}"
    return f"exit={completed.returncode}\n{completed.stdout.strip()}"


def environment_identity(profile: str, script: Path) -> dict[str, str]:
    identity = {
        "platform": sys.platform,
        "platform_release": platform.platform(),
        "python": sys.version,
        "script_kind": script.suffix.casefold(),
    }
    if script.suffix.casefold() == ".ps1":
        identity["pwsh"] = command_output(
            ["pwsh", "-NoLogo", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"]
        )
    if profile in {"wsl", "qemu", "vm", "physical"}:
        if os.name == "nt":
            identity["wsl"] = command_output(
                [
                    "wsl.exe", "-d", "Ubuntu", "--exec", "sh", "-c",
                    "uname -srmo; python3 --version; sha256sum /etc/os-release 2>/dev/null || true",
                ]
            )
        else:
            identity["linux"] = command_output(
                ["sh", "-c", "uname -srmo; python3 --version; sha256sum /etc/os-release 2>/dev/null || true"]
            )
    if profile == "qemu":
        executable = "qemu-system-x86_64.exe" if os.name == "nt" else "qemu-system-x86_64"
        identity["qemu"] = command_output([executable, "--version"])
    if profile == "vm":
        vbox = shutil.which("VBoxManage") or r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
        identity["virtualbox"] = command_output([vbox, "--version"])
        vmrun = shutil.which("vmrun") or r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe"
        identity["vmware"] = command_output([vmrun])
    if profile == "physical" and os.name == "nt":
        identity["storage"] = command_output(
            [
                "pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                "Get-Disk | Sort-Object Number | Select-Object Number,UniqueId,SerialNumber,Size,PartitionStyle,OperationalStatus | ConvertTo-Json -Compress",
            ]
        )
    return identity


def task_identity(script: Path, arguments: list[str]) -> tuple[dict, dict]:
    registry = load_registry()
    task = registry_task(script, registry)
    use_discovery = task.get("discover", True)
    inputs = (
        discover_inputs(script, tracked_files())
        if use_discovery
        else {
            script.resolve(),
            (SCRIPT_DIR / "incremental_test.py").resolve(),
            (SCRIPT_DIR / "_incremental_test.py").resolve(),
            (SCRIPT_DIR / "incremental test.ps1").resolve(),
        }
    )
    patterns = list(task.get("inputs", []))
    folded_arguments = {argument.casefold() for argument in arguments}
    for marker, selected_patterns in task.get("inputs_by_arg", {}).items():
        if marker.casefold() in folded_arguments:
            patterns.extend(selected_patterns)
    for rule in task.get("inputs_unless_arg", []):
        if rule["arg"].casefold() not in folded_arguments:
            patterns.extend(rule["inputs"])
    inputs.update(expand_patterns(patterns))
    argument_labels: dict[Path, str] = {}
    normalized_arguments: list[str] = []
    for index, argument in enumerate(arguments):
        if argument.startswith("-"):
            normalized_arguments.append(argument)
            continue
        candidate = Path(argument)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        if candidate.exists() and candidate.resolve() == PROJECT_ROOT.resolve():
            normalized_arguments.append("@project-root")
            continue
        if candidate.is_file():
            resolved = candidate.resolve()
            inputs.add(resolved)
            argument_labels[resolved] = f"argument:{index}:{resolved.name}"
            normalized_arguments.append(f"@input:{index}:{resolved.name}")
        elif candidate.is_dir():
            resolved_root = candidate.resolve()
            for item in resolved_root.rglob("*"):
                if item.is_file():
                    resolved = item.resolve()
                    inputs.add(resolved)
                    argument_labels[resolved] = (
                        f"argument:{index}/" + resolved.relative_to(resolved_root).as_posix()
                    )
            normalized_arguments.append(f"@input-tree:{index}")
        else:
            normalized_arguments.append(argument)
    connection = digest_connection()
    try:
        input_records = []
        for path in sorted(inputs, key=lambda item: canonical_relative(item).casefold()):
            relative = argument_labels.get(path.resolve(), canonical_relative(path))
            if not path.is_file():
                input_records.append({"path": relative, "missing": True})
            else:
                input_records.append(
                    {"path": relative, "bytes": path.stat().st_size, "sha256": file_digest(path, connection)}
                )
    finally:
        connection.close()

    profile = task.get("profile", "pure")
    for marker, selected_profile in task.get("profile_by_arg", {}).items():
        if marker.casefold() in folded_arguments:
            profile = selected_profile
            break
    payload = {
        "schema": SCHEMA,
        "task": task["id"],
        "definition": task,
        "arguments": normalized_arguments,
        "inputs": input_records,
        "environment": environment_identity(profile, script),
    }
    key = sha256_bytes(canonical_json(payload))
    return task, {"key": key, "payload": payload}


def result_path(task_id: str, key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", task_id)
    return RESULT_ROOT / safe / f"{key}.json"


def evidence_root(task_id: str, key: str) -> Path:
    return result_path(task_id, key).with_suffix(".evidence")


def output_records(task: dict) -> list[dict]:
    outputs = expand_patterns(task.get("outputs", []))
    connection = digest_connection()
    try:
        records = []
        for path in sorted(outputs, key=lambda item: canonical_relative(item).casefold()):
            if not path.is_file():
                records.append({"path": canonical_relative(path), "missing": True})
            else:
                records.append({"path": canonical_relative(path), "sha256": file_digest(path, connection)})
        return records
    finally:
        connection.close()


def reusable(task: dict, identity: dict) -> bool:
    path = result_path(task["id"], identity["key"])
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if record.get("status") != "passed" or record.get("key") != identity["key"]:
        return False
    if record.get("outputs", []) != output_records(task):
        return False
    connection = digest_connection()
    try:
        for evidence in record.get("evidence", []):
            archived = evidence_root(task["id"], identity["key"]) / evidence["path"]
            if not archived.is_file() or file_digest(archived, connection) != evidence["sha256"]:
                return False
    finally:
        connection.close()
    return True


def archive_evidence(task: dict, key: str) -> list[dict]:
    patterns = task.get("evidence", [])
    if not patterns:
        return []
    paths = expand_patterns(patterns)
    destination_root = evidence_root(task["id"], key)
    temporary_root = destination_root.with_name(f".{destination_root.name}.{os.getpid()}.tmp")
    if temporary_root.exists():
        shutil.rmtree(temporary_root)
    temporary_root.mkdir(parents=True)
    connection = digest_connection()
    records: list[dict] = []
    try:
        for source in sorted(paths, key=lambda item: canonical_relative(item).casefold()):
            if not source.is_file():
                continue
            relative = canonical_relative(source)
            destination = temporary_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            records.append({"path": relative, "sha256": file_digest(destination, connection)})
    finally:
        connection.close()
    if destination_root.exists():
        shutil.rmtree(destination_root)
    os.replace(temporary_root, destination_root)
    return records


@contextlib.contextmanager
def task_lock(task_id: str, key: str):
    ensure_state()
    lock = LOCK_ROOT / f"{sha256_bytes(f'{task_id}:{key}'.encode())}.lock"
    started = time.monotonic()
    stream = lock.open("a+b")
    stream.seek(0, os.SEEK_END)
    if stream.tell() == 0:
        stream.write(b"\0")
        stream.flush()
    acquired = False
    while not acquired:
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            if time.monotonic() - started > 6 * 60 * 60:
                stream.close()
                raise TimeoutError(f"timed out waiting for incremental task lock: {task_id}")
            time.sleep(0.1)
    try:
        yield
    finally:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def execute(script: Path, arguments: list[str], task: dict, identity: dict) -> int:
    relative = canonical_relative(script)
    if os.environ.get(ACTIVE_SCRIPT) == relative:
        return -1
    if task.get("uncacheable") or any(
        marker.casefold() in {argument.casefold() for argument in arguments}
        for marker in task.get("uncacheable_when_args", [])
    ):
        state = "EXECUTE"
    elif reusable(task, identity):
        print(f"REUSED {task['id']} - input key {identity['key'][:12]}", flush=True)
        return 0
    else:
        state = "EXECUTE"

    with task_lock(task["id"], identity["key"]):
        if not task.get("uncacheable") and reusable(task, identity):
            print(f"REUSED {task['id']} - input key {identity['key'][:12]}", flush=True)
            return 0
        print(f"{state} {task['id']} - input key {identity['key'][:12]}", flush=True)
        environment = os.environ.copy()
        environment[ACTIVE_SCRIPT] = relative
        if script.suffix.casefold() == ".ps1":
            serialized_invocation = environment.get(
                "T1OS_INCREMENTAL_POWERSHELL_INVOCATION"
            )
            if serialized_invocation:
                environment["T1OS_INCREMENTAL_POWERSHELL_SCRIPT"] = str(script)
                powershell = """$ErrorActionPreference='Stop'
$xml=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:T1OS_INCREMENTAL_POWERSHELL_INVOCATION))
$invocation=[Management.Automation.PSSerializer]::Deserialize($xml)
$bound=@{}
foreach($item in @($invocation.Parameters)){
    if($null -ne $item -and -not [string]::IsNullOrEmpty([string]$item.Name)){
        $bound[[string]$item.Name]=$item.Value
    }
}
$unbound=@($invocation.Unbound | Where-Object { $null -ne $_ })
& $env:T1OS_INCREMENTAL_POWERSHELL_SCRIPT @bound @unbound
if(-not $?){exit 1}
"""
                command = [
                    "pwsh", "-NoLogo", "-NoProfile", "-NonInteractive",
                    "-ExecutionPolicy", "Bypass", "-Command", powershell,
                ]
            else:
                command = [
                    "pwsh", "-NoLogo", "-NoProfile", "-NonInteractive",
                    "-ExecutionPolicy", "Bypass", "-File", str(script), *arguments,
                ]
        elif script.suffix.casefold() == ".sh":
            command = ["bash", str(script), *arguments]
        else:
            command = [sys.executable, str(script), *arguments]
        completed = subprocess.run(command, cwd=PROJECT_ROOT, env=environment, check=False)
        if completed.returncode != 0:
            return int(completed.returncode)
        if not task.get("uncacheable"):
            evidence = archive_evidence(task, identity["key"])
            record = {
                "format": 1,
                "task": task["id"],
                "key": identity["key"],
                "status": "passed",
                "completed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "identity": identity["payload"],
                "outputs": output_records(task),
                "evidence": evidence,
            }
            atomic_json(result_path(task["id"], identity["key"]), record)
        return 0


def audited_scripts() -> set[str]:
    result: set[str] = set()
    for path in SCRIPT_DIR.iterdir():
        if path.is_file() and path.suffix.casefold() in {".ps1", ".py", ".sh"}:
            if re.match(r"^(test|validate|audit)(?:\s|\.|$)", path.name, re.IGNORECASE):
                result.add(canonical_relative(path))
    roothealth = SCRIPT_DIR / "roothealth-repair"
    for path in roothealth.rglob("*"):
        if ".journal-integration-v2-work" in path.parts or not path.is_file():
            continue
        if path.suffix.casefold() in {".ps1", ".py", ".sh"} and re.match(
            r"^(test|verify|check|validate)(?:[-\s.]|$)", path.name, re.IGNORECASE
        ):
            result.add(canonical_relative(path))
    tests_root = SCRIPT_DIR / "tests"
    if tests_root.is_dir():
        for path in tests_root.rglob("*"):
            if path.is_file() and path.suffix.casefold() in {".ps1", ".py", ".sh"}:
                result.add(canonical_relative(path))
    return result


def audit_registry() -> int:
    registry = load_registry()
    registered = {task["script"] for task in registry["tasks"]}
    actual = audited_scripts()
    missing = sorted(actual - registered)
    stale = sorted(registered - actual)
    duplicate_ids = sorted(
        task_id for task_id in {task["id"] for task in registry["tasks"]}
        if sum(task["id"] == task_id for task in registry["tasks"]) != 1
    )
    guard_markers = {
        ".ps1": "Invoke-T1OSIncrementalTestGuard",
        ".py": "_t1os_incremental_guard",
        ".sh": "T1OS_INCREMENTAL_ACTIVE_SCRIPT",
    }
    unguarded = []
    for relative in sorted(actual & registered):
        path = PROJECT_ROOT / relative
        marker = guard_markers[path.suffix.casefold()]
        if marker not in path.read_text(encoding="utf-8", errors="replace"):
            unguarded.append(relative)
    if missing or stale or duplicate_ids or unguarded:
        if missing:
            print("Unregistered test scripts:\n  " + "\n  ".join(missing), file=sys.stderr)
        if stale:
            print("Stale registry scripts:\n  " + "\n  ".join(stale), file=sys.stderr)
        if duplicate_ids:
            print("Duplicate task IDs:\n  " + "\n  ".join(duplicate_ids), file=sys.stderr)
        if unguarded:
            print("Test scripts bypassing the incremental guard:\n  " + "\n  ".join(unguarded), file=sys.stderr)
        return 1
    print(f"Incremental test registry audit passed: {len(actual)} scripts registered.")
    return 0


def task_result_directory(task_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", task_id)
    return RESULT_ROOT / safe


def show_status() -> int:
    registry = load_registry()
    for task in registry["tasks"]:
        directory = task_result_directory(task["id"])
        records = list(directory.glob("*.json")) if directory.is_dir() else []
        print(f"{task['id']}\t{len(records)} passing input key(s)")
    return 0


def invalidate_task(task_id: str) -> int:
    registry = load_registry()
    known = {task["id"] for task in registry["tasks"]}
    if task_id not in known:
        print(f"Unknown incremental test task: {task_id}", file=sys.stderr)
        return 2
    directory = task_result_directory(task_id)
    if directory.is_dir():
        shutil.rmtree(directory)
        print(f"Invalidated cached passing results for {task_id}.")
    else:
        print(f"No cached passing results exist for {task_id}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--script", required=True)
    run_parser.add_argument("arguments", nargs=argparse.REMAINDER)
    explain_parser = subparsers.add_parser("explain")
    explain_parser.add_argument("--script", required=True)
    explain_parser.add_argument("arguments", nargs=argparse.REMAINDER)
    subparsers.add_parser("audit")
    subparsers.add_parser("status")
    subparsers.add_parser("list")
    invalidate_parser = subparsers.add_parser("invalidate")
    invalidate_parser.add_argument("--task", required=True)
    options = parser.parse_args()

    if options.command == "audit":
        return audit_registry()
    if options.command == "status":
        return show_status()
    if options.command == "list":
        for task in load_registry()["tasks"]:
            print(f"{task['id']}\t{task['script']}")
        return 0
    if options.command == "invalidate":
        return invalidate_task(options.task)
    script = Path(options.script).resolve()
    arguments = list(options.arguments)
    if arguments and arguments[0] == "--":
        arguments.pop(0)
    task, identity = task_identity(script, arguments)
    if options.command == "explain":
        print(json.dumps({
            "task": task["id"], "key": identity["key"],
            "reusable": reusable(task, identity), "identity": identity["payload"],
        }, indent=2, sort_keys=True))
        return 0
    result = execute(script, arguments, task, identity)
    return 0 if result == -1 else result


if __name__ == "__main__":
    raise SystemExit(main())
