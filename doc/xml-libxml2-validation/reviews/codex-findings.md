# Codex adversarial review — full Xerces replacement

Frozen candidate: `94e69565a2e6473fe389874d8a2214abb1c3a9c8`.
Final-removal base: `c5b68c645f80960cc033db79313978b1ad8fb058`.
Original develop control: `77cccda7caf40b46a4919d33748450270eccd565`.

**Final follow-up status:** All three original findings are corrected in `fcdc7458543e8936a0f8915828860669c7044514`. The intermediate globally strict SAX2 correction at `72d8c395e6` exposed legacy-reader compatibility failures in the coordinator's full suite; the final correction preserves generic SAX1 mode and explicitly enables strict SAX2 for ImzML. Independent follow-up found no remaining concrete blocker in these corrections. Full cross-platform/build-suite validation remains with the coordinator.

Read-only review: no source edits, commits, or pushes by this reviewer. Other agents began fixing findings while this report was prepared; line numbers below refer to the frozen candidate, not their working edits. Historical benchmark evidence was not rerun or modified.

## Frozen-candidate findings — all corrected in follow-up

### 1. [P2] Do not traverse DTD entity templates as mzIdentML records

**Location:** `src/openms/source/FORMAT/HANDLERS/MzIdentMLDOMHandler.cpp:125-127`, document overload of `descendants_`.

**Trigger:** Replace the existing `SpectrumIdentificationList` subtree in `MzIdentMLFile_whole.mzid` with an internal general entity reference (`&sil;`), declaring that same subtree as the entity replacement value in the internal DTD. This preserves the effective document content. The new `xmlDoc*` overload casts the document to a node and walks every child tree, including the DTD. After expansion, libxml2 retains a parsed replacement tree under the entity declaration as well as the inserted document subtree.

**Observed impact:** The frozen candidate loads 6 peptide identifications; the original fixture and the Xerces control load 3. The duplicate records are returned successfully, so downstream identification counts and analyses receive duplicated data. Other globally collected element types are also exposed to the same traversal.

**Minimal fix:** Start document queries at `xmlDocGetRootElement(doc)` and search only its actual element subtree. Preserve root inclusion deliberately if required by the helper contract; never visit the DTD.

**Regression test:** An entity-wrapped identification list must yield exactly the same proteins, peptide identifications and hits as the original fixture. The small linked repro is `review-probe.cpp`; generated input is `entity-sil.mzid` in this directory.

**Introduced versus preexisting:** Introduced by the native DOM replacement. The old Xerces document query does not visit DTD entity declaration templates. Reproduced against the candidate build and the existing Xerces control library.

### 2. [P2] Keep foreign namespace elements out of mzIdentML data

**Location:** `src/openms/source/FORMAT/HANDLERS/MzIdentMLDOMHandler.cpp:72-75` and `:113` (`name_` and descendant matching); corresponding child-name comparisons use the same helper.

**Trigger:** Prepend `<foreign:DBSequence xmlns:foreign="urn:unrelated" ...>` before the unchanged real `DBSequence` in `MzIdentMLFile_whole.mzid`. Give it the same unqualified id/accession but `Seq=AAAAAAAA`. This is well-formed XML with an unrelated expanded element name. The new helper returns only `node->name` and ignores `node->ns->href`, so the foreign element matches `DBSequence` and wins the map's first insertion.

**Observed impact:** The frozen candidate successfully returns `PROT1` with sequence `AAAAAAAA`; the Xerces control returns the unchanged actual mzIdentML sequence `PRGTEIN`. The same local-name matching applies to structural lists and parameter elements, allowing unrelated namespaced content to be treated as mzIdentML values. Schema validity of this mixed-namespace fixture is not asserted; the loader does not perform schema validation.

**Minimal fix:** Match the accepted mzIdentML namespace URIs (and unqualified legacy elements if compatibility requires them), rather than every namespace with the same local name. Apply the policy to root validation, descendant collection and child-name dispatch while retaining support for arbitrary prefixes bound to a recognized URI.

**Regression test:** A foreign `DBSequence` before a real one must not replace its sequence; foreign parameters should not change scores. Keep the existing recognized-prefix test. Repro input is `foreign-db-extra.mzid`.

