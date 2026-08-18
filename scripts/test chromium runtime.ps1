[CmdletBinding()]
param()

$incrementalTestBootstrap = Join-Path $PSScriptRoot 'incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'common.ps1')
$mountScript = Join-Path $PSScriptRoot 'mount.ps1'
$unmountScript = Join-Path $PSScriptRoot 'unmount.ps1'
$mountPoint = '/mnt/t1fs'
$mounted = $false
$operationError = $null

if (Test-T1OSDiskMounted) {
    throw 'storage.img is already mounted. Unmount it before testing Chromium.'
}

try {
    & pwsh -NoLogo -NoProfile -NonInteractive -File $mountScript
    if ($LASTEXITCODE -ne 0) {
        throw "Could not mount storage.img (exit code $LASTEXITCODE)."
    }
    $mounted = $true

    $diagnostic = @'
set -euo pipefail
root=$1
processes="$root/the one/drivers/processes"
state="$root/the one/drivers/state"
nodes="$root/the one/drivers/nodes"
ephemeral="$root/.ephemeral"
created=
diagnostic_master_created=0
diagnostic_identity_created=0
diagnostic_user="crdiag$$"
diagnostic_master_file="$root/the one/master/master.txt"
if [ -f "$diagnostic_master_file" ] &&
        [ ! -L "$diagnostic_master_file" ]; then
    diagnostic_master_record=$(head -n 1 "$diagnostic_master_file" | tr -d '\r\n')
    diagnostic_master_user=${diagnostic_master_record%%:*}
    case "$diagnostic_master_user" in
        ''|*[!A-Za-z0-9._-]*)
            echo 'The Chromium diagnostic found an invalid master credential record' >&2
            exit 1
            ;;
        *)
            diagnostic_user=$diagnostic_master_user
            ;;
    esac
fi
diagnostic_user_root="$root/master/$diagnostic_user"
diagnostic_identity_directory="$root/the one/settings/session"
diagnostic_identity="$diagnostic_identity_directory/identity.json"
chromium_program="$root/the one/software/chromium/program"
chromium_extensions="$chromium_program/extensions"
chromium_settings="$root/the one/settings/chromium"
chromium_settings_backup="$ephemeral/chromium-settings-backup"
chromium_settings_existed=0
chromium_settings_backup_ready=0
dns_file="$root/the one/settings/network/dns.txt"
dns_backup="$ephemeral/dns.txt.backup"
dns_file_existed=0
dns_backup_ready=0
if [ -e "$chromium_extensions" ] || [ -L "$chromium_extensions" ]; then
    echo 'The measured Chromium program tree already contains an extensions object' >&2
    exit 1
fi

cleanup() {
    set +e
    rm -rf -- \
        "$chromium_settings/profile/.t1os-owned-state-test" \
        "$chromium_settings/config/.t1os-owned-state-test" \
        "$chromium_settings/font-cache/.t1os-owned-state-test"
    rm -f -- \
        "$chromium_settings/profile/Default/.t1os-unsafe-link" \
        "$chromium_settings/config/.t1os-unsafe-fifo"
    if [ "$chromium_settings_backup_ready" = 1 ]; then
        rm -rf -- "$chromium_settings"
        if [ "$chromium_settings_existed" = 1 ]; then
            cp -a -- "$chromium_settings_backup" "$chromium_settings"
        fi
    fi
    if [ "$dns_backup_ready" = 1 ]; then
        if [ "$dns_file_existed" = 1 ]; then
            cp -a -- "$dns_backup" "$dns_file"
        else
            rm -f -- "$dns_file"
        fi
    fi
    for target in random urandom full zero null; do
        umount "$nodes/$target" 2>/dev/null || true
    done
    mountpoint -q "$state/class/drm" && umount "$state/class/drm"
    mountpoint -q "$state" && umount "$state"
    mountpoint -q "$processes" && umount "$processes"
    mountpoint -q "$ephemeral" && umount "$ephemeral"
    for target in $created; do rm -f -- "$target"; done
    if [ "$diagnostic_master_created" = 1 ]; then
        rm -rf -- "$diagnostic_user_root"
        rm -f -- "$diagnostic_master_file"
        rmdir "$root/the one/master" "$root/master" 2>/dev/null || true
    fi
    if [ "$diagnostic_identity_created" = 1 ]; then
        rm -f -- "$diagnostic_identity"
        rmdir -- "$diagnostic_identity_directory" 2>/dev/null || true
    fi
    if [ -d "$chromium_extensions" ] &&
            [ ! -L "$chromium_extensions" ] &&
            ! find "$chromium_extensions" -mindepth 1 -print -quit |
                grep -q .; then
        rmdir -- "$chromium_extensions"
    fi
}
trap cleanup EXIT

mkdir -p "$processes" "$state" "$nodes" "$ephemeral"
mount -t proc proc "$processes"
mount --bind /sys "$state"
mount -t tmpfs -o mode=1777,nosuid,nodev tmpfs "$ephemeral"
if [ -e "$chromium_settings" ] || [ -L "$chromium_settings" ]; then
    if [ ! -d "$chromium_settings" ] || [ -L "$chromium_settings" ]; then
        echo 'The Chromium settings root is not a real directory' >&2
        exit 1
    fi
    cp -a -- "$chromium_settings" "$chromium_settings_backup"
    chromium_settings_existed=1
