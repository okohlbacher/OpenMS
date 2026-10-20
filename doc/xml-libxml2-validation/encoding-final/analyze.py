from pathlib import Path
from collections import defaultdict
import json,statistics,csv,hashlib
root=Path(__file__).resolve().parents[2];out=root/'results/encoding-final185/macos';x=json.loads((out/'benchmarks.json').read_text());prep=json.loads((out/'input-preparation.json').read_text())
assert len(x['records'])==60 and not x['failures'],(len(x['records']),x['failures'])
groups=defaultdict(list);digests={};clock=[]
for row in x['records']:
 key=row['mode'];fingerprint=tuple(row[n] for n in ['hash_per_worker','spectra_per_worker','chromatograms_per_worker','points_per_worker','index_spectra','index_chromatograms'])
 assert key not in digests or digests[key]==fingerprint,(key,row);digests[key]=fingerprint
 encoding='UTF-8' if Path(row['input']).name=='large-utf8.mzML' else 'ISO-8859-1';groups[row['backend'],encoding,row['mode']].append(row)
 if row['seconds']>row['process_seconds']+0.1 or row['user_seconds']+row['system_seconds']>row['process_seconds']*1.1+0.1:clock.append(row)
for label,files in x['libraries'].items():
 for path,digest in files.items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest,path
rows=[]
for (backend,encoding,mode),records in sorted(groups.items()):
 assert len(records)==5
 times=[r['seconds'] if mode=='stream' else r['jobs'][0]['open_seconds'] for r in records]
 rows.append({'backend':backend,'encoding':encoding,'mode':mode,'repetitions':5,'seconds_median':statistics.median(times),'seconds_min':min(times),'seconds_max':max(times),'peak_rss_mib_median':statistics.median(r['max_rss_bytes']/2**20 for r in records),'process_user_seconds_median':statistics.median(r['user_seconds'] for r in records),'process_system_seconds_median':statistics.median(r['system_seconds'] for r in records),'total_workload_seconds_median':statistics.median(r['seconds'] for r in records)})
summary={'source_comment':'https://github.com/OpenMS/OpenMS/issues/10623#issuecomment-6284417895','candidate':json.loads((out/'experiment.json').read_text())['candidate'],'results':rows,'all_cross_encoding_and_backend_digests_match':True,'library_hashes_unchanged_through_run':True,'clock_check_flags':clock,'input_bytes':prep['bytes'],'method':'Stream uses workload elapsed; default open uses job.open_seconds excluding2048randomqueries. PeakRSS/user/systemCPU coverentireprocessincludingqueries andcommoninitialization. Min/median/maxof5 randomizedrepeats.'}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
with (out/'comparison.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
old=root/'results/encoding-followup/macos/all-comparisons.csv'
with old.open() as f:reader=csv.DictReader(f);fields=reader.fieldnames;prior=list(reader)
fields += [k for k in ['declaration','source_commit','library_sha256','evidence_phase'] if k not in fields]
with (out/'all-comparisons.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
 for row in prior:w.writerow(row)
 for row in x['summary']:
  extra={k:row.get(k,'') for k in fields};extra.update(platform='macos',variant='encoding-final185',matrix='encoding-declaration',input=row['input'].replace(str(root),'$WORKSPACE'),declaration='UTF-8' if 'large-utf8' in row['input'] else 'ISO-8859-1',source_commit=summary['candidate'] if row['backend']=='libxml2-full' else '',library_sha256=next(d for p,d in x['libraries'][row['backend']].items() if p.endswith('/libOpenMS.dylib')),evidence_phase='encoding-final185');w.writerow(extra)
print(json.dumps(summary,indent=2))
print('Combined table prior rows',len(prior),'new cells',len(x['summary']))
