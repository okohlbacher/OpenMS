"""Synthetic checks for the detectors fixed after the PRIDE validation (no test data needed)."""

import numpy as np

from prose_auto import detect_chemistry as chem
from prose_auto import prose_params as pp
from prose_auto.cli import _outside_panel
from prose_auto.evidence import Evidence
from prose_auto.reconcile import reconcile
from prose_auto.repository import sdrf_evidence
from prose_auto.spectra import Run, Scan

PROTON = 1.007276


def _envelope(mass, z, inten):
    mz0 = (mass + z * PROTON) / z
    return [(mz0 + k * chem.C13 / z, inten * f) for k, f in enumerate((1.0, 0.8, 0.4, 0.15))]


def _ms1_run(n_scans=60, n_pep=50, heavy=None, seed=1):
    """MS1 scans of tryptic-like peptides. Peptide masses follow the mass-defect rule (n * 1.000495 Da), so
    unlabelled spacings cluster near whole Daltons, as in real data. heavy: delta (Da) of a SILAC partner."""
    rng = np.random.default_rng(seed)
    run = Run(path="synthetic")
    for i in range(n_scans):
        peaks = []
        for _ in range(n_pep):
            nom = rng.integers(800, 3500)
            mass = nom * 1.000495 + rng.normal(0, 0.02)
            z = int(rng.choice([2, 3]))
            inten = rng.uniform(1e5, 1e7)
            peaks += _envelope(mass, z, inten)
            if heavy:
                peaks += _envelope(mass + heavy, z, inten * rng.uniform(0.5, 2.0))
        peaks.sort()
        mz = np.array([p[0] for p in peaks])
        it = np.array([p[1] for p in peaks])
        run.ms1.append(Scan(f"s{i}", 1, float(i), mz, it, scan_low=300, scan_high=2000))
    return run


def test_silac_no_false_call_on_label_free():
    e = chem.detect_silac(_ms1_run())[0]
    assert e.value == "no SILAC", e.stats["enrichment"]


def test_silac_real_pairs_are_called():
    e = chem.detect_silac(_ms1_run(heavy=chem.SILAC_DELTAS["Lys8"]))[0]
    assert e.value == "SILAC (Lys8/Arg10)", e.stats
    assert e.stats["distinct_light"]["Lys8"] >= 30


def test_silac_controls_keep_the_mass_defect():
    for d in chem.SILAC_DELTAS.values():
        cs = chem._silac_controls(d)
        assert cs and all(abs((c - d) / chem.C13 - round((c - d) / chem.C13)) < 1e-9 for c in cs)


def _ms2(n, nl_frac, charge=2, oxonium=0.0, seed=2):
    rng = np.random.default_rng(seed)
    run = Run(path="synthetic")
    for i in range(n):
        prec = rng.uniform(500, 1000)
        mz = list(rng.uniform(150, 1500, 60))
        if rng.random() < nl_frac:
            mz.append(prec - chem.H3PO4 / charge)
        if rng.random() < oxonium:
            mz.append(chem.DIAG["HexNAc_204"])
        mz = np.sort(np.array(mz))
        run.ms2.append(Scan(f"m{i}", 2, float(i), mz, np.full(mz.size, 1e6), precursor_mz=prec,
                            charge=charge, scan_low=100, scan_high=2000))
    return run


def test_phospho_from_neutral_loss_share():
    calls = {e.value for e in chem.detect_enrichment(_ms2(400, 0.06))}
    assert "Phospho (STY)" in calls
    assert {e.value for e in chem.detect_enrichment(_ms2(400, 0.0))} == {"none"}


def test_no_glyco_call_on_dia():
    run = _ms2(400, 0.0, oxonium=0.4)
    assert "Glyco (HexNAc oxonium)" in {e.value for e in chem.detect_enrichment(run)}
    assert "Glyco (HexNAc oxonium)" not in {e.value for e in chem.detect_enrichment(run, dia=True)}


def test_text_does_not_override_a_tested_enrichment():
    ev = [Evidence("enrichment", "none", 0.6, "data", "diagnostic ions"),
          Evidence("enrichment", "Phospho (STY)", 0.45, "text", "keywords"),
          Evidence("enrichment", "Phospho (STY)", 0.6, "llm", "cli")]
    d = reconcile(ev)["enrichment"]
    assert d.value == "none" and d.status == "review" and d.conflicts
    # DIA: the spectra could not test it (weak data evidence), so the text decides
    ev[0] = Evidence("enrichment", "none", 0.3, "data", "diagnostic ions")
    assert reconcile(ev)["enrichment"].value == "Phospho (STY)"


