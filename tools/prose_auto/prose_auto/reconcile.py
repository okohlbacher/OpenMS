"""Turn all evidence into one decision per parameter.

Policy
------
* Parameters the instrument and the spectra determine (tolerances, offsets,
  acquisition, analyzers, fragmentation, labels): measurements win
  (search > data > metadata), then repository, user, text, llm, default.
* Sample-preparation parameters (organism, protease, Cys alkylation,
  enrichment): a clear mini-search result wins; otherwise the user's own
  description, then the repository record, then methods text, then the LLM,
  then weak diagnostic-ion evidence, then the default.
* Independent sources that agree raise the confidence
  (1 - prod(1 - c_i)); a disagreeing source with confidence >= 0.4 is a
  conflict, and a conflict between a measurement and what the user or the
  repository says puts the parameter on 'review'.
* Tolerances combine: |offset| + 4 sigma from a mini-search when there is
  one; otherwise the data precision plus a measured offset; otherwise the
  instrument default, flagged for review and for ProSE's calibration pass.
"""

from __future__ import annotations

import re

import math

from .detect_instrument import classify_instrument
from .external import REAGENT_GENERA
from . import taxa
from .evidence import Decision, Evidence

MEASURED = {"precursor_tolerance", "fragment_tolerance", "precursor_offset", "fragment_offset",
            "acquisition", "dia_windows", "ms1_analyzer", "ms2_analyzer", "fragmentation",
            "collision_energy", "ion_mobility", "charge_range", "instrument", "instrument_class", "label"}
ORDER_MEASURED = ["search", "data", "metadata", "repository", "user", "text", "llm", "default"]
ORDER_SAMPLE = ["user", "repository", "text", "llm", "search", "data", "metadata", "default"]

NEGATIVE = {"no isobaric label", "no SILAC", "none", "unknown", "label free"}


def _same(a, b):
    if isinstance(a, dict) and isinstance(b, dict) and "value" in a and "value" in b:
        if a.get("unit", "").lower() != b.get("unit", "").lower():
            return False
        x, y = abs(float(a["value"])), abs(float(b["value"]))
        return max(x, y) <= 2.0 * max(min(x, y), 1e-9) or abs(x - y) <= 2.0
    na, nb = str(a).lower(), str(b).lower()
    if na == nb:
        return True
    # loose matches: 'TMT10/11plex' vs 'TMT', 'Orbitrap Fusion' vs 'Orbitrap Fusion ETD',
    # 'Escherichia coli K-12' vs 'Escherichia coli', 'DIA (diaPASEF)' vs 'DIA'
    return na.split(" (")[0] in nb or nb.split(" (")[0] in na or \
        (na[:3] == nb[:3] and na[:3] in ("tmt", "itr", "sil", "dia", "dda"))


def _organism_key(v):
    return taxa.key(v)


def _stated_untested(d, evs):
    """A search can only pick among the databases it searched. When the user or a repository states an organism of
    another genus that no search tested (outside the panel, proteome fetch failed or DIA without a search), the
    nearest panel organism winning says nothing against it: the stated organism wins, flagged for review."""
    if d.source != "search":
        return d
    g = lambda v: str(v).replace("_", " ").split(" ")[0].lower()
    searched = {g(k) for e in evs if e.source == "search" for k in (e.stats or {})}
    stated = [e for e in evs if e.source in ("user", "repository") and e.confidence >= 0.5
              and g(e.value) != g(d.value) and g(e.value) not in searched]
    if not stated:
        return d
    s = max(stated, key=lambda e: e.confidence)
    note = f"the mini-search prefers {d.value}, but {s.source} states {s.value}, which no searched database covers"
    return Decision("organism", s.value, round(s.confidence * 0.9, 3), s.source, evs, d.conflicts + [note], "review")


MIN_DB_SHARE = 0.1   # of the largest searched database's peptides, for a search to test a species


