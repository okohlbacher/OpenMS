#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb
cd "$root"
test -f results/CONVERTER_BUILD_COMPLETE
python3 - <<'PY'
import json,hashlib,sqlite3
from pathlib import Path
root=Path.cwd();manifest=json.loads((root/'staging/real-input-manifest.json').read_text())
for row in manifest['files']:
 p=root/'data'/row['destination'];h=hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
 assert p.stat().st_size==row['bytes'] and h==row['sha256'],p
manifest['remote_verified']=True
(root/'results/real-inputs-verified.json').write_text(json.dumps(manifest,indent=2)+'\n')
c=sqlite3.connect('file:'+str(root/'data/SBA415.d/analysis.tdf')+'?mode=ro',uri=True)
rows=c.execute('SELECT MsMsType,count(*),sum(NumPeaks),min(Time),max(Time) FROM Frames GROUP BY MsMsType').fetchall()
(root/'results/raw-tims-provenance.json').write_text(json.dumps({'query':'SELECT MsMsType,count(*),sum(NumPeaks),min(Time),max(Time) FROM Frames GROUP BY MsMsType','rows':rows,'conversion_rt_seconds':[600,1200],'calibration':'OpenMS RATIONAL from TDF calibration tables; no proprietary SDK','conversion_library':'WITH_OPENTIMS=ON; timed snapshots remain OFF'},indent=2)+'\n')
PY
export LD_LIBRARY_PATH="$root/build-libxml2-full/lib:$root/dependencies/install/lib:/scratch/kohlbach/contrib/build/lib" OPENMS_TMPDIR="$root/tmp" OMP_NUM_THREADS=8 OPENBLAS_NUM_THREADS=1
/usr/bin/time -v converter-build/convert_tims data/SBA415.d data/pasef-im-600-1200s.mzML > logs/conversion.log 2>&1
sha256sum data/pasef-im-600-1200s.mzML > results/converted-im.sha256
touch results/CONVERSION_COMPLETE
