[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$builder = Join-Path $PSScriptRoot 'build roothealth.ps1'
$checker = Join-Path $projectRoot 'environment\hardware\tools\roothealth'
$journalValidator = Join-Path $PSScriptRoot 'validate roothealth journal.py'
$ntfscp = Join-Path $PSScriptRoot 'roothealth-repair\journal-integration-v2\ntfscp'

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Ubuntu WSL is required to test roothealth.'
}
if (-not (Test-Path -LiteralPath $builder -PathType Leaf)) {
    throw "The roothealth builder is missing: $builder"
}
foreach ($requiredInput in @($journalValidator, $ntfscp)) {
    if (-not (Test-Path -LiteralPath $requiredInput -PathType Leaf)) {
        throw "A roothealth test input is missing: $requiredInput"
    }
}

& pwsh -NoLogo -NoProfile -NonInteractive -File $builder
$buildExitCode = $LASTEXITCODE
if ($buildExitCode -ne 0) {
    throw "The roothealth build failed before testing (exit code $buildExitCode)."
}
if (-not (Test-Path -LiteralPath $checker -PathType Leaf)) {
    throw "The roothealth build did not produce its checker: $checker"
}

$wslChecker = ConvertTo-WslPath -WindowsPath $checker
$wslJournalValidator = ConvertTo-WslPath -WindowsPath $journalValidator
$wslNtfscp = ConvertTo-WslPath -WindowsPath $ntfscp

$testCommand = @'
set -euo pipefail

checker=$1
journal_validator=$2
ntfscp_tool=$3
export LC_ALL=C
umask 077

required_commands=(
    awk bash blockdev chmod cp dd grep losetup mkdir mkfs.ntfs mktemp mount.ntfs-3g
    ntfsinfo python3 readlink rm rmdir sed seq sha256sum stat strace sync timeout
    truncate umount
)
missing=()
for command_name in "${required_commands[@]}"; do
    command -v "$command_name" >/dev/null 2>&1 || missing+=("$command_name")
done
if [ "${#missing[@]}" -ne 0 ]; then
    printf 'Missing roothealth test commands: %s\n' "${missing[*]}" >&2
    exit 127
fi
[ -x "$checker" ] || {
    echo "The checker is not executable in WSL: $checker" >&2
    exit 1
}

work=$(mktemp -d /var/tmp/roothealth-test.XXXXXX)
case "$work" in
    /var/tmp/roothealth-test.*) ;;
    *) echo "Unexpected checker-test path: $work" >&2; exit 1 ;;
esac

active_loop=
mounted=0
mount_root=
cleanup() {
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
    if [ "${ROOTHEALTH_KEEP_TEST_WORK:-0}" = 1 ]; then
        echo "Preserved roothealth test workspace: $work" >&2
    elif [ "$cleanup_failed" = 0 ]; then
        case "$work" in
            /var/tmp/roothealth-test.*) rm -rf -- "$work" ;;
        esac
    else
        echo "Could not completely clean checker-test workspace: $work" >&2
    fi
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

clean_image="$work/t1os-clean.ntfs"
ordinary_image="$work/ordinary.ntfs"
dirty_image="$work/t1os-dirty.ntfs"
truncated_image="$work/truncated.ntfs"
backup_boot_image="$work/t1os-backup-boot-corrupt.ntfs"
backup_mismatch_image="$work/t1os-backup-boot-mismatch.ntfs"
mft_image="$work/t1os-mft-corrupt.ntfs"
index_image="$work/t1os-index-corrupt.ntfs"
precedence_image="$work/ordinary-dirty.ntfs"
writable_probe_image="$work/t1os-writable-probe.ntfs"
boot_dirty_image="$work/t1os-boot-dirty.ntfs"
boot_backup_image="$work/t1os-boot-backup-corrupt.ntfs"

format_and_mount() {
    image=$1
    size=$2
    label=$3

    truncate -s "$size" "$image"
    active_loop=$(losetup --find --show "$image")
    mkfs.ntfs -F -Q -L "$label" "$active_loop" >/dev/null
    mount_root="$work/mount"
    mkdir -p "$mount_root"
    mount.ntfs-3g -o rw,permissions,windows_names,big_writes \
        "$active_loop" "$mount_root"
    mounted=1
}

finish_fixture() {
    sync
    umount "$mount_root"
    mounted=0
    losetup --detach "$active_loop"
    active_loop=
    rmdir "$mount_root"
    mount_root=
}

format_and_mount "$clean_image" 512M 'T1OS CHECK TEST'
mkdir -p \
    "$mount_root/the one/software/python/bin" \
    "$mount_root/the one/build/GODDESS" \
    "$mount_root/the one/build/drivers" \
    "$mount_root/the one/drivers/tools" \
    "$mount_root/the one/drivers/settings" \
    "$mount_root/the one/drivers/modules/test-kernel" \
    "$mount_root/the one/logs" \
    "$mount_root/the one/checker-fixture-index"

printf '#!/bin/sh\nexit 0\n' \
	>"$mount_root/the one/software/python/bin/python"
