[CmdletBinding()]
param(
    [switch]$Clean,

    [switch]$Resume,

    [string]$ModuleSigningKeyPath = '',

    [string]$ModuleSigningCertificatePath = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$kernelRoot = Join-Path $projectRoot 'source\entry\kernel'
$configSource = Join-Path $kernelRoot 'T10Skernel hardware 0.19 settings.txt'
$policySource = Join-Path $kernelRoot 't1os_lsm.c'
$quotedShebangPatch = Join-Path $kernelRoot 't1os quoted shebang.patch'
$ntfsNoAccessRulesPatch = Join-Path $kernelRoot 't1os ntfs3 noacsrules.patch'
$settingsTarget = Join-Path $kernelRoot 'T10Skernel hardware 0.19 settings.txt'
$kernelTarget = Join-Path $kernelRoot 'current build\t1osbzimage-hardware-0.19'
$hardwareRoot = Join-Path $projectRoot 'environment\hardware'
$bootTarget = Join-Path $hardwareRoot 'boot\vmlinuz-hardware'
$provenanceTarget = Join-Path $hardwareRoot 'boot\kernel-build-inputs.json'
$modulesTarget = Join-Path $hardwareRoot 'modules.tar.zst'
$developmentRoot = Join-Path $projectRoot 'development\hardware kernel'
$stageRoot = Join-Path $developmentRoot 'stage'
$stageKernel = Join-Path $stageRoot 'vmlinuz-hardware'
$stageSettings = Join-Path $stageRoot 'T10Skernel hardware 0.19 settings.txt'
$stageModules = Join-Path $stageRoot 'modules.tar.zst'
$stageRelease = Join-Path $stageRoot 'kernel-release.txt'
$cacheRoot = Join-Path ([System.IO.Path]::GetTempPath()) 't1os-kernel-cache'
$kernelVersion = '7.1.5'
$kernelSha256 = '22a0196b3cbcdf34dc27b77561f4d040585fd3447edc9ab3531a1ac79e3041e7'
$archive = Join-Path $cacheRoot "linux-$kernelVersion.tar.xz"
$kernelUrl = "https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-$kernelVersion.tar.xz"
$nvidiaVersion = '610.43.03'
$nvidiaSha256 = '45e2d4c134a23c35e50f253a4aa63e7e5e8d17e3d185d4a07c8a58e9612ed392'
$nvidiaRunfile = Join-Path $cacheRoot "NVIDIA-Linux-x86_64-$nvidiaVersion.run"
$nvidiaUrl = "https://us.download.nvidia.com/XFree86/Linux-x86_64/$nvidiaVersion/NVIDIA-Linux-x86_64-$nvidiaVersion.run"
$protectedSigningRoot = '/root/.config/t1os/module-signing'
$repositorySigningKey = Join-Path $kernelRoot 'module signing key.pem'
$repositorySigningCertificate = Join-Path $kernelRoot 'module signing certificate.pem'
$moduleSigningKey = if ([string]::IsNullOrWhiteSpace($ModuleSigningKeyPath)) {
    if (Test-Path -LiteralPath $repositorySigningKey -PathType Leaf) {
        $repositorySigningKey
    }
    else {
        "$protectedSigningRoot/module-signing-key.pem"
    }
}
else {
    $ModuleSigningKeyPath.Trim()
}
$moduleSigningCertificate = if ([string]::IsNullOrWhiteSpace($ModuleSigningCertificatePath)) {
    if (Test-Path -LiteralPath $repositorySigningCertificate -PathType Leaf) {
        $repositorySigningCertificate
    }
    else {
        "$protectedSigningRoot/module-signing-certificate.pem"
    }
}
else {
    $ModuleSigningCertificatePath.Trim()
}

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

foreach ($requiredFile in @(
    $configSource,
    $policySource,
    $quotedShebangPatch,
    $ntfsNoAccessRulesPatch
)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required kernel input not found: $requiredFile"
    }
}

function Resolve-T1OSWslInputPath {
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [Parameter(Mandatory)]
        [string]$Description
    )

    if ($Path.StartsWith('/', [StringComparison]::Ordinal)) {
        & wsl.exe -d Ubuntu -u root --exec test -s $Path
        if ($LASTEXITCODE -ne 0) {
            throw "$Description was not found in the Ubuntu filesystem: $Path"
        }
        return $Path
    }

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description was not found: $Path"
    }
    return ConvertTo-WslPath -WindowsPath $Path
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

if ($Clean -and (Test-Path -LiteralPath $nvidiaRunfile)) {
    Remove-Item -LiteralPath $nvidiaRunfile -Force
}

if (-not (Test-Path -LiteralPath $nvidiaRunfile -PathType Leaf)) {
    Write-Host "Downloading NVIDIA open GPU driver $nvidiaVersion..."
    & curl.exe --fail --location --retry 5 --continue-at - --output $nvidiaRunfile $nvidiaUrl
    if ($LASTEXITCODE -ne 0) {
        throw "NVIDIA driver download failed (exit code $LASTEXITCODE)."
    }
}

$nvidiaHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $nvidiaRunfile).Hash.ToLowerInvariant()
if ($nvidiaHash -ne $nvidiaSha256) {
    throw "NVIDIA driver hash mismatch. Expected $nvidiaSha256, received $nvidiaHash."
}

if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null

$wslArchive = ConvertTo-WslPath -WindowsPath $archive
$wslConfig = ConvertTo-WslPath -WindowsPath $configSource
$wslPolicy = ConvertTo-WslPath -WindowsPath $policySource
$wslQuotedShebangPatch = ConvertTo-WslPath -WindowsPath $quotedShebangPatch
$wslNtfsNoAccessRulesPatch = ConvertTo-WslPath -WindowsPath $ntfsNoAccessRulesPatch
$wslStageKernel = ConvertTo-WslPath -WindowsPath $stageKernel
$wslStageSettings = ConvertTo-WslPath -WindowsPath $stageSettings
$wslStageModules = ConvertTo-WslPath -WindowsPath $stageModules
$wslStageRelease = ConvertTo-WslPath -WindowsPath $stageRelease
$wslNvidiaRunfile = ConvertTo-WslPath -WindowsPath $nvidiaRunfile
$wslModuleSigningKey = Resolve-T1OSWslInputPath `
    -Path $moduleSigningKey -Description 'Module signing key'
$wslModuleSigningCertificate = Resolve-T1OSWslInputPath `
    -Path $moduleSigningCertificate -Description 'Module signing certificate'
$resumeValue = if ($Resume) { '1' } else { '0' }

$buildCommand = @'
set -euo pipefail

archive=$1
config=$2
policy=$3
stage_kernel=$4
stage_settings=$5
stage_modules=$6
stage_release=$7
kernel_version=$8
kernel_sha256=$9
resume=${10}
nvidia_runfile=${11}
nvidia_version=${12}
nvidia_sha256=${13}
module_signing_key=${14}
module_signing_certificate=${15}
quoted_shebang_patch=${16}
ntfs_noacsrules_patch=${17}
work=/var/tmp/t1os-hardware-kernel
source="$work/linux-$kernel_version"
modules_work="$work/modules-stage"
archive_work="$work/t1os-driver-archive"
nvidia_source="/var/tmp/t1os-nvidia-open-$nvidia_version"
nvidia_module_set='nvidia nvidia-modeset nvidia-drm nvidia-uvm'
nvidia_module_set_stamp="$nvidia_source/.t1os-kernel-module-set"
build_signing_key="$source/certs/t1os-module-signing-key.pem"
build_signing_certificate="$source/certs/t1os-module-signing-certificate.pem"

# CONFIG_MODULE_SIG_KEY must be available throughout Kbuild, including the
# external NVIDIA module signing step, but the build-local private-key copy
# must not survive either a successful build or an error.  -Resume recreates
# the combined PEM before it is used, so removing it on every exit is safe.
cleanup_build_signing_key() {
    rm -f -- "$build_signing_key"
}
trap cleanup_build_signing_key EXIT

require_command() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "Required kernel build command not found: $1" >&2
        exit 127
    }
}

for command_name in make gcc bc bison flex perl python3 openssl pahole pkg-config sha256sum tar zstd xz depmod modinfo nm strings patch; do
    require_command "$command_name"
done
test -s "$module_signing_key" || { echo 'Required module signing key is missing.' >&2; exit 1; }
test -s "$module_signing_certificate" || { echo 'Required module signing certificate is missing.' >&2; exit 1; }
[ "$(stat -c '%u:%g:%a' "$module_signing_key")" = '0:0:600' ] || {
    echo 'The module signing key must be root:root mode 0600.' >&2
    exit 1
}
certificate_mode=$(stat -c '%u:%g:%a' "$module_signing_certificate")
case "$certificate_mode" in
    0:0:600|0:0:644) ;;
    *) echo 'The module signing certificate must be root-owned mode 0600 or 0644.' >&2; exit 1 ;;
esac
key_public_hash=$(openssl pkey -in "$module_signing_key" -pubout -outform DER | sha256sum | awk '{print $1}')
certificate_public_hash=$(openssl x509 -in "$module_signing_certificate" -pubkey -noout |
    openssl pkey -pubin -outform DER | sha256sum | awk '{print $1}')
[ "$key_public_hash" = "$certificate_public_hash" ] || {
    echo 'The module signing key does not match its certificate.' >&2
    exit 1
}

test -f /usr/include/openssl/ssl.h || {
    echo 'Required OpenSSL development headers were not found.' >&2
    exit 127
}

printf '%s  %s\n' "$kernel_sha256" "$archive" | sha256sum -c -
printf '%s  %s\n' "$nvidia_sha256" "$nvidia_runfile" | sha256sum -c -

require_builtin() {
    grep -qx "CONFIG_$1=y" "$source/.config" || {
        echo "Boot-critical CONFIG_$1 is not built in." >&2
        exit 1
    }
}

