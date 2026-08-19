$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$buildScript = Join-Path $projectRoot 'scripts\build\build chromium runtime.ps1'
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
    & $buildScript -Profile release -OptimizedHelpers
}
finally {
    if ($null -ne $lock) {
        $lock.Dispose()
    }
}
