#!/bin/bash
set -euo pipefail

image=${1:?release image path required}
scanner=${2:?raw I30 scanner path required}
partition_offset=${3:-537919488}
partition_size=${4:-10198450176}
slice=$(mktemp /var/tmp/roothealth-release-p2.XXXXXX)
pidfile=$(mktemp /var/tmp/roothealth-release-p2.pid.XXXXXX)
rm -f "$pidfile"

cleanup()
{
	if [ -f "$pidfile" ]; then
		pid=$(cat "$pidfile")
		kill "$pid" 2>/dev/null || true
		for attempt in 1 2 3 4 5; do
			kill -0 "$pid" 2>/dev/null || break
			sleep 0.1
		done
	fi
	fusermount3 -u "$slice" 2>/dev/null || true
	rm -f "$slice" "$pidfile"
}
trap cleanup EXIT INT TERM

qemu-storage-daemon --daemonize --pidfile "$pidfile" \
	--blockdev driver=file,node-name=source,filename="$image",read-only=on \
	--blockdev driver=raw,node-name=p2,file=source,offset="$partition_offset",size="$partition_size",read-only=on \
	--export type=fuse,id=p2export,node-name=p2,mountpoint="$slice",writable=off,allow-other=off

RH_I30_RAW_ONLY=1 "$scanner" "$slice"
