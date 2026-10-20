"""Bind the staged source archives to actual Git blobs of the recorded commits."""

import argparse, hashlib, io, json, subprocess, tarfile
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("repository", type=Path)
p.add_argument("archives", type=Path)
p.add_argument("output", type=Path)
a = p.parse_args()
result = {}
for backend, commit in [
    ("xerces", "58aa37348c968a12e3285295f28c197cc0b7bdbe"),
    ("libxml2-full", "8f66b3d921c9512e1e5968f494c77715ff71c696"),
]:
    raw = subprocess.check_output(["git", "-C", str(a.repository), "ls-tree", "-rz", commit])
    blobs = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        description, name = record.split(b"\t", 1)
        mode, kind, oid = description.decode().split()
        if kind == "blob" and mode != "120000":
            blobs[name.decode()] = oid
    export_substitutions = []
    seen = set()
    differences = []
    archive = a.archives / (backend + ".tar.gz")
    with archive.open("rb") as f:
        archive_hash = hashlib.file_digest(f, "sha256").hexdigest()
    with tarfile.open(archive) as tar:
        for member in tar:
            if not member.isfile():
                continue
            name = member.name.removeprefix("./")
            data = tar.extractfile(member).read()
            oid = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            seen.add(name)
            if name == ".git_archival.txt" and blobs.get(name) != oid:
                attrs = subprocess.check_output(
                    ["git", "-C", str(a.repository), "show", commit + ":.gitattributes"], text=True
                )
                assert ".git_archival.txt export-subst" in attrs
                generated = subprocess.check_output(
                    ["git", "-C", str(a.repository), "archive", commit, name]
                )
                with tarfile.open(fileobj=io.BytesIO(generated)) as exported:
                    expected_export = exported.extractfile(name).read()
                assert data == expected_export, (
                    backend,
                    "Unexpected Git export-subst content",
                    data,
                    expected_export,
                )
                export_substitutions.append(
                    dict(path=name, content=data.decode(), verified_against_git_archive=True)
                )
                continue
            if blobs.get(name) != oid:
                differences.append(dict(path=name, git_blob=blobs.get(name), archive_blob=oid))
    result[backend] = dict(
        commit=commit,
        archive_sha256=archive_hash,
        regular_files_checked=len(seen),
        differences=differences,
        verified_export_substitutions=export_substitutions,
        all_archive_regular_files_match_commit_or_export_substitution=not differences,
        git_regular_blobs_not_in_archive=sorted(set(blobs) - seen),
    )
a.output.write_text(json.dumps(result, indent=2) + "\n")
assert all(
    r["all_archive_regular_files_match_commit_or_export_substitution"] for r in result.values()
), result
print({b: (r["commit"], r["regular_files_checked"]) for b, r in result.items()})
