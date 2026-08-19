#!/usr/bin/env bash
set -u

umask 077
script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
project_root="$(CDPATH= cd -- "$script_dir/../../.." && pwd)"
state_dir="$project_root/development/chromium release"
log_path="$state_dir/chromium-scheduled-release.log"
exit_path="$state_dir/chromium-scheduled-release.exit.txt"
exit_temp="$exit_path.tmp"

mkdir -p -- "$state_dir" || exit 125
rm -f -- "$exit_temp"
PYTHONUNBUFFERED=1 python3 -u \
    "$project_root/development/build chromium runtime.py" \
    prepare --profile release >"$log_path" 2>&1
result=$?
printf '%s\n' "$result" >"$exit_temp" || exit 125
mv -f -- "$exit_temp" "$exit_path" || exit 125
exit "$result"
