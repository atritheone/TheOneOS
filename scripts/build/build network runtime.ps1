[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$softwareDestination = Join-Path $projectRoot 'source\software\network'
$catalogueDestination = Join-Path $projectRoot 'source\catalogue\network'
$settingsDestination = Join-Path $projectRoot 'source\settings\network'
$version = '2.11'
$archiveSha256 = '912ea06f74e30a8e36fbb68064d6cdff218d8d591db0fc5d75dee6c81ac7fc0a'

New-Item -ItemType Directory -Path $softwareDestination -Force | Out-Null
New-Item -ItemType Directory -Path $catalogueDestination -Force | Out-Null
New-Item -ItemType Directory -Path $settingsDestination -Force | Out-Null

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

$wslSoftwareDestination = ConvertTo-WslPath -WindowsPath $softwareDestination
$wslCatalogueDestination = ConvertTo-WslPath -WindowsPath $catalogueDestination
$wslSettingsDestination = ConvertTo-WslPath -WindowsPath $settingsDestination

$build = @'
set -euo pipefail
version=$1
expected_sha=$2
software_destination=$3
catalogue_destination=$4
settings_destination=$5
cache=/var/tmp/t1os-network-cache
work=/var/tmp/t1os-network-work
archive="$cache/wpa_supplicant-$version.tar.gz"
source="$work/wpa_supplicant-$version"
software_stage="$work/software"
catalogue_stage="$work/catalogue"

for command_name in curl sha256sum tar make gcc pkg-config patchelf readelf strings strip rsync python3; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "Required network runtime build command is unavailable: $command_name" >&2
        exit 127
    }
done

pkg-config --exists libnl-3.0 libnl-genl-3.0 || {
    echo 'libnl-3-dev and libnl-genl-3-dev are required.' >&2
    exit 127
}

mkdir -p "$cache"
rm -rf -- "$work"
mkdir -p "$work" "$software_stage" "$catalogue_stage"

if [ ! -s "$archive" ] || [ "$(sha256sum "$archive" | awk '{print $1}')" != "$expected_sha" ]; then
    rm -f -- "$archive"
    curl --fail --location --retry 5 --connect-timeout 30 \
        "https://w1.fi/releases/wpa_supplicant-$version.tar.gz" \
        --output "$archive"
fi

actual_sha=$(sha256sum "$archive" | awk '{print $1}')
[ "$actual_sha" = "$expected_sha" ] || {
    echo "wpa_supplicant archive hash mismatch: $actual_sha" >&2
    exit 1
}

tar -xzf "$archive" -C "$work"

python3 - "$source" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
replacements = (
    ('/var/run/wpa_supplicant', '/.ephemeral/network/control'),
    ('/var/run/wpa_priv', '/.ephemeral/network/private'),
    ('/etc/ssl/certs/ca-certificates.crt', '/the one/settings/network/cacerts.pem'),
    ('/etc/tnc_config', '/the one/settings/network/tnc.conf'),
    ('/etc/', '/the one/settings/network/'),
    ('/usr/bin/x-www-browser', '/the one/software/chromium/chromium'),
    ('/dev/urandom', '/the one/drivers/nodes/urandom'),
    ('/dev/random', '/the one/drivers/nodes/random'),
    ('/dev/null', '/the one/drivers/nodes/null'),
    ('/dev/rfkill', '/the one/drivers/nodes/rfkill'),
    ('/proc/', '/the one/drivers/processes/'),
    ('/sys/', '/the one/drivers/state/'),
    ('/tmp', '/.ephemeral/network'),
)

for path in root.rglob('*'):
    if not path.is_file() or path.suffix not in {'.c', '.h'}:
        continue
    text = path.read_text(encoding='utf-8', errors='surrogateescape')
    changed = text
    for old, new in replacements:
        changed = changed.replace(old, new)
    if changed != text:
        path.write_text(changed, encoding='utf-8', errors='surrogateescape')

rfkill = root / 'src' / 'drivers' / 'rfkill.c'
text = rfkill.read_text(encoding='utf-8')
text = text.replace('char buf[24 + IFNAMSIZ + 1];', 'char buf[256];')
text = text.replace('char buf2[31 + 11 + 1];', 'char buf2[256];')
rfkill.write_text(text, encoding='utf-8')
PY

