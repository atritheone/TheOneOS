[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$environmentRoot = Join-Path $projectRoot 'environment'
$hardwareRoot = Join-Path $environmentRoot 'hardware'
$baseVdi = Join-Path $environmentRoot 't1os-root.vdi'
$bootIso = Join-Path $environmentRoot 't1os-boot.iso'
$guestAdditions = Join-Path $projectRoot 'source\software\virtualbox\guestadditions.py'
$testAgent = Join-Path $projectRoot 'source\software\virtualbox\vmtestagent.py'
$buildRoot = Join-Path $projectRoot 'source\build software'
$bootAnimation = Join-Path $projectRoot 'source\boot\boot animation\boot animation.py'
$terminalFixture = Join-Path $PSScriptRoot 'fixtures\brick terminal emulator.py'
$pythonIndex = Join-Path $hardwareRoot 't1os-python-index'
$profiledPythonConfig = Join-Path $projectRoot 'source\python\build\runtime.json'
$manifestPath = Join-Path $hardwareRoot 't1os-vm-test-base.json'
$templateRoot = Join-Path $hardwareRoot 'vm-test-template'
$baseVmName = 'The One OS'
$templateName = 'T1OS Codex Test Base'
$snapshotName = 'codex-clean'

function Get-T1OSVBoxManage {
    $command = Get-Command VBoxManage -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $default = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
    if (Test-Path -LiteralPath $default -PathType Leaf) {
        return $default
    }
    throw 'VBoxManage was not found.'
}

function Invoke-T1OSVBox {
    param([Parameter(Mandatory)][string[]]$Arguments)

    & $script:vbox @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "VBoxManage $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

function Get-T1OSVmInfo {
    param([Parameter(Mandatory)][string]$Name)

    $output = @(& $script:vbox showvminfo $Name --machinereadable 2>$null)
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    return $output
}

function Get-T1OSVmState {
    param([Parameter(Mandatory)][string[]]$Info)

    $line = $Info | Where-Object { $_ -match '^VMState=' } | Select-Object -First 1
    if (-not $line) {
        return 'missing'
    }
    return ([string]$line).Split('=', 2)[1].Trim('"')
}

function Get-T1OSSignature {
    $base = Get-Item -LiteralPath $baseVdi
    $iso = Get-Item -LiteralPath $bootIso
    $buildFiles = @(Get-ChildItem -LiteralPath $buildRoot -Recurse -File -Force |
        Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' } |
        Sort-Object FullName)
    $buildLines = foreach ($file in $buildFiles) {
        $relative = $file.FullName.Substring($buildRoot.Length).TrimStart('\') -replace '\\', '/'
        "$relative`0$((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant())"
    }
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $buildBytes = [System.Text.Encoding]::UTF8.GetBytes(($buildLines -join "`n"))
        $buildHash = ([BitConverter]::ToString($hasher.ComputeHash($buildBytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $hasher.Dispose()
    }
    return [ordered]@{
        format = 1
        base_vdi_length = [int64]$base.Length
        base_vdi_write_ticks = [int64]$base.LastWriteTimeUtc.Ticks
        boot_iso_length = [int64]$iso.Length
        boot_iso_write_ticks = [int64]$iso.LastWriteTimeUtc.Ticks
        guest_additions_sha256 = (Get-FileHash -LiteralPath $guestAdditions -Algorithm SHA256).Hash.ToLowerInvariant()
        test_agent_sha256 = (Get-FileHash -LiteralPath $testAgent -Algorithm SHA256).Hash.ToLowerInvariant()
        boot_animation_sha256 = (Get-FileHash -LiteralPath $bootAnimation -Algorithm SHA256).Hash.ToLowerInvariant()
        terminal_fixture_sha256 = (Get-FileHash -LiteralPath $terminalFixture -Algorithm SHA256).Hash.ToLowerInvariant()
        python_index_sha256 = Get-T1OSDirectoryHash -Path $pythonIndex
        profiled_python_config_sha256 = (Get-FileHash -LiteralPath $profiledPythonConfig -Algorithm SHA256).Hash.ToLowerInvariant()
        template_builder_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
        build_tree_sha256 = $buildHash
        build_file_count = $buildFiles.Count
    }
}

function Get-T1OSDirectoryHash {
    param([Parameter(Mandatory)][string]$Path)

    $files = @(Get-ChildItem -LiteralPath $Path -Recurse -File -Force | Sort-Object FullName)
    $lines = foreach ($file in $files) {
        $relative = $file.FullName.Substring($Path.Length).TrimStart('\') -replace '\\', '/'
        "$relative`0$((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant())"
    }
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
        return ([BitConverter]::ToString($hasher.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $hasher.Dispose()
    }
}

function Test-T1OSCurrentTemplate {
    param([Parameter(Mandatory)]$Signature)

    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        return $false
    }
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    }
    catch {
        return $false
    }
    foreach ($name in $Signature.Keys) {
        if ([string]$manifest.signature.$name -cne [string]$Signature[$name]) {
            return $false
        }
    }
    $info = Get-T1OSVmInfo -Name $templateName
    if (-not $info -or (Get-T1OSVmState -Info $info) -ne 'poweroff') {
        return $false
    }
    $expectedIso = [System.IO.Path]::GetFullPath($bootIso)
    $attachedIso = $null
    foreach ($line in $info) {
        if ([string]$line -match '^"SATA-[0-9]+-[0-9]+"="(.+\.iso)"$') {
            $attachedIso = [System.IO.Path]::GetFullPath(($Matches[1] -replace '\\\\', '\'))
            break
        }
    }
    if (-not $attachedIso -or $attachedIso -cne $expectedIso) {
        return $false
    }
    $snapshots = @(& $script:vbox snapshot $templateName list --machinereadable 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not ($snapshots -match ('^SnapshotName.*="' + [regex]::Escape($snapshotName) + '"$'))) {
        return $false
    }
    return $true
}

function Remove-T1OSTemplateDirectory {
    if (-not (Test-Path -LiteralPath $templateRoot)) {
        return
    }
    $resolved = [System.IO.Path]::GetFullPath($templateRoot)
    $allowed = [System.IO.Path]::GetFullPath($hardwareRoot).TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($allowed, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "refusing to remove unexpected VM test template path: $resolved"
    }
    # VBoxManage unregistervm --delete can return just before VBoxSVC releases
    # the cloned VDI on Windows. Retry this exact disposable path briefly so a
    # harmless asynchronous close does not make template refresh flaky.
    for ($attempt = 1; $attempt -le 40; $attempt++) {
        try {
            Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction Stop
            return
        }
        catch {
            if (-not (Test-Path -LiteralPath $resolved)) {
                return
            }
            if ($attempt -eq 40) {
                throw
            }
            Start-Sleep -Milliseconds 250
        }
    }
}

function Get-T1OSAttachedVdi {
    param([Parameter(Mandatory)][string[]]$Info)

    foreach ($line in $Info) {
        if ([string]$line -match '^"SATA-[0-9]+-[0-9]+"="(.+\.vdi)"$') {
            return ($Matches[1] -replace '\\\\', '\')
        }
    }
    throw "the VM '$templateName' has no attached VDI."
}

function Install-T1OSTestAgent {
    param(
        [Parameter(Mandatory)][string]$Vdi,
        [Parameter(Mandatory)]$Signature
    )

    $wslVdi = ([string](& wsl.exe -d Ubuntu --exec wslpath -a $Vdi | Select-Object -First 1)).Trim()
    $wslGuest = ([string](& wsl.exe -d Ubuntu --exec wslpath -a $guestAdditions | Select-Object -First 1)).Trim()
    $wslAgent = ([string](& wsl.exe -d Ubuntu --exec wslpath -a $testAgent | Select-Object -First 1)).Trim()
    $wslBuild = ([string](& wsl.exe -d Ubuntu --exec wslpath -a $buildRoot | Select-Object -First 1)).Trim()
    $wslBootAnimation = ([string](& wsl.exe -d Ubuntu --exec wslpath -a $bootAnimation | Select-Object -First 1)).Trim()
    $wslTerminalFixture = ([string](& wsl.exe -d Ubuntu --exec wslpath -a $terminalFixture | Select-Object -First 1)).Trim()
    $wslPythonIndex = ([string](& wsl.exe -d Ubuntu --exec wslpath -a $pythonIndex | Select-Object -First 1)).Trim()
    $wslProfiledPythonConfig = ([string](& wsl.exe -d Ubuntu --exec wslpath -a $profiledPythonConfig | Select-Object -First 1)).Trim()
    if (-not $wslVdi -or -not $wslGuest -or -not $wslAgent -or -not $wslBuild -or -not $wslBootAnimation -or -not $wslTerminalFixture -or -not $wslPythonIndex -or -not $wslProfiledPythonConfig) {
        throw 'WSL could not resolve the VM test image inputs.'
    }

    $install = @'
set -eu
vdi=$1
guest=$2
agent=$3
build=$4
boot_animation=$5
terminal_fixture=$6
python_index=$7
guest_hash=$8
agent_hash=$9
boot_animation_hash=${10}
terminal_fixture_hash=${11}
profiled_python_config=${12}
profiled_list=$(mktemp /var/tmp/t1os-profiled-python.XXXXXX)
device=
mount_point="/mnt/t1os-vm-test-$$"
mounted=0
cleanup() {
    status=$?
    if [ "$mounted" = 1 ]; then
        sync || true
        umount "$mount_point" 2>/dev/null || true
    fi
    if [ -n "$device" ]; then
        qemu-nbd --disconnect "$device" >/dev/null 2>&1 || true
    fi
    rmdir "$mount_point" 2>/dev/null || true
    rm -f -- "$profiled_list"
    exit "$status"
}
trap cleanup EXIT INT TERM

require_profiled_source() {
    source_path=$1
    [ -f "$source_path" ] && [ ! -L "$source_path" ] || {
        echo "profiled Python source is missing or redirected: $source_path" >&2
        exit 1
    }
    printf '#!"/the one/software/python/bin/python" -B\n' | cmp -n 43 - "$source_path" >/dev/null || {
        echo "profiled Python source lacks the exact byte-0 LF shebang: $source_path" >&2
        exit 1
    }
}

modprobe nbd max_part=16
for candidate in /dev/nbd*; do
    name=${candidate#/dev/}
    if [ ! -s "/sys/block/$name/pid" ]; then
        device=$candidate
        break
    fi
done
[ -n "$device" ] || { echo 'no free NBD device is available' >&2; exit 1; }

qemu-nbd --connect="$device" --format=vdi "$vdi"
attempt=0
while [ "$(blkid -s TYPE -o value "$device" 2>/dev/null || true)" != ext4 ]; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt 40 ] || { echo 'test VDI did not expose an ext4 filesystem' >&2; exit 1; }
    sleep 0.1
done

mkdir -p "$mount_point"
mount -o rw,nosuid,nodev "$device" "$mount_point"
mounted=1
python3 -B - "$profiled_python_config" "$profiled_list" <<'PY'
import json
from pathlib import Path, PurePosixPath
import sys

config = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
policy = config.get('profiled_python_entrypoints')
if (
    not isinstance(policy, dict)
    or policy.get('format') != 1
    or policy.get('owner') != 0
    or policy.get('group') != 0
    or policy.get('install_mode') != '0555'
    or policy.get('shebang') != '#!"/the one/software/python/bin/python" -B\n'
    or not isinstance(policy.get('entries'), list)
):
    raise SystemExit('profiled Python policy is malformed')
roots = config.get('protected_external_roots')
if not isinstance(roots, list):
    raise SystemExit('protected external root policy is malformed')
roots_by_name = {}
for root in roots:
    if not isinstance(root, dict):
        raise SystemExit('protected external root record is malformed')
    name = root.get('name')
    destination = root.get('destination')
    if (
        not isinstance(name, str)
        or not name
        or name in roots_by_name
        or not isinstance(destination, str)
        or not destination.startswith('/')
        or str(PurePosixPath(destination)) != destination
    ):
        raise SystemExit('protected external root record is malformed')
    roots_by_name[name] = destination

rows = []
destinations = []
for entry in policy['entries']:
    if not isinstance(entry, dict) or set(entry) != {'root', 'path', 'destination'}:
        raise SystemExit('profiled Python entrypoint record is malformed')
    root_name = entry['root']
    relative_text = entry['path']
    if root_name not in roots_by_name or not isinstance(relative_text, str):
        raise SystemExit('profiled Python entrypoint root or path is invalid')
    relative = PurePosixPath(relative_text)
    if (
        not relative_text
        or relative.is_absolute()
        or relative_text != str(relative)
        or any(part in ('', '.', '..') for part in relative.parts)
        or relative.suffix != '.py'
    ):
        raise SystemExit('profiled Python entrypoint path is invalid')
    expected_destination = str(PurePosixPath(roots_by_name[root_name]) / relative)
    if entry['destination'] != expected_destination:
        raise SystemExit('profiled Python entrypoint destination is invalid')
    rows.append(f"{root_name}\t{relative_text}")
    destinations.append(expected_destination)
if (
    len(rows) != len(set(rows))
    or len(destinations) != len(set(destinations))
    or destinations != sorted(destinations)
):
    raise SystemExit('profiled Python entrypoint inventory is duplicated or unsorted')
rows.sort()
Path(sys.argv[2]).write_text('\n'.join(rows) + '\n', encoding='utf-8', newline='\n')
PY
destination="$mount_point/the one/software/virtualbox"
[ -d "$destination" ] || { echo 'VirtualBox guest software directory is missing' >&2; exit 1; }
require_profiled_source "$guest"
install -m 0555 "$guest" "$destination/guestadditions.py"
grep -Fqx "virtualbox_software$(printf '\t')guestadditions.py" "$profiled_list"
install -m 0444 "$agent" "$destination/vmtestagent.py"
[ "$(sha256sum "$destination/guestadditions.py" | cut -d' ' -f1)" = "$guest_hash" ]
[ "$(sha256sum "$destination/vmtestagent.py" | cut -d' ' -f1)" = "$agent_hash" ]

boot_destination="$mount_point/boot/boot animation/boot animation.py"
require_profiled_source "$boot_animation"
install -D -m 0555 "$boot_animation" "$boot_destination"
grep -Fqx "boot$(printf '\t')boot animation/boot animation.py" "$profiled_list"
[ "$(sha256sum "$boot_destination" | cut -d' ' -f1)" = "$boot_animation_hash" ]

# Remove the exact interpreter alias left by older VM templates. Current T1OS
# kernels execute the quoted canonical interpreter path directly.
python_alias="$mount_point/t1python"
python_target="/the one/software/python/bin/python"
if [ -L "$python_alias" ]; then
    [ "$(readlink "$python_alias")" = "$python_target" ] || {
        echo 'the VM Python alias points at an unexpected target' >&2
        exit 1
    }
	rm -- "$python_alias"
elif [ -e "$python_alias" ]; then
    echo 'the VM Python alias path is not a symbolic link' >&2
    exit 1
fi
[ ! -e "$python_alias" ] && [ ! -L "$python_alias" ]

developer_policy="$mount_point/t1os-developer-policy"
printf '%s\n' enabled > "$developer_policy"
chown 0:0 "$developer_policy"
chmod 0400 "$developer_policy"
[ "$(cat "$developer_policy")" = enabled ]

vm_test_marker="$mount_point/t1os-vm-test-agent"
printf '%s\n' enabled > "$vm_test_marker"
chown 0:0 "$vm_test_marker"
chmod 0400 "$vm_test_marker"

build_destination="$mount_point/the one/build"
[ -d "$build_destination" ] || { echo 'T1OS build directory is missing' >&2; exit 1; }
find "$build_destination" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$build" -type f ! -path '*/__pycache__/*' -print0 | while IFS= read -r -d '' source_file; do
    relative=${source_file#"$build"/}
    destination_file="$build_destination/$relative"
    install_mode=0444
    if grep -Fqx "build_software$(printf '\t')$relative" "$profiled_list"; then
        require_profiled_source "$source_file"
        install_mode=0555
    fi
    install -D -m "$install_mode" "$source_file" "$destination_file"
    cmp -s "$source_file" "$destination_file" || {
        echo "current build overlay did not copy correctly: $relative" >&2
        exit 1
    }
done

# Package discovery and installation use the real manager paths against a
# deterministic, root-owned local PyPI mirror.  This makes feature runs fast,
# repeatable, and independent of the host network while still resolving a
# genuine third-party wheel.
python_index_destination="$mount_point/software/t1os-python-index"
[ ! -e "$python_index_destination" ] || {
    echo 'the VM Python test index destination already exists' >&2
    exit 1
}
mkdir -p "$python_index_destination"
find "$python_index" -type l -print -quit | grep -q . && {
    echo 'the VM Python test index contains a symbolic link' >&2
    exit 1
}
find "$python_index" -type f -print0 | while IFS= read -r -d '' source_file; do
    relative=${source_file#"$python_index"/}
    install -D -m 0444 "$source_file" "$python_index_destination/$relative"
    cmp -s "$source_file" "$python_index_destination/$relative"
done
find "$python_index_destination" -type d -exec chmod 0555 {} +
chown -R 0:0 "$python_index_destination"

python3 -B - "$build_destination/python/tools.json" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
configuration = json.loads(path.read_text(encoding='utf-8'))
configuration['index_url'] = 'file:///software/t1os-python-index/simple/'
configuration['project_json_url'] = 'file:///software/t1os-python-index/pypi/{name}/json'
path.write_text(json.dumps(configuration, indent=2, sort_keys=True) + '\n', encoding='utf-8')
PY
chown 0:0 "$build_destination/python/tools.json"
chmod 0444 "$build_destination/python/tools.json"

# The release LSM intentionally makes the runtime image and catalogue
# immutable.  Publish one root-owned, non-user-writable package area for the
# signed disposable VM and make the ordinary interpreter discover its managed
# site directory.  GODDESS supplies the matching manager-only environment.
python_test_root="$mount_point/software/t1os-python"
for directory in management site-packages bin catalogue; do
    mkdir -p "$python_test_root/$directory"
    chown 0:0 "$python_test_root/$directory"
    chmod 0755 "$python_test_root/$directory"
done
chown 0:0 "$python_test_root"
chmod 0755 "$python_test_root"
system_site_packages=$(find "$mount_point/the one/software/python/lib" -mindepth 2 -maxdepth 2 -type d -path '*/python*/site-packages' -print)
[ "$(printf '%s\n' "$system_site_packages" | sed '/^$/d' | wc -l)" -eq 1 ] || {
    echo 'the VM system Python site-packages directory is ambiguous' >&2
    exit 1
}
printf '%s\n' '/software/t1os-python/site-packages' > "$system_site_packages/t1os-vm-test-managed.pth"
chown 0:0 "$system_site_packages/t1os-vm-test-managed.pth"
chmod 0444 "$system_site_packages/t1os-vm-test-managed.pth"

profiled_tab=$(printf '\t')
while IFS="$profiled_tab" read -r profile_root profile_relative; do
    case "$profile_root" in
        build_software)
            profile_source="$build/$profile_relative"
            profile_destination="$build_destination/$profile_relative"
            ;;
        boot)
            [ "$profile_relative" = 'boot animation/boot animation.py' ] || {
                echo "unsupported boot profile entrypoint: $profile_relative" >&2
                exit 1
            }
            profile_source="$boot_animation"
            profile_destination="$boot_destination"
            ;;
        virtualbox_software)
            [ "$profile_relative" = 'guestadditions.py' ] || {
                echo "unsupported VirtualBox profile entrypoint: $profile_relative" >&2
                exit 1
            }
            profile_source="$guest"
            profile_destination="$destination/guestadditions.py"
            ;;
        *)
            echo "unsupported profiled Python root: $profile_root" >&2
            exit 1
            ;;
    esac
    require_profiled_source "$profile_source"
    [ -f "$profile_destination" ] && [ ! -L "$profile_destination" ] || {
        echo "profiled Python destination is missing or redirected: $profile_destination" >&2
        exit 1
    }
    cmp -s -- "$profile_source" "$profile_destination" || {
        echo "profiled Python destination content differs: $profile_destination" >&2
        exit 1
    }
    [ "$(stat -c '%u:%g:%a:%h' "$profile_destination")" = '0:0:555:1' ] || {
        echo "profiled Python destination identity differs: $profile_destination" >&2
        exit 1
    }
done < "$profiled_list"

# Every disposable clone starts with the same development login. Provision it
# through T1OS's own credential broker so the image contains a policy-valid
# password hash and correctly owned private home tree.
printf '%s\n' password | PYTHONPATH="$build_destination" python3 -c \
    'import sys; from broker import broker; broker.provision_user(sys.argv[1], "development", sys.stdin.read().rstrip("\r\n"))' \
    "$mount_point"

# Put the arbitrary program in the private development home, matching a file
# the signed-in user created and then ran from an ordinary shell.  VM-only
# infrastructure such as the agent and package mirror stays root-owned.
terminal_fixture_destination="$mount_point/master/development/terminal_test.py"
install -m 0755 "$terminal_fixture" "$terminal_fixture_destination"
chown 1000:1000 "$terminal_fixture_destination"
[ "$(sha256sum "$terminal_fixture_destination" | cut -d' ' -f1)" = "$terminal_fixture_hash" ]
sync
umount "$mount_point"
mounted=0
e2fsck -f -n "$device"
qemu-nbd --disconnect "$device"
device=
rmdir "$mount_point"
'@

    & wsl.exe -d Ubuntu -u root --exec bash -c $install bash $wslVdi $wslGuest $wslAgent $wslBuild $wslBootAnimation $wslTerminalFixture $wslPythonIndex $Signature.guest_additions_sha256 $Signature.test_agent_sha256 $Signature.boot_animation_sha256 $Signature.terminal_fixture_sha256 $wslProfiledPythonConfig
    if ($LASTEXITCODE -ne 0) {
        throw "could not install the bounded VM test agent into '$Vdi'."
    }
}

$script:vbox = Get-T1OSVBoxManage
foreach ($path in @($baseVdi, $bootIso, $guestAdditions, $testAgent, $bootAnimation, $terminalFixture, $profiledPythonConfig)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "required VM test input is missing: $path"
    }
}
if (-not (Test-Path -LiteralPath $pythonIndex -PathType Container)) {
    throw "required VM test Python index is missing: $pythonIndex"
}
if (-not (Test-Path -LiteralPath $buildRoot -PathType Container)) {
    throw "required VM test build tree is missing: $buildRoot"
}
New-Item -ItemType Directory -Path $hardwareRoot -Force | Out-Null

$baseInfo = Get-T1OSVmInfo -Name $baseVmName
if (-not $baseInfo) {
    throw "base VirtualBox VM '$baseVmName' is not registered."
}
if ((Get-T1OSVmState -Info $baseInfo) -ne 'poweroff') {
    throw "base VirtualBox VM '$baseVmName' must be powered off."
}

$signature = Get-T1OSSignature
if (-not $Force -and (Test-T1OSCurrentTemplate -Signature $signature)) {
    Write-Host "reusing current VM test template '$templateName'."
    Write-Host "Manifest: $manifestPath"
    exit 0
}

$templateInfo = Get-T1OSVmInfo -Name $templateName
if ($templateInfo) {
    if ((Get-T1OSVmState -Info $templateInfo) -ne 'poweroff') {
        throw "VM test template '$templateName' must be powered off before replacement."
    }
    Invoke-T1OSVBox -Arguments @('unregistervm', $templateName, '--delete')
}
Remove-T1OSTemplateDirectory
New-Item -ItemType Directory -Path $templateRoot -Force | Out-Null

try {
    Write-Host 'creating the one-time full VM test template from the last validated base VDI...'
    Invoke-T1OSVBox -Arguments @(
        'clonevm', $baseVmName,
        '--name', $templateName,
        '--basefolder', $templateRoot,
        '--mode', 'machine',
        '--register'
    )
    # VBoxManage's headless scan-code injection targets the emulated PS/2
    # controller.  T1OS also discovers that controller as its physical evdev
    # keyboard, whereas a USB keyboard configured without an attached HID can
    # silently discard automation input.  Keep the disposable test appliance
    # aligned with the device that the guest actually opens.
    Invoke-T1OSVBox -Arguments @('modifyvm', $templateName, '--keyboard', 'ps2')
    # The registered release VM may intentionally leave its optical drive
    # empty after a build. The Codex template must always boot the exact ISO in
    # its signed input manifest, independent of that mutable machine state.
    Invoke-T1OSVBox -Arguments @(
        'storageattach', $templateName,
        '--storagectl', 'SATA', '--port', '1', '--device', '0',
        '--type', 'dvddrive', '--medium', $bootIso
    )
    $templateInfo = Get-T1OSVmInfo -Name $templateName
    $templateVdi = Get-T1OSAttachedVdi -Info $templateInfo
    Write-Host 'installing the restricted file-based test agent into the test-only derivative...'
    Install-T1OSTestAgent -Vdi $templateVdi -Signature $signature
    Invoke-T1OSVBox -Arguments @('snapshot', $templateName, 'take', $snapshotName, '--description', 'Immutable Codex VM test baseline')

    $manifest = [ordered]@{
        format = 1
        template_vm = $templateName
        snapshot = $snapshotName
        template_vdi = $templateVdi
        created_at = [DateTime]::UtcNow.ToString('o')
        signature = $signature
    }
    $manifest | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $manifestPath -Encoding utf8
}
catch {
    $failedInfo = Get-T1OSVmInfo -Name $templateName
    if ($failedInfo -and (Get-T1OSVmState -Info $failedInfo) -eq 'poweroff') {
        & $script:vbox unregistervm $templateName --delete *> $null
    }
    throw
}

Write-Host "VM test template '$templateName' is ready."
Write-Host "Manifest: $manifestPath"
exit 0
