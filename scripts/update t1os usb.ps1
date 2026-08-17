[CmdletBinding()]
param(
    [switch]$Prepare,
    [switch]$IncludeBoot,
    [switch]$ValidateOnly,
    [switch]$Full
)

$ErrorActionPreference = 'Stop'
$targetValidator = Join-Path $PSScriptRoot 'push to disk.ps1'
$aclPreparer = Join-Path $PSScriptRoot 'migrate managed python usb acl.ps1'
$bootUpdater = Join-Path $PSScriptRoot 'push hardware kernel to usb.ps1'

foreach ($required in @($targetValidator, $aclPreparer, $bootUpdater)) {
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
    Write-Host 'Updating the kernel, initramfs, EFI boot files, and modules...'
    & $bootUpdater -Confirm:$false
    if ($LASTEXITCODE -ne 0) {
        throw "T1OS USB boot update failed (exit code $LASTEXITCODE)."
    }
}

if ($Full) {
    Write-Host 'Running the exhaustive managed userspace synchronization...'
    & $targetValidator -UsbDrive -Full
}
else {
    Write-Host 'Planning the incremental managed userspace update...'
    & $targetValidator -UsbDrive -Fast
}
if ($LASTEXITCODE -ne 0) {
    throw "T1OS USB userspace update failed (exit code $LASTEXITCODE)."
}
Write-Host 'T1OS USB update completed and verified.'
