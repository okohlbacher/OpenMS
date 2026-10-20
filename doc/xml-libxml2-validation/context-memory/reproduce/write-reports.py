from pathlib import Path
import json
root=Path('OpenMS-libxml2/doc/xml-libxml2-validation/context-memory');a=Path('results/context-memory/final-analysis');s=json.loads((a/'summary.json').read_text());long=json.loads((a/'sustained-comparisons.json').read_text());c=json.loads((a/'comparisons.json').read_text())
names=['large-matched-plain.mzML','large-matched-zlib.mzML','dda-lumos.mzML','pasef-published.mzML','pasef-im-600-1200s.mzML'];labels=['Matched plain','Matched internal zlib','Real Lumos DDA','Published PASEF','Real TIMS IM'];label=dict(zip(names,labels))
def row(mode,name,v,n):return next(r for r in s if r['mode']==mode and r['input']==name and r['version']==v and r['workers']==n)
memtable='| Input | Retained MiB/reader, before → after | Reduction | 96-reader random-read peak MiB, before → after | Post-read residue MiB, before → after |\n|---|---:|---:|---:|---:|\n'
for name,title in zip(names,labels):
 b=row('contexts',name,'baseline',96);f=row('contexts',name,'candidate',96);br=row('indexed-sync',name,'baseline',96);fr=row('indexed-sync',name,'candidate',96);x=next(r for r in c if r['mode']=='contexts' and r['workers']==96 and r['input']==name)
 memtable+=f"| {title} | {b['idle_adjusted_retained_mib_per_reader']:.1f} → {f['idle_adjusted_retained_mib_per_reader']:.1f} | {x['reduction_percent']:.1f}% | {br['peak_rss_mib_median']:,.0f} → {fr['peak_rss_mib_median']:,.0f} | {br['resident_rss_mib_median']:.0f} → {fr['resident_rss_mib_median']:.0f} |\n"
maxslower=max(100*(1/r['worker_read_seconds_speedup']-1) for r in long);maxfaster=max(100*(r['worker_read_seconds_speedup']-1) for r in long)
report=f'''# Retained-context memory and indexed-read follow-up

Product source: `ac0e80acbe46102e0305a672c07bc38a81f3f164`, compared with the previous complete libxml2 replacement (`8f66b3d9`, code-identical to publication `441ac13`). **Linux checks through96 readers are complete.** This changes footer traversal; streaming, whole-document loads and decompression were not rerun.

At96 retained readers, memory per reader falls **72–87% on four inputs**. The small IM footer keeps the original path and its memory stays unchanged. The implementation uses the existing DOM for wrapped footers≤2MiB and forward-only `xmlTextReader` above that bound. It requires libxml2 READER support. There is no allocator tuning or trim call in OpenMS.

{memtable}
Retained estimates subtract same-N idle RSS and include index/allocator state. Indexed peaks cover the complete short-loop workload. Post-read residue is sampled after readers are destroyed; **the lower active footprint does not guarantee lower RSS after closing**. In the plain case that residue rises from52 to962MiB. Separate no-trim probes show freed arena bytes rather than live parser objects; this tradeoff remains visible.

![Memory at96 readers](figures/memory-at-96.png)

The final **15 paired sustained settings** use8192 queries/reader (IM2048), three fresh processes per role. Query-loop time is at most **{maxslower:.1f}% slower** than baseline across those settings; the largest throughput gain is{maxfaster:.1f}%. These descriptive medians pass the5% investigation gate, but are not a proof of equivalence on other inputs or allocators. IM checks include1/32/64/96 readers. Five23–100ms short-loop flags received longer confirmations at their exact original CPU placement; every repetition is retained.

Opening and closing must be distinguished from query loops. In the fixed-physical-mask confirmations, complete open/read/close workloads are1.52× faster for DDA64 and1.21× for PASEF64, yet their **global read phase including teardown/join is34% and18% slower**, respectively. Plain96 complete-workload throughput is4.07× higher. The full clocks, ranges, CPU masks and outcomes are in the [details](DETAILS.md) and [combined table](all-comparisons.csv).

![Paired sustained reads](figures/sustained-indexed-speed.png)

The all-reader-only attempt was rejected: it saved memory on IM too but slowed sustained IM loops. Buffer-copy removal and packed-ID alternatives also remain separately recorded. The2MiB cutoff is a bounded compromise demonstrated on these files, not an adaptive or universally optimal rule.

**Validation:** seven Linux and four macOS focused suites pass, plus20 independent footer controls on each platform. Complete index IDs/order/offsets and sampled query digests agree;9,307 archived source files, actual compiled/committed file hashes, mapped libraries, cached inputs, native exits and schedules were verified. Codex, Kimi and Claude Opus5.5 reviews are [retained with dispositions](review/DECISIONS.md). This is222 fresh final measurements plus132 unchanged baseline records:354 selected records/118 cells. Controls, rejected iterations and the stopped affinity pilot are separate.

The [one combined table](all-comparisons.csv) has **3,674 cells**, preserving the previous3,488 macOS/Linux cells and labeling every new accepted/rejected phase. Prior [macOS build/encoding evidence](../gap-bench/REPORT.md) stays separate: no new macOS performance, compressed-data, whole-load or decompression measurement is claimed for this source. Windows, sanitizers, minimum-version execution, cold I/O and other IM encodings remain untested here; the old full747/746-suite results belong to the earlier source.

[Memory scaling graph](figures/context-memory-scaling.png) · [Allocator/lifecycle graph](figures/allocator-diagnostic.png) · [Detailed findings](DETAILS.md) · [Methods and reproduction](reproduce/README.md)
'''
(root/'REPORT.md').write_text(report)
details='''# Detailed targeted results

All numbers below summarize three fresh processes per cell. Whole-workload seconds, global synchronized reads including close/join, and per-worker query loops have different boundaries. The per-process median worker time is summarized across the three processes. Ratios of medians are descriptive, not significance tests. The final primary phase uses the reused baseline's0–95 CPU mask at every N; sustained rows explicitly identify their own placement. The96-CPU set contains64 physical cores plus32 SMT siblings.

## Retained context and indexed RSS at96

'''+memtable+'''
Whole streaming/load/decompression results remain in the unchanged [previous handoff](../gap-bench/REPORT.md), with their own older product source. These numbers are current before/after libxml2 comparisons, not a fresh current-source Xerces comparison.

## Per-reader context scaling

| Input | Readers | Before MiB/reader | After MiB/reader | Reduction |
|---|---:|---:|---:|---:|
'''
for name in names:
 for n in [1,32,64,96]:
  x=next(r for r in c if r['mode']=='contexts' and r['input']==name and r['workers']==n)
  details+=f"| {label[name]} | {n} | {x['before_mib_per_reader']:.2f} | {x['after_mib_per_reader']:.2f} | {x['reduction_percent']:.1f}% |\n"
