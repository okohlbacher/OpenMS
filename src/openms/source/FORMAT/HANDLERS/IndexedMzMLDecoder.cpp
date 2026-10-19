// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// --------------------------------------------------------------------------
// $Maintainer: Hannes Roest $
// $Authors: Hannes Roest $
// --------------------------------------------------------------------------

#include <OpenMS/FORMAT/HANDLERS/IndexedMzMLDecoder.h>
#include <expat.h>
#include <memory>
#include <exception>
#include <cstring>
#include <string_view>

#include <OpenMS/SYSTEM/File.h>

#include <boost/regex.hpp>
#include <boost/lexical_cast.hpp>

#include <limits>
#include <cstdint>
#include <algorithm>
#include <fstream>
#include <iostream>

namespace OpenMS
{

  namespace IndexedMzMLUtils
  {
    std::streampos stringToStreampos(const std::string& s)
    {
      // Try to cast the string to a type that can hold the integer value
      // stored in the std::streampos type (which can vary from 32 to 128 bits
      // depending on the system).
      //
      // long long has a minimal size of 64 bits and can address a range up to
      // 16 Exbibit (or 2 Exbibyte), we can hopefully expect our files to be
      // smaller than an Exabyte and should be safe.
      std::streampos res;
      try
      {

        res = boost::lexical_cast< unsigned long long >(s);
        // TESTING CAST: res = (int) res; // use this only when emulating 32 bit systems

      }
      catch (boost::bad_lexical_cast&)
      {
        std::cerr << "Trying to convert corrupted / unreadable value to std::streampos : " << s << std::endl;
        std::cerr << "This can also happen if the value exceeds 63 bits, please check your input." << std::endl;
        throw Exception::ConversionError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
            std::string("Could not convert string '") + s + "' to a 64 bit integer.");
      }

      // Check if the value can fit into std::streampos
      if ( std::abs( boost::lexical_cast< long double >(s) - res) > 0.1)
      {
        std::cerr << "Your system may not support addressing a file of this size,"
          << " only addresses that fit into a " << sizeof(std::streamsize)*8 <<
          " bit integer are supported on your system." << std::endl;
        throw Exception::ConversionError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
            std::string("Could not convert string '") + s + "' to an integer on your system.");
      }

