#!/usr/bin/env bash
# shellcheck disable=SC2016 # Literal NTFS system names intentionally contain '$'.
set -euo pipefail

repair_checker=$1
check_checker=$2
fixtures=$3
fault_source=$4
report_validator=$5
policy_checker=$6
io_closure_checker=$7
journal_validator=$8
ntfscp_tool=$9
wal_fixtures=${10}
problem_header=${11:-}
policy_source=${12:-}
engine_source=${13:-}
engine_manifest=${14:-}
policy_audit_checker=${15}
policy_implementation_checker=${16}
policy_audit=${17}
native_redo_fixture=${18}
native_log_corpus=${19}
native_replay_proposal_checker=${20}
native_replay_proposal=${21}
powercut_materializer=${22}
native_empty_fixture=${23}

for optional_name in problem_header policy_source engine_source engine_manifest; do
    if [ "${!optional_name}" = __ROOTHEALTH_EMPTY_ARGUMENT__ ]; then
        printf -v "$optional_name" %s ''
    fi
done

export LC_ALL=C
export PYTHONDONTWRITEBYTECODE=1
umask 077

required_commands=(
    awk bash blockdev cc cmp cp dd find grep head ln losetup mkdir mkfs.ntfs mktemp mv
    mount.ntfs-3g ntfscat ntfsinfo python3 readlink rm rmdir sed seq sha256sum
    sleep stat strace sync timeout truncate umount
)
missing=()
for command_name in "${required_commands[@]}"; do
    command -v "$command_name" >/dev/null 2>&1 || missing+=("$command_name")
done
if [ "${#missing[@]}" -ne 0 ]; then
    printf 'Missing roothealth repair-test commands: %s\n' "${missing[*]}" >&2
    exit 127
fi
for required_file in \
        "$repair_checker" "$check_checker" "$fixtures" "$fault_source" \
        "$report_validator" "$policy_checker" "$io_closure_checker" \
        "$journal_validator" "$wal_fixtures"; do
    [ -f "$required_file" ] || {
        echo "Required roothealth repair-test input is absent: $required_file" >&2
        exit 1
    }
done
for required_file in "$native_redo_fixture" "$native_log_corpus" \
        "$native_replay_proposal_checker" "$native_replay_proposal" \
        "$powercut_materializer" "$native_empty_fixture"; do
    [ -f "$required_file" ] || {
        echo "Required native-log qualification input is absent: $required_file" >&2
        exit 1
    }
done
python3 -B "$powercut_materializer" --self-test
python3 -B "$report_validator" --self-test
for required_file in "$policy_audit_checker" "$policy_implementation_checker" \
        "$policy_audit"; do
    [ -f "$required_file" ] || {
        echo "Required roothealth repair policy audit input is absent: $required_file" >&2
        exit 1
    }
done
command -v "$ntfscp_tool" >/dev/null 2>&1 || {
    echo "The selected pinned ntfscp is unavailable: $ntfscp_tool" >&2
    exit 127
}
[ -x "$repair_checker" ] || {
    echo "Repair checker is not executable: $repair_checker" >&2
    exit 1
}
[ -x "$check_checker" ] || {
    echo "Read-only checker is not executable: $check_checker" >&2
    exit 1
}

set +e
repair_help=$("$repair_checker" --help 2>&1)
repair_help_exit=$?
set -e
if [ "$repair_help_exit" -ne 0 ] || \
        ! printf '%s\n' "$repair_help" | grep -Eq -- '(^|[[:space:]])--repair([=[:space:]]|$)' || \
        ! printf '%s\n' "$repair_help" | grep -Eq -- '(^|[[:space:]])--expected-serial([=[:space:]]|$)' || \
        ! printf '%s\n' "$repair_help" | grep -Eq -- '(^|[[:space:]])--expected-journal-uuid([=[:space:]]|$)' || \
        ! printf '%s\n' "$repair_help" | grep -Eq -- '(^|[[:space:]])--expected-journal-record([=[:space:]]|$)'; then
    echo 'roothealth does not expose the required explicit --repair capability.' >&2
    echo 'Repair qualification is mandatory and was not skipped.' >&2
    printf '%s\n' "$repair_help" >&2
    exit 1
fi
if printf '%s\n' "$repair_help" | \
        grep -Eq -- '--repair-auto|--repair-yes|--repair-no|auto-repair'; then
    echo 'roothealth exposes forbidden generic/yes-all repair controls.' >&2
    exit 1
fi
set +e
check_help=$("$check_checker" --help 2>&1)
check_help_exit=$?
set -e
if [ "$check_help_exit" -ne 0 ] || \
        ! printf '%s\n' "$check_help" | grep -Eq -- '(^|[[:space:]])--check([=[:space:]]|$)' || \
        ! printf '%s\n' "$check_help" | grep -Eq -- '(^|[[:space:]])--expected-serial([=[:space:]]|$)' || \
        ! printf '%s\n' "$check_help" | grep -Eq -- '(^|[[:space:]])--expected-journal-uuid([=[:space:]]|$)' || \
        ! printf '%s\n' "$check_help" | grep -Eq -- '(^|[[:space:]])--expected-journal-record([=[:space:]]|$)'; then
    echo 'roothealth read-only mode does not expose the required bound WAL identity.' >&2
    printf '%s\n' "$check_help" >&2
    exit 1
fi
if [ -z "$problem_header" ] || [ -z "$policy_source" ] || \
        [ -z "$engine_source" ] || [ ! -f "$problem_header" ] || \
        [ ! -f "$policy_source" ] || [ ! -e "$engine_source" ]; then
    echo 'Repair qualification requires ntfs-next problem.h, roothealth policy, and engine source.' >&2
    echo 'Pass -ProblemHeaderPath, -PolicySourcePath, and -EngineSourcePath.' >&2
    exit 1
fi
if [ -z "$engine_manifest" ] || [ ! -f "$engine_manifest" ]; then
    echo 'Repair qualification requires the exact roothealth linked translation-unit manifest.' >&2
    echo 'Pass -EngineManifestPath from the production build.' >&2
    exit 1
fi
python3 "$policy_checker" "$problem_header" "$policy_source" \
    --translation-unit-manifest "$engine_manifest" "$engine_source"
python3 "$policy_audit_checker" "$policy_audit" "$problem_header"
python3 "$policy_implementation_checker" "$policy_audit" "$policy_source" \
    "$engine_source" "$engine_manifest"
python3 "$io_closure_checker" "$engine_source" "$engine_manifest"
python3 "$native_redo_fixture" self-test --tree "$engine_source"
python3 -B "$native_empty_fixture" self-test --tree "$engine_source"
NATIVE_REPLAY_PROPOSAL=$native_replay_proposal ENGINE_SOURCE=$engine_source python3 -B - <<'PY'
import json
import os
from pathlib import Path

manifest = json.loads(Path(os.environ["NATIVE_REPLAY_PROPOSAL"]).read_text())
if manifest.get("release_qualified") is not True or \
        manifest.get("status") != "QUALIFIED_BOUNDED_NATIVE_REPLAY":
    raise SystemExit(
        "native replay qualification: bounded immutable-preimage replay is not qualified"
    )
blockers = {item.get("id") for item in manifest.get("blockers", [])}
if "NATIVE_ID5_ID6_WAL_REDERIVATION_NOT_MERGED" in blockers:
    raise SystemExit("native replay qualification: the merged ID5/ID6 blocker remains")
if "OP2_IMMUTABLE_SLOT_AUTHORITY_NOT_MERGED" not in blockers:
    raise SystemExit("native replay qualification: the remaining op2 boundary was erased")

wal = (Path(os.environ["ENGINE_SOURCE"]) / "src/roothealth_wal.c").read_text()
for token in (
    "RH_WRITE_INDEX_ROOT",
    "RH_WRITE_INDEX_BITMAP",
    "RH_WRITE_BITMAP_MFT",
    "RH_WRITE_BITMAP_CLUSTER",
    "RH_WRITE_VOLUME_DIRTY_SET",
    "RH_WRITE_VOLUME_DIRTY_CLEAR",
):
    if token not in wal:
        raise SystemExit(f"recovery registry: implemented action missing: {token}")
for token in (
    "rh_wal_builtin_native_replay_verify",
    "roothealth_log_replay_plan_mounted",
    "rh_complete_census_run",
    "RH_WRITE_LOGFILE_REDO",
    "RH_WRITE_LOGFILE_RESTART",
):
    if token not in wal:
        raise SystemExit(f"native replay qualification: rederivation token missing: {token}")
print("bounded native replay qualified; immutable-preimage ID5/ID6 rederivation present")
PY

work=$(mktemp -d /var/tmp/roothealth-repair-test.XXXXXX)
case "$work" in
    /var/tmp/roothealth-repair-test.*) ;;
    *) echo "Unexpected repair-test path: $work" >&2; exit 1 ;;
esac
active_loop=
secondary_loop=
mounted=0
mount_root=
cleanup() {
    cleanup_status=$?
    set +e
    cleanup_failed=0
    if [ "$mounted" = 1 ] && [ -n "$mount_root" ]; then
        if umount "$mount_root"; then
            mounted=0
        else
            cleanup_failed=1
        fi
    fi
    if [ "$mounted" = 0 ] && [ -n "$active_loop" ]; then
        if losetup --detach "$active_loop"; then
            active_loop=
        else
            cleanup_failed=1
        fi
    fi
    if [ "$mounted" = 0 ] && [ -n "$secondary_loop" ]; then
        if losetup --detach "$secondary_loop"; then
            secondary_loop=
        else
            cleanup_failed=1
        fi
    fi
    if [ "$cleanup_status" -ne 0 ] || [ "${ROOTHEALTH_KEEP_WORK:-0}" = 1 ] ||
            [ -e "$work/.preserve" ]; then
        echo "Preserved roothealth repair-test workspace: $work" >&2
    elif [ "$cleanup_failed" = 0 ]; then
        case "$work" in
            /var/tmp/roothealth-repair-test.*) rm -rf -- "$work" ;;
        esac
    else
        echo "Could not completely clean roothealth repair-test workspace: $work" >&2
    fi
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

fault_library="$work/roothealth-write-fault.so"
cc -shared -fPIC -O2 -Wall -Wextra -Werror \
    -o "$fault_library" "$fault_source" -ldl

# Prove that the prewrite read-fault mode really intercepts the selected
# object and that an incomplete test configuration fails closed.  This helper
# smoke is deliberately independent of RootHealth so a broken LD_PRELOAD shim
# cannot turn the foundation I/O cases into false product evidence.
read_fault_probe="$work/read-fault-probe.bin"
truncate -s 4096 "$read_fault_probe"
read_fault_probe_before=$(sha256sum "$read_fault_probe" | awk '{print $1}')
set +e
env LD_PRELOAD="$fault_library" ROOTHEALTH_FAULT_MODE=read-fault \
    ROOTHEALTH_FAULT_TARGET="$read_fault_probe" \
    ROOTHEALTH_FAULT_READ_OFFSET=0 \
    dd if="$read_fault_probe" of=/dev/null bs=512 count=1 status=none \
    >"$work/read-fault-probe.log" 2>&1
read_fault_probe_status=$?
env LD_PRELOAD="$fault_library" ROOTHEALTH_FAULT_MODE=read-fault \
    ROOTHEALTH_FAULT_TARGET="$read_fault_probe" \
    dd if="$read_fault_probe" of=/dev/null bs=512 count=1 status=none \
    >"$work/read-fault-partial.log" 2>&1
read_fault_partial_status=$?
set -e
[ "$read_fault_probe_status" -ne 0 ] || {
    echo 'Read-fault observer did not inject EIO into the selected object.' >&2
    exit 1
}
[ "$read_fault_partial_status" -eq 125 ] || {
    echo "Partial read-fault configuration returned $read_fault_partial_status; expected 125." >&2
    exit 1
}
[ "$read_fault_probe_before" = "$(sha256sum "$read_fault_probe" | awk '{print $1}')" ] || {
    echo 'Read-fault observer smoke changed its selected object.' >&2
    exit 1
}
printf 'PASS read-fault-observer selected-eio=true partial-exit=125 writes=0\n'

base_image="$work/t1os-repair-base.ntfs"
ordinary_image="$work/ordinary-dirty.ntfs"
native_redo_base_image="$work/native-redo-base.ntfs"
native_redo_image="$work/native-redo.ntfs"
native_redo_powercut_source_image="$work/native-redo-powercut-source.ntfs"
native_redo_clean_source_image="$work/native-redo-clean-source.ntfs"
native_redo_clean_history_image="$work/native-redo-clean-history.ntfs"
native_redo_mirror_interrupt_image="$work/native-redo-mirror-interrupt.ntfs"
native_redo_clean_disagree_image="$work/native-redo-clean-disagree.ntfs"
native_redo_manifest="$work/native-redo.json"
mount_root="$work/mount"
mkdir -p "$mount_root"

format_and_mount() {
    image=$1
    size=$2
    label=$3
    truncate -s "$size" "$image"
    active_loop=$(losetup --find --show "$image")
    mkfs.ntfs -F -Q -L "$label" "$active_loop" >/dev/null
    mount.ntfs-3g -o rw,permissions,windows_names,big_writes \
        "$active_loop" "$mount_root"
    mounted=1
}

mount_existing_rw() {
    image=$1
    active_loop=$(losetup --find --show "$image")
    mount.ntfs-3g -o rw,permissions,windows_names,big_writes \
        "$active_loop" "$mount_root"
    mounted=1
}

finish_mount() {
    sync
    umount "$mount_root"
    mounted=0
    losetup --detach "$active_loop"
    active_loop=
}

assert_journal_locator_flags() {
    journal_report=$1
    fixture_name=$2
    python3 -B - "$journal_report" "$fixture_name" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1], encoding='utf-8'))
name = sys.argv[2]
journal = report.get('journal')
checks = report.get('checks')
if not isinstance(journal, dict) or not isinstance(checks, dict):
    raise SystemExit(f'{name} production fixture lacks journal flag evidence')
expected = '0x00002007'
fields = (
    'standard_information_flags',
    'file_name_flags',
    'extend_i30_file_name_flags',
    'required_protected_flags',
)
if any(journal.get(field) != expected for field in fields):
    raise SystemExit(
        f'{name} journal locator copies are not exact 0x2007: '
        f'{ {field: journal.get(field) for field in fields}!r}'
    )
if journal.get('protected_flags_present') is not True:
    raise SystemExit(f'{name} journal protected flags are not attested')
for field in ('file_flags_consistent', 'protected_file_flags',
              'extend_i30_flags_consistent'):
    if checks.get(field) is not True:
        raise SystemExit(f'{name} journal locator check failed: {field}')
PY
}

provision_journal() {
    image=$1
    fixture_name=$2
    seed="$work/$fixture_name.roothealth.seed"
    seed_report="$work/$fixture_name.roothealth-seed.json"
    journal_report="$work/$fixture_name.roothealth-journal.json"
    building="$image.building"
    [ ! -e "$building" ] || {
        echo "Journal build staging path already exists: $building" >&2
        exit 1
    }
    mv "$image" "$building"
    active_loop=$(losetup --find --show "$building")
    python3 "$journal_validator" seed "$active_loop" "$seed" \
        --report "$seed_report"
    "$ntfscp_tool" -f -m "$active_loop" "$seed" '$Extend/$RootHealth'
    sync
    mount.ntfs-3g -o rw,permissions,show_sys_files \
        "$active_loop" "$mount_root"
    mounted=1
    python3 - "$mount_root/\$Extend/\$RootHealth" <<'PY'
import os
from pathlib import Path
import struct
import sys

path = Path(sys.argv[1])
required = 0x00002007
os.setxattr(path, "system.ntfs_attrib", struct.pack("<I", required))
observed = struct.unpack("<I", os.getxattr(path, "system.ntfs_attrib"))[0]
if observed != required:
    raise SystemExit(
        f"journal protected attributes did not persist: 0x{observed:08x}"
    )
PY
    sync
    umount "$mount_root"
    mounted=0
    losetup --detach "$active_loop"
    active_loop=
    python3 "$journal_validator" provision-flags "$building" >/dev/null
    active_loop=$(losetup --find --show "$building")
    python3 "$journal_validator" validate "$active_loop" \
        --require-one-run --require-zero-entry-area --report "$journal_report"
    losetup --detach "$active_loop"
    active_loop=
    assert_journal_locator_flags "$journal_report" "$fixture_name"
    mv "$building" "$image"
}

format_and_mount "$base_image" 512M 'T1OS REPAIR TEST'
mkdir -p \
    "$mount_root/the one/software/python/bin" \
    "$mount_root/the one/build/GODDESS" \
    "$mount_root/the one/build/drivers" \
    "$mount_root/the one/settings/operations" \
    "$mount_root/the one/drivers/tools" \
    "$mount_root/the one/drivers/settings" \
    "$mount_root/the one/drivers/modules/test-kernel" \
    "$mount_root/the one/logs" \
    "$mount_root/the one/repair-index" \
    "$mount_root/the one/repair-payloads" \
    "$mount_root/the one/orphan-source" \
    "$mount_root/the one/recovered files/roothealth" \
    "$mount_root/the one/deep/collation-parent-a" \
    "$mount_root/the one/deep/collation-parent-b" \
    "$mount_root/the one/deep/compressed"
printf '#!/bin/sh\nexit 0\n' >"$mount_root/the one/software/python/bin/python"
printf '#!/bin/sh\nexit 0\n' >"$mount_root/the one/software/python/bin/python4.13"
printf '#!/bin/sh\nexit 0\n' >"$mount_root/the one/drivers/tools/modprobe"
chmod 0755 \
    "$mount_root/the one/software/python/bin/python" \
    "$mount_root/the one/software/python/bin/python4.13" \
    "$mount_root/the one/drivers/tools/modprobe"
printf 'print("repair fixture")\n' >"$mount_root/the one/build/GODDESS/GODDESS.py"
printf 'print("repair driver fixture")\n' >"$mount_root/the one/build/drivers/driverserver.py"
printf '' >"$mount_root/the one/settings/operations/operations.txt"
printf '{"format":1,"fixture":true}\n' \
    >"$mount_root/the one/settings/operations/completed.json"
printf '{"format":1,"repair_fixture":true}\n' \
    >"$mount_root/the one/drivers/settings/policy.json"
printf '%064d  test-kernel/modules.dep\n' 0 \
    >"$mount_root/the one/drivers/modules/module-manifest.sha256"
printf 'kernel/test.ko:\n' \
    >"$mount_root/the one/drivers/modules/test-kernel/modules.dep"
dd if=/dev/zero of="$mount_root/the one/repair-payloads/bitmap.bin" \
    bs=4096 count=128 status=none
printf 'bitmap allocation payload\n' | dd \
    of="$mount_root/the one/repair-payloads/bitmap.bin" conv=notrunc status=none
printf 'live MFT bitmap payload\n' \
    >"$mount_root/the one/repair-payloads/live-record.txt"
python3 - "$mount_root/the one/repair-payloads/journal-overlap.bin" <<'PY'
from pathlib import Path
import sys

Path(sys.argv[1]).write_bytes((b'ROOTHEALTH-JOURNAL-OWNER-ORACLE-' * 128)[:4096])
PY
printf 'attribute-list base stream\n' >"$mount_root/the one/deep/attrlist.bin"
ln "$mount_root/the one/deep/attrlist.bin" \
    "$mount_root/the one/deep/collation-parent-b/attrlist-shared.bin"
ln "$mount_root/the one/deep/attrlist.bin" \
    "$mount_root/the one/deep/collation-parent-a/attrlist-shared.bin"
printf 'user-defined attribute holder\n' >"$mount_root/the one/deep/user-defined.bin"
printf 'raw MFT layout candidate base value\n' \
    >"$mount_root/the one/deep/layout-candidate.bin"
python3 - "$mount_root/the one/deep/runlist-size.bin" <<'PY'
from pathlib import Path
import sys

Path(sys.argv[1]).write_bytes((b'RUNLIST-SIZE-ORACLE-' * 700)[:12345])
PY
python3 - "$mount_root/the one/deep" <<'PY'
import os
from pathlib import Path
import sys

directory = Path(sys.argv[1])
sparse = directory / 'unflagged-sparse.bin'
filler = directory / 'unflagged-sparse-filler.tmp'
sparse.write_bytes((b'SPARSE-RUN-FIRST-' * 16384)[:192 * 1024])
filler.write_bytes((b'SPARSE-RUN-FILLER-' * 16384)[:192 * 1024])
with sparse.open('ab') as handle:
    handle.write((b'SPARSE-RUN-LAST-' * 16384)[:192 * 1024])
filler.unlink()
(directory / 'mapping-pair-tail.bin').write_bytes(
    (b'MAPPING-PAIR-TAIL-' * 16384)[:192 * 1024]
)
(directory / 'attribute-end-tail.bin').write_bytes(b'AT-END-TAIL-ORACLE\n')
sparse_unit = directory / 'sparse-unit.bin'
with sparse_unit.open('wb', buffering=0) as handle:
    os.ftruncate(handle.fileno(), 64 * 4096)
    if os.pwrite(handle.fileno(), b'H' * 4096, 0) != 4096:
        raise SystemExit('short sparse-unit head write')
    if os.pwrite(handle.fileno(), b'T' * 4096, 63 * 4096) != 4096:
        raise SystemExit('short sparse-unit tail write')
    os.fsync(handle.fileno())
PY
printf 'hard-link reciprocity oracle\n' >"$mount_root/the one/deep/link-source.bin"
ln "$mount_root/the one/deep/link-source.bin" \
    "$mount_root/the one/deep/link-second.bin"
printf 'resident FILE_NAME value collation oracle\n' \
    >"$mount_root/the one/deep/collation-parent-b/shared.bin"
ln "$mount_root/the one/deep/collation-parent-b/shared.bin" \
    "$mount_root/the one/deep/collation-parent-a/shared.bin"
printf 'POSIX collision member A\n' \
    >"$mount_root/the one/deep/collation-parent-a/PosixName.bin"
printf 'POSIX collision member B\n' \
    >"$mount_root/the one/deep/collation-parent-a/posixname.bin"
python3 - "$mount_root/the one/deep/duplicate-a.bin" \
    "$mount_root/the one/deep/duplicate-b.bin" <<'PY'
from pathlib import Path
import sys

payload = (b'DUPLICATE-CLUSTER-CONTENT-PROOF-' * 8192)[:256 * 1024]
for name in sys.argv[1:]:
    Path(name).write_bytes(payload)
PY
python3 - "$mount_root/the one/deep/compressed" <<'PY'
import os
from pathlib import Path
import struct
import sys

directory = Path(sys.argv[1])
current = struct.unpack('<I', os.getxattr(directory, 'system.ntfs_attrib'))[0]
os.setxattr(directory, 'system.ntfs_attrib', struct.pack('<I', current | 0x800))
(directory / 'metadata.bin').write_bytes(
    (b'ROOTHEALTH-COMPRESSED-METADATA-' * 32768)[:768 * 1024]
)
PY
dd if=/dev/zero of="$mount_root/the one/orphan-source/reconnect.bin" \
    bs=4096 count=32 status=none
printf 'original-parent orphan payload\n' | dd \
    of="$mount_root/the one/orphan-source/reconnect.bin" conv=notrunc status=none
dd if=/dev/zero of="$mount_root/the one/orphan-source/recovery.bin" \
    bs=4096 count=32 status=none
printf 'missing-parent recovery payload\n' | dd \
    of="$mount_root/the one/orphan-source/recovery.bin" conv=notrunc status=none
for entry_number in $(seq -w 1 128); do
    entry_path=$(printf '%s/the one/repair-index/entry-%s-abcdefghijklmnopqrstuvwxyz0123456789.data' \
        "$mount_root" "$entry_number")
    printf 'repair index fixture %s\n' "$entry_number" >"$entry_path"
done
finish_mount
printf 'named stream content\n' >"$work/named-stream.bin"
for stream_number in $(seq -w 1 24); do
    "$ntfscp_tool" -f -N "stream$stream_number" "$base_image" \
        "$work/named-stream.bin" '/the one/deep/attrlist.bin' >/dev/null
done
python3 - "$work/user-defined-stream.bin" <<'PY'
from pathlib import Path
import sys
Path(sys.argv[1]).write_bytes(
    (b'USER-DEFINED-NONRESIDENT-RUNLIST-' * 8192)[:192 * 1024]
)
PY
"$ntfscp_tool" -f -N userDefinedStream "$base_image" \
    "$work/user-defined-stream.bin" '/the one/deep/user-defined.bin' >/dev/null
printf 'resident layout stream value\n' >"$work/layout-resident-stream.bin"
"$ntfscp_tool" -f -N layoutResident "$base_image" \
    "$work/layout-resident-stream.bin" '/the one/deep/layout-candidate.bin' >/dev/null
provision_journal "$base_image" t1os
# Build the exact 0x40000 ATTRIBUTE_LIST before the final bitmap-pair pool,
# then reserve the next allocator extent until every later allocation is done.
# Releasing that reservation at the final cleanup leaves a deterministic free
# peer immediately after the list run for the isolated >0x40000 negative.
printf 'x' >"$work/large-attrlist-stream.bin"
"$ntfscp_tool" -f "$base_image" "$work/large-attrlist-stream.bin" \
    '/the one/deep/large-attrlist.bin' >/dev/null
python3 -B - >"$work/large-attrlist-names.txt" <<'PY'
for ordinal in range(488):
    prefix = f's{ordinal:04d}'
    print(prefix + 'x' * (255 - len(prefix)))
prefix = 'z0489'
print(prefix + 'y' * (208 - len(prefix)))
PY
while IFS= read -r stream_name; do
    "$ntfscp_tool" -f -N "$stream_name" "$base_image" \
        "$work/large-attrlist-stream.bin" \
        '/the one/deep/large-attrlist.bin' >/dev/null
done <"$work/large-attrlist-names.txt"
dd if=/dev/zero of="$work/large-attrlist-adjacent.bin" \
    bs=4096 count=1 status=none
"$ntfscp_tool" -f "$base_image" "$work/large-attrlist-adjacent.bin" \
    '/the one/deep/large-attrlist-adjacent.reserve' >/dev/null
# Allocate many one-cluster files after every other fixture allocation is
# complete, select two whose actual LCNs share one bitmap byte, retain one as
# the known payload, and delete its peer.  This makes the same-byte live/free
# truth deterministic without trusting allocator placement.
mount_existing_rw "$base_image"
python3 - "$mount_root/the one/repair-payloads" <<'PY'
import os
from pathlib import Path
import sys

directory = Path(sys.argv[1])
for ordinal in range(64):
    path = directory / f'bitmap-pair-candidate-{ordinal:02d}.bin'
    block = bytes((0x41 + ordinal % 23,)) * 4096
    with path.open('wb', buffering=0) as handle:
        if handle.write(block) != len(block):
            raise SystemExit('short bitmap candidate write')
        os.fsync(handle.fileno())
directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
finish_mount
declare -A bitmap_candidate_by_byte=()
bitmap_selected=
bitmap_victim=
for ordinal in $(seq -w 0 63); do
    candidate_path="/the one/repair-payloads/bitmap-pair-candidate-$ordinal.bin"
    candidate_lcn=$(ntfscluster -F "$candidate_path" "$base_image" |
        awk '$1 == 0 && $3 == 1 {print $2}')
    case "$candidate_lcn" in
        ''|*[!0-9]*)
            echo "Bitmap candidate $ordinal lacks one exact cluster: $candidate_lcn" >&2
            exit 1
            ;;
    esac
    candidate_byte=$((candidate_lcn / 8))
    if [ -n "${bitmap_candidate_by_byte[$candidate_byte]:-}" ]; then
        bitmap_selected=${bitmap_candidate_by_byte[$candidate_byte]}
        bitmap_victim=$ordinal
        break
    fi
    bitmap_candidate_by_byte[$candidate_byte]=$ordinal
done
if [ -z "$bitmap_selected" ] || [ -z "$bitmap_victim" ]; then
    echo 'Could not construct a same-byte live/free cluster pair.' >&2
    exit 1
fi
mount_existing_rw "$base_image"
rm -- "$mount_root/the one/repair-payloads/bitmap.bin"
mv -- \
    "$mount_root/the one/repair-payloads/bitmap-pair-candidate-$bitmap_selected.bin" \
    "$mount_root/the one/repair-payloads/bitmap.bin"
for ordinal in $(seq -w 0 63); do
    [ "$ordinal" = "$bitmap_selected" ] || \
        rm -- "$mount_root/the one/repair-payloads/bitmap-pair-candidate-$ordinal.bin"
done
rm -- "$mount_root/the one/deep/large-attrlist-adjacent.reserve"
finish_mount
unset bitmap_candidate_by_byte
active_loop=$(losetup --find --show --read-only "$base_image")
rm -f -- "$work/t1os.roothealth-journal.json"
python3 "$journal_validator" validate "$active_loop" \
    --require-one-run --require-zero-entry-area \
    --report "$work/t1os.roothealth-journal.json"
