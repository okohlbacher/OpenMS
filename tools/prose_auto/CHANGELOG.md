# Changelog

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
