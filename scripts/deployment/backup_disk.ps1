[CmdletBinding()]
param(
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$environmentRoot = Join-Path $projectRoot 'environment\software'
. (Join-Path $PSScriptRoot '..\common.ps1')
$Version = Get-T1OSCurrentVersion -ProjectRoot $projectRoot -Version $Version
Set-Location -LiteralPath $environmentRoot

$sourcePath = Join-Path $environmentRoot 'storage.img'
$backupDirectory = Join-Path $environmentRoot 'backups'
$backupName = 'storage_{0}_{1}.img' -f (Get-Date -Format 'yyyyMMdd_HHmmss'), $Version
$destinationPath = Join-Path $backupDirectory $backupName

if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
    throw "Disk image not found: $sourcePath"
}

if (Test-T1OSDiskMounted) {
    throw 'The disk is mounted. Unmount it before making a backup.'
}

New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
Write-Host "Backing up storage.img to $destinationPath..."

$source = $null
$destination = $null
$copyError = $null
try {
    $source = [System.IO.File]::OpenRead($sourcePath)
    $destination = [System.IO.File]::Create($destinationPath)
    $buffer = New-Object byte[] (8MB)
    $copied = [long]0
    $nextProgress = 10

    while (($read = $source.Read($buffer, 0, $buffer.Length)) -gt 0) {
        $destination.Write($buffer, 0, $read)
        $copied += $read
        $percent = [math]::Floor(($copied / $source.Length) * 100)
        if ($percent -ge $nextProgress) {
            Write-Host "Backup progress: $percent%"
            $nextProgress += 10
        }
    }
}
catch {
    $copyError = $_
}
finally {
    if ($destination) { $destination.Dispose() }
    if ($source) { $source.Dispose() }
}

if ($copyError) {
    if (Test-Path -LiteralPath $destinationPath) {
        Remove-Item -LiteralPath $destinationPath -Force -ErrorAction SilentlyContinue
    }
    throw $copyError
}

Write-Host "Disk backup completed: $destinationPath"
exit 0
