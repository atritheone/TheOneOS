[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$driveLetter = 'D'
$driveRoot = "$driveLetter`:\"
$volume = Get-Volume -DriveLetter $driveLetter -ErrorAction Stop
$partition = Get-Partition -DriveLetter $driveLetter -ErrorAction Stop
$disk = $partition | Get-Disk -ErrorAction Stop

if (
    $disk.BusType -cne 'USB' -or
    $disk.IsBoot -or
    $disk.IsSystem -or
    $disk.IsReadOnly -or
    [string]$volume.FileSystemType -cne 'NTFS' -or
    [string]$volume.HealthStatus -cne 'Healthy' -or
    -not ([string]$volume.FileSystemLabel).StartsWith(
        'T1OS',
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw 'D: is not the healthy writable T1OS USB target.'
}
foreach ($relative in @(
    'boot',
    'the one',
    'the one\build\chromium',
    'the one\build\audio',
    'the one\build\graphics',
    'the one\build\windows',
    'the one\catalogue\graphics\drivers',
    'the one\software\chromium',
    'the one\settings\media'
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $driveRoot $relative))) {
        throw "T1OS USB target path is absent: $relative"
    }
}

# A source-built Chromium ELF can retain the Windows read-only DOS attribute
# from an earlier DrvFS deployment even though the containing NTFS directory
# is writable. rsync correctly stages the replacement, but NTFS then rejects
# its final rename over that read-only destination. Clear only that installed
# file's attribute before entering the scoped, checksum-verified deployment.
$installedChrome = Join-Path $driveRoot 'the one\software\chromium\program\chrome'
if (Test-Path -LiteralPath $installedChrome) {
    $installedChromeItem = Get-Item -Force -LiteralPath $installedChrome
    if ($installedChromeItem.IsReadOnly) {
        $installedChromeItem.IsReadOnly = $false
        $installedChromeItem = Get-Item -Force -LiteralPath $installedChrome
        if ($installedChromeItem.IsReadOnly) {
            throw 'Could not clear the installed Chromium read-only attribute.'
        }
    }
}

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $converted = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $converted) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($converted | Select-Object -First 1)).Trim()
}

$chromiumSource = ConvertTo-WslPath (
    Join-Path $projectRoot 'source\software\chromium'
)
$chromiumLauncher = ConvertTo-WslPath (
    Join-Path $projectRoot 'source\build software\chromium\chromium.py'
)
$audioServer = ConvertTo-WslPath (
    Join-Path $projectRoot 'source\build software\audio\audioserver.py'
)
$audioClient = ConvertTo-WslPath (
    Join-Path $projectRoot 'source\build software\audio\audio.py'
)
$windowServer = ConvertTo-WslPath (
    Join-Path $projectRoot 'source\build software\windows\windowserver.py'
)
$graphicsEngine = ConvertTo-WslPath (
    Join-Path $projectRoot 'source\build software\graphics\graphics.py'
)
$mediaPolicy = ConvertTo-WslPath (
    Join-Path $projectRoot 'source\settings\media\video decode service.json'
)
$hardwareDiagnostics = ConvertTo-WslPath (
    Join-Path $projectRoot 'source\build software\chromium\hardware diagnostics.json'
)
$graphicsCatalogue = ConvertTo-WslPath (
    Join-Path $projectRoot 'source\catalogue\graphics\catalogue.json'
)
$nvidiaVaapiDriver = ConvertTo-WslPath (
    Join-Path $projectRoot 'source\catalogue\graphics\drivers\nvidia_drv_video.so'
)

$copyCommand = @'
set -eu
mount_point=/mnt/t1chromium
drive_source=$1
chromium_source=$2
chromium_launcher=$3
window_server=$4
graphics_engine=$5
media_policy=$6
hardware_diagnostics=$7
graphics_catalogue=$8
nvidia_vaapi_driver=$9
audio_server=${10}
audio_client=${11}
mounted_here=0

