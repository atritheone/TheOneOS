[CmdletBinding()]
param(
    [string]$ImagePath,

    [string]$PassphraseFile
)

$incrementalTestBootstrap = Join-Path $PSScriptRoot 'incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
if ([string]::IsNullOrWhiteSpace($ImagePath)) {
    $ImagePath = Join-Path $projectRoot 'environment\hardware\t1os-hardware-usb.img'
}
$ImagePath = [System.IO.Path]::GetFullPath($ImagePath)
$manifestPath = "$ImagePath.json"
$buildSourcePath = Join-Path $projectRoot 'source\build software'
$driversSourcePath = Join-Path $projectRoot 'source\drivers'
$chromiumSoftwarePath = Join-Path $projectRoot 'source\software\chromium'
$sourceRootImage = Join-Path $projectRoot 'environment\software\storage.img'
$hardwareRoot = Join-Path $projectRoot 'environment\hardware'
$kernelPath = Join-Path $hardwareRoot 'boot\vmlinuz-hardware'
$kernelReleasePath = Join-Path $hardwareRoot 'kernel-release.txt'
$initramfsPath = Join-Path $hardwareRoot 'boot\initramfs-hardware'
$modulesPath = Join-Path $hardwareRoot 'modules.tar.zst'
$firmwarePath = Join-Path $hardwareRoot 'firmware.tar.zst'
$firmwareManifestPath = Join-Path $hardwareRoot 't1os-firmware-manifest.json'
$graphicsCataloguePath = Join-Path $projectRoot 'source\catalogue\graphics\catalogue.json'
$compatibilityReportPath = Join-Path $hardwareRoot 'desktop-compatibility-report.json'
$moduleLoaderPath = Join-Path $projectRoot 'source\drivers\tools\modprobe'
$ntfsCheckerBuilderPath = Join-Path $projectRoot 'scripts\build\build roothealth.ps1'
$ntfsCheckerPath = Join-Path $hardwareRoot 'tools\roothealth'
$journalValidatorPath = Join-Path $PSScriptRoot 'validate roothealth journal.py'

if (-not (Test-Path -LiteralPath $ntfsCheckerBuilderPath -PathType Leaf)) {
    throw "roothealth builder not found: $ntfsCheckerBuilderPath"
}
& $ntfsCheckerBuilderPath
if (-not $?) {
    throw 'The roothealth build failed before image validation.'
}

foreach ($requiredFile in @(
    $ImagePath,
    $manifestPath,
    $sourceRootImage,
    $kernelPath,
    $kernelReleasePath,
    $initramfsPath,
    $modulesPath,
    $firmwarePath,
    $firmwareManifestPath,
    $graphicsCataloguePath,
    $compatibilityReportPath,
    $moduleLoaderPath,
    $ntfsCheckerPath,
    $journalValidatorPath
)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required image validation input not found: $requiredFile"
    }
}
foreach ($requiredDirectory in @($buildSourcePath, $driversSourcePath, $chromiumSoftwarePath)) {
    if (-not (Test-Path -LiteralPath $requiredDirectory -PathType Container)) {
        throw "Required source provenance directory not found: $requiredDirectory"
    }
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ImagePath).Hash.ToLowerInvariant()
if ($manifest.state -ne 'validated' -or $hash -ne ([string]$manifest.sha256).ToLowerInvariant()) {
    throw 'The sidecar manifest does not validate the image hash.'
}
if ([string]$manifest.root_filesystem -ne 'ntfs') {
    throw 'The sidecar manifest does not identify an NTFS root filesystem.'
}
if (
    [int]$manifest.format -lt 2 -or
    [string]$manifest.recovery_filesystem -cne 'squashfs-zstd' -or
    [string]$manifest.recovery_sha256 -notmatch '^[0-9a-f]{64}$' -or
    [int64]$manifest.recovery_bytes -le 4096 -or
    [int64]$manifest.recovery_bytes -gt 3GB -or
    [string]$manifest.esp_uuid -notmatch '^[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}$'
) {
    throw 'The sidecar manifest does not identify a valid independent recovery partition.'
}
$rootLabel = [string]$manifest.root_label
if ($rootLabel -notmatch '^T1OS \d+(?:\.\d+)?$' -or $rootLabel.Length -gt 32) {
    throw 'The sidecar manifest does not contain a valid version-derived NTFS root label.'
}
if ([bool]$manifest.windows_native_root -ne (-not [bool]$manifest.encrypted)) {
    throw 'The sidecar manifest Windows-native root state is inconsistent with encryption.'
}
if ([bool]$manifest.encrypted) {
    if ([string]::IsNullOrWhiteSpace($PassphraseFile)) {
        throw 'Encrypted image journal validation requires -PassphraseFile.'
    }
    $PassphraseFile = [System.IO.Path]::GetFullPath($PassphraseFile)
    if (-not (Test-Path -LiteralPath $PassphraseFile -PathType Leaf)) {
        throw "Encrypted image passphrase file not found: $PassphraseFile"
    }
}
$rootHealthJournal = $manifest.roothealth_journal
$journalValidatorHash = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $journalValidatorPath
).Hash.ToLowerInvariant()
if (
    $null -eq $rootHealthJournal -or
    [int]$rootHealthJournal.format -ne 1 -or
    [string]$rootHealthJournal.state -cne 'provisioned-and-validated' -or
    [string]$rootHealthJournal.path -cne '$Extend/$RootHealth' -or
    [int64]$rootHealthJournal.logical_bytes -ne 134217728 -or
    [string]$rootHealthJournal.required_flags -cne '0x00002007' -or
    [string]$rootHealthJournal.record_locator -cne "$($rootHealthJournal.mft_record):$($rootHealthJournal.mft_sequence)" -or
    [string]$rootHealthJournal.headers.state -cne 'EMPTY' -or
    [int64]$rootHealthJournal.headers.selected_generation -ne 2 -or
    [int64]$rootHealthJournal.headers.max_entry_count -ne 4096 -or
    [int64]$rootHealthJournal.provisioning_run_count -ne 1 -or
    -not [bool]$rootHealthJournal.ownership.complete -or
    -not [bool]$rootHealthJournal.ownership.unique_owner -or
    -not [bool]$rootHealthJournal.ownership.self_nonoverlap -or
    [string]$rootHealthJournal.provenance.validator_sha256 -cne $journalValidatorHash -or
    [string]$rootHealthJournal.provenance.ntfscp_binary_sha256 -notmatch '^[0-9a-f]{64}$' -or
    [string]$rootHealthJournal.provenance.ntfscp_manifest_sha256 -notmatch '^[0-9a-f]{64}$' -or
    [string]$rootHealthJournal.identity_sha256 -notmatch '^[0-9a-f]{64}$' -or
    [string]$rootHealthJournal.headers.entry_area_zero_sha256 -notmatch '^[0-9a-f]{64}$'
) {
    throw 'The sidecar lacks a complete source-bound RootHealth journal attestation.'
}
$journalManifestJson = $rootHealthJournal | ConvertTo-Json -Depth 12 -Compress
$journalManifestBase64 = [System.Convert]::ToBase64String(
    [System.Text.Encoding]::UTF8.GetBytes($journalManifestJson)
)
$preferredAudioCodec = ([string]$manifest.preferred_audio_codec).ToLowerInvariant()
if ($preferredAudioCodec -and $preferredAudioCodec -notmatch '^[0-9a-f]{8}$') {
    throw 'The sidecar manifest preferred audio codec is neither automatic nor a valid codec ID.'
}
$compatibilityHash = ([string]$manifest.desktop_compatibility_report_sha256).ToLowerInvariant()
if ($compatibilityHash -notmatch '^[0-9a-f]{64}$') {
    throw 'The sidecar manifest does not contain a valid desktop compatibility report hash.'
}
$actualCompatibilityHash = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $compatibilityReportPath
).Hash.ToLowerInvariant()
if ($actualCompatibilityHash -cne $compatibilityHash) {
    throw 'The sidecar desktop compatibility report hash does not match the current report.'
}
$buildSourceHash = ([string]$manifest.build_source_sha256).ToLowerInvariant()
$driversSourceHash = ([string]$manifest.drivers_source_sha256).ToLowerInvariant()
$chromiumSourceHash = ([string]$manifest.chromium_source_sha256).ToLowerInvariant()
$sourceRootHash = ([string]$manifest.source_root_sha256).ToLowerInvariant()
if (
    $buildSourceHash -notmatch '^[0-9a-f]{64}$' -or
    $driversSourceHash -notmatch '^[0-9a-f]{64}$' -or
    $chromiumSourceHash -notmatch '^[0-9a-f]{64}$' -or
    $sourceRootHash -notmatch '^[0-9a-f]{64}$'
) {
    throw 'The sidecar manifest does not contain valid source provenance hashes.'
}
$actualSourceRootHash = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $sourceRootImage
).Hash.ToLowerInvariant()
if ($actualSourceRootHash -cne $sourceRootHash) {
    throw 'The sidecar source storage hash does not match the current storage.img.'
}