printf '#!/bin/sh\nexit 0\n' \
    >"$mount_root/the one/software/python/bin/python3.13"
printf '#!/bin/sh\nexit 0\n' \
    >"$mount_root/the one/drivers/tools/modprobe"
chmod 0755 \
	"$mount_root/the one/software/python/bin/python" \
    "$mount_root/the one/software/python/bin/python3.13" \
    "$mount_root/the one/drivers/tools/modprobe"
printf 'print("T1OS checker fixture")\n' \
    >"$mount_root/the one/build/GODDESS/GODDESS.py"
printf 'print("T1OS driver fixture")\n' \
    >"$mount_root/the one/build/drivers/driverserver.py"
printf '{"format":1,"fixture":true}\n' \
    >"$mount_root/the one/drivers/settings/policy.json"
printf '%064d  test-kernel/modules.dep\n' 0 \
    >"$mount_root/the one/drivers/modules/module-manifest.sha256"
printf 'kernel/test.ko:\n' \
    >"$mount_root/the one/drivers/modules/test-kernel/modules.dep"
printf 'This non-critical record is corrupted by the MFT test.\n' \
    >"$mount_root/the one/logs/mft-payload.bin"
test -s "$mount_root/the one/software/python/bin/python"
test -x "$mount_root/the one/software/python/bin/python"
test -s "$mount_root/the one/build/GODDESS/GODDESS.py"
test -s "$mount_root/the one/build/drivers/driverserver.py"
test -x "$mount_root/the one/drivers/tools/modprobe"
test -s "$mount_root/the one/drivers/settings/policy.json"
test -s "$mount_root/the one/drivers/modules/module-manifest.sha256"
test -s "$mount_root/the one/drivers/modules/test-kernel/modules.dep"

# Long, numerous names force a real $I30 allocation while keeping the target
# directory outside the required T1OS identity path set.
for entry_number in $(seq -w 1 128); do
    entry_path=$(
        printf '%s/entry-%s-abcdefghijklmnopqrstuvwxyz0123456789.data' \
            "$mount_root/the one/checker-fixture-index" "$entry_number"
    )
    printf 'index fixture %s\n' "$entry_number" >"$entry_path"
done
finish_fixture

mount_root="$work/mount"
mkdir -p "$mount_root"
seed="$work/roothealth.seed"
journal_report="$work/roothealth.json"
building="$clean_image.building"
mv "$clean_image" "$building"
active_loop=$(losetup --find --show "$building")
python3 -B "$journal_validator" seed "$active_loop" "$seed" >/dev/null
"$ntfscp_tool" -f -m "$active_loop" "$seed" '$Extend/$RootHealth'
sync
mount.ntfs-3g -o rw,permissions,show_sys_files "$active_loop" "$mount_root"
mounted=1
python3 -B - "$mount_root/\$Extend/\$RootHealth" <<'PY'
import os
from pathlib import Path
import struct
import sys

path = Path(sys.argv[1])
required = 0x00002007
os.setxattr(path, 'system.ntfs_attrib', struct.pack('<I', required))
if struct.unpack('<I', os.getxattr(path, 'system.ntfs_attrib'))[0] != required:
    raise SystemExit('RootHealth journal protected attributes did not persist')
PY
sync
umount "$mount_root"
mounted=0
losetup --detach "$active_loop"
active_loop=
python3 -B "$journal_validator" provision-flags "$building" >/dev/null
active_loop=$(losetup --find --show --read-only "$building")
python3 -B "$journal_validator" validate "$active_loop" \
    --require-one-run --require-zero-entry-area --report "$journal_report"
losetup --detach "$active_loop"
active_loop=
mv "$building" "$clean_image"
read -r expected_serial expected_journal_uuid expected_journal_record \
        expected_journal_sequence <<EOF
$(python3 -B - "$journal_report" <<'PY'
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
identity_args=(
    --expected-serial "$expected_serial"
    --expected-journal-uuid "$expected_journal_uuid"
    --expected-journal-record "$expected_journal_record:$expected_journal_sequence"
)
rmdir "$mount_root"
mount_root=

format_and_mount "$ordinary_image" 64M 'ORDINARY NTFS'
mkdir -p "$mount_root/Documents"
printf 'This volume is valid NTFS but it is not a T1OS root.\n' \
    >"$mount_root/Documents/readme.txt"
finish_fixture

cp --reflink=auto --sparse=always "$clean_image" "$dirty_image"
cp --reflink=auto --sparse=always "$clean_image" "$backup_boot_image"
cp --reflink=auto --sparse=always "$clean_image" "$backup_mismatch_image"
cp --reflink=auto --sparse=always "$clean_image" "$mft_image"
cp --reflink=auto --sparse=always "$clean_image" "$index_image"
cp --reflink=auto --sparse=always "$ordinary_image" "$precedence_image"
cp --reflink=auto --sparse=always "$clean_image" "$writable_probe_image"
truncate -s 4096 "$truncated_image"
printf 'NTFS    ' | dd of="$truncated_image" bs=1 seek=3 conv=notrunc status=none

mft_payload_inode=$(
    ntfsinfo -F '/the one/logs/mft-payload.bin' "$clean_image" |
        awk 'NR == 1 && $1 == "Dumping" && $2 == "Inode" { print $3 }'
)
index_directory_info=$(ntfsinfo -F '/the one/checker-fixture-index' "$clean_image")
index_root_inode=$(
    printf '%s\n' "$index_directory_info" |
        awk '$1 == "Dumping" && $2 == "attribute" && $3 == "$INDEX_ROOT" &&
                $6 == "mft" && $7 == "record" { print $8 }'
)
case "$mft_payload_inode" in
    ''|*[!0-9]*) echo 'Could not resolve the MFT fixture inode.' >&2; exit 1 ;;
