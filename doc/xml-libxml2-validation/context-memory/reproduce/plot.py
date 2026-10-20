import argparse,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
p=argparse.ArgumentParser();p.add_argument('summary',type=Path);p.add_argument('profiles',type=Path);p.add_argument('output',type=Path);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
s=json.loads(a.summary.read_text());N=[1,32,64,96];C={'baseline':'#c97728','candidate':'#217b9a'}
names=['large-matched-plain.mzML','large-matched-zlib.mzML','dda-lumos.mzML','pasef-published.mzML','pasef-im-600-1200s.mzML'];labels=['Plain arrays','Internal zlib','Real DDA','Published PASEF','Real TIMS IM']
def one(mode,name,v,n):return next(r for r in s if r['mode']==mode and r['input']==name and r['version']==v and r['workers']==n)
def save(fig,name):
 fig.tight_layout(rect=(0,.05,1,.94))
 for ext in ['png','svg']:fig.savefig(a.output/(name+'.'+ext),dpi=180)
 plt.close(fig)
fig,axs=plt.subplots(2,3,figsize=(14,8))
for j,i in enumerate([0,2,4]):
 for v in C:
  axs[0,j].plot(N,[one('contexts',names[i],v,n)['idle_adjusted_retained_mib_per_reader'] for n in N],'o-',color=C[v],label='Before: footer DOM' if v=='baseline' else 'After: forward reader')
  axs[1,j].plot(N,[one('indexed-sync',names[i],v,n)['synchronized_read_queries_per_s'] for n in N],'o-',color=C[v])
 for row in [0,1]:
  ax=axs[row,j];ax.set_xscale('log',base=2);ax.set_xticks(N,list(map(str,N)));ax.set_xlabel('Independent readers');ax.grid(alpha=.2);ax.set_title(labels[i]);ax.set_ylim(bottom=0);ax.axvline(64,color='#aaa',lw=.7,ls=':')
 axs[0,j].set_ylabel('Idle-adjusted retained MiB per reader');axs[1,j].set_ylabel('Synchronized read-phase queries/s')
axs[0,0].legend(fontsize=8);fig.suptitle('libxml2 footer optimization: retained context memory and indexed reads',fontsize=14)
fig.text(.5,.01,'3 fresh-process runs/cell; cached same input; metadata skipped. Read-phase clock includes teardown/join. 96 CPUs = 64 physical + 32 SMT.',ha='center',fontsize=8);save(fig,'context-memory-scaling')
fig,axs=plt.subplots(1,2,figsize=(13,5))
x=np.arange(5)
for k,v in enumerate(C):
 bars=axs[0].bar(x+(k-.5)*.36,[one('contexts',n,v,96)['idle_adjusted_retained_mib_per_reader'] for n in names],.34,color=C[v],label='Before' if v=='baseline' else 'After')
 axs[0].bar_label(bars,fmt='%.1f',fontsize=8,padding=3)
 bars=axs[1].bar(x+(k-.5)*.36,[one('indexed-sync',n,v,96)['peak_rss_mib_median']/1024 for n in names],.34,color=C[v])
 axs[1].bar_label(bars,fmt='%.2f',fontsize=8,padding=3)
for ax in axs:ax.set_xticks(x,['Plain','Zlib','DDA','PASEF','TIMS IM']);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True);ax.set_ylim(bottom=0)
axs[0].legend();axs[0].set_ylabel('Idle-adjusted retained MiB per reader');axs[0].set_title('96 retained readers');axs[1].set_ylabel('Process native peak RSS (GiB)');axs[1].set_title('96 synchronized random readers')
fig.suptitle('Measured memory reductions on five indexed inputs',fontsize=14);fig.text(.5,.01,'Context estimates include index/allocator state, not isolated XML parser structs. Native peaks cover complete indexed workload.',ha='center',fontsize=8);save(fig,'memory-at-96')
fig,axs=plt.subplots(1,2,figsize=(13,5))
for k,v in enumerate(C):
 rows=[json.loads(line) for line in (a.profiles/f'profile-{v}-96-no-trim.jsonl').read_text().splitlines()];r=next(r for r in rows if r['phase']=='contexts_retained')
 vals=[r['resident_bytes']/2**30,(r['in_use_bytes']+r['mmap_bytes'])/2**30,r['free_arena_bytes']/2**30]
 bars=axs[0].bar(np.arange(3)+(k-.5)*.36,vals,.34,color=C[v],label='Before' if v=='baseline' else 'After');axs[0].bar_label(bars,fmt='%.2f',fontsize=8,padding=3)
 axs[1].plot(['Before open','96 retained','After close'],[r['resident_bytes']/2**30 for r in rows],'o-',color=C[v],label='Before' if v=='baseline' else 'After')
axs[0].set_xticks(np.arange(3),['Resident RSS','Live allocated heap*','Free arena bytes*']);axs[0].set_title('Allocator state with 96 retained contexts');axs[0].legend();axs[1].set_title('Separate no-trim lifecycle diagnostic');axs[1].legend()
for ax in axs:ax.set_ylabel('GiB');ax.set_ylim(bottom=0);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
fig.suptitle('Root cause: freed footer-DOM allocations retained in worker arenas',fontsize=14);fig.text(.5,.01,'*mallinfo2 covers the whole process; arena counters are not physical RSS. Closing all objects need not return all free pages. No trim in these traces.',ha='center',fontsize=8);save(fig,'allocator-diagnostic')
