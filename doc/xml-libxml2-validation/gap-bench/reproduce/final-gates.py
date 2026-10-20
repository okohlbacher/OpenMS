"""Verify the final clean-env inflaters, audit assertions and RT window before timing."""

import importlib.util, json, math, xml.etree.ElementTree as ET
from pathlib import Path

spec = importlib.util.spec_from_file_location("gap", Path(__file__).with_name("run-gap.py"))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
a = json.loads((g.OUT / "correctness-audits.json").read_text())
group = {}
for r in a:
    g.validate_backend(r, r["backend"])
    group.setdefault(r["input"], []).append(r)
assert all((g.ROOT / "data" / n).stat().st_size >= 1_000_000_000 for n in g.FILES[:4])
assert all(
    (r["spectra_per_worker"], r["chromatograms_per_worker"], r["points_per_worker"])
    == (131072, 1, 131072 * 2048 + 131072)
    for n in g.FILES[:4]
    for r in group[n]
)
assert len({r["aux_hash_per_worker"] for n in g.FILES[:4] for r in group[n]}) == 1
assert all(
    r["im_array_values_per_worker"] == r["im_scalar_spectra_per_worker"] == 0
    for r in group["pasef-published.mzML"]
)
assert all(
    r["im_array_values_per_worker"] > 100_000_000 and r["im_scalar_spectra_per_worker"] > 20_000
    for r in group["pasef-im-600-1200s.mzML"]
)
# RT bounds and precursor scalar-IM presence are an independent XML metadata audit.
N = "{http://psi.hupo.org/ms/mzml}"
times = []
precursor_im = 0
stack = []
for event, e in ET.iterparse(g.ROOT / "data/pasef-im-600-1200s.mzML", events=("start", "end")):
    if event == "start":
        stack.append(e)
        continue
    if e.tag == N + "spectrum":
        for scan in e.findall(".//" + N + "scan"):
            for cv in scan.findall(N + "cvParam"):
                if cv.get("accession") == "MS:1000016":
                    t = float(cv.get("value"))
                    t *= 60 if cv.get("unitAccession") == "UO:0000031" else 1
                    times.append(t)
        for precursor in e.findall(".//" + N + "precursor"):
            for cv in precursor.findall(".//" + N + "cvParam"):
                if cv.get("accession") in ["MS:1002815", "MS:1002476"] and math.isfinite(
                    float(cv.get("value"))
                ):
                    precursor_im += 1
        e.clear()
        if len(stack) > 1:
            stack[-2].remove(e)
    stack.pop()
assert times and min(times) >= 600 and max(times) <= 1200, (min(times), max(times))
metadata = dict(
    spectra_with_rt=len(times),
    min_rt_seconds=min(times),
    max_rt_seconds=max(times),
    finite_precursor_im_cv_terms=precursor_im,
    note="Independent XML metadata audit; decoded per-peak/scalar IM equivalence is checked by both OpenMS backends. Not exhaustive equivalence of every metadata field.",
)
(g.OUT / "im-window-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
g.SHM.mkdir(exist_ok=True)
target = g.SHM / "final-inflater-correctness.xml"
rows = []
for name in g.FILES[2:4]:
    expected = g.sha(g.ROOT / "data" / name[:-3])
    for tool in ["gzip", "pigz", "rapidgzip"]:
        for n in ([1] if tool == "gzip" else [1, 96]):
            r = g.require(g.inflate(g.ROOT / "data" / name, tool, n, target))
            actual = g.sha(target)
            assert (
                actual == expected
                and r["output_bytes"] == (g.ROOT / "data" / name[:-3]).stat().st_size
            )
            assert not any(
                "OpenMS" in p or str(g.ROOT / "dependencies") in p or "/contrib/" in p
                for p in r["loaded_library_maps"]
            )
            r.update(input=name, tool=tool, requested_threads=n, output_sha256=actual)
            rows.append(r)
            target.unlink()
            print("FINAL INFLATER VERIFIED", name, tool, n, flush=True)
(g.OUT / "final-decompressor-correctness.json").write_text(json.dumps(rows, indent=2) + "\n")
floor = g.require(g.measure(["/usr/bin/true"], g.BASE))
(g.OUT / "native-supervisor-floor.json").write_text(json.dumps(floor, indent=2) + "\n")
(g.OUT / "FINAL_GATES_COMPLETE").touch()
print("Final gates completed")