losetup --detach "$active_loop"
active_loop=
assert_journal_locator_flags "$work/t1os.roothealth-journal.json" t1os-final

format_and_mount "$ordinary_image" 512M 'ORDINARY REPAIR'
mkdir -p "$mount_root/Documents"
printf 'Structurally valid ordinary NTFS.\n' >"$mount_root/Documents/readme.txt"
finish_mount
provision_journal "$ordinary_image" ordinary
python3 "$fixtures" mutate dirty-log "$ordinary_image" \
    --state "$work/ordinary-dirty.state.json" >/dev/null

# The native redo encoder targets the final UTF-16 code unit of this production
# T1OS label, preserving the required identity prefix through replay.  The
# volume also has the same namespace identity and pre-provisioned $RootHealth
# WAL as every production repair target.
format_and_mount "$native_redo_base_image" 512M 'T1OS 0.31'
mkdir -p \
    "$mount_root/the one/software/python/bin" \
    "$mount_root/the one/build/GODDESS" \
    "$mount_root/the one/build/drivers" \
    "$mount_root/the one/drivers/tools" \
    "$mount_root/the one/drivers/settings" \
    "$mount_root/the one/drivers/modules/test-kernel" \
    "$mount_root/the one/recovered files/roothealth"
printf '#!/bin/sh\nexit 0\n' >"$mount_root/the one/software/python/bin/python"
printf '#!/bin/sh\nexit 0\n' >"$mount_root/the one/drivers/tools/modprobe"
chmod 0755 \
    "$mount_root/the one/software/python/bin/python" \
    "$mount_root/the one/drivers/tools/modprobe"
printf 'print("native redo fixture")\n' \
    >"$mount_root/the one/build/GODDESS/GODDESS.py"
printf 'print("native redo driver fixture")\n' \
    >"$mount_root/the one/build/drivers/driverserver.py"
printf '{"format":1,"native_redo_fixture":true}\n' \
    >"$mount_root/the one/drivers/settings/policy.json"
printf '%064d  test-kernel/modules.dep\n' 0 \
    >"$mount_root/the one/drivers/modules/module-manifest.sha256"
printf 'kernel/native-redo.ko:\n' \
    >"$mount_root/the one/drivers/modules/test-kernel/modules.dep"
finish_mount
provision_journal "$native_redo_base_image" native-redo
cp --reflink=auto --sparse=always \
    "$native_redo_base_image" "$native_redo_clean_source_image"
python3 "$fixtures" mutate volume-dirty-only "$native_redo_base_image" \
    --state "$work/native-redo-dirty.state.json" >/dev/null
native_redo_base_before=$(sha256sum "$native_redo_base_image" | awk '{print $1}')
python3 "$native_redo_fixture" encode "$native_redo_base_image" \
    "$native_redo_image" --manifest "$native_redo_manifest" >/dev/null
[ "$native_redo_base_before" = "$(sha256sum "$native_redo_base_image" | awk '{print $1}')" ] || {
    echo 'Native redo encoder changed its source T1OS volume.' >&2
    exit 1
}
cp --reflink=auto --sparse=always \
    "$native_redo_clean_source_image" "$native_redo_clean_history_image"
python3 -B - "$native_redo_fixture" "$native_redo_image" \
        "$native_redo_clean_history_image" <<'PY'
import importlib.util
import os
import struct
import sys

fixture_path, source_path, output_path = sys.argv[1:]
spec = importlib.util.spec_from_file_location("native_redo_fixture", fixture_path)
if spec is None or spec.loader is None:
    raise SystemExit("could not load native redo fixture helpers")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)

with open(source_path, "rb", buffering=0) as source, open(
    output_path, "r+b", buffering=0
) as output:
    source_geometry = fixture.parse_geometry(source)
    output_geometry = fixture.parse_geometry(output)
    source_size, source_runs = fixture.find_logfile(source, source_geometry)
    output_size, output_runs = fixture.find_logfile(output, output_geometry)
    if source_size != output_size:
        raise SystemExit("clean-history $LogFile size changed")
    pages = bytearray(
        fixture.stream_read(
            source, source_runs, source_geometry["cluster_size"],
            0, 4 * fixture.LOG_PAGE_SIZE,
        )
    )
    for page_number in (0, 1):
        start = page_number * fixture.LOG_PAGE_SIZE
        logical = fixture.mst_unprotect(
            bytes(pages[start:start + fixture.LOG_PAGE_SIZE]),
            fixture.LOG_PAGE_SIZE,
        )
        restart_area = fixture.u16(logical, 24)
        flags_offset = restart_area + 14
        struct.pack_into("<H", logical, flags_offset,
                         fixture.u16(logical, flags_offset) | 2)
        pages[start:start + fixture.LOG_PAGE_SIZE] = fixture.mst_protect(
            logical, fixture.u16(logical, 4), 0xD100 + page_number
        )

    # A clean restart makes old record pages non-authoritative.  Poison one
    # old base-page magic so the pre-v0.5.1 historical walk would refuse it.
    start = 2 * fixture.LOG_PAGE_SIZE
    logical = fixture.mst_unprotect(
        bytes(pages[start:start + fixture.LOG_PAGE_SIZE]),
        fixture.LOG_PAGE_SIZE,
    )
    logical[0:4] = b"OLD!"
    pages[start:start + fixture.LOG_PAGE_SIZE] = fixture.mst_protect(
        logical, fixture.u16(logical, 4), 0xD102
    )
    fixture.stream_write(
        output, output_runs, output_geometry["cluster_size"], 0, pages
    )
    output.flush()
    os.fsync(output.fileno())
PY
python3 "$native_log_corpus" "$native_redo_fixture" "$native_redo_image" \
    "$native_redo_manifest" "$work/native-log-corpus" >/dev/null
cp --reflink=auto --sparse=always \
    "$native_redo_image" "$native_redo_mirror_interrupt_image"
cp --reflink=auto --sparse=always \
    "$native_redo_clean_source_image" "$native_redo_clean_disagree_image"
python3 "$fixtures" mutate native-redo-primary-applied \
    "$native_redo_mirror_interrupt_image" --manifest "$native_redo_manifest" \
    --state "$work/native-redo-mirror-interrupt.state.json" >/dev/null
python3 "$fixtures" mutate native-redo-primary-applied \
    "$native_redo_clean_disagree_image" --manifest "$native_redo_manifest" \
    --state "$work/native-redo-clean-disagree.state.json" >/dev/null

resolve_inode() {
    image=$1
    path=$2
    inode=$(ntfsinfo -F "$path" "$image" |
        awk 'NR == 1 && $1 == "Dumping" && $2 == "Inode" { print $3 }')
    case "$inode" in
        ''|*[!0-9]*) echo "Could not resolve fixture inode for $path" >&2; exit 1 ;;
    esac
    printf '%s\n' "$inode"
}

resolve_index_inode() {
    image=$1
    path=$2
    attribute=$3
    inode=$(ntfsinfo -F "$path" "$image" |
        awk -v wanted="$attribute" \
            '$1 == "Dumping" && $2 == "attribute" && $3 == wanted { print $8 }')
    case "$inode" in
        ''|*[!0-9]*) echo "Could not resolve $attribute record for $path" >&2; exit 1 ;;
    esac
    printf '%s\n' "$inode"
}

bitmap_inode=$(resolve_inode "$base_image" '/the one/repair-payloads/bitmap.bin')
live_inode=$(resolve_inode "$base_image" '/the one/repair-payloads/live-record.txt')
journal_overlap_inode=$(resolve_inode \
    "$base_image" '/the one/repair-payloads/journal-overlap.bin')
index_inode=$(resolve_index_inode "$base_image" '/the one/repair-index' '$INDEX_ROOT')
index_allocation_inode=$(resolve_index_inode \
    "$base_image" '/the one/repair-index' '$INDEX_ALLOCATION')
reconnect_inode=$(resolve_inode "$base_image" '/the one/orphan-source/reconnect.bin')
recovery_inode=$(resolve_inode "$base_image" '/the one/orphan-source/recovery.bin')
root_index_inode=$(resolve_index_inode "$base_image" '/' '$INDEX_ROOT')
root_index_allocation_inode=$(resolve_index_inode \
    "$base_image" '/' '$INDEX_ALLOCATION')
the_one_inode=$(resolve_inode "$base_image" '/the one')
python_parent_index_inode=$(resolve_index_inode \
    "$base_image" '/the one/software/python/bin' '$INDEX_ROOT')
python_parent_inode=$(resolve_inode \
    "$base_image" '/the one/software/python/bin')
python_inode=$(resolve_inode "$base_image" '/the one/software/python/bin/python')
python_donor_inode=$(resolve_inode \
    "$base_image" '/the one/software/python/bin/python4.13')
attribute_list_inode=$(resolve_inode "$base_image" '/the one/deep/attrlist.bin')
large_attribute_list_inode=$(resolve_inode \
    "$base_image" '/the one/deep/large-attrlist.bin')
runlist_size_inode=$(resolve_inode "$base_image" '/the one/deep/runlist-size.bin')
deep_parent_inode=$(resolve_inode "$base_image" '/the one/deep')
link_inode=$(resolve_inode "$base_image" '/the one/deep/link-source.bin')
hardlink_inode=$(resolve_inode \
    "$base_image" '/the one/deep/collation-parent-a/shared.bin')
hardlink_parent_a_inode=$(resolve_inode \
    "$base_image" '/the one/deep/collation-parent-a')
hardlink_parent_b_inode=$(resolve_inode \
    "$base_image" '/the one/deep/collation-parent-b')
posix_collision_first_inode=$(resolve_inode \
    "$base_image" '/the one/deep/collation-parent-a/PosixName.bin')
posix_collision_second_inode=$(resolve_inode \
    "$base_image" '/the one/deep/collation-parent-a/posixname.bin')
sparse_unit_inode=$(resolve_inode "$base_image" '/the one/deep/sparse-unit.bin')
duplicate_first_inode=$(resolve_inode "$base_image" '/the one/deep/duplicate-a.bin')
duplicate_second_inode=$(resolve_inode "$base_image" '/the one/deep/duplicate-b.bin')
compressed_inode=$(resolve_inode "$base_image" '/the one/deep/compressed/metadata.bin')
user_defined_inode=$(resolve_inode "$base_image" '/the one/deep/user-defined.bin')
unflagged_sparse_inode=$(resolve_inode \
    "$base_image" '/the one/deep/unflagged-sparse.bin')
mapping_pair_tail_inode=$(resolve_inode \
    "$base_image" '/the one/deep/mapping-pair-tail.bin')
attribute_end_tail_inode=$(resolve_inode \
    "$base_image" '/the one/deep/attribute-end-tail.bin')
layout_candidate_inode=$(resolve_inode \
    "$base_image" '/the one/deep/layout-candidate.bin')
operations_parent_inode=$(resolve_inode \
    "$base_image" '/the one/settings/operations')
operations_inode=$(resolve_inode \
    "$base_image" '/the one/settings/operations/operations.txt')
operations_completed_inode=$(resolve_inode \
    "$base_image" '/the one/settings/operations/completed.json')
goddess_parent_inode=$(resolve_inode "$base_image" '/the one/build/GODDESS')
for inode in "$hardlink_inode" "$hardlink_parent_a_inode" \
        "$hardlink_parent_b_inode" "$posix_collision_first_inode" \
        "$posix_collision_second_inode" "$python_parent_inode" \
        "$python_donor_inode" "$sparse_unit_inode" \
        "$layout_candidate_inode" "$large_attribute_list_inode" \
        "$operations_parent_inode" "$operations_inode" \
        "$operations_completed_inode" "$goddess_parent_inode"; do
    case "$inode" in
        ''|*[!0-9]*) echo "Invalid census fixture inode: $inode" >&2; exit 1 ;;
    esac
done
python3 -B - "$work/hardlink-collation.state.json" "$hardlink_inode" \
    "$hardlink_parent_a_inode" "$hardlink_parent_b_inode" <<'PY'
import json
import sys

state = {
    'kind': 'hardlink-collation',
    'inode': int(sys.argv[2]),
    'parent_inodes': [int(sys.argv[3]), int(sys.argv[4])],
    'target_name': 'shared.bin',
}
with open(sys.argv[1], 'w', encoding='utf-8') as handle:
    json.dump(state, handle, sort_keys=True)
    handle.write('\n')
PY
python3 -B - "$work/posix-collision-clean.state.json" \
    "$hardlink_parent_a_inode" "$posix_collision_first_inode" \
    "$posix_collision_second_inode" <<'PY'
import json
import sys

state = {
    'kind': 'posix-collision-clean',
    'parent_inode': int(sys.argv[2]),
    'inodes': [int(sys.argv[3]), int(sys.argv[4])],
    'final_names': ['PosixName.bin', 'posixname.bin'],
    'required_anchor': False,
}
with open(sys.argv[1], 'w', encoding='utf-8') as handle:
    json.dump(state, handle, sort_keys=True)
    handle.write('\n')
PY
python3 -B - "$work/attribute-list-hardlink.state.json" "$attribute_list_inode" \
    "$hardlink_parent_a_inode" "$hardlink_parent_b_inode" <<'PY'
import json
import sys

state = {
    'kind': 'attribute-list-hardlink',
    'inode': int(sys.argv[2]),
    'parent_inodes': [int(sys.argv[3]), int(sys.argv[4])],
    'target_name': 'attrlist-shared.bin',
}
with open(sys.argv[1], 'w', encoding='utf-8') as handle:
    json.dump(state, handle, sort_keys=True)
    handle.write('\n')
PY
python3 -B - "$work/large-attribute-list.state.json" \
    "$large_attribute_list_inode" <<'PY'
import json
import sys

state = {'kind': 'large-attribute-list', 'inode': int(sys.argv[2])}
with open(sys.argv[1], 'w', encoding='utf-8') as handle:
    json.dump(state, handle, sort_keys=True)
    handle.write('\n')
PY
python3 -B - "$work/sparse-stream.state.json" "$sparse_unit_inode" <<'PY'
import json
import sys

state = {'kind': 'sparse-stream', 'inode': int(sys.argv[2])}
with open(sys.argv[1], 'w', encoding='utf-8') as handle:
    json.dump(state, handle, sort_keys=True)
    handle.write('\n')
PY
python3 "$fixtures" mutate fragment-data "$base_image" \
    --inode "$unflagged_sparse_inode" \
    --state "$work/fragment-data-preparation.json" >/dev/null
python3 -B - "$work/fragment-data-preparation.json" <<'PY'
import json
import re
import sys

state = json.load(open(sys.argv[1], encoding='utf-8'))
runs = state.get('runs')
if (
    state.get('kind') != 'fragment-data'
    or not isinstance(runs, list)
    or len(runs) < 2
    or any(not isinstance(run, list) or len(run) != 3 or run[1] is None for run in runs)
    or not re.fullmatch(r'[0-9a-f]{64}', str(state.get('content_sha256', '')))
):
    raise SystemExit(f'fragmented ordinary DATA preparation failed: {state!r}')
PY

namespace_manifest() {
    image=$1
    output=$2
    active_loop=$(losetup --find --show --read-only "$image")
    mount.ntfs-3g -o ro,permissions "$active_loop" "$mount_root"
    mounted=1
    python3 - "$mount_root/the one" >"$output" <<'PY'
from pathlib import Path
import hashlib
import json
import os
import sys

root = Path(sys.argv[1])
entries = {}
for directory, names, files in os.walk(root):
    names.sort()
    files.sort()
    directory_path = Path(directory)
    if directory_path != root:
        relative = directory_path.relative_to(root).as_posix()
        entries[relative] = {"type": "directory"}
    for name in files:
        path = directory_path / name
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries[relative] = {"type": "symlink", "target": os.readlink(path)}
        else:
            digest = hashlib.sha256()
            with path.open('rb') as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(chunk)
            entries[relative] = {
                "type": "file",
                "size": path.stat().st_size,
                "sha256": digest.hexdigest(),
            }
print(json.dumps(entries, sort_keys=True, separators=(',', ':')))
PY
    if find "$mount_root" -xdev \( -iname lost+found -o -name 'FSCK_*' \) \
            -print -quit | grep -q .; then
        echo 'Forbidden Linux recovery namespace appeared on the T1OS volume.' >&2
        exit 1
    fi
    umount "$mount_root"
    mounted=0
    losetup --detach "$active_loop"
    active_loop=
}

base_manifest="$work/base-manifest.json"
namespace_manifest "$base_image" "$base_manifest"
operations_stale_manifest="$work/operations-registry-stale-manifest.json"
python3 -B - "$base_manifest" "$operations_stale_manifest" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding='utf-8'))
removed = manifest.pop('settings/operations/operations.txt', None)
if not isinstance(removed, dict) or removed.get('type') != 'file':
    raise SystemExit('base fixture lacks the operations registry manifest entry')
with open(sys.argv[2], 'w', encoding='utf-8') as output:
    json.dump(manifest, output, sort_keys=True, separators=(',', ':'))
    output.write('\n')
PY
python3 "$fixtures" inspect "$base_image" \
    --state "$work/hardlink-collation.state.json" \
    >"$work/hardlink-collation.inspect.json"
python3 "$fixtures" inspect "$base_image" \
    --state "$work/sparse-stream.state.json" \
    >"$work/sparse-stream.inspect.json"
python3 -B - "$work/hardlink-collation.state.json" \
    "$work/hardlink-collation.inspect.json" \
    "$work/sparse-stream.inspect.json" <<'PY'
import hashlib
import json
import sys

state = json.load(open(sys.argv[1], encoding='utf-8'))
hardlink = json.load(open(sys.argv[2], encoding='utf-8')).get(
    'hardlink_collation'
)
if (
    not isinstance(hardlink, dict)
    or state['parent_inodes'] != sorted(state['parent_inodes'])
    or hardlink.get('link_count') != 2
    or hardlink.get('file_name_count') != 2
    or hardlink.get('resident_parent_order') != state['parent_inodes']
    or hardlink.get('attribute_instances') == sorted(hardlink.get('attribute_instances', []))
    or hardlink.get('values_distinct') is not True
    or hardlink.get('values_collated') is not True
    or hardlink.get('all_reciprocal') is not True
    or len(hardlink.get('index_copies', [])) != 2
    or any(
        item.get('reciprocal') is not True
        or item.get('semantic_key_match') is not True
        for item in hardlink.get('index_copies', [])
    )
):
    raise SystemExit(f'clean hardlink resident-value collation failed: {hardlink!r}')

sparse = json.load(open(sys.argv[3], encoding='utf-8')).get('sparse_stream')
runs = sparse.get('runs', []) if isinstance(sparse, dict) else []
expected_content = b'H' * 4096 + bytes(62 * 4096) + b'T' * 4096
if (
    not isinstance(sparse, dict)
    or sparse.get('attribute_flags') != 0x8000
    or sparse.get('record_attrs_offset') != 56
    or sparse.get('record_bytes_in_use') != 368
    or sparse.get('record_next_attr_instance') != 3
    or sparse.get('attribute_record_offset') != 272
    or sparse.get('attribute_record_length') != 88
    or sparse.get('compression_unit') != 4
    or sparse.get('data_size') != 64 * 4096
    or sparse.get('initialized_size') != 64 * 4096
    or sparse.get('allocated_size') != 64 * 4096
    or sparse.get('compressed_size') != 2 * 4096
    or sparse.get('physical_bytes') != 2 * 4096
    or sparse.get('logical_clusters') != 64
    or sparse.get('mapped_clusters') != 2
    or sparse.get('sparse_clusters') != 62
    or len(runs) != 3
    or runs[0][0] != 0 or not isinstance(runs[0][1], int) or runs[0][2] != 1
    or runs[1] != [1, None, 62]
    or runs[2][0] != 63 or not isinstance(runs[2][1], int) or runs[2][2] != 1
    or sparse.get('runlist_complete') is not True
    or sparse.get('tail_run_mapped') is not True
    or sparse.get('mapped_lcns_distinct') is not True
    or sparse.get('mapped_cluster_bits') != [True, True]
    or sparse.get('mft_bitmap_bit') is not True
    or sparse.get('hole_all_zero') is not True
    or sparse.get('mapping_pairs_offset') != 72
    or sparse.get('mapping_pairs_record_offset') != 344
    or sparse.get('terminator_attribute_offset') != 82
    or sparse.get('terminator_record_offset') != 354
    or sparse.get('mapping_tail_record_offset') != 355
    or sparse.get('mapping_tail_length') != 5
    or sparse.get('mapping_tail_hex') != 'ff00000000'
    or sparse.get('mapping_tail_all_zero') is not False
    or sparse.get('mapping_tail_pinned_producer_slack') is not True
    or sparse.get('mapping_tail_opaque_slack') is not True
    or sparse.get('mapping_tail_accepted_slack') is not True
    or sparse.get('head_sha256') != hashlib.sha256(b'H' * 4096).hexdigest()
    or sparse.get('tail_sha256') != hashlib.sha256(b'T' * 4096).hexdigest()
    or sparse.get('logical_sha256') != hashlib.sha256(expected_content).hexdigest()
):
    raise SystemExit(f'clean genuine sparse-stream census failed: {sparse!r}')
PY
native_redo_base_manifest="$work/native-redo-base-manifest.json"
namespace_manifest "$native_redo_base_image" "$native_redo_base_manifest"
recovery_sha=$(sha256sum <(ntfscat -i "$recovery_inode" "$base_image") | awk '{print $1}')
expected_serial=$(python3 "$fixtures" inspect "$base_image" |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["primary_serial"])')
case "$expected_serial" in
    [0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F]) ;;
    *) echo "Could not derive the fixture NTFS serial: $expected_serial" >&2; exit 1 ;;
esac
read -r journal_serial expected_journal_uuid expected_journal_record expected_journal_sequence <<EOF
$(python3 - "$work/t1os.roothealth-journal.json" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1], encoding='utf-8'))
print(
    report['device']['serial'],
    report['journal']['header']['journal_uuid'],
    report['journal']['mft_record'],
    report['journal']['mft_sequence'],
)
PY
)
EOF
[ "$journal_serial" = "$expected_serial" ] || {
    echo "Provisioned journal serial $journal_serial differs from $expected_serial." >&2
    exit 1
}
case "$expected_journal_uuid" in
    ????????-????-????-????-????????????) ;;
    *) echo "Could not derive fixture journal UUID: $expected_journal_uuid" >&2; exit 1 ;;
esac
case "$expected_journal_record" in
    ''|*[!0-9]*) echo "Could not derive fixture journal record: $expected_journal_record" >&2; exit 1 ;;
esac
case "$expected_journal_sequence" in
    ''|*[!0-9]*) echo "Could not derive fixture journal sequence: $expected_journal_sequence" >&2; exit 1 ;;
esac
expected_report_serial="0x${expected_serial,,}"
read -r ordinary_journal_serial ordinary_journal_uuid <<EOF
$(python3 - "$work/ordinary.roothealth-journal.json" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1], encoding='utf-8'))
print(report['device']['serial'], report['journal']['header']['journal_uuid'])
PY
)
EOF
ordinary_report_serial="0x${ordinary_journal_serial,,}"
report_binding_args=(
    --expected-journal-uuid "$expected_journal_uuid"
    --expected-volume-serial "$expected_report_serial"
)
ordinary_report_binding_args=(
    --expected-journal-uuid "$ordinary_journal_uuid"
    --expected-volume-serial "$ordinary_report_serial"
)
read -r native_redo_serial native_redo_uuid native_redo_record native_redo_sequence <<EOF
$(python3 - "$work/native-redo.roothealth-journal.json" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1], encoding='utf-8'))
print(
    report['device']['serial'],
    report['journal']['header']['journal_uuid'],
    report['journal']['mft_record'],
    report['journal']['mft_sequence'],
)
PY
)
EOF
native_redo_report_serial="0x${native_redo_serial,,}"
native_redo_identity_args=(
    --expected-serial "$native_redo_serial"
    --expected-journal-uuid "$native_redo_uuid"
    --expected-journal-record "$native_redo_record:$native_redo_sequence"
)
native_redo_report_binding_args=(
    --expected-journal-uuid "$native_redo_uuid"
    --expected-volume-serial "$native_redo_report_serial"
)

clean_restart_history_before=$(
    sha256sum "$native_redo_clean_history_image" | awk '{print $1}'
)
active_loop=$(losetup --find --show "$native_redo_clean_history_image")
clean_restart_history_log="$work/boot-clean-restart-history.log"
clean_restart_history_started=$(date +%s%N)
set +e
timeout 8s "$repair_checker" --boot-repair --quiet --require-t1os-root \
    "${native_redo_identity_args[@]}" "$active_loop" \
    >"$clean_restart_history_log" 2>&1
clean_restart_history_status=$?
set -e
clean_restart_history_finished=$(date +%s%N)
losetup --detach "$active_loop"
active_loop=
clean_restart_history_after=$(
    sha256sum "$native_redo_clean_history_image" | awk '{print $1}'
)
[ "$clean_restart_history_status" -eq 0 ] || {
    echo "Clean restart with historical noise returned $clean_restart_history_status." >&2
    sed -n '1,160p' "$clean_restart_history_log" >&2
    exit 1
}
[ "$clean_restart_history_before" = "$clean_restart_history_after" ] || {
    echo 'Clean restart fast path wrote to its target.' >&2
    exit 1
}
[ ! -s "$clean_restart_history_log" ] || {
    echo 'Quiet clean restart fast path produced console output.' >&2
    sed -n '1,160p' "$clean_restart_history_log" >&2
    exit 1
}
clean_restart_history_ms=$((
    (clean_restart_history_finished - clean_restart_history_started) / 1000000
))
[ "$clean_restart_history_ms" -le 2000 ] || {
    echo "Clean restart fast path took ${clean_restart_history_ms}ms." >&2
    exit 1
}
printf 'PASS boot-clean-restart-history exit=0 elapsed_ms=%s writes=0\n' \
    "$clean_restart_history_ms"

clone_fixture() {
    source=$1
    destination=$2
    cp --reflink=auto --sparse=always "$source" "$destination"
}

clone_fixture "$native_redo_image" "$native_redo_powercut_source_image"

