## Findings

**No concrete introduced defects found in the four files.**

### Checks performed

**`tools/ci/check_no_xerces.py`**
- `build`, `vcpkg` and `vcpkg_installed` are now pruned only at the source root. Nested build trees are still caught by the `CMakeCache.txt` and `cmake-build-*` checks.
- `.github/actions/build/action.yml` is now scanned.
- Vendored paths are still pruned:
  - `src/openms/extern`, `src/openms/thirdparty` and `tools/xml-parser-benchmark` through `excluded_paths`.
  - `vcpkg/ports/...` at the root through `excluded_root`.
- The `parent == source` and `relative_to(source).parts` checks hold for absolute, relative and `.` source dirs. `os.walk` yields paths with the same prefix, and `Path` normalizes trailing slashes.
- The existing allowed-vendor test and the prune test still pass with this logic.

**`test_check_no_xerces.py`**
- The new `action.yml` case would have failed under the old global `build` exclusion. It covers the fix.
- The nested `build` and `vcpkg` cases have no `CMakeCache.txt`, so they test path pruning rather than cache pruning. Both are correct.

**`MzIdentMLFile_test.cpp`**
- The below-budget `&b;` case expands to 10,000 characters, under libxml2's 1 MB always-allowed expansion. It proves the same DTD and entity path work.
- The negative case now requires "amplification" in the message. This closes the false positive from the 10 MB text-node limit or other parse errors.
  - The wording has been stable since libxml2 2.11. The backend already needs ≥2.13 (`xmlCtxtSetErrorHandler`), so this is acceptable.
- `(line 2, column ` pins the actual format. The old split `line 2` / `column ` match could pass on unrelated text.

**`XMLParserBackend_test.cpp`**
- `( in line 2 column ` pins the `fatalError` callback format.
- The below-budget case `id='&e2;'` gives 1,000 characters, which matches `expanded`. It proves the full DTD is present and parsed.
- The negative case cannot pass by accident if the explicit limit is removed. Under `HUGE`, libxml2 would then expand 100 MB and return a spectrum without throwing.

### Optional residual (not introduced, low severity)
- **What:** The decoder's negative case still accepts any `ParseError`. The decoder uses `XML_PARSE_NOERROR` and throws the generic "No root element or malformed XML".
- **Trigger:** The positive case uses entity expansion in an attribute, but the negative uses element content. A regression that breaks only element-content entity references would still satisfy the negative.
- **Impact:** That regression would pass the test unnoticed.
- **Minimal fix (if wanted):** Also call `decoder.domParseSpectrum(dtd + "]><spectrum defaultArrayLength='0'>&e2;</spectrum>", spectrum)` and expect no throw.
