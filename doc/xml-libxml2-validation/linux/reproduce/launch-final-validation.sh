#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-libxml2-replacement-20261020-01a153cb
cd "$root"
test "$(cat results/VALIDATION_EXIT_STATUS)" = 0
test -f results/SUPPLEMENTAL_COMPLETE
mkdir -p results/candidate-72d8c395 logs/candidate-72d8c395
for file in results/*; do
 name=$(basename "$file")
 if test -f "$file"; then
  case "$name" in dependency*|libxml2*|zstd*|environment*|private*|driver.pid|reviewed-driver.pid) continue;; esac
  mv "$file" results/candidate-72d8c395/
 fi
done
for name in configure.log build.log bundle-fetch.log reviewed-validation-pipeline.log benchmark-configure.log benchmark-build.log supplemental.log; do
 if test -f "logs/$name"; then mv "logs/$name" logs/candidate-72d8c395/; fi
done
set +e
bash staging/run-final-validation.sh > logs/final-validation-pipeline.log 2>&1
status=$?
set -e
echo "$status" > results/VALIDATION_EXIT_STATUS
exit "$status"
