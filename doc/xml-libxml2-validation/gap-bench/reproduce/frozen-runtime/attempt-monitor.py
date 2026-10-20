"""Preserve launch-level failures, including exceptions before a cell can be written."""

import hashlib, json, os, time
from pathlib import Path

root = Path("/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb")
out = root / "results/gap"
pid = int((out / "launcher.pid").read_text())
path = out / "attempts.jsonl"


def write(row):
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()
        os.fsync(f.fileno())


proc = Path(f"/proc/{pid}/stat")
state = proc.read_text()
write(
    dict(
        event="observed-running",
        launcher_pid=pid,
        launcher_proc_stat=state,
        observed_unix=time.time(),
        note="Corrected canonical launch. The superseded28-record pilot and operator-stop receipt are retained separately and excluded from final summaries.",
    )
)
while proc.exists():
    try:
        if proc.read_text().split(") ", 1)[1].split()[0] == "Z":
            break
    except FileNotFoundError:
        break
    if (out / "ALL_MEASUREMENTS_COMPLETE").exists():
        break
    time.sleep(30)
complete = (out / "ALL_MEASUREMENTS_COMPLETE").exists()
logs = {}
for name in ["gap-launch-final.log", "gap-matrix.log", "gap-access.log"]:
    p = root / "logs" / name
    if p.exists():
        logs[name] = dict(
            sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
            bytes=p.stat().st_size,
            traceback="Traceback (most recent call last)" in p.read_text(),
        )
write(
    dict(
        event="finished",
        launcher_pid=pid,
        status="complete" if complete else "failed-or-interrupted",
        completed_unix=time.time(),
        logs=logs,
    )
)
