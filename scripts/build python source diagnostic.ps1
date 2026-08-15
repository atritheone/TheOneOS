[CmdletBinding()]
param(
    [switch]$Offline
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$builder = Join-Path $projectRoot 'development\build python source diagnostic.py'

if (-not (Test-Path -LiteralPath $builder -PathType Leaf)) {
    throw "Python source diagnostic builder not found: $builder"
}
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Required command not found: wsl.exe'
}

$wslBuilder = (& wsl.exe -d Ubuntu --exec wslpath -a $builder | Select-Object -First 1).Trim()
if ([string]::IsNullOrWhiteSpace($wslBuilder)) {
    throw "Could not translate the source diagnostic builder path: $builder"
}

$arguments = @($wslBuilder)
if ($Offline) {
    $arguments += '--offline'
}

& wsl.exe -d Ubuntu --exec python3 -B @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Python source diagnostic failed (exit code $LASTEXITCODE)."
}

Write-Host 'The non-promotable CPython source diagnostic completed successfully.'
Write-Host (Join-Path $projectRoot 'development\python source diagnostic\source-rebuild-report.json')
