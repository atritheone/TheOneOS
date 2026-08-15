#!/usr/bin/env python3
"""Turn the verified CPython 3.14 archive into a non-promoted T1OS runtime."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile


REPO = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO / "source" / "python" / "locks" / "python-3.14.7-candidate.json"
RUNTIME_CONFIG = REPO / "source" / "python" / "build" / "runtime.json"
DEVELOPMENT = REPO / "development" / "python 3.14 candidate"
CACHE = DEVELOPMENT / "cache"
PUBLISHED = DEVELOPMENT / "t1os"
STAGE = Path("/tmp/t1os-python-3.14.7-package")
SOFTWARE = STAGE / "software" / "python"
CATALOGUE = STAGE / "catalogue" / "python"
IMAGE = STAGE / "catalogue" / "image"
BUILD_SOFTWARE = STAGE / "build"
BOOT = STAGE / "boot"
VIRTUALBOX_SOFTWARE = STAGE / "software" / "virtualbox"
MANIFEST = STAGE / "manifest.json"
BOOT_RELEASE = STAGE / "boot-release.json"
CANONICAL_SOFTWARE = "/the one/software/python"
CANONICAL_CATALOGUE = "/the one/catalogue/python"
CANONICAL_IMAGE = "/the one/catalogue/image"
PROFILED_SHEBANG = b'#!"/the one/software/python/bin/python" -B\n'


class PackageFailure(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_profiled_python_policy() -> tuple[dict, set[tuple[str, str]]]:
    config = json.loads(RUNTIME_CONFIG.read_text(encoding="utf-8"))
    policy = config.get("profiled_python_entrypoints")
    if not isinstance(policy, dict) or set(policy) != {
        "format", "owner", "group", "install_mode", "shebang", "entries"
    }:
        raise PackageFailure("Profiled Python entrypoint policy is malformed")
    if (
        policy["format"] != 1
        or policy["owner"] != 0
        or policy["group"] != 0
        or policy["install_mode"] != "0555"
        or policy["shebang"] != PROFILED_SHEBANG.decode("ascii")
        or not isinstance(policy["entries"], list)
        or not policy["entries"]
    ):
        raise PackageFailure("Profiled Python entrypoint policy is not fail-closed")
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
            raise PackageFailure("Profiled Python entrypoint record is malformed")
        root_name = entry["root"]
        relative = entry["path"]
        destination = entry["destination"]
        if root_name not in roots or not isinstance(relative, str) or not isinstance(destination, str):
            raise PackageFailure("Profiled Python entrypoint identity is malformed")
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
            raise PackageFailure(f"Unsafe profiled Python entrypoint: {relative!r}")
        expected_destination = roots[root_name]["destination"].rstrip("/") + "/" + relative
        if destination != expected_destination:
            raise PackageFailure(f"Profiled Python destination differs: {destination}")
        identity = (root_name, relative)
        if identity in identities or destination in destinations:
            raise PackageFailure(f"Duplicate profiled Python entrypoint: {destination}")
        source = REPO / roots[root_name]["source"] / Path(*parsed.parts)
        try:
            mode = source.lstat().st_mode
            payload = source.read_bytes()
        except OSError as error:
            raise PackageFailure(f"Could not inspect profiled Python entrypoint {source}: {error}") from error
        if source.is_symlink() or not stat.S_ISREG(mode):
            raise PackageFailure(f"Profiled Python entrypoint is not a regular file: {source}")
        if payload.startswith(b"\xef\xbb\xbf") or not payload.startswith(PROFILED_SHEBANG):
            raise PackageFailure(
                f"Profiled Python entrypoint lacks the exact byte-0 LF shebang: {source}"
            )
        identities.add(identity)
        destinations.add(destination)
        ordered_destinations.append(destination)
    if ordered_destinations != sorted(ordered_destinations):
        raise PackageFailure("Profiled Python entrypoint inventory is not canonically ordered")
    return policy, identities


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
        raise PackageFailure(
            f"Command failed ({result.returncode}): {' '.join(command)}\n{result.stdout.strip()}"
        )
    return result.stdout


def remove_published_candidate() -> None:
    """Remove only the generated published candidate, including read-only files."""

    if not PUBLISHED.exists():
        return
    published = PUBLISHED.resolve()
    development = DEVELOPMENT.resolve()
    if PUBLISHED.is_symlink() or published.parent != development:
        raise PackageFailure(f"Refusing unsafe candidate cleanup: {PUBLISHED}")

    def make_removable(function, path, _error):
        os.chmod(path, 0o700 if os.path.isdir(path) else 0o600)
        function(path)

    shutil.rmtree(PUBLISHED, onerror=make_removable)


def validate_file(path: Path, record: dict) -> None:
    if (
        not path.is_file()
        or path.stat().st_size != int(record["size"])
        or sha256_file(path) != str(record["sha256"])
    ):
        raise PackageFailure(f"Locked input differs: {path}")


def load_lock() -> dict:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if lock.get("python_version") != "3.14.7" or lock.get("python_abi") != "cp314":
        raise PackageFailure("Candidate lock does not describe CPython 3.14.7/cp314")
    return lock


def reset_stage() -> None:
    stage = STAGE.resolve()
    if stage != Path("/tmp/t1os-python-3.14.7-package"):
        raise PackageFailure(f"Unsafe stage path: {stage}")
    if STAGE.exists():
        if STAGE.is_symlink():
            raise PackageFailure("Refusing to remove a symbolic-link stage")
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)


def extract_source(archive_path: Path) -> None:
    extract_root = STAGE / ".extract"
    extract_root.mkdir()
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(extract_root, filter="data")
    roots = [path for path in extract_root.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise PackageFailure("Source candidate archive has an unexpected root layout")
    shutil.move(str(roots[0]), str(SOFTWARE))
    extract_root.rmdir()
    for link in sorted((path for path in SOFTWARE.rglob("*") if path.is_symlink()), key=str):
        target = link.resolve(strict=True)
        if SOFTWARE.resolve() not in target.parents or not target.is_file():
            raise PackageFailure(f"Unsafe or non-file archive link: {link}")
        data = target.read_bytes()
        mode = stat.S_IMODE(target.stat().st_mode)
        link.unlink()
        link.write_bytes(data)
        link.chmod(mode)


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def slim_runtime() -> None:
    for relative in (
        "include",
        "share",
        "lib/pkgconfig",
        "lib/python3.14/config-3.14-x86_64-linux-gnu",
        "lib/python3.14/tkinter",
        "lib/python3.14/idlelib",
        "lib/python3.14/turtledemo",
        "lib/python3.14/ensurepip",
        "lib/python3.14/venv",
        "lib/python3.14/site-packages/pip",
        "lib/python3.14/curses/panel.py",
        "lib/python3.14/dbm/gnu.py",
        "lib/python3.14/dbm/ndbm.py",
        "lib/python3.14/turtle.py",
    ):
        remove_path(SOFTWARE / relative)
    for path in (SOFTWARE / "lib" / "python3.14" / "site-packages").glob("pip-*.dist-info"):
        remove_path(path)
    for relative in ("lib/libpython3.14.a",):
        remove_path(SOFTWARE / relative)
    bin_root = SOFTWARE / "bin"
    for path in bin_root.iterdir():
        if path.name != "python3.14":
            remove_path(path)
    dynload = SOFTWARE / "lib" / "python3.14" / "lib-dynload"
    for pattern in (
        "_curses_panel.cpython-314-*.so",
        "_dbm.cpython-314-*.so",
        "_gdbm.cpython-314-*.so",
        "_tkinter.cpython-314-*.so",
        "_uuid.cpython-314-*.so",
    ):
        for path in dynload.glob(pattern):
            path.unlink()
    marker = SOFTWARE / "lib" / "python3.14" / "EXTERNALLY-MANAGED"
    marker.write_text(
        "[externally-managed]\nError=Use the Python directives in Brick to change T1OS Python modules.\n",
        encoding="utf-8",
        newline="\n",
    )


def extract_wheel(path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            member = Path(info.filename)
            mode = info.external_attr >> 16
            if (
                member.is_absolute()
                or ".." in member.parts
                or stat.S_ISLNK(mode)
                or stat.S_ISCHR(mode)
                or stat.S_ISBLK(mode)
                or stat.S_ISFIFO(mode)
            ):
                raise PackageFailure(f"Unsafe wheel member in {path.name}: {info.filename}")
        archive.extractall(destination)


def install_runtime_packages(lock: dict) -> None:
    site = SOFTWARE / "lib" / "python3.14" / "site-packages"
    by_name = {item["name"].lower(): item for item in lock["runtime_wheels"]}
    for package in ("freetype-py", "pyroute2"):
        item = by_name[package]
        wheel = CACHE / item["filename"]
        validate_file(wheel, item)
        extract_wheel(wheel, site)
    pillow = by_name["pillow"]
    pillow_wheel = CACHE / pillow["filename"]
    validate_file(pillow_wheel, pillow)
    extract_wheel(pillow_wheel, IMAGE)
    package_sources = {item["name"]: item for item in lock["t1os_packages"]}
    for source_name in ("sitecustomize.py", "t1os-ca-certificates.pth"):
        item = package_sources[source_name]
        source = REPO / item["path"]
        validate_file(source, item)
        shutil.copy2(source, site / source_name)
    for empty in site.rglob("freetype_py.libs"):
        if empty.is_dir() and not any(empty.iterdir()):
            empty.rmdir()


def copy_native_catalogue() -> None:
    source = REPO / "source" / "catalogue" / "python"
    if not source.is_dir():
        raise PackageFailure("The current T1OS native catalogue is missing")
    shutil.copytree(source, CATALOGUE)


def copy_t1os_sources() -> None:
    def ignore_generated(_directory: str, names: list[str]) -> set[str]:
        return {
            name for name in names
            if name == "__pycache__" or name.endswith((".pyc", ".pyo"))
        }

    for source, destination in (
        (REPO / "source" / "build software", BUILD_SOFTWARE),
        (REPO / "source" / "boot", BOOT),
        (REPO / "source" / "software" / "virtualbox", VIRTUALBOX_SOFTWARE),
    ):
        shutil.copytree(source, destination, ignore=ignore_generated)


def elf_files(root: Path) -> list[Path]:
    def is_elf(path: Path) -> bool:
        if not path.is_file():
            return False
        with path.open("rb") as stream:
            return stream.read(4) == b"\x7fELF"

    return sorted(
        (path for path in root.rglob("*") if is_elf(path)),
        key=lambda path: path.as_posix(),
    )


def patch_elfs() -> None:
    python = SOFTWARE / "bin" / "python3.14"
    run(["patchelf", "--set-interpreter", f"{CANONICAL_CATALOGUE}/ld-linux-x86-64.so.2", str(python)])
    for path in elf_files(SOFTWARE):
        if path.name != "python.o":
            run(["patchelf", "--set-rpath", CANONICAL_CATALOGUE, str(path)])
    image_runpath = f"{CANONICAL_IMAGE}/pillow.libs:{CANONICAL_IMAGE}:{CANONICAL_CATALOGUE}"
    for path in elf_files(IMAGE):
        declared = set(needed(path))
        for merged_library in ("libpthread.so.0", "libdl.so.2", "librt.so.1"):
            if merged_library in declared:
                run(["patchelf", "--replace-needed", merged_library, "libc.so.6", str(path)])
        run(["patchelf", "--set-rpath", image_runpath, str(path)])


def install_compatibility_entrypoint() -> None:
    """Install the stable T1OS command plus a temporary pre-3.14 compatibility name."""
    source = SOFTWARE / "bin" / "python3.14"
    shutil.copy2(source, SOFTWARE / "bin" / "python")
    shutil.copy2(source, SOFTWARE / "bin" / "python3.13")


def remove_bytecode() -> None:
    for path in sorted(STAGE.rglob("*.pyc")):
        path.unlink()
    for path in sorted((p for p in STAGE.rglob("__pycache__") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if not any(path.iterdir()):
            path.rmdir()


def target_command(program: list[str]) -> list[str]:
    local_library_path = ":".join((str(IMAGE / "pillow.libs"), str(IMAGE), str(CATALOGUE)))
    return [
        str(CATALOGUE / "ld-linux-x86-64.so.2"),
        "--library-path",
        local_library_path,
        str(SOFTWARE / "bin" / "python3.14"),
        *program,
    ]


def compile_bytecode() -> None:
    environment = os.environ.copy()
    environment.update({"PYTHONNOUSERSITE": "1", "PYTHONPATH": "", "PYTHONHASHSEED": "0"})
    run(
        target_command(
            [
                "-B", "-S", "-m", "compileall", "-q", "-f", "-j", "1",
                "--invalidation-mode", "checked-hash", "-s", str(SOFTWARE),
                "-p", CANONICAL_SOFTWARE, str(SOFTWARE),
            ]
        ),
        env=environment,
    )
    run(
        target_command(
            [
                "-B", "-S", "-m", "compileall", "-q", "-f", "-j", "1",
                "--invalidation-mode", "checked-hash", "-s", str(IMAGE),
                "-p", CANONICAL_IMAGE, str(IMAGE),
            ]
        ),
        env=environment,
    )


def verify_no_links() -> None:
    links = [path for path in STAGE.rglob("*") if path.is_symlink()]
    if links:
        raise PackageFailure(f"Packaged candidate contains symbolic links: {links[:5]}")


def needed(path: Path) -> list[str]:
    output = run(["readelf", "-d", str(path)])
    return re.findall(r"Shared library: \[([^]]+)\]", output)


def verify_native_closure() -> dict:
    roots = [SOFTWARE, CATALOGUE, IMAGE]
    elfs = [path for root in roots for path in elf_files(root)]
    providers: dict[str, Path] = {}
    for path in elfs:
        providers.setdefault(path.name, path)
        output = run(["readelf", "-d", str(path)])
        match = re.search(r"Library soname: \[([^]]+)\]", output)
        if match:
            providers.setdefault(match.group(1), path)
    unresolved: dict[str, list[str]] = {}
    edges = 0
    for path in elfs:
        missing = []
        for name in needed(path):
            edges += 1
            if name not in providers:
                missing.append(name)
        if missing:
            unresolved[path.relative_to(STAGE).as_posix()] = sorted(set(missing))
    if unresolved:
        raise PackageFailure(f"Candidate native closure is incomplete: {unresolved}")
    return {"elf_files": len(elfs), "needed_edges": edges, "unresolved": 0}


def verify_bytecode() -> dict:
    script = r'''
import importlib.util, json, marshal, pathlib, sys, types
pairs=[(pathlib.Path(sys.argv[1]),"/the one/software/python"),(pathlib.Path(sys.argv[2]),"/the one/catalogue/image")]
count=codes=0
for root,canonical in pairs:
    for pyc in root.rglob("*.pyc"):
        data=pyc.read_bytes(); count+=1
        assert data[:4]==importlib.util.MAGIC_NUMBER,(pyc,"magic")
        assert int.from_bytes(data[4:8],"little")==3,(pyc,"flags")
        source=pyc.parent.parent/(pyc.name.split(".cpython-314",1)[0]+".py")
        assert source.is_file(),(pyc,"source")
        assert data[8:16]==importlib.util.source_hash(source.read_bytes()),(pyc,"source hash")
        stack=[marshal.loads(data[16:])]
        while stack:
            value=stack.pop(); codes+=1
            assert value.co_filename.startswith(canonical+"/"),(pyc,value.co_filename)
            assert "/mnt/" not in value.co_filename and "/ppp-marker/" not in value.co_filename
            stack.extend(item for item in value.co_consts if isinstance(item,types.CodeType))
print(json.dumps({"checked_hash_pycs":count,"canonical_code_objects":codes},sort_keys=True))
'''
    environment = {
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": "",
    }
    output = run(
        target_command(["-B", "-S", "-c", script, str(SOFTWARE), str(IMAGE)]),
        env=environment,
    )
    return json.loads(output.strip().splitlines()[-1])


def verify_t1os_consumers() -> dict:
    script = r'''
import builtins, importlib, io, json, os, sys
sys.path.insert(0,sys.argv[1]); sys.path.insert(0,sys.argv[2])
results={}
for name in ("graphics.graphics","network.network","expanse.expanse","brick.brick"):
    original_open=builtins.open
    def isolated_open(file,*args,**kwargs):
        if name=="brick.brick" and os.fspath(file)=="/the one/settings/t1osversion.txt":
            return io.StringIO("0.31\n")
        return original_open(file,*args,**kwargs)
    try:
        builtins.open=isolated_open
        importlib.import_module(name); results[name]=True
    except Exception as error: results[name]=f"{type(error).__name__}: {error}"
    finally: builtins.open=original_open
print(json.dumps(results,sort_keys=True))
'''
    environment = {
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": "",
        "T1OS_IMAGE_CATALOGUE": str(IMAGE),
    }
    output = run(
        target_command(
            [
                "-B", "-P", "-c", script,
                str(BUILD_SOFTWARE), str(IMAGE),
            ]
        ),
        env=environment,
    )
    result = json.loads(output.strip().splitlines()[-1])
    failures = {name: value for name, value in result.items() if value is not True}
    if failures:
        raise PackageFailure(f"Critical T1OS consumer imports failed: {failures}")
    return result


def smoke_test() -> dict:
    dynload = SOFTWARE / "lib" / "python3.14" / "lib-dynload"
    modules = sorted(
        {
            path.name.split(".cpython-314-", 1)[0]
            for path in dynload.glob("*.cpython-314-*.so")
        }
    )
    script = r'''
import datetime, importlib, importlib.metadata, importlib.util, io, json, os, pathlib, sys
sys.path.insert(0, os.environ["T1OS_IMAGE_CATALOGUE"])
failed={}
for name in json.loads(os.environ["T1OS_EXTENSION_MODULES"]):
    try: importlib.import_module(name)
    except Exception as error: failed[name]=f"{type(error).__name__}: {error}"
import PIL, freetype, pyroute2
from PIL import Image
formats={}
for fmt in ("PNG","JPEG","GIF","BMP","WEBP"):
    stream=io.BytesIO(); Image.new("RGB",(3,2),(10,20,30)).save(stream,format=fmt)
    stream.seek(0); loaded=Image.open(stream); loaded.load(); formats[fmt]=loaded.size
print(json.dumps({"python":sys.version.split()[0],"safe_path":sys.flags.safe_path,
"dont_write_bytecode":sys.dont_write_bytecode,"prefix":sys.prefix,
"pillow":PIL.__version__,"freetype_py":importlib.metadata.version("freetype-py"),
"freetype_native":".".join(map(str,freetype.version())),"pyroute2":pyroute2.__version__,
"extensions":len(json.loads(os.environ["T1OS_EXTENSION_MODULES"])),"failed":failed,
"formats":formats,"atreyan_year":datetime.datetime.now().year,
"pip_available":importlib.util.find_spec("pip") is not None},sort_keys=True))
'''
    environment = {
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": "",
        "PYTHONHASHSEED": "0",
        "T1OS_IMAGE_CATALOGUE": str(IMAGE),
        "T1OS_EXTENSION_MODULES": json.dumps(modules),
    }
    output = run(target_command(["-B", "-P", "-c", script]), env=environment)
    result = json.loads(output.strip().splitlines()[-1])
    if result["python"] != "3.14.7" or result["failed"] or result["pip_available"]:
        raise PackageFailure(f"T1OS candidate smoke test failed: {result}")
    if any((SOFTWARE / "bin" / name).exists() for name in ("pip", "pip3", "pip3.14")):
        raise PackageFailure("The T1OS runtime exposes a forbidden pip command")
    if result["pillow"] != "12.3.0" or result["pyroute2"] != "0.9.4":
        raise PackageFailure(f"T1OS candidate package versions differ: {result}")
    compatibility = run(
        [
            str(CATALOGUE / "ld-linux-x86-64.so.2"),
            "--library-path",
            ":".join((str(IMAGE / "pillow.libs"), str(IMAGE), str(CATALOGUE))),
            str(SOFTWARE / "bin" / "python3.13"),
            "-B", "-P", "-c", "import sys; print(sys.version.split()[0])",
        ],
        env=environment,
    ).strip()
    if compatibility != "3.14.7":
        raise PackageFailure(f"python3.13 compatibility entrypoint failed: {compatibility}")
    result["python3.13_compatibility_entrypoint"] = compatibility
    stable = run(
        [
            str(CATALOGUE / "ld-linux-x86-64.so.2"),
            "--library-path",
            ":".join((str(IMAGE / "pillow.libs"), str(IMAGE), str(CATALOGUE))),
            str(SOFTWARE / "bin" / "python"),
            "-B", "-P", "-c", "import sys; print(sys.version.split()[0])",
        ],
        env=environment,
    ).strip()
    if stable != "3.14.7":
        raise PackageFailure(f"Stable T1OS python entrypoint failed: {stable}")
    result["stable_python_entrypoint"] = stable
    service_environment = dict(environment)
    service_environment["T1OS_SYSTEM_ROOT"] = str(STAGE)
    service = json.loads(run(
        target_command([
            "-B", "-P", str(BUILD_SOFTWARE / "python" / "python.py"),
            "diagnostic",
        ]),
        env=service_environment,
    ))
    if not service.get("passed") or "pip" in service or not service.get("resolver"):
        raise PackageFailure(f"T1OS Python module service diagnostic failed: {service}")
    result["module_service"] = "passed"
    return result


def file_records(
    root: Path, area: str, profiled: set[tuple[str, str]]
) -> list[dict]:
    records = []
    for directory in (path for path in root.rglob("*") if path.is_dir()):
        directory.chmod(0o755)
    for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.as_posix()):
        relative = path.relative_to(root).as_posix()
        with path.open("rb") as stream:
            elf = stream.read(4) == b"\x7fELF"
        is_profiled = (area, relative) in profiled
        executable = is_profiled or (
            not relative.endswith(".py")
            and ((area == "software" and relative.startswith("bin/")) or elf)
        )
        install_mode = "0555" if executable else "0444"
        path.chmod(int(install_mode, 8))
        records.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
                "install_mode": install_mode,
            }
        )
    return records


def main() -> int:
    try:
        lock = load_lock()
        profiled_policy, profiled = load_profiled_python_policy()
        source_record = lock["source_candidate"]
        source_archive = REPO / source_record["path"]
        validate_file(source_archive, source_record)
        reset_stage()
        extract_source(source_archive)
        slim_runtime()
        install_runtime_packages(lock)
        copy_native_catalogue()
        copy_t1os_sources()
        remove_bytecode()
        patch_elfs()
        install_compatibility_entrypoint()
        compile_bytecode()
        verify_no_links()
        closure = verify_native_closure()
        bytecode = verify_bytecode()
        smoke = smoke_test()
        consumers = verify_t1os_consumers()
        software_records = file_records(SOFTWARE, "software", profiled)
        catalogue_records = file_records(CATALOGUE, "catalogue", profiled)
        image_records = file_records(IMAGE, "image", profiled)
        build_records = file_records(BUILD_SOFTWARE, "build_software", profiled)
        boot_records = file_records(BOOT, "boot", profiled)
        virtualbox_records = file_records(
            VIRTUALBOX_SOFTWARE, "virtualbox_software", profiled
        )
        manifest = {
            "format": 1,
            "component": "t1os-python-candidate",
            "candidate_release": lock["candidate_release"],
            "python_version": lock["python_version"],
            "python_abi": lock["python_abi"],
            "promotable": False,
            "profiled_python_entrypoints": profiled_policy,
            "install_policy": {
                "owner": 0,
                "group": 0,
                "directory_mode": "0755",
                "regular_file_mode": "0444",
                "profiled_python_mode": "0555",
            },
            "source_archive": source_record,
            "destinations": {
                "software": CANONICAL_SOFTWARE,
                "catalogue": CANONICAL_CATALOGUE,
                "image": CANONICAL_IMAGE,
                "build_software": "/the one/build",
                "boot": "/boot",
                "virtualbox_software": "/the one/software/virtualbox",
            },
            "verification": {
                "native_closure": closure,
                "bytecode": bytecode,
                "smoke": smoke,
                "critical_t1os_consumers": consumers,
            },
            "payloads": {
                "software": software_records,
                "catalogue": catalogue_records,
                "image": image_records,
                "build_software": build_records,
                "boot": boot_records,
                "virtualbox_software": virtualbox_records,
            },
        }
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
        shutil.copy2(MANIFEST, SOFTWARE / "manifest.json")
        manifest_digest = sha256_file(MANIFEST)
        BOOT_RELEASE.write_text(
            json.dumps(
                {
                    "format": 1,
                    "component": "t1os-python-candidate-boot",
                    "release": lock["candidate_release"],
                    "manifest_sha256": manifest_digest,
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        remove_published_candidate()
        shutil.copytree(STAGE, PUBLISHED)
        published_manifest = PUBLISHED / "manifest.json"
        print(json.dumps({
            "manifest": published_manifest.relative_to(REPO).as_posix(),
            "manifest_sha256": manifest_digest,
            "software_files": len(software_records),
            "catalogue_files": len(catalogue_records),
            "image_files": len(image_records),
            "build_software_files": len(build_records),
            "boot_files": len(boot_records),
            "virtualbox_software_files": len(virtualbox_records),
            "verification": manifest["verification"],
        }, indent=2))
        return 0
    except (PackageFailure, OSError, json.JSONDecodeError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"package python 3.14 candidate: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
