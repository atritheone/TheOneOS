[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$validator = Join-Path $PSScriptRoot 'validate profiled python entrypoints.py'

if (-not (Test-Path -LiteralPath $validator -PathType Leaf)) {
    throw "Profiled Python validator not found: $validator"
}
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Required command not found: wsl.exe'
}

$wslValidator = (& wsl.exe -d Ubuntu --exec wslpath -a $validator |
    Select-Object -First 1).Trim()
$wslProjectRoot = (& wsl.exe -d Ubuntu --exec wslpath -a $projectRoot |
    Select-Object -First 1).Trim()
if ([string]::IsNullOrWhiteSpace($wslValidator) -or
    [string]::IsNullOrWhiteSpace($wslProjectRoot)) {
    throw 'Could not translate the profiled Python validation paths for WSL.'
}

& wsl.exe -d Ubuntu --exec python3 -B $wslValidator --repo $wslProjectRoot --policy-only
if ($LASTEXITCODE -ne 0) {
    throw "Profiled Python validation failed (exit code $LASTEXITCODE)."
}
