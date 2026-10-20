# Complete-replacement scaling evidence

See [the report](REPORT.md), [macOS options](MACOS_OPTIONS.md), [all comparisons](all-comparisons.csv) and [figures](figures/). The Linux production source is `8f66b3d921c9512e1e5968f494c77715ff71c696`; private macOS experimental patches are explicitly identified and are not shipped changes.

The [throughput supplement](REPORT.md#throughput-in-mbs-and-remaining-benchmark-gaps) adds derived MB/s, decoded points/s and scaling graphs, with explicit unmeasured benchmark gaps; it adds no new benchmark runs. Restore `throughput-section.md` at the phase root when regenerating the report.

Every final cell has five fresh-process repetitions. The new phase contributes 2,280 Linux and 280 macOS performance records. Historical summary cells are retained unchanged in the combined table; source/build identities separate the phases. Whole-workload and dedicated opening-phase seconds are different columns.

Raw matrices and large logs are deterministically gzip-compressed. Decompress a `.json.gz` to its original `.json` name before analysis. Linux `transport-verification.json` checks every copied result/log against the remote manifest before scratch cleanup; `cleanup.json` records removal of only the dedicated task-owned root. The parent SHA256SUMS covers published files and may differ from transport hashes for compressed representations.

Reproduction scripts retain the original workspace and scratch layout. Restore this directory to `results/full-scaling/` in a workspace containing `OpenMS-libxml2/`, the historical benchmark sources/data, and required dependencies; adjust explicit node/root paths for a new run. `source-input-manifest.json` pins source/input/archive identities and includes a public base plus `xerces-optimized.patch` to reproduce the optimized control. Official dependency archives and their hashes are in the preparation script. Linux builds use private dependencies and read-only shared contrib. macOS experiments require the recorded Homebrew libraries, native builds, frozen benchmark executable and original OpenMS build objects for the isolated handler re-link. No binaries, objects, private reviewer stderr or credentials are published.

Context overhead is an idle-adjusted process estimate including retained reader/index/metadata and allocator state. It is not the byte size of a libxml2 parser context; sampling after worker joins excludes live worker stacks. Independent-reader scaling and single-reader fixed-work OpenMP are separate matrices; 96 readers on this node include SMT.

Private-patch review receipts: Codex reviewed the actual caller/fallback contract; Kimi and Claude Opus 5.5 independently reviewed both isolated candidates. Unsupported partial buffer overlap and duplicated skip predicates remain limitations. The report discloses the native Xerces DOMTest failure reproduced with the installed bottle.
