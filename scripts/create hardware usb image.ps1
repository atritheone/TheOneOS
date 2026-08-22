[CmdletBinding(SupportsShouldProcess)]
param(
    # The production root, complete hardware firmware set, dedicated recovery
    # partition, and working-space margin do not fit safely below 16 GiB.
    [ValidateRange(16, 256)]
    [int]$ImageSizeGiB = 16,

    [string]$OutputPath,

    [switch]$EncryptRoot,

    [string]$PassphraseFile,

    [switch]$Production,

    [string]$SecureBootPrivateKey,

    [string]$SecureBootCertificate,

    [ValidateSet('cpu', 'auto')]
    [string]$SecureBootGraphics = 'cpu',

    [AllowEmptyString()]
    [string]$PreferredAudioCodec = '10ec0897',

    [switch]$SkipCompatibilityValidation,

    [Parameter(Mandatory)]
    [string]$NtfscpPath,

    [Parameter(Mandatory)]
    [string]$NtfscpProvenancePath,

    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'common.ps1')

$currentVersionPath = Join-Path $projectRoot 'current_version.txt'
if (-not (Test-Path -LiteralPath $currentVersionPath -PathType Leaf)) {
    throw "Current T1OS version file not found: $currentVersionPath"
}
$currentVersion = (Get-Content -LiteralPath $currentVersionPath -Raw).Trim()
if ($currentVersion -notmatch '^\d+(?:\.\d+)?$') {
    throw "current_version.txt must contain one non-negative decimal version: $currentVersion"
}
$rootVolumeLabel = "T1OS $currentVersion"
if ($rootVolumeLabel.Length -gt 32) {
    throw "The version-derived NTFS volume label exceeds 32 characters: $rootVolumeLabel"
}

if ($PreferredAudioCodec -and $PreferredAudioCodec -notmatch '^[0-9A-Fa-f]{8}$') {
    throw 'PreferredAudioCodec must be empty for automatic selection or an eight-digit hexadecimal codec ID.'
}

$sourceRootImage = Join-Path $projectRoot 'environment\software\storage.img'
$hardwareRoot = Join-Path $projectRoot 'environment\hardware'
$kernelPath = Join-Path $hardwareRoot 'boot\vmlinuz-hardware'
$kernelReleasePath = Join-Path $hardwareRoot 'kernel-release.txt'
$initramfsPath = Join-Path $hardwareRoot 'boot\initramfs-hardware'
$modulesPath = Join-Path $hardwareRoot 'modules.tar.zst'
$moduleLoaderPath = Join-Path $projectRoot 'source\drivers\tools\modprobe'
$firmwarePath = Join-Path $hardwareRoot 'firmware.tar.zst'
$firmwareManifestPath = Join-Path $hardwareRoot 't1os-firmware-manifest.json'
$graphicsCataloguePath = Join-Path $projectRoot 'source\catalogue\graphics\catalogue.json'
$compatibilityReportPath = Join-Path $hardwareRoot 'desktop-compatibility-report.json'
$buildSourcePath = Join-Path $projectRoot 'source\build software'
$driversSourcePath = Join-Path $projectRoot 'source\drivers'
$chromiumSoftwarePath = Join-Path $projectRoot 'source\software\chromium'
$journalValidatorPath = Join-Path $PSScriptRoot 'validate roothealth journal.py'
$NtfscpPath = [System.IO.Path]::GetFullPath($NtfscpPath)
$NtfscpProvenancePath = [System.IO.Path]::GetFullPath($NtfscpProvenancePath)
$grubThemePath = Join-Path $projectRoot 'source\entry\grub\t1os hardware theme.txt'
$grubBackgroundPath = Join-Path $projectRoot 'source\entry\grub\t1os black background.png.base64'
$driveIconPath = Join-Path $projectRoot 'flash\T1OS Logo - Black Transparent.ico'
$grubTemplate = if ($EncryptRoot) {
    Join-Path $projectRoot 'source\entry\grub\grub hardware encrypted 0.2.cfg'
}
else {
    Join-Path $projectRoot 'source\entry\grub\grub hardware 0.2.cfg'
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $name = if ($EncryptRoot) { 't1os-hardware-usb-encrypted.img' } else { 't1os-hardware-usb.img' }
    $OutputPath = Join-Path $hardwareRoot $name
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$partialPath = "$OutputPath.building"
$manifestPath = "$OutputPath.json"
$partialManifestPath = "$manifestPath.building"
$previousImagePath = "$OutputPath.previous"
$previousManifestPath = "$manifestPath.previous"

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

function Assert-ProjectOutputPath {
    param([Parameter(Mandatory)][string]$Path)

    $root = [System.IO.Path]::GetFullPath($hardwareRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $candidate = [System.IO.Path]::GetFullPath($Path)
    $prefix = $root + [System.IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "USB image output must remain inside the hardware-artifact directory: $candidate"
    }

    $cursor = [System.IO.Path]::GetFullPath((Split-Path -Path $candidate -Parent))
    while ($true) {
        if (Test-Path -LiteralPath $cursor) {
            $ancestor = Get-Item -LiteralPath $cursor -Force
            if (-not $ancestor.PSIsContainer -or $ancestor.LinkType) {
                throw "USB image output has a redirected or non-directory ancestor: $cursor"
            }
        }
        if ($cursor.Equals($root, [System.StringComparison]::OrdinalIgnoreCase)) {
            break
        }
        $next = [System.IO.Path]::GetDirectoryName($cursor)
        if (-not $next -or -not $next.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "USB image output escaped the hardware-artifact directory: $candidate"
        }
        $cursor = $next
    }
}

Assert-ProjectOutputPath -Path $OutputPath

$outputArtifactPaths = @(
    $OutputPath,
    $partialPath,
    $manifestPath,
    $partialManifestPath,
    $previousImagePath,
    $previousManifestPath
)
$protectedInputPaths = @(
    $sourceRootImage,
    $kernelPath,
    $kernelReleasePath,
    $initramfsPath,
    $grubTemplate,
    $grubThemePath,
    $grubBackgroundPath,
    $driveIconPath,
    $modulesPath,
    $moduleLoaderPath,
    $firmwarePath,
    $firmwareManifestPath,
    $graphicsCataloguePath,
    $compatibilityReportPath,
    $buildSourcePath,
    $driversSourcePath,
    $chromiumSoftwarePath,
    $(if (-not [string]::IsNullOrWhiteSpace($PassphraseFile)) {
        [System.IO.Path]::GetFullPath($PassphraseFile)
    }),
    $(if (-not [string]::IsNullOrWhiteSpace($SecureBootPrivateKey)) {
        [System.IO.Path]::GetFullPath($SecureBootPrivateKey)
    }),
    $(if (-not [string]::IsNullOrWhiteSpace($SecureBootCertificate)) {
        [System.IO.Path]::GetFullPath($SecureBootCertificate)
    })
) | Where-Object { $_ } | ForEach-Object { [System.IO.Path]::GetFullPath($_) }
foreach ($artifactPath in $outputArtifactPaths) {
    $fullArtifactPath = [System.IO.Path]::GetFullPath($artifactPath)
    foreach ($inputPath in $protectedInputPaths) {
        if ($fullArtifactPath.Equals($inputPath, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "USB image output artifact collides with a build input: $fullArtifactPath"
        }
    }
    if (Test-Path -LiteralPath $fullArtifactPath) {
        $existingArtifact = Get-Item -LiteralPath $fullArtifactPath -Force
        if ($existingArtifact.PSIsContainer -or $existingArtifact.LinkType) {
            throw "USB image output artifact is a directory or redirect: $fullArtifactPath"
        }
    }
}

foreach ($requiredFile in @($sourceRootImage, $kernelPath, $kernelReleasePath, $initramfsPath, $grubTemplate, $grubThemePath, $grubBackgroundPath, $driveIconPath, $modulesPath, $moduleLoaderPath, $firmwarePath, $firmwareManifestPath, $graphicsCataloguePath, $journalValidatorPath, $NtfscpPath, $NtfscpProvenancePath)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required hardware-image input not found: $requiredFile"
    }
}
foreach ($requiredDirectory in @($buildSourcePath, $driversSourcePath, $chromiumSoftwarePath)) {
    if (-not (Test-Path -LiteralPath $requiredDirectory -PathType Container)) {
        throw "Required hardware-image source directory not found: $requiredDirectory"
    }
}

try {
    $graphicsCatalogue = Get-Content -LiteralPath $graphicsCataloguePath -Raw | ConvertFrom-Json
}
catch {
    throw "Could not parse the graphics catalogue used for NVIDIA provenance: $($_.Exception.Message)"
}
try {
    $firmwareManifest = Get-Content -LiteralPath $firmwareManifestPath -Raw | ConvertFrom-Json
}
catch {
    throw "Could not parse the firmware manifest used for NVIDIA provenance: $($_.Exception.Message)"
}

if ($graphicsCatalogue.state -ne 'ready' -or $graphicsCatalogue.profile -ne 'hardware') {
    throw 'The graphics catalogue must be a ready hardware build before a hardware USB image can be created.'
}
$graphicsNvidiaVersion = ([string]$graphicsCatalogue.sources.nvidia_open_driver.version).Trim()
$graphicsNvidiaRunfileHash = ([string]$graphicsCatalogue.sources.nvidia_open_driver.runfile_sha256).Trim().ToLowerInvariant()
$firmwareNvidiaVersion = ([string]$firmwareManifest.nvidia_open_driver_version).Trim()
$firmwareNvidiaRunfileHash = ([string]$firmwareManifest.nvidia_open_driver_archive_sha256).Trim().ToLowerInvariant()
if (
    $graphicsNvidiaVersion -notmatch '^\d+(?:\.\d+)+$' -or
    $graphicsNvidiaRunfileHash -notmatch '^[0-9a-f]{64}$' -or
    'nvidia-open' -notin @($graphicsCatalogue.drivers) -or
    'nvidia-nvdec-vaapi' -notin @($graphicsCatalogue.drivers)
) {
    throw 'The ready graphics catalogue does not contain valid NVIDIA graphics and NVDEC provenance.'
}
if ($firmwareNvidiaVersion -notmatch '^\d+(?:\.\d+)+$' -or $firmwareNvidiaRunfileHash -notmatch '^[0-9a-f]{64}$') {
    throw 'The firmware manifest does not contain valid NVIDIA open-driver version and runfile hash provenance.'
}
if (
    $graphicsNvidiaVersion -cne $firmwareNvidiaVersion -or
    $graphicsNvidiaRunfileHash -cne $firmwareNvidiaRunfileHash
) {
    throw "NVIDIA stack provenance mismatch: graphics uses $graphicsNvidiaVersion/$graphicsNvidiaRunfileHash but firmware uses $firmwareNvidiaVersion/$firmwareNvidiaRunfileHash."
}
$nvidiaOpenDriverVersion = $graphicsNvidiaVersion
$nvidiaOpenDriverRunfileHash = $graphicsNvidiaRunfileHash
$graphicsCatalogueHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $graphicsCataloguePath).Hash.ToLowerInvariant()
$firmwareManifestHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $firmwareManifestPath).Hash.ToLowerInvariant()
$kernelRelease = (Get-Content -LiteralPath $kernelReleasePath -Raw).Trim()
if ($kernelRelease -notmatch '^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$') {
    throw "The staged hardware kernel release is invalid: $kernelRelease"
}

