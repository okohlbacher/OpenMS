#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb
cd "$root"
test "$(cat results/BUILD_EXIT_STATUS)" = 0
export LD_LIBRARY_PATH="$root/dependencies/install/lib:/scratch/kohlbach/contrib/build/lib"
export OPENMS_TMPDIR="$root/tmp" OMP_NUM_THREADS=1 OMP_DYNAMIC=FALSE OPENBLAS_NUM_THREADS=1 LC_ALL=C.UTF-8
cmake -S staging/extended-benchmark-source -B extended-benchmark-build -DOpenMS_DIR="$root/build-xerces" -DCMAKE_BUILD_TYPE=Release > logs/extended-configure.log 2>&1
cmake --build extended-benchmark-build --target xml_parser_benchmark xml_benchmark_launcher -j8 > logs/extended-build.log 2>&1
for backend in xerces libxml2-full; do
 if [[ "$backend" == xerces ]]; then LD_LIBRARY_PATH="$root/snapshots/$backend/lib:$LD_LIBRARY_PATH" ctest --test-dir extended-benchmark-build --output-on-failure > "results/$backend-extended-smoke.log" 2>&1; fi
 LD_LIBRARY_PATH="$root/snapshots/$backend/lib:$LD_LIBRARY_PATH" extended-benchmark-build/xml_parser_benchmark verify data/huge-array.mzML 1 2048 > "results/$backend-extended-million-points.json" 2> "logs/$backend-extended-million-points.log"
done
LD_LIBRARY_PATH="$root/snapshots/xerces/lib:$LD_LIBRARY_PATH" extended-benchmark-build/xml_parser_benchmark generate data/large-matched-plain.mzML 131072 2048 > logs/generate-plain.log 2>&1
LD_LIBRARY_PATH="$root/snapshots/xerces/lib:$LD_LIBRARY_PATH" extended-benchmark-build/xml_parser_benchmark generate data/large-matched-zlib.mzML 131072 2048 zlib > logs/generate-zlib.log 2>&1
gzip -n -6 -c data/large-matched-plain.mzML > data/large-matched-plain.mzML.gz
gzip -n -6 -c data/large-matched-zlib.mzML > data/large-matched-zlib.mzML.gz
python3 - <<'PY'
from pathlib import Path
import hashlib,json
root=Path.cwd();rows={}
for p in sorted((root/'data').glob('large-matched-*')):
 assert p.stat().st_size>=1_000_000_000,p
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 rows[p.name]={'bytes':p.stat().st_size,'sha256':h.hexdigest()}
assert len(rows)==4
(root/'results/matched-inputs.json').write_text(json.dumps(rows,indent=2)+'\n');print(rows)
PY
touch results/EXTENDED_DATA_COMPLETE
