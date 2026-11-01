"""prose-auto: propose ProSE search settings from the data itself.

    prose-auto panel proteomes/        (download the model-organism panel once)
    prose-auto analyze run.mzML [--panel proteomes/ | --fasta db.fasta]
                                [--description "HeLa, TMTpro, IAA" | --description @notes.txt]
                                [--methods methods.txt] [--accession PXD012345]
                                [--llm none|claude|codex|cli:<cmd>|openai:<model>] [--jev]
                                [--prose /path/to/ProSE] [--open-search] [-o outdir]
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import csv
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import delta_combos as DC
from . import detect_chemistry as chem
from . import detect_instrument as inst
from . import detect_tolerance as tol
from . import external as ext
from . import jev as J
from . import llm as L
from . import prose_params as pp
from . import repository as repo
from . import tagsearch as ts
from . import text_extract as tx
from .hypotheses import HypothesisTester
from .evidence import Evidence
from .reconcile import reconcile
from .spectra import load_mzml

LOW_RES = {"IT", "LIT", "PAULIONTRAP", "RADIALEJECTIONLINEARIONTRAP", "AXIALEJECTIONLINEARIONTRAP"}
MEASURED_SOURCES = ("data", "metadata", "search")
STATED_SOURCES = ("user", "repository", "text", "llm")
OUTSIDE_PANEL_MAX = 2   # organisms outside the panel fetched per run
SHORTLIST_MAX = 5       # tier-2 candidates
# isobaric label (value prefix) -> ts.LABEL_MASS key; the longer prefix first
LABEL_MASS_KEYS = (("TMTpro", "TMTpro"), ("TMT", "TMT"), ("iTRAQ8", "iTRAQ8plex"), ("iTRAQ", "iTRAQ4plex"))
# search evidence a new tier-2 organism winner invalidates
TIER2_REDO = ("organism", "precursor_offset", "precursor_tolerance", "fragment_offset", "fragment_tolerance",
              "cys_alkylation", "enzyme")


def _arg_text(v):
    if not v:
        return ""
    if v.startswith("@") and os.path.exists(v[1:]):
        return open(v[1:], encoding="utf-8", errors="replace").read()
    if os.path.exists(v):
        return open(v, encoding="utf-8", errors="replace").read()
    return v


def _first(evs, param):
    c = [e for e in evs if e.parameter == param]
    return max(c, key=lambda e: e.confidence) if c else None


def _value(evs, param, default):
    e = _first(evs, param)
    return e.value if e else default


def _unspecific(ev):
    return any(e.parameter == "enzyme" and e.value == "unspecific cleavage" and e.confidence >= 0.6 for e in ev)


def _genus(v):
    return str(v).replace("_", " ").split(" ")[0].lower()


def _species_key(name):
    """genus and species, lower case"""
    return " ".join(str(name).replace("_", " ").split()[:2]).lower()


def _fasta_name(a):
    return os.path.splitext(os.path.basename(a.fasta))[0]


def _panel(a, with_fasta=False):
    """the --panel databases by name, with the user's --fasta if asked"""
    panel = ts.load_panel(a.panel) if a.panel else {}
    return {**panel, _fasta_name(a): a.fasta} if with_fasta and a.fasta else panel


def _outside_panel(ev, panel):
    """Organisms worth fetching: stated by the user, a repository record or the text (confidence >= 0.5), or called
    by FASTag with confidence >= 0.75, whose genus no panel database covers. Stated organisms first."""
    have = {_genus(k) for k in panel}
    stated = [e for e in ev if e.parameter == "organism" and e.source in STATED_SOURCES and e.confidence >= 0.5]
    tagged = [e for e in ev if e.parameter == "organism" and e.method == "FASTag species" and e.confidence >= 0.75]
    out, seen = [], set()
    for e in sorted(stated, key=lambda e: -e.confidence) + sorted(tagged, key=lambda e: -e.confidence):
        g = _genus(e.value)
        if g and g not in have and g not in seen and g not in ("unknown", "not"):
            out.append(str(e.value))
            seen.add(g)
    return out[:OUTSIDE_PANEL_MAX]


def _val(v):
    return f"{v['value']} {v.get('unit', '')}".strip() if isinstance(v, dict) and "value" in v else v


def _data_features(ev, digest_stats, term_stats=None, per_parameter=4):
    """What the spectra themselves show, as one text for the readers (a separate source, labelled as measured, so
    they can weigh it against the authors' texts): every parameter's measured evidence (up to per_parameter, most
    confident first) with its reason, the provisional reading of the spectra alone, and the precursor mass and
    charge distribution."""
    lines = []
    measured = [e for e in ev if e.source in MEASURED_SOURCES]
    for p in dict.fromkeys(e.parameter for e in measured):
        for e in sorted((e for e in measured if e.parameter == p), key=lambda e: -e.confidence)[:per_parameter]:
            lines.append(f"{p}: {_val(e.value)} (confidence {e.confidence:.2f}; {e.source}/{e.method}"
                         f"{': ' + e.detail[:240] if e.detail else ''})")
    prov = [f"{k} = {_val(d.value)} (confidence {d.confidence:.2f})" for k, d in reconcile(measured).items()
            if d.source != "default" and d.value not in ("unknown", None)]
    if prov:
        lines.append("Provisional reading of the spectra alone (prose-auto, before the texts; the texts may correct "
                     "it): " + "; ".join(prov))
    if digest_stats:
        lines.append(f"precursor neutral mass: median {digest_stats['median_mass']} Da, 90th percentile "
                     f"{digest_stats['q90_mass']} Da; {digest_stats['charge_1']:.0%} singly charged "
                     f"({digest_stats['spectra']} charged MS2 spectra); tryptic peptides: median about 1200-2500 Da, "
                     "HLA class I ligands (8-12 residues): about 900-1200 Da")
    if term_stats and term_stats.get("cterm_tags"):
        lines.append(f"C-terminal residues of {term_stats['cterm_tags']} sequence tags: K/R {term_stats.get('cterm_KR')}"
                     f" (tryptic digests >= 0.86, HLA ligands about 0.3), hydrophobic L/V/F/Y/M "
                     f"{term_stats.get('cterm_anchors_LVFYM')} (HLA class I about 0.5, class II about 0.1); most frequent "
                     f"{term_stats.get('cterm_top')}; heavy Lys8 {term_stats.get('heavy_K8')}, heavy Arg10 "
                     f"{term_stats.get('heavy_R10')}")
    return "Measured from the raw spectra by prose-auto (not stated by the authors):\n" + "\n".join(lines)[:20000]