foreach ($artifact in @(
    @{ Name = 'kernel'; Path = $kernelPath; Property = 'kernel_sha256' },
    @{ Name = 'initramfs'; Path = $initramfsPath; Property = 'initramfs_sha256' },
    @{ Name = 'modules archive'; Path = $modulesPath; Property = 'modules_sha256' },
    @{ Name = 'firmware archive'; Path = $firmwarePath; Property = 'firmware_sha256' }
)) {
    $expectedArtifactHash = ([string]$manifest.($artifact.Property)).ToLowerInvariant()
    $actualArtifactHash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $artifact.Path
    ).Hash.ToLowerInvariant()
    if (
        $expectedArtifactHash -notmatch '^[0-9a-f]{64}$' -or
        $actualArtifactHash -ne $expectedArtifactHash
    ) {
        throw "The sidecar $($artifact.Name) hash does not match the current hardware artifact."
    }
}

$kernelRelease = (Get-Content -LiteralPath $kernelReleasePath -Raw).Trim()
$sidecarKernelRelease = ([string]$manifest.kernel_release).Trim()
if (
    $kernelRelease -notmatch '^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$' -or
    $sidecarKernelRelease -cne $kernelRelease
) {
    throw 'The sidecar kernel release does not match the staged hardware kernel release.'
}
$nvidiaOpenDriverVersion = ([string]$manifest.nvidia_open_driver_version).Trim()
$nvidiaOpenDriverRunfileHash = (
    [string]$manifest.nvidia_open_driver_runfile_sha256
).Trim().ToLowerInvariant()
if (
    $nvidiaOpenDriverVersion -notmatch '^\d+(?:\.\d+)+$' -or
    $nvidiaOpenDriverRunfileHash -notmatch '^[0-9a-f]{64}$'
) {
    throw 'The sidecar manifest lacks valid NVIDIA open-driver version and runfile provenance.'
}
$graphicsCatalogueHash = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $graphicsCataloguePath
).Hash.ToLowerInvariant()
$firmwareManifestHash = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $firmwareManifestPath
).Hash.ToLowerInvariant()
if (
    ([string]$manifest.graphics_catalogue_sha256).Trim().ToLowerInvariant() -cne $graphicsCatalogueHash -or
    ([string]$manifest.firmware_manifest_sha256).Trim().ToLowerInvariant() -cne $firmwareManifestHash
) {
    throw 'The sidecar graphics or firmware manifest hash does not match the current NVIDIA stack artifacts.'
}
$moduleLoaderHash = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $moduleLoaderPath
).Hash.ToLowerInvariant()
if (
    ([string]$manifest.module_loader_sha256).Trim().ToLowerInvariant() -cne $moduleLoaderHash
) {
    throw 'The sidecar module-loader hash does not match the current T1OS loader.'
}
try {
    $graphicsCatalogue = Get-Content -LiteralPath $graphicsCataloguePath -Raw | ConvertFrom-Json
    $firmwareManifest = Get-Content -LiteralPath $firmwareManifestPath -Raw | ConvertFrom-Json
    $compatibilityReport = Get-Content -LiteralPath $compatibilityReportPath -Raw | ConvertFrom-Json
}
catch {
    throw "Could not parse current hardware provenance manifests: $($_.Exception.Message)"
}
$graphicsNvidiaVersion = ([string]$graphicsCatalogue.sources.nvidia_open_driver.version).Trim()
$graphicsNvidiaHash = (
    [string]$graphicsCatalogue.sources.nvidia_open_driver.runfile_sha256
).Trim().ToLowerInvariant()
$firmwareNvidiaVersion = ([string]$firmwareManifest.nvidia_open_driver_version).Trim()
$firmwareNvidiaHash = (
    [string]$firmwareManifest.nvidia_open_driver_archive_sha256
).Trim().ToLowerInvariant()
if (
    $graphicsCatalogue.state -ne 'ready' -or
    $graphicsCatalogue.profile -ne 'hardware' -or
    'nvidia-open' -notin @($graphicsCatalogue.drivers) -or
    'nvidia-nvdec-vaapi' -notin @($graphicsCatalogue.drivers) -or
    $graphicsNvidiaVersion -cne $nvidiaOpenDriverVersion -or
    $firmwareNvidiaVersion -cne $nvidiaOpenDriverVersion -or
    $graphicsNvidiaHash -cne $nvidiaOpenDriverRunfileHash -or
    $firmwareNvidiaHash -cne $nvidiaOpenDriverRunfileHash -or
    $compatibilityReport.state -ne 'ready' -or
    ([string]$compatibilityReport.kernel_release).Trim() -cne $kernelRelease -or
    ([string]$compatibilityReport.modules_archive_sha256).Trim().ToLowerInvariant() -cne ([string]$manifest.modules_sha256).Trim().ToLowerInvariant() -or
    ([string]$compatibilityReport.firmware_manifest_sha256).Trim().ToLowerInvariant() -cne $firmwareManifestHash -or
    ([string]$compatibilityReport.graphics_manifest_sha256).Trim().ToLowerInvariant() -cne $graphicsCatalogueHash -or
    ([string]$compatibilityReport.nvidia_open_driver.version).Trim() -cne $nvidiaOpenDriverVersion -or
    ([string]$compatibilityReport.nvidia_open_driver.runfile_sha256).Trim().ToLowerInvariant() -cne $nvidiaOpenDriverRunfileHash -or
    ([string]$compatibilityReport.nvidia_open_driver.kernel_module_version).Trim() -cne $nvidiaOpenDriverVersion
) {
    throw 'The current compatibility report, modules, firmware, and graphics userspace do not describe one exact NVIDIA open-driver release.'
}

$wslImageOutput = & wsl.exe -d Ubuntu --exec wslpath -a $ImagePath
$wslPathExitCode = $LASTEXITCODE
$wslImage = ([string]($wslImageOutput | Select-Object -First 1)).Trim()
if ($wslPathExitCode -ne 0 -or -not $wslImage) {
    throw 'Could not translate the image path for WSL.'
}
$wslBuildSourceOutput = & wsl.exe -d Ubuntu --exec wslpath -a $buildSourcePath
$wslBuildSourceExitCode = $LASTEXITCODE
$wslBuildSource = ([string]($wslBuildSourceOutput | Select-Object -First 1)).Trim()
if ($wslBuildSourceExitCode -ne 0 -or -not $wslBuildSource) {
    throw 'Could not translate the build source path for WSL.'
}
$wslDriversSourceOutput = & wsl.exe -d Ubuntu --exec wslpath -a $driversSourcePath
$wslDriversSourceExitCode = $LASTEXITCODE
$wslDriversSource = ([string]($wslDriversSourceOutput | Select-Object -First 1)).Trim()
if ($wslDriversSourceExitCode -ne 0 -or -not $wslDriversSource) {
    throw 'Could not translate the driver source path for WSL.'
}
$wslChromiumSourceOutput = & wsl.exe -d Ubuntu --exec wslpath -a $chromiumSoftwarePath
$wslChromiumSourceExitCode = $LASTEXITCODE
$wslChromiumSource = ([string]($wslChromiumSourceOutput | Select-Object -First 1)).Trim()
if ($wslChromiumSourceExitCode -ne 0 -or -not $wslChromiumSource) {
    throw 'Could not translate the Chromium runtime source path for WSL.'
}
$wslModulesOutput = & wsl.exe -d Ubuntu --exec wslpath -a $modulesPath
$wslModulesExitCode = $LASTEXITCODE
$wslModules = ([string]($wslModulesOutput | Select-Object -First 1)).Trim()
if ($wslModulesExitCode -ne 0 -or -not $wslModules) {
    throw 'Could not translate the module archive path for WSL.'
}
$wslFirmwareOutput = & wsl.exe -d Ubuntu --exec wslpath -a $firmwarePath
$wslFirmwareExitCode = $LASTEXITCODE
$wslFirmware = ([string]($wslFirmwareOutput | Select-Object -First 1)).Trim()
if ($wslFirmwareExitCode -ne 0 -or -not $wslFirmware) {
    throw 'Could not translate the firmware archive path for WSL.'
}
$wslGraphicsCatalogueOutput = & wsl.exe -d Ubuntu --exec wslpath -a $graphicsCataloguePath
$wslGraphicsCatalogueExitCode = $LASTEXITCODE
$wslGraphicsCatalogue = ([string](
    $wslGraphicsCatalogueOutput | Select-Object -First 1
)).Trim()
if ($wslGraphicsCatalogueExitCode -ne 0 -or -not $wslGraphicsCatalogue) {
    throw 'Could not translate the graphics catalogue path for WSL.'
}
$wslFirmwareManifestOutput = & wsl.exe -d Ubuntu --exec wslpath -a $firmwareManifestPath
$wslFirmwareManifestExitCode = $LASTEXITCODE
$wslFirmwareManifest = ([string](
    $wslFirmwareManifestOutput | Select-Object -First 1
)).Trim()
if ($wslFirmwareManifestExitCode -ne 0 -or -not $wslFirmwareManifest) {
    throw 'Could not translate the firmware manifest path for WSL.'
}
$wslNtfsCheckerOutput = & wsl.exe -d Ubuntu --exec wslpath -a $ntfsCheckerPath
$wslNtfsCheckerExitCode = $LASTEXITCODE
$wslNtfsChecker = ([string]($wslNtfsCheckerOutput | Select-Object -First 1)).Trim()
if ($wslNtfsCheckerExitCode -ne 0 -or -not $wslNtfsChecker) {
    throw 'Could not translate the roothealth path for WSL.'
}
$wslJournalValidatorOutput = & wsl.exe -d Ubuntu --exec wslpath -a $journalValidatorPath
$wslJournalValidatorExitCode = $LASTEXITCODE
$wslJournalValidator = ([string](
    $wslJournalValidatorOutput | Select-Object -First 1
)).Trim()
if ($wslJournalValidatorExitCode -ne 0 -or -not $wslJournalValidator) {
    throw 'Could not translate the RootHealth journal validator path for WSL.'
}
$wslPassphrase = '-'
if ([bool]$manifest.encrypted) {
    $wslPassphraseOutput = & wsl.exe -d Ubuntu --exec wslpath -a $PassphraseFile
    $wslPassphraseExitCode = $LASTEXITCODE
    $wslPassphrase = ([string]($wslPassphraseOutput | Select-Object -First 1)).Trim()
    if ($wslPassphraseExitCode -ne 0 -or -not $wslPassphrase) {
        throw 'Could not translate the encrypted image passphrase path for WSL.'
    }
}

