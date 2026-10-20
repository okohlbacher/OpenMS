# Review: candidate `domParseIndexedEnd_`

Only `domParseIndexedEnd_` changed; `parseOffsets`, `findIndexListOffset` and `stringToStreampos` are byte-identical.

**I found no memory-safety, lifetime or security bugs.**

- `document` still owns the DOM on every early return and exception path. `document.reset()` happens before any use of the packed data, and the packed data doesn't point into the DOM.
- `auto& packed = indices.back()` is taken again on each outer iteration. Nothing is added to `indices` while it is held, so the reference is never invalidated.
- `substr(begin, length)` stays in range, including empty IDs where `begin == ids.size()`. The ranges are length-based, so embedded content can't break them.
- Error precedence matches the original:
  - DOM failure comes before any conversion.
  - Within one index, offset conversion runs before the name check.
  - Across indices, processing is in document order, so an unknown name in index *k* still beats a bad offset in index *k+1*.
- The permissive child semantics and last-wins are preserved. An empty index still clears that output, and a missing index still leaves it untouched.
- Outputs are only written by two `vector` move-assignments at the end, which are noexcept. Failures, including `bad_alloc` while building the result, now leave the outputs unchanged.

## Findings

### 1. Repeated indices are all turned into strings, then all but the last are thrown away (cost; works against the change's own goal)
The original replaced the output at each index, so earlier results were freed as it went. The candidate:
- keeps every index's packed data for the whole DOM lifetime, and
- after `document.reset()`, allocates the final strings for **every** packed index, then discards all but the last of each type.

So for repeated `spectrum`/`chromatogram` indices, short-lived string allocations are mixed in with the long-lived ones, in exactly the phase meant to allocate only survivors. The work is also O(all indices) instead of O(the last ones).

Fix: in the first pass, record the position of the last `spectrum` and last `chromatogram` entry in `indices`. Build strings only for those two, or drop superseded entries when a later index of the same name appears.

### 2. Behaviour changes when both output arguments are the same vector
If a caller passes the same vector as both `spectra_offsets` and `chromatograms_offsets`:
- the original ends up with whichever index came **last in the document**;
- the candidate always writes spectra first, then chromatograms, so chromatogram data wins whenever both exist.

This is a niche case and may not be a supported contract, but it is a real change in observable behaviour. If you care, assign the outputs in the order the last index of each type appeared.

### 3. Leftover includes from the earlier reader attempt
`<libxml/xmlreader.h>` and `<exception>` are no longer used. They add a dependency on the reader API that nothing needs. Remove them.

### 4. Tests don't cover the new transactional behaviour
Every failure case in the tests either has a single index or fails in the DOM parser, and the original also passes all of those. These cases would actually tell the old and new versions apart:
- `<index name='spectrum'>…valid…</index><index name='unknown'/>` should return -1 with the sentinel outputs still intact.
- A valid spectrum index followed by a chromatogram offset that overflows should throw `ConversionError` with the sentinel outputs still intact. The existing overflow test doesn't check the outputs after the throw.
- Repeated `spectrum` indices should give last-wins, with both outputs checked.

Nit: section names and comments still describe the reader implementation ("Forward-only", "Footer cursor", "reader's initial input buffer").

## Note for your pending measurements (mechanism, not tuning)
Under glibc, freed small blocks are kept in per-size free lists and handed back most-recent-first. Freeing the DOM and then allocating heap strings of about 32–64 bytes (typical mzML `idRef`s are longer than the 15-byte inline-string limit) will tend to reuse exactly the freed DOM blocks.

So "free the DOM before allocating" may not change where the retained strings end up. Check this directly, for example with `malloc_info` or heap page residency before and after, rather than relying on the reordering. Finding 1 makes this worse when indices repeat.
