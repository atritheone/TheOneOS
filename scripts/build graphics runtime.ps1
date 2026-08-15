[CmdletBinding()]
param(
    [switch]$Clean,

    [ValidateSet('vm', 'hardware')]
    [string]$Profile = 'vm',

    [switch]$EnableNvidia
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$catalogueTarget = Join-Path $projectRoot 'source\catalogue\graphics'
$softwareTarget = Join-Path $projectRoot 'source\software\graphics'
$developmentRoot = Join-Path $projectRoot 'development\graphics runtime'
$stageRoot = Join-Path $developmentRoot 'stage'
$catalogueStage = Join-Path $stageRoot 'catalogue'
$softwareStage = Join-Path $stageRoot 'software'
$mesaVersion = '26.1.5'
$mesaSha256 = '79e421c7ce18cd9e790b8375920325779f10798630bf30e0b22f1a21c8617122'
$libdrmVersion = '2.4.134'
$libdrmCommit = 'e984d448b8b17aab853369e6c203e53719f46de1'
$mesonVersion = '1.7.2'
$cmakeVersion = '3.31.6'
$libvaVersion = '2.24.1'
$libvaSha256 = 'eec6050b52876f229bd35e9df17cd31a06785e18e6f7990c445b584628483d67'
$gmmlibVersion = '22.10.0'
$gmmlibCommit = '0246660b2ade17afc1c9c4c510368fa649ca809f'
$intelMediaVersion = '26.1.5'
$intelMediaCommit = '1d2d8e96aeaba0471dc7fd0a7e85190519758fc5'
$rustVersion = '1.88.0'
$bindgenVersion = '0.71.1'
$vmsvgaMesaPatch = Join-Path $projectRoot 'resource\patches\vmsvga video\mesa'
$nvidiaVaapiPlanarPatch = Join-Path $projectRoot 'resource\patches\nvidia vaapi planar export\apply_t1os_planar_export.py'
$nvidiaPathProviderSource = Join-Path $projectRoot 'resource\entry\graphics\t1os_nvidia_path_provider.c'
$nvidiaVersion = '610.43.03'
$nvidiaSha256 = '45e2d4c134a23c35e50f253a4aa63e7e5e8d17e3d185d4a07c8a58e9612ed392'
$nvidiaVaapiCommit = '03bb5a0c082493f95f2cd54ffd31dbfa8c7cbe7d'
$nvidiaVaapiSha256 = '88c2a48f2999c0800f24dda7976393d877536e24d5ee7cbc6fd4947453946938'
$nvCodecHeadersVersion = 'n13.1.15.0'
$nvCodecHeadersCommit = '0a6fba9a2820628b8103464f4c8753ee05838baa'
$nvCodecHeadersSha256 = '1d2070546de622fd6074a99d4b283e727988b7c3624ef85f97b88962264314d2'
$gstreamerVersion = '1.26.11'
$gstreamerSha256 = '2e0bd192d0438ea606a6f76a95c8e16542167656ffec2c2bc3aaf6ee0837fbf6'
$gstreamerBaseSha256 = 'fc50f885d41f5d0407ce0876ec7235d9e7b82d48db2f4bc72c5f244a4ac79263'
$gstreamerBadSha256 = '110fb82795f0e569b1e27b12ab9699d35c7762e1ff4db95335d6ac8d1442af3d'
$nvidiaCacheRoot = Join-Path ([System.IO.Path]::GetTempPath()) 't1os-kernel-cache'
$nvidiaRunfile = Join-Path $nvidiaCacheRoot "NVIDIA-Linux-x86_64-$nvidiaVersion.run"
$nvidiaUrl = "https://us.download.nvidia.com/XFree86/Linux-x86_64/$nvidiaVersion/NVIDIA-Linux-x86_64-$nvidiaVersion.run"

if ($EnableNvidia -and $Profile -ne 'hardware') {
    throw '-EnableNvidia is only valid with -Profile hardware.'
}

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

    $output = & wsl.exe --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }

    $translatedPath = ([string]($output | Select-Object -First 1)).Trim()
    if ([string]::IsNullOrWhiteSpace($translatedPath)) {
        throw "WSL returned an empty path for: $WindowsPath"
    }

    return $translatedPath
}

foreach ($path in @($developmentRoot, $stageRoot, $catalogueStage, $softwareStage, $catalogueTarget, $softwareTarget, $vmsvgaMesaPatch, $nvidiaVaapiPlanarPatch, $nvidiaPathProviderSource)) {
    Assert-ProjectPath -Path $path
}

foreach ($requiredPatch in @('apply_svga_video.py', 'svga_video.cpp', 'svga_video_bridge.c', 'svga_video.h', 'svga_vbox_video.h')) {
    $requiredPatchPath = Join-Path $vmsvgaMesaPatch $requiredPatch
    if (-not (Test-Path -LiteralPath $requiredPatchPath -PathType Leaf)) {
        throw "Required VMSVGA Mesa patch input not found: $requiredPatchPath"
    }
}

if (-not (Test-Path -LiteralPath $nvidiaPathProviderSource -PathType Leaf)) {
    throw "Required NVIDIA path provider source not found: $nvidiaPathProviderSource"
}

if (-not (Test-Path -LiteralPath $nvidiaVaapiPlanarPatch -PathType Leaf)) {
    throw "Required NVIDIA VA-API planar export patch not found: $nvidiaVaapiPlanarPatch"
}

foreach ($command in @('wsl.exe', 'pwsh', 'curl.exe')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $command"
    }
}

if ($EnableNvidia) {
    New-Item -ItemType Directory -Path $nvidiaCacheRoot -Force | Out-Null

    if ($Clean -and (Test-Path -LiteralPath $nvidiaRunfile)) {
        Remove-Item -LiteralPath $nvidiaRunfile -Force
    }

    if (-not (Test-Path -LiteralPath $nvidiaRunfile -PathType Leaf)) {
        Write-Host "Downloading NVIDIA open GPU userspace $nvidiaVersion..."
        & curl.exe --fail --location --retry 5 --continue-at - --output $nvidiaRunfile $nvidiaUrl
        if ($LASTEXITCODE -ne 0) {
            throw "NVIDIA driver download failed (exit code $LASTEXITCODE)."
        }
    }

    $actualNvidiaHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $nvidiaRunfile).Hash.ToLowerInvariant()
    if ($actualNvidiaHash -ne $nvidiaSha256) {
        throw "NVIDIA driver hash mismatch. Expected $nvidiaSha256, received $actualNvidiaHash."
    }
}

if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $catalogueStage -Force | Out-Null
New-Item -ItemType Directory -Path $softwareStage -Force | Out-Null

$wslCatalogueStage = ConvertTo-WslPath -WindowsPath $catalogueStage
$wslSoftwareStage = ConvertTo-WslPath -WindowsPath $softwareStage
$wslVmsvgaMesaPatch = ConvertTo-WslPath -WindowsPath $vmsvgaMesaPatch
$wslNvidiaVaapiPlanarPatch = ConvertTo-WslPath -WindowsPath $nvidiaVaapiPlanarPatch
$wslNvidiaPathProviderSource = ConvertTo-WslPath -WindowsPath $nvidiaPathProviderSource
$wslNvidiaRunfile = if ($EnableNvidia) {
    ConvertTo-WslPath -WindowsPath $nvidiaRunfile
}
else {
    '-'
}
$cleanValue = if ($Clean) { '1' } else { '0' }
$nvidiaValue = if ($EnableNvidia) { '1' } else { '0' }

$buildCommand = @'
set -euo pipefail

catalogue_stage=$1
software_stage=$2
mesa_version=$3
mesa_sha256=$4
libdrm_version=$5
libdrm_commit=$6
meson_version=$7
clean=$8
profile=$9
enable_nvidia=${10}
rust_version=${11}
bindgen_version=${12}
libva_version=${13}
libva_sha256=${14}
vmsvga_mesa_patch=${15}
gmmlib_version=${16}
gmmlib_commit=${17}
intel_media_version=${18}
intel_media_commit=${19}
cmake_version=${20}
nvidia_runfile=${21}
nvidia_version=${22}
nvidia_sha256=${23}
nvidia_path_provider=${24}
nvidia_vaapi_commit=${25}
nvidia_vaapi_sha256=${26}
nv_codec_headers_version=${27}
nv_codec_headers_commit=${28}
nv_codec_headers_sha256=${29}
gstreamer_version=${30}
gstreamer_sha256=${31}
gstreamer_base_sha256=${32}
gstreamer_bad_sha256=${33}
nvidia_vaapi_planar_patch=${34}
cache=/var/tmp/t1os-graphics-cache
work=/var/tmp/t1os-graphics-work
tools=/var/tmp/t1os-graphics-tools
prefix='/the one/catalogue/graphics'
runtime_runpath='/the one/catalogue/graphics:/the one/catalogue/python'
nvidia_runtime_runpath='/the one/catalogue/graphics/nvidia:/the one/catalogue/graphics:/the one/catalogue/python'

