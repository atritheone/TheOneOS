$ErrorActionPreference = 'Stop'

$taskName = 'T1OS Chromium Release Build'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    throw "Scheduled task already exists: $taskName"
}

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$worker = Join-Path $PSScriptRoot 'chromium-scheduled-release.sh'
$stateRoot = Join-Path $projectRoot 'development\chromium release'
$exitPath = Join-Path $stateRoot 'chromium-scheduled-release.exit.txt'
New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
if (Test-Path -LiteralPath $exitPath) {
    Remove-Item -LiteralPath $exitPath -Force
}

$wslWorker = (& wsl.exe -d Ubuntu --exec wslpath -a $worker).Trim()
if (-not $wslWorker.StartsWith('/mnt/')) {
    throw "Unexpected WSL worker path: $wslWorker"
}
$wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
$action = New-ScheduledTaskAction `
    -Execute $wsl `
    -Argument ('-d Ubuntu -u edward --exec bash "' + $wslWorker + '"') `
    -WorkingDirectory $projectRoot
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Settings $settings `
    -Description 'Complete and validate the official T1OS Chromium release runtime.' |
    Out-Null
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 3

$task = Get-ScheduledTask -TaskName $taskName
$info = Get-ScheduledTaskInfo -TaskName $taskName
Write-Output "TASK=$($task.State)"
Write-Output "LAST_RESULT=$($info.LastTaskResult)"
Write-Output "WORKER=$wslWorker"
