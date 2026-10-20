#!/usr/bin/env python3
"""Publication figures, medians and observed ranges kept in the accompanying CSV."""

import argparse, json
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

p = argparse.ArgumentParser()
p.add_argument("summary", type=Path)
p.add_argument("output", type=Path)
p.add_argument("--historical-throughput", type=Path)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
D = json.loads(a.summary.read_text())
N = [1, 32, 64, 96]
B = ["xerces", "libxml2-full"]
C = {
    "xerces": "#c97728",
    "libxml2-full": "#217b9a",
    "gzip": "#777777",
    "pigz": "#9a4e99",
    "rapidgzip": "#27865c",
}
L = {
    "xerces": "Xerces",
    "libxml2-full": "Complete libxml2",
    "gzip": "gzip (1 thread)",
    "pigz": "pigz",
    "rapidgzip": "rapidgzip",
}
FILES = [
    "large-matched-plain.mzML",
    "large-matched-zlib.mzML",
    "large-matched-plain.mzML.gz",
    "large-matched-zlib.mzML.gz",
    "dda-lumos.mzML",
    "pasef-published.mzML",
    "pasef-im-600-1200s.mzML",
]
TITLES = [
    "Plain arrays",
    "Internal zlib",
    "Plain arrays + outer gzip",
    "Internal zlib + outer gzip",
    "Real DDA (Lumos)",
    "Published PASEF (no IM)",
    "Real TIMS IM (600–1200 s)",
]


def rows(kind, name=None, b=None, **where):
    return sorted(
        [
            r
            for r in D
            if r["kind"] == kind
            and (name is None or r["input"] == name)
            and (b is None or r.get("backend") == b)
            and all(r.get(k) == v for k, v in where.items())
        ],
        key=lambda r: r.get("requested_threads", r.get("workers", r.get("omp", 1))),
    )


def axis(ax, label="Concurrent in-process readers"):
    ax.set_xscale("log", base=2)
    ax.set_xticks(N, [str(n) for n in N])
    ax.set_xlabel(label)
    ax.grid(alpha=0.2)
    ax.set_axisbelow(True)
    ax.axvline(64, ls=":", lw=0.7, color="#999")


def save(fig, name, caption):
    fig.text(0.5, 0.008, caption, ha="center", fontsize=8)
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    for ext in ["png", "svg"]:
        fig.savefig(a.output / (name + "." + ext), dpi=180)
    plt.close(fig)


fig, axs = plt.subplots(2, 3, figsize=(14, 8))
for j, field in enumerate(["Mpoints_per_s", "file_MB_per_s", "native_peak_rss_mib_median"]):
    ax = axs[0, j]
    x = np.arange(4)
    for i, b in enumerate(B):
        yy = [rows("readers", f, b, workers=1)[0][field] for f in FILES[:4]]
        bars = ax.bar(x + (i - 0.5) * 0.36, yy, 0.34, color=C[b], label=L[b])
        ax.bar_label(bars, fmt="%.1f", fontsize=7, padding=3)
    ax.set_xticks(x, ["Plain", "Zlib", "Plain\n+ gzip", "Zlib\n+ gzip"])
    ax.set_title(
        [
            "Matched decoded work, one reader",
            "Actual input bytes, one reader",
            "Streaming native peak RSS, one reader",
        ][j]
    )
    ax.set_ylabel(["Million points/s", "Input MB/s", "MiB"][j])
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)
    if j == 0:
        ax.legend(fontsize=8)
for j, (name, title) in enumerate(
    zip([FILES[0], FILES[1], FILES[2]], ["Plain", "Internal zlib", "Plain + outer gzip"])
):
    ax = axs[1, j]
    for b in B:
        rr = rows("readers", name, b)
        ax.plot(
            [r["workers"] for r in rr],
            [r["Mpoints_per_s"] for r in rr],
            "o-",
            color=C[b],
            label=L[b],
            ms=4,
        )
    axis(ax)
    ax.set_title(title + " — same-file concurrency")
    ax.set_ylabel("Aggregate million points/s")
