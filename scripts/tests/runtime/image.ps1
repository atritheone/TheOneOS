[CmdletBinding()]
param()

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$environmentRoot = Join-Path $projectRoot 'environment'
. (Join-Path $projectRoot 'scripts\common.ps1')
Set-Location -LiteralPath $environmentRoot

function Invoke-ImageDiagnostic {

    $mountScript = Join-Path $projectRoot 'scripts/mount.ps1'
    $unmountScript = Join-Path $projectRoot 'scripts/unmount.ps1'
    $buildSource = Join-Path $projectRoot 'source\build software'
    $catalogueSource = Join-Path $projectRoot 'source\catalogue\image'
    $mountPoint = '/mnt/t1fs'
    $buildTarget = '/mnt/t1fs/the one/build'
    $catalogueTarget = '/mnt/t1fs/the one/catalogue/image'
    $diskMounted = $false
    $buildMounted = $false
    $catalogueMounted = $false
    $cleanupError = $null

    foreach ($requiredPath in @($buildSource, $catalogueSource)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Container)) {
            throw "image diagnostic source directory not found: $requiredPath"
        }
    }

    try {
        Write-Host 'mounting the T1OS image for image diagnostics...'
        & pwsh -NoLogo -NoProfile -NonInteractive -File $mountScript | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "mount failed with exit code $LASTEXITCODE."
        }
        $diskMounted = $true

        $wslSources = @()
        foreach ($source in @($buildSource, $catalogueSource)) {
            $translated = & wsl.exe --exec wslpath -a $source
            if ($LASTEXITCODE -ne 0 -or -not $translated) {
                throw "could not translate image diagnostic path for WSL: $source"
            }
            $wslSources += ([string]($translated | Select-Object -First 1)).Trim()
        }

        & wsl.exe -u root --exec nsenter -t 1 -m -- mkdir -p $catalogueTarget "$mountPoint/.ephemeral"
        if ($LASTEXITCODE -ne 0) {
            throw 'could not create image diagnostic mount targets.'
        }

        & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslSources[0] $buildTarget
        if ($LASTEXITCODE -ne 0) { throw 'image build bind mount failed.' }
        $buildMounted = $true

        & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslSources[1] $catalogueTarget
        if ($LASTEXITCODE -ne 0) { throw 'image catalogue bind mount failed.' }
        $catalogueMounted = $true

        $python = '/the one/software/python/bin/python3.13'
        $viewer = '/the one/build/viewer/viewer.py'
        $output = & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B $viewer --diagnostic 2>&1
        $exitCode = $LASTEXITCODE

        if (-not $output) {
            throw 'image diagnostic produced no output.'
        }

        $actual = ([string]($output | Select-Object -Last 1)).Trim() | ConvertFrom-Json
        if ($exitCode -ne 0 -or -not $actual.passed) {
            $message = if ($actual.error) { [string]$actual.error } else { [string]($actual.errors -join '; ') }
            throw "image diagnostic failed: $message"
        }

        if (-not $actual.checks.png -or -not $actual.checks.jpeg -or -not $actual.checks.orientation -or -not $actual.checks.bgra_surface -or @($actual.checks.invalid_rejected).Count -ne 2) {
            throw 'image diagnostic did not exercise both decoders, EXIF orientation, BGRA output, and invalid input rejection.'
        }

        $graphicsOutput = & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B $viewer --graphics-diagnostic 2>&1
        $graphicsExitCode = $LASTEXITCODE

        if (-not $graphicsOutput) {
            throw 'Viewer graphics diagnostic produced no output.'
        }

        $graphicsActual = ([string]($graphicsOutput | Select-Object -Last 1)).Trim() | ConvertFrom-Json
        if ($graphicsExitCode -ne 0 -or -not $graphicsActual.passed) {
            throw "Viewer graphics diagnostic failed: $($graphicsActual.errors -join '; ')"
        }

        if (-not $graphicsActual.checks.managed_scene -or -not $graphicsActual.checks.cpu_blit -or -not $graphicsActual.checks.pan_clamp -or -not $graphicsActual.checks.controls -or -not $graphicsActual.checks.async_worker) {
            throw 'Viewer graphics diagnostic did not exercise managed rendering, CPU blitting, pan limits, controls, and asynchronous surface work.'
        }

        $brick = '/the one/build/brick/brick.py'
        $viewOutput = & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B $brick view-diagnostic 2>&1
        $viewExitCode = $LASTEXITCODE

        if (-not $viewOutput) {
            throw 'Brick image-view diagnostic produced no output.'
        }

        $viewActual = ([string]($viewOutput | Select-Object -Last 1)).Trim() | ConvertFrom-Json
        if ($viewExitCode -ne 0 -or -not $viewActual.passed) {
            throw "Brick image-view diagnostic failed: $($viewActual.errors -join '; ')"
        }

        if ($viewActual.checks.decode.format -ne 'JPEG' -or -not $viewActual.checks.inline_scrollback -or -not $viewActual.checks.scrolling -or -not $viewActual.checks.managed_scene -or -not $viewActual.checks.cpu_blit -or -not $viewActual.checks.directive) {
            throw 'Brick image-view diagnostic did not exercise inline JPEG scrollback, scrolling, managed rendering, CPU blitting, and directive registration.'
        }

        Write-Host 'image runtime diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 8 -Compress)
        Write-Host ($graphicsActual | ConvertTo-Json -Depth 8 -Compress)
        Write-Host ($viewActual | ConvertTo-Json -Depth 8 -Compress)
    }
    finally {
        foreach ($mount in @(
            @($catalogueMounted, $catalogueTarget),
            @($buildMounted, $buildTarget)
        )) {
            if ($mount[0]) {
                & wsl.exe -u root --exec nsenter -t 1 -m -- umount $mount[1]
                if ($LASTEXITCODE -ne 0 -and -not $cleanupError) {
                    $cleanupError = "image bind unmount failed for $($mount[1])."
                }
            }
        }

        if ($diskMounted) {
            & pwsh -NoLogo -NoProfile -NonInteractive -File $unmountScript | Out-Host
            if ($LASTEXITCODE -ne 0 -and -not $cleanupError) {
                $cleanupError = 'image diagnostic image unmount failed.'
            }
        }

        if ($cleanupError) {
            throw $cleanupError
        }
    }
}


Write-Host "checking that storage is not mounted..."

$mounted = Test-T1OSDiskMounted

if ($mounted) {
    Write-Host ""
    Write-Host "t1fs is mounted. running unmount..."

    $unmountScript = Join-Path $projectRoot 'scripts/unmount.ps1'

    if (-not (Test-Path $unmountScript)) {
        Write-Host "unmount.ps1 not found in this directory."
        exit 1
    }

    & pwsh -NoLogo -NoProfile -NonInteractive -File "$unmountScript"
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        Write-Host "unmount failed with exit code $exitCode."
        exit 1
    }

    Write-Host ""
    Write-Host "unmount completed. continuing..."
}


Invoke-ImageDiagnostic

Write-Host 'Runtime image validation passed.'
