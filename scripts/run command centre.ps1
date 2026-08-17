[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$commandCentreRoot = Join-Path $projectRoot 'software\command centre'
Set-Location -LiteralPath $commandCentreRoot

if (-not (Test-Path -LiteralPath (Join-Path $commandCentreRoot 'node_modules') -PathType Container)) {
    Write-Host 'installing command centre dependencies...'
    & npm install
    if ($LASTEXITCODE -ne 0) {
        throw "npm install failed with exit code $LASTEXITCODE."
    }
}

Write-Host 'starting the one os command centre...'
& npm start
exit $LASTEXITCODE