if [ "$resume" != 1 ]; then
    case "$work" in
        /var/tmp/t1os-hardware-kernel) rm -rf -- "$work" ;;
        *) echo "Refusing to replace unexpected kernel work path: $work" >&2; exit 1 ;;
    esac

    mkdir -p "$work"
    tar -xf "$archive" -C "$work"
    mkdir -p "$source/security/t1os"
    cp -- "$policy" "$source/security/t1os/t1os_lsm.c"
    # CONFIG_MODULE_SIG_KEY must name one PEM containing both the private key
    # and its matching X.509 certificate. Keep that build-local identity 0600.
    install -m 0600 -- "$module_signing_key" "$build_signing_key"
    cat -- "$module_signing_certificate" >> "$build_signing_key"
    install -m 0644 -- "$module_signing_certificate" "$build_signing_certificate"

printf '%s\n' \
    'config SECURITY_T1OS' \
    '    bool "T1OS security module"' \
    '    default n' \
    '    help' \
    '      Enforces T1OS master and architect path, execution, and process rules.' \
    > "$source/security/t1os/Kconfig"
printf '%s\n' 'obj-$(CONFIG_SECURITY_T1OS) += t1os_lsm.o' > "$source/security/t1os/Makefile"
sed -i '/source "security\/landlock\/Kconfig"/a source "security/t1os/Kconfig"' "$source/security/Kconfig"
printf '%s\n' 'obj-$(CONFIG_SECURITY_T1OS) += t1os/' >> "$source/security/Makefile"

cp -- "$config" "$source/.config"
config_tool="$source/scripts/config"

"$config_tool" --file "$source/.config" \
    --set-str LOCALVERSION '-t1os-hardware' \
    --set-str MODPROBE_PATH '/the one/drivers/tools/modprobe' \
    --disable LOCALVERSION_AUTO \
    --enable SECURITY_T1OS \
    --enable EFI \
    --enable EFI_STUB \
    --enable EFI_PARTITION \
    --enable EFIVAR_FS \
    --enable DEVTMPFS \
    --enable DEVTMPFS_MOUNT \
    --enable BLK_DEV_NVME \
    --enable SATA_AHCI \
    --enable SCSI \
    --enable BLK_DEV_SD \
    --enable USB \
    --enable USB_XHCI_HCD \
    --enable USB_XHCI_PCI \
    --enable USB_STORAGE \
    --enable USB_UAS \
    --enable HID \
    --enable HID_GENERIC \
    --enable USB_HID \
    --enable INPUT_EVDEV \
    --enable VT \
    --enable VT_CONSOLE \
    --enable UNIX98_PTYS \
    --enable EXT4_FS \
    --enable SQUASHFS \
    --enable SQUASHFS_ZSTD \
    --enable EXFAT_FS \
    --enable FAT_FS \
    --enable VFAT_FS \
    --enable NLS_CODEPAGE_437 \
    --enable NLS_ASCII \
    --enable NLS_UTF8 \
    --disable NTFS_FS \
    --enable NTFS3_FS \
    --disable NTFS3_64BIT_CLUSTER \
    --enable NTFS3_FS_POSIX_ACL \
    --enable DRM \
    --enable DRM_KMS_HELPER \
    --enable DRM_FBDEV_EMULATION \
    --enable DRM_SIMPLEDRM \
    --enable DRM_VMWGFX \
    --enable DRM_VIRTIO_GPU \
    --enable FRAMEBUFFER_CONSOLE \
    --enable R8169 \
    --enable E1000 \
    --enable E1000E \
    --enable IGB \
    --enable IGC \
    --enable USB_RTL8152 \
    --enable FW_LOADER \
    --enable MICROCODE \
    --enable SND \
    --enable SND_HDA_INTEL \
    --enable SND_HDA_CODEC_REALTEK \
    --enable SND_HDA_CODEC_HDMI \
    --enable BLK_DEV_DM \
    --enable DM_CRYPT \
    --enable CRYPTO_AES \
    --enable CRYPTO_XTS \
    --enable CRYPTO_SHA256 \
    --enable MODULES \
    --disable MODULE_UNLOAD \
    --disable MODULE_FORCE_LOAD \
    --disable MODULE_FORCE_UNLOAD \
    --enable MODVERSIONS \
    --enable MODULE_SIG \
    --enable MODULE_SIG_FORCE \
    --enable MODULE_SIG_ALL \
    --set-str MODULE_SIG_KEY 'certs/t1os-module-signing-key.pem' \
    --set-str SYSTEM_TRUSTED_KEYS 'certs/t1os-module-signing-certificate.pem' \
    --enable MODULE_COMPRESS \
    --enable MODULE_COMPRESS_ZSTD \
    --disable KEXEC \
    --disable KEXEC_FILE \
    --disable KEXEC_CORE \
    --disable CRASH_DUMP \
    --disable CRASH_HOTPLUG \
    --disable USER_NS \
    --disable PROC_KCORE \
    --disable PROC_VMCORE \
    --disable DEVMEM \
    --enable SECURITY_LOCKDOWN_LSM \
    --enable LOCK_DOWN_KERNEL_FORCE_INTEGRITY \
    --disable LOCK_DOWN_KERNEL_FORCE_NONE \
    --disable LOCK_DOWN_KERNEL_FORCE_CONFIDENTIALITY \
    --enable DEBUG_FS \
    --disable DEBUG_FS_ALLOW_ALL \
    --enable DEBUG_FS_ALLOW_NONE \
    --enable INIT_ON_ALLOC_DEFAULT_ON \
    --enable INIT_ON_FREE_DEFAULT_ON \
    --enable ZERO_CALL_USED_REGS \
    --set-str LSM 't1os,landlock,lockdown,yama,loadpin,safesetid,integrity,apparmor,selinux,smack,tomoyo,bpf,ipe' \
    --module DRM_AMDGPU \
    --module DRM_RADEON \
    --module DRM_NOUVEAU \
    --module DRM_I915 \
    --module DRM_XE \
    --module VMD \
    --module AQTION \
    --module ALX \
    --module B44 \
    --module BNX2 \
    --module BNX2X \
    --module BNXT \
    --module TIGON3 \
    --module IXGBE \
    --module IXGBEVF \
    --module I40E \
    --module IAVF \
    --module ICE \
    --module SKY2 \
    --module FORCEDETH \
    --module 8139CP \
    --module 8139TOO \
    --module VIA_RHINE \
    --module VIA_VELOCITY \
    --module PCNET32 \
    --module E100 \
    --module USB_USBNET \
    --module USB_NET_AX8817X \
    --module USB_NET_AX88179_178A \
    --module USB_NET_CDCETHER \
    --module USB_NET_CDC_NCM \
    --module USB_LAN78XX \
    --module USB_NET_SMSC95XX \
    --module CFG80211 \
    --module MAC80211 \
    --module IWLWIFI \
    --module IWLMVM \
    --module MT7921E \
    --module MT7925E \
    --module ATH10K_PCI \
    --module ATH11K_PCI \
    --module ATH12K \
    --module BRCMFMAC \
    --module BT_HCIBTUSB \
    --module SND_USB_AUDIO \
    --module SND_HDA_CODEC_ANALOG \
    --module SND_HDA_CODEC_CONEXANT \
    --module SND_HDA_CODEC_CS8409 \
    --module SND_HDA_CODEC_IDT \
    --module SND_HDA_CODEC_VIA \
    --module SND_SOC_SOF \
    --module SND_SOC_SOF_AMD_REMBRANDT \
    --module SND_SOC_SOF_INTEL_APL \
    --module SND_SOC_SOF_INTEL_CNL \
    --module SND_SOC_SOF_INTEL_ICL \
    --module SND_SOC_SOF_INTEL_TGL \
    --module SND_SOC_SOF_INTEL_MTL \
    --module SND_SOC_SOF_INTEL_LNL \
    --module SND_SOC_SOF_INTEL_PTL \
    --module HID_APPLE \
    --module HID_ASUS \
    --module HID_CORSAIR \
    --module HID_LENOVO \
    --module HID_LOGITECH \
    --module HID_MICROSOFT \
    --module HID_MULTITOUCH \
    --module HID_PLAYSTATION \
    --module HID_STEAM \
    --module HID_STEELSERIES \
    --module HID_WACOM \
    --module I2C_HID_ACPI \
    --module JOYSTICK_XPAD

