#!/usr/bin/env python3
"""Collate only the frozen before/after retention and synchronized indexed cells."""
import argparse,csv,gzip,json,statistics as st
from pathlib import Path
from collections import defaultdict
p=argparse.ArgumentParser();p.add_argument('raw',type=Path);p.add_argument('output',type=Path);p.add_argument('--historical',type=Path);a=p.parse_args()
assert (a.raw/'ALL_COMPLETE').exists()
assert json.loads((a.raw/'launch.json').read_text())['status']=='complete'
f=a.raw/'records.jsonl'
with gzip.open(str(f)+'.gz','rt') if not f.exists() else f.open() as stream:rows=[json.loads(line) for line in stream]
assert len(rows)==264 and all(r['ok'] and r['native_exit_code']==0 for r in rows)
key=lambda c:json.dumps(c,sort_keys=True)
assert len({key(r['cell']) for r in rows})==264 and len({r['identity_sha256'] for r in rows})==1
schedule=json.loads((a.raw/'schedule.json').read_text());assert {key(c) for c in schedule}=={key(r['cell']) for r in rows}
manifest=json.loads((a.raw.parent/'candidate-source-manifest.json').read_text())
groups=defaultdict(list)
for r in rows:groups[key({k:v for k,v in r['cell'].items() if k!='rep'})].append(r)
assert len(groups)==88
a.output.mkdir(parents=True,exist_ok=True)
summary=[]
for k,rr in sorted(groups.items()):
 c=json.loads(k);assert len(rr)==3 and {r['cell']['rep'] for r in rr}=={0,1,2}
 s=dict(c,repetitions=3,evidence_phase='linux-footer-reader-memory',platform='linux',backend='libxml2-full',variant='footer-dom-before' if c['version']=='baseline' else 'footer-reader-after',source_commit=manifest['baseline_archive_product_commit'] if c['version']=='baseline' else manifest['candidate_product_commit'])
 def stats(label,values):s.update({label+'_median':st.median(values),label+'_min':min(values),label+'_max':max(values)})
 for field in ['seconds','process_seconds','synchronized_read_seconds','native_user_seconds','native_system_seconds','sampled_native_threads']:
  stats(field,[r[field] for r in rr])
 stats('peak_rss_mib',[r['native_peak_rss_bytes']/2**20 for r in rr]);stats('resident_rss_mib',[r['resident_rss_bytes']/2**20 for r in rr])
 stats('worker_open_seconds',[st.median(j['open_seconds'] for j in r['jobs']) for r in rr])
 stats('worker_read_seconds',[st.median(j['read_seconds'] for j in r['jobs']) for r in rr])
 s.update(rss_measurement_basis='C++ VmHWM; post-join statm while contexts retained (or post-read residue)',seconds_basis='C++ whole workload including open; synchronized read clock separately excludes open and includes teardown/join',matrix='retained-contexts' if c['mode']=='contexts' else 'synchronized-indexed-read' if c['mode']=='indexed-sync' else 'idle')
 if c['mode']=='indexed-sync':
  q=64 if c['input']=='pasef-im-600-1200s.mzML' else 256
  s.update(queries_per_reader=q,aggregate_queries_per_s=c['workers']*q/s['seconds_median'],synchronized_read_queries_per_s=c['workers']*q/s['synchronized_read_seconds_median'])
 s['rss_mib_median']=s['peak_rss_mib_median'];s['rss_mib_max']=s['peak_rss_mib_max']
 summary.append(s)
idle={(s['version'],s['workers']):s for s in summary if s['mode']=='idle'}
for s in summary:
 if s['mode']=='contexts':s['idle_adjusted_retained_mib_per_reader']=(s['resident_rss_mib_median']-idle[s['version'],s['workers']]['resident_rss_mib_median'])/s['workers']
by={(s['mode'],s['input'],s['workers'],s['version']):s for s in summary}
regressions=[]; comparisons=[]
for (mode,name,n,v),b in by.items():
 if v!='baseline' or mode=='idle':continue
 c=by[mode,name,n,'candidate'];r=dict(mode=mode,input=name,workers=n)
 if mode=='contexts':
  r.update(before_mib_per_reader=b['idle_adjusted_retained_mib_per_reader'],after_mib_per_reader=c['idle_adjusted_retained_mib_per_reader'],reduction_percent=100*(1-c['idle_adjusted_retained_mib_per_reader']/b['idle_adjusted_retained_mib_per_reader']))
 else:
  for metric in ['seconds','synchronized_read_seconds','worker_read_seconds']:
   r[metric+'_speedup']=b[metric+'_median']/c[metric+'_median']
   if c[metric+'_median']>1.05*b[metric+'_median']:regressions.append(dict(input=name,workers=n,metric=metric,before=b[metric+'_median'],after=c[metric+'_median']))
 comparisons.append(r)
def writecsv(path,rr):
 fields=list(dict.fromkeys(k for r in rr for k in r))
 with path.open('w',newline='') as f:
  w=csv.DictWriter(f,fields);w.writeheader();w.writerows(rr)
for name,obj in [('summary.json',summary),('comparisons.json',comparisons),('regression-check.json',regressions)]: (a.output/name).write_text(json.dumps(obj,indent=2)+'\n')
writecsv(a.output/'summary.csv',summary);writecsv(a.output/'comparisons.csv',comparisons)
if a.historical:
 with a.historical.open(newline='') as f:old=list(csv.DictReader(f))
 assert len(old)==3488
 writecsv(a.output/'all-comparisons.csv',old+summary)
meta=dict(workload_records=264,cells=88,repetitions=3,combined_cells=3576 if a.historical else None,regression_flags=len(regressions),speed_gate='>5% median increase requires investigation; not a significance test',historical_cells_preserved=3488)
(a.output/'table-provenance.json').write_text(json.dumps(meta,indent=2)+'\n');print(meta)