fig.suptitle(
    "Linux matched formats: 4.505 GB plain / 2.206 GB zlib / 1.948 & 1.370 GB gzip", fontsize=13
)
save(
    fig,
    "matched-formats",
    "3 fresh-process runs/cell; cached input. Workload time excludes shared warmup. 64 physical cores; 96 requested CPUs includes 32 SMT siblings.",
)
fig, axs = plt.subplots(2, 3, figsize=(14, 8))
for j, (name, title) in enumerate(zip(FILES[4:], TITLES[4:])):
    for b in B:
        rr = rows("readers", name, b)
        xx = [r["workers"] for r in rr]
        axs[0, j].plot(xx, [r["Mpoints_per_s"] for r in rr], "o-", color=C[b], label=L[b], ms=4)
        axs[1, j].plot(xx, [r["native_peak_rss_mib_median"] for r in rr], "o-", color=C[b], ms=4)
    for i in [0, 1]:
        axis(axs[i, j])
        axs[i, j].set_title(title)
    axs[0, j].set_ylabel("Aggregate million points/s")
    axs[1, j].set_ylabel("Native peak RSS (MiB)")
    axs[1, j].set_ylim(bottom=0)
axs[0, 0].legend(fontsize=8)
fig.suptitle(
    "Measured real acquisitions: throughput and streaming RSS through 96 readers", fontsize=13
)
save(
    fig,
    "real-acquisitions",
    "Real files have different acquisition content: compare backends within each input. IM is a real 10-min subset; no universal modality ranking.",
)
fig, axs = plt.subplots(2, 3, figsize=(14, 8))
for i, (name, title) in enumerate(zip(FILES[2:4], TITLES[2:4])):
    for tool in ["gzip", "pigz", "rapidgzip"]:
        rr = rows("decompress", name, tool=tool)
        xx = [r["requested_threads"] for r in rr]
        for j, field in enumerate(
            ["inflated_output_MB_per_s", "native_peak_rss_mib_median", "native_threads_median"]
        ):
            axs[i, j].plot(
                xx,
                [r[field] for r in rr],
                "o-" if tool != "gzip" else "s",
                color=C[tool],
                label=L[tool],
                ms=4,
            )
    for j in range(3):
        axis(axs[i, j], "Requested tool setting (-p / -P)")
        axs[i, j].set_title(title)
        axs[i, j].set_ylabel(
            [
                "Inflated XML output MB/s",
                "Native launch/tool peak RSS (MiB)",
                "Observed process threads (sampled)",
            ][j]
        )
        axs[i, j].set_ylim(bottom=0)
axs[0, 0].legend(fontsize=8)
fig.suptitle(
    "One ordinary gzip file: gzip, pigz and rapidgzip through requested 96 threads", fontsize=13
)
save(
    fig,
    "single-file-decompression",
    "3 fresh CLI processes/cell, CRC verified, no imported index. Full CLI startup included. Pigz thread setting does not imply parallel DEFLATE decoding.",
)
fig, axs = plt.subplots(2, 3, figsize=(14, 8))
for i, name in enumerate(FILES[2:4]):
    for b in B:
        baseline = rows("readers", name, b, workers=1)[0]
        axs[i, 0].axhline(
            baseline["end_to_end_file_MB_per_s"],
            color=C[b],
            ls=":",
            lw=1,
            label=L[b] + " internal gzip",
        )
        axs[i, 1].axhline(baseline["native_peak_rss_mib_median"], color=C[b], ls=":", lw=1)
        for tool in ["gzip", "pigz", "rapidgzip"]:
            rr = rows("staged-pipeline", name, b, tool=tool)
            xx = [r["requested_threads"] for r in rr]
            style = "-" if b == "libxml2-full" else "--"
            for j, field in enumerate(
                [
                    "compressed_input_MB_per_s",
                    "native_peak_rss_mib_median",
                    "tmpfs_file_plus_component_peak_mib_upper_bound",
                ]
            ):
                axs[i, j].plot(
                    xx,
                    [r[field] for r in rr],
                    marker="o",
                    ls=style,
                    color=C[tool],
                    label=L[tool] + " → " + L[b],
                    ms=3,
                )
    for j in range(3):
        axis(axs[i, j], "Requested decompressor setting")
        axs[i, j].set_title(TITLES[i + 2])
        axs[i, j].set_ylabel(
            [
                "End-to-end compressed input MB/s",
                "Max sequential component RSS (MiB)",
                "File RAM + component peak upper bound (MiB)",
            ][j]
        )
        axs[i, j].set_ylim(bottom=0)
