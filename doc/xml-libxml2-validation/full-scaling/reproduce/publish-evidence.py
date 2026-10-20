"""Curate immutable measurement evidence after the successful Linux copy."""
from pathlib import Path
import gzip,json,shutil
root=Path(__file__).resolve().parents[3];src=root/'results/full-scaling';dest=root/'OpenMS-libxml2/doc/xml-libxml2-validation/full-scaling'
assert (src/'linux/PIPELINE_EXIT_STATUS').read_text().strip()=='0'
assert json.loads((src/'linux/analysis.json').read_text())['process_records']==2280
assert json.loads((src/'linux/transport-verification.json').read_text())['all_match']
dest.mkdir(parents=True,exist_ok=True)
def copy(p,d,compress=False):
 d.parent.mkdir(parents=True,exist_ok=True)
 if compress:
  with d.with_name(d.name+'.gz').open('wb') as raw:
   with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as out:out.write(p.read_bytes())
 else:shutil.copyfile(p,d)
for n in ['REPORT.md','MACOS_OPTIONS.md','all-comparisons.csv','table-provenance.json','harness-header-audit.json','harness-source-manifest.json','throughput-section.md']:copy(src/n,dest/n)
for folder in ['figures','reproduce']:
 for p in (src/folder).iterdir():
  if p.is_file() and p.suffix in ['.py','.sh','.json','.patch','.svg','.png']:copy(p,dest/folder/p.name)
if (src/'throughput').is_dir():
 for p in (src/'throughput').iterdir():
  if p.is_file():copy(p,dest/'throughput'/p.name)
for p in (src/'linux').rglob('*'):
 if not p.is_file() or p.name.endswith('.pyc'):continue
 relative=p.relative_to(src/'linux');compress=p.suffix in ['.log','.txt'] or (p.suffix=='.json' and p.stat().st_size>250000)
 copy(p,dest/'linux'/relative,compress)
for p in (src/'macos').iterdir():
 if not p.is_file() or p.suffix not in ['.json','.csv','.patch','.log','.gz']:continue
 # Publish the final candidate and retained failure controls, excluding a discarded intermediate handler candidate.
 if p.name=='experimental-openms-tests.log':continue
 copy(p,dest/'macos'/p.name,p.suffix=='.log' or (p.suffix=='.json' and p.stat().st_size>250000))
review=root/'replacement-review/macos-options'
for n in ['input-manifest.json','codex-caller-review.md','claude-findings.md','claude-review-run.json','kimi-review-output.txt','kimi-review-run.json']:
 copy(review/n,dest/'reviews'/n)
(dest/'README.md').write_text('''# Complete-replacement scaling evidence\n\nSee [the report](REPORT.md), [macOS options](MACOS_OPTIONS.md), [all comparisons](all-comparisons.csv) and [figures](figures/). The Linux production source is `8f66b3d921c9512e1e5968f494c77715ff71c696`; private macOS experimental patches are explicitly identified and are not shipped changes.\n\nEvery final cell has five fresh-process repetitions. The new phase contributes 2,280 Linux and 280 macOS performance records. Historical summary cells are retained unchanged in the combined table; source/build identities separate the phases. Whole-workload and dedicated opening-phase seconds are different columns.\n\nRaw matrices and large logs are deterministically gzip-compressed. Decompress a `.json.gz` to its original `.json` name before analysis. Linux `transport-verification.json` checks every copied result/log against the remote manifest before scratch cleanup; `cleanup.json` records removal of only the dedicated task-owned root. The parent SHA256SUMS covers published files and may differ from transport hashes for compressed representations.\n\nReproduction scripts retain the original workspace and scratch layout. Restore this directory to `results/full-scaling/` in a workspace containing `OpenMS-libxml2/`, the historical benchmark sources/data, and required dependencies; adjust explicit node/root paths for a new run. `source-input-manifest.json` pins source/input/archive identities and includes a public base plus `xerces-optimized.patch` to reproduce the optimized control. Official dependency archives and their hashes are in the preparation script. Linux builds use private dependencies and read-only shared contrib. macOS experiments require the recorded Homebrew libraries, native builds, frozen benchmark executable and original OpenMS build objects for the isolated handler re-link. No binaries, objects, private reviewer stderr or credentials are published.\n\nContext overhead is an idle-adjusted process estimate including retained reader/index/metadata and allocator state. It is not the byte size of a libxml2 parser context; sampling after worker joins excludes live worker stacks. Independent-reader scaling and single-reader fixed-work OpenMP are separate matrices; 96 readers on this node include SMT.\n\nPrivate-patch review receipts: Codex reviewed the actual caller/fallback contract; Kimi and Claude Opus 5.5 independently reviewed both isolated candidates. Unsupported partial buffer overlap and duplicated skip predicates remain limitations. The report discloses the native Xerces DOMTest failure reproduced with the installed bottle.\n''')
print('Curated',sum(p.is_file() for p in dest.rglob('*')),'files')
