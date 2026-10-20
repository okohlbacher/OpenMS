from pathlib import Path
import importlib.util,json,os
root=Path('/scratch/kohlbach/openms-context-memory-20261020-01a153cb')
spec=importlib.util.spec_from_file_location('p',root/'run-targeted.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);g=m.g
os.sched_setaffinity(0,set(range(96,128)))
rows=[]
for v in ['baseline','candidate','candidate-buffer']:
 e=g.env(v);e['MALLOC_MMAP_THRESHOLD_']='16777216'
 r=g.measure([g.LAUNCHER,'/usr/bin/taskset','-c','0-63',g.BINARY,'indexed-sync',root/'data/pasef-im-600-1200s.mzML',64,2048],e)
 assert r['ok'];r['diagnostic_version']=v;rows.append(r)
 print(v,r['synchronized_read_seconds'],r['native_minflt'],flush=True)
(root/'results/allocator-diagnostic.json').write_text(json.dumps(rows,indent=2)+'\n')
