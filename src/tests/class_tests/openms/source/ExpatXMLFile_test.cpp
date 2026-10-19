// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
// --------------------------------------------------------------------------
// $Maintainer: Timo Sachsenberg $
// --------------------------------------------------------------------------

#include <OpenMS/CONCEPT/ClassTest.h>
#include <OpenMS/FORMAT/XMLFile.h>
#include <OpenMS/FORMAT/HANDLERS/XMLHandler.h>
#include <OpenMS/FORMAT/HANDLERS/XMLAttributes.h>
#include <OpenMS/FORMAT/HANDLERS/MzMLSpectrumDecoder.h>
#include <OpenMS/FORMAT/HANDLERS/IndexedMzMLDecoder.h>
#include <OpenMS/test_config.h>

#include <atomic>
#include <cstdio>
#include <fstream>
#include <thread>
#include <vector>

using namespace OpenMS;
using namespace OpenMS::Internal;

namespace
{
  struct Reader : XMLFile
  {
    using XMLFile::parse_;
    using XMLFile::parseBuffer_;
    using XMLFile::enforceEncoding_;
    using XMLFile::save_;
  };

  struct FragmentReader : MzMLSpectrumDecoder
  {
    using MzMLSpectrumDecoder::BinaryData;
    using MzMLSpectrumDecoder::domParseString_;
  };
  struct FooterReader : IndexedMzMLDecoder
  {
    using IndexedMzMLDecoder::domParseIndexedEnd_;
  };

  struct Handler : XMLHandler
  {
    Handler() : XMLHandler("ExpatXMLFile_test", "") {}
    std::u16string text;
    std::vector<std::u16string> tags;
    std::vector<std::u16string> end_tags;
    bool attributes_ok = false;
    bool unicode_attribute_ok = false;
    bool abort = false;
    bool fail = false;
    std::string document;
    void onStartElement(const char16_t* name, const XMLAttributes& attributes) override
    {
      tags.emplace_back(name);
      if (abort) throw EndParsingSoftly(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION);
      if (fail) throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "callback sentinel", "");
      if (tags.back() == u"p:child")
      {
        attributes_ok = std::u16string(attributes.value("a")) == u"\u00e4\U0001f9ea&" &&
          std::u16string(attributes.value(u"a")) == u"\u00e4\U0001f9ea&" &&
          attributes.index(u"a") == 0 && attributes.index(u"missing") < 0 &&
          attributes.value("missing") == nullptr && attributes.valueByIndex(99) == nullptr &&
          std::u16string(attributes.valueByIndex(0)) == u"\u00e4\U0001f9ea&";
        const char16_t* unicode_value = attributes.value("\xc3\xa4");
        unicode_attribute_ok = unicode_value && std::u16string(unicode_value) == u"unicode" &&
          attributes.value(u"\u00e4") && std::u16string(attributes.value(u"\u00e4")) == u"unicode";
      }
    }
    void onEndElement(const char16_t* name) override { end_tags.emplace_back(name); }
    void onCharacters(const char16_t* value, Size length) override { text.append(value, length); }
    void writeTo(std::ostream& stream) override { stream << document; }
  };
}

START_TEST(ExpatXMLFile, "$Id$")

START_SECTION((qualified names, attribute access, entities and Unicode across input chunks))
{
  Reader reader;
  Handler handler;
  const std::string padding(65500, 'x');
  reader.parseBuffer_("<?xml version='1.0'?><root xmlns:p='urn:test'><p:child a='\xc3\xa4\xf0\x9f\xa7\xaa&amp;' \xc3\xa4='unicode'>" + padding + "\xc3\xa4\xf0\x9f\xa7\xaa&amp;<![CDATA[<tail>]]></p:child></root>", &handler);
  TEST_EQUAL(handler.tags.size(), 2)
  TEST_TRUE(handler.tags[1] == u"p:child")
  TEST_TRUE(handler.attributes_ok)
  TEST_TRUE(handler.unicode_attribute_ok)
  TEST_TRUE(handler.end_tags == std::vector<std::u16string>({u"p:child", u"root"}))
  TEST_TRUE(handler.text == std::u16string(65500, u'x') + u"\u00e4\U0001f9ea&<tail>")
}
END_SECTION

START_SECTION((malformed XML and callback exception propagation))
{
  Reader reader;
  Handler handler;
  TEST_EXCEPTION(Exception::ParseError, reader.parseBuffer_("<root><child></root>", &handler))
  TEST_EXCEPTION(Exception::ParseError, reader.parseBuffer_("", &handler))
  TEST_EXCEPTION(Exception::ParseError, reader.parseBuffer_("<root>\xff</root>", &handler))
  handler.fail = true;
  TEST_EXCEPTION(Exception::InvalidValue, reader.parseBuffer_("<root/>", &handler))
  handler.fail = false;
  handler.abort = true;
  // Soft abort must succeed even though the remainder is malformed.
  reader.parseBuffer_("<root><bad", &handler);
  handler.abort = false;
  reader.parseBuffer_("<root/>", &handler);
}
END_SECTION

