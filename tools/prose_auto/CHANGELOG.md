# Changelog

## 0.1.5 (2026-11-03)

Mixture union search
- When organism_mix is suspected, ProSE, the alkylation probe and the FASTag mass-gap pass search the union of the
  suspected proteomes (`<panel>/extra/union/A+B.fasta`). An organism joins if an indicator of strength >= 0.3 names
  it and the panel mini-search gives it at least max(10, 0.5 % of the spectra) spectra the winner does not explain;
  winner first, then by those spectra, at most 4. Reagent genera join only when the user or the record names them.
- `.auto.json` carries `organisms` and `search_database`; `.auto.md` names the union; the SDRF organism column
  lists them separated by ";".
- Mixset (38 runs): 19/19 mixtures get a union, no pure file does. On the union runs PSMs +24 %, peptides +27 %,
  protein groups +47 % over 0.1.3 (97 %, 94 %, 97 % of the true-organism search), combined PSM FDP <= 1.5 %.
  Benchmark (180): 3 unions (PXD012636, PXD053406, PXD066672), PSMs +32 %.

Charge range
- The charge range counts only precursors up to 9,000 Da (ProSE's peptide:max_mass) and is clamped to 1..20,
  ProSE's limit. PXD062749 (heavy non-peptide ions at 8+ to 60+) went from 2..56 to 2..20; five other runs narrow.

## 0.1.4 (2026-11-03)

Runs without a digest
- Top-down, middle-down, native and intact-mass runs are detected right after reading the spectra
  (`topdown.py`). Such a run gets no ProSE parameters, no Jev questions and no mini-search. prose-auto writes the
  verdict, the reason with its numbers and "use FLASHTnT (OpenMS)" to `.auto.json` and `.auto.md`, and exits with
  status 3.
- Signals: charged MS2 precursors (median mass and charge, share at 8+); without precursor charges FLASHDeconv
  (`--flashdeconv`) on 40 MS1 and 40 MS2 spectra, and a charge-state series among the MS1 peaks scored against
  chance. Native: a charge series above m/z 2000, or precursors of >= 10 kDa at most at 0.078 sqrt(M).
- On 123 public runs (13 studies) against 268 bottom-up runs: intact mass 13/13, top-down 59/60, native 30/38,
  middle-down 8/12 aborted; no bottom-up run aborted. Two benchmark runs are top-down and are now aborted
  (PXD033100 intact EF-Tu, PXD024405 protamines). Thresholds set on these runs.

FASTag 1.8.0
- Requires FASTag >= 1.8.0. The termini and mass-gap passes read FASTag's own reports (`-digest_out`,
  `-label_out`, `-massgap_out`) with the 0.1.3 model table (`data/prose_auto_013_digest_models.tsv`); the tag-TSV
  parsing, the model scoring, the mass-gap histogram code, `delta_combos.py` and the MS2 scan-start gate (now
  FASTag's `ms2_first_peak` rule) are gone. The policy (confidences, TMTpro margin override, label, SILAC,
  alkylation and modification rules, HLA mapping, PASEF gate) stays in prose-auto.
- On 213 rerun runs every FASTag value equals 0.1.3's (terminal tags within 17, margins within 0.006); eight
  decisions moved because Jev answered differently. The two FASTag passes take 0.70x the time (59.5 s -> 41.5 s
  on 10 runs).

## 0.1.3 (2026-11-02)

Proteases and HLA ligands
- Protease from the published matrices: the FASTag tag termini (C-terminal residue and, from 100 tags, the
  N-terminal one; window +-0.008 Da) are scored by multinomial log-likelihood against MEROPS P1/P1' frequencies
  (trypsin, Lys-C, Lys-N, chymotrypsin, Glu-C, proteasome), PeptideCutter rules for Arg-C and Asp-N, the MHC
  Motif Atlas ligand ends (HLA-I, HLA-II) and the human proteome background ("unspecific") (5 % non-specific
  cleavage mixed into every model; `data/protease_models.tsv`). The margin per tag is the confidence; a call needs
  100 C-terminal tags and a margin >= 0.15. HLA-I/proteasome give class I ligands, HLA-II/unspecific class II.
- No tag call on timsTOF (ddaPASEF, diaPASEF: C-terminal R is nearly invisible), when the MS2 scans start above
  the y1 ion of K (147.11), or between trypsin and Lys-C/Arg-C when isobaric-labelled K dominates (TMTpro).
- Enzyme decision: user or repository, else the stronger of the tag call and Jev "+data" at p >= 0.8, else the
  keywords, else Trypsin. Inside the trypsin family (Trypsin, Trypsin/P, Lys-C, Arg-C) a Jev answer picks the
  member. The mini-search protease competition is removed.
- Keywords: Lys-N, lysyl and glutamyl endopeptidase, V8 protease; "unspecific" needs immunopeptidomics or HLA
  ligands, a bare "HLA" no longer counts; "no enzyme" in a control phrasing and texts naming three or more
  proteases give no call; a protease in the file name (`AspN`, `GluC`, `LysC`, `LysN`, `ArgC`, `chymo`) is evidence.
