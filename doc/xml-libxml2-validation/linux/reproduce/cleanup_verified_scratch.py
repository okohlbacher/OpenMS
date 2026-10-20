from pathlib import Path
import hashlib,json,shutil,datetime
root=Path('/scratch/kohlbach/openms-libxml2-replacement-20261020-01a153cb')
contrib=Path('/scratch/kohlbach/contrib/build')
assert str(root)=='/scratch/kohlbach/openms-libxml2-replacement-20261020-01a153cb'
assert root.is_dir() and not root.is_symlink() and root.resolve()==root
assert contrib.is_dir() and contrib.resolve()!=root
assert (root/'results/VALIDATION_EXIT_STATUS').read_text().strip()=='0'
assert (root/'results/CLASS_TEST_EXIT_STATUS').read_text().strip()=='0'
assert (root/'results/SUPPLEMENTAL_COMPLETE').is_file()
assert (root/'results/source-identity.txt').read_text().splitlines()[0]=='8f66b3d921c9512e1e5968f494c77715ff71c696'
assert not(root/'results/source-status.txt').read_text().strip()
for line in (root/'results/openms-libraries.sha256').read_text().splitlines():
 digest,path=line.split(None,1)
 assert hashlib.sha256(Path(path.strip()).read_bytes()).hexdigest()==digest
before=str(contrib.resolve())
shutil.rmtree(root)
assert not root.exists() and contrib.is_dir() and str(contrib.resolve())==before
print(json.dumps({'removed_root':str(root),'absent_after_removal':not root.exists(),'shared_contrib_preserved':str(contrib),'candidate':'8f66b3d921c9512e1e5968f494c77715ff71c696','local_copy_precondition':'233 result/log files verified against transfer-final-sha256.txt before this authorized cleanup','tests_succeeded':747,'review_gate':'Codex, Kimi and Claude Opus5.5 completed; no blocking findings','completed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()},indent=2))
