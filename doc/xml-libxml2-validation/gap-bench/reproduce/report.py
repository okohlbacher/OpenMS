#!/usr/bin/env python3
"""Generate the concise handoff from measured medians, with explicit scope limits."""

import argparse, json, statistics as st
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("summary", type=Path)
p.add_argument("raw", type=Path)
p.add_argument("output", type=Path)
p.add_argument("--concise-output", type=Path)
a = p.parse_args()
D = json.loads(a.summary.read_text())
P = json.loads(a.summary.with_name("table-provenance.json").read_text())
C = json.loads((a.raw / "correctness-audits.json").read_text())
IM = json.loads((a.raw / "im-window-metadata.json").read_text())
B = ["xerces", "libxml2-full"]
names = [
    "large-matched-plain.mzML",
    "large-matched-zlib.mzML",
    "large-matched-plain.mzML.gz",
    "large-matched-zlib.mzML.gz",
    "dda-lumos.mzML",
    "pasef-published.mzML",
    "pasef-im-600-1200s.mzML",
]
labels = [
    "Matched plain",
    "Matched internal zlib",
    "Matched plain + outer gzip",
    "Matched zlib + outer gzip",
    "Real DDA (Lumos)",
    "Published PASEF (no IM)",
    "Real TIMS IM,600–1200s",
]


def select(kind, name=None, b=None, **kw):
    return [
        r
        for r in D
        if r["kind"] == kind
        and (name is None or r["input"] == name)
        and (b is None or r.get("backend") == b)
        and all(r.get(k) == v for k, v in kw.items())
    ]


def one(*args, **kw):
    r = select(*args, **kw)
    assert len(r) == 1, (args, kw, len(r))
    return r[0]


def f(x):
    return f"{x:,.1f}"


def table(headers, rows):
    return "\n".join(
        ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
        + ["| " + " | ".join(map(str, r)) + " |" for r in rows]
    )


def pair(kind, name, metric, **where):
    return " / ".join(f(one(kind, name, b, **where)[metric]) for b in B)


intro = f"""# XML replacement: large matched files, real acquisitions and single-file decompression

This phase measures the enumerated **Linux** cases with the user-requested reduced schedule: four matched files each ≥1,000,000,000 bytes; real DDA, published PASEF and a mobility-preserving real TIMS window; gzip/pigz/rapidgzip on **one gzip file** through requested96 threads. It also adds whole-document RSS, indexed-read RSS and retained-context overhead on these inputs. **{P['workload_records']:,} fresh workload records / {P['native_processes']:,} native processes, three repetitions per cell; {P['summary_cells']} new summary cells.** The [combined table](all-comparisons.csv) has {P.get('combined_summary_cells',0):,} cells across platforms and phases. The user reduced the original schedule after412 completed measurements. Selection prefers completed repetitions then original repetition number, never speed. Non-selected completed measurements remain supplemental raw evidence; the superseded28-record pilot stays separately excluded. Native source remains Xerces`58aa3734` versus complete libxml2`8f66b3d9`; no product-parser change was made for this phase.

**Interpretation:** compare backends within the same input. Independent readers are threads in one process reading the same cached inode; each has its own state. The96-CPU set contains64 physical cores plus32 SMT siblings. Requested tool/OMP settings, sampled process-thread counts and CPU-time/wall-time consumption (including runtime spin and startup) is a separate metric. XSD correctness was tested previously; XSD validation is not timed here.

## Matched and real inputs: one-reader throughput and RSS

Rates use the C++ workload clock. **Xerces / complete libxml2** in each paired column. MB is decimal; RSS MiB is binary. Compressed-file MB/s has a different byte denominator; points/s shows the common decoded work for the four matched forms.

"""
rr = []
for n, label in zip(names, labels):
    r = one("readers", n, "xerces", workers=1)
    rr.append(
        [
            label,
            f(r["file_bytes"] / 1e6),
            pair("readers", n, "file_MB_per_s", workers=1),
            pair("readers", n, "Mpoints_per_s", workers=1),
            pair("readers", n, "native_peak_rss_mib_median", workers=1),
        ]
    )