def _search_psms(evs):
    """(PSMs per organism key, spectra searched, winner key) of the last panel mini-search, or None"""
    search = [e for e in evs if e.source == "search" and e.method == "panel mini-search" and e.stats
              and " + " not in str(e.value)]
    if not search:
        return None
    st = search[-1].stats
    # a database far smaller than the largest searched is no test of its species (PXD066108: a 167-peptide
    # Macaca mulatta proteome beside 2.5 million human peptides)
    top = max((v.get("peptides") or 0 for v in st.values() if isinstance(v, dict)), default=0)
    psms = {_organism_key(k): v.get("psms", 0) for k, v in st.items()
            if isinstance(v, dict) and not (v.get("peptides") and v["peptides"] < MIN_DB_SHARE * top)}
    return psms, st.get("n_spectra") or 0, max(psms, key=psms.get) if psms else None


def _absent(psms, n, k):
    return k in psms and psms[k] < max(10, 0.01 * n)


def _absent_pick(d, evs):
    """A record that names several species picks the first at equal confidence (PXD028735: "Candida albicans (yeast)"
    for a human-yeast-E. coli benchmark, decided for a pure human file). When the search tested the pick and it
    explains under max(10, 1%) of the spectra while another named species explains more, that species wins."""
    if d.source not in ("user", "repository", "text", "llm"):
        return d
    got = _search_psms(evs)
    if not got:
        return d
    psms, n, best = got
    named = {_organism_key(e.value) for e in evs if e.source in ("user", "repository", "text", "llm")}
    if not (best and best in named and _absent(psms, n, _organism_key(d.value)) and not _absent(psms, n, best)):
        return d
    w = max((e for e in evs if e.source in ("user", "repository", "text", "llm") and _organism_key(e.value) == best),
            key=lambda e: e.confidence)
    note = (f"{d.source} picks {d.value}, which the mini-search tested: {psms[_organism_key(d.value)]} of {n} spectra; "
            f"{w.value}, also named, explains {psms[best]}")
    return Decision("organism", w.value, round(w.confidence * 0.9, 3), w.source, evs, d.conflicts + [note], "review")


MIN_RULE_SHARE = 0.05   # of the mini-search spectra the data species must explain before it overrules the record


def _untested_pick(d, evs):
    """Records and texts often name several species (host and sample, spike-in standards, the organism of an antibody).
    The decisive mini-search tests the FASTag shortlist (the data's top species). When the metadata pick is not on
    that shortlist, the mini-search finds another of the named species best, and FASTag calls that species too, the
    data choose among the named species. A pick on the shortlist keeps its place: close relatives (mouse/human) can
    lose a head-to-head on homology alone."""
    if d.source not in ("user", "repository", "text", "llm"):
        return d
    search = [e for e in evs if e.source == "search" and e.method == "panel mini-search" and e.stats]
    if not search:
        return d
    psms = {_organism_key(k): v.get("psms", 0) for k, v in search[0].stats.items() if isinstance(v, dict)}
    best = max(psms, key=psms.get) if psms else None
    # tier 2 searches the stated organisms too; one searched only for being stated is not on the data shortlist
    # (PXD043814: PRIDE says human, the rat SMCs explain 343 spectra, human 232)
    off = {_organism_key(k) for k in search[0].stats.get("stated_added", [])}
    named = {_organism_key(e.value) for e in evs if e.source in ("user", "repository", "text", "llm")}
    fastag = [e for e in evs if e.method == "FASTag species" and e.confidence >= 0.5]
    if (not best or best == _organism_key(d.value) or _organism_key(d.value) in psms.keys() - off or best not in named
            or not fastag or _organism_key(fastag[0].value) != best):
        return d
    # a weak search result is no reason to overrule the record: the antibody of an IP (mouse IgG in human cells,
    # PXD050844: 75 of 2000 spectra) is named in the texts too. The rule was right from 7 % on (PXD031090)
    m = re.search(r"of (\d+) spectra", search[0].detail or "")
    n = search[0].stats.get("n_spectra") or (int(m.group(1)) if m else 0)
    if n and psms[best] < MIN_RULE_SHARE * n:
        return d
    note = (f"{d.source} picks {d.value}, which is not among the species the data shortlist; of the species the "
            f"records and texts name, the mini-search finds {search[0].value} best ({psms[best]} PSMs) and FASTag agrees")
    conf, _ = _combine(search[0], evs)
    return Decision("organism", search[0].value, round(conf * 0.85, 3), "search", evs, d.conflicts + [note], "review")


MEASURED_SOURCES = ("data", "metadata", "search")


