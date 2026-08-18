[CmdletBinding()]
param(
    [switch]$DeploymentPayloadOnly
)

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$verifier = Join-Path $projectRoot 'development\promote python 3.14 runtime.py'
$buildWorkflow = Join-Path $PSScriptRoot '..\build\build python runtime.ps1'
$profiledEntrypointVerifier = Join-Path $PSScriptRoot '..\audits\validate profiled python entrypoints.py'
$managerTest = Join-Path $projectRoot 'source\python\tests\test_python_packages.py'
$manager = Join-Path $projectRoot 'source\build software\python\python.py'
$pythonRoot = Join-Path $projectRoot 'source\software\python'
$catalogueRoot = Join-Path $projectRoot 'source\catalogue\python'
$imageRoot = Join-Path $projectRoot 'source\catalogue\image'

foreach ($requiredVerifier in @($verifier, $buildWorkflow, $profiledEntrypointVerifier)) {
    if (-not (Test-Path -LiteralPath $requiredVerifier -PathType Leaf)) {
        throw "Python 3.14 runtime verifier not found: $requiredVerifier"
    }
}

$buildWorkflowText = Get-Content -Raw -LiteralPath $buildWorkflow
foreach ($requiredText in @(
    '[switch]$Promote',
    'if (-not ($Rebuild -or $StageOnly -or $Promote))',
    '$wslPromoter verify',
    'no candidate was built'
)) {
    if (-not $buildWorkflowText.Contains($requiredText)) {
        throw "Python production is missing its explicit-build guard: $requiredText"
    }
}
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Required command not found: wsl.exe'
}

$verificationCommand = if ($DeploymentPayloadOnly) {
    'verify-deployment'
}
else {
    'verify'
}
$wslVerifier = (& wsl.exe -d Ubuntu --exec wslpath -a $verifier |
    Select-Object -First 1).Trim()
$wslProfiledEntrypointVerifier = (& wsl.exe -d Ubuntu --exec wslpath -a $profiledEntrypointVerifier |
    Select-Object -First 1).Trim()
$wslProjectRoot = (& wsl.exe -d Ubuntu --exec wslpath -a $projectRoot |
    Select-Object -First 1).Trim()
if (
    [string]::IsNullOrWhiteSpace($wslVerifier) -or
    [string]::IsNullOrWhiteSpace($wslProfiledEntrypointVerifier) -or
    [string]::IsNullOrWhiteSpace($wslProjectRoot)
) {
    throw "Could not translate Python 3.14 verifier path: $verifier"
}
$profiledArguments = @(
    $wslProfiledEntrypointVerifier,
    '--repo',
    $wslProjectRoot,
    '--policy-only'
)
$null = & wsl.exe -d Ubuntu --exec python3 -B @profiledArguments
if ($LASTEXITCODE -ne 0) {
    throw "Profiled Python entrypoint verification failed (exit code $LASTEXITCODE)."
}
& wsl.exe -d Ubuntu --exec python3 -B $wslVerifier $verificationCommand
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.14 runtime verification failed (exit code $LASTEXITCODE)."
}

if (-not $DeploymentPayloadOnly) {
    foreach ($path in @($managerTest, $manager)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "T1OS Python package test input not found: $path"
        }
    }
    $wslManagerTest = (& wsl.exe -d Ubuntu --exec wslpath -a $managerTest | Select-Object -First 1).Trim()
    $wslManager = (& wsl.exe -d Ubuntu --exec wslpath -a $manager | Select-Object -First 1).Trim()
    $wslPython = (& wsl.exe -d Ubuntu --exec wslpath -a (Join-Path $pythonRoot 'bin\python') | Select-Object -First 1).Trim()
    $wslLoader = (& wsl.exe -d Ubuntu --exec wslpath -a (Join-Path $catalogueRoot 'ld-linux-x86-64.so.2') | Select-Object -First 1).Trim()
    $wslCatalogue = (& wsl.exe -d Ubuntu --exec wslpath -a $catalogueRoot | Select-Object -First 1).Trim()
    $wslImage = (& wsl.exe -d Ubuntu --exec wslpath -a $imageRoot | Select-Object -First 1).Trim()
    $libraries = "$wslImage/pillow.libs`:$wslImage`:$wslCatalogue"
    & wsl.exe -d Ubuntu --exec env `
        PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH= `
        $wslLoader --library-path $libraries $wslPython -B -P `
        $wslManagerTest $wslManager $wslLoader $wslPython $libraries
    if ($LASTEXITCODE -ne 0) {
        throw "T1OS Python package transaction tests failed (exit code $LASTEXITCODE)."
    }
}

if ($DeploymentPayloadOnly) {
    Write-Host 'T1OS canonical Python 3.14 deployment payload verification passed.'
}
else {
    Write-Host 'T1OS canonical Python 3.14 release verification passed.'
}
