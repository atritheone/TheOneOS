[CmdletBinding(SupportsShouldProcess)]
param()

$ErrorActionPreference = 'Stop'

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'WSL is required for the T1OS hardware build.'
}

$distribution = 'Ubuntu'
$packages = @(
    'ca-certificates',
    'curl',
    'git',
    'patch',
    'gnupg',
    'openssl',
    'perl',
    'python3',
    'coreutils',
    'gzip',
    'binutils',
    'util-linux',
    'e2fsprogs',
    'cpio',
    'file',
    'nasm',
    'build-essential',
    'autoconf',
    'automake',
    'libtool',
    'libgcrypt20-dev',
    'bc',
    'bison',
    'flex',
    'libssl-dev',
    'libelf-dev',
    'dwarves',
    'zstd',
    'libzstd-dev',
    'xz-utils',
    'kmod',
    'gdisk',
    'parted',
    'dosfstools',
    'ntfs-3g',
    'mtools',
    'rsync',
    'cryptsetup-bin',
    'grub-efi-amd64-bin',
    'grub-pc-bin',
    'qemu-system-x86',
    'ovmf',
    'shellcheck',
    'strace',
    'sbsigntool',
    'systemd-ukify',
    'systemd-boot-efi',
    'ninja-build',
    'pkg-config',
    'patchelf',
    'python3-venv',
    'python3-mako',
    'python3-yaml',
    'llvm-dev',
    'libclang-dev',
    'libpolly-18-dev',
    'libclc-18-dev',
    'libclc-18',
    'libllvmspirvlib-18-dev',
    'llvm-spirv-18',
    'libvulkan-dev',
    'glslang-tools',
    'spirv-tools',
    'libexpat1-dev',
    'libglib2.0-dev',
    'libpciaccess-dev',
    'libudev-dev',
    'libnl-3-dev',
    'libnl-genl-3-dev',
    'rustup',
    'bindgen',
    'cbindgen'
)

$description = "$distribution WSL build environment: $($packages -join ', ')"
if (-not $PSCmdlet.ShouldProcess($description, 'Install or update T1OS hardware build dependencies')) {
    return
}

$installCommand = @'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt_options=(
    -o Acquire::ForceIPv4=true
    -o Acquire::Retries=5
    -o Acquire::http::Timeout=30
    -o Acquire::https::Timeout=30
)
apt-get "${apt_options[@]}" update
for attempt in 1 2 3; do
    if apt-get "${apt_options[@]}" install -y "$@"; then
        break
    fi
    echo "apt dependency installation attempt $attempt failed; retrying..." >&2
    sleep 2
    if [ "$attempt" = 3 ]; then
        exit 1
    fi
done

required_commands=(
    aclocal autoconf automake autoreconf awk bash bc bison blkid cc cpio cryptsetup curl depmod e2fsck
    file flex fsck.vfat g++ gcc git grub-install gzip ldconfig losetup
    libtoolize make mcopy mmd mkfs.ext4 mkfs.ntfs mkfs.vfat modinfo mount mountpoint
    nasm ninja nm ntfs-3g ntfsfix openssl pahole parted patchelf perl pkg-config
    patch python3 qemu-system-x86_64 readelf rsync sbsign sbverify sgdisk
    sha256sum shellcheck stat strace strings strip tar ukify umount xz zstd
)
missing=()
for command_name in "${required_commands[@]}"; do
    command -v "$command_name" >/dev/null 2>&1 || missing+=("$command_name")
done
if [ "${#missing[@]}" -ne 0 ]; then
    printf 'Installed package set is missing required commands: %s\n' "${missing[*]}" >&2
    exit 127
fi

for module_name in glib-2.0 gobject-2.0 gmodule-2.0; do
    pkg-config --exists "$module_name" || {
        echo "Installed package set is missing pkg-config module: $module_name" >&2
        exit 127
    }
done

python3 -m venv /var/tmp/t1os-dependency-venv-check
rm -rf -- /var/tmp/t1os-dependency-venv-check
printf 'T1OS hardware build dependency postflight passed (%s commands).\n' "${#required_commands[@]}"
'@

& wsl.exe -d $distribution -u root --exec bash -c $installCommand bash @packages
if ($LASTEXITCODE -ne 0) {
    throw "Hardware build dependency installation failed (exit code $LASTEXITCODE)."
}

Write-Host 'T1OS hardware build dependencies are installed.'