- SILAC needs >= 50 tags on both K and R; a low K/R share alone no longer votes for HLA ligands.
- Non-tryptic Orbitrap DDA (16 runs): enzyme 9 -> 15/16, label 14 -> 15/16, Cys alkylation 7 -> 8/10.
  DIA/timsTOF (11 non-tryptic runs, 12 tryptic controls): 5 -> 8/11, controls 12/12. HLA ligands 14/14.

Organisms
- Organism names resolve to NCBI taxon ids (`taxa.py`, `data/organism_taxa.tsv`, 165 taxa from the UniProt
  taxonomy); "yeast" is *S. cerevisiae* (4932), not *Candida albicans*.
- Tier 2 also searches every stated organism (user, repository, text from 0.5). A record's pick that was searched
  and explains under max(10, 1 %) of the spectra yields to another named species the search finds. A database
  under 10 % of the largest searched one's peptides tests nothing; an organism searched only for being stated
  does not keep a record's pick on the data shortlist.
- `organism_mix`: the "A + B" search indicator needs >= 40 unique spectra and 0.12 x the winner's PSMs, without
  PSMs of trypsin, keratins and serum albumin. A mixture only the records and texts describe is reported as
  study-level (`scope`), and not suspected when every stated second species was searched and is absent.
- Label agreement: "no SILAC" and "no isobaric label" agree unless they negate the decided label class.
- Mixture set (38 runs): sensitivity 19/19, specificity 15 -> 18/19; single-species files right 18 -> 19/19;
  suspected mixtures among the 180 validation runs 19 -> 9. Agreement at 0.2 on all data: precision
  0.16 -> 0.25, recall 0.71 -> 0.65.

Search windows
- ProSE windows per analyzer, as multiples of the measured error with ppm floors: Orbitrap precursor 4x, fragment
  2x (10/20 ppm); Astral 8x, 2x (10/10 ppm); TOF 1x, 1x (10/15 ppm); ion trap unchanged.

Fixes
- Target-decoy FDR of the mini-search: tied scores pass or fail together; the 1 % cut no longer falls inside a group
  of equal scores.
- A tier-2 organism winner also redoes the FASTag mass-gap evidence (Cys alkylation, modification combinations)
  against its database; before, the gaps against the losing database were kept.
- The FASTag species call runs once per run: after a failed ProSE organism search the panel stages reuse it.
- `--threads` also caps the OpenMP, OpenBLAS and MKL thread pools (unless set in the environment).

180 validation and held-out runs: enzyme 174/175 and every other setting as in 0.1.2; organism 174 -> 177/180.

## 0.1.2 (2026-11-02)

- Jev reads last: after the mini-search, the ProSE organism search, FASTag and the mass gaps, with the texts and
  every indicator (counts and reference ranges, no verdicts, no confidences). Its second request judges each final
  setting against the texts and the indicators (supports / texts contradict / indicators contradict / not
  mentioned); tolerances and modifications against the texts only.
- New output `agreement`: per setting, the confidence-weighted share of independent detectors that disagree
  (inconsistency, level, dissenting detectors, Jev's verdict), and an overall score. An inconsistency >= 0.2
  flags 53 of the 73 wrong decisions and 16 % of the correct ones.
- New output `organism_mix`: a suspected mixture of organisms from at least two kinds of indicator (a second
  database with spectra of its own, several genera stated, Jev's p(mixed species)).
- No single indicator decides an enrichment: a strong diagnostic-ion signal or two independent indicators are
  needed; on ion-trap MS2 the neutral-loss test no longer counts as tested. Enrichment 160 -> 165/180.
- HLA ligand call from several indicators (tag termini where valid, hydrophobic C-termini, precursor masses,
  singly charged share); tag termini alone no longer claim an unspecific digest.
- Lock-mass share counts scans with a hit, not hits.

## 0.1.1 (2026-11-02)

- pyopenms 3.5 (the last release for Python 3.10): idXML is read into a `PeptideIdentificationList`; a plain list
  failed there and broke the ProSE organism search.
- Tests: the shell-script stand-ins of DIAspeXtract and FileConverter are skipped on Windows.

## 0.1.0 (2026-11-02)

First release of the prototype.

- `auto` organism mode: the spectra check a stated organism (panel mini-search, FASTag, tier 2). Without a
  stated organism, one ProSE signature-panel search decides. 174/180 correct on the validation and held-out studies.
- HLA ligands: the unspecific-cleavage claim of the ProSE ladder needs a fully-tryptic PSM share below 0.5
  (tryptic runs 77-98 %, HLA ligand files 4-5 %).
- Persistent peptide indexes, a random 2,000-spectrum mini-search sample and query-time Cys and protease
  variants: a median run takes about 1-2 min.
- Readers (LLM, Jev) see all metadata and the measured data features. `--jev-priors` adds parameter
  distributions to the Jev prompt (no measurable effect; off by default).
- Repository fetches retry once on DNS, timeout and 5xx failures.
