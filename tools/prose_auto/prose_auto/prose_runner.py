"""Optional confirmation with ProSE itself on a subset of the spectra.

Two runs, both on the top-TIC MS2 subset:

1. closed search with the proposed settings and the calibration pass on;
   ProSE's -summary_out YAML reports per file the precursor and fragment
   error (median, MAD, recommended ppm) and the PSM/peptide/protein counts;
2. optional open search (precursor window of +-500 Da turns ProSE's open
   mode on) with -out_mod_analysis_dir; the delta-mass tables show the mass
   shifts that the closed search is missing (a Cys alkylation that is not
   set, labels, frequent variable modifications).

This needs a ProSE binary (OpenMS build or installer); the Python
mini-search in hypotheses.py covers the same questions when there is none.
"""

from __future__ import annotations

import csv
import glob
import os
import shutil
import subprocess
import tempfile

from .evidence import Evidence
from .spectra import write_subset_mzml


def find_prose(path=None):
    return path or shutil.which("ProSE")


def _run(cmd, log):
    log("  $ " + " ".join(cmd[:6]) + (" ..." if len(cmd) > 6 else ""))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2000:] or r.stdout[-2000:])
    return r


def confirm_with_prose(prose, mzml, fasta, cli_args, n_spectra=5000, open_search=False, log=print):
    import yaml
    ev = []
    with tempfile.TemporaryDirectory(prefix="prose_auto_") as tmp:
        sub = os.path.join(tmp, "subset.mzML")
        n = write_subset_mzml(mzml, sub, n_spectra)
        summ = os.path.join(tmp, "summary.yaml")
        args = [a for a in cli_args]
        # make sure the calibration pass runs and reports the errors
        if "-Search:calibration:enabled" in args:
            i = args.index("-Search:calibration:enabled")
            args[i + 1] = "true"
        else:
            args += ["-Search:calibration:enabled", "true"]
        _run([prose, "-in", sub, "-database", fasta, "-out", os.path.join(tmp, "out.idXML"),
              "-summary_out", summ, "-no_summary"] + args, log)
        with open(summ) as fh:
            s = yaml.safe_load(fh)
        pf = (s.get("per_file") or [{}])[0]
        stats = {k: pf.get(k) for k in ("ms2_spectra", "target_psms", "unique_peptides", "unique_proteins",
                                         "achieved_psm_fdr")}
        frac = (pf.get("target_psms") or 0) / max(1, n)
        ev.append(Evidence("organism", os.path.basename(fasta), min(0.9, 0.3 + frac), "search", "ProSE subset search",
                           f"ProSE identified {pf.get('target_psms')} of {n} subset spectra "
                           f"({frac:.0%}) against {os.path.basename(fasta)}", stats))
        for kind in ("precursor", "fragment"):
            e = pf.get(f"{kind}_error") or {}
            if e.get("valid"):
                ev.append(Evidence(f"{kind}_offset", {"value": e["median_ppm"], "unit": "ppm"}, 0.9, "search",
                                   "ProSE calibration", f"ProSE {kind} error median {e['median_ppm']} ppm, "
                                   f"MAD {e['mad_ppm']} ppm"))
                ev.append(Evidence(f"{kind}_tolerance", {"value": e["recommended_ppm"], "unit": "ppm"}, 0.9,
                                   "search", "ProSE calibration",
                                   f"ProSE recommends {e['recommended_ppm']} ppm from its calibration PSMs"))
        if open_search:
            mods = os.path.join(tmp, "mods")
            os.makedirs(mods)
            oargs = [a for a in args]
            for key, val in (("-Search:precursor:mass_tolerance_lower", "500"),
                             ("-Search:precursor:mass_tolerance_upper", "500"),
                             ("-Search:precursor:mass_tolerance_unit", "Da"),
                             ("-Search:calibration:enabled", "false")):
                if key in oargs:
                    oargs[oargs.index(key) + 1] = val
                else:
                    oargs += [key, val]
            _run([prose, "-in", sub, "-database", fasta, "-out", os.path.join(tmp, "open.idXML"),
                  "-out_mod_analysis_dir", mods, "-no_summary"] + oargs, log)
            shifts = []
            for f in glob.glob(os.path.join(mods, "*")):
                if "aggregate" in os.path.basename(f).lower() or len(glob.glob(os.path.join(mods, "*"))) == 1:
                    with open(f) as fh:
                        rows = list(csv.DictReader(fh, delimiter="\t"))
                    shifts.extend(rows[:15])
            if shifts:
                ev.append(Evidence("variable_mods", [r for r in shifts], 0.5, "search", "ProSE open search",
                                   "most frequent mass shifts of the open search (see the table)"))
    return ev


PHOSPHO = ["Phospho (S)", "Phospho (T)", "Phospho (Y)"]
SILAC_HEAVY = ["Label:13C(6)15N(2) (K)", "Label:13C(6)15N(4) (R)"]


