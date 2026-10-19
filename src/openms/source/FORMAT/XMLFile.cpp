// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// --------------------------------------------------------------------------
// $Maintainer: Timo Sachsenberg $
// $Authors: Marc Sturm $
// --------------------------------------------------------------------------

#include <OpenMS/FORMAT/XMLFile.h>

#include <OpenMS/CONCEPT/Init.h>

#include <OpenMS/CONCEPT/Macros.h>

#include <OpenMS/FORMAT/HANDLERS/XMLHandler.h>
#include <OpenMS/FORMAT/HANDLERS/XMLAttributes.h>
#include <pugixml.hpp>
#include <functional>
#include <array>
#include <xercesc/util/BinInputStream.hpp>
#include <OpenMS/SYSTEM/File.h>
#include <OpenMS/FORMAT/VALIDATORS/XMLValidator.h>

#include <OpenMS/FORMAT/CompressedInputSource.h>
#include <OpenMS/FORMAT/FileNameUtils.h>

#include <xercesc/framework/LocalFileInputSource.hpp>
#include <xercesc/framework/MemBufInputSource.hpp>

#include <xercesc/sax2/SAX2XMLReader.hpp>
#include <xercesc/sax2/XMLReaderFactory.hpp>

#include <zlib.h>
#include <bzlib.h>

#include <fstream>
#include <iomanip> // setprecision etc.
#include <streambuf>

#include <memory>
#include <xercesc/util/XMLString.hpp>

using namespace std;

namespace OpenMS::Internal
{

    /// This class ensures that the reset() method of the XMLHandler is called when it goes out of scope.
    /// useful when used in exception handling
    class XMLCleaner_
    {
public:
      explicit XMLCleaner_(XMLHandler * handler) :
        p_(handler)
      {

      }

      ~XMLCleaner_()
      {
        p_->reset();
      }

private:
      XMLHandler * p_;
    };

    XMLFile::XMLFile()
    = default;

    XMLFile::XMLFile(const std::string & schema_location, const std::string & version) :
      schema_location_(schema_location),
      schema_version_(version)
    {
    }

    XMLFile::~XMLFile()
    = default;

    void XMLFile::enforceEncoding_(const std::string& encoding)
    {
      enforced_encoding_ = encoding;
    }

