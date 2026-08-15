[CmdletBinding()]
param(
    [switch]$Offline
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$builder = Join-Path $projectRoot 'development\build python 3.14 candidate.py'

if (-not (Test-Path -LiteralPath $builder -PathType Leaf)) {
    throw "Python 3.14 candidate builder not found: $builder"
}
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Required command not found: wsl.exe'
}

$wslBuilder = (& wsl.exe -d Ubuntu --exec wslpath -a $builder | Select-Object -First 1).Trim()
if ([string]::IsNullOrWhiteSpace($wslBuilder)) {
    throw "Could not translate the Python 3.14 candidate builder path: $builder"
}

$arguments = @($wslBuilder)
if ($Offline) {
    $arguments += '--offline'
}

& wsl.exe -d Ubuntu --exec python3 -B @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.14 candidate build failed (exit code $LASTEXITCODE)."
}

Write-Host 'The non-promoted T1OS Python 3.14 candidate completed successfully.'
Write-Host (Join-Path $projectRoot 'development\python 3.14 candidate\candidate-report.json')
