
<invoke name="Write">
<parameter name="file_path">/Users/kohlbach/.claude/plans/review-this-small-product-mellow-lollipop.md</parameter>
<parameter name="content"># Adversarial review: index-footer extraction via xmlTextReader

## Context
Retained fast OnDisc contexts showed much higher RSS with libxml2. The suspected cause is allocator retention after freeing the footer DOM, not live parser contexts. This change replaces DOM parsing of the index footer with a forward-only `xmlTextReader`. It expands only one `<offset>` subtree at a time. Spectrum parsing and decoding are unchanged.

This is a static review of the pasted code only. No tools were run. Linux baseline, candidate, and profiling results are pending, so nothing below claims a memory or speed outcome. The pre-change libxml2 DOM implementation was not included, so parity claims against it are marked **verify**.

## Verdict
- **No accidental DOM preservation found.**
- **No security regression found.**
- **Node lifetimes and resource handling are correct.**
- **One introduced behavioural change in error precedence**, plus test gaps for several claimed invariants.

## 1. Introduced defect: error precedence changed (exception instead of -1)
`IndexedMzMLDecoder.cpp`, depth-3 branch: `stringToStreampos(text)` runs while the reader is still streaming.

- **Before:** the DOM parse failed on any malformation first, so `parseOffsets` returned `-1` before any offset text was converted.
- **Now:** a bad offset that comes *before* the malformation throws `Exception::ConversionError`. The reader never reaches the well-formedness error.
- **Example:**
  ```
  <indexList><index name='spectrum'><offset idRef='a'>abc</offset></index><index name='chromatogram'><offset>1</index></indexList></indexedmzML>
  ```
  This throws now. It returned `-1` before.
- **Caller impact:** `IndexedMzMLHandler::parseFooter_` does not catch the exception. A corrupt or truncated footer now propagates out of `openFile` instead of setting `parsing_success_ = false`.
- This violates the "keep old errors" requirement.
- **Fix:**
  - On the first `ConversionError`, store it in a `std::exception_ptr`.
  - Stop all semantic handling (conversion, name checks, finish_index), but keep calling `xmlTextReaderRead` to the end.
  - If `status < 0`, return `-1`. Otherwise rethrow.
  - This keeps the old ordering (parse error, then document-order semantics) without buffering the offset strings.
- **Test to add:** the example above. Expect `-1` and untouched sentinel outputs.

## 2. Areas checked and found OK
- **DOM preservation**
  - No `xmlTextReaderPreserve`, `PreservePattern`, or `CurrentDoc` (which sets `preserve`). XInclude and validation are not enabled.
  - `xmlTextReaderCurrentNode` and `xmlTextReaderExpand` do not set `NODE_IS_PRESERVED`. Visited siblings are freed via `node->prev` / `node->last`.
  - Freeing is suppressed while `entNr > 0`. That cannot happen here: the synthetic `<indexedmzML>` root comes first, so the tail cannot declare a DTD. Only predefined entities and character references can occur, and `NOENT` produces no entity-ref nodes.
  - Recycled nodes (`ctxt->freeElems`, capped) and the dictionary die with `xmlFreeTextReader`.
- **Node lifetime**
  - The `CurrentNode` and `Expand` results and the `ConstLocalName` pointer are all used before the next `Read`.
  - `in` outlives the reader, which may reference the buffer zero-copy.
- **Exception safety**
  - The throw happens between `Read` calls, never through a libxml2 callback frame.
  - The `unique_ptr` frees the reader.
  - `content` is freed before conversion.
  - Outputs are committed only on success, so they are untouched on `-1` or a throw.
- **Malformed XML**
  - Truncation and mismatched tags inside `Expand` make `DoExpand` return `NULL`, which returns `-1`.
  - At the end of the root, the reader calls `xmlParseChunk(..., terminate=1)`, so trailing junk should yield `-1`. This is not tested.
  - Reading continues after `</indexList>`, which is required for parity.
- **State**
  - `IsEmptyElement` correctly handles `<index/>`, which emits no END_ELEMENT.
  - `<index ...></index>` emits END_ELEMENT and is handled.
  - `index_name` and `offsets` cannot leak across indices.