export KBUILD_BUILD_USER=t1os
export KBUILD_BUILD_HOST=t1os-hardware-builder
export KBUILD_BUILD_TIMESTAMP='2026-07-31 00:00:00 +0000'

    make -C "$source" olddefconfig

else
    echo 'Resuming the validated kernel build from /var/tmp/t1os-hardware-kernel.'
    test -s "$source/.config"
    test -s "$source/vmlinux"
    test -s "$source/arch/x86/boot/bzImage"
    cp -- "$policy" "$source/security/t1os/t1os_lsm.c"
    # Recreate the combined identity on resume so it cannot accumulate copies.
    install -m 0600 -- "$module_signing_key" "$build_signing_key"
    cat -- "$module_signing_certificate" >> "$build_signing_key"
    install -m 0644 -- "$module_signing_certificate" "$build_signing_certificate"
fi

if ! grep -Fq 'T1OS keeps its interpreter below `/the one`.' "$source/fs/binfmt_script.c"; then
    patch --batch --forward --fuzz=0 -d "$source" -p1 < "$quoted_shebang_patch"
fi
grep -Fq 'bool quoted_name = false;' "$source/fs/binfmt_script.c"
grep -Fq "i_sep = strnchr(i_name, i_end - i_name, '\"');" "$source/fs/binfmt_script.c"

if ! grep -Fq 'unsigned noacsrules : 1;' "$source/fs/ntfs3/ntfs_fs.h"; then
    patch --batch --forward --fuzz=0 -d "$source" -p1 < "$ntfs_noacsrules_patch"
