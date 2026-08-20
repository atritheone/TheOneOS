[CmdletBinding()]
param()

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path

function ConvertTo-T1OSWslPath {
    param([Parameter(Mandatory)][string]$Path)

    $converted = & wsl.exe -d Ubuntu --exec wslpath -a $Path
    if ($LASTEXITCODE -ne 0 -or -not $converted) {
        throw "Could not translate test path for WSL: $Path"
    }
    return ([string]($converted | Select-Object -First 1)).Trim()
}

$wslProjectRoot = ConvertTo-T1OSWslPath -Path $projectRoot
$initScript = Join-Path $projectRoot 'source\entry\init\init hardware.sh'
$angelContract = Join-Path $projectRoot 'source\entry\init\ANGEL.md'
$angelVoiceTest = Join-Path $projectRoot 'scripts\tests\test angel voice.py'
$angelRecoveryTest = Join-Path $projectRoot 'scripts\tests\test angel recovery.ps1'
$initramfsBuilder = Join-Path $projectRoot 'scripts\build\build hardware initramfs.ps1'
$bootPolicyBuilder = Join-Path $projectRoot 'scripts\build\build boot protected roots.py'
$ntfsCheckerBuilder = Join-Path $projectRoot 'scripts\build\build roothealth.ps1'
$ntfsCheckerTest = Join-Path $projectRoot 'scripts\tests\test roothealth.ps1'
$ntfsChecker = Join-Path $projectRoot 'environment\hardware\tools\roothealth'
$ntfsCheckerMetadata = Join-Path $projectRoot 'environment\hardware\tools\roothealth.json'
$ntfsCheckerLicense = Join-Path $projectRoot 'environment\hardware\tools\roothealth.COPYING'
$ntfsCheckerSourceArchive = Join-Path $projectRoot 'environment\hardware\tools\roothealth-source.tar.gz'
$ntfsCheckerProductPatch = Join-Path $projectRoot 'source\entry\roothealth\0001-roothealth-read-only-checker.patch'
$ntfsCheckerSecurityPatch = Join-Path $projectRoot 'source\entry\roothealth\0002-ntfs-3g-2026.7.7-index-hardening.patch'
$ntfsCheckerVerdictPatch = Join-Path $projectRoot 'source\entry\roothealth\0003-roothealth-verdict-hardening.patch'
$imageBuilder = Join-Path $projectRoot 'scripts\create hardware usb image.ps1'
$bundleBuilder = Join-Path $projectRoot 'scripts\create hardware usb bundle.ps1'
$bundleValidator = Join-Path $projectRoot 'scripts\test hardware usb bundle.ps1'
$flashScript = Join-Path $projectRoot 'scripts\flash hardware usb.ps1'
$imageValidator = Join-Path $projectRoot 'scripts\validate hardware usb image.ps1'
$productionPreparer = Join-Path $projectRoot 'scripts\build\prepare prod build.ps1'
$hardwareUsbWorkflow = Join-Path $projectRoot 'scripts\build\build hardware usb.ps1'
$kernelBuilder = Join-Path $projectRoot 'scripts\build\build hardware kernel.ps1'
$graphicsKernelBuilder = Join-Path $projectRoot 'scripts\build\build graphics kernel.ps1'
$rootPushScript = Join-Path $projectRoot 'scripts\deployment\push to disk.ps1'
$hardwareKernelPushScript = Join-Path $projectRoot 'scripts\deployment\push hardware kernel to usb.ps1'
$grubScript = Join-Path $projectRoot 'source\entry\grub\grub hardware 0.2.cfg'
$encryptedGrubScript = Join-Path $projectRoot 'source\entry\grub\grub hardware encrypted 0.2.cfg'
$grubTheme = Join-Path $projectRoot 'source\entry\grub\t1os hardware theme.txt'
$grubBackground = Join-Path $projectRoot 'source\entry\grub\t1os black background.png.base64'
$kernelConfig = Join-Path $projectRoot 'source\entry\kernel\T10Skernel hardware 0.19 settings.txt'
$kernelPolicy = Join-Path $projectRoot 'source\entry\kernel\t1os_lsm.c'
$goddessScript = Join-Path $projectRoot 'source\build software\GODDESS\GODDESS.py'
$expanseScript = Join-Path $projectRoot 'source\build software\expanse\expanse.py'
$authenticationBroker = Join-Path $projectRoot 'source\build software\broker\broker.py'
$inputServer = Join-Path $projectRoot 'source\build software\input\inputserver.py'
$hardwareRoot = Join-Path $projectRoot 'environment\hardware'
$kernel = Join-Path $hardwareRoot 'boot\vmlinuz-hardware'
$initramfs = Join-Path $hardwareRoot 'boot\initramfs-hardware'
$pythonManifest = Join-Path $projectRoot 'source\software\python\manifest.json'
$pythonRelease = [string](
    Get-Content -LiteralPath $pythonManifest -Raw | ConvertFrom-Json
).release
if ($pythonRelease -notmatch '^[0-9A-Za-z][0-9A-Za-z._+-]{0,127}$') {
    throw 'The canonical Python manifest has an invalid release identifier.'
}
$firmwareArchive = Join-Path $hardwareRoot 'firmware.tar.zst'
$firmwareManifest = Join-Path $hardwareRoot 't1os-firmware-manifest.json'
$moduleArchive = Join-Path $hardwareRoot 'modules.tar.zst'
$driverServer = Join-Path $projectRoot 'source\build software\drivers\driverserver.py'
$operationsScript = Join-Path $projectRoot 'source\build software\operations\operations.py'
$moduleLoader = Join-Path $projectRoot 'source\drivers\tools\modprobe'
$driverPolicy = Join-Path $projectRoot 'source\drivers\settings\policy.json'
$desktopCompatibility = Join-Path $projectRoot 'source\drivers\settings\desktop compatibility.json'
$compatibilityValidator = Join-Path $projectRoot 'scripts\audits\validate hardware compatibility.ps1'
$driverRuntime = Join-Path $projectRoot 'source\drivers\settings\runtime.json'
$networkServer = Join-Path $projectRoot 'source\build software\network\network.py'
$wirelessEngine = Join-Path $projectRoot 'source\software\network\wireless-engine'
$networkLoader = Join-Path $projectRoot 'source\catalogue\network\ld-linux-x86-64.so.2'
$networkCertificates = Join-Path $projectRoot 'source\settings\network\cacerts.pem'
$graphicsCatalogueRoot = Join-Path $projectRoot 'source\catalogue\graphics'
$graphicsCatalogue = Join-Path $graphicsCatalogueRoot 'catalogue.json'
$intelVaapi = Join-Path $graphicsCatalogueRoot 'drivers\iHD_drv_video.so'
$r600Vaapi = Join-Path $graphicsCatalogueRoot 'drivers\r600_drv_video.so'
$radeonsiVaapi = Join-Path $graphicsCatalogueRoot 'drivers\radeonsi_drv_video.so'
$nouveauVaapi = Join-Path $graphicsCatalogueRoot 'drivers\nouveau_drv_video.so'
$virtioVaapi = Join-Path $graphicsCatalogueRoot 'drivers\virtio_gpu_drv_video.so'
$vmwgfxVaapi = Join-Path $graphicsCatalogueRoot 'drivers\vmwgfx_drv_video.so'
$nouveauDrm = Join-Path $graphicsCatalogueRoot 'libdrm_nouveau.so.2'
$nouveauVulkan = Join-Path $graphicsCatalogueRoot 'libvulkan_nouveau.so'
$vulkanLoader = Join-Path $projectRoot 'source\catalogue\graphics\libvulkan.so.1'
$nvidiaEgl = Join-Path $graphicsCatalogueRoot 'nvidia\libEGL.so.1'
$nvidiaGles = Join-Path $graphicsCatalogueRoot 'nvidia\libGLESv2.so.2'
$nvidiaEglVendor = Join-Path $graphicsCatalogueRoot 'nvidia\egl_vendor.d\10_nvidia.json'
$nvidiaGbmBackend = Join-Path $graphicsCatalogueRoot 'nvidia\gbm\nvidia-drm_gbm.so'
$nvidiaPathProvider = Join-Path $graphicsCatalogueRoot 'nvidia\t1os-nvidia-path-provider.so'
$nvidiaPathProviderSource = Join-Path $projectRoot 'source\entry\graphics\t1os_nvidia_path_provider.c'
$nvidiaRuntime = Join-Path $graphicsCatalogueRoot 'nvidia\runtime.json'
$nvidiaVaapi = Join-Path $graphicsCatalogueRoot 'drivers\nvidia_drv_video.so'
$nvidiaCuda = Join-Path $graphicsCatalogueRoot 'nvidia\libcuda.so.1'
$nvidiaNvcuvid = Join-Path $graphicsCatalogueRoot 'nvidia\libnvcuvid.so.1'
$nvidiaPtxjit = Join-Path $graphicsCatalogueRoot 'nvidia\libnvidia-ptxjitcompiler.so.1'
$gstreamerCore = Join-Path $graphicsCatalogueRoot 'libgstreamer-1.0.so.0'
$gstreamerBase = Join-Path $graphicsCatalogueRoot 'libgstbase-1.0.so.0'
$gstreamerCodecParsers = Join-Path $graphicsCatalogueRoot 'libgstcodecparsers-1.0.so.0'
$mediaDecodeService = Join-Path $projectRoot 'source\software\audio\t1-media-decoderd'
$mediaDecodeWorker = Join-Path $projectRoot 'source\software\audio\t1-video-decode'
$audioRuntimeManifest = Join-Path $projectRoot 'source\software\audio\manifest.json'
$mediaDecodeServiceSource = Join-Path $projectRoot 'source\native\video\t1_media_decoded.c'
$mediaDecodeWorkerSource = Join-Path $projectRoot 'source\native\video\t1_media_decode_worker.c'
$mediaDecodeProtocolSource = Join-Path $projectRoot 'source\native\video\t1_media_decode_protocol.h'
$chromiumServer = Join-Path $projectRoot 'source\build software\chromium\chromium.py'
$chromiumEngine = Join-Path $projectRoot 'source\software\chromium\program\chrome'
$chromiumSandbox = Join-Path $projectRoot 'source\software\chromium\program\chrome-sandbox'
$chromiumLibc = Join-Path $projectRoot 'source\software\chromium\libraries\libc.so.6'
$chromiumLibasound = Join-Path $projectRoot 'source\software\chromium\libraries\libasound.so.2'
$chromiumProvider = Join-Path $projectRoot 'source\software\chromium\t1os-path-provider.so'
$chromiumProviderSource = Join-Path $projectRoot 'source\entry\chromium\t1os_path_provider.c'
$chromiumInputBridge = Join-Path $projectRoot 'source\software\chromium\tools\t1os-xinput'
$chromiumInputBridgeSource = Join-Path $projectRoot 'source\entry\chromium\t1os_xinput.c'
$chromiumWindowManager = Join-Path $projectRoot 'source\software\chromium\tools\t1os-xwm'
$chromiumWindowManagerSource = Join-Path $projectRoot 'source\entry\chromium\t1os_xwm.c'
$windowServer = Join-Path $projectRoot 'source\build software\windows\windowserver.py'
$brickScript = Join-Path $projectRoot 'source\build software\brick\brick.py'
$chromiumSubprocess = Join-Path $projectRoot 'source\software\chromium\tools\t1os-chrome-subprocess'
$chromiumSubprocessSource = Join-Path $projectRoot 'source\entry\chromium\t1os_chrome_subprocess.c'
$runtimePathContract = Join-Path $projectRoot 'source\settings\runtime paths.json'
$wslInit = (& wsl.exe -d Ubuntu --exec wslpath -a $initScript | Select-Object -First 1).Trim()
$wslInitramfs = (& wsl.exe -d Ubuntu --exec wslpath -a $initramfs | Select-Object -First 1).Trim()
$wslModules = (& wsl.exe -d Ubuntu --exec wslpath -a $moduleArchive | Select-Object -First 1).Trim()
$wslFirmware = (& wsl.exe -d Ubuntu --exec wslpath -a $firmwareArchive | Select-Object -First 1).Trim()
$wslModuleLoader = (& wsl.exe -d Ubuntu --exec wslpath -a $moduleLoader | Select-Object -First 1).Trim()
$wslWirelessEngine = (& wsl.exe -d Ubuntu --exec wslpath -a $wirelessEngine | Select-Object -First 1).Trim()
$wslNetworkLoader = (& wsl.exe -d Ubuntu --exec wslpath -a $networkLoader | Select-Object -First 1).Trim()
$wslNetworkCatalogue = (& wsl.exe -d Ubuntu --exec wslpath -a (Split-Path -Path $networkLoader -Parent) | Select-Object -First 1).Trim()
$wslChromiumEngine = (& wsl.exe -d Ubuntu --exec wslpath -a $chromiumEngine | Select-Object -First 1).Trim()
$wslChromiumSandbox = (& wsl.exe -d Ubuntu --exec wslpath -a $chromiumSandbox | Select-Object -First 1).Trim()
$wslChromiumLibc = (& wsl.exe -d Ubuntu --exec wslpath -a $chromiumLibc | Select-Object -First 1).Trim()
$wslChromiumLibasound = (& wsl.exe -d Ubuntu --exec wslpath -a $chromiumLibasound | Select-Object -First 1).Trim()
$wslChromiumProvider = (& wsl.exe -d Ubuntu --exec wslpath -a $chromiumProvider | Select-Object -First 1).Trim()
$wslChromiumInputBridge = (& wsl.exe -d Ubuntu --exec wslpath -a $chromiumInputBridge | Select-Object -First 1).Trim()
$wslChromiumSubprocess = (& wsl.exe -d Ubuntu --exec wslpath -a $chromiumSubprocess | Select-Object -First 1).Trim()
$wslNvidiaPathProvider = (& wsl.exe -d Ubuntu --exec wslpath -a $nvidiaPathProvider | Select-Object -First 1).Trim()
$wslNvidiaVaapi = (& wsl.exe -d Ubuntu --exec wslpath -a $nvidiaVaapi | Select-Object -First 1).Trim()
$wslMediaDecodeService = (& wsl.exe -d Ubuntu --exec wslpath -a $mediaDecodeService | Select-Object -First 1).Trim()
$wslMediaDecodeWorker = (& wsl.exe -d Ubuntu --exec wslpath -a $mediaDecodeWorker | Select-Object -First 1).Trim()

