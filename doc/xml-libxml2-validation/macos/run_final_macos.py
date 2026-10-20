from pathlib import Path
import os, subprocess, json, hashlib, time
work=Path(__file__).resolve().parent.parent; out=work/'replacement-validation'; src=work/'OpenMS-libxml2'; build=work/'OpenMS-replacement-build'; bins=out/'benchmark-build'
env=dict(os.environ,DYLD_LIBRARY_PATH=str(build/'lib'),OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',OMP_DYNAMIC='FALSE')
def run(args, log, expected=0):
 with (out/log).open('w') as f:r=subprocess.run(list(map(str,args)),cwd=work,env=env,stdout=f,stderr=subprocess.STDOUT)
 assert r.returncode==expected,(args,r.returncode)
def capture(args):
 r=subprocess.run(list(map(str,args)),cwd=work,env=env,capture_output=True,text=True);return r
for component in ['library','OpenMS_headers']:
 run(['cmake','--install',build,'--prefix',out/'sdk','--component',component],f'sdk-install-opus-{component}.log')
run(['cmake','--build',out/'consumer-build','-j4'],'consumer-build-opus.log')
run([out/'consumer-build/consumer'],'consumer-run-opus.log')
run(['cmake','--build',bins,'-j4'],'benchmark-build-opus.log')
run(['ctest','--test-dir',bins,'--output-on-failure'],'benchmark-smoke-opus.log')
r=capture([bins/'xml_benchmark_launcher',bins/'xml_parser_benchmark','verify',work/'benchmark-data/huge-array.mzML','1','2048']);assert r.returncode==0,r.stderr
value=json.loads(next(s for s in r.stdout.splitlines() if s.startswith('{')));assert value=={'verified':True,'spectra':1,'points':1048577,'hash':'16141847955750882229'},value
(out/'huge-array-opus.json').write_text(json.dumps(value,indent=2)+'\n');(out/'huge-array-opus-stderr.log').write_text(r.stderr)
run(['python3',out/'run_native_conformance.py'],'conformance-run-opus.log')
run(['python3',out/'run_network_control.py'],'network-control-run-opus.log')
run(['python3',src/'tools/ci/check_no_xerces.py','--build-dir',build],'no-xerces-opus.log')
with (out/'removal-guard-tests-opus.log').open('w') as f:
 r=subprocess.run(['python3','-m','unittest','discover','-s','tools/ci/tests','-p','test_check_no_xerces.py'],cwd=src,env=env,stdout=f,stderr=subprocess.STDOUT);assert r.returncode==0
r=capture(['python3',src/'tools/xml-poc/check_schemas.py','--root',src]);assert r.returncode==0,r.stderr
(out/'schemas.json').write_text(r.stdout);(out/'schemas-stderr.log').write_text(r.stderr)
current=json.loads(r.stdout);original=json.loads((work/'results/optimized/macos/schema-results.json').read_text())
key=lambda x:{(v['file'],v['schema']):v['status'] for v in x['validation']}
assert key(current)==key(original);assert current['summary']['schema_count']==22 and current['summary']['instance_count']==195
(out/'schema-comparison.json').write_text(json.dumps({'bundled_schemas':22,'compiled':22,'instances':195,'changed_native_outcomes':[],'archived_reference':'results/optimized/macos/schema-results.json'},indent=2)+'\n')
api=[]
for case,xml,xsd,expected in [('huge-array',work/'benchmark-data/huge-array.mzML',src/'share/OpenMS/SCHEMAS/mzML_idx_1_10.xsd',True),('anyuri-windows',src/'tools/xml-poc/fixtures/anyuri-windows.xml',src/'tools/xml-poc/fixtures/anyuri.xsd',False),('anyuri-normalized',src/'tools/xml-poc/fixtures/anyuri-normalized.xml',src/'tools/xml-poc/fixtures/anyuri.xsd',True)]:
 r=capture([bins/'xml_schema_validation_probe',xml,xsd]);value=json.loads(next(s for s in r.stdout.splitlines() if s.startswith('{')));assert value['valid']==expected and r.returncode==int(not expected),(case,r)
 api.append(dict(case=case,returncode=r.returncode,stderr=r.stderr,**value))
(out/'schema-api-results.json').write_text(json.dumps({'binary_sha256':hashlib.sha256((bins/'xml_schema_validation_probe').read_bytes()).hexdigest(),'results':api},indent=2)+'\n')
artifacts=[build/'lib/libOpenMS.dylib',build/'lib/libOpenSwathAlgo.dylib',bins/'xml_parser_benchmark',bins/'xml_schema_validation_probe',bins/'xml_conformance_probe']
manifest={'candidate':subprocess.check_output(['git','-C',str(src),'rev-parse','HEAD'],text=True).strip(),'finished_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'artifacts':[{'path':str(p.relative_to(work)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in artifacts]}
(out/'artifact-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('All final macOS SDK, smoke, huge, conformance, network-control, guard and schema probes passed',flush=True)
