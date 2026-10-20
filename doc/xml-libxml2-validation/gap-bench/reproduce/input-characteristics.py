"""Post-run read-only input declaration and mobility-CV inventory."""

import ctypes, gzip, hashlib, json, math, re, xml.etree.ElementTree as ET
from pathlib import Path

root = Path("/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb")
out = root / "results/gap"
names = json.loads((out / "inputs.json").read_text())
results = {}
N = "{http://psi.hupo.org/ms/mzml}"
for name in names:
    p = root / "data" / name
    with gzip.open(p, "rb") if name.endswith(".gz") else p.open("rb") as f:
        header = f.read(4096)
    match = re.search(rb'<\?xml[^>]*encoding=[\'"]([^\'"]+)', header)
    row = dict(
        xml_encoding_declaration=match.group(1).decode() if match else None, bytes=p.stat().st_size
    )
    if not name.startswith("large-matched"):
        stack = []
        counts = {}
        data_terms = {}
        for event, e in ET.iterparse(p, events=("start", "end")):
            if event == "start":
                stack.append(e)
                continue
            if e.tag == N + "cvParam" and any(
                word in e.get("name", "").lower()
                for word in ["mobility", "faims", "collisional cross section"]
            ):
                key = e.get("accession") + " " + e.get("name")
                counts[key] = counts.get(key, 0) + 1
                scalar = e.get("accession") in [
                    "MS:1002815",
                    "MS:1002476",
                    "MS:1001581",
                    "MS:1002954",
                ]
                value = e.get("value", "")
                finite_scalar = scalar and value and math.isfinite(float(value))
                if "array" in e.get("name", "").lower() or finite_scalar:
                    data_terms[key] = data_terms.get(key, 0) + 1
            e.clear()
            if len(stack) > 1:
                stack[-2].remove(e)
            stack.pop()
        row["mobility_related_cv_counts"] = counts
        row["mobility_array_or_finite_scalar_cv_counts"] = data_terms
        if name == "pasef-published.mzML":
            assert not data_terms, data_terms
    results[name] = row
versions = {}
for label, path in [
    ("OpenMS both backends", "/scratch/kohlbach/contrib/build/lib/libz.so.1"),
    ("system pigz", "/lib/x86_64-linux-gnu/libz.so.1"),
]:
    lib = ctypes.CDLL(path)
    lib.zlibVersion.restype = ctypes.c_char_p
    with open(path, "rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    versions[label] = dict(path=path, version=lib.zlibVersion().decode(), sha256=digest)
(out / "input-characteristics.json").write_text(
    json.dumps(
        dict(
            inputs=results,
            zlib_runtimes=versions,
            page_size_bytes=__import__("os").sysconf("SC_PAGESIZE"),
        ),
        indent=2,
    )
    + "\n"
)
print("Input declaration/CV inventory and actual zlib versions captured")
