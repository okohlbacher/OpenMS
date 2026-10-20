#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb
cd "$root"
export LD_LIBRARY_PATH="$root/snapshots/xerces/lib:$root/dependencies/install/lib:/scratch/kohlbach/contrib/build/lib" OPENMS_TMPDIR="$root/tmp" OMP_NUM_THREADS=1 OMP_DYNAMIC=FALSE OPENBLAS_NUM_THREADS=1
mkdir -p post-controls
# The shared timing binary was built against the Xerces SDK. Writing uses handler
# inheritance whose ABI changed: only generate against its own SDK/backend.
for form in plain zlib; do
 extra=();if [[ "$form" == zlib ]]; then extra=(zlib);fi
 extended-benchmark-build/xml_parser_benchmark generate "post-controls/large-matched-$form.mzML" 131072 2048 "${extra[@]}" > "logs/native-sdk-regenerate-$form.log" 2>&1
done
python3 - <<'PY'
import hashlib,json
from pathlib import Path
root=Path.cwd();out={}
for form in ['plain','zlib']:
 old=root/'data'/f'large-matched-{form}.mzML';new=root/'post-controls'/old.name
 def sha(p):
  with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
 out[form]={'native_sdk':'xerces58aa; same SDK as timing binary','original_sha256':sha(old),'native_regenerated_sha256':sha(new),'bytes':new.stat().st_size,'byte_identical':sha(old)==sha(new)}
(root/'results/gap/native-sdk-generation-control.json').write_text(json.dumps(out,indent=2)+'\n')
assert all(r['byte_identical'] for r in out.values()),out
PY
cp results/gap/audit-tests.json results/gap/audit-tests-before-generation-sdk-fix.json
python3 post-control-source/test-audit.py > logs/native-sdk-audit-tests.log 2>&1
# Compile the same harness against the full SDK and run its untimed smoke suite
# against its own build DLL (WITH_OPENTIMS=ON conversion build). Timed DLLs unchanged.
cmake -S staging/extended-benchmark-source -B native-full-control-build -DOpenMS_DIR="$root/build-libxml2-full" -DCMAKE_BUILD_TYPE=Release > logs/native-full-control-configure.log 2>&1
cmake --build native-full-control-build --target xml_parser_benchmark xml_benchmark_launcher -j8 > logs/native-full-control-build.log 2>&1
LD_LIBRARY_PATH="$root/build-libxml2-full/lib:$root/dependencies/install/lib:/scratch/kohlbach/contrib/build/lib" ctest --test-dir native-full-control-build --output-on-failure > results/gap/native-full-sdk-smoke.log 2>&1
LD_LIBRARY_PATH="$root/snapshots/xerces/lib:$root/dependencies/install/lib:/scratch/kohlbach/contrib/build/lib" ctest --test-dir extended-benchmark-build --output-on-failure > results/gap/native-xerces-sdk-smoke.log 2>&1
touch results/gap/NATIVE_SDK_CONTROLS_COMPLETE
