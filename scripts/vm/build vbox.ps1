[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$buildScript = Join-Path $PSScriptRoot 'build and run vbox.ps1'

if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    throw "virtualbox build script not found: $buildScript"
}

Write-Host 'building the t1os virtualbox vm...'
& pwsh -NoLogo -NoProfile -NonInteractive -File $buildScript -BuildOnly
exit $LASTEXITCODE
