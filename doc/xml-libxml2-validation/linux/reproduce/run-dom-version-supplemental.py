import hashlib,json,os,struct,subprocess
from pathlib import Path
root=Path('/scratch/kohlbach/openms-libxml2-replacement-20261020-01a153cb')
source=root/'source'; out=root/'results'; binary=root/'benchmark-build'

def run(args):
 result=subprocess.run([str(a) for a in args],capture_output=True,text=True)
 if result.returncode: raise RuntimeError((args,result.returncode,result.stdout,result.stderr))
 return result

def json_output(result):
 return json.loads(next(s for s in result.stdout.splitlines() if s.startswith('{')))

huge=json_output(run([binary/'xml_benchmark_launcher',binary/'xml_parser_benchmark','verify',root/'data/huge-array.mzML','1','2048']))
assert huge=={'verified':True,'spectra':1,'points':1048577,'hash':'16141847955750882229'},huge
(out/'huge-array-equivalence.json').write_text(json.dumps(huge,indent=2)+'\n')
api=[]
for case,xml,xsd,expected in [('huge-array',root/'data/huge-array.mzML',source/'share/OpenMS/SCHEMAS/mzML_idx_1_10.xsd',True),('anyuri-windows',source/'tools/xml-poc/fixtures/anyuri-windows.xml',source/'tools/xml-poc/fixtures/anyuri.xsd',False),('anyuri-normalized',source/'tools/xml-poc/fixtures/anyuri-normalized.xml',source/'tools/xml-poc/fixtures/anyuri.xsd',True)]:
 result=subprocess.run([str(binary/'xml_schema_validation_probe'),str(xml),str(xsd)],capture_output=True,text=True)
 value=json_output(result);assert value['valid']==expected and result.returncode==int(not expected),(case,result)
 api.append(dict(case=case,backend='libxml2',returncode=result.returncode,stderr=result.stderr,**value))
(out/'schema-api-results.json').write_text(json.dumps(api,indent=2)+'\n')
previous=out/'candidate-fcdc7458'
inherited={name:{'source_cpp_build_commit':'fcdc7458543e8936a0f8915828860669c7044514','sha256':hashlib.sha256((previous/name).read_bytes()).hexdigest(),'relative_path':str(Path('candidate-fcdc7458')/name)} for name in ('schema-results.json','schema-comparison.json','conformance-results.json')}
(out/'unchanged-validation-evidence.json').write_text(json.dumps({'method':'Prior fcdc 22/195 schema and44genericconformance outcomes retained; only MzIdentML reader empty engine-version fallback changed; XMLFile, schema validator, schemas andgenericconformance code unchanged. No new corpus/conformance run claimed.','inherited':inherited},indent=2)+'\n')
print('Final DOM-version supplemental:3sharedsmoke,hugeequivalence,3actualschemaAPIcases; unchangedschema/conformanceevidence referenced to priorfcdc run')