def load_signatures(path):
    """signatures.tsv.gz of build_sigpanel.py: peptide (I->L) -> species name or genus:<Genus>"""
    import gzip
    with gzip.open(path, "rt") as fh:
        return dict(line.rstrip("\n").split("\t") for line in fh)


def _species_counts(idxml, signatures=None):
    """PSMs at the FDR cut per species: discriminating and all; contaminant hits (accession prefix CRAP) are counted
    apart. Discriminating: the peptide is in one candidate species only, or, with signatures (a signature-protein
    panel), it is a signature of that species in the whole reference set; a genus signature counts for every species
    of the genus that matched (the species signatures then decide between them). Also returned: the share of the
    PSMs that are fully tryptic (K/R before and at the C-terminus, or a protein terminus), which tells tryptic
    peptides found by an unspecific search from HLA ligands."""
    import pyopenms as oms
    from collections import Counter
    prots, peps = [], oms.PeptideIdentificationList()   # pyopenms 3.5 (Python 3.10) rejects a plain list
    oms.IdXMLFile().load(idxml, prots, peps)
    disc, allm, crap, n, tryp = Counter(), Counter(), 0, 0, 0
    for pid in peps:
        hits = pid.getHits()
        if not hits or hits[0].getMetaValue("target_decoy") == "decoy":
            continue
        n += 1
        sp = {ev.getProteinAccession().split("|")[0] for ev in hits[0].getPeptideEvidences()}
        if "CRAP" in sp:
            crap += 1
            continue
        allm.update(sp)
        pe, seq = hits[0].getPeptideEvidences(), hits[0].getSequence().toUnmodifiedString()
        tryp += (any(e.getAABefore() in "KR[" for e in pe)
                 and (seq[-1] in "KR" or any(e.getAAAfter() == "]" for e in pe)))
        if signatures is not None:
            lab = signatures.get(hits[0].getSequence().toUnmodifiedString().replace("I", "L"))
            if lab and lab.startswith("genus:"):
                for x in sp:
                    if x.split("_")[0] == lab[6:]:
                        disc[x] += 1
            elif lab in sp:
                disc[lab] += 1
        elif len(sp) == 1:
            disc[next(iter(sp))] += 1
    return n, disc, allm, crap, tryp / max(n - crap, 1)


HLA_CANDIDATES = {(8, 14): 4, (12, 25): 2}   # unspecific indexes of all panel proteomes are too large