esac
case "$index_root_inode" in
    ''|*[!0-9]*) echo 'Could not resolve the index-root fixture inode.' >&2; exit 1 ;;
esac
case "$index_directory_info" in
    *'Dumping attribute $INDEX_ALLOCATION'*) ;;
    *) echo 'The index fixture did not allocate a real $I30 tree.' >&2; exit 1 ;;
esac

python3 - "$dirty_image" "$precedence_image" "$backup_boot_image" \
        "$backup_mismatch_image" "$mft_image" "$mft_payload_inode" \
        "$index_image" "$index_root_inode" <<'PY'
from __future__ import annotations

from pathlib import Path
import struct
import sys


class FixtureError(RuntimeError):
    pass


def geometry(path: Path) -> dict[str, int]:
    with path.open('rb') as handle:
        boot = handle.read(512)
    if len(boot) != 512 or boot[3:11] != b'NTFS    ':
        raise FixtureError(f'not an NTFS fixture: {path}')
    sector_size = struct.unpack_from('<H', boot, 11)[0]
    sectors_per_cluster = boot[13]
    total_sectors = struct.unpack_from('<Q', boot, 40)[0]
    mft_lcn = struct.unpack_from('<Q', boot, 48)[0]
    mftmirr_lcn = struct.unpack_from('<Q', boot, 56)[0]
    record_code = struct.unpack_from('<b', boot, 64)[0]
    if sector_size not in (512, 1024, 2048, 4096):
        raise FixtureError(f'invalid fixture sector size: {sector_size}')
    if not sectors_per_cluster:
        raise FixtureError('invalid fixture sectors-per-cluster')
    cluster_size = sector_size * sectors_per_cluster
    record_size = (
        1 << -record_code if record_code < 0 else record_code * cluster_size
    )
    if record_size < sector_size or record_size > 65536:
        raise FixtureError(f'invalid fixture MFT record size: {record_size}')
    return {
        'sector_size': sector_size,
        'sectors_per_cluster': sectors_per_cluster,
        'cluster_size': cluster_size,
        'total_sectors': total_sectors,
        'mft_offset': mft_lcn * cluster_size,
        'mftmirr_offset': mftmirr_lcn * cluster_size,
        'record_size': record_size,
    }


def read_record(handle, offset: int, record_size: int) -> bytearray:
    handle.seek(offset)
    raw = bytearray(handle.read(record_size))
    if len(raw) != record_size or raw[:4] != b'FILE':
        raise FixtureError(f'MFT record is not contiguous at byte {offset}')
    return raw


def fixed_record(raw: bytearray, sector_size: int) -> bytearray:
    fixed = bytearray(raw)
    usa_offset, usa_count = struct.unpack_from('<HH', fixed, 4)
    if (
        usa_offset < 8
        or usa_count < 2
        or usa_offset + usa_count * 2 > len(fixed)
    ):
        raise FixtureError('invalid fixture MFT update-sequence array')
    sequence = fixed[usa_offset:usa_offset + 2]
    for index in range(1, usa_count):
        trailer = index * sector_size - 2
        replacement = usa_offset + index * 2
        if fixed[trailer:trailer + 2] != sequence:
            raise FixtureError('fixture MFT update-sequence check failed')
        fixed[trailer:trailer + 2] = fixed[replacement:replacement + 2]
    return fixed


def resident_attribute_position(
    fixed: bytearray,
    attribute_type: int,
    attribute_name: str | None = None,
) -> tuple[int, int]:
    offset = struct.unpack_from('<H', fixed, 20)[0]
    while offset + 24 <= len(fixed):
        found_type, length = struct.unpack_from('<II', fixed, offset)
        if found_type == 0xFFFFFFFF:
            break
        if length < 24 or offset + length > len(fixed):
            raise FixtureError('invalid fixture MFT attribute bounds')
        nonresident = fixed[offset + 8]
        name_length = fixed[offset + 9]
        name_offset = struct.unpack_from('<H', fixed, offset + 10)[0]
        name = ''
        if name_length:
            name_end = name_offset + name_length * 2
            if name_offset < 24 or name_end > length:
                raise FixtureError('invalid fixture MFT attribute name')
            name = bytes(
                fixed[offset + name_offset:offset + name_end]
            ).decode('utf-16-le')
        if (
            found_type == attribute_type
            and not nonresident
            and (attribute_name is None or name == attribute_name)
        ):
            value_length = struct.unpack_from('<I', fixed, offset + 16)[0]
            value_offset = struct.unpack_from('<H', fixed, offset + 20)[0]
            if value_offset < 24 or value_offset + value_length > length:
                raise FixtureError('invalid fixture resident attribute value')
            return offset + value_offset, value_length
        offset += length
    raise FixtureError(
        f'fixture attribute 0x{attribute_type:x} {attribute_name!r} not found'
    )


