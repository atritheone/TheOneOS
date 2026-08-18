[CmdletBinding()]
param(
    [string]$RepairCheckerPath,
    [string]$CheckCheckerPath,
    [string]$JournalValidatorPath,
    [string]$NtfscpPath,
    [string]$ProblemHeaderPath,
    [string]$PolicySourcePath,
    [string]$EngineSourcePath,
    [string]$EngineManifestPath
)

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$assetRoot = Join-Path $PSScriptRoot '..\roothealth-repair'

if (-not $RepairCheckerPath) {
    $RepairCheckerPath = Join-Path $projectRoot 'environment\hardware\tools\roothealth'
}
if (-not $CheckCheckerPath) {
    $CheckCheckerPath = Join-Path $projectRoot 'environment\hardware\tools\roothealth'
}

$harnessPath = Join-Path $assetRoot 'test.sh'
$fixturePath = Join-Path $assetRoot 'fixtures.py'
$walFixturePath = Join-Path $assetRoot 'wal-fixtures.py'
$nativeRedoFixturePath = Join-Path $assetRoot 'native_logfile_redo_fixture.py'
$nativeEmptyFixturePath = Join-Path $assetRoot 'native_logfile_empty_t1os_fixture.py'
$nativeLogCorpusPath = Join-Path $assetRoot 'native-log-corpus.py'
$nativeReplayProposalCheckerPath = Join-Path $assetRoot 'check-native-replay-v1_1-v2-proposal.py'
$nativeReplayProposalPath = Join-Path $assetRoot 'native-replay-v1_1-v2-proposal-qualification.json'
$powercutMaterializerPath = Join-Path $assetRoot 'powercut-materialize.py'
$faultSourcePath = Join-Path $assetRoot 'write-fault.c'
$reportValidatorPath = Join-Path $assetRoot 'validate-report.py'
$policyCheckerPath = Join-Path $assetRoot 'check-policy.py'
$ioClosureCheckerPath = Join-Path $assetRoot 'check-io-closure.py'
$policyAuditCheckerPath = Join-Path $assetRoot 'check-repair-policy-audit.py'
$policyImplementationCheckerPath = Join-Path $assetRoot 'check-repair-policy-implementation.py'
$policyAuditPath = Join-Path $assetRoot 'repair-policy-audit.json'
if (-not $JournalValidatorPath) {
    $JournalValidatorPath = Join-Path $PSScriptRoot '..\validate roothealth journal.py'
}

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $resolved = (Resolve-Path -LiteralPath $WindowsPath).Path
    $output = & wsl.exe -d Ubuntu --exec wslpath -a $resolved
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Ubuntu WSL is required to qualify roothealth repair mode.'
}
foreach ($requiredFile in @(
    $RepairCheckerPath,
    $CheckCheckerPath,
    $harnessPath,
    $fixturePath,
    $walFixturePath,
    $nativeRedoFixturePath,
    $nativeEmptyFixturePath,
    $nativeLogCorpusPath,
    $nativeReplayProposalCheckerPath,
    $nativeReplayProposalPath,
    $powercutMaterializerPath,
    $faultSourcePath,
    $reportValidatorPath,
    $policyCheckerPath,
    $ioClosureCheckerPath,
    $policyAuditCheckerPath,
    $policyImplementationCheckerPath,
    $policyAuditPath,
    $JournalValidatorPath
)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required roothealth repair qualification input is missing: $requiredFile"
    }
}