require_command() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "Required WSL build command not found: $1" >&2
        exit 127
    }
}

for command_name in curl git gcc g++ ninja pkg-config patchelf readelf sha256sum strings tar python3; do
    require_command "$command_name"
done

# Apply one native baseline to every component built in this runtime.  Meson,
# CMake, and Cargo inherit these values; copied vendor binaries remain subject
# to the manifest inspection below but are not rewritten by the build.
hardening_cflags=(
    -O2
    -fstack-protector-strong
    -fstack-clash-protection
    -fcf-protection=full
    -fno-plt
    -fno-common
    -D_FORTIFY_SOURCE=3
    -Wformat
    -Wformat-security
    -Werror=format-security
)
hardening_ldflags=(-Wl,-z,relro,-z,now,-z,noexecstack,--as-needed)
export CFLAGS="${hardening_cflags[*]}"
export CXXFLAGS="${hardening_cflags[*]}"
export LDFLAGS="${hardening_ldflags[*]}"
export RUSTFLAGS='-C relocation-model=pic -C link-arg=-Wl,-z,relro -C link-arg=-Wl,-z,now -C link-arg=-Wl,-z,noexecstack'

libdrm_amdgpu=disabled
libdrm_nouveau=disabled
libdrm_intel=disabled
libdrm_radeon=disabled
gallium_drivers=virgl,svga,softpipe
vulkan_drivers=
llvm_option=disabled
shared_llvm=disabled
spirv_tools=disabled
gallium_va=disabled
video_codecs=

if [ "$profile" = vm ]; then
    gallium_va=enabled
    video_codecs=all
fi

if [ "$profile" = hardware ]; then
    libdrm_amdgpu=enabled
    libdrm_intel=enabled
    libdrm_radeon=enabled
    gallium_drivers=iris,crocus,r600,radeonsi,virgl,svga,softpipe
    vulkan_drivers=intel,amd
    llvm_option=enabled
    shared_llvm=enabled
    spirv_tools=enabled
    gallium_va=enabled
    video_codecs=all
    require_command llvm-config
    llvm_libdir=$(llvm-config --libdir)
    [ -f "$llvm_libdir/libPolly.a" ] && [ -f "$llvm_libdir/libPollyISL.a" ] || {
        echo 'LLVM Polly development libraries are required for RadeonSI.' >&2
        exit 127
    }

    if [ "$enable_nvidia" = 1 ]; then
        libdrm_nouveau=enabled
        gallium_drivers=iris,crocus,r600,radeonsi,nouveau,zink,virgl,svga,softpipe
        vulkan_drivers=intel,amd,nouveau
        require_command bison
        require_command flex
        require_command make
        for glib_module in glib-2.0 gobject-2.0 gmodule-2.0; do
            pkg-config --exists "$glib_module" || {
                echo "NVIDIA VP9 build requires pkg-config module $glib_module (install libglib2.0-dev)." >&2
                exit 127
            }
        done
        require_command rustup
        if ! rustup toolchain list | grep -Eq "^${rust_version}(-x86_64-unknown-linux-gnu)?( |$)"; then
            rustup toolchain install "$rust_version" --profile minimal
        fi
        export RUSTUP_TOOLCHAIN="$rust_version"
        require_command rustc
        require_command cargo
        [ "$(rustc --version | awk '{print $2}')" = "$rust_version" ] || {
            echo "Pinned Rust toolchain $rust_version is not active." >&2
            exit 1
        }
        rust_tools=/var/tmp/t1os-graphics-rust-tools
        if [ ! -x "$rust_tools/bin/bindgen" ] || [ "$("$rust_tools/bin/bindgen" --version | awk '{print $2}')" != "$bindgen_version" ]; then
            rm -rf -- "$rust_tools"
            cargo install --locked --version "$bindgen_version" --root "$rust_tools" bindgen-cli
        fi
        export PATH="$rust_tools/bin:$PATH"
        [ "$(bindgen --version | awk '{print $2}')" = "$bindgen_version" ] || {
            echo "Pinned bindgen $bindgen_version is not active." >&2
            exit 1
        }
    fi
fi

if [ "$clean" = 1 ]; then
    case "$work" in
        /var/tmp/t1os-graphics-work) rm -rf -- "$work" ;;
        *) echo "Refusing to clean unexpected work path: $work" >&2; exit 1 ;;
    esac
fi

mkdir -p "$cache" "$work"

if \
    [ ! -x "$tools/bin/meson" ] \
    || [ "$("$tools/bin/meson" --version)" != "$meson_version" ] \
    || [ ! -x "$tools/bin/cmake" ] \
    || [ "$("$tools/bin/cmake" --version | awk 'NR == 1 { print $3 }')" != "$cmake_version" ]
then
    case "$tools" in
        /var/tmp/t1os-graphics-tools) rm -rf -- "$tools" ;;
        *) echo "Refusing to replace unexpected tools path: $tools" >&2; exit 1 ;;
    esac

    python3 -m venv "$tools"
    "$tools/bin/python" -m pip install --disable-pip-version-check \
        "meson==$meson_version" \
        "cmake==$cmake_version"
fi

meson="$tools/bin/meson"
cmake="$tools/bin/cmake"
mesa_archive="$cache/mesa-$mesa_version.tar.xz"
mesa_url="https://archive.mesa3d.org/mesa-$mesa_version.tar.xz"
libva_archive="$cache/libva-$libva_version.tar.bz2"
libva_url="https://github.com/intel/libva/releases/download/$libva_version/libva-$libva_version.tar.bz2"
nvidia_vaapi_archive="$cache/nvidia-vaapi-driver-$nvidia_vaapi_commit.tar.gz"
nvidia_vaapi_url="https://github.com/elFarto/nvidia-vaapi-driver/archive/$nvidia_vaapi_commit.tar.gz"
nv_codec_headers_archive="$cache/nv-codec-headers-$nv_codec_headers_commit.tar.gz"
nv_codec_headers_url="https://github.com/FFmpeg/nv-codec-headers/archive/$nv_codec_headers_commit.tar.gz"
gstreamer_archive="$cache/gstreamer-$gstreamer_version.tar.xz"
gstreamer_url="https://gstreamer.freedesktop.org/src/gstreamer/gstreamer-$gstreamer_version.tar.xz"
gstreamer_base_archive="$cache/gst-plugins-base-$gstreamer_version.tar.xz"
gstreamer_base_url="https://gstreamer.freedesktop.org/src/gst-plugins-base/gst-plugins-base-$gstreamer_version.tar.xz"
gstreamer_bad_archive="$cache/gst-plugins-bad-$gstreamer_version.tar.xz"
gstreamer_bad_url="https://gstreamer.freedesktop.org/src/gst-plugins-bad/gst-plugins-bad-$gstreamer_version.tar.xz"

if [ ! -f "$mesa_archive" ]; then
    curl -fL --retry 5 --retry-delay 2 -o "$mesa_archive" "$mesa_url"
fi

printf '%s  %s\n' "$mesa_sha256" "$mesa_archive" | sha256sum -c -

if [ ! -f "$libva_archive" ]; then
    curl -fL --retry 5 --retry-delay 2 -o "$libva_archive" "$libva_url"
fi

printf '%s  %s\n' "$libva_sha256" "$libva_archive" | sha256sum -c -

if [ "$enable_nvidia" = 1 ]; then
    for archive_specification in \
        "$nvidia_vaapi_archive|$nvidia_vaapi_url|$nvidia_vaapi_sha256" \
        "$nv_codec_headers_archive|$nv_codec_headers_url|$nv_codec_headers_sha256" \
        "$gstreamer_archive|$gstreamer_url|$gstreamer_sha256" \
        "$gstreamer_base_archive|$gstreamer_base_url|$gstreamer_base_sha256" \
        "$gstreamer_bad_archive|$gstreamer_bad_url|$gstreamer_bad_sha256"
    do
        IFS='|' read -r archive url expected_sha256 <<EOF
$archive_specification
EOF
        if [ ! -f "$archive" ]; then
            curl -fL --retry 5 --retry-delay 2 -o "$archive" "$url"
        fi
        printf '%s  %s\n' "$expected_sha256" "$archive" | sha256sum -c -
    done
fi

libdrm_cache="$cache/libdrm"
if [ ! -d "$libdrm_cache/.git" ]; then
    rm -rf -- "$libdrm_cache"
    git clone --filter=blob:none --no-checkout https://gitlab.freedesktop.org/mesa/drm.git "$libdrm_cache"
fi

