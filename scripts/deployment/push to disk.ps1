[CmdletBinding()]
param(
    [switch]$UsbDrive,

    [switch]$ValidateTargetOnly,

    [switch]$ValidateManagedTreeOnly,

    [switch]$VerifyManagedReleaseOnly,

    [switch]$SyncManagedReleaseOnly,

    [switch]$Fast,

    [switch]$Full
)

$ErrorActionPreference = 'Stop'
$deploymentStopwatch = [Diagnostics.Stopwatch]::StartNew()
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $PSScriptRoot '..\common.ps1')
. (Join-Path $PSScriptRoot '..\deployment state.ps1')
$buildSource = Join-Path $projectRoot 'source\build software'
$bootSource = Join-Path $projectRoot 'source\boot'
$driversSource = Join-Path $projectRoot 'source\drivers'
$graphicsCatalogueSource = Join-Path $projectRoot 'source\catalogue\graphics'
$virtualBoxCatalogueSource = Join-Path $projectRoot 'source\catalogue\virtualbox'
$virtualBoxSoftwareSource = Join-Path $projectRoot 'source\software\virtualbox'
$virtualBoxSettingsSource = Join-Path $projectRoot 'source\settings\virtualbox'
$audioCatalogueSource = Join-Path $projectRoot 'source\catalogue\audio'
$audioSoftwareSource = Join-Path $projectRoot 'source\software\audio'
$networkCatalogueSource = Join-Path $projectRoot 'source\catalogue\network'
$networkSoftwareSource = Join-Path $projectRoot 'source\software\network'
$networkSettingsSource = Join-Path $projectRoot 'source\settings\network'
$mediaSettingsSource = Join-Path $projectRoot 'source\settings\media'
$chromiumSoftwareSource = Join-Path $projectRoot 'source\software\chromium'
$nativeProtocolHeader = Join-Path $projectRoot 'source\native\video\t1_media_decode_protocol.h'
$nativeWatchdogHeader = Join-Path $projectRoot 'source\native\video\t1_media_decode_watchdog.h'
$chromiumOverlayRoot = Join-Path $projectRoot 'resource\chromium-source\150.0.7871.181'
$chromiumProtocolHeader = Join-Path $chromiumOverlayRoot 'overlay\media\gpu\t1os\t1_media_decode_protocol.h'
$chromiumSourceManifest = Join-Path $chromiumOverlayRoot 'manifest.json'
$runtimePathContractSource = Join-Path $projectRoot 'source\settings\runtime paths.json'
$imageCatalogueSource = Join-Path $projectRoot 'source\catalogue\image'
$pythonSoftwareSource = Join-Path $projectRoot 'source\software\python'
$systemSoftwareSource = Join-Path $projectRoot 'source\software\system'
$pythonCatalogueSource = Join-Path $projectRoot 'source\catalogue\python'
$pythonManifestSource = Join-Path $pythonSoftwareSource 'manifest.json'
$pythonReleaseLockSource = Join-Path $projectRoot 'source\python\locks\release.json'
$pythonRuntimeConfigSource = Join-Path $projectRoot 'source\python\build\runtime.json'
$pythonRuntimeVerifier = Join-Path $PSScriptRoot '..\tests\test python runtime.ps1'
$bootPolicyBuilder = Join-Path $PSScriptRoot '..\build\build boot protected roots.py'
$bootPolicyDirectory = Join-Path $projectRoot 'development\hardware boot policy'
$bootPolicyManifest = Join-Path $bootPolicyDirectory 'protected-roots.json'
$resourceSource = Join-Path $projectRoot 'resource'
$logoSource = Join-Path $resourceSource 'logos'
$fatalScreenSource = Join-Path $projectRoot 'flash\red_screen_of_death.png'
$imagePath = Join-Path $projectRoot 'environment\software\storage.img'
$mountPoint = if ($UsbDrive) { '/mnt/t1drive' } else { '/mnt/t1fs' }
$buildDestination = "$mountPoint/the one/build"
$bootDestination = "$mountPoint/boot"
$driversDestination = "$mountPoint/the one/drivers"
$graphicsCatalogueDestination = "$mountPoint/the one/catalogue/graphics"
$virtualBoxCatalogueDestination = "$mountPoint/the one/catalogue/virtualbox"
$virtualBoxSoftwareDestination = "$mountPoint/the one/software/virtualbox"
$virtualBoxSettingsDestination = "$mountPoint/the one/settings/virtualbox"
$audioCatalogueDestination = "$mountPoint/the one/catalogue/audio"
$audioSoftwareDestination = "$mountPoint/the one/software/audio"
$networkCatalogueDestination = "$mountPoint/the one/catalogue/network"
$networkSoftwareDestination = "$mountPoint/the one/software/network"
$networkSettingsDestination = "$mountPoint/the one/settings/network"
$mediaSettingsDestination = "$mountPoint/the one/settings/media"
$chromiumSoftwareDestination = "$mountPoint/the one/software/chromium"
$runtimePathContractDestination = "$mountPoint/the one/settings/runtime paths.json"
$imageCatalogueDestination = "$mountPoint/the one/catalogue/image"
$pythonSoftwareDestination = "$mountPoint/the one/software/python"
$pythonCatalogueDestination = "$mountPoint/the one/catalogue/python"
$fontDestination = "$mountPoint/the one/resources/fonts"

function Get-T1OSUsbDriveTarget {
    $requiredRelativePaths = @(
        'boot',
        'the one',
        'the one\build',
        'the one\settings\runtime paths.json',
        'the one\resources\t1os-drive.ico',
        'autorun.inf'
    )

    $candidates = @(
        Get-Volume -ErrorAction Stop |
            Where-Object {
                $_.DriveLetter -and (
                    [string]$_.DriveLetter -ceq 'D' -or
                    ([string]$_.FileSystemLabel).StartsWith(
                        'T1OS',
                        [StringComparison]::OrdinalIgnoreCase
                    )
                )
            } |
            ForEach-Object {
                $volume = $_
                $driveLetter = ([string]$volume.DriveLetter).ToUpperInvariant()
                $root = "$driveLetter`:\"
                $partition = Get-Partition -DriveLetter $driveLetter -ErrorAction Stop
                $disk = $partition | Get-Disk -ErrorAction Stop

                if (
                    $disk.BusType -cne 'USB' -or
                    $disk.IsBoot -or
                    $disk.IsSystem -or
                    $disk.IsReadOnly -or
                    [string]$volume.FileSystemType -cne 'NTFS' -or
                    [string]$volume.HealthStatus -cne 'Healthy'
                ) {
                    return
                }

                foreach ($relativePath in $requiredRelativePaths) {
                    if (-not (Test-Path -LiteralPath (Join-Path $root $relativePath))) {
                        return
                    }
                }

                $autorun = Get-Content -LiteralPath (Join-Path $root 'autorun.inf') -Raw
                if (
                    $autorun -notmatch '(?im)^\s*Label=T1OS(?:\s|$)' -or
                    $autorun -notmatch '(?im)^\s*Icon="the one\\resources\\t1os-drive\.ico"\s*$'
                ) {
                    return
                }

                [pscustomobject]@{
                    DriveLetter = $driveLetter
                    Root = $root
                    DriveSource = "$driveLetter`:"
                    Label = ([string]$volume.FileSystemLabel).Trim()
                    DiskNumber = [int]$disk.Number
                    SerialNumber = ([string]$disk.SerialNumber).Trim()
                    Model = ([string]$disk.FriendlyName).Trim()
                }
            }
    )

    $driveD = @($candidates | Where-Object { $_.DriveLetter -ceq 'D' })
    if ($driveD.Count -eq 1) {
        return $driveD[0]
    }
    if ($candidates.Count -eq 1) {
        return $candidates[0]
    }
    if ($candidates.Count -eq 0) {
        throw 'No healthy NTFS T1OS USB drive was found at D: or on a volume whose name starts with T1OS.'
    }

    $identities = $candidates | ForEach-Object {
        "$($_.DriveLetter): '$($_.Label)' on USB disk $($_.DiskNumber)"
    }
    throw "More than one T1OS USB drive was found. Keep only the intended target connected: $($identities -join '; ')"
}

foreach ($requiredDirectory in @($buildSource, $bootSource, $driversSource, $graphicsCatalogueSource, $virtualBoxCatalogueSource, $virtualBoxSoftwareSource, $virtualBoxSettingsSource, $audioCatalogueSource, $audioSoftwareSource, $networkCatalogueSource, $networkSoftwareSource, $networkSettingsSource, $chromiumSoftwareSource, $imageCatalogueSource, $pythonSoftwareSource, $systemSoftwareSource, $pythonCatalogueSource, $resourceSource, $logoSource)) {
    if (-not (Test-Path -LiteralPath $requiredDirectory -PathType Container)) {
        throw "Source directory not found: $requiredDirectory"
    }
}

$requiredFiles = @(
    $runtimePathContractSource,
    $nativeProtocolHeader,
    $nativeWatchdogHeader,
    $chromiumProtocolHeader,
    $chromiumSourceManifest,
    $pythonManifestSource,
    $pythonReleaseLockSource,
    $pythonRuntimeConfigSource,
    $pythonRuntimeVerifier,
    $bootPolicyBuilder,
    $fatalScreenSource,
    (Join-Path $resourceSource 'fonts\atkinsonhyperlegiblenext.ttf'),
    (Join-Path $resourceSource 'fonts\cambria.ttf'),
    (Join-Path $resourceSource 'fonts\Fira_Code_v6.2\ttf\FiraCode-Retina.ttf'),
    (Join-Path $resourceSource 'fonts\Fira_Code_v6.2\ttf\FiraCode-Bold.ttf'),
    (Join-Path $resourceSource 'fonts\Fira_Code_v6.2\ttf\FiraCode-SemiBold.ttf'),
    (Join-Path $networkSettingsSource 'cacerts.pem'),
    (Join-Path $networkSettingsSource 'network.txt')
)
foreach ($requiredFile in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required source file not found: $requiredFile"
    }
}

try {
    $pythonManifest = Get-Content -Raw -LiteralPath $pythonManifestSource |
        ConvertFrom-Json -ErrorAction Stop
    $pythonReleaseLock = Get-Content -Raw -LiteralPath $pythonReleaseLockSource |
        ConvertFrom-Json -ErrorAction Stop
}
catch {
    throw "The managed Python manifest or release lock is malformed JSON: $($_.Exception.Message)"
}

$expectedPythonRelease = [string]$pythonReleaseLock.release
$expectedPythonManifestSha256 = [string]$pythonReleaseLock.outputs.manifest_sha256
if (
    $expectedPythonRelease -notmatch '^[0-9A-Za-z][0-9A-Za-z._+-]{0,127}$' -or
    $expectedPythonManifestSha256 -notmatch '^[0-9a-f]{64}$' -or
    [string]$pythonReleaseLock.outputs.software_tree.sha256 -notmatch '^[0-9a-f]{64}$' -or
    [string]$pythonReleaseLock.outputs.catalogue_tree.sha256 -notmatch '^[0-9a-f]{64}$'
) {
    throw 'The managed Python release lock is absent or malformed.'
}

$actualPythonManifestSha256 = (
    Get-FileHash -LiteralPath $pythonManifestSource -Algorithm SHA256
).Hash.ToLowerInvariant()
if (
    [string]$pythonManifest.state -cne 'verified' -or
    [string]$pythonManifest.release -cne $expectedPythonRelease -or
    [string]$pythonManifest.software.tree.sha256 -cne [string]$pythonReleaseLock.outputs.software_tree.sha256 -or
    [string]$pythonManifest.catalogue.tree.sha256 -cne [string]$pythonReleaseLock.outputs.catalogue_tree.sha256 -or
    $actualPythonManifestSha256 -cne $expectedPythonManifestSha256
) {
    throw 'The managed Python source payload is not bound to the immutable release-zero lock.'
}

if (-not $UsbDrive -and -not (Test-Path -LiteralPath $imagePath -PathType Leaf)) {
    throw "Disk image not found: $imagePath"
}

$targetDiscoveryStopwatch = [Diagnostics.Stopwatch]::StartNew()
$usbTarget = if ($UsbDrive) { Get-T1OSUsbDriveTarget } else { $null }
$targetDiscoveryStopwatch.Stop()
if ($usbTarget) {
    Write-Host "T1OS USB drive: $($usbTarget.DriveLetter): '$($usbTarget.Label)'"
    Write-Host "USB disk: $($usbTarget.DiskNumber) $($usbTarget.Model)"
}
if (@(
    $ValidateTargetOnly,
    $ValidateManagedTreeOnly,
    $VerifyManagedReleaseOnly,
    $SyncManagedReleaseOnly
).Where({ $_ }).Count -gt 1) {
    throw 'Choose only one USB validation or verification mode.'
}
if ($ValidateTargetOnly) {
    if (-not $UsbDrive) {
        throw '-ValidateTargetOnly is available only with -UsbDrive.'
    }
    Write-Host 'T1OS USB drive target validation passed.'
    exit 0
}
if ($ValidateManagedTreeOnly -and -not $UsbDrive) {
    throw '-ValidateManagedTreeOnly is available only with -UsbDrive.'
}
if ($VerifyManagedReleaseOnly -and -not $UsbDrive) {
    throw '-VerifyManagedReleaseOnly is available only with -UsbDrive.'
}

if ($Fast -and $Full) {
    throw 'Choose either -Fast or -Full, not both.'
}

$deploymentStatePath = if ($UsbDrive) {
    Join-Path $usbTarget.Root 'the one\settings\usb update state.json'
}
else {
    Join-Path $projectRoot 'environment\software\storage.img update state.json'
}
$targetIdentity = if ($UsbDrive) {
    'usb|{0}|{1}|{2}|{3}' -f @(
        $usbTarget.DriveLetter,
        $usbTarget.DiskNumber,
        $usbTarget.SerialNumber,
        $usbTarget.Label
    )
}
else {
    $imageItem = Get-Item -LiteralPath $imagePath -Force
    'image|{0}|{1}|{2}' -f @(
        $imageItem.FullName,
        $imageItem.Length,
        $imageItem.LastWriteTimeUtc.Ticks
    )
}

$sourceStateStopwatch = [Diagnostics.Stopwatch]::StartNew()
$deploymentSourceState = Get-T1OSDeploymentSourceState `
    -ProjectRoot $projectRoot -ScriptRoot (Split-Path -Path $PSScriptRoot -Parent)
$sourceStateStopwatch.Stop()
$allManagedRoots = @($deploymentSourceState.roots.psobject.Properties.Name)

if (-not $Full) {
    $previousDeploymentState = Read-T1OSDeploymentState `
        -Path $deploymentStatePath
    $deploymentPlan = Get-T1OSDeploymentPlan `
        -SourceState $deploymentSourceState `
        -PreviousState $previousDeploymentState `
        -TargetIdentity $targetIdentity
    $selectedManagedRoots = @($deploymentPlan.roots)
    $fullTargetVerification = [bool]$deploymentPlan.full_verification
    $unchangedLargeFiles = @($deploymentPlan.unchanged_large_files)
}
else {
    $selectedManagedRoots = $allManagedRoots
    $fullTargetVerification = $true
    $unchangedLargeFiles = @()
}

if ($SyncManagedReleaseOnly) {
    $selectedManagedRoots = @(
        'build', 'boot', 'virtualbox_software',
        'image_catalogue', 'python'
    )
}

Write-Host "Selected managed root(s): $($selectedManagedRoots -join ', ')"

if (
    $selectedManagedRoots.Count -eq 0 -and
    -not ($ValidateManagedTreeOnly -or $VerifyManagedReleaseOnly -or $SyncManagedReleaseOnly)
) {
    Write-Host 'The deployment target already contains the current managed source state.'
    Write-Host ("Target validation {0:N2}s; source inventory {1:N2}s; no content scan was needed." -f `
        $targetDiscoveryStopwatch.Elapsed.TotalSeconds,
        $sourceStateStopwatch.Elapsed.TotalSeconds)
    exit 0
}

$preparationStopwatch = [Diagnostics.Stopwatch]::StartNew()

