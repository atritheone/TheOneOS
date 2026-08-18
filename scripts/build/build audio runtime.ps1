[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$Development
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$catalogueTarget = Join-Path $projectRoot 'source\catalogue\audio'
$softwareTarget = Join-Path $projectRoot 'source\software\audio'
$graphicsCatalogueTarget = Join-Path $projectRoot 'source\catalogue\graphics'
$testTarget = Join-Path $projectRoot 'resource\tests\audio'
$videoDecoderSource = Join-Path $projectRoot 'source\native\video\t1_video_decode.c'
$videoMulticallSource = Join-Path $projectRoot 'source\native\video\t1_video_multicall.c'
$nativeVideoRoot = Join-Path $projectRoot 'source\native\video'
$mediaDaemonSource = Join-Path $nativeVideoRoot 't1_media_decoded.c'
$mediaWorkerSource = Join-Path $nativeVideoRoot 't1_media_decode_worker.c'
$mediaTransportSource = Join-Path $nativeVideoRoot 't1_media_decode_transport.c'
$mediaPrivilegeSource = Join-Path $nativeVideoRoot 't1_media_decode_privilege.c'
$mediaPrivilegeHeader = Join-Path $nativeVideoRoot 't1_media_decode_privilege.h'
$mediaSandboxSource = Join-Path $nativeVideoRoot 't1_media_decode_sandbox.c'
$mediaSandboxHeader = Join-Path $nativeVideoRoot 't1_media_decode_sandbox.h'
$mediaProtocolHeader = Join-Path $nativeVideoRoot 't1_media_decode_protocol.h'
$mediaWatchdogHeader = Join-Path $nativeVideoRoot 't1_media_decode_watchdog.h'
$mediaProtocolTest = Join-Path $nativeVideoRoot 'tests\t1_media_protocol_test.c'
$mediaSandboxTest = Join-Path $nativeVideoRoot 'tests\t1_media_sandbox_test.c'
$mediaCapabilitiesSource = Join-Path $projectRoot 'source\settings\media\playback capabilities.json'
$developmentRoot = Join-Path $projectRoot 'development\audio runtime'
$stageRoot = Join-Path $developmentRoot 'stage'
$catalogueStage = Join-Path $stageRoot 'catalogue'
$softwareStage = Join-Path $stageRoot 'software'
$ffmpegVersion = '8.1.2'
$ffmpegSha256 = '464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c'
$ffmpegSigningFingerprint = 'FCF986EA15E6E293A5644F10B4322F04D67658D8'
$libvaVersion = '2.24.1'
$libvaSha256 = 'eec6050b52876f229bd35e9df17cd31a06785e18e6f7990c445b584628483d67'

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

    $translated = ([string]($output | Select-Object -First 1)).Trim()
    if ([string]::IsNullOrWhiteSpace($translated)) {
        throw "WSL returned an empty path for: $WindowsPath"
    }

    return $translated
}

foreach ($path in @($catalogueTarget, $softwareTarget, $graphicsCatalogueTarget, $testTarget, $developmentRoot, $stageRoot, $catalogueStage, $softwareStage, $videoDecoderSource, $videoMulticallSource, $nativeVideoRoot, $mediaDaemonSource, $mediaWorkerSource, $mediaTransportSource, $mediaPrivilegeSource, $mediaPrivilegeHeader, $mediaSandboxSource, $mediaSandboxHeader, $mediaProtocolHeader, $mediaProtocolTest, $mediaSandboxTest, $mediaCapabilitiesSource)) {
    Assert-ProjectPath -Path $path
}

foreach ($requiredSource in @($videoDecoderSource, $videoMulticallSource, $mediaDaemonSource, $mediaWorkerSource, $mediaTransportSource, $mediaPrivilegeSource, $mediaPrivilegeHeader, $mediaSandboxSource, $mediaSandboxHeader, $mediaProtocolHeader, $mediaProtocolTest, $mediaSandboxTest, $mediaCapabilitiesSource)) {
    if (-not (Test-Path -LiteralPath $requiredSource -PathType Leaf)) {
        throw "A native media source was not found: $requiredSource"
    }
}

foreach ($command in @('wsl.exe', 'pwsh')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $command"
    }
}

if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $catalogueStage -Force | Out-Null
New-Item -ItemType Directory -Path $softwareStage -Force | Out-Null
New-Item -ItemType Directory -Path $testTarget -Force | Out-Null

$wslCatalogueStage = ConvertTo-WslPath -WindowsPath $catalogueStage
$wslSoftwareStage = ConvertTo-WslPath -WindowsPath $softwareStage
$wslTestTarget = ConvertTo-WslPath -WindowsPath $testTarget
$wslGraphicsCatalogue = ConvertTo-WslPath -WindowsPath $graphicsCatalogueTarget
$wslVideoDecoderSource = ConvertTo-WslPath -WindowsPath $videoDecoderSource
$wslNativeVideoRoot = ConvertTo-WslPath -WindowsPath $nativeVideoRoot
$wslMediaCapabilitiesSource = ConvertTo-WslPath -WindowsPath $mediaCapabilitiesSource
$cleanValue = if ($Clean) { '1' } else { '0' }
$developmentValue = if ($Development) { '1' } else { '0' }
$buildMode = if ($Development) { 'development' } else { 'release' }

$buildCommand = @'
set -euo pipefail

catalogue_stage=$1
software_stage=$2
test_root=$3
ffmpeg_version=$4
ffmpeg_sha256=$5
signing_fingerprint=$6
clean=$7
video_decoder_source=$8
native_video_root=$9
development=${10}
capability_contract=${11}
cache=/var/tmp/t1os-audio-cache
work=/var/tmp/t1os-audio-work
gpg_home=/var/tmp/t1os-audio-gpg
archive="$cache/ffmpeg-$ffmpeg_version.tar.xz"
signature="$archive.asc"
source_url="https://ffmpeg.org/releases/ffmpeg-$ffmpeg_version.tar.xz"
signature_url="$source_url.asc"
key_url=https://ffmpeg.org/ffmpeg-devel.asc
runtime_runpath='/the one/catalogue/audio:/the one/catalogue/graphics:/the one/catalogue/python'
runtime_interpreter='/the one/catalogue/python/ld-linux-x86-64.so.2'
graphics_build_root='/var/tmp/t1os-graphics-work/install/the one/catalogue/graphics'
graphics_sdk=/var/tmp/t1os-audio-graphics-sdk
graphics_pkgconfig=/var/tmp/t1os-audio-graphics-pkgconfig
media_daemon_source="$native_video_root/t1_media_decoded.c"
video_multicall_source="$native_video_root/t1_video_multicall.c"
media_worker_source="$native_video_root/t1_media_decode_worker.c"
media_transport_source="$native_video_root/t1_media_decode_transport.c"
media_privilege_source="$native_video_root/t1_media_decode_privilege.c"
media_privilege_header="$native_video_root/t1_media_decode_privilege.h"
media_sandbox_source="$native_video_root/t1_media_decode_sandbox.c"
media_sandbox_header="$native_video_root/t1_media_decode_sandbox.h"
media_file_sandbox_source="$native_video_root/t1_media_file_sandbox.c"
media_protocol_header="$native_video_root/t1_media_decode_protocol.h"
media_watchdog_header="$native_video_root/t1_media_decode_watchdog.h"
media_protocol_test="$native_video_root/tests/t1_media_protocol_test.c"
media_sandbox_test="$native_video_root/tests/t1_media_sandbox_test.c"

