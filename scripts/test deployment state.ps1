[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'deployment state.ps1')

function Assert-DeploymentTest {
    param(
        [Parameter(Mandatory)]
        [bool]$Condition,

        [Parameter(Mandatory)]
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

$stopwatch = [Diagnostics.Stopwatch]::StartNew()
$source = Get-T1OSDeploymentSourceState `
    -ProjectRoot $projectRoot -ScriptRoot $PSScriptRoot
$stopwatch.Stop()
Assert-DeploymentTest `
    -Condition (@($source.roots.psobject.Properties).Count -eq 18) `
    -Message 'The deployment source inventory does not contain all 18 managed roots.'
Assert-DeploymentTest `
    -Condition ($stopwatch.Elapsed.TotalSeconds -lt 5) `
    -Message "The metadata-only source inventory exceeded five seconds: $($stopwatch.Elapsed)."

$previous = [pscustomobject]@{
    format = 2
    contract_stamp = $source.contract_stamp
    target_identity = 'test-target'
    roots = $source.roots
}
$unchanged = Get-T1OSDeploymentPlan `
    -SourceState $source -PreviousState $previous `
    -TargetIdentity 'test-target'
Assert-DeploymentTest -Condition (@($unchanged.roots).Count -eq 0) `
    -Message 'An unchanged source produced deployment work.'
Assert-DeploymentTest -Condition (-not $unchanged.full_verification) `
    -Message 'An unchanged valid state requested exhaustive verification.'

$changedSource = $source | ConvertTo-Json -Depth 8 | ConvertFrom-Json
$changedSource.roots.network_settings.source_stamp = 'f' * 64
$changed = Get-T1OSDeploymentPlan `
    -SourceState $changedSource -PreviousState $previous `
    -TargetIdentity 'test-target'
Assert-DeploymentTest `
    -Condition (@($changed.roots).Count -eq 1 -and $changed.roots[0] -ceq 'network_settings') `
    -Message 'A one-root source change did not produce a one-root deployment plan.'

$changedChromium = $source | ConvertTo-Json -Depth 8 | ConvertFrom-Json
$changedChromium.roots.chromium.source_stamp = 'e' * 64
$chromiumPlan = Get-T1OSDeploymentPlan `
    -SourceState $changedChromium -PreviousState $previous `
    -TargetIdentity 'test-target'
Assert-DeploymentTest `
    -Condition ($chromiumPlan.unchanged_large_files -contains `
        'chromium|source/software/chromium/program/chrome') `
    -Message 'The planner did not preserve an unchanged large Chromium engine.'

$changedChromiumDigest = $changedChromium | ConvertTo-Json -Depth 8 |
    ConvertFrom-Json
$changedChromiumDigest.roots.chromium.large_files.'source/software/chromium/program/chrome'.declared_sha256 = 'd' * 64
$chromiumDigestPlan = Get-T1OSDeploymentPlan `
    -SourceState $changedChromiumDigest -PreviousState $previous `
    -TargetIdentity 'test-target'
Assert-DeploymentTest `
    -Condition ($chromiumDigestPlan.unchanged_large_files -notcontains `
        'chromium|source/software/chromium/program/chrome') `
    -Message 'A changed declared Chromium digest incorrectly skipped the engine.'

$invalid = Get-T1OSDeploymentPlan `
    -SourceState $source -PreviousState $previous `
    -TargetIdentity 'different-target'
Assert-DeploymentTest `
    -Condition (@($invalid.roots).Count -eq 18 -and $invalid.full_verification) `
    -Message 'A target identity mismatch did not force exhaustive synchronization.'

$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) `
    "t1os-deployment-state-test-$PID-$([guid]::NewGuid().ToString('N'))"
$statePath = Join-Path $temporaryRoot 'state.json'
try {
    Write-T1OSDeploymentState -Path $statePath -SourceState $source `
        -TargetIdentity 'test-target' -FullVerification $true
    $roundTrip = Read-T1OSDeploymentState -Path $statePath
    Assert-DeploymentTest `
        -Condition ($null -ne $roundTrip -and $roundTrip.target_identity -ceq 'test-target') `
        -Message 'Atomic deployment-state round trip failed.'
}
finally {
    Remove-Item -LiteralPath $temporaryRoot -Recurse -Force `
        -ErrorAction SilentlyContinue
}

Write-Host ("Deployment state tests passed; source inventory took {0:N3}s." -f `
    $stopwatch.Elapsed.TotalSeconds)
