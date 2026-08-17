[CmdletBinding()]
param(
    [string]$VmName = 'The One OS',

    [string]$Destination,

    [switch]$SaveRunningVm,

    [switch]$KeepRawClone,

    [ValidateRange(1, 100)]
    [int]$RetainedBoots = 5
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$environmentRoot = Join-Path $projectRoot 'environment'
$serialLogPath = Join-Path $environmentRoot 'vbox-serial.log'
$timestamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$token = [guid]::NewGuid().ToString('N').Substring(0, 12)

if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path $environmentRoot "extracted logs\$timestamp"
}
$Destination = [System.IO.Path]::GetFullPath($Destination)

$temporaryParent = Join-Path ([System.IO.Path]::GetTempPath()) 'T1OS Log Export'
$temporaryRoot = Join-Path $temporaryParent $token
$rawClonePath = Join-Path $temporaryRoot 'runtime.raw'
$mountPoint = "/mnt/t1os-log-export-$token"
$runtimeMounted = $false
$resumeVm = $false
$completed = $false
$managedDestinationRoot = Join-Path $environmentRoot 'extracted logs'

function Get-T1OSVBoxManage {
    $command = Get-Command VBoxManage -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $default = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
    if (Test-Path -LiteralPath $default -PathType Leaf) {
        return $default
    }

    throw 'VBoxManage was not found. Install VirtualBox or add VBoxManage to PATH.'
}

