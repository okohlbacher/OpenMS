from pathlib import Path
import hashlib, json

root = Path("/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb")
manifest = json.loads((root / "staging/source-input-manifest.json").read_text())
checks = {}
for name, item in manifest["files"].items():
    path = root / ("data" if name.startswith("benchmark-data/") else "staging") / Path(name).name
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == item["sha256"], path
    checks[str(path)] = {"bytes": path.stat().st_size, "sha256": digest}
(root / "results/input-verification.json").write_text(json.dumps(checks, indent=2) + "\n")
print("Verified archives and input hashes", len(checks))