if (-not $SkipCompatibilityValidation) {
    $compatibilityValidator = Join-Path $PSScriptRoot 'audits\validate hardware compatibility.ps1'
    Write-Host 'Checking complete desktop hardware dependency closure before image creation...'
    & pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $compatibilityValidator
    if ($LASTEXITCODE -ne 0) {
        throw "Hardware USB image compatibility validation failed (exit code $LASTEXITCODE)."
    }
}
if (-not (Test-Path -LiteralPath $compatibilityReportPath -PathType Leaf)) {
    throw "Desktop compatibility report not found: $compatibilityReportPath"
}
try {
    $compatibilityReport = Get-Content -LiteralPath $compatibilityReportPath -Raw | ConvertFrom-Json
}
catch {
    throw "Could not parse the desktop compatibility report: $($_.Exception.Message)"
}
$modulesArchiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $modulesPath).Hash.ToLowerInvariant()
$reportModulesHash = ([string]$compatibilityReport.modules_archive_sha256).Trim().ToLowerInvariant()
$reportFirmwareManifestHash = ([string]$compatibilityReport.firmware_manifest_sha256).Trim().ToLowerInvariant()
$reportGraphicsManifestHash = ([string]$compatibilityReport.graphics_manifest_sha256).Trim().ToLowerInvariant()
$reportNvidiaVersion = ([string]$compatibilityReport.nvidia_open_driver.version).Trim()
$reportNvidiaRunfileHash = ([string]$compatibilityReport.nvidia_open_driver.runfile_sha256).Trim().ToLowerInvariant()
$reportNvidiaModuleVersion = ([string]$compatibilityReport.nvidia_open_driver.kernel_module_version).Trim()
if (
    $compatibilityReport.state -ne 'ready' -or
    ([string]$compatibilityReport.kernel_release).Trim() -cne $kernelRelease -or
    $reportModulesHash -cne $modulesArchiveHash -or
    $reportFirmwareManifestHash -cne $firmwareManifestHash -or
    $reportGraphicsManifestHash -cne $graphicsCatalogueHash -or
    $reportNvidiaVersion -cne $nvidiaOpenDriverVersion -or
    $reportNvidiaRunfileHash -cne $nvidiaOpenDriverRunfileHash -or
    $reportNvidiaModuleVersion -cne $nvidiaOpenDriverVersion
) {
    throw 'The desktop compatibility report is stale or does not describe the exact kernel modules, firmware, graphics userspace, and NVIDIA release selected for this image.'
}

if ($EncryptRoot) {
    if ([string]::IsNullOrWhiteSpace($PassphraseFile)) {
        throw '-PassphraseFile is required with -EncryptRoot. The file is never copied into the image.'
    }
    $PassphraseFile = [System.IO.Path]::GetFullPath($PassphraseFile)
    if (-not (Test-Path -LiteralPath $PassphraseFile -PathType Leaf)) {
        throw "Passphrase file not found: $PassphraseFile"
    }
    if ((Get-Item -LiteralPath $PassphraseFile).Length -lt 12) {
        throw 'The encrypted-root passphrase file is unexpectedly short.'
    }
}
elseif (-not [string]::IsNullOrWhiteSpace($PassphraseFile)) {
    throw '-PassphraseFile may only be supplied with -EncryptRoot.'
}

$secureBoot = -not [string]::IsNullOrWhiteSpace($SecureBootPrivateKey) -or -not [string]::IsNullOrWhiteSpace($SecureBootCertificate)
if ($secureBoot) {
    if ([string]::IsNullOrWhiteSpace($SecureBootPrivateKey) -or [string]::IsNullOrWhiteSpace($SecureBootCertificate)) {
        throw 'Secure Boot requires both -SecureBootPrivateKey and -SecureBootCertificate.'
    }
    $SecureBootPrivateKey = [System.IO.Path]::GetFullPath($SecureBootPrivateKey)
    $SecureBootCertificate = [System.IO.Path]::GetFullPath($SecureBootCertificate)
    foreach ($secureBootFile in @($SecureBootPrivateKey, $SecureBootCertificate)) {
        if (-not (Test-Path -LiteralPath $secureBootFile -PathType Leaf)) {
            throw "Secure Boot input not found: $secureBootFile"
        }
    }
}

if (Test-T1OSDiskMounted) {
    throw 'environment/software/storage.img is mounted. Unmount it before building a hardware image.'
}

if ((Test-Path -LiteralPath $OutputPath) -and -not $Force) {
    throw "Output already exists. Use -Force to replace this project artifact: $OutputPath"
}
if ((Test-Path -LiteralPath $manifestPath) -and -not $Force) {
    throw "Output manifest already exists. Use -Force to replace this project artifact: $manifestPath"
}
if (Test-Path -LiteralPath $partialPath) {
    throw "An unfinished hardware image exists: $partialPath"
}
if (Test-Path -LiteralPath $partialManifestPath) {
    throw "An unfinished hardware image manifest exists: $partialManifestPath"
}

if (-not $PSCmdlet.ShouldProcess($OutputPath, "Create a $ImageSizeGiB GiB T1OS UEFI USB image")) {
    return
}

New-Item -ItemType Directory -Path (Split-Path -Path $OutputPath -Parent) -Force | Out-Null

$sourceRootHashBefore = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $sourceRootImage
).Hash.ToLowerInvariant()
$wslSource = ConvertTo-WslPath -WindowsPath $sourceRootImage
$wslKernel = ConvertTo-WslPath -WindowsPath $kernelPath
$wslInitramfs = ConvertTo-WslPath -WindowsPath $initramfsPath
$wslModules = ConvertTo-WslPath -WindowsPath $modulesPath
$wslFirmware = ConvertTo-WslPath -WindowsPath $firmwarePath
$wslFirmwareManifest = ConvertTo-WslPath -WindowsPath $firmwareManifestPath
$wslGraphicsCatalogue = ConvertTo-WslPath -WindowsPath $graphicsCataloguePath
$wslGrubTemplate = ConvertTo-WslPath -WindowsPath $grubTemplate
$wslGrubTheme = ConvertTo-WslPath -WindowsPath $grubThemePath
$wslGrubBackground = ConvertTo-WslPath -WindowsPath $grubBackgroundPath
$wslDriveIcon = ConvertTo-WslPath -WindowsPath $driveIconPath
$wslCompatibilityReport = ConvertTo-WslPath -WindowsPath $compatibilityReportPath
$wslBuildSource = ConvertTo-WslPath -WindowsPath $buildSourcePath
$wslDriversSource = ConvertTo-WslPath -WindowsPath $driversSourcePath
$wslChromiumSoftware = ConvertTo-WslPath -WindowsPath $chromiumSoftwarePath
$wslPartial = ConvertTo-WslPath -WindowsPath $partialPath
$wslJournalValidator = ConvertTo-WslPath -WindowsPath $journalValidatorPath
$wslNtfscp = ConvertTo-WslPath -WindowsPath $NtfscpPath
$wslNtfscpProvenance = ConvertTo-WslPath -WindowsPath $NtfscpProvenancePath
$wslPassphrase = if ($EncryptRoot) { ConvertTo-WslPath -WindowsPath $PassphraseFile } else { '-' }
$encryptValue = if ($EncryptRoot) { '1' } else { '0' }
$productionValue = if ($Production) { '1' } else { '0' }
$secureBootValue = if ($secureBoot) { '1' } else { '0' }
$wslSecureBootKey = if ($secureBoot) { ConvertTo-WslPath -WindowsPath $SecureBootPrivateKey } else { '-' }
$wslSecureBootCertificate = if ($secureBoot) { ConvertTo-WslPath -WindowsPath $SecureBootCertificate } else { '-' }
$journalValidatorHash = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $journalValidatorPath
).Hash.ToLowerInvariant()
$ntfscpProvenanceHash = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $NtfscpProvenancePath
).Hash.ToLowerInvariant()
$ntfscpPreflightOutput = & wsl.exe -d Ubuntu -u root --exec env `
    PYTHONDONTWRITEBYTECODE=1 `
    python3 -B $wslJournalValidator verify-ntfscp `
    $wslNtfscp $wslNtfscpProvenance
if ($LASTEXITCODE -ne 0) {
    throw 'The selected ntfscp lacks release-qualified pinned-d4 provenance.'
}
try {
    $ntfscpAttestation = ($ntfscpPreflightOutput -join "`n") | ConvertFrom-Json
}
catch {
    throw "Could not parse selected ntfscp provenance: $($_.Exception.Message)"
}
if (
    [string]$ntfscpAttestation.state -cne 'release-qualified' -or
    [string]$ntfscpAttestation.manifest_sha256 -cne $ntfscpProvenanceHash
) {
    throw 'The selected ntfscp attestation is not release-qualified or source-bound.'
}
$ntfscpBinaryHash = [string]$ntfscpAttestation.binary_sha256

$buildCommand = @'
set -euo pipefail
export LC_ALL=C
export PYTHONDONTWRITEBYTECODE=1

source_image=$1
kernel=$2
initramfs=$3
modules=$4
firmware=$5
grub_template=$6
published_output=$7
size_gib=$8
encrypt=$9
passphrase=${10}
production=${11}
secure_boot=${12}
secure_key=${13}
secure_certificate=${14}
secure_graphics=${15}
audio_codec=${16}
grub_theme=${17}
compatibility_report=${18}
grub_background=${19}
root_label=${20}
build_source=${21}
drivers_source=${22}
graphics_catalogue=${23}
firmware_manifest=${24}
nvidia_open_driver_version=${25}
nvidia_open_driver_runfile_sha256=${26}
graphics_catalogue_sha256=${27}
firmware_manifest_sha256=${28}
expected_kernel_release=${29}
drive_icon=${30}
chromium_source=${31}
source_root_sha256=${32}
journal_validator=${33}
journal_validator_sha256=${34}
ntfscp_tool=${35}
ntfscp_provenance=${36}
ntfscp_provenance_sha256=${37}
ntfscp_binary_sha256=${38}

for command_name in sgdisk losetup mkfs.vfat mkfs.ntfs ntfs-3g ntfsfix mount umount rsync grub-install blkid blockdev dd e2fsck fsck.vfat python3 stat cp sync cmp sha256sum file modinfo find mksquashfs unsquashfs; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "Required USB-image command not installed: $command_name" >&2
        exit 127
    }