$validateCommand = @'
set -euo pipefail
export LC_ALL=C
export PYTHONDONTWRITEBYTECODE=1
trap 'status=$?; echo "Hardware USB image validation command failed at line $LINENO: $BASH_COMMAND" >&2; exit "$status"' ERR
image=$1
expected_root_uuid=$2
encrypted=$3
secure_boot=$4
expected_audio_codec=$5
expected_compatibility_hash=$6
expected_root_label=$7
expected_build_source_hash=$8
expected_drivers_source_hash=$9
build_source=${10}
drivers_source=${11}
modules_archive=${12}
firmware_archive=${13}
expected_kernel_hash=${14}
expected_initramfs_hash=${15}
expected_kernel_release=${16}
graphics_catalogue=${17}
firmware_manifest=${18}
expected_graphics_catalogue_hash=${19}
expected_firmware_manifest_hash=${20}
expected_nvidia_version=${21}
expected_nvidia_runfile_hash=${22}
expected_production=${23}
chromium_source=${24}
expected_chromium_source_hash=${25}
expected_source_root_hash=${26}
ntfs_checker=${27}
roothealth_journal_validator=${28}
roothealth_journal_validator_sha256=${29}
roothealth_journal_base64=${30}
roothealth_report_validator="$(dirname "$roothealth_journal_validator")/roothealth-repair/validate-report.py"
passphrase=${31}
expected_image_sha256=${32}
expected_recovery_sha256=${33}
expected_recovery_bytes=${34}
expected_esp_uuid=${35}
work=/var/tmp/t1os-usb-validate
loop=
mounted=0
root_mounted=0
recovery_mounted=0
mapper_name=t1os-usb-validate-root
mapper_open=0
root_device=

stage_source_trees() {
    local expected_build=$1
    local expected_drivers=$2
    local unexpected_build_files

    if find "$build_source" "$drivers_source" -type l -print -quit | grep -q .; then
        echo 'Current build or driver source contains a forbidden symbolic link.' >&2
        find "$build_source" "$drivers_source" -type l -print | head -20 >&2
        exit 1
    fi

    mkdir -p "$expected_build" "$expected_drivers"
    rsync -r --delete \
        --exclude='__pycache__/' \
        --exclude='*.py[co]' \
        -- "$build_source"/ "$expected_build"/

    for legacy_windows_dir in windowserver "window server"; do
        if [ -e "$expected_build/windows" ] && [ -e "$expected_build/$legacy_windows_dir" ]; then
            echo "Both windows and $legacy_windows_dir exist in the current build source." >&2
            exit 1
        fi
        if [ -d "$expected_build/$legacy_windows_dir" ]; then
            mv "$expected_build/$legacy_windows_dir" "$expected_build/windows"
        fi
    done
    unexpected_build_files=$(find "$expected_build" -type f \
        ! -name '*.py' \
        ! -path "$expected_build/chromium/hardware diagnostics.json" \
        ! -path "$expected_build/chromium/google api credentials.example.json" \
        ! -path "$expected_build/python/tools.json" \
        ! -path "$expected_build/python/pip-*.whl" \
        ! -path "$expected_build/python/python-command" \
        -print)
    if [ -n "$unexpected_build_files" ]; then
        echo 'Current staged build contains an unexpected non-Python file:' >&2
        printf '%s\n' "$unexpected_build_files" >&2
        exit 1
    fi

    rsync -r --delete -- "$drivers_source"/ "$expected_drivers"/
    normalize_production_build_tree "$expected_build" "$expected_production"
}

normalize_production_build_tree() {
    local build_tree=$1
    local production_mode=$2

    case "$production_mode" in
        1|True) ;;
        0|False) return 0 ;;
        *)
            echo "Invalid production provenance mode: $production_mode" >&2
            exit 1
            ;;
    esac

    # Production preparation changes only these anchored Python debug
    # assignments. Apply the identical transformation to this disposable
    # expected tree so provenance remains exact for every other byte while
    # the checked-in source tree is never modified.
    python3 - "$build_tree" <<'PY'
import os
import re
import sys

build_root = sys.argv[1]
pattern = re.compile(
    r'^([ \t]*(?:DEBUG[A-Z0-9_]*|_DEBUG_[A-Z0-9_]*)[ \t]*=[ \t]*)True([ \t]*(?:#.*)?)$',
    re.MULTILINE,
)

for directory, subdirectories, filenames in os.walk(build_root):
    subdirectories.sort()
    for filename in sorted(filenames):
        if not filename.endswith('.py'):
            continue
        file_path = os.path.join(directory, filename)
        with open(file_path, 'r+', encoding='utf-8') as handle:
            original = handle.read()
            updated = pattern.sub(r'\1False\2', original)
            if updated == original:
                continue
            handle.seek(0)
            handle.write(updated)
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
PY
}

source_tree_sha256() {
    python3 - "$1" <<'PY'
import hashlib
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
for path in sorted(root.rglob('*'), key=lambda item: item.relative_to(root).as_posix()):
    relative = path.relative_to(root).as_posix().encode('utf-8')
    if path.is_symlink():
        raise SystemExit(f'provenance tree contains symbolic link: {path}')
    if path.is_dir():
        kind = b'd'
        payload = b''
    elif path.is_file():
        kind = b'f'
        file_digest = hashlib.sha256()
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                file_digest.update(chunk)
        payload = file_digest.digest()
    else:
        raise SystemExit(f'provenance tree contains unsupported entry: {path}')
    digest.update(kind)
    digest.update(len(relative).to_bytes(8, 'big'))
    digest.update(relative)
    digest.update(payload)
print(digest.hexdigest())
PY
}

