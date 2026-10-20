from pathlib import Path
import subprocess,os,json
root=Path(__file__).resolve().parents[3];out=root/'results/full-scaling/macos';fixtures=out/'ignored-text-fixtures';fixtures.mkdir(exist_ok=True)
original=(root/'benchmark-data/small.mzML').read_bytes();start=original.index(b'<binary>')+len(b'<binary>');assert original[start] in b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
utf8=original.replace(b'encoding="ISO-8859-1"',b'encoding="UTF-8"     ',1);assert len(utf8)==len(original)
cases=[('latin1-high-byte',original[:start]+b'\xe9'+original[start+1:],True),('utf8-high-bytes',utf8[:start]+b'\xc3\xa9'+utf8[start+2:],True),('utf8-invalid-byte',utf8[:start]+b'\xff'+utf8[start+1:],False),('undefined-entity',original[:start]+b'&undefined;'+original[start+11:],False)]
rows=[];binary=root/'benchmark-optimized-build/xml_parser_benchmark';launcher=binary.with_name('xml_benchmark_launcher')
for case,payload,expected in cases:
 assert len(payload)==len(original);path=fixtures/(case+'.mzML');path.write_bytes(payload)
 for mode in ['contexts-metadata','stream']:
  baseline=None
  for backend in ['full-homebrew','full-ascii-o3','discard-ascii-o3']:
   env=dict(os.environ,DYLD_LIBRARY_PATH=str(out/'snapshots'/backend/'lib'),OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
   r=subprocess.run([str(launcher),str(binary),mode,str(path),'1','0'],env=env,capture_output=True,text=True);lines=[s for s in r.stdout.splitlines() if s.startswith('{')];value=json.loads(lines[-1]) if lines else None
   current=(r.returncode,tuple(value[k] for k in ['hash_per_worker','spectra_per_worker','chromatograms_per_worker','points_per_worker','index_spectra','index_chromatograms']) if value else None)
   if baseline is None:baseline=current
   else:assert current==baseline,(case,mode,backend,baseline,current)
   if mode=='contexts-metadata':assert (r.returncode==0)==expected,(case,backend,r.stderr)
   if mode=='contexts-metadata' and case=='undefined-entity':assert 'undefined' in r.stderr.lower(),r.stderr
   rows.append({'case':case,'mode':mode,'backend':backend,'accepted':r.returncode==0,'returncode':r.returncode,'fingerprint':current[1],'stderr':r.stderr})
(out/'ignored-text-correctness.json').write_text(json.dumps({'checks':len(rows),'all_outcomes_and_digests_match':True,'method':'Same-length payload mutations preserve raw index offsets; highLatin1/UTF8 payloads are ignored by metadata-only reads, invalidUTF8/entities must still reject; full streaming outcomes compared too.','results':rows},indent=2)+'\n');print('Ignored-text edge cases',len(rows),'matched')
