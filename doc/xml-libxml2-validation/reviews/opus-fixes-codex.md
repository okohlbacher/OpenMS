# Independent Codex review of Opus fixes

Reviewed all 11 modified tracked files against `cbb180af85` and relevant XMLFile/XMLHandler callers, XMLAttributes callback construction and mzIdentML load path. This reviewer did not implement these changes. No new actionable correctness or security findings remain in this diff.

## Disposition of actual Opus findings

| ID | Disposition and reviewed evidence |
|---|---|
| M1 | Resolved. Configure checks SAX1, PUSH, SCHEMAS and THREAD feature macros and rejects a missing feature; warns if both ICONV and ICU are absent. Check state is scoped and caches are invalidated to support dependency replacement. Real Homebrew headers define the expected macros. Inspected synthetic configure logs for each required-feature rejection and the optional encoding warning. |
| M2 | Resolved in source. The composite action selects `python` on Windows and `python3` elsewhere using a task-specific shell variable. Actual Windows execution remains a CI validation limit. |
| L1 | Resolved. SAX1 and SAX2 both clear comment and processing-instruction callbacks before constructing the push parser; entity/DTD callbacks remain available. Inspected isolated probe evidence: 20,000 retained comment/PI document nodes before disabling callbacks, zero afterward. Regression covers file streaming across chunks in both modes. This is allocation evidence, not a complete platform RSS benchmark. |
| L2 | Resolved. Both mutable and const `Values` rvalues are deleted; the lvalue-backed pointer view remains copy constructible/assignable. Adapter callers supply local lvalue storage whose lifetime encloses callbacks. Compile-time traits and alias/copy behavior tests cover the contract. Retaining a view beyond its documented callback lifetime remains unsupported. |
| L3 | Resolved within the guard's intended dependency-detection scope. One pruned walk scans nested CMake discovery/targets, product headers/sources and relevant package recipes, with replacement decoding. Tests cover multiline discovery, nested targets, quoted dependency discovery, Docker/CI/shell/pyproject packages, adjacent distro package versions, binary names and generated/vendor exclusions. The guard is a regression aid rather than a parser of arbitrary generated build code. |
| L4 | Resolved. Native mzIdentML read enables HUGE while retaining amplification 5, NONET, NO_XXE and NOENT without recovery. Regression uses both text and an attribute larger than 10 MB and rejects nested entity amplification. Document and context ownership remains scoped. |
| L5 | Resolved. Unsupported encoding and fallback SAX errors retain the actual filename. DOM diagnostics are suppressed only on the parser context, retrieved from that context on failure and include line/column. Callback errors remain captured and rethrown in C++ without crossing C frames. Tests cover filename/encoding and malformed DOM location. |
| L6 | Resolved. Strict SAX2 warning-only parse test verifies the relative-namespace warning is emitted while valid text and the root callback are delivered. Existing namespace-invalid rejection tests remain. Generic SAX1 qualified-name compatibility policy is unchanged. |

## Validation and limits

Independently executed all 10 removal-guard unit tests successfully and executed the product-source removal guard successfully. `git diff --check` passed. Read the successful 1,065-target incremental build log and isolated comment/PI and warning-only probe outputs. The latter reports a warning and successful parser return 0.

The root agent owns full CTest and Linux validation; those were still running at review time and this review does not assert their final outcomes. No shared build directory was changed by this reviewer. Windows, Docker and wheel jobs were not executed by this reviewer. Existing historical prototype performance measurements are not evidence for the modified full-removal branch.

## Reviewed tracked files

- `.github/actions/build/action.yml`
- `cmake/cmake_findExternalLibs.cmake`
- `src/openms/include/OpenMS/FORMAT/HANDLERS/XMLAttributes.h`
- `src/openms/source/FORMAT/HANDLERS/MzIdentMLDOMHandler.cpp`
- `src/openms/source/FORMAT/HANDLERS/XMLAttributes.cpp`
- `src/openms/source/FORMAT/XMLFile.cpp`
- `src/tests/class_tests/openms/source/MzIdentMLFile_test.cpp`
- `src/tests/class_tests/openms/source/StringManager_test.cpp`
- `src/tests/class_tests/openms/source/XMLParserBackend_test.cpp`
- `tools/ci/check_no_xerces.py`
- `tools/ci/tests/test_check_no_xerces.py`

Reviewed diff SHA-256: `ac541a16f91147ab412a55f9234eac3e190449e9c87fe2c4fceef75dd3a0f367`.

## Follow-up: include propagation in config mode

Verified installed official libxml2 2.15.4 config and CMake's FindLibXml2 both explicitly define `LIBXML2_INCLUDE_DIRS`. Read the exact pinned vcpkg wrapper (`f9ffbaa46ad8e284b2b74919f7e0ba259564d424/ports/libxml2/vcpkg-cmake-wrapper.cmake`): it removes mode flags, calls `_find_package(${ARGS} CONFIG)` and provides the legacy FOUND alias. An isolated actual CONFIG-mode configure successfully checks all four required feature macros using only the include variable; log: `replacement-review/config-mode-probe/configure.log`.

The installed Homebrew config has no config-version file, so the isolated include-propagation probe omits a version request; forcing CONFIG with a version rejects that Homebrew package before feature checks. OpenMS's normal module discovery already validates the version successfully. This is a pre-existing package-discovery distinction, not a new feature-check failure. No counterexample requiring target-based include fallback was found for the official config/module interfaces.

## Exact committed candidate confirmation

Confirmed the complete reviewed diff is now committed as `1858656a86869ba462545a9232b89a0e1e1c319c`. The diff from `cbb180af857f1c89956db8ac5128e4182d9b9ea8` has the same SHA-256 recorded above (`ac541a16f91147ab412a55f9234eac3e190449e9c87fe2c4fceef75dd3a0f367`), covering all 11 files without further code changes. Full platform suites and vendor follow-up reviews remain root-owned pending validation.
