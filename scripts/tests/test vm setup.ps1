[CmdletBinding()]
param(
    [ValidateSet('All', 'VirtualBox', 'VMware')]
    [string]$Platform = 'All'
)

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$targets = if ($Platform -eq 'All') {
    @('VirtualBox', 'VMware')
}
else {
    @($Platform)
}

foreach ($target in $targets) {
    $runScript = if ($target -eq 'VirtualBox') {
        Join-Path $PSScriptRoot '..\vm\run vbox.ps1'
    }
    else {
        Join-Path $PSScriptRoot '..\vm\run vmware.ps1'
    }

    Write-Host "validating the $target VM setup..."
    & pwsh -NoLogo -NoProfile -NonInteractive -File $runScript -ValidateOnly
    if ($LASTEXITCODE -ne 0) {
        throw "$target VM setup validation failed with exit code $LASTEXITCODE."
    }
}

Write-Host 'all requested T1OS VM setups are ready.'
exit 0
