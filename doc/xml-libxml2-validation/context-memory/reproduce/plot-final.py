"""Render final selected memory and separately paired sustained clocks."""
import argparse,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
p=argparse.ArgumentParser();p.add_argument('analysis',type=Path);p.add_argument('profiles',type=Path);p.add_argument('out',type=Path);a=p.parse_args();a.out.mkdir(exist_ok=True,parents=True)
s=json.loads((a.analysis/'summary.json').read_text());long=json.loads((a.analysis/'sustained-comparisons.json').read_text())
N=[1,32,64,96];colors={'baseline':'#c97728','candidate':'#217b9a'}
names=['large-matched-plain.mzML','large-matched-zlib.mzML','dda-lumos.mzML','pasef-published.mzML','pasef-im-600-1200s.mzML'];labels=['Matched plain','Matched zlib','Real DDA','Published PASEF','Real TIMS IM']
label=dict(zip(names,labels))
def one(mode,name,v,n):return next(r for r in s if r['mode']==mode and r['input']==name and r['version']==v and r['workers']==n)
def save(fig,name):
 fig.tight_layout(rect=(0,.07,1,.94))
 for ext in ['png','svg']:fig.savefig(a.out/(name+'.'+ext),dpi=180)
 plt.close(fig)
fig,axs=plt.subplots(2,3,figsize=(13,8))
for ax,name,title in zip(axs.flat,names,labels):
 for v in colors:
  rs=[one('contexts',name,v,n) for n in N]
  ax.plot(N,[r['idle_adjusted_retained_mib_per_reader'] for r in rs],'o-',color=colors[v],label='Before: full footer DOM' if v=='baseline' else 'After: bounded DOM / reader')
 ax.set_ylim(0,1.12*max(one('contexts',name,v,n)['idle_adjusted_retained_mib_per_reader'] for v in colors for n in N));ax.set_title(title);ax.set_xscale('log',base=2);ax.set_xticks(N,list(map(str,N)));ax.set_ylim(bottom=0);ax.set_xlabel('Independent retained readers');ax.set_ylabel('Idle-adjusted MiB per reader');ax.grid(alpha=.2)
axs[1,2].axis('off');axs[1,2].legend(*axs[0,0].get_legend_handles_labels(),loc='upper left',frameon=False)
axs[1,2].text(.02,.65,'Same cached inputs and native SDK\n3 fresh processes per cell\nMetadata skipped\n96 CPUs = 64 physical + 32 SMT\n\nIM retains the existing small-footer path.\nContext estimate includes index/allocator state.',va='top',fontsize=11)
fig.suptitle('Retained libxml2 reader memory: targeted Linux follow-up',fontsize=15);fig.text(.5,.015,'Baseline reused only with unchanged binary/libraries/input and matching primary CPU placement; no new macOS performance measurement.',ha='center',fontsize=9);save(fig,'context-memory-scaling')
fig,axs=plt.subplots(1,2,figsize=(13,5.5));x=np.arange(5)
for k,v in enumerate(colors):
 bars=axs[0].bar(x+(k-.5)*.36,[one('contexts',n,v,96)['idle_adjusted_retained_mib_per_reader'] for n in names],.34,color=colors[v],label='Before' if v=='baseline' else 'After');axs[0].bar_label(bars,fmt='%.1f',fontsize=8,padding=3)
 bars=axs[1].bar(x+(k-.5)*.36,[one('indexed-sync',n,v,96)['peak_rss_mib_median']/1024 for n in names],.34,color=colors[v]);axs[1].bar_label(bars,fmt='%.2f',fontsize=8,padding=3)
for ax in axs:ax.set_xticks(x,['Plain','Zlib','DDA','PASEF','TIMS IM']);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True);ax.set_ylim(bottom=0)
axs[0].legend();axs[0].set_ylabel('Idle-adjusted MiB per reader');axs[0].set_title('96 retained contexts');axs[1].set_ylabel('Whole-process native peak RSS (GiB)');axs[1].set_title('96 synchronized random readers (short loops)')
fig.suptitle('Active context memory and random-read peaks are different measurements',fontsize=14);fig.text(.5,.015,'Contexts remain alive after workers join; indexed peaks include open/read/close. These are not isolated XML parser struct sizes.',ha='center',fontsize=9);save(fig,'memory-at-96')
long=sorted(long,key=lambda r:(names.index(r['input']),r['workers']));x=np.arange(len(long));xt=[label[r['input']].replace('Matched ','').replace('Published ','')+'\n'+str(r['workers'])+' readers\n'+('primary mask' if r.get('cpu_placement')=='0..95' else '0..N-1') for r in long]
fig,axs=plt.subplots(2,1,figsize=(16,8))
axs[0].bar(x,[r['worker_read_seconds_speedup'] for r in long],color='#217b9a');axs[0].axhline(1,color='#555');axs[0].axhline(1/1.05,color='#c97728',ls=':',label='5% slower threshold');axs[0].set_ylim(0,max(1.15,max(r['worker_read_seconds_speedup'] for r in long)*1.08));axs[0].legend(fontsize=8);axs[0].set_title('Per-worker query loop: excludes open, barrier and close')
for i,(field,color,name) in enumerate([('seconds_speedup','#477f59','Complete open/read/close'),('synchronized_read_seconds_speedup','#8966a1','Global read phase, including close/join')]):axs[1].bar(x+(i-.5)*.36,[r[field] for r in long],.34,color=color,label=name)
axs[1].axhline(1,color='#555');axs[1].legend(fontsize=8);axs[1].set_title('Opening and teardown can change end-to-end conclusions')
for ax in axs:ax.set_xticks(x,xt,fontsize=8);ax.set_ylabel('Speedup: baseline / final time');ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
fig.suptitle('Paired sustained indexed-read checks: three separate clocks',fontsize=15);fig.text(.5,.015,'3 randomized fresh processes per role/cell;8192 queries/reader, TIMS IM2048. Values >1 are faster; medians are descriptive, not significance tests.',ha='center',fontsize=9);save(fig,'sustained-indexed-speed')
fig,axs=plt.subplots(1,2,figsize=(13,5.5))
for k,(name,title) in enumerate([('baseline','Before'),('final','After')]):
 rows=[json.loads(l) for l in (a.profiles/f'profile-{name}-96-no-trim.jsonl').read_text().splitlines()];r=next(r for r in rows if r['phase']=='contexts_retained');col=list(colors.values())[k]
 vals=[r['resident_bytes']/2**30,(r['in_use_bytes']+r['mmap_bytes'])/2**30,r['free_arena_bytes']/2**30];bars=axs[0].bar(np.arange(3)+(k-.5)*.36,vals,.34,color=col,label=title);axs[0].bar_label(bars,fmt='%.2f',fontsize=8,padding=3)
 axs[1].plot(['Before open','96 retained','After close'],[r['resident_bytes']/2**30 for r in rows],'o-',color=col,label=title)
axs[0].set_xticks(np.arange(3),['Resident RSS','Live heap*','Free arenas*']);axs[0].set_title('Matched plain: retained allocator state');axs[1].set_title('No-trim lifecycle diagnostic')
for ax in axs:ax.set_ylabel('GiB');ax.set_ylim(bottom=0);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True);ax.legend()
fig.suptitle('Freed footer allocations explain retained memory; closing is a separate tradeoff',fontsize=14);fig.text(.5,.015,'*mallinfo2 covers the whole process; allocator counters are not RSS. No trim or allocator tuning in these traces or in OpenMS.',ha='center',fontsize=9);save(fig,'allocator-diagnostic')
