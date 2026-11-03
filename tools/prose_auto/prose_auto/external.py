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


FASTAG_MIN_VERSION = (1, 8, 0)   # -digest_out, -label_out, -massgap_out
DIGEST_MODELS = os.path.join(os.path.dirname(__file__), "data", "prose_auto_013_digest_models.tsv")
_NLABEL = {"TMT6/10/11plex": ("TMT", 229.162932), "TMTpro (16/18plex)": ("TMTpro", 304.207146),
           "iTRAQ4plex": ("iTRAQ4", 144.102063)}
KR_TRYPTIC = 0.8
SILAC_MIN_TAGS = 50   # K- and R-terminal tags each before the heavy shares count (chymotrypsin: Lys8 50% of 12% K/R)
TAG_MIN = 100         # C-terminal tag ends before the termini say anything (FASTag's -digest_tag_min)
TAG_AAS = "GASPVTCLNDQKEMHFRYW"   # I merged into L
# model -> enzyme value; HLA-I ligands and proteasome products are class I, HLA-II ligands and unspecific cleavage
# class II (their ends barely differ from the proteome: "no protease")
TAG_MODELS = {"Trypsin": "Trypsin", "Lys-C": "Lys-C", "Arg-C": "Arg-C", "Glu-C": "Glu-C", "Chymotrypsin": "Chymotrypsin",
              "Asp-N": "Asp-N", "Lys-N": "Lys-N", "HLA-I": "unspecific cleavage", "proteasome": "unspecific cleavage",
              "HLA-II": "unspecific cleavage", "unspecific": "unspecific cleavage"}
HLA_CLASS = {"HLA-I": "I", "proteasome": "I", "HLA-II": "II", "unspecific": "II"}


@functools.lru_cache(maxsize=None)
def fastag_version(fastag):
    """(major, minor, patch) from the 'Version:' line of FASTag --help, or None"""
    r = subprocess.run([str(fastag), "--help"], capture_output=True, text=True, timeout=120)
    for line in (r.stdout + r.stderr).splitlines():
        if line.startswith("Version:"):
            try:
                return tuple(int(x) for x in line.split()[1].split(".")[:3])
            except ValueError:
                return None
    return None


def require_fastag(fastag):
    v = fastag_version(fastag)
    if not v or v < FASTAG_MIN_VERSION:
        raise RuntimeError(f"prose-auto needs FASTag >= {'.'.join(map(str, FASTAG_MIN_VERSION))} (-digest_out, "
                           f"-label_out, -massgap_out); {fastag} reports {'.'.join(map(str, v)) if v else 'no version'}")


def _report(path):
    """a FASTag long-form report (section, key, value, n, description) as {(section, key): value}"""
    return {(r["section"], r["key"]): r["value"] for r in _tsv(path)}


def _num(rep, section, key, default=0.0):
    v = rep.get((section, key), "-")
    return default if v in ("-", "") else float(v)


def fastag_termini(fastag, mzml, frag_tol=20.0, frag_unit="ppm", subsample=0.25, threads=0, log=print):
    """Protease and labels from the termini of FASTag k=4 tags (Carbamidomethyl only, so labels are mass gaps).
    FASTag counts the tag ends (-digest_out) and the label gaps (-label_out) and scores the tag-profile models of
    data/prose_auto_013_digest_models.tsv (MEROPS, MHC Motif Atlas, proteome background) by multinomial
    log-likelihood. On 17 calibration runs: C-terminal K/R share 0.86-0.99 on tryptic HCD runs (threshold 0.80; on
    180 benchmark runs tryptic Orbitrap DDA 0.84-0.98, tryptic timsTOF 0.33-0.66), 0.27-0.42 on HLA class I and II
    (class I: hydrophobic anchors L/V/F/Y/M 0.44-0.63, class II about 0.1); N-terminal TMT/TMTpro on 5-10% of the tags
    of labelled runs (>= 0.1% otherwise); heavy Lys8 and Arg10 shares >= 0.25 only in SILAC runs (label-free <= 0.16,
    diaPASEF pseudo-spectra show an Arg10 artifact without Lys8). FASTag gives no call on MS2 scans that start above
    y1 of K (PXD066944, PXD038809: K 0.02-0.13 on tryptic runs). High-res MS2 only; 1-16 s on 25%.
    Returns evidence (enzyme, label) and the stats (C-terminal residue shares, HLA class hint)."""
    if frag_unit != "ppm":
        return [], {}
    with tempfile.TemporaryDirectory(prefix="fastag_termini_") as tmp:
        dg, lb = os.path.join(tmp, "digest.tsv"), os.path.join(tmp, "label.tsv")
        _run([fastag, "-in", mzml, "-out", os.path.join(tmp, "tags.tsv"), "-tag_length", 4, "-threads", threads,
              "-subsample_fraction", subsample, "-digest_out", dg, "-label_out", lb, "-digest_models", DIGEST_MODELS]
             + _frag_args(frag_tol, frag_unit), log)
        return termini_evidence(_report(dg), _report(lb))