cleanup() {
    status=$?
    if [ "$mounted_here" = 1 ]; then
        sync
        umount "$mount_point" || status=1
    fi
    trap - EXIT HUP INT TERM
    exit "$status"
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$mount_point"
if mountpoint -q "$mount_point"; then
    echo "$mount_point is already mounted" >&2
    exit 1
fi
if find "$mount_point" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    echo "$mount_point contains stale unmounted files" >&2
    exit 1
fi

mount -t drvfs "$drive_source" "$mount_point" \
    -o metadata,uid=0,gid=0,umask=022
mounted_here=1
case ",$(findmnt -rn -o OPTIONS -T "$mount_point" | head -n 1)," in
    *,ro,*) echo 'T1OS USB mounted read-only' >&2; exit 1 ;;
esac

target="$mount_point/the one"
test -d "$target/build/chromium"
test -d "$target/build/audio"
test -d "$target/build/graphics"
test -d "$target/build/windows"
test -d "$target/catalogue/graphics/drivers"
test -d "$target/software/chromium"
test -d "$target/settings/media"
test -f "$mount_point/autorun.inf"
grep -Eiq '^Label=T1OS([[:space:]]|$)' "$mount_point/autorun.inf"

# Use rsync's temporary-file-and-rename update for helpers. Some previously
# deployed root-owned executables can be replaced in their writable directory
# but cannot be opened in-place through DrvFS/NTFS ACL translation.
rsync -a --no-whole-file --checksum --delete-delay \
    --no-perms --no-owner --no-group --omit-dir-times --no-times \
    --itemize-changes --human-readable \
    --out-format='Chromium software: %i %n%L' \
    -- "$chromium_source"/ "$target/software/chromium"/

