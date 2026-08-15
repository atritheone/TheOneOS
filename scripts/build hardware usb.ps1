[CmdletBinding()]
param(
    [switch]$PlanOnly,

    [switch]$SkipQemu,

    [switch]$ArtifactsOnly,

    [ValidatePattern('^[0-9A-Fa-f]{8}$')]
    [string]$PreferredAudioCodec = '10ec0897',

    [string]$ModuleSigningKeyPath = '',

    [string]$ModuleSigningCertificatePath = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'common.ps1')
$ntfscpPath = Join-Path $projectRoot 'scripts\roothealth-repair\journal-integration-v2\ntfscp'
$ntfscpProvenancePath = Join-Path $projectRoot 'scripts\roothealth-repair\journal-integration-v2\ntfscp-provenance.release-qualified.json'
$kernelArguments = @()
if (-not [string]::IsNullOrWhiteSpace($ModuleSigningKeyPath)) {
    $kernelArguments += @('-ModuleSigningKeyPath', $ModuleSigningKeyPath)
}
if (-not [string]::IsNullOrWhiteSpace($ModuleSigningCertificatePath)) {
    $kernelArguments += @(
        '-ModuleSigningCertificatePath',
        $ModuleSigningCertificatePath
    )
}

$steps = @(
    [pscustomobject]@{
        Name = 'stage complete pinned hardware firmware'
        Script = 'stage hardware firmware.ps1'
        Arguments = @()
    },
    [pscustomobject]@{
        Name = 'build the hardware kernel and modules'
        Script = 'build hardware kernel.ps1'
        Arguments = $kernelArguments
    },
    [pscustomobject]@{
        Name = 'build the T1OS driver module loader'
        Script = 'build driver runtime.ps1'
        Arguments = @()
    },
    [pscustomobject]@{
        Name = 'build Intel, AMD, NVIDIA, and VM graphics userspace'
        Script = 'build graphics runtime.ps1'
        Arguments = @('-Profile', 'hardware', '-EnableNvidia')
    },
    [pscustomobject]@{
        Name = 'build the development audio and media runtime'
        Script = 'build audio runtime.ps1'
        Arguments = @('-Development')
    },
    [pscustomobject]@{
        Name = 'build the network runtime'
        Script = 'build network runtime.ps1'
        Arguments = @()
    },
    [pscustomobject]@{
        Name = 'prepare the release Chromium T1OS runtime'
        Script = 'build chromium runtime.ps1'
        Arguments = @('-Profile', 'release')
    },
    [pscustomobject]@{
        Name = 'audit T1OS source runtime paths'
        Script = 'audit t1os runtime paths.ps1'
        Arguments = @('-SkipStorageImage')
    },
    [pscustomobject]@{
        Name = 'build the read-only roothealth'
        Script = 'build roothealth.ps1'
        Arguments = @()
    },
    [pscustomobject]@{
        Name = 'exercise the roothealth against corruption fixtures'
        Script = 'test roothealth.ps1'
        Arguments = @()
    },
    [pscustomobject]@{
        Name = 'qualify roothealth repair, refusal, and power-cut behavior'
        Script = 'test roothealth repair.ps1'
        Arguments = @(
            '-RepairCheckerPath', (Join-Path $projectRoot 'environment\hardware\tools\roothealth'),
            '-CheckCheckerPath', (Join-Path $projectRoot 'environment\hardware\tools\roothealth'),
            '-NtfscpPath', $ntfscpPath,
            '-ProblemHeaderPath', (Join-Path $projectRoot 'development\roothealth\engine\include\problem.h'),
            '-PolicySourcePath', (Join-Path $projectRoot 'development\roothealth\engine\src\roothealth_policy.c'),
            '-EngineSourcePath', (Join-Path $projectRoot 'development\roothealth\engine'),
            '-EngineManifestPath', (Join-Path $projectRoot 'environment\hardware\tools\roothealth-linked-inputs.manifest')
        )
    },
    [pscustomobject]@{
        Name = 'build the hardware initramfs'
        Script = 'build hardware initramfs.ps1'
        Arguments = @()
    },
    [pscustomobject]@{
        Name = 'synchronise T1OS into storage.img'
        Script = 'push to disk.ps1'
        Arguments = @()
    },
    [pscustomobject]@{
        Name = 'audit the deployed T1OS runtime paths'
        Script = 'audit t1os runtime paths.ps1'
        Arguments = @()
    },
    [pscustomobject]@{
        Name = 'exercise the Chromium T1OS runtime'
        Script = 'test chromium runtime.ps1'
        Arguments = @()
    },
    [pscustomobject]@{
        Name = 'validate hardware build artifacts'
        Script = 'test hardware build.ps1'
        Arguments = @()
    },
    [pscustomobject]@{
        Name = 'validate complete desktop hardware dependency closure'
        Script = 'validate hardware compatibility.ps1'
        Arguments = @()
    },
    [pscustomobject]@{
        Name = 'validate hardware-wide video routing and capabilities'
        Script = 'test video compatibility.ps1'
        Arguments = @()
    },
    [pscustomobject]@{
        Name = 'reset storage.img to verified production defaults'
        Script = 'prepare prod build.ps1'
        Arguments = @()
    },
    [pscustomobject]@{
        Name = 'assemble the 16 GiB production USB image'
        Script = 'create hardware usb image.ps1'
        Arguments = @(
            '-ImageSizeGiB', '16',
            '-PreferredAudioCodec', $PreferredAudioCodec,
            '-Production',
            '-SkipCompatibilityValidation',
            '-NtfscpPath', $ntfscpPath,
            '-NtfscpProvenancePath', $ntfscpProvenancePath,
            '-Force'
        )
    },
    [pscustomobject]@{
        Name = 'validate the USB image'
        Script = 'validate hardware usb image.ps1'
        Arguments = @()
    },
    [pscustomobject]@{
        Name = 'create the compact capacity-independent USB bundle'
        Script = 'create hardware usb bundle.ps1'
        Arguments = @(
            '-SkipImageValidation',
            '-Force'
        )
    },
    [pscustomobject]@{
        Name = 'validate the bundle at multiple USB capacities'
        Script = 'test hardware usb bundle.ps1'
        Arguments = @()
    }
)

