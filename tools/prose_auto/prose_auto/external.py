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
import functools
import math
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
        e = RuntimeError((r.stderr or r.stdout)[-1500:])
        e.returncode = r.returncode
        raise e
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
KR_TRYPTIC = 0.8
# residue window on the tag termini (high-res MS2 only): 0.02 Da counted N-terminal F (147.068 Da, nterm_mass) as a
# C-terminal E of a reversed b tag (E + water 147.053 Da)
TERMINUS_WINDOW_DA = 0.008
SILAC_MIN_TAGS = 50   # K- and R-terminal tags each before the heavy shares count (chymotrypsin: Lys8 50% of 12% K/R)


TAG_MIN = 100            # terminal tags per end for the tag-profile call
NONSPECIFIC_SHARE = 0.05   # proteome background mixed into every model: non-specific cleavage (stated, not tuned)
TAG_AAS = "GASPVTCLNDQKEMHFRYW"   # I merged into L
# model -> enzyme value; HLA-I ligands and proteasome products are class I, HLA-II ligands and unspecific cleavage
# class II (their ends barely differ from the proteome: "no protease")
TAG_MODELS = {"Trypsin": "Trypsin", "Lys-C": "Lys-C", "Arg-C": "Arg-C", "Glu-C": "Glu-C", "Chymotrypsin": "Chymotrypsin",
              "Asp-N": "Asp-N", "Lys-N": "Lys-N", "HLA-I": "unspecific cleavage", "proteasome": "unspecific cleavage",
              "HLA-II": "unspecific cleavage", "unspecific": "unspecific cleavage"}
HLA_CLASS = {"HLA-I": "I", "proteasome": "I", "HLA-II": "II", "unspecific": "II"}


@functools.lru_cache(maxsize=None)
def _tag_models():
    """(C-terminal, N-terminal) residue distributions per model from data/protease_models.tsv (MEROPS, MHC Motif
    Atlas, proteome; sources in its header). Arg-C and Asp-N have 7 and 19 MEROPS sites: the PeptideCutter rules
    (after R; before D) with the proteome background at the other end."""
    m = {}
    with open(os.path.join(os.path.dirname(__file__), "data", "protease_models.tsv")) as fh:
        for r in csv.DictReader((l for l in fh if not l.startswith("#")), delimiter="\t"):
            m.setdefault((r["model"], r["end"]), {})[r["residue"]] = float(r["freq"])
    bg = m[("background", "C")]
    one = lambda a: {x: float(x == a) for x in TAG_AAS}
    raw = {k: (m[(f"merops:{k}", "C")], m[(f"merops:{k}", "N")])
           for k in ("Trypsin", "Lys-C", "Glu-C", "Chymotrypsin", "Lys-N", "proteasome")}
    raw.update({"Arg-C": (one("R"), bg), "Asp-N": (bg, one("D")), "unspecific": (bg, bg),
                "HLA-I": (m[("atlas:HLA-I", "C")], m[("atlas:HLA-I", "N")]),
                "HLA-II": (m[("atlas:HLA-II", "C")], m[("atlas:HLA-II", "N")])})
    mix = lambda p: {a: (1 - NONSPECIFIC_SHARE) * p.get(a, 0.0) + NONSPECIFIC_SHARE * bg[a] for a in TAG_AAS}
    return {k: (mix(c), mix(n)) for k, (c, n) in raw.items()}


def protease_call(cterm, nterm):
    """Multinomial log-likelihood of the C- and N-terminal residue counts under each model (the N-terminal end only
    with >= TAG_MIN tags). Returns (model, runner-up with another enzyme value, margin in log-likelihood per tag) or
    None below TAG_MIN C-terminal tags. Margins on 44 test runs: trypsin 0.29-1.61, Lys-C 0.09-0.35 and Arg-C 0.01-0.09
    against trypsin, Glu-C 1.03, HLA-I 0.20-0.47."""
    n_c, n_n = sum(cterm.values()), sum(nterm.values())
    if n_c < TAG_MIN:
        return None
    use_n = n_n >= TAG_MIN

    def ll(cnt, p):
        z = sum(p.values())
        return sum(k * math.log(p[a] / z) for a, k in cnt.items() if k)
    sc = {k: ll(cterm, c) + (ll(nterm, n) if use_n else 0.0) for k, (c, n) in _tag_models().items()}
    rk = sorted(sc, key=lambda k: -sc[k])
    other = next(k for k in rk if TAG_MODELS[k] != TAG_MODELS[rk[0]])
    return rk[0], other, (sc[rk[0]] - sc[other]) / (n_c + (n_n if use_n else 0))


def _residue_counts(v, near, offset=0.0):
    """residue counts over TAG_AAS; labelled K (TMT, TMTpro, iTRAQ4, Lys8) count as K; Arg10 is left out (166.109 Da
    shows at 3-15% in label-free runs)"""
    cnt = {a: near(v, _RES[a] + offset) for a in TAG_AAS}
    cnt["K"] += sum(near(v, _RES[k] + offset) for k in ("K+TMT", "K+TMTpro", "K+iTRAQ4", "K+8"))
    return cnt


