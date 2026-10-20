"""Probe only the confirmed IM read regressions for the separate buffer candidate."""
from pathlib import Path
import importlib.util,json,os,statistics,time,hashlib,random
root=Path('/scratch/kohlbach/openms-context-memory-20261020-01a153cb');out=root/'results/buffer-speed';out.mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('previous',root/'run-targeted.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);g=m.g;g.OUT=out
os.sched_setaffinity(0,set(range(96,128)))
prior=[json.loads(line) for line in (root/'results/confirmation/records.jsonl').read_text().splitlines()]
ref=next(g.fingerprint(r) for r in prior if r['cell']['input']=='pasef-im-600-1200s.mzML')
cells=[dict(workers=n,rep=rep) for n in [32,64,96] for rep in range(3)];random.Random(20261024).shuffle(cells)
with (out/'records.jsonl').open('w',buffering=1) as f:
 for c in cells:
  n=c['workers'];cache=g.cached_input(root/'data/pasef-im-600-1200s.mzML')
  r=g.measure([g.LAUNCHER,'/usr/bin/taskset','-c',f'0-{n-1}',g.BINARY,'indexed-sync',root/'data/pasef-im-600-1200s.mzML',n,2048],g.env('candidate-buffer'))
  assert r['ok'] and r['native_exit_code']==0 and g.fingerprint(r)==ref
  assert '/snapshots/candidate-buffer/lib/' in r['openms_library']
  r.update(cell=c,input_cache_before=cache,completed_unix=time.time());f.write(json.dumps(r)+'\n');os.fsync(f.fileno());print(c,flush=True)
(out/'ALL_COMPLETE').touch()
