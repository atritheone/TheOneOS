[CmdletBinding()]
param(
    [string]$VmName = 'The One OS',
    [string]$Username = 'development',
    [string]$Password = 'password',
    [int]$Width = 2560,
    [int]$Height = 1440,
    [int]$BootTimeoutSeconds = 90,
    [int]$ActionTimeoutSeconds = 20,
    [int]$FrameSamples = 130,
    [ValidateRange(2, 64)]
    [int]$CpuCount = 4,
    [ValidateSet('hardware', 'no3d', 'cpu')]
    [string]$GraphicsMode = 'hardware',
    [string]$EvidenceRoot,
    [switch]$Matrix
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$environmentRoot = Join-Path $projectRoot 'environment'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'

if ($Matrix) {
    $matrixRoot = Join-Path $environmentRoot "graphics-matrix-$timestamp"
    New-Item -ItemType Directory -Path $matrixRoot -Force | Out-Null
    $cases = @(
        [ordered]@{ name = 'hardware-1080-class'; width = 2048; height = 1152; mode = 'hardware'; samples = 130 },
        [ordered]@{ name = 'hardware-1440p'; width = 2560; height = 1440; mode = 'hardware'; samples = 130 },
        [ordered]@{ name = 'software-opengl-1440p'; width = 2560; height = 1440; mode = 'no3d'; samples = 40 },
        [ordered]@{ name = 'cpu-compositor-1440p'; width = 2560; height = 1440; mode = 'cpu'; samples = 40 }
    )
    $caseReports = @()
    $matrixErrors = [System.Collections.Generic.List[string]]::new()

    foreach ($case in $cases) {
        $caseRoot = Join-Path $matrixRoot $case.name
        $caseLog = Join-Path $caseRoot 'run.log'
        New-Item -ItemType Directory -Path $caseRoot -Force | Out-Null
        Write-Host "running graphics matrix case $($case.name)..."
        & pwsh -NoLogo -NoProfile -NonInteractive -File $PSCommandPath `
            -VmName $VmName `
            -Username $Username `
            -Password $Password `
            -Width $case.width `
            -Height $case.height `
            -BootTimeoutSeconds $BootTimeoutSeconds `
            -ActionTimeoutSeconds $ActionTimeoutSeconds `
            -FrameSamples $case.samples `
            -CpuCount $CpuCount `
            -GraphicsMode $case.mode `
            -EvidenceRoot $caseRoot *> $caseLog
        $caseExitCode = $LASTEXITCODE
        $caseReportPath = Join-Path $caseRoot 'report.json'

        if (Test-Path -LiteralPath $caseReportPath -PathType Leaf) {
            $caseReports += Get-Content -LiteralPath $caseReportPath -Raw | ConvertFrom-Json
        }

        if ($caseExitCode -ne 0) {
            $matrixErrors.Add("$($case.name) failed with exit code $caseExitCode")
        }
    }

    $fourKRoot = Join-Path $matrixRoot 'managed-opengl-4k'
    $fourKLog = Join-Path $fourKRoot 'run.log'
    $fourKReportPath = Join-Path $fourKRoot 'report.json'
    New-Item -ItemType Directory -Path $fourKRoot -Force | Out-Null
    Write-Host 'running graphics matrix case managed-opengl-4k...'
    $fourKOutput = @(& pwsh -NoLogo -NoProfile -NonInteractive -File (Join-Path $PSScriptRoot 'test.ps1') -GraphicsCompositor 2>&1)
    $fourKExitCode = $LASTEXITCODE
    [System.IO.File]::WriteAllLines($fourKLog, [string[]]@($fourKOutput | ForEach-Object { [string]$_ }))
    $fourKJson = $fourKOutput |
        ForEach-Object { ([string]$_).Trim() } |
        Where-Object { $_.StartsWith('{') -and $_.EndsWith('}') } |
        Select-Object -Last 1
    $fourKDiagnostic = $null
    $fourKErrors = [System.Collections.Generic.List[string]]::new()

    if ([string]::IsNullOrWhiteSpace($fourKJson)) {
        $fourKErrors.Add('The compositor diagnostic did not return JSON.')
    }
    else {
        try {
            $fourKDiagnostic = $fourKJson | ConvertFrom-Json
        }
        catch {
            $fourKErrors.Add("The compositor diagnostic returned invalid JSON: $($_.Exception.Message)")
        }
    }

    if ($fourKExitCode -ne 0) {
        $fourKErrors.Add("The compositor diagnostic exited with code $fourKExitCode.")
    }

    if ($null -ne $fourKDiagnostic) {
        if (-not $fourKDiagnostic.passed) {
            $fourKErrors.Add('The compositor diagnostic reported failure.')
        }

        if (($fourKDiagnostic.checks.managed_scene_4k.resolution -join 'x') -ne '3840x2160') {
            $fourKErrors.Add('The compositor diagnostic did not validate 4K managed-scene geometry.')
        }

        if (($fourKDiagnostic.checks.opengl_framebuffer_4k.resolution -join 'x') -ne '3840x2160') {
            $fourKErrors.Add('The compositor diagnostic did not render a 4K OpenGL framebuffer.')
        }
    }

    $fourKReport = [ordered]@{
        format = 1
        passed = $fourKErrors.Count -eq 0
        graphics_mode = 'offscreen-opengl'
        resolution = @(3840, 2160)
        generated_at = (Get-Date).ToString('o')
        output = $fourKRoot
        checks = if ($null -ne $fourKDiagnostic) { $fourKDiagnostic.checks } else { @{} }
        telemetry = if ($null -ne $fourKDiagnostic) { $fourKDiagnostic.telemetry } else { $null }
        performance = if ($null -ne $fourKDiagnostic) { $fourKDiagnostic.performance } else { $null }
        errors = @($fourKErrors)
    }
    [System.IO.File]::WriteAllText($fourKReportPath, ($fourKReport | ConvertTo-Json -Depth 16))
    $caseReports += [pscustomobject]$fourKReport

    if (-not $fourKReport.passed) {
        $matrixErrors.Add('managed-opengl-4k failed')
    }

    $matrixReport = [ordered]@{
        format = 1
        passed = $matrixErrors.Count -eq 0 -and $caseReports.Count -eq ($cases.Count + 1)
        vm = $VmName
        vcpus = $CpuCount
        virtualbox_display_note = 'VirtualBox VMSVGA 7.2.4 advertises 2048x1152 as its 1080-class mode and does not expose 3840x2160 to this guest; exact 4K is tested with the compositor offscreen OpenGL framebuffer.'
        generated_at = (Get-Date).ToString('o')
        output = $matrixRoot
        cases = @($caseReports)
        errors = @($matrixErrors)
    }
    $matrixReportPath = Join-Path $matrixRoot 'report.json'
    [System.IO.File]::WriteAllText($matrixReportPath, ($matrixReport | ConvertTo-Json -Depth 16))

    if (-not $matrixReport.passed) {
        throw "VirtualBox graphics matrix failed. Evidence: $matrixReportPath"
    }

    Write-Host "VirtualBox graphics matrix passed. Evidence: $matrixReportPath"
    exit 0
}

$outputRoot = if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
    Join-Path $environmentRoot "graphics-vbox-$timestamp"
} else {
    [System.IO.Path]::GetFullPath($EvidenceRoot)
}
$mountPoint = '/mnt/t1os-vbox-test'
$stages = [ordered]@{}
$checks = [ordered]@{}
$errors = [System.Collections.Generic.List[string]]::new()
$telemetry = $null
$telemetryText = $null
$showcase = $null
$showcaseText = $null
$showcase3d = $null
$showcase3dText = $null
$runtimeRaw = Join-Path $outputRoot 'runtime.raw'
$runtimeMounted = $false
$failure = $null
$interactiveStarted = $false
$bootConfigOriginal = $null
$bootOverrideApplied = $false

New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

$vboxCommand = Get-Command VBoxManage -ErrorAction SilentlyContinue
$vbox = if ($vboxCommand) { $vboxCommand.Source } else { 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe' }

if (-not (Test-Path -LiteralPath $vbox -PathType Leaf)) {
    throw 'VBoxManage was not found. Install VirtualBox or add VBoxManage to PATH.'
}

Add-Type -AssemblyName System.Drawing

function Invoke-VBox {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments,
        [switch]$Quiet
    )

    if ($Quiet) {
        & $vbox @Arguments *> $null
    }
    else {
        & $vbox @Arguments
    }

    if ($LASTEXITCODE -ne 0) {
        throw "VBoxManage $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

function Set-CpuBootOverride {
    param(
        [Parameter(Mandatory)][bool]$Enabled,
        [switch]$Restore
    )

    $bootConfig = Join-Path $environmentRoot 'iso\boot\grub\grub.cfg'
    $bootIso = Join-Path $environmentRoot 't1os-boot.iso'
    $createIso = Join-Path $PSScriptRoot 'create iso.ps1'

    if (-not (Test-Path -LiteralPath $bootConfig -PathType Leaf)) {
        throw "Boot configuration not found: $bootConfig"
    }

    if ($null -eq $script:bootConfigOriginal) {
        $script:bootConfigOriginal = [System.IO.File]::ReadAllText($bootConfig)
    }

    $text = $script:bootConfigOriginal

    if (-not $Restore) {
        $text = [regex]::Replace(
            $text,
            'video=Virtual-1:\d+x\d+-32@60',
            "video=Virtual-1:${Width}x${Height}-32@60",
            1
        )
    }

    if ($Enabled -and -not $Restore) {
        $text = [regex]::Replace(
            $text,
            '(?m)^(\s*vt\.global_cursor_default)',
            { param($match) "        t1os.graphics=cpu \`r`n" + $match.Groups[1].Value },
            1
        )

        if ($text -notmatch 't1os\.graphics=cpu') {
            throw 'Could not add the CPU compositor boot override.'
        }
    }

    [System.IO.File]::WriteAllText($bootConfig, $text)
    Invoke-VBox -Arguments @('storageattach', $VmName, '--storagectl', 'SATA', '--port', '1', '--device', '0', '--type', 'dvddrive', '--medium', 'none') -Quiet
    & pwsh -NoLogo -NoProfile -NonInteractive -File $createIso

    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $bootIso -PathType Leaf)) {
        throw 'Could not rebuild the boot ISO for the graphics test mode.'
    }

    Invoke-VBox -Arguments @('storageattach', $VmName, '--storagectl', 'SATA', '--port', '1', '--device', '0', '--type', 'dvddrive', '--medium', $bootIso) -Quiet
    $script:bootOverrideApplied = $Enabled -and -not $Restore
}

