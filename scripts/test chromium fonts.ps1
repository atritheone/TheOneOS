[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$runtime = Join-Path $projectRoot 'source\software\chromium'
$configuration = Join-Path $runtime 'resources\fontconfig-configuration\fonts.conf'

if (-not (Test-Path -LiteralPath $configuration -PathType Leaf)) {
    throw "Chromium font configuration is missing: $configuration"
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
$diagnostic = @'
set -euo pipefail
runtime=$1

cleanup() {
    set +e
    mountpoint -q "/the one/software/chromium" &&
        umount "/the one/software/chromium"
    rm -rf -- "/the one/settings/chromium"
    rmdir "/the one/software/chromium" "/the one/software" "/the one" \
        2>/dev/null || true
    rm -rf -- /.ephemeral/chromium
    rmdir /.ephemeral 2>/dev/null || true
}
trap cleanup EXIT

command -v fc-match >/dev/null
[ ! -e "/the one/software/chromium" ]
[ ! -e /.ephemeral/chromium ]
mkdir -p "/the one/software/chromium" "/the one/settings/chromium/font-cache"
mount --bind "$runtime" "/the one/software/chromium"
config="/the one/software/chromium/resources/fontconfig-configuration/fonts.conf"

match() {
    env \
        LD_LIBRARY_PATH="/the one/software/chromium/libraries" \
        FONTCONFIG_PATH="/the one/software/chromium/resources/fontconfig-configuration" \
        FONTCONFIG_FILE="$config" \
        fc-match -f '%{family[0]}' "$1"
}

[ "$(match sans-serif)" = "Noto Sans" ]
[ "$(match serif)" = "Noto Serif" ]
[ "$(match monospace)" = "Noto Sans Mono" ]
[ "$(match Arial)" = "Arimo" ]
[ "$(match Helvetica)" = "Arimo" ]
[ "$(match Roboto)" = "Noto Sans" ]
[ "$(match "Times New Roman")" = "Tinos" ]
[ "$(match "Courier New")" = "Cousine" ]
[ "$(match system-ui)" = "Noto Sans" ]
[ "$(match "Unknown Browser UI")" = "Noto Sans" ]

echo "sans-serif=$(match sans-serif)"
echo "serif=$(match serif)"
echo "monospace=$(match monospace)"
echo "Arial=$(match Arial)"
echo "Roboto=$(match Roboto)"
echo "Times New Roman=$(match "Times New Roman")"
echo "Courier New=$(match "Courier New")"
echo "unknown=$(match "Unknown Browser UI")"
'@

# PowerShell's native pipeline supplies the final newline; keep any appended
# carriage return inside a shell comment.
$normalized = $diagnostic.Replace("`r", '') + "`n# end"
$normalized | wsl.exe -d Ubuntu -u root --exec bash -s -- $wslRuntime
if ($LASTEXITCODE -ne 0) {
    throw "Chromium font diagnostic failed (exit code $LASTEXITCODE)."
}

Write-Host 'Chromium font diagnostic passed.'