for native_source in \
    "$video_decoder_source" \
    "$video_multicall_source" \
    "$media_daemon_source" \
    "$media_worker_source" \
    "$media_transport_source" \
    "$media_privilege_source" \
    "$media_privilege_header" \
    "$media_sandbox_source" \
    "$media_sandbox_header" \
    "$media_file_sandbox_source" \
    "$media_protocol_header" \
    "$media_watchdog_header" \
    "$media_protocol_test" \
    "$media_sandbox_test"; do
    test -f "$native_source"
done

require_command() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "Required WSL build command not found: $1" >&2
        exit 127
    }
}

for command_name in curl gcc make tar xz gpg sha256sum readelf patchelf strip python3 nasm pkg-config; do
    require_command "$command_name"
done

for required_graphics_file in \
    "$graphics_build_root/pkgconfig/libdrm.pc" \
    "$graphics_build_root/pkgconfig/libva.pc" \
    "$graphics_build_root/pkgconfig/libva-drm.pc"; do
    if [ ! -f "$required_graphics_file" ]; then
        echo "The graphics runtime must be built before the media runtime: $required_graphics_file" >&2
        exit 1
    fi
done

case "$graphics_sdk" in
    /var/tmp/t1os-audio-graphics-sdk) rm -f -- "$graphics_sdk" ;;
    *) echo "Refusing to replace unexpected graphics SDK link: $graphics_sdk" >&2; exit 1 ;;
esac
case "$graphics_pkgconfig" in
    /var/tmp/t1os-audio-graphics-pkgconfig) rm -rf -- "$graphics_pkgconfig" ;;
    *) echo "Refusing to replace unexpected pkg-config path: $graphics_pkgconfig" >&2; exit 1 ;;
esac
ln -s -- "$graphics_build_root" "$graphics_sdk"
mkdir -p "$graphics_pkgconfig"
for pc in libdrm libva libva-drm; do
    sed "s|^prefix=.*|prefix=$graphics_sdk|" \
        "$graphics_build_root/pkgconfig/$pc.pc" > "$graphics_pkgconfig/$pc.pc"
done

export PKG_CONFIG_PATH="$graphics_pkgconfig"
unset PKG_CONFIG_SYSROOT_DIR
export LD_LIBRARY_PATH="$graphics_sdk"

mkdir -p "$cache"

if [ "$clean" = 1 ]; then
    case "$work" in
        /var/tmp/t1os-audio-work) rm -rf -- "$work" ;;
        *) echo "Refusing to clean unexpected audio work path: $work" >&2; exit 1 ;;
    esac
fi

if [ ! -f "$archive" ]; then
    curl -fL --retry 5 --retry-delay 2 -o "$archive.part" "$source_url"
    mv -- "$archive.part" "$archive"
fi

if [ ! -f "$signature" ]; then
    curl -fL --retry 5 --retry-delay 2 -o "$signature.part" "$signature_url"
    mv -- "$signature.part" "$signature"
fi

printf '%s  %s\n' "$ffmpeg_sha256" "$archive" | sha256sum -c -

case "$gpg_home" in
    /var/tmp/t1os-audio-gpg) rm -rf -- "$gpg_home" ;;
    *) echo "Refusing to replace unexpected GPG path: $gpg_home" >&2; exit 1 ;;
esac

mkdir -m 700 "$gpg_home"
if [ ! -f "$cache/ffmpeg-devel.asc" ]; then
    curl -fL --retry 5 --retry-delay 2 -o "$cache/ffmpeg-devel.asc.part" "$key_url"
    mv -- "$cache/ffmpeg-devel.asc.part" "$cache/ffmpeg-devel.asc"
fi
GNUPGHOME="$gpg_home" gpg --batch --import "$cache/ffmpeg-devel.asc" >/dev/null 2>&1
fingerprints=$(GNUPGHOME="$gpg_home" gpg --batch --with-colons --fingerprint | awk -F: '$1 == "fpr" {print $10}')
printf '%s\n' "$fingerprints" | grep -Fx "$signing_fingerprint" >/dev/null
GNUPGHOME="$gpg_home" gpg --batch --verify "$signature" "$archive"

case "$work" in
    /var/tmp/t1os-audio-work) rm -rf -- "$work" ;;
    *) echo "Refusing to replace unexpected audio work path: $work" >&2; exit 1 ;;
esac

mkdir -p "$work/source" "$work/install" "$catalogue_stage" "$software_stage"
tar -xf "$archive" --strip-components=1 -C "$work/source"
cd "$work/source"

configure_args=(
    --prefix=/usr/local/t1os-audio
    --enable-shared
    --disable-static
    --enable-pic
    --disable-autodetect
    --disable-doc
    --disable-programs
    --enable-ffmpeg
    --enable-ffprobe
    --disable-avdevice
    --disable-network
    --disable-indevs
    --disable-outdevs
    --enable-vaapi
    --disable-encoders
    --enable-encoder=pcm_s16le
    --enable-encoder=rawvideo
    --disable-muxers
    --enable-muxer=pcm_s16le
    --enable-muxer=rawvideo
    --disable-protocols
    --enable-protocol=file
    --enable-protocol=pipe
    --disable-gpl
    --disable-nonfree
    --extra-cflags=-fstack-protector-strong\ -fstack-clash-protection\ -fcf-protection=full\ -fno-plt\ -fno-common\ -D_FORTIFY_SOURCE=3\ -Wformat\ -Wformat-security\ -Werror=format-security
    --extra-ldflags=-Wl,-z,relro,-z,now,-z,noexecstack,--as-needed
    --extra-ldexeflags=-pie
)

