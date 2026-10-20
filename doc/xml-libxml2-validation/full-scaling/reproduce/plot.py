from pathlib import Path
import json
import sys
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
root=Path(__file__).resolve().parents[3];base=root/'results/full-scaling';out=base/'figures';out.mkdir(exist_ok=True)
colors={'xerces':'#d98532','libxml2-full':'#287a9e'};labels={'xerces':'Xerces control','libxml2-full':'Complete libxml2 replacement'};workers=[1,2,4,8,16,32,64,96]
inputs=['large.mzML','medium-zlib.mzML'];titles=['1.05 GiB plain mzML','Binary-zlib mzML']
def load(name):return json.loads((base/'linux'/(name+'.json')).read_text())
def selected(data,b,f,m):return sorted([r for r in data['summary'] if r['backend']==b and Path(r['input']).name==f and r['mode']==m],key=lambda x:x['workers'])
def axis(ax):
 ax.set_xscale('log',base=2);ax.set_xticks(workers,[str(n) for n in workers]);ax.grid(alpha=.2);ax.set_axisbelow(True);ax.axvline(64,color='#999',ls=':',lw=.8);ax.set_xlabel('Independent readers')
def save(fig,name,caption):
 fig.text(.5,.012,caption,ha='center',fontsize=8);fig.tight_layout(rect=(0,.05,1,.95))
 for ext in ['png','svg']:fig.savefig(out/(name+'.'+ext),dpi=170)
 plt.close(fig)
if '--mac-only' not in sys.argv:
 primary=load('benchmarks');meta=load('metadata-scaling');memory=load('memory-scaling');omp=load('openmp-scaling')
 fig,axes=plt.subplots(2,3,figsize=(13,7.3))
 for i,(f,title) in enumerate(zip(inputs,titles)):
  for j,(data,mode,ylabel) in enumerate([(primary,'stream','Aggregate files/s'),(primary,'indexed','Random reads/s, including open'),(meta,'indexed-metadata','Per-reader metadata opening (s)')]):
   ax=axes[i,j]
   for b in colors:
    rr=selected(data,b,f,mode);ys=[r['workers']/r['seconds_median'] if mode=='stream' else r['workers']*2048/r['seconds_median'] if mode=='indexed' else r['job_open_seconds_median'] for r in rr]
    ax.plot([r['workers'] for r in rr],ys,'o-',color=colors[b],label=labels[b],ms=4)
   axis(ax);ax.set_ylabel(ylabel);ax.set_title(title+' — '+('stream' if j==0 else 'index-only random reads' if j==1 else 'default open'))
 axes[0,0].legend(fontsize=8);fig.suptitle('Complete replacement vs Xerces: Linux scaling through 96 readers',fontsize=13)
 save(fig,'linux-throughput','Median of 5 fresh processes per cell; OpenMP/BLAS=1. EPYC 7763:64 physical cores;96 includes SMT. Dotted line:64 cores.')
 fig,axes=plt.subplots(2,4,figsize=(15,7.2))
 for i,(f,title) in enumerate(zip(inputs,titles)):
  for j,(data,mode,name) in enumerate([(primary,'stream','Streaming'),(memory,'load','Whole load, retained'),(primary,'indexed','Index-only random reads'),(meta,'indexed-metadata','Default open + random reads')]):
   ax=axes[i,j]
   for b in colors:
    rr=selected(data,b,f,mode);ax.plot([r['workers'] for r in rr],[r['rss_mib_median']/1024 for r in rr],'o-',color=colors[b],label=labels[b],ms=4)
   axis(ax);ax.set_ylabel('Process peak RSS (GiB)');ax.set_title(title+'\n'+name,fontsize=10);ax.set_ylim(bottom=0)
 axes[0,0].legend(fontsize=8);fig.suptitle('Linux peak RSS: streaming, whole-document loads and parallel random reads',fontsize=13)
 save(fig,'linux-rss','Median of 5 wait4 peaks, including launch/startup; low-memory cells can include a driver RSS floor. Whole loads retained until workers finish.')
 contexts=json.loads((base/'linux/context-overhead.json').read_text())['results'];fig,axes=plt.subplots(2,2,figsize=(11.8,7.2))
 for i,(f,title) in enumerate(zip(inputs,titles)):
  for j,(mode,name) in enumerate([('contexts','Fast reader + index'),('contexts-metadata','Default reader + index + metadata')]):
   ax=axes[i,j]
   for b in colors:
    rr=sorted([r for r in contexts if r['backend']==b and Path(r['input']).name==f and r['mode']==mode],key=lambda r:r['workers'])
    for metric,style,short in [('resident_extra_mib_per_reader','-','retained'),('peak_extra_mib_per_reader','--','peak')]:ax.plot([r['workers'] for r in rr],[r[metric] for r in rr],marker='o',ls=style,color=colors[b],ms=3,label=labels[b]+' — '+short)
   axis(ax);ax.set_ylabel('Idle-adjusted MiB / reader');ax.set_title(title+'\n'+name,fontsize=11)
 axes[0,0].legend(fontsize=7);fig.suptitle('Linux per-reader context overhead: (RSScontexts − RSSidle) / N',fontsize=13)
 save(fig,'linux-context-overhead','Independent medians; reader/index/metadata/allocator state, not native XML context size. statm is approximate; low peak-RSS cells include launch floor.')
 fig,axes=plt.subplots(2,2,figsize=(11.8,7.2))
 for i,(f,title) in enumerate(zip(inputs,titles)):
  for b in colors:
   rr=sorted([r for r in omp['summary'] if r['backend']==b and Path(r['input']).name==f],key=lambda x:x['openmp_threads']);one=next(r['seconds_median'] for r in rr if r['openmp_threads']==1)
   axes[i,0].plot([r['openmp_threads'] for r in rr],[one/r['seconds_median'] for r in rr],'o-',color=colors[b],label=labels[b],ms=4)
   axes[i,1].plot([r['openmp_threads'] for r in rr],[r['rss_mib_median'] for r in rr],'o-',color=colors[b],label=labels[b],ms=4)
  for j in [0,1]:axis(axes[i,j]);axes[i,j].set_xlabel('Requested OpenMP threads; one reader');axes[i,j].set_title(title)
  axes[i,0].set_ylabel('Fixed-work speedup vs 1 thread');axes[i,0].axhline(1,color='#999',lw=.8);axes[i,1].set_ylabel('Process peak RSS (MiB)')
 axes[0,0].legend(fontsize=8);fig.suptitle('Single-file OpenMP scaling and RSS are separate from reader concurrency',fontsize=13)
 save(fig,'linux-openmp','Median of 5 processes. Post-run census at requested OpenMP=96:192 native process threads on both backends, including retained runtime teams.')