if (-not $Fast -and -not ($ValidateManagedTreeOnly -or $VerifyManagedReleaseOnly)) {
    Write-Host 'Verifying the canonical Python deployment payload before opening the deployment target...'
    & $pythonRuntimeVerifier -DeploymentPayloadOnly
}
elseif ($Fast) {
    Write-Host 'Fast deployment mode: immutable manifest/lock identity passed; skipping the redundant canonical source rebuild audit.'
}
else {
    Write-Host 'Managed-Python mode: unrelated T1OS source roots are outside this verification scope.'
}

function ConvertTo-WslPath {
    param(
        [Parameter(Mandatory)]
        [string]$WindowsPath
    )

    $output = & wsl.exe --exec wslpath -a $WindowsPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }

    $translatedPath = ([string]($output | Select-Object -First 1)).Trim()
    if ([string]::IsNullOrWhiteSpace($translatedPath)) {
        throw "WSL returned an empty path for: $WindowsPath"
    }

    return $translatedPath
}

$bootPolicyDirectory = Split-Path -Path $bootPolicyManifest -Parent
New-Item -ItemType Directory -Path $bootPolicyDirectory -Force | Out-Null
$wslProjectRoot = ConvertTo-WslPath -WindowsPath $projectRoot
$wslBootPolicyBuilder = "$wslProjectRoot/scripts/build/build boot protected roots.py"
$wslBootPolicyManifest = "$wslProjectRoot/development/hardware boot policy/protected-roots.json"
$bootPolicyStampPath = "$bootPolicyManifest.inputs.sha256"
$bootPolicyInput = @(
    $deploymentSourceState.contract_stamp,
    $deploymentSourceState.roots.build.source_stamp,
    $deploymentSourceState.roots.boot.source_stamp,
    $deploymentSourceState.roots.virtualbox_software.source_stamp,
    $deploymentSourceState.roots.image_catalogue.source_stamp,
    $deploymentSourceState.roots.python.source_stamp
) -join "`n"
$bootPolicyInputStamp = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData(
        [Text.Encoding]::UTF8.GetBytes($bootPolicyInput)
    )
).ToLowerInvariant()
$cachedBootPolicyStamp = if (Test-Path -LiteralPath $bootPolicyStampPath -PathType Leaf) {
    (Get-Content -Raw -LiteralPath $bootPolicyStampPath).Trim()
}
else {
    ''
}
if (
    $cachedBootPolicyStamp -cne $bootPolicyInputStamp -or
    -not (Test-Path -LiteralPath $bootPolicyManifest -PathType Leaf)
) {
    & wsl.exe --exec python3 -B $wslBootPolicyBuilder `
        --repo $wslProjectRoot --output $wslBootPolicyManifest
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $bootPolicyManifest -PathType Leaf)) {
        throw 'The independent boot protected-root policy build failed.'
    }
    [IO.File]::WriteAllText(
        $bootPolicyStampPath,
        "$bootPolicyInputStamp`n",
        [Text.UTF8Encoding]::new($false)
    )
}
else {
    Write-Host 'Boot protected-root policy inputs are unchanged; reusing the verified manifest.'
}

$buildFileCount = [int]$deploymentSourceState.roots.build.files
$bootFileCount = [int]$deploymentSourceState.roots.boot.files
$driversFileCount = [int]$deploymentSourceState.roots.drivers.files
$graphicsCatalogueFileCount = [int]$deploymentSourceState.roots.graphics.files
$virtualBoxCatalogueFileCount = [int]$deploymentSourceState.roots.virtualbox_catalogue.files
$virtualBoxSoftwareFileCount = [int]$deploymentSourceState.roots.virtualbox_software.files
$virtualBoxSettingsFileCount = [int]$deploymentSourceState.roots.virtualbox_settings.files
$audioCatalogueFileCount = [int]$deploymentSourceState.roots.audio_catalogue.files
$audioSoftwareFileCount = [int]$deploymentSourceState.roots.audio_software.files
$networkCatalogueFileCount = [int]$deploymentSourceState.roots.network_catalogue.files
$networkSoftwareFileCount = [int]$deploymentSourceState.roots.network_software.files
$networkSettingsFileCount = [int]$deploymentSourceState.roots.network_settings.files
$chromiumSoftwareFileCount = [int]$deploymentSourceState.roots.chromium.files
$imageCatalogueFileCount = [int]$deploymentSourceState.roots.image_catalogue.files
$pythonSoftwareFileCount = @(Get-ChildItem -LiteralPath $pythonSoftwareSource -File -Recurse).Count
$pythonCatalogueFileCount = @(Get-ChildItem -LiteralPath $pythonCatalogueSource -File -Recurse).Count
$logoFileCount = @(Get-ChildItem -LiteralPath $logoSource -File -Recurse -Filter '*.png').Count
Write-Host "Preparing to push $buildFileCount build file(s), $bootFileCount boot file(s), $driversFileCount driver runtime file(s), $graphicsCatalogueFileCount graphics catalogue file(s), $virtualBoxCatalogueFileCount VirtualBox catalogue file(s), $virtualBoxSoftwareFileCount VirtualBox software file(s), $virtualBoxSettingsFileCount VirtualBox settings file(s), $audioCatalogueFileCount audio catalogue file(s), $audioSoftwareFileCount audio software file(s), $networkCatalogueFileCount network catalogue file(s), $networkSoftwareFileCount network software file(s), $networkSettingsFileCount network setting file(s), $chromiumSoftwareFileCount Chromium runtime file(s), $imageCatalogueFileCount image catalogue file(s), $pythonSoftwareFileCount Python runtime file(s), $pythonCatalogueFileCount Python catalogue file(s), $logoFileCount logo file(s), and the runtime fonts..."

$operationError = $null

try {
    if ($UsbDrive) {
        Write-Host "The T1OS USB drive will remain mounted inside one controlled WSL process for the complete sync."
        $wslImagePath = $usbTarget.DriveSource
    }
    else {
        Write-Host 'Checking the disk mount status...'
        if (Test-T1OSDiskMounted -MountPoint $mountPoint) {
            throw "Refusing to push while $mountPoint is already mounted."
        }

        Write-Host 'The disk is unmounted. It will remain mounted inside one controlled WSL process for the complete sync.'
        Assert-T1OSFilesystemHealthy -ImagePath $imagePath -Operation 'pushing files to it'
        $wslImagePath = "$wslProjectRoot/environment/software/storage.img"
    }
    $wslBuildSource = "$wslProjectRoot/source/build software"
    $wslBootSource = "$wslProjectRoot/source/boot"
    $wslDriversSource = "$wslProjectRoot/source/drivers"
    $wslGraphicsCatalogueSource = "$wslProjectRoot/source/catalogue/graphics"
    $wslVirtualBoxCatalogueSource = "$wslProjectRoot/source/catalogue/virtualbox"
    $wslVirtualBoxSoftwareSource = "$wslProjectRoot/source/software/virtualbox"
    $wslVirtualBoxSettingsSource = "$wslProjectRoot/source/settings/virtualbox"
    $wslAudioCatalogueSource = "$wslProjectRoot/source/catalogue/audio"
    $wslAudioSoftwareSource = "$wslProjectRoot/source/software/audio"
    $wslNetworkCatalogueSource = "$wslProjectRoot/source/catalogue/network"
    $wslNetworkSoftwareSource = "$wslProjectRoot/source/software/network"
    $wslNetworkSettingsSource = "$wslProjectRoot/source/settings/network"
    $wslMediaSettingsSource = "$wslProjectRoot/source/settings/media"
    $wslChromiumSoftwareSource = "$wslProjectRoot/source/software/chromium"
    $wslNativeProtocolHeader = "$wslProjectRoot/source/native/video/t1_media_decode_protocol.h"
    $wslNativeWatchdogHeader = "$wslProjectRoot/source/native/video/t1_media_decode_watchdog.h"
    $wslChromiumProtocolHeader = "$wslProjectRoot/resource/chromium-source/150.0.7871.181/overlay/media/gpu/t1os/t1_media_decode_protocol.h"
    $wslChromiumSourceManifest = "$wslProjectRoot/resource/chromium-source/150.0.7871.181/manifest.json"
    $wslRuntimePathContractSource = "$wslProjectRoot/source/settings/runtime paths.json"
    $wslImageCatalogueSource = "$wslProjectRoot/source/catalogue/image"
    $wslPythonSoftwareSource = "$wslProjectRoot/source/software/python"
    $wslPythonCatalogueSource = "$wslProjectRoot/source/catalogue/python"
    $wslPythonRuntimeConfigSource = "$wslProjectRoot/source/python/build/runtime.json"
    $wslResourceSource = "$wslProjectRoot/resource"

    Write-Host "Comparing build software with $buildDestination..."
    Write-Host "Comparing boot files with $bootDestination..."
    Write-Host "Comparing the T1OS driver runtime with $driversDestination..."
    Write-Host "Comparing graphics catalogue with $graphicsCatalogueDestination..."
    Write-Host "Comparing VirtualBox catalogue with $virtualBoxCatalogueDestination..."
    Write-Host "Comparing VirtualBox software with $virtualBoxSoftwareDestination..."
    Write-Host "Comparing VirtualBox settings with $virtualBoxSettingsDestination..."
    Write-Host "Comparing audio catalogue with $audioCatalogueDestination..."
    Write-Host "Comparing audio software with $audioSoftwareDestination..."
    Write-Host "Comparing image catalogue with $imageCatalogueDestination..."
    Write-Host "Comparing the managed Python runtime with $pythonSoftwareDestination..."
    Write-Host "Comparing the managed Python catalogue with $pythonCatalogueDestination..."
    Write-Host "Comparing runtime fonts, logos, and mouse cursors with /the one/resources..."

    $copyCommand = @'
set -eu
mount_point=$1
build_destination=$2
boot_destination=$3
graphics_catalogue_destination=$4
virtualbox_catalogue_destination=$5
virtualbox_software_destination=$6
audio_catalogue_destination=$7
audio_software_destination=$8
build_source=$9
boot_source=${10}
graphics_catalogue_source=${11}
virtualbox_catalogue_source=${12}
virtualbox_software_source=${13}
audio_catalogue_source=${14}
audio_software_source=${15}
image_catalogue_destination=${16}
image_catalogue_source=${17}
image_path=${18}
virtualbox_settings_destination=${19}
virtualbox_settings_source=${20}
font_destination=${21}
drivers_destination=${22}
drivers_source=${23}
network_catalogue_destination=${24}
network_software_destination=${25}
network_settings_destination=${26}
chromium_software_destination=${27}
runtime_path_contract_destination=${28}
network_catalogue_source=${29}
network_software_source=${30}
network_settings_source=${31}
chromium_software_source=${32}
runtime_path_contract_source=${33}
resource_source=${34}
target_mode=${35}
media_settings_source=${36}
media_settings_destination=${37}
native_protocol_header=${38}
native_watchdog_header=${39}
chromium_protocol_header=${40}
chromium_source_manifest=${41}
python_software_destination=${42}
python_catalogue_destination=${43}
python_software_source=${44}
python_catalogue_source=${45}
expected_python_release=${46}
expected_python_manifest_sha256=${47}
preflight_only=${48}
managed_verify_only=${49}
managed_sync_only=${50}
profiled_python_config=${51}
boot_policy_manifest=${52}
selected_roots=${53}
exhaustive_verify=${54}
skip_chromium_engine=${55}
logo_resource_destination="$mount_point/the one/resources/logos"
cursor_resource_destination="$mount_point/the one/resources/cursors"
system_resource_destination="$mount_point/the one/resources/system"
system_software_source="$build_source/../software/system"
system_software_destination="$mount_point/the one/software/system"

case "$expected_python_release" in
    ''|*[!0-9A-Za-z._+-]*)
        echo 'Expected Python release argument is malformed.' >&2
        exit 1
        ;;
esac
case "$expected_python_manifest_sha256" in
    *[!0-9a-f]*|'')
        echo 'Expected Python manifest digest argument is malformed.' >&2
        exit 1
        ;;
esac
[ "${#expected_python_manifest_sha256}" -eq 64 ] || {
    echo 'Expected Python manifest digest does not contain 64 hexadecimal characters.' >&2
    exit 1
}

root_selected() {
    requested=$1
    case ",$selected_roots," in
        *,$requested,*) return 0 ;;
        *) return 1 ;;
    esac
}

for command_name in rsync mount umount mountpoint findmnt losetup readlink readelf python3 find grep head mv rm cp mkdir rmdir chmod chown cmp sha256sum awk wc sync od tr; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "Required WSL push command is not installed: $command_name" >&2
        exit 127
    }
done

stage="/tmp/t1os-push-$$"
mounted_here=0

cleanup_loops() {
    [ "$target_mode" = image ] || return 0
    losetup -j "$image_path" 2>/dev/null |
        while IFS=: read -r loop_device _; do
            [ -n "$loop_device" ] || continue
            if ! findmnt -rn -S "$loop_device" >/dev/null 2>&1; then
                losetup -d "$loop_device"
            fi
        done
}

cleanup() {
    status=$?
    rm -rf -- "$stage"

    if [ "$mounted_here" = 1 ]; then
        if ! umount "$mount_point"; then
            echo "Could not release $mount_point after the push." >&2
            status=1
        fi
    fi

    cleanup_loops
    trap - EXIT HUP INT TERM
    exit "$status"
}
trap cleanup EXIT HUP INT TERM

python3 - "$mount_point" <<'PY'
import os
import stat
import sys

mount = os.path.abspath(sys.argv[1])
parent = os.path.dirname(mount)
parent_status = os.lstat(parent)
if stat.S_ISLNK(parent_status.st_mode) or not stat.S_ISDIR(parent_status.st_mode):
    raise SystemExit(f'unsafe mount-point parent: {parent}')
if os.path.realpath(parent) != parent:
    raise SystemExit(f'mount-point parent resolves elsewhere: {parent}')
try:
    status = os.lstat(mount)
except FileNotFoundError:
    os.mkdir(mount, 0o755)
    status = os.lstat(mount)
if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
    raise SystemExit(f'unsafe mount point: {mount}')
if os.path.realpath(mount) != mount:
    raise SystemExit(f'mount point resolves elsewhere: {mount}')
PY

if mountpoint -q "$mount_point"; then
    echo "$mount_point became mounted before the controlled push started." >&2
    exit 1
fi

if find "$mount_point" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    echo "$mount_point contains stale files while unmounted; refusing to push." >&2
    exit 1
fi

cleanup_loops

if [ "$target_mode" = drive ]; then
    # Do not enable DrvFS metadata on the physical NTFS volume. Historical
    # Linux-looking modes on the USB are not T1OS policy, and honoring them can
    # block a maintenance identity that the real NTFS ACL permits. Windows ACLs
    # authorize this offline update; the T1OS LSM protects the installed paths
    # when the operating system runs.
    mount -t drvfs "$image_path" "$mount_point" \
        -o uid=0,gid=0,umask=022
    mounted_here=1
    mount_options=$(findmnt -rn -o OPTIONS -T "$mount_point" | head -n 1)
    case ",$mount_options," in
        *,ro,*)
            echo 'The T1OS USB drive mounted read-only; refusing to push.' >&2
            exit 1
            ;;
    esac
    source_device=$(findmnt -rn -o SOURCE -T "$mount_point" | head -n 1)
    if [ "$source_device" != "$image_path" ]; then
        echo "$mount_point is not backed by the requested Windows drive $image_path." >&2
        exit 1
    fi
