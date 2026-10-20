from pathlib import Path
from collections import defaultdict
import json,hashlib
root=Path('/scratch/kohlbach/openms-libxml2-scaling-20261020-01a153cb');counts={'benchmarks':1280,'memory-scaling':480,'metadata-scaling':320,'openmp-scaling':160,'encoding-followup':40};workers={1,2,4,8,16,32,64,96};outputs={};fingerprints={}
for name,expected in counts.items():
 x=json.loads((root/'results'/(name+'.json')).read_text());assert len(x['records'])==expected,(name,len(x['records']));assert not x['failures'],(name,x['failures'])
 assert {r['backend'] for r in x['records']}=={'xerces','libxml2-full'}
 groups=defaultdict(list)
 for r in x['records']:
  n=r['openmp_threads'] if name=='openmp-scaling' else r['workers'];groups[r['backend'],r['input'],r['mode'],n].append(r)
  assert r['max_rss_bytes']>0 and r['process_seconds']>0
  key=(r['input'],r['mode']);digest=tuple(r[k] for k in ['hash_per_worker','spectra_per_worker','chromatograms_per_worker','points_per_worker','index_spectra','index_chromatograms'])
  assert key not in fingerprints or fingerprints[key]==digest,(key,r);fingerprints[key]=digest
  if r['mode'].startswith('contexts'):assert r['resident_rss_bytes']>0
 for k,rows in groups.items():assert len(rows)==5,(name,k,len(rows))
 assert {k[-1] for k in groups}==({1} if name=='encoding-followup' else workers)
 for backend,files in x['libraries'].items():
  for p,h in files.items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,p
 outputs[name]={'records':expected,'cells':len(groups),'all_fingerprints_match':True,'library_hashes_unchanged':True}
(root/'results/final-validation.json').write_text(json.dumps(outputs,indent=2)+'\n');print(json.dumps(outputs,indent=2))