details+='''
![Context scaling](figures/context-memory-scaling.png)

## Sustained read confirmations

Speedup is baseline time / final time;>1 is faster. The query-loop column excludes open/barriers/destruction. The global read-phase column includes destruction/join. Masks are allowed CPUs, not a claim of pinned per-worker placement. `0..N-1` uses physical CPUs through64; `0..95` matches the original primary placement. No rows with different masks/query lengths are pooled.

| Input | Readers | CPU mask | Query-loop speedup | Global read + close speedup | Complete workload speedup |
|---|---:|---|---:|---:|---:|
'''
for r in sorted(long,key=lambda r:(names.index(r['input']),r['workers'],r['cpu_placement'])):
 details+=f"| {label[r['input']]} | {r['workers']} | {r['cpu_placement']} | {r['worker_read_seconds_speedup']:.3f}× | {r['synchronized_read_seconds_speedup']:.3f}× | {r['seconds_speedup']:.3f}× |\n"
details+='''
## Mechanism and rejected alternatives

On the plain96-reader no-trim diagnostic, baseline resident RSS is9.81GB with about1.15GB live allocations and8.63GB free arena bytes. The final candidate is1.55GB resident with the same live allocation total and0.37GB free arena bytes. After destroying readers, baseline is52.6MB and final487.5MB (about448.5MB free arenas). These are individual diagnostic processes rather than the canonical three-run context medians; do not replace one counter/phase with another. Glibc arena history varies with scheduling. The larger final post-close residue is allocator retention, not a guarantee of a leak or a promise that the OS immediately receives freed pages.

The initial all-reader implementation cut retained IM RSS but caused substantial sustained query-loop regressions and many more minor page faults. A getter buffer-copy experiment did not fix it. Contiguous packed IDs, including a preallocation variant, preserved loops but left much larger retained RSS. Exact sources, review findings and their failed/diagnostic results remain archived. Fixed malloc-threshold probes disable glibc's normal dynamic heuristics and were not adopted. No fastest-repetition or fastest-candidate result is substituted into the final phase.

The selected strategy restores the original DOM path only below a2MiB wrapped-footer bound, avoiding the observed small-IM allocator/read-loop regression; large indices use the reader path. Actual tails are about1.63MB IM,2.17MB PASEF,4.69MB DDA and6.38–6.41MB generated. The threshold includes the14-byte artificial wrapper/newline. A different acquisition, spectrum size, allocator or library version may need further evaluation. IM still has roughly17.7MiB retained overhead per reader, so its previous Xerces memory advantage remains a historical comparison, not solved here.

![Allocator diagnostic](figures/allocator-diagnostic.png)

## Evidence boundaries and gates

The final selected324-record initial stage is132 reused baseline plus192 fresh final processes. Five final primary short-loop flags triggered30 further fresh confirmations at the same primary CPU placement, making354 selected records/118 cells. Both stages have complete identities, schedules, native exit checks, cache gates and every repetition. Untimed controls, allocator probes, all-reader/copy/packed rejected versions, and the stopped wrong-affinity pilot are kept separate. The table retains those rejected summary cells with explicit labels and source identities.

The final source is checked against all9,307 regular archived files with only decoder, decoder tests and READER CMake discovery changed. The actual compiled hashes match the committed blobs. Source/input/native harness/mapped DLL identities stay unchanged over timings; complete offset-vector fingerprints match both versions on all five files. SDK footer controls pass20/20 per platform for small/large paths, malformed tail/junk/NUL, duplicates, truncation, conversion/XML error precedence, namespaces/entities/CDATA/nested content and missing IDs. The proposed trailing-junk reader defect was not reproduced on2.15.4. Product output vectors now stay unchanged on failure; alias last-type behavior is preserved. Final seven/four focused suites are not a rerun of the previous full Linux/macOS747/746 suites.

[Raw evidence](raw/) · [Accepted phase summary](summary.csv) · [Sustained summary](sustained-summary.csv) · [All platforms/phases](all-comparisons.csv) · [Reproduction](reproduce/README.md) · [Review decisions](review/DECISIONS.md)
'''
(root/'DETAILS.md').write_text(details)