verify_deployed_sources() {
    local deployed_root=$1
    local deployed_build="$deployed_root/the one/build"
    local deployed_drivers="$deployed_root/the one/drivers"
    local deployed_chromium="$deployed_root/the one/software/chromium"
    local build_differences
    local driver_differences
    local chromium_source_sha256
    local relative

    build_differences=$(rsync -r --checksum --delete --itemize-changes --dry-run \
        --exclude='__pycache__/' \
        --exclude='*.py[co]' \
        -- "$expected_build"/ "$deployed_build"/)
    if [ -n "$build_differences" ]; then
        echo 'Final USB build provenance differs from current source:' >&2
        printf '%s\n' "$build_differences" >&2
        exit 1
    fi

    driver_differences=$(rsync -r --checksum --delete --itemize-changes --dry-run \
        --exclude='/modules/' \
        --exclude='/firmware/' \
        --exclude='/nodes/' \
        --exclude='/state/' \
        --exclude='/control/' \
        --exclude='/processes/' \
        -- "$expected_drivers"/ "$deployed_drivers"/)
    if [ -n "$driver_differences" ]; then
        echo 'Final USB driver-runtime provenance differs from current source:' >&2
        printf '%s\n' "$driver_differences" >&2
        exit 1
    fi

    chromium_source_sha256=$(source_tree_sha256 "$deployed_chromium")
    if [ "$chromium_source_sha256" != "$expected_chromium_source_hash" ]; then
        echo 'Final USB Chromium runtime provenance differs from current source:' >&2
        echo "expected: $expected_chromium_source_hash" >&2
        echo "deployed: $chromium_source_sha256" >&2
        exit 1
    fi

    for relative in \
        'GODDESS/GODDESS.py' \
        'graphics/graphics.py' \
        'windows/windowserver.py' \
        'startup/startup.py' \
        'lock screen/lock screen.py' \
        'drivers/driverserver.py'; do
        test -s "$expected_build/$relative"
        if ! cmp -s -- "$expected_build/$relative" "$deployed_build/$relative"; then
            echo "Final USB critical build file differs from current source: $relative" >&2
            exit 1
        fi
    done
    if ! cmp -s -- "$expected_drivers/tools/modprobe" "$deployed_drivers/tools/modprobe"; then
        echo 'Final USB module loader differs from current source: tools/modprobe' >&2
        exit 1
    fi
}

cleanup() {
    status=$?
    cleanup_failed=0
    set +e
    trap - EXIT ERR HUP INT TERM
    if [ "$root_mounted" != 0 ]; then
        if umount "$work/root"; then root_mounted=0; else cleanup_failed=1; fi
    fi
    if [ "$recovery_mounted" != 0 ]; then
        if umount "$work/recovery"; then recovery_mounted=0; else cleanup_failed=1; fi
    fi
    if [ "$mapper_open" != 0 ]; then
        if cryptsetup close "$mapper_name"; then mapper_open=0; else cleanup_failed=1; fi
    fi
    if [ "$mounted" != 0 ]; then
        if umount "$work/esp"; then mounted=0; else cleanup_failed=1; fi
    fi
    if [ -n "$loop" ]; then
        if losetup -d "$loop"; then loop=; else cleanup_failed=1; fi
    fi
    if [ "$root_mounted" = 0 ] && [ "$recovery_mounted" = 0 ] && [ "$mounted" = 0 ]; then
        rm -rf -- "$work" || cleanup_failed=1
    else
        cleanup_failed=1
        echo "USB image validation left a mounted work tree at $work." >&2
    fi
    if [ "$cleanup_failed" -ne 0 ] && [ "$status" -eq 0 ]; then
        status=1
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

rm -rf -- "$work"
mkdir -p "$work/esp" "$work/recovery" "$work/root"
test -f "$roothealth_report_validator"
command -v unsquashfs >/dev/null 2>&1 || {
    echo 'unsquashfs is required to validate the zstd recovery payload.' >&2
    exit 127
}
printf '%s  %s\n' "$roothealth_journal_validator_sha256" "$roothealth_journal_validator" | sha256sum -c -
image_hash_before=$(sha256sum "$image" | awk '{print $1}')
[ "$image_hash_before" = "$expected_image_sha256" ]
expected_build="$work/expected-build"
expected_drivers="$work/expected-drivers"
stage_source_trees "$expected_build" "$expected_drivers"
actual_build_source_hash=$(source_tree_sha256 "$expected_build")
actual_drivers_source_hash=$(source_tree_sha256 "$expected_drivers")
actual_chromium_source_hash=$(source_tree_sha256 "$chromium_source")
[ "$actual_build_source_hash" = "$expected_build_source_hash" ] || {
    echo 'Sidecar build provenance hash does not match the current source tree.' >&2
    echo "expected: $expected_build_source_hash" >&2
    echo "current:  $actual_build_source_hash" >&2
    exit 1
}
[ "$actual_drivers_source_hash" = "$expected_drivers_source_hash" ] || {
    echo 'Sidecar driver provenance hash does not match the current source tree.' >&2
    echo "expected: $expected_drivers_source_hash" >&2
    echo "current:  $actual_drivers_source_hash" >&2
    exit 1
}
[ "$actual_chromium_source_hash" = "$expected_chromium_source_hash" ] || {
    echo 'Sidecar Chromium runtime provenance hash does not match the current source tree.' >&2
    echo "expected: $expected_chromium_source_hash" >&2
    echo "current:  $actual_chromium_source_hash" >&2
    exit 1
}
sgdisk --verify "$image"
loop=$(losetup --find --show --read-only --partscan "$image")
for unused in 1 2 3 4 5; do
    [ -b "${loop}p1" ] && [ -b "${loop}p2" ] && [ -b "${loop}p3" ] && break
    sleep 1
done
[ -b "${loop}p1" ] && [ -b "${loop}p2" ] && [ -b "${loop}p3" ]
[ "$(blockdev --getro "$loop")" = 1 ]
fsck.vfat -n "${loop}p1"
[ "$(blockdev --getsize64 "${loop}p2")" = 3221225472 ]
sgdisk --info=2 "$loop" | grep -Fiq '0FC63DAF-8483-4772-8E79-3D69D8477DE4'
actual_recovery_sha256=$(head -c "$expected_recovery_bytes" "${loop}p2" | sha256sum | awk '{print $1}')
[ "$actual_recovery_sha256" = "$expected_recovery_sha256" ]
dd if="${loop}p2" of="$work/recovery.squashfs" bs=1M \
    iflag=count_bytes count="$expected_recovery_bytes" status=none
[ "$(sha256sum "$work/recovery.squashfs" | awk '{print $1}')" = "$expected_recovery_sha256" ]
rm -rf -- "$work/recovery"
unsquashfs -no-progress -d "$work/recovery" "$work/recovery.squashfs" >/dev/null
test -s "$work/recovery/the one/settings/recovery/files.tsv"
awk -F '\t' 'NR == 1 { valid = ($1 == "H" && $2 == "1") } END { exit valid && NR > 10 ? 0 : 1 }' \
    "$work/recovery/the one/settings/recovery/files.tsv"
mount -o ro "${loop}p1" "$work/esp"
mounted=1
test -s "$work/esp/EFI/BOOT/BOOTX64.EFI"
test -s "$work/esp/boot/vmlinuz-hardware"
test -s "$work/esp/boot/initramfs-hardware"
printf '%s  %s\n' "$expected_kernel_hash" "$work/esp/boot/vmlinuz-hardware" | sha256sum -c -
printf '%s  %s\n' "$expected_initramfs_hash" "$work/esp/boot/initramfs-hardware" | sha256sum -c -
kernel_description=$(file -b "$work/esp/boot/vmlinuz-hardware")
case "$kernel_description" in
    *"version $expected_kernel_release "*) ;;
    *)
        echo "USB kernel does not identify the expected module release: $expected_kernel_release" >&2
        echo "$kernel_description" >&2
        exit 1
        ;;
esac
test -s "$work/esp/boot/grub/grub.cfg"
test -s "$work/esp/boot/grub/t1os-theme.txt"
test -s "$work/esp/boot/grub/t1os-black.png"
test -s "$work/esp/T1OS/image-manifest.json"
test -s "$work/esp/T1OS/desktop-compatibility-report.json"
printf '%s  %s\n' "$expected_compatibility_hash" "$work/esp/T1OS/desktop-compatibility-report.json" | sha256sum -c -
python3 - "$work/esp/T1OS/image-manifest.json" "$expected_audio_codec" "$expected_compatibility_hash" "$expected_root_label" "$expected_build_source_hash" "$expected_drivers_source_hash" "$expected_kernel_release" "$expected_graphics_catalogue_hash" "$expected_firmware_manifest_hash" "$expected_nvidia_version" "$expected_nvidia_runfile_hash" "$expected_chromium_source_hash" "$expected_source_root_hash" "$expected_recovery_sha256" "$expected_recovery_bytes" "$expected_esp_uuid" <<'PY'
import json
import sys
with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    manifest = json.load(handle)
if manifest.get('preferred_audio_codec') != (sys.argv[2] or None):
    raise SystemExit('ESP manifest preferred audio codec mismatch')
if manifest.get('desktop_compatibility_report_sha256') != sys.argv[3]:
    raise SystemExit('ESP manifest desktop compatibility hash mismatch')
if manifest.get('root_filesystem') != 'ntfs':
    raise SystemExit('ESP manifest does not identify an NTFS root')
if manifest.get('root_label') != sys.argv[4]:
    raise SystemExit('ESP manifest NTFS root label mismatch')