gmmlib_cache="$cache/gmmlib"
if [ ! -d "$gmmlib_cache/.git" ]; then
    rm -rf -- "$gmmlib_cache"
    git clone --filter=blob:none --no-checkout https://github.com/intel/gmmlib.git "$gmmlib_cache"
fi
git -C "$gmmlib_cache" fetch --depth 1 origin "$gmmlib_commit"
git -C "$gmmlib_cache" checkout --detach "$gmmlib_commit"
[ "$(git -C "$gmmlib_cache" rev-parse HEAD)" = "$gmmlib_commit" ] || {
    echo 'The checked-out Intel gmmlib commit does not match the pinned commit.' >&2
    exit 1
}

intel_media_cache="$cache/intel-media-driver"
if [ ! -d "$intel_media_cache/.git" ]; then
    rm -rf -- "$intel_media_cache"
    git clone --filter=blob:none --no-checkout https://github.com/intel/media-driver.git "$intel_media_cache"
fi
git -C "$intel_media_cache" fetch --depth 1 origin "$intel_media_commit"
git -C "$intel_media_cache" checkout --detach "$intel_media_commit"
[ "$(git -C "$intel_media_cache" rev-parse HEAD)" = "$intel_media_commit" ] || {
    echo 'The checked-out Intel media-driver commit does not match the pinned commit.' >&2
    exit 1
}

git -C "$libdrm_cache" fetch --depth 1 origin "$libdrm_commit"
git -C "$libdrm_cache" checkout --detach "$libdrm_commit"

if [ "$(git -C "$libdrm_cache" rev-parse HEAD)" != "$libdrm_commit" ]; then
    echo 'The checked-out libdrm commit does not match the pinned commit.' >&2
    exit 1
fi

case "$work" in
    /var/tmp/t1os-graphics-work) rm -rf -- "$work" ;;
    *) echo "Refusing to replace unexpected work path: $work" >&2; exit 1 ;;
esac

mkdir -p "$work/source" "$work/build" "$work/install"
tar -xf "$mesa_archive" -C "$work/source"
mkdir -p "$work/source/libva"
tar -xf "$libva_archive" --strip-components=1 -C "$work/source/libva"
cp -a -- "$libdrm_cache" "$work/source/libdrm"
cp -a -- "$gmmlib_cache" "$work/source/gmmlib"
cp -a -- "$intel_media_cache" "$work/source/intel-media-driver"

if [ "$enable_nvidia" = 1 ]; then
    printf '%s  %s\n' "$nvidia_sha256" "$nvidia_runfile" | sha256sum -c -
    sh "$nvidia_runfile" \
        --extract-only \
        --target "$work/source/nvidia-$nvidia_version"
    test -s "$work/source/nvidia-$nvidia_version/LICENSE"
    test -s "$work/source/nvidia-$nvidia_version/libEGL_nvidia.so.$nvidia_version"
    test -s "$work/source/nvidia-$nvidia_version/libnvidia-eglcore.so.$nvidia_version"
    mkdir -p \
        "$work/source/nvidia-vaapi-driver" \
        "$work/source/nv-codec-headers" \
        "$work/source/gstreamer" \
        "$work/source/gst-plugins-base" \
        "$work/source/gst-plugins-bad"
    tar -xf "$nvidia_vaapi_archive" --strip-components=1 \
        -C "$work/source/nvidia-vaapi-driver"
    python3 "$nvidia_vaapi_planar_patch" \
        "$work/source/nvidia-vaapi-driver"
    tar -xf "$nv_codec_headers_archive" --strip-components=1 \
        -C "$work/source/nv-codec-headers"
    tar -xf "$gstreamer_archive" --strip-components=1 \
        -C "$work/source/gstreamer"
    tar -xf "$gstreamer_base_archive" --strip-components=1 \
        -C "$work/source/gst-plugins-base"
    tar -xf "$gstreamer_bad_archive" --strip-components=1 \
        -C "$work/source/gst-plugins-bad"
    test -s "$work/source/nvidia-vaapi-driver/src/direct/nv-driver.c"
    test -s "$work/source/nvidia-vaapi-driver/src/vp9.c"
    test -s "$work/source/nv-codec-headers/include/ffnvcodec/dynlink_cuviddec.h"
    test -s "$work/source/gst-plugins-bad/gst-libs/gst/codecparsers/gstvp9parser.c"
fi

if [ "$(git -C "$work/source/libdrm" rev-parse HEAD)" != "$libdrm_commit" ]; then
    echo 'The staged libdrm source does not match the pinned commit.' >&2
    exit 1
fi

python3 - "$work/source/libdrm" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
replacements = {
    '/dev/dri': '/the one/drivers/nodes/dri',
    '/proc/dri': '/the one/drivers/state/dri',
    '/sys/dev/char': '/the one/drivers/state/dev/char',
    '/sys/bus/pci/devices': '/the one/drivers/state/bus/pci/devices',
    '/dev/pci': '/the one/drivers/nodes/pci',
}

for relative in ('xf86drm.h', 'xf86drm.c', 'xf86drmMode.c'):
    path = source / relative
    text = path.read_text(encoding='utf-8')
    for old, new in replacements.items():
        text = text.replace(old, new)
    path.write_text(text, encoding='utf-8')

# T1OS exposes a read-only sysfs view under the driver-state tier.  A DRM
# descriptor's Linux major number is authoritative even when a device's
# optional sysfs "device/drm" backlink is absent (as it is for VirtualBox's
# render node).  libva calls drmGetNodeTypeFromFd before it can create a VA
# display, so retain the state-tree validation when available and use the DRM
# major as the kernel-backed fallback.
path = source / 'xf86drm.c'
text = path.read_text(encoding='utf-8')
old = '''    return stat(path, &sbuf) == 0;
#elif defined(__FreeBSD__)'''
new = '''    return stat(path, &sbuf) == 0 || maj == DRM_MAJOR;
#elif defined(__FreeBSD__)'''
if text.count(old) != 1:
    raise SystemExit('libdrm DRM-node validation did not match the pinned source')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
PY

libdrm_build="$work/build/libdrm"
"$meson" setup "$libdrm_build" "$work/source/libdrm" \
    --buildtype=release \
    --default-library=shared \
    --prefix="$prefix" \
    --libdir=. \
    --strip \
    -Dintel="$libdrm_intel" \
    -Dradeon="$libdrm_radeon" \
    -Damdgpu="$libdrm_amdgpu" \
    -Dnouveau="$libdrm_nouveau" \
    -Dvmwgfx=disabled \
    -Domap=disabled \
    -Dexynos=disabled \
    -Dfreedreno=disabled \
    -Dtegra=disabled \
    -Dvc4=disabled \
    -Detnaviv=disabled \
    -Dcairo-tests=disabled \
    -Dman-pages=disabled \
    -Dvalgrind=disabled \
    -Dinstall-test-programs=false \
    -Dudev=false \
    -Dtests=false

"$meson" compile -C "$libdrm_build"
DESTDIR="$work/install" "$meson" install -C "$libdrm_build"

export PKG_CONFIG_PATH="$work/install$prefix/pkgconfig"
export PKG_CONFIG_SYSROOT_DIR="$work/install"
export LD_LIBRARY_PATH="$work/install$prefix"

libva_build="$work/build/libva"
"$meson" setup "$libva_build" "$work/source/libva" \
    --buildtype=release \
    --default-library=shared \
    --prefix="$prefix" \
    --libdir=. \
    --strip \
    -Ddriverdir="$prefix/drivers" \
    -Ddisable_drm=false \
    -Dwith_x11=no \
    -Dwith_glx=no \
    -Dwith_wayland=no \
    -Dwith_win32=no \
    -Denable_docs=false

"$meson" compile -C "$libva_build"
DESTDIR="$work/install" "$meson" install -C "$libva_build"

gmmlib_build="$work/build/gmmlib"
"$cmake" -S "$work/source/gmmlib" -B "$gmmlib_build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$prefix" \
    -DCMAKE_INSTALL_LIBDIR=. \
    -DBUILD_TESTING=OFF
"$cmake" --build "$gmmlib_build" --parallel
DESTDIR="$work/install" "$cmake" --install "$gmmlib_build" --strip

# pkg-config represents flags as a whitespace-separated string, so a staged
# sysroot containing the canonical "/the one" prefix is not safe as a native
# build dependency prefix. Mirror the already-built dependencies into a
# no-space build-only prefix. The installed runtime remains exclusively under
# /the one/catalogue/graphics.
build_deps="$work/build-dependencies"
refresh_build_dependencies() {
    rm -rf -- "$build_deps"
    mkdir -p "$build_deps"
    cp -a -- "$work/install$prefix/." "$build_deps/"
    if [ -d "$build_deps/pkgconfig" ]; then
        python3 - "$build_deps/pkgconfig" "$prefix" "$build_deps" <<'PY'
from pathlib import Path
import sys

pkgconfig, canonical, build_prefix = sys.argv[1:]
for path in Path(pkgconfig).glob('*.pc'):
    text = path.read_text(encoding='utf-8')
    text = text.replace(canonical.replace(' ', r'\ '), build_prefix)
    text = text.replace(canonical, build_prefix)
    path.write_text(text, encoding='utf-8')
PY
    fi
}

