# Footer-memory review dispositions

Codex traced the allocation path and reviewed the final error/barrier state machines. Actual tool-free Kimi and Claude Opus5.5 initial/final receipts and inputs are retained; private stderr is excluded. Reviews are findings, not approval votes.

| Finding | Decision |
|---|---|
| Whole-footer DOM nodes remain as free arena memory | Confirmed by Linux mallinfo2/statm probes:96 retained readers keep roughly8GiB free arena memory despite about1.1GiB live allocations. Replace the DOM with forward-only xmlTextReader, expanding only one offset subtree; no allocator settings/trim in OpenMS. |
| Bad numeric offset can throw before later XML malformation | Fixed before canonical measurements: retain the first ConversionError, continue well-formedness checks, return-1 for later malformedXML, otherwise rethrow. A32,000-byte padding regression test places the XML failure beyond read-ahead. Unknown index names are checked after their offsets, as before. |
| Kimi initial claims old parser checked index/offset element names | Rejected against actual old source: it processed any direct child elements. Tests pin that permissive behavior and last-index-type-wins; no unrequested stricter validation. |
| Missing optional READER library feature | Added explicit configure-time feature check. The same2.13 minimum and NONET/NO_XXE/NOENT/default parser bounds remain. |
| Reader/expanded-node lifetime, accidental DOM preservation | Both final reviews find no introduced defect: pointers are consumed before nextRead, no Preserve API, only one offset subtree expanded, reader RAII. |
| Partial thread-team construction could strand a benchmark barrier | Private harness cleanup drops missing workers from start/read barriers, releases/joins created workers, then rethrows. This only protects failure startup; no product change. Missing-file four-reader negative controls separately verify pre-read-barrier error handling. |
| Faster open could hide slower indexed reads | Added private indexed-sync mode: all readers finish open before a common read phase. Report full-workload, synchronized-read-with-teardown/join and per-worker query-loop clocks separately; gate before/after within this phase. |
| Transactional output vectors on error | Intentional tightening: failed footer parses leave caller outputs unchanged. Old code could partially assign before a later semantic error. Tests pin failure outputs. |

Final Opus5.5 and Kimi report no concrete introduced defect after correction. Optional minimum-version2.13 runtime testing and forced thread-resource exhaustion were not performed; Linux/macOS tests use2.15.4. The minimum library reader API is longstanding, but this is not an execution claim for every libxml2 version.

Kimi final informational note says old libxml2 xmlNode->name was qualified for prefixed nodes; this is not supported by the actual local-name API. A baseline/candidate namespace-footer probe is retained with the final post-checks to adjudicate using execution rather than model assertions.

Allocator probes that call malloc_trim are explicitly diagnostic and separate from canonical timing/RSS. No claim is made that destructing all reader objects immediately returns every allocator page to the OS; the no-trim lifecycle probes and post-read RSS remain visible.

## Final strategy and subsequent actual reviews

The all-reader-only claim above is superseded: sustained IM loops regressed despite faster opens. All264 initial processes and54 confirmations remain separately published as rejected-candidate evidence. Removing a spectrum-buffer copy did not recover speed (9 processes); packed-ID and preallocated packed-ID DOM variants saved much less retained memory. Exact sources/patches and measurements remain excluded diagnostics; no fastest version/repetition is substituted for the final schedule.

The final product keeps the original DOM path for wrapped footers up to2MiB and the reviewed reader above it. This explicitly bounded small-footer fast path preserves IM allocator reuse in the measured input; it does not promise a universal optimal cutoff. No global allocator settings or malloc_trim are introduced. The final primary rerun matches the unchanged baseline's0–95 CPU placement; an early wrapper that narrowed primary CPUs was stopped, fully retained as an excluded pilot, and corrected before the canonical run. Sustained paired checks always use0..N-1.

Actual additional Opus5.5 and Kimi reviews of the packed variant both identified output-vector alias assignment order. Both final paths now retain whichever index type was last in document order for aliased outputs. Product tests cover aliasing, transactional failures,70,000 offsets reaching the reader path and small/large error precedence.

Final Opus5.5 static review found no definite reader logic defect but proposed a possible failure to reject trailing junk beyond read-ahead. Independent SDK controls execute both size paths with4,096 trailing spaces then junk, and4,096 NUL bytes, as well as duplicate lists, truncated/mismatched XML, conversion/duplicate precedence and namespace/CDATA/entity content. All20 controls pass on macOS and Linux. The suspected trailing-junk defect is therefore not reproduced on tested libxml2 2.15.4. Expanded controls address the substantive test-coverage gaps without changing the frozen product or timed harness. The low stderr difference for numeric errors before later XML failure is acknowledged: large-reader diagnostics may print before returning-1, while outputs/error codes remain matched. The required READER feature is checked explicitly by CMake.

Review models/inputs/receipts are preserved under individual directories. Private stderr is excluded. Reviews are static, not substitutes for execution or speed measurements; minimum-version runtime, forced thread exhaustion, Windows and sanitizers remain unexecuted here.

Final Kimi2.2.0 completed successfully (same exact packet as final Opus): no confirmed high/medium correctness defect; its substantive low finding is reader-path coverage for namespace/CDATA/entity/permissive/missing-ID cases. The independent final control program now runs these in both0/2MiB-padded paths and checks returned IDs as well as positions; its final expected count is20. The final receipts and actual execution logs govern the pass claim. Threshold applies to the wrapped buffer, so raw footer boundary is2MiB minus14 bytes. Both reviewers confirm alias and conversion/XML-error order after correction.