if manifest.get('windows_native_root') != (not manifest.get('encrypted')):
    raise SystemExit('ESP manifest Windows-native root state is inconsistent with encryption')
if manifest.get('build_source_sha256') != sys.argv[5]:
    raise SystemExit('ESP manifest build provenance hash mismatch')
if manifest.get('drivers_source_sha256') != sys.argv[6]:
    raise SystemExit('ESP manifest driver provenance hash mismatch')
if manifest.get('kernel_release') != sys.argv[7]:
    raise SystemExit('ESP manifest kernel release mismatch')
if manifest.get('graphics_catalogue_sha256') != sys.argv[8]:
    raise SystemExit('ESP manifest graphics catalogue hash mismatch')
if manifest.get('firmware_manifest_sha256') != sys.argv[9]:
    raise SystemExit('ESP manifest firmware manifest hash mismatch')
if manifest.get('nvidia_open_driver_version') != sys.argv[10]:
    raise SystemExit('ESP manifest NVIDIA open-driver version mismatch')
if manifest.get('nvidia_open_driver_runfile_sha256') != sys.argv[11]:
    raise SystemExit('ESP manifest NVIDIA runfile hash mismatch')
if manifest.get('chromium_source_sha256') != sys.argv[12]:
    raise SystemExit('ESP manifest Chromium runtime provenance hash mismatch')
if manifest.get('source_root_sha256') != sys.argv[13]:
    raise SystemExit('ESP manifest source storage hash mismatch')
if manifest.get('format') != 2 or manifest.get('recovery_filesystem') != 'squashfs-zstd':
    raise SystemExit('ESP manifest recovery format mismatch')
if manifest.get('recovery_sha256') != sys.argv[14] or manifest.get('recovery_bytes') != int(sys.argv[15]):
    raise SystemExit('ESP manifest recovery identity mismatch')
if manifest.get('esp_uuid') != sys.argv[16]:
    raise SystemExit('ESP manifest boot filesystem identity mismatch')
PY
if grep -q '@T1OS_' "$work/esp/boot/grub/grub.cfg"; then
    echo 'USB GRUB configuration retains an unexpanded T1OS placeholder.' >&2
    exit 1
fi
if [ "$encrypted" = True ]; then
    grep -Fq 'root=/dev/mapper/t1os-root' "$work/esp/boot/grub/grub.cfg"
    grep -Fq 't1os.luks.name=t1os-root' "$work/esp/boot/grub/grub.cfg"
else
    grep -Fq "root=UUID=$expected_root_uuid" "$work/esp/boot/grub/grub.cfg"
fi
grep -Fq 't1os.recoverypart=SCAN' "$work/esp/boot/grub/grub.cfg"
grep -Fq "t1os.esppart=UUID=$expected_esp_uuid" "$work/esp/boot/grub/grub.cfg"
grep -Fq "t1os.recovery.sha256=$expected_recovery_sha256" "$work/esp/boot/grub/grub.cfg"
grep -Fq "t1os.recovery.bytes=$expected_recovery_bytes" "$work/esp/boot/grub/grub.cfg"
grep -Fq 'rootfstype=ntfs3' "$work/esp/boot/grub/grub.cfg"
grep -Fqx 'set timeout_style=menu' "$work/esp/boot/grub/grub.cfg"
grep -Fqx 'set timeout=5' "$work/esp/boot/grub/grub.cfg"
grep -Fq 'title-text: "The One OS"' "$work/esp/boot/grub/t1os-theme.txt"
grep -Fq 'desktop-image: "t1os-black.png"' "$work/esp/boot/grub/t1os-theme.txt"
grep -Fq 'desktop-color: "#000000"' "$work/esp/boot/grub/t1os-theme.txt"
grep -Fq 'terminal-border: "0"' "$work/esp/boot/grub/t1os-theme.txt"
grep -Fq 'text = "booting in %d..."' "$work/esp/boot/grub/t1os-theme.txt"
[ "$(grep -Ec '^menuentry "(boot|safe mode|recovery)"' "$work/esp/boot/grub/grub.cfg")" = 3 ]
if grep -Eq '^menuentry "[^"]*T1OS' "$work/esp/boot/grub/grub.cfg"; then
    echo 'USB GRUB menu entry exposes the internal T1OS name.' >&2
    exit 1
fi
boot_entry=$(sed -n '/^menuentry "boot"/,/^}/p' "$work/esp/boot/grub/grub.cfg")
printf '%s\n' "$boot_entry" | grep -Fq 't1os.graphics=auto'
printf '%s\n' "$boot_entry" | grep -Fq 't1os.quiet=1'
printf '%s\n' "$boot_entry" | grep -Fq 'nvidia_drm.modeset=1'
printf '%s\n' "$boot_entry" | grep -Fq 'nvidia_drm.fbdev=1'
printf '%s\n' "$boot_entry" | grep -Fq 'nouveau.config=NvGspFw=0'
printf '%s\n' "$boot_entry" | grep -Fq 'console=ttyS0,115200n8 quiet loglevel=0 logo.nologo'
if printf '%s\n' "$boot_entry" | grep -Fq 'console=tty0'; then
    echo 'Normal USB boot unexpectedly enables the local text console.' >&2
    exit 1
fi
safe_entry=$(sed -n '/^menuentry "safe mode"/,/^}/p' "$work/esp/boot/grub/grub.cfg")
printf '%s\n' "$safe_entry" | grep -Fq 't1os.graphics=framebuffer'
printf '%s\n' "$safe_entry" | grep -Fq 'module_blacklist=amdgpu,radeon,nouveau'
printf '%s\n' "$safe_entry" | grep -Fq 'nvidia,nvidia_modeset,nvidia_drm'
grub-script-check "$work/esp/boot/grub/grub.cfg"

if [ "$encrypted" = True ]; then
    command -v cryptsetup >/dev/null 2>&1
    sgdisk --info=3 "$loop" | grep -Fiq 'CA7D7CCB-63ED-4C53-861C-1742536059CC'
    cryptsetup isLuks "${loop}p3"
    cryptsetup open --readonly --type luks --key-file "$passphrase" \
        "${loop}p3" "$mapper_name"
    mapper_open=1
    root_device="/dev/mapper/$mapper_name"
    [ "$(blkid -s TYPE -o value "$root_device")" = ntfs ]
    [ "$(blkid -s LABEL -o value "$root_device")" = "$expected_root_label" ]
    actual_root_uuid=$(blkid -s UUID -o value "$root_device")
    [ "$actual_root_uuid" = "$expected_root_uuid" ]
else
    sgdisk --info=3 "$loop" | grep -Fiq 'EBD0A0A2-B9E5-4433-87C0-68B6B72699C7'
    [ "$(blkid -s TYPE -o value "${loop}p3")" = ntfs ]
    [ "$(blkid -s LABEL -o value "${loop}p3")" = "$expected_root_label" ]
    actual_root_uuid=$(blkid -s UUID -o value "${loop}p3")
    [ "$actual_root_uuid" = "$expected_root_uuid" ]
    root_device="${loop}p3"
    mapfile -t expected_roothealth_identity < <(
        python3 -B - "$roothealth_journal_base64" <<'PY'
import base64
import json
import sys

expected = json.loads(base64.b64decode(sys.argv[1], validate=True).decode('utf-8'))
serial = expected.get('volume_serial')
if isinstance(serial, str):
    serial = serial.lower()
    if not serial.startswith('0x'):
        serial = '0x' + serial
values = (
    serial,
    expected.get('journal_uuid'),
    expected.get('record_locator'),
)
if not all(isinstance(value, str) and value for value in values):
    raise SystemExit('RootHealth journal attestation lacks its expected identity')
print(*values, sep='\n')
PY
    )
    [ "${#expected_roothealth_identity[@]}" = 3 ]
    image_hash_before_ntfs_check=$(sha256sum "$image" | awk '{print $1}')
    "$ntfs_checker" --check --quiet --require-t1os-root \
        --expected-serial "${expected_roothealth_identity[0]}" \
        --expected-journal-uuid "${expected_roothealth_identity[1]}" \
        --expected-journal-record "${expected_roothealth_identity[2]}" \
        --report "$work/roothealth.json" "${loop}p3"
    image_hash_after_ntfs_check=$(sha256sum "$image" | awk '{print $1}')
    [ "$image_hash_before_ntfs_check" = "$image_hash_after_ntfs_check" ]
    python3 -B "$roothealth_report_validator" "$work/roothealth.json" \
        --check-state EMPTY --expected-exit 0 \
        --expected-journal-uuid "${expected_roothealth_identity[1]}" \
        --expected-volume-serial "${expected_roothealth_identity[0]}"
    ntfs-3g "${loop}p3" "$work/root" -o ro,permissions,windows_names
    root_mounted=1
    if find "$work/root" -xdev -type l -print -quit | grep -q .; then
        echo 'T1OS root filesystem contains a forbidden symbolic link.' >&2
        find "$work/root" -xdev -type l -print | head -20 >&2
        exit 1
    fi
    verify_deployed_sources "$work/root"
    deployed_graphics_root="$work/root/the one/catalogue/graphics"
    deployed_firmware_root="$work/root/the one/drivers/firmware"
    test -s "$deployed_graphics_root/catalogue.json"
    test -s "$deployed_firmware_root/t1os-firmware-manifest.json"
    printf '%s  %s\n' "$expected_graphics_catalogue_hash" "$deployed_graphics_root/catalogue.json" | sha256sum -c -
    printf '%s  %s\n' "$expected_firmware_manifest_hash" "$deployed_firmware_root/t1os-firmware-manifest.json" | sha256sum -c -
    cmp -s -- "$graphics_catalogue" "$deployed_graphics_root/catalogue.json"
    cmp -s -- "$firmware_manifest" "$deployed_firmware_root/t1os-firmware-manifest.json"
    python3 - "$deployed_graphics_root" "$deployed_firmware_root/t1os-firmware-manifest.json" "$expected_nvidia_version" "$expected_nvidia_runfile_hash" <<'PY'
