from pathlib import Path
import tempfile,shutil,subprocess,json,hashlib
root=Path(__file__).resolve().parents[3];source=root/'dependencies/libxml2-speed/xerces-c-3.3.0/samples/data';binary=root/'dependencies/libxml2-speed/xerces-native-build/tests/DOMTest';out=root/'results/full-scaling/macos'
with tempfile.TemporaryDirectory(prefix='openms-xerces-dom-control-',dir='/tmp') as temp:
 fixture=Path(temp)/'data';shutil.copytree(source,fixture)
 for p in source.rglob('*'):
  if p.is_file():assert p.read_bytes()==(fixture/p.relative_to(source)).read_bytes()
 r=subprocess.run([str(binary)],cwd=fixture,capture_output=True,text=True);(out/'xerces-dom-control.log').write_text(r.stdout+r.stderr)
 receipt={'returncode':r.returncode,'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'method':'Unchanged native DOMTest binary and byte-identical copied sample fixtures; only cwd changes from spaced workspace to actual no-space temporary directory. Original failure was relative baseURI expectations.','source_fixture':str(source),'no_space_cwd':str(fixture)}
 (out/'xerces-dom-control.json').write_text(json.dumps(receipt,indent=2)+'\n');assert r.returncode==0,receipt
print('Unchanged native Xerces DOMTest passed with no-space cwd')