def test_sdrf_variable_mod_is_not_an_enrichment():
    sdrf = ("source name\tcharacteristics[organism]\tcomment[modification parameters]\n"
            "s1\tHomo sapiens\tNT=Phospho;TA=S,T,Y;MT=variable\n")
    assert not [e for e in sdrf_evidence(sdrf) if e.parameter == "enrichment"]
    sdrf = sdrf.replace("\n", "\tcharacteristics[enrichment process]\n", 1).rstrip("\n") + \
        "\tenrichment of phosphorylated protein\n"
    assert [e.value for e in sdrf_evidence(sdrf) if e.parameter == "enrichment"] == ["Phospho (STY)"]


def test_tmt6_with_isotope_peaks_is_not_tmt2():
    # PXD000001 pattern: 126, 128C, 130C, 131N plus their 13C isotopes at 127C and 129C; 127N and 129N unused
    ch = [chem.REPORTERS[k] for k in ("TMT126", "TMT127C", "TMT128C", "TMT129C", "TMT130C", "TMT131N")]
    rng = np.random.default_rng(3)
    run = Run(path="synthetic")
    for i in range(300):
        mz = np.sort(np.concatenate([ch, rng.uniform(150, 1500, 60)]))
        run.ms2.append(Scan(f"m{i}", 2, float(i), mz, np.full(mz.size, 1e6), precursor_mz=600.0, charge=2,
                            scan_low=100, scan_high=2000))
    labels = [e.value for e in chem.detect_labels(run) if e.method == "reporter ions"]
    assert labels == ["TMT6plex"], labels


def test_lysc_plus_trypsin_is_trypsin():
    sdrf = ("source name\tcomment[cleavage agent details]\tcomment[cleavage agent details]\n"
            "s1\tNT=Lys-C;AC=MS:1001309\tNT=Trypsin;AC=MS:1001251\n")
    assert [e.value for e in sdrf_evidence(sdrf) if e.parameter == "enzyme"] == ["Trypsin"]


def test_stated_organism_outside_the_panel_wins():
    stats = {"Homo_sapiens": {"psms": 300}, "Mus_musculus": {"psms": 120}}
    ev = [Evidence("organism", "Homo_sapiens", 0.8, "search", "panel mini-search", "", stats),
          Evidence("organism", "Gallus gallus", 0.7, "repository", "sdrf")]
    d = reconcile(ev)["organism"]
    assert d.value == "Gallus gallus" and d.status == "review"
    # a stated organism the search did test loses to a clear search result
    ev[1] = Evidence("organism", "Mus musculus", 0.7, "repository", "sdrf")
    assert reconcile(ev)["organism"].value == "Homo_sapiens"


def test_outside_panel_candidates():
    panel = {"Homo_sapiens": "h.fasta", "Escherichia_coli": "e.fasta"}
    ev = [Evidence("organism", "Pectobacterium", 0.84, "data", "FASTag species"),
          Evidence("organism", "Danio", 0.6, "data", "FASTag species"),
          Evidence("organism", "Gallus gallus", 0.7, "repository", "sdrf"),
          Evidence("organism", "Homo sapiens", 0.7, "repository", "pride")]
    assert _outside_panel(ev, panel) == ["Gallus gallus", "Pectobacterium"]


def test_search_windows_enzyme_and_calibration():
    ev = [Evidence("precursor_tolerance", {"value": 8, "unit": "ppm"}, 0.9, "search", "mini-search PSMs"),
          Evidence("fragment_tolerance", {"value": 6, "unit": "ppm"}, 0.9, "search", "mini-search PSMs"),
          Evidence("precursor_offset", {"value": 1.2, "unit": "ppm"}, 0.9, "search", "mini-search PSMs"),
          Evidence("enzyme", "Trypsin", 0.8, "search", "protease competition")]
    P = pp.to_prose(reconcile(ev))["params"]
    assert P["Search:precursor:mass_tolerance_lower"] == 16.0      # 2x measured, above the 10 ppm floor
    assert P["Search:fragment:mass_tolerance"] == 20.0             # 2x 6 = 12, floor 20 ppm
    assert P["Search:enzyme"] == "Trypsin/P"                       # the protease test cannot see the P rule
    assert P["Search:calibration:enabled"] == "false"              # small measured offset, high-res MS2
    # ion-trap MS2: 0.35 Da and calibration on; every trypsin source (here an SDRF-style "Trypsin") -> Trypsin/P
    ev[1] = Evidence("fragment_tolerance", {"value": 0.5, "unit": "Da"}, 0.9, "search", "mini-search PSMs")
    ev.append(Evidence("enzyme", "Trypsin", 0.7, "repository", "sdrf", "trypsin, not cleaving before proline"))
    P = pp.to_prose(reconcile(ev))["params"]
    assert (P["Search:fragment:mass_tolerance"], P["Search:fragment:mass_tolerance_unit"]) == (0.35, "Da")
    assert P["Search:calibration:enabled"] == "true" and P["Search:enzyme"] == "Trypsin/P"


