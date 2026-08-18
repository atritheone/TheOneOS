# build and run.ps1

[CmdletBinding()]
param(
    [switch]$BuildOnly
)

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$environmentRoot = Join-Path $projectRoot 'environment\software'
. (Join-Path $PSScriptRoot '..\common.ps1')
Set-Location -LiteralPath $environmentRoot

if (Test-T1OSDiskMounted) {
    Write-Host 't1fs is mounted. unmount it before building the virtualbox vm.'
    exit 1
}

$rawImagePath = Join-Path $environmentRoot 'storage.img'
Assert-T1OSFilesystemHealthy -ImagePath $rawImagePath -Operation 'replacing the VirtualBox VM'

$logPath = Join-Path $environmentRoot "build-and-run.log"

Start-Transcript -Path $logPath -Append

$vmName   = "The One OS"
$isoPath  = Join-Path $environmentRoot "t1os-boot.iso"
$vdiPath  = Join-Path $environmentRoot "t1os-root.vdi"
$serialPath = Join-Path $environmentRoot "vbox-serial.log"
$virtualBoxVersionFile = Join-Path $projectRoot 'source\settings\virtualbox\version.txt'

Write-Host "locating VBoxManage..."

$vbox = "VBoxManage"
& $vbox --version *> $null
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    $vboxDefault = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"

    if (Test-Path $vboxDefault) {
        $vbox = $vboxDefault
        & $vbox --version *> $null
        $exitCode = $LASTEXITCODE
    } else {
        Write-Host "vboxmanage not found in PATH or at $vboxDefault"
        exit 1
    }
}

Write-Host "using VBoxManage at: $vbox"
Write-Host ""

$vmwareVmxPath = Join-Path $environmentRoot 'vmware\The One OS.vmx'
$vmrunCommand = Get-Command vmrun -ErrorAction SilentlyContinue
if ($vmrunCommand -and (Test-Path -LiteralPath $vmwareVmxPath -PathType Leaf)) {
    $runningVmwareVms = @(& $vmrunCommand.Source -T ws list)
    $vmwareIsRunning = $runningVmwareVms | Where-Object {
        [string]::Equals(([string]$_).Trim(), $vmwareVmxPath, [System.StringComparison]::OrdinalIgnoreCase)
    }
    if ($vmwareIsRunning) {
        Write-Host 'the T1OS VMware VM is running and is using the shared boot ISO. Stop it before rebuilding the VirtualBox VM.'
        exit 1
    }
}

function Invoke-T1OSVBoxMutation {
    param(
        [Parameter(Mandatory)]
        [string]$Description,

        [Parameter(Mandatory)]
        [string[]]$VBoxArguments,

        [int]$MaximumAttempts = 40,

        [int]$RetryDelayMilliseconds = 500
    )

    $transientPattern = '(?i)(already locked for a session|being unlocked|object is not ready|VBOX_E_INVALID_OBJECT_STATE|E_ACCESSDENIED)'
    $waitingReported = $false

    foreach ($attempt in 1..$MaximumAttempts) {
        $commandOutput = @(& $vbox @VBoxArguments 2>&1)
        $commandExitCode = $LASTEXITCODE

        if ($commandExitCode -eq 0) {
            foreach ($line in $commandOutput) {
                Write-Host $line.ToString()
            }
            if ($attempt -gt 1) {
                Write-Host "VirtualBox became ready for $Description after $attempt attempts."
            }
            return 0
        }

        $commandText = ($commandOutput | ForEach-Object { $_.ToString() }) -join "`n"
        $isTransient = $commandText -match $transientPattern
        if ($isTransient -and $attempt -lt $MaximumAttempts) {
            if (-not $waitingReported) {
                Write-Host "VirtualBox is still releasing a session for $Description. waiting..."
                $waitingReported = $true
            }
            Start-Sleep -Milliseconds $RetryDelayMilliseconds
            continue
        }

        foreach ($line in $commandOutput) {
            Write-Host $line.ToString()
        }
        return $commandExitCode
    }

    return 1
}

