// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
// $Maintainer: Timo Sachsenberg $
#include <OpenMS/CONCEPT/ClassTest.h>
#include <OpenMS/FORMAT/XMLFile.h>
#include <OpenMS/FORMAT/HANDLERS/XMLHandler.h>
#include <OpenMS/FORMAT/HANDLERS/MzMLSpectrumDecoder.h>
#include <OpenMS/KERNEL/MSSpectrum.h>
#include <future>

using namespace OpenMS;

namespace
{
  class Reader : public Internal::XMLFile
  {
  public:
    using XMLFile::parseBuffer_;
  };

  class Handler : public Internal::XMLHandler
  {
  public:
    Handler() : XMLHandler("prototype", "1.0") {}
    std::u16string attribute;
    std::u16string text;
    Size elements = 0;
    void onStartElement(const char16_t*, const Internal::XMLAttributes& attrs) override
    {
      ++elements;
      if (const auto* value = attrs.value("label")) attribute = value;
    }
    void onEndElement(const char16_t*) override {}
    void onCharacters(const char16_t* chars, Size length) override { text.append(chars, length); }
  };
}

START_TEST(XMLBackendPrototype, "$Id$")
START_SECTION((Unicode attributes, text, entities and CDATA))
{
  Handler handler;
  Reader().parseBuffer_("<root label=\"Grüße &#x1F600;\">A&amp;<![CDATA[B]]><child/>C</root>", &handler);
  TEST_EQUAL(handler.elements, 2)
  TEST_TRUE(handler.attribute == u"Grüße \U0001F600")
  TEST_TRUE(handler.text == u"A&BC")
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