def test_fragment_floor_per_analyzer():
    for ins, floor in (("Orbitrap Astral", 10.0), ("timsTOF Pro", 15.0), ("Q Exactive HF", 20.0)):
        ev = [Evidence("instrument", ins, 0.9, "metadata", "mzML"),
              Evidence("fragment_tolerance", {"value": 3, "unit": "ppm"}, 0.9, "search", "mini-search PSMs")]
        assert pp.to_prose(reconcile(ev))["params"]["Search:fragment:mass_tolerance"] == floor, ins


def test_two_tier_shortlist():
    from prose_auto import external as ext
    from prose_auto.cli import _organism_shortlist
    taxa = [{"name": n} for n in ("Bos taurus", "Macaca mulatta", "Homo sapiens", "Pan troglodytes", "Mus musculus")]
    ev = [Evidence("organism", "Macaca mulatta", 0.6, "data", "FASTag species", "", {"taxa": taxa}),
          Evidence("organism", "Macaca fascicularis", 0.7, "repository", "sdrf")]
    top = ext.fastag_shortlist(ev)
    assert top == ["Macaca mulatta", "Homo sapiens", "Pan troglodytes"]   # the reagent genus Bos is skipped
    got = _organism_shortlist(ev, {"Homo_sapiens": "h.fasta"}, top)
    assert got == ["Macaca fascicularis", "Macaca mulatta", "Homo sapiens", "Pan troglodytes"]


def test_dia_placeholder_charges_are_no_charge_range():
    from prose_auto import detect_instrument as inst
    run = Run(path="synthetic")
    for i in range(400):   # 20 repeating 25 Th windows, every spectrum with the converter's placeholder 2+
        c = 400 + 25 * (i % 20)
        run.ms2.append(Scan(f"w{i}", 2, float(i), np.array([200.0, 300.0]), np.array([1.0, 1.0]), precursor_mz=c,
                            charge=2, iso_lower=12.5, iso_upper=12.5, scan_low=100, scan_high=2000))
    cr = [e for e in inst.detect_acquisition(run) if e.parameter == "charge_range"]
    assert cr and cr[0].value == [2, 4] and cr[0].source == "default"


def test_not_in_panel_does_not_outrank_a_species_call():
    ev = [Evidence("organism", "not in panel", 0.5, "search", "panel mini-search"),
          Evidence("organism", "Homo sapiens", 0.65, "data", "FASTag species")]
    assert reconcile(ev)["organism"].value == "Homo sapiens"


def test_dia_spectra_do_not_test_enrichment():
    none = [e for e in chem.detect_enrichment(_ms2(400, 0.0), dia=True) if e.value == "none"]
    assert none and none[0].confidence < 0.6    # weak: records and text decide


def test_prose_organism_search_counts_discriminating_psms(tmp_path, monkeypatch):
    import pyopenms as oms
    from prose_auto import prose_runner as pr
    calls = []

    def fake_run(args, log):   # ProSE stand-in: PSMs (accessions -> species) depend on the variable mods searched
        calls.append(args)
        phospho = "Phospho (S)" in args
        hits = [["Mus_musculus|M1", "Homo_sapiens|H1"]] * 40 + [["Mus_musculus|M2"]] * 6 + [["CRAP|K1"]] * 30
        if phospho:
            hits += [["Homo_sapiens|H2"]] * 25
        peps = []
        for i, accs in enumerate(hits):
            h = oms.PeptideHit()
            h.setSequence(oms.AASequence.fromString("PEPTIDEK"))
            h.setMetaValue("target_decoy", "target")
            evs = []
            for a in accs:
                e = oms.PeptideEvidence()
                e.setProteinAccession(a)
                evs.append(e)
            h.setPeptideEvidences(evs)
            pid = oms.PeptideIdentification()
            pid.setIdentifier("r")
            pid.setHits([h])
            peps.append(pid)
        prot = oms.ProteinIdentification()
        prot.setIdentifier("r")
        ph = []
        for a in sorted({a for accs in hits for a in accs}):
            x = oms.ProteinHit()
            x.setAccession(a)
            ph.append(x)
        prot.setHits(ph)
        oms.IdXMLFile().store(args[args.index("-out_idxml") + 1], [prot], peps)

    monkeypatch.setattr(pr, "_run", fake_run)
    fa = tmp_path / "x.fasta"
    fa.write_text(">sp|P1|X\nPEPTIDEK\n")
    cands = {"Homo_sapiens": str(fa), "Mus_musculus": str(fa)}
    ev, win = pr.organism_with_prose("ProSE", "x.mzML", cands, ["Carbamidomethyl (C)"], ["Oxidation (M)"],
                                     (20, "ppm"), (20, "ppm"), contaminants=str(fa), log=lambda *a: None)
    # shared peptides and keratin do not count; mouse has 6 < 10 discriminating PSMs, so phospho is tried next
    assert win == "Homo_sapiens" and len(calls) == 2 and "Phospho (S)" in calls[1]
    assert ev[0].stats["steps"]["as decided"]["discriminating"] == {"Mus_musculus": 6}


