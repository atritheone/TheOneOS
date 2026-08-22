[CmdletBinding()]
param(
    [switch]$Prepare,
    [switch]$IncludeBoot,
    [switch]$ValidateOnly,
    [switch]$Full
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$targetValidator = Join-Path $PSScriptRoot 'push to disk.ps1'
$aclPreparer = Join-Path $PSScriptRoot 'migrate managed python usb acl.ps1'
$bootUpdater = Join-Path $PSScriptRoot 'push hardware kernel to usb.ps1'
$kernelBuilder = Join-Path $projectRoot 'scripts\build\build hardware kernel.ps1'
$initramfsBuilder = Join-Path $projectRoot 'scripts\build\build hardware initramfs.ps1'
$systemPatchelf = Join-Path $projectRoot 'source\software\system\patchelf'

foreach ($required in @(
    $targetValidator,
    $aclPreparer,
    $bootUpdater,
    $kernelBuilder,
    $initramfsBuilder,
    $systemPatchelf
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required T1OS USB update component is missing: $required"
    }
}

if ($ValidateOnly -and ($Prepare -or $IncludeBoot -or $Full)) {
    throw '-ValidateOnly cannot be combined with an update or maintenance action.'
}

if ($ValidateOnly) {
    & $targetValidator -UsbDrive -ValidateTargetOnly
    if ($LASTEXITCODE -ne 0) {
        throw "T1OS USB target validation failed (exit code $LASTEXITCODE)."
    }
    Write-Host 'The T1OS USB target is valid; no files were changed.'
    exit 0
}

if ($Prepare -or $IncludeBoot) {
    # These are separate maintenance programs, so validate the physical target
    # before either is allowed to run. The normal userspace path below enters
    # the deployment engine directly and therefore performs discovery once.
    & $targetValidator -UsbDrive -ValidateTargetOnly
    if ($LASTEXITCODE -ne 0) {
        throw "T1OS USB target validation failed (exit code $LASTEXITCODE)."
    }
}

if ($Prepare) {
    Write-Host 'Preparing the one-time Windows maintenance ACL...'
    & $aclPreparer
    if ($LASTEXITCODE -ne 0) {
        throw "T1OS USB maintenance preparation failed (exit code $LASTEXITCODE)."
    }
}

if ($IncludeBoot) {
    # A complete update is source-driven. Rebuild both boot artifacts here so
    # a byte-identical but stale local artifact can never be mistaken for the
    # latest kernel/initramfs merely because it already matches the USB.
    Write-Host 'Rebuilding the hardware kernel and matching module archive...'
    & $kernelBuilder -Resume
    if ($LASTEXITCODE -ne 0) {
        throw "T1OS hardware kernel rebuild failed (exit code $LASTEXITCODE)."
    }
    Write-Host 'Rebuilding the hardware initramfs from the current boot sources...'
    & $initramfsBuilder
    if ($LASTEXITCODE -ne 0) {
        throw "T1OS hardware initramfs rebuild failed (exit code $LASTEXITCODE)."
    }
    Write-Host 'Updating the rebuilt kernel, initramfs, EFI boot files, and modules...'
    & $bootUpdater -Confirm:$false
    if ($LASTEXITCODE -ne 0) {
        throw "T1OS USB boot update failed (exit code $LASTEXITCODE)."
    }
}

if ($Full) {
    Write-Host 'Running the exhaustive managed userspace and system-software synchronization...'
    & $targetValidator -UsbDrive -Full
}
else {
    Write-Host 'Planning the incremental managed userspace and system-software update...'
    & $targetValidator -UsbDrive -Fast
}
if ($LASTEXITCODE -ne 0) {
    throw "T1OS USB userspace update failed (exit code $LASTEXITCODE)."
}
Write-Host 'T1OS USB update completed and verified.'