dirty_image="$work/dirty-log.ntfs"
dirty_only_image="$work/dirty-only-wiped-log.ntfs"
boot_primary_image="$work/boot-primary.ntfs"
boot_backup_image="$work/boot-backup.ntfs"
mft_primary_image="$work/mft-primary.ntfs"
mft_mirror_image="$work/mft-mirror.ntfs"
boot_primary_powercut_source="$work/boot-primary-powercut-source.ntfs"
boot_backup_powercut_source="$work/boot-backup-powercut-source.ntfs"
mft_primary_powercut_source="$work/mft-primary-powercut-source.ntfs"
mft_mirror_powercut_source="$work/mft-mirror-powercut-source.ntfs"
bitmap_image="$work/bitmaps.ntfs"
journal_mft_false_free_image="$work/journal-mft-false-free.ntfs"
journal_cluster_false_free_image="$work/journal-cluster-false-free.ntfs"
journal_duplicate_owner_image="$work/journal-duplicate-owner.ntfs"
journal_mft_duplicate_image="$work/journal-mft-false-free-duplicate.ntfs"
journal_cluster_duplicate_image="$work/journal-cluster-false-free-duplicate.ntfs"
journal_duplicate_torn_image="$work/journal-duplicate-owner-one-torn.ntfs"
journal_duplicate_preparing_image="$work/journal-duplicate-owner-preparing.ntfs"
index_image="$work/index.ntfs"
index_bitmap_set_image="$work/index-bitmap-set.ntfs"
operations_stale_image="$work/operations-registry-stale.ntfs"
operations_stale_bitmaps_image="$work/operations-registry-stale-bitmaps.ntfs"
operations_stale_bitmaps_powercut_source="$work/operations-registry-stale-bitmaps-powercut-source.ntfs"
operations_stale_wrong_path_image="$work/operations-registry-wrong-path.ntfs"
operations_stale_ambiguous_image="$work/operations-registry-ambiguous.ntfs"
orphan_parent_image="$work/orphan-parent.ntfs"
orphan_recovery_image="$work/orphan-recovery.ntfs"
compound_image="$work/compound.ntfs"
clean_image="$work/clean.ntfs"
path_symlink_image="$work/path-symlink-clean.ntfs"
path_race_source_image="$work/path-race-source.ntfs"
path_race_victim_image="$work/path-race-victim.ntfs"
wal_invalid_image="$work/wal-invalid.ntfs"
wal_one_torn_image="$work/wal-one-torn.ntfs"
wal_ambiguous_image="$work/wal-ambiguous.ntfs"
io_image="$work/io-truncated.ntfs"
identity_parent_image="$work/identity-parent-index.ntfs"
identity_root_image="$work/identity-root-index.ntfs"
identity_missing_image="$work/identity-missing.ntfs"
attribute_list_image="$work/attribute-list.ntfs"
attribute_list_equal_triple_order_image="$work/attribute-list-equal-triple-order.ntfs"
large_attribute_list_boundary_image="$work/large-attribute-list-boundary.ntfs"
large_attribute_list_boundary_overrun_image="$work/large-attribute-list-boundary-overrun.ntfs"
large_attribute_list_truncated_image="$work/large-attribute-list-truncated.ntfs"
large_attribute_list_over_limit_image="$work/large-attribute-list-over-limit.ntfs"
runlist_size_image="$work/runlist-size.ntfs"
reparse_index_image="$work/reparse-index.ntfs"
secure_derived_image="$work/secure-derived.ntfs"
secure_sii_stale_image="$work/secure-sii-stale.ntfs"
upcase_attrdef_image="$work/upcase-attrdef.ntfs"
upcase_nonascii_image="$work/upcase-nonascii.ntfs"
user_defined_runlist_image="$work/user-defined-runlist.ntfs"
unflagged_sparse_image="$work/unflagged-sparse-run.ntfs"
mapping_pair_tail_image="$work/mapping-pair-tail.ntfs"
attribute_end_tail_image="$work/attribute-end-tail.ntfs"
link_reciprocity_image="$work/link-reciprocity.ntfs"
hardlink_value_order_image="$work/hardlink-value-order.ntfs"
posix_collision_clean_image="$work/posix-collision-clean.ntfs"
sparse_unit_header_image="$work/sparse-unit-header.ntfs"
duplicate_cluster_image="$work/duplicate-cluster.ntfs"
compressed_metadata_image="$work/compressed-metadata.ntfs"
compressed_payload_image="$work/compressed-payload.ntfs"
layout_candidate_cases=(
    layout-attrs-offset-candidate
    layout-attrs-offset-ambiguous
    layout-bytes-in-use-candidate
    layout-bytes-in-use-ambiguous
    layout-bytes-in-use-dual-chain
    layout-next-instance-candidate
    layout-next-instance-wrap-candidate
    layout-resident-value-candidate
    layout-resident-name-candidate
    layout-resident-length-candidate
    layout-resident-ambiguous
)
file_name_cached_cases=(
    file-name-cached-timestamps
    file-name-cached-allocated-size
    file-name-cached-data-size
    file-name-cached-file-attributes
    file-name-cached-ea-reparse
)
file_name_stable_cases=(
    file-name-stable-parent
    file-name-stable-sequence
    file-name-stable-flags
)
posix_collision_negative_cases=(
    posix-collision-exact-duplicate
    posix-collision-duplicate-reference
    posix-collision-required-anchor
)

for image in "$dirty_image" "$dirty_only_image" "$boot_primary_image" "$boot_backup_image" \
        "$mft_primary_image" "$mft_mirror_image" "$bitmap_image" \
        "$journal_mft_false_free_image" "$journal_cluster_false_free_image" \
        "$journal_duplicate_owner_image" "$journal_mft_duplicate_image" \
        "$journal_cluster_duplicate_image" "$journal_duplicate_torn_image" \
        "$journal_duplicate_preparing_image" \
		"$index_image" "$index_bitmap_set_image" \
		"$operations_stale_image" "$operations_stale_bitmaps_image" \
		"$operations_stale_wrong_path_image" \
        "$operations_stale_ambiguous_image" \
        "$orphan_parent_image" "$orphan_recovery_image" \
        "$compound_image" "$clean_image" "$path_symlink_image" \
        "$path_race_source_image" "$wal_invalid_image" \
        "$wal_one_torn_image" "$wal_ambiguous_image" "$io_image" \
        "$identity_parent_image" "$identity_root_image" \
        "$identity_missing_image" "$attribute_list_image" \
        "$attribute_list_equal_triple_order_image" \
        "$large_attribute_list_boundary_image" \
        "$large_attribute_list_boundary_overrun_image" \
        "$large_attribute_list_truncated_image" \
        "$large_attribute_list_over_limit_image" \
        "$runlist_size_image" "$reparse_index_image" \
        "$secure_derived_image" "$secure_sii_stale_image" \
        "$upcase_attrdef_image" "$upcase_nonascii_image" \
        "$user_defined_runlist_image" "$unflagged_sparse_image" \
        "$mapping_pair_tail_image" "$attribute_end_tail_image" \
        "$link_reciprocity_image" "$hardlink_value_order_image" \
        "$posix_collision_clean_image" \
        "$sparse_unit_header_image" "$duplicate_cluster_image" \
        "$compressed_metadata_image" "$compressed_payload_image"; do
    clone_fixture "$base_image" "$image"
done
for name in "${file_name_cached_cases[@]}" "${file_name_stable_cases[@]}" \
        "${posix_collision_negative_cases[@]}"; do
    clone_fixture "$base_image" "$work/$name.ntfs"
done
clone_fixture "$base_image" "$work/posix-collision-mixed-namespace.ntfs"
for layout_case in "${layout_candidate_cases[@]}"; do
    clone_fixture "$base_image" "$work/$layout_case.ntfs"
done
clone_fixture "$ordinary_image" "$path_race_victim_image"

python3 "$wal_fixtures" mutate both-torn "$wal_invalid_image" \
    "$work/t1os.roothealth-journal.json" >/dev/null
python3 "$wal_fixtures" mutate one-torn "$wal_one_torn_image" \
    "$work/t1os.roothealth-journal.json" >/dev/null
python3 "$wal_fixtures" mutate equal-generation-divergent "$wal_ambiguous_image" \
    "$work/t1os.roothealth-journal.json" >/dev/null
truncate -s 32M "$io_image"
python3 "$fixtures" mutate index-reference "$identity_parent_image" \
    --index-inode "$python_parent_index_inode" --target-name python \
    --target-inode "$python_inode" \
    --state "$work/identity-parent-index.state.json" >/dev/null
python3 "$fixtures" mutate index-reference "$identity_root_image" \
    --index-inode "$root_index_inode" --target-name 'the one' \
    --target-inode "$the_one_inode" \
    --index-allocation-inode "$root_index_allocation_inode" \
    --state "$work/identity-root-index.state.json" >/dev/null
mount_existing_rw "$identity_missing_image"
rm -- "$mount_root/the one/software/python/bin/python"
finish_mount

python3 "$fixtures" mutate dirty-log "$dirty_image" \
    --state "$work/dirty-log.state.json" >/dev/null
python3 "$fixtures" mutate volume-dirty-wiped-log "$dirty_only_image" \
    --state "$work/dirty-only.state.json" >/dev/null
python3 "$fixtures" mutate boot-primary "$boot_primary_image" \
    --state "$work/boot-primary.state.json" >/dev/null
python3 "$fixtures" mutate boot-backup "$boot_backup_image" \
    --state "$work/boot-backup.state.json" >/dev/null
python3 "$fixtures" mutate mft-primary "$mft_primary_image" \
    --state "$work/mft-primary.state.json" >/dev/null
python3 "$fixtures" mutate mft-mirror "$mft_mirror_image" \
    --state "$work/mft-mirror.state.json" >/dev/null
clone_fixture "$boot_primary_image" "$boot_primary_powercut_source"
clone_fixture "$boot_backup_image" "$boot_backup_powercut_source"
clone_fixture "$mft_primary_image" "$mft_primary_powercut_source"
clone_fixture "$mft_mirror_image" "$mft_mirror_powercut_source"
python3 "$fixtures" mutate bitmaps "$bitmap_image" \
    --allocated-inode "$bitmap_inode" --live-inode "$live_inode" \
    --state "$work/bitmaps.state.json" >/dev/null
python3 "$fixtures" mutate journal-mft-false-free \
    "$journal_mft_false_free_image" \
    --layout "$work/t1os.roothealth-journal.json" \
    --state "$work/journal-mft-false-free.state.json" >/dev/null
python3 "$fixtures" mutate journal-cluster-false-free \
    "$journal_cluster_false_free_image" \
	--layout "$work/t1os.roothealth-journal.json" \
	--state "$work/journal-cluster-false-free.state.json" >/dev/null
python3 "$fixtures" mutate bitmaps "$operations_stale_bitmaps_image" \
	--allocated-inode "$bitmap_inode" --live-inode "$live_inode" \
	--state "$work/operations-registry-stale-bitmaps.state.json" >/dev/null
python3 "$fixtures" mutate journal-duplicate-owner \
    "$journal_duplicate_owner_image" \
    --layout "$work/t1os.roothealth-journal.json" \
    --overlap-inode "$journal_overlap_inode" \
    --state "$work/journal-duplicate-owner.state.json" >/dev/null
python3 "$fixtures" mutate journal-mft-false-free-duplicate \
    "$journal_mft_duplicate_image" \
    --layout "$work/t1os.roothealth-journal.json" \
    --overlap-inode "$journal_overlap_inode" \
    --state "$work/journal-mft-false-free-duplicate.state.json" >/dev/null
python3 "$fixtures" mutate journal-cluster-false-free-duplicate \
    "$journal_cluster_duplicate_image" \
    --layout "$work/t1os.roothealth-journal.json" \
    --overlap-inode "$journal_overlap_inode" \
    --state "$work/journal-cluster-false-free-duplicate.state.json" >/dev/null
python3 "$fixtures" mutate journal-duplicate-owner \
    "$journal_duplicate_torn_image" \
    --layout "$work/t1os.roothealth-journal.json" \
    --overlap-inode "$journal_overlap_inode" \
    --state "$work/journal-duplicate-owner-one-torn.state.json" >/dev/null
python3 "$wal_fixtures" mutate one-torn "$journal_duplicate_torn_image" \
    "$work/t1os.roothealth-journal.json" >/dev/null
python3 "$fixtures" mutate journal-duplicate-owner \
    "$journal_duplicate_preparing_image" \
    --layout "$work/t1os.roothealth-journal.json" \
    --overlap-inode "$journal_overlap_inode" \
    --state "$work/journal-duplicate-owner-preparing.state.json" >/dev/null
python3 "$wal_fixtures" mutate preparing-zero \
    "$journal_duplicate_preparing_image" \
    "$work/t1os.roothealth-journal.json" >/dev/null
python3 "$fixtures" mutate index-i30 "$index_image" \
    --index-inode "$index_inode" \
    --index-allocation-inode "$index_allocation_inode" \
    --state "$work/index.state.json" >/dev/null
python3 "$fixtures" mutate index-bitmap-set "$index_bitmap_set_image" \
    --index-inode "$index_allocation_inode" \
    --state "$work/index-bitmap-set.state.json" >/dev/null

make_stale_resident_index_entry() {
    image=$1
    parent_inode=$2
    snapshot=$3
    shift 3
    python3 "$fixtures" snapshot-record "$image" "$parent_inode" "$snapshot"
    mount_existing_rw "$image"
    for relative_path in "$@"; do
        rm -- "$mount_root/$relative_path"
    done
    finish_mount
    python3 "$fixtures" restore-record "$image" "$snapshot" >/dev/null
}

make_stale_resident_index_entry "$operations_stale_image" \
	"$operations_parent_inode" "$work/operations-registry-stale.snapshot.json" \
	'the one/settings/operations/operations.txt'
make_stale_resident_index_entry "$operations_stale_bitmaps_image" \
	"$operations_parent_inode" \
	"$work/operations-registry-stale-bitmaps.snapshot.json" \
	'the one/settings/operations/operations.txt'
clone_fixture "$operations_stale_bitmaps_image" \
	"$operations_stale_bitmaps_powercut_source"
make_stale_resident_index_entry "$operations_stale_wrong_path_image" \
	"$operations_parent_inode" "$work/operations-registry-wrong-path.snapshot.json" \
	'the one/settings/operations/completed.json'
make_stale_resident_index_entry "$operations_stale_ambiguous_image" \
    "$operations_parent_inode" "$work/operations-registry-ambiguous.snapshot.json" \
    'the one/settings/operations/operations.txt' \
    'the one/settings/operations/completed.json'
python3 "$fixtures" mutate attribute-list "$attribute_list_image" \
    --inode "$attribute_list_inode" --state "$work/attribute-list.state.json" >/dev/null
python3 "$fixtures" mutate attribute-list-equal-triple-order \
    "$attribute_list_equal_triple_order_image" --inode "$attribute_list_inode" \
    --parent-inode "$hardlink_parent_a_inode" \
    --second-parent-inode "$hardlink_parent_b_inode" \
    --target-name attrlist-shared.bin \
    --state "$work/attribute-list-equal-triple-order.state.json" >/dev/null
python3 "$fixtures" mutate large-attribute-list-boundary \
    "$large_attribute_list_boundary_image" \
    --inode "$large_attribute_list_inode" \
    --state "$work/large-attribute-list-boundary.state.json" >/dev/null
python3 "$fixtures" mutate large-attribute-list-boundary-overrun \
    "$large_attribute_list_boundary_overrun_image" \
    --inode "$large_attribute_list_inode" \
    --state "$work/large-attribute-list-boundary-overrun.state.json" >/dev/null
python3 "$fixtures" mutate large-attribute-list-truncated \
    "$large_attribute_list_truncated_image" \
    --inode "$large_attribute_list_inode" \
    --state "$work/large-attribute-list-truncated.state.json" >/dev/null
python3 "$fixtures" mutate large-attribute-list-over-limit \
    "$large_attribute_list_over_limit_image" \
    --inode "$large_attribute_list_inode" \
    --state "$work/large-attribute-list-over-limit.state.json" >/dev/null
python3 "$fixtures" mutate runlist-size "$runlist_size_image" \
    --inode "$runlist_size_inode" --state "$work/runlist-size.state.json" >/dev/null
python3 "$fixtures" mutate reparse-index "$reparse_index_image" \
    --state "$work/reparse-index.state.json" >/dev/null
python3 "$fixtures" mutate secure-derived "$secure_derived_image" \
    --state "$work/secure-derived.state.json" >/dev/null
python3 "$fixtures" mutate secure-sii-stale "$secure_sii_stale_image" \
    --state "$work/secure-sii-stale.state.json" >/dev/null
python3 "$fixtures" mutate upcase-attrdef "$upcase_attrdef_image" \
    --state "$work/upcase-attrdef.state.json" >/dev/null
python3 "$fixtures" mutate upcase-nonascii "$upcase_nonascii_image" \
    --state "$work/upcase-nonascii.state.json" >/dev/null
python3 "$fixtures" mutate user-defined-runlist "$user_defined_runlist_image" \
    --inode "$user_defined_inode" --stream-name userDefinedStream \
    --state "$work/user-defined-runlist.state.json" >/dev/null
python3 "$fixtures" mutate unflagged-sparse-run "$unflagged_sparse_image" \
    --inode "$unflagged_sparse_inode" \
    --state "$work/unflagged-sparse-run.state.json" >/dev/null
python3 "$fixtures" mutate mapping-pair-tail "$mapping_pair_tail_image" \
    --inode "$mapping_pair_tail_inode" \
    --state "$work/mapping-pair-tail.state.json" >/dev/null
python3 "$fixtures" mutate attribute-end-tail "$attribute_end_tail_image" \
    --inode "$attribute_end_tail_inode" \
    --state "$work/attribute-end-tail.state.json" >/dev/null
python3 "$fixtures" mutate link-reciprocity "$link_reciprocity_image" \
    --inode "$link_inode" --parent-inode "$deep_parent_inode" \
    --target-name link-second.bin \
    --state "$work/link-reciprocity.state.json" >/dev/null
python3 "$fixtures" mutate hardlink-value-order "$hardlink_value_order_image" \
    --inode "$hardlink_inode" --parent-inode "$hardlink_parent_a_inode" \
    --second-parent-inode "$hardlink_parent_b_inode" --target-name shared.bin \
    --state "$work/hardlink-value-order.state.json" >/dev/null
for name in "${file_name_cached_cases[@]}" "${file_name_stable_cases[@]}"; do
    python3 "$fixtures" mutate "$name" "$work/$name.ntfs" \
        --inode "$hardlink_inode" --parent-inode "$hardlink_parent_a_inode" \
        --second-parent-inode "$hardlink_parent_b_inode" \
        --target-name shared.bin --state "$work/$name.state.json" >/dev/null
done
for name in posix-collision-exact-duplicate posix-collision-mixed-namespace \
        posix-collision-duplicate-reference; do
    python3 "$fixtures" mutate "$name" "$work/$name.ntfs" \
        --parent-inode "$hardlink_parent_a_inode" \
        --inode "$posix_collision_first_inode" \
        --second-inode "$posix_collision_second_inode" \
        --target-name PosixName.bin --second-target-name posixname.bin \
        --state "$work/$name.state.json" >/dev/null
done
python3 "$fixtures" mutate posix-collision-required-anchor \
    "$work/posix-collision-required-anchor.ntfs" \
    --parent-inode "$python_parent_inode" --inode "$python_inode" \
    --second-inode "$python_donor_inode" --target-name python \
    --second-target-name python4.13 \
    --state "$work/posix-collision-required-anchor.state.json" >/dev/null
python3 "$fixtures" mutate sparse-unit-header "$sparse_unit_header_image" \
    --inode "$sparse_unit_inode" \
    --state "$work/sparse-unit-header.state.json" >/dev/null
python3 "$fixtures" mutate duplicate-cluster "$duplicate_cluster_image" \
    --first-inode "$duplicate_first_inode" --second-inode "$duplicate_second_inode" \
    --state "$work/duplicate-cluster.state.json" >/dev/null
python3 "$fixtures" mutate compressed-metadata "$compressed_metadata_image" \
    --inode "$compressed_inode" --state "$work/compressed-metadata.state.json" >/dev/null
python3 "$fixtures" mutate compressed-payload "$compressed_payload_image" \
    --inode "$compressed_inode" --state "$work/compressed-payload.state.json" >/dev/null
for layout_case in "${layout_candidate_cases[@]}"; do
    python3 "$fixtures" mutate "$layout_case" "$work/$layout_case.ntfs" \
        --inode "$layout_candidate_inode" \
        --state "$work/$layout_case.state.json" >/dev/null
done

make_orphan() {
    image=$1
    inode=$2
    relative_path=$3
    snapshot=$4
    state=$5
    bad_parent=$6
    python3 "$fixtures" snapshot-orphan "$image" "$inode" "$snapshot"
    mount_existing_rw "$image"
    rm -- "$mount_root/$relative_path"
    finish_mount
    restore_args=()
    [ "$bad_parent" = false ] || restore_args+=(--bad-parent)
    python3 "$fixtures" restore-orphan "$image" "$snapshot" \
        "${restore_args[@]}" --state "$state" >/dev/null
}

make_orphan "$orphan_parent_image" "$reconnect_inode" \
    'the one/orphan-source/reconnect.bin' "$work/orphan-parent.snapshot.json" \
    "$work/orphan-parent.state.json" false
make_orphan "$orphan_recovery_image" "$recovery_inode" \
    'the one/orphan-source/recovery.bin' "$work/orphan-recovery.snapshot.json" \
    "$work/orphan-recovery.state.json" true

python3 "$fixtures" snapshot-orphan "$compound_image" "$reconnect_inode" \
    "$work/compound-parent.snapshot.json"
python3 "$fixtures" snapshot-orphan "$compound_image" "$recovery_inode" \
    "$work/compound-recovery.snapshot.json"
mount_existing_rw "$compound_image"
rm -- \
    "$mount_root/the one/orphan-source/reconnect.bin" \
    "$mount_root/the one/orphan-source/recovery.bin"
finish_mount
python3 "$fixtures" restore-orphan "$compound_image" \
    "$work/compound-parent.snapshot.json" >/dev/null
python3 "$fixtures" restore-orphan "$compound_image" \
    "$work/compound-recovery.snapshot.json" --bad-parent >/dev/null
python3 "$fixtures" mutate volume-dirty-wiped-log "$compound_image" >/dev/null
python3 "$fixtures" mutate boot-backup "$compound_image" >/dev/null
python3 "$fixtures" mutate journal-mft-false-free "$compound_image" \
    --layout "$work/t1os.roothealth-journal.json" \
    --state "$work/compound-journal-mft.state.json" >/dev/null
python3 "$fixtures" mutate journal-cluster-false-free "$compound_image" \
    --layout "$work/t1os.roothealth-journal.json" \
    --state "$work/compound-journal-cluster.state.json" >/dev/null
python3 "$fixtures" mutate mft-mirror "$compound_image" >/dev/null
python3 "$fixtures" mutate bitmaps "$compound_image" \
    --allocated-inode "$bitmap_inode" --live-inode "$live_inode" >/dev/null
python3 "$fixtures" mutate index-i30 "$compound_image" \
    --index-inode "$index_inode" \
    --index-allocation-inode "$index_allocation_inode" >/dev/null

repair_scope_args=()
if [ -n "${ROOTHEALTH_REPAIR_SCOPE:-}" ]; then
    repair_scope_args=(--scope "$ROOTHEALTH_REPAIR_SCOPE")
fi
repair_identity_args=(
    --expected-serial "$expected_serial"
    --expected-journal-uuid "$expected_journal_uuid"
    --expected-journal-record "$expected_journal_record:$expected_journal_sequence"
)
trace_syscalls='execve,execveat,open,openat,openat2,close,close_range,dup,dup2,dup3,fcntl,lseek,read,readv,pread64,preadv,preadv2,write,writev,pwrite64,pwritev,pwritev2,ftruncate,fallocate,copy_file_range,splice,sendfile,sendfile64,mmap,mprotect,msync,ioctl,io_uring_setup,io_uring_enter,io_uring_register,fsync,fdatasync,sync,syncfs,sync_file_range'

run_check() {
    local image=$1
    local case_name=$2
    local expected=$3
    local report="$work/check-$case_name.json"
    local expected_status check_state status
    active_loop=$(losetup --find --show --read-only "$image")
    set +e
    timeout 180s "$check_checker" --check --quiet --require-t1os-root \
        "${repair_identity_args[@]}" --report "$report" "$active_loop" \
        >"$work/check-$case_name.log" 2>&1
    status=$?
    set -e
    losetup --detach "$active_loop"
    active_loop=
    case "$expected" in
        clean)
            expected_status=0
            check_state=EMPTY
            ;;
        unsafe)
            expected_status=2
            check_state=EMPTY
            ;;
        interrupted)
            expected_status=2
            check_state=RECOVERY_REQUIRED
            ;;
        wal-unsupported)
            expected_status=2
            check_state=RECOVERY_REQUIRED
            ;;
        wal-invalid)
            expected_status=2
            check_state=INVALID
            ;;
        wal-degraded)
            expected_status=2
            check_state=DEGRADED
            ;;
        io)
            expected_status=3
            check_state=IO_ERROR
            ;;
        unsafe-or-io)
            case "$status" in
                2)
                    expected_status=2
                    check_state=$(python3 -B - "$report" <<'PY'
import json
import sys
wal = json.load(open(sys.argv[1], encoding='utf-8')).get('wal', {})
if wal.get('checked') is False:
    print('UNCHECKED')
elif wal.get('valid') is None:
    print('PARTIAL')
elif wal.get('valid') is False:
    print('INVALID')
else:
    print('EMPTY' if wal.get('state') == 'EMPTY' else 'RECOVERY_REQUIRED')
PY
)
                    ;;
                3) expected_status=3; check_state=IO_ERROR ;;
                *) expected_status=-1; check_state=EMPTY ;;
            esac
            ;;
        clean-or-unsafe)
            case "$status" in
                0) expected_status=0 ;;
                2) expected_status=2 ;;
                *) expected_status=-1 ;;
            esac
            check_state=EMPTY
            ;;
        wrong-root)
            expected_status=4
            check_state=EMPTY
            ;;
        *) echo "Unknown check expectation $expected" >&2; exit 1 ;;
    esac
    [ "$status" -eq "$expected_status" ] || {
        echo "Read-only check $case_name returned $status for expectation $expected." >&2
        sed -n '1,180p' "$work/check-$case_name.log" >&2
        touch "$work/.preserve"
        if [ -f "$report" ]; then
            sed -n '1,240p' "$report" >&2
        fi
        exit 1
    }
    python3 "$report_validator" "$report" \
        "${report_binding_args[@]}" \
        --check-state "$check_state" --expected-exit "$status"
    printf '%s\n' "$status"
}

native_run_check() {
    local -a repair_identity_args=("${native_redo_identity_args[@]}")
    local -a report_binding_args=("${native_redo_report_binding_args[@]}")
    run_check "$@"
}

trace_target_io() {
    trace=$1
    device=$2
    expectation=$3
    python3 - "$trace" "$device" "$expectation" <<'PY'
from pathlib import Path
import re
import sys

lines = Path(sys.argv[1]).read_text(encoding='utf-8', errors='replace').splitlines()
device = sys.argv[2]
expectation = sys.argv[3]
literal = f'"{device}"'
opens = [line for line in lines if literal in line and re.search(r'\bopen(?:at|at2)?\(', line)]
if not opens and expectation != 'none-optional-open':
    raise SystemExit(f'strace did not observe an open of {device}')
writable_opens = [line for line in opens if 'O_WRONLY' in line or 'O_RDWR' in line]
write_pattern = re.compile(
    r'\b(?:copy_file_range|fallocate|ftruncate|pwrite64|pwritev2?|sendfile64?|splice|writev?)\('
)
writes = [line for line in lines if (f'<{device}>' in line or f'<{device}<' in line) and write_pattern.search(line)]
target_ioctls = [
    line for line in lines
    if (f'<{device}>' in line or f'<{device}<' in line) and re.search(r'\bioctl\(', line)
]
readonly_ioctl = re.compile(
    r'\b(?:BLKGETSIZE64|BLKGETRO|BLKSSZGET|BLKPBSZGET|BLKIOMIN|BLKIOOPT|BLKALIGNOFF)\b'
    r'|\bBLKBSZSET,\s*\[512\]'
)
unreviewed_ioctls = [line for line in target_ioctls if not readonly_ioctl.search(line)]
io_uring = [
    line for line in lines
    if re.search(r'\bio_uring_(?:setup|enter|register)\(', line)
]
writable_maps = [
    line for line in lines
    if (f'<{device}>' in line or f'<{device}<' in line) and re.search(r'\bmmap\(', line)
    and 'PROT_WRITE' in line and 'MAP_SHARED' in line
]
mapping_pattern = re.compile(
    r'\bmmap\([^,]*,\s*(0x[0-9a-fA-F]+|[0-9]+),\s*[^,]*,\s*([^,]*MAP_SHARED[^,]*),'
    r'.*\)\s*=\s*(0x[0-9a-fA-F]+)'
)
mprotect_pattern = re.compile(
    r'\bmprotect\((0x[0-9a-fA-F]+),\s*(0x[0-9a-fA-F]+|[0-9]+),\s*([^)]*PROT_WRITE[^)]*)\)'
)
shared_target_maps = []
for line in lines:
    if f'<{device}>' not in line and f'<{device}<' not in line:
        continue
    match = mapping_pattern.search(line)
    if match:
        pid_match = re.match(r'^\s*(\d+)\s+', line)
        shared_target_maps.append((
            pid_match.group(1) if pid_match else '',
            int(match.group(3), 16),
            int(match.group(1), 0),
        ))
write_enabled_maps = []
for line in lines:
    match = mprotect_pattern.search(line)
    if not match:
        continue
    pid_match = re.match(r'^\s*(\d+)\s+', line)
    pid = pid_match.group(1) if pid_match else ''
    start = int(match.group(1), 16)
    end = start + int(match.group(2), 0)
    if any(pid == owner and start < base + length and base < end
           for owner, base, length in shared_target_maps):
        write_enabled_maps.append(line)
if writable_maps or write_enabled_maps:
    raise SystemExit(
        f'target was mapped writable: direct={writable_maps!r}, '
        f'mprotect={write_enabled_maps!r}'
    )
if unreviewed_ioctls:
    raise SystemExit(f'target received unreviewed ioctl attempts: {unreviewed_ioctls!r}')
if io_uring:
    raise SystemExit(f'roothealth attempted unreviewed io_uring I/O: {io_uring!r}')
unmodelled_sync = [
    line for line in lines
    if re.search(r'\b(?:sync|syncfs|sync_file_range)\(', line)
]
implicit_sync_opens = [
    line for line in opens if re.search(r'\bO_(?:D?SYNC)\b', line)
]
if unmodelled_sync or implicit_sync_opens:
    raise SystemExit(
        f'roothealth used unmodelled durability: syscalls={unmodelled_sync!r}, '
        f'opens={implicit_sync_opens!r}'
    )
if expectation in ('none', 'none-optional-open'):
    if writable_opens or writes:
        raise SystemExit(f'clean/rejected target was writable: opens={writable_opens!r}, writes={writes!r}')
elif expectation == 'repair':
    if not writable_opens or not writes:
        raise SystemExit(f'repair did not expose expected target I/O: opens={opens!r}, writes={writes!r}')
else:
    raise SystemExit(f'unknown trace expectation {expectation!r}')
print(len(writes))
PY
}

