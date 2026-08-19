[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('build', 'test', 'package')]
    [string]$Phase,

    [switch]$TraceSignals
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$builder = Join-Path $projectRoot 'development\build chromium source.py'
$stateRoot = Join-Path $projectRoot 'development\chromium release'
$lockPath = Join-Path $stateRoot 'chromium-release-build.lock'
$lock = $null

New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
try {
    $lock = [System.IO.File]::Open(
        $lockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
    $wslBuilder = (& wsl.exe -d Ubuntu --exec wslpath -a $builder).Trim()
    if (-not $wslBuilder.StartsWith('/mnt/')) {
        throw "Unexpected WSL builder path: $wslBuilder"
    }
    $builderArguments = @(
        $wslBuilder, $Phase,
        '--profile', 'release',
        '--source', '/home/edward/t1os-chromium/src',
        '--stage', '/home/edward/t1os-chromium/t1os-runtime-release'
    )
    if ($TraceSignals) {
        $tracePath = Join-Path $stateRoot 'chromium-source-signal.trace'
        $wslTracePath = (& wsl.exe -d Ubuntu --exec wslpath -a $tracePath).Trim()
        & wsl.exe -d Ubuntu --exec strace -e trace=signal -o $wslTracePath `
            python3 @builderArguments
    }
    else {
        & wsl.exe -d Ubuntu --exec python3 @builderArguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Chromium source phase '$Phase' exited with code $LASTEXITCODE."
    }
}
finally {
    if ($null -ne $lock) {
        $lock.Dispose()
    }
}
