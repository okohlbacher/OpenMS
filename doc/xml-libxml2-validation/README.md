# Complete replacement evidence

Final source/guard/test candidate: `8f66b3d921c9512e1e5968f494c77715ff71c696`; runtime implementation: `1858656a86869ba462545a9232b89a0e1e1c319c`. Later commits add only documentation/evidence. See the [migration report](../xml_libxml2_migration.md).

- [macOS](macos/): final 746/747 suite, unchanged-source Network_test control, current installed SDK consumer and parser/schema probes; `ctest-final-guard.log` is final.
- [Linux](linux/): final 747/747 suite, clean source and exact library hashes, 233 verified copied result/log files, fresh schema/conformance/API probes and successful scratch cleanup preserving shared contrib.
- [Independent reviews](reviews/README.md): complete Codex/Kimi/Claude Opus 5.5 coverage and all correction phases, with exact input/source identities, findings, dispositions and terminal-completion checks; private stderr is excluded.
- [Final timing and RSS graph](encoding-final/README.md): 60 successful post-review declaration experiments against the completed replacement and frozen Xerces/libxml2 PoCs, decoded equality and phase timings.
- [Earlier encoding experiment](encoding-followup/README.md): 60 separately versioned measurements at cbb180a, preserved as provenance.
- [One combined table](encoding-final/all-comparisons.csv): 2,776 five-run summary cells, 13,880 underlying process records across the historical two-platform prototype comparison and both encoding phases; separately archived clock-confirmation runs are not counted here.

The earlier [prototype handoff and cross-platform graphs](../../tools/xml-parser-benchmark/HANDOFF.md) retain whole-load RSS, parallel random-read RSS/context overhead and Linux scaling through 96 threads. Those are not new measurements of this complete migration. Historical benchmark artifacts remain byte-for-byte unchanged. `evidence_phase`, `variant` and `matrix` separate the combined table’s experiments; whole-workload seconds differ from the dedicated default-open phase column. Native Homebrew parser optimization flags were not normalized to OpenMS Release flags.

SHA256SUMS covers every published evidence file except itself. Local attributes preserve raw CSV/log/figure bytes and their inherited whitespace without changing product formatting rules. Transport manifests cover the broader local raw archive and can name files not duplicated in this compact publication; detailed Linux compile/test logs are gzip compressed. Reproduction scripts retain their original workspace/scratch layouts and expect the source/dependency/input prerequisites documented in their phase READMEs.