def _echo(a: Evidence, b: Evidence):
    """a reader that saw the measured data (Jev "+data") and a measurement are no independent witnesses"""
    return (a.method.endswith("+data") and b.source in MEASURED_SOURCES) or \
        (b.method.endswith("+data") and a.source in MEASURED_SOURCES)


def _combine(winner: Evidence, evs: list):
    agree = [e for e in evs if e is not winner and _same(e.value, winner.value) and e.source != winner.source
             and not _echo(e, winner)]
    p = 1 - winner.confidence
    for e in agree:
        p *= 1 - 0.5 * e.confidence   # agreement counts half: sources are not fully independent
    return min(0.99, 1 - p), agree


def _pick(evs, order, strong_first=None):
    if strong_first:
        strong = [e for e in evs if e.source == strong_first and e.confidence >= 0.7
                  and str(e.value) not in NEGATIVE]
        if strong:
            return max(strong, key=lambda e: e.confidence)
    for src in order:
        c = [e for e in evs if e.source == src]
        if c:
            return max(c, key=lambda e: e.confidence)
    return None


def _decide(param, evs, order=None, pool=None):
    """pool: the evidence the winner may come from (default all); conflicts and agreement count all of evs."""
    measured = order is ORDER_MEASURED or param in MEASURED
    order = order or (ORDER_MEASURED if measured else ORDER_SAMPLE)
    w = _pick(evs if pool is None else pool, order, strong_first=None if measured else "search")
    if w is None:
        return None
    conf, agree = _combine(w, evs)
    conflicts = []
    for e in evs:
        if e is w or e.confidence < 0.4 or _same(e.value, w.value):
            continue
        if param == "organism" and _organism_key(e.value) == _organism_key(w.value):
            continue
        conflicts.append(f"{e.source} ({e.method}) says {e.value}: {e.detail}")
        conf *= 0.85
    status = "auto" if conf >= 0.7 and not conflicts else ("default" if w.source == "default" else "review")
    if conflicts and any(e.source in ("user", "repository") for e in evs if not _same(e.value, w.value)) \
            and w.source in ("data", "search", "metadata"):
        status = "review"
    return Decision(param, w.value, round(conf, 3), w.source, evs, conflicts, status)


def _variable_mods(evs):
    """Lists from different sources complement each other (the delta-mass histogram, the SDRF, Jev's flags): the
    union of the modifications a source names with confidence >= 0.5, most supported first. As one winning list, a second list counted as a conflict and dropped both below the
    threshold of the search settings."""
    strong = [e for e in evs if e.confidence >= 0.5 and isinstance(e.value, list)]
    if not strong:
        return _decide("variable_mods", evs)
    measured = {m for e in strong if e.source in MEASURED_SOURCES for m in e.value}
    score = {}
    for e in strong:
        echo = e.method.endswith("+data")
        for m in e.value:
            if isinstance(m, str) and not (echo and m in measured):   # Jev repeating a measurement adds nothing
                score[m] = score.get(m, 0.0) + e.confidence
    if not score:
        return _decide("variable_mods", evs)
    w = max(strong, key=lambda e: e.confidence)
    sources = {e.source for e in strong if not e.method.endswith("+data")} or {w.source}
    conf = min(0.9, w.confidence + 0.1 * (len(sources) - 1))
    return Decision("variable_mods", sorted(score, key=lambda m: -score[m]), round(conf, 3),
                    w.source, evs, [], "auto" if conf >= 0.7 else "review")


def _label(evs):
    pos = [e for e in evs if str(e.value) not in NEGATIVE]
    measured_neg = [e for e in evs if str(e.value) in ("no isobaric label",) and e.source == "data"]
    silac_neg = [e for e in evs if str(e.value) == "no SILAC" and e.source == "data"]
    data_pos = [e for e in pos if e.source == "data" and e.confidence >= 0.6]
    if data_pos:
        d = _decide("label", [e for e in evs if e in data_pos or e.source != "data"])
        d.value = max(data_pos, key=lambda e: e.confidence).value
        d.evidence = evs
        return d
    if measured_neg and silac_neg and not [e for e in pos if e.source in ("user", "repository") and "silac" in str(e.value).lower()]:
        lf = Evidence("label", "label free", min(measured_neg[0].confidence, 0.9), "data", "reporter ions + MS1 pairs",
                      "no reporter ions and no heavy/light MS1 pairs")
        d = _decide("label", [lf] + [e for e in evs if e.source != "data"])
        d.evidence = evs + [lf]
        return d
    return _decide("label", evs)


