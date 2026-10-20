"""Derive throughput units from frozen measurements; does not rerun benchmarks."""
from pathlib import Path
import csv,gzip,hashlib,json,statistics
root=Path(__file__).resolve().parents[2];out=Path(__file__).resolve().parent;source=root/'results/full-scaling/all-comparisons.csv';raw=json.loads((root/'results/full-scaling/linux/benchmarks.json').read_text());inputs={}
for path,meta in raw['inputs'].items():
 r=next(r for r in raw['records'] if r['input']==path and r['mode']=='stream')
 inputs[Path(path).name]=dict(meta,points=r['points_per_worker'],spectra=r['spectra_per_worker'],digest=r['hash_per_worker'])
inputs['large-utf8.mzML']=dict(inputs['large.mzML'],sha256='b864ae517f17976e50f3ffcbb2d205db6532f28b76b27b44d93dbe3b3600b81d')
assert len({inputs[n]['digest'] for n in ['medium.mzML','medium-zlib.mzML','medium-zlib.mzML.gz']})==1
h=hashlib.sha256()
with gzip.open(root/'benchmark-data/medium-zlib.mzML.gz','rb') as f:
 for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
assert h.hexdigest()==inputs['medium-zlib.mzML']['sha256']
with source.open() as f:reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
added=['input_name','input_file_MB','decoded_points_per_file','derived_file_MB_per_s','derived_file_MiB_per_s','derived_outer_inflated_XML_MB_per_s','derived_plain_XML_equivalent_MB_per_s','derived_Mpoints_per_s','derived_files_per_s','derived_queries_per_s','derived_open_ms_per_reader','derived_rate_scope','derived_effective_mode','derived_effective_readers']
for r in rows:
 name=Path(r['input']).name;meta=inputs[name];r.update(input_name=name,input_file_MB=meta['bytes']/1e6,decoded_points_per_file=meta['points'])
 if r.get('file_bytes'):assert int(r['file_bytes'])==meta['bytes']
 r['file_bytes']=meta['bytes'];n=int(r['workers'] or (1 if r['matrix']=='openmp-scaling' else 0));mode=r['mode'] or ('stream' if r['matrix']=='openmp-scaling' else '');assert n>0;r.update(derived_effective_mode=mode,derived_effective_readers=n);seconds=float(r['seconds_median']);assert seconds>0
 if mode in ['stream','load']:
  xml=inputs['medium-zlib.mzML']['bytes'] if name.endswith('.gz') else meta['bytes'];plain=inputs['medium.mzML']['bytes'] if name in ['medium.mzML','medium-zlib.mzML','medium-zlib.mzML.gz'] else meta['bytes']
  r.update(derived_file_MB_per_s=n*meta['bytes']/seconds/1e6,derived_file_MiB_per_s=n*meta['bytes']/seconds/2**20,derived_outer_inflated_XML_MB_per_s=n*xml/seconds/1e6,derived_plain_XML_equivalent_MB_per_s=n*plain/seconds/1e6,derived_Mpoints_per_s=n*meta['points']/seconds/1e6,derived_files_per_s=n/seconds,derived_rate_scope='aggregate independent readers' if n>1 else 'single reader')
  if r.get('aggregate_mib_per_second'):assert abs(float(r['aggregate_mib_per_second'])-r['derived_file_MiB_per_s'])<1e-6
 if r['mode'] in ['indexed','indexed-metadata']:r['derived_queries_per_s']=r['aggregate_spectra_per_second']
 if r['mode'] in ['indexed','indexed-metadata','index-open','contexts','contexts-metadata']:r['derived_open_ms_per_reader']=float(r['job_open_seconds_median'])*1000
