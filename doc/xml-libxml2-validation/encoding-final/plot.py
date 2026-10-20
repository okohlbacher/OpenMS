from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
root=Path(__file__).resolve().parents[2];out=root/'results/encoding-final185/macos';data=json.loads((out/'summary.json').read_text());rows={(r['backend'],r['encoding'],r['mode']):r for r in data['results']}
backends=['xerces','libxml2-poc','libxml2-full'];labels=['Xerces\npublished snapshot','libxml2\npublished PoC','libxml2\ncomplete replacement'];colors=['#d78b30','#3979ae'];fig,axes=plt.subplots(2,2,figsize=(11,7.7))
for col,(mode,title) in enumerate([('stream','mzML streaming'),('indexed-metadata','Default indexed open')]):
 for row in [0,1]:
  ax=axes[row,col];x=np.arange(3)
  for i,encoding in enumerate(['ISO-8859-1','UTF-8']):
   selected=[rows[b,encoding,mode] for b in backends]
   ys=[r['seconds_median'] if row==0 else r['peak_rss_mib_median'] for r in selected]
   errors=([[r['seconds_median']-r['seconds_min'] for r in selected],[r['seconds_max']-r['seconds_median'] for r in selected]] if row==0 else None)
   bars=ax.bar(x+(i-.5)*.34,ys,.32,label=encoding,color=colors[i],yerr=errors,capsize=3,error_kw={'elinewidth':1})
   ax.bar_label(bars,labels=[f'{v:.2f}' if row==0 else f'{v:.1f}' for v in ys],padding=3,fontsize=8)
  ax.set_xticks(x,labels);ax.set_title(title if row==0 else title+' — process peak RSS');ax.set_ylabel('Seconds' if row==0 else 'MiB');ax.set_ylim(0,max(r['seconds_max'] if row==0 else r['peak_rss_mib_median'] for (b,e,m),r in rows.items() if m==mode)*1.18);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
axes[0,0].legend(frameon=False);fig.suptitle('M4 Max: declaration-only experiment with the complete replacement',fontsize=13)
fig.text(.5,.014,'1.05 GiB ASCII body; identical file size/index offsets. Median of 5 randomized runs; time whiskers min–max.\nOpen time excludes 2,048 queries; process peak RSS includes initialization and queries. Product implementation 1858656; guard/tests 8f66b3d.',ha='center',fontsize=8)
fig.tight_layout(rect=(0,.05,1,.95))
for ext in ['png','svg']:fig.savefig(out/('encoding-comparison.'+ext),dpi=180)
