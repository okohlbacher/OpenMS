from pathlib import Path
import hashlib, json, subprocess, urllib.request, sys, os

root = Path("/scratch/kohlbach/openms-xml-gap-bench-20261020-01a153cb")
os.environ["UV_CACHE_DIR"] = str(root / "cache/uv")
meta = json.load(urllib.request.urlopen("https://pypi.org/pypi/rapidgzip/0.16.0/json"))
version = meta["info"]["version"]
choices = [
    x
    for x in meta["urls"]
    if (
        "cp"
        + str(sys.version_info.major)
        + str(sys.version_info.minor)
        + "-cp"
        + str(sys.version_info.major)
        + str(sys.version_info.minor)
    )
    in x["filename"]
    and "x86_64" in x["filename"]
    and "manylinux" in x["filename"]
]
assert choices, version
wheel = choices[0]
p = root / "dependencies" / wheel["filename"]
urllib.request.urlretrieve(wheel["url"], p)
assert hashlib.sha256(p.read_bytes()).hexdigest() == wheel["digests"]["sha256"]
env = root / "decompress-env"
uv = "/home/kohlbach/.local/bin/uv"
subprocess.run([uv, "venv", str(env), "--clear", "--python", sys.executable], check=True)
subprocess.run([uv, "pip", "install", "--python", str(env / "bin/python"), str(p)], check=True)
commands = {}
for cmd in [
    ["/usr/bin/gzip", "--version"],
    ["/usr/bin/pigz", "--version"],
    [str(env / "bin/rapidgzip"), "--version"],
    [str(env / "bin/rapidgzip"), "--help"],
]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0
    commands[" ".join(cmd)] = {"stdout": r.stdout, "stderr": r.stderr}
(root / "results/decompressors.json").write_text(
    json.dumps(
        {
            "rapidgzip_version": version,
            "rapidgzip_wheel": wheel,
            "commands": commands,
            "binaries": {
                str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [Path("/usr/bin/gzip"), Path("/usr/bin/pigz"), env / "bin/rapidgzip"]
            },
        },
        indent=2,
    )
    + "\n"
)
print("Pinned rapidgzip", version, flush=True)
