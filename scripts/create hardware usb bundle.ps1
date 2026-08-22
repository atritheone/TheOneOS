[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$ImagePath,

    [string]$OutputPath,

    [ValidateRange(64, 2048)]
    [int]$GrowthReserveMiB = 256,

    [switch]$SkipImageValidation,

    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$hardwareRoot = Join-Path $projectRoot 'environment\hardware'
$journalValidatorPath = Join-Path $PSScriptRoot 'validate roothealth journal.py'

if ([string]::IsNullOrWhiteSpace($ImagePath)) {
    $ImagePath = Join-Path $hardwareRoot 't1os-hardware-usb.img'
}
$ImagePath = [System.IO.Path]::GetFullPath($ImagePath)
$imageManifestPath = "$ImagePath.json"

foreach ($requiredFile in @($ImagePath, $imageManifestPath, $journalValidatorPath)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required hardware USB bundle input not found: $requiredFile"
    }
}

$imageManifest = Get-Content -LiteralPath $imageManifestPath -Raw | ConvertFrom-Json
if ($imageManifest.state -cne 'validated') {
    throw 'The source hardware image manifest is not validated.'
}
if ([bool]$imageManifest.encrypted) {
    throw 'The Windows-native T1OS bundle requires an unencrypted NTFS root.'
}
if ([string]$imageManifest.root_filesystem -cne 'ntfs') {
    throw 'The source hardware image does not contain an NTFS root.'
}
if (
    [int]$imageManifest.format -lt 2 -or
    [string]$imageManifest.recovery_filesystem -cne 'squashfs-zstd' -or
    [string]$imageManifest.recovery_sha256 -notmatch '^[0-9a-f]{64}$' -or
    [int64]$imageManifest.recovery_bytes -le 4096 -or
    [int64]$imageManifest.recovery_bytes -gt 3GB
) {
    throw 'The source hardware image lacks a valid independent recovery payload.'
}
$sourceJournal = $imageManifest.roothealth_journal
$journalValidatorHash = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $journalValidatorPath
).Hash.ToLowerInvariant()
if (
    $null -eq $sourceJournal -or
    [string]$sourceJournal.state -cne 'provisioned-and-validated' -or
    [string]$sourceJournal.path -cne '$Extend/$RootHealth' -or
    [int64]$sourceJournal.logical_bytes -ne 134217728 -or
    [string]$sourceJournal.required_flags -cne '0x00002007' -or
    [string]$sourceJournal.headers.state -cne 'EMPTY' -or
    [string]$sourceJournal.provenance.validator_sha256 -cne $journalValidatorHash -or
    -not [bool]$sourceJournal.ownership.complete -or
    -not [bool]$sourceJournal.ownership.unique_owner -or
    -not [bool]$sourceJournal.ownership.self_nonoverlap
) {
    throw 'The source image lacks a complete source-bound RootHealth journal attestation.'
}
$sourceJournalBase64 = [System.Convert]::ToBase64String(
    [System.Text.Encoding]::UTF8.GetBytes(
        ($sourceJournal | ConvertTo-Json -Depth 12 -Compress)
    )
)

$version = ([string]$imageManifest.root_label -replace '^T1OS ', '').Trim()
if ($version -notmatch '^\d+(?:\.\d+)?$') {
    throw 'The source hardware image has an invalid version-derived root label.'
}