def _digest_run(n, mass, charges, seed=4):
    rng = np.random.default_rng(seed)
    run = Run(path="synthetic")
    for i in range(n):
        z = int(rng.choice(charges))
        mz = np.sort(rng.uniform(150, 1500, 60))
        m = rng.normal(mass, 150)
        run.ms2.append(Scan(f"d{i}", 2, float(i), mz, np.full(mz.size, 1e6), precursor_mz=(m + z * PROTON) / z,
                            charge=z, scan_low=100, scan_high=2000))
    return run


def test_digest_hint_hla_class_i_only_from_short_precursors():
    assert chem.digest_hint(_digest_run(400, 950, [1, 2]))[0] == "HLA class I?"
    assert chem.digest_hint(_digest_run(400, 1700, [2, 3]))[0] is None          # tryptic
    assert chem.digest_hint(_digest_run(400, 950, [1, 2]), ms2_high_res=False)[0] is None


def test_prose_ladder_order_and_hla_evidence(tmp_path, monkeypatch):
    from prose_auto import prose_runner as pr
    seen = []

    def fake_run(args, log):   # PSMs only in the unspecific class I search
        seen.append(args[args.index("-Search:enzyme") + 1] + ("" if "-Search:peptide:max_size" not in args else
                    ":" + args[args.index("-Search:peptide:max_size") + 1]))
    monkeypatch.setattr(pr, "_run", fake_run)
    from collections import Counter
    monkeypatch.setattr(pr, "_species_counts", lambda out, sig=None: (
        (30, Counter({"Homo_sapiens": 30}), Counter({"Homo_sapiens": 30}), 0) if seen[-1] == "unspecific cleavage:14"
        else (0, Counter(), Counter(), 0)))
    fa = tmp_path / "x.fasta"
    fa.write_text(">sp|P1|X\nPEPTIDEK\n")
    kw = dict(contaminants=None, log=lambda *a: None)
    ev, win = pr.organism_with_prose("ProSE", "x", {"Homo_sapiens": str(fa)}, [], [], (20, "ppm"), (20, "ppm"), **kw)
    assert seen == ["Trypsin/P"] * 3 + ["unspecific cleavage:14"] and win == "Homo_sapiens"
    assert {e.parameter: e.value for e in ev if e.parameter != "organism"} == \
        {"enzyme": "unspecific cleavage", "peptide_length": [8, 14]}
    seen.clear()
    pr.organism_with_prose("ProSE", "x", {"Homo_sapiens": str(fa)}, [], [], (20, "ppm"), (20, "ppm"), hla_first=True, **kw)
    assert seen == ["unspecific cleavage:14"]     # the hint puts the HLA search first; it found the organism


def test_jev_cache(tmp_path, monkeypatch):
    from prose_auto import jev as J
    n = []
    monkeypatch.setenv("PROSE_AUTO_JEV_CACHE", str(tmp_path))
    j = J.Jev(key="k", transport=lambda body: n.append(1) or {"answers": {"q": {"choice": "a"}}})
    assert j.decide({"s": 1}, {"q": {}}) == j.decide({"s": 1}, {"q": {}}) == {"q": {"choice": "a"}}
    assert len(n) == 1 and all("k" not in open(f).read() for f in tmp_path.glob("*.json"))


def test_jev_sees_the_data_features():
    from prose_auto import schema as S
    from prose_auto.cli import _data_features
    ev = [Evidence("label", "TMT10/11plex", 0.9, "data", "reporter ions", "126-131 reporters in 94% of MS2"),
          Evidence("label", "TMT6plex", 0.6, "text", "keywords")]
    txt = _data_features(ev, {"median_mass": 950, "q90_mass": 1260, "charge_1": 0.4, "spectra": 5000})
    assert "TMT10/11plex" in txt and "reporters in 94%" in txt and "median 950 Da" in txt and "TMT6plex" not in txt
    state = S.study_state({"PRIDE description": "x" * 70000, "measured from the spectra": txt})
    assert state["measured from the spectra"] == txt          # never cut away by long texts