def _panel_match(name, panel):
    """the panel database of a species name (genus and species), if any"""
    key = _species_key(name)
    return next((k for k in panel if k.replace("_", " ").lower() == key), None)


def _organism_shortlist(ev, panel, fastag_top):
    """Tier-2 candidates: the stated organisms and confident FASTag calls the panel lacks (_outside_panel), then the
    FASTag top-ranked species (in the panel or not), without duplicates."""
    out, seen = [], set()
    for o in _outside_panel(ev, panel) + list(fastag_top):
        if _species_key(o) not in seen:
            out.append(str(o))
            seen.add(_species_key(o))
    return out[:SHORTLIST_MAX]


@dataclass
class _Run:
    """What the stages of one analysis share."""
    a: argparse.Namespace
    log: object
    base: str                 # output path stem
    spectra_file: str         # the MS2 spectra the detectors and searches see
    ev: list = field(default_factory=list)
    timings: dict = field(default_factory=dict)
    run: object = None
    acq: object = None        # acquisition as detected
    pseudo: bool = False      # DIAspeXtract pseudo-spectra replace the input
    search_acq: object = None
    ms2a: str = "ORBITRAP"
    hr1: bool = True
    hr2: bool = True

    @property
    def ftol(self):           # FASTag fragment tolerance
        return (20.0, "ppm") if self.hr2 else (0.3, "Da")


@contextlib.contextmanager
def _timed(c, key):
    t = time.time()
    yield
    c.timings[key] = round(time.time() - t, 1)


def _fastag_fraction(c):
    """The fraction of the MS2 FASTag tags: --fastag-subsample if given, else at most --fastag-spectra spectra (0 =
    all). Tagging the whole file took 25 min on a 77k-MS2 run (PXD028358)."""
    a = c.a
    if a.fastag_subsample:
        return a.fastag_subsample
    n = c.run.n_ms2_total
    return round(a.fastag_spectra / n, 4) if a.fastag_spectra and n > a.fastag_spectra else 0.0


def _fastag_species(c):
    a = c.a
    return ext.fastag_species(a.fastag, c.spectra_file, *c.ftol, threads=a.threads, subsample=_fastag_fraction(c),
                              log=c.log, taxonomy_dir=a.fastag_taxonomy,
                              rank="species" if a.fastag_taxonomy else "genus")


def _shortlist(c, panel):
    # ion-trap MS2: short tags match large (polyploid) proteomes by chance (wheat and salmon ranked first on mouse
    # and Arabidopsis LTQ runs), so the FASTag shortlist is used only with high-resolution MS2
    return _organism_shortlist(c.ev, panel, ext.fastag_shortlist(c.ev) if c.a.fastag_taxonomy and c.hr2 else [])


def _timstof_input(c):
    """Bruker timsTOF (pyopenms cannot read .d): only DIA goes through DIAspeXtract; ddaPASEF is converted to mzML
    by OpenMS FileConverter (one MS2 per precursor)."""
    a, log = c.a, c.log
    mode = ext.tims_acquisition(a.mzml)
    if mode == "diaPASEF":
        if not a.diaspextract:
            raise SystemExit("a diaPASEF .d input needs --diaspextract")
        log(f"[0/7] diaPASEF: DIAspeXtract {a.mzml} -> pseudo-MS/MS spectra")
        try:
            c.spectra_file = ext.diaspextract(a.diaspextract, a.mzml, c.base + ".pseudo.mzML", a.threads, log=log)
            acq = ("DIA (diaPASEF)", "analysis.tdf: diaPASEF frames; pseudo-spectra by DIAspeXtract")
        except RuntimeError as e:
            if getattr(e, "returncode", None) != ext.DIASPEXTRACT_DDA_INPUT:
                raise SystemExit(f"DIAspeXtract cannot read {a.mzml}: {str(e).strip()[-300:]}")
            log("  DIAspeXtract: the input is ddaPASEF (exit 11); converting it as DDA")
            mode = "ddaPASEF"
    if mode == "ddaPASEF":
        if not a.fileconverter:
            raise SystemExit("a ddaPASEF .d input needs --fileconverter (OpenMS FileConverter with timsTOF support)")
        log(f"[0/7] ddaPASEF: FileConverter {a.mzml} -> mzML")
        try:
            # the converted mzML (6-23 GB with profile MS1) is only an input: keep it out of the results
            tmp = tempfile.mkdtemp(prefix="prose_auto_ddapasef_")
            atexit.register(shutil.rmtree, tmp, True)
            c.spectra_file = ext.fileconverter(a.fileconverter, a.mzml,
                                               os.path.join(tmp, os.path.basename(c.base) + ".mzML"), a.threads, log=log)
        except RuntimeError as e:
            raise SystemExit(f"FileConverter cannot read {a.mzml}: {str(e).strip()[-300:]}")
        acq = ("DDA (ddaPASEF)", "analysis.tdf: ddaPASEF frames; converted by OpenMS FileConverter")
    elif mode != "diaPASEF":
        raise SystemExit(f"{a.mzml}: timsTOF acquisition {mode or 'unknown or mixed'} is not supported "
                         "(ddaPASEF and diaPASEF are)")
    c.ev.append(Evidence("acquisition", acq[0], 0.95, "metadata", "Bruker .d input", acq[1]))
    c.ev.append(Evidence("ion_mobility", True, 0.95, "metadata", "Bruker .d input", "timsTOF data"))
    name = ext.tims_instrument(a.mzml)
    if name:
        c.ev.append(Evidence("instrument", name, 0.95, "metadata", "analysis.tdf", f"InstrumentName {name}"))