refresh_build_dependencies
export PKG_CONFIG_PATH="$build_deps/pkgconfig"
unset PKG_CONFIG_SYSROOT_DIR
export LD_LIBRARY_PATH="$build_deps"

# Intel's media driver is the current VA-API implementation for the i915 and
# Xe generations in this compatibility window. Patch its fallback device
# discovery into the T1OS-owned hardware namespace; callers that already pass
# a DRM file descriptor are unaffected.
python3 - "$work/source/intel-media-driver" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
replacements = {
    '/dev/dri': '/the one/drivers/nodes/dri',
    '/sys/dev/char': '/the one/drivers/state/dev/char',
    '/sys/class/drm': '/the one/drivers/state/class/drm',
    '/sys/bus/pci/devices': '/the one/drivers/state/bus/pci/devices',
}
for path in source.rglob('*'):
    if not path.is_file() or path.suffix.lower() not in {
        '.c', '.cc', '.cpp', '.h', '.hpp',
    }:
        continue
    text = path.read_text(encoding='utf-8', errors='surrogateescape')
    updated = text
    for old, new in replacements.items():
        updated = updated.replace(old, new)
    if updated != text:
        path.write_text(updated, encoding='utf-8', errors='surrogateescape')
PY

intel_media_build="$work/build/intel-media-driver"
"$cmake" -S "$work/source/intel-media-driver" -B "$intel_media_build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$prefix" \
    -DCMAKE_INSTALL_LIBDIR=. \
    -DCMAKE_PREFIX_PATH="$build_deps" \
    -DCMAKE_LIBRARY_PATH="$build_deps" \
    -DLIBVA_DRIVERS_PATH="$prefix/drivers" \
    -DMEDIA_RUN_TEST_SUITE=OFF \
    -DINSTALL_DRIVER_SYSCONF=OFF \
    -DBUILD_CMRTLIB=ON \
    -DENABLE_KERNELS=ON
"$cmake" --build "$intel_media_build" --parallel
DESTDIR="$work/install" "$cmake" --install "$intel_media_build" --strip

mesa_source="$work/source/mesa-$mesa_version"
mesa_build="$work/build/mesa"

python3 "$vmsvga_mesa_patch/apply_svga_video.py" \
    "$mesa_source" "$vmsvga_mesa_patch"

python3 - "$mesa_source/src/loader/loader.c" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding='utf-8')
old = '"/sys/dev/char/%d:%d/device/%s"'
new = '"/the one/drivers/state/dev/char/%d:%d/device/%s"'

if text.count(old) != 1:
    raise SystemExit('Mesa device-state path did not match the pinned source')

path.write_text(text.replace(old, new), encoding='utf-8')
PY

if [ "$enable_nvidia" = 1 ]; then
    python3 - "$mesa_source/src/gallium/drivers/nouveau" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
for path in source.rglob('*.[ch]'):
    text = path.read_text(encoding='utf-8')
    updated = text.replace('/lib/firmware', '/the one/drivers/firmware')
    if updated != text:
        path.write_text(updated, encoding='utf-8')
PY
fi

python3 - "$mesa_source" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
root_meson = source / 'meson.build'
text = root_meson.read_text(encoding='utf-8')
old = '''  with_gallium_radeonsi,
  with_gallium_virgl,
]'''
new = '''  with_gallium_radeonsi,
  with_gallium_virgl,
  with_gallium_svga,
]'''
if old not in text:
    raise SystemExit('Mesa VA driver eligibility list did not match the pinned source')
root_meson.write_text(text.replace(old, new, 1), encoding='utf-8')

va_meson = source / 'src/gallium/targets/va/meson.build'
text = va_meson.read_text(encoding='utf-8')
old = '''      dep_libdrm, driver_r600, driver_radeonsi, driver_nouveau, driver_d3d12, driver_virgl,
      idep_mesautil,'''
new = '''      dep_libdrm, driver_r600, driver_radeonsi, driver_nouveau, driver_d3d12, driver_virgl, driver_svga,
      idep_mesautil,'''
if old not in text:
    raise SystemExit('Mesa VA target dependency list did not match the pinned source')
text = text.replace(old, new, 1)
old = '''              [with_gallium_virgl, 'virtio_gpu'],
              [with_gallium_d3d12_video, 'd3d12']]'''
new = '''              [with_gallium_virgl, 'virtio_gpu'],
              [with_gallium_svga, 'vmwgfx'],
              [with_gallium_d3d12_video, 'd3d12']]'''
if old not in text:
    raise SystemExit('Mesa VA target driver list did not match the pinned source')
va_meson.write_text(text.replace(old, new, 1), encoding='utf-8')

dri_meson = source / 'src/gallium/targets/dri/meson.build'
text = dri_meson.read_text(encoding='utf-8')
old = '''              [with_gallium_virgl, 'virtio_gpu'],
              [with_gallium_d3d12_video, 'd3d12']]'''
new = '''              [with_gallium_virgl, 'virtio_gpu'],
              [with_gallium_svga, 'vmwgfx'],
              [with_gallium_d3d12_video, 'd3d12']]'''
if old not in text:
    raise SystemExit('Mesa unified Gallium VA driver list did not match the pinned source')
dri_meson.write_text(text.replace(old, new, 1), encoding='utf-8')
PY

"$meson" setup "$mesa_build" "$mesa_source" \
    --buildtype=release \
    --default-library=shared \
    --auto-features=disabled \
    --prefix="$prefix" \
    --libdir=. \
    --strip \
    -Dplatforms= \
    -Degl-native-platform=drm \
    -Ddri-drivers-path="$prefix/drivers" \
    -Dgbm-backends-path="$prefix/gbm" \
    -Dva-libs-path="$prefix/drivers" \
    -Dgallium-drivers="$gallium_drivers" \
    -Dgallium-va="$gallium_va" \
    -Dvulkan-drivers="$vulkan_drivers" \
    -Dglx=disabled \
    -Degl=enabled \
    -Dgbm=enabled \
    -Dgles1=disabled \
    -Dgles2=enabled \
    -Dopengl=false \
    -Dllvm="$llvm_option" \
    -Dshared-llvm="$shared_llvm" \
    -Dspirv-tools="$spirv_tools" \
    -Dshader-cache=enabled \
    -Dxmlconfig=disabled \
    -Dzstd=enabled \
    -Dzlib=disabled \
    -Dvideo-codecs="$video_codecs" \
    -Dgallium-rusticl=false \
    -Dbuild-tests=false \
    -Dtools= \
    -Dperfetto=false \
    -Dteflon=false \
    -Dallow-fallback-for=

"$meson" compile -C "$mesa_build"
DESTDIR="$work/install" "$meson" install -C "$mesa_build"