def termini_evidence(d, lab):
    """The prose-auto policy on FASTag's -digest_out and -label_out reports (dicts from _report)."""
    tags, tot = int(_num(d, "count", "tags_filtered")), int(_num(d, "count", "tot"))
    if tot < TAG_MIN:
        return [], {"tags": tags, "cterm_tags": tot}
    # res: the C-terminal residue keys (labelled K and Arg10 apart), as the K/R share counts them
    res = {a: int(_num(d, "pos", f"C.P1.{a}")) for a in TAG_AAS if a not in "KR"}
    res.update({k: int(_num(d, "residue", f"C.{k}")) for k in ("K", "K+TMT", "K+TMTpro", "K+iTRAQ4", "K+8", "R", "R+10")})
    share = {a: v / tot for a, v in res.items()}
    cterm_k, n_n = _num(d, "pos", "C.P1.K"), int(_num(d, "count", "n_n"))
    stats = {"tags": tags, "cterm_tags": tot, "cterm_KR": round(_num(d, "share", "kr"), 3),
             "cterm_anchors_LVFYM": round(_num(d, "share", "anchors_LVFYM"), 3),
             "cterm_top": {a: round(v, 3) for a, v in sorted(share.items(), key=lambda x: -x[1])[:6]},
             "nterm_tags": n_n, "nterm_D": round(_num(d, "share", "nterm_D"), 3),
             "ms2_first_peak_mz": _num(d, "meta", "ms2_first_peak_mz", None)}
    ev = []
    if d.get(("call", "status")) == "call":
        model, other, margin = d[("call", "model")], d[("call", "runner_up")], _num(d, "call", "margin")
        # isobaric labels make K-ending tags easy to read (intense labelled y1): tryptic TMTpro runs show K 0.93,
        # R 0.06 (PXD037434, PXD001670), so the K/R split is no evidence there
        iso_k = res["K+TMT"] + res["K+TMTpro"] + res["K+iTRAQ4"]
        if model in ("Lys-C", "Arg-C") and TAG_MODELS.get(other) == "Trypsin" and iso_k > cterm_k / 2:
            margin = 0.0
        stats.update({"tag_call": model, "tag_runner_up": other, "tag_margin": round(margin, 3)})
        n_c = int(_num(d, "count", "n_c"))
        why = (f"tag-profile call over {n_c} C- and {n_n} N-terminal residues: {model} "
               f"(next {other}, {margin:.2f} log-likelihood per tag)")
        if model in HLA_CLASS:
            stats["hla_hint"] = f"HLA class {HLA_CLASS[model]}?"
        # the margin is the confidence: a weak call loses to a confident Jev answer (reconcile._enzyme)
        ev.append(Evidence("enzyme", TAG_MODELS[model], round(min(0.8, 0.45 + margin), 3), "data", "FASTag termini",
                           why, stats))
    else:
        stats["tag_nocall"] = d.get(("call", "reason"))
    for name, (key, m) in _NLABEL.items():
        x, bg = _num(lab, "nlabel", f"{key}.count"), _num(lab, "nlabel", f"{key}.background")
        if x >= 0.01 * tags and x >= 20 * max(bg, 1):
            ev.append(Evidence("label", name, 0.5, "data", "FASTag termini",
                               f"{x / tags:.1%} of the sequence tags start after a {m:.3f} Da N-terminal gap ({name}"
                               + ("; same mass as iTRAQ8plex, the reporter ions decide" if key == "TMTpro" else "")
                               + ")", stats))
    hk, hr = _num(lab, "heavy", "K8.share"), _num(lab, "heavy", "R10.share")
    stats.update({"heavy_K8": round(hk, 3), "heavy_R10": round(hr, 3)})
    nk, nr = _num(lab, "heavy", "K.tags"), _num(lab, "heavy", "R.tags")
    if hk >= 0.2 and hr >= 0.2 and stats["cterm_KR"] >= KR_TRYPTIC and min(nk, nr) >= SILAC_MIN_TAGS:
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
    """Cys alkylation and modification combinations from FASTag's mass-gap report (-massgap_out: tags placed on
    fasta without fixed modifications)."""
    with tempfile.TemporaryDirectory(prefix="fastag_") as tmp:
        mg = os.path.join(tmp, "massgap.tsv")
        cmd = [fastag, "-in", mzml, "-out", os.path.join(tmp, "tags.tsv"), "-tag_length", 4, "-extension", 6,
               "-threads", threads, "-recon_fasta", fasta, "-recon_out", os.path.join(tmp, "recon.tsv"),
               "-massgap_out", mg,
               "-recon_min_length", 5,   # the size-derived default (6-7 on a proteome) placed 2.5-14x fewer spectra
               "-fixed_modifications"] + _frag_args(frag_tol, frag_unit)
        if subsample:
            cmd += ["-subsample_fraction", subsample]
        _run(cmd, log)
        return massgap_evidence(_report(mg) if os.path.exists(mg) else {})


