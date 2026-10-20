#!/bin/bash
root=/scratch/kohlbach/openms-libxml2-replacement-20261020-01a153cb
cd "$root"
bash staging/run-final-guard-validation.sh
status=$?
echo "$status" > results/VALIDATION_EXIT_STATUS
exit "$status"