def _tolerance(kind, evs, offsets, instrument, ms_analyzer):
    """kind: precursor | fragment"""
    param = f"{kind}_tolerance"
    search = [e for e in evs if e.source == "search"]
    if search:
        d = _decide(param, evs)
        return d
    data = [e for e in evs if e.source == "data"]
    info = classify_instrument(instrument or "")
    if kind == "precursor":
        dflt = {"value": info[2] if info else 10.0, "unit": "ppm"}
    else:
        lowres = ms_analyzer in ("IT", "LIT", "PAULIONTRAP")
        dflt = {"value": 0.5, "unit": "Da"} if lowres else {"value": info[3] if info and info[4] == "ppm" else 20.0, "unit": "ppm"}
    default = Evidence(param, dflt, 0.4, "default", "instrument class",
                       f"default for {info[0] if info else 'an unknown instrument'}"
                       + (" with ion-trap MS2" if kind == "fragment" and dflt["unit"] == "Da" else ""))
    if not data:
        d = _decide(param, evs + [default])
        d.evidence = evs + [default]
        if d.source in ("default", "llm"):
            d.status = "review"
            d.conflicts.append("not measured: enable ProSE calibration (Search:calibration:enabled) "
                               "or run the mini-search with a FASTA")
        return d
    best = max(data, key=lambda e: e.confidence)
    v = dict(best.value)
    off = [e for e in offsets if e.source in ("data", "search")]
    if off:
        o = max(off, key=lambda e: e.confidence)
        if o.value.get("unit") == v.get("unit"):
            v["value"] = round(v["value"] + abs(o.value["value"]), 3)
        note = f"precision from {best.method} plus the {o.method} offset {o.value['value']:+} {o.value['unit']}"
        conf = min(best.confidence, o.confidence) + 0.1
    else:
        # precision only: never go below the instrument default, the offset is unknown
        if v.get("unit") == dflt["unit"]:
            v["value"] = max(v["value"], dflt["value"])
        note = f"precision from {best.method}; offset unknown, kept at least at the instrument default"
        conf = best.confidence * 0.8
    comb = Evidence(param, v, conf, "data", "combined", note)
    # the combined value is the decision; the raw precision estimates are its inputs
    conflicts = [f"{e.source} ({e.method}) says {e.value}: {e.detail}" for e in evs
                 if e.source in ("repository", "user", "text") and e.confidence >= 0.4 and not _same(e.value, v)]
    status = "auto" if off and conf >= 0.7 and not conflicts else "review"
    if not off:
        conflicts.append("systematic offset not measured: ProSE's calibration pass is recommended")
    return Decision(param, v, round(min(conf, 0.99), 3), "data", evs + [default, comb], conflicts, status)


ENRICH_SEP = " + "
STRONG_ENRICHMENT = 0.7   # one diagnostic-ion signal this strong decides alone (neutral loss >= 5 % at a clean control)