dirty_path = Path(sys.argv[1])
precedence_path = Path(sys.argv[2])
backup_path = Path(sys.argv[3])
backup_mismatch_path = Path(sys.argv[4])
mft_path = Path(sys.argv[5])
mft_inode = int(sys.argv[6])
index_path = Path(sys.argv[7])
index_inode = int(sys.argv[8])

def set_dirty(path: Path) -> None:
    """Set VOLUME_IS_DIRTY in both record 3 copies without changing its USA."""
    volume_geometry = geometry(path)
    with path.open('r+b') as handle:
        for base in (
            volume_geometry['mft_offset'],
            volume_geometry['mftmirr_offset'],
        ):
            record_offset = base + 3 * volume_geometry['record_size']
            raw = read_record(handle, record_offset, volume_geometry['record_size'])
            fixed = fixed_record(raw, volume_geometry['sector_size'])
            value_offset, value_length = resident_attribute_position(fixed, 0x70)
            if value_length < 12:
                raise FixtureError('fixture $VOLUME_INFORMATION is too short')
            flags_offset = value_offset + 10
            flags = struct.unpack_from('<H', fixed, flags_offset)[0] | 0x0001
            struct.pack_into('<H', raw, flags_offset, flags)
            handle.seek(record_offset)
            handle.write(raw)


set_dirty(dirty_path)
set_dirty(precedence_path)

# Damage only the backup boot sector. The valid primary still identifies and
# opens the volume, allowing the checker to classify the disagreement as unsafe.
backup_geometry = geometry(backup_path)
backup_offset = (
    backup_geometry['total_sectors'] * backup_geometry['sector_size']
)
if backup_offset + backup_geometry['sector_size'] > backup_path.stat().st_size:
    raise FixtureError('fixture backup boot sector is outside the image')
with backup_path.open('r+b') as handle:
    handle.seek(backup_offset + 3)
    original = handle.read(1)
    if not original:
        raise FixtureError('could not read fixture backup boot sector')
    handle.seek(backup_offset + 3)
    handle.write(bytes((original[0] ^ 0x5A,)))

# Leave the backup boot sector structurally valid but make it differ from the
# primary volume identity. Signature-only validation must not accept it.
backup_mismatch_geometry = geometry(backup_mismatch_path)
backup_mismatch_offset = (
    backup_mismatch_geometry['total_sectors']
    * backup_mismatch_geometry['sector_size']
)
with backup_mismatch_path.open('r+b') as handle:
    handle.seek(0)
    primary = handle.read(backup_mismatch_geometry['sector_size'])
    handle.seek(backup_mismatch_offset)
    backup = handle.read(backup_mismatch_geometry['sector_size'])
    if primary != backup:
        raise FixtureError('pristine primary and backup boot sectors differ')
    legacy_sector = (
        backup_mismatch_geometry['total_sectors']
        // backup_mismatch_geometry['sectors_per_cluster']
        // 2
        * backup_mismatch_geometry['sectors_per_cluster']
    )
    handle.seek(legacy_sector * backup_mismatch_geometry['sector_size'])
    legacy = handle.read(backup_mismatch_geometry['sector_size'])
    if legacy == primary:
        raise FixtureError('fixture unexpectedly has an exact legacy backup boot sector')
    handle.seek(backup_mismatch_offset + 72)
    original = handle.read(1)
    if not original:
        raise FixtureError('could not read fixture backup volume serial')
    handle.seek(backup_mismatch_offset + 72)
    handle.write(bytes((original[0] ^ 0x5A,)))
    handle.seek(backup_mismatch_offset)
    changed = handle.read(backup_mismatch_geometry['sector_size'])
    differences = [
        offset for offset, (left, right) in enumerate(zip(primary, changed))
        if left != right
    ]
    if differences != [72]:
        raise FixtureError(f'backup mismatch changed unexpected bytes: {differences}')
    if changed[3:11] != b'NTFS    ' or changed[510:512] != b'\x55\xaa':
        raise FixtureError('backup mismatch damaged structural boot markers')

# Break the update-sequence trailer of a non-critical file record. Required
# T1OS paths remain resolvable, then the complete MFT pass must detect this.
mft_geometry = geometry(mft_path)
mft_record_offset = (
    mft_geometry['mft_offset'] + mft_inode * mft_geometry['record_size']
)
with mft_path.open('r+b') as handle:
    raw = read_record(handle, mft_record_offset, mft_geometry['record_size'])
    usa_offset, usa_count = struct.unpack_from('<HH', raw, 4)
    if usa_count < 2 or usa_offset + usa_count * 2 > len(raw):
        raise FixtureError('invalid target MFT update-sequence array')
    trailer = mft_geometry['sector_size'] - 2
    raw[trailer] ^= 0x5A
    handle.seek(mft_record_offset)
    handle.write(raw)

