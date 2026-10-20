# Final adversarial review: IndexedMzMLDecoder streaming footer parse

No tools were run. This review is from the supplied sources only.

## Verdict

**I found no concrete introduced defects in the decoder, the tests, the CMake change or the harness.** Below are a few test gaps worth closing and some low-severity notes.

## Decoder (`domParseIndexedEnd_`): equivalence with old DOM

I traced each case against the old implementation:

| Case | Old DOM | New reader | Match |
|---|---|---|---|
| Any malformation, before or after a bad offset | `-1` (parse first) | `status < 0` → `-1`. Delayed `exception_ptr` is rethrown only after `status == 0` | ✓ |
| Duplicate depth-1 `indexList` after a bad offset | `-1` (checked before conversion) | depth-1 branch is ordered before `else if (conversion_error) continue;` | ✓ |
| Unknown index name *before* a bad offset | `-1` | `finish_index` → `-1` | ✓ |
| Unknown name on the same or a later index *after* a bad offset | throws (conversion runs before the name check) | `finish_index` is skipped, then rethrow | ✓ |
| Several bad offsets | first one wins | first is saved, later offsets are not expanded | ✓ |
| Any child element name; repeated type is last-wins; missing `idRef` → `""` | yes | yes (depth-only dispatch, move-assign) | ✓ |
| Namespaced or undeclared-prefix `indexList` | `node->name` | `ConstLocalName` (same string in both cases) | ✓ |
| `<index .../>` (empty element) | empty vector assigned | `IsEmptyElement` → `finish_index`. The reader emits no END_ELEMENT for it | ✓ |
| Nested `<value>` or CDATA in an offset | `xmlNodeGetContent` | Expand, then `xmlNodeGetContent`. Depth ≥ 4 nodes are visited later and ignored | ✓ |
| `<indexList/>` | `0`, outputs untouched | same | ✓ |

**Delayed exception state:**
- A stale `in_list` after a conversion error is harmless, because every non-duplicate element and every end element is skipped.
- Only `ConversionError` is deferred. `bad_alloc` still propagates immediately, as before.

**Lifetimes:**
- `in` outlives `reader`.
- The `xmlTextReaderCurrentNode` and `xmlTextReaderExpand` pointers are used only within the same iteration, before the next `Read` can free them.
- On rethrow, `reader` unwinds normally.

**Intended deviation:** outputs are now transactional on failure. The old code partially assigned outputs on a later `-1` or throw. This is benign and stated in your summary.

## Test gaps (recommended, not defects)

1. **Pin both directions of delayed precedence.** Only "later malformation" is tested today:
   - Bad offset, then `</indexList><indexList/></indexedmzML>`, should return `-1` (duplicate wins).
   - Bad offset, then `<index name='unknown'/>`, should **throw** (old order).
   - Unknown index, then bad offset, should return `-1`.
2. **Trailing content after the root**, e.g. `...</indexedmzML><x/>`. Old DOM returns `-1`. The new code depends on the reader's terminal `xmlParseChunk(..., terminate=1)` reporting it. That is likely to work, but it is unpinned and version-sensitive.
3. **Run the unclosed-root case (footer #3) on Linux against the minimum libxml2 2.13.** The reader's EOF error reporting is the most version-sensitive path, and macOS may be on a newer libxml2.
4. **Padding size nit.** The padding is 32,000 bytes, not 32 KiB. The reader pushes in small chunks, so the padding is ample, and the test discriminates either way.

## Harness

**Correct:**
- Every pre-barrier failure path drops from the barrier, and post-barrier failures need no drop.
- If every worker drops, the main thread still completes the phase.
- Barriers, `results` and `errors` all outlive `threads`.
- Per-worker `read_seconds` excludes open and barrier time.
- `synchronized_read_seconds` includes teardown and join, as designed.

**Notes:**
- **Low severity:** if `threads.emplace_back` throws (thread exhaustion near 96 workers), the jthread destructors join workers blocked on `start`, and the run deadlocks. It is unlikely, but a try/catch that calls `start.arrive_and_drop()` once per missing worker would close it.
- **Gate coverage:** `indexed-sync` fingerprints sample `queries` random spectra and never read chromatograms. Equal worker digests only prove determinism across threads, not decoder correctness. For the decoder change, also:
  - run `verify` on all 5 inputs, which uses indexed access for every spectrum and chromatogram against a full load;
  - compare `index_spectra` and `index_chromatograms` against a baseline from the old build.

## CMake

The `READER` feature check matches the new `xmlreader` dependency. `unset(... CACHE)` with push/pop state is correct. The duplicate `include(CheckSymbolExists)` is harmless.

## Nits

- The function name `domParseIndexedEnd_` is now a misnomer. It is private, so leaving it is fine.
- The allocator-arena rationale in the leading comment is an unmeasured claim. Revisit it once the Linux RSS numbers are in.