done
[ -x "$ntfscp_tool" ] || { echo 'Selected pinned ntfscp is not executable.' >&2; exit 127; }
[ -f "$journal_validator" ] && [ -f "$ntfscp_provenance" ]
printf '%s  %s\n' "$journal_validator_sha256" "$journal_validator" | sha256sum -c -
printf '%s  %s\n' "$ntfscp_provenance_sha256" "$ntfscp_provenance" | sha256sum -c -
if [ "$encrypt" = 1 ]; then
    command -v cryptsetup >/dev/null 2>&1 || { echo 'cryptsetup is required for encryption.' >&2; exit 127; }
fi
if [ "$secure_boot" = 1 ]; then
    command -v ukify >/dev/null 2>&1 || { echo 'ukify is required for Secure Boot images.' >&2; exit 127; }
    command -v sbverify >/dev/null 2>&1 || { echo 'sbverify is required for Secure Boot images.' >&2; exit 127; }
fi

case "$nvidia_open_driver_version" in
    ''|*[!0-9.]*|.*|*.) echo 'Invalid NVIDIA open-driver version provenance.' >&2; exit 1 ;;
esac
case "$nvidia_open_driver_runfile_sha256" in
    *[!0-9a-f]*|'') echo 'Invalid NVIDIA open-driver runfile hash provenance.' >&2; exit 1 ;;
esac
[ "${#nvidia_open_driver_runfile_sha256}" = 64 ]
[ "${#graphics_catalogue_sha256}" = 64 ]
[ "${#firmware_manifest_sha256}" = 64 ]
[ "${#source_root_sha256}" = 64 ]
case "$source_root_sha256" in
    *[!0-9a-f]*|'') echo 'Invalid source storage hash provenance.' >&2; exit 1 ;;
esac
printf '%s  %s\n' "$source_root_sha256" "$source_image" | sha256sum -c -
case "$expected_kernel_release" in
    ''|*[!A-Za-z0-9._+-]*) echo 'Invalid staged kernel release.' >&2; exit 1 ;;
esac
printf '%s  %s\n' "$graphics_catalogue_sha256" "$graphics_catalogue" | sha256sum -c -
printf '%s  %s\n' "$firmware_manifest_sha256" "$firmware_manifest" | sha256sum -c -
kernel_description=$(file -b "$kernel")
case "$kernel_description" in
    *"version $expected_kernel_release "*) ;;
    *)
        echo "Kernel image does not identify the staged module release: $expected_kernel_release" >&2
        echo "$kernel_description" >&2
        exit 1
        ;;
esac

work=/var/tmp/t1os-usb-image
output="$work/t1os-hardware-usb.img.building"
source_mount="$work/source"
esp_mount="$work/esp"
root_mount="$work/root"
recovery_mount="$work/recovery"
image_loop=
source_loop=
root_device=
recovery_device=
mapper_name=t1os-usb-build-root
mapper_open=0
mounted_source=0
mounted_esp=0
mounted_root=0

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
    normalize_production_build_tree "$expected_build" "$production"
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

verify_source_deployment() {
    local deployment_label=$1
    local deployed_root=$2
    local deployed_build="$deployed_root/the one/build"
    local deployed_drivers="$deployed_root/the one/drivers"
    local deployed_chromium="$deployed_root/the one/software/chromium"
    local build_differences
    local driver_differences
    local chromium_source_sha256
    local relative

    test -d "$deployed_build"
    test -d "$deployed_drivers"
    test -d "$deployed_chromium"

    build_differences=$(rsync -r --checksum --delete --itemize-changes --dry-run \
        --exclude='__pycache__/' \
        --exclude='*.py[co]' \
        -- "$expected_build"/ "$deployed_build"/)
    if [ -n "$build_differences" ]; then
        echo "$deployment_label build provenance differs from current source:" >&2
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
        echo "$deployment_label driver-runtime provenance differs from current source:" >&2
        printf '%s\n' "$driver_differences" >&2
        exit 1
    fi

    chromium_source_sha256=$(source_tree_sha256 "$deployed_chromium")
    if [ "$chromium_source_sha256" != "$expected_chromium_source_sha256" ]; then
        echo "$deployment_label Chromium runtime provenance differs from current source:" >&2
        echo "expected: $expected_chromium_source_sha256" >&2
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
            echo "$deployment_label critical build file differs from current source: $relative" >&2
            exit 1
        fi
    done
    if ! cmp -s -- "$expected_drivers/tools/modprobe" "$deployed_drivers/tools/modprobe"; then
        echo "$deployment_label module loader differs from current source: tools/modprobe" >&2
        exit 1
    fi
}

cleanup() {
    status=$?
    cleanup_failed=0
    set +e
    trap - EXIT HUP INT TERM
    sync || cleanup_failed=1
    if [ "$mounted_root" != 0 ]; then
        if umount "$root_mount"; then mounted_root=0; else cleanup_failed=1; fi
    fi
    if [ "$mounted_esp" != 0 ]; then
        if umount "$esp_mount"; then mounted_esp=0; else cleanup_failed=1; fi
    fi
    if [ "$mounted_source" != 0 ]; then
        if umount "$source_mount"; then mounted_source=0; else cleanup_failed=1; fi
    fi
    if [ "$mapper_open" != 0 ]; then
        if cryptsetup close "$mapper_name"; then mapper_open=0; else cleanup_failed=1; fi
    fi
    if [ -n "$source_loop" ]; then
        if losetup -d "$source_loop"; then source_loop=; else cleanup_failed=1; fi
    fi
    if [ -n "$image_loop" ]; then
        if losetup -d "$image_loop"; then image_loop=; else cleanup_failed=1; fi
    fi
    if [ "$mounted_root" = 0 ] && [ "$mounted_esp" = 0 ] && [ "$mounted_source" = 0 ]; then
        rm -rf -- "$work" || cleanup_failed=1
    else
        cleanup_failed=1
        echo "USB image cleanup left a mounted work tree at $work." >&2
    fi
    if [ "$cleanup_failed" -ne 0 ] && [ "$status" -eq 0 ]; then
        status=1
    fi
    if [ "$status" -ne 0 ] && [ -z "$image_loop" ] && [ "$mounted_root" = 0 ] && [ "$mounted_esp" = 0 ]; then
        rm -f -- "$output" "$published_output"
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

case "$work" in
    /var/tmp/t1os-usb-image) rm -rf -- "$work" ;;
    *) echo "Refusing to replace unexpected work path: $work" >&2; exit 1 ;;
esac
expected_build="$work/expected-build"
expected_drivers="$work/expected-drivers"
    mkdir -p "$source_mount" "$esp_mount" "$root_mount" "$recovery_mount"
ntfscp_attestation="$work/ntfscp-attestation.json"
python3 -B "$journal_validator" verify-ntfscp \
    "$ntfscp_tool" "$ntfscp_provenance" --report "$ntfscp_attestation"
python3 -B - "$ntfscp_attestation" "$ntfscp_binary_sha256" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as handle:
    report = json.load(handle)
if report.get('state') != 'release-qualified':
    raise SystemExit('selected ntfscp is not release-qualified')
if report.get('binary_sha256') != sys.argv[2]:
    raise SystemExit('selected ntfscp binary hash changed after PowerShell preflight')
PY
stage_source_trees "$expected_build" "$expected_drivers"
expected_build_sha256=$(source_tree_sha256 "$expected_build")
expected_drivers_sha256=$(source_tree_sha256 "$expected_drivers")
expected_chromium_source_sha256=$(source_tree_sha256 "$chromium_source")

# losetup detaches are lazy on current kernels.  A just-unmounted storage.img
# can therefore remain associated with its old loop briefly even though the
# mount itself is gone.  Reattaching it during that window can expose an ext4
# journal which has not finished closing and makes the read-only mount fail.
source_release_attempt=0
while losetup -j "$source_image" 2>/dev/null | grep -q .; do
    source_release_attempt=$((source_release_attempt + 1))
    if [ "$source_release_attempt" -ge 50 ]; then
        echo 'storage.img still has an active WSL loop mapping after 10 seconds.' >&2
        losetup -j "$source_image" >&2 || true
        exit 1
    fi
    sleep 0.2
done

source_fsck_attempt=0
while :; do
    set +e
    # Image creation is a read-only consumer of the canonical storage image.
    # Force a complete check but never replay, repair, or update its metadata.
    source_fsck_output=$(e2fsck -fn "$source_image" 2>&1)
    source_fsck_status=$?
    set -e

    [ -z "$source_fsck_output" ] || printf '%s\n' "$source_fsck_output"

    if [ "$source_fsck_status" -eq 0 ]; then
        break
    fi

    source_fsck_attempt=$((source_fsck_attempt + 1))

    # Windows and OneDrive can retain a short-lived write handle after the
    # preceding storage.img synchronisation.  Retry only e2fsck operational
    # failures that explicitly report an access/busy condition.  Corruption,
    # usage errors, and every other status still fail without delay.
    if [ "$source_fsck_status" -eq 8 ] &&
       [ "$source_fsck_attempt" -lt 60 ] &&
       printf '%s\n' "$source_fsck_output" |
           grep -Eqi 'permission denied|device or resource busy|resource temporarily unavailable'; then
        echo "storage.img is temporarily locked; retrying preflight $source_fsck_attempt/59..." >&2
        sleep 0.25
        continue
    fi

    echo "storage.img preflight filesystem check failed with status $source_fsck_status." >&2
    exit "$source_fsck_status"
done

truncate -s "${size_gib}G" "$output"
if [ "$encrypt" = 1 ]; then
    root_type=8309
    root_partition_name=T1OS_CRYPT
    root_kind=luks
else
    root_type=0700
    root_partition_name=$root_label
    root_kind=plain
fi
sgdisk --zap-all "$output"
sgdisk --clear \
    --new=1:2048:+512M --typecode=1:ef00 --change-name=1:T1OS_EFI \
    --new=2:0:+3G --typecode=2:8300 --change-name=2:T1OS_RECOVERY \
    --new=3:0:0 --typecode=3:"$root_type" --change-name=3:"$root_partition_name" \
    "$output"
sgdisk --verify "$output"

image_loop=$(losetup --find --show --partscan "$output")
source_loop=$(losetup --find --show --read-only "$source_image")
esp_device="${image_loop}p1"
recovery_device="${image_loop}p2"
root_partition="${image_loop}p3"

for unused in 1 2 3 4 5; do
    [ -b "$esp_device" ] && [ -b "$recovery_device" ] && [ -b "$root_partition" ] && break
    sleep 1
done
[ -b "$esp_device" ] && [ -b "$recovery_device" ] && [ -b "$root_partition" ] || {
    echo 'Loop partition devices did not appear.' >&2
    exit 1
}

mkfs.vfat -F 32 -n T1OS_EFI "$esp_device"

