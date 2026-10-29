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

START_SECTION((static bool anchorStretch(...)))
{
  const String seq = "MKAAGGLSVPKTEEFRDDMNPQRWYHAACKKGSLTV"; // 35 residues
  std::vector<double> pro = {0.0};
  for (char aa : seq) pro.push_back(pro.back() + ResidueDB::getInstance()->getResidue(aa)->getMonoWeight(Residue::Internal));
  const double water = Residue::getInternalToFull().getMonoWeight(), iso = Constants::C13C12_MASSDIFF_U;
  const auto mass_of = [&](int a, int b) { return pro[b] - pro[a] + water; };
  const std::vector<double> pre {Residue::getInternalToBIon().getMonoWeight()}, suf {Residue::getInternalToYIon().getMonoWeight()};
  // observed fragments of the proteoform 6..24 (0-based residues [6, 24)): b3, b5 and y4
  const auto frags_of = [&](int a, int b) {
    std::vector<double> f {pro[a + 3] - pro[a] + pre[0], pro[a + 5] - pro[a] + pre[0], pro[b] - pro[b - 4] + suf[0]};
    std::sort(f.begin(), f.end());
    return f;
  };
  std::vector<int> ms, me;
  std::vector<double> mm;
  int a = -1, b = -1, k = 9, support = 0;
  bool acetyl = true;
  // a terminal result 0..35 (both ends at the protein ends) and a precursor of 6..24: both ends move to the fragment-supported stretch
  bool ok = FLASHExtenderAlgorithm::anchorStretch(pro, seq, 0, 35, 10, 18, ms, me, mm, frags_of(6, 24), pre, suf, 10e-6, mass_of(6, 24), a, b, k, acetyl, support);
  TEST_EQUAL(ok, true)
  TEST_EQUAL(a, 6)
  TEST_EQUAL(b, 24)
  TEST_EQUAL(k, 0)
  TEST_EQUAL(acetyl, false)
  TEST_EQUAL(support, 3)
  // an end no fragment reads is no anchor: without the y ion nothing fits
  std::vector<double> only_b {pro[9] - pro[6] + pre[0], pro[11] - pro[6] + pre[0]};
  ok = FLASHExtenderAlgorithm::anchorStretch(pro, seq, 0, 35, 10, 18, ms, me, mm, only_b, pre, suf, 10e-6, mass_of(6, 24), a, b, k, acetyl, support);
  TEST_EQUAL(ok, false)
  // the residues the terminal paths read stay inside: a core reaching residue 26 rules the stretch out
  ok = FLASHExtenderAlgorithm::anchorStretch(pro, seq, 0, 35, 10, 27, ms, me, mm, frags_of(6, 24), pre, suf, 10e-6, mass_of(6, 24), a, b, k, acetyl, support);
  TEST_EQUAL(ok, false)
  // a terminal stretch that already fits stays where it is (unmoved), also with a precursor one isotope high
  ok = FLASHExtenderAlgorithm::anchorStretch(pro, seq, 6, 24, 10, 18, ms, me, mm, frags_of(6, 24), pre, suf, 10e-6, mass_of(6, 24) + iso, a, b, k, acetyl, support);
  TEST_EQUAL(ok, true)
  TEST_EQUAL(a, 6)
  TEST_EQUAL(b, 24)
  TEST_EQUAL(k, 1)
  // an acetylated protein N-terminus after the initiator Met: residues [1, 20) + 42.01, the b ions carry the acetyl
  std::vector<double> f_ac {pro[4] - pro[1] + 42.010565 + pre[0], pro[20] - pro[16] + suf[0]};
  std::sort(f_ac.begin(), f_ac.end());
  ok = FLASHExtenderAlgorithm::anchorStretch(pro, seq, 1, -1, 5, 10, ms, me, mm, f_ac, pre, suf, 10e-6, mass_of(1, 20) + 42.010565, a, b, k, acetyl, support);
  TEST_EQUAL(ok, true)
  TEST_EQUAL(a, 1)
  TEST_EQUAL(b, 20)
  TEST_EQUAL(acetyl, true)
  // a modification inside counts in the mass and in the fragments past it; one cut by the stretch rules it out
  ms = {12}; me = {12}; mm = {79.966331};
  std::vector<double> f_mod {pro[9] - pro[6] + pre[0], pro[24] - pro[12] + 79.966331 + suf[0]};
  std::sort(f_mod.begin(), f_mod.end());
  ok = FLASHExtenderAlgorithm::anchorStretch(pro, seq, 0, 35, 10, 18, ms, me, mm, f_mod, pre, suf, 10e-6, mass_of(6, 24) + 79.966331, a, b, k, acetyl, support);
  TEST_EQUAL(ok, true)
  TEST_EQUAL(a, 6)
  TEST_EQUAL(b, 24)
  ms = {5}; me = {7}; mm = {79.966331}; // a range [5, 7] that the start 6 would cut
  ok = FLASHExtenderAlgorithm::anchorStretch(pro, seq, 0, 35, 10, 18, ms, me, mm, frags_of(6, 24), pre, suf, 10e-6, mass_of(6, 24), a, b, k, acetyl, support);
  TEST_EQUAL(ok, false)
}
END_SECTION

START_SECTION((truncation_penalty))
{
  TEST_EQUAL(FLASHExtenderAlgorithm::truncation_penalty, 19)
}
END_SECTION

END_TEST