def _pseudo_spectra(c):
    """DIA mzML: DIAspeXtract pseudo-MS/MS spectra for the DDA-style stages. DIAspeXtract needs ion mobility
    (diaPASEF); Orbitrap DIA gets a constant-mobility copy. Any failure keeps the spectra as they are."""
    a, log = c.a, c.log
    if not (str(c.acq).startswith("DIA") and a.diaspextract and c.spectra_file == a.mzml):
        return
    im = _first(c.ev, "ion_mobility")
    with_im = bool(im and im.value is True)
    log("  DIA mzML with ion mobility: DIAspeXtract pseudo-MS/MS spectra for the DDA-style stages" if with_im else
        "  DIA mzML without ion mobility: DIAspeXtract on a constant-mobility copy (retention time only)")
    try:
        if with_im:
            c.spectra_file = ext.diaspextract(a.diaspextract, a.mzml, c.base + ".pseudo.mzML", a.threads, log=log)
        else:
            # Orbitrap DIA: DIAspeXtract refuses data without ion mobility, so give it a constant 1/K0 and switch its
            # mobility steps off; it then traces precursors and fragments by retention time alone (PXD026600: 44k
            # pseudo-spectra, 7.2k PSMs at 1% entrapment FDP)
            im_copy = ext.with_constant_mobility(a.mzml, c.base + ".im.mzML")
            c.spectra_file = ext.diaspextract(a.diaspextract, im_copy, c.base + ".pseudo.mzML", a.threads,
                                              extra=ext.NO_MOBILITY_OPTIONS, log=log)
            os.remove(im_copy)
        c.run = load_mzml(c.spectra_file, max_ms2=a.max_ms2)
    except RuntimeError as e:
        log("  DIAspeXtract: the input is DDA (exit 11), continuing on the spectra as they are"
            if getattr(e, "returncode", None) == ext.DIASPEXTRACT_DDA_INPUT else
            f"  DIAspeXtract failed, continuing without pseudo-spectra: {str(e).strip()[-300:]}")


def _chemistry(c, raw):
    """Diagnostic ions, the digest hint and the FASTag termini. Returns (hint, hint_stats, term_stats)."""
    a, run, hr2 = c.a, c.run, c.hr2
    with _timed(c, "chemistry"):
        c.ev += chem.detect_labels(run, hr2) + chem.detect_enrichment(run, hr2, dia=str(c.acq).startswith("DIA")) \
            + chem.detect_cys_alkylation(run, hr2)
        if c.pseudo and raw is not run:   # pseudo-spectra carry no MS1: the SILAC pairs come from the DIA run itself
            c.ev += chem.detect_silac(raw)
        hint, hint_stats = chem.digest_hint(run, hr2)
    term_stats = {}
    if a.fastag and hr2:   # protease (C-terminal residues) and labels (N-terminal gaps) from FASTag k=4 tags
        with _timed(c, "termini"):
            try:
                term_ev, term_stats = ext.fastag_termini(a.fastag, c.spectra_file, threads=a.threads, log=c.log)
                # on DIA pseudo-spectra co-eluting fragments put +8/+10 Da gaps behind K/R by chance (32%/50% in the
                # label-free Orbitrap DIA run PXD066483): heavy termini count only on DDA spectra
                c.ev += [e for e in term_ev if not (c.pseudo and "SILAC" in str(e.value))]
            except Exception as e:
                c.log(f"  FASTag termini failed: {e}")
    return hint, hint_stats, term_stats


def _texts_and_readers(c, hint_stats, term_stats):
    """Repository records, the user's description and methods, then the readers (LLM, Jev) over all texts.
    Returns (study, backend, jev, llm_rejected, llm_text_conflicts, jev_report)."""
    a, log = c.a, c.log
    texts = {}
    if a.accession:
        e, texts = repo.repository_evidence(a.accession, log=log, fetch_paper=not a.no_paper, sdrf_use=a.sdrf)
        c.ev += e
    desc, methods = _arg_text(a.description), _arg_text(a.methods)
    if desc:
        c.ev += tx.extract(desc, source="user", base_conf=0.75)
    if methods:
        c.ev += tx.extract(methods, source="text", base_conf=0.55)
    for k in ("sample_protocol", "data_protocol", "description", "methods"):
        if texts.get(k):
            c.ev += tx.extract(texts[k], source="text", base_conf=0.5)
    study = {"user's description": desc, "methods section": methods,
             "PRIDE title": texts.get("title", ""), "PRIDE description": texts.get("description", ""),
             "PRIDE sample protocol": texts.get("sample_protocol", ""),
             "PRIDE data protocol": texts.get("data_protocol", ""),
             "paper methods": texts.get("methods", ""), "PRIDE record": texts.get("record", "")}
    backend = L.make_backend(a.llm)
    if backend or a.jev:   # only the readers use the whole SDRF
        study["SDRF"] = repo.sdrf_digest(texts.get("sdrf", ""), a.mzml.rstrip("/"))
    study = {k: v for k, v in study.items() if v}
    rejected, conflicts = [], []
    if backend and study:
        log(f"  LLM: {backend.name} (one multi-head request over {len(study)} texts)")
        e, rejected, conflicts = L.extract_study(backend, study, user=bool(desc))
        c.ev += e
        if a.llm_priors:
            c.ev += L.literature_priors(backend, _value(c.ev, "instrument", ""), c.acq,
                                        _value(c.ev, "fragmentation", ""), c.ms2a)
    jev = J.Jev() if a.jev else None
    jev_report = {}
    if jev and study:
        # Jev also sees the run and what the spectra show (marker ions, mass errors, the provisional reading)
        run_info = (f"data file {os.path.basename(a.mzml.rstrip('/'))}; " + "; ".join(
            f"{k} {v}" for k, v in c.run.summary().items() if k != "path" and v not in (None, "", []))
            + ("; DIA pseudo-MS/MS spectra by DIAspeXtract" if c.pseudo else ""))
        jev_study = {**study, "run": run_info,
                     "measured from the spectra": _data_features(c.ev, hint_stats, term_stats)}
        log(f"  Jev: {jev.name} (one multi-head request over {len(jev_study)} sources, one of them the data)")
        e, jev_report = J.read_study(jev, jev_study, user=bool(desc))
        c.ev += e
    return study, backend, jev, rejected, conflicts, jev_report