axs[0, 0].legend(fontsize=6, ncol=2)
fig.suptitle("External decompression → regular RAM file → OpenMS: sequential staging", fontsize=13)
save(
    fig,
    "staged-pipeline",
    "Same end-to-end process-clock basis. No FIFO/streaming-pipeline claim. RAM file adds 4.505 GB or 2.206 GB beyond component RSS; final column is an upper bound.",
)
fig, axs = plt.subplots(2, 3, figsize=(14, 8))
for j, name in enumerate([FILES[0], FILES[1], FILES[-1]]):
    for b in B:
        rr = rows("random-access", name, b)
        xx = [r["workers"] for r in rr]
        axs[0, j].plot(
            xx, [r["aggregate_queries_per_s"] for r in rr], "o-", color=C[b], label=L[b], ms=4
        )
        axs[1, j].plot(xx, [r["native_peak_rss_mib_median"] for r in rr], "o-", color=C[b], ms=4)
    for i in [0, 1]:
        axis(axs[i, j])
        axs[i, j].set_title(TITLES[FILES.index(name)])
    axs[0, j].set_ylabel("Aggregate queries/s, including open")
    axs[1, j].set_ylabel("Native peak RSS (MiB)")
    axs[1, j].set_ylim(bottom=0)
axs[0, 0].legend(fontsize=8)
fig.suptitle("New large/real indexed inputs: random reads and RSS through 96 readers", fontsize=13)
save(
    fig,
    "random-access",
    "Each reader owns index/file state; deterministic 256 queries (IM64). Fast open skips full metadata. Outer gzip is not an indexed-input path.",
)
fig, axs = plt.subplots(1, 3, figsize=(14, 4.8))
for j, name in enumerate([FILES[0], FILES[1], FILES[-1]]):
    for b in B:
        rr = rows("retained-contexts", name, b)
        axs[j].plot(
            [r["workers"] for r in rr],
            [r["idle_adjusted_retained_mib_per_reader"] for r in rr],
            "o-",
            color=C[b],
            label=L[b],
            ms=4,
        )
    axis(axs[j])
    axs[j].set_title(TITLES[FILES.index(name)])
    axs[j].set_ylabel("Idle-adjusted retained MiB / reader")
axs[0].legend(fontsize=8)
fig.suptitle("Per-reader context/index overhead after joining, contexts retained", fontsize=13)
save(
    fig,
    "context-overhead",
    "(median resident RSS contexts − median resident RSS idle at sameN)/N. Includes index/allocator state, not isolated native XML parser context; statm approximate.",
)
fig, axs = plt.subplots(1, 2, figsize=(14, 5.6))
xx = np.arange(7)
for j, field in enumerate(["file_MB_per_s", "native_peak_rss_mib_median"]):
    for i, (b, omp) in enumerate([(B[0], 1), (B[1], 1), (B[0], 96), (B[1], 96)]):
        yy = [rows("whole-document", name, b, omp=omp)[0][field] for name in FILES]
        axs[j].bar(
            xx + (i - 1.5) * 0.2,
            yy,
            0.19,
            color=C[b],
            alpha=1 if omp == 1 else 0.45,
            label=L[b] + f" OMP{omp}",
        )
    axs[j].set_xticks(
        xx,
        ["Plain", "Zlib", "Plain\n+ gzip", "Zlib\n+ gzip", "DDA", "PASEF", "TIMS IM"],
        fontsize=9,
    )
    axs[j].set_ylabel(["Actual input MB/s", "Native peak RSS (MiB)"][j])
    axs[j].set_ylim(bottom=0)
    axs[j].grid(axis="y", alpha=0.2)
    axs[j].set_axisbelow(True)
