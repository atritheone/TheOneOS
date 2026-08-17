[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$Resume
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$kernelRoot = Join-Path $projectRoot 'source\entry\kernel'
$configSource = Join-Path $kernelRoot 'T10Skernel hardware 0.19 settings.txt'
$policySource = Join-Path $kernelRoot 't1os_lsm.c'
$quotedShebangPatch = Join-Path $kernelRoot 't1os quoted shebang.patch'
$settingsTarget = Join-Path $kernelRoot 'T10Skernel virtualbox 0.19 settings.txt'
$kernelTarget = Join-Path $kernelRoot 'current build\t1osbzimage-virtualbox-0.19'
$environmentTarget = Join-Path $projectRoot 'environment\t1osbzimage-virtualbox-0.19'
$isoKernelTarget = Join-Path $projectRoot 'environment\iso\boot\vmlinuz'
$developmentRoot = Join-Path $projectRoot 'development\graphics kernel'
$stageRoot = Join-Path $developmentRoot 'stage'
$stageKernel = Join-Path $stageRoot 't1osbzimage-virtualbox-0.19'
$stageSettings = Join-Path $stageRoot 'T10Skernel virtualbox 0.19 settings.txt'
$cacheRoot = Join-Path ([System.IO.Path]::GetTempPath()) 't1os-kernel-cache'
$archive = Join-Path $cacheRoot 'linux-7.1.5.tar.xz'
$kernelVersion = '7.1.5'
$kernelSha256 = '22a0196b3cbcdf34dc27b77561f4d040585fd3447edc9ab3531a1ac79e3041e7'
$kernelUrl = 'https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.1.5.tar.xz'
$vmsvgaKernelPatch = Join-Path $projectRoot 'resource\patches\vmsvga video\kernel'

function Assert-ProjectPath {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $fullProjectRoot = [System.IO.Path]::GetFullPath($projectRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $projectPrefix = $fullProjectRoot + [System.IO.Path]::DirectorySeparatorChar

    if (-not $fullPath.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside the T1OS project: $fullPath"
    }
}

function ConvertTo-WslPath {
    param(
        [Parameter(Mandatory)]
        [string]$WindowsPath
    )

    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath

    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }

    return ([string]($output | Select-Object -First 1)).Trim()
}

foreach ($path in @($kernelRoot, $configSource, $policySource, $quotedShebangPatch, $settingsTarget, $kernelTarget, $environmentTarget, $isoKernelTarget, $developmentRoot, $stageRoot, $stageKernel, $stageSettings, $vmsvgaKernelPatch)) {
    Assert-ProjectPath -Path $path
}

foreach ($path in @($configSource, $policySource, $quotedShebangPatch)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required kernel source file not found: $path"
    }
}

foreach ($requiredPatch in @('apply_vmsvga_video.py', 'vbox_vmsvga_video.h')) {
    $requiredPatchPath = Join-Path $vmsvgaKernelPatch $requiredPatch
    if (-not (Test-Path -LiteralPath $requiredPatchPath -PathType Leaf)) {
        throw "Required VMSVGA kernel patch input not found: $requiredPatchPath"
    }
}

foreach ($command in @('wsl.exe', 'curl.exe')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $command"
    }
}

New-Item -ItemType Directory -Path $cacheRoot -Force | Out-Null

if ($Clean -and (Test-Path -LiteralPath $archive)) {
    Remove-Item -LiteralPath $archive -Force
}

if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    Write-Host "Downloading Linux $kernelVersion from kernel.org..."
    & curl.exe --fail --location --retry 5 --continue-at - --output $archive $kernelUrl

    if ($LASTEXITCODE -ne 0) {
        throw "Linux source download failed (exit code $LASTEXITCODE)."
    }
}

$archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()

if ($archiveHash -ne $kernelSha256) {
    throw "Linux source hash mismatch. Expected $kernelSha256, received $archiveHash."
}

if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null

$wslArchive = ConvertTo-WslPath -WindowsPath $archive
$wslConfig = ConvertTo-WslPath -WindowsPath $configSource
$wslPolicy = ConvertTo-WslPath -WindowsPath $policySource
$wslQuotedShebangPatch = ConvertTo-WslPath -WindowsPath $quotedShebangPatch
$wslStageKernel = ConvertTo-WslPath -WindowsPath $stageKernel
$wslStageSettings = ConvertTo-WslPath -WindowsPath $stageSettings
$wslVmsvgaKernelPatch = ConvertTo-WslPath -WindowsPath $vmsvgaKernelPatch
$resumeValue = if ($Resume) { '1' } else { '0' }

$buildCommand = @'
set -euo pipefail

archive=$1
config=$2
policy=$3
stage_kernel=$4
stage_settings=$5
kernel_version=$6
kernel_sha256=$7
vmsvga_kernel_patch=$8
resume=$9
quoted_shebang_patch=${10}
work=/var/tmp/t1os-graphics-kernel
source="$work/linux-$kernel_version"

