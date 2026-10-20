from pathlib import Path
import shutil,gzip,json,hashlib,subprocess,re
local=Path('results/context-memory');pub=Path('OpenMS-libxml2/doc/xml-libxml2-validation/context-memory');repo=Path('OpenMS-libxml2')
manifest=json.loads((local/'transport-manifest.json').read_text());mapping={'results':local/'linux-results','logs':local/'linux-logs','post-checks':local/'linux-post-checks','staging/benchmark-source':local/'linux-benchmark-source'}
for name,meta in manifest['files'].items():
 prefix=next(k for k in mapping if name.startswith(k+'/'));p=mapping[prefix]/name[len(prefix)+1:]
 assert p.stat().st_size==meta['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==meta['sha256'],name
source=json.loads((local/'staging/final-source-manifest.json').read_text());proof=json.loads((local/'linux-results/final-post-verification.json').read_text())
for name,v in source['committed_files'].items():
 assert proof['actual_source_sha256'][name]==v['sha256']
 assert hashlib.sha256(subprocess.check_output(['git','-C',str(repo),'show',source['candidate_product_commit']+':'+name])).hexdigest()==v['sha256']
(local/'local-copy-verification.json').write_text(json.dumps(dict(transport_files_checked=len(manifest['files']),all_bytes_and_hashes_match=True,actual_compiled_source_matches_committed_blobs=True),indent=2)+'\n')
def copy(src,dst,compress=False):
 dst.parent.mkdir(exist_ok=True,parents=True)
 if compress:Path(str(dst)+'.gz').write_bytes(gzip.compress(src.read_bytes(),mtime=0))
 else:shutil.copyfile(src,dst)
for src in (local/'linux-results').rglob('*'):
 if src.is_file() and src.name not in ['buffer-speed.jsonl','packed-speed.jsonl']:
  copy(src,pub/'raw'/src.relative_to(local/'linux-results'),src.suffix=='.jsonl')
for folder,dest in [(local/'linux-logs',pub/'build/linux'),(local/'logs',pub/'build/macos')]:
 for src in folder.rglob('*'):
  if src.is_file():copy(src,dest/src.relative_to(folder),src.suffix=='.log')
for src in (local/'review').rglob('*'):
 if src.is_file() and 'stderr' not in src.name and src.suffix in ['.md','.json','.txt','.py']:
  copy(src,pub/'review'/src.relative_to(local/'review'))
for src in (local/'reproduce').glob('*'):
 if src.is_file() and src.suffix in ['.py','.sh','.json','.cpp']:
  copy(src,pub/'reproduce'/src.name)
for src in (local/'linux-benchmark-source').rglob('*'):
 if src.is_file():copy(src,pub/'reproduce/private-harness'/src.relative_to(local/'linux-benchmark-source'))
for src in (local/'staging/final-controls').glob('*'):
 if src.is_file():copy(src,pub/'reproduce/final-controls'/src.name)
for name in ['buffer-copy-experiment.patch','packed-first.cpp','packed-prealloc.cpp','final-source-manifest.json','final-product.patch']:
 copy(local/'staging'/name,pub/'reproduce'/name)
for name in ['transport-manifest.json','local-copy-verification.json']:copy(local/name,pub/'raw'/name)
for src in (local/'final-analysis').glob('*'):
 if src.suffix in ['.json','.csv']:copy(src,pub/src.name)
# Preserve readable prose without modifying byte-pinned source/review/raw data.
for p in [pub/'REPORT.md',pub/'DETAILS.md',pub/'reproduce/README.md']:
 text=p.read_text();parts=re.split(r'(`[^`]*`|\[[^\]]*\]\([^)]*\))',text)
 for i in range(0,len(parts),2):
  t=parts[i]
  t=re.sub(r'\b(At|at|through|from|to|plus|than|use|include|Five|previous|are|the|full|plain|DDA|PASEF|about|with|below|above|by|all|roughly|contains|same|first|over|both|per|on)(?=\d)',r'\1 ',t)
  t=re.sub(r'(?<=\d)(MiB|GiB|GB|MB|ms|queries|readers|fresh|records|cells|CPUs|settings|files)\b',r' \1',t)
  t=re.sub(r'\b(IM|Opus)(?=\d)',r'\1 ',t);t=re.sub(r'([≤≥])(?=\d)',r'\1 ',t)
  parts[i]=t
 p.write_text(''.join(parts))
print('Verified transport files:',len(manifest['files']),'curated files:',sum(p.is_file() for p in pub.rglob('*')))