def _organism_from_metadata(c):
    """Organism from the metadata instead of the data: the user's FASTA, else the most confident stated organism
    (user, repository record, SDRF, text, Jev); the hypotheses search only that proteome, FASTag makes no species
    call and there is no tier 2. Nothing stated: the organism stays unknown and the mini-search is skipped.
    Returns the one-database panel ({} if none)."""
    a = c.a
    panel = _panel(a)
    top = _first([e for e in c.ev if e.parameter == "organism" and e.source in STATED_SOURCES
                  and str(e.value) not in ("not in panel", "unknown")], "organism")
    db = None
    if a.fasta:
        db = (_fasta_name(a), a.fasta)
        c.ev.append(Evidence("organism", db[0], 0.9, "user", "--fasta", f"the user's database {a.fasta}"))
    elif top:
        hit = _panel_match(top.value, panel)
        db = (hit, panel[hit]) if hit else (fetch_proteome(top.value, os.path.join(a.panel, "extra"), c.log)
                                            if a.panel else None)
    c.log(f"  organism from metadata: {db[0] if db else 'none stated'}")
    return {db[0]: db[1]} if db else {}


def _hla_first(c, hint, hint_stats, term_stats):
    """HLA ligands (no protease): a hint from the precursor masses, or stated (SDRF "unspecific cleavage"); the ProSE
    organism search then tries the unspecific search first, and only its result sets the enzyme."""
    hla = term_stats.get("hla_hint")
    first = "II" if hla == "HLA class II?" and not hint else "I" if hint or hla or _unspecific(c.ev) else None
    if first:
        c.log(f"  HLA class {first} ligands? ({hint or hla or 'stated'}; {hint_stats}): "
              "the unspecific search goes first")
    return first


def _organism_from_prose(c, hla_first):
    """Organism from one ProSE search: panel + stated organisms outside it + the FASTag shortlist, concatenated; the
    winner by discriminating PSMs (prose_runner.organism_with_prose). The hypotheses then search the winner.
    Returns the winner's one-database panel, or None if ProSE failed (the panel mini-search decides then)."""
    from .prose_runner import find_prose, load_signatures, organism_with_prose
    a, log, hr2 = c.a, c.log, c.hr2
    org_panel = None
    with _timed(c, "organism_prose"):
        panel = _panel(a, with_fasta=True)
        sig = a.organism_panel   # signature-protein panel: covers the whole reference set, no FASTag shortlist
        if sig:
            with open(os.path.join(sig, "species.tsv")) as fh:
                cands = {r["species"]: r["proteome"] for r in csv.DictReader(fh, delimiter="\t")}
        else:
            cands = dict(panel)
            if a.fastag:
                try:   # ion-trap tags match large proteomes by chance
                    c.ev += [e for e in _fastag_species(c) if hr2 or not a.fastag_taxonomy]
                except Exception as e:
                    log(f"  FASTag failed: {e}")
            for o in _shortlist(c, panel):
                if not _panel_match(o, panel) and a.panel:
                    got = fetch_proteome(o, os.path.join(a.panel, "extra"), log)
                    if got and os.path.getsize(got[1]) > 100000:   # tiny files are wrong (virus) proteomes
                        cands[got[0]] = got[1]
        lab = _first([e for e in c.ev if e.parameter == "label" and e.value not in ("no isobaric label", "no SILAC",
                                                                                    "unknown", "label free")], "label")
        enr = _first([e for e in c.ev if e.parameter == "enrichment" and e.confidence >= 0.5], "enrichment")
        fixed = ["Carbamidomethyl (C)"] + pp.LABEL_MODS.get(lab.value if lab else "", [])
        var = (["Oxidation (M)"] + pp.SILAC_VARIABLE.get(lab.value if lab else "", [])
               + pp.ENRICHMENT_MODS.get(enr.value if enr else "", []))
        log(f"  organism: one ProSE search against {len(cands)} proteomes")
        try:
            stated = [_panel_match(e.value, cands) or str(e.value).replace(" ", "_") for e in
                      sorted((e for e in c.ev if e.parameter == "organism" and e.confidence >= 0.5),
                             key=lambda e: -e.confidence)]
            oe, win = organism_with_prose(find_prose(a.prose_bin), c.spectra_file, cands, fixed, var,
                                          (20.0, "ppm") if c.hr1 else (1.0, "Da"), (20.0, "ppm") if hr2 else (0.4, "Da"),
                                          contaminants=a.contaminants, threads=a.threads, hla_first=hla_first,
                                          preferred=stated + ["Homo_sapiens", "Mus_musculus"],
                                          panel_db=os.path.join(sig, "sigpanel.fasta") if sig else None,
                                          signatures=load_signatures(os.path.join(sig, "signatures.tsv.gz"))
                                          if sig else None, log=log)
            c.ev += oe
            org_panel = {win: cands[win]} if win else {}
        except Exception as e:
            log(f"  ProSE organism search failed, panel mini-search instead: {str(e)[-300:]}")
    return org_panel