# FASTag modification name -> ProSE names (the variable modifications a dominant gap proposes)
MOD_NAMES = {
    "Oxidation": ["Oxidation (M)"], "Dioxidation": ["Dioxidation (M)"], "Deamidated": ["Deamidated (N)", "Deamidated (Q)"],
    "Gln->pyro-Glu": ["Gln->pyro-Glu (N-term Q)"], "Glu->pyro-Glu": ["Glu->pyro-Glu (N-term E)"],
    "Carbamidomethyl": ["Carbamidomethyl (C)"], "Cation:Na": ["Cation:Na (DE)"], "Cation:K": ["Cation:K (DE)"],
    "Carbamyl": ["Carbamyl (N-term)"], "Formyl": ["Formyl (N-term)"], "Acetyl": ["Acetyl (K)", "Acetyl (N-term)"],
    "Methyl": ["Methyl (K)", "Methyl (R)"], "Dimethyl": ["Dimethyl (K)", "Dimethyl (R)"], "Trimethyl": ["Trimethyl (K)"],
    "Propionyl": ["Propionyl (K)", "Propionyl (N-term)"], "Butyryl": ["Butyryl (K)"], "Crotonyl": ["Crotonyl (K)"],
    "Succinyl": ["Succinyl (K)"], "Malonyl": ["Malonyl (K)"], "GG": ["GG (K)"],
    "Phospho": ["Phospho (S)", "Phospho (T)", "Phospho (Y)"], "Sulfo": ["Sulfo (Y)"], "Nitro": ["Nitro (Y)"],
    "HexNAc": ["HexNAc (S)", "HexNAc (T)"], "Hex": ["Hex (K)"], "Cysteinyl": ["Cysteinyl (C)"],
    "Methylthio": ["Methylthio (C)"], "Propionamide": ["Propionamide (C)"], "Nethylmaleimide": ["Nethylmaleimide (C)"],
    "TMT6plex": ["TMT6plex (K)", "TMT6plex (N-term)"], "TMTpro": ["TMTpro (K)", "TMTpro (N-term)"],
    "iTRAQ4plex": ["iTRAQ4plex (K)", "iTRAQ4plex (N-term)"], "Label:13C(6)15N(2)": ["Label:13C(6)15N(2) (K)"],
    "Label:13C(6)15N(4)": ["Label:13C(6)15N(4) (R)"], "Label:2H(4)": ["Label:2H(4) (K)"],
    "Label:13C(6)": ["Label:13C(6) (R)"], "Met-loss": ["Met-loss (Protein N-term M)"],
    "Met-loss+Acetyl": ["Met-loss+Acetyl (Protein N-term M)"],
}
ENRICHMENT = {"Phospho": "Phospho (STY)", "Acetyl": "Acetyl (K)", "GG": "GlyGly (K)", "HexNAc": "Glyco (HexNAc oxonium)"}
SILAC_GAPS = {"Label:2H(4)": "Lys4", "Label:13C(6)": "Arg6", "Label:13C(6)15N(2)": "Lys8", "Label:13C(6)15N(4)": "Arg10"}


