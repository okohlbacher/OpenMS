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
result=run(['python3',source/'tools/xml-poc/check_schemas.py','--library',root/'dependencies/install/lib/libxml2.so','--root',source])
(out/'schema-results.json').write_text(result.stdout);(out/'schema-diagnostics.txt').write_text(result.stderr)
current=json.loads(result.stdout)
archived=json.loads((root/'staging/original-schema-results.json').read_text())
key=lambda d:{(r['file'],r['schema']):r['status'] for r in d['validation']}
assert key(current)==key(archived),'Native195-case schema outcomes changed'
assert current['summary']['schema_count']==22 and current['summary']['instance_count']==195
(out/'schema-comparison.json').write_text(json.dumps({'cases':195,'schemas':22,'all_libxml_statuses_match_archived_original':True,'archived_original_sha256':hashlib.sha256((root/'staging/original-schema-results.json').read_bytes()).hexdigest(),'method':'Current native libxml2 only; compare frozen archived outcomes without building/linking Xerces'},indent=2)+'\n')
api=[]
for case,xml,xsd,expected in [('huge-array',root/'data/huge-array.mzML',source/'share/OpenMS/SCHEMAS/mzML_idx_1_10.xsd',True),('anyuri-windows',source/'tools/xml-poc/fixtures/anyuri-windows.xml',source/'tools/xml-poc/fixtures/anyuri.xsd',False),('anyuri-normalized',source/'tools/xml-poc/fixtures/anyuri-normalized.xml',source/'tools/xml-poc/fixtures/anyuri.xsd',True)]:
 result=subprocess.run([str(binary/'xml_schema_validation_probe'),str(xml),str(xsd)],capture_output=True,text=True)
 value=json_output(result);assert value['valid']==expected and result.returncode==int(not expected),(case,result)
 api.append(dict(case=case,backend='libxml2',returncode=result.returncode,stderr=result.stderr,**value))
(out/'schema-api-results.json').write_text(json.dumps(api,indent=2)+'\n')
cases={'entity-valid':b'<r>A&amp;B</r>','undefined-entity':b'<r>&undefined;</r>','malformed-reference':b'<r>A&-B</r>','duplicate-attribute':b'<r a="1" a="2"/>','invalid-utf8':b'<r>\xff</r>','overlong-utf8':b'<r>\xc0\xaf</r>','truncated-utf8':b'<r>\xe2\x82</r>','latin1':b'<?xml version="1.0" encoding="ISO-8859-1"?><r>\xe9</r>','windows1252':b'<?xml version="1.0" encoding="windows-1252"?><r>\x80</r>','unicode':'<r>β🧬</r>'.encode(),'mismatched-tag':b'<r>\n<x></r>'}
text={'entity-valid':'A&B','latin1':'é','windows1252':'€','unicode':'β🧬'}
fixtures=root/'data/conformance';fixtures.mkdir(exist_ok=True)
rows=[]
for name,payload in cases.items():
 fixture=fixtures/(name+'.xml');fixture.write_bytes(payload)
 for repeat in range(4):
  result=run([binary/'xml_conformance_probe',fixture]);value=json_output(result)
  expected=name in text;assert value['accepted']==expected,(name,value)
  if expected:
   utf16=text[name].encode('utf-16le');assert value['utf16_code_units']==list(struct.unpack('<'+'H'*(len(utf16)//2),utf16)),(name,value)
  rows.append(dict(backend='libxml2',case=name,repetition=repeat,stderr=result.stderr,**value))
(out/'conformance-results.json').write_text(json.dumps({'method':'Eleven generic XML cases, four isolated native-libxml2 process repetitions each','results':rows},indent=2)+'\n')
print('Supplemental: shared smoke, huge equivalence,22schemas/195unchanged statuses,3actual API cases,44native conformance checks passed')