fi
chromium_settings_backup_ready=1
if [ -e "$dns_file" ] || [ -L "$dns_file" ]; then
    if [ ! -f "$dns_file" ] || [ -L "$dns_file" ]; then
        echo 'The Chromium DNS configuration is not a regular file' >&2
        exit 1
    fi
    cp -a -- "$dns_file" "$dns_backup"
    dns_file_existed=1
fi
dns_backup_ready=1

# A booted T1OS instance has an authenticated user and measured DRM state
# before Chromium starts. The live process-chain test uses the software-safe
# Nouveau path because WSL exposes no physical DRM device. NVIDIA's mandatory
# render-node and NVDEC contracts are covered by the static and video suites.
if [ ! -e "$diagnostic_master_file" ]; then
    mkdir -p "$root/the one/master" "$diagnostic_user_root/flash/downloads"
    printf '%s\n' "$diagnostic_user" > "$diagnostic_master_file"
    diagnostic_master_created=1
fi
if [ ! -e "$diagnostic_identity" ]; then
    mkdir -p "$diagnostic_identity_directory"
    printf '{"format":1,"username":"%s"}\n' "$diagnostic_user" \
        > "$diagnostic_identity"
    chown 0:1000 "$diagnostic_identity_directory" "$diagnostic_identity"
    chmod 0750 "$diagnostic_identity_directory"
    chmod 0640 "$diagnostic_identity"
    diagnostic_identity_created=1
fi
fake_drm="$ephemeral/chromium-test-drm"
mkdir -p "$fake_drm/card0-HDMI-A-1" "$fake_drm/card0/device/driver"
printf 'connected\n' > "$fake_drm/card0-HDMI-A-1/status"
ln -s '/the one/drivers/state/module/nouveau' \
    "$fake_drm/card0/device/driver/module"
mount --bind "$fake_drm" "$state/class/drm"

for target in null zero full random urandom; do
    destination="$nodes/$target"
    if [ ! -e "$destination" ]; then
        : > "$destination"
        created="$created $destination"
    fi
    mount --bind "/dev/$target" "$destination"
done

chroot "$root" \
    '/the one/software/python/bin/python3.13' -B \
    '/the one/build/chromium/chromium.py' diagnostic |
    tee "$ephemeral/chromium-runtime-diagnostic.json"
grep -F '"cache_policy": true' "$ephemeral/chromium-runtime-diagnostic.json"
grep -F '"nonblocking_transport": true' "$ephemeral/chromium-runtime-diagnostic.json"

chroot "$root" \
    '/the one/software/python/bin/python3.13' -B \
    '/the one/build/chromium/chromium.py' instance-diagnostic

if [ -e "$root/the one/settings/chromium/instance.sock" ] || [ -L "$root/the one/settings/chromium/instance.sock" ]; then
    echo 'Chromium instance diagnostic left its activation socket behind' >&2
    exit 1
fi

profile="$chromium_settings/profile"
config="$chromium_settings/config"
font_cache="$chromium_settings/font-cache"
mkdir -p "$profile/Default" "$config" "$font_cache"

unsafe_link="$profile/Default/.t1os-unsafe-link"
ln -s '/the one/settings' "$unsafe_link"
if chroot "$root" \
        '/the one/software/python/bin/python3.13' -B \
        '/the one/build/chromium/chromium.py' engine-diagnostic \
        >"$ephemeral/chromium-unsafe-link.out" 2>&1; then
    echo 'Chromium accepted an unexpected profile symbolic link' >&2
    exit 1
fi
grep -F 'unexpected symbolic link in Chromium owned state' \
    "$ephemeral/chromium-unsafe-link.out"
rm -f -- "$unsafe_link"

unsafe_fifo="$config/.t1os-unsafe-fifo"
mkfifo "$unsafe_fifo"
if chroot "$root" \
        '/the one/software/python/bin/python3.13' -B -c \
        'import runpy; state = runpy.run_path("/the one/build/chromium/chromium.py"); state["repairchromiumownedtree"]("/the one/settings/chromium/config")' \
        >"$ephemeral/chromium-unsafe-fifo.out" 2>&1; then
    echo 'Chromium accepted an unexpected object in its configuration tree' >&2
    exit 1
fi
grep -F 'unexpected fifo in Chromium owned state' \
    "$ephemeral/chromium-unsafe-fifo.out"
rm -f -- "$unsafe_fifo"

for directory in "$profile" "$config" "$font_cache"; do
    fixture="$directory/.t1os-owned-state-test"
    mkdir -p "$fixture/nested"
    printf 'root-owned state\n' > "$fixture/nested/sentinel"
    chown -R 0:0 "$fixture"
    find "$fixture" -type d -exec chmod 0500 {} +
    find "$fixture" -type f -exec chmod 0400 {} +
done