fi
if ! grep -Fq '(!S_ISDIR(mode) || !sbi->options->noacsrules)' "$source/fs/ntfs3/inode.c"; then
    python3 - "$source/fs/ntfs3/inode.c" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = "\tif (std5->fa & FILE_ATTRIBUTE_READONLY)\n\t\tmode &= ~0222;"
new = """\t/*
\t * Windows uses READONLY on directories for folder customisation; it is
\t * not a directory write-access rule.  A synthetic noacsrules mount must
\t * therefore not turn such a directory (including a volume root) into
\t * 0555 and strand an otherwise writable removable volume.
\t */
\tif ((std5->fa & FILE_ATTRIBUTE_READONLY) &&
\t    (!S_ISDIR(mode) || !sbi->options->noacsrules))
\t\tmode &= ~0222;"""
if text.count(old) != 1:
    raise SystemExit('NTFS3 read-only mode rule did not match the pinned source exactly')
path.write_text(text.replace(old, new))
PY
fi
grep -Fq 'fsparam_flag("noacsrules",' "$source/fs/ntfs3/super.c"
grep -Fq 'if (!sbi->options->noacsrules)' "$source/fs/ntfs3/inode.c"
grep -Fq '(!S_ISDIR(mode) || !sbi->options->noacsrules)' "$source/fs/ntfs3/inode.c"

for required in \
    SECURITY_T1OS MODULE_SIG MODULE_SIG_FORCE MODULE_SIG_ALL \
    SECURITY_LOCKDOWN_LSM LOCK_DOWN_KERNEL_FORCE_INTEGRITY \
    DEBUG_FS_ALLOW_NONE INIT_ON_ALLOC_DEFAULT_ON INIT_ON_FREE_DEFAULT_ON \
    ZERO_CALL_USED_REGS; do
    grep -qx "CONFIG_$required=y" "$source/.config" || {
        echo "Required production hardening CONFIG_$required is not enabled." >&2
        exit 1
    }
done
for forbidden in \
    MODULE_UNLOAD MODULE_FORCE_LOAD MODULE_FORCE_UNLOAD KEXEC KEXEC_FILE \
    KEXEC_CORE CRASH_DUMP CRASH_HOTPLUG \
    USER_NS PROC_KCORE PROC_VMCORE DEVMEM DEBUG_FS_ALLOW_ALL \
    LOCK_DOWN_KERNEL_FORCE_NONE; do
    if grep -Eq "^CONFIG_$forbidden=(y|m|1|\")" "$source/.config"; then
        echo "Forbidden production CONFIG_$forbidden is enabled." >&2
        exit 1
    fi
done
grep -qx 'CONFIG_LSM="t1os,landlock,lockdown,yama,loadpin,safesetid,integrity,apparmor,selinux,smack,tomoyo,bpf,ipe"' "$source/.config"
grep -qx 'CONFIG_MODULE_SIG_KEY="certs/t1os-module-signing-key.pem"' "$source/.config"
grep -qx 'CONFIG_SYSTEM_TRUSTED_KEYS="certs/t1os-module-signing-certificate.pem"' "$source/.config"

# Linux 7.1.5 does not contain Lyude Paul's stable-targeted r535 display-head fix
# (20260429030348.3930866-1-lyude@redhat.com).  Without it, the GSP display
# path has an empty .state callback and no .rgpos callback.  On Ada this leaves
# DRM unable to read the active head or scanout position during firmware-fb
# takeover, producing the exact "scanoutpos query failed" / "wndw-0: timeout"
# sequence captured on physical hardware.  Apply the upstream three-file
# change with exact old/new guards so a changed kernel cannot accept a fuzzy
# or partial backport.
python3 - "$source" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])

def replace_exact(relative, old, new):
    path = source / relative
    text = path.read_text(encoding="utf-8")
    if old in text:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        return
    if new in text:
        return
    raise SystemExit(f"r535 display-head backport context missing: {relative}")

replace_exact(
    "drivers/gpu/drm/nouveau/nvkm/engine/disp/gv100.c",
    """static void
gv100_head_rgpos(struct nvkm_head *head, u16 *hline, u16 *vline)
""",
    """void
gv100_head_rgpos(struct nvkm_head *head, u16 *hline, u16 *vline)
""",
)
replace_exact(
    "drivers/gpu/drm/nouveau/nvkm/engine/disp/gv100.c",
    """static void
gv100_head_state(struct nvkm_head *head, struct nvkm_head_state *state)
""",
    """void
gv100_head_state(struct nvkm_head *head, struct nvkm_head_state *state)
""",
)
replace_exact(
    "drivers/gpu/drm/nouveau/nvkm/engine/disp/head.h",
    """int gv100_head_cnt(struct nvkm_disp *, unsigned long *);
int gv100_head_new(struct nvkm_disp *, int id);
""",
    """int gv100_head_cnt(struct nvkm_disp *, unsigned long *);
int gv100_head_new(struct nvkm_disp *, int id);
void gv100_head_state(struct nvkm_head *head, struct nvkm_head_state *state);
void gv100_head_rgpos(struct nvkm_head *head, u16 *hline, u16 *vline);
""",
)
replace_exact(
    "drivers/gpu/drm/nouveau/nvkm/subdev/gsp/rm/r535/disp.c",
    """static void
r535_head_state(struct nvkm_head *head, struct nvkm_head_state *state)
{
}

static const struct nvkm_head_func
r535_head = {
	.state = r535_head_state,
	.vblank_get = r535_head_vblank_get,
	.vblank_put = r535_head_vblank_put,
};
""",
    """static const struct nvkm_head_func
r535_head = {
	.state = gv100_head_state,
	.rgpos = gv100_head_rgpos,
	.vblank_get = r535_head_vblank_get,
	.vblank_put = r535_head_vblank_put,
};
""",
)
PY