if [ "$development" = 1 ]; then
    configure_args+=(
        --enable-debug=3
        --disable-stripping
    )
else
    configure_args+=(--disable-debug)
fi

./configure "${configure_args[@]}"
make -j"$(nproc)"
make DESTDIR="$work/install" install

prefix="$work/install/usr/local/t1os-audio"
ffmpeg="$prefix/bin/ffmpeg"
ffprobe="$prefix/bin/ffprobe"
libdir="$prefix/lib"
test -x "$ffmpeg"
test -x "$ffprobe"

LD_LIBRARY_PATH="$libdir:$graphics_sdk" \
    "$ffmpeg" -hide_banner -buildconf > "$software_stage/buildconf.txt"

if grep -F -- '--disable-x86asm' "$software_stage/buildconf.txt" >/dev/null; then
    echo 'FFmpeg was built without the required x86 assembly optimizations.' >&2
    exit 1
fi

cp -- "$ffmpeg" "$software_stage/ffmpeg"
cp -- "$ffprobe" "$software_stage/ffprobe"

native_cflags=(
    -std=c11
    -Wall
    -Wextra
    -Werror
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
native_ldflags=(-Wl,-z,relro,-z,now,-z,noexecstack,--as-needed)
if [ "$development" = 1 ]; then
    native_cflags+=(
        -O0
        -g3
        -fno-omit-frame-pointer
        -DT1_MEDIA_DEVELOPMENT=1
    )
else
    native_cflags+=(-O2 -DNDEBUG)
fi

native_objects="$work/native-objects"
mkdir -p "$native_objects"
gcc "${native_cflags[@]}" \
    -fPIC \
    -shared \
    "${native_ldflags[@]}" \
    -Wl,-soname,libt1-media-file-sandbox.so.1 \
    "$media_file_sandbox_source" \
    "$media_sandbox_source" \
    -o "$native_objects/libt1-media-file-sandbox.so.1"
cp -- \
    "$native_objects/libt1-media-file-sandbox.so.1" \
    "$catalogue_stage/libt1-media-file-sandbox.so.1"
gcc "${native_cflags[@]}" \
    -fPIE \
    -I"$prefix/include" \
    -I"$graphics_sdk/include" \
    -Dmain=t1_video_player_main \
    -c "$video_decoder_source" \
    -o "$native_objects/t1_video_player.o"
gcc "${native_cflags[@]}" \
    -fPIE \
    -I"$prefix/include" \
    -I"$graphics_sdk/include" \
    -Dmain=t1_media_decode_worker_entry \
    -c "$media_worker_source" \
    -o "$native_objects/t1_media_decode_worker.o"
gcc "${native_cflags[@]}" \
    -fPIE \
    -c "$media_transport_source" \
    -o "$native_objects/t1_media_decode_transport.o"
gcc "${native_cflags[@]}" \
    -fPIE \
    -c "$media_privilege_source" \
    -o "$native_objects/t1_media_decode_privilege.o"
gcc "${native_cflags[@]}" \
    -fPIE \
    -c "$media_sandbox_source" \
    -o "$native_objects/t1_media_decode_sandbox.o"
gcc "${native_cflags[@]}" \
    -fPIE \
    -c "$video_multicall_source" \
    -o "$native_objects/t1_video_multicall.o"
gcc "${native_cflags[@]}" \
    -fPIE \
    -L"$libdir" \
    -L"$graphics_sdk" \
    "${native_ldflags[@]}" \
    -pie \
    -Wl,-rpath-link,"$libdir" \
    -o "$software_stage/t1-video-decode" \
    "$native_objects/t1_video_multicall.o" \
    "$native_objects/t1_video_player.o" \
    "$native_objects/t1_media_decode_worker.o" \
    "$native_objects/t1_media_decode_transport.o" \
    "$native_objects/t1_media_decode_privilege.o" \
    "$native_objects/t1_media_decode_sandbox.o" \
    -lavformat -lavcodec -lavutil -lva -lva-drm

gcc "${native_cflags[@]}" \
    -fPIE \
    "${native_ldflags[@]}" \
    -pie \
    -o "$software_stage/t1-media-decoderd" \
    "$media_daemon_source" \
    "$media_transport_source" \
    "$media_privilege_source"

gcc "${native_cflags[@]}" \
    -fPIE \
    "${native_ldflags[@]}" \
    -pie \
    -o "$work/t1-media-protocol-test" \
    "$media_protocol_test" \
    "$media_transport_source" \
    "$media_privilege_source"
gcc "${native_cflags[@]}" \
    -fPIE \
    "${native_ldflags[@]}" \
    -pie \
    -pthread \
    -o "$work/t1-media-sandbox-test" \
    "$media_sandbox_test" \
    "$media_sandbox_source" \
    "$media_privilege_source"

set +e
LD_LIBRARY_PATH="$libdir:$graphics_sdk" \
    "$software_stage/t1-video-decode" \
    --device /nonexistent --probe \
    > /dev/null 2> "$work/t1-video-player-dispatch.log"
player_dispatch_status=$?
set -e
if [ "$player_dispatch_status" -ne 2 ] ||
   ! grep -F 'VAAPI device creation failed:' \
       "$work/t1-video-player-dispatch.log" >/dev/null; then
    echo 'The t1-video-decode multicall binary did not preserve Player probe dispatch.' >&2
    exit 1
fi

LD_LIBRARY_PATH="$libdir:$graphics_sdk" \
    "$software_stage/t1-video-decode" \
    --file-sandbox-self-test "$work/source/configure" \
    | grep -F 'input=read-only unrelated-files=denied' >/dev/null

LD_LIBRARY_PATH="$libdir:$graphics_sdk" \
    "$work/t1-media-protocol-test" \
    "$software_stage/t1-video-decode"
LD_LIBRARY_PATH="$libdir:$graphics_sdk" \
    "$software_stage/t1-video-decode" \
    --t1md-worker --backpressure-self-test
LD_LIBRARY_PATH="$libdir:$graphics_sdk" \
    "$software_stage/t1-video-decode" \
    --t1md-worker --capability-contract-self-test
"$work/t1-media-sandbox-test"
"$software_stage/t1-media-decoderd" --self-test
"$software_stage/t1-media-decoderd" \
    --fd-sanitization-self-test \
    --self-test-null-device /dev/null
"$software_stage/t1-media-decoderd" \
    --watchdog-self-test
"$software_stage/t1-media-decoderd" \
    --watchdog-state-self-test \
    --self-test-state "$work/t1md-watchdog-state.json"
"$software_stage/t1-media-decoderd" \
    --privilege-self-test --worker-uid 65534 --worker-gid 1000
"$software_stage/t1-media-decoderd" \
    --parent-death-self-test --worker-uid 65534 --worker-gid 1000
probe_security_log="$work/t1-media-probe-security.log"
if LD_LIBRARY_PATH="$libdir:$graphics_sdk" \
   "$software_stage/t1-media-decoderd" \
    --socket /tmp/t1md-build-probe.sock \
    --state none \
    --device /nonexistent \
    --worker "$software_stage/t1-video-decode" \
    --worker-uid 65534 \
    --worker-gid 1000 \
    --socket-uid 1000 \
    --socket-gid 1000 \
    --allow-uid 1000 \
    --max-sessions 1 \
    --max-connections 1 \
    --hardware-probe-self-test \
    --self-test-null-device /dev/null \
    --debug \
    > /dev/null 2> "$probe_security_log"; then
    echo 'The daemon unexpectedly passed a nonexistent render-node probe.' >&2
    exit 1
fi
grep -F 'T1_MEDIA_WORKER probe-failed device=/nonexistent' "$probe_security_log" >/dev/null
grep -E 'T1_MEDIA_WORKER sandbox=ready landlock_abi=[5-9][0-9]* .*seccomp=filter seccomp_tsync=1 worker_uid=65534 worker_gid=1000' \
    "$probe_security_log" >/dev/null
if grep -F 'refused unsafe identity' "$probe_security_log" >/dev/null; then
    echo 'The daemon probe worker did not enter its measured identity.' >&2
    exit 1
fi

T1OS_MEDIA_SANDBOX_INPUT=/etc/hosts \
T1OS_MEDIA_SANDBOX_REQUIRED=1 \
LD_PRELOAD="$native_objects/libt1-media-file-sandbox.so.1" \
    /usr/bin/true

protocol_header_sha256=$(sha256sum "$media_protocol_header" | awk '{print $1}')
watchdog_header_sha256=$(sha256sum "$media_watchdog_header" | awk '{print $1}')
cp -- "$work/source/COPYING.LGPLv2.1" "$software_stage/licence LGPL-2.1.txt"
cp -- "$work/source/LICENSE.md" "$software_stage/licence ffmpeg.txt"
printf '%s\n' "$ffmpeg_version" > "$software_stage/version.txt"
cat > "$software_stage/notice.txt" <<EOF
T1OS media uses FFmpeg $ffmpeg_version, built without GPL or nonfree components.
Source: $source_url
Source SHA-256: $ffmpeg_sha256
Build configuration: buildconf.txt
T1MD protocol version: 1
T1MD authoritative header SHA-256: $protocol_header_sha256
T1MD watchdog header SHA-256: $watchdog_header_sha256
FFmpeg is licensed under the GNU Lesser General Public License version 2.1 or later.
The exact corresponding source archive and signature must accompany the distributed T1OS release.
EOF

for library in "$libdir"/*.so.*; do
    [ -f "$library" ] || continue
    soname=$(readelf -d "$library" | sed -n 's/.*(SONAME).*\[\([^]]*\)\].*/\1/p')
    [ -n "$soname" ] || continue
    cp -L -- "$library" "$catalogue_stage/$soname"
done

if [ "$development" != 1 ]; then
    strip --strip-unneeded "$software_stage/ffmpeg"
    strip --strip-unneeded "$software_stage/ffprobe"
    strip --strip-unneeded "$software_stage/t1-video-decode"
    strip --strip-unneeded "$software_stage/t1-media-decoderd"
fi
for library in "$catalogue_stage"/*.so.*; do
    if [ "$development" != 1 ]; then
        strip --strip-unneeded "$library"
    fi
    patchelf --set-rpath "$runtime_runpath" "$library"
done
patchelf --set-interpreter "$runtime_interpreter" "$software_stage/ffmpeg"
patchelf --set-rpath "$runtime_runpath" "$software_stage/ffmpeg"
patchelf --set-interpreter "$runtime_interpreter" "$software_stage/ffprobe"
patchelf --set-rpath "$runtime_runpath" "$software_stage/ffprobe"
patchelf --set-interpreter "$runtime_interpreter" "$software_stage/t1-video-decode"
patchelf --set-rpath "$runtime_runpath" "$software_stage/t1-video-decode"
patchelf --set-interpreter "$runtime_interpreter" "$software_stage/t1-media-decoderd"
patchelf --set-rpath "$runtime_runpath" "$software_stage/t1-media-decoderd"

# The deployable software tier is deliberately binary-only apart from its
# machine-readable manifest.  Remove build notices from the staging directory
# before hashing so every manifest entry corresponds to a shipped artifact.
for staged_file in "$software_stage"/*; do
    [ -f "$staged_file" ] || continue
    case "$(basename "$staged_file")" in
        ffmpeg|ffprobe|t1-video-decode|t1-media-decoderd) ;;
        *) rm -f -- "$staged_file" ;;
    esac
done

export T1OS_AUDIO_CATALOGUE_STAGE="$catalogue_stage"
export T1OS_AUDIO_SOFTWARE_STAGE="$software_stage"
export T1OS_AUDIO_VERSION="$ffmpeg_version"
export T1OS_AUDIO_SHA256="$ffmpeg_sha256"
export T1OS_AUDIO_SOURCE_URL="$source_url"
export T1OS_AUDIO_RUNPATH="$runtime_runpath"
export T1OS_AUDIO_INTERPRETER="$runtime_interpreter"
export T1OS_AUDIO_BUILD_MODE=$(
    if [ "$development" = 1 ]; then
        printf development
    else
        printf release
    fi
)
export T1OS_MEDIA_PROTOCOL_HEADER_SHA256="$protocol_header_sha256"
export T1OS_MEDIA_WATCHDOG_HEADER_SHA256="$watchdog_header_sha256"

loader=/lib64/ld-linux-x86-64.so.2
if [ ! -x "$loader" ]; then
    loader=/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2
fi
test -x "$loader"
loader_path="$catalogue_stage:$graphics_build_root"
"$loader" --library-path "$loader_path" "$software_stage/ffmpeg" -hide_banner -demuxers > "$work/demuxers.txt"
"$loader" --library-path "$loader_path" "$software_stage/ffmpeg" -hide_banner -decoders > "$work/decoders.txt"
"$loader" --library-path "$loader_path" "$software_stage/ffmpeg" -hide_banner -encoders > "$work/encoders.txt"
"$loader" --library-path "$loader_path" "$software_stage/ffmpeg" -hide_banner -muxers > "$work/muxers.txt"
"$loader" --library-path "$loader_path" "$software_stage/ffmpeg" -hide_banner -filters > "$work/filters.txt"
"$loader" --library-path "$loader_path" "$software_stage/ffmpeg" -hide_banner -hwaccels > "$work/hwaccels.txt"
export T1OS_AUDIO_CAPABILITY_CONTRACT="$capability_contract"
export T1OS_AUDIO_CAPABILITY_ROOT="$work"

python3 - <<'PY'
from pathlib import Path
import hashlib
import json
import os
import platform
import re
import subprocess

catalogue = Path(os.environ['T1OS_AUDIO_CATALOGUE_STAGE'])
software = Path(os.environ['T1OS_AUDIO_SOFTWARE_STAGE'])
runpath = os.environ['T1OS_AUDIO_RUNPATH']
interpreter = os.environ['T1OS_AUDIO_INTERPRETER']
base = {
    'ld-linux-x86-64.so.2',
    'libc.so.6',
    'libdl.so.2',
    'libm.so.6',
    'libpthread.so.0',
    'librt.so.1',
    'libdrm.so.2',
    'libva.so.2',
    'libva-drm.so.2',
}

contract_path = Path(os.environ['T1OS_AUDIO_CAPABILITY_CONTRACT'])
capability_root = Path(os.environ['T1OS_AUDIO_CAPABILITY_ROOT'])
contract = json.loads(contract_path.read_text(encoding='utf-8'))
if contract.get('format') != 1:
    raise SystemExit('media playback capability contract format is not supported')

def lines(name):
    return (capability_root / name).read_text(
        encoding='utf-8', errors='replace'
    ).splitlines()

def decoders(kind):
    prefix = {'video': 'V', 'audio': 'A', 'subtitle': 'S'}[kind]
    result = set()
    for line in lines('decoders.txt'):
        match = re.match(r'^\s*([VAS])[A-Z.]{5}\s+(\S+)', line)
        if match and match.group(1) == prefix:
            result.add(match.group(2))
    return sorted(result)

def namedlisting(name, pattern):
    result = set()
    for line in lines(name):
        match = re.match(pattern, line)
        if not match:
            continue
        result.update(value for value in match.group(1).split(',') if value)
    return sorted(result)

video_decoders = decoders('video')
audio_decoders = decoders('audio')
subtitle_decoders = decoders('subtitle')
demuxers = namedlisting('demuxers.txt', r'^\s*D\s+(\S+)')
filters = namedlisting('filters.txt', r'^\s*[TSC.]{2,3}\s+(\S+)')
hwaccels = sorted({
    line.strip()
    for line in lines('hwaccels.txt')[1:]
    if line.strip() and 'Hardware acceleration methods' not in line
})

available = {
    'guaranteed_video_decoders': set(video_decoders),
    'compatibility_video_decoders': set(video_decoders),
    'guaranteed_audio_decoders': set(audio_decoders),
    'guaranteed_subtitle_codecs': set(subtitle_decoders),
    'required_demuxers': set(demuxers),
    'required_filters': set(filters),
    'required_hwaccels': set(hwaccels),
}
missing_capabilities = {
    key: sorted(set(contract.get(key, ())) - values)
    for key, values in available.items()
    if set(contract.get(key, ())) - values
}
if missing_capabilities:
    raise SystemExit(json.dumps({
        'missing_media_capabilities': missing_capabilities,
    }, indent=2, sort_keys=True))

def inspect(path):
    header = subprocess.run(
        ['readelf', '-h', str(path)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout
    dynamic = subprocess.run(
        ['readelf', '-dW', str(path)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout
    program = subprocess.run(
        ['readelf', '-lW', str(path)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout
    stack_lines = [line for line in program.splitlines() if 'GNU_STACK' in line]
    return {
        'needed': re.findall(r'\(NEEDED\).*?\[([^]]+)\]', dynamic),
        'soname': (re.findall(r'\(SONAME\).*?\[([^]]+)\]', dynamic) or [None])[0],
        'runpath': (re.findall(r'\(RUNPATH\).*?\[([^]]+)\]', dynamic) or [None])[0],
        'interpreter': (re.findall(r'Requesting program interpreter:\s*([^]]+)', program) or [None])[0],
        'hardening': {
            'position_independent': bool(re.search(r'Type:\s+DYN\b', header)),
            'relro': 'GNU_RELRO' in program,
            'bind_now': 'BIND_NOW' in dynamic,
            'non_executable_stack': bool(stack_lines) and all(
                'RWE' not in line for line in stack_lines
            ),
        },
    }

def record(area, path, root):
    data = path.read_bytes()
    return {
        'area': area,
        'path': path.relative_to(root).as_posix(),
        'size': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        **inspect(path),
    }

catalogue_files = [record('catalogue', path, catalogue) for path in sorted(catalogue.iterdir()) if path.is_file()]
software_files = [record('software', path, software) for path in sorted(software.iterdir()) if path.is_file() and path.name != 'manifest.json']
provided = {item['path'] for item in catalogue_files}
binary_files = [item for item in catalogue_files + software_files if item['needed']]
unresolved = sorted({needed for item in binary_files for needed in item['needed'] if needed not in provided and needed not in base})
invalid_runpaths = sorted(f"{item['area']}/{item['path']}" for item in binary_files if item['runpath'] != runpath)
programs = [
    item for item in software_files
    if item['path'] in (
        'ffmpeg',
        'ffprobe',
        't1-video-decode',
        't1-media-decoderd',
    )
]
invalid_interpreter = sorted(item['path'] for item in programs if item['interpreter'] != interpreter)
invalid_catalogue = sorted(path.name for path in catalogue.iterdir() if not re.fullmatch(r'lib[^/]+\.so\.\d+', path.name))
symlinks = sorted(str(path) for root in (catalogue, software) for path in root.rglob('*') if path.is_symlink())
hardening_failures = sorted(
    f"{item['area']}/{item['path']}"
    for item in catalogue_files + software_files
    if not all(item['hardening'].values())
)

if (unresolved or invalid_runpaths or invalid_interpreter or invalid_catalogue
        or symlinks or hardening_failures):
    raise SystemExit(json.dumps({
        'unresolved': unresolved,
        'invalid_runpaths': invalid_runpaths,
        'invalid_interpreter': invalid_interpreter,
        'invalid_catalogue': invalid_catalogue,
        'symlinks': symlinks,
        'hardening_failures': hardening_failures,
    }, indent=2))

manifest = {
    'format': 1,
    'state': 'ready',
    'architecture': 'x86_64',
    'component': 'T1OS media decoder runtime',
    'build_mode': os.environ['T1OS_AUDIO_BUILD_MODE'],
    'source': {
        'name': 'FFmpeg',
        'version': os.environ['T1OS_AUDIO_VERSION'],
        'url': os.environ['T1OS_AUDIO_SOURCE_URL'],
        'sha256': os.environ['T1OS_AUDIO_SHA256'],
    },
    'runtime': {
        'executable': '/the one/software/audio/ffmpeg',
        'probe': '/the one/software/audio/ffprobe',
        'video_decoder': '/the one/software/audio/t1-video-decode',
        'media_decode_service': '/the one/software/audio/t1-media-decoderd',
        'media_decode_worker': '/the one/software/audio/t1-video-decode',
        'media_decode_worker_mode': '--t1md-worker',
        'media_decode_protocol': {
            'name': 'T1MD',
            'version': 1,
            'transport': 'AF_UNIX/SOCK_SEQPACKET',
            'header_sha256': os.environ['T1OS_MEDIA_PROTOCOL_HEADER_SHA256'],
            'maximum_decode_requests': 1,
            'maximum_in_flight_frames': 16,
            'backpressure_feature_bit': 64,
            'linear_memory_output_feature_bit': 128,
            'backpressure_message_type': 15,
            'backpressure_timeout_ms': 0,
            'backpressure_reset_terminal': 'RESET_DONE-without-EXIT',
        },
        'media_decode_surface_export': {
            'mode': 'separate-layers',
            'object_layout': 'one-object-per-plane',
            'modifier_scope': 'per-object',
            'modifier_layout': 'natural-per-plane',
            'composed_fallback': False,
            'chroma_subsampling': '4:2:0',
            'bit_depths': [8, 10],
            'output_formats': ['NV12', 'P010'],
        },
        'media_decode_watchdog': {
            'format': 1,
            'policy_id': 't1md-watchdog-v1',
            'header_sha256': os.environ[
                'T1OS_MEDIA_WATCHDOG_HEADER_SHA256'
            ],
            'authority': 'supervisor',
            'clock': 'CLOCK_MONOTONIC',
            'timeout_action': 'SIGKILL',
            'idle_timeout_ms': 0,
            'starting_timeout_ms': 15000,
            'hello_timeout_ms': 30000,
            'create_timeout_ms': 15000,
            'decode_timeout_ms': 15000,
            'flush_timeout_ms': 15000,
            'reset_timeout_ms': 10000,
            'release_timeout_ms': 6000,
            'destroy_timeout_ms': 10000,
            'cleanup_timeout_ms': 10000,
            'exiting_timeout_ms': 1000,
        },
        'media_decode_sandbox': {
            'required': True,
            'worker_uid': 65534,
            'worker_gid': 1000,
            'landlock_minimum_abi': 5,
            'landlock_filesystem': (
                'deny-by-default-all-through-ioctl-dev'
            ),
            'landlock_network': 'deny-tcp-bind-connect',
            'runtime_filesystem': 'read-only',
            'device_filesystem': 'read-write-ioctl',
            'seccomp': 'filter',
            'seccomp_tsync': True,
            'network_creation': 'denied',
            'process_creation': 'threads-only',
            'session_stdin': 'null',
            'session_stdout': 'null',
            'session_stderr': (
                'bounded-nonblocking-relay'
                if os.environ['T1OS_AUDIO_BUILD_MODE']
                == 'development'
                else 'null'
            ),
            'session_diagnostic_limit': (
                1048576
                if os.environ['T1OS_AUDIO_BUILD_MODE']
                == 'development'
                else 0
            ),
            'session_exec_visible_fds': 6,
            'session_required_ipc_fds': 3,
            'session_unexpected_inherited_fds': 0,
            'probe_diagnostic_limit': 65536,
            'rlimit_core': 0,
            'rlimit_fsize': 67108864,
            'rlimit_nofile': 256,
            'rlimit_nproc': 256,
            'local_file_native': {
                'activation': 'before-container-open',
                'filesystem': 'exact-input-read-only',
                'seccomp': 'filter-tsync',
                'network_creation': 'denied',
                'process_creation': 'threads-only',
            },
            'local_file_software': {
                'activation': 'pre-main-constructor',
                'library': (
                    '/the one/catalogue/audio/'
                    'libt1-media-file-sandbox.so.1'
                ),
                'filesystem': 'exact-input-read-only',
                'seccomp': 'filter-tsync',
                'network_creation': 'denied',
                'process_creation': 'threads-only',
            },
        },
        'runpath': runpath,
        'interpreter': interpreter,
        'library_tier': '/the one/catalogue/audio',
        'native_hardening_required': [
            'PIE/PIC', 'full RELRO', 'BIND_NOW', 'non-executable stack',
            'stack protector', 'FORTIFY_SOURCE=3', 'stack clash protection',
            'control-flow protection',
        ],
    },
    'capabilities': {
        'format': 1,
        'policy': contract.get('policy', ''),
        'scope': contract.get('scope', ''),
        'video_decoders': video_decoders,
        'audio_decoders': audio_decoders,
        'subtitle_decoders': subtitle_decoders,
        'demuxers': demuxers,
        'filters': filters,
        'hardware_accelerators': hwaccels,
        'video_extensions': sorted(contract.get('video_extensions', ())),
        'audio_extensions': sorted(contract.get('audio_extensions', ())),
        'guaranteed_video_decoders': sorted(
            contract.get('guaranteed_video_decoders', ())
        ),
        'compatibility_video_decoders': sorted(
            contract.get('compatibility_video_decoders', ())
        ),
        'guaranteed_audio_decoders': sorted(
            contract.get('guaranteed_audio_decoders', ())
        ),
        'guaranteed_subtitle_codecs': sorted(
            contract.get('guaranteed_subtitle_codecs', ())
        ),
        'required_demuxers': sorted(contract.get('required_demuxers', ())),
        'required_filters': sorted(contract.get('required_filters', ())),
        'required_hwaccels': sorted(contract.get('required_hwaccels', ())),
        'out_of_scope': list(contract.get('out_of_scope', ())),
    },
    'build_host': platform.platform(),
    'files': catalogue_files + software_files,
    'verification': {
        'unresolved_dependencies': [],
        'invalid_runpaths': [],
        'invalid_catalogue_files': [],
        'symlinks': [],
        'missing_capabilities': {},
    },
}

(software / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
PY

"$loader" --library-path "$loader_path" "$software_stage/ffmpeg" -hide_banner -version >/dev/null
"$loader" --library-path "$loader_path" "$software_stage/ffprobe" -hide_banner -version >/dev/null
"$loader" --library-path "$loader_path" "$software_stage/t1-video-decode" --device /nonexistent --probe >/dev/null 2>&1 && {
    echo 'The native video decoder unexpectedly opened a nonexistent render node.' >&2
    exit 1
}
"$loader" --library-path "$loader_path" "$software_stage/t1-video-decode" \
    --t1md-worker --backpressure-self-test >/dev/null
"$loader" --library-path "$loader_path" "$software_stage/t1-video-decode" \
    --t1md-worker --capability-contract-self-test >/dev/null
"$loader" --library-path "$loader_path" "$software_stage/t1-media-decoderd" --self-test >/dev/null
"$loader" --library-path "$loader_path" "$software_stage/t1-media-decoderd" \
    --fd-sanitization-self-test \
    --self-test-null-device /dev/null \
    --self-test-loader "$loader" \
    --self-test-library-path "$loader_path" >/dev/null
"$loader" --library-path "$loader_path" "$software_stage/t1-media-decoderd" \
    --watchdog-self-test >/dev/null
"$loader" --library-path "$loader_path" "$software_stage/t1-media-decoderd" \
    --watchdog-state-self-test \
    --self-test-state "$work/t1md-watchdog-state-loader.json" >/dev/null
"$loader" --library-path "$loader_path" "$software_stage/t1-media-decoderd" \
    --privilege-self-test --worker-uid 65534 --worker-gid 1000 >/dev/null
"$loader" --library-path "$loader_path" "$software_stage/t1-media-decoderd" \
    --parent-death-self-test --worker-uid 65534 --worker-gid 1000 >/dev/null
set +e
"$loader" --library-path "$loader_path" "$software_stage/t1-video-decode" \
    --t1md-worker --probe --device /nonexistent --maximum-sessions 1 \
    --expected-uid 65534 --expected-gid 1000 --expected-parent "$$" \
    >/dev/null 2>&1
unsafe_worker_status=$?
set -e
if [ "$unsafe_worker_status" -ne 77 ]; then
    echo "The media decode worker did not refuse unsafe root execution (status $unsafe_worker_status)." >&2
    exit 1
fi
grep -Eq '(^|[[:space:]])mp3([[:space:]]|$)' "$work/demuxers.txt"
grep -Eq '(^|[[:space:]])flac([[:space:]]|$)' "$work/decoders.txt"
for demuxer in mov matroska webm avi; do
    grep -Eq "(^|[[:space:],])$demuxer([[:space:],]|$)" "$work/demuxers.txt"
done
for decoder in h264 hevc vp8 vp9 av1 mpeg4 aac opus vorbis; do
    grep -Eq "(^|[[:space:]])$decoder([[:space:]]|$)" "$work/decoders.txt"
done
grep -Eq '(^|[[:space:]])rawvideo([[:space:]]|$)' "$work/encoders.txt"
grep -Eq '(^|[[:space:]])rawvideo([[:space:]]|$)' "$work/muxers.txt"
for filter in format fps scale scale_vaapi hwdownload setpts showinfo; do
    grep -Eq "(^|[[:space:]])$filter([[:space:]]|$)" "$work/filters.txt"
done
grep -Eq '(^|[[:space:]])vaapi([[:space:]]|$)' "$work/hwaccels.txt"

for fixture in sample.mp3 sample.flac; do
    if [ -f "$test_root/$fixture" ]; then
        "$loader" --library-path "$loader_path" "$software_stage/ffmpeg" \
            -hide_banner -loglevel error -nostdin -i "$test_root/$fixture" \
            -map 0:a:0 -vn -sn -dn -ac 2 -ar 48000 -c:a pcm_s16le -f s16le \
            "$work/$fixture.pcm"
        test -s "$work/$fixture.pcm"
    fi
done

printf 'Media catalogue files: '
find "$catalogue_stage" -maxdepth 1 -type f | wc -l
printf 'Media software files: '
find "$software_stage" -maxdepth 1 -type f | wc -l
du -sh "$catalogue_stage" "$software_stage"
'@

Write-Host "Building FFmpeg $ffmpegVersion for the T1OS media runtime ($buildMode)..."
$unixBuildCommand = $buildCommand.Replace("`r", '')
$buildStart = [System.Diagnostics.ProcessStartInfo]::new()
$buildStart.FileName = 'wsl.exe'
$buildStart.UseShellExecute = $false
$buildStart.RedirectStandardInput = $true
foreach ($argument in @(
    '-u', 'root', '--exec', 'bash', '-s', '--',
    $wslCatalogueStage, $wslSoftwareStage, $wslTestTarget,
    $ffmpegVersion, $ffmpegSha256, $ffmpegSigningFingerprint,
    $cleanValue, $wslVideoDecoderSource, $wslNativeVideoRoot,
    $developmentValue, $wslMediaCapabilitiesSource
)) {
    $buildStart.ArgumentList.Add([string]$argument)
}
$buildProcess = [System.Diagnostics.Process]::Start($buildStart)
$buildProcess.StandardInput.Write($unixBuildCommand)
$buildProcess.StandardInput.Close()
$buildProcess.WaitForExit()
$buildExitCode = $buildProcess.ExitCode
$buildProcess.Dispose()
if ($buildExitCode -ne 0) {
    throw "The T1OS media runtime build failed (exit code $buildExitCode)."
}

$manifestStage = Join-Path $softwareStage 'manifest.json'
if (-not (Test-Path -LiteralPath $manifestStage -PathType Leaf)) {
    throw "The staged audio manifest was not generated: $manifestStage"
}

$manifest = Get-Content -LiteralPath $manifestStage -Raw | ConvertFrom-Json
if ($manifest.state -ne 'ready' -or $manifest.source.version -ne $ffmpegVersion) {
    throw 'The staged audio manifest does not match the pinned FFmpeg build.'
}
$capabilityManifest = $manifest.capabilities
$capabilityContract = Get-Content -Raw -LiteralPath $mediaCapabilitiesSource | ConvertFrom-Json
$capabilityPairs = @(
    @('guaranteed_video_decoders', 'video_decoders'),
    @('compatibility_video_decoders', 'video_decoders'),
    @('guaranteed_audio_decoders', 'audio_decoders'),
    @('guaranteed_subtitle_codecs', 'subtitle_decoders'),
    @('required_demuxers', 'demuxers'),
    @('required_filters', 'filters'),
    @('required_hwaccels', 'hardware_accelerators')
)
if (
    $capabilityManifest.format -ne 1 -or
    $capabilityManifest.policy -ne $capabilityContract.policy -or
    $capabilityManifest.scope -ne $capabilityContract.scope -or
    @($manifest.verification.missing_capabilities.PSObject.Properties).Count -ne 0
) {
    throw 'The staged media capability attestation is invalid.'
}
foreach ($pair in $capabilityPairs) {
    $promised = @($capabilityContract.($pair[0]))
    $available = @($capabilityManifest.($pair[1]))
    $missing = @($promised | Where-Object { $_ -notin $available })
    if ($missing) {
        throw "The staged runtime is missing $($pair[0]): $($missing -join ', ')"
    }
}
$protocolManifest = $manifest.runtime.media_decode_protocol
$surfaceExportManifest = $manifest.runtime.media_decode_surface_export
$watchdogManifest = $manifest.runtime.media_decode_watchdog
$sandboxManifest = $manifest.runtime.media_decode_sandbox
$expectedProtocolHeaderSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $mediaProtocolHeader).Hash
$expectedWatchdogHeaderSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $mediaWatchdogHeader).Hash
if (
    $protocolManifest.name -ne 'T1MD' -or
    $protocolManifest.version -ne 1 -or
    $protocolManifest.transport -ne 'AF_UNIX/SOCK_SEQPACKET' -or
    $protocolManifest.header_sha256 -ne $expectedProtocolHeaderSha256 -or
    $protocolManifest.maximum_decode_requests -ne 1 -or
    $protocolManifest.maximum_in_flight_frames -ne 16 -or
    $protocolManifest.backpressure_feature_bit -ne 64 -or
    $protocolManifest.linear_memory_output_feature_bit -ne 128 -or
    $protocolManifest.backpressure_message_type -ne 15 -or
    $protocolManifest.backpressure_timeout_ms -ne 0 -or
    $protocolManifest.backpressure_reset_terminal -ne 'RESET_DONE-without-EXIT' -or
    $surfaceExportManifest.mode -ne 'separate-layers' -or
    $surfaceExportManifest.object_layout -ne 'one-object-per-plane' -or
    $surfaceExportManifest.modifier_scope -ne 'per-object' -or
    $surfaceExportManifest.modifier_layout -ne 'natural-per-plane' -or
    $surfaceExportManifest.composed_fallback -ne $false -or
    $surfaceExportManifest.chroma_subsampling -ne '4:2:0' -or
    (@($surfaceExportManifest.bit_depths) -join ',') -ne '8,10' -or
    (@($surfaceExportManifest.output_formats) -join ',') -ne 'NV12,P010' -or
    $watchdogManifest.format -ne 1 -or
    $watchdogManifest.policy_id -ne 't1md-watchdog-v1' -or
    $watchdogManifest.header_sha256 -ne $expectedWatchdogHeaderSha256 -or
    $watchdogManifest.authority -ne 'supervisor' -or
    $watchdogManifest.clock -ne 'CLOCK_MONOTONIC' -or
    $watchdogManifest.timeout_action -ne 'SIGKILL' -or
    $watchdogManifest.idle_timeout_ms -ne 0 -or
    $watchdogManifest.starting_timeout_ms -ne 15000 -or
    $watchdogManifest.hello_timeout_ms -ne 30000 -or
    $watchdogManifest.create_timeout_ms -ne 15000 -or
    $watchdogManifest.decode_timeout_ms -ne 15000 -or
    $watchdogManifest.flush_timeout_ms -ne 15000 -or
    $watchdogManifest.reset_timeout_ms -ne 10000 -or
    $watchdogManifest.release_timeout_ms -ne 6000 -or
    $watchdogManifest.destroy_timeout_ms -ne 10000 -or
    $watchdogManifest.cleanup_timeout_ms -ne 10000 -or
    $watchdogManifest.exiting_timeout_ms -ne 1000 -or
    $sandboxManifest.session_exec_visible_fds -ne 6 -or
    $sandboxManifest.session_required_ipc_fds -ne 3 -or
    $sandboxManifest.session_unexpected_inherited_fds -ne 0 -or
    $sandboxManifest.local_file_native.activation -ne 'before-container-open' -or
    $sandboxManifest.local_file_native.filesystem -ne 'exact-input-read-only' -or
    $sandboxManifest.local_file_native.seccomp -ne 'filter-tsync' -or
    $sandboxManifest.local_file_software.activation -ne 'pre-main-constructor' -or
    $sandboxManifest.local_file_software.library -ne '/the one/catalogue/audio/libt1-media-file-sandbox.so.1' -or
    $sandboxManifest.local_file_software.filesystem -ne 'exact-input-read-only' -or
    $sandboxManifest.local_file_software.seccomp -ne 'filter-tsync'
) {
    throw 'The staged audio manifest decode/export/watchdog attestation is invalid.'
}

Get-ChildItem -LiteralPath $softwareStage -File |
    Where-Object Name -NotIn @('manifest.json', 'ffmpeg', 'ffprobe', 't1-video-decode', 't1-media-decoderd') |
    Remove-Item -Force

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

$invalidCatalogueFiles = @(Get-ChildItem -LiteralPath $catalogueTarget -File | Where-Object { $_.Name -notmatch '^lib.+\.so\.\d+$' })
if ($invalidCatalogueFiles) {
    throw "The audio catalogue contains non-library files: $($invalidCatalogueFiles.Name -join ', ')"
}

$catalogueFiles = @(Get-ChildItem -LiteralPath $catalogueTarget -File)
$softwareFiles = @(Get-ChildItem -LiteralPath $softwareTarget -File)
Write-Host "Media runtime completed: $($catalogueFiles.Count) library file(s), $($softwareFiles.Count) software file(s)."
