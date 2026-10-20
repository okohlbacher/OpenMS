"""Final candidate only for primary cells; paired long checks for resolved flags.
Never pool rejected candidates. Reuse the immutable original primary baseline.
"""
from pathlib import Path
import hashlib,importlib.util,json,os,random,threading,time,traceback
ROOT=Path('/scratch/kohlbach/openms-context-memory-20261020-01a153cb')
OUT=ROOT/'results/final-targeted';OUT.mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('primary',ROOT/'run-targeted.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);g=m.g;g.OUT=OUT
FILES=m.FILES
SOURCE=['src/openms/source/FORMAT/HANDLERS/IndexedMzMLDecoder.cpp','src/tests/class_tests/openms/source/IndexedMzMLDecoder_test.cpp','cmake/cmake_findExternalLibs.cmake','src/openms/source/FORMAT/HANDLERS/IndexedMzMLHandler.cpp','src/tests/class_tests/openms/source/IndexedMzMLFile_test.cpp']

def call(c,queries):
    n=c['workers'];name=c['input'];version=c['version'];snapshot='final-hybrid' if version=='candidate' else 'baseline'
    mask='0-95' if c.get('phase')=='primary' else f'0-{n-1}' if n>1 else '0'
    row=g.measure([g.LAUNCHER,'/usr/bin/taskset','-c',mask,g.BINARY,c['mode'],ROOT/'data'/name,n,queries],g.env(snapshot))
    assert row['ok'] and row['native_exit_code']==0 and len(row['jobs'])==n
    assert str(ROOT/'snapshots'/snapshot/'lib') in row['openms_library']
    assert not any('xerces' in p.lower() for p in row['loaded_library_maps'])
    return row

def main():
    assert (ROOT/'results/HYBRID_BUILD_COMPLETE').exists()
    os.sched_setaffinity(0,set(range(96,128)))
    previous=[json.loads(l) for l in (ROOT/'results/measurements/records.jsonl').read_text().splitlines()]
    refs={name:g.fingerprint(next(r for r in previous if r['cell']['input']==name and r['mode']=='indexed-sync')) for name in FILES}
    controls=[];mapped=set()
    for name in FILES:
        r=call(dict(input=name,version='candidate',workers=1,mode='indexed-sync'),64 if name==FILES[-1] else 256)
        assert g.fingerprint(r)==refs[name];mapped.update(r['loaded_library_maps']);controls.append(r)
    longcases=json.loads((ROOT/'staging/confirmation-protocol.json').read_text())['cases']
    longcases.append(dict(input=FILES[-1],workers=1))
    assert len(longcases)==10
    longrefs={}
    for name in FILES:
        for v in ['baseline','candidate']:
            r=call(dict(input=name,version=v,workers=1,mode='indexed-sync'),2048 if name==FILES[-1] else 8192)
            fingerprint=g.fingerprint(r)
            if name in longrefs:assert fingerprint==longrefs[name]
            longrefs[name]=fingerprint;mapped.update(r['loaded_library_maps']);controls.append(r)
    (OUT/'controls.json').write_text(json.dumps(controls,indent=2)+'\n')
    immutable=[ROOT/'source'/p for p in SOURCE]+[Path(__file__),ROOT/'post-checks/selected-final-protocol.json',ROOT/'benchmark-build/xml_parser_benchmark',ROOT/'benchmark-build/xml_benchmark_launcher',ROOT/'native-meter',ROOT/'meter.py',ROOT/'run-targeted.py',ROOT/'staging/benchmark-source/benchmark.cpp',ROOT/'staging/benchmark-source/CMakeLists.txt']
    identity=dict(source_files={str(p.relative_to(ROOT/'source')):g.sha(p) for p in [ROOT/'source'/p for p in SOURCE]},files={str(p):g.sha(p) for p in immutable},mapped_files={p:g.sha(Path(p)) for p in sorted(mapped)},inputs={name:dict(bytes=(ROOT/'data'/name).stat().st_size,sha256=g.sha(ROOT/'data'/name)) for name in FILES},reused_baseline_identity=json.loads((ROOT/'results/measurements/identity.json').read_text()),policy=json.loads((ROOT/'post-checks/selected-final-protocol.json').read_text()))
    identity_sha=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest();(OUT/'identity.json').write_text(json.dumps(identity,indent=2)+'\n')
    cells=[dict(r['cell'],phase='primary',queries=64 if r['cell']['input']==FILES[-1] else 256) for r in previous if r['cell']['version']=='candidate']
    assert len(cells)==132
    cells += [dict(c,mode='indexed-sync',version=v,rep=rep,phase='sustained',queries=2048 if c['input']==FILES[-1] else 8192) for c in longcases for v in ['baseline','candidate'] for rep in range(3)]
    assert len(cells)==192
    random.Random(20261025).shuffle(cells);(OUT/'schedule.json').write_text(json.dumps(cells,indent=2)+'\n')
    stop=threading.Event();monitor=threading.Thread(target=g.monitor,args=(stop,),daemon=True);monitor.start()
    try:
        with (OUT/'records.jsonl').open('w',buffering=1) as f:
            for i,c in enumerate(cells):
                cache=g.cached_input(ROOT/'data'/c['input']);r=call(c,c['queries'])
                if c['mode']=='indexed-sync':assert g.fingerprint(r)==(refs if c['phase']=='primary' else longrefs)[c['input']]
                assert all(p in mapped for p in r['loaded_library_maps'])
                r.update(cell=c,input_cache_before=cache,identity_sha256=identity_sha,completed_unix=time.time());f.write(json.dumps(r,sort_keys=True)+'\n');os.fsync(f.fileno());print(i+1,'/192',c,flush=True)
    finally:stop.set();monitor.join()
    assert all(g.sha(Path(p))==h for p,h in identity['files'].items())
    assert all(g.sha(Path(p))==h for p,h in identity['mapped_files'].items())
    assert all(g.sha(ROOT/'data'/name)==v['sha256'] for name,v in identity['inputs'].items())
    assert m.identity(json.loads((ROOT/'results/measurements/bound-library-paths.json').read_text()))==identity['reused_baseline_identity']
    (OUT/'ALL_COMPLETE').touch()

if __name__=='__main__':
    receipt=dict(started_unix=time.time())
    try:main();receipt['status']='complete'
    except BaseException:receipt.update(status='failed',traceback=traceback.format_exc());raise
    finally:receipt['completed_unix']=time.time();(OUT/'launch.json').write_text(json.dumps(receipt,indent=2)+'\n')