function Assert-HardwareOutputPath {
    param([Parameter(Mandatory)][string]$Path)

    $root = [System.IO.Path]::GetFullPath($hardwareRoot).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar
    )
    $candidate = [System.IO.Path]::GetFullPath($Path)
    $prefix = $root + [System.IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith(
        $prefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "T1OS bundle output must remain inside the hardware-artifact directory: $candidate"
    }

    $cursor = [System.IO.Path]::GetFullPath((Split-Path -Path $candidate -Parent))
    while ($true) {
        if (Test-Path -LiteralPath $cursor) {
            $ancestor = Get-Item -LiteralPath $cursor -Force
            if (-not $ancestor.PSIsContainer -or $ancestor.LinkType) {
                throw "T1OS bundle output has a redirected or non-directory ancestor: $cursor"
            }
        }
        if ($cursor.Equals($root, [System.StringComparison]::OrdinalIgnoreCase)) {
            break
        }
        $next = [System.IO.Path]::GetDirectoryName($cursor)
        if (-not $next -or -not $next.StartsWith(
            $root,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "T1OS bundle output escaped the hardware-artifact directory: $candidate"
        }
        $cursor = $next
    }
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $hardwareRoot "The One OS $version.t1os"
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
Assert-HardwareOutputPath -Path $OutputPath
if ([System.IO.Path]::GetExtension($OutputPath).ToLowerInvariant() -ne '.t1os') {
    throw 'The compact T1OS bundle output must end in .t1os.'
}
$outputVersionMatches = [regex]::Matches(
    [System.IO.Path]::GetFileNameWithoutExtension($OutputPath),
    '(?<![\d.])\d+\.\d+(?![\d.])'
)
if (
    $outputVersionMatches.Count -ne 1 -or
    $outputVersionMatches[0].Value -cne $version
) {
    throw "The bundle filename must contain the drive version $version exactly once."
}
if (Test-Path -LiteralPath $OutputPath) {
    $existingOutput = Get-Item -LiteralPath $OutputPath -Force
    if ($existingOutput.PSIsContainer -or $existingOutput.LinkType) {
        throw "T1OS bundle output is a directory or redirect: $OutputPath"
    }
    if (-not $Force) {
        throw "T1OS bundle already exists. Use -Force to replace it: $OutputPath"
    }
}
$partialPath = Join-Path (Split-Path -Path $OutputPath -Parent) (
    ".{0}.{1}.building" -f
        [System.IO.Path]::GetFileName($OutputPath),
        [guid]::NewGuid().ToString('N')
)

$actualImageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ImagePath).Hash.ToLowerInvariant()
if ($actualImageHash -cne ([string]$imageManifest.sha256).ToLowerInvariant()) {
    throw 'The source hardware image hash no longer matches its validated manifest.'
}

if (-not $SkipImageValidation) {
    & pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (
        Join-Path $PSScriptRoot 'validate hardware usb image.ps1'
    ) -ImagePath $ImagePath
    if ($LASTEXITCODE -ne 0) {
        throw 'The source hardware image failed validation before bundle creation.'
    }
}

if (-not $PSCmdlet.ShouldProcess(
    $OutputPath,
    "Create a compact capacity-independent T1OS $version USB installation bundle"
)) {
    return
}

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

function ConvertFrom-WslPath {
    param([Parameter(Mandatory)][string]$WslPath)

    $output = & wsl.exe -d Ubuntu --exec wslpath -w $WslPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate WSL path for Windows: $WslPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

$wslWorkPath = "/var/tmp/t1os-usb-bundle-$([guid]::NewGuid().ToString('N'))"

$shell = @'
set -euo pipefail
export LC_ALL=C
export PYTHONDONTWRITEBYTECODE=1
umask 022

image=$1
reserve_mib=$2
roothealth_journal_validator=$3
roothealth_journal_validator_sha256=$4
source_journal_base64=$5
expected_source_image_sha256=$6
expected_recovery_bytes=$7
expected_recovery_sha256=$8
work=$9
esp_output="$work/esp.img"
root_output="$work/root.ntfs.img"
recovery_output="$work/recovery.squashfs"
source_journal_report="${root_output}.source-roothealth.json"
resized_journal_report="${root_output}.resized-roothealth.json"

if [[ ! "$work" =~ ^/var/tmp/t1os-usb-bundle-[0-9a-f]{32}$ ]]; then
    echo "Refusing unexpected bundle work path: $work" >&2
    exit 1
fi

for command_name in awk blockdev blkid chmod cp cmp dd losetup mkdir ntfsclone ntfsfix ntfsresize rm sed sha256sum stat sync tail truncate; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "Required T1OS bundle command not installed: $command_name" >&2
        exit 127
    }
done

source_loop=
root_loop=
preserve_work=0
cleanup() {
    status=$?
    trap - EXIT HUP INT TERM
    [ -z "$root_loop" ] || losetup -d "$root_loop" >/dev/null 2>&1 || true
    [ -z "$source_loop" ] || losetup -d "$source_loop" >/dev/null 2>&1 || true
    if [ "$preserve_work" -eq 0 ]; then
        if [[ "$work" =~ ^/var/tmp/t1os-usb-bundle-[0-9a-f]{32}$ ]]; then
            rm -rf -- "$work"
        else
            status=1
        fi
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

rm -rf -- "$work"
mkdir -m 0755 -- "$work"
[ ! -L "$work" ]
[ "$(stat -c %u "$work")" = 0 ]
[ "$(stat -c %a "$work")" = 755 ]

source_loop=$(losetup --find --show --partscan --read-only "$image")
esp_device="${source_loop}p1"
recovery_device="${source_loop}p2"
root_device="${source_loop}p3"
[ -b "$esp_device" ] && [ -b "$recovery_device" ] && [ -b "$root_device" ] || {
    echo 'The source image partition devices did not appear.' >&2
    exit 1
}
printf '%s  %s\n' "$roothealth_journal_validator_sha256" "$roothealth_journal_validator" | sha256sum -c -
source_image_hash_before=$(sha256sum "$image" | awk '{print $1}')
[ "$source_image_hash_before" = "$expected_source_image_sha256" ]
python3 -B "$roothealth_journal_validator" validate "$root_device" \
    --require-one-run --require-zero-entry-area \
    --report "$source_journal_report"
python3 -B - \
    "$source_journal_report" "$source_journal_base64" <<'PY'
import base64
import hashlib
import json
from pathlib import Path
import sys

with Path(sys.argv[1]).open(encoding='utf-8') as handle:
    report = json.load(handle)
expected = json.loads(base64.b64decode(sys.argv[2], validate=True).decode('utf-8'))
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
    raise SystemExit('source RootHealth journal raw validation is incomplete')
if identity_hash != expected.get('identity_sha256') or journal['run_count'] != 1:
    raise SystemExit('source RootHealth journal identity or run profile changed')
if any(journal[key] != '0x00002007' for key in (
    'standard_information_flags', 'file_name_flags',
    'extend_i30_file_name_flags', 'required_protected_flags',
)):
    raise SystemExit('source RootHealth journal protected flags changed')
if not all(journal['ownership'].get(key) is True for key in (
    'complete', 'unique_owner', 'self_nonoverlap',
)):
    raise SystemExit('source RootHealth journal ownership proof is incomplete')
if header['selected_generation'] != 2 or \
        [slot['generation'] for slot in header['slots']] != [1, 2] or \
        any(slot['state'] != 'EMPTY' for slot in header['slots']):
    raise SystemExit('source RootHealth journal headers are not canonical EMPTY')
PY

esp_bytes=$(blockdev --getsize64 "$esp_device")
recovery_partition_bytes=$(blockdev --getsize64 "$recovery_device")
root_original_bytes=$(blockdev --getsize64 "$root_device")
[ "$esp_bytes" = 536870912 ] || {
    echo "The source EFI partition is not exactly 512 MiB: $esp_bytes" >&2
    exit 1
}
[ "$recovery_partition_bytes" = 3221225472 ]

dd if="$esp_device" of="$esp_output" bs=4M conv=sparse status=none
dd if="$recovery_device" of="$recovery_output" bs=1M \
    iflag=count_bytes count="$expected_recovery_bytes" status=none
[ "$(stat -c %s "$recovery_output")" = "$expected_recovery_bytes" ]
[ "$(sha256sum "$recovery_output" | awk '{print $1}')" = "$expected_recovery_sha256" ]
min_mb=$(
    ntfsresize --info-mb-only --force "$root_device" |
        sed -n 's/^Minsize (in MB):[[:space:]]*//p' |
        tail -n 1
)
case "$min_mb" in
    ''|*[!0-9]*) echo 'Could not determine the minimum NTFS payload size.' >&2; exit 1 ;;
esac

alignment=$((64 * 1024 * 1024))
reserve_bytes=$((reserve_mib * 1024 * 1024))
minimum_bytes=$((min_mb * 1000000))
root_bytes=$((minimum_bytes + reserve_bytes))
root_bytes=$((((root_bytes + alignment - 1) / alignment) * alignment))
if [ "$root_bytes" -gt "$root_original_bytes" ]; then
    root_bytes=$root_original_bytes
fi

ntfsclone --quiet --force --overwrite "$root_output" "$root_device"
losetup -d "$source_loop"
source_loop=

root_loop=$(losetup --find --show "$root_output")
ntfsresize --force --no-progress-bar --size "$root_bytes" "$root_loop"
ntfsfix --clear-dirty "$root_loop" >/dev/null
losetup -d "$root_loop"
root_loop=
truncate -s "$root_bytes" "$root_output"

root_loop=$(losetup --find --show --read-only "$root_output")
ntfsresize --check --force --no-action "$root_loop"
root_uuid=$(blkid -s UUID -o value "$root_loop")
root_label=$(blkid -s LABEL -o value "$root_loop")
root_hash_before_journal_check=$(sha256sum "$root_output" | awk '{print $1}')
python3 -B "$roothealth_journal_validator" validate "$root_loop" \
    --require-zero-entry-area \
    --report "$resized_journal_report"
root_hash_after_journal_check=$(sha256sum "$root_output" | awk '{print $1}')
[ "$root_hash_before_journal_check" = "$root_hash_after_journal_check" ]
resized_journal_base64=$(python3 -B - \
    "$resized_journal_report" "$source_journal_base64" <<'PY'
import base64
import hashlib
import json
from pathlib import Path
import sys

report_path = Path(sys.argv[1])
with report_path.open(encoding='utf-8') as handle:
    report = json.load(handle)
source = json.loads(base64.b64decode(sys.argv[2], validate=True).decode('utf-8'))
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
exclusion_hash = hashlib.sha256(
    json.dumps(journal['write_exclusion'], sort_keys=True, separators=(',', ':')).encode()
).hexdigest()
if report.get('state') != 'structurally-valid' or not all(report['checks'].values()):
    raise SystemExit('resized RootHealth journal raw validation is incomplete')
if identity_hash != source.get('identity_sha256') or journal['run_count'] < 1:
    raise SystemExit('resized RootHealth journal identity or run profile is invalid')
if any(journal[key] != '0x00002007' for key in (
    'standard_information_flags', 'file_name_flags',
    'extend_i30_file_name_flags', 'required_protected_flags',
)):
    raise SystemExit('resized RootHealth journal protected flags changed')
if not all(journal['ownership'].get(key) is True for key in (
    'complete', 'unique_owner', 'self_nonoverlap',
)):
    raise SystemExit('resized RootHealth journal ownership proof is incomplete')
if header['selected_generation'] != 2 or \
        [slot['generation'] for slot in header['slots']] != [1, 2] or \
        any(slot['state'] != 'EMPTY' for slot in header['slots']):
    raise SystemExit('resized RootHealth journal headers are not canonical EMPTY')
source['state'] = 'resize-preserved-and-validated'
source['run_policy'] = 'VALIDATED_AFTER_RESIZE'
source['resize_validation'] = {
    'report_sha256': hashlib.sha256(report_path.read_bytes()).hexdigest(),
    'run_count': journal['run_count'],
    'write_exclusion': {
        'range_count': sum(len(value) for value in journal['write_exclusion'].values()),
        'sha256': exclusion_hash,
    },
    'ownership': {
        'complete': journal['ownership']['complete'],
        'unique_owner': journal['ownership']['unique_owner'],
        'self_nonoverlap': journal['ownership']['self_nonoverlap'],
        'journal_clusters': journal['ownership']['journal_clusters'],
    },
    'headers': {
        'state': 'EMPTY',
        'selected_generation': header['selected_generation'],
        'slot_generations': [slot['generation'] for slot in header['slots']],
        'max_entry_count': header['max_entry_count'],
        'entry_area_zero_sha256': header['entry_area_zero_sha256'],
    },
}
encoded = json.dumps(source, sort_keys=True, separators=(',', ':')).encode()
print(base64.b64encode(encoded).decode('ascii'))
PY
)
losetup -d "$root_loop"
root_loop=
source_image_hash_after=$(sha256sum "$image" | awk '{print $1}')
[ "$source_image_hash_after" = "$source_image_hash_before" ]
rm -f -- \
    "$source_journal_report" \
    "$resized_journal_report"

chmod 0644 -- "$esp_output" "$root_output" "$recovery_output"
for payload in "$esp_output" "$root_output" "$recovery_output"; do
    [ -f "$payload" ] && [ ! -L "$payload" ]
    [ "$(stat -c %u "$payload")" = 0 ]
    [ "$(stat -c %a "$payload")" = 644 ]
done

esp_sha256=$(sha256sum "$esp_output" | awk '{print $1}')
root_sha256=$(sha256sum "$root_output" | awk '{print $1}')
sync -f "$esp_output" "$root_output" "$recovery_output"

printf 'ESP_BYTES=%s\n' "$esp_bytes"
printf 'RECOVERY_PARTITION_BYTES=%s\n' "$recovery_partition_bytes"
printf 'RECOVERY_BYTES=%s\n' "$expected_recovery_bytes"
printf 'RECOVERY_SHA256=%s\n' "$expected_recovery_sha256"
printf 'ROOT_BYTES=%s\n' "$root_bytes"
printf 'ROOT_UUID=%s\n' "$root_uuid"
printf 'ROOT_LABEL=%s\n' "$root_label"
printf 'ESP_SHA256=%s\n' "$esp_sha256"
printf 'ROOT_SHA256=%s\n' "$root_sha256"
printf 'ROOTHEALTH_JOURNAL_BASE64=%s\n' "$resized_journal_base64"
preserve_work=1
'@

$cleanupShell = @'
set -euo pipefail
work=$1
if [[ ! "$work" =~ ^/var/tmp/t1os-usb-bundle-[0-9a-f]{32}$ ]]; then
    echo "Refusing unexpected bundle cleanup path: $work" >&2
    exit 1
fi
rm -rf -- "$work"
'@

function Remove-WslBundleWork {
    param([Parameter(Mandatory)][string]$WorkPath)

    $normalizedCleanupShell = $cleanupShell.Replace("`r", '') + "`n# end"
    $normalizedCleanupShell |
        & wsl.exe -d Ubuntu -u root --exec bash -s -- $WorkPath
    if ($LASTEXITCODE -ne 0) {
        throw "T1OS bundle WSL cleanup failed (exit code $LASTEXITCODE): $WorkPath"
    }
}

$payloadResult = $null
$wslWorkReady = $false
$operationError = $null
$cleanupError = $null
$normalizedShell = $shell.Replace("`r", '') + "`n# end"
try {
    $payloadResult = $normalizedShell |
        & wsl.exe -d Ubuntu -u root --exec bash -s -- (
        ConvertTo-WslPath -WindowsPath $ImagePath
    ) $GrowthReserveMiB (
        ConvertTo-WslPath -WindowsPath $journalValidatorPath
    ) $journalValidatorHash $sourceJournalBase64 $actualImageHash (
        [int64]$imageManifest.recovery_bytes
    ) ([string]$imageManifest.recovery_sha256) $wslWorkPath
    if ($LASTEXITCODE -ne 0) {
        throw "T1OS bundle payload construction failed (exit code $LASTEXITCODE)."
    }
    $wslWorkReady = $true
    $workPath = ConvertFrom-WslPath -WslPath $wslWorkPath
    $espPayloadPath = Join-Path $workPath 'esp.img'
    $recoveryPayloadPath = Join-Path $workPath 'recovery.squashfs'
    $rootPayloadPath = Join-Path $workPath 'root.ntfs.img'

    $payloadValues = @{}
    foreach ($line in $payloadResult) {
        if ($line -match '^([A-Z0-9_]+)=(.*)$') {
            $payloadValues[$Matches[1]] = $Matches[2]
        }
        elseif ($line) {
            Write-Host $line
        }
    }
    foreach ($requiredValue in @(
        'ESP_BYTES', 'ROOT_BYTES', 'ROOT_UUID', 'ROOT_LABEL',
        'ESP_SHA256', 'ROOT_SHA256', 'ROOTHEALTH_JOURNAL_BASE64',
        'RECOVERY_PARTITION_BYTES', 'RECOVERY_BYTES', 'RECOVERY_SHA256'
    )) {
        if (-not $payloadValues.ContainsKey($requiredValue)) {
            throw "Bundle construction did not report $requiredValue."
        }
    }

    $espBytes = [long]$payloadValues.ESP_BYTES
    $rootBytes = [long]$payloadValues.ROOT_BYTES
    $recoveryPartitionBytes = [long]$payloadValues.RECOVERY_PARTITION_BYTES
    $recoveryBytes = [long]$payloadValues.RECOVERY_BYTES
    $rootUuid = [string]$payloadValues.ROOT_UUID
    $rootLabel = [string]$payloadValues.ROOT_LABEL
    if ($rootUuid -cne [string]$imageManifest.root_uuid) {
        throw 'The compact NTFS payload UUID differs from the validated source image.'
    }
    if ($rootLabel -cne [string]$imageManifest.root_label) {
        throw 'The compact NTFS payload label differs from the validated source image.'
    }
    if (
        (Get-Item -LiteralPath $espPayloadPath).Length -ne $espBytes -or
        (Get-Item -LiteralPath $rootPayloadPath).Length -ne $rootBytes -or
        (Get-Item -LiteralPath $recoveryPayloadPath).Length -ne $recoveryBytes -or
        $espBytes -ne 512MB -or
        $rootBytes -le 0 -or
        $rootBytes -gt [int64]$imageManifest.bytes -or
        [string]$payloadValues.ESP_SHA256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$payloadValues.ROOT_SHA256 -notmatch '^[0-9a-f]{64}$' -or
        $recoveryBytes -ne [int64]$imageManifest.recovery_bytes -or
        $recoveryPartitionBytes -ne 3GB -or
        [string]$payloadValues.RECOVERY_SHA256 -cne [string]$imageManifest.recovery_sha256
    ) {
        throw 'The staged bundle payload metadata is inconsistent.'
    }
    try {
        $bundleJournalBytes = [System.Convert]::FromBase64String(
            [string]$payloadValues.ROOTHEALTH_JOURNAL_BASE64
        )
        $bundleJournal = (
            [System.Text.Encoding]::UTF8.GetString($bundleJournalBytes)
        ) | ConvertFrom-Json
    }
    catch {
        throw "Bundle construction returned an invalid RootHealth journal attestation: $($_.Exception.Message)"
    }
    if (
        [string]$bundleJournal.state -cne 'resize-preserved-and-validated' -or
        [string]$bundleJournal.path -cne '$Extend/$RootHealth' -or
        [int64]$bundleJournal.logical_bytes -ne 134217728 -or
        [string]$bundleJournal.required_flags -cne '0x00002007' -or
        [int64]$bundleJournal.resize_validation.run_count -lt 1 -or
        -not [bool]$bundleJournal.resize_validation.ownership.complete -or
        -not [bool]$bundleJournal.resize_validation.ownership.unique_owner -or
        -not [bool]$bundleJournal.resize_validation.ownership.self_nonoverlap
    ) {
        throw 'Bundle construction returned an incomplete resized RootHealth journal attestation.'
    }

    $minimumTargetBytes = 1MB + $espBytes + $recoveryPartitionBytes + $rootBytes + 1MB
    $bundleManifest = [ordered]@{
        format = 't1os-usb-bundle'
        format_version = 2
        state = 'validated'
        version = $version
        drive_version = $version
        volume_label = [string]$imageManifest.root_label
        root_uuid = $rootUuid
        root_filesystem = 'ntfs'
        partition_table = 'gpt'
        windows_native_root = $true
        windows_autorun = 'autorun.inf'
        windows_drive_icon = 'the one\resources\system\drive logo.ico'
        minimum_target_bytes = $minimumTargetBytes
        source_image = [string]$imageManifest.image
        source_image_bytes = [long]$imageManifest.bytes
        source_image_sha256 = $actualImageHash
        production = [bool]$imageManifest.production
        secure_boot = [bool]$imageManifest.secure_boot
        kernel_release = [string]$imageManifest.kernel_release
        roothealth_journal = $bundleJournal
        esp = [ordered]@{
            entry = 'esp.img'
            bytes = $espBytes
            sha256 = ([string]$payloadValues.ESP_SHA256).ToLowerInvariant()
            filesystem = 'fat32'
            label = 'T1OS_EFI'
        }
        recovery = [ordered]@{
            entry = 'recovery.squashfs'
            bytes = $recoveryBytes
            partition_bytes = $recoveryPartitionBytes
            sha256 = ([string]$payloadValues.RECOVERY_SHA256).ToLowerInvariant()
            filesystem = 'squashfs-zstd'
            label = 'T1OS_RECOVERY'
        }
        root = [ordered]@{
            entry = 'root.ntfs.img'
            bytes = $rootBytes
            sha256 = ([string]$payloadValues.ROOT_SHA256).ToLowerInvariant()
            filesystem = 'ntfs'
            label = [string]$imageManifest.root_label
            uuid = $rootUuid
            growth_reserve_mib = $GrowthReserveMiB
        }
    }
    $manifestJson = $bundleManifest | ConvertTo-Json -Depth 8
    $manifestPayload = [System.Text.UTF8Encoding]::new($false).GetBytes(
        $manifestJson + [Environment]::NewLine
    )

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archiveStream = $null
    $archive = $null
    try {
        $archiveStream = [System.IO.FileStream]::new(
            $partialPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        $archive = [System.IO.Compression.ZipArchive]::new(
            $archiveStream,
            [System.IO.Compression.ZipArchiveMode]::Create,
            $false
        )

        Write-Host 'Compressing manifest.json...'
        $manifestEntry = $archive.CreateEntry(
            'manifest.json',
            [System.IO.Compression.CompressionLevel]::Optimal
        )
        $manifestStream = $manifestEntry.Open()
        try {
            $manifestStream.Write($manifestPayload, 0, $manifestPayload.Length)
        }
        finally {
            $manifestStream.Dispose()
        }

        foreach ($payload in @(
            [pscustomobject]@{ Path = $espPayloadPath; Entry = 'esp.img' },
            [pscustomobject]@{ Path = $recoveryPayloadPath; Entry = 'recovery.squashfs' },
            [pscustomobject]@{ Path = $rootPayloadPath; Entry = 'root.ntfs.img' }
        )) {
            Write-Host "Compressing $($payload.Entry)..."
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $archive,
                $payload.Path,
                $payload.Entry,
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
        }
    }
    finally {
        if ($archive) {
            $archive.Dispose()
        }
        if ($archiveStream) {
            $archiveStream.Dispose()
        }
    }

    if (-not (Test-Path -LiteralPath $partialPath -PathType Leaf)) {
        throw 'The compact T1OS bundle archive was not created.'
    }
    $partialBundle = Get-Item -LiteralPath $partialPath -Force
    if ($partialBundle.LinkType -or $partialBundle.Length -le 0) {
        throw 'The compact T1OS bundle archive is empty or redirected.'
    }
    $bundleHash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $partialPath
    ).Hash.ToLowerInvariant()
    Assert-HardwareOutputPath -Path $OutputPath
    if (Test-Path -LiteralPath $OutputPath) {
        $existingOutput = Get-Item -LiteralPath $OutputPath -Force
        if ($existingOutput.PSIsContainer -or $existingOutput.LinkType) {
            throw "T1OS bundle output became a directory or redirect: $OutputPath"
        }
    }
    Remove-WslBundleWork -WorkPath $wslWorkPath
    $wslWorkReady = $false
    [System.IO.File]::Move($partialPath, $OutputPath, [bool]$Force)
}
catch {
    $operationError = $_
}
finally {
    try {
        if (Test-Path -LiteralPath $partialPath) {
            Remove-Item -LiteralPath $partialPath -Force
        }
    }
    catch {
        $cleanupError = $_
    }

    if ($wslWorkReady) {
        try {
            Remove-WslBundleWork -WorkPath $wslWorkPath
        }
        catch {
            if (-not $cleanupError) {
                $cleanupError = $_
            }
        }
    }
}

if ($operationError) {
    if ($cleanupError) {
        Write-Warning "Bundle cleanup also failed: $($cleanupError.Exception.Message)"
    }
    throw $operationError
}
if ($cleanupError) {
    throw $cleanupError
}

$bundle = Get-Item -LiteralPath $OutputPath
Write-Host "Validated compact T1OS USB bundle: $OutputPath"
Write-Host "Bundle bytes: $($bundle.Length)"
Write-Host "Minimum target bytes: $minimumTargetBytes"
Write-Host "SHA-256: $bundleHash"
