
<invoke name="Write">
<parameter name="file_path">/Users/kohlbach/.claude/plans/adversarial-review-requested-by-zazzy-sutherland.md</parameter>
<parameter name="content"># Adversarial review: Linux XML gap-bench harness (pre-publication)

## Context
The user asked for an adversarial review before publishing the XML benchmark evidence. The review covers only measurement correctness, false-claim risk, data integrity, memory and thread accounting, validation gaps, and runner reliability. It reviews `reproduce/run-gap.py`, `reproduce/test-audit.py`, `staging/extended-benchmark-source/benchmark.cpp` and `staging/converter-source/convert_tims.cpp`. It requests no product-parser changes. The user's stated deliberate scope is accepted: cached-file throughput rather than cold storage, no FIFO or streaming claim, SHA checks only at 1/96, RATIONAL TIMS calibration, timed XSD out of scope, and the historical phase kept separate.

The outcome is a findings list ordered by severity, with a concrete fix for each finding. All fixes are harness-only or reporting-only.

## Verdict
Most of the design is sound. Specifically:
- Native VmHWM is read post-exec, so it correctly excludes the parent floor.
- Per-run digests are compared against a cross-backend reference.
- CRC is checked on every decompressor run.
- The sequential-RSS definition is honest.

Three issues could invalidate published numbers or the core claim of comparing identical builds (H1–H3). Several cheap assertions are missing for numeric claims that will be stated in the writeup (M-series).

---

## HIGH

**H1. The binary-swap comparison has unverified ABI and identity.**
- Evidence: a single `BINARY` (`extended-benchmark-build/xml_parser_benchmark`) runs against both snapshots. The only thing that changes is `LD_LIBRARY_PATH` in `env()`.
- Evidence: `benchmark.cpp` uses inline and header code from `MzMLFile`, `MSExperiment`, `OnDiscMSExperiment`, `PlainMSDataWritingConsumer` and `PeakFileOptions`.
- Risk: if the Xerces and libxml2 snapshots install different public headers, running one binary against the other `libOpenMS` is an ODR/ABI violation. Typical causes are `XMLFile`/handler layouts or Xerces-typed members. Digests matching does not rule out silent performance or behaviour effects.
- Identity gap: the identity check `str(ROOT/'snapshots'/backend/'lib') in r['openms_library']` uses the loader-reported path, not a realpath. Two symlinked snapshots that point to the same `.so` would pass it.
- Provenance gap: no hash is recorded for `BINARY`, `LAUNCHER`, the snapshot libs, `libxml2`, `libxerces`, the compiler flags, or the decompressor binaries.
- Fix:
  - Diff the two installed include trees and record the result. Alternatively, build the same `benchmark.cpp` once per snapshot against that snapshot's headers.
  - Record `realpath` and SHA-256 for every loaded `.so`, the benchmark, the launcher and the tools.
  - Record CMake build type and flags for both snapshots.
  - Write this as `manifest.json` in `audit()` and check it on every `run()` cell and on resume.

**H2. `process_seconds` is quantized by 50 ms polling and includes startup.**
- Evidence: in `measure()`, the loop does `wait4(WNOHANG)` followed by `time.sleep(.05)`, so exit is detected up to 50 ms late.
- Evidence: staged cells pay this twice, plus two process startups.
- Evidence: decompress cells have no native timer.
- Impact: rapidgzip at high `-P` on a roughly 1 GB `.gz` file can finish in under 1 s, which makes the error 5–15% or more. That is enough to fabricate apparent saturation in the scaling curves.
- Additional cost, to verify: if `decompress-env/bin/rapidgzip` is the PyPI console script, every run also includes Python interpreter startup and import, adding about 50–150 ms. Its VmHWM and thread counts would also include the interpreter.
- Fix:
  - Wait with `os.pidfd_open` and `select.poll(timeout=50)`, so the sampler wakes immediately on exit. Alternatively, do a blocking `wait4` in the main thread and sample from a side thread.
  - Record a per-tool zero-work baseline, such as an empty `.gz` file, every rep.
  - Report the tool type: native C++ CLI or Python wrapper.

**H3. The decompressor environment inherits OpenMS library paths, conditional on contents.**
- Evidence: `inflate()` calls `measure(cmd, env())`. `env()` puts `snapshots/libxml2-full/lib:dependencies/install/lib:contrib/build/lib` first on `LD_LIBRARY_PATH`.
- Risk: OpenMS dependency and contrib trees commonly ship a `libz.so.1`. If they do here, `/usr/bin/pigz`, rapidgzip and Python's zlib bind to that zlib, not the system zlib. pigz inflate is zlib's `inflateBack`.
- Blind spot: the maps filter only keeps `libOpenMS`, `libxerces` and `libxml2`, so this binding would never be visible.
- Fix:
  - Give decompressors a clean environment without OpenMS paths.
  - Capture all mapped `.so` files, at least `libz`, `libisal`, `libgomp`, `libstdc++` and `libc`, for every run.
  - Record which zlib OpenMS's internal gzip uses, because the internal-gzip-versus-pigz comparison depends on it.

