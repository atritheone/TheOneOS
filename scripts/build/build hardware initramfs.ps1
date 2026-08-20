[CmdletBinding()]
param(
    [switch]$Candidate314
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
if ($Candidate314) {
    throw (
        'Python candidate roots are non-deployable because they contain a generated ' +
        'snapshot of /the one/build. Package and promote the candidate, then build the ' +
        'initramfs from the canonical source/software/python release instead.'
    )
}
$busyBoxSource = Join-Path $projectRoot 'environment\software\initramfs\bin\busybox'
$initSource = Join-Path $projectRoot 'source\entry\init\init hardware.sh'
$recoverySource = Join-Path $projectRoot 'source\entry\init\angel recovery.sh'
$recoveryAuthSource = Join-Path $projectRoot 'source\entry\recoveryauth\recoveryauth.c'
$pythonManifest = if ($Candidate314) {
    Join-Path $projectRoot 'development\python 3.14 candidate\t1os\manifest.json'
}
else {
    Join-Path $projectRoot 'source\software\python\manifest.json'
}
$pythonReleaseLock = if ($Candidate314) {
    Join-Path $projectRoot 'development\python 3.14 candidate\t1os\boot-release.json'
}
else {
    Join-Path $projectRoot 'source\python\locks\release.json'
}
$pythonVerifier = Join-Path $projectRoot 'scripts\tests\test python runtime.ps1'
$pythonRuntimeConfig = Join-Path $projectRoot 'source\python\build\runtime.json'
$bootPolicyBuilder = Join-Path $projectRoot 'scripts\build\build boot protected roots.py'
$bootPolicyDirectory = Join-Path $projectRoot 'development\hardware boot policy'
$bootPolicyManifest = Join-Path $bootPolicyDirectory 'protected-roots.json'
$ntfsCheckerBuilder = Join-Path $projectRoot 'scripts\build\build roothealth.ps1'
$ntfsCheckerSource = Join-Path $projectRoot 'environment\hardware\tools\roothealth'
$firmwareArchive = Join-Path $projectRoot 'environment\hardware\firmware.tar.zst'
$outputDirectory = Join-Path $projectRoot 'environment\hardware\boot'
$outputPath = Join-Path $outputDirectory 'initramfs-hardware'
$stageRoot = Join-Path $projectRoot 'development\hardware initramfs stage'

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

$requiredFiles = @($busyBoxSource, $initSource, $recoverySource, $recoveryAuthSource, $pythonManifest, $pythonReleaseLock, $pythonRuntimeConfig, $bootPolicyBuilder, $ntfsCheckerBuilder)
if (-not $Candidate314) {
    $requiredFiles += $pythonVerifier
}
foreach ($requiredFile in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required initramfs input not found: $requiredFile"
    }
}

& $ntfsCheckerBuilder
if (-not $?) {
    throw 'The roothealth build failed before initramfs construction.'
}
if (-not (Test-Path -LiteralPath $ntfsCheckerSource -PathType Leaf)) {
    throw "The roothealth artifact is missing: $ntfsCheckerSource"
}

