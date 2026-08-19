[CmdletBinding()]
param(
    [ValidateSet('Smoke', 'Brick', 'Gui', 'Features', 'Full')]
    [string]$Suite = 'Full',
    [int]$PollSeconds = 5
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$testScript = Join-Path $PSScriptRoot '..\tests\test t1os vm.ps1'
$chromiumStateRoot = Join-Path $projectRoot 'development\chromium release'
$softwareRoot = Join-Path $projectRoot 'environment\software'
$stdoutPath = Join-Path $softwareRoot 't1os-vm-monitored.stdout.log'
$stderrPath = Join-Path $softwareRoot 't1os-vm-monitored.stderr.log'
$chromiumBuildLockPath = Join-Path $chromiumStateRoot 'chromium-release-build.lock'
$builderPattern = '^(chromium|chrome|ninja|autoninja|gn)$'
$wslBuilderArguments = '(?i)(build chromium (?:runtime|source)\.py|/t1os-chromium/|(?:^|[ /])(autoninja|ninja|gn)(?: |$))'

if (-not (Test-Path -LiteralPath $testScript -PathType Leaf)) {
    throw "VM test script is missing: $testScript"
}

# A release Chromium build and this VM harness intentionally cannot share the
# workspace: the monitor below terminates Chromium builders as foreign test
# activity.  Hold this exclusive lock for the lifetime of the VM run so either
# workflow can start first without a check-then-start race.
$chromiumBuildLock = $null
New-Item -ItemType Directory -Path $chromiumStateRoot -Force | Out-Null
try {
    $chromiumBuildLock = [System.IO.File]::Open(
        $chromiumBuildLockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
}
catch [System.IO.IOException] {
    throw 'A coordinated Chromium release build is active; refusing the VM test.'
}

$activeWslChromiumBuild = @(
    & wsl.exe -d Ubuntu --exec bash -lc 'ps -eo args=' 2>$null |
        Where-Object {
            $_ -match '(?i)(build chromium (?:runtime|source)\.py|/home/edward/t1os-chromium/.*/ninja)'
        }
)
if ($activeWslChromiumBuild.Count -ne 0) {
    throw 'An active Chromium release build was found; refusing the VM test.'
}

Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
$baselineFiles = @(& rg --files $projectRoot 2>$null).Count
$shellPath = (Get-Process -Id $PID).Path
$arguments = @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass',
    '-File', ('"' + $testScript + '"'),
    '-Suite', $Suite
)
$process = Start-Process -FilePath $shellPath -ArgumentList $arguments `
    -WorkingDirectory $projectRoot -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath -WindowStyle Hidden -PassThru

$reportedOutputLines = 0
$builderFirstSeen = @{}
$wslKilledGroups = @{}
$killedBuilders = @()
try {
    while (-not $process.HasExited) {
        Start-Sleep -Seconds ([Math]::Max(1, $PollSeconds))
        $process.Refresh()

        if (Test-Path -LiteralPath $stdoutPath) {
            $lines = @(Get-Content -LiteralPath $stdoutPath)
            if ($lines.Count -gt $reportedOutputLines) {
                $lines[$reportedOutputLines..($lines.Count - 1)] | Write-Host
                $reportedOutputLines = $lines.Count
            }
        }

        $builders = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $_.ProcessName -match $builderPattern
        })
        $workspaceFiles = @(& rg --files $projectRoot 2>$null).Count
        foreach ($builder in $builders) {
            if (-not $builderFirstSeen.ContainsKey($builder.Id)) {
                $builderFirstSeen[$builder.Id] = [DateTime]::UtcNow
                Write-Warning "unexpected builder appeared: $($builder.ProcessName) pid=$($builder.Id)"
            }
            $age = if ($builder.StartTime) {
                ([DateTime]::Now - $builder.StartTime).TotalSeconds
            }
            else {
                ([DateTime]::UtcNow - $builderFirstSeen[$builder.Id]).TotalSeconds
            }
            $fileSurge = $workspaceFiles - $baselineFiles
            if ($age -ge 180 -or $builder.CPU -ge 120 -or $fileSurge -ge 2000) {
                Stop-Process -Id $builder.Id -Force
                $killedBuilders += "$($builder.ProcessName):$($builder.Id)"
                Write-Warning (
                    "killed pathological builder $($builder.ProcessName) pid=$($builder.Id) " +
                    "age=$([Math]::Round($age))s cpu=$([Math]::Round($builder.CPU, 1))s " +
                    "workspace_file_surge=$fileSurge"
                )
            }
        }

        # Chromium builds normally run inside WSL, where their Python driver,
        # Ninja and compiler children are invisible to Get-Process.  Inspect
        # the Linux process table and terminate the numeric process group so a
        # killed parent cannot leave thousands of compiler children behind.
        $wslRows = @(& wsl.exe -d Ubuntu --exec bash -lc `
            'ps -eo pid=,pgid=,etimes=,pcpu=,comm=,args=' 2>$null)
        foreach ($row in $wslRows) {
            if ($row -notmatch '^\s*(\d+)\s+(\d+)\s+(\d+)\s+([0-9.]+)\s+(\S+)\s+(.*)$') {
                continue
            }
            $wslPid = [int]$Matches[1]
            $wslPgid = [int]$Matches[2]
            $wslAge = [long]$Matches[3]
            $wslCpu = [double]$Matches[4]
            $wslName = $Matches[5]
            $wslArguments = $Matches[6]
            if (
                $wslName -notmatch $builderPattern -and
                $wslArguments -notmatch $wslBuilderArguments
            ) {
                continue
            }
            if ($wslKilledGroups.ContainsKey($wslPgid)) {
                continue
            }
            $fileSurge = $workspaceFiles - $baselineFiles
            # A T1OS Chromium source/runtime build is never part of a VM test.
            # Stop it as soon as it appears; waiting for a generic resource
            # threshold lets Ninja create thousands of intermediate files.
            $isT1OSChromiumBuild = $wslArguments -match '(?i)(build chromium (?:runtime|source)\.py|/home/edward/t1os-chromium/)'
            if ($isT1OSChromiumBuild -or $wslAge -ge 180 -or ($wslAge -ge 120 -and $wslCpu -ge 80) -or $fileSurge -ge 2000) {
                & wsl.exe -d Ubuntu --exec bash -lc "kill -TERM -- -$wslPgid" 2>$null
                Start-Sleep -Milliseconds 500
                & wsl.exe -d Ubuntu --exec bash -lc `
                    "kill -0 $wslPid 2>/dev/null && kill -KILL -- -$wslPgid || true" 2>$null
                $wslKilledGroups[$wslPgid] = $true
                $killedBuilders += "wsl-$wslName`:$wslPid"
                Write-Warning (
                    "killed pathological WSL builder $wslName pid=$wslPid pgid=$wslPgid " +
                    "age=$($wslAge)s cpu=$wslCpu% workspace_file_surge=$fileSurge"
                )
            }
        }
    }
}
finally {
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $chromiumBuildLock) {
        $chromiumBuildLock.Dispose()
        $chromiumBuildLock = $null
    }
}

if (Test-Path -LiteralPath $stdoutPath) {
    $lines = @(Get-Content -LiteralPath $stdoutPath)
    if ($lines.Count -gt $reportedOutputLines) {
        $lines[$reportedOutputLines..($lines.Count - 1)] | Write-Host
    }
}
if (Test-Path -LiteralPath $stderrPath) {
    $errors = Get-Content -LiteralPath $stderrPath -Raw
    if ($errors) {
        [Console]::Error.Write($errors)
    }
}

Write-Host "Builder monitor: baseline files=$baselineFiles, killed=$($killedBuilders.Count)."
if ($process.ExitCode -ne 0) {
    throw "T1OS VM $Suite suite failed with exit code $($process.ExitCode)."
}