---

## MEDIUM

**M1. Failures are never recorded, and resume can silently mix configurations.**
- In `run()`, `require()` raises before `f.write`, so failed or timed-out cells leave no row. The `if r['ok']` filter is therefore dead code, and the failure rate cannot be reported.
- Records carry no config or manifest hash. A resumed run can reuse rows produced by an older binary or older snapshots.
- A truncated final JSONL line makes `json.loads` crash on resume.
- Fix:
  - Write the row with `ok=false` first, then raise.
  - Add a manifest hash to each record and to the resume key.
  - Tolerate or truncate a partial final line.

**M2. Cache residency behind the "cached-file" label is asserted, not measured.**
- About 4 GB+ plain inputs, 1.45 GB PASEF, `.gz` files and a roughly 4 GB tmpfs staged file all compete for RAM. Nothing proves inputs are resident at cell start; this is weakest in rep 0 and after a resume.
- `os.wait4` usage is available, but `ru_inblock` and `ru_majflt` are discarded.
- The filesystem type of `/scratch` is not recorded. Client caching on Lustre/GPFS behaves differently.
- Fix:
  - Store `ru_inblock`, `ru_majflt`, `ru_minflt`, `ru_nvcsw` and `ru_nivcsw` on every row.
  - Flag or reject cells with `ru_inblock > 0`.
  - Record `findmnt` for ROOT and SHM.
  - Optionally run `fincore`/`vmtouch` before each cell.

**M3. The topology claim is unverified, and >64 threads means SMT.**
- The claim "0-95 = 64 physical + 32 SMT" is never checked. On a dual-socket 7763, 0-95 would instead be 96 physical cores across two NUMA nodes. NPS mode is also unrecorded.
- Threads are unpinned inside 0-95. For N ≤ 64, sibling co-scheduling can still happen.
- The Python harness itself (20 Hz sampler plus monitor) is unpinned and runs on the measured CPUs.
- Fix:
  - Record `lscpu`, `/sys/devices/system/cpu/cpu*/topology/thread_siblings_list`, `numactl -H`, and governor/boost state.
  - Pin the harness with `os.sched_setaffinity(0, {96..127})`.
  - Label every point above 64 as SMT; never present it as core scaling.

**M4. The "requested vs actual" thread census is not native, and is only asserted at 96.**
- The binary emits only `requested_openmp_threads`. "Actual" is a procfs-sampled lower bound, and only the census cells at 96 assert it.
- Pool threads in the count do not prove concurrent work.
- Fix:
  - After the run, have the benchmark execute a probe `#pragma omp parallel` with `requested_team` and emit `omp_get_num_threads()`. This is a harness change, not a parser change.
  - Report `(user+sys)/wall` as the effective-parallelism metric on every row.
  - For OpenMP cells, assert `sampled_threads <= omp+3`.
  - For decompressors, report actual threads rather than `-p`/`-P`.

**M5. The environment is inherited wholesale.**
- `BASE = os.environ.copy()` leaks the caller's `OMP_THREAD_LIMIT`, `OMP_PROC_BIND`/`PLACES`, `GOMP_*`, `MALLOC_*`, `LD_PRELOAD` and similar variables.
- Fix: build the environment from a whitelist, assert there is no `LD_PRELOAD`, and dump the effective environment into the manifest.

**M6. Throughput denominators are ambiguous.**
- For `.gz` readers, `file_bytes` is the compressed size.
- Plain and internal-zlib files hold identical content but have different byte counts.
- Decompress cells only have `process_seconds`, while OpenMS cells also have native `seconds`.
- Fix:
  - Report decompressed-XML bytes per second and points (or spectra) per second as the primary metric for all inputs.
  - Never divide native `seconds` and process `process_seconds` against each other in one comparison.

**M7. Mobility audit gaps.**
- Precursor-level ion mobility (`Precursor::getDriftTime` / `selectedIon` 1/K0) is not hashed. For PASEF MS2 this is the main mobility carrier.
- Integer and string data arrays are not hashed.
- The assertion `im_array_values>0 or im_scalar>0` is weak; a few values would pass.
- The claim "published PASEF without mobility" is not asserted.
- The 600–1200 s RT range of the subset is not reported.
- Fix:
  - Hash precursor mobility, m/z and charge in the aux digest.
  - Assert `im_array_values == points` for TIMS frames, or report the fraction.
  - Assert IM count `== 0` for `pasef-published`.
  - Emit min/max RT and spectrum count per MS level for the subset.