grep -Fq 'void gv100_head_state(struct nvkm_head *head, struct nvkm_head_state *state);' \
    "$source/drivers/gpu/drm/nouveau/nvkm/engine/disp/head.h"
grep -Fq '.state = gv100_head_state,' \
    "$source/drivers/gpu/drm/nouveau/nvkm/subdev/gsp/rm/r535/disp.c"
grep -Fq '.rgpos = gv100_head_rgpos,' \
    "$source/drivers/gpu/drm/nouveau/nvkm/subdev/gsp/rm/r535/disp.c"
! grep -Fq 'r535_head_state(' \
    "$source/drivers/gpu/drm/nouveau/nvkm/subdev/gsp/rm/r535/disp.c"

# T1OS selects Nouveau firmware-interface index 0 at boot. Keep that policy
# hardware-generic: the pinned kernel must map index 0 to the mature r535 ABI
# on Ada, while GPUs whose first supported interface is r570 (including
# Blackwell) must continue to map index 0 to r570.
grep -Fq '{ 0, tu102_gsp_load, &ad102_gsp, &r535_rm_ga102, "535.113.01" }' \
    "$source/drivers/gpu/drm/nouveau/nvkm/subdev/gsp/ad102.c"
grep -Fq '{ 0, gh100_gsp_load, &gb202_gsp, &r570_rm_gb20x, "570.144" }' \
    "$source/drivers/gpu/drm/nouveau/nvkm/subdev/gsp/gb202.c"
grep -Fq '"Nv%sFw"' \
    "$source/drivers/gpu/drm/nouveau/include/nvkm/core/firmware.h"

for option in SECURITY_T1OS EFI EFI_STUB EFI_PARTITION EFIVAR_FS DEVTMPFS BLK_DEV_NVME SATA_AHCI SCSI BLK_DEV_SD USB USB_XHCI_HCD USB_XHCI_PCI USB_STORAGE USB_UAS HID HID_GENERIC USB_HID INPUT_EVDEV VT VT_CONSOLE UNIX98_PTYS EXT4_FS SQUASHFS SQUASHFS_ZSTD EXFAT_FS FAT_FS VFAT_FS NLS_CODEPAGE_437 NLS_ASCII NLS_UTF8 NTFS3_FS DRM DRM_SIMPLEDRM DRM_VMWGFX DRM_VIRTIO_GPU FRAMEBUFFER_CONSOLE R8169 E1000 E1000E IGB IGC USB_RTL8152 FW_LOADER MICROCODE SND_HDA_INTEL SND_HDA_CODEC_REALTEK SND_HDA_CODEC_HDMI BLK_DEV_DM DM_CRYPT; do
    require_builtin "$option"
done
grep -Fqx 'CONFIG_MODPROBE_PATH="/the one/drivers/tools/modprobe"' "$source/.config"

# make is incremental during -Resume and rebuilds any refreshed T1OS policy.
make -C "$source" -j"$(nproc)" bzImage modules
kernel_release=$(make -s -C "$source" kernelrelease)
image="$source/arch/x86/boot/bzImage"
test -s "$image"
nm "$source/drivers/gpu/drm/nouveau/nouveau.ko" |
    grep -E ' [Tt] gv100_head_state$' >/dev/null
nm "$source/drivers/gpu/drm/nouveau/nouveau.ko" |
    grep -E ' [Tt] gv100_head_rgpos$' >/dev/null

# Modern NVIDIA desktop GPUs use NVIDIA's matching open kernel module as the
# primary backend. This avoids relying on Nouveau's still-incomplete GSP
# display-window implementation while retaining Nouveau as the fallback for
# hardware not supported by NVIDIA's current Turing-and-newer open module.
if [ "$resume" != 1 ] ||
   [ ! -s "$nvidia_source/kernel-open/Makefile" ] ||
   [ ! -s "$nvidia_module_set_stamp" ] ||
   [ "$(cat "$nvidia_module_set_stamp" 2>/dev/null || true)" != "$nvidia_module_set" ]; then
    case "$nvidia_source" in
        /var/tmp/t1os-nvidia-open-*) rm -rf -- "$nvidia_source" ;;
        *) echo "Refusing to replace unexpected NVIDIA source path: $nvidia_source" >&2; exit 1 ;;
    esac
    sh "$nvidia_runfile" --extract-only --target "$nvidia_source"
    printf '%s\n' "$nvidia_module_set" > "$nvidia_module_set_stamp"
