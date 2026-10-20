#!/bin/bash
root=/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb
bash "$root/staging/build-and-benchmark.sh"
status=$?
echo "$status" > "$root/results/BUILD_EXIT_STATUS"
exit "$status"
