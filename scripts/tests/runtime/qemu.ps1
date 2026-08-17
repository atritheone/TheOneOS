[CmdletBinding()]
param(
    [switch]$OpenGL
)

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$environmentRoot = Join-Path $projectRoot 'environment'
. (Join-Path $projectRoot 'scripts\common.ps1')
Set-Location -LiteralPath $environmentRoot

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

Write-Host "checking that storage is not mounted..."

$mounted = Test-T1OSDiskMounted

if ($mounted) {
    Write-Host ""
    Write-Host "t1fs is mounted. running unmount..."

    $unmountScript = Join-Path $projectRoot 'scripts/unmount.ps1'

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



Write-Host 'Runtime qemu validation passed.'