mac=json.loads((base/'macos/options-summary.json').read_text());md={(r['backend'],r['encoding'],r['mode']):r for r in mac['results']};bs=['xerces','full-homebrew','full-o2','full-o3','full-ascii-o3','discard-homebrew','discard-ascii-o3'];bl=['Xerces','Full\nbottle','Full\n−O2','Full\n−O3','Full\nASCII','Discard\nbottle','Discard\nASCII'];fig,axes=plt.subplots(2,2,figsize=(14,8))
for c,(mode,title) in enumerate([('stream','Streaming'),('indexed-metadata','Default indexed open')]):
 for row in [0,1]:
  ax=axes[row,c];x=np.arange(len(bs))
  for k,(e,color) in enumerate([('ISO-8859-1','#d98532'),('UTF-8','#287a9e')]):
   rr=[md[b,e,mode] for b in bs];ys=[r['seconds_median'] if row==0 else r['rss_mib_median'] for r in rr];errors=[[r['seconds_median']-r['seconds_min'] for r in rr],[r['seconds_max']-r['seconds_median'] for r in rr]] if row==0 else None
   bars=ax.bar(x+(k-.5)*.36,ys,.34,label=e,color=color,yerr=errors,capsize=2,error_kw={'elinewidth':.8});ax.bar_label(bars,labels=[f'{v:.2f}' if row==0 else f'{v:.0f}' for v in ys],padding=3,fontsize=7)
  ax.set_xticks(x,bl,fontsize=8);ax.set_ylabel('Seconds' if row==0 else 'Peak RSS (MiB)');ax.set_title(title+('' if row==0 else ' — entire process'));ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True);ax.set_ylim(bottom=0,top=ax.get_ylim()[1]*1.12)
