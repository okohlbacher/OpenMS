#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-context-memory-20261020-01a153cb
cd "$root"
trap 'printf "%s\n" "$?" > results/PREPARATION_EXIT_STATUS' EXIT
while test ! -f results/BASELINE_BUILD_COMPLETE; do
 if ! kill -0 "$(cat results/build-launcher.pid)" 2>/dev/null; then echo 'Baseline build failed';exit 1;fi
 sleep 5
done
prefix="$root/dependencies/install"
export LD_LIBRARY_PATH="$root/snapshots/baseline/lib:$prefix/lib:/scratch/kohlbach/contrib/build/lib" OPENMS_TMPDIR="$root/tmp" OMP_NUM_THREADS=1 OMP_DYNAMIC=FALSE OPENBLAS_NUM_THREADS=1
printf '%s  %s\n' facea08f452382d13226ab81bf8a97698f3f701489f01ce79a0b0835e04bfa7c staging/libxml2-full.tar.gz | sha256sum -c -
cmake -S staging/benchmark-source -B benchmark-build -DOpenMS_DIR="$root/build" -DCMAKE_BUILD_TYPE=Release > logs/harness-configure.log 2>&1
cmake --build benchmark-build -j8 > logs/harness-build.log 2>&1
ctest --test-dir benchmark-build --output-on-failure > results/baseline-harness-tests.log 2>&1
benchmark-build/xml_parser_benchmark generate data/large-matched-plain.mzML 131072 2048 > logs/generate-plain.log 2>&1
benchmark-build/xml_parser_benchmark generate data/large-matched-zlib.mzML 131072 2048 zlib > logs/generate-zlib.log 2>&1
for n in 1 96; do taskset -c 0-95 benchmark-build/context_profile data/large-matched-plain.mzML "$n" > "results/profile-baseline-$n.jsonl"; done
cp staging/candidate/src/openms/source/FORMAT/HANDLERS/IndexedMzMLDecoder.cpp source/src/openms/source/FORMAT/HANDLERS/
cp staging/candidate/src/tests/class_tests/openms/source/IndexedMzMLDecoder_test.cpp source/src/tests/class_tests/openms/source/
cp staging/candidate/cmake/cmake_findExternalLibs.cmake source/cmake/
cmake --build build --target IndexedMzMLDecoder_test IndexedMzMLFile_test IndexedMzMLFileLoader_test OnDiscMSExperiment_test MzMLSpectrumDecoder_test XMLFile_test XMLParserBackend_test -j24 > logs/candidate-build.log 2>&1
ctest --test-dir build -R '^(IndexedMzMLDecoder|IndexedMzMLFile|IndexedMzMLFileLoader|OnDiscMSExperiment|MzMLSpectrumDecoder|XMLFile|XMLParserBackend)_test$' --output-on-failure -j4 > results/candidate-tests.log 2>&1
mkdir -p snapshots/candidate/lib
cp -a build/lib/libOpenMS.so* build/lib/libOpenSwathAlgo.so* snapshots/candidate/lib/
cp build/CMakeCache.txt results/candidate-cache.txt
sha256sum snapshots/candidate/lib/* > results/candidate-libraries.sha256
export LD_LIBRARY_PATH="$root/snapshots/candidate/lib:$prefix/lib:/scratch/kohlbach/contrib/build/lib"
ctest --test-dir benchmark-build --output-on-failure > results/candidate-harness-tests.log 2>&1
for n in 1 96; do taskset -c 0-95 benchmark-build/context_profile data/large-matched-plain.mzML "$n" > "results/profile-candidate-$n.jsonl"; done
python3 source/tools/ci/check_no_xerces.py --build-dir build > results/no-xerces-check.log 2>&1
touch results/CANDIDATE_BUILD_COMPLETE
# The separate conversion artifact never supplies a timed library.
cmake -S source -B build -DWITH_OPENTIMS=ON > logs/converter-openms-configure.log 2>&1
cmake --build build --target OpenMS -j24 > logs/converter-openms-build.log 2>&1
cmake -S staging/converter-source -B converter-build -DOpenMS_DIR="$root/build" -DCMAKE_BUILD_TYPE=Release > logs/converter-configure.log 2>&1
cmake --build converter-build -j8 > logs/converter-build.log 2>&1
python3 - <<'PY'
from pathlib import Path
import json,time,hashlib
r=Path.cwd();m=json.loads((r/'staging/real-input-manifest.json').read_text())
while not all((r/'data'/v['destination']).is_file() and (r/'data'/v['destination']).stat().st_size==v['bytes'] for v in m['files']):time.sleep(5)
for v in m['files']:
 p=r/'data'/v['destination']
 with p.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==v['sha256'],p
(r/'results/real-input-verification.json').write_text(json.dumps(m,indent=2)+'\n')
PY
export LD_LIBRARY_PATH="$root/build/lib:$prefix/lib:/scratch/kohlbach/contrib/build/lib" OMP_NUM_THREADS=8
/usr/bin/time -v converter-build/convert_tims data/SBA415.d data/pasef-im-600-1200s.mzML > logs/conversion.log 2>&1
sha256sum data/*.mzML > results/input-sha256.txt
g++ -O2 -std=c++17 staging/native-meter.cpp -o native-meter
cp staging/meter.py staging/run-targeted.py "$root/"
touch results/PREPARATION_COMPLETE
