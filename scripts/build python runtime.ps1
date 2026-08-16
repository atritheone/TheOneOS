[CmdletBinding()]
param(
    [switch]$Offline,
    [switch]$Rebuild,
    [switch]$StageOnly,
    [switch]$Promote
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
if ($StageOnly -and $Promote) {
    throw '-StageOnly and -Promote are mutually exclusive.'
}

$wslPromoter = (& wsl.exe -d Ubuntu --exec wslpath -a $promoter |
    Select-Object -First 1).Trim()
if ([string]::IsNullOrWhiteSpace($wslPromoter)) {
    throw "Could not translate Python 3.14 promoter path: $promoter"
}

# The default operation is deliberately read-only. Generic build and deploy
# workflows may call this command as a gate, but only an explicit Python
# rebuild, stage, or promotion request may construct a candidate.
if (-not ($Rebuild -or $StageOnly -or $Promote)) {
    & wsl.exe -d Ubuntu --exec python3 -B $wslPromoter verify
    if ($LASTEXITCODE -ne 0) {
        throw (
            'The existing Python production release failed verification. ' +
            'It was not rebuilt automatically; repair its payload or request ' +
            '-Rebuild/-Promote explicitly.'
        )
    }
    Write-Host 'T1OS Python production is unchanged and verified; no candidate was built.'
    exit 0
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

# -Rebuild preserves the established explicit rebuild-and-promote operation.
# -Promote supports promotion of an already-built candidate without rebuilding
# CPython. Neither path can be entered accidentally by the default invocation.
& wsl.exe -d Ubuntu --exec python3 -B $wslPromoter promote
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.14.7 promotion failed (exit code $LASTEXITCODE)."
}

Write-Host 'T1OS Python 3.14.7 is the canonical verified production runtime.'
Write-Host (Join-Path $projectRoot 'source\software\python')
Write-Host (Join-Path $projectRoot 'source\catalogue\python')