**Introduced versus preexisting:** Introduced by replacing Xerces qualified-tag-name matching with unconditional local-name matching. The control ignores the prefixed foreign record.

### 3. [P2] Preserve namespace error checking when routing ImzML through XMLFile

**Location:** `src/openms/source/FORMAT/ImzMLFile.cpp:548` (new shared parse call), with `src/openms/source/FORMAT/XMLFile.cpp:168` selecting SAX1.

**Trigger:** Add `ghost:flag="1"` to the root of `ImzMLFile_1_Example_Continuous.imzML` without defining `xmlns:ghost`. Keep the original companion IBD. The removed direct reader enabled `fgSAX2CoreNameSpaces`; the shared libxml2 adapter initializes SAX1, which does not validate namespace bindings.

**Observed impact:** `ImzMLFile::loadSpectraIndex` successfully returns 9 spectra in the candidate; the Xerces control throws a ParseError explaining that prefix `ghost` cannot be resolved to a namespace URI (line 6, column 23). The generic SAX probe also accepts duplicate expanded attribute names and an illegal `xml` binding. This is acceptance of namespace-invalid input; valid-input data corruption is not demonstrated for ImzML.

**Minimal robust fix:** Use a namespace-aware SAX2 adapter for ImzML and reconstruct the existing qualified-name callback contract from prefix/local name. A shared namespace-aware mode can be selected internally if preserving the generic XMLFile legacy behavior is required. libxml2 SAX1 has no option that enables full namespace validation; a hand-written namespace validator or a second parsing pass would add unnecessary parser logic/cost.

**Regression test:** Both full ImzML load and index-only load must reject an unbound attribute prefix and duplicate expanded attribute names, while the existing ordinary ImzML fixtures still pass. The standalone `imzml-review-probe.cpp` demonstrates the index-only case. Input generation: add the attribute to the existing continuous fixture, write `invalid-namespace.imzML`, and place/link its IBD as `invalid-namespace.ibd`.

**Introduced versus preexisting:** Generic XMLFile SAX1 behavior was already in the tested PoC. The final-removal ImzML rerouting newly weakens a formerly namespace-aware reader, so this path-specific finding is introduced by this candidate.

## Checks and limits

- Reviewed all 63 changed files relative to the tested PoC, including build/configuration, native DOM reader/writer ownership and error paths, stream adapters and ImzML routing, strict Unicode and integer conversion, attribute lifetime/lookup, initialization, headers, CI removal guard and added tests. Also traced the prior PoC changes in XMLFile, indexed mzML decoding, UTF-8 character dispatch and XMLValidator against original develop, and the relevant mzIdentML/ImzML callers.
- Compiled a small standalone probe against `OpenMS-replacement-build/lib/libOpenMS.dylib`. The same executable was run against the existing Xerces control via `DYLD_LIBRARY_PATH=../OpenMS-optimized-build/lib` to verify behavioral differences.
- Confirmed native DOM loading for ordinary, space-containing, Unicode, `#` and literal `%20` filenames on this macOS host.
- Ran the 3 CI removal-guard unit tests and the guard against the full replacement build: passed. Frozen diff whitespace check passed.
- SAX1 namespace observations are preexisting for the generic XMLFile adapter, but a direct ImzML repro and control comparison established the path-specific regression in finding 3.
- Existing incomplete legacy DOM writer behavior and known schema `xs:anyURI` differences were not relabeled as new regressions. No further confirmed blocker was found in stream ownership, callback exception capture/soft stop, conversion, installation lists, static libxml2 lookup, or the reviewed Docker/wheel/Windows configuration changes.
- Full CTest and Linux validation belong to the coordinating task. This reviewer did not rerun heavy tests, Windows/MSVC builds, full Docker builds, wheel packaging, or historical benchmark matrices. Configuration review does not establish those platform executions have passed.

## Independent follow-up review of commit 72d8c395e6

Reviewed the complete five-file diff from the frozen candidate to `72d8c395e6f90ee3c0ff250a6575fb5985fe44df`:

