"""Post-matrix validation probes; monitored runs are NOT performance records."""
from pathlib import Path
import datetime,json,os,subprocess,time
root=Path('/scratch/kohlbach/openms-libxml2-scaling-20261020-01a153cb');assert (root/'results/PIPELINE_EXIT_STATUS').read_text().strip()=='0';os.sched_setaffinity(0,set(range(96)))
binary=root/'benchmark-build/xml_parser_benchmark';launcher=binary.with_name('xml_benchmark_launcher');results=[];matrix=json.loads((root/'results/benchmarks.json').read_text())
for workers,omp in [(96,1),(1,96)]:
 for backend in ['xerces','libxml2-full']:
  env=dict(os.environ,OMP_NUM_THREADS=str(omp),OMP_DYNAMIC='FALSE',OPENBLAS_NUM_THREADS='1',OPENMS_TMPDIR=str(root/'tmp'),LD_LIBRARY_PATH=f'{root}/snapshots/{backend}/lib:{root}/dependencies/install/lib:/scratch/kohlbach/contrib/build/lib')
  p=subprocess.Popen([str(launcher),str(binary),'stream',str(root/'data/large.mzML'),str(workers),'0'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);peak=0;samples=0;xerces_mapped=False;begin=time.monotonic()
  while p.poll() is None:
   try:
    status=Path(f'/proc/{p.pid}/status').read_text();peak=max(peak,next(int(l.split()[1]) for l in status.splitlines() if l.startswith('Threads:')));samples+=1
    if samples%25==0:xerces_mapped|='libxerces-c' in Path(f'/proc/{p.pid}/maps').read_text()
   except (FileNotFoundError,StopIteration):pass
   if time.monotonic()-begin>120:p.kill();raise RuntimeError('Thread probe timed out')
   time.sleep(.02)
  stdout,stderr=p.communicate();assert p.returncode==0,(backend,stderr);row=json.loads(stdout);expected=next(r for r in matrix['records'] if r['backend']==backend and Path(r['input']).name=='large.mzML' and r['mode']=='stream');assert row['hash_per_worker']==expected['hash_per_worker']
  if backend=='libxml2-full':assert not xerces_mapped
  results.append({'backend':backend,'reader_workers':workers,'requested_OpenMP_threads':omp,'peak_native_process_threads':peak,'samples':samples,'sample_interval_seconds':.02,'returncode':p.returncode,'decoded_fingerprint_matches_matrix':True,'xerces_mapped':xerces_mapped,'benchmark_output':row})
  print(backend,workers,omp,peak,flush=True)
(root/'results/thread-census.json').write_text(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'note':'Four post-matrix validation probes with procfs sampling. NOT included in canonical performance medians or process-record counts. Includes main thread and retained runtime teams.','results':results},indent=2)+'\n')