$wslRepairChecker = ConvertTo-WslPath -WindowsPath $RepairCheckerPath
$wslCheckChecker = ConvertTo-WslPath -WindowsPath $CheckCheckerPath
$wslHarness = ConvertTo-WslPath -WindowsPath $harnessPath
$wslFixtures = ConvertTo-WslPath -WindowsPath $fixturePath
$wslWalFixtures = ConvertTo-WslPath -WindowsPath $walFixturePath
$wslNativeRedoFixture = ConvertTo-WslPath -WindowsPath $nativeRedoFixturePath
$wslNativeEmptyFixture = ConvertTo-WslPath -WindowsPath $nativeEmptyFixturePath
$wslNativeLogCorpus = ConvertTo-WslPath -WindowsPath $nativeLogCorpusPath
$wslNativeReplayProposalChecker = ConvertTo-WslPath -WindowsPath $nativeReplayProposalCheckerPath
$wslNativeReplayProposal = ConvertTo-WslPath -WindowsPath $nativeReplayProposalPath
$wslPowercutMaterializer = ConvertTo-WslPath -WindowsPath $powercutMaterializerPath
$wslFaultSource = ConvertTo-WslPath -WindowsPath $faultSourcePath
$wslReportValidator = ConvertTo-WslPath -WindowsPath $reportValidatorPath
$wslPolicyChecker = ConvertTo-WslPath -WindowsPath $policyCheckerPath
$wslIoClosureChecker = ConvertTo-WslPath -WindowsPath $ioClosureCheckerPath
$wslPolicyAuditChecker = ConvertTo-WslPath -WindowsPath $policyAuditCheckerPath
$wslPolicyImplementationChecker = ConvertTo-WslPath -WindowsPath $policyImplementationCheckerPath
$wslPolicyAudit = ConvertTo-WslPath -WindowsPath $policyAuditPath
$wslJournalValidator = ConvertTo-WslPath -WindowsPath $JournalValidatorPath
$wslNtfscp = if ([string]::IsNullOrWhiteSpace($NtfscpPath)) {
    'ntfscp'
}
else {
    $resolvedNtfscp = [System.IO.Path]::GetFullPath($NtfscpPath)
    if (-not (Test-Path -LiteralPath $resolvedNtfscp -PathType Leaf)) {
        throw "The selected pinned ntfscp is missing: $resolvedNtfscp"
    }
    ConvertTo-WslPath -WindowsPath $resolvedNtfscp
}

$wslProblemHeader = ''
$wslPolicySource = ''
$wslEngineSource = ''
$wslEngineManifest = ''
if ($ProblemHeaderPath) {
    $wslProblemHeader = ConvertTo-WslPath -WindowsPath $ProblemHeaderPath
}
if ($PolicySourcePath) {
    $wslPolicySource = ConvertTo-WslPath -WindowsPath $PolicySourcePath
}
if ($EngineSourcePath) {
    $wslEngineSource = ConvertTo-WslPath -WindowsPath $EngineSourcePath
}
if ($EngineManifestPath) {
    $wslEngineManifest = ConvertTo-WslPath -WindowsPath $EngineManifestPath
}
$emptyWslArgument = '__ROOTHEALTH_EMPTY_ARGUMENT__'
$wslProblemHeaderArgument = if ($wslProblemHeader) {
    $wslProblemHeader
}
else {
    $emptyWslArgument
}
$wslPolicySourceArgument = if ($wslPolicySource) {
    $wslPolicySource
}
else {
    $emptyWslArgument
}
$wslEngineSourceArgument = if ($wslEngineSource) {
    $wslEngineSource
}
else {
    $emptyWslArgument
}
$wslEngineManifestArgument = if ($wslEngineManifest) {
    $wslEngineManifest
}
else {
    $emptyWslArgument
}

& wsl.exe -d Ubuntu -u root --exec bash $wslHarness `
    $wslRepairChecker `
    $wslCheckChecker `
    $wslFixtures `
    $wslFaultSource `
    $wslReportValidator `
    $wslPolicyChecker `
    $wslIoClosureChecker `
    $wslJournalValidator `
    $wslNtfscp `
    $wslWalFixtures `
    $wslProblemHeaderArgument `
    $wslPolicySourceArgument `
    $wslEngineSourceArgument `
    $wslEngineManifestArgument `
    $wslPolicyAuditChecker `
    $wslPolicyImplementationChecker `
    $wslPolicyAudit `
    $wslNativeRedoFixture `
    $wslNativeLogCorpus `
    $wslNativeReplayProposalChecker `
    $wslNativeReplayProposal `
    $wslPowercutMaterializer `
    $wslNativeEmptyFixture
$testExitCode = $LASTEXITCODE
if ($testExitCode -ne 0) {
    throw "roothealth repair qualification failed (exit code $testExitCode)."
}

Write-Host 'roothealth repair qualification passed.'
