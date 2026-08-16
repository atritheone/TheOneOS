#!/bin/sh
set -eu

if [ "$#" -ne 5 ]; then
	echo "usage: $0 MUTATOR COMMIT SOURCE SERIAL SCRATCH" >&2
	exit 5
fi

mutator=$1
commit=$2
source_image=$3
serial=$4
scratch=$5
cases=0

for mode in \
	powercut-before-pwrite:1 \
	powercut-after-pwrite:1 \
	powercut-before-sync:1 \
	powercut-after-sync:1 \
	powercut-after-verify:1 \
	powercut-before-sync:2 \
	powercut-after-sync:2
do
	image="$scratch/$(printf '%s' "$mode" | tr ':/' '__').ntfs"
	"$mutator" "$source_image" "$image"
	set +e
	ROOTHEALTH_REPAIR_TEST_FAIL="$mode" "$commit" "$serial" "$image" 0
	status=$?
	set -e
	if [ "$status" -ne 86 ]; then
		echo "fault $mode exited $status, expected 86" >&2
		exit 1
	fi
	"$commit" "$serial" "$image" 0 >/dev/null
	cases=$((cases + 1))
done

printf 'foundation-direct-powercut cases=%u passed=1\n' "$cases"
