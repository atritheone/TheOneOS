[CmdletBinding()]
param(
    [string]$BundlePath,

    [ValidateRange(2, 256)]
    [int[]]$TargetSizesGiB
)

$incrementalTestBootstrap = Join-Path $PSScriptRoot 'incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$version = (Get-Content -LiteralPath (
    Join-Path $projectRoot 'current_version.txt'
) -Raw).Trim()
$pythonManifest = Get-Content -LiteralPath (
    Join-Path $projectRoot 'source\software\python\manifest.json'
) -Raw | ConvertFrom-Json
$pythonRelease = [string]$pythonManifest.release
if ($pythonRelease -notmatch '^[0-9A-Za-z][0-9A-Za-z._+-]{0,127}$') {
    throw 'The canonical Python manifest has an invalid release identifier.'
}
if ([string]::IsNullOrWhiteSpace($BundlePath)) {
    $BundlePath = Join-Path (
        Join-Path $projectRoot 'environment\hardware'
    ) "The One OS $version.t1os"
}
$BundlePath = [System.IO.Path]::GetFullPath($BundlePath)
if (-not (Test-Path -LiteralPath $BundlePath -PathType Leaf)) {
    throw "T1OS bundle not found: $BundlePath"
}

$flashScript = Join-Path $PSScriptRoot 'flash hardware usb.ps1'
$journalValidatorPath = Join-Path $PSScriptRoot 'validate roothealth journal.py'
if (-not (Test-Path -LiteralPath $journalValidatorPath -PathType Leaf)) {
    throw "RootHealth journal validator not found: $journalValidatorPath"
}
$layoutJson = & pwsh -NoLogo -NoProfile -NonInteractive `
    -ExecutionPolicy Bypass `
    -File $flashScript `
    -InspectImage `
    -ImagePath $BundlePath
if ($LASTEXITCODE -ne 0) {
    throw 'The PowerShell flasher rejected the T1OS bundle.'
}
$layout = $layoutJson | ConvertFrom-Json
if (-not $layout.valid -or -not $layout.bundle) {
    throw 'The selected file did not inspect as a valid T1OS bundle.'
}
$journalValidatorHash = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $journalValidatorPath
).Hash.ToLowerInvariant()
$expectedJournal = $layout.roothealthJournal
if (
    $null -eq $expectedJournal -or
    [string]$expectedJournal.state -cne 'resize-preserved-and-validated' -or
    [string]$expectedJournal.path -cne '$Extend/$RootHealth' -or
    [int64]$expectedJournal.logical_bytes -ne 134217728 -or
    [string]$expectedJournal.required_flags -cne '0x00002007' -or
    [string]$expectedJournal.provenance.validator_sha256 -cne $journalValidatorHash
) {
    throw 'The inspected bundle lacks its source-bound RootHealth journal attestation.'
}
$expectedJournalBase64 = [System.Convert]::ToBase64String(
    [System.Text.Encoding]::UTF8.GetBytes(
        ($expectedJournal | ConvertTo-Json -Depth 12 -Compress)
    )
)

if (-not $TargetSizesGiB -or $TargetSizesGiB.Count -eq 0) {
    $minimumGiB = [int][math]::Ceiling([long]$layout.minimumTargetBytes / 1GB)
    $TargetSizesGiB = @($minimumGiB, [math]::Max(16, $minimumGiB + 8))
}
$TargetSizesGiB = @($TargetSizesGiB | Sort-Object -Unique)
if ($TargetSizesGiB.Count -lt 2) {
    throw 'Bundle validation requires at least two distinct target capacities.'
}
foreach ($targetSize in $TargetSizesGiB) {
    if (($targetSize * 1GB) -lt [long]$layout.minimumTargetBytes) {
        throw "The $targetSize GiB test target is smaller than the bundle minimum."
    }
}

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

