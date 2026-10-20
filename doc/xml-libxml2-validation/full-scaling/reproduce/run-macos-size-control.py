from pathlib import Path
import os,subprocess,shutil,json,hashlib,time
root=Path(__file__).resolve().parents[3];out=root/'results/full-scaling/macos';snap=out/'snapshots';snap.mkdir(exist_ok=True)
variants={'full-homebrew':(root/'OpenMS-replacement-build/lib',Path('/opt/homebrew/opt/libxml2/lib/libxml2.16.dylib')),'full-o2':(root/'OpenMS-replacement-build/lib',root/'dependencies/libxml2-speed/install-o2/lib/libxml2.16.dylib'),'full-os':(root/'OpenMS-replacement-build/lib',root/'dependencies/libxml2-speed/install-os/lib/libxml2.16.dylib')}
for label,(directory,parser) in variants.items():
 dest=snap/label/'lib';dest.mkdir(parents=True,exist_ok=True)
 for name in ['libOpenMS.dylib','libOpenSwathAlgo.dylib']:shutil.copy2(directory/name,dest/name)
 if parser:
  p=dest/'libxml2.16.dylib'
  if p.is_symlink():p.unlink()
  p.symlink_to(parser)
binary=root/'benchmark-optimized-build/xml_parser_benchmark';launcher=binary.with_name('xml_benchmark_launcher')
# Confirm actual dyld parser resolution in a separate process before timing.
for label in variants:
 env=dict(os.environ,DYLD_LIBRARY_PATH=str(snap/label/'lib'),DYLD_PRINT_LIBRARIES='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
 result=subprocess.run([str(launcher),str(binary),'indexed-metadata',str(root/'benchmark-data/small.mzML'),'1','1'],capture_output=True,text=True,env=env)
 assert result.returncode==0,(label,result.stderr[-500:]);(out/(label+'-dyld.log')).write_text(result.stderr)
 if variants[label][1]:
  parser=variants[label][1].resolve();assert str(parser) in result.stderr or str((snap/label/'lib/libxml2.16.dylib').absolute()) in result.stderr,(label,result.stderr)
cmd=['python3',str(root/'OpenMS-libxml2/tools/xml-parser-benchmark/run_benchmarks.py'),'--binary',str(binary)]
for label in variants:cmd+=['--backend',label+'='+str(snap/label/'lib')]
for name in ['large.mzML','large-utf8.mzML']:cmd+=['--input',str(root/'benchmark-data'/name)]
cmd+=['--workers','1','--modes','stream,indexed-metadata','--repetitions','5','--queries','2048','--output',str(out/'size-control.json')]
(out/'size-control-experiment.json').write_text(json.dumps({'source_commit':'8f66b3d921c9512e1e5968f494c77715ff71c696','started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'command':cmd,'variants':{k:{'OpenMS_source':'experimental one-unit discard-first patch' if k.startswith('discard') else 'full replacement' if k.startswith('full') else 'published optimized Xerces','parser':str(p.resolve()) if p else 'Homebrew Xerces3.3.0'} for k,(d,p) in variants.items()},'note':'Private experiments only; production sources and dependency choices unchanged. O2/O3 have identical source/features; Homebrew is a separately packaged reference.'},indent=2)+'\n')
with(out/'size-control-runs.log').open('w') as log:r=subprocess.run(cmd,env=dict(os.environ,OMP_DYNAMIC='FALSE',OMP_WAIT_POLICY='passive'),stdout=log,stderr=subprocess.STDOUT)
assert r.returncode==0,r.returncode
print('Mac optimization matrix complete')
