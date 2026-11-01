"""Tests on OpenMS test data (run from tools/prose_auto: python -m pytest tests)."""

import json
import os

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
    assert P["Search:precursor:mass_tolerance_lower"] == 10  # 2x the measured 4 ppm, floor 10 ppm
    assert P["Search:calibration:enabled"] == "true"
    assert "<ITEMLIST" in pp.to_ini_snippet(P)


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
        return {"answers": {"organism": {"choice": "contradicts", "probabilities": {"contradicts": 0.85}}},
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
    issues = J.cross_check(jev, {"user's description": "HeLa"}, dec)
    assert issues and issues[0]["parameter"] == "organism" and issues[0]["severity"] == "high"
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