else
    mount_attempt=1
    while :; do
        mount -o loop,rw "$image_path" "$mount_point"
        mounted_here=1
        mount_options=$(findmnt -rn -o OPTIONS -T "$mount_point" | head -n 1)
        case ",$mount_options," in
            *,ro,*)
                echo "The storage image mounted read-only on attempt $mount_attempt; resetting the loop device." >&2
                umount "$mount_point"
                mounted_here=0
                cleanup_loops
                if [ "$mount_attempt" -ge 3 ]; then
                    echo 'The storage image could not be mounted read-write after three attempts.' >&2
                    exit 1
                fi
                mount_attempt=$((mount_attempt + 1))
                ;;
            *)
                break
                ;;
        esac
    done
    source_device=$(findmnt -rn -o SOURCE -T "$mount_point" | head -n 1)
    source_device=${source_device%%\[*}
    backing_file=$(losetup -n -O BACK-FILE "$source_device" 2>/dev/null | head -n 1)

    if [ -z "$backing_file" ] || [ "$(readlink -f "$backing_file")" != "$(readlink -f "$image_path")" ]; then
        echo "$mount_point is not backed by the requested storage image." >&2
        exit 1
    fi
fi

mkdir -p "$stage"
if [ "$target_mode" = drive ]; then
    [ -d "$mount_point/boot" ] &&
        [ -d "$mount_point/the one/build" ] &&
        [ -f "$mount_point/the one/settings/runtime paths.json" ] &&
        [ -f "$mount_point/the one/resources/t1os-drive.ico" ] &&
        [ -f "$mount_point/autorun.inf" ] || {
            echo 'The mounted Windows drive is not a complete T1OS USB root.' >&2
            exit 1
        }
    grep -Eiq '^[[:space:]]*Label=T1OS([[:space:]]|$)' "$mount_point/autorun.inf" || {
        echo 'The mounted Windows drive does not contain the expected T1OS identity label.' >&2
        exit 1
    }
fi

# This is the last read-only gate before anything below the mounted target is
# removed, created, copied, chowned, or chmodded. Check every named ancestor
# without following links, then recursively reject hostile entries in every
# tree the updater can mutate.
python3 - "$mount_point" "$preflight_only" "$managed_verify_only" "$managed_sync_only" "$selected_roots" <<'PY'
import os
import stat
import sys

mount = os.path.abspath(sys.argv[1])
preflight_only, managed_verify_only, managed_sync_only = (
    value == 'True' for value in sys.argv[2:5]
)
selected = {value for value in sys.argv[5].split(',') if value}
if preflight_only or managed_verify_only or managed_sync_only:
    selected = {
        'build', 'boot', 'virtualbox_software', 'image_catalogue', 'python'
    }
root_map = {
    'build': ('the one/build',),
    'boot': ('boot',),
    'drivers': ('the one/drivers',),
    'graphics': ('the one/catalogue/graphics',),
    'virtualbox_catalogue': ('the one/catalogue/virtualbox',),
    'virtualbox_software': ('the one/software/virtualbox',),
    'virtualbox_settings': ('the one/settings/virtualbox',),
    'audio_catalogue': ('the one/catalogue/audio',),
    'audio_software': ('the one/software/audio',),
    'network_catalogue': ('the one/catalogue/network',),
    'network_software': ('the one/software/network',),
    'network_settings': ('the one/settings/network',),
    'media_settings': ('the one/settings/media',),
    'chromium': ('the one/software/chromium',),
    'image_catalogue': ('the one/catalogue/image',),
    'python': ('the one/software/python', 'the one/catalogue/python'),
    'resources': (
        'the one/resources/fonts',
        'the one/resources/logos',
        'the one/resources/cursors',
        'the one/resources/system',
    ),
}
leaf_map = {
    # This deployment changes one settings contract, not the application state
    # beside it. Chromium can leave valid SQLite WAL/journal files that DrvFS
    # cannot stat after a hardware boot; recursively inspecting the unrelated
    # profile both exceeds the mutation scope and makes safe updates fail.
    'runtime_contract': ('the one/settings/runtime paths.json',),
}
unknown = selected - set(root_map) - set(leaf_map)
if unknown:
    raise SystemExit(f'unknown selected deployment roots: {sorted(unknown)}')
relative_roots = tuple(dict.fromkeys(
    relative
    for name in sorted(selected)
    for relative in root_map.get(name, ())
))
relative_leaves = tuple(dict.fromkeys(
    relative
    for name in sorted(selected)
    for relative in leaf_map.get(name, ())
))
integrity_roots = frozenset({
    'the one/software/python',
    'the one/catalogue/python',
    'the one/catalogue/image',
    'the one/build',
    'boot',
    'the one/software/virtualbox',
})
mutable_roots = relative_roots

def lstat_directory(path):
    try:
        status = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
        raise SystemExit(f'unsafe mounted-target ancestor or root: {path}')
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
    if reparse and getattr(status, 'st_file_attributes', 0) & reparse:
        raise SystemExit(f'mounted-target path is a reparse point: {path}')
    if status.st_mode & (stat.S_ISUID | stat.S_ISGID):
        raise SystemExit(f'mounted-target directory has set-id bits: {path}')
    return True

if not lstat_directory(mount):
    raise SystemExit(f'mounted-target root disappeared: {mount}')
mount_device = os.lstat(mount).st_dev
mount_real = os.path.realpath(mount)
if mount_real != mount:
    raise SystemExit(f'mounted-target root resolves elsewhere: {mount} -> {mount_real}')

for relative in relative_roots:
    candidate = os.path.normpath(os.path.join(mount, relative))
    if os.path.commonpath((mount, candidate)) != mount:
        raise SystemExit(f'mounted-target path escapes its mount: {candidate}')
    current = mount
    for component in relative.split('/'):
        current = os.path.join(current, component)
        if not lstat_directory(current):
            break
        if os.lstat(current).st_dev != mount_device:
            raise SystemExit(f'nested filesystem in mounted-target path: {current}')
    resolved = os.path.realpath(candidate)
    if resolved != candidate or os.path.commonpath((mount_real, resolved)) != mount_real:
        raise SystemExit(f'mounted-target path resolves outside its canonical root: {candidate}')

for relative in relative_leaves:
    candidate = os.path.normpath(os.path.join(mount, relative))
    if os.path.commonpath((mount, candidate)) != mount:
        raise SystemExit(f'mounted-target leaf escapes its mount: {candidate}')
    current = mount
    for component in os.path.dirname(relative).split('/'):
        current = os.path.join(current, component)
        if not lstat_directory(current):
            break
        if os.lstat(current).st_dev != mount_device:
            raise SystemExit(f'nested filesystem in mounted-target leaf path: {current}')
    try:
        status = os.lstat(candidate)
    except FileNotFoundError:
        continue
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
    if (
        stat.S_ISLNK(status.st_mode)
        or not stat.S_ISREG(status.st_mode)
        or (reparse and getattr(status, 'st_file_attributes', 0) & reparse)
        or status.st_nlink != 1
        or status.st_dev != mount_device
        or os.path.realpath(candidate) != os.path.abspath(candidate)
    ):
        raise SystemExit(f'unsafe mounted-target leaf: {candidate}')

def inspect_tree(root, require_single_link):
    if not os.path.lexists(root):
        return
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = entry.path
                status = entry.stat(follow_symlinks=False)
                mode = status.st_mode
                reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
                if (
                    entry.is_symlink()
                    or (reparse and getattr(status, 'st_file_attributes', 0) & reparse)
                ):
                    raise SystemExit(f'unsafe entry in protected mounted-target root: {path}')
                if status.st_dev != mount_device:
                    raise SystemExit(f'nested filesystem in protected mounted-target root: {path}')
                if os.path.realpath(path) != os.path.abspath(path):
                    raise SystemExit(f'protected mounted-target entry resolves elsewhere: {path}')
                if stat.S_ISDIR(mode):
                    pending.append(path)
                elif stat.S_ISREG(mode):
                    if require_single_link and status.st_nlink != 1:
                        raise SystemExit(f'hard-linked file in protected mounted-target root: {path}')
                else:
                    raise SystemExit(f'special entry in protected mounted-target root: {path}')

for relative in mutable_roots:
    inspect_tree(
        os.path.join(mount, relative),
        require_single_link=relative in integrity_roots,
    )

PY

if [ "$preflight_only" = True ]; then
    echo 'Managed USB tree structural preflight passed; no payload bytes were changed.'
    exit 0
fi

# Linux mode bits on the physical NTFS USB are not a T1OS authorization
# boundary; the T1OS LSM applies the runtime policy. Do not try to make any USB
# tree writable with chmod before replacing its content. storage.img remains a
# Linux filesystem and retains its reproducible metadata transition.
if \
    [ "$target_mode" = image ] &&
    [ "$managed_verify_only" != True ] &&
    [ "$managed_sync_only" != True ]
then
    make_tree_writable() {
        root_name=$1
        writable_tree=$2
        root_selected "$root_name" || return 0
        if [ -d "$writable_tree" ]; then
            find "$writable_tree" -xdev -type d -exec chmod u+rwx {} +
            find "$writable_tree" -xdev -type f -exec chmod u+rw {} +
        fi
    }
    make_tree_writable drivers "$drivers_destination"
    make_tree_writable graphics "$graphics_catalogue_destination"
    make_tree_writable virtualbox_catalogue "$virtualbox_catalogue_destination"
    make_tree_writable virtualbox_settings "$virtualbox_settings_destination"
    make_tree_writable audio_catalogue "$audio_catalogue_destination"
    make_tree_writable audio_software "$audio_software_destination"
    make_tree_writable network_catalogue "$network_catalogue_destination"
    make_tree_writable network_software "$network_software_destination"
    make_tree_writable network_settings "$network_settings_destination"
    make_tree_writable media_settings "$media_settings_destination"
    make_tree_writable chromium "$chromium_software_destination"
    make_tree_writable resources "$font_destination"
    make_tree_writable resources "$logo_resource_destination"
    make_tree_writable resources "$cursor_resource_destination"
    make_tree_writable resources "$system_resource_destination"
    make_tree_writable resources "$system_software_destination"
    if root_selected runtime_contract && [ -f "$runtime_path_contract_destination" ]; then
        chmod u+rw "$runtime_path_contract_destination"
    fi
fi

python3 - "$runtime_path_contract_source" > "$stage/forbidden-runtime-roots" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as stream:
    contract = json.load(stream)

roots = contract.get('forbidden_runtime_roots')
if not isinstance(roots, list) or not roots:
    raise SystemExit('The runtime path contract has no forbidden roots.')

for root in roots:
    if not isinstance(root, str) or not root.startswith('/') or root == '/' or '/' in root[1:]:
        raise SystemExit(f'Invalid forbidden runtime root: {root!r}')
    print(root[1:])
PY

while IFS= read -r forbidden; do
    if [ -e "$mount_point/$forbidden" ] || [ -L "$mount_point/$forbidden" ]; then
        echo "The T1OS storage root contains a forbidden Linux hierarchy path: /$forbidden" >&2
        exit 1
    fi
done < "$stage/forbidden-runtime-roots"

# Retire the superseded location if an older development image created it.
# The no-follow gate above has already proved its managed ancestor is safe.
rm -rf -- "$mount_point/the one/software/drivers"

mkdir -p "$stage/build"
rsync -a --no-whole-file --delete --delete-excluded --exclude='__pycache__/' --exclude='*.py[co]' -- "$build_source"/ "$stage/build"/

for legacy_windows_dir in windowserver "window server"; do
    if [ -e "$stage/build/windows" ] && [ -e "$stage/build/$legacy_windows_dir" ]; then
        echo "Both windows and $legacy_windows_dir exist in the staged build." >&2
        exit 1
    fi
    if [ -d "$stage/build/$legacy_windows_dir" ]; then
        mv "$stage/build/$legacy_windows_dir" "$stage/build/windows"
    fi
done

if [ -e "$stage/build/writein" ] && [ -e "$stage/build/write in" ]; then
    echo 'Both writein and write in exist in the staged build.' >&2
    exit 1
fi

if [ -d "$stage/build/write in" ]; then
    mv "$stage/build/write in" "$stage/build/writein"
fi

unexpected_build_files=$(find "$stage/build" -type f \
    ! -name '*.py' \
    ! -path "$stage/build/chromium/hardware diagnostics.json" \
    ! -path "$stage/build/chromium/google api credentials.example.json" \
    ! -path "$stage/build/python/tools.json" \
    ! -path "$stage/build/python/pip-*.whl" \
    ! -path "$stage/build/python/python-command" \
    -print)
if [ -n "$unexpected_build_files" ]; then
    echo 'The staged build contains an unexpected non-Python file:' >&2
    printf '%s\n' "$unexpected_build_files" >&2
    exit 1
fi

mkdir -p \
    "$stage/resources/fonts" \
    "$stage/resources/logos" \
    "$stage/resources/cursors" \
    "$stage/resources/system"

cp -a -- "$resource_source/fonts/atkinsonhyperlegiblenext.ttf" "$stage/resources/fonts/atkinsonhyperlegiblenext.ttf"
cp -a -- "$resource_source/fonts/cambria.ttf" "$stage/resources/fonts/cambria.ttf"
cp -a -- "$resource_source/fonts/Fira_Code_v6.2/ttf/FiraCode-Retina.ttf" "$stage/resources/fonts/firacode.ttf"
cp -a -- "$resource_source/fonts/Fira_Code_v6.2/ttf/FiraCode-Bold.ttf" "$stage/resources/fonts/firacodebold.ttf"
cp -a -- "$resource_source/fonts/Fira_Code_v6.2/ttf/FiraCode-SemiBold.ttf" "$stage/resources/fonts/firacodesemibold.ttf"

fatal_screen_source="$resource_source/../flash/red_screen_of_death.png"
if [ ! -f "$fatal_screen_source" ] || [ -L "$fatal_screen_source" ] || [ ! -s "$fatal_screen_source" ]; then
    echo 'The fatal screen artwork is missing, empty, or symbolic.' >&2
    exit 1
fi
png_signature=$(od -An -tx1 -N8 "$fatal_screen_source" | tr -d ' \n')
if [ "$png_signature" != '89504e470d0a1a0a' ]; then
    echo 'The fatal screen artwork is not a PNG file.' >&2
    exit 1
fi
cp -a -- "$fatal_screen_source" "$stage/resources/system/red_screen_of_death.png"

logo_source="$resource_source/logos"
unexpected_logo_resources=$(find "$logo_source" \( -type f ! -name '*.png' -o -type l \) -print)
if [ -n "$unexpected_logo_resources" ]; then
    echo 'The source logo tree contains unsupported files or symbolic links:' >&2
    printf '%s\n' "$unexpected_logo_resources" >&2
    exit 1
fi

empty_logo_resources=$(find "$logo_source" -type f -name '*.png' ! -size +0c -print)
if [ -n "$empty_logo_resources" ]; then
    echo 'The source logo tree contains empty PNG files:' >&2
    printf '%s\n' "$empty_logo_resources" >&2
    exit 1
fi

logo_count=$(find "$logo_source" -type f -name '*.png' | wc -l)
if [ "$logo_count" -eq 0 ]; then
    echo 'The source logo tree contains no PNG files.' >&2
    exit 1
fi

rsync \
    -a \
    --prune-empty-dirs \
    --include='*/' \
    --include='*.png' \
    --exclude='*' \
    -- "$logo_source"/ "$stage/resources/logos"/

staged_logo_count=$(find "$stage/resources/logos" -type f -name '*.png' | wc -l)
if [ "$staged_logo_count" -ne "$logo_count" ]; then
    echo "Logo staging copied $staged_logo_count of $logo_count PNG files." >&2
    exit 1
fi

unexpected_logo_resources=$(find "$stage/resources/logos" -type f ! -name '*.png' -print)
if [ -n "$unexpected_logo_resources" ]; then
    echo 'The staged logo resources contain non-PNG files:' >&2
    printf '%s\n' "$unexpected_logo_resources" >&2
    exit 1
fi

cursor_source="$resource_source/cursors/extra simple white original"
stage_cursor() {
    filename=$1
    destination="$stage/resources/cursors"

    if [ ! -f "$cursor_source/$filename" ] || [ -L "$cursor_source/$filename" ] || [ ! -s "$cursor_source/$filename" ]; then
        echo "Mouse cursor source is missing, empty, or symbolic: $filename" >&2
        exit 1
    fi

    cp -a -- "$cursor_source/$filename" "$destination/$filename"
}
stage_cursor 'mousecursor.png'
stage_cursor 'mousecursorlink.png'
stage_cursor 'mousecursortext.png'
stage_cursor 'mousecurosrbusy.png'
stage_cursor 'mousecursordiagonal.png'
stage_cursor 'mousecursordiagonal2.png'
stage_cursor 'mousecursorhorizontal.png'
stage_cursor 'mousecursorvertical.png'

validate_catalogue() {
    # These extension/ELF rules apply to native runtime catalogues. The Python
    # image catalogue contains checked-hash bytecode and package metadata; it
    # is validated separately against the immutable Python release inventory
    # by verify_managed_python_release().
    unexpected_catalogue_files=$(find \
        "$graphics_catalogue_destination" \
        "$virtualbox_catalogue_destination" \
        "$audio_catalogue_destination" \
        "$network_catalogue_destination" \
        -type f \
            ! -name '*.py' \
            ! -name '*.so' \
            ! -name '*.so.*' \
            ! -path "$graphics_catalogue_destination/catalogue.json" \
            ! -path "$graphics_catalogue_destination/vulkan/icd.d/*.json" \
            ! -path "$graphics_catalogue_destination/nvidia/LICENSE.txt" \
            ! -path "$graphics_catalogue_destination/nvidia/nvidia-vaapi-driver-LICENSE.txt" \
            ! -path "$graphics_catalogue_destination/nvidia/runtime.json" \
            ! -path "$graphics_catalogue_destination/nvidia/supported-gpus.json" \
            ! -path "$graphics_catalogue_destination/nvidia/egl_vendor.d/*.json" \
            ! -path "$graphics_catalogue_destination/nvidia/gbm/*.json" \
            -print)
    if [ -n "$unexpected_catalogue_files" ]; then
        echo 'The catalogue contains files that are not runtime library dependencies:' >&2
        printf '%s\n' "$unexpected_catalogue_files" >&2
        exit 1
    fi

    catalogue_metadata=$(find \
        "$graphics_catalogue_destination" \
        "$virtualbox_catalogue_destination" \
        "$audio_catalogue_destination" \
        "$network_catalogue_destination" \
        -type f \( \
        -iname '*licence*' -o \
        -iname '*license*' -o \
        -iname 'version.txt' -o \
        -iname '*manifest*' -o \
        -iname '*notice*' -o \
        -iname '*readme*' -o \
        -iname 'catalogue.json' -o \
        -iname '*.pyi' -o \
        -iname 'py.typed' \
    \) \
        ! -path "$graphics_catalogue_destination/catalogue.json" \
        ! -path "$graphics_catalogue_destination/nvidia/LICENSE.txt" \
        ! -path "$graphics_catalogue_destination/nvidia/nvidia-vaapi-driver-LICENSE.txt" \
        ! -path "$graphics_catalogue_destination/nvidia/runtime.json" \
        ! -path "$graphics_catalogue_destination/nvidia/supported-gpus.json" \
        ! -path "$graphics_catalogue_destination/nvidia/egl_vendor.d/*.json" \
        ! -path "$graphics_catalogue_destination/nvidia/gbm/*.json" \
        -print)
    if [ -n "$catalogue_metadata" ]; then
        echo 'The catalogue contains metadata or development-only files:' >&2
        printf '%s\n' "$catalogue_metadata" >&2
        exit 1
    fi

    find "$graphics_catalogue_destination/vulkan/icd.d" -maxdepth 1 -type f -name '*.json' -print 2>/dev/null > "$stage/vulkan-icd-files" || true
    while IFS= read -r icd_file; do
        python3 - "$icd_file" "$graphics_catalogue_destination" <<'PY'
import json
import os
import sys

manifest_path, graphics_root = sys.argv[1:]
with open(manifest_path, encoding='utf-8') as stream:
    manifest = json.load(stream)

library_path = manifest.get('ICD', {}).get('library_path', '')
runtime_prefix = '/the one/catalogue/graphics/'
if not library_path.startswith(runtime_prefix):
    raise SystemExit(f'Vulkan ICD uses an unexpected library path: {library_path!r}')

library_name = os.path.basename(os.path.normpath(library_path))
if not library_name or not os.path.isfile(os.path.join(graphics_root, library_name)):
    raise SystemExit(f'Vulkan ICD library is missing from the graphics catalogue: {library_name!r}')
PY
    done < "$stage/vulkan-icd-files"

    find \
        "$graphics_catalogue_destination" \
        "$virtualbox_catalogue_destination" \
        "$audio_catalogue_destination" \
        "$network_catalogue_destination" \
        -type f \
        ! -name '*.py' \
        ! -name '*.json' \
        ! -path "$graphics_catalogue_destination/nvidia/LICENSE.txt" \
        ! -path "$graphics_catalogue_destination/nvidia/nvidia-vaapi-driver-LICENSE.txt" \
        -print > "$stage/catalogue-elf-files"
    while IFS= read -r catalogue_file; do
        if ! readelf -h "$catalogue_file" >/dev/null 2>&1; then
            echo "The catalogue file is not a loadable ELF library: $catalogue_file" >&2
            exit 1
        fi
    done < "$stage/catalogue-elf-files"
}

# The optional VirtualBox catalogue is normally empty and is removed after a
# successful push. Do not recreate that empty directory beneath the protected
# runtime catalogue parent on the next push. Route its no-op sync and catalogue
# validation through the private stage instead.
if \
    [ ! -d "$virtualbox_catalogue_destination" ] &&
    ! find "$virtualbox_catalogue_source" -type f \
        ! -name 'catalogue.json' \
        ! -iname '*licence*' \
        ! -iname '*license*' \
        -print -quit | grep -q .
then
    virtualbox_catalogue_destination="$stage/empty-virtualbox-catalogue"
fi

mkdir -p "$build_destination" "$boot_destination" "$drivers_destination" "$graphics_catalogue_destination" "$virtualbox_catalogue_destination" "$virtualbox_software_destination" "$virtualbox_settings_destination" "$audio_catalogue_destination" "$audio_software_destination" "$network_catalogue_destination" "$network_software_destination" "$network_settings_destination" "$media_settings_destination" "$chromium_software_destination" "$image_catalogue_destination" "$python_software_destination" "$python_catalogue_destination" "$system_software_destination" "$font_destination" "$logo_resource_destination" "$cursor_resource_destination" "$system_resource_destination"

# rsync archive mode is useful for storage.img, whose POSIX metadata is part of
# the installed image. On the physical NTFS USB only content and topology are
# synchronized; its Linux-looking mode bits are neither portable nor a T1OS
# authorization boundary.
usb_rsync_metadata_options=
if [ "$target_mode" = drive ]; then
    usb_rsync_metadata_options='--no-perms --no-owner --no-group --no-times --omit-dir-times'
fi

sync_tree() {
    label=$1
    source=$2
    destination=$3

    echo "Checking $label for changes..."
    rsync \
        -a \
        --no-whole-file \
        $usb_rsync_metadata_options \
        --checksum \
        --delete-delay \
        --itemize-changes \
        --human-readable \
        --out-format="$label: %i %n%L" \
        -- "$source"/ "$destination"/
}

sync_driver_runtime() {
    label=$1
    source=$2
    destination=$3

    echo "Checking $label for changes..."
    # The kernel updater owns firmware and module generations. Driverserver owns
    # nodes/processes/state while T1OS is running. This synchronizer owns only
    # the source-controlled settings and tools and must never delete the other
    # subtrees merely because they are absent from source/drivers.
    rsync \
        -a \
        --no-whole-file \
        $usb_rsync_metadata_options \
        --checksum \
        --delete-delay \
        --filter='protect /firmware/***' \
        --filter='protect /modules*/***' \
        --filter='protect /.t1os-modules-update-*/***' \
        --filter='protect /nodes/***' \
        --filter='protect /processes/***' \
        --filter='protect /state/***' \
        --itemize-changes \
        --human-readable \
        --out-format="$label: %i %n%L" \
        -- "$source"/ "$destination"/
}

sync_large_tree() {
    label=$1
    source=$2
    destination=$3

    echo "Checking $label for changes..."
    # The Chromium executable is larger than the development image's free
    # workspace. Update its existing extents directly instead of requiring a
    # second full-size temporary copy beside the installed executable.
    chromium_engine_filter=
    if [ "$skip_chromium_engine" = True ]; then
        chromium_engine_filter="--exclude=/program/chrome"
        echo 'Chromium engine manifest record is unchanged; skipping its 1.24 GiB checksum scan.'
    fi
    rsync \
        -a \
        --no-whole-file \
        $usb_rsync_metadata_options \
        --inplace \
        $chromium_engine_filter \
        --checksum \
        --delete-delay \
        --itemize-changes \
        --human-readable \
        --out-format="$label: %i %n%L" \
        -- "$source"/ "$destination"/
}

sync_virtualbox_catalogue() {
    label=$1
    source=$2
    destination=$3

    echo "Checking $label for changes..."
    rsync \
        -a \
        --no-whole-file \
        $usb_rsync_metadata_options \
        --checksum \
        --delete-delay \
        --delete-excluded \
        --exclude='catalogue.json' \
        --exclude='*licence*' \
        --exclude='*license*' \
        --itemize-changes \
        --human-readable \
        --out-format="$label: %i %n%L" \
        -- "$source"/ "$destination"/
}

sync_python_software_tree() {
    label=$1
    source=$2
    destination=$3

    echo "Checking $label for changes..."
    rsync \
        -r \
        --no-whole-file \
        --checksum \
        --filter='protect /chromium/google api credentials.json' \
        --delete-delay \
        --delete-excluded \
        --exclude='__pycache__/' \
        --exclude='*.py[co]' \
        --itemize-changes \
        --human-readable \
        --out-format="$label: %i %n%L" \
        -- "$source"/ "$destination"/
}

sync_protected_tree() {
    label=$1
    source=$2
    destination=$3

    echo "Checking $label for changes..."
    rsync \
        -r \
        --no-whole-file \
        --checksum \
        --delete-delay \
        --itemize-changes \
        --human-readable \
        --out-format="$label: %i %n%L" \
        -- "$source"/ "$destination"/
}

sync_file() {
    label=$1
    source=$2
    destination=$3

    echo "Checking $label for changes..."
    rsync \
        -a \
        --no-whole-file \
        --no-perms \
        --no-owner \
        --no-group \
        --checksum \
        --itemize-changes \
        --human-readable \
        --out-format="$label: %i %n%L" \
        -- "$source" "$destination"
}

sync_resource_tree() {
    label=$1
    source=$2
    destination=$3

    echo "Checking $label for changes..."
    rsync \
        -a \
        --no-whole-file \
        --no-perms \
        --no-owner \
        --no-group \
        --omit-dir-times \
        --checksum \
        --delete-delay \
        --itemize-changes \
        --human-readable \
        --out-format="$label: %i %n%L" \
        -- "$source"/ "$destination"/
}

verify_tree() {
    label=$1
    source=$2
    destination=$3

    differences=$(rsync -a --no-whole-file $usb_rsync_metadata_options --checksum --delete --itemize-changes --dry-run -- "$source"/ "$destination"/)
    if [ -n "$differences" ]; then
        echo "$label verification found remaining differences:" >&2
        printf '%s\n' "$differences" >&2
        exit 1
    fi
}

verify_virtualbox_catalogue() {
    label=$1
    source=$2
    destination=$3

    differences=$(rsync -a --no-whole-file $usb_rsync_metadata_options --checksum --delete --delete-excluded \
        --exclude='catalogue.json' --exclude='*licence*' --exclude='*license*' \
        --itemize-changes --dry-run -- "$source"/ "$destination"/)
    if [ -n "$differences" ]; then
        echo "$label verification found remaining differences:" >&2
        printf '%s\n' "$differences" >&2
        exit 1
    fi
}

verify_python_software_tree() {
    label=$1
    source=$2
    destination=$3

    differences=$(rsync -r --no-whole-file --checksum --delete --delete-excluded \
        --exclude='__pycache__/' --exclude='*.py[co]' \
        --itemize-changes --dry-run -- "$source"/ "$destination"/)
    if [ -n "$differences" ]; then
        echo "$label verification found remaining differences:" >&2
        printf '%s\n' "$differences" >&2
        exit 1
    fi
}

verify_protected_tree() {
    label=$1
    source=$2
    destination=$3

    differences=$(rsync -r --no-whole-file --checksum \
        --filter='protect /chromium/google api credentials.json' --delete \
        --itemize-changes --dry-run -- "$source"/ "$destination"/)
    if [ -n "$differences" ]; then
        echo "$label verification found remaining content differences:" >&2
        printf '%s\n' "$differences" >&2
        exit 1
    fi
}

prepare_t1pip_filters() {
    t1pip_software_filter="$stage/t1pip-software.filter"
    t1pip_catalogue_filter="$stage/t1pip-catalogue.filter"
    python3 - \
        "$python_software_destination" \
        "$python_catalogue_destination" \
        "$t1pip_software_filter" \
        "$t1pip_catalogue_filter" <<'PY'
import hashlib
import json
import os
from pathlib import PurePosixPath
import stat
import sys

software, catalogue, software_filter, catalogue_filter = map(os.path.abspath, sys.argv[1:])
state_path = os.path.join(software, '.t1pip', 'state.json')

def fail(message):
    raise SystemExit(message)

def safe(value):
    if not isinstance(value, str) or not value or '\\' in value:
        fail(f'unsafe path in installed Python module state: {value!r}')
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or parsed.as_posix() != value or any(part in ('', '.', '..') for part in parsed.parts):
        fail(f'unsafe path in installed Python module state: {value!r}')
    return value

def verify(root, relative, record):
    path = os.path.join(root, relative)
    status = os.lstat(path)
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
        fail(f'unsafe installed Python module file: {path}')
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if status.st_size != record.get('size') or digest.hexdigest() != record.get('sha256'):
        fail(f'installed Python module file differs from its state: {path}')

software_rules = []
catalogue_rules = []
if os.path.isfile(state_path):
    with open(state_path, encoding='utf-8') as stream:
        state = json.load(stream)
    if not isinstance(state, dict) or state.get('format') != 2:
        fail('installed Python module state has an unsupported format')
    software_rules.append('P /.t1pip/***')
    for record in state.get('files', []):
        relative = safe(record.get('path'))
        area = record.get('area')
        if area == 'site':
            installed = 'lib/python3.14/site-packages/' + relative
        elif area == 'bin':
            installed = 'bin/' + relative
        else:
            fail(f'unknown installed T1OS pip area: {area!r}')
        verify(software, installed, record)
        software_rules.append('P /' + installed)
    for record in state.get('catalogue_files', []):
        relative = safe(record.get('path'))
        verify(catalogue, relative, record)
        catalogue_rules.append('P /' + relative)

for path, rules in ((software_filter, software_rules), (catalogue_filter, catalogue_rules)):
    with open(path, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write('\n'.join(rules) + ('\n' if rules else ''))
PY
}

sync_managed_python_release() {
    prepare_t1pip_filters
    echo 'Checking Python software for changes...'
    rsync -r --no-whole-file \
        --checksum --delete-delay --filter="merge $t1pip_software_filter" \
        --itemize-changes --human-readable --out-format='Python software: %i %n%L' \
        -- "$python_software_source"/ "$python_software_destination"/
    echo 'Checking Python catalogue for changes...'
    rsync -r --no-whole-file \
        --checksum --delete-delay --filter="merge $t1pip_catalogue_filter" \
        --itemize-changes --human-readable --out-format='Python catalogue: %i %n%L' \
        -- "$python_catalogue_source"/ "$python_catalogue_destination"/
}

protect_managed_python_release() {
    python3 - \
        "$mount_point" \
        "$python_software_destination" \
        "$python_catalogue_destination" \
        "$image_catalogue_destination" \
        "$build_destination" \
        "$boot_destination" \
        "$virtualbox_software_destination" \
        "$expected_python_release" \
        "$expected_python_manifest_sha256" \
        "$target_mode" \
        "$managed_verify_only" \
        "$profiled_python_config" \
        "$boot_policy_manifest" <<'PY'
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import stat
import sys

(
    mount,
    software,
    catalogue,
    image_catalogue,
    build_software,
    boot,
    virtualbox_software,
) = (os.path.abspath(value) for value in sys.argv[1:8])
expected_release = sys.argv[8]
expected_manifest_sha256 = sys.argv[9]
target_mode = sys.argv[10]
managed_python_only = sys.argv[11] == 'True'
profiled_python_config = os.path.abspath(sys.argv[12])
boot_policy_manifest = os.path.abspath(sys.argv[13])
if target_mode not in ('drive', 'image'):
    raise SystemExit('protected deployment target mode is invalid')
normalize_metadata = target_mode == 'image'
root_paths = {
    'software': software,
    'catalogue': catalogue,
    'image_catalogue': image_catalogue,
    'build_software': build_software,
    'boot': boot,
    'virtualbox_software': virtualbox_software,
}
canonical_root_paths = {
    'software': os.path.join(mount, 'the one', 'software', 'python'),
    'catalogue': os.path.join(mount, 'the one', 'catalogue', 'python'),
    'image_catalogue': os.path.join(mount, 'the one', 'catalogue', 'image'),
    'build_software': os.path.join(mount, 'the one', 'build'),
    'boot': os.path.join(mount, 'boot'),
    'virtualbox_software': os.path.join(mount, 'the one', 'software', 'virtualbox'),
}
if root_paths != canonical_root_paths:
    raise SystemExit('protected deployment arguments do not name the six canonical roots')
expected_external = (
    ('image_catalogue', 'source/catalogue/image', '/the one/catalogue/image', False),
    ('build_software', 'source/build software', '/the one/build', True),
    ('boot', 'source/boot', '/boot', True),
    ('virtualbox_software', 'source/software/virtualbox', '/the one/software/virtualbox', True),
)

def fail(message):
    raise SystemExit(message)

def lstat_regular(path):
    try:
        status = os.lstat(path)
    except FileNotFoundError:
        fail(f'protected release file is missing: {path}')
    if not stat.S_ISREG(status.st_mode) or stat.S_ISLNK(status.st_mode):
        fail(f'protected release path is not a regular file: {path}')
    if status.st_nlink != 1:
        fail(f'protected release file is hard-linked: {path}')
    return status

def digest(path):
    value = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()

manifest_path = os.path.join(software, 'manifest.json')
lstat_regular(manifest_path)
if not re.fullmatch(r'[0-9a-f]{64}', expected_manifest_sha256):
    fail('expected Python manifest digest is malformed')
if digest(manifest_path) != expected_manifest_sha256:
    fail('deployed Python manifest differs from the immutable release lock')
try:
    descriptor = os.open(
        manifest_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    )
    with os.fdopen(descriptor, encoding='utf-8') as stream:
        manifest = json.load(stream)
except (OSError, UnicodeError, json.JSONDecodeError) as error:
    fail(f'deployed Python manifest is malformed: {error}')
if manifest.get('state') != 'verified' or manifest.get('release') != expected_release:
    fail('deployed Python manifest does not describe the expected verified release')
try:
    with open(boot_policy_manifest, encoding='utf-8') as stream:
        boot_policy = json.load(stream)
except (OSError, UnicodeError, json.JSONDecodeError) as error:
    fail(f'boot protected-root policy is unreadable: {error}')
profile_policy = boot_policy.get('profiled_python_entrypoints')
if (
    boot_policy.get('format') != 1
    or boot_policy.get('component') != 't1os-boot-protected-roots'
    or not isinstance(profile_policy, dict)
    or set(profile_policy) != {
        'format', 'owner', 'group', 'install_mode', 'shebang', 'entries'
    }
    or profile_policy.get('format') != 1
    or profile_policy.get('owner') != 0
    or profile_policy.get('group') != 0
    or profile_policy.get('install_mode') != '0555'
    or profile_policy.get('shebang') != '#!"/the one/software/python/bin/python" -B\n'
    or not isinstance(profile_policy.get('entries'), list)
    or not profile_policy['entries']
    or manifest.get('install_policy', {}).get('owner') != 0
    or manifest.get('install_policy', {}).get('group') != 0
):
    fail('independent boot policy or Python ownership contract differs')

def validate_relative(value, *, root_allowed):
    if (
        not isinstance(value, str)
        or not value
        or '\\' in value
        or any(character in value for character in '\x00\t\r\n')
    ):
        fail(f'invalid protected release relative path: {value!r}')
    if value == '.':
        if root_allowed:
            return value
        fail('a protected release file cannot use the root path')
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or '..' in parsed.parts or '.' in parsed.parts:
        fail(f'unsafe protected release relative path: {value!r}')
    if parsed.as_posix() != value:
        fail(f'non-canonical protected release relative path: {value!r}')
    return value

def parse_records(entry, label):
    if not isinstance(entry, dict):
        fail(f'protected release root is malformed: {label}')
    directories = entry.get('directories')
    files = entry.get('files')
    tree = entry.get('tree')
    if not isinstance(directories, list) or not isinstance(files, list) or not isinstance(tree, dict):
        fail(f'protected release inventories are malformed: {label}')
    directory_modes = {}
    for record in directories:
        if not isinstance(record, dict) or set(record) != {'path', 'install_mode'}:
            fail(f'malformed directory record in {label}')
        relative = validate_relative(record['path'], root_allowed=True)
        if relative in directory_modes or record['install_mode'] != '0755':
            fail(f'invalid or duplicate directory record in {label}: {relative}')
        directory_modes[relative] = 0o755
    if '.' not in directory_modes:
        fail(f'protected release root record is missing from {label}')
    file_records = {}
    for record in files:
        if not isinstance(record, dict) or set(record) != {
            'path', 'size', 'sha256', 'install_mode'
        }:
            fail(f'malformed file record in {label}')
        relative = validate_relative(record['path'], root_allowed=False)
        if relative in file_records or relative in directory_modes:
            fail(f'duplicate protected release path in {label}: {relative}')
        if type(record['size']) is not int or record['size'] < 0:
            fail(f'invalid protected release file size in {label}: {relative}')
        if not isinstance(record['sha256'], str) or re.fullmatch(
            r'[0-9a-f]{64}', record['sha256']
        ) is None:
            fail(f'invalid protected release digest in {label}: {relative}')
        if record['install_mode'] not in ('0444', '0555'):
            fail(f'invalid protected release file mode in {label}: {relative}')
        file_records[relative] = record
    if list(directory_modes) != sorted(directory_modes) or list(file_records) != sorted(file_records):
        fail(f'protected release records are not canonically ordered: {label}')
    tree_digest = hashlib.sha256()
    for relative, install_mode in directory_modes.items():
        tree_digest.update(f'directory\t{relative}\t{install_mode:04o}\n'.encode('utf-8'))
    for relative, record in file_records.items():
        tree_digest.update(
            (
                f"file\t{relative}\t{record['size']}\t{record['sha256']}\t"
                f"{record['install_mode']}\n"
            ).encode('utf-8')
        )
    if (
        set(tree) != {'algorithm', 'directories', 'files', 'bytes', 'sha256'}
        or tree.get('algorithm') != 't1os-install-tree-sha256-v2'
        or type(tree.get('directories')) is not int
        or type(tree.get('files')) is not int
        or type(tree.get('bytes')) is not int
        or tree.get('directories') != len(directory_modes)
        or tree.get('files') != len(file_records)
        or tree.get('bytes') != sum(item['size'] for item in file_records.values())
        or not isinstance(tree.get('sha256'), str)
        or re.fullmatch(r'[0-9a-f]{64}', tree['sha256']) is None
        or tree_digest.hexdigest() != tree['sha256']
    ):
        fail(f'protected release tree summary is malformed: {label}')
    return directory_modes, file_records

if manifest.get('software', {}).get('destination') != '/the one/software/python':
    fail('Python software manifest destination differs')
if manifest.get('catalogue', {}).get('destination') != '/the one/catalogue/python':
    fail('Python catalogue manifest destination differs')

external = boot_policy.get('roots')
if not isinstance(external, list) or len(external) != len(expected_external):
    fail('independent boot protected-root inventory differs')
external_by_name = {}
for entry, expected in zip(external, expected_external):
    name, source, destination, exclude_generated = expected
    if (
        not isinstance(entry, dict)
        or entry.get('name') != name
        or entry.get('source') != source
        or entry.get('destination') != destination
        or entry.get('exclude_generated_bytecode') is not exclude_generated
        or name in external_by_name
    ):
        fail(f'protected external-root contract differs: {name}')
    external_by_name[name] = entry

profiled = set()
profiled_destinations = []
external_contract = {
    name: (source, destination)
    for name, source, destination, _ in expected_external
}
for entry in profile_policy['entries']:
    if not isinstance(entry, dict) or set(entry) != {'root', 'path', 'destination'}:
        fail('profiled Python entrypoint record is malformed')
    name = entry['root']
    relative = validate_relative(entry['path'], root_allowed=False)
    destination = entry['destination']
    if (
        name not in external_contract
        or not relative.endswith('.py')
        or destination != external_contract[name][1].rstrip('/') + '/' + relative
        or (name, relative) in profiled
        or destination in profiled_destinations
    ):
        fail(f'profiled Python entrypoint identity differs: {entry!r}')
    profiled.add((name, relative))
    profiled_destinations.append(destination)
if profiled_destinations != sorted(profiled_destinations):
    fail('profiled Python entrypoint inventory is not canonically ordered')

seen_profiled = set()
for name in ('build_software', 'boot', 'virtualbox_software'):
    files = external_by_name[name].get('files')
    if not isinstance(files, list):
        fail(f'profiled Python manifest root is malformed: {name}')
    for record in files:
        if not isinstance(record, dict) or not isinstance(record.get('path'), str):
            fail(f'profiled Python manifest record is malformed: {name}')
        identity = (name, record['path'])
        if identity in profiled:
            seen_profiled.add(identity)
            expected_mode = '0555'
        elif record['path'].endswith('.py'):
            expected_mode = '0444'
        else:
            continue
        if record.get('install_mode') != expected_mode:
            fail(
                f'profiled/ordinary Python mode differs: '
                f'{name}/{record["path"]} expected {expected_mode}'
            )
if seen_profiled != profiled:
    fail('canonical manifest omits a profiled Python entrypoint')

specifications = [
    ('software', manifest['software'], True),
    ('catalogue', manifest['catalogue'], False),
]
if managed_python_only:
    specifications.append(
        ('image_catalogue', external_by_name['image_catalogue'], False)
    )
else:
    specifications.extend(
        (name, external_by_name[name], False) for name, *_ in expected_external
    )

managed_records = {'software': {}, 'catalogue': {}}
t1pip_state_path = os.path.join(software, '.t1pip', 'state.json')
if os.path.isfile(t1pip_state_path):
    try:
        with open(t1pip_state_path, encoding='utf-8') as stream:
            t1pip_state = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f'installed Python module state is malformed: {error}')
    if not isinstance(t1pip_state, dict) or t1pip_state.get('format') != 2:
        fail('installed Python module state has an unsupported format')

    def add_managed_record(area, relative, record, executable=False):
        relative = validate_relative(relative, root_allowed=False)
        if (
            not isinstance(record, dict)
            or type(record.get('size')) is not int
            or record['size'] < 0
            or not isinstance(record.get('sha256'), str)
            or re.fullmatch(r'[0-9a-f]{64}', record['sha256']) is None
            or relative in managed_records[area]
        ):
            fail(f'invalid installed Python module ownership record: {relative}')
        managed_records[area][relative] = {
            'path': relative,
            'size': record['size'],
            'sha256': record['sha256'],
            'install_mode': '0555' if executable else '0444',
        }

    for record in t1pip_state.get('files', []):
        if not isinstance(record, dict):
            fail('installed Python module file record is malformed')
        relative = validate_relative(record.get('path'), root_allowed=False)
        if record.get('area') == 'site':
            installed_relative = 'lib/python3.14/site-packages/' + relative
            installed_path = os.path.join(software, installed_relative)
            try:
                with open(installed_path, 'rb') as stream:
                    executable = stream.read(4) == b'\x7fELF'
            except OSError as error:
                fail(f'installed Python module file is missing: {error}')
        elif record.get('area') == 'bin':
            installed_relative = 'bin/' + relative
            executable = True
        else:
            fail(f"unknown installed Python module area: {record.get('area')!r}")
        add_managed_record('software', installed_relative, record, executable)
    for record in t1pip_state.get('catalogue_files', []):
        if not isinstance(record, dict):
            fail('installed Python module catalogue record is malformed')
        add_managed_record(
            'catalogue', validate_relative(record.get('path'), root_allowed=False),
            record, True,
        )

def scan_root(root):
    root = os.path.abspath(root)
    if os.path.commonpath((mount, root)) != mount or os.path.realpath(root) != root:
        fail(f'protected release root escapes its mount: {root}')
    status = os.lstat(root)
    mount_device = os.lstat(mount).st_dev
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
    if (
        stat.S_ISLNK(status.st_mode)
        or not stat.S_ISDIR(status.st_mode)
        or (reparse and getattr(status, 'st_file_attributes', 0) & reparse)
    ):
        fail(f'protected release root is not a real directory: {root}')
    if status.st_dev != mount_device:
        fail(f'protected release root is a nested filesystem: {root}')
    directories = {'.': (root, status)}
    files = {}
    pending = [(root, '')]
    while pending:
        directory, prefix = pending.pop()
        with os.scandir(directory) as entries:
            for item in entries:
                relative = f'{prefix}/{item.name}' if prefix else item.name
                path = item.path
                item_status = item.stat(follow_symlinks=False)
                mode = item_status.st_mode
                if (
                    item.is_symlink()
                    or (
                        normalize_metadata
                        and mode & (stat.S_ISUID | stat.S_ISGID)
                    )
                    or (
                        reparse
                        and getattr(item_status, 'st_file_attributes', 0) & reparse
                    )
                ):
                    fail(f'unsafe entry in protected release root: {path}')
                if item_status.st_dev != mount_device:
                    fail(f'nested filesystem in protected release root: {path}')
                if os.path.realpath(path) != os.path.abspath(path):
                    fail(f'protected release entry resolves elsewhere: {path}')
                if stat.S_ISDIR(mode):
                    directories[relative] = (path, item_status)
                    pending.append((path, relative))
                elif stat.S_ISREG(mode):
                    if item_status.st_nlink != 1:
                        fail(f'protected release file is hard-linked: {path}')
                    files[relative] = (path, item_status)
                else:
                    fail(f'special entry in protected release root: {path}')
    return directories, files

validated = []
credential_relative = 'chromium/google api credentials.json'
for name, entry, include_manifest in specifications:
    root = root_paths[name]
    directory_modes, file_records = parse_records(entry, name)
    if include_manifest:
        if 'manifest.json' in file_records or 'manifest.json' in directory_modes:
            fail('self-referential Python manifest inventory is forbidden')
        file_records = dict(file_records)
        file_records['manifest.json'] = {
            'path': 'manifest.json',
            'size': os.lstat(manifest_path).st_size,
            'sha256': expected_manifest_sha256,
            'install_mode': '0444',
        }
    for relative, record in managed_records.get(name, {}).items():
        if relative in file_records or relative in directory_modes:
            fail(f'installed package collides with the immutable Python release: {relative}')
        file_records[relative] = record
        parent = PurePosixPath(relative).parent
        while parent.as_posix() != '.':
            directory_modes.setdefault(parent.as_posix(), 0o755)
            parent = parent.parent
    actual_directories, actual_files = scan_root(root)
    supplemental_credentials = {}
    supplemental_manager = {}
    if name == 'build_software' and credential_relative in actual_files:
        supplemental_credentials[credential_relative] = actual_files.pop(
            credential_relative
        )
    if name == 'software' and os.path.isfile(t1pip_state_path):
        for relative in list(actual_files):
            if relative == '.t1pip/state.json' or relative.startswith('.t1pip/'):
                path, status = actual_files.pop(relative)
                if relative.startswith('.t1pip/transactions/'):
                    fail(f'an unfinished Python module transaction is present: {path}')
                supplemental_manager[relative] = (
                    'file', status.st_size, digest(path)
                )
        for relative in list(actual_directories):
            if relative == '.t1pip' or relative.startswith('.t1pip/'):
                actual_directories.pop(relative)
                supplemental_manager[relative] = ('directory', 0, '')
        if '.t1pip/state.json' not in supplemental_manager:
            fail('installed Python module state disappeared during verification')
    if set(actual_directories) != set(directory_modes):
        fail(f'protected release directory inventory mismatch below {root}')
    if set(actual_files) != set(file_records):
        fail(f'protected release file inventory mismatch below {root}')
    for relative, record in file_records.items():
        path, status = actual_files[relative]
        if status.st_size != record['size'] or digest(path) != record['sha256']:
            fail(f'protected release content mismatch: {path}')
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as stream:
            prefix = stream.read(128)
            is_elf = prefix[:4] == b'\x7fELF'
        is_profiled = (name, relative) in profiled
        if is_profiled and not prefix.startswith(b'#!"/the one/software/python/bin/python" -B\n'):
            fail(f'profiled Python entrypoint has an unsafe shebang: {path}')
        expected_mode = '0555' if (
            is_profiled
            or (
                not relative.endswith('.py')
                and (is_elf or (name == 'software' and relative.startswith('bin/')))
            )
        ) else '0444'
        if record['install_mode'] != expected_mode:
            fail(f'protected release executable/data policy differs: {path}')
    validated.append((
        directory_modes,
        file_records,
        actual_directories,
        actual_files,
        supplemental_credentials,
        supplemental_manager,
    ))

# Image builds normalize reproducible POSIX metadata only after every root has
# passed its complete no-follow inventory and content check. Physical USB
# updates deliberately do not chmod/chown DrvFS paths: those bits are not the
# T1OS runtime authorization boundary and some valid NTFS ACLs reject chmod.
def set_policy(path, expected_mode, *, directory, gid=0):
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    if directory:
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        status = os.fstat(descriptor)
        if directory:
            if not stat.S_ISDIR(status.st_mode):
                fail(f'protected release directory changed during hardening: {path}')
        elif not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
            fail(f'protected release file changed during hardening: {path}')
        if status.st_uid != 0 or status.st_gid != gid:
            os.fchown(descriptor, 0, gid)
            status = os.fstat(descriptor)
        if stat.S_IMODE(status.st_mode) != expected_mode:
            os.fchmod(descriptor, expected_mode)
    finally:
        os.close(descriptor)

if normalize_metadata:
    for (
        directory_modes,
        file_records,
        actual_directories,
        actual_files,
        supplemental_credentials,
        supplemental_manager,
    ) in validated:
        for relative, (path, _) in actual_files.items():
            set_policy(path, int(file_records[relative]['install_mode'], 8), directory=False)
        # Children first keeps traversal available until the root itself is sealed.
        for relative in sorted(actual_directories, key=lambda value: value.count('/'), reverse=True):
            path, _ = actual_directories[relative]
            set_policy(path, directory_modes[relative], directory=True)
        for path, _ in supplemental_credentials.values():
            set_policy(path, 0o440, directory=False, gid=1000)

for ancestor in (
    mount,
    os.path.join(mount, 'the one'),
    os.path.join(mount, 'the one', 'software'),
    os.path.join(mount, 'the one', 'catalogue'),
):
    status = os.lstat(ancestor)
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
        fail(f'canonical protected-release ancestor is unsafe: {ancestor}')
    if normalize_metadata:
        status = os.lstat(ancestor)
        if status.st_uid != 0 or status.st_gid != 0:
            fail(f'canonical protected-release ancestor ownership mismatch: {ancestor}')
        if stat.S_IMODE(status.st_mode) not in (0o555, 0o755):
            fail(f'canonical protected-release ancestor mode mismatch: {ancestor}')

# Re-scan after chmod/chown and prove exact type, link count, mode, and owner.
for (name, _, _), (
    directory_modes,
    file_records,
    _,
    _,
    supplemental_credentials,
    supplemental_manager,
) in zip(specifications, validated):
    root = root_paths[name]
    actual_directories, actual_files = scan_root(root)
    current_credentials = {}
    if name == 'build_software' and credential_relative in actual_files:
        current_credentials[credential_relative] = actual_files.pop(
            credential_relative
        )
    current_manager = {}
    if name == 'software' and os.path.isfile(t1pip_state_path):
        for relative in list(actual_files):
            if relative == '.t1pip/state.json' or relative.startswith('.t1pip/'):
                path, status = actual_files.pop(relative)
                current_manager[relative] = ('file', status.st_size, digest(path))
        for relative in list(actual_directories):
            if relative == '.t1pip' or relative.startswith('.t1pip/'):
                actual_directories.pop(relative)
                current_manager[relative] = ('directory', 0, '')
    if current_manager != supplemental_manager:
        fail('Python module state changed during verification')
    if set(current_credentials) != set(supplemental_credentials):
        fail('protected Google API credential inventory changed during hardening')
    for relative, expected_mode in directory_modes.items():
        path, status = actual_directories[relative]
        if normalize_metadata and (
            stat.S_IMODE(status.st_mode) != expected_mode
            or status.st_uid != 0
            or status.st_gid != 0
        ):
            fail(f'protected release directory policy mismatch: {path}')
    for relative, record in file_records.items():
        path, status = actual_files[relative]
        if (
            status.st_nlink != 1
            or (
                normalize_metadata
                and (
                    stat.S_IMODE(status.st_mode) != int(record['install_mode'], 8)
                    or status.st_uid != 0
                    or status.st_gid != 0
                    or status.st_mode & (stat.S_ISUID | stat.S_ISGID)
                )
            )
        ):
            fail(f'protected release file policy mismatch: {path}')
    for path, status in current_credentials.values():
        if status.st_nlink != 1 or (
            normalize_metadata
            and (
                stat.S_IMODE(status.st_mode) != 0o440
                or status.st_uid != 0
                or status.st_gid != 1000
            )
        ):
            fail(f'protected Google API credential policy mismatch: {path}')

if normalize_metadata:
    for ancestor in (
        mount,
        os.path.join(mount, 'the one'),
        os.path.join(mount, 'the one', 'software'),
        os.path.join(mount, 'the one', 'catalogue'),
    ):
        status = os.lstat(ancestor)
        if (
            stat.S_IMODE(status.st_mode) not in (0o555, 0o755)
            or status.st_uid != 0
            or status.st_gid != 0
        ):
            fail(f'canonical protected-release ancestor policy mismatch: {ancestor}')
PY
}

verify_managed_python_release() {
    prepare_t1pip_filters
    differences=$(rsync -r --no-whole-file --checksum --delete \
        --filter="merge $t1pip_software_filter" \
        --itemize-changes --dry-run -- \
        "$python_software_source"/ "$python_software_destination"/)
    [ -z "$differences" ] || {
        echo 'Managed Python software verification found remaining content differences:' >&2
        printf '%s\n' "$differences" >&2
        exit 1
    }
    differences=$(rsync -r --no-whole-file --checksum --delete \
        --filter="merge $t1pip_catalogue_filter" \
        --itemize-changes --dry-run -- \
        "$python_catalogue_source"/ "$python_catalogue_destination"/)
    [ -z "$differences" ] || {
        echo 'Managed Python catalogue verification found remaining content differences:' >&2
        printf '%s\n' "$differences" >&2
        exit 1
    }
    differences=$(rsync -r --no-whole-file --checksum --delete \
        --itemize-changes --dry-run -- \
        "$image_catalogue_source"/ "$image_catalogue_destination"/)
    [ -z "$differences" ] || {
        echo 'Managed Python image-package catalogue verification found remaining content differences:' >&2
        printf '%s\n' "$differences" >&2
        exit 1
    }

    readelf -l "$python_software_destination/bin/python" |
        grep -F 'Requesting program interpreter: /the one/catalogue/python/ld-linux-x86-64.so.2' >/dev/null
    readelf -d "$python_software_destination/bin/python" |
        grep -F 'Library runpath: [/the one/catalogue/python]' >/dev/null

    PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH='' \
        "$python_catalogue_destination/ld-linux-x86-64.so.2" \
        --library-path "$python_catalogue_destination:$image_catalogue_destination:$image_catalogue_destination/pillow.libs" \
        "$python_software_destination/bin/python" -B -I -c \
        'import sys; sys.path.insert(0, sys.argv[1]); import freetype, pyroute2; from PIL import Image; assert sys.version_info[:3] == (3, 14, 7); assert Image.__version__ == "12.3.0"' \
        "$image_catalogue_destination"
}

verify_tree_without_permissions() {
    label=$1
    source=$2
    destination=$3

    # Physical NTFS targets deliberately do not preserve POSIX ownership,
    # modes, or timestamps.  Reuse the same target-specific metadata options
    # as the corresponding sync so exhaustive verification measures content
    # and topology instead of reporting copy-time mtimes as payload drift.
    # storage.img leaves this variable empty and therefore retains archive
    # metadata verification.
    differences=$(rsync -a --no-whole-file $usb_rsync_metadata_options --no-perms --no-owner --no-group --checksum --delete --itemize-changes --dry-run -- "$source"/ "$destination"/)
    if [ -n "$differences" ]; then
        echo "$label verification found remaining differences:" >&2
        printf '%s\n' "$differences" >&2
        exit 1
    fi
}

verify_resource_tree() {
    label=$1
    source=$2
    destination=$3

    differences=$(rsync -a --no-whole-file --no-perms --no-owner --no-group --omit-dir-times --checksum --delete --itemize-changes --dry-run -- "$source"/ "$destination"/)
    if [ -n "$differences" ]; then
        echo "$label verification found remaining differences:" >&2
        printf '%s\n' "$differences" >&2
        exit 1
    fi
}

if [ "$managed_verify_only" = True ]; then
    protect_managed_python_release
    verify_managed_python_release
    echo 'Managed USB release content and runtime verification passed; no payload bytes were changed.'
    exit 0
fi

if [ "$managed_sync_only" = True ]; then
    sync_protected_tree 'build' "$stage/build" "$build_destination"
    sync_python_software_tree 'boot' "$boot_source" "$boot_destination"
    sync_python_software_tree \
        'VirtualBox software' \
        "$virtualbox_software_source" \
        "$virtualbox_software_destination"
    sync_protected_tree \
        'image catalogue' \
        "$image_catalogue_source" \
        "$image_catalogue_destination"
    sync_managed_python_release
    sync -f "$mount_point"
    protect_managed_python_release
    verify_managed_python_release
    echo 'Managed release roots were synchronized and verified without changing unrelated runtime trees.'
    exit 0
fi

if root_selected build; then
    sync_protected_tree 'build' "$stage/build" "$build_destination"
fi
if root_selected boot; then
    sync_python_software_tree 'boot' "$boot_source" "$boot_destination"
fi
if root_selected drivers; then
    sync_driver_runtime 'driver runtime' "$drivers_source" "$drivers_destination"
    if [ "$target_mode" = image ]; then
        chmod 0755 "$drivers_destination/tools/modprobe"
    fi
    test -s "$drivers_destination/settings/policy.json"
    test -s "$drivers_destination/settings/runtime.json"
    readelf -h "$drivers_destination/tools/modprobe" >/dev/null
fi
if root_selected graphics; then
    sync_tree 'graphics catalogue' "$graphics_catalogue_source" "$graphics_catalogue_destination"
fi
if root_selected virtualbox_catalogue; then
    sync_virtualbox_catalogue 'VirtualBox catalogue' "$virtualbox_catalogue_source" "$virtualbox_catalogue_destination"
fi
if root_selected virtualbox_software; then
    sync_python_software_tree 'VirtualBox software' "$virtualbox_software_source" "$virtualbox_software_destination"
fi
if root_selected virtualbox_settings; then
    sync_tree 'VirtualBox settings' "$virtualbox_settings_source" "$virtualbox_settings_destination"
fi
if root_selected audio_catalogue; then
    sync_tree 'audio catalogue' "$audio_catalogue_source" "$audio_catalogue_destination"
fi
if root_selected audio_software; then
    sync_tree 'audio software' "$audio_software_source" "$audio_software_destination"
    for media_binary in t1-media-decoderd t1-video-decode; do
        if [ -f "$audio_software_destination/$media_binary" ]; then
            if [ "$target_mode" = image ]; then
                chown 0:0 "$audio_software_destination/$media_binary"
                chmod 0755 "$audio_software_destination/$media_binary"
            fi
            readelf -h "$audio_software_destination/$media_binary" >/dev/null
        fi
    done
fi
if root_selected network_catalogue; then
    sync_tree 'network catalogue' "$network_catalogue_source" "$network_catalogue_destination"
fi
if root_selected network_software; then
    sync_tree 'network software' "$network_software_source" "$network_software_destination"
    if [ "$target_mode" = image ]; then
        chmod 0755 "$network_software_destination/wireless-engine"
    fi
fi
if root_selected network_settings; then
    sync_file 'network certificate bundle' "$network_settings_source/cacerts.pem" "$network_settings_destination/cacerts.pem"
    if [ ! -e "$network_settings_destination/network.txt" ]; then
        sync_file 'default network settings' "$network_settings_source/network.txt" "$network_settings_destination/network.txt"
        if [ "$target_mode" = image ]; then
            chmod 0644 "$network_settings_destination/network.txt"
        fi
    else
        echo 'Preserving the runtime-managed network.txt file.'
    fi
    if [ -f "$network_settings_source/wireless.txt" ]; then
        sync_file 'configured wireless settings' "$network_settings_source/wireless.txt" "$network_settings_destination/wireless.txt"
    elif [ -f "$network_settings_destination/wireless.txt" ]; then
        echo 'Preserving the runtime-managed wireless.txt file.'
    fi
    if [ "$target_mode" = image ]; then
        chmod 0644 "$network_settings_destination/cacerts.pem"
        if [ -f "$network_settings_destination/wireless.txt" ]; then
            chmod 0600 "$network_settings_destination/wireless.txt"
        fi
    fi
fi
preserve_media_decode_kill_switch=0
if root_selected media_settings && \
    [ "$target_mode" = drive ] &&
    [ -e "$media_settings_destination/video decode service.json" ] &&
    python3 - "$media_settings_destination/video decode service.json" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding='utf-8') as stream:
        policy = json.load(stream)
