"""Regression gate: regenerating observational access audits cannot change identity."""

import importlib.util, json, subprocess
from pathlib import Path

root = Path("/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb")
spec = importlib.util.spec_from_file_location("gap", root / "run-gap.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
first = g.bind_identity()
subprocess.run(["/usr/bin/python3", str(root / "run-access.py"), "--preflight"], check=True)
second = g.bind_identity()
assert first == second
(g.OUT / "identity-rewrite-test.json").write_text(
    json.dumps(
        {
            "identity_before": first,
            "identity_after": second,
            "access_audit_rewritten": True,
            "unchanged": first == second,
        },
        indent=2,
    )
    + "\n"
)
(g.OUT / "IDENTITY_REWRITE_TEST_COMPLETE").touch()
print("Identity remains stable across regenerated indexed audit")