function Get-T1OSVBoxVmState {
    $info = @(& $vbox showvminfo $vmName --machinereadable 2>$null)
    if ($LASTEXITCODE -ne 0) {
        return $null
    }

    $stateLine = $info | Where-Object { $_ -match '^VMState=' } | Select-Object -First 1
    if (-not $stateLine) {
        throw "VirtualBox did not report a state for '$vmName'."
    }

    return ([regex]::Match([string]$stateLine, '^VMState="(?<state>[^"]+)"$')).Groups['state'].Value
}

if (-not (Test-Path -LiteralPath $virtualBoxVersionFile -PathType Leaf)) {
    Write-Host "T1OS VirtualBox runtime version file not found at $virtualBoxVersionFile"
    exit 1
}

$hostVersionText = [string](& $vbox --version)
$guestVersionText = Get-Content -LiteralPath $virtualBoxVersionFile -Raw
$hostVersionMatch = [regex]::Match($hostVersionText.Trim(), '^(?<major>\d+)\.(?<minor>\d+)\.(?<patch>\d+)r(?<revision>\d+)')
$guestVersionMatch = [regex]::Match($guestVersionText.Trim(), 'VirtualBox Guest Additions (?<major>\d+)\.(?<minor>\d+)\.(?<patch>\d+) r(?<revision>\d+)')

if (-not $hostVersionMatch.Success -or -not $guestVersionMatch.Success) {
    Write-Host "Could not compare the host and T1OS VirtualBox versions. host='$hostVersionText' guest='$($guestVersionText.Trim())'"
    exit 1
}

$hostSeries = "$($hostVersionMatch.Groups['major'].Value).$($hostVersionMatch.Groups['minor'].Value)"
$guestSeries = "$($guestVersionMatch.Groups['major'].Value).$($guestVersionMatch.Groups['minor'].Value)"
$guestVersion = "$guestSeries.$($guestVersionMatch.Groups['patch'].Value)r$($guestVersionMatch.Groups['revision'].Value)"

if ($hostSeries -ne $guestSeries) {
    Write-Host "Incompatible VirtualBox series. host=$($hostVersionMatch.Value) guest=$guestVersion"
    exit 1
}

if ($hostVersionMatch.Groups['patch'].Value -ne $guestVersionMatch.Groups['patch'].Value -or
    $hostVersionMatch.Groups['revision'].Value -ne $guestVersionMatch.Groups['revision'].Value) {
    Write-Warning "VirtualBox host $($hostVersionMatch.Value) and Guest Additions $guestVersion differ, but both use the compatible $hostSeries series."
}
else {
    Write-Host "matched T1OS Guest Additions runtime: $guestVersion"
}
Write-Host ""

Write-Host "checking for existing vm '$vmName'..."
$vmState = Get-T1OSVBoxVmState
$vmExists = $null -ne $vmState

if ($vmState -in @('running', 'paused')) {
    # The attached ISO cannot be replaced safely while VirtualBox has an
    # active session. Stop the VM before generating any replacement media.
    Write-Host "vm is $vmState. attempting to power it off before rebuilding its media..."
    $exitCode = Invoke-T1OSVBoxMutation -Description 'power off' -VBoxArguments @('controlvm', $vmName, 'poweroff')
    if ($exitCode -ne 0) {
        Write-Host "failed to power off the existing vm (exit code $exitCode)."
        exit 1
    }

    foreach ($attempt in 1..20) {
        $vmState = Get-T1OSVBoxVmState
        if ($vmState -eq 'poweroff') {
            break
        }
        Start-Sleep -Milliseconds 500
    }

    if ($vmState -ne 'poweroff') {
        Write-Host "existing vm did not finish powering off; current state is '$vmState'."
        exit 1
    }
}

Write-Host "running create iso.ps1 to regenerate t1os-boot.iso..."

$createIsoScript = Join-Path $PSScriptRoot 'create iso.ps1'

if (-not (Test-Path -LiteralPath $createIsoScript -PathType Leaf)) {
    Write-Host "create iso.ps1 not found at $createIsoScript"
    exit 1
}

& pwsh -NoLogo -NoProfile -NonInteractive -File $createIsoScript
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Host "create iso.ps1 failed with exit code $exitCode."
    exit 1
}

if (-not (Test-Path -LiteralPath $isoPath -PathType Leaf)) {
    Write-Host "t1os-boot.iso was not produced at $isoPath."
    exit 1
}

