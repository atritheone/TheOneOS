[CmdletBinding()]
param(
    [switch]$Offline,
    [switch]$Rebuild,
    [switch]$StageOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$candidateBuilder = Join-Path $PSScriptRoot 'build python 3.14 candidate.ps1'
$candidatePackager = Join-Path $PSScriptRoot 'package python 3.14 candidate.ps1'
$promoter = Join-Path $projectRoot 'development\promote python 3.14 runtime.py'

foreach ($required in @($candidateBuilder, $candidatePackager, $promoter)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Canonical Python 3.14 build input not found: $required"
    }
}
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Required command not found: wsl.exe'
}

if ($Rebuild) {
    $arguments = @()
    if ($Offline) {
        $arguments += '-Offline'
    }
    & $candidateBuilder @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.14.7 source build failed (exit code $LASTEXITCODE)."
    }
}

& $candidatePackager
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.14.7 packaging failed (exit code $LASTEXITCODE)."
}

if ($StageOnly) {
    Write-Host 'T1OS Python 3.14.7 was verified and packaged without promotion.'
    exit 0
}

$wslPromoter = (& wsl.exe -d Ubuntu --exec wslpath -a $promoter |
    Select-Object -First 1).Trim()
if ([string]::IsNullOrWhiteSpace($wslPromoter)) {
    throw "Could not translate Python 3.14 promoter path: $promoter"
}
& wsl.exe -d Ubuntu --exec python3 -B $wslPromoter promote
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.14.7 promotion failed (exit code $LASTEXITCODE)."
}

Write-Host 'T1OS Python 3.14.7 is the canonical verified production runtime.'
Write-Host (Join-Path $projectRoot 'source\software\python')
Write-Host (Join-Path $projectRoot 'source\catalogue\python')
