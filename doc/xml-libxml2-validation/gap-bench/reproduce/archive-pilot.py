import json, shutil, time
from pathlib import Path

root = Path("/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb")
out = root / "results/gap"
pilot = out / "pilot-before-identity-fix"
pilot.mkdir(exist_ok=True)
# Preserve the complete pilot records, initial identity and its sampled dependency controls.
for name in [
    "records.jsonl",
    "schedule.json",
    "resources.jsonl",
    "measurement-identity.json",
    "frozen-runner.sha256",
    "attempts.jsonl",
    "pilot-stop-receipt.json",
]:
    p = out / name
    if p.exists():
        shutil.move(str(p), str(pilot / name))
for name in ["gap-matrix.log", "gap-launch-final.log", "attempt-monitor.log"]:
    p = root / "logs" / name
    if p.exists():
        shutil.copy2(p, pilot / name)
for name in ["run-gap.py", "run-access.py", "native-meter.cpp", "native-meter"]:
    shutil.copy2(root / name, pilot / name)
for name in [
    "correctness-audits.json",
    "indexed-correctness.json",
    "final-decompressor-correctness.json",
    "inputs.json",
]:
    shutil.copy2(out / name, pilot / name)
paths = set()
rows = [json.loads(l) for l in (pilot / "records.jsonl").read_text().splitlines()]
for r in rows:
    for x in ([r["decompress"], r["parse"]] if r["cell"]["kind"] == "staged-pipeline" else [r]):
        paths.update(p for p in x["loaded_library_maps"] if Path(p).is_file())
for name in [
    "correctness-audits.json",
    "indexed-correctness.json",
    "final-decompressor-correctness.json",
]:
    for r in json.loads((out / name).read_text()):
        paths.update(p for p in r["loaded_library_maps"] if Path(p).is_file())
(out / "identity-dependency-paths.json").write_text(json.dumps(sorted(paths), indent=2) + "\n")
(pilot / "README.md").write_text(
    "# Superseded pilot, excluded from canonical summaries\n\n28 completed workload records from the first measurement protocol are retained verbatim. The next in-flight cell was operator-stopped to fix a configuration-identity guard before the long final run. No parser mismatch or timed I/O fault prompted the restart. All cells will be remeasured under one final identity. Original logs, launch/stop receipt, runtime sources and sampled dependencies remain here. Fixture generation will also be checked under its matching SDK.\n"
)
print("Archived pilot records", len(rows), "fixed dependency paths", len(paths))
