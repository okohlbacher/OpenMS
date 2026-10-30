// Copyright (c) 2002-present, OpenMS Inc., OpenMS Team -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// --------------------------------------------------------------------------
// $Maintainer: Kyowon Jeong $
// $Authors: Oliver Kohlbacher $
// --------------------------------------------------------------------------

#include <OpenMS/CONCEPT/ClassTest.h>
#include <OpenMS/test_config.h>

#include <OpenMS/ANALYSIS/TOPDOWN/FLASHExtenderAlgorithm.h>

using namespace OpenMS;

// the truncation penalty FLASHTnT's precursor re-selection allows for, and the defaults of the precursor-mass options
START_TEST(FLASHExtenderAlgorithm, "$Id$")

START_SECTION((truncation_penalty))
{
  TEST_EQUAL(FLASHExtenderAlgorithm::truncation_penalty, 19)
}
END_SECTION

START_SECTION((FLASHExtenderAlgorithm()))
{
  const Param p = FLASHExtenderAlgorithm().getDefaults();
  TEST_STRING_EQUAL(p.getValue("skip_precursor_inference").toString(), "false")
  TEST_EQUAL(p.getValidStrings("skip_precursor_inference").size(), 3)
  TEST_STRING_EQUAL(p.getValue("ladder_end_penalty").toString(), "true")
  TEST_EQUAL(p.getValidStrings("ladder_end_penalty").size(), 2)
  TEST_EQUAL(p.exists("mass_closure"), false)
}
END_SECTION

END_TEST
