[CmdletBinding()]
param()

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$runtime = Join-Path $projectRoot 'source\software\chromium'
$client = Join-Path $PSScriptRoot 'test chromium xwm.py'

foreach ($path in @(
    (Join-Path $runtime 'tools\Xvfb'),
    (Join-Path $runtime 'tools\t1os-xwm'),
    (Join-Path $runtime 'tools\t1os-xinput'),
    (Join-Path $runtime 't1os-path-provider.so'),
    $client
)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Chromium XWM diagnostic input is missing: $path"
    }
}

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

$wslRuntime = ConvertTo-WslPath -WindowsPath $runtime
$wslClient = ConvertTo-WslPath -WindowsPath $client
$diagnostic = @'
set -euo pipefail
runtime=$1
test_client=$2
xvfb_pid=
xwm_pid=

cleanup() {
    set +e
    [ -z "$xwm_pid" ] || kill -9 "$xwm_pid" 2>/dev/null
    [ -z "$xvfb_pid" ] || kill -9 "$xvfb_pid" 2>/dev/null
    wait "$xwm_pid" 2>/dev/null || true
    wait "$xvfb_pid" 2>/dev/null || true
    mountpoint -q "/the one/software/chromium" &&
        umount "/the one/software/chromium"
    rm -f \
        /tmp/t1os-xwm-damage.log \
        /tmp/t1os-xwm-error.log \
        /tmp/t1os-xinput-exact.input \
        /tmp/t1os-xinput-over.input \
        /tmp/t1os-xinput-exact-output.log \
        /tmp/t1os-xinput-exact-error.log \
        /tmp/t1os-xinput-over-output.log \
        /tmp/t1os-xinput-over-error.log
    rmdir "/the one/software/chromium" "/the one/software" "/the one" \
        2>/dev/null || true
    rm -rf -- /.ephemeral/chromium
    rmdir /.ephemeral 2>/dev/null || true
}
trap cleanup EXIT

[ ! -e "/the one/software/chromium" ]
[ ! -e /.ephemeral/chromium ]
mkdir -p \
    "/the one/software/chromium" \
    /.ephemeral/chromium/display \
    /.ephemeral/chromium/framebuffer \
    /.ephemeral/chromium/temporary
mount --bind "$runtime" "/the one/software/chromium"
cp \
    "/the one/software/chromium/t1os-path-provider.so" \
    /.ephemeral/chromium/path-provider.so
chmod 0555 /.ephemeral/chromium/path-provider.so

env \
    DISPLAY=:99 \
    LD_PRELOAD=/.ephemeral/chromium/path-provider.so \
    TMPDIR=/.ephemeral/chromium/temporary \
    "/the one/software/chromium/tools/Xvfb" \
    :99 -screen 0 2560x1440x24 \
    -fbdir /.ephemeral/chromium/framebuffer \
    -nolisten tcp -noreset -nocursor \
    >/tmp/t1os-xwm-error.log 2>&1 &
xvfb_pid=$!

for ignored in $(seq 1 200); do
    [ -S /.ephemeral/chromium/display/X99 ] && break
    kill -0 "$xvfb_pid"
    sleep .02
done
[ -S /.ephemeral/chromium/display/X99 ]

env \
    DISPLAY=:99 \
    LD_PRELOAD=/.ephemeral/chromium/path-provider.so \
    TMPDIR=/.ephemeral/chromium/temporary \
    T1OS_XWM_READY=/.ephemeral/chromium/xwm.ready \
    "/the one/software/chromium/tools/t1os-xwm" \
    >/tmp/t1os-xwm-damage.log 2>>/tmp/t1os-xwm-error.log &
xwm_pid=$!

for ignored in $(seq 1 200); do
    [ -f /.ephemeral/chromium/xwm.ready ] && break
    kill -0 "$xwm_pid"
    sleep .02
done
[ -f /.ephemeral/chromium/xwm.ready ]

# The Python bridge accepts exactly one MiB of raw UTF-8 paste data, encoded as
# two hexadecimal characters per byte. Zero bytes keep the X11 action itself a
# no-op while exercising the complete native protocol record. The following
# PING proves that the exact boundary was consumed; one raw byte over must stop
# at the fixed reader bound before PING can be processed.
python3 - \
    /tmp/t1os-xinput-exact.input \
    /tmp/t1os-xinput-over.input <<'PY'
import sys

for path, size in ((sys.argv[1], 1024 * 1024), (sys.argv[2], 1024 * 1024 + 1)):
    with open(path, "wb") as stream:
        stream.write(b"T " + (b"00" * size) + b"\nP\n")
PY

env \
    DISPLAY=:99 \
    LD_PRELOAD=/.ephemeral/chromium/path-provider.so \
    TMPDIR=/.ephemeral/chromium/temporary \
    "/the one/software/chromium/tools/t1os-xinput" \
    </tmp/t1os-xinput-exact.input \
    >/tmp/t1os-xinput-exact-output.log \
    2>/tmp/t1os-xinput-exact-error.log
grep -q '^READY$' /tmp/t1os-xinput-exact-output.log
grep -q '^PONG$' /tmp/t1os-xinput-exact-output.log