text = (
    intro
    + table(
        [
            "Input",
            "Actual MB",
            "Input MB/s, X / L",
            "Million points/s, X / L",
            "Peak RSS MiB, X / L",
        ],
        rr,
    )
    + "\n\n![Matched-format throughput and RSS](figures/matched-formats.png)\n\n"
)
text += """The matched variants contain131,072 spectra, one chromatogram and268,566,528 decoded points, with identical base **and auxiliary** digests. Each gzip inflates byte-for-byte to its corresponding XML. The real inputs intentionally have different content; their throughput is not a ranking of acquisition technologies.

"""
real = []
for n in names[4:]:
    r = next(r for r in C if r["input"] == n)
    real.append(
        [
            labels[names.index(n)],
            f(r["spectra_per_worker"]),
            f(r["points_per_worker"]),
            f(r["im_array_values_per_worker"]),
            f(r["im_scalar_spectra_per_worker"]),
        ]
    )
text += table(
    [
        "Real input",
        "Spectra",
        "Decoded points",
        "Finite IM-array values",
        "Finite scalar-IM spectra",
    ],
    real,
)
text += f"""\n\nDDA is public PXD008952; published PASEF and vendor TIMS data are MSV000101607/PXD077653. The published PASEF mzML has zero finite scalar/per-peak IM values. The separate TIMS conversion preserves IM for the actual {IM['min_rt_seconds']:.6f}–{IM['max_rt_seconds']:.6f}s window ({IM['finite_precursor_im_cv_terms']:,} finite precursor IM CV terms). It uses OpenMS **RATIONAL table calibration**, not a proprietary-SDK equivalence claim. Public URLs, original checksums, conversion source and configuration are in the evidence. The IM-only mutation test changes the auxiliary digest while leaving the peak digest unchanged; both backends agree on all seven inputs. This audit is not exhaustive equivalence of every metadata field. The matched/converted-IM XML declares Latin-1; public DDA/PASEF declares UTF-8. Inputs differ in content and encoding, so cross-input rates do not isolate acquisition or encoding effects. Both OpenMS backends use zlib1.3.1; system pigz uses zlib1.3. The complete runtime inventory is retained.

## Same-file reader scaling and memory

"""
rr = []
for n in [names[0], names[1], names[2], *names[4:]]:
    for workers in ([1, 64, 96] if n in names[:3] else [1, 96]):
        rr.append(
            [
                labels[names.index(n)],
                workers,
                pair("readers", n, "Mpoints_per_s", workers=workers),
                pair("readers", n, "native_peak_rss_mib_median", workers=workers),
            ]
        )
text += table(["Input", "Readers", "Aggregate million points/s, X / L", "Peak RSS MiB, X / L"], rr)
text += "\n\n![Real acquisition throughput and RSS](figures/real-acquisitions.png)\n\nSingle-file OpenMP is a separate fixed-work sweep through96; it does not multiply input work. The new one-thread main warmup avoids the prior unused main-thread team: the96-thread controls observed97 process threads on both backends. Threads observed by sampling are a lower bound and do not alone prove active parallel decoding.\n\n![Fixed-work OpenMP scaling](figures/single-file-openmp.png)\n\n## One-file gzip decompression and staged end-to-end workflow\n\nThe following are **full CLI/process times**, including startup; rapidgzip is a Python entry point around its compiled decoder. No startup subtraction or imported gzip index is used. CRC verification is enabled; full output SHA checks pass at1/96 under the exact clean runtime environment. Gzip is one-thread-only. Pigz `-p96` does not create96 DEFLATE decoders; its sampled helper-thread count is shown.\n\n"
rr = []
for n in names[2:4]:
    for tool in ["gzip", "pigz", "rapidgzip"]:
        choices = select("decompress", n, tool=tool)
        best = max(choices, key=lambda r: r["inflated_output_MB_per_s"])
        end = one("decompress", n, tool=tool, requested_threads=1 if tool == "gzip" else 96)
        rr.append(
            [
                labels[names.index(n)],
                tool,
                best["requested_threads"],
                f(best["inflated_output_MB_per_s"]),
                f(end["inflated_output_MB_per_s"]),
                f(end["native_peak_rss_mib_median"]),
                f(end["native_threads_median"]),
            ]
        )
