"""Keep every iteration separate; final plots pair reused baseline with hybrid."""
from pathlib import Path
import csv,json,statistics as st,gzip
from collections import defaultdict
import argparse
p=argparse.ArgumentParser();p.add_argument('raw',type=Path);p.add_argument('out',type=Path);p.add_argument('historical',type=Path);p.add_argument('source_commit');a=p.parse_args();a.out.mkdir(exist_ok=True,parents=True)
def read(path):
    text=path.read_text() if path.exists() else gzip.decompress(Path(str(path)+'.gz').read_bytes()).decode()
    return [json.loads(l) for l in text.splitlines()]
primary=read(a.raw/'measurements/records.jsonl');final=read(a.raw/'final-targeted/records.jsonl');confirm=read(a.raw/'confirmation/records.jsonl')
assert len(primary)==264 and len(final)==192 and len(confirm)==54
supplement=read(a.raw/'final-supplement/records.jsonl');assert len(supplement)==30 and all(r['ok'] and r['native_exit_code']==0 for r in supplement)
assert (a.raw/'final-supplement/ALL_COMPLETE').exists()
for rr in [primary,final,confirm]:assert all(r['ok'] and r['native_exit_code']==0 for r in rr)
assert (a.raw/'final-targeted/ALL_COMPLETE').exists()
assert json.loads((a.raw/'final-targeted/launch.json').read_text())['status']=='complete'

def summarize(rows,phase,candidate_commit,acceptance):
    groups=defaultdict(list)
    for r in rows:
        c=r['cell'];name=c.get('input','pasef-im-600-1200s.mzML');n=c['workers'];mode=c.get('mode',r['mode']);v=c.get('version','candidate');q=c.get('queries',2048 if 'im-' in name else 8192 if 'sustained' in phase or 'confirmation' in phase else 256)
        if 'original-primary' in phase:q=64 if 'im-' in name else 256
        groups[(name,n,mode,v,q)].append(r)
    result=[]
    for (name,n,mode,v,q),rs in sorted(groups.items()):
        assert len(rs)==3 and {r['cell']['rep'] for r in rs}=={0,1,2}
        s=dict(platform='linux',backend='libxml2-full',evidence_phase=phase,variant='footer-dom-before' if v=='baseline' else phase,source_commit='8f66b3d921c9512e1e5968f494c77715ff71c696' if v=='baseline' else candidate_commit,input=name,workers=n,mode=mode,version=v,repetitions=3,acceptance=acceptance,queries_per_reader=q if mode=='indexed-sync' else 0,matrix='retained-contexts' if mode=='contexts' else 'synchronized-indexed-read' if mode=='indexed-sync' else 'idle')
        def stats(k,values):s.update({k+'_median':st.median(values),k+'_min':min(values),k+'_max':max(values)})
        for field in ['seconds','synchronized_read_seconds','process_seconds','native_user_seconds','native_system_seconds','native_minflt','sampled_native_threads']:stats(field,[r[field] for r in rs])
        stats('peak_rss_mib',[r['native_peak_rss_bytes']/2**20 for r in rs]);stats('resident_rss_mib',[r['resident_rss_bytes']/2**20 for r in rs])
        for field in ['open_seconds','read_seconds']:stats('worker_'+field,[st.median(j[field] for j in r['jobs']) for r in rs])
        s.update(rss_mib_median=s['peak_rss_mib_median'],rss_mib_max=s['peak_rss_mib_max'],rss_measurement_basis='native C++ VmHWM peak; statm after join; contexts kept alive only in contexts mode',seconds_basis='whole workload; separate worker loop excludes open/barrier/close; global sync excludes open but includes close/join')
        if mode=='indexed-sync':s.update(aggregate_queries_per_s=n*q/s['seconds_median'],synchronized_read_queries_per_s=n*q/s['synchronized_read_seconds_median'],worker_loop_queries_per_s=n*q/s['worker_read_seconds_median'])
        result.append(s)
    idle={(s['version'],s['workers']):s['resident_rss_mib_median'] for s in result if s['mode']=='idle'}
    for s in result:
        if s['mode']=='contexts':s['idle_adjusted_retained_mib_per_reader']=(s['resident_rss_mib_median']-idle[s['version'],s['workers']])/s['workers']
    return result