- `src/openms/source/FORMAT/HANDLERS/MzIdentMLDOMHandler.cpp`
- `src/openms/source/FORMAT/XMLFile.cpp`
- `src/tests/class_tests/openms/source/ImzMLFile_test.cpp`
- `src/tests/class_tests/openms/source/MzIdentMLFile_test.cpp`
- `src/tests/class_tests/openms/source/XMLParserBackend_test.cpp`

The native document query now begins at the actual root. Namespace filtering accepts the bundled mzIdentML 1.0–1.3 URIs and historical unqualified elements; root validation, descendant name matching and first/next child helpers apply this policy. The incidental legacy DOM writer correction removes the inherited literal `search_engine_` CV lookup, uses actual engine/version values, puts SoftwareName under AnalysisSoftware, and falls back to a user parameter for unknown software names. No new concrete issue was found in those changes; the legacy writer remains incomplete as already noted.

The SAX2 adapter reconstructs qualified names from prefix/local name, includes local xmlns declarations for compatibility with existing callbacks, and consumes attribute values with the SAX2 five-pointer tuple's explicit begin/end bounds. The NOENT option retains normalized entity values. Callback exceptions and soft stop still flow through the existing context-local exception guard; namespace errors use the same context-local diagnostic handler. Existing attribute-index callers find an index by name before reading by index, so placing namespace declaration entries first does not change their selected attribute. Review found no newly exposed lifetime or C++ exception escape in these callback changes.

Independent runtime checks against the rebuilt replacement library:

- Original `entity-sil.mzid`: 3 peptide identifications, rather than the faulty 6.
- Original `foreign-db-extra.mzid`: actual `PROT1` sequence `PRGTEIN`, rather than injected `AAAAAAAA`.
- Original ImzML unbound-prefix fixture: rejected with ParseError identifying unbound `ghost`; the faulty candidate returned 9 spectra.
- Generic probes for an unbound attribute prefix, duplicate expanded attribute name and illegal xml namespace binding: all rejected with the expected diagnostic.
- Additional standalone `sax2-followup-probe.cpp`: a 70,000-character qualified attribute crossing the 65,536-byte chunk boundary, Unicode, numeric/predefined/internal entities, a following sentinel attribute, qualified element start/end names, and an empty default namespace declaration all passed their assertions.
- Commit diff whitespace check passed. No source edits or builds were performed by this reviewer during follow-up. The implementation agent's focused CTest run was reported as 5/5 passed; the coordinator's full build/CTest remains independent ongoing work.

**Remaining concrete review issues:** none in the five-file correction. This does not claim Windows/MSVC, complete Docker images, wheel packaging, or every possible XML input was executed by this reviewer.

## Final compatibility follow-up: fcdc745854

Reviewed all five changed files from `72d8c395e6` to `fcdc7458543e8936a0f8915828860669c7044514`: XMLFile's header and implementation, ImzMLFile.cpp, XMLParserBackend_test.cpp, and comment-only maintenance of CompressedInputSource.h.

`XMLFile::parse_` and `parseBuffer_` now have an optional `namespace_aware` argument defaulting to false. Generic callers therefore retain original develop's namespace-disabled qualified-name behavior. The same flag reaches the shared parser through plain, compressed and buffer read paths. Native SAX1 start/end callbacks preserve qualified names and attribute conversion; selecting true installs the previously reviewed SAX2 callbacks. ImzML's common `loadImpl_` explicitly passes true, covering full, streaming and index-only paths. Error callbacks, entity options, exception capture and soft stop remain shared, with no ignored error codes or fixture-specific handling. The added protected-method argument changes the compiled method signature; consumers must rebuild as the migration's existing SDK notice already requires.

The tests now explicitly distinguish generic legacy input from strict namespace checking. Generic tests accept the historical OpenXQuest unbound qualified attribute and malformed namespace URI, while NamespaceReader explicitly enables strict parsing for invalid-prefix, duplicate expanded attribute, reserved binding, qualified-name/value-slice, entity and soft-stop cases. Existing ImzML strict full/index-only regressions remain in place. No test fixtures were patched to hide failures.

Independent verification against the final rebuilt library (standalone probes recompiled for the current XMLFile signature):

