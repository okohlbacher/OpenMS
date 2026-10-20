## Findings

**No introduced correctness or security regression found in either patch.**

### 1. `libxml2-ascii.patch` (`latin1ToUTF8` word fast path)

- **Bounds:** Correct. `inend - in >= 8` guards the 8-byte read. Each ASCII byte maps to exactly one output byte, so `outend - out >= 8` is sufficient for the write.
  - Negative `*inlen` or `*outlen` gives a negative difference, so the fast path is skipped and behavior matches the original.
  - Partial words and short output space fall through to the unchanged byte loop. That preserves `*inlen`/`*outlen` and the `XML_ENC_ERR_SPACE` semantics.
- **UB and portability:** Clean.
  - Both `memcpy`s go through a local, so there is no overlap UB, no alignment requirement and no strict-aliasing issue.
  - The `0x80…80` mask is the same in every byte, so endianness is irrelevant.
- **Aliasing (unsupported, not a regression):**
  - Exact in-place use (`out == in`) still gives identical results, as your 65 cases confirm.
  - Partially overlapping buffers (`in < out < in+8`) now give different output than the original byte-serial loop.
  - The original already corrupted unread input on any overlap with `out > in`, including after any non-ASCII expansion. libxml2 only calls this with separate buffers, and the public API makes no overlap promise. So this is unsupported alias use, not a regression.
  - Your in-place test covers only exact aliasing, so its comment overstates what it covers.
- **Minor, not a defect:** `unsigned c = *in;` now follows a statement (C99 mixed declarations). libxml2 2.15 assumes C99, but a `-Wdeclaration-after-statement` build would warn. Moving the declaration above the new block avoids that.
- **Scope note:** The speedup only applies to input declared or detected as ISO-8859-1. UTF-8 mzML never goes through this converter.

### 2. `handler-discard-first.patch`

- **Equivalence:** The new early return can only change the outcome when the payload contains a non-ASCII byte. Previously that returned `false`, fell back to `onCharacters`, and hit its first check (`skip_* || !getFillData()`), which returns immediately. Now it returns `true` directly. Both paths discard the payload, so the observable result is the same.
- **Subclass guard preserved:** The new check comes after the `typeid` test, so derived handlers still always take the fallback. The comment's "including derived handlers" is accurate only because of that ordering. Keep the ordering if this is ever refactored.
- **Assumption to confirm:** Equivalence also requires that the caller's fallback step has no observable side effect for this data. That step is the UTF-8→UTF-16 conversion before calling `onCharacters`: no warning, counter or exception. libxml2 hands SAX already-validated UTF-8, so this should hold, but the caller code wasn't shown.
- **Pre-existing, not introduced:**
  - `onCharacters` calls `open_tags_.back()` without an emptiness check.
  - That would be UB for non-ASCII characters with `open_tags_` empty while not skipping. In practice it is unreachable, because SAX does not deliver character data outside the root element.
  - The patch adds a guard on its own path and does not widen this exposure.

### Test coverage
- The oracle covers 8-byte boundary offsets (prefix 0–17), output-capacity edges, the return code, and guard bytes on both sides of the output.
- Negative-length inputs are not tested but are identical by inspection.
- The digest match against unpatched `-O3` closes the gap between the oracle and the real library.
