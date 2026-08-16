
#!/usr/bin/env python3
"""Derive the exact project translation-unit/object closure from a GNU ld map."""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import sys


ARCHIVE_RE = re.compile(
    r"\.\./libntfs/\.libs/libntfs\.a\(libntfs_la-([A-Za-z0-9_]+)\.o\)"
)
LOAD_RE = re.compile(r"^LOAD ([^\s]+\.o)$", re.MULTILINE)
SYSTEM_OBJECT_PREFIXES = ("/usr/", "/lib/", "/opt/")


def digest(path: pathlib.Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", required=True, type=pathlib.Path)
    parser.add_argument("--map", required=True, dest="map_path", type=pathlib.Path)
    parser.add_argument("--sources", required=True, type=pathlib.Path)
    parser.add_argument("--objects", required=True, type=pathlib.Path)
    args = parser.parse_args()

    tree = args.tree.resolve(strict=True)
    link_map = args.map_path.read_text(encoding="utf-8", errors="strict")
    records: dict[str, tuple[pathlib.Path, pathlib.Path]] = {}

    archive_names = sorted(set(ARCHIVE_RE.findall(link_map)))
    if not archive_names:
        raise SystemExit("link map contains no source-built libntfs archive members")
    for name in archive_names:
        source_rel = pathlib.Path("libntfs") / f"{name}.c"
        object_rel = pathlib.Path("libntfs/.libs") / f"libntfs_la-{name}.o"
        records[source_rel.as_posix()] = (tree / source_rel, tree / object_rel)

    for loaded in LOAD_RE.findall(link_map):
        if loaded.startswith(SYSTEM_OBJECT_PREFIXES):
            continue
        if "/" in loaded or not loaded.endswith(".o"):
            raise SystemExit(f"unmapped non-system link input: {loaded}")
        name = loaded[:-2]
        source_rel = pathlib.Path("src") / f"{name}.c"
        object_rel = pathlib.Path("src") / loaded
        key = source_rel.as_posix()
        if key in records:
            raise SystemExit(f"duplicate source link input: {key}")
        records[key] = (tree / source_rel, tree / object_rel)

    if len(records) != 72:
        raise SystemExit(f"unexpected project link closure size: {len(records)} (expected 72)")
    for source_rel, (source, obj) in records.items():
        if source.suffix != ".c" or not source.is_file():
            raise SystemExit(f"linked input has no unique C source: {source_rel}")
        if not obj.is_file():
            raise SystemExit(f"linked object missing: {obj}")

    source_lines = ["# roothealth-linked-inputs-v1 complete-link-inputs=true"]
    source_lines.extend(sorted(records))
    args.sources.write_text("\n".join(source_lines) + "\n", encoding="ascii")

    object_lines = [
        "# roothealth-linked-objects-v1 complete-link-inputs=true",
        "source\tsource_sha256\tobject\tobject_sha256",
    ]
    for source_rel in sorted(records):
        source, obj = records[source_rel]
        object_rel = obj.relative_to(tree).as_posix()
        object_lines.append(
            f"{source_rel}\t{digest(source)}\t{object_rel}\t{digest(obj)}"
        )
    args.objects.write_text("\n".join(object_lines) + "\n", encoding="ascii")
    print(f"roothealth-link-closure sources={len(records)} objects={len(records)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
