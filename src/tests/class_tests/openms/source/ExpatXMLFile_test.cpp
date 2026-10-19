// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
// --------------------------------------------------------------------------
// $Maintainer: Timo Sachsenberg $
// --------------------------------------------------------------------------

#include <OpenMS/CONCEPT/ClassTest.h>
#include <OpenMS/FORMAT/XMLFile.h>
#include <OpenMS/FORMAT/HANDLERS/XMLHandler.h>
#include <OpenMS/FORMAT/HANDLERS/XMLAttributes.h>
#include <OpenMS/test_config.h>

#include <atomic>
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

  struct Handler : XMLHandler
  {
    Handler() : XMLHandler("ExpatXMLFile_test", "") {}
    std::u16string text;
    std::vector<std::u16string> tags;
    bool attributes_ok = false;
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
      }
    }
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
  reader.parseBuffer_("<?xml version='1.0'?><root xmlns:p='urn:test'><p:child a='\xc3\xa4\xf0\x9f\xa7\xaa&amp;'>" + padding + "\xc3\xa4\xf0\x9f\xa7\xaa&amp;<![CDATA[<tail>]]></p:child></root>", &handler);
  TEST_EQUAL(handler.tags.size(), 2)
  TEST_TRUE(handler.tags[1] == u"p:child")
  TEST_TRUE(handler.attributes_ok)
  TEST_TRUE(handler.text == std::u16string(65500, u'x') + u"\u00e4\U0001f9ea&<tail>")
}
END_SECTION

START_SECTION((malformed XML and callback exception propagation))
{
  Reader reader;
  Handler handler;
  TEST_EXCEPTION(Exception::ParseError, reader.parseBuffer_("<root><child></root>", &handler))
  TEST_EXCEPTION(Exception::ParseError, reader.parseBuffer_("", &handler))
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
  }
  Handler zipped;
  reader.parse_(OPENMS_GET_TEST_DATA_PATH("Deisotoper_input1.mzML.zip"), &zipped);
  TEST_TRUE(!zipped.tags.empty())
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
        }
      }
      catch (...) { correct = false; }
    });
  }
  for (auto& worker : workers) worker.join();
  TEST_TRUE(correct.load())
}
END_SECTION

END_TEST
