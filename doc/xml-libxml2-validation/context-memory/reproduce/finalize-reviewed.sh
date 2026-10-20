#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-context-memory-20261020-01a153cb
cd "$root"
while test ! -f results/PREPARATION_EXIT_STATUS; do sleep 5; done
test "$(cat results/PREPARATION_EXIT_STATUS)" = 0
for n in 1 96; do mv "results/profile-candidate-$n.jsonl" "results/profile-initial-reader-$n.jsonl"; done
cp staging/candidate/src/openms/source/FORMAT/HANDLERS/IndexedMzMLDecoder.cpp source/src/openms/source/FORMAT/HANDLERS/
cp staging/candidate/src/tests/class_tests/openms/source/IndexedMzMLDecoder_test.cpp source/src/tests/class_tests/openms/source/
cp staging/candidate/cmake/cmake_findExternalLibs.cmake source/cmake/
prefix="$root/dependencies/install"
export LD_LIBRARY_PATH="$root/build/lib:$prefix/lib:/scratch/kohlbach/contrib/build/lib" OPENMS_TMPDIR="$root/tmp" OMP_NUM_THREADS=1 OMP_DYNAMIC=FALSE OPENBLAS_NUM_THREADS=1
cmake -S source -B build -DWITH_OPENTIMS=OFF > logs/reviewed-configure.log 2>&1
cmake --build build --target IndexedMzMLDecoder_test IndexedMzMLFile_test IndexedMzMLFileLoader_test OnDiscMSExperiment_test MzMLSpectrumDecoder_test XMLFile_test XMLParserBackend_test -j24 > logs/reviewed-build.log 2>&1
ctest --test-dir build -R '^(IndexedMzMLDecoder|IndexedMzMLFile|IndexedMzMLFileLoader|OnDiscMSExperiment|MzMLSpectrumDecoder|XMLFile|XMLParserBackend)_test$' --output-on-failure -j4 > results/reviewed-tests.log 2>&1
cp -a build/lib/libOpenMS.so* build/lib/libOpenSwathAlgo.so* snapshots/candidate/lib/
cp build/CMakeCache.txt results/reviewed-cache.txt
sha256sum snapshots/candidate/lib/* > results/reviewed-libraries.sha256
export LD_LIBRARY_PATH="$root/snapshots/candidate/lib:$prefix/lib:/scratch/kohlbach/contrib/build/lib"
for n in 1 96; do taskset -c 0-95 benchmark-build/context_profile data/large-matched-plain.mzML "$n" > "results/profile-candidate-$n.jsonl"; done
ctest --test-dir benchmark-build --output-on-failure > results/reviewed-harness-tests.log 2>&1
python3 source/tools/ci/check_no_xerces.py --build-dir build > results/reviewed-no-xerces-check.log 2>&1
cp staging/meter.py staging/run-targeted.py "$root/"
python3 - <<'PY'
from pathlib import Path
import hashlib,json
r=Path.cwd();rows={}
for p in sorted((r/'staging/candidate').rglob('*')):
 if p.is_file():
  n=str(p.relative_to(r/'staging/candidate'));a=r/'source'/n
  assert a.read_bytes()==p.read_bytes(),n
  rows[n]=hashlib.sha256(p.read_bytes()).hexdigest()
(r/'results/reviewed-source-files.json').write_text(json.dumps(rows,indent=2)+'\n')
old=json.loads((r/'staging/previous-inputs.json').read_text())
for name in ['large-matched-plain.mzML','large-matched-zlib.mzML','dda-lumos.mzML','pasef-published.mzML']:
 p=r/'data'/name
 with p.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==old[name]['sha256'],name
PY
touch results/REVIEWED_BUILD_COMPLETE
