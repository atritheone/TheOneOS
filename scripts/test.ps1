# test.ps1

[CmdletBinding()]
param(
    [switch]$GraphicsBaseline,
    [switch]$UpdateGraphicsBaseline,
    [switch]$GraphicsOpenGL,
    [switch]$GraphicsCompositor,
    [switch]$GraphicsBrick,
    [switch]$GraphicsPlayer,
    [switch]$BrickDirectives,
    [switch]$GraphicsWrite,
    [switch]$WritePerformance,
    [switch]$GraphicsArray,
    [switch]$GraphicsCalculator,
    [switch]$GraphicsOperationsCentre,
    [switch]$OperationsServer,
    [switch]$GraphicsExpanse,
    [switch]$GraphicsStartup,
    [switch]$GraphicsLockscreen,
    [switch]$GraphicsBoot,
    [switch]$VirtualBoxClipboard,
    [switch]$GraphicsKms,
    [switch]$Audio,
    [switch]$Media,
    [switch]$Image,
    [switch]$OpenGL,
    [switch]$Deployed
)

$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$environmentRoot = Join-Path $projectRoot 'environment'
. (Join-Path $PSScriptRoot 'common.ps1')
Set-Location -LiteralPath $environmentRoot

function Invoke-GraphicsBaseline {
    param(
        [Parameter(Mandatory)]
        [bool]$Update,

        [ValidateSet('baseline', 'opengl', 'compositor', 'brick', 'player', 'brick-directives', 'write', 'write-performance', 'array', 'calculator', 'operations-centre', 'operations-server', 'expanse', 'startup', 'lockscreen', 'boot', 'virtualbox-clipboard')]
        [string]$Mode = 'baseline',

        [bool]$UseDeployed = $false
    )

    $mountScript = Join-Path $PSScriptRoot 'mount.ps1'
    $unmountScript = Join-Path $PSScriptRoot 'unmount.ps1'
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

        if (-not $UseDeployed -and $Mode -in @('baseline', 'opengl', 'compositor', 'player', 'write', 'write-performance', 'array', 'calculator', 'operations-centre', 'expanse', 'startup')) {
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

        if (-not $UseDeployed -and $Mode -in @('opengl', 'compositor', 'brick', 'player', 'brick-directives', 'write', 'array', 'calculator', 'operations-centre', 'expanse', 'startup', 'lockscreen', 'boot')) {
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

        if (-not $actual.checks.geometry -or -not $actual.checks.playing_scene -or -not $actual.checks.metadata_scene -or -not $actual.checks.embedded_artwork -or -not $actual.checks.metadata_worker -or -not $actual.checks.paused_scene -or -not $actual.checks.drag_preview -or -not $actual.checks.time_format -or -not $actual.checks.compact_layout -or -not $actual.checks.open_prompt -or -not $actual.checks.focus_input -or -not $actual.checks.playback_lifecycle) {
            throw 'the Player diagnostic did not validate its playback controls, states, and responsive layout.'
        }

        if (-not $actual.checks.managed_graphics -or -not $actual.checks.cpu_fallback -or -not $actual.checks.cpu_paint) {
            throw 'the Player diagnostic did not validate managed rendering and the CPU fallback.'
        }

        Write-Host 'Player managed graphics diagnostic passed.'
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

        if (-not $actual.checks.capability_negotiation -or -not $actual.checks.cpu_fallback -or -not $actual.checks.error_fallback -or -not $actual.checks.timeout_fallback) {
            throw 'the Write diagnostic did not exercise managed negotiation and every CPU fallback path.'
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

        if (-not $actual.checks.capability_negotiation -or -not $actual.checks.cpu_fallback -or -not $actual.checks.missing_capability_fallback -or -not $actual.checks.error_fallback -or -not $actual.checks.timeout_fallback) {
            throw 'the Array diagnostic did not exercise managed negotiation and every CPU fallback path.'
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
            -not $actual.checks.default_sort.descending
        ) {
            throw 'the Operations Centre diagnostic did not preserve GPU telemetry, column resizing, descending operation sort, or graphics fallback.'
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

        if (-not $actual.checks.capability_negotiation -or -not $actual.checks.cpu_fallback -or -not $actual.checks.missing_capability_fallback -or -not $actual.checks.error_fallback -or -not $actual.checks.timeout_fallback) {
            throw 'the Expanse diagnostic did not exercise managed negotiation and every CPU fallback path.'
        }

        if ([int]$actual.checks.opaque_backgrounds -ne 7 -or -not $actual.checks.first_frame_complete -or -not $actual.checks.atkinson_baseline -or -not $actual.checks.variable_width_clipping -or [int]$actual.checks.bgra_images -lt 1 -or [int]$actual.checks.png_icons -ne 20 -or -not $actual.checks.dedicated_software_icons -or -not $actual.checks.calculator_software -or -not $actual.checks.operations_centre_software -or -not $actual.checks.png_icon_cache.hit -or [int]$actual.checks.png_icon_cache.resolution_variants -ne 2) {
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

        if (-not $actual.checks.capability_negotiation -or -not $actual.checks.cpu_fallback -or -not $actual.checks.missing_capability_fallback -or -not $actual.checks.error_fallback -or -not $actual.checks.timeout_fallback) {
            throw "the $Mode diagnostic did not exercise managed negotiation and every CPU fallback path."
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

function Invoke-AudioDiagnostic {

    $mountScript = Join-Path $PSScriptRoot 'mount.ps1'
    $unmountScript = Join-Path $PSScriptRoot 'unmount.ps1'
    $buildSource = Join-Path $projectRoot 'source\build software'
    $catalogueSource = Join-Path $projectRoot 'source\catalogue\audio'
    $graphicsCatalogueSource = Join-Path $projectRoot 'source\catalogue\graphics'
    $softwareSource = Join-Path $projectRoot 'source\software\audio'
    $fixturesSource = Join-Path $projectRoot 'resource\tests\audio'
    $mediaFixturesSource = Join-Path $projectRoot 'resource\tests\media'
    $mountPoint = '/mnt/t1fs'
    $buildTarget = '/mnt/t1fs/the one/build'
    $catalogueTarget = '/mnt/t1fs/the one/catalogue/audio'
    $graphicsCatalogueTarget = '/mnt/t1fs/the one/catalogue/graphics'
    $softwareTarget = '/mnt/t1fs/the one/software/audio'
    $fixturesTarget = '/mnt/t1fs/.ephemeral/audio-tests'
    $metadataTarget = '/mnt/t1fs/.ephemeral/audio-metadata-tests'
    $mediaFixturesTarget = '/mnt/t1fs/.ephemeral/media-fixture-source'
    $mediaTarget = '/mnt/t1fs/.ephemeral/media-tests'
    $metadataPath = '/.ephemeral/audio-metadata-tests/tagged.mp3'
    $diskMounted = $false
    $buildMounted = $false
    $catalogueMounted = $false
    $graphicsCatalogueMounted = $false
    $softwareMounted = $false
    $fixturesMounted = $false
    $mediaFixturesMounted = $false
    $metadataCreated = $false
    $mediaCreated = $false
    $cleanupError = $null

    foreach ($requiredPath in @($buildSource, $catalogueSource, $graphicsCatalogueSource, $softwareSource, $fixturesSource, $mediaFixturesSource)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Container)) {
            throw "audio diagnostic source directory not found: $requiredPath"
        }
    }

    try {
        Write-Host 'mounting the T1OS image for audio diagnostics...'
        & pwsh -NoLogo -NoProfile -NonInteractive -File $mountScript | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "mount failed with exit code $LASTEXITCODE."
        }
        $diskMounted = $true

        $wslSources = @()
        foreach ($source in @($buildSource, $catalogueSource, $graphicsCatalogueSource, $softwareSource, $fixturesSource, $mediaFixturesSource)) {
            $translated = & wsl.exe --exec wslpath -a $source
            if ($LASTEXITCODE -ne 0 -or -not $translated) {
                throw "could not translate audio diagnostic path for WSL: $source"
            }
            $wslSources += ([string]($translated | Select-Object -First 1)).Trim()
        }

        & wsl.exe -u root --exec nsenter -t 1 -m -- mkdir -p $catalogueTarget $graphicsCatalogueTarget $softwareTarget $fixturesTarget $mediaFixturesTarget $mediaTarget
        if ($LASTEXITCODE -ne 0) {
            throw 'could not create audio diagnostic mount targets.'
        }

        & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslSources[0] $buildTarget
        if ($LASTEXITCODE -ne 0) { throw 'audio build bind mount failed.' }
        $buildMounted = $true

        & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslSources[1] $catalogueTarget
        if ($LASTEXITCODE -ne 0) { throw 'audio catalogue bind mount failed.' }
        $catalogueMounted = $true

        & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslSources[2] $graphicsCatalogueTarget
        if ($LASTEXITCODE -ne 0) { throw 'graphics catalogue bind mount failed.' }
        $graphicsCatalogueMounted = $true

        & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslSources[3] $softwareTarget
        if ($LASTEXITCODE -ne 0) { throw 'audio software bind mount failed.' }
        $softwareMounted = $true

        & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslSources[4] $fixturesTarget
        if ($LASTEXITCODE -ne 0) { throw 'audio fixture bind mount failed.' }
        $fixturesMounted = $true

        & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslSources[5] $mediaFixturesTarget
        if ($LASTEXITCODE -ne 0) { throw 'media fixture source bind mount failed.' }
        $mediaFixturesMounted = $true
        $mediaCreated = $true

        $python = '/the one/software/python/bin/python3.13'
        $audioApi = '/the one/build/audio/audio.py'
        $mediaApi = '/the one/build/media/media.py'
        $serverImport = "import runpy, sys; sys.path.insert(0, '/the one/build/audio'); runpy.run_path('/the one/build/audio/audioserver.py', run_name='audio_diagnostic')"
        & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B -c $serverImport
        if ($LASTEXITCODE -ne 0) {
            throw 'audio server could not load from its boot-time script path.'
        }

        $serverCheck = @'
import runpy
import sys
import json
import os
import socket
import errno

sys.path.insert(0, '/the one/build/audio')
server = runpy.run_path('/the one/build/audio/audioserver.py', run_name='audio_engine_diagnostic')
realtek = {
    'card': 3,
    'codecs': [{'name': 'Realtek ALC897', 'vendor_id': '10ec0897', 'subsystem_id': '1462ee26'}],
    'usb': '',
}
soundblaster = {
    'card': 1,
    'codecs': [{'name': 'Realtek ALC899', 'vendor_id': '10ec0899', 'subsystem_id': '11020041'}],
    'usb': '',
}
hdmi = {
    'card': 0,
    'codecs': [{'name': 'NVIDIA HDMI', 'vendor_id': '10de00a5', 'subsystem_id': ''}],
    'usb': '',
}
assert server['pcmnumbers']('/the one/drivers/nodes/snd/pcmC3D0p') == (3, 0)
assert server['pcmpreferencekey']('pcmC3D0p', '10ec0897', realtek) < server['pcmpreferencekey']('pcmC1D0p', '10ec0897', soundblaster)
assert server['pcmpreferencekey']('pcmC3D0p', '10ec0897', realtek) < server['pcmpreferencekey']('pcmC0D3p', '10ec0897', hdmi)
assert server['pcmpreferencekey']('pcmC3D0p', None, realtek) < server['pcmpreferencekey']('pcmC1D0p', None, soundblaster)
server['ALSACARDINFO'][3] = realtek
assert server['pcmcandidatediagnostic']('pcmC3D0p', None)['rank'] == 5
assert server['calibratedmastergain'](0.0) == 0.0
assert abs(server['calibratedmastergain'](0.20) - (0.20 * 0.90 / 0.28)) < 0.000001
assert abs(server['calibratedmastergain'](0.28) - 0.90) < 0.000001
assert server['calibratedmastergain'](1.0) == 1.0

engine = server['alsactlpath'].__globals__
assert engine['ctypes'].sizeof(engine['sndctleminfo']) == 272
assert engine['ctypes'].sizeof(engine['sndctlemvalue']) == 1224
assert engine['ctypes'].sizeof(engine['sndctlemlist']) == 80
originalischardev = engine['ischardev']
engine['ischardev'] = lambda path: str(path).endswith('/controlC3')
assert server['alsactlpath']('/the one/drivers/nodes/snd', 'pcmC3D0p').endswith('/controlC3')
engine['ischardev'] = originalischardev

originalioctl = engine['fcntl'].ioctl
writes = []
currenttype = [None]
def mixerioctl(fd, request, obj, *args):
    if isinstance(obj, engine['sndctleminfo']):
        assert obj.id.iface == 2
        name = bytes(obj.id.name).split(b'\x00', 1)[0].decode('ascii')
        obj.type = 3 if name == 'Auto-Mute Mode' else (1 if name.endswith('Switch') else 2)
        obj.count = 2
        obj.value.integer.min = 0
        obj.value.integer.max = 100
        currenttype[0] = obj.type
        return 0
    if isinstance(obj, engine['sndctlemvalue']):
        if currenttype[0] == 1:
            values = obj.value.boolean
        elif currenttype[0] == 2:
            values = obj.value.integer
        else:
            values = obj.value.enumerated
        writes.append([int(values[0]), int(values[1])])
        return 0
    raise AssertionError(type(obj))
engine['fcntl'].ioctl = mixerioctl
assert server['alsasetbyname'](1, 'Front Playback Volume', 0.5)
assert writes[-1] == [50, 50]
assert server['alsasetbyname'](1, 'Front Playback Switch', 1)
assert writes[-1] == [1, 1]
assert server['alsasetbyname'](1, 'Auto-Mute Mode', 0)
assert writes[-1] == [0, 0]
engine['fcntl'].ioctl = originalioctl

setuprequests = []
startthresholds = []
def setupioctl(fd, request, obj, *args):
    setuprequests.append(request)
    if isinstance(obj, engine['snd_pcm_sw_params']):
        startthresholds.append(int(obj.start_threshold))
    return 0
engine['fcntl'].ioctl = setupioctl
originalserverlog = engine['log']
engine['log'] = lambda text: None
setupinfo = server['alsasetup'](9, 48000, 2, 480, 's16le')
assert setupinfo['samplerate'] == 48000
assert setupinfo['channels'] == 2
assert startthresholds == [1440]
assert engine['io']('A', 0x40) in setuprequests
assert engine['io']('A', 0x42) not in setuprequests
engine['log'] = originalserverlog
engine['fcntl'].ioctl = originalioctl

stream = {
    'id': 1,
    'fd': 1,
    'alive': True,
    'closing': False,
    'started': True,
    'paused': True,
    'state': 'paused',
    'rb': server['rbnew'](server['FRAMEBYTES'] * 960),
    'gain': 1.0,
    'mute': False,
    'inbytes': 0,
    'outbytes': 0,
    'presentedframes': 0,
    'segments': [],
    'format': {'samplerate': 48000, 'channels': 2, 'format': 's16le'},
    'underruns': 0,
}
assert server['rbpush'](stream['rb'], b'\x01\x00\x01\x00' * 480)
server['STREAMS'].clear()
server['STREAMS'][1] = stream
queued = server['rbavail'](stream['rb'])
assert server['mixcollectframes'](480) == []
assert server['rbavail'](stream['rb']) == queued
stream['paused'] = False
stream['state'] = 'playing'
assert len(server['mixcollectframes'](480)) == 1
assert server['rbavail'](stream['rb']) == 0
assert server['rbpush'](stream['rb'], b'\x01\x00\x01\x00' * 480)
stream['mute'] = True
beforemutedoutput = stream['outbytes']
assert server['mixcollectframes'](480) == []
assert server['rbavail'](stream['rb']) == 0
assert stream['outbytes'] == beforemutedoutput + (480 * server['FRAMEBYTES'])
stream['mute'] = False

clock = [0.0]
engine = server['mixloop'].__globals__
originalbackendwrite = engine['backendwrite']
engine['time'].monotonic = lambda: clock[0]
engine['BACKEND'] = {
    'type': 'hda',
    'hda': {'samplerate': 44100, 'channels': 2, 'format': 's16le'},
}
engine['MIXFRAMES'] = 441
engine['LASTMIX'] = 0.0
engine['MIXEDFRAMES'] = 0
engine['BACKENDPRESENTEDFRAMES'] = 0
engine['XRUNS'] = 0
engine['LASTSTATLOG'] = 0.0
engine['mixonceframes'] = lambda frames, timelineframe=None: b'\x00' * (frames * engine['FRAMEBYTES'])
engine['backendwrite'] = lambda pcm: True
engine['log'] = lambda text: None
engine['mixloop']()
baseline = engine['MIXEDFRAMES']
for tick in range(1, 51):
    clock[0] = tick * 0.02
    engine['mixloop']()
assert engine['MIXEDFRAMES'] - baseline == 44100
assert engine['XRUNS'] == 0
assert engine['backendsamplerate']() == 44100
assert engine['streamformat']({'samplerate': 44100, 'channels': 2, 'format': 's16le'})['samplerate'] == 44100

outputring = engine['rbnew'](441 * engine['FRAMEBYTES'] * 16)
originalbackendfilepump = engine['backendfilepump']
engine['BACKEND'] = {
    'type': 'file',
    'alsa': True,
    'alsainfo': {'samplerate': 44100, 'channels': 2, 'format': 's16le'},
    'periodframes': 441,
    'bufferframes': 1764,
    'framebytes': engine['FRAMEBYTES'],
    'outrb': outputring,
    'pending': b'',
    'outfd': None,
}
engine['LASTMIX'] = 0.0
engine['MIXEDFRAMES'] = 0
engine['BACKENDPRESENTEDFRAMES'] = 0
engine['backendfilepump'] = lambda: False
engine['backendwrite'] = originalbackendwrite
engine['mixloop']()
assert engine['backendpendingframes']() == 3528
assert engine['MIXEDFRAMES'] == 3528
engine['rbpop'](outputring, 441 * engine['FRAMEBYTES'])
clock[0] += 0.02
engine['mixloop']()
assert engine['MIXEDFRAMES'] == 3969
assert engine['backendpresentedframes']() == 441

engine['backendfilepump'] = originalbackendfilepump
recoveryring = engine['rbnew'](480 * engine['FRAMEBYTES'] * 4)
assert engine['rbpush'](recoveryring, b'\x01\x00\x01\x00' * 480)
engine['BACKEND'] = {
    'type': 'file',
    'alsa': True,
    'periodframes': 480,
    'bufferframes': 1920,
    'framebytes': engine['FRAMEBYTES'],
    'outrb': recoveryring,
    'pending': b'',
    'outfd': 9,
    'outpath': '/test/pcmC1D0p',
    'ready': True,
    'recoveries': 0,
}
engine['BACKENDERRS'] = 0
engine['BACKENDWRITES'] = 0
engine['BACKENDBYTES'] = 0
engine['XRUNS'] = 0
originalalsadelay = engine['alsadelay']
originaloswrite = engine['os'].write
originalioctl = engine['fcntl'].ioctl
writesfailed = [False]
def recoveringwrite(fd, data):
    if not writesfailed[0]:
        writesfailed[0] = True
        raise OSError(errno.EPIPE, 'simulated playback underrun')
    return len(data)
engine['alsadelay'] = lambda fd: 0
engine['os'].write = recoveringwrite
engine['fcntl'].ioctl = lambda fd, request, obj, *args: 0
engine['log'] = lambda text: None
assert not engine['backendfilepump']()
assert engine['BACKEND']['recoveries'] == 1
assert engine['XRUNS'] == 1
assert engine['BACKENDERRS'] == 1
assert len(engine['BACKEND']['pending']) == 480 * engine['FRAMEBYTES']
assert engine['backendfilepump']()
assert engine['BACKEND']['pending'] == b''
assert engine['BACKENDWRITES'] == 1
assert engine['BACKENDBYTES'] == 480 * engine['FRAMEBYTES']
engine['alsadelay'] = originalalsadelay
engine['os'].write = originaloswrite
engine['fcntl'].ioctl = originalioctl

engine['BACKEND'] = {}
engine['MIXEDFRAMES'] = 350
engine['BACKENDPRESENTEDFRAMES'] = 0
presented = {
    'outbytes': 400 * engine['FRAMEBYTES'],
    'presentedframes': 0,
    'segments': [[100, 500, 0]],
}
assert engine['streampresentedframes'](presented) == 250
assert engine['streamstatusdata'](dict(presented, id=2, state='playing'))['presented_bytes'] == 250 * engine['FRAMEBYTES']

decoder = engine['audioapi'].decodercommand('/tmp/test.flac', samplerate=44100)
rateindex = decoder.index('-ar')
assert decoder[rateindex + 1] == '44100'

controller = engine['audioapi'].PlaybackController()
sender = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
try:
    for payload in (
        {'command': 'pause'},
        {'command': 'resume'},
        {'command': 'mute', 'muted': True},
        {'command': 'seek', 'position': 2.5},
        {'command': 'stop'},
    ):
        sender.sendto(json.dumps(payload).encode('utf-8'), controller.path)
    controller.poll()
    assert controller.paused is False
    assert controller.muted is True
    assert controller.takeseek() == 2.5
    assert controller.stopped is True
finally:
    sender.close()
    controller.close()

controlpath = '/.ephemeral/audio/control-helper-test.sock'
receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
try:
    if os.path.exists(controlpath):
        os.unlink(controlpath)
    receiver.bind(controlpath)
    receiver.settimeout(1.0)
    commands = (
        ('pause', None, {'command': 'pause'}),
        ('resume', None, {'command': 'resume'}),
        ('mute', None, {'command': 'mute', 'muted': True}),
        ('seek', 4.25, {'command': 'seek', 'position': 4.25}),
        ('stop', None, {'command': 'stop'}),
    )
    for command, position, expected in commands:
        assert engine['audioapi'].sendcontrol(
            controlpath,
            command,
            position=position,
            muted=True if command == 'mute' else None,
        )
        actual = json.loads(receiver.recv(4096).decode('utf-8'))
        assert actual == expected
    assert not engine['audioapi'].sendcontrol(controlpath, 'unknown')
    assert not engine['audioapi'].sendcontrol(controlpath, 'seek', position=-1.0)
finally:
    receiver.close()
    try:
        os.unlink(controlpath)
    except Exception:
        pass
print('audio engine timing and pause diagnostics passed.')
'@
        & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B -c $serverCheck
        if ($LASTEXITCODE -ne 0) {
            throw 'audio engine timing or pause diagnostic failed.'
        }

        $brickCheck = @'
import json
import os
import runpy
import socket
import sys

sys.path.insert(0, '/the one/build')
brick = runpy.run_path('/the one/build/brick/brick.py', run_name='brick_audio_diagnostic')
brick['gfx']._xres = 900
brick['gfx']._yres = 600
brick['applyuiscale'](900, 600)
brick['measurements']()
playback = brick['PLAYBACK']
playback.update({
    'id': 77,
    'state': 'playing',
    'position': 30.0,
    'duration': 120.0,
    'control': '/.ephemeral/audio/test.sock',
})
brick['playbackappend'](77)
geometry = brick['playbackgeometry']()
assert geometry['track'][2] > 20
assert geometry['track'][2] < 450
assert geometry['thumb'][0] > geometry['track'][0]
playbackindex = brick['playbacklineindex']()
layout = brick['contentlayout']()
assert geometry['y'] == layout['y0'] + ((playbackindex - layout['start']) * brick['LINEHEIGHT'])
playingcommands = []
brick['graphicsbuildplayback'](playingcommands, [0, 0, 900, 600])
assert any(command.get('kind') == 'text' for command in playingcommands)
playingrects = [command for command in playingcommands if command.get('kind') == 'rectangle']
assert brick['playbackstatusline'](
    'T1OS_AUDIO_STATUS ' + json.dumps({
        'type': 'audio_status',
        'state': 'paused',
        'position': 31.0,
        'duration': 120.0,
    })
)
assert playback['state'] == 'paused'
pausedcommands = []
brick['graphicsbuildplayback'](pausedcommands, [0, 0, 900, 600])
pausedrects = [command for command in pausedcommands if command.get('kind') == 'rectangle']
assert len(playingrects) < len(pausedrects)
playback['state'] = 'stopped'
assert brick['playbacksuppressline']('> playback stopped')
assert not brick['playbacksuppressline']('> another message')
playback['state'] = 'paused'

controlpath = '/.ephemeral/audio/brick-test.sock'
try:
    if os.path.exists(controlpath):
        os.unlink(controlpath)
    receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    receiver.bind(controlpath)
    receiver.settimeout(1.0)
    playback['control'] = controlpath
    assert brick['playbackcommand']('seek', position=45.0)
    command = json.loads(receiver.recv(4096).decode('utf-8'))
    assert command == {'command': 'seek', 'position': 45.0}
finally:
    try:
        receiver.close()
    except Exception:
        pass
    try:
        os.unlink(controlpath)
    except Exception:
        pass
brick['playbackfinish'](77, '> playback complete')
assert brick['SCROLL'][playbackindex] == '> playback complete'
assert brick['STYLES'][playbackindex] is None
assert len(brick['SCROLL']) == 1

brick['SCROLL'].clear()
brick['STYLES'].clear()
playback.clear()
playback.update({
    'id': 88,
    'state': 'playing',
    'media_kind': 'video',
    'position': 1.0,
    'duration': 2.0,
    'generation': 0,
    'rows': 10,
    'control': '/.ephemeral/media/test.sock',
    'frame': {},
})
brick['playbackappend'](88, rows=10)
frameroot = '/.ephemeral/media/brick-diagnostic'
os.makedirs(frameroot, exist_ok=True)
framepath = frameroot + '/frame.bgra'
with open(framepath, 'wb') as stream:
    stream.write(bytes((0x11, 0x22, 0x33, 0xff)) * 4)
assert brick['playbackstatusline'](
    'T1OS_MEDIA_STATUS ' + json.dumps({
        'type': 'media_status',
        'state': 'playing',
        'media_kind': 'video',
        'position': 1.1,
        'duration': 2.0,
        'generation': 0,
    })
)
assert brick['playbackstatusline'](
    'T1OS_MEDIA_FRAME ' + json.dumps({
        'type': 'media_frame',
        'media_kind': 'video',
        'path': framepath,
        'width': 2,
        'height': 2,
        'pts': 1.1,
        'frame': 1,
        'generation': 0,
    })
)
videogeometry = brick['playbackgeometry']()
assert len(brick['SCROLL']) == 10
assert videogeometry['video'][3] > 0
videocommands = []
brick['graphicsbuildplayback'](videocommands, [0, 0, 900, 600])
assert any(command.get('kind') == 'image' and command.get('id') == 'playback-video' for command in videocommands)
brick['playbackfinish'](88, '> playback complete')
assert len(brick['SCROLL']) == 1 and brick['SCROLL'][0] == '> playback complete'
os.unlink(framepath)
os.rmdir(frameroot)
print('brick media control diagnostics passed.')
'@
        & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B -c $brickCheck
        if ($LASTEXITCODE -ne 0) {
            throw 'brick audio control diagnostic failed.'
        }

        & wsl.exe -u root --exec nsenter -t 1 -m -- mkdir -p $metadataTarget
        if ($LASTEXITCODE -ne 0) {
            throw 'could not create the tagged audio diagnostic directory.'
        }
        $metadataCreated = $true

        $taggedBuilder = @'
import struct
import zlib

source = '/.ephemeral/audio-tests/sample.mp3'
target = '/.ephemeral/audio-metadata-tests/tagged.mp3'


def frame(name, value):

    payload = b'\x00' + value.encode('latin-1')
    return name.encode('ascii') + struct.pack('>I', len(payload)) + b'\x00\x00' + payload


def synchsafe(value):

    return bytes(((value >> 21) & 0x7f, (value >> 14) & 0x7f, (value >> 7) & 0x7f, value & 0x7f))


def chunk(name, value):

    return struct.pack('>I', len(value)) + name + value + struct.pack('>I', zlib.crc32(name + value) & 0xffffffff)


cover = b'\x89PNG\r\n\x1a\n'
cover += chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 0))
cover += chunk(b'IDAT', zlib.compress(b'\x00\xd2\x50\x1e\x28\x46\xa0\x00\xfa\xbe\x46\xd2\x50\x1e'))
cover += chunk(b'IEND', b'')


frames = b''.join((
    frame('TIT2', 'Signal Fires'),
    frame('TPE1', 'The Diagnostics'),
    frame('TALB', 'Native Audio'),
    frame('TPE2', 'T1OS Ensemble'),
    frame('TCOM', 'Ada Signal'),
    frame('TCON', 'Electronic'),
    frame('TYER', '2026'),
    frame('TRCK', '3/12'),
    frame('TPOS', '1/2'),
))
picture = b'\x00image/png\x00\x03\x00' + cover
frames += b'APIC' + struct.pack('>I', len(picture)) + b'\x00\x00' + picture

with open(source, 'rb') as stream:

    audio = stream.read()

if audio.startswith(b'ID3') and len(audio) >= 10:

    oldsize = ((audio[6] & 0x7f) << 21) | ((audio[7] & 0x7f) << 14) | ((audio[8] & 0x7f) << 7) | (audio[9] & 0x7f)
    audio = audio[10 + oldsize:]

with open(target, 'wb') as stream:

    stream.write(b'ID3\x03\x00\x00' + synchsafe(len(frames)) + frames + audio)
'@
        & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B -c $taggedBuilder
        if ($LASTEXITCODE -ne 0) {
            throw 'could not create the tagged MP3 and embedded artwork fixture.'
        }

        $validOutput = & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B $audioApi diagnostic '/.ephemeral/audio-tests/sample.mp3' '/.ephemeral/audio-tests/sample.flac' $metadataPath
        $validExitCode = $LASTEXITCODE
        if (-not $validOutput) {
            throw 'audio diagnostic produced no output.'
        }

        $actual = ([string]($validOutput | Select-Object -Last 1)).Trim() | ConvertFrom-Json
        if ($validExitCode -ne 0 -or -not $actual.passed) {
            throw "valid audio fixtures failed: $($actual.errors -join '; ')"
        }
        if (@($actual.checks.decoded.PSObject.Properties).Count -ne 3) {
            throw 'audio diagnostic did not decode MP3, FLAC, and tagged MP3 fixtures.'
        }

        $taggedInfo = @($actual.checks.metadata.PSObject.Properties | Where-Object Name -EQ $metadataPath | Select-Object -ExpandProperty Value)
        $taggedArtwork = @($actual.checks.artworks.PSObject.Properties | Where-Object Name -EQ $metadataPath | Select-Object -ExpandProperty Value)
        if (-not $actual.checks.metadata_parser -or $taggedInfo.Count -ne 1 -or $taggedInfo[0].tags.title -ne 'Signal Fires' -or $taggedInfo[0].tags.artist -ne 'The Diagnostics' -or $taggedInfo[0].tags.album -ne 'Native Audio' -or -not $taggedInfo[0].artwork -or $taggedArtwork.Count -ne 1 -or [int]$taggedArtwork[0] -lt 8) {
            throw 'audio diagnostic did not preserve tags, stream information, and embedded artwork.'
        }

        $player = '/the one/build/player/player.py'
        $playerOutput = & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B $player metadata-diagnostic $metadataPath 2>&1
        $playerExitCode = $LASTEXITCODE
        if (-not $playerOutput) {
            throw 'Player metadata diagnostic produced no output.'
        }

        $playerActual = ([string]($playerOutput | Select-Object -Last 1)).Trim() | ConvertFrom-Json
        if ($playerExitCode -ne 0 -or -not $playerActual.passed -or -not $playerActual.checks.scene -or $playerActual.checks.metadata.title -ne 'Signal Fires' -or $playerActual.checks.metadata.artist -ne 'The Diagnostics' -or $playerActual.checks.metadata.album -ne 'Native Audio' -or $playerActual.checks.artwork.surface.Count -ne 2) {
            throw "Player metadata diagnostic failed: $($playerActual.errors -join '; ')"
        }

        & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B '/.ephemeral/media-fixture-source/build.py' '/.ephemeral/media-tests'
        if ($LASTEXITCODE -ne 0) {
            throw 'could not generate deterministic media fixtures.'
        }

        $mediaAudioVideo = '/.ephemeral/media-tests/sample audio video.avi'
        $mediaVideoOnly = '/.ephemeral/media-tests/sample video only.avi'
        $mediaOutput = & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B $mediaApi diagnostic $mediaAudioVideo $mediaVideoOnly 2>&1
        $mediaExitCode = $LASTEXITCODE
        if (-not $mediaOutput) {
            throw 'media diagnostic produced no output.'
        }

        $mediaActual = ([string]($mediaOutput | Select-Object -Last 1)).Trim() | ConvertFrom-Json
        if ($mediaExitCode -ne 0 -or -not $mediaActual.passed -or -not $mediaActual.checks.decoder_optimizations -or -not $mediaActual.checks.shared_frame_ring -or -not $mediaActual.checks.probe_parser -or -not $mediaActual.checks.frame_publication -or -not $mediaActual.checks.video_only_playback -or -not $mediaActual.checks.video_controls -or -not $mediaActual.checks.audio_video_sync) {
            throw "media runtime diagnostic failed: $($mediaActual.errors -join '; ')"
        }
        if (@($mediaActual.checks.decoded.PSObject.Properties).Count -ne 2) {
            throw 'media diagnostic did not decode both generated video fixtures.'
        }

        $invalidOutput = & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B $audioApi diagnostic '/.ephemeral/audio-tests/corrupt.mp3' 2>&1
        $invalidExitCode = $LASTEXITCODE
        if (-not $invalidOutput) {
            throw 'invalid audio diagnostic produced no output.'
        }

        $invalid = ([string]($invalidOutput | Select-Object -Last 1)).Trim() | ConvertFrom-Json
        if ($invalidExitCode -eq 0 -or $invalid.passed -or $invalid.errors.Count -eq 0) {
            throw 'the decoder accepted the corrupt MP3 fixture.'
        }

        Write-Host 'audio runtime diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 8 -Compress)
        Write-Host ($playerActual | ConvertTo-Json -Depth 8 -Compress)
        Write-Host 'media runtime diagnostic passed.'
        Write-Host ($mediaActual | ConvertTo-Json -Depth 8 -Compress)
    }
    finally {
        if ($mediaCreated) {
            if ($mediaTarget -ne '/mnt/t1fs/.ephemeral/media-tests') {
                throw 'refusing to remove an unexpected media diagnostic path.'
            }
            & wsl.exe -u root --exec nsenter -t 1 -m -- rm -rf -- $mediaTarget
            if ($LASTEXITCODE -ne 0 -and -not $cleanupError) {
                $cleanupError = 'media diagnostic cleanup failed.'
            }
        }

        if ($metadataCreated) {
            if ($metadataTarget -ne '/mnt/t1fs/.ephemeral/audio-metadata-tests') {
                throw 'refusing to remove an unexpected audio metadata diagnostic path.'
            }
            & wsl.exe -u root --exec nsenter -t 1 -m -- rm -rf -- $metadataTarget
            if ($LASTEXITCODE -ne 0 -and -not $cleanupError) {
                $cleanupError = 'audio metadata diagnostic cleanup failed.'
            }
        }

        foreach ($mount in @(
            @($mediaFixturesMounted, $mediaFixturesTarget),
            @($fixturesMounted, $fixturesTarget),
            @($softwareMounted, $softwareTarget),
            @($graphicsCatalogueMounted, $graphicsCatalogueTarget),
            @($catalogueMounted, $catalogueTarget),
            @($buildMounted, $buildTarget)
        )) {
            if ($mount[0]) {
                & wsl.exe -u root --exec nsenter -t 1 -m -- umount $mount[1]
                if ($LASTEXITCODE -ne 0 -and -not $cleanupError) {
                    $cleanupError = "audio bind unmount failed for $($mount[1])."
                }
            }
        }

        if ($diskMounted) {
            & pwsh -NoLogo -NoProfile -NonInteractive -File $unmountScript | Out-Host
            if ($LASTEXITCODE -ne 0 -and -not $cleanupError) {
                $cleanupError = 'audio diagnostic image unmount failed.'
            }
        }

        if ($cleanupError) {
            throw $cleanupError
        }
    }
}

function Invoke-ImageDiagnostic {

    $mountScript = Join-Path $PSScriptRoot 'mount.ps1'
    $unmountScript = Join-Path $PSScriptRoot 'unmount.ps1'
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

function Get-GraphicsBootState {

    $mountScript = Join-Path $PSScriptRoot 'mount.ps1'
    $unmountScript = Join-Path $PSScriptRoot 'unmount.ps1'
    $mounted = $false

    try {
        & pwsh -NoLogo -NoProfile -NonInteractive -File $mountScript | Out-Host

        if ($LASTEXITCODE -ne 0) {
            throw "mount failed with exit code $LASTEXITCODE."
        }

        $mounted = $true
        $countCommand = @'
log='/mnt/t1fs/the one/logs/graphics.py.log'
ready=$(grep -Fc '> graphics OpenGL ready' "$log" 2>/dev/null || true)
present=$(grep -Fc '> graphics OpenGL present error' "$log" 2>/dev/null || true)
permission=$(grep -Fc "Permission denied: '/the one/drivers/nodes/dri/card0'" "$log" 2>/dev/null || true)
gpu_ready=$(grep -Fc '> graphics GPU window compositor ready' "$log" 2>/dev/null || true)
gpu_disabled=$(grep -Fc '> graphics GPU window compositor disabled' "$log" 2>/dev/null || true)
printf '{"ready":%s,"present_errors":%s,"permission_errors":%s,"gpu_ready":%s,"gpu_disabled":%s}\n' "$ready" "$present" "$permission" "$gpu_ready" "$gpu_disabled"
'@
        $output = & wsl.exe -d Ubuntu -u root --exec nsenter -t 1 -m -- bash -c $countCommand

        if ($LASTEXITCODE -ne 0 -or -not $output) {
            throw 'could not read the graphics boot log state.'
        }

        return ([string]($output | Select-Object -Last 1)).Trim() | ConvertFrom-Json
    }
    finally {
        if ($mounted) {
            & pwsh -NoLogo -NoProfile -NonInteractive -File $unmountScript | Out-Host

            if ($LASTEXITCODE -ne 0) {
                throw "image unmount failed with exit code $LASTEXITCODE."
            }
        }
    }
}

function Invoke-GraphicsKms {

    $qemu = 'C:\Program Files\qemu\qemu-system-x86_64.exe'

    if (-not (Test-Path -LiteralPath $qemu -PathType Leaf)) {
        throw "QEMU was not found: $qemu"
    }

    foreach ($name in @('t1osbzimage-virtualbox-0.19', 'initramfs.cpio.gz', 'storage.img')) {
        $path = Join-Path $environmentRoot $name

        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "KMS test input was not found: $path"
        }
    }

    $before = Get-GraphicsBootState
    $temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) 't1os-graphics-kms'
    $serialPath = Join-Path $temporaryRoot 'serial.log'
    $stdoutPath = Join-Path $temporaryRoot 'stdout.log'
    $stderrPath = Join-Path $temporaryRoot 'stderr.log'
    New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
    Remove-Item -LiteralPath $serialPath, $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    $arguments = @(
        '-machine', 'pc,accel=tcg',
        '-cpu', 'qemu64',
        '-m', '512M',
        '-kernel', 't1osbzimage-virtualbox-0.19',
        '-initrd', 'initramfs.cpio.gz',
        '-append', '"root=/dev/vda console=ttyS0 video=1280x720@60 vt.global_cursor_default=0"',
        '-drive', 'file=storage.img,format=raw,if=virtio',
        '-nic', 'user,model=virtio-net-pci',
        '-serial', "file:$serialPath",
        '-no-reboot',
        '-device', 'virtio-keyboard-pci',
        '-display', 'none',
        '-vga', 'virtio'
    )

    Write-Host 'booting the headless DRM/KMS regression guest...'
    $process = Start-Process -FilePath $qemu -ArgumentList $arguments -WorkingDirectory $environmentRoot -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -WindowStyle Hidden -PassThru

    try {
        if (-not $process.WaitForExit(60000)) {
            Stop-Process -Id $process.Id -Force
            $process.WaitForExit()
        }
    }
    finally {
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
        }
    }

    if (-not (Test-Path -LiteralPath $serialPath -PathType Leaf) -or (Get-Item -LiteralPath $serialPath).Length -eq 0) {
        $detail = Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue
        throw "the KMS guest produced no serial output: $detail"
    }

    $after = Get-GraphicsBootState

    if ([int]$after.ready -le [int]$before.ready) {
        throw 'the KMS guest did not append an OpenGL-ready event.'
    }

    if ([int]$after.present_errors -ne [int]$before.present_errors) {
        throw 'the KMS guest appended an OpenGL presentation error.'
    }

    if ([int]$after.permission_errors -ne [int]$before.permission_errors) {
        throw 'the KMS guest appended a DRM permission error.'
    }

    if ([int]$after.gpu_ready -le [int]$before.gpu_ready) {
        throw 'the KMS guest did not append a GPU-window-compositor-ready event.'
    }

    if ([int]$after.gpu_disabled -ne [int]$before.gpu_disabled) {
        throw 'the KMS guest disabled the GPU window compositor.'
    }

    Remove-Item -LiteralPath $serialPath, $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    Write-Host 'headless DRM/KMS regression passed.'
    Write-Host ($after | ConvertTo-Json -Compress)
}

