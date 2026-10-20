#!/usr/bin/env python3
"""Serial fresh-process gap matrix. Never run alongside build/conversion/preparation.
Native benchmark VmHWM is authoritative; wait4 retains its inherited parent floor.
CLI RSS uses a small native fork supervisor; sampled VmHWM is a cross-check. Sequential staging uses max RSS plus tmpfs bytes.
"""

import argparse, contextlib, hashlib, json, os, random, select, signal, subprocess, tempfile, time, threading, traceback
from pathlib import Path

ROOT = Path("/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb")
OUT = ROOT / "results/gap"
OUT.mkdir(exist_ok=True)
SHM = Path("/dev/shm/openms-xml-gap-bench-kohlbach-20261020-01a153cb")
BINARY = ROOT / "extended-benchmark-build/xml_parser_benchmark"
LAUNCHER = BINARY.with_name("xml_benchmark_launcher")
THREADS = [1, 2, 4, 8, 16, 32, 64, 96]
BACKENDS = ["xerces", "libxml2-full"]
FILES = [
    "large-matched-plain.mzML",
    "large-matched-zlib.mzML",
    "large-matched-plain.mzML.gz",
    "large-matched-zlib.mzML.gz",
    "dda-lumos.mzML",
    "pasef-published.mzML",
    "pasef-im-600-1200s.mzML",
]
BASE = dict(PATH="/usr/bin:/bin", HOME=os.environ["HOME"], TMPDIR=str(ROOT / "tmp"))
BASE.update(
    OMP_DYNAMIC="FALSE",
    OPENBLAS_NUM_THREADS="1",
    MKL_NUM_THREADS="1",
    BLIS_NUM_THREADS="1",
    VECLIB_MAXIMUM_THREADS="1",
    OPENMS_TMPDIR=str(ROOT / "tmp"),
    LC_ALL="C.UTF-8",
)