- Internal entity identification list returns 3 peptide identifications.
- Foreign DBSequence injection leaves `PROT1=PRGTEIN`.
- ImzML with unbound `ghost` prefix is rejected with the expected ParseError.
- Explicit strict SAX2 probe passes 70,000-character bounded attribute, Unicode/entity normalization, qualified start/end names and default-namespace-reset assertions.
- Generic namespace-disabled probe accepts the same three namespace-invalid constructs accepted by original develop and the frozen PoC; this acceptance is deliberate legacy compatibility and is isolated from ImzML's strict path.
- Independently reran `XQuestResultXMLFile_test` and `IDScoreSwitcherAlgorithm_test` from `/tmp`: both passed. The implementation agent reported all 10 focused tests, including XFDR, passed. This reviewer did not independently rerun XFDR's TOPP fixture; it remains covered by the coordinator's suite.
- Final commit diff whitespace check passed.

**Remaining concrete review issues:** none found in this final mode-selection correction or the three original fixes. No OpenMS source edits or build-directory mutations by this reviewer. The full 747-test run, Windows/MSVC, Docker runtime and wheel packaging verification remain with the coordinating task; this review does not claim to have executed them.

## Changed-file coverage

- `.github/actions/build/action.yml`
- `.github/workflows/pyopenms-wheels-cibuildwheel.yml`
- `AGENTS.md`
- `CHANGELOG`
- `cmake/OpenMSConfig.cmake.in`
- `cmake/cmake_findExternalLibs.cmake`
- `cmake/compiler_flags.cmake`
- `doc/doxygen/install/install-win.doxygen`
- `doc/doxygen/public/ExternalCode.doxygen`
- `doc/doxygen/public/developer_faq.doxygen`
- `doc/openms/docs/manual/develop/developer-guidelines-for-adding-new-dependent-libraries.md`
- `dockerfiles/Dockerfile`
- `src/openms/CMakeLists.txt`
- `src/openms/include/OpenMS/CONCEPT/Init.h`
- `src/openms/include/OpenMS/FORMAT/Bzip2InputStream.h`
- `src/openms/include/OpenMS/FORMAT/CompressedInputSource.h`
- `src/openms/include/OpenMS/FORMAT/GzipInputStream.h`
- `src/openms/include/OpenMS/FORMAT/HANDLERS/ImzMLHandler.h`
- `src/openms/include/OpenMS/FORMAT/HANDLERS/MzIdentMLDOMHandler.h`
- `src/openms/include/OpenMS/FORMAT/HANDLERS/MzMLSpectrumDecoder.h`
- `src/openms/include/OpenMS/FORMAT/HANDLERS/SAX2HandlerAdapter.h`
- `src/openms/include/OpenMS/FORMAT/HANDLERS/StringManager.h`
- `src/openms/include/OpenMS/FORMAT/HANDLERS/XMLAttributes.h`
- `src/openms/include/OpenMS/FORMAT/HANDLERS/XMLHandler.h`
- `src/openms/include/OpenMS/FORMAT/HANDLERS/sources.cmake`
- `src/openms/include/OpenMS/FORMAT/InputStream.h`
- `src/openms/include/OpenMS/FORMAT/XMLFile.h`
- `src/openms/include/OpenMS/FORMAT/ZipInputStream.h`
- `src/openms/include/OpenMS/FORMAT/sources.cmake`
- `src/openms/include/OpenMS/KERNEL/OnDiscImzMLExperiment.h`
- `src/openms/source/CONCEPT/Init.cpp`
- `src/openms/source/FORMAT/Bzip2InputStream.cpp`
- `src/openms/source/FORMAT/CompressedInputSource.cpp`
- `src/openms/source/FORMAT/GzipInputStream.cpp`
- `src/openms/source/FORMAT/HANDLERS/ImzMLHandler.cpp`
- `src/openms/source/FORMAT/HANDLERS/MzIdentMLDOMHandler.cpp`
- `src/openms/source/FORMAT/HANDLERS/MzMLHandler.cpp`
- `src/openms/source/FORMAT/HANDLERS/MzMLSpectrumDecoder.cpp`
- `src/openms/source/FORMAT/HANDLERS/MzXMLHandler.cpp`
- `src/openms/source/FORMAT/HANDLERS/StringManager.cpp`
- `src/openms/source/FORMAT/HANDLERS/XMLAttributes.cpp`
- `src/openms/source/FORMAT/ImzMLFile.cpp`
- `src/openms/source/FORMAT/XMLFile.cpp`
- `src/openms/source/FORMAT/ZipInputStream.cpp`
- `src/pyOpenMS/bindings/bind_format.cpp`
- `src/pyOpenMS/pyproject.toml`
- `src/testframework/include/OpenMS/CONCEPT/ClassTest.h`
- `src/tests/class_tests/openms/CMakeLists.txt`
- `src/tests/class_tests/openms/executables.cmake`
- `src/tests/class_tests/openms/source/Bzip2InputStream_test.cpp`
- `src/tests/class_tests/openms/source/CompressedInputSource_test.cpp`
- `src/tests/class_tests/openms/source/GzipInputStream_test.cpp`
- `src/tests/class_tests/openms/source/ImzMLFile_test.cpp`
- `src/tests/class_tests/openms/source/MzIdentMLFile_test.cpp`
- `src/tests/class_tests/openms/source/StringManager_test.cpp`
- `src/tests/class_tests/openms/source/XMLParserBackend_test.cpp`
- `src/tests/class_tests/openms/source/ZipInputStream_test.cpp`
- `src/tests/external/boost_free/CMakeLists.txt`
- `src/topp/UniPEFF/include/UniProtXMLFile.h`
- `src/topp/UniPEFF/source/UniProtXMLHandler.cpp`
- `tools/ci/check_no_xerces.py`
- `tools/ci/tests/test_check_no_xerces.py`
- `vcpkg.json`

