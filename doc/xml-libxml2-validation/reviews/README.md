# Independent review coverage

The review gate covers the full migration, not just a prototype. Source at `c5b68c645f80960cc033db79313978b1ad8fb058` is the frozen published libxml2 PoC; the replacement adds a complete native DOM, shared XML infrastructure and dependency/CI migration.

- Codex reviewed the complete replacement and confirmed corrections for DTD traversal, namespace selection and strict imzML handling. Subsequent complete correction reviews are in `opus-fixes-codex.md` (all 11 files at 1858656) and `final-guard-codex.md` (all 4 final guard/test files at 8f66b3d).
- Kimi reviewed the initial complete replacement, followed by all relevant correction phases: `initial/`, `followup/`, `namespace-mode/`, `ci-guard/`, `dom-version/`, `opus-fixes/` and `final-guard/`. Read original findings alongside their dispositions; superseded findings are not unresolved final defects.
- Claude Opus 5.5 completed the self-contained complete product review at cbb180a (`final-opus/`): full 63-file diff plus critical complete source, tests and CI. It returned two Medium and six Low findings, with no Critical or High finding. Initial corrections were committed at 1858656, with the residual guard/test refinements below completed at 8f66b3d.
- Opus 5.5 then reviewed all 11 correction files and relevant full context (`opus-fixes/`). It found a residual CI-action pruning gap and weak amplification/location controls. The four-file correction at 8f66b3d closes those concrete issues, independently rechecked by Codex, Kimi and Opus (`final-guard/`).

Every completed Claude receipt identifies actual model `claude-opus-5-5`, a successful process return, and no fallback. Its raw terminal envelopes were checked for `subtype=success`, `is_error=false`, `stop_reason=end_turn` and `terminal_reason=completed`. Interrupted earlier calls are not counted. Only final findings and small run/input manifests are published; private reviewer stderr/reasoning is excluded.

Accepted low-impact residuals are explicit in `final-guard-codex.md`: cosmetic diagnostic newlines/zero locations; nonfatal DOM diagnostics suppressed from stderr; structural comment/PI node-retention probe rather than an automated RSS assertion; no dedicated stderr-suppression assertion; generic indexed-decoder error wording leaves a narrow negative-test specificity limit. These do not introduce a demonstrated unsafe-acceptance defect in this correction. Windows/Docker/wheel execution remains unverified; source review does not count as execution.

The migration summary also discloses the inherited incomplete legacy DOM writer and malformed XL-MS unequal-array-length bounds risk. These were not hidden by modifying fixture data or weakening XML namespace errors.