function Get-VmState {
    $line = & $vbox showvminfo $VmName --machinereadable 2>$null | Where-Object { $_ -match '^VMState=' } | Select-Object -First 1

    if ($LASTEXITCODE -ne 0 -or -not $line) {
        $registered = & $vbox list vms 2>$null | Select-String "`"$VmName`"" -Quiet
        $running = & $vbox list runningvms 2>$null | Select-String "`"$VmName`"" -Quiet

        if ($registered -and -not $running) {
            return 'poweroff'
        }

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

    throw "VirtualBox VM did not reach state $($State -join ', ') within $TimeoutSeconds seconds; current state is $current."
}

function Start-TestVm {
    $messages = @()

    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $output = & $vbox startvm $VmName --type headless 2>&1

        if ($LASTEXITCODE -eq 0) {
            return
        }

        $messages += "attempt ${attempt}: $([string]($output -join ' '))"
        Start-Sleep -Seconds 2
    }

    throw "VirtualBox could not start the VM after three attempts. $($messages -join '; ')"
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

function Send-WinKey {
    Send-ScanCodes -Codes @('e0', '5b', 'e0', 'db')
}

function Send-Text {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Text)

    if ($Text.Length -gt 0) {
        Invoke-VBox -Arguments @('controlvm', $VmName, 'keyboardputstring', $Text) -Quiet
    }
}