require_command() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "Required WSL kernel build command not found: $1" >&2
        exit 127
    }
}

for command_name in make gcc bc bison flex perl openssl pahole pkg-config sha256sum tar zstd nm strings patch; do
    require_command "$command_name"
done

if [ ! -f /usr/include/openssl/ssl.h ]; then
    echo 'Required WSL OpenSSL development headers were not found.' >&2
    exit 127
fi

printf '%s  %s\n' "$kernel_sha256" "$archive" | sha256sum -c -

if [ "$resume" = 1 ]; then
    [ -s "$source/Makefile" ] || {
        echo 'The VM kernel work tree is absent; rerun without -Resume.' >&2
        exit 1
    }
    echo "Resuming the validated VM kernel build from $work."
else
    case "$work" in
        /var/tmp/t1os-graphics-kernel) rm -rf -- "$work" ;;
        *) echo "Refusing to replace unexpected work path: $work" >&2; exit 1 ;;
    esac
    mkdir -p "$work"
    tar -xf "$archive" -C "$work"
    python3 "$vmsvga_kernel_patch/apply_vmsvga_video.py" \
        "$source" "$vmsvga_kernel_patch"
fi
if ! grep -Fq 'T1OS keeps its interpreter below `/the one`.' "$source/fs/binfmt_script.c"; then
    patch --batch --forward --fuzz=0 -d "$source" -p1 < "$quoted_shebang_patch"
fi
grep -Fq 'bool quoted_name = false;' "$source/fs/binfmt_script.c"
grep -Fq "i_sep = strnchr(i_name, i_end - i_name, '\"');" "$source/fs/binfmt_script.c"
mkdir -p "$source/security/t1os"
cp -- "$policy" "$source/security/t1os/t1os_lsm.c"
drm_rule_line=$(grep -n -m1 'DRM/KMS devices are owned by the window server' "$source/security/t1os/t1os_lsm.c" | cut -d: -f1)
audio_rule_line=$(grep -n -m1 "ALSA is the audio service's entire device authority" "$source/security/t1os/t1os_lsm.c" | cut -d: -f1)

if [ -z "$drm_rule_line" ] || [ -z "$audio_rule_line" ] || [ "$drm_rule_line" -ge "$audio_rule_line" ]; then
    echo 'The DRM rule must precede the scoped ALSA device-node rule.' >&2
    exit 1
fi

printf '%s\n' \
    'config SECURITY_T1OS' \
    '    bool "T1OS security module"' \
    '    default n' \
    '    help' \
    '      Enforces T1OS master and architect path, execution, and process rules.' \
    > "$source/security/t1os/Kconfig"
printf '%s\n' 'obj-$(CONFIG_SECURITY_T1OS) += t1os_lsm.o' > "$source/security/t1os/Makefile"
sed -i '/^source "security\/t1os\/Kconfig"$/d' "$source/security/Kconfig"
sed -i '/source "security\/landlock\/Kconfig"/a source "security/t1os/Kconfig"' "$source/security/Kconfig"
sed -i '/^obj-$(CONFIG_SECURITY_T1OS) += t1os\/$/d' "$source/security/Makefile"
printf '%s\n' 'obj-$(CONFIG_SECURITY_T1OS) += t1os/' >> "$source/security/Makefile"
cp -- "$config" "$source/.config"
config_tool="$source/scripts/config"
"$config_tool" --file "$source/.config" \
    --set-str LOCALVERSION '-t1os-virtualbox' \
    --set-str MODPROBE_PATH '/the one/drivers/tools/modprobe' \
    --set-str MODULE_SIG_KEY 'certs/signing_key.pem' \
    --set-str SYSTEM_TRUSTED_KEYS '' \
    --set-str SYSTEM_REVOCATION_KEYS '' \
    --disable LOCALVERSION_AUTO \
    --enable SECURITY_T1OS \
    --enable DEVTMPFS \
    --enable DEVTMPFS_MOUNT \
    --enable SCSI \
    --enable BLK_DEV_SD \
    --enable ATA \
    --enable SATA_AHCI \
    --enable ATA_PIIX \
    --enable EXT4_FS \
    --enable VIRTIO \
    --enable VIRTIO_PCI \
    --enable VIRTIO_NET \
    --enable NF_CONNTRACK \
    --enable NFT_CT \
    --enable DRM \
    --enable DRM_VMWGFX \
    --disable DRM_VBOXVIDEO \
    --enable VBOXGUEST \
    --enable VBOXSF_FS \
    --enable SND \
    --enable SND_HDA_INTEL \
    --enable SND_INTEL8X0 \
    --enable SERIAL_8250 \
    --enable SERIAL_8250_CONSOLE \
    --enable USB_XHCI_HCD \
    --enable USB_XHCI_PCI \
    --enable HID \
    --enable HID_GENERIC \
    --enable USB_HID \
    --enable INPUT_EVDEV

