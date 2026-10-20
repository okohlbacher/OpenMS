# Independent final Codex check

Candidate: `8f66b3d921c9512e1e5968f494c77715ff71c696`; base: `1858656a86869ba462545a9232b89a0e1e1c319c`.

No actionable introduced findings in the complete four-file correction diff. This reviewer did not implement the changes. Runtime parser implementation is unchanged from the previously reviewed 1858656 candidate.

## Opus follow-up findings 1–3

1. **Resolved: guard pruning.** `build`, `vcpkg` and `vcpkg_installed` exclusions now apply only at checkout root. Actual vendor/historical trees use explicit relative paths. `.github/actions/build/action.yml` and nested source directories named `build` or `vcpkg` are visited. Existing `CMakeCache.txt` detection still prunes generated build directories. New tests exercise the composite action package regression and nested product CMake discovery, while preserving prior vendor/build exclusions.
2. **Resolved: location test specificity.** The DOM test checks `(line 2, column `, while the SAX callback test checks its existing `( in line 2 column ` format. Neither can pass merely because libxml2 describes the opening element as `broken line 2`.
3. **Resolved: amplification controls.** The mzIdentML fixture verifies the XML declaration insertion point, accepts the identical DTD with the 10,000-character below-budget expansion, then requires an amplification-specific rejection for the larger expansion. The indexed decoder test now also verifies real expansion of the identical DTD into the spectrum ID. Inspected the decoder itself: it passes the full input, including DTD, to `xmlCtxtReadMemory`; it does not lexically strip a prefix before `<spectrum>`. Thus the earlier unconfirmed DTD-stripping concern does not apply. The root-closing callback and explicit amplification limit remain unchanged.

## Disposition of optional Opus follow-up items 4–6

- **4 — diagnostic formatting: accepted presentation limitation.** Retained libxml2 diagnostic strings can contain a trailing newline, and fallback location text can contain line/column zero. This does not change parsing, acceptance, exception ownership or the actual diagnostic. No runtime edit is warranted for this optional formatting nit in the final guard/test correction.
- **5 — suppressed nonfatal DOM diagnostics: disclosed visibility trade-off.** The context-local no-op DOM reporter intentionally suppresses libxml2 stderr; a successfully returned DOM can therefore have unreported warning or nonfatal namespace diagnostics. Strict SAX2 still rejects namespace errors. This candidate does not change DOM acceptance semantics, and no concrete introduced data-corruption or unsafe-acceptance defect was established. Capturing and logging all diagnostics would be a separate behavior change rather than a necessary correction to this four-file diff.
- **6 — memory and stderr regression coverage: disclosed test limitation.** The functional comment/PI test verifies callback behavior across chunk boundaries, not retained DOM-node counts or RSS. The separate structural probe is the evidence for the memory correction: 20,000 retained nodes with default callbacks versus zero when disabled. It is not an automated class-suite memory assertion. DOM stderr suppression likewise lacks an automated assertion. These coverage limits remain explicit; this review does not claim the class test alone guards memory or stderr behavior.

## Validation and scope

Independently ran all **11** removal-guard unit tests successfully, ran the guard against the actual product source successfully, and ran `git diff --check` successfully. Read the entire four-file diff, review packet, prior Opus follow-up findings and relevant native DOM/decoder/SAX source. The root owns the new macOS/Linux full-suite runs, which were pending at review time; this review does not claim their final results. No code, documentation or shared build directory was modified by this reviewer. Windows/Docker execution remains outside this review.

Reviewed files:

- `src/tests/class_tests/openms/source/MzIdentMLFile_test.cpp`
- `src/tests/class_tests/openms/source/XMLParserBackend_test.cpp`
- `tools/ci/check_no_xerces.py`
- `tools/ci/tests/test_check_no_xerces.py`

Diff SHA-256: `a96481b3c7bfe954bf3912051c141c8492c50852adb7764c157a0410fcb534cc`.
