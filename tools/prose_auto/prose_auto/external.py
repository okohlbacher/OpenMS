"""Adapters for external tools: FASTag and DIAspeXtract.

FASTag (github.com/okohlbacher/FASTag) reads sequence tags from MS2 spectra.
prose-auto uses two of its outputs:

* `-species`: a genus call from tag 7-mers against its bundled index of ~50
  reference proteomes (model organisms, contaminants, pathogens, microbiome).
  Database free, so it also works when the organism is not in the panel.
  Genus level only: close relatives (mammals) share most 7-mers, and reagent
  genera (Bos, Sus, Oryctolagus, ...) show up in almost every run.
* `-recon_fasta` + `-delta_out`: tags placed on a proteome with NO fixed
  modification; the histogram of flank mass gaps shows the Cys alkylation
  (+57.021 carbamidomethyl, +45.988 methylthio, ...) and labels as peaks.

DIAspeXtract (github.com/okohlbacher/diaspextract) turns diaPASEF (Bruker .d,
or DIA mzML) into pseudo-MS/MS spectra with one precursor each, so the DDA
detectors and the mini-search can run on DIA data too.
"""

from __future__ import annotations

import csv
import os
import subprocess
import tempfile

from .evidence import Evidence

REAGENT_GENERA = {"Bos", "Sus", "Oryctolagus", "Gallus", "Capra", "Ovis", "Equus", "Lysobacter",
                  "Achromobacter", "Staphylococcus"}

# Cys alkylation and isobaric labels as mass gaps when the search sets no fixed modification
DELTA_CANDIDATES = {
    "Carbamidomethyl (C)": 57.021464,
    "Propionamide (C)": 71.037114,
    "Nethylmaleimide (C)": 125.047679,
    "Methylthio (C)": 45.987721,
    "Carboxymethyl (C)": 58.005479,
}


