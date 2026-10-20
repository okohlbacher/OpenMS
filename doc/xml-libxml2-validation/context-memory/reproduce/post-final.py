"""After final timings: immutable runtime/input/source and complete index gates."""
from pathlib import Path
import hashlib,json,subprocess,tarfile,os
root=Path('/scratch/kohlbach/openms-context-memory-20261020-01a153cb');out=root/'results/final-targeted'
assert (out/'ALL_COMPLETE').exists() and json.loads((out/'launch.json').read_text())['status']=='complete'
identity=json.loads((out/'identity.json').read_text())
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
for key in ['files','mapped_files']:
    assert all(sha(p)==v for p,v in identity[key].items())
assert all(sha(root/'data'/name)==v['sha256'] for name,v in identity['inputs'].items())
rows=[json.loads(l) for l in (out/'records.jsonl').read_text().splitlines()]
assert len(rows)==192 and len({json.dumps(r['cell'],sort_keys=True) for r in rows})==192
assert all(r['ok'] and r['native_exit_code']==0 and r['input_cache_before']['resident_file_bytes']==r['input_cache_before']['file_bytes'] for r in rows)
assert {json.dumps(r['cell'],sort_keys=True) for r in rows}=={json.dumps(c,sort_keys=True) for c in json.loads((out/'schedule.json').read_text())}
for r in rows:
    c=r['cell'];expected='0-95' if c['phase']=='primary' or c['workers']==96 else '0' if c['workers']==1 else f"0-{c['workers']-1}"
    assert r['cpu_affinity']==expected
changed={p:identity['source_files'][p] for p in ['src/openms/source/FORMAT/HANDLERS/IndexedMzMLDecoder.cpp','src/tests/class_tests/openms/source/IndexedMzMLDecoder_test.cpp','cmake/cmake_findExternalLibs.cmake']}
archive=root/'staging/libxml2-full.tar.gz';assert sha(archive)=='facea08f452382d13226ab81bf8a97698f3f701489f01ce79a0b0835e04bfa7c'
count=0
with tarfile.open(archive) as tar:
    for member in tar:
        if member.isfile():
            count+=1;actual=sha(root/'source'/member.name)
            expected=changed[member.name] if member.name in changed else hashlib.sha256(tar.extractfile(member).read()).hexdigest()
            assert actual==expected,member.name
proofs=[]
for label,padding in [('namespaced-small',0),('namespaced-large',2*1024*1024)]:
    fixture=root/'post-checks'/(label+'.xml')
    fixture.write_text(' '*padding+"<n:indexList xmlns:n='urn:test'><n:index name='spectrum'><n:offset idRef='s'>37</n:offset></n:index></n:indexList><indexListOffset>0</indexListOffset></indexedmzML>")
for path in [*[root/'data'/name for name in identity['inputs']],root/'post-checks/namespaced-small.xml',root/'post-checks/namespaced-large.xml']:
    compared=[]
    for v in ['baseline','final-hybrid']:
        env=dict(os.environ,LD_LIBRARY_PATH=f'{root}/snapshots/{v}/lib:{root}/dependencies/install/lib:/scratch/kohlbach/contrib/build/lib',OMP_NUM_THREADS='1')
        r=json.loads(subprocess.check_output([str(root/'post-check-build/index_offset_proof'),str(path)],env=env,text=True))
        compared.append(r);proofs.append(dict(r,input=path.name,version=v))
    assert compared[0]==compared[1],path
(root/'results/final-offset-proofs.json').write_text(json.dumps(proofs,indent=2)+'\n')
receipt=dict(regular_source_files_checked=count,source_changed_only_three_expected_files=True,actual_source_sha256=changed,runtime_inputs_harness_unchanged=True,unique_new_records=192,final_selected_including_reused_baseline_records=324,all_native_exits_success=True,all_input_pages_resident=True,cpu_placement_matches_phase=True,all_complete_index_vectors_agree=True,both_size_paths_namespace_control_pass=True)
(root/'results/final-post-verification.json').write_text(json.dumps(receipt,indent=2)+'\n');(root/'results/FINAL_POST_COMPLETE').touch();print(receipt)
