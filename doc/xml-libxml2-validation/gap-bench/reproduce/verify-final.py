import datetime, hashlib, importlib.util, json, tarfile, subprocess
from pathlib import Path

root = Path("/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb")
out = root / "results/gap"
assert (out / "ALL_MEASUREMENTS_COMPLETE").exists()
manifest = json.loads((root / "staging/source-input-manifest.json").read_text())
backends = {}
for backend in ["xerces", "libxml2-full"]:
    archive = root / "staging" / (backend + ".tar.gz")
    expected = manifest["files"]["results/full-scaling/staging/" + backend + ".tar.gz"]["sha256"]
    with archive.open("rb") as f:
        assert hashlib.file_digest(f, "sha256").hexdigest() == expected
    differences = []
    n = 0
    with tarfile.open(archive) as tar:
        for m in tar:
            if not m.isfile():
                continue
            n += 1
            p = root / ("source-" + backend) / m.name
            expected_file = hashlib.sha256(tar.extractfile(m).read()).hexdigest()
            if not p.is_file():
                differences.append(m.name)
                continue
            with p.open("rb") as f:
                if hashlib.file_digest(f, "sha256").hexdigest() != expected_file:
                    differences.append(m.name)
    backends[backend] = dict(
        archive_sha256=expected, regular_files=n, all_match=not differences, differences=differences
    )
assert all(v["all_match"] for v in backends.values()), backends
spec = importlib.util.spec_from_file_location("gap", root / "run-gap.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
identity_sha = g.bind_identity()
payload = json.loads((out / "measurement-identity.json").read_text())
frozen_paths = json.loads((out / "identity-dependency-paths.json").read_text())
assert all(Path(p).is_file() for p in frozen_paths), "Frozen dependency path missing"
bound_realpaths = {row["realpath"] for row in payload["files"].values()}
metadata = json.loads((out / "im-window-metadata.json").read_text())
references = json.loads((out / "references.json").read_text())
assert metadata["spectra_with_rt"] == references["pasef-im-600-1200s.mzML"][0]

rows = []
for filename in ["records.jsonl", "access-records.jsonl"]:
    rows.extend(json.loads(l) for l in (out / filename).read_text().splitlines())
assert all(r["ok"] for r in rows)
selected = []
for filename in ["reduced-primary-schedule.json", "reduced-access-schedule.json"]:
    selected.extend(json.loads((out / filename).read_text()))
key = lambda c: json.dumps(c, sort_keys=True)
assert len(selected) == 600 and len({key(c) for c in selected}) == 600
by_cell = {key(r["cell"]): r for r in rows}
assert len(by_cell) == len(rows), "Duplicate raw cells"
assert all(key(c) in by_cell for c in selected), "Missing selected workload"
selected_rows = [by_cell[key(c)] for c in selected]
assert len(selected_rows) + sum(r["cell"]["kind"] == "staged-pipeline" for r in selected_rows) == 660
launch = json.loads((out / "reduced-launch.json").read_text())
assert launch["status"] == "complete"
assert launch["scheduler_sha256"] == hashlib.sha256((root / "reduced-schedule.py").read_bytes()).hexdigest()
assert launch["measurement_identity_sha256"] == identity_sha
assert {r["measurement_identity_sha256"] for r in rows} == {identity_sha}
for r in rows:
    assert r["input_cache_before"]["resident_file_bytes"] == r["input_cache_before"]["file_bytes"]
    native = [r["decompress"], r["parse"]] if r["cell"]["kind"] == "staged-pipeline" else [r]
    assert all(v["native_exit_code"] == 0 for v in native)
    for v in native:
        for path in v["loaded_library_maps"]:
            assert Path(path).is_file(), (r["cell"], "Mapped library no longer exists", path)
            assert str(Path(path).resolve()) in bound_realpaths, (
                r["cell"],
                "Unbound mapped library",
                path,
            )

for h in ["libxml2-full", "xerces"]:
    frozen = (root / "results" / f"{h}-libraries.sha256").read_text()
    for line in frozen.splitlines():
        expected, p = line.split(maxsplit=1)
        with open(p, "rb") as f:
            assert hashlib.file_digest(f, "sha256").hexdigest() == expected
receipt = dict(
    utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    source_archives=backends,
    measurement_identity_sha256=identity_sha,
    canonical_workloads=len(selected_rows),
    preserved_total_workloads=len(rows),
    canonical_native_processes=660,
    all_preserved_native_processes=len(rows) + sum(r["cell"]["kind"] == "staged-pipeline" for r in rows),
    inputs_and_timed_dlls_unchanged=True,
    all_input_pages_resident_before_each_cell=True,
    all_observed_mapped_libraries_bound_to_frozen_identity=True,
    im_xml_rt_terms_equal_decoded_spectrum_count=True,
)
(out / "final-verification.json").write_text(json.dumps(receipt, indent=2) + "\n")
print("All final source/input/DLL/cell/identity gates passed")

subprocess.run(
    ["/usr/bin/python3", str(root / "post-control-source/input-characteristics.py")], check=True
)
