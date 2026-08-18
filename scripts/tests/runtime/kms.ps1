[CmdletBinding()]
param()

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$environmentRoot = Join-Path $projectRoot 'environment\software'
. (Join-Path $projectRoot 'scripts\common.ps1')
Set-Location -LiteralPath $environmentRoot

function Get-GraphicsBootState {

    $mountScript = Join-Path $projectRoot 'scripts/deployment/mount.ps1'
    $unmountScript = Join-Path $projectRoot 'scripts/deployment/unmount.ps1'
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

    $unmountScript = Join-Path $projectRoot 'scripts/deployment/unmount.ps1'

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


Invoke-GraphicsKms

Write-Host 'Runtime kms validation passed.'
