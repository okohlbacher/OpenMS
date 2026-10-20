import importlib.util, json, platform, subprocess
from pathlib import Path

spec = importlib.util.spec_from_file_location("gap", Path(__file__).with_name("run-gap.py"))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def command(c, env=None):
    p = subprocess.run(c, capture_output=True, text=True, env=env)
    return dict(command=c, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)


rows = {
    name: command(c)
    for name, c in {
        "cpu": ["lscpu"],
        "numa": ["numactl", "--hardware"],
        "scratch": ["findmnt", "-T", str(g.ROOT), "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"],
        "tmpfs": ["findmnt", "-T", str(g.SHM), "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"],
        "compiler": ["g++", "--version"],
        "kernel": ["uname", "-a"],
    }.items()
}
rows["sysfs"] = {
    str(p): p.read_text().strip()
    for pattern in [
        "cpu*/topology/thread_siblings_list",
        "cpu0/cpufreq/scaling_governor",
        "cpufreq/boost",
        "amd_pstate/status",
    ]
    for p in Path("/sys/devices/system/cpu").glob(pattern)
    if p.is_file()
}
rows["load"] = Path("/proc/loadavg").read_text()
rows["memory"] = Path("/proc/meminfo").read_text()
rows["tools"] = {}
for name, p in [
    ("gzip", Path("/usr/bin/gzip")),
    ("pigz", Path("/usr/bin/pigz")),
    ("rapidgzip", g.ROOT / "decompress-env/bin/rapidgzip"),
]:
    with p.open("rb") as f:
        header = f.read(160)
    rows["tools"][name] = dict(
        executable=str(p),
        realpath=str(p.resolve()),
        sha256=g.sha(p),
        type=(
            "ELF native executable"
            if header.startswith(b"\x7fELF")
            else "interpreter entry point; startup and interpreter RSS included"
        ),
        header=header.decode(errors="replace") if header.startswith(b"#!") else None,
        linked_libraries=command(["/usr/bin/ldd", str(p)], g.BASE),
    )
rows["openms_linked_libraries"] = {
    b: command(["/usr/bin/ldd", str(g.ROOT / "snapshots" / b / "lib/libOpenMS.so")], g.env(b))
    for b in g.BACKENDS
}
(g.OUT / "final-environment.json").write_text(json.dumps(rows, indent=2) + "\n")
print("Environment and transitive-library metadata captured")