$shell = @'
set -euo pipefail
export LC_ALL=C
export PYTHONDONTWRITEBYTECODE=1
trap 'status=$?; echo "T1OS bundle validation command failed at line $LINENO: $BASH_COMMAND" >&2; exit "$status"' ERR

bundle=$1
expected_version=$2
expected_label=$3
expected_uuid=$4
esp_bytes=$5
recovery_bytes=$6
recovery_partition_bytes=$7
root_bytes=$8
esp_hash=$9
recovery_hash=${10}
root_hash=${11}
expected_production=${12}
roothealth_journal_validator=${13}
roothealth_journal_validator_sha256=${14}
expected_journal_base64=${15}
expected_python_release=${16}
shift 16

for command_name in awk blkid blockdev cmp dd find fsck.vfat grep losetup mount.ntfs-3g ntfsfix ntfsresize python3 rm sgdisk sha256sum sort stat tr truncate umount; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "Required bundle-test command not installed: $command_name" >&2
        exit 127
    }
done

work=$(mktemp -d /tmp/t1os-bundle-test.XXXXXX)
loop=
root_mount="$work/root"
mounted=0
cleanup() {
    if [ "$mounted" = 1 ]; then
        umount "$root_mount" >/dev/null 2>&1 || true
    fi
    if [ -n "$loop" ]; then
        losetup -d "$loop" >/dev/null 2>&1 || true
    fi
    rm -rf -- "$work"
}
trap cleanup EXIT

validate_journal() {
    local target=$1
    local report=$2
    local stage=$3
    local hash_target=$4
    local before_hash=$5

    python3 -B "$roothealth_journal_validator" validate "$target" \
        --require-zero-entry-area --report "$report" >/dev/null
    python3 -B - "$report" "$expected_journal_base64" "$stage" <<'PY'
import base64
import hashlib
import json
from pathlib import Path
import sys

report_path = Path(sys.argv[1])
with report_path.open(encoding='utf-8') as handle:
    report = json.load(handle)
expected = json.loads(base64.b64decode(sys.argv[2], validate=True).decode('utf-8'))
stage = sys.argv[3]
journal = report['journal']
header = journal['header']
identity = {
    'volume_serial': report['device']['serial'],
    'journal_uuid': header['journal_uuid'],
    'mft_record': journal['mft_record'],
    'mft_sequence': journal['mft_sequence'],
    'logical_bytes': journal['logical_bytes'],
    'required_flags': '0x00002007',
}
identity_hash = hashlib.sha256(
    json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()
).hexdigest()
if report.get('state') != 'structurally-valid' or not all(report['checks'].values()):
    raise SystemExit(f'{stage} RootHealth journal validation is incomplete')
if identity_hash != expected.get('identity_sha256') or journal['run_count'] < 1:
    raise SystemExit(f'{stage} RootHealth identity or run profile changed')
if stage == 'compact' and journal['run_count'] != expected['resize_validation']['run_count']:
    raise SystemExit('compact RootHealth run count differs from its bundle attestation')
if any(journal[key] != '0x00002007' for key in (
    'standard_information_flags', 'file_name_flags',
    'extend_i30_file_name_flags', 'required_protected_flags',
)):
    raise SystemExit(f'{stage} RootHealth protected flags changed')
if not all(journal['ownership'].get(key) is True for key in (
    'complete', 'unique_owner', 'self_nonoverlap',
)):
    raise SystemExit(f'{stage} RootHealth ownership proof is incomplete')
if header['selected_generation'] != 2 or \
        [slot['generation'] for slot in header['slots']] != [1, 2] or \
        any(slot['state'] != 'EMPTY' for slot in header['slots']):
    raise SystemExit(f'{stage} RootHealth headers are not canonical EMPTY')
print(journal['run_count'])
PY
    local after_hash
    after_hash=$(sha256sum "$hash_target" | awk '{print $1}')
    [ "$after_hash" = "$before_hash" ]
}

python3 -B - "$bundle" "$work" <<'PY'
import pathlib
import sys
import zipfile