from pathlib import Path, PurePosixPath
import hashlib
import json
import sys

graphics_root = Path(sys.argv[1])
firmware_manifest_path = Path(sys.argv[2])
expected_version = sys.argv[3]
expected_runfile_hash = sys.argv[4]

with (graphics_root / 'catalogue.json').open('r', encoding='utf-8') as handle:
    graphics = json.load(handle)
with firmware_manifest_path.open('r', encoding='utf-8') as handle:
    firmware = json.load(handle)

source = graphics.get('sources', {}).get('nvidia_open_driver', {})
if (
    graphics.get('state') != 'ready'
    or graphics.get('profile') != 'hardware'
    or 'nvidia-open' not in graphics.get('drivers', [])
    or 'nvidia-nvdec-vaapi' not in graphics.get('drivers', [])
    or source.get('version') != expected_version
    or source.get('runfile_sha256') != expected_runfile_hash
):
    raise SystemExit('deployed graphics catalogue NVIDIA provenance mismatch')
if (
    firmware.get('nvidia_open_driver_version') != expected_version
    or firmware.get('nvidia_open_driver_archive_sha256') != expected_runfile_hash
):
    raise SystemExit('deployed firmware manifest NVIDIA provenance mismatch')

merged_glibc_dependencies = {
    'libdl.so.2',
    'libpthread.so.0',
    'librt.so.1',
}
declared_base_dependencies = set(
    graphics.get('runtime', {}).get('base_dependencies', [])
)
invalid_base_dependencies = sorted(
    merged_glibc_dependencies & declared_base_dependencies
)
if invalid_base_dependencies:
    raise SystemExit(
        'deployed graphics manifest declares absent merged-glibc base '
        'dependencies: ' + ', '.join(invalid_base_dependencies)
    )

paths = set()
unrewritten_dependencies = []
for entry in graphics.get('files', []):
    relative = str(entry.get('path', ''))
    pure = PurePosixPath(relative)
    if (
        not relative
        or pure.is_absolute()
        or '..' in pure.parts
        or '\\' in relative
        or relative in paths
    ):
        raise SystemExit(f'unsafe or duplicate graphics manifest path: {relative!r}')
    paths.add(relative)
    candidate = graphics_root.joinpath(*pure.parts)
    if not candidate.is_file():
        raise SystemExit(f'deployed graphics file is missing: {relative}')
    if candidate.stat().st_size != int(entry.get('size', -1)):
        raise SystemExit(f'deployed graphics file size mismatch: {relative}')
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if digest != str(entry.get('sha256', '')).lower():
        raise SystemExit(f'deployed graphics file hash mismatch: {relative}')
    for dependency in entry.get('needed', []):
        if dependency in merged_glibc_dependencies:
            unrewritten_dependencies.append(f'{relative}:{dependency}')

if unrewritten_dependencies:
    raise SystemExit(
        'deployed graphics ELF retains merged-glibc dependencies: '
        + ', '.join(sorted(unrewritten_dependencies))
    )

required_nvidia = {
    'drivers/nvidia_drv_video.so',
    'libgstreamer-1.0.so.0',
    'libgstbase-1.0.so.0',
    'libgstcodecparsers-1.0.so.0',
    'nvidia/libEGL.so.1',
    'nvidia/libGLESv2.so.2',
    'nvidia/libEGL_nvidia.so.0',
    'nvidia/libnvidia-egl-gbm.so.1',
    'nvidia/libcuda.so.1',
    'nvidia/libnvcuvid.so.1',
    'nvidia/libnvidia-ptxjitcompiler.so.1',
    'nvidia/egl_vendor.d/10_nvidia.json',
    'nvidia/gbm/15_nvidia_gbm.json',
    'nvidia/gbm/nvidia-drm_gbm.so',
    'nvidia/t1os-nvidia-path-provider.so',
    'nvidia/runtime.json',
}
missing = sorted(required_nvidia - paths)
if missing:
    raise SystemExit('deployed NVIDIA userspace manifest is incomplete: ' + ', '.join(missing))
with (graphics_root / 'nvidia/runtime.json').open('r', encoding='utf-8') as handle:
    runtime = json.load(handle)
video_decode = runtime.get('video_decode', {})
if (
    runtime.get('provider') != 'nvidia-open'
    or runtime.get('version') != expected_version
    or video_decode.get('backend') != 'NVDEC direct'
    or video_decode.get('software_fallback') is not False
):
    raise SystemExit('deployed NVIDIA runtime metadata mismatch')
