[CmdletBinding()]
param(
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$catalogueTarget = Join-Path $projectRoot 'source\catalogue\image'
$developmentRoot = Join-Path $projectRoot 'development\image catalogue'
$cacheRoot = Join-Path $developmentRoot 'cache'
$stageRoot = Join-Path $developmentRoot 'stage'
$extractRoot = Join-Path $stageRoot 'extract'
$catalogueStage = Join-Path $stageRoot 'catalogue'
$pillowVersion = '12.3.0'
$wheelName = 'pillow-12.3.0-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl'
$wheelUrl = "https://files.pythonhosted.org/packages/f7/62/de5bdd77d935331f4f802edc11e4d82950f642caad6cb2f949837b8560e2/$wheelName"
$wheelSha256 = '0847a763afefb695bc912d7c131e7e0632d4edc1d8698f58ddabec8e46b8b6d3'
$wheelPath = Join-Path $cacheRoot $wheelName

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

    return ([string]($output | Select-Object -First 1)).Trim()
}

foreach ($path in @($catalogueTarget, $developmentRoot, $cacheRoot, $stageRoot, $extractRoot, $catalogueStage)) {
    Assert-ProjectPath -Path $path
}

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Required command not found: wsl.exe'
}

if ($Clean -and (Test-Path -LiteralPath $developmentRoot)) {
    Remove-Item -LiteralPath $developmentRoot -Recurse -Force
}

if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $cacheRoot -Force | Out-Null
New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
New-Item -ItemType Directory -Path $catalogueStage -Force | Out-Null

if (-not (Test-Path -LiteralPath $wheelPath -PathType Leaf)) {
    $partialPath = "$wheelPath.partial"
    Invoke-WebRequest -Uri $wheelUrl -OutFile $partialPath
    Move-Item -LiteralPath $partialPath -Destination $wheelPath
}

$actualHash = (Get-FileHash -LiteralPath $wheelPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -cne $wheelSha256) {
    throw "Pillow wheel SHA-256 mismatch. Expected $wheelSha256, received $actualHash."
}

$archivePath = Join-Path $stageRoot 'pillow.zip'
Copy-Item -LiteralPath $wheelPath -Destination $archivePath
Expand-Archive -LiteralPath $archivePath -DestinationPath $extractRoot

$pilSource = Join-Path $extractRoot 'PIL'
$librariesSource = Join-Path $extractRoot 'pillow.libs'
$metadataSource = Get-ChildItem -LiteralPath $extractRoot -Directory -Filter 'pillow-*.dist-info' | Select-Object -First 1

if (-not (Test-Path -LiteralPath $pilSource -PathType Container)) {
    throw 'Pillow wheel does not contain the PIL package.'
}

if (-not (Test-Path -LiteralPath $librariesSource -PathType Container)) {
    throw 'Pillow wheel does not contain its bundled native libraries.'
}

if (-not $metadataSource) {
    throw 'Pillow wheel metadata was not found.'
}

Copy-Item -LiteralPath $pilSource -Destination (Join-Path $catalogueStage 'PIL') -Recurse
Copy-Item -LiteralPath $librariesSource -Destination (Join-Path $catalogueStage 'pillow.libs') -Recurse

$licenceSource = Get-ChildItem -LiteralPath $metadataSource.FullName -File -Recurse | Where-Object Name -EQ 'LICENSE' | Select-Object -First 1
if (-not $licenceSource) {
    throw 'Pillow licence was not found in the wheel.'
}

Copy-Item -LiteralPath $licenceSource.FullName -Destination (Join-Path $catalogueStage 'licence Pillow.txt')

$versionText = @(
    "Pillow $pillowVersion"
    "Wheel: $wheelName"
    "Source: $wheelUrl"
    "SHA-256: $wheelSha256"
) -join [Environment]::NewLine
Set-Content -LiteralPath (Join-Path $catalogueStage 'version.txt') -Value $versionText -Encoding utf8NoBOM

$wslCatalogueStage = ConvertTo-WslPath -WindowsPath $catalogueStage
$patchCommand = @'
set -eu

root=$1
runpath='/the one/catalogue/image/pillow.libs:/the one/catalogue/image:/the one/catalogue/python'

for command_name in find readelf patchelf; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "Required WSL build command not found: $command_name" >&2
        exit 127
    }
done

find "$root" -type l -print -quit | grep -q . && {
    echo 'Pillow catalogue contains a symbolic link.' >&2
    exit 1
}

find "$root/PIL" "$root/pillow.libs" -type f \( -name '*.so' -o -name '*.so.*' \) -print0 |
while IFS= read -r -d '' library; do
    machine=$(readelf -h "$library" | sed -n 's/^[[:space:]]*Machine:[[:space:]]*//p')
    case "$machine" in
        *X86-64*) ;;
        *) echo "Unexpected image library architecture in $library: $machine" >&2; exit 1 ;;
    esac

    for merged_library in libpthread.so.0 libdl.so.2 librt.so.1; do
        if patchelf --print-needed "$library" | grep -Fx "$merged_library" >/dev/null; then
            patchelf --replace-needed "$merged_library" libc.so.6 "$library"
        fi
    done

    patchelf --set-rpath "$runpath" "$library"
    readelf -d "$library" | grep -F "$runpath" >/dev/null
done
'@

& wsl.exe -u root --exec bash -c $patchCommand bash $wslCatalogueStage
if ($LASTEXITCODE -ne 0) {
    throw 'Pillow native library validation or runpath patching failed.'
}

$files = @()
foreach ($file in Get-ChildItem -LiteralPath $catalogueStage -File -Recurse | Sort-Object FullName) {
    $relative = [System.IO.Path]::GetRelativePath($catalogueStage, $file.FullName).Replace('\', '/')
    $files += [ordered]@{
        path = $relative
        size = $file.Length
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

$manifest = [ordered]@{
    format = 1
    component = 'image'
    package = 'Pillow'
    version = $pillowVersion
    python = 'cp313'
    architecture = 'x86_64'
    wheel = $wheelName
    source = $wheelUrl
    source_sha256 = $wheelSha256
    runtime_path = '/the one/catalogue/image'
    files = $files
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $catalogueStage 'catalogue.json') -Encoding utf8NoBOM

Remove-Item -LiteralPath (Join-Path $catalogueStage 'catalogue.json') -Force
Remove-Item -LiteralPath (Join-Path $catalogueStage 'licence Pillow.txt') -Force
Remove-Item -LiteralPath (Join-Path $catalogueStage 'version.txt') -Force
Get-ChildItem -LiteralPath (Join-Path $catalogueStage 'PIL') -File -Recurse -Filter '*.pyi' | Remove-Item -Force
Remove-Item -LiteralPath (Join-Path $catalogueStage 'PIL\py.typed') -Force

if (Test-Path -LiteralPath $catalogueTarget) {
    Remove-Item -LiteralPath $catalogueTarget -Recurse -Force
}

Copy-Item -LiteralPath $catalogueStage -Destination $catalogueTarget -Recurse

$installedCount = @(Get-ChildItem -LiteralPath $catalogueTarget -File -Recurse).Count
Write-Host "Pillow $pillowVersion image catalogue built successfully with $installedCount file(s)."
Write-Host "Runtime destination: /the one/catalogue/image"