fi
test -s "$nvidia_source/LICENSE"
test -s "$nvidia_source/kernel-open/Makefile"
grep -Fq "NV_VERSION_STRING=\\\"$nvidia_version\\\"" \
    "$nvidia_source/kernel-open/Kbuild"
nvidia_jobs=$(nproc)
if [ "$nvidia_jobs" -gt 4 ]; then
    nvidia_jobs=4
fi
make -C "$nvidia_source/kernel-open" -j"$nvidia_jobs" \
    SYSSRC="$source" \
    NV_KERNEL_MODULES='nvidia nvidia-modeset nvidia-drm nvidia-uvm' \
    modules
for nvidia_module in nvidia nvidia-modeset nvidia-drm nvidia-uvm; do
    test -s "$nvidia_source/kernel-open/$nvidia_module.ko"
    modinfo -F vermagic "$nvidia_source/kernel-open/$nvidia_module.ko" |
        grep -Fq "$kernel_release"
    [ "$(modinfo -F version "$nvidia_source/kernel-open/$nvidia_module.ko")" = "$nvidia_version" ]
    "$source/scripts/sign-file" sha256 "$build_signing_key" \
        "$build_signing_certificate" \
        "$nvidia_source/kernel-open/$nvidia_module.ko"
    test -n "$(modinfo -F signer "$nvidia_source/kernel-open/$nvidia_module.ko")"
done

rm -f -- "$stage_modules"
# Always reinstall the kernel modules after the incremental build.  A resumed
# build may have rebuilt Nouveau or another module even when a previous
# modules.dep exists; reusing that tree would put stale .ko files in the image.
rm -rf -- "$modules_work"
mkdir -p "$modules_work"
make -C "$source" modules_install INSTALL_MOD_PATH="$modules_work" INSTALL_MOD_STRIP=1
make -C "$nvidia_source/kernel-open" \
    SYSSRC="$source" \
    NV_KERNEL_MODULES='nvidia nvidia-modeset nvidia-drm nvidia-uvm' \
    INSTALL_MOD_PATH="$modules_work" \
    INSTALL_MOD_STRIP=1 \
    modules_install
while IFS= read -r -d '' installed_module; do
    test -n "$(modinfo -F signer "$installed_module")" || {
        echo "Unsigned installed module: $installed_module" >&2
        exit 1
    }
done < <(find "$modules_work/lib/modules" -type f -name '*.ko*' -print0)
rm -f -- "$modules_work/lib/modules/$kernel_release/build" "$modules_work/lib/modules/$kernel_release/source"
depmod -b "$modules_work" "$kernel_release"

nm "$source/vmlinux" | grep ' t t1os_lsm_init$' >/dev/null
nm "$source/vmlinux" | grep ' t t1os_kernel_read_file$' >/dev/null
strings "$source/vmlinux" | grep -F '/the one/drivers/nodes/dri/card' >/dev/null
strings "$source/vmlinux" | grep -Fx '/the one/drivers/nodes/nvidia-modeset' >/dev/null
strings "$source/vmlinux" | grep -Fx '/the one/drivers/nodes/dri/renderD' >/dev/null
strings "$source/vmlinux" | grep -Fx '/the one/drivers/processes/driver/nvidia' >/dev/null
strings "$source/vmlinux" | grep -F '/the one/drivers/tools/modprobe' >/dev/null
strings "$source/vmlinux" | grep -Fx '/the one/build/windows/windowserver.py' >/dev/null
strings "$source/vmlinux" | grep -Fx '/the one/build/drivers/driverserver.py' >/dev/null
strings "$source/vmlinux" | grep -Fx '/the one/build' >/dev/null
strings "$source/vmlinux" | grep -Fx '/the one/software' >/dev/null
strings "$source/vmlinux" | grep -Fx '/the one/drivers/nodes/pts/ptmx' >/dev/null
test -f "$modules_work/lib/modules/$kernel_release/modules.dep"
test -n "$(find "$modules_work/lib/modules/$kernel_release" -type f -name 'nvidia.ko*' -print -quit)"
test -n "$(find "$modules_work/lib/modules/$kernel_release" -type f -name 'nvidia-modeset.ko*' -print -quit)"
test -n "$(find "$modules_work/lib/modules/$kernel_release" -type f -name 'nvidia-drm.ko*' -print -quit)"
test -n "$(find "$modules_work/lib/modules/$kernel_release" -type f -name 'nvidia-uvm.ko*' -print -quit)"
grep -Fq 'nvidia-drm' "$modules_work/lib/modules/$kernel_release/modules.dep"
grep -Eq '/nvidia-uvm\.ko[^:]*: .*\/nvidia\.ko' \
    "$modules_work/lib/modules/$kernel_release/modules.dep"

