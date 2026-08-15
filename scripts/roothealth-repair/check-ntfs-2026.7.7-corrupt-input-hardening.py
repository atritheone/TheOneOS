#!/usr/bin/env python3
"""Source-bound build, analyzer, and sanitizer gate for linked NTFS parsers."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
LEGACY_PIPELINE_PATCH = (
    PROJECT_ROOT / "resource/entry/roothealth/0002-ntfs-3g-2026.7.7-index-hardening.patch"
)
LEGACY_PIPELINE_PATCH_SHA256 = (
    "b4c2b59b3115adeb422bb47f37ebf064b5440856f97404ba6f083e6432d8dfaa"
)
EXPECTED = {
    "include/index.h":
        "9713d6f1eb1dd8596d139c95031890563e4a4785c3f27812c1a74246db25055b",
    "libntfs/attrib.c":
        "04fe422d352d9beb115a1af34188b8ac4a386a6ff90a488cbebdf6fe2fcf7e95",
    "libntfs/compress.c":
        "c228f6a097340c094327bf16f43a411659db081f3373339c18f958f6c7f6576e",
    "libntfs/index.c":
        "77f2e5bddeaee3db6f62f5add64796096bb92f435c89d382153d6c2292563da0",
    "libntfs/runlist.c":
        "369dc9c3922ca85791171a64e652763f215568e2e42aeab92c0492143d4e733b",
    "src/ntfscat.c":
        "79b2828e48b1243cf586db8f5d5d76d73bd596d4ace1726dc2d56021b9dbbcdf",
    "src/ntfsck.c":
        "80f997d2ce187efc0b58332c3dac6b4b77eadd5b6981debfd0f7610ff138db9a",
    "src/roothealth_repair.c":
        "b018e42b285808f2d95d0d4103597f87b1c56adb5a267514bf05731d667f1d40",
    "src/Makefile.am":
        "7dec7cac9e91b9c06b73019cd67fd4cba97c0ddaa1514097b2aa461a4a92a875",
}
ASSETS = {
    "ntfs-2026.7.7-corrupt-input-hardening.patch":
        "84e5015f8600257e3a077d627a28c03d2c23dd0acd4b7f0bf44e6cc98056a93d",
    "ntfs-2026.7.7-corrupt-input-selftest.c":
        "f7264991674d0c5ac6bddda65536a9c624fb1ed8f0368b85d2e1b99ebf089f6f",
}
CHANGED_TUS = (
    "libntfs/attrib.c",
    "libntfs/compress.c",
    "libntfs/index.c",
    "libntfs/runlist.c",
    "src/ntfscat.c",
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run(
    command: list[str], label: str, cwd: Path, env: dict[str, str] | None = None
) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"{label} failed ({completed.returncode})\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout


def source_static_gate(tree: Path) -> None:
    patch_text = (HERE / "ntfs-2026.7.7-corrupt-input-hardening.patch").read_text()
    require("diff --git a/src/ntfsck.c" not in patch_text,
            "hardening patch mutates the unlinked legacy checker")
    require("diff --git a/src/roothealth_repair.c" not in patch_text,
            "hardening patch mutates roothealth policy/orchestration")
    require(LEGACY_PIPELINE_PATCH.is_file(), "legacy pipeline patch missing")
    require(digest(LEGACY_PIPELINE_PATCH) == LEGACY_PIPELINE_PATCH_SHA256,
            "legacy pipeline hardening patch drift")

    index_text = (tree / "libntfs/index.c").read_text()
    attrib_text = (tree / "libntfs/attrib.c").read_text()
    compress_text = (tree / "libntfs/compress.c").read_text()
    runlist_text = (tree / "libntfs/runlist.c").read_text()
    ntfscat_text = (tree / "src/ntfscat.c").read_text()
    for token in (
        "ntfs_ie_stream_inconsistent(ih, inum)",
        "len < sizeof(INDEX_ENTRY_HEADER) || (len & 7)",
        "entry_length < sizeof(VCN)",
        "tail_size < 0 || dst_entries > dst_allocated",
        "ictx->pindex >= MAX_PARENT_VCN - 1",
    ):
        require(token in index_text, f"missing index hardening: {token}")
    for token in (
        "ir->index_block_size",
        "< NTFS_BLOCK_SIZE",
        "ntfs_ie_stream_inconsistent(&ir->index",
    ):
        require(token in attrib_text, f"missing INDEX_ROOT hardening: {token}")
    for token in (
        "if ((size_t)(cb_end - cb) < sizeof(hdr))",
        "if ((size_t)(cb_sb_end - cb) < sizeof(pt))",
        "if (cb == cb_sb_end || dest == dest_sb_end)",
        "cb = cb_sb_end",
    ):
        require(token in compress_text, f"missing compression hardening: {token}")
    for token in (
        "ntfs_mapping_pair_sign_extend",
        "b > sizeof(deltaxcn)",
        "__builtin_add_overflow(vcn, deltaxcn, &vcn)",
        "__builtin_add_overflow(lcn, deltaxcn, &lcn)",
    ):
        require(token in runlist_text, f"missing runlist hardening: {token}")
    require("if (bufsize < block_size)" in ntfscat_text,
            "ntfscat retains a fixed index-block buffer")

    makefile = (tree / "src/Makefile").read_text()
    object_start = makefile.find("am_roothealth_repair_core_OBJECTS =")
    require(object_start >= 0, "configured roothealth object manifest missing")
    object_end = makefile.find("\nroothealth_repair_core_OBJECTS =", object_start)
    require(object_end > object_start, "configured roothealth object manifest malformed")
    objects = makefile[object_start:object_end]
    require("roothealth_repair_main.$(OBJEXT)" in objects,
            "roothealth entry object missing")
    require("ntfsck.$(OBJEXT)" not in objects, "legacy ntfsck linked into roothealth")


def compile_object(
    cc: str,
    tree: Path,
    source: str,
    output: Path,
    extra: list[str],
) -> None:
    command = [
        cc,
        "-DHAVE_CONFIG_H",
        "-D_GNU_SOURCE",
        "-D_FORTIFY_SOURCE=3",
        "-I.",
        "-Iinclude",
        "-Ilibntfs",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-Wno-address-of-packed-member",
        "-Wno-unused-parameter",
        *extra,
        "-c",
        source,
        "-o",
        str(output),
    ]
    run(command, f"compile {source}", tree)


def build_and_run_selftest(
    cc: str,
    objcopy: str,
    tree: Path,
    work: Path,
    sanitizer: bool,
) -> None:
    mode = "sanitizer" if sanitizer else "strict"
    common = ["-O1", "-g", "-fno-inline"] if sanitizer else ["-O0", "-g", "-fno-inline"]
    if sanitizer:
        common += ["-fno-omit-frame-pointer", "-fsanitize=address,undefined"]

    objects: dict[str, Path] = {}
    sources = ("index", "compress", "attrib", "runlist") if sanitizer else ("index", "compress")
    for name in sources:
        output = work / f"{name}-{mode}.o"
        compile_object(cc, tree, f"libntfs/{name}.c", output,
                       [*common, "-Wno-unused-function"])
        objects[name] = output

    index_test = work / f"index-{mode}-test.o"
    compress_test = work / f"compress-{mode}-test.o"
    run([objcopy,
         "--globalize-symbol=ntfs_ir_to_ib",
         "--globalize-symbol=ntfs_ib_copy_tail",
         str(objects["index"]), str(index_test)],
        f"globalize index {mode} symbols", tree)
    run([objcopy, "--globalize-symbol=ntfs_decompress",
         str(objects["compress"]), str(compress_test)],
        f"globalize compression {mode} symbol", tree)

    binary = work / f"corrupt-input-{mode}"
    link = [
        cc,
        "-DHAVE_CONFIG_H",
        "-D_GNU_SOURCE",
        "-D_FORTIFY_SOURCE=3",
        "-I.",
        "-Iinclude",
        "-Ilibntfs",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-Wno-address-of-packed-member",
        *( ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
           if sanitizer else ["-O2"] ),
        str(HERE / "ntfs-2026.7.7-corrupt-input-selftest.c"),
        str(index_test),
        str(compress_test),
    ]
    if sanitizer:
        link += [str(objects["attrib"]), str(objects["runlist"])]
    link += [
        "libntfs/.libs/libntfs.a",
        "-o",
        str(binary),
        "-lpthread",
        "-ldl",
        "-luuid",
    ]
    run(link, f"link {mode} malformed-input gate", tree)
    environment = os.environ.copy()
    if sanitizer:
        environment["ASAN_OPTIONS"] = "abort_on_error=1:detect_leaks=1"
        environment["UBSAN_OPTIONS"] = "halt_on_error=1"
    output = run([str(binary)], f"run {mode} malformed-input gate", tree,
                 environment)
    require(output.strip() == "PASS 30 bounded corrupt-input checks",
            f"unexpected {mode} self-test result: {output!r}")


def run_source_bound_gate(tree: Path, cc: str) -> None:
    for relative, expected in EXPECTED.items():
        path = tree / relative
        require(path.is_file(), f"missing source/build input: {relative}")
        require(digest(path) == expected, f"source hash drift: {relative}")
    for relative, expected in ASSETS.items():
        path = HERE / relative
        require(path.is_file(), f"missing qualification asset: {relative}")
        require(digest(path) == expected, f"qualification asset drift: {relative}")

    archive = tree / "libntfs/.libs/libntfs.a"
    binary = tree / "src/roothealth-repair-core"
    require(archive.is_file(), "configured libntfs archive missing")
    require(binary.is_file(), "roothealth product binary missing")
    source_static_gate(tree)

    make = shutil.which("make")
    nm = shutil.which("nm")
    objcopy = shutil.which("objcopy")
    require(bool(make and nm and objcopy), "make, nm, and objcopy are required")
    run([make, "-C", "src", "roothealth-repair-core", "V=1"],
        "roothealth product link", tree)
    symbols = run([nm, "-a", str(binary)], "roothealth symbol inventory", tree)
    for symbol in (
        "ntfs_decompress",
        "ntfs_ie_stream_inconsistent",
        "ntfs_mapping_pairs_decompress_i",
        "roothealth_repair_main.c",
    ):
        require(symbol in symbols, f"linked hardening symbol missing: {symbol}")
    require(" ntfsck.c" not in symbols, "legacy ntfsck translation unit linked")

    with tempfile.TemporaryDirectory(prefix="rh-ntfs-2026-7-7-gate.") as temp:
        work = Path(temp)
        for source in CHANGED_TUS:
            stem = Path(source).stem
            compile_object(cc, tree, source, work / f"{stem}-strict.o", ["-O2"])
            compile_object(cc, tree, source, work / f"{stem}-analyzer.o",
                           ["-O0", "-fanalyzer"])
        build_and_run_selftest(cc, objcopy, tree, work, sanitizer=False)
        build_and_run_selftest(cc, objcopy, tree, work, sanitizer=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", type=Path)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    require(args.tree is not None or args.self_test,
            "provide --tree and/or --self-test")

    if args.self_test:
        sample = b"roothealth-linked-parser"
        changed = sample + b"\x00"
        require(hashlib.sha256(sample).digest() != hashlib.sha256(changed).digest(),
                "digest drift self-test failed")
        patch = (HERE / "ntfs-2026.7.7-corrupt-input-hardening.patch").read_text()
        require("diff --git a/libntfs/compress.c" in patch,
                "compression omission self-test failed")
        require("diff --git a/libntfs/runlist.c" in patch,
                "runlist omission self-test failed")

    if args.tree is not None:
        run_source_bound_gate(args.tree.resolve(), args.cc)
        print("PASS linked-parser sources=9 strict=5 analyzer=5 malformed=30x2")
    else:
        print("PASS linked-parser qualification self-test")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"FAIL: {error}", file=os.sys.stderr)
        raise SystemExit(1)
