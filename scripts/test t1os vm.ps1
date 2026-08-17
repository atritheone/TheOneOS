[CmdletBinding()]
param(
    [ValidateSet('Smoke', 'Brick', 'Gui', 'Features', 'Full')]
    [string]$Suite = 'Brick',

    [string[]]$Directive,

    [ValidateRange(60, 600)]
    [int]$BootTimeoutSeconds = 240,

    [ValidateRange(10, 600)]
    [int]$RequestTimeoutSeconds = 300,

    [ValidateRange(5, 600)]
    [int]$LockScreenTimeoutSeconds = 120,

    [ValidateRange(800, 3840)]
    # Match the template's native VMSVGA scanout.  Forcing a live mode change
    # after WindowServer owns KMS can stall vmwgfx and produces a black host
    # capture even though the renderer itself is healthy.
    [int]$Width = 1920,

    [ValidateRange(600, 2160)]
    [int]$Height = 1080,

    [string]$Username = 'development',

    [string]$Password = 'password'
)

$incrementalTestBootstrap = Join-Path $PSScriptRoot 'incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$environmentRoot = Join-Path $projectRoot 'environment'
$hardwareRoot = Join-Path $environmentRoot 'hardware'
$sourceBuildRoot = Join-Path $projectRoot 'source\build software'
$terminalFixtureSource = Join-Path $PSScriptRoot 'fixtures\brick terminal emulator.py'
$reportPath = Join-Path $hardwareRoot 't1os-vm-test-report.json'
$evidencePath = Join-Path $hardwareRoot 't1os-vm-test-serial.log'
$guiEvidenceRoot = Join-Path $hardwareRoot 't1os-vm-test-gui'
$baseVmName = 'T1OS Codex Test Base'
$baseSnapshot = 'codex-clean'
$shareName = 'T1OS_Codex_Test'
$token = [guid]::NewGuid().ToString('N').Substring(0, 12)
$cloneName = "T1OS Codex Test $token"
$runRoot = Join-Path $hardwareRoot "t1os-vm-test-$token"
$cloneBase = Join-Path $runRoot 'vm'
$exchangeRoot = Join-Path $runRoot 'exchange'
$serialPath = Join-Path $runRoot 'serial.log'
$guiRunRoot = Join-Path $runRoot 'gui'
$registered = $false
$started = $false
$results = @()
$guiStages = [ordered]@{}
$guiChecks = [ordered]@{}
$guiLaunch = $null
$guiMode = $null
$featureChecks = [ordered]@{}
$featureLaunches = [ordered]@{}
$featureStatus = $null
$serviceStatus = $null
$failure = $null
$startedAt = [DateTime]::UtcNow
$bootSeconds = $null

function Get-T1OSVBoxManage {
    $command = Get-Command VBoxManage -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $default = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
    if (Test-Path -LiteralPath $default -PathType Leaf) {
        return $default
    }

    throw 'VBoxManage was not found. Install VirtualBox or add VBoxManage to PATH.'
}

function Invoke-T1OSVBox {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$Quiet
    )

    if ($Quiet) {
        & $script:vbox @Arguments *> $null
    }
    else {
        & $script:vbox @Arguments | Out-Host
    }
    if ($LASTEXITCODE -ne 0) {
        throw "VBoxManage $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

function Get-T1OSVmState {
    $line = & $script:vbox showvminfo $cloneName --machinereadable 2>$null |
        Where-Object { $_ -match '^VMState=' } |
        Select-Object -First 1
    if ($LASTEXITCODE -ne 0 -or -not $line) {
        return 'missing'
    }
    return ([string]$line).Split('=', 2)[1].Trim('"')
}

function Read-T1OSSharedText {
    param([Parameter(Mandatory)][string]$Path)

    try {
        $stream = [System.IO.FileStream]::new(
            $Path,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
        )
        try {
            $reader = [System.IO.StreamReader]::new($stream)
            try {
                return $reader.ReadToEnd()
            }
            finally {
                $reader.Dispose()
            }
        }
        finally {
            $stream.Dispose()
        }
    }
    catch [System.IO.IOException] {
        return ''
    }
}

function Read-T1OSSharedJson {
    param([Parameter(Mandatory)][string]$Path)

    $text = Read-T1OSSharedText -Path $Path
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $null
    }
    try {
        return $text | ConvertFrom-Json -Depth 100
    }
    catch {
        return $null
    }
}

function Test-T1OSFatalSerial {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Text)

    return $Text -match (
        'I CANNOT CONTINUE|Kernel panic|blocked for more than 120 seconds|' +
        'GPU OWNER FAILED|ABORTING SYSTEM'
    )
}

