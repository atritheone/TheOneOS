[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param()

$ErrorActionPreference = 'Stop'
throw (
    'Python candidate roots are non-deployable because they contain a generated ' +
    'snapshot of /the one/build. Package and promote the candidate, then deploy ' +
    'the canonical verified Python release with push to disk.ps1.'
)
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$imagePath = Join-Path $projectRoot 'environment\storage.img'
$candidateRoot = Join-Path $projectRoot 'development\python 3.14 candidate\t1os'
$manifestPath = Join-Path $candidateRoot 'manifest.json'

foreach ($required in @($imagePath, $manifestPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required Python 3.14 storage input is missing: $required"
    }
}
foreach ($required in @(
    (Join-Path $candidateRoot 'software\python'),
    (Join-Path $candidateRoot 'catalogue\python'),
    (Join-Path $candidateRoot 'catalogue\image'),
    (Join-Path $candidateRoot 'build'),
    (Join-Path $candidateRoot 'boot'),
    (Join-Path $candidateRoot 'software\virtualbox')
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Container)) {
        throw "Required Python 3.14 candidate root is missing: $required"
    }
}
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Required command not found: wsl.exe'
}

try {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json -ErrorAction Stop
}
catch {
    throw "The Python 3.14 candidate manifest is malformed: $($_.Exception.Message)"
}
if (
    [string]$manifest.component -cne 't1os-python-candidate' -or
    [string]$manifest.candidate_release -cne '3.14.7-t1os-candidate.2' -or
    [string]$manifest.python_version -cne '3.14.7' -or
    [string]$manifest.python_abi -cne 'cp314' -or
    [bool]$manifest.promotable -or
    @($manifest.payloads.build_software).Count -eq 0 -or
    @($manifest.payloads.boot).Count -eq 0 -or
    @($manifest.payloads.virtualbox_software).Count -eq 0
) {
    throw 'The staged payload is not the complete verified Python 3.14.7 candidate.'
}

$manifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
$imageHashBefore = (Get-FileHash -LiteralPath $imagePath -Algorithm SHA256).Hash.ToLowerInvariant()
$imageSize = (Get-Item -LiteralPath $imagePath).Length
if ($imageSize -ne 6442450944) {
    throw "The storage image has an unexpected size: $imageSize"
}

Write-Host "Python candidate: $($manifest.candidate_release)"
Write-Host "Candidate manifest SHA-256: $manifestHash"
Write-Host "Storage image before: $imageHashBefore ($imageSize bytes)"

if (-not $PSCmdlet.ShouldProcess(
    $imagePath,
    'Transactionally replace managed Python, its catalogues, and versionless userspace callers'
)) {
    Write-Host 'The storage-image deployment was not executed.'
    exit 0
}

function ConvertTo-WslPath([string]$Path) {
    $translated = (& wsl.exe -d Ubuntu --exec wslpath -a $Path | Select-Object -First 1).Trim()
    if ([string]::IsNullOrWhiteSpace($translated)) {
        throw "Could not translate path into WSL: $Path"
    }
    return $translated
}

$wslImage = ConvertTo-WslPath $imagePath
$wslCandidate = ConvertTo-WslPath $candidateRoot
$wslManifest = ConvertTo-WslPath $manifestPath
$mountPoint = "/tmp/t1os-python314-storage-$PID"

$script = @'
set -euo pipefail
image=$1
candidate=$2
manifest=$3
expected_manifest=$4
mount_point=$5

for command_name in awk blockdev e2fsck find findmnt grep losetup mkdir mount mountpoint mv \
        python3 readlink rm rmdir rsync sha256sum sync umount; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "Required storage deployment command is missing: $command_name" >&2
        exit 127
    }
done

[ "$(sha256sum "$manifest" | awk '{print $1}')" = "$expected_manifest" ] || {
    echo 'The candidate manifest changed before storage deployment.' >&2
    exit 1
}

if losetup -j "$image" | grep -q .; then
    echo 'The storage image already has a loop association.' >&2
    exit 1
fi
e2fsck -fn "$image"

mkdir -p "$mount_point"
[ -z "$(find "$mount_point" -mindepth 1 -maxdepth 1 -print -quit)" ] || {
    echo 'The storage mount point is not empty.' >&2
    exit 1
}

loop=''
mounted=0
completed=0
destinations=()
stages=()
backups=()