validate_rescan_execution_trace() {
    trace=$1
    device=$2
    report=$3
    checker=$4
    python3 -B - "$trace" "$device" "$report" "$checker" <<'PY'
import hashlib
import json
from pathlib import Path
import re
import sys

trace_path, device, report_path, checker_path = sys.argv[1:]
lines = Path(trace_path).read_text(encoding='utf-8', errors='replace').splitlines()
report = json.loads(Path(report_path).read_text(encoding='utf-8'))
initial = report.get('initial')
batch_samples = report.get('batch_samples')
if not isinstance(initial, dict) or not isinstance(batch_samples, list):
    raise SystemExit('repair report lacks initial/batch execution evidence')
rescans = [
    batch.get('rescan')
    for batch in batch_samples
    if isinstance(batch, dict) and isinstance(batch.get('rescan'), dict)
]
if len(rescans) != len(batch_samples):
    raise SystemExit('repair batch lacks its bound rescan execution evidence')
initial_execution = initial.get('execution')
if not isinstance(initial_execution, dict):
    raise SystemExit('repair report lacks initial execution evidence')
final = report.get('final')
final_execution = final.get('execution') if isinstance(final, dict) else None
rescan_exec_ids = {
    item.get('execution', {}).get('exec_id')
    for item in rescans
    if isinstance(item.get('execution'), dict)
}
if (
    isinstance(final_execution, dict)
    and final_execution.get('role') == 'SELF_EXEC_RESCAN'
    and final_execution.get('exec_id') not in rescan_exec_ids
):
    rescans.append(final)
initial_pid = initial_execution.get('pid')
expected_binary = hashlib.sha256(Path(checker_path).read_bytes()).hexdigest()
if initial_execution.get('binary_sha256') != expected_binary:
    raise SystemExit('reported initial binary hash differs from the executed checker')

pid_pattern = re.compile(r'^\s*(?:\[pid\s+)?(\d+)\]?\s+')
open_pattern = re.compile(r'\bopen(?:at|at2)?\(')
exec_pattern = re.compile(r'\bexecve(?:at)?\(')
target_write_pattern = re.compile(
    r'\b(?:copy_file_range|fallocate|ftruncate|pwrite64|pwritev2?|' \
    r'sendfile64?|splice|writev?)\('
)

def line_pid(line: str) -> int | None:
    match = pid_pattern.match(line)
    return int(match.group(1)) if match else None

report_literals = (f'"{report_path}"', f'"{Path(report_path).name}"')
report_opens = [
    line for line in lines
    if line_pid(line) == initial_pid
    and any(literal in line for literal in report_literals)
    and open_pattern.search(line)
]
if not report_opens or any('O_CLOEXEC' not in line for line in report_opens):
    raise SystemExit('initial report descriptor was not opened O_CLOEXEC')

if not rescans:
    plan = report.get('plan')
    commit = report.get('commit')
    if (
        not isinstance(plan, dict)
        or plan.get('operations') != 0
        or not isinstance(commit, dict)
        or commit.get('started') is not False
        or commit.get('completed') is not False
        or not isinstance(final, dict)
        or final.get('binding') != 'INITIAL'
        or final.get('execution') != initial_execution
    ):
        raise SystemExit('zero-plan repair did not preserve exact INITIAL evidence')
    print(0)
    raise SystemExit(0)

seen_pids = {initial_pid}
seen_exec_ids = {initial_execution.get('exec_id')}
for index, rescan in enumerate(rescans):
    execution = rescan.get('execution') if isinstance(rescan, dict) else None
    if not isinstance(execution, dict):
        raise SystemExit(f'rescan {index} lacks execution evidence')
    child_pid = execution.get('pid')
    child_exec = execution.get('exec_id')
    if child_pid in seen_pids or child_exec in seen_exec_ids:
        raise SystemExit(f'rescan {index} reused PID or exec_id')
    seen_pids.add(child_pid)
    seen_exec_ids.add(child_exec)
    if execution.get('binary_sha256') != expected_binary:
        raise SystemExit(f'rescan {index} binary hash differs from checker')
    child_lines = [line for line in lines if line_pid(line) == child_pid]
    execs = [line for line in child_lines if exec_pattern.search(line)]
    if not execs:
        raise SystemExit(f'rescan {index} PID has no observed self-exec')
    target_opens = [
        line for line in child_lines
        if f'"{device}"' in line and open_pattern.search(line)
        and re.search(r'=\s*\d+<' + re.escape(device), line)
    ]
    if not target_opens:
        raise SystemExit(f'rescan {index} did not independently open the target')
    if any(
        'O_WRONLY' in line or 'O_RDWR' in line or 'O_CLOEXEC' not in line
        for line in target_opens
    ):
        raise SystemExit(f'rescan {index} target open was not O_RDONLY|O_CLOEXEC')
    target_writes = [
        line for line in child_lines
        if (f'<{device}>' in line or f'<{device}<' in line) and target_write_pattern.search(line)
    ]
    if target_writes:
        raise SystemExit(f'rescan {index} attempted target writes: {target_writes!r}')
    report_access = [
        line for line in child_lines
        if (any(literal in line for literal in report_literals)
            and open_pattern.search(line))
        or (f'<{report_path}>' in line and target_write_pattern.search(line))
    ]
    if report_access:
        raise SystemExit(f'rescan {index} accessed the report descriptor/path')
    pipe_written = 0
    for line in child_lines:
        if '<pipe:[' not in line or not re.search(r'\bwritev?\(', line):
            continue
        match = re.search(r'\)\s*=\s*(\d+)\s*$', line)
        if match:
            pipe_written += int(match.group(1))
    if pipe_written != execution.get('pipe_payload_bytes'):
        raise SystemExit(
            f'rescan {index} pipe bytes differ: trace={pipe_written} '
            f'report={execution.get("pipe_payload_bytes")!r}'
        )
print(len(rescans))
PY
}

assert_manifest_equal() {
    image=$1
    case_name=$2
    expected_manifest=${3:-$base_manifest}
    actual="$work/manifest-$case_name.json"
    namespace_manifest "$image" "$actual"
    if ! cmp -s "$expected_manifest" "$actual"; then
        echo "T1OS namespace/content manifest differs after $case_name repair." >&2
        python3 - "$expected_manifest" "$actual" <<'PY' >&2
import json, sys
left = json.load(open(sys.argv[1], encoding='utf-8'))
right = json.load(open(sys.argv[2], encoding='utf-8'))
for key in sorted(set(left) | set(right)):
    if left.get(key) != right.get(key):
        print(key, left.get(key), right.get(key))
PY
        exit 1
    fi
}

assert_recovery_manifest() {
    image=$1
    case_name=$2
    actual="$work/manifest-$case_name.json"
    namespace_manifest "$image" "$actual"
    python3 - "$base_manifest" "$actual" "$recovery_sha" <<'PY'
import json
import sys

expected = json.load(open(sys.argv[1], encoding='utf-8'))
actual = json.load(open(sys.argv[2], encoding='utf-8'))
digest = sys.argv[3]
original = 'orphan-source/recovery.bin'
expected.pop(original)
candidates = [
    path for path, value in actual.items()
    if path.startswith('recovered files/roothealth/')
    and value.get('type') == 'file' and value.get('sha256') == digest
]
if len(candidates) != 1:
    raise SystemExit(f'expected exactly one recovered payload, found {candidates!r}')
actual.pop(candidates[0])
if expected != actual:
    differing = [key for key in sorted(set(expected) | set(actual)) if expected.get(key) != actual.get(key)]
    raise SystemExit(f'namespace differs outside recovered payload: {differing!r}')
PY
}

assert_raw_health() {
    image=$1
    case_name=$2
	inspect_args=()
	if [ "$case_name" = bitmaps ]; then
		inspect_args=(--state "$work/bitmaps.state.json")
	elif [ "$case_name" = operations-registry-stale-bitmaps ]; then
		inspect_args=(--state "$work/operations-registry-stale-bitmaps.state.json")
    elif [ "$case_name" = identity-parent-index ]; then
        inspect_args=(--state "$work/identity-parent-index.state.json")
    elif [ "$case_name" = identity-root-index ]; then
        inspect_args=(--state "$work/identity-root-index.state.json")
    elif [ "$case_name" = journal-mft-false-free ] || \
            [ "$case_name" = journal-cluster-false-free ]; then
        inspect_args=(--state "$work/$case_name.state.json")
    elif [[ "$case_name" == layout-next-instance-* ]]; then
        inspect_args=(--state "$work/$case_name.state.json")
    fi
    python3 "$fixtures" inspect "$image" "${inspect_args[@]}" \
        >"$work/inspect-$case_name.json"
    python3 - "$work/inspect-$case_name.json" "$case_name" <<'PY'
import json
import sys

inspection = json.load(open(sys.argv[1], encoding='utf-8'))
for field in ('boot_equal', 'primary_boot_ntfs', 'backup_boot_ntfs', 'mft_mirror_equal'):
    if inspection.get(field) is not True:
        raise SystemExit(f'{sys.argv[2]} raw invariant failed: {field}={inspection.get(field)!r}')
if inspection.get('primary_serial') != inspection.get('backup_serial'):
    raise SystemExit(f'{sys.argv[2]} boot serial copies differ')
if sys.argv[2] in ('bitmaps', 'operations-registry-stale-bitmaps'):
    expected = {
        'allocated_cluster': True,
        'free_cluster': False,
        'live_inode': True,
        'unused_inode': False,
    }
    bitmap = inspection.get('bitmap_state')
    if not isinstance(bitmap, dict) or any(
        bitmap.get(field) is not value for field, value in expected.items()
    ):
        raise SystemExit(
            f'bitmap repair did not restore raw allocation truth: '
            f'{bitmap!r}'
        )
    for prefix in ('cluster', 'mft'):
        if (
            bitmap.get(f'{prefix}_byte') != bitmap.get(f'{prefix}_expected_byte')
            or not isinstance(bitmap.get(f'{prefix}_set_mask'), int)
            or not isinstance(bitmap.get(f'{prefix}_clear_mask'), int)
            or bitmap.get(f'{prefix}_set_mask') == 0
            or bitmap.get(f'{prefix}_clear_mask') == 0
            or bitmap.get(f'{prefix}_set_mask') & bitmap.get(f'{prefix}_clear_mask')
        ):
            raise SystemExit(
                f'bitmap repair did not restore same-byte mixed truth: {bitmap!r}'
            )
if sys.argv[2] in ('identity-parent-index', 'identity-root-index'):
    reference = inspection.get('index_reference')
    if not isinstance(reference, dict) or reference.get('valid') is not True:
        raise SystemExit(
            f'{sys.argv[2]} did not restore the exact MFT reference: {reference!r}'
        )
if sys.argv[2] in ('journal-mft-false-free', 'journal-cluster-false-free'):
    allocation = inspection.get('journal_allocation')
    if (
        not isinstance(allocation, dict)
        or allocation.get('mft_bit') is not True
        or allocation.get('cluster_bit') is not True
        or allocation.get('journal_cluster_owner_count') != 1
    ):
        raise SystemExit(
            f'{sys.argv[2]} did not restore exact journal allocation truth: '
            f'{allocation!r}'
        )
if sys.argv[2].startswith('layout-next-instance-'):
    value = inspection.get('layout_candidate')
    if (
        not isinstance(value, dict)
        or value.get('next_attr_instance')
        != value.get('expected_repaired_next_attr_instance')
        or value.get('prepared_instance_value')
        != (0xffff if sys.argv[2].endswith('-wrap-candidate') else None)
    ):
        raise SystemExit(
            f'{sys.argv[2]} did not restore the derived allocator cursor: {value!r}'
        )
PY
}

assert_journal_allocation_healthy() {
    image=$1
    case_name=$2
    inspection="$work/journal-allocation-$case_name.inspect.json"
    python3 "$fixtures" inspect "$image" \
        --state "$work/compound-journal-mft.state.json" >"$inspection"
    python3 - "$inspection" "$case_name" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding='utf-8')).get('journal_allocation')
if (
    not isinstance(value, dict)
    or value.get('mft_bit') is not True
    or value.get('cluster_bit') is not True
    or value.get('journal_cluster_owner_count') != 1
    or value.get('ownership_records_examined', 0) <= 0
):
    raise SystemExit(
        f'{sys.argv[2]} lacks exact repaired journal ownership/allocation: {value!r}'
    )
PY
}

repair_case() {
    case_name=$1
    image=$2
    manifest_mode=$3
    shift 3
    expected_kinds=("$@")
    run_check "$image" "initial-$case_name" unsafe >/dev/null
    before=$(sha256sum "$image" | awk '{print $1}')
    report="$work/repair-$case_name.json"
    trace="$work/repair-$case_name.strace"
    active_loop=$(losetup --find --show "$image")
    repair_device=$active_loop
    [ "$(blockdev --getro "$active_loop")" = 0 ] || {
        echo "Repair loop unexpectedly read-only for $case_name." >&2
        exit 1
    }
    set +e
    timeout 300s strace -f -yy -o "$trace" \
        -e trace="$trace_syscalls" \
        "$repair_checker" --repair --quiet --require-t1os-root \
        "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
        --report "$report" "$active_loop" \
        >"$work/repair-$case_name.log" 2>&1
    status=$?
    set -e
    losetup --detach "$active_loop"
    active_loop=
    if [ "$status" -ne 0 ]; then
        echo "Repair case $case_name returned $status; expected rescan-backed 0." >&2
        sed -n '1,220p' "$work/repair-$case_name.log" >&2
        exit 1
    fi
    after=$(sha256sum "$image" | awk '{print $1}')
    [ "$before" != "$after" ] || {
        echo "Repair case $case_name made no image change." >&2
        exit 1
    }
    validator_args=()
    for kind in "${expected_kinds[@]}"; do
        validator_args+=(--expected-kind "$kind")
    done
    python3 "$report_validator" "$report" \
        "${report_binding_args[@]}" "${validator_args[@]}"
    trace_target_io "$trace" "$repair_device" repair >/dev/null || {
        echo "Target I/O trace validation failed for $case_name." >&2
        exit 1
    }
    validate_rescan_execution_trace "$trace" "$repair_device" "$report" \
        "$repair_checker" >/dev/null
    run_check "$image" "final-$case_name" clean >/dev/null
    assert_raw_health "$image" "$case_name"
    case "$manifest_mode" in
        equal) assert_manifest_equal "$image" "$case_name" ;;
        recovery) assert_recovery_manifest "$image" "$case_name" ;;
        operations-stale) assert_manifest_equal "$image" "$case_name" \
            "$operations_stale_manifest" ;;
        *) echo "Unknown manifest mode $manifest_mode" >&2; exit 1 ;;
    esac
    printf 'PASS repair-%-22s exit=0 before=%s after=%s\n' \
        "$case_name" "$before" "$after"
}

assert_clean_foundation_report() {
    case_name=$1
    action_id=$2
    expected_kind=$3
    report_path=${4:-$work/repair-$case_name.json}
    python3 -B - "$report_path" "$action_id" \
        "$expected_kind" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1], encoding='utf-8'))
action_id = int(sys.argv[2])
kind = sys.argv[3]
foundation = report.get('foundation_repairs')
if not isinstance(foundation, list) or len(foundation) != 1:
    raise SystemExit('clean sole-peer repair is not exactly one foundation action')
action = foundation[0]
if action.get('action_id') != action_id or action.get('kind') != kind:
    raise SystemExit(f'clean foundation action differs: {action!r}')
if report.get('repairs') != [] or report.get('transactions') != []:
    raise SystemExit('clean foundation repair fabricated an internal WAL transaction')
plan = report.get('plan', {})
if (
    plan.get('operations') != 1
    or plan.get('foundation_operations') != 1
    or plan.get('wal_operations') != 0
    or plan.get('by_action_id') != {str(action_id): 1}
    or plan.get('by_kind') != {kind: 1}
):
    raise SystemExit(f'clean foundation plan is not exact: {plan!r}')
initial = report.get('initial', {})
if (
    initial.get('exit_code') != 2
    or initial.get('result') != 'unsafe'
    or initial.get('dirty') is not False
    or initial.get('logfile_clean') is not True
):
    raise SystemExit(f'foundation fixture did not start NTFS-clean: {initial!r}')
rescans = report.get('rescans')
if (
    not isinstance(rescans, list)
    or len(rescans) != 1
    or rescans[0].get('stage') != 'FINAL'
    or rescans[0].get('binding') != 'FOUNDATION'
    or rescans[0].get('dirty') is not False
    or rescans[0].get('result') != 'clean'
):
    raise SystemExit(f'clean foundation rescan differs: {rescans!r}')
wal = report.get('wal', {})
if wal.get('write_boundaries') != 0 or wal.get('actions') != []:
    raise SystemExit('clean foundation repair advanced the internal WAL')
if report.get('dirty_cleared') is not False:
    raise SystemExit('clean foundation repair fabricated a dirty lifecycle')
PY
}

assert_native_redo_target() {
    image=$1
    phase=$2
    inspection="$work/native-redo-$phase.inspect.json"
    python3 "$fixtures" inspect "$image" >"$inspection"
    python3 - "$inspection" "$native_redo_manifest" "$phase" <<'PY'
import json
import sys

seen = json.load(open(sys.argv[1], encoding='utf-8'))
manifest = json.load(open(sys.argv[2], encoding='utf-8'))
phase = sys.argv[3]
transaction = manifest['transaction']
before = bytes.fromhex(transaction['before_utf16le']).decode('utf-16-le')
after = bytes.fromhex(transaction['after_utf16le']).decode('utf-16-le')
if before == after or len(before) != 1 or len(after) != 1:
    raise SystemExit('native redo manifest has no exact one-code-unit delta')
expected = transaction['volume_name_before'] if phase == 'before' else \
    transaction['volume_name_after']
if seen.get('volume_name') != expected:
    raise SystemExit(
        f'native redo target differs in {phase}: '
        f'{seen.get("volume_name")!r} != {expected!r}'
    )
if seen.get('mft_mirror_equal') is not True:
    raise SystemExit(f'native redo {phase} primary/$MFTMirr records differ')
PY
}

assert_native_mirror_disagreement() {
    image=$1
    state=$2
    inspection="$work/$(basename "$state" .state.json).inspect.json"
    python3 "$fixtures" inspect "$image" --state "$state" >"$inspection"
    python3 - "$inspection" "$native_redo_manifest" <<'PY'
import json
import sys

seen = json.load(open(sys.argv[1], encoding='utf-8'))
manifest = json.load(open(sys.argv[2], encoding='utf-8'))
value = seen.get('native_redo_primary_applied')
if not isinstance(value, dict) or value.get('differ') is not True:
    raise SystemExit('native mirror-interruption fixture lacks a valid disagreement')
before = bytes.fromhex(manifest['transaction']['before_utf16le']).decode('utf-16-le')
after = bytes.fromhex(manifest['transaction']['after_utf16le']).decode('utf-16-le')
if value.get('primary_name') != manifest['transaction']['volume_name_after']:
    raise SystemExit(f'native disagreement primary differs: {value!r}')
if value.get('mirror_name') != manifest['transaction']['volume_name_before']:
    raise SystemExit(f'native disagreement mirror differs: {value!r}')
PY
}

native_repair_case() {
    image=${1:-$native_redo_image}
    case_name=${2:-native-redo}
    initial_phase=${3:-before}
    local -a repair_identity_args=("${native_redo_identity_args[@]}")
    local -a report_binding_args=("${native_redo_report_binding_args[@]}")
    if [ "$initial_phase" = before ]; then
        assert_native_redo_target "$image" before
    else
        assert_native_mirror_disagreement "$image" \
            "$work/$case_name.state.json"
    fi
    run_check "$image" "initial-$case_name" unsafe >/dev/null
    before=$(sha256sum "$image" | awk '{print $1}')
    report="$work/repair-$case_name.json"
    trace="$work/repair-$case_name.strace"
    active_loop=$(losetup --find --show "$image")
    repair_device=$active_loop
    [ "$(blockdev --getro "$active_loop")" = 0 ] || {
        echo 'Native redo repair loop unexpectedly read-only.' >&2
        exit 1
    }
    set +e
    timeout 300s strace -f -yy -o "$trace" -e trace="$trace_syscalls" \
        "$repair_checker" --repair --quiet --require-t1os-root \
        "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
        --report "$report" "$active_loop" \
        >"$work/repair-$case_name.log" 2>&1
    status=$?
    set -e
    losetup --detach "$active_loop"
    active_loop=
    [ "$status" -eq 0 ] || {
        echo "Native redo repair returned $status; expected rescan-backed 0." >&2
        sed -n '1,240p' "$work/repair-$case_name.log" >&2
        exit 1
    }
    after=$(sha256sum "$image" | awk '{print $1}')
    [ "$before" != "$after" ] || {
        echo 'Native redo repair made no image change.' >&2
        exit 1
    }
    python3 "$report_validator" "$report" \
        "${report_binding_args[@]}" \
        --expected-kind logfile-redo --expected-kind logfile-restart \
        --expected-kind volume-dirty-clear
    trace_target_io "$trace" "$repair_device" repair >/dev/null
    validate_rescan_execution_trace "$trace" "$repair_device" "$report" \
        "$repair_checker" >/dev/null
    run_check "$image" "final-$case_name" clean >/dev/null
    assert_raw_health "$image" "$case_name"
    assert_native_redo_target "$image" after
    assert_manifest_equal "$image" "$case_name" \
        "$native_redo_base_manifest"
    python3 - "$report" "$native_redo_manifest" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1], encoding='utf-8'))
fixture = json.load(open(sys.argv[2], encoding='utf-8'))
if report.get('foundation_repairs') != []:
    raise SystemExit('native redo used a forbidden direct-copy foundation repair')
repairs = report.get('repairs')
if not isinstance(repairs, list):
    raise SystemExit('native redo report lacks repairs')
if [item.get('action_id') for item in repairs] != [5, 5, 6, 6, 25, 25]:
    raise SystemExit('native redo physical action order differs')
transactions = report.get('batch_samples')
ledger = report.get('batch_ledger')
if (
    not isinstance(transactions, list)
    or len(transactions) != 2
    or not isinstance(ledger, dict)
    or ledger.get('record_count') != 2
):
    raise SystemExit('native redo report does not have two bounded transaction samples')
if transactions[0].get('phase') != 'METADATA_REPAIR' or transactions[0].get('by_action_id') != {'5': 2, '6': 2}:
    raise SystemExit('native redo metadata transaction counts differ')
if transactions[1].get('phase') != 'DIRTY_CLEAR' or transactions[1].get('by_action_id') != {'25': 2}:
    raise SystemExit('native redo dirty-clear transaction counts differ')
native_log = report.get('native_log')
if not isinstance(native_log, dict):
    raise SystemExit('native redo report lacks native_log evidence')
expected_counts = {
    'checked': True,
    'state': 'REPLAY_PLANNED',
    'version_major': 1,
    'version_minor': 1,
    'pages_examined': 7,
    'wiped_pages_scanned': 1,
    'checkpoint_records_examined': 0,
    'control_records_examined': 2,
    'mutation_records_examined': 1,
    'open_attribute_tables': 0,
    'attribute_name_tables': 0,
    'dirty_page_tables': 0,
    'transaction_tables': 0,
    'actions_seen': 3,
    'redo_actions': 1,
    'undo_actions': 0,
    'restart_pages_planned': 2,
    'unsupported_actions': 0,
    'io_errors': 0,
    'parse_errors': 0,
    'planned_io_operations': 4,
    'planned_io_bytes': 10240,
}
for field, expected in expected_counts.items():
    if native_log.get(field) != expected:
        raise SystemExit(
            f'native redo native_log.{field} differs: {native_log.get(field)!r}'
        )
if (
    not isinstance(native_log.get('logfile_bytes'), int)
    or native_log['logfile_bytes'] <= 0
    or native_log['logfile_bytes'] % 4096
    or native_log.get('pages_expected') != native_log['logfile_bytes'] // 4096
):
    raise SystemExit('native redo logfile geometry does not reconcile')
restart = fixture['restart']
expected_lsns = {
    'restart_lsn': int(restart['synced_lsn'], 0),
    'synced_lsn': int(restart['synced_lsn'], 0),
    'committed_lsn': int(restart['committed_lsn'], 0),
    'latest_lsn': int(restart['current_lsn'], 0),
}
for field, expected in expected_lsns.items():
    if native_log.get(field) != expected:
        raise SystemExit(
            f'native redo native_log.{field} differs: {native_log.get(field)!r}'
        )
PY
    printf 'PASS repair-%-22s exit=0 before=%s after=%s actions=5,5,6,6,25,25\n' \
        "$case_name" "$before" "$after"
}

native_clean_disagreement_refusal() {
    local -a repair_identity_args=("${native_redo_identity_args[@]}")
    local -a report_binding_args=("${native_redo_report_binding_args[@]}")
    image=$native_redo_clean_disagree_image
    case_name=native-redo-clean-disagree
    assert_native_mirror_disagreement "$image" \
        "$work/native-redo-clean-disagree.state.json"
    run_check "$image" "initial-$case_name" unsafe >/dev/null
    before=$(sha256sum "$image" | awk '{print $1}')
    report="$work/refusal-$case_name.json"
    trace="$work/refusal-$case_name.strace"
    active_loop=$(losetup --find --show "$image")
    device=$active_loop
    set +e
    timeout 300s strace -f -yy -o "$trace" -e trace="$trace_syscalls" \
        "$repair_checker" --repair --quiet --require-t1os-root \
        "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
        --report "$report" "$active_loop" \
        >"$work/refusal-$case_name.log" 2>&1
    status=$?
    set -e
    losetup --detach "$active_loop"
    active_loop=
    [ "$status" -eq 2 ] || {
        echo "Clean unresolved MFT disagreement returned $status; expected 2." >&2
        sed -n '1,220p' "$work/refusal-$case_name.log" >&2
        exit 1
    }
    [ "$before" = "$(sha256sum "$image" | awk '{print $1}')" ] || {
        echo 'Clean unresolved MFT disagreement changed the target.' >&2
        exit 1
    }
    python3 "$report_validator" "$report" \
        "${report_binding_args[@]}" --rejection-exit 2 --rejection-wal empty
    trace_target_io "$trace" "$device" none >/dev/null
    assert_native_mirror_disagreement "$image" \
        "$work/native-redo-clean-disagree.state.json"
    printf 'PASS repair-refusal-%-16s exit=2 sha256=%s writes=0\n' \
        native-mft-disagree "$before"
}

