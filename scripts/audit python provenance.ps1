[CmdletBinding()]
param(
    [switch]$Offline
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$builder = Join-Path $projectRoot 'development\build python runtime.py'

if (-not (Test-Path -LiteralPath $builder -PathType Leaf)) {
    throw "Python runtime builder not found: $builder"
}
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Required command not found: wsl.exe'
}

$wslBuilder = (& wsl.exe -d Ubuntu --exec wslpath -a $builder | Select-Object -First 1).Trim()
if ([string]::IsNullOrWhiteSpace($wslBuilder)) {
    throw "Could not translate the Python runtime builder path for WSL: $builder"
}

$arguments = @($wslBuilder, 'audit', '--write')
if ($Offline) {
    $arguments += '--offline'
}

& wsl.exe -d Ubuntu --exec python3 @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Python provenance audit failed (exit code $LASTEXITCODE)."
}

Write-Host 'T1OS Python phase-0 provenance audit passed.'
Write-Host (Join-Path $projectRoot 'source\python\provenance\legacy-evidence.json')
