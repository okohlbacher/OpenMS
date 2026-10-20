"""Run only after all copied result/log bytes match the remote transport manifest."""
from pathlib import Path
import hashlib,json,os,re,shutil,sys,datetime
root=Path('/scratch/kohlbach/openms-libxml2-scaling-20261020-01a153cb');shared=Path('/scratch/kohlbach/contrib/build')
assert len(sys.argv)==2 and re.fullmatch('[0-9a-f]{64}',sys.argv[1])
assert not root.is_symlink() and root.resolve()==root and root.stat().st_uid==os.getuid()
assert shared.is_dir() and shared.resolve()!=root
assert (root/'results/PIPELINE_EXIT_STATUS').read_text().strip()=='0' and (root/'results/MATRICES_COMPLETE').is_file()
assert hashlib.sha256((root/'results/transport.sha256').read_bytes()).hexdigest()==sys.argv[1]
x=json.loads((root/'results/source-archive-verification.json').read_text());assert all(x['all_match'] for x in x['backends'].values())
m=json.loads((root/'staging/source-input-manifest.json').read_text());assert m['source_commits']['libxml2-full']=='8f66b3d921c9512e1e5968f494c77715ff71c696'
x=json.loads((root/'results/final-validation.json').read_text());assert sum(r['records'] for r in x.values())==2280
shutil.rmtree(root)
assert not root.exists() and shared.is_dir()
print(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'removed':str(root),'removed_exists_after':root.exists(),'shared_contrib_preserved':shared.is_dir(),'shared_contrib':str(shared),'verified_transport_manifest_sha256':sys.argv[1],'all_measured_runs_complete':True,'source_commits':m['source_commits']},indent=2))
