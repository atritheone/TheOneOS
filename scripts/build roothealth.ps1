[CmdletBinding()]
param([switch]$Clean)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$engineSource = Join-Path $projectRoot 'development\roothealth\engine'
$outputDirectory = Join-Path $projectRoot 'environment\hardware\tools'
$binaryPath = Join-Path $outputDirectory 'roothealth'
$metadataPath = Join-Path $outputDirectory 'roothealth.json'
$licensePath = Join-Path $outputDirectory 'roothealth.COPYING'
$sourceBundlePath = Join-Path $outputDirectory 'roothealth-source.tar.gz'
$linkedInputsPath = Join-Path $outputDirectory 'roothealth-linked-inputs.manifest'
$obsoleteArchivePath = Join-Path $outputDirectory 'roothealth-upstream.tar.gz'
$contractPath = Join-Path $projectRoot 'source\entry\roothealth\REPAIR-CONTRACT.md'
$rolloutPath = Join-Path $projectRoot 'source\entry\roothealth\ROLLOUT-v0.5.1.md'
$qualificationPath = Join-Path $projectRoot 'source\entry\roothealth\QUALIFICATION-v0.5.1.md'
$failureTaxonomyPath = Join-Path $projectRoot 'source\entry\roothealth\FAILURE-TAXONOMY-v1.md'
$checkerVersion = '0.5.1'
$upstreamCommit = 'd4f481df6926557f7b18b471a43313652dec6f7e'

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)
    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Ubuntu WSL is required to build roothealth.'
}
foreach ($required in @(
    (Join-Path $engineSource 'configure.ac'),
    (Join-Path $engineSource 'autogen.sh'),
    (Join-Path $engineSource 'COPYING'),
    (Join-Path $engineSource 'src\roothealth_repair_main.c'),
    $contractPath,
    $rolloutPath,
    $qualificationPath,
    $failureTaxonomyPath,
    $PSCommandPath
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "RootHealth build input is missing: $required"
    }
}

New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
if ($Clean) {
    foreach ($generated in @(
        $binaryPath, $metadataPath, $licensePath, $sourceBundlePath,
        $obsoleteArchivePath, $linkedInputsPath
    )) {
        if (Test-Path -LiteralPath $generated) {
            Remove-Item -LiteralPath $generated -Force
        }
    }
}

$wslSource = ConvertTo-WslPath $engineSource
$wslBinary = ConvertTo-WslPath $binaryPath
$wslLicense = ConvertTo-WslPath $licensePath
$wslBundle = ConvertTo-WslPath $sourceBundlePath
$wslLinkedInputs = ConvertTo-WslPath $linkedInputsPath
$wslRecipe = ConvertTo-WslPath $PSCommandPath
$wslContract = ConvertTo-WslPath $contractPath
$wslRollout = ConvertTo-WslPath $rolloutPath
$wslQualification = ConvertTo-WslPath $qualificationPath
$wslFailureTaxonomy = ConvertTo-WslPath $failureTaxonomyPath

$buildCommand = @'
set -euo pipefail
source_tree=$1
output=$2
license_output=$3
bundle_output=$4
linked_inputs_output=$5
recipe=$6
contract=$7
rollout=$8
qualification=$9
failure_taxonomy=${10}

export LC_ALL=C SOURCE_DATE_EPOCH=0
umask 022
for command_name in autoreconf make gcc strip readelf file tar gzip sha256sum find cp; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "Missing RootHealth build command: $command_name" >&2
        exit 127
    }
done

work=$(mktemp -d /var/tmp/roothealth-production.XXXXXX)
case "$work" in /var/tmp/roothealth-production.*) ;; *) exit 1 ;; esac
output_tmp="${output}.building"
license_tmp="${license_output}.building"
bundle_tmp="${bundle_output}.building"
linked_inputs_tmp="${linked_inputs_output}.building"
cleanup() {
    rm -f -- "$output_tmp" "$license_tmp" "$bundle_tmp" "$linked_inputs_tmp"
    case "$work" in /var/tmp/roothealth-production.*) rm -rf -- "$work" ;; esac
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

