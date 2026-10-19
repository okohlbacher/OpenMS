// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
// $Maintainer: Timo Sachsenberg $
#include <OpenMS/CONCEPT/ClassTest.h>
#include <OpenMS/FORMAT/XMLFile.h>
#include <OpenMS/FORMAT/HANDLERS/XMLHandler.h>
#include <OpenMS/FORMAT/HANDLERS/MzMLSpectrumDecoder.h>
#include <OpenMS/KERNEL/MSSpectrum.h>
#include <future>
#include <fstream>

using namespace OpenMS;

namespace
{
  class Reader : public Internal::XMLFile
  {
  public:
    using XMLFile::parseBuffer_;
    using XMLFile::parse_;
    using XMLFile::enforceEncoding_;
  };

  class Handler : public Internal::XMLHandler
  {
  public:
    Handler() : XMLHandler("prototype", "1.0") {}
    std::u16string attribute;
    std::u16string unicode_attribute;
    std::u16string text;
    Size elements = 0;
    void onStartElement(const char16_t*, const Internal::XMLAttributes& attrs) override
    {
      ++elements;
      if (const auto* value = attrs.value("label")) attribute = value;
      if (const auto* value = attrs.value("β")) unicode_attribute = value;
    }
    void onEndElement(const char16_t*) override {}
    void onCharacters(const char16_t* chars, Size length) override { text.append(chars, length); }
  };
}

START_TEST(XMLBackendPrototype, "$Id$")
START_SECTION((Unicode attributes, text, entities and CDATA))
{
  Handler handler;
  Reader().parseBuffer_("<root label=\"Grüße &#x1F600;\" β=\"UTF8-name\">A&amp;<![CDATA[B]]><child/>C</root>", &handler);
  TEST_EQUAL(handler.elements, 2)
  TEST_TRUE(handler.attribute == u"Grüße \U0001F600")
  TEST_TRUE(handler.text == u"A&BC")
  TEST_TRUE(handler.unicode_attribute == u"UTF8-name")
}
END_SECTION

START_SECTION(Independent encoding overrides for sequential buffers and files)
{
  Reader latin1;
  Reader utf8;
  latin1.enforceEncoding_("ISO-8859-1");
  utf8.enforceEncoding_("UTF-8");
  const std::string latin1_xml = "<root label=\"\xe9\">caf\xe9 &#x1F600;</root>";
  const std::string utf8_xml = "<root label=\"β\">Grüße \U0001F600</root>";
  Handler latin1_buffer;
  Handler utf8_buffer;
  latin1.parseBuffer_(latin1_xml, &latin1_buffer);
  utf8.parseBuffer_(utf8_xml, &utf8_buffer);
  TEST_TRUE(latin1_buffer.attribute == u"é")
  TEST_TRUE(latin1_buffer.text == u"café \U0001F600")
  TEST_TRUE(utf8_buffer.attribute == u"β")
  TEST_TRUE(utf8_buffer.text == u"Grüße \U0001F600")

  std::string latin1_path;
  std::string utf8_path;
  NEW_TMP_FILE(latin1_path)
  NEW_TMP_FILE(utf8_path)
  { std::ofstream output(latin1_path, std::ios::binary); output << latin1_xml; }
  { std::ofstream output(utf8_path, std::ios::binary); output << utf8_xml; }
  Handler latin1_file;
  Handler utf8_file;
  latin1.parse_(latin1_path, &latin1_file);
  utf8.parse_(utf8_path, &utf8_file);
  TEST_TRUE(latin1_file.attribute == latin1_buffer.attribute)
  TEST_TRUE(latin1_file.text == latin1_buffer.text)
  TEST_TRUE(utf8_file.attribute == utf8_buffer.attribute)
  TEST_TRUE(utf8_file.text == utf8_buffer.text)
}
END_SECTION

START_SECTION(Iterative traversal preserves callback order)
{
  class Events : public Internal::XMLHandler
  {
  public:
    Events() : XMLHandler("events", "1.0") {}
    std::u16string events;
    void onStartElement(const char16_t* name, const Internal::XMLAttributes&) override
    { events += u"+" + std::u16string(name) + u";"; }
    void onEndElement(const char16_t* name) override
    { events += u"-" + std::u16string(name) + u";"; }
    void onCharacters(const char16_t* text, Size length) override
    { events += u"T" + std::u16string(text, length) + u";"; }
  } handler;
  Reader().parseBuffer_("<root>A<a>B<![CDATA[C]]></a><b/>D</root>", &handler);
  TEST_TRUE(handler.events == u"+root;TA;+a;TB;TC;-a;+b;-b;TD;-root;")
}
END_SECTION

