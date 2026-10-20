from pathlib import Path
import json, subprocess

root = Path(__file__).resolve().parents[3]
manifest = json.loads((root / "results/context-memory/reproduce/real-input-manifest.json").read_text())
remote = "kohlbach@ibminode05"
base = "/scratch/kohlbach/openms-context-memory-20261020-01a153cb/data"
ssh = [
    "ssh",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=15",
    "-J",
    "kohlbach@sshgw.cs.uni-tuebingen.de",
]
subprocess.run(ssh + [remote, "mkdir -p " + base + "/SBA415.d"], check=True)
with (root / "results/context-memory/logs/real-transfer.log").open("w") as log:
    for r in manifest["files"]:
        subprocess.run(
            [
                "rsync",
                "-a",
                "-e",
                "ssh -o BatchMode=yes -o ConnectTimeout=15 -J kohlbach@sshgw.cs.uni-tuebingen.de",
                r["local_source"],
                remote + ":" + base + "/" + r["destination"],
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
        print("Copied", r["destination"], flush=True)
subprocess.run(
    [
        "rsync",
        "-a",
        "-e",
        "ssh -o BatchMode=yes -o ConnectTimeout=15 -J kohlbach@sshgw.cs.uni-tuebingen.de",
        str(root / "results/context-memory/reproduce/real-input-manifest.json"),
        remote + ":/scratch/kohlbach/openms-context-memory-20261020-01a153cb/staging/",
    ],
    check=True,
)
print("All real data staged")
