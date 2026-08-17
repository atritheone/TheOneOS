#!/usr/bin/env python3
"""Validate the stable format-3 roothealth repair report contract."""

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
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import uuid


class ReportError(RuntimeError):
    pass


HASH = re.compile(r"^[0-9a-f]{64}$")
UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
SERIAL = re.compile(r"^0x[0-9a-f]{16}$")
LOCATOR_BOOL_FIELDS = (
    "fast_path_trusted",
    "fallback_attempted",
    "fallback_ambiguous",
)
LOCATOR_COUNT_FIELDS = (
    "unreadable_record_count",
    "definite_duplicate_count",
)
LOCATOR_FIELDS = LOCATOR_BOOL_FIELDS + LOCATOR_COUNT_FIELDS
REPAIR_ACTIONS = {
    1: "boot-primary",
    2: "boot-backup",
    3: "mft-primary",
    4: "mft-mirror",
    5: "logfile-redo",
    6: "logfile-restart",
    7: "mft-record",
    8: "attribute-list",
    9: "runlist-mapping-pairs",
    10: "attribute-data",
    11: "index-root",
    12: "index-allocation",
    13: "index-bitmap",
    14: "cluster-data",
    15: "recovery-namespace",
    16: "reparse-index",
    17: "secure-sds",
    18: "secure-sdh",
    19: "secure-sii",
    20: "upcase-data",
    21: "attrdef-data",
    22: "bitmap-mft",
    23: "bitmap-cluster",
    24: "volume-dirty-set",
    25: "volume-dirty-clear",
}
REPAIR_KINDS = tuple(REPAIR_ACTIONS.values())
REPORT_SIZE_LIMIT = 4 * 1024 * 1024
REPAIR_SAMPLE_LIMIT = 128
REPAIR_SAMPLE_EDGE_COUNT = 32
REPAIR_LEDGER_FORMAT = "RHREPL3"
REPAIR_LEDGER_MAGIC = b"RHREPL3\0"
BATCH_SAMPLE_LIMIT = 64
BATCH_SAMPLE_EDGE_COUNT = 16
BATCH_LEDGER_FORMAT = "RHTXN3"
BATCH_LEDGER_MAGIC = b"RHTXN3\0\0"
WAL_ACTION_SAMPLE_LIMIT = 128
WAL_ACTION_SAMPLE_EDGE_COUNT = 32
WAL_LEDGER_FORMAT = "RHWAL3"
WAL_LEDGER_MAGIC = b"RHWAL3\0\0"
ISSUE_SAMPLE_LIMIT = 128
ISSUE_SAMPLE_EDGE_COUNT = 32
ISSUE_LEDGER_FORMAT = "RHISS3"
ISSUE_LEDGER_MAGIC = b"RHISS3\0\0"
REPORT_BUDGET_MAGIC = b"RHSIZE3\0"
REPORT_RESERVATION_METHOD = "POSIX_FALLOCATE"
MAX_ACTION_TARGET_BYTES = 256
MAX_ISSUE_CODE_BYTES = 128
MAX_ISSUE_PASS_BYTES = 128
MAX_ISSUE_PATH_BYTES = 512
MAX_ISSUE_MESSAGE_BYTES = 1024
MAX_ISSUE_PREDICATES = 8
MAX_ISSUE_PREDICATE_BYTES = 64
MAX_ISSUE_ACTION_ORDINALS = 16
MAX_RESCAN_SAMPLE_JSON_BYTES = 8 * 1024
FIXED_REPORT_ENVELOPE_BYTES = 128 * 1024
MAX_JSON_ESCAPE_EXPANSION = 6
MAX_DEVICE_PATH_BYTES = 4096
MAX_MAPPER_NAME_BYTES = 255
MAX_VERSION_TEXT_BYTES = 64
MAX_IDENTITY_TEXT_BYTES = 512
MAX_SERIAL_TEXT_BYTES = 18
MAX_COVERAGE_CHECK_ID_BYTES = 255
DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)$")
WAL_STATES = (
    "EMPTY",
    "PREPARING",
    "APPLYING",
    "COMMITTED",
    "ROLLBACK",
)
WAL_ACTION_KINDS = (
    "undo-payload-append",
    "descriptor-append",
    "state-transition",
    "superblock-reconstruct",
    "rollback-restore",
)
WAL_ACTION_KIND_CODES = {
    name: index + 1 for index, name in enumerate(WAL_ACTION_KINDS)
}
WAL_STATE_CODES = {
    None: 0,
    "EMPTY": 1,
    "PREPARING": 2,
    "APPLYING": 3,
    "COMMITTED": 4,
    "ROLLBACK": 5,
}
BATCH_PHASE_CODES = {
    "FOUNDATION": 1,
    "METADATA_REPAIR": 2,
    "DIRTY_CLEAR": 3,
}
BATCH_ORIGIN_CODES = {
    "FOUNDATION": 1,
    "NEW": 2,
    "RECOVERED_COMMITTED": 3,
    "RECOVERED_ROLLED_BACK": 4,
}
BATCH_RESULT_CODES = {
    "accepted": 1,
    "refused": 2,
    "rolled-back": 3,
}
ISSUE_SEVERITY_CODES = {
    "INFO": 1,
    "WARNING": 2,
    "CORRUPTION": 3,
    "IO": 4,
    "UNSAFE": 5,
}
ISSUE_POLICY_CODES = {
    "ALLOW": 1,
    "CONDITIONAL": 2,
    "DENY": 3,
}
NATIVE_LOG_STATES = (
    "CLEAN_RESTART",
    "REPLAY_PLANNED",
    "EMPTY_T1OS",
    "UNSAFE",
    "IO_ERROR",
)
NATIVE_LOG_FIELDS = {
    "checked",
    "state",
    "logfile_bytes",
    "pages_expected",
    "pages_examined",
    "wiped_pages_scanned",
    "version_major",
    "version_minor",
    "restart_lsn",
    "synced_lsn",
    "committed_lsn",
    "latest_lsn",
    "checkpoint_records_examined",
    "control_records_examined",
    "mutation_records_examined",
    "open_attribute_tables",
    "attribute_name_tables",
    "dirty_page_tables",
    "transaction_tables",
    "actions_seen",
    "redo_actions",
    "undo_actions",
    "restart_pages_planned",
    "unsupported_actions",
    "io_errors",
    "parse_errors",
    "planned_io_operations",
    "planned_io_bytes",
}
NATIVE_LOG_U32_FIELDS = (
    "pages_examined",
    "wiped_pages_scanned",
    "checkpoint_records_examined",
    "control_records_examined",
    "mutation_records_examined",
    "open_attribute_tables",
    "attribute_name_tables",
    "dirty_page_tables",
    "transaction_tables",
    "actions_seen",
    "redo_actions",
    "undo_actions",
    "restart_pages_planned",
    "unsupported_actions",
    "io_errors",
    "parse_errors",
)
NATIVE_LOG_NULLABLE_U64_FIELDS = (
    "logfile_bytes",
    "restart_lsn",
    "synced_lsn",
    "committed_lsn",
    "latest_lsn",
)
COVERAGE_MAGIC = b"RHCOV3\0\0"
COVERAGE_VERSION = 3
COVERAGE_U64_MAX = (1 << 64) - 1
COVERAGE_CHECK_ID = re.compile(r"^[a-z0-9_.-]+$")
COVERAGE_CHECK_RESULTS = {
    "PASS": 1,
    "FAIL": 2,
    "UNREADABLE": 3,
    "SKIPPED": 4,
}
REQUIRED_FIXED_SYSTEM_CHECK_IDS = (
    "extend.objid",
    "extend.quota",
    "extend.reparse",
    "extend.roothealth",
    "extend.usnjrnl",
    "system.attrdef",
    "system.badclus",
    "system.bitmap",
    "system.boot",
    "system.extend",
    "system.logfile",
    "system.mft",
    "system.mftmirr",
    "system.root",
    "system.secure",
    "system.upcase",
    "system.volume",
)
COVERAGE_COUNTER_GROUPS = (
    (
        "mft_slots",
        ("expected", "completed", "live", "free", "unreadable", "invalid"),
    ),
    (
        "attributes",
        (
            "expected", "completed", "resident", "nonresident", "user_defined",
            "extents_expected", "extents_completed", "runs_expected", "runs_completed",
            "unreadable", "skipped",
        ),
    ),
    (
        "namespace_links",
        ("expected", "completed", "reciprocal", "unresolved", "unreadable"),
    ),
    (
        "indexes",
        (
            "expected", "completed", "blocks_allocated", "blocks_reachable",
            "blocks_examined", "blocks_unreadable", "bitmap_bits_expected",
            "bitmap_bits_examined",
        ),
    ),
    (
        "bitmaps",
        (
            "mft_bits_expected", "mft_bits_examined", "cluster_bits_expected",
            "cluster_bits_examined", "differences",
        ),
    ),
    (
        "security",
        (
            "ids_expected", "ids_examined", "descriptors_expected",
            "descriptors_examined", "sds_entries_expected", "sds_entries_examined",
            "sdh_entries_expected", "sdh_entries_examined", "sii_entries_expected",
            "sii_entries_examined", "unreadable",
        ),
    ),
    (
        "reparse",
        (
            "attributes_expected", "attributes_examined", "index_entries_expected",
            "index_entries_examined", "unresolved", "unreadable",
        ),
    ),
    ("compressed", ("units_expected", "units_examined", "unreadable")),
    ("fixed_system", ("expected", "completed", "failed")),
)
EXECUTION_FIELDS = {
    "role",
    "exec_id",
    "pid",
    "parent_pid",
    "binary_sha256",
    "transport",
    "pipe_payload_bytes",
    "transport_exit_status",
    "timeout_ms",
    "timed_out",
    "device_fd_inherited",
    "report_fd_inherited",
}
TOP_LEVEL_FIELDS = {
    "format",
    "checker",
    "checker_version",
    "mode",
    "result",
    "exit_code",
    "device",
    "identity",
    "initial",
    "native_log",
    "foundation_repairs",
    "plan",
    "commit",
    "batch_ledger",
    "batch_samples",
    "repairs",
    "wal",
    "issue_ledger",
    "issues",
    "report_budget",
    "final",
    "dirty_cleared",
}
DEVICE_FIELDS = {
    "requested_path",
    "resolved_path",
    "requested_was_symlink",
    "resolved_type",
    "requested_dev",
    "requested_ino",
    "resolved_dev",
    "resolved_ino",
    "resolved_major",
    "resolved_minor",
    "mapper_name",
    "selection_proven",
}
IDENTITY_FIELDS = {
    "prewrite_checked",
    "prewrite_valid",
    "expected_serial",
    "observed_primary_serial",
    "observed_backup_serial",
    "expected_label",
    "observed_label",
    "anchor",
}
SNAPSHOT_FIELDS = {
    "completed",
    "scan_id",
    "execution",
    "fresh_process",
    "read_only",
    "exit_code",
    "result",
    "dirty",
    "logfile_clean",
    "native_log_state",
    "identity_valid",
    "coverage",
}
RESCAN_FIELDS = SNAPSHOT_FIELDS | {
    "ordinal",
    "stage",
    "binding",
    "transaction_uuid",
    "plan_hash",
}
PLAN_FIELDS = {
    "operations",
    "bytes",
    "priority_operations",
    "foundation_operations",
    "foundation_bytes",
    "wal_operations",
    "wal_bytes",
    "by_action_id",
    "by_kind",
    "bytes_by_action_id",
    "bytes_by_kind",
}
COMMIT_FIELDS = {
    "started",
    "completed",
    "last_verified_ordinal",
    "syncs",
    "write_boundaries",
}
WAL_FIELDS = {
    "checked",
    "present",
    "valid",
    "state",
    "generation",
    "recovery_required",
    "recovered",
    "journal_uuid",
    "volume_serial",
    "transaction_kind",
    "max_entry_count",
    *LOCATOR_FIELDS,
    "write_boundaries",
    "action_ledger",
    "actions",
}
ACTION_FIELDS = {
    "ordinal",
    "action_id",
    "kind",
    "target",
    "offset",
    "length",
    "before_hash",
    "after_hash",
    "verified",
    "write_boundaries",
}
REPAIR_SAMPLE_FIELDS = ACTION_FIELDS | {"sample_reasons"}
FOUNDATION_ACTION_FIELDS = ACTION_FIELDS | {
    "sync_ordinal",
    "sync_completed",
    "readback_verified",
    "authority",
}
FOUNDATION_AUTHORITY_FIELDS = {
    "source_peer",
    "target_peer",
    "source_strict_valid",
    "source_expected_bound",
    "target_status",
    "sole_valid_peer",
    "conflicting_valid_peer",
}
BATCH_RECORD_FIELDS = {
    "ordinal",
    "phase",
    "origin",
    "transaction_uuid",
    "plan_hash",
    "repair_ledger_hash",
    "entry_count",
    "target_bytes",
    "by_action_id",
    "by_kind",
    "bytes_by_action_id",
    "bytes_by_kind",
    "commit_started",
    "commit_completed",
    "rollback_completed",
    "rollback_readback_verified",
    "rollback_restored_entries",
    "rollback_restored_bytes",
    "rollback_syncs",
    "rollback_write_boundaries",
    "last_verified_ordinal",
    "syncs",
    "write_boundaries",
    "result",
    "rescan_digest",
    "post_coverage_ledger_hash",
    "post_diagnosis_hash",
}
BATCH_SAMPLE_FIELDS = BATCH_RECORD_FIELDS | {"sample_reasons", "rescan"}
WAL_ACTION_FIELDS = {
    "ordinal",
    "kind",
    "extent_offset",
    "length",
    "slot",
    "transaction_ordinal",
    "transaction_uuid",
    "from_state",
    "to_state",
    "before_hash",
    "after_hash",
    "sync_ordinal",
    "sync_completed",
    "readback_verified",
    "write_boundaries",
}
WAL_ACTION_SAMPLE_FIELDS = WAL_ACTION_FIELDS | {"sample_reasons"}
ISSUE_FIELDS = {
    "ordinal",
    "code",
    "pass",
    "message",
    "severity",
    "resolved",
    "record",
    "offset",
    "path",
    "policy",
    "required_predicates",
    "failed_predicates",
    "action_ordinals",
}
ISSUE_SAMPLE_FIELDS = ISSUE_FIELDS | {"sample_reasons"}
MAX_RESCAN_PIPE_PAYLOAD = 4 * 1024 * 1024
MAX_RESCAN_TIMEOUT_MS = 300_000


def require_exact_fields(
    value: dict[str, object], expected: set[str], field: str
) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        unknown = sorted(set(value) - expected)
        raise ReportError(
            f"{field} field set differs from format-3 "
            f"(missing={missing!r}, unknown={unknown!r})"
        )


def require_release_checker(value: object, field: str = "checker") -> None:
    if value != "roothealth":
        raise ReportError(f"{field} must be the packaged roothealth binary")


def require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ReportError(f"{field} must be boolean")
    return value


def require_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ReportError(f"{field} must be a non-negative integer")
    return value


def require_positive_int(value: object, field: str) -> int:
    result = require_int(value, field)
    if result == 0:
        raise ReportError(f"{field} must be positive")
    return result


def require_u32(value: object, field: str) -> int:
    result = require_int(value, field)
    if result > (1 << 32) - 1:
        raise ReportError(f"{field} exceeds uint32")
    return result


def require_u64(value: object, field: str) -> int:
    result = require_int(value, field)
    if result > (1 << 64) - 1:
        raise ReportError(f"{field} exceeds uint64")
    return result