cleanup() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ "$completed" != 1 ] && [ "$mounted" = 1 ]; then
        for ((index=${#destinations[@]}-1; index>=0; index--)); do
            destination=${destinations[$index]}
            stage=${stages[$index]}
            backup=${backups[$index]}
            failed="${stage}.failed"
            if [ -e "$backup" ]; then
                if [ -e "$destination" ]; then
                    mv -- "$destination" "$failed" || true
                fi
                mv -- "$backup" "$destination" || true
                rm -rf -- "$failed" || true
            fi
            rm -rf -- "$stage" || true
        done
        sync || true
    fi
    if [ "$mounted" = 1 ]; then
        if ! umount "$mount_point"; then
            echo 'Could not unmount storage image.' >&2
            status=1
        fi
        mounted=0
    fi
    if [ -n "$loop" ] && losetup "$loop" >/dev/null 2>&1; then
        if ! losetup -d "$loop"; then
            echo 'Could not detach storage loop device.' >&2
            status=1
        fi
    fi
    rmdir "$mount_point" 2>/dev/null || true
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

loop=$(losetup --find --show "$image")
blockdev --setrw "$loop"
mount -o rw "$loop" "$mount_point"
mounted=1
mount_options=$(findmnt -rn -o OPTIONS -T "$mount_point")
case ",$mount_options," in
    *,ro,*) echo 'Storage image mounted read-only.' >&2; exit 1 ;;
esac
[ "$(readlink -f "$(losetup -n -O BACK-FILE "$loop")")" = "$(readlink -f "$image")" ] || {
    echo 'Loop device is not backed by the requested storage image.' >&2
    exit 1
}
[ -d "$mount_point/the one/build" ] &&
[ -f "$mount_point/the one/settings/runtime paths.json" ] &&
[ -f "$mount_point/the one/build/GODDESS/GODDESS.py" ] &&
[ -f "$mount_point/the one/drivers/settings/policy.json" ] || {
    echo 'Mounted filesystem is not a T1OS storage root.' >&2
    exit 1
}

python3 - "$mount_point" <<'PY'
import os, stat, sys
mount=os.path.abspath(sys.argv[1])
roots=(
    "the one/software/python",
    "the one/catalogue/python",
    "the one/catalogue/image",
    "the one/build",
    "boot",
    "the one/software/virtualbox",
)
for relative in roots:
    path=os.path.join(mount,relative)
    current=mount
    for part in relative.split('/'):
        current=os.path.join(current,part)
        status=os.lstat(current)
        if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
            raise SystemExit(f"unsafe destination ancestor: {current}")
    for directory, names, files in os.walk(path, followlinks=False):
        for name in [*names,*files]:
            child=os.path.join(directory,name); status=os.lstat(child)
            if stat.S_ISLNK(status.st_mode) or not (stat.S_ISDIR(status.st_mode) or stat.S_ISREG(status.st_mode)):
                raise SystemExit(f"unsafe destination entry: {child}")
PY

token="$$"
destinations=(
    "$mount_point/the one/software/python"
    "$mount_point/the one/catalogue/python"
    "$mount_point/the one/catalogue/image"
    "$mount_point/the one/build"
    "$mount_point/boot"
    "$mount_point/the one/software/virtualbox"
)
sources=(
    "$candidate/software/python"
    "$candidate/catalogue/python"
    "$candidate/catalogue/image"
    "$candidate/build"
    "$candidate/boot"
    "$candidate/software/virtualbox"
)
stages=(
    "$mount_point/the one/software/.python.t1os-$token.stage"
    "$mount_point/the one/catalogue/.python.t1os-$token.stage"
    "$mount_point/the one/catalogue/.image.t1os-$token.stage"
    "$mount_point/the one/.build.t1os-$token.stage"
    "$mount_point/.boot.t1os-$token.stage"
    "$mount_point/the one/software/.virtualbox.t1os-$token.stage"
)
backups=(
    "$mount_point/the one/software/.python.t1os-$token.backup"
    "$mount_point/the one/catalogue/.python.t1os-$token.backup"
    "$mount_point/the one/catalogue/.image.t1os-$token.backup"
    "$mount_point/the one/.build.t1os-$token.backup"
    "$mount_point/.boot.t1os-$token.backup"
    "$mount_point/the one/software/.virtualbox.t1os-$token.backup"
)

for index in "${!destinations[@]}"; do
    [ ! -e "${stages[$index]}" ] && [ ! -e "${backups[$index]}" ] || {
        echo 'Reserved transaction path already exists.' >&2
        exit 1
    }
    mkdir "${stages[$index]}"
    rsync -a --delete -- "${sources[$index]}/" "${stages[$index]}/"
done

verify_payload() {
    software_root=$1
    catalogue_root=$2
    image_root=$3
    build_root=$4
    boot_root=$5
    virtualbox_root=$6
    manifest_path=$7
    python3 - "$software_root" "$catalogue_root" "$image_root" "$build_root" "$boot_root" "$virtualbox_root" "$manifest_path" <<'PY'
import hashlib, json, os, pathlib, stat, sys
manifest_path=pathlib.Path(sys.argv[7])
manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
areas={
    "software": pathlib.Path(sys.argv[1]),
    "catalogue": pathlib.Path(sys.argv[2]),
    "image": pathlib.Path(sys.argv[3]),
    "build_software": pathlib.Path(sys.argv[4]),
    "boot": pathlib.Path(sys.argv[5]),
    "virtualbox_software": pathlib.Path(sys.argv[6]),
}
manifest_hash=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
for name, area in areas.items():
    expected={row["path"]:row for row in manifest["payloads"][name]}
    if name=="software":
        expected["manifest.json"]={"size":manifest_path.stat().st_size,"sha256":manifest_hash}
    actual={}
    for directory, directories, files in os.walk(area, followlinks=False):
        for entry in [*directories,*files]:
            path=pathlib.Path(directory)/entry; status=path.lstat()
            if stat.S_ISLNK(status.st_mode) or not (stat.S_ISDIR(status.st_mode) or stat.S_ISREG(status.st_mode)):
                raise SystemExit(f"unsafe payload entry: {path}")
        for entry in files:
            path=pathlib.Path(directory)/entry
            relative=path.relative_to(area).as_posix()
            actual[relative]=path
    if set(actual)!=set(expected):
        raise SystemExit(f"{name} inventory differs: missing={sorted(set(expected)-set(actual))[:3]} extra={sorted(set(actual)-set(expected))[:3]}")
    for relative,path in actual.items():
        row=expected[relative]
        if path.stat().st_size!=row["size"] or hashlib.sha256(path.read_bytes()).hexdigest()!=row["sha256"]:
            raise SystemExit(f"{name} payload differs: {relative}")
PY
}

verify_payload "${stages[0]}" "${stages[1]}" "${stages[2]}" "${stages[3]}" \
    "${stages[4]}" "${stages[5]}" "$manifest"

for index in "${!destinations[@]}"; do
    mv -- "${destinations[$index]}" "${backups[$index]}"
    mv -- "${stages[$index]}" "${destinations[$index]}"
done

verify_payload \
    "$mount_point/the one/software/python" \
    "$mount_point/the one/catalogue/python" \
    "$mount_point/the one/catalogue/image" \
    "$mount_point/the one/build" \
    "$mount_point/boot" \
    "$mount_point/the one/software/virtualbox" \
    "$mount_point/the one/software/python/manifest.json"

root="$mount_point/the one"
loader="$root/catalogue/python/ld-linux-x86-64.so.2"
python="$root/software/python/bin/python"
compatibility_python="$root/software/python/bin/python3.13"
image_catalogue="$root/catalogue/image"
libraries="$image_catalogue/pillow.libs:$image_catalogue:$root/catalogue/python"
PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH= \
    "$loader" --library-path "$libraries" "$python" -B -P - "$image_catalogue" <<'PY'
import json, ssl, sqlite3, sys
sys.path.insert(0,sys.argv[1])
import PIL, freetype, pyroute2
result={"python":sys.version.split()[0],"pillow":PIL.__version__,
"freetype":".".join(map(str,freetype.version())),"pyroute2":pyroute2.__version__,
"openssl":ssl.OPENSSL_VERSION,"sqlite":sqlite3.sqlite_version,
"safe_path":bool(sys.flags.safe_path),"dont_write_bytecode":bool(sys.dont_write_bytecode)}
print(json.dumps(result,sort_keys=True))
assert result["python"]=="3.14.7" and result["pillow"]=="12.3.0" and result["pyroute2"]=="0.9.4"
assert result["safe_path"] and result["dont_write_bytecode"]
PY
test "$(PYTHONDONTWRITEBYTECODE=1 "$loader" --library-path "$libraries" \
    "$compatibility_python" -B -P -c 'import sys; print(sys.version.split()[0])')" = '3.14.7'

completed=1
for backup in "${backups[@]}"; do rm -rf -- "$backup"; done
sync
umount "$mount_point"
mounted=0
losetup -d "$loop"
loop=''
e2fsck -fn "$image"
rmdir "$mount_point"
trap - EXIT HUP INT TERM
'@

& wsl.exe -d Ubuntu -u root --exec bash -c $script bash `
    $wslImage $wslCandidate $wslManifest $manifestHash $mountPoint
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.14 storage deployment failed (exit $LASTEXITCODE)."
}

$imageHashAfter = (Get-FileHash -LiteralPath $imagePath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host ''
Write-Host 'Python 3.14.7 and versionless userspace callers were deployed to storage.img.'
Write-Host "Storage image after SHA-256: $imageHashAfter"
Write-Host 'The image was cleanly unmounted and its post-write e2fsck read-only check passed.'
