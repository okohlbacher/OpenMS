# Adversarial review: Xerces→libxml2 final branch (c5b68c6 → cbb180a)

I found no Critical or High findings. Items marked *unexecuted* come from reviewing source and configuration only. Windows, Docker and wheel jobs were not run.

---

### M1 — Medium — libxml2 build features are not checked at configure time; generic XML reading depends on SAX1 at runtime
*Origin: SAX1 came from the prototype. The final build config leaves it unguarded now that Xerces is gone.*

- **Where:** `src/openms/source/FORMAT/XMLFile.cpp:211` (`xmlSAXVersion(&sax, namespace_aware ? 2 : 1)`) and `cmake/cmake_findExternalLibs.cmake:22` (only a version check).
- **Trigger:**
  1. Build against a libxml2 ≥ 2.13 configured without SAX1 (`-DLIBXML2_WITH_SAX1=OFF`, meson `-Dsax1=disabled`, or `--with-minimum`).
  2. The build compiles and links.
  3. Every load through `XMLFile` (mzML, featureXML, idXML, …) then throws `ParseError("libxml2 could not initialize the requested SAX callbacks")`.
  4. With `THREADS=OFF`, concurrent `parseBuffer_` calls race on libxml2 global state.
  5. Without iconv or ICU, documents declaring `windows-1252` fail with an unsupported-encoding error. Xerces handled that encoding natively.
- **Impact:** The library builds and links but fails on every generic XML read. Only Docker pins these flags.
- **Fix:** Add `check_symbol_exists` checks against `libxml/xmlversion.h` for `LIBXML_SAX1_ENABLED`, `LIBXML_THREAD_ENABLED`, `LIBXML_PUSH_ENABLED` and `LIBXML_SCHEMAS_ENABLED`, failing with `FATAL_ERROR`. Warn if neither `LIBXML_ICONV_ENABLED` nor `LIBXML_ICU_ENABLED` is set.
  - Alternative: drop SAX1 entirely. Use SAX2 and, when `!namespace_aware`, downgrade `XML_FROM_NAMESPACE` errors to warnings. `qualifiedName()` already rebuilds `prefix:local` for unbound prefixes.
- **Test:** A configure-time test. Also run the "legacy qualified names" `XMLParserBackend_test` section through the chosen path.

### M2 — Medium — the Windows CI step calls `python3` *(unexecuted)*
*Origin: introduced.*

- **Where:** `.github/actions/build/action.yml:246-247`
- **Trigger:** The `windows-x64-ci` job runs the step under bash on `windows-latest`. Toolcache Python provides `python.exe`, so `python3` either does not resolve or hits the Store stub. The repo's own Windows wheel job uses `python`.
- **Impact:** The step fails, and the implicit `success()` condition then skips the `Test` step. The Windows build job goes red.
- **Fix:** Use `PY=$(command -v python3 || command -v python)`, or add `actions/setup-python` before the step.
- **Test:** One Windows CI run.

### L1 — Low — comments and PIs pile up in `ctxt->myDoc` during SAX parsing
*Origin: prototype.*

- **Where:** `XMLFile.cpp:211-228`. `xmlSAXVersion` installs `xmlSAX2Comment` and `xmlSAX2ProcessingInstruction`. Element callbacks are overridden, so `ctxt->node` stays `NULL` and every comment or PI is attached to `myDoc` until the parse ends.
- **Trigger:** An mzML or featureXML file with many `<!-- … -->` comments.
- **Impact:** Memory grows without bound in proportion to comment volume, defeating streaming.
- **Fix:** Set `sax.comment = nullptr; sax.processingInstruction = nullptr;`. No handler consumes them.
- **Test:** Parse 10⁶ comments through `parseBuffer_` and check that peak RSS stays bounded, or count allocations via `xmlMemSetup`.

### L2 — Low — `XMLAttributes` holds a `const Values&`
*Origin: introduced (public header).*