New-Item -ItemType Directory -Path $bootPolicyDirectory -Force | Out-Null
$wslBootPolicyBuilder = ConvertTo-WslPath -WindowsPath $bootPolicyBuilder
$wslProjectRoot = ConvertTo-WslPath -WindowsPath $projectRoot
$wslBootPolicyManifest = ConvertTo-WslPath -WindowsPath $bootPolicyManifest
& wsl.exe -d Ubuntu --exec python3 -B $wslBootPolicyBuilder `
    --repo $wslProjectRoot --output $wslBootPolicyManifest
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $bootPolicyManifest -PathType Leaf)) {
    throw 'The independent boot protected-root policy build failed.'
}

try {
    $manifestObject = Get-Content -Raw -LiteralPath $pythonManifest | ConvertFrom-Json
    $releaseObject = Get-Content -Raw -LiteralPath $pythonReleaseLock | ConvertFrom-Json
}
catch {
    throw "The initramfs cannot read the managed Python manifest or immutable release lock: $($_.Exception.Message)"
}

$lockedManifestHash = if ($Candidate314) {
    [string]$releaseObject.manifest_sha256
}
else {
    [string]$releaseObject.outputs.manifest_sha256
}
if ($lockedManifestHash -cnotmatch '^[0-9a-f]{64}$') {
    throw 'The immutable Python release lock has no valid outputs.manifest_sha256 value.'
}
$actualManifestHash = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $pythonManifest
).Hash.ToLowerInvariant()
if ($Candidate314) {
    if (
        [string]$manifestObject.component -cne 't1os-python-candidate' -or
        [string]$manifestObject.candidate_release -cne [string]$releaseObject.release -or
        [string]$manifestObject.python_version -cne '3.14.7' -or
        [string]$manifestObject.python_abi -cne 'cp314' -or
        [string]$releaseObject.component -cne 't1os-python-candidate-boot' -or
        $actualManifestHash -cne $lockedManifestHash
    ) {
        throw 'The initramfs cannot attest this Python 3.14 candidate payload.'
    }
}
elseif (
    [string]$manifestObject.state -cne 'verified' -or
    [string]$manifestObject.release -cne [string]$releaseObject.release -or
    $actualManifestHash -cne $lockedManifestHash -or
    [string]$manifestObject.software.tree.sha256 -cne [string]$releaseObject.outputs.software_tree.sha256 -or
    [string]$manifestObject.catalogue.tree.sha256 -cne [string]$releaseObject.outputs.catalogue_tree.sha256
) {
    throw 'The initramfs cannot attest a Python payload that differs from release zero.'
}

# Verify the deployment payload that this initramfs actually embeds. The full
# release verifier also binds mutable host-side protected roots which are not
# copied into the initramfs; their unrelated development drift must not block a
# byte-identical, release-locked Python deployment payload.
if (-not $Candidate314) {
    # This verifier is consumed as machine-readable build input. Bypass the
    # incremental test wrapper so a cache-status line cannot replace its JSON.
    $previousIncrementalScript = $env:T1OS_INCREMENTAL_ACTIVE_SCRIPT
    try {
        $env:T1OS_INCREMENTAL_ACTIVE_SCRIPT = 'scripts/tests/test python runtime.ps1'
        $verificationJson = (& $pythonVerifier -DeploymentPayloadOnly | Out-String)
        $verificationExitCode = $LASTEXITCODE
    }
    finally {
        $env:T1OS_INCREMENTAL_ACTIVE_SCRIPT = $previousIncrementalScript
    }
    if ($verificationExitCode -ne 0) {
        throw "The canonical Python verifier failed before initramfs construction (exit code $verificationExitCode)."
    }
    try {
        $verificationObject = $verificationJson | ConvertFrom-Json
    }
    catch {
        throw "The canonical Python verifier returned malformed JSON: $($_.Exception.Message)"
    }
    if (
        [string]$verificationObject.release -cne [string]$manifestObject.release -or
        [string]$verificationObject.manifest_sha256 -cne $lockedManifestHash -or
        [int]$verificationObject.software_files -le 0 -or
        [int]$verificationObject.catalogue_files -le 0
    ) {
        throw 'The Python deployment verifier did not confirm the locked initramfs payload.'
    }
}

if (-not (Test-Path -LiteralPath $firmwareArchive -PathType Leaf)) {
    throw "Hardware firmware has not been staged. Run 'stage hardware firmware.ps1' first."
}

if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null

$wslBusyBox = ConvertTo-WslPath -WindowsPath $busyBoxSource
$wslInit = ConvertTo-WslPath -WindowsPath $initSource
$wslRecovery = ConvertTo-WslPath -WindowsPath $recoverySource
$wslRecoveryAuth = ConvertTo-WslPath -WindowsPath $recoveryAuthSource
$wslFirmware = ConvertTo-WslPath -WindowsPath $firmwareArchive
$wslPythonManifest = ConvertTo-WslPath -WindowsPath $pythonManifest
$wslPythonReleaseLock = ConvertTo-WslPath -WindowsPath $pythonReleaseLock
$wslPythonRuntimeConfig = ConvertTo-WslPath -WindowsPath $pythonRuntimeConfig
$wslBootPolicyManifest = ConvertTo-WslPath -WindowsPath $bootPolicyManifest
$wslNtfsChecker = ConvertTo-WslPath -WindowsPath $ntfsCheckerSource
$wslStage = ConvertTo-WslPath -WindowsPath $stageRoot
$wslOutput = ConvertTo-WslPath -WindowsPath $outputPath
$candidateMode = if ($Candidate314) { '1' } else { '0' }

$buildCommand = @'
set -euo pipefail

busybox=$1
init=$2
firmware_archive=$3
: "$4" # Reserved staging argument; archive construction uses native Linux storage.
output=$5
python_manifest=$6
python_release_lock=$7
ntfs_checker=$8
candidate_mode=$9
recovery_script=${10}
profiled_python_config=${11}
boot_policy_manifest=${12}
recovery_auth_source=${13}
umask 022
export LC_ALL=C

# DrvFS without metadata reports every staged path as 0777.  Build the archive
# on the WSL distribution's native filesystem so cpio receives real POSIX
# modes, then publish only the completed archive back to the workspace.
work=$(mktemp -d /var/tmp/t1os-hardware-initramfs.XXXXXX)
case "$work" in
    /var/tmp/t1os-hardware-initramfs.*) ;;
    *) echo "Unexpected initramfs work path: $work" >&2; exit 1 ;;
esac
rootfs="$work/rootfs"
early="$work/early"
firmware="$work/firmware"
output_tmp="${output}.building"
cleanup() {
    rm -f -- "$output_tmp"
    case "$work" in
        /var/tmp/t1os-hardware-initramfs.*) rm -rf -- "$work" ;;
    esac
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
rm -f -- "$output_tmp"
mkdir -p "$rootfs/bin" "$rootfs/dev" "$rootfs/proc" "$rootfs/sys" "$rootfs/run" "$rootfs/mnt"
mkdir -p "$rootfs/sbin" "$rootfs/lib" "$rootfs/lib64" "$rootfs/usr/lib"
mkdir -p "$early/kernel/x86/microcode" "$firmware"
tar --zstd -xf "$firmware_archive" -C "$firmware" ./amd-ucode ./intel-ucode

cp -- "$busybox" "$rootfs/bin/busybox"
cp -- "$init" "$rootfs/init"
cp -- "$recovery_script" "$rootfs/angel-recovery"
cp -- "$busybox" "$rootfs/bin/sh"
cp -- "$busybox" "$rootfs/bin/mdev"
chmod 0755 "$rootfs/bin/busybox" "$rootfs/bin/sh" "$rootfs/bin/mdev" "$rootfs/init" "$rootfs/angel-recovery"

# Destructive recovery must remain usable when the installed Python runtime is
# the component which failed.  Build a small, initramfs-native verifier for the
# versioned master credential formats; Angel sends the password only over this
# program's standard input and never executes authentication code from root.
cc -std=c11 -O2 -Wall -Wextra -Werror -D_FORTIFY_SOURCE=2 \
    -fstack-protector-strong -Wl,-z,relro,-z,now \
    -o "$rootfs/sbin/recoveryauth" "$recovery_auth_source" \
    -Wl,-l:libargon2.so.1 -lcrypto
ldd "$rootfs/sbin/recoveryauth" | awk '
    /=> \// { print $3 }
    /^[[:space:]]*\// { print $1 }
' | sort -u | while IFS= read -r library; do
    [ -f "$library" ] || continue
    destination="$rootfs$library"
    mkdir -p "$(dirname "$destination")"
    cp -L -- "$library" "$destination"
done

python3 - \
    "$python_manifest" \
    "$python_release_lock" \
    "$rootfs/protected-roots.tsv" \
    "$candidate_mode" \
    "$profiled_python_config" \
    "$rootfs/profiled-python-entrypoints.tsv" \
    "$boot_policy_manifest" <<'PY'
import hashlib
import json
from pathlib import Path
import re
import sys

manifest_path = Path(sys.argv[1])
release_path = Path(sys.argv[2])
output_path = Path(sys.argv[3])
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
release = json.loads(release_path.read_text(encoding='utf-8'))
manifest_bytes = manifest_path.read_bytes()
manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
candidate_mode = sys.argv[4] == '1'
runtime_config_path = Path(sys.argv[5])
profiled_output_path = Path(sys.argv[6])
boot_policy_path = Path(sys.argv[7])
runtime_config = json.loads(runtime_config_path.read_text(encoding='utf-8'))
boot_policy = json.loads(boot_policy_path.read_text(encoding='utf-8'))

safe_hash = re.compile(r'^[0-9a-f]{64}$')

def validate_path(value: object, *, allow_root: bool) -> str:
    if not isinstance(value, str) or not value or '\t' in value or '\n' in value or '\r' in value:
        raise SystemExit(f'Unrepresentable protected path: {value!r}')
    if value == '.':
        if allow_root:
            return value
        raise SystemExit('A protected file cannot use the root path')
    parts = value.split('/')
    if value.startswith('/') or any(part in ('', '.', '..') for part in parts):
        raise SystemExit(f'Non-canonical protected path: {value!r}')
    return value

profile_policy = boot_policy.get('profiled_python_entrypoints')
if (
    boot_policy.get('format') != 1
    or boot_policy.get('component') != 't1os-boot-protected-roots'
    or not isinstance(profile_policy, dict)
    or set(profile_policy) != {
        'format', 'owner', 'group', 'install_mode', 'shebang', 'entries'
    }
    or profile_policy.get('format') != 1
    or profile_policy.get('owner') != 0
    or profile_policy.get('group') != 0
    or profile_policy.get('install_mode') != '0555'
    or profile_policy.get('shebang') != '#!"/the one/software/python/bin/python" -B\n'
    or not isinstance(profile_policy.get('entries'), list)
    or not profile_policy['entries']
    or manifest.get('install_policy', {}).get('owner') != 0
    or manifest.get('install_policy', {}).get('group') != 0
):
    raise SystemExit('Python manifest differs from the canonical profiled-entrypoint policy')

root_destinations = {
    'build_software': '/the one/build',
    'boot': '/boot',
    'virtualbox_software': '/the one/software/virtualbox',
}
profiled = set()
profiled_destinations = []
for entry in profile_policy['entries']:
    if not isinstance(entry, dict) or set(entry) != {'root', 'path', 'destination'}:
        raise SystemExit('Profiled Python entrypoint record is malformed')
    name = entry['root']
    path = validate_path(entry['path'], allow_root=False)
    destination = entry['destination']
    if (
        name not in root_destinations
        or not path.endswith('.py')
        or destination != root_destinations[name].rstrip('/') + '/' + path
        or (name, path) in profiled
        or destination in profiled_destinations
    ):
        raise SystemExit(f'Profiled Python entrypoint identity differs: {entry!r}')
    profiled.add((name, path))
    profiled_destinations.append(destination)
if profiled_destinations != sorted(profiled_destinations):
    raise SystemExit('Profiled Python entrypoint inventory is not canonically ordered')
seen_profiled = set()

def validate_python_mode(name: str, path: str, mode: str) -> None:
    identity = (name, path)
    if identity in profiled:
        expected = '0555'
        seen_profiled.add(identity)
    elif path.endswith('.py'):
        expected = '0444'
    else:
        return
    if mode != expected:
        raise SystemExit(
            f'Python install mode differs for {name}/{path}: expected {expected}, got {mode}'
        )

def finish_profiled_inventory() -> None:
    if seen_profiled != profiled:
        raise SystemExit(
            'Protected manifest omits profiled Python entries: '
            + repr(sorted(profiled - seen_profiled))
        )
    profiled_output_path.write_text(
        ''.join(destination + '\n' for destination in profiled_destinations),
        encoding='utf-8',
        newline='\n',
    )

if candidate_mode:
    if (
        release.get('component') != 't1os-python-candidate-boot'
        or release.get('release') != manifest.get('candidate_release')
        or release.get('manifest_sha256') != manifest_digest
        or manifest.get('component') != 't1os-python-candidate'
        or manifest.get('python_version') != '3.14.7'
        or manifest.get('python_abi') != 'cp314'
    ):
        raise SystemExit('Python candidate manifest differs from its boot release lock')

    specs = [
        ('python_software', 'software', '/the one/software/python', False),
        ('python_catalogue', 'catalogue', '/the one/catalogue/python', False),
        ('image_catalogue', 'image', '/the one/catalogue/image', False),
        ('build_software', 'build_software', '/the one/build', True),
        ('boot', 'boot', '/boot', True),
        ('virtualbox_software', 'virtualbox_software', '/the one/software/virtualbox', True),
    ]
    payloads = manifest.get('payloads')
    destinations = manifest.get('destinations')
    if not isinstance(payloads, dict) or not isinstance(destinations, dict):
        raise SystemExit('Python candidate protected payloads are missing')

    rows = [f"H\t1\t{release['release']}\t{manifest_digest}\t6"]
    for name, key, destination, exclude_generated in specs:
        if destinations.get(key) != destination:
            raise SystemExit(f'Candidate destination differs: {key}')
        records = payloads.get(key)
        if not isinstance(records, list) or not records:
            raise SystemExit(f'Candidate payload inventory is missing: {key}')
        files = []
        directories = {'.'}
        seen = set()
        for item in records:
            if not isinstance(item, dict):
                raise SystemExit(f'Malformed candidate record: {key}')
            path = validate_path(item.get('path'), allow_root=False)
            size = item.get('size')
            digest = item.get('sha256')
            mode = item.get('install_mode')
            if (
                path in seen or not isinstance(size, int) or isinstance(size, bool) or size < 0
                or not isinstance(digest, str) or not safe_hash.fullmatch(digest)
                or mode not in ('0444', '0555')
            ):
                raise SystemExit(f'Invalid candidate file identity: {key}/{path}')
            if exclude_generated and ('__pycache__' in Path(path).parts or path.endswith(('.pyc', '.pyo'))):
                raise SystemExit(f'Generated bytecode entered candidate root: {key}/{path}')
            validate_python_mode(name, path, mode)
            seen.add(path)
            parent = Path(path).parent
            while str(parent) != '.':
                directories.add(parent.as_posix())
                parent = parent.parent
            files.append((path, size, digest, mode))
        if name == 'python_software':
            if 'manifest.json' in seen:
                raise SystemExit('Candidate software inventory includes its external manifest')
            files.append(('manifest.json', len(manifest_bytes), manifest_digest, '0444'))
        tree_input = ''.join(
            [f'D\t{path}\n' for path in sorted(directories)]
            + [f'F\t{path}\t{size}\t{digest}\t{mode}\n' for path, size, digest, mode in sorted(files)]
        ).encode()
        tree_digest = hashlib.sha256(tree_input).hexdigest()
        rows.append(
            f"R\t{name}\t{destination}\t{1 if exclude_generated else 0}\t"
            f"{len(directories)}\t{len(files)}\t{tree_digest}"
        )
        for path in sorted(directories):
            rows.append(f'D\t{name}\t{path}\t0755')
        for path, size, digest, mode in sorted(files):
            rows.append(f'F\t{name}\t{path}\t{size}\t{digest}\t{mode}')
    finish_profiled_inventory()
    output_path.write_text('\n'.join(rows) + '\n', encoding='utf-8', newline='\n')
    raise SystemExit(0)

if release.get('outputs', {}).get('manifest_sha256') != manifest_digest:
    raise SystemExit('Python manifest digest differs from the immutable release lock')
if manifest.get('state') != 'verified' or manifest.get('release') != release.get('release'):
    raise SystemExit('Python manifest identity differs from the immutable release lock')

expected_external = [
    ('image_catalogue', 'source/catalogue/image', '/the one/catalogue/image', False),
    ('build_software', 'source/build software', '/the one/build', True),
    ('boot', 'source/boot', '/boot', True),
    ('virtualbox_software', 'source/software/virtualbox', '/the one/software/virtualbox', True),
]
external = boot_policy.get('roots')
if not isinstance(external, list):
    raise SystemExit('Independent boot protected-root inventories are missing')
if len(external) != 4:
    raise SystemExit('Exactly four protected external root inventories are required')

root_specs = [
    ('python_software', manifest.get('software'), '/the one/software/python', False),
    ('python_catalogue', manifest.get('catalogue'), '/the one/catalogue/python', False),
]
for expected, item in zip(expected_external, external, strict=True):
    name, source, destination, exclude_generated = expected
    if not isinstance(item, dict):
        raise SystemExit(f'Malformed protected external root: {name}')
    if (
        item.get('name') != name
        or item.get('source') != source
        or item.get('destination') != destination
        or item.get('exclude_generated_bytecode') is not exclude_generated
    ):
        raise SystemExit(f'Protected external root policy differs: {name}')
    root_specs.append((name, item, destination, exclude_generated))

if manifest.get('software', {}).get('tree') != release.get('outputs', {}).get('software_tree'):
    raise SystemExit('Python software tree differs from the immutable release lock')
if manifest.get('catalogue', {}).get('tree') != release.get('outputs', {}).get('catalogue_tree'):
    raise SystemExit('Python native catalogue differs from the immutable release lock')

rows = [f"H\t1\t{release['release']}\t{manifest_digest}\t6"]
for name, inventory, destination, exclude_generated in root_specs:
    if not isinstance(inventory, dict) or inventory.get('destination') != destination:
        raise SystemExit(f'Malformed protected root inventory: {name}')
    directories = inventory.get('directories')
    files = inventory.get('files')
    tree = inventory.get('tree')
    if not isinstance(directories, list) or not isinstance(files, list) or not isinstance(tree, dict):
        raise SystemExit(f'Incomplete protected root inventory: {name}')
    if tree.get('algorithm') != 't1os-install-tree-sha256-v2' or not safe_hash.fullmatch(str(tree.get('sha256', ''))):
        raise SystemExit(f'Invalid protected tree identity: {name}')

    directory_paths = set()
    file_paths = set()
    for item in directories:
        if not isinstance(item, dict) or item.get('install_mode') != '0755':
            raise SystemExit(f'Invalid protected directory record in {name}')
        path = validate_path(item.get('path'), allow_root=True)
        if path in directory_paths:
            raise SystemExit(f'Duplicate protected directory in {name}: {path}')
        directory_paths.add(path)
    if '.' not in directory_paths:
        raise SystemExit(f'Protected root directory record is absent: {name}')

    normalized_files = []
    for item in files:
        if not isinstance(item, dict) or item.get('install_mode') not in ('0444', '0555'):
            raise SystemExit(f'Invalid protected file record in {name}')
        path = validate_path(item.get('path'), allow_root=False)
        size = item.get('size')
        digest = item.get('sha256')
        if (
            path in file_paths
            or path in directory_paths
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or not safe_hash.fullmatch(digest)
        ):
            raise SystemExit(f'Invalid protected file identity in {name}: {path}')
        parent = str(Path(path).parent).replace('\\', '/')
        if parent not in directory_paths:
            raise SystemExit(f'Protected file parent is absent in {name}: {path}')
        if exclude_generated and ('__pycache__' in Path(path).parts or path.endswith(('.pyc', '.pyo'))):
            raise SystemExit(f'Generated bytecode entered protected root {name}: {path}')
        validate_python_mode(name, path, item['install_mode'])
        file_paths.add(path)
        normalized_files.append((path, size, digest, item['install_mode']))

    if (
        tree.get('directories') != len(directory_paths)
        or tree.get('files') != len(file_paths)
        or tree.get('bytes') != sum(item[1] for item in normalized_files)
    ):
        raise SystemExit(f'Protected tree counts differ in {name}')

    if name == 'python_software':
        if 'manifest.json' in file_paths or 'manifest.json' in directory_paths:
            raise SystemExit('Python manifest must be added only from its release-lock digest')
        normalized_files.append(('manifest.json', len(manifest_bytes), manifest_digest, '0444'))

    rows.append(
        f"R\t{name}\t{destination}\t{1 if exclude_generated else 0}\t"
        f"{len(directory_paths)}\t{len(normalized_files)}\t{tree['sha256']}"
    )
    for path in sorted(directory_paths):
        rows.append(f'D\t{name}\t{path}\t0755')
    for path, size, digest, mode in sorted(normalized_files):
        rows.append(f'F\t{name}\t{path}\t{size}\t{digest}\t{mode}')

finish_profiled_inventory()
output_path.write_text('\n'.join(rows) + '\n', encoding='utf-8', newline='\n')
PY
chmod 0444 "$rootfs/protected-roots.tsv" "$rootfs/profiled-python-entrypoints.tsv"
awk -F '\t' '
    NR == 1 { valid = ($1 == "H" && $2 == "1" && $5 == "6") }
    $1 == "R" { roots++ }
    END { exit valid && roots == 6 ? 0 : 1 }
' "$rootfs/protected-roots.tsv"

cryptsetup_binary=$(command -v cryptsetup)
[ -x "$cryptsetup_binary" ] || {
    echo 'cryptsetup is required to produce the hardware recovery initramfs.' >&2
    exit 127
}
cp -L -- "$cryptsetup_binary" "$rootfs/sbin/cryptsetup"
ldd "$cryptsetup_binary" | awk '
    /=> \// { print $3 }
    /^[[:space:]]*\// { print $1 }
' | sort -u | while IFS= read -r library; do
    [ -f "$library" ] || continue
    destination="$rootfs$library"
    mkdir -p "$(dirname "$destination")"
    cp -L -- "$library" "$destination"
done

    "$ntfs_checker" --version | grep -Fq 'roothealth v0.5.2'
cp -L -- "$ntfs_checker" "$rootfs/sbin/roothealth"
ldd "$ntfs_checker" | awk '
    /=> \// { print $3 }
    /^[[:space:]]*\// { print $1 }
' | sort -u | while IFS= read -r library; do
    [ -f "$library" ] || continue
    destination="$rootfs$library"
    mkdir -p "$(dirname "$destination")"
    cp -L -- "$library" "$destination"
done

# cryptsetup loads its token modules dynamically. They are not used for the
# console passphrase path, but copying the directory keeps recovery extensible.
for token_root in /usr/lib/x86_64-linux-gnu/cryptsetup /lib/x86_64-linux-gnu/cryptsetup; do
    if [ -d "$token_root" ]; then
        mkdir -p "$rootfs$(dirname "$token_root")"
        cp -a -- "$token_root" "$rootfs$token_root"
    fi
done

amd_microcode_files=$(find "$firmware/amd-ucode" -maxdepth 1 -type f -name '*.bin' | sort)
[ -n "$amd_microcode_files" ] || {
    echo 'No AMD microcode was found in the staged firmware.' >&2
    exit 1
}
for microcode_file in $amd_microcode_files; do
    cat -- "$microcode_file" >> "$early/kernel/x86/microcode/AuthenticAMD.bin"
done

intel_microcode_files=$(find "$firmware/intel-ucode" -maxdepth 1 -type f | sort)
[ -n "$intel_microcode_files" ] || {
    echo 'No Intel microcode was found in the staged firmware.' >&2
    exit 1
}
for microcode_file in $intel_microcode_files; do
    cat -- "$microcode_file" >> "$early/kernel/x86/microcode/GenuineIntel.bin"
done

# Normalize archive metadata after every copy.  The initramfs contains no
# mutable data: directories are traversable, programs and the ELF loader are
# executable, ordinary payloads are read-only to non-root users, and the
# release inventory itself is immutable even to an accidental owner write.
find "$early" "$rootfs" -type d -exec chmod 0755 -- {} +
find "$early" "$rootfs" -type f -exec chmod 0644 -- {} +
chmod 0755 "$rootfs/init"
chmod 0755 "$rootfs/angel-recovery"
find "$rootfs/bin" "$rootfs/sbin" -type f -exec chmod 0755 -- {} +
find "$rootfs" -type f -name 'ld-linux*.so*' -exec chmod 0755 -- {} +
chmod 0444 "$rootfs/protected-roots.tsv" "$rootfs/profiled-python-entrypoints.tsv"

# Archive timestamps and ordering are build inputs, not ambient host state.
find "$early" "$rootfs" -depth -exec touch -h -d '@0' -- {} +

if find "$early" "$rootfs" -type l -print -quit | grep -q .; then
    echo 'Hardware initramfs contains a forbidden symbolic link.' >&2
    find "$early" "$rootfs" -type l -print | head -20 >&2
    exit 1
fi

(cd "$early" && find . -print0 | sort -z | cpio --null --format=newc --owner=0:0 --reproducible --create > "$work/early.cpio")
(cd "$rootfs" && find . -print0 | sort -z | cpio --null --format=newc --owner=0:0 --reproducible --create | gzip -n -9 > "$work/main.cpio.gz")

# Validate cpio headers themselves.  Inspecting the staging tree would miss
# exactly the DrvFS mode corruption this gate is intended to prevent.
cpio --numeric-uid-gid -tv < "$work/early.cpio" > "$work/early.list" 2>/dev/null
gzip -cd "$work/main.cpio.gz" | cpio --numeric-uid-gid -tv > "$work/main.list" 2>/dev/null
validate_archive_modes() {
    archive_kind=$1
    listing=$2
    awk -v archive_kind="$archive_kind" '
        {
            mode=$1
            uid=$3
            gid=$4
            path=$NF
            expected=""
            if (uid != "0" || gid != "0") {
                printf "%s archive member is not root-owned: %s %s:%s\n", archive_kind, path, uid, gid > "/dev/stderr"
                bad=1
            }
            if (substr(mode, 1, 1) == "d") {
                expected="drwxr-xr-x"
            } else if (substr(mode, 1, 1) == "-") {
                expected="-rw-r--r--"
                if (archive_kind == "main" && (path == "protected-roots.tsv" || path == "profiled-python-entrypoints.tsv")) {
                    expected="-r--r--r--"
                } else if (archive_kind == "main" && (path == "init" || path == "angel-recovery" || path ~ /^(bin|sbin)\// || path ~ /(^|\/)ld-linux[^\/]*$/)) {
                    expected="-rwxr-xr-x"
                }
            } else {
                printf "%s archive contains a special member: %s %s\n", archive_kind, path, mode > "/dev/stderr"
                bad=1
            }
            if (expected != "" && mode != expected) {
                printf "%s archive mode differs for %s: expected %s, got %s\n", archive_kind, path, expected, mode > "/dev/stderr"
                bad=1
            }
        }
        END { exit bad ? 1 : 0 }
    ' "$listing"
}
validate_archive_modes early "$work/early.list"
validate_archive_modes main "$work/main.list"

# Verify both archive members and the scripts needed before switch_root.
cpio -it < "$work/early.cpio" | grep -qx 'kernel/x86/microcode/AuthenticAMD.bin'
cpio -it < "$work/early.cpio" | grep -qx 'kernel/x86/microcode/GenuineIntel.bin'
gzip -cd "$work/main.cpio.gz" | cpio -it | grep -qx 'init'
gzip -cd "$work/main.cpio.gz" | cpio -it | grep -qx 'angel-recovery'
gzip -cd "$work/main.cpio.gz" | cpio -it | grep -qx 'bin/busybox'
gzip -cd "$work/main.cpio.gz" | cpio -it | grep -qx 'sbin/cryptsetup'
gzip -cd "$work/main.cpio.gz" | cpio -it | grep -qx 'sbin/roothealth'
gzip -cd "$work/main.cpio.gz" | cpio -it | grep -qx 'sbin/recoveryauth'
gzip -cd "$work/main.cpio.gz" | cpio -it | grep -qx 'lib64/ld-linux-x86-64.so.2'
gzip -cd "$work/main.cpio.gz" | cpio -it | grep -qx 'protected-roots.tsv'
gzip -cd "$work/main.cpio.gz" | cpio -it | grep -qx 'profiled-python-entrypoints.tsv'
    "$rootfs/sbin/roothealth" --version | grep -Fq 'roothealth v0.5.2'
"$rootfs/sbin/roothealth" --help | grep -Eq '(^|[[:space:]])--repair([=[:space:]]|$)'
"$rootfs/sbin/roothealth" --help | grep -Eq '(^|[[:space:]])--preflight([=[:space:]]|$)'
"$rootfs/sbin/roothealth" --help | grep -Eq '(^|[[:space:]])--boot-repair([=[:space:]]|$)'
if [ "$(grep -Fo -- '--boot-repair' "$rootfs/init" | wc -l)" -ne 1 ]; then
    echo 'Hardware initramfs must contain exactly one RootHealth --boot-repair invocation.' >&2
    exit 1
fi
if grep -Fq -- '--repair' "$rootfs/init"; then
    echo 'Hardware initramfs still contains the offline full RootHealth repair mode.' >&2
    exit 1
fi
if grep -Fq -- '--preflight' "$rootfs/init"; then
    echo 'Hardware initramfs still contains a legacy RootHealth --preflight invocation.' >&2
    exit 1
fi
if grep -Fq -- '--check' "$rootfs/init"; then
    echo 'Hardware initramfs still contains a separate RootHealth --check invocation.' >&2
    exit 1
fi
"$rootfs/bin/busybox" sh -n "$rootfs/init"
cat "$work/early.cpio" "$work/main.cpio.gz" > "$output_tmp"
test -s "$output_tmp"
mv -f -- "$output_tmp" "$output"
sha256sum "$output"
'@

$buildExitCode = 1
$normalizedBuildCommand = $buildCommand.Replace("`r", '') + "`n# end"
$normalizedBuildCommand |
    & wsl.exe -d Ubuntu -u root --exec bash -s -- $wslBusyBox $wslInit $wslFirmware $wslStage $wslOutput $wslPythonManifest $wslPythonReleaseLock $wslNtfsChecker $candidateMode $wslRecovery $wslPythonRuntimeConfig $wslBootPolicyManifest $wslRecoveryAuth
$buildExitCode = $LASTEXITCODE
if ($buildExitCode -ne 0) {
    throw "Hardware initramfs build failed (exit code $buildExitCode)."
}

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $outputPath).Hash.ToLowerInvariant()
Write-Host "Hardware initramfs completed: $hash"
Write-Host "Output: $outputPath"