text += table(
    [
        "Input",
        "Tool",
        "Best tested setting",
        "Best inflated XML MB/s",
        "Setting96 MB/s*",
        "Setting96 RSS MiB*",
        "Observed threads*",
    ],
    rr,
)
text += """\n\n*Gzip columns use its only setting1. “Best” is the maximum measured three-run median among the tested settings, not a guarantee of an optimum or a statistically significant win. [CSV](summary.csv) includes every setting, ranges, compressed-input MB/s, inflated-output MB/s and CPU equivalents.

![Single-file decompression](figures/single-file-decompression.png)

A second measured workflow writes a **regular RAM file**, then parses it with one OpenMS reader/OMP1. This is sequential staging, **not a FIFO or streaming pipeline**: the existing XML reader performs an initial seek. End-to-end process clocks are used for both the staged workflow and the internal-gzip baseline. Native process RSS is the maximum of the two sequential components, not their sum; the additional4.505GB or2.206GB RAM-file footprint is reported separately. A figure also shows file bytes plus component RSS as a conservative upper bound, not a measured simultaneous physical-RAM peak.

"""
rr = []
for n in names[2:4]:
    for b in B:
        baseline = one("readers", n, b, workers=1)
        best = min(select("staged-pipeline", n, b), key=lambda r: r["process_seconds_median"])
        rr.append(
            [
                labels[names.index(n)],
                "Xerces" if b == "xerces" else "libxml2",
                f(baseline["process_seconds_median"]),
                f"{best['tool']} {best['requested_threads']}",
                f(best["process_seconds_median"]),
                f(best["native_peak_rss_mib_median"]),
                f(best["staged_file_bytes"] / 2**20),
            ]
        )
text += table(
    [
        "Input",
        "Parser",
        "Internal gzip s",
        "Best measured staged setting",
        "Staged end-to-end s",
        "Component peak MiB",
        "Additional RAM file MiB",
    ],
    rr,
)
text += """\n\n![Staged workflow and RAM cost](figures/staged-pipeline.png)

## Whole-document and random-access RSS, per-reader contexts

Whole-document results retain one complete experiment and compare requested OMP1/96. New indexed tests use256 deterministic random queries per reader,64 for the IM input, through96 concurrent readers. Fast/default-index opening here skips full metadata; the previous phase separately measured metadata-aware opening. Outer gzip is excluded from indexed access because this is an indexed regular-file path.

"""
rr = []
for n in names:
    rr.append(
        [
            labels[names.index(n)],
            pair("whole-document", n, "native_peak_rss_mib_median", omp=1),
            pair("whole-document", n, "native_peak_rss_mib_median", omp=96),
        ]
    )
text += (
    table(["Input", "Whole load OMP1 RSS MiB, X / L", "Whole load OMP96 RSS MiB, X / L"], rr)
    + "\n\n"
)
rr = []
for n in [n for n in names if not n.endswith(".gz")]:
    rr.append(
        [
            labels[names.index(n)],
            pair("random-access", n, "native_peak_rss_mib_median", workers=96),
            pair("retained-contexts", n, "idle_adjusted_retained_mib_per_reader", workers=1),
            pair("retained-contexts", n, "idle_adjusted_retained_mib_per_reader", workers=96),
        ]
    )
