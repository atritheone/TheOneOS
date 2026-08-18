[CmdletBinding()]
param(
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$vmName = 'The One OS'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$environmentRoot = Join-Path $projectRoot 'environment\software'
. (Join-Path $PSScriptRoot '..\common.ps1')
$rawImagePath = Join-Path $environmentRoot 'storage.img'
$vdiPath = Join-Path $environmentRoot 't1os-root.vdi'
$isoPath = Join-Path $environmentRoot 't1os-boot.iso'
$kernelPath = Join-Path $environmentRoot 'iso\boot\vmlinuz'
$initramfsPath = Join-Path $environmentRoot 'iso\boot\initramfs'
$grubConfigPath = Join-Path $environmentRoot 'iso\boot\grub\grub.cfg'
$initSourcePath = Join-Path $projectRoot 'source\entry\init\init software.sh'
$serialPath = Join-Path $environmentRoot 'vbox-serial.log'

function Get-T1OSVirtualBoxVmState {
    param(
        [Parameter(Mandatory)]
        [string]$VBoxManage,

        [Parameter(Mandatory)]
        [string]$Name
    )

    $info = @(& $VBoxManage showvminfo $Name --machinereadable 2>$null)
    if ($LASTEXITCODE -ne 0) {
        return $null
    }

    $stateLine = $info | Where-Object { $_ -match '^VMState=' } | Select-Object -First 1
    if (-not $stateLine) {
        throw "virtualbox did not report a state for '$Name'."
    }

    return ([regex]::Match($stateLine, '^VMState="(?<state>[^"]+)"$')).Groups['state'].Value
}

function Set-T1OSVirtualBoxDisplayHint {
    param(
        [Parameter(Mandatory)]
        [string]$VBoxManage,

        [Parameter(Mandatory)]
        [string]$Name
    )

    foreach ($attempt in 1..5) {
        & $VBoxManage controlvm $Name setvideomodehint 2560 1440 32 *> $null
        if ($LASTEXITCODE -eq 0) {
            return $true
        }
        Start-Sleep -Seconds 1
    }

    return $false
}

function ConvertFrom-T1OSMachineReadableInfo {
    param([Parameter(Mandatory)][string[]]$Lines)

    $values = @{}
    foreach ($line in $Lines) {
        $match = [regex]::Match([string]$line, '^"?(?<key>[^"=]+)"?=(?:"(?<quoted>.*)"|(?<raw>.*))$')
        if (-not $match.Success) {
            continue
        }
        $value = if ($match.Groups['quoted'].Success) {
            $match.Groups['quoted'].Value.Replace('\\', '\')
        }
        else {
            $match.Groups['raw'].Value
        }
        $values[$match.Groups['key'].Value] = $value
    }
    return $values
}

function Assert-T1OSVirtualBoxConfiguration {
    param(
        [Parameter(Mandatory)][string]$VBoxManage,
        [Parameter(Mandatory)][string]$Name
    )

    $info = @(& $VBoxManage showvminfo $Name --machinereadable 2>$null)
    if ($LASTEXITCODE -ne 0) {
        throw "the VirtualBox VM '$Name' is not registered. Run scripts/vm/build vbox.ps1."
    }

    $values = ConvertFrom-T1OSMachineReadableInfo -Lines $info
    $expected = [ordered]@{
        memory = '2048'
        cpus = '4'
        boot1 = 'dvd'
        boot2 = 'disk'
        graphicscontroller = 'vmsvga'
        vram = '256'
        accelerate3d = 'on'
        nic1 = 'nat'
        nictype1 = 'virtio'
        cableconnected1 = 'on'
        audio_out = 'on'
        'SATA-0-0' = $vdiPath
        'SATA-1-0' = $isoPath
        uartmode1 = "file,$serialPath"
    }

    $problems = @()
    foreach ($entry in $expected.GetEnumerator()) {
        if (-not $values.ContainsKey($entry.Key) -or $values[$entry.Key] -ne $entry.Value) {
            $actual = if ($values.ContainsKey($entry.Key)) { $values[$entry.Key] } else { '<missing>' }
            $problems += "$($entry.Key)=$actual (expected $($entry.Value))"
        }
    }
    if ($problems.Count -gt 0) {
        throw "the VirtualBox VM configuration is incomplete or points at the wrong media: $($problems -join '; '). Run scripts/vm/build vbox.ps1."
    }
}

Write-Host 'locating vboxmanage...'
$vbox = Get-Command VBoxManage -ErrorAction SilentlyContinue
if ($vbox) {
    $vboxPath = $vbox.Source
}
else {
    $vboxPath = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
    if (-not (Test-Path -LiteralPath $vboxPath -PathType Leaf)) {
        throw 'vboxmanage was not found. install virtualbox or add vboxmanage to path.'
    }
}

Assert-T1OSArtifactCurrent `
    -ArtifactPath $vdiPath `
    -InputPath @($rawImagePath) `
    -RebuildCommand 'scripts/vm/build vbox.ps1'
Assert-T1OSArtifactCurrent `
    -ArtifactPath $isoPath `
    -InputPath @($kernelPath, $initramfsPath, $grubConfigPath, $initSourcePath) `
    -RebuildCommand 'scripts/vm/build vbox.ps1'
Assert-T1OSBootRootIdentity -ImagePath $rawImagePath -GrubConfigPath $grubConfigPath | Out-Null
Assert-T1OSVirtualBoxConfiguration -VBoxManage $vboxPath -Name $vmName

if ($ValidateOnly) {
    $validatedState = Get-T1OSVirtualBoxVmState -VBoxManage $vboxPath -Name $vmName
    Write-Host "VirtualBox VM setup is ready (state=$validatedState)."
    exit 0
}

$vmState = $null
foreach ($attempt in 1..5) {
    $vmState = Get-T1OSVirtualBoxVmState -VBoxManage $vboxPath -Name $vmName
    if ($vmState) {
        break
    }
    Start-Sleep -Milliseconds 250
}

if (-not $vmState) {
    throw "the virtualbox vm '$vmName' has not been built. run build for vbox first."
}

if ($vmState -notin @('running', 'paused')) {
    foreach ($override in @(
        @('VBoxInternal/Devices/vga/0/Config/VMSVGAPciId', '0'),
        @('VBoxInternal/Devices/vga/0/Config/VMSVGAPciBarLayout', '1')
    )) {
        & $vboxPath setextradata $vmName $override[0] $override[1]
        if ($LASTEXITCODE -ne 0) {
            throw "virtualbox could not enable the T1OS VMSVGA video-command bridge (exit code $LASTEXITCODE)."
        }
    }
}

if ($vmState -eq 'running') {
    Write-Host "the virtualbox vm '$vmName' is already running."
    if (-not (Set-T1OSVirtualBoxDisplayHint -VBoxManage $vboxPath -Name $vmName)) {
        Write-Warning 'the running vm did not accept the 2560x1440 display hint; KMS will use the best advertised fallback.'
    }
    exit 0
}

if ($vmState -eq 'paused') {
    Write-Host "resuming paused virtualbox vm '$vmName'..."
    & $vboxPath controlvm $vmName resume
    if ($LASTEXITCODE -ne 0) {
        throw "virtualbox could not resume the vm (exit code $LASTEXITCODE)."
    }
}
else {
    Write-Host "starting virtualbox vm '$vmName'..."
    & $vboxPath startvm $vmName --type gui
    if ($LASTEXITCODE -ne 0) {
        throw "virtualbox could not start the vm (exit code $LASTEXITCODE)."
    }
}

foreach ($attempt in 1..20) {
    $vmState = Get-T1OSVirtualBoxVmState -VBoxManage $vboxPath -Name $vmName
    if ($vmState -eq 'running') {
        break
    }
    Start-Sleep -Milliseconds 500
}

if ($vmState -ne 'running') {
    throw "virtualbox reported vm state '$vmState' after launch instead of 'running'."
}

if (-not (Set-T1OSVirtualBoxDisplayHint -VBoxManage $vboxPath -Name $vmName)) {
    Write-Warning 'the running vm did not accept the 2560x1440 display hint; KMS will use the best advertised fallback.'
}

Write-Host 't1os started in virtualbox.'
exit 0
