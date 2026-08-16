[CmdletBinding()]
param(
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$vmName = 'The One OS'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$environmentRoot = Join-Path $projectRoot 'environment'
. (Join-Path $PSScriptRoot 'common.ps1')
$vmxPath = Join-Path $environmentRoot "vmware\$vmName.vmx"
$rawImagePath = Join-Path $environmentRoot 'storage.img'
$vmdkPath = Join-Path $environmentRoot 't1os-root.vmdk'
$isoPath = Join-Path $environmentRoot 't1os-boot.iso'
$kernelPath = Join-Path $environmentRoot 'iso\boot\vmlinuz'
$initramfsPath = Join-Path $environmentRoot 'iso\boot\initramfs'
$grubConfigPath = Join-Path $environmentRoot 'iso\boot\grub\grub.cfg'
$initSourcePath = Join-Path $projectRoot 'source\entry\init\init software.sh'
$serialPath = Join-Path $environmentRoot 'vmware-serial.log'

$vmrun = Get-Command vmrun -ErrorAction SilentlyContinue
if (-not $vmrun) {
    throw 'vmrun was not found. install vmware workstation or add vmrun to path.'
}

if (-not (Test-Path -LiteralPath $vmxPath -PathType Leaf)) {
    throw "the vmware vm has not been built. run build for vmware first: $vmxPath"
}

Assert-T1OSArtifactCurrent `
    -ArtifactPath $vmdkPath `
    -InputPath @($rawImagePath) `
    -RebuildCommand 'scripts/build vmware.ps1'
Assert-T1OSArtifactCurrent `
    -ArtifactPath $isoPath `
    -InputPath @($kernelPath, $initramfsPath, $grubConfigPath, $initSourcePath) `
    -RebuildCommand 'scripts/build vmware.ps1'
Assert-T1OSBootRootIdentity -ImagePath $rawImagePath -GrubConfigPath $grubConfigPath | Out-Null

$vmxText = Get-Content -LiteralPath $vmxPath -Raw
foreach ($requiredSetting in @(
    "sata0:0.fileName = `"$vmdkPath`"",
    "sata0:1.fileName = `"$isoPath`"",
    'sata0:1.deviceType = "cdrom-image"',
    'ethernet0.connectionType = "nat"',
    'sound.virtualDev = "hdaudio"',
    'serial0.present = "TRUE"',
    "serial0.fileName = `"$serialPath`""
)) {
    if (-not $vmxText.Contains($requiredSetting)) {
        throw "the VMware configuration is incomplete or points at the wrong media. Missing: $requiredSetting. Run scripts/build vmware.ps1."
    }
}

$qemuImg = Get-Command qemu-img -ErrorAction SilentlyContinue
if ($qemuImg) {
    $diskInfoText = (& $qemuImg.Source info --output=json $vmdkPath) -join "`n"
    if ($LASTEXITCODE -ne 0) {
        throw 'qemu-img could not validate t1os-root.vmdk.'
    }
    $diskInfo = $diskInfoText | ConvertFrom-Json
    $rawLength = (Get-Item -LiteralPath $rawImagePath).Length
    if ([int64]$diskInfo.'virtual-size' -ne $rawLength) {
        throw "the VMware disk has the wrong virtual size ($($diskInfo.'virtual-size') instead of $rawLength). Run scripts/build vmware.ps1."
    }
}

if ($ValidateOnly) {
    Write-Host 'VMware VM setup is ready.'
    exit 0
}

$runningVms = @(& $vmrun.Source -T ws list)
$alreadyRunning = $runningVms | Where-Object {
    [string]::Equals(([string]$_).Trim(), $vmxPath, [System.StringComparison]::OrdinalIgnoreCase)
}
if ($alreadyRunning) {
    Write-Host "the vmware vm '$vmName' is already running."
    exit 0
}

Write-Host "starting vmware vm '$vmName'..."
& $vmrun.Source -T ws start $vmxPath gui
if ($LASTEXITCODE -ne 0) {
    throw "vmware could not start the vm (exit code $LASTEXITCODE)."
}

Write-Host 't1os started in vmware.'
exit 0