if [ "$encrypt" = 1 ]; then
    cryptsetup luksFormat --batch-mode --type luks2 --label T1OS_CRYPT --key-file "$passphrase" "$root_partition"
    cryptsetup open --type luks --key-file "$passphrase" "$root_partition" "$mapper_name"
    mapper_open=1
    root_device="/dev/mapper/$mapper_name"
else
    root_device=$root_partition
fi

mkfs.ntfs -F -Q -L "$root_label" "$root_device"
journal_seed="$work/roothealth.seed"
journal_seed_report="$work/roothealth-seed.json"
journal_provision_report="$work/roothealth-provision.json"
journal_initial_report="$work/roothealth-initial.json"
journal_manifest="$work/roothealth-journal-manifest.json"
python3 -B "$journal_validator" seed \
    "$root_device" "$journal_seed" --report "$journal_seed_report"
"$ntfscp_tool" -f -m "$root_device" "$journal_seed" '$Extend/$RootHealth'
sync
ntfs-3g "$root_device" "$root_mount" \
    -o permissions,windows_names,big_writes,show_sys_files
mounted_root=1
python3 -B - "$root_mount/\$Extend/\$RootHealth" <<'PY'
import os
from pathlib import Path
import struct
import sys

path = Path(sys.argv[1])
required = 0x00002007
os.setxattr(path, 'system.ntfs_attrib', struct.pack('<I', required))
observed = struct.unpack('<I', os.getxattr(path, 'system.ntfs_attrib'))[0]
if observed != required:
    raise SystemExit(f'journal protected flags did not persist: 0x{observed:08x}')
PY
sync
umount "$root_mount"
mounted_root=0
provision_arguments=(
    provision-flags-device "$root_device"
    --builder-image "$output"
    --root-kind "$root_kind"
    --root-partition-number 3
    --expected-partition-name "$root_partition_name"
    --report "$journal_provision_report"
)
if [ "$root_kind" = luks ]; then
    provision_arguments+=(--expected-mapper-name "$mapper_name")
fi
python3 -B "$journal_validator" "${provision_arguments[@]}"
python3 -B "$journal_validator" validate "$root_device" \
    --require-one-run --require-zero-entry-area \
    --report "$journal_initial_report"
python3 -B - \
    "$journal_seed_report" "$journal_provision_report" "$journal_initial_report" \
    "$ntfscp_attestation" "$journal_manifest" \
    "$journal_validator_sha256" "$ntfscp_provenance_sha256" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

seed_path, provision_path, validation_path, tool_path, output_path = map(Path, sys.argv[1:6])
validator_sha256, provenance_sha256 = sys.argv[6:8]

def load(path):
    with path.open(encoding='utf-8') as handle:
        return json.load(handle)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

seed = load(seed_path)
provision = load(provision_path)
validation = load(validation_path)
tool = load(tool_path)
journal = validation['journal']
header = journal['header']
ownership = journal['ownership']
exclusion = journal['write_exclusion']
if validation.get('state') != 'structurally-valid' or not all(validation['checks'].values()):
    raise SystemExit('fresh journal raw validation is incomplete')
if journal['run_count'] != 1 or journal['logical_bytes'] != 134217728:
    raise SystemExit('fresh journal is not the exact contiguous 128 MiB profile')
if (
    journal['standard_information_flags'] != '0x00002007'
    or journal['file_name_flags'] != '0x00002007'
    or journal['extend_i30_file_name_flags'] != '0x00002007'
):
    raise SystemExit('fresh journal protected flags are not exact 0x2007')
if not all(ownership.get(key) is True for key in ('complete', 'unique_owner', 'self_nonoverlap')):
    raise SystemExit('fresh journal ownership census is incomplete')
if header['journal_uuid'] != seed['journal_uuid'] or validation['device']['serial'] != seed['volume_serial']:
    raise SystemExit('fresh journal seed identity does not bind the NTFS volume')
slot_generations = [slot['generation'] for slot in header['slots']]
if header['selected_generation'] != 2 or slot_generations != [1, 2]:
    raise SystemExit('fresh journal does not have canonical EMPTY dual headers')
if any(slot['state'] != 'EMPTY' for slot in header['slots']):
    raise SystemExit('fresh journal header is not EMPTY')
if not header.get('entry_area_zero_sha256'):
    raise SystemExit('fresh journal lacks a zero-entry-area digest')
canonical_exclusion = json.dumps(exclusion, sort_keys=True, separators=(',', ':')).encode()
identity = {
    'volume_serial': validation['device']['serial'],
    'journal_uuid': header['journal_uuid'],
    'mft_record': journal['mft_record'],
    'mft_sequence': journal['mft_sequence'],
    'logical_bytes': journal['logical_bytes'],
    'required_flags': '0x00002007',
}
identity_sha256 = hashlib.sha256(
    json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()
).hexdigest()
manifest = {
    'format': 1,
    'state': 'provisioned-and-validated',
    'path': '$Extend/$RootHealth',
    **identity,
    'record_locator': f"{journal['mft_record']}:{journal['mft_sequence']}",
    'identity_sha256': identity_sha256,
    'run_policy': 'ONE_AT_PROVISION_VALIDATED_AFTER_RESIZE',
    'provisioning_run_count': 1,
    'headers': {
        'state': 'EMPTY',
        'selected_generation': 2,
        'slot_generations': slot_generations,
        'max_entry_count': header['max_entry_count'],
        'entry_area_zero_sha256': header['entry_area_zero_sha256'],
    },
    'ownership': {
        'complete': True,
        'unique_owner': True,
        'self_nonoverlap': True,
        'journal_clusters': ownership['journal_clusters'],
    },
    'provisioning_write_exclusion': {
        'range_count': sum(len(value) for value in exclusion.values()),
        'sha256': hashlib.sha256(canonical_exclusion).hexdigest(),
    },
    'provenance': {
        'validator_sha256': validator_sha256,
        'ntfscp_binary_sha256': tool['binary_sha256'],
        'ntfscp_manifest_sha256': provenance_sha256,
        'ntfs_next_commit': tool['upstream_commit'],
        'ntfs_next_archive_sha256': tool['upstream_archive_sha256'],
        'seed_report_sha256': digest(seed_path),
        'provision_report_sha256': digest(provision_path),
        'validation_report_sha256': digest(validation_path),
    },
}
with output_path.open('x', encoding='utf-8') as handle:
    json.dump(manifest, handle, indent=2, sort_keys=True)
    handle.write('\n')
PY
rm -f -- "$journal_seed"
read -r roothealth_serial roothealth_journal_uuid roothealth_journal_record <<EOF
$(python3 -B - "$journal_manifest" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as handle:
    manifest = json.load(handle)
print(
    manifest['volume_serial'],
    manifest['journal_uuid'],
    manifest['record_locator'],
)
PY
)
EOF
case "$roothealth_serial:$roothealth_journal_uuid:$roothealth_journal_record" in
    *[!0-9A-Fa-f:-]*)
        echo 'RootHealth boot identity contains an unsafe kernel-command-line byte.' >&2
        exit 1
        ;;
esac
mount -o ro "$source_loop" "$source_mount"
mounted_source=1
ntfs-3g "$root_device" "$root_mount" -o permissions,windows_names,big_writes
mounted_root=1
mount "$esp_device" "$esp_mount"
mounted_esp=1

verify_source_deployment 'storage.img' "$source_mount"

python3 - "$source_mount" <<'PY'
import os
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
top_level_allowed = {
    '.ephemeral',
    '.remainder',
    '.rubbish',
    'boot',
    'master',
    'software',
    'the one',
}
reserved = {'CON', 'PRN', 'AUX', 'NUL'}
reserved.update(f'COM{number}' for number in range(1, 10))
reserved.update(f'LPT{number}' for number in range(1, 10))
invalid = set('<>:"/\\|?*')

for directory, directories, files in os.walk(root):
    names = directories + files
    folded = {}
    relative_directory = pathlib.Path(directory).relative_to(root)
    is_terminfo_bucket_directory = relative_directory == pathlib.Path('the one/settings/terminfo')
    is_terminfo_directory = (
        relative_directory == pathlib.Path('the one/settings/terminfo') or
        relative_directory.parts[:3] == ('the one', 'settings', 'terminfo')
    )
    for name in names:
        relative = (pathlib.Path(directory) / name).relative_to(root)
        if relative_directory == pathlib.Path('.') and name not in top_level_allowed:
            raise SystemExit(f'Non-default T1OS root entry is forbidden: {relative}')
        try:
            utf16_length = len(name.encode('utf-16-le')) // 2
        except UnicodeEncodeError as error:
            raise SystemExit(f'Filename is not valid Unicode for Windows: {relative}: {error}')
        if not name or any(ord(character) < 32 or character in invalid for character in name):
            raise SystemExit(f'Filename contains a Windows-forbidden character: {relative}')
        if name.endswith((' ', '.')):
            raise SystemExit(f'Filename ends with a Windows-forbidden space or dot: {relative}')
        if name.split('.', 1)[0].upper() in reserved:
            raise SystemExit(f'Filename uses a Windows-reserved device name: {relative}')
        if utf16_length > 255:
            raise SystemExit(f'Filename exceeds the NTFS component limit: {relative}')
        key = name.casefold()
        previous = folded.get(key)
        if previous is not None and previous != name and not is_terminfo_directory:
            raise SystemExit(
                f'Case-insensitive filename collision in {relative_directory}: '
                f'{previous!r} and {name!r}'
            )
        folded[key] = name

        if is_terminfo_bucket_directory and len(name.encode('utf-8')) != 1:
            raise SystemExit(f'Terminfo bucket cannot be converted to one-byte hexadecimal form: {relative}')

        target = pathlib.Path(directory) / name
        if target.is_symlink():
            raise SystemExit(f'T1OS root contains a forbidden symbolic link: {relative}')
        if not target.is_dir() and not target.is_file():
            raise SystemExit(f'T1OS root contains a Windows-inaccessible special file: {relative}')
PY

# Store terminfo with lowercase hexadecimal bucket and entry names. Ncurses'
# canonical tree contains both case-colliding buckets and case-colliding entry
# names, so encoding both components is required for unambiguous Windows
# access. The initramfs reconstructs the exact case-sensitive names in tmpfs.
rsync -aHAX --numeric-ids --delete \
    --exclude='/the one/settings/terminfo/*' \
    -- "$source_mount"/ "$root_mount"/

# Give the Windows-visible T1OS volume its branded drive icon in the system
# resources tree. Remove the legacy location when rebuilding from an older root.
install -d -m 0755 -- "$root_mount/the one/resources/system"
install -m 0644 -- "$drive_icon" "$root_mount/the one/resources/system/drive logo.ico"
rm -f -- "$root_mount/the one/resources/t1os-drive.ico"
printf '[Autorun]\r\nIcon="the one\\resources\\system\\drive logo.ico"\r\nLabel=%s\r\n' \
    "$root_label" > "$root_mount/autorun.inf"