except Exception:
    raise SystemExit(1)
raise SystemExit(
    0
    if isinstance(policy, dict) and policy.get('kill_switch') is True
    else 1
)
PY
then
    preserve_media_decode_kill_switch=1
fi
if root_selected media_settings; then
    if [ "$preserve_media_decode_kill_switch" = 1 ]; then
        echo 'Preserving the USB media decode service emergency kill switch.'
    else
        sync_file 'development media decode service policy' \
            "$media_settings_source/video decode service.json" \
            "$media_settings_destination/video decode service.json"
    fi
    if [ "$target_mode" = image ]; then
        chmod 0644 "$media_settings_destination/video decode service.json"
    fi
fi
if root_selected media_settings || root_selected chromium || root_selected audio_software; then
python3 - "$media_settings_destination/video decode service.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as stream:
    policy = json.load(stream)
if not isinstance(policy, dict):
    raise SystemExit('media decode service policy is not an object')
if type(policy.get('protocol_version')) is not int or policy['protocol_version'] != 1:
    raise SystemExit('media decode service policy is not T1MD version 1')
if (
    type(policy.get('max_sessions')) is not int
    or policy['max_sessions'] != 8
):
    raise SystemExit('media decode service max_sessions must be exactly 8')
if not isinstance(policy.get('enabled'), bool):
    raise SystemExit('media decode service enabled policy is not Boolean')
