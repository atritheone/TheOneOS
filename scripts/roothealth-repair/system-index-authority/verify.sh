#!/bin/sh
set -eu

t1os_incremental_script=$(readlink -f -- "$0")
t1os_incremental_cursor=$(dirname -- "$t1os_incremental_script")
while [ "$t1os_incremental_cursor" != / ] && [ ! -f "$t1os_incremental_cursor/incremental_test.py" ]; do
	t1os_incremental_cursor=$(dirname -- "$t1os_incremental_cursor")
done
if [ -f "$t1os_incremental_cursor/incremental_test.py" ]; then
	t1os_incremental_project=$(dirname -- "$t1os_incremental_cursor")
	t1os_incremental_relative=${t1os_incremental_script#"$t1os_incremental_project"/}
	if [ "${T1OS_INCREMENTAL_ACTIVE_SCRIPT:-}" != "$t1os_incremental_relative" ]; then
		exec python3 -B "$t1os_incremental_cursor/incremental_test.py" run --script "$t1os_incremental_script" -- "$@"
	fi
fi

package_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
(cd "$package_dir" && sha256sum -c SHA256SUMS)

if [ "$#" -gt 1 ]; then
	printf '%s\n' "usage: $0 [bound-baseline-tree]" >&2
	exit 64
fi
if [ "$#" -eq 1 ]; then
	(cd "$1" && git apply --check --whitespace=error-all \
		"$package_dir/system-index-authority.patch")
fi

printf '%s\n' system_index_authority_publication=verified