test -s "$root_mount/the one/resources/system/drive logo.ico"
test ! -e "$root_mount/the one/resources/t1os-drive.ico"
tr -d '\r' < "$root_mount/autorun.inf" | grep -Fqx "Label=$root_label"

# The storage source can have been exercised as a bootable development image.
# Never turn its one-shot runtime graphics-recovery state into image defaults.
# Match only the canonical marker and the decimal-PID atomic names GODDESS uses.
graphics_recovery_settings="$root_mount/the one/settings"
graphics_recovery_marker="$graphics_recovery_settings/graphics recovery boot.json"
graphics_recovery_temporary_regex='.*/graphics recovery boot[.]json[.][0-9]+[.]new'
rm -f -- "$graphics_recovery_marker"
find "$graphics_recovery_settings" \
    -regextype posix-extended \
    -mindepth 1 \
    -maxdepth 1 \
    -regex "$graphics_recovery_temporary_regex" \
    -exec rm -f -- {} +
remaining_graphics_recovery_temporary=$(
    find "$graphics_recovery_settings" \
        -regextype posix-extended \
        -mindepth 1 \
        -maxdepth 1 \
        -regex "$graphics_recovery_temporary_regex" \
        -print \
        -quit
)
if [ -e "$graphics_recovery_marker" ] ||
   [ -L "$graphics_recovery_marker" ] ||
   [ -n "$remaining_graphics_recovery_temporary" ]; then
    echo 'The hardware root retained one-shot graphics-recovery state.' >&2
    exit 1
fi

terminfo_source="$source_mount/the one/settings/terminfo"
terminfo_target="$root_mount/the one/settings/terminfo"
if [ -d "$terminfo_source" ]; then
    mkdir -p "$terminfo_target"
    : > "$terminfo_target/index.tsv"
    for bucket in "$terminfo_source"/*; do
        [ -d "$bucket" ] || {
            echo "Unexpected non-directory terminfo bucket: $bucket" >&2
            exit 1
        }
        bucket_name=${bucket##*/}
        bucket_hex=$(printf '%s' "$bucket_name" | od -An -tx1 | tr -d ' \n')
        [ "${#bucket_hex}" = 2 ] || {
            echo "Terminfo bucket is not one byte: $bucket_name" >&2
            exit 1
        }
        mkdir -p "$terminfo_target/$bucket_hex"
        bucket_octal=$(printf '%03o' "$((0x$bucket_hex))")
        for entry in "$bucket"/*; do
            [ -f "$entry" ] || {
                echo "Unexpected non-file terminfo entry: $entry" >&2
                exit 1
            }
            entry_name=${entry##*/}
            entry_hex=$(printf '%s' "$entry_name" | od -An -tx1 | tr -d ' \n')
            [ -n "$entry_hex" ] || {
                echo "Terminfo entry has an empty encoded name: $entry" >&2
                exit 1
            }
            rsync -aHAX --numeric-ids -- "$entry" "$terminfo_target/$bucket_hex/$entry_hex"
            printf '%s\t%s\t%s\t%s\n' \
                "$bucket_hex" "$entry_hex" "$bucket_octal" "$entry_name" \
                >> "$terminfo_target/index.tsv"
        done
    done
fi
test -s "$terminfo_target/index.tsv"
test -s "$terminfo_target/6c/6c696e7578"
test -s "$terminfo_target/4c/4c46542d5043383530"
test ! -e "$terminfo_target/l"
test ! -e "$terminfo_target/L"
for obsolete in bin dev etc home lib lib64 mnt opt proc root run sbin srv sys tmp usr var; do
    rm -rf -- "$root_mount/$obsolete"
done
rm -rf -- \
    "$root_mount/the one/drivers/modules" \
    "$root_mount/the one/drivers/firmware"
mkdir -p \
    "$root_mount/the one/drivers/modules" \
    "$root_mount/the one/drivers/firmware" \
    "$root_mount/the one/drivers/tools" \
    "$root_mount/the one/drivers/settings" \
    "$root_mount/the one/settings" \
    "$root_mount/the one/logs"
tar --zstd -xf "$modules" -C "$root_mount"
module_releases=$(find "$root_mount/the one/drivers/modules" -mindepth 1 -maxdepth 1 -type d -printf '%f\n')
[ "$module_releases" = "$expected_kernel_release" ] || {
    echo "Kernel module archive release mismatch: expected $expected_kernel_release, found $module_releases" >&2
    exit 1
}
test -s "$root_mount/the one/drivers/modules/$expected_kernel_release/modules.dep"
test -s "$root_mount/the one/drivers/modules/module-manifest.sha256"
(cd "$root_mount/the one/drivers/modules" && sha256sum -c module-manifest.sha256)
for nvidia_module_name in nvidia nvidia-modeset nvidia-drm nvidia-uvm; do
    nvidia_module=$(find "$root_mount/the one/drivers/modules/$expected_kernel_release" \
        -type f -name "$nvidia_module_name.ko*" -print -quit)
    test -n "$nvidia_module"
    [ "$(modinfo -F version "$nvidia_module")" = "$nvidia_open_driver_version" ] || {
        echo "NVIDIA kernel module $nvidia_module_name does not match the selected userspace and firmware release." >&2
        exit 1
    }
done
grep -Eq '/nvidia-uvm\.ko[^:]*: .*\/nvidia\.ko' \
    "$root_mount/the one/drivers/modules/$expected_kernel_release/modules.dep"
tar --zstd -xf "$firmware" -C "$root_mount/the one/drivers/firmware"
test -s "$root_mount/the one/catalogue/graphics/catalogue.json"
test -s "$root_mount/the one/drivers/firmware/t1os-firmware-manifest.json"
cmp -s -- "$graphics_catalogue" "$root_mount/the one/catalogue/graphics/catalogue.json" || {
    echo 'The graphics catalogue in storage.img differs from the ready catalogue used for NVIDIA provenance.' >&2
    exit 1
}
cmp -s -- "$firmware_manifest" "$root_mount/the one/drivers/firmware/t1os-firmware-manifest.json" || {
    echo 'The firmware archive manifest differs from the NVIDIA firmware provenance manifest.' >&2
    exit 1
}
test -x "$root_mount/the one/drivers/tools/modprobe"
test -s "$root_mount/the one/drivers/settings/policy.json"
test -s "$root_mount/the one/build/drivers/driverserver.py"
test ! -e "$root_mount/the one/software/drivers"
chown 0:0 "$root_mount/the one/software/chromium/program/chrome-sandbox"
chmod 4755 "$root_mount/the one/software/chromium/program/chrome-sandbox"
test "$(stat -c '%u:%g:%a' "$root_mount/the one/software/chromium/program/chrome-sandbox")" = '0:0:4755'
if [ "$production" = 1 ]; then
    chromium_settings="$root_mount/the one/settings/chromium"
    chromium_profile="$chromium_settings/profile"
    chromium_config="$chromium_settings/config"
    chromium_font_cache="$chromium_settings/font-cache"
    chromium_legacy_cache="$chromium_settings/cache"
    mkdir -p "$chromium_settings"
    rm -rf -- \
        "$chromium_profile" \
        "$chromium_config" \
        "$chromium_font_cache" \
        "$chromium_legacy_cache" \
        "$chromium_settings/instance.lock" \
        "$chromium_settings/instance.sock"
    for directory in "$chromium_profile" "$chromium_config" "$chromium_font_cache"; do
        mkdir -p "$directory"
        chown 1000:1000 "$directory"
        chmod 0700 "$directory"
    done
    chown 1000:1000 "$chromium_settings"
    chmod 0700 "$chromium_settings"
fi
if find "$root_mount" -xdev -type l -print -quit | grep -q .; then
    echo 'T1OS root filesystem contains a forbidden symbolic link.' >&2
    find "$root_mount" -xdev -type l -print | head -20 >&2
    exit 1
fi

for forbidden in bin dev etc home lib lib64 mnt opt proc root run sbin srv sys tmp usr var; do
    if [ -e "$root_mount/$forbidden" ]; then
        echo "Forbidden Linux hierarchy path was created in T1OS: /$forbidden" >&2
        exit 1
    fi
done
printf '%s\n' 'T1OS hardware root filesystem' > "$root_mount/the one/settings/hardware-root.marker"
mkdir -p "$root_mount/the one/settings/audio"
python3 - "$root_mount/the one/settings/audio/audioserver.json" "$audio_codec" <<'PY'
import json
import os
import sys

path, codec = sys.argv[1], sys.argv[2].lower()
config = {}
try:
    with open(path, 'r', encoding='utf-8') as handle:
        loaded = json.load(handle)
        if isinstance(loaded, dict):
            config.update(loaded)
except FileNotFoundError:
    pass
config['autodevice'] = True
config['preferredcodec'] = codec or None
temporary = path + '.tmp'
with open(temporary, 'w', encoding='utf-8') as handle:
    json.dump(config, handle, indent=4, sort_keys=True)
    handle.write('\n')
    handle.flush()
    os.fsync(handle.fileno())
os.replace(temporary, path)
PY

if [ "$production" = 1 ]; then
    rm -rf -- "$root_mount/master" "$root_mount/the one/master" "$root_mount/.rubbish"
    find "$root_mount/the one/logs" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    find "$root_mount/the one/build" -type d -name __pycache__ -prune -exec rm -rf -- {} +
    for directory in "$chromium_profile" "$chromium_config" "$chromium_font_cache"; do
        [ -z "$(find "$directory" -mindepth 1 -print -quit)" ]
        [ "$(stat -c '%u:%g:%a' "$directory")" = '1000:1000:700' ]
    done
    test ! -e "$chromium_legacy_cache"
    test ! -e "$chromium_settings/instance.lock"
    test ! -e "$chromium_settings/instance.sock"
fi

# Recovery must not depend on the writable root it repairs. Remove the legacy
# root-resident placeholder, then create a complete immutable baseline and a
# file-by-file identity manifest on the dedicated recovery partition.
rm -rf -- "$root_mount/.recover"
recovery_settings="$root_mount/the one/settings/recovery"
mkdir -p "$recovery_settings"
recovery_manifest="$recovery_settings/files.tsv"
python3 -B - "$root_mount" "$recovery_manifest" "$root_label" "$source_root_sha256" <<'PY'
import hashlib
import os
from pathlib import Path
import stat
import sys

root = Path(sys.argv[1])
manifest = Path(sys.argv[2])
label = sys.argv[3]
generation = sys.argv[4]
excluded = {
    Path('.ephemeral'), Path('.recover'), Path('.remainder'), Path('.rubbish'),
    Path('master'), Path('software'), Path('the one/master'),
}