with(out/'throughput-all-phases.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields+added);w.writeheader();w.writerows(rows)
fresh=[r for r in rows if r['evidence_phase'].startswith('complete-scaling-')]
with(out/'throughput-complete-replacement.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields+added);w.writeheader();w.writerows(fresh)
# Machine-readable tables used by the response and graph.
def select(matrix,name,b,n=1,omp=1,platform='linux'):
 return next(r for r in fresh if r['platform']==platform and r['matrix']==matrix and r['input_name']==name and r['backend']==b and int(r['workers'])==n and int(r['openmp_threads'])==omp and r['mode']=='stream')
tables={}
for key,names,matrix in [('linux_technical',['large.mzML','medium.mzML','medium-zlib.mzML','medium-zlib.mzML.gz'],'benchmarks'),('linux_encoding',['large.mzML','large-utf8.mzML'],'encoding-followup')]:
 tables[key]=[{k:r[k] for k in ['input_name','backend','workers','input_file_MB','seconds_median','derived_file_MB_per_s','derived_outer_inflated_XML_MB_per_s','derived_plain_XML_equivalent_MB_per_s','derived_Mpoints_per_s']} for name in names for b in ['xerces','libxml2-full'] for r in [select(matrix,name,b)]]
tables['linux_reader_scaling']=[{k:r[k] for k in ['input_name','backend','workers','seconds_median','derived_file_MB_per_s','derived_plain_XML_equivalent_MB_per_s','derived_Mpoints_per_s']} for name in ['large.mzML','medium-zlib.mzML.gz'] for n in [1,2,4,8,16,32,64,96] for b in ['xerces','libxml2-full'] for r in [select('benchmarks',name,b,n)]]
tables['macos_native_encoding']=[{k:r[k] for k in ['input_name','backend','seconds_median','derived_file_MB_per_s','derived_Mpoints_per_s']} for name in ['large.mzML','large-utf8.mzML'] for b in ['xerces-native-o3','full-o3'] for r in [select('matched-native',name,b,platform='macos')]]
tables['linux_fixed_work_OpenMP']=[{k:r[k] for k in ['input_name','backend','openmp_threads','seconds_median','derived_file_MB_per_s','derived_plain_XML_equivalent_MB_per_s','derived_Mpoints_per_s']} for name in ['large.mzML','medium-zlib.mzML'] for omp in [1,2,4,8,16,32,64,96] for b in ['xerces','libxml2-full'] for r in [select('openmp-scaling',name,b,omp=omp)]]
(out/'selected-tables.json').write_text(json.dumps(tables,indent=2)+'\n')
(out/'provenance.json').write_text(json.dumps({'derived_from':str(source.relative_to(root)),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'all_summary_cells':len(rows),'new_summary_cells':len(fresh),'new_benchmark_runs':0,'inputs':inputs,'definitions':{'MB':'1000000 bytes','MiB':'1048576 bytes','file_MB_per_s':'reader_count * actual file bytes / median workload seconds / 1e6; streaming/load only','plain_XML_equivalent_MB_per_s':'same formula using140758760 bytes for the three matched medium forms; nominal work normalization, not actual compressed bytes read','outer_inflated_XML_MB_per_s':'uses68885049 bytes for outer gzip, otherwise actual XML file size','Mpoints_per_s':'reader_count * decoded spectrum+chromatogram point count / median seconds /1e6','indexed':'queries/s, not fictitious whole-file MB/s','timing':'C++ workload interval, warmed shared initialization excluded; cached inputs; medians of five; no XSD validation timed','historical':'phase labels, clock caveats and source distinctions retained; source CSV untouched. Blank historical OpenMP worker/mode fields are resolved as1reader/stream only in added effective fields'},'limitations':['Compressed matched corpus is140.8MB plain /68.9MB internal-zlib /42.3MB outer-gzip, not the1.126GB large input.','Outer gzip thread scaling is independent full-file readers, not one-stream parallel inflation or pigz.','No acquisition-stratified PASEF/IM/DDA benchmark corpus measured.','Current native macOS controls have one reader; historical Mac reader scaling remains separately labeled.']},indent=2)+'\n')
print('Derived',len(rows),'all-phase and',len(fresh),'fresh summary rows; zero new benchmark runs')
for name in ['linux_technical','linux_encoding','macos_native_encoding']:
 print(name)
 for r in tables[name]:print(r['input_name'],r['backend'],round(float(r['seconds_median']),4),round(r['derived_file_MB_per_s'],1),round(r['derived_Mpoints_per_s'],2))
