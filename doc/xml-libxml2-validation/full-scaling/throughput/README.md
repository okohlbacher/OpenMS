# Derived throughput evidence

These tables and the graph are unit conversions of the existing measurements, not new benchmark runs. See the [handoff throughput section](../REPORT.md#throughput-in-mbs-and-remaining-benchmark-gaps) for measured results and missing coverage.

`calculate.py` reads the unchanged combined table and raw Linux input metadata and verifies the outer-gzip payload against the recorded internal-zlib file hash. `plot.py` renders `selected-tables.json`. To reproduce, restore these files to `results/chris-throughput/` under the original workspace and restore/decompress the earlier phase evidence to `results/full-scaling/`, with its benchmark-data prerequisites; then run calculate.py followed by plot.py using Python and matplotlib. The scripts retain this original workspace layout. No measurements or source implementations are changed.

The new main-report generator optionally inserts `throughput-section.md` from the restored phase root. Parent SHA256SUMS covers the published files, including this directory’s original artifact checksum manifest. Actual-file, inflated-XML and plain-XML-equivalent byte rates have different denominators. Queries/s is used for indexed workloads. Historical blank OpenMP mode/reader fields are resolved only in added effective fields.