mkdir -p "$work/build" "$work/bundle/roothealth-source"
cp -a -- "$source_tree/." "$work/build/"
cp -a -- "$source_tree/." "$work/bundle/roothealth-source/engine/"
for tree in "$work/build" "$work/bundle/roothealth-source/engine"; do
    if [ -f "$tree/Makefile" ]; then
        make -C "$tree" distclean >/dev/null 2>&1 || true
    fi
    find "$tree" -type d \( -name .deps -o -name .libs \) -prune -exec rm -rf -- {} +
    find "$tree" -type f \( -name '*.o' -o -name '*.lo' -o -name '*.la' -o -name '*.pyc' \) -delete
done

cd "$work/build"
autoreconf -fi >/dev/null
CFLAGS='-O2 -g0 -fstack-protector-strong -fPIE -Wall -Wno-address-of-packed-member' \
CPPFLAGS='-D_FORTIFY_SOURCE=3' \
LDFLAGS="-Wl,-z,relro,-z,now,-pie,-Map,$work/roothealth.link.map" \
    ./configure --disable-library --disable-mtab --disable-ldconfig >/dev/null
make -C libntfs -j"$(nproc)" libntfs.la >/dev/null
make -C src -j"$(nproc)" roothealth \
    CFLAGS='-O2 -g0 -fstack-protector-strong -fPIE -Wall -Wextra -Werror -Wno-address-of-packed-member -Wno-format-nonliteral' >/dev/null

