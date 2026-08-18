[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$buildScript = Join-Path $PSScriptRoot 'build and run vmware.ps1'

if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    throw "vmware build script not found: $buildScript"
}

Write-Host 'building the t1os vmware vm...'
& pwsh -NoLogo -NoProfile -NonInteractive -File $buildScript -BuildOnly -ForceConvert
exit $LASTEXITCODE
