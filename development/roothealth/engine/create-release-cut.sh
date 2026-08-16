#!/bin/sh
set -eu
ordinal=$1
mode=$2
image=$3
cp --reflink=auto /var/tmp/roothealth-release-journal5.building "$image"
chmod 600 "$image"
printf '\177' | dd of="$image" bs=1 seek=131547417 conv=notrunc status=none
set +e
ROOTHEALTH_REPAIR_TEST_FAIL="powercut-${mode}-pwrite:${ordinal}" \
  /var/tmp/roothealth_bitmap_wal.semantic.testing \
  0A88678D60F5A4ED b9435c51-cbd1-419a-9373-97d74580012b 67 2 "$image" \
  >/var/tmp/rh-release-cut-child.log 2>&1
result=$?
set -e
echo "cut-result=$result"
cat /var/tmp/rh-release-cut-child.log
test "$result" -eq 86