def _mini_search(c, panel, org_fixed, unspec):
    """Mini-search hypotheses (DDA only: DIA spectra have no single precursor). Returns the HypothesisTester or
    None. With the organism fixed (metadata, ProSE) its organism evidence is dropped."""
    a, log, hr2 = c.a, c.log, c.hr2
    dia = str(c.search_acq).startswith("DIA")
    if not panel or dia or a.no_search:
        log("[6/7] mini-search skipped" + (" (DIA without pseudo-spectra)" if dia else
                                           " (no --panel/--fasta)" if not panel else ""))
        return None
    log(f"[6/7] mini-search on {min(a.spectra, len(c.run.ms2))} spectra against {len(panel)} database(s)")
    with _timed(c, "mini_search"):
        lab = _first([e for e in c.ev if e.parameter == "label" and e.source == "data"
                      and e.value not in ("no isobaric label", "no SILAC", "unknown")], "label")
        mods = ts.Mods()
        key = next((k for p, k in LABEL_MASS_KEYS if str(lab.value).startswith(p)), None) if lab else None
        if key:
            mods.k = mods.nterm = ts.LABEL_MASS[key]
        h = HypothesisTester(c.run, 20.0 if hr2 else 0.4, hr2, prec_ppm=20.0 if c.hr1 else 500.0,
                             n_spectra=a.spectra, mods=mods, log=log, sample=a.sample)
        oe = h.organism(panel)
        if not org_fixed:
            c.ev += oe
        if h.best_db:
            c.ev += h.accuracy() + h.alkylation()
            if not a.skip_enzyme and not unspec:   # the protease competition knows no unspecific digest
                c.ev += h.enzyme()
    return h


def _fastag_stage(c, h, org_fixed):
    """FASTag species call (unless the organism is fixed), then the mass-gap histogram against the winning database:
    Cys alkylation and modification combinations."""
    a, log = c.a, c.log
    ftol, funit = c.ftol
    with _timed(c, "fastag"):
        log("  FASTag: genus call from sequence tags")
        try:
            fev = [] if org_fixed else _fastag_species(c)
            if a.fastag_taxonomy and not c.hr2:  # ion-trap tags hit large proteomes by chance (wheat, salmon first)
                for e in fev:
                    e.confidence = min(e.confidence, 0.2)
            c.ev += fev
            db = (h.best_db[1] if h is not None and h.best_db else None) or a.fasta
            if db:
                log(f"  FASTag: mass-gap histogram against {os.path.basename(db)} without fixed modifications")
                alk = ext.fastag_alkylation(a.fastag, c.spectra_file, db, ftol, funit, threads=a.threads, log=log,
                                            subsample=_fastag_fraction(c))
                c.ev += alk
                # the same gap histogram, explained as modification combinations (variable mods, enrichment)
                c.ev += DC.detect(alk[0].stats.get("hist", []) if alk else [], 0.02 if funit == "ppm" else 0.5)
        except Exception as e:
            log(f"  FASTag failed: {e}")


def _tier2(c, h, panel, unspec):
    """Organism, tier 2: the FASTag species ranking (extended index) gives a top-3 shortlist; with the stated
    organisms and confident FASTag calls the panel lacks, their reference proteomes are fetched (cached in
    <panel>/extra) and searched against the panel winner, so the nearest panel organism does not win by default."""
    a, log = c.a, c.log
    shortlist = _shortlist(c, panel)
    if not (shortlist and h is not None and a.panel):
        return
    with _timed(c, "organism_tier2"):
        dbs = {}
        for o in shortlist:
            hit = _panel_match(o, panel)
            p = (hit, panel[hit]) if hit else fetch_proteome(o, os.path.join(a.panel, "extra"), log)
            if p:
                dbs[p[0]] = p[1]
        prev = h.best_db[0] if h.best_db else None
        if prev:
            dbs[prev] = h.best_db[1]
        if len(dbs) > 1 or (dbs and prev is None):
            log(f"  organism tier 2: testing {', '.join(dbs)}")
            new = h.organism(dbs)
            if h.best_db and h.best_db[0] != prev:  # a new winner: redo the stages that used the old one
                c.ev = [e for e in c.ev if not (e.source == "search" and e.parameter in TIER2_REDO)] + new
                c.ev += h.accuracy() + h.alkylation() + ([] if a.skip_enzyme or unspec else h.enzyme())
            else:  # the winner holds; the new search evidence records which candidates were tested
                c.ev = [e for e in c.ev if not (e.source == "search" and e.parameter == "organism")] + new


def _confirm_with_prose(c, decisions, prose, panel, h):
    """A ProSE subset search on the proposed settings, on the spectra the settings came from (converted or
    pseudo-spectra) and the decided database (a tier-2 winner is not in the panel); on failure the data-only
    result stays."""
    from .prose_runner import confirm_with_prose, find_prose
    a = c.a
    exe = find_prose(a.prose)
    org = decisions["organism"].value
    db = a.fasta or (h.best_db[1] if h is not None and h.best_db and h.best_db[0] == org else None) \
        or (panel.get(org) if panel else None)
    if exe and db:
        c.log(f"  confirming with ProSE ({exe})")
        try:
            c.ev += confirm_with_prose(exe, c.spectra_file, db, pp.to_cli(prose["params"]), open_search=a.open_search,
                                       log=c.log)
            decisions = reconcile(c.ev)
            prose = pp.to_prose(decisions)
        except Exception as e:
            c.log(f"  ProSE confirmation failed: {e}")
    return decisions, prose


