[CmdletBinding()]
param(
    [string]$ImagePath,

    [ValidateRange(30, 300)]
    [int]$TimeoutSeconds = 300
)

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
if ([string]::IsNullOrWhiteSpace($ImagePath)) {
    $ImagePath = Join-Path $projectRoot 'environment\hardware\t1os-hardware-usb.img'
}
$ImagePath = [System.IO.Path]::GetFullPath($ImagePath)
$manifestPath = "$ImagePath.json"
$logPath = Join-Path $projectRoot 'environment\hardware\qemu-hardware-serial.log'

foreach ($requiredFile in @($ImagePath, $manifestPath)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required QEMU test input not found: $requiredFile"
    }
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ([bool]$manifest.encrypted) {
    throw 'The unattended QEMU smoke test only accepts the non-encrypted development image.'
}

& pwsh -NoLogo -NoProfile -NonInteractive -File (Join-Path $PSScriptRoot '..\validate hardware usb image.ps1') -ImagePath $ImagePath
if ($LASTEXITCODE -ne 0) {
    throw 'Static image validation failed before QEMU launch.'
}

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

if (Test-Path -LiteralPath $logPath) {
    Remove-Item -LiteralPath $logPath -Force
}
$wslImage = ConvertTo-WslPath -WindowsPath $ImagePath
$wslLog = ConvertTo-WslPath -WindowsPath $logPath

$testCommand = @'
set -euo pipefail
image=$1
host_serial_log=$2
timeout_seconds=$3
work=/var/tmp/t1os-qemu-hardware
serial_log=$work/serial.log
monitor_socket=$work/monitor.sock

command -v qemu-system-x86_64 >/dev/null 2>&1 || {
    echo 'qemu-system-x86_64 is not installed.' >&2
    exit 127
}
command -v qemu-img >/dev/null 2>&1 || {
    echo 'qemu-img is not installed.' >&2
    exit 127
}

ovmf_code=
ovmf_vars=
for candidate in /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd; do
    [ -f "$candidate" ] && { ovmf_code=$candidate; break; }
done
for candidate in /usr/share/OVMF/OVMF_VARS_4M.fd /usr/share/OVMF/OVMF_VARS.fd; do
    [ -f "$candidate" ] && { ovmf_vars=$candidate; break; }
done
[ -n "$ovmf_code" ] && [ -n "$ovmf_vars" ] || {
    echo 'OVMF firmware files were not found.' >&2
    exit 127
}

case "$work" in
    /var/tmp/t1os-qemu-hardware) rm -rf -- "$work" ;;
    *) echo "Refusing to replace unexpected QEMU work path: $work" >&2; exit 1 ;;
esac
mkdir -p "$work"
cp -- "$ovmf_vars" "$work/OVMF_VARS.fd"
qemu-img create -q -f qcow2 -F raw -b "$image" "$work/t1os-overlay.qcow2"

# A clean development image correctly enters interactive first-run creation and
# cannot reach the lock screen without invented user input.  Inspect the base
# image before QEMU starts so the smoke test can require the appropriate final
# presentation barrier without weakening retained-user images.
mkdir -p "$work/inspect"
image_loop=$(losetup --find --show --partscan "$image")
mounted_inspect=0
cleanup_inspect() {
    set +e
    if [ "$mounted_inspect" = 1 ]; then
        umount "$work/inspect"
        mounted_inspect=0
    fi
    if [ -n "${image_loop:-}" ]; then
        losetup -d "$image_loop"
        image_loop=
    fi
}
trap cleanup_inspect EXIT HUP INT TERM
mount.ntfs-3g -o ro "${image_loop}p3" "$work/inspect"
mounted_inspect=1
if [ -s "$work/inspect/the one/master/master.txt" ]; then
    expected_first_run=0
else
    expected_first_run=1
fi
cleanup_inspect
trap - EXIT HUP INT TERM
rm -f -- "$serial_log"
copy_serial_log() {
    [ ! -f "$serial_log" ] || cp -- "$serial_log" "$host_serial_log"
}
trap copy_serial_log EXIT

