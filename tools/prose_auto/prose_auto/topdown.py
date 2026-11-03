"""Top-down, middle-down, native and intact-mass runs: no digest, so ProSE (a peptide search) does not apply.

The check runs right after reading the spectra. It uses the MS2 precursors (charge and m/z) where the headers give
a charge, else the MS1 spectra deconvolved by FLASHDeconv on a subsample. Bottom-up precursors are 600-4000 Da at
2+/3+; intact proteoforms carry 10+ to 50+ and masses well above 10 kDa; native ions carry few charges for their
mass (z ~ 0.078 sqrt(M), CA2 29 kDa at 10+); middle-down precursors (histone tails, antibody subunits) fall in
between. The thresholds are calibrated on public runs (topdown/ in the validation tree)."""
import math
import os
import shutil
import subprocess
import tempfile

import numpy as np

from .spectra import PROTON

EXIT_NO_DIGEST = 3          # prose-auto analyze: a run without a digest, nothing to set for ProSE
RECOMMENDATION = "use FLASHTnT (OpenMS)"
MIN_CHARGED = 0.5           # share of MS2 precursors with a charge before the headers decide
N_MS1 = 40                  # MS1 spectra (highest TIC) for FLASHDeconv when the headers have no charge


def native_charge(mass):
    """typical native charge of a globular protein of this mass (Da), z ~ 0.078 sqrt(M)"""
    return 0.078 * np.sqrt(mass)


def precursor_features(run):
    """masses and charges of the MS2 precursors that carry a charge"""
    z = np.array([s.charge for s in run.ms2 if s.charge > 0 and s.precursor_mz > 0], dtype=float)
    mz = np.array([s.precursor_mz for s in run.ms2 if s.charge > 0 and s.precursor_mz > 0], dtype=float)
    f = {"ms2": len(run.ms2), "charged": len(z), "charged_share": round(len(z) / len(run.ms2), 3) if run.ms2 else 0.0}
    if len(z):
        m = (mz - PROTON) * z
        f.update(_mass_stats(m, z))
    return f


def _mass_stats(m, z, w=None):
    w = np.ones_like(m) if w is None else w
    o = np.argsort(m)
    cw = np.cumsum(w[o]) / w.sum()
    med = float(m[o][np.searchsorted(cw, 0.5)])
    big = m >= 20000
    return {"median_mass": round(med, 1), "median_charge": float(np.median(z)),
            "share_ge_5k": round(float(w[m >= 5000].sum() / w.sum()), 3),
            "share_ge_10k": round(float(w[m >= 10000].sum() / w.sum()), 3),
            "share_z_ge_8": round(float(w[z >= 8].sum() / w.sum()), 3),
            "native_ratio": round(float(np.median(z[big] / native_charge(m[big]))), 2) if big.sum() >= 3 else None}


def ms1_features(run, flashdeconv, tol_ppm=10.0, threads=1, log=print, level=1):
    """FLASHDeconv on the N_MS1 highest-TIC MS1 spectra (level=2: MS2 spectra, deconvolved like MS1 so that fragment
    charges are free): intensity-weighted mass and charge statistics of the deconvolved masses (its own tolerance
    estimate returned 0 ppm on Orbitrap MS1 and nothing deconvolved)"""
    import pyopenms as oms
    ms1 = sorted(run.ms1 if level == 1 else run.ms2, key=lambda s: -s.tic)[:N_MS1]
    if not ms1 or not flashdeconv:
        return {"ms1_deconvolved": 0}
    tmp = tempfile.mkdtemp(prefix="prose_auto_td_")
    try:
        exp = oms.MSExperiment()
        for i, s in enumerate(sorted(ms1, key=lambda s: s.rt)):
            sp = oms.MSSpectrum()
            sp.setNativeID(f"scan={i + 1}")
            sp.setMSLevel(1)
            sp.setRT(s.rt)
            sp.set_peaks((s.mz, s.intensity))
            exp.addSpectrum(sp)
        src, out = os.path.join(tmp, "ms1.mzML"), os.path.join(tmp, "ms1.tsv")
        oms.MzMLFile().store(src, exp)
        r = subprocess.run([flashdeconv, "-in", src, "-out", os.path.join(tmp, "f.tsv"), "-out_spec1", out,
                            "-SD:tol", str(tol_ppm), "10", "-keep_empty_out", "-threads", str(threads)], capture_output=True, text=True)
        if r.returncode or not os.path.exists(out):
            log(f"  FLASHDeconv failed ({r.returncode}): {r.stderr.strip()[-200:]}")
            return {"ms1_deconvolved": 0}
        return _spec1_stats(out)
    finally:
        shutil.rmtree(tmp, True)