def analyze(a, log=print):
    t0 = time.time()
    if not a.diaspextract:   # DIA pseudo-DDA spectra automatically when DIAspeXtract is installed
        a.diaspextract = (os.environ.get("PROSE_AUTO_DIASPEXTRACT") or shutil.which("DIAspeXtract")
                          or shutil.which("diaspextract"))
    if not getattr(a, "fileconverter", None):
        a.fileconverter = os.environ.get("PROSE_AUTO_FILECONVERTER") or shutil.which("FileConverter")
    os.makedirs(a.out, exist_ok=True)
    c = _Run(a, log, os.path.join(a.out, os.path.splitext(os.path.basename(a.mzml.rstrip("/")))[0]), a.mzml)
    if a.mzml.rstrip("/").lower().endswith(".d"):
        _timstof_input(c)
    log(f"[1/7] reading {c.spectra_file}")
    # raw: the run as read; its MS1 serves the SILAC pair test when DIA pseudo-spectra replace it
    c.run = raw = load_mzml(c.spectra_file, max_ms2=a.max_ms2)
    c.timings["read"] = round(time.time() - t0, 1)

    log("[2/7] instrument, fragmentation, acquisition mode")
    c.ev += inst.detect_instrument(c.run)
    if c.spectra_file == a.mzml:
        c.ev += inst.detect_acquisition(c.run)
    c.acq = _first(c.ev, "acquisition").value
    _pseudo_spectra(c)
    c.pseudo = c.spectra_file != a.mzml
    if c.pseudo:  # pseudo-spectra carry DIAspeXtract's charge calls: measure the range on them
        cr = inst.charge_range(c.run.ms2)
        if cr:
            c.ev = [e for e in c.ev if e.parameter != "charge_range"] + cr
    c.search_acq = "DDA" if c.pseudo else c.acq      # pseudo-spectra have one precursor each
    c.ms2a = _value(c.ev, "ms2_analyzer", "ORBITRAP")
    c.hr1, c.hr2 = _value(c.ev, "ms1_analyzer", "ORBITRAP") not in LOW_RES, c.ms2a not in LOW_RES

    log("[3/7] mass accuracy from repeated ions and known ions")
    with _timed(c, "tolerance"):
        c.ev += tol.detect_tolerances(c.run, c.search_acq, ms2_high_res=c.hr2, ms1_high_res=c.hr1)
    log("[4/7] labels, enrichment, Cys alkylation (diagnostic ions)")
    hint, hint_stats, term_stats = _chemistry(c, raw)
    log("[5/7] repository records and text")
    with _timed(c, "text"):
        study, backend, jev, llm_rejected, llm_text_conflicts, jev_report = _texts_and_readers(c, hint_stats,
                                                                                               term_stats)

    # organism: from the metadata or one ProSE search fixes it (org_panel = the one database); otherwise the panel
    # mini-search, FASTag and tier 2 decide
    org_panel = _organism_from_metadata(c) if a.organism_source == "metadata" else None
    hla_first = _hla_first(c, hint, hint_stats, term_stats)
    if a.organism_source == "prose" and not str(c.search_acq).startswith("DIA"):
        org_panel = _organism_from_prose(c, hla_first)
    org_fixed = org_panel is not None
    unspec = _unspecific(c.ev)
    panel = org_panel if org_fixed else _panel(a, with_fasta=True)
    h = _mini_search(c, panel, org_fixed, unspec)
    if a.fastag:
        _fastag_stage(c, h, org_fixed)
    if not org_fixed:
        _tier2(c, h, panel, unspec)

    log("[7/7] reconciling")
    decisions = reconcile(c.ev)
    prose = pp.to_prose(decisions)
    if a.prose is not None:   # a bare --prose means ProSE from PATH
        decisions, prose = _confirm_with_prose(c, decisions, prose, panel, h)
    review = L.review(backend, decisions) if backend and a.llm_review else []
    # the texts alone: the data cannot confirm themselves
    jev_issues = J.cross_check(jev, study, decisions) if jev and study else []
    consistency = J.consistency(decisions)
    c.timings["total"] = round(time.time() - t0, 1)
    return {
        "tool": "prose-auto 0.1 (prototype)",
        "input": {**c.run.summary(), "given": a.mzml, "pseudo_spectra": c.spectra_file if c.pseudo else None},
        "decisions": {k: d.to_dict() for k, d in decisions.items()},
        "prose": prose,
        "prose_cli": pp.to_cli(prose["params"]),
        "sdrf": pp.to_sdrf_technical(decisions),
        "llm": {"backend": backend.name if backend else None, "rejected": llm_rejected, "review": review},
        "jev": {"model": jev.name if jev else None, "cross_check": jev_issues, "study": jev_report,
                "calls": jev.calls if jev else 0, "cost_usd": round(jev.cost_usd, 5) if jev else 0},
        "consistency": consistency,
        "text_conflicts": llm_text_conflicts + (jev_report.get("text_rules", []) if jev_report else []),
        "timings_s": c.timings,
        "digest_hint": {"hint": hint, **hint_stats, "termini": term_stats},
    }


STATUS = {"auto": "auto", "review": "REVIEW", "default": "default", "unknown": "unknown"}


def _fmt(v):
    if isinstance(v, dict) and "value" in v:
        return f"{v['value']} {v.get('unit', '')}".strip()
    if isinstance(v, dict):
        return ", ".join(f"{k}={v[k]}" for k in list(v)[:4] if k != "windows")
    if isinstance(v, list):
        return ", ".join(str(x) for x in v[:6])
    return str(v)


