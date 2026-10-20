"""CLI startup control, not a volume-throughput benchmark."""

import gzip, importlib.util, json
from pathlib import Path

spec = importlib.util.spec_from_file_location("gap", Path(__file__).with_name("run-gap.py"))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
p = g.ROOT / "tmp/empty.gz"
with p.open("wb") as f:
    with gzip.GzipFile(filename="", fileobj=f, mode="wb", mtime=0) as z:
        z.write(b"")
rows = []
for rep in range(5):
    for tool in ["gzip", "pigz", "rapidgzip"]:
        for n in ([1] if tool == "gzip" else [1, 96]):
            r = g.require(g.inflate(p, tool, n))
            r.update(tool=tool, requested_threads=n, rep=rep)
            rows.append(r)
(g.OUT / "cli-startup-controls.json").write_text(json.dumps(rows, indent=2) + "\n")
p.unlink()
print("25 zero-work CLI controls completed; startup is not subtracted from canonical timings")