- **Security**
  - Same parser and flags as before: `NONET | NO_XXE | NOENT | NOERROR | NOWARNING`.
  - No `XML_PARSE_HUGE`, so the default depth, text-length, and amplification limits apply.
  - The known reader UAF (CVE-2024-25062) needs DTD validation plus XInclude. Neither is enabled, and the 2.13 minimum includes the fix.
- **CMake / portability**
  - The READER check matches the unconditional `#include <libxml/xmlreader.h>`. Without it, a reader-less build fails at compile time anyway; the check turns that into a clear configure error.
  - READER is on by default in upstream builds; only minimal or explicitly stripped builds lack it.
  - `XML_PARSE_NO_XXE` needs 2.13, which matches `find_package(LibXml2 2.13)`.

## 3. Baseline parity to verify (not shown; possibly introduced)
Diff each item against the old DOM function, then pin it with a test.

| Behaviour now | Question |
|---|---|
| Repeated same-name `<index>`: last wins (`spectra = std::move(offsets)`) | Did the old code append or last-win? **"Repeated indices" is claimed preserved but no test covers it.** |
| No local-name check at depth 2 (`index`) or depth 3 (`offset`); any element there counts | Did the old code check names? Pin with `<foo name='spectrum'>` and `<index><bar>1</bar>`. |
| `<indexList/>` or zero indices returns `0` | Same before? |
| A missing index type leaves the caller's vector untouched | Same before? The test only covers the "present but empty" case. |
| `indexList` accepted only at depth 1 | Was the old lookup recursive? |
| Unbound prefix (`<n:indexList>` without xmlns): name is `n:indexList`, so `-1` | Expected to match the DOM (same SAX2 builder); pin it. |

## 4. Pre-existing limitations (not introduced)
- **The whole tail is held in `std::string xml`.** This is a large transient allocation and a confounder for the arena-retention measurement.
- **libxml2 may make its own full-tail copy.** Depending on the version, `xmlReaderForMemory` → `xmlParserInputBufferCreateStatic` may copy the buffer when it is not flagged zero-terminated. This would be a second tail-sized `malloc` during the call. Check it in heaptrack rather than assuming either way.
- `lexical_cast<unsigned long long>` accepts a leading `-` (it wraps), and rejects whitespace around offsets.
- Non-UTF-8 files: the tail has no XML declaration.
- Index size is limited to `INT_MAX`.
- `stringToStreampos` writes to `std::cerr`.

## 5. Nits
- The `property` lambda leaks `value` if the `std::string` construction throws `bad_alloc`.
- `xmlGetProp` returning NULL on OOM silently yields an empty idRef.
- Test comment "rejected before entering a backend DOM parser" is now stale wording.
- Add brief comments that depth 2/3 intentionally skip element-name checks (or add the checks if the baseline had them).

## 6. Tests to add
1. Bad offset text followed by a later malformation: expect `-1`, outputs untouched (this fails today; see §1).
2. Repeated `index name='spectrum'` (twice, with different offsets): pin the baseline semantics.
3. Junk after `</indexedmzML>` (e.g. `<x/>` or text): expect `-1`.
4. Malformation after `</indexList>` (e.g. unclosed `<fileChecksum>`): expect `-1`.
5. Unbound prefix footer and non-`index`/non-`offset` element names: pin the baseline semantics.
6. Missing `idRef` and missing-index-type preservation.
7. Optional guard against accidental DOM preservation, in a dedicated test binary:
   - Count live libxml2 bytes via `xmlMemSetup` while parsing 100k offsets.
   - Assert the peak is much smaller than the tail size.
   - Must run before any other libxml2 use in that process.

## Verification (pending, user-run)
- Linux baseline vs candidate: RSS and heaptrack for N retained fast OnDisc contexts. Check:
  - peak live libxml2 bytes inside `domParseIndexedEnd_`;
  - any tail-sized libxml2 allocations;
  - `malloc_info` / arena stats after the parse.
- Indexed-open speed on large indices (with `Expand` per offset).
- Run the four existing tests plus the §6 additions on Linux and macOS.
</parameter>
</invoke>
<invoke name="ExitPlanMode">
</invoke>