def sha(p):
    with open(p, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def env(backend="libxml2-full", omp=1):
    e = BASE.copy()
    e.update(
        OMP_NUM_THREADS=str(omp),
        LD_LIBRARY_PATH=f"{ROOT}/snapshots/{backend}/lib:{ROOT}/dependencies/install/lib:/scratch/kohlbach/contrib/build/lib",
    )
    return e


def measure(cmd, environment, output=None, timeout=7200):
    """Sample status of the actual PID, excluding Python-parent inherited wait4 RSS."""
    with tempfile.TemporaryDirectory(
        dir=ROOT / "tmp"
    ) as directory, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        directory = Path(directory)
        pidfile = directory / "pid"
        usagefile = directory / "usage.json"
        destination = open(output, "wb") if output else stdout
        start = time.perf_counter()
        p = subprocess.Popen(
            [
                "/usr/bin/taskset",
                "-c",
                "0-95",
                str(ROOT / "native-meter"),
                str(pidfile),
                str(usagefile),
                *map(str, cmd),
            ],
            stdout=destination,
            stderr=stderr,
            env=environment,
            start_new_session=True,
        )
        pidfd = os.pidfd_open(p.pid)
        peak = threads = 0
        maps = []
        affinity = None
        samples = 0
        timedout = False
        while True:
            try:
                pid = int(pidfile.read_text())
                status = Path(f"/proc/{pid}/status").read_text()
                values = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
                # taskset/launcher mm can briefly precede exec; these are native tiny programs.
                peak = max(peak, int(values.get("VmHWM", "0 kB").split()[0]) * 1024)
                threads = max(threads, int(values.get("Threads", "0")))
                samples += 1
                affinity = values.get("Cpus_allowed_list", "").strip()
                if samples % 10 == 0 or not maps:
                    mapped = [
                        line.split()[-1]
                        for line in Path(f"/proc/{pid}/maps").read_text().splitlines()
                        if ".so" in line
                    ]
                    maps = sorted(set(maps + mapped))
            except (OSError, ValueError):
                pass
            child, status, usage = os.wait4(p.pid, os.WNOHANG)
            if child:
                break
            if time.perf_counter() - start > timeout:
                os.killpg(p.pid, signal.SIGKILL)
                child, status, usage = os.wait4(p.pid, 0)
                timedout = True
                break
            select.select([pidfd], [], [], 0.01)
        elapsed = time.perf_counter() - start
        os.close(pidfd)
        p.returncode = os.waitstatus_to_exitcode(status)
        if output:
            destination.close()
        stdout.seek(0)
        stderr.seek(0)
        s = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        row = dict(
            ok=p.returncode == 0 and not timedout,
            exit_code=p.returncode,
            process_seconds=elapsed,
            user_seconds=usage.ru_utime,
            system_seconds=usage.ru_stime,
            wait4_max_rss_bytes=usage.ru_maxrss * 1024,
            sampled_native_hwm_bytes=peak,
            sampled_native_threads=threads,
            procfs_samples=samples,
            cpu_affinity=affinity,
            loaded_library_maps=maps,
            command=list(map(str, cmd)),
            stderr=err[-16384:],
            timed_out=timedout,
        )
        lines = [l for l in s.splitlines() if l.startswith("{")]
        if lines:
            objects = [json.loads(line) for line in lines]
            protocol = [
                obj
                for obj in objects
                if isinstance(obj, dict)
                and (("mode" in obj and "hash_per_worker" in obj) or "verified" in obj)
            ]
            assert len(protocol) == 1, objects
            row.update(protocol[0])
        elif s:
            row["stdout"] = s[-16384:]
        if usagefile.exists():
            row.update(json.loads(usagefile.read_text()))
        if output and output != "/dev/null":
            row["output_bytes"] = Path(output).stat().st_size
        return row


def bench(file, backend, workers=1, omp=1, mode="stream"):
    return measure([LAUNCHER, BINARY, mode, file, workers, 2048], env(backend, omp))


def inflate(file, tool, n, output=None):
    if tool == "gzip":
        cmd = ["/usr/bin/gzip", "-dc", file]
    elif tool == "pigz":
        cmd = ["/usr/bin/pigz", "-p", n, "-dc", file]
    else:
        cmd = [ROOT / "decompress-env/bin/rapidgzip", "--verify", "-P", n, "-dc", file]
    return measure(cmd, BASE, output=output or "/dev/null")


def validate_backend(row, backend):
    assert str(ROOT / "snapshots" / backend / "lib") in row["openms_library"], row
    assert row["cpu_affinity"] == "0-95", row
    maps = row["loaded_library_maps"]
    assert maps, row
    has_xerces = any("libxerces" in x.lower() for x in maps)
    has_libxml = any("libxml2.so" in x for x in maps)
    assert has_xerces == (backend == "xerces") and has_libxml == (backend == "libxml2-full"), maps
    assert (
        row["sampled_native_threads"] <= row["workers"] * row["requested_openmp_threads"] + 5
    ), row
    if row["mode"] != "idle" and row["seconds"] > 1 and row["requested_openmp_threads"] == 1:
        assert row["sampled_native_threads"] >= row["workers"] + 1, row


def cached_input(file):
    cmd = [str(ROOT / "native-meter"), "--residency", str(file)]
    r = json.loads(subprocess.check_output(cmd, text=True))
    if r["resident_file_bytes"] < r["file_bytes"]:
        with open(file, "rb") as f:
            while f.read(8 * 1024 * 1024):
                pass
        r = json.loads(subprocess.check_output(cmd, text=True))
    assert r["resident_file_bytes"] == r["file_bytes"], r
    return r


def require(row):
    if not row["ok"]:
        with (OUT / "failures.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")
        raise RuntimeError(json.dumps(row))
    return row


def fingerprint(row):
    return tuple(
        row[k]
        for k in [
            "spectra_per_worker",
            "chromatograms_per_worker",
            "points_per_worker",
            "hash_per_worker",
        ]
    )


def audit():
    assert (ROOT / "results/EXTENDED_DATA_COMPLETE").exists()
    assert (ROOT / "results/CONVERSION_COMPLETE").exists()
    records = []
    reference = {}
    aux = {}
    for name in FILES:
        for backend in BACKENDS:
            row = require(bench(ROOT / "data" / name, backend, mode="stream-audit"))
            row.update(input=name, backend=backend, phase="correctness-auxiliary")
            records.append(row)
            fp = fingerprint(row)
            if name in reference:
                assert reference[name] == fp, (name, backend, "base digest")
            reference[name] = fp
            extra = tuple(
                row[k]
                for k in [
                    "aux_hash_per_worker",
                    "im_array_values_per_worker",
                    "im_scalar_spectra_per_worker",
                    "ms1_per_worker",
                    "ms2_per_worker",
                    "ms3plus_per_worker",
                ]
            )
            if name in aux:
                assert aux[name] == extra, (name, backend, "auxiliary digest")
            aux[name] = extra
            if name == "pasef-im-600-1200s.mzML":
                assert (
                    row["im_array_values_per_worker"] > 0 or row["im_scalar_spectra_per_worker"] > 0
                )
        print("AUDIT", name, reference[name], aux[name], flush=True)
    assert len({reference[n] for n in FILES[:4]}) == 1
    assert len({aux[n] for n in FILES[:4]}) == 1
    assert aux["pasef-published.mzML"][1:3] == (0, 0)
    assert reference[FILES[0]][:3] == (131072, 1, 131072 * 2048 + 131072)
    assert all((ROOT / "data" / n).stat().st_size >= 1_000_000_000 for n in FILES[:4])
    (OUT / "correctness-audits.json").write_text(json.dumps(records, indent=2) + "\n")
    (OUT / "references.json").write_text(json.dumps(reference, indent=2) + "\n")
    # Native concurrency evidence: no N-thread warmup team retained in main.
    controls = []
    for backend in BACKENDS:
        for workers, omp in [(1, 96), (96, 1)]:
            row = require(bench(ROOT / "data/large-matched-zlib.mzML", backend, workers, omp))
            assert fingerprint(row) == reference["large-matched-zlib.mzML"]
            assert row["sampled_native_threads"] >= 96 and row["sampled_native_threads"] <= 100, row
            assert row["native_peak_rss_bytes"] > 0
            if backend == "libxml2-full":
                assert not any("libxerces" in x.lower() for x in row["loaded_library_maps"])
            row.update(backend=backend, phase="thread-census")
            controls.append(row)
    (OUT / "thread-census.json").write_text(json.dumps(controls, indent=2) + "\n")
    # Full byte verification is outside canonical timing, both endpoints per inflater.
    SHM.mkdir(exist_ok=True)
    target = SHM / "correctness.xml"
    decomp = []
    for name in FILES[2:4]:
        expected = sha(ROOT / "data" / name[:-3])
        for tool in ["gzip", "pigz", "rapidgzip"]:
            for n in ([1] if tool == "gzip" else [1, 96]):
                row = require(inflate(ROOT / "data" / name, tool, n, target))
                actual = sha(target)
                assert actual == expected, (name, tool, n)
                assert row["output_bytes"] == (ROOT / "data" / name[:-3]).stat().st_size
                row.update(input=name, tool=tool, requested_threads=n, output_sha256=actual)
                decomp.append(row)
                target.unlink()
                print("INFLATE VERIFIED", name, tool, n, flush=True)
    (OUT / "decompressor-correctness.json").write_text(json.dumps(decomp, indent=2) + "\n")
    inputs = {
        name: dict(bytes=(ROOT / "data" / name).stat().st_size, sha256=sha(ROOT / "data" / name))
        for name in FILES
    }
    (OUT / "inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
    (OUT / "CORRECTNESS_COMPLETE").touch()


def identity():
    files = [
        BINARY,
        LAUNCHER,
        ROOT / "native-meter",
        ROOT / "run-gap.py",
        ROOT / "run-access.py",
        ROOT / "native-meter.cpp",
        Path("/usr/bin/gzip"),
        Path("/usr/bin/pigz"),
        ROOT / "decompress-env/bin/rapidgzip",
        ROOT / "decompress-env/bin/python",
    ]
    files += list((ROOT / "staging/extended-benchmark-source").glob("*.cpp")) + list(
        (ROOT / "staging/extended-benchmark-source").glob("CMakeLists.txt")
    )
    files += list((ROOT / "snapshots").glob("*/lib/*"))
    files += list((ROOT / "dependencies/install/lib").glob("libxml2.so*")) + list(
        (ROOT / "dependencies/install/lib").glob("libxerces-c*.so*")
    )
    # Frozen dependency paths are immutable configuration, not regenerated audit output.
    paths_file = OUT / "identity-dependency-paths.json"
    paths = json.loads(paths_file.read_text())
    files += [paths_file] + [Path(p) for p in paths]
    files = sorted(set(files))
    payload = dict(
        files={
            str(p): dict(realpath=str(p.resolve()), sha256=sha(p)) for p in files if p.is_file()
        },
        inputs={
            name: dict(
                bytes=(ROOT / "data" / name).stat().st_size, sha256=sha(ROOT / "data" / name)
            )
            for name in FILES
        },
        environment=BASE,
        openms_environments={b: env(b) for b in BACKENDS},
        source_commits={
            "xerces": "58aa37348c968a12e3285295f28c197cc0b7bdbe",
            "libxml2-full": "8f66b3d921c9512e1e5968f494c77715ff71c696",
        },
    )
    expected = json.loads((OUT / "inputs.json").read_text())
    assert payload["inputs"] == expected, "Input changed since correctness audit"
    real = json.loads((ROOT / "staging/real-input-manifest.json").read_text())
    for row in real["files"]:
        if row["destination"] in FILES:
            assert payload["inputs"][row["destination"]] == {k: row[k] for k in ["bytes", "sha256"]}
    matched = json.loads((ROOT / "results/matched-inputs.json").read_text())
    for name, row in matched.items():
        assert payload["inputs"][name] == row
    assert (
        payload["inputs"]["pasef-im-600-1200s.mzML"]["sha256"]
        == (ROOT / "results/converted-im.sha256").read_text().split()[0]
    )
    # Distinct copied libraries, not labels on two symlinks to one binary.
    libs = {b: (ROOT / "snapshots" / b / "lib/libOpenMS.so").resolve() for b in BACKENDS}
    assert libs["xerces"] != libs["libxml2-full"] and sha(libs["xerces"]) != sha(
        libs["libxml2-full"]
    )
    return payload


def bind_identity():
    payload = identity()
    path = OUT / "measurement-identity.json"
    if path.exists():
        assert (
            json.loads(path.read_text()) == payload
        ), "Measurement identity changed: refuse mixed-config resume"
    else:
        path.write_text(json.dumps(payload, indent=2) + "\n")
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@contextlib.contextmanager
def cell_attempt(cell):
    try:
        yield
    except BaseException as error:
        row = dict(
            cell=cell,
            error_type=type(error).__name__,
            error=str(error),
            traceback=traceback.format_exc(),
            unix=time.time(),
        )
        with (OUT / "cell-failures.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")
            f.flush()
            os.fsync(f.fileno())
        raise


def monitor(stop):
    with (OUT / "resources.jsonl").open("a") as f:
        while not stop.is_set():
            m = Path("/proc/meminfo").read_text()
            line = dict(
                timestamp=time.time(),
                loadavg=Path("/proc/loadavg").read_text().strip(),
                memory=[
                    x
                    for x in m.splitlines()
                    if x.startswith(("MemAvailable:", "SwapFree:", "Dirty:"))
                ],
            )
            f.write(json.dumps(line) + "\n")
            f.flush()
            stop.wait(15)


def run():
    assert (OUT / "CORRECTNESS_COMPLETE").exists()
    os.sched_setaffinity(0, set(range(96, 128)))
    identity_sha = bind_identity()
    reference = json.loads((OUT / "references.json").read_text())
    cells = []
    for rep in range(5):
        for name in FILES:
            for backend in BACKENDS:
                for n in THREADS:
                    cells.append(
                        dict(kind="readers", input=name, backend=backend, workers=n, omp=1, rep=rep)
                    )
        for name in FILES[:2]:
            for backend in BACKENDS:
                for n in THREADS:
                    cells.append(
                        dict(
                            kind="single-file-openmp",
                            input=name,
                            backend=backend,
                            workers=1,
                            omp=n,
                            rep=rep,
                        )
                    )
        for name in FILES[2:4]:
            for tool in ["gzip", "pigz", "rapidgzip"]:
                for n in ([1] if tool == "gzip" else THREADS):
                    cells.append(
                        dict(kind="decompress", input=name, tool=tool, requested_threads=n, rep=rep)
                    )
                    for backend in BACKENDS:
                        cells.append(
                            dict(
                                kind="staged-pipeline",
                                input=name,
                                tool=tool,
                                requested_threads=n,
                                backend=backend,
                                rep=rep,
                            )
                        )
    random.Random(20261020).shuffle(cells)

    def key(c):
        return json.dumps(c, sort_keys=True)

    path = OUT / "records.jsonl"
    done = set()
    if path.exists():
        for l in path.read_text().splitlines():
            r = json.loads(l)
            if r["ok"]:
                assert r["measurement_identity_sha256"] == identity_sha
                done.add(key(r["cell"]))
    (OUT / "schedule.json").write_text(json.dumps(cells, indent=2) + "\n")
    SHM.mkdir(exist_ok=True)
    target = SHM / "staged.xml"
    stop = threading.Event()
    mon = threading.Thread(target=monitor, args=(stop,), daemon=True)
    mon.start()
    try:
        with path.open("a", buffering=1) as f:
            for i, c in enumerate(cells):
                if key(c) in done:
                    continue
                with cell_attempt(c):
                    start = time.time()
                    file = ROOT / "data" / c["input"]
                    kind = c["kind"]
                    cache = cached_input(file)
                    if kind in ["readers", "single-file-openmp"]:
                        r = bench(file, c["backend"], c["workers"], c["omp"])
                        require(r)
                        assert fingerprint(r) == tuple(reference[c["input"]]), c
                        validate_backend(r, c["backend"])
                        assert r["requested_openmp_threads"] == c["omp"]
                        if kind == "single-file-openmp":
                            assert r["sampled_native_threads"] >= c["omp"] + 1, r
                    elif kind == "decompress":
                        r = require(inflate(file, c["tool"], c["requested_threads"]))
                    else:
                        if target.exists():
                            target.unlink()
                        begin = time.perf_counter()
                        d = require(inflate(file, c["tool"], c["requested_threads"], target))
                        p = require(bench(target, c["backend"]))
                        elapsed = time.perf_counter() - begin
                        assert d["output_bytes"] == (ROOT / "data" / c["input"][:-3]).stat().st_size
                        assert fingerprint(p) == tuple(reference[c["input"]]), c
                        validate_backend(p, c["backend"])
                        r = dict(
                            ok=True,
                            process_seconds=elapsed,
                            decompress=d,
                            parse=p,
                            staged_file_bytes=d["output_bytes"],
                            sequential_component_native_peak_rss_bytes=max(
                                d["native_wait4_peak_rss_bytes"], p["native_peak_rss_bytes"]
                            ),
                            rss_definition="max of sequential components; CLI native-supervisor wait4; tmpfs file additional",
                            sampled_native_threads=max(
                                d["sampled_native_threads"], p["sampled_native_threads"]
                            ),
                        )
                        target.unlink()
                    r.update(
                        cell=c,
                        measurement_identity_sha256=identity_sha,
                        input_cache_before=cache,
                        started_unix=start,
                        completed_unix=time.time(),
                    )
                    f.write(json.dumps(r, sort_keys=True) + "\n")
                    os.fsync(f.fileno())
                    print(f'{i+1}/{len(cells)} {c} {r["process_seconds"]:.3f}s', flush=True)
    finally:
        stop.set()
        mon.join()
    assert bind_identity() == identity_sha
    (OUT / "MATRIX_COMPLETE").touch()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["audit", "run"])
    a = p.parse_args()
    audit() if a.mode == "audit" else run()
