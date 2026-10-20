"""Separately preserved, longer read checks only for primary >5% loop flags."""
from pathlib import Path
import hashlib,importlib.util,json,os,random,time,traceback,threading
ROOT=Path('/scratch/kohlbach/openms-context-memory-20261020-01a153cb')
OUT=ROOT/'results/confirmation';OUT.mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('primary',ROOT/'run-targeted.py');primary=importlib.util.module_from_spec(spec);spec.loader.exec_module(primary)
g=primary.g;g.OUT=OUT

def main():
 os.sched_setaffinity(0,set(range(96,128)))
 protocol=json.loads((ROOT/'staging/confirmation-protocol.json').read_text())
 refs={};controls=[];mapped=set()
 def call(c):
  name=c['input'];n=c['workers'];q=2048 if name=='pasef-im-600-1200s.mzML' else 8192
  mask='0' if n==1 else f'0-{n-1}'
  row=g.measure([g.LAUNCHER,'/usr/bin/taskset','-c',mask,g.BINARY,'indexed-sync',ROOT/'data'/name,n,q],g.env(c['version']))
  if not row['ok']:
   with (OUT/'failures.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
   raise RuntimeError('Confirmation process failed')
  assert row['cpu_affinity']==mask and row['native_exit_code']==0
  assert str(ROOT/'snapshots'/c['version']/'lib') in row['openms_library']
  assert len(row['jobs'])==n and any('libxml2.so' in p for p in row['loaded_library_maps'])
  assert not any('libxerces' in p.lower() for p in row['loaded_library_maps'])
  return row
 for name in sorted({c['input'] for c in protocol['cases']}):
  for v in ['baseline','candidate']:
   r=call(dict(input=name,workers=1,version=v))
   if name in refs:assert refs[name]==g.fingerprint(r)
   refs[name]=g.fingerprint(r);mapped.update(r['loaded_library_maps']);controls.append(dict(r,input=name,version=v))
 (OUT/'controls.json').write_text(json.dumps(controls,indent=2)+'\n')
 identity=dict(primary_identity=json.loads((ROOT/'results/measurements/identity.json').read_text()),wrapper_sha256=g.sha(Path(__file__)),protocol=protocol,taskset_sha256=g.sha(Path('/usr/bin/taskset')),mapped_files={p:g.sha(Path(p)) for p in sorted(mapped)})
 identity_sha=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest();(OUT/'identity.json').write_text(json.dumps(identity,indent=2)+'\n')
 cells=[dict(c,version=v,rep=rep) for c in protocol['cases'] for v in ['baseline','candidate'] for rep in range(3)]
 assert len(cells)==54
 random.Random(20261023).shuffle(cells);(OUT/'schedule.json').write_text(json.dumps(cells,indent=2)+'\n')
 stop=threading.Event();monitor=threading.Thread(target=g.monitor,args=(stop,),daemon=True);monitor.start()
 try:
  with (OUT/'records.jsonl').open('w',buffering=1) as f:
   for i,c in enumerate(cells):
    cache=g.cached_input(ROOT/'data'/c['input']);r=call(c);assert g.fingerprint(r)==refs[c['input']]
    assert all(p in mapped for p in r['loaded_library_maps'])
    r.update(cell=c,input_cache_before=cache,confirmation_identity_sha256=identity_sha,completed_unix=time.time());f.write(json.dumps(r,sort_keys=True)+'\n');os.fsync(f.fileno());print(i+1,'/54',c,flush=True)
 finally:stop.set();monitor.join()
 assert all(g.sha(Path(p))==h for p,h in identity['mapped_files'].items())
 assert primary.identity(json.loads((ROOT/'results/measurements/bound-library-paths.json').read_text()))==identity['primary_identity']
 (OUT/'ALL_COMPLETE').touch()

if __name__=='__main__':
 receipt=dict(started_unix=time.time())
 try:main();receipt['status']='complete'
 except BaseException:receipt.update(status='failed',traceback=traceback.format_exc());raise
 finally:receipt['completed_unix']=time.time();(OUT/'launch.json').write_text(json.dumps(receipt,indent=2)+'\n')
