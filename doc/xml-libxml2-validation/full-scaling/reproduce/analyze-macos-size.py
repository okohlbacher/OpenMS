from pathlib import Path
from collections import defaultdict
import json,statistics,csv,hashlib
root=Path(__file__).resolve().parents[3];out=root/'results/full-scaling/macos';x=json.loads((out/'size-control.json').read_text());assert len(x['records'])==60 and not x['failures'];groups=defaultdict(list);digests={};flags=[]
for r in x['records']:
 e='UTF-8' if Path(r['input']).name=='large-utf8.mzML' else 'ISO-8859-1';groups[r['backend'],e,r['mode']].append(r)
 fingerprint=tuple(r[k] for k in ['hash_per_worker','spectra_per_worker','chromatograms_per_worker','points_per_worker','index_spectra','index_chromatograms']);key=r['mode'];assert key not in digests or digests[key]==fingerprint;digests[key]=fingerprint
 if r['seconds']>r['process_seconds']+.1 or r['user_seconds']+r['system_seconds']>r['process_seconds']*1.1+.1:flags.append({'backend':r['backend'],'encoding':e,'mode':r['mode'],'repetition':r['repetition']})
for b,files in x['libraries'].items():
 for p,h in files.items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,p
rows=[]
for (b,e,m),rr in sorted(groups.items()):
 assert len(rr)==5;times=[r['seconds'] if m=='stream' else r['jobs'][0]['open_seconds'] for r in rr]
 rows.append({'backend':b,'encoding':e,'mode':m,'repetitions':5,'seconds_median':statistics.median(times),'seconds_min':min(times),'seconds_max':max(times),'rss_mib_median':statistics.median(r['max_rss_bytes']/2**20 for r in rr),'whole_workload_seconds_median':statistics.median(r['seconds'] for r in rr),'user_seconds_median':statistics.median(r['user_seconds'] for r in rr),'system_seconds_median':statistics.median(r['system_seconds'] for r in rr)})
summary={'results':rows,'records':60,'all_fingerprints_match':True,'all_library_hashes_unchanged':True,'clock_flags':flags,'source':'8f66b3d921c9512e1e5968f494c77715ff71c696','experimental_handler':'ignored binary payloads only; general non-ASCII fallback preserved','method':'five randomized fresh processes per backend/encoding/path; opening is phase-only; RSS/CPU includes initialization and2048queries'}
(out/'size-control-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
with(out/'size-control-summary.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
print(json.dumps(summary,indent=2))
