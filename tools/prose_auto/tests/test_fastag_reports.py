"""The prose-auto policy on recorded FASTag 1.8.0 reports (-digest_out, -label_out, -massgap_out) of three public
runs; the expected values are the stored 0.1.3 decisions (v9d) of the same runs."""
import os

import pytest

from prose_auto import external as ext

D = os.path.join(os.path.dirname(__file__), "data", "fastag18")
rep = lambda run, kind: ext._report(os.path.join(D, f"{run}.{kind}.tsv"))


def test_tryptic_silac_phospho_run():   # PXD001186 SILACexpB_flowthr2 (Orbitrap Elite, phospho, Lys8/Arg10)
    ev, st = ext.termini_evidence(rep("PXD001186", "digest"), rep("PXD001186", "label"))
    assert [(e.parameter, e.value) for e in ev] == [("enzyme", "Trypsin"), ("label", "SILAC (Lys8/Arg10)")]
    assert st["tag_runner_up"] == "Lys-C" and st["tag_margin"] == pytest.approx(1.436, abs=0.006)
    assert ev[0].confidence == 0.8 and ev[1].confidence == 0.7 and st["cterm_KR"] == pytest.approx(0.978, abs=0.002)
    gap = {e.parameter: e for e in ext.massgap_evidence(rep("PXD001186", "massgap"))}
    assert gap["cys_alkylation"].value == "Carbamidomethyl (C)" and gap["cys_alkylation"].stats["counts"]["Carboxymethyl (C)"] == 4
    assert gap["variable_mods"].value == ["Phospho (S)", "Phospho (T)", "Phospho (Y)", "Label:2H(4) (K)",
                                          "Label:13C(6)15N(2) (K)", "Label:13C(6) (R)", "Gln->pyro-Glu (N-term Q)"]
    assert gap["enrichment"].value == "Phospho (STY)" and "label" not in gap   # no two SILAC gaps >= 8 %
    peak = gap["variable_mods"].stats["peaks"][6]
    assert peak["explained_by"] == ["Gln->pyro-Glu", "Phospho"] and peak["alternatives"][0] == ["Gln->pyro-Glu", "Sulfo"]


def test_hla_class_i_run():   # PXD006939 HLApI_RA957_2_R2
    ev, st = ext.termini_evidence(rep("PXD006939", "digest"), rep("PXD006939", "label"))
    assert [(e.parameter, e.value) for e in ev] == [("enzyme", "unspecific cleavage")]
    assert st["tag_call"] == "HLA-I" and st["hla_hint"] == "HLA class I?" and st["tag_runner_up"] == "Trypsin"
    gap = ext.massgap_evidence(rep("PXD006939", "massgap"))
    assert gap[0].value == "unknown" and gap[1].value == ["Trimethyl (K)", "GG (K)"]


def test_tmtpro_run_lys_c_reading_gets_no_margin():   # PXD037434 P20210201029_F8 (TMTpro, tryptic)
    ev, st = ext.termini_evidence(rep("PXD037434", "digest"), rep("PXD037434", "label"))
    assert [(e.parameter, e.value) for e in ev] == [("enzyme", "Lys-C"), ("label", "TMTpro (16/18plex)")]
    assert st["tag_margin"] == 0.0 and ev[0].confidence == 0.45 and st["cterm_tags"] == 10227


def test_no_call_and_few_tags():
    d = rep("PXD037434", "digest")
    d[("call", "status")], d[("call", "reason")] = "no_call", "ms2_first_peak"
    ev, st = ext.termini_evidence(d, rep("PXD037434", "label"))
    assert st["tag_nocall"] == "ms2_first_peak" and [e.parameter for e in ev] == ["label"]
    d[("count", "tot")] = "40"
    assert ext.termini_evidence(d, {}) == ([], {"tags": 102029, "cterm_tags": 40})


def test_fastag_version_gate(tmp_path):
    for v, ok in (("1.7.2", False), ("1.8.0", True), ("1.10.1", True)):
        exe = tmp_path / f"FASTag{v}"
        exe.write_text(f"#!/bin/sh\necho 'Version: {v} (OpenMS 3.7.0)'\n")
        exe.chmod(0o755)
        if ok:
            ext.require_fastag(str(exe))
        else:
            with pytest.raises(RuntimeError, match="FASTag >= 1.8.0"):
                ext.require_fastag(str(exe))