if not isinstance(policy.get('kill_switch'), bool):
    raise SystemExit('media decode service kill switch is not Boolean')
if not isinstance(policy.get('development_debug'), bool):
    raise SystemExit('media decode service development debug setting is not Boolean')
PY
fi
if root_selected chromium; then
    sync_large_tree 'Chromium software' "$chromium_software_source" "$chromium_software_destination"
    if [ "$target_mode" = image ]; then
        chmod 0755 "$chromium_software_destination/program/chrome" "$chromium_software_destination/tools/"*
        chown 0:0 "$chromium_software_destination/program/chrome-sandbox"
        chmod 4755 "$chromium_software_destination/program/chrome-sandbox"
        test "$(stat -c '%u:%g:%a' "$chromium_software_destination/program/chrome-sandbox")" = '0:0:4755'
    fi
fi
if root_selected media_settings || root_selected chromium || root_selected audio_software; then
python3 - \
    "$media_settings_destination/video decode service.json" \
    "$audio_software_destination" \
    "$chromium_software_destination/manifest.json" \
    "$native_protocol_header" \
    "$native_watchdog_header" \
    "$chromium_protocol_header" \
    "$chromium_source_manifest" <<'PY'
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

(
    policy_path,
    audio_root,
    chromium_manifest_path,
    native_protocol_path,
    native_watchdog_path,
    chromium_protocol_path,
    chromium_source_manifest_path,
) = map(Path, sys.argv[1:])
chromium_root = chromium_manifest_path.parent
with policy_path.open(encoding='utf-8') as stream:
    policy = json.load(stream)

