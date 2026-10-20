#!/bin/bash
root=/scratch/kohlbach/openms-libxml2-scaling-20261020-01a153cb
bash "$root/staging/build-and-benchmark.sh"
status=$?
echo "$status" > "$root/results/PIPELINE_EXIT_STATUS"
exit "$status"