**M8. Stated numeric claims have no assertion.**
- The claims "131072×2048" and "all actual files ≥1 GB" are not checked. The outer gzip of the internal-zlib file could plausibly land near 1 GB.
- Fix: in `audit()`:
  - assert `spectra_per_worker == 131072`;
  - assert `points_per_worker == 131072*2048 + 131072` (spectrum points plus the TIC chromatogram);
  - assert `stat().st_size >= 1e9` (or `2**30`, with the unit stated) for the four synthetic files.

**M9. "Independent readers" are in-process threads on one inode.**
- All N workers are threads in one process. They share the malloc arenas, parser globals, the CV singletons, and one page cache over one inode.
- Same-file lockstep reads can inflate aggregate throughput through LLC and DRAM reuse, or deflate it through contention on the inode's page cache.
- Fix: word the claim as "N concurrent in-process readers of the same cached file". Optionally add a control with N distinct copies on DDA 617 MB (N=96 needs about 59 GB) at N ∈ {1,16,64,96}.

**M10. The launcher is unreviewed but load-bearing.**
- procfs sampling, `kill()` on timeout and the maps capture all assume `LAUNCHER` execs into `BINARY`. If it forks, samples and kills hit the wrong process, and a timeout leaves an orphan running during later cells.
- Only the four census cells indirectly detect a fork.
- Fix:
  - Assert `os.readlink(f'/proc/{pid}/exe')` equals the expected binary once a sample shows more than one thread.
  - Kill the process group, using `start_new_session=True` and `os.killpg`.
  - Provide the launcher source for review.

---

## LOW

- **L1.** `output_bytes` is 0 on every decompress-only row, because it is the `stat` of `/dev/null`. Drop the field or record a counted byte total.
- **L2.** `maps` and `cpu_affinity` are captured only when `threads>1`, so they are missing for gzip and pigz `-p1`. Capture them on the first sample where `/proc/pid/exe` is the target, and assert affinity `== '0-95'`.
- **L3.** The parent-floor test only asserts `native < wait4`, which could flake. Assert `wait4 >= 128 MiB + baseline` and `native <= wait4 - 64 MiB`.
- **L4.** Bind audit to run: re-hash `inputs.json` and the manifest at the end of `run()` before writing `MATRIX_COMPLETE`.
- **L5.** Decompress-only cells write to `/dev/null`, while the staged first stage writes to tmpfs. Do not reuse decompress-only times as staged stage-1 times.
- **L6.** Staged cells don't assert `p['openms_library']` matches the snapshot. Readers and OMP cells do.
- **L7.** The pigz 1..96 sweep is mostly redundant, since there is one inflater. Keep it, but do not plot it as scaling.
- **L8.** The "no simultaneous builds" rule is only a docstring. Add a pre-cell gate: abort or flag if 1-minute loadavg exceeds a threshold, or if compiler or conversion processes exist.
- **L9.** Rename the CLI-row fields `sampled_native_*` to `sampled_procfs_*`, to avoid confusion with native C++ VmHWM.
- **L10.** Record pigz, gzip and rapidgzip versions, the `.gz` creation tool and level, and upstream accessions and checksums for the real datasets.

## Verified correct (no action)
- Native VmHWM is read from `/proc/self/status` after exec. A new mm resets hiwater, so the Python fork/vfork floor is correctly excluded. `wait4` is retained raw.
- The CLI procfs VmHWM sample is a genuine lower bound. VmHWM, not VmRSS, is sampled, so only post-last-sample growth is missed.
- The fingerprint is checked on every reader, OpenMP and staged run, and cross-backend equality is asserted in audit.
- The binary asserts that all workers produce identical digests.
- The aux flag does not perturb the base hash.
- Full SHA checks run at 1/96 against the plain originals, and `--verify` and CRC are checked on every run.
- The IM-only mutant test (`test-audit.py`) does change only the aux digest, and both backends agree.
- The census `(1,96)`/`(96,1)` thread bound of 96–100 correctly matches main + worker + 95 pool threads, or main + 96.
- The staged RSS definition and the no-FIFO/no-streaming wording are consistent with the code.

## Verification of fixes (when executed)
1. Run `test-audit.py` with these additions:
   - a forced-fail cell that must appear in `records.jsonl` with `ok=false`;
   - a check that the manifest hash mismatch on resume aborts;
   - a pidfd timing check, where `sleep 0.123` measures 0.123 ± 0.005 s.
2. Run `audit()`:
   - the M8 size and count asserts pass;
   - the manifest lists distinct realpaths and hashes per snapshot;
   - the header-diff result is recorded;
   - the decompressor maps show the intended `libz`.
3. Run a short `run()` smoke subset (1 rep, N ∈ {1,96}):
   - rows contain `ru_inblock==0` and a probe OMP team equal to the requested size;
   - `(user+sys)/wall` is plausible;
   - the harness PID affinity is 96–127.
</parameter>
</invoke>
YYPAYLOAD_PLACEHOLDER
<invoke name="ExitPlanMode">
</invoke>
