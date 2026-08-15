#!/usr/bin/env python3
"""Validate RootHealth durability capture and materialize crash-media states.

The input is UTF-8, tab-separated ``roothealth-powercut-tsv-v2``.  Decimal
integers are canonical (``0`` or a non-zero digit followed by digits; signed
fields may additionally have one leading ``-``).  Empty lines and comments
are not permitted.  The exact records are:

    H  2  512  target_st_dev  target_st_ino  target_st_rdev
    W  seq  write_id  epoch  operation  offset  requested  result  errno
       payload_offset  payload_length  flags  pid  tid
    S  seq  barrier_id  epoch  fsync|fdatasync  result  errno
       last_write_id  pid  tid
    C  seq  barrier_id  epoch  fsync|fdatasync  last_write_id  pid  tid

The whitespace above is explanatory; records use one tab between fields and
one record per line.  ``W`` operations are ``write``, ``pwrite``,
``pwrite64``, ``writev``, ``pwritev``, or ``pwritev2``.  Sequence, write, and
barrier identifiers start at one and are contiguous.  Epochs start at one; a
successful ``S`` closes its epoch and advances the next epoch.  ``C`` is an
optional terminal marker emitted immediately before a selected barrier is
suppressed and the process is killed.  It consumes the next sequence and
barrier identifiers but does not make its epoch durable.

Successful writes may be short because the production writer loops.  A
positive result owns exactly that many contiguous bytes in the external
payload file; a zero result or failed ``-1`` attempt owns none.  Attempts keep
their syscall order and identifiers even when they contribute no bytes.
Offsets and successful byte counts may be unaligned: alignment is a WAL
descriptor/oracle property, not a syscall-capture property.  All W/S/C records
must have the same positive pid/tid pair.  In particular, pwritev2
RWF_DSYNC/RWF_SYNC and every other unmodelled flag are rejected rather than
treated as an implicit durability barrier.

For each S (and a terminal C), the materializer models a crash immediately
before that barrier.  Writes in epochs closed by earlier S records are fully
durable.  Current-epoch cases retain syscall order but derive sector identity
only from ``floor(device_offset / 512)``.  They include event prefixes cut at
every physical sector boundary, leading/trailing fragments of every touched
physical sector, isolated epoch sectors, and isolated/suffix/all-but-one
sector states for every multi-sector syscall.  Bytes outside captured syscall
ranges always retain the prior durable image.  No ordering of unsynchronised
physical sectors is assumed.

Each logical case is recorded even when it is byte-identical to another case.
Image files are deduplicated only after their complete physical SHA-256 values
match (and a byte comparison defends against a hash collision).
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import asdict, dataclass
from typing import Iterable, Sequence


SCHEMA = "roothealth-powercut-tsv-v2"
SCHEMA_VERSION = 2
RELEASE_SECTOR_SIZE = 512
TEAR_WIDTHS = (1, 256, 511)
FICLONE = 0x40049409
CHUNK_SIZE = 1024 * 1024
MAX_EVENTS = 100_000

WRITE_OPERATIONS = {
    "write",
    "pwrite",
    "pwrite64",
    "writev",
    "pwritev",
    "pwritev2",
}
BARRIER_OPERATIONS = {"fsync", "fdatasync"}

UNSIGNED = re.compile(r"(?:0|[1-9][0-9]*)\Z")
SIGNED = re.compile(r"(?:0|-?[1-9][0-9]*)\Z")


class PowercutError(RuntimeError):
    """Qualification input is malformed or cannot be materialized safely."""


@dataclass(frozen=True)
class Header:
    version: int
    sector_size: int
    target_st_dev: int
    target_st_ino: int
    target_st_rdev: int


@dataclass(frozen=True)
class WriteEvent:
    seq: int
    write_id: int
    epoch: int
    operation: str
    offset: int
    requested: int
    result: int
    error: int
    payload_offset: int
    payload_length: int
    flags: int
    pid: int
    tid: int


@dataclass(frozen=True)
class BarrierEvent:
    record: str
    seq: int
    barrier_id: int
    epoch: int
    operation: str
    result: int | None
    error: int | None
    last_write_id: int
    pid: int
    tid: int


@dataclass(frozen=True)
class Inventory:
    header: Header
    writes: tuple[WriteEvent, ...]
    barriers: tuple[BarrierEvent, ...]
    writer_pid: int
    writer_tid: int
    payload_size: int
    event_count: int


def unsigned(text: str, field: str, line_number: int) -> int:
    if not UNSIGNED.fullmatch(text):
        raise PowercutError(
            f"line {line_number}: {field} is not a canonical unsigned decimal"
        )
    return int(text)


def signed(text: str, field: str, line_number: int) -> int:
    if not SIGNED.fullmatch(text):
        raise PowercutError(
            f"line {line_number}: {field} is not a canonical signed decimal"
        )
    return int(text)


def regular_file(path: Path, label: str) -> os.stat_result:
    try:
        details = path.lstat()
    except OSError as error:
        raise PowercutError(f"cannot stat {label} {path}: {error}") from error
    if not stat.S_ISREG(details.st_mode):
        raise PowercutError(f"{label} is not a regular non-symlink file: {path}")
    return details


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb", buffering=0) as handle:
            while True:
                block = handle.read(CHUNK_SIZE)
                if not block:
                    break
                digest.update(block)
    except OSError as error:
        raise PowercutError(f"cannot hash {path}: {error}") from error
    return digest.hexdigest()


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def require_distinct_output(
    output: Path, protected: Sequence[tuple[str, Path]], label: str
) -> None:
    destination = resolved(output)
    for protected_label, protected_path in protected:
        if destination == resolved(protected_path):
            raise PowercutError(
                f"{label} resolves to the protected {protected_label}: {output}"
            )


def parse_header(fields: list[str], line_number: int) -> Header:
    if len(fields) != 6:
        raise PowercutError(
            f"line {line_number}: H requires exactly 6 fields, found {len(fields)}"
        )
    header = Header(
        version=unsigned(fields[1], "schema version", line_number),
        sector_size=unsigned(fields[2], "sector size", line_number),
        target_st_dev=unsigned(fields[3], "target st_dev", line_number),
        target_st_ino=unsigned(fields[4], "target st_ino", line_number),
        target_st_rdev=unsigned(fields[5], "target st_rdev", line_number),
    )
    if header.version != SCHEMA_VERSION:
        raise PowercutError(
            f"line {line_number}: schema version is {header.version}, expected 2"
        )
    if header.sector_size != RELEASE_SECTOR_SIZE:
        raise PowercutError(
            f"line {line_number}: sector size is {header.sector_size}, expected 512"
        )
    return header


def parse_write(fields: list[str], line_number: int) -> WriteEvent:
    if len(fields) != 14:
        raise PowercutError(
            f"line {line_number}: W requires exactly 14 fields, found {len(fields)}"
        )
    operation = fields[4]
    if operation not in WRITE_OPERATIONS:
        raise PowercutError(
            f"line {line_number}: unrecognised write operation {operation!r}"
        )
    return WriteEvent(
        seq=unsigned(fields[1], "sequence", line_number),
        write_id=unsigned(fields[2], "write id", line_number),
        epoch=unsigned(fields[3], "epoch", line_number),
        operation=operation,
        offset=signed(fields[5], "write offset", line_number),
        requested=unsigned(fields[6], "requested length", line_number),
        result=signed(fields[7], "write result", line_number),
        error=unsigned(fields[8], "write errno", line_number),
        payload_offset=unsigned(fields[9], "payload offset", line_number),
        payload_length=unsigned(fields[10], "payload length", line_number),
        flags=unsigned(fields[11], "write flags", line_number),
        pid=unsigned(fields[12], "pid", line_number),
        tid=unsigned(fields[13], "tid", line_number),
    )


def parse_barrier(fields: list[str], line_number: int) -> BarrierEvent:
    record = fields[0]
    if record == "S":
        if len(fields) != 10:
            raise PowercutError(
                f"line {line_number}: S requires exactly 10 fields, found {len(fields)}"
            )
        result: int | None = signed(fields[5], "barrier result", line_number)
        error: int | None = unsigned(fields[6], "barrier errno", line_number)
        last_write_index = 7
        pid_index = 8
        tid_index = 9
    elif record == "C":
        if len(fields) != 8:
            raise PowercutError(
                f"line {line_number}: C requires exactly 8 fields, found {len(fields)}"
            )
        result = None
        error = None
        last_write_index = 5
        pid_index = 6
        tid_index = 7
    else:  # pragma: no cover - caller constrains the tag
        raise PowercutError(f"line {line_number}: invalid barrier record {record!r}")

    operation = fields[4]
    if operation not in BARRIER_OPERATIONS:
        raise PowercutError(
            f"line {line_number}: unrecognised barrier operation {operation!r}"
        )
    return BarrierEvent(
        record=record,
        seq=unsigned(fields[1], "sequence", line_number),
        barrier_id=unsigned(fields[2], "barrier id", line_number),
        epoch=unsigned(fields[3], "epoch", line_number),
        operation=operation,
        result=result,
        error=error,
        last_write_id=unsigned(
            fields[last_write_index], "last write id", line_number
        ),
        pid=unsigned(fields[pid_index], "pid", line_number),
        tid=unsigned(fields[tid_index], "tid", line_number),
    )


def parse_inventory(events_path: Path, payload_path: Path, source_size: int) -> Inventory:
    regular_file(events_path, "event log")
    payload_stat = regular_file(payload_path, "payload")
    if source_size <= 0 or source_size % RELEASE_SECTOR_SIZE:
        raise PowercutError(
            f"source size {source_size} is not a positive 512-byte multiple"
        )

    try:
        text = events_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise PowercutError(f"cannot read event log {events_path}: {error}") from error
    if not text:
        raise PowercutError("event log is empty")
    if "\x00" in text:
        raise PowercutError("event log contains NUL")
    lines = text.splitlines()
    if len(lines) > MAX_EVENTS + 1:
        raise PowercutError(f"event log exceeds the {MAX_EVENTS}-event bound")
    if any(not line for line in lines):
        raise PowercutError("event log contains an empty record")

    first = lines[0].split("\t")
    if not first or first[0] != "H":
        raise PowercutError("event log must begin with one H record")
    header = parse_header(first, 1)

    writes: list[WriteEvent] = []
    barriers: list[BarrierEvent] = []
    expected_seq = 1
    expected_write_id = 1
    expected_barrier_id = 1
    current_epoch = 1
    expected_payload_offset = 0
    latest_write_id = 0
    writer: tuple[int, int] | None = None
    terminal_crash = False
    final_tag = "H"

    for line_number, line in enumerate(lines[1:], 2):
        fields = line.split("\t")
        tag = fields[0]
        if tag == "H":
            raise PowercutError(f"line {line_number}: duplicate H record")
        if terminal_crash:
            raise PowercutError(f"line {line_number}: record follows terminal C")
        if tag == "W":
            event: WriteEvent | BarrierEvent = parse_write(fields, line_number)
        elif tag in ("S", "C"):
            event = parse_barrier(fields, line_number)
        else:
            raise PowercutError(f"line {line_number}: unknown record tag {tag!r}")

        if event.seq != expected_seq:
            raise PowercutError(
                f"line {line_number}: sequence {event.seq} is not expected {expected_seq}"
            )
        expected_seq += 1
        if event.epoch != current_epoch:
            raise PowercutError(
                f"line {line_number}: epoch {event.epoch} is not current {current_epoch}"
            )
        if event.pid <= 0 or event.tid <= 0:
            raise PowercutError(f"line {line_number}: pid and tid must be positive")
        identity = (event.pid, event.tid)
        if writer is None:
            writer = identity
        elif writer != identity:
            raise PowercutError(
                f"line {line_number}: multiple target writers {writer!r} and {identity!r}"
            )

        if isinstance(event, WriteEvent):
            if event.write_id != expected_write_id:
                raise PowercutError(
                    f"line {line_number}: write id {event.write_id} is not expected "
                    f"{expected_write_id}"
                )
            expected_write_id += 1
            latest_write_id = event.write_id
            if event.requested <= 0:
                raise PowercutError(f"line {line_number}: zero-length write is forbidden")
            if event.result < -1 or event.result > event.requested:
                raise PowercutError(
                    f"line {line_number}: impossible write result {event.result}, "
                    f"requested {event.requested}"
                )
            if event.result == -1 and event.error <= 0:
                raise PowercutError(
                    f"line {line_number}: failed write has no errno"
                )
            if event.result >= 0 and event.error != 0:
                raise PowercutError(
                    f"line {line_number}: nonfailed write retained errno {event.error}"
                )
            captured_length = max(event.result, 0)
            if event.payload_length != captured_length:
                raise PowercutError(
                    f"line {line_number}: payload length {event.payload_length} "
                    f"does not equal captured result length {captured_length}"
                )
            if event.payload_offset != expected_payload_offset:
                raise PowercutError(
                    f"line {line_number}: payload offset {event.payload_offset} is not "
                    f"contiguous expected offset {expected_payload_offset}"
                )
            expected_payload_offset += event.payload_length
            if event.offset < 0:
                raise PowercutError(f"line {line_number}: non-positional write is forbidden")
            if event.offset > source_size or event.offset + captured_length > source_size:
                raise PowercutError(
                    f"line {line_number}: write [{event.offset}, "
                    f"{event.offset + captured_length}) exceeds source size {source_size}"
                )
            if event.flags:
                raise PowercutError(
                    f"line {line_number}: write flags 0x{event.flags:x} contain "
                    "unmodelled/durability semantics"
                )
            writes.append(event)
        else:
            if event.barrier_id != expected_barrier_id:
                raise PowercutError(
                    f"line {line_number}: barrier id {event.barrier_id} is not expected "
                    f"{expected_barrier_id}"
                )
            expected_barrier_id += 1
            if event.last_write_id != latest_write_id:
                raise PowercutError(
                    f"line {line_number}: barrier last-write id {event.last_write_id} "
                    f"does not equal {latest_write_id}"
                )
            if event.record == "S":
                if event.result != 0 or event.error != 0:
                    raise PowercutError(
                        f"line {line_number}: unsuccessful durability barrier "
                        f"result={event.result} errno={event.error}"
                    )
                current_epoch += 1
            else:
                terminal_crash = True
            barriers.append(event)
        final_tag = tag

    if writer is None or not writes:
        raise PowercutError("event log contains no target writes")
    if not barriers:
        raise PowercutError("event log contains no target durability barrier")
    if final_tag not in ("S", "C"):
        raise PowercutError("event log ends with writes not closed by S or C")
    if expected_payload_offset != payload_stat.st_size:
        raise PowercutError(
            f"payload size {payload_stat.st_size} does not equal captured span "
            f"{expected_payload_offset}"
        )

    return Inventory(
        header=header,
        writes=tuple(writes),
        barriers=tuple(barriers),
        writer_pid=writer[0],
        writer_tid=writer[1],
        payload_size=payload_stat.st_size,
        event_count=expected_seq - 1,
    )


def read_exact(fd: int, offset: int, length: int, label: str) -> bytes:
    pieces: list[bytes] = []
    remaining = length
    cursor = offset
    while remaining:
        try:
            piece = os.pread(fd, remaining, cursor)
        except OSError as error:
            raise PowercutError(f"cannot read {label} at {cursor}: {error}") from error
        if not piece:
            raise PowercutError(f"short read of {label} at {cursor}")
        pieces.append(piece)
        cursor += len(piece)
        remaining -= len(piece)
    return b"".join(pieces)


def write_exact(fd: int, offset: int, data: bytes, label: str) -> None:
    view = memoryview(data)
    cursor = offset
    while view:
        try:
            written = os.pwrite(fd, view, cursor)
        except OSError as error:
            raise PowercutError(f"cannot write {label} at {cursor}: {error}") from error
        if written <= 0:
            raise PowercutError(f"short write of {label} at {cursor}")
        cursor += written
        view = view[written:]


def hash_fd(fd: int, size: int) -> str:
    digest = hashlib.sha256()
    cursor = 0
    while cursor < size:
        block = read_exact(fd, cursor, min(CHUNK_SIZE, size - cursor), "image")
        digest.update(block)
        cursor += len(block)
    return digest.hexdigest()


def clone_dense(source_fd: int, destination_fd: int, size: int) -> None:
    os.ftruncate(destination_fd, size)
    cursor = 0
    while cursor < size:
        block = read_exact(
            source_fd, cursor, min(CHUNK_SIZE, size - cursor), "source image"
        )
        write_exact(destination_fd, cursor, block, "destination image")
        cursor += len(block)


def clone_sparse(source_fd: int, destination_fd: int, size: int) -> bool:
    if not hasattr(os, "SEEK_DATA") or not hasattr(os, "SEEK_HOLE"):
        return False
    os.ftruncate(destination_fd, size)
    cursor = 0
    copied_any = False
    try:
        while cursor < size:
            try:
                data_offset = os.lseek(source_fd, cursor, os.SEEK_DATA)
            except OSError as error:
                if error.errno == errno.ENXIO:
                    break
                if error.errno in (errno.EINVAL, errno.ENOTSUP, errno.ENOSYS):
                    return False
                raise
            hole_offset = os.lseek(source_fd, data_offset, os.SEEK_HOLE)
            end = min(hole_offset, size)
            position = data_offset
            while position < end:
                block = read_exact(
                    source_fd,
                    position,
                    min(CHUNK_SIZE, end - position),
                    "source image",
                )
                write_exact(destination_fd, position, block, "destination image")
                position += len(block)
            copied_any = True
            cursor = end
    except OSError as error:
        raise PowercutError(f"cannot clone sparse source: {error}") from error
    return copied_any or size == 0 or cursor >= size


def clone_source(source_fd: int, destination: Path, size: int) -> int:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        destination_fd = os.open(destination, flags, 0o600)
    except OSError as error:
        raise PowercutError(f"cannot create state image {destination}: {error}") from error
    try:
        try:
            fcntl.ioctl(destination_fd, FICLONE, source_fd)
        except OSError:
            os.ftruncate(destination_fd, 0)
            if not clone_sparse(source_fd, destination_fd, size):
                os.ftruncate(destination_fd, 0)
                clone_dense(source_fd, destination_fd, size)
        if os.fstat(destination_fd).st_size != size:
            raise PowercutError(f"cloned image {destination} has the wrong size")
        return destination_fd
    except BaseException:
        os.close(destination_fd)
        try:
            destination.unlink()
        except OSError:
            pass
        raise


def files_equal(left: Path, right: Path, size: int) -> bool:
    left_fd = os.open(left, os.O_RDONLY)
    right_fd = os.open(right, os.O_RDONLY)
    try:
        cursor = 0
        while cursor < size:
            length = min(CHUNK_SIZE, size - cursor)
            if read_exact(left_fd, cursor, length, str(left)) != read_exact(
                right_fd, cursor, length, str(right)
            ):
                return False
            cursor += length
        return True
    finally:
        os.close(left_fd)
        os.close(right_fd)


def writes_by_epoch(inventory: Inventory) -> dict[int, list[WriteEvent]]:
    result: dict[int, list[WriteEvent]] = {}
    for event in inventory.writes:
        result.setdefault(event.epoch, []).append(event)
    return result


def captured_length(event: WriteEvent) -> int:
    return max(event.result, 0)


def touched_sectors(event: WriteEvent) -> list[int]:
    length = captured_length(event)
    if not length:
        return []
    first = event.offset // RELEASE_SECTOR_SIZE
    last = (event.offset + length - 1) // RELEASE_SECTOR_SIZE
    return list(range(first, last + 1))


def write_segment(
    event: WriteEvent, absolute_start: int, absolute_end: int
) -> dict[str, int] | None:
    write_start = event.offset
    write_end = event.offset + captured_length(event)
    start = max(write_start, absolute_start)
    end = min(write_end, absolute_end)
    if start >= end:
        return None
    return {
        "write_id": event.write_id,
        "local_offset": start - write_start,
        "length": end - start,
        "device_offset": start,
    }


def full_segment(event: WriteEvent) -> dict[str, int] | None:
    return write_segment(event, event.offset, event.offset + captured_length(event))


def segments_for_ranges(
    events: Sequence[WriteEvent], ranges: Sequence[tuple[int, int]]
) -> list[dict[str, int]]:
    segments: list[dict[str, int]] = []
    for event in events:
        for start, end in sorted(ranges):
            selected = write_segment(event, start, end)
            if selected is not None:
                segments.append(selected)
    return segments


def ranges_for_sectors(sectors: Iterable[int]) -> list[tuple[int, int]]:
    return [
        (sector * RELEASE_SECTOR_SIZE, (sector + 1) * RELEASE_SECTOR_SIZE)
        for sector in sorted(set(sectors))
    ]


def event_prefix_cuts(event: WriteEvent) -> list[int]:
    length = captured_length(event)
    if not length:
        return [0]
    cuts = {0, length}
    boundary = ((event.offset // RELEASE_SECTOR_SIZE) + 1) * RELEASE_SECTOR_SIZE
    end = event.offset + length
    while boundary < end:
        cuts.add(boundary - event.offset)
        boundary += RELEASE_SECTOR_SIZE
    return sorted(cuts)


def case_specs(inventory: Inventory) -> list[dict[str, object]]:
    epochs = writes_by_epoch(inventory)
    cases: list[dict[str, object]] = []
    for barrier in inventory.barriers:
        current = epochs.get(barrier.epoch, [])
        positive = [event for event in current if captured_length(event)]
        physical_sectors = sorted(
            {sector for event in positive for sector in touched_sectors(event)}
        )
        prefix = f"b{barrier.barrier_id:06d}-e{barrier.epoch:06d}"
        common: dict[str, object] = {
            "barrier_id": barrier.barrier_id,
            "barrier_record": barrier.record,
            "barrier_operation": barrier.operation,
            "epoch": barrier.epoch,
            "epoch_result_bytes": sum(captured_length(event) for event in current),
            "epoch_write_ids": [event.write_id for event in current],
            "positive_write_ids": [event.write_id for event in positive],
            "touched_physical_sectors": physical_sectors,
        }

        prior_event_segments: list[dict[str, int]] = []
        if not current:
            cases.append(
                {
                    **common,
                    "id": f"{prefix}-empty-epoch",
                    "pattern": "empty-epoch",
                    "segments": [],
                    "write_id": None,
                    "write_result": None,
                    "physical_sector": None,
                    "width": None,
                }
            )
        for event in current:
            for cut in event_prefix_cuts(event):
                segments = [dict(segment) for segment in prior_event_segments]
                if cut:
                    selected = write_segment(event, event.offset, event.offset + cut)
                    if selected is None:  # pragma: no cover - cut is bounded above
                        raise PowercutError("internal event-prefix cut selected no bytes")
                    segments.append(selected)
                cases.append(
                    {
                        **common,
                        "id": (
                            f"{prefix}-event-w{event.write_id:06d}-"
                            f"prefix-{cut:012d}"
                        ),
                        "pattern": "event-prefix",
                        "segments": segments,
                        "write_id": event.write_id,
                        "write_result": event.result,
                        "write_requested": event.requested,
                        "prefix_bytes_in_write": cut,
                        "physical_sector": None,
                        "width": None,
                    }
                )

            for sector in touched_sectors(event):
                sector_start = sector * RELEASE_SECTOR_SIZE
                sector_end = sector_start + RELEASE_SECTOR_SIZE
                for direction in ("leading", "trailing"):
                    for width in TEAR_WIDTHS:
                        fragment = (
                            (sector_start, sector_start + width)
                            if direction == "leading"
                            else (sector_end - width, sector_end)
                        )
                        selected = write_segment(event, *fragment)
                        cases.append(
                            {
                                **common,
                                "id": (
                                    f"{prefix}-w{event.write_id:06d}-sector-"
                                    f"{sector:012d}-{direction}-{width:03d}"
                                ),
                                "pattern": f"write-sector-{direction}",
                                "segments": [] if selected is None else [selected],
                                "write_id": event.write_id,
                                "write_result": event.result,
                                "physical_sector": sector,
                                "sector_device_offset": sector_start,
                                "width": width,
                            }
                        )
            event_full = full_segment(event)
            if event_full is not None:
                prior_event_segments.append(event_full)

        # A physical sector may contain bytes from several overlapping or
        # discontiguous syscalls.  Apply those syscalls in capture order while
        # leaving every other current-epoch sector at the prior durable image.
        for sector in physical_sectors:
            sector_start = sector * RELEASE_SECTOR_SIZE
            sector_end = sector_start + RELEASE_SECTOR_SIZE
            full = segments_for_ranges(current, [(sector_start, sector_end)])
            cases.append(
                {
                    **common,
                    "id": f"{prefix}-epoch-sector-{sector:012d}-isolated",
                    "pattern": "epoch-isolated-sector",
                    "segments": full,
                    "write_id": None,
                    "write_result": None,
                    "physical_sector": sector,
                    "sector_device_offset": sector_start,
                    "width": RELEASE_SECTOR_SIZE,
                }
            )
            for direction in ("leading", "trailing"):
                for width in TEAR_WIDTHS:
                    fragment = (
                        (sector_start, sector_start + width)
                        if direction == "leading"
                        else (sector_end - width, sector_end)
                    )
                    cases.append(
                        {
                            **common,
                            "id": (
                                f"{prefix}-epoch-sector-{sector:012d}-"
                                f"{direction}-{width:03d}"
                            ),
                            "pattern": f"epoch-sector-{direction}",
                            "segments": segments_for_ranges(current, [fragment]),
                            "write_id": None,
                            "write_result": None,
                            "physical_sector": sector,
                            "sector_device_offset": sector_start,
                            "width": width,
                        }
                    )

        # Without role metadata the generic capture cannot distinguish a
        # control write from a large old-payload append.  Therefore every
        # multi-sector syscall gets the complete bounded sector classes; no
        # first/last/run-transition reduction is silently applied.
        for event in positive:
            sectors = touched_sectors(event)
            if len(sectors) <= 1:
                continue
            for index, sector in enumerate(sectors):
                patterns = (
                    ("write-isolated-sector", [sector]),
                    ("write-sector-suffix", sectors[index:]),
                    ("write-all-but-one-sector", sectors[:index] + sectors[index + 1 :]),
                )
                for pattern, selected_sectors in patterns:
                    cases.append(
                        {
                            **common,
                            "id": (
                                f"{prefix}-w{event.write_id:06d}-{pattern}-"
                                f"{sector:012d}"
                            ),
                            "pattern": pattern,
                            "segments": segments_for_ranges(
                                [event], ranges_for_sectors(selected_sectors)
                            ),
                            "write_id": event.write_id,
                            "write_result": event.result,
                            "physical_sector": sector,
                            "selected_physical_sectors": selected_sectors,
                            "width": None,
                        }
                    )
    return cases


def apply_write_segment(
    destination_fd: int,
    payload_fd: int,
    event: WriteEvent,
    local_offset: int,
    length: int,
) -> None:
    if length <= 0 or local_offset < 0 or local_offset + length > event.result:
        raise PowercutError("internal write-segment bounds are invalid")
    data = read_exact(
        payload_fd,
        event.payload_offset + local_offset,
        length,
        f"payload for write {event.write_id}",
    )
    write_exact(
        destination_fd,
        event.offset + local_offset,
        data,
        f"state write {event.write_id}",
    )


def apply_full_write(
    destination_fd: int, payload_fd: int, event: WriteEvent
) -> None:
    length = captured_length(event)
    if length:
        apply_write_segment(destination_fd, payload_fd, event, 0, length)


def apply_case(
    destination_fd: int,
    payload_fd: int,
    inventory: Inventory,
    case: dict[str, object],
) -> None:
    target_epoch = int(case["epoch"])
    for event in inventory.writes:
        if event.epoch < target_epoch:
            apply_full_write(destination_fd, payload_fd, event)
    current = {
        event.write_id: event
        for event in inventory.writes
        if event.epoch == target_epoch
    }
    segments = case["segments"]
    if not isinstance(segments, list):  # pragma: no cover - generated internally
        raise PowercutError("internal case segments are not a list")
    previous_write_id = 0
    for raw_segment in segments:
        if not isinstance(raw_segment, dict):
            raise PowercutError("internal case segment is not an object")
        try:
            write_id = int(raw_segment["write_id"])
            local_offset = int(raw_segment["local_offset"])
            length = int(raw_segment["length"])
            device_offset = int(raw_segment["device_offset"])
        except (KeyError, TypeError, ValueError) as error:
            raise PowercutError("internal case segment fields are invalid") from error
        if write_id < previous_write_id:
            raise PowercutError("case segments are not in syscall order")
        previous_write_id = write_id
        event = current.get(write_id)
        if event is None:
            raise PowercutError(f"case references non-current write {write_id}")
        if device_offset != event.offset + local_offset:
            raise PowercutError("case segment device/local offsets disagree")
        apply_write_segment(
            destination_fd, payload_fd, event, local_offset, length
        )


def case_overlay(
    source_fd: int,
    payload_fd: int,
    inventory: Inventory,
    case: dict[str, object],
) -> tuple[tuple[int, bytes], ...]:
    """Return the exact changed physical sectors for a generated case.

    A capture commonly has hundreds of logical cut descriptions that resolve
    to the same physical media.  Materializing and hashing the complete source
    image for every alias is needlessly quadratic in image size.  This routine
    applies the same ordered byte segments as ``apply_case`` to private
    512-byte sector buffers, then returns an exact (not hash-only) canonical
    representation of sectors that differ from the immutable source.  The
    full image is still cloned, fsynced, and SHA-256 hashed once for every
    distinct canonical representation.
    """

    originals: dict[int, bytes] = {}
    sectors: dict[int, bytearray] = {}

    def overlay_segment(event: WriteEvent, local_offset: int, length: int) -> None:
        if length <= 0 or local_offset < 0 or local_offset + length > event.result:
            raise PowercutError("internal overlay write-segment bounds are invalid")
        data = read_exact(
            payload_fd,
            event.payload_offset + local_offset,
            length,
            f"overlay payload for write {event.write_id}",
        )
        absolute = event.offset + local_offset
        consumed = 0
        while consumed < length:
            position = absolute + consumed
            sector = position // RELEASE_SECTOR_SIZE
            within = position % RELEASE_SECTOR_SIZE
            selected = min(RELEASE_SECTOR_SIZE - within, length - consumed)
            if sector not in sectors:
                original = read_exact(
                    source_fd,
                    sector * RELEASE_SECTOR_SIZE,
                    RELEASE_SECTOR_SIZE,
                    f"source sector {sector}",
                )
                originals[sector] = original
                sectors[sector] = bytearray(original)
            sectors[sector][within : within + selected] = data[
                consumed : consumed + selected
            ]
            consumed += selected

    target_epoch = int(case["epoch"])
    for event in inventory.writes:
        if event.epoch < target_epoch and captured_length(event):
            overlay_segment(event, 0, captured_length(event))

    current = {
        event.write_id: event
        for event in inventory.writes
        if event.epoch == target_epoch
    }
    segments = case["segments"]
    if not isinstance(segments, list):  # pragma: no cover - generated internally
        raise PowercutError("internal overlay case segments are not a list")
    previous_write_id = 0
    for raw_segment in segments:
        if not isinstance(raw_segment, dict):
            raise PowercutError("internal overlay case segment is not an object")
        try:
            write_id = int(raw_segment["write_id"])
            local_offset = int(raw_segment["local_offset"])
            length = int(raw_segment["length"])
            device_offset = int(raw_segment["device_offset"])
        except (KeyError, TypeError, ValueError) as error:
            raise PowercutError("internal overlay case segment fields are invalid") from error
        if write_id < previous_write_id:
            raise PowercutError("overlay case segments are not in syscall order")
        previous_write_id = write_id
        event = current.get(write_id)
        if event is None:
            raise PowercutError(f"overlay case references non-current write {write_id}")
        if device_offset != event.offset + local_offset:
            raise PowercutError("overlay case device/local offsets disagree")
        overlay_segment(event, local_offset, length)

    return tuple(
        (sector, bytes(sectors[sector]))
        for sector in sorted(sectors)
        if bytes(sectors[sector]) != originals[sector]
    )


def source_metadata(path: Path) -> tuple[os.stat_result, str]:
    details = regular_file(path, "source image")
    if details.st_size <= 0 or details.st_size % RELEASE_SECTOR_SIZE:
        raise PowercutError(
            f"source image size {details.st_size} is not a positive 512-byte multiple"
        )
    return details, file_sha256(path)


def validate_inventory_final(
    source: Path,
    inventory_final: Path,
    payload: Path,
    inventory: Inventory,
) -> str:
    if any(barrier.record == "C" for barrier in inventory.barriers):
        raise PowercutError("a C inventory has no trustworthy final media image")
    regular_file(inventory_final, "inventory final image")
    if inventory_final.stat().st_size != source.stat().st_size:
        raise PowercutError("inventory final image size differs from source")

    with tempfile.TemporaryDirectory(prefix="roothealth-powercut-replay.") as temp:
        replay = Path(temp) / "replay.img"
        source_fd = os.open(source, os.O_RDONLY)
        payload_fd = os.open(payload, os.O_RDONLY)
        try:
            replay_fd = clone_source(source_fd, replay, source.stat().st_size)
            try:
                for event in inventory.writes:
                    apply_full_write(replay_fd, payload_fd, event)
                os.fsync(replay_fd)
            finally:
                os.close(replay_fd)
        finally:
            os.close(payload_fd)
            os.close(source_fd)
        if not files_equal(replay, inventory_final, source.stat().st_size):
            raise PowercutError(
                "captured writes do not replay byte-for-byte to the inventory final image"
            )
    return file_sha256(inventory_final)


def inventory_report(
    source: Path,
    events: Path,
    payload: Path,
    inventory: Inventory,
    source_hash: str,
    inventory_final_hash: str | None,
) -> dict[str, object]:
    return {
        "format": 1,
        "schema": SCHEMA,
        "source": {
            "path": str(source),
            "size": source.stat().st_size,
            "sha256": source_hash,
        },
        "capture": {
            "events_path": str(events),
            "events_sha256": file_sha256(events),
            "payload_path": str(payload),
            "payload_size": inventory.payload_size,
            "payload_sha256": file_sha256(payload),
            "event_count": inventory.event_count,
            "write_count": len(inventory.writes),
            "positive_write_count": sum(
                event.result > 0 for event in inventory.writes
            ),
            "short_write_count": sum(
                0 < event.result < event.requested for event in inventory.writes
            ),
            "zero_write_count": sum(
                event.result == 0 for event in inventory.writes
            ),
            "failed_write_count": sum(
                event.result == -1 for event in inventory.writes
            ),
            "barrier_count": len(inventory.barriers),
            "writer_pid": inventory.writer_pid,
            "writer_tid": inventory.writer_tid,
            "target": asdict(inventory.header),
            "terminal_crash": any(
                barrier.record == "C" for barrier in inventory.barriers
            ),
            "inventory_final_sha256": inventory_final_hash,
        },
    }


def atomic_json(path: Path, value: dict[str, object]) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = parent / f".{path.name}.tmp-{os.getpid()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        data = (
            json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
        ).encode("ascii")
        write_exact(descriptor, 0, data, "manifest")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def validate_command(args: argparse.Namespace) -> dict[str, object]:
    source = Path(args.source)
    events = Path(args.events)
    payload = Path(args.payload)
    source_stat, source_hash = source_metadata(source)
    inventory = parse_inventory(events, payload, source_stat.st_size)
    final_hash = None
    if args.inventory_final:
        final_hash = validate_inventory_final(
            source, Path(args.inventory_final), payload, inventory
        )
    if file_sha256(source) != source_hash:
        raise PowercutError("source image changed during validation")
    report = inventory_report(
        source, events, payload, inventory, source_hash, final_hash
    )
    if args.report:
        report_path = Path(args.report)
        protected = [("source image", source), ("event log", events), ("payload", payload)]
        if args.inventory_final:
            protected.append(("inventory final image", Path(args.inventory_final)))
        require_distinct_output(report_path, protected, "validation report")
        if report_path.exists():
            raise PowercutError(f"validation report already exists: {report_path}")
        atomic_json(report_path, report)
        if file_sha256(source) != source_hash:
            raise PowercutError("source image changed while publishing validation report")
    return report


def materialize_command(args: argparse.Namespace) -> dict[str, object]:
    source = Path(args.source)
    events = Path(args.events)
    payload = Path(args.payload)
    output = Path(args.output_dir)
    manifest_path = Path(args.manifest)
    source_stat, source_hash = source_metadata(source)
    inventory = parse_inventory(events, payload, source_stat.st_size)
    final_hash = None
    if args.inventory_final:
        final_hash = validate_inventory_final(
            source, Path(args.inventory_final), payload, inventory
        )

    protected = [("source image", source), ("event log", events), ("payload", payload)]
    if args.inventory_final:
        protected.append(("inventory final image", Path(args.inventory_final)))
    require_distinct_output(output, protected, "output directory")
    require_distinct_output(manifest_path, protected, "manifest")
    if resolved(manifest_path) == resolved(output):
        raise PowercutError("manifest path resolves to the output directory")
    if output.exists():
        raise PowercutError(f"output directory already exists: {output}")
    if manifest_path.exists():
        raise PowercutError(f"manifest already exists: {manifest_path}")
    output.mkdir(parents=True, mode=0o700)

    specs = case_specs(inventory)
    physical: dict[str, dict[str, object]] = {}
    overlays: dict[tuple[tuple[int, bytes], ...], str] = {}
    logical: list[dict[str, object]] = []
    source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    payload_fd = os.open(payload, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        for number, spec in enumerate(specs, 1):
            case_id = str(spec["id"])
            overlay = case_overlay(source_fd, payload_fd, inventory, spec)
            state_hash = overlays.get(overlay)
            if state_hash is None:
                temporary = output / f".state-{number:08d}.tmp"
                destination_fd = clone_source(source_fd, temporary, source_stat.st_size)
                try:
                    apply_case(destination_fd, payload_fd, inventory, spec)
                    os.fsync(destination_fd)
                    state_hash = hash_fd(destination_fd, source_stat.st_size)
                finally:
                    os.close(destination_fd)

                state_name = f"state-{state_hash}.ntfs"
                state_path = output / state_name
                if state_hash in physical:
                    if not state_path.exists() or not files_equal(
                        temporary, state_path, source_stat.st_size
                    ):
                        raise PowercutError(
                            f"physical SHA-256 collision/inconsistent state {state_hash}"
                        )
                    temporary.unlink()
                else:
                    os.replace(temporary, state_path)
                    physical[state_hash] = {
                        "sha256": state_hash,
                        "path": state_name,
                        "size": source_stat.st_size,
                        "logical_case_ids": [],
                    }
                overlays[overlay] = state_hash
            state_name = f"state-{state_hash}.ntfs"
            aliases = physical[state_hash]["logical_case_ids"]
            if not isinstance(aliases, list):  # pragma: no cover
                raise PowercutError("internal physical alias list is malformed")
            aliases.append(case_id)
            logical.append(
                {
                    **spec,
                    "physical_sha256": state_hash,
                    "physical_path": state_name,
                }
            )
    finally:
        os.close(payload_fd)
        os.close(source_fd)

    if file_sha256(source) != source_hash:
        raise PowercutError("source image changed during materialization")
    report = inventory_report(
        source, events, payload, inventory, source_hash, final_hash
    )
    report.update(
        {
            "tear_widths": list(TEAR_WIDTHS),
            "state_directory": str(output),
            "persistence_model": {
                "sector_identity": "physical-device-offset-div-512",
                "prior_durable_baseline": True,
                "unsynced_epoch_prefix_order_assumed": False,
                "event_prefix_cases": True,
                "epoch_isolated_sector_cases": True,
                "multi_sector_write_classes": [
                    "write-isolated-sector",
                    "write-sector-suffix",
                    "write-all-but-one-sector",
                ],
                "write_role_metadata": False,
                "large_append_reduction_applied": False,
                "role_metadata_required_before_reduction": True,
                "exact_sector_overlay_deduplication": True,
            },
            "logical_case_count": len(logical),
            "physical_state_count": len(physical),
            "logical_cases": logical,
            "physical_states": [physical[key] for key in sorted(physical)],
        }
    )
    atomic_json(manifest_path, report)
    if file_sha256(source) != source_hash:
        raise PowercutError("source image changed while publishing materialization manifest")
    return report


def event_text() -> tuple[str, bytes]:
    payloads = [
        b"abc",
        b"UVWXYZ",
        b"12",
        b"34",
        b"C" * 1024,
        b"D" * 512,
    ]
    rows = [
        "H\t2\t512\t10\t20\t30",
        "W\t1\t1\t1\tpwrite\t3\t3\t3\t0\t0\t3\t0\t700\t700",
        "W\t2\t2\t1\tpwritev\t510\t6\t6\t0\t3\t6\t0\t700\t700",
        "W\t3\t3\t1\tpwrite\t1020\t4\t2\t0\t9\t2\t0\t700\t700",
        "W\t4\t4\t1\tpwrite\t1022\t2\t2\t0\t11\t2\t0\t700\t700",
        "W\t5\t5\t1\tpwrite\t1500\t2\t0\t0\t13\t0\t0\t700\t700",
        "W\t6\t6\t1\tpwrite\t1600\t2\t-1\t5\t13\t0\t0\t700\t700",
        "S\t7\t1\t1\tfdatasync\t0\t0\t6\t700\t700",
        "W\t8\t7\t2\tpwrite64\t512\t1024\t1024\t0\t13\t1024\t0\t700\t700",
        "W\t9\t8\t2\tpwritev2\t2048\t512\t512\t0\t1037\t512\t0\t700\t700",
        "S\t10\t2\t2\tfsync\t0\t0\t8\t700\t700",
    ]
    return "\n".join(rows) + "\n", b"".join(payloads)


def expected_state(source: bytes, writes: Iterable[tuple[int, bytes]]) -> bytes:
    value = bytearray(source)
    for offset, data in writes:
        value[offset : offset + len(data)] = data
    return bytes(value)


def self_test() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="roothealth-powercut-selftest.") as temp:
        root = Path(temp)
        source = root / "source.img"
        events = root / "events.tsv"
        payload = root / "payload.bin"
        inventory_final = root / "inventory-final.img"
        source_bytes = bytes((index * 17 + 3) % 251 for index in range(4096))
        source.write_bytes(source_bytes)
        text, payload_bytes = event_text()
        events.write_text(text, encoding="utf-8")
        payload.write_bytes(payload_bytes)
        final_bytes = expected_state(
            source_bytes,
            (
                (3, b"abc"),
                (510, b"UVWXYZ"),
                (1020, b"12"),
                (1022, b"34"),
                (512, b"C" * 1024),
                (2048, b"D" * 512),
            ),
        )
        inventory_final.write_bytes(final_bytes)
        original_hash = file_sha256(source)

        validate_args = argparse.Namespace(
            source=str(source),
            events=str(events),
            payload=str(payload),
            inventory_final=str(inventory_final),
            report=None,
        )
        validation = validate_command(validate_args)
        capture = validation["capture"]
        if not isinstance(capture, dict) or capture["write_count"] != 8:
            raise PowercutError("self-test validation lost captured writes")
        if (
            capture["short_write_count"] != 1
            or capture["zero_write_count"] != 1
            or capture["failed_write_count"] != 1
        ):
            raise PowercutError("self-test write-attempt diagnostics disagree")

        output = root / "states"
        manifest_path = root / "manifest.json"
        materialize_args = argparse.Namespace(
            source=str(source),
            events=str(events),
            payload=str(payload),
            inventory_final=str(inventory_final),
            output_dir=str(output),
            manifest=str(manifest_path),
        )
        manifest = materialize_command(materialize_args)
        logical = manifest["logical_cases"]
        if not isinstance(logical, list) or len(logical) != 111:
            raise PowercutError(
                f"self-test expected 111 logical cases, found {len(logical)}"
            )
        by_id = {str(case["id"]): case for case in logical}

        def state_bytes(case_id: str) -> bytes:
            case = by_id[case_id]
            return (output / str(case["physical_path"])).read_bytes()

        barrier1_full = "b000001-e000001-event-w000006-prefix-000000000000"
        barrier2_zero = "b000002-e000002-event-w000007-prefix-000000000000"
        if by_id[barrier1_full]["physical_sha256"] != by_id[barrier2_zero][
            "physical_sha256"
        ]:
            raise PowercutError("self-test did not physically deduplicate epoch handoff")

        crossing_prefix = expected_state(
            source_bytes, ((3, b"abc"), (510, b"UV"))
        )
        if (
            state_bytes(
                "b000001-e000001-event-w000002-prefix-000000000002"
            )
            != crossing_prefix
        ):
            raise PowercutError("self-test physical-boundary event prefix is incorrect")

        durable_epoch1 = expected_state(
            source_bytes,
            ((3, b"abc"), (510, b"UVWXYZ"), (1020, b"12"), (1022, b"34")),
        )
        overlap_prefix = expected_state(durable_epoch1, ((512, b"C" * 512),))
        if (
            state_bytes(
                "b000002-e000002-event-w000007-prefix-000000000512"
            )
            != overlap_prefix
        ):
            raise PowercutError("self-test overlapping epoch prefix is incorrect")

        previous_epoch_preserved = expected_state(durable_epoch1, ((512, b"C"),))
        previous_epoch_case = state_bytes(
            "b000002-e000002-w000007-sector-000000000001-leading-001"
        )
        if previous_epoch_case != previous_epoch_preserved:
            raise PowercutError("self-test tear did not preserve prior durable epoch")
        if previous_epoch_case[513:516] != durable_epoch1[513:516]:
            raise PowercutError("self-test tear changed prior-epoch bytes outside fragment")

        crossing_leading = expected_state(source_bytes, ((510, b"U"),))
        crossing_leading_id = (
            "b000001-e000001-w000002-sector-000000000000-leading-511"
        )
        actual_crossing_leading = state_bytes(crossing_leading_id)
        if actual_crossing_leading != crossing_leading:
            raise PowercutError("self-test unaligned leading tear is incorrect")
        if (
            actual_crossing_leading[509] != source_bytes[509]
            or actual_crossing_leading[511] != source_bytes[511]
            or actual_crossing_leading[3:6] != source_bytes[3:6]
        ):
            raise PowercutError("self-test tear changed bytes outside its syscall fragment")

        crossing_trailing = expected_state(source_bytes, ((511, b"V"),))
        if (
            state_bytes(
                "b000001-e000001-w000002-sector-000000000000-trailing-001"
            )
            != crossing_trailing
        ):
            raise PowercutError("self-test unaligned trailing tear is incorrect")

        noncrossing = expected_state(source_bytes, ((3, b"abc"),))
        if (
            state_bytes(
                "b000001-e000001-w000001-sector-000000000000-leading-256"
            )
            != noncrossing
        ):
            raise PowercutError("self-test unaligned noncrossing write is incorrect")

        epoch_sector = expected_state(
            source_bytes, ((3, b"abc"), (510, b"UV"))
        )
        if (
            state_bytes(
                "b000001-e000001-epoch-sector-000000000000-isolated"
            )
            != epoch_sector
        ):
            raise PowercutError("self-test physical epoch-sector overlay is incorrect")

        sector_one_only = expected_state(source_bytes, ((512, b"WXYZ"),))
        if (
            state_bytes(
                "b000001-e000001-w000002-write-isolated-sector-000000000001"
            )
            != sector_one_only
        ):
            raise PowercutError("self-test isolated multi-sector write is incorrect")

        short_state = expected_state(
            source_bytes, ((3, b"abc"), (510, b"UVWXYZ"), (1020, b"12"))
        )
        if (
            state_bytes(
                "b000001-e000001-event-w000003-prefix-000000000002"
            )
            != short_state
        ):
            raise PowercutError("self-test short-write prefix is incorrect")
        retry_state = expected_state(short_state, ((1022, b"34"),))
        retry_id = "b000001-e000001-event-w000004-prefix-000000000002"
        zero_id = "b000001-e000001-event-w000005-prefix-000000000000"
        failure_id = "b000001-e000001-event-w000006-prefix-000000000000"
        if state_bytes(retry_id) != retry_state:
            raise PowercutError("self-test short-write retry is incorrect")
        if not (
            by_id[retry_id]["physical_sha256"]
            == by_id[zero_id]["physical_sha256"]
            == by_id[failure_id]["physical_sha256"]
        ):
            raise PowercutError("zero/failure attempts invented durable bytes")

        persistence = manifest.get("persistence_model")
        if not isinstance(persistence, dict) or (
            persistence.get("large_append_reduction_applied") is not False
            or persistence.get("role_metadata_required_before_reduction") is not True
        ):
            raise PowercutError("self-test persistence-model manifest is incomplete")

        if file_sha256(source) != original_hash:
            raise PowercutError("self-test materializer changed its source")

        def reject(name: str, event_value: str, payload_value: bytes) -> None:
            tampered_events = root / f"tampered-{name}.tsv"
            tampered_payload = root / f"tampered-{name}.bin"
            tampered_events.write_text(event_value, encoding="utf-8")
            tampered_payload.write_bytes(payload_value)
            try:
                parse_inventory(tampered_events, tampered_payload, len(source_bytes))
            except PowercutError:
                return
            raise PowercutError(f"self-test accepted {name} tampering")

        reject(
            "sequence",
            text.replace("W\t2\t2\t1", "W\t99\t2\t1", 1),
            payload_bytes,
        )
        reject("payload", text, payload_bytes[:-1])
        reject(
            "durability-flags",
            text.replace("\t1037\t512\t0\t700\t700", "\t1037\t512\t2\t700\t700", 1),
            payload_bytes,
        )
        reject(
            "writer",
            text.replace(
                "S\t10\t2\t2\tfsync\t0\t0\t8\t700\t700",
                "S\t10\t2\t2\tfsync\t0\t0\t8\t701\t700",
                1,
            ),
            payload_bytes,
        )
        reject(
            "failed-without-errno",
            text.replace("\t2\t-1\t5\t13\t0\t0", "\t2\t-1\t0\t13\t0\t0", 1),
            payload_bytes,
        )

        same_size_payload = root / "tampered-same-size.bin"
        changed_payload = bytearray(payload_bytes)
        changed_payload[0] ^= 0x5A
        same_size_payload.write_bytes(changed_payload)
        tampered_validation = argparse.Namespace(
            source=str(source),
            events=str(events),
            payload=str(same_size_payload),
            inventory_final=str(inventory_final),
            report=None,
        )
        try:
            validate_command(tampered_validation)
        except PowercutError:
            pass
        else:
            raise PowercutError(
                "self-test accepted same-size payload tampering against final replay"
            )

        crash_text = text.replace(
            "S\t10\t2\t2\tfsync\t0\t0\t8\t700\t700",
            "C\t10\t2\t2\tfsync\t8\t700\t700",
            1,
        )
        crash_events = root / "crash-events.tsv"
        crash_events.write_text(crash_text, encoding="utf-8")
        crash_inventory = parse_inventory(
            crash_events, payload, len(source_bytes)
        )
        if crash_inventory.barriers[-1].record != "C":
            raise PowercutError("self-test did not retain terminal crash marker")

        return {
            "result": "PASS",
            "schema": SCHEMA,
            "logical_cases": len(logical),
            "physical_states": manifest["physical_state_count"],
            "two_epochs": True,
            "overlap": True,
            "unaligned_crossing": True,
            "unaligned_noncrossing": True,
            "short_retry": True,
            "zero_and_failure_attempts": True,
            "physical_sector_subsets": True,
            "old_bytes_preserved": True,
            "terminal_crash": True,
            "tamper_rejection": True,
            "source_immutable": True,
        }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Validate RootHealth durability events and synthesize crash images."
    )
    result.add_argument(
        "--self-test", action="store_true", help="run bounded internal schema/materializer tests"
    )
    commands = result.add_subparsers(dest="command")

    validate = commands.add_parser("validate", help="validate capture without creating states")
    validate.add_argument("events")
    validate.add_argument("payload")
    validate.add_argument("source")
    validate.add_argument("--inventory-final")
    validate.add_argument("--report")

    materialize = commands.add_parser(
        "materialize", help="validate capture and create deduplicated state images"
    )
    materialize.add_argument("events")
    materialize.add_argument("payload")
    materialize.add_argument("source")
    materialize.add_argument("output_dir")
    materialize.add_argument("--manifest", required=True)
    materialize.add_argument("--inventory-final")
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        if arguments.self_test:
            if arguments.command:
                raise PowercutError("--self-test cannot be combined with a command")
            value = self_test()
        elif arguments.command == "validate":
            value = validate_command(arguments)
        elif arguments.command == "materialize":
            value = materialize_command(arguments)
        else:
            raise PowercutError("select validate, materialize, or --self-test")
    except PowercutError as error:
        print(f"powercut materializer: {error}", file=sys.stderr)
        return 1
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
