#!/usr/bin/env python3
"""Whole-document RSS and indexed access/context scaling on the new inputs.
Separate supplement: random queries are fixed per worker, not whole-file MB/s.
"""

import importlib.util, json, os, random, time, threading
from pathlib import Path

spec = importlib.util.spec_from_file_location("gap", Path(__file__).with_name("run-gap.py"))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def call(name, backend, mode, n=1, omp=1):
    queries = 64 if name == "pasef-im-600-1200s.mzML" else 256
    return g.require(
        g.measure(
            [g.LAUNCHER, g.BINARY, mode, g.ROOT / "data" / name, n, queries], g.env(backend, omp)
        )
    )


def main(preflight=False):
    assert (g.OUT / "references.json").exists()
    os.sched_setaffinity(0, set(range(96, 128)))
    identity_sha = g.bind_identity() if not preflight else None
    reference = json.loads((g.OUT / "references.json").read_text())
    indexed = {}
    index_counts = {}
    controls = []
    names = [n for n in g.FILES if not n.endswith(".gz")]
    for name in names:
        for backend in g.BACKENDS:
            r = call(name, backend, "indexed")
            f = g.fingerprint(r)
            if name in indexed:
                assert indexed[name] == f, (name, backend)
            indexed[name] = f
            index_counts[name] = (r["index_spectra"], r["index_chromatograms"])
            r.update(input=name, backend=backend)
            controls.append(r)
    (g.OUT / "indexed-correctness.json").write_text(json.dumps(controls, indent=2) + "\n")
    (g.OUT / "ACCESS_PREFLIGHT_COMPLETE").touch()
    if preflight:
        return
    cells = []
    for rep in range(5):
        for name in g.FILES:
            for backend in g.BACKENDS:
                for omp in [1, 96]:
                    cells.append(
                        dict(
                            kind="whole-document",
                            mode="load",
                            input=name,
                            backend=backend,
                            workers=1,
                            omp=omp,
                            rep=rep,
                        )
                    )
        for name in names:
            for backend in g.BACKENDS:
                for n in g.THREADS:
                    for mode in ["indexed", "contexts"]:
                        cells.append(
                            dict(
                                kind="random-access" if mode == "indexed" else "retained-contexts",
                                mode=mode,
                                input=name,
                                backend=backend,
                                workers=n,
                                omp=1,
                                rep=rep,
                            )
                        )
        for backend in g.BACKENDS:
            for n in g.THREADS:
                cells.append(
                    dict(
                        kind="idle",
                        mode="idle",
                        input=names[0],
                        backend=backend,
                        workers=n,
                        omp=1,
                        rep=rep,
                    )
                )
    random.Random(20261021).shuffle(cells)
    path = g.OUT / "access-records.jsonl"
    done = set()

    def key(c):
        return json.dumps(c, sort_keys=True)

    if path.exists():
        for line in path.read_text().splitlines():
            r = json.loads(line)
            if r["ok"]:
                assert r["measurement_identity_sha256"] == identity_sha
                done.add(key(r["cell"]))
    (g.OUT / "access-schedule.json").write_text(json.dumps(cells, indent=2) + "\n")
    stop = threading.Event()
    mon = threading.Thread(target=g.monitor, args=(stop,), daemon=True)
    mon.start()
    try:
        with path.open("a", buffering=1) as f:
            for i, c in enumerate(cells):
                if key(c) in done:
                    continue
                with g.cell_attempt(c):
                    cache = g.cached_input(g.ROOT / "data" / c["input"])
                    r = call(c["input"], c["backend"], c["mode"], c["workers"], c["omp"])
                    if c["mode"] == "load":
                        assert g.fingerprint(r) == tuple(reference[c["input"]]), c
                    elif c["mode"] == "indexed":
                        assert g.fingerprint(r) == indexed[c["input"]], c
                    elif c["mode"] == "contexts":
                        assert (r["index_spectra"], r["index_chromatograms"]) == index_counts[
                            c["input"]
                        ], c
                    g.validate_backend(r, c["backend"])
                    r.update(
                        cell=c,
                        measurement_identity_sha256=identity_sha,
                        input_cache_before=cache,
                        completed_unix=time.time(),
                    )
                    f.write(json.dumps(r, sort_keys=True) + "\n")
                    os.fsync(f.fileno())
                    print(f'{i+1}/{len(cells)} {c} {r["process_seconds"]:.3f}s', flush=True)
    finally:
        stop.set()
        mon.join()
    assert g.bind_identity() == identity_sha
    (g.OUT / "ACCESS_COMPLETE").touch()


if __name__ == "__main__":
    import sys

    main("--preflight" in sys.argv)