    void parse(xercesc::InputSource* const source, XMLHandler* handler)
    {
      // Deliberately DOM-backed event delivery: this prototype measures the whole-file
      // memory cost of pugixml rather than claiming to supply streaming parsing.
      // ponytail: the DOM is O(file size); use a streaming backend for bounded-memory loads.
      auto utf16 = [](const char* value)
      {
        const auto wide = pugi::as_wide(value);
        std::u16string result;
        for (auto ch : wide)
        {
          const auto cp = static_cast<uint32_t>(ch);
          if constexpr (sizeof(wchar_t) == 2) result.push_back(static_cast<char16_t>(cp));
          else if (cp <= 0xffff) result.push_back(static_cast<char16_t>(cp));
          else
          {
            result.push_back(static_cast<char16_t>(0xd800 + ((cp - 0x10000) >> 10)));
            result.push_back(static_cast<char16_t>(0xdc00 + ((cp - 0x10000) & 0x3ff)));
          }
        }
        return result;
      };
      unique_ptr<xercesc::BinInputStream> stream(source->makeStream());
      if (!stream)
      {
        throw Exception::ParseError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "", "Cannot open XML input stream");
      }
      std::vector<char> input;
      std::array<XMLByte, 65536> chunk;
      XMLSize_t count;
      while ((count = stream->readBytes(chunk.data(), chunk.size())) != 0)
      {
        input.insert(input.end(), chunk.begin(), chunk.begin() + count);
      }
      pugi::xml_document document;
      // Keep whitespace text and CDATA so handler character data is preserved.
      pugi::xml_encoding encoding = pugi::encoding_auto;
      if (source->getEncoding())
      {
        const std::string requested = StringManager::convert(reinterpret_cast<const char16_t*>(source->getEncoding()));
        if (requested == "UTF-8" || requested == "utf-8") encoding = pugi::encoding_utf8;
        else if (requested == "UTF-16" || requested == "utf-16") encoding = pugi::encoding_utf16;
        else if (requested == "ISO-8859-1") encoding = pugi::encoding_latin1;
        else
        {
          throw Exception::ParseError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "", "Unsupported pugixml encoding override: " + requested);
        }
      }
      const auto status = document.load_buffer_inplace(input.data(), input.size(), pugi::parse_default | pugi::parse_ws_pcdata, encoding);
      if (!status)
      {
        throw Exception::ParseError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "",
            std::string("pugixml: ") + status.description() + " at byte " + std::to_string(status.offset));
      }
      std::function<void(pugi::xml_node)> visit = [&](pugi::xml_node node)
      {
        if (node.type() == pugi::node_element)
        {
          auto name = utf16(node.name());
          XMLAttributes::Values attributes;
          for (auto attr : node.attributes()) attributes.emplace_back(utf16(attr.name()), utf16(attr.value()));
          handler->onStartElement(name.c_str(), XMLAttributes(attributes));
          for (auto child : node.children()) visit(child);
          handler->onEndElement(name.c_str());
        }
        else if (node.type() == pugi::node_pcdata || node.type() == pugi::node_cdata)
        {
          auto text = utf16(node.value());
          handler->onCharacters(text.c_str(), text.size());
        }
      };
      try
      {
        for (auto child : document.children()) visit(child);
      }
      catch (const XMLHandler::EndParsingSoftly&)
      {
        // Early callback termination works, but the DOM has already been built.
      }
    }

    void XMLFile::parse_(const std::string & filename, XMLHandler * handler)
    {
      // ensure handler->reset() is called to save memory (in case the XMLFile
      // reader, e.g. FeatureXMLFile, is used again)
      XMLCleaner_ clean(handler);

      StringManager sm;
      //try to open file
      if (!File::exists(filename))
      {
        throw Exception::FileNotFound(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, filename);
      }

      // initialize parser
      try
      {
        Internal::xercesInitialize(); // serialised: Xerces requires it, and parseBuffer_() runs on several threads at once
      }
      catch (const xercesc::XMLException & toCatch)
      {
        throw Exception::ParseError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
            "",std::string("Error during initialization: ") + StringManager().convert(toCatch.getMessage()));
      }


      // peak ahead into the file: is it bzip2 or gzip compressed?
      std::string bz;
      {
        std::ifstream file(filename.c_str());
        char tmp_bz[3];
        file.read(tmp_bz, 2);
        tmp_bz[2] = '\0';
        bz =std::string(tmp_bz);
      }

      unique_ptr<xercesc::InputSource> source;

      char g1 = 0x1f;
      char g2 = 0;
      g2 |= 1 << 7;
      g2 |= 1 << 3;
      g2 |= 1 << 1;
      g2 |= 1 << 0;
      //g2 = static_cast<char>(0x8b); // can make troubles if it is casted to 0x7F which is the biggest number signed char can save
      if ((bz[0] == 'B' && bz[1] == 'Z') || (bz[0] == g1 && bz[1] == g2) || (bz[0] == 'P' && bz[1] == 'K'))
      {
        source.reset(new CompressedInputSource(sm.convert(filename).c_str(), bz));
      }
      else
      {
        source.reset(new xercesc::LocalFileInputSource(sm.convert(filename).c_str()));
      }
      // what if no encoding given http://xerces.apache.org/xerces-c/apiDocs-3/classInputSource.html
      if (!enforced_encoding_.empty())
      {
        static const XMLCh* s_enc = xercesc::XMLString::transcode(enforced_encoding_.c_str());
        source->setEncoding(s_enc);
      }
      
      parse(source.get(), handler);
    }

    void XMLFile::parseBuffer_(const std::string & buffer, XMLHandler * handler)
    {
      // ensure handler->reset() is called to save memory (in case the XMLFile
      // reader, e.g. FeatureXMLFile, is used again)
      XMLCleaner_ clean(handler);

      StringManager sm;

      // initialize parser
      try
      {
        Internal::xercesInitialize(); // serialised: Xerces requires it, and parseBuffer_() runs on several threads at once
      }
      catch (const xercesc::XMLException & toCatch)
      {
        throw Exception::ParseError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
            "",std::string("Error during initialization: ") + StringManager().convert(toCatch.getMessage()));
      }

      // TODO: handle non-plain text
      // peak ahead into the file: is it bzip2 or gzip compressed?
      // std::string bz = StringUtils::substr(buffer, 0, 2);

      unique_ptr<xercesc::InputSource> source;
      {
        auto fake_id = sm.convert("inMemory");
        source.reset(new xercesc::MemBufInputSource(reinterpret_cast<const unsigned char *>(buffer.c_str()), buffer.size(), fake_id.c_str()));
      }
      // what if no encoding given http://xerces.apache.org/xerces-c/apiDocs-3/classInputSource.html
      if (!enforced_encoding_.empty())
      {
        static const XMLCh* s_enc = xercesc::XMLString::transcode(enforced_encoding_.c_str());
        source->setEncoding(s_enc);
      }
      
      parse(source.get(), handler);
    }

    void XMLFile::save_(const std::string & filename, XMLHandler * handler) const
    {
      // Detect compression from filename extension, in any letter case like on input (and in TOPPBase's check)
      const FileTypes::Type compression = FileNameUtils::compressionType(filename);
      const bool use_gzip = compression == FileTypes::GZ;
      const bool use_bzip2 = compression == FileTypes::BZ2;

      if (use_gzip)
      {
        // Minimal std::streambuf that writes gzip-compressed data via zlib
        class GzipOStreambuf : public std::streambuf
        {
        public:
          enum { BUF_SIZE = 65536 };

          explicit GzipOStreambuf(const char* fn) : gz_(gzopen(fn, "wb"))
          {
            if (gz_) setp(buf_, buf_ + BUF_SIZE);
          }

          ~GzipOStreambuf()
          {
            flush_buffer();
            if (gz_) gzclose(gz_);
          }

          bool is_open() const { return gz_ != nullptr; }

        protected:
          int_type overflow(int_type c) override
          {
            if (!gz_) return traits_type::eof();
            if (pptr() == epptr() && !flush_buffer()) return traits_type::eof();
            if (!traits_type::eq_int_type(c, traits_type::eof()))
            {
              *pptr() = traits_type::to_char_type(c);
              pbump(1);
            }
            return traits_type::not_eof(c);
          }

          int sync() override { return flush_buffer() ? 0 : -1; }

        private:
          bool flush_buffer()
          {
            int n = static_cast<int>(pptr() - pbase());
            if (n > 0)
            {
              if (gzwrite(gz_, pbase(), static_cast<unsigned>(n)) != n) return false;
              setp(buf_, buf_ + BUF_SIZE);
            }
            return true;
          }

          gzFile gz_;
          char buf_[BUF_SIZE];
        };

        GzipOStreambuf sbuf(filename.c_str());
        if (!sbuf.is_open())
        {
          throw Exception::UnableToCreateFile(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, filename);
        }
        std::ostream os(&sbuf);
        os.precision(writtenDigits(double()));
        handler->writeTo(os);
      }
      else if (use_bzip2)
      {
        // Minimal std::streambuf that writes bzip2-compressed data via bzlib
        class Bzip2OStreambuf : public std::streambuf
        {
        public:
          enum { BUF_SIZE = 65536 };

          explicit Bzip2OStreambuf(const char* fn) : file_(nullptr), bz_(nullptr)
          {
            file_ = fopen(fn, "wb");
            if (!file_) return;
            int err = BZ_OK;
            bz_ = BZ2_bzWriteOpen(&err, file_, 9, 0, 0);
            if (err != BZ_OK)
            {
              BZ2_bzWriteClose(&err, bz_, 1, nullptr, nullptr);
              bz_ = nullptr;
              fclose(file_);
              file_ = nullptr;
              return;
            }
            setp(buf_, buf_ + BUF_SIZE);
          }

          ~Bzip2OStreambuf()
          {
            flush_buffer();
            if (bz_)
            {
              int err = BZ_OK;
              BZ2_bzWriteClose(&err, bz_, 0, nullptr, nullptr);
            }
            if (file_) fclose(file_);
          }

          bool is_open() const { return bz_ != nullptr; }

        protected:
          int_type overflow(int_type c) override
          {
            if (!bz_) return traits_type::eof();
            if (pptr() == epptr() && !flush_buffer()) return traits_type::eof();
            if (!traits_type::eq_int_type(c, traits_type::eof()))
            {
              *pptr() = traits_type::to_char_type(c);
              pbump(1);
            }
            return traits_type::not_eof(c);
          }

          int sync() override { return flush_buffer() ? 0 : -1; }

        private:
          bool flush_buffer()
          {
            if (!bz_) return false;
            int n = static_cast<int>(pptr() - pbase());
            if (n > 0)
            {
              int err = BZ_OK;
              BZ2_bzWrite(&err, bz_, pbase(), n);
              if (err != BZ_OK && err != BZ_RUN_OK) return false;
              setp(buf_, buf_ + BUF_SIZE);
            }
            return true;
          }

          FILE* file_;
          BZFILE* bz_;
          char buf_[BUF_SIZE];
        };

        Bzip2OStreambuf sbuf(filename.c_str());
        if (!sbuf.is_open())
        {
          throw Exception::UnableToCreateFile(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, filename);
        }
        std::ostream os(&sbuf);
        os.precision(writtenDigits(double()));
        handler->writeTo(os);
      }
      else
      {
        // Uncompressed: open in binary mode to avoid any line ending conversions
        std::ofstream os(filename.c_str(), std::ios::out | std::ios::binary);
        os.precision(writtenDigits(double()));
        if (!os)
        {
          throw Exception::UnableToCreateFile(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, filename);
        }
        handler->writeTo(os);
        os.close();
      }
    }

    std::string encodeTab(const std::string& to_encode)
    {
      if (!StringUtils::has(to_encode, '\t'))
      {
        return to_encode;
      }
      else
      {
        std::string result = to_encode;
        StringUtils::substitute(result, "\t", "&#x9;");
        return result;
      }
    }

    bool XMLFile::isValid(const std::string & filename, std::ostream & os)
    {
      if (schema_location_.empty())
      {
        throw Exception::NotImplemented(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION);
      }
      std::string current_location = File::find(schema_location_);
      return XMLValidator().isValid(filename, current_location, os);
    }

    const std::string & XMLFile::getVersion() const
    {
      return schema_version_;
    }

} // namespace OpenMS  // namespace Internal