assert_deep_corruption() {
    image=$1
    case_name=$2
    state="$work/$case_name.state.json"
    inspection="$work/$case_name.inspect.json"
    python3 "$fixtures" inspect "$image" --state "$state" >"$inspection"
    python3 - "$case_name" "$state" "$inspection" <<'PY'
import json
import sys

name = sys.argv[1]
state = json.load(open(sys.argv[2], encoding='utf-8'))
seen = json.load(open(sys.argv[3], encoding='utf-8'))
if name == 'dirty-only':
    value = seen.get('volume_dirty_wiped_log')
    ok = (
        isinstance(value, dict)
        and value.get('primary_flags', 0) & 1
        and value.get('mirror_flags', 0) & 1
        and value.get('logfile_size') == state['logfile_size']
        and value.get('logfile_all_ff') is True
    )
elif name == 'dirty-log':
    value = seen.get('dirty_log')
    ok = (
        isinstance(value, dict)
        and value.get('primary_flags', 0) & 1
        and value.get('mirror_flags', 0) & 1
        and value.get('logfile_size') == state['logfile_size']
        and value.get('restart_magic') == ['RSTR', 'RSTR']
        and value.get('restart_usa') == [0xA101, 0xA102]
        and len(value.get('restart_page_sha256', [])) == 2
        and all(
            isinstance(item, str) and len(item) == 64
            for item in value.get('restart_page_sha256', [])
        )
    )
elif name.startswith('journal-'):
    value = seen.get('journal_allocation')
    duplicate = 'duplicate' in name
    false_mft = 'mft-false-free' in name
    false_cluster = 'cluster-false-free' in name
    ok = (
        isinstance(value, dict)
        and value.get('mft_bit') is (not false_mft)
        and value.get('cluster_bit') is (not false_cluster)
        and value.get('journal_cluster_owner_count') == (2 if duplicate else 1)
        and value.get('ownership_records_examined', 0) > 0
        and (
            (duplicate and value.get('overlap_lcn') == state['journal_cluster'])
            or (not duplicate and value.get('overlap_lcn') is None)
        )
    )
elif name == 'attribute-list':
    value = seen.get('attribute_list')
    ok = isinstance(value, dict) and value.get('valid') is False and value.get('extent_valid') is True
elif name == 'attribute-list-equal-triple-order':
    value = seen.get('attribute_list_hardlink')
    ok = (
        isinstance(value, dict)
        and value.get('link_count') == 3
        and value.get('resolved_values_collated') is False
        and value.get('all_entries_resolved') is True
        and value.get('all_reciprocal') is True
        and value.get('ale_instance_order') == state['ale_instance_order']
        and value.get('ale_record_order') == state['ale_record_order']
        and sorted(value.get('value_sha256_in_ale_order', [])) == state['value_sha256']
        and state.get('permitted_equal_triple_order') is True
        and value.get('ale_parent_order') == state['permuted_ale_parent_order']
        and value.get('ale_parent_order') != state['original_ale_parent_order']
        and all(
            item.get('semantic_key_match') is True
            and item.get('reciprocal') is True
            for item in value.get('index_copies', [])
        )
    )
elif name == 'large-attribute-list-boundary':
    value = seen.get('large_attribute_list_boundary')
    ok = (
        isinstance(value, dict)
        and value.get('nonresident') is True
        and value.get('logical_size') == state['logical_size']
        and value.get('logical_size') == 0x40000
        and value.get('entry_count') == state['entry_count']
        and value.get('entry_offset') == state['entry_offset']
        and value.get('entry_length') == state['entry_length']
        and value.get('extent_inode') == state['extent_inode']
        and value.get('extent_sequence') == state['expected_sequence']
        and value.get('reference_sequence') == state['wrong_sequence']
        and value.get('reference_sequence') != value.get('extent_sequence')
        and value.get('stream_sha256') == state['stream_after_sha256']
        and value.get('stream_sha256') != state['stream_before_sha256']
    )
elif name == 'large-attribute-list-boundary-overrun':
    value = seen.get('large_attribute_list_boundary_overrun')
    ok = (
        isinstance(value, dict)
        and value.get('nonresident') is True
        and value.get('logical_size') == 0x40000
        and value.get('initialized_size') == 0x40000
        and value.get('entry_offset') == state['entry_offset']
        and value.get('entry_length') == state['wrong_entry_length']
        and value.get('claimed_entry_end') == state['claimed_entry_end']
        and value.get('claimed_entry_end') == 0x40008
        and value.get('stream_sha256') == state['stream_after_sha256']
        and value.get('stream_sha256') != state['stream_before_sha256']
        and value.get('tail_hex') == state['tail_hex']
        and value.get('parse_rejected') is True
        and value.get('parsed_entries') == 0
    )
elif name == 'large-attribute-list-truncated':
    value = seen.get('large_attribute_list_truncated')
    ok = (
        isinstance(value, dict)
        and value.get('nonresident') is True
        and state['original_logical_size'] == 0x40000
        and state['truncated_size'] == 0x3ffff
        and value.get('logical_size') == state['truncated_size']
        and value.get('initialized_size') == state['truncated_size']
        and value.get('allocated_size') == state['allocated_size']
        and value.get('prefix_sha256') == state['prefix_sha256']
        and value.get('tail_hex') == state['truncated_tail_hex']
        and value.get('parse_rejected') is True
        and value.get('parsed_entries') == 0
    )
elif name == 'large-attribute-list-over-limit':
    value = seen.get('large_attribute_list_over_limit')
    ok = (
        isinstance(value, dict)
        and value.get('nonresident') is True
        and value.get('maximum_valid_size') == 0x40000
        and value.get('logical_size') == 0x40008
        and value.get('initialized_size') == 0x40008
        and value.get('logical_size') == state['over_limit_size']
        and value.get('allocated_size') == state['allocated_size']
        and value.get('highest_vcn') == state['highest_vcn']
        and value.get('runs') == state['expanded_runs']
        and value.get('entry_count') == state['entry_count']
        and value.get('bound_entry_count') == state['bound_entry_count']
        and value.get('last_entry_offset') == state['last_entry_offset']
        and value.get('last_entry_length') == state['last_entry_length']
        and value.get('last_entry_end') == state['over_limit_size']
        and value.get('appended_lcn') == state['appended_lcn']
        and value.get('appended_cluster_bitmap_set') is True
        and value.get('mapping_hex') == state['mapping_after_hex']
        and value.get('mapping_hex') != state['mapping_before_hex']
        and value.get('opaque_mapping_slack_hex') == state['opaque_mapping_slack_hex']
        and value.get('valid_prefix_sha256') == state['valid_prefix_sha256']
        and value.get('stream_sha256') == state['stream_sha256']
    )
elif name == 'runlist-size':
    value = seen.get('runlist_size')
    ok = (
        isinstance(value, dict)
        and value.get('initialized_size') == state['wrong_initialized_size']
        and value.get('data_size') == state['data_size']
        and value.get('content_sha256') == state['content_sha256']
    )
elif name == 'reparse-index':
    value = seen.get('reparse_index')
    ok = isinstance(value, dict) and value.get('reserved') == '5a0000'
elif name == 'secure-derived':
    value = seen.get('secure_derived')
    ok = (
        isinstance(value, dict)
        and value.get('sds_equal') is False
        and value.get('sds_primary_sha256') == state['sds_primary_sha256']
        and value.get('index_reserved') == {'$SDH': '5a0000', '$SII': '5a0000'}
    )
elif name == 'secure-sii-stale':
    value = seen.get('secure_sii_stale')
    ok = (
        isinstance(value, dict)
        and value.get('security_id') == state['security_id']
        and value.get('sds_offset') == state['stale_sds_offset']
        and value.get('sds_length') == state['sds_length']
    )
elif name == 'upcase-attrdef':
    value = seen.get('upcase_attrdef')
    ok = (
        isinstance(value, dict)
        and value.get('upcase_value') == state['upcase_wrong']
        and value.get('attrdef_type') == state['attrdef_wrong_type']
    )
elif name == 'upcase-nonascii':
    value = seen.get('upcase_nonascii')
    ok = (
        isinstance(value, dict)
        and value.get('stream_size') == state['stream_size']
        and value.get('codepoint') == state['codepoint']
        and value.get('mapping') == state['wrong_mapping']
    )
elif name == 'user-defined-runlist':
    value = seen.get('user_defined_runlist')
    ok = (
        isinstance(value, dict)
        and value.get('type') == state['user_defined_type']
        and value.get('mapping_hex') == state['after_mapping_hex']
        and value.get('mapping_hex') != state['before_mapping_hex']
    )
elif name == 'unflagged-sparse-run':
    value = seen.get('unflagged_sparse_run')
    original_runs = state['original_runs']
    mutated_runs = state['mutated_runs']
    ok = (
        isinstance(value, dict)
        and state['attribute_flags'] == 0
        and value.get('attribute_flags') == 0
        and value.get('attribute_instance') == state['attribute_instance']
        and all(run[1] is not None for run in original_runs)
        and value.get('runs') == mutated_runs
        and value.get('sparse_run_count') == 1
        and mutated_runs[:-1] == original_runs[:-1]
        and mutated_runs[-1][0] == original_runs[-1][0]
        and mutated_runs[-1][1] is None
        and mutated_runs[-1][2] == original_runs[-1][2]
        and value.get('terminator_record_offset') == state['mutated_terminator_record_offset']
        and value.get('mapping_hex') == state['after_mapping_hex']
        and value.get('mapping_hex') != state['before_mapping_hex']
        and value.get('tail_hex') == state['mutated_tail_hex']
        and state.get('opaque_post_terminator_slack') is True
    )
elif name == 'mapping-pair-tail':
    value = seen.get('mapping_pair_tail')
    expected_tail = bytes((state['tail_value'],)) + bytes(state['tail_length'] - 1)
    ok = (
        isinstance(value, dict)
        and state['before_tail_hex'] == bytes(state['tail_length']).hex()
        and value.get('attribute_flags') == state['attribute_flags']
        and value.get('attribute_instance') == state['attribute_instance']
        and value.get('runs') == state['runs']
        and value.get('encoded_mapping_hex') == state['encoded_mapping_hex']
        and value.get('encoded_mapping_sha256') == state['encoded_mapping_sha256']
        and value.get('terminator_record_offset') == state['terminator_record_offset']
        and value.get('tail_record_offset') == state['tail_record_offset']
        and value.get('tail_hex') == expected_tail.hex()
        and value.get('tail_nonzero_record_offsets') == [state['tail_record_offset']]
        and value.get('opaque_ignored_slack') is True
    )
elif name == 'attribute-end-tail':
    value = seen.get('attribute_end_tail')
    expected_tail = bytes((state['tail_value'],)) + bytes(state['tail_length'] - 1)
    ok = (
        isinstance(value, dict)
        and state['tail_length'] == 4
        and state['before_tail_hex'] == bytes(4).hex()
        and value.get('at_end_record_offset') == state['at_end_record_offset']
        and value.get('at_end_value') == 0xffffffff
        and value.get('tail_record_offset') == state['tail_record_offset']
        and value.get('tail_hex') == expected_tail.hex()
        and value.get('tail_nonzero_record_offsets') == [state['tail_record_offset']]
        and value.get('bytes_in_use') == state['bytes_in_use']
        and state['tail_record_offset'] + state['tail_length'] == state['bytes_in_use']
    )
elif name == 'link-reciprocity':
    value = seen.get('link_reciprocity')
    ok = (
        isinstance(value, dict)
        and value.get('link_count') == state['wrong_link_count']
        and value.get('file_name_count', 0) >= state['expected_link_count']
        and value.get('target_parent_sequence') == 0
    )
elif name == 'hardlink-value-order':
    value = seen.get('hardlink_collation')
    ok = (
        isinstance(value, dict)
        and value.get('link_count') == 2
        and value.get('file_name_count') == 2
        and value.get('resident_parent_order') == state['wrong_parent_order']
        and value.get('resident_parent_order') == list(reversed(state['expected_parent_order']))
        and value.get('attribute_instances') == state['wrong_attribute_instances']
        and sorted(value.get('value_sha256', [])) == state['value_sha256']
        and value.get('values_distinct') is True
        and value.get('values_collated') is False
        and value.get('all_reciprocal') is True
        and all(
            item.get('reciprocal') is True
            and item.get('semantic_key_match') is True
            for item in value.get('index_copies', [])
        )
    )
elif name.startswith('file-name-cached-'):
    value = seen.get('file_name_index_field')
    copy = value.get('mutated_copy') if isinstance(value, dict) else None
    ok = (
        isinstance(value, dict)
        and isinstance(copy, dict)
        and state.get('mutation_class') == 'cached'
        and value.get('field') == state.get('field')
        and value.get('link_count') == 2
        and value.get('file_name_count') == 2
        and value.get('all_reciprocal') is True
        and copy.get('semantic_key_match') is True
        and copy.get('entry_flags_valid') is True
        and copy.get('reciprocal') is True
        and state.get('field') in copy.get('cached_differences', [])
        and copy.get('cached_difference_count', 0) >= 1
        and copy.get('key_sha256') == state.get('key_after_sha256')
        and copy.get('key_sha256') != state.get('key_before_sha256')
        and copy.get('file_name_value_sha256')
        == state.get('file_name_value_sha256')
    )
elif name.startswith('file-name-stable-'):
    value = seen.get('file_name_index_field')
    copy = value.get('mutated_copy') if isinstance(value, dict) else None
    ok = (
        isinstance(value, dict)
        and isinstance(copy, dict)
        and state.get('mutation_class') == 'stable'
        and value.get('link_count') == 2
        and value.get('file_name_count') == 2
        and value.get('all_reciprocal') is False
        and copy.get('reciprocal') is False
        and copy.get('semantic_key_match')
        is state.get('expected_semantic_key_match')
        and copy.get('entry_flags_valid')
        is state.get('expected_entry_flags_valid')
        and copy.get('file_name_value_sha256')
        == state.get('file_name_value_sha256')
    )
elif name == 'posix-collision-clean':
    value = seen.get('posix_collision')
    ok = (
        isinstance(value, dict)
        and value.get('canonical_collision') is True
        and value.get('exact_utf16_duplicate') is False
        and value.get('all_posix') is True
        and value.get('unique_entry_references') is True
        and value.get('all_reciprocal') is True
        and len(value.get('members', [])) == 2
        and all(
            member.get('entry_flags_valid') is True
            and member.get('stable_key_match') is True
            and member.get('reciprocal') is True
            for member in value.get('members', [])
        )
    )
elif name.startswith('posix-collision-'):
    expectations = {
        'posix-collision-exact-duplicate': (True, True, True, True, True, False),
        'posix-collision-mixed-namespace': (True, False, False, True, True, False),
        'posix-collision-duplicate-reference': (True, False, True, False, False, False),
        'posix-collision-required-anchor': (True, False, True, True, True, True),
    }
    value = seen.get('posix_collision')
    observed = (
        value.get('canonical_collision'),
        value.get('exact_utf16_duplicate'),
        value.get('all_posix'),
        value.get('all_reciprocal'),
        value.get('unique_entry_references'),
        value.get('required_anchor'),
    ) if isinstance(value, dict) else None
    ok = observed == expectations.get(name) and len(value.get('members', [])) == 2
elif name == 'sparse-unit-header':
    value = seen.get('sparse_stream')
    ok = (
        isinstance(value, dict)
        and value.get('attribute_flags') == state['attribute_flags']
        and value.get('attribute_instance') == state['attribute_instance']
        and value.get('compression_unit') == state['wrong_compression_unit']
        and value.get('data_size') == state['data_size']
        and value.get('initialized_size') == state['initialized_size']
        and value.get('allocated_size') == state['allocated_size']
        and value.get('compressed_size') == state['compressed_size']
        and value.get('runs') == state['runs']
        and value.get('mapped_lcns') == state['mapped_lcns']
        and value.get('logical_sha256') == state['logical_sha256']
        and value.get('mapping_hex') == state['mapping_hex']
        and value.get('attribute_record_offset') == state['attribute_record_offset']
        and value.get('attribute_record_length') == state['attribute_record_length']
        and value.get('mapping_pairs_offset') == state['mapping_pairs_offset']
        and value.get('terminator_attribute_offset') == state['terminator_attribute_offset']
        and value.get('mapping_tail_length') == state['mapping_tail_length']
        and value.get('mapping_tail_hex') == state['mapping_tail_hex']
        and value.get('mapping_tail_opaque_slack') is True
        and value.get('mapping_tail_accepted_slack') is True
        and value.get('runlist_complete') is True
        and value.get('tail_run_mapped') is True
        and value.get('mapped_cluster_bits') == [True, True]
        and value.get('mft_bitmap_bit') is True
        and value.get('hole_all_zero') is True
    )
elif name == 'duplicate-cluster':
    value = seen.get('duplicate_cluster')
    ok = (
        isinstance(value, dict)
        and value.get('same_runs') is True
        and value.get('first_sha256') == state['content_sha256']
        and value.get('second_sha256') == state['content_sha256']
        and value.get('original_second_all_allocated') is True
    )
elif name == 'compressed-metadata':
    value = seen.get('compressed_metadata')
    ok = (
        isinstance(value, dict)
        and value.get('flags') == state['flags']
        and value.get('compression_unit') == state['wrong_compression_unit']
        and value.get('compressed_size') == state['wrong_compressed_size']
    )
elif name == 'compressed-payload':
    value = seen.get('compressed_payload')
    ok = (
        isinstance(value, dict)
        and value.get('physical_offset') == state['physical_offset']
        and value.get('header_hex') == state['after_header_hex']
        and value.get('header_hex') != state['before_header_hex']
    )
elif name.startswith('layout-'):
    value = seen.get('layout_candidate')
    canonical = state.get('canonical', {})
    ranges = state.get('changed_ranges', [])
    observed_ranges = value.get('changed_ranges', []) if isinstance(value, dict) else []
    ok = (
        isinstance(value, dict)
        and state.get('kind') == name
        and state.get('typed_action_id') == 7
        and state.get('typed_apply_required') is True
        and state.get('expected_check_result') == 'unsafe'
        and state.get('expected_repair_result') in (
            'refused-no-write-until-ID7', 'success-after-fresh-rescan'
        )
        and value.get('kind') == name
        and value.get('inode') == state.get('inode')
        and value.get('record_device_offset') == state.get('record_device_offset')
        and value.get('record_size') == state.get('record_size')
        and value.get('typed_action_id') == 7
        and value.get('typed_apply_required') is True
        and value.get('evidence_class') == state.get('evidence_class')
        and value.get('record_sha256') == state.get('after_record_sha256')
        and value.get('raw_record_sha256') == state.get('after_raw_record_sha256')
        and value.get('reconstructed_before_sha256') == state.get('before_record_sha256')
        and value.get('unchanged_bytes_sha256') == state.get('unchanged_bytes_sha256')
        and value.get('resident_name_sha256') == state.get('resident_name_after_sha256')
        and value.get('resident_value_sha256') == state.get('resident_value_after_sha256')
        and value.get('changed_ranges_match') is True
        and len(ranges) > 0
        and len(observed_ranges) == len(ranges)
        and all(
            observed.get('record_offset') == expected.get('record_offset')
            and observed.get('device_offset') == expected.get('device_offset')
            and observed.get('length') == expected.get('length')
            and observed.get('current_hex') == expected.get('after_hex')
            and observed.get('matches_after') is True
            for observed, expected in zip(observed_ranges, ranges)
        )
    )
    if name.startswith('layout-attrs-offset'):
        ok = ok and value.get('attrs_offset') == canonical.get('attrs_offset', -8) + 8
    elif name.startswith('layout-bytes-in-use'):
        ok = ok and value.get('bytes_in_use') == canonical.get('bytes_in_use', 8) - 8
        if name == 'layout-bytes-in-use-dual-chain':
            ok = (
                ok
                and value.get('plausible_bytes_in_use_candidates')
                == [canonical.get('bytes_in_use'), canonical.get('bytes_in_use') + 8]
                and value.get('second_at_end_hex') == 'ffffffff00000000'
                and state.get('evidence_class') == 'AMBIGUOUS_MULTIPLE_PACKED_ENDS'
            )
    elif name in ('layout-next-instance-candidate', 'layout-next-instance-wrap-candidate'):
        expected_max = 0xffff if name.endswith('-wrap-candidate') else canonical.get('max_attribute_instance')
        ok = (
            ok
            and value.get('candidate_max_attribute_instance') == expected_max
            and value.get('expected_repaired_next_attr_instance') == ((expected_max + 1) & 0xffff)
            and value.get('next_attr_instance') == (1 if name.endswith('-wrap-candidate') else expected_max)
            and value.get('prepared_instance_value') == (0xffff if name.endswith('-wrap-candidate') else None)
            and state.get('evidence_class') == 'DERIVABLE_ALLOCATOR_CURSOR'
            and state.get('repair_required') is True
            and state.get('expected_repair_result') == 'success-after-fresh-rescan'
        )
    elif name in ('layout-resident-value-candidate', 'layout-resident-ambiguous'):
        ok = ok and value.get('resident_value_offset') == canonical.get('resident_value_offset', -1) + 1
    if name in ('layout-resident-name-candidate', 'layout-resident-ambiguous'):
        ok = ok and value.get('resident_name_offset') == canonical.get('resident_name_offset', -1) + 1
    if name in ('layout-resident-length-candidate', 'layout-resident-ambiguous'):
        ok = ok and value.get('resident_record_length') == canonical.get('resident_record_length', -1) + 1
    if name.startswith('layout-next-instance-'):
        pass
    elif name.endswith('-candidate'):
        ok = (
            ok
            and state.get('evidence_class') == 'DERIVABLE_LAYOUT_CANDIDATE'
            and value.get('resident_name_sha256') == canonical.get('resident_name_sha256')
            and value.get('resident_value_sha256') == canonical.get('resident_value_sha256')
        )
    elif not name.startswith('layout-next-instance-'):
        ok = ok and str(state.get('evidence_class', '')).startswith('AMBIGUOUS_')
else:
    raise SystemExit(f'unknown deep raw oracle {name!r}')
if not ok:
    raise SystemExit(f'{name} raw mutation oracle failed: {value!r}')
PY
}

assert_attribute_list_hardlink_clean() {
    inspection="$work/attribute-list-hardlink.clean.inspect.json"
    python3 "$fixtures" inspect "$base_image" \
        --state "$work/attribute-list-hardlink.state.json" >"$inspection"
    python3 -B - "$work/attribute-list-hardlink.state.json" "$inspection" <<'PY'
import json
import sys

state = json.load(open(sys.argv[1], encoding='utf-8'))
value = json.load(open(sys.argv[2], encoding='utf-8')).get(
    'attribute_list_hardlink'
)
if (
    not isinstance(value, dict)
    or value.get('link_count') != 3
    or value.get('selected_file_name_count') != 2
    or value.get('file_name_entry_count', 0) < 3
    or value.get('attribute_list_entry_count', 0) <= 3
    or value.get('ale_parent_order') != state['parent_inodes']
    or value.get('resolved_values_distinct') is not True
    or value.get('resolved_values_collated') is not True
    or value.get('instances_nonmonotonic') is not True
    or value.get('all_entries_resolved') is not True
    or value.get('all_reciprocal') is not True
    or len(value.get('index_copies', [])) != 2
    or any(
        item.get('semantic_key_match') is not True
        or item.get('reciprocal') is not True
        for item in value.get('index_copies', [])
    )
):
    raise SystemExit(
        'production clean ATTRIBUTE_LIST/FILE_NAME oracle failed: '
        f'{value!r}'
    )
PY
}

assert_large_attribute_list_clean() {
    inspection="$work/large-attribute-list.clean.inspect.json"
    python3 "$fixtures" inspect "$base_image" \
        --state "$work/large-attribute-list.state.json" >"$inspection"
    python3 -B - "$inspection" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding='utf-8')).get(
    'large_attribute_list'
)
runs = value.get('runs', []) if isinstance(value, dict) else []
if (
    not isinstance(value, dict)
    or value.get('nonresident') is not True
    or value.get('logical_size') != 0x40000
    or value.get('initialized_size') != value.get('logical_size')
    or value.get('allocated_size', 0) < value.get('logical_size', 0)
    or value.get('run_count') != len(runs)
    or not runs
    or any(run[1] is None or run[2] <= 0 for run in runs)
    or value.get('entry_count') != 493
    or value.get('bound_entry_count') != value.get('entry_count')
    or value.get('unique_binding_count') != value.get('entry_count')
    or value.get('storage_record_count') != 489
    or value.get('extension_record_count') != 488
    or value.get('full_length_named_data_count') != 488
    or value.get('cap_tail_named_data_count') != 1
    or value.get('max_name_length') != 255
    or value.get('all_entries_bound') is not True
    or value.get('boundary_limit') != 256 * 1024
    or value.get('boundary_entry_relation') != 'ENDS_AT_LIMIT'
    or value.get('boundary_entry_end') != 0x40000
    or value.get('read_fault_logical_offset') != 0x3ffff
    or value.get('read_fault_physical_offset', 0) <= 0
    or len(str(value.get('stream_sha256', ''))) != 64
):
    raise SystemExit(
        f'production streaming exact-256-KiB ATTRIBUTE_LIST oracle failed: {value!r}'
    )
PY
}

refusal_case() {
    local case_name=$1
    local image=$2
    local policy_ids=$3
    local check_expectation=${4:-unsafe-or-io}
    local rejection_wal=${5:-auto}
    local fixture_oracle=${6:-deep}
    local before report trace refusal_device status
    if [ "$fixture_oracle" = deep ]; then
        assert_deep_corruption "$image" "$case_name"
    fi
    run_check "$image" "initial-refusal-$case_name" "$check_expectation" >/dev/null
    before=$(sha256sum "$image" | awk '{print $1}')
    report="$work/refusal-$case_name.json"
    trace="$work/refusal-$case_name.strace"
    active_loop=$(losetup --find --show "$image")
    refusal_device=$active_loop
    set +e
    timeout 300s strace -f -yy -o "$trace" -e trace="$trace_syscalls" \
        "$repair_checker" --repair --quiet --require-t1os-root \
        "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
        --report "$report" "$active_loop" \
        >"$work/refusal-$case_name.log" 2>&1
    status=$?
    set -e
    losetup --detach "$active_loop"
    active_loop=
    local expected_status=2
    [ "$check_expectation" != io ] || expected_status=3
    if [ "$check_expectation" = unsafe-or-io ]; then
        case "$status" in 2|3) expected_status=$status ;; *) expected_status=-1 ;; esac
    fi
    [ "$status" -eq "$expected_status" ] || {
        echo "Unapproved repair family $case_name returned $status; expected fail-closed 2/3." >&2
        sed -n '1,220p' "$work/refusal-$case_name.log" >&2
        exit 1
    }
    [ "$before" = "$(sha256sum "$image" | awk '{print $1}')" ] || {
        echo "Refused repair family $case_name changed the target." >&2
        exit 1
    }
    if [ "$expected_status" -eq 3 ]; then
        python3 "$report_validator" "$report" --early-io
    else
        if [ "$rejection_wal" = auto ]; then
            rejection_wal=$(python3 -B - "$report" <<'PY'
import json
import sys
wal = json.load(open(sys.argv[1], encoding='utf-8')).get('wal', {})
if wal.get('checked') is False:
    print('unchecked')
elif wal.get('valid') is False:
    print('invalid')
elif wal.get('valid') is None:
    print('partial')
elif wal.get('state') == 'EMPTY' and wal.get('recovery_required') is True:
    print('degraded')
elif wal.get('state') == 'EMPTY':
    print('empty')
else:
    print('interrupted')
PY
)
        fi
        python3 "$report_validator" "$report" "${report_binding_args[@]}" \
            --rejection-exit 2 --rejection-wal "$rejection_wal"
    fi
    trace_target_io "$trace" "$refusal_device" none >/dev/null
    if [ "$fixture_oracle" = deep ]; then
        assert_deep_corruption "$image" "$case_name"
    fi
    printf 'PASS repair-refusal-%-16s exit=%s policies=%s sha256=%s writes=0\n' \
        "$case_name" "$expected_status" "$policy_ids" "$before"
}

clean_noop_case() {
    local case_name=$1
    local image=$2
    local before report trace slack_device status
    assert_deep_corruption "$image" "$case_name"
    run_check "$image" "opaque-slack-$case_name" clean >/dev/null
    before=$(sha256sum "$image" | awk '{print $1}')
    report="$work/noop-$case_name.json"
    trace="$work/noop-$case_name.strace"
    active_loop=$(losetup --find --show "$image")
    slack_device=$active_loop
    set +e
    timeout 300s strace -f -yy -o "$trace" -e trace="$trace_syscalls" \
        "$repair_checker" --repair --quiet --require-t1os-root \
        "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
        --report "$report" "$active_loop" \
        >"$work/noop-$case_name.log" 2>&1
    status=$?
    set -e
    losetup --detach "$active_loop"
    active_loop=
    [ "$status" -eq 0 ] || {
        echo "Clean no-op case $case_name returned $status; expected 0." >&2
        sed -n '1,220p' "$work/noop-$case_name.log" >&2
        exit 1
    }
    [ "$before" = "$(sha256sum "$image" | awk '{print $1}')" ] || {
        echo "Clean no-op case $case_name was normalized or changed." >&2
        exit 1
    }
    python3 "$report_validator" "$report" \
        "${report_binding_args[@]}" --noop
    trace_target_io "$trace" "$slack_device" none >/dev/null
    validate_rescan_execution_trace "$trace" "$slack_device" \
        "$report" "$repair_checker" >/dev/null
    assert_deep_corruption "$image" "$case_name"
    assert_manifest_equal "$image" clean
    printf 'PASS repair-noop-%-19s exit=0 sha256=%s writes=0\n' \
        "$case_name" "$before"
}

# A clean --repair is a pure read-only diagnosis.  This catches upstream's
# unconditional lost+found creation and any other write-on-clean behaviour.
run_check "$clean_image" clean-census-hardlink-sparse clean >/dev/null
python3 "$wal_fixtures" inspect "$clean_image" \
    "$work/t1os.roothealth-journal.json" --expect healthy \
    --expected-journal-uuid "$expected_journal_uuid" \
    --expected-volume-serial "$expected_report_serial" >/dev/null
clean_before=$(sha256sum "$clean_image" | awk '{print $1}')
clean_report="$work/repair-clean.json"
clean_trace="$work/repair-clean.strace"
active_loop=$(losetup --find --show "$clean_image")
set +e
timeout 300s strace -f -yy -o "$clean_trace" \
    -e trace="$trace_syscalls" \
    "$repair_checker" --repair --quiet --require-t1os-root \
    "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
    --report "$clean_report" "$active_loop" \
    >"$work/repair-clean.log" 2>&1
clean_status=$?
set -e
clean_device=$active_loop
losetup --detach "$active_loop"
active_loop=
[ "$clean_status" -eq 0 ] || {
    echo "Clean repair returned $clean_status; expected 0." >&2
    sed -n '1,220p' "$work/repair-clean.log" >&2
    exit 1
}
clean_after=$(sha256sum "$clean_image" | awk '{print $1}')
[ "$clean_before" = "$clean_after" ] || {
    echo 'Clean --repair changed the whole-image SHA-256.' >&2
    exit 1
}
python3 "$report_validator" "$clean_report" \
    "${report_binding_args[@]}" --noop
