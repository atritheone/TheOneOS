[CmdletBinding()]
param(
    [ValidateSet('Smoke', 'Brick', 'Gui', 'Features', 'Issues', 'Python', 'Full')]
    [string]$Suite = 'Brick',

    [string[]]$Directive,

    [ValidateSet('viewer', 'write', 'player-audio', 'player-video', 'array-opengl', 'chromium')]
    [string[]]$IssueCase,

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

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$environmentRoot = Join-Path $projectRoot 'environment\software'
$softwareRoot = $environmentRoot
$sourceBuildRoot = Join-Path $projectRoot 'source\build software'
$terminalFixtureSource = Join-Path $PSScriptRoot '..\fixtures\brick terminal emulator.py'
$reportPath = Join-Path $softwareRoot 't1os-vm-test-report.json'
$evidencePath = Join-Path $softwareRoot 't1os-vm-test-serial.log'
$guiEvidenceRoot = Join-Path $softwareRoot 't1os-vm-test-gui'
$baseVmName = 'T1OS Codex Test Base'
$baseSnapshot = 'codex-clean'
$shareName = 'T1OS_Codex_Test'
$token = [guid]::NewGuid().ToString('N').Substring(0, 12)
$cloneName = "T1OS Codex Test $token"
$runRoot = Join-Path $softwareRoot "t1os-vm-test-$token"
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
$issueChecks = [ordered]@{}
$issueLaunches = [ordered]@{}
$pythonChecks = [ordered]@{}
$pythonLaunches = [ordered]@{}
$pythonSettingsLaunch = $null
$pythonBrickMutationLaunch = $null
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
        [ValidateSet(
            'brick', 'brick-gui', 'settings-gui', 'settings-display-gui',
            'player-gui', 'player-audio-gui', 'viewer-gui', 'write-gui',
            'chromium-gui', 'array-opengl-gui', 'session-status',
            'feature-status', 'service-status', 'network-probe', 'close-fixed-guis',
            'creep-self-test'
        )]
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

function Send-T1OSCtrlShortcut {
    param([Parameter(Mandatory)][string]$ScanCode)

    $released = '{0:x2}' -f (([Convert]::ToInt32($ScanCode, 16) + 0x80) -band 0xff)
    Send-T1OSScanCodes -Codes @('1d', $ScanCode, $released, '9d')
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
        '1'='02'; '2'='03'; '3'='04'; '4'='05'; '5'='06'; '6'='07'; '7'='08'
        '8'='09'; '9'='0a'; '0'='0b'; '-'='0c'; ','='33'; '.'='34'; '/'='35'
    }
    $shiftedScanCodes = @{ ':'='27' }
    foreach ($character in $Text.ToCharArray()) {
        $key = [string]$character
        if ($scanCodes.ContainsKey($key)) {
            Send-T1OSKey -ScanCode $scanCodes[$key]
        }
        elseif ($shiftedScanCodes.ContainsKey($key)) {
            $scanCode = $shiftedScanCodes[$key]
            $released = '{0:x2}' -f (([Convert]::ToInt32($scanCode, 16) + 0x80) -band 0xff)
            Send-T1OSScanCodes -Codes @('2a', $scanCode, $released, 'aa')
        }
        else {
            throw "ASCII scan-code injection does not support '$key'."
        }
        Start-Sleep -Milliseconds $DelayMilliseconds
    }
}

