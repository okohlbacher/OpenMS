# Complete libxml2 replacement

This branch extends the tested libxml2 prototype into a complete replacement of Xerces in OpenMS core, including mzIdentML DOM handling, imzML, XML strings and attributes, compressed streams, dependency discovery, Docker, wheels and the shared CI build action. It requires libxml2 2.13 or newer with SAX1, PUSH, SCHEMAS and THREAD support; configuration rejects builds missing these features and warns if both iconv and ICU are absent. The pinned vcpkg baseline supplies 2.15.3; the Docker recipe builds checksum-pinned 2.15.4 because Ubuntu 24.04 supplies an older version.

The earlier [benchmark handoff](../tools/xml-parser-benchmark/HANDOFF.md) and its cross-platform graphs remain the evidence for the three prototype implementations. Those results were measured before this complete migration; they are not new measurements of this branch. The historical standalone benchmark comparator can optionally use Xerces to reproduce that comparison, but building and using OpenMS does not require it.

## Timo’s dependency and performance questions

[Timo’s original comment](https://github.com/OpenMS/OpenMS/issues/10623#issuecomment-6264980988) asks about XML dependencies already brought in through Apache components; his adjacent comment asks about schema validation. Original develop already lists libxml2 in vcpkg and attaches it to statically linked Arrow targets where their bundled dependencies require it (`cmake/cmake_findExternalLibs.cmake`). This migration reuses that existing dependency and raises its minimum to 2.13; it removes Xerces from OpenMS core rather than promising that every optional third-party library uses the same XML implementation. All 22 bundled schemas compile, with the retained instance compatibility difference described below.

The [newer macOS performance question](https://github.com/OpenMS/OpenMS/issues/10623#issuecomment-6284417895) is addressed by a [controlled declaration experiment, table and timing/RSS graph](xml-libxml2-validation/encoding-final/README.md), rerun after review: UTF-8 reduces the complete replacement’s streaming time **17.0%** and default-open time **28.6%**, shrinking its penalties versus Xerces from 33.3%→10.7% and 70.5%→21.2%. Peak RSS is about 52.1 MiB for streaming and 104.2 MiB for UTF-8 metadata open plus queries, versus Xerces’s 56.4 and 118.0 MiB. All 60 final decoded fingerprints match. The [one combined table](xml-libxml2-validation/encoding-final/all-comparisons.csv) includes 2,776 summary cells across the historical platform comparison and both encoding phases. OpenMS itself uses Release `-O3`; Homebrew parser flags were not normalized. This isolates the declaration effect on one host/input and supports Timo’s encoding-conversion hypothesis without claiming a function-level profile or a complete explanation of platform differences.

## Compatibility and ownership

Public file APIs retain their names. SDK consumers must rebuild: XML handler signatures use standard `char16_t`, `XMLAttributes` is a non-owning view of native attribute storage valid only during the receiving callback, and StringManager returns standard strings or `std::unique_ptr<char16_t[]>` instead of Xerces handles. Constructing an attribute view from a temporary vector is forbidden; copying or assigning the view does not extend the backing storage’s lifetime. The private SAX2HandlerAdapter and Xerces initialization entry points are removed. StringManager rejects malformed UTF-8 and UTF-16 rather than replacing invalid sequences. Compression streams implement the private OpenMS InputStream interface. No installed header requires Xerces or libxml2 headers.

The generic parser preserves the previous namespace-disabled behavior used by legacy xQuest and idXML files. ImzML explicitly enables namespace checks, matching its previous dedicated Xerces parser. SAX2 callbacks preserve qualified names, namespace declarations, normalized entity values and bounded attribute slices.

Each parser owns its context and error state. Initialization uses `std::call_once`; OpenMS does not call process-wide libxml2 cleanup while other code may retain contexts. External entity loading is disabled. Comment and processing-instruction callbacks are disabled so SAX parsing does not accumulate their DOM nodes. The mzIdentML DOM reader accepts text and attributes larger than 10 MB while retaining an explicit entity-amplification limit of 5; diagnostics remain local to each parser and report the input and location. Streaming reads use bounded input chunks; whole-dataset loads still retain decoded spectra by API design, and mzIdentML retains a DOM. Separate reader contexts remain required for concurrent indexed reads.

Schema validation keeps the prototype’s documented compatibility decision: libxml2 rejects backslashes in `xs:anyURI` values which Xerces accepted. This branch does not silently rewrite those values. The legacy internal mzIdentML DOM writer remains incomplete in its inherited business logic; the public MzIdentMLFile store path uses its established streaming writer. In the legacy writer, an absent software version is serialized as the explicit sentinel `unknown` so that the reader retains the engine name; the original absence cannot be recovered from that placeholder.

## Validation

The final tested source and guard/test candidate is `8f66b3d921c9512e1e5968f494c77715ff71c696`; runtime implementation is unchanged from `1858656a86869ba462545a9232b89a0e1e1c319c`. Subsequent publication commits add documentation and evidence. On both hosts, OpenMS used Release `-O3 -DNDEBUG`, C++23 and libxml2 2.15.4, with Xerces discovery disabled. Linux used a private libxml2 build with LEGACY off and SAX1, PUSH, SCHEMAS, THREADS, ICONV and ZLIB on. The final suites completed in 65.78 seconds on macOS and 103.25 seconds on Linux.

| Check | macOS ARM64 | Linux x86-64, ibminode05 |
|---|---|---|
| Full core, TOPP and class-test build | Pass | Pass |
| All enabled class tests | 746/747 | 747/747 |
| Remaining macOS Network_test control | Pass with no-space fixture path | Original test passes |
| Bundled schema compilation | 22/22 | 22/22 |
| Instance validation versus archived libxml2 outcomes | 195/195 unchanged | 195/195 unchanged |
| Actual XMLValidator API probes | 3/3 expected outcomes | 3/3 expected outcomes |
| Benchmark smoke suite | Pass | Pass |
| Million-point mzML stream/load/index equivalence | Pass | Pass |
| Historical conformance corpus | 11/11 expected outcomes | 44/44 native repeats |
| Product source and built-library Xerces guard | Pass | Pass |
| Guard unit tests | 11/11 | 11/11 |
| Installed shared SDK consumer compile/run | Pass | Not separately run |

The removal guard covers nested CMake discovery and targets, CI actions, package recipes, invalid source encodings and pruned generated/vendor trees.

The macOS class-suite exception is unchanged `Network_test`: its literal `file://` URL contains unescaped spaces from the workspace path, so libcurl rejects it before XML code runs. The original test source, linked against this build and compiled with a generated no-space fixture path, passes. No product test was skipped or fixture changed to hide namespace failures.

Windows builds, Docker image assembly and wheel publication require their respective CI environments and were not executed by these macOS/Linux core checks. Inherited Windows compression/stat path handling remains unverified. The existing XL-MS mzIdentML fragmentation parser also has an inherited unequal-array-length bounds risk, documented in the review disposition; this migration does not claim to fix every pre-existing malformed-input issue.

Independent Codex, Kimi and Claude Opus 5.5 reviews are complete, including all final corrections; the [coverage index and receipts](xml-libxml2-validation/reviews/README.md) preserve exact source/input identities and dispositions. Opus’s complete review found no Critical or High issues; its two Medium and six Low findings led to feature/interpreter checks, bounded comment/PI handling, safer attribute views, a broader removal guard, large-DOM support, local diagnostics and warning coverage. Follow-up review also closed a CI-action pruning gap and strengthened amplification/location controls. Optional diagnostic-format/visibility and memory-regression-test limitations remain explicitly disclosed in the review records.

All schema and conformance checks were refreshed against the final runtime implementation. The 233 copied Linux result/log files passed checksum verification before the successful dedicated scratch checkout/build was removed; the shared contrib installation was preserved. Raw final evidence and the cleanup receipt are in [xml-libxml2-validation](xml-libxml2-validation/). Historical 96-thread scaling, whole-load RSS and per-context overhead describe the earlier prototypes, not newly measured complete-migration scaling.