text += table(
    [
        "Input",
        "Random-read96 peak MiB, X / L",
        "Retained context/index MiB per reader at1, X / L",
        "At96, X / L",
    ],
    rr,
)
text += """\n\nContext estimates are `(median resident RSS of retained contexts − median idle RSS at sameN)/N`, using post-join statm while contexts remain alive. They include index, reader and allocator state; they are not the isolated size of a native XML parser context. Independent medians and statm accounting make small differences approximate; negative estimates are not clipped.

![Whole-document load and RSS](figures/whole-document.png)
![Random-read scaling and RSS](figures/random-access.png)
![Retained context overhead](figures/context-overhead.png)

## Cross-platform handoff and measurement limits

The earlier macOS M4 Max results remain measured evidence: native-O3 libxml2 and a valid UTF-8 declaration brought the same1,126.2MB ASCII-body control close to Xerces (420.0 versus418.8MB/s); Latin-1 still favored Xerces (356.2 versus460.8MB/s). This supports testing native builds and real input encoding on macOS. It does not justify relabeling arbitrary Latin-1 files without transcoding or adopting the experimental byte-truncation patch. The new large compressed/real/decompression matrix is **Linux-only**; no new macOS numbers are implied.

![Cross-platform evidence with phase boundaries](figures/platforms.png)

All selected runs use fresh processes, randomized order, three reps, CPU0–95 on EPYC7763, native-O3 GCC13.3/C++23, private libxml2 2.15.4 and Xerces3.3.0. MinCore confirms every input page resident before each timed cell; any warming occurs outside timing. The driver is pinned to96–127; work threads are scheduled freely inside0–95, so low-N placements are not guaranteed distinct physical cores. Native in-block I/O, major faults, CPU time, thread samples, mapped libraries and resource history remain auditable.

C++ VmHWM excludes Python's inherited launch-RSS floor. Decompressors use a small native fork supervisor for wait4 peak RSS, with raw Python wait4 retained separately; the native launch floor is calibrated in the controls. For CLI RSS, tables use the larger of native-child wait4 and sampled child VmHWM. Small gzip/pigz processes show disagreement near the1MiB launch floor; both measurements remain in the CSV/raw data, so sub-MiB precision is not claimed. The sampled component is a lower bound. Native clocks and pidfd exit notification avoid polling quantization. CLI process startup and interpreter memory remain included. Input hashes, peak/auxiliary digests and native SDK controls pass on both backends. The focused native suites pass25 Xerces/28 libxml2 tests, plus smoke/million-point/removal-guard checks. Runtime/tool/input/source/harness hashes bind every canonical record and resumed run; dependency paths are frozen independently of regenerated audit output. Both XML-backend mappings and distinct snapshot libraries are checked; neither timing nor RSS is claimed as isolated parser cost. This harness differs from the older warmup/RSS method, so cross-phase changes are not attributed solely to parser code.

The requested gaps now have measurements for these particular inputs/settings. Remaining scope limits are cold-storage I/O, timed XSD validation, new macOS compressed/real-input/decompression measurements, other acquisitions/IM encodings, exhaustive metadata equivalence and alternative streaming integration. The staged workflow is not integrated into product OpenMS. See [full summary](summary.csv), [all phases](all-comparisons.csv), controls/raw logs and [reproduction](reproduce/README.md).
"""
def readable(value):
    fixes = {
        "after412": "after 412", "workloads;279": "workloads; 279", "through96": "through 96", "At96": "At 96", "Random-read96": "Random-read 96",
        "excluded28": "excluded 28", "Linux96": "Linux 96", "contains64": "contains 64", "plus32": "plus 32",
        "versus460.8MB/s": "versus 460.8 MB/s", "/2.206GB": "/2.206 GB", "covering200": "covering 200", "than1GB": "than 1 GB",
        "the96": "the 96", "at1/96": "at 1/96", "at96": "at 96", "at1,": "at 1,",
        "setting1": "setting 1", "setting96": "setting 96", "create96": "create 96",
        "mean96": "mean 96", "the1MiB": "the 1 MiB", "additional4.505GB": "additional 4.505 GB",
        "or2.206GB": "or 2.206 GB", "additional4.505GB/2.206GB": "additional 4.505 GB/2.206 GB",
        "yielded420.0MB/s": "yielded 420.0 MB/s", "versus418.8MB/s": "versus 418.8 MB/s",
        "yielded356.2": "yielded 356.2", "TIMS600": "TIMS 600", "TIMS IM,600": "TIMS IM, 600",
        "CPU0": "CPU 0", "to96": "to 96", "inside0": "inside 0", "same1,126.2MB": "same 1,126.2 MB",
        "roughly5": "roughly 5", "about4": "about 4", "about5": "about 5", "about2": "about 2",
        "is7": "is 7", "window is about5": "window is about 5",
        "contain131": "contain 131", "and268": "and 268", "terms).": "terms).",
        "use256": "use 256", "reader,64": "reader, 64", "observed97": "observed 97",
        "compile/source": "compile/source",
    }
    for before, after in fixes.items():
        value = value.replace(before, after)
    return value