accelerator=tcg,thread=multi
cpu_model=max
echo "QEMU accelerator: $accelerator"

stop_qemu() {
    if [ -S "$monitor_socket" ]; then
        printf 'system_powerdown\n' |
            timeout 1s nc -U "$monitor_socket" >/dev/null 2>&1 || true
    fi
    for _ in $(seq 1 30); do
        ! kill -0 "$qemu_pid" 2>/dev/null && return
        sleep 1
    done
    kill -TERM "$qemu_pid" 2>/dev/null || true
}

set +e
qemu-system-x86_64 \
        -machine q35 \
        -accel "$accelerator" \
        -cpu "$cpu_model" \
        -smp 4 \
        -m 4096 \
        -drive if=pflash,format=raw,readonly=on,file="$ovmf_code" \
        -drive if=pflash,format=raw,file="$work/OVMF_VARS.fd" \
        -drive if=none,id=t1os_usb,file="$work/t1os-overlay.qcow2",format=qcow2,cache=unsafe \
        -device qemu-xhci,id=xhci \
        -device usb-storage,bus=xhci.0,drive=t1os_usb,removable=on,bootindex=1 \
        -device usb-kbd \
        -device usb-tablet \
        -audiodev driver=none,id=audio0 \
        -device usb-audio,audiodev=audio0 \
        -device ich9-intel-hda \
        -device hda-duplex,audiodev=audio0 \
        -vga none \
        -device virtio-vga,xres=800,yres=600 \
        -display none \
        -vnc unix:"$work/vnc.sock" \
        -monitor unix:"$monitor_socket",server=on,wait=off \
        -serial file:"$serial_log" \
        -no-reboot &
qemu_pid=$!
deadline=$((SECONDS + timeout_seconds))
acceptance_seen=0
acceptance_deadline=0
fatal_seen=0

roothealth_ready() {
    grep -Fq '~ I verified and completed every qualified NTFS repair before mounting The One OS. ~' "$serial_log" 2>/dev/null ||
        grep -Fq '~ RootHealth verified the boot-critical NTFS metadata without a complete filesystem scan. ~' "$serial_log" 2>/dev/null
}