axes[0,0].legend(fontsize=8);fig.suptitle('M4 Max: compiler controls and isolated converter / ignored-binary experiments',fontsize=13)
save(fig,'macos-options','Median of 5; time whiskers min–max. Open time excludes 2,048 queries; RSS includes initialization and queries. Private experiments are not shipped changes.')
size=json.loads((base/'macos/size-control-summary.json').read_text());sd={(r['backend'],r['encoding'],r['mode']):r for r in size['results']}
matched=json.loads((base/'macos/matched-native-summary.json').read_text());nd={(r['backend'],r['encoding'],r['mode']):r for r in matched['results']}
fig,axes=plt.subplots(2,2,figsize=(12.5,7.6))
for row,(d,backs,names,title) in enumerate([(sd,['full-homebrew','full-os','full-o2'],['Homebrew bottle','Local −Os','Local −O2'],'Matched libxml2 source: size vs speed optimization'),(nd,['xerces-bottle','xerces-native-o3','full-o3','discard-ascii-o3'],['Xerces bottle','Xerces native −O3','libxml2 native −O3','Private combination −O3'],'Native −O3 parser controls')]):
 for col,mode in enumerate(['stream','indexed-metadata']):
  ax=axes[row,col];xx=np.arange(len(backs))
  for k,(e,color) in enumerate([('ISO-8859-1','#d98532'),('UTF-8','#287a9e')]):
   rr=[d[b,e,mode] for b in backs];ys=[r['seconds_median'] for r in rr];errors=[[r['seconds_median']-r['seconds_min'] for r in rr],[r['seconds_max']-r['seconds_median'] for r in rr]]
   bars=ax.bar(xx+(k-.5)*.36,ys,.34,label=e,color=color,yerr=errors,capsize=2,error_kw={'elinewidth':.8});ax.bar_label(bars,labels=[f'{v:.2f}' for v in ys],padding=3,fontsize=8)
  ax.set_xticks(xx,names,fontsize=8,rotation=10);ax.set_title(title+'\n'+('streaming' if col==0 else 'default opening'),fontsize=11);ax.set_ylabel('Seconds');ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True);ax.set_ylim(0,ax.get_ylim()[1]*1.13)
axes[0,0].legend(fontsize=8);fig.suptitle('M4 Max: build configuration matters for both XML libraries',fontsize=13)
save(fig,'macos-build-controls','Separate randomized phases; compare within each panel. Median of 5; whiskers min–max. Opening excludes queries; exact bottle flags not recovered.')
if '--mac-only' not in sys.argv:
 encoding=load('encoding-followup');lg=defaultdict(list)
 for r in encoding['records']:
  e='UTF-8' if Path(r['input']).name=='large-utf8.mzML' else 'ISO-8859-1';lg[r['backend'],e,r['mode']].append(r)
 import statistics
 fig,axes=plt.subplots(1,2,figsize=(12.5,5));cases=[('Mac Latin-1','mac','ISO-8859-1'),('Mac UTF-8','mac','UTF-8'),('Linux Latin-1','linux','ISO-8859-1'),('Linux UTF-8','linux','UTF-8')]
 for ax,mode,title in zip(axes,['stream','indexed-metadata'],['Streaming','Default opening']):
  for i,(name,host,e) in enumerate(cases):
   if host=='mac':
    installed=md['full-homebrew',e,mode]['seconds_median']/md['xerces',e,mode]['seconds_median'];native=nd['full-o3',e,mode]['seconds_median']/nd['xerces-native-o3',e,mode]['seconds_median'];experiment=nd['discard-ascii-o3',e,mode]['seconds_median']/nd['xerces-native-o3',e,mode]['seconds_median']
    ax.bar(i-.25,installed,.23,color='#287a9e',label='Installed parser packages' if i==0 else None);ax.bar(i,native,.23,color='#d98532',label='Matched native −O3 parsers' if i==0 else None);ax.bar(i+.25,experiment,.23,color='#8462ad',label='Private Mac combination / native Xerces' if i==0 else None)
   else:
    key=lambda rr:statistics.median(r['seconds'] if mode=='stream' else r['jobs'][0]['open_seconds'] for r in rr)
    native=key(lg['libxml2-full',e,mode])/key(lg['xerces',e,mode]);ax.bar(i,native,.45,color='#d98532')
  ax.axhline(1,color='#444',ls='--',lw=1);ax.set_xticks(range(4),[x[0] for x in cases],rotation=15);ax.set_ylabel('Time / specified same-host Xerces control');ax.set_title(title);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
 axes[0].legend(fontsize=7);fig.suptitle('Encoding and build controls across platforms',fontsize=13)
 save(fig,'platform-encoding','Each series normalized to its matching same-host Xerces build. CPU/transcoder/compiler differ; private patches tested only on macOS.')
print('Figures generated')
