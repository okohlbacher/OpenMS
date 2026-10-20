#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb
cd "$root"
test "$(cat results/BUILD_EXIT_STATUS)" = 0
export LD_LIBRARY_PATH="$root/dependencies/install/lib:/scratch/kohlbach/contrib/build/lib" OPENMS_TMPDIR="$root/tmp" OMP_NUM_THREADS=8 OPENBLAS_NUM_THREADS=1
# Timed source/DLL snapshots are already frozen. Enable the vendor reader only
# in the separate conversion build artifact, never in the timed snapshots.
cmake -S source-libxml2-full -B build-libxml2-full -DWITH_OPENTIMS=ON > logs/converter-openms-configure.log 2>&1
cmake --build build-libxml2-full --target OpenMS -j24 > logs/converter-openms-build.log 2>&1
cmake -S staging/converter-source -B converter-build -DOpenMS_DIR="$root/build-libxml2-full" -DCMAKE_BUILD_TYPE=Release > logs/converter-configure.log 2>&1
cmake --build converter-build -j8 > logs/converter-build.log 2>&1
cp build-libxml2-full/CMakeCache.txt results/converter-openms-cache.txt
sha256sum build-libxml2-full/lib/libOpenMS.so* > results/converter-openms-libraries.sha256
# Called separately after copying and verifying the public raw input.
touch results/CONVERTER_BUILD_COMPLETE
