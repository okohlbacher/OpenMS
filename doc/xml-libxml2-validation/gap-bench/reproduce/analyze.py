#!/usr/bin/env python3
"""Collate phase-separated timing/RSS evidence; derive rates from three-run medians."""

import argparse, csv, gzip, json, statistics as st
from collections import defaultdict
from pathlib import Path

P = argparse.ArgumentParser()
P.add_argument("raw", type=Path)
P.add_argument("output", type=Path)
P.add_argument("--historical", type=Path)
a = P.parse_args()
a.output.mkdir(parents=True, exist_ok=True)


def load(name):
    return json.loads((a.raw / name).read_text())


def records(name):
    p = a.raw / name
    if not p.exists():
        p = Path(str(p) + ".gz")
    with gzip.open(p, "rt") if p.suffix == ".gz" else p.open() as f:
        return [json.loads(l) for l in f]


all_rows = records("records.jsonl") + records("access-records.jsonl")
selected = load("reduced-primary-schedule.json") + load("reduced-access-schedule.json")
cell_key = lambda c: json.dumps(c, sort_keys=True)
by_cell = {cell_key(r["cell"]): r for r in all_rows}
assert len(by_cell) == len(all_rows), "Duplicate raw cells"
assert len(selected) == 600 and len({cell_key(c) for c in selected}) == 600
rows = [by_cell[cell_key(c)] for c in selected]
assert len({r["measurement_identity_sha256"] for r in rows}) == 1
assert (a.raw / "ALL_MEASUREMENTS_COMPLETE").exists()
assert (a.raw / "POST_CONTROLS_COMPLETE").exists(), "Post-run validation has not passed"
attempts = records("attempts.jsonl")
reduced_launch = load("reduced-launch.json")
assert reduced_launch["status"] == "complete", "No complete reduced launch receipt"
failure_file = a.raw / "failures.jsonl"
failures = (
    [json.loads(l) for l in failure_file.read_text().splitlines()] if failure_file.exists() else []
)
cell_failure_file = a.raw / "cell-failures.jsonl"
cell_failures = (
    [json.loads(l) for l in cell_failure_file.read_text().splitlines()]
    if cell_failure_file.exists()
    else []
)
inputs = load("inputs.json")
refs = load("references.json")
groups = defaultdict(list)
for r in rows:
    assert r["ok"], r
    cell = {k: v for k, v in r["cell"].items() if k != "rep"}
    groups[json.dumps(cell, sort_keys=True)].append(r)
def cli_peak(v):
    return max(v["native_wait4_peak_rss_bytes"], v["sampled_native_hwm_bytes"])