if ($ArtifactsOnly) {
    $artifactStepScripts = @(
        'prepare prod build.ps1',
        'create hardware usb image.ps1',
        'validate hardware usb image.ps1',
        'create hardware usb bundle.ps1',
        'test hardware usb bundle.ps1'
    )
    $steps = @($steps | Where-Object { $_.Script -in $artifactStepScripts })

    $imageStep = $steps | Where-Object { $_.Script -ceq 'create hardware usb image.ps1' }
    $imageStep.Arguments = @(
        '-ImageSizeGiB', '16',
        '-PreferredAudioCodec', $PreferredAudioCodec,
        '-Production',
        '-NtfscpPath', $ntfscpPath,
        '-NtfscpProvenancePath', $ntfscpProvenancePath,
        '-Force'
    )
}
elseif (-not $SkipQemu) {
    $steps += [pscustomobject]@{
        Name = 'boot-test the USB image with QEMU and OVMF'
        Script = 'test hardware usb qemu.ps1'
        Arguments = @()
    }
}

foreach ($step in $steps) {
    $scriptPath = Join-Path $PSScriptRoot $step.Script
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        throw "Required hardware workflow script not found: $scriptPath"
    }
}
foreach ($releaseTool in @($ntfscpPath, $ntfscpProvenancePath)) {
    if (-not (Test-Path -LiteralPath $releaseTool -PathType Leaf)) {
        throw "Required release-qualified roothealth tool input not found: $releaseTool"
    }
}

if ($ArtifactsOnly) {
    Write-Host 'T1OS USB raw-image and bundle rebuild:'
}
else {
    Write-Host 'T1OS development hardware USB workflow:'
}
for ($index = 0; $index -lt $steps.Count; $index++) {
    Write-Host ("  {0}. {1}" -f ($index + 1), $steps[$index].Name)
}

if ($PlanOnly) {
    Write-Host 'Hardware USB workflow plan validation passed.'
    return
}

if (Test-T1OSDiskMounted) {
    throw 'environment/storage.img is mounted. Unmount it before starting the hardware USB workflow.'
}

for ($index = 0; $index -lt $steps.Count; $index++) {
    $step = $steps[$index]
    $scriptPath = Join-Path $PSScriptRoot $step.Script
    $stepArguments = [string[]]$step.Arguments
    Write-Host ("[{0}/{1}] {2}..." -f ($index + 1), $steps.Count, $step.Name)
    & pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $scriptPath @stepArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Hardware USB workflow failed while attempting to $($step.Name) (exit code $LASTEXITCODE)."
    }
}

$imagePath = Join-Path $projectRoot 'environment\hardware\t1os-hardware-usb.img'
$manifestPath = "$imagePath.json"
$version = (Get-Content -LiteralPath (Join-Path $projectRoot 'current_version.txt') -Raw).Trim()
$bundlePath = Join-Path $projectRoot "environment\hardware\The One OS $version.t1os"
if ($ArtifactsOnly) {
    Write-Host 'T1OS USB raw-image and bundle rebuild completed successfully.'
}
else {
    Write-Host 'T1OS development hardware USB workflow completed successfully.'
}
Write-Host "Image: $imagePath"
Write-Host "Manifest: $manifestPath"
Write-Host "Compact bundle: $bundlePath"