Write-Host ""
if ($vmExists) {
    Write-Host "unregistering and deleting vm '$vmName'..."
    $exitCode = Invoke-T1OSVBoxMutation -Description 'VM removal' -VBoxArguments @('unregistervm', $vmName, '--delete')

    if ($exitCode -ne 0) {
        Write-Host "failed to unregister/delete existing vm (exit code $exitCode)."
        exit 1
    }

    Write-Host "existing vm removed."
} else {
    Write-Host "no existing vm named '$vmName' found."
}

Write-Host ""
Write-Host "running convert vbox.ps1 to regenerate t1os-root.vdi..."

$convertScript = Join-Path $PSScriptRoot "convert vbox.ps1"

if (-not (Test-Path $convertScript)) {
    Write-Host "convert vbox.ps1 not found at $convertScript"
    exit 1
}

& pwsh -NoLogo -NoProfile -NonInteractive -File "$convertScript"
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Host "convert vbox.ps1 failed with exit code $exitCode."
    exit 1
}

if (-not (Test-Path $vdiPath)) {
    Write-Host "t1os-root.vdi not found at $vdiPath after conversion."
    exit 1
}

Write-Host ""
Write-Host "creating new vm '$vmName'..."

& $vbox createvm --name "$vmName" --platform-architecture x86 --ostype "Linux_64" --register
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Host "createvm failed with exit code $exitCode."
    exit 1
}

Write-Host "configuring system settings..."

$exitCode = Invoke-T1OSVBoxMutation -Description 'system configuration' -VBoxArguments @(
    'modifyvm', $vmName,
    '--memory', '2048',
    '--ioapic', 'on',
    '--cpus', '4',
    '--x86-hpet', 'on',
    '--x86-pae', 'on',
    '--boot1', 'dvd', '--boot2', 'disk', '--boot3', 'none', '--boot4', 'none',
    '--chipset', 'piix3',
    '--mouse', 'usbtablet',
    '--keyboard', 'usb',
    '--usb-ohci', 'on',
    '--usb-xhci', 'on',
    '--clipboard-mode', 'bidirectional',
    '--clipboard-file-transfers', 'enabled',
    '--drag-and-drop', 'bidirectional',
    '--paravirt-provider', 'hyperv',
    '--hwvirtex', 'on',
    '--nested-paging', 'on'
)

if ($exitCode -ne 0) {
    Write-Host "modifyvm (system) failed with exit code $exitCode."
    exit 1
}

Write-Host "configuring display..."

$exitCode = Invoke-T1OSVBoxMutation -Description 'display configuration' -VBoxArguments @(
    'modifyvm', $vmName,
    '--graphicscontroller', 'vmsvga',
    '--vram', '256',
    '--accelerate-3d', 'on'
)

if ($exitCode -ne 0) {
    Write-Host "modifyvm (display) failed with exit code $exitCode."
    exit 1
}

Write-Host "enabling the T1OS VMSVGA video-command bridge..."

foreach ($override in @(
    @('VBoxInternal/Devices/vga/0/Config/VMSVGAPciId', '0'),
    @('VBoxInternal/Devices/vga/0/Config/VMSVGAPciBarLayout', '1')
)) {
    $exitCode = Invoke-T1OSVBoxMutation -Description 'VMSVGA video-command bridge' -VBoxArguments @(
        'setextradata', $vmName, $override[0], $override[1]
    )
    if ($exitCode -ne 0) {
        Write-Host "setextradata (VMSVGA video-command bridge) failed with exit code $exitCode."
        exit 1
    }
}

Write-Host "setting initial guest display hint to 2560x1440..."

$exitCode = Invoke-T1OSVBoxMutation -Description 'display size hint' -VBoxArguments @(
    'setextradata', $vmName, 'GUI/LastGuestSizeHint', '2560,1440'
)

if ($exitCode -ne 0) {
    Write-Host "setextradata (display hint) failed with exit code $exitCode."
    exit 1
}

$exitCode = Invoke-T1OSVBoxMutation -Description 'maximum guest resolution' -VBoxArguments @(
    'setextradata', $vmName, 'GUI/MaxGuestResolution', 'any'
)
if ($exitCode -ne 0) {
    Write-Host "setextradata (maximum guest resolution) failed with exit code $exitCode."
    exit 1
}

