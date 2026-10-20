from pathlib import Path
import subprocess,os,json,hashlib,time
root=Path(__file__).resolve().parents[2];out=root/'results/encoding-final185/macos'
while 'Total Test time (real)' not in (root/'replacement-validation/ctest-final-guard.log').read_text():time.sleep(5)
time.sleep(5)
binary=root/'benchmark-optimized-build/xml_parser_benchmark';runner=root/'OpenMS-libxml2/tools/xml-parser-benchmark/run_benchmarks.py'
cmd=['python3',str(runner),'--binary',str(binary),'--backend','xerces='+str(root/'snapshots-optimized/xerces/lib'),'--backend','libxml2-poc='+str(root/'snapshots-optimized/libxml2/lib'),'--backend','libxml2-full='+str(root/'OpenMS-replacement-build/lib'),'--input',str(root/'benchmark-data/large.mzML'),'--input',str(root/'benchmark-data/large-utf8.mzML'),'--workers','1','--modes','stream,indexed-metadata','--repetitions','5','--queries','2048','--output',str(out/'benchmarks.json')]
meta={'command':cmd,'method':'Timo declaration-only experiment; frozen published optimized Xerces/libxml2 PoC snapshots plus full-removal candidate; five randomized repeats per cell; cached input, independent fresh process; default indexed open reported via job open_seconds,2048 query reads reported separately.','candidate':subprocess.check_output(['git','-C',str(root/'OpenMS-libxml2'),'rev-parse','HEAD'],text=True).strip(),'cpu':subprocess.check_output(['sysctl','-n','machdep.cpu.brand_string'],text=True).strip(),'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'source_comment':'https://github.com/OpenMS/OpenMS/issues/10623#issuecomment-6284417895','native_parser_flags':'Homebrew parser dependencies unchanged; original macOS parser compile flags were not normalized to OpenMS Release flags.'}
for name,path in [('libxml2','/opt/homebrew/opt/libxml2/lib/libxml2.dylib'),('xerces','/opt/homebrew/opt/xerces-c/lib/libxerces-c.dylib')]:
 p=Path(path);meta[name]={'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
(out/'experiment.json').write_text(json.dumps(meta,indent=2)+'\n')
with (out/'runs.log').open('w') as log:r=subprocess.run(cmd,cwd=root,stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,OMP_DYNAMIC='FALSE',OMP_WAIT_POLICY='passive'))
print('Encoding experiment exit',r.returncode,flush=True)
raise SystemExit(r.returncode)
