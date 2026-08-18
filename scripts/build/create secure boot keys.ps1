[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)]
    [string]$OutputDirectory,

    [ValidatePattern('^[A-Za-z0-9 ._-]{1,64}$')]
    [string]$CommonName = 'T1OS Secure Boot',

    [ValidateRange(365, 3650)]
    [int]$ValidityDays = 3650
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$projectRootFull = [System.IO.Path]::GetFullPath($projectRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
$projectPrefix = $projectRootFull + [System.IO.Path]::DirectorySeparatorChar

if ($OutputDirectory.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Secure Boot private keys must be generated outside the T1OS project.'
}
if (Test-Path -LiteralPath $OutputDirectory) {
    $existing = @(Get-ChildItem -LiteralPath $OutputDirectory -Force)
    if ($existing.Count -gt 0) {
        throw "Secure Boot output directory is not empty: $OutputDirectory"
    }
}

if (-not $PSCmdlet.ShouldProcess($OutputDirectory, 'Generate a new T1OS Secure Boot private key and certificate')) {
    return
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$privateKey = Join-Path $OutputDirectory 't1os-secure-boot.key.pem'
$certificate = Join-Path $OutputDirectory 't1os-secure-boot.cert.pem'
$certificateDer = Join-Path $OutputDirectory 't1os-secure-boot.cert.der'

$wslDirectoryOutput = & wsl.exe -d Ubuntu --exec wslpath -a $OutputDirectory
$wslPathExitCode = $LASTEXITCODE
$wslDirectory = ([string]($wslDirectoryOutput | Select-Object -First 1)).Trim()
if ($wslPathExitCode -ne 0 -or -not $wslDirectory) {
    throw 'Could not translate the Secure Boot key directory for WSL.'
}

$generateCommand = @'
set -euo pipefail
directory=$1
common_name=$2
validity_days=$3
private_key="$directory/t1os-secure-boot.key.pem"
certificate="$directory/t1os-secure-boot.cert.pem"
certificate_der="$directory/t1os-secure-boot.cert.der"

umask 077
openssl req \
    -new \
    -x509 \
    -newkey rsa:4096 \
    -sha256 \
    -nodes \
    -days "$validity_days" \
    -subj "/CN=$common_name/" \
    -keyout "$private_key" \
    -out "$certificate"
openssl x509 -in "$certificate" -outform DER -out "$certificate_der"
openssl x509 -in "$certificate" -noout -fingerprint -sha256 -subject -dates
test -s "$private_key"
test -s "$certificate"
test -s "$certificate_der"
'@

& wsl.exe -d Ubuntu -u root --exec bash -c $generateCommand bash $wslDirectory $CommonName $ValidityDays
if ($LASTEXITCODE -ne 0) {
    throw "Secure Boot key generation failed (exit code $LASTEXITCODE)."
}

Write-Host "Private key: $privateKey"
Write-Host "Certificate: $certificate"
Write-Host "Firmware enrollment certificate: $certificateDer"
Write-Host 'Keep the private key offline and backed up. Enroll only the DER certificate in MSI Secure Boot Custom Mode.'
