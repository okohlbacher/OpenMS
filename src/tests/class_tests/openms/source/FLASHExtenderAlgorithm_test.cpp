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
#include <OpenMS/CHEMISTRY/Residue.h>
#include <OpenMS/CHEMISTRY/ResidueDB.h>
#include <set>

using namespace OpenMS;

// the mass closure of a terminal result (option mass_closure) on a synthetic protein
START_TEST(FLASHExtenderAlgorithm, "$Id$")

START_SECTION((static bool closeMass(...)))
{
  const String seq = "MKAAGGLSVPKTEEFRDDMNPQRWYHAACKKGSLTV"; // 35 residues
  std::vector<double> pro = {0.0};
  for (char aa : seq) pro.push_back(pro.back() + ResidueDB::getInstance()->getResidue(aa)->getMonoWeight(Residue::Internal));
  const double water = Residue::getInternalToFull().getMonoWeight();
  const auto mass_of = [&](int a, int b) { return pro[b] - pro[a] + water; };
  int a = -1, b = -1;
  double shift = 0;
  const char* name = nullptr;
  std::vector<int> ms, me;
  std::vector<double> mm;
  // the start is kept (residue 2, after the Met), the end moves to where the mass fits: residues 2..20
  bool ok = FLASHExtenderAlgorithm::closeMass(pro, seq, 1, 35, true, {5, 9}, ms, me, mm, mass_of(1, 20), 0.01, 500.0, a, b, shift, name);
  TEST_EQUAL(ok, true)
  TEST_EQUAL(a, 1)
  TEST_EQUAL(b, 20)
  TEST_EQUAL(shift, 0.0)
  TEST_STRING_EQUAL(name, "none")
  // the kept ladder bounds the moved terminus: a cleavage read at position 25 cannot be cut off
  ok = FLASHExtenderAlgorithm::closeMass(pro, seq, 1, 35, true, {25}, ms, me, mm, mass_of(1, 20), 0.01, 500.0, a, b, shift, name);
  TEST_EQUAL(ok, false)
  // the end is kept (the C-terminus), the start moves: residues 12..35
  ok = FLASHExtenderAlgorithm::closeMass(pro, seq, 0, 35, false, {30}, ms, me, mm, mass_of(12, 35), 0.01, 500.0, a, b, shift, name);
  TEST_EQUAL(ok, true)
  TEST_EQUAL(a, 12)
  TEST_EQUAL(b, 35)
  // an isotope error of the precursor mass is explained and not added to the proteoform
  ok = FLASHExtenderAlgorithm::closeMass(pro, seq, 0, 35, false, {}, ms, me, mm, mass_of(12, 35) + Constants::C13C12_MASSDIFF_U, 0.01, 500.0, a, b, shift, name);
  TEST_EQUAL(ok, true)
  TEST_STRING_EQUAL(name, "+1 isotope")
  // N-terminal acetylation only at the protein N-terminus: 1..20 + 42.01 fits (start 0), 12..35 + 42.01 does not
  ok = FLASHExtenderAlgorithm::closeMass(pro, seq, 0, 35, true, {}, ms, me, mm, mass_of(0, 20) + 42.010565, 0.01, 500.0, a, b, shift, name);
  TEST_EQUAL(ok, true)
  TEST_STRING_EQUAL(name, "acetyl")
  TEST_EQUAL(b, 20)
  ok = FLASHExtenderAlgorithm::closeMass(pro, seq, 12, 35, true, {}, ms, me, mm, mass_of(12, 35) + 42.010565, 0.01, 500.0, a, b, shift, name);
  TEST_EQUAL(ok, false)
  // a modification inside the stretch counts; a precursor nothing fits returns false
  ms = {15}; me = {15}; mm = {79.966};
  ok = FLASHExtenderAlgorithm::closeMass(pro, seq, 1, 35, true, {}, ms, me, mm, mass_of(1, 20) + 79.966, 0.01, 500.0, a, b, shift, name);
  TEST_EQUAL(ok, true)
  TEST_EQUAL(b, 20)
  ok = FLASHExtenderAlgorithm::closeMass(pro, seq, 1, 35, true, {}, ms, me, mm, 123456.7, 0.01, 500.0, a, b, shift, name);
  TEST_EQUAL(ok, false)
}
END_SECTION

START_SECTION((truncation_penalty))
{
  TEST_EQUAL(FLASHExtenderAlgorithm::truncation_penalty, 19)
}
END_SECTION

END_TEST
