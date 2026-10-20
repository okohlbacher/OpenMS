from pathlib import Path
import subprocess,re,hashlib,json
root=Path(__file__).resolve().parents[3];repo=root/'OpenMS-libxml2';refs=['58aa37348c968a12e3285295f28c197cc0b7bdbe','8f66b3d921c9512e1e5968f494c77715ff71c696']
paths=['FORMAT/MzMLFile.h','FORMAT/XMLFile.h','FORMAT/OPTIONS/PeakFileOptions.h','FORMAT/HANDLERS/IndexedMzMLHandler.h','FORMAT/HANDLERS/MzMLSpectrumDecoder.h','FORMAT/DATAACCESS/MSDataWritingConsumer.h','KERNEL/OnDiscMSExperiment.h','KERNEL/MSExperiment.h','KERNEL/MSSpectrum.h','KERNEL/MSChromatogram.h','INTERFACES/IMSDataConsumer.h','INTERFACES/DataStructures.h']
rows=[]
def normalized(s):
 s=re.sub(r'/\*.*?\*/|//[^\n]*','',s,flags=re.S)
 return re.sub(r'\s+','',s)
for name in paths:
 full='src/openms/include/OpenMS/'+name;contents=[subprocess.check_output(['git','-C',str(repo),'show',ref+':'+full]) for ref in refs]
 if name=='FORMAT/XMLFile.h':
  # The only declaration changes are protected nonvirtual parser entry points;
  # the harness never calls those methods. No members/vtable slots change.
  assert normalized(contents[0].decode())==normalized(contents[1].decode().replace(', bool namespace_aware = false',''))
  note='Only protected nonvirtual parse/parseBuffer bool parameter added; fields and virtual destructor unchanged; not called by harness'
 else:
  assert normalized(contents[0].decode())==normalized(contents[1].decode()),name
  note='Same declarations/layout; comments may differ'
 rows.append({'header':name,'xerces_sha256':hashlib.sha256(contents[0]).hexdigest(),'complete_sha256':hashlib.sha256(contents[1]).hexdigest(),'audit':note})
(root/'results/full-scaling/harness-header-audit.json').write_text(json.dumps({'source_commits':refs,'scope':'Public storage/callback declarations used by timed harness; NOT a blanket ABI compatibility claim for all OpenMS XML APIs. General consumers must rebuild.','method':'Compare exact committed headers after stripping comments/whitespace; XMLFile exception manually restricted to two nonvirtual protected signatures. Actual linked-library selection and no direct Xerces dependency verified separately.','headers':rows},indent=2)+'\n');print('Audited',len(rows),'timed/client headers')
