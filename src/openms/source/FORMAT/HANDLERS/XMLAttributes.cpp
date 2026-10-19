// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// --------------------------------------------------------------------------
// $Maintainer: Timo Sachsenberg $
// $Authors: Timo Sachsenberg $
// --------------------------------------------------------------------------

#include <OpenMS/FORMAT/HANDLERS/XMLAttributes.h>

#include <xercesc/sax2/Attributes.hpp>
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
  }

  const char16_t* XMLAttributes::value(const char16_t* qname) const
  {
    if (native_)
    {
      for (const auto& item : *static_cast<const Values*>(attributes_))
      {
        if (item.first == qname) return item.second.c_str();
      }
      return nullptr;
    }
    return reinterpret_cast<const char16_t*>(attrs(attributes_)->getValue(reinterpret_cast<const ::XMLCh*>(qname)));
  }

  const char16_t* XMLAttributes::value(const char* qname) const
  {
    // Narrow OpenMS names are UTF-8, irrespective of the process locale.
    const xercesc::TranscodeFromStr transcoded(reinterpret_cast<const XMLByte*>(qname), std::strlen(qname), "UTF-8");
    return value(reinterpret_cast<const char16_t*>(transcoded.str()));
  }

  SignedSize XMLAttributes::index(const char16_t* qname) const
  {
    if (native_)
    {
      const auto& values = *static_cast<const Values*>(attributes_);
      for (Size i = 0; i < values.size(); ++i) if (values[i].first == qname) return i;
      return -1;
    }
    return static_cast<SignedSize>(attrs(attributes_)->getIndex(reinterpret_cast<const ::XMLCh*>(qname)));
  }

  const char16_t* XMLAttributes::valueByIndex(Size i) const
  {
    if (native_)
    {
      const auto& values = *static_cast<const Values*>(attributes_);
      return i < values.size() ? values[i].second.c_str() : nullptr;
    }
    return reinterpret_cast<const char16_t*>(attrs(attributes_)->getValue(static_cast<XMLSize_t>(i)));
  }

} // namespace OpenMS::Internal
