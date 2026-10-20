# Compact native comparison: independent interpretation

The five compact runs and five fresh cap64 reference runs passed closure checks. Each complete-file run matched all three scientific export hashes, byte sizes and row counts. Compact native manifest: `9b2fdcef1af239bef0974e75def935edcb3c294da53db1e6c3e014f3689f2bc1`; reference manifest: `4f35f6e726ab098e0f603216bf099ad9dbbdf27643122ebd8f802867ce6c4189`. Raw GNU CPU/RSS/fault/context metrics agree with each run result; precise walls come from the protected monotonic harness interval, with the rounded GNU elapsed value independently checked.

| Physical cores requested | Reference wall s | Compact wall s | Wall reduction | Reference RSS GiB | Compact RSS GiB | RSS reduction |
|---:|---:|---:|---:|---:|---:|---:|
|16|63.560|63.308|0.40%|7.188|5.277|26.59%|
|32|37.177|36.268|2.44%|12.627|8.957|29.07%|
|64|27.940|26.256|6.03%|23.241|16.399|29.44%|
|128|27.535|25.747|6.49%|26.493|19.114|27.85%|
|192|27.897|26.080|6.51%|29.066|21.574|25.77%|

The clearest measured effect is memory: maximum RSS falls by 25.77–29.44% across the five widths. The stride changes from 48 to 32 bytes, but total RSS includes other containers, outputs, reserve slack and allocator retention; a one-third payload change cannot be equated to a one-third process-memory change. The measurements are consistent with substantial peak-payload savings without requiring an unmeasured cache explanation.

Wall reductions increase from 0.40% at 16 cores to about 6.0–6.5% at 64–192. System CPU falls 22.75–28.20% at all five widths. At 64/128/192 the reference system times 243.80/245.28/250.50s become 185.76/186.38/186.21s, while user CPU falls only 1.25/1.17/0.96%. Total charged CPU drops 5.73/5.57/5.62%. At 16, total charged CPU instead rises 0.19% despite lower RSS and system CPU. That asymmetry argues for reporting memory savings separately from arithmetic throughput.

Voluntary context-switch counts decrease in all five comparisons: at 64/128/192, 270,650/260,423/301,374 become 195,463/187,355/185,393. Involuntary switches do not show a uniform improvement (some widths increase). Minor faults fall 18.54–26.34%; major faults vary in both directions. These whole-process counts cannot identify exact wait durations, allocator locking or cache misses. They support lower kernel activity as an observed accompaniment, not a proved mechanism.

Compact storage does not restore scaling beyond 64. The compact wall times at 64/128/192 are 26.256/25.747/26.080s: little additional gain, followed by a small reversal in this single measurement. Both treatments deliberately cap MS1 at 64 workers; only other phases, including MS2, can use the larger requested team. The baseline diagnostic shows MS1 dominates spectral wall time and that MS2 has a separate tail. Native compact runs contain no equivalent per-phase instrumentation, so the observed end-to-end improvement must not be assigned exactly to MS1, MS2, copy work or scheduling.

The comparison uses the same physical-core prefixes, no SMT, detailed outputs, warmed input, OpenMP settings and external runtime hashes. All 157 compact capture members and 25 source/header copies were locally rehashed. Producer before/after source/runtime/input identities close. The large output TSVs, original input and remote ELF/object contents are represented by producer hashes rather than a new local rehash.

There is one measurement per treatment and width, in serialized non-adjacent cohorts. These are descriptive observed differences, not replicated estimates or significance claims. The experiment combines field reordering, packing and getter/setter migration, without a 40-byte reordered wide-integer control. No hardware cache-miss, bandwidth, IPC or NUMA measurement isolates those mechanisms. No new one-core timing, parallel-efficiency or Karp–Flatt curve is inferred. Native measurements use immutable R2; the final two-file whitespace delta is separately source-bound.
