#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb
cd "$root"
echo $$ > results/gap/launcher.pid
test "$(cat results/PREPARATION_EXIT_STATUS)" = 0
test -f results/CONVERSION_COMPLETE
test -f results/gap/audit-tests.json
while test ! -f results/gap/CORRECTNESS_COMPLETE; do
 if ! pgrep -u "$(id -u)" -f '^python3 run-gap.py audit$' > /dev/null; then echo 'Correctness process exited without completion'; exit 1; fi
 sleep 10
done
test -f results/gap/FINAL_GATES_COMPLETE
test -f results/gap/ACCESS_PREFLIGHT_COMPLETE
test -f results/gap/NATIVE_SDK_CONTROLS_COMPLETE
test -f results/gap/IDENTITY_REWRITE_TEST_COMPLETE
python3 run-gap.py run > logs/gap-matrix.log 2>&1
python3 run-access.py > logs/gap-access.log 2>&1
free -b > results/gap/memory-after.txt
uptime > results/gap/load-after.txt
touch results/gap/ALL_MEASUREMENTS_COMPLETE
