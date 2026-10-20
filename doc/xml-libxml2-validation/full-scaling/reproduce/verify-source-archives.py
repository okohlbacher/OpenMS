from pathlib import Path
import hashlib,json,tarfile,datetime
root=Path('/scratch/kohlbach/openms-libxml2-scaling-20261020-01a153cb');assert (root/'results/PIPELINE_EXIT_STATUS').read_text().strip()=='0';manifest=json.loads((root/'staging/source-input-manifest.json').read_text());outputs={}
for backend in ['xerces','libxml2-full']:
 archive=root/'staging'/(backend+'.tar.gz');expected=manifest['files']['results/full-scaling/staging/'+backend+'.tar.gz']['sha256'];assert hashlib.sha256(archive.read_bytes()).hexdigest()==expected
 entries=[];differences=[]
 with tarfile.open(archive) as tar:
  for m in tar:
   if not m.isfile():continue
   p=root/('source-'+backend)/m.name
   h=hashlib.sha256(tar.extractfile(m).read()).hexdigest()
   if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=h:differences.append(m.name)
   entries.append((m.name,h))
 outputs[backend]={'source_commit':manifest['source_commits'][backend],'archive_sha256':expected,'regular_files':len(entries),'all_match':not differences,'differences':differences}
harness=json.loads((root/'staging/harness-source-manifest.json').read_text())
for row in harness['files']:
 assert row['matches_frozen_public_source']
 assert hashlib.sha256((root/'staging/benchmark-source'/row['file']).read_bytes()).hexdigest()==row['sha256']
assert hashlib.sha256((root/'run_benchmarks.py').read_bytes()).hexdigest()==next(r['sha256'] for r in harness['files'] if r['file']=='run_benchmarks.py')
(root/'results/source-archive-verification.json').write_text(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'backends':outputs,'harness_matches_public_frozen_source':True,'harness_source_commit':harness['public_source_commit'],'harness_files':len(harness['files'])},indent=2)+'\n')
assert all(x['all_match'] for x in outputs.values()),outputs
print('All tracked archive files still match both measured source trees')