# rsync deliberately does not copy DrvFS ownership or mode metadata from the
# Windows source tree.  A changed ELF is therefore created as 0644 before its
# atomic rename unless executable mode is restored explicitly.  Preserve the
# established permissions while requiring execute permission on every program
# Chromium can launch; the SUID sandbox retains its separately verified 4755.
for executable in \
    "$target/software/chromium/program/chrome" \
    "$target/software/chromium/program/chrome_crashpad_handler" \
    "$target/software/chromium/tools"/*
do
    test -f "$executable"
    if test ! -x "$executable"; then
        chmod a+x "$executable"
    fi
done
rsync -a --no-whole-file --no-perms --no-owner --no-group --no-times --checksum \
    -- "$chromium_launcher" "$target/build/chromium/chromium.py"
rsync -a --no-whole-file --no-perms --no-owner --no-group --no-times --checksum \
    -- "$audio_server" "$target/build/audio/audioserver.py"
rsync -a --no-whole-file --no-perms --no-owner --no-group --no-times --checksum \
    -- "$audio_client" "$target/build/audio/audio.py"
rsync -a --no-whole-file --no-perms --no-owner --no-group --no-times --checksum \
    -- "$window_server" "$target/build/windows/windowserver.py"
rsync -a --no-whole-file --no-perms --no-owner --no-group --no-times --checksum \
    -- "$graphics_engine" "$target/build/graphics/graphics.py"
rsync -a --no-whole-file --no-perms --no-owner --no-group --no-times --checksum \
    -- "$media_policy" "$target/settings/media/video decode service.json"
# The live USB settings directory deliberately rejects creation of new files.
# Chromium's audited fallback lives beside the launcher, where it remains
# available even when the settings image rejects a new policy filename. Create
# or update that exact removable-media policy atomically.
rsync -a --no-whole-file --no-perms --no-owner --no-group --no-times --checksum \
    -- "$hardware_diagnostics" \
    "$target/build/chromium/hardware diagnostics.json"
rsync -a --no-whole-file --no-perms --no-owner --no-group --no-times --checksum \
    -- "$nvidia_vaapi_driver" \
    "$target/catalogue/graphics/drivers/nvidia_drv_video.so"
rsync -a --no-whole-file --no-perms --no-owner --no-group --no-times --checksum \
    -- "$graphics_catalogue" "$target/catalogue/graphics/catalogue.json"

# The existing root-owned setuid sandbox is deliberately preserved. DrvFS
# metadata updates are not required for this content-only deployment and can
# be rejected by the host ACL even when ordinary file replacement is allowed.
test "$(stat -c '%u:%g:%a' \
    "$target/software/chromium/program/chrome-sandbox")" = '0:0:4755'
test -x "$target/software/chromium/program/chrome"
test -x "$target/software/chromium/program/chrome_crashpad_handler"

differences=$(rsync -a --no-whole-file --no-perms --no-owner --no-group \
    --omit-dir-times --no-times \
    --checksum --delete --itemize-changes --dry-run -- \
    "$chromium_source"/ "$target/software/chromium"/)
test -z "$differences" || {
    echo 'Chromium USB read-back differs:' >&2
    printf '%s\n' "$differences" >&2
    exit 1
}
cmp -s "$chromium_launcher" "$target/build/chromium/chromium.py"
cmp -s "$audio_server" "$target/build/audio/audioserver.py"
cmp -s "$audio_client" "$target/build/audio/audio.py"
cmp -s "$window_server" "$target/build/windows/windowserver.py"
cmp -s "$graphics_engine" "$target/build/graphics/graphics.py"
cmp -s "$media_policy" "$target/settings/media/video decode service.json"
cmp -s "$hardware_diagnostics" \
    "$target/build/chromium/hardware diagnostics.json"
cmp -s "$nvidia_vaapi_driver" \
    "$target/catalogue/graphics/drivers/nvidia_drv_video.so"
cmp -s "$graphics_catalogue" "$target/catalogue/graphics/catalogue.json"

source_hash=$(sha256sum "$chromium_source/program/chrome" | awk '{print $1}')
target_hash=$(sha256sum "$target/software/chromium/program/chrome" | awk '{print $1}')
test "$source_hash" = "$target_hash"
# The target hash above proves byte identity, so inspect the local source ELF
# for the bridge-specific code marker instead of performing a fourth complete
# read of the 2.5 GB executable from the USB. This marker proves the bounded
# RGB GBM DMA-BUF producer, rather than the retired stream transport, is built.
grep -a -F -q -- 'T1OS_PRESENTATION_BRIDGE transport=rgb-gbm-dmabuf-v1' \
    "$chromium_source/program/chrome"
printf 'Chromium SHA-256: %s\n' "$target_hash"
printf 'Chromium Python SHA-256: '
sha256sum "$target/build/chromium/chromium.py" | awk '{print $1}'
printf 'AudioServer Python SHA-256: '
sha256sum "$target/build/audio/audioserver.py" | awk '{print $1}'
printf 'Audio client Python SHA-256: '
sha256sum "$target/build/audio/audio.py" | awk '{print $1}'
printf 'WindowServer SHA-256: '
sha256sum "$target/build/windows/windowserver.py" | awk '{print $1}'
printf 'Graphics engine SHA-256: '
sha256sum "$target/build/graphics/graphics.py" | awk '{print $1}'
printf 'NVIDIA VA-API driver SHA-256: '
sha256sum "$target/catalogue/graphics/drivers/nvidia_drv_video.so" | awk '{print $1}'
sync
'@

$temporaryScript = Join-Path (
    [System.IO.Path]::GetTempPath()
) "t1os-chromium-push-$([guid]::NewGuid().ToString('N')).sh"
[System.IO.File]::WriteAllText(
    $temporaryScript,
    $copyCommand,
    [System.Text.UTF8Encoding]::new($false)
)
try {
    $wslScript = ConvertTo-WslPath $temporaryScript
    $wslArguments = @(
        '-d', 'Ubuntu', '-u', 'root', '--exec', 'sh', $wslScript, 'D:',
        $chromiumSource, $chromiumLauncher, $windowServer, $graphicsEngine,
        $mediaPolicy, $hardwareDiagnostics, $graphicsCatalogue,
        $nvidiaVaapiDriver, $audioServer, $audioClient
    )
    & wsl.exe @wslArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Scoped Chromium USB deployment failed (exit $LASTEXITCODE)."
    }
}
finally {
    if (Test-Path -LiteralPath $temporaryScript) {
        Remove-Item -LiteralPath $temporaryScript -Force
    }
}

$updated = Get-Volume -DriveLetter $driveLetter -ErrorAction Stop
if (
    [string]$updated.FileSystemType -cne 'NTFS' -or
    [string]$updated.HealthStatus -cne 'Healthy'
) {
    throw 'The T1OS USB did not remain a healthy NTFS volume.'
}
Write-Host "Scoped Chromium presentation deployment completed on $driveLetter`:"