while kill -0 "$qemu_pid" 2>/dev/null; do
    if grep -Fq 'I CANNOT CONTINUE.' "$serial_log" 2>/dev/null || \
       grep -Fq 'I FOUND UNSAFE NTFS METADATA' "$serial_log" 2>/dev/null || \
       grep -Fq 'Kernel panic' "$serial_log" 2>/dev/null || \
       grep -Fq 'blocked for more than 120 seconds' "$serial_log" 2>/dev/null || \
       grep -Fiq 'DURING THE DRIVER-RESET PHASE' "$serial_log" 2>/dev/null || \
       grep -Fiq 'DURING THE FIRMWARE-RECOVERY-REBOOT PHASE' "$serial_log" 2>/dev/null || \
       grep -Fq 'GPU OWNER FAILED' "$serial_log" 2>/dev/null; then
        fatal_seen=1
        stop_qemu
        break
    fi
    common_ready=0
    if roothealth_ready && \
       grep -Fq '~ I verified The One OS root identity while it was read-only. ~' "$serial_log" 2>/dev/null && \
       grep -Fq 'I HAVE COMPLETED THE HANDOFF TO THE FIRST SYSTEM PROCESS.' "$serial_log" 2>/dev/null && \
       grep -Fq 'I AM SHOWING THE EARLY BOOT PROGRESS ON PROCESS ' "$serial_log" 2>/dev/null && \
       grep -Eq 'THE DRIVER SERVER IS READY\..*DRI/RENDERD128.*REPORTED 0 FAILURES\.' "$serial_log" 2>/dev/null && \
       grep -Eq 'THE WINDOW SERVER IS READY ON PROCESS [0-9]+ USING THE OPENGL BACKEND\.' "$serial_log" 2>/dev/null && \
       grep -Fiq 'DURING THE ACCELERATION-UNAVAILABLE PHASE' "$serial_log" 2>/dev/null && \
       grep -Fiq 'REPLACING OWNER WITH CPU-RENDERED KMS BEFORE ANIMATION' "$serial_log" 2>/dev/null && \
       grep -Fq 'HARDWARE ACCELERATION IS UNAVAILABLE' "$serial_log" 2>/dev/null && \
       grep -Fq 'I AM SWITCHING TO CPU DISPLAY OUTPUT.' "$serial_log" 2>/dev/null && \
       grep -Fq 'I HAVE STARTED A WINDOW SERVER ATTEMPT USING THE KMS-FRAMEBUFFER BACKEND ON PROCESS ' "$serial_log" 2>/dev/null && \
       grep -Eq 'THE WINDOW SERVER IS READY ON PROCESS [0-9]+ USING THE KMS-FRAMEBUFFER BACKEND\.' "$serial_log" 2>/dev/null && \
       grep -Fq 'I AM SHOWING THE BOOT PROGRESS ON PROCESS ' "$serial_log" 2>/dev/null && \
       grep -Fq 'I HAVE STARTED THE FIRST-RUN OR LOGIN EXPERIENCE USING THE KMS-FRAMEBUFFER GRAPHICS BACKEND.' "$serial_log" 2>/dev/null; then
        common_ready=1
    fi
    presentation_ready=0
    if [ "$common_ready" = 1 ]; then
        if [ "$expected_first_run" = 1 ]; then
            presentation_ready=1
        elif grep -Fq 'THE LOCK SCREEN SHOWED ITS FIRST FRAME ON PROCESS ' "$serial_log" 2>/dev/null && \
             grep -Fq 'I VERIFIED THE LOCK SCREEN AFTER THE DISPLAY HANDOFF ON PROCESS ' "$serial_log" 2>/dev/null; then
            presentation_ready=1
        fi
    fi
    if [ "$presentation_ready" = 1 ]; then
        if [ "$acceptance_seen" = 0 ]; then
            acceptance_seen=1
            acceptance_deadline=$((SECONDS + 15))
        elif [ "$SECONDS" -ge "$acceptance_deadline" ]; then
            stop_qemu
            break
        fi
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
        stop_qemu
        break
    fi
    sleep 1
done

wait "$qemu_pid"
qemu_status=$?
set -e

if [ "$acceptance_seen" = 0 ] && [ "$qemu_status" -ne 0 ] && [ "$qemu_status" -ne 143 ]; then
    echo "QEMU failed with status $qemu_status" >&2
    exit "$qemu_status"
fi

if [ "$fatal_seen" -ne 0 ]; then
    echo 'T1OS entered a fatal diagnostic state during the QEMU stability window.' >&2
    exit 1
fi

