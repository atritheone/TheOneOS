#!/usr/bin/env python3
"""Build bounded, one-fault native-$LogFile rejection fixtures.

The source must be the strict nonzero-redo image emitted by
native_logfile_redo_fixture.py.  Every output clone changes one parser trust
boundary (or the redundant pair for RSTR-only fields) while preserving the
source image byte-for-byte.  The product qualification then proves every
case returns unsafe with an empty repair plan and zero target/WAL writes.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
from typing import Callable


class CorpusError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_encoder(path: Path):
    spec = importlib.util.spec_from_file_location("roothealth_native_redo", path)
    if spec is None or spec.loader is None:
        raise CorpusError(f"cannot import native redo encoder {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_sparse(source: Path, destination: Path) -> None:
    if destination.exists():
        raise CorpusError(f"refusing to overwrite corpus image {destination}")
    completed = os.spawnlp(
        os.P_WAIT,
        "cp",
        "cp",
        "--reflink=auto",
        "--sparse=always",
        "--",
        str(source),
        str(destination),
    )
    if completed:
        raise CorpusError(f"sparse clone failed for {destination} (exit {completed})")


def mutate_protected_page(
    encoder,
    image: Path,
    runs,
    cluster_size: int,
    page_number: int,
    mutator: Callable[[bytearray], None],
) -> None:
    offset = page_number * encoder.LOG_PAGE_SIZE
    with image.open("r+b", buffering=0) as handle:
        raw = encoder.stream_read(
            handle, runs, cluster_size, offset, encoder.LOG_PAGE_SIZE
        )
        usa_offset = encoder.u16(raw, 4)
        usn = encoder.u16(raw, usa_offset)
        logical = encoder.mst_unprotect(raw, encoder.LOG_PAGE_SIZE)
        before = bytes(logical)
        mutator(logical)
        if logical == before:
            raise CorpusError("native-log corpus mutator made no logical change")
        changed = encoder.mst_protect(logical, usa_offset, usn)
        encoder.stream_write(handle, runs, cluster_size, offset, changed)
        handle.flush()
        os.fsync(handle.fileno())


def mutate_raw_page(
    encoder,
    image: Path,
    runs,
    cluster_size: int,
    page_number: int,
    mutator: Callable[[bytearray], None],
) -> None:
    offset = page_number * encoder.LOG_PAGE_SIZE
    with image.open("r+b", buffering=0) as handle:
        raw = bytearray(
            encoder.stream_read(
                handle, runs, cluster_size, offset, encoder.LOG_PAGE_SIZE
            )
        )
        before = bytes(raw)
        mutator(raw)
        if raw == before:
            raise CorpusError("native-log raw corpus mutator made no change")
        encoder.stream_write(handle, runs, cluster_size, offset, bytes(raw))
        handle.flush()
        os.fsync(handle.fileno())


def set_u16(offset: int, value: int) -> Callable[[bytearray], None]:
    return lambda page: struct.pack_into("<H", page, offset, value)


def set_u32(offset: int, value: int) -> Callable[[bytearray], None]:
    return lambda page: struct.pack_into("<I", page, offset, value)


def set_u64(offset: int, value: int) -> Callable[[bytearray], None]:
    return lambda page: struct.pack_into("<Q", page, offset, value)


def build(
    encoder_path: Path,
    source: Path,
    source_manifest: Path,
    output: Path,
) -> dict[str, object]:
    encoder = load_encoder(encoder_path)
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    if manifest.get("format") != "roothealth-native-logfile-redo-v1":
        raise CorpusError("native redo source manifest format differs")
    source_digest = sha256(source)
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise CorpusError(f"corpus output must be new or empty: {output}")
    else:
        output.mkdir(parents=True)

    with source.open("rb", buffering=0) as handle:
        geometry = encoder.parse_geometry(handle)
        _, runs = encoder.find_logfile(handle, geometry)
    cluster_size = int(geometry["cluster_size"])
    forget = (
        encoder.TARGET_LOG_PAGE * encoder.LOG_PAGE_SIZE
        + encoder.RCRD_DATA_OFFSET
        + 104
    )
    restart_area = encoder.RESTART_AREA_OFFSET

    # name, affected pages, raw-MST mutation, logical mutator
    cases: list[tuple[str, tuple[int, ...], bool, Callable[[bytearray], None]]] = [
        ("record-client-data-length", (5,), False, set_u32(encoder.RCRD_DATA_OFFSET + 24, 0xFFF8)),
        ("redo-offset", (5,), False, set_u16(encoder.RCRD_DATA_OFFSET + 52, 0xFFF8)),
        ("redo-length", (5,), False, set_u16(encoder.RCRD_DATA_OFFSET + 54, 0xFFF8)),
        ("undo-offset", (5,), False, set_u16(encoder.RCRD_DATA_OFFSET + 56, 0xFFF8)),
        ("undo-length", (5,), False, set_u16(encoder.RCRD_DATA_OFFSET + 58, 0xFFF8)),
        ("target-attribute", (5,), False, set_u16(encoder.RCRD_DATA_OFFSET + 60, 0xFFFF)),
        ("lcns-to-follow", (5,), False, set_u16(encoder.RCRD_DATA_OFFSET + 62, 0xFFFF)),
        ("record-offset", (5,), False, set_u16(encoder.RCRD_DATA_OFFSET + 64, 0xFFFF)),
        ("attribute-offset", (5,), False, set_u16(encoder.RCRD_DATA_OFFSET + 66, 0xFFFF)),
        ("redo-undo-opcode-pair", (5,), False, set_u16(encoder.RCRD_DATA_OFFSET + 50, 8)),
        ("rstr-restart-offset", (0, 1), False, set_u16(24, 0xFFF8)),
        ("rstr-client-offset", (0, 1), False, set_u16(restart_area + 22, 0xFFF8)),
        ("rcrd-next-record-offset", (5,), False, set_u16(24, 0xFFF8)),
        ("mst-usa-count", (5,), True, set_u16(6, 8)),
        ("mst-usa-offset", (5,), True, set_u16(4, 0x10)),
        ("mst-usa-tail", (5,), True, lambda page: page.__setitem__(510, page[510] ^ 0x5A)),
        ("lsn-previous-cycle", (5,), False, set_u64(encoder.RCRD_DATA_OFFSET + 8, int(manifest["transaction"]["update_lsn"], 16))),
        ("lsn-undo-cycle", (5,), False, set_u64(forget - encoder.TARGET_LOG_PAGE * encoder.LOG_PAGE_SIZE + 16, int(manifest["transaction"]["forget_lsn"], 16))),
    ]

    outputs: list[dict[str, object]] = []
    for ordinal, (name, pages, raw, mutator) in enumerate(cases, 1):
        destination = output / f"{ordinal:02d}-{name}.ntfs"
        copy_sparse(source, destination)
        before = sha256(destination)
        if before != source_digest:
            raise CorpusError(f"corpus clone {name} differs before mutation")
        for page in pages:
            if raw:
                mutate_raw_page(
                    encoder, destination, runs, cluster_size, page, mutator
                )
            else:
                mutate_protected_page(
                    encoder, destination, runs, cluster_size, page, mutator
                )
        after = sha256(destination)
        if after == before:
            raise CorpusError(f"corpus mutation {name} changed no source bytes")
        outputs.append(
            {
                "ordinal": ordinal,
                "name": name,
                "image": str(destination),
                "pages": list(pages),
                "raw_mst_fault": raw,
                "before_sha256": before,
                "after_sha256": after,
            }
        )
    if sha256(source) != source_digest:
        raise CorpusError("native redo corpus builder changed its source fixture")
    result = {
        "format": "roothealth-native-logfile-rejection-corpus-v1",
        "source": str(source),
        "source_sha256": source_digest,
        "case_count": len(outputs),
        "cases": outputs,
    }
    (output / "corpus.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("encoder", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("source_manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        result = build(args.encoder, args.source, args.source_manifest, args.output)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (CorpusError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"roothealth native-log corpus failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
