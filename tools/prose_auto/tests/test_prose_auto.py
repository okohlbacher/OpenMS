"""Tests on OpenMS test data (run from tools/prose_auto: python -m pytest tests)."""

import json
import os
import sys

import numpy as np

import pytest

from prose_auto import detect_chemistry as chem
from prose_auto import detect_instrument as inst
from prose_auto import detect_tolerance as tol
from prose_auto import llm as L
from prose_auto import prose_params as pp
from prose_auto import tagsearch as ts
from prose_auto import text_extract as tx
from prose_auto.evidence import Evidence
from prose_auto.hypotheses import HypothesisTester
from prose_auto.reconcile import reconcile
from prose_auto.repository import sdrf_evidence
from prose_auto.spectra import load_mzml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TOPP = os.path.join(ROOT, "src", "tests", "topp")
BSA = os.path.join(ROOT, "share", "OpenMS", "examples", "BSA")


def first(evs, p):
    c = [e for e in evs if e.parameter == p]
    return max(c, key=lambda e: e.confidence) if c else None


@pytest.fixture(scope="module")
def bsa():
    return load_mzml(os.path.join(BSA, "BSA1.mzML"))


def test_instrument_and_dda(bsa):
    ev = inst.detect_instrument(bsa) + inst.detect_acquisition(bsa)
    assert first(ev, "instrument").value == "LTQ Orbitrap XL"
    assert first(ev, "ms1_analyzer").value == "ORBITRAP"
    assert first(ev, "ms2_analyzer").value == "IT"
    assert first(ev, "fragmentation").value == "CID"
    assert first(ev, "acquisition").value == "DDA"


def test_dia_windows():
    from types import SimpleNamespace as S
    # 3 repeating 50-Th windows (+1 single scan): fewer than 5 periodic windows is no DIA scheme
    run = load_mzml(os.path.join(TOPP, "DIAuditor_1_input.mzML"))
    assert first(inst.detect_acquisition(run), "acquisition").value != "DIA"
    dia = [S(iso_width=16.0, iso_center=400 + 16 * (i % 40) + 8, iso_lower=8.0, iso_upper=8.0, charge=0, ion_mobility=None)
           for i in range(4000)]
    ev = inst.detect_acquisition(S(ms2=dia))
    assert first(ev, "acquisition").value == "DIA"
    w = first(ev, "dia_windows").value
    assert w["n_windows"] == 40 and w["min_mz"] == 400.0


def test_narrow_window_dia_is_not_prm():
    from types import SimpleNamespace as S
    def run(charge, n_centres):
        ms2 = [S(iso_width=2.0, iso_center=400 + 2 * (i % n_centres) + 1, iso_lower=1.0, iso_upper=1.0, charge=charge,
                 ion_mobility=None) for i in range(60 * n_centres)]
        return S(ms2=ms2)
    assert first(inst.detect_acquisition(run(0, 200)), "acquisition").value == "DIA"     # Astral 2 Th DIA, 400 Th
    assert first(inst.detect_acquisition(run(0, 20)), "acquisition").value == "PRM"      # 20 targets, 40 Th
    prm = [S(iso_width=1.2, iso_center=400 + 37.3 * (i % 16), iso_lower=0.6, iso_upper=0.6, charge=2, ion_mobility=None)
           for i in range(1600)]                                                            # 16 scattered targets
    assert first(inst.detect_acquisition(S(ms2=prm)), "acquisition").value == "PRM"