Y1_K = 147.1128   # y1 of a C-terminal K; MS2 scans that start above it hide K-ending y tags


def fastag_termini(fastag, mzml, frag_tol=20.0, frag_unit="ppm", subsample=0.25, threads=0, log=print,
                   ms2_low_mz=None):
    """Protease and labels from the termini of FASTag k=4 tags (Carbamidomethyl only, so labels are mass gaps).
    Tags read from y ions keep the C-terminal end in cterm_mass (one residue left: its residue mass); tags read
    from b ions are written reversed, with the C-terminal end in nterm_mass plus water; the N-terminal label is the
    bare label mass in either column. On 17 calibration runs: C-terminal K/R share 0.86-0.99 on tryptic HCD runs (threshold 0.80; on 180 benchmark
    runs tryptic Orbitrap DDA 0.84-0.98, tryptic timsTOF 0.33-0.66),
    0.27-0.42 on HLA class I and II (class I: hydrophobic anchors L/V/F/Y/M 0.44-0.63, class II about 0.1);
    N-terminal TMT/TMTpro on 5-10% of the tags of labelled runs (>= 0.1% otherwise); heavy Lys8 and Arg10 shares
    >= 0.25 only in SILAC runs (label-free <= 0.16, diaPASEF pseudo-spectra show an Arg10 artifact without Lys8).
    The protease (or HLA class) is the tag-profile call over both ends (protease_call; N-terminal residue: bare
    residue mass in nterm_mass). High-res MS2 only; 1-16 s on 25%.
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
    w = TERMINUS_WINDOW_DA
    near = lambda v, m: bisect.bisect_right(v, m + w) - bisect.bisect_left(v, m - w)
    res = {a: near(c, m) + near(n, m + H2O) for a, m in _RES.items()}
    tot, tags = sum(res.values()), len(c)
    if tot < TAG_MIN:
        return [], {"tags": tags, "cterm_tags": tot}
    share = {a: v / tot for a, v in res.items()}
    kr = sum(v for a, v in share.items() if a[0] in "KR")
    anchors = sum(share[a] for a in "LVFYM")
    cterm = {a: x + y for (a, x), y in zip(_residue_counts(c, near).items(), _residue_counts(n, near, H2O).values())}
    nterm = _residue_counts(n, near)
    # MS2 scans from m/z 150 or 156 (PXD066944, PXD038809) left K 0.02-0.13 on tryptic runs: no tag call there
    call = None if ms2_low_mz and ms2_low_mz > Y1_K + 0.1 else protease_call(cterm, nterm)
    stats = {"tags": tags, "cterm_tags": tot, "cterm_KR": round(kr, 3), "cterm_anchors_LVFYM": round(anchors, 3),
             "cterm_top": {a: round(v, 3) for a, v in sorted(share.items(), key=lambda x: -x[1])[:6]},
             "nterm_tags": sum(nterm.values()), "nterm_D": round(nterm["D"] / max(sum(nterm.values()), 1), 3),
             "ms2_low_mz": ms2_low_mz}
    ev = []
    if call:
        model, other, margin = call
        # isobaric labels make K-ending tags easy to read (intense labelled y1): tryptic TMTpro runs show K 0.93,
        # R 0.06 (PXD037434, PXD001670), so the K/R split is no evidence there
        iso_k = sum(near(c, _RES[k]) + near(n, _RES[k] + H2O) for k in ("K+TMT", "K+TMTpro", "K+iTRAQ4"))
        if model in ("Lys-C", "Arg-C") and TAG_MODELS[other] == "Trypsin" and iso_k > cterm["K"] / 2:
            margin = 0.0
        stats.update({"tag_call": model, "tag_runner_up": other, "tag_margin": round(margin, 3)})
        why = (f"tag-profile call over {sum(cterm.values())} C- and {sum(nterm.values())} N-terminal residues: {model} "
               f"(next {other}, {margin:.2f} log-likelihood per tag)")
        if model in HLA_CLASS:
            stats["hla_hint"] = f"HLA class {HLA_CLASS[model]}?"
        # the margin is the confidence: a weak call loses to a confident Jev answer (reconcile._enzyme)
        ev.append(Evidence("enzyme", TAG_MODELS[model], round(min(0.8, 0.45 + margin), 3), "data", "FASTag termini",
                           why, stats))
    for lab, m in _NLABEL.items():
        x, bg = near(n, m) + near(c, m), near(n, m + 0.5) + near(c, m + 0.5)
        if x >= 0.01 * tags and x >= 20 * max(bg, 1):
            ev.append(Evidence("label", lab, 0.5, "data", "FASTag termini",
                               f"{x / tags:.1%} of the sequence tags start after a {m:.3f} Da N-terminal gap ({lab}"
                               + ("; same mass as iTRAQ8plex, the reporter ions decide" if lab.startswith("TMTpro") else "")
                               + ")", stats))
    hk, hr = share["K+8"] / max(share["K+8"] + share["K"], 1e-9), share["R+10"] / max(share["R+10"] + share["R"], 1e-9)
    stats.update({"heavy_K8": round(hk, 3), "heavy_R10": round(hr, 3)})
    nk, nr = res["K"] + res["K+8"], res["R"] + res["R+10"]
    if hk >= 0.2 and hr >= 0.2 and kr >= KR_TRYPTIC and min(nk, nr) >= SILAC_MIN_TAGS:
        # both heavy shares >= 30% occurred only in SILAC runs (5 of 164, three of them annotated label free in the
        # SDRF but SILAC by their text or file name); 20-30% stays a hint
        ev.append(Evidence("label", "SILAC (Lys8/Arg10)", 0.7 if min(hk, hr) >= 0.3 else 0.5, "data", "FASTag termini",
                           f"heavy C-terminal Lys8 {hk:.0%} and Arg10 {hr:.0%} of the tryptic C-termini", stats))
    return ev, stats


def fastag_shortlist(evs, n=3):
    """The top-n taxa of a FASTag species ranking (reagent genera only when nothing else is ranked), for the
    two-tier organism test."""
    taxa = [t for e in evs if e.method == "FASTag species" for t in (e.stats or {}).get("taxa", [])]
    names = [t["name"] for t in taxa if t.get("name")]
    real = [x for x in names if x.split()[0] not in REAGENT_GENERA]
    return (real or names)[:n]


def fastag_alkylation(fastag, mzml, fasta, frag_tol=20.0, frag_unit="ppm", threads=0, log=print, subsample=0.0):
    """Cys alkylation from the FASTag mass-gap histogram without fixed mods."""
    with tempfile.TemporaryDirectory(prefix="fastag_") as tmp:
        out = os.path.join(tmp, "tags.tsv")
        delta = os.path.join(tmp, "delta.tsv")
        cmd = [fastag, "-in", mzml, "-out", out, "-tag_length", 4, "-extension", 6, "-threads", threads,
               "-recon_fasta", fasta, "-recon_out", os.path.join(tmp, "recon.tsv"), "-delta_out", delta,
               "-recon_min_length", 5,   # the size-derived default (6-7 on a proteome) placed 2.5-14x fewer spectra
               "-fixed_modifications"] + _frag_args(frag_tol, frag_unit)
        if subsample:
            cmd += ["-subsample_fraction", subsample]
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
             "top_bins": sorted(hist, key=lambda x: -x[1])[:15],
             "hist": [h[:2] for h in hist if h[1] >= 2]}   # for delta_combos; singletons are noise
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


# Bruker Frames.MsMsType: 0 MS1, 8 ddaPASEF MS/MS, 9 diaPASEF MS/MS, 10 prm-PASEF MS/MS
TIMS_MODES = {8: "ddaPASEF", 9: "diaPASEF", 10: "prm-PASEF"}


def tims_acquisition(d):
    """Acquisition mode of a Bruker timsTOF .d from analysis.tdf: 'ddaPASEF', 'diaPASEF', 'prm-PASEF', 'MS1 only',
    or None when the file is unreadable or mixes MS/MS types. The DIA window tables exist (empty) in ddaPASEF files
    too, so the frame types decide."""
    import sqlite3
    tdf = os.path.join(d, "analysis.tdf")
    if not os.path.exists(tdf):
        return None
    try:
        db = sqlite3.connect(f"file:{tdf}?mode=ro", uri=True)
        types = {t for (t,) in db.execute("SELECT DISTINCT MsMsType FROM Frames")} - {0}
    except sqlite3.Error:
        return None
    if not types:
        return "MS1 only"
    return TIMS_MODES.get(types.pop()) if len(types) == 1 else None


def tims_instrument(d):
    """Instrument name of a Bruker .d (analysis.tdf GlobalMetadata InstrumentName, e.g. 'timsTOF Pro 2'), or None"""
    import sqlite3
    try:
        db = sqlite3.connect(f"file:{os.path.join(d, 'analysis.tdf')}?mode=ro", uri=True)
        row = db.execute("SELECT Value FROM GlobalMetadata WHERE Key = 'InstrumentName'").fetchone()
    except sqlite3.Error:
        return None
    return row[0].strip() if row and row[0] and row[0].strip() else None


def fileconverter(exe, inp, out_mzml, threads=0, log=print):
    """Bruker ddaPASEF .d -> mzML with OpenMS FileConverter (built-in timsTOF reader: one MS2 per precursor)."""
    _run([exe, "-in", inp, "-out", out_mzml] + (["-threads", threads] if threads else []), log, timeout=6 * 3600)
    return out_mzml


DIASPEXTRACT_DDA_INPUT = 11   # DIAspeXtract exit code: the input is DDA (ddaPASEF), not DIA


def diaspextract(exe, inp, out_mzml, threads=0, extra=(), log=print):
    """diaPASEF .d (or DIA mzML) -> pseudo-MS/MS mzML. A RuntimeError carries DIAspeXtract's exit code as
    .returncode (DIASPEXTRACT_DDA_INPUT: the input is DDA)."""
    cmd = [exe, "-in", inp, "-out", out_mzml] + (["-threads", threads] if threads else []) + list(extra)
    _run(cmd, log, timeout=12 * 3600)
    return out_mzml