def excluded_path(relative: Path) -> bool:
    return any(relative == item or item in relative.parents for item in excluded)

rows = [('H', '1', label, generation, '-')]
for path in sorted(root.rglob('*'), key=lambda item: item.relative_to(root).as_posix()):
    relative_path = path.relative_to(root)
    relative = relative_path.as_posix()
    if excluded_path(relative_path) or path == manifest:
        continue
    if '\t' in relative or '\n' in relative or '\r' in relative:
        raise SystemExit(f'recovery path contains a forbidden control character: {relative!r}')
    metadata = path.lstat()
    mode = f'{stat.S_IMODE(metadata.st_mode):04o}'
    if stat.S_ISDIR(metadata.st_mode):
        rows.append(('D', relative, '0', '-', mode))
    elif stat.S_ISREG(metadata.st_mode):
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        rows.append(('F', relative, str(metadata.st_size), digest.hexdigest(), mode))
    else:
        raise SystemExit(f'recovery baseline contains an unsupported entry: {relative}')

temporary = manifest.with_suffix('.tsv.new')
with temporary.open('w', encoding='utf-8', newline='\n') as handle:
    for row in rows:
        handle.write('\t'.join(row) + '\n')
    handle.flush()
    os.fsync(handle.fileno())
os.replace(temporary, manifest)
PY
chmod 0444 "$recovery_manifest"
awk -F '\t' 'NR == 1 { valid = ($1 == "H" && $2 == "1") } END { exit valid && NR > 10 ? 0 : 1 }' "$recovery_manifest"

recovery_image="$work/recovery.squashfs"
mksquashfs "$root_mount" "$recovery_image" \
    -noappend -all-root -no-xattrs -no-progress -comp zstd \
    -b 1M -Xcompression-level 22 -tailends -no-exports \
    -e .ephemeral .recover .remainder .rubbish master software 'the one/master'
recovery_bytes=$(stat -c %s "$recovery_image")
recovery_partition_bytes=$(blockdev --getsize64 "$recovery_device")
[ "$recovery_bytes" -gt 4096 ] && [ "$recovery_bytes" -le "$recovery_partition_bytes" ] || {
    echo 'The recovery baseline does not fit in the dedicated recovery partition.' >&2
    exit 1
}
dd if="$recovery_image" of="$recovery_device" bs=4M conv=fsync,notrunc status=none
recovery_sha256=$(sha256sum "$recovery_image" | awk '{print $1}')
[ "$(head -c "$recovery_bytes" "$recovery_device" | sha256sum | awk '{print $1}')" = "$recovery_sha256" ]
rm -rf -- "$recovery_mount"
unsquashfs -no-progress -d "$recovery_mount" "$recovery_image" >/dev/null
cmp -s -- "$recovery_manifest" "$recovery_mount/the one/settings/recovery/files.tsv"

verify_source_deployment 'final USB root' "$root_mount"
final_source_build="$work/final-source-build"
final_source_drivers="$work/final-source-drivers"
stage_source_trees "$final_source_build" "$final_source_drivers"
final_build_source_sha256=$(source_tree_sha256 "$final_source_build")
final_drivers_source_sha256=$(source_tree_sha256 "$final_source_drivers")
final_chromium_source_sha256=$(source_tree_sha256 "$chromium_source")
[ "$final_build_source_sha256" = "$expected_build_sha256" ] || {
    echo 'The build source changed while the USB image was being created.' >&2
    exit 1
}
[ "$final_drivers_source_sha256" = "$expected_drivers_sha256" ] || {
    echo 'The driver source changed while the USB image was being created.' >&2
    exit 1
}
[ "$final_chromium_source_sha256" = "$expected_chromium_source_sha256" ] || {
    echo 'The Chromium runtime source changed while the USB image was being created.' >&2
    exit 1
}

mkdir -p "$esp_mount/boot/grub" "$esp_mount/EFI/BOOT" "$esp_mount/T1OS"
cp -- "$kernel" "$esp_mount/boot/vmlinuz-hardware"
cp -- "$initramfs" "$esp_mount/boot/initramfs-hardware"
cp -- "$grub_theme" "$esp_mount/boot/grub/t1os-theme.txt"
python3 - "$grub_background" "$esp_mount/boot/grub/t1os-black.png" <<'PY'
import base64
import sys

with open(sys.argv[1], 'r', encoding='ascii') as source:
    encoded = ''.join(source.read().split())
payload = base64.b64decode(encoded, validate=True)
if not payload.startswith(b'\x89PNG\r\n\x1a\n'):
    raise SystemExit('GRUB background source did not decode to a PNG')
with open(sys.argv[2], 'wb') as destination:
    destination.write(payload)
PY
cp -- "$compatibility_report" "$esp_mount/T1OS/desktop-compatibility-report.json"

root_uuid=$(blkid -s UUID -o value "$root_device")
[ -n "$root_uuid" ]
root_partuuid=$(blkid -s PARTUUID -o value "$root_partition")
recovery_partuuid=$(blkid -s PARTUUID -o value "$recovery_device")
esp_partuuid=$(blkid -s PARTUUID -o value "$esp_device")
[ -n "$root_partuuid" ] && [ -n "$recovery_partuuid" ] && [ -n "$esp_partuuid" ]
esp_uuid=$(blkid -s UUID -o value "$esp_device")
[ -n "$esp_uuid" ]
root_label_token=${root_label// /_}
case "$root_label_token" in
    ''|*[!A-Za-z0-9._-]*) echo 'The root label cannot be represented safely on the kernel command line.' >&2; exit 1 ;;
esac
luks_uuid=
if [ "$encrypt" = 1 ]; then
    luks_uuid=$(cryptsetup luksUUID "$root_partition")
    [ -n "$luks_uuid" ]
fi

sed \
    -e "s/@T1OS_ROOT_UUID@/$root_uuid/g" \
    -e "s/@T1OS_ROOT_PARTUUID@/$root_partuuid/g" \
    -e "s/@T1OS_LUKS_UUID@/$luks_uuid/g" \
    -e "s/@T1OS_RECOVERY_PARTUUID@/$recovery_partuuid/g" \
    -e "s/@T1OS_ESP_PARTUUID@/$esp_partuuid/g" \
    -e "s/@T1OS_ESP_UUID@/$esp_uuid/g" \
    -e "s/@T1OS_RECOVERY_SHA256@/$recovery_sha256/g" \
    -e "s/@T1OS_RECOVERY_BYTES@/$recovery_bytes/g" \
    -e "s/@T1OS_ROOT_LABEL_TOKEN@/$root_label_token/g" \
    -e "s/@T1OS_ROOTHEALTH_SERIAL@/$roothealth_serial/g" \
    -e "s/@T1OS_ROOTHEALTH_UUID@/$roothealth_journal_uuid/g" \
    -e "s/@T1OS_ROOTHEALTH_RECORD@/$roothealth_journal_record/g" \
    "$grub_template" > "$esp_mount/boot/grub/grub.cfg"

if grep -q '@T1OS_' "$esp_mount/boot/grub/grub.cfg"; then
    echo 'Generated GRUB configuration retains an unexpanded T1OS placeholder.' >&2
    exit 1
fi
grub-script-check "$esp_mount/boot/grub/grub.cfg"
grub-install \
    --target=x86_64-efi \
    --efi-directory="$esp_mount" \
    --boot-directory="$esp_mount/boot" \
    --removable \
    --no-nvram \
    --recheck
test -s "$esp_mount/EFI/BOOT/BOOTX64.EFI"
test -s "$esp_mount/boot/grub/t1os-theme.txt"
test -s "$esp_mount/boot/grub/t1os-black.png"

if [ "$secure_boot" = 1 ]; then
    mkdir -p "$esp_mount/EFI/T1OS"
    roothealth_cmdline="t1os.roothealth.serial=$roothealth_serial t1os.roothealth.uuid=$roothealth_journal_uuid t1os.roothealth.record=$roothealth_journal_record"
    recovery_identity="t1os.recoverypart=SCAN t1os.esppart=UUID=$esp_uuid t1os.recovery.sha256=$recovery_sha256 t1os.recovery.bytes=$recovery_bytes t1os.rootlabel=$root_label_token"
    if [ "$encrypt" = 1 ]; then
        root_identity="rd.luks.uuid=$luks_uuid t1os.luks.name=t1os-root root=/dev/mapper/t1os-root"
    else
        root_identity="root=UUID=$root_uuid"
    fi
    cmdline="init=/init $root_identity rootwait rw rootfstype=ntfs3 t1os.rootwait=60 $roothealth_cmdline $recovery_identity t1os.graphics=$secure_graphics t1os.quiet=1 nvidia_drm.modeset=1 nvidia_drm.fbdev=1 nouveau.config=NvGspFw=0 vt.global_cursor_default=0 console=ttyS0,115200n8 quiet loglevel=0 logo.nologo"
    recovery_cmdline="init=/init $root_identity rootwait ro rootfstype=ntfs3 t1os.rootwait=60 $roothealth_cmdline $recovery_identity t1os.graphics=framebuffer t1os.recovery=1 module_blacklist=amdgpu,radeon,nouveau,nvidia,nvidia_modeset,nvidia_drm,nvidia_uvm,nvidia_peermem,i915,xe,ast,mgag200,qxl,bochs_drm,vmwgfx,virtio_gpu vt.global_cursor_default=0 console=ttyS0,115200n8 quiet loglevel=0 logo.nologo"

    ukify build \
        --linux="$kernel" \
        --initrd="$initramfs" \
        --cmdline="$cmdline" \
        --secureboot-private-key="$secure_key" \
        --secureboot-certificate="$secure_certificate" \
        --output="$esp_mount/EFI/BOOT/BOOTX64.EFI"
    ukify build \
        --linux="$kernel" \
        --initrd="$initramfs" \
        --cmdline="$recovery_cmdline" \
        --secureboot-private-key="$secure_key" \
        --secureboot-certificate="$secure_certificate" \
        --output="$esp_mount/EFI/T1OS/RECOVERYX64.EFI"
    sbverify --list "$esp_mount/EFI/BOOT/BOOTX64.EFI"
    sbverify --list "$esp_mount/EFI/T1OS/RECOVERYX64.EFI"
fi

