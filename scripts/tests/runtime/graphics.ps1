[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Mode,
    [switch]$Update,
    [switch]$Deployed
)

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$environmentRoot = Join-Path $projectRoot 'environment\software'
. (Join-Path $projectRoot 'scripts\common.ps1')
Set-Location -LiteralPath $environmentRoot

function Invoke-GraphicsBaseline {
    param(
        [Parameter(Mandatory)]
        [bool]$Update,

        [ValidateSet('baseline', 'opengl', 'compositor', 'brick', 'player', 'viewer', 'brick-directives', 'write', 'write-performance', 'array', 'calculator', 'operations-centre', 'operations-server', 'settings', 'expanse', 'startup', 'lockscreen', 'boot', 'virtualbox-clipboard')]
        [string]$Mode = 'baseline',

        [bool]$UseDeployed = $false
    )

    $mountScript = Join-Path $projectRoot 'scripts/deployment/mount.ps1'
    $unmountScript = Join-Path $projectRoot 'scripts/deployment/unmount.ps1'
    $buildSource = Join-Path $projectRoot 'source\build software'
    $bootSource = Join-Path $projectRoot 'source\boot'
    $virtualBoxSoftwareSource = Join-Path $projectRoot 'source\software\virtualbox'
    $baselinePath = Join-Path $projectRoot 'development\graphics baseline.json'
    $catalogueSource = Join-Path $projectRoot 'source\catalogue\graphics'
    $fontSource = Join-Path $projectRoot 'resource\fonts'
    $expanseResourceSource = Join-Path $projectRoot 'resource\logos'
    $mountPoint = '/mnt/t1fs'
    $buildTarget = '/mnt/t1fs/the one/build'
    $bootTarget = '/mnt/t1fs/boot'
    $virtualBoxSoftwareTarget = '/mnt/t1fs/the one/software/virtualbox'
    $catalogueTarget = '/mnt/t1fs/the one/catalogue/graphics'
    $fontTarget = '/mnt/t1fs/the one/resources/fonts'
    $expanseResourceTarget = '/mnt/t1fs/the one/resources/expanse'
    $ephemeralTarget = '/mnt/t1fs/.ephemeral'
    $logsTarget = '/mnt/t1fs/the one/logs'
    $rubbishTarget = '/mnt/t1fs/.rubbish'
    $driversTarget = '/mnt/t1fs/the one/drivers'
    $processTarget = '/mnt/t1fs/the one/drivers/processes'
    $diagnosticTempRoot = '/tmp/t1os-graphics-{0}-{1}' -f $PID, [guid]::NewGuid().ToString('N')
    $diskMounted = $false
    $buildMounted = $false
    $bootMounted = $false
    $virtualBoxSoftwareMounted = $false
    $catalogueMounted = $false
    $fontMounted = $false
    $expanseResourceMounted = $false
    $ephemeralMounted = $false
    $logsMounted = $false
    $rubbishMounted = $false
    $driversMounted = $false
    $processMounted = $false
    $diagnosticTempCreated = $false
    $baselineOutput = $null
    $baselineExitCode = 1

    try {
        Write-Host 'mounting the T1OS image for graphics baseline testing...'

        & pwsh -NoLogo -NoProfile -NonInteractive -File $mountScript -ReadOnly
        if ($LASTEXITCODE -ne 0) {
            throw "mount failed with exit code $LASTEXITCODE."
        }

        $diskMounted = $true

        Write-Host 'binding writable temporary runtime and log directories over the read-only image...'
        & wsl.exe -u root --exec nsenter -t 1 -m -- mkdir -p "$diagnosticTempRoot/ephemeral" "$diagnosticTempRoot/logs" "$diagnosticTempRoot/rubbish" "$diagnosticTempRoot/drivers/processes"
        if ($LASTEXITCODE -ne 0) {
            throw 'could not create writable graphics diagnostic directories.'
        }
        $diagnosticTempCreated = $true

        & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind "$diagnosticTempRoot/ephemeral" $ephemeralTarget
        if ($LASTEXITCODE -ne 0) {
            throw "writable ephemeral bind mount failed with exit code $LASTEXITCODE."
        }
        $ephemeralMounted = $true

        & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind "$diagnosticTempRoot/logs" $logsTarget
        if ($LASTEXITCODE -ne 0) {
            throw "writable log bind mount failed with exit code $LASTEXITCODE."
        }
        $logsMounted = $true

        if ($Mode -eq 'brick-directives') {
            Write-Host 'binding a writable disposable rubbish tier for Brick directive testing...'
            & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind "$diagnosticTempRoot/rubbish" $rubbishTarget
            if ($LASTEXITCODE -ne 0) {
                throw "writable rubbish bind mount failed with exit code $LASTEXITCODE."
            }
            $rubbishMounted = $true

            & wsl.exe -u root --exec nsenter -t 1 -m -- sh -c 'umask 077; printf "%s\n" "role=architect" > "$1"' sh "$diagnosticTempRoot/ephemeral/brick-test-master.txt"
            if ($LASTEXITCODE -ne 0) {
                throw 'could not create the disposable Brick architect-role fixture.'
            }
        }

        if ($Mode -in @('operations-server', 'brick-directives')) {
            Write-Host 'mounting the process telemetry tree for the Operations Server diagnostic...'

            & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind "$diagnosticTempRoot/drivers" $driversTarget
            if ($LASTEXITCODE -ne 0) {
                throw "driver telemetry bind mount failed with exit code $LASTEXITCODE."
            }

            $driversMounted = $true

            & wsl.exe -u root --exec nsenter -t 1 -m -- mount -t proc proc $processTarget
            if ($LASTEXITCODE -ne 0) {
                throw "process telemetry mount failed with exit code $LASTEXITCODE."
            }

            $processMounted = $true
        }

        if (-not $UseDeployed) {
            Write-Host 'locating the current build source in WSL...'

            $wslBuildOutput = & wsl.exe --exec wslpath -a $buildSource
            if ($LASTEXITCODE -ne 0 -or -not $wslBuildOutput) {
                throw 'could not translate the build source path for WSL.'
            }

            $wslBuildSource = ([string]($wslBuildOutput | Select-Object -First 1)).Trim()
            if ([string]::IsNullOrWhiteSpace($wslBuildSource)) {
                throw 'WSL returned an empty build source path.'
            }

            Write-Host 'binding the current source over the image build tier...'

            & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslBuildSource $buildTarget
            if ($LASTEXITCODE -ne 0) {
                throw "build bind mount failed with exit code $LASTEXITCODE."
            }

            $buildMounted = $true
        }

        if (-not $UseDeployed -and $Mode -in @('baseline', 'opengl', 'compositor', 'player', 'viewer', 'write', 'write-performance', 'array', 'calculator', 'operations-centre', 'expanse', 'startup')) {
            Write-Host 'locating and binding the current font resources...'

            $wslFontOutput = & wsl.exe --exec wslpath -a $fontSource
            if ($LASTEXITCODE -ne 0 -or -not $wslFontOutput) {
                throw 'could not translate the font resource path for WSL.'
            }

            $wslFontSource = ([string]($wslFontOutput | Select-Object -First 1)).Trim()
            & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslFontSource $fontTarget
            if ($LASTEXITCODE -ne 0) {
                throw "font resource bind mount failed with exit code $LASTEXITCODE."
            }

            $fontMounted = $true
        }

        if (-not $UseDeployed -and $Mode -eq 'expanse') {
            Write-Host 'locating and binding the canonical Expanse PNG resources...'

            $wslExpanseResourceOutput = & wsl.exe --exec wslpath -a $expanseResourceSource
            if ($LASTEXITCODE -ne 0 -or -not $wslExpanseResourceOutput) {
                throw 'could not translate the Expanse PNG resource path for WSL.'
            }

            $wslExpanseResourceSource = ([string]($wslExpanseResourceOutput | Select-Object -First 1)).Trim()
            & wsl.exe -u root --exec nsenter -t 1 -m -- mkdir -p $expanseResourceTarget
            if ($LASTEXITCODE -ne 0) {
                throw 'could not create the Expanse PNG resource mount target.'
            }

            & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslExpanseResourceSource $expanseResourceTarget
            if ($LASTEXITCODE -ne 0) {
                throw "Expanse PNG resource bind mount failed with exit code $LASTEXITCODE."
            }

            $expanseResourceMounted = $true
        }

        if (-not $UseDeployed -and $Mode -eq 'virtualbox-clipboard') {
            Write-Host 'locating and binding the current VirtualBox software...'

            $wslVirtualBoxOutput = & wsl.exe --exec wslpath -a $virtualBoxSoftwareSource
            if ($LASTEXITCODE -ne 0 -or -not $wslVirtualBoxOutput) {
                throw 'could not translate the VirtualBox software source path for WSL.'
            }

            $wslVirtualBoxSource = ([string]($wslVirtualBoxOutput | Select-Object -First 1)).Trim()
            & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslVirtualBoxSource $virtualBoxSoftwareTarget
            if ($LASTEXITCODE -ne 0) {
                throw "VirtualBox software bind mount failed with exit code $LASTEXITCODE."
            }

            $virtualBoxSoftwareMounted = $true
        }

        if (-not $UseDeployed -and $Mode -eq 'boot') {
            Write-Host 'locating and binding the current boot source...'

            $wslBootOutput = & wsl.exe --exec wslpath -a $bootSource
            if ($LASTEXITCODE -ne 0 -or -not $wslBootOutput) {
                throw 'could not translate the boot source path for WSL.'
            }

            $wslBootSource = ([string]($wslBootOutput | Select-Object -First 1)).Trim()
            & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslBootSource $bootTarget
            if ($LASTEXITCODE -ne 0) {
                throw "boot bind mount failed with exit code $LASTEXITCODE."
            }

            $bootMounted = $true
        }

        if (-not $UseDeployed -and $Mode -in @('opengl', 'compositor', 'brick', 'player', 'viewer', 'brick-directives', 'write', 'array', 'calculator', 'operations-centre', 'expanse', 'startup', 'lockscreen', 'boot')) {
            Write-Host 'locating and binding the current graphics catalogue...'

            $wslCatalogueOutput = & wsl.exe --exec wslpath -a $catalogueSource
            if ($LASTEXITCODE -ne 0 -or -not $wslCatalogueOutput) {
                throw 'could not translate the graphics catalogue path for WSL.'
            }

            $wslCatalogueSource = ([string]($wslCatalogueOutput | Select-Object -First 1)).Trim()
            & wsl.exe -u root --exec nsenter -t 1 -m -- mkdir -p $catalogueTarget
            if ($LASTEXITCODE -ne 0) {
                throw 'could not create the graphics catalogue mount target.'
            }

            & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslCatalogueSource $catalogueTarget
            if ($LASTEXITCODE -ne 0) {
                throw "graphics catalogue bind mount failed with exit code $LASTEXITCODE."
            }

            $catalogueMounted = $true
        }

        $program = '/the one/build/graphics/graphics.py'
        $argument = $Mode

        if ($Mode -eq 'compositor') {
            $program = '/the one/build/windows/windowserver.py'
            $argument = 'diagnostic'
        }

        if ($Mode -eq 'brick') {
            $program = '/the one/build/brick/brick.py'
            $argument = 'graphics-diagnostic'
        }

        if ($Mode -eq 'player') {
            $program = '/the one/build/player/player.py'
            $argument = 'graphics-diagnostic'
        }

        if ($Mode -eq 'viewer') {
            $program = '/the one/build/viewer/viewer.py'
            $argument = '--graphics-diagnostic'
        }

        if ($Mode -eq 'brick-directives') {
            $program = '/the one/build/brick/brick.py'
            $argument = 'directive-diagnostic'
        }

        if ($Mode -eq 'write') {
            $program = '/the one/build/write/write.py'
            $argument = 'graphics-diagnostic'
        }

        if ($Mode -eq 'write-performance') {
            $program = '/the one/build/write/write.py'
            $argument = 'performance-diagnostic'
        }

        if ($Mode -eq 'array') {
            $program = '/the one/build/array/array.py'
            $argument = 'graphics-diagnostic'
        }

        if ($Mode -eq 'calculator') {
            $program = '/the one/build/calculator/calculator.py'
            $argument = 'graphics-diagnostic'
        }

        if ($Mode -eq 'operations-centre') {
            $program = '/the one/build/operations/operationscentre.py'
            $argument = 'graphics-diagnostic'
        }

        if ($Mode -eq 'operations-server') {
            $program = '/the one/build/operations/operationsserver.py'
            $argument = 'diagnostic'
        }

        if ($Mode -eq 'expanse') {
            $program = '/the one/build/expanse/expanse.py'
            $argument = 'graphics-diagnostic'
        }

        if ($Mode -eq 'settings') {
            $program = '/the one/build/settings/settings.py'
            $argument = '--diagnostic'
        }

        if ($Mode -eq 'startup') {
            $program = '/the one/build/startup/startup.py'
            $argument = 'graphics-diagnostic'
        }

        if ($Mode -eq 'lockscreen') {
            $program = '/the one/build/lock screen/lock screen.py'
            $argument = 'graphics-diagnostic'
        }

        if ($Mode -eq 'boot') {
            $program = '/boot/boot animation/boot animation.py'
            $argument = 'graphics-diagnostic'
        }

        if ($Mode -eq 'virtualbox-clipboard') {
            $program = '/the one/software/virtualbox/guestadditions.py'
            $argument = 'diagnostic'
        }

        Write-Host "running $program $argument with the T1OS Python runtime..."

        if ($Mode -eq 'expanse') {
            $loader = 'import importlib.util,runpy,sys,types; package=types.ModuleType("windows"); package.__path__=["/the one/build/windows"]; sys.modules["windows"]=package; spec=importlib.util.spec_from_file_location("windows.windowserver","/the one/build/windows/windowserver.py"); module=importlib.util.module_from_spec(spec); sys.modules["windows.windowserver"]=module; spec.loader.exec_module(module); program=sys.argv[1]; argument=sys.argv[2]; sys.argv=[program,argument]; runpy.run_path(program,run_name="__main__")'
            $baselineOutput = & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint '/the one/software/python/bin/python3.13' -B -c $loader $program $argument
        }
        elseif ($Mode -eq 'brick-directives') {
            $baselineOutput = & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/bin/env 'T1OS_MASTER_FILE=/.ephemeral/brick-test-master.txt' /usr/sbin/chroot $mountPoint '/the one/software/python/bin/python3.13' -B $program $argument
        }
        elseif ($Mode -eq 'settings') {
            $loader = 'import runpy,sys,tempfile; tempfile.tempdir="/.ephemeral"; program=sys.argv[1]; argument=sys.argv[2]; sys.argv=[program,argument]; runpy.run_path(program,run_name="__main__")'
            $baselineOutput = & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint '/the one/software/python/bin/python3.13' -B -c $loader $program $argument
        }
        else {
            $baselineOutput = & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint '/the one/software/python/bin/python3.13' -B $program $argument
        }

        $baselineExitCode = $LASTEXITCODE
    }
    finally {
        if ($expanseResourceMounted) {
            Write-Host 'unmounting the canonical Expanse PNG resources...'

            & wsl.exe -u root --exec nsenter -t 1 -m -- umount $expanseResourceTarget
            if ($LASTEXITCODE -ne 0) {
                throw "Expanse PNG resource bind unmount failed with exit code $LASTEXITCODE."
            }
        }

        if ($virtualBoxSoftwareMounted) {
            Write-Host 'unmounting the current VirtualBox software...'

            & wsl.exe -u root --exec nsenter -t 1 -m -- umount $virtualBoxSoftwareTarget
            if ($LASTEXITCODE -ne 0) {
                throw "VirtualBox software bind unmount failed with exit code $LASTEXITCODE."
            }
        }

        if ($bootMounted) {
            Write-Host 'unmounting the current boot source...'

            & wsl.exe -u root --exec nsenter -t 1 -m -- umount $bootTarget
            if ($LASTEXITCODE -ne 0) {
                throw "boot bind unmount failed with exit code $LASTEXITCODE."
            }
        }

        if ($catalogueMounted) {
            Write-Host 'unmounting the current graphics catalogue...'

            & wsl.exe -u root --exec nsenter -t 1 -m -- umount $catalogueTarget
            if ($LASTEXITCODE -ne 0) {
                throw "graphics catalogue bind unmount failed with exit code $LASTEXITCODE."
            }
        }

        if ($fontMounted) {
            Write-Host 'unmounting the current font resources...'

            & wsl.exe -u root --exec nsenter -t 1 -m -- umount $fontTarget
            if ($LASTEXITCODE -ne 0) {
                throw "font resource bind unmount failed with exit code $LASTEXITCODE."
            }
        }

        if ($buildMounted) {
            Write-Host 'unmounting the current build source...'

            & wsl.exe -u root --exec nsenter -t 1 -m -- umount $buildTarget

            if ($LASTEXITCODE -ne 0) {
                Start-Sleep -Milliseconds 300
                & wsl.exe -u root --exec nsenter -t 1 -m -- umount $buildTarget
            }

            if ($LASTEXITCODE -ne 0) {
                throw "build bind unmount failed with exit code $LASTEXITCODE."
            }
        }

        if ($processMounted) {
            Write-Host 'unmounting the process telemetry tree...'

            & wsl.exe -u root --exec nsenter -t 1 -m -- umount $processTarget
            if ($LASTEXITCODE -ne 0) {
                throw "process telemetry unmount failed with exit code $LASTEXITCODE."
            }
        }

        if ($driversMounted) {
            Write-Host 'unmounting the diagnostic driver tree...'

            & wsl.exe -u root --exec nsenter -t 1 -m -- umount $driversTarget
            if ($LASTEXITCODE -ne 0) {
                throw "driver telemetry bind unmount failed with exit code $LASTEXITCODE."
            }
        }

        if ($rubbishMounted) {
            Write-Host 'unmounting the disposable Brick rubbish tier...'

            & wsl.exe -u root --exec nsenter -t 1 -m -- umount $rubbishTarget
            if ($LASTEXITCODE -ne 0) {
                throw "Brick rubbish bind unmount failed with exit code $LASTEXITCODE."
            }
        }

        if ($logsMounted) {
            Write-Host 'unmounting the writable diagnostic logs...'

            & wsl.exe -u root --exec nsenter -t 1 -m -- umount $logsTarget
            if ($LASTEXITCODE -ne 0) {
                throw "diagnostic log bind unmount failed with exit code $LASTEXITCODE."
            }
        }

        if ($ephemeralMounted) {
            Write-Host 'unmounting the writable diagnostic runtime...'

            & wsl.exe -u root --exec nsenter -t 1 -m -- umount $ephemeralTarget
            if ($LASTEXITCODE -ne 0) {
                throw "diagnostic runtime bind unmount failed with exit code $LASTEXITCODE."
            }
        }

        if ($diskMounted) {
            Write-Host 'unmounting the T1OS image...'

            & pwsh -NoLogo -NoProfile -NonInteractive -File $unmountScript
            if ($LASTEXITCODE -ne 0) {
                throw "image unmount failed with exit code $LASTEXITCODE."
            }
        }

        if ($diagnosticTempCreated) {
            & wsl.exe -u root --exec sh -c 'case "$1" in /tmp/t1os-graphics-*) rm -rf -- "$1";; *) exit 1;; esac' sh $diagnosticTempRoot
            if ($LASTEXITCODE -ne 0) {
                throw 'graphics diagnostic temporary-directory cleanup failed.'
            }
        }
    }

    if (-not $baselineOutput) {
        throw 'graphics baseline returned no output.'
    }

    $baselineText = ([string]($baselineOutput -join "`n")).Trim()
    $baselineJson = @($baselineOutput | Where-Object {
        ([string]$_).TrimStart().StartsWith('{')
    } | Select-Object -Last 1)

    if ($baselineJson.Count -eq 1) {
        $baselineText = ([string]$baselineJson[0]).Trim()
    }

    try {
        $actual = $baselineText | ConvertFrom-Json
    }
    catch {
        throw "graphics baseline returned invalid JSON: $baselineText"
    }

    if ($baselineExitCode -ne 0 -or -not $actual.passed) {
        $errors = ([string[]]$actual.errors) -join '; '
        throw "graphics baseline failed: $errors"
    }

    if ($Mode -eq 'virtualbox-clipboard') {
        Write-Host 'VirtualBox clipboard diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 5 -Compress)
        return
    }

    if ($Mode -eq 'operations-server') {

        if (
            [double]$actual.checks.gpu_telemetry.system_percent -ne 12.0 -or
            [double]$actual.checks.gpu_telemetry.process_percent -ne 7.2
        ) {
            throw 'the Operations Server diagnostic did not preserve system and per-operation GPU telemetry.'
        }

        Write-Host 'Operations Server lifecycle and telemetry diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 5 -Compress)
        return
    }

    if ($Mode -eq 'settings') {
        if (-not $actual.checks.settings_3839x1974_80_scale) {
            throw 'Settings did not preserve its 3839x1974 at 80% scale contract.'
        }

        Write-Host 'Settings persistence, layout, scale, and managed-text diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 5 -Compress)
        return
    }

    if ($Mode -eq 'opengl') {
        Write-Host 'graphics OpenGL diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 5 -Compress)
        return
    }

    if ($Mode -eq 'compositor') {

        if ([int]$actual.telemetry.failed_frames -ne 0) {
            throw 'the compositor diagnostic recorded failed GPU frames.'
        }

        if ([int]$actual.telemetry.fallbacks -ne 0) {
            throw 'the compositor diagnostic used the CPU fallback.'
        }

        if ([int]$actual.checks.occlusion_culling.windows -lt 1 -or [int]$actual.checks.occlusion_culling.draw_calls_saved -lt 1) {
            throw 'the compositor diagnostic did not exercise occlusion culling.'
        }

        if ([int]$actual.graphics_api.committed_commands -ne 3) {
            throw 'the compositor diagnostic did not commit rectangle, image, and text commands.'
        }

        if (-not $actual.graphics_api.atomic_scene -or [int]$actual.graphics_api.batch_messages -ne 1 -or [int]$actual.graphics_api.batch_commands -ne 3) {
            throw 'the compositor diagnostic did not commit one atomic managed scene.'
        }

        if ([int]$actual.telemetry.partial_frames -lt 1 -or [int64]$actual.telemetry.scissored_pixels -lt 1 -or [int]$actual.telemetry.persistent_sync_frames -lt 1) {
            throw 'the compositor diagnostic did not exercise persistent partial composition.'
        }

        if (-not $actual.checks.atomic_scene -or $null -eq $actual.checks.full_frame_fallback) {
            throw 'the compositor diagnostic did not exercise atomic scenes and full-frame recovery.'
        }

        if ([int]$actual.checks.window_telemetry.batch_commits -lt 1 -or [int]$actual.checks.window_telemetry.gpu_draw_calls -lt 1) {
            throw 'the compositor diagnostic did not record per-window attribution telemetry.'
        }

        if ([int]$actual.checks.partial_composition.draw_calls_saved -lt 1 -or [int64]$actual.checks.partial_composition.damage_pixels -ge [int64]$actual.checks.partial_composition.frame_pixels) {
            throw 'the compositor diagnostic did not prove reduced partial-frame work.'
        }

        if ($null -eq $actual.checks.cursor_partial -or $null -eq $actual.checks.cursor_old_region -or $null -eq $actual.checks.cursor_new_region -or $null -eq $actual.checks.cursor_removed) {
            throw 'the compositor diagnostic did not verify damage-aware cursor movement and removal.'
        }

        if (-not $actual.checks.transition_final_frame -or -not $actual.checks.startmenu_final_map -or -not $actual.checks.window_final_map -or $null -eq $actual.checks.window_chrome_first_frame -or $null -eq $actual.checks.window_button_first_frame) {
            throw 'the compositor diagnostic did not verify final mapping frames for shell surfaces and window chrome.'
        }

        if ([int]$actual.checks.operations_centre_global_shortcut.launches -ne 1 -or [int]$actual.checks.operations_centre_global_shortcut.focused_window_events -ne 0) {
            throw 'the compositor diagnostic did not preserve Ctrl+Shift+Esc as the exclusive global Operations Centre shortcut.'
        }

        if ([int]$actual.checks.gpu_process_telemetry.pid -ne 4242 -or -not $actual.checks.gpu_process_telemetry.sampled) {
            throw 'the compositor diagnostic did not expose sampled per-process GPU telemetry.'
        }

        if (
            [int]$actual.checks.chromium_external_buffer.source[0] -ne 32 -or
            [int]$actual.checks.chromium_external_buffer.source[1] -ne 24 -or
            [int]$actual.checks.chromium_external_buffer.output[0] -ne 96 -or
            [int]$actual.checks.chromium_external_buffer.output[1] -ne 72 -or
            -not $actual.checks.chromium_external_buffer.logical_resize_reused_texture
        ) {
            throw 'the compositor diagnostic did not scale a bounded Chromium source into its logical output.'
        }

        if (Test-Path -LiteralPath $baselinePath -PathType Leaf) {

            $stored = Get-Content -LiteralPath $baselinePath -Raw | ConvertFrom-Json
            $compositorBaseline = $stored.compositor_1440p

            if ($null -ne $compositorBaseline) {

                $timingTolerance = [double]$compositorBaseline.timing_tolerance_multiplier
                $resourceTolerance = [double]$compositorBaseline.resource_tolerance_multiplier

                if ([double]$actual.performance.percentile_95_frame_ms -gt ([double]$compositorBaseline.percentile_95_frame_ms * $timingTolerance)) {
                    throw 'the compositor 95th-percentile frame time exceeded the stored 1440p tolerance.'
                }

                if ([double]$actual.performance.draw_calls_per_frame -gt ([double]$compositorBaseline.draw_calls_per_frame * $resourceTolerance)) {
                    throw 'the compositor draw calls per frame exceeded the stored 1440p tolerance.'
                }

                if ([double]$actual.performance.maximum_texture_bytes -gt ([double]$compositorBaseline.maximum_texture_bytes * $resourceTolerance)) {
                    throw 'the compositor peak texture memory exceeded the stored 1440p tolerance.'
                }
            }
        }

        Write-Host 'GPU window compositor diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 8 -Compress)
        return
    }

    if ($Mode -eq 'brick') {

        if (-not $actual.checks.capability_negotiation -or -not $actual.checks.cpu_fallback) {
            throw 'the Brick diagnostic did not exercise managed negotiation and CPU fallback.'
        }

        if (-not $actual.checks.opaque_background -or -not $actual.checks.text_clipping -or -not $actual.checks.image_view_scene) {
            throw 'the Brick diagnostic did not validate background coverage, clipped text, and image viewing.'
        }

        if ([int]$actual.checks.command_budget.commands -ge [int]$actual.checks.command_budget.limit) {
            throw 'the Brick managed scene exhausted its command budget.'
        }

        if ([int]$actual.checks.atomic_scene.messages -ne 1 -or [int]$actual.checks.atomic_scene.commands -lt 1) {
            throw 'the Brick diagnostic did not submit one atomic managed scene.'
        }

        if (Test-Path -LiteralPath $baselinePath -PathType Leaf) {

            $stored = Get-Content -LiteralPath $baselinePath -Raw | ConvertFrom-Json
            $brickBaseline = $stored.brick_1440p

            if ($null -ne $brickBaseline) {

                if ([double]$actual.performance.average_scene_build_ms -gt ([double]$brickBaseline.average_scene_build_ms * [double]$brickBaseline.timing_tolerance_multiplier)) {
                    throw 'the Brick managed-scene build time exceeded the stored 1440p tolerance.'
                }

                if ([int]$actual.performance.maximum_commands -gt ([int]$brickBaseline.maximum_commands * [double]$brickBaseline.command_tolerance_multiplier)) {
                    throw 'the Brick managed-scene command count exceeded the stored 1440p tolerance.'
                }
            }
        }

        Write-Host 'Brick managed graphics diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 8 -Compress)
        return
    }

    if ($Mode -eq 'player') {

        if (-not $actual.checks.geometry -or -not $actual.checks.playing_scene -or -not $actual.checks.metadata_scene -or -not $actual.checks.embedded_artwork -or -not $actual.checks.metadata_worker -or -not $actual.checks.deferred_artwork -or -not $actual.checks.pending_artwork_state -or -not $actual.checks.paused_scene -or -not $actual.checks.drag_preview -or -not $actual.checks.time_format -or -not $actual.checks.compact_layout -or -not $actual.checks.focus_input -or -not $actual.checks.playback_lifecycle) {
            throw 'the Player diagnostic did not validate its playback controls, states, and responsive layout.'
        }

        if (-not $actual.checks.managed_graphics -or -not $actual.checks.error_gpu_retention -or -not $actual.checks.timeout_gpu_retention -or -not $actual.checks.cpu_fallback -or -not $actual.checks.cpu_paint) {
            throw 'the Player diagnostic did not validate managed rendering, strict GPU recovery, and the unavailable-GPU recovery painter.'
        }

        Write-Host 'Player managed graphics diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 8 -Compress)
        return
    }

    if ($Mode -eq 'viewer') {
        if (
            -not $actual.checks.managed_scene -or
            -not $actual.checks.async_worker -or
            [string]$actual.checks.surface_permissions.parent -ne '0711' -or
            [string]$actual.checks.surface_permissions.directory -ne '0711' -or
            [string]$actual.checks.surface_permissions.file -ne '0604'
        ) {
            throw 'the Viewer diagnostic did not preserve its managed-scene and WindowServer-readable surface contract.'
        }

        Write-Host 'Viewer managed graphics and surface-permission diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 8 -Compress)
        return
    }

    if ($Mode -eq 'brick-directives') {

        if (
            -not $actual.checks.copy_file_with_spaces -or
            -not $actual.checks.copy_tier_with_spaces -or
            -not $actual.checks.move_tier_success -or
            -not $actual.checks.write_in_with_spaces -or
            -not $actual.checks.restore_with_spaces -or
            -not $actual.checks.deterministic_restore -or
            -not $actual.checks.protected_path_with_spaces -or
            -not $actual.checks.recursive_tier_help -or
            -not $actual.checks.directive_catalogue -or
            -not $actual.checks.t1os_version_only -or
            -not $actual.checks.paste_confirmation -or
            -not $actual.checks.connective_paths -or
            -not $actual.checks.navigation_and_depth -or
            -not $actual.checks.details_compare_replace -or
            -not $actual.checks.syntax_only -or
            -not $actual.checks.bounded_read -or
            -not $actual.checks.expanded_search -or
            -not $actual.checks.system_report -or
            -not $actual.checks.operations_lifecycle -or
            -not $actual.checks.directive_outcomes -or
            -not $actual.checks.parsing_suite -or
            -not $actual.checks.files_suite -or
            -not $actual.checks.rubbish_suite -or
            -not $actual.checks.search_suite -or
            -not $actual.checks.operations_suite -or
            -not $actual.checks.development_suite -or
            -not $actual.checks.dogfood_suite
        ) {
            throw 'the Brick directive diagnostic did not validate every directive capability.'
        }

        Write-Host 'Brick directive diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 5 -Compress)
        return
    }

    if ($Mode -eq 'write') {

        if (-not $actual.checks.capability_negotiation -or -not $actual.checks.cpu_fallback -or -not $actual.checks.error_gpu_retention -or -not $actual.checks.timeout_gpu_retention) {
            throw 'the Write diagnostic did not exercise managed negotiation and strict GPU recovery.'
        }

        if (-not $actual.checks.opaque_background -or -not $actual.checks.atkinson_baseline -or -not $actual.checks.variable_width_clipping) {
            throw 'the Write diagnostic did not validate background coverage, Atkinson placement, and variable-width clipping.'
        }

        if ([int]$actual.checks.outlined_menu -ne 4 -or -not $actual.checks.selection_cursor_scrollbars -or -not $actual.checks.cursor_visibility -or -not $actual.checks.status_path_prompt) {
            throw 'the Write diagnostic did not preserve menu, selection, cursor, scrollbar, status, and prompt geometry.'
        }

        if ([int]$actual.checks.vertical_scrollbar_geometry.track.Count -ne 4 -or [int]$actual.checks.vertical_scrollbar_geometry.thumb.Count -ne 4 -or [int]$actual.checks.vertical_scrollbar_geometry.opaque -ne 1 -or -not $actual.checks.document_viewport_reserved_ui -or -not $actual.checks.right_edge_scrollbar -or -not $actual.checks.status_beneath_scrollbar) {
            throw 'the Write diagnostic did not reserve and mask the scrollbar and status-bar regions.'
        }

        if ([int]$actual.checks.atomic_scene.messages -ne 1 -or [int]$actual.checks.atomic_scene.commands -lt 1 -or [int]$actual.checks.atomic_scene.damage -ne 1) {
            throw 'the Write diagnostic did not submit one atomic damage-aware scene.'
        }

        if ([int]$actual.checks.retained_cursor_patch.upsert -gt 2 -or [int]$actual.checks.retained_cursor_patch.remove -gt 2) {
            throw 'the Write retained cursor patch replaced unrelated scene nodes.'
        }

        if ([int]$actual.checks.command_budget.commands -ge [int]$actual.checks.command_budget.limit) {
            throw 'the Write managed scene exhausted its command budget.'
        }

        if (Test-Path -LiteralPath $baselinePath -PathType Leaf) {

            $stored = Get-Content -LiteralPath $baselinePath -Raw | ConvertFrom-Json
            $writeBaseline = $stored.write_1440p

            if ($null -ne $writeBaseline) {

                if ([double]$actual.performance.average_scene_build_ms -gt ([double]$writeBaseline.average_scene_build_ms * [double]$writeBaseline.timing_tolerance_multiplier)) {
                    throw 'the Write managed-scene build time exceeded the stored 1440p tolerance.'
                }

                if ([double]$actual.performance.maximum_scene_build_ms -gt ([double]$writeBaseline.maximum_scene_build_ms * [double]$writeBaseline.timing_tolerance_multiplier)) {
                    throw 'the Write maximum managed-scene build time exceeded the stored 1440p tolerance.'
                }

                if ([int]$actual.performance.maximum_commands -gt ([int]$writeBaseline.maximum_commands * [double]$writeBaseline.command_tolerance_multiplier)) {
                    throw 'the Write managed-scene command count exceeded the stored 1440p tolerance.'
                }
            }
        }

        Write-Host 'Write managed graphics diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 8 -Compress)
        return
    }

    if ($Mode -eq 'write-performance') {

        if (-not $actual.checks.document_round_trip -or -not $actual.checks.incremental_widths -or -not $actual.checks.operation_undo_redo -or -not $actual.checks.tab_indentation -or -not $actual.checks.saved_revision -or -not $actual.checks.typing_coalesced) {
            throw 'the Write performance diagnostic did not preserve editing, width-cache, and history correctness.'
        }

        if ([int]$actual.checks.incremental_wrap_lines -gt 1 -or -not $actual.checks.lazy_width_index -or -not $actual.checks.bounded_advance_cache -or -not $actual.checks.bounded_wrap_cache -or -not $actual.checks.streaming_io -or -not $actual.checks.compact_long_line_index -or [int]$actual.checks.mixed_edit_model -lt 96) {
            throw 'the Write performance diagnostic did not preserve incremental wrapping, lazy widths, bounded caches, streaming I/O, compact long-line indexing, and mixed-edit correctness.'
        }

        if (-not $actual.checks.editor_completeness) {
            throw 'the Write diagnostic did not preserve the complete baseline editor feature set.'
        }

        if ([double]$actual.performance.maximum_edit_ms -gt 100.0 -or [double]$actual.performance.maximum_scene_build_ms -gt 100.0) {
            throw 'the Write large-file edit or scene build exceeded the 100 ms regression limit.'
        }

        if (
            [double]$actual.performance.cpu.typing.maximum_ms -gt 33.0 -or
            [double]$actual.performance.cpu.shift_selection.maximum_ms -gt 33.0 -or
            [double]$actual.performance.cpu.scroll.maximum_ms -gt 33.0 -or
            [double]$actual.performance.cpu.wrapped_typing.maximum_ms -gt 33.0 -or
            [double]$actual.performance.million_character_line.edit_maximum_ms -gt 33.0
        ) {
            throw 'the Write end-to-end CPU interaction path exceeded the 33 ms regression limit.'
        }

        if ([int]$actual.performance.undo_bytes_for_200_characters -gt 65536) {
            throw 'the Write operation history exceeded its coalesced typing memory limit.'
        }

        Write-Host 'Write large-file performance diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 8 -Compress)
        return
    }

    if ($Mode -eq 'array') {

        if (-not $actual.checks.capability_negotiation -or -not $actual.checks.cpu_fallback -or -not $actual.checks.missing_capability_fallback -or -not $actual.checks.error_gpu_retention -or -not $actual.checks.timeout_gpu_retention) {
            throw 'the Array diagnostic did not exercise managed negotiation and strict GPU recovery.'
        }

        if (-not $actual.checks.opaque_background -or -not $actual.checks.first_frame_complete -or -not $actual.checks.atkinson_baseline -or -not $actual.checks.variable_width_clipping -or -not $actual.checks.tree_clipping) {
            throw 'the Array diagnostic did not validate first-frame coverage, Atkinson placement, and clipping.'
        }

        if (-not $actual.checks.header_modes -or -not $actual.checks.tree_selection_rename -or -not $actual.checks.drag_box -or -not $actual.checks.overlay_order) {
            throw 'the Array diagnostic did not preserve header, tree, selection, rename, drag-box, and overlay rendering.'
        }

        if (-not $actual.checks.scrollbar_geometry.opaque -or [int]$actual.checks.scrollbar_geometry.vertical.Count -ne 4 -or [int]$actual.checks.scrollbar_geometry.horizontal.Count -ne 4) {
            throw 'the Array diagnostic did not preserve both opaque scrollbar geometries.'
        }

        if (-not $actual.checks.permission_status -or -not $actual.checks.permission_checks.denied -or -not $actual.checks.permission_checks.fail_closed -or -not $actual.checks.permission_checks.batch_preflight -or -not $actual.checks.permission_checks.history_preflight -or [int]$actual.checks.permission_checks.checked_paths -ne 2) {
            throw 'the Array diagnostic did not preserve Architect denial feedback and fail-closed path checks.'
        }

        if ([int]$actual.checks.outlined_panels.status -ne 4 -or [int]$actual.checks.outlined_panels.context -ne 4 -or [int]$actual.checks.outlined_panels.confirm -ne 4) {
            throw 'the Array diagnostic did not preserve the status, context, and confirmation panel outlines.'
        }

        if ([int]$actual.checks.atomic_scene.messages -ne 1 -or [int]$actual.checks.atomic_scene.commands -lt 1 -or [int]$actual.checks.atomic_scene.damage -ne 1 -or [int]$actual.checks.damage_coalescing -ne 1) {
            throw 'the Array diagnostic did not submit one atomic damage-aware scene.'
        }

        if ([int]$actual.checks.command_budget.commands -ge ([int]$actual.checks.command_budget.limit * 0.75)) {
            throw 'the Array managed scene consumed too much of its command budget.'
        }

        if (Test-Path -LiteralPath $baselinePath -PathType Leaf) {

            $stored = Get-Content -LiteralPath $baselinePath -Raw | ConvertFrom-Json
            $arrayBaseline = $stored.array_1440p

            if ($null -ne $arrayBaseline) {

                if ([double]$actual.performance.average_scene_build_ms -gt ([double]$arrayBaseline.average_scene_build_ms * [double]$arrayBaseline.timing_tolerance_multiplier)) {
                    throw 'the Array managed-scene build time exceeded the stored 1440p tolerance.'
                }

                if ([double]$actual.performance.maximum_scene_build_ms -gt ([double]$arrayBaseline.maximum_scene_build_ms * [double]$arrayBaseline.timing_tolerance_multiplier)) {
                    throw 'the Array maximum managed-scene build time exceeded the stored 1440p tolerance.'
                }

                if ([int]$actual.performance.maximum_commands -gt ([int]$arrayBaseline.maximum_commands * [double]$arrayBaseline.command_tolerance_multiplier)) {
                    throw 'the Array managed-scene command count exceeded the stored 1440p tolerance.'
                }
            }
        }

        Write-Host 'Array managed graphics diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 8 -Compress)
        return
    }

    if ($Mode -eq 'operations-centre') {

        if (
            -not $actual.checks.array_palette -or
            -not $actual.checks.operations_scene -or
            -not $actual.checks.cpu_fallback -or
            -not $actual.checks.performance_graphs -or
            -not $actual.checks.gpu_performance -or
            -not $actual.checks.gpu_column -or
            -not $actual.checks.column_resize -or
            [string]$actual.checks.default_sort.column -ne 'name' -or
            [bool]$actual.checks.default_sort.descending
        ) {
            throw 'the Operations Centre diagnostic did not preserve GPU telemetry, column resizing, alphabetical operation sort, or graphics fallback.'
        }

        if ([int]$actual.checks.command_budget -ge 768) {
            throw 'the Operations Centre managed scene consumed too much of its command budget.'
        }

        Write-Host 'Operations Centre managed graphics diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 8 -Compress)
        return
    }

    if ($Mode -eq 'calculator') {

        if (-not $actual.checks.calculation -or -not $actual.checks.managed_scene -or -not $actual.checks.cpu_fallback -or -not $actual.checks.responsive_controls -or -not $actual.checks.t1os_palette) {
            throw 'the Calculator diagnostic did not validate arithmetic, managed rendering, CPU fallback, responsive controls, and the t1os palette.'
        }

        if ([int]$actual.checks.command_budget -ge 128) {
            throw 'the Calculator managed scene consumed too much of its command budget.'
        }

        Write-Host 'Calculator managed graphics diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 5 -Compress)
        return
    }

    if ($Mode -eq 'expanse') {

        if (-not $actual.checks.capability_negotiation -or -not $actual.checks.cpu_fallback -or -not $actual.checks.missing_capability_fallback -or -not $actual.checks.error_gpu_retention -or -not $actual.checks.timeout_gpu_retention) {
            throw 'the Expanse diagnostic did not exercise managed negotiation and strict GPU recovery.'
        }

        if ([int]$actual.checks.opaque_backgrounds -ne 7 -or -not $actual.checks.first_frame_complete -or -not $actual.checks.atkinson_baseline -or -not $actual.checks.variable_width_clipping -or [int]$actual.checks.bgra_images -lt 1 -or [int]$actual.checks.png_icons -ne 21 -or -not $actual.checks.dedicated_software_icons -or -not $actual.checks.calculator_software -or -not $actual.checks.operations_centre_software -or -not $actual.checks.png_icon_cache.hit -or [int]$actual.checks.png_icon_cache.resolution_variants -ne 2) {
            throw 'the Expanse diagnostic did not validate complete first frames, PNG masters, resolution-specific icon caching, Atkinson text, clipping, and BGRA surfaces.'
        }

        if (-not $actual.checks.desktop -or -not $actual.checks.taskbar -or -not $actual.checks.startmenu -or -not $actual.checks.tooltip -or -not $actual.checks.instancelist -or -not $actual.checks.taskmenu -or -not $actual.checks.volumebar) {
            throw 'the Expanse diagnostic did not exercise all seven managed surfaces.'
        }

        if (-not $actual.checks.surface_failure_isolation -or -not $actual.checks.damage_coalescing -or -not $actual.checks.inactive_transients_deferred) {
            throw 'the Expanse diagnostic did not isolate failures, coalesce damage, or defer inactive transient surfaces.'
        }

        foreach ($role in @('desktop', 'taskbar', 'startmenu', 'tooltip', 'instancelist', 'taskmenu', 'volumebar')) {
            if ([int]$actual.checks.atomic_scenes.$role -ne 1) {
                throw "the Expanse $role surface did not submit one atomic scene."
            }
        }

        if ([int]$actual.checks.command_budget.maximum_surface -ge ([int]$actual.checks.command_budget.surface_limit * 0.75) -or [int]$actual.checks.command_budget.aggregate -ge ([int]$actual.checks.command_budget.total_limit * 0.75)) {
            throw 'the Expanse managed surfaces consumed too much of their command budgets.'
        }

        if (-not $actual.checks.atomic_cpu_startmenu.atomic_buffer -or -not $actual.checks.atomic_cpu_startmenu.full_damage -or [int64]$actual.checks.atomic_cpu_startmenu.buffer_bytes -lt 1) {
            throw 'the Expanse diagnostic did not preserve the atomic CPU start-menu fallback.'
        }

        if ($Update) {

            $stored = Get-Content -LiteralPath $baselinePath -Raw | ConvertFrom-Json
            $expanseBaseline = [ordered]@{
                roles = $actual.performance.roles
                maximum_surface_commands = [int]$actual.performance.maximum_surface_commands
                aggregate_commands = [int]$actual.performance.aggregate_commands
                timing_tolerance_multiplier = 2.0
                command_tolerance_multiplier = 1.25
            }
            $stored | Add-Member -NotePropertyName expanse_1440p -NotePropertyValue $expanseBaseline -Force
            $stored | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $baselinePath -Encoding utf8
            Write-Host "updated the Expanse 1440p baseline at $baselinePath."
        }
        elseif (Test-Path -LiteralPath $baselinePath -PathType Leaf) {

            $stored = Get-Content -LiteralPath $baselinePath -Raw | ConvertFrom-Json
            $expanseBaseline = $stored.expanse_1440p

            if ($null -ne $expanseBaseline) {

                foreach ($property in $actual.performance.roles.PSObject.Properties) {

                    $role = $property.Name
                    $measured = $property.Value
                    $baseline = $expanseBaseline.roles.$role

                    if ($null -eq $baseline) {
                        throw "the Expanse baseline is missing the $role surface."
                    }

                    $averageLimit = [Math]::Max(0.25, [double]$baseline.average_scene_build_ms * [double]$expanseBaseline.timing_tolerance_multiplier)
                    $maximumLimit = [Math]::Max(0.5, [double]$baseline.maximum_scene_build_ms * [double]$expanseBaseline.timing_tolerance_multiplier)

                    if ([double]$measured.average_scene_build_ms -gt $averageLimit) {
                        throw "the Expanse $role average scene-build time exceeded its stored 1440p tolerance."
                    }

                    if ([double]$measured.maximum_scene_build_ms -gt $maximumLimit) {
                        throw "the Expanse $role maximum scene-build time exceeded its stored 1440p tolerance."
                    }

                    if ([int]$measured.maximum_commands -gt ([int]$baseline.maximum_commands * [double]$expanseBaseline.command_tolerance_multiplier)) {
                        throw "the Expanse $role command count exceeded its stored 1440p tolerance."
                    }
                }

                if ([int]$actual.performance.maximum_surface_commands -gt ([int]$expanseBaseline.maximum_surface_commands * [double]$expanseBaseline.command_tolerance_multiplier) -or [int]$actual.performance.aggregate_commands -gt ([int]$expanseBaseline.aggregate_commands * [double]$expanseBaseline.command_tolerance_multiplier)) {
                    throw 'the Expanse aggregate managed command count exceeded its stored 1440p tolerance.'
                }
            }
        }

        Write-Host 'Expanse managed graphics diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 12 -Compress)
        return
    }

    if ($Mode -in @('startup', 'lockscreen', 'boot')) {

        if (-not $actual.checks.capability_negotiation -or -not $actual.checks.cpu_fallback -or -not $actual.checks.missing_capability_fallback -or -not $actual.checks.error_gpu_retention -or -not $actual.checks.timeout_gpu_retention) {
            throw "the $Mode diagnostic did not exercise managed negotiation and strict GPU recovery."
        }

        if (-not $actual.checks.opaque_background -or -not $actual.checks.first_frame_complete -or -not $actual.checks.first_frame_before_map) {
            throw "the $Mode diagnostic did not validate its complete opaque first frame."
        }

        if ([int]$actual.checks.atomic_scene.messages -ne 1 -or [int]$actual.checks.atomic_scene.commands -lt 1 -or [int]$actual.checks.atomic_scene.damage -lt 1) {
            throw "the $Mode diagnostic did not submit one atomic damage-aware scene."
        }

        if ([int]$actual.checks.command_budget.commands -ge ([int]$actual.checks.command_budget.limit * 0.75)) {
            throw "the $Mode managed scene consumed too much of its command budget."
        }

        if ($Mode -eq 'startup') {

            if (-not $actual.checks.setup_flow -or -not $actual.checks.login_flow -or -not $actual.checks.masked_passwords -or -not $actual.checks.authentication_material_absent -or -not $actual.checks.resize_reconstruction -or -not $actual.checks.typography_roles -or -not $actual.checks.animation_pacing -or -not $actual.checks.animation_ack_pump -or [int]$actual.checks.managed_dirty_rect.Count -ne 4) {
                throw 'the Startup diagnostic did not preserve setup, login, password safety, resize, typography, managed dirty rectangles, and refresh-paced acknowledgement-driven animation.'
            }
        }

        if ($Mode -eq 'lockscreen') {

            if (-not $actual.checks.time_date_layout -or -not $actual.checks.direct_framebuffer_fallback -or -not $actual.checks.cambria_baseline) {
                throw 'the Lock Screen diagnostic did not preserve time/date layout, Cambria, and direct-framebuffer fallback.'
            }
        }

        if ($Mode -eq 'boot') {

            if (-not $actual.checks.title_fade -or -not $actual.checks.title_fade_pacing -or [int]$actual.checks.dot_frames.Count -ne 3 -or -not $actual.checks.final_black -or -not $actual.checks.final_commit_before_unmap -or -not $actual.checks.cursor_finally_restore) {
                throw 'the Boot Animation diagnostic did not preserve its refresh-paced fade, animation phases, and teardown lifecycle.'
            }
        }

        $baselineName = "${Mode}_1440p"

        if ($Update) {

            $stored = Get-Content -LiteralPath $baselinePath -Raw | ConvertFrom-Json
            $applicationBaseline = [ordered]@{
                average_scene_build_ms = [double]$actual.performance.average_scene_build_ms
                maximum_scene_build_ms = [double]$actual.performance.maximum_scene_build_ms
                maximum_commands = [int]$actual.performance.maximum_commands
                timing_tolerance_multiplier = 2.0
                command_tolerance_multiplier = 1.25
            }
            $stored | Add-Member -NotePropertyName $baselineName -NotePropertyValue $applicationBaseline -Force
            $stored | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $baselinePath -Encoding utf8
            Write-Host "updated the $Mode 1440p baseline at $baselinePath."
        }
        elseif (Test-Path -LiteralPath $baselinePath -PathType Leaf) {

            $stored = Get-Content -LiteralPath $baselinePath -Raw | ConvertFrom-Json
            $property = $stored.PSObject.Properties[$baselineName]

            if ($null -eq $property) {
                throw "the graphics baseline is missing $baselineName."
            }

            $applicationBaseline = $property.Value
            $averageLimit = [Math]::Max(0.25, [double]$applicationBaseline.average_scene_build_ms * [double]$applicationBaseline.timing_tolerance_multiplier)
            $maximumLimit = [Math]::Max(0.5, [double]$applicationBaseline.maximum_scene_build_ms * [double]$applicationBaseline.timing_tolerance_multiplier)

            if ([double]$actual.performance.average_scene_build_ms -gt $averageLimit) {
                throw "the $Mode average managed-scene build time exceeded its stored 1440p tolerance."
            }

            if ([double]$actual.performance.maximum_scene_build_ms -gt $maximumLimit) {
                throw "the $Mode maximum managed-scene build time exceeded its stored 1440p tolerance."
            }

            if ([int]$actual.performance.maximum_commands -gt ([int]$applicationBaseline.maximum_commands * [double]$applicationBaseline.command_tolerance_multiplier)) {
                throw "the $Mode managed-scene command count exceeded its stored 1440p tolerance."
            }
        }

        Write-Host "$Mode managed graphics diagnostic passed."
        Write-Host ($actual | ConvertTo-Json -Depth 10 -Compress)
        return
    }

    if ($Update) {
        Write-Host "updating graphics baseline at $baselinePath..."

        if (Test-Path -LiteralPath $baselinePath -PathType Leaf) {

            try {
                $previous = Get-Content -LiteralPath $baselinePath -Raw | ConvertFrom-Json

                if ($null -ne $previous.compositor_1440p) {
                    $actual | Add-Member -NotePropertyName compositor_1440p -NotePropertyValue $previous.compositor_1440p -Force
                }

                if ($null -ne $previous.brick_1440p) {
                    $actual | Add-Member -NotePropertyName brick_1440p -NotePropertyValue $previous.brick_1440p -Force
                }

                if ($null -ne $previous.write_1440p) {
                    $actual | Add-Member -NotePropertyName write_1440p -NotePropertyValue $previous.write_1440p -Force
                }

                if ($null -ne $previous.array_1440p) {
                    $actual | Add-Member -NotePropertyName array_1440p -NotePropertyValue $previous.array_1440p -Force
                }

                if ($null -ne $previous.expanse_1440p) {
                    $actual | Add-Member -NotePropertyName expanse_1440p -NotePropertyValue $previous.expanse_1440p -Force
                }

                if ($null -ne $previous.startup_1440p) {
                    $actual | Add-Member -NotePropertyName startup_1440p -NotePropertyValue $previous.startup_1440p -Force
                }

                if ($null -ne $previous.lockscreen_1440p) {
                    $actual | Add-Member -NotePropertyName lockscreen_1440p -NotePropertyValue $previous.lockscreen_1440p -Force
                }

                if ($null -ne $previous.boot_1440p) {
                    $actual | Add-Member -NotePropertyName boot_1440p -NotePropertyValue $previous.boot_1440p -Force
                }
            }
            catch {
                Write-Warning 'the existing compositor baseline could not be preserved.'
            }
        }

        $actual | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $baselinePath -Encoding utf8

        Write-Host 'graphics baseline updated successfully.'
        return
    }

    if (-not (Test-Path -LiteralPath $baselinePath -PathType Leaf)) {
        throw "graphics baseline file not found: $baselinePath"
    }

    try {
        $expected = Get-Content -LiteralPath $baselinePath -Raw | ConvertFrom-Json
    }
    catch {
        throw "could not read graphics baseline file: $baselinePath"
    }

    $actualContract = $actual.contract | ConvertTo-Json -Depth 20 -Compress
    $expectedContract = $expected.contract | ConvertTo-Json -Depth 20 -Compress

    if ($actualContract -cne $expectedContract) {
        Write-Host 'expected graphics contract:'
        Write-Host $expectedContract
        Write-Host 'actual graphics contract:'
        Write-Host $actualContract
        throw 'graphics baseline contract changed.'
    }

    Write-Host 'graphics baseline passed.'
    Write-Host ($actual.metrics | ConvertTo-Json -Depth 5 -Compress)
}


Write-Host "checking that storage is not mounted..."

$mounted = Test-T1OSDiskMounted

if ($mounted) {
    Write-Host ""
    Write-Host "t1fs is mounted. running unmount..."

    $unmountScript = Join-Path $projectRoot 'scripts/deployment/unmount.ps1'

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


Invoke-GraphicsBaseline -Update ([bool]$Update) -Mode $Mode -UseDeployed ([bool]$Deployed)

Write-Host 'Runtime graphics validation passed.'