# Give a non-critical directory's named $INDEX_ROOT an invalid (<512) index
# block size. The hardening pass must reject it without traversing unsafe nodes.
index_geometry = geometry(index_path)
index_record_offset = (
    index_geometry['mft_offset'] + index_inode * index_geometry['record_size']
)
with index_path.open('r+b') as handle:
    raw = read_record(handle, index_record_offset, index_geometry['record_size'])
    fixed = fixed_record(raw, index_geometry['sector_size'])
    value_offset, value_length = resident_attribute_position(fixed, 0x90, '$I30')
    if value_length < 16:
        raise FixtureError('fixture $INDEX_ROOT is too short')
    struct.pack_into('<I', raw, value_offset + 8, 256)
    handle.seek(index_record_offset)
    handle.write(raw)
PY

cp --reflink=auto --sparse=always "$dirty_image" "$boot_dirty_image"
cp --reflink=auto --sparse=always "$backup_boot_image" "$boot_backup_image"

validate_report() {
    report=$1
    expected_exit=$2
    expected_result=$3
    expected_required=$4
    expected_checked=$5
    expected_valid=$6
    expected_backup_checked=$7
    expected_backup_valid=$8
    expected_logfile_checked=$9
    expected_logfile_clean=${10}
    expected_dirty_checked=${11}
    expected_dirty=${12}

    python3 - "$report" "$expected_exit" "$expected_result" \
            "$expected_required" "$expected_checked" "$expected_valid" \
            "$expected_backup_checked" "$expected_backup_valid" \
            "$expected_logfile_checked" "$expected_logfile_clean" \
            "$expected_dirty_checked" "$expected_dirty" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys


report_path = Path(sys.argv[1])
expected_exit = int(sys.argv[2])
expected_result = sys.argv[3]


if not report_path.is_file() or report_path.stat().st_size == 0:
    raise SystemExit(f'checker report is missing or empty: {report_path}')
try:
    report = json.loads(report_path.read_text(encoding='utf-8'))
except (OSError, UnicodeError, json.JSONDecodeError) as error:
    raise SystemExit(f'checker report is not valid UTF-8 JSON: {error}')
if type(report) is not dict:
    raise SystemExit('checker report root must be an object')

required_keys = {
    'format', 'checker', 'checker_version', 'mode', 'result', 'exit_code',
    'device', 'identity', 'initial', 'repairs', 'commit', 'final', 'issues',
}
missing = sorted(required_keys.difference(report))
if missing:
    raise SystemExit(f'checker report keys are missing: {missing}')
if type(report['format']) is not int or report['format'] != 3:
    raise SystemExit('checker report format must be integer 3')
if report['checker'] != 'roothealth':
    raise SystemExit('checker report product identity differs')
if report['checker_version'] != '0.5.1':
    raise SystemExit('checker report version differs from the shipped product')
if report['mode'] != 'check':
    raise SystemExit('checker report mode must remain check')
if report['repairs'] not in ([], None):
    raise SystemExit('check-only report claims repairs')
for scan_name in ('initial', 'final'):
    scan = report.get(scan_name)
    if isinstance(scan, dict) and scan.get('completed') is True \
            and scan.get('read_only') is not True:
        raise SystemExit(f'{scan_name} scan did not attest read-only operation')
if expected_result == 'clean':
    initial = report.get('initial')
    if not isinstance(initial, dict) or initial.get('completed') is not True:
        raise SystemExit('clean report lacks a completed initial scan')
    if initial.get('coverage', {}).get('complete') is not True:
        raise SystemExit('clean report lacks complete census coverage')
    if initial.get('identity_valid') is not True:
        raise SystemExit('clean report lacks valid T1OS identity')
    if report.get('issues') not in ([], None):
        raise SystemExit('clean report contains issues')
if report['result'] != expected_result:
    raise SystemExit(
        f'checker report result differs: expected {expected_result!r}, '
        f'found {report["result"]!r}'
    )
if report['exit_code'] != expected_exit:
    raise SystemExit(
        f'checker report exit differs: expected {expected_exit}, '
        f'found {report["exit_code"]!r}'
    )
PY
}