trace_target_io "$clean_trace" "$clean_device" none >/dev/null
validate_rescan_execution_trace "$clean_trace" "$clean_device" \
    "$clean_report" "$repair_checker" >/dev/null
assert_manifest_equal "$clean_image" clean
printf 'PASS repair-%-22s exit=0 sha256=%s writes=0\n' clean "$clean_after"

# A redundant copy which cannot be read is not authority for overwriting it.
# Inject EIO independently at the primary and backup boot sectors before any
# plan exists; each case must report exit 3 with no foundation action/write.
assert_boot_read_failure() {
    case_name=$1
    offset_kind=$2
    report="$work/repair-$case_name.json"
    trace="$work/repair-$case_name.strace"
    before=$(sha256sum "$clean_image" | awk '{print $1}')
    active_loop=$(losetup --find --show "$clean_image")
    device=$active_loop
    device_size=$(blockdev --getsize64 "$active_loop")
    case "$offset_kind" in
        primary) read_offset=0 ;;
        backup) read_offset=$((device_size - 512)) ;;
        *) echo "Unknown boot read-fault location $offset_kind" >&2; exit 1 ;;
    esac
    set +e
    timeout 300s strace -f -yy -o "$trace" -e trace="$trace_syscalls" \
        env LD_PRELOAD="$fault_library" ROOTHEALTH_FAULT_MODE=read-fault \
        ROOTHEALTH_FAULT_TARGET="$active_loop" \
        ROOTHEALTH_FAULT_READ_OFFSET="$read_offset" \
        "$repair_checker" --repair --quiet --require-t1os-root \
        "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
        --report "$report" "$active_loop" \
        >"$work/repair-$case_name.log" 2>&1
    status=$?
    set -e
    losetup --detach "$active_loop"
    active_loop=
    [ "$status" -eq 3 ] || {
        echo "Boot $offset_kind read failure returned $status; expected 3." >&2
        sed -n '1,220p' "$work/repair-$case_name.log" >&2
        exit 1
    }
    [ "$before" = "$(sha256sum "$clean_image" | awk '{print $1}')" ] || {
        echo "Boot $offset_kind read failure changed the target." >&2
        exit 1
    }
    python3 "$report_validator" "$report" --early-io
    python3 -B - "$report" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding='utf-8'))
if value.get('foundation_repairs') != []:
    raise SystemExit('unreadable foundation target produced a repair record')
if value.get('plan', {}).get('operations') != 0 or value.get('commit', {}).get('started') is not False:
    raise SystemExit('unreadable foundation target entered planning/commit')
PY
    trace_target_io "$trace" "$device" none >/dev/null
    printf 'PASS repair-%-22s exit=3 sha256=%s writes=0\n' \
        "$case_name" "$before"
}

assert_boot_read_failure boot-primary-read-io primary
assert_boot_read_failure boot-backup-read-io backup

# The exact 0x40000-byte nonresident ATTRIBUTE_LIST ceiling must be streamed
# completely.  An injected EIO in its final byte is a real device failure,
# never a clean/partial census and never repair authority.
assert_large_attribute_list_clean
large_attrlist_read_offset=$(python3 -B - \
    "$work/large-attribute-list.clean.inspect.json" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding='utf-8'))['large_attribute_list']
print(value['read_fault_physical_offset'])
PY
)
case "$large_attrlist_read_offset" in
    ''|*[!0-9]*) echo 'Large ATTRIBUTE_LIST read-fault offset is invalid.' >&2; exit 1 ;;
esac
large_attrlist_io_before=$(sha256sum "$clean_image" | awk '{print $1}')
large_attrlist_io_report="$work/repair-large-attribute-list-read-io.json"
large_attrlist_io_trace="$work/repair-large-attribute-list-read-io.strace"
active_loop=$(losetup --find --show "$clean_image")
large_attrlist_io_device=$active_loop
set +e
timeout 300s strace -f -yy -o "$large_attrlist_io_trace" \
    -e trace="$trace_syscalls" \
    env LD_PRELOAD="$fault_library" ROOTHEALTH_FAULT_MODE=read-fault \
    ROOTHEALTH_FAULT_TARGET="$active_loop" \
    ROOTHEALTH_FAULT_READ_OFFSET="$large_attrlist_read_offset" \
    "$repair_checker" --repair --quiet --require-t1os-root \
    "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
    --report "$large_attrlist_io_report" "$active_loop" \
    >"$work/repair-large-attribute-list-read-io.log" 2>&1
large_attrlist_io_status=$?
set -e
losetup --detach "$active_loop"
active_loop=
[ "$large_attrlist_io_status" -eq 3 ] || {
    echo "Large ATTRIBUTE_LIST read fault returned $large_attrlist_io_status; expected 3." >&2
    sed -n '1,220p' "$work/repair-large-attribute-list-read-io.log" >&2
    exit 1
}
[ "$large_attrlist_io_before" = "$(sha256sum "$clean_image" | awk '{print $1}')" ] || {
    echo 'Large ATTRIBUTE_LIST read fault changed the target.' >&2
    exit 1
}
python3 "$report_validator" "$large_attrlist_io_report" --early-io
python3 -B - "$large_attrlist_io_report" <<'PY'
import json
import sys
report = json.load(open(sys.argv[1], encoding='utf-8'))
if report.get('foundation_repairs') != [] or report.get('repairs') != []:
    raise SystemExit('large ATTRIBUTE_LIST read uncertainty produced a repair')
plan = report.get('plan', {})
commit = report.get('commit', {})
if plan.get('operations') != 0 or commit.get('started') is not False:
    raise SystemExit('large ATTRIBUTE_LIST read uncertainty entered commit')
PY
trace_target_io "$large_attrlist_io_trace" "$large_attrlist_io_device" none >/dev/null
printf 'PASS repair-%-22s exit=3 offset=%s sha256=%s writes=0\n' \
    large-attrlist-read-io "$large_attrlist_read_offset" "$large_attrlist_io_before"

# A stable mapper-style final symlink is resolved once to the attested block
# node.  The report must retain both identities while the clean repair remains
# a zero-write no-op.
mapper_test_root="$work/dev/mapper"
mkdir -p "$mapper_test_root"
stable_mapper_path="$mapper_test_root/t1os-root-stable"
stable_before=$(sha256sum "$path_symlink_image" | awk '{print $1}')
stable_report="$work/repair-path-stable.json"
stable_trace="$work/repair-path-stable.strace"
active_loop=$(losetup --find --show "$path_symlink_image")
stable_device=$active_loop
ln -s "$active_loop" "$stable_mapper_path"
stable_resolved=$(readlink -f "$stable_mapper_path")
[ "$stable_resolved" = "$active_loop" ] || {
    echo 'Stable mapper-style test path did not resolve to its loop device.' >&2
    exit 1
}
set +e
timeout 300s strace -f -yy -o "$stable_trace" -e trace="$trace_syscalls" \
    "$repair_checker" --repair --quiet --require-t1os-root \
    "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
    --report "$stable_report" "$stable_mapper_path" \
    >"$work/repair-path-stable.log" 2>&1
stable_status=$?
set -e
rm -- "$stable_mapper_path"
losetup --detach "$active_loop"
active_loop=
[ "$stable_status" -eq 0 ] || {
    echo "Stable mapper-style repair returned $stable_status; expected 0." >&2
    sed -n '1,200p' "$work/repair-path-stable.log" >&2
    exit 1
}
[ "$stable_before" = "$(sha256sum "$path_symlink_image" | awk '{print $1}')" ] || {
    echo 'Stable mapper-style clean path changed the target.' >&2
    exit 1
}
python3 "$report_validator" "$stable_report" \
    "${report_binding_args[@]}" --noop \
    --expected-requested-path "$stable_mapper_path" \
    --expected-resolved-path "$stable_resolved" \
    --expected-requested-symlink true
trace_target_io "$stable_trace" "$stable_device" none >/dev/null
validate_rescan_execution_trace "$stable_trace" "$stable_device" \
    "$stable_report" "$repair_checker" >/dev/null
assert_manifest_equal "$path_symlink_image" path-stable
printf 'PASS repair-path-%-17s exit=0 sha256=%s writes=0\n' stable-symlink "$stable_before"

# A final-component retarget before selection must bind the newly resolved
# node and fail the expected-serial/identity barrier.  Neither the former nor
# the replacement target may become writable.  A separate synchronized
# in-flight retarget case below pins the actual resolution/open race.
retarget_mapper_path="$mapper_test_root/t1os-root-retarget"
retarget_source_before=$(sha256sum "$path_race_source_image" | awk '{print $1}')
retarget_victim_before=$(sha256sum "$path_race_victim_image" | awk '{print $1}')
retarget_report="$work/repair-path-retarget.json"
retarget_trace="$work/repair-path-retarget.strace"
active_loop=$(losetup --find --show "$path_race_source_image")
retarget_source_device=$active_loop
secondary_loop=$(losetup --find --show "$path_race_victim_image")
retarget_victim_device=$secondary_loop
ln -s "$active_loop" "$retarget_mapper_path"
rm -- "$retarget_mapper_path"
ln -s "$secondary_loop" "$retarget_mapper_path"
retarget_resolved=$(readlink -f "$retarget_mapper_path")
set +e
timeout 300s strace -f -yy -o "$retarget_trace" -e trace="$trace_syscalls" \
    "$repair_checker" --repair --quiet --require-t1os-root \
    "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
    --report "$retarget_report" "$retarget_mapper_path" \
    >"$work/repair-path-retarget.log" 2>&1
retarget_status=$?
set -e
rm -- "$retarget_mapper_path"
losetup --detach "$secondary_loop"
secondary_loop=
losetup --detach "$active_loop"
active_loop=
[ "$retarget_status" -eq 4 ] || {
    echo "Retargeted mapper-style path returned $retarget_status; expected 4." >&2
    sed -n '1,200p' "$work/repair-path-retarget.log" >&2
    exit 1
}
[ "$retarget_source_before" = "$(sha256sum "$path_race_source_image" | awk '{print $1}')" ] || {
    echo 'Retarget refusal changed the former source device.' >&2
    exit 1
}
[ "$retarget_victim_before" = "$(sha256sum "$path_race_victim_image" | awk '{print $1}')" ] || {
    echo 'Retarget refusal changed the replacement device.' >&2
    exit 1
}
python3 "$report_validator" "$retarget_report" \
    "${ordinary_report_binding_args[@]}" --rejection-exit 4 \
    --expected-requested-path "$retarget_mapper_path" \
    --expected-resolved-path "$retarget_resolved" \
    --expected-requested-symlink true
trace_target_io "$retarget_trace" "$retarget_victim_device" none >/dev/null
trace_target_io "$retarget_trace" "$retarget_source_device" none-optional-open >/dev/null
printf 'PASS repair-path-%-17s exit=4 source=%s victim=%s writes=0\n' \
    retarget-refusal "$retarget_source_before" "$retarget_victim_before"

# Retarget the final mapper-style symlink only after the checker has opened
# and attested the original block node.  Foundation repair is deliberately
# closed in the v0.3 orchestrator, so use a clean source here: the race still
# proves that every later read and the self-rescan stay bound to the selected
# node, while both backing images must remain byte-for-byte unchanged.
live_race_mapper_path="$mapper_test_root/t1os-root-live-race"
live_race_source_before=$(sha256sum "$path_race_source_image" | awk '{print $1}')
live_race_victim_before=$(sha256sum "$path_race_victim_image" | awk '{print $1}')
live_race_report="$work/repair-path-live-race.json"
active_loop=$(losetup --find --show "$path_race_source_image")
live_race_source_device=$active_loop
secondary_loop=$(losetup --find --show "$path_race_victim_image")
live_race_victim_device=$secondary_loop
ln -s "$live_race_source_device" "$live_race_mapper_path"
set +e
timeout 300s "$repair_checker" --repair --quiet --require-t1os-root \
    "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
    --report "$live_race_report" "$live_race_mapper_path" \
    >"$work/repair-path-live-race.log" 2>&1 &
