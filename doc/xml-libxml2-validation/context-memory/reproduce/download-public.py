from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,subprocess,time
root=Path('/scratch/kohlbach/openms-context-memory-20261020-01a153cb')
manifest=json.loads((root/'staging/real-input-manifest.json').read_text())

def download(row):
    target=root/'data'/row['destination'];target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_name(target.name+'.download')
    if target.exists():
        with target.open('rb') as f:
            if target.stat().st_size==row['bytes'] and hashlib.file_digest(f,'sha256').hexdigest()==row['sha256']:
                return dict(destination=row['destination'],sha256=row['sha256'],reused_verified=True)
    begin=time.time()
    subprocess.run(['curl','--silent','--show-error','--fail','--location','--retry','5','--retry-delay','30','--retry-max-time','1200','--connect-timeout','30','--max-time','3600',row['source_url'],'-o',str(temporary)],check=True)
    with temporary.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
    assert temporary.stat().st_size==row['bytes'] and actual==row['sha256'],row['destination']
    temporary.rename(target)
    print('Verified',row['destination'],row['bytes'],flush=True)
    return dict(destination=row['destination'],sha256=actual,elapsed_seconds=time.time()-begin)

with ThreadPoolExecutor(max_workers=1) as pool:
    rows=list(pool.map(download,manifest['files'][1:]))
(root/'results/direct-public-downloads.json').write_text(json.dumps(rows,indent=2)+'\n')
