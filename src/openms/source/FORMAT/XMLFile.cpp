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
#include <expat.h>
#include <OpenMS/SYSTEM/File.h>
#include <OpenMS/FORMAT/VALIDATORS/XMLValidator.h>

#include <OpenMS/FORMAT/CompressedInputSource.h>
#include <OpenMS/FORMAT/FileNameUtils.h>

#include <xercesc/framework/LocalFileInputSource.hpp>
#include <xercesc/framework/MemBufInputSource.hpp>

#include <xercesc/util/BinInputStream.hpp>

#include <zlib.h>
#include <bzlib.h>

#include <fstream>
#include <iomanip> // setprecision etc.
#include <streambuf>

#include <memory>
#include <array>
#include <exception>
#include <string_view>
#include <vector>
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

    namespace
    {
      static_assert(sizeof(XML_Char) == 1, "This adapter requires UTF-8 Expat callbacks.");

      // Expat validates UTF-8 before callbacks; OpenMS handlers still consume UTF-16.
      std::u16string utf16(std::string_view text)
      {
        std::u16string result;
        result.reserve(text.size());
        for (Size i = 0; i < text.size();)
        {
          unsigned char lead = static_cast<unsigned char>(text[i++]);
          unsigned code = lead;
          unsigned continuation = 0;
          if (lead >= 0xf0) { code &= 0x07; continuation = 3; }
          else if (lead >= 0xe0) { code &= 0x0f; continuation = 2; }
          else if (lead >= 0xc0) { code &= 0x1f; continuation = 1; }
          for (unsigned j = 0; j < continuation; ++j)
          {
            code = (code << 6) | (static_cast<unsigned char>(text[i++]) & 0x3f);
          }
          if (code > 0xffff)
          {
            code -= 0x10000;
            result.push_back(static_cast<char16_t>(0xd800 + (code >> 10)));
            result.push_back(static_cast<char16_t>(0xdc00 + (code & 0x3ff)));
          }
          else result.push_back(static_cast<char16_t>(code));
        }
        return result;
      }

      struct ExpatCallbacks
      {
        XML_Parser parser;
        XMLHandler& handler;
        std::exception_ptr exception;

        template <typename Callback>
        void invoke(Callback&& callback) noexcept
        {
          // Never unwind a C++ exception through Expat's C stack.
          if (exception) return;
          try { callback(); }
          catch (...)
          {
            exception = std::current_exception();
            XML_StopParser(parser, XML_FALSE);
          }
        }

        static void XMLCALL start(void* data, const XML_Char* name, const XML_Char** attributes) noexcept
        {
          auto& self = *static_cast<ExpatCallbacks*>(data);
          self.invoke([&]
          {
            const auto tag = utf16(name);
            std::vector<std::u16string> strings;
            for (Size i = 0; attributes[i]; ++i) strings.push_back(utf16(attributes[i]));
            std::vector<const char16_t*> pairs;
            pairs.reserve(strings.size() + 1);
            for (const auto& value : strings) pairs.push_back(value.c_str());
            pairs.push_back(nullptr);
            self.handler.onStartElement(tag.c_str(), XMLAttributes(pairs.data()));
          });
        }

        static void XMLCALL end(void* data, const XML_Char* name) noexcept
        {
          auto& self = *static_cast<ExpatCallbacks*>(data);
          self.invoke([&]
          {
            const auto tag = utf16(name);
            self.handler.onEndElement(tag.c_str());
          });
        }

        static void XMLCALL characters(void* data, const XML_Char* text, int length) noexcept
        {
          auto& self = *static_cast<ExpatCallbacks*>(data);
          self.invoke([&]
          {
            const auto value = utf16(std::string_view(text, static_cast<Size>(length)));
            self.handler.onCharacters(value.c_str(), value.size());
          });
        }
      };
    }

    void parse(xercesc::InputSource* source, XMLHandler* handler, const std::string& encoding)
    {
      // Reuse the existing bounded-memory plain/compressed streams. Xerces remains
      // a dependency for these stream adapters, DOM readers and XSD validation.
      unique_ptr<XML_ParserStruct, decltype(&XML_ParserFree)> parser(
        XML_ParserCreate(encoding.empty() ? nullptr : encoding.c_str()), XML_ParserFree);
      if (!parser) throw std::bad_alloc();
      ExpatCallbacks callbacks{parser.get(), *handler, {}};
      XML_SetUserData(parser.get(), &callbacks);
      XML_SetElementHandler(parser.get(), ExpatCallbacks::start, ExpatCallbacks::end);
      XML_SetCharacterDataHandler(parser.get(), ExpatCallbacks::characters);
      // Ordinary OpenMS SAX reads use qualified names without namespace expansion.
      // External entities are rejected; parameter entity parsing is disabled.
      XML_SetParamEntityParsing(parser.get(), XML_PARAM_ENTITY_PARSING_NEVER);
      XML_SetExternalEntityRefHandler(parser.get(), [](XML_Parser, const XML_Char*, const XML_Char*, const XML_Char*, const XML_Char*) -> int { return XML_STATUS_ERROR; });
      try
      {
        unique_ptr<xercesc::BinInputStream> stream(source->makeStream());
        if (!stream) throw Exception::ParseError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "", "Cannot open XML input stream");
        std::array<XMLByte, 65536> buffer;
        for (;;)
        {
          const auto length = stream->readBytes(buffer.data(), buffer.size());
          const auto status = XML_Parse(parser.get(), reinterpret_cast<const char*>(buffer.data()), static_cast<int>(length), length == 0);
          if (callbacks.exception) std::rethrow_exception(callbacks.exception);
          if (status == XML_STATUS_ERROR)
          {
            handler->fatalError(XMLHandler::LOAD, XML_ErrorString(XML_GetErrorCode(parser.get())),
                                static_cast<UInt>(XML_GetCurrentLineNumber(parser.get())),
                                static_cast<UInt>(XML_GetCurrentColumnNumber(parser.get()) + 1));
          }
          if (length == 0) break;
        }
      }
      catch (const xercesc::XMLException& error)
      {
        throw Exception::ParseError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "", StringManager::convert(error.getMessage()));
      }
      catch (const XMLHandler::EndParsingSoftly&)
      {
        // Expected early termination (metadata/size-only reads).
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
        char tmp_bz[3] = {};
        file.read(tmp_bz, 2);
        tmp_bz[2] = '\0';
        bz = std::string(tmp_bz, 2);
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
      parse(source.get(), handler, enforced_encoding_);
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
      parse(source.get(), handler, enforced_encoding_);
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
