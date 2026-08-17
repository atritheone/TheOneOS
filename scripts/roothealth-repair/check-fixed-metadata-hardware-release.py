#!/usr/bin/env python3
"""Read-only release-image gate for the proposed $UpCase/$AttrDef slice."""

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
import binascii
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import uuid


HERE = Path(__file__).resolve().parent
DISK_BYTES = 10_737_418_240
DISK_SHA256 = "a58dc4e86d12d14e1b09aea90b893587c7146c6f90cecf061c66233d2b727622"
PARTITION_NUMBER = 2
PARTITION_FIRST_LBA = 1_050_624
PARTITION_LAST_LBA = 20_969_471
PARTITION_BYTES = 10_198_450_176
PARTITION_SHA256 = "f89363dacb77c1227d74dc82e180238b7a4be10767ccb86ab5376bf4ff6a3685"
PARTITION_NAME = "T1OS 0.31"
BASIC_DATA_GUID = uuid.UUID("ebd0a0a2-b9e5-4433-87c0-68b6b72699c7")
BLOCK = 16 * 1024 * 1024


def run(command: list[str | Path], label: str, *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        [str(item) for item in command], cwd=cwd, text=True,
        capture_output=True, check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"{label} failed ({completed.returncode})\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout.strip()


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb", buffering=0) as source:
        for chunk in iter(lambda: source.read(BLOCK), b""):
            result.update(chunk)
    return result.hexdigest()


def exact_pread(fd: int, length: int, offset: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        chunk = os.pread(fd, length - len(result), offset + len(result))
        if not chunk:
            raise RuntimeError("short read while validating GPT")
        result.extend(chunk)
    return bytes(result)


def validate_gpt(disk: Path) -> dict[str, object]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(disk, flags)
    try:
        header_sector = exact_pread(fd, 512, 512)
        fields = struct.unpack_from("<8sIIIIQQQQ16sQIII", header_sector)
        (signature, revision, header_size, header_crc, reserved, current_lba,
         backup_lba, first_usable, last_usable, disk_guid, entries_lba,
         entry_count, entry_size, entries_crc) = fields
        if (signature != b"EFI PART" or revision != 0x00010000 or \
                not 92 <= header_size <= 512 or reserved or current_lba != 1 or \
                backup_lba != DISK_BYTES // 512 - 1 or entry_count != 128 or \
                entry_size != 128):
            raise RuntimeError("unsupported or inconsistent primary GPT header")
        encoded = bytearray(header_sector[:header_size])
        encoded[16:20] = b"\0" * 4
        if binascii.crc32(encoded) & 0xFFFFFFFF != header_crc:
            raise RuntimeError("primary GPT header CRC mismatch")
        entries = exact_pread(fd, entry_count * entry_size, entries_lba * 512)
        if binascii.crc32(entries) & 0xFFFFFFFF != entries_crc:
            raise RuntimeError("primary GPT entry-array CRC mismatch")
        start = (PARTITION_NUMBER - 1) * entry_size
        entry = entries[start:start + entry_size]
        type_guid, unique_guid, first_lba, last_lba, attributes, name = \
            struct.unpack_from("<16s16sQQQ72s", entry)
        decoded_name = name.decode("utf-16-le").split("\0", 1)[0]
        if uuid.UUID(bytes_le=type_guid) != BASIC_DATA_GUID or \
                not uuid.UUID(bytes_le=unique_guid).int or \
                first_lba != PARTITION_FIRST_LBA or \
                last_lba != PARTITION_LAST_LBA or attributes or \
                decoded_name != PARTITION_NAME or \
                (last_lba - first_lba + 1) * 512 != PARTITION_BYTES:
            raise RuntimeError("GPT partition 2 identity or geometry drift")
        return {
            "disk_guid": str(uuid.UUID(bytes_le=disk_guid)),
            "first_usable_lba": first_usable,
            "last_usable_lba": last_usable,
            "partition_guid": str(uuid.UUID(bytes_le=unique_guid)),
            "partition_name": decoded_name,
        }
    finally:
        os.close(fd)


def stream_disk(disk: Path, partition_output: Path | None) -> tuple[str, str]:
    disk_hash = hashlib.sha256()
    partition_hash = hashlib.sha256()
    partition_start = PARTITION_FIRST_LBA * 512
    partition_end = (PARTITION_LAST_LBA + 1) * 512
    output = partition_output.open("wb", buffering=0) if partition_output else None
    try:
        position = 0
        with disk.open("rb", buffering=0) as source:
            while True:
                data = source.read(BLOCK)
                if not data:
                    break
                disk_hash.update(data)
                block_end = position + len(data)
                left = max(position, partition_start)
                right = min(block_end, partition_end)
                if left < right:
                    part = data[left - position:right - position]
                    partition_hash.update(part)
                    if output:
                        output.write(part)
                position = block_end
        if position != DISK_BYTES:
            raise RuntimeError("release image size changed during read")
    finally:
        if output:
            output.close()
    return disk_hash.hexdigest(), partition_hash.hexdigest()


def compile_probes(tree: Path, work: Path, cc: str) -> tuple[Path, Path]:
    static_ntfs = tree / "libntfs/.libs/libntfs.a"
    if not static_ntfs.is_file():
        raise RuntimeError("configured libntfs/.libs/libntfs.a is required")
    includes = [
        f"-I{tree}", f"-I{tree / 'include'}", f"-I{tree / 'src'}",
        f"-I{tree / 'libntfs'}",
    ]
    strict = [
        cc, "-std=gnu11", "-DHAVE_CONFIG_H", "-D_GNU_SOURCE",
        "-D_FORTIFY_SOURCE=3", "-Wall", "-Wextra", "-Werror",
        "-Wformat=2", "-Wshadow", "-Wno-address-of-packed-member",
        "-fno-common", *includes,
    ]
    sources = {
        "fixed": "roothealth_fixed_metadata",
        "write": "roothealth_write",
        "overlay": "roothealth_overlay",
        "coverage": "roothealth_coverage",
        "attrdef": "attrdef",
        "policy": "roothealth_policy",
        "raw": "roothealth_raw_mft",
        "namespace": "roothealth_namespace",
        "bitmap": "roothealth_bitmap",
        "hash": "roothealth_hash_stream",
        "index": "roothealth_index_bitmap",
    }
    objects: dict[str, Path] = {}
    for name, source in sources.items():
        target = work / f"{name}.o"
        run(strict + ["-c", tree / "src" / f"{source}.c", "-o", target],
            f"strict compile {source}")
        objects[name] = target
    hardware_object = work / "hardware.o"
    census_object = work / "census.o"
    run(strict + ["-c", HERE / "fixed_metadata_hardware_probe.c", "-o",
                  hardware_object], "strict compile hardware probe")
    run(strict + ["-c", HERE / "fixed_metadata_release_census_probe.c", "-o",
                  census_object], "strict compile census probe")
    hardware = work / "hardware-probe"
    census = work / "census-probe"
    run([cc, "-o", hardware, hardware_object, objects["fixed"],
         objects["overlay"], objects["write"], objects["coverage"],
         objects["attrdef"], static_ntfs], "link hardware probe")
    run([cc, "-o", census, census_object, objects["fixed"], objects["raw"],
         objects["namespace"], objects["bitmap"], objects["hash"],
         objects["index"], objects["overlay"], objects["write"],
         objects["policy"], objects["coverage"], objects["attrdef"],
         static_ntfs], "link census probe")
    return hardware, census


def require_probe_result(actual: dict[str, object], expected: dict[str, object],
                         label: str) -> None:
    for key, value in expected.items():
        if actual.get(key) != value:
            raise RuntimeError(
                f"{label} field {key!r}: expected {value!r}, "
                f"observed {actual.get(key)!r}"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", type=Path, required=True,
                        help="patched, configured ntfs-next source tree")
    parser.add_argument("--disk", type=Path, required=True,
                        help="canonical T1OS v0.31 10-GiB hardware image")
    parser.add_argument("--partition-copy", type=Path,
                        help="existing read-only partition copy; hash must match p2")
    parser.add_argument("--cc", default=os.environ.get("CC", "gcc"))
    args = parser.parse_args()
    tree = args.tree.resolve()
    disk = args.disk.resolve()
    if not disk.is_file() or disk.stat().st_size != DISK_BYTES:
        raise RuntimeError("canonical hardware image is missing or wrong size")
    before_stat = disk.stat()
    gpt = validate_gpt(disk)
    with tempfile.TemporaryDirectory(prefix="rh-fixed-hardware-gate.") as tmp:
        work = Path(tmp)
        partition = args.partition_copy.resolve() if args.partition_copy else \
            work / "T1OS-0.31-p2.ntfs"
        disk_before, partition_streamed = stream_disk(
            disk, None if args.partition_copy else partition,
        )
        if disk_before != DISK_SHA256:
            raise RuntimeError("whole release image hash drift")
        if partition_streamed != PARTITION_SHA256:
            raise RuntimeError("streamed GPT partition 2 hash drift")
        if not partition.is_file() or partition.stat().st_size != PARTITION_BYTES \
                or sha256(partition) != PARTITION_SHA256:
            raise RuntimeError("partition probe image does not equal streamed p2")
        partition_before = sha256(partition)
        hardware, census = compile_probes(tree, work, args.cc)
        hardware_result = json.loads(run([hardware, partition], "hardware probe"))
        census_result = json.loads(run([census, partition], "release census probe"))
        require_probe_result(hardware_result, {
            "result": "PASS", "source_writes": 0, "ordinary_mount": True,
            "upcase_length": 131072, "upcase_lcn": 311380,
            "upcase_offset": 1275412480, "attrdef_length": 2560,
            "attrdef_lcn": 311238, "attrdef_offset": 1274830848,
        }, "hardware probe")
        require_probe_result(census_result, {
            "result": "PASS", "source_writes": 0, "raw_complete": True,
            "cluster_bitmap_clean": True, "identity": "MATCH",
            "attributes": 66853, "bitmap_bits": 2489855, "indexes": 2225,
            "links": 21957, "runs": 18605, "slots": 22062,
        }, "release census probe")
        if sha256(partition) != partition_before:
            raise RuntimeError("partition probe modified its input")
    disk_after = sha256(disk)
    after_stat = disk.stat()
    if disk_after != disk_before or before_stat.st_size != after_stat.st_size or \
            before_stat.st_mtime_ns != after_stat.st_mtime_ns:
        raise RuntimeError("canonical release image changed during read-only gate")
    print(json.dumps({
        "disk_bytes": before_stat.st_size,
        "disk_sha256_before": disk_before,
        "disk_sha256_after": disk_after,
        "gpt": gpt,
        "partition": {
            "number": PARTITION_NUMBER,
            "first_lba": PARTITION_FIRST_LBA,
            "last_lba": PARTITION_LAST_LBA,
            "bytes": PARTITION_BYTES,
            "sha256": partition_streamed,
        },
        "hardware_probe": hardware_result,
        "release_census_probe": census_result,
        "source_writes": 0,
        "result": "PASS",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
