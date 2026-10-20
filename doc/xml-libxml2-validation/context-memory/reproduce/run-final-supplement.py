"""Sustained confirmations only for final short-loop flags, exact primary affinity."""
from pathlib import Path
import importlib.util,json,os,random,time,hashlib
ROOT=Path('/scratch/kohlbach/openms-context-memory-20261020-01a153cb');OUT=ROOT/'results/final-supplement';OUT.mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('p',ROOT/'post-checks/run-final-targeted.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);g=m.g;g.OUT=OUT
os.sched_setaffinity(0,set(range(96,128)))
identity=json.loads((ROOT/'results/final-targeted/identity.json').read_text())
for group in ['files','mapped_files']:assert all(g.sha(Path(p))==h for p,h in identity[group].items())
cases=[('dda-lumos.mzML',32),('dda-lumos.mzML',64),('large-matched-plain.mzML',64),('large-matched-zlib.mzML',64),('pasef-published.mzML',64)]
prior=[json.loads(l) for l in (ROOT/'results/final-targeted/records.jsonl').read_text().splitlines()]
refs={name:g.fingerprint(next(r for r in prior if r['cell']['phase']=='sustained' and r['cell']['input']==name)) for name,n in cases}
cells=[dict(input=name,workers=n,version=v,mode='indexed-sync',queries=8192,phase='primary-affinity-sustained',rep=rep) for name,n in cases for v in ['baseline','candidate'] for rep in range(3)]
random.Random(20261026).shuffle(cells);(OUT/'schedule.json').write_text(json.dumps(cells,indent=2)+'\n')
receipt=dict(started_unix=time.time());hashes=dict(parent_identity_sha256=g.sha(ROOT/'results/final-targeted/identity.json'),wrapper_sha256=g.sha(Path(__file__)),cases=cases,affinity='0-95',basis='all final primary worker-loop >5% flags; all repetitions, matched sustained primary CPU mask')
(OUT/'identity.json').write_text(json.dumps(hashes,indent=2)+'\n')
try:
 with (OUT/'records.jsonl').open('w',buffering=1) as f:
  for i,c in enumerate(cells):
   cache=g.cached_input(ROOT/'data'/c['input']);r=m.call(dict(c,phase='primary'),8192)
   assert r['cpu_affinity']=='0-95' and g.fingerprint(r)==refs[c['input']]
   assert all(p in identity['mapped_files'] for p in r['loaded_library_maps'])
   r.update(cell=c,input_cache_before=cache,completed_unix=time.time());f.write(json.dumps(r)+'\n');os.fsync(f.fileno());print(i+1,'/30',c,flush=True)
 for group in ['files','mapped_files']:assert all(g.sha(Path(p))==h for p,h in identity[group].items())
 assert all(g.sha(ROOT/'data'/name)==v['sha256'] for name,v in identity['inputs'].items())
 (OUT/'ALL_COMPLETE').touch();receipt['status']='complete'
finally:receipt['completed_unix']=time.time();(OUT/'launch.json').write_text(json.dumps(receipt,indent=2)+'\n')
