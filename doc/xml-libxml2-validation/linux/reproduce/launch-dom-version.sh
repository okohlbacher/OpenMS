#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-libxml2-replacement-20261020-01a153cb
cd "$root"
test -f results/FINAL_DECODING_CI_COMPLETE
test "$(cat results/CLASS_TEST_EXIT_STATUS)" = 0
mkdir -p results/candidate-fcdc7458 logs/candidate-fcdc7458
for file in results/*; do
 name=$(basename "$file")
 if test -f "$file"; then
  case "$name" in dependency*|libxml2*|zstd*|environment*|private*|*driver.pid) continue;; esac
  mv "$file" results/candidate-fcdc7458/
 fi
done
for name in configure.log build.log bundle-fetch.log final-validation-pipeline.log benchmark-configure.log benchmark-build.log supplemental.log ci-bundle-fetch.log final-decoding-ci.log final-ci-pipeline.log; do
 if test -f "logs/$name"; then mv "logs/$name" logs/candidate-fcdc7458/; fi
done
set +e
bash staging/run-dom-version-validation.sh > logs/dom-version-validation-pipeline.log 2>&1
status=$?
set -e
echo "$status" > results/VALIDATION_EXIT_STATUS
exit "$status"