$exitCode = Invoke-T1OSVBoxMutation -Description 'custom video mode' -VBoxArguments @(
    'setextradata', $vmName, 'CustomVideoMode1', '2560x1440x32'
)
if ($exitCode -ne 0) {
    Write-Host "setextradata (custom video mode) failed with exit code $exitCode."
    exit 1
}

Write-Host "configuring audio (intel hd audio out)..."

$exitCode = Invoke-T1OSVBoxMutation -Description 'audio configuration' -VBoxArguments @(
    'modifyvm', $vmName,
    '--audio-driver', 'was',
    '--audio-controller', 'hda',
    '--audio-enabled', 'on',
    '--audio-out', 'on',
    '--audio-in', 'off'
)
if ($exitCode -ne 0) {
    Write-Host "modifyvm (audio) failed with exit code $exitCode."
    exit 1
}

Write-Host "configuring network adapter 1 as NAT with virtio-net and host-backed DNS..."

$exitCode = Invoke-T1OSVBoxMutation -Description 'network configuration' -VBoxArguments @(
    'modifyvm', $vmName,
    '--nic1', 'nat',
    '--nic-type1', 'virtio',
    '--cable-connected1', 'on',
    '--natdnsproxy1', 'on',
    '--natdnshostresolver1', 'on'
)

if ($exitCode -ne 0) {
    Write-Host "modifyvm (network) failed with exit code $exitCode."
    exit 1
}

Write-Host "configuring serial port COM1 log at $serialPath..."

if (Test-Path -LiteralPath $serialPath) {
    Remove-Item -LiteralPath $serialPath -Force
}

$exitCode = Invoke-T1OSVBoxMutation -Description 'serial-port configuration' -VBoxArguments @(
    'modifyvm', $vmName,
    '--uart1', '0x3F8', '4',
    '--uart-mode1', 'file', $serialPath
)

if ($exitCode -ne 0) {
    Write-Host "modifyvm (serial) failed with exit code $exitCode."
    exit 1
}

Write-Host "setting up storage controllers and attaching t1os-root.vdi + t1os-boot.iso..."

$exitCode = Invoke-T1OSVBoxMutation -Description 'SATA controller creation' -VBoxArguments @(
    'storagectl', $vmName, '--name', 'SATA', '--add', 'sata', '--controller', 'IntelAhci'
)

if ($exitCode -ne 0) {
    Write-Host "storagectl failed with exit code $exitCode."
    exit 1
}

$exitCode = Invoke-T1OSVBoxMutation -Description 'VDI attachment' -VBoxArguments @(
    'storageattach', $vmName,
    '--storagectl', 'SATA',
    '--port', '0', '--device', '0',
    '--type', 'hdd',
    '--medium', $vdiPath
)

if ($exitCode -ne 0) {
    Write-Host "storageattach (hdd) failed with exit code $exitCode."
    exit 1
}

$exitCode = Invoke-T1OSVBoxMutation -Description 'boot ISO attachment' -VBoxArguments @(
    'storageattach', $vmName,
    '--storagectl', 'SATA',
    '--port', '1', '--device', '0',
    '--type', 'dvddrive',
    '--medium', $isoPath
)

if ($exitCode -ne 0) {
    Write-Host "storageattach (dvd) failed with exit code $exitCode."
    exit 1
}

Write-Host ""
Write-Host "vm '$vmName' created and configured."
Write-Host "kernel serial log: $serialPath"

if ($BuildOnly) {
    Write-Host 'virtualbox build completed. the vm was not started.'
    Stop-Transcript
    exit 0
}

Write-Host "starting vm..."

$exitCode = Invoke-T1OSVBoxMutation -Description 'VM startup' -VBoxArguments @(
    'startvm', $vmName, '--type', 'gui'
)

if ($exitCode -ne 0) {
    Write-Host "failed to start vm (exit code $exitCode)."
    exit 1
}

Start-Sleep -Seconds 2
& $vbox controlvm "$vmName" setvideomodehint 2560 1440 32

if ($LASTEXITCODE -ne 0) {
    Write-Host "the running vm did not accept the 2560x1440 display hint; KMS will use the best advertised fallback."
}

Write-Host "vm started."
Stop-Transcript
