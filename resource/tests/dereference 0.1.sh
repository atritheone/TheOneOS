#!/usr/bin/env bash

find . -type l -print0 | while IFS= read -r -d '' link; do
  target=$(readlink -f "$link") || continue
  echo "replacing '$link' → '$target'"
  rm "$link"
  cp -a "$target" "$link"
done