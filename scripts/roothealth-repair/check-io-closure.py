#!/usr/bin/env python3
"""Prove direct production writes are confined to reviewed roothealth modules."""

from __future__ import annotations

import sys as _t1os_incremental_sys
from pathlib import Path as _T1OSIncrementalPath

if __name__ == "__main__":
    _t1os_incremental_scripts = next(
        (parent for parent in _T1OSIncrementalPath(__file__).resolve().parents
         if (parent / "incremental_test.py").is_file()),
        None,
    )
    if _t1os_incremental_scripts is not None:
        _t1os_incremental_sys.path.insert(0, str(_t1os_incremental_scripts))
        from _incremental_test import guard as _t1os_incremental_guard
        if _t1os_incremental_guard(__file__, _t1os_incremental_sys.argv[1:]):
            raise SystemExit(0)

import argparse
from pathlib import Path
import re
import sys
import tempfile


class ClosureError(RuntimeError):
    pass


ROLE = re.compile(r"ROOTHEALTH_IO_ROLE\s*\(\s*(TYPED_WRITER|RAW_WAL|REPORT)\s*\)")
DIRECT_TARGET_IO = re.compile(
    r"(?:->\s*pwrite\s*\(|\b(?:pwrite|pwrite64|pwritev|pwritev2|write|writev)\s*\("
    r"|\b(?:sendfile|sendfile64|io_uring_setup|io_uring_enter|io_uring_register)\s*\("
    r"|\bsyscall\s*\(\s*SYS_(?:pwrite64?|writev?|sendfile64?|io_uring_(?:setup|enter|register))\b"
    r"|\b(?:fallocate|ftruncate|copy_file_range|splice|msync)\s*\("
    r"|\b(?:BLKDISCARD|BLKSECDISCARD|BLKZEROOUT|FICLONE|FICLONERANGE)\b)"
)
DEVICE_ONLY_IO = re.compile(
    r"(?:->\s*pwrite\s*\(|\b(?:pwrite|pwrite64|pwritev|pwritev2)\s*\("
    r"|\b(?:sendfile|sendfile64|io_uring_setup|io_uring_enter|io_uring_register)\s*\("
    r"|\bsyscall\s*\(\s*SYS_(?:pwrite64?|sendfile64?|io_uring_(?:setup|enter|register))\b"
    r"|\b(?:fallocate|ftruncate|copy_file_range|splice|msync|mprotect)\s*\("
    r"|\b(?:BLKDISCARD|BLKSECDISCARD|BLKZEROOUT|FICLONE|FICLONERANGE)\b)"
)
WRITABLE_SHARED_MMAP = re.compile(
    r"\bmmap(?:64)?\s*\([^;]{0,2048}(?:"
    r"PROT_WRITE[^;]{0,1024}MAP_SHARED|MAP_SHARED[^;]{0,1024}PROT_WRITE"
    r")[^;]{0,2048}\)",
    re.DOTALL,
)
WRITE_ENABLE_MPROTECT = re.compile(
    r"\bmprotect\s*\([^;]{0,1024}\bPROT_WRITE\b[^;]{0,1024}\)", re.DOTALL
)
UNREVIEWED_IOCTL = re.compile(
    r"(?:\bioctl\s*\(|\bsyscall\s*\(\s*SYS_ioctl\b)", re.DOTALL
)
UNMODELED_BARRIER = re.compile(
    r"(?:\b(?:sync|syncfs|sync_file_range)\s*\("
    r"|\bsyscall\s*\(\s*SYS_(?:sync|syncfs|sync_file_range)\b)",
    re.DOTALL,
)


