// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// --------------------------------------------------------------------------
// $Maintainer: Kyowon Jeong $
// $Authors: Oliver Kohlbacher $
// --------------------------------------------------------------------------

#pragma once

#include <cstdlib>
#include <cstring>

namespace OpenMS
{
  /// TEMPORARY (ablation build, not for merging): whether the always-on fix @p name (cascade, tiebreak, duplicate) is switched back to
  /// upstream da4ee8eb78's behaviour, by its name in the comma-separated environment variable FLASHTNT_ABLATE
  inline bool flashAblated(const char* name)
  {
    const char* list = std::getenv("FLASHTNT_ABLATE");
    return list != nullptr && std::strstr(list, name) != nullptr;
  }
} // namespace OpenMS