START_SECTION((explicit encoding is applied per reader))
{
  Reader reader;
  Handler latin;
  reader.enforceEncoding_("ISO-8859-1");
  reader.parseBuffer_("<root>\xe4</root>", &latin);
  TEST_TRUE(latin.text == u"\u00e4")
  Handler utf8;
  reader.enforceEncoding_("UTF-8");
  reader.parseBuffer_("<root>\xc3\xa4</root>", &utf8);
  TEST_TRUE(utf8.text == u"\u00e4")
}
END_SECTION

START_SECTION((UTF-16 declaration and entity policy))
{
  Reader reader;
  Handler unicode;
  const std::u16string document = u"<?xml version='1.0' encoding='UTF-16'?><root>\u00e4\U0001f9ea</root>";
  std::string encoded = "\xff\xfe";
  for (char16_t unit : document)
  {
    encoded.push_back(static_cast<char>(unit & 0xff));
    encoded.push_back(static_cast<char>(unit >> 8));
  }
  reader.parseBuffer_(encoded, &unicode);
  TEST_TRUE(unicode.text == u"\u00e4\U0001f9ea")
  Handler internal;
  reader.parseBuffer_("<!DOCTYPE root [<!ENTITY text 'internal'>]><root>&text;</root>", &internal);
  TEST_TRUE(internal.text == u"internal")
  Handler external;
  TEST_EXCEPTION(Exception::ParseError, reader.parseBuffer_("<!DOCTYPE root [<!ENTITY text SYSTEM 'must-not-open'>]><root>&text;</root>", &external))
}
END_SECTION

START_SECTION((plain, gzip, bzip2 and ZIP inputs))
{
  Reader reader;
  Handler writer;
  writer.document = "<root>compressed text</root>";
  std::string path;
  NEW_TMP_FILE(path)
  for (const std::string suffix : {"", ".gz", ".bz2"})
  {
    const auto filename = path + suffix;
    reader.save_(filename, &writer);
    Handler parsed;
    reader.parse_(filename, &parsed);
    TEST_TRUE(parsed.text == u"compressed text")
    std::remove(filename.c_str());
  }
  Handler zipped;
  reader.parse_(OPENMS_GET_TEST_DATA_PATH("Deisotoper_input1.mzML.zip"), &zipped);
  TEST_TRUE(!zipped.tags.empty())
}
END_SECTION

START_SECTION((Expat indexed fragments preserve metadata and accept large binary text))
{
  FragmentReader reader;
  std::vector<FragmentReader::BinaryData> arrays;
  const std::string binary(13 * 1024 * 1024, 'A');
  const auto id = reader.domParseString_("<spectrum id='scan=\xc3\xa4&amp;1' defaultArrayLength='1277952'><binaryDataArrayList><binaryDataArray>"
    "<cvParam accession='MS:1000523' value=''/><cvParam accession='MS:1000514' value=''/>"
    "<binary>" + binary + "</binary></binaryDataArray></binaryDataArrayList></spectrum>", arrays);
  TEST_EQUAL(id, "scan=\xc3\xa4&1")
  TEST_EQUAL(arrays.size(), 1)
  ABORT_IF(arrays.empty())
  TEST_EQUAL(arrays[0].size, 1277952)
  TEST_EQUAL(arrays[0].base64, binary)
  std::vector<FragmentReader::BinaryData> framed;
  TEST_EQUAL(reader.domParseString_("<spectrum id='frame' defaultArrayLength='0'/></spectrumList><chromatogramList>", framed), "frame")
  TEST_EXCEPTION(Exception::ParseError, reader.domParseString_("<spectrum defaultArrayLength='0'><binaryDataArray/></spectrum>", arrays))
  TEST_EXCEPTION(Exception::ParseError, reader.domParseString_("<spectrum defaultArrayLength='0'><binaryDataArray><binary><bad/></binary></binaryDataArray></spectrum>", arrays))
  TEST_EXCEPTION(Exception::ParseError, reader.domParseString_("<spectrum defaultArrayLength='0'><binaryDataArray><binary><![CDATA[AAAA]]></binary></binaryDataArray></spectrum>", arrays))
  TEST_EXCEPTION(Exception::ParseError, reader.domParseString_("<spectrum defaultArrayLength='0'><binaryDataArray><binary>AAAA<!--bad--></binary></binaryDataArray></spectrum>", arrays))
  TEST_EXCEPTION(Exception::ParseError, reader.domParseString_("<spectrum defaultArrayLength='0'><broken></spectrum>", arrays))
  TEST_EXCEPTION(Exception::ParseError, reader.domParseString_("<spectrum/>", arrays))
}
END_SECTION

