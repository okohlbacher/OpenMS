I didn't run anything because tools are disabled, so this is a static review. Plan mode asks for a plan file, but since you said tools are off I'm reporting here.

**Bottom line:** I found no definite logic defect in the new reader path. Error precedence, transactional outputs, alias handling, and namespace handling match the DOM path for every case I traced. There is one probable behavioral divergence to confirm with a test, plus several test-coverage gaps where tests named for the reader actually run the DOM path.

## 1. Probable divergence: content after `</indexedmzML>` may go unchecked in the reader path

This depends on my reading of libxml2's `xmlTextReaderRead`/`xmlTextReaderPushData`, so confirm it with a test.

- The reader feeds the push parser in roughly 512-byte chunks.
- When the root element closes, `xmlTextReaderRead` calls `xmlParseChunk(ctxt, "", 0, 1)`. That finishes the parse without feeding the rest of the input buffer.
- Junk in the same chunk as `</indexedmzML>` is caught. Junk that appears only after about 512+ bytes of trailing whitespace is probably never parsed.
- On that input, `xmlReadMemory` (DOM path) returns -1 ("Extra content at the end of the document"). The reader path would likely return 0 and commit the offsets.
- A realistic trigger is a file with NUL or garbage padding after the footer. The same tail would be rejected under 2 MiB and accepted above it.

Test to add to the padded loop:

```cpp
write("<indexList><index name='spectrum'><offset>1</offset></index></indexList></indexedmzML>"
      + std::string(4096, ' ') + "<junk/>");
TEST_EQUAL(decoder.parseOffsets(filename, 0, spectra, chromatograms), -1)
```

Add a variant with `std::string(4096, '\0')` as well.

If it fails, either document the leniency or add an end-of-input check. One option is comparing `xmlTextReaderByteConsumed()` to `in.size()`, after checking what that function returns on your minimum libxml2 version.

## 2. Tests named for the reader actually exercise the DOM path

Everything below 2 MiB takes the DOM fast path:

- **"Footer cursor preserves DOM error precedence…"**: the 32,000-space case is about 32 KB, so it runs on the DOM. The comment "beyond the reader's initial input buffer" is wrong. The `<foo>/<bar>` permissive case and the empty `<indexList/>` output-preservation case also run on the DOM.
- **"Forward-only footer parsing preserves nested text attributes and namespaces"**: DOM only. The reader's `xmlTextReaderExpand` + `xmlNodeGetContent` handling of CDATA, nested `<value>`, `&amp;` in `idRef`, and a prefixed `n:indexList` has no coverage.
- **"Footer cursor handles … malformed XML"**: only the 70k-offset case reaches the reader. All four malformed footers run on the DOM.

Reader-path cases with no test anywhere:
- duplicate `indexList`;
- truncated document with no root close;
- `<offset>123</index>` mismatched end tag;
- a conversion error followed by an unknown index name in the same or a later index (should throw `ConversionError`);
- a conversion error followed by a duplicate `indexList` (should return -1);
- empty `<indexList/>` preserving outputs.

The fix is to run these sections through the same `padding ∈ {0, 2 MiB}` loop.

## 3. Minor test robustness issue

In the padded section, `spectra[0]` and `chromatograms[0]` are read without the size guards the other sections use. If a regression empties the vectors, the test crashes (undefined behavior) instead of failing.

## 4. Low: extra stderr output on the reader path

`stringToStreampos` writes to `std::cerr` before it throws. In the reader path, conversion runs before a later XML error is found, so a malformed large footer prints "Trying to convert corrupted…" and then returns -1. The DOM path prints nothing for the same input. Accept it or note it.

## 5. Low: build dependency on libxml2's reader module

`xmlreader.h` and `xmlTextReader*` need `LIBXML_READER_ENABLED`. Check that the contrib/CMake libxml2 build options for this replacement don't turn it off.

## Checked and consistent with old semantics

- **Error precedence:** XML errors and duplicate list → -1; an earlier unknown name → -1 before a later conversion error; a conversion error beats later unknown names; any late XML error beats a conversion error.
- **Empty elements:** `<index …/>` has no END_ELEMENT, and `finish_index` is called at element start.
- **Names:** `ConstLocalName` matches `xmlNode->name`, including unbound prefixes.
- **Aliased outputs:** commit order is correct whether the last index was a spectrum or a chromatogram, or only one type is present.
- **Untouched outputs:** with no indices, outputs are left alone.
- **No DTD or entity concerns:** the `<indexedmzML>` prefix means a DOCTYPE can't appear in the tail.
- **Memory:** nodes are freed sibling by sibling during streaming, since expanded nodes aren't marked preserved.

Maintainability nit, not a defect: the `property` lambda and the output-commit block are duplicated between the two paths. Pulling them into one helper keeps the transactional and alias semantics from drifting apart.