axs[0].legend(fontsize=8)
fig.suptitle("Whole-document load: one retained experiment, OpenMP 1 vs 96", fontsize=13)
save(
    fig,
    "whole-document",
    "3 fresh-process runs/cell. Whole-file load + decoded digest work. Requested OpenMP team is separate from concurrent whole-document readers.",
)
if a.historical_throughput:
    old = json.loads(a.historical_throughput.read_text())
    fig, axs = plt.subplots(1, 2, figsize=(13, 5.4))
    cases = [
        ("Linux Latin-1", "linux_encoding", "large.mzML"),
        ("Linux UTF-8", "linux_encoding", "large-utf8.mzML"),
        ("macOS Latin-1", "macos_native_encoding", "large.mzML"),
        ("macOS UTF-8", "macos_native_encoding", "large-utf8.mzML"),
    ]
    xx = np.arange(4)
    for i, b in enumerate(B):
        yy = []
        for _, group, name in cases:
            backend = (B if group == "linux_encoding" else ["xerces-native-o3", "full-o3"])[i]
            yy.append(
                next(
                    r["derived_file_MB_per_s"]
                    for r in old[group]
                    if r["input_name"] == name and r["backend"] == backend
                )
            )
        bars = axs[0].bar(xx + (i - 0.5) * 0.36, yy, 0.34, color=C[b], label=L[b])
        axs[0].bar_label(bars, fmt="%.0f", fontsize=8, padding=3)
    axs[0].set_xticks(xx, [r[0] for r in cases], rotation=12, fontsize=9)
    axs[0].set_ylabel("Input MB/s")
    axs[0].set_title("Prior native −O3 encoding controls\nSame 1,126.2 MB ASCII-body input")
    axs[0].legend(fontsize=8)
    xx = np.arange(4)
    for i, b in enumerate(B):
        bars = axs[1].bar(
            xx + (i - 0.5) * 0.36,
            [rows("readers", f, b, workers=1)[0]["Mpoints_per_s"] for f in FILES[:4]],
            0.34,
            color=C[b],
        )
        axs[1].bar_label(bars, fmt="%.1f", fontsize=8, padding=3)
    axs[1].set_xticks(xx, ["Plain", "Zlib", "Plain\n+ gzip", "Zlib\n+ gzip"])
    axs[1].set_ylabel("Million points/s")
    axs[1].set_title(
        "New Linux matched 4.505 GB plain-equivalent data\nAll four actual files ≥1 GB, one reader"
    )
    fig.suptitle(
        "Cross-platform evidence with phase and workload boundaries preserved", fontsize=13
    )
    save(
        fig,
        "platforms",
        "Left: existing Linux EPYC/macOS M4 Max encoding controls. Right: new Linux-only compressed-input phase. No new macOS compressed/real-data results.",
    )
fig, axs = plt.subplots(2, 2, figsize=(11.5, 7.5))
for i, name in enumerate(FILES[:2]):
    for b in B:
        rr = sorted(rows("single-file-openmp", name, b), key=lambda r: r["omp"])
        xx = [r["omp"] for r in rr]
        one = next(r["workload_seconds_median"] for r in rr if r["omp"] == 1)
        axs[i, 0].plot(
            xx, [one / r["workload_seconds_median"] for r in rr], "o-", color=C[b], label=L[b], ms=4
        )
        axs[i, 1].plot(xx, [r["native_peak_rss_mib_median"] for r in rr], "o-", color=C[b], ms=4)
    for j in [0, 1]:
        axis(axs[i, j], "Requested OpenMP threads; one file/reader")
        axs[i, j].set_title(TITLES[i])
    axs[i, 0].set_ylabel("Fixed-work speedup vs1 thread")
    axs[i, 0].axhline(1, color="#999", lw=0.8)
    axs[i, 1].set_ylabel("Native peak RSS (MiB)")
    axs[i, 1].set_ylim(bottom=0)
axs[0, 0].legend(fontsize=8)
fig.suptitle("Single-file OpenMP scaling, independent of reader concurrency", fontsize=13)
save(
    fig,
    "single-file-openmp",
    "Only endpoints 1/96 measured. Main warmup uses 1 thread. Each worker sets the requested team; 96-thread controls observed 97 process threads, not the prior 192 retained-team count.",
)
