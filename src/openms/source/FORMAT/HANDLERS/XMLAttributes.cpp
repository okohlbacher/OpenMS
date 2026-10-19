// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// --------------------------------------------------------------------------
// $Maintainer: Timo Sachsenberg $
// $Authors: Timo Sachsenberg $
// --------------------------------------------------------------------------

#include <OpenMS/FORMAT/HANDLERS/XMLAttributes.h>

#include <xercesc/sax2/Attributes.hpp>
#include <string_view>
#include <xercesc/util/XMLString.hpp>
#include <xercesc/util/TransService.hpp>
#include <cstring>

namespace OpenMS::Internal
{
  // XMLCh is guaranteed to match char16_t in size; the attribute values are
  // consumed purely as UTF-16 code units, so the reinterpret_cast at this
  // boundary is well-defined for our use.
  static_assert(sizeof(::XMLCh) == sizeof(char16_t), "XMLCh is not sized correctly for UTF-16.");

  namespace
  {
    inline const xercesc::Attributes* attrs(const void* handle)
    {
      return static_cast<const xercesc::Attributes*>(handle);
    }

    bool equalsASCII(const char16_t* wide, const char* ascii)
    {
      while (*ascii && *wide == static_cast<unsigned char>(*ascii))
      {
        ++wide;
        ++ascii;
      }
      return *ascii == 0 && *wide == 0;
    }
  }

  const char16_t* XMLAttributes::value(const char16_t* qname) const
  {
    if (pairs_)
    {
      const auto i = index(qname);
      return i < 0 ? nullptr : pairs_[2 * i + 1];
    }
    return reinterpret_cast<const char16_t*>(attrs(attributes_)->getValue(reinterpret_cast<const ::XMLCh*>(qname)));
  }

  const char16_t* XMLAttributes::value(const char* qname) const
  {
    if (pairs_)
    {
      bool ascii = true;
      for (const auto* ch = qname; *ch; ++ch)
      {
        if (static_cast<unsigned char>(*ch) > 127) { ascii = false; break; }
      }
      if (ascii)
      {
        // XML vocabulary names are usually ASCII; avoid allocating a transcoder.
        for (Size i = 0; pairs_[2 * i]; ++i)
        {
          if (equalsASCII(pairs_[2 * i], qname)) return pairs_[2 * i + 1];
        }
        return nullptr;
      }
      // Expat names are UTF-8 regardless of the process locale.
      const xercesc::TranscodeFromStr name(reinterpret_cast<const XMLByte*>(qname), std::strlen(qname), "UTF-8");
      return value(reinterpret_cast<const char16_t*>(name.str()));
    }
    ::XMLCh* transcoded = xercesc::XMLString::transcode(qname);
    const char16_t* val = value(reinterpret_cast<const char16_t*>(transcoded));
    xercesc::XMLString::release(&transcoded);
    return val;
  }

  SignedSize XMLAttributes::index(const char16_t* qname) const
  {
    if (pairs_)
    {
      for (SignedSize i = 0; pairs_[2 * i]; ++i)
      {
        if (std::u16string_view(pairs_[2 * i]) == qname) return i;
      }
      return -1;
    }
    return static_cast<SignedSize>(attrs(attributes_)->getIndex(reinterpret_cast<const ::XMLCh*>(qname)));
  }

  const char16_t* XMLAttributes::valueByIndex(Size i) const
  {
    if (pairs_)
    {
      for (Size j = 0; pairs_[2 * j]; ++j)
      {
        if (i == j) return pairs_[2 * j + 1];
      }
      return nullptr;
    }
    return reinterpret_cast<const char16_t*>(attrs(attributes_)->getValue(static_cast<XMLSize_t>(i)));
  }

} // namespace OpenMS::Internal