src/roothealth --version | grep -Fxq 'roothealth v0.5.1 (ntfs-next d4f481d)'
src/roothealth --help | grep -Eq '(^|[[:space:]])--repair([=[:space:]]|$)'
src/roothealth --help | grep -Eq '(^|[[:space:]])--preflight([=[:space:]]|$)'
src/roothealth --help | grep -Eq '(^|[[:space:]])--boot-repair([=[:space:]]|$)'
src/roothealth --help | grep -Eq '(^|[[:space:]])--expected-journal-record([=[:space:]]|$)'
strip --strip-all src/roothealth
file src/roothealth | grep -Fq 'ELF 64-bit LSB pie executable'
readelf -W -l src/roothealth | grep -Eq 'GNU_STACK[[:space:]].* RW '
readelf -W -l src/roothealth | grep -Fq 'GNU_RELRO'
readelf -W -d src/roothealth | grep -Eq 'FLAGS.*BIND_NOW'
needed=$(readelf -W -d src/roothealth | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p')
[ "$needed" = libc.so.6 ] || {
    echo "Unexpected RootHealth runtime dependencies: $needed" >&2
    exit 1
}

extract_c_sources() {
    awk -v variable="$1" -v prefix="$2" '
        $0 ~ "^" variable "[[:space:]]*=" { active=1 }
        active {
            continued = ($0 ~ /\\[[:space:]]*$/)
            line=$0
            sub(/^[^=]*=/, "", line)
            gsub(/\\/, "", line)
            count=split(line, fields, /[[:space:]]+/)
            for (field_index=1; field_index<=count; field_index++)
                if (fields[field_index] ~ /^[A-Za-z0-9_][A-Za-z0-9_.-]*\.c$/)
                    print prefix "/" fields[field_index]
            if (!continued)
                exit
        }
    ' "$3"
}
{
    echo '# roothealth-linked-inputs-v1 complete-link-inputs=true'
    {
        extract_c_sources roothealth_SOURCES src src/Makefile.am
        extract_c_sources libntfs_la_SOURCES libntfs libntfs/Makefile.am
        echo libntfs/unix_io.c
    } | LC_ALL=C sort -u
} > "$linked_inputs_tmp"
while IFS= read -r linked_source; do
    case "$linked_source" in \#*|'') continue ;; esac
    [ -f "$linked_source" ] || {
        echo "Linked-input manifest names a missing source: $linked_source" >&2
        exit 1
    }
done < "$linked_inputs_tmp"

cp -- src/roothealth "$output_tmp"
cp -- COPYING "$license_tmp"
chmod 0755 "$output_tmp"
chmod 0644 "$license_tmp"
cp -- "$recipe" "$work/bundle/roothealth-source/build-roothealth.ps1"
mkdir -p "$work/bundle/roothealth-source/resource"
cp -- "$contract" "$work/bundle/roothealth-source/resource/REPAIR-CONTRACT.md"
cp -- "$rollout" "$work/bundle/roothealth-source/resource/ROLLOUT-v0.5.1.md"
cp -- "$qualification" "$work/bundle/roothealth-source/resource/QUALIFICATION-v0.5.1.md"
cp -- "$failure_taxonomy" "$work/bundle/roothealth-source/resource/FAILURE-TAXONOMY-v1.md"
cp -- "$work/roothealth.link.map" "$work/bundle/roothealth-source/roothealth.link.map"
(
    cd "$work/bundle/roothealth-source"
    find . -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)
find "$work/bundle/roothealth-source" -type d -exec chmod 0755 {} +
find "$work/bundle/roothealth-source" -type f -exec chmod 0644 {} +
find "$work/bundle/roothealth-source" -depth -exec touch -h -d '@0' {} +
tar --sort=name --format=gnu --mtime='@0' --owner=0 --group=0 --numeric-owner \
    -C "$work/bundle" -cf - roothealth-source | gzip -n -9 > "$bundle_tmp"
chmod 0644 "$bundle_tmp"

mv -f -- "$output_tmp" "$output"
mv -f -- "$license_tmp" "$license_output"
mv -f -- "$bundle_tmp" "$bundle_output"
mv -f -- "$linked_inputs_tmp" "$linked_inputs_output"
sha256sum "$output" "$license_output" "$bundle_output" "$linked_inputs_output"
'@

$normalizedBuildCommand = $buildCommand.Replace("`r", '') + "`n# end"
$normalizedBuildCommand | & wsl.exe -d Ubuntu -u root --exec bash -s -- `
    $wslSource $wslBinary $wslLicense $wslBundle $wslLinkedInputs $wslRecipe $wslContract $wslRollout $wslQualification $wslFailureTaxonomy
if ($LASTEXITCODE -ne 0) {
    throw "RootHealth production build failed (exit code $LASTEXITCODE)."
}

$gccVersion = (& wsl.exe -d Ubuntu --exec gcc -dumpfullversion | Select-Object -First 1).Trim()
if ($LASTEXITCODE -ne 0 -or -not $gccVersion) {
    throw 'Could not record the RootHealth compiler version.'
}
$metadata = [ordered]@{
    format = 2
    product = 'roothealth'
    version = $checkerVersion
    target = 'x86_64-linux-initramfs'
    mode = 'qualified-repair'
    upstream = [ordered]@{ project = 'ntfsprogs-plus/ntfsprogs-plus'; commit = $upstreamCommit }
    build = [ordered]@{
        compiler = "gcc $gccVersion"
        source = 'development/roothealth/engine'
        configure = @('--disable-library', '--disable-mtab', '--disable-ldconfig')
        runtime_dependencies = @('libc.so.6')
        hardening = @('PIE', 'NX-stack', 'RELRO', 'BIND_NOW', 'FORTIFY_SOURCE=3')
    }
    enabled_policies = @(
        'operations-registry-resident-i30-v1',
        'mft-bitmap-full-ledger-v1',
        'index-bitmap-set-only-v1',
        'cluster-bitmap-exhaustive-v1',
        'native-log-replay-v1.1-v2-bounded'
    )
    recovery_verified_actions = @(5, 6, 11, 13, 22, 23, 24, 25)
    outputs = [ordered]@{
        binary = [ordered]@{
            path = 'environment/hardware/tools/roothealth'
            bytes = (Get-Item -LiteralPath $binaryPath).Length
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $binaryPath).Hash.ToLowerInvariant()
        }
        license = [ordered]@{
            path = 'environment/hardware/tools/roothealth.COPYING'
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $licensePath).Hash.ToLowerInvariant()
        }
        corresponding_source = [ordered]@{
            path = 'environment/hardware/tools/roothealth-source.tar.gz'
            bytes = (Get-Item -LiteralPath $sourceBundlePath).Length
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceBundlePath).Hash.ToLowerInvariant()
            kind = 'deterministic-complete-source-bundle'
        }
        linked_inputs = [ordered]@{
            path = 'environment/hardware/tools/roothealth-linked-inputs.manifest'
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $linkedInputsPath).Hash.ToLowerInvariant()
        }
    }
}
$metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $metadataPath -Encoding utf8
Write-Host "Built RootHealth v${checkerVersion}: $binaryPath"