def massgap_evidence(rep, max_mods_out=5):
    """The prose-auto policy on FASTag's -massgap_out report: the Cys alkylation peak; variable_mods (modifications
    explaining >= 2% of the spectra with a mass gap), enrichment (phospho, acetyl-lysine, GlyGly, HexNAc >= 10%) and
    SILAC labels from the explained gaps (the MS Andrea idea, Buur, Winkler & Dorfer 2026, on a histogram)."""
    counts = {n: int(_num(rep, "cys", n)) for n in DELTA_CANDIDATES}
    total, zero = int(_num(rep, "cys", "spectra")), int(_num(rep, "cys", "zero_bin"))
    split = lambda v: None if v in ("none", "-", "") else v.split(" + ")
    peaks, i = [], 1
    while (("peak", f"{i}.delta")) in rep:
        alt = rep.get(("peak", f"{i}.alternatives"), "-")
        ctx = rep.get(("peak", f"{i}.context"), "-")
        peaks.append({"delta": round(_num(rep, "peak", f"{i}.delta"), 4), "spectra": int(_num(rep, "peak", f"{i}.spectra")),
                      "explained_by": split(rep.get(("peak", f"{i}.explained_by"), "none")),
                      "alternatives": [] if alt in ("-", "") else [c.split(" + ") for c in alt.split(";")],
                      **({"context": ctx} if ctx not in ("-", "") else {})})
        i += 1
    share = {k: float(v) for (sec, k), v in rep.items() if sec == "share"}
    shifted = int(_num(rep, "combo", "shifted_spectra"))
    gaps = {"placed_spectra": int(_num(rep, "combo", "placed_spectra")), "shifted_spectra": shifted,
            "peaks": peaks[:25], "share": {k: round(v, 4) for k, v in share.items()}}
    stats = {"counts": counts, "zero_bin": zero, "spectra": total}
    best = max(counts, key=counts.get)
    second = sorted(counts.values())[-2]
    if counts[best] < 10:
        ev = [Evidence("cys_alkylation", "unknown", 0.15, "data", "FASTag mass gaps",
                       f"no Cys alkylation peak in the FASTag gap histogram ({total} spectra placed)", stats)]
    else:
        ratio = (counts[best] + 1) / (second + 1)
        ev = [Evidence("cys_alkylation", best, min(0.85, 0.4 + 0.15 * ratio ** 0.5), "data", "FASTag mass gaps",
                       f"{counts[best]} placed spectra with a {DELTA_CANDIDATES[best]:+.3f} Da gap "
                       f"(next candidate {second}); searched without fixed modifications", stats)]
    if not shifted:
        return ev
    mods = [n for n, x in sorted(share.items(), key=lambda kv: -kv[1]) if x >= 0.02 and n != "Carbamidomethyl"]
    if mods:
        ev.append(Evidence("variable_mods", [x for n in mods[:max_mods_out] for x in MOD_NAMES.get(n, [n])], 0.5, "data",
                           "delta-mass combinations", "mass gaps explained as modification combinations: "
                           + ", ".join(f"{n} {share[n]:.0%}" for n in mods[:max_mods_out])
                           + f" of {shifted} spectra with a mass gap", gaps))
    # two or more SILAC labels each explaining >= 8 % of >= 500 gapped spectra (triplex PXD016465: Arg6 20 %, Lys4 18 %,
    # Lys8 8 %); label-free validation runs reach 13 % for one label at most (PXD033741, Arg10)
    seen = {v for n, v in SILAC_GAPS.items() if share.get(n, 0) >= 0.08}
    if len(seen) >= 2 and shifted >= 500:
        med, heavy = seen & {"Lys4", "Arg6"}, seen & {"Lys8", "Arg10"}
        name = "SILAC triplex (Lys4/Arg6, Lys8/Arg10)" if med and heavy else "SILAC (Lys8/Arg10)" if heavy else "SILAC (Lys4/Arg6)"
        ev.append(Evidence("label", name, 0.7, "data", "delta-mass combinations", "SILAC labels explain the mass gaps: "
                           + ", ".join(f"{n} {share[n]:.0%}" for n in SILAC_GAPS if SILAC_GAPS[n] in seen)
                           + f" of {shifted} spectra", gaps))
    for n, enr in ENRICHMENT.items():
        if share.get(n, 0) >= 0.10:
            ev.append(Evidence("enrichment", enr, min(0.7, 0.4 + share[n]), "data", "delta-mass combinations",
                               f"{n} explains {share[n]:.0%} of {shifted} spectra with a mass gap", gaps))
    return ev


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