def _enrichment(evs):
    """No single indicator decides an enrichment. The indicators: diagnostic ions (neutral loss, oxonium,
    immonium), mass gaps (delta-mass combinations), the ProSE organism search, keywords in the texts, Jev. An
    enrichment needs a strong diagnostic-ion signal or two independent indicators, Jev counting only next to a
    text keyword or a second measurement (it read the measured profile). Where the spectra tested it and found
    nothing (high-resolution DDA), the texts alone do not overrule them: project texts mention phospho for the
    total-proteome runs of a phospho study. A stated enrichment (user, repository) decides as before.
    Single-indicator calls this stops: one keyword on DIA (3 runs), Jev alone (PXD076863), a GlyGly mass gap alone
    (114.043 Da is also an Asn residue, PXD027767)."""
    if any(e.source in ("user", "repository") and e.confidence >= 0.5 for e in evs):
        return _decide("enrichment", evs)
    fam = lambda v: str(v).split()[0].lower()
    pos = [e for e in evs if str(e.value) not in NEGATIVE and e.source != "default" and e.confidence >= 0.3]
    kinds = {}
    for e in pos:
        kinds.setdefault(fam(e.value), set()).add(e.method if e.source in MEASURED_SOURCES else e.source)
    tested_none = any(e.source == "data" and str(e.value) == "none" and e.confidence >= 0.6 for e in evs)

    def supported(f):
        k = kinds[f]
        measured = k - {"text", "llm"}
        if any(e.method == "diagnostic ions" and e.confidence >= STRONG_ENRICHMENT for e in pos if fam(e.value) == f):
            return True
        n = len(k) - ("llm" in k and "text" not in k and len(measured) < 2)   # Jev echoing one measurement
        return n >= 2 and (measured or not tested_none)

    keep = {f for f in kinds if supported(f)}
    sub = [e for e in evs if fam(e.value) in keep] or [e for e in evs if str(e.value) in NEGATIVE]
    if not sub:
        return None
    d = _decide("enrichment", sub, ORDER_MEASURED if any(e.source in MEASURED_SOURCES for e in sub) else None)
    for e in evs:
        if e not in sub and e.confidence >= 0.4 and not _same(e.value, d.value):
            d.conflicts.append(f"{e.source} ({e.method}) says {e.value}: {e.detail}"
                               + ("" if keep else " (one indicator alone does not decide)"))
            d.confidence = round(d.confidence * 0.85, 3)
            d.status = "review"
    d.evidence = evs
    return d


def _co_enrichment(d, evs):
    """TiO2 also takes sialylated glycopeptides (PXD003531: phospho neutral loss 10.7 %, HexNAc oxonium 59 %): every
    other enrichment the spectra show strongly (data, >= 0.8, another family) joins the decision as 'A + B'"""
    if d.value in ("none", "unknown"):
        return d
    fam = lambda v: str(v).split()[0].lower()
    vals = [d.value]
    for e in sorted(evs, key=lambda e: -e.confidence):
        if (e.source == "data" and e.confidence >= 0.8 and e.value not in ("none", "unknown")
                and fam(e.value) not in {fam(v) for v in vals}):
            vals.append(e.value)
    if len(vals) == 1:
        return d
    d.value = ENRICH_SEP.join(vals)
    # evidence for a joined part agrees with the decision: drop it from the conflicts and undo their penalty
    keep = [c for c in d.conflicts if not any(f" says {v}:" in c for v in vals)]
    d.confidence = round(min(0.99, d.confidence / 0.85 ** (len(d.conflicts) - len(keep))), 3)
    d.conflicts = keep
    if not keep and d.confidence >= 0.7:
        d.status = "auto"
    return d


JEV_ENZYME_P = 0.8
KR_FAMILY = ("Trypsin", "Trypsin/P", "Lys-C", "Arg-C")
TAG_MARGIN = 0.15   # tag-profile margin (log-likelihood per tag) from which the tag call takes part in the decision


def _enzyme(evs):
    """The protease. What the user or a repository record states comes first. Then the tag-profile call (FASTag
    termini under published cleavage specificities, high-res MS2, margin >= TAG_MARGIN: 17/17 tryptic, 12/12 HLA)
    and a Jev answer with p >= 0.8 (17 of 18 non-tryptic digests), the more confident one; the tag margin is its
    confidence. Keyword text names the first protease it finds (the first of six in a protease comparison, "no
    enzyme" of a control) and decides only without them, as does the ProSE organism search (HLA-first). No protease
    competition: the Trypsin rule covers Lys-C and Arg-C peptides, and it lost to the tags on tryptic and HLA runs."""
    first = [e for e in evs if e.source in ("user", "repository")]
    tag = [e for e in evs if e.method == "FASTag termini" and (e.stats or {}).get("tag_margin", 0) >= TAG_MARGIN]
    jev = [e for e in evs if e.source == "llm" and e.method.endswith("+data")
           and (e.stats or {}).get("p", 0) >= JEV_ENZYME_P]
    if not first and (tag or jev):
        w = max(tag + jev, key=lambda e: e.confidence)
        # within the K/R family the tags only tell the family: labels, the scan range and the Trypsin rule's
        # missed cleavages bias the K/R split (tryptic Astral and TMTpro runs read Arg-C or Lys-C), so a Jev answer
        # naming a family member picks the member (keywords do not: "tryptic" in a protease comparison)
        if w in tag and w.value in KR_FAMILY:
            w = next((e for e in jev if e.value in KR_FAMILY), w)
        return _decide("enzyme", evs, pool=[w])
    weak = [e for e in evs if e.method == "FASTag termini" and e not in tag]   # a weak tag call does not decide
    return _decide("enzyme", evs, pool=[e for e in evs if e not in weak])


