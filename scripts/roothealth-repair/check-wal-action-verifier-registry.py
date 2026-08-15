#!/usr/bin/env python3
"""Exact-source and sanitizer gate for the proposed WAL verifier registry."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent
EXPECTED = {
    "src/roothealth_wal.c":
        "16a1a1bd3317a3ac955d4062c3c21b1b8830909de9c85512b241f4bf4b9e7c3c",
    "src/roothealth_wal.h":
        "8dd4e279dd02fa1fb55c55a4b82942dadd3646fb0e49fe6da03ee54021bda7f9",
}
ASSETS = {
    "wal-action-verifier-registry.patch":
        "c5c565e8ddd9640758967e982ea6fb53f9528fa1d77d84d00f02795833b597c1",
    "wal_action_verifier_registry_selftest.c":
        "ef30107bcd37c99ee0ecf814899cb273fa1b52ce7e29c4cfec1517ac953d4d98",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run(command: list[str], label: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        command, text=True, capture_output=True, env=env, check=False
    )
    if completed.returncode:
        raise RuntimeError(
            f"{label} failed ({completed.returncode})\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", required=True, type=Path)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    tree = args.tree.resolve()

    for relative, expected in EXPECTED.items():
        path = tree / relative
        require(path.is_file(), f"missing patched source: {path}")
        require(digest(path) == expected, f"source hash drift: {relative}")
    for name, expected in ASSETS.items():
        path = HERE / name
        require(digest(path) == expected, f"audit asset hash drift: {name}")

    wal_text = (tree / "src/roothealth_wal.c").read_text()
    header_text = (tree / "src/roothealth_wal.h").read_text()
    required_source = (
        "rh_wal_register_action_verifier",
        "rh_wal_dispatch_action_verifiers",
        "rh_wal_validate_legacy_recovery_targets",
        "result = rh_wal_dispatch_action_verifiers",
        "rh_wal_install_builtin_action_verifiers",
        "rh_wal_preimage_read",
        "rh_wal_entry_old_read",
        "callback_errno = errno",
        "errno = EOPNOTSUPP",
        "memcmp(preimage, &writer_snapshot",
        "memcmp(entries, entry_snapshot",
    )
    for token in required_source:
        require(token in wal_text, f"missing fail-closed source token: {token}")
    require(
        "RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_REDO)" in wal_text
        and "RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_RESTART)" in wal_text,
        "native ID5/ID6 registration is not explicitly disabled",
    )
    for token in (
        "RH_WAL_ACTION_VERIFIER_ABI_VERSION",
        "struct rh_wal_recovery_entry_view",
        "struct rh_wal_action_verifier_context",
        "preimage",
        "transaction_kind",
        "state",
    ):
        require(token in header_text, f"missing verifier ABI field: {token}")
    require(
        "struct rh_writer *preimage;" not in header_text
        and "old_bytes" not in header_text
        and "void *opaque" not in header_text,
        "callback ABI exposes mutable writer, payload, or opaque pointers",
    )

    dependency_sources = [
        tree / "src/roothealth_bitmap.c",
        tree / "src/roothealth_census_device.c",
        tree / "src/roothealth_hash_stream.c",
        tree / "src/roothealth_overlay.c",
        tree / "src/roothealth_dirty.c",
        tree / "src/roothealth_policy.c",
        tree / "src/roothealth_raw_mft.c",
    ]
    archive = tree / "libntfs/.libs/libntfs.a"
    for dependency in [*dependency_sources, archive]:
        require(dependency.is_file(), f"configured source/build input missing: {dependency}")

    with tempfile.TemporaryDirectory(prefix="rh-wal-verifier-gate.") as temp:
        work = Path(temp)
        includes = [
            f"-I{tree}", f"-I{tree / 'include'}", f"-I{tree / 'libntfs'}",
            f"-I{tree / 'src'}",
        ]
        strict = [
            args.cc, "-std=gnu11", "-D_GNU_SOURCE", "-D_FORTIFY_SOURCE=3",
            "-DHAVE_CONFIG_H", "-Wall", "-Wextra", "-Werror", "-Wformat=2",
            "-Wshadow", "-Wno-address-of-packed-member", *includes,
        ]
        run(
            strict + ["-c", str(tree / "src/roothealth_wal.c"),
                      "-o", str(work / "wal.strict.o")],
            "strict WAL compile",
        )
        run(
            strict + ["-fanalyzer", "-c", str(tree / "src/roothealth_wal.c"),
                      "-o", str(work / "wal.analyzer.o")],
            "WAL static analyzer",
        )
        sanitizer = strict + [
            "-DROOTHEALTH_WAL_TEST_HOOKS", "-ffunction-sections",
            "-fdata-sections", "-fsanitize=address,undefined",
            "-fno-omit-frame-pointer",
        ]
        run(
            sanitizer + ["-c", str(tree / "src/roothealth_wal.c"),
                         "-o", str(work / "wal.san.o")],
            "sanitized WAL compile",
        )
        run(
            sanitizer + ["-c", str(tree / "src/roothealth_write.c"),
                         "-o", str(work / "write.san.o")],
            "sanitized writer compile",
        )
        dependencies: list[Path] = []
        for source in dependency_sources:
            output = work / f"{source.stem}.san.o"
            run(
                sanitizer + ["-c", str(source), "-o", str(output)],
                f"sanitized dependency compile ({source.name})",
            )
            dependencies.append(output)
        binary = work / "registry-selftest"
        run(
            sanitizer + [
                str(HERE / "wal_action_verifier_registry_selftest.c"),
                str(work / "wal.san.o"), str(work / "write.san.o"),
                *(str(path) for path in dependencies), str(archive),
                "-Wl,--gc-sections", "-o", str(binary),
            ],
            "sanitized registry self-test link",
        )
        environment = os.environ.copy()
        environment["ASAN_OPTIONS"] = "detect_leaks=1:abort_on_error=1"
        environment["UBSAN_OPTIONS"] = "halt_on_error=1"
        output = run([str(binary)], "sanitized registry self-test", environment)
        require("PASS (9/9)" in output, "registry self-test did not pass all cases")

    print(
        "PASS: exact WAL verifier registry; unregistered/native IDs fail closed; "
        "strict+analyzer+ASan/UBSan 9/9"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
