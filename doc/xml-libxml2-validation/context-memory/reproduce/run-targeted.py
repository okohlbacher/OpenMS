#!/usr/bin/env python3
"""Only retained contexts, synchronized random reads, and same-N idle controls."""
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import threading
import time
import traceback

ROOT = Path('/scratch/kohlbach/openms-context-memory-20261020-01a153cb')
OUT = ROOT / 'results/measurements'
OUT.mkdir(exist_ok=True)
spec = importlib.util.spec_from_file_location('meter', ROOT / 'meter.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
FILES = ['large-matched-plain.mzML','large-matched-zlib.mzML','dda-lumos.mzML','pasef-published.mzML','pasef-im-600-1200s.mzML']
VERSIONS = ['baseline','candidate']
N = [1,32,64,96]


def key(c):
    return json.dumps(c, sort_keys=True)


def call(c):
    q = 64 if c['input'] == FILES[-1] else 256
    return g.require(g.measure([g.LAUNCHER,g.BINARY,c['mode'],ROOT/'data'/c['input'],c['workers'],q],g.env(c['version'])))


def identity(paths):
    files = [ROOT/'run-targeted.py', ROOT/'meter.py', ROOT/'native-meter', g.BINARY, g.LAUNCHER]
    files += list((ROOT/'staging/benchmark-source').glob('*.cpp')) + [ROOT/'staging/benchmark-source/CMakeLists.txt']
    files += [Path(p) for p in paths]
    files += list((ROOT/'staging/candidate').rglob('*.cpp')) + [ROOT/'staging/candidate/cmake/cmake_findExternalLibs.cmake',ROOT/'staging/candidate-source-manifest.json',ROOT/'staging/protocol.json']
    return dict(files={str(p):g.sha(p) for p in sorted(set(files))},inputs={n:dict(bytes=(ROOT/'data'/n).stat().st_size,sha256=g.sha(ROOT/'data'/n)) for n in FILES},environments={v:g.env(v) for v in VERSIONS},affinity='0-95',driver_affinity='96-127')


def main():
    assert (ROOT/'results/PREPARATION_COMPLETE').exists()
    assert (ROOT/'results/REVIEWED_BUILD_COMPLETE').exists()
    assert (ROOT/'staging/candidate-source-manifest.json').exists()
    os.sched_setaffinity(0,set(range(96,128)))
    prior = json.loads((ROOT/'staging/previous-indexed-correctness.json').read_text())
    expected = {r['input']:g.fingerprint(r) for r in prior}
    counts = {r['input']:(r['index_spectra'],r['index_chromatograms']) for r in prior}
    controls = []
    mapped = set()
    for name in FILES:
        for v in VERSIONS:
            c=dict(input=name,version=v,mode='indexed-sync',workers=1,rep=-1)
            r=call(c);g.validate_backend(r,v)
            assert g.fingerprint(r)==expected[name],(name,v)
            assert r['synchronized_read_seconds']>0
            mapped.update(r['loaded_library_maps'])
            controls.append(dict(r,cell=c))
    # Failures before the read barrier must release every waiter instead of hanging.
    for v in VERSIONS:
        r=g.measure([g.LAUNCHER,g.BINARY,'indexed-sync',ROOT/'data/absent.mzML',4,1],g.env(v),timeout=15)
        assert not r['ok'] and not r['timed_out'] and r['native_exit_code']!=0,r
        controls.append(dict(r,expected_negative='missing input releases barrier',version=v))
    (OUT/'correctness.json').write_text(json.dumps(controls,indent=2)+'\n')
    paths=sorted(mapped);(OUT/'bound-library-paths.json').write_text(json.dumps(paths,indent=2)+'\n')
    frozen=identity(paths);identity_sha=hashlib.sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest()
    (OUT/'identity.json').write_text(json.dumps(frozen,indent=2)+'\n')
    cells=[]
    for rep in range(3):
        for v in VERSIONS:
            for n in N:
                for name in FILES:
                    for mode in ['contexts','indexed-sync']:
                        cells.append(dict(version=v,workers=n,input=name,mode=mode,rep=rep))
                cells.append(dict(version=v,workers=n,input=FILES[0],mode='idle',rep=rep))
    random.Random(20261022).shuffle(cells)
    assert len(cells)==264
    (OUT/'schedule.json').write_text(json.dumps(cells,indent=2)+'\n')
    done=set();path=OUT/'records.jsonl'
    if path.exists():
        for line in path.read_text().splitlines():
            r=json.loads(line);assert r['identity_sha256']==identity_sha and r['ok'];done.add(key(r['cell']))
    stop=threading.Event();monitor=threading.Thread(target=g.monitor,args=(stop,),daemon=True);monitor.start()
    try:
        with path.open('a',buffering=1) as f:
            for i,c in enumerate(cells):
                if key(c) in done:continue
                with g.cell_attempt(c):
                    cache=g.cached_input(ROOT/'data'/c['input'])
                    r=call(c);g.validate_backend(r,c['version'])
                    assert all(str(Path(p).resolve()) in {str(Path(p).resolve()) for p in paths} for p in r['loaded_library_maps'])
                    if c['mode']=='indexed-sync':assert g.fingerprint(r)==expected[c['input']],c
                    if c['mode']=='contexts':assert (r['index_spectra'],r['index_chromatograms'])==counts[c['input']],c
                    assert r['requested_openmp_threads']==1
                    r.update(cell=c,input_cache_before=cache,identity_sha256=identity_sha,completed_unix=time.time())
                    f.write(json.dumps(r,sort_keys=True)+'\n');os.fsync(f.fileno())
                    print(f'{i+1}/264 {c} {r["seconds"]:.3f}s',flush=True)
    finally:
        stop.set();monitor.join()
    assert frozen==identity(paths),'Source/input/runtime identity changed'
    assert len([json.loads(line) for line in path.read_text().splitlines()])==264
    (OUT/'ALL_COMPLETE').touch()


if __name__=='__main__':
    receipt=dict(started_unix=time.time())
    try:
        main();receipt.update(status='complete')
    except BaseException:
        receipt.update(status='failed',traceback=traceback.format_exc());raise
    finally:
        receipt['completed_unix']=time.time();(OUT/'launch.json').write_text(json.dumps(receipt,indent=2)+'\n')
