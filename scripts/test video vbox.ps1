[CmdletBinding()]
param(
    [string]$VmName = 'The One OS',
    [string]$Username = 'development',
    [string]$Password = 'password',
    [string]$Fixture = '/master/videos/video-pipeline-test.mp4',
    [int]$Width = 1280,
    [int]$Height = 720,
    [int]$BootTimeoutSeconds = 90,
    [int]$MinimumPresentedFrames = 200,
    [double]$MaximumDropPercent = 2.0,
    [double]$MaximumP95DriftMs = 50.0,
    [double]$MaximumDriftMs = 100.0,
    [string]$EvidenceRoot,
    [switch]$InitialSetup
)

$incrementalTestBootstrap = Join-Path $PSScriptRoot 'incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$environmentRoot = Join-Path $projectRoot 'environment'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outputRoot = if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
    Join-Path $environmentRoot "video-vbox-$timestamp"
}
else {
    [System.IO.Path]::GetFullPath($EvidenceRoot)
}
$runtimeRaw = Join-Path $outputRoot 'runtime.raw'
$mountPoint = '/mnt/t1os-video-test'
$checks = [ordered]@{}
$errors = [System.Collections.Generic.List[string]]::new()
$telemetry = $null
$playerLog = ''
$mediaLog = ''
$windowLog = ''
$videoProbe = $null
$runtimeMounted = $false
$started = $false

New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

$vboxCommand = Get-Command VBoxManage -ErrorAction SilentlyContinue
$vbox = if ($vboxCommand) {
    $vboxCommand.Source
}
else {
    'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
}

if (-not (Test-Path -LiteralPath $vbox -PathType Leaf)) {
    throw 'VBoxManage was not found.'
}

Add-Type -AssemblyName System.Drawing

