#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb
for ((n=0;n<720;n++)); do
 if test -f "$root/results/BUILD_EXIT_STATUS"; then break; fi
 sleep 5
done
test "$(cat "$root/results/BUILD_EXIT_STATUS")" = 0
bash "$root/staging/prepare-extended.sh" > "$root/logs/prepare-extended.log" 2>&1 &
first=$!
bash "$root/staging/prepare-converter.sh" > "$root/logs/prepare-converter.log" 2>&1 &
second=$!
status=0
wait "$first" || status=$?
wait "$second" || status=$?
echo "$status" > "$root/results/PREPARATION_EXIT_STATUS"
exit "$status"