native_protocol = native_protocol_path.read_bytes()
if native_protocol != chromium_protocol_path.read_bytes():
    raise SystemExit('native and Chromium T1MD protocol headers differ')
protocol_hash = hashlib.sha256(native_protocol).hexdigest()
watchdog_header_hash = hashlib.sha256(
    native_watchdog_path.read_bytes()
).hexdigest()
with chromium_source_manifest_path.open(encoding='utf-8') as stream:
    source_contract = json.load(stream)
revision = source_contract.get('chromium_revision')
source_hash = source_contract.get('source_overlay_sha256')
if (
    type(source_contract.get('format')) is not int
    or source_contract.get('format') != 1
    or source_contract.get('protocol_magic') != 'T1MD'
    or type(source_contract.get('protocol_version')) is not int
    or source_contract.get('protocol_version') != 1
    or source_contract.get('chromium_version') != '150.0.7871.181'
    or source_contract.get('chromium_tag')
    != 'refs/tags/150.0.7871.181'
    or revision != '24b04c927b23c39cf9c5227cc8dc6f64a744c8e9'
    or source_contract.get('depot_tools_revision')
    != '93919990d65a94fd62a5b1bae4e2909df6996e4a'
    or type(source_contract.get('descriptor_pool_size')) is not int
    or source_contract.get('descriptor_pool_size') != 8
    or not isinstance(source_hash, str)
    or re.fullmatch(r'[0-9a-f]{64}', source_hash) is None
):
    raise SystemExit('Chromium source provenance/pool contract differs')
