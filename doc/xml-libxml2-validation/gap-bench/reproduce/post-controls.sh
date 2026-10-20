#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb
cd "$root"
while test ! -f results/gap/ALL_MEASUREMENTS_COMPLETE; do
 if ! test -r "/proc/$(cat results/gap/launcher.pid)/stat"; then echo 'Timing launcher exited without completion';exit 1;fi
 sleep 30
done
python3 post-control-source/verify-final.py
touch results/gap/POST_CONTROLS_COMPLETE
