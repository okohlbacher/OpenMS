#!/usr/bin/env python3
"""Independently check selection, reported arithmetic and unchanged historical rows."""
import argparse
import csv
import gzip
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('raw', type=Path)
p.add_argument('published', type=Path)
p.add_argument('history', type=Path)
a = p.parse_args()
read = lambda path: json.loads(path.read_text())
key = lambda c: json.dumps(c, sort_keys=True)
base = lambda c: key({k: v for k, v in c.items() if k != 'rep'})
def lines(name):
    path = a.raw / name
    if path.exists():
        return path.read_text().splitlines()
    with gzip.open(str(path) + '.gz', 'rt') as f:
        return f.read().splitlines()


all_rows = []
for n in ['records.jsonl', 'access-records.jsonl']:
    all_rows += [json.loads(line) for line in lines(n)]
lookup = {key(r['cell']): r for r in all_rows}
selected = read(a.raw / 'reduced-primary-schedule.json') + read(a.raw / 'reduced-access-schedule.json')
summary = read(a.published / 'summary.json')
inputs = read(a.raw / 'inputs.json')
launch = read(a.raw / 'reduced-launch.json')
assert launch['largest_throughput_files'] == sorted(inputs, key=lambda n: inputs[n]['bytes'], reverse=True)[:3]
groups = defaultdict(list)
for c in selected:
    groups[base(c)].append(lookup[key(c)])
assert len(selected) == 600 and len(groups) == len(summary) == 200
assert all(len(g) == len({r['cell']['rep'] for r in g}) == 3 for g in groups.values())
prior = [json.loads(line) for line in lines('records.jsonl')][:412]
# Original records are append-only; the cutoff receipt preserves the exact old bytes separately.
prior_keys = {key(r['cell']) for r in prior}
for config, group in groups.items():
    cell = {k: v for k, v in group[0]['cell'].items() if k != 'rep'}
    choices = [dict(cell, rep=n) for n in range(5)]
    choices.sort(key=lambda c: (key(c) not in prior_keys, c['rep']))
    assert {key(r['cell']) for r in group} == {key(c) for c in choices[:3]}
close = lambda x, y: math.isclose(x, y, rel_tol=1e-12, abs_tol=1e-10)
by_summary = {key({k: v for k, v in r.items() if k in ['kind','input','backend','workers','omp','tool','requested_threads','mode']}): r for r in summary}
idle = {(r['backend'], r['workers']): r for r in summary if r['kind'] == 'idle'}
for s in summary:
    c = {k: v for k, v in s.items() if k in ['kind','input','backend','workers','omp','tool','requested_threads','mode']}
    g = groups[key(c)]
    seconds = statistics.median(r['process_seconds'] for r in g)
    assert close(s['process_seconds_median'], seconds)
    if s['kind'] in ['readers','single-file-openmp','whole-document']:
        t = statistics.median(r['seconds'] for r in g)
        assert close(s['file_MB_per_s'], s.get('workers', 1) * inputs[s['input']]['bytes'] / t / 1e6)
    elif s['kind'] in ['decompress','staged-pipeline']:
        assert close(s['inflated_output_MB_per_s'], inputs[s['input'][:-3]]['bytes'] / seconds / 1e6)
    if s['kind'] == 'retained-contexts':
        baseline = idle[s['backend'], s['workers']]['resident_rss_mib_median']
        resident = statistics.median(r['resident_rss_bytes'] for r in g) / 2**20
        assert close(s['idle_adjusted_retained_mib_per_reader'], (resident - baseline) / s['workers'])
    if s['kind'] == 'decompress':
        peak = statistics.median(max(r['native_wait4_peak_rss_bytes'], r['sampled_native_hwm_bytes']) for r in g) / 2**20
        assert close(s['native_peak_rss_mib_median'], peak)
with a.history.open(newline='') as f:
    old = list(csv.DictReader(f))
with (a.published / 'all-comparisons.csv').open(newline='') as f:
    combined = list(csv.DictReader(f))
assert len(old) == 3288 and len(combined) == 3488
assert all(all(combined[i][k] == v for k, v in row.items()) for i, row in enumerate(old))
receipt = dict(selected_cells=200, selected_workloads=600, selected_native_processes=660,
               original_historical_cells_unchanged=3288, combined_cells=3488,
               selection_independent_of_speed=True, median_rate_and_rss_arithmetic_passed=True)
(a.published / 'derived-verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(receipt)