if [ "$enable_nvidia" = 1 ]; then
    # Mesa has now supplied EGL and refreshed pkg-config metadata. Recreate the
    # no-space dependency prefix before building the Chromium-facing NVDEC
    # adapter; the earlier snapshot intentionally predates Mesa.
    refresh_build_dependencies
    make -C "$work/source/nv-codec-headers" \
        PREFIX="$build_deps" \
        LIBDIR=. \
        install

    gst_prefix="$work/gstreamer-dependencies"
    rm -rf -- "$gst_prefix"
    gst_core_build="$work/build/gstreamer"
    gst_base_build="$work/build/gst-plugins-base"
    gst_bad_build="$work/build/gst-plugins-bad"

    export PKG_CONFIG_PATH="$build_deps/pkgconfig"
    export LD_LIBRARY_PATH="$build_deps"
    "$meson" setup "$gst_core_build" "$work/source/gstreamer" \
        --prefix="$gst_prefix" \
        --libdir=lib \
        --buildtype=release \
        --default-library=shared \
        --strip \
        --auto-features=disabled \
        -Dgst_debug=false \
        -Dgst_parse=false \
        -Dregistry=false \
        -Dtracer_hooks=false \
        -Dptp-helper=disabled \
        -Doption-parsing=false \
        -Dcheck=disabled \
        -Dlibunwind=disabled \
        -Dlibdw=disabled \
        -Dbash-completion=disabled \
        -Dcoretracers=disabled \
        -Dexamples=disabled \
        -Dtests=disabled \
        -Dbenchmarks=disabled \
        -Dtools=disabled \
        -Dintrospection=disabled \
        -Dnls=disabled \
        -Ddoc=disabled \
        -Dextra-checks=disabled \
        -Dglib_debug=disabled \
        -Dglib_assert=false \
        -Dglib_checks=false
    "$meson" compile -C "$gst_core_build"
    "$meson" install -C "$gst_core_build"

    export PKG_CONFIG_PATH="$gst_prefix/lib/pkgconfig:$build_deps/pkgconfig"
    export LD_LIBRARY_PATH="$gst_prefix/lib:$build_deps"
    "$meson" setup "$gst_base_build" "$work/source/gst-plugins-base" \
        --prefix="$gst_prefix" \
        --libdir=lib \
        --buildtype=release \
        --default-library=shared \
        --strip \
        --auto-features=disabled \
        -Dexamples=disabled \
        -Dtests=disabled \
        -Dtools=disabled \
        -Dintrospection=disabled \
        -Dnls=disabled \
        -Ddoc=disabled \
        -Dorc=disabled \
        -Dgl=disabled \
        -Dglib_debug=disabled \
        -Dglib_assert=false \
        -Dglib_checks=false
    "$meson" compile -C "$gst_base_build"
    "$meson" install -C "$gst_base_build"

    "$meson" setup "$gst_bad_build" "$work/source/gst-plugins-bad" \
        --prefix="$gst_prefix" \
        --libdir=lib \
        --buildtype=release \
        --default-library=shared \
        --strip \
        --auto-features=disabled \
        -Dexamples=disabled \
        -Dtests=disabled \
        -Dtools=disabled \
        -Dintrospection=disabled \
        -Dnls=disabled \
        -Ddoc=disabled \
        -Dorc=disabled \
        -Dextra-checks=disabled \
        -Dglib_debug=disabled \
        -Dglib_assert=false \
        -Dglib_checks=false
    "$meson" compile -C "$gst_bad_build"
    "$meson" install -C "$gst_bad_build"
    pkg-config --atleast-version="$gstreamer_version" \
        gstreamer-codecparsers-1.0

    nvidia_vaapi_build="$work/build/nvidia-vaapi-driver"
    "$meson" setup \
        "$nvidia_vaapi_build" \
        "$work/source/nvidia-vaapi-driver" \
        --prefix="$prefix" \
        --libdir=. \
        --buildtype=release \
        --default-library=shared \
        --strip \
        --wrap-mode=nofallback
    "$meson" compile -C "$nvidia_vaapi_build"
    # libva.pc points driverdir at the no-space build mirror. Materialize the
    # one reviewed output directly into the canonical staged runtime instead
    # of letting Meson install any unrelated file into that mirror.
    mkdir -p "$work/install$prefix/drivers"
    cp -- "$nvidia_vaapi_build/nvidia_drv_video.so" \
        "$work/install$prefix/drivers/nvidia_drv_video.so"
    test -s "$work/install$prefix/drivers/nvidia_drv_video.so"
    readelf -Ws "$work/install$prefix/drivers/nvidia_drv_video.so" |
        grep -F 'vp9Codec' >/dev/null
fi

runtime="$work/install$prefix"
rm -rf -- "$catalogue_stage" "$software_stage"
mkdir -p "$catalogue_stage/gbm" "$catalogue_stage/drivers" "$catalogue_stage/vulkan/icd.d" "$software_stage"

copy_elf_soname() {
    source_file=$1
    soname=$(readelf -d "$source_file" 2>/dev/null | sed -n 's/.*(SONAME).*\[\([^]]*\)\].*/\1/p' | head -n 1)
    if [ -n "$soname" ]; then
        cp -L -- "$source_file" "$catalogue_stage/$soname"
    fi
}

find "$runtime" -maxdepth 1 \( -type f -o -type l \) -print0 | while IFS= read -r -d '' runtime_file; do
    copy_elf_soname "$runtime_file"
done

if [ "$enable_nvidia" = 1 ]; then
    for gstreamer_soname in \
        libgstreamer-1.0.so.0 \
        libgstbase-1.0.so.0 \
        libgstcodecparsers-1.0.so.0
    do
        gstreamer_library=$(find "$gst_prefix/lib" -maxdepth 1 -type f \
            -name "$gstreamer_soname.*" -print -quit)
        [ -n "$gstreamer_library" ] && [ -s "$gstreamer_library" ] || {
            echo "Missing pinned GStreamer runtime library: $gstreamer_soname" >&2
            exit 1
        }
        copy_elf_soname "$gstreamer_library"
    done
fi