function Invoke-T1OSVBox {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$Quiet
    )

    if ($Quiet) {
        & $script:vbox @Arguments *> $null
    }
    else {
        & $script:vbox @Arguments | Out-Host
    }
    if ($LASTEXITCODE -ne 0) {
        throw "VBoxManage $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

function Get-T1OSVmInformation {
    $lines = @(& $script:vbox showvminfo $VmName --machinereadable)
    if ($LASTEXITCODE -ne 0) {
        throw "VirtualBox VM '$VmName' is not registered."
    }

    $state = $null
    $uuid = $null
    $vdi = $null
    foreach ($line in $lines) {
        $text = [string]$line
        if ($text -match '^VMState="([^"]+)"$') {
            $state = $Matches[1]
        }
        elseif ($text -match '^UUID="([^"]+)"$') {
            $uuid = $Matches[1]
        }
        elseif ($text -match '^"SATA-[0-9]+-[0-9]+"="(.+\.vdi)"$') {
            $vdi = $Matches[1] -replace '\\\\', '\'
        }
    }

    if (-not $state -or -not $uuid) {
        throw "Could not read the state and UUID of VirtualBox VM '$VmName'."
    }
    if (-not $vdi -or -not (Test-Path -LiteralPath $vdi -PathType Leaf)) {
        throw "Could not locate the VDI attached to VirtualBox VM '$VmName'."
    }

    return [pscustomobject]@{
        State = $state
        Uuid = $uuid
        Vdi = [System.IO.Path]::GetFullPath($vdi)
    }
}

function Wait-T1OSVmState {
    param(
        [Parameter(Mandatory)][string[]]$Expected,
        [ValidateRange(1, 120)][int]$TimeoutSeconds = 60
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $information = Get-T1OSVmInformation
        if ($information.State -in $Expected) {
            return $information.State
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "VM '$VmName' did not reach state $($Expected -join ' or ') within $TimeoutSeconds seconds."
}

function ConvertTo-T1OSWslPath {
    param([Parameter(Mandatory)][string]$Path)

    $output = @(& wsl.exe --exec wslpath -a $Path)
    if ($LASTEXITCODE -ne 0 -or $output.Count -eq 0) {
        throw "WSL could not translate path: $Path"
    }
    $translated = ([string]$output[0]).Trim()
    if ([string]::IsNullOrWhiteSpace($translated)) {
        throw "WSL returned an empty path for: $Path"
    }
    return $translated
}

function Remove-T1OSExpiredLogExports {
    $resolvedRoot = [System.IO.Path]::GetFullPath($script:managedDestinationRoot)

    if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
        return
    }

    $rootPrefix = $resolvedRoot.TrimEnd('\') + '\'
    $exports = @(
        Get-ChildItem -LiteralPath $resolvedRoot -Directory |
            Where-Object {
                $_.Name -match '^\d{8}T\d{6}Z$' -and
                (Test-Path -LiteralPath (Join-Path $_.FullName 'manifest.json') -PathType Leaf)
            } |
            Sort-Object Name -Descending
    )

    foreach ($expired in @($exports | Select-Object -Skip $RetainedBoots)) {
        $resolvedExpired = [System.IO.Path]::GetFullPath($expired.FullName)

        if (-not $resolvedExpired.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove unexpected log-export path: $resolvedExpired"
        }

        Remove-Item -LiteralPath $resolvedExpired -Recurse -Force
        Write-Host "Removed expired boot-log export: $resolvedExpired"
    }
}

$vbox = Get-T1OSVBoxManage
$vm = Get-T1OSVmInformation
$originalState = $vm.State

if ($originalState -eq 'running') {
    if (-not $SaveRunningVm) {
        throw "VM '$VmName' is running. Shut it down first, or pass -SaveRunningVm to preserve and restore its running state."
    }
    Write-Host "Saving running VM '$VmName' so its VDI can be cloned consistently..."
    Invoke-T1OSVBox -Arguments @('controlvm', $VmName, 'savestate')
    [void](Wait-T1OSVmState -Expected @('saved'))
    $resumeVm = $true
}
elseif ($originalState -notin @('poweroff', 'saved', 'aborted')) {
    throw "VM '$VmName' must be powered off, saved, or aborted before extraction; state=$originalState."
}

try {
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null

    Write-Host "Cloning the runtime VDI attached to '$VmName'..."
    Invoke-T1OSVBox -Arguments @('clonemedium', 'disk', $vm.Vdi, $rawClonePath, '--format', 'RAW')

    $wslRawClone = ConvertTo-T1OSWslPath -Path $rawClonePath
    $wslDestination = ConvertTo-T1OSWslPath -Path $Destination

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $filesystemInitialCheck = @(
            & wsl.exe -u root --exec /usr/sbin/e2fsck -f -n $wslRawClone 2>&1
        )
        $filesystemInitialCheckExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $filesystemInitialCheck | Set-Content -LiteralPath (Join-Path $Destination 'filesystem-check-initial.txt')

    # A read-only e2fsck deliberately skips journal replay and can still exit
    # zero.  Runtime logs commonly live only in that pending journal after a VM
    # save, so exit code alone would produce a clean-looking but stale export.
    # Replay/repair only the disposable clone whenever e2fsck reports that it
    # skipped recovery; the attached VDI is never modified.
    $filesystemInitialText = ($filesystemInitialCheck | ForEach-Object {
        [string]$_
    }) -join "`n"
    $filesystemJournalPending = $filesystemInitialText -match '(?i)(skipping journal recovery|needs journal recovery|recovering journal)'
    $filesystemRepairPerformed = (
        $filesystemInitialCheckExitCode -ne 0 -or
        $filesystemJournalPending
    )
    $filesystemRepairExitCode = $null
    if ($filesystemRepairPerformed) {
        Write-Warning "The cloned runtime filesystem needs journal recovery or repair (e2fsck exit code $filesystemInitialCheckExitCode). Repairing only the disposable clone..."
        try {
            $ErrorActionPreference = 'Continue'
            $filesystemRepair = @(
                & wsl.exe -u root --exec /usr/sbin/e2fsck -f -y $wslRawClone 2>&1
            )
            $filesystemRepairExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        $filesystemRepair | Set-Content -LiteralPath (Join-Path $Destination 'filesystem-repair.txt')
        if ($filesystemRepairExitCode -notin @(0, 1)) {
            throw "The disposable runtime clone could not be repaired safely (e2fsck exit code $filesystemRepairExitCode)."
        }
    }

    try {
        $ErrorActionPreference = 'Continue'
        $filesystemCheck = @(
            & wsl.exe -u root --exec /usr/sbin/e2fsck -f -n $wslRawClone 2>&1
        )
        $filesystemCheckExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $filesystemCheck | Set-Content -LiteralPath (Join-Path $Destination 'filesystem-check.txt')
    if ($filesystemCheckExitCode -ne 0) {
        throw "The disposable runtime clone is not clean after recovery (e2fsck exit code $filesystemCheckExitCode)."
    }

    Write-Host 'Mounting the cloned filesystem read-only without journal replay...'
    & wsl.exe -u root --exec sh -c 'mkdir -p "$2"; mount -o loop,ro,noload "$1" "$2"' sh $wslRawClone $mountPoint
    if ($LASTEXITCODE -ne 0) {
        throw 'WSL could not mount the cloned VirtualBox runtime disk read-only.'
    }
    $runtimeMounted = $true

    & wsl.exe -u root --exec test -d "$mountPoint/the one/logs"
    if ($LASTEXITCODE -ne 0) {
        throw "The runtime filesystem does not contain '/the one/logs'."
    }

    $archivePath = Join-Path $Destination 'logs.tar.gz'
    $wslArchivePath = ConvertTo-T1OSWslPath -Path $archivePath
    Write-Host "Archiving '/the one/logs' with Linux metadata..."
    & wsl.exe -u root --exec tar --numeric-owner -C "$mountPoint/the one" -czf $wslArchivePath logs
    if ($LASTEXITCODE -ne 0) {
        throw 'WSL could not archive the T1OS logs.'
    }

    $browsePath = Join-Path $Destination 'logs'
    New-Item -ItemType Directory -Path $browsePath -Force | Out-Null
    $wslBrowsePath = ConvertTo-T1OSWslPath -Path $browsePath
    & wsl.exe -u root --exec sh -c 'cp -R --preserve=timestamps "$1"/. "$2"/' sh "$mountPoint/the one/logs" $wslBrowsePath
    if ($LASTEXITCODE -ne 0) {
        throw 'WSL could not create the browsable copy of the T1OS logs.'
    }

    $statistics = @(& wsl.exe -u root --exec sh -c 'files=$(find "$1" -type f | wc -l); bytes=$(find "$1" -type f -printf "%s\n" | awk "{total += \$1} END {print total + 0}"); printf "%s %s\n" "$files" "$bytes"' sh "$mountPoint/the one/logs")
    if ($LASTEXITCODE -ne 0 -or $statistics.Count -eq 0 -or ([string]$statistics[0]) -notmatch '^(\d+)\s+(\d+)$') {
        throw 'Could not calculate statistics for the extracted logs.'
    }
    $fileCount = [long]$Matches[1]
    $contentBytes = [long]$Matches[2]

    $serialCopied = $false
    if (Test-Path -LiteralPath $serialLogPath -PathType Leaf) {
        Copy-Item -LiteralPath $serialLogPath -Destination (Join-Path $Destination 'vbox-serial.log') -Force
        $serialCopied = $true
    }

    $mediumInfo = @(& $vbox showmediuminfo disk $vm.Vdi)
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not read the attached VDI identity from VirtualBox.'
    }
    $mediumUuid = $null
    foreach ($line in $mediumInfo) {
        if ([string]$line -match '^UUID:\s+([^\s]+)\s*$') {
            $mediumUuid = $Matches[1]
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($mediumUuid)) {
        throw 'VirtualBox did not report the UUID of the attached VDI.'
    }

    $archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifest = [ordered]@{
        format = 't1os-vbox-log-export-v1'
        extracted_at_utc = [DateTime]::UtcNow.ToString('o')
        vm_name = $VmName
        vm_uuid = $vm.Uuid
        vm_original_state = $originalState
        source_vdi = $vm.Vdi
        source_vdi_uuid = $mediumUuid
        guest_log_path = '/the one/logs'
        filesystem_initial_check_exit_code = $filesystemInitialCheckExitCode
        filesystem_journal_pending = $filesystemJournalPending
        filesystem_repair_performed = $filesystemRepairPerformed
        filesystem_repair_exit_code = $filesystemRepairExitCode
        filesystem_check_exit_code = $filesystemCheckExitCode
        file_count = $fileCount
        content_bytes = $contentBytes
        archive = 'logs.tar.gz'
        archive_sha256 = $archiveHash
        browsable_copy = 'logs'
        serial_log_copied = $serialCopied
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Destination 'manifest.json') -Encoding utf8
    $completed = $true

    Write-Host "Extracted $fileCount log files ($contentBytes bytes) to:"
    Write-Host "  $Destination"
    Write-Host "Archive SHA-256: $archiveHash"
    Remove-T1OSExpiredLogExports
}
finally {
    if ($runtimeMounted) {
        & wsl.exe -u root --exec umount $mountPoint *> $null
        $runtimeMounted = $false
    }
    & wsl.exe -u root --exec rmdir $mountPoint *> $null

    if (-not $KeepRawClone -and (Test-Path -LiteralPath $temporaryRoot -PathType Container)) {
        $resolvedTemporaryParent = [System.IO.Path]::GetFullPath($temporaryParent).TrimEnd('\') + '\'
        $resolvedTemporaryRoot = [System.IO.Path]::GetFullPath($temporaryRoot)
        if (-not $resolvedTemporaryRoot.StartsWith($resolvedTemporaryParent, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove unexpected temporary path: $resolvedTemporaryRoot"
        }
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }

    if ($resumeVm) {
        Write-Host "Restoring VM '$VmName' to its original running state..."
        Invoke-T1OSVBox -Arguments @('startvm', $VmName, '--type', 'gui')
        [void](Wait-T1OSVmState -Expected @('running'))
    }
}

if (-not $completed) {
    throw 'T1OS log extraction did not complete.'
}