START_SECTION(Deep documents use bounded traversal stack and soft exits remain local)
{
  class Counts : public Internal::XMLHandler
  {
  public:
    Counts() : XMLHandler("deep", "1.0") {}
    Size starts = 0;
    Size ends = 0;
    bool stop = false;
    void onStartElement(const char16_t*, const Internal::XMLAttributes&) override
    {
      ++starts;
      if (stop && starts == 2) throw EndParsingSoftly(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION);
    }
    void onEndElement(const char16_t*) override { ++ends; }
    void onCharacters(const char16_t*, Size) override {}
  } handler;
  constexpr Size depth = 20000;
  std::string xml;
  xml.reserve(depth * 7);
  for (Size i = 0; i < depth; ++i) xml += "<n>";
  for (Size i = 0; i < depth; ++i) xml += "</n>";
  Reader().parseBuffer_(xml, &handler);
  TEST_EQUAL(handler.starts, depth)
  TEST_EQUAL(handler.ends, depth)
  Counts stopped;
  stopped.stop = true;
  Reader().parseBuffer_("<root><a/><b/></root>", &stopped);
  TEST_EQUAL(stopped.starts, 2)
  TEST_EQUAL(stopped.ends, 0)
}
END_SECTION

START_SECTION(Malformed XML produces ParseError)
{
  Handler handler;
  TEST_EXCEPTION(Exception::ParseError, Reader().parseBuffer_("<root><child></root>", &handler))
  MzMLSpectrumDecoder decoder;
  MSSpectrum spectrum;
  TEST_EXCEPTION(Exception::ParseError, decoder.domParseSpectrum("<spectrum defaultArrayLength=\"0\"><bad></spectrum>", spectrum))
}
END_SECTION

START_SECTION(Indexed fragments with trailing ancestor markup)
{
  MzMLSpectrumDecoder decoder;
  MSSpectrum spectrum;
  const std::string fragment = "<spectrum id=\"framed\" defaultArrayLength=\"0\"><binaryDataArrayList>"
      "<binaryDataArray><cvParam accession=\"MS:1000523\"/><cvParam accession=\"MS:1000514\"/><binary/></binaryDataArray>"
      "<binaryDataArray><cvParam accession=\"MS:1000523\"/><cvParam accession=\"MS:1000515\"/><binary/></binaryDataArray>"
      "</binaryDataArrayList><!-- </spectrum> is only comment text --></spectrum>";
  decoder.domParseSpectrum(fragment + "</spectrumList><chromatogramList count=\"1\">", spectrum);
  TEST_EQUAL(spectrum.getNativeID(), "framed")
  TEST_EQUAL(spectrum.size(), 0)
  TEST_EXCEPTION(Exception::ParseError,
      decoder.domParseSpectrum("<spectrum defaultArrayLength=\"0\"><bad></spectrum></spectrumList>", spectrum))
}
END_SECTION

START_SECTION(Independent documents and decoders on concurrent workers)
{
  std::vector<std::future<bool>> workers;
  for (Size worker = 0; worker < 8; ++worker)
  {
    workers.push_back(std::async(std::launch::async, [worker]
    {
      for (Size iteration = 0; iteration < 50; ++iteration)
      {
        Handler handler;
        Reader().parseBuffer_("<root label=\"worker\">safe</root>", &handler);
        if (handler.elements != 1 || handler.text != u"safe" || handler.attribute != u"worker") return false;
        MzMLSpectrumDecoder decoder;
        MSSpectrum spectrum;
        const std::string id = std::to_string(worker);
        decoder.domParseSpectrum("<spectrum id=\"" + id + "\" defaultArrayLength=\"0\"><binaryDataArrayList>"
            "<binaryDataArray><cvParam accession=\"MS:1000523\"/><cvParam accession=\"MS:1000514\"/><binary/></binaryDataArray>"
            "<binaryDataArray><cvParam accession=\"MS:1000523\"/><cvParam accession=\"MS:1000515\"/><binary/></binaryDataArray>"
            "</binaryDataArrayList></spectrum>", spectrum);
        if (spectrum.getNativeID() != id || !spectrum.empty()) return false;
      }
      return true;
    }));
  }
  for (auto& worker : workers) TEST_TRUE(worker.get())
}
END_SECTION
END_TEST
