[CmdletBinding()]
param(
    [ValidateSet('All', 'VirtualBox', 'VMware')]
    [string]$Platform = 'All'
)

$ErrorActionPreference = 'Stop'
$targets = if ($Platform -eq 'All') {
    @('VirtualBox', 'VMware')
}
else {
    @($Platform)
}

foreach ($target in $targets) {
    $runScript = if ($target -eq 'VirtualBox') {
        Join-Path $PSScriptRoot 'run vbox.ps1'
    }
    else {
        Join-Path $PSScriptRoot 'run vmware.ps1'
    }

    Write-Host "validating the $target VM setup..."
    & pwsh -NoLogo -NoProfile -NonInteractive -File $runScript -ValidateOnly
    if ($LASTEXITCODE -ne 0) {
        throw "$target VM setup validation failed with exit code $LASTEXITCODE."
    }
}

Write-Host 'all requested T1OS VM setups are ready.'
exit 0