$linuxCheck = @'
set -euo pipefail
trap 'status=$?; printf "Linux artifact check failed at line %s (exit %s): %s\n" "$LINENO" "$status" "$BASH_COMMAND" >&2' ERR
init=$1
initramfs=$2
modules=$3
module_loader=$4
wireless_engine=$5
network_loader=$6
network_catalogue=$7
chromium_engine=$8
chromium_provider=$9
chromium_sandbox=${10}
chromium_libc=${11}
chromium_input_bridge=${12}
chromium_libasound=${13}
chromium_subprocess=${14}
nvidia_path_provider=${15}
nvidia_vaapi=${16}
firmware=${17}
media_decode_service=${18}
media_decode_worker=${19}
expected_python_release=${20}
module_work=/var/tmp/t1os-module-validate
shellcheck -s sh "$init"

offset=$(python3 - "$initramfs" <<'PY'
from pathlib import Path
import sys
data = Path(sys.argv[1]).read_bytes()
magic = b'\x1f\x8b\x08'
offset = next(
    (
        position
        for position in range(0, len(data) - len(magic) + 1, 512)
        if data[position:position + len(magic)] == magic
    ),
    -1,
)
if offset < 0:
    raise SystemExit('512-byte-aligned gzip member not found in initramfs')
print(offset)
PY
)
early_listing=$(cpio --numeric-uid-gid -tv < "$initramfs" 2>/dev/null)
main_listing=$(
    dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none |
        gzip -cd |
        cpio --numeric-uid-gid -tv 2>/dev/null
)
validate_archive_modes() {
    archive_kind=$1
    awk -v archive_kind="$archive_kind" '
        {
            mode=$1
            uid=$3
            gid=$4
            path=$NF
            expected=""
            if (uid != "0" || gid != "0") bad=1
            if (substr(mode, 1, 1) == "d") {
                expected="drwxr-xr-x"
            } else if (substr(mode, 1, 1) == "-") {
                expected="-rw-r--r--"
                if (archive_kind == "main" && (path == "protected-roots.tsv" || path == "profiled-python-entrypoints.tsv")) {
                    expected="-r--r--r--"
                } else if (archive_kind == "main" && (path == "init" || path == "angel-recovery" || path ~ /^(bin|sbin)\// || path ~ /(^|\/)ld-linux[^\/]*$/)) {
                    expected="-rwxr-xr-x"
                }
            } else {
                bad=1
            }
            if (expected != "" && mode != expected) bad=1
        }
        END { exit bad ? 1 : 0 }
    '
}
printf '%s\n' "$early_listing" | validate_archive_modes early
printf '%s\n' "$main_listing" | validate_archive_modes main
test "$(
    dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none |
        gzip -cd |
        cpio -i --to-stdout init 2>/dev/null |
        sha256sum | awk '{print $1}'
)" = "$(sha256sum "$init" | awk '{print $1}')"
dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | cpio -it 2>/dev/null | grep -qx 'sbin/cryptsetup'
dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | cpio -it 2>/dev/null | grep -qx 'sbin/roothealth'
dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | cpio -it 2>/dev/null | grep -qx 'sbin/recoveryauth'
dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | cpio -it 2>/dev/null | grep -qx 'lib64/ld-linux-x86-64.so.2'
dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | cpio -it 2>/dev/null | grep -qx 'bin/sh'
dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | cpio -it 2>/dev/null | grep -qx 'bin/mdev'
dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | cpio -it 2>/dev/null | grep -qx 'protected-roots.tsv'
dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | cpio -it 2>/dev/null | grep -qx 'profiled-python-entrypoints.tsv'
(
    initramfs_work=$(mktemp -d /var/tmp/t1os-initramfs-policy-validate.XXXXXX)
    trap 'rm -rf -- "$initramfs_work"' EXIT
    dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none |
        gzip -cd |
        (cd "$initramfs_work" && cpio -id --quiet)

    "$initramfs_work/bin/busybox" sh -eu -s -- \
        "$initramfs_work" "$expected_python_release" <<'BOOT_POLICY_TEST'
root=$1
expected_python_release=$2
definitions=$("$root/bin/busybox" sed '/^\. \/angel-recovery$/d;/^mount_pseudo_filesystems$/,$d' "$root/init")
eval "$definitions"
busybox="$root/bin/busybox"
protected_inventory="$root/protected-roots.tsv"
profiled_inventory="$root/profiled-python-entrypoints.tsv"

secure_protected_directory "$root"
secure_protected_file "$root/init" 0555
secure_protected_file "$protected_inventory" 0444
secure_protected_file "$profiled_inventory" 0444
[ "$("$busybox" sed -n '$=' "$profiled_inventory")" -gt 0 ]
validate_protected_inventory_file

"$busybox" awk -F '\t' '
    $1 == "H" && $2 == "1" && $3 == expected && $5 == "6" { release = 1 }
    $1 == "F" && $2 == "python_software" && $3 == "bin/python" { stable = 1 }
    $1 == "F" && $2 == "python_software" && $3 == "bin/python3.14" { versioned = 1 }
    $1 == "F" && $2 == "python_software" && $3 == "bin/python3.13" { compatibility = 1 }
    $1 == "D" && $2 == "python_software" && $3 == "lib/python3.14" { stdlib = 1 }
    $2 == "python_software" && $3 ~ /^lib\/python3\.13(\/|$)/ { obsolete = 1 }
    END { exit !(release && stable && versioned && compatibility && stdlib && !obsolete) }
' expected="$expected_python_release" "$protected_inventory"

malformed_inventory="$root/protected-roots-malformed.tsv"
"$busybox" cp "$protected_inventory" "$malformed_inventory"
"$busybox" chmod 0644 "$malformed_inventory"
"$busybox" printf 'X\tunexpected\n' >>"$malformed_inventory"
"$busybox" chmod 0444 "$malformed_inventory"
protected_inventory=$malformed_inventory
if validate_protected_inventory_file; then
    echo 'The boot inventory validator accepted a malformed record.' >&2
    exit 1
fi
BOOT_POLICY_TEST

    unshare --mount "$initramfs_work/bin/busybox" sh -eu -s -- "$initramfs_work" <<'BOOT_MOUNT_POLICY_TEST'
root=$1
busybox="$root/bin/busybox"
probe_root="$root/mount-probe"
cleanup() {
    "$busybox" umount "$probe_root" 2>/dev/null || true
}
trap cleanup EXIT

"$busybox" mount --make-rprivate /
"$busybox" mkdir -p "$probe_root"
"$busybox" mount -t tmpfs -o rw,nodev,nosuid tmpfs "$probe_root"
definitions=$("$busybox" sed '/^\. \/angel-recovery$/d;/^mount_pseudo_filesystems$/,$d' "$root/init")
eval "$definitions"
busybox="$root/bin/busybox"

"$busybox" chmod 0777 "$probe_root"
secure_protected_mount_root "$probe_root"
"$busybox" ln -s "$probe_root" "$root/mount-probe-link"
if secure_protected_mount_root "$root/mount-probe-link"; then
    echo 'The protected mount-root validator accepted a symbolic link.' >&2
    exit 1
fi
"$busybox" rm "$root/mount-probe-link"
BOOT_MOUNT_POLICY_TEST
)
if dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | \
        cpio -itv 2>/dev/null | awk '$1 ~ /^l/ { found=1 } END { exit found ? 0 : 1 }'; then
    echo 'The hardware initramfs contains forbidden symbolic links.' >&2
    exit 1
