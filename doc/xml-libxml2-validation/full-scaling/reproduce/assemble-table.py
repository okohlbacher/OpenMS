from pathlib import Path
import csv,json,hashlib,statistics
root=Path(__file__).resolve().parents[3];out=root/'results/full-scaling';old=root/'OpenMS-libxml2/doc/xml-libxml2-validation/encoding-final/all-comparisons.csv'
with old.open() as f:r=csv.DictReader(f);fields=r.fieldnames;prior=list(r)
fields += [k for k in ['native_parser_build','parser_library_sha256','experimental_patch_sha256','file_bytes'] if k not in fields]
refs={'xerces':'58aa37348c968a12e3285295f28c197cc0b7bdbe','libxml2-full':'8f66b3d921c9512e1e5968f494c77715ff71c696'};rows=[];new_records=0
contexts=json.loads((out/'linux/context-overhead.json').read_text())['results'];contextmap={(r['backend'],r['input'],r['mode'],r['workers']):r for r in contexts}
def corehash(x,b):return next(h for p,h in x['libraries'][b].items() if Path(p).name.startswith('libOpenMS.'))
for platform,datasets in [('linux',['benchmarks','memory-scaling','metadata-scaling','openmp-scaling','encoding-followup']),('macos',['options','size-control','matched-native'])]:
 for name in datasets:
  x=json.loads((out/platform/(name+'.json')).read_text());new_records+=len(x['records'])
  for r in x['summary']:
   b=r['backend'];v={k:r.get(k,'') for k in fields};v.update(platform=platform,variant='complete-replacement' if platform=='linux' else 'macos-optimization-options',matrix=name,evidence_phase='complete-scaling-'+platform,source_commit=refs['xerces'] if b.startswith('xerces') else refs['libxml2-full'],library_sha256=corehash(x,b))
   if name=='openmp-scaling':v.update(mode='stream',workers=1,openmp_threads=r['openmp_threads'])
   else:v['openmp_threads']=1
   v['input']=r['input'].replace('/scratch/kohlbach/openms-libxml2-scaling-20261020-01a153cb','$LINUX_WORKSPACE').replace(str(root),'$WORKSPACE')
   v['declaration']='UTF-8' if Path(r['input']).name=='large-utf8.mzML' else 'ISO-8859-1'
   v['file_bytes']=x.get('inputs',{}).get(r['input'],{}).get('bytes','')
   if platform=='linux':
    v['native_parser_build']='Xerces3.3.0 Release -O3 gnuiconv' if b=='xerces' else 'libxml2 2.15.4 unpatched Release -O3'
    cm=contextmap.get((b,r['input'],r.get('mode'),r.get('workers')))
    if cm:v.update(idle_peak_rss_mib_median=cm['peak_idle_mib'],peak_excess_mib_per_reader=cm['peak_extra_mib_per_reader'],idle_resident_rss_mib_median=cm['resident_idle_mib'],retained_overhead_mib_per_reader=cm['resident_extra_mib_per_reader'])
    prefix='libxerces-c' if b=='xerces' else 'libxml2.so';v['parser_library_sha256']=next(line.split()[0] for line in (out/'linux/dependency-libraries.sha256').read_text().splitlines() if Path(line.split()[1]).name.startswith(prefix))
   else:
    v['native_parser_build']=('Xerces3.3.0 native -O3 CoreFoundation' if b=='xerces-native-o3' else 'Xerces3.3.0 Homebrew bottle' if b.startswith('xerces') else 'libxml2 2.15.4 '+('Homebrew bottle' if b.endswith('homebrew') else 'CMake -Os' if b=='full-os' else 'CMake -O2' if b=='full-o2' else 'CMake -O3 ASCII converter prototype' if 'ascii' in b else 'CMake -O3'))
    hashes=[h for p,h in x['libraries'][b].items() if Path(p).name.startswith(('libxml2.','libxerces-c'))]
    if hashes:v['parser_library_sha256']=hashes[0]
    else:v['parser_library_sha256']=hashlib.sha256(Path('/opt/homebrew/opt/xerces-c/lib/libxerces-c.dylib').read_bytes()).hexdigest()
    patches=[]
    if 'ascii' in b:patches.append(hashlib.sha256((out/'macos/libxml2-ascii.patch').read_bytes()).hexdigest())
    if b.startswith('discard'):patches.append(hashlib.sha256((out/'macos/handler-discard-first.patch').read_bytes()).hexdigest())
    v['experimental_patch_sha256']=';'.join(patches)
   rows.append(v)
with(out/'all-comparisons.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(prior);w.writerows(rows)
(out/'table-provenance.json').write_text(json.dumps({'prior_cells':len(prior),'new_cells':len(rows),'new_process_records':new_records,'total_cells':len(prior)+len(rows),'prior_phase':'published prototypes and120declaration followups','new_phase':'complete replacement Linux96scaling plus isolatedMacbuild/sourceoptions','all_new_cells_five_repetitions':all(r['repetitions']==5 for r in rows),'historical_rows_retained':True,'time_column':'seconds_median is whole workload; job_open_seconds_median isolates opening'},indent=2)+'\n');assert all(r['repetitions']==5 for r in rows);print('Table:',len(prior),'historical+',len(rows),'new cells;',new_records,'new process records')
