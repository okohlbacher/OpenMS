#!/usr/bin/env python3
"""Prove metadata/mobility audit detects changes the peak-only digest cannot."""

import base64, copy, json, struct, tempfile, xml.etree.ElementTree as ET
from pathlib import Path
import importlib.util

spec = importlib.util.spec_from_file_location("gap", Path(__file__).with_name("run-gap.py"))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
N = "http://psi.hupo.org/ms/mzml"
ET.register_namespace("", N)


def tag(x):
    return "{" + N + "}" + x


def cv(parent, accession, name, value="", **extra):
    return ET.SubElement(
        parent,
        tag("cvParam"),
        dict(cvRef="MS", accession=accession, name=name, value=str(value), **extra),
    )


def execute():
    with tempfile.TemporaryDirectory(dir=g.ROOT / "tmp") as d:
        d = Path(d)
        plain = d / "base.mzML"
        g.require(g.measure([g.LAUNCHER, g.BINARY, "generate", plain, 2, 4], g.env("xerces")))
        tree = ET.parse(plain)
        for i, spectrum in enumerate(tree.findall(".//" + tag("spectrum"))):
            for v in spectrum.findall(tag("cvParam")):
                if v.get("accession") == "MS:1000511":
                    v.set("value", str(i + 1))
            scan = spectrum.find(".//" + tag("scan"))
            cv(
                scan,
                "MS:1002815",
                "inverse reduced ion mobility",
                1.2 + i,
                unitCvRef="MS",
                unitAccession="MS:1002814",
                unitName="volt-second per square centimeter",
            )
            arrays = spectrum.find(tag("binaryDataArrayList"))
            arrays.set("count", str(len(arrays) + 1))
            data = base64.b64encode(struct.pack("<4f", 1.0, 1.1, 1.2, 1.3)).decode()
            a = ET.SubElement(arrays, tag("binaryDataArray"), dict(encodedLength=str(len(data))))
            cv(a, "MS:1000521", "32-bit float")
            cv(a, "MS:1000576", "no compression")
            cv(
                a,
                "MS:1003008",
                "raw inverse reduced ion mobility array",
                unitCvRef="MS",
                unitAccession="MS:1002814",
                unitName="volt-second per square centimeter",
            )
            ET.SubElement(a, tag("binary")).text = data
        good = d / "im.mzML"
        tree.write(good, encoding="UTF-8", xml_declaration=True)
        mutant = copy.deepcopy(tree)
        mutant.findall(".//" + tag("spectrum"))[0].findall(".//" + tag("binary"))[-1].text = (
            base64.b64encode(struct.pack("<4f", 9.0, 1.1, 1.2, 1.3)).decode()
        )
        changed = d / "changed-im.mzML"
        mutant.write(changed, encoding="UTF-8", xml_declaration=True)
        results = []
        for backend in g.BACKENDS:
            a = g.require(g.bench(good, backend, mode="stream-audit"))
            b = g.require(g.bench(changed, backend, mode="stream-audit"))
            g.validate_backend(a, backend)
            try:
                g.validate_backend(a, "xerces" if backend == "libxml2-full" else "libxml2-full")
            except AssertionError:
                pass
            else:
                raise AssertionError("Swapped XML backend was accepted")
            assert g.fingerprint(a) == g.fingerprint(b)
            assert a["aux_hash_per_worker"] != b["aux_hash_per_worker"]
            assert (
                a["im_array_values_per_worker"] == 8 and a["im_scalar_spectra_per_worker"] == 2
            ), a
            assert a["ms1_per_worker"] == 1 and a["ms2_per_worker"] == 1, a
            results.append(dict(backend=backend, original=a, mutated=b))
        assert (
            results[0]["original"]["aux_hash_per_worker"]
            == results[1]["original"]["aux_hash_per_worker"]
        )
        # Raised Python RSS floor must not contaminate native post-exec VmHWM.
        parent = bytearray(128 * 1024 * 1024)
        for i in range(0, len(parent), 4096):
            parent[i] = 1
        small = g.require(g.bench(good, "libxml2-full", mode="stream-audit"))
        assert small["native_peak_rss_bytes"] < small["wait4_max_rss_bytes"], small
        assert small["native_peak_rss_bytes"] > 0
        assert 0 < small["native_wait4_peak_rss_bytes"] < small["wait4_max_rss_bytes"], small
        assert (
            abs(small["native_wait4_peak_rss_bytes"] - small["native_peak_rss_bytes"])
            < 8 * 1024 * 1024
        ), small
        clock = g.require(g.measure(["/usr/bin/sleep", "0.123"], g.BASE))
        assert 0.120 <= clock["process_seconds"] <= 0.143, clock
        failed = g.measure(["/usr/bin/false"], g.BASE)
        assert not failed["ok"]
        original_out, original_identity = g.OUT, g.identity
        try:
            g.OUT = d
            g.identity = lambda: {"test_identity": 1}
            g.bind_identity()
            g.identity = lambda: {"test_identity": 2}
            try:
                g.bind_identity()
            except AssertionError:
                pass
            else:
                raise AssertionError("Changed identity was accepted")
            try:
                g.require(failed)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Failed subprocess accepted")
            assert json.loads((d / "failures.jsonl").read_text())["exit_code"] == 1
            try:
                with g.cell_attempt({"kind": "expected-negative-control"}):
                    raise AssertionError("expected cell validation failure")
            except AssertionError:
                pass
            else:
                raise AssertionError("Per-cell validation failure was accepted")
            assert (
                json.loads((d / "cell-failures.jsonl").read_text())["error_type"]
                == "AssertionError"
            )
        finally:
            g.OUT, g.identity = original_out, original_identity
        result = dict(
            tests=[
                "finite scalar and per-peak mobility recognized",
                "IM-only mutation changes auxiliary digest while peak digest stays fixed",
                "MS-level counts recognized",
                "both XML backends agree",
                "native HWM excludes raised Python-parent wait4 floor",
                "swapped backend rejected",
                "pidfd exit timing calibrated",
                "failed subprocess recorded",
                "changed identity resume rejected",
            ],
            results=results,
            parent_rss_floor_control=small,
            pidfd_clock_control=clock,
            expected_failure_control=failed,
        )
        (g.OUT / "audit-tests.json").write_text(json.dumps(result, indent=2) + "\n")
        print("All audit and RSS-floor tests passed", flush=True)


if __name__ == "__main__":
    execute()