Write-Host "checking that storage is not mounted..."

$mounted = Test-T1OSDiskMounted

if ($mounted) {
    Write-Host ""
    Write-Host "t1fs is mounted. running unmount..."

    $unmountScript = Join-Path $PSScriptRoot "unmount.ps1"

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

if ($GraphicsBaseline -or $UpdateGraphicsBaseline -or $GraphicsOpenGL -or $GraphicsCompositor -or $GraphicsBrick -or $GraphicsPlayer -or $BrickDirectives -or $GraphicsWrite -or $WritePerformance -or $GraphicsArray -or $GraphicsCalculator -or $GraphicsOperationsCentre -or $OperationsServer -or $GraphicsExpanse -or $GraphicsStartup -or $GraphicsLockscreen -or $GraphicsBoot -or $VirtualBoxClipboard) {
    $mode = if ($VirtualBoxClipboard) { 'virtualbox-clipboard' } elseif ($GraphicsBoot) { 'boot' } elseif ($GraphicsLockscreen) { 'lockscreen' } elseif ($GraphicsStartup) { 'startup' } elseif ($GraphicsExpanse) { 'expanse' } elseif ($OperationsServer) { 'operations-server' } elseif ($GraphicsOperationsCentre) { 'operations-centre' } elseif ($GraphicsCalculator) { 'calculator' } elseif ($GraphicsArray) { 'array' } elseif ($WritePerformance) { 'write-performance' } elseif ($GraphicsWrite) { 'write' } elseif ($BrickDirectives) { 'brick-directives' } elseif ($GraphicsPlayer) { 'player' } elseif ($GraphicsBrick) { 'brick' } elseif ($GraphicsCompositor) { 'compositor' } elseif ($GraphicsOpenGL) { 'opengl' } else { 'baseline' }
    Invoke-GraphicsBaseline -Update ([bool]$UpdateGraphicsBaseline) -Mode $mode -UseDeployed ([bool]$Deployed)
    exit 0
}

if ($GraphicsKms) {
    Invoke-GraphicsKms
    exit 0
}

if ($Audio -or $Media) {
    Invoke-AudioDiagnostic
    exit 0
}

if ($Image) {
    Invoke-ImageDiagnostic
    exit 0
}

$qemu = "C:\Program Files\qemu\qemu-system-x86_64.exe"

$displayDevice = @('-vga', 'virtio')
$displayBackend = 'gtk,zoom-to-fit=off,grab-on-hover=off'

if ($OpenGL) {
    $displayDevice = @('-vga', 'none', '-device', 'virtio-vga-gl')
    $displayBackend = 'gtk,gl=on,zoom-to-fit=off,grab-on-hover=off'
}

$args = @(
    "-machine", "pc,accel=whpx",
    "-cpu",     "qemu64",
    "-m",       "512M",
    "-kernel",  "t1osbzimage-virtualbox-0.19",
    "-initrd",  "initramfs.cpio.gz",
    "-append",  "root=/dev/vda console=ttyS0 video=2560x1440@60 vt.global_cursor_default=0",
    "-drive",   "file=storage.img,format=raw,if=virtio",
    "-nic",     "user,model=virtio-net-pci",
    "-serial",  "stdio",
    "-no-reboot",
	"-device", "virtio-keyboard-pci",
    "-display", $displayBackend,
	"-audiodev","dsound,id=audio0",
    "-device",  "virtio-sound-pci,audiodev=audio0"
)

$args += $displayDevice

& $qemu @args 2>&1 | Tee-Object -FilePath "qemu_debug.log"
