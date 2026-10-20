from pathlib import Path
from collections import defaultdict
import json,statistics,csv
root=Path(__file__).resolve().parents[3];out=root/'results/full-scaling/linux';names={'benchmarks':1280,'memory-scaling':480,'metadata-scaling':320,'openmp-scaling':160,'encoding-followup':40};records={};summary={};flags=[]
for name,n in names.items():
 x=json.loads((out/(name+'.json')).read_text());assert len(x['records'])==n and not x['failures'],name;records[name]=x['records'];summary[name]=x['summary']
 for r in x['records']:
  if r['seconds']>r['process_seconds']+.1:flags.append({'matrix':name,'backend':r['backend'],'input':r['input'],'workers':r['workers'],'repetition':r['repetition']})
# Declaration-only control must also agree across the two different input paths.
encoding_digests={}
for r in records['encoding-followup']:
 key=r['mode'];value=tuple(r[k] for k in ['hash_per_worker','spectra_per_worker','chromatograms_per_worker','points_per_worker','index_spectra','index_chromatograms'])
 assert key not in encoding_digests or encoding_digests[key]==value,(key,r)
 encoding_digests[key]=value
context=[]
for name,mode in [('memory-scaling','contexts'),('metadata-scaling','contexts-metadata')]:
 x=summary[name];idle=summary['memory-scaling']
 for r in x:
  if r['mode']!=mode:continue
  i=next(i for i in idle if i['backend']==r['backend'] and i['input']==r['input'] and i['mode']=='idle' and i['workers']==r['workers'])
  context.append({'backend':r['backend'],'input':r['input'],'mode':mode,'workers':r['workers'],'resident_context_mib':r['resident_rss_mib_median'],'resident_idle_mib':i['resident_rss_mib_median'],'resident_extra_mib_per_reader':(r['resident_rss_mib_median']-i['resident_rss_mib_median'])/r['workers'],'peak_context_mib':r['rss_mib_median'],'peak_idle_mib':i['rss_mib_median'],'peak_extra_mib_per_reader':(r['rss_mib_median']-i['rss_mib_median'])/r['workers']})
(out/'context-overhead.json').write_text(json.dumps({'method':'Difference of median context and idle RSS at matching N/backend/input, divided byN. Includes retained index/metadata, allocator retention and reader state; not sizeof(native parser). Peakwait4 and approximatestatm resident kept separate.','results':context},indent=2)+'\n')
with (out/'context-overhead.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(context[0]));w.writeheader();w.writerows(context)
(out/'analysis.json').write_text(json.dumps({'process_records':sum(names.values()),'cells':sum(len(s) for s in summary.values()),'clock_flags':flags,'context_rows':len(context),'source':'8f66b3d921c9512e1e5968f494c77715ff71c696','canonical_native_library':'unpatched libxml2-2.15.4','independent_reader_threads':[1,2,4,8,16,32,64,96],'fixed_work_OpenMP_threads':[1,2,4,8,16,32,64,96]},indent=2)+'\n')
print('Linux:',sum(names.values()),'records;',len(context),'context rows;',len(flags),'clock flags')