bundle = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
with zipfile.ZipFile(bundle, "r") as archive:
    names = archive.namelist()
    if names != ["manifest.json", "esp.img", "recovery.squashfs", "root.ntfs.img"]:
        raise SystemExit(f"unexpected bundle entries: {names!r}")
    for name in names:
        archive.extract(name, destination)
PY

[ "$(stat -c %s "$work/esp.img")" = "$esp_bytes" ]
[ "$(stat -c %s "$work/recovery.squashfs")" = "$recovery_bytes" ]
[ "$(stat -c %s "$work/root.ntfs.img")" = "$root_bytes" ]
[ "$(sha256sum "$work/esp.img" | awk '{print $1}')" = "$esp_hash" ]
[ "$(sha256sum "$work/recovery.squashfs" | awk '{print $1}')" = "$recovery_hash" ]
[ "$(sha256sum "$work/root.ntfs.img" | awk '{print $1}')" = "$root_hash" ]
printf '%s  %s\n' "$roothealth_journal_validator_sha256" "$roothealth_journal_validator" | sha256sum -c -
compact_root_hash=$(sha256sum "$work/root.ntfs.img" | awk '{print $1}')
compact_run_count=$(validate_journal \
    "$work/root.ntfs.img" "$work/compact-roothealth.json" compact \
    "$work/root.ntfs.img" "$compact_root_hash")

mkdir "$root_mount"
esp_sectors=$((esp_bytes / 512))
recovery_sectors=$((recovery_partition_bytes / 512))
for size_gib in "$@"; do
    disk="$work/target-${size_gib}.img"
    truncate -s "${size_gib}G" "$disk"
    sgdisk --zap-all "$disk" >/dev/null
    sgdisk \
        --new=1:2048:+${esp_sectors}S \
        --typecode=1:EF00 \
        --change-name=1:T1OS_EFI \
        --new=2:0:+${recovery_sectors}S \
        --typecode=2:8300 \
        --change-name=2:T1OS_RECOVERY \
        --new=3:0:0 \
        --typecode=3:0700 \
        --change-name=3:T1OS_ROOT \
        "$disk" >/dev/null
    sgdisk --verify "$disk" >/dev/null

    loop=$(losetup --find --show --partscan "$disk")
    esp_device="${loop}p1"
    recovery_device="${loop}p2"
    root_device="${loop}p3"
    test -b "$esp_device"
    test -b "$recovery_device"
    test -b "$root_device"
    [ "$(blockdev --getsize64 "$esp_device")" = "$esp_bytes" ]
    [ "$(blockdev --getsize64 "$recovery_device")" = "$recovery_partition_bytes" ]
    [ "$(blockdev --getsize64 "$root_device")" -ge "$root_bytes" ]

    dd if="$work/esp.img" of="$esp_device" bs=4M conv=notrunc status=none
    dd if="$work/recovery.squashfs" of="$recovery_device" bs=4M conv=notrunc status=none
    dd if="$work/root.ntfs.img" of="$root_device" bs=4M conv=notrunc status=none
    # With neither --size nor --expand, ntfsresize performs the conventional
    # end-of-device growth used here.  Its --expand option is a distinct
    # rebasing operation for space added at the beginning of a partition.
    ntfsresize --force --no-progress-bar "$root_device"
    ntfsfix --clear-dirty "$root_device" >/dev/null
    fsck.vfat -n "$esp_device" >/dev/null
    [ "$(head -c "$recovery_bytes" "$recovery_device" | sha256sum | awk '{print $1}')" = "$recovery_hash" ]
    ntfsresize --check --force --no-action "$root_device" >/dev/null
    [ "$(blkid -s UUID -o value "$root_device")" = "$expected_uuid" ]
    [ "$(blkid -s LABEL -o value "$root_device")" = "$expected_label" ]
    target_hash_before_journal=$(sha256sum "$disk" | awk '{print $1}')
    expanded_run_count=$(validate_journal \
        "$root_device" "$work/expanded-${size_gib}-roothealth.json" \
        "expanded-${size_gib}GiB" "$disk" "$target_hash_before_journal")

    mount.ntfs-3g -o ro "$root_device" "$root_mount"
    mounted=1
    test -s "$root_mount/the one/resources/t1os-drive.ico"
    test -f "$root_mount/the one/software/python/bin/python"
    test -f "$root_mount/the one/software/python/bin/python3.14"
    test -d "$root_mount/the one/software/python/lib/python3.14"
    test ! -d "$root_mount/the one/software/python/lib/python3.13"
    python3 -B - "$root_mount/the one/software/python/manifest.json" "$expected_python_release" <<'PY'
