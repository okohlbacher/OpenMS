#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-libxml2-replacement-20261020-01a153cb
cd "$root"
while ! test -f results/VALIDATION_EXIT_STATUS; do sleep 2; done
test "$(cat results/VALIDATION_EXIT_STATUS)" = 0
mkdir -p results/initial-94e69565 logs/initial-94e69565
for name in source-identity.txt build-cache.txt compile_commands.json source-diff.txt source-status.txt test-inventory.json class-tests.log CLASS_TEST_EXIT_STATUS LastTest.log LastTestsFailed.log no-xerces-check.log ci-python-tests.log linked-libraries.txt openms-libraries.sha256 VALIDATION_COMPLETE VALIDATION_EXIT_STATUS; do
 if test -f "results/$name"; then mv "results/$name" results/initial-94e69565/; fi
done
for name in configure.log build.log validation-pipeline.log base-fetch.log bundle-fetch.log; do
 if test -f "logs/$name"; then mv "logs/$name" logs/initial-94e69565/; fi
done
set +e
bash staging/run-reviewed-validation.sh > logs/reviewed-validation-pipeline.log 2>&1
status=$?
set -e
echo "$status" > results/VALIDATION_EXIT_STATUS
exit "$status"