cat > "$source/wpa_supplicant/.config" <<'EOF'
CONFIG_DRIVER_NL80211=y
CONFIG_LIBNL32=y
CONFIG_CTRL_IFACE=y
CONFIG_BACKEND=file
CONFIG_TLS=openssl
CONFIG_SAE=y
CONFIG_IEEE80211W=y
CONFIG_IEEE80211R=y
CONFIG_OWE=y
CONFIG_NO_CONFIG_BLOBS=y
CFLAGS += -O2 -fPIE -fstack-protector-strong -fstack-clash-protection -fcf-protection=full -fno-plt -fno-common -D_FORTIFY_SOURCE=3 -Wformat -Wformat-security -Werror=format-security
LDFLAGS += -pie -Wl,-z,relro,-z,now,-z,noexecstack,--as-needed
EOF

make -C "$source/wpa_supplicant" -j"$(nproc)" wpa_supplicant
"$source/wpa_supplicant/wpa_supplicant" -v

cp -- "$source/wpa_supplicant/wpa_supplicant" "$software_stage/wireless-engine"

ldd "$software_stage/wireless-engine" | awk '
    /=> \// { print $3 }
    /^\// { print $1 }
' | sort -u | while IFS= read -r library; do
    [ -f "$library" ] || continue
    cp -L -- "$library" "$catalogue_stage/$(basename "$library")"
done

loader=$(ldd "$software_stage/wireless-engine" | awk '/ld-linux/ { print $1; exit }')
if [ -z "$loader" ] || [ ! -f "$loader" ]; then
    loader=/lib64/ld-linux-x86-64.so.2
fi
cp -L -- "$loader" "$catalogue_stage/ld-linux-x86-64.so.2"

patchelf \
    --set-interpreter '/the one/catalogue/network/ld-linux-x86-64.so.2' \
    --set-rpath '/the one/catalogue/network' \
    "$software_stage/wireless-engine"
strip --strip-unneeded "$software_stage/wireless-engine"

for forbidden in /dev/ /proc/ /sys/ /etc/ /usr/ /run/ /var/ /tmp/; do
    if strings "$software_stage/wireless-engine" | grep -F "$forbidden" >/dev/null; then
        echo "The wireless engine still contains forbidden runtime path $forbidden" >&2
        strings "$software_stage/wireless-engine" | grep -F "$forbidden" | head -n 10 >&2
        exit 1
    fi
done

readelf -l "$software_stage/wireless-engine" | grep -F '/the one/catalogue/network/ld-linux-x86-64.so.2' >/dev/null
readelf -d "$software_stage/wireless-engine" | grep -F '/the one/catalogue/network' >/dev/null
readelf -h "$software_stage/wireless-engine" | grep -Eq 'Type:[[:space:]]+DYN'
readelf -lW "$software_stage/wireless-engine" | grep -F 'GNU_RELRO' >/dev/null
readelf -lW "$software_stage/wireless-engine" | grep -E 'GNU_STACK.*RW[[:space:]]' >/dev/null
if readelf -lW "$software_stage/wireless-engine" | grep -E 'GNU_STACK.*RWE' >/dev/null; then
    echo 'The wireless engine has an executable stack.' >&2
    exit 1
fi
readelf -dW "$software_stage/wireless-engine" | grep -F 'BIND_NOW' >/dev/null

rsync -a --delete -- "$software_stage/" "$software_destination/"
rsync -a --delete -- "$catalogue_stage/" "$catalogue_destination/"
test -s /etc/ssl/certs/ca-certificates.crt
cp -- /etc/ssl/certs/ca-certificates.crt "$settings_destination/cacerts.pem"
chmod 0644 "$settings_destination/cacerts.pem"
sha256sum "$software_destination/wireless-engine"
'@

& wsl.exe -d Ubuntu -u root --exec bash -c $build bash $version $archiveSha256 $wslSoftwareDestination $wslCatalogueDestination $wslSettingsDestination
if ($LASTEXITCODE -ne 0) {
    throw "Network runtime build failed (exit code $LASTEXITCODE)."
}

Write-Host 'T1OS network runtime completed successfully.'
Write-Host "Software: $softwareDestination"
Write-Host "Catalogue: $catalogueDestination"