original=summarize(primary,'context-original-primary','c41fd17602ed3196c5bb235e7dcd8e6c625a91a0','baseline reusable; all-reader candidate rejected for IM speed')
for row in original:
    row['acceptance']='final reused immutable baseline' if row['version']=='baseline' else 'rejected: sustained IM read regression'
new=summarize([r for r in final if r['cell']['phase']=='primary'],'context-final-hybrid-primary',a.source_commit,'final selected candidate')
base=[dict(s,acceptance='final reused immutable baseline') for s in original if s['version']=='baseline']
selected=base+new;assert len(selected)==88
sustained=summarize([r for r in final if r['cell']['phase']=='sustained'],'context-final-hybrid-sustained',a.source_commit,'final paired sustained checks')
confirmation=summarize(confirm,'context-all-reader-confirmation','c41fd17602ed3196c5bb235e7dcd8e6c625a91a0','rejected all-reader candidate; preserve all repetitions')
extras=[]
for fn,phase,source in [('buffer-speed/records.jsonl','context-rejected-buffer-copy','uncommitted experiment; source patch retained'),('packed-speed/records.jsonl','context-rejected-packed-ids','uncommitted experiment; exact source retained')]:
    extras+=summarize(read(a.raw/fn),phase,source,'excluded diagnostic iteration')
by={(s['mode'],s['input'],s['workers'],s['version']):s for s in selected};comparisons=[]
for (mode,name,n,v),b in sorted(by.items()):
    if v!='baseline' or mode=='idle':continue
    c=by[mode,name,n,'candidate'];r=dict(mode=mode,input=name,workers=n)
    if mode=='contexts':r.update(before_mib_per_reader=b['idle_adjusted_retained_mib_per_reader'],after_mib_per_reader=c['idle_adjusted_retained_mib_per_reader'],reduction_percent=100*(1-c['idle_adjusted_retained_mib_per_reader']/b['idle_adjusted_retained_mib_per_reader']))
    else:
        for field in ['seconds','synchronized_read_seconds','worker_read_seconds']:r[field+'_speedup']=b[field+'_median']/c[field+'_median']
    comparisons.append(r)
for row in sustained:row['cpu_placement']='0..N-1'
supp=summarize(supplement,'context-final-primary-affinity-sustained',a.source_commit,'final matched primary-affinity flag confirmation')
for row in supp:row['cpu_placement']='0..95'
paired={(s['input'],s['workers'],s['version'],s['cpu_placement']):s for s in sustained+supp};long=[]
for (name,n,v,placement),b in sorted(paired.items()):
    if v!='baseline':continue
    c=paired[name,n,'candidate',placement];r=dict(input=name,workers=n,cpu_placement=placement)
    for field in ['seconds','synchronized_read_seconds','worker_read_seconds']:r[field+'_speedup']=b[field+'_median']/c[field+'_median']
    long.append(r)
def csvout(name,rr):
    fields=list(dict.fromkeys(k for r in rr for k in r))
    with (a.out/name).open('w',newline='') as f:w=csv.DictWriter(f,fields);w.writeheader();w.writerows(rr)
with a.historical.open(newline='') as f:historical=list(csv.DictReader(f))
assert len(historical)==3488
allrows=historical+original+new+sustained+supp+confirmation+extras
assert len(allrows)==3674
for name,data in [('summary',selected),('comparisons',comparisons),('sustained-summary',sustained+supp),('sustained-comparisons',long)]:
    (a.out/(name+'.json')).write_text(json.dumps(data,indent=2)+'\n');csvout(name+'.csv',data)
csvout('all-comparisons.csv',allrows)
(a.out/'table-provenance.json').write_text(json.dumps(dict(historical_cells_unchanged=3488,original_primary_cells=len(original),final_new_primary_cells=len(new),final_sustained_cells=len(sustained)+len(supp),rejected_confirmation_cells=len(confirmation),rejected_buffer_packed_cells=len(extras),combined_cells=len(allrows),final_selected_workload_records=354,final_new_workload_records=222,baseline_reused_workload_records=132),indent=2)+'\n')
print(json.dumps(long,indent=2));print(json.dumps([r for r in comparisons if r['mode']=='contexts' and r['workers']==96],indent=2))
