# build and run vmware.ps1

[CmdletBinding()]
param(
    [switch]$BuildOnly,
    [switch]$ForceConvert
)

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$environmentRoot = Join-Path $projectRoot 'environment\software'
. (Join-Path $PSScriptRoot '..\common.ps1')
Set-Location -LiteralPath $environmentRoot

if (Test-T1OSDiskMounted) {
    Write-Host 't1fs is mounted. unmount it before building the vmware vm.'
    exit 1
}

$logPath = Join-Path $environmentRoot "build-and-run-vmware.log"

Start-Transcript -Path $logPath -Append


$vmName   = "The One OS"
$isoPath  = Join-Path $environmentRoot "t1os-boot.iso"
$rawImagePath = Join-Path $environmentRoot 'storage.img'
$vmdkPath = Join-Path $environmentRoot "t1os-root.vmdk"
$convertScript = Join-Path $PSScriptRoot "convert vmware.ps1"
$createIsoScript = Join-Path $PSScriptRoot 'create iso.ps1'
$vmDir    = Join-Path $environmentRoot "vmware"
$vmxPath  = Join-Path $vmDir "$vmName.vmx"
$serialPath = Join-Path $environmentRoot 'vmware-serial.log'


Write-Host "locating VMware tools..."

$vmrun = Get-Command vmrun -ErrorAction SilentlyContinue
if (-not $vmrun) {
    Write-Host "vmrun not found."
    exit 1
}

$vdisk = Get-Command vmware-vdiskmanager -ErrorAction SilentlyContinue
if (-not $vdisk) {
    Write-Host "vmware-vdiskmanager not found."
    exit 1
}

$vboxCommand = Get-Command VBoxManage -ErrorAction SilentlyContinue
if (-not $vboxCommand) {
    $vboxDefault = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
    if (Test-Path -LiteralPath $vboxDefault -PathType Leaf) {
        $vboxPath = $vboxDefault
    }
}
else {
    $vboxPath = $vboxCommand.Source
}

$vboxRegistered = $false
if ($vboxPath) {
    $vboxStateLine = & $vboxPath showvminfo 'The One OS' --machinereadable 2>$null |
        Where-Object { $_ -match '^VMState=' } |
        Select-Object -First 1
    if ($LASTEXITCODE -eq 0 -and $vboxStateLine) {
        $vboxRegistered = $true
        $vboxState = ([string]$vboxStateLine).Split('=', 2)[1].Trim('"')
        if ($vboxState -ne 'poweroff') {
            Write-Host "the T1OS VirtualBox VM is $vboxState and is using the shared boot ISO. Power it off before rebuilding the VMware VM."
            exit 1
        }
    }
}


Assert-T1OSFilesystemHealthy -ImagePath $rawImagePath -Operation 'replacing the VMware VM'

if (-not (Test-Path $vmDir)) {
    New-Item -ItemType Directory -Path $vmDir | Out-Null
}

Write-Host "checking for existing vm(s) named '$vmName'..."

$existingVmxFiles = Get-ChildItem -Path $vmDir -Recurse -Filter "$vmName.vmx" -ErrorAction SilentlyContinue

foreach ($vmx in $existingVmxFiles) {

    Write-Host "found existing vmx: $($vmx.FullName)"
    Write-Host "stopping vm (if running)..."

    $runningVms = @(& $vmrun.Source -T ws list)
    $isRunning = $runningVms | Where-Object {
        [string]::Equals(([string]$_).Trim(), $vmx.FullName, [System.StringComparison]::OrdinalIgnoreCase)
    }
    if ($isRunning) {
        & $vmrun.Source -T ws stop "$($vmx.FullName)" soft | Out-Null
        foreach ($attempt in 1..30) {
            Start-Sleep -Milliseconds 500
            $runningVms = @(& $vmrun.Source -T ws list)
            $isRunning = $runningVms | Where-Object {
                [string]::Equals(([string]$_).Trim(), $vmx.FullName, [System.StringComparison]::OrdinalIgnoreCase)
            }
            if (-not $isRunning) {
                break
            }
        }
        if ($isRunning) {
            Write-Host 'the VMware guest did not stop cleanly; forcing it off before replacing its files...'
            & $vmrun.Source -T ws stop "$($vmx.FullName)" hard | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Host 'could not stop the existing VMware VM.'
                exit 1
            }
        }
    }


    Write-Host "deleting vm registration/files via vmrun..."

    & $vmrun.Source -T ws deleteVM "$($vmx.FullName)" | Out-Null


    Write-Host "removing leftover vm files..."

    Remove-Item -Path $vmx.Directory.FullName -Recurse -Force -ErrorAction SilentlyContinue
}

