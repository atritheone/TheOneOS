[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$packager = Join-Path $projectRoot 'development\package python 3.14 candidate.py'

if (-not (Test-Path -LiteralPath $packager -PathType Leaf)) {
    throw "Python 3.14 candidate packager not found: $packager"
}
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Required command not found: wsl.exe'
}

$wslPackager = (& wsl.exe -d Ubuntu --exec wslpath -a $packager | Select-Object -First 1).Trim()
if ([string]::IsNullOrWhiteSpace($wslPackager)) {
    throw "Could not translate Python 3.14 packager path: $packager"
}

& wsl.exe -d Ubuntu --exec python3 -B $wslPackager
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.14 candidate packaging failed (exit code $LASTEXITCODE)."
}

Write-Host 'The T1OS Python 3.14 candidate payload completed successfully.'
Write-Host (Join-Path $projectRoot 'development\python 3.14 candidate\t1os\manifest.json')