export T1OS_ROOT_UUID="$root_uuid"
export T1OS_ROOT_PARTUUID="$root_partuuid"
export T1OS_RECOVERY_PARTUUID="$recovery_partuuid"
export T1OS_ESP_PARTUUID="$esp_partuuid"
export T1OS_ESP_UUID="$esp_uuid"
export T1OS_RECOVERY_SHA256="$recovery_sha256"
export T1OS_RECOVERY_BYTES="$recovery_bytes"
export T1OS_LUKS_UUID="$luks_uuid"
export T1OS_ENCRYPTED="$encrypt"
export T1OS_IMAGE_SIZE_GIB="$size_gib"
export T1OS_SECURE_BOOT="$secure_boot"
export T1OS_AUDIO_CODEC="$audio_codec"
export T1OS_ROOT_LABEL="$root_label"
export T1OS_COMPATIBILITY_SHA256="$(sha256sum "$compatibility_report" | awk '{print $1}')"
export T1OS_BUILD_SOURCE_SHA256="$expected_build_sha256"
export T1OS_DRIVERS_SOURCE_SHA256="$expected_drivers_sha256"
export T1OS_CHROMIUM_SOURCE_SHA256="$expected_chromium_source_sha256"
export T1OS_SOURCE_ROOT_SHA256="$source_root_sha256"
printf '%s  %s\n' "$graphics_catalogue_sha256" "$graphics_catalogue" | sha256sum -c -
printf '%s  %s\n' "$firmware_manifest_sha256" "$firmware_manifest" | sha256sum -c -
cmp -s -- "$graphics_catalogue" "$root_mount/the one/catalogue/graphics/catalogue.json"
cmp -s -- "$firmware_manifest" "$root_mount/the one/drivers/firmware/t1os-firmware-manifest.json"
export T1OS_NVIDIA_OPEN_DRIVER_VERSION="$nvidia_open_driver_version"
export T1OS_NVIDIA_OPEN_DRIVER_RUNFILE_SHA256="$nvidia_open_driver_runfile_sha256"
export T1OS_GRAPHICS_CATALOGUE_SHA256="$graphics_catalogue_sha256"
export T1OS_FIRMWARE_MANIFEST_SHA256="$firmware_manifest_sha256"
export T1OS_KERNEL_RELEASE="$expected_kernel_release"
python3 -B - "$esp_mount/T1OS/image-manifest.json" <<'PY'
import json
import os
import platform
import sys

manifest = {
    'format': 2,
    'image_type': 'T1OS removable UEFI hardware image',
    'architecture': 'x86_64',
    'partition_table': 'GPT',
    'efi_fallback': 'EFI/BOOT/BOOTX64.EFI',
    'image_size_gib': int(os.environ['T1OS_IMAGE_SIZE_GIB']),
    'root_uuid': os.environ['T1OS_ROOT_UUID'],
    'root_partuuid': os.environ['T1OS_ROOT_PARTUUID'],
    'recovery_partuuid': os.environ['T1OS_RECOVERY_PARTUUID'],
    'esp_partuuid': os.environ['T1OS_ESP_PARTUUID'],
    'esp_uuid': os.environ['T1OS_ESP_UUID'],
    'recovery_sha256': os.environ['T1OS_RECOVERY_SHA256'],
    'recovery_bytes': int(os.environ['T1OS_RECOVERY_BYTES']),
    'recovery_filesystem': 'squashfs-zstd',
    'root_filesystem': 'ntfs',
    'root_label': os.environ['T1OS_ROOT_LABEL'],
    'windows_native_root': os.environ['T1OS_ENCRYPTED'] != '1',
    'luks_uuid': os.environ['T1OS_LUKS_UUID'] or None,
    'encrypted': os.environ['T1OS_ENCRYPTED'] == '1',
    'secure_boot': os.environ['T1OS_SECURE_BOOT'] == '1',
    'preferred_audio_codec': os.environ['T1OS_AUDIO_CODEC'] or None,
    'desktop_compatibility_report_sha256': os.environ['T1OS_COMPATIBILITY_SHA256'],
    'build_source_sha256': os.environ['T1OS_BUILD_SOURCE_SHA256'],
    'drivers_source_sha256': os.environ['T1OS_DRIVERS_SOURCE_SHA256'],
    'chromium_source_sha256': os.environ['T1OS_CHROMIUM_SOURCE_SHA256'],
    'source_root_sha256': os.environ['T1OS_SOURCE_ROOT_SHA256'],
    'nvidia_open_driver_version': os.environ['T1OS_NVIDIA_OPEN_DRIVER_VERSION'],
    'nvidia_open_driver_runfile_sha256': os.environ['T1OS_NVIDIA_OPEN_DRIVER_RUNFILE_SHA256'],
    'graphics_catalogue_sha256': os.environ['T1OS_GRAPHICS_CATALOGUE_SHA256'],
    'firmware_manifest_sha256': os.environ['T1OS_FIRMWARE_MANIFEST_SHA256'],
    'kernel_release': os.environ['T1OS_KERNEL_RELEASE'],
    'boot_strategy': 'signed-unified-kernel-image' if os.environ['T1OS_SECURE_BOOT'] == '1' else 'grub-removable',
    'build_host': platform.platform(),
}
with open(sys.argv[1], 'w', encoding='utf-8') as handle:
    json.dump(manifest, handle, indent=2)
    handle.write('\n')
PY

sync
umount "$root_mount"; mounted_root=0
python3 -B "$journal_validator" validate "$root_device" \
    --require-one-run --require-zero-entry-area \
    --report "$work/roothealth-final.json"
python3 -B - \
    "$journal_manifest" "$work/roothealth-final.json" \
    "$esp_mount/T1OS/image-manifest.json" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import sys

with Path(sys.argv[1]).open(encoding='utf-8') as handle:
    expected = json.load(handle)
with Path(sys.argv[2]).open(encoding='utf-8') as handle:
    report = json.load(handle)
embedded_path = Path(sys.argv[3])
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
    json.dumps(
        journal['write_exclusion'], sort_keys=True, separators=(',', ':')
    ).encode()
).hexdigest()
if identity_hash != expected['identity_sha256']:
    raise SystemExit('final journal identity changed after root population')
if exclusion_hash != expected['provisioning_write_exclusion']['sha256']:
    raise SystemExit('final journal physical exclusions changed during image build')
if journal['run_count'] != 1 or not all(report['checks'].values()):
    raise SystemExit('final image lost the one-run complete journal proof')
if any(journal[key] != '0x00002007' for key in (
    'standard_information_flags', 'file_name_flags',
    'extend_i30_file_name_flags', 'required_protected_flags'
)):
    raise SystemExit('final image journal flags changed')
if not all(journal['ownership'].get(key) is True for key in (
    'complete', 'unique_owner', 'self_nonoverlap'
)):
    raise SystemExit('final image journal ownership proof is incomplete')
if header['selected_generation'] != 2 or \
        [slot['generation'] for slot in header['slots']] != [1, 2] or \
        any(slot['state'] != 'EMPTY' for slot in header['slots']):
    raise SystemExit('final image journal headers are not canonical EMPTY')

def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

expected['final_validation'] = {
    'report_sha256': file_digest(sys.argv[2]),
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

def atomic_json(path, value):
    temporary = path.with_name(path.name + '.roothealth-tmp')
    if temporary.exists():
        raise SystemExit(f'refusing stale journal manifest temporary file: {temporary}')
    with temporary.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)

atomic_json(Path(sys.argv[1]), expected)
with embedded_path.open(encoding='utf-8') as handle:
    embedded = json.load(handle)
embedded['roothealth_journal'] = expected
atomic_json(embedded_path, embedded)
PY
umount "$esp_mount"; mounted_esp=0
umount "$source_mount"; mounted_source=0

ntfsfix -n "$root_device"
# Linux's vfat mount can leave the freshly created primary boot-sector dirty
# flag different from its backup even after a clean unmount. Repair only this
# build-owned ESP, then require the read-only verification to be clean.
vfat_repair_status=0
fsck.vfat -a "$esp_device" || vfat_repair_status=$?
[ "$vfat_repair_status" -le 1 ]
fsck.vfat -n "$esp_device"
sgdisk --verify "$image_loop"

if [ "$mapper_open" = 1 ]; then
    cryptsetup close "$mapper_name"
    mapper_open=0
fi
if losetup "$source_loop" >/dev/null 2>&1; then
    losetup -d "$source_loop"
fi
source_loop=
if losetup "$image_loop" >/dev/null 2>&1; then
    losetup -d "$image_loop"
fi
image_loop=

sgdisk --verify "$output"
rm -f -- "$published_output"
cp --sparse=always -- "$output" "$published_output"
sync -f "$published_output"
[ "$(stat -c %s "$published_output")" = "$(stat -c %s "$output")" ]
cmp -- "$output" "$published_output"
printf 'ROOT_UUID=%s\n' "$root_uuid"
printf 'ROOT_PARTUUID=%s\n' "$root_partuuid"
printf 'RECOVERY_PARTUUID=%s\n' "$recovery_partuuid"
printf 'ESP_PARTUUID=%s\n' "$esp_partuuid"
printf 'ESP_UUID=%s\n' "$esp_uuid"
printf 'RECOVERY_SHA256=%s\n' "$recovery_sha256"
printf 'RECOVERY_BYTES=%s\n' "$recovery_bytes"
printf 'LUKS_UUID=%s\n' "$luks_uuid"
printf 'BUILD_SOURCE_SHA256=%s\n' "$expected_build_sha256"
printf 'DRIVERS_SOURCE_SHA256=%s\n' "$expected_drivers_sha256"
printf 'CHROMIUM_SOURCE_SHA256=%s\n' "$expected_chromium_source_sha256"
python3 -B - "$journal_manifest" <<'PY'
import base64
from pathlib import Path
import sys

print('ROOTHEALTH_JOURNAL_BASE64=' + base64.b64encode(Path(sys.argv[1]).read_bytes()).decode('ascii'))
PY
'@

$buildExitCode = 1
$buildInvocationError = $null
$normalizedBuildCommand = $buildCommand.Replace("`r", '') + "`n# end"
try {
    try {
        $buildOutput = $normalizedBuildCommand |
            & wsl.exe -d Ubuntu -u root --exec bash -s -- $wslSource $wslKernel $wslInitramfs $wslModules $wslFirmware $wslGrubTemplate $wslPartial $ImageSizeGiB $encryptValue $wslPassphrase $productionValue $secureBootValue $wslSecureBootKey $wslSecureBootCertificate $SecureBootGraphics $PreferredAudioCodec $wslGrubTheme $wslCompatibilityReport $wslGrubBackground $rootVolumeLabel $wslBuildSource $wslDriversSource $wslGraphicsCatalogue $wslFirmwareManifest $nvidiaOpenDriverVersion $nvidiaOpenDriverRunfileHash $graphicsCatalogueHash $firmwareManifestHash $kernelRelease $wslDriveIcon $wslChromiumSoftware $sourceRootHashBefore $wslJournalValidator $journalValidatorHash $wslNtfscp $wslNtfscpProvenance $ntfscpProvenanceHash $ntfscpBinaryHash
        $buildExitCode = $LASTEXITCODE
    }
    catch {
        $buildInvocationError = $_
    }
}
finally {
    $sourceRootHashAfter = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $sourceRootImage
    ).Hash.ToLowerInvariant()
    if ($sourceRootHashAfter -cne $sourceRootHashBefore) {
        throw "Hardware image creation changed its storage.img source: $sourceRootHashBefore -> $sourceRootHashAfter"
    }
}
if ($buildInvocationError) {
    throw $buildInvocationError
}
if ($buildExitCode -ne 0) {
    if ($buildOutput) {
        $buildOutput | ForEach-Object { Write-Host $_ }
    }
    throw "Hardware USB image build failed (exit code $buildExitCode)."
}

