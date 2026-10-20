#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-libxml2-replacement-20261020-01a153cb
cd "$root"
export LD_LIBRARY_PATH="$root/build/lib:$root/dependencies/install/lib:/scratch/kohlbach/contrib/build/lib"
export LC_ALL=C.UTF-8 OPENMS_TMPDIR="$root/tmp" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
cmake -S source/tools/xml-parser-benchmark -B benchmark-build -DOpenMS_DIR="$root/build" -DCMAKE_BUILD_TYPE=Release > logs/benchmark-configure.log 2>&1
cmake --build benchmark-build -j8 > logs/benchmark-build.log 2>&1
ctest --test-dir benchmark-build --output-on-failure > results/benchmark-tests.log 2>&1
python3 staging/run-dom-version-supplemental.py > logs/supplemental.log 2>&1
touch results/SUPPLEMENTAL_COMPLETE