def _run(cmd, log, timeout=6 * 3600):
    log("  $ " + " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-1500:])
    return r


def _tsv(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _frag_args(frag_tol, frag_unit):
    return ["-fragment_tolerance", frag_tol, "-fragment_tolerance_unit", frag_unit]


def _taxonomy_args(taxonomy_dir, rank):
    """an external FASTag index (tax_k7.taxdb + pruned nodes/names.dmp in one directory) and the report rank"""
    a = ["-species_rank", rank]
    if taxonomy_dir:
        a += ["-taxdb", os.path.join(taxonomy_dir, "tax_k7.taxdb"),
              "-taxonomy_nodes", os.path.join(taxonomy_dir, "nodes.dmp"),
              "-taxonomy_names", os.path.join(taxonomy_dir, "names.dmp")]
    return a


def fastag_species(fastag, mzml, frag_tol=20.0, frag_unit="ppm", fixed=("Carbamidomethyl (C)",),
                   subsample=0.0, threads=0, log=print, taxonomy_dir=None, rank="genus"):
    """Taxon call from FASTag -species: genus with the shipped index, species with an extended one."""
    with tempfile.TemporaryDirectory(prefix="fastag_") as tmp:
        out = os.path.join(tmp, "tags.tsv")
        sp = os.path.join(tmp, "species.tsv")
        cmd = [fastag, "-in", mzml, "-out", out, "-species", "-tag_length", 7, "-species_out", sp,
               "-threads", threads] + _frag_args(frag_tol, frag_unit) + _taxonomy_args(taxonomy_dir, rank)
        cmd += ["-fixed_modifications"] + list(fixed)
        if subsample:
            cmd += ["-subsample_fraction", subsample]
        _run(cmd, log)
        rows = _tsv(sp) if os.path.exists(sp) else []
    if not rows:
        return [Evidence("organism", "unknown", 0.1, "data", "FASTag species", "FASTag reported no taxon")]
    for r in rows:
        r["adjusted"] = float(r.get("adjusted") or r.get("observed") or 0)
        r["observed"] = float(r.get("observed") or 0)
    rows.sort(key=lambda r: -r["adjusted"])
    table = [{k: r.get(k) for k in ("name", "observed", "adjusted", "expected", "qvalue")} for r in rows[:15]]
    # the top non-reagent genus is the call; a reagent genus on top is reported as such
    top = rows[0]
    real = [r for r in rows if str(r["name"]).split()[0] not in REAGENT_GENERA]  # genus or species rank
    call = real[0] if real and (str(top["name"]).split()[0] in REAGENT_GENERA and real[0]["adjusted"] >= 0.5 * top["adjusted"]) else top
    nxt = next((r for r in rows if r is not call), None)
    margin = (call["adjusted"] - (nxt["adjusted"] if nxt else 0)) / max(call["adjusted"], 1)
    n = call["observed"]
    conf = 0.25 + min(0.35, 0.12 * (n ** 0.5) / 3) + min(0.3, margin)
    conf = min(0.85, conf if n >= 20 else min(conf, 0.35))
    detail = (f"FASTag {rank} call {call['name']} from {int(n)} tag-carrying spectra"
              + (f"; next {nxt['name']} ({nxt['adjusted']:.0f} vs {call['adjusted']:.0f})" if nxt else "")
              + ("; reagent genus on top skipped" if call is not top else ""))
    return [Evidence("organism", call["name"], conf, "data", "FASTag species", detail, {"taxa": table})]


H2O = 18.010565
_AA = {"G": 57.02146, "A": 71.03711, "S": 87.03203, "P": 97.05276, "V": 99.06841, "T": 101.04768, "C": 160.03065,
       "L": 113.08406, "N": 114.04293, "D": 115.02694, "Q": 128.05858, "K": 128.09496, "E": 129.04259,
       "M": 131.04049, "H": 137.05891, "F": 147.06841, "R": 156.10111, "Y": 163.06333, "W": 186.07931}
_RES = dict(_AA, **{"K+TMT": _AA["K"] + 229.162932, "K+TMTpro": _AA["K"] + 304.207146,
                    "K+iTRAQ4": _AA["K"] + 144.102063, "K+8": _AA["K"] + 8.014199, "R+10": _AA["R"] + 10.008269})
_NLABEL = {"TMT6/10/11plex": 229.162932, "TMTpro (16/18plex)": 304.207146, "iTRAQ4plex": 144.102063}
KR_TRYPTIC, KR_NONTRYPTIC, CLASS_I_ANCHORS = 0.8, 0.5, 0.35


def fastag_termini(fastag, mzml, frag_tol=20.0, frag_unit="ppm", subsample=0.25, threads=0, log=print):
    """Protease and labels from the termini of FASTag k=4 tags (Carbamidomethyl only, so labels are mass gaps).
    Tags read from y ions keep the C-terminal end in cterm_mass (one residue left: its residue mass); tags read
    from b ions are written reversed, with the C-terminal end in nterm_mass plus water; the N-terminal label is the
    bare label mass in either column. On 17 calibration runs: C-terminal K/R share 0.86-0.99 on tryptic HCD runs,
    0.27-0.42 on HLA class I and II (class I: hydrophobic anchors L/V/F/Y/M 0.44-0.63, class II about 0.1);
    N-terminal TMT/TMTpro on 5-10% of the tags of labelled runs (>= 0.1% otherwise); heavy Lys8 and Arg10 shares
    >= 0.25 only in SILAC runs (label-free <= 0.16, diaPASEF pseudo-spectra show an Arg10 artifact without Lys8).
    Ion-trap and pseudo-spectra K/R shares (0.6-0.65) give no protease call. High-res MS2 only; 1-16 s on 25%.
    Returns evidence (enzyme, label) and the stats (C-terminal residue shares, HLA class hint)."""
    import bisect
    if frag_unit != "ppm":
        return [], {}
    with tempfile.TemporaryDirectory(prefix="fastag_termini_") as tmp:
        out = os.path.join(tmp, "tags.tsv")
        cmd = [fastag, "-in", mzml, "-out", out, "-tag_length", 4, "-threads", threads,
               "-subsample_fraction", subsample] + _frag_args(frag_tol, frag_unit)
        _run(cmd, log)
        c, n = [], []
        for r in _tsv(out):
            if r.get("gapped") == "0" and float(r.get("evalue") or 9) <= 1:
                c.append(float(r["cterm_mass"]))
                n.append(float(r["nterm_mass"]))
    c.sort(); n.sort()
    w = 0.02
    near = lambda v, m: bisect.bisect_right(v, m + w) - bisect.bisect_left(v, m - w)
    res = {a: near(c, m) + near(n, m + H2O) for a, m in _RES.items()}
    tot, tags = sum(res.values()), len(c)
    if tot < 200:
        return [], {"tags": tags, "cterm_tags": tot}
    share = {a: v / tot for a, v in res.items()}
    kr = sum(v for a, v in share.items() if a[0] in "KR")
    anchors = sum(share[a] for a in "LVFYM")
    stats = {"tags": tags, "cterm_tags": tot, "cterm_KR": round(kr, 3), "cterm_anchors_LVFYM": round(anchors, 3),
             "cterm_top": {a: round(v, 3) for a, v in sorted(share.items(), key=lambda x: -x[1])[:6]}}
    ev = []
    if kr >= KR_TRYPTIC:
        ev.append(Evidence("enzyme", "Trypsin", 0.6, "data", "FASTag termini",
                           f"{kr:.0%} of the C-terminal residues of {tot} sequence tags are K/R: a tryptic digest", stats))
    elif kr <= KR_NONTRYPTIC:
        stats["hla_hint"] = "HLA class I?" if anchors >= CLASS_I_ANCHORS else "HLA class II?"
        ev.append(Evidence("enzyme", "unspecific cleavage", 0.45, "data", "FASTag termini",
                           f"only {kr:.0%} of the C-terminal residues of {tot} sequence tags are K/R (tryptic: >= 86%); "
                           f"hydrophobic anchors L/V/F/Y/M {anchors:.0%}: {stats['hla_hint']}", stats))
    for lab, m in _NLABEL.items():
        x, bg = near(n, m) + near(c, m), near(n, m + 0.5) + near(c, m + 0.5)
        if x >= 0.01 * tags and x >= 20 * max(bg, 1):
            ev.append(Evidence("label", lab, 0.5, "data", "FASTag termini",
                               f"{x / tags:.1%} of the sequence tags start after a {m:.3f} Da N-terminal gap ({lab}"
                               + ("; same mass as iTRAQ8plex, the reporter ions decide" if lab.startswith("TMTpro") else "")
                               + ")", stats))
    hk, hr = share["K+8"] / max(share["K+8"] + share["K"], 1e-9), share["R+10"] / max(share["R+10"] + share["R"], 1e-9)
    stats.update({"heavy_K8": round(hk, 3), "heavy_R10": round(hr, 3)})
    if hk >= 0.2 and hr >= 0.2:
        ev.append(Evidence("label", "SILAC (Lys8/Arg10)", 0.5, "data", "FASTag termini",
                           f"heavy C-terminal Lys8 {hk:.0%} and Arg10 {hr:.0%} of the tryptic C-termini", stats))
    return ev, stats


def fastag_shortlist(evs, n=3):
    """The top-n taxa of a FASTag species ranking (reagent genera only when nothing else is ranked), for the
    two-tier organism test."""
    taxa = [t for e in evs if e.method == "FASTag species" for t in (e.stats or {}).get("taxa", [])]
    names = [t["name"] for t in taxa if t.get("name")]
    real = [x for x in names if x.split()[0] not in REAGENT_GENERA]
    return (real or names)[:n]


def fastag_alkylation(fastag, mzml, fasta, frag_tol=20.0, frag_unit="ppm", threads=0, log=print):
    """Cys alkylation from the FASTag mass-gap histogram without fixed mods."""
    with tempfile.TemporaryDirectory(prefix="fastag_") as tmp:
        out = os.path.join(tmp, "tags.tsv")
        delta = os.path.join(tmp, "delta.tsv")
        cmd = [fastag, "-in", mzml, "-out", out, "-tag_length", 4, "-extension", 6, "-threads", threads,
               "-recon_fasta", fasta, "-recon_out", os.path.join(tmp, "recon.tsv"), "-delta_out", delta,
               "-fixed_modifications"] + _frag_args(frag_tol, frag_unit)
        _run(cmd, log)
        rows = _tsv(delta) if os.path.exists(delta) else []
    hist = []
    for r in rows:
        try:
            hist.append((float(r.get("delta")), int(float(r.get("spectra") or 0)), r.get("top_interps", "")))
        except (TypeError, ValueError):
            continue
    total = sum(c for _, c, _ in hist)
    tol = 0.02 if frag_unit == "ppm" else 0.5
    counts = {name: sum(c for d, c, _ in hist if abs(d - m) <= tol) for name, m in DELTA_CANDIDATES.items()}
    zero = sum(c for d, c, _ in hist if abs(d) <= tol)
    stats = {"counts": counts, "zero_bin": zero, "spectra": total,
             "top_bins": sorted(hist, key=lambda x: -x[1])[:15]}
    best = max(counts, key=counts.get)
    second = sorted(counts.values())[-2] if len(counts) > 1 else 0
    if counts[best] < 10:
        return [Evidence("cys_alkylation", "unknown", 0.15, "data", "FASTag mass gaps",
                         f"no Cys alkylation peak in the FASTag gap histogram ({total} spectra placed)", stats)]
    ratio = (counts[best] + 1) / (second + 1)
    conf = min(0.85, 0.4 + 0.15 * ratio ** 0.5)
    return [Evidence("cys_alkylation", best, conf, "data", "FASTag mass gaps",
                     f"{counts[best]} placed spectra with a {DELTA_CANDIDATES[best]:+.3f} Da gap "
                     f"(next candidate {second}); searched without fixed modifications", stats)]


# DIAspeXtract on a constant-mobility copy: mobility tracing, weighting, charge veto and twin folding off
NO_MOBILITY_OPTIONS = ["-trace:detector", "openms", "-gate:delta_im", "1.0", "-assembly:im_weight_sigma", "0",
                       "-charge:im_charge_veto", "false", "-assembly:twin_im_tolerance", "-1",
                       "-trace:im_slice_merge", "-1"]


def with_constant_mobility(src, dst, k0=1.0):
    """Copy of a DIA mzML without ion mobility in which every peak carries 1/K0 = k0, so DIAspeXtract accepts it."""
    import numpy as np
    import pyopenms as oms
    exp = oms.MSExperiment()
    oms.MzMLFile().load(str(src), exp)
    spectra = exp.getSpectra()  # iterating an MSExperiment yields copies
    for s in spectra:
        fda = oms.FloatDataArray()
        fda.setName("Ion Mobility")
        fda.set_data(np.full(s.size(), k0, dtype=np.float32))
        s.setFloatDataArrays([f for f in s.getFloatDataArrays() if f.getName() != "Ion Mobility"] + [fda])
        s.setDriftTimeUnit(oms.DriftTimeUnit.VSSC)
    exp.setSpectra(spectra)
    exp.updateRanges()
    oms.MzMLFile().store(str(dst), exp)
    return dst


def diaspextract(exe, inp, out_mzml, threads=0, extra=(), log=print):
    """diaPASEF .d (or DIA mzML) -> pseudo-MS/MS mzML."""
    cmd = [exe, "-in", inp, "-out", out_mzml] + (["-threads", threads] if threads else []) + list(extra)
    _run(cmd, log, timeout=12 * 3600)
    return out_mzml
