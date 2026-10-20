#!/usr/bin/env python3
"""User-requested smaller schedule; preserve frozen measurement code and identity."""
import hashlib
import importlib.util
import json
import random
import time
import traceback
from pathlib import Path

ROOT = Path('/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb')
OUT = ROOT / 'results/gap'
ORIGINAL_SHUFFLE = random.Random.shuffle
LARGE = ['large-matched-plain.mzML', 'large-matched-zlib.mzML', 'large-matched-plain.mzML.gz']
REAL = ['dda-lumos.mzML', 'pasef-published.mzML', 'pasef-im-600-1200s.mzML']
N = [1, 32, 64, 96]


def key(c):
    return json.dumps(c, sort_keys=True)


def base(c):
    return key({k: v for k, v in c.items() if k != 'rep'})


def wanted(c):
    kind = c['kind']
    if kind == 'readers':
        return ((c['input'] in LARGE and c['workers'] in N)
                or (c['input'] in REAL and c['workers'] in [1, 96])
                or (c['input'] == 'large-matched-zlib.mzML.gz' and c['workers'] == 1))
    if kind == 'single-file-openmp':
        return c['omp'] in [1, 96]
    if kind == 'decompress':
        return c['requested_threads'] in ([1] if c['tool'] == 'gzip' else N)
    if kind == 'staged-pipeline':
        return c['requested_threads'] in ([1] if c['tool'] == 'gzip' else [1, 96])
    if kind == 'whole-document':
        return True
    if kind in ['random-access', 'retained-contexts', 'idle']:
        return c['workers'] in N
    raise ValueError(c)


def reduced_shuffle(self, cells):
    existing = []
    for filename in ['records.jsonl', 'access-records.jsonl']:
        p = OUT / filename
        if p.exists():
            existing.extend(json.loads(s) for s in p.read_text().splitlines())
    completed = {key(r['cell']) for r in existing if r['ok']}
    groups = {}
    for c in cells:
        if wanted(c):
            groups.setdefault(base(c), []).append(c)
    selected = []
    for group in groups.values():
        # Select by completion status and original repetition number, never performance.
        group.sort(key=lambda c: (key(c) not in completed, c['rep']))
        selected.extend(group[:3])
    ORIGINAL_SHUFFLE(self, selected)
    cells[:] = selected
    phase = 'primary' if any(c['kind'] == 'readers' for c in cells) else 'access'
    (OUT / f'reduced-{phase}-schedule.json').write_text(json.dumps(cells, indent=2) + '\n')
    print(phase, 'target', len(cells), 'reuse', sum(key(c) in completed for c in cells), flush=True)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == '__main__':
    random.Random.shuffle = reduced_shuffle
    receipt = dict(started_unix=time.time(), reason='Explicit user-requested reduction',
                   scheduler_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   repetitions=3, largest_throughput_files=LARGE, scaling=N,
                   completed_selection='Prefer completed, then original rep number; never timing',
                   excluded_pilot='pilot-before-identity-fix')
    path = OUT / 'reduced-launch.json'
    try:
        g = load('reduced_gap', ROOT / 'run-gap.py')
        receipt['measurement_identity_sha256'] = g.bind_identity()
        path.write_text(json.dumps(receipt, indent=2) + '\n')
        g.run()
        access = load('reduced_access', ROOT / 'run-access.py')
        access.main()
        assert g.bind_identity() == receipt['measurement_identity_sha256']
        receipt.update(status='complete', completed_unix=time.time())
        (OUT / 'ALL_MEASUREMENTS_COMPLETE').touch()
    except BaseException:
        receipt.update(status='failed', completed_unix=time.time(), traceback=traceback.format_exc())
        raise
    finally:
        path.write_text(json.dumps(receipt, indent=2) + '\n')
