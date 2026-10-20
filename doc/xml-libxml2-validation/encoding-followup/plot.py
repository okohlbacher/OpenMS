from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
root=Path(__file__).resolve().parents[2];out=root/'results/encoding-followup/macos';data=json.loads((out/'summary.json').read_text());rows={(r['backend'],r['encoding'],r['mode']):r for r in data['results']}
backends=['xerces','libxml2-poc','libxml2-full'];labels=['Xerces\npublished snapshot','libxml2\npublished PoC','libxml2\nfull replacement'];colors=['#d78b30','#3979ae'];fig,axes=plt.subplots(1,2,figsize=(11,4.4))
for ax,mode,title in zip(axes,['stream','indexed-metadata'],['mzML streaming','Default indexed open (metadata scan)']):
 x=np.arange(3)
 for i,encoding in enumerate(['ISO-8859-1','UTF-8']):
  selected=[rows[b,encoding,mode] for b in backends];ys=[r['seconds_median'] for r in selected];low=[r['seconds_median']-r['seconds_min'] for r in selected];high=[r['seconds_max']-r['seconds_median'] for r in selected]
  bars=ax.bar(x+(i-.5)*.34,ys,.32,label=encoding,color=colors[i],yerr=[low,high],capsize=3,error_kw={'elinewidth':1})
  ax.bar_label(bars,labels=[f'{v:.2f}' for v in ys],padding=3,fontsize=8)
 ax.set_xticks(x,labels);ax.set_title(title);ax.set_ylabel('Seconds (lower is better)');ax.set_ylim(0,max(r['seconds_max'] for (b,e,m),r in rows.items() if m==mode)*1.18);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
axes[0].legend(frameon=False);fig.suptitle('M4 Max: changing only the encoding declaration removes much of the libxml2 penalty',fontsize=12)
fig.text(.5,.01,'1.05 GiB ASCII body; identical file size/index offsets. Median of 5 randomized runs; whiskers min–max. Open excludes 2,048 queries.',ha='center',fontsize=8)
fig.tight_layout(rect=(0,.045,1,.93))
for ext in ['png','svg']:fig.savefig(out/('encoding-comparison.'+ext),dpi=180)