def _spec1_stats(path):
    import csv
    rows = list(csv.DictReader(open(path), delimiter="\t"))
    if not rows:
        return {"ms1_deconvolved": 0}
    key = lambda *ks: next(k for k in ks if k in rows[0])
    km, ki = key("MonoisotopicMass", "MonoMass"), key("SumIntensity", "Intensity")
    kz0, kz1 = key("MinCharge"), key("MaxCharge")
    m = np.array([float(r[km]) for r in rows])
    w = np.array([float(r[ki]) for r in rows])
    z0, z1 = np.array([float(r[kz0]) for r in rows]), np.array([float(r[kz1]) for r in rows])
    f = {"ms1_deconvolved": len(rows), **_mass_stats(m, (z0 + z1) / 2, w)}
    f["median_charge_states"] = float(np.median(z1 - z0 + 1))
    return f


LADDER_PEAKS = 30          # most intense peaks per spectrum tried as a member of a charge series
LADDER_SPECTRA = 5         # highest-TIC spectra searched
LADDER_MIN_INTENSITY = 0.02   # of the spectrum's base peak, for a series member


def charge_ladder(scans, zmin=5, zmax=150):
    """The most significant series of consecutive charge states of one mass among the most intense peaks (the
    UniDec idea; no isotope resolution needed, so it works on native and TOF spectra). A series is scored by the
    chance of its members under the spectrum's peak density (dense bottom-up spectra fill long high-charge series
    by chance): signif = -log10(chance) - log10(trials). Returns {states, mass, z_min, z_max, mz, share, signif}."""
    best = {"states": 0, "signif": 0.0}
    trials = math.log10(2 * LADDER_PEAKS * (zmax - zmin + 1) * LADDER_SPECTRA)
    for s in sorted(scans, key=lambda s: -s.tic)[:LADDER_SPECTRA]:
        if s.mz.size < 3:
            continue
        keep = s.intensity >= LADDER_MIN_INTENSITY * s.intensity.max()
        mz, it = s.mz[keep], s.intensity[keep]
        o = np.argsort(mz)
        mz, it = mz[o], it[o]
        density = len(mz) / max(mz[-1] - mz[0], 1.0)

        def hit(t, rel):
            tol = rel * t
            i, j = np.searchsorted(mz, t - tol), np.searchsorted(mz, t + tol)
            return (int(i + np.argmax(it[i:j])) if j > i else None), min(1.0, 2 * tol * density)

        # resolved isotopes: the same isotope peak recurs at exact m/z in every charge state (20 ppm); unresolved
        # native peaks are broad (0.05 %)
        for p, rel in ((x, r) for x in mz[np.argsort(-it)[:LADDER_PEAKS]] for r in (2e-5, 5e-4)):
            for z in range(zmin, zmax + 1):
                m = (p - PROTON) * z
                got, logp = {z: hit(p, rel)[0]}, 0.0
                for step in (1, -1):
                    k = z + step
                    while 1 <= k <= zmax + 3:
                        h, ph = hit((m + k * PROTON) / k, rel)
                        if h is None:
                            break
                        got[k], logp = h, logp + math.log10(ph)
                        k += step
                sig = -logp - trials
                if len(got) >= 3 and sig > best["signif"]:
                    best = {"states": len(got), "mass": round(m, 1), "z_min": min(got), "z_max": max(got),
                            "mz": round(float(p), 2), "signif": round(sig, 2),
                            "share": round(float(it[list(set(got.values()))].sum() / s.intensity.sum()), 3)}
    return best


def tdf_precursor_features(d):
    """precursor_features for a ddaPASEF .d from analysis.tdf (the charges FileConverter writes into the mzML)"""
    import sqlite3
    con = sqlite3.connect(f"file:{os.path.join(d, 'analysis.tdf')}?mode=ro", uri=True)
    rows = con.execute("SELECT MonoisotopicMz, Charge FROM Precursors").fetchall()
    con.close()
    z = np.array([c or 0 for _, c in rows], dtype=float)
    mz = np.array([m or 0 for m, _ in rows], dtype=float)
    ok = (z > 0) & (mz > 0)
    f = {"ms2": len(rows), "charged": int(ok.sum()), "charged_share": round(float(ok.mean()), 3) if rows else 0.0}
    if ok.any():
        f.update(_mass_stats((mz[ok] - PROTON) * z[ok], z[ok]))
    return f


MIN_PRECURSORS = 5   # charged MS2 precursors before they decide (PXD033100: 10 ETD scans of intact EF-Tu)
# Thresholds from 123 top-down, middle-down, native and intact-mass runs against 270 bottom-up runs (the 180
# benchmark runs, non-tryptic, HLA, DIA/timsTOF and mixture sets; topdown/ in the validation tree). Bottom-up
# maxima in brackets.
PREC_MASS, PREC_CHARGE = 5000.0, 5   # median precursor mass and charge [4.4 kDa at 5+]
PREC_INTACT_MASS = 10000.0           # median precursor mass alone [4.4 kDa]
PREC_Z8 = 0.15                       # share of precursors at 8+ or more [0.11]
MS1_MASS, MS1_CHARGE = 4000.0, 5     # deconvolved MS1, intensity-weighted medians [4.1 kDa, 4.5+]
MS2_MASS, MS2_MIN = 3000.0, 10      # deconvolved MS2 fragments, median mass and count [1.4 kDa]; native fragments
                                     # are heavy at low charge (aquaporin Z 10.6 kDa at 2.5+)
