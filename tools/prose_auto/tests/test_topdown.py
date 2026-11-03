"""Top-down, middle-down, native and intact-mass runs: the verdict and the abort (no ProSE settings, exit 3)."""
import json

import numpy as np
import pytest

from prose_auto import cli
from prose_auto import topdown as td
from prose_auto.spectra import PROTON, Run, Scan


def _run(precursors=(), ms1=()):
    r = Run(path="x.mzML")
    r.ms2 = [Scan(f"scan={i}", 2, float(i), np.array([200.0]), np.array([1.0]), precursor_mz=mz, charge=z)
             for i, (mz, z) in enumerate(precursors)]
    r.ms1 = list(ms1)
    r.n_ms2_total, r.n_ms1_total = len(r.ms2), len(r.ms1)
    return r


def _mz(mass, z):
    return mass / z + PROTON


def test_bottom_up_precursors_are_no_abort():
    r = _run([(_mz(m, z), z) for m, z in [(1500.0, 2), (2100.0, 3), (900.0, 2), (4400.0, 5), (1800.0, 2)] * 20])
    assert td.detect(r) is None


def test_top_down_middle_down_and_native_from_precursors():
    lysate = [(_mz(m, z), z) for m, z in [(5500.0, 7), (6000.0, 8), (12000.0, 13), (4800.0, 6), (16000.0, 15)] * 10]
    v = td.detect(_run(lysate))
    assert v["class"] == "top-down" and "use FLASHTnT" in v["recommendation"] and "kDa" in v["reason"]
    tails = [(_mz(m, z), z) for m, z in [(5400.0, 9), (5500.0, 9), (6100.0, 10)] * 10]      # histone tails, no tail >10 kDa
    assert td.detect(_run(tails))["class"] == "middle-down"
    native = [(_mz(29000.0, z), z) for z in (9, 10, 11)] * 5                                 # CA2 29 kDa at 10+
    assert td.detect(_run(native))["class"] == "native"


def test_charge_ladder_and_ms1_only_intact_run():
    m, zs = 16951.0, range(12, 30)
    peaks = np.array(sorted(_mz(m, z) for z in zs))
    noise = np.linspace(500.0, 2000.0, 200)
    mz = np.concatenate([peaks, noise])
    it = np.concatenate([np.full(len(peaks), 100.0), np.full(len(noise), 3.0)])
    o = np.argsort(mz)
    s = Scan("scan=1", 1, 1.0, mz[o], it[o], tic=float(it.sum()))
    lad = td.charge_ladder([s])
    assert lad["states"] >= 15 and abs(lad["mass"] - m) < 2 and lad["signif"] >= td.LADDER_SIGNIF
    v = td.detect(_run(ms1=[s]))
    assert v["class"] == "intact mass" and "charge series" in v["reason"]


def test_analyze_aborts_with_exit_3(tmp_path, monkeypatch):
    lysate = [(_mz(m, z), z) for m, z in [(9000.0, 11), (14000.0, 15), (22000.0, 20)] * 5]
    monkeypatch.setattr(cli, "load_mzml", lambda *a, **k: _run(lysate))
    out = tmp_path / "o"
    with pytest.raises(SystemExit) as e:
        cli.main(["analyze", str(tmp_path / "td.mzML"), "-o", str(out)])
    assert e.value.code == td.EXIT_NO_DIGEST
    rep = json.load(open(out / "td.auto.json"))
    assert rep["no_digest"]["class"] == "top-down" and "decisions" not in rep and not (out / "td.prose.ini").exists()
