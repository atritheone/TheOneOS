$ErrorActionPreference = 'Stop'

$taskName = 'T1OS Chromium Release Build'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$stateRoot = Join-Path $projectRoot 'development\chromium release'
$exitPath = Join-Path $stateRoot 'chromium-scheduled-release.exit.txt'
$logPath = Join-Path $stateRoot 'chromium-scheduled-release.log'
$task = Get-ScheduledTask -TaskName $taskName
if ($task.State -eq 'Running') {
    throw 'Chromium scheduled task is unexpectedly already running.'
}
if (Test-Path -LiteralPath $exitPath) {
    Remove-Item -LiteralPath $exitPath -Force
}

Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 3
while ($true) {
    $task = Get-ScheduledTask -TaskName $taskName
    $info = Get-ScheduledTaskInfo -TaskName $taskName
    $exitValue = 'pending'
    if (Test-Path -LiteralPath $exitPath) {
        $exitValue = (Get-Content -LiteralPath $exitPath -Raw).Trim()
    }
    $progress = 'no-log'
    if (Test-Path -LiteralPath $logPath) {
        $matches = @(
            Get-Content -LiteralPath $logPath -Tail 160 |
                Where-Object {
                    $_ -match '^\[[0-9]+/[0-9]+\]' -or
                    $_ -match 'verified compiled runtime|installed validated|ninja: no work|error:'
                }
        )
        if ($matches.Count -gt 0) {
            $progress = $matches[-1]
        }
        else {
            $progress = Get-Content -LiteralPath $logPath -Tail 1
        }
    }
    Write-Output (
        (Get-Date -Format o) +
        " TASK=$($task.State) RESULT=$($info.LastTaskResult)" +
        " EXIT=$exitValue PROGRESS=$progress"
    )
    if ($task.State -ne 'Running') {
        break
    }
    Start-Sleep -Seconds 30
}
if (Test-Path -LiteralPath $logPath) {
    Get-Content -LiteralPath $logPath -Tail 80
}