LADDER_SIGNIF = 8.0                  # charge-ladder significance [5.8]
NATIVE_MZ = 2000.0                   # m/z of a charge series [1584]: native ions sit at m/z 2300-11400
TOP_DOWN_MASS = 10000.0              # median mass: top-down above; below, middle-down unless proteoforms
MIDDLE_DOWN_TAIL = 0.05              # ... above 10 kDa make at least this share (top-down 0.02-0.66, middle-down 0)


def classify(prec, ms1, ms2, ladder, n_ms2):
    """(class, reason) for a run without a digest, or None. Charged MS2 precursors decide when the headers give
    charges; else the deconvolved MS1 masses, the MS2 fragments (deconvolved like MS1) and the MS1 charge ladder."""
    lad = ladder or {}
    native_series = lad.get("states", 0) >= 3 and lad.get("signif", 0) > 0 and lad.get("mz", 0) >= NATIVE_MZ
    if prec.get("charged", 0) >= MIN_PRECURSORS and prec.get("charged_share", 0) >= MIN_CHARGED:
        m, z, z8 = prec["median_mass"], prec["median_charge"], prec["share_z_ge_8"]
        if not ((m >= PREC_MASS and z >= PREC_CHARGE) or m >= PREC_INTACT_MASS or z8 >= PREC_Z8):
            return None
        reason = f"median MS2 precursor charge {z:g}+, median neutral mass {m / 1000:.1f} kDa, {z8:.0%} at 8+ or more"
        if m >= TOP_DOWN_MASS and z <= native_charge(m):
            return "native", reason + f" (native ions carry about 0.078 sqrt(M) = {native_charge(m):.0f} charges)"
        return _size_class(m, prec["share_ge_10k"]), reason
    why = []
    if ms1.get("ms1_deconvolved") and ms1["median_mass"] >= MS1_MASS and ms1["median_charge"] >= MS1_CHARGE:
        why.append(f"deconvolved MS1 masses: median {ms1['median_mass'] / 1000:.1f} kDa at {ms1['median_charge']:g}+")
    if ms2.get("ms1_deconvolved", 0) >= MS2_MIN and ms2["median_mass"] >= MS2_MASS:
        why.append(f"MS2 fragments: median {ms2['median_mass'] / 1000:.1f} kDa at {ms2['median_charge']:g}+")
    if lad.get("signif", 0) >= LADDER_SIGNIF or native_series:
        why.append(f"MS1 charge series {lad['z_min']}+ to {lad['z_max']}+ at m/z {lad['mz']:.0f}")
    if not why:
        return None
    reason = "; ".join(why) + " (no precursor charges in the MS2 headers)"
    if native_series:
        return "native", reason
    if n_ms2 == 0:
        return "intact mass", reason + ", no MS2"
    if why[0].startswith("deconvolved"):
        return _size_class(ms1["median_mass"], ms1["share_ge_10k"]), reason
    return "top-down", reason


def _size_class(median_mass, share_10k):
    """middle-down: precursors of 5-10 kDa without a proteoform tail above 10 kDa (a single small protein such as
    ubiquitin alone looks the same)"""
    return "middle-down" if median_mass < TOP_DOWN_MASS and share_10k < MIDDLE_DOWN_TAIL else "top-down"


def detect(run, flashdeconv=None, threads=1, log=print):
    """The verdict for a run without a digest ({class, reason, recommendation, features}), or None. FLASHDeconv and
    the charge ladder run only when the MS2 headers carry too few precursor charges (DIA, MS1-only and Thermo
    intact runs, direct infusion)."""
    prec = precursor_features(run)
    ms1 = ms2 = ladder = {}
    if not (prec["charged"] >= MIN_PRECURSORS and prec["charged_share"] >= MIN_CHARGED):
        tol = 20.0 if any("TOF" in x for x in run.analyzers) else 10.0
        if flashdeconv:
            ms1 = ms1_features(run, flashdeconv, tol_ppm=tol, threads=threads, log=log)
            ms2 = ms1_features(run, flashdeconv, tol_ppm=tol, threads=threads, log=log, level=2)
        ladder = charge_ladder(run.ms1)
    got = classify(prec, ms1, ms2, ladder, run.n_ms2_total)
    if not got:
        return None
    return {"class": got[0], "reason": got[1], "recommendation": RECOMMENDATION,
            "features": {"precursors": prec, "ms1": ms1, "ms2_fragments": ms2, "ms1_charge_ladder": ladder}}