function Get-T1OSImageStats {
    param([Parameter(Mandatory)][string]$Path)

    $bitmap = [System.Drawing.Bitmap]::new($Path)
    try {
        $nonBlack = 0
        $light = 0
        $red = 0
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
                if ($pixel.R -gt 180 -and $pixel.G -lt 40 -and $pixel.B -lt 40) {
                    $red++
                }
            }
        }

        return [ordered]@{
            width = $bitmap.Width
            height = $bitmap.Height
            samples = $samples
            non_black_samples = $nonBlack
            light_samples = $light
            red_samples = $red
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
        [int]$MinRedSamples = 0,
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
                $stats.red_samples -ge $MinRedSamples -and
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

function Wait-T1OSPythonIdle {
    param([int]$TimeoutSeconds = 300)

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $status = Invoke-T1OSAgentRequest -Action 'brick' -Command 'python status' -Order 0
        if ($status.passed) {
            $data = $status.response.result.results[0].data
            if (-not [bool]$data.transaction.running) {
                return $status
            }
        }
        Start-Sleep -Seconds 2
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'the managed Python transaction did not become idle.'
}

function Wait-T1OSPythonModule {
    param(
        [Parameter(Mandatory)][string]$Name,
        [bool]$Present = $true,
        [int]$TimeoutSeconds = 300
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $result = Invoke-T1OSAgentRequest -Action 'brick' `
            -Command "show python module $Name" -Order 0
        if ($Present -and $result.passed) {
            return $result
        }
        if (-not $Present -and -not $result.passed -and
            [string]$result.response.result.results[0].code -eq 'module_missing') {
            return $result
        }
        $feature = Get-T1OSFeatureStatus
        if ([string]$feature.settings_status.python_stage -eq 'python-error') {
            throw "Settings Python change failed: $([string]$feature.settings_status.python_code): $([string]$feature.settings_status.python_error)"
        }
        Start-Sleep -Seconds 2
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Python module state did not settle: name=$Name present=$Present"
}

function Wait-T1OSSettingsPythonOperation {
    param(
        [Parameter(Mandatory)][string]$Operation,
        [int]$TimeoutSeconds = 300
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $feature = Get-T1OSFeatureStatus
        $stage = [string]$feature.settings_status.python_stage
        if ($stage -eq 'python-error') {
            throw "Settings Python change failed: $([string]$feature.settings_status.python_code): $([string]$feature.settings_status.python_error)"
        }
        if ($stage -eq 'python-complete' -and
            [string]$feature.settings_status.python_operation -eq $Operation) {
            return $feature
        }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Settings Python operation did not complete: $Operation"
}

function Wait-T1OSSettingsPythonReady {
    param(
        [Parameter(Mandatory)][int]$ProcessId,
        [int]$TimeoutSeconds = 60
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $feature = Get-T1OSFeatureStatus
        $status = $feature.settings_status
        if ([int]$status.pid -eq $ProcessId -and
            [string]$status.section -eq 'python' -and
            [bool]$status.graphics_active -and
            -not [bool]$status.python_busy) {
            return $feature
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Settings Python page did not become idle: pid=$ProcessId"
}

function Wait-T1OSBrickPythonStage {
    param(
        [Parameter(Mandatory)][int]$ProcessId,
        [Parameter(Mandatory)][string]$Operation,
        [Parameter(Mandatory)][string]$Stage,
        [string]$PythonName = '',
        [int]$TimeoutSeconds = 300
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $feature = Get-T1OSFeatureStatus
        $status = $feature.brick_status
        if ([int]$status.pid -eq $ProcessId -and
            [string]$status.python_operation -eq $Operation -and
            ([string]::IsNullOrEmpty($PythonName) -or
             [string]$status.python_name -eq $PythonName)) {
            $actual = [string]$status.stage
            if ($actual -in @('python-auth-error', 'python-cancelled')) {
                throw "Brick Python authorisation failed: $actual $([string]$status.python_error)"
            }
            if ($actual -eq $Stage) {
                if ($Stage -eq 'python-complete' -and -not [bool]$status.python_ok) {
                    $detail = if ($null -ne $status.python_data) {
                        $status.python_data | ConvertTo-Json -Compress -Depth 8
                    } else { '{}' }
                    throw "Brick Python operation failed: $([string]$status.python_code): $([string]$status.python_error) data=$detail"
                }
                return $feature
            }
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Brick Python stage did not arrive: operation=$Operation stage=$Stage pid=$ProcessId"
}

function Wait-T1OSBrickStage {
    param(
        [Parameter(Mandatory)][int]$ProcessId,
        [Parameter(Mandatory)][string]$Stage,
        [int]$TimeoutSeconds = 60
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $feature = Get-T1OSFeatureStatus
        $status = $feature.brick_status
        if ([int]$status.pid -eq $ProcessId -and
            [string]$status.stage -eq $Stage) {
            return $feature
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Brick stage did not arrive: stage=$Stage pid=$ProcessId"
}

function Wait-T1OSCreepInteractiveStage {
    param(
        [Parameter(Mandatory)][string]$Stage,
        [Parameter(Mandatory)][int]$Sequence,
        [int]$TimeoutSeconds = 30
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $feature = Get-T1OSFeatureStatus
        $status = $feature.creep_interactive
        if ([string]$status.stage -eq 'failed') {
            $detail = $status | ConvertTo-Json -Compress -Depth 8
            throw "Creep failed before becoming interactive: $detail"
        }
        if ([string]$status.stage -eq $Stage -and
            [int]$status.sequence -eq $Sequence) {
            return $feature
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Creep interactive stage did not arrive: stage=$Stage sequence=$Sequence"
}

function Invoke-T1OSCreepFrontTest {
    Write-Host 'PYTHON: running and interacting with Creep in Brick front mode...'
    Start-Sleep -Seconds 2
    [void](Save-T1OSGuiStage -Name 'python-creep-launch' -TimeoutSeconds 30)
    [void](Wait-T1OSCreepInteractiveStage -Stage 'ready' -Sequence 0)
    $interactiveCommands = @(
        'set target 127.0.0.1:65535',
        'add endpoints api/v1,login',
        'set debug true',
        'show options',
        'help'
    )
    $sequence = 0
    foreach ($command in $interactiveCommands) {
        Send-T1OSAsciiScanText -Text $command -DelayMilliseconds 35
        Send-T1OSKey -ScanCode '1c'
        $sequence++
        $interactive = Wait-T1OSCreepInteractiveStage `
            -Stage 'running' -Sequence $sequence
    }
    $interactiveStatus = $interactive.creep_interactive
    if ([string]$interactiveStatus.target -ne '127.0.0.1:65535' -or
        -not [bool]$interactiveStatus.debug -or
        @($interactiveStatus.endpoints) -notcontains '/api' -or
        @($interactiveStatus.endpoints) -notcontains '/api/v1' -or
        @($interactiveStatus.endpoints) -notcontains '/login') {
        $detail = $interactiveStatus | ConvertTo-Json -Compress -Depth 8
        throw "Creep front-mode state did not match the entered commands: $detail"
    }
    [void](Save-T1OSGuiStage -Name 'python-creep-front' -TimeoutSeconds 30)
    Send-T1OSAsciiScanText -Text 'exit' -DelayMilliseconds 60
    Send-T1OSKey -ScanCode '1c'
    [void](Wait-T1OSCreepInteractiveStage -Stage 'exited' -Sequence $sequence)
    $pythonChecks.creep_front_interactive = $true
}

function Invoke-T1OSSettingsPythonInstall {
    param(
        [Parameter(Mandatory)][string]$Name,
        [switch]$Reuse,
        [switch]$CloseAfter
    )

    if ($Reuse) {
        $launch = $script:pythonSettingsLaunch
        if ($null -eq $launch) {
            throw 'Settings reuse was requested before the Python page was launched.'
        }
    }
    else {
        $launch = Invoke-T1OSAgentRequest -Action 'settings-gui' -Order 0
        $script:pythonSettingsLaunch = $launch
    }
    $pythonLaunches["settings-$Name"] = $launch
    if (-not $launch.passed) {
        throw "Settings could not be launched to install $Name."
    }
    if (-not $Reuse) {
        Start-Sleep -Seconds 3
        Send-T1OSWinShortcut -ScanCode '39'
        Start-Sleep -Seconds 1
    }
    [void](Wait-T1OSSettingsPythonReady `
        -ProcessId ([int]$launch.response.pid) -TimeoutSeconds 60)

    $scale = [Math]::Max(0.5, [Math]::Min($Width / 1920.0, $Height / 1080.0))
    $queryX = [int][Math]::Round(1000 * $scale)
    $queryY = 28 + [int][Math]::Round(162 * $scale)
    $actionX = $Width - [int][Math]::Round(81 * $scale)
    $confirmY = 28 + [int][Math]::Round(248 * $scale)

    Send-T1OSClick -X $queryX -Y $queryY
    Start-Sleep -Milliseconds 500
    Send-T1OSAsciiScanText -Text $Name -DelayMilliseconds 75
    Start-Sleep -Seconds 1
    Send-T1OSClick -X $actionX -Y $queryY
    Start-Sleep -Seconds 1
    Send-T1OSClick -X $actionX -Y $confirmY
    Start-Sleep -Seconds 1
    Send-T1OSAsciiScanText -Text $Password -DelayMilliseconds 75
    Send-T1OSKey -ScanCode '1c'

    [void](Wait-T1OSPythonModule -Name $Name -Present $true -TimeoutSeconds 300)
    [void](Wait-T1OSSettingsPythonOperation -Operation 'install_module' -TimeoutSeconds 300)
    $pythonChecks["settings_installed_$Name"] = $true
    if ($CloseAfter) {
        Start-Sleep -Seconds 1
        $closed = Invoke-T1OSAgentRequest -Action 'close-fixed-guis' -Order 0
        if (-not $closed.passed) {
            throw "Settings did not close cleanly after installing $Name."
        }
        $script:pythonSettingsLaunch = $null
    }
}

function Invoke-T1OSBrickPythonMutation {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Command
    )

    $launch = $script:pythonBrickMutationLaunch
    if ($null -eq $launch) {
        $launch = Invoke-T1OSAgentRequest -Action 'brick-gui' -Order 0
        $script:pythonBrickMutationLaunch = $launch
    }
    $pythonLaunches["brick-$Name"] = $launch
    if (-not $launch.passed) {
        throw "Brick could not be launched for Python directive: $Command"
    }
    if ($pythonLaunches.Count -eq 3) {
        # The two Settings launch records precede the first mutation record.
        Start-Sleep -Seconds 3
        Send-T1OSWinShortcut -ScanCode '39'
        Start-Sleep -Seconds 2
    }
    Send-T1OSText -Text $Command
    Send-T1OSKey -ScanCode '1c'
    $operation = switch -Regex ($Command) {
        '^install python wheel ' { 'install_wheel'; break }
        '^apply python lock ' { 'apply_lock'; break }
        '^install python module ' { 'install_module'; break }
        '^remove python module ' { 'remove_module'; break }
        '^pin python module ' { 'pin_module'; break }
        '^unpin python module ' { 'unpin_module'; break }
        '^update python module ' { 'update_module'; break }
        '^update python modules$' { 'update_modules'; break }
        '^repair python modules$' { 'repair_modules'; break }
        '^restore python modules$' { 'restore_modules'; break }
        '^clear python cache$' { 'clear_cache'; break }
        default { throw "No Python manager operation mapping for Brick directive: $Command" }
    }
    $brickPid = [int]$launch.response.pid
    [void](Wait-T1OSBrickPythonStage -ProcessId $brickPid -Operation $operation `
        -Stage 'python-password-ready' -TimeoutSeconds 30)
    # Brick's modal password reader consumes the keyboard stream.  Use actual
    # press/release scan codes so the test follows the same path as a physical
    # keyboard instead of VirtualBox's separate text-injection path.
    Send-T1OSAsciiScanText -Text $Password -DelayMilliseconds 100
    Send-T1OSKey -ScanCode '1c'
    [void](Wait-T1OSBrickPythonStage -ProcessId $brickPid -Operation $operation `
        -Stage 'python-complete' -TimeoutSeconds 300)
    [void](Wait-T1OSPythonIdle -TimeoutSeconds 300)
    $pythonChecks[$Name] = $true
}

function Assert-T1OSPythonDirectiveCode {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Command,
        [Parameter(Mandatory)][string]$ExpectedCode
    )

    $result = Invoke-T1OSAgentRequest -Action 'brick' -Command $Command -Order 0
    $code = [string]$result.response.result.results[0].code
    if ($result.passed -or $code -ne $ExpectedCode) {
        throw "Python directive '$Command' returned '$code', expected '$ExpectedCode'."
    }
    $pythonChecks[$Name] = $true
}

function Invoke-T1OSPythonDirectiveTest {
    Write-Host 'PYTHON: verifying the lowercase missing-module question...'
    # Reuse the already-focused, maximised Brick from the GUI smoke test. A
    # second fixed launch is intentionally not used because it would exercise
    # window-stack focus selection rather than the Python prompt itself.
    $promptLaunch = $script:guiLaunch
    if ($null -eq $promptLaunch -or -not $promptLaunch.passed) {
        throw 'The focused Brick window is unavailable for prompt testing.'
    }
    Send-T1OSAsciiScanText -Text 'run /software/creep.py' -DelayMilliseconds 35
    Send-T1OSKey -ScanCode '1c'
    $prompt = Wait-T1OSBrickStage `
        -ProcessId ([int]$promptLaunch.response.pid) `
        -Stage 'python-missing-prompt'
    $missing = @($prompt.brick_status.python_missing)
    if ($missing -notcontains 'requests' -or $missing -notcontains 'paramiko') {
        $detail = $prompt.brick_status | ConvertTo-Json -Compress -Depth 8
        throw "Brick did not identify Creep's missing modules: $detail"
    }
    [void](Save-T1OSGuiStage -Name 'python-missing-modules-question' -TimeoutSeconds 30)
    Send-T1OSAsciiScanText -Text 'no' -DelayMilliseconds 75
    Send-T1OSKey -ScanCode '1c'
    $answer = Wait-T1OSBrickStage `
        -ProcessId ([int]$promptLaunch.response.pid) `
        -Stage 'python-missing-answer'
    if ([string]$answer.brick_status.python_answer -cne 'no') {
        throw 'Brick did not accept the lowercase no answer.'
    }
    $pythonChecks.missing_module_prompt_lowercase_no = $true

    # Run the command again in the same focused Brick and take the affirmative
    # path. The detected order is stable because missingpythonmodules sorts it.
    Send-T1OSAsciiScanText -Text 'run /software/creep.py' -DelayMilliseconds 35
    Send-T1OSKey -ScanCode '1c'
    Start-Sleep -Seconds 1
    Send-T1OSAsciiScanText -Text 'yes' -DelayMilliseconds 75
    Send-T1OSKey -ScanCode '1c'
    $brickPid = [int]$promptLaunch.response.pid
    [void](Wait-T1OSBrickPythonStage -ProcessId $brickPid `
        -Operation 'install_module' -Stage 'python-password-ready' `
        -PythonName 'paramiko' -TimeoutSeconds 30)
    Send-T1OSAsciiScanText -Text $Password -DelayMilliseconds 100
    Send-T1OSKey -ScanCode '1c'
    [void](Wait-T1OSPythonModule -Name 'paramiko' -Present $true -TimeoutSeconds 300)
    Start-Sleep -Seconds 2
    [void](Wait-T1OSBrickPythonStage -ProcessId $brickPid `
        -Operation 'install_module' -Stage 'python-password-ready' `
        -PythonName 'requests' -TimeoutSeconds 30)
    Send-T1OSAsciiScanText -Text $Password -DelayMilliseconds 100
    Send-T1OSKey -ScanCode '1c'
    [void](Wait-T1OSPythonModule -Name 'requests' -Present $true -TimeoutSeconds 300)
    $pythonChecks.missing_module_prompt_lowercase_yes = $true
    $pythonChecks.missing_modules_installed = $true
    Invoke-T1OSCreepFrontTest

    Write-Host 'PYTHON: installing requests and paramiko through Settings...'
    Invoke-T1OSSettingsPythonInstall -Name 'requests'
    Invoke-T1OSSettingsPythonInstall -Name 'paramiko' -Reuse -CloseAfter

    Write-Host 'PYTHON: exercising every read-only Brick Python directive...'
    $queries = [ordered]@{
        python_status = 'python status'
        check_python = 'check python'
        check_python_modules = 'check python modules'
        python_history = 'python history'
        list_python_modules = 'list python modules'
        show_python_module = 'show python module requests'
        find_python_module = 'find python module requests'
        list_python_updates = 'list python updates'
    }
    foreach ($entry in $queries.GetEnumerator()) {
        $result = Invoke-T1OSAgentRequest -Action 'brick' -Command $entry.Value -Order 0
        if (-not $result.passed) {
            throw "Brick Python directive failed: $($entry.Value)"
        }
        $pythonChecks[$entry.Key] = $true
    }

    Write-Host 'PYTHON: exercising every Brick Python mutation directive...'
    Invoke-T1OSBrickPythonMutation -Name install_python_wheel `
        -Command 'install python wheel /software/t1os-python-index/packages/humanize-4.16.0-py3-none-any.whl'
    [void](Wait-T1OSPythonModule -Name 'humanize' -Present $true)

    $export = Invoke-T1OSAgentRequest -Action 'brick' `
        -Command 'export python lock /master/development/creep-lock.toml' `
        -Order 0
    if (-not $export.passed) {
        throw 'export python lock did not write the lock through Brick.'
    }
    $exportedFile = Invoke-T1OSAgentRequest -Action 'brick' `
        -Command 'show details /master/development/creep-lock.toml' -Order 0
    if (-not $exportedFile.passed) {
        throw 'the exported Python lock is not visible in the user filesystem.'
    }
    $pythonChecks.export_python_lock = $true

    Invoke-T1OSBrickPythonMutation -Name remove_wheel_before_apply `
        -Command 'remove python module humanize'
    [void](Wait-T1OSPythonModule -Name 'humanize' -Present $false)
    Invoke-T1OSBrickPythonMutation -Name apply_python_lock `
        -Command 'apply python lock /master/development/creep-lock.toml'
    $lockedModule = Wait-T1OSPythonModule -Name 'humanize' -Present $true
    if (-not [bool]$lockedModule.response.result.results[0].data.modules[0].pinned) {
        throw 'apply python lock did not restore the wheel-pinned humanize module.'
    }

    Invoke-T1OSBrickPythonMutation -Name install_python_module `
        -Command 'install python module humanize'
    [void](Wait-T1OSPythonModule -Name 'humanize' -Present $true)

    Invoke-T1OSBrickPythonMutation -Name pin_python_module `
        -Command 'pin python module humanize'
    $module = Wait-T1OSPythonModule -Name 'humanize' -Present $true
    if (-not [bool]$module.response.result.results[0].data.modules[0].pinned) {
        throw 'pin python module did not pin humanize.'
    }

    Invoke-T1OSBrickPythonMutation -Name unpin_python_module `
        -Command 'unpin python module humanize'
    $module = Wait-T1OSPythonModule -Name 'humanize' -Present $true
    if ([bool]$module.response.result.results[0].data.modules[0].pinned) {
        throw 'unpin python module left humanize pinned.'
    }

    Invoke-T1OSBrickPythonMutation -Name update_python_module `
        -Command 'update python module humanize'
    Invoke-T1OSBrickPythonMutation -Name update_python_modules `
        -Command 'update python modules'
    Invoke-T1OSBrickPythonMutation -Name repair_python_modules `
        -Command 'repair python modules'
    Invoke-T1OSBrickPythonMutation -Name clear_python_cache `
        -Command 'clear python cache'
    Invoke-T1OSBrickPythonMutation -Name remove_python_module `
        -Command 'remove python module humanize'
    [void](Wait-T1OSPythonModule -Name 'humanize' -Present $false)
    Invoke-T1OSBrickPythonMutation -Name restore_python_modules `
        -Command 'restore python modules'
    [void](Wait-T1OSPythonModule -Name 'humanize' -Present $true)

    $status = Get-T1OSFeatureStatus
    foreach ($moduleName in @('requests', 'paramiko')) {
        if (-not [bool]$status.python_module_availability.$moduleName) {
            throw "the adapted creep dependency is unavailable: $moduleName"
        }
    }
    $pythonChecks.creep_dependencies_importable = $true

    $closed = Invoke-T1OSAgentRequest -Action 'close-fixed-guis' -Order 0
    if (-not $closed.passed) {
        throw 'Brick did not close cleanly after the Python directive suite.'
    }
    $script:pythonBrickMutationLaunch = $null
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

    $scale = [Math]::Max(
        0.5,
        [Math]::Min($Width / 1920.0, $Height / 1080.0)
    )
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

function Invoke-T1OSIssueTest {
    $settingsNavigationFailure = ''
    Write-Host 'ISSUES: exercising Settings navigation through physical pointer input...'
    $launch = Invoke-T1OSAgentRequest -Action 'settings-display-gui' -Order 0
    $script:issueLaunches.settings = $launch
    if (-not $launch.passed) { throw 'the issue test could not launch Settings.' }
    Start-Sleep -Seconds 3
    Send-T1OSWinShortcut -ScanCode '39'
    Start-Sleep -Seconds 2
    $display = Save-T1OSGuiStage -Name '20-issues-settings-display' -TimeoutSeconds 30
    # Exercise the visible Master and About rows at the image's current 100%
    # scale.  The former 80%-scale coordinates hit Network and Recovery and
    # made a screenshot change look like a navigation pass.
    Send-T1OSClick -X 76 -Y 388
    Start-Sleep -Seconds 2
    $masterStatus = Get-T1OSFeatureStatus
    $script:issueLaunches['settings-master-status'] = $masterStatus
    if ([string]$masterStatus.settings_status.section -ne 'master') {
        $settingsDetail = $masterStatus.settings_status | ConvertTo-Json -Depth 5 -Compress
        $settingsNavigationFailure = "Settings did not select Master from physical pointer input: $settingsDetail"
    }
    $master = Save-T1OSGuiStage -Name '21-issues-settings-master' -DifferentFrom $display.sha256 -TimeoutSeconds 20
    Send-T1OSClick -X 76 -Y 532
    Start-Sleep -Seconds 2
    $aboutStatus = Get-T1OSFeatureStatus
    $script:issueLaunches['settings-about-status'] = $aboutStatus
    if ([string]$aboutStatus.settings_status.section -ne 'about') {
        $settingsDetail = $aboutStatus.settings_status | ConvertTo-Json -Depth 5 -Compress
        $settingsNavigationFailure = "Settings did not select About from physical pointer input: $settingsDetail"
    }
    [void](Save-T1OSGuiStage -Name '22-issues-settings-about' -DifferentFrom $master.sha256 -TimeoutSeconds 20)
    $script:issueChecks.settings_navigation_clicks = $true
    Send-T1OSAltF4
    Start-Sleep -Seconds 2

    $cases = @(
        [ordered]@{ action='viewer-gui'; name='viewer'; wait=6 },
        [ordered]@{ action='write-gui'; name='write'; wait=4 },
        [ordered]@{ action='player-audio-gui'; name='player-audio'; wait=8 },
        [ordered]@{ action='player-gui'; name='player-video'; wait=8 },
        [ordered]@{ action='array-opengl-gui'; name='array-opengl'; wait=8 },
        [ordered]@{ action='chromium-gui'; name='chromium'; wait=10 }
    )
    if ($IssueCase -and $IssueCase.Count -gt 0) {
        $selectedIssueCases = @($IssueCase | ForEach-Object { [string]$_ })
        $cases = @($cases | Where-Object { $_.name -in $selectedIssueCases })
    }
    $chromiumSelected = @($cases.name) -contains 'chromium'
    if ($chromiumSelected) {
        $networkProbe = Invoke-T1OSAgentRequest -Action 'network-probe' -Order 0
        $script:issueLaunches['network-probe'] = $networkProbe
        if (-not $networkProbe.passed) {
            throw 'The fixed guest DNS/TCP/TLS network probe failed before Chromium launch.'
        }
    }
    $previous = [string]$script:guiStages['04-desktop'].sha256
    $number = 23
    $chromiumPresentationStatus = $null
    foreach ($case in $cases) {
        $chromiumNavigationBaseline = $null
        Write-Host "ISSUES: launching $($case.name)..."
        $caseLaunch = Invoke-T1OSAgentRequest -Action $case.action -Order 0
        $script:issueLaunches[$case.name] = $caseLaunch
        if (-not $caseLaunch.passed) { throw "the issue test could not launch $($case.name)." }
        Start-Sleep -Seconds $case.wait
        if ($case.name -eq 'chromium') {
            # A first launch from the immutable runtime can spend more than
            # ten seconds starting the sandboxed GPU process.  Readiness is
            # the complete brokered transport contract, not merely a live
            # Python wrapper or a mapped but still-empty X11 window.
            # Match the guest supervisor's bounded cold-start allowance plus
            # its GPU-runtime verification interval.  A freshly cloned VDI
            # reaches BrowserWindow after roughly 45-50 seconds and its first
            # renderer after roughly 70 seconds, so the former 60-second host
            # poll stopped before the guest could finish a valid cold start.
            $presentationDeadline = [DateTime]::UtcNow.AddSeconds(150)
            do {
                $chromiumPresentationStatus = Get-T1OSServiceStatus
                $presentationChromiumLog = [string]$chromiumPresentationStatus.logs.'chromium.py'
                $presentationEngineLog = [string]$chromiumPresentationStatus.logs.'chromium-engine-debug'
                $presentationGraphicsLog = [string]$chromiumPresentationStatus.logs.'graphics.py'
                if (
                    $presentationChromiumLog -match 'Chromium T1OS GPU presentation authorized' -and
                    $presentationEngineLog -match 'T1OS_PRESENTATION_BRIDGE transport=rgb-gbm-dmabuf-v1' -and
                    $presentationGraphicsLog -match 'video connection authorized.*chromium-presentation'
                ) {
                    break
                }
                $chromiumLiveness = Get-T1OSFeatureStatus
                if (-not $chromiumLiveness.chromium_alive) {
                    throw 'Chromium exited before establishing its brokered GPU presentation path.'
                }
                Start-Sleep -Seconds 2
            } while ([DateTime]::UtcNow -lt $presentationDeadline)
            $chromiumNavigationBaseline = Save-T1OSGuiStage `
                -Name 'issues-chromium-about-blank' -TimeoutSeconds 30
            # This fixed-resolution VM run can physically exercise the visible
            # omnibox. Ctrl+A is then scoped to the location field itself.
            Send-T1OSClick -X 500 -Y 149
            Start-Sleep -Milliseconds 250
            Send-T1OSCtrlShortcut -ScanCode '1e'
            Start-Sleep -Milliseconds 250
            Send-T1OSText -Text 'data:text/html,%3Ctitle%3ET1OSDATA%3C%2Ftitle%3E%3Cbody%20style%3D%22background%3Ared%3Bcolor%3Awhite%3Bfont-size%3A72px%22%3ET1OSDATA%3C%2Fbody%3E'
            Send-T1OSKey -ScanCode '1c'
            $offlineDeadline = [DateTime]::UtcNow.AddSeconds(20)
            do {
                Start-Sleep -Milliseconds 500
                $offlineStatus = Get-T1OSServiceStatus
                $offlineChromiumLog = [string]$offlineStatus.logs.'chromium.py'
            } while (
                $offlineChromiumLog -notmatch 'chromium document title changed title="T1OSDATA"' -and
                [DateTime]::UtcNow -lt $offlineDeadline
            )
            if ($offlineChromiumLog -notmatch 'chromium document title changed title="T1OSDATA"') {
                throw 'Chromium did not load the deterministic offline document.'
            }
            $offlineStage = Save-T1OSGuiStage `
                -Name 'issues-chromium-offline' `
                -DifferentFrom $chromiumNavigationBaseline.sha256 `
                -MinRedSamples 5000 `
                -TimeoutSeconds 20

            # Exercise cursor semantics through the real Chromium renderer,
            # XFixes bridge, Chromium wrapper, and WindowServer.  Each third of
            # this deterministic page requests a distinct CSS cursor.
            Send-T1OSClick -X 500 -Y 149
            Start-Sleep -Milliseconds 250
            Send-T1OSCtrlShortcut -ScanCode '1e'
            Start-Sleep -Milliseconds 250
            Send-T1OSText -Text 'data:text/html,%3Ctitle%3ET1OSCURSOR%3C%2Ftitle%3E%3Cstyle%3Ehtml%2Cbody%7Bmargin%3A0%3Bheight%3A100%25%7Ddiv%7Bposition%3Afixed%3Btop%3A0%3Bbottom%3A0%3Bwidth%3A33.34%25%7D%23t%7Bleft%3A0%3Bcursor%3Atext%7D%23l%7Bleft%3A33.33%25%3Bcursor%3Apointer%7D%23b%7Bleft%3A66.66%25%3Bcursor%3Await%7D%3C%2Fstyle%3E%3Cdiv%20id%3Dt%3E%3C%2Fdiv%3E%3Cdiv%20id%3Dl%3E%3C%2Fdiv%3E%3Cdiv%20id%3Db%3E%3C%2Fdiv%3E'
            Send-T1OSKey -ScanCode '1c'
            $cursorPageDeadline = [DateTime]::UtcNow.AddSeconds(20)
            do {
                Start-Sleep -Milliseconds 500
                $cursorPageStatus = Get-T1OSServiceStatus
                $cursorPageLog = [string]$cursorPageStatus.logs.'chromium.py'
            } while (
                $cursorPageLog -notmatch 'chromium document title changed title="T1OSCURSOR"' -and
                [DateTime]::UtcNow -lt $cursorPageDeadline
            )
            if ($cursorPageLog -notmatch 'chromium document title changed title="T1OSCURSOR"') {
                throw 'Chromium did not load the deterministic cursor test document.'
            }
            $missingCursorModes = [System.Collections.Generic.List[string]]::new()
            foreach ($cursorProbe in @(
                @{ x = 250; mode = 'text' },
                @{ x = 650; mode = 'link' },
                @{ x = 1050; mode = 'busy' }
            )) {
                Send-T1OSMouseAbsolute -X $cursorProbe.x -Y 500
                $cursorDeadline = [DateTime]::UtcNow.AddSeconds(5)
                do {
                    Start-Sleep -Milliseconds 200
                    $cursorStatus = Get-T1OSServiceStatus
                    $cursorLog = [string]$cursorStatus.logs.'chromium.py'
                } while (
                    $cursorLog -notmatch "chromium cursor mode changed mode=$($cursorProbe.mode)" -and
                    [DateTime]::UtcNow -lt $cursorDeadline
                )
                if ($cursorLog -notmatch "chromium cursor mode changed mode=$($cursorProbe.mode)") {
                    $missingCursorModes.Add([string]$cursorProbe.mode)
                }
            }
            if ($missingCursorModes.Count -gt 0) {
                throw "Chromium did not translate these CSS cursors into native T1OS cursors: $($missingCursorModes -join ', ')."
            }
            $script:issueChecks.chromium_cursor_modes = $true

            # A document title is semantic renderer evidence. Do not accept a
            # changed hash, spinner, error page, or partially repainted frame
            # as successful internet navigation.
            Send-T1OSClick -X 500 -Y 149
            Start-Sleep -Milliseconds 250
            Send-T1OSCtrlShortcut -ScanCode '1e'
            Start-Sleep -Milliseconds 250
            Send-T1OSText -Text 'https://example.com'
            Send-T1OSKey -ScanCode '1c'
            $internetDeadline = [DateTime]::UtcNow.AddSeconds(45)
            do {
                Start-Sleep -Seconds 1
                $internetStatus = Get-T1OSServiceStatus
                $internetChromiumLog = [string]$internetStatus.logs.'chromium.py'
            } while (
                $internetChromiumLog -notmatch 'chromium document title changed title="Example Domain"' -and
                [DateTime]::UtcNow -lt $internetDeadline
            )
            if ($internetChromiumLog -notmatch 'chromium document title changed title="Example Domain"') {
                $failurePath = Join-Path $guiRunRoot 'issues-chromium-internet-failure.png'
                Invoke-T1OSVBox -Arguments @('controlvm', $cloneName, 'screenshotpng', $failurePath) -Quiet
                throw 'Chromium did not finish the external HTTPS navigation.'
            }
            $chromiumNavigationBaseline = $offlineStage
        }
        $stage = Save-T1OSGuiStage -Name ('{0}-issues-{1}' -f $number, $case.name) `
            -DifferentFrom $(if ($chromiumNavigationBaseline) { $chromiumNavigationBaseline.sha256 } else { $previous }) `
            -TimeoutSeconds 30
        $previous = $stage.sha256
        $status = Get-T1OSFeatureStatus
        if ($case.name -eq 'array-opengl' -and -not $status.opengl_scene_ready) {
            # The capability test continuously submits retained telemetry and
            # animation patches after its first accelerated frame. A single
            # status sample can therefore land on scene-submitted even though
            # the preceding managed-only frame is visibly presented. Wait for
            # the WindowServer's next physical GRAPHICS_COMMITTED receipt.
            $openglDeadline = [DateTime]::UtcNow.AddSeconds(10)
            do {
                Start-Sleep -Milliseconds 250
                $status = Get-T1OSFeatureStatus
            } while (
                -not $status.opengl_scene_ready -and
                [DateTime]::UtcNow -lt $openglDeadline
            )
        }
        $script:issueLaunches["$($case.name)-status"] = $status
        if ($case.name -eq 'viewer' -and -not $status.viewer_alive) { throw 'Viewer exited while loading the fixed image.' }
        if ($case.name -eq 'write' -and -not $status.write_alive) { throw 'Write exited while loading the non-empty file.' }
        if ($case.name -eq 'player-audio' -and -not $status.player_audio_alive) { throw 'Player exited while loading audio artwork.' }
        if ($case.name -eq 'player-video' -and (-not $status.player_alive -or -not $status.player_playback_ready)) { throw 'Player did not reach decoded video playback.' }
        if ($case.name -eq 'array-opengl' -and -not $status.opengl_scene_ready) {
            $openglDetail = $status.opengl_status | ConvertTo-Json -Depth 5 -Compress
            throw "OpenGL test did not commit an accelerated managed-only scene: $openglDetail"
        }
        if ($case.name -eq 'chromium' -and -not $status.chromium_alive) { throw 'Chromium exited after launch.' }
        if ($case.name -eq 'chromium') {
            $script:issueChecks.chromium_internet_navigation = $true
        }
        $script:issueChecks[$case.name] = $true
        $number++
        Send-T1OSAltF4
        Start-Sleep -Seconds 2
        $close = Invoke-T1OSAgentRequest -Action 'close-fixed-guis' -Order 0
        $script:issueLaunches["$($case.name)-close"] = $close
        if (-not $close.passed -or $close.response.source -ne 'deployed') {
            throw "the issue test could not close $($case.name) after verification."
        }
        Start-Sleep -Seconds 1
    }
    $script:serviceStatus = if ($chromiumPresentationStatus) {
        $chromiumPresentationStatus
    }
    else {
        Get-T1OSServiceStatus
    }
    $chromiumLog = [string]$script:serviceStatus.logs.'chromium.py'
    $chromiumEngineLog = [string]$script:serviceStatus.logs.'chromium-engine-debug'
    $graphicsLog = [string]$script:serviceStatus.logs.'graphics.py'
    if ($chromiumSelected) {
        if (
            $chromiumLog -match '(?i)engine supervisor failed|exited before creating a window' -or
            $chromiumEngineLog -match '(?im)^\[[^\r\n]*:FATAL:|zygote_host_impl_linux\.cc'
        ) {
            throw 'Chromium reported a fatal engine or zygote startup failure.'
        }
        if (
            $chromiumLog -notmatch 'Chromium T1OS GPU presentation authorized' -or
            $chromiumEngineLog -notmatch 'T1OS_PRESENTATION_BRIDGE transport=rgb-gbm-dmabuf-v1' -or
            $graphicsLog -notmatch 'video connection authorized.*chromium-presentation'
        ) {
            throw 'Chromium did not establish its brokered EGL/GBM GPU presentation path.'
        }
    }
    if ($graphicsLog -match 'rejected CPU damage') {
        throw 'The accelerated issue run attempted CPU-rendered window damage.'
    }
    if ($settingsNavigationFailure) {
        throw $settingsNavigationFailure
    }
}

function Remove-T1OSVmTestDirectory {
    if (-not (Test-Path -LiteralPath $runRoot)) {
        return
    }

    $resolvedRunRoot = [System.IO.Path]::GetFullPath($runRoot)
    $resolvedSoftwareRoot = [System.IO.Path]::GetFullPath($softwareRoot).TrimEnd('\') + '\'
    if (-not $resolvedRunRoot.StartsWith($resolvedSoftwareRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
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
        'Issues' { @('version') }
        'Python' { @('version') }
        'Full' { @('test brick', 'test directives') }
    }
}
$runGui = $Suite -in @('Gui', 'Features', 'Issues', 'Python', 'Full')
$runFeatures = $Suite -in @('Features', 'Full')
$runIssues = $Suite -eq 'Issues'
$runPython = $Suite -in @('Python', 'Full')
$deferredDirectives = @()

$script:vbox = Get-T1OSVBoxManage
$preparationScript = Join-Path $PSScriptRoot '..\vm\prepare vm test vbox.ps1'
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
    if ($runPython) {
        Invoke-T1OSPythonDirectiveTest
    }
    if ($runIssues) {
        Invoke-T1OSIssueTest
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
        issues = if ($runIssues) {
            [ordered]@{
                passed = -not $failure -and $issueChecks.Count -ge 7 -and -not ($issueChecks.Values -contains $false)
                checks = $issueChecks
                launches = $issueLaunches
            }
        }
        else {
            $null
        }
        python = if ($runPython) {
            [ordered]@{
                passed = -not $failure -and $pythonChecks.Count -ge 24 -and -not ($pythonChecks.Values -contains $false)
                checks = $pythonChecks
                launches = $pythonLaunches
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
