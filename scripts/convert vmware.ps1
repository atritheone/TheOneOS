# convert vmware.ps1

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$environmentRoot = Join-Path $projectRoot 'environment'
. (Join-Path $PSScriptRoot 'common.ps1')
Set-Location -LiteralPath $environmentRoot

$source = Join-Path $environmentRoot "storage.img"
$vmdk = Join-Path $environmentRoot "t1os-root.vmdk"

if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "storage.img not found: $source"
}

if (Test-T1OSDiskMounted) {
    throw 'The disk is mounted. Unmount it before conversion.'
}

Assert-T1OSFilesystemHealthy -ImagePath $source -Operation 'converting it for VMware'

$qemuImg = Get-Command qemu-img -ErrorAction SilentlyContinue
if (-not $qemuImg) {
    $qemuImgDefault = 'C:\Program Files\qemu\qemu-img.exe'
    if (Test-Path -LiteralPath $qemuImgDefault -PathType Leaf) {
        $qemuImgPath = $qemuImgDefault
    }
    else {
        throw 'qemu-img was not found. Install QEMU or add qemu-img to PATH.'
    }
}
else {
    $qemuImgPath = $qemuImg.Source
}

$temporaryVmdk = Join-Path $environmentRoot ('.t1os-root-{0}.vmdk' -f [guid]::NewGuid().ToString('N'))

try {
    Write-Host 'Converting storage.img to a replacement t1os-root.vmdk...'
    & $qemuImgPath convert -f raw -O vmdk $source $temporaryVmdk
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $temporaryVmdk -PathType Leaf)) {
        throw "qemu-img failed with exit code $LASTEXITCODE."
    }

    if (Test-Path -LiteralPath $vmdk -PathType Leaf) {
        Install-T1OSReplacementFile -SourcePath $temporaryVmdk -DestinationPath $vmdk
    }
    else {
        Move-Item -LiteralPath $temporaryVmdk -Destination $vmdk
    }
    $temporaryVmdk = $null

    Write-Host "VMware disk created: $vmdk"
    exit 0
}
finally {
    if ($null -ne $temporaryVmdk -and (Test-Path -LiteralPath $temporaryVmdk)) {
        Remove-Item -LiteralPath $temporaryVmdk -Force -ErrorAction SilentlyContinue
    }
}