import json
from pathlib import Path
import sys

manifest = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
expected_release = sys.argv[2]
assert manifest['state'] == 'verified'
assert manifest['release'] == expected_release
assert manifest['python_version'] == '3.14.7'
assert manifest['python_abi'] == 'cp314'
PY
    tr -d '\r' < "$root_mount/autorun.inf" > "$work/autorun-normalized"
    grep -Fqx '[Autorun]' "$work/autorun-normalized"
    grep -Fqx 'Icon="the one\resources\t1os-drive.ico"' "$work/autorun-normalized"
    grep -Fqx "Label=$expected_label" "$work/autorun-normalized"
    printf '%s\n' \
        .ephemeral .remainder autorun.inf boot software 'the one' \
        > "$work/root-entries.expected"
    if [ "$expected_production" != True ]; then
        printf '%s\n' .rubbish >> "$work/root-entries.expected"
        if [ -e "$root_mount/master" ]; then
            printf '%s\n' master >> "$work/root-entries.expected"
        fi
    fi
    LC_ALL=C sort -o "$work/root-entries.expected" "$work/root-entries.expected"
    find "$root_mount" -mindepth 1 -maxdepth 1 -printf '%f\n' |
        LC_ALL=C sort > "$work/root-entries.actual"
    cmp "$work/root-entries.expected" "$work/root-entries.actual"
    expanded_root_bytes=$(blockdev --getsize64 "$root_device")
    umount "$root_mount"
    mounted=0
    losetup -d "$loop"
    loop=
    rm -f -- "$disk"
    printf 'Validated %s GiB target: root_bytes=%s label=%s version=%s journal_runs=%s compact_runs=%s\n' \
        "$size_gib" "$expanded_root_bytes" \
        "$expected_label" "$expected_version" \
        "$expanded_run_count" "$compact_run_count"
done
'@

# Keep the complete capacity test inside WSL instead of staging a script in
# Windows temporary storage. The trailing comment safely absorbs the native
# pipeline's final line ending.
$normalizedShell = $shell.Replace("`r", '') + "`n# end"
$normalizedShell | & wsl.exe -d Ubuntu -u root --exec bash -s -- (
    ConvertTo-WslPath -WindowsPath $BundlePath
) (
    [string]$layout.version
) (
    [string]$layout.volumeLabel
) (
    [string]$layout.rootUuid
) (
    [long]$layout.espBytes
) (
    [long]$layout.recoveryBytes
) (
    [long]$layout.recoveryPartitionBytes
) (
    [long]$layout.rootBytes
) (
    [string]$layout.espHash
) (
    [string]$layout.recoveryHash
) (
    [string]$layout.rootHash
) (
    [string][bool]$layout.production
) (
    ConvertTo-WslPath -WindowsPath $journalValidatorPath
) $journalValidatorHash $expectedJournalBase64 $pythonRelease @($TargetSizesGiB)
if ($LASTEXITCODE -ne 0) {
    throw "Capacity-independent bundle validation failed (exit code $LASTEXITCODE)."
}

Write-Host "T1OS bundle passed $($TargetSizesGiB.Count) target-capacity tests."