live_race_runner=$!
set -e
live_race_opened=0
for _ in $(seq 1 10000); do
    candidates="$live_race_runner"
    children_file="/proc/$live_race_runner/task/$live_race_runner/children"
    if [ -r "$children_file" ]; then
        candidates="$candidates $(<"$children_file")"
    fi
    for candidate in $candidates; do
        [ -d "/proc/$candidate/fd" ] || continue
        for fd in /proc/"$candidate"/fd/*; do
            [ -e "$fd" ] || continue
            if [ "$(readlink "$fd" 2>/dev/null || true)" = "$live_race_source_device" ]; then
                live_race_opened=1
                break 3
            fi
        done
    done
    kill -0 "$live_race_runner" 2>/dev/null || break
    sleep 0.001
done
[ "$live_race_opened" -eq 1 ] || {
    set +e
    wait "$live_race_runner"
    live_race_early_status=$?
    set -e
    echo "Could not synchronize live path retarget (checker exit $live_race_early_status)." >&2
    exit 1
}
live_race_replacement="$mapper_test_root/.t1os-root-live-race-replacement"
ln -s "$live_race_victim_device" "$live_race_replacement"
mv -Tf -- "$live_race_replacement" "$live_race_mapper_path"
set +e
wait "$live_race_runner"
live_race_status=$?
set -e
live_race_resolved=$live_race_source_device
rm -- "$live_race_mapper_path"
losetup --detach "$secondary_loop"
secondary_loop=
losetup --detach "$active_loop"
active_loop=
[ "$live_race_status" -eq 0 ] || {
    echo "Live retarget repair returned $live_race_status; expected 0." >&2
    sed -n '1,220p' "$work/repair-path-live-race.log" >&2
    exit 1
}
[ "$live_race_source_before" = "$(sha256sum "$path_race_source_image" | awk '{print $1}')" ] || {
    echo 'Live retarget check changed the originally selected source node.' >&2
    exit 1
}
[ "$live_race_victim_before" = "$(sha256sum "$path_race_victim_image" | awk '{print $1}')" ] || {
    echo 'Live retarget changed the replacement/victim node.' >&2
    exit 1
}
python3 "$report_validator" "$live_race_report" \
    "${report_binding_args[@]}" --noop \
    --expected-requested-path "$live_race_mapper_path" \
    --expected-resolved-path "$live_race_resolved" \
    --expected-requested-symlink true
run_check "$path_race_source_image" path-live-race-final clean >/dev/null
assert_manifest_equal "$path_race_source_image" path-live-race
printf 'PASS repair-path-%-17s exit=0 source=%s victim=%s\n' \
    live-retarget "$live_race_source_device" "$live_race_victim_device"

assert_report_refusal() {
    case_name=$1
    mode=$2
    report_path=
    victim=
    sentinel='roothealth must not overwrite this report path'
    case "$mode" in
        existing)
            report_path="$work/report-existing.json"
            printf '%s\n' "$sentinel" >"$report_path"
            before_path_state=$(stat -c '%i:%a:%s:%Y' "$report_path")
            ;;
        symlink)
            victim="$work/report-symlink-victim"
            report_path="$work/report-symlink.json"
            printf '%s\n' "$sentinel" >"$victim"
            ln -s "$victim" "$report_path"
            before_path_state=$(stat -Lc '%i:%a:%s:%Y' "$victim")
            ;;
        special)
            report_path=/dev/full
            ;;
        target) ;;
        *) echo "Unknown report-refusal mode $mode" >&2; exit 1 ;;
    esac
    before=$(sha256sum "$clean_image" | awk '{print $1}')
    trace="$work/report-refusal-$case_name.strace"
    active_loop=$(losetup --find --show "$clean_image")
    device=$active_loop
    [ "$mode" != target ] || report_path=$active_loop
    set +e
    timeout 300s strace -f -yy -o "$trace" \
        -e trace="$trace_syscalls" \
        "$repair_checker" --repair --quiet --require-t1os-root \
        "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
        --report "$report_path" "$active_loop" \
        >"$work/report-refusal-$case_name.log" 2>&1
    status=$?
    set -e
    losetup --detach "$active_loop"
    active_loop=
    [ "$status" -eq 5 ] || {
        echo "Report refusal $case_name returned $status; expected 5." >&2
        sed -n '1,180p' "$work/report-refusal-$case_name.log" >&2
        exit 1
    }
    [ "$before" = "$(sha256sum "$clean_image" | awk '{print $1}')" ] || {
        echo "Report refusal $case_name changed the target." >&2
        exit 1
    }
    trace_target_io "$trace" "$device" none-optional-open >/dev/null
    case "$mode" in
        existing)
            if [ "$(<"$report_path")" != "$sentinel" ] || \
                    [ "$(stat -c '%i:%a:%s:%Y' "$report_path")" != "$before_path_state" ]; then
                echo 'Existing report path was changed.' >&2
                exit 1
            fi
            ;;
        symlink)
            if [ ! -L "$report_path" ] || \
                    [ "$(readlink "$report_path")" != "$victim" ] || \
                    [ "$(<"$victim")" != "$sentinel" ] || \
                    [ "$(stat -Lc '%i:%a:%s:%Y' "$victim")" != "$before_path_state" ]; then
                echo 'Report symlink or its victim was changed.' >&2
                exit 1
            fi
            ;;
    esac
    printf 'PASS repair-report-%-15s exit=5 sha256=%s writes=0\n' "$case_name" "$before"
}

assert_report_refusal existing existing
assert_report_refusal symlink symlink
assert_report_refusal special-device special
assert_report_refusal target-alias target

# O_EXCL creation can succeed and serialization can still fail.  Constrain the
# checker child to a zero-byte regular-file limit while ignoring SIGXFSZ; the
# checker must return 5, unlink only its new incomplete report, and never write
# the clean target.
flush_report="$work/report-flush-failure.json"
flush_trace="$work/report-flush-failure.strace"
flush_before=$(sha256sum "$clean_image" | awk '{print $1}')
active_loop=$(losetup --find --show "$clean_image")
flush_device=$active_loop
set +e
timeout 300s strace -f -yy -o "$flush_trace" \
    -e trace="$trace_syscalls" \
    bash -c 'trap "" XFSZ; ulimit -f 0; exec "$@" >/dev/null 2>&1' bash \
    "$repair_checker" --repair --quiet --require-t1os-root \
    "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
    --report "$flush_report" "$active_loop"
flush_status=$?
set -e
losetup --detach "$active_loop"
active_loop=
[ "$flush_status" -eq 5 ] || {
    echo "Post-create report write failure returned $flush_status; expected 5." >&2
    exit 1
}
if [ -e "$flush_report" ] || [ -L "$flush_report" ]; then
    echo 'Post-create report write failure left an incomplete report.' >&2
    exit 1
fi
[ "$flush_before" = "$(sha256sum "$clean_image" | awk '{print $1}')" ] || {
    echo 'Post-create report write failure changed the target.' >&2
    exit 1
}
trace_target_io "$flush_trace" "$flush_device" none-optional-open >/dev/null
printf 'PASS repair-report-%-15s exit=5 sha256=%s writes=0\n' flush-failure "$flush_before"

assert_identity_refusal() {
    case_name=$1
    wal_expectation=$2
    shift 2
    identity_args=("$@")
    before=$(sha256sum "$clean_image" | awk '{print $1}')
    report="$work/identity-$case_name.json"
    trace="$work/identity-$case_name.strace"
    active_loop=$(losetup --find --show "$clean_image")
    device=$active_loop
    set +e
    timeout 300s strace -f -yy -o "$trace" -e trace="$trace_syscalls" \
        "$repair_checker" --repair --quiet --require-t1os-root \
        "${identity_args[@]}" "${repair_scope_args[@]}" \
        --report "$report" "$active_loop" \
        >"$work/identity-$case_name.log" 2>&1
    status=$?
    set -e
    losetup --detach "$active_loop"
    active_loop=
    [ "$status" -eq 2 ] || {
        echo "Identity refusal $case_name returned $status; expected 2." >&2
        sed -n '1,200p' "$work/identity-$case_name.log" >&2
        exit 1
    }
    [ "$before" = "$(sha256sum "$clean_image" | awk '{print $1}')" ] || {
        echo "Identity refusal $case_name changed the target." >&2
        exit 1
    }
    python3 "$report_validator" "$report" \
        "${report_binding_args[@]}" \
        --rejection-exit 2 --rejection-wal "$wal_expectation"
    trace_target_io "$trace" "$device" none >/dev/null
    printf 'PASS repair-identity-%-13s exit=2 sha256=%s writes=0\n' "$case_name" "$before"
}

wrong_journal_uuid=00000000-0000-0000-0000-000000000001
[ "$wrong_journal_uuid" != "$expected_journal_uuid" ] || \
    wrong_journal_uuid=ffffffff-ffff-ffff-ffff-ffffffffffff
wrong_journal_record=$((expected_journal_record + 1))
wrong_journal_sequence=$((expected_journal_sequence == 65535 ? 1 : expected_journal_sequence + 1))
assert_identity_refusal wrong-uuid untrusted-empty \
    --expected-serial "$expected_serial" \
    --expected-journal-uuid "$wrong_journal_uuid" \
    --expected-journal-record "$expected_journal_record:$expected_journal_sequence"
assert_identity_refusal wrong-record unchecked \
    --expected-serial "$expected_serial" \
    --expected-journal-uuid "$expected_journal_uuid" \
    --expected-journal-record "$wrong_journal_record:$expected_journal_sequence"
assert_identity_refusal wrong-sequence unchecked \
    --expected-serial "$expected_serial" \
    --expected-journal-uuid "$expected_journal_uuid" \
    --expected-journal-record "$expected_journal_record:$wrong_journal_sequence"

missing_uuid_report="$work/identity-missing-uuid.json"
missing_uuid_trace="$work/identity-missing-uuid.strace"
missing_uuid_before=$(sha256sum "$clean_image" | awk '{print $1}')
active_loop=$(losetup --find --show "$clean_image")
missing_uuid_device=$active_loop
set +e
timeout 300s strace -f -yy -o "$missing_uuid_trace" -e trace="$trace_syscalls" \
    "$repair_checker" --repair --quiet --require-t1os-root \
    --expected-serial "$expected_serial" \
    --expected-journal-record "$expected_journal_record:$expected_journal_sequence" \
    "${repair_scope_args[@]}" --report "$missing_uuid_report" "$active_loop" \
    >"$work/identity-missing-uuid.log" 2>&1
missing_uuid_status=$?
set -e
losetup --detach "$active_loop"
active_loop=
[ "$missing_uuid_status" -eq 5 ] || {
    echo "Missing expected journal UUID returned $missing_uuid_status; expected 5." >&2
    sed -n '1,160p' "$work/identity-missing-uuid.log" >&2
    exit 1
}
if [ -e "$missing_uuid_report" ] || [ -L "$missing_uuid_report" ]; then
    echo 'Usage failure for missing journal UUID published a report.' >&2
    exit 1
fi
[ "$missing_uuid_before" = "$(sha256sum "$clean_image" | awk '{print $1}')" ] || {
    echo 'Missing journal UUID usage failure changed the target.' >&2
    exit 1
}
trace_target_io "$missing_uuid_trace" "$missing_uuid_device" none-optional-open >/dev/null
printf 'PASS repair-identity-%-13s exit=5 sha256=%s writes=0\n' missing-uuid "$missing_uuid_before"

# A single valid superblock remains authoritative but degraded.  Repair must
# reconstruct only its redundant peer, attest that write independently, and
# finish with two identical valid EMPTY headers and a fresh clean rescan.
python3 "$wal_fixtures" inspect "$wal_one_torn_image" \
    "$work/t1os.roothealth-journal.json" --expect degraded \
    --expected-journal-uuid "$expected_journal_uuid" \
    --expected-volume-serial "$expected_report_serial" >/dev/null
run_check "$wal_one_torn_image" initial-wal-one-torn wal-degraded >/dev/null
wal_one_torn_before=$(sha256sum "$wal_one_torn_image" | awk '{print $1}')
wal_one_torn_report="$work/repair-wal-one-torn.json"
wal_one_torn_trace="$work/repair-wal-one-torn.strace"
active_loop=$(losetup --find --show "$wal_one_torn_image")
wal_one_torn_device=$active_loop
set +e
timeout 300s strace -f -yy -o "$wal_one_torn_trace" -e trace="$trace_syscalls" \
    "$repair_checker" --repair --quiet --require-t1os-root \
    "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
    --report "$wal_one_torn_report" "$active_loop" \
    >"$work/repair-wal-one-torn.log" 2>&1
wal_one_torn_status=$?
set -e
losetup --detach "$active_loop"
active_loop=
[ "$wal_one_torn_status" -eq 0 ] || {
    echo "One-torn WAL repair returned $wal_one_torn_status; expected 0." >&2
    sed -n '1,220p' "$work/repair-wal-one-torn.log" >&2
    exit 1
}
[ "$wal_one_torn_before" != "$(sha256sum "$wal_one_torn_image" | awk '{print $1}')" ] || {
    echo 'One-torn WAL reconstruction did not change the damaged header.' >&2
    exit 1
}
python3 "$report_validator" "$wal_one_torn_report" \
    "${report_binding_args[@]}"
trace_target_io "$wal_one_torn_trace" "$wal_one_torn_device" repair >/dev/null
validate_rescan_execution_trace "$wal_one_torn_trace" "$wal_one_torn_device" \
    "$wal_one_torn_report" "$repair_checker" >/dev/null
python3 "$wal_fixtures" inspect "$wal_one_torn_image" \
    "$work/t1os.roothealth-journal.json" --expect healthy \
    --expected-journal-uuid "$expected_journal_uuid" \
    --expected-volume-serial "$expected_report_serial" >/dev/null
run_check "$wal_one_torn_image" wal-one-torn-final clean >/dev/null
assert_manifest_equal "$wal_one_torn_image" wal-one-torn
printf 'PASS repair-%-22s exit=0 action=superblock-reconstruct\n' wal-one-torn-reconstruct

# A serial-matching T1OS target with malformed internal WAL metadata must fail
# closed before enabling any writable target handle.
python3 "$wal_fixtures" inspect "$wal_invalid_image" \
    "$work/t1os.roothealth-journal.json" --expect invalid >/dev/null
run_check "$wal_invalid_image" initial-wal-invalid wal-invalid >/dev/null
wal_invalid_before=$(sha256sum "$wal_invalid_image" | awk '{print $1}')
wal_invalid_report="$work/repair-wal-invalid.json"
wal_invalid_trace="$work/repair-wal-invalid.strace"
active_loop=$(losetup --find --show "$wal_invalid_image")
wal_invalid_device=$active_loop
set +e
timeout 300s strace -f -yy -o "$wal_invalid_trace" \
    -e trace="$trace_syscalls" \
    "$repair_checker" --repair --quiet --require-t1os-root \
    "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
    --report "$wal_invalid_report" "$active_loop" \
    >"$work/repair-wal-invalid.log" 2>&1
wal_invalid_status=$?
set -e
losetup --detach "$active_loop"
active_loop=
[ "$wal_invalid_status" -eq 2 ] || {
    echo "Malformed WAL repair returned $wal_invalid_status; expected 2." >&2
    sed -n '1,200p' "$work/repair-wal-invalid.log" >&2
    exit 1
}
[ "$wal_invalid_before" = "$(sha256sum "$wal_invalid_image" | awk '{print $1}')" ] || {
    echo 'Malformed WAL repair changed the target.' >&2
    exit 1
}
python3 "$report_validator" "$wal_invalid_report" \
    --rejection-exit 2 --rejection-wal invalid
trace_target_io "$wal_invalid_trace" "$wal_invalid_device" none >/dev/null
printf 'PASS repair-%-22s exit=2 sha256=%s writes=0\n' wal-invalid "$wal_invalid_before"

# Two individually valid headers with an equal generation but differing bytes
# have no unique authority and must not be repaired or selected by UUID bias.
python3 "$wal_fixtures" inspect "$wal_ambiguous_image" \
    "$work/t1os.roothealth-journal.json" --expect ambiguous >/dev/null
run_check "$wal_ambiguous_image" initial-wal-ambiguous wal-invalid >/dev/null
wal_ambiguous_before=$(sha256sum "$wal_ambiguous_image" | awk '{print $1}')
wal_ambiguous_report="$work/repair-wal-ambiguous.json"
wal_ambiguous_trace="$work/repair-wal-ambiguous.strace"
active_loop=$(losetup --find --show "$wal_ambiguous_image")
wal_ambiguous_device=$active_loop
set +e
timeout 300s strace -f -yy -o "$wal_ambiguous_trace" -e trace="$trace_syscalls" \
    "$repair_checker" --repair --quiet --require-t1os-root \
    "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
    --report "$wal_ambiguous_report" "$active_loop" \
    >"$work/repair-wal-ambiguous.log" 2>&1
wal_ambiguous_status=$?
set -e
losetup --detach "$active_loop"
active_loop=
[ "$wal_ambiguous_status" -eq 2 ] || {
    echo "Ambiguous WAL repair returned $wal_ambiguous_status; expected 2." >&2
    sed -n '1,200p' "$work/repair-wal-ambiguous.log" >&2
    exit 1
}
[ "$wal_ambiguous_before" = "$(sha256sum "$wal_ambiguous_image" | awk '{print $1}')" ] || {
    echo 'Ambiguous WAL repair changed the target.' >&2
    exit 1
}
python3 "$report_validator" "$wal_ambiguous_report" \
    --rejection-exit 2 --rejection-wal invalid
trace_target_io "$wal_ambiguous_trace" "$wal_ambiguous_device" none >/dev/null
printf 'PASS repair-%-22s exit=2 sha256=%s writes=0\n' wal-ambiguous "$wal_ambiguous_before"

# Geometry that claims sectors beyond the block device is structurally invalid,
# not an observed read error.  It must fail unsafe before WAL discovery and
# without inventing identity or mutation evidence.
io_before=$(sha256sum "$io_image" | awk '{print $1}')
io_report="$work/repair-io-truncated.json"
io_trace="$work/repair-io-truncated.strace"
active_loop=$(losetup --find --show "$io_image")
io_device=$active_loop
set +e
timeout 300s strace -f -yy -o "$io_trace" \
    -e trace="$trace_syscalls" \
    "$repair_checker" --repair --quiet --require-t1os-root \
    "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
    --report "$io_report" "$active_loop" \
    >"$work/repair-io-truncated.log" 2>&1
io_status=$?
set -e
losetup --detach "$active_loop"
active_loop=
[ "$io_status" -eq 2 ] || {
    echo "Truncated-target repair returned $io_status; expected 2." >&2
    sed -n '1,200p' "$work/repair-io-truncated.log" >&2
    exit 1
}
[ "$io_before" = "$(sha256sum "$io_image" | awk '{print $1}')" ] || {
    echo 'Truncated-target I/O failure changed the target.' >&2
    exit 1
}
python3 "$report_validator" "$io_report" --rejection-exit 2 --rejection-wal unchecked
trace_target_io "$io_trace" "$io_device" none >/dev/null
printf 'PASS repair-%-22s exit=2 sha256=%s writes=0\n' geometry-truncated "$io_before"

# Pre-write identity is a mandatory mutation barrier, even if ordinary NTFS is
# dirty.  It must return 4 without opening the target writable.
ordinary_before=$(sha256sum "$ordinary_image" | awk '{print $1}')
ordinary_report="$work/repair-ordinary.json"
ordinary_trace="$work/repair-ordinary.strace"
active_loop=$(losetup --find --show "$ordinary_image")
set +e
timeout 300s strace -f -yy -o "$ordinary_trace" \
    -e trace="$trace_syscalls" \
    "$repair_checker" --repair --quiet --require-t1os-root \
    "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
    --report "$ordinary_report" "$active_loop" \
    >"$work/repair-ordinary.log" 2>&1
ordinary_status=$?
set -e
ordinary_device=$active_loop
losetup --detach "$active_loop"
active_loop=
[ "$ordinary_status" -eq 4 ] || {
    echo "Dirty ordinary NTFS repair returned $ordinary_status; expected 4." >&2
    sed -n '1,220p' "$work/repair-ordinary.log" >&2
    exit 1
}
[ "$ordinary_before" = "$(sha256sum "$ordinary_image" | awk '{print $1}')" ] || {
    echo 'Rejected ordinary NTFS was changed.' >&2
    exit 1
}
python3 "$report_validator" "$ordinary_report" \
    "${ordinary_report_binding_args[@]}" --rejection-exit 4
trace_target_io "$ordinary_trace" "$ordinary_device" none >/dev/null
printf 'PASS repair-%-22s exit=4 sha256=%s writes=0\n' wrong-root "$ordinary_before"

# A genuinely absent required MFT/FILE_NAME anchor is not index corruption and
# must remain a zero-write wrong-root verdict.
run_check "$identity_missing_image" initial-identity-missing wrong-root >/dev/null
identity_missing_before=$(sha256sum "$identity_missing_image" | awk '{print $1}')
identity_missing_report="$work/repair-identity-missing.json"
identity_missing_trace="$work/repair-identity-missing.strace"
active_loop=$(losetup --find --show "$identity_missing_image")
identity_missing_device=$active_loop
set +e
timeout 300s strace -f -yy -o "$identity_missing_trace" -e trace="$trace_syscalls" \
    "$repair_checker" --repair --quiet --require-t1os-root \
    "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
    --report "$identity_missing_report" "$active_loop" \
    >"$work/repair-identity-missing.log" 2>&1
identity_missing_status=$?
set -e
losetup --detach "$active_loop"
active_loop=
[ "$identity_missing_status" -eq 4 ] || {
    echo "Missing identity anchor repair returned $identity_missing_status; expected 4." >&2
    sed -n '1,200p' "$work/repair-identity-missing.log" >&2
    exit 1
}
[ "$identity_missing_before" = "$(sha256sum "$identity_missing_image" | awk '{print $1}')" ] || {
    echo 'Missing identity anchor repair changed the target.' >&2
    exit 1
}
python3 "$report_validator" "$identity_missing_report" \
    "${report_binding_args[@]}" --rejection-exit 4 --rejection-wal empty
trace_target_io "$identity_missing_trace" "$identity_missing_device" none >/dev/null
printf 'PASS repair-%-22s exit=4 sha256=%s writes=0\n' identity-missing "$identity_missing_before"

# Journal allocation false-clears are repairable only after the raw fixture
# proves one exact owner through a complete readable MFT census.  An otherwise
# identical duplicate-owner image must fail before any WAL or target write.
assert_deep_corruption "$journal_mft_false_free_image" \
    journal-mft-false-free
repair_case journal-mft-false-free "$journal_mft_false_free_image" equal \
    volume-dirty-set bitmap-mft volume-dirty-clear
assert_deep_corruption "$journal_cluster_false_free_image" \
    journal-cluster-false-free
repair_case journal-cluster-false-free "$journal_cluster_false_free_image" equal \
    volume-dirty-set bitmap-cluster volume-dirty-clear
refusal_case journal-duplicate-owner "$journal_duplicate_owner_image" \
    WAL_OWNERSHIP_DUPLICATE io
refusal_case journal-mft-false-free-duplicate "$journal_mft_duplicate_image" \
    WAL_MFT_FALSE_FREE_WITH_DUPLICATE_OWNER io
refusal_case journal-cluster-false-free-duplicate \
    "$journal_cluster_duplicate_image" \
    WAL_CLUSTER_FALSE_FREE_WITH_DUPLICATE_OWNER io
refusal_case journal-duplicate-owner-one-torn \
    "$journal_duplicate_torn_image" WAL_OWNERSHIP_BLOCKS_SUPERBLOCK_RECONSTRUCTION \
    io empty
refusal_case journal-duplicate-owner-preparing \
    "$journal_duplicate_preparing_image" WAL_OWNERSHIP_BLOCKS_RECOVERY \
    io interrupted

# Exercise every newly authorized v0.4.0 metadata surface before the broad
# negative corpus so qualification failures retain a short diagnostic path.
repair_case bitmaps "$bitmap_image" equal volume-dirty-set bitmap-mft \
    bitmap-cluster volume-dirty-clear
repair_case index-bitmap-set "$index_bitmap_set_image" equal \
    volume-dirty-set index-bitmap volume-dirty-clear
repair_case operations-registry-stale "$operations_stale_image" \
	operations-stale volume-dirty-set index-root volume-dirty-clear
repair_case operations-registry-stale-bitmaps \
	"$operations_stale_bitmaps_image" operations-stale volume-dirty-set \
	index-root bitmap-mft bitmap-cluster volume-dirty-clear
refusal_case operations-registry-wrong-path \
    "$operations_stale_wrong_path_image" NAMESPACE_PATH_NOT_AUTHORIZED \
    unsafe-or-io auto skip
refusal_case operations-registry-ambiguous \
    "$operations_stale_ambiguous_image" NAMESPACE_REPAIR_AMBIGUOUS \
    unsafe-or-io auto skip

# These deterministic raw oracles exercise the next approved safe-repair
# surface.  Until a policy-specific validator and typed WAL action exists for
# each family, the only acceptable behavior is an explicit unsafe/no-write
# refusal; generic ntfs-next AUTO approval is never accepted.
assert_attribute_list_hardlink_clean
refusal_case attribute-list "$attribute_list_image" PR_ATTRLIST_REBUILD
refusal_case attribute-list-equal-triple-order \
    "$attribute_list_equal_triple_order_image" \
    ATTRIBUTE_LIST_EQUAL_TRIPLE_PROFILE_UNSUPPORTED
clean_noop_case posix-collision-clean "$posix_collision_clean_image"
clean_noop_case posix-collision-mixed-namespace \
    "$work/posix-collision-mixed-namespace.ntfs"
refusal_case large-attribute-list-boundary \
    "$large_attribute_list_boundary_image" \
    ATTRIBUTE_LIST_BOUNDARY_REFERENCE_MISMATCH
refusal_case large-attribute-list-boundary-overrun \
    "$large_attribute_list_boundary_overrun_image" \
    ATTRIBUTE_LIST_ENTRY_EXCEEDS_STREAM
refusal_case large-attribute-list-truncated \
    "$large_attribute_list_truncated_image" \
    ATTRIBUTE_LIST_STREAM_TRUNCATED
refusal_case large-attribute-list-over-limit \
    "$large_attribute_list_over_limit_image" \
    ATTRIBUTE_LIST_EXCEEDS_0X40000
refusal_case runlist-size "$runlist_size_image" PR_ATTR_INITIALIZED_SIZE_MISMATCH
refusal_case reparse-index "$reparse_index_image" PR_IE_RESERVED_NOT_ZERO/INDEX_RESERVED
refusal_case secure-derived "$secure_derived_image" PR_SECURE_SDS_MIRROR_MISMATCH/PR_SECURE_SDH_MISMATCH/INDEX_RESERVED
refusal_case secure-sii-stale "$secure_sii_stale_image" PR_SECURE_SII_MISMATCH/INDEX_CORRUPT_ENTRIES
refusal_case upcase-attrdef "$upcase_attrdef_image" PR_UPCASE_CORRUPTED/PR_ATTRDEF_CORRUPTED
refusal_case upcase-nonascii "$upcase_nonascii_image" PR_UPCASE_CORRUPTED
refusal_case user-defined-runlist "$user_defined_runlist_image" PR_NAMESPACE_WALK_INCOMPLETE
refusal_case unflagged-sparse-run "$unflagged_sparse_image" \
    UNFLAGGED_SPARSE_RUN/CLUSTER_BITMAP_CENSUS_INCOMPLETE
python3 -B - "$work/refusal-unflagged-sparse-run.json" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1], encoding='utf-8'))
if report.get('repairs') != [] or report.get('foundation_repairs') != []:
    raise SystemExit('unflagged sparse coverage hole authorized a repair')
plan = report.get('plan', {})
if plan.get('operations') != 0 or plan.get('by_action_id') != {}:
    raise SystemExit('unflagged sparse coverage hole authorized a bitmap plan')
PY
clean_noop_case mapping-pair-tail "$mapping_pair_tail_image"
clean_noop_case attribute-end-tail "$attribute_end_tail_image"
refusal_case link-reciprocity "$link_reciprocity_image" PR_MFT_LINK_COUNT_MISMATCH/PR_FN_PARENT_SEQNO_ZERO
refusal_case hardlink-value-order "$hardlink_value_order_image" \
    CANONICAL_ATTRIBUTE_ORDER
for name in "${file_name_cached_cases[@]}"; do
    clean_noop_case "$name" "$work/$name.ntfs"
done
for name in "${file_name_stable_cases[@]}"; do
    refusal_case "$name" "$work/$name.ntfs" \
        FILE_NAME_I30_STABLE_RECIPROCITY_MISMATCH
done
for name in "${posix_collision_negative_cases[@]}"; do
    refusal_case "$name" "$work/$name.ntfs" \
        POSIX_NAMESPACE_COLLISION_AMBIGUITY
done
refusal_case sparse-unit-header "$sparse_unit_header_image" \
    PR_ATTR_COMPRESSION_UNIT_CORRUPTED
for layout_case in "${layout_candidate_cases[@]}"; do
    [[ "$layout_case" == layout-next-instance-* ]] && continue
    refusal_case "$layout_case" "$work/$layout_case.ntfs" \
        RH_RAW_MFT_LAYOUT_CANDIDATE/ID7_APPLY_UNAVAILABLE
done
refusal_case layout-next-instance-candidate \
    "$work/layout-next-instance-candidate.ntfs" \
    RH_RAW_MFT_LAYOUT_CANDIDATE/ID7_RECOVERY_UNREGISTERED
refusal_case layout-next-instance-wrap-candidate \
    "$work/layout-next-instance-wrap-candidate.ntfs" \
    RH_RAW_MFT_LAYOUT_CANDIDATE/ID7_RECOVERY_UNREGISTERED
refusal_case duplicate-cluster "$duplicate_cluster_image" PR_CLUSTER_DUPLICATION_FOUND/DUPLICATE_CLUSTER_RUNLIST
refusal_case compressed-metadata "$compressed_metadata_image" PR_ATTR_COMPRESSION_UNIT_CORRUPTED/PR_ATTR_COMPRESSED_SIZE_MISMATCH
refusal_case compressed-payload "$compressed_payload_image" \
    PR_COMPRESSED_UNIT_CORRUPTED

assert_deep_corruption "$dirty_only_image" dirty-only
repair_case dirty-only "$dirty_only_image" equal volume-dirty-clear
python3 - "$work/repair-dirty-only.json" <<'PY'
import json
import sys
report = json.load(open(sys.argv[1], encoding='utf-8'))
if report.get('plan', {}).get('by_action_id') != {'25': 2}:
    raise SystemExit('dirty-only repair is not exactly the paired ID25 clear')
transactions = report.get('batch_samples')
if not isinstance(transactions, list) or len(transactions) != 1:
    raise SystemExit('dirty-only repair has an unexpected transaction count')
transaction = transactions[0]
if transaction.get('phase') != 'DIRTY_CLEAR' or transaction.get('by_action_id') != {'25': 2}:
    raise SystemExit('dirty-only transaction is not the paired DIRTY_CLEAR')
if any(action in report.get('plan', {}).get('by_action_id', {}) for action in ('5', '6')):
    raise SystemExit('wiped-log dirty-only repair incorrectly planned logfile actions')
native_log = report.get('native_log')
if not isinstance(native_log, dict):
    raise SystemExit('wiped-log dirty-only report lacks native_log evidence')
zero_fields = (
    'checkpoint_records_examined', 'control_records_examined',
    'mutation_records_examined', 'open_attribute_tables',
    'attribute_name_tables', 'dirty_page_tables', 'transaction_tables',
    'actions_seen', 'redo_actions', 'undo_actions', 'restart_pages_planned',
    'unsupported_actions', 'io_errors', 'parse_errors',
    'planned_io_operations', 'planned_io_bytes',
)
if (
    native_log.get('checked') is not True
    or native_log.get('state') != 'EMPTY_T1OS'
    or native_log.get('version_major') is not None
    or native_log.get('version_minor') is not None
    or any(native_log.get(field) is not None for field in (
        'restart_lsn', 'synced_lsn', 'committed_lsn', 'latest_lsn'
    ))
    or not isinstance(native_log.get('pages_expected'), int)
    or native_log.get('pages_examined') != native_log.get('pages_expected')
    or native_log.get('wiped_pages_scanned') != native_log.get('pages_expected')
    or any(native_log.get(field) != 0 for field in zero_fields)
):
    raise SystemExit('wiped-log dirty-only EMPTY_T1OS evidence differs')
PY

native_repair_case

refusal_case dirty-log "$dirty_image" NATIVE_LOG_UNSAFE
python3 -B - "$work/refusal-dirty-log.json" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1], encoding='utf-8'))
native_log = report.get('native_log')
if (
    not isinstance(native_log, dict)
    or native_log.get('checked') is not True
    or native_log.get('state') != 'UNSAFE'
    or native_log.get('actions_seen') != 0
    or native_log.get('redo_actions') != 0
    or native_log.get('undo_actions') != 0
    or native_log.get('restart_pages_planned') != 0
    or native_log.get('planned_io_operations') != 0
    or native_log.get('planned_io_bytes') != 0
    or native_log.get('io_errors') != 0
    or (
        native_log.get('parse_errors', 0)
        + native_log.get('unsupported_actions', 0)
    ) <= 0
):
    raise SystemExit('zero-LSN dirty native log did not fail closed exactly')
if report.get('plan', {}).get('operations') != 0:
    raise SystemExit('zero-LSN dirty native log retained a repair plan')
PY
refusal_case boot-primary "$boot_primary_image" FOUNDATION_COMMIT_DISABLED \
    unsafe-or-io auto skip
refusal_case boot-backup "$boot_backup_image" FOUNDATION_COMMIT_DISABLED \
    unsafe-or-io auto skip
refusal_case mft-primary "$mft_primary_image" FOUNDATION_COMMIT_DISABLED \
    unsafe-or-io auto skip
refusal_case mft-mirror "$mft_mirror_image" FOUNDATION_COMMIT_DISABLED \
    unsafe-or-io auto skip
refusal_case index-i30 "$index_image" PR_IDX_BITMAP_MISMATCH \
    unsafe-or-io auto skip
refusal_case identity-parent-index "$identity_parent_image" \
    INDEX_RECOVERY_UNREGISTERED unsafe-or-io auto skip
refusal_case identity-root-index "$identity_root_image" \
    INDEX_RECOVERY_UNREGISTERED unsafe-or-io auto skip
refusal_case orphan-parent "$orphan_parent_image" \
    NAMESPACE_RECOVERY_UNREGISTERED unsafe-or-io auto skip
refusal_case orphan-recovery "$orphan_recovery_image" \
    NAMESPACE_RECOVERY_UNREGISTERED unsafe-or-io auto skip

validate_capture_trace() {
    event_log=$1
    trace=$2
    device=$3
    python3 - "$event_log" "$trace" "$device" <<'PY'
from pathlib import Path
import re
import sys

events = [line.split('\t') for line in Path(sys.argv[1]).read_text().splitlines()]
device = sys.argv[3]
expected = []
for row in events[1:]:
    if row[0] == 'W':
        operation = 'pwrite64' if row[4] in ('pwrite', 'pwrite64') else row[4]
        expected.append((operation, int(row[7])))
    elif row[0] == 'S':
        expected.append((row[4], int(row[5])))
    elif row[0] == 'C':
        # The selected libc barrier is killed before issuing the kernel call.
        continue
    else:
        raise SystemExit(f'unknown observer event {row!r}')

observed = []
for line in Path(sys.argv[2]).read_text(encoding='utf-8', errors='replace').splitlines():
    if f'<{device}>' not in line and f'<{device}<' not in line:
        continue
    match = re.search(
        r'\b(write|writev|pwrite64|pwritev|pwritev2|fsync|fdatasync)\(.*\)\s+=\s+(-?[0-9]+)',
        line,
    )
    if match:
        observed.append((match.group(1), int(match.group(2))))
if observed != expected:
    raise SystemExit(
        'observer/strace target call sequence differs:\n'
        f'expected={expected!r}\nobserved={observed!r}'
    )
print(len([event for event in expected if event[0] not in ('fsync', 'fdatasync')]))
PY
}

first_target_write() {
    event_log=$1
    journal_layout=${2:-$work/t1os.roothealth-journal.json}
    python3 - "$event_log" "$journal_layout" <<'PY'
import json
from pathlib import Path
import sys

rows = [line.split('\t') for line in Path(sys.argv[1]).read_text().splitlines()[1:]]
layout = json.load(open(sys.argv[2], encoding='utf-8'))
ranges = []
for run in layout['journal']['runs']:
    start = run['lcn'] * layout['device']['cluster_size']
    clusters = run.get('clusters', run.get('length'))
    if not isinstance(clusters, int) or clusters <= 0:
        raise SystemExit(f'invalid journal run length: {run!r}')
    ranges.append((start, start + clusters * layout['device']['cluster_size']))
for row in rows:
    if row[0] != 'W' or int(row[7]) <= 0:
        continue
    write_id = int(row[2])
    epoch = int(row[3])
    offset = int(row[5])
    length = int(row[7])
    if offset < 0:
        raise SystemExit(f'cannot classify non-positional write {write_id}')
    inside_wal = any(start <= offset and offset + length <= end for start, end in ranges)
    overlaps_wal = any(offset < end and start < offset + length for start, end in ranges)
    if overlaps_wal and not inside_wal:
        raise SystemExit(f'write {write_id} crosses a WAL extent boundary')
    if not inside_wal:
        if epoch <= 1:
            raise SystemExit('filesystem target mutation preceded the first real WAL barrier')
        print(write_id)
        break
else:
    raise SystemExit('compound repair inventory contains no non-WAL target write')
PY
}

interrupted_expectation() {
    image=$1
    inspection=$2
    journal_layout=${3:-$work/t1os.roothealth-journal.json}
    journal_uuid=${4:-$expected_journal_uuid}
    volume_serial=${5:-$expected_report_serial}
    python3 "$wal_fixtures" inspect "$image" \
        "$journal_layout" \
        --expected-journal-uuid "$journal_uuid" \
        --expected-volume-serial "$volume_serial" >"$inspection"
    python3 - "$inspection" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1], encoding='utf-8'))
verdict = report['verdict']
selected = report.get('selected')
if verdict in ('invalid', 'ambiguous'):
    print('wal-invalid')
elif not isinstance(selected, dict):
    raise SystemExit('runtime WAL inspection has no selected header')
elif selected.get('state') != 'EMPTY':
    oracle = selected.get('entry_oracle')
    if not isinstance(oracle, dict) or oracle.get('valid') is not True:
        # The product's read-only phase attests the selected header here; the
        # recovery path independently validates/rederives the referenced entry
        # prefix before any write.  Preserve that staged public distinction.
        print('wal-degraded' if verdict == 'degraded' else 'unsafe-or-io')
        raise SystemExit(0)
    if oracle.get('entry_count') != selected.get('entry_count'):
        raise SystemExit('WAL entry oracle/header count disagreement')
    if oracle.get('target_bytes') != selected.get('target_bytes'):
        raise SystemExit('WAL entry oracle/header target-byte disagreement')
    if oracle.get('plan_sha256') != selected.get('plan_sha256'):
        raise SystemExit('WAL entry oracle/header plan-hash disagreement')
    if oracle.get('semantic_seals_valid') is not True:
        raise SystemExit('selected non-EMPTY WAL lacks semantic target seals')
    if oracle.get('recovery_rederivation_supported') is not True:
        print('wal-unsupported')
    else:
        print('interrupted')
elif verdict == 'degraded':
    print('wal-degraded')
else:
    print('clean-or-unsafe')
PY
}

validate_killed_report() {
    report=$1
    python3 - "$report" <<'PY'
import json
import os
from pathlib import Path
import stat
import sys

path = Path(sys.argv[1])
if not path.exists() and not path.is_symlink():
    raise SystemExit(0)
metadata = path.lstat()
if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
    raise SystemExit('killed repair report is not a regular no-follow file')
if stat.S_IMODE(metadata.st_mode) & 0o077:
    raise SystemExit('killed repair report is accessible outside its owner')
data = path.read_bytes()
try:
    value = json.loads(data)
except (UnicodeError, json.JSONDecodeError):
    raise SystemExit(0)
if isinstance(value, dict) and value.get('format') == 3:
    raise SystemExit('killed repair left a parseable format-3 report')
PY
}

foundation_state_health() {
    image=$1
    case_name=$2
    python3 -B - "$base_image" "$image" "$case_name" <<'PY'
from pathlib import Path
import struct
import sys

base_path = Path(sys.argv[1])
image_path = Path(sys.argv[2])
case = sys.argv[3]
base_size = base_path.stat().st_size
if image_path.stat().st_size != base_size:
    raise SystemExit('foundation cut changed the image size')
with base_path.open('rb') as base:
    boot = base.read(512)
if boot[3:11] != b'NTFS    ' or boot[510:512] != b'\x55\xaa':
    raise SystemExit('foundation oracle base boot is invalid')
sector_size = struct.unpack_from('<H', boot, 11)[0]
sectors_per_cluster = boot[13]
total_sectors = struct.unpack_from('<Q', boot, 40)[0]
mft_lcn = struct.unpack_from('<Q', boot, 48)[0]
mftmirr_lcn = struct.unpack_from('<Q', boot, 56)[0]
record_code = struct.unpack_from('<b', boot, 64)[0]
cluster_size = sector_size * sectors_per_cluster
record_size = 1 << -record_code if record_code < 0 else record_code * cluster_size
ranges = {
    'boot-primary': (0, sector_size),
    'boot-backup': (total_sectors * sector_size, sector_size),
    'mft-primary': (mft_lcn * cluster_size, record_size),
    'mft-mirror': (mftmirr_lcn * cluster_size, record_size),
}
try:
    target_offset, target_length = ranges[case]
except KeyError as error:
    raise SystemExit(f'unknown foundation oracle case {case!r}') from error
target_end = target_offset + target_length
if target_offset < 0 or target_end > base_size:
    raise SystemExit('foundation oracle target is outside the image')

def compare_range(start: int, end: int) -> bool:
    with base_path.open('rb') as left, image_path.open('rb') as right:
        left.seek(start)
        right.seek(start)
        remaining = end - start
        while remaining:
            amount = min(1024 * 1024, remaining)
            if left.read(amount) != right.read(amount):
                return False
            remaining -= amount
    return True

# A direct foundation write is allowed to touch exactly one redundant target.
# Everything else—including the peer authority, $Volume dirty records, and the
# preallocated RootHealth WAL—must remain byte-identical to the clean oracle.
if not compare_range(0, target_offset) or not compare_range(target_end, base_size):
    raise SystemExit('foundation cut changed bytes outside its sole target')
target_matches = compare_range(target_offset, target_end)
print('clean' if target_matches else 'unsafe')
PY
}

foundation_converge_state() {
    image=$1
    case_name=$2
    action_id=$3
    expected_kind=$4
    label=$5
    state=$(foundation_state_health "$image" "$case_name")
    run_check "$image" "$label-before" "$state" >/dev/null
    report="$work/$label-recovery.json"
    trace="$work/$label-recovery.strace"
    active_loop=$(losetup --find --show "$image")
    recovery_device=$active_loop
    set +e
    timeout 300s strace -f -yy -o "$trace" -e trace="$trace_syscalls" \
        "$repair_checker" --repair --quiet --require-t1os-root \
        "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
        --report "$report" "$active_loop" \
        >"$work/$label-recovery.log" 2>&1
    recovery_status=$?
    set -e
    losetup --detach "$active_loop"
    active_loop=
    [ "$recovery_status" -eq 0 ] || {
        echo "Foundation recovery $label returned $recovery_status; expected 0." >&2
        sed -n '1,220p' "$work/$label-recovery.log" >&2
        exit 1
    }
    case "$state" in
        clean)
            python3 "$report_validator" "$report" \
                "${report_binding_args[@]}" --noop
            trace_target_io "$trace" "$recovery_device" none >/dev/null
            ;;
        unsafe)
            python3 "$report_validator" "$report" \
                "${report_binding_args[@]}" --expected-kind "$expected_kind"
            assert_clean_foundation_report "$case_name" "$action_id" \
                "$expected_kind" "$report"
            trace_target_io "$trace" "$recovery_device" repair >/dev/null
            ;;
        *) echo "Unknown foundation state $state" >&2; exit 1 ;;
    esac
    validate_rescan_execution_trace "$trace" "$recovery_device" "$report" \
        "$repair_checker" >/dev/null
    [ "$(sha256sum "$image" | awk '{print $1}')" = \
            "$(sha256sum "$base_image" | awk '{print $1}')" ] || {
        echo "Foundation recovery $label did not converge to the exact clean oracle." >&2
        exit 1
    }
    run_check "$image" "$label-final" clean >/dev/null
}

foundation_trace_counts() {
    trace=$1
    device=$2
    expected_writes=$3
    expected_syncs=$4
    python3 -B - "$trace" "$device" "$expected_writes" "$expected_syncs" <<'PY'
from pathlib import Path
import re
import sys

lines = Path(sys.argv[1]).read_text(encoding='utf-8', errors='replace').splitlines()
device = sys.argv[2]
expected_writes = int(sys.argv[3])
expected_syncs = int(sys.argv[4])
writes = []
syncs = []
for line in lines:
    if f'<{device}>' not in line and f'<{device}<' not in line:
        continue
    if re.search(r'\b(?:write|writev|pwrite64|pwritev|pwritev2)\(', line):
        writes.append(line)
    if re.search(r'\b(?:fsync|fdatasync)\(', line):
        syncs.append(line)
if len(writes) != expected_writes or len(syncs) != expected_syncs:
    raise SystemExit(
        f'foundation cut I/O differs: writes={len(writes)}/{expected_writes}, '
        f'syncs={len(syncs)}/{expected_syncs}'
    )
PY
}

foundation_powercut_sweep() {
    case_name=$1
    source_image=$2
    action_id=$3
    expected_kind=$4
    source_hash=$(sha256sum "$source_image" | awk '{print $1}')
    [ "$(foundation_state_health "$source_image" "$case_name")" = unsafe ] || {
        echo "Foundation source $case_name is not the intended readable-invalid target." >&2
        exit 1
    }

    inventory_image="$work/foundation-$case_name-inventory.ntfs"
    inventory_report="$work/foundation-$case_name-inventory.json"
    inventory_events="$work/foundation-$case_name-inventory.tsv"
    inventory_payload="$work/foundation-$case_name-inventory.payload"
    inventory_trace="$work/foundation-$case_name-inventory.strace"
    clone_fixture "$source_image" "$inventory_image"
    active_loop=$(losetup --find --show "$inventory_image")
    inventory_device=$active_loop
    set +e
    timeout 300s strace -f -yy -o "$inventory_trace" \
        -e trace="$trace_syscalls" \
        env LD_PRELOAD="$fault_library" ROOTHEALTH_FAULT_MODE=capture \
        ROOTHEALTH_FAULT_TARGET="$active_loop" \
        ROOTHEALTH_FAULT_LOG="$inventory_events" \
        ROOTHEALTH_FAULT_PAYLOAD="$inventory_payload" \
        "$repair_checker" --repair --quiet --require-t1os-root \
        "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
        --report "$inventory_report" "$active_loop" \
        >"$work/foundation-$case_name-inventory.log" 2>&1
    inventory_status=$?
    set -e
    losetup --detach "$active_loop"
    active_loop=
    [ "$inventory_status" -eq 0 ] || {
        echo "Foundation inventory $case_name returned $inventory_status; expected 0." >&2
        sed -n '1,240p' "$work/foundation-$case_name-inventory.log" >&2
        exit 1
    }
    python3 "$report_validator" "$inventory_report" \
        "${report_binding_args[@]}" --expected-kind "$expected_kind"
    assert_clean_foundation_report "$case_name" "$action_id" \
        "$expected_kind" "$inventory_report"
    python3 -B "$powercut_materializer" validate \
        "$inventory_events" "$inventory_payload" "$source_image" \
        --inventory-final "$inventory_image" >/dev/null
    validate_capture_trace "$inventory_events" "$inventory_trace" \
        "$inventory_device" >/dev/null
    validate_rescan_execution_trace "$inventory_trace" "$inventory_device" \
        "$inventory_report" "$repair_checker" >/dev/null
    python3 -B - "$inventory_events" "$inventory_report" <<'PY'
import json
from pathlib import Path
import sys

rows = [line.split('\t') for line in Path(sys.argv[1]).read_text().splitlines()]
report = json.load(open(sys.argv[2], encoding='utf-8'))
writes = [row for row in rows[1:] if row[0] == 'W']
syncs = [row for row in rows[1:] if row[0] == 'S']
if len(writes) != 1 or len(syncs) != 2:
    raise SystemExit(f'foundation inventory is not 1 pwrite/2 barriers: {len(writes)}/{len(syncs)}')
action = report['foundation_repairs'][0]
write = writes[0]
if (
    int(write[5]) != action['offset']
    or int(write[6]) != action['length']
    or int(write[7]) != action['length']
    or int(write[8]) != 0
):
    raise SystemExit('foundation inventory write differs from its action record')
if any(int(row[5]) != 0 or int(row[6]) != 0 for row in syncs):
    raise SystemExit('foundation inventory contains a failed real barrier')
if action.get('write_boundaries') != 1 or report.get('commit', {}).get('syncs') != 2:
    raise SystemExit('foundation report boundary/sync totals differ from observation')
PY
    [ "$(foundation_state_health "$inventory_image" "$case_name")" = clean ] || {
        echo "Foundation inventory $case_name did not reach the exact clean state." >&2
        exit 1
    }

    state_directory="$work/foundation-$case_name-states"
    state_manifest="$work/foundation-$case_name-states.json"
    python3 -B "$powercut_materializer" materialize \
        "$inventory_events" "$inventory_payload" "$source_image" \
        "$state_directory" --manifest "$state_manifest" \
        --inventory-final "$inventory_image" >/dev/null
    python3 -B - "$state_manifest" \
        >"$work/foundation-$case_name-states.tsv" <<'PY'
import json
import sys
manifest = json.load(open(sys.argv[1], encoding='utf-8'))
if manifest['logical_case_count'] < manifest['physical_state_count']:
    raise SystemExit('foundation materializer lost logical durability cases')
for ordinal, state in enumerate(manifest['physical_states']):
    print(ordinal, state['path'], state['sha256'], sep='\t')
PY
    materialized_count=0
    while IFS=$'\t' read -r ordinal state_name state_hash; do
        state_image="$state_directory/$state_name"
        [ "$state_hash" = "$(sha256sum "$state_image" | awk '{print $1}')" ] || {
            echo "Foundation materialized state $case_name/$ordinal hash differs." >&2
            exit 1
        }
        foundation_converge_state "$state_image" "$case_name" "$action_id" \
            "$expected_kind" "foundation-$case_name-media-$ordinal"
        materialized_count=$((materialized_count + 1))
    done <"$work/foundation-$case_name-states.tsv"

    signal_modes=(
        crash-before-write crash-after-write
        crash-before-barrier crash-after-barrier
        crash-before-barrier crash-after-barrier
    )
    signal_at=(1 1 1 1 2 2)
    signal_writes=(0 1 1 1 1 1)
    signal_syncs=(0 0 0 1 1 2)
    for index in "${!signal_modes[@]}"; do
        cut=$((index + 1))
        mode=${signal_modes[$index]}
        at=${signal_at[$index]}
        attempt="$work/foundation-$case_name-signal-$cut.ntfs"
        report="$work/foundation-$case_name-signal-$cut.json"
        trace="$work/foundation-$case_name-signal-$cut.strace"
        events="$work/foundation-$case_name-signal-$cut.tsv"
        payload="$work/foundation-$case_name-signal-$cut.payload"
        clone_fixture "$source_image" "$attempt"
        active_loop=$(losetup --find --show "$attempt")
        cut_device=$active_loop
        observer_args=(
            ROOTHEALTH_FAULT_MODE="$mode"
            ROOTHEALTH_FAULT_TARGET="$active_loop"
            ROOTHEALTH_FAULT_AT="$at"
        )
        case "$mode" in
            *barrier)
                observer_args+=(
                    ROOTHEALTH_FAULT_LOG="$events"
                    ROOTHEALTH_FAULT_PAYLOAD="$payload"
                )
                ;;
        esac
        set +e
        timeout 300s strace -f -yy -o "$trace" -e trace="$trace_syscalls" \
            env LD_PRELOAD="$fault_library" "${observer_args[@]}" \
            "$repair_checker" --repair --quiet --require-t1os-root \
            "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
            --report "$report" "$active_loop" \
            >"$work/foundation-$case_name-signal-$cut.log" 2>&1
        cut_status=$?
        set -e
        losetup --detach "$active_loop"
        active_loop=
        [ "$cut_status" -eq 137 ] || {
            echo "Foundation SIGKILL $case_name/$mode:$at returned $cut_status; expected 137." >&2
            exit 1
        }
        validate_killed_report "$report"
        foundation_trace_counts "$trace" "$cut_device" \
            "${signal_writes[$index]}" "${signal_syncs[$index]}"
        foundation_converge_state "$attempt" "$case_name" "$action_id" \
            "$expected_kind" "foundation-$case_name-signal-$cut"
    done

    hook_names=(
        powercut-before-pwrite:1 powercut-after-pwrite:1
        powercut-before-sync:1 powercut-after-sync:1
        powercut-after-verify:1 powercut-before-sync:2 powercut-after-sync:2
    )
    hook_writes=(0 1 1 1 1 1 1)
    hook_syncs=(0 0 0 1 1 1 2)
    for index in "${!hook_names[@]}"; do
        cut=$((index + 1))
        hook=${hook_names[$index]}
        attempt="$work/foundation-$case_name-hook-$cut.ntfs"
        report="$work/foundation-$case_name-hook-$cut.json"
        trace="$work/foundation-$case_name-hook-$cut.strace"
        clone_fixture "$source_image" "$attempt"
        active_loop=$(losetup --find --show "$attempt")
        cut_device=$active_loop
        set +e
        timeout 300s strace -f -yy -o "$trace" -e trace="$trace_syscalls" \
            env ROOTHEALTH_REPAIR_TEST_FAIL="$hook" \
            "$repair_checker" --repair --quiet --require-t1os-root \
            "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
            --report "$report" "$active_loop" \
            >"$work/foundation-$case_name-hook-$cut.log" 2>&1
        cut_status=$?
        set -e
        losetup --detach "$active_loop"
        active_loop=
        [ "$cut_status" -eq 86 ] || {
            echo "Foundation hook $case_name/$hook returned $cut_status; expected 86." >&2
            exit 1
        }
        validate_killed_report "$report"
        foundation_trace_counts "$trace" "$cut_device" \
            "${hook_writes[$index]}" "${hook_syncs[$index]}"
        foundation_converge_state "$attempt" "$case_name" "$action_id" \
            "$expected_kind" "foundation-$case_name-hook-$cut"
    done

    [ "$source_hash" = "$(sha256sum "$source_image" | awk '{print $1}')" ] || {
        echo "Foundation sweep changed immutable source $case_name." >&2
        exit 1
    }
    printf 'PASS foundation-powercut-%-12s media=%s signals=6 hooks=7 source=%s\n' \
        "$case_name" "$materialized_count" "$source_hash"
}

# Foundation repair is hard-closed in v0.3, so the four families above are
# exercised as mandatory zero-write refusals instead of unreachable crash
# sweeps.  Crash qualification below targets the enabled bitmap/WAL family.

native_powercut_sweep() {
    local -a repair_identity_args=("${native_redo_identity_args[@]}")
    local -a report_binding_args=("${native_redo_report_binding_args[@]}")
    source_image=$native_redo_powercut_source_image
    source_before=$(sha256sum "$source_image" | awk '{print $1}')
    assert_native_redo_target "$source_image" before

    inventory_image="$work/native-powercut-inventory.ntfs"
    inventory_report="$work/native-powercut-inventory.json"
    inventory_events="$work/native-powercut-inventory.tsv"
    inventory_payload="$work/native-powercut-inventory.payload"
    inventory_capture="$work/native-powercut-inventory-capture.json"
    inventory_trace="$work/native-powercut-inventory.strace"
    clone_fixture "$source_image" "$inventory_image"
    active_loop=$(losetup --find --show "$inventory_image")
    inventory_device=$active_loop
    set +e
    timeout 300s strace -f -yy -o "$inventory_trace" \
        -e trace="$trace_syscalls" \
        env LD_PRELOAD="$fault_library" \
        ROOTHEALTH_FAULT_MODE=capture \
        ROOTHEALTH_FAULT_TARGET="$active_loop" \
        ROOTHEALTH_FAULT_LOG="$inventory_events" \
        ROOTHEALTH_FAULT_PAYLOAD="$inventory_payload" \
        "$repair_checker" --repair --quiet --require-t1os-root \
        "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
        --report "$inventory_report" "$active_loop" \
        >"$work/native-powercut-inventory.log" 2>&1
    inventory_status=$?
    set -e
    losetup --detach "$active_loop"
    active_loop=
    [ "$inventory_status" -eq 0 ] || {
        echo "Native replay power-cut inventory returned $inventory_status; expected 0." >&2
        sed -n '1,240p' "$work/native-powercut-inventory.log" >&2
        exit 1
    }
    python3 -B "$powercut_materializer" validate \
        "$inventory_events" "$inventory_payload" "$source_image" \
        --inventory-final "$inventory_image" --report "$inventory_capture" >/dev/null
    read -r native_write_count native_barrier_count < <(python3 - "$inventory_capture" <<'PY'
import json
import sys
capture = json.load(open(sys.argv[1], encoding='utf-8'))['capture']
print(capture['write_count'], capture['barrier_count'])
PY
    )
    if [ "$native_write_count" -le 0 ] || [ "$native_barrier_count" -le 0 ]; then
        echo 'Native replay power-cut inventory has no writes or real barriers.' >&2
        exit 1
    fi
    native_first_target=$(first_target_write \
        "$inventory_events" "$work/native-redo.roothealth-journal.json")
    native_capture_count=$(validate_capture_trace \
        "$inventory_events" "$inventory_trace" "$inventory_device")
    native_trace_count=$(trace_target_io "$inventory_trace" "$inventory_device" repair)
    validate_rescan_execution_trace "$inventory_trace" "$inventory_device" \
        "$inventory_report" "$repair_checker" >/dev/null
    if [ "$native_write_count" -ne "$native_capture_count" ] || \
            [ "$native_write_count" -ne "$native_trace_count" ]; then
        echo 'Native replay observer and strace write counts differ.' >&2
        exit 1
    fi
    python3 "$report_validator" "$inventory_report" \
        "${report_binding_args[@]}" \
        --expected-kind logfile-redo --expected-kind logfile-restart \
        --expected-kind volume-dirty-clear
    assert_native_redo_target "$inventory_image" after
    assert_manifest_equal "$inventory_image" native-powercut-inventory \
        "$native_redo_base_manifest"

    state_directory="$work/native-powercut-states"
    state_manifest="$work/native-powercut-states.json"
    python3 -B "$powercut_materializer" materialize \
        "$inventory_events" "$inventory_payload" "$source_image" \
        "$state_directory" --manifest "$state_manifest" \
        --inventory-final "$inventory_image" >"$work/native-powercut-materialize.log"
    python3 - "$state_manifest" >"$work/native-powercut-physical-states.tsv" <<'PY'
import json
import sys
manifest = json.load(open(sys.argv[1], encoding='utf-8'))
if manifest['logical_case_count'] < manifest['physical_state_count']:
    raise SystemExit('native materializer lost logical durability cases')
for ordinal, state in enumerate(manifest['physical_states']):
    print(ordinal, state['path'], state['sha256'], sep='\t')
PY

    native_physical_count=0
    while IFS=$'\t' read -r state_ordinal state_name state_hash; do
        state_image="$state_directory/$state_name"
        [ "$state_hash" = "$(sha256sum "$state_image" | awk '{print $1}')" ] || {
            echo "Native materialized state $state_ordinal hash differs." >&2
            exit 1
        }
        inspection="$work/native-powercut-state-$state_ordinal-wal.json"
        check_expectation=$(interrupted_expectation \
            "$state_image" "$inspection" \
            "$work/native-redo.roothealth-journal.json" \
            "$native_redo_uuid" "$native_redo_report_serial")
        precheck_status=$(run_check "$state_image" \
            "native-power-state-$state_ordinal" "$check_expectation")
        if [ "$check_expectation" = wal-unsupported ]; then
            echo "Successful native repair inventory emitted an unqualified recovery action in state $state_ordinal." >&2
            echo 'Release qualification requires convergence for every action the binary can emit.' >&2
            exit 1
        fi
        recovery_report="$work/native-powercut-state-$state_ordinal-recovery.json"
        active_loop=$(losetup --find --show "$state_image")
        set +e
        timeout 300s "$repair_checker" --repair --quiet --require-t1os-root \
            "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
            --report "$recovery_report" "$active_loop" \
            >"$work/native-powercut-state-$state_ordinal-recovery.log" 2>&1
        recovery_status=$?
        set -e
        losetup --detach "$active_loop"
        active_loop=
        [ "$recovery_status" -eq 0 ] || {
            echo "Native replay did not converge for state $state_ordinal (exit $recovery_status)." >&2
            sed -n '1,240p' \
                "$work/native-powercut-state-$state_ordinal-recovery.log" >&2
            exit 1
        }
        recovery_validation=()
        [ "$precheck_status" -eq 0 ] && recovery_validation+=(--noop)
        python3 "$report_validator" "$recovery_report" \
            "${report_binding_args[@]}" "${recovery_validation[@]}"
        run_check "$state_image" \
            "native-power-state-final-$state_ordinal" clean >/dev/null
        assert_native_redo_target "$state_image" after
        assert_manifest_equal "$state_image" \
            "native-powercut-state-$state_ordinal" "$native_redo_base_manifest"
        native_physical_count=$((native_physical_count + 1))
        printf 'PASS native-powercut-state state=%s hash=%s\n' \
            "$state_ordinal" "$state_hash"
    done <"$work/native-powercut-physical-states.tsv"

    for barrier in $(seq 1 "$native_barrier_count"); do
        attempt="$work/native-powercut-barrier-$barrier.ntfs"
        events="$work/native-powercut-barrier-$barrier.tsv"
        payload="$work/native-powercut-barrier-$barrier.payload"
        fault_report="$work/native-powercut-barrier-$barrier-report.json"
        fault_trace="$work/native-powercut-barrier-$barrier.strace"
        clone_fixture "$source_image" "$attempt"
        active_loop=$(losetup --find --show "$attempt")
        fault_device=$active_loop
        set +e
        timeout 300s strace -f -yy -o "$fault_trace" -e trace="$trace_syscalls" \
            env LD_PRELOAD="$fault_library" \
            ROOTHEALTH_FAULT_MODE=crash-before-barrier \
            ROOTHEALTH_FAULT_AT="$barrier" \
            ROOTHEALTH_FAULT_TARGET="$active_loop" \
            ROOTHEALTH_FAULT_LOG="$events" \
            ROOTHEALTH_FAULT_PAYLOAD="$payload" \
            "$repair_checker" --repair --quiet --require-t1os-root \
            "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
            --report "$fault_report" "$active_loop" \
            >"$work/native-powercut-barrier-$barrier.log" 2>&1
        fault_status=$?
        set -e
        losetup --detach "$active_loop"
        active_loop=
        [ "$fault_status" -eq 137 ] || {
            echo "Native crash before barrier $barrier returned $fault_status; expected 137." >&2
            sed -n '1,200p' "$work/native-powercut-barrier-$barrier.log" >&2
            exit 1
        }
        python3 -B "$powercut_materializer" validate \
            "$events" "$payload" "$source_image" >/dev/null
        validate_capture_trace "$events" "$fault_trace" "$fault_device" >/dev/null
        trace_target_io "$fault_trace" "$fault_device" repair >/dev/null
        validate_killed_report "$fault_report"
        printf 'PASS native-powercut-crash barrier=%s/%s\n' \
            "$barrier" "$native_barrier_count"
    done
    [ "$source_before" = "$(sha256sum "$source_image" | awk '{print $1}')" ] || {
        echo 'Native power-cut sweep changed its immutable source image.' >&2
        exit 1
    }
    printf 'PASS native-powercut-sweep writes=%s barriers=%s first-target=%s states=%s\n' \
        "$native_write_count" "$native_barrier_count" \
        "$native_first_target" "$native_physical_count"
}

# Native ID5/ID6 is an enabled atomic WAL family.  Materialize every distinct
# durable state and require recovery to converge before exercising the existing
# bitmap/dirty family below.
if [ "${ROOTHEALTH_SKIP_NATIVE_POWERCUT:-0}" != 1 ]; then
    native_powercut_sweep
fi

# Capture every target write attempt and every real durability barrier on a
# enabled cluster-bitmap corruption.  LD_PRELOAD is scoped to the checker exec: timeout and
# strace themselves are never interposed.  The killed loop cache is not used as
# crash media; the independent materializer below replays captured bytes onto
# the immutable source according to conservative physical-sector durability.
inventory_image="$work/powercut-inventory.ntfs"
clone_fixture "$operations_stale_bitmaps_powercut_source" "$inventory_image"
inventory_report="$work/powercut-inventory.json"
inventory_events="$work/powercut-inventory.tsv"
inventory_payload="$work/powercut-inventory.payload"
inventory_capture="$work/powercut-inventory-capture.json"
inventory_trace="$work/powercut-inventory.strace"
active_loop=$(losetup --find --show "$inventory_image")
inventory_device=$active_loop
set +e
timeout 300s strace -f -yy -o "$inventory_trace" \
    -e trace="$trace_syscalls" \
    env LD_PRELOAD="$fault_library" \
    ROOTHEALTH_FAULT_MODE=capture \
    ROOTHEALTH_FAULT_TARGET="$active_loop" \
    ROOTHEALTH_FAULT_LOG="$inventory_events" \
    ROOTHEALTH_FAULT_PAYLOAD="$inventory_payload" \
    "$repair_checker" --repair --quiet --require-t1os-root \
    "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
    --report "$inventory_report" "$active_loop" \
    >"$work/powercut-inventory.log" 2>&1
inventory_status=$?
set -e
losetup --detach "$active_loop"
active_loop=
[ "$inventory_status" -eq 0 ] || {
    echo "Power-cut inventory repair returned $inventory_status; expected 0." >&2
    sed -n '1,240p' "$work/powercut-inventory.log" >&2
    exit 1
}
python3 -B "$powercut_materializer" validate \
	"$inventory_events" "$inventory_payload" \
	"$operations_stale_bitmaps_powercut_source" \
    --inventory-final "$inventory_image" --report "$inventory_capture" >/dev/null
read -r write_count barrier_count < <(python3 - "$inventory_capture" <<'PY'
import json
import sys
capture = json.load(open(sys.argv[1], encoding='utf-8'))['capture']
print(capture['write_count'], capture['barrier_count'])
PY
)
if [ "$write_count" -le 0 ] || [ "$barrier_count" -le 0 ]; then
    echo 'Power-cut inventory has no target writes or real durability barriers.' >&2
    exit 1
fi
first_target=$(first_target_write "$inventory_events")
capture_trace_count=$(validate_capture_trace \
    "$inventory_events" "$inventory_trace" "$inventory_device")
trace_count=$(trace_target_io "$inventory_trace" "$inventory_device" repair)
validate_rescan_execution_trace "$inventory_trace" "$inventory_device" \
    "$inventory_report" "$repair_checker" >/dev/null
if [ "$trace_count" -ne "$write_count" ] || \
        [ "$capture_trace_count" -ne "$write_count" ]; then
    echo "Observer counted $write_count writes but strace observed $trace_count." >&2
    exit 1
fi
python3 "$report_validator" "$inventory_report" \
	"${report_binding_args[@]}" \
	--expected-kind volume-dirty-set --expected-kind index-root \
	--expected-kind bitmap-mft --expected-kind bitmap-cluster \
	--expected-kind volume-dirty-clear
assert_manifest_equal "$inventory_image" powercut-inventory \
	"$operations_stale_manifest"
assert_raw_health "$inventory_image" operations-registry-stale-bitmaps

compound_before=$(sha256sum "$operations_stale_bitmaps_powercut_source" | awk '{print $1}')

state_directory="$work/powercut-states"
state_manifest="$work/powercut-states.json"
python3 -B "$powercut_materializer" materialize \
	"$inventory_events" "$inventory_payload" \
	"$operations_stale_bitmaps_powercut_source" \
    "$state_directory" --manifest "$state_manifest" \
    --inventory-final "$inventory_image" >"$work/powercut-materialize.log"
python3 - "$state_manifest" >"$work/powercut-physical-states.tsv" <<'PY'
import json
import sys
manifest = json.load(open(sys.argv[1], encoding='utf-8'))
if manifest['logical_case_count'] < manifest['physical_state_count']:
    raise SystemExit('materializer lost logical durability cases')
for ordinal, state in enumerate(manifest['physical_states']):
    print(ordinal, state['path'], state['sha256'], sep='\t')
PY

physical_count=0
while IFS=$'\t' read -r state_ordinal state_name state_hash; do
    state_image="$state_directory/$state_name"
    [ "$state_hash" = "$(sha256sum "$state_image" | awk '{print $1}')" ] || {
        echo "Materialized state $state_ordinal hash differs from its manifest." >&2
        exit 1
    }
    interrupted_inspection="$work/powercut-state-$state_ordinal-wal.json"
    check_expectation=$(interrupted_expectation "$state_image" "$interrupted_inspection")
    precheck_status=$(run_check "$state_image" "power-state-$state_ordinal" \
        "$check_expectation")
    if [ "$check_expectation" = wal-unsupported ]; then
        echo "Successful compound repair inventory emitted an unqualified recovery action in state $state_ordinal." >&2
        echo 'Release qualification requires convergence for every action the binary can emit.' >&2
        exit 1
    fi
    recovery_report="$work/powercut-state-$state_ordinal-recovery.json"
    active_loop=$(losetup --find --show "$state_image")
    set +e
    timeout 300s "$repair_checker" --repair --quiet --require-t1os-root \
        "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
        --report "$recovery_report" "$active_loop" \
        >"$work/powercut-state-$state_ordinal-recovery.log" 2>&1
    recovery_status=$?
    set -e
    losetup --detach "$active_loop"
    active_loop=
    [ "$recovery_status" -eq 0 ] || {
        echo "Repair did not converge for materialized state $state_ordinal (exit $recovery_status)." >&2
        sed -n '1,240p' "$work/powercut-state-$state_ordinal-recovery.log" >&2
        exit 1
    }
    recovery_validation=()
    [ "$precheck_status" -eq 0 ] && recovery_validation+=(--noop)
    python3 "$report_validator" "$recovery_report" \
        "${report_binding_args[@]}" "${recovery_validation[@]}"
    run_check "$state_image" "power-state-final-$state_ordinal" clean >/dev/null
	assert_manifest_equal "$state_image" "powercut-state-$state_ordinal" \
		"$operations_stale_manifest"
	assert_raw_health "$state_image" operations-registry-stale-bitmaps
    physical_count=$((physical_count + 1))
    printf 'PASS powercut-state state=%s hash=%s\n' "$state_ordinal" "$state_hash"
done <"$work/powercut-physical-states.tsv"

# A separate SIGKILL run proves that each real barrier is reachable and that
# the selected fsync/fdatasync never reaches the kernel.  Its loop image is
# intentionally discarded; only the side-channel/strace/report assertions are
# used.  SIGKILL may strand a private incomplete report, which is not a
# published format-3 result and is ignored by recovery.
for barrier in $(seq 1 "$barrier_count"); do
    attempt="$work/powercut-barrier-$barrier.ntfs"
    events="$work/powercut-barrier-$barrier.tsv"
    payload="$work/powercut-barrier-$barrier.payload"
    fault_report="$work/powercut-barrier-$barrier-report.json"
    fault_trace="$work/powercut-barrier-$barrier.strace"
	clone_fixture "$operations_stale_bitmaps_powercut_source" "$attempt"
    active_loop=$(losetup --find --show "$attempt")
    fault_device=$active_loop
    set +e
    timeout 300s strace -f -yy -o "$fault_trace" -e trace="$trace_syscalls" \
        env LD_PRELOAD="$fault_library" \
        ROOTHEALTH_FAULT_MODE=crash-before-barrier \
        ROOTHEALTH_FAULT_AT="$barrier" \
        ROOTHEALTH_FAULT_TARGET="$active_loop" \
        ROOTHEALTH_FAULT_LOG="$events" \
        ROOTHEALTH_FAULT_PAYLOAD="$payload" \
        "$repair_checker" --repair --quiet --require-t1os-root \
        "${repair_identity_args[@]}" "${repair_scope_args[@]}" \
        --report "$fault_report" "$active_loop" \
        >"$work/powercut-barrier-$barrier.log" 2>&1
    fault_status=$?
    set -e
    losetup --detach "$active_loop"
    active_loop=
    [ "$fault_status" -eq 137 ] || {
        echo "Crash before barrier $barrier returned $fault_status; expected 137." >&2
        sed -n '1,200p' "$work/powercut-barrier-$barrier.log" >&2
        exit 1
    }
	python3 -B "$powercut_materializer" validate \
		"$events" "$payload" \
		"$operations_stale_bitmaps_powercut_source" >/dev/null
    validate_capture_trace "$events" "$fault_trace" "$fault_device" >/dev/null
    trace_target_io "$fault_trace" "$fault_device" repair >/dev/null
    validate_killed_report "$fault_report"
    printf 'PASS powercut-crash barrier=%s/%s\n' "$barrier" "$barrier_count"
done
[ "$compound_before" = "$(sha256sum "$operations_stale_bitmaps_powercut_source" | awk '{print $1}')" ] || {
    echo 'Power-cut sweep changed its immutable source corruption fixture.' >&2
    exit 1
}

echo "roothealth repair qualification passed: $write_count writes, $barrier_count barriers, first target write $first_target, $physical_count durable states."
