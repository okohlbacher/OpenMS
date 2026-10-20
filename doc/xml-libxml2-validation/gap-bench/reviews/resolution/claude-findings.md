## Final resolution review

**No blocking measurement or identity errors remain in the supplied material.** Your two rebuttals to Kimi hold.

### Confirmed resolved

- **XML pruning.** `e.clear()` and parent removal sit inside the `spectrum` end branch, and only `stack.pop()` runs unconditionally. Scan and precursor descendants are still intact when each spectrum is audited, so Kimi's finding came from misread indentation.
- **RSS floor.** The control numbers are consistent with Linux 6.8 `exec_mmap` folding the old mm's high-water mark into `signal->maxrss`:
  - native VmHWM is 39.4 MB;
  - native-supervisor wait4 is 39.8 MB, roughly 400 KB of pre-exec floor;
  - outer Python wait4 is 154 MB, the forked Python image.

  Asserting that the outer RSS equals the native RSS would be wrong, and you were right not to apply it.
- **Identity mutability.** The frozen path list is separate from the regenerated audit, and the rewrite test shows the identity hash is unchanged. Resume compares parsed dicts, so key order does not matter.
- **Per-cell exceptions.** `BaseException` is caught, logged with fsync, and re-raised. Interrupts and `SystemExit` are recorded and are never swallowed.
- **SDK-matched regeneration.** Both XML inputs regenerate byte-identically (`bbd284fb…`, `4982dbc3…`), which closes the writer-ABI concern for these inputs.

### Minor items (non-blocking, cheap assertions only)

1. **Frozen-path coverage is not shown to be enforced.** Freezing the list fixes the mutability bug, but nothing shown proves that the libraries actually mapped at run time are a subset of `identity-dependency-paths.json`. This matters most for the rapidgzip extension `.so`: the `decompress-env/bin/python` symlink does not cover site-packages. If per-cell `/proc/<pid>/maps` realpaths are already checked against the frozen set, this is closed. If not, a one-line subset assertion closes it.
2. **Missing files are silently dropped.** In `identity()`, `if p.is_file()` filters out entries. A frozen dependency path that is missing at first bind is omitted rather than rejected. Later resumes would detect the change, but the first bind would not. `assert all(Path(p).is_file() for p in paths)` would fix this.
3. **`spectra_with_rt` counts scan RT terms, not spectra.** A spectrum with no RT would pass the 600–1200 s window check vacuously. If the separate exact-spectrum-count gate equals 22,544, this is closed. Otherwise, count `spectrum` ends and assert that the two counts match.
4. **`source_commits` are hardcoded labels.** They are not verified against the build. Describe them as recorded provenance, not checked identity.

### Accepted as stated scope

These are adequately disclosed:
- CPU/wall as CPU consumption, not proof of active decoding;
- GCC libgomp rather than libomp;
- CLI startup included in timings;
- the difference-of-medians context approximation;
- metadata equivalence that is non-exhaustive;
- possible SMT sibling placement at low thread counts.

**Verdict:** ready to publish once items 1–3 are confirmed as already covered or given the one-line assertions. None of them requires re-running the canonical matrix unless item 1 turns up an unhashed mapped library.