def reconcile(evidence: list) -> dict:
    by = {}
    for e in evidence:
        by.setdefault(e.parameter, []).append(e)
    out = {}
    get = lambda p: out.get(p).value if out.get(p) else None
    for p in ("instrument", "instrument_class", "ms1_analyzer", "ms2_analyzer", "fragmentation",
              "collision_energy", "ion_mobility", "acquisition", "dia_windows", "charge_range",
              "precursor_offset", "fragment_offset", "enzyme", "cys_alkylation", "enrichment",
              "peptide_length"):
        if p in by:
            d = _enrichment(by[p]) if p == "enrichment" else _enzyme(by[p]) if p == "enzyme" else _decide(p, by[p])
            if d:
                out[p] = _co_enrichment(d, by[p]) if p == "enrichment" else d
    if "variable_mods" in by:
        d = _variable_mods(by["variable_mods"])
        if d:
            out["variable_mods"] = d
    if "label" in by:
        d = _label(by["label"])
        if d:
            out["label"] = d
    # organism: the search result names a panel file; match it to the stated species
    if "organism" in by:
        # "not in panel" only says the panel search could not decide; it must not outrank a real organism call
        # (FASTag species, records, text): on DIA runs and TMT runs with reporters in MS3 the mini-search finds too
        # few PSMs while FASTag names the species
        real = [e for e in by["organism"] if e.value not in ("not in panel", "unknown") and e.confidence >= 0.5]
        if real:
            by["organism"] = [e for e in by["organism"] if e.value != "not in panel"]
        d = _decide("organism", by["organism"])
        if d:
            out["organism"] = _untested_pick(_absent_pick(_stated_untested(d, by["organism"]), by["organism"]),
                                             by["organism"])
    instrument = get("instrument") or ""
    for kind in ("precursor", "fragment"):
        param = f"{kind}_tolerance"
        d = _tolerance(kind, by.get(param, []), by.get(f"{kind}_offset", []), instrument,
                       get("ms2_analyzer") if kind == "fragment" else get("ms1_analyzer"))
        if d:
            out[param] = d
    # defaults for what nothing determined
    for p, v, why in (("enzyme", "Trypsin", "most common protease"),
                      ("cys_alkylation", "Carbamidomethyl (C)", "most common alkylation"),
                      ("label", "label free", "no label evidence"),
                      ("enrichment", "none", "no enrichment evidence")):
        if p not in out or (out[p].value == "unknown" and p in ("cys_alkylation", "enzyme")):
            e = Evidence(p, v, 0.3, "default", "default", why)
            prev = out[p].evidence if p in out else []
            out[p] = Decision(p, v, 0.3, "default", prev + [e], [], "default")
    if "organism" not in out:
        out["organism"] = Decision("organism", "unknown", 0.0, "default", [], ["give a FASTA, a "
                                   "description, a PXD accession or an organism panel"], "unknown")
    return out


def _label_compatible(neg, label):
    """a negative label call agrees unless it negates the decided label's class: "no SILAC" agrees with TMT and
    with label free, "no isobaric label" with SILAC (they made 120 of 171 flags on correct label decisions)"""
    neg, label = str(neg), str(label)
    if neg == "no SILAC":
        return not label.startswith("SILAC")
    if neg == "no isobaric label":
        return not label.startswith(("TMT", "iTRAQ"))
    return neg in NEGATIVE and label == "label free"


NO_AGREEMENT = {"precursor_tolerance", "fragment_tolerance", "precursor_offset", "fragment_offset", "charge_range",
                "dia_windows", "collision_energy", "variable_mods", "peptide_length"}


