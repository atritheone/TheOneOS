[CmdletBinding()]
param(
    [string]$RootPath,
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $PSScriptRoot '..\common.ps1')

if ([string]::IsNullOrWhiteSpace($RootPath)) {
    $RootPath = $projectRoot
}

$RootPath = (Resolve-Path -LiteralPath $RootPath).Path
$Version = Get-T1OSCurrentVersion -ProjectRoot $projectRoot -Version $Version

$sourceFolderNames = @(
    'build software',
    'boot'
)

$sourceBasePath = Join-Path -Path $RootPath -ChildPath 'source'
$legacySourceCodePath = Join-Path -Path $RootPath -ChildPath 'legacy\source code'
$destinationBaseName = 't1os_{0}' -f $Version
$destinationPath = Join-Path -Path $legacySourceCodePath -ChildPath $destinationBaseName

if (-not (Test-Path -LiteralPath $sourceBasePath -PathType Container)) {
    throw "Source folder not found: $sourceBasePath"
}

if (-not (Test-Path -LiteralPath $legacySourceCodePath -PathType Container)) {
    New-Item -Path $legacySourceCodePath -ItemType Directory -Force | Out-Null
}

$suffix = 1
while (Test-Path -LiteralPath $destinationPath) {
    $destinationName = '{0}({1})' -f $destinationBaseName, $suffix
    $destinationPath = Join-Path -Path $legacySourceCodePath -ChildPath $destinationName
    $suffix++
}

New-Item -Path $destinationPath -ItemType Directory | Out-Null

$copiedCount = 0

foreach ($sourceFolderName in $sourceFolderNames) {
    $sourcePath = Join-Path -Path $sourceBasePath -ChildPath $sourceFolderName

    if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
        Write-Warning "Source folder not found: $sourcePath"
        continue
    }

    $files = Get-ChildItem -LiteralPath $sourcePath -Filter '*.py' -File -Recurse

    foreach ($file in $files) {
        $relativePath = $file.FullName.Substring($sourcePath.Length).TrimStart('\', '/')
        $targetPath = Join-Path -Path $destinationPath -ChildPath (
            Join-Path -Path $sourceFolderName -ChildPath $relativePath
        )
        $targetDirectory = Split-Path -Path $targetPath -Parent

        if (-not (Test-Path -LiteralPath $targetDirectory -PathType Container)) {
            New-Item -Path $targetDirectory -ItemType Directory -Force | Out-Null
        }

        Copy-Item -LiteralPath $file.FullName -Destination $targetPath
        $copiedCount++
    }
}

Write-Host "Copied $copiedCount Python file(s) to: $destinationPath"