cp -- "$image" "$stage_kernel"
cp -- "$source/.config" "$stage_settings"
printf '%s\n' "$kernel_release" > "$stage_release"
rm -rf -- "$archive_work"
mkdir -p "$archive_work/the one/drivers/modules"
cp -a -- "$modules_work/lib/modules/$kernel_release" "$archive_work/the one/drivers/modules/"
(cd "$archive_work/the one/drivers/modules" && find "$kernel_release" -type f -print0 | sort -z | xargs -0 sha256sum > module-manifest.sha256)
test -s "$archive_work/the one/drivers/modules/module-manifest.sha256"
(cd "$archive_work" && tar --sort=name --mtime='UTC 2026-07-31' --owner=0 --group=0 --numeric-owner -cf - . | zstd -19 -T0 -o "$stage_modules")
sha256sum "$stage_kernel" "$stage_settings" "$stage_release"
'@

Write-Host "Building the T1OS hardware kernel from Linux $kernelVersion..."
$buildScriptPath = Join-Path $stageRoot 'build-hardware-kernel.sh'
[System.IO.File]::WriteAllText(
    $buildScriptPath,
    $buildCommand,
    [System.Text.UTF8Encoding]::new($false)
)
$wslBuildScript = ConvertTo-WslPath -WindowsPath $buildScriptPath
$buildExitCode = 1
try {
    & wsl.exe -d Ubuntu -u root --exec bash $wslBuildScript $wslArchive $wslConfig $wslPolicy $wslStageKernel $wslStageSettings $wslStageModules $wslStageRelease $kernelVersion $kernelSha256 $resumeValue $wslNvidiaRunfile $nvidiaVersion $nvidiaSha256 $wslModuleSigningKey $wslModuleSigningCertificate $wslQuotedShebangPatch $wslNtfsNoAccessRulesPatch
    $buildExitCode = $LASTEXITCODE
}
finally {
    if (Test-Path -LiteralPath $buildScriptPath) {
        Remove-Item -LiteralPath $buildScriptPath -Force
    }
}
if ($buildExitCode -ne 0) {
    throw "The T1OS hardware kernel build failed (exit code $buildExitCode)."
}

foreach ($artifact in @($stageKernel, $stageSettings, $stageRelease, $stageModules)) {
    if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) {
        throw "The hardware kernel build did not produce: $artifact"
    }
}

New-Item -ItemType Directory -Path (Split-Path -Path $kernelTarget -Parent) -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Path $bootTarget -Parent) -Force | Out-Null
Copy-Item -LiteralPath $stageKernel -Destination $kernelTarget -Force
Copy-Item -LiteralPath $stageKernel -Destination $bootTarget -Force
Copy-Item -LiteralPath $stageSettings -Destination $settingsTarget -Force

if (Test-Path -LiteralPath $modulesTarget) {
    Remove-Item -LiteralPath $modulesTarget -Force
}
Copy-Item -LiteralPath $stageModules -Destination $modulesTarget
Copy-Item -LiteralPath $stageRelease -Destination (Join-Path $hardwareRoot 'kernel-release.txt') -Force

$resourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $kernelTarget).Hash.ToLowerInvariant()
$bootHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $bootTarget).Hash.ToLowerInvariant()
if ($resourceHash -ne $bootHash) {
    throw 'The resource and hardware-stage kernel images do not match.'
}

function Get-T1OSArtifactRecord {
    param([Parameter(Mandatory)][string]$Path)

    $fullPath = [IO.Path]::GetFullPath($Path)
    $relativePath = [IO.Path]::GetRelativePath($projectRoot, $fullPath).Replace('\', '/')
    return [ordered]@{
        path = $relativePath
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $fullPath).Hash.ToLowerInvariant()
    }
}

$kernelProvenance = [ordered]@{
    format = 1
    component = 't1os-hardware-kernel'
    kernel_version = $kernelVersion
    nvidia_version = $nvidiaVersion
    inputs = @(
        Get-T1OSArtifactRecord -Path $PSCommandPath
        Get-T1OSArtifactRecord -Path $configSource
        Get-T1OSArtifactRecord -Path $policySource
        Get-T1OSArtifactRecord -Path $quotedShebangPatch
        Get-T1OSArtifactRecord -Path $ntfsNoAccessRulesPatch
    )
    outputs = @(
        Get-T1OSArtifactRecord -Path $bootTarget
        Get-T1OSArtifactRecord -Path $modulesTarget
        Get-T1OSArtifactRecord -Path (Join-Path $hardwareRoot 'kernel-release.txt')
    )
}
[IO.File]::WriteAllText(
    $provenanceTarget,
    (($kernelProvenance | ConvertTo-Json -Depth 6) + "`n"),
    [Text.UTF8Encoding]::new($false)
)

$release = (Get-Content -LiteralPath $stageRelease -Raw).Trim()
Write-Host "T1OS hardware kernel completed: $resourceHash"
Write-Host "Kernel release: $release"
Write-Host "Kernel: $bootTarget"
Write-Host "Modules: $modulesTarget"
Write-Host "Provenance: $provenanceTarget"