summary = []
for key, rr in sorted(groups.items()):
    c = json.loads(key)
    assert len(rr) == 3 and len({r["cell"]["rep"] for r in rr}) == 3, c
    r = dict(
        c,
        repetitions=3,
        evidence_phase="linux-large-real-decompression",
        platform="linux",
        source_commit={
            "xerces": "58aa37348c968a12e3285295f28c197cc0b7bdbe",
            "libxml2-full": "8f66b3d921c9512e1e5968f494c77715ff71c696",
        }.get(c.get("backend", ""), "not-OpenMS"),
        file_bytes=inputs[c["input"]]["bytes"],
    )

    def stats(field, values):
        r[field + "_median"] = st.median(values)
        r[field + "_min"] = min(values)
        r[field + "_max"] = max(values)

    stats("process_seconds", [v["process_seconds"] for v in rr])
    stats("native_threads", [v["sampled_native_threads"] for v in rr])
    if c["kind"] != "staged-pipeline":
        stats(
            "effective_cpu_equivalents",
            [
                (v["native_user_seconds"] + v["native_system_seconds"])
                / v["native_process_seconds"]
                for v in rr
            ],
        )
        r["native_inblock_max"] = max(v["native_inblock"] for v in rr)
        r["native_major_faults_max"] = max(v["native_majflt"] for v in rr)
    kind = c["kind"]
    backend = c.get("backend", "")
    n = c.get("workers", 1)
    if kind == "staged-pipeline":
        stats(
            "native_peak_rss_mib",
            [max(cli_peak(v["decompress"]), v["parse"]["native_peak_rss_bytes"]) / 2**20 for v in rr],
        )
        r["staged_file_bytes"] = rr[0]["staged_file_bytes"]
        stats("decompress_seconds", [v["decompress"]["process_seconds"] for v in rr])
        stats("parse_process_seconds", [v["parse"]["process_seconds"] for v in rr])
        r["rss_measurement_basis"] = "max sequential component peaks; CLI max(wait4, sampled VmHWM); tmpfs additional"
        stats(
            "decompress_peak_rss_mib",
            [cli_peak(v["decompress"]) / 2**20 for v in rr],
        )
        stats("parse_peak_rss_mib", [v["parse"]["native_peak_rss_bytes"] / 2**20 for v in rr])
    elif kind == "decompress":
        stats("native_peak_rss_mib", [cli_peak(v) / 2**20 for v in rr])
        stats("native_wait4_peak_rss_mib", [v["native_wait4_peak_rss_bytes"] / 2**20 for v in rr])
        stats("sampled_native_hwm_mib", [v["sampled_native_hwm_bytes"] / 2**20 for v in rr])
        r["rss_measurement_basis"] = (
            "max(native-supervisor wait4, sampled child VmHWM); sampled part lower bound"
        )
        stats("raw_driver_wait4_rss_mib", [v["wait4_max_rss_bytes"] / 2**20 for v in rr])
    else:
        stats("native_peak_rss_mib", [v["native_peak_rss_bytes"] / 2**20 for v in rr])
        stats("resident_rss_mib", [v["resident_rss_bytes"] / 2**20 for v in rr])
        stats("workload_seconds", [v["seconds"] for v in rr])
        r["rss_measurement_basis"] = "C++ /proc/self/status VmHWM; native wait4 cross-check"
        stats("raw_driver_wait4_rss_mib", [v["wait4_max_rss_bytes"] / 2**20 for v in rr])
        r["hash_per_worker"] = rr[0]["hash_per_worker"]
        assert len(set(v["hash_per_worker"] for v in rr)) == 1
        if kind in ["readers", "single-file-openmp", "whole-document"]:
            assert all(
                tuple(
                    v[k]
                    for k in [
                        "spectra_per_worker",
                        "chromatograms_per_worker",
                        "points_per_worker",
                        "hash_per_worker",
                    ]
                )
                == tuple(refs[c["input"]])
                for v in rr
            )
        stats("job_open_seconds", [j["open_seconds"] for v in rr for j in v["jobs"]])
        stats("job_read_seconds", [j["read_seconds"] for v in rr for j in v["jobs"]])
        assert all(f"/snapshots/{backend}/lib" in v["openms_library"] for v in rr)
    if kind in ["readers", "single-file-openmp", "whole-document"]:
        r["file_MB_per_s"] = n * r["file_bytes"] / r["workload_seconds_median"] / 1e6
        r["Mpoints_per_s"] = n * refs[c["input"]][2] / r["workload_seconds_median"] / 1e6
        r["end_to_end_file_MB_per_s"] = n * r["file_bytes"] / r["process_seconds_median"] / 1e6
        if c["input"].startswith("large-matched"):
            r["plain_equivalent_MB_per_s"] = (
                n * inputs["large-matched-plain.mzML"]["bytes"] / r["workload_seconds_median"] / 1e6
            )
    elif kind in ["decompress", "staged-pipeline"]:
        expanded = inputs[c["input"][:-3]]["bytes"]
        r["inflated_bytes"] = expanded
        r["compressed_input_MB_per_s"] = r["file_bytes"] / r["process_seconds_median"] / 1e6
        r["inflated_output_MB_per_s"] = expanded / r["process_seconds_median"] / 1e6
        if kind == "staged-pipeline":
            r["tmpfs_file_plus_component_peak_mib_upper_bound"] = (
                r["staged_file_bytes"] / 2**20 + r["native_peak_rss_mib_median"]
            )
    elif kind == "random-access":
        q = 64 if c["input"] == "pasef-im-600-1200s.mzML" else 256
        r["queries_per_worker"] = q
        r["aggregate_queries_per_s"] = n * q / r["workload_seconds_median"]

    summary.append(r)