engine_diagnostic_log="$ephemeral/chromium-engine-current.log"
chroot "$root" \
    '/the one/software/python/bin/python3.13' -B \
    '/the one/build/chromium/chromium.py' engine-diagnostic \
    2>"$engine_diagnostic_log" |
    tee "$ephemeral/chromium-engine-diagnostic.json"
cat "$engine_diagnostic_log" >&2
grep -F '"zygote_provider": true' \
    "$ephemeral/chromium-engine-diagnostic.json"
grep -F '"zygote_library_path": true' \
    "$ephemeral/chromium-engine-diagnostic.json"
grep -F '"zygote_verified": true' \
    "$ephemeral/chromium-engine-diagnostic.json"
grep -F '"sandbox_environment": true' \
    "$ephemeral/chromium-engine-diagnostic.json"
grep -F '"gpu_found": true' \
    "$ephemeral/chromium-engine-diagnostic.json"
grep -F '"gpu_provider": true' \
    "$ephemeral/chromium-engine-diagnostic.json"
grep -F '"utility_found": true' \
    "$ephemeral/chromium-engine-diagnostic.json"
grep -F '"utility_provider": true' \
    "$ephemeral/chromium-engine-diagnostic.json"
grep -F '"utility_launch_scope": true' \
    "$ephemeral/chromium-engine-diagnostic.json"
grep -F '"utility_runtime_ready": true' \
    "$ephemeral/chromium-engine-diagnostic.json"
grep -F '"video_driver": "nouveau"' \
    "$ephemeral/chromium-engine-diagnostic.json"
grep -F '"gpu_driver_loaded": false' \
    "$ephemeral/chromium-engine-diagnostic.json"
grep -F '"expected_library_path": "/the one/software/chromium/libraries:/the one/catalogue/graphics"' \
    "$ephemeral/chromium-engine-diagnostic.json"
for directory in "$profile" "$config" "$font_cache"; do
    fixture="$directory/.t1os-owned-state-test"
    [ "$(stat -c '%u:%g:%a' "$fixture")" = '1000:1000:700' ]
    [ "$(stat -c '%u:%g:%a' "$fixture/nested")" = '1000:1000:700' ]
    [ "$(stat -c '%u:%g:%a' "$fixture/nested/sentinel")" = '1000:1000:600' ]
    rm -rf -- "$fixture"
done
grep -F 'Chromium owned state write probes passed roots=4' \
    "$ephemeral/chromium-engine-current.log"
# The diagnostic JSON above verifies the live sandbox, zygote, GPU, utility,
# provider, launch-scope, and library-path chain.  Wrapper log emission is
# asynchronous and can land outside this invocation's line-number window, so
# do not duplicate those live assertions with a timing-sensitive log match.
if grep -F 't1os-chrome-subprocess: invalid Chromium parent' \
    "$ephemeral/chromium-engine-current.log"; then
    echo 'Chromium diagnostic rejected a measured browser/zygote parent' >&2
    exit 1
fi
if grep -F 'Network service crashed or was terminated' \
    "$ephemeral/chromium-engine-current.log"; then
    echo 'Chromium diagnostic entered a Network Service crash loop' >&2
    exit 1
fi

chroot "$root" \
    '/the one/software/python/bin/python3.13' -B \
    '/the one/build/chromium/chromium.py' audio-diagnostic

for name in SingletonLock SingletonSocket SingletonCookie; do
    path="$root/the one/settings/chromium/profile/$name"
    if [ -e "$path" ] || [ -L "$path" ]; then
        echo "Chromium diagnostic left a persistent profile singleton: $name" >&2
        exit 1
    fi
done
if [ -e "$root/.t1dns" ] || [ -L "$root/.t1dns" ]; then
    echo 'Chromium diagnostic found the forbidden non-T1OS DNS alias' >&2
    exit 1
fi
if [ -e "$root/the one/dns.txt" ] || [ -L "$root/the one/dns.txt" ]; then
    echo 'Chromium diagnostic found the rejected shallow DNS path' >&2
    exit 1
fi
grep -Eq '^nameserver [0-9]+(\.[0-9]+){3}$' "$root/the one/settings/network/dns.txt"

# System-extension discovery is redirected to the ephemeral Chromium runtime.
# Any object here means the provider regressed and mutated packaged software.
if [ -e "$chromium_extensions" ] || [ -L "$chromium_extensions" ]; then
    echo 'Chromium diagnostic mutated its measured program directory' >&2
    exit 1
fi
'@

    & wsl.exe -d Ubuntu -u root --exec nsenter -t 1 -m -- bash -c $diagnostic bash $mountPoint
    if ($LASTEXITCODE -ne 0) {
        throw "Chromium T1OS runtime diagnostic failed (exit code $LASTEXITCODE)."
    }
}
catch {
    $operationError = $_
}
finally {
    if ($mounted) {
        & pwsh -NoLogo -NoProfile -NonInteractive -File $unmountScript
        if ($LASTEXITCODE -ne 0 -and -not $operationError) {
            $operationError = [Exception]::new("Could not unmount storage.img after Chromium testing (exit code $LASTEXITCODE).")
        }
    }
}

if ($operationError) {
    throw $operationError
}

Write-Host 'Chromium T1OS runtime diagnostic passed.'