def markdown(rep):
    i = rep["input"]
    L_ = [f"# prose-auto report: {os.path.basename(i['path'])}", "",
          f"{i['instrument'] or 'unknown instrument'}, {i['ms1']} MS1 / {i['ms2']} MS2 / {i['ms3']} MS3 spectra. "
          f"Run time {rep['timings_s'].get('total')} s.", "",
          "| Parameter | Value | Confidence | Status | From |", "|---|---|---|---|---|"]
    order = ["acquisition", "instrument", "ms1_analyzer", "ms2_analyzer", "fragmentation", "precursor_tolerance",
             "precursor_offset", "fragment_tolerance", "fragment_offset", "charge_range", "label", "cys_alkylation",
             "enrichment", "enzyme", "organism", "variable_mods", "dia_windows", "collision_energy",
             "instrument_class", "ion_mobility"]
    ds = rep["decisions"]
    keys = [k for k in order if k in ds] + [k for k in ds if k not in order]
    for k in keys:
        d = ds[k]
        L_.append(f"| {d['label']} | {_fmt(d['value'])} | {d['confidence']:.2f} | {STATUS[d['status']]} | {d['source']} |")
    L_ += ["", "## Conflicts and notes", ""]
    n = len(L_)
    for d in ds.values():
        L_ += [f"- **{d['label']}**: {c}" for c in d["conflicts"]]
    L_ += [f"- {x}" for x in rep["prose"]["notes"]]
    L_ += [f"- Consistency ({r.get('severity')}): **{r.get('parameter')}** {r.get('issue')}"
           for r in rep.get("consistency", [])]
    L_ += [f"- Texts disagree with each other ({r.get('kind', '')}): {r.get('message') or r.get('issue')}"
           for r in rep.get("text_conflicts", [])]
    L_ += [f"- Jev cross-check ({r.get('severity')}): **{r.get('parameter')}** {r.get('issue')}"
           for r in rep.get("jev", {}).get("cross_check", [])]
    L_ += [f"- LLM review ({r.get('severity')}): **{r.get('parameter')}** {r.get('issue')}"
           for r in rep["llm"]["review"]]
    if len(L_) == n:
        L_.append("- none")
    L_ += ["", "## ProSE parameters", "", "```", "ProSE -in <mzML> -database <fasta> -out <idXML> \\",
           "  " + " ".join(f'"{x}"' if " " in x or not x else x for x in rep["prose_cli"]), "```", "",
           "## Evidence", ""]
    for k in keys:
        d = ds[k]
        L_.append(f"**{d['label']}** = {_fmt(d['value'])}")
        for e in d["evidence"]:
            q = f' — "{e["quote"]}"' if e.get("quote") else ""
            L_.append(f"- [{e['source']}/{e['method']}] {_fmt(e['value'])} ({e['confidence']:.2f}): {e['detail']}{q}")
        L_.append("")
    if rep["llm"]["rejected"]:
        L_ += ["## LLM statements rejected by the quote check", ""]
        for r in rep["llm"]["rejected"][:20]:
            L_.append(f"- {r.get('source', '')}: {r.get('parameter')} = {r.get('value')} ({r.get('why', r.get('error'))})")
    return "\n".join(L_) + "\n"


MODEL_PROTEOMES = {
    "Homo_sapiens": "UP000005640", "Mus_musculus": "UP000000589", "Rattus_norvegicus": "UP000002494",
    "Bos_taurus": "UP000009136", "Sus_scrofa": "UP000008227", "Danio_rerio": "UP000000437",
    "Drosophila_melanogaster": "UP000000803", "Caenorhabditis_elegans": "UP000001940",
    "Saccharomyces_cerevisiae": "UP000002311", "Arabidopsis_thaliana": "UP000006548",
    "Escherichia_coli": "UP000000625", "Bacillus_subtilis": "UP000001570",
}


def _download(url, dst, log=print, attempts=5):
    """UniProt's REST endpoints return sporadic HTTP 500s: retry, and never leave a partial file."""
    part = f"{dst}.{os.getpid()}.part"  # parallel analyses may fetch the same proteome
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=600) as r, open(part, "wb") as fh:
                shutil.copyfileobj(r, fh, 1 << 20)
                want = r.headers.get("Content-Length")
                if want and fh.tell() != int(want):   # a cut connection must not become a cached database
                    raise OSError(f"truncated download: {fh.tell()} of {want} bytes")
        except BaseException as e:
            with contextlib.suppress(OSError):
                os.remove(part)
            if not isinstance(e, OSError):  # URLError and HTTPError are OSErrors
                raise
            log(f"    attempt {attempt + 1} failed: {e}")
            time.sleep(10 * 2 ** attempt)
            continue
        os.replace(part, dst)
        return True
    return False


def fetch_panel(out, reviewed=True, log=print):
    """Download the model-organism panel (UniProt reference proteomes)."""
    os.makedirs(out, exist_ok=True)
    for name, up in MODEL_PROTEOMES.items():
        q = f"(proteome:{up})" + ("+AND+(reviewed:true)" if reviewed else "")
        dst = os.path.join(out, f"{name}.fasta")
        if os.path.getsize(dst) if os.path.exists(dst) else 0:
            log(f"  {name}: present, skipped")
            continue
        log(f"  {name} ({up}) -> {dst}")
        if not _download(f"https://rest.uniprot.org/uniprotkb/stream?format=fasta&query={q}", dst, log):
            log(f"  {name}: giving up; the panel lacks this organism")


def fetch_proteome(organism, cache, log=print):
    """UniProt reference proteome of an organism outside the panel (species name, or a genus: then the first
    reference proteome UniProt lists for it), all entries (non-model organisms have few reviewed ones), cached as
    <cache>/<Genus_species>.fasta. Returns (name, path) or None."""
    words = str(organism).replace("_", " ").split()
    if not words or not words[0][:1].isupper():
        return None
    query = " ".join(words[:2]) if len(words) > 1 and words[1].islower() and words[1].isalpha() else words[0]
    os.makedirs(cache, exist_ok=True)
    # taxonomy_name matches a genus or a species with all its strains; the proteome_type query field returns nothing,
    # so reference proteomes are picked from the results
    q = urllib.parse.quote(f'taxonomy_name:"{query}"')
    url = f"https://rest.uniprot.org/proteomes/search?query={q}&fields=upid,organism&format=json&size=25"
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            hits = [h for h in json.load(r).get("results", []) if h.get("proteomeType", "").startswith("Reference")]
    except (OSError, ValueError) as e:
        log(f"  proteome lookup for {query} failed: {e}")
        return None
    if not hits:
        log(f"  no UniProt reference proteome for {query}")
        return None
    up, sci = hits[0]["id"], hits[0]["taxonomy"]["scientificName"]
    name = "_".join(sci.split()[:2])
    dst = os.path.join(cache, f"{name}.fasta")
    if not (os.path.exists(dst) and os.path.getsize(dst)):
        log(f"  fetching {sci} reference proteome {up} for {organism}")
        if not _download(f"https://rest.uniprot.org/uniprotkb/stream?format=fasta&query=(proteome:{up})", dst, log):
            return None
    return name, dst