# Mesa's Vulkan drivers and Zink load the Vulkan loader dynamically by SONAME,
# so it is not visible in the ELF NEEDED closure. Package it explicitly for
# every hardware profile; the dependency pass then collects its dependencies.
if [ "$profile" = hardware ]; then
    require_command ldconfig
    # Consume the complete ldconfig stream.  Exiting awk after the first match
    # closes the pipe early and, under pipefail, turns ldconfig's SIGPIPE into
    # a false build failure after the expensive driver compilation completed.
    vulkan_loader=$(ldconfig -p | awk '
        /libvulkan\.so\.1 .*x86-64/ && !found { loader = $NF; found = 1 }
        END { if (found) print loader }
    ')
    [ -n "$vulkan_loader" ] && [ -f "$vulkan_loader" ] || {
        echo 'Could not resolve the Vulkan loader libvulkan.so.1.' >&2
        exit 1
    }
    copy_elf_soname "$vulkan_loader"
fi

find "$runtime/gbm" -maxdepth 1 \( -type f -o -type l \) -name '*.so' -print0 | while IFS= read -r -d '' backend_file; do
    cp -L -- "$backend_file" "$catalogue_stage/gbm/$(basename "$backend_file")"
done

if [ -d "$runtime/drivers" ]; then
    find "$runtime/drivers" -maxdepth 1 \( -type f -o -type l \) -name '*.so' -print0 | while IFS= read -r -d '' driver_file; do
        cp -L -- "$driver_file" "$catalogue_stage/drivers/$(basename "$driver_file")"
    done
fi

if [ -d "$runtime/share/vulkan/icd.d" ]; then
    find "$runtime/share/vulkan/icd.d" -maxdepth 1 -type f -name '*.json' -exec cp -- {} "$catalogue_stage/vulkan/icd.d/" \;
fi

if [ "$enable_nvidia" = 1 ]; then
    nvidia_source="$work/source/nvidia-$nvidia_version"
    nvidia_stage="$catalogue_stage/nvidia"
    mkdir -p \
        "$nvidia_stage/egl_vendor.d" \
        "$nvidia_stage/gbm"

    # T1OS forbids runtime symlinks. Materialize each ABI name as a regular
    # file from NVIDIA's matching runfile instead of reproducing its symlink
    # installation layout.
    cp -- "$nvidia_source/libEGL.so.1.1.0" \
        "$nvidia_stage/libEGL.so.1"
    cp -- "$nvidia_source/libGLESv2.so.2.1.0" \
        "$nvidia_stage/libGLESv2.so.2"
    cp -- "$nvidia_source/libGLdispatch.so.0" \
        "$nvidia_stage/libGLdispatch.so.0"
    cp -- "$nvidia_source/libEGL_nvidia.so.$nvidia_version" \
        "$nvidia_stage/libEGL_nvidia.so.0"
    cp -- "$nvidia_source/libGLESv2_nvidia.so.$nvidia_version" \
        "$nvidia_stage/libGLESv2_nvidia.so.2"
    for nvidia_library in \
        libnvidia-eglcore \
        libnvidia-glsi \
        libnvidia-gpucomp \
        libnvidia-glcore \
        libnvidia-glvkspirv \
        libnvidia-rtcore \
        libnvidia-ptxjitcompiler \
        libnvidia-tls
    do
        test -s "$nvidia_source/$nvidia_library.so.$nvidia_version"
        cp -- "$nvidia_source/$nvidia_library.so.$nvidia_version" \
            "$nvidia_stage/$nvidia_library.so.$nvidia_version"
    done
    cp -- "$nvidia_source/libnvidia-allocator.so.$nvidia_version" \
        "$nvidia_stage/libnvidia-allocator.so.1"
    cp -- "$nvidia_source/libcuda.so.$nvidia_version" \
        "$nvidia_stage/libcuda.so.1"
    cp -- "$nvidia_source/libnvcuvid.so.$nvidia_version" \
        "$nvidia_stage/libnvcuvid.so.1"
    cp -- "$nvidia_source/libnvidia-ptxjitcompiler.so.$nvidia_version" \
        "$nvidia_stage/libnvidia-ptxjitcompiler.so.1"
    cp -- "$nvidia_source/libnvidia-egl-gbm.so.1.1.3" \
        "$nvidia_stage/libnvidia-egl-gbm.so.1"
    cp -- "$nvidia_source/libnvidia-allocator.so.$nvidia_version" \
        "$nvidia_stage/gbm/nvidia-drm_gbm.so"
    cp -- "$nvidia_source/LICENSE" "$nvidia_stage/LICENSE.txt"
    cp -- "$work/source/nvidia-vaapi-driver/COPYING" \
        "$nvidia_stage/nvidia-vaapi-driver-LICENSE.txt"
    cp -- "$nvidia_source/supported-gpus/supported-gpus.json" \
        "$nvidia_stage/supported-gpus.json"
    test -s "$nvidia_path_provider"
    gcc \
        "${hardening_cflags[@]}" \
        -shared \
        -fPIC \
        -Wall \
        -Wextra \
        -Werror \
        "${hardening_ldflags[@]}" \
        -Wl,-soname,t1os-nvidia-path-provider.so \
        -o "$nvidia_stage/t1os-nvidia-path-provider.so" \
        "$nvidia_path_provider" \
        -ldl
    readelf -Ws "$nvidia_stage/t1os-nvidia-path-provider.so" |
        grep -E ' (open|open64|openat|openat64|access|__xstat64|opendir|realpath)$' \
        >/dev/null
    readelf -lW "$nvidia_stage/t1os-nvidia-path-provider.so" |
        grep -F 'GNU_RELRO' >/dev/null
    readelf -dW "$nvidia_stage/t1os-nvidia-path-provider.so" |
        grep -F 'BIND_NOW' >/dev/null
    readelf -lW "$nvidia_stage/t1os-nvidia-path-provider.so" |
        grep -E 'GNU_STACK.*RW[[:space:]]' >/dev/null
    if readelf -lW "$nvidia_stage/t1os-nvidia-path-provider.so" |
            grep -E 'GNU_STACK.*RWE' >/dev/null; then
        echo 'The NVIDIA path provider has an executable stack.' >&2
        exit 1
    fi
    strings "$nvidia_stage/t1os-nvidia-path-provider.so" |
        grep -F '/the one/drivers/nodes' >/dev/null
    strings "$nvidia_stage/t1os-nvidia-path-provider.so" |
        grep -F '/the one/drivers/processes' >/dev/null
    strings "$nvidia_stage/t1os-nvidia-path-provider.so" |
        grep -F '/the one/drivers/state' >/dev/null
    strings "$nvidia_stage/t1os-nvidia-path-provider.so" |
        grep -F 't1os-cuda-thread-name' >/dev/null
    if strings "$nvidia_stage/t1os-nvidia-path-provider.so" |
        grep -F '/the one/drivers/nodes/null' >/dev/null; then
        exit 1
    fi
    strings "$nvidia_stage/t1os-nvidia-path-provider.so" |
        grep -Fx 'nvidia-uvm' >/dev/null
    if strings "$nvidia_stage/t1os-nvidia-path-provider.so" |
        grep -Fx 'nvidia-uvm-tools' >/dev/null; then
        exit 1
    fi
    (
        # glibc tokenizes LD_PRELOAD on spaces as well as colons. The WSL
        # staging path inherits the project directory name and therefore
        # cannot be used as an LD_PRELOAD value directly. Exercise the exact
        # staged provider from a private, space-free path instead.
        nvidia_path_provider_selftest="/var/tmp/t1os-nvidia-path-provider-selftest-$$.so"
        trap 'rm -f -- "$nvidia_path_provider_selftest"' EXIT
        cp -- "$nvidia_stage/t1os-nvidia-path-provider.so" \
            "$nvidia_path_provider_selftest"
        LD_PRELOAD="$nvidia_path_provider_selftest" \
            python3 - <<'PY'
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

    python3 - \
        "$nvidia_stage" \
        "$nvidia_version" \
        "$nvidia_sha256" \
        "$nvidia_vaapi_commit" \
        "$nv_codec_headers_version" \
        "$nv_codec_headers_commit" \
        "$gstreamer_version" <<'PY'
from pathlib import Path
import json
import sys

root = Path(sys.argv[1])
(root / "egl_vendor.d/10_nvidia.json").write_text(
    json.dumps({
        "file_format_version": "1.0.0",
        "ICD": {
            "library_path": (
                "/the one/catalogue/graphics/nvidia/libEGL_nvidia.so.0"
            ),
        },
    }, indent=2) + "\n",
    encoding="utf-8",
)
(root / "gbm/15_nvidia_gbm.json").write_text(
    json.dumps({
        "file_format_version": "1.0.0",
        "ICD": {
            "library_path": (
                "/the one/catalogue/graphics/nvidia/"
                "libnvidia-egl-gbm.so.1"
            ),
        },
    }, indent=2) + "\n",
    encoding="utf-8",
)
(root / "runtime.json").write_text(
    json.dumps({
        "format": 1,
        "provider": "nvidia-open",
        "version": sys.argv[2],
        "runfile_sha256": sys.argv[3],
        "kernel_module_flavor": "open",
        "supported_generation": "Turing and newer",
        "video_decode": {
            "api": "VA-API",
            "backend": "NVDEC direct",
            "driver_commit": sys.argv[4],
            "nv_codec_headers": {
                "version": sys.argv[5],
                "commit": sys.argv[6],
            },
            "gstreamer_codecparsers": sys.argv[7],
            "dma_buf_export": "multi-object-natural-per-plane-modifier-v2",
            "software_fallback": False,
        },
    }, indent=2) + "\n",
    encoding="utf-8",
)
PY
fi

# glibc 2.34 and newer provide the former libdl, libpthread, and librt
# interfaces from libc.  T1OS intentionally ships that merged runtime
# without the legacy compatibility DSOs, while several upstream graphics
# binaries retain their old DT_NEEDED names.  Rewrite those names before
# dependency closure instead of declaring libraries that are not deployed.
find "$catalogue_stage" -type f -print0 |
while IFS= read -r -d '' elf_file; do
    if ! readelf -h "$elf_file" >/dev/null 2>&1; then
        continue
    fi

    for merged_library in libdl.so.2 libpthread.so.0 librt.so.1; do
        if patchelf --print-needed "$elf_file" |
                grep -Fx "$merged_library" >/dev/null; then
            patchelf --replace-needed \
                "$merged_library" \
                libc.so.6 \
                "$elf_file"
        fi
    done

    if patchelf --print-needed "$elf_file" |
            grep -Ex 'libdl\.so\.2|libpthread\.so\.0|librt\.so\.1' \
                >/dev/null; then
        echo "Merged glibc dependency remains after rewrite: $elf_file" >&2
        patchelf --print-needed "$elf_file" >&2
        exit 1
    fi
done

python3 - "$catalogue_stage" <<'PY'
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

catalogue = Path(sys.argv[1])
provided = {path.name for path in catalogue.rglob('*') if path.is_file()}
base = {
    'ld-linux-x86-64.so.2',
    'libc.so.6',
    'libm.so.6',
    'libz.so.1',
    'libzstd.so.1',
}

def dynamic(path):
    result = subprocess.run(
        ['readelf', '-d', str(path)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.stdout

def needed(path):
    return re.findall(r'\(NEEDED\).*?\[([^]]+)\]', dynamic(path))

def locate(name):
    result = subprocess.run(
        ['ldconfig', '-p'],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    pattern = re.compile(r'^\s*' + re.escape(name) + r'\s+.*=>\s+(\S+)$')
    for line in result.stdout.splitlines():
        match = pattern.match(line)
        if match and 'x86-64' in line:
            return Path(match.group(1))
    raise RuntimeError(f'Could not resolve runtime dependency: {name}')

changed = True
while changed:
    changed = False
    for path in list(catalogue.rglob('*')):
        if not path.is_file():
            continue
        for name in needed(path):
            if name in provided or name in base:
                continue
            source = locate(name)
            shutil.copyfile(source.resolve(), catalogue / name)
            provided.add(name)
            changed = True
PY

find "$catalogue_stage" -type f -print0 | while IFS= read -r -d '' elf_file; do
    if readelf -h "$elf_file" >/dev/null 2>&1; then
        case "$elf_file" in
            "$catalogue_stage"/nvidia/*|\
            "$catalogue_stage"/drivers/nvidia_drv_video.so)
                patchelf --set-rpath "$nvidia_runtime_runpath" "$elf_file"
                ;;
            *)
                patchelf --set-rpath "$runtime_runpath" "$elf_file"
                strip --strip-unneeded "$elf_file" 2>/dev/null || true
                ;;
        esac
    fi
done

cp -- "$mesa_source/docs/license.rst" "$catalogue_stage/licence mesa.txt"
sed -n '9,32p' "$work/source/libdrm/xf86drm.c" > "$catalogue_stage/licence libdrm.txt"
cp -- "$work/source/libva/COPYING" "$catalogue_stage/licence libva.txt"
cp -- "$work/source/gmmlib/LICENSE.md" "$catalogue_stage/licence intel gmmlib.txt"
cp -- "$work/source/intel-media-driver/LICENSE.md" "$catalogue_stage/licence intel media driver.txt"

cat > "$software_stage/version.txt" <<EOF
T1OS graphics runtime
Mesa $mesa_version
libdrm $libdrm_version ($libdrm_commit)
libva $libva_version
Intel gmmlib $gmmlib_version ($gmmlib_commit)
Intel media driver $intel_media_version ($intel_media_commit)
Meson $meson_version
CMake $cmake_version
NVIDIA open GPU driver $nvidia_version
NVIDIA VA-API driver $nvidia_vaapi_commit
NVIDIA codec headers $nv_codec_headers_version ($nv_codec_headers_commit)
GStreamer codec parsers $gstreamer_version
EOF

export T1OS_CATALOGUE_STAGE="$catalogue_stage"
export T1OS_MESA_VERSION="$mesa_version"
export T1OS_MESA_SHA256="$mesa_sha256"
export T1OS_LIBDRM_VERSION="$libdrm_version"
export T1OS_LIBDRM_COMMIT="$libdrm_commit"
export T1OS_LIBVA_VERSION="$libva_version"
export T1OS_LIBVA_SHA256="$libva_sha256"
export T1OS_GMMLIB_VERSION="$gmmlib_version"
export T1OS_GMMLIB_COMMIT="$gmmlib_commit"
export T1OS_INTEL_MEDIA_VERSION="$intel_media_version"
export T1OS_INTEL_MEDIA_COMMIT="$intel_media_commit"
export T1OS_MESON_VERSION="$meson_version"
export T1OS_CMAKE_VERSION="$cmake_version"
export T1OS_RUNTIME_RUNPATH="$runtime_runpath"
export T1OS_NVIDIA_RUNTIME_RUNPATH="$nvidia_runtime_runpath"
export T1OS_NVIDIA_VERSION="$nvidia_version"
export T1OS_NVIDIA_SHA256="$nvidia_sha256"
export T1OS_NVIDIA_VAAPI_COMMIT="$nvidia_vaapi_commit"
export T1OS_NVIDIA_VAAPI_SHA256="$nvidia_vaapi_sha256"
export T1OS_NV_CODEC_HEADERS_VERSION="$nv_codec_headers_version"
export T1OS_NV_CODEC_HEADERS_COMMIT="$nv_codec_headers_commit"
export T1OS_NV_CODEC_HEADERS_SHA256="$nv_codec_headers_sha256"
export T1OS_GSTREAMER_VERSION="$gstreamer_version"
export T1OS_GSTREAMER_SHA256="$gstreamer_sha256"
export T1OS_GSTREAMER_BASE_SHA256="$gstreamer_base_sha256"
export T1OS_GSTREAMER_BAD_SHA256="$gstreamer_bad_sha256"
export T1OS_GRAPHICS_PROFILE="$profile"
export T1OS_ENABLE_NVIDIA="$enable_nvidia"
export T1OS_RUST_VERSION="$rust_version"
export T1OS_BINDGEN_VERSION="$bindgen_version"

python3 - <<'PY'
from pathlib import Path
import hashlib
import json
import os
import platform
import re
import subprocess

catalogue = Path(os.environ['T1OS_CATALOGUE_STAGE'])
runtime_runpath = os.environ['T1OS_RUNTIME_RUNPATH']
nvidia_runtime_runpath = os.environ['T1OS_NVIDIA_RUNTIME_RUNPATH']
base = {
    'ld-linux-x86-64.so.2',
    'libc.so.6',
    'libm.so.6',
    'libz.so.1',
    'libzstd.so.1',
}

def inspect(path):
    result = subprocess.run(
        ['readelf', '-d', str(path)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    output = result.stdout
    return {
        'needed': re.findall(r'\(NEEDED\).*?\[([^]]+)\]', output),
        'soname': (re.findall(r'\(SONAME\).*?\[([^]]+)\]', output) or [None])[0],
        'runpath': (re.findall(r'\(RUNPATH\).*?\[([^]]+)\]', output) or [None])[0],
    }

files = []
provided = {path.name for path in catalogue.rglob('*') if path.is_file()}
for path in sorted(catalogue.rglob('*')):
    if (
        not path.is_file()
        or path.name == 'catalogue.json'
        or path.name.startswith('licence ')
    ):
        continue
    relative = path.relative_to(catalogue).as_posix()
    data = path.read_bytes()
    metadata = inspect(path)
    files.append({
        'path': relative,
        'size': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        **metadata,
    })

unresolved = sorted({
    dependency
    for file in files
    for dependency in file['needed']
    if dependency not in provided and dependency not in base
})
merged_glibc_dependencies = sorted({
    f"{file['path']}:{dependency}"
    for file in files
    for dependency in file['needed']
    if dependency in {
        'libdl.so.2',
        'libpthread.so.0',
        'librt.so.1',
    }
})
invalid_runpaths = sorted(
    file['path'] for file in files
    if (
        file['needed']
        and file['runpath'] != (
            nvidia_runtime_runpath
            if (
                file['path'].startswith('nvidia/')
                or file['path'] == 'drivers/nvidia_drv_video.so'
            )
            else runtime_runpath
        )
    )
)
symlinks = sorted(path.relative_to(catalogue).as_posix() for path in catalogue.rglob('*') if path.is_symlink())
required = {
    'libdrm.so.2',
    'libva.so.2',
    'libva-drm.so.2',
    'libEGL.so.1',
    'libGLESv2.so.2',
    'libgbm.so.1',
    'libgallium-26.1.5.so',
    'gbm/dri_gbm.so',
}
profile = os.environ['T1OS_GRAPHICS_PROFILE']
enable_nvidia = os.environ['T1OS_ENABLE_NVIDIA'] == '1'
if profile == 'hardware':
    required.update({
        'libdrm_amdgpu.so.1',
        'libdrm_intel.so.1',
        'libdrm_radeon.so.1',
        'libvulkan.so.1',
        'libvulkan_intel.so',
        'libvulkan_radeon.so',
        'drivers/iHD_drv_video.so',
        'drivers/r600_drv_video.so',
        'drivers/radeonsi_drv_video.so',
    })
if profile == 'vm':
    required.add('drivers/vmwgfx_drv_video.so')
if enable_nvidia:
    required.update({
        'libdrm_nouveau.so.2',
        'libvulkan.so.1',
        'libvulkan_nouveau.so',
        'drivers/nouveau_drv_video.so',
        'drivers/nvidia_drv_video.so',
        'libgstreamer-1.0.so.0',
        'libgstbase-1.0.so.0',
        'libgstcodecparsers-1.0.so.0',
        'nvidia/libEGL.so.1',
        'nvidia/libGLESv2.so.2',
        'nvidia/libGLdispatch.so.0',
        'nvidia/libEGL_nvidia.so.0',
        'nvidia/libGLESv2_nvidia.so.2',
        'nvidia/libnvidia-eglcore.so.' + os.environ['T1OS_NVIDIA_VERSION'],
        'nvidia/libnvidia-glsi.so.' + os.environ['T1OS_NVIDIA_VERSION'],
        'nvidia/libnvidia-gpucomp.so.' + os.environ['T1OS_NVIDIA_VERSION'],
        'nvidia/libcuda.so.1',
        'nvidia/libnvcuvid.so.1',
        'nvidia/libnvidia-ptxjitcompiler.so.1',
        'nvidia/libnvidia-egl-gbm.so.1',
        'nvidia/egl_vendor.d/10_nvidia.json',
        'nvidia/gbm/15_nvidia_gbm.json',
        'nvidia/gbm/nvidia-drm_gbm.so',
        'nvidia/t1os-nvidia-path-provider.so',
        'nvidia/nvidia-vaapi-driver-LICENSE.txt',
        'nvidia/runtime.json',
    })
missing = sorted(required - {file['path'] for file in files})

if (
    unresolved
    or merged_glibc_dependencies
    or invalid_runpaths
    or symlinks
    or missing
):
    raise SystemExit(json.dumps({
        'unresolved': unresolved,
        'merged_glibc_dependencies': merged_glibc_dependencies,
        'invalid_runpaths': invalid_runpaths,
        'symlinks': symlinks,
        'missing': missing,
    }, indent=2))

manifest = {
    'format': 1,
    'state': 'ready',
    'architecture': 'x86_64',
    'runtime': {
        'runpath': runtime_runpath,
        'nvidia_runpath': nvidia_runtime_runpath if enable_nvidia else None,
        'gbm_backend_path': '/the one/catalogue/graphics/gbm',
        'nvidia_gbm_backend_path': (
            '/the one/catalogue/graphics/nvidia/gbm'
            if enable_nvidia else None
        ),
        'nvidia_path_provider': (
            '/the one/catalogue/graphics/nvidia/'
            't1os-nvidia-path-provider.so'
            if enable_nvidia else None
        ),
        'device_path': '/the one/drivers/nodes/dri',
        'base_dependencies': sorted(base),
    },
    'sources': {
        'mesa': {
            'version': os.environ['T1OS_MESA_VERSION'],
            'sha256': os.environ['T1OS_MESA_SHA256'],
        },
        'libdrm': {
            'version': os.environ['T1OS_LIBDRM_VERSION'],
            'commit': os.environ['T1OS_LIBDRM_COMMIT'],
        },
        'libva': {
            'version': os.environ['T1OS_LIBVA_VERSION'],
            'sha256': os.environ['T1OS_LIBVA_SHA256'],
        },
        'intel_gmmlib': {
            'version': os.environ['T1OS_GMMLIB_VERSION'],
            'commit': os.environ['T1OS_GMMLIB_COMMIT'],
        },
        'intel_media_driver': {
            'version': os.environ['T1OS_INTEL_MEDIA_VERSION'],
            'commit': os.environ['T1OS_INTEL_MEDIA_COMMIT'],
        },
        'meson': os.environ['T1OS_MESON_VERSION'],
        'cmake': os.environ['T1OS_CMAKE_VERSION'],
        'rust': os.environ['T1OS_RUST_VERSION'] if enable_nvidia else None,
        'bindgen': os.environ['T1OS_BINDGEN_VERSION'] if enable_nvidia else None,
        'nvidia_open_driver': (
            {
                'version': os.environ['T1OS_NVIDIA_VERSION'],
                'runfile_sha256': os.environ['T1OS_NVIDIA_SHA256'],
                'supported_generation': 'Turing and newer',
            }
            if enable_nvidia else None
        ),
        'nvidia_vaapi_driver': (
            {
                'commit': os.environ['T1OS_NVIDIA_VAAPI_COMMIT'],
                'archive_sha256': os.environ['T1OS_NVIDIA_VAAPI_SHA256'],
                'backend': 'NVDEC direct',
                'chromium_export': True,
                't1os_planar_export': 'multi-object-natural-per-plane-modifier-v2',
            }
            if enable_nvidia else None
        ),
        'nv_codec_headers': (
            {
                'version': os.environ['T1OS_NV_CODEC_HEADERS_VERSION'],
                'commit': os.environ['T1OS_NV_CODEC_HEADERS_COMMIT'],
                'archive_sha256': os.environ['T1OS_NV_CODEC_HEADERS_SHA256'],
            }
            if enable_nvidia else None
        ),
        'gstreamer_codecparsers': (
            {
                'version': os.environ['T1OS_GSTREAMER_VERSION'],
                'gstreamer_sha256': os.environ['T1OS_GSTREAMER_SHA256'],
                'plugins_base_sha256': os.environ[
                    'T1OS_GSTREAMER_BASE_SHA256'
                ],
                'plugins_bad_sha256': os.environ[
                    'T1OS_GSTREAMER_BAD_SHA256'
                ],
                'purpose': 'NVIDIA VA-API VP9 parser',
            }
            if enable_nvidia else None
        ),
        'compiler': subprocess.check_output(['gcc', '-dumpfullversion'], text=True).strip(),
        'build_host': platform.platform(),
    },
    'profile': profile,
    'drivers': (
        ['i915', 'xe', 'iris', 'crocus', 'anv', 'radeon', 'r600', 'r600-vaapi', 'amdgpu', 'radeonsi', 'radv', 'nvidia-open', 'nvidia-nvdec-vaapi', 'nouveau', 'nouveau-vaapi', 'nvk', 'zink', 'virtio_gpu', 'vmwgfx', 'swrast']
        if enable_nvidia else
        ['i915', 'xe', 'iris', 'crocus', 'anv', 'radeon', 'r600', 'r600-vaapi', 'amdgpu', 'radeonsi', 'radv', 'virtio_gpu', 'vmwgfx', 'swrast']
        if profile == 'hardware' else
        ['virtio_gpu', 'vmwgfx', 'vmwgfx-vaapi', 'swrast']
    ),
    'files': files,
}

(catalogue / 'catalogue.json').write_text(
    json.dumps(manifest, indent=2) + '\n',
    encoding='utf-8',
)
PY

printf 'Packaged graphics catalogue files: '
find "$catalogue_stage" -type f | wc -l
du -sh "$catalogue_stage"
'@

Write-Host "Building Mesa $mesaVersion and libdrm $libdrmVersion in WSL..."
$buildScriptPath = Join-Path $stageRoot 'build-graphics-runtime.sh'
[System.IO.File]::WriteAllText(
    $buildScriptPath,
    $buildCommand,
    [System.Text.UTF8Encoding]::new($false)
)
$wslBuildScript = ConvertTo-WslPath -WindowsPath $buildScriptPath
$buildExitCode = 1
try {
    & wsl.exe -u root --exec bash $wslBuildScript $wslCatalogueStage $wslSoftwareStage $mesaVersion $mesaSha256 $libdrmVersion $libdrmCommit $mesonVersion $cleanValue $Profile $nvidiaValue $rustVersion $bindgenVersion $libvaVersion $libvaSha256 $wslVmsvgaMesaPatch $gmmlibVersion $gmmlibCommit $intelMediaVersion $intelMediaCommit $cmakeVersion $wslNvidiaRunfile $nvidiaVersion $nvidiaSha256 $wslNvidiaPathProviderSource $nvidiaVaapiCommit $nvidiaVaapiSha256 $nvCodecHeadersVersion $nvCodecHeadersCommit $nvCodecHeadersSha256 $gstreamerVersion $gstreamerSha256 $gstreamerBaseSha256 $gstreamerBadSha256 $wslNvidiaVaapiPlanarPatch
    $buildExitCode = $LASTEXITCODE
}
finally {
    if (Test-Path -LiteralPath $buildScriptPath) {
        Remove-Item -LiteralPath $buildScriptPath -Force
    }
}
if ($buildExitCode -ne 0) {
    throw "The graphics runtime build failed (exit code $buildExitCode)."
}

$manifestStage = Join-Path $catalogueStage 'catalogue.json'
if (-not (Test-Path -LiteralPath $manifestStage -PathType Leaf)) {
    throw "The staged graphics manifest was not generated: $manifestStage"
}

$manifest = Get-Content -LiteralPath $manifestStage -Raw | ConvertFrom-Json
if ($manifest.state -ne 'ready' -or $manifest.sources.mesa.version -ne $mesaVersion -or $manifest.sources.libdrm.commit -ne $libdrmCommit) {
    throw 'The staged graphics manifest does not match the pinned build inputs.'
}
if ($EnableNvidia -and $manifest.sources.nvidia_open_driver.version -ne $nvidiaVersion) {
    throw 'The staged NVIDIA graphics userspace does not match the pinned driver.'
}
if (
    $EnableNvidia -and (
        $manifest.sources.nvidia_vaapi_driver.commit -ne $nvidiaVaapiCommit -or
        $manifest.sources.nvidia_vaapi_driver.t1os_planar_export -ne 'multi-object-natural-per-plane-modifier-v2' -or
        $manifest.sources.nv_codec_headers.commit -ne $nvCodecHeadersCommit -or
        $manifest.sources.gstreamer_codecparsers.version -ne $gstreamerVersion
    )
) {
    throw 'The staged NVIDIA video decode runtime does not match the pinned sources.'
}

Remove-Item -LiteralPath (Join-Path $catalogueStage 'licence mesa.txt') -Force
Remove-Item -LiteralPath (Join-Path $catalogueStage 'licence libdrm.txt') -Force
Remove-Item -LiteralPath (Join-Path $catalogueStage 'licence libva.txt') -Force
Remove-Item -LiteralPath (Join-Path $catalogueStage 'licence intel gmmlib.txt') -Force
Remove-Item -LiteralPath (Join-Path $catalogueStage 'licence intel media driver.txt') -Force
Remove-Item -LiteralPath (Join-Path $softwareStage 'version.txt') -Force

foreach ($target in @($catalogueTarget, $softwareTarget)) {
    if (Test-Path -LiteralPath $target) {
        Get-ChildItem -LiteralPath $target -Force | Remove-Item -Recurse -Force
    }
    else {
        New-Item -ItemType Directory -Path $target -Force | Out-Null
    }
}

Copy-Item -Path (Join-Path $catalogueStage '*') -Destination $catalogueTarget -Recurse -Force
Copy-Item -Path (Join-Path $softwareStage '*') -Destination $softwareTarget -Recurse -Force

$catalogueFiles = @(Get-ChildItem -LiteralPath $catalogueTarget -File -Recurse)
$catalogueBytes = ($catalogueFiles | Measure-Object -Property Length -Sum).Sum
Write-Host "Graphics runtime completed: $($catalogueFiles.Count) catalogue file(s), $catalogueBytes byte(s)."
