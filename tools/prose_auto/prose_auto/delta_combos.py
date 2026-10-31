"""Mass shifts explained as combinations of modifications (the MS Andrea idea, Buur, Winkler & Dorfer 2026,
applied to a mass-shift histogram instead of single PSMs).

The FASTag mass-gap pass (external.fastag_alkylation: tags placed on the decided proteome without fixed
modifications) yields a histogram of precursor-vs-peptide mass gaps. Each frequent gap is explained by the smallest
combination of up to three modifications from a curated Unimod set whose masses sum to it; a gap of 112.052 Da is
then two propionylations, 98.037 Da propionyl + acetyl. The modifications that explain many spectra become variable
modification evidence, and phospho, acetyl-lysine, GlyGly or HexNAc that dominate become enrichment evidence.
"""

from __future__ import annotations

import bisect
import itertools

from .evidence import Evidence

# name -> (monoisotopic mass shift, ProSE names, prior): prior 1.0 = seen in most runs, 0.5 = study-specific
MODS = {
    "Oxidation": (15.994915, ["Oxidation (M)"], 1.0),
    "Dioxidation": (31.989829, ["Dioxidation (M)"], 0.5),
    "Deamidated": (0.984016, ["Deamidated (N)", "Deamidated (Q)"], 1.0),
    "Gln->pyro-Glu": (-17.026549, ["Gln->pyro-Glu (N-term Q)"], 1.0),
    "Glu->pyro-Glu": (-18.010565, ["Glu->pyro-Glu (N-term E)"], 1.0),
    "Carbamidomethyl": (57.021464, ["Carbamidomethyl (C)"], 1.0),
    "Cation:Na": (21.981943, ["Cation:Na (DE)"], 0.7),
    "Cation:K": (37.955882, ["Cation:K (DE)"], 0.5),
    "Carbamyl": (43.005814, ["Carbamyl (N-term)"], 0.7),
    "Formyl": (27.994915, ["Formyl (N-term)"], 0.5),
    "Acetyl": (42.010565, ["Acetyl (K)", "Acetyl (N-term)"], 1.0),
    "Methyl": (14.01565, ["Methyl (K)", "Methyl (R)"], 0.7),
    "Dimethyl": (28.0313, ["Dimethyl (K)", "Dimethyl (R)"], 0.7),
    "Trimethyl": (42.04695, ["Trimethyl (K)"], 0.5),
    "Propionyl": (56.026215, ["Propionyl (K)", "Propionyl (N-term)"], 0.5),
    "Butyryl": (70.041865, ["Butyryl (K)"], 0.3),
    "Crotonyl": (68.026215, ["Crotonyl (K)"], 0.3),
    "Succinyl": (100.016044, ["Succinyl (K)"], 0.3),
    "Malonyl": (86.000394, ["Malonyl (K)"], 0.3),
    "GG": (114.042927, ["GG (K)"], 0.5),
    "Phospho": (79.966331, ["Phospho (S)", "Phospho (T)", "Phospho (Y)"], 0.7),
    "Sulfo": (79.956815, ["Sulfo (Y)"], 0.2),
    "Nitro": (44.985078, ["Nitro (Y)"], 0.3),
    "HexNAc": (203.079373, ["HexNAc (S)", "HexNAc (T)"], 0.5),
    "Hex": (162.052824, ["Hex (K)"], 0.3),
    "Cysteinyl": (119.004099, ["Cysteinyl (C)"], 0.3),
    "Methylthio": (45.987721, ["Methylthio (C)"], 0.5),
    "Propionamide": (71.037114, ["Propionamide (C)"], 0.5),
    "Nethylmaleimide": (125.047679, ["Nethylmaleimide (C)"], 0.5),
    "TMT6plex": (229.162932, ["TMT6plex (K)", "TMT6plex (N-term)"], 0.5),
    "TMTpro": (304.207146, ["TMTpro (K)", "TMTpro (N-term)"], 0.5),
    "iTRAQ4plex": (144.102063, ["iTRAQ4plex (K)", "iTRAQ4plex (N-term)"], 0.5),
    "Label:13C(6)15N(2)": (8.014199, ["Label:13C(6)15N(2) (K)"], 0.5),
    "Label:13C(6)15N(4)": (10.008269, ["Label:13C(6)15N(4) (R)"], 0.5),
    "Label:2H(4)": (4.025107, ["Label:2H(4) (K)"], 0.5),
    "Label:13C(6)": (6.020129, ["Label:13C(6) (R)"], 0.5),
    "Met-loss": (-131.040485, ["Met-loss (Protein N-term M)"], 0.7),
    "Met-loss+Acetyl": (-89.02992, ["Met-loss+Acetyl (Protein N-term M)"], 0.7),
}
ENRICHMENT = {"Phospho": "Phospho (STY)", "Acetyl": "Acetyl (K)", "GG": "GlyGly (K)", "HexNAc": "Glyco (HexNAc oxonium)"}
MAX_MODS = 3