def nullable_bool(value: object, field: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise ReportError(f"{field} must be boolean or null")
    return value


def nullable_int(value: object, field: str) -> int | None:
    if value is not None:
        return require_int(value, field)
    return None


def nullable_u16(value: object, field: str) -> int | None:
    if value is None:
        return None
    result = require_int(value, field)
    if result > (1 << 16) - 1:
        raise ReportError(f"{field} exceeds uint16")
    return result


def nullable_u32(value: object, field: str) -> int | None:
    if value is None:
        return None
    return require_u32(value, field)


def nullable_u64(value: object, field: str) -> int | None:
    if value is None:
        return None
    return require_u64(value, field)


def require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ReportError(f"{field} is not lowercase SHA-256")
    return value


def require_uuid(value: object, field: str) -> str:
    if not isinstance(value, str) or not UUID.fullmatch(value):
        raise ReportError(f"{field} is not a canonical lowercase UUID")
    return value


def require_bounded_utf8(
    value: object, field: str, maximum: int, *, allow_empty: bool = False
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ReportError(f"{field} must be bounded UTF-8 text")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ReportError(f"{field} is not valid UTF-8") from error
    if len(encoded) > maximum:
        raise ReportError(f"{field} exceeds {maximum} UTF-8 bytes")
    return value


def canonical_text(
    value: object,
    field: str,
    maximum: int,
    *,
    nullable: bool = False,
    allow_empty: bool = False,
) -> bytes:
    if value is None:
        if not nullable:
            raise ReportError(f"{field} must not be null")
        return struct.pack("<H", 0xFFFF)
    text_value = require_bounded_utf8(
        value, field, maximum, allow_empty=allow_empty
    )
    encoded = text_value.encode("utf-8")
    if len(encoded) >= 0xFFFF:
        raise ReportError(f"{field} cannot use the null string sentinel")
    return struct.pack("<H", len(encoded)) + encoded


def canonical_hash_or_zero(value: object, field: str, *, nullable: bool) -> bytes:
    if value is None:
        if not nullable:
            raise ReportError(f"{field} must not be null")
        return bytes(32)
    return bytes.fromhex(require_sha256(value, field))


def canonical_nullable_u64(value: object, field: str) -> bytes:
    if value is None:
        return struct.pack("<Q", (1 << 64) - 1)
    number = require_u64(value, field)
    if number == (1 << 64) - 1:
        raise ReportError(f"{field} collides with the null uint64 sentinel")
    return struct.pack("<Q", number)


def validate_sample_reasons(
    value: object, field: str, allowed: tuple[str, ...] = ("ERROR", "FIRST", "LAST")
) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or value != sorted(set(value))
        or any(reason not in allowed for reason in value)
    ):
        raise ReportError(f"{field} is invalid")
    return value


def action_maps_from_record(
    record: dict[str, object], field: str, entry_count: int, target_bytes: int
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
    count_ids = record.get("by_action_id")
    count_kinds = record.get("by_kind")
    byte_ids = record.get("bytes_by_action_id")
    byte_kinds = record.get("bytes_by_kind")
    mappings = (count_ids, count_kinds, byte_ids, byte_kinds)
    if not all(isinstance(mapping, dict) for mapping in mappings):
        raise ReportError(f"{field} action count/byte maps must be objects")
    assert isinstance(count_ids, dict) and isinstance(count_kinds, dict)
    assert isinstance(byte_ids, dict) and isinstance(byte_kinds, dict)
    valid_ids = {str(action_id) for action_id in REPAIR_ACTIONS}
    for name, mapping in (
        ("by_action_id", count_ids),
        ("bytes_by_action_id", byte_ids),
    ):
        if any(
            key not in valid_ids
            or not isinstance(number, int)
            or isinstance(number, bool)
            or number <= 0
            or number > (1 << 64) - 1
            for key, number in mapping.items()
        ):
            raise ReportError(f"{field}.{name} is invalid")
    for name, mapping in (("by_kind", count_kinds), ("bytes_by_kind", byte_kinds)):
        if any(
            key not in REPAIR_KINDS
            or not isinstance(number, int)
            or isinstance(number, bool)
            or number <= 0
            or number > (1 << 64) - 1
            for key, number in mapping.items()
        ):
            raise ReportError(f"{field}.{name} is invalid")
    if set(count_ids) != set(byte_ids) or set(count_kinds) != set(byte_kinds):
        raise ReportError(f"{field} action count/byte key sets differ")
    if sum(count_ids.values()) != entry_count or sum(count_kinds.values()) != entry_count:
        raise ReportError(f"{field} action counts differ from entry_count")
    if sum(byte_ids.values()) != target_bytes or sum(byte_kinds.values()) != target_bytes:
        raise ReportError(f"{field} action bytes differ from target_bytes")
    expected_count_kinds = {
        REPAIR_ACTIONS[int(action_id)]: number
        for action_id, number in count_ids.items()
    }
    expected_byte_kinds = {
        REPAIR_ACTIONS[int(action_id)]: number
        for action_id, number in byte_ids.items()
    }
    if count_kinds != expected_count_kinds or byte_kinds != expected_byte_kinds:
        raise ReportError(f"{field} action ID/name maps differ")
    return count_ids, count_kinds, byte_ids, byte_kinds


def canonical_action_maps(
    count_ids: dict[str, int], byte_ids: dict[str, int]
) -> bytes:
    payload = bytearray()
    for action_id in REPAIR_ACTIONS:
        payload.extend(struct.pack("<Q", count_ids.get(str(action_id), 0)))
    for action_id in REPAIR_ACTIONS:
        payload.extend(struct.pack("<Q", byte_ids.get(str(action_id), 0)))
    return bytes(payload)


def canonical_snapshot_digest(value: object, field: str) -> str:
    if not isinstance(value, dict):
        raise ReportError(f"{field} must be an object")
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(b"RHSCAN3\0")
    digest.update(struct.pack("<I", 3))
    digest.update(struct.pack("<Q", len(encoded)))
    digest.update(encoded)
    return digest.hexdigest()


def canonical_diagnosis_hash(value: object, field: str) -> str:
    if not isinstance(value, dict):
        raise ReportError(f"{field} must be an object")
    diagnosis = {
        name: value.get(name)
        for name in (
            "completed",
            "exit_code",
            "result",
            "dirty",
            "logfile_clean",
            "native_log_state",
            "identity_valid",
        )
    }
    encoded = json.dumps(
        diagnosis,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(b"RHDIAG3\0")
    digest.update(struct.pack("<I", 3))
    digest.update(struct.pack("<Q", len(encoded)))
    digest.update(encoded)
    return digest.hexdigest()


def canonical_batch_record(record: object, field: str) -> bytes:
    if not isinstance(record, dict):
        raise ReportError(f"{field} must be an object")
    if set(record) not in (
        BATCH_RECORD_FIELDS,
        BATCH_RECORD_FIELDS | {"rescan"},
        BATCH_SAMPLE_FIELDS,
    ):
        raise ReportError(f"{field} contains unknown batch-record fields")
    ordinal = require_u64(record.get("ordinal"), f"{field}.ordinal")
    phase = record.get("phase")
    origin = record.get("origin")
    result = record.get("result")
    if phase not in BATCH_PHASE_CODES:
        raise ReportError(f"{field}.phase is invalid")
    if origin not in BATCH_ORIGIN_CODES:
        raise ReportError(f"{field}.origin is invalid")
    if result not in BATCH_RESULT_CODES:
        raise ReportError(f"{field}.result is invalid")
    if phase == "FOUNDATION":
        if origin != "FOUNDATION" or record.get("transaction_uuid") is not None:
            raise ReportError(f"{field} foundation identity differs")
        uuid_bytes = bytes(16)
    else:
        if origin == "FOUNDATION":
            raise ReportError(f"{field} transaction has foundation origin")
        uuid_bytes = uuid.UUID(
            require_uuid(record.get("transaction_uuid"), f"{field}.transaction_uuid")
        ).bytes
    commit_started = require_bool(record.get("commit_started"), f"{field}.commit_started")
    commit_completed = require_bool(
        record.get("commit_completed"), f"{field}.commit_completed"
    )
    rollback_completed = require_bool(
        record.get("rollback_completed"), f"{field}.rollback_completed"
    )
    rollback_readback_verified = require_bool(
        record.get("rollback_readback_verified"),
        f"{field}.rollback_readback_verified",
    )
    entry_count = require_u64(record.get("entry_count"), f"{field}.entry_count")
    target_bytes = require_u64(record.get("target_bytes"), f"{field}.target_bytes")
    if (entry_count == 0) != (target_bytes == 0):
        raise ReportError(f"{field} has inconsistent zero-operation totals")
    if entry_count == 0 and not (
        origin == "RECOVERED_ROLLED_BACK" and result == "rolled-back"
    ):
        raise ReportError(f"{field} is an unauthorized zero-operation phase")
    last_verified = require_u64(
        record.get("last_verified_ordinal"), f"{field}.last_verified_ordinal"
    )
    syncs = require_u64(record.get("syncs"), f"{field}.syncs")
    boundaries = require_u64(
        record.get("write_boundaries"), f"{field}.write_boundaries"
    )
    rollback_restored = require_u64(
        record.get("rollback_restored_entries"),
        f"{field}.rollback_restored_entries",
    )
    rollback_bytes = require_u64(
        record.get("rollback_restored_bytes"),
        f"{field}.rollback_restored_bytes",
    )
    rollback_syncs = require_u64(
        record.get("rollback_syncs"), f"{field}.rollback_syncs"
    )
    rollback_boundaries = require_u64(
        record.get("rollback_write_boundaries"),
        f"{field}.rollback_write_boundaries",
    )
    count_ids, _, byte_ids, _ = action_maps_from_record(
        record, field, entry_count, target_bytes
    )
    rescan_digest = record.get("rescan_digest")
    coverage_hash = record.get("post_coverage_ledger_hash")
    diagnosis_hash = record.get("post_diagnosis_hash")
    rescan_present = rescan_digest is not None
    if rescan_present:
        require_sha256(rescan_digest, f"{field}.rescan_digest")
        require_sha256(coverage_hash, f"{field}.post_coverage_ledger_hash")
        require_sha256(diagnosis_hash, f"{field}.post_diagnosis_hash")
    elif coverage_hash is not None or diagnosis_hash is not None:
        raise ReportError(f"{field} has post-batch hashes without a rescan")
    if result == "refused":
        if (
            origin != "NEW"
            or commit_started
            or commit_completed
            or rollback_completed
            or rollback_readback_verified
            or rollback_restored
            or rollback_bytes
            or rollback_syncs
            or rollback_boundaries
            or last_verified
            or syncs
            or boundaries
        ):
            raise ReportError(f"{field} refused phase has commit evidence")
        if rescan_present:
            raise ReportError(f"{field} refused phase fabricated a rescan")
    elif result == "accepted":
        if (
            origin == "RECOVERED_ROLLED_BACK"
            or not commit_started
            or not commit_completed
            or rollback_completed
            or rollback_readback_verified
            or rollback_restored
            or rollback_bytes
            or rollback_syncs
            or rollback_boundaries
            or not rescan_present
        ):
            raise ReportError(f"{field} completed phase lacks commit/rescan evidence")
        if last_verified != entry_count or syncs == 0 or boundaries == 0:
            raise ReportError(f"{field} completed phase evidence is incomplete")
    else:
        if (
            origin != "RECOVERED_ROLLED_BACK"
            or commit_completed
            or not rollback_completed
            or not rollback_readback_verified
            or not rescan_present
            or last_verified > entry_count
            or rollback_restored != last_verified
            or rollback_restored > entry_count
            or rollback_bytes > target_bytes
            or syncs
            or boundaries
        ):
            raise ReportError(f"{field} recovered rollback evidence is incomplete")
        if commit_started is not (last_verified > 0):
            raise ReportError(
                f"{field} PREPARING/APPLYING rollback prefix evidence differs"
            )
        if rollback_restored == 0:
            if rollback_bytes or rollback_syncs or rollback_boundaries:
                raise ReportError(f"{field} zero-prefix rollback has raw restores")
        elif rollback_bytes == 0 or rollback_syncs == 0 or rollback_boundaries == 0:
            raise ReportError(f"{field} applied-prefix rollback lacks raw evidence")
    flags = (
        (1 if commit_started else 0)
        | (2 if commit_completed else 0)
        | (4 if rescan_present else 0)
        | (8 if rollback_completed else 0)
        | (16 if rollback_readback_verified else 0)
    )
    payload = bytearray()
    payload.extend(
        struct.pack(
            "<QBBBBI",
            ordinal,
            BATCH_PHASE_CODES[phase],
            BATCH_ORIGIN_CODES[origin],
            BATCH_RESULT_CODES[result],
            flags,
            0,
        )
    )
    payload.extend(uuid_bytes)
    payload.extend(bytes.fromhex(require_sha256(record.get("plan_hash"), f"{field}.plan_hash")))
    payload.extend(
        bytes.fromhex(
            require_sha256(
                record.get("repair_ledger_hash"), f"{field}.repair_ledger_hash"
            )
        )
    )
    payload.extend(
        struct.pack(
            "<QQQQQQQQQ",
            entry_count,
            target_bytes,
            last_verified,
            syncs,
            boundaries,
            rollback_restored,
            rollback_bytes,
            rollback_syncs,
            rollback_boundaries,
        )
    )
    payload.extend(canonical_action_maps(count_ids, byte_ids))
    payload.extend(canonical_hash_or_zero(rescan_digest, f"{field}.rescan_digest", nullable=True))
    payload.extend(
        canonical_hash_or_zero(
            coverage_hash, f"{field}.post_coverage_ledger_hash", nullable=True
        )
    )
    payload.extend(
        canonical_hash_or_zero(
            diagnosis_hash, f"{field}.post_diagnosis_hash", nullable=True
        )
    )
    return bytes(payload)


def batch_ledger_hash(records: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    digest.update(BATCH_LEDGER_MAGIC)
    digest.update(struct.pack("<I", 3))
    digest.update(struct.pack("<Q", len(records)))
    for index, record in enumerate(records):
        if record.get("ordinal") != index:
            raise ReportError("RHTXN3 record ordinals are not contiguous")
        digest.update(canonical_batch_record(record, f"batch_records[{index}]"))
    return digest.hexdigest()


def validate_batch_ledger(
    report: dict[str, object],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    ledger = report.get("batch_ledger")
    if not isinstance(ledger, dict):
        raise ReportError("batch_ledger must be an object")
    exact_fields = {
        "format",
        "record_count",
        "ledger_hash",
        "foundation_count",
        "new_count",
        "recovered_committed_count",
        "recovered_rolled_back_count",
        "metadata_count",
        "dirty_clear_count",
        "accepted_count",
        "refused_count",
        "rolled_back_count",
        "priority_count",
        "rescan_count",
        "commit_started_count",
        "commit_completed_count",
        "verified_entries",
        "rollback_restored_entries",
        "rollback_restored_bytes",
        "rollback_syncs",
        "rollback_write_boundaries",
        "entry_count",
        "target_bytes",
        "syncs",
        "write_boundaries",
        "by_action_id",
        "by_kind",
        "bytes_by_action_id",
        "bytes_by_kind",
        "dirty_set_action_count",
        "dirty_set_phase_ordinal",
        "dirty_clear_action_count",
        "dirty_clear_phase_ordinal",
        "native_redo_count",
        "native_restart_count",
        "native_phase_ordinal",
        "first_metadata_ordinal",
        "first_phase",
        "last_phase",
        "final_rescan_digest",
        "final_coverage_ledger_hash",
        "final_diagnosis_hash",
    }
    if set(ledger) != exact_fields:
        raise ReportError("batch_ledger field set differs from RHTXN3")
    if ledger.get("format") != BATCH_LEDGER_FORMAT:
        raise ReportError("batch_ledger format differs")
    record_count = require_u64(ledger.get("record_count"), "batch_ledger.record_count")
    require_sha256(ledger.get("ledger_hash"), "batch_ledger.ledger_hash")
    aggregate_names = (
        "foundation_count",
        "new_count",
        "recovered_committed_count",
        "recovered_rolled_back_count",
        "metadata_count",
        "dirty_clear_count",
        "accepted_count",
        "refused_count",
        "rolled_back_count",
        "priority_count",
        "rescan_count",
        "commit_started_count",
        "commit_completed_count",
        "verified_entries",
        "rollback_restored_entries",
        "rollback_restored_bytes",
        "rollback_syncs",
        "rollback_write_boundaries",
        "entry_count",
        "target_bytes",
        "syncs",
        "write_boundaries",
        "dirty_set_action_count",
        "dirty_clear_action_count",
        "native_redo_count",
        "native_restart_count",
    )
    aggregates = {
        name: require_u64(ledger.get(name), f"batch_ledger.{name}")
        for name in aggregate_names
    }
    if aggregates["foundation_count"] not in (0, 1):
        raise ReportError("RHTXN3 has more than one foundation phase")
    if (
        aggregates["foundation_count"]
        + aggregates["new_count"]
        + aggregates["recovered_committed_count"]
        + aggregates["recovered_rolled_back_count"]
        != record_count
    ):
        raise ReportError("RHTXN3 origin counts differ from record_count")
    if aggregates["metadata_count"] + aggregates["dirty_clear_count"] + aggregates[
        "foundation_count"
    ] != record_count:
        raise ReportError("RHTXN3 phase counts differ from record_count")
    if (
        aggregates["accepted_count"]
        + aggregates["refused_count"]
        + aggregates["rolled_back_count"]
        != record_count
    ):
        raise ReportError("RHTXN3 result counts differ from record_count")
    if aggregates["rescan_count"] != record_count - aggregates["refused_count"]:
        raise ReportError("RHTXN3 committed-phase/rescan count differs")
    if aggregates["recovered_rolled_back_count"] != aggregates["rolled_back_count"]:
        raise ReportError("RHTXN3 recovered-rollback origin/result counts differ")
    if (
        aggregates["rollback_restored_entries"] > aggregates["verified_entries"]
        or aggregates["rollback_restored_bytes"] > aggregates["target_bytes"]
        or (
            aggregates["rollback_restored_entries"] == 0
            and (
                aggregates["rollback_restored_bytes"]
                or aggregates["rollback_syncs"]
                or aggregates["rollback_write_boundaries"]
            )
        )
    ):
        raise ReportError("RHTXN3 rollback aggregates are invalid")
    if (
        aggregates["commit_completed_count"] > aggregates["commit_started_count"]
        or aggregates["commit_started_count"] > record_count
        or aggregates["verified_entries"] > aggregates["entry_count"]
    ):
        raise ReportError("RHTXN3 commit aggregates are invalid")
    if (
        aggregates["commit_started_count"] < aggregates["accepted_count"]
        or aggregates["commit_started_count"]
        > aggregates["accepted_count"] + aggregates["rolled_back_count"]
        or aggregates["commit_completed_count"] != aggregates["accepted_count"]
    ):
        raise ReportError("RHTXN3 commit/result aggregates differ")
    if aggregates["refused_count"] and (
        aggregates["commit_started_count"]
        > record_count - aggregates["refused_count"]
    ):
        raise ReportError("RHTXN3 refused phase entered commit")
    if (
        aggregates["priority_count"]
        < aggregates["refused_count"] + aggregates["rolled_back_count"]
        or aggregates["priority_count"] > record_count
    ):
        raise ReportError("RHTXN3 priority count differs from phase results")
    if aggregates["dirty_set_action_count"] > 2 * aggregates["metadata_count"]:
        raise ReportError("RHTXN3 dirty-set actions exceed its physical phases")
    if aggregates["dirty_clear_action_count"] > 2 * aggregates["dirty_clear_count"]:
        raise ReportError("RHTXN3 dirty-clear actions exceed its physical phases")
    for name in (
        "dirty_set_phase_ordinal",
        "dirty_clear_phase_ordinal",
        "native_phase_ordinal",
        "first_metadata_ordinal",
    ):
        value = ledger.get(name)
        if value is not None:
            ordinal = require_u64(value, f"batch_ledger.{name}")
            if ordinal >= record_count:
                raise ReportError(f"batch_ledger.{name} is outside the ledger")
    first_metadata = ledger.get("first_metadata_ordinal")
    if aggregates["metadata_count"] == 0:
        if first_metadata is not None:
            raise ReportError("RHTXN3 fabricates a first metadata ordinal")
    elif first_metadata is None:
        raise ReportError("RHTXN3 omits its first metadata ordinal")
    if aggregates["dirty_set_action_count"]:
        dirty_set_ordinal = ledger.get("dirty_set_phase_ordinal")
        if (
            not isinstance(dirty_set_ordinal, int)
            or dirty_set_ordinal < int(first_metadata)
        ):
            raise ReportError("dirty-set is outside the metadata phase sequence")
    elif ledger.get("dirty_set_phase_ordinal") is not None:
        raise ReportError("RHTXN3 fabricates a dirty-set phase")
    if aggregates["native_redo_count"] or aggregates["native_restart_count"]:
        if (
            aggregates["native_redo_count"] == 0
            or aggregates["native_restart_count"] < 2
            or aggregates["native_restart_count"] > 2 * aggregates["metadata_count"]
            or not isinstance(ledger.get("native_phase_ordinal"), int)
            or int(ledger["native_phase_ordinal"]) < int(first_metadata)
        ):
            raise ReportError("native replay aggregate is outside its metadata phases")
    elif ledger.get("native_phase_ordinal") is not None:
        raise ReportError("RHTXN3 fabricates a native replay phase")
    if aggregates["dirty_clear_count"]:
        if (
            aggregates["dirty_clear_action_count"] < 2
            or ledger.get("dirty_clear_phase_ordinal") != record_count - 1
        ):
            raise ReportError("DIRTY_CLEAR is not the paired final phase")
    elif (
        aggregates["dirty_clear_action_count"]
        or ledger.get("dirty_clear_phase_ordinal") is not None
    ):
        raise ReportError("RHTXN3 fabricates dirty-clear action evidence")
    entry_count = aggregates["entry_count"]
    target_bytes = aggregates["target_bytes"]
    count_ids, _, byte_ids, _ = action_maps_from_record(
        ledger, "batch_ledger", entry_count, target_bytes
    )
    if count_ids.get("24", 0) != aggregates["dirty_set_action_count"]:
        raise ReportError("RHTXN3 dirty-set aggregate differs from action map")
    if count_ids.get("25", 0) != aggregates["dirty_clear_action_count"]:
        raise ReportError("RHTXN3 dirty-clear aggregate differs from action map")
    if count_ids.get("5", 0) != aggregates["native_redo_count"]:
        raise ReportError("RHTXN3 native-redo aggregate differs from action map")
    if count_ids.get("6", 0) != aggregates["native_restart_count"]:
        raise ReportError("RHTXN3 native-restart aggregate differs from action map")
    first_phase = ledger.get("first_phase")
    last_phase = ledger.get("last_phase")
    if record_count == 0:
        if (
            entry_count
            or target_bytes
            or aggregates["syncs"]
            or aggregates["write_boundaries"]
            or count_ids
            or byte_ids
            or first_phase is not None
            or last_phase is not None
            or ledger.get("final_rescan_digest") is not None
            or ledger.get("final_coverage_ledger_hash") is not None
            or ledger.get("final_diagnosis_hash") is not None
        ):
            raise ReportError("empty RHTXN3 ledger has nonempty aggregates")
    else:
        if first_phase not in BATCH_PHASE_CODES or last_phase not in BATCH_PHASE_CODES:
            raise ReportError("nonempty RHTXN3 ledger lacks endpoint phases")
        if aggregates["foundation_count"] and first_phase != "FOUNDATION":
            raise ReportError("foundation is not the first RHTXN3 phase")
        if aggregates["dirty_clear_count"] and last_phase != "DIRTY_CLEAR":
            raise ReportError("dirty-clear is not the last RHTXN3 phase")
        for name in (
            "final_rescan_digest",
            "final_coverage_ledger_hash",
            "final_diagnosis_hash",
        ):
            value = ledger.get(name)
            if aggregates["rescan_count"]:
                require_sha256(value, f"batch_ledger.{name}")
            elif value is not None:
                raise ReportError(f"batch_ledger.{name} exists without a rescan")
    samples_raw = report.get("batch_samples")
    if not isinstance(samples_raw, list) or len(samples_raw) > BATCH_SAMPLE_LIMIT:
        raise ReportError("batch_samples must be a bounded sample array")
    samples: list[dict[str, object]] = []
    previous = -1
    for index, sample in enumerate(samples_raw):
        if not isinstance(sample, dict):
            raise ReportError(f"batch_samples[{index}] must be an object")
        require_exact_fields(
            sample, BATCH_SAMPLE_FIELDS, f"batch_samples[{index}]"
        )
        ordinal = require_u64(sample.get("ordinal"), f"batch_samples[{index}].ordinal")
        if ordinal <= previous or ordinal >= record_count:
            raise ReportError("batch sample ordinal is invalid")
        reasons = validate_sample_reasons(
            sample.get("sample_reasons"),
            f"batch_samples[{index}].sample_reasons",
        )
        canonical_batch_record(sample, f"batch_samples[{index}]")
        rescan = sample.get("rescan")
        if sample.get("rescan_digest") is None:
            if rescan is not None:
                raise ReportError("uncommitted batch sample fabricated rescan evidence")
        else:
            encoded_rescan = json.dumps(
                rescan,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            if len(encoded_rescan) > MAX_RESCAN_SAMPLE_JSON_BYTES:
                raise ReportError("batch rescan sample exceeds its fixed report slot")
            if canonical_snapshot_digest(
                rescan, f"batch_samples[{index}].rescan"
            ) != sample.get("rescan_digest"):
                raise ReportError("batch rescan digest differs from its sample")
        is_error = (
            sample.get("result") != "accepted"
            or (
                isinstance(rescan, dict)
                and rescan.get("result") in ("io-error", "wrong-root", "internal-error")
            )
            or (
                isinstance(rescan, dict)
                and isinstance(rescan.get("execution"), dict)
                and (
                    rescan["execution"].get("timed_out") is True
                    or rescan["execution"].get("transport_exit_status") not in (0, None)
                )
            )
        )
        if ("ERROR" in reasons) != is_error:
            raise ReportError("batch ERROR sample reason differs from its semantics")
        samples.append(sample)
        previous = ordinal
    required_first = set(range(min(BATCH_SAMPLE_EDGE_COUNT, record_count)))
    required_last = set(
        range(max(0, record_count - BATCH_SAMPLE_EDGE_COUNT), record_count)
    )
    observed = {int(sample["ordinal"]) for sample in samples}
    if not required_first.issubset(observed) or not required_last.issubset(observed):
        raise ReportError("batch_samples omits mandatory RHTXN3 edge samples")
    for sample in samples:
        ordinal = int(sample["ordinal"])
        reasons = sample["sample_reasons"]
        assert isinstance(reasons, list)
        if (ordinal in required_first) != ("FIRST" in reasons):
            raise ReportError("batch FIRST reason differs")
        if (ordinal in required_last) != ("LAST" in reasons):
            raise ReportError("batch LAST reason differs")
        if ordinal not in required_first | required_last and "ERROR" not in reasons:
            raise ReportError("non-edge batch sample lacks ERROR reason")
    if record_count == len(samples):
        ordered = sorted(samples, key=lambda sample: int(sample["ordinal"]))
        if batch_ledger_hash(ordered) != ledger.get("ledger_hash"):
            raise ReportError("complete RHTXN3 samples differ from ledger hash")
        phases = Counter(str(sample["phase"]) for sample in ordered)
        origins = Counter(str(sample["origin"]) for sample in ordered)
        results = Counter(str(sample["result"]) for sample in ordered)
        if (
            phases.get("FOUNDATION", 0) != aggregates["foundation_count"]
            or phases.get("METADATA_REPAIR", 0) != aggregates["metadata_count"]
            or phases.get("DIRTY_CLEAR", 0) != aggregates["dirty_clear_count"]
            or origins.get("NEW", 0) != aggregates["new_count"]
            or origins.get("RECOVERED_COMMITTED", 0)
            != aggregates["recovered_committed_count"]
            or origins.get("RECOVERED_ROLLED_BACK", 0)
            != aggregates["recovered_rolled_back_count"]
            or results.get("accepted", 0) != aggregates["accepted_count"]
            or results.get("refused", 0) != aggregates["refused_count"]
            or results.get("rolled-back", 0) != aggregates["rolled_back_count"]
        ):
            raise ReportError("complete RHTXN3 samples differ from phase aggregates")
        sample_priority_count = sum(
            "ERROR" in sample["sample_reasons"] for sample in ordered
        )
        if sample_priority_count != aggregates["priority_count"]:
            raise ReportError("complete RHTXN3 samples differ from priority count")
        for index, sample in enumerate(ordered):
            if sample["phase"] == "DIRTY_CLEAR":
                ids = sample["by_action_id"]
                assert isinstance(ids, dict)
                count = int(ids.get("25", 0))
                if set(ids) - {"25"} or count > 2:
                    raise ReportError(
                        f"batch_samples[{index}] DIRTY_CLEAR action set differs"
                    )
                if sample["result"] == "accepted" and count != 2:
                    raise ReportError(
                        f"batch_samples[{index}] accepted DIRTY_CLEAR is not paired"
                    )
        seen_new = False
        for sample in ordered:
            if sample["origin"] == "NEW":
                seen_new = True
            elif sample["origin"] in (
                "RECOVERED_COMMITTED",
                "RECOVERED_ROLLED_BACK",
            ) and seen_new:
                raise ReportError("recovered work follows NEW work")

        native_samples: list[tuple[int, dict[str, object]]] = []
        for index, sample in enumerate(ordered):
            ids = sample["by_action_id"]
            assert isinstance(ids, dict)
            redo_count = int(ids.get("5", 0))
            restart_count = int(ids.get("6", 0))
            if not redo_count and not restart_count:
                continue
            if (
                sample.get("phase") != "METADATA_REPAIR"
                or redo_count == 0
                or restart_count > 2
                or (sample.get("result") != "rolled-back" and restart_count != 2)
            ):
                raise ReportError("RHTXN3 native phase cardinality differs")
            native_samples.append((index, sample))
        if native_samples:
            if ledger.get("native_phase_ordinal") != native_samples[0][0]:
                raise ReportError("RHTXN3 native phase ordinal differs")
            completed_native = [
                (index, sample)
                for index, sample in native_samples
                if sample.get("result") != "rolled-back"
            ]
            if len(completed_native) > 1:
                raise ReportError("RHTXN3 contains multiple completed native phases")
            if completed_native:
                completed_index, completed = completed_native[0]
                if (completed_index, completed) != native_samples[-1]:
                    raise ReportError("RHTXN3 native rollback follows completed replay")
                completed_ids = completed["by_action_id"]
                completed_bytes = completed["bytes_by_action_id"]
                assert isinstance(completed_ids, dict)
                assert isinstance(completed_bytes, dict)
                for prefix_index, prefix in native_samples[:-1]:
                    prefix_ids = prefix["by_action_id"]
                    prefix_bytes = prefix["bytes_by_action_id"]
                    assert isinstance(prefix_ids, dict)
                    assert isinstance(prefix_bytes, dict)
                    if (
                        prefix.get("origin") != "RECOVERED_ROLLED_BACK"
                        or prefix.get("result") != "rolled-back"
                        or prefix.get("plan_hash") != completed.get("plan_hash")
                        or any(
                            int(prefix_ids.get(action_id, 0))
                            > int(completed_ids.get(action_id, 0))
                            for action_id in ("5", "6")
                        )
                        or any(
                            int(prefix_bytes.get(action_id, 0))
                            > int(completed_bytes.get(action_id, 0))
                            for action_id in ("5", "6")
                        )
                    ):
                        raise ReportError(
                            f"batch_samples[{prefix_index}] is not an authenticated native prefix"
                        )
        elif ledger.get("native_phase_ordinal") is not None:
            raise ReportError("RHTXN3 native ordinal lacks a native action")
        if sum(int(sample["entry_count"]) for sample in ordered) != entry_count:
            raise ReportError("complete RHTXN3 samples differ from entry total")
        if sum(int(sample["target_bytes"]) for sample in ordered) != target_bytes:
            raise ReportError("complete RHTXN3 samples differ from byte total")
        if sum(int(sample["syncs"]) for sample in ordered) != aggregates["syncs"]:
            raise ReportError("complete RHTXN3 samples differ from sync total")
        if (
            sum(int(sample["write_boundaries"]) for sample in ordered)
            != aggregates["write_boundaries"]
        ):
            raise ReportError("complete RHTXN3 samples differ from boundary total")
        if (
            sum(sample["commit_started"] is True for sample in ordered)
            != aggregates["commit_started_count"]
            or sum(sample["commit_completed"] is True for sample in ordered)
            != aggregates["commit_completed_count"]
            or sum(int(sample["last_verified_ordinal"]) for sample in ordered)
            != aggregates["verified_entries"]
            or sum(int(sample["rollback_restored_entries"]) for sample in ordered)
            != aggregates["rollback_restored_entries"]
            or sum(int(sample["rollback_restored_bytes"]) for sample in ordered)
            != aggregates["rollback_restored_bytes"]
            or sum(int(sample["rollback_syncs"]) for sample in ordered)
            != aggregates["rollback_syncs"]
            or sum(int(sample["rollback_write_boundaries"]) for sample in ordered)
            != aggregates["rollback_write_boundaries"]
        ):
            raise ReportError("complete RHTXN3 samples differ from commit aggregates")
        complete_counts: Counter[str] = Counter()
        complete_bytes: Counter[str] = Counter()
        for sample in ordered:
            complete_counts.update(sample["by_action_id"])
            complete_bytes.update(sample["bytes_by_action_id"])
        if dict(complete_counts) != count_ids or dict(complete_bytes) != byte_ids:
            raise ReportError("complete RHTXN3 samples differ from action maps")
    return ledger, samples


def canonical_wal_action(action: object, field: str) -> bytes:
    if not isinstance(action, dict):
        raise ReportError(f"{field} must be an object")
    if set(action) not in (WAL_ACTION_FIELDS, WAL_ACTION_SAMPLE_FIELDS):
        raise ReportError(f"{field} contains unknown WAL-action fields")
    ordinal = require_u64(action.get("ordinal"), f"{field}.ordinal")
    kind = action.get("kind")
    if kind not in WAL_ACTION_KIND_CODES:
        raise ReportError(f"{field}.kind is invalid")
    extent_offset = require_u64(action.get("extent_offset"), f"{field}.extent_offset")
    length = require_u64(action.get("length"), f"{field}.length")
    if length == 0:
        raise ReportError(f"{field}.length must be nonzero")
    slot = action.get("slot")
    if kind in ("superblock-reconstruct", "state-transition"):
        if slot not in (0, 1):
            raise ReportError(f"{field}.slot is invalid for a superblock write")
        slot_code = int(slot) + 1
    else:
        if slot is not None:
            raise ReportError(f"{field}.slot must be null")
        slot_code = 0
    transaction_ordinal = action.get("transaction_ordinal")
    transaction_uuid = action.get("transaction_uuid")
    if transaction_ordinal is not None:
        require_u64(transaction_ordinal, f"{field}.transaction_ordinal")
        uuid_bytes = uuid.UUID(
            require_uuid(transaction_uuid, f"{field}.transaction_uuid")
        ).bytes
    else:
        if transaction_uuid is not None:
            raise ReportError(f"{field} has a UUID without a transaction ordinal")
        uuid_bytes = bytes(16)
    if kind in (
        "undo-payload-append",
        "descriptor-append",
        "rollback-restore",
    ) and transaction_ordinal is None:
        raise ReportError(f"{field} transaction-bound WAL action lacks an ordinal")
    if kind == "superblock-reconstruct" and transaction_ordinal is not None:
        raise ReportError(f"{field} superblock reconstruction claims a transaction")
    from_state = action.get("from_state")
    to_state = action.get("to_state")
    if kind == "state-transition":
        if from_state not in WAL_STATE_CODES or to_state not in WAL_STATE_CODES:
            raise ReportError(f"{field} lacks canonical transition states")
        if from_state is None or to_state is None or from_state == to_state:
            raise ReportError(f"{field} has an invalid state transition")
    elif from_state is not None or to_state is not None:
        raise ReportError(f"{field} fabricated transition states")
    before_hash = require_sha256(action.get("before_hash"), f"{field}.before_hash")
    after_hash = require_sha256(action.get("after_hash"), f"{field}.after_hash")
    # A new transaction may reuse WAL slots whose stale payload/descriptor
    # already equals the new bytes.  The physical write, sync and readback
    # remain mandatory.  State/reconstruction/restore actions must change.
    if before_hash == after_hash and kind not in (
        "undo-payload-append",
        "descriptor-append",
    ):
        raise ReportError(f"{field} records a no-op WAL write")
    sync_ordinal = require_u64(action.get("sync_ordinal"), f"{field}.sync_ordinal")
    if sync_ordinal == 0:
        raise ReportError(f"{field}.sync_ordinal must be positive")
    if (
        action.get("sync_completed") is not True
        or action.get("readback_verified") is not True
    ):
        raise ReportError(f"{field} lacks sync/readback proof")
    boundaries = require_u64(action.get("write_boundaries"), f"{field}.write_boundaries")
    if boundaries == 0:
        raise ReportError(f"{field} has no physical write boundary")
    payload = bytearray()
    payload.extend(
        struct.pack(
            "<QBBBBI",
            ordinal,
            WAL_ACTION_KIND_CODES[kind],
            WAL_STATE_CODES[from_state],
            WAL_STATE_CODES[to_state],
            slot_code,
            3,
        )
    )
    payload.extend(canonical_nullable_u64(transaction_ordinal, f"{field}.transaction_ordinal"))
    payload.extend(uuid_bytes)
    payload.extend(
        struct.pack(
            "<QQQQ",
            extent_offset,
            length,
            sync_ordinal,
            boundaries,
        )
    )
    payload.extend(bytes.fromhex(before_hash))
    payload.extend(bytes.fromhex(after_hash))
    return bytes(payload)


def wal_ledger_hash(actions: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    digest.update(WAL_LEDGER_MAGIC)
    digest.update(struct.pack("<I", 3))
    digest.update(struct.pack("<Q", len(actions)))
    for index, action in enumerate(actions):
        if action.get("ordinal") != index:
            raise ReportError("RHWAL3 action ordinals are not contiguous")
        digest.update(canonical_wal_action(action, f"wal_records[{index}]"))
    return digest.hexdigest()


def validate_wal_action_ledger(wal: dict[str, object]) -> list[dict[str, object]]:
    ledger = wal.get("action_ledger")
    if not isinstance(ledger, dict):
        raise ReportError("wal.action_ledger must be an object")
    exact_fields = {
        "format",
        "entry_count",
        "ledger_hash",
        "total_bytes",
        "syncs",
        "write_boundaries",
        "by_kind",
        "bytes_by_kind",
        "syncs_by_kind",
        "boundaries_by_kind",
        "first_kind",
        "last_kind",
        "error_count",
    }
    if set(ledger) != exact_fields:
        raise ReportError("wal.action_ledger field set differs from RHWAL3")
    if ledger.get("format") != WAL_LEDGER_FORMAT:
        raise ReportError("wal.action_ledger format differs")
    entry_count = require_u64(ledger.get("entry_count"), "wal.action_ledger.entry_count")
    require_sha256(ledger.get("ledger_hash"), "wal.action_ledger.ledger_hash")
    total_bytes = require_u64(ledger.get("total_bytes"), "wal.action_ledger.total_bytes")
    syncs = require_u64(ledger.get("syncs"), "wal.action_ledger.syncs")
    boundaries = require_u64(
        ledger.get("write_boundaries"), "wal.action_ledger.write_boundaries"
    )
    error_count = require_u64(ledger.get("error_count"), "wal.action_ledger.error_count")
    by_kind = ledger.get("by_kind")
    bytes_by_kind = ledger.get("bytes_by_kind")
    syncs_by_kind = ledger.get("syncs_by_kind")
    boundaries_by_kind = ledger.get("boundaries_by_kind")
    if not all(
        isinstance(mapping, dict)
        for mapping in (
            by_kind,
            bytes_by_kind,
            syncs_by_kind,
            boundaries_by_kind,
        )
    ):
        raise ReportError("wal.action_ledger kind maps must be objects")
    assert isinstance(by_kind, dict) and isinstance(bytes_by_kind, dict)
    assert isinstance(syncs_by_kind, dict) and isinstance(boundaries_by_kind, dict)
    if not (
        set(by_kind)
        == set(bytes_by_kind)
        == set(syncs_by_kind)
        == set(boundaries_by_kind)
    ):
        raise ReportError("wal.action_ledger kind-map keys differ")
    for name, mapping in (
        ("by_kind", by_kind),
        ("bytes_by_kind", bytes_by_kind),
        ("syncs_by_kind", syncs_by_kind),
        ("boundaries_by_kind", boundaries_by_kind),
    ):
        if any(
            kind not in WAL_ACTION_KIND_CODES
            or not isinstance(number, int)
            or isinstance(number, bool)
            or number <= 0
            or number > (1 << 64) - 1
            for kind, number in mapping.items()
        ):
            raise ReportError(f"wal.action_ledger.{name} is invalid")
    if (
        sum(by_kind.values()) != entry_count
        or sum(bytes_by_kind.values()) != total_bytes
        or sum(syncs_by_kind.values()) != syncs
        or sum(boundaries_by_kind.values()) != boundaries
    ):
        raise ReportError("wal.action_ledger kind aggregates differ")
    first_kind = ledger.get("first_kind")
    last_kind = ledger.get("last_kind")
    if entry_count == 0:
        if (
            by_kind
            or bytes_by_kind
            or syncs_by_kind
            or boundaries_by_kind
            or total_bytes
            or syncs
            or boundaries
            or error_count
            or first_kind is not None
            or last_kind is not None
        ):
            raise ReportError("empty RHWAL3 ledger has nonzero aggregates")
    elif first_kind not in WAL_ACTION_KIND_CODES or last_kind not in WAL_ACTION_KIND_CODES:
        raise ReportError("nonempty RHWAL3 ledger lacks endpoint kinds")
    actions = wal.get("actions")
    if not isinstance(actions, list) or len(actions) > WAL_ACTION_SAMPLE_LIMIT:
        raise ReportError("wal.actions is not a bounded sample array")
    samples: list[dict[str, object]] = []
    previous = -1
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ReportError(f"wal.actions[{index}] must be an object")
        require_exact_fields(
            action, WAL_ACTION_SAMPLE_FIELDS, f"wal.actions[{index}]"
        )
        ordinal = require_u64(action.get("ordinal"), f"wal.actions[{index}].ordinal")
        if ordinal <= previous or ordinal >= entry_count:
            raise ReportError("wal action sample ordinal is invalid")
        validate_sample_reasons(
            action.get("sample_reasons"), f"wal.actions[{index}].sample_reasons"
        )
        canonical_wal_action(action, f"wal.actions[{index}]")
        samples.append(action)
        previous = ordinal
    required_first = set(range(min(WAL_ACTION_SAMPLE_EDGE_COUNT, entry_count)))
    required_last = set(
        range(max(0, entry_count - WAL_ACTION_SAMPLE_EDGE_COUNT), entry_count)
    )
    observed = {int(action["ordinal"]) for action in samples}
    if not required_first.issubset(observed) or not required_last.issubset(observed):
        raise ReportError("wal.actions omits mandatory RHWAL3 edge samples")
    observed_error = 0
    for action in samples:
        ordinal = int(action["ordinal"])
        reasons = action["sample_reasons"]
        assert isinstance(reasons, list)
        if (ordinal in required_first) != ("FIRST" in reasons):
            raise ReportError("wal action FIRST reason differs")
        if (ordinal in required_last) != ("LAST" in reasons):
            raise ReportError("wal action LAST reason differs")
        if "ERROR" in reasons:
            observed_error += 1
        elif ordinal not in required_first | required_last:
            raise ReportError("non-edge wal action sample lacks ERROR reason")
    if observed_error > error_count:
        raise ReportError("sampled WAL errors exceed the RHWAL3 error aggregate")
    if entry_count == len(samples):
        ordered = sorted(samples, key=lambda action: int(action["ordinal"]))
        if wal_ledger_hash(ordered) != ledger.get("ledger_hash"):
            raise ReportError("complete RHWAL3 samples differ from ledger hash")
        if sum(int(action["length"]) for action in ordered) != total_bytes:
            raise ReportError("complete RHWAL3 samples differ from byte total")
        if sum(int(action["write_boundaries"]) for action in ordered) != boundaries:
            raise ReportError("complete RHWAL3 samples differ from boundary total")
        if len(ordered) != syncs:
            raise ReportError("complete RHWAL3 samples differ from sync total")
        counts = Counter(str(action["kind"]) for action in ordered)
        byte_counts: Counter[str] = Counter()
        sync_counts: Counter[str] = Counter()
        boundary_counts: Counter[str] = Counter()
        for action in ordered:
            byte_counts[str(action["kind"])] += int(action["length"])
            sync_counts[str(action["kind"])] += 1
            boundary_counts[str(action["kind"])] += int(action["write_boundaries"])
        if (
            dict(counts) != by_kind
            or dict(byte_counts) != bytes_by_kind
            or dict(sync_counts) != syncs_by_kind
            or dict(boundary_counts) != boundaries_by_kind
        ):
            raise ReportError("complete RHWAL3 samples differ from kind maps")
    if wal.get("write_boundaries") != boundaries:
        raise ReportError("wal.write_boundaries differs from RHWAL3")
    return samples


def validate_wal_batch_reconciliation(
    wal: dict[str, object],
    batch_ledger: dict[str, object],
    batch_samples: list[dict[str, object]],
) -> None:
    action_ledger = wal.get("action_ledger")
    assert isinstance(action_ledger, dict)
    counts = action_ledger.get("by_kind")
    bytes_by_kind = action_ledger.get("bytes_by_kind")
    syncs_by_kind = action_ledger.get("syncs_by_kind")
    boundaries_by_kind = action_ledger.get("boundaries_by_kind")
    assert isinstance(counts, dict) and isinstance(bytes_by_kind, dict)
    assert isinstance(syncs_by_kind, dict) and isinstance(boundaries_by_kind, dict)
    if (
        counts.get("rollback-restore", 0)
        != batch_ledger.get("rollback_restored_entries")
        or bytes_by_kind.get("rollback-restore", 0)
        != batch_ledger.get("rollback_restored_bytes")
        or syncs_by_kind.get("rollback-restore", 0)
        != batch_ledger.get("rollback_syncs")
        or boundaries_by_kind.get("rollback-restore", 0)
        != batch_ledger.get("rollback_write_boundaries")
    ):
        raise ReportError("RHWAL3 rollback totals differ from RHTXN3")
    sampled_batches = {
        int(sample["ordinal"]): sample for sample in batch_samples
    }
    actions = wal.get("actions")
    assert isinstance(actions, list)
    for index, action in enumerate(actions):
        if action.get("kind") != "rollback-restore":
            continue
        ordinal = action.get("transaction_ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool):
            raise ReportError(f"wal.actions[{index}] rollback is unbound")
        batch = sampled_batches.get(ordinal)
        if (
            batch is None
            or batch.get("origin") != "RECOVERED_ROLLED_BACK"
            or batch.get("result") != "rolled-back"
            or action.get("transaction_uuid") != batch.get("transaction_uuid")
        ):
            raise ReportError(
                f"wal.actions[{index}] rollback batch UUID/ordinal differs"
            )


def wal_object(report: dict[str, object]) -> dict[str, object]:
    wal = report.get("wal")
    if not isinstance(wal, dict):
        raise ReportError("wal must be an object")
    require_exact_fields(wal, WAL_FIELDS, "wal")
    require_bool(wal.get("checked"), "wal.checked")
    require_bool(wal.get("recovered"), "wal.recovered")
    for field in ("present", "valid", "recovery_required"):
        nullable_bool(wal.get(field), f"wal.{field}")
    if wal.get("state") is not None and wal.get("state") not in WAL_STATES:
        raise ReportError("wal.state is absent or unknown")
    if wal.get("transaction_kind") not in (
        None,
        "NONE",
        "METADATA_REPAIR",
        "DIRTY_CLEAR",
    ):
        raise ReportError("wal.transaction_kind is absent or unknown")
    nullable_u64(wal.get("generation"), "wal.generation")
    nullable_u32(wal.get("max_entry_count"), "wal.max_entry_count")
    for field in LOCATOR_BOOL_FIELDS:
        nullable_bool(wal.get(field), f"wal.{field}")
    for field in LOCATOR_COUNT_FIELDS:
        nullable_u64(wal.get(field), f"wal.{field}")
    require_u64(wal.get("write_boundaries"), "wal.write_boundaries")
    validate_wal_action_ledger(wal)
    journal_uuid = wal.get("journal_uuid")
    volume_serial = wal.get("volume_serial")
    if journal_uuid is not None and (
        not isinstance(journal_uuid, str) or not UUID.fullmatch(journal_uuid)
    ):
        raise ReportError("wal.journal_uuid is not canonical lowercase UUID text")
    if volume_serial is not None and (
        not isinstance(volume_serial, str) or not SERIAL.fullmatch(volume_serial)
    ):
        raise ReportError("wal.volume_serial is not a fixed lowercase hexadecimal serial")
    return wal


def require_trusted_locator(wal: dict[str, object]) -> None:
    if wal.get("fast_path_trusted") is not True:
        raise ReportError("WAL locator did not trust the attested RECORD:SEQUENCE fast path")
    if wal.get("fallback_attempted") is not False or wal.get("fallback_ambiguous") is not False:
        raise ReportError("attested WAL unexpectedly entered ambiguous fallback discovery")
    require_u64(wal.get("unreadable_record_count"), "wal.unreadable_record_count")
    require_u64(wal.get("definite_duplicate_count"), "wal.definite_duplicate_count")


def require_bound_wal(
    report: dict[str, object], expected_journal_uuid: str, expected_volume_serial: str
) -> dict[str, object]:
    wal = wal_object(report)
    if not expected_journal_uuid or not expected_volume_serial:
        raise ReportError("bound WAL validation requires expected UUID and serial")
    if (
        wal.get("checked") is not True
        or wal.get("present") is not True
        or wal.get("valid") is not True
    ):
        raise ReportError("the preallocated $Extend/$RootHealth WAL was not validated")
    require_trusted_locator(wal)
    if wal.get("definite_duplicate_count") != 0:
        raise ReportError("validated WAL locator found a definite duplicate")
    if wal.get("state") is None or wal.get("generation") is None:
        raise ReportError("validated WAL lacks state or generation")
    if wal.get("max_entry_count") != 4096:
        raise ReportError("validated WAL does not enforce max_entry_count 4096")
    if wal.get("state") == "EMPTY":
        if wal.get("transaction_kind") != "NONE":
            raise ReportError("EMPTY WAL has a non-NONE transaction kind")
    elif wal.get("transaction_kind") not in ("METADATA_REPAIR", "DIRTY_CLEAR"):
        raise ReportError("non-EMPTY WAL has no typed transaction kind")
    if not isinstance(wal.get("recovery_required"), bool):
        raise ReportError("validated WAL lacks recovery_required")
    journal_uuid = wal.get("journal_uuid")
    volume_serial = wal.get("volume_serial")
    if journal_uuid != expected_journal_uuid:
        raise ReportError(
            f"wal.journal_uuid differs from provisioned journal: {journal_uuid!r}"
        )
    if volume_serial != expected_volume_serial:
        raise ReportError(
            f"wal.volume_serial differs from expected target: {volume_serial!r}"
        )
    return wal


def validate_device(report: dict[str, object]) -> dict[str, object]:
    device = report.get("device")
    if not isinstance(device, dict):
        raise ReportError("device must be an object")
    require_exact_fields(device, DEVICE_FIELDS, "device")
    for field in ("requested_path", "resolved_path"):
        value = device.get(field)
        if not isinstance(value, str) or not value.startswith("/"):
            raise ReportError(f"device.{field} must be a nonempty absolute path")
        require_bounded_utf8(value, f"device.{field}", MAX_DEVICE_PATH_BYTES)
    require_bool(device.get("requested_was_symlink"), "device.requested_was_symlink")
    if device.get("resolved_type") != "block":
        raise ReportError("device.resolved_type must be 'block'")
    for field in ("requested_dev", "requested_ino", "resolved_dev", "resolved_ino"):
        value = device.get(field)
        if (
            not isinstance(value, str)
            or len(value) > 20
            or not DECIMAL.fullmatch(value)
            or int(value) > (1 << 64) - 1
        ):
            raise ReportError(f"device.{field} must be a uint64 decimal string")
    require_u32(device.get("resolved_major"), "device.resolved_major")
    require_u32(device.get("resolved_minor"), "device.resolved_minor")
    mapper_name = device.get("mapper_name")
    if mapper_name is not None:
        require_bounded_utf8(
            mapper_name, "device.mapper_name", MAX_MAPPER_NAME_BYTES
        )
    if require_bool(device.get("selection_proven"), "device.selection_proven") is not True:
        raise ReportError("device selection was not proven stable")
    return device


def validate_identity(report: dict[str, object]) -> dict[str, object]:
    identity = report.get("identity")
    if not isinstance(identity, dict):
        raise ReportError("identity must be an object")
    require_exact_fields(identity, IDENTITY_FIELDS, "identity")
    checked = require_bool(
        identity.get("prewrite_checked"), "identity.prewrite_checked"
    )
    valid = nullable_bool(identity.get("prewrite_valid"), "identity.prewrite_valid")
    for name in (
        "expected_serial",
        "observed_primary_serial",
        "observed_backup_serial",
        "expected_label",
        "observed_label",
        "anchor",
    ):
        value = identity.get(name)
        if value is not None:
            require_bounded_utf8(
                value,
                f"identity.{name}",
                MAX_SERIAL_TEXT_BYTES if "serial" in name else MAX_IDENTITY_TEXT_BYTES,
            )
    observed_fields = (
        "observed_primary_serial",
        "observed_backup_serial",
        "observed_label",
        "anchor",
    )
    if not checked:
        if valid is not None:
            raise ReportError("unchecked identity fabricated prewrite_valid")
        if any(identity.get(name) is not None for name in observed_fields):
            raise ReportError("unchecked identity fabricated observed evidence")
    else:
        if not isinstance(valid, bool):
            raise ReportError("checked identity lacks a boolean prewrite_valid")
        if valid and any(identity.get(name) is None for name in observed_fields):
            raise ReportError("valid pre-write identity lacks complete observed evidence")
    return identity


def identity_self_test() -> int:
    checked = {
        "prewrite_checked": True,
        "prewrite_valid": True,
        "expected_serial": "0x1122334455667788",
        "observed_primary_serial": "0x1122334455667788",
        "observed_backup_serial": "0x1122334455667788",
        "expected_label": "T1OS",
        "observed_label": "T1OS-test",
        "anchor": "the one",
    }
    unchecked = {
        "prewrite_checked": False,
        "prewrite_valid": None,
        "expected_serial": "0x1122334455667788",
        "observed_primary_serial": None,
        "observed_backup_serial": None,
        "expected_label": "T1OS",
        "observed_label": None,
        "anchor": None,
    }
    validate_identity({"identity": checked})
    validate_identity({"identity": unchecked})
    negatives: list[dict[str, object]] = []
    case = copy.deepcopy(unchecked)
    case["prewrite_valid"] = False
    negatives.append(case)
    case = copy.deepcopy(unchecked)
    case["observed_primary_serial"] = "0x1122334455667788"
    negatives.append(case)
    case = copy.deepcopy(checked)
    case["prewrite_valid"] = None
    negatives.append(case)
    case = copy.deepcopy(checked)
    case["observed_label"] = None
    negatives.append(case)
    negative_count = 0
    for case in negatives:
        try:
            validate_identity({"identity": case})
        except ReportError:
            negative_count += 1
        else:
            raise ReportError("identity tri-state self-test accepted invalid evidence")
    return negative_count


def coverage_count(value: object, field: str) -> int | None:
    result = nullable_int(value, field)
    if result is not None and result > COVERAGE_U64_MAX:
        raise ReportError(f"{field} exceeds unsigned 64-bit ledger encoding")
    return result


def coverage_ledger_payload(value: dict[str, object], field: str) -> bytes:
    """Return the frozen RHCOV3 canonical byte stream for a validated object."""
    payload = bytearray(COVERAGE_MAGIC)
    payload.extend(struct.pack("<I", COVERAGE_VERSION))
    payload.append(1 if value.get("complete") is True else 0)

    counters: list[int | None] = []
    for counter in ("io_errors", "skipped"):
        counters.append(coverage_count(value.get(counter), f"{field}.{counter}"))
    for group_name, counter_names in COVERAGE_COUNTER_GROUPS:
        group = value.get(group_name)
        if not isinstance(group, dict):
            raise ReportError(f"{field}.{group_name} must be an object")
        for counter in counter_names:
            counters.append(
                coverage_count(group.get(counter), f"{field}.{group_name}.{counter}")
            )
    if len(counters) != 60:
        raise ReportError("internal format-3 coverage counter table is not 60 fields")
    for counter in counters:
        if counter is None:
            payload.extend(b"\0" + b"\0" * 8)
        else:
            payload.extend(b"\1" + struct.pack("<Q", counter))

    fixed = value.get("fixed_system")
    if not isinstance(fixed, dict):
        raise ReportError(f"{field}.fixed_system must be an object")
    checks = fixed.get("checks")
    if not isinstance(checks, list):
        raise ReportError(f"{field}.fixed_system.checks must be an array")
    if len(checks) > len(REQUIRED_FIXED_SYSTEM_CHECK_IDS):
        raise ReportError(f"{field}.fixed_system.checks exceeds the frozen set")
    if len(checks) > 65535:
        raise ReportError(f"{field}.fixed_system.checks exceeds 65535 entries")

    encoded_checks: list[tuple[bytes, int]] = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            raise ReportError(f"{field}.fixed_system.checks[{index}] is malformed")
        check_id = check.get("id")
        if not isinstance(check_id, str) or not COVERAGE_CHECK_ID.fullmatch(check_id):
            raise ReportError(
                f"{field}.fixed_system.checks[{index}].id is not canonical ASCII"
            )
        encoded_id = check_id.encode("ascii")
        if not encoded_id or len(encoded_id) > MAX_COVERAGE_CHECK_ID_BYTES:
            raise ReportError(
                f"{field}.fixed_system.checks[{index}].id length is invalid"
            )
        result = COVERAGE_CHECK_RESULTS.get(check.get("result"))
        if result is None:
            raise ReportError(
                f"{field}.fixed_system.checks[{index}].result is invalid"
            )
        encoded_checks.append((encoded_id, result))
    encoded_ids = [check_id for check_id, _ in encoded_checks]
    if encoded_ids != sorted(encoded_ids) or len(set(encoded_ids)) != len(encoded_ids):
        raise ReportError(f"{field}.fixed_system check IDs are not sorted/unique")

    payload.extend(struct.pack("<I", len(encoded_checks)))
    for check_id, result in encoded_checks:
        payload.extend(struct.pack("<H", len(check_id)))
        payload.extend(check_id)
        payload.append(result)
    return bytes(payload)


def validate_coverage(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ReportError(f"{field} must be an object")
    require_bool(value.get("complete"), f"{field}.complete")
    ledger_hash = value.get("ledger_hash")
    if not isinstance(ledger_hash, str) or not HASH.fullmatch(ledger_hash):
        raise ReportError(f"{field}.ledger_hash is not SHA-256")

    for group_name, fields in COVERAGE_COUNTER_GROUPS[:-1]:
        group = value.get(group_name)
        if not isinstance(group, dict):
            raise ReportError(f"{field}.{group_name} must be an object")
        if set(group) != set(fields):
            raise ReportError(f"{field}.{group_name} fields differ from format-3")
        for counter in fields:
            coverage_count(group.get(counter), f"{field}.{group_name}.{counter}")

    fixed = value.get("fixed_system")
    if not isinstance(fixed, dict) or set(fixed) != {
        "expected", "completed", "failed", "checks"
    }:
        raise ReportError(f"{field}.fixed_system fields differ from format-3")
    for counter in ("expected", "completed", "failed"):
        coverage_count(fixed.get(counter), f"{field}.fixed_system.{counter}")
    checks = fixed.get("checks")
    if not isinstance(checks, list):
        raise ReportError(f"{field}.fixed_system.checks must be an array")
    check_ids: list[str] = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict) or set(check) != {"id", "result"}:
            raise ReportError(f"{field}.fixed_system.checks[{index}] is malformed")
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id:
            raise ReportError(f"{field}.fixed_system.checks[{index}].id is invalid")
        if check.get("result") not in COVERAGE_CHECK_RESULTS:
            raise ReportError(f"{field}.fixed_system.checks[{index}].result is invalid")
        check_ids.append(check_id)
    if check_ids != sorted(set(check_ids)):
        raise ReportError(f"{field}.fixed_system check IDs are not sorted/unique")
    for counter in ("io_errors", "skipped"):
        coverage_count(value.get(counter), f"{field}.{counter}")
    expected_top = {
        "complete", "ledger_hash",
        *(group_name for group_name, _ in COVERAGE_COUNTER_GROUPS[:-1]),
        "fixed_system", "io_errors", "skipped",
    }
    if set(value) != expected_top:
        raise ReportError(f"{field} fields differ from format-3")
    computed_hash = hashlib.sha256(coverage_ledger_payload(value, field)).hexdigest()
    if ledger_hash != computed_hash:
        raise ReportError(f"{field}.ledger_hash does not bind the canonical ledger")
    return value


def coverage_self_test() -> int:
    """Exercise the frozen ledger encoding without accepting JSON/hash drift."""
    values: list[int | None] = [
        None if index in (1, 17, 43, 59) else index * 0x01020304050607 + 7
        for index in range(60)
    ]
    position = 0
    coverage: dict[str, object] = {
        "complete": False,
        "ledger_hash": "",
        "io_errors": values[position],
        "skipped": values[position + 1],
    }
    position += 2
    for group_name, counter_names in COVERAGE_COUNTER_GROUPS:
        group: dict[str, object] = {}
        for counter_name in counter_names:
            group[counter_name] = values[position]
            position += 1
        coverage[group_name] = group
    assert position == 60
    fixed = coverage["fixed_system"]
    assert isinstance(fixed, dict)
    fixed["checks"] = [
        {"id": "attrdef.basic", "result": "PASS"},
        {"id": "mft.0", "result": "FAIL"},
        {"id": "secure-sii", "result": "UNREADABLE"},
        {"id": "upcase-nonascii", "result": "SKIPPED"},
    ]

    # Independently generated from the frozen RHCOV3 byte grammar.  This
    # prevents this validator's encoder and its tests from drifting together.
    expected_hash = "48477bed28045444d8c8b4fbe21f0cafb31172758c2520a19043e908d1b0b885"
    coverage["ledger_hash"] = expected_hash
    validate_coverage(coverage, "selftest.coverage")
    canonical = coverage_ledger_payload(coverage, "selftest.coverage")
    if hashlib.sha256(canonical).hexdigest() != expected_hash:
        raise ReportError("coverage self-test known vector changed")

    # JSON member insertion order is deliberately outside the canonical form.
    reordered_json = {
        key: copy.deepcopy(coverage[key]) for key in reversed(tuple(coverage))
    }
    mft = reordered_json["mft_slots"]
    assert isinstance(mft, dict)
    reordered_json["mft_slots"] = {
        key: mft[key] for key in reversed(tuple(mft))
    }
    validate_coverage(reordered_json, "selftest.json-order")

    negative_count = 0

    def must_reject(name: str, mutation: object) -> None:
        nonlocal negative_count
        candidate = copy.deepcopy(coverage)
        if callable(mutation):
            mutation(candidate)
        else:
            candidate["ledger_hash"] = mutation
        try:
            validate_coverage(candidate, f"selftest.{name}")
        except ReportError:
            negative_count += 1
            return
        raise ReportError(f"coverage self-test accepted {name} drift")

    def field_drift(candidate: dict[str, object]) -> None:
        group = candidate["mft_slots"]
        assert isinstance(group, dict) and isinstance(group["expected"], int)
        group["expected"] += 1

    must_reject("field", field_drift)

    wrong_order = bytearray(canonical)
    first_counter = 13
    second_counter = first_counter + 9
    wrong_order[first_counter:second_counter + 9] = (
        canonical[second_counter:second_counter + 9]
        + canonical[first_counter:first_counter + 9]
    )
    must_reject("counter-order", hashlib.sha256(wrong_order).hexdigest())

    def null_drift(candidate: dict[str, object]) -> None:
        candidate["skipped"] = 0

    must_reject("null", null_drift)
    zero_instead_of_null = copy.deepcopy(coverage)
    zero_instead_of_null["skipped"] = 0
    if coverage_ledger_payload(zero_instead_of_null, "selftest.null-tag") == canonical:
        raise ReportError("coverage self-test null tag aliases integer zero")

    wrong_endian = bytearray(canonical)
    wrong_endian[8:12] = struct.pack(">I", COVERAGE_VERSION)
    must_reject("endianness", hashlib.sha256(wrong_endian).hexdigest())

    def result_drift(candidate: dict[str, object]) -> None:
        fixed_group = candidate["fixed_system"]
        assert isinstance(fixed_group, dict)
        checks = fixed_group["checks"]
        assert isinstance(checks, list) and isinstance(checks[0], dict)
        checks[0]["result"] = "FAIL"

    must_reject("result", result_drift)

    def duplicate_drift(candidate: dict[str, object]) -> None:
        fixed_group = candidate["fixed_system"]
        assert isinstance(fixed_group, dict)
        checks = fixed_group["checks"]
        assert isinstance(checks, list)
        checks.append(copy.deepcopy(checks[-1]))

    must_reject("duplicate", duplicate_drift)

    def check_order_drift(candidate: dict[str, object]) -> None:
        fixed_group = candidate["fixed_system"]
        assert isinstance(fixed_group, dict)
        checks = fixed_group["checks"]
        assert isinstance(checks, list)
        checks[0], checks[1] = checks[1], checks[0]

    must_reject("check-order", check_order_drift)

    def unknown_result(candidate: dict[str, object]) -> None:
        fixed_group = candidate["fixed_system"]
        assert isinstance(fixed_group, dict)
        checks = fixed_group["checks"]
        assert isinstance(checks, list) and isinstance(checks[0], dict)
        checks[0]["result"] = "CLEAN"

    must_reject("unknown-result", unknown_result)

    def overflow(candidate: dict[str, object]) -> None:
        candidate["io_errors"] = 1 << 64

    must_reject("u64-overflow", overflow)

    def invalid_id(candidate: dict[str, object]) -> None:
        fixed_group = candidate["fixed_system"]
        assert isinstance(fixed_group, dict)
        checks = fixed_group["checks"]
        assert isinstance(checks, list) and isinstance(checks[0], dict)
        checks[0]["id"] = "AttrDef/basic"

    must_reject("check-id", invalid_id)

    if negative_count != 10:
        raise ReportError(
            f"coverage self-test expected 10 negative cases, found {negative_count}"
        )
    return negative_count


def validate_execution(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != EXECUTION_FIELDS:
        raise ReportError(f"{field} fields differ from format-3")
    role = value.get("role")
    transport = value.get("transport")
    exec_id = value.get("exec_id")
    try:
        parsed_exec_id = uuid.UUID(str(exec_id))
    except (AttributeError, ValueError) as error:
        raise ReportError(f"{field}.exec_id is not an RFC 4122 UUID") from error
    if (
        not isinstance(exec_id, str)
        or not UUID.fullmatch(exec_id)
        or str(parsed_exec_id) != exec_id
        or parsed_exec_id.variant != uuid.RFC_4122
    ):
        raise ReportError(f"{field}.exec_id is not a canonical UUID")
    pid = require_u32(value.get("pid"), f"{field}.pid")
    parent_pid = require_u32(value.get("parent_pid"), f"{field}.parent_pid")
    if pid == 0 or parent_pid == 0:
        raise ReportError(f"{field} PID evidence must be positive")
    binary_hash = value.get("binary_sha256")
    if not isinstance(binary_hash, str) or not HASH.fullmatch(binary_hash):
        raise ReportError(f"{field}.binary_sha256 is not SHA-256")
    payload_bytes = require_u32(
        value.get("pipe_payload_bytes"), f"{field}.pipe_payload_bytes"
    )
    timed_out = value.get("timed_out")
    if value.get("device_fd_inherited") is not False:
        raise ReportError(f"{field} inherited the target device descriptor")
    if value.get("report_fd_inherited") is not False:
        raise ReportError(f"{field} inherited the report descriptor")

    if role == "INITIAL":
        if (
            transport != "DIRECT"
            or payload_bytes != 0
            or value.get("transport_exit_status") is not None
            or value.get("timeout_ms") is not None
            or timed_out is not None
        ):
            raise ReportError(f"{field} INITIAL execution evidence differs")
    elif role == "SELF_EXEC_RESCAN":
        status = nullable_u32(
            value.get("transport_exit_status"),
            f"{field}.transport_exit_status",
        )
        timeout_ms = nullable_u32(value.get("timeout_ms"), f"{field}.timeout_ms")
        if (
            transport != "SELF_EXEC_PIPE_V1"
            or payload_bytes == 0
            or payload_bytes > MAX_RESCAN_PIPE_PAYLOAD
            or status != 0
            or isinstance(status, bool)
            or not isinstance(timeout_ms, int)
            or isinstance(timeout_ms, bool)
            or timeout_ms <= 0
            or timeout_ms > MAX_RESCAN_TIMEOUT_MS
            or timed_out is not False
        ):
            raise ReportError(f"{field} self-exec transport evidence differs")
    else:
        raise ReportError(f"{field}.role is invalid")
    return value


def validate_execution_chain(
    initial: dict[str, object],
    rescans: list[dict[str, object]],
    *,
    self_exec_rescans: bool,
) -> None:
    initial_execution = initial.get("execution")
    assert isinstance(initial_execution, dict)
    if (
        initial_execution.get("role") != "INITIAL"
        or initial_execution.get("transport") != "DIRECT"
    ):
        raise ReportError("initial snapshot is not the direct initial execution")
    initial_pid = initial_execution.get("pid")
    binary_hash = initial_execution.get("binary_sha256")
    exec_ids = [initial_execution.get("exec_id")]
    pids = [initial_pid]
    for index, rescan in enumerate(rescans):
        execution = rescan.get("execution")
        assert isinstance(execution, dict)
        if self_exec_rescans:
            if (
                execution.get("role") != "SELF_EXEC_RESCAN"
                or execution.get("transport") != "SELF_EXEC_PIPE_V1"
                or execution.get("parent_pid") != initial_pid
                or execution.get("binary_sha256") != binary_hash
            ):
                raise ReportError(
                    f"rescans[{index}] is not a child self-exec of the initial binary"
                )
            exec_ids.append(execution.get("exec_id"))
            pids.append(execution.get("pid"))
        elif execution != initial_execution:
            raise ReportError(
                "read-only check FINAL alias has a different execution identity"
            )
    if len(set(exec_ids)) != len(exec_ids):
        raise ReportError("repair diagnosis/rescans reuse an exec_id")
    if len(set(pids)) != len(pids):
        raise ReportError("repair diagnosis/rescans do not use distinct PIDs")


def execution_self_test() -> int:
    initial_execution: dict[str, object] = {
        "role": "INITIAL",
        "exec_id": "10000000-0000-4000-8000-000000000001",
        "pid": 101,
        "parent_pid": 100,
        "binary_sha256": "1" * 64,
        "transport": "DIRECT",
        "pipe_payload_bytes": 0,
        "transport_exit_status": None,
        "timeout_ms": None,
        "timed_out": None,
        "device_fd_inherited": False,
        "report_fd_inherited": False,
    }
    child_execution: dict[str, object] = {
        "role": "SELF_EXEC_RESCAN",
        "exec_id": "20000000-0000-4000-8000-000000000002",
        "pid": 102,
        "parent_pid": 101,
        "binary_sha256": "1" * 64,
        "transport": "SELF_EXEC_PIPE_V1",
        "pipe_payload_bytes": 4096,
        "transport_exit_status": 0,
        "timeout_ms": 180_000,
        "timed_out": False,
        "device_fd_inherited": False,
        "report_fd_inherited": False,
    }
    validate_execution(initial_execution, "selftest.execution.initial")
    validate_execution(child_execution, "selftest.execution.child")
    initial = {"execution": initial_execution}
    child = {"execution": child_execution}
    validate_execution_chain(initial, [child], self_exec_rescans=True)
    negative_count = 0

    def reject_field(field: str, value: object) -> None:
        nonlocal negative_count
        candidate = copy.deepcopy(child_execution)
        candidate[field] = value
        try:
            validate_execution(candidate, f"selftest.execution.{field}")
        except ReportError:
            negative_count += 1
            return
        raise ReportError(f"execution self-test accepted {field} drift")

    reject_field("pipe_payload_bytes", 0)
    reject_field("pipe_payload_bytes", MAX_RESCAN_PIPE_PAYLOAD + 1)
    reject_field("transport_exit_status", 9)
    reject_field("timeout_ms", 0)
    reject_field("timeout_ms", MAX_RESCAN_TIMEOUT_MS + 1)
    reject_field("timed_out", True)
    reject_field("device_fd_inherited", True)
    reject_field("report_fd_inherited", True)

    def reject_chain(name: str, execution: dict[str, object]) -> None:
        nonlocal negative_count
        try:
            validate_execution(execution, f"selftest.execution.{name}")
            validate_execution_chain(
                initial,
                [{"execution": execution}],
                self_exec_rescans=True,
            )
        except ReportError:
            negative_count += 1
            return
        raise ReportError(f"execution self-test accepted {name} drift")

    duplicate_pid = copy.deepcopy(child_execution)
    duplicate_pid["pid"] = initial_execution["pid"]
    reject_chain("duplicate-pid", duplicate_pid)
    duplicate_exec = copy.deepcopy(child_execution)
    duplicate_exec["exec_id"] = initial_execution["exec_id"]
    reject_chain("duplicate-exec", duplicate_exec)
    wrong_parent = copy.deepcopy(child_execution)
    wrong_parent["parent_pid"] = 999
    reject_chain("wrong-parent", wrong_parent)
    wrong_binary = copy.deepcopy(child_execution)
    wrong_binary["binary_sha256"] = "2" * 64
    reject_chain("wrong-binary", wrong_binary)

    malformed = copy.deepcopy(child_execution)
    del malformed["report_fd_inherited"]
    try:
        validate_execution(malformed, "selftest.execution.malformed")
    except ReportError:
        negative_count += 1
    else:
        raise ReportError("execution self-test accepted a truncated object")
    if negative_count != 13:
        raise ReportError(
            f"execution self-test expected 13 negative cases, found {negative_count}"
        )
    return negative_count


def require_complete_coverage(
    value: dict[str, object], field: str, *, allow_differences: bool = False,
    allow_fixed_skips: bool = False,
) -> None:
    if value.get("complete") is not (False if allow_fixed_skips else True):
        raise ReportError(f"{field} is not complete")

    def group(name: str) -> dict[str, int]:
        raw = value[name]
        assert isinstance(raw, dict)
        if any(item is None for item in raw.values()):
            raise ReportError(f"{field}.{name} fabricates an unknown complete counter")
        return {key: int(item) for key, item in raw.items()}

    mft = group("mft_slots")
    if not (
        mft["expected"] > 0
        and mft["expected"]
        == mft["completed"]
        == mft["live"] + mft["free"]
        and mft["unreadable"] == 0
        and mft["invalid"] == 0
    ):
        raise ReportError(f"{field}.mft_slots does not reconcile")
    attrs = group("attributes")
    if not (
        attrs["expected"] > 0
        and attrs["nonresident"] > 0
        and attrs["runs_expected"] > 0
        and attrs["expected"] == attrs["completed"]
        and attrs["completed"] == attrs["resident"] + attrs["nonresident"]
        and attrs["user_defined"] <= attrs["completed"]
        and attrs["extents_expected"] == attrs["extents_completed"]
        and attrs["runs_expected"] == attrs["runs_completed"]
        and attrs["unreadable"] == attrs["skipped"] == 0
    ):
        raise ReportError(f"{field}.attributes does not reconcile")
    namespace = group("namespace_links")
    if not (
        namespace["expected"] > 0
        and namespace["expected"]
        == namespace["completed"]
        == namespace["reciprocal"]
        and namespace["unresolved"] == namespace["unreadable"] == 0
    ):
        raise ReportError(f"{field}.namespace_links does not reconcile")
    indexes = group("indexes")
    if not (
        indexes["expected"] > 0
        and indexes["expected"] == indexes["completed"]
        and indexes["blocks_allocated"] == indexes["blocks_reachable"]
        == indexes["blocks_examined"]
        and indexes["blocks_unreadable"] == 0
        and indexes["bitmap_bits_expected"] == indexes["bitmap_bits_examined"]
    ):
        raise ReportError(f"{field}.indexes does not reconcile")
    bitmaps = group("bitmaps")
    if not (
        bitmaps["mft_bits_expected"] > 0
        and bitmaps["cluster_bits_expected"] > 0
        and bitmaps["mft_bits_expected"] == bitmaps["mft_bits_examined"]
        and bitmaps["cluster_bits_expected"] == bitmaps["cluster_bits_examined"]
        and (allow_differences or bitmaps["differences"] == 0)
    ):
        raise ReportError(f"{field}.bitmaps does not reconcile")
    security = group("security")
    for stem in ("ids", "descriptors", "sds_entries", "sdh_entries", "sii_entries"):
        if (
            security[f"{stem}_expected"] <= 0
            or security[f"{stem}_expected"] != security[f"{stem}_examined"]
        ):
            raise ReportError(f"{field}.security {stem} coverage differs")
    if security["unreadable"]:
        raise ReportError(f"{field}.security has unreadable coverage")
    reparse = group("reparse")
    if not (
        reparse["attributes_expected"] == reparse["attributes_examined"]
        and reparse["index_entries_expected"] == reparse["index_entries_examined"]
        and reparse["unresolved"] == reparse["unreadable"] == 0
    ):
        raise ReportError(f"{field}.reparse does not reconcile")
    compressed = group("compressed")
    if not (
        compressed["units_expected"] == compressed["units_examined"]
        and compressed["unreadable"] == 0
    ):
        raise ReportError(f"{field}.compressed does not reconcile")
    fixed = value["fixed_system"]
    assert isinstance(fixed, dict)
    expected = fixed.get("expected")
    completed = fixed.get("completed")
    failed = fixed.get("failed")
    checks = fixed.get("checks")
    check_ids = (
        [check.get("id") for check in checks]
        if isinstance(checks, list)
        else []
    )
    allowed_failed_ids = (
        {"system.bitmap"}
        if allow_differences and bitmaps["differences"] > 0
        else set()
    )
    observed_failed_ids = {
        str(check.get("id"))
        for check in checks
        if isinstance(check, dict) and check.get("result") == "FAIL"
    } if isinstance(checks, list) else set()
    observed_unreadable_ids = {
        str(check.get("id"))
        for check in checks
        if isinstance(check, dict) and check.get("result") == "UNREADABLE"
    } if isinstance(checks, list) else set()
    observed_skipped_ids = {
        str(check.get("id"))
        for check in checks
        if isinstance(check, dict) and check.get("result") == "SKIPPED"
    } if isinstance(checks, list) else set()
    expected_completed = (
        len(checks) - len(observed_skipped_ids)
        if isinstance(checks, list) and allow_fixed_skips
        else len(checks) if isinstance(checks, list) else None
    )
    if (
        expected is None
        or completed is None
        or failed is None
        or not isinstance(checks, list)
        or expected != len(checks)
        or completed != expected_completed
        or failed != len(observed_failed_ids)
        or not observed_failed_ids.issubset(allowed_failed_ids)
        or observed_unreadable_ids
        or (observed_skipped_ids and not allow_fixed_skips)
        or tuple(check_ids) != REQUIRED_FIXED_SYSTEM_CHECK_IDS
    ):
        raise ReportError(
            f"{field}.fixed_system does not reconcile: "
            f"expected={expected!r} completed={completed!r} failed={failed!r} "
            f"allowed_failed={sorted(allowed_failed_ids)!r} "
            f"observed_failed={sorted(observed_failed_ids)!r} "
            f"observed_unreadable={sorted(observed_unreadable_ids)!r} "
            f"observed_skipped={sorted(observed_skipped_ids)!r}"
        )
    expected_skipped = len(observed_skipped_ids) if allow_fixed_skips else 0
    if value.get("io_errors") != 0 or value.get("skipped") != expected_skipped:
        raise ReportError(f"{field} has I/O errors or skipped work")


def require_operations_stale_coverage(
    value: dict[str, object], field: str, *, allow_differences: bool = False,
) -> None:
    """Validate the one permitted pre-repair namespace-precursor shape."""
    if value.get("complete") is not False or value.get("io_errors") != 0:
        raise ReportError(f"{field} is not a fail-closed namespace precursor")

    def known_group(name: str) -> dict[str, int]:
        raw = value[name]
        assert isinstance(raw, dict)
        if any(item is None for item in raw.values()):
            raise ReportError(f"{field}.{name} has an unknown required counter")
        return {key: int(item) for key, item in raw.items()}

    mft = known_group("mft_slots")
    if not (
        mft["expected"] > 0
        and mft["expected"] == mft["completed"] == mft["live"] + mft["free"]
        and mft["unreadable"] == mft["invalid"] == 0
    ):
        raise ReportError(f"{field}.mft_slots does not reconcile")
    attrs = known_group("attributes")
    if not (
        attrs["expected"] > 0
        and attrs["nonresident"] > 0
        and attrs["runs_expected"] > 0
        and attrs["expected"] == attrs["completed"]
        and attrs["completed"] == attrs["resident"] + attrs["nonresident"]
        and attrs["user_defined"] <= attrs["completed"]
        and attrs["extents_expected"] == attrs["extents_completed"]
        and attrs["runs_expected"] == attrs["runs_completed"]
        and attrs["unreadable"] == attrs["skipped"] == 0
    ):
        raise ReportError(f"{field}.attributes does not reconcile")
    namespace = value["namespace_links"]
    assert isinstance(namespace, dict)
    if not (
        isinstance(namespace.get("expected"), int)
        and namespace.get("expected", 0) > 0
        and namespace.get("expected") == namespace.get("completed")
        and namespace.get("reciprocal") is None
        and namespace.get("unresolved") == namespace.get("unreadable") == 0
    ):
        raise ReportError(f"{field}.namespace_links is not the stale-edge shape")
    bitmaps = known_group("bitmaps")
    if not (
        bitmaps["mft_bits_expected"] > 0
        and bitmaps["cluster_bits_expected"] > 0
        and bitmaps["mft_bits_expected"] == bitmaps["mft_bits_examined"]
        and bitmaps["cluster_bits_expected"] == bitmaps["cluster_bits_examined"]
        and (allow_differences or bitmaps["differences"] == 0)
    ):
        raise ReportError(f"{field}.bitmaps does not reconcile")
    compressed = known_group("compressed")
    if not (
        compressed["units_expected"] == compressed["units_examined"]
        and compressed["unreadable"] == 0
    ):
        raise ReportError(f"{field}.compressed does not reconcile")
    for name in ("indexes", "security", "reparse"):
        raw = value[name]
        assert isinstance(raw, dict)
        if any(item is not None for item in raw.values()):
            raise ReportError(f"{field}.{name} fabricated downstream coverage")

    fixed = value["fixed_system"]
    assert isinstance(fixed, dict)
    checks = fixed.get("checks")
    if not isinstance(checks, list):
        raise ReportError(f"{field}.fixed_system.checks is absent")
    results = {str(check.get("id")): check.get("result") for check in checks}
    failed_ids = {"extend.objid", "extend.quota", "extend.reparse"}
    passed_ids = {"system.attrdef", "system.upcase"}
    skipped_ids = set(REQUIRED_FIXED_SYSTEM_CHECK_IDS) - failed_ids - passed_ids
    expected_results = {
        **{check_id: "FAIL" for check_id in failed_ids},
        **{check_id: "PASS" for check_id in passed_ids},
        **{check_id: "SKIPPED" for check_id in skipped_ids},
    }
    if (
        tuple(check.get("id") for check in checks)
        != REQUIRED_FIXED_SYSTEM_CHECK_IDS
        or results != expected_results
        or fixed.get("expected") != len(REQUIRED_FIXED_SYSTEM_CHECK_IDS)
        or fixed.get("completed") != len(failed_ids) + len(passed_ids)
        or fixed.get("failed") != len(failed_ids)
        # The absent Secure provider contributes its two frozen counter
        # families in addition to the individually skipped fixed checks.
        or value.get("skipped") != len(skipped_ids) + 2
    ):
        raise ReportError(f"{field}.fixed_system is not the stale-edge precursor")


def complete_coverage_self_test() -> int:
    coverage: dict[str, object] = {
        "complete": True,
        "ledger_hash": "",
        "io_errors": 0,
        "skipped": 0,
    }
    for group_name, counters in COVERAGE_COUNTER_GROUPS:
        coverage[group_name] = {counter: 0 for counter in counters}
    coverage["mft_slots"].update(
        expected=32, completed=32, live=20, free=12
    )
    coverage["attributes"].update(
        expected=64,
        completed=64,
        resident=63,
        nonresident=1,
        extents_expected=1,
        extents_completed=1,
        runs_expected=1,
        runs_completed=1,
    )
    coverage["namespace_links"].update(
        expected=10, completed=10, reciprocal=10
    )
    coverage["indexes"].update(expected=8, completed=8)
    coverage["bitmaps"].update(
        mft_bits_expected=32,
        mft_bits_examined=32,
        cluster_bits_expected=1024,
        cluster_bits_examined=1024,
    )
    coverage["security"].update(
        ids_expected=1,
        ids_examined=1,
        descriptors_expected=1,
        descriptors_examined=1,
        sds_entries_expected=1,
        sds_entries_examined=1,
        sdh_entries_expected=1,
        sdh_entries_examined=1,
        sii_entries_expected=1,
        sii_entries_examined=1,
    )
    fixed = coverage["fixed_system"]
    fixed.update(
        expected=len(REQUIRED_FIXED_SYSTEM_CHECK_IDS),
        completed=len(REQUIRED_FIXED_SYSTEM_CHECK_IDS),
        checks=[
            {"id": check_id, "result": "PASS"}
            for check_id in REQUIRED_FIXED_SYSTEM_CHECK_IDS
        ],
    )
    coverage["ledger_hash"] = hashlib.sha256(
        coverage_ledger_payload(coverage, "selftest.complete")
    ).hexdigest()
    validate_coverage(coverage, "selftest.complete")
    require_complete_coverage(coverage, "selftest.complete")

    negative_count = 0
    for name, candidate in (
        ("zero-denominators", copy.deepcopy(coverage)),
        ("missing-fixed-check", copy.deepcopy(coverage)),
    ):
        if name == "zero-denominators":
            candidate["mft_slots"].update(
                expected=0, completed=0, live=0, free=0
            )
        else:
            candidate_fixed = candidate["fixed_system"]
            candidate_fixed["checks"].pop()
            candidate_fixed["expected"] -= 1
            candidate_fixed["completed"] -= 1
        try:
            require_complete_coverage(candidate, f"selftest.{name}")
        except ReportError:
            negative_count += 1
        else:
            raise ReportError(f"complete coverage self-test accepted {name}")
    return negative_count


def validate_native_log(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != NATIVE_LOG_FIELDS:
        raise ReportError(f"{field} fields differ from format-3")
    checked = require_bool(value.get("checked"), f"{field}.checked")
    state = value.get("state")
    if state is not None and state not in NATIVE_LOG_STATES:
        raise ReportError(f"{field}.state is invalid")
    logfile_bytes = nullable_u64(value.get("logfile_bytes"), f"{field}.logfile_bytes")
    pages_expected = nullable_u32(
        value.get("pages_expected"), f"{field}.pages_expected"
    )
    version_major = nullable_u16(
        value.get("version_major"), f"{field}.version_major"
    )
    version_minor = nullable_u16(
        value.get("version_minor"), f"{field}.version_minor"
    )
    lsns = {
        name: nullable_u64(value.get(name), f"{field}.{name}")
        for name in NATIVE_LOG_NULLABLE_U64_FIELDS
        if name != "logfile_bytes"
    }
    counts = {
        name: require_u32(value.get(name), f"{field}.{name}")
        for name in NATIVE_LOG_U32_FIELDS
    }
    planned_operations = require_u64(
        value.get("planned_io_operations"), f"{field}.planned_io_operations"
    )
    planned_bytes = require_u64(
        value.get("planned_io_bytes"), f"{field}.planned_io_bytes"
    )

    if not checked:
        if (
            state is not None
            or logfile_bytes is not None
            or pages_expected is not None
            or version_major is not None
            or version_minor is not None
            or any(item is not None for item in lsns.values())
            or any(counts.values())
            or planned_operations
            or planned_bytes
        ):
            raise ReportError(f"{field} fabricates evidence while unchecked")
        return value

    if state is None or logfile_bytes is None or pages_expected is None:
        raise ReportError(f"{field} checked without a bound logfile/state")
    if logfile_bytes == 0 or logfile_bytes % 4096 != 0:
        raise ReportError(f"{field}.logfile_bytes is not positive 4 KiB geometry")
    if pages_expected != logfile_bytes // 4096:
        raise ReportError(f"{field}.pages_expected differs from logfile size")
    if counts["pages_examined"] > pages_expected:
        raise ReportError(f"{field}.pages_examined exceeds the logfile")
    if counts["wiped_pages_scanned"] > counts["pages_examined"]:
        raise ReportError(f"{field}.wiped_pages_scanned exceeds examined pages")
    if counts["actions_seen"] != (
        counts["control_records_examined"] + counts["mutation_records_examined"]
    ):
        raise ReportError(f"{field}.actions_seen does not reconcile")
    if counts["checkpoint_records_examined"] > counts["control_records_examined"]:
        raise ReportError(f"{field} checkpoint count exceeds control records")
    for name in (
        "open_attribute_tables",
        "attribute_name_tables",
        "dirty_page_tables",
        "transaction_tables",
    ):
        if counts[name] > counts["control_records_examined"]:
            raise ReportError(f"{field}.{name} exceeds control records")
    for name in ("redo_actions", "undo_actions"):
        if counts[name] > counts["mutation_records_examined"]:
            raise ReportError(f"{field}.{name} exceeds mutation records")
    if bool(version_major is None) != bool(version_minor is None):
        raise ReportError(f"{field} has a partial native-log version")

    errors = counts["unsupported_actions"] + counts["io_errors"] + counts["parse_errors"]
    if state == "EMPTY_T1OS":
        zero_fields = (
            "checkpoint_records_examined",
            "control_records_examined",
            "mutation_records_examined",
            "open_attribute_tables",
            "attribute_name_tables",
            "dirty_page_tables",
            "transaction_tables",
            "actions_seen",
            "redo_actions",
            "undo_actions",
            "restart_pages_planned",
            "unsupported_actions",
            "io_errors",
            "parse_errors",
        )
        if (
            counts["pages_examined"] != pages_expected
            or counts["wiped_pages_scanned"] != pages_expected
            or any(counts[name] for name in zero_fields)
            or version_major is not None
            or any(item is not None for item in lsns.values())
            or planned_operations
            or planned_bytes
        ):
            raise ReportError(f"{field} EMPTY_T1OS evidence differs")
    elif state in ("CLEAN_RESTART", "REPLAY_PLANNED"):
        if (version_major, version_minor) not in ((1, 1), (2, 0)):
            raise ReportError(f"{field} uses an unsupported restart-page version")
        if any(item is None for item in lsns.values()) or errors:
            raise ReportError(f"{field} valid restart state lacks clean LSN evidence")
        if state == "CLEAN_RESTART" and (
            counts["redo_actions"]
            or counts["undo_actions"]
            or counts["restart_pages_planned"]
            or planned_operations
            or planned_bytes
        ):
            raise ReportError(f"{field} CLEAN_RESTART contains a repair plan")
        if state == "REPLAY_PLANNED" and (
            counts["mutation_records_examined"] == 0
            or counts["redo_actions"] + counts["undo_actions"] == 0
            or counts["restart_pages_planned"] != 2
            or planned_operations == 0
            or planned_bytes == 0
        ):
            raise ReportError(f"{field} REPLAY_PLANNED evidence is incomplete")
    elif state == "UNSAFE":
        if (
            counts["io_errors"]
            or not (counts["parse_errors"] or counts["unsupported_actions"])
            or planned_operations
            or planned_bytes
        ):
            raise ReportError(f"{field} UNSAFE evidence differs")
    elif state == "IO_ERROR":
        if counts["io_errors"] == 0 or planned_operations or planned_bytes:
            raise ReportError(f"{field} IO_ERROR evidence differs")
    else:
        raise ReportError(f"{field}.state is invalid")
    return value


def validate_native_log_reconciliation(
    native_log: dict[str, object],
    *,
    mode: str,
    plan: object,
    repairs: object,
    batch_ledger: object,
    batch_samples: object,
) -> None:
    """Require complete, hash-bound detail for a claimed native replay plan."""

    if native_log.get("state") != "REPLAY_PLANNED":
        return
    if mode != "repair":
        raise ReportError("read-only check cannot publish REPLAY_PLANNED")
    if not isinstance(plan, dict):
        raise ReportError("native replay lacks its top-level plan")
    if not isinstance(repairs, list) or not repairs:
        raise ReportError("native replay lacks detailed ID 5/6 repairs")
    if not isinstance(batch_ledger, dict) or not batch_ledger:
        raise ReportError("native replay lacks its RHTXN3 ledger")
    if not isinstance(batch_samples, list) or not batch_samples:
        raise ReportError("native replay lacks its detailed RHTXN3 transactions")

    record_count = batch_ledger.get("record_count")
    if (
        not isinstance(record_count, int)
        or isinstance(record_count, bool)
        or record_count == 0
        or len(batch_samples) != record_count
        or [sample.get("ordinal") for sample in batch_samples]
        != list(range(record_count))
    ):
        raise ReportError("native replay requires the complete RHTXN3 ledger")
    if batch_ledger.get("ledger_hash") != batch_ledger_hash(batch_samples):
        raise ReportError("native replay RHTXN3 hash differs from its transactions")

    native_transactions: list[tuple[int, dict[str, object]]] = []
    for index, sample in enumerate(batch_samples):
        counts = sample.get("by_action_id")
        if (
            isinstance(counts, dict)
            and (counts.get("5", 0) or counts.get("6", 0))
            and sample.get("origin") == "NEW"
            and sample.get("result") in ("accepted", "refused")
        ):
            native_transactions.append((index, sample))
    if len(native_transactions) != 1:
        raise ReportError("native replay lacks exactly one current metadata transaction")
    native_ordinal, transaction = native_transactions[0]
    if not isinstance(transaction, dict):
        raise ReportError("native replay RHTXN3 transaction is not an object")
    transaction_counts = transaction.get("by_action_id")
    transaction_bytes = transaction.get("bytes_by_action_id")
    if (
        transaction.get("phase") != "METADATA_REPAIR"
        or transaction.get("origin") != "NEW"
        or transaction.get("result") not in ("accepted", "refused")
        or not isinstance(transaction_counts, dict)
        or not isinstance(transaction_bytes, dict)
    ):
        raise ReportError("native replay RHTXN3 transaction shape differs")

    transaction_start = sum(
        int(sample["entry_count"])
        for sample in batch_samples[:native_ordinal]
        if sample.get("phase") != "FOUNDATION" and sample.get("origin") == "NEW"
    )
    transaction_count = int(transaction["entry_count"])
    transaction_ordinals = range(
        transaction_start, transaction_start + transaction_count
    )
    repairs_by_ordinal = {repair.get("ordinal"): repair for repair in repairs}
    if len(repairs_by_ordinal) != len(repairs) or any(
        ordinal not in repairs_by_ordinal for ordinal in transaction_ordinals
    ):
        raise ReportError("native replay lacks every detailed transaction repair")
    transaction_repairs = [
        repairs_by_ordinal[ordinal] for ordinal in transaction_ordinals
    ]
    if transaction.get("repair_ledger_hash") != repair_ledger_hash(
        transaction_repairs
    ):
        raise ReportError("native replay RHREPL3 hash differs from detailed repairs")

    action_ids = [int(repair["action_id"]) for repair in transaction_repairs]
    dirty_set_count = int(transaction_counts.get("24", 0))
    validate_native_action_order(action_ids, dirty_set_count, native_ordinal)
    native_repairs = [
        repair for repair in transaction_repairs if repair.get("action_id") in (5, 6)
    ]
    action_counts = Counter(str(repair["action_id"]) for repair in native_repairs)
    byte_counts: Counter[str] = Counter()
    for repair in native_repairs:
        byte_counts[str(repair["action_id"])] += int(repair["length"])

    planned_operations = int(native_log["planned_io_operations"])
    planned_bytes = int(native_log["planned_io_bytes"])
    if (
        len(native_repairs) != planned_operations
        or sum(byte_counts.values()) != planned_bytes
        or action_counts["5"] == 0
        or action_counts["6"] != native_log.get("restart_pages_planned")
    ):
        raise ReportError("native_log planned I/O differs from detailed ID 5/6 repairs")
    if transaction.get("result") == "refused" and any(
        repair.get("verified") is not False or repair.get("write_boundaries") != 0
        for repair in transaction_repairs
    ):
        raise ReportError("refused native replay contains physical write evidence")

    expected_count_ids = dict(action_counts)
    expected_byte_ids = dict(byte_counts)
    expected_count_kinds = {
        REPAIR_ACTIONS[int(action_id)]: count
        for action_id, count in expected_count_ids.items()
    }
    expected_byte_kinds = {
        REPAIR_ACTIONS[int(action_id)]: count
        for action_id, count in expected_byte_ids.items()
    }
    for field, record in (
        ("top-level plan", plan),
        ("RHTXN3 transaction", transaction),
    ):
        count_ids = record.get("by_action_id")
        count_kinds = record.get("by_kind")
        byte_ids = record.get("bytes_by_action_id")
        byte_kinds = record.get("bytes_by_kind")
        if not all(
            isinstance(mapping, dict)
            for mapping in (count_ids, count_kinds, byte_ids, byte_kinds)
        ):
            raise ReportError(f"native replay {field} action maps are absent")
        assert isinstance(count_ids, dict) and isinstance(count_kinds, dict)
        assert isinstance(byte_ids, dict) and isinstance(byte_kinds, dict)
        if (
            {action_id: count_ids.get(action_id, 0) for action_id in ("5", "6")}
            != expected_count_ids
            or {
                kind: count_kinds.get(kind, 0) for kind in expected_count_kinds
            }
            != expected_count_kinds
            or {action_id: byte_ids.get(action_id, 0) for action_id in ("5", "6")}
            != expected_byte_ids
            or {kind: byte_kinds.get(kind, 0) for kind in expected_byte_kinds}
            != expected_byte_kinds
        ):
            raise ReportError(f"native replay differs from {field} ID 5/6 maps")
    if (
        int(batch_ledger.get("native_redo_count", 0)) < action_counts["5"]
        or int(batch_ledger.get("native_restart_count", 0)) < action_counts["6"]
    ):
        raise ReportError("current native replay exceeds its RHTXN3 aggregates")


def native_log_self_test() -> int:
    def blank() -> dict[str, object]:
        value: dict[str, object] = {
            "checked": False,
            "state": None,
            "logfile_bytes": None,
            "pages_expected": None,
            "version_major": None,
            "version_minor": None,
            "restart_lsn": None,
            "synced_lsn": None,
            "committed_lsn": None,
            "latest_lsn": None,
            "planned_io_operations": 0,
            "planned_io_bytes": 0,
        }
        value.update({name: 0 for name in NATIVE_LOG_U32_FIELDS})
        return value

    unchecked = blank()
    empty = dict(
        blank(),
        checked=True,
        state="EMPTY_T1OS",
        logfile_bytes=512 * 4096,
        pages_expected=512,
        pages_examined=512,
        wiped_pages_scanned=512,
    )
    clean = dict(
        blank(),
        checked=True,
        state="CLEAN_RESTART",
        logfile_bytes=512 * 4096,
        pages_expected=512,
        pages_examined=4,
        version_major=1,
        version_minor=1,
        restart_lsn=100,
        synced_lsn=100,
        committed_lsn=100,
        latest_lsn=100,
    )
    replay = dict(
        clean,
        state="REPLAY_PLANNED",
        checkpoint_records_examined=1,
        control_records_examined=1,
        mutation_records_examined=1,
        transaction_tables=1,
        actions_seen=2,
        redo_actions=1,
        restart_pages_planned=2,
        planned_io_operations=4,
        planned_io_bytes=10240,
    )
    unsafe = dict(
        blank(),
        checked=True,
        state="UNSAFE",
        logfile_bytes=512 * 4096,
        pages_expected=512,
        pages_examined=1,
        parse_errors=1,
    )
    io_error = dict(
        blank(),
        checked=True,
        state="IO_ERROR",
        logfile_bytes=512 * 4096,
        pages_expected=512,
        pages_examined=1,
        io_errors=1,
    )
    for index, candidate in enumerate(
        (unchecked, empty, clean, replay, unsafe, io_error)
    ):
        validate_native_log(candidate, f"selftest.native.positive[{index}]")
    negative_count = 0

    def must_reject(name: str, candidate: dict[str, object]) -> None:
        nonlocal negative_count
        try:
            validate_native_log(candidate, f"selftest.native.{name}")
        except ReportError:
            negative_count += 1
            return
        raise ReportError(f"native-log self-test accepted {name}")

    missing = dict(unchecked)
    del missing["checked"]
    must_reject("missing-field", missing)
    must_reject("unchecked-evidence", dict(unchecked, pages_examined=1))
    must_reject("geometry", dict(clean, logfile_bytes=4097))
    must_reject("examined-overflow", dict(clean, pages_examined=513))
    must_reject("action-reconciliation", dict(replay, actions_seen=3))
    must_reject("checkpoint-overflow", dict(replay, checkpoint_records_examined=2))
    must_reject("redo-overflow", dict(replay, redo_actions=2))
    must_reject("partial-version", dict(clean, version_minor=None))
    must_reject("empty-partial-scan", dict(empty, pages_examined=511))
    must_reject("empty-actions", dict(empty, actions_seen=1))
    must_reject("clean-plan", dict(clean, planned_io_operations=1))
    must_reject("replay-no-mutation", dict(replay, mutation_records_examined=0))
    must_reject("replay-no-restart", dict(replay, restart_pages_planned=0))
    must_reject("unsafe-no-reason", dict(unsafe, parse_errors=0))
    must_reject("unsafe-io", dict(unsafe, io_errors=1))
    must_reject("io-no-error", dict(io_error, io_errors=0))
    must_reject("unknown-state", dict(clean, state="RESET"))
    must_reject("uint32-overflow", dict(clean, pages_examined=1 << 32))
    if negative_count != 18:
        raise ReportError(
            f"native-log self-test expected 18 negatives, found {negative_count}"
        )
    return negative_count


def native_replay_reconciliation_self_test() -> int:
    native_log: dict[str, object] = {
        "checked": True,
        "state": "REPLAY_PLANNED",
        "logfile_bytes": 512 * 4096,
        "pages_expected": 512,
        "pages_examined": 4,
        "wiped_pages_scanned": 0,
        "version_major": 1,
        "version_minor": 1,
        "restart_lsn": 100,
        "synced_lsn": 100,
        "committed_lsn": 100,
        "latest_lsn": 100,
        "checkpoint_records_examined": 1,
        "control_records_examined": 1,
        "mutation_records_examined": 1,
        "open_attribute_tables": 0,
        "attribute_name_tables": 0,
        "dirty_page_tables": 0,
        "transaction_tables": 1,
        "actions_seen": 2,
        "redo_actions": 1,
        "undo_actions": 0,
        "restart_pages_planned": 2,
        "unsupported_actions": 0,
        "io_errors": 0,
        "parse_errors": 0,
        "planned_io_operations": 4,
        "planned_io_bytes": 10240,
    }
    validate_native_log(native_log, "selftest.native-replay.native_log")

    raw_repairs: list[dict[str, object]] = []
    native_lengths = (1024, 1024, 4096, 4096)
    for ordinal, (action_id, length) in enumerate(
        zip((5, 5, 6, 6), native_lengths, strict=True)
    ):
        raw_repairs.append(
            {
                "ordinal": ordinal,
                "sample_reasons": ["ERROR", "FIRST", "LAST"],
                "action_id": action_id,
                "kind": REPAIR_ACTIONS[action_id],
                "target": f"native-{ordinal}",
                "offset": sum(native_lengths[:ordinal]),
                "length": length,
                "before_hash": f"{ordinal + 1:x}" * 64,
                "after_hash": f"{ordinal + 5:x}" * 64,
                "verified": False,
                "write_boundaries": 0,
            }
        )
    repairs = validate_repair_samples(raw_repairs)
    count_ids = {"5": 2, "6": 2}
    count_kinds = {"logfile-redo": 2, "logfile-restart": 2}
    byte_ids = {"5": 2048, "6": 8192}
    byte_kinds = {"logfile-redo": 2048, "logfile-restart": 8192}
    plan: dict[str, object] = {
        "operations": 4,
        "bytes": 10240,
        "priority_operations": 4,
        "foundation_operations": 0,
        "foundation_bytes": 0,
        "wal_operations": 4,
        "wal_bytes": 10240,
        "by_action_id": count_ids,
        "by_kind": count_kinds,
        "bytes_by_action_id": byte_ids,
        "bytes_by_kind": byte_kinds,
    }
    transaction: dict[str, object] = {
        "ordinal": 0,
        "sample_reasons": ["ERROR", "FIRST", "LAST"],
        "phase": "METADATA_REPAIR",
        "origin": "NEW",
        "transaction_uuid": "10000000-0000-4000-8000-000000000001",
        "plan_hash": "a" * 64,
        "repair_ledger_hash": repair_ledger_hash(repairs),
        "entry_count": 4,
        "target_bytes": 10240,
        "by_action_id": count_ids,
        "by_kind": count_kinds,
        "bytes_by_action_id": byte_ids,
        "bytes_by_kind": byte_kinds,
        "commit_started": False,
        "commit_completed": False,
        "rollback_completed": False,
        "rollback_readback_verified": False,
        "rollback_restored_entries": 0,
        "rollback_restored_bytes": 0,
        "rollback_syncs": 0,
        "rollback_write_boundaries": 0,
        "last_verified_ordinal": 0,
        "syncs": 0,
        "write_boundaries": 0,
        "result": "refused",
        "rescan_digest": None,
        "post_coverage_ledger_hash": None,
        "post_diagnosis_hash": None,
        "rescan": None,
    }
    batch_ledger: dict[str, object] = {
        "format": BATCH_LEDGER_FORMAT,
        "record_count": 1,
        "ledger_hash": batch_ledger_hash([transaction]),
        "foundation_count": 0,
        "new_count": 1,
        "recovered_committed_count": 0,
        "recovered_rolled_back_count": 0,
        "metadata_count": 1,
        "dirty_clear_count": 0,
        "accepted_count": 0,
        "refused_count": 1,
        "rolled_back_count": 0,
        "priority_count": 1,
        "rescan_count": 0,
        "commit_started_count": 0,
        "commit_completed_count": 0,
        "verified_entries": 0,
        "rollback_restored_entries": 0,
        "rollback_restored_bytes": 0,
        "rollback_syncs": 0,
        "rollback_write_boundaries": 0,
        "entry_count": 4,
        "target_bytes": 10240,
        "syncs": 0,
        "write_boundaries": 0,
        "by_action_id": count_ids,
        "by_kind": count_kinds,
        "bytes_by_action_id": byte_ids,
        "bytes_by_kind": byte_kinds,
        "dirty_set_action_count": 0,
        "dirty_set_phase_ordinal": None,
        "dirty_clear_action_count": 0,
        "dirty_clear_phase_ordinal": None,
        "native_redo_count": 2,
        "native_restart_count": 2,
        "native_phase_ordinal": 0,
        "first_metadata_ordinal": 0,
        "first_phase": "METADATA_REPAIR",
        "last_phase": "METADATA_REPAIR",
        "final_rescan_digest": None,
        "final_coverage_ledger_hash": None,
        "final_diagnosis_hash": None,
    }
    _, batch_samples = validate_batch_ledger(
        {"batch_ledger": batch_ledger, "batch_samples": [transaction]}
    )
    validate_native_log_reconciliation(
        native_log,
        mode="repair",
        plan=plan,
        repairs=repairs,
        batch_ledger=batch_ledger,
        batch_samples=batch_samples,
    )

    zero_plan = {
        "operations": 0,
        "bytes": 0,
        "priority_operations": 0,
        "foundation_operations": 0,
        "foundation_bytes": 0,
        "wal_operations": 0,
        "wal_bytes": 0,
        "by_action_id": {},
        "by_kind": {},
        "bytes_by_action_id": {},
        "bytes_by_kind": {},
    }
    negative_count = 0

    def must_reject(
        name: str,
        *,
        candidate_mode: str = "repair",
        candidate_plan: object = plan,
        candidate_repairs: object = repairs,
        candidate_ledger: object = batch_ledger,
        candidate_samples: object = batch_samples,
    ) -> None:
        nonlocal negative_count
        try:
            validate_native_log_reconciliation(
                native_log,
                mode=candidate_mode,
                plan=candidate_plan,
                repairs=candidate_repairs,
                batch_ledger=candidate_ledger,
                batch_samples=candidate_samples,
            )
        except ReportError:
            negative_count += 1
            return
        raise ReportError(f"native replay self-test accepted {name}")

    must_reject("check-mode", candidate_mode="check")
    must_reject("empty-top-plan", candidate_plan=zero_plan)
    must_reject("empty-top-repairs", candidate_repairs=[])
    must_reject("empty-transaction-ledger", candidate_ledger={})
    must_reject("empty-transaction-samples", candidate_samples=[])
    wrong_plan = copy.deepcopy(plan)
    wrong_plan["by_action_id"] = {"5": 4}
    must_reject("top-plan-id-map", candidate_plan=wrong_plan)
    wrong_repairs = copy.deepcopy(repairs)
    wrong_repairs[1]["action_id"] = 7
    wrong_repairs[1]["kind"] = REPAIR_ACTIONS[7]
    must_reject("nonnative-detailed-repair", candidate_repairs=wrong_repairs)
    wrong_transaction = copy.deepcopy(batch_samples)
    wrong_transaction[0]["repair_ledger_hash"] = "f" * 64
    must_reject("repair-ledger-hash", candidate_samples=wrong_transaction)
    wrong_ledger = copy.deepcopy(batch_ledger)
    wrong_ledger["native_restart_count"] = 1
    must_reject("transaction-ledger-aggregate", candidate_ledger=wrong_ledger)
    wrong_rhtxn_hash = copy.deepcopy(batch_ledger)
    wrong_rhtxn_hash["ledger_hash"] = "f" * 64
    must_reject("transaction-ledger-hash", candidate_ledger=wrong_rhtxn_hash)
    if negative_count != 10:
        raise ReportError(
            "native replay self-test expected 10 negatives, "
            f"found {negative_count}"
        )
    return negative_count


def uncommitted_native_plan_self_test() -> int:
    raw_repairs: list[dict[str, object]] = []
    native_lengths = (1024, 1024, 4096, 4096)
    for ordinal, (action_id, length) in enumerate(
        zip((5, 5, 6, 6), native_lengths, strict=True)
    ):
        raw_repairs.append(
            {
                "ordinal": ordinal,
                "action_id": action_id,
                "kind": REPAIR_ACTIONS[action_id],
                "target": f"native-{ordinal}",
                "offset": sum(native_lengths[:ordinal]),
                "length": length,
                "before_hash": f"{ordinal + 1:x}" * 64,
                "after_hash": f"{ordinal + 5:x}" * 64,
                "verified": False,
                "write_boundaries": 0,
                "sample_reasons": ["FIRST", "LAST"],
            }
        )
    repairs = [
        validate_action(item, index, "selftest.native-plan.repairs")
        for index, item in enumerate(raw_repairs)
    ]
    transaction: dict[str, object] = {
        "ordinal": 0,
        "origin": "NEW",
        "kind": "METADATA_REPAIR",
        "transaction_uuid": "10000000-0000-4000-8000-000000000001",
        "plan_hash": "a" * 64,
        "initial_state": "PREPARING",
        "final_state": "ROLLBACK",
        "entry_count": 4,
        "target_bytes": 10240,
        "repair_first_ordinal": 0,
        "repair_count": 4,
        "repair_sample_first_index": 0,
        "repair_sample_count": 4,
        "repair_ledger_format": REPAIR_LEDGER_FORMAT,
        "repair_ledger_hash": repair_ledger_hash(raw_repairs),
        "by_action_id": {"5": 2, "6": 2},
        "by_kind": {"logfile-redo": 2, "logfile-restart": 2},
        "bytes_by_action_id": {"5": 2048, "6": 8192},
        "bytes_by_kind": {"logfile-redo": 2048, "logfile-restart": 8192},
        "first_action_ids": [5, 5],
        "last_action_ids": [6, 6],
        "commit_started": False,
        "commit_completed": False,
        "last_verified_ordinal": 0,
        "syncs": 0,
        "write_boundaries": 0,
        "result": "refused",
    }
    transactions, new_transactions = validate_transactions(
        {"transactions": [transaction]}, repairs
    )
    if transactions != [transaction] or new_transactions != [transaction]:
        raise ReportError("uncommitted native-plan self-test lost its transaction")
    validate_wal_action_reconciliation({"actions": []}, transactions)

    negative_count = 0

    def reject_action(name: str, mutation: dict[str, object]) -> None:
        nonlocal negative_count
        candidate = copy.deepcopy(raw_repairs[0])
        candidate.update(mutation)
        try:
            validate_action(candidate, 0, f"selftest.native-plan.{name}")
        except ReportError:
            negative_count += 1
            return
        raise ReportError(f"uncommitted native-plan self-test accepted {name}")

    reject_action("verified-without-write", {"verified": True})
    reject_action("write-without-verify", {"write_boundaries": 1})

    for name, mutation in (
        ("commit-started", {"commit_started": True}),
        ("verified-ordinal", {"last_verified_ordinal": 1}),
    ):
        candidate = copy.deepcopy(transaction)
        candidate.update(mutation)
        try:
            validate_transactions({"transactions": [candidate]}, repairs)
        except ReportError:
            negative_count += 1
        else:
            raise ReportError(f"uncommitted native-plan self-test accepted {name}")
    try:
        validate_wal_action_reconciliation(
            {"actions": [{"transaction_ordinal": 0}]}, transactions
        )
    except ReportError:
        negative_count += 1
    else:
        raise ReportError("uncommitted native plan wrote the internal WAL")
    if negative_count != 5:
        raise ReportError(
            "uncommitted native-plan self-test expected 5 negatives, "
            f"found {negative_count}"
        )
    return negative_count


def validate_snapshot(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ReportError(f"{field} must be an object")
    require_exact_fields(
        value,
        SNAPSHOT_FIELDS if field == "initial" else RESCAN_FIELDS,
        field,
    )
    if field != "initial":
        require_u64(value.get("ordinal"), f"{field}.ordinal")
        if value.get("stage") not in ("POST_METADATA", "FINAL"):
            raise ReportError(f"{field}.stage is invalid")
        if value.get("binding") not in ("INITIAL", "FOUNDATION", "TRANSACTION"):
            raise ReportError(f"{field}.binding is invalid")
        transaction_uuid = value.get("transaction_uuid")
        if transaction_uuid is not None:
            require_uuid(transaction_uuid, f"{field}.transaction_uuid")
        plan_hash = value.get("plan_hash")
        if plan_hash is not None:
            require_sha256(plan_hash, f"{field}.plan_hash")
    completed = require_bool(value.get("completed"), f"{field}.completed")
    scan_id = value.get("scan_id")
    if scan_id is not None and (
        not isinstance(scan_id, str) or not UUID.fullmatch(scan_id)
    ):
        raise ReportError(f"{field}.scan_id is not a canonical UUID or null")
    if completed and scan_id is None:
        raise ReportError(f"{field} completed without a scan_id")
    validate_execution(value.get("execution"), f"{field}.execution")
    if value.get("fresh_process") is not True or value.get("read_only") is not True:
        raise ReportError(f"{field} must attest a fresh read-only process")
    exit_code = value.get("exit_code")
    result = value.get("result")
    if exit_code is not None and (
        not isinstance(exit_code, int)
        or isinstance(exit_code, bool)
        or exit_code not in (0, 2, 3, 4, 5)
    ):
        raise ReportError(f"{field}.exit_code is invalid")
    if result is not None and result not in (
        "clean",
        "unsafe",
        "io-error",
        "wrong-root",
        "internal-error",
    ):
        raise ReportError(f"{field}.result is invalid")
    for state in ("dirty", "logfile_clean", "identity_valid"):
        nullable_bool(value.get(state), f"{field}.{state}")
    if "native_log_state" not in value:
        raise ReportError(f"{field}.native_log_state is absent")
    native_state = value.get("native_log_state")
    if native_state is not None and native_state not in NATIVE_LOG_STATES:
        raise ReportError(f"{field}.native_log_state is invalid")
    validate_coverage(value.get("coverage"), f"{field}.coverage")
    if completed and (exit_code is None or result is None):
        raise ReportError(f"{field} completed without result/exit evidence")
    if result == "clean" and (
        exit_code != 0
        or value.get("dirty") is not False
        or value.get("logfile_clean") is not True
        or value.get("identity_valid") is not True
        or native_state not in ("CLEAN_RESTART", "EMPTY_T1OS")
    ):
        raise ReportError(f"{field} clean result lacks clean state evidence")
    if completed:
        if value.get("logfile_clean") is True and native_state not in (
            "CLEAN_RESTART",
            "EMPTY_T1OS",
        ):
            raise ReportError(f"{field} logfile result disagrees with native state")
        if native_state == "REPLAY_PLANNED" and value.get("logfile_clean") is not False:
            raise ReportError(f"{field} planned replay is not marked log-unclean")
        if native_state in ("UNSAFE", "IO_ERROR") and value.get("logfile_clean") is True:
            raise ReportError(f"{field} unsafe native log is marked clean")
    return value


def canonical_issue_record(issue: object, field: str) -> bytes:
    if not isinstance(issue, dict):
        raise ReportError(f"{field} must be an object")
    if set(issue) not in (ISSUE_FIELDS, ISSUE_SAMPLE_FIELDS):
        raise ReportError(f"{field} contains unknown issue fields")
    ordinal = require_u64(issue.get("ordinal"), f"{field}.ordinal")
    severity = issue.get("severity")
    policy = issue.get("policy")
    if severity not in ISSUE_SEVERITY_CODES:
        raise ReportError(f"{field}.severity is invalid")
    if policy not in ISSUE_POLICY_CODES:
        raise ReportError(f"{field}.policy is invalid")
    resolved = require_bool(issue.get("resolved"), f"{field}.resolved")
    code = canonical_text(
        issue.get("code"), f"{field}.code", MAX_ISSUE_CODE_BYTES
    )
    pass_name = canonical_text(
        issue.get("pass"), f"{field}.pass", MAX_ISSUE_PASS_BYTES
    )
    path = canonical_text(
        issue.get("path"),
        f"{field}.path",
        MAX_ISSUE_PATH_BYTES,
        nullable=True,
        allow_empty=True,
    )
    message = canonical_text(
        issue.get("message"), f"{field}.message", MAX_ISSUE_MESSAGE_BYTES
    )
    required_predicates = issue.get("required_predicates")
    failed_predicates = issue.get("failed_predicates")
    if not isinstance(required_predicates, list) or not isinstance(failed_predicates, list):
        raise ReportError(f"{field} predicate arrays are absent")
    for name, predicates in (
        ("required_predicates", required_predicates),
        ("failed_predicates", failed_predicates),
    ):
        if (
            len(predicates) > MAX_ISSUE_PREDICATES
            or predicates != sorted(set(predicates))
        ):
            raise ReportError(f"{field}.{name} is not bounded/sorted/unique")
        for index, predicate in enumerate(predicates):
            require_bounded_utf8(
                predicate,
                f"{field}.{name}[{index}]",
                MAX_ISSUE_PREDICATE_BYTES,
            )
    if any(predicate not in required_predicates for predicate in failed_predicates):
        raise ReportError(f"{field} failed predicate is not required")
    action_ordinals = issue.get("action_ordinals")
    if (
        not isinstance(action_ordinals, list)
        or len(action_ordinals) > MAX_ISSUE_ACTION_ORDINALS
        or action_ordinals != sorted(set(action_ordinals))
    ):
        raise ReportError(f"{field}.action_ordinals is not sorted/unique")
    for index, action_ordinal in enumerate(action_ordinals):
        require_u64(action_ordinal, f"{field}.action_ordinals[{index}]")
    payload = bytearray()
    payload.extend(
        struct.pack(
            "<QBBBB",
            ordinal,
            ISSUE_SEVERITY_CODES[severity],
            1 if resolved else 0,
            ISSUE_POLICY_CODES[policy],
            0,
        )
    )
    payload.extend(canonical_nullable_u64(issue.get("record"), f"{field}.record"))
    payload.extend(canonical_nullable_u64(issue.get("offset"), f"{field}.offset"))
    payload.extend(code)
    payload.extend(pass_name)
    payload.extend(path)
    payload.extend(message)
    payload.extend(struct.pack("<H", len(required_predicates)))
    for index, predicate in enumerate(required_predicates):
        payload.extend(
            canonical_text(
                predicate,
                f"{field}.required_predicates[{index}]",
                MAX_ISSUE_PREDICATE_BYTES,
            )
        )
    payload.extend(struct.pack("<H", len(failed_predicates)))
    for index, predicate in enumerate(failed_predicates):
        payload.extend(
            canonical_text(
                predicate,
                f"{field}.failed_predicates[{index}]",
                MAX_ISSUE_PREDICATE_BYTES,
            )
        )
    payload.extend(struct.pack("<I", len(action_ordinals)))
    for action_ordinal in action_ordinals:
        payload.extend(struct.pack("<Q", int(action_ordinal)))
    return bytes(payload)


def issue_ledger_hash(issues: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    digest.update(ISSUE_LEDGER_MAGIC)
    digest.update(struct.pack("<I", 3))
    digest.update(struct.pack("<Q", len(issues)))
    for index, issue in enumerate(issues):
        if issue.get("ordinal") != index:
            raise ReportError("RHISS3 issue ordinals are not contiguous")
        digest.update(canonical_issue_record(issue, f"issue_records[{index}]"))
    return digest.hexdigest()


def validate_issues(report: dict[str, object]) -> dict[str, object]:
    ledger = report.get("issue_ledger")
    if not isinstance(ledger, dict):
        raise ReportError("issue_ledger must be an object")
    exact_fields = {
        "format",
        "entry_count",
        "ledger_hash",
        "resolved_count",
        "unresolved_count",
        "error_count",
        "by_severity",
        "unresolved_by_severity",
        "first_severity",
        "last_severity",
    }
    if set(ledger) != exact_fields:
        raise ReportError("issue_ledger field set differs from RHISS3")
    if ledger.get("format") != ISSUE_LEDGER_FORMAT:
        raise ReportError("issue_ledger format differs")
    entry_count = require_u64(ledger.get("entry_count"), "issue_ledger.entry_count")
    require_sha256(ledger.get("ledger_hash"), "issue_ledger.ledger_hash")
    resolved_count = require_u64(
        ledger.get("resolved_count"), "issue_ledger.resolved_count"
    )
    unresolved_count = require_u64(
        ledger.get("unresolved_count"), "issue_ledger.unresolved_count"
    )
    error_count = require_u64(ledger.get("error_count"), "issue_ledger.error_count")
    if resolved_count + unresolved_count != entry_count or error_count > entry_count:
        raise ReportError("issue_ledger resolution totals differ")
    by_severity = ledger.get("by_severity")
    unresolved_by_severity = ledger.get("unresolved_by_severity")
    if not isinstance(by_severity, dict) or not isinstance(unresolved_by_severity, dict):
        raise ReportError("issue_ledger severity maps must be objects")
    for name, mapping, total in (
        ("by_severity", by_severity, entry_count),
        ("unresolved_by_severity", unresolved_by_severity, unresolved_count),
    ):
        if any(
            severity not in ISSUE_SEVERITY_CODES
            or not isinstance(number, int)
            or isinstance(number, bool)
            or number <= 0
            or number > (1 << 64) - 1
            for severity, number in mapping.items()
        ) or sum(mapping.values()) != total:
            raise ReportError(f"issue_ledger.{name} is invalid")
    if any(
        unresolved_by_severity.get(severity, 0) > by_severity.get(severity, 0)
        for severity in unresolved_by_severity
    ):
        raise ReportError("issue_ledger unresolved severity count exceeds total")
    first_severity = ledger.get("first_severity")
    last_severity = ledger.get("last_severity")
    if entry_count == 0:
        if (
            by_severity
            or unresolved_by_severity
            or first_severity is not None
            or last_severity is not None
        ):
            raise ReportError("empty RHISS3 ledger has nonempty aggregates")
    elif (
        first_severity not in ISSUE_SEVERITY_CODES
        or last_severity not in ISSUE_SEVERITY_CODES
    ):
        raise ReportError("nonempty RHISS3 ledger lacks endpoint severities")
    issues = report.get("issues")
    if not isinstance(issues, list) or len(issues) > ISSUE_SAMPLE_LIMIT:
        raise ReportError("issues must be a bounded sample array")
    samples: list[dict[str, object]] = []
    previous = -1
    for index, issue in enumerate(issues):
        if not isinstance(issue, dict):
            raise ReportError(f"issues[{index}] must be an object")
        require_exact_fields(issue, ISSUE_SAMPLE_FIELDS, f"issues[{index}]")
        ordinal = require_u64(issue.get("ordinal"), f"issues[{index}].ordinal")
        if ordinal <= previous or ordinal >= entry_count:
            raise ReportError("issue sample ordinal is invalid")
        reasons = validate_sample_reasons(
            issue.get("sample_reasons"), f"issues[{index}].sample_reasons"
        )
        canonical_issue_record(issue, f"issues[{index}]")
        is_error = (
            issue.get("resolved") is not True
            or issue.get("severity") in ("IO", "UNSAFE")
        )
        if ("ERROR" in reasons) != is_error:
            raise ReportError("issue ERROR sample reason differs from its semantics")
        samples.append(issue)
        previous = ordinal
    required_first = set(range(min(ISSUE_SAMPLE_EDGE_COUNT, entry_count)))
    required_last = set(
        range(max(0, entry_count - ISSUE_SAMPLE_EDGE_COUNT), entry_count)
    )
    observed = {int(issue["ordinal"]) for issue in samples}
    if not required_first.issubset(observed) or not required_last.issubset(observed):
        raise ReportError("issues omits mandatory RHISS3 edge samples")
    observed_error = 0
    for issue in samples:
        ordinal = int(issue["ordinal"])
        reasons = issue["sample_reasons"]
        assert isinstance(reasons, list)
        if (ordinal in required_first) != ("FIRST" in reasons):
            raise ReportError("issue FIRST reason differs")
        if (ordinal in required_last) != ("LAST" in reasons):
            raise ReportError("issue LAST reason differs")
        if "ERROR" in reasons:
            observed_error += 1
        elif ordinal not in required_first | required_last:
            raise ReportError("non-edge issue sample lacks ERROR reason")
    if observed_error > error_count:
        raise ReportError("sampled issue errors exceed RHISS3 error aggregate")
    if entry_count == len(samples):
        ordered = sorted(samples, key=lambda issue: int(issue["ordinal"]))
        if issue_ledger_hash(ordered) != ledger.get("ledger_hash"):
            raise ReportError("complete RHISS3 samples differ from ledger hash")
        resolved = sum(issue["resolved"] is True for issue in ordered)
        errors = sum(
            issue["resolved"] is not True or issue["severity"] in ("IO", "UNSAFE")
            for issue in ordered
        )
        severities = Counter(str(issue["severity"]) for issue in ordered)
        unresolved_severities = Counter(
            str(issue["severity"]) for issue in ordered if issue["resolved"] is not True
        )
        if (
            resolved != resolved_count
            or len(ordered) - resolved != unresolved_count
            or errors != error_count
            or dict(severities) != by_severity
            or dict(unresolved_severities) != unresolved_by_severity
        ):
            raise ReportError("complete RHISS3 samples differ from aggregates")
    if report.get("exit_code") == 0 and (
        unresolved_count != 0 or error_count != 0
    ):
        raise ReportError("exit 0 has unresolved/error issue aggregates")
    return ledger


def validate_action(
    repair: object,
    index: int,
    collection: str,
    *,
    expected_ordinal: int | None = None,
) -> dict[str, object]:
    if not isinstance(repair, dict):
        raise ReportError(f"{collection}[{index}] must be an object")
    ordinal = require_u64(repair.get("ordinal"), f"{collection}[{index}].ordinal")
    if expected_ordinal is None:
        expected_ordinal = index
    if ordinal != expected_ordinal:
        raise ReportError(
            f"{collection}[{index}].ordinal differs from {expected_ordinal}"
        )
    action_id = repair.get("action_id")
    if (
        not isinstance(action_id, int)
        or isinstance(action_id, bool)
        or action_id not in REPAIR_ACTIONS
    ):
        raise ReportError(f"{collection}[{index}].action_id is not format-3")
    if repair.get("kind") != REPAIR_ACTIONS[action_id]:
        raise ReportError(f"{collection}[{index}] action ID/name mapping differs")
    require_bounded_utf8(
        repair.get("target"),
        f"{collection}[{index}].target",
        MAX_ACTION_TARGET_BYTES,
    )
    require_u64(repair.get("offset"), f"{collection}[{index}].offset")
    length = require_u64(repair.get("length"), f"{collection}[{index}].length")
    if length == 0:
        raise ReportError(f"{collection}[{index}].length must be nonzero")
    before_hash = repair.get("before_hash")
    after_hash = repair.get("after_hash")
    if not isinstance(before_hash, str) or not HASH.fullmatch(before_hash):
        raise ReportError(f"{collection}[{index}].before_hash is not SHA-256")
    if not isinstance(after_hash, str) or not HASH.fullmatch(after_hash):
        raise ReportError(f"{collection}[{index}].after_hash is not SHA-256")
    if before_hash == after_hash:
        raise ReportError(f"{collection}[{index}] records a no-op write")
    verified = require_bool(repair.get("verified"), f"{collection}[{index}].verified")
    write_boundaries = require_u64(
        repair.get("write_boundaries"), f"{collection}[{index}].write_boundaries"
    )
    if verified != bool(write_boundaries):
        raise ReportError(
            f"{collection}[{index}] verification/write-boundary evidence differs"
        )
    return repair


def repair_ledger_hash(repairs: list[dict[str, object]]) -> str:
    """Hash one complete ordered physical-action ledger."""

    digest = hashlib.sha256()
    digest.update(REPAIR_LEDGER_MAGIC)
    digest.update(struct.pack("<I", 3))
    digest.update(struct.pack("<Q", len(repairs)))
    for local_ordinal, repair in enumerate(repairs):
        digest.update(
            struct.pack(
                "<QIQQ",
                local_ordinal,
                int(repair["action_id"]),
                int(repair["offset"]),
                int(repair["length"]),
            )
        )
        digest.update(bytes.fromhex(str(repair["before_hash"])))
        digest.update(bytes.fromhex(str(repair["after_hash"])))
    return digest.hexdigest()


def validate_action_maps(
    transaction: dict[str, object], index: int, entry_count: int, target_bytes: int
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
    count_ids = transaction.get("by_action_id")
    count_kinds = transaction.get("by_kind")
    byte_ids = transaction.get("bytes_by_action_id")
    byte_kinds = transaction.get("bytes_by_kind")
    if not all(
        isinstance(value, dict)
        for value in (count_ids, count_kinds, byte_ids, byte_kinds)
    ):
        raise ReportError(f"transactions[{index}] action count/byte maps must be objects")
    assert isinstance(count_ids, dict) and isinstance(count_kinds, dict)
    assert isinstance(byte_ids, dict) and isinstance(byte_kinds, dict)
    valid_ids = {str(value) for value in REPAIR_ACTIONS}
    for name, mapping in (
        ("by_action_id", count_ids),
        ("bytes_by_action_id", byte_ids),
    ):
        if any(
            key not in valid_ids
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
            for key, value in mapping.items()
        ):
            raise ReportError(f"transactions[{index}].{name} is invalid")
    for name, mapping in (("by_kind", count_kinds), ("bytes_by_kind", byte_kinds)):
        if any(
            key not in REPAIR_KINDS
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
            for key, value in mapping.items()
        ):
            raise ReportError(f"transactions[{index}].{name} is invalid")
    if set(count_ids) != set(byte_ids):
        raise ReportError(f"transactions[{index}] action count/byte ID sets differ")
    if set(count_kinds) != set(byte_kinds):
        raise ReportError(f"transactions[{index}] action count/byte kind sets differ")
    if sum(count_ids.values()) != entry_count or sum(count_kinds.values()) != entry_count:
        raise ReportError(f"transactions[{index}] action counts differ from entry_count")
    if sum(byte_ids.values()) != target_bytes or sum(byte_kinds.values()) != target_bytes:
        raise ReportError(f"transactions[{index}] action bytes differ from target_bytes")
    mapped_counts = {
        REPAIR_ACTIONS[int(action_id)]: count for action_id, count in count_ids.items()
    }
    mapped_bytes = {
        REPAIR_ACTIONS[int(action_id)]: count for action_id, count in byte_ids.items()
    }
    if mapped_counts != count_kinds or mapped_bytes != byte_kinds:
        raise ReportError(f"transactions[{index}] action ID/name maps differ")
    return count_ids, count_kinds, byte_ids, byte_kinds


def validate_repair_samples(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        raise ReportError("repairs must be a bounded sample array")
    if len(raw) > REPAIR_SAMPLE_LIMIT:
        raise ReportError("repairs exceeds the format-3 sample limit")
    samples: list[dict[str, object]] = []
    previous = -1
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ReportError(f"repairs[{index}] must be an object")
        require_exact_fields(item, REPAIR_SAMPLE_FIELDS, f"repairs[{index}]")
        ordinal = require_u64(item.get("ordinal"), f"repairs[{index}].ordinal")
        if ordinal <= previous:
            raise ReportError("repair sample ordinals are not strictly increasing")
        sample = validate_action(
            item, index, "repairs", expected_ordinal=ordinal
        )
        reasons = sample.get("sample_reasons")
        if (
            not isinstance(reasons, list)
            or not reasons
            or reasons != sorted(set(reasons))
            or any(reason not in ("ERROR", "FIRST", "LAST") for reason in reasons)
        ):
            raise ReportError(f"repairs[{index}].sample_reasons is invalid")
        samples.append(sample)
        previous = ordinal
    return samples


def maximum_report_envelope() -> bytes:
    """Serialize the fixed worst-case production report arena model."""

    maximum_u64 = (1 << 64) - 1
    escaped_target = "\0" * MAX_ACTION_TARGET_BYTES
    escaped_path = "\0" * MAX_ISSUE_PATH_BYTES
    escaped_message = "\0" * MAX_ISSUE_MESSAGE_BYTES
    predicate = "\0" * MAX_ISSUE_PREDICATE_BYTES
    action_maps = {str(action_id): maximum_u64 for action_id in REPAIR_ACTIONS}
    kind_maps = {kind: maximum_u64 for kind in REPAIR_KINDS}
    repair_slot = {
        "ordinal": maximum_u64,
        "sample_reasons": ["ERROR", "FIRST", "LAST"],
        "action_id": 25,
        "kind": REPAIR_ACTIONS[25],
        "target": escaped_target,
        "offset": maximum_u64,
        "length": maximum_u64,
        "before_hash": "f" * 64,
        "after_hash": "e" * 64,
        "verified": True,
        "write_boundaries": maximum_u64,
    }
    batch_slot = {
        "ordinal": maximum_u64,
        "sample_reasons": ["ERROR", "FIRST", "LAST"],
        "phase": "METADATA_REPAIR",
        "origin": "RECOVERED_COMMITTED",
        "transaction_uuid": "ffffffff-ffff-4fff-bfff-ffffffffffff",
        "plan_hash": "f" * 64,
        "repair_ledger_hash": "e" * 64,
        "entry_count": maximum_u64,
        "target_bytes": maximum_u64,
        "last_verified_ordinal": maximum_u64,
        "syncs": maximum_u64,
        "write_boundaries": maximum_u64,
        "by_action_id": action_maps,
        "by_kind": kind_maps,
        "bytes_by_action_id": action_maps,
        "bytes_by_kind": kind_maps,
        "commit_started": True,
        "commit_completed": True,
        "rollback_completed": False,
        "rollback_readback_verified": False,
        "rollback_restored_entries": 0,
        "rollback_restored_bytes": 0,
        "rollback_syncs": 0,
        "rollback_write_boundaries": 0,
        "result": "accepted",
        "rescan_digest": "d" * 64,
        "post_coverage_ledger_hash": "c" * 64,
        "post_diagnosis_hash": "b" * 64,
        # The value reserves the complete bounded JSON rescan slot; the key is
        # the exact public format-3 sample key.
        "rescan": "x" * MAX_RESCAN_SAMPLE_JSON_BYTES,
    }
    wal_slot = {
        "ordinal": maximum_u64,
        "sample_reasons": ["ERROR", "FIRST", "LAST"],
        "kind": "state-transition",
        "extent_offset": maximum_u64,
        "length": maximum_u64,
        "slot": 1,
        "transaction_ordinal": maximum_u64 - 1,
        "transaction_uuid": "ffffffff-ffff-4fff-bfff-ffffffffffff",
        "from_state": "COMMITTED",
        "to_state": "EMPTY",
        "before_hash": "f" * 64,
        "after_hash": "e" * 64,
        "sync_ordinal": maximum_u64,
        "sync_completed": True,
        "readback_verified": True,
        "write_boundaries": maximum_u64,
    }
    issue_slot = {
        "ordinal": maximum_u64,
        "sample_reasons": ["ERROR", "FIRST", "LAST"],
        "code": "\0" * MAX_ISSUE_CODE_BYTES,
        "pass": "\0" * MAX_ISSUE_PASS_BYTES,
        "message": escaped_message,
        "severity": "UNSAFE",
        "resolved": False,
        "record": maximum_u64 - 1,
        "offset": maximum_u64 - 1,
        "path": escaped_path,
        "policy": "CONDITIONAL",
        "required_predicates": [predicate] * MAX_ISSUE_PREDICATES,
        "failed_predicates": [predicate] * MAX_ISSUE_PREDICATES,
        "action_ordinals": list(range(MAX_ISSUE_ACTION_ORDINALS)),
    }
    envelope = {
        "fixed_report_slot": "x" * FIXED_REPORT_ENVELOPE_BYTES,
        "repair_samples": [repair_slot] * REPAIR_SAMPLE_LIMIT,
        "batch_samples": [batch_slot] * BATCH_SAMPLE_LIMIT,
        "wal_action_samples": [wal_slot] * WAL_ACTION_SAMPLE_LIMIT,
        "issue_samples": [issue_slot] * ISSUE_SAMPLE_LIMIT,
    }
    require_exact_fields(repair_slot, REPAIR_SAMPLE_FIELDS, "max.repair_sample")
    require_exact_fields(batch_slot, BATCH_SAMPLE_FIELDS, "max.batch_sample")
    require_exact_fields(
        wal_slot, WAL_ACTION_SAMPLE_FIELDS, "max.wal_action_sample"
    )
    require_exact_fields(issue_slot, ISSUE_SAMPLE_FIELDS, "max.issue_sample")
    return json.dumps(
        envelope,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def maximum_fixed_report_fields() -> bytes:
    """Serialize every non-sample field at its independently enforced bound."""

    maximum_u64 = (1 << 64) - 1
    escaped_path = "\0" * MAX_DEVICE_PATH_BYTES
    count_ids = {str(action_id): maximum_u64 for action_id in REPAIR_ACTIONS}
    count_kinds = {kind: maximum_u64 for kind in REPAIR_KINDS}
    coverage: dict[str, object] = {
        "complete": True,
        "ledger_hash": "f" * 64,
        "io_errors": maximum_u64,
        "skipped": maximum_u64,
    }
    for group_name, counter_names in COVERAGE_COUNTER_GROUPS:
        coverage[group_name] = {
            counter: maximum_u64 for counter in counter_names
        }
    fixed_system = coverage["fixed_system"]
    assert isinstance(fixed_system, dict)
    fixed_system["checks"] = [
        {
            "id": f"{index:02d}." + "x" * (MAX_COVERAGE_CHECK_ID_BYTES - 3),
            "result": "UNREADABLE",
        }
        for index in range(len(REQUIRED_FIXED_SYSTEM_CHECK_IDS))
    ]
    execution = {
        "role": "SELF_EXEC_RESCAN",
        "exec_id": "ffffffff-ffff-4fff-bfff-ffffffffffff",
        "pid": (1 << 32) - 1,
        "parent_pid": (1 << 32) - 1,
        "binary_sha256": "f" * 64,
        "transport": "SELF_EXEC_PIPE_V1",
        "pipe_payload_bytes": MAX_RESCAN_PIPE_PAYLOAD,
        "transport_exit_status": (1 << 32) - 1,
        "timeout_ms": MAX_RESCAN_TIMEOUT_MS,
        "timed_out": True,
        "device_fd_inherited": False,
        "report_fd_inherited": False,
    }
    rescan_snapshot = {
        "ordinal": maximum_u64,
        "stage": "POST_METADATA",
        "binding": "TRANSACTION",
        "transaction_uuid": "ffffffff-ffff-4fff-bfff-ffffffffffff",
        "plan_hash": "f" * 64,
        "completed": True,
        "scan_id": "ffffffff-ffff-4fff-bfff-ffffffffffff",
        "execution": execution,
        "fresh_process": True,
        "read_only": True,
        "exit_code": 5,
        "result": "internal-error",
        "dirty": True,
        "logfile_clean": False,
        "native_log_state": "REPLAY_PLANNED",
        "identity_valid": False,
        "coverage": coverage,
    }
    initial_snapshot = {
        name: value
        for name, value in rescan_snapshot.items()
        if name in SNAPSHOT_FIELDS
    }
    native_log: dict[str, object] = {"checked": True}
    for field in NATIVE_LOG_FIELDS - {"checked"}:
        if field == "state":
            native_log[field] = "REPLAY_PLANNED"
        elif field in ("version_major", "version_minor"):
            native_log[field] = (1 << 16) - 1
        elif field == "pages_expected" or field in NATIVE_LOG_U32_FIELDS:
            native_log[field] = (1 << 32) - 1
        else:
            native_log[field] = maximum_u64
    foundation_repairs = []
    peer_pairs = (
        (1, "BACKUP", "PRIMARY"),
        (2, "PRIMARY", "BACKUP"),
        (3, "MFT_MIRROR", "MFT_PRIMARY"),
        (4, "MFT_PRIMARY", "MFT_MIRROR"),
    )
    for ordinal, (action_id, source_peer, target_peer) in enumerate(peer_pairs):
        foundation_repairs.append(
            {
                "ordinal": ordinal,
                "action_id": action_id,
                "kind": REPAIR_ACTIONS[action_id],
                "target": "\0" * MAX_ACTION_TARGET_BYTES,
                "offset": maximum_u64,
                "length": maximum_u64,
                "before_hash": "f" * 64,
                "after_hash": "e" * 64,
                "verified": True,
                "write_boundaries": maximum_u64,
                "sync_ordinal": ordinal + 1,
                "sync_completed": True,
                "readback_verified": True,
                "authority": {
                    "source_peer": source_peer,
                    "target_peer": target_peer,
                    "source_strict_valid": True,
                    "source_expected_bound": True,
                    "target_status": "READABLE_STRUCTURALLY_INVALID",
                    "sole_valid_peer": True,
                    "conflicting_valid_peer": False,
                },
            }
        )
    batch_ledger = {
        "format": BATCH_LEDGER_FORMAT,
        "record_count": maximum_u64,
        "ledger_hash": "f" * 64,
        "foundation_count": 1,
        "new_count": maximum_u64,
        "recovered_committed_count": maximum_u64,
        "recovered_rolled_back_count": maximum_u64,
        "metadata_count": maximum_u64,
        "dirty_clear_count": 1,
        "accepted_count": maximum_u64,
        "refused_count": maximum_u64,
        "rolled_back_count": maximum_u64,
        "priority_count": maximum_u64,
        "rescan_count": maximum_u64,
        "commit_started_count": maximum_u64,
        "commit_completed_count": maximum_u64,
        "verified_entries": maximum_u64,
        "rollback_restored_entries": maximum_u64,
        "rollback_restored_bytes": maximum_u64,
        "rollback_syncs": maximum_u64,
        "rollback_write_boundaries": maximum_u64,
        "entry_count": maximum_u64,
        "target_bytes": maximum_u64,
        "syncs": maximum_u64,
        "write_boundaries": maximum_u64,
        "by_action_id": count_ids,
        "by_kind": count_kinds,
        "bytes_by_action_id": count_ids,
        "bytes_by_kind": count_kinds,
        "dirty_set_action_count": 2,
        "dirty_set_phase_ordinal": maximum_u64,
        "dirty_clear_action_count": 2,
        "dirty_clear_phase_ordinal": maximum_u64,
        "native_redo_count": maximum_u64,
        "native_restart_count": 2,
        "native_phase_ordinal": maximum_u64,
        "first_metadata_ordinal": maximum_u64,
        "first_phase": "FOUNDATION",
        "last_phase": "DIRTY_CLEAR",
        "final_rescan_digest": "f" * 64,
        "final_coverage_ledger_hash": "f" * 64,
        "final_diagnosis_hash": "f" * 64,
    }
    wal_ledger = {
        "format": WAL_LEDGER_FORMAT,
        "entry_count": maximum_u64,
        "ledger_hash": "f" * 64,
        "total_bytes": maximum_u64,
        "syncs": maximum_u64,
        "write_boundaries": maximum_u64,
        "by_kind": {
            kind: maximum_u64 for kind in WAL_ACTION_KIND_CODES
        },
        "bytes_by_kind": {
            kind: maximum_u64 for kind in WAL_ACTION_KIND_CODES
        },
        "syncs_by_kind": {
            kind: maximum_u64 for kind in WAL_ACTION_KIND_CODES
        },
        "boundaries_by_kind": {
            kind: maximum_u64 for kind in WAL_ACTION_KIND_CODES
        },
        "first_kind": WAL_ACTION_KINDS[0],
        "last_kind": WAL_ACTION_KINDS[-1],
        "error_count": maximum_u64,
    }
    issue_ledger = {
        "format": ISSUE_LEDGER_FORMAT,
        "entry_count": maximum_u64,
        "ledger_hash": "f" * 64,
        "resolved_count": maximum_u64,
        "unresolved_count": maximum_u64,
        "error_count": maximum_u64,
        "by_severity": {
            severity: maximum_u64 for severity in ISSUE_SEVERITY_CODES
        },
        "unresolved_by_severity": {
            severity: maximum_u64 for severity in ISSUE_SEVERITY_CODES
        },
        "first_severity": "INFO",
        "last_severity": "UNSAFE",
    }
    report_budget: dict[str, object] = {
        "limit_bytes": REPORT_SIZE_LIMIT,
        "reservation_method": REPORT_RESERVATION_METHOD,
        "reserved_bytes": REPORT_SIZE_LIMIT,
        "reserved_before_mutation": True,
        "fixed_buffers_allocated_before_mutation": True,
        "envelope_frozen_before_mutation": True,
        "every_committed_batch_preflighted_before_its_commit": True,
        "future_batches_envelope_constrained": True,
        "worst_case_bytes": REPORT_SIZE_LIMIT,
        "written_bytes": REPORT_SIZE_LIMIT,
        "size_proof_format": "RHSIZE3",
        "size_proof_hash": "f" * 64,
    }
    for prefix, limit in (
        ("repair", REPAIR_SAMPLE_LIMIT),
        ("batch", BATCH_SAMPLE_LIMIT),
        ("wal_action", WAL_ACTION_SAMPLE_LIMIT),
        ("issue", ISSUE_SAMPLE_LIMIT),
    ):
        report_budget[f"{prefix}_samples_limit"] = limit
        report_budget[f"{prefix}_samples_emitted"] = limit
        report_budget[f"{prefix}_samples_omitted"] = maximum_u64
        report_budget[f"{prefix}_priority_emitted"] = limit
        report_budget[f"{prefix}_priority_omitted"] = maximum_u64
    fixed = {
        "format": 3,
        "checker": "roothealth",
        "checker_version": "v" * MAX_VERSION_TEXT_BYTES,
        "mode": "repair",
        "result": "internal-error",
        "exit_code": 5,
        "device": {
            "requested_path": escaped_path,
            "resolved_path": escaped_path,
            "requested_was_symlink": True,
            "resolved_type": "block",
            "requested_dev": str(maximum_u64),
            "requested_ino": str(maximum_u64),
            "resolved_dev": str(maximum_u64),
            "resolved_ino": str(maximum_u64),
            "resolved_major": (1 << 32) - 1,
            "resolved_minor": (1 << 32) - 1,
            "mapper_name": "\0" * MAX_MAPPER_NAME_BYTES,
            "selection_proven": True,
        },
        "identity": {
            "prewrite_checked": True,
            "prewrite_valid": True,
            "expected_serial": "\0" * MAX_SERIAL_TEXT_BYTES,
            "observed_primary_serial": "\0" * MAX_SERIAL_TEXT_BYTES,
            "observed_backup_serial": "\0" * MAX_SERIAL_TEXT_BYTES,
            "expected_label": "\0" * MAX_IDENTITY_TEXT_BYTES,
            "observed_label": "\0" * MAX_IDENTITY_TEXT_BYTES,
            "anchor": "\0" * MAX_IDENTITY_TEXT_BYTES,
        },
        "initial": initial_snapshot,
        "final": rescan_snapshot,
        "native_log": native_log,
        "foundation_repairs": foundation_repairs,
        "plan": {
            "operations": maximum_u64,
            "bytes": maximum_u64,
            "priority_operations": maximum_u64,
            "foundation_operations": 4,
            "foundation_bytes": maximum_u64,
            "wal_operations": maximum_u64,
            "wal_bytes": maximum_u64,
            "by_action_id": count_ids,
            "by_kind": count_kinds,
            "bytes_by_action_id": count_ids,
            "bytes_by_kind": count_kinds,
        },
        "commit": {
            "started": True,
            "completed": True,
            "last_verified_ordinal": maximum_u64,
            "syncs": maximum_u64,
            "write_boundaries": maximum_u64,
        },
        "batch_ledger": batch_ledger,
        "batch_samples": [],
        "repairs": [],
        "wal": {
            "checked": True,
            "present": True,
            "valid": True,
            "state": "ROLLBACK",
            "generation": maximum_u64,
            "recovery_required": True,
            "recovered": True,
            "journal_uuid": "ffffffff-ffff-4fff-bfff-ffffffffffff",
            "volume_serial": "0xffffffffffffffff",
            "transaction_kind": "METADATA_REPAIR",
            "max_entry_count": (1 << 32) - 1,
            "fast_path_trusted": True,
            "fallback_attempted": True,
            "fallback_ambiguous": True,
            "unreadable_record_count": maximum_u64,
            "definite_duplicate_count": maximum_u64,
            "write_boundaries": maximum_u64,
            "action_ledger": wal_ledger,
            "actions": [],
        },
        "issue_ledger": issue_ledger,
        "issues": [],
        "report_budget": report_budget,
        "dirty_cleared": True,
    }
    require_exact_fields(fixed, TOP_LEVEL_FIELDS, "max.report")
    require_exact_fields(fixed["device"], DEVICE_FIELDS, "max.device")
    require_exact_fields(fixed["identity"], IDENTITY_FIELDS, "max.identity")
    require_exact_fields(fixed["initial"], SNAPSHOT_FIELDS, "max.initial")
    require_exact_fields(fixed["final"], RESCAN_FIELDS, "max.final")
    require_exact_fields(fixed["plan"], PLAN_FIELDS, "max.plan")
    require_exact_fields(fixed["commit"], COMMIT_FIELDS, "max.commit")
    require_exact_fields(fixed["wal"], WAL_FIELDS, "max.wal")
    for index, action in enumerate(foundation_repairs):
        require_exact_fields(
            action, FOUNDATION_ACTION_FIELDS, f"max.foundation[{index}]"
        )
        authority = action["authority"]
        assert isinstance(authority, dict)
        require_exact_fields(
            authority,
            FOUNDATION_AUTHORITY_FIELDS,
            f"max.foundation[{index}].authority",
        )
    return json.dumps(
        fixed,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


MAX_REPORT_ENVELOPE = maximum_report_envelope()
MAX_REPORT_ENVELOPE_BYTES = len(MAX_REPORT_ENVELOPE)
MAX_REPORT_ENVELOPE_HASH = hashlib.sha256(MAX_REPORT_ENVELOPE).hexdigest()
MAX_FIXED_REPORT_FIELDS = maximum_fixed_report_fields()
MAX_FIXED_REPORT_FIELDS_BYTES = len(MAX_FIXED_REPORT_FIELDS)
MAX_FIXED_REPORT_FIELDS_HASH = hashlib.sha256(MAX_FIXED_REPORT_FIELDS).hexdigest()


def report_size_proof_hash() -> str:
    values = (
        REPORT_SIZE_LIMIT,
        MAX_REPORT_ENVELOPE_BYTES,
        REPAIR_SAMPLE_LIMIT,
        REPAIR_SAMPLE_EDGE_COUNT,
        BATCH_SAMPLE_LIMIT,
        BATCH_SAMPLE_EDGE_COUNT,
        WAL_ACTION_SAMPLE_LIMIT,
        WAL_ACTION_SAMPLE_EDGE_COUNT,
        ISSUE_SAMPLE_LIMIT,
        ISSUE_SAMPLE_EDGE_COUNT,
        MAX_ACTION_TARGET_BYTES,
        MAX_ISSUE_CODE_BYTES,
        MAX_ISSUE_PASS_BYTES,
        MAX_ISSUE_PATH_BYTES,
        MAX_ISSUE_MESSAGE_BYTES,
        MAX_ISSUE_PREDICATES,
        MAX_ISSUE_PREDICATE_BYTES,
        MAX_ISSUE_ACTION_ORDINALS,
        MAX_RESCAN_SAMPLE_JSON_BYTES,
        FIXED_REPORT_ENVELOPE_BYTES,
        MAX_JSON_ESCAPE_EXPANSION,
        MAX_DEVICE_PATH_BYTES,
        MAX_MAPPER_NAME_BYTES,
        MAX_VERSION_TEXT_BYTES,
        MAX_IDENTITY_TEXT_BYTES,
        MAX_SERIAL_TEXT_BYTES,
        MAX_COVERAGE_CHECK_ID_BYTES,
        MAX_FIXED_REPORT_FIELDS_BYTES,
    )
    digest = hashlib.sha256()
    digest.update(REPORT_BUDGET_MAGIC)
    digest.update(struct.pack("<I", 3))
    for value in values:
        digest.update(struct.pack("<Q", value))
    digest.update(bytes.fromhex(MAX_REPORT_ENVELOPE_HASH))
    digest.update(bytes.fromhex(MAX_FIXED_REPORT_FIELDS_HASH))
    return digest.hexdigest()


def validate_serialized_report_size(payload: bytes) -> None:
    if len(payload) > REPORT_SIZE_LIMIT:
        raise ReportError("report exceeds the 4 MiB qualification ceiling")


def validate_fixed_report_size(payload: bytes) -> None:
    if len(payload) > FIXED_REPORT_ENVELOPE_BYTES:
        raise ReportError("non-sample report fields exceed the fixed 128 KiB slot")


def omitted_fixed_field_overflow_fixture() -> bytes:
    fixed = json.loads(MAX_FIXED_REPORT_FIELDS)
    fixed["omitted_fixed_field"] = ""
    empty = json.dumps(
        fixed,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    padding = FIXED_REPORT_ENVELOPE_BYTES + 1 - len(empty)
    if padding < 0:
        raise ReportError("fixed-field overflow fixture has no padding headroom")
    fixed["omitted_fixed_field"] = "x" * padding
    encoded = json.dumps(
        fixed,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) != FIXED_REPORT_ENVELOPE_BYTES + 1:
        raise ReportError("fixed-field overflow fixture is not exactly one byte over")
    return encoded


def validate_report_budget(
    report: dict[str, object], actual_bytes: int | None = None
) -> None:
    budget = report.get("report_budget")
    if not isinstance(budget, dict):
        raise ReportError("report_budget must be an object")
    exact_fields = {
        "limit_bytes",
        "reservation_method",
        "reserved_bytes",
        "reserved_before_mutation",
        "fixed_buffers_allocated_before_mutation",
        "envelope_frozen_before_mutation",
        "every_committed_batch_preflighted_before_its_commit",
        "future_batches_envelope_constrained",
        "worst_case_bytes",
        "written_bytes",
        "size_proof_format",
        "size_proof_hash",
    }
    for prefix in ("repair", "batch", "wal_action", "issue"):
        exact_fields.update(
            {
                f"{prefix}_samples_limit",
                f"{prefix}_samples_emitted",
                f"{prefix}_samples_omitted",
                f"{prefix}_priority_emitted",
                f"{prefix}_priority_omitted",
            }
        )
    if set(budget) != exact_fields:
        raise ReportError("report_budget field set differs from format 3")
    if (
        budget.get("limit_bytes") != REPORT_SIZE_LIMIT
        or budget.get("reservation_method") != REPORT_RESERVATION_METHOD
        or budget.get("reserved_bytes") != REPORT_SIZE_LIMIT
    ):
        raise ReportError("report reservation differs from the fixed 4 MiB arena")
    for field in (
        "reserved_before_mutation",
        "fixed_buffers_allocated_before_mutation",
        "envelope_frozen_before_mutation",
        "every_committed_batch_preflighted_before_its_commit",
        "future_batches_envelope_constrained",
    ):
        if budget.get(field) is not True:
            raise ReportError(f"report_budget.{field} is not attested")
    if budget.get("worst_case_bytes") != MAX_REPORT_ENVELOPE_BYTES:
        raise ReportError("report worst-case envelope differs from the frozen vector")
    if budget.get("size_proof_format") != "RHSIZE3":
        raise ReportError("report size-proof format differs")
    if budget.get("size_proof_hash") != report_size_proof_hash():
        raise ReportError("report size-proof hash differs")
    written = require_u64(budget.get("written_bytes"), "report_budget.written_bytes")
    if not 0 < written <= MAX_REPORT_ENVELOPE_BYTES <= REPORT_SIZE_LIMIT:
        raise ReportError("report budget byte bounds are invalid")
    if actual_bytes is not None and written != actual_bytes:
        raise ReportError("report_budget.written_bytes differs from the report file")
    plan = report.get("plan")
    batch_ledger = report.get("batch_ledger")
    wal = report.get("wal")
    issue_ledger = report.get("issue_ledger")
    if (
        not isinstance(plan, dict)
        or not isinstance(batch_ledger, dict)
        or not isinstance(wal, dict)
        or not isinstance(wal.get("action_ledger"), dict)
        or not isinstance(issue_ledger, dict)
    ):
        raise ReportError("report budget lacks bounded ledger aggregates")
    sources = {
        "repair": (
            REPAIR_SAMPLE_LIMIT,
            report.get("repairs"),
            plan.get("wal_operations"),
            plan.get("priority_operations"),
        ),
        "batch": (
            BATCH_SAMPLE_LIMIT,
            report.get("batch_samples"),
            batch_ledger.get("record_count"),
            batch_ledger.get("priority_count"),
        ),
        "wal_action": (
            WAL_ACTION_SAMPLE_LIMIT,
            wal.get("actions"),
            wal["action_ledger"].get("entry_count"),
            wal["action_ledger"].get("error_count"),
        ),
        "issue": (
            ISSUE_SAMPLE_LIMIT,
            report.get("issues"),
            issue_ledger.get("entry_count"),
            issue_ledger.get("error_count"),
        ),
    }
    for prefix, (limit, samples, total_value, priority_value) in sources.items():
        if budget.get(f"{prefix}_samples_limit") != limit:
            raise ReportError(f"report {prefix} sample limit differs")
        if not isinstance(samples, list):
            raise ReportError(f"report {prefix} samples are absent")
        total = require_u64(total_value, f"{prefix} sample total")
        priority_total = require_u64(priority_value, f"{prefix} priority total")
        emitted = require_u64(
            budget.get(f"{prefix}_samples_emitted"),
            f"report_budget.{prefix}_samples_emitted",
        )
        omitted = require_u64(
            budget.get(f"{prefix}_samples_omitted"),
            f"report_budget.{prefix}_samples_omitted",
        )
        priority_emitted = require_u64(
            budget.get(f"{prefix}_priority_emitted"),
            f"report_budget.{prefix}_priority_emitted",
        )
        priority_omitted = require_u64(
            budget.get(f"{prefix}_priority_omitted"),
            f"report_budget.{prefix}_priority_omitted",
        )
        observed_priority = sum(
            isinstance(sample, dict)
            and "ERROR" in sample.get("sample_reasons", [])
            for sample in samples
        )
        if emitted != len(samples) or emitted + omitted != total:
            raise ReportError(f"report {prefix} sample totals do not reconcile")
        if (
            priority_emitted != observed_priority
            or priority_emitted + priority_omitted != priority_total
        ):
            raise ReportError(f"report {prefix} priority totals do not reconcile")


def _sample_action_maps(
    action_id: int, count: int, byte_count: int
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
    kind = REPAIR_ACTIONS[action_id]
    return (
        {str(action_id): count},
        {kind: count},
        {str(action_id): byte_count},
        {kind: byte_count},
    )


def _batch_vector_record(
    ordinal: int,
    *,
    result: str = "accepted",
    origin: str = "NEW",
    action_id: int = 23,
    rescan: dict[str, object] | None = None,
) -> dict[str, object]:
    if rescan is None and result != "refused":
        rescan = {"result": "unsafe", "ordinal": ordinal}
    count_ids, count_kinds, byte_ids, byte_kinds = _sample_action_maps(
        action_id, 1, 512
    )
    started = result != "refused"
    completed = result == "accepted"
    rolled_back = result == "rolled-back"
    return {
        "ordinal": ordinal,
        "phase": "METADATA_REPAIR",
        "origin": origin,
        "transaction_uuid": f"10000000-0000-4000-8000-{ordinal + 1:012x}",
        "plan_hash": "a" * 64,
        "repair_ledger_hash": "b" * 64,
        "entry_count": 1,
        "target_bytes": 512,
        "by_action_id": count_ids,
        "by_kind": count_kinds,
        "bytes_by_action_id": byte_ids,
        "bytes_by_kind": byte_kinds,
        "commit_started": started,
        "commit_completed": completed,
        "rollback_completed": rolled_back,
        "rollback_readback_verified": rolled_back,
        "rollback_restored_entries": 1 if rolled_back else 0,
        "rollback_restored_bytes": 512 if rolled_back else 0,
        "rollback_syncs": 1 if rolled_back else 0,
        "rollback_write_boundaries": 2 if rolled_back else 0,
        "last_verified_ordinal": 1 if started else 0,
        "syncs": 1 if completed else 0,
        "write_boundaries": 2 if completed else 0,
        "result": result,
        "rescan_digest": (
            canonical_snapshot_digest(rescan, "batch vector rescan")
            if rescan is not None
            else None
        ),
        "post_coverage_ledger_hash": "c" * 64 if rescan is not None else None,
        "post_diagnosis_hash": "d" * 64 if rescan is not None else None,
        "rescan": rescan,
    }


def schema_closure_self_test() -> tuple[int, int]:
    """Prove unknown fields and integer overflows cannot escape RHSIZE3."""

    fixed = json.loads(MAX_FIXED_REPORT_FIELDS)
    envelope = json.loads(MAX_REPORT_ENVELOPE)
    unknown_payload = "\0" * (
        REPORT_SIZE_LIMIT - MAX_REPORT_ENVELOPE_BYTES + 1
    )
    field_cases: list[tuple[str, dict[str, object], set[str]]] = [
        ("top", fixed, TOP_LEVEL_FIELDS),
        ("device", fixed["device"], DEVICE_FIELDS),
        ("identity", fixed["identity"], IDENTITY_FIELDS),
        ("snapshot", fixed["initial"], SNAPSHOT_FIELDS),
        ("plan", fixed["plan"], PLAN_FIELDS),
        ("commit", fixed["commit"], COMMIT_FIELDS),
        ("wal", fixed["wal"], WAL_FIELDS),
        (
            "foundation",
            fixed["foundation_repairs"][0],
            FOUNDATION_ACTION_FIELDS,
        ),
        (
            "foundation-authority",
            fixed["foundation_repairs"][0]["authority"],
            FOUNDATION_AUTHORITY_FIELDS,
        ),
        ("repair-sample", envelope["repair_samples"][0], REPAIR_SAMPLE_FIELDS),
        ("batch-sample", envelope["batch_samples"][0], BATCH_SAMPLE_FIELDS),
        (
            "wal-action-sample",
            envelope["wal_action_samples"][0],
            WAL_ACTION_SAMPLE_FIELDS,
        ),
        ("issue-sample", envelope["issue_samples"][0], ISSUE_SAMPLE_FIELDS),
    ]
    field_negatives = 0
    for name, source, expected in field_cases:
        candidate = copy.deepcopy(source)
        candidate["unknown_format3_field"] = unknown_payload
        try:
            require_exact_fields(candidate, expected, f"schema.{name}")
        except ReportError:
            field_negatives += 1
        else:
            raise ReportError(f"schema closure accepted unknown {name} field")

    numeric_negatives = 0

    def must_reject(name: str, callback: object) -> None:
        nonlocal numeric_negatives
        assert callable(callback)
        try:
            callback()
        except (ReportError, OverflowError):
            numeric_negatives += 1
            return
        raise ReportError(f"numeric closure accepted {name}")

    must_reject(
        "development-checker",
        lambda: require_release_checker("roothealth-repair-core"),
    )
    valid_device = {
        "requested_path": "/dev/mapper/t1os-root",
        "resolved_path": "/dev/dm-0",
        "requested_was_symlink": True,
        "resolved_type": "block",
        "requested_dev": "1",
        "requested_ino": "2",
        "resolved_dev": "3",
        "resolved_ino": "4",
        "resolved_major": 253,
        "resolved_minor": 0,
        "mapper_name": "t1os-root",
        "selection_proven": True,
    }
    oversized_device = copy.deepcopy(valid_device)
    oversized_device["resolved_major"] = 1 << 32
    must_reject(
        "device-u32",
        lambda: validate_device({"device": oversized_device}),
    )
    oversized_dev_string = copy.deepcopy(valid_device)
    oversized_dev_string["resolved_dev"] = str(1 << 64)
    must_reject(
        "device-decimal-u64",
        lambda: validate_device({"device": oversized_dev_string}),
    )
    execution = {
        "role": "INITIAL",
        "exec_id": "10000000-0000-4000-8000-000000000001",
        "pid": 1 << 32,
        "parent_pid": 1,
        "binary_sha256": "a" * 64,
        "transport": "DIRECT",
        "pipe_payload_bytes": 0,
        "transport_exit_status": None,
        "timeout_ms": None,
        "timed_out": None,
        "device_fd_inherited": False,
        "report_fd_inherited": False,
    }
    must_reject("execution-pid-u32", lambda: validate_execution(execution, "initial.execution"))
    wal = copy.deepcopy(fixed["wal"])
    wal["generation"] = 1 << 64
    must_reject("wal-generation-u64", lambda: wal_object({"wal": wal}))
    repair = copy.deepcopy(envelope["repair_samples"][0])
    repair["ordinal"] = 1 << 64
    must_reject(
        "repair-ordinal-u64",
        lambda: validate_action(repair, 0, "repairs", expected_ordinal=1 << 64),
    )
    batch = _batch_vector_record(0)
    batch["ordinal"] = 1 << 64
    must_reject("batch-ordinal-u64", lambda: canonical_batch_record(batch, "batch"))
    wal_action = copy.deepcopy(envelope["wal_action_samples"][0])
    wal_action["ordinal"] = 1 << 64
    must_reject(
        "wal-action-ordinal-u64",
        lambda: canonical_wal_action(wal_action, "wal-action"),
    )
    issue = copy.deepcopy(envelope["issue_samples"][0])
    issue["ordinal"] = 1 << 64
    must_reject("issue-ordinal-u64", lambda: canonical_issue_record(issue, "issue"))
    return field_negatives, numeric_negatives


def bounded_ledger_self_test() -> int:
    one_batch = _batch_vector_record(0)
    one_batch["sample_reasons"] = ["FIRST", "LAST"]
    one_rescan = one_batch["rescan"]
    assert isinstance(one_rescan, dict)
    batch_hash = batch_ledger_hash([one_batch])
    count_ids, count_kinds, byte_ids, byte_kinds = _sample_action_maps(23, 1, 512)
    batch_ledger = {
        "format": BATCH_LEDGER_FORMAT,
        "record_count": 1,
        "ledger_hash": batch_hash,
        "foundation_count": 0,
        "new_count": 1,
        "recovered_committed_count": 0,
        "recovered_rolled_back_count": 0,
        "metadata_count": 1,
        "dirty_clear_count": 0,
        "accepted_count": 1,
        "refused_count": 0,
        "rolled_back_count": 0,
        "priority_count": 0,
        "rescan_count": 1,
        "commit_started_count": 1,
        "commit_completed_count": 1,
        "verified_entries": 1,
        "rollback_restored_entries": 0,
        "rollback_restored_bytes": 0,
        "rollback_syncs": 0,
        "rollback_write_boundaries": 0,
        "entry_count": 1,
        "target_bytes": 512,
        "syncs": 1,
        "write_boundaries": 2,
        "by_action_id": count_ids,
        "by_kind": count_kinds,
        "bytes_by_action_id": byte_ids,
        "bytes_by_kind": byte_kinds,
        "dirty_set_action_count": 0,
        "dirty_set_phase_ordinal": None,
        "dirty_clear_action_count": 0,
        "dirty_clear_phase_ordinal": None,
        "native_redo_count": 0,
        "native_restart_count": 0,
        "native_phase_ordinal": None,
        "first_metadata_ordinal": 0,
        "first_phase": "METADATA_REPAIR",
        "last_phase": "METADATA_REPAIR",
        "final_rescan_digest": one_batch["rescan_digest"],
        "final_coverage_ledger_hash": "c" * 64,
        "final_diagnosis_hash": "d" * 64,
    }
    validate_batch_ledger(
        {"batch_ledger": batch_ledger, "batch_samples": [one_batch]}
    )
    rollback_batch = _batch_vector_record(
        0,
        result="rolled-back",
        origin="RECOVERED_ROLLED_BACK",
    )
    new_after_rollback = _batch_vector_record(1)
    rollback_batch["sample_reasons"] = ["ERROR", "FIRST", "LAST"]
    new_after_rollback["sample_reasons"] = ["FIRST", "LAST"]
    rollback_hash = batch_ledger_hash([rollback_batch, new_after_rollback])
    rollback_ledger = copy.deepcopy(batch_ledger)
    rollback_ledger.update(
        {
            "record_count": 2,
            "ledger_hash": rollback_hash,
            "new_count": 1,
            "recovered_rolled_back_count": 1,
            "metadata_count": 2,
            "accepted_count": 1,
            "rolled_back_count": 1,
            "priority_count": 1,
            "rescan_count": 2,
            "commit_started_count": 2,
            "commit_completed_count": 1,
            "verified_entries": 2,
            "rollback_restored_entries": 1,
            "rollback_restored_bytes": 512,
            "rollback_syncs": 1,
            "rollback_write_boundaries": 2,
            "entry_count": 2,
            "target_bytes": 1024,
            "syncs": 1,
            "write_boundaries": 2,
            "by_action_id": {"23": 2},
            "by_kind": {"bitmap-cluster": 2},
            "bytes_by_action_id": {"23": 1024},
            "bytes_by_kind": {"bitmap-cluster": 1024},
            "final_rescan_digest": new_after_rollback["rescan_digest"],
        }
    )
    validate_batch_ledger(
        {
            "batch_ledger": rollback_ledger,
            "batch_samples": [rollback_batch, new_after_rollback],
        }
    )

    wal_action = {
        "ordinal": 0,
        "sample_reasons": ["FIRST", "LAST"],
        "kind": "superblock-reconstruct",
        "extent_offset": 8192,
        "length": 4096,
        "slot": 0,
        "transaction_ordinal": None,
        "transaction_uuid": None,
        "from_state": None,
        "to_state": None,
        "before_hash": "1" * 64,
        "after_hash": "2" * 64,
        "sync_ordinal": 1,
        "sync_completed": True,
        "readback_verified": True,
        "write_boundaries": 2,
    }
    wal_hash = wal_ledger_hash([wal_action])
    wal = {
        "write_boundaries": 2,
        "actions": [wal_action],
        "action_ledger": {
            "format": WAL_LEDGER_FORMAT,
            "entry_count": 1,
            "ledger_hash": wal_hash,
            "total_bytes": 4096,
            "syncs": 1,
            "write_boundaries": 2,
            "by_kind": {"superblock-reconstruct": 1},
            "bytes_by_kind": {"superblock-reconstruct": 4096},
            "syncs_by_kind": {"superblock-reconstruct": 1},
            "boundaries_by_kind": {"superblock-reconstruct": 2},
            "first_kind": "superblock-reconstruct",
            "last_kind": "superblock-reconstruct",
            "error_count": 0,
        },
    }
    validate_wal_action_ledger(wal)
    rollback_action = {
        "ordinal": 0,
        "sample_reasons": ["ERROR", "FIRST", "LAST"],
        "kind": "rollback-restore",
        "extent_offset": 16384,
        "length": 512,
        "slot": None,
        "transaction_ordinal": 0,
        "transaction_uuid": rollback_batch["transaction_uuid"],
        "from_state": None,
        "to_state": None,
        "before_hash": "3" * 64,
        "after_hash": "4" * 64,
        "sync_ordinal": 1,
        "sync_completed": True,
        "readback_verified": True,
        "write_boundaries": 2,
    }
    rollback_wal = {
        "write_boundaries": 2,
        "actions": [rollback_action],
        "action_ledger": {
            "format": WAL_LEDGER_FORMAT,
            "entry_count": 1,
            "ledger_hash": wal_ledger_hash([rollback_action]),
            "total_bytes": 512,
            "syncs": 1,
            "write_boundaries": 2,
            "by_kind": {"rollback-restore": 1},
            "bytes_by_kind": {"rollback-restore": 512},
            "syncs_by_kind": {"rollback-restore": 1},
            "boundaries_by_kind": {"rollback-restore": 2},
            "first_kind": "rollback-restore",
            "last_kind": "rollback-restore",
            "error_count": 1,
        },
    }
    validate_wal_action_ledger(rollback_wal)
    validate_wal_batch_reconciliation(
        rollback_wal,
        rollback_ledger,
        [rollback_batch, new_after_rollback],
    )
    preparing_rollback = copy.deepcopy(rollback_batch)
    preparing_rollback.update(
        {
            "commit_started": False,
            "last_verified_ordinal": 0,
            "rollback_restored_entries": 0,
            "rollback_restored_bytes": 0,
            "rollback_syncs": 0,
            "rollback_write_boundaries": 0,
        }
    )
    canonical_batch_record(preparing_rollback, "preparing_rollback")

    issue = {
        "ordinal": 0,
        "sample_reasons": ["FIRST", "LAST"],
        "code": "FIXED",
        "pass": "fixed-system",
        "message": "resolved",
        "severity": "WARNING",
        "resolved": True,
        "record": None,
        "offset": None,
        "path": None,
        "policy": "CONDITIONAL",
        "required_predicates": ["AUTHORITY_EXACT"],
        "failed_predicates": [],
        "action_ordinals": [0],
    }
    issue_hash = issue_ledger_hash([issue])
    issue_report = {
        "exit_code": 0,
        "issues": [issue],
        "issue_ledger": {
            "format": ISSUE_LEDGER_FORMAT,
            "entry_count": 1,
            "ledger_hash": issue_hash,
            "resolved_count": 1,
            "unresolved_count": 0,
            "error_count": 0,
            "by_severity": {"WARNING": 1},
            "unresolved_by_severity": {},
            "first_severity": "WARNING",
            "last_severity": "WARNING",
        },
    }
    validate_issues(issue_report)

    known_vectors = {
        "batch": "23d8419530d2114fcc3155111d04a4ab7839b4bf3b79d8298b03683c874df788",
        "rollback_batch": "a7fdb63c6cf7d9b3bad7bccd6a7a8f473ad4f55386245743bdaae4639e566e7c",
        "wal": "18211ba78c377c0cd96efc9f768994c9b9d7edf50519e3e70265265776958236",
        "issue": "f44cfeecdc8b057c3368c2dc5845592d6d3a5305bb3552041b11af84eb30d705",
        "envelope_bytes": 3_466_470,
        "envelope_hash": "d0f04d213d43dca8fe85d7ec2adbb9efb7cfbe56015f0899f42a82f208ec7ad6",
        "fixed_bytes": 98_927,
        "fixed_hash": "54f41614828eac7d21067812657883c7b299ef0d9021921b904834cfef58fb85",
        "size_proof_hash": "03e7d405abfb81027dddd44ec44c970b7f35221deddaabb55e78ededcf70f8a4",
    }
    observed_vectors = {
        "batch": batch_hash,
        "rollback_batch": rollback_hash,
        "wal": wal_hash,
        "issue": issue_hash,
        "envelope_bytes": MAX_REPORT_ENVELOPE_BYTES,
        "envelope_hash": MAX_REPORT_ENVELOPE_HASH,
        "fixed_bytes": MAX_FIXED_REPORT_FIELDS_BYTES,
        "fixed_hash": MAX_FIXED_REPORT_FIELDS_HASH,
        "size_proof_hash": report_size_proof_hash(),
    }
    if observed_vectors != known_vectors:
        raise ReportError(
            "bounded-ledger known vector drifted: "
            + json.dumps(observed_vectors, sort_keys=True)
        )
    if MAX_REPORT_ENVELOPE_BYTES > REPORT_SIZE_LIMIT:
        raise ReportError("max-envelope known vector exceeds 4 MiB")
    if MAX_FIXED_REPORT_FIELDS_BYTES > FIXED_REPORT_ENVELOPE_BYTES:
        raise ReportError("fixed report fields exceed their reserved 128 KiB slot")
    validate_serialized_report_size(MAX_REPORT_ENVELOPE)
    validate_fixed_report_size(MAX_FIXED_REPORT_FIELDS)
    negative_count = 0

    def must_reject(name: str, callback: object) -> None:
        nonlocal negative_count
        assert callable(callback)
        try:
            callback()
        except ReportError:
            negative_count += 1
            return
        raise ReportError(f"bounded-ledger self-test accepted {name}")

    must_reject(
        "one-byte-report-overflow",
        lambda: validate_serialized_report_size(bytes(REPORT_SIZE_LIMIT + 1)),
    )
    must_reject(
        "one-omitted-fixed-field-overflow",
        lambda: validate_fixed_report_size(omitted_fixed_field_overflow_fixture()),
    )
    missing_rescan = copy.deepcopy(one_batch)
    missing_rescan["rescan"] = None
    must_reject(
        "committed-rescan-omitted",
        lambda: validate_batch_ledger(
            {"batch_ledger": batch_ledger, "batch_samples": [missing_rescan]}
        ),
    )
    bad_dirty = copy.deepcopy(batch_ledger)
    bad_dirty["dirty_set_action_count"] = 2
    bad_dirty["dirty_set_phase_ordinal"] = 0
    must_reject(
        "dirty-set-map-mismatch",
        lambda: validate_batch_ledger(
            {"batch_ledger": bad_dirty, "batch_samples": [one_batch]}
        ),
    )
    rollback_after_new = [
        _batch_vector_record(0),
        _batch_vector_record(
            1,
            result="rolled-back",
            origin="RECOVERED_ROLLED_BACK",
        ),
    ]
    rollback_after_new[0]["sample_reasons"] = ["FIRST", "LAST"]
    rollback_after_new[1]["sample_reasons"] = ["ERROR", "FIRST", "LAST"]
    rollback_after_new_ledger = copy.deepcopy(rollback_ledger)
    rollback_after_new_ledger["ledger_hash"] = batch_ledger_hash(rollback_after_new)
    rollback_after_new_ledger["final_rescan_digest"] = rollback_after_new[1][
        "rescan_digest"
    ]
    must_reject(
        "rollback-after-new",
        lambda: validate_batch_ledger(
            {
                "batch_ledger": rollback_after_new_ledger,
                "batch_samples": rollback_after_new,
            }
        ),
    )
    rollback_committed = copy.deepcopy(rollback_batch)
    rollback_committed["commit_completed"] = True
    must_reject(
        "rollback-commit-completed",
        lambda: canonical_batch_record(rollback_committed, "rollback"),
    )
    accepted_incomplete = copy.deepcopy(one_batch)
    accepted_incomplete["commit_completed"] = False
    must_reject(
        "accepted-commit-incomplete",
        lambda: canonical_batch_record(accepted_incomplete, "accepted"),
    )
    unbound_rollback = copy.deepcopy(rollback_wal)
    unbound_rollback["actions"][0]["transaction_ordinal"] = None
    unbound_rollback["actions"][0]["transaction_uuid"] = None
    must_reject(
        "unbound-rollback-action",
        lambda: validate_wal_action_ledger(unbound_rollback),
    )
    mismatched_rollback = copy.deepcopy(rollback_wal)
    mismatched_rollback["actions"][0][
        "transaction_uuid"
    ] = "20000000-0000-4000-8000-000000000001"
    must_reject(
        "mismatched-rollback-action",
        lambda: validate_wal_batch_reconciliation(
            mismatched_rollback,
            rollback_ledger,
            [rollback_batch, new_after_rollback],
        ),
    )
    bad_wal = copy.deepcopy(wal)
    bad_wal["actions"][0]["slot"] = None
    must_reject("wal-slot", lambda: validate_wal_action_ledger(bad_wal))
    unresolved = copy.deepcopy(issue_report)
    unresolved["issue_ledger"]["resolved_count"] = 0
    unresolved["issue_ledger"]["unresolved_count"] = 1
    unresolved["issue_ledger"]["error_count"] = 1
    unresolved["issue_ledger"]["unresolved_by_severity"] = {"WARNING": 1}
    unresolved["issues"][0]["resolved"] = False
    unresolved["issues"][0]["sample_reasons"] = ["ERROR", "FIRST", "LAST"]
    must_reject("exit0-unresolved", lambda: validate_issues(unresolved))
    long_message = copy.deepcopy(issue_report)
    long_message["issues"][0]["message"] = "x" * (MAX_ISSUE_MESSAGE_BYTES + 1)
    must_reject("issue-message-bound", lambda: validate_issues(long_message))
    changed_message = copy.deepcopy(issue_report)
    changed_message["issues"][0]["message"] = "altered!"
    must_reject("issue-message-hash-binding", lambda: validate_issues(changed_message))
    if negative_count != 13:
        raise ReportError(
            f"bounded-ledger self-test expected 13 negatives, found {negative_count}"
        )
    return negative_count


def action_count_maps(
    repairs: list[dict[str, object]],
) -> tuple[dict[str, int], dict[str, int]]:
    by_action_id = Counter(str(repair["action_id"]) for repair in repairs)
    by_kind = Counter(str(repair["kind"]) for repair in repairs)
    return dict(by_action_id), dict(by_kind)


def validate_mirrored_mft_pair(
    pair: list[dict[str, object]], transaction_index: int, pair_offset: int
) -> None:
    if len(pair) != 2:
        raise ReportError(
            f"transactions[{transaction_index}] has an incomplete mirrored MFT pair"
        )
    first, second = pair
    for field in ("action_id", "kind", "target", "mft_record", "length"):
        if first.get(field) != second.get(field):
            raise ReportError(
                f"transactions[{transaction_index}] mirrored MFT pair differs in {field}"
            )
    if first.get("peer") != "MFT_PRIMARY" or second.get("peer") != "MFT_MIRROR":
        raise ReportError(
            f"transactions[{transaction_index}] mirrored MFT pair at {pair_offset} is reversed"
        )
    if first.get("offset") == second.get("offset"):
        raise ReportError(
            f"transactions[{transaction_index}] mirrored MFT pair targets one physical sector"
        )
    relative_offsets: list[int] = []
    for item in pair:
        semantic_offset = require_int(
            item.get("semantic_offset"),
            f"transactions[{transaction_index}] mirrored semantic_offset",
        )
        semantic_length = require_int(
            item.get("semantic_length"),
            f"transactions[{transaction_index}] mirrored semantic_length",
        )
        offset = int(item["offset"])
        length = int(item["length"])
        if semantic_length == 0 or not (
            offset <= semantic_offset
            and semantic_offset + semantic_length <= offset + length
        ):
            raise ReportError(
                f"transactions[{transaction_index}] mirrored semantic range escapes its sector"
            )
        relative_offsets.append(semantic_offset - offset)
    if relative_offsets[0] != relative_offsets[1]:
        raise ReportError(
            f"transactions[{transaction_index}] mirrored semantic offsets differ"
        )


def validate_dirty_pair(
    pair: list[dict[str, object]], transaction_index: int, action_id: int
) -> None:
    validate_mirrored_mft_pair(pair, transaction_index, 0)
    expected_kind = REPAIR_ACTIONS[action_id]
    for item in pair:
        if (
            item.get("action_id") != action_id
            or item.get("kind") != expected_kind
            or item.get("target") != "$Volume::$VOLUME_INFORMATION.flags"
            or item.get("mft_record") != 3
            or item.get("length") != 512
            or item.get("semantic_length") != 2
        ):
            raise ReportError(
                f"transactions[{transaction_index}] dirty action lacks exact record-3 sector evidence"
            )
    before = pair[0].get("volume_flags_before")
    after = pair[0].get("volume_flags_after")
    if (
        not isinstance(before, int)
        or isinstance(before, bool)
        or not 0 <= before <= 0xFFFF
        or not isinstance(after, int)
        or isinstance(after, bool)
        or not 0 <= after <= 0xFFFF
        or pair[1].get("volume_flags_before") != before
        or pair[1].get("volume_flags_after") != after
    ):
        raise ReportError(
            f"transactions[{transaction_index}] dirty pair flag evidence differs"
        )
    if action_id == 24:
        valid_delta = not (before & 1) and after == (before | 1)
    else:
        valid_delta = bool(before & 1) and after == (before & ~1)
    if not valid_delta:
        raise ReportError(
            f"transactions[{transaction_index}] dirty pair has the wrong semantic flag delta"
        )


def validate_native_action_order(
    action_ids: list[int], dirty_set_count: int, transaction_index: int
) -> None:
    redo_count = action_ids.count(5)
    restart_count = action_ids.count(6)
    if bool(redo_count) != bool(restart_count) or restart_count not in (0, 2):
        raise ReportError(
            f"transactions[{transaction_index}] native redo/restart cardinality differs"
        )
    if not redo_count:
        return
    native_start = 2 if dirty_set_count else 0
    native_end = native_start + redo_count
    if (
        action_ids[native_start:native_end] != [5] * redo_count
        or 5 in action_ids[native_end:]
        or action_ids[-2:] != [6, 6]
        or 6 in action_ids[:-2]
    ):
        raise ReportError(
            f"transactions[{transaction_index}] native redo/restart ordering differs"
        )


def native_action_order_self_test() -> int:
    for action_ids, dirty_set_count in (
        ([], 0),
        ([5, 5, 6, 6], 0),
        ([24, 24, 5, 5, 7, 13, 6, 6], 2),
    ):
        validate_native_action_order(action_ids, dirty_set_count, 0)
    negative_count = 0
    for action_ids, dirty_set_count in (
        ([6, 6], 0),
        ([5], 0),
        ([5, 6], 0),
        ([7, 5, 6, 6], 0),
        ([5, 6, 6, 7], 0),
        ([24, 24, 7, 6, 6], 2),
    ):
        try:
            validate_native_action_order(action_ids, dirty_set_count, 0)
        except ReportError:
            negative_count += 1
        else:
            raise ReportError(
                f"native action-order self-test accepted {action_ids!r}"
            )
    return negative_count


def foundation_plan_hash(repairs: list[dict[str, object]]) -> str | None:
    if not repairs:
        return None
    digest = hashlib.sha256()
    for repair in repairs:
        digest.update(struct.pack(">IQQ", repair["action_id"], repair["offset"], repair["length"]))
        digest.update(bytes.fromhex(str(repair["before_hash"])))
        digest.update(bytes.fromhex(str(repair["after_hash"])))
    return digest.hexdigest()


def validate_foundation(report: dict[str, object]) -> tuple[list[dict[str, object]], str | None]:
    raw = report.get("foundation_repairs")
    if not isinstance(raw, list):
        raise ReportError("foundation_repairs must be an array")
    if len(raw) > 4:
        raise ReportError("foundation_repairs exceeds the four redundant peers")
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ReportError(f"foundation_repairs[{index}] must be an object")
        require_exact_fields(
            item, FOUNDATION_ACTION_FIELDS, f"foundation_repairs[{index}]"
        )
    repairs = [validate_action(item, index, "foundation_repairs") for index, item in enumerate(raw)]
    if len({repair["action_id"] for repair in repairs}) != len(repairs):
        raise ReportError("foundation_repairs repeats a direct peer action")
    expected_peers = {
        1: ("BACKUP", "PRIMARY"),
        2: ("PRIMARY", "BACKUP"),
        3: ("MFT_MIRROR", "MFT_PRIMARY"),
        4: ("MFT_PRIMARY", "MFT_MIRROR"),
    }
    for index, repair in enumerate(repairs):
        action_id = repair["action_id"]
        if action_id not in expected_peers:
            raise ReportError(
                f"foundation_repairs[{index}] is not a direct redundant-copy action"
            )
        sync_ordinal = require_u64(
            repair.get("sync_ordinal"), f"foundation_repairs[{index}].sync_ordinal"
        )
        if sync_ordinal != index + 1:
            raise ReportError("foundation repair sync ordinals are not contiguous")
        if (
            repair.get("verified") is not True
            or repair.get("write_boundaries") == 0
            or repair.get("sync_completed") is not True
            or repair.get("readback_verified") is not True
        ):
            raise ReportError(f"foundation_repairs[{index}] lacks sync/readback proof")
        authority = repair.get("authority")
        if not isinstance(authority, dict):
            raise ReportError(f"foundation_repairs[{index}].authority must be an object")
        require_exact_fields(
            authority,
            FOUNDATION_AUTHORITY_FIELDS,
            f"foundation_repairs[{index}].authority",
        )
        source_peer, target_peer = expected_peers[action_id]
        if authority.get("source_peer") != source_peer or authority.get("target_peer") != target_peer:
            raise ReportError(f"foundation_repairs[{index}] peer authority differs")
        if authority.get("target_status") != "READABLE_STRUCTURALLY_INVALID":
            raise ReportError(f"foundation_repairs[{index}] target status is unsafe")
        for field in (
            "source_strict_valid",
            "source_expected_bound",
            "sole_valid_peer",
        ):
            if authority.get(field) is not True:
                raise ReportError(f"foundation_repairs[{index}] lacks {field} evidence")
        if authority.get("conflicting_valid_peer") is not False:
            raise ReportError(f"foundation_repairs[{index}] has conflicting authority")
    return repairs, foundation_plan_hash(repairs)


def foundation_self_test() -> int:
    action: dict[str, object] = {
        "ordinal": 0,
        "action_id": 1,
        "kind": "boot-primary",
        "target": "primary boot sector",
        "offset": 0,
        "length": 512,
        "before_hash": "1" * 64,
        "after_hash": "2" * 64,
        "verified": True,
        "write_boundaries": 1,
        "sync_ordinal": 1,
        "sync_completed": True,
        "readback_verified": True,
        "authority": {
            "source_peer": "BACKUP",
            "target_peer": "PRIMARY",
            "source_strict_valid": True,
            "source_expected_bound": True,
            "target_status": "READABLE_STRUCTURALLY_INVALID",
            "sole_valid_peer": True,
            "conflicting_valid_peer": False,
        },
    }
    report = {"foundation_repairs": [action]}
    repairs, plan_hash = validate_foundation(report)
    if len(repairs) != 1 or not isinstance(plan_hash, str):
        raise ReportError("foundation self-test lost its strict readable target")
    negative_count = 0
    for status in ("UNREADABLE", "STRUCTURALLY_INVALID"):
        candidate = copy.deepcopy(report)
        candidate["foundation_repairs"][0]["authority"]["target_status"] = status
        try:
            validate_foundation(candidate)
        except ReportError:
            negative_count += 1
        else:
            raise ReportError(
                f"foundation self-test accepted unsafe target status {status}"
            )
    return negative_count


def validate_transactions(
    report: dict[str, object], repairs: list[dict[str, object]]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    raw = report.get("transactions")
    if not isinstance(raw, list):
        raise ReportError("transactions must be an array")
    transactions: list[dict[str, object]] = []
    new_transactions: list[dict[str, object]] = []
    repair_cursor = 0
    sample_cursor = 0
    for index, transaction in enumerate(raw):
        if not isinstance(transaction, dict):
            raise ReportError(f"transactions[{index}] must be an object")
        if transaction.get("ordinal") != index:
            raise ReportError(f"transactions[{index}].ordinal is not contiguous")
        origin = transaction.get("origin")
        kind = transaction.get("kind")
        if origin not in ("NEW", "RECOVERED_COMMITTED"):
            raise ReportError(f"transactions[{index}].origin is invalid")
        if kind not in ("METADATA_REPAIR", "DIRTY_CLEAR"):
            raise ReportError(f"transactions[{index}].kind is invalid")
        transaction_uuid = transaction.get("transaction_uuid")
        plan_hash = transaction.get("plan_hash")
        if not isinstance(transaction_uuid, str) or not UUID.fullmatch(transaction_uuid):
            raise ReportError(f"transactions[{index}].transaction_uuid is invalid")
        if not isinstance(plan_hash, str) or not HASH.fullmatch(plan_hash):
            raise ReportError(f"transactions[{index}].plan_hash is invalid")
        if transaction.get("initial_state") not in (
            "PREPARING",
            "APPLYING",
            "COMMITTED",
            "ROLLBACK",
        ):
            raise ReportError(f"transactions[{index}].initial_state is invalid")
        if transaction.get("final_state") not in ("EMPTY", "ROLLBACK"):
            raise ReportError(f"transactions[{index}].final_state is invalid")
        if origin == "NEW" and transaction.get("initial_state") != "PREPARING":
            raise ReportError(f"transactions[{index}] new transaction did not start PREPARING")
        if origin == "RECOVERED_COMMITTED" and transaction.get("initial_state") != "COMMITTED":
            raise ReportError(f"transactions[{index}] recovered origin was not COMMITTED")
        entry_count = require_int(transaction.get("entry_count"), f"transactions[{index}].entry_count")
        target_bytes = require_int(transaction.get("target_bytes"), f"transactions[{index}].target_bytes")
        if entry_count == 0 or target_bytes == 0:
            raise ReportError(f"transactions[{index}] records a zero-operation WAL plan")
        if transaction.get("repair_ledger_format") != REPAIR_LEDGER_FORMAT:
            raise ReportError(f"transactions[{index}].repair_ledger_format differs")
        ledger_hash = transaction.get("repair_ledger_hash")
        if not isinstance(ledger_hash, str) or not HASH.fullmatch(ledger_hash):
            raise ReportError(f"transactions[{index}].repair_ledger_hash is invalid")
        first = require_int(
            transaction.get("repair_first_ordinal"),
            f"transactions[{index}].repair_first_ordinal",
        )
        count = require_int(transaction.get("repair_count"), f"transactions[{index}].repair_count")
        if first != repair_cursor:
            raise ReportError(f"transactions[{index}] repair span is not contiguous")
        sample_first = require_int(
            transaction.get("repair_sample_first_index"),
            f"transactions[{index}].repair_sample_first_index",
        )
        sample_count = require_int(
            transaction.get("repair_sample_count"),
            f"transactions[{index}].repair_sample_count",
        )
        if sample_first != sample_cursor or sample_first + sample_count > len(repairs):
            raise ReportError(f"transactions[{index}] repair sample span differs")
        span = repairs[sample_first : sample_first + sample_count]
        sample_cursor += sample_count
        count_ids, count_kinds, byte_ids, byte_kinds = validate_action_maps(
            transaction, index, entry_count, target_bytes
        )
        if origin == "NEW":
            if count == 0 or count != entry_count:
                raise ReportError(f"transactions[{index}] new repair span/count differs")
            repair_cursor += count
            if any(
                int(repair["ordinal"]) < first
                or int(repair["ordinal"]) >= first + count
                for repair in span
            ):
                raise ReportError(f"transactions[{index}] sample escapes its repair span")
            new_transactions.append(transaction)
        else:
            if count != 0 or sample_count != 0:
                raise ReportError(
                    f"transactions[{index}] recovered COMMITTED entry rewrote target repairs"
                )
        sample_ids, sample_kinds = action_count_maps(span)
        sample_byte_ids: Counter[str] = Counter()
        sample_byte_kinds: Counter[str] = Counter()
        for repair in span:
            sample_byte_ids[str(repair["action_id"])] += int(repair["length"])
            sample_byte_kinds[str(repair["kind"])] += int(repair["length"])
        if any(sample_ids[key] > count_ids.get(key, 0) for key in sample_ids):
            raise ReportError(f"transactions[{index}] samples exceed action counts")
        if any(sample_kinds[key] > count_kinds.get(key, 0) for key in sample_kinds):
            raise ReportError(f"transactions[{index}] samples exceed kind counts")
        if any(sample_byte_ids[key] > byte_ids.get(key, 0) for key in sample_byte_ids):
            raise ReportError(f"transactions[{index}] samples exceed action bytes")
        if any(sample_byte_kinds[key] > byte_kinds.get(key, 0) for key in sample_byte_kinds):
            raise ReportError(f"transactions[{index}] samples exceed kind bytes")
        fully_sampled = (
            origin == "NEW"
            and sample_count == count
            and [int(repair["ordinal"]) for repair in span]
            == list(range(first, first + count))
        )
        if fully_sampled:
            if (
                sample_ids != count_ids
                or sample_kinds != count_kinds
                or dict(sample_byte_ids) != byte_ids
                or dict(sample_byte_kinds) != byte_kinds
                or repair_ledger_hash(span) != ledger_hash
            ):
                raise ReportError(f"transactions[{index}] complete sampled ledger differs")
        first_action_ids = transaction.get("first_action_ids")
        last_action_ids = transaction.get("last_action_ids")
        edge_count = min(2, entry_count)
        for field, values in (
            ("first_action_ids", first_action_ids),
            ("last_action_ids", last_action_ids),
        ):
            if (
                not isinstance(values, list)
                or len(values) != edge_count
                or any(
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value not in REPAIR_ACTIONS
                    for value in values
                )
            ):
                raise ReportError(f"transactions[{index}].{field} is invalid")
        assert isinstance(first_action_ids, list) and isinstance(last_action_ids, list)
        if fully_sampled:
            action_ids = [int(repair["action_id"]) for repair in span]
            if first_action_ids != action_ids[:edge_count] or last_action_ids != action_ids[-edge_count:]:
                raise ReportError(f"transactions[{index}] action edge summaries differ")
        if kind == "DIRTY_CLEAR":
            if count_ids != {"25": 2} or count_kinds != {"volume-dirty-clear": 2}:
                raise ReportError(f"transactions[{index}] DIRTY_CLEAR action set differs")
            if first_action_ids != [25, 25] or last_action_ids != [25, 25]:
                raise ReportError(
                    f"transactions[{index}] DIRTY_CLEAR is not the ordered primary/mirror pair"
                )
            if fully_sampled:
                validate_dirty_pair(span, index, 25)
        else:
            if "25" in count_ids:
                raise ReportError(f"transactions[{index}] metadata contains dirty-clear")
            dirty_set_count = count_ids.get("24", 0)
            if dirty_set_count not in (0, 2):
                raise ReportError(
                    f"transactions[{index}] metadata dirty-set is not a primary/mirror pair"
                )
            if dirty_set_count and first_action_ids != [24, 24]:
                raise ReportError(
                    f"transactions[{index}] dirty-set pair is not first and ordered"
                )
            if dirty_set_count and fully_sampled:
                validate_dirty_pair(span[:2], index, 24)
            redo_count = count_ids.get("5", 0)
            restart_count = count_ids.get("6", 0)
            if bool(redo_count) != bool(restart_count) or restart_count not in (0, 2):
                raise ReportError(f"transactions[{index}] native redo/restart counts differ")
            if restart_count and last_action_ids != [6, 6]:
                raise ReportError(f"transactions[{index}] native restart pages are not last")
            if fully_sampled:
                action_ids = [int(repair["action_id"]) for repair in span]
                validate_native_action_order(action_ids, dirty_set_count, index)
        if fully_sampled:
            pair_offset = 0
            while pair_offset < len(span):
                mft_record = span[pair_offset].get("mft_record")
                if (
                    isinstance(mft_record, int)
                    and not isinstance(mft_record, bool)
                    and 0 <= mft_record <= 3
                ):
                    validate_mirrored_mft_pair(
                        span[pair_offset : pair_offset + 2], index, pair_offset
                    )
                    pair_offset += 2
                else:
                    pair_offset += 1
        for field in ("commit_started", "commit_completed"):
            require_bool(transaction.get(field), f"transactions[{index}].{field}")
        last_verified = require_int(
            transaction.get("last_verified_ordinal"),
            f"transactions[{index}].last_verified_ordinal",
        )
        syncs = require_int(
            transaction.get("syncs"), f"transactions[{index}].syncs"
        )
        write_boundaries = require_int(
            transaction.get("write_boundaries"),
            f"transactions[{index}].write_boundaries",
        )
        expected_target_boundaries = sum(
            int(repair["write_boundaries"]) for repair in span
        )
        if fully_sampled and write_boundaries != expected_target_boundaries:
            raise ReportError(
                f"transactions[{index}].write_boundaries differs from its target actions"
            )
        if last_verified > entry_count:
            raise ReportError(f"transactions[{index}] verified ordinal exceeds entry count")
        transaction_result = transaction.get("result")
        if transaction_result not in ("accepted", "rolled-back", "refused"):
            raise ReportError(f"transactions[{index}].result is invalid")
        if transaction_result == "accepted":
            if (
                transaction.get("final_state") != "EMPTY"
                or transaction.get("commit_started") is not True
                or transaction.get("commit_completed") is not True
                or last_verified != entry_count
                or write_boundaries == 0
                or any(
                    repair.get("verified") is not True
                    or repair.get("write_boundaries") == 0
                    for repair in span
                )
            ):
                raise ReportError(f"transactions[{index}] accepted state is incomplete")
        elif transaction_result == "refused":
            if (
                origin != "NEW"
                or transaction.get("final_state") != "ROLLBACK"
                or transaction.get("commit_started") is not False
                or transaction.get("commit_completed") is not False
                or last_verified != 0
                or syncs != 0
                or write_boundaries != 0
                or any(
                    repair.get("verified") is not False
                    or repair.get("write_boundaries") != 0
                    for repair in span
                )
            ):
                raise ReportError(f"transactions[{index}] refused state is not zero-write")
        transactions.append(transaction)
    if sample_cursor != len(repairs):
        raise ReportError("transaction sample spans do not exactly cover repairs")
    required_first = set(range(min(REPAIR_SAMPLE_EDGE_COUNT, repair_cursor)))
    required_last = set(
        range(max(0, repair_cursor - REPAIR_SAMPLE_EDGE_COUNT), repair_cursor)
    )
    observed_ordinals = {int(repair["ordinal"]) for repair in repairs}
    if not required_first.issubset(observed_ordinals) or not required_last.issubset(observed_ordinals):
        raise ReportError("repair samples omit mandatory first/last actions")
    for repair in repairs:
        ordinal = int(repair["ordinal"])
        reasons = repair["sample_reasons"]
        assert isinstance(reasons, list)
        if (ordinal in required_first) != ("FIRST" in reasons):
            raise ReportError("repair FIRST sample reason differs")
        if (ordinal in required_last) != ("LAST" in reasons):
            raise ReportError("repair LAST sample reason differs")
        if ordinal not in required_first | required_last and "ERROR" not in reasons:
            raise ReportError("non-edge repair sample lacks ERROR reason")
    seen_new = False
    for index, transaction in enumerate(transactions):
        if transaction["origin"] == "NEW":
            seen_new = True
        elif seen_new:
            raise ReportError(
                f"transactions[{index}] recovered COMMITTED entry follows NEW work"
            )
    new_kinds = [
        transaction["kind"]
        for transaction in transactions
        if transaction["origin"] == "NEW"
    ]
    if "DIRTY_CLEAR" in new_kinds and (
        new_kinds[-1] != "DIRTY_CLEAR" or new_kinds.count("DIRTY_CLEAR") != 1
    ):
        raise ReportError("DIRTY_CLEAR is not the single final NEW transaction")
    metadata_seen = 0
    native_seen = 0
    for index, transaction in enumerate(transactions):
        if transaction["kind"] != "METADATA_REPAIR":
            continue
        counts = transaction["by_action_id"]
        assert isinstance(counts, dict)
        if counts.get("24", 0):
            if metadata_seen != 0:
                raise ReportError("only the first metadata transaction may set dirty")
        if counts.get("5", 0) or counts.get("6", 0):
            native_seen += 1
            if metadata_seen != 0:
                raise ReportError("native replay does not precede derived metadata batches")
        metadata_seen += 1
    if native_seen > 1:
        raise ReportError("native replay spans more than one metadata transaction")
    return transactions, new_transactions


def validate_wal_action_reconciliation(
    wal: dict[str, object], transactions: list[dict[str, object]]
) -> None:
    actions = wal.get("actions")
    assert isinstance(actions, list)
    by_transaction: dict[int, list[dict[str, object]]] = {}
    for index, action in enumerate(actions):
        assert isinstance(action, dict)
        ordinal = action.get("transaction_ordinal")
        if ordinal is None:
            continue
        if ordinal >= len(transactions):
            raise ReportError(
                f"wal.actions[{index}] references an absent transaction"
            )
        transaction = transactions[ordinal]
        if transaction.get("origin") != "NEW":
            raise ReportError(
                f"wal.actions[{index}] references a non-NEW transaction"
            )
        by_transaction.setdefault(ordinal, []).append(action)
    for ordinal, transaction in enumerate(transactions):
        if transaction.get("origin") != "NEW":
            continue
        transaction_actions = by_transaction.get(ordinal, [])
        if transaction.get("result") == "refused":
            if transaction_actions:
                raise ReportError(
                    f"transactions[{ordinal}] refused plan wrote the raw WAL"
                )
            continue
        kinds = {action.get("kind") for action in transaction_actions}
        if not {"undo-payload-append", "descriptor-append", "state-transition"}.issubset(kinds):
            raise ReportError(
                f"transactions[{ordinal}] lacks complete raw WAL action evidence"
            )
        if transaction.get("result") == "accepted":
            transitions = [
                (action.get("from_state"), action.get("to_state"))
                for action in transaction_actions
                if action.get("kind") == "state-transition"
            ]
            if transitions != [
                ("EMPTY", "PREPARING"),
                ("PREPARING", "APPLYING"),
                ("APPLYING", "COMMITTED"),
                ("COMMITTED", "EMPTY"),
            ]:
                raise ReportError(
                    f"transactions[{ordinal}] accepted WAL transition order differs"
                )


def validate_rescan_binding(
    state: dict[str, object],
    index: int,
    transactions: list[dict[str, object]],
    foundation_hash: str | None,
) -> None:
    binding = state.get("binding")
    transaction_uuid = state.get("transaction_uuid")
    plan_hash = state.get("plan_hash")
    stage = state.get("stage")
    if binding == "INITIAL":
        if stage != "FINAL" or transaction_uuid is not None or plan_hash is not None:
            raise ReportError(f"rescans[{index}] INITIAL binding differs")
    elif binding == "FOUNDATION":
        new_kinds = [
            transaction.get("kind")
            for transaction in transactions
            if transaction.get("origin") == "NEW"
        ]
        if (
            stage not in ("POST_METADATA", "FINAL")
            or transaction_uuid is not None
            or foundation_hash is None
            or plan_hash != foundation_hash
            or (stage == "FINAL" and new_kinds)
            or (stage == "POST_METADATA" and not new_kinds)
        ):
            raise ReportError(f"rescans[{index}] FOUNDATION binding differs")
    elif binding == "TRANSACTION":
        if (
            not isinstance(transaction_uuid, str)
            or not UUID.fullmatch(transaction_uuid)
            or not isinstance(plan_hash, str)
            or not HASH.fullmatch(plan_hash)
            or not any(
                tx["transaction_uuid"] == transaction_uuid
                and tx["plan_hash"] == plan_hash
                for tx in transactions
            )
        ):
            raise ReportError(f"rescans[{index}] transaction binding differs")
    else:
        raise ReportError(f"rescans[{index}].binding is invalid")


def validate_rescans(
    report: dict[str, object],
    transactions: list[dict[str, object]],
    foundation_hash: str | None,
) -> list[dict[str, object]]:
    raw = report.get("rescans")
    if not isinstance(raw, list):
        raise ReportError("rescans must be an array")
    rescans: list[dict[str, object]] = []
    for index, rescan in enumerate(raw):
        state = validate_snapshot(rescan, f"rescans[{index}]")
        if state.get("ordinal") != index:
            raise ReportError(f"rescans[{index}].ordinal is not contiguous")
        if state.get("stage") not in ("POST_METADATA", "FINAL"):
            raise ReportError(f"rescans[{index}].stage is invalid")
        validate_rescan_binding(state, index, transactions, foundation_hash)
        rescans.append(state)
    final = validate_snapshot(report.get("final"), "final")
    if rescans:
        last = rescans[-1]
        if last.get("stage") != "FINAL":
            raise ReportError("last rescan is not FINAL")
        for field in (
            "completed",
            "scan_id",
            "execution",
            "fresh_process",
            "read_only",
            "exit_code",
            "result",
            "dirty",
            "logfile_clean",
            "native_log_state",
            "identity_valid",
            "coverage",
        ):
            if final.get(field) != last.get(field):
                raise ReportError(f"final.{field} differs from the final rescan")
    elif final.get("completed") is not False:
        raise ReportError("completed final snapshot has no fresh rescan")
    return rescans


def foundation_rescan_binding_self_test() -> int:
    plan_hash = "a" * 64
    final = {
        "stage": "FINAL",
        "binding": "FOUNDATION",
        "transaction_uuid": None,
        "plan_hash": plan_hash,
    }
    post_metadata = dict(final, stage="POST_METADATA")
    dirty_clear = [{"origin": "NEW", "kind": "DIRTY_CLEAR"}]
    metadata_then_clear = [
        {"origin": "NEW", "kind": "METADATA_REPAIR"},
        {"origin": "NEW", "kind": "DIRTY_CLEAR"},
    ]
    validate_rescan_binding(final, 0, [], plan_hash)
    validate_rescan_binding(post_metadata, 0, dirty_clear, plan_hash)
    validate_rescan_binding(post_metadata, 0, metadata_then_clear, plan_hash)
    negative_count = 0

    def must_reject(
        name: str,
        state: dict[str, object],
        transactions: list[dict[str, object]],
        foundation: str | None = plan_hash,
    ) -> None:
        nonlocal negative_count
        try:
            validate_rescan_binding(state, 0, transactions, foundation)
        except ReportError:
            negative_count += 1
            return
        raise ReportError(f"foundation rescan self-test accepted {name}")

    must_reject("final-before-dirty-clear", final, dirty_clear)
    must_reject("post-without-next-phase", post_metadata, [])
    must_reject("wrong-plan", dict(final, plan_hash="b" * 64), [])
    must_reject(
        "transaction-uuid",
        dict(final, transaction_uuid="10000000-0000-4000-8000-000000000001"),
        [],
    )
    if negative_count != 4:
        raise ReportError(
            "foundation rescan self-test expected 4 negative cases, "
            f"found {negative_count}"
        )
    return negative_count


def validate_common(
    report: dict[str, object], expected_journal_uuid: str, expected_volume_serial: str
) -> dict[str, object]:
    require_exact_fields(report, TOP_LEVEL_FIELDS, "report")
    if report.get("format") != 3:
        raise ReportError("repair report format must be 3")
    if report.get("mode") != "repair":
        raise ReportError("repair report mode must be 'repair'")
    if report.get("result") not in (
        "clean",
        "unsafe",
        "io-error",
        "wrong-root",
        "internal-error",
    ):
        raise ReportError("repair report result is invalid")
    exit_code = require_u32(report.get("exit_code"), "exit_code")
    if exit_code not in (0, 2, 3, 4, 5):
        raise ReportError("repair report exit code is invalid")
    require_bool(report.get("dirty_cleared"), "dirty_cleared")
    checker = report.get("checker")
    require_release_checker(checker)
    require_bounded_utf8(
        report.get("checker_version"),
        "checker_version",
        MAX_VERSION_TEXT_BYTES,
    )
    device = validate_device(report)
    initial = validate_snapshot(report.get("initial"), "initial")
    native_log = validate_native_log(report.get("native_log"), "native_log")
    if initial.get("native_log_state") != native_log.get("state"):
        raise ReportError("initial native-log state differs from detailed evidence")
    issue_ledger = validate_issues(report)
    identity = validate_identity(report)
    plan = report.get("plan")
    if not isinstance(plan, dict):
        raise ReportError("plan must be an object")
    require_exact_fields(plan, PLAN_FIELDS, "plan")
    require_u64(plan.get("operations"), "plan.operations")
    require_u64(plan.get("bytes"), "plan.bytes")
    require_u64(plan.get("priority_operations"), "plan.priority_operations")
    for field in (
        "foundation_operations",
        "foundation_bytes",
        "wal_operations",
        "wal_bytes",
    ):
        require_u64(plan.get(field), f"plan.{field}")
    if not isinstance(plan.get("by_action_id"), dict):
        raise ReportError("plan.by_action_id must be an object")
    if not isinstance(plan.get("by_kind"), dict):
        raise ReportError("plan.by_kind must be an object")
    if not isinstance(plan.get("bytes_by_action_id"), dict):
        raise ReportError("plan.bytes_by_action_id must be an object")
    if not isinstance(plan.get("bytes_by_kind"), dict):
        raise ReportError("plan.bytes_by_kind must be an object")
    commit = report.get("commit")
    if not isinstance(commit, dict):
        raise ReportError("commit must be an object")
    require_exact_fields(commit, COMMIT_FIELDS, "commit")
    require_bool(commit.get("started"), "commit.started")
    require_bool(commit.get("completed"), "commit.completed")
    require_u64(commit.get("last_verified_ordinal"), "commit.last_verified_ordinal")
    require_u64(commit.get("syncs"), "commit.syncs")
    require_u64(commit.get("write_boundaries"), "commit.write_boundaries")

    foundation, foundation_hash = validate_foundation(report)
    repairs = validate_repair_samples(report.get("repairs"))
    batch_ledger, batch_samples = validate_batch_ledger(report)
    if "transactions" in report or "rescans" in report:
        raise ReportError(
            "unbounded transactions/rescans arrays are forbidden; use RHTXN3 samples"
        )
    validate_report_budget(report)
    foundation_bytes = sum(int(repair["length"]) for repair in foundation)
    if batch_ledger.get("foundation_count") != (1 if foundation else 0):
        raise ReportError("RHTXN3 foundation count differs from foundation repairs")
    new_samples = [sample for sample in batch_samples if sample.get("origin") == "NEW"]
    new_entry_count = sum(int(sample["entry_count"]) for sample in new_samples)
    new_target_bytes = sum(int(sample["target_bytes"]) for sample in new_samples)
    new_count_ids: Counter[str] = Counter()
    new_count_kinds: Counter[str] = Counter()
    new_byte_ids: Counter[str] = Counter()
    new_byte_kinds: Counter[str] = Counter()
    for sample in new_samples:
        new_count_ids.update(sample["by_action_id"])
        new_count_kinds.update(sample["by_kind"])
        new_byte_ids.update(sample["bytes_by_action_id"])
        new_byte_kinds.update(sample["bytes_by_kind"])
    foundation_count_ids, foundation_count_kinds = action_count_maps(foundation)
    foundation_byte_ids: Counter[str] = Counter()
    foundation_byte_kinds: Counter[str] = Counter()
    for action in foundation:
        foundation_byte_ids[str(action["action_id"])] += int(action["length"])
        foundation_byte_kinds[str(action["kind"])] += int(action["length"])
    expected_count_ids = Counter(foundation_count_ids) + new_count_ids
    expected_count_kinds = Counter(foundation_count_kinds) + new_count_kinds
    expected_byte_ids = foundation_byte_ids + new_byte_ids
    expected_byte_kinds = foundation_byte_kinds + new_byte_kinds
    if plan.get("operations") != len(foundation) + new_entry_count:
        raise ReportError("plan.operations differs from the physical repair count")
    if plan.get("bytes") != foundation_bytes + new_target_bytes:
        raise ReportError("plan.bytes differs from the physical repair-byte total")
    if plan.get("foundation_operations") != len(foundation) or plan.get("foundation_bytes") != foundation_bytes:
        raise ReportError("plan foundation totals differ")
    expected_wal_operations = new_entry_count
    expected_wal_bytes = new_target_bytes
    if (
        plan.get("wal_operations") != expected_wal_operations
        or plan.get("wal_bytes") != expected_wal_bytes
    ):
        raise ReportError("plan WAL totals differ")
    for name, expected in (
        ("by_action_id", dict(expected_count_ids)),
        ("by_kind", dict(expected_count_kinds)),
        ("bytes_by_action_id", dict(expected_byte_ids)),
        ("bytes_by_kind", dict(expected_byte_kinds)),
    ):
        if plan.get(name) != expected:
            raise ReportError(f"plan.{name} differs from NEW RHTXN3 work")
    if plan.get("priority_operations") > plan.get("wal_operations"):
        raise ReportError("plan priority operations exceed WAL operations")
    for repair in repairs:
        if int(repair["ordinal"]) >= int(plan["wal_operations"]):
            raise ReportError("repair sample ordinal exceeds the WAL repair plan")
    expected_started = (
        int(batch_ledger["commit_started_count"]) != 0
        or int(batch_ledger["rolled_back_count"]) != 0
    )
    expected_completed = expected_started and (
        int(batch_ledger["accepted_count"])
        + int(batch_ledger["rolled_back_count"])
        == int(batch_ledger["record_count"]) - int(batch_ledger["refused_count"])
    )
    if commit.get("started") is not expected_started:
        raise ReportError("commit.started differs from RHTXN3")
    if commit.get("completed") is not expected_completed:
        raise ReportError("commit.completed differs from RHTXN3")
    if commit.get("last_verified_ordinal") != batch_ledger.get("verified_entries"):
        raise ReportError("commit.last_verified_ordinal does not reconcile")
    wal = wal_object(report)
    validate_wal_batch_reconciliation(wal, batch_ledger, batch_samples)
    wal_action_ledger = wal["action_ledger"]
    assert isinstance(wal_action_ledger, dict)
    current_phase_syncs = (
        int(batch_ledger["syncs"])
        if foundation
        else sum(
            int(sample["syncs"])
            for sample in batch_samples
            if sample.get("origin") == "NEW"
        )
    )
    current_phase_boundaries = (
        int(batch_ledger["write_boundaries"])
        if foundation
        else sum(
            int(sample["write_boundaries"])
            for sample in batch_samples
            if sample.get("origin") == "NEW"
        )
    )
    expected_syncs = current_phase_syncs + int(wal_action_ledger["syncs"])
    if commit.get("syncs") != expected_syncs:
        raise ReportError("commit.syncs differs from RHTXN3+RHWAL3")
    expected_boundaries = current_phase_boundaries + int(wal["write_boundaries"])
    if commit.get("write_boundaries") != expected_boundaries:
        raise ReportError("commit.write_boundaries does not reconcile")
    if native_log.get("state") == "REPLAY_PLANNED":
        current_native_operations = 0
        current_native_bytes = 0
        for sample in batch_samples:
            if sample.get("origin") != "NEW":
                continue
            counts = sample.get("by_action_id")
            byte_counts = sample.get("bytes_by_action_id")
            assert isinstance(counts, dict) and isinstance(byte_counts, dict)
            current_native_operations += int(counts.get("5", 0)) + int(
                counts.get("6", 0)
            )
            current_native_bytes += int(byte_counts.get("5", 0)) + int(
                byte_counts.get("6", 0)
            )
        if (
            native_log.get("planned_io_operations") != current_native_operations
            or native_log.get("planned_io_bytes") != current_native_bytes
        ):
            raise ReportError("native-log plan differs from current RHTXN3 work")
    validate_native_log_reconciliation(
        native_log,
        mode="repair",
        plan=plan,
        repairs=repairs,
        batch_ledger=batch_ledger,
        batch_samples=batch_samples,
    )

    transactions: list[dict[str, object]] = []
    new_transactions: list[dict[str, object]] = []
    rescans: list[dict[str, object]] = []
    for index, sample in enumerate(batch_samples):
        transaction = dict(sample)
        transaction["kind"] = sample.get("phase")
        if sample.get("phase") != "FOUNDATION":
            transactions.append(transaction)
            if sample.get("origin") == "NEW":
                new_transactions.append(transaction)
        rescan_raw = sample.get("rescan")
        if rescan_raw is None:
            continue
        rescan = validate_snapshot(
            rescan_raw, f"batch_samples[{index}].rescan"
        )
        coverage = rescan["coverage"]
        assert isinstance(coverage, dict)
        if coverage.get("ledger_hash") != sample.get("post_coverage_ledger_hash"):
            raise ReportError("batch rescan coverage hash differs from RHTXN3")
        if canonical_diagnosis_hash(
            rescan, f"batch_samples[{index}].rescan"
        ) != sample.get("post_diagnosis_hash"):
            raise ReportError("batch rescan diagnosis hash differs from RHTXN3")
        if sample.get("phase") == "FOUNDATION":
            if (
                rescan.get("binding") != "FOUNDATION"
                or rescan.get("transaction_uuid") is not None
                or rescan.get("plan_hash") != sample.get("plan_hash")
            ):
                raise ReportError("foundation rescan binding differs")
        elif (
            rescan.get("binding") != "TRANSACTION"
            or rescan.get("transaction_uuid") != sample.get("transaction_uuid")
            or rescan.get("plan_hash") != sample.get("plan_hash")
        ):
            raise ReportError("transaction rescan binding differs")
        rescans.append(rescan)
    final = validate_snapshot(report.get("final"), "final")
    if int(batch_ledger["rescan_count"]):
        expected_final_digest = batch_ledger.get("final_rescan_digest")
        if canonical_snapshot_digest(final, "final") != expected_final_digest:
            raise ReportError("final snapshot differs from the final RHTXN3 rescan")
        final_coverage = final["coverage"]
        assert isinstance(final_coverage, dict)
        if (
            final_coverage.get("ledger_hash")
            != batch_ledger.get("final_coverage_ledger_hash")
            or canonical_diagnosis_hash(final, "final")
            != batch_ledger.get("final_diagnosis_hash")
        ):
            raise ReportError("final snapshot state hashes differ from RHTXN3")
    if not any(
        canonical_snapshot_digest(rescan, "sampled rescan")
        == canonical_snapshot_digest(final, "final")
        for rescan in rescans
    ) and final.get("completed") is True:
        rescans.append(final)
    validate_execution_chain(initial, rescans, self_exec_rescans=True)
    return {
        "device": device,
        "initial": initial,
        "foundation": foundation,
        "foundation_hash": foundation_hash,
        "repairs": repairs,
        "batch_ledger": batch_ledger,
        "batch_samples": batch_samples,
        "transactions": transactions,
        "new_transactions": new_transactions,
        "rescans": rescans,
        "plan": plan,
        "commit": commit,
        "wal": wal,
        "issue_ledger": issue_ledger,
        "native_log": native_log,
    }


def validate_committed_batch_rescans(
    foundation: list[dict[str, object]],
    transactions: list[dict[str, object]],
    rescans: list[dict[str, object]],
) -> None:
    committed_metadata = [
        transaction
        for transaction in transactions
        if transaction.get("kind") == "METADATA_REPAIR"
        and transaction.get("result") == "accepted"
    ]
    expected_intermediate: list[tuple[str, dict[str, object] | None]] = []
    if foundation:
        expected_intermediate.append(("FOUNDATION", None))
    expected_intermediate.extend(
        ("TRANSACTION", transaction) for transaction in committed_metadata
    )
    if not expected_intermediate:
        return
    if len(rescans) != len(expected_intermediate) + 1:
        raise ReportError("structural batches lack one fresh rescan per commit")
    for rescan_index, ((binding, transaction), rescan) in enumerate(
        zip(expected_intermediate, rescans[:-1])
    ):
        if (
            rescan.get("stage") != "POST_METADATA"
            or rescan.get("binding") != binding
            or rescan.get("exit_code") != 2
            or rescan.get("result") != "unsafe"
            or rescan.get("dirty") is not True
            or rescan.get("identity_valid") is not True
        ):
            raise ReportError(
                f"POST_METADATA rescan {rescan_index} does not bind its batch"
            )
        if transaction is not None and (
            rescan.get("transaction_uuid") != transaction.get("transaction_uuid")
            or rescan.get("plan_hash") != transaction.get("plan_hash")
        ):
            raise ReportError(
                f"POST_METADATA rescan {rescan_index} transaction binding differs"
            )


def validate_success(
    report: dict[str, object],
    expected_kinds: list[str],
    noop: bool,
    wal_recovery_only: bool,
    expected_journal_uuid: str,
    expected_volume_serial: str,
) -> None:
    context = validate_common(report, expected_journal_uuid, expected_volume_serial)
    require_bound_wal(report, expected_journal_uuid, expected_volume_serial)
    if report.get("result") != "clean" or report.get("exit_code") != 0:
        raise ReportError("successful repair report must be clean with exit 0")
    identity = report["identity"]
    assert isinstance(identity, dict)
    plan = context["plan"]
    commit = context["commit"]
    repairs = context["repairs"]
    foundation = context["foundation"]
    transactions = context["transactions"]
    new_transactions = context["new_transactions"]
    batch_ledger = context["batch_ledger"]
    batch_samples = context["batch_samples"]
    rescans = context["rescans"]
    initial = context["initial"]
    assert isinstance(plan, dict) and isinstance(commit, dict)
    assert isinstance(repairs, list) and isinstance(foundation, list)
    assert isinstance(transactions, list) and isinstance(new_transactions, list)
    assert isinstance(batch_ledger, dict) and isinstance(batch_samples, list)
    assert isinstance(rescans, list) and isinstance(initial, dict)
    scan_ids = [initial.get("scan_id")] + [rescan.get("scan_id") for rescan in rescans]
    if any(scan_id is None for scan_id in scan_ids) or len(set(scan_ids)) != len(scan_ids):
        raise ReportError("repair diagnosis/rescans do not have distinct fresh scan IDs")
    recovered_count = int(batch_ledger["recovered_committed_count"]) + int(
        batch_ledger["recovered_rolled_back_count"]
    )
    if (
        identity.get("prewrite_checked") is not True
        or identity.get("prewrite_valid") is not True
    ):
        recovered_samples = [
            sample
            for sample in batch_samples
            if sample.get("origin")
            in ("RECOVERED_COMMITTED", "RECOVERED_ROLLED_BACK")
        ]
        if (
            recovered_count == 0
            or len(recovered_samples) != recovered_count
            or any(
                not isinstance(sample.get("rescan"), dict)
                or sample["rescan"].get("completed") is not True
                or sample["rescan"].get("identity_valid") is not True
                for sample in recovered_samples
            )
        ):
            raise ReportError(
                "repair writes were not gated by identity or authenticated recovery"
            )
    wal_object_value = report.get("wal")
    assert isinstance(wal_object_value, dict)
    wal_actions = wal_object_value.get("actions")
    assert isinstance(wal_actions, list)
    reconstructed_degraded = any(
        isinstance(action, dict)
        and action.get("kind") == "superblock-reconstruct"
        for action in wal_actions
    )
    if recovered_count or reconstructed_degraded:
        if (
            initial.get("result") != "unsafe"
            or initial.get("exit_code") != 2
            or initial["coverage"].get("complete") is not False
        ):
            raise ReportError(
                "WAL recovery does not begin with a fail-closed partial INITIAL scan"
            )
        if recovered_count and (
            not batch_samples
            or batch_samples[0].get("origin")
            not in ("RECOVERED_COMMITTED", "RECOVERED_ROLLED_BACK")
        ):
            raise ReportError(
                "transaction recovery is not the first sampled repair phase"
            )
        if reconstructed_degraded and (
            wal_object_value.get("valid") is not True
            or wal_object_value.get("recovery_required") is not True
        ):
            raise ReportError(
                "superblock reconstruction lacks a valid degraded INITIAL WAL"
            )
    else:
        plan_kinds_for_initial = plan.get("by_kind")
        if "index-root" in expected_kinds or (
            isinstance(plan_kinds_for_initial, dict)
            and plan_kinds_for_initial.get("index-root", 0) == 1
        ):
            require_operations_stale_coverage(
                initial["coverage"], "initial.coverage", allow_differences=True,
            )
        else:
            require_complete_coverage(
                initial["coverage"], "initial.coverage", allow_differences=True,
                allow_fixed_skips="index-bitmap" in expected_kinds,
            )
    for index, rescan in enumerate(rescans):
        rolled_back_namespace = False
        for transaction_index, transaction in enumerate(transactions):
            kinds = transaction.get("by_kind")
            if (
                transaction.get("transaction_uuid")
                != rescan.get("transaction_uuid")
                or transaction.get("origin") != "RECOVERED_ROLLED_BACK"
                or transaction.get("result") != "rolled-back"
            ):
                continue
            rolled_back_namespace = (
                isinstance(kinds, dict) and kinds.get("index-root", 0) == 1
            ) or any(
                later.get("origin") == "NEW"
                and later.get("kind") == "METADATA_REPAIR"
                and isinstance(later.get("by_kind"), dict)
                and later["by_kind"].get("index-root", 0) == 1
                for later in transactions[transaction_index + 1 :]
            )
            break
        if rolled_back_namespace:
            # A crash before acceptance can roll action 11 back to the exact
            # one-edge field precursor.  That rescan is intentionally partial;
            # the following NEW transaction must repair it and finish complete.
            require_operations_stale_coverage(
                rescan["coverage"], f"rescans[{index}].coverage",
                allow_differences=True,
            )
        else:
            require_complete_coverage(
                rescan["coverage"], f"rescans[{index}].coverage",
                allow_differences=index + 1 < len(rescans),
            )
    operations = plan["operations"]
    assert isinstance(operations, int)
    if operations and commit.get("started") is not True:
        raise ReportError("nonempty repair did not mark commit.started")
    if operations and commit.get("completed") is not True:
        raise ReportError("successful repair did not mark commit.completed")
    if int(commit.get("last_verified_ordinal")) < operations:
        raise ReportError("commit did not verify every planned operation")
    plan_kinds = plan.get("by_kind")
    assert isinstance(plan_kinds, dict)
    kinds = list(plan_kinds)
    missing = sorted(set(expected_kinds) - set(kinds))
    if missing:
        raise ReportError("repair report is missing action kinds: " + ", ".join(missing))
    final = report["final"]
    assert isinstance(final, dict)
    if final.get("completed") is not True or final.get("result") != "clean":
        raise ReportError("exit 0 was not backed by a final fresh clean rescan")
    wal = report["wal"]
    assert isinstance(wal, dict)
    if recovered_count:
        if (
            wal.get("state") not in ("PREPARING", "APPLYING", "COMMITTED")
            or wal.get("recovery_required") is not True
            or wal.get("recovered") is not True
        ):
            raise ReportError("successful recovery lacks its initial WAL state evidence")
    elif reconstructed_degraded:
        if (
            wal.get("state") != "EMPTY"
            or wal.get("recovery_required") is not True
            or not wal.get("actions")
        ):
            raise ReportError(
                "successful degraded-WAL reconstruction lacks its initial evidence"
            )
    else:
        if wal.get("state") != "EMPTY":
            raise ReportError("successful repair did not finalize the WAL to EMPTY")
        if wal.get("recovery_required") is not False:
            raise ReportError("successful repair still reports WAL recovery required")
    if noop and wal_recovery_only:
        raise ReportError("no-op and WAL-recovery-only assertions are mutually exclusive")
    if noop:
        if (
            operations
            or plan.get("bytes")
            or repairs
            or foundation
            or batch_ledger.get("record_count")
            or batch_samples
        ):
            raise ReportError("clean --repair planned or performed a write")
        if commit.get("started") is not False or report.get("dirty_cleared") is not False:
            raise ReportError("clean --repair entered commit or cleared dirty state")
        if initial.get("result") != "clean" or initial.get("exit_code") != 0:
            raise ReportError("clean --repair initial diagnosis was not clean")
        if (
            len(rescans) != 1
            or rescans[0].get("stage") != "FINAL"
            or rescans[0].get("binding") != "INITIAL"
            or rescans[0].get("result") != "clean"
        ):
            raise ReportError("clean --repair did not perform exactly one FINAL rescan")
        if wal.get("write_boundaries") != 0:
            raise ReportError("clean --repair advanced the internal WAL")
        if wal.get("recovered") is not False:
            raise ReportError("clean --repair falsely reports WAL recovery")
        if wal.get("actions"):
            raise ReportError("clean --repair fabricated raw WAL actions")
    elif wal_recovery_only or (
        reconstructed_degraded
        and int(batch_ledger.get("record_count")) == 0
        and operations == 0
    ):
        if (
            operations
            or plan.get("bytes")
            or repairs
            or foundation
            or batch_ledger.get("record_count")
            or batch_samples
            or expected_kinds
        ):
            raise ReportError("WAL housekeeping entered the filesystem repair plan")
        if commit.get("started") is not False or commit.get("last_verified_ordinal") != 0:
            raise ReportError("WAL housekeeping entered the filesystem commit")
        if report.get("dirty_cleared") is not False:
            raise ReportError("WAL housekeeping cleared a clean volume's dirty flag")
        if len(rescans) != 1 or rescans[0].get("binding") != "INITIAL" or rescans[0].get("result") != "clean":
            raise ReportError("WAL housekeeping did not remain a clean FINAL rescan")
        if not isinstance(wal.get("write_boundaries"), int) or wal.get("write_boundaries") <= 0:
            raise ReportError("WAL housekeeping did not report durable reconstruction writes")
        if not wal.get("actions"):
            raise ReportError("WAL housekeeping lacks raw action attestation")
    else:
        metadata_count = int(batch_ledger["metadata_count"])
        dirty_set_count = int(batch_ledger["dirty_set_action_count"])
        if recovered_count:
            recovery_rescan = batch_samples[recovered_count - 1].get("rescan")
            if not isinstance(recovery_rescan, dict):
                raise ReportError("recovered work lacks its fresh post-recovery scan")
            initial_dirty = recovery_rescan.get("dirty")
        elif reconstructed_degraded and metadata_count:
            initial_dirty = dirty_set_count == 0
        elif reconstructed_degraded and int(batch_ledger["dirty_clear_count"]):
            # A torn superblock can hide the initial volume-state snapshot.
            # An independently rederived DIRTY_CLEAR transaction nevertheless
            # proves that its exact preimage was dirty.
            initial_dirty = True
        else:
            initial_dirty = initial.get("dirty")
        if initial_dirty not in (True, False):
            raise ReportError("mutating repair did not establish its pre-plan dirty state")
        recovered_count = int(batch_ledger["recovered_committed_count"]) + int(
            batch_ledger["recovered_rolled_back_count"]
        )
        if recovered_count == 0:
            if initial_dirty is False and metadata_count and dirty_set_count != 2:
                raise ReportError(
                    "clean-start first metadata transaction lacks the paired dirty-set"
                )
            if (initial_dirty is True or metadata_count == 0) and dirty_set_count != 0:
                raise ReportError("already-dirty/nonmetadata repair fabricated dirty-set")
        clean_foundation_only = (
            bool(foundation)
            and plan.get("wal_operations") == 0
            and batch_ledger.get("foundation_count") == 1
            and batch_ledger.get("record_count") == 1
            and batch_ledger.get("metadata_count") == 0
            and batch_ledger.get("dirty_clear_count") == 0
            and initial_dirty is False
        )
        if clean_foundation_only:
            if (
                initial.get("exit_code") != 2
                or initial.get("result") != "unsafe"
                or initial.get("logfile_clean") is not True
            ):
                raise ReportError(
                    "clean foundation repair lacks an unsafe clean-volume diagnosis"
                )
            if (
                len(rescans) != 1
                or rescans[0].get("stage") != "FINAL"
                or rescans[0].get("binding") != "FOUNDATION"
                or rescans[0].get("exit_code") != 0
                or rescans[0].get("result") != "clean"
                or rescans[0].get("dirty") is not False
                or rescans[0].get("logfile_clean") is not True
                or rescans[0].get("identity_valid") is not True
            ):
                raise ReportError(
                    "clean foundation repair lacks one FINAL FOUNDATION rescan"
                )
            if report.get("dirty_cleared") is not False:
                raise ReportError("clean foundation repair fabricated a dirty clear")
            if wal.get("write_boundaries") != 0 or wal.get("actions"):
                raise ReportError("clean foundation repair wrote the internal WAL")
            return
        if (
            int(batch_ledger.get("accepted_count"))
            + int(batch_ledger.get("rolled_back_count"))
            != int(batch_ledger.get("record_count"))
            or batch_ledger.get("refused_count") != 0
            or batch_ledger.get("rescan_count") != batch_ledger.get("record_count")
        ):
            raise ReportError(
                "successful repair does not bind one fresh rescan to every recovered/committed batch"
            )
        if not (foundation or metadata_count) and recovered_count == 0:
            if len(rescans) != 1 or rescans[0].get("stage") != "FINAL":
                raise ReportError("dirty-only repair must have only its FINAL rescan")
            if not reconstructed_degraded and (
                initial.get("exit_code") != 2
                or initial.get("dirty") is not True
                or initial.get("logfile_clean") is not True
                or initial.get("identity_valid") is not True
            ):
                raise ReportError("dirty-only initial scan did not prove structural/log/identity health")
        recovered_dirty_clear_only = (
            recovered_count > 0
            and not new_transactions
            and operations == 0
            and int(batch_ledger.get("record_count")) == recovered_count
            and int(batch_ledger.get("dirty_clear_count")) == recovered_count
            and all(
                sample.get("phase") == "DIRTY_CLEAR"
                and sample.get("origin") == "RECOVERED_COMMITTED"
                and sample.get("result") == "accepted"
                for sample in batch_samples
            )
        )
        if recovered_dirty_clear_only:
            if report.get("dirty_cleared") is not False:
                raise ReportError(
                    "recovered-only DIRTY_CLEAR fabricated a new dirty-clear claim"
                )
            if final.get("dirty") is not False:
                raise ReportError(
                    "recovered-only DIRTY_CLEAR lacks a fresh clean-volume result"
                )
            return
        if report.get("dirty_cleared") is not True:
            raise ReportError("mutating repair did not report dirty clear")
        if (
            int(batch_ledger.get("dirty_clear_count")) < 1
            or int(batch_ledger.get("dirty_clear_action_count")) < 2
            or batch_ledger.get("last_phase") != "DIRTY_CLEAR"
        ):
            raise ReportError("mutating repair lacks paired final DIRTY_CLEAR")
        dirty_transaction = batch_samples[-1]
        if (
            dirty_transaction.get("phase") != "DIRTY_CLEAR"
            or dirty_transaction.get("origin") != "NEW"
            or dirty_transaction.get("by_action_id") != {"25": 2}
        ):
            raise ReportError("final RHTXN3 sample is not the dirty-clear pair")
        final_rescan = rescans[-1]
        if (
            final_rescan.get("binding") != "TRANSACTION"
            or final_rescan.get("transaction_uuid") != dirty_transaction.get("transaction_uuid")
            or final_rescan.get("plan_hash") != dirty_transaction.get("plan_hash")
        ):
            raise ReportError("FINAL rescan is not bound to the DIRTY_CLEAR transaction")


def validate_rejection(
    report: dict[str, object],
    expected_exit: int,
    expected_wal: str,
    expected_journal_uuid: str,
    expected_volume_serial: str,
) -> None:
    context = validate_common(report, expected_journal_uuid, expected_volume_serial)
    if report.get("exit_code") != expected_exit:
        raise ReportError(
            f"rejection report exit differs: expected {expected_exit}, got {report.get('exit_code')!r}"
        )
    plan = context["plan"]
    commit = context["commit"]
    repairs = context["repairs"]
    foundation = context["foundation"]
    transactions = context["transactions"]
    rescans = context["rescans"]
    native_log = context["native_log"]
    assert isinstance(plan, dict) and isinstance(commit, dict)
    assert isinstance(repairs, list) and isinstance(foundation, list)
    assert isinstance(transactions, list) and isinstance(rescans, list)
    assert isinstance(native_log, dict)
    if foundation:
        raise ReportError("rejected repair performed a foundation write")
    if transactions:
        action_counts = transactions[0].get("by_action_id") if len(transactions) == 1 else None
        if (
            native_log.get("state") != "REPLAY_PLANNED"
            or len(transactions) != 1
            or transactions[0].get("origin") != "NEW"
            or transactions[0].get("kind") != "METADATA_REPAIR"
            or transactions[0].get("result") != "refused"
            or not isinstance(action_counts, dict)
            or not action_counts
            or any(action_id not in ("5", "6") for action_id in action_counts)
        ):
            raise ReportError("rejected repair retained a non-native write plan")
    elif repairs or plan.get("operations") or plan.get("bytes"):
        raise ReportError("zero-plan rejection fabricated a transaction")
    if (
        commit.get("started") is not False
        or commit.get("completed") is not False
        or commit.get("last_verified_ordinal") != 0
        or commit.get("syncs") != 0
        or commit.get("write_boundaries") != 0
    ):
        raise ReportError("rejected repair entered commit")
    if report.get("dirty_cleared") is not False:
        raise ReportError("rejected repair cleared the dirty flag")
    if rescans:
        raise ReportError("early rejection fabricated a fresh rescan")
    final = report.get("final")
    if not isinstance(final, dict) or final.get("completed") is not False:
        raise ReportError("early rejection fabricated a completed final snapshot")
    wal = report["wal"]
    assert isinstance(wal, dict)
    if wal.get("write_boundaries") != 0 or wal.get("recovered") is not False:
        raise ReportError("rejected repair wrote or recovered the internal WAL")
    if wal.get("actions"):
        raise ReportError("rejected repair fabricated raw WAL actions")
    if expected_wal == "unchecked":
        if wal.get("checked") is not False:
            raise ReportError("wrong-root rejection probed WAL before the identity barrier")
        for field in (
            "present",
            "valid",
            "state",
            "generation",
            "recovery_required",
            "journal_uuid",
            "volume_serial",
            "transaction_kind",
            "max_entry_count",
            *LOCATOR_FIELDS,
        ):
            if wal.get(field) is not None:
                raise ReportError(f"unchecked rejection fabricated wal.{field}")
    elif expected_wal == "invalid":
        if (
            wal.get("checked") is not True
            or wal.get("present") is not True
            or wal.get("valid") is not False
        ):
            raise ReportError("malformed-journal rejection did not identify an invalid WAL")
        for field in (
            "state",
            "generation",
            "recovery_required",
            "journal_uuid",
            "volume_serial",
            "transaction_kind",
            "max_entry_count",
        ):
            if wal.get(field) is not None:
                raise ReportError(f"invalid WAL rejection fabricated wal.{field}")
        if (
            wal.get("fast_path_trusted") is not False
            or wal.get("fallback_attempted") is not False
            or wal.get("fallback_ambiguous") is not False
            or wal.get("unreadable_record_count") != 0
            or wal.get("definite_duplicate_count") != 0
        ):
            raise ReportError("invalid WAL locator retained trust or ambiguous evidence")
    elif expected_wal == "partial":
        if (
            wal.get("checked") is not True
            or wal.get("present") is not True
            or wal.get("valid") is not None
            or wal.get("state") is not None
            or wal.get("generation") is not None
            or wal.get("recovery_required") is not None
            or wal.get("journal_uuid") is not None
            or wal.get("volume_serial") is not None
            or wal.get("transaction_kind") is not None
            or wal.get("max_entry_count") is not None
            or wal.get("fast_path_trusted") is not False
            or wal.get("fallback_attempted") is not False
            or wal.get("fallback_ambiguous") is not False
            or wal.get("write_boundaries") != 0
        ):
            raise ReportError("partial WAL rejection fabricated validated or trusted state")
    elif expected_wal == "empty":
        require_bound_wal(report, expected_journal_uuid, expected_volume_serial)
        if wal.get("state") != "EMPTY" or wal.get("recovery_required") is not False:
            raise ReportError("rejected repair advanced or left a nonempty internal WAL")
    elif expected_wal == "untrusted-empty":
        if (
            wal.get("checked") is not True
            or wal.get("present") is not True
            or wal.get("valid") is not True
            or wal.get("state") != "EMPTY"
            or wal.get("transaction_kind") != "NONE"
            or wal.get("recovery_required") is not False
            or wal.get("fast_path_trusted") is not False
            or wal.get("fallback_attempted") is not False
            or wal.get("fallback_ambiguous") is not False
            or wal.get("unreadable_record_count") != 0
            or wal.get("definite_duplicate_count") != 0
            or wal.get("write_boundaries") != 0
        ):
            raise ReportError("identity rejection did not preserve an observed, untrusted EMPTY WAL")
    elif expected_wal == "degraded":
        require_bound_wal(report, expected_journal_uuid, expected_volume_serial)
        if wal.get("state") != "EMPTY" or wal.get("recovery_required") is not True:
            raise ReportError("degraded-WAL rejection did not preserve recovery-required EMPTY state")
    elif expected_wal == "interrupted":
        require_bound_wal(report, expected_journal_uuid, expected_volume_serial)
        if wal.get("state") == "EMPTY" or wal.get("recovery_required") is not True:
            raise ReportError("rejected interrupted repair did not preserve recovery-required WAL")
    else:
        raise ReportError(f"unsupported rejected WAL expectation {expected_wal!r}")


def validate_check(
    report: dict[str, object],
    expected_exit: int,
    expected_state: str,
    expected_journal_uuid: str,
    expected_volume_serial: str,
) -> None:
    require_exact_fields(report, TOP_LEVEL_FIELDS, "report")
    if report.get("format") != 3 or report.get("mode") != "check":
        raise ReportError("read-only report must use format 3 and mode 'check'")
    require_bounded_utf8(
        report.get("checker_version"), "checker_version", MAX_VERSION_TEXT_BYTES
    )
    require_release_checker(report.get("checker"))
    require_bool(report.get("dirty_cleared"), "dirty_cleared")
    if report.get("exit_code") != expected_exit:
        raise ReportError(
            f"read-only report exit differs: expected {expected_exit}, "
            f"got {report.get('exit_code')!r}"
        )
    validate_device(report)
    validate_identity(report)
    validate_issues(report)
    initial = validate_snapshot(report.get("initial"), "initial")
    native_log = validate_native_log(report.get("native_log"), "native_log")
    if initial.get("native_log_state") != native_log.get("state"):
        raise ReportError("read-only native-log state differs from detailed evidence")
    if native_log.get("state") == "REPLAY_PLANNED":
        raise ReportError("read-only check cannot publish REPLAY_PLANNED")
    if initial.get("exit_code") != expected_exit or report.get("result") != initial.get("result"):
        raise ReportError("read-only top-level result differs from its public scan")
    if (
        report.get("foundation_repairs") != []
        or report.get("batch_samples") != []
        or report.get("repairs") != []
        or "transactions" in report
        or "rescans" in report
    ):
        raise ReportError("read-only check fabricated repair arrays")
    batch_ledger, batch_samples = validate_batch_ledger(report)
    if batch_ledger.get("record_count") != 0 or batch_samples:
        raise ReportError("read-only check fabricated an RHTXN3 phase")
    plan = report.get("plan")
    commit = report.get("commit")
    if not isinstance(plan, dict) or not isinstance(commit, dict):
        raise ReportError("read-only check lacks plan/commit objects")
    if plan != {
        "operations": 0,
        "bytes": 0,
        "priority_operations": 0,
        "foundation_operations": 0,
        "foundation_bytes": 0,
        "wal_operations": 0,
        "wal_bytes": 0,
        "by_action_id": {},
        "by_kind": {},
        "bytes_by_action_id": {},
        "bytes_by_kind": {},
    }:
        raise ReportError("read-only check has a nonzero or malformed plan")
    if commit != {
        "started": False,
        "completed": False,
        "last_verified_ordinal": 0,
        "syncs": 0,
        "write_boundaries": 0,
    }:
        raise ReportError("read-only check has a nonzero or malformed commit")
    final = validate_snapshot(report.get("final"), "final")
    rescans = [final]
    validate_execution_chain(initial, rescans, self_exec_rescans=False)
    if (
        len(rescans) != 1
        or rescans[0].get("stage") != "FINAL"
        or rescans[0].get("binding") != "INITIAL"
        or rescans[0].get("scan_id") != initial.get("scan_id")
    ):
        raise ReportError("read-only check did not alias its one public scan")
    for field in (
        "completed",
        "scan_id",
        "execution",
        "fresh_process",
        "read_only",
        "exit_code",
        "result",
        "dirty",
        "logfile_clean",
        "native_log_state",
        "identity_valid",
        "coverage",
    ):
        if rescans[0].get(field) != initial.get(field):
            raise ReportError(f"read-only initial/FINAL scan differs in {field}")
    if expected_exit == 0:
        require_complete_coverage(initial["coverage"], "initial.coverage")
    if report.get("dirty_cleared") is not False:
        raise ReportError("read-only check claims dirty-state mutation")
    if expected_state == "IO_ERROR":
        wal = wal_object(report)
        if (
            expected_exit != 3
            or initial.get("completed") is not False
            or initial.get("result") != "io-error"
            or wal.get("recovered") is not False
            or wal.get("write_boundaries") != 0
            or wal.get("actions")
        ):
            raise ReportError("read-only I/O uncertainty fabricated WAL or completion evidence")
        if wal.get("checked") is True:
            partial_wal = (
                wal.get("present") is True
                and wal.get("valid") is None
                and wal.get("state") is None
                and wal.get("fast_path_trusted") is False
                and wal.get("fallback_attempted") is False
                and wal.get("fallback_ambiguous") is False
            )
            complete_empty_wal = (
                wal.get("present") is True
                and wal.get("valid") is True
                and wal.get("state") == "EMPTY"
                and wal.get("recovery_required") is False
                and wal.get("transaction_kind") == "NONE"
            )
            if not (partial_wal or complete_empty_wal):
                raise ReportError("read-only I/O uncertainty has inconsistent partial WAL evidence")
        elif wal.get("checked") is False:
            for field in ("present", *LOCATOR_FIELDS):
                if wal.get(field) is not None:
                    raise ReportError(f"read-only pre-WAL I/O fabricated wal.{field}")
        else:
            raise ReportError("read-only I/O uncertainty has non-boolean wal.checked")
        return
    if expected_state == "PARTIAL":
        wal = wal_object(report)
        if (
            expected_exit != 2
            or wal.get("checked") is not True
            or wal.get("present") is not True
            or wal.get("valid") is not None
            or wal.get("state") is not None
            or wal.get("generation") is not None
            or wal.get("recovery_required") is not None
            or wal.get("journal_uuid") is not None
            or wal.get("volume_serial") is not None
            or wal.get("transaction_kind") is not None
            or wal.get("max_entry_count") is not None
            or wal.get("recovered") is not False
            or wal.get("fast_path_trusted") is not False
            or wal.get("fallback_attempted") is not False
            or wal.get("fallback_ambiguous") is not False
            or wal.get("write_boundaries") != 0
            or wal.get("actions")
        ):
            raise ReportError("read-only unsafe scan fabricated partial WAL state")
        return
    if expected_state == "UNCHECKED":
        wal = wal_object(report)
        if (
            expected_exit != 2
            or wal.get("checked") is not False
            or wal.get("recovered") is not False
            or wal.get("write_boundaries") != 0
            or wal.get("actions")
        ):
            raise ReportError("read-only unsafe scan fabricated unchecked WAL state")
        for field in ("present", *LOCATOR_FIELDS):
            if wal.get(field) is not None:
                raise ReportError(f"read-only pre-WAL unsafe scan fabricated wal.{field}")
        return
    if expected_state == "INVALID":
        wal = wal_object(report)
        if (
            expected_exit != 2
            or wal.get("checked") is not True
            or wal.get("present") is not True
            or wal.get("valid") is not False
            or wal.get("recovered") is not False
            or wal.get("write_boundaries") != 0
        ):
            raise ReportError("invalid WAL did not map to zero-write unsafe exit 2")
        if wal.get("write_boundaries") != 0 or wal.get("recovered") is not False:
            raise ReportError("read-only invalid WAL scan wrote/recovered state")
        for field in (
            "state",
            "generation",
            "recovery_required",
            "journal_uuid",
            "volume_serial",
            "transaction_kind",
            "max_entry_count",
        ):
            if wal.get(field) is not None:
                raise ReportError(f"invalid WAL scan fabricated wal.{field}")
        if (
            wal.get("fast_path_trusted") is not False
            or wal.get("fallback_attempted") is not False
            or wal.get("fallback_ambiguous") is not False
            or wal.get("unreadable_record_count") != 0
            or wal.get("definite_duplicate_count") != 0
        ):
            raise ReportError("invalid WAL scan retained trust or ambiguous locator evidence")
        return
    wal = require_bound_wal(report, expected_journal_uuid, expected_volume_serial)
    if wal.get("write_boundaries") != 0 or wal.get("recovered") is not False:
        raise ReportError("read-only check advanced or recovered WAL state")
    if expected_state == "EMPTY":
        if wal.get("state") != "EMPTY" or wal.get("recovery_required") is not False:
            raise ReportError("read-only scan did not prove an EMPTY WAL")
    elif expected_state == "RECOVERY_REQUIRED":
        if wal.get("state") == "EMPTY" or wal.get("recovery_required") is not True:
            raise ReportError("interrupted repair WAL did not fail closed as recovery-required")
        if expected_exit != 2:
            raise ReportError("a valid non-EMPTY WAL must map to unsafe exit 2")
    elif expected_state == "DEGRADED":
        if (
            expected_exit != 2
            or wal.get("state") not in (
                "EMPTY", "PREPARING", "APPLYING", "COMMITTED", "ROLLBACK"
            )
            or wal.get("recovery_required") is not True
            or wal.get("recovered") is not False
            or wal.get("write_boundaries") != 0
        ):
            raise ReportError(
                "one-valid/one-torn WAL did not expose zero-write degraded recovery"
            )
    else:
        raise ReportError(f"unsupported expected check WAL state {expected_state!r}")


def validate_early_io(report: dict[str, object]) -> None:
    require_exact_fields(report, TOP_LEVEL_FIELDS, "report")
    if report.get("format") != 3 or report.get("mode") != "repair":
        raise ReportError("early I/O report must use format 3 and mode 'repair'")
    if report.get("result") != "io-error" or report.get("exit_code") != 3:
        raise ReportError("early I/O report must use result io-error and exit 3")
    require_release_checker(report.get("checker"))
    require_bounded_utf8(
        report.get("checker_version"), "checker_version", MAX_VERSION_TEXT_BYTES
    )
    require_bool(report.get("dirty_cleared"), "dirty_cleared")
    validate_device(report)
    initial = validate_snapshot(report.get("initial"), "initial")
    native_log = validate_native_log(report.get("native_log"), "native_log")
    native_unchecked = (
        native_log.get("checked") is False
        and initial.get("native_log_state") is None
    )
    native_checked_clean = (
        native_log.get("checked") is True
        and native_log.get("state") in ("CLEAN_RESTART", "EMPTY_T1OS")
        and initial.get("native_log_state") == native_log.get("state")
        and native_log.get("planned_io_operations") == 0
        and native_log.get("planned_io_bytes") == 0
        and native_log.get("io_errors") == 0
        and native_log.get("parse_errors") == 0
        and native_log.get("unsupported_actions") == 0
    )
    if not (native_unchecked or native_checked_clean):
        raise ReportError("I/O report has inconsistent native-log evidence")
    if initial.get("result") not in (None, "io-error"):
        raise ReportError("early I/O initial snapshot has an unrelated result")
    validate_issues(report)
    identity = validate_identity(report)
    identity_unchecked = (
        identity.get("prewrite_checked") is False
        and identity.get("prewrite_valid") is None
    )
    identity_valid = (
        identity.get("prewrite_checked") is True
        and identity.get("prewrite_valid") is True
        and initial.get("identity_valid") is True
    )
    if not (identity_unchecked or identity_valid):
        raise ReportError("I/O report has inconsistent pre-write identity evidence")
    plan = report.get("plan")
    commit = report.get("commit")
    repairs = report.get("repairs")
    if not isinstance(plan, dict) or not isinstance(commit, dict) or not isinstance(repairs, list):
        raise ReportError("early I/O report lacks plan/commit/repair containers")
    require_exact_fields(plan, PLAN_FIELDS, "plan")
    require_exact_fields(commit, COMMIT_FIELDS, "commit")
    if (
        plan.get("operations") != 0
        or plan.get("bytes") != 0
        or plan.get("priority_operations") != 0
        or plan.get("foundation_operations") != 0
        or plan.get("foundation_bytes") != 0
        or plan.get("wal_operations") != 0
        or plan.get("wal_bytes") != 0
        or plan.get("by_action_id") != {}
        or plan.get("by_kind") != {}
        or plan.get("bytes_by_action_id") != {}
        or plan.get("bytes_by_kind") != {}
    ):
        raise ReportError("early I/O failure produced a repair plan")
    if (
        commit.get("started") is not False
        or commit.get("completed") is not False
        or commit.get("last_verified_ordinal") != 0
        or commit.get("syncs") != 0
        or commit.get("write_boundaries") != 0
        or repairs
    ):
        raise ReportError("early I/O failure entered a repair commit")
    if report.get("dirty_cleared") is not False:
        raise ReportError("early I/O failure cleared dirty state")
    batch_ledger, batch_samples = validate_batch_ledger(report)
    if (
        report.get("foundation_repairs") != []
        or batch_ledger.get("record_count") != 0
        or batch_samples
        or "transactions" in report
        or "rescans" in report
    ):
        raise ReportError("early I/O failure fabricated repair orchestration")
    final = validate_snapshot(report.get("final"), "final")
    if final.get("completed") is not False:
        raise ReportError("early I/O failure fabricated a completed final snapshot")
    validate_execution_chain(initial, [], self_exec_rescans=True)
    if final.get("execution") != initial.get("execution"):
        raise ReportError("early I/O final snapshot changed initial execution identity")
    wal = wal_object(report)
    if wal.get("checked") not in (False, True) or wal.get("recovered") is not False:
        raise ReportError("early I/O failure claimed WAL recovery")
    if wal.get("write_boundaries") != 0:
        raise ReportError("early I/O failure wrote the internal WAL")
    if wal.get("checked") is True:
        partial_wal = (
            wal.get("present") is True
            and wal.get("valid") is None
            and wal.get("state") is None
            and wal.get("generation") is None
            and wal.get("recovery_required") is None
            and wal.get("journal_uuid") is None
            and wal.get("volume_serial") is None
            and wal.get("transaction_kind") is None
            and wal.get("max_entry_count") is None
            and wal.get("fast_path_trusted") is False
            and wal.get("fallback_attempted") is False
            and wal.get("fallback_ambiguous") is False
            and wal.get("unreadable_record_count") == 0
            and wal.get("definite_duplicate_count") == 0
        )
        complete_empty_wal = (
            wal.get("present") is True
            and wal.get("valid") is True
            and wal.get("state") == "EMPTY"
            and wal.get("recovery_required") is False
            and wal.get("transaction_kind") == "NONE"
        )
        if not (partial_wal or complete_empty_wal):
            raise ReportError("I/O failure has inconsistent WAL evidence")
    else:
        for field in ("present", *LOCATOR_FIELDS):
            if wal.get(field) is not None:
                raise ReportError(f"early I/O failure fabricated wal.{field}")


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        try:
            coverage_negative_count = coverage_self_test()
            complete_coverage_negative_count = complete_coverage_self_test()
            execution_negative_count = execution_self_test()
            identity_negative_count = identity_self_test()
            foundation_negative_count = foundation_self_test()
            native_order_negative_count = native_action_order_self_test()
            native_log_negative_count = native_log_self_test()
            native_replay_negative_count = native_replay_reconciliation_self_test()
            bounded_ledger_negative_count = bounded_ledger_self_test()
            schema_field_negative_count, schema_numeric_negative_count = (
                schema_closure_self_test()
            )
            print(
                "roothealth format-3 report self-test passed: "
                "coverage=1-known-vector+1-json-order+"
                f"{coverage_negative_count}-negative "
                "complete-coverage=1-positive+"
                f"{complete_coverage_negative_count}-negative "
                f"execution=2-positive+{execution_negative_count}-negative "
                f"identity=2-positive+{identity_negative_count}-negative "
                f"foundation=1-positive+{foundation_negative_count}-negative "
                "native-order=3-positive+"
                f"{native_order_negative_count}-negative "
                "native-log=6-positive+"
                f"{native_log_negative_count}-negative "
                "native-replay=1-positive+"
                f"{native_replay_negative_count}-negative "
                "bounded-ledgers=4-known-vectors+1-max-envelope+"
                f"{bounded_ledger_negative_count}-negative "
                f"schema-closure={schema_field_negative_count}-field+"
                f"{schema_numeric_negative_count}-numeric-negative"
            )
            return 0
        except ReportError as error:
            print(
                f"roothealth format-3 coverage-ledger self-test failed: {error}",
                file=sys.stderr,
            )
            return 1
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--expected-kind", action="append", default=[])
    parser.add_argument("--noop", action="store_true")
    parser.add_argument("--wal-recovery-only", action="store_true")
    parser.add_argument("--rejection-exit", type=int)
    parser.add_argument(
        "--rejection-wal",
        choices=("unchecked", "invalid", "partial", "empty", "untrusted-empty", "degraded", "interrupted"),
        default="unchecked",
    )
    parser.add_argument("--early-io", action="store_true")
    parser.add_argument(
        "--check-state",
        choices=(
            "EMPTY", "RECOVERY_REQUIRED", "INVALID", "DEGRADED",
            "PARTIAL", "UNCHECKED", "IO_ERROR",
        ),
    )
    parser.add_argument("--expected-exit", type=int)
    parser.add_argument("--expected-journal-uuid", default="")
    parser.add_argument("--expected-volume-serial", default="")
    parser.add_argument("--expected-requested-path")
    parser.add_argument("--expected-resolved-path")
    parser.add_argument(
        "--expected-requested-symlink", choices=("true", "false")
    )
    args = parser.parse_args()
    try:
        report_size = args.report.stat().st_size
        if report_size > REPORT_SIZE_LIMIT:
            raise ReportError("report exceeds the 4 MiB qualification ceiling")
        report = json.loads(args.report.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ReportError("repair report root must be an object")
        validate_report_budget(report, report_size)
        if (
            args.expected_requested_path is not None
            or args.expected_resolved_path is not None
            or args.expected_requested_symlink is not None
        ):
            device = validate_device(report)
            if (
                args.expected_requested_path is not None
                and device.get("requested_path") != args.expected_requested_path
            ):
                raise ReportError("device.requested_path differs from the invocation")
            if (
                args.expected_resolved_path is not None
                and device.get("resolved_path") != args.expected_resolved_path
            ):
                raise ReportError("device.resolved_path differs from the attested node")
            if args.expected_requested_symlink is not None and device.get(
                "requested_was_symlink"
            ) is not (args.expected_requested_symlink == "true"):
                raise ReportError("device.requested_was_symlink differs")
        if args.early_io:
            if args.check_state is not None or args.rejection_exit is not None or args.noop or args.wal_recovery_only or args.expected_kind:
                raise ReportError("early-I/O validation cannot use other outcome assertions")
            validate_early_io(report)
        elif args.check_state is not None:
            if args.expected_exit is None:
                raise ReportError("--check-state requires --expected-exit")
            if args.rejection_exit is not None or args.noop or args.wal_recovery_only or args.expected_kind:
                raise ReportError("check-report validation cannot use repair assertions")
            validate_check(
                report,
                args.expected_exit,
                args.check_state,
                args.expected_journal_uuid,
                args.expected_volume_serial,
            )
        elif args.rejection_exit is None:
            validate_success(
                report,
                args.expected_kind,
                args.noop,
                args.wal_recovery_only,
                args.expected_journal_uuid,
                args.expected_volume_serial,
            )
        else:
            validate_rejection(
                report,
                args.rejection_exit,
                args.rejection_wal,
                args.expected_journal_uuid,
                args.expected_volume_serial,
            )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ReportError) as error:
        print(f"roothealth repair report validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