run_case() {
    case_name=$1
    image=$2
    expected_exit=$3
    expected_result=$4
    expected_required=$5
    expected_checked=$6
    expected_valid=$7
    expected_backup_checked=$8
    expected_backup_valid=$9
    expected_logfile_checked=${10}
    expected_logfile_clean=${11}
    expected_dirty_checked=${12}
    expected_dirty=${13}
    report="$work/$case_name.json"
    transcript="$work/$case_name.log"

    before=$(sha256sum "$image" | awk '{print $1}')
    active_loop=$(losetup --find --show --read-only "$image")
    actual_read_only=$(blockdev --getro "$active_loop")
    if [ "$actual_read_only" != 1 ]; then
        echo "Fixture loop is not block-read-only for $case_name: $active_loop" >&2
        exit 1
    fi

    set +e
    timeout 120s "$checker" --check --require-t1os-root "${identity_args[@]}" --report "$report" \
        "$active_loop" >"$transcript" 2>&1
    actual_exit=$?
    set -e

    losetup --detach "$active_loop"
    active_loop=
    after=$(sha256sum "$image" | awk '{print $1}')
    if [ "$before" != "$after" ]; then
        echo "The checker changed the whole-image SHA-256 for $case_name." >&2
        exit 1
    fi
    if [ "$actual_exit" -ne "$expected_exit" ]; then
        echo "$case_name returned $actual_exit; expected $expected_exit." >&2
        sed -n '1,160p' "$transcript" >&2
        exit 1
    fi
    validate_report "$report" "$expected_exit" "$expected_result" \
        "$expected_required" "$expected_checked" "$expected_valid" \
        "$expected_backup_checked" "$expected_backup_valid" \
        "$expected_logfile_checked" "$expected_logfile_clean" \
        "$expected_dirty_checked" "$expected_dirty"
    if [ "$(stat -c %a "$report")" != 600 ]; then
        echo "Checker report permissions differ from 0600 for $case_name." >&2
        exit 1
    fi
    printf 'PASS %-24s exit=%s sha256=%s\n' \
        "$case_name" "$actual_exit" "$after"
}

run_preflight_case() {
    case_name=$1
    image=$2
    expected_exit=$3
    transcript="$work/preflight-$case_name.log"

    before=$(sha256sum "$image" | awk '{print $1}')
    active_loop=$(losetup --find --show --read-only "$image")
    set +e
    timeout 30s "$checker" --preflight --quiet --require-t1os-root \
        "${identity_args[@]}" "$active_loop" >"$transcript" 2>&1
    actual_exit=$?
    set -e
    losetup --detach "$active_loop"
    active_loop=
    after=$(sha256sum "$image" | awk '{print $1}')

    if [ "$before" != "$after" ]; then
        echo "RootHealth preflight changed the whole-image SHA-256 for $case_name." >&2
        exit 1
    fi
    if [ "$actual_exit" -ne "$expected_exit" ]; then
        echo "preflight-$case_name returned $actual_exit; expected $expected_exit." >&2
        sed -n '1,160p' "$transcript" >&2
        exit 1
    fi
    if [ "$case_name" = clean ] && [ -s "$transcript" ]; then
        echo 'Clean quiet preflight unexpectedly produced console output.' >&2
        sed -n '1,160p' "$transcript" >&2
        exit 1
    fi
    printf 'PASS preflight-%-14s exit=%s sha256=%s\n' \
        "$case_name" "$actual_exit" "$after"
}

run_preflight_case clean "$clean_image" 0
run_preflight_case ordinary-non-t1os "$ordinary_image" 4
run_preflight_case dirty "$dirty_image" 2
run_preflight_case backup-boot-corrupt "$backup_boot_image" 2

run_boot_repair_case() {
    case_name=$1
    image=$2
    expected_image=$3
    transcript="$work/boot-repair-$case_name.log"
    before=$(sha256sum "$image" | awk '{print $1}')
    expected=$(sha256sum "$expected_image" | awk '{print $1}')
    active_loop=$(losetup --find --show "$image")
    started_ns=$(date +%s%N)
    set +e
    timeout 8s "$checker" --boot-repair --quiet --require-t1os-root \
        "${identity_args[@]}" "$active_loop" >"$transcript" 2>&1
    actual_exit=$?
    set -e
    finished_ns=$(date +%s%N)
    elapsed_ms=$(( (finished_ns - started_ns) / 1000000 ))
    losetup --detach "$active_loop"
    active_loop=
    after=$(sha256sum "$image" | awk '{print $1}')

    if [ "$actual_exit" -ne 0 ]; then
        echo "boot-repair-$case_name returned $actual_exit; expected 0." >&2
        sed -n '1,160p' "$transcript" >&2
        exit 1
    fi
    if [ "$after" != "$expected" ]; then
        echo "boot-repair-$case_name did not produce the expected image." >&2
        echo "before=$before after=$after expected=$expected" >&2
        exit 1
    fi
    if [ "$elapsed_ms" -gt 2000 ]; then
        echo "boot-repair-$case_name took ${elapsed_ms}ms; budget is 2000ms." >&2
        exit 1
    fi
    if [ -s "$transcript" ]; then
        echo "Quiet boot repair produced console output for $case_name." >&2
        sed -n '1,160p' "$transcript" >&2
        exit 1
    fi
    printf 'PASS boot-repair-%-12s exit=%s elapsed_ms=%s sha256=%s\n' \
        "$case_name" "$actual_exit" "$elapsed_ms" "$after"
}