if (-not (Test-Path -LiteralPath $partialPath -PathType Leaf)) {
    throw 'The hardware USB image was not created.'
}

$rootUuidLine = $buildOutput | Where-Object { $_ -match '^ROOT_UUID=' } | Select-Object -Last 1
$rootPartUuidLine = $buildOutput | Where-Object { $_ -match '^ROOT_PARTUUID=' } | Select-Object -Last 1
$recoveryPartUuidLine = $buildOutput | Where-Object { $_ -match '^RECOVERY_PARTUUID=' } | Select-Object -Last 1
$espPartUuidLine = $buildOutput | Where-Object { $_ -match '^ESP_PARTUUID=' } | Select-Object -Last 1
$espUuidLine = $buildOutput | Where-Object { $_ -match '^ESP_UUID=' } | Select-Object -Last 1
$recoveryHashLine = $buildOutput | Where-Object { $_ -match '^RECOVERY_SHA256=' } | Select-Object -Last 1
$recoveryBytesLine = $buildOutput | Where-Object { $_ -match '^RECOVERY_BYTES=' } | Select-Object -Last 1
$luksUuidLine = $buildOutput | Where-Object { $_ -match '^LUKS_UUID=' } | Select-Object -Last 1
$buildSourceHashLine = $buildOutput | Where-Object { $_ -match '^BUILD_SOURCE_SHA256=' } | Select-Object -Last 1
$driversSourceHashLine = $buildOutput | Where-Object { $_ -match '^DRIVERS_SOURCE_SHA256=' } | Select-Object -Last 1
$chromiumSourceHashLine = $buildOutput | Where-Object { $_ -match '^CHROMIUM_SOURCE_SHA256=' } | Select-Object -Last 1
$journalManifestLine = $buildOutput | Where-Object { $_ -match '^ROOTHEALTH_JOURNAL_BASE64=' } | Select-Object -Last 1
if (-not $rootUuidLine -or -not $rootPartUuidLine -or -not $recoveryPartUuidLine -or
    -not $espPartUuidLine -or -not $espUuidLine -or
    -not $recoveryHashLine -or -not $recoveryBytesLine) {
    throw 'The image build did not report its root UUID.'
}
if (-not $buildSourceHashLine -or -not $driversSourceHashLine -or -not $chromiumSourceHashLine) {
    throw 'The image build did not report its source provenance hashes.'
}
if (-not $journalManifestLine) {
    throw 'The image build did not report its validated RootHealth journal manifest.'
}
$rootUuid = ($rootUuidLine -split '=', 2)[1]
$rootPartUuid = ($rootPartUuidLine -split '=', 2)[1]
$recoveryPartUuid = ($recoveryPartUuidLine -split '=', 2)[1]
$espPartUuid = ($espPartUuidLine -split '=', 2)[1]
$espUuid = ($espUuidLine -split '=', 2)[1]
$recoveryHash = ($recoveryHashLine -split '=', 2)[1]
$recoveryBytes = [int64](($recoveryBytesLine -split '=', 2)[1])
$luksUuid = if ($luksUuidLine) { ($luksUuidLine -split '=', 2)[1] } else { '' }
$buildSourceHash = ($buildSourceHashLine -split '=', 2)[1]
$driversSourceHash = ($driversSourceHashLine -split '=', 2)[1]
$chromiumSourceHash = ($chromiumSourceHashLine -split '=', 2)[1]
if (
    $buildSourceHash -notmatch '^[0-9a-f]{64}$' -or
    $driversSourceHash -notmatch '^[0-9a-f]{64}$' -or
    $chromiumSourceHash -notmatch '^[0-9a-f]{64}$'
) {
    throw 'The image build reported invalid source provenance hashes.'
}
if (
    $rootPartUuid -notmatch '^[0-9a-f-]+$' -or
    $recoveryPartUuid -notmatch '^[0-9a-f-]+$' -or
    $espPartUuid -notmatch '^[0-9a-f-]+$' -or
    $espUuid -notmatch '^[0-9A-Fa-f-]{9}$' -or
    $recoveryHash -notmatch '^[0-9a-f]{64}$' -or
    $recoveryBytes -le 4096 -or $recoveryBytes -gt 3221225472
) {
    throw 'The image build reported invalid recovery partition identity.'
}
try {
    $journalManifestBytes = [System.Convert]::FromBase64String(
        ($journalManifestLine -split '=', 2)[1]
    )
    $journalManifestJson = [System.Text.Encoding]::UTF8.GetString($journalManifestBytes)
    $rootHealthJournal = $journalManifestJson | ConvertFrom-Json
}
catch {
    throw "The image build reported an invalid RootHealth journal manifest: $($_.Exception.Message)"
}
if (
    [string]$rootHealthJournal.state -cne 'provisioned-and-validated' -or
    [string]$rootHealthJournal.path -cne '$Extend/$RootHealth' -or
    [int64]$rootHealthJournal.logical_bytes -ne 134217728 -or
    [string]$rootHealthJournal.required_flags -cne '0x00002007' -or
    [string]$rootHealthJournal.headers.state -cne 'EMPTY' -or
    -not [bool]$rootHealthJournal.ownership.complete -or
    -not [bool]$rootHealthJournal.ownership.unique_owner -or
    -not [bool]$rootHealthJournal.ownership.self_nonoverlap -or
    [string]$rootHealthJournal.provenance.validator_sha256 -cne $journalValidatorHash -or
    [string]$rootHealthJournal.provenance.ntfscp_binary_sha256 -cne $ntfscpBinaryHash -or
    [string]$rootHealthJournal.provenance.ntfscp_manifest_sha256 -cne $ntfscpProvenanceHash
) {
    throw 'The image build returned an incomplete or source-unbound RootHealth journal manifest.'
}

$imageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $partialPath).Hash.ToLowerInvariant()

$manifest = [ordered]@{
    format = 2
    state = 'validated'
    image = [System.IO.Path]::GetFileName($OutputPath)
    bytes = (Get-Item -LiteralPath $partialPath).Length
    sha256 = $imageHash
    root_uuid = $rootUuid
    root_partuuid = $rootPartUuid
    recovery_partuuid = $recoveryPartUuid
    esp_partuuid = $espPartUuid
    esp_uuid = $espUuid
    recovery_sha256 = $recoveryHash
    recovery_bytes = $recoveryBytes
    recovery_filesystem = 'squashfs-zstd'
    root_filesystem = 'ntfs'
    root_label = $rootVolumeLabel
    windows_native_root = -not [bool]$EncryptRoot
    luks_uuid = if ($luksUuid) { $luksUuid } else { $null }
    encrypted = [bool]$EncryptRoot
    production = [bool]$Production
    secure_boot = [bool]$secureBoot
    preferred_audio_codec = if ($PreferredAudioCodec) { $PreferredAudioCodec.ToLowerInvariant() } else { $null }
    kernel_release = $kernelRelease
    kernel_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $kernelPath).Hash.ToLowerInvariant()
    initramfs_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $initramfsPath).Hash.ToLowerInvariant()
    modules_sha256 = $modulesArchiveHash
    firmware_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $firmwarePath).Hash.ToLowerInvariant()
    firmware_manifest_sha256 = $firmwareManifestHash
    graphics_catalogue_sha256 = $graphicsCatalogueHash
    nvidia_open_driver_version = $nvidiaOpenDriverVersion
    nvidia_open_driver_runfile_sha256 = $nvidiaOpenDriverRunfileHash
    module_loader_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $moduleLoaderPath).Hash.ToLowerInvariant()
    desktop_compatibility_report_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $compatibilityReportPath).Hash.ToLowerInvariant()
    build_source_sha256 = $buildSourceHash
    drivers_source_sha256 = $driversSourceHash
    chromium_source_sha256 = $chromiumSourceHash
    source_root_sha256 = $sourceRootHashBefore
    roothealth_journal = $rootHealthJournal
}
$manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $partialManifestPath -Encoding utf8

# Keep the last validated image and manifest until the replacement and its
# sidecar have both been built. If either final move fails, restore the pair.
foreach ($staleBackup in @($previousImagePath, $previousManifestPath)) {
    if (Test-Path -LiteralPath $staleBackup) {
        throw "A preserved hardware image recovery artifact exists: $staleBackup"
    }
}

$previousImageSaved = $false
$previousManifestSaved = $false
$newImageInstalled = $false
$newManifestInstalled = $false
$swapSucceeded = $false
try {
    if ($Force -and (Test-Path -LiteralPath $OutputPath)) {
        Move-Item -LiteralPath $OutputPath -Destination $previousImagePath
        $previousImageSaved = $true
    }
    if ($Force -and (Test-Path -LiteralPath $manifestPath)) {
        Move-Item -LiteralPath $manifestPath -Destination $previousManifestPath
        $previousManifestSaved = $true
    }

    Move-Item -LiteralPath $partialPath -Destination $OutputPath
    $newImageInstalled = $true
    Move-Item -LiteralPath $partialManifestPath -Destination $manifestPath
    $newManifestInstalled = $true
    $swapSucceeded = $true
}
catch {
    if ($newImageInstalled -and (Test-Path -LiteralPath $OutputPath)) {
        Remove-Item -LiteralPath $OutputPath -Force
    }
    if ($newManifestInstalled -and (Test-Path -LiteralPath $manifestPath)) {
        Remove-Item -LiteralPath $manifestPath -Force
    }
    if ($previousImageSaved -and (Test-Path -LiteralPath $previousImagePath)) {
        Move-Item -LiteralPath $previousImagePath -Destination $OutputPath
    }
    if ($previousManifestSaved -and (Test-Path -LiteralPath $previousManifestPath)) {
        Move-Item -LiteralPath $previousManifestPath -Destination $manifestPath
    }
    throw
}
finally {
    if ($swapSucceeded) {
        foreach ($backup in @($previousImagePath, $previousManifestPath)) {
            if (Test-Path -LiteralPath $backup) {
                Remove-Item -LiteralPath $backup -Force
            }
        }
    }
}

Write-Host "Validated T1OS UEFI USB image: $OutputPath"
Write-Host "SHA-256: $imageHash"
Write-Host "Root UUID: $rootUuid"
Write-Host "Recovery SHA-256: $recoveryHash ($recoveryBytes bytes)"
Write-Host "Source storage SHA-256: $sourceRootHashBefore"
if ($luksUuid) { Write-Host "LUKS UUID: $luksUuid" }
Write-Host "Manifest: $manifestPath"
