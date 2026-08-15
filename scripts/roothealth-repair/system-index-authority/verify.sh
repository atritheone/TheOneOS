#!/bin/sh
set -eu

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