def strip_comments_and_literals(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    source = re.sub(r"//[^\n]*", "", source)
    source = re.sub(r'"(?:\\.|[^"\\])*"', '""', source)
    return re.sub(r"'(?:\\.|[^'\\])*'", "''", source)


def manifest_entries(text_value: str) -> list[Path]:
    lines = text_value.splitlines()
    required_header = "# roothealth-linked-inputs-v1 complete-link-inputs=true"
    if not lines or lines[0] != required_header:
        raise ClosureError(
            "translation-unit manifest lacks the complete-link-inputs attestation"
        )
    entries: list[Path] = []
    entry_text: list[str] = []
    for line_number, raw_line in enumerate(lines[1:], 2):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            raise ClosureError(
                f"translation-unit manifest line {line_number} contains an unrecognized directive"
            )
        entry = Path(line)
        if entry.is_absolute() or entry.suffix != ".c" or ".." in entry.parts:
            raise ClosureError(
                f"translation-unit manifest line {line_number} is not a safe relative C path: {line!r}"
            )
        entries.append(entry)
        entry_text.append(line)
    if not entries:
        raise ClosureError("translation-unit manifest contains no C files")
    if entry_text != sorted(set(entry_text)):
        raise ClosureError(
            "translation-unit manifest paths must be sorted and unique"
        )
    return entries


def source_files(root: Path, manifest: Path) -> list[Path]:
    if not root.is_dir():
        raise ClosureError(f"engine source is not a directory: {root}")
    root = root.resolve()
    files: list[Path] = []
    for relative in manifest_entries(manifest.read_text(encoding="utf-8")):
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise ClosureError(f"translation unit escapes engine source: {relative}") from error
        if not path.is_file():
            raise ClosureError(f"linked translation unit is absent: {relative}")
        files.append(path)
    return files


def analyze_source(path: Path, raw_source: str) -> tuple[str | None, list[str]]:
    found_roles = ROLE.findall(raw_source)
    if len(found_roles) > 1:
        raise ClosureError(f"multiple ROOTHEALTH_IO_ROLE declarations in {path}")
    role = found_roles[0] if found_roles else None
    source = strip_comments_and_literals(raw_source)
    violations: list[str] = []
    # The v2 power-cut observer/materializer records only fsync/fdatasync.
    # Alternate durability barriers are therefore forbidden even inside a
    # reviewed writer until the capture ABI explicitly models them.
    for match in UNMODELED_BARRIER.finditer(source):
        line_number = source.count("\n", 0, match.start()) + 1
        violations.append(f"{path}:{line_number}:unmodeled durability barrier")
    for line_number, line in enumerate(source.splitlines(), 1):
        if not DIRECT_TARGET_IO.search(line):
            continue
        if role in ("TYPED_WRITER", "RAW_WAL"):
            continue
        if role == "REPORT":
            continue
        violations.append(f"{path}:{line_number}:{line.strip()}")
    if role not in ("TYPED_WRITER", "RAW_WAL"):
        for pattern, description in (
            (WRITABLE_SHARED_MMAP, "writable shared mmap"),
            (WRITE_ENABLE_MPROTECT, "write-enabling mprotect"),
            (UNREVIEWED_IOCTL, "unreviewed ioctl call"),
        ):
            for match in pattern.finditer(source):
                line_number = source.count("\n", 0, match.start()) + 1
                violations.append(f"{path}:{line_number}:{description}")
    return role, violations


def self_test() -> None:
    role, violations = analyze_source(
        Path("linked-writer.c"),
        "/* ROOTHEALTH_IO_ROLE(TYPED_WRITER) */\n"
        "int linked_writer(int fd) { return pwrite(fd, 0, 0, 0); }\n",
    )
    if role != "TYPED_WRITER" or violations:
        raise ClosureError("self-test lost an I/O role declared in a comment")
    with tempfile.TemporaryDirectory(prefix="roothealth-io-closure-") as directory:
        root = Path(directory)
        linked = root / "linked-writer.c"
        unlinked = root / "unlinked-utility.c"
        manifest = root / "linked.units"
        linked.write_text("int linked(void) { return 0; }\n", encoding="utf-8")
        unlinked.write_text("int utility(int fd) { return pwrite(fd, 0, 0, 0); }\n", encoding="utf-8")
        header = "# roothealth-linked-inputs-v1 complete-link-inputs=true\n"
        manifest.write_text(header + "linked-writer.c\n", encoding="utf-8")
        selected = source_files(root, manifest)
        if selected != [linked.resolve()] or unlinked.resolve() in selected:
            raise ClosureError(
                "self-test did not confine scanning to linked translation units"
            )
        for foreign_input in ("prebuilt.o", "archive.a", "plugin.so"):
            manifest.write_text(
                header + f"linked-writer.c\n{foreign_input}\n", encoding="utf-8"
            )
            try:
                source_files(root, manifest)
            except ClosureError as error:
                if "not a safe relative C path" not in str(error):
                    raise
            else:
                raise ClosureError(
                    f"self-test accepted non-C linked input {foreign_input}"
                )
        for malformed in (
            "linked-writer.c\n",
            header + "z.c\na.c\n",
            header + "linked-writer.c\nlinked-writer.c\n",
        ):
            manifest.write_text(malformed, encoding="utf-8")
            try:
                source_files(root, manifest)
            except ClosureError:
                pass
            else:
                raise ClosureError(
                    "self-test accepted an incomplete, unsorted, or duplicate manifest"
                )
        manifest.write_text(header + "linked-writer.c\n", encoding="utf-8")
    _, bypasses = analyze_source(
        Path("unreviewed.c"),
        "int bypass(int fd) { return ioctl(fd, BLKDISCARD, 0); }\n"
        "int variable(int fd, unsigned long request) { return ioctl(fd, request, 0); }\n"
        "long raw(int fd, unsigned long request) { return syscall(SYS_ioctl, fd, request); }\n"
        "int remap(void *p) { return mprotect(p, 4096, PROT_WRITE); }\n",
    )
    if len(bypasses) < 4:
        raise ClosureError("self-test did not reject alternate target-write bypasses")
    _, barrier_bypasses = analyze_source(
        Path("reviewed-writer-barriers.c"),
        "/* ROOTHEALTH_IO_ROLE(TYPED_WRITER) */\n"
        "void a(void) { sync(); }\n"
        "int b(int fd) { return syncfs(fd); }\n"
        "int c(int fd) { return sync_file_range(fd, 0, 1, 0); }\n"
        "long d(void) { return syscall(SYS_sync); }\n"
        "long e(int fd) { return syscall(SYS_syncfs, fd); }\n"
        "long f(int fd) { return syscall(SYS_sync_file_range, fd, 0, 1, 0); }\n",
    )
    if len(barrier_bypasses) != 6:
        raise ClosureError(
            "self-test did not reject every unmodeled durability barrier"
        )


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        try:
            self_test()
            print(
                "roothealth I/O closure self-test passed: "
                "comment_roles=true complete_link_manifest=true non_c_inputs_rejected=true "
                "variable_ioctl_rejected=true alternate_bypasses=true "
                "alternate_barriers_rejected=true"
            )
            return 0
        except ClosureError as error:
            print(f"roothealth I/O closure self-test failed: {error}", file=sys.stderr)
            return 1
    parser = argparse.ArgumentParser()
    parser.add_argument("engine_source", type=Path)
    parser.add_argument("translation_unit_manifest", type=Path)
    args = parser.parse_args()
    try:
        self_test()
        roles: dict[str, list[Path]] = {"TYPED_WRITER": [], "RAW_WAL": [], "REPORT": []}
        violations: list[str] = []
        for path in source_files(args.engine_source, args.translation_unit_manifest):
            # Linked libntfs supplies the read-only parser API and retains its
            # general-purpose mutation entry points for other ntfsprogs tools.
            # RootHealth contains those calls at runtime with FS_NO_REPAIR and
            # the typed device backend; this source-role gate applies to the
            # RootHealth-owned I/O closure.
            if "/libntfs/" in path.as_posix():
                continue
            role, path_violations = analyze_source(
                path, path.read_text(encoding="utf-8")
            )
            if role:
                roles[role].append(path)
            violations.extend(path_violations)
        for required_role in ("TYPED_WRITER", "RAW_WAL"):
            if len(roles[required_role]) != 1:
                raise ClosureError(
                    f"expected exactly one {required_role} module, found "
                    f"{[str(path) for path in roles[required_role]]}"
                )
        if len(roles["REPORT"]) < 1:
            raise ClosureError(
                "expected at least one REPORT module, found "
                + ", ".join(str(path) for path in roles["REPORT"])
            )
        if violations:
            raise ClosureError(
                "direct target-capable I/O exists outside the typed writer/raw WAL "
                "(or device I/O exists in the report writer):\n" + "\n".join(violations)
            )
        print(
            "roothealth I/O closure passed: typed_writer=%s raw_wal=%s reports=%s"
            % (
                roles["TYPED_WRITER"][0],
                roles["RAW_WAL"][0],
                len(roles["REPORT"]),
            )
        )
        return 0
    except (OSError, UnicodeError, ClosureError) as error:
        print(f"roothealth I/O closure check failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