a.output.write_text(readable(text))
if a.concise_output:
    concise = f"""# XML replacement benchmark handoff

The user-requested reduced Linux phase contains **{P['workload_records']:,} workload runs / {P['native_processes']:,} native processes**, covering200 cells with three repetitions each. It compares the complete libxml2 replacement (`8f66b3d9`) with the optimized Xerces control (`58aa3734`), through96 requested threads. Correctness and final source/input/runtime checks passed. The original schedule was reduced after412 completed workloads;279 completed non-selected records remain supplemental evidence. The excluded28-record pilot is preserved separately.

Four matched files, each larger than1GB, represent plain XML, internal zlib, outer gzip and both compression layers. Real inputs cover a public Lumos DDA run, published PASEF without retained mobility, and a real TIMS600–1200s window with finite per-peak/scalar mobility. The latter uses OpenMS RATIONAL table calibration; it is not a proprietary-SDK equivalence claim.

Paired values below are **Xerces / libxml2**. MB is decimal; RSS MiB is binary. Streaming rates use the C++ workload clock. Each comparison uses the same cached input; unlike formats have different input-byte denominators.

"""
    short_rows = []
    for n, label in zip(names, labels):
        short_rows.append([
            label,
            pair("readers", n, "file_MB_per_s", workers=1),
            pair("readers", n, "native_peak_rss_mib_median", workers=1),
            pair("readers", n, "Mpoints_per_s", workers=96) if n != names[3] else "Not selected",
        ])
    concise += table([
        "Input", "One reader MB/s, X / L", "One reader peak MiB, X / L",
        "96 readers aggregate million points/s, X / L",
    ], short_rows)
    concise += "\n\n![Matched throughput and RSS](figures/matched-formats.png)\n\n"
    concise += "One-reader libxml2 is about4–6% slower on matched generated inputs and about5% faster on these real inputs. At96 readers its matched throughput is7–22% higher, DDA/PASEF is about2.5×/2.2×, while the IM window is about5% slower. These are descriptive ratios of medians for these inputs, not significance tests or universal parser rankings.\n\n"
    concise += "Whole-document RSS is close between backends. Libxml2 has lower indexed random-read peaks on these inputs but higher retained-context/index overhead. These are distinct workloads; neither establishes an across-the-board memory win. Whole-document and multi-reader indexed RSS, plus retained context/index overhead, are measured separately. The context estimate subtracts same-N idle RSS and includes index/allocator state; it is not isolated XML-context size. All settings and ranges are in the [combined table](all-comparisons.csv).\n\n"
    memory_rows = []
    for n in [names[0], names[4], names[6]]:
        memory_rows.append([
            labels[names.index(n)],
            pair("whole-document", n, "native_peak_rss_mib_median", omp=1),
            pair("random-access", n, "native_peak_rss_mib_median", workers=96),
            pair("retained-contexts", n, "idle_adjusted_retained_mib_per_reader", workers=96),
        ])
    concise += table([
        "Input", "Whole load peak MiB, X / L", "Random-read96 peak MiB, X / L",
        "Retained context/index MiB per reader at96, X / L",
    ], memory_rows) + "\n\n"
    decomp_rows = []
    for n in names[2:4]:
        for tool in ["gzip", "pigz", "rapidgzip"]:
            end = one("decompress", n, tool=tool, requested_threads=1 if tool == "gzip" else 96)
            decomp_rows.append([
                labels[names.index(n)], tool, end["requested_threads"],
                f(end["inflated_output_MB_per_s"]),
                f(end["native_peak_rss_mib_median"]),
            ])
    concise += table([
        "Single gzip file", "Tool", "Requested setting", "Inflated XML MB/s", "Peak RSS MiB",
    ], decomp_rows)
    concise += "\n\nCLI RSS uses max(native-child wait4, sampled child VmHWM); the sampled part is a lower bound. Small tools are near the1MiB launch floor, so do not infer sub-MiB precision. Pigz uses an ordinary single inflate stream plus helper threads: `-p96` does not mean96 parallel decoders. Rapidgzip uses its compiled decoder through a Python entry point; startup/interpreter costs remain included. External decompression followed by OpenMS is measured as sequential RAM-file staging, with the additional4.505GB/2.206GB file footprint reported separately.\n\n"
    concise += "![Cross-platform evidence](figures/platforms.png)\n\n"
    concise += "Earlier macOS evidence remains a separate phase: native-O3/UTF-8 yielded420.0MB/s for libxml2 versus418.8MB/s for Xerces on the same ASCII-body control; Latin-1 yielded356.2 versus460.8MB/s. Native builds and actual encoding deserve testing on macOS. The new compressed/real-data/decompression measurements are Linux-only. The Linux96-CPU set contains64 physical cores plus32 SMT siblings; observed thread counts and CPU consumption do not prove useful parallel decoding.\n\n"
    concise += "Remaining limits: cold-storage I/O, timed XSD validation, new macOS compressed/real/decompression runs, other acquisitions/IM encodings, exhaustive metadata equivalence and alternative product integration. Whole loads retain an MSExperiment; they do not benchmark a separate DOM API.\n\n"
    concise += f"[Detailed findings]({a.output.name}) · [Methods and reproduction](reproduce/README.md) · [Phase table](summary.csv) · [Combined table](all-comparisons.csv)\n"
    a.concise_output.write_text(readable(concise))
print("Handoff generated from", len(D), "summary cells")