def indicator_agreement(decisions: dict, jev_verdicts=None):
    """How far the independent indicators agree with each decision. Per parameter, each detector (source:method)
    counts once with its strongest evidence; agreement = the confidence-weighted share that backs the decided value,
    inconsistency = 1 - agreement. Jev's verdict (texts and indicators against the decision) is reported beside it,
    and a contradiction by Jev counts as one more dissenting indicator. The tolerances and modification lists are
    left out: their sources measure different quantities (the error in the data, the authors' search window).
    overall = the confidence-weighted mean over the parameters with >= 2 indicators; level from the inconsistency
    (low < 0.2 <= medium < 0.4 <= high)."""
    jev_verdicts = jev_verdicts or {}
    per = {}
    for p, d in decisions.items():
        if p in NO_AGREEMENT or d.value in (None, "", "unknown"):
            continue
        parts = str(d.value).split(ENRICH_SEP) if p == "enrichment" else [d.value]
        best = {}
        for e in d.evidence:
            if e.source == "default" or e.method == "combined" or e.confidence < 0.3:
                continue
            agree = any(_same(e.value, v) or (p == "organism" and _organism_key(e.value) == _organism_key(v))
                        or (p == "label" and _label_compatible(e.value, v))
                        for v in parts)
            k = f"{e.source}:{e.method}"
            if k not in best or e.confidence > best[k][0]:
                best[k] = (e.confidence, agree, e.value)
        jv = jev_verdicts.get(p) or {}
        if str(jv.get("verdict", "")).endswith("contradict"):
            best[f"jev cross-check:{jv['verdict']}"] = (0.7 * jv.get("p", 0.5), False, jv["verdict"])
        if not best:
            continue
        tot = sum(c for c, _, _ in best.values())
        ok = sum(c for c, a, _ in best.values() if a)
        inc = round(1 - ok / tot, 2) if tot else 0.0
        per[p] = {"inconsistency": inc, "indicators": len(best), "agreeing": sum(a for _, a, _ in best.values()),
                  "dissent": [f"{k} = {_short(v)}" for k, (c, a, v) in sorted(best.items(), key=lambda kv: -kv[1][0])
                              if not a],
                  "level": _level(inc)}
        if jv:
            per[p]["jev"] = jv
    multi = {p: v for p, v in per.items() if v["indicators"] >= 2}
    w = {p: decisions[p].confidence or 0.1 for p in multi}
    overall = round(sum(multi[p]["inconsistency"] * w[p] for p in multi) / sum(w.values()), 2) if multi else 0.0
    worst = sorted(multi, key=lambda p: -multi[p]["inconsistency"])[:3]
    return {"overall": {"inconsistency": overall, "level": _level(overall),
                        "most_inconsistent": [p for p in worst if multi[p]["inconsistency"] >= 0.2]},
            "parameters": per}


def _level(x):
    return "low" if x < 0.2 else "medium" if x < 0.4 else "high"


def _short(v):
    return f"{v['value']} {v.get('unit', '')}".strip() if isinstance(v, dict) and "value" in v else str(v)[:60]


SEARCH_INDICATORS = ("panel mini-search", "ProSE organism search")