PY
    t1os_loader="$work/root/the one/catalogue/python/ld-linux-x86-64.so.2"
    test -x "$t1os_loader"
    nvidia_elf_count=0
    while IFS= read -r -d '' nvidia_elf; do
        if ! readelf -h "$nvidia_elf" >/dev/null 2>&1; then
            continue
        fi
        nvidia_elf_count=$((nvidia_elf_count + 1))
        if readelf -d "$nvidia_elf" |
                grep -Eq '\(NEEDED\).*\[(libdl\.so\.2|libpthread\.so\.0|librt\.so\.1)\]'; then
            echo "Deployed NVIDIA ELF retains a merged-glibc dependency: $nvidia_elf" >&2
            readelf -d "$nvidia_elf" >&2
            exit 1
        fi
        nvidia_inside=${nvidia_elf#"$work/root"}
        if ! chroot "$work/root" \
                '/the one/catalogue/python/ld-linux-x86-64.so.2' \
                --list "$nvidia_inside" \
                >"$work/nvidia-loader.out" 2>&1; then
            echo "T1OS loader could not resolve deployed NVIDIA ELF: $nvidia_inside" >&2
            cat "$work/nvidia-loader.out" >&2
            exit 1
        fi
    done < <(find "$deployed_graphics_root/nvidia" -type f -print0)
    if [ "$nvidia_elf_count" -eq 0 ]; then
        echo 'Deployed NVIDIA runtime contains no ELF files.' >&2
        exit 1
    fi
    chroot "$work/root" \
        '/the one/software/python/bin/python' \
        -B -c \
        'import ctypes, sys; [ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL) for path in sys.argv[1:]]' \
        '/the one/catalogue/graphics/nvidia/libGLdispatch.so.0' \
        "/the one/catalogue/graphics/nvidia/libnvidia-glsi.so.$expected_nvidia_version" \
        "/the one/catalogue/graphics/nvidia/libnvidia-gpucomp.so.$expected_nvidia_version" \
        "/the one/catalogue/graphics/nvidia/libnvidia-eglcore.so.$expected_nvidia_version" \
        '/the one/catalogue/graphics/nvidia/gbm/nvidia-drm_gbm.so' \
        '/the one/catalogue/graphics/nvidia/libEGL_nvidia.so.0' \
        '/the one/catalogue/graphics/nvidia/libGLESv2_nvidia.so.2' \
        '/the one/catalogue/graphics/nvidia/libnvidia-egl-gbm.so.1' \
        '/the one/catalogue/graphics/nvidia/libEGL.so.1' \
        '/the one/catalogue/graphics/nvidia/libGLESv2.so.2'
    mkdir -p "$work/expected-modules" "$work/expected-firmware"
    tar --zstd -xf "$modules_archive" -C "$work/expected-modules"
    tar --zstd -xf "$firmware_archive" -C "$work/expected-firmware"
    module_differences=$(rsync -r --checksum --delete --itemize-changes --dry-run \
        -- "$work/expected-modules/the one/drivers/modules"/ \
        "$work/root/the one/drivers/modules"/)
    if [ -n "$module_differences" ]; then
        echo 'Final USB kernel module tree differs from the current module archive:' >&2
        printf '%s\n' "$module_differences" >&2
        exit 1
    fi
    firmware_differences=$(rsync -r --checksum --delete --itemize-changes --dry-run \
        -- "$work/expected-firmware"/ \
        "$work/root/the one/drivers/firmware"/)
    if [ -n "$firmware_differences" ]; then
        echo 'Final USB firmware tree differs from the current firmware archive:' >&2
        printf '%s\n' "$firmware_differences" >&2
        exit 1
    fi
    test ! -e "$work/root/.terminfo"
    printf '%s\n' \
        .ephemeral .remainder autorun.inf boot software 'the one' \
        > "$work/root-entries.expected"
    if [ "$expected_production" != True ]; then
        printf '%s\n' .rubbish >> "$work/root-entries.expected"
        # A retained development image may already have an account home, while
        # a clean first-run image correctly has no /master until startup creates
        # the account. Production images must contain neither.
        if [ -e "$work/root/master" ]; then
            printf '%s\n' master >> "$work/root-entries.expected"
        fi
    fi
    LC_ALL=C sort -o "$work/root-entries.expected" "$work/root-entries.expected"
    while IFS= read -r expected; do
        test -e "$work/root/$expected"
    done < "$work/root-entries.expected"
    find "$work/root" -mindepth 1 -maxdepth 1 -printf '%f\n' |
        LC_ALL=C sort > "$work/root-entries.actual"
    cmp "$work/root-entries.expected" "$work/root-entries.actual"
    test -s "$work/root/the one/resources/t1os-drive.ico"
    test ! -e "$work/root/.recover"
    cmp -s \
        "$work/root/the one/settings/recovery/files.tsv" \
        "$work/recovery/the one/settings/recovery/files.tsv"
    tr -d '\r' < "$work/root/autorun.inf" > "$work/autorun-normalized"
    grep -Fqx '[Autorun]' "$work/autorun-normalized"
    grep -Fqx 'Icon="the one\resources\t1os-drive.ico"' "$work/autorun-normalized"
    grep -Fqx "Label=$expected_root_label" "$work/autorun-normalized"
    for forbidden in bin dev etc home lib lib64 mnt opt proc root run sbin srv sys tmp usr var; do
        if [ -e "$work/root/$forbidden" ]; then
            echo "Forbidden Linux hierarchy found in T1OS root: /$forbidden" >&2
            exit 1
        fi
    done
    test -x "$work/root/the one/drivers/tools/modprobe"
    test -s "$work/root/the one/drivers/settings/policy.json"
    test -s "$work/root/the one/drivers/settings/runtime.json"
    test -s "$work/root/the one/settings/terminfo/index.tsv"
    test -s "$work/root/the one/settings/terminfo/6c/6c696e7578"
    test -s "$work/root/the one/settings/terminfo/4c/4c46542d5043383530"
    test ! -e "$work/root/the one/settings/terminfo/l"
    test ! -e "$work/root/the one/settings/terminfo/L"
    if [ "$expected_production" = True ]; then
        settings_root="$work/root/the one/settings"
        chromium_settings="$work/root/the one/settings/chromium"
        for directory in \
            "$chromium_settings/profile" \
            "$chromium_settings/config" \
            "$chromium_settings/font-cache"; do
            test -d "$directory"
            [ -z "$(find "$directory" -mindepth 1 -print -quit)" ]
            [ "$(stat -c '%u:%g:%a' "$directory")" = '1000:1000:700' ]
        done
        test ! -e "$chromium_settings/cache"
        test ! -e "$chromium_settings/instance.lock"
        test ! -e "$chromium_settings/instance.sock"
        [ -z "$(find "$work/root/.ephemeral" -mindepth 1 -print -quit)" ]
        for runtime_name in control nodes processes state; do
            runtime_root="$work/root/the one/drivers/$runtime_name"
            test -d "$runtime_root"
            [ -z "$(find "$runtime_root" -mindepth 1 -print -quit)" ]
        done
        python3 - "$settings_root" "$expected_root_label" "$expected_audio_codec" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
root_label = sys.argv[2]
audio_codec = sys.argv[3] or None
version = root_label.removeprefix('T1OS ')
expected_top_level = {
    'audio',
    'brick',
    'chromium',
    'expanse',
    'hardware-root.marker',
    'media',
    'network',
    'recovery',
    'runtime paths.json',
    't1osversion.txt',
    'terminfo',
    'virtualbox',
}
actual_top_level = {entry.name for entry in root.iterdir()}
if actual_top_level != expected_top_level:
    raise SystemExit(
        'production image settings inventory mismatch: ' +
        repr(sorted(actual_top_level))
    )

for path in root.rglob('*'):
    if path.is_symlink():
        raise SystemExit(f'production image settings contain a symbolic link: {path}')

if any((root / 'brick').iterdir()):
    raise SystemExit('production image retained Brick settings')
if {entry.name for entry in (root / 'expanse').iterdir()} != {
    'taskbarpins.json', 'taskbarorder.json'
}:
    raise SystemExit('production image retained unexpected Expanse settings')
for name in ('taskbarpins.json', 'taskbarorder.json'):
    with (root / 'expanse' / name).open('r', encoding='utf-8') as handle:
        if json.load(handle) != []:
            raise SystemExit(f'production image did not reset {name}')

network_entries = {entry.name for entry in (root / 'network').iterdir()}
if not {'cacerts.pem', 'network.txt'} <= network_entries:
    raise SystemExit('production image lacks required default network settings')
if not network_entries <= {'cacerts.pem', 'network.txt', 'tnc.conf'}:
    raise SystemExit(
        'production image retained user/runtime network settings: ' +
        repr(sorted(network_entries))
    )
if (root / 'network' / 'network.txt').read_text(encoding='utf-8').strip() != 'dhcp=true':
    raise SystemExit('production image network mode is not the DHCP default')
if {entry.name for entry in (root / 'media').iterdir()} != {
    'hardware diagnostics.json',
    'video decode service.json'
}:
    raise SystemExit('production image media settings inventory mismatch')
with (root / 'media' / 'hardware diagnostics.json').open(
    'r',
    encoding='utf-8',
) as handle:
    hardware_diagnostics = json.load(handle)
if hardware_diagnostics != {
    'format': 1,
    'enabled': False,
    'chromium_engine': False,
    'media_service': False,
    'engine_log_limit_bytes': 8388608,
}:
    raise SystemExit('production image hardware diagnostic policy mismatch')
if {entry.name for entry in (root / 'virtualbox').iterdir()} != {'version.txt'}:
    raise SystemExit('production image VirtualBox settings inventory mismatch')
if (root / 't1osversion.txt').read_text(encoding='utf-8').strip() != version:
    raise SystemExit('production image on-disk version does not match its volume label')
if (root / 'hardware-root.marker').read_text(encoding='utf-8').strip() != 'T1OS hardware root filesystem':
    raise SystemExit('production image hardware-root marker mismatch')

with (root / 'audio' / 'audioserver.json').open('r', encoding='utf-8') as handle:
    audio = json.load(handle)
if audio != {
    'autodevice': True,
    'mastergain': 0.2,
    'preferredcodec': audio_codec,
}:
    raise SystemExit('production image audio settings are not release defaults')
PY
    fi
    test -s "$work/root/the one/build/drivers/driverserver.py"
    test -x "$work/root/the one/software/chromium/tools/t1os-xwm"
    test ! -e "$work/root/the one/software/drivers"
    test -s "$work/root/the one/drivers/modules/module-manifest.sha256"
    test -n "$(find "$work/root/the one/drivers/firmware" -type f -print -quit)"
    test -s "$work/root/the one/drivers/firmware/iwlwifi-cc-a0-77.ucode"
    test -s "$work/root/the one/drivers/firmware/regulatory.db"
    test -s "$work/root/the one/drivers/firmware/nvidia/ad104/gsp/booter_load-535.113.01.bin"
    test -s "$work/root/the one/drivers/firmware/nvidia/ad104/gsp/booter_unload-535.113.01.bin"
    test -s "$work/root/the one/drivers/firmware/nvidia/ad104/gsp/bootloader-535.113.01.bin"
    test -s "$work/root/the one/drivers/firmware/nvidia/ad104/gsp/gsp-535.113.01.bin"
    test -s "$work/root/the one/drivers/firmware/nvidia/ad104/gsp/gsp-570.144.bin"
    test -s "$work/root/the one/drivers/firmware/nvidia/$expected_nvidia_version/gsp_ga10x.bin"
    test -s "$work/root/the one/drivers/firmware/nvidia/$expected_nvidia_version/gsp_tu10x.bin"
    test -s "$work/root/the one/drivers/firmware/nvidia/$expected_nvidia_version/ucodes_ga10x.bin"
    test -s "$work/root/the one/drivers/firmware/nvidia/$expected_nvidia_version/ucodes_tu10x.bin"
    test -s "$work/root/the one/catalogue/graphics/nvidia/libEGL.so.1"
    test -s "$work/root/the one/catalogue/graphics/nvidia/libGLESv2.so.2"
    test -s "$work/root/the one/catalogue/graphics/nvidia/libEGL_nvidia.so.0"
    test -s "$work/root/the one/catalogue/graphics/nvidia/libnvidia-egl-gbm.so.1"
    test -s "$work/root/the one/catalogue/graphics/nvidia/libcuda.so.1"
    test -s "$work/root/the one/catalogue/graphics/nvidia/libnvcuvid.so.1"
    test -s "$work/root/the one/catalogue/graphics/nvidia/libnvidia-ptxjitcompiler.so.1"
    test -s "$work/root/the one/catalogue/graphics/drivers/nvidia_drv_video.so"
    test -s "$work/root/the one/catalogue/graphics/libgstcodecparsers-1.0.so.0"
    test -s "$work/root/the one/catalogue/graphics/nvidia/egl_vendor.d/10_nvidia.json"
    test -s "$work/root/the one/catalogue/graphics/nvidia/gbm/15_nvidia_gbm.json"
    test -s "$work/root/the one/catalogue/graphics/nvidia/gbm/nvidia-drm_gbm.so"
    test -s "$work/root/the one/catalogue/graphics/nvidia/t1os-nvidia-path-provider.so"
    test -s "$work/root/the one/catalogue/graphics/nvidia/runtime.json"
    (cd "$work/root/the one/drivers/modules" && sha256sum -c --quiet module-manifest.sha256)
    kernel_release=$(find "$work/root/the one/drivers/modules" -mindepth 1 -maxdepth 1 -type d -printf '%f\n')
    [ "$kernel_release" = "$expected_kernel_release" ]
    test -s "$work/root/the one/drivers/modules/$kernel_release/modules.dep"
    for nvidia_module_name in nvidia nvidia-modeset nvidia-drm nvidia-uvm; do
        nvidia_module=$(find "$work/root/the one/drivers/modules/$kernel_release" \
            -type f -name "$nvidia_module_name.ko*" -print -quit)
        test -n "$nvidia_module"
        [ "$(modinfo -F version "$nvidia_module")" = "$expected_nvidia_version" ]
    done
    grep -Fq 'nvidia-drm' "$work/root/the one/drivers/modules/$kernel_release/modules.dep"
    grep -Eq '/nvidia-uvm\.ko[^:]*: .*\/nvidia\.ko' \
        "$work/root/the one/drivers/modules/$kernel_release/modules.dep"
    file "$work/root/the one/drivers/tools/modprobe" | grep -F 'statically linked' >/dev/null
    strings "$work/root/the one/drivers/tools/modprobe" | grep -F '/the one/drivers/modules' >/dev/null
    "$work/root/the one/drivers/tools/modprobe" \
        --dirname "$work/root" \
        --set-version "$kernel_release" \
        --show-depends snd_usb_audio | grep -F 'snd-usb-audio.ko' >/dev/null
    python3 - "$work/root/the one/settings/audio/audioserver.json" "$expected_audio_codec" <<'PY'
import json
import sys
with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    config = json.load(handle)
if config.get('preferredcodec') != (sys.argv[2] or None):
    raise SystemExit('root audio preference mismatch')
PY
fi

python3 -B "$roothealth_journal_validator" validate "$root_device" \
    --require-one-run --require-zero-entry-area \
    --report "$work/roothealth-journal.json"
python3 -B - \
    "$work/roothealth-journal.json" "$roothealth_journal_base64" \
    "$work/esp/T1OS/image-manifest.json" <<'PY'
import base64
import hashlib
import json
from pathlib import Path
import sys

with Path(sys.argv[1]).open(encoding='utf-8') as handle:
    report = json.load(handle)
expected = json.loads(base64.b64decode(sys.argv[2], validate=True).decode('utf-8'))
with Path(sys.argv[3]).open(encoding='utf-8') as handle:
    embedded = json.load(handle)
if embedded.get('roothealth_journal') != expected:
    raise SystemExit('ESP and sidecar RootHealth journal attestations differ')
if (
    expected.get('format') != 1
    or expected.get('state') != 'provisioned-and-validated'
    or expected.get('path') != '$Extend/$RootHealth'
    or expected.get('logical_bytes') != 134217728
    or expected.get('required_flags') != '0x00002007'
    or expected.get('record_locator') !=
        f"{expected.get('mft_record')}:{expected.get('mft_sequence')}"
    or expected.get('headers', {}).get('state') != 'EMPTY'
    or expected.get('headers', {}).get('selected_generation') != 2
    or expected.get('headers', {}).get('slot_generations') != [1, 2]
    or expected.get('headers', {}).get('max_entry_count') != 4096
):
    raise SystemExit('sidecar RootHealth journal attestation is malformed')
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
    raise SystemExit('RootHealth journal read-only validation is incomplete')
if identity_hash != expected['identity_sha256']:
    raise SystemExit('RootHealth journal identity differs from its sidecar attestation')
if journal['run_count'] != expected['final_validation']['run_count']:
    raise SystemExit('RootHealth journal run count differs from its final build attestation')
if exclusion_hash != expected['final_validation']['write_exclusion']['sha256']:
    raise SystemExit('RootHealth journal write-exclusion set differs from its final build attestation')
if any(journal[key] != '0x00002007' for key in (
    'standard_information_flags', 'file_name_flags',
    'extend_i30_file_name_flags', 'required_protected_flags',
)):
    raise SystemExit('RootHealth journal protected flags are not exact 0x2007')
if not all(journal['ownership'].get(key) is True for key in (
    'complete', 'unique_owner', 'self_nonoverlap',
)):
    raise SystemExit('RootHealth journal ownership census is incomplete')
if header['selected_generation'] != 2 or \
        [slot['generation'] for slot in header['slots']] != [1, 2] or \
        any(slot['state'] != 'EMPTY' for slot in header['slots']):
    raise SystemExit('RootHealth journal does not have canonical EMPTY dual headers')
PY
image_hash_after=$(sha256sum "$image" | awk '{print $1}')
[ "$image_hash_after" = "$image_hash_before" ]

if [ "$secure_boot" = True ]; then
    command -v sbverify >/dev/null 2>&1
    sbverify --list "$work/esp/EFI/BOOT/BOOTX64.EFI"
    test -s "$work/esp/EFI/T1OS/RECOVERYX64.EFI"
    sbverify --list "$work/esp/EFI/T1OS/RECOVERYX64.EFI"
fi

echo "Validated image root UUID: $expected_root_uuid"
'@

# Keep the complete validation program inside WSL. PowerShell's native pipeline
# supplies the final newline; an explicit trailing comment safely absorbs any
# carriage return appended at that boundary.
$normalizedValidateCommand = $validateCommand.Replace("`r", '') + "`n# end"
$normalizedValidateCommand | & wsl.exe -d Ubuntu -u root --exec bash -s -- $wslImage ([string]$manifest.root_uuid) ([string][bool]$manifest.encrypted) ([string][bool]$manifest.secure_boot) $preferredAudioCodec $compatibilityHash $rootLabel $buildSourceHash $driversSourceHash $wslBuildSource $wslDriversSource $wslModules $wslFirmware ([string]$manifest.kernel_sha256) ([string]$manifest.initramfs_sha256) $kernelRelease $wslGraphicsCatalogue $wslFirmwareManifest $graphicsCatalogueHash $firmwareManifestHash $nvidiaOpenDriverVersion $nvidiaOpenDriverRunfileHash ([string][bool]$manifest.production) $wslChromiumSource $chromiumSourceHash $sourceRootHash $wslNtfsChecker $wslJournalValidator $journalValidatorHash $journalManifestBase64 $wslPassphrase $hash ([string]$manifest.recovery_sha256) ([string][int64]$manifest.recovery_bytes) ([string]$manifest.esp_uuid)
$validateExitCode = $LASTEXITCODE
if ($validateExitCode -ne 0) {
    throw "Hardware USB image validation failed (exit code $validateExitCode)."
}

Write-Host "Hardware USB image validation passed: $ImagePath"
Write-Host "SHA-256: $hash"