run_boot_repair_case clean "$clean_image" "$clean_image"
run_boot_repair_case dirty "$boot_dirty_image" "$clean_image"
run_boot_repair_case backup-boot "$boot_backup_image" "$clean_image"

run_case clean "$clean_image" 0 clean true true true true true true true true false
run_case ordinary-non-t1os "$ordinary_image" 4 wrong-root \
    true true false true true true true true false
run_case dirty "$dirty_image" 2 unsafe \
    true false null true true true true true true
run_case truncated "$truncated_image" 2 unsafe \
    true false null false null false null false null
run_case backup-boot-corrupt "$backup_boot_image" 2 unsafe \
    true false null true false false null true false
run_case backup-boot-mismatch "$backup_mismatch_image" 2 unsafe \
    true false null true false false null true false
run_case mft-fixup-corrupt "$mft_image" 2 unsafe \
    true false null true true true true true false
run_case index-root-corrupt "$index_image" 3 io-error \
    true false null true true true true true false
run_case dirty-non-t1os-precedence "$precedence_image" 4 wrong-root \
    true false null true true true true true true

writable_report="$work/writable-probe.json"
writable_trace="$work/writable-probe.strace"
writable_log="$work/writable-probe.log"
writable_before=$(sha256sum "$writable_probe_image" | awk '{print $1}')
active_loop=$(losetup --find --show "$writable_probe_image")
if [ "$(blockdev --getro "$active_loop")" != 0 ]; then
    echo "Writable checker probe unexpectedly received a read-only loop: $active_loop" >&2
    exit 1
fi
set +e
timeout 120s strace -f -qq -yy -o "$writable_trace" \
    -e trace=open,openat,openat2,write,writev,pwrite64,pwritev,pwritev2,\
ftruncate,fallocate,copy_file_range,splice,mmap \
    "$checker" --check --require-t1os-root "${identity_args[@]}" --report "$writable_report" \
    "$active_loop" >"$writable_log" 2>&1
writable_exit=$?
set -e
writable_device=$active_loop
losetup --detach "$active_loop"
active_loop=
writable_after=$(sha256sum "$writable_probe_image" | awk '{print $1}')
if [ "$writable_exit" -ne 0 ]; then
    echo "Writable checker probe returned $writable_exit; expected 0." >&2
    sed -n '1,160p' "$writable_log" >&2
    exit 1
fi
if [ "$writable_before" != "$writable_after" ]; then
    echo 'The checker changed the writable probe image.' >&2
    exit 1
fi
validate_report "$writable_report" 0 clean \
    true true true true true true true true false
python3 - "$writable_trace" "$writable_device" <<'PY'
from pathlib import Path
import re
import sys


trace = Path(sys.argv[1]).read_text(encoding='utf-8', errors='replace').splitlines()
device = sys.argv[2]
device_literal = f'"{device}"'
opens = [
    line for line in trace
    if device_literal in line and re.search(r'\bopen(?:at|at2)?\(', line)
]
if not opens:
    raise SystemExit(f'strace did not observe the checker opening {device}')
if any(
    'O_WRONLY' in line or 'O_RDWR' in line or 'O_TRUNC' in line
    for line in opens
):
    raise SystemExit(f'checker opened its target for writing: {opens!r}')
if not any('O_RDONLY' in line for line in opens):
    raise SystemExit(f'checker target open was not explicitly read-only: {opens!r}')
for line in trace:
    if re.search(
        r'\b(?:copy_file_range|fallocate|ftruncate|pwrite64|pwritev2?|splice|writev?)\(',
        line,
    ) and f'<{device}>' in line:
        raise SystemExit(f'checker attempted a target-device write: {line}')
    if (
        re.search(r'\bmmap\(', line)
        and f'<{device}>' in line
        and 'PROT_WRITE' in line
        and 'MAP_SHARED' in line
    ):
        raise SystemExit(f'checker mapped the target writable: {line}')
PY
printf 'PASS %-24s exit=%s sha256=%s\n' \
    writable-open-proof "$writable_exit" "$writable_after"

[ -c /dev/full ] || {
    echo '/dev/full is required to exercise report-path rejection.' >&2
    exit 1
}
existing_report="$work/existing-report.json"
symlink_target="$work/symlink-target.json"
symlink_report="$work/symlink-report.json"
printf '%s\n' existing-report-sentinel >"$existing_report"
printf '%s\n' symlink-target-sentinel >"$symlink_target"
ln -s "$symlink_target" "$symlink_report"
existing_report_before=$(sha256sum "$existing_report" | awk '{print $1}')
symlink_target_before=$(sha256sum "$symlink_target" | awk '{print $1}')
report_failure_before=$(sha256sum "$clean_image" | awk '{print $1}')
active_loop=$(losetup --find --show --read-only "$clean_image")
run_report_rejection() {
    case_name=$1
    report_path=$2
    report_log="$work/report-$case_name.log"
    set +e
    timeout 120s "$checker" --check --require-t1os-root "${identity_args[@]}" \
        --report "$report_path" "$active_loop" >"$report_log" 2>&1
    report_failure_exit=$?
    set -e
    if [ "$report_failure_exit" -ne 5 ]; then
        echo "Report rejection $case_name returned $report_failure_exit; expected 5." >&2
        sed -n '1,160p' "$report_log" >&2
        exit 1
    fi
    printf 'PASS %-24s exit=%s\n' "report-reject-$case_name" \
        "$report_failure_exit"
}
run_report_rejection dev-full /dev/full
run_report_rejection existing-file "$existing_report"
run_report_rejection final-symlink "$symlink_report"
postcreate_report="$work/postcreate-write-failure.json"
set +e
timeout 120s bash -c \
    'trap "" XFSZ; ulimit -f 0; exec "$@"' bash \
    "$checker" --check --require-t1os-root "${identity_args[@]}" --report "$postcreate_report" \
    "$active_loop" >/dev/null 2>&1
