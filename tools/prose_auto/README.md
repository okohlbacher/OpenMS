# prose-auto: an Auto Mode prototype for ProSE

[![prose_auto](https://github.com/okohlbacher/OpenMS/actions/workflows/prose_auto.yml/badge.svg?branch=prose-auto)](https://github.com/okohlbacher/OpenMS/actions/workflows/prose_auto.yml)


`prose-auto` proposes ProSE search settings from an mzML file. It uses the
spectra and the file metadata, and optionally a FASTA or a model-organism
panel, a free-text description, a methods section, and the PRIDE/MassIVE/SDRF
records of a dataset. Every proposed setting comes with a confidence, its
source and the evidence behind it, and a setting is flagged for review
when the sources disagree.

This is a temporary exploration tool. It shows which detectors work and what
the GUI needs. It is not meant to be the final implementation: the detectors
that work belong in ProSE (C++) or in a prose-gui sidecar, as described in the
Auto Mode report.

## Install and run

```bash
pip install pyopenms numpy pyyaml          # or: pip install -e tools/prose_auto
cd tools/prose_auto
python -m prose_auto.cli panel proteomes/  # once: UniProt Swiss-Prot of 12 model organisms
python -m prose_auto.cli analyze run.mzML --panel proteomes/ \
    --description "HeLa, TMTpro 16plex, IAA, Exploris 480" \
    --accession PXD012345 --llm claude -o out/
```

The outputs, written per input to `out/`:

| File | Content |
|---|---|
| `<run>.auto.json` | everything: decisions, evidence, ProSE parameters, SDRF columns, LLM review (the GUI contract) |
| `<run>.auto.md` | readable report: settings table, conflicts, ProSE command line, evidence |
| `<run>.prose.ini` | ProSE INI fragment (`ProSE:1:Search:...`) |
| `<run>.sdrf_technical.tsv` | SDRF technical columns (instrument, label, tolerances, modifications) |

`--json` prints the report JSON to stdout and the log to stderr, so prose-gui
can run it as a sidecar.

## External tools (optional)

| Flag | Tool | What it adds |
|---|---|---|
| `--fastag <exe>` | [FASTag](https://github.com/okohlbacher/FASTag) | a database-free genus call (`-species`, reagent genera such as Bos/Sus are skipped when a real genus is close) and, with a FASTA, the Cys alkylation from the tag mass-gap histogram searched without fixed modifications (`-recon_fasta`, `-delta_out`) |
| `--fastag-subsample <f>` | FASTag | analyse only a fraction of the MS2 spectra |
| `--diaspextract <exe>` | [DIAspeXtract](https://github.com/okohlbacher/diaspextract) | converts a diaPASEF `.d` folder (required for `.d` input) or a DIA mzML with ion mobility into pseudo-MS/MS spectra (Orbitrap DIA without ion mobility skips it and stays on the DIA path; DDA-PASEF `.d` is not supported and stops with an error), so the mini-search and FASTag also run on DIA data |
| `--threads <n>` | both | threads for the external tools |

FASTag needs high-resolution MS2 to be useful: on the ion-trap BSA example it
places only a handful of tags, and its evidence stays below the mini-search.

## Runs without a digest

Top-down, middle-down, native and intact-mass runs are recognised right after reading the spectra
(`topdown.py`): from the MS2 precursor charges and masses, else FLASHDeconv on a few MS1 and MS2 spectra
(`--flashdeconv`) and charge-state series in MS1. prose-auto then sets no ProSE parameters, writes the verdict with
its reason and the recommendation "use FLASHTnT (OpenMS)", and exits with status 3.

## Pipeline

| Step | Module | What it decides | Basis |
|---|---|---|---|
| 1 metadata | `detect_instrument.py` | instrument model and class, MS1/MS2 analyzer (filter string `FTMS`/`ITMS`, mzML CV), activation, NCE, ion mobility | mzML CV terms, Thermo filter strings |
| 2 acquisition | `detect_instrument.py` | DDA / DIA / diaPASEF / PRM, DIA window scheme, charge range | isolation-window width, number of distinct window centres, repeats per cycle, charge annotation |
| 3 mass precision | `detect_tolerance.py` | fragment and precursor precision without a database | Param-Medic pairs (May et al. 2017), extended to DIA window repeats and MS1 scan-to-scan; Gaussian + uniform EM |
| 3 mass offset | `detect_tolerance.py` | systematic offset without a database | lock-mass polysiloxane ions (MS1), immonium and y1 ions (HCD MS2) |
| 4 chemistry | `detect_chemistry.py` | TMT/TMTpro/iTRAQ plex, SILAC, phospho/glyco/acetyl enrichment, Cys alkylation (weak) | reporter and diagnostic ions against control m/z values (Param-Medic 2019 idea); MS1 heavy/light pairs with an intensity check |
| 5 mini-search | `tagsearch.py`, `hypotheses.py` | organism, Cys alkylation, calibrated offsets and tolerances | binomial b/y scoring with target/reversed-decoy FDR on the top-TIC subset; competing hypotheses compared by PSMs at 1% FDR |
| 5 protease | `external.py` (FASTag >= 1.8.0 `-digest_out`) | protease, HLA ligand class | FASTag scores the tag termini against MEROPS, PeptideCutter, MHC Motif Atlas and proteome models (`data/prose_auto_013_digest_models.tsv`); not on timsTOF |
| 5 records and text | `repository.py`, `text_extract.py` | what the submitters and the user say | PRIDE API v3, PROXI, bigbio/sdrf-annotated-datasets, Europe PMC methods; keyword rules with verbatim quotes |
| 6 LLM | `llm.py` | the same from free text, literature priors, a final review | any CLI or OpenAI-compatible endpoint; quotes must occur in the text |
| 6b Jev (last) | `jev.py`, `schema.py` | every head from the texts and all indicators; afterwards a consistency verdict per setting | typed choice questions over the texts plus the measured and search profiles (`--jev`) |
| 7 reconcile | `reconcile.py` | one decision per parameter, confidence, conflicts, status; indicator agreement; suspected organism mix | measured beats stated for instrument-determined settings; a clear mini-search result beats text for sample prep; an enrichment needs a strong signal or two indicators |
| (opt) ProSE | `prose_runner.py` | confirmation with ProSE's own calibration pass and an open search | `-summary_out` YAML (`precursor_error`, `fragment_error`), `-out_mod_analysis_dir` |

## LLM backends

`--llm` takes `none` (the default; the rule-based extractor still runs),
`claude` (`claude -p`), `codex` (`codex exec -`), `cli:<any command reading
stdin>`, or `openai:<model>` (`OPENAI_BASE_URL`, `OPENAI_API_KEY`). It
answers three prompts: extract settings from text, typical tolerances for an
instrument/acquisition (`--llm-priors`), and a review of the final settings
(`--llm-review`).

## Reading the texts: one schema, many heads

`schema.py` defines the ProSE settings that texts can state as *heads*
(organism, sample type, protease, missed cleavages, Cys alkylation, label,
enrichment, acquisition, fragmentation, MS2 analyzer, instrument, precursor
and fragment tolerance), each with a closed list of values, plus yes/no flags
for variable modifications and for search types ProSE does not cover
(open, cross-link, glycan, top-down). All texts of a study (the user's
description, SDRF, PRIDE title/description/protocols, methods) go into one
labelled state and are read in **one request**:

* `--llm`: the generative LLM gets the heads, values and consistency rules in
  one prompt, answers every head with a verbatim quote (checked), and lists
  where the texts contradict each other or a rule.
* `--jev`: [Jev](https://docs.typesafe.ai) answers every head as a typed
  `choice` question (with "not stated") and every flag as a `noul` question.
  The head answers are decoded jointly: the most probable combination that
  breaks no hard rule wins, so a near-tie in one head is settled by the
  others. Jev runs after all searches and sees the texts plus every indicator
  as profiles with reference ranges. After reconciling, it judges each final
  setting against the texts and the indicators (supports / texts contradict /
  indicators contradict / not mentioned). Two requests per run, about $0.01. A TypeSafe console key
  (`TYPESAFE_API_KEY` or `JEV_API_KEY`) uses `api.typesafe.ai/v1/systemone`; a
  `jv_live_` key uses the jevtypesafeai.com proxy. About $0.001 per request.

**Consistency rules** (`schema.RULES`) say which values exclude each other
(*hard*: TMT/iTRAQ with ion-trap CID MS2, PASEF on a non-timsTOF, ETD on an
instrument without ETD, trypsin on an immunopeptidome, ppm fragment windows
on ion-trap MS2, Orbitrap vs TOF analyzer), which are unusual (*soft*: TMT
with DIA, unspecific search of a digest, K-GG without trypsin, 0.3 Da fragment
windows on high-res MS2, metabolic 15N/heavy-water labels, mixed species,
out-of-scope search types) and which imply others (*imply*: phospho
enrichment adds Phospho (STY), PASEF implies TOF and ion mobility). They are
applied to the text answers, to the final settings (`consistency` in the
report) and to the tuning loop's proposals.

## Tuning loop (`python -m prose_auto.tune`)

Starts from a report's ProSE settings and improves them with ProSE on a
top-TIC subset: each round reads ProSE's diagnostics (PSMs, calibration error
of precursor and fragment, open-search mass shifts), builds a shortlist of
changes (widen/narrow tolerances, add a modification seen as a mass shift,
drop surplus modifications, Trypsin/P, more missed cleavages, calibration),
drops any that break a hard rule, lets Jev order them (`--jev`; rule order
otherwise), searches the top few and keeps a change that gains at least 1%.
`--entrap entrap.py` scores by PSMs at 1% entrapment FDP instead of raw PSMs.
Every step goes to `<run>.tune.trace.jsonl` for later calibration of the
chooser.

```bash
python -m prose_auto.tune out/run.auto.json --prose ProSE --database td_entrap.fasta \
    --entrap entrap.py --jev --threads 16
```

## Tests

```bash
cd tools/prose_auto && python -m pytest tests -q
```

The tests use OpenMS test data: BSA1 (LTQ Orbitrap XL, CID/ion trap), the
DIAuditor and OpenSWATH DIA inputs, and the IsobaricAnalyzer iTRAQ input. A
fake LLM covers the quote guard.

## Organism and validation

`--organism-source auto` (the default):
- **An organism is stated and `--panel` is given:** the spectra check the stated organism. The panel mini-search, FASTag and tier 2 run with the stated organisms as evidence, and the data overrule the record only from 5 % of the mini-search spectra.
- **With `--fasta` or without a panel:** the stated organism is used directly.
- **Nothing stated:** one ProSE search against the signature panel (`--organism-panel`), else the panel mini-search.

On 180 public studies (62 validation, 118 held-out, one run each; truth from the curated SDRFs) the default reaches:

| Parameter | Correct |
|---|---|
| organism | 177/180 |
| instrument | 163/180 |
| acquisition | 168/180 |
| label | 160/178 |
| enrichment | 165/180 |
| enzyme | 174/175 |
| Cys alkylation | 122/128 |

The mass tolerances are measured, not copied. A wide-window search against the true proteome agrees with the measured error in 117 of 120 cases. The curated SDRF value is the authors' search-engine window, not the instrument's accuracy, so it is not used as truth.

Every report also carries `agreement` (per setting: the inconsistency of the independent indicators, the
dissenting detectors and Jev's verdict; overall score and level) and `organism_mix` (suspected, score,
indicators, scope). An inconsistency of 0.2 or more flags 65 % of the wrong decisions (precision 0.25).

Other sets (0.1.3): non-tryptic Orbitrap DDA enzyme 15/16, DIA/timsTOF non-tryptic 8/11 with 12/12 tryptic
controls, HLA ligand files 14/14 (unspecific, human); organism mixtures (38 runs) sensitivity 19/19, specificity
18/19.

## Known limits (prototype)

* The mini-search is pure Python; with persistent peptide indexes it takes 10-30 s per run.
* Repeated-ion and MS1 scan-to-scan estimates give precision without the offset and are about 2x too small
  alone; the mini-search PSM errors or the immonium/y1 probe should decide.
* Proteases on timsTOF come from the records, the texts and Jev only: the tag termini there miss C-terminal R.
  N-side cutters (Lys-N, Asp-N) need 100 N-terminal tags; LysargiNase has no model and reads as "unspecific".
* The non-tryptic sets are small (16 Orbitrap DDA, 11 DIA/timsTOF runs).
* `organism_mix` from the records and texts alone is study-level: a pure file of a mixed study is flagged unless
  the stated second species was searched and is absent.