function Wait-T1OSTestGuest {
    $begin = [DateTime]::UtcNow
    $deadline = $begin.AddSeconds($BootTimeoutSeconds)
    $readyPath = Join-Path $exchangeRoot 'agent-ready.json'

    while ([DateTime]::UtcNow -lt $deadline) {
        $state = Get-T1OSVmState
        if ($state -in @('poweroff', 'aborted', 'saved', 'missing')) {
            throw "the disposable T1OS VM stopped before test readiness; state=$state."
        }

        $serial = if (Test-Path -LiteralPath $serialPath -PathType Leaf) {
            Read-T1OSSharedText -Path $serialPath
        }
        else {
            ''
        }
        if (Test-T1OSFatalSerial -Text $serial) {
            throw 'the disposable T1OS VM emitted a fatal boot marker.'
        }

        $agent = if (Test-Path -LiteralPath $readyPath -PathType Leaf) {
            Read-T1OSSharedJson -Path $readyPath
        }
        else {
            $null
        }
        # Current GODDESS writes individual service readiness to lazy per-service
        # logs rather than mirroring those legacy phrases to serial.  Serial is
        # still authoritative for the PID 1 trust handoff; GUI suites separately
        # require live Exchange and WindowServer session state below.
        $bootAccepted = $serial.Contains(
            'I AM AWAKE, AND MY PYTHON RUNTIME IS READY.'
        )

        if ($agent -and $agent.format -eq 1 -and $agent.source -eq 'deployed' -and $bootAccepted) {
            return [ordered]@{
                agent = $agent
                seconds = [Math]::Round(([DateTime]::UtcNow - $begin).TotalSeconds, 3)
            }
        }

        Start-Sleep -Milliseconds 250
    }

    throw "the disposable T1OS VM did not expose its embedded-build Brick test agent within $BootTimeoutSeconds seconds."
}