build_marker = (
    'T1OS_MEDIA_DECODER=T1MD/1;brokered_socket=1;pool=8;'
    f'chromium={revision};protocol_sha256={protocol_hash};'
    f'source_sha256={source_hash}'
)
if (
    source_contract.get('protocol_header_sha256') != protocol_hash
    or source_contract.get('build_marker') != build_marker
):
    raise SystemExit('Chromium source/protocol provenance differs')

forbidden_language_suffixes = {
    '.asm', '.bash', '.c', '.cc', '.cjs', '.cpp', '.cxx', '.fish',
    '.h', '.hh', '.hpp', '.inc', '.java', '.js', '.jsx', '.m', '.mm',
    '.py', '.rs', '.s', '.sh', '.ts', '.tsx', '.zsh', '.mojom', '.gn',
    '.gni', '.proto', '.idl', '.webidl', '.cmake', '.mk', '.gradle',
    '.scala', '.cs', '.fs', '.vb', '.r', '.dart', '.php', '.t1os',
    '.img',
}
for runtime_root in (audio_root, chromium_root):
    for path in runtime_root.rglob('*'):
        if not path.is_file():
            continue
        if path.suffix.lower() in forbidden_language_suffixes:
            raise SystemExit(
                f'compiled runtime contains a loose language file: {path}'
            )
        with path.open('rb') as stream:
            if stream.read(2) == b'#!':
                raise SystemExit(
                    f'compiled runtime contains an interpreted script: {path}'
                )

if not policy.get('enabled') or policy.get('kill_switch'):
    raise SystemExit(0)

for name in ('t1-media-decoderd', 't1-video-decode'):
    path = audio_root / name
    if not path.is_file():
        raise SystemExit(f'enabled media decode service binary is missing: {path}')
if (audio_root / 't1-media-decode-worker').exists():
    raise SystemExit(
        'the LSM-ineligible standalone media worker must not be deployed'
    )

with (audio_root / 'manifest.json').open(encoding='utf-8') as stream:
    audio = json.load(stream)
audio_runtime = audio.get('runtime', {})
audio_protocol = audio_runtime.get('media_decode_protocol', {})
expected_audio_protocol = {
    'name': 'T1MD',
    'version': 1,
    'transport': 'AF_UNIX/SOCK_SEQPACKET',
    'header_sha256': protocol_hash,
    'maximum_decode_requests': 1,
    'maximum_in_flight_frames': 16,
    'backpressure_feature_bit': 64,
    'linear_memory_output_feature_bit': 128,
    'backpressure_message_type': 15,
    'backpressure_timeout_ms': 0,
    'backpressure_reset_terminal': 'RESET_DONE-without-EXIT',
}
if (
    not isinstance(audio_protocol, dict)
    or set(audio_protocol) != set(expected_audio_protocol)
    or any(
        type(audio_protocol.get(name)) is not type(value)
        or audio_protocol.get(name) != value
        for name, value in expected_audio_protocol.items()
    )
):
    raise SystemExit(
        'enabled media decode service does not advertise T1MD protocol v1'
    )
audio_surface_export = audio_runtime.get('media_decode_surface_export', {})
expected_surface_export = {
    'mode': 'separate-layers',
    'object_layout': 'one-object-per-plane',
    'modifier_scope': 'per-object',
    'modifier_layout': 'natural-per-plane',
    'composed_fallback': False,
    'chroma_subsampling': '4:2:0',
    'bit_depths': [8, 10],
    'output_formats': ['NV12', 'P010'],
}
if (
    not isinstance(audio_surface_export, dict)
    or set(audio_surface_export) != set(expected_surface_export)
    or any(
        type(audio_surface_export.get(name)) is not type(value)
        or audio_surface_export.get(name) != value
        for name, value in expected_surface_export.items()
    )
):
    raise SystemExit(
        'enabled media decode service surface-export contract differs'
    )
if (
    audio_runtime.get('media_decode_worker')
    != '/the one/software/audio/t1-video-decode'
    or audio_runtime.get('media_decode_worker_mode') != '--t1md-worker'
):
    raise SystemExit(
        'enabled media decode service does not use the LSM-authorized '
        'compiled multicall worker'
    )
audio_watchdog = audio_runtime.get('media_decode_watchdog', {})
expected_watchdog = {
    'format': 1,
    'policy_id': 't1md-watchdog-v1',
    'header_sha256': watchdog_header_hash,
    'authority': 'supervisor',
    'clock': 'CLOCK_MONOTONIC',
    'timeout_action': 'SIGKILL',
    'idle_timeout_ms': 0,
    'starting_timeout_ms': 15000,
    'hello_timeout_ms': 30000,
    'create_timeout_ms': 15000,
    'decode_timeout_ms': 15000,
    'flush_timeout_ms': 15000,
    'reset_timeout_ms': 10000,
    'release_timeout_ms': 6000,
    'destroy_timeout_ms': 10000,
    'cleanup_timeout_ms': 10000,
    'exiting_timeout_ms': 1000,
}
if (
    not isinstance(audio_watchdog, dict)
    or set(audio_watchdog) != set(expected_watchdog)
    or any(
        type(audio_watchdog.get(name)) is not type(value)
        or audio_watchdog.get(name) != value
        for name, value in expected_watchdog.items()
    )
):
    raise SystemExit(
        'enabled media decode service watchdog manifest differs'
    )
audio_sandbox = audio_runtime.get('media_decode_sandbox', {})
expected_sandbox = {
    'required': True,
    'worker_uid': 65534,
    'worker_gid': 1000,
    'landlock_minimum_abi': 5,
    'landlock_filesystem': 'deny-by-default-all-through-ioctl-dev',
    'landlock_network': 'deny-tcp-bind-connect',
    'runtime_filesystem': 'read-only',
    'device_filesystem': 'read-write-ioctl',
    'seccomp': 'filter',
    'seccomp_tsync': True,
    'network_creation': 'denied',
    'process_creation': 'threads-only',
    'session_stdin': 'null',
    'session_stdout': 'null',
    'session_stderr': 'bounded-nonblocking-relay',
    'session_diagnostic_limit': 1048576,
    'session_exec_visible_fds': 6,
    'session_required_ipc_fds': 3,
    'session_unexpected_inherited_fds': 0,
    'rlimit_core': 0,
    'rlimit_fsize': 67108864,
    'rlimit_nofile': 256,
    'rlimit_nproc': 256,
}
if (
    not isinstance(audio_sandbox, dict)
    or any(audio_sandbox.get(name) != value
           for name, value in expected_sandbox.items())
    or any(
        type(audio_sandbox.get(name)) is not int
        for name in (
            'worker_uid',
            'worker_gid',
            'landlock_minimum_abi',
            'session_diagnostic_limit',
            'session_exec_visible_fds',
            'session_required_ipc_fds',
            'session_unexpected_inherited_fds',
            'rlimit_core',
            'rlimit_fsize',
            'rlimit_nofile',
            'rlimit_nproc',
        )
    )
    or audio_sandbox.get('required') is not True
    or audio_sandbox.get('seccomp_tsync') is not True
):
    raise SystemExit(
        'enabled media decode service sandbox manifest is incomplete'
    )

with chromium_manifest_path.open(encoding='utf-8') as stream:
    chromium = json.load(stream)
release_gn_args = [
    'target_os="linux"',
    'target_cpu="x64"',
    'is_component_build=false',
    'enable_t1os_video_decoder=true',
    'proprietary_codecs=true',
    'ffmpeg_branding="Chrome"',
    'enable_hevc_parser_and_hw_decoder=true',
    'enable_platform_hevc=true',
    'use_sysroot=true',
    'use_remoteexec=false',
    'use_siso=false',
    'is_debug=false',
    'is_official_build=true',
    'dcheck_always_on=false',
    'symbol_level=1',
    'blink_symbol_level=0',
]
source_build = chromium.get('source_build')
if (
    chromium.get('development') is not False
    or not isinstance(source_build, dict)
    or set(source_build) != {
        'profile',
        'gn_args',
        'strip_policy',
        'required_debug_sections',
        'debug_sections',
    }
    or source_build.get('profile') != 'release'
    or source_build.get('gn_args') != release_gn_args
    or source_build.get('strip_policy') != 'none'
    or source_build.get('required_debug_sections') != []
    or not isinstance(source_build.get('debug_sections'), dict)
    or set(source_build['debug_sections'])
    != {'chrome', 'chrome_crashpad_handler'}
):
    raise SystemExit(
        'production image requires the exact official release Chromium profile'
    )
capability = chromium.get('t1os_media_decoder', {})
expected = {
    'protocol': 'T1MD',
    'protocol_version': 1,
    'feature': 'T1OSVideoDecoder',
    'chromium_revision': revision,
    'descriptor_pool_size': 8,
    'protocol_header_sha256': protocol_hash,
    'source_overlay_sha256': source_hash,
    'build_marker': build_marker,
}
if (
    capability.get('available') is not True
    or capability.get('brokered_socket') is not True
    or any(capability.get(name) != value for name, value in expected.items())
):
    raise SystemExit(
        'media decode policy is enabled but Chromium is not the patched '
        'brokered T1MD runtime'
    )

required_helper_paths = {
    'program/chrome-sandbox',
    't1os-path-provider.so',
    'tools/t1os-chrome-subprocess',
    'tools/t1os-xinput',
    'tools/t1os-xwm',
}
helper_artifacts = chromium.get('t1os_helper_artifacts')
if (
    not isinstance(helper_artifacts, dict)
    or set(helper_artifacts) != required_helper_paths
):
    raise SystemExit(
        'enabled media decode policy Chromium helper inventory differs'
    )
helper_build = chromium.get('t1os_helper_build')
production_helper_flags = [
    '-O2',
    '-DNDEBUG',
    '-D_FORTIFY_SOURCE=3',
    '-fno-omit-frame-pointer',
    '-fstack-protector-strong',
    '-fstack-clash-protection',
    '-fcf-protection=full',
    '-fno-plt',
    '-fno-common',
    '-Wformat=2',
    '-Werror=format-security',
]
required_debug_sections = []
if (
    not isinstance(helper_build, dict)
    or set(helper_build) != {
        'mode',
        'compiler_flags',
        'strip_policy',
        'required_debug_sections',
        'debug_sections',
    }
    or helper_build.get('mode') != 'production'
    or helper_build.get('compiler_flags') != production_helper_flags
    or helper_build.get('strip_policy') != 'production-selective'
    or helper_build.get('required_debug_sections') != required_debug_sections
):
    raise SystemExit(
        'enabled media decode policy Chromium helpers are not an exact '
        'hardened production build'
    )
helper_debug_sections = helper_build.get('debug_sections')
if (
    not isinstance(helper_debug_sections, dict)
    or set(helper_debug_sections) != required_helper_paths
):
    raise SystemExit('Chromium helper debug-section inventory differs')