env \
    DISPLAY=:99 \
    LD_PRELOAD=/.ephemeral/chromium/path-provider.so \
    TMPDIR=/.ephemeral/chromium/temporary \
    "/the one/software/chromium/tools/t1os-xinput" \
    </tmp/t1os-xinput-over.input \
    >/tmp/t1os-xinput-over-output.log \
    2>/tmp/t1os-xinput-over-error.log
grep -q '^READY$' /tmp/t1os-xinput-over-output.log
! grep -q '^PONG$' /tmp/t1os-xinput-over-output.log
grep -q 'command exceeds limit' /tmp/t1os-xinput-over-error.log

DISPLAY=:99 python3 "$test_client" 1920 1080 2560 1316

diagnostic_complete() {
    local cursor_count damage_count
    local -a fullscreen_events

    grep -q '^WINDOW ' /tmp/t1os-xwm-damage.log || return 1
    grep -q '^DAMAGE 37 29 ' /tmp/t1os-xwm-damage.log || return 1
    grep -q '^DAMAGE 57 49 ' /tmp/t1os-xwm-damage.log || return 1
    grep -q '^DAMAGE 297 49 ' /tmp/t1os-xwm-damage.log || return 1
    grep -q '^DAMAGE 537 49 ' /tmp/t1os-xwm-damage.log || return 1
    grep -q '^DAMAGE 57 289 ' /tmp/t1os-xwm-damage.log || return 1
    grep -q '^DAMAGE 297 289 ' /tmp/t1os-xwm-damage.log || return 1
    grep -q '^DAMAGE 137 129 ' /tmp/t1os-xwm-damage.log || return 1
    cursor_count=$(grep -Ec '^CURSOR(_IMAGE)? ' /tmp/t1os-xwm-damage.log || true)
    [ "$cursor_count" -ge 3 ] || return 1
    mapfile -t fullscreen_events < <(
        sed -n 's/^FULLSCREEN //p' /tmp/t1os-xwm-damage.log
    )
    [ "${#fullscreen_events[@]}" -eq 4 ] || return 1
    [ "${fullscreen_events[0]}" = 1 ] || return 1
    [ "${fullscreen_events[1]}" = 0 ] || return 1
    [ "${fullscreen_events[2]}" = 1 ] || return 1
    [ "${fullscreen_events[3]}" = 0 ] || return 1
    damage_count=$(grep -c '^DAMAGE ' /tmp/t1os-xwm-damage.log || true)
    [ "$damage_count" -ge 12 ]
}

for ignored in $(seq 1 300); do
    diagnostic_complete && break
    kill -0 "$xwm_pid"
    sleep .01
done
if ! diagnostic_complete; then
    echo 'Chromium XWM terminal event set was incomplete:' >&2
    cat /tmp/t1os-xwm-damage.log >&2
    exit 1
fi
grep -q '^WINDOW ' /tmp/t1os-xwm-damage.log
grep -q '^DAMAGE ' /tmp/t1os-xwm-damage.log
grep -q '^DAMAGE 37 29 ' /tmp/t1os-xwm-damage.log
grep -q '^DAMAGE 57 49 ' /tmp/t1os-xwm-damage.log
grep -q '^DAMAGE 297 49 ' /tmp/t1os-xwm-damage.log
grep -q '^DAMAGE 537 49 ' /tmp/t1os-xwm-damage.log
grep -q '^DAMAGE 57 289 ' /tmp/t1os-xwm-damage.log
grep -q '^DAMAGE 297 289 ' /tmp/t1os-xwm-damage.log
grep -q '^DAMAGE 137 129 ' /tmp/t1os-xwm-damage.log
cursor_count=$(grep -Ec '^CURSOR(_IMAGE)? ' /tmp/t1os-xwm-damage.log)
[ "$cursor_count" -ge 3 ]
mapfile -t fullscreen_events < <(
    sed -n 's/^FULLSCREEN //p' /tmp/t1os-xwm-damage.log
)
[ "${#fullscreen_events[@]}" -eq 4 ]
[ "${fullscreen_events[0]}" = 1 ]
[ "${fullscreen_events[1]}" = 0 ]
[ "${fullscreen_events[2]}" = 1 ]
[ "${fullscreen_events[3]}" = 0 ]
count=$(grep -c '^DAMAGE ' /tmp/t1os-xwm-damage.log)
[ "$count" -ge 12 ]
echo "Window announcements: $(grep -c '^WINDOW ' /tmp/t1os-xwm-damage.log)"
echo "Fullscreen state events: ${fullscreen_events[*]}"
echo "Cursor state events: $cursor_count"
echo "XDamage events: $count"
'@

$normalized = $diagnostic.Replace("`r", '')
$normalized | wsl.exe -d Ubuntu -u root --exec bash -s -- $wslRuntime $wslClient
if ($LASTEXITCODE -ne 0) {
    throw "Chromium XWM diagnostic failed (exit code $LASTEXITCODE)."
}

Write-Host 'Chromium XWM diagnostic passed.'
