function ConvertTo-T1OSIncrementalArguments {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [Collections.IDictionary]$BoundParameters,

        [object[]]$UnboundArguments = @()
    )

    $result = [Collections.Generic.List[string]]::new()
    foreach ($name in @($BoundParameters.Keys | Sort-Object)) {
        $value = $BoundParameters[$name]
        if ($value -is [Management.Automation.SwitchParameter]) {
            if ($value.IsPresent) {
                $result.Add("-$name")
            }
            continue
        }
        if ($value -is [bool]) {
            $result.Add("-$name`:$($value.ToString().ToLowerInvariant())")
            continue
        }
        $result.Add("-$name")
        if ($value -is [Collections.IEnumerable] -and $value -isnot [string]) {
            foreach ($item in $value) {
                $result.Add([string]$item)
            }
        }
        elseif ($null -ne $value) {
            $result.Add([string]$value)
        }
    }
    foreach ($argument in $UnboundArguments) {
        $result.Add([string]$argument)
    }
    return $result.ToArray()
}

function Invoke-T1OSIncrementalTestGuard {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ScriptPath,

        [Parameter(Mandatory)]
        [Collections.IDictionary]$BoundParameters,

        [object[]]$UnboundArguments = @()
    )

    $projectRoot = Split-Path -Path $PSScriptRoot -Parent
    $relative = [IO.Path]::GetRelativePath($projectRoot, $ScriptPath).Replace('\', '/')
    if ($env:T1OS_INCREMENTAL_ACTIVE_SCRIPT -ceq $relative) {
        return $false
    }

    $runner = Join-Path $PSScriptRoot 'incremental_test.py'
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $python) {
        throw 'Python is required by the T1OS incremental test runner.'
    }
    $arguments = ConvertTo-T1OSIncrementalArguments `
        -BoundParameters $BoundParameters `
        -UnboundArguments $UnboundArguments
    $parameterRecords = @(
        foreach ($name in $BoundParameters.Keys) {
            [pscustomobject]@{ Name = [string]$name; Value = $BoundParameters[$name] }
        }
    )
    $invocation = [pscustomobject]@{
        Parameters = $parameterRecords
        Unbound = @($UnboundArguments)
    }
    $serializedInvocation = [Management.Automation.PSSerializer]::Serialize($invocation)
    $encodedInvocation = [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes($serializedInvocation)
    )
    $previousInvocation = $env:T1OS_INCREMENTAL_POWERSHELL_INVOCATION
    try {
        $env:T1OS_INCREMENTAL_POWERSHELL_INVOCATION = $encodedInvocation
        & $python $runner run --script $ScriptPath -- @arguments | Out-Host
        $runnerExitCode = $LASTEXITCODE
    }
    finally {
        $env:T1OS_INCREMENTAL_POWERSHELL_INVOCATION = $previousInvocation
    }
    if ($runnerExitCode -ne 0) {
        throw "Incremental test task failed with exit code $runnerExitCode."
    }
    return $true
}