START_SECTION((Expat index footer handles Unicode, entities, offset conversion and failures))
{
  FooterReader reader;
  IndexedMzMLDecoder::OffsetVector spectra, chromatograms;
  const std::string footer = "<indexedmzML><indexList count='2'><index name='spectrum'>"
    "<offset idRef='scan=\xc3\xa4&amp;1'>123456789012</offset></index>"
    "<index name='chromatogram'><offset idRef='TIC'>42</offset></index>"
    "</indexList><indexListOffset>1</indexListOffset></indexedmzML>";
  TEST_EQUAL(reader.domParseIndexedEnd_(footer, spectra, chromatograms), 0)
  TEST_EQUAL(spectra.size(), 1)
  TEST_EQUAL(chromatograms.size(), 1)
  ABORT_IF(spectra.empty() || chromatograms.empty())
  TEST_EQUAL(spectra[0].first, "scan=\xc3\xa4&1")
  TEST_EQUAL(spectra[0].second, std::streampos(123456789012LL))
  TEST_EQUAL(chromatograms[0].second, std::streampos(42))
  TEST_EQUAL(reader.domParseIndexedEnd_("<root><indexList/><indexList/></root>", spectra, chromatograms), -1)
  TEST_EQUAL(reader.domParseIndexedEnd_("<root><indexList><index name='invalid'/></indexList></root>", spectra, chromatograms), -1)
  TEST_EXCEPTION(Exception::ConversionError, reader.domParseIndexedEnd_("<root><indexList><index name='spectrum'><offset>bad</offset></index></indexList></root>", spectra, chromatograms))
  TEST_EXCEPTION(Exception::ParseError, reader.domParseIndexedEnd_("<root><indexList></root>", spectra, chromatograms))
}
END_SECTION

START_SECTION((independent concurrent parser instances))
{
  std::atomic<bool> correct{true};
  std::vector<std::thread> workers;
  for (int i = 0; i < 8; ++i)
  {
    workers.emplace_back([&]
    {
      try
      {
        for (int j = 0; j < 25; ++j)
        {
          Reader reader;
          Handler handler;
          reader.parseBuffer_("<root>parallel \xf0\x9f\xa7\xaa</root>", &handler);
          if (handler.text != u"parallel \U0001f9ea") correct = false;
          FragmentReader fragments;
          std::vector<FragmentReader::BinaryData> arrays;
          if (fragments.domParseString_("<spectrum id='thread' defaultArrayLength='1'><binaryDataArray><binary>AAAA</binary></binaryDataArray></spectrum>", arrays) != "thread" ||
              arrays.size() != 1 || arrays[0].base64 != "AAAA") correct = false;
          FooterReader footer;
          IndexedMzMLDecoder::OffsetVector spectra, chromatograms;
          if (footer.domParseIndexedEnd_("<root><indexList><index name='spectrum'><offset idRef='thread'>42</offset></index></indexList></root>", spectra, chromatograms) != 0 ||
              spectra.size() != 1 || spectra[0].second != std::streampos(42)) correct = false;
        }
      }
      catch (...) { correct = false; }
    });
  }
  for (auto& worker : workers) worker.join();
  TEST_TRUE(correct.load())
}
END_SECTION

START_SECTION(Native ASCII attribute lookup and UTF8 fallback)
{
  const char16_t* pairs[]{u"id", u"one", u"idRef", u"two", u"β", u"unicode", u"naïve", u"accent", nullptr};
  const Internal::XMLAttributes attributes(pairs);
  TEST_TRUE(attributes.value(u"id") != nullptr)
  TEST_TRUE(attributes.value("id") == attributes.value(u"id"))
  TEST_TRUE(attributes.value("idRef") == attributes.value(u"idRef"))
  TEST_TRUE(attributes.value("idR") == nullptr)
  TEST_TRUE(attributes.value("idReference") == nullptr)
  TEST_TRUE(attributes.value("") == nullptr)
  TEST_TRUE(attributes.value("missing") == nullptr)
  TEST_TRUE(attributes.value(u"β") != nullptr)
  TEST_TRUE(attributes.value("β") == attributes.value(u"β"))
  TEST_TRUE(attributes.value("naïve") == attributes.value(u"naïve"))
  TEST_TRUE(attributes.value("βmissing") == nullptr)
}
END_SECTION
END_TEST
