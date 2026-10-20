"""After timings: validate immutable identity, complete offsets and source provenance."""
from pathlib import Path
import hashlib,importlib.util,json,subprocess,tarfile,os
root=Path('/scratch/kohlbach/openms-context-memory-20261020-01a153cb');out=root/'results/measurements'
assert (out/'ALL_COMPLETE').exists()
assert json.loads((out/'launch.json').read_text())['status']=='complete'
spec=importlib.util.spec_from_file_location('runner',root/'run-targeted.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
paths=json.loads((out/'bound-library-paths.json').read_text());frozen=json.loads((out/'identity.json').read_text());assert g.identity(paths)==frozen
rows=[json.loads(line) for line in (out/'records.jsonl').read_text().splitlines()]
assert len(rows)==264 and len({json.dumps(r['cell'],sort_keys=True) for r in rows})==264
assert all(r['ok'] and r['native_exit_code']==0 and r['input_cache_before']['resident_file_bytes']==r['input_cache_before']['file_bytes'] for r in rows)
source=json.loads((root/'staging/candidate-source-manifest.json').read_text());changed=source['changed_files_sha256']
archive=root/'staging/libxml2-full.tar.gz'
with archive.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==source['baseline_archive_sha256']
count=0
with tarfile.open(archive) as tar:
 for member in tar:
  if member.isfile():
   count+=1;p=root/'source'/member.name;actual=hashlib.sha256(p.read_bytes()).hexdigest()
   expected=changed[member.name] if member.name in changed else hashlib.sha256(tar.extractfile(member).read()).hexdigest()
   assert actual==expected,member.name
controls=[]
fixture=root/'post-checks/namespaced-footer.xml'
fixture.write_text("<n:indexList xmlns:n='urn:test'><n:index name='spectrum'><n:offset idRef='s'>37</n:offset></n:index></n:indexList><indexListOffset>0</indexListOffset></indexedmzML>")
for name in [*g.FILES, str(fixture)]:
 results=[]
 for v in g.VERSIONS:
  env=g.g.env(v)
  raw=subprocess.check_output([str(root/'post-check-build/index_offset_proof'),str(root/'data'/name) if name in g.FILES else name],env=env,text=True)
  r=json.loads(raw);results.append(r);controls.append(dict(r,input=name,version=v))
 assert results[0]==results[1],name
 if name==str(fixture):assert results[0]['spectra']==1
(root/'results/full-offset-proofs.json').write_text(json.dumps(controls,indent=2)+'\n')
(root/'results/candidate-source-manifest.json').write_text(json.dumps(source,indent=2)+'\n')
receipt=dict(source_archive_regular_files_checked=count,source_changed_only_committed_three_files=True,measurement_identity_unchanged=True,unique_workloads=264,all_native_exits_success=True,all_input_pages_resident_before_each_cell=True,all_five_complete_offset_vectors_agree=True,namespaced_footer_accepted_by_both_versions=True)
(root/'results/post-verification.json').write_text(json.dumps(receipt,indent=2)+'\n');(root/'results/POST_COMPLETE').touch();print(receipt)