## Independent triage of Kimi concerns

See `kimi-triage.md` for dispositions of every A1–A6, B1–B3 and C1–C5 item, primary-source references, and bounded encoding/amplification repros. No additional migration blocker was established; inherited XL-MS cardinality validation is explicitly deferred.

## Final CI diagnostic correction: 0f77eb46b4

Independently inspected the two-line guard/test correction from 8cf5579a16 to 0f77eb46b4. Dependency inspector decoding errors are now caught as UnicodeError and turned into the same controlled failing diagnostic as process/OS errors. The existing inspector-failure test method covers FileNotFoundError, CalledProcessError and UnicodeDecodeError as three subtests. All five guard test methods passed independently, the source/linked-library guard passed against OpenMS-replacement-build, and the commit diff whitespace check passed. A decoding failure still fails closed; no false pass or ignored inspection result is introduced. No C++ change or additional concrete issue found.

## Final C++ follow-up: cbb180af85 writer version fallback

Independently reviewed the complete two-file diff from 0f77eb46b4 to cbb180af857f1c89956db8ac5128e4182d9b9ea8. The legacy DOM writer now emits `unknown` for an empty search-engine version or empty protein-run vector, while preserving an explicit version. The short-circuit condition safely avoids front() for an empty vector. This prevents the reader's existing nonempty-name/nonempty-version filter from discarding the software entry solely because its version was omitted. The regression observes actual serialized AnalysisSoftware attributes through the XML parser and asserts explicit Mascot/2.1.0 and missing-version Mascot/unknown cases. It does not claim a complete legacy-writer round trip, which remains limited by inherited protocol/placeholder gaps.

Independently ran the rebuilt MzIdentMLFile_test from /tmp: passed, including the new missing-version section. The commit diff whitespace check passed. No source or shared-build-directory changes by this reviewer; no additional concrete issue found in this final C++ correction.

Kimi's 72d8 follow-up dispositions: (1) wrong protocol builder remains inherited and explicitly deferred: original develop77 already called buildAnalysisCollection_(apc_p), and public MzIdentMLFile::store uses the separate writer; a one-line call swap alone would not establish a complete valid legacy output. (2) empty version metadata-loss behavior is corrected by cbb180af85 and the focused regression above. The namespace-mode compatibility correction fcdc745854 remains applicable and unchanged.