def main(argv=None):
    ap = argparse.ArgumentParser(prog="prose-auto", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    an = sub.add_parser("analyze", help="propose search settings for one mzML file")
    an.add_argument("mzml")
    an.add_argument("--panel", help="directory of model-organism FASTA files (one per organism)")
    an.add_argument("--fasta", help="the user's database; searched in addition to the panel")
    an.add_argument("--description", help="free-text description of the experiment, or @file")
    an.add_argument("--methods", help="methods section (file or text)")
    an.add_argument("--accession", help="PXD/MSV accession: PRIDE, MassIVE and curated SDRF records")
    an.add_argument("--no-paper", action="store_true", help="do not fetch the paper from Europe PMC")
    an.add_argument("--llm", default="none", help="none | claude | codex | cli:<cmd> | openai:<model>")
    an.add_argument("--jev", action="store_true",
                    help="classify the texts with Jev and cross-check the settings (JEV_API_KEY)")
    an.add_argument("--llm-priors", action="store_true", help="ask the LLM for literature tolerance priors")
    an.add_argument("--llm-review", action="store_true", help="let the LLM review the final settings")
    an.add_argument("--prose", nargs="?", const="", help="confirm with a ProSE subset search (path or PATH)")
    an.add_argument("--open-search", action="store_true", help="with --prose: also run an open search")
    an.add_argument("--fastag", help="FASTag executable: genus call and Cys alkylation from sequence tags")
    an.add_argument("--fastag-taxonomy", default=os.environ.get("PROSE_AUTO_FASTAG_TAXONOMY"),
                    help="extended FASTag index directory (tax_k7.taxdb, nodes.dmp, names.dmp): species-rank "
                         "ranking and the two-tier organism test (default $PROSE_AUTO_FASTAG_TAXONOMY)")
    an.add_argument("--fastag-subsample", type=float, default=0.0,
                    help="fraction of the MS2 FASTag tags (0: --fastag-spectra decides)")
    an.add_argument("--fastag-spectra", type=int, default=20000,
                    help="at most this many MS2 for the FASTag species and mass-gap calls (0 = all)")
    an.add_argument("--diaspextract", help="DIAspeXtract executable: pseudo-MS/MS spectra for DIA / .d input "
                    "(default: PROSE_AUTO_DIASPEXTRACT, else DIAspeXtract on PATH)")
    an.add_argument("--fileconverter", help="OpenMS FileConverter with timsTOF support, for ddaPASEF .d input "
                    "(default: PROSE_AUTO_FILECONVERTER, else FileConverter on PATH)")
    an.add_argument("--threads", type=int, default=0, help="threads for external tools (0 = their default)")
    an.add_argument("--spectra", type=int, default=2000, help="MS2 spectra for the mini-search")
    an.add_argument("--sample", choices=("random", "top"), default="random",
                    help="mini-search spectra: a random sample (default; more correct organism calls in the sampling "
                         "study) or the highest-TIC ones")
    an.add_argument("--max-ms2", type=int, default=20000, help="MS2 spectra read for the detectors")
    an.add_argument("--no-search", action="store_true", help="skip the mini-search")
    an.add_argument("--organism-source", choices=("data", "prose", "metadata"), default="data",
                    help="data: organism from panel mini-search, FASTag and tier 2; prose: one ProSE search against "
                         "panel + shortlist (ProSE from --prose-bin or PATH); metadata: from --fasta or the "
                         "stated organism only (user, repository, SDRF, text, Jev)")
    an.add_argument("--prose-bin", help="ProSE executable for --organism-source prose (default: ProSE on PATH)")
    an.add_argument("--organism-panel", help="signature-protein panel directory (build_sigpanel.py) for "
                    "--organism-source prose: one search covers the whole reference set")
    an.add_argument("--contaminants", help="contaminant FASTA (cRAP) for the ProSE organism search")
    an.add_argument("--sdrf", choices=("use", "jev", "off"), default="use",
                    help="curated SDRF (with --accession): use = evidence and reader input, jev = reader input "
                         "only (Jev/LLM), off = not fetched")
    an.add_argument("--skip-enzyme", action="store_true", help="skip the protease competition")
    an.add_argument("-o", "--out", default="prose_auto_out")
    an.add_argument("--json", action="store_true", help="print the report JSON to stdout (for the GUI)")
    pn = sub.add_parser("panel", help="download the model-organism FASTA panel from UniProt")
    pn.add_argument("out")
    pn.add_argument("--all-entries", action="store_true", help="TrEMBL too (default: Swiss-Prot only)")
    a = ap.parse_args(argv)
    if a.cmd == "panel":
        fetch_panel(a.out, reviewed=not a.all_entries)
    if a.cmd == "analyze":
        log = (lambda *x: print(*x, file=sys.stderr)) if a.json else print
        rep = analyze(a, log)
        os.makedirs(a.out, exist_ok=True)
        base = os.path.join(a.out, os.path.splitext(os.path.basename(a.mzml))[0])
        with open(base + ".auto.json", "w") as fh:
            json.dump(rep, fh, indent=1, default=str)
        with open(base + ".auto.md", "w") as fh:
            fh.write(markdown(rep))
        with open(base + ".prose.ini", "w") as fh:
            fh.write(pp.to_ini_snippet(rep["prose"]["params"]))
        with open(base + ".sdrf_technical.tsv", "w") as fh:
            fh.write("\t".join(rep["sdrf"]) + "\n" + "\t".join(rep["sdrf"].values()) + "\n")
        if a.json:
            print(json.dumps(rep, default=str))
        else:
            print(markdown(rep).split("## Evidence")[0])
            print(f"written: {base}.auto.json, .auto.md, .prose.ini, .sdrf_technical.tsv")


if __name__ == "__main__":
    main()
