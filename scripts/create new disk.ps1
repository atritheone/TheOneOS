[CmdletBinding(SupportsShouldProcess)]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$environmentRoot = Join-Path $projectRoot 'environment'
. (Join-Path $PSScriptRoot 'common.ps1')
$sourcePath = Join-Path $environmentRoot 'storage.img'
$sourceExists = Test-Path -LiteralPath $sourcePath -PathType Leaf
$destinationName = if ($sourceExists) { 'storage_new.img' } else { 'storage.img' }
$destinationPath = Join-Path $environmentRoot $destinationName
$partialPath = "$destinationPath.creating"

if (-not (Test-Path -LiteralPath $environmentRoot -PathType Container)) {
    throw "Environment directory not found: $environmentRoot"
}

if (Test-Path -LiteralPath $destinationPath) {
    throw "Destination already exists; no file was changed: $destinationPath"
}

if (Test-Path -LiteralPath $partialPath) {
    throw "An unfinished image already exists: $partialPath"
}

if (Test-T1OSDiskMounted) {
    throw 'The disk is mounted. Unmount it before creating a new disk image.'
}

function ConvertTo-WslPath {
    param(
        [Parameter(Mandatory)]
        [string]$WindowsPath
    )

    $output = & wsl.exe --exec wslpath -a $WindowsPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }

    $translatedPath = ([string]($output | Select-Object -First 1)).Trim()
    if ([string]::IsNullOrWhiteSpace($translatedPath)) {
        throw "WSL returned an empty path for: $WindowsPath"
    }

    return $translatedPath
}

function Get-ExtHeaderValue {
    param(
        [Parameter(Mandatory)]
        [string[]]$Header,

        [Parameter(Mandatory)]
        [string]$Name
    )

    $line = $Header | Where-Object { $_ -match ('^' + [regex]::Escape($Name) + ':') } | Select-Object -First 1
    if (-not $line) {
        throw "Could not read '$Name' from the source filesystem."
    }

    return (($line -split ':', 2)[1]).Trim()
}

$imageSize = [long]2GB
$blockSize = 4096
$blockCount = [long]($imageSize / $blockSize)
$inodeCount = 131072
$inodeSize = 256
$reservedPercentage = 5
$filesystemFeatures = $null
$volumeLabel = $null

if ($sourceExists) {
    $imageSize = (Get-Item -LiteralPath $sourcePath).Length
    $wslSourcePath = ConvertTo-WslPath -WindowsPath $sourcePath

    $fileDescription = & wsl.exe --exec file $wslSourcePath
    if ($LASTEXITCODE -ne 0 -or $fileDescription -notmatch 'ext4 filesystem') {
        throw "The source image is not a readable ext4 filesystem: $sourcePath"
    }

    $filesystemHeaderOutput = & wsl.exe -u root --exec /usr/sbin/dumpe2fs -h $wslSourcePath 2>$null
    $dumpe2fsExitCode = $LASTEXITCODE
    $filesystemHeader = @($filesystemHeaderOutput | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($dumpe2fsExitCode -ne 0 -or -not $filesystemHeader) {
        throw "Could not inspect the source filesystem: $sourcePath"
    }

    $blockSize = [int](Get-ExtHeaderValue -Header $filesystemHeader -Name 'Block size')
    $blockCount = [long](Get-ExtHeaderValue -Header $filesystemHeader -Name 'Block count')
    $inodeCount = [int](Get-ExtHeaderValue -Header $filesystemHeader -Name 'Inode count')
    $inodeSize = [int](Get-ExtHeaderValue -Header $filesystemHeader -Name 'Inode size')
    $reservedBlockCount = [long](Get-ExtHeaderValue -Header $filesystemHeader -Name 'Reserved block count')
    $reservedPercentage = [math]::Round(($reservedBlockCount / $blockCount) * 100, 2)
    $filesystemFeatures = (Get-ExtHeaderValue -Header $filesystemHeader -Name 'Filesystem features') -replace '\s+', ','
    $volumeLabel = Get-ExtHeaderValue -Header $filesystemHeader -Name 'Filesystem volume name'
    if ($volumeLabel -eq '<none>') { $volumeLabel = $null }

    $filesystemSize = $blockCount * $blockSize
    if ($filesystemSize -ne $imageSize) {
        throw "Source filesystem geometry does not match its image size: $sourcePath"
    }
}

Write-Host "New image: $destinationPath"
Write-Host "Size: $imageSize bytes"
Write-Host "Filesystem: ext4"
Write-Host "Block size: $blockSize bytes"
Write-Host "Inodes: $inodeCount"
if ($filesystemFeatures) { Write-Host "Features: $filesystemFeatures" }

if (-not $PSCmdlet.ShouldProcess($destinationPath, 'Create a blank ext4 disk image')) {
    Write-Host 'No disk image was created.'
    exit 0
}

$wslPartialPath = ConvertTo-WslPath -WindowsPath $partialPath
$created = $false

try {
    Write-Host 'Allocating the raw image...'
    & wsl.exe --exec truncate -s $imageSize $wslPartialPath
    if ($LASTEXITCODE -ne 0) {
        throw "Could not allocate the raw image (exit code $LASTEXITCODE)."
    }

    $mkfsArguments = @(
        '-F',
        '-b', [string]$blockSize,
        '-N', [string]$inodeCount,
        '-I', [string]$inodeSize,
        '-m', [string]$reservedPercentage,
        '-U', 'random'
    )
    if ($filesystemFeatures) { $mkfsArguments += @('-O', $filesystemFeatures) }
    if ($volumeLabel) { $mkfsArguments += @('-L', $volumeLabel) }
    $mkfsArguments += $wslPartialPath

    Write-Host 'Creating the ext4 filesystem...'
    & wsl.exe -u root --exec /usr/sbin/mkfs.ext4 @mkfsArguments
    if ($LASTEXITCODE -ne 0) {
        throw "mkfs.ext4 failed with exit code $LASTEXITCODE."
    }

    $newDescription = & wsl.exe --exec file $wslPartialPath
    if ($LASTEXITCODE -ne 0 -or $newDescription -notmatch 'ext4 filesystem') {
        throw 'The new image failed filesystem verification.'
    }

    Move-Item -LiteralPath $partialPath -Destination $destinationPath
    $created = $true
}
finally {
    if (-not $created -and (Test-Path -LiteralPath $partialPath)) {
        Remove-Item -LiteralPath $partialPath -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Created new disk image: $destinationPath"
exit 0