postcreate_exit=$?
set -e
if [ "$postcreate_exit" -ne 5 ]; then
    echo "Post-create report failure returned $postcreate_exit; expected 5." >&2
    exit 1
fi
if [ -e "$postcreate_report" ] || [ -L "$postcreate_report" ]; then
    echo 'The checker left an incomplete report after a write failure.' >&2
    exit 1
fi
printf 'PASS %-24s exit=%s\n' report-postcreate-failure "$postcreate_exit"
losetup --detach "$active_loop"
active_loop=
report_failure_after=$(sha256sum "$clean_image" | awk '{print $1}')
if [ "$report_failure_before" != "$report_failure_after" ]; then
    echo 'A rejected report path changed the target image.' >&2
    exit 1
fi
existing_report_after=$(sha256sum "$existing_report" | awk '{print $1}')
symlink_target_after=$(sha256sum "$symlink_target" | awk '{print $1}')
if [ "$existing_report_before" != "$existing_report_after" ]; then
    echo 'The checker overwrote an existing report file.' >&2
    exit 1
fi
if [ ! -L "$symlink_report" ] || \
        [ "$(readlink "$symlink_report")" != "$symlink_target" ] || \
        [ "$symlink_target_before" != "$symlink_target_after" ]; then
    echo 'The checker followed or replaced the report symlink.' >&2
    exit 1
fi
printf 'PASS %-24s exit=%s sha256=%s\n' \
    report-path-safety 5 "$report_failure_after"

for help_option in --help -h; do
    set +e
    help_output=$("$checker" "$help_option" 2>&1)
    help_exit=$?
    set -e
    if [ "$help_exit" -ne 0 ] || \
            ! printf '%s\n' "$help_output" | grep -Fqx 'roothealth v0.5.1' || \
            ! printf '%s\n' "$help_output" | grep -Fq -- '--preflight' || \
            ! printf '%s\n' "$help_output" | grep -Fq -- '--repair'; then
        echo "Checker help does not expose the v0.3 preflight and repair interfaces for $help_option." >&2
        printf '%s\n' "$help_output" >&2
        exit 1
    fi
done
for version_option in --version -V; do
    set +e
    version_output=$("$checker" "$version_option" 2>&1)
    version_exit=$?
    set -e
    if [ "$version_exit" -ne 0 ] || \
            ! printf '%s\n' "$version_output" | \
                grep -Fqx 'roothealth v0.5.1 (ntfs-next d4f481d)'; then
        echo "Checker version output differs for $version_option." >&2
        printf '%s\n' "$version_output" >&2
        exit 1
    fi
done
printf 'PASS %-24s exit=%s\n' product-help-version 0

invalid_cli_log="$work/invalid-cli.log"
set +e
"$checker" --check --not-a-roothealth-option \
    >"$invalid_cli_log" 2>&1
invalid_cli_exit=$?
set -e
if [ "$invalid_cli_exit" -ne 5 ]; then
    echo "Invalid CLI returned $invalid_cli_exit; expected 5." >&2
    sed -n '1,160p' "$invalid_cli_log" >&2
    exit 1
fi
printf 'PASS %-24s exit=%s\n' invalid-cli "$invalid_cli_exit"

echo 'roothealth read-only fixture validation passed.'
'@

$testScriptPath = Join-Path (
    [System.IO.Path]::GetTempPath()
) "t1os-test-ntfsck-$([guid]::NewGuid().ToString('N')).sh"
[System.IO.File]::WriteAllText(
    $testScriptPath,
    $testCommand,
    [System.Text.UTF8Encoding]::new($false)
)

$testExitCode = 1
try {
    $wslTestScript = ConvertTo-WslPath -WindowsPath $testScriptPath
    & wsl.exe -d Ubuntu -u root --exec bash $wslTestScript `
        $wslChecker $wslJournalValidator $wslNtfscp
    $testExitCode = $LASTEXITCODE
}
finally {
    if (Test-Path -LiteralPath $testScriptPath) {
        Remove-Item -LiteralPath $testScriptPath -Force
    }
}
if ($testExitCode -ne 0) {
    throw "roothealth fixture validation failed (exit code $testExitCode)."
}

Write-Host 'roothealth fixture validation passed.'
