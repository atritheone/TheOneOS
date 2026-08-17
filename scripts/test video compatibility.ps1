[CmdletBinding()]
param()

$incrementalTestBootstrap = Join-Path $PSScriptRoot 'incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$testPath = Join-Path $PSScriptRoot 'test video compatibility.py'

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'WSL is required to test the video hardware contract safely.'
}
if (-not (Test-Path -LiteralPath $testPath -PathType Leaf)) {
    throw "Video compatibility test was not found: $testPath"
}

$wslPathOutput = & wsl.exe -d Ubuntu --exec wslpath -a $testPath
$wslPathExitCode = $LASTEXITCODE
$wslTestPath = ($wslPathOutput | Select-Object -First 1).Trim()
if ($wslPathExitCode -ne 0 -or -not $wslTestPath) {
    throw "Could not translate the video compatibility test path for WSL: $testPath"
}

& wsl.exe -d Ubuntu --exec python3 -B $wslTestPath

if ($LASTEXITCODE -ne 0) {
    throw "Video hardware compatibility failed with exit code $LASTEXITCODE."
}

Write-Host 'Video hardware compatibility passed.'