test -s "$serial_log"
roothealth_ready
grep -Fq '~ I verified The One OS root identity while it was read-only. ~' "$serial_log"
grep -Fq '~ I have prepared the root drive and will now hand control to GODDESS. ~' "$serial_log"
grep -Fq 'I HAVE COMPLETED THE HANDOFF TO THE FIRST SYSTEM PROCESS.' "$serial_log"
grep -Fq 'I AM SHOWING THE EARLY BOOT PROGRESS ON PROCESS ' "$serial_log"
grep -Eq 'THE DRIVER SERVER IS READY\..*DRI/RENDERD128.*REPORTED 0 FAILURES\.' "$serial_log"
grep -Eq 'THE WINDOW SERVER IS READY ON PROCESS [0-9]+ USING THE OPENGL BACKEND\.' "$serial_log"
grep -Fiq 'DURING THE ACCELERATION-UNAVAILABLE PHASE' "$serial_log"
grep -Fiq 'REPLACING OWNER WITH CPU-RENDERED KMS BEFORE ANIMATION' "$serial_log"
grep -Fq 'HARDWARE ACCELERATION IS UNAVAILABLE' "$serial_log"
grep -Fq 'I AM SWITCHING TO CPU DISPLAY OUTPUT.' "$serial_log"
grep -Fq 'I HAVE STARTED A WINDOW SERVER ATTEMPT USING THE KMS-FRAMEBUFFER BACKEND ON PROCESS ' "$serial_log"
grep -Eq 'THE WINDOW SERVER IS READY ON PROCESS [0-9]+ USING THE KMS-FRAMEBUFFER BACKEND\.' "$serial_log"
grep -Fq 'I AM SHOWING THE BOOT PROGRESS ON PROCESS ' "$serial_log"
grep -Fq 'I HAVE STARTED THE FIRST-RUN OR LOGIN EXPERIENCE USING THE KMS-FRAMEBUFFER GRAPHICS BACKEND.' "$serial_log"
if [ "$expected_first_run" = 0 ]; then
    grep -Fq 'THE LOCK SCREEN SHOWED ITS FIRST FRAME ON PROCESS ' "$serial_log"
    grep -Fq 'I VERIFIED THE LOCK SCREEN AFTER THE DISPLAY HANDOFF ON PROCESS ' "$serial_log"
fi
test "$(grep -Ec 'THE WINDOW SERVER IS READY ON PROCESS [0-9]+ USING THE OPENGL BACKEND\.' "$serial_log")" -eq 1
test "$(grep -Fic 'DURING THE ACCELERATION-UNAVAILABLE PHASE' "$serial_log")" -eq 1
# Normal consumer boot deliberately uses quiet loglevel=0. Driver readiness is
# therefore proven by the T1OS Driver Server hand-off above instead of by
# informational kernel lines which are intentionally absent.
! grep -Fq 'is not a valid root filesystem for The One OS' "$serial_log"
! grep -Fq 'I COULD NOT FIND THE ROOT FILESYSTEM' "$serial_log"
! grep -Fq 'SWITCH_ROOT RETURNED UNEXPECTEDLY' "$serial_log"
! grep -Fq 'ABORTING SYSTEM' "$serial_log"
! grep -Fq 'I CANNOT CONTINUE.' "$serial_log"
! grep -Fq 'I FOUND UNSAFE NTFS METADATA' "$serial_log"
! grep -Fq 'Kernel panic' "$serial_log"
! grep -Fq 'blocked for more than 120 seconds' "$serial_log"
! grep -Fiq 'DURING THE DRIVER-RESET PHASE' "$serial_log"
! grep -Fiq 'DURING THE BOOT-ANIMATION-PRESENTATION PHASE' "$serial_log"
! grep -Fiq 'DURING THE FIRMWARE-RECOVERY-REBOOT PHASE' "$serial_log"
! grep -Fiq 'I AM RESTARTING INTO FIRMWARE FRAMEBUFFER RECOVERY' "$serial_log"
! grep -Fq 'GPU OWNER FAILED' "$serial_log"

copy_serial_log
trap - EXIT
rm -rf -- "$work"
if [ "$expected_first_run" = 1 ]; then
    echo 'UEFI USB QEMU smoke test completed the software-renderer to CPU-KMS first-run hand-off.'
else
    echo 'UEFI USB QEMU smoke test completed the software-renderer to CPU-KMS lock-screen hand-off.'
fi
'@

# Keep the QEMU harness inside WSL. PowerShell's native pipeline supplies the
# final newline; the trailing comment safely absorbs its line ending.
$normalizedTestCommand = $testCommand.Replace("`r", '') + "`n# end"
$normalizedTestCommand | & wsl.exe -d Ubuntu -u root --exec bash -s -- $wslImage $wslLog $TimeoutSeconds
$testExitCode = $LASTEXITCODE
if ($testExitCode -ne 0) {
    throw "UEFI USB QEMU smoke test failed (exit code $testExitCode). See $logPath"
}

Write-Host 'UEFI USB QEMU smoke test passed.'
Write-Host "Serial log: $logPath"