for relative in sorted(required_helper_paths):
    helper_path = chromium_root / relative
    expected_hash = helper_artifacts[relative]
    if (
        not helper_path.is_file()
        or not isinstance(expected_hash, str)
        or re.fullmatch(r'[0-9a-f]{64}', expected_hash) is None
        or hashlib.sha256(helper_path.read_bytes()).hexdigest() != expected_hash
    ):
        raise SystemExit(f'Chromium helper hash differs: {helper_path}')
    inspection = subprocess.run(
        ['readelf', '--wide', '--sections', str(helper_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if inspection.returncode != 0:
        raise SystemExit(f'Chromium helper ELF inspection failed: {helper_path}')
    actual_sections = sorted({
        match.group(2)
        for line in inspection.stdout.splitlines()
        if (
            (match := re.match(r'^\s*\[\s*(\d+)\]\s+(\S+)', line))
            and int(match.group(1)) != 0
        )
    })
    if (
        helper_debug_sections[relative] != actual_sections
    ):
        raise SystemExit(
            f'Chromium production helper section inventory differs: {helper_path}'
        )

marker = expected['build_marker'].encode('ascii')
chrome_path = chromium_manifest_path.parent / 'program' / 'chrome'
found = False
tail = b''
with chrome_path.open('rb') as stream:
    while True:
        block = stream.read(1024 * 1024)
        if not block:
            break
        candidate = tail + block
        if marker in candidate:
            found = True
            break
        tail = candidate[-(len(marker) - 1):]
if not found:
    raise SystemExit(
        'enabled media decode policy Chromium binary lacks its T1MD build marker'
    )
PY
fi
if root_selected runtime_contract; then
    rsync -a --no-whole-file $usb_rsync_metadata_options --checksum -- "$runtime_path_contract_source" "$runtime_path_contract_destination"
fi
if root_selected image_catalogue; then
    sync_protected_tree 'image catalogue' "$image_catalogue_source" "$image_catalogue_destination"
fi
if root_selected python; then
    sync_managed_python_release
fi
if root_selected resources; then
    sync_tree 'system software' "$system_software_source" "$system_software_destination"
    sync_file 'Atkinson font' "$stage/resources/fonts/atkinsonhyperlegiblenext.ttf" "$font_destination/atkinsonhyperlegiblenext.ttf"
    sync_file 'Cambria font' "$stage/resources/fonts/cambria.ttf" "$font_destination/cambria.ttf"
    sync_file 'Fira Code regular font' "$stage/resources/fonts/firacode.ttf" "$font_destination/firacode.ttf"
    sync_file 'Fira Code bold font' "$stage/resources/fonts/firacodebold.ttf" "$font_destination/firacodebold.ttf"
    sync_file 'Fira Code semibold font' "$stage/resources/fonts/firacodesemibold.ttf" "$font_destination/firacodesemibold.ttf"
    sync_file 'fatal screen artwork' "$stage/resources/system/red_screen_of_death.png" "$system_resource_destination/red_screen_of_death.png"
    sync_resource_tree 'logo resources' "$stage/resources/logos" "$logo_resource_destination"
    sync_resource_tree 'mouse cursor resources' "$stage/resources/cursors" "$cursor_resource_destination"
    if [ "$target_mode" = image ]; then
        chown 0:0 "$system_software_destination" "$system_software_destination/patchelf"
        chmod 0755 "$system_software_destination"
        chmod 0555 "$system_software_destination/patchelf"
    fi
fi
# Fonts are immutable shared display resources.  WindowServer renders managed
# client text itself, so image builds must not inherit developer-worktree mode
# bits that make a font readable only by the desktop account.
if [ "$target_mode" = image ]; then
    chown 0:0 "$font_destination"
    chmod 0755 "$font_destination"
    for runtime_font in atkinsonhyperlegiblenext.ttf cambria.ttf firacode.ttf firacodebold.ttf firacodesemibold.ttf; do
        chown 0:0 "$font_destination/$runtime_font"
        chmod 0444 "$font_destination/$runtime_font"
    done
fi
# Make every completed write visible and durable before content verification.
# This is particularly important on physical DrvFS targets, where an atomic
# rsync replacement can otherwise be observed through a stale cached handle.
sync -f "$mount_point"
if root_selected build || root_selected boot || root_selected virtualbox_software || root_selected image_catalogue || root_selected python; then
    protect_managed_python_release
fi
if [ "$exhaustive_verify" = True ]; then
    verify_protected_tree 'build' "$stage/build" "$build_destination"
    verify_python_software_tree 'boot' "$boot_source" "$boot_destination"
    driver_differences=$(rsync -a --no-whole-file --no-perms --no-owner --no-group \
        --no-times --omit-dir-times --checksum --delete \
        --filter='protect /firmware/***' \
        --filter='protect /modules*/***' \
        --filter='protect /.t1os-modules-update-*/***' \
        --filter='protect /nodes/***' \
        --filter='protect /processes/***' \
        --filter='protect /state/***' \
        --itemize-changes --dry-run -- "$drivers_source"/ "$drivers_destination"/)
    if [ -n "$driver_differences" ]; then
        echo 'driver runtime verification found remaining differences:' >&2
        printf '%s\n' "$driver_differences" >&2
        exit 1
    fi
    verify_tree 'graphics catalogue' "$graphics_catalogue_source" "$graphics_catalogue_destination"
    verify_virtualbox_catalogue 'VirtualBox catalogue' "$virtualbox_catalogue_source" "$virtualbox_catalogue_destination"
    verify_python_software_tree 'VirtualBox software' "$virtualbox_software_source" "$virtualbox_software_destination"
    verify_tree 'VirtualBox settings' "$virtualbox_settings_source" "$virtualbox_settings_destination"
    verify_tree 'audio catalogue' "$audio_catalogue_source" "$audio_catalogue_destination"
    verify_tree_without_permissions 'audio software' "$audio_software_source" "$audio_software_destination"
    verify_tree 'network catalogue' "$network_catalogue_source" "$network_catalogue_destination"
    verify_tree_without_permissions 'network software' "$network_software_source" "$network_software_destination"
    cmp -s -- "$network_settings_source/cacerts.pem" "$network_settings_destination/cacerts.pem"
    test -s "$network_settings_destination/network.txt"
    if [ -f "$network_settings_source/wireless.txt" ]; then
        cmp -s -- "$network_settings_source/wireless.txt" "$network_settings_destination/wireless.txt"
    fi
    test -s "$media_settings_destination/video decode service.json"
    verify_tree_without_permissions 'Chromium software' "$chromium_software_source" "$chromium_software_destination"
    cmp -s -- "$runtime_path_contract_source" "$runtime_path_contract_destination"
    verify_protected_tree 'image catalogue' "$image_catalogue_source" "$image_catalogue_destination"
    verify_managed_python_release
    verify_tree_without_permissions 'system software' "$system_software_source" "$system_software_destination"
    readelf -h "$system_software_destination/patchelf" >/dev/null
    if [ "$target_mode" = image ]; then
        [ -x "$system_software_destination/patchelf" ]
    fi
    for runtime_font in atkinsonhyperlegiblenext.ttf cambria.ttf firacode.ttf firacodebold.ttf firacodesemibold.ttf; do
        cmp -s -- "$stage/resources/fonts/$runtime_font" "$font_destination/$runtime_font" || {
            echo "Runtime font verification found a remaining difference: $runtime_font" >&2
            exit 1
        }
        if [ "$target_mode" = image ]; then
            [ "$(stat -c '%u:%g:%a' "$font_destination/$runtime_font")" = '0:0:444' ] || {
                echo "Runtime font permissions are unsafe: $runtime_font" >&2
                exit 1
            }
        fi
    done
    cmp -s -- "$stage/resources/system/red_screen_of_death.png" "$system_resource_destination/red_screen_of_death.png" || {
        echo 'Fatal screen artwork verification found a remaining difference.' >&2
        exit 1
    }
    verify_resource_tree 'logo resources' "$stage/resources/logos" "$logo_resource_destination"
    verify_resource_tree 'mouse cursor resources' "$stage/resources/cursors" "$cursor_resource_destination"
    rm -rf -- \
        "$mount_point/the one/resources/expanse" \
        "$mount_point/the one/resources/graphics/mouse cursors"
    rmdir -- "$mount_point/the one/resources/graphics" 2>/dev/null || true
fi

if root_selected build || [ "$exhaustive_verify" = True ]; then
unexpected_build_files=$(find "$build_destination" -type f \
    ! -name '*.py' \
    ! -path "$build_destination/chromium/hardware diagnostics.json" \
    ! -path "$build_destination/chromium/google api credentials.example.json" \
    ! -path "$build_destination/chromium/google api credentials.json" \
    ! -path "$build_destination/python/tools.json" \
    ! -path "$build_destination/python/pip-*.whl" \
    ! -path "$build_destination/python/python-command" \
    -print)
if [ -n "$unexpected_build_files" ]; then
    echo 'The deployed build contains an unexpected non-Python file:' >&2
    printf '%s\n' "$unexpected_build_files" >&2
    exit 1
fi
fi

if root_selected graphics || root_selected virtualbox_catalogue || root_selected audio_catalogue || root_selected network_catalogue || [ "$exhaustive_verify" = True ]; then
    validate_catalogue
fi

if root_selected virtualbox_catalogue && [ -d "$virtualbox_catalogue_destination" ] && ! find "$virtualbox_catalogue_destination" -mindepth 1 -print -quit | grep -q .; then
    rmdir "$virtualbox_catalogue_destination"
fi

if [ "$exhaustive_verify" = True ]; then
printf 'build files on disk: '
find "$build_destination" -type f | wc -l
printf 'boot files on disk: '
find "$boot_destination" -type f | wc -l
printf 'driver runtime files on disk: '
find "$drivers_destination" -type f | wc -l
printf 'graphics catalogue files on disk: '
find "$graphics_catalogue_destination" -type f | wc -l
printf 'VirtualBox catalogue files on disk: '
if [ -d "$virtualbox_catalogue_destination" ]; then find "$virtualbox_catalogue_destination" -type f | wc -l; else echo 0; fi
printf 'VirtualBox software files on disk: '
find "$virtualbox_software_destination" -type f | wc -l
printf 'VirtualBox settings files on disk: '
find "$virtualbox_settings_destination" -type f | wc -l
printf 'audio catalogue files on disk: '
find "$audio_catalogue_destination" -type f | wc -l
printf 'audio software files on disk: '
find "$audio_software_destination" -type f | wc -l
printf 'network catalogue files on disk: '
find "$network_catalogue_destination" -type f | wc -l
printf 'network software files on disk: '
find "$network_software_destination" -type f | wc -l
    printf 'network settings files on disk: '
    find "$network_settings_destination" -type f | wc -l
    printf 'media settings files on disk: '
    find "$media_settings_destination" -type f | wc -l
printf 'Chromium software files on disk: '
find "$chromium_software_destination" -type f | wc -l
printf 'image catalogue files on disk: '
find "$image_catalogue_destination" -type f | wc -l
printf 'managed Python software files on disk: '
find "$python_software_destination" -type f | wc -l
printf 'managed Python catalogue files on disk: '
find "$python_catalogue_destination" -type f | wc -l
printf 'system software files on disk: '
find "$system_software_destination" -type f | wc -l
printf 'runtime resource files on disk: '
find "$font_destination" "$logo_resource_destination" "$cursor_resource_destination" "$system_resource_destination" -type f | wc -l
printf 'Atkinson Hyperlegible Next SHA-256: '
sha256sum "$font_destination/atkinsonhyperlegiblenext.ttf" | awk '{print $1}'
fi
'@

    Write-Host 'Synchronising only new, changed, and removed files...'
    # Keep the complete push program inside WSL instead of staging a shell file
    # in Windows temporary storage. Normalize CRLF before streaming; the final
    # comment sentinel safely absorbs the native pipeline's appended line ending.
    $normalizedCopyCommand = $copyCommand.Replace("`r", '') + "`n# end"
    $copyExitCode = 1
    $targetMode = if ($UsbDrive) { 'drive' } else { 'image' }
    $preflightOnly = if ($ValidateManagedTreeOnly) { 'True' } else { 'False' }
    $managedVerifyOnly = if ($VerifyManagedReleaseOnly) { 'True' } else { 'False' }
    $managedSyncOnly = if ($SyncManagedReleaseOnly) { 'True' } else { 'False' }
    $selectedRootArgument = $selectedManagedRoots -join ','
    $exhaustiveVerifyArgument = if ($fullTargetVerification) { 'True' } else { 'False' }
    $skipChromiumEngineArgument = if (
        $unchangedLargeFiles -contains 'chromium|source/software/chromium/program/chrome'
    ) { 'True' } else { 'False' }
    $readOnlyReplacementTargets = @()
    if (
        $UsbDrive -and
        -not ($ValidateManagedTreeOnly -or $VerifyManagedReleaseOnly) -and
        @($selectedManagedRoots | Where-Object {
            $_ -in @('python', 'image_catalogue', 'build', 'boot', 'virtualbox_software')
        }).Count -gt 0
    ) {
        # Linux mode bits on an offline T1OS target are not an authorization boundary.
        # DrvFS nevertheless maps NTFS's DOS read-only attribute to a replacement
        # denial. Snapshot only files inside the six manifest-bound release roots,
        # clear that attribute for the atomic rsync window, and restore it below.
        $replacementRoots = @(
            (Join-Path $usbTarget.Root 'the one\software\python'),
            (Join-Path $usbTarget.Root 'the one\catalogue\python'),
            (Join-Path $usbTarget.Root 'the one\catalogue\image'),
            (Join-Path $usbTarget.Root 'the one\build'),
            (Join-Path $usbTarget.Root 'boot'),
            (Join-Path $usbTarget.Root 'the one\software\virtualbox')
        )
        $readOnlyReplacementTargets = @(
            foreach ($replacementRoot in $replacementRoots) {
                if (Test-Path -LiteralPath $replacementRoot -PathType Container) {
                    Get-ChildItem -LiteralPath $replacementRoot -Recurse -File -Force |
                        Where-Object { $_.IsReadOnly } |
                        ForEach-Object { $_.FullName }
                }
            }
        )
        foreach ($readOnlyTarget in $readOnlyReplacementTargets) {
            $targetItem = Get-Item -LiteralPath $readOnlyTarget -Force
            $targetItem.IsReadOnly = $false
            if ((Get-Item -LiteralPath $readOnlyTarget -Force).IsReadOnly) {
                throw "Could not clear the protected release read-only attribute: $readOnlyTarget"
            }
        }
    }
    try {
        $preparationStopwatch.Stop()
        $copyStopwatch = [Diagnostics.Stopwatch]::StartNew()
        $normalizedCopyCommand |
            & wsl.exe -u root --exec bash -s -- $mountPoint $buildDestination $bootDestination $graphicsCatalogueDestination $virtualBoxCatalogueDestination $virtualBoxSoftwareDestination $audioCatalogueDestination $audioSoftwareDestination $wslBuildSource $wslBootSource $wslGraphicsCatalogueSource $wslVirtualBoxCatalogueSource $wslVirtualBoxSoftwareSource $wslAudioCatalogueSource $wslAudioSoftwareSource $imageCatalogueDestination $wslImageCatalogueSource $wslImagePath $virtualBoxSettingsDestination $wslVirtualBoxSettingsSource $fontDestination $driversDestination $wslDriversSource $networkCatalogueDestination $networkSoftwareDestination $networkSettingsDestination $chromiumSoftwareDestination $runtimePathContractDestination $wslNetworkCatalogueSource $wslNetworkSoftwareSource $wslNetworkSettingsSource $wslChromiumSoftwareSource $wslRuntimePathContractSource $wslResourceSource $targetMode $wslMediaSettingsSource $mediaSettingsDestination $wslNativeProtocolHeader $wslNativeWatchdogHeader $wslChromiumProtocolHeader $wslChromiumSourceManifest $pythonSoftwareDestination $pythonCatalogueDestination $wslPythonSoftwareSource $wslPythonCatalogueSource $expectedPythonRelease $expectedPythonManifestSha256 $preflightOnly $managedVerifyOnly $managedSyncOnly $wslPythonRuntimeConfigSource $wslBootPolicyManifest $selectedRootArgument $exhaustiveVerifyArgument $skipChromiumEngineArgument
        $copyExitCode = $LASTEXITCODE
        $copyStopwatch.Stop()
        if ($copyExitCode -ne 0) {
            $targetName = if ($UsbDrive) { 'T1OS USB drive' } else { 'disk' }
            throw "The files could not be pushed to the $targetName (exit code $copyExitCode)."
        }
    }
    finally {
        foreach ($readOnlyTarget in $readOnlyReplacementTargets) {
            if (Test-Path -LiteralPath $readOnlyTarget -PathType Leaf) {
                (Get-Item -LiteralPath $readOnlyTarget -Force).IsReadOnly = $true
            }
        }
    }

    if ($ValidateManagedTreeOnly) {
        Write-Host 'Managed T1OS USB tree structural validation passed; no files were changed.'
        return
    }
    if ($VerifyManagedReleaseOnly) {
        Write-Host 'Managed T1OS USB release content verification passed; no files were changed.'
        return
    }
    if ($SyncManagedReleaseOnly) {
        Write-Host 'Managed T1OS release roots were synchronized and verified.'
        return
    }

    if ($UsbDrive) {
        $updatedVolume = Get-Volume -DriveLetter $usbTarget.DriveLetter -ErrorAction Stop
        if (
            [string]$updatedVolume.FileSystemType -cne 'NTFS' -or
            [string]$updatedVolume.HealthStatus -cne 'Healthy' -or
            -not ([string]$updatedVolume.FileSystemLabel).StartsWith(
                'T1OS',
                [StringComparison]::OrdinalIgnoreCase
            )
        ) {
            throw 'The T1OS USB drive did not remain a healthy, labelled NTFS volume after the push.'
        }
    }
    else {
        Assert-T1OSFilesystemHealthy -ImagePath $imagePath -Operation 'accepting the completed push'
    }
    $completedTargetIdentity = if ($UsbDrive) {
        $targetIdentity
    }
    else {
        $completedImageItem = Get-Item -LiteralPath $imagePath -Force
        'image|{0}|{1}|{2}' -f @(
            $completedImageItem.FullName,
            $completedImageItem.Length,
            $completedImageItem.LastWriteTimeUtc.Ticks
        )
    }
    Write-T1OSDeploymentState `
        -Path $deploymentStatePath `
        -SourceState $deploymentSourceState `
        -TargetIdentity $completedTargetIdentity `
        -FullVerification $fullTargetVerification `
        -PreviousState $previousDeploymentState
    Write-Host 'Build software, boot files, the managed Python release, drivers, graphics, VirtualBox, audio, network, Chromium, media policy, image catalogue, managed settings, fonts, logos, and mouse cursors were incrementally synchronised successfully.'
}
catch {
    $operationError = $_
}

if ($operationError) {
    throw $operationError
}

if ($UsbDrive) {
    Write-Host "Push to drive completed. $($usbTarget.DriveLetter): remains available in Windows."
}
else {
    Write-Host 'Push to disk completed and the disk is unmounted.'
}
$deploymentStopwatch.Stop()
Write-Host ("Deployment timing: target validation {0:N2}s; source inventory {1:N2}s; preparation {2:N2}s; target sync {3:N2}s; total {4:N2}s." -f `
    $targetDiscoveryStopwatch.Elapsed.TotalSeconds,
    $sourceStateStopwatch.Elapsed.TotalSeconds,
    $preparationStopwatch.Elapsed.TotalSeconds,
    $copyStopwatch.Elapsed.TotalSeconds,
    $deploymentStopwatch.Elapsed.TotalSeconds)
exit 0
