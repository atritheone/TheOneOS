[CmdletBinding()]
param(
    [switch]$IncludeUsbImage
)

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}

$ErrorActionPreference = 'Stop'
$caseRoot = Join-Path $PSScriptRoot 'hardware'
$cases = @(
    'syntax.ps1',
    'usb and provenance.ps1',
    'graphics and angel.ps1',
    'init and desktop contracts.ps1',
    'roothealth contracts.ps1',
    'desktop runtime contracts.ps1',
    'driver and boot contracts.ps1',
    'kernel policy contracts.ps1',
    'python component contracts.ps1',
    'network and driver diagnostics.ps1',
    'linux artifact contracts.ps1'
)

foreach ($case in $cases) {
    $casePath = Join-Path $caseRoot $case
    if (-not (Test-Path -LiteralPath $casePath -PathType Leaf)) {
        throw "Required hardware validation case not found: $casePath"
    }
    & pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $casePath
    if ($LASTEXITCODE -ne 0) {
        throw "Hardware validation case failed: $case"
    }
}

if ($IncludeUsbImage) {
    & pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (
        Join-Path $PSScriptRoot '..\validate hardware usb image.ps1'
    )
    if ($LASTEXITCODE -ne 0) {
        throw 'Hardware USB image validation failed.'
    }
}

Write-Host 'T1OS hardware build validation passed.'
