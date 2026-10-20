# Final review findings (benchmark harness only)

The core omp=1 reader, decoder and RSS numbers and the correctness gates look sound. Four issues remain that affect claims or labels, plus some low-severity notes.

## Medium / high

**1. libomp spin-wait invalidates CPU/wall as "active concurrency" for omp>1 cells, and may bias omp≥64 timings.**
- The launcher's `__KMP_REGISTERED_LIB_` handling shows the runtime is LLVM libomp. Its default `KMP_BLOCKTIME` is 200 ms, so idle team threads spin rather than sleep.
- Neither `BASE` nor `env()` sets `KMP_BLOCKTIME` or `OMP_WAIT_POLICY`, and the identity payload doesn't record them.
- Between MzMLHandler's parallel decode chunks, the serial XML parse almost certainly runs for less than 200 ms. So in `single-file-openmp` and `whole-document` omp=96 cells, the 95 team threads spin for most of the run.
- **Consequence:** `effective_cpu_equivalents` approaches the team size regardless of useful parallelism. It cannot be presented as active concurrency for these cells. It is still valid for omp=1 reader cells.
- At omp=96 on CPUs 0-95, the serial parse thread plus 95 spinners fully subscribe the set. Spinners on SMT siblings can slow the serial parse, which biases omp=64/96 wall times (both backends) toward worse scaling.
- **Fix:** relabel omp>1 CPU/wall as "CPU consumption including runtime spin-wait". Better, add a `KMP_BLOCKTIME=0` (or `OMP_WAIT_POLICY=passive`) sensitivity run for the omp>1 cells and record the setting in `BASE`/identity.

**2. `canonical_failures=0` is hardcoded, and most canonical failures are never logged.**
- `analyze.py` writes the constant without reading `failures.jsonl`.
- Only `require()` (non-zero exit or timeout) logs a failure. Fingerprint mismatches, `validate_backend` thread/map/affinity assertions and the `single-file-openmp` thread assertion all raise without writing anything.
- On resume, those cells are rerun silently. A retry-until-pass pattern would therefore be indistinguishable from a clean run, and the zero-failure claim is unsupported.
- **Fix:** log every per-cell exception (cell key plus row) before re-raising, and compute failures and attempts per cell from that log in `analyze.py`.

**3. `all-comparisons.csv` `seconds_median` mixes clocks without a basis column.**
- It is the C++ workload clock for C++ rows but the end-to-end process clock for `decompress` and `staged-pipeline` rows.
- Historical rows have whatever their phase used.
- `rss_measurement_basis` exists but there is no time equivalent. Any cross-row comparison taken from the combined CSV conflates clocks, which contradicts "kept separate".
- **Fix:** add a `seconds_basis` column (and set it for historical rows).

**4. The header audit omits the actual base classes of an object the binary constructs by value.**
- `generate()` stack-constructs `PlainMSDataWritingConsumer`. `MSDataWritingConsumer` derives from `Internal::MzMLHandler`, which derives from `Internal::XMLHandler`.
- In the Xerces commit, `XMLHandler` derives from `xercesc::DefaultHandler`, so its layout and vtable very likely differ in the libxml2 commit. The identical `MSDataWritingConsumer.h` hash does not cover this.
- `test-audit.py` runs `generate` under the default `libxml2-full` env. If the single harness binary was compiled against Xerces-commit headers, that fixture generation is ODR/ABI-unsafe.
- Timed paths don't call `generate`, so timings are unaffected. But the audit's "used by harness" scope and the generated IM fixture are not covered.
- **Fix:** state which commit's headers the binary was compiled against, run `generate` only under that backend, and add `XMLHandler.h` and `MzMLHandler.h` to the audit.

## Low

5. **No team-formation gate for omp=96 whole-document cells.** `whole-document` omp=96 cells lack the `threads >= omp+1` assertion that `single-file-openmp` has. "Large fixed OMP asserts actual threads" therefore doesn't cover `load`.

6. **pigz thread labels.** pigz decompression is single-threaded inflate plus at most read/write/check helper threads. The pigz `requested_threads` axis must not be described as decompression scaling; the recorded `sampled_native_threads` will show this.

7. **Cache evidence is weaker than it looks.**
   - Residency is checked only before each cell.
   - If `/scratch` is a network or parallel filesystem, `ru_inblock`/majflt do not count network reads, so zero inblock is not proof of a cache hit.
   - Inblock is not summarized for the decompress component of staged cells.
   - **Fix:** a post-cell `mincore` check would close this.

8. **Misleading field name for stream readers.** `idle_adjusted_retained_mib_per_reader` is also emitted for stream `readers`, where it measures post-join allocator residue rather than retained contexts. Rename it or restrict it to `retained-contexts`.

9. **Identity and provenance robustness (fails loudly; does not produce wrong numbers):**
   - `identity()` hashes `.so` paths sampled from `indexed-correctness.json`, which `run-access` main rewrites after its first bind. The maps union is sampling-dependent: pre-exec supervisor maps, refresh only every 10th sample. This can make the end-of-run identity assert fail after a full run.
   - The same sampling means the final-gates "no OpenMS libs in inflater maps" check would pass vacuously for a process never sampled after exec. This is fine for the multi-second gated runs.
   - `final-gates.py`, `test-audit.py`, `control-startup.py` and `analyze.py` are not in the hashed harness set.
   - `analyze.py` doesn't assert a single `measurement_identity_sha256` across `records.jsonl` and `access-records.jsonl`.