idle = {(r["backend"], r["workers"]): r for r in summary if r["kind"] == "idle"}
for r in summary:
    if r["kind"] in ["retained-contexts", "random-access", "readers"]:
        i = idle[r["backend"], r["workers"]]
        r["idle_adjusted_peak_mib_per_reader"] = (
            r["native_peak_rss_mib_median"] - i["native_peak_rss_mib_median"]
        ) / r["workers"]
        metric = (
            "idle_adjusted_retained_mib_per_reader"
            if r["kind"] == "retained-contexts"
            else "idle_adjusted_postjoin_residue_mib_per_reader"
        )
        r[metric] = (r["resident_rss_mib_median"] - i["resident_rss_mib_median"]) / r["workers"]
(a.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def writecsv(path, rr):
    keys = list(dict.fromkeys(k for r in rr for k in r))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        w.writerows(rr)


writecsv(a.output / "summary.csv", summary)
provenance = dict(
    summary_cells=len(summary),
    workload_records=len(rows),
    preserved_total_workload_records=len(all_rows),
    supplemental_records=len(all_rows) - len(rows),
    selection_method=reduced_launch["completed_selection"],
    native_processes=len(rows) + sum(r["cell"]["kind"] == "staged-pipeline" for r in rows),
    repetitions=3,
    inputs=inputs,
    operator_stopped_launches=sum((a.raw / name).exists() for name in [
        "user-reduction-stop-receipt.json", "pilot-before-identity-fix/pilot-stop-receipt.json"
    ]),
    failed_process_entries=len(failures),
    failed_cell_attempts=len(cell_failures),
    failed_launch_attempts=sum(r.get("status") == "failed-or-interrupted" for r in attempts),
    completed_native_exit_failures=sum(
        v["native_exit_code"] != 0
        for r in rows
        for v in ([r["decompress"], r["parse"]] if r["cell"]["kind"] == "staged-pipeline" else [r])
    ),
    units="MB decimal; RSS MiB binary",
    harness_phase="native VmHWM plus native supervisor, 1-thread main warmup, 10ms procfs sampling",
    historical_measurement_methods_retained=True,
)
assert (
    len(summary) == 200 and len(rows) == 600 and provenance["native_processes"] == 660
), provenance
if a.historical:
    with a.historical.open(newline="") as f:
        history = list(csv.DictReader(f))
    for r in history:
        r["rss_measurement_basis"] = "historical phase method; see original phase report"
        r["seconds_basis"] = "historical phase workload clock; see original phase report"
    appended = []
    for r in summary:
        d = dict(
            r,
            seconds_basis=(
                "C++ workload clock; shared warmup excluded"
                if "workload_seconds_median" in r
                else "end-to-end process clock; startup included"
            ),
            variant="complete-replacement-gap-phase",
            matrix=r["kind"],
            mode=r.get(
                "mode", "stream" if r["kind"] in ["readers", "single-file-openmp"] else r["kind"]
            ),
            seconds_median=r.get("workload_seconds_median", r["process_seconds_median"]),
            seconds_min=r.get("workload_seconds_min", r["process_seconds_min"]),
            seconds_max=r.get("workload_seconds_max", r["process_seconds_max"]),
            rss_mib_median=r["native_peak_rss_mib_median"],
            rss_mib_max=r["native_peak_rss_mib_max"],
            openmp_threads=r.get("omp", 1),
        )
        appended.append(d)
    writecsv(a.output / "all-comparisons.csv", history + appended)
    provenance["historical_summary_cells"] = len(history)
    provenance["combined_summary_cells"] = len(history) + len(appended)
(a.output / "table-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
print(json.dumps({k: v for k, v in provenance.items() if k != "inputs"}, indent=2))