function Send-SlowText {
    param(
        [Parameter(Mandatory)][AllowEmptyString()][string]$Text,
        [int]$DelayMilliseconds = 45
    )

    foreach ($character in $Text.ToCharArray()) {
        Send-Text -Text ([string]$character)
        Start-Sleep -Milliseconds $DelayMilliseconds
    }
}

function Get-ImageStats {
    param([Parameter(Mandatory)][string]$Path)

    $bitmap = [System.Drawing.Bitmap]::new($Path)

    try {
        $nonBlack = 0
        $light = 0
        $colored = 0
        $samples = 0
        $colors = [System.Collections.Generic.HashSet[int]]::new()
        $step = 8

        for ($y = 0; $y -lt $bitmap.Height; $y += $step) {
            for ($x = 0; $x -lt $bitmap.Width; $x += $step) {
                $pixel = $bitmap.GetPixel($x, $y)
                $samples++
                [void]$colors.Add($pixel.ToArgb())

                if ($pixel.R -gt 8 -or $pixel.G -gt 8 -or $pixel.B -gt 8) {
                    $nonBlack++
                }

                if ($pixel.R -gt 180 -and $pixel.G -gt 180 -and $pixel.B -gt 180) {
                    $light++
                }

                if (([Math]::Max($pixel.R, [Math]::Max($pixel.G, $pixel.B)) - [Math]::Min($pixel.R, [Math]::Min($pixel.G, $pixel.B))) -gt 20) {
                    $colored++
                }
            }
        }

        return [ordered]@{
            width = $bitmap.Width
            height = $bitmap.Height
            samples = $samples
            non_black_samples = $nonBlack
            light_samples = $light
            colored_samples = $colored
            unique_sampled_colors = $colors.Count
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
        [int]$TimeoutSeconds = $ActionTimeoutSeconds,
        [int]$StageWidth = $Width,
        [int]$StageHeight = $Height
    )

    $path = Join-Path $outputRoot "$Name.png"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = $null

    do {
        try {
            Invoke-VBox -Arguments @('controlvm', $VmName, 'setvideomodehint', "$StageWidth", "$StageHeight", '32') -Quiet
            Invoke-VBox -Arguments @('controlvm', $VmName, 'screenshotpng', $path) -Quiet
            $stats = Get-ImageStats -Path $path

            if ($stats.width -eq $StageWidth -and $stats.height -eq $StageHeight -and $stats.unique_sampled_colors -ge 2) {
                if (-not $DifferentFrom -or $stats.sha256 -ne $DifferentFrom) {
                    $stages[$Name] = $stats
                    return $stats
                }
            }

        }
        catch {
            $lastError = $_.Exception.Message
        }

        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)

    throw "Stage '$Name' did not produce a distinct ${StageWidth}x${StageHeight} screenshot within $TimeoutSeconds seconds. $lastError"
}

function Get-RightEdgeLightPixels {
    param([Parameter(Mandatory)][string]$Path)

    $bitmap = [System.Drawing.Bitmap]::new($Path)

    try {
        $count = 0

        for ($y = 0; $y -lt $bitmap.Height; $y++) {
            $pixel = $bitmap.GetPixel($bitmap.Width - 1, $y)

            if ($pixel.R -gt 220 -and $pixel.G -gt 220 -and $pixel.B -gt 220) {
                $count++
            }
        }

        return $count
    }
    finally {
        $bitmap.Dispose()
    }
}

function Get-AttachedVdi {
    $lines = & $vbox showvminfo $VmName --machinereadable

    foreach ($line in $lines) {
        if ([string]$line -match '^"SATA-[0-9]+-[0-9]+"="(.+\.vdi)"$') {
            return ($Matches[1] -replace '\\\\', '\')
        }
    }

    $fallback = Join-Path $environmentRoot 't1os-root.vdi'

    if (Test-Path -LiteralPath $fallback -PathType Leaf) {
        return $fallback
    }

    throw 'Could not locate the T1OS VDI attached to the VirtualBox VM.'
}

function Read-GuestFile {
    param([Parameter(Mandatory)][string]$GuestPath)

    $content = & wsl.exe -u root --exec sh -c 'cat "$1"' sh "$mountPoint/$GuestPath"

    if ($LASTEXITCODE -ne 0) {
        return $null
    }

    return ([string]($content -join "`n"))
}

try {
    $vmExists = & $vbox list vms | Select-String "`"$VmName`"" -Quiet

    if (-not $vmExists) {
        throw "VirtualBox VM '$VmName' is not registered. Run scripts/build vbox.ps1 first."
    }

    if ((Get-VmState) -ne 'poweroff') {
        throw "VirtualBox VM '$VmName' must be powered off before the graphics regression run."
    }

    $accelerate3d = if ($GraphicsMode -eq 'no3d') { 'off' } else { 'on' }
    Invoke-VBox -Arguments @('modifyvm', $VmName, '--cpus', [string]$CpuCount, '--paravirtprovider', 'hyperv', '--hpet', 'on', '--accelerate3d', $accelerate3d) -Quiet
    Invoke-VBox -Arguments @('setextradata', $VmName, 'VBoxInternal/Devices/vga/0/Config/VMSVGAPciId', '0') -Quiet
    Invoke-VBox -Arguments @('setextradata', $VmName, 'VBoxInternal/Devices/vga/0/Config/VMSVGAPciBarLayout', '1') -Quiet

    if ($GraphicsMode -eq 'cpu' -or $Width -ne 2560 -or $Height -ne 1440) {
    Set-CpuBootOverride -Enabled ($GraphicsMode -eq 'cpu')
    }

    $machineInfo = & $vbox showvminfo $VmName --machinereadable
    $checks['vmsvga'] = [bool]($machineInfo -match '^graphicscontroller="vmsvga"$')
    $checks['accelerate3d_mode'] = if ($GraphicsMode -eq 'no3d') {
        [bool]($machineInfo -match '^accelerate3d="off"$')
    } else {
        [bool]($machineInfo -match '^accelerate3d="on"$')
    }
    $vramLine = $machineInfo | Where-Object { $_ -match '^vram=' } | Select-Object -First 1
    $vram = if ($vramLine) { [int](([string]$vramLine).Split('=')[1]) } else { 0 }
    $cpuLine = $machineInfo | Where-Object { $_ -match '^cpus=' } | Select-Object -First 1
    $cpuCount = if ($cpuLine) { [int](([string]$cpuLine).Split('=')[1]) } else { 0 }
    $checks['vram_256mb'] = $vram -ge 256
    $checks['expected_vcpus'] = $cpuCount -eq $CpuCount
    $checks['multiple_vcpus'] = $cpuCount -ge 2
    $checks['hyperv_clock_provider'] = [bool]($machineInfo -match '^paravirtprovider="hyperv"$')
    $checks['hpet_enabled'] = [bool]($machineInfo -match '^hpet="on"$')

    if (-not $checks.vmsvga -or -not $checks.accelerate3d_mode -or -not $checks.vram_256mb -or -not $checks.expected_vcpus -or -not $checks.multiple_vcpus -or -not $checks.hyperv_clock_provider -or -not $checks.hpet_enabled) {
        throw "The VM must use $CpuCount vCPUs, Hyper-V paravirtualization, HPET, VMSVGA, the requested 3D mode, and at least 256 MB of video memory."
    }

    Invoke-VBox -Arguments @('setextradata', $VmName, 'GUI/LastGuestSizeHint', "$Width,$Height") -Quiet
    Invoke-VBox -Arguments @('setextradata', $VmName, 'GUI/MaxGuestResolution', 'any') -Quiet
    Invoke-VBox -Arguments @('setextradata', $VmName, 'CustomVideoMode1', "${Width}x${Height}x32") -Quiet
    Start-TestVm
    [void](Wait-VmState -State @('running') -TimeoutSeconds 20)
    Start-Sleep -Seconds 2
    Invoke-VBox -Arguments @('controlvm', $VmName, 'setvideomodehint', "$Width", "$Height", '32') -Quiet

    $lock = Capture-Stage -Name '01-lock-screen' -TimeoutSeconds $BootTimeoutSeconds
    $interactiveStarted = $true
    $checks['lock_screen_visible'] = $lock.non_black_samples -gt 0

    $lockBeforeLogin = $lock

    if ($Width -gt 800 -and $Height -gt 600) {
        $lockSmall = Capture-Stage -Name '01a-lock-screen-small' -DifferentFrom $lock.sha256 -StageWidth 800 -StageHeight 600
        $checks['lock_screen_shrink_visible'] = $lockSmall.non_black_samples -gt 0
        $lockRestored = Capture-Stage -Name '01b-lock-screen-restored' -DifferentFrom $lockSmall.sha256
        $checks['lock_screen_grow_visible'] = $lockRestored.non_black_samples -gt 0
        $lockBeforeLogin = $lockRestored

        # Exercise the reported race as well as the stable resize path: shrink,
        # grow, then dismiss before either client can rely on a quiet display.
        Invoke-VBox -Arguments @('controlvm', $VmName, 'setvideomodehint', '800', '600', '32') -Quiet
        Start-Sleep -Milliseconds 150
        Invoke-VBox -Arguments @('controlvm', $VmName, 'setvideomodehint', "$Width", "$Height", '32') -Quiet
        Start-Sleep -Milliseconds 150
    }

    Send-Key -ScanCode '39'
    Start-Sleep -Seconds 2
    $login = Capture-Stage -Name '02-login' -DifferentFrom $lockBeforeLogin.sha256
    $checks['login_visible'] = $true
    $checks['login_after_lock_resize_visible'] = $login.non_black_samples -gt 0
    Send-Text -Text $Password
    Send-Key -ScanCode '1c'
    Start-Sleep -Seconds 5
    $desktop = Capture-Stage -Name '03-desktop' -DifferentFrom $login.sha256 -TimeoutSeconds 40
    $checks['desktop_visible'] = $desktop.non_black_samples -gt 0

    Send-WinShortcut -ScanCode '30'
    Start-Sleep -Seconds 3
    $brick = Capture-Stage -Name '04-brick' -DifferentFrom $desktop.sha256
    $checks['brick_visible'] = $true
    Send-Text -Text 'help'
    Send-Key -ScanCode '1c'
    Start-Sleep -Seconds 2
    $brickOutput = Capture-Stage -Name '05-brick-output' -DifferentFrom $brick.sha256
    $checks['brick_text_updates'] = $true

    Send-WinShortcut -ScanCode '39'
    Start-Sleep -Seconds 2
    $brickMaximized = Capture-Stage -Name '06-brick-maximized' -DifferentFrom $brickOutput.sha256
    $checks['window_maximize'] = $true
    Send-WinShortcut -ScanCode '39'
    Start-Sleep -Seconds 2

    for ($index = 0; $index -lt [Math]::Max(0, $FrameSamples); $index++) {
        Send-Text -Text 'a'
        Start-Sleep -Milliseconds 25

        if (($index + 1) % 65 -eq 0) {
            Send-Key -ScanCode '1c'
            Start-Sleep -Milliseconds 250
        }
    }

    Send-Key -ScanCode '1c'
    Start-Sleep -Seconds 2
    [void](Capture-Stage -Name '07-brick-stress' -DifferentFrom $brickMaximized.sha256)

    Send-WinShortcut -ScanCode '12'
    Start-Sleep -Seconds 4
    $array = Capture-Stage -Name '08-array' -DifferentFrom $brickOutput.sha256
    $checks['array_visible'] = $array.light_samples -gt $desktop.light_samples

    if ($Width -ge 1280 -and $Height -ge 800) {
        $reflowWidth = 800
        $reflowHeight = 600
        Invoke-VBox -Arguments @('controlvm', $VmName, 'setvideomodehint', "$reflowWidth", "$reflowHeight", '32') -Quiet
        Start-Sleep -Seconds 2
        $arrayReflow = Capture-Stage -Name '08a-array-live-resize' -DifferentFrom $array.sha256 -StageWidth $reflowWidth -StageHeight $reflowHeight
        $arrayReflowPath = Join-Path $outputRoot '08a-array-live-resize.png'
        $rightEdgeLightPixels = Get-RightEdgeLightPixels -Path $arrayReflowPath
        $checks['live_resize_resolution'] = $arrayReflow.width -eq $reflowWidth -and $arrayReflow.height -eq $reflowHeight
        $checks['live_resize_window_reflow'] = $rightEdgeLightPixels -le 12
        [void](Capture-Stage -Name '08b-array-live-resize-restored' -DifferentFrom $arrayReflow.sha256)
    }

    Send-WinShortcut -ScanCode '2d'
    Start-Sleep -Seconds 2

    Send-WinShortcut -ScanCode '30'
    Start-Sleep -Seconds 2
    Send-Text -Text 'run /the one/build/write/write.py behind'
    Send-Key -ScanCode '1c'
    Start-Sleep -Seconds 6
    $write = Capture-Stage -Name '09-write' -DifferentFrom $array.sha256
    $checks['write_visible'] = $write.light_samples -gt $desktop.light_samples

    Send-WinKey
    Start-Sleep -Seconds 2
    $startMenu = Capture-Stage -Name '10-start-menu' -DifferentFrom $write.sha256
    $checks['start_menu_visible'] = $true
    Send-Key -ScanCode '01'
    Start-Sleep -Seconds 1

    Send-WinShortcut -ScanCode '2d'
    Start-Sleep -Seconds 1

    for ($index = 0; $index -lt 3; $index++) {
        Send-WinShortcut -ScanCode '12'
        Start-Sleep -Milliseconds 700
        Send-WinShortcut -ScanCode '39'
        Start-Sleep -Milliseconds 500
        Send-WinShortcut -ScanCode '39'
        Start-Sleep -Milliseconds 500
        Send-WinShortcut -ScanCode '2d'
        Start-Sleep -Milliseconds 700
    }

    $checks['window_lifecycle_stress'] = $true
    Start-Sleep -Seconds 3
    Send-WinShortcut -ScanCode '30'
    Start-Sleep -Seconds $(if ($GraphicsMode -eq 'no3d') { 10 } elseif ($GraphicsMode -eq 'cpu') { 4 } else { 2 })
    $showcaseExpectation = if ($GraphicsMode -eq 'cpu') { 'cpu' } elseif ($GraphicsMode -eq 'no3d') { 'software' } else { 'gpu' }
    $showcaseMode = if ($GraphicsMode -eq 'cpu') { 'cputest' } elseif ($GraphicsMode -eq 'no3d') { 'softtest' } else { 'gputest' }
    $showcaseInputDelay = if ($GraphicsMode -eq 'hardware') { 45 } else { 140 }
    Send-SlowText -Text "run /software/opengl test.py $showcaseMode behind" -DelayMilliseconds $showcaseInputDelay
    Start-Sleep -Milliseconds $(if ($GraphicsMode -eq 'hardware') { 500 } else { 1800 })
    Send-Key -ScanCode '1c'
    Start-Sleep -Milliseconds $(if ($GraphicsMode -eq 'no3d') { 15000 } elseif ($GraphicsMode -eq 'cpu') { 2500 } else { 1200 })
    $showcaseStage = Capture-Stage -Name '11-opengl-showcase' -DifferentFrom $startMenu.sha256
    $checks['opengl_showcase_visible'] = $showcaseStage.colored_samples -ge 200 -or $GraphicsMode -eq 'cpu'
    Start-Sleep -Seconds $(if ($GraphicsMode -eq 'cpu') { 4 } elseif ($GraphicsMode -eq 'no3d') { 25 } else { 30 })
    Send-WinShortcut -ScanCode '30'
    Start-Sleep -Seconds $(if ($GraphicsMode -eq 'no3d') { 10 } elseif ($GraphicsMode -eq 'cpu') { 4 } else { 2 })
    $showcase3dMode = if ($GraphicsMode -eq 'cpu') { '3dcputest' } elseif ($GraphicsMode -eq 'no3d') { '3dsofttest' } else { '3dgputest' }
    Send-SlowText -Text "run /software/opengl 3d test.py $showcase3dMode behind" -DelayMilliseconds $showcaseInputDelay
    Start-Sleep -Milliseconds $(if ($GraphicsMode -eq 'hardware') { 700 } else { 1800 })
    Send-Key -ScanCode '1c'
    Start-Sleep -Seconds $(if ($GraphicsMode -eq 'no3d') { 20 } elseif ($GraphicsMode -eq 'cpu') { 3 } else { 2 })
    $showcase3dStage = Capture-Stage -Name '12-opengl-3d-showcase' -DifferentFrom $showcaseStage.sha256
    $checks['opengl_3d_showcase_visible'] = $showcase3dStage.colored_samples -ge 200 -or $GraphicsMode -eq 'cpu'
    Start-Sleep -Seconds $(if ($GraphicsMode -eq 'no3d') { 25 } elseif ($GraphicsMode -eq 'cpu') { 3 } else { 8 })
    Send-WinShortcut -ScanCode '30'
    Start-Sleep -Seconds $(if ($GraphicsMode -eq 'no3d') { 8 } elseif ($GraphicsMode -eq 'cpu') { 3 } else { 2 })
    Send-SlowText -Text 'shut down' -DelayMilliseconds $(if ($GraphicsMode -eq 'hardware') { 45 } else { 140 })
    Send-Key -ScanCode '1c'
    [void](Wait-VmState -State @('poweroff', 'aborted') -TimeoutSeconds 90)
    $checks['clean_guest_shutdown'] = (Get-VmState) -eq 'poweroff'
}
catch {
    $failure = $_.Exception
    $errors.Add($_.Exception.Message)
}
finally {
    if ((Get-VmState) -notin @('poweroff', 'missing')) {
        try {
            Invoke-VBox -Arguments @('controlvm', $VmName, 'poweroff') -Quiet
            [void](Wait-VmState -State @('poweroff', 'aborted') -TimeoutSeconds 20)
        }
        catch {
            $errors.Add("VM cleanup failed: $($_.Exception.Message)")
        }
    }

    if ($null -ne $bootConfigOriginal) {
        try {
            Set-CpuBootOverride -Enabled $false -Restore
        }
        catch {
            $errors.Add("Boot ISO restoration failed: $($_.Exception.Message)")
        }
    }
}

try {
    $serialSource = Join-Path $environmentRoot 'vbox-serial.log'
    $expectedKernelReleasePath = Join-Path $environmentRoot 'hardware\kernel-release.txt'

    if (Test-Path -LiteralPath $serialSource -PathType Leaf) {
        $serialEvidence = Join-Path $outputRoot 'vbox-serial.log'
        Copy-Item -LiteralPath $serialSource -Destination $serialEvidence -Force
        $serialText = [System.IO.File]::ReadAllText($serialEvidence)
        if (Test-Path -LiteralPath $expectedKernelReleasePath -PathType Leaf) {
            $expectedKernelRelease = ([System.IO.File]::ReadAllText($expectedKernelReleasePath)).Trim()
            $checks['expected_kernel_release'] = [bool]($serialText -match "Linux version $([regex]::Escape($expectedKernelRelease))(?:\s|$)")
        }
        else {
            $checks['expected_kernel_release'] = $false
        }
        $checks['smp_cpu_count'] = [bool]($serialText -match "smp: Brought up .* $CpuCount CPUs")
        $checks['stable_smp_clock'] = [bool]($serialText -match 'clocksource: Switched to clocksource (hpet|hyperv_clocksource|tsc)')
        $checks['no_rcu_stalls'] = -not [bool]($serialText -match '(?i)rcu.*detected stalls|rcu.*kthread starved')
        $checks['no_kernel_panic'] = -not [bool]($serialText -match 'Kernel panic')
    }

    $vdi = Get-AttachedVdi
    Invoke-VBox -Arguments @('clonemedium', 'disk', $vdi, $runtimeRaw, '--format', 'RAW') -Quiet
    $wslRawOutput = & wsl.exe --exec wslpath -a $runtimeRaw

    if ($LASTEXITCODE -ne 0 -or -not $wslRawOutput) {
        throw 'WSL could not locate the cloned VirtualBox runtime disk.'
    }

    $wslRaw = ([string]($wslRawOutput | Select-Object -First 1)).Trim()
    & wsl.exe -u root --exec sh -c 'mkdir -p "$2"; mount -o loop,ro,noload "$1" "$2"' sh $wslRaw $mountPoint

    if ($LASTEXITCODE -ne 0) {
        throw 'WSL could not mount the cloned VirtualBox runtime disk read-only.'
    }

    $runtimeMounted = $true
    $telemetryText = Read-GuestFile -GuestPath 'the one/logs/graphics telemetry.json'

    if (-not $telemetryText) {
        throw 'The guest did not write graphics telemetry.'
    }

    [System.IO.File]::WriteAllText((Join-Path $outputRoot 'graphics telemetry.json'), $telemetryText)
    $showcaseText = Read-GuestFile -GuestPath 'the one/logs/opengl test.json'

    if (-not $showcaseText) {
        $showcaseText = Read-GuestFile -GuestPath '.ephemeral/opengl-test/live-test.json'
    }

    if ($showcaseText) {
        [System.IO.File]::WriteAllText((Join-Path $outputRoot 'opengl test.json'), $showcaseText)

        try {
            $showcase = $showcaseText | ConvertFrom-Json
        }
        catch {
            $errors.Add("The OpenGL showcase returned invalid JSON: $($_.Exception.Message)")
        }
    }
    else {
        $showcaseProgress = Read-GuestFile -GuestPath 'the one/logs/opengl test progress.json'

        if (-not $showcaseProgress) {
            $showcaseProgress = Read-GuestFile -GuestPath '.ephemeral/opengl-test/progress.json'
        }

        if ($showcaseProgress) {
            [System.IO.File]::WriteAllText((Join-Path $outputRoot 'opengl test progress.json'), $showcaseProgress)
            $errors.Add("The OpenGL showcase did not write its automated live-test result. Last progress: $showcaseProgress")
        }
        else {
            $errors.Add('The OpenGL showcase did not write its automated live-test result or progress record.')
        }
    }
    $showcase3dText = Read-GuestFile -GuestPath 'the one/logs/opengl 3d test.json'

    if (-not $showcase3dText) {
        $showcase3dText = Read-GuestFile -GuestPath '.ephemeral/opengl-3d-test/live-test.json'
    }

    if ($showcase3dText) {
        [System.IO.File]::WriteAllText((Join-Path $outputRoot 'opengl 3d test.json'), $showcase3dText)

        try {
            $showcase3d = $showcase3dText | ConvertFrom-Json
        }
        catch {
            $errors.Add("The OpenGL 3D showcase returned invalid JSON: $($_.Exception.Message)")
        }
    }
    else {
        $showcase3dProgress = Read-GuestFile -GuestPath 'the one/logs/opengl 3d test progress.json'

        if (-not $showcase3dProgress) {
            $showcase3dProgress = Read-GuestFile -GuestPath '.ephemeral/opengl-3d-test/progress.json'
        }

        if ($showcase3dProgress) {
            [System.IO.File]::WriteAllText((Join-Path $outputRoot 'opengl 3d test progress.json'), $showcase3dProgress)
            $errors.Add("The OpenGL 3D showcase did not write its automated live-test result. Last progress: $showcase3dProgress")
        }
        else {
            $errors.Add('The OpenGL 3D showcase did not write its automated live-test result or progress record.')
        }
    }
    $windowLog = Read-GuestFile -GuestPath 'the one/logs/windowserver.py.log'

    if ($windowLog) {
        [System.IO.File]::WriteAllText((Join-Path $outputRoot 'windowserver.py.log'), $windowLog)
    }

    $graphicsLog = Read-GuestFile -GuestPath 'the one/logs/graphics.py.log'

    if ($graphicsLog) {
        [System.IO.File]::WriteAllText((Join-Path $outputRoot 'graphics.py.log'), $graphicsLog)
    }

    $virtualBoxLog = Read-GuestFile -GuestPath 'the one/logs/guestadditions.py.log'

    if ($virtualBoxLog) {
        [System.IO.File]::WriteAllText((Join-Path $outputRoot 'guestadditions.py.log'), $virtualBoxLog)
    }

    $telemetry = $telemetryText | ConvertFrom-Json

    if ($interactiveStarted) {
        $metrics = $telemetry.telemetry
        $checks['guest_resolution'] = [int]$telemetry.width -eq $Width -and [int]$telemetry.height -eq $Height
        $checks['opengl_backend'] = [string]$telemetry.backend -eq 'opengl'
        $checks['window_compositor_mode'] = if ($GraphicsMode -eq 'cpu') {
            [string]$telemetry.window_compositor -eq 'cpu'
        } else {
            [string]$telemetry.window_compositor -eq 'gpu'
        }
        $checks['hardware_acceleration_mode'] = if ($GraphicsMode -eq 'no3d') {
            -not [bool]$telemetry.hardware_accelerated
        } else {
            [bool]$telemetry.hardware_accelerated
        }
        $checks['drm_driver_recorded'] = -not [string]::IsNullOrWhiteSpace([string]$telemetry.drm_driver)
        $checks['no_failed_frames'] = [int]$metrics.failed_frames -eq 0
        $checks['no_gpu_fallbacks'] = [int]$metrics.fallbacks -eq 0 -and -not [bool]$telemetry.gpu_failed
        $checks['no_managed_command_errors'] = [int]$telemetry.window_telemetry.managed_command_errors -eq 0
        $checks['no_application_graphics_fallbacks'] = (@($telemetry.window_telemetry.windows | Measure-Object -Property fallbacks -Sum).Sum -eq 0)
        $retainedWindows = @($telemetry.window_telemetry.windows | Where-Object {
            [bool]$_.mapped -and [int]$_.scene_commits -gt 0
        })
        $checks['texture_count_within_limit'] = [int64]$metrics.texture_count -le [int64]$metrics.texture_limit
        $checks['texture_bytes_within_limit'] = [int64]$metrics.texture_bytes -le [int64]$metrics.texture_byte_limit
        $showcaseExpectation = if ($GraphicsMode -eq 'cpu') { 'cpu' } elseif ($GraphicsMode -eq 'no3d') { 'software' } else { 'gpu' }
        $checks['opengl_showcase_result_present'] = $null -ne $showcase
        $checks['opengl_showcase_expected_path'] = $null -ne $showcase -and [string]$showcase.expected_path -eq $showcaseExpectation
        $checks['opengl_showcase_live_test_passed'] = $null -ne $showcase -and [bool]$showcase.passed
        $checks['opengl_3d_showcase_result_present'] = $null -ne $showcase3d
        $checks['opengl_3d_showcase_expected_path'] = $null -ne $showcase3d -and [string]$showcase3d.expected_path -eq $showcaseExpectation
        $checks['opengl_3d_showcase_live_test_passed'] = $null -ne $showcase3d -and [bool]$showcase3d.passed

        if ($GraphicsMode -eq 'hardware' -and $null -ne $showcase) {
            $checks['opengl_showcase_normal_average_under_16_7ms'] = [double]$showcase.profiles.normal.render_average_ms -gt 0.0 -and [double]$showcase.profiles.normal.render_average_ms -lt 16.7
            $checks['opengl_showcase_normal_p95_under_33ms'] = [double]$showcase.profiles.normal.render_p95_ms -gt 0.0 -and [double]$showcase.profiles.normal.render_p95_ms -lt 33.0
            $checks['opengl_showcase_stress_p95_under_33ms'] = [double]$showcase.profiles.stress.render_p95_ms -gt 0.0 -and [double]$showcase.profiles.stress.render_p95_ms -lt 33.0
        }

        if ($GraphicsMode -ne 'cpu') {
            $checks['analytic_2d_lines_active'] = [int64]$metrics.aa_2d_line_segments -gt 0
            $checks['analytic_3d_wireframes_active'] = [int64]$metrics.aa_3d_wire_segments -gt 0
            $checks['mapped_retained_scenes_remain_active'] = $retainedWindows.Count -gt 0 -and @(
                $retainedWindows | Where-Object { -not [bool]$_.managed -or -not [bool]$_.managed_only }
            ).Count -eq 0
            $sceneCachedWindows = @($retainedWindows | Where-Object { [int]$_.scene_texture_renders -gt 0 })
            $checks['managed_scene_texture_cache_active'] = $sceneCachedWindows.Count -ge 3
            $checks['managed_scene_texture_cache_reused'] = (@($sceneCachedWindows | Measure-Object -Property scene_texture_hits -Sum).Sum -gt 0)
            $checks['scene_updates_scheduled'] = [int]$telemetry.window_telemetry.scene_updates_completed -gt 0
            $checks['scene_update_queue_drained'] = [int]$telemetry.window_telemetry.scene_updates_completed -eq [int]$telemetry.window_telemetry.scene_updates_queued
            $checks['glyphs_prewarmed'] = [int]$metrics.glyph_prewarm_runs -gt 0 -and [int]$metrics.glyph_prewarmed -gt 0

            if ($GraphicsMode -eq 'hardware') {
                $checks['quality_3d_supersampling_active'] = [int64]$metrics.aa_supersample_scenes -gt 0 -and [int64]$metrics.aa_supersample_pixels -gt 0
                $checks['quality_3d_targets_allocated'] = [int64]$metrics.aa_target_count -gt 0 -and [int64]$metrics.aa_target_bytes -gt 0
                $checks['quality_3d_no_fallbacks'] = [int64]$metrics.aa_quality_fallbacks -eq 0
                $checks['frame_samples'] = [int]$metrics.frame_samples -ge [Math]::Min(120, [Math]::Max(1, $FrameSamples))
                $steadyProfile = $metrics.frame_profiles.steady_partial
                $steadyTarget = if ($Width -eq 2560 -and $Height -eq 1440) { 33.0 } elseif ($Width -le 1920 -and $Height -le 1080) { 33.0 } else { 67.0 }
                $maximumTarget = if ($Width -ge 3840 -or $Height -ge 2160) { 500.0 } else { 350.0 }
                $checks['interactive_median_within_33ms'] = [double]$metrics.percentile_50_frame_ms -le 33.0
                $checks['average_frame_within_40ms'] = [double]$metrics.average_frame_ms -le 40.0
                # The continuously animated 3D showcase intentionally occupies
                # the final rolling frame history.  Accept the isolated normal
                # and stress profiles collected immediately beforehand as the
                # equivalent steady-workload sample evidence.
                $checks['steady_partial_samples'] = [int]$steadyProfile.samples -ge 120 -or (
                    $null -ne $showcase -and
                    [int]$showcase.profiles.normal.samples -ge 100 -and
                    [int]$showcase.profiles.stress.samples -ge 60
                )
                $checks['steady_partial_p95_within_target'] = [double]$steadyProfile.percentile_95_ms -le $steadyTarget
                $checks['lifecycle_p95_within_150ms'] = [double]$metrics.percentile_95_frame_ms -le 150.0
                $checks['maximum_frame_within_target'] = [double]$metrics.maximum_frame_ms -le $maximumTarget
            }
            else {
                $checks['software_analytic_3d_active'] = [int64]$metrics.aa_analytic_scenes -gt 0
                $checks['software_3d_supersampling_avoided'] = [int64]$metrics.aa_supersample_scenes -eq 0
                $checks['software_path_presented_frames'] = [int]$metrics.frames -gt 0
            }
        }
        else {
            $checks['managed_scenes_disabled'] = $retainedWindows.Count -eq 0
            $checks['software_path_presented_frames'] = [int]$metrics.frames -gt 0
        }

        $taskbarWindows = @($telemetry.window_telemetry.windows | Where-Object { $_.role -eq 'taskbar' })
        $checks['taskbar_scene_commits_bounded'] = $taskbarWindows.Count -ge 1 -and @($taskbarWindows | Where-Object { [int]$_.scene_commits -gt 50 }).Count -eq 0

        foreach ($entry in $checks.GetEnumerator()) {
            if (-not [bool]$entry.Value) {
                $errors.Add("Check failed: $($entry.Key)")
            }
        }
    }
}
catch {
    $errors.Add("Runtime evidence extraction failed: $($_.Exception.Message)")
}
finally {
    if ($runtimeMounted) {
        & wsl.exe -u root --exec umount $mountPoint *> $null
    }

    if (Test-Path -LiteralPath $runtimeRaw -PathType Leaf) {
        Remove-Item -LiteralPath $runtimeRaw -Force
    }
}

$report = [ordered]@{
    format = 1
    passed = $errors.Count -eq 0
    vm = $VmName
    account = $Username
    graphics_mode = $GraphicsMode
    vcpus = $CpuCount
    resolution = @($Width, $Height)
    generated_at = (Get-Date).ToString('o')
    output = $outputRoot
    checks = $checks
    stages = $stages
    telemetry = if ($telemetry) {
        [ordered]@{
            renderer = $telemetry.renderer
            drm_driver = $telemetry.drm_driver
            hardware_accelerated = $telemetry.hardware_accelerated
            window_compositor = $telemetry.window_compositor
            frames = $telemetry.telemetry.frames
            frame_samples = $telemetry.telemetry.frame_samples
            average_frame_ms = $telemetry.telemetry.average_frame_ms
            percentile_95_frame_ms = $telemetry.telemetry.percentile_95_frame_ms
            maximum_frame_ms = $telemetry.telemetry.maximum_frame_ms
            draw_calls_per_frame = $telemetry.telemetry.draw_calls_per_frame
            upload_bytes_per_frame = $telemetry.telemetry.upload_bytes_per_frame
            texture_count = $telemetry.telemetry.texture_count
            texture_bytes = $telemetry.telemetry.texture_bytes
            glyph_prewarmed = $telemetry.telemetry.glyph_prewarmed
            aa_2d_line_segments = $telemetry.telemetry.aa_2d_line_segments
            aa_3d_wire_segments = $telemetry.telemetry.aa_3d_wire_segments
            aa_analytic_scenes = $telemetry.telemetry.aa_analytic_scenes
            aa_supersample_scenes = $telemetry.telemetry.aa_supersample_scenes
            aa_supersample_pixels = $telemetry.telemetry.aa_supersample_pixels
            aa_supersample_average_resolve_ms = $telemetry.telemetry.aa_supersample_average_resolve_ms
            aa_quality_fallbacks = $telemetry.telemetry.aa_quality_fallbacks
            aa_target_count = $telemetry.telemetry.aa_target_count
            aa_target_bytes = $telemetry.telemetry.aa_target_bytes
            scene_updates_completed = $telemetry.window_telemetry.scene_updates_completed
        }
    } else { $null }
    showcase = if ($showcase) {
        [ordered]@{
            passed = [bool]$showcase.passed
            expected_path = [string]$showcase.expected_path
            profiles = $showcase.profiles
            checks = $showcase.checks
            final = [ordered]@{
                renderer = $showcase.final.renderer
                hardware_accelerated = $showcase.final.hardware_accelerated
                window_compositor = $showcase.final.window_compositor
                owned_window = $showcase.final.owned_window
                compositor = $showcase.final.compositor
            }
            errors = @($showcase.errors)
        }
    } else { $null }
    showcase_3d = if ($showcase3d) {
        [ordered]@{
            passed = [bool]$showcase3d.passed
            expected_path = [string]$showcase3d.expected_path
            growth = $showcase3d.growth
            checks = $showcase3d.checks
            final = [ordered]@{
                renderer = $showcase3d.final.renderer
                hardware_accelerated = $showcase3d.final.hardware_accelerated
                window_compositor = $showcase3d.final.window_compositor
                owned_window = $showcase3d.final.owned_window
            }
            errors = @($showcase3d.errors)
        }
    } else { $null }
    errors = @($errors)
}

$reportPath = Join-Path $outputRoot 'report.json'
[System.IO.File]::WriteAllText($reportPath, ($report | ConvertTo-Json -Depth 12))

if ($errors.Count -gt 0) {
    Write-Host ($report | ConvertTo-Json -Depth 12)
    throw "VirtualBox graphics regression failed. Evidence: $reportPath"
}

Write-Host 'VirtualBox graphics regression passed.'
Write-Host ($report | ConvertTo-Json -Depth 12 -Compress)
