#!/bin/sh
set -eu

modules_archive=$1
firmware_archive=$2
firmware_manifest=$3
mount_point=/mnt/t1os-usb-hardware-repair
stage_name=.t1os-hardware-repair

mkdir -p -- "$mount_point"
if mountpoint -q "$mount_point"; then
    echo 'Hardware-repair mount point is already in use.' >&2
    exit 1
fi
mount -t drvfs D: "$mount_point" -o uid=0,gid=0,umask=022
diagnostic=/mnt/c/Users/Public/t1os-usb-hardware-repair.log
: > "$diagnostic"
exec > "$diagnostic" 2>&1
set -x
cleanup() {
    status=$?
    sync
    if ! umount "$mount_point"; then
        status=1
    fi
    exit "$status"
}
trap cleanup EXIT HUP INT TERM

test -f "$mount_point/autorun.inf"
grep -Eiq '^[[:space:]]*Label=T1OS([[:space:]]|$)' "$mount_point/autorun.inf"
drivers="$mount_point/the one/drivers"
test -d "$drivers"
test ! -L "$drivers"

stage="$drivers/$stage_name"
old="$drivers/modules.repair-old"
if ! (
    cd "$drivers/modules" 2>/dev/null &&
    sha256sum -c module-manifest.sha256 >/dev/null 2>&1
); then
    rm -rf -- "$stage" "$old"
    mkdir -- "$stage"
    stage_windows=$(wslpath -w "$stage")
    fsutil.exe file setCaseSensitiveInfo "$stage_windows" enable >/dev/null
    fsutil.exe file queryCaseSensitiveInfo "$stage_windows" |
        grep -Eiq '\bis enabled\b'
    tar --zstd -xf "$modules_archive" -C "$stage"
    new="$stage/the one/drivers/modules"
    test -d "$new"
    test ! -L "$new"
    (cd "$new" && sha256sum -c module-manifest.sha256 >/dev/null)
    if [ -d "$drivers/modules" ]; then
        mv -- "$drivers/modules" "$old"
    fi
    if ! mv -- "$new" "$drivers/modules"; then
        [ ! -d "$old" ] || mv -- "$old" "$drivers/modules"
        exit 1
    fi
    (cd "$drivers/modules" && sha256sum -c module-manifest.sha256 >/dev/null)
    rm -rf -- "$stage" "$old"
fi

firmware="$drivers/firmware"
mkdir -p -- "$firmware"
test ! -L "$firmware"
# The pinned firmware set contains case-distinct filenames. Enable Windows
# per-directory case sensitivity throughout the existing tree before filling
# only missing/size-mismatched archive members left by an interrupted repair.
python3 -B - "$mount_point" "$firmware" <<'PY'
import os
import subprocess
import sys

mount = os.path.abspath(sys.argv[1])
root = os.path.abspath(sys.argv[2])
for directory, _, _ in os.walk(root):
    relative = os.path.relpath(directory, mount)
    windows = 'D:\\' + relative.replace('/', '\\')
    subprocess.run(
        ['fsutil.exe', 'file', 'setCaseSensitiveInfo', windows, 'enable'],
        check=True,
        stdout=subprocess.DEVNULL,
    )
PY
firmware_repair_list=/tmp/t1os-firmware-repair-$$.txt
python3 -B - "$firmware" "$firmware_manifest" "$firmware_repair_list" <<'PY'
import json
import os
import sys

root = os.path.abspath(sys.argv[1])
with open(sys.argv[2], encoding='utf-8') as stream:
    records = json.load(stream).get('files', [])
needed = []
for record in records:
    relative = record['path']
    path = os.path.join(root, *relative.split('/'))
    try:
        size = os.lstat(path).st_size
    except FileNotFoundError:
        size = -1
    if size != record['size']:
        needed.append('./' + relative)
with open(sys.argv[3], 'w', encoding='utf-8', newline='\n') as stream:
    stream.write('\n'.join(needed) + ('\n' if needed else ''))
print(f'firmware_files_requiring_extraction={len(needed)}')
PY
if [ -s "$firmware_repair_list" ]; then
    tar --zstd -xf "$firmware_archive" -C "$firmware" -T "$firmware_repair_list"
fi
rm -f -- "$firmware_repair_list"
cp -- "$firmware_manifest" "$firmware/t1os-firmware-manifest.json"

python3 -B - "$firmware" "$firmware_manifest" <<'PY'
import hashlib
import json
import os
import stat
import sys

root = os.path.abspath(sys.argv[1])
with open(sys.argv[2], encoding='utf-8') as stream:
    manifest = json.load(stream)
records = manifest.get('files')
if not isinstance(records, list) or not records:
    raise SystemExit('firmware manifest has no file inventory')
expected = {'t1os-firmware-manifest.json'}
for record in records:
    relative = record.get('path')
    if not isinstance(relative, str) or relative.startswith('/') or '..' in relative.split('/'):
        raise SystemExit(f'unsafe firmware path: {relative!r}')
    expected.add(relative)
    path = os.path.join(root, *relative.split('/'))
    status = os.lstat(path)
    if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
        raise SystemExit(f'unsafe firmware payload: {relative}')
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if status.st_size != record.get('size') or digest.hexdigest() != record.get('sha256'):
        raise SystemExit(f'firmware payload differs: {relative}')
actual = set()
for directory, directories, files in os.walk(root):
    for name in directories:
        path = os.path.join(directory, name)
        if os.path.islink(path):
            raise SystemExit(f'firmware symlink is forbidden: {path}')
    for name in files:
        actual.add(os.path.relpath(os.path.join(directory, name), root).replace(os.sep, '/'))
extra = sorted(actual - expected)
missing = sorted(expected - actual)
if extra or missing:
    raise SystemExit(f'firmware inventory differs: extra={extra[:5]} missing={missing[:5]}')
print(f'firmware_files_verified={len(expected)}')
PY

sync
echo 'T1OS USB modules and firmware were restored and verified.'
