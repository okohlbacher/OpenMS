from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
out=Path(__file__).resolve().parent;d=json.loads((out/'selected-tables.json').read_text());fig,axs=plt.subplots(2,2,figsize=(12.5,8));colors=['#d98532','#287a9e'];labels=['Xerces','Complete libxml2']
ax=axs[0,0];names=['medium.mzML','medium-zlib.mzML','medium-zlib.mzML.gz'];xx=np.arange(3)
for i,b in enumerate(['xerces','libxml2-full']):
 ys=[next(r['derived_Mpoints_per_s'] for r in d['linux_technical'] if r['input_name']==n and r['backend']==b) for n in names];bars=ax.bar(xx+(i-.5)*.36,ys,.34,color=colors[i],label=labels[i]);ax.bar_label(bars,fmt='%.2f',fontsize=8,padding=3)
ax.set_xticks(xx,['Plain XML','Internal zlib','Internal zlib\n+ outer gzip']);ax.set_ylabel('Decoded million points/s');ax.set_title('Linux: identical decoded work, one reader');ax.legend(fontsize=9);ax.set_ylim(0,16)
ax=axs[0,1];cases=[('Linux Latin-1','linux_encoding','large.mzML'),('Linux UTF-8','linux_encoding','large-utf8.mzML'),('Mac Latin-1','macos_native_encoding','large.mzML'),('Mac UTF-8','macos_native_encoding','large-utf8.mzML')];xx=np.arange(4)
for i in range(2):
 ys=[]
 for _,group,name in cases:
  backend=(['xerces','libxml2-full'] if group=='linux_encoding' else ['xerces-native-o3','full-o3'])[i];ys.append(next(r['derived_file_MB_per_s'] for r in d[group] if r['input_name']==name and r['backend']==backend))
 bars=ax.bar(xx+(i-.5)*.36,ys,.34,color=colors[i]);ax.bar_label(bars,fmt='%.0f',fontsize=8,padding=3)
ax.set_xticks(xx,[r[0] for r in cases],fontsize=9,rotation=12);ax.set_ylabel('File MB/s (decimal)');ax.set_title('1,126.2 MB input: native -O3 parser builds');ax.set_ylim(0,520)
for ax,name,title in [(axs[1,0],'large.mzML','Linux: large/plain XML'),(axs[1,1],'medium-zlib.mzML.gz','Linux: internal zlib + outer gzip')]:
 for i,b in enumerate(['xerces','libxml2-full']):
  rr=[r for r in d['linux_reader_scaling'] if r['input_name']==name and r['backend']==b];ax.plot([int(r['workers']) for r in rr],[r['derived_file_MB_per_s'] for r in rr],'o-',color=colors[i],label=labels[i],ms=4)
 ax.set_xscale('log',base=2);ax.set_xticks([1,2,4,8,16,32,64,96],[str(n) for n in [1,2,4,8,16,32,64,96]]);ax.set_xlabel('Independent readers; OpenMP=1');ax.set_ylabel('Aggregate file MB/s');ax.set_title(title);ax.axvline(64,color='#999',ls=':',lw=.8);ax.set_ylim(bottom=0)
for ax in axs.flat:ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
fig.suptitle('mzML throughput re-expressed from recorded five-run medians',fontsize=14)
fig.text(.5,.022,'Cached OpenMS parse + base64/decompression + decoded-data digest; no XSD timing. MB = 10⁶ bytes. Readers share one input.',ha='center',fontsize=8)
fig.text(.5,.006,'Matched medium forms: 140.8 / 68.9 / 42.3 MB and 8.39 million points each. Outer-gzip curves do not measure parallel inflation of one file.',ha='center',fontsize=8)
fig.tight_layout(rect=(0,.055,1,.95))
for ext in ['png','svg']:fig.savefig(out/('throughput.'+ext),dpi=170)
print('Graph generated')
