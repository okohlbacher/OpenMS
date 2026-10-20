"""Stop only the task-owned pilot launcher and descendants before identity-guard fix."""

import json, os, signal, time
from pathlib import Path

root = Path("/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb")
out = root / "results/gap"
parent = 3362704
# Stop the queued post-controller so it cannot act on a cancelled launch.
try:
    os.kill(3365415, signal.SIGTERM)
except ProcessLookupError:
    pass
states = {}
for p in Path("/proc").glob("[0-9]*/stat"):
    try:
        raw = p.read_text()
        fields = raw.split(") ", 1)[1].split()
        states[int(p.parent.name)] = (int(fields[1]), raw)
    except (OSError, ValueError, IndexError):
        pass
ids = {parent}
while True:
    new = {pid for pid, (ppid, _) in states.items() if ppid in ids} | ids
    if new == ids:
        break
    ids = new
receipt = dict(
    reason="Predeclared harness-only restart: freeze dependency-path identity instead of deriving it from an audit file rewritten by access preflight; add complete per-cell exception logging and SDK-matched fixture generation. Preserve all completed pilot records; none enter final canonical summaries.",
    unix=time.time(),
    launcher=parent,
    task_processes=sorted(ids),
    proc_stats={str(pid): states[pid][1] for pid in ids if pid in states},
)
(out / "pilot-stop-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
for pid in sorted(ids, reverse=True):
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
print("Stopped only task pilot process tree:", sorted(ids))