      return res;
    }
  }

  int IndexedMzMLDecoder::parseOffsets(const std::string& filename, std::streampos indexoffset, OffsetVector& spectra_offsets, OffsetVector& chromatograms_offsets)
  {
    std::ifstream f(filename, std::ios::binary);
    if (!f.is_open())
    {
      if (!File::exists(filename))
      {
        throw Exception::FileNotFound(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, filename);
      }
      if (!File::readable(filename))
      {
        throw Exception::FileNotReadable(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, filename);
      }
      throw Exception::IOException(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, filename);
    }

    f.seekg(0, std::ios::end);
    const std::streampos length = f.tellg();
    if (!f || length < 0 || indexoffset < 0 || indexoffset > length)
    {
      std::cerr << "IndexedMzMLDecoder::parseOffsets Error: Offset was " << indexoffset
                << " (not between 0 and " << length << ").\n";
      return -1;
    }

    // Read straight into the final XML buffer: no raw allocation or full-tail copy.
    std::string xml = "<indexedmzML>";
    const Size prefix_size = xml.size();
    const std::streamoff tail_length = length - indexoffset;
    if (tail_length == 0 || tail_length > std::numeric_limits<std::streamsize>::max() ||
        static_cast<std::uintmax_t>(tail_length) > xml.max_size() - prefix_size - 1)
    {
      return -1;
    }
    const Size tail_size = static_cast<Size>(tail_length);
    xml.resize(prefix_size + tail_size + 1);
    f.seekg(indexoffset);
    if (!f) { return -1; }
    f.read(xml.data() + prefix_size, static_cast<std::streamsize>(tail_length));
    if (!f || f.gcount() != tail_length) { return -1; }
    xml.back() = '\n';
    return domParseIndexedEnd_(xml, spectra_offsets, chromatograms_offsets);
  }

  std::streampos IndexedMzMLDecoder::findIndexListOffset(const std::string& filename, int buffersize)
  {
    if (buffersize <= 0) { return -1; }
    std::ifstream f(filename, std::ios::binary);
    if (!f.is_open())
    {
      if (!File::exists(filename))
      {
        throw Exception::FileNotFound(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, filename);
      }
      if (!File::readable(filename))
      {
        throw Exception::FileNotReadable(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, filename);
      }
      throw Exception::IOException(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, filename);
    }

    f.seekg(0, std::ios::end);
    const std::streampos length = f.tellg();
    if (!f || length < 0) { return -1; }
    const std::streamoff read_length = std::min(static_cast<std::streamoff>(length), static_cast<std::streamoff>(buffersize));
    std::string buffer;
    if (read_length > std::numeric_limits<std::streamsize>::max() ||
        static_cast<std::uintmax_t>(read_length) > buffer.max_size()) { return -1; }
    buffer.resize(static_cast<Size>(read_length));
    f.seekg(-read_length, std::ios::end);
    if (!f) { return -1; }
    f.read(buffer.data(), static_cast<std::streamsize>(read_length));
    if (!f || f.gcount() != read_length) { return -1; }

    // The same namespace/whitespace-tolerant pattern is shared by independent
    // readers; C++ initializes it once and regex_search never mutates it.
    static const boost::regex listoffset_rx(R"(<[^>/]*indexListOffset\s*>\s*(\d*))");
    boost::smatch matches;
    if (!boost::regex_search(buffer, matches, listoffset_rx) || matches[1].length() == 0)
    {
      std::cerr << "IndexedMzMLDecoder::findIndexListOffset Error: Could not find element indexListOffset in the last "
                << read_length << " bytes. Maybe this is not an indexedMzML.\n";
      return -1;
    }
    return OpenMS::IndexedMzMLUtils::stringToStreampos(matches[1].str());
  }

  int IndexedMzMLDecoder::domParseIndexedEnd_(const std::string& in, OffsetVector& spectra_offsets, OffsetVector& chromatograms_offsets)
  {
    struct Footer
    {
      XML_Parser parser;
      std::exception_ptr exception;
      OffsetVector spectra, chromatograms, entries;
      std::string index_name, id, offset;
      Size depth = 0, list_depth = 0, index_depth = 0, offset_depth = 0, lists = 0;
      bool invalid_index = false, has_spectra = false, has_chromatograms = false;
      static const char* attribute(const XML_Char** attributes, const char* name)
      {
        for (Size i = 0; attributes[i]; i += 2)
        {
          if (std::strcmp(attributes[i], name) == 0) return attributes[i + 1];
        }
        return "";
      }
      void capture() noexcept
      {
        if (!exception) exception = std::current_exception();
        XML_StopParser(parser, XML_FALSE);
      }
      static void XMLCALL start(void* opaque, const XML_Char* name, const XML_Char** attributes) noexcept
      {
        auto& s = *static_cast<Footer*>(opaque);
        if (s.exception) return;
        try
        {
          ++s.depth;
          if (std::string_view(name) == "indexList" && s.depth > 1)
          {
            ++s.lists;
            s.list_depth = s.depth;
          }
          else if (s.list_depth && s.depth == s.list_depth + 1)
          {
            s.index_depth = s.depth;
            s.index_name = attribute(attributes, "name");
            s.entries.clear();
          }
          else if (s.index_depth && s.depth == s.index_depth + 1)
          {
            s.offset_depth = s.depth;
            s.id = attribute(attributes, "idRef");
            s.offset.clear();
          }
        }
        catch (...) { s.capture(); }
      }
      static void XMLCALL end(void* opaque, const XML_Char*) noexcept
      {
        auto& s = *static_cast<Footer*>(opaque);
        if (s.exception) return;
        try
        {
          if (s.depth == s.offset_depth)
          {
            s.entries.emplace_back(s.id, IndexedMzMLUtils::stringToStreampos(s.offset));
            s.offset_depth = 0;
          }
          if (s.depth == s.index_depth)
          {
            if (s.index_name == "spectrum") { s.spectra = std::move(s.entries); s.has_spectra = true; }
            else if (s.index_name == "chromatogram") { s.chromatograms = std::move(s.entries); s.has_chromatograms = true; }
            else { s.invalid_index = true; }
            s.index_depth = 0;
          }
          if (s.depth == s.list_depth) s.list_depth = 0;
          --s.depth;
        }
        catch (...) { s.capture(); }
      }
      static void XMLCALL text(void* opaque, const XML_Char* value, int length) noexcept
      {
        auto& s = *static_cast<Footer*>(opaque);
        if (s.exception) return;
        try { if (s.offset_depth) s.offset.append(value, static_cast<Size>(length)); }
        catch (...) { s.capture(); }
      }
    };
    std::unique_ptr<XML_ParserStruct, decltype(&XML_ParserFree)> parser(XML_ParserCreate(nullptr), XML_ParserFree);
    if (!parser) throw std::bad_alloc();
    Footer footer{};
    footer.parser = parser.get();
    XML_SetUserData(parser.get(), &footer);
    XML_SetElementHandler(parser.get(), Footer::start, Footer::end);
    XML_SetCharacterDataHandler(parser.get(), Footer::text);
    XML_SetParamEntityParsing(parser.get(), XML_PARAM_ENTITY_PARSING_NEVER);
    XML_SetExternalEntityRefHandler(parser.get(), [](XML_Parser, const XML_Char*, const XML_Char*, const XML_Char*, const XML_Char*) -> int { return XML_STATUS_ERROR; });
    for (Size offset = 0;;)
    {
      const auto count = std::min<Size>(65536, in.size() - offset);
      const bool final = offset + count == in.size();
      const auto status = XML_Parse(parser.get(), in.data() + offset, static_cast<int>(count), final);
      if (footer.exception) std::rethrow_exception(footer.exception);
      if (status == XML_STATUS_ERROR)
      {
        throw Exception::ParseError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "", XML_ErrorString(XML_GetErrorCode(parser.get())));
      }
      if (final) break;
      offset += count;
    }
    if (footer.lists != 1 || footer.invalid_index) return -1;
    if (footer.has_spectra) spectra_offsets = std::move(footer.spectra);
    if (footer.has_chromatograms) chromatograms_offsets = std::move(footer.chromatograms);
    return 0;
  }

}
