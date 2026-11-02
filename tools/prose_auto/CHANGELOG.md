# Changelog

## 0.1.3 (2026-11-02)

- Target-decoy FDR of the mini-search: tied scores pass or fail together; the 1 % cut no longer falls inside a group
  of equal scores.
- A tier-2 organism winner also redoes the FASTag mass-gap evidence (Cys alkylation, modification combinations)
  against its database; before, the gaps against the losing database were kept.
- The FASTag species call runs once per run: after a failed ProSE organism search the panel stages reuse it.
- `--threads` also caps the OpenMP, OpenBLAS and MKL thread pools (unless set in the environment).

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
