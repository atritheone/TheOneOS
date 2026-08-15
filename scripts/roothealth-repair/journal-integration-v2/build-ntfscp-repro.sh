#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "usage: build-ntfscp-repro.sh ARCHIVE NEW_OUTPUT_DIRECTORY" >&2
    exit 64
fi

archive=$1
output=$2
expected_archive=13dc944f477997ae4ecd89e3d0fdaa34b74ebbc1f7beb675657624ed6289eff5
expected_binary=018bbc424a433b567410152686f145e42a3adf201f257dbc93fc763cdd971bb8
source_root=ntfsprogs-plus-d4f481df6926557f7b18b471a43313652dec6f7e

case "$output" in
    ''|/|.) echo "unsafe output directory" >&2; exit 64 ;;
esac
[ -f "$archive" ] || { echo "archive is not a regular file" >&2; exit 66; }
[ ! -e "$output" ] || { echo "output already exists" >&2; exit 73; }
printf '%s  %s\n' "$expected_archive" "$archive" | sha256sum -c -
mkdir -m 0700 -- "$output"

export LC_ALL=C
export TZ=UTC
export SOURCE_DATE_EPOCH=0
export ZERO_AR_DATE=1

require_version() {
    actual=$(sh -c "$1")
    [ "$actual" = "$2" ] || {
        printf 'unexpected %s: %s\n' "$3" "$actual" >&2
        exit 69
    }
}

require_version 'gcc -dumpfullversion -dumpversion' '13.3.0' gcc
require_version 'ld --version | sed -n 1p' 'GNU ld (GNU Binutils for Ubuntu) 2.42' ld
require_version 'make --version | sed -n 1p' 'GNU Make 4.3' make
require_version 'autoreconf --version | sed -n 1p' 'autoreconf (GNU Autoconf) 2.71' autoreconf
require_version 'automake --version | sed -n 1p' 'automake (GNU automake) 1.16.5' automake
require_version 'libtoolize --version | sed -n 1p' 'libtoolize (GNU libtool) 2.4.7' libtoolize

build_one() {
    ordinal=$1
    tree="$output/build-$ordinal"
    mkdir -m 0700 -- "$tree"
    tar -xzf "$archive" --strip-components=1 -C "$tree"
    prefix_flags="-ffile-prefix-map=$tree=/usr/src/ntfs-next-d4 -fdebug-prefix-map=$tree=/usr/src/ntfs-next-d4 -fmacro-prefix-map=$tree=/usr/src/ntfs-next-d4"
    (
        cd "$tree"
        autoreconf -fi
        CFLAGS="-O2 -g0 -fstack-protector-strong -fPIE $prefix_flags -fno-record-gcc-switches" \
        CPPFLAGS='-D_GNU_SOURCE -D_FORTIFY_SOURCE=3' \
        LDFLAGS='-Wl,--build-id=sha1,-z,relro,-z,now,-pie' \
        ARFLAGS=crD \
            ./configure --disable-shared --enable-static
        make -j1 -C libntfs V=1 libntfs.la
        make -j1 -C src V=1 ntfscp
        cd src
        gcc -O2 -g0 -fstack-protector-strong -fPIE \
            $prefix_flags -fno-record-gcc-switches \
            -Wall -Wno-address-of-packed-member \
            -Wl,--build-id=sha1 -Wl,-z -Wl,relro -Wl,-z -Wl,now \
            -Wl,-pie -Wl,-Map="$tree/ntfscp.link.map" \
            -o ntfscp.map ntfscp.o utils.o ../libntfs/.libs/libntfs.a
        cmp ntfscp ntfscp.map
    ) >"$output/build-$ordinal.log" 2>&1
    printf '%s  %s\n' "$expected_binary" "$tree/src/ntfscp" | sha256sum -c -
}

build_one a
build_one b
cmp "$output/build-a/src/ntfscp" "$output/build-b/src/ntfscp"

for ordinal in a b; do
    grep -o '../libntfs/.libs/libntfs.a([^)]*)' \
        "$output/build-$ordinal/ntfscp.link.map" |
        sed -E 's#.*\(([^)]*)\)#\1#' |
        LC_ALL=C sort -u >"$output/build-$ordinal.link-members"
done
cmp "$output/build-a.link-members" "$output/build-b.link-members"
[ "$(wc -l <"$output/build-a.link-members")" -eq 30 ]

install -m 0755 "$output/build-a/src/ntfscp" "$output/ntfscp"
printf 'NTFSCP_REPRODUCIBLE_PASS builds=2 archive=%s binary=%s linked_archive_members=30\n' \
    "$expected_archive" "$expected_binary"