def combinations(max_mods=MAX_MODS):
    """(mass, combination) for every multiset of up to max_mods modifications, sorted by mass"""
    names = list(MODS)
    out = []
    for k in range(1, max_mods + 1):
        for combo in itertools.combinations_with_replacement(names, k):
            out.append((sum(MODS[n][0] for n in combo), combo))
    out.sort()
    return out


_COMBOS = None


def explain(delta, tol):
    """All combinations within tol of delta, best first: fewest modifications, then the highest prior product"""
    global _COMBOS
    if _COMBOS is None:
        _COMBOS = combinations()
    masses = [m for m, _ in _COMBOS]
    i, j = bisect.bisect_left(masses, delta - tol), bisect.bisect_right(masses, delta + tol)
    hits = [c for _, c in _COMBOS[i:j]]

    def prior(c):
        p = 1.0
        for n in c:
            p *= MODS[n][2]
        return p
    return sorted(hits, key=lambda c: (len(c), -prior(c), abs(sum(MODS[n][0] for n in c) - delta)))


def detect(hist, tol, min_spectra=20, min_share=0.005, max_mods_out=5):
    """hist: [(delta, spectra, ...)] of the FASTag mass-gap histogram. Returns evidence: variable_mods (the
    modifications explaining >= 2% of the spectra with a mass gap) and enrichment (phospho, acetyl-lysine, GlyGly, HexNAc
    explaining >= 10%), with the explained peaks as stats."""
    total = sum(h[1] for h in hist)
    if not total:
        return []
    # FASTag bins are far finer than the tolerance: a peak is the sum of all unclaimed bins within tol of its top bin
    bins = sorted((h[0], h[1]) for h in hist)
    deltas = [b[0] for b in bins]
    claimed = [False] * len(bins)
    peaks = []
    for i in sorted(range(len(bins)), key=lambda i: -bins[i][1]):
        if claimed[i] or abs(bins[i][0]) <= tol:
            continue
        d = bins[i][0]
        lo, hi = bisect.bisect_left(deltas, d - tol), bisect.bisect_right(deltas, d + tol)
        near = [j for j in range(lo, hi) if not claimed[j]]
        for j in near:
            claimed[j] = True
        n = sum(bins[j][1] for j in near)
        d = sum(bins[j][0] * bins[j][1] for j in near) / n
        if n < max(min_spectra, min_share * total) or abs(d) <= 2 * tol:   # calibration offsets are not modifications
            continue
        ex = explain(d, tol)
        peaks.append({"delta": round(d, 4), "spectra": n, "explained_by": list(ex[0]) if ex else None,
                      "alternatives": [list(c) for c in ex[1:8]]})
    # isobaric combinations (acetyl + butyryl = 2 x propionyl, C6H8O2): prefer the one whose members the run also
    # shows alone, i.e. as single-modification peaks
    alone = {}
    for p in peaks:
        if p["explained_by"] and len(p["explained_by"]) == 1:
            alone[p["explained_by"][0]] = alone.get(p["explained_by"][0], 0) + p["spectra"]
    for p in peaks:
        ex = [p["explained_by"]] + p["alternatives"] if p["explained_by"] else []
        if len(ex) > 1 and len(ex[0]) > 1:
            k = len(ex[0])
            same = [c for c in ex if len(c) == k]
            score = lambda c: min(alone.get(n, 0) for n in c)
            best = max(same, key=score)
            if score(best) > score(ex[0]):
                p["alternatives"] = [c for c in ex if c != best][:3]
                p["explained_by"] = best
                p["context"] = "members seen as single-modification peaks"
    # three modifications explain almost any gap; trust one only when each member is also a single-modification peak
    for p in peaks:
        if p["explained_by"] and len(p["explained_by"]) == 3 and not all(n in alone for n in p["explained_by"]):
            p["alternatives"] = [p["explained_by"]] + p["alternatives"][:2]
            p["explained_by"] = None
    # shares among the shifted spectra: in most runs the zero-gap bin holds most placements and would dilute them
    shifted = sum(h[1] for h in hist if abs(h[0]) > 2 * tol) or 1
    share = {}
    for p in peaks:
        for name in p["explained_by"] or []:
            share[name] = share.get(name, 0) + p["spectra"] / shifted
    stats = {"placed_spectra": total, "shifted_spectra": shifted, "peaks": peaks[:25],
             "share": {k: round(v, 4) for k, v in share.items()}}
    ev = []
    mods = [n for n, s in sorted(share.items(), key=lambda x: -x[1]) if s >= 0.02 and n != "Carbamidomethyl"]
    if mods:
        names = [x for n in mods[:max_mods_out] for x in MODS[n][1]]
        ev.append(Evidence("variable_mods", names, 0.5, "data", "delta-mass combinations",
                           "mass gaps explained as modification combinations: "
                           + ", ".join(f"{n} {share[n]:.0%}" for n in mods[:max_mods_out])
                           + f" of {shifted} spectra with a mass gap", stats))
    for n, enr in ENRICHMENT.items():
        if share.get(n, 0) >= 0.10:
            ev.append(Evidence("enrichment", enr, min(0.7, 0.4 + share[n]), "data", "delta-mass combinations",
                               f"{n} explains {share[n]:.0%} of {shifted} spectra with a mass gap", stats))
    return ev