def organism_with_prose(prose, spectra, candidates, fixed, variable, prec, frag, contaminants=None, threads=0,
                        min_psms=10, hla_first=False, preferred=(), panel_db=None, signatures=None, log=print):
    """One ProSE search against all candidate proteomes (concatenated, accessions prefixed with the species) plus
    contaminants. The winner has the most PSMs on peptides no other candidate has: shared peptides (36% of the
    human tryptic peptides are also mouse peptides) and contaminants (keratin) do not count. No winner: search again
    with variable phospho, then with variable SILAC heavy Lys/Arg, then unspecific HLA class I ligands (8-14), the
    chemistry the panel mini-search cannot express (phospho, SILAC and HLA runs gave it 0-17 PSMs of 2000).
    then HLA class II ligands (12-25). hla_first: "I"/"II" (or True = I): the data or the texts suggest HLA ligands of that class, so
    that search goes first (the tryptic steps follow if it finds nothing). Unspecific searches use the HLA_CANDIDATES best
    candidates (preferred first, then by matches so far, then the panel order).
    The step that found the winner is returned as evidence too (enrichment, label, enzyme and length).
    panel_db/signatures: a signature-protein panel (build_sigpanel.py) is searched instead of the concatenated
    candidates in the tryptic steps; candidates then maps every panel species to its full proteome (unspecific steps).
    Returns (evidence, winner name or None). prec/frag: (value, unit)."""
    from collections import Counter
    from .hypotheses import _margin_conf
    ev = []
    with tempfile.TemporaryDirectory(prefix="prose_auto_org_") as tmp:
        def write_db(names, path):
            with open(path, "w") as fh:
                for name in list(names) + (["CRAP"] if contaminants else []):
                    for line in open(contaminants if name == "CRAP" else candidates[name]):
                        fh.write(f">{name}|{line[1:]}" if line.startswith(">") else line)
            return path

        db = write_db({} if panel_db else candidates, os.path.join(tmp, "candidates.fasta"))
        if panel_db:  # the panel's accessions already carry the species prefix; contaminants appended
            with open(db, "a") as fh:
                fh.write(open(panel_db).read())
        tryptic = [("as decided", [], None)]
        if not any(m in variable for m in PHOSPHO):
            tryptic.append(("+ variable phospho", PHOSPHO, None))
        if not any(m in variable for m in SILAC_HEAVY):
            tryptic.append(("+ variable SILAC heavy", SILAC_HEAVY, None))
        hla1, hla2 = ("HLA class I ligands (unspecific)", [], (8, 14)), ("HLA class II ligands (unspecific)", [], (12, 25))
        steps = ([hla2] + tryptic + [hla1] if hla_first == "II" else [hla1] + tryptic + [hla2] if hla_first
                 else tryptic + [hla1, hla2])
        added, tried, seen = [], {}, Counter()

        def step(label, extra, length):
            out = os.path.join(tmp, "org.idXML")
            dbi = db
            if length:
                order = [c for c in preferred if c in candidates] + [c for c, _ in seen.most_common()
                                                                     if c in candidates] + list(candidates)
                names = list(dict.fromkeys(order))[:HLA_CANDIDATES[length]]
                dbi = write_db({n: candidates[n] for n in names}, os.path.join(tmp, "hla.fasta"))
            extra_now = [] if length else added
            args = [prose, "-in", spectra, "-database", dbi, "-out_idxml", out, "-no_summary",
                    "-Search:enzyme", "unspecific cleavage" if length else "Trypsin/P", "-Search:decoys", "generate",
                    "-Search:FDR:PSM", "0.01",
                    "-Search:precursor:mass_tolerance_lower", str(prec[0]),
                    "-Search:precursor:mass_tolerance_upper", str(prec[0]),
                    "-Search:precursor:mass_tolerance_unit", prec[1],
                    "-Search:fragment:mass_tolerance", str(frag[0]), "-Search:fragment:mass_tolerance_unit", frag[1],
                    "-Search:modifications:fixed", *fixed, "-Search:modifications:variable", *variable,
                    *extra_now]
            if length:
                args += ["-Search:peptide:min_size", str(length[0]), "-Search:peptide:max_size", str(length[1])]
            if threads:
                args += ["-threads", str(threads)]
            _run(args, log)
            n, disc, allm, crap, tryp = _species_counts(out, None if length else signatures)
            seen.update(allm)
            ranked = disc.most_common()
            tried[label] = {"psms": n, "contaminant_psms": crap, "fully_tryptic": round(tryp, 2),
                            "discriminating": dict(ranked[:6]),
                            "all_matching": dict(allm.most_common(6))}
            log(f"  organism (ProSE, {label}): {n} PSMs ({tryp:.0%} fully tryptic), discriminating {dict(ranked[:4])}")
            return ranked, tryp

        for label, extra, length in steps:
            added += extra
            ranked, tryp = step(label, extra, length)
            if ranked and ranked[0][1] >= min_psms:
                break
        # an unspecific search finds tryptic peptides too (four tryptic validation runs, three of them timsTOF with few
        # K/R tag ends, were called "unspecific cleavage" after an HLA-first search): mostly fully tryptic PSMs mean a
        # tryptic digest, and the organism then comes from the tryptic search (the signature panel) when it finds one
        if length and ranked and ranked[0][1] >= min_psms and tryp >= 0.5:
            log(f"  {tryp:.0%} of the unspecific PSMs are fully tryptic: tryptic digest, not HLA ligands")
            length = None
            if not any(t[0] in tried for t in tryptic):
                t_ranked, _ = step(*tryptic[0])
                if t_ranked and t_ranked[0][1] >= min_psms:
                    label, ranked = tryptic[0][0], t_ranked
    stats = {"steps": tried, "candidates": list(candidates)}
    if not ranked or ranked[0][1] < min_psms:
        ev.append(Evidence("organism", "not in panel", 0.5, "search", "ProSE organism search",
                           f"no candidate proteome has {min_psms} discriminating PSMs at 1% FDR "
                           f"({', '.join(tried)})", stats))
        return ev, None
    (best, top), second = ranked[0], (ranked[1][1] if len(ranked) > 1 else 0)
    ev.append(Evidence("organism", best, _margin_conf(top, second), "search", "ProSE organism search",
                       f"{best}: {top} PSMs on peptides no other candidate has; next "
                       + (f"{ranked[1][0]} with {second}" if second else "none") + f" ({label})", stats))
    for k, u in ranked[1:]:
        if u >= max(min_psms, 0.2 * top):  # a second organism with many discriminating PSMs: mixed sample
            ev.append(Evidence("organism", f"{best} + {k}", 0.5, "search", "ProSE organism search",
                               f"{k} has {u} discriminating PSMs ({best}: {top}): mixed sample, spike-ins or "
                               "xenograft?", stats))
    # what the winning step says about the chemistry (only what the first search did not have)
    why = f"the ProSE organism search found {top} discriminating PSMs only with: {label}"
    if label == "+ variable phospho":
        ev.append(Evidence("enrichment", "Phospho (STY)", 0.6, "search", "ProSE organism search", why))
    elif label == "+ variable SILAC heavy":
        ev.append(Evidence("label", "SILAC (Lys8/Arg10)", 0.6, "search", "ProSE organism search", why))
    elif length:
        ev.append(Evidence("enzyme", "unspecific cleavage", 0.7, "search", "ProSE organism search", why))
        ev.append(Evidence("peptide_length", list(length), 0.7, "search", "ProSE organism search", why))
    return ev, best