- **Where:** `src/openms/include/OpenMS/FORMAT/HANDLERS/XMLAttributes.h:29`, `:44`
- **Trigger:** `XMLAttributes a(XMLAttributes::Values{{u"id",u"x"}}); a.value(u"id");` compiles and then reads freed memory.
- **Impact:** A dangling reference in a public API. Copy-assignment is also silently deleted (it was defaulted before), and CHANGELOG does not mention it.
- **Fix:** Add `XMLAttributes(Values&&) = delete;`. Store `const Values*` so the class stays assignable.
- **Test:** `static_assert(!std::is_constructible_v<XMLAttributes, XMLAttributes::Values&&>)` and `static_assert(std::is_copy_assignable_v<XMLAttributes>)`.

### L3 — Low — gaps in the removal guard
*Origin: introduced.*

- **Where:** `tools/ci/check_no_xerces.py:19-30`
- **Trigger 1:** Add `find_package(XercesC)` to any `CMakeLists.txt` other than `src/openms/CMakeLists.txt`, or to any `cmake/*.cmake`, `dockerfiles/*`, `tools/ci/*.sh` or `pyproject.toml`. The guard passes.
- **Trigger 2:** A non-UTF-8 file under `src/` raises an uncaught `UnicodeDecodeError` traceback instead of a reported failure.
- **Fix:** Scan every `CMakeLists.txt` and `*.cmake`, plus the Dockerfiles and CI scripts, for `XercesC|xerces-c|xercesc`. Read files with `errors='replace'`.
- **Test:** Add a fixture `src/topp/CMakeLists.txt` containing `find_package(XercesC)` and expect exit code 1. Add a Latin-1 `.cpp` fixture and expect a clean result.

### L4 — Low — the mzIdentML DOM read lacks `XML_PARSE_HUGE`
*Origin: introduced; Xerces had no such cap.*

- **Where:** `MzIdentMLDOMHandler.cpp`, in `readMzIdentMLFile()` at the `xmlCtxtReadFile` call.
- **Trigger:** Any text node over 10 MB, such as a `<Seq>` or a `userParam` text, fails with "huge text node". An attribute over 10 MB, such as `FragmentArray values`, fails the same way.
- **Impact:** A `ParseError` on input Xerces accepted. This is also inconsistent with `MzMLSpectrumDecoder`, which deliberately sets `HUGE` together with amplification 5.
- **Fix:** Add `XML_PARSE_HUGE`. Keep `xmlCtxtSetMaxAmplification(…, 5)`.
- **Test:** An mzid whose `<Seq>` is longer than 10,000,000 characters loads.

### L5 — Low — diagnostics lose context
*Origin: `XMLFile.cpp` items from the prototype; the DOM read is introduced.*

- **Where 1:** `XMLFile.cpp:245` and `:263` throw `ParseError` with an empty filename ("Unsupported XML encoding", "libxml2 rejected XML input").
- **Where 2:** The DOM read sets neither `XML_PARSE_NOERROR` nor an error handler. libxml2 prints to stderr, and the thrown message has no line or column.
- **Fix:**
  - Pass `filename` into both throws.
  - In the DOM read, call `xmlCtxtSetErrorHandler` to capture `line` and `int2` into the message.
- **Test:**
  - After `enforceEncoding_("bogus")`, `parse_(f)` throws and the exception reports `f`.
  - A malformed mzid gives a message containing "line N".

### L6 — Low — no test for a warning-only SAX2 parse
*Origin: introduced (namespace-aware mode).*

- **Where:** `XMLFile.cpp:250-264`. Warnings route to `handler->warning`, but there is no coverage that a parse emitting only `XML_ERR_WARNING`s still succeeds, i.e. that `xmlParseChunk` returns 0.
- **Trigger:** imzML with `xmlns:xsi='relative'` or another non-absolute namespace URI, parsed under SAX2.
- **Fix:** Add a test only.
- **Test:** `NamespaceReader().parseBuffer_("<root xmlns='rel'/>")` succeeds and `handler.warning` is called.

---

**Scope note:** M2 is *unexecuted*. The Docker libxml2 stage, the Homebrew wheel prefix (`PKG_CONFIG_USE_CMAKE_PREFIX_PATH` resolves the keg correctly), the vcpkg constraint and `OpenMSConfig`'s static `find_dependency` raised no source-level defects. They still need execution evidence.