fi
cpio -it < "$initramfs" 2>/dev/null | grep -qx 'kernel/x86/microcode/AuthenticAMD.bin'
cpio -it < "$initramfs" 2>/dev/null | grep -qx 'kernel/x86/microcode/GenuineIntel.bin'
rm -rf -- "$module_work"
mkdir -p "$module_work"
tar --zstd -xf "$modules" -C "$module_work"
if tar --zstd -tf "$modules" | grep -Eq '^\.?/?(lib|usr|sbin|bin)/'; then
    echo 'The module archive contains a forbidden Linux hierarchy.' >&2
    exit 1
fi
test -s "$module_work/the one/drivers/modules/module-manifest.sha256"
(cd "$module_work/the one/drivers/modules" && sha256sum -c --quiet module-manifest.sha256)
test -s "$module_work/the one/drivers/modules"/*/modules.dep
file "$module_loader" | grep -F 'statically linked' >/dev/null
strings "$module_loader" | grep -F '/the one/drivers/modules' >/dev/null
strings "$module_loader" | grep -F '/the one/drivers/processes/modules' >/dev/null
strings "$module_loader" | grep -F '/the one/drivers/processes/cmdline' >/dev/null
strings "$module_loader" | grep -F '/the one/drivers/state/module/%s' >/dev/null
if strings "$module_loader" | grep -Fx '/proc/modules' >/dev/null; then exit 1; fi
if strings "$module_loader" | grep -Fx '/proc/cmdline' >/dev/null; then exit 1; fi
"$module_loader" --version | grep -F 'kmod version 34.2' >/dev/null
kernel_release=$(find "$module_work/the one/drivers/modules" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | head -n 1)
[ -n "$kernel_release" ]
"$module_loader" --dirname "$module_work" --set-version "$kernel_release" --show-depends snd_usb_audio | grep -F 'snd-usb-audio.ko' >/dev/null
nvidia_core_module=$(find "$module_work/the one/drivers/modules/$kernel_release" -type f -name 'nvidia.ko*' -print -quit)
nvidia_uvm_module=$(find "$module_work/the one/drivers/modules/$kernel_release" -type f -name 'nvidia-uvm.ko*' -print -quit)
test -n "$nvidia_core_module"
test -n "$nvidia_uvm_module"
[ "$(modinfo -F version "$nvidia_core_module")" = '610.43.03' ]
[ "$(modinfo -F version "$nvidia_uvm_module")" = '610.43.03' ]
[ "$(modinfo -F version "$nvidia_core_module")" = "$(modinfo -F version "$nvidia_uvm_module")" ]
nvidia_uvm_dependencies=$("$module_loader" --dirname "$module_work" --set-version "$kernel_release" --show-depends nvidia_uvm)
printf '%s\n' "$nvidia_uvm_dependencies" | awk '
    /^insmod .*\/nvidia\.ko(\.[^ ]+)?[[:space:]]*$/ { core = NR }
    /^insmod .*\/nvidia-uvm\.ko(\.[^ ]+)?[[:space:]]*$/ { uvm = NR }
    END { exit !(core && uvm && core < uvm) }
'
rm -rf -- "$module_work"

if tar --zstd -tvf "$firmware" | awk '$1 ~ /^l/ { found=1 } END { exit found ? 0 : 1 }'; then
    echo 'The firmware archive contains forbidden symbolic links.' >&2
    exit 1
fi

readelf -lW "$wireless_engine" | grep -F '/the one/catalogue/network/ld-linux-x86-64.so.2' >/dev/null
readelf -dW "$wireless_engine" | grep -F '/the one/catalogue/network' >/dev/null
"$network_loader" --library-path "$network_catalogue" "$wireless_engine" -v | grep -F 'wpa_supplicant v2.11' >/dev/null
readelf -h "$nvidia_path_provider" >/dev/null
readelf -dW "$nvidia_path_provider" |
    grep -F '/the one/catalogue/graphics/nvidia:/the one/catalogue/graphics:/the one/catalogue/python' \
        >/dev/null
strings "$nvidia_path_provider" | grep -F '/the one/drivers/nodes' >/dev/null
strings "$nvidia_path_provider" | grep -F '/the one/drivers/processes' >/dev/null
strings "$nvidia_path_provider" | grep -F '/the one/drivers/state' >/dev/null
strings "$nvidia_path_provider" | grep -F 't1os-cuda-thread-name' >/dev/null
if strings "$nvidia_path_provider" | grep -F '/the one/drivers/nodes/null' >/dev/null; then exit 1; fi
strings "$nvidia_path_provider" | grep -Fx 'nvidia-uvm' >/dev/null
if strings "$nvidia_path_provider" | grep -Fx 'nvidia-uvm-tools' >/dev/null; then exit 1; fi
(
    # The dynamic loader treats spaces in LD_PRELOAD as entry separators.
    # Exercise the exact provider from a private, space-free pathname.
    nvidia_path_provider_selftest="/var/tmp/t1os-nvidia-path-provider-selftest-$$.so"
    trap 'rm -f -- "$nvidia_path_provider_selftest"' EXIT
    cp -- "$nvidia_path_provider" "$nvidia_path_provider_selftest"
    LD_PRELOAD="$nvidia_path_provider_selftest" python3 - <<'PY'
import ctypes
import os

path = f'/proc/self/task/{os.getpid()}/comm'
flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC
descriptor = os.open(path, flags)
try:
    target = os.readlink(f'/dev/fd/{descriptor}')
    assert target.startswith('/memfd:t1os-cuda-thread-name'), target
    payload = b't1os-cuda-worker'
    assert os.write(descriptor, payload) == len(payload)
finally:
    os.close(descriptor)

libc = ctypes.CDLL(None, use_errno=True)
libc.fopen.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
libc.fopen.restype = ctypes.c_void_p
libc.fileno.argtypes = [ctypes.c_void_p]
libc.fileno.restype = ctypes.c_int
libc.fclose.argtypes = [ctypes.c_void_p]
libc.fclose.restype = ctypes.c_int
stream = libc.fopen(path.encode(), b'wb')
assert stream, ctypes.get_errno()
stream_descriptor = libc.fileno(stream)
target = os.readlink(f'/dev/fd/{stream_descriptor}')
assert target.startswith('/memfd:t1os-cuda-thread-name'), target
assert libc.fclose(stream) == 0
PY
)
readelf -h "$chromium_provider" >/dev/null
for media_decode_binary in "$media_decode_service" "$media_decode_worker"; do
    readelf -h "$media_decode_binary" >/dev/null
    readelf -lW "$media_decode_binary" |
        grep -F '/the one/catalogue/python/ld-linux-x86-64.so.2' >/dev/null
    readelf -dW "$media_decode_binary" |
        grep -F '/the one/catalogue/audio:/the one/catalogue/graphics:/the one/catalogue/python' \
            >/dev/null
done
readelf -dW "$nvidia_vaapi" | grep -F '(NEEDED)' | grep -F 'libgstcodecparsers-1.0.so.0' >/dev/null
readelf -Ws "$nvidia_vaapi" | grep -F 'gst_vp9_parser_new' >/dev/null
readelf -Ws "$nvidia_vaapi" | grep -F 'gst_vp9_parser_parse_frame_header' >/dev/null
strings "$chromium_provider" | grep -F '/the one/drivers/nodes' >/dev/null
strings "$chromium_provider" | grep -F '/.ephemeral/chromium' >/dev/null
strings "$chromium_provider" | grep -Fx '/.ephemeral/chromium/extensions' >/dev/null
strings "$chromium_provider" | grep -Fx '/.ephemeral/volumes' >/dev/null
strings "$chromium_provider" | grep -Fx '/the one/drivers/nodes/urandom' >/dev/null
strings "$chromium_provider" | grep -Fx '/dev/nvidiactl' >/dev/null
strings "$chromium_provider" | grep -F '/the one/drivers/nodes/nvidia' >/dev/null
readelf -Ws "$chromium_provider" | awk '$8 == "__xstat64" { found=1 } END { exit !found }'
if strings "$chromium_provider" | grep -Fx '/dev/nvidia-uvm' >/dev/null; then exit 1; fi
if strings "$chromium_provider" | grep -Fx '/the one/drivers/nodes/nvidia-uvm' >/dev/null; then exit 1; fi
if strings "$chromium_provider" | grep -F 'NVIDIA sandbox bridge' >/dev/null; then exit 1; fi
if strings "$chromium_provider" | grep -Fx 't1os-nv-broker' >/dev/null; then exit 1; fi
if strings "$chromium_provider" | grep -Fx 't1os-cuda-thread-name' >/dev/null; then exit 1; fi
if strings "$chromium_provider" | grep -Fx '/dev/nvidia-uvm-tools' >/dev/null; then exit 1; fi
if strings "$chromium_provider" | grep -Fx '/dev/nvidia-caps' >/dev/null; then exit 1; fi
strings "$chromium_provider" | grep -Fx 'SingletonLock' >/dev/null
if strings "$chromium_provider" | grep -F 'T1OS path provider trace:' >/dev/null; then exit 1; fi
if strings "$chromium_provider" | grep -Fx '/drives' >/dev/null; then exit 1; fi
readelf -lW "$chromium_engine" | grep -F '/the one/software/chromium/libraries/ld-linux-x86-64.so.2' >/dev/null
readelf -dW "$chromium_engine" | grep -F '/the one/software/chromium/libraries' >/dev/null
chromium_video_features=$(strings "$chromium_engine" | grep -E '^(AcceleratedVideoDecodeLinuxGL|VaapiOnNvidiaGPUs|FallbackAfterDecodeError|Dav1dVideoDecoder)$')
for feature in AcceleratedVideoDecodeLinuxGL VaapiOnNvidiaGPUs FallbackAfterDecodeError Dav1dVideoDecoder; do
    printf '%s\n' "$chromium_video_features" | grep -Fx "$feature" >/dev/null
done
readelf -lW "$chromium_input_bridge" | grep -F '/the one/software/chromium/libraries/ld-linux-x86-64.so.2' >/dev/null
readelf -dW "$chromium_input_bridge" | grep -F '/the one/software/chromium/libraries' >/dev/null
strings "$chromium_input_bridge" | grep -F '/the one/software/chromium/libraries/libxdo.so.3' >/dev/null
file "$chromium_subprocess" | grep -Eq '(^|, )(statically linked|static-pie linked)(,|$)'
if readelf -lW "$chromium_subprocess" | grep -Eq '[[:space:]]INTERP[[:space:]]'; then exit 1; fi
strings "$chromium_subprocess" | grep -Fx '/the one/software/chromium/program/chrome' >/dev/null
strings "$chromium_subprocess" | grep -Fx '/.ephemeral/chromium/path-provider.so' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'SANDBOX_LD_LIBRARY_PATH=/the one/software/chromium/libraries:/the one/catalogue/graphics' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'SANDBOX_GPU_LD_LIBRARY_PATH=/the one/catalogue/graphics/nvidia:/the one/catalogue/graphics:/the one/software/chromium/libraries' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'SANDBOX_GPU_EGL_VENDOR_LIBRARY_FILENAMES=/the one/catalogue/graphics/nvidia/egl_vendor.d/10_nvidia.json' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'SANDBOX_GPU_EGL_EXTERNAL_PLATFORM_CONFIG_DIRS=/the one/catalogue/graphics/nvidia/gbm' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'SANDBOX_GPU_GBM_BACKENDS_PATH=/the one/catalogue/graphics/nvidia/gbm' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'SANDBOX_GPU_GBM_BACKEND=nvidia-drm' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'SANDBOX_LD_PRELOAD' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'SANDBOX_LD_LIBRARY_PATH' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'T1OS_CHROMIUM_LAUNCH_ID' >/dev/null
strings "$chromium_subprocess" | grep -Fx '/the one/drivers/processes' >/dev/null
strings "$chromium_subprocess" | grep -Fx 't1os-chrome-subprocess: invalid child process type' >/dev/null
strings "$chromium_subprocess" | grep -Fx 't1os-chrome-subprocess: invalid child identity' >/dev/null
strings "$chromium_subprocess" | grep -Fx 't1os-chrome-subprocess: invalid Chromium parent' >/dev/null
strings "$chromium_subprocess" | grep -Fx 't1os-chrome-subprocess: unsafe loader environment' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'GLIBC_TUNABLES=' >/dev/null
readelf -h "$chromium_sandbox" >/dev/null
strings "$chromium_sandbox" | grep -Fx '/.ephemeral/chromium/sandbox-root' >/dev/null
if strings "$chromium_sandbox" | grep -F '/.t1p' >/dev/null; then exit 1; fi
if strings "$chromium_sandbox" | grep -F '/proc/self/fd' >/dev/null; then exit 1; fi
if strings "$chromium_sandbox" | grep -F '/.ephemeral/chromium/processes' >/dev/null; then exit 1; fi
strings "$chromium_engine" | grep -F '/the one/settings/network/dns.txt' >/dev/null
strings "$chromium_libc" | grep -F '/the one/settings/network/dns.txt' >/dev/null
if strings "$chromium_engine" | grep -F '/etc/resolv.conf' >/dev/null; then exit 1; fi
if strings "$chromium_libc" | grep -F '/etc/resolv.conf' >/dev/null; then exit 1; fi
if strings "$chromium_engine" | grep -F '/.t1dns/resolver' >/dev/null; then exit 1; fi
if strings "$chromium_libc" | grep -F '/.t1dns/resolver' >/dev/null; then exit 1; fi
if strings "$chromium_engine" | grep -F '/the one/dns.txt' >/dev/null; then exit 1; fi
if strings "$chromium_libc" | grep -F '/the one/dns.txt' >/dev/null; then exit 1; fi
strings "$chromium_libasound" | grep -F '/the one/drivers/nodes/null' >/dev/null
if strings "$chromium_libasound" | grep -Fx '/dev/null' >/dev/null; then exit 1; fi
'@

$normalizedLinuxCheck = $linuxCheck.Replace("`r", '') + "`n# end"
$normalizedLinuxCheck | wsl.exe -d Ubuntu -u root --exec bash -s -- $wslInit $wslInitramfs $wslModules $wslModuleLoader $wslWirelessEngine $wslNetworkLoader $wslNetworkCatalogue $wslChromiumEngine $wslChromiumProvider $wslChromiumSandbox $wslChromiumLibc $wslChromiumInputBridge $wslChromiumLibasound $wslChromiumSubprocess $wslNvidiaPathProvider $wslNvidiaVaapi $wslFirmware $wslMediaDecodeService $wslMediaDecodeWorker $pythonRelease
$linuxCheckExitCode = $LASTEXITCODE
if ($linuxCheckExitCode -ne 0) {
    throw 'Hardware Linux artifact validation failed.'
}


Write-Host 'Hardware linux artifact contracts validation passed.'