export KBUILD_BUILD_USER=t1os
export KBUILD_BUILD_HOST=t1os-builder
export KBUILD_BUILD_TIMESTAMP='2026-07-31 00:00:00 +0000'

make -C "$source" olddefconfig

require_builtin() {
    grep -qx "CONFIG_$1=y" "$source/.config" || {
        echo "VirtualBox-critical CONFIG_$1 is not built in." >&2
        exit 1
    }
}

for option in SECURITY_T1OS DEVTMPFS SCSI BLK_DEV_SD ATA SATA_AHCI ATA_PIIX EXT4_FS VIRTIO VIRTIO_PCI VIRTIO_NET NF_CONNTRACK NFT_CT DRM DRM_VMWGFX VBOXGUEST VBOXSF_FS SND SND_HDA_INTEL SND_INTEL8X0 SERIAL_8250 SERIAL_8250_CONSOLE USB_XHCI_HCD USB_XHCI_PCI HID HID_GENERIC USB_HID INPUT_EVDEV; do
    require_builtin "$option"
done
grep -qx 'CONFIG_DRM_VBOXVIDEO=n' "$source/.config" || ! grep -q '^CONFIG_DRM_VBOXVIDEO=' "$source/.config"
grep -Fqx 'CONFIG_MODPROBE_PATH="/the one/drivers/tools/modprobe"' "$source/.config"

make -C "$source" -j"$(nproc)" bzImage
image="$source/arch/x86/boot/bzImage"

test -s "$image"
nm "$source/vmlinux" | grep ' t t1os_lsm_init$' >/dev/null
strings "$source/vmlinux" | grep -F '/the one/drivers/nodes/dri/card' >/dev/null
strings "$source/vmlinux" | grep -F '/the one/drivers/nodes/dri/renderD' >/dev/null
strings "$source/vmlinux" | grep -F '/the one/software/virtualbox/VBoxDRMClient' >/dev/null
strings "$source/vmlinux" | grep -F '/the one/software/virtualbox/VBoxT1Clipboard' >/dev/null
strings "$source/vmlinux" | grep -F '/the one/software/virtualbox/VBoxT1Service' >/dev/null
strings "$source/vmlinux" | grep -F '/the one/drivers/nodes/vboxguest' >/dev/null
strings "$source/vmlinux" | grep -F '/the one/drivers/nodes/vboxuser' >/dev/null
strings "$source/vmlinux" | grep -F '/the one/drivers/tools/modprobe' >/dev/null
strings "$source/vmlinux" | grep -Fx '/the one/build/windows/windowserver.py' >/dev/null
strings "$source/vmlinux" | grep -Fx '/the one/build/drivers/driverserver.py' >/dev/null
strings "$source/vmlinux" | grep -Fx '/the one/build' >/dev/null
strings "$source/vmlinux" | grep -Fx '/the one/software' >/dev/null
strings "$source/vmlinux" | grep -Fx '/the one/drivers/nodes/pts/ptmx' >/dev/null
nm "$source/vmlinux" | grep ' t vmw_vbox_video_notify' >/dev/null
cp -- "$image" "$stage_kernel"
cp -- "$source/.config" "$stage_settings"
sha256sum "$stage_kernel"
'@

Write-Host "Building the T1OS graphics kernel from Linux $kernelVersion..."
& wsl.exe -d Ubuntu --exec bash -c $buildCommand bash $wslArchive $wslConfig $wslPolicy $wslStageKernel $wslStageSettings $kernelVersion $kernelSha256 $wslVmsvgaKernelPatch $resumeValue $wslQuotedShebangPatch

if ($LASTEXITCODE -ne 0) {
    throw "The T1OS graphics kernel build failed (exit code $LASTEXITCODE)."
}

if (-not (Test-Path -LiteralPath $stageKernel -PathType Leaf) -or -not (Test-Path -LiteralPath $stageSettings -PathType Leaf)) {
    throw 'The kernel build did not produce its staged image and configuration.'
}

Copy-Item -LiteralPath $stageKernel -Destination $kernelTarget -Force
Copy-Item -LiteralPath $stageKernel -Destination $environmentTarget -Force
Copy-Item -LiteralPath $stageKernel -Destination $isoKernelTarget -Force
Copy-Item -LiteralPath $stageSettings -Destination $settingsTarget -Force

$targetHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $kernelTarget).Hash.ToLowerInvariant()
$environmentHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $environmentTarget).Hash.ToLowerInvariant()
$isoKernelHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $isoKernelTarget).Hash.ToLowerInvariant()

if ($targetHash -ne $environmentHash -or $targetHash -ne $isoKernelHash) {
    throw 'The resource, environment, and ISO-stage kernel images do not match.'
}

Write-Host "T1OS graphics kernel completed: $targetHash"
Write-Host "Kernel: $kernelTarget"
Write-Host "Configuration: $settingsTarget"