def test_wide_window_dda_is_not_dia():
    from types import SimpleNamespace as S
    # 4-Th DDA (PXD003531): 4000 precursors in 10000 MS2, most isolated twice; DIA: 40 centres, 400 cycles
    dda = [S(iso_width=4.0, iso_center=400 + 0.37 * (i // 2), iso_lower=2.0, iso_upper=2.0, charge=2, ion_mobility=None)
           for i in range(6000)] + [S(iso_width=4.0, iso_center=1600 + 0.3 * (i // 4), iso_lower=2.0, iso_upper=2.0,
                                      charge=2, ion_mobility=None) for i in range(4000)]
    dia = [S(iso_width=16.0, iso_center=400 + 16 * (i % 40) + 8, iso_lower=8.0, iso_upper=8.0, charge=0, ion_mobility=None)
           for i in range(16000)]
    assert first(inst.detect_acquisition(S(ms2=dda)), "acquisition").value == "DDA"
    assert first(inst.detect_acquisition(S(ms2=dia)), "acquisition").value == "DIA"
    # the same precursor fragmented twice in a row (PXD004732) repeats with gap 1: not a DIA cycle
    twice = [S(iso_width=2.0, iso_center=400 + 0.37 * (i // 2), iso_lower=1.0, iso_upper=1.0, charge=2, ion_mobility=None)
             for i in range(4000)]
    assert first(inst.detect_acquisition(S(ms2=twice)), "acquisition").value == "DDA"
    assert inst.window_periodicity([400 + 16 * (i % 40) for i in range(4000)]) == (1.0, 40, 40)


def test_itraq_reporters():
    run = load_mzml(os.path.join(TOPP, "IsobaricAnalyzer_input_1.mzML"))
    lab = [e for e in chem.detect_labels(run, True) if e.method == "reporter ions"][0]
    assert lab.value == "iTRAQ4plex"


def test_low_res_tolerances(bsa):
    ev = tol.detect_tolerances(bsa, "DDA", ms2_high_res=False, ms1_high_res=True)
    f = first(ev, "fragment_tolerance")
    assert f.value["unit"] == "Da" and 0.2 <= f.value["value"] <= 0.8
    p = first(ev, "precursor_tolerance")
    assert p.value["unit"] == "ppm" and p.value["value"] <= 10


def test_gauss_uniform_fit():
    import numpy as np
    rng = np.random.default_rng(1)
    x = np.concatenate([rng.normal(2.0, 1.5, 2000), rng.uniform(-30, 30, 1000)])
    mu, sigma, pi = tol.fit_gauss_uniform(x, 30)
    assert abs(mu - 2.0) < 0.2 and abs(sigma - 1.5) < 0.2 and 0.6 < pi < 0.75


def _write(path, recs):
    with open(path, "w") as fh:
        for h, s in recs:
            fh.write(f">{h}\n{s}\n")


def test_digest_cache_and_variants(tmp_path):
    fasta = tmp_path / "p.fasta"
    _write(fasta, [("P1", "MKCLLAGGTKPEPTIDECKRAAACCDEFGHIKLMNPQRSTVWYK"), ("REV_P2", "AAAAAAAAK"), ("P3", "XXBCDEFGHIKK")])
    cache = tmp_path / "cache"
    m = ts.Mods(cys=57.021464, k=229.162932, nterm=229.162932)
    idx = ts.index_for("p", str(fasta), m, cache_dir=str(cache))
    assert len(list(cache.iterdir())) == 1 and len(ts._LOADED) >= 1
    for i in range(len(idx)):
        seq = idx.seq(i)
        assert set(seq) <= set(ts.AA)                           # X/B peptides are dropped
        ref = sum(ts.AA[a] + (m.cys if a == "C" else m.k if a == "K" else 0) for a in seq) + ts.H2O + m.nterm
        assert abs(idx.masses[i] - ref) < 1e-9
    assert all(np.diff(idx.masses) >= 0)
    ts._LOADED.clear()
    again = ts.index_for("p", str(fasta), ts.Mods(cys=0.0), cache_dir=str(cache))   # from disk, another Cys
    assert len(again) == len(idx) and len(list(cache.iterdir())) == 1
    f = ts._fragments("PEPTIDEK", ts.Mods(cys=0.0))
    assert f.size == 14 and abs(f[0] - (ts.AA["P"] + ts.PROTON)) < 1e-9
    # binomial tail against the direct sum
    from math import comb, log10
    for k, n, p in ((3, 14, 0.1), (0, 10, 0.2), (14, 14, 0.5)):
        ref = 0.0 if k <= 0 else -log10(max(sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1)), 1e-300))
        got = ts._binom_scores(np.array([k]), np.array([n]), np.array([p]))[0]
        assert abs(got - ref) < 1e-9


def test_mini_search_alkylation(bsa, tmp_path):
    # BSA plus an unrelated proteome-like decoy organism (shuffled BSA-free mix)
    mix = os.path.join(ROOT, "share", "OpenMS", "examples", "TOPPAS", "data", "BSA_Identification",
                       "18Protein_SoCe_Tr_detergents_trace.fasta")
    recs = [(a, s) for a, s in ts.read_fasta(mix) if "SORC5" not in a]
    ecoli = os.path.join(ROOT, "share", "OpenMS", "examples", "TOPPAS", "data", "Identification",
                         "target_decoy_Ecoli_K12_TaxID_83333.proteomes.fasta")
    _write(tmp_path / "mix.fasta", recs)
    h = HypothesisTester(bsa, 0.4, False, prec_ppm=20, n_spectra=1200)
    ev = h.organism({"mix": str(tmp_path / "mix.fasta"), "ecoli": ecoli})
    assert first(ev, "organism").value == "mix"
    alk = h.alkylation()[0]
    assert alk.value == "Carbamidomethyl (C)" and alk.confidence > 0.8
    acc = h.accuracy()
    assert abs(first(acc, "precursor_offset").value["value"]) < 3


def test_reader_texts_and_independence():
    from prose_auto import repository as repo
    sdrf = ("source name\tcharacteristics[organism]\tcomment[data file]\tcomment[label]\n"
            "s1\tHomo sapiens\ta.raw\tSILAC light\ns1\tHomo sapiens\ta.raw\tSILAC heavy\ns2\tHomo sapiens\tb.raw\tSILAC light\n")
    d = repo.sdrf_digest(sdrf, "/x/a.mzML")
    assert d.startswith("Rows of this data file (a.mzML)") and d.count("comment[label]=") == 2
    assert "characteristics[organism]: Homo sapiens (3)" in d and "comment[label]: SILAC light (2); SILAC heavy (1)" in d
    rec = repo.record_text({"organisms": [{"name": "Homo sapiens"}], "keywords": ["SILAC", "phospho"],
                            "instruments": [{"name": "Q Exactive"}], "title": "ignored"})
    assert rec == "organisms: Homo sapiens\ninstruments: Q Exactive\nkeywords: SILAC; phospho"
    # a reader that saw the measured data does not raise the confidence of the measurement it may repeat
    data = Evidence("label", "SILAC (Lys8/Arg10)", 0.7, "data", "MS1 heavy/light pairs")
    blind = reconcile([data, Evidence("label", "SILAC (Lys8/Arg10)", 0.5, "llm", "jev:jev-latest")])["label"]
    seen = reconcile([data, Evidence("label", "SILAC (Lys8/Arg10)", 0.5, "llm", "jev:jev-latest+data")])["label"]
    assert seen.confidence == 0.7 and blind.confidence > 0.7


def test_variable_mods_and_stated_windows():
    from prose_auto import schema as S
    d = reconcile([Evidence("variable_mods", ["Oxidation (M)", "Deamidated (N)"], 0.5, "data", "delta-mass combinations"),
                   Evidence("variable_mods", ["Phospho (S)", "Oxidation (M)"], 0.5, "llm", "jev:x"),
                   Evidence("variable_mods", ["Acetyl (K)"], 0.3, "repository", "pride")])["variable_mods"]
    assert d.value == ["Oxidation (M)", "Deamidated (N)", "Phospho (S)"] and d.confidence >= 0.5
    P = pp.to_prose(d := reconcile([
        Evidence("precursor_tolerance", {"value": 20.0, "unit": "ppm"}, 0.6, "repository", "sdrf"),
        Evidence("fragment_tolerance", {"value": 0.02, "unit": "Da"}, 0.6, "repository", "sdrf"),
        Evidence("ms2_analyzer", "ORBITRAP", 0.95, "metadata", "mzML")]))["params"]
    assert P["Search:precursor:mass_tolerance_lower"] == 20.0                  # stated window, not doubled
    assert (P["Search:fragment:mass_tolerance"], P["Search:fragment:mass_tolerance_unit"]) == (0.02, "Da")
    assert S._ppm("20 ppm") == 20.0 and S._ppm(">=0.5 Da") == 500.0
    # defaults and measured errors are still widened; an ion trap by its full analyzer name gets 0.35 Da
    P = pp.to_prose(reconcile([Evidence("precursor_tolerance", {"value": 10.0, "unit": "ppm"}, 0.9, "data", "x"),
                               Evidence("ms2_analyzer", "PAULIONTRAP", 0.95, "metadata", "mzML"),
                               Evidence("fragment_tolerance", {"value": 0.5, "unit": "Da"}, 0.8, "data", "x")]))["params"]
    assert P["Search:precursor:mass_tolerance_lower"] == 20.0 and P["Search:fragment:mass_tolerance"] == 0.35
    assert P["Search:calibration:enabled"] == "true"
    # a stated Da window stays when the analyzer is unknown
    P = pp.to_prose(reconcile([Evidence("fragment_tolerance", {"value": 0.02, "unit": "Da"}, 0.6, "repository", "sdrf")]))
    assert P["params"]["Search:fragment:mass_tolerance"] == 0.02
    # Jev having seen the data: no boost in either direction, and no extra source in the modification merge
    cys = lambda m: Evidence("cys_alkylation", "Carbamidomethyl (C)", 0.6, *m)
    d = reconcile([cys(("llm", "jev:x+data")), cys(("data", "Cys immonium"))])["cys_alkylation"]
    assert d.confidence == 0.6
    vm = reconcile([Evidence("variable_mods", ["Oxidation (M)"], 0.6, "data", "delta-mass combinations"),
                    Evidence("variable_mods", ["Oxidation (M)", "Phospho (S)"], 0.6, "llm", "jev:x+data")])["variable_mods"]
    assert vm.value == ["Oxidation (M)", "Phospho (S)"] and vm.confidence == 0.6


def test_enrichment_keywords_need_enrichment_terms():
    enr = lambda t: {e.value for e in tx.extract(t, "text") if e.parameter == "enrichment"}
    assert enr("Phosphopeptides were enriched with TiO2 beads.") == {"Phospho (STY)"}
    assert enr("Proteins were annotated with KEGG pathways; phosphatase inhibitors were added.") == set()
    assert enr("Phospho (STY) was set as a variable modification.") == set()
    assert enr("K-epsilon-GG peptides: anti-K-GG antibody enrichment of the ubiquitinome.") == {"GlyGly (K)"}


def test_text_extract():
    ev = tx.extract("HeLa cells, alkylated with iodoacetamide, TMT10plex, Q Exactive HF, DIA", "user")
    vals = {e.parameter: e.value for e in ev}
    assert vals["organism"] == "Homo sapiens"
    assert vals["cys_alkylation"] == "Carbamidomethyl (C)"
    assert vals["label"] == "TMT10/11plex"
    assert vals["instrument"] == "Q Exactive HF"
    assert vals["acquisition"] == "DIA"


class FakeLLM(L.Backend):
    name = "fake"

    def __init__(self, answer):
        self.answer = answer

    def complete(self, prompt):
        return self.answer


def test_llm_quote_guard():
    text = "Proteins were alkylated with iodoacetamide and digested with trypsin."
    ans = json.dumps([
        {"parameter": "cys_alkylation", "value": "carbamidomethyl", "quote": "alkylated with iodoacetamide", "confidence": 0.9},
        {"parameter": "label", "value": "TMT", "quote": "labelled with TMT", "confidence": 0.9},   # not in text
        {"parameter": "colour", "value": "blue", "quote": "trypsin", "confidence": 0.9},
    ])
    ev, rej = L.extract_settings(FakeLLM("Here you go:\n```json\n" + ans + "\n```"), text, "methods")
    assert [(e.parameter, e.value) for e in ev] == [("cys_alkylation", "Carbamidomethyl (C)")]
    assert len(rej) == 2


def test_sdrf_parse():
    sdrf = ("source name\tcharacteristics[organism]\tcomment[label]\tcomment[instrument]\t"
            "comment[modification parameters]\tcomment[cleavage agent details]\tcomment[precursor mass tolerance]\n"
            "s1\tHomo sapiens\tTMT126\tNT=Q Exactive HF;AC=MS:1002523\tNT=Carbamidomethyl;TA=C;MT=fixed\t"
            "NT=Trypsin;AC=MS:1001251\t10 ppm\n")
    vals = {e.parameter: e.value for e in sdrf_evidence(sdrf)}
    assert vals["organism"] == "Homo sapiens" and vals["cys_alkylation"] == "Carbamidomethyl (C)"
    assert vals["precursor_tolerance"] == {"value": 10.0, "unit": "ppm"}


def test_reconcile_conflict_and_params():
    ev = [
        Evidence("label", "TMT10/11plex", 0.95, "data", "reporter ions"),
        Evidence("label", "label free", 0.75, "user", "keywords"),
        Evidence("precursor_tolerance", {"value": 4, "unit": "ppm"}, 0.9, "search", "mini-search PSMs"),
        Evidence("fragment_tolerance", {"value": 0.0, "unit": "ppm"}, 0.0, "data", "x"),
        Evidence("cys_alkylation", "Carbamidomethyl (C)", 0.9, "search", "alkylation competition"),
        Evidence("cys_alkylation", "none (free Cys)", 0.75, "user", "keywords"),
    ]
    d = reconcile(ev)
    assert d["label"].value == "TMT10/11plex" and d["label"].status == "review" and d["label"].conflicts
    assert d["cys_alkylation"].value == "Carbamidomethyl (C)" and d["cys_alkylation"].status == "review"
    P = pp.to_prose(d)["params"]
    assert "TMT6plex (K)" in P["Search:modifications:fixed"]
    assert P["Search:precursor:mass_tolerance_lower"] == 16  # 4x the measured 4 ppm
    assert P["Search:calibration:enabled"] == "true"
    assert "<ITEMLIST" in pp.to_ini_snippet(P)


def test_silac_coherent_pairs_and_gaps():
    from prose_auto.delta_combos import silac_from_gaps
    E = lambda k8, r10, r6, k4: {"Lys8": k8, "Arg10": r10, "Arg6": r6, "Lys4/dimethyl-d4": k4}
    many = E(400, 400, 400, 400)
    assert chem._coherent_silac_pair(E(3.06, 3.58, 0.55, 0.66), many)[0] == "SILAC (Lys8/Arg10)"   # PXD001739
    assert chem._coherent_silac_pair(E(1.3, 0.87, 3.74, 3.04), many)[0] == "SILAC (Lys4/Arg6)"     # PXD009049
    assert chem._coherent_silac_pair(E(2.07, 2.19, 2.49, 1.56), many) is None                      # triplex: gaps
    assert chem._coherent_silac_pair(E(1.0, 1.0, 1.2, 3.5), many) is None                          # dimethyl-d4
    assert chem._coherent_silac_pair(E(3.06, 3.58, 0.55, 0.66), E(150, 400, 400, 400)) is None     # too few
    tri = {"Label:13C(6)": 0.20, "Label:2H(4)": 0.18, "Label:13C(6)15N(2)": 0.08, "Oxidation": 0.10}
    assert silac_from_gaps(tri, 860)[0].value.startswith("SILAC triplex")                           # PXD016465
    assert silac_from_gaps({"Label:13C(6)15N(4)": 0.13}, 2000) == []                                # one label only
    assert silac_from_gaps({"Label:13C(6)15N(4)": 0.05, "Label:13C(6)15N(2)": 0.04}, 1179) == []    # PXD050844
    assert "Label:2H(4) (K)" in pp.SILAC_VARIABLE["SILAC (Lys4/Arg6)"]


def test_co_enrichment():
    # PXD003531: TiO2 phospho enrichment that also took glycopeptides; a weaker third signal stays out
    ev = [Evidence("enrichment", "Phospho (STY)", 0.814, "data", "diagnostic ions"),
          Evidence("enrichment", "Glyco (HexNAc oxonium)", 0.9, "data", "diagnostic ions"),
          Evidence("enrichment", "Phospho (STY)", 0.58, "data", "delta-mass combinations"),
          Evidence("enrichment", "Acetyl (K)", 0.6, "data", "diagnostic ions")]
    d = reconcile(ev)
    assert d["enrichment"].value == "Glyco (HexNAc oxonium) + Phospho (STY)"
    assert not any("Phospho" in c for c in d["enrichment"].conflicts) and d["enrichment"].confidence >= 0.7
    P = pp.to_prose(d)["params"]
    assert "Phospho (S)" in P["Search:modifications:variable"] and "Acetyl (K)" not in P["Search:modifications:variable"]
    assert reconcile(ev[:1])["enrichment"].value == "Phospho (STY)"


def test_organism_data_chooses_among_named_species():
    def ev(searched):
        stats = {n: {"psms": c} for n, c in searched.items()}
        return [Evidence("organism", "Escherichia coli", 0.6, "repository", "pride", ""),
                Evidence("organism", "Homo sapiens (human)", 0.6, "repository", "pride", ""),
                Evidence("organism", "Homo sapiens", 0.66, "data", "FASTag species", ""),
                Evidence("organism", "Homo_sapiens", 0.47, "search", "panel mini-search", "", stats)]
    # the record's first pick (E. coli) is not on the data's shortlist; the mini-search and FASTag find human, also named
    d = reconcile(ev({"Homo_sapiens": 1129, "Chlorocebus_sabaeus": 923}))["organism"]
    assert d.value == "Homo_sapiens" and d.status == "review" and "not among the species the data shortlist" in d.conflicts[-1]
    # a pick on the shortlist keeps its place
    assert reconcile(ev({"Homo_sapiens": 1129, "Escherichia_coli": 300}))["organism"].value == "Escherichia coli"
    # FASTag disagreeing, or the data species not named by the metadata: no change
    e = ev({"Homo_sapiens": 1129})
    e[2] = Evidence("organism", "Mus musculus", 0.66, "data", "FASTag species", "")
    assert reconcile(e)["organism"].value == "Escherichia coli"
    e = ev({"Rattus_norvegicus": 900})
    e[2] = Evidence("organism", "Rattus norvegicus", 0.66, "data", "FASTag species", "")
    e[3] = Evidence("organism", "Rattus_norvegicus", 0.47, "search", "panel mini-search", "", {"Rattus_norvegicus": {"psms": 900}})
    assert reconcile(e)["organism"].value == "Escherichia coli"
    # a weak search share (antibody species of an IP) does not overrule the record
    e = ev({"Homo_sapiens": 75, "Chlorocebus_sabaeus": 16})
    e[3].stats["n_spectra"] = 2000
    assert reconcile(e)["organism"].value == "Escherichia coli"


def test_tims_acquisition(tmp_path):
    import sqlite3
    from prose_auto import external as ext

    def tdf(name, types):
        d = tmp_path / f"{name}.d"
        d.mkdir()
        db = sqlite3.connect(d / "analysis.tdf")
        db.execute("CREATE TABLE Frames (Id INTEGER PRIMARY KEY, MsMsType INTEGER)")
        db.execute("CREATE TABLE DiaFrameMsMsWindows (WindowGroup, ScanNumBegin, ScanNumEnd, IsolationMz, IsolationWidth)")
        db.executemany("INSERT INTO Frames (MsMsType) VALUES (?)", [(t,) for t in types])
        db.commit()
        return str(d)
    # an empty DIA window table, as in every ddaPASEF file, must not make it DIA
    assert ext.tims_acquisition(tdf("dda", [0, 8, 8, 0, 8])) == "ddaPASEF"
    assert ext.tims_acquisition(tdf("dia", [0, 9, 9])) == "diaPASEF"
    assert ext.tims_acquisition(tdf("ms1", [0, 0])) == "MS1 only"
    assert ext.tims_acquisition(tdf("mixed", [0, 8, 9])) is None
    assert ext.tims_acquisition(str(tmp_path)) is None
    d = tdf("named", [0, 9])
    import sqlite3 as sq
    db = sq.connect(os.path.join(d, "analysis.tdf"))
    db.execute("CREATE TABLE GlobalMetadata (Key TEXT, Value TEXT)")
    db.execute("INSERT INTO GlobalMetadata VALUES ('InstrumentName', 'timsTOF Pro 2')")
    db.commit()
    assert ext.tims_instrument(d) == "timsTOF Pro 2" and ext.tims_instrument(str(tmp_path)) is None


def test_schema_rules_and_decode():
    from prose_auto import schema as S
    hard = S.check({"label": "TMT6plex", "ms2_analyzer": "IT", "fragmentation": "CID", "acquisition": "DDA"})
    assert [r["rule"] for r in hard] == ["isobaric_it_cid"]
    assert not S.check({"label": "TMT6plex", "ms2_analyzer": "IT", "fragmentation": "CID", "acquisition": "DDA SPS-MS3"},
                       kinds=("hard",))
    assert S.check({"acquisition": "DIA (diaPASEF)", "instrument": "Orbitrap Exploris 480"})[0]["rule"] == "pasef_needs_tims"
    assert S.check({"sample_type": "immunopeptidome", "enzyme": "Trypsin"})[0]["kind"] == "hard"
    # a near-tie in one head is settled by the others: diaPASEF beats DIA on a timsTOF
    a, changed = S.decode({
        "acquisition": {"probabilities": {"DIA (diaPASEF)": 0.48, "DDA": 0.52}},
        "instrument": {"probabilities": {"Orbitrap Exploris 480": 0.9, "timsTOF Pro": 0.1}},
        "label": {"probabilities": {"TMT6plex": 0.55, "label free": 0.45}},
        "ms2_analyzer": {"probabilities": {"IT": 0.9, "ORBITRAP": 0.1}},
        "fragmentation": {"probabilities": {"CID": 0.9, "HCD": 0.1}}})
    assert a["label"] == "label free" and "label" in changed      # TMT is impossible with ion-trap CID
    assert a["acquisition"] == "DDA"
    assert "CONSISTENCY RULES" in S.prompt_schema()


def _fake_jev_answers(body):
    qs = body["questions"]
    if "organism" in qs and "supports" in qs["organism"]["criteria"]:
        return {"answers": {"organism": {"choice": "texts_contradict", "probabilities": {"texts_contradict": 0.85}}},
                "usage": {"cost_usd": 0.0004}}
    ans = {k: {"noul": 0.1} for k in qs if ":" in k}
    ans["var:Acetyl (Protein N-term)"] = {"noul": 0.9}
    ans.update({
        "organism": {"choice": "homo_sapiens", "probabilities": {"homo_sapiens": 0.9}},
        "label": {"choice": "tmtpro_16_18plex", "probabilities": {"tmtpro_16_18plex": 0.8, "label_free": 0.2}},
        "ms2_analyzer": {"choice": "orbitrap", "probabilities": {"orbitrap": 0.9}},
        "fragmentation": {"choice": "hcd", "probabilities": {"hcd": 0.9}},
        "enzyme": {"choice": "not_stated", "probabilities": {"not_stated": 0.7}},
        "enrichment": {"choice": "phospho_sty", "probabilities": {"phospho_sty": 0.8}},
        "fragment_tolerance": {"choice": "20_ppm", "probabilities": {"20_ppm": 0.9}}})
    return {"answers": ans, "usage": {"cost_usd": 0.0012}}


def test_jev_read_study_and_cross_check():
    from prose_auto import jev as J

    jev = J.Jev(key="x", transport=_fake_jev_answers)
    ev, rep = J.read_study(jev, {"user's description": "HeLa, TMTpro 16plex, TiO2", "PRIDE data protocol": "20 ppm"},
                           user=True)
    got = {e.parameter: e.value for e in ev}
    assert got["organism"] == "Homo sapiens" and got["label"] == "TMTpro (16/18plex)"
    assert got["enrichment"] == "Phospho (STY)" and got["fragment_tolerance"] == {"value": 20.0, "unit": "ppm"}
    assert "enzyme" not in got
    assert any(e.parameter == "variable_mods" and "Acetyl (Protein N-term)" in e.value for e in ev)
    assert any(e.parameter == "variable_mods" and "Phospho (S)" in e.value for e in ev)   # implied by the enrichment
    assert all(e.source == "llm" and e.confidence <= 0.7 for e in ev)
    assert rep["sources"] == ["user's description", "PRIDE data protocol"]
    dec = reconcile([Evidence("organism", "Mus musculus", 0.9, "search", "t", "t")])
    issues, verdicts = J.cross_check(jev, {"user's description": "HeLa"}, dec)
    assert issues and issues[0]["parameter"] == "organism" and issues[0]["severity"] == "high"
    assert verdicts["organism"]["verdict"] == "texts_contradict"
    assert jev.calls == 2 and abs(jev.cost_usd - 0.0016) < 1e-9


def test_llm_study_extraction_with_rules():
    class Fake(L.Backend):
        name = "fake"

        def complete(self, prompt):
            assert "CONSISTENCY RULES" in prompt and "[PRIDE sample protocol]" in prompt
            return json.dumps({
                "settings": [
                    {"head": "label", "value": "TMT10/11plex", "quote": "TMT10plex", "source": "x", "confidence": 0.9},
                    {"head": "ms2_analyzer", "value": "IT", "quote": "ion trap", "confidence": 0.8},
                    {"head": "fragmentation", "value": "CID", "quote": "CID", "confidence": 0.8},
                    {"head": "organism", "value": "Homo sapiens", "quote": "invented words", "confidence": 0.9},
                    {"head": "precursor_tolerance", "value": {"value": 10, "unit": "ppm"}, "quote": "10 ppm"}],
                "contradictions": [{"heads": ["label"], "issue": "abstract says label free",
                                    "quotes": ["label-free"]}]})

    texts = {"PRIDE description": "A label-free study.", "PRIDE sample protocol":
             "Peptides were TMT10plex labelled, CID in the ion trap, 10 ppm precursor tolerance."}
    ev, rejected, conflicts = L.extract_study(Fake(), texts)
    got = {e.parameter: e.value for e in ev}
    assert got["label"] == "TMT10/11plex" and got["precursor_tolerance"] == {"value": 10.0, "unit": "ppm"}
    assert "organism" not in got and rejected[0]["why"] == "quote not found in the texts"
    kinds = {c.get("rule") or c["kind"] for c in conflicts}
    assert "isobaric_it_cid" in kinds and "text" in kinds


def test_tune_loop_with_fake_prose(tmp_path):
    from prose_auto import tune as T

    calls = []

    def fake(mzml, P, open_search=False):
        calls.append(open_search)
        if open_search:
            return {"shifts": [(79.966, 400), (0.984, 50)]}
        score = 1000
        if "Phospho (S)" in (P.get("Search:modifications:variable") or []):
            score += 300
        if P.get("Search:enzyme") == "Trypsin/P":
            score -= 5
        return {"score": score, "psms": score, "ms2": 5000,
                "precursor_error": {"valid": True, "recommended_ppm": 4.0},
                "fragment_error": {"valid": True, "recommended_ppm": 12.0}}

    fake.n = 0
    P0 = {"Search:precursor:mass_tolerance_lower": 10.0, "Search:precursor:mass_tolerance_upper": 10.0,
          "Search:precursor:mass_tolerance_unit": "ppm", "Search:fragment:mass_tolerance": 20.0,
          "Search:fragment:mass_tolerance_unit": "ppm", "Search:modifications:variable": ["Oxidation (M)"],
          "Search:enzyme": "Trypsin", "Search:calibration:enabled": "true"}
    import prose_auto.tune as tm
    tm.write_subset_mzml = lambda src, dst, n: 5000
    res = T.tune("x.mzML", P0, fake, facts={"ms2_analyzer": "ORBITRAP"}, rounds=3, per_round=10,
                 trace=str(tmp_path / "t.jsonl"), log=lambda *a: None)
    assert res["final_score"] == 1300 and "Phospho (S)" in res["params"]["Search:modifications:variable"]
    assert any(h["action"] == "add_phospho" and h["kept"] for h in res["history"])
    assert (tmp_path / "t.jsonl").read_text().count("\n") == len(res["history"])
    # ion-trap MS2: a ppm fragment window is never proposed (hard rule)
    c = T.candidates({**P0, "Search:fragment:mass_tolerance": 0.5, "Search:fragment:mass_tolerance_unit": "Da"},
                     {"fragment_error": {}}, [], {"ms2_analyzer": "IT"})
    assert not any(k.endswith("fragment") for k, _, _ in c)


def test_bench_text_end_to_end(tmp_path, monkeypatch):
    from prose_auto import bench_text as B
    from prose_auto import jev as J

    d = tmp_path / "repo" / "datasets" / "PXD000123"
    d.mkdir(parents=True)
    (d / "PXD000123.sdrf.tsv").write_text(
        "source name\tcharacteristics[organism]\tcomment[instrument]\tcomment[label]\tcomment[cleavage agent details]\t"
        "comment[modification parameters]\tcomment[modification parameters]\tcomment[fragment mass tolerance]\n"
        "s1\tHomo sapiens\tNT=Orbitrap Fusion Lumos;AC=MS:1002732\tTMTpro 126\tNT=Trypsin\t"
        "NT=Carbamidomethyl;TA=C;MT=Fixed\tNT=Acetyl;PP=Protein N-term;MT=Variable\t20 ppm\n")
    monkeypatch.setattr(B, "texts_for", lambda acc, paper=False: (
        {"PRIDE title": "x", "PRIDE description": "HeLa TMTpro study " * 20}, {"instruments": [{"name": "Q Exactive"}]}))
    real = J.Jev
    monkeypatch.setattr(J, "Jev", lambda: real(key="x", transport=_fake_jev_answers))
    a = type("A", (), {"sdrf_repo": str(tmp_path / "repo"), "n": 1, "seed": 1, "paper": False, "llm": None,
                       "no_jev": False, "out": str(tmp_path / "out")})()
    B.run(a)
    rows = (tmp_path / "out" / "rows.tsv").read_text().splitlines()
    got = {(r.split("\t")[1], r.split("\t")[2]): r.split("\t")[5] for r in rows[1:]}
    assert got[("organism", "jev")] == "1" and got[("label", "jev")] == "1"
    assert got[("instrument", "pride")] == "0" and got[("fragment_tolerance", "jev")] == "1"
    assert "var:acetyl" in (tmp_path / "out" / "rows.tsv").read_text()
    assert "Jev calibration" in (tmp_path / "out" / "summary.md").read_text()



def test_organism_from_metadata_searches_only_the_given_db(tmp_path):
    from prose_auto import cli
    mix = os.path.join(ROOT, "share", "OpenMS", "examples", "TOPPAS", "data", "BSA_Identification",
                       "18Protein_SoCe_Tr_detergents_trace.fasta")
    out = tmp_path / "out"
    cli.main(["analyze", os.path.join(BSA, "BSA1.mzML"), "--fasta", mix, "--organism-source", "metadata",
              "--spectra", "1200", "-o", str(out)])
    rep = json.load(open(out / "BSA1.auto.json"))
    org = rep["decisions"]["organism"]
    assert org["value"] == "18Protein_SoCe_Tr_detergents_trace"
    assert all(e["source"] != "search" for e in org["evidence"])     # no data-based organism call
    assert rep["decisions"]["cys_alkylation"]["value"] == "Carbamidomethyl (C)"   # hypotheses ran on the given DB


@pytest.mark.skipif(sys.platform == "win32", reason="the DIAspeXtract and FileConverter stand-ins are shell scripts")
def test_diaspextract_exit_11_falls_back_to_dda(tmp_path):
    """frames that look diaPASEF, a DIAspeXtract that answers 'this is DDA' (exit 11): FileConverter takes over"""
    import sqlite3, stat
    from prose_auto import cli
    d = tmp_path / "run.d"
    d.mkdir()
    db = sqlite3.connect(d / "analysis.tdf")
    db.execute("CREATE TABLE Frames (Id INTEGER PRIMARY KEY, MsMsType INTEGER)")
    db.executemany("INSERT INTO Frames (MsMsType) VALUES (?)", [(0,), (9,)])
    db.commit()
    def tool(name, body):
        f = tmp_path / name
        f.write_text("#!/bin/sh\n" + body + "\n")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
        return str(f)
    dia = tool("diaspextract", "echo 'input is ddaPASEF' >&2; exit 11")
    fc = tool("FileConverter", f'cp "{os.path.join(BSA, "BSA1.mzML")}" "$4"')
    mix = os.path.join(ROOT, "share", "OpenMS", "examples", "TOPPAS", "data", "BSA_Identification",
                       "18Protein_SoCe_Tr_detergents_trace.fasta")
    out = tmp_path / "out"
    cli.main(["analyze", str(d), "--diaspextract", dia, "--fileconverter", fc, "--fasta", mix,
              "--organism-source", "metadata", "--spectra", "600", "-o", str(out)])
    rep = json.load(open(out / "run.auto.json"))
    assert rep["decisions"]["acquisition"]["value"] == "DDA (ddaPASEF)"


def test_indicator_agreement_and_organism_mix():
    from prose_auto.reconcile import indicator_agreement, organism_mix
    ev = [Evidence("organism", "Homo_sapiens", 0.7, "search", "panel mini-search", "",
                   {"Homo_sapiens": {"psms": 300, "unique_vs_best": 250}, "Escherichia_coli": {"psms": 120,
                    "unique_vs_best": 100}}),
          Evidence("organism", "Homo_sapiens + Escherichia_coli", 0.5, "search", "panel mini-search", "",
                   {"Homo_sapiens": {"psms": 300}, "Escherichia_coli": {"psms": 120, "unique_vs_best": 100}}),
          Evidence("organism", "Homo sapiens (human)", 0.6, "repository", "pride"),
          Evidence("organism", "Escherichia coli", 0.6, "repository", "pride"),
          Evidence("enzyme", "Trypsin", 0.8, "search", "protease competition"),
          Evidence("enzyme", "Trypsin", 0.5, "text", "keywords"),
          Evidence("label", "TMT10/11plex", 0.9, "data", "reporter ions"),
          Evidence("label", "label free", 0.5, "text", "keywords")]
    dec = reconcile(ev)
    ag = indicator_agreement(dec, {"label": {"verdict": "texts_contradict", "p": 0.9}})
    assert ag["parameters"]["enzyme"]["inconsistency"] == 0.0
    lab = ag["parameters"]["label"]
    assert lab["inconsistency"] > 0.4 and lab["level"] == "high" and len(lab["dissent"]) == 2
    assert "label" in ag["overall"]["most_inconsistent"]
    mix = organism_mix(ev, {"probabilities": {"organism": {"mixed species": 0.8}}})
    assert mix["suspected"] and len(mix["indicators"]) == 3 and mix["score"] > 0.8
    assert not organism_mix(ev[:2])["suspected"]   # the search note alone
    assert not organism_mix(ev[:1] + ev[2:3])["suspected"]


def test_fdr_filter_accepts_tied_scores_only_as_a_group():
    # 99 targets above a tie of 1 target and 2 decoys: cutting inside the tie would pass 100 targets at 2% FDR
    psms = [(i, 100.0 - i, False, "PEPTIDE", 0.0) for i in range(99)]
    psms += [(99, 1.0, False, "PEPTIDE", 0.0), (100, 1.0, True, "EDITPEP", 0.0), (101, 1.0, True, "EDITPEP", 0.0)]
    ok, thr = ts.fdr_filter(psms)
    assert len(ok) == 99 and thr == 2.0


def _fake_run(**kw):
    from argparse import Namespace
    from prose_auto import cli
    a = Namespace(**{"fastag": "FASTag", "fasta": None, "panel": "p", "fastag_subsample": 0.1,
                     "fastag_taxonomy": None, "threads": 0, **kw})
    return cli._Run(a, lambda *x: None, "base", "run.mzML")


def test_tier2_redoes_mass_gaps_for_a_new_winner(monkeypatch):
    from prose_auto import cli
    monkeypatch.setattr(cli.ext, "fastag_alkylation", lambda fastag, mzml, db, *x, **k:
                        [Evidence("cys_alkylation", db, 0.5, "data", "FASTag mass gaps", "", {"hist": []})])
    monkeypatch.setattr(cli, "_shortlist", lambda c, panel: ["B"])

    class H:
        best_db = ("A", "a.fasta")
        def organism(self, dbs):
            self.best_db = ("B", dbs["B"])
            return [Evidence("organism", "B", 0.8, "search", "panel mini-search")]
        def accuracy(self):
            return []
        alkylation = enzyme = accuracy

    c, h = _fake_run(), H()
    cli._fastag_stage(c, h, org_fixed=True)
    cli._tier2(c, h, {"A": "a.fasta", "B": "b.fasta"})
    assert [e.value for e in c.ev if e.method == "FASTag mass gaps"] == ["b.fasta"]


def test_fastag_species_runs_once(monkeypatch):
    from prose_auto import cli
    calls = []
    monkeypatch.setattr(cli.ext, "fastag_species", lambda *x, **k:
                        calls.append(1) or [Evidence("organism", "Homo", 0.6, "data", "FASTag")])
    c = _fake_run()
    c.ev += cli._fastag_species(c)        # the ProSE organism search's call; ProSE then fails
    cli._fastag_stage(c, None, org_fixed=False)
    assert len(calls) == 1 and len([e for e in c.ev if e.method == "FASTag"]) == 1
    monkeypatch.setattr(cli.ext, "fastag_species", lambda *x, **k: calls.append(1) or 1 / 0)
    c = _fake_run()
    for _ in range(2):
        with pytest.raises(ZeroDivisionError):
            cli._fastag_species(c)
    assert len(calls) == 2                 # a failure is not retried either


def test_threads_cap_numeric_libraries(monkeypatch):
    from prose_auto import cli
    monkeypatch.setattr(os, "environ", {"MKL_NUM_THREADS": "2"})
    cli._cap_threads(["analyze", "run.mzML", "--threads", "4"])
    assert os.environ == {"MKL_NUM_THREADS": "2", "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4"}
    monkeypatch.setattr(os, "environ", {})
    cli._cap_threads(["analyze", "run.mzML", "--threads=0"])
    assert os.environ == {}


def test_search_windows_4x_precursor_on_high_res_ms2():
    tol = lambda ms2, pv, fv, fu: pp.to_prose(reconcile([
        Evidence("ms2_analyzer", ms2, 0.95, "metadata", "mzML"),
        Evidence("precursor_tolerance", {"value": pv, "unit": "ppm"}, 0.9, "search", "mini-search PSMs"),
        Evidence("fragment_tolerance", {"value": fv, "unit": fu}, 0.9, "search", "mini-search PSMs")]))["params"]
    P = tol("ORBITRAP", 5.0, 15.0, "ppm")
    assert P["Search:precursor:mass_tolerance_lower"] == 20.0 and P["Search:fragment:mass_tolerance"] == 30.0
    P = tol("ORBITRAP", 2.0, 5.0, "ppm")           # floors 10 / 20 ppm
    assert P["Search:precursor:mass_tolerance_lower"] == 10.0 and P["Search:fragment:mass_tolerance"] == 20.0
    P = tol("IT", 7.0, 0.5, "Da")                  # ion trap: 2x precursor, 0.35 Da fragment
    assert P["Search:precursor:mass_tolerance_lower"] == 14.0 and P["Search:fragment:mass_tolerance"] == 0.35
    astral = Evidence("instrument", "Orbitrap Astral", 0.9, "metadata", "mzML")
    tims = Evidence("instrument", "timsTOF Pro", 0.9, "metadata", "mzML")
    win = lambda ins, ms2, pv, fv: (lambda P: (P["Search:precursor:mass_tolerance_lower"],
                                               P["Search:fragment:mass_tolerance"]))(pp.to_prose(reconcile([
        ins, Evidence("ms2_analyzer", ms2, 0.95, "metadata", "mzML"),
        Evidence("precursor_tolerance", {"value": pv, "unit": "ppm"}, 0.9, "search", "mini-search PSMs"),
        Evidence("fragment_tolerance", {"value": fv, "unit": "ppm"}, 0.9, "search", "mini-search PSMs")]))["params"])
    assert win(astral, "ASTRAL", 3.0, 7.0) == (24.0, 14.0)       # Astral: 8x precursor, 2x fragment
    assert win(astral, "ASTRAL", 1.0, 3.0) == (10.0, 10.0)       # floors 10 / 10 ppm
    assert win(tims, "TOF", 22.0, 25.0) == (22.0, 25.0)          # TOF: 1x
    assert win(tims, "TOF", 5.0, 8.0) == (10.0, 15.0)            # floors 10 / 15 ppm


def test_strong_jev_outranks_disagreeing_enzyme_keywords():
    kw = Evidence("enzyme", "Arg-C", 0.5, "text", "keywords", "text mentions 'ArgC'")
    jev = lambda p: Evidence("enzyme", "Glu-C", 0.6, "llm", "jev:x+data", "", {"p": p})
    assert reconcile([kw, jev(0.93)])["enzyme"].value == "Glu-C"
    assert reconcile([kw, jev(0.6)])["enzyme"].value == "Arg-C"       # a weak Jev answer leaves the keyword
    tag = lambda v, m: Evidence("enzyme", v, min(0.8, 0.45 + m), "data", "FASTag termini", "", {"tag_margin": m})
    assert reconcile([tag("Trypsin", 0.6), jev(0.93)])["enzyme"].value == "Trypsin"      # tag 0.8 > Jev 0.6
    assert reconcile([kw, tag("Trypsin", 0.6)])["enzyme"].value == "Trypsin"   # keywords do not pick the member
    assert reconcile([kw, tag("Lys-C", 0.15)])["enzyme"].value == "Lys-C"                 # tag above the keywords
    assert reconcile([kw, tag("Lys-C", 0.05), jev(0.93)])["enzyme"].value == "Glu-C"      # weak tag: Jev
    assert reconcile([kw, tag("Lys-C", 0.05)])["enzyme"].value == "Arg-C"                 # weak tag: keywords
    assert reconcile([tag("Lys-C", 0.05)])["enzyme"].value == "Trypsin"                   # ... or the default
    # within the K/R family a Jev answer picks the member (tryptic Astral runs read Arg-C)
    tryp = Evidence("enzyme", "Trypsin", 0.6, "llm", "jev:x+data", "", {"p": 1.0})
    assert reconcile([tag("Arg-C", 0.4), tryp])["enzyme"].value == "Trypsin"
    assert reconcile([tag("Arg-C", 0.4), jev(0.93)])["enzyme"].value == "Arg-C"    # Jev outside the family: confidence
    assert reconcile([tag("Arg-C", 0.4)])["enzyme"].value == "Arg-C"
    user = Evidence("enzyme", "Asp-N", 0.75, "user", "keywords", "")
    assert reconcile([user, tag("Trypsin", 0.6)])["enzyme"].value == "Asp-N"              # the user's word first


def test_enzyme_keywords_and_file_name():
    enz = lambda t: [e.value for e in tx.extract(t) if e.parameter == "enzyme"]
    assert enz("Proteins were digested with Lysyl Endopeptidase overnight.") == ["Lys-C"]
    assert enz("Digestion with V8 protease.") == ["Glu-C"] and enz("Lys-N digestion") == ["Lys-N"]
    assert enz("stained with an anti-HLA-DR antibody; Glu-C digestion") == ["Glu-C"]
    assert enz("HLA class I ligands were eluted") == ["unspecific cleavage"]
    assert enz("a negative control with no enzyme; chymotrypsin digestion") == ["Chymotrypsin"]
    assert enz("lysates were digested with ArgC, AspN, Chymotrypsin, GluC, LysC and trypsin") == []
    fn = lambda n: [e.value for e in tx.from_file_name(n)]
    assert fn("/d/HeLa_GluC_HCD_1.mzML") == ["Glu-C"] and fn("Actin_AspN_4h.mzML") == ["Asp-N"]
    assert fn("x_2nd_LysC.mzML") == ["Lys-C"] and fn("HeLa_LysC_trypsin_1.mzML") == [] and fn("run1.mzML") == []


def test_fastag_termini_tag_profile_and_silac_gate(monkeypatch):
    from prose_auto import external as ext
    m = ext._RES
    tags = [m["F"]] * 300 + [m["K"]] * 20 + [m["K+8"]] * 20 + [m["R"]] * 5 + [m["R+10"]] * 15
    monkeypatch.setattr(ext, "_run", lambda cmd, log: None)
    monkeypatch.setattr(ext, "_tsv", lambda p: [{"gapped": "0", "evalue": "0.1", "cterm_mass": str(x),
                                                 "nterm_mass": "0"} for x in tags])
    ev, st = ext.fastag_termini("FASTag", "run.mzML")
    # a chymotrypsin profile, and heavy shares of 50% on 12% K/R C-termini are no SILAC
    assert [(e.parameter, e.value) for e in ev] == [("enzyme", "Chymotrypsin")] and st["tag_call"] == "Chymotrypsin"
    # N-terminal F (147.068 Da in nterm_mass) is no C-terminal E (b tag: E + water 147.053 Da)
    tags = [(m["K"], m["F"])] * 125 + [(m["R"], m["F"])] * 125
    monkeypatch.setattr(ext, "_tsv", lambda p: [{"gapped": "0", "evalue": "0.1", "cterm_mass": str(c),
                                                 "nterm_mass": str(n)} for c, n in tags])
    ev, st = ext.fastag_termini("FASTag", "run.mzML")
    assert [e.value for e in ev] == ["Trypsin"]
    # tryptic TMTpro: labelled K tags dominate; the Lys-C reading gets no margin (Jev and the texts decide)
    tags = [(m["K+TMTpro"], 0.0)] * 280 + [(m["R"], 0.0)] * 20
    monkeypatch.setattr(ext, "_tsv", lambda p: [{"gapped": "0", "evalue": "0.1", "cterm_mass": str(c),
                                                 "nterm_mass": str(n)} for c, n in tags])
    ev, st = ext.fastag_termini("FASTag", "run.mzML")
    assert st["tag_call"] == "Lys-C" and st["tag_margin"] == 0.0
    # an MS2 scan range from m/z 150 hides the y1 of K: no tag call
    ev, st = ext.fastag_termini("FASTag", "run.mzML", ms2_low_mz=150.0)
    assert "tag_call" not in st and not [e for e in ev if e.parameter == "enzyme"]


def test_protease_call_from_external_models():
    from prose_auto import external as ext
    cnt = lambda **k: {a: k.get(a, 0) for a in ext.TAG_AAS}
    none = cnt()
    call = lambda c, n=none: ext.protease_call(c, n)[0]
    assert call(cnt(K=150, R=150)) == "Trypsin"
    assert call(cnt(K=290, R=10)) == "Lys-C" and call(cnt(R=290, K=10)) == "Arg-C"
    assert call(cnt(E=280, D=20)) == "Glu-C"
    bgc = cnt(L=30, A=20, S=20, G=20, E=20, K=15, R=10, V=15)
    assert call(bgc, cnt(D=120, L=10, A=10, S=10)) == "Asp-N"
    assert ext.HLA_CLASS[call(cnt(L=60, V=40, F=20, Y=20, K=15, M=10))] == "I"
    assert ext.protease_call(cnt(K=50, R=40), none) is None                 # below 100 terminal tags
    model, other, margin = ext.protease_call(cnt(K=150, R=150), none)
    assert ext.TAG_MODELS[other] != "Trypsin" and margin > 0


def test_digest_votes_from_the_tag_profile():
    from prose_auto import cli
    tryp_prec = {"median_mass": 1500.0, "q90_mass": 2500.0, "charge_1": 0.0}
    hla_prec = {"median_mass": 1000.0, "q90_mass": 1500.0, "charge_1": 0.2}
    assert cli._digest_votes(tryp_prec, {"tag_call": "HLA-II"}, False, False)[1] == "II"
    assert cli._digest_votes(hla_prec, {"tag_call": "Chymotrypsin", "cterm_anchors_LVFYM": 0.5}, False, False)[1] is None
    assert cli._digest_votes(tryp_prec, {"tag_call": "HLA-I"}, False, True)[1] is None     # timsTOF: tags not valid
    assert cli._digest_votes(tryp_prec, {"tag_call": "HLA-II"}, True, False)[1] == "II"    # Orbitrap DIA pseudo-spectra
    assert cli._digest_votes(hla_prec, {"cterm_anchors_LVFYM": 0.5}, False, False)[1] == "I"
    assert cli._digest_votes(tryp_prec, {"cterm_anchors_LVFYM": 0.5}, False, False)[1] is None


def test_protease_competition_trypsin_family_from_c_terminal_residues():
    h = HypothesisTester.__new__(HypothesisTester)
    h.best_db, h.mods, h.log = ("x", "x.fasta"), ts.Mods(), lambda *a: None
    psm = lambda seqs: ([(i, 10.0, False, s, 0.0) for i, s in enumerate(seqs)], 0)
    res = {"Trypsin": psm(["PEPTIDEK"] * 95 + ["PEPTIDER"] * 5), "Lys-C": psm(["PEPTIDEK"] * 90)}
    h._search = lambda name, path, mods, enzyme="Trypsin": res.get(enzyme, psm(["PEPTIDE"] * 10))
    e = h.enzyme()[0]
    assert e.value == "Lys-C" and e.confidence > 0.9
    res["Trypsin"] = psm(["PEPTIDEK"] * 50 + ["PEPTIDER"] * 50)
    assert h.enzyme()[0].value == "Trypsin"
    assert ts.digest("AAAAAAAKDDDDDDDKEEEEEEE", "Lys-N", missed=0) == ["AAAAAAA", "KDDDDDDD", "KEEEEEEE"]


def test_organism_names_resolve_to_ncbi_taxa():
    from prose_auto import taxa
    tid = lambda n: (taxa.resolve(n) or (None,))[0]
    assert tid("yeast") == tid("Baker's yeast") == tid("Saccharomyces cerevisiae (baker's yeast)") == 4932
    assert tid("Candida albicans (yeast)") == 5476 and tid("Homo sapiens (human)") == tid("Homo_sapiens") == 9606
    assert tid("Physcomitrella patens") == 3218 and tid("Erysipelatoclostridium ramosum") == 1547   # old names
    assert tid("E. coli K-12") == 562 and tid("Plasmodium falciparum 3D7") == 5833                   # strains
    assert taxa.key("Mus musculus") == taxa.key("mouse") and taxa.key("Foo bar baz") == "foo bar"


def test_absent_stated_organism_and_study_level_mixture():
    from prose_auto.reconcile import organism_mix
    search = lambda second: Evidence("organism", "Homo_sapiens", 0.5, "search", "panel mini-search", "",
                                     {"Homo_sapiens": {"psms": 655}, "Candida_albicans": {"psms": second},
                                      "n_spectra": 2000})
    rec = [Evidence("organism", "Candida albicans (yeast)", 0.6, "repository", "pride"),
           Evidence("organism", "Homo sapiens (human)", 0.6, "repository", "pride")]
    d = reconcile(rec + [search(2)])["organism"]
    assert d.value == "Homo sapiens (human)" and d.status == "review"      # the record's first pick is absent
    assert reconcile(rec + [search(300)])["organism"].value == "Candida albicans (yeast)"
    jev = {"probabilities": {"organism": {"mixed species": 0.9}}}
    mix = organism_mix(rec + [search(2)], jev)
    assert not mix["suspected"] and mix["scope"] == "study" and "single-species" in mix["note"]
    assert organism_mix(rec + [search(300)], jev)["suspected"]
    tiny = Evidence("organism", "Homo_sapiens", 0.5, "search", "panel mini-search", "",
                    {"Homo_sapiens": {"psms": 655, "peptides": 2500000},
                     "Candida_albicans": {"psms": 0, "peptides": 167}, "n_spectra": 2000})
    assert reconcile(rec + [tiny])["organism"].value == "Candida albicans (yeast)"   # a 167-peptide database tests nothing


def test_stated_only_candidate_is_off_the_data_shortlist():
    st = lambda added: {"Rattus_norvegicus": {"psms": 343}, "Mus_musculus": {"psms": 316},
                        "Homo_sapiens": {"psms": 232}, "n_spectra": 2000, "stated_added": added}
    ev = lambda added: [Evidence("organism", "Homo sapiens (human)", 0.6, "repository", "pride"),
                        Evidence("organism", "Rattus norvegicus", 0.5, "text", "keywords"),
                        Evidence("organism", "Rattus norvegicus", 0.64, "data", "FASTag species"),
                        Evidence("organism", "Rattus_norvegicus", 0.43, "search", "panel mini-search",
                                 "Rattus_norvegicus explains 343 of 2000 spectra", st(added))]
    assert reconcile(ev(["Homo_sapiens"]))["organism"].value == "Rattus_norvegicus"
    assert reconcile(ev([]))["organism"].value == "Homo sapiens (human)"     # human on the shortlist keeps its place


def test_mix_indicator_ignores_crap_psms(tmp_path):
    a, b = tmp_path / "a.fasta", tmp_path / "b.fasta"
    a.write_text(">sp|P1|PROT_HUMAN Protein GN=PROT\nMMMMMMMR\n")
    b.write_text(">sp|P2|K1C9_BOVIN Keratin GN=KRT9\nLLLLLLLKEEEEEEEK\n>sp|P3|OTHER_BOVIN Other GN=OTH\nGGGGGGGK\n")
    h = HypothesisTester.__new__(HypothesisTester)
    h.scans, h.mods, h.log, h.best_db = [None] * 2000, ts.Mods(), lambda *x: None, None
    psm = lambda scans, pep: [(i, 10.0, False, pep, 0.0) for i in scans]
    res = {"a": psm(range(300), "MMMMMMMR"), "b": psm(range(1000, 1070), "LLLLLLLK") + psm(range(1100, 1130), "GGGGGGGK")}
    h._search = lambda name, path, mods, enzyme="Trypsin": (res[name], 1)
    ev = h.organism({"a": str(a), "b": str(b)})
    assert [e.value for e in ev] == ["a"] and ev[0].stats["b"]["unique_vs_best"] == 30    # keratin PSMs left out
    res["b"] += psm(range(1200, 1220), "GGGGGGGK")
    h._done = {}
    assert [e.value for e in h.organism({"a": str(a), "b": str(b)})] == ["a", "a + b"]      # 50 >= max(40, 36)


def test_negative_label_calls_agree_unless_they_negate_the_label_class():
    from prose_auto.reconcile import _label_compatible
    assert _label_compatible("no SILAC", "TMT10/11plex") and _label_compatible("no isobaric label", "label free")
    assert not _label_compatible("no SILAC", "SILAC (Lys8/Arg10)") and not _label_compatible("no isobaric label", "TMTpro (16/18plex)")