if ($existingVmxFiles) {
    Write-Host "existing vm(s) removed."
}

if (-not (Test-Path $vmDir)) {
    New-Item -ItemType Directory -Path $vmDir | Out-Null
}

if (-not (Test-Path -LiteralPath $createIsoScript -PathType Leaf)) {
    Write-Host "create iso.ps1 not found: $createIsoScript"
    exit 1
}

Write-Host 'regenerating the shared T1OS boot ISO...'
& pwsh -NoLogo -NoProfile -NonInteractive -File $createIsoScript
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $isoPath -PathType Leaf)) {
    Write-Host 'boot ISO creation failed.'
    exit 1
}

# create iso.ps1 replaces the shared ISO atomically. VirtualBox identifies DVD
# media separately from the pathname, so refresh the powered-off canonical VM's
# attachment before its old medium registration can decay to `emptydrive`.
if ($vboxRegistered) {
    Write-Host 'refreshing the canonical VirtualBox boot ISO attachment...'
    & $vboxPath storageattach $vmName `
        --storagectl 'SATA' --port 1 --device 0 `
        --type dvddrive --medium $isoPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'could not refresh the canonical VirtualBox boot ISO attachment.'
        exit 1
    }
}

$vmdkIsStale = (Test-Path -LiteralPath $vmdkPath -PathType Leaf) -and (
    (Get-Item -LiteralPath $rawImagePath).LastWriteTimeUtc -gt
    (Get-Item -LiteralPath $vmdkPath).LastWriteTimeUtc
)

if ($ForceConvert -or -not (Test-Path $vmdkPath) -or $vmdkIsStale) {

    if (-not (Test-Path $convertScript)) {
        Write-Host "convert vmware.ps1 not found."
        exit 1
    }

    Write-Host "converting raw disk using convert vmware.ps1..."

    & pwsh -NoLogo -NoProfile -NonInteractive -File "$convertScript"
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        Write-Host "disk conversion failed (exit code $exitCode)."
        exit 1
    }
}

if (-not (Test-Path $vmxPath)) {

    Write-Host "creating vmx file..."

@"
.encoding = "UTF-8"
config.version = "8"
virtualHW.version = "20"

displayName = "$vmName"
guestOS = "otherlinux-64"

memsize = "2048"
numvcpus = "2"

mks.enable3d = "TRUE"
svga.graphicsMemoryKB = "262144"

bios.bootOrder = "cdrom,hdd"

floppy0.present = "FALSE"

sata0.present = "TRUE"

sata0:0.present = "TRUE"
sata0:0.fileName = "$vmdkPath"

sata0:1.present = "TRUE"
sata0:1.fileName = "$isoPath"
sata0:1.deviceType = "cdrom-image"

ethernet0.present = "TRUE"
ethernet0.connectionType = "nat"
ethernet0.virtualDev = "e1000"

usb.present = "FALSE"

sound.present = "TRUE"
sound.autodetect = "TRUE"
sound.virtualDev = "hdaudio"
sound.fileName = "-1"

serial0.present = "TRUE"
serial0.fileType = "file"
serial0.fileName = "$serialPath"
serial0.tryNoRxLoss = "TRUE"
serial0.yieldOnMsrRead = "TRUE"

tools.syncTime = "TRUE"
time.synchronize.continue = "TRUE"
time.synchronize.restore = "TRUE"
time.synchronize.resume.disk = "TRUE"
time.synchronize.shrink = "TRUE"
time.synchronize.tools.startup = "TRUE"

"@ | Set-Content -Path $vmxPath -Encoding ASCII
}


Write-Host ""
Write-Host "vm '$vmName' created and configured."

if ($BuildOnly) {
    Write-Host 'vmware build completed. the vm was not started.'
    Stop-Transcript
    exit 0
}

Write-Host "starting vm..."

& $vmrun.Source -T ws start "$vmxPath" gui
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Host "failed to start vm (exit code $exitCode)."
    exit 1
}

Write-Host "vm started."

Stop-Transcript