def organism_mix(evidence: list, jev_report=None):
    """Suspected mixture of organisms (benchmark mixes, xenografts, host-pathogen, co-culture), from independent
    indicators, each with a strength in 0..1:
    - search: a second database explains many spectra the winner does not (the mini-search or ProSE "A + B" note);
      strength 0.4 + its share of the winner's PSMs, at most 0.6: alone it is no mix (related species, contaminants
      and the antibody of an IP explain spectra of their own too)
    - stated: the user or the repository record names organisms of two or more genera (0.5); the texts alone 0.2
      (cell lines, BSA, E. coli expression hosts and antibodies name other species without a mixed sample)
    - Jev: p(organism = mixed species) x 0.7
    FASTag species ranks are left out: on large panels unrelated species score alike (Brachypodium vs Thalassiosira
    2693 vs 2688 tags in a human run). suspected = two kinds of indicator >= 0.3; score = 1 - prod(1 - s)."""
    ind = []
    genus = lambda v: taxa.scientific(v).replace("_", " ").split(" ")[0].lower()
    for e in evidence:
        if e.parameter == "organism" and e.source == "search" and " + " in str(e.value):
            a, b = str(e.value).split(" + ", 1)
            st = e.stats or {}
            top = (st.get(a) or {}).get("psms") if isinstance(st.get(a), dict) else None
            u = (st.get(b) or {}).get("unique_vs_best") if isinstance(st.get(b), dict) else None
            s = min(0.6, 0.4 + (u / top if top and u else 0.2))
            ind.append({"indicator": e.method, "species": [a, b], "strength": round(s, 2), "detail": e.detail})
    for srcs, s, name in ((("user", "repository"), 0.5, "stated by the user or the repository record"),
                          (("text",), 0.2, "named in the texts")):
        g = {}
        for e in evidence:
            if e.parameter == "organism" and e.source in srcs and e.confidence >= 0.45 and \
                    str(e.value) not in ("not in panel", "unknown"):
                g.setdefault(genus(e.value), e.value)
        if len(g) >= 2:
            ind.append({"indicator": name, "species": sorted(g.values()), "strength": s})
    p = ((jev_report or {}).get("probabilities") or {}).get("organism", {}).get("mixed species", 0.0)
    if p >= 0.2:
        ind.append({"indicator": "Jev (texts and indicators)", "species": [], "strength": round(0.7 * p, 2),
                    "detail": f"p(mixed species) = {p:.2f}"})
    score = 1.0
    for i in ind:
        score *= 1 - i["strength"]
    suspected = len({i["indicator"] for i in ind if i["strength"] >= 0.3}) >= 2
    out = {"suspected": suspected, "score": round(1 - score, 2), "indicators": ind,
           "scope": "file" if any(i["indicator"] in SEARCH_INDICATORS for i in ind) else "study"}
    # records, texts and Jev describe the study; a file of a mixed study can hold one species (the human-only and
    # 0 ng yeast files of benchmarks, uninfected controls): when every stated second species was searched and is
    # absent from this file, the mixture is the study's, not the file's
    got = _search_psms(evidence)
    if suspected and out["scope"] == "study" and got:
        psms, n, best = got
        named = {_organism_key(s) for i in ind for s in i["species"]} - {best}
        if named and all(_absent(psms, n, k) for k in named):
            out.update(suspected=False, note="study describes a mixture; this file looks single-species")
    return out


MIX_MAX_ORGANISMS = 4   # databases of a mixture union
MIX_OWN_SPECTRA = 10    # spectra of its own (and 0.5 % of the searched spectra) before a named organism joins it


def mixture_union(evidence, mix, decided):
    """The databases of a suspected mixture, ordered by evidence: the decided organism, then each organism a mixture
    indicator of strength >= 0.3 names (the texts name every species they mention: mouse beside a human-yeast
    benchmark, PXD045500) that the last panel mini-search tested and found with spectra of its own (no cRAP, none the
    winner explains) >= max(10, 0.5 % of the spectra), most first; at most 4. Reagent genera (trypsin, BSA, keratin
    hosts) join only when the user or the record names them. On the 0.1.3 mixset decisions the second species of
    the 19 mixed runs had 12-623 such spectra, those of the pure files of mixture studies 0-3, so a pure file keeps
    one database. Returns [(database name, own spectra)]; [] when no second organism qualifies."""
    if not (mix or {}).get("suspected"):
        return []
    search = [e for e in evidence if e.source == "search" and e.method == "panel mini-search" and e.stats
              and " + " not in str(e.value)]
    if not search:
        return []
    st = search[-1].stats
    n = st.get("n_spectra") or 0
    dbs = {_organism_key(k): k for k, v in st.items() if isinstance(v, dict)}
    named = {_organism_key(x) for i in mix["indicators"] if i["strength"] >= 0.3 for x in i["species"]}
    stated = {_organism_key(e.value) for e in evidence if e.parameter == "organism" and e.source in ("user", "repository")}
    first = _organism_key(decided)
    own = sorted(((st[dbs[k]].get("unique_vs_best") or 0, dbs[k]) for k in named & dbs.keys() - {first}
                  if taxa.scientific(dbs[k]).replace("_", " ").split(" ")[0] not in REAGENT_GENERA or k in stated),
                 reverse=True)
    own = [(k, u) for u, k in own if u >= max(MIX_OWN_SPECTRA, 0.005 * n)]
    if not own:
        return []
    return ([(dbs.get(first, decided), None)] + own)[:MIX_MAX_ORGANISMS]