function Invoke-VBox {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments,
        [switch]$Quiet
    )

    if ($Quiet) {
        & $script:vbox @Arguments *> $null
    }
    else {
        & $script:vbox @Arguments
    }

    if ($LASTEXITCODE -ne 0) {
        throw "VBoxManage $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

function Get-VmState {
    $line = & $script:vbox showvminfo $VmName --machinereadable 2>$null |
        Where-Object { $_ -match '^VMState=' } |
        Select-Object -First 1

    if (-not $line) {
        return 'missing'
    }

    return ([string]$line).Split('=', 2)[1].Trim('"')
}

function Wait-VmState {
    param(
        [Parameter(Mandatory)]
        [string[]]$State,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    do {
        $current = Get-VmState

        if ($current -in $State) {
            return $current
        }

        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    throw "VirtualBox VM did not reach $($State -join ', ') within $TimeoutSeconds seconds; current state is $current."
}

function Send-ScanCodes {
    param([Parameter(Mandatory)][string[]]$Codes)

    Invoke-VBox -Arguments (@('controlvm', $VmName, 'keyboardputscancode') + $Codes) -Quiet
}

function Send-Key {
    param([Parameter(Mandatory)][string]$ScanCode)

    $released = '{0:x2}' -f (([Convert]::ToInt32($ScanCode, 16) + 0x80) -band 0xff)
    Send-ScanCodes -Codes @($ScanCode, $released)
}

function Send-WinShortcut {
    param([Parameter(Mandatory)][string]$ScanCode)

    $released = '{0:x2}' -f (([Convert]::ToInt32($ScanCode, 16) + 0x80) -band 0xff)
    Send-ScanCodes -Codes @('e0', '5b', $ScanCode, $released, 'e0', 'db')
}

function Send-Text {
    param([Parameter(Mandatory)][string]$Text)

    # VirtualBox can overrun a guest application's keyboard queue when a long
    # command is injected as one burst while the VM is busy.  Pace bounded
    # chunks so diagnostic and launch commands arrive intact.
    for ($offset = 0; $offset -lt $Text.Length; $offset += 1) {
        $length = 1
        $chunk = $Text.Substring($offset, $length)
        Invoke-VBox -Arguments @('controlvm', $VmName, 'keyboardputstring', $chunk) -Quiet
        Start-Sleep -Milliseconds 75
    }
}

function Get-ScreenshotStats {
    param([Parameter(Mandatory)][string]$Path)

    $bitmap = [System.Drawing.Bitmap]::new($Path)

    try {
        $nonBlack = 0
        $samples = 0

        for ($y = 0; $y -lt $bitmap.Height; $y += 8) {
            for ($x = 0; $x -lt $bitmap.Width; $x += 8) {
                $pixel = $bitmap.GetPixel($x, $y)
                $samples++

                if ($pixel.R -gt 8 -or $pixel.G -gt 8 -or $pixel.B -gt 8) {
                    $nonBlack++
                }
            }
        }

        return [ordered]@{
            width = $bitmap.Width
            height = $bitmap.Height
            samples = $samples
            non_black_samples = $nonBlack
            sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    finally {
        $bitmap.Dispose()
    }
}

function Capture-Stage {
    param(
        [Parameter(Mandatory)][string]$Name,
        [string]$DifferentFrom,
        [int]$TimeoutSeconds = 30
    )

    $path = Join-Path $script:outputRoot "$Name.png"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    do {
        try {
            Invoke-VBox -Arguments @('controlvm', $VmName, 'setvideomodehint', "$Width", "$Height", '32') -Quiet
            Invoke-VBox -Arguments @('controlvm', $VmName, 'screenshotpng', $path) -Quiet
        }
        catch {
            # Headless VirtualBox can briefly reject control commands while
            # firmware hands the display to vmwgfx.  This is a boot-state
            # transition, not a failed playback check, so retry within the
            # existing bounded stage deadline.
            Start-Sleep -Milliseconds 500
            continue
        }

        $stats = Get-ScreenshotStats -Path $path

        if (
            $stats.width -eq $Width -and
            $stats.height -eq $Height -and
            $stats.non_black_samples -gt 0 -and
            ([string]::IsNullOrWhiteSpace($DifferentFrom) -or $stats.sha256 -ne $DifferentFrom)
        ) {
            return $stats
        }

        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    throw "Stage '$Name' did not produce a distinct ${Width}x${Height} image."
}

function Get-AttachedVdi {
    foreach ($line in (& $script:vbox showvminfo $VmName --machinereadable)) {
        if ([string]$line -match '^"SATA-[0-9]+-[0-9]+"="(.+\.vdi)"$') {
            return ($Matches[1] -replace '\\\\', '\')
        }
    }

    throw "The VM '$VmName' has no attached VDI."
}

function Read-GuestFile {
    param([Parameter(Mandatory)][string]$GuestPath)

    $content = & wsl.exe -d Ubuntu -u root --exec sh -c 'cat "$1"' sh "$mountPoint/$GuestPath" 2>$null

    if ($LASTEXITCODE -ne 0) {
        return ''
    }

    return [string]($content -join "`n")
}

try {
    if ((Get-VmState) -ne 'poweroff') {
        throw "VirtualBox VM '$VmName' must be powered off before the video test."
    }

    Invoke-VBox -Arguments @('setextradata', $VmName, 'VBoxInternal/Devices/vga/0/Config/VMSVGAPciId', '0') -Quiet
    Invoke-VBox -Arguments @('setextradata', $VmName, 'VBoxInternal/Devices/vga/0/Config/VMSVGAPciBarLayout', '1') -Quiet

    $machine = & $vbox showvminfo $VmName --machinereadable
    $checks['vmsvga_configured'] = [bool]($machine -match '^graphicscontroller="vmsvga"$')
    $checks['three_dimensional_acceleration'] = [bool]($machine -match '^accelerate3d="on"$')
    $pciIdentity = & $vbox getextradata $VmName 'VBoxInternal/Devices/vga/0/Config/VMSVGAPciId'
    $barLayout = & $vbox getextradata $VmName 'VBoxInternal/Devices/vga/0/Config/VMSVGAPciBarLayout'
    $checks['vmsvga_video_extensions'] = [bool]($pciIdentity -match 'Value:\s*0\s*$')
    $checks['vmsvga_bar_layout'] = [bool]($barLayout -match 'Value:\s*1\s*$')

    if (
        -not $checks.vmsvga_configured -or
        -not $checks.three_dimensional_acceleration -or
        -not $checks.vmsvga_video_extensions -or
        -not $checks.vmsvga_bar_layout
    ) {
        throw 'The video test requires VMSVGA, 3D acceleration, and the T1OS VirtualBox video-command bridge.'
    }

    Invoke-VBox -Arguments @('startvm', $VmName, '--type', 'headless') -Quiet
    $started = $true
    [void](Wait-VmState -State @('running') -TimeoutSeconds 20)
    # Establish the acceptance resolution before the guest opens its KMS
    # device.  Repeatedly changing the mode while PID 1 is waiting for the
    # WindowServer handshake can force a full GBM/EGL rebuild into that
    # deliberately short readiness window.
    Invoke-VBox -Arguments @('controlvm', $VmName, 'setvideomodehint', "$Width", "$Height", '32') -Quiet
    Start-Sleep -Seconds 2

    $lock = Capture-Stage -Name '01-lock-screen' -TimeoutSeconds $BootTimeoutSeconds
    Send-Key -ScanCode '39'

    if ($InitialSetup) {
        # The first-run welcome is intentionally animated before it begins
        # accepting account input.  Wait for that sequence to finish so text
        # cannot be consumed by the title screen.
        Start-Sleep -Seconds 15
        $login = Capture-Stage -Name '02-initial-setup' -DifferentFrom $lock.sha256
        Send-Text -Text $Username
        Send-Key -ScanCode '1c'
        Start-Sleep -Seconds 1
        Send-Text -Text $Password
        Send-Key -ScanCode '1c'
        Start-Sleep -Seconds 1
        Send-Text -Text $Password
        Send-Key -ScanCode '1c'
        Start-Sleep -Seconds 7
    }
    else {
        Start-Sleep -Seconds 2
        $login = Capture-Stage -Name '02-login' -DifferentFrom $lock.sha256
        Send-Text -Text $Password
        Send-Key -ScanCode '1c'
        Start-Sleep -Seconds 5
    }

    $desktop = Capture-Stage -Name '03-desktop' -DifferentFrom $login.sha256 -TimeoutSeconds 50

    Send-WinShortcut -ScanCode '30'
    Start-Sleep -Seconds 3
    $brick = Capture-Stage -Name '04-brick' -DifferentFrom $desktop.sha256
    Send-Text -Text 'run /the one/build/media/media.py video-probe H264'
    Send-Key -ScanCode '1c'
    Start-Sleep -Seconds 8
    Send-Text -Text "run /the one/build/player/player.py $Fixture"
    Send-Key -ScanCode '1c'
    Start-Sleep -Seconds 5

    # Capture the samples unconditionally and evaluate motion below.  A
    # stalled decoder is an acceptance failure, but it must not abort the
    # guest before clean shutdown or the ext4 journal may hide the diagnostic
    # logs that explain the stall.
    $frame1 = Capture-Stage -Name '05-video-frame-1'
    Start-Sleep -Milliseconds 800
    $frame2 = Capture-Stage -Name '06-video-frame-2'
    Start-Sleep -Milliseconds 800
    $frame3 = Capture-Stage -Name '07-video-frame-3'
    $checks['changing_video_frames'] = (
        $frame1.sha256 -ne $frame2.sha256 -and
        $frame2.sha256 -ne $frame3.sha256
    )

    # Let the ten-second fixture reach its terminal state so the player can
    # persist completion, backend, zero-copy, and A/V drift telemetry.
    Start-Sleep -Seconds 12
    Send-WinShortcut -ScanCode '30'
    Start-Sleep -Seconds 2
    Send-Text -Text 'shut down'
    Send-Key -ScanCode '1c'
    [void](Wait-VmState -State @('poweroff', 'aborted') -TimeoutSeconds 90)
    $checks['clean_guest_shutdown'] = (Get-VmState) -eq 'poweroff'
}
catch {
    $errors.Add($_.Exception.Message)
}
finally {
    if ($started -and (Get-VmState) -notin @('poweroff', 'missing')) {
        try {
            Invoke-VBox -Arguments @('controlvm', $VmName, 'poweroff') -Quiet
            [void](Wait-VmState -State @('poweroff', 'aborted') -TimeoutSeconds 20)
        }
        catch {
            $errors.Add("VM cleanup failed: $($_.Exception.Message)")
        }
    }
}

try {
    $vdi = Get-AttachedVdi
    Invoke-VBox -Arguments @('clonemedium', 'disk', $vdi, $runtimeRaw, '--format', 'RAW') -Quiet
    $wslRaw = ([string](& wsl.exe --exec wslpath -a $runtimeRaw | Select-Object -First 1)).Trim()

    if ([string]::IsNullOrWhiteSpace($wslRaw)) {
        throw 'WSL could not locate the cloned runtime disk.'
    }

    & wsl.exe -d Ubuntu -u root --exec sh -c 'mkdir -p "$2"; mount -o loop,ro,noload "$1" "$2"' sh $wslRaw $mountPoint

    if ($LASTEXITCODE -ne 0) {
        throw 'The cloned runtime disk could not be mounted read-only.'
    }

    $runtimeMounted = $true
    $telemetryText = Read-GuestFile -GuestPath 'the one/logs/graphics telemetry.json'
    $playerLog = Read-GuestFile -GuestPath 'the one/logs/player.py.log'
    $mediaLog = Read-GuestFile -GuestPath 'the one/logs/media.py.log'
    $windowLog = Read-GuestFile -GuestPath 'the one/logs/windowserver.py.log'

    if ([string]::IsNullOrWhiteSpace($telemetryText)) {
        throw 'The guest did not persist graphics telemetry.'
    }

    $telemetry = $telemetryText | ConvertFrom-Json
    [System.IO.File]::WriteAllText((Join-Path $outputRoot 'graphics telemetry.json'), $telemetryText)
    [System.IO.File]::WriteAllText((Join-Path $outputRoot 'player.py.log'), $playerLog)
    [System.IO.File]::WriteAllText((Join-Path $outputRoot 'media.py.log'), $mediaLog)
    [System.IO.File]::WriteAllText((Join-Path $outputRoot 'windowserver.py.log'), $windowLog)

    $video = $telemetry.video_telemetry
    $gpu = $telemetry.telemetry
    $surfaceCapability = $telemetry.gpu_api.video_surfaces

    foreach ($line in ($mediaLog -split "\r?\n")) {
        $candidate = $line.Trim()

        if ($candidate.StartsWith('{') -and $candidate.Contains('"attempts"')) {
            try {
                $videoProbe = $candidate | ConvertFrom-Json
            }
            catch {
                # Preserve the complete raw probe log as evidence below.
            }
        }
    }

    $terminal = [regex]::Matches(
        $playerLog,
        'video playback terminal state=(?<state>\w+) backend=(?<backend>[^ ]+) hardware_decode=(?<hardware>\w+) zero_copy=(?<zero>\w+) drm_driver=(?<drm>[^ ]*) va_driver=(?<va>[^ ]*) decoded_frames=(?<decoded>\d+) submitted_frames=(?<submitted>\d+) presented_frames=(?<presented>\d+) dropped_frames=(?<dropped>\d+) compositor_dropped_frames=(?<compositor_dropped>\d+) audio_underruns=(?<underruns>\d+) maximum_av_drift_ms=(?<drift>[0-9.]+) percentile_95_av_drift_ms=(?<p95>[0-9.]+)'
    ) | Select-Object -Last 1

    $checks['vmwgfx_runtime'] = [string]$telemetry.drm_driver -eq 'vmwgfx'
    $checks['hardware_opengl'] = [string]$telemetry.backend -eq 'opengl' -and [bool]$telemetry.hardware_accelerated
    $checks['gpu_compositor'] = [string]$telemetry.window_compositor -eq 'gpu'
    $checks['dma_buf_surface_capability'] = [bool]$surfaceCapability.available -and [bool]$surfaceCapability.zero_copy
    $checks['compositor_render_node_reported'] = -not [string]::IsNullOrWhiteSpace([string]$telemetry.render_node)
    $checks['video_probe_reported'] = $null -ne $videoProbe
    $checks['video_probe_hardware_decoder'] = (
        $null -ne $videoProbe -and
        $null -ne $videoProbe.acceleration -and
        [string]$videoProbe.acceleration.backend -eq 'virtualbox-vmsvga-vaapi'
    )
    $checks['video_connection'] = [int]$video.connections -ge 1
    $checks['video_frames_submitted'] = [int]$video.frames -ge $MinimumPresentedFrames
    $checks['video_frames_presented'] = [int]$video.presented_frames -ge $MinimumPresentedFrames
    $checks['video_partial_damage'] = [int]$video.partial_damage_frames -gt 0
    $checks['video_direct_composition'] = [int]$video.direct_composition_draws -gt 0
    $checks['video_surface_imports'] = [int]$gpu.video_surface_imports -ge $MinimumPresentedFrames
    $checks['video_surface_draws'] = [int]$gpu.video_surface_draws -ge $MinimumPresentedFrames
    $checks['video_surface_releases'] = [int]$gpu.video_surface_releases -ge $MinimumPresentedFrames
    $checks['adaptive_gpu_scaling_used'] = [int]$gpu.video_surface_gpu_scaled_imports -gt 0
    $checks['dma_buf_export_mode_used'] = (
        [int]$gpu.video_surface_composed_imports -gt 0 -or
        [int]$gpu.video_surface_planar_imports -gt 0
    )
    $checks['no_video_import_failures'] = [int]$gpu.video_surface_import_failures -eq 0
    $checks['no_video_protocol_errors'] = [int]$video.protocol_errors -eq 0
    $checks['no_gpu_fallbacks'] = [int]$gpu.fallbacks -eq 0 -and -not [bool]$telemetry.gpu_failed
    $checks['player_terminal_telemetry'] = $null -ne $terminal

    if ($null -ne $terminal) {
        $checks['player_completed'] = $terminal.Groups['state'].Value -eq 'complete'
        $checks['virtualbox_hardware_decoder'] = $terminal.Groups['backend'].Value -eq 'virtualbox-vmsvga-vaapi'
        $checks['virtualbox_drm_driver'] = $terminal.Groups['drm'].Value -eq 'vmwgfx'
        $checks['virtualbox_va_driver'] = $terminal.Groups['va'].Value -eq 'vmwgfx'
        $checks['player_zero_copy'] = (
            $terminal.Groups['hardware'].Value -eq 'True' -and
            $terminal.Groups['zero'].Value -eq 'True'
        )
        $decodedFrames = [int]$terminal.Groups['decoded'].Value
        $submittedFrames = [int]$terminal.Groups['submitted'].Value
        $presentedFrames = [int]$terminal.Groups['presented'].Value
        $droppedFrames = [int]$terminal.Groups['dropped'].Value
        $dropDenominator = [Math]::Max(1, $presentedFrames + $droppedFrames)
        $dropPercent = 100.0 * $droppedFrames / $dropDenominator
        $checks['player_decoded_frames'] = $decodedFrames -ge $MinimumPresentedFrames
        $checks['player_submitted_frames'] = $submittedFrames -ge $MinimumPresentedFrames
        $checks['player_presented_frames'] = $presentedFrames -ge $MinimumPresentedFrames
        $checks['presentation_ratio'] = (
            $submittedFrames -gt 0 -and
            $presentedFrames -ge [Math]::Floor($submittedFrames * 0.95)
        )
        $checks['video_drop_rate_bounded'] = $dropPercent -le $MaximumDropPercent
        $checks['no_compositor_drops'] = [int]$terminal.Groups['compositor_dropped'].Value -eq 0
        $checks['no_audio_underruns'] = [int]$terminal.Groups['underruns'].Value -eq 0
        $checks['presented_av_drift_bounded'] = [double]$terminal.Groups['drift'].Value -le $MaximumDriftMs
        $checks['presented_p95_av_drift_bounded'] = [double]$terminal.Groups['p95'].Value -le $MaximumP95DriftMs
    }
}
catch {
    $errors.Add("Runtime evidence extraction failed: $($_.Exception.Message)")
}
finally {
    if ($runtimeMounted) {
        & wsl.exe -d Ubuntu -u root --exec umount $mountPoint *> $null
    }

    if (Test-Path -LiteralPath $runtimeRaw -PathType Leaf) {
        Remove-Item -LiteralPath $runtimeRaw -Force
    }
}

foreach ($entry in $checks.GetEnumerator()) {
    if (-not [bool]$entry.Value) {
        $errors.Add("Check failed: $($entry.Key)")
    }
}

$report = [ordered]@{
    format = 1
    passed = $errors.Count -eq 0
    vm = $VmName
    account = $Username
    initial_setup = [bool]$InitialSetup
    fixture = $Fixture
    resolution = @($Width, $Height)
    acceptance = [ordered]@{
        minimum_presented_frames = $MinimumPresentedFrames
        maximum_drop_percent = $MaximumDropPercent
        maximum_p95_drift_ms = $MaximumP95DriftMs
        maximum_drift_ms = $MaximumDriftMs
    }
    generated_at = (Get-Date).ToString('o')
    output = $outputRoot
    checks = $checks
    video_telemetry = if ($telemetry) { $telemetry.video_telemetry } else { $null }
    video_probe = $videoProbe
    gpu_video_telemetry = if ($telemetry) {
        [ordered]@{
            imports = $telemetry.telemetry.video_surface_imports
            draws = $telemetry.telemetry.video_surface_draws
            releases = $telemetry.telemetry.video_surface_releases
            import_failures = $telemetry.telemetry.video_surface_import_failures
            composed_imports = $telemetry.telemetry.video_surface_composed_imports
            planar_imports = $telemetry.telemetry.video_surface_planar_imports
            gpu_scaled_imports = $telemetry.telemetry.video_surface_gpu_scaled_imports
            modifier_imports = $telemetry.telemetry.video_surface_modifier_imports
        }
    }
    else {
        $null
    }
    errors = @($errors)
}
$reportPath = Join-Path $outputRoot 'report.json'
[System.IO.File]::WriteAllText($reportPath, ($report | ConvertTo-Json -Depth 12))

if (-not $report.passed) {
    throw "VirtualBox video pipeline failed. Evidence: $reportPath"
}

Write-Host "VirtualBox video pipeline passed. Evidence: $reportPath"
Write-Host ($report | ConvertTo-Json -Depth 12 -Compress)