function Invoke-T1OSAgentRequest {
    param(
        [ValidateSet('brick', 'brick-gui', 'settings-gui', 'player-gui', 'session-status', 'feature-status', 'service-status')]
        [string]$Action = 'brick',
        [AllowEmptyString()][string]$Command = '',
        [Parameter(Mandatory)][int]$Order
    )

    $requestId = [guid]::NewGuid().ToString('N').Substring(0, 16)
    $requestPath = Join-Path $exchangeRoot "request-$requestId.json"
    $temporaryPath = Join-Path $exchangeRoot ".$requestId.tmp"
    $responsePath = Join-Path $exchangeRoot "response-$requestId.json"
    $request = [ordered]@{
        format = 1
        id = $requestId
        action = $Action
    }
    if ($Action -eq 'brick') {
        $request.directive = $Command
        $request.timeout_seconds = $RequestTimeoutSeconds
    }
    $json = $request | ConvertTo-Json -Depth 10 -Compress
    [System.IO.File]::WriteAllText($temporaryPath, $json + "`n", [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporaryPath -Destination $requestPath

    $deadline = [DateTime]::UtcNow.AddSeconds($RequestTimeoutSeconds + 15)
    while ([DateTime]::UtcNow -lt $deadline) {
        $state = Get-T1OSVmState
        if ($state -ne 'running') {
            throw "the disposable T1OS VM stopped while running agent action '$Action'; state=$state."
        }

        if (Test-Path -LiteralPath $serialPath -PathType Leaf) {
            $serial = Read-T1OSSharedText -Path $serialPath
            if (Test-T1OSFatalSerial -Text $serial) {
                throw "the disposable T1OS VM emitted a fatal marker while running agent action '$Action'."
            }
        }

        if (Test-Path -LiteralPath $responsePath -PathType Leaf) {
            $response = Read-T1OSSharedJson -Path $responsePath
            if ($response -and $response.id -eq $requestId) {
                return [ordered]@{
                    order = $Order
                    directive = $Command
                    action = $Action
                    passed = [bool]$response.passed
                    response = $response
                }
            }
        }

        Start-Sleep -Milliseconds 100
    }

    throw "agent action '$Action' did not return a response within $($RequestTimeoutSeconds + 15) seconds."
}

function Send-T1OSScanCodes {
    param([Parameter(Mandatory)][string[]]$Codes)

    Invoke-T1OSVBox -Arguments (@('controlvm', $cloneName, 'keyboardputscancode') + $Codes) -Quiet
}

function Get-T1OSSessionStatus {
    $result = Invoke-T1OSAgentRequest -Action 'session-status' -Order 0
    if (-not $result.passed -or $result.response.source -ne 'guest-state') {
        throw 'the VM test agent could not read the guest session state.'
    }
    if ($result.response.has_user -and $result.response.username -ne $Username) {
        throw "the VM test template account is '$($result.response.username)', not '$Username'."
    }
    return $result.response
}

function Wait-T1OSDesktopSession {
    param([int]$TimeoutSeconds = 60)

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $status = Get-T1OSSessionStatus
        if (
            $status.has_user -and $status.session_active -and
            $status.exchange_ready -and $status.windowserver_ready
        ) {
            return $status
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "the T1OS desktop session services did not become ready within $TimeoutSeconds seconds."
}

function Wait-T1OSLockScreen {
    param([int]$TimeoutSeconds = 120)

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $status = Get-T1OSSessionStatus
        if ($status.windowserver_ready -and $status.lock_screen_ready) {
            return $status
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "the T1OS verified lock-screen presentation did not become ready within $TimeoutSeconds seconds."
}

function Wait-T1OSLoginReady {
    param([int]$TimeoutSeconds = 30)

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $nextActivation = [DateTime]::MinValue
    $status = $null
    do {
        $status = Get-T1OSSessionStatus
        if ($status.windowserver_ready -and $status.login_ready) {
            return $status
        }

        # A headless VirtualBox control key can be lost at the exact moment
        # WindowServer changes focus. Retry only while the broker proves that
        # the same lock-screen process is still live; once it exits, never send
        # another activation key into the password field.
        $now = [DateTime]::UtcNow
        if ($status.lock_screen_ready -and $now -ge $nextActivation) {
            Send-T1OSKey -ScanCode '39'
            $nextActivation = $now.AddMilliseconds(500)
        }

        Start-Sleep -Milliseconds 125
    } while ([DateTime]::UtcNow -lt $deadline)

    $detail = if ($null -eq $status) { 'no guest status received' } else {
        $status | ConvertTo-Json -Compress -Depth 4
    }
    throw "the T1OS password form did not become input-ready within $TimeoutSeconds seconds; last guest state: $detail"
}

function Send-T1OSKey {
    param([Parameter(Mandatory)][string]$ScanCode)

    $released = '{0:x2}' -f (([Convert]::ToInt32($ScanCode, 16) + 0x80) -band 0xff)
    Send-T1OSScanCodes -Codes @($ScanCode, $released)
}

function Send-T1OSWinShortcut {
    param([Parameter(Mandatory)][string]$ScanCode)

    $released = '{0:x2}' -f (([Convert]::ToInt32($ScanCode, 16) + 0x80) -band 0xff)
    Send-T1OSScanCodes -Codes @('e0', '5b', $ScanCode, $released, 'e0', 'db')
}

function Send-T1OSAltF4 {
    Send-T1OSScanCodes -Codes @('38', '3e', 'be', 'b8')
}

function Send-T1OSMouseAbsolute {
    param(
        [Parameter(Mandatory)][int]$X,
        [Parameter(Mandatory)][int]$Y,
        [ValidateRange(0, 31)][int]$Buttons = 0
    )

    $virtualBox = $null
    $machine = $null
    $session = $null
    $console = $null
    $mouse = $null
    $locked = $false
    try {
        $virtualBox = New-Object -ComObject VirtualBox.VirtualBox
        $machine = $virtualBox.FindMachine($cloneName)
        $session = New-Object -ComObject VirtualBox.Session
        $machine.LockMachine($session, 1)
        $locked = $true
        $console = $session.Console
        $mouse = $console.Mouse
        $clampedX = [Math]::Max(1, [Math]::Min($Width - 1, $X))
        $clampedY = [Math]::Max(1, [Math]::Min($Height - 1, $Y))
        $mouse.PutMouseEventAbsolute($clampedX, $clampedY, 0, 0, $Buttons)
    }
    finally {
        if ($locked) {
            $session.UnlockMachine()
        }
        foreach ($value in @($mouse, $console, $session, $machine, $virtualBox)) {
            if ($null -ne $value -and [System.Runtime.InteropServices.Marshal]::IsComObject($value)) {
                [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($value)
            }
        }
    }
}

function Send-T1OSClick {
    param(
        [Parameter(Mandatory)][int]$X,
        [Parameter(Mandatory)][int]$Y
    )

    Send-T1OSMouseAbsolute -X $X -Y $Y
    Start-Sleep -Milliseconds 100
    Send-T1OSMouseAbsolute -X $X -Y $Y -Buttons 1
    Start-Sleep -Milliseconds 100
    Send-T1OSMouseAbsolute -X $X -Y $Y
    Start-Sleep -Milliseconds 200
}

function Send-T1OSText {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Text)

    if ($Text.Length -gt 0) {
        Invoke-T1OSVBox -Arguments @('controlvm', $cloneName, 'keyboardputstring', $Text) -Quiet
    }
}

function Send-T1OSSlowText {
    param(
        [Parameter(Mandatory)][AllowEmptyString()][string]$Text,
        [ValidateRange(10, 500)][int]$DelayMilliseconds = 75
    )

    foreach ($character in $Text.ToCharArray()) {
        Invoke-T1OSVBox -Arguments @(
            'controlvm', $cloneName, 'keyboardputstring', [string]$character
        ) -Quiet
        Start-Sleep -Milliseconds $DelayMilliseconds
    }
}

function Send-T1OSAsciiScanText {
    param(
        [Parameter(Mandatory)][string]$Text,
        [ValidateRange(10, 500)][int]$DelayMilliseconds = 60
    )

    $scanCodes = @{
        'a'='1e'; 'b'='30'; 'c'='2e'; 'd'='20'; 'e'='12'; 'f'='21'; 'g'='22'
        'h'='23'; 'i'='17'; 'j'='24'; 'k'='25'; 'l'='26'; 'm'='32'; 'n'='31'
        'o'='18'; 'p'='19'; 'q'='10'; 'r'='13'; 's'='1f'; 't'='14'; 'u'='16'
        'v'='2f'; 'w'='11'; 'x'='2d'; 'y'='15'; 'z'='2c'; ' '='39'
    }
    foreach ($character in $Text.ToCharArray()) {
        $key = [string]$character
        if (-not $scanCodes.ContainsKey($key)) {
            throw "ASCII scan-code injection does not support '$key'."
        }
        Send-T1OSKey -ScanCode $scanCodes[$key]
        Start-Sleep -Milliseconds $DelayMilliseconds
    }
}

function Get-T1OSImageStats {
    param([Parameter(Mandatory)][string]$Path)

    $bitmap = [System.Drawing.Bitmap]::new($Path)
    try {
        $nonBlack = 0
        $light = 0
        $samples = 0
        $colors = [System.Collections.Generic.HashSet[int]]::new()

        for ($y = 0; $y -lt $bitmap.Height; $y += 8) {
            for ($x = 0; $x -lt $bitmap.Width; $x += 8) {
                $pixel = $bitmap.GetPixel($x, $y)
                $samples++
                [void]$colors.Add($pixel.ToArgb())
                if ($pixel.R -gt 8 -or $pixel.G -gt 8 -or $pixel.B -gt 8) {
                    $nonBlack++
                }
                if ($pixel.R -gt 180 -and $pixel.G -gt 180 -and $pixel.B -gt 180) {
                    $light++
                }
            }
        }

        return [ordered]@{
            width = $bitmap.Width
            height = $bitmap.Height
            samples = $samples
            non_black_samples = $nonBlack
            light_samples = $light
            unique_sampled_colors = $colors.Count
            sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    finally {
        $bitmap.Dispose()
    }
}

function Save-T1OSGuiStage {
    param(
        [Parameter(Mandatory)][string]$Name,
        [string]$DifferentFrom,
        [int]$MinNonBlackSamples = 1,
        [int]$MinUniqueColors = 8,
        [int]$TimeoutSeconds = 30
    )

    $path = Join-Path $guiRunRoot "$Name.png"
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastError = ''
    do {
        try {
            Invoke-T1OSVBox -Arguments @('controlvm', $cloneName, 'setvideomodehint', [string]$Width, [string]$Height, '32') -Quiet
            Invoke-T1OSVBox -Arguments @('controlvm', $cloneName, 'screenshotpng', $path) -Quiet
            $stats = Get-T1OSImageStats -Path $path
            if (
                $stats.width -eq $Width -and
                $stats.height -eq $Height -and
                $stats.non_black_samples -ge $MinNonBlackSamples -and
                $stats.unique_sampled_colors -ge $MinUniqueColors -and
                (-not $DifferentFrom -or $stats.sha256 -ne $DifferentFrom)
            ) {
                $guiStages[$Name] = $stats
                return $stats
            }
        }
        catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "GUI stage '$Name' did not produce a distinct, nonblank ${Width}x${Height} screenshot. $lastError"
}

function Invoke-T1OSGuiTest {
    New-Item -ItemType Directory -Path $guiRunRoot -Force | Out-Null
    Invoke-T1OSVBox -Arguments @('controlvm', $cloneName, 'setvideomodehint', [string]$Width, [string]$Height, '32') -Quiet

    $initialStatus = Get-T1OSSessionStatus

    if (-not $initialStatus.has_user) {
        $script:guiMode = 'first-run'
        Write-Host 'GUI: completing the disposable VM first-run account flow...'
        $firstRun = Save-T1OSGuiStage -Name '01-first-run' -MinNonBlackSamples 50 -TimeoutSeconds 40
        $guiChecks.first_run_form_visible = $true

        Send-T1OSText -Text $Username
        Send-T1OSKey -ScanCode '1c'
        Start-Sleep -Milliseconds 150
        $guiChecks.first_run_password_visible = $true

        Send-T1OSText -Text $Password
        Send-T1OSKey -ScanCode '1c'
        Start-Sleep -Milliseconds 150
        $guiChecks.first_run_confirmation_visible = $true

        Send-T1OSText -Text $Password
        Send-T1OSKey -ScanCode '1c'
        [void](Wait-T1OSDesktopSession)
        $guiChecks.first_run_account_created = $true
        Start-Sleep -Seconds 2
        $desktop = Save-T1OSGuiStage -Name '04-desktop' -DifferentFrom $firstRun.sha256 -MinUniqueColors 2 -TimeoutSeconds 40
    }
    else {
        $script:guiMode = 'login'
        Write-Host 'GUI: completing the disposable VM lock-screen login flow...'
        [void](Wait-T1OSLockScreen -TimeoutSeconds $LockScreenTimeoutSeconds)
        $lock = Save-T1OSGuiStage -Name '01-lock-screen' -TimeoutSeconds 40
        $guiChecks.lock_screen_visible = $true

        [void](Wait-T1OSLoginReady -TimeoutSeconds $LockScreenTimeoutSeconds)
        Start-Sleep -Milliseconds 250
        $login = Save-T1OSGuiStage -Name '02-login' -DifferentFrom $lock.sha256
        $guiChecks.login_visible = $true

        Send-T1OSText -Text $Password
        Send-T1OSKey -ScanCode '1c'
        [void](Wait-T1OSDesktopSession)
        Start-Sleep -Seconds 2
        $desktop = Save-T1OSGuiStage -Name '04-desktop' -DifferentFrom $login.sha256 -MinUniqueColors 2 -TimeoutSeconds 40
    }
    $guiChecks.desktop_visible = $true

    Write-Host 'GUI: verifying post-login system services through Brick...'
    $systemResult = Invoke-T1OSAgentRequest -Action 'brick' -Command 'check system' -Order ($script:results.Count + 1)
    $script:results += $systemResult
    if (-not $systemResult.passed) {
        throw 'Brick system checks did not pass after the desktop session started.'
    }
    $guiChecks.post_login_system_services = $true

    Write-Host 'GUI: launching embedded Brick through the authenticated Operations broker...'
    $script:guiLaunch = Invoke-T1OSAgentRequest -Action 'brick-gui' -Order 0
    if (-not $script:guiLaunch.passed -or $script:guiLaunch.response.source -ne 'deployed') {
        throw 'the VM test agent could not launch embedded graphical Brick through Operations.'
    }
    Start-Sleep -Seconds 3
    $brick = Save-T1OSGuiStage -Name '05-brick' -DifferentFrom $desktop.sha256
    $guiChecks.brokered_brick_visible = $true

    Send-T1OSText -Text 'version'
    Send-T1OSKey -ScanCode '1c'
    Start-Sleep -Seconds 2
    $output = Save-T1OSGuiStage -Name '06-brick-output' -DifferentFrom $brick.sha256
    $guiChecks.keyboard_input_changed_brick = $true

    Send-T1OSWinShortcut -ScanCode '39'
    Start-Sleep -Seconds 2
    [void](Save-T1OSGuiStage -Name '07-brick-maximized' -DifferentFrom $output.sha256)
    $guiChecks.window_maximize_changed_frame = $true
}

function Get-T1OSFeatureStatus {
    $status = Invoke-T1OSAgentRequest -Action 'feature-status' -Order 0
    if (-not $status.passed -or $status.response.source -ne 'guest-state') {
        throw 'the VM test agent could not read fixed feature-test state.'
    }
    return $status.response
}

function Get-T1OSServiceStatus {
    $status = Invoke-T1OSAgentRequest -Action 'service-status' -Order 0
    if (-not $status.passed -or $status.response.source -ne 'guest-state') {
        throw 'the VM test agent could not read fixed service diagnostics.'
    }
    return $status.response
}

function Invoke-T1OSFeatureTest {
    Write-Host 'FEATURES: launching the embedded Settings Python page through Operations...'
    $settingsLaunch = Invoke-T1OSAgentRequest -Action 'settings-gui' -Order 0
    $script:featureLaunches.settings = $settingsLaunch
    if (-not $settingsLaunch.passed -or $settingsLaunch.response.source -ne 'deployed') {
        throw 'the VM test agent could not launch embedded Settings through Operations.'
    }
    Start-Sleep -Seconds 3
    Send-T1OSWinShortcut -ScanCode '39'
    Start-Sleep -Seconds 2
    $settings = Save-T1OSGuiStage -Name '08-settings-python' -TimeoutSeconds 30
    $featureChecks.settings_python_page_visible = $true

    $scale = [Math]::Max(0.5, [Math]::Sqrt(($Width * $Height) / (1920.0 * 1080.0)))
    $titleBar = 28
    # fieldrow reserves roughly the left third for the label.  Click the
    # actual editable value box so both Settings' button and text-cursor hit
    # tests agree, including when the window is maximised.
    $queryX = [int][Math]::Round(1000 * $scale)
    $queryY = $titleBar + [int][Math]::Round(162 * $scale)
    $rightInset = [int][Math]::Round(81 * $scale)
    $actionX = $Width - $rightInset
    $confirmY = $titleBar + [int][Math]::Round(248 * $scale)
    $checkX = $Width - [int][Math]::Round(197 * $scale)
    $checkY = $titleBar + [int][Math]::Round(104 * $scale)

    Send-T1OSClick -X $queryX -Y $queryY
    Send-T1OSText -Text 'humanize'
    Start-Sleep -Seconds 1
    $query = Save-T1OSGuiStage -Name '09-settings-python-query' -DifferentFrom $settings.sha256
    $featureChecks.settings_python_query_editable = $true

    Send-T1OSClick -X $actionX -Y $queryY
    Start-Sleep -Seconds 1
    $pending = Save-T1OSGuiStage -Name '10-settings-python-pending' -DifferentFrom $query.sha256
    $featureChecks.settings_python_change_reviewed = $true

    Send-T1OSClick -X $actionX -Y $confirmY
    Start-Sleep -Seconds 1
    $passwordEmpty = Save-T1OSGuiStage -Name '11-password-prompt-empty' -DifferentFrom $pending.sha256
    $featureChecks.native_password_prompt_empty_visible = $true

    Send-T1OSText -Text $Password
    Start-Sleep -Seconds 1
    $passwordFilled = Save-T1OSGuiStage -Name '12-password-prompt-filled' -DifferentFrom $passwordEmpty.sha256
    $featureChecks.native_password_prompt_masks_input = $true
    Send-T1OSKey -ScanCode '1c'
    Start-Sleep -Seconds 3
    [void](Save-T1OSGuiStage -Name '12a-password-submit-result' -DifferentFrom $passwordFilled.sha256)

    Write-Host 'FEATURES: waiting for Settings to install humanize...'
    $installed = $null
    $deadline = [DateTime]::UtcNow.AddSeconds(240)
    do {
        $installed = Invoke-T1OSAgentRequest -Action 'brick' -Command 'show python module humanize' -Order ($script:results.Count + 1)
        if ($installed.passed) {
            break
        }
        Start-Sleep -Seconds 2
    } while ([DateTime]::UtcNow -lt $deadline)
    $script:results += $installed
    if (-not $installed.passed) {
        throw 'Settings did not install the humanize Python module within 240 seconds.'
    }
    $featureChecks.settings_python_module_installed = $true
    Start-Sleep -Seconds 2
    [void](Save-T1OSGuiStage -Name '13-settings-humanize-installed' -DifferentFrom $passwordFilled.sha256)

    Send-T1OSClick -X $checkX -Y $checkY
    Start-Sleep -Seconds 4
    [void](Save-T1OSGuiStage -Name '14-settings-python-check')
    $featureChecks.settings_python_health_check_exercised = $true

    # Prove the fixed spaced-path fixture remains visible after the package
    # transaction before exercising graphical command entry and PTY startup.
    $fixtureGuestPath = '/master/development/terminal_test.py'
    $fixtureInspection = Invoke-T1OSAgentRequest -Action 'brick' -Command `
        'show details /master/development/terminal_test.py' `
        -Order ($script:results.Count + 1)
    $script:results += $fixtureInspection
    if (-not $fixtureInspection.passed) {
        throw 'the Brick terminal emulator fixture is not visible after Python module installation.'
    }
    $featureChecks.brick_terminal_fixture_visible_after_python_change = $true
    Send-T1OSAltF4
    Start-Sleep -Seconds 2

    Write-Host 'FEATURES: running an interactive Python program in the Brick terminal emulator...'
    # Settings may remain alive after its close shortcut, and the original
    # Brick can be obscured behind it.  Launch a fresh brokered Brick so the
    # following keyboard events have a deterministic foreground recipient.
    $terminalBrickLaunch = Invoke-T1OSAgentRequest -Action 'brick-gui' -Order 0
    $script:featureLaunches.terminal_brick = $terminalBrickLaunch
    if (-not $terminalBrickLaunch.passed -or $terminalBrickLaunch.response.source -ne 'deployed') {
        throw 'the VM test agent could not foreground Brick for the terminal-emulator test.'
    }
    Start-Sleep -Seconds 3
    Send-T1OSWinShortcut -ScanCode '39'
    Start-Sleep -Seconds 2
    Send-T1OSText -Text "run $fixtureGuestPath alpha `"two words`""
    Send-T1OSKey -ScanCode '1c'
    Start-Sleep -Seconds 2
    $terminalInput = Save-T1OSGuiStage -Name '15-brick-terminal-input' -TimeoutSeconds 30
    $featureChecks.brick_terminal_program_started = $true
    # Drive the live console through the physical PS/2 path. VirtualBox's
    # keyboardputstring is suitable for forms and Brick's command editor, but
    # can coalesce its Unicode events while a foreground PTY owns input.
    Send-T1OSAsciiScanText -Text 'interactive answer'
    Start-Sleep -Milliseconds 250
    Send-T1OSKey -ScanCode '1c'
    Start-Sleep -Seconds 2
    [void](Save-T1OSGuiStage -Name '15a-brick-terminal-reply')

    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        $script:featureStatus = Get-T1OSFeatureStatus
        if ($script:featureStatus.terminal_fixture_passed) {
            break
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    if (-not $script:featureStatus.terminal_fixture_passed) {
        throw 'the Brick terminal emulator fixture did not report TERMINAL_EMULATOR_PASS.'
    }
    Start-Sleep -Seconds 1
    [void](Save-T1OSGuiStage -Name '16-brick-terminal-pass' -DifferentFrom $terminalInput.sha256)
    $featureChecks.brick_terminal_tty_ansi_arguments_module_and_input = $true

    Write-Host 'FEATURES: checking managed Python state through headless Brick...'
    $pythonResult = Invoke-T1OSAgentRequest -Action 'brick' -Command 'python status; show python module humanize; check python; list python updates; python history' -Order ($script:results.Count + 1)
    $script:results += $pythonResult
    if (-not $pythonResult.passed) {
        throw 'Brick managed-Python status, inventory, health, update, or history checks failed.'
    }
    $featureChecks.brick_python_management_queries_passed = $true

    Write-Host 'FEATURES: playing /software/without_a_blush.mp4 in embedded Player...'
    $playerLaunch = Invoke-T1OSAgentRequest -Action 'player-gui' -Order 0
    $script:featureLaunches.player = $playerLaunch
    if (-not $playerLaunch.passed -or $playerLaunch.response.source -ne 'deployed') {
        throw 'the VM test agent could not launch embedded Player through Operations.'
    }
    Start-Sleep -Seconds 4
    $playerA = Save-T1OSGuiStage -Name '17-player-video-frame-a' -TimeoutSeconds 30
    Start-Sleep -Seconds 2
    [void](Save-T1OSGuiStage -Name '18-player-video-frame-b' -DifferentFrom $playerA.sha256 -TimeoutSeconds 30)
    $script:featureStatus = Get-T1OSFeatureStatus
    if (
        -not $script:featureStatus.player_alive -or
        $script:featureStatus.player_media_bytes -le 0 -or
        -not $script:featureStatus.player_playback_ready
    ) {
        $playerDetail = $script:featureStatus.player_status | ConvertTo-Json -Depth 4 -Compress
        throw "Player did not decode and present the fixed without_a_blush.mp4 media file: $playerDetail"
    }
    $featureChecks.player_opened_without_a_blush = $true
    $featureChecks.player_video_frames_changed = $true
    $featureChecks.managed_python_module_importable = [bool]$script:featureStatus.humanize_available
    if (-not $featureChecks.managed_python_module_importable) {
        throw 'humanize was recorded by the Python manager but was not importable in the guest runtime.'
    }
}

function Remove-T1OSVmTestDirectory {
    if (-not (Test-Path -LiteralPath $runRoot)) {
        return
    }

    $resolvedRunRoot = [System.IO.Path]::GetFullPath($runRoot)
    $resolvedHardwareRoot = [System.IO.Path]::GetFullPath($hardwareRoot).TrimEnd('\') + '\'
    if (-not $resolvedRunRoot.StartsWith($resolvedHardwareRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "refusing to remove unexpected VM test directory: $resolvedRunRoot"
    }

    Get-ChildItem -LiteralPath $resolvedRunRoot -Force -Recurse -ErrorAction SilentlyContinue |
        ForEach-Object { $_.Attributes = [System.IO.FileAttributes]::Normal }
    (Get-Item -LiteralPath $resolvedRunRoot -Force).Attributes = [System.IO.FileAttributes]::Normal
    Remove-Item -LiteralPath $resolvedRunRoot -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $Directive -or $Directive.Count -eq 0) {
    $Directive = switch ($Suite) {
        'Smoke' { @('version', 'role') }
        'Brick' { @('version; role', 'test parsing', 'test dogfood') }
        'Gui' { @('version') }
        'Features' { @('version') }
        'Full' { @('test brick', 'test directives') }
    }
}
$runGui = $Suite -in @('Gui', 'Features', 'Full')
$runFeatures = $Suite -in @('Features', 'Full')
$deferredDirectives = @()

$script:vbox = Get-T1OSVBoxManage
$preparationScript = Join-Path $PSScriptRoot 'prepare vm test vbox.ps1'
Write-Host 'preparing the isolated T1OS VirtualBox test template...'
& pwsh -NoLogo -NoProfile -NonInteractive -File $preparationScript
if ($LASTEXITCODE -ne 0) {
    throw 'the isolated T1OS VirtualBox test template could not be prepared.'
}

if (-not (Test-Path -LiteralPath $sourceBuildRoot -PathType Container)) {
    throw "T1OS source build tree not found: $sourceBuildRoot"
}

New-Item -ItemType Directory -Path $cloneBase, $exchangeRoot -Force | Out-Null
if ($runFeatures) {
    if (-not (Test-Path -LiteralPath $terminalFixtureSource -PathType Leaf)) {
        throw "Brick terminal emulator fixture not found: $terminalFixtureSource"
    }
}

try {
    Write-Host "creating disposable linked VM '$cloneName'..."
    Invoke-T1OSVBox -Arguments @(
        'clonevm', $baseVmName,
        '--snapshot', $baseSnapshot,
        '--options', 'link',
        '--name', $cloneName,
        '--basefolder', $cloneBase,
        '--mode', 'machine',
        '--register'
    ) -Quiet
    $registered = $true

    Invoke-T1OSVBox -Arguments @(
        'modifyvm', $cloneName,
        '--uart1', '0x3F8', '4',
        '--uart-mode1', 'file', $serialPath
    ) -Quiet
    Invoke-T1OSVBox -Arguments @(
        'sharedfolder', 'add', $cloneName,
        '--name', $shareName,
        '--hostpath', $exchangeRoot,
        '--automount'
    ) -Quiet
    Write-Host 'starting the disposable VM headlessly...'
    Invoke-T1OSVBox -Arguments @('startvm', $cloneName, '--type', 'headless') -Quiet
    $started = $true
    if ($runGui) {
        # Publish the final display geometry before VBoxDRMClient starts.  A
        # post-readiness hint is too late: WindowServer may already own KMS and
        # vmwgfx can stall while changing the active framebuffer live.
        Invoke-T1OSVBox -Arguments @(
            'controlvm', $cloneName, 'setvideomodehint',
            [string]$Width, [string]$Height, '32'
        ) -Quiet
    }

    $readiness = Wait-T1OSTestGuest
    $bootSeconds = $readiness.seconds
    Write-Host "T1OS and the embedded-build Brick agent are ready after $bootSeconds seconds."
    $script:serviceStatus = Get-T1OSServiceStatus
    if (-not $script:serviceStatus.operations_ready) {
        throw 'the authenticated Operations broker is not accepting VM test requests.'
    }
    if (-not $script:serviceStatus.python_ready) {
        throw 'the protected T1OS Python manager is not accepting VM test requests.'
    }

    $order = 0
    foreach ($command in $Directive) {
        # Rubbish operations intentionally require an authenticated desktop
        # identity. Run their complete diagnostic after the real GUI login,
        # instead of fabricating session state in the pre-login appliance.
        if ($runGui -and $command -eq 'test directives') {
            $deferredDirectives += $command
            continue
        }
        $order++
        Write-Host "[$order/$($Directive.Count)] Brick execute: $command"
        $result = Invoke-T1OSAgentRequest -Action 'brick' -Command $command -Order $order
        $results += $result
        if ($result.passed) {
            Write-Host '  passed'
        }
        else {
            Write-Host '  failed'
        }
    }

    if ($results | Where-Object { -not $_.passed }) {
        throw 'one or more Brick headless directives failed in the disposable VM.'
    }

    if ($runGui) {
        Invoke-T1OSGuiTest
    }
    foreach ($command in $deferredDirectives) {
        $order++
        Write-Host "[$order/$($Directive.Count)] Brick execute after GUI login: $command"
        $result = Invoke-T1OSAgentRequest -Action 'brick' -Command $command -Order $order
        $results += $result
        if ($result.passed) {
            Write-Host '  passed'
        }
        else {
            Write-Host '  failed'
        }
    }
    if ($results | Where-Object { -not $_.passed }) {
        throw 'one or more Brick directives failed in the disposable VM.'
    }
    if ($runFeatures) {
        Invoke-T1OSFeatureTest
    }
}
catch {
    $failure = $_.Exception.Message
    if ($started -and (Get-T1OSVmState) -eq 'running') {
        try {
            # Refresh the fixed guest logs after the failure.  The initial
            # snapshot predates GUI launch and cannot explain a later error.
            $script:serviceStatus = Get-T1OSServiceStatus
        }
        catch {
            # Preserve the primary failure if the agent has already stopped.
        }
    }
}
finally {
    if (Test-Path -LiteralPath $serialPath -PathType Leaf) {
        Copy-Item -LiteralPath $serialPath -Destination $evidencePath -Force
    }

    if ($runGui -and (Test-Path -LiteralPath $guiRunRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $guiEvidenceRoot -Force | Out-Null
        Get-ChildItem -LiteralPath $guiEvidenceRoot -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -in @('.png', '.log') } |
            Remove-Item -Force
        Get-ChildItem -LiteralPath $guiRunRoot -Filter '*.png' -File |
            ForEach-Object {
                Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $guiEvidenceRoot $_.Name) -Force
            }
        Get-ChildItem -LiteralPath $exchangeRoot -Filter '*.log' -File -ErrorAction SilentlyContinue |
            ForEach-Object {
                Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $guiEvidenceRoot $_.Name) -Force
            }
    }

    if ($started -and (Get-T1OSVmState) -eq 'running') {
        & $vbox controlvm $cloneName poweroff *> $null
        foreach ($attempt in 1..30) {
            Start-Sleep -Milliseconds 500
            if ((Get-T1OSVmState) -ne 'running') {
                break
            }
        }
    }
    if ($registered) {
        & $vbox unregistervm $cloneName --delete *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "could not remove disposable VM '$cloneName'."
        }
    }

    $report = [ordered]@{
        format = 1
        suite = $Suite
        vm = $cloneName
        started_at = $startedAt.ToString('o')
        finished_at = [DateTime]::UtcNow.ToString('o')
        boot_seconds = $bootSeconds
        source = 'embedded-current-build'
        source_build = $sourceBuildRoot
        passed = -not $failure -and -not ($results | Where-Object { -not $_.passed })
        error = $failure
        directives = $results
        services = $serviceStatus
        gui = if ($runGui) {
            [ordered]@{
                passed = -not $failure -and $guiChecks.Count -ge 7 -and -not ($guiChecks.Values -contains $false)
                mode = $guiMode
                checks = $guiChecks
                stages = $guiStages
                launch = $guiLaunch
                evidence_root = $guiEvidenceRoot
                resolution = @($Width, $Height)
            }
        }
        else {
            $null
        }
        features = if ($runFeatures) {
            [ordered]@{
                passed = -not $failure -and $featureChecks.Count -ge 12 -and -not ($featureChecks.Values -contains $false)
                checks = $featureChecks
                launches = $featureLaunches
                status = $featureStatus
                terminal_fixture = $terminalFixtureSource
            }
        }
        else {
            $null
        }
        serial_evidence = $evidencePath
    }
    $report | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Remove-T1OSVmTestDirectory
}

if ($failure) {
    Write-Host "T1OS VM test failed: $failure"
    Write-Host "Report: $reportPath"
    exit 1
}

Write-Host "T1OS VM $Suite suite passed."
Write-Host "Report: $reportPath"
Write-Host "Serial evidence: $evidencePath"
exit 0
