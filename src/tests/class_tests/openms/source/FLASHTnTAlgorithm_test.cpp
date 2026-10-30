// Copyright (c) 2002-present, OpenMS Inc., OpenMS Team -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// --------------------------------------------------------------------------
// $Maintainer: Kyowon Jeong $
// $Authors: Oliver Kohlbacher $
// --------------------------------------------------------------------------

#include <OpenMS/CONCEPT/ClassTest.h>
#include <OpenMS/test_config.h>

#include <OpenMS/ANALYSIS/TOPDOWN/FLASHTnTAlgorithm.h>
#include <OpenMS/METADATA/ProteinHit.h>
#include <set>
#include <functional>
#include <OpenMS/ANALYSIS/TOPDOWN/DeconvolvedSpectrum.h>

using namespace OpenMS;

// The decisions of the FDR rules: the protein evidence rule (option protein_evidence), the entry order that breaks candidate-cut
// ties, the blind modification count the evidence rule reads, the grouping of small proteoform classes (option merge_small_classes),
// the window masses of DeconvMassInfo (option precursor_reselect), and the defaults of the options.
START_TEST(FLASHTnTAlgorithm, "$Id$")

START_SECTION((static bool proteinEvidenceSupported(Size proteoforms, bool strong)))
{
  // two distinct proteoforms, or one strong proteoform
  TEST_EQUAL(FLASHTnTAlgorithm::proteinEvidenceSupported(1, false), false)
  TEST_EQUAL(FLASHTnTAlgorithm::proteinEvidenceSupported(2, false), true)
  TEST_EQUAL(FLASHTnTAlgorithm::proteinEvidenceSupported(1, true), true)
  TEST_EQUAL(FLASHTnTAlgorithm::proteinEvidenceSupported(0, false), false)
}
END_SECTION

START_SECTION((static std::uint64_t entryOrder(std::uint64_t index)))
{
  // deterministic, collision-free on the first entries, and not the database order: about half the consecutive pairs ascend
  std::set<std::uint64_t> seen;
  Size ascending = 0;
  for (std::uint64_t i = 0; i < 1000; i++)
  {
    TEST_EQUAL(FLASHTnTAlgorithm::entryOrder(i), FLASHTnTAlgorithm::entryOrder(i))
    seen.insert(FLASHTnTAlgorithm::entryOrder(i));
    if (i > 0 && FLASHTnTAlgorithm::entryOrder(i) > FLASHTnTAlgorithm::entryOrder(i - 1)) ascending++;
  }
  TEST_EQUAL(seen.size(), 1000)
  TEST_EQUAL(ascending > 400 && ascending < 600, true)
  TEST_EQUAL(FLASHTnTAlgorithm::entryOrder(0) == 0, false)
}
END_SECTION

START_SECTION((static Size blindModCount(const ProteinHit& hit)))
{
  ProteinHit h;
  h.setMetaValue("Modifications", DoubleList {15.99, 42.01});
  TEST_EQUAL(FLASHTnTAlgorithm::blindModCount(h), 2) // without the kinds, every modification counts as blind
  h.setMetaValue("ModificationVariable", IntList {1, 0}); // one variable, one blind
  TEST_EQUAL(FLASHTnTAlgorithm::blindModCount(h), 1)
  h.setMetaValue("ModificationVariable", IntList {1, 2}); // one variable, one fixed by the database entry
  TEST_EQUAL(FLASHTnTAlgorithm::blindModCount(h), 0)
  h.setMetaValue("BlindModCount", 1); // the search's own count wins
  TEST_EQUAL(FLASHTnTAlgorithm::blindModCount(h), 1)
}
END_SECTION

START_SECTION((static std::vector<std::vector<int>> groupClasses(const std::vector<int>& class_order, const std::vector<Size>& class_size, Size min_targets, bool by_kind, const std::function<int(int)>& kind_of)))
{
  // classes as in FLASHTnT: 0 determined, 1 both termini, 2 open terminus, 3 precursor ladder, 4 terminal ladder
  const std::vector<int> class_order = {0, 1, 2, 3, 4};
  const std::vector<int> kind_order = {0, 3, 4, 1, 2};
  const auto kind_of = [](int c) { return c == 0 ? 0 : 1; };
  // E. coli-like run: a small undetermined group (93 + 5 < 100) before a large precursor-ladder class
  std::vector<Size> size = {760, 93, 5, 156, 577};
  auto g = FLASHTnTAlgorithm::groupClasses(class_order, size, 100, false, kind_of);
  TEST_EQUAL(g.size(), 3)
  TEST_EQUAL(g[1].size(), 3) // true: the undetermined group absorbs the precursor-ladder class
  TEST_EQUAL(g[1][2], 3)
  g = FLASHTnTAlgorithm::groupClasses(kind_order, size, 100, true, kind_of);
  TEST_EQUAL(g.size(), 3) // kind: determined | precursor ladder | terminal ladder + the small undetermined group (last, joins the group before it)
  TEST_EQUAL(g[1].size(), 1)
  TEST_EQUAL(g[1][0], 3)
  TEST_EQUAL(g[2].size(), 3)
  TEST_EQUAL(g[2][0], 4)
  // an undetermined group of at least 100 stays its own group, in both walks
  size = {760, 93, 10, 156, 577};
  g = FLASHTnTAlgorithm::groupClasses(class_order, size, 100, false, kind_of);
  TEST_EQUAL(g.size(), 4)
  g = FLASHTnTAlgorithm::groupClasses(kind_order, size, 100, true, kind_of);
  TEST_EQUAL(g.size(), 4) // determined | precursor ladder | terminal ladder | undetermined
  TEST_EQUAL(g[3].size(), 2)
  TEST_EQUAL(g[3][0], 1)
  // empty classes take no part
  size = {760, 93, 10, 0, 577};
  g = FLASHTnTAlgorithm::groupClasses(kind_order, size, 100, true, kind_of);
  TEST_EQUAL(g.size(), 3)
  TEST_EQUAL(g[1].size(), 1)
  TEST_EQUAL(g[1][0], 4)
  // a tiny run: the determined class alone is small and joins the other kind's first group
  size = {30, 20, 5, 10, 50};
  g = FLASHTnTAlgorithm::groupClasses(kind_order, size, 100, true, kind_of);
  TEST_EQUAL(g.size(), 1)
  TEST_EQUAL(g[0].size(), 5)
}
END_SECTION

START_SECTION((static String DeconvolvedSpectrum::formatWindowMasses(const std::vector<std::tuple<double, double>>& map)))
{
  std::vector<std::tuple<double, double>> map = {{0.0, 1e6}, {8565.4321, 1234.5}, {8579.4477, 99.0}};
  const String s = DeconvolvedSpectrum::formatWindowMasses(map);
  TEST_EQUAL(s.hasSubstring("8565.432"), true)
  TEST_EQUAL(s.hasSubstring("1e+06"), false) // the total-intensity entry (mass 0) is left out
  const auto back = DeconvolvedSpectrum::parseWindowMasses(s);
  TEST_EQUAL(back.size(), 2)
  TEST_REAL_SIMILAR(std::get<0>(back[0]), 8565.4321)
  TEST_REAL_SIMILAR(std::get<1>(back[1]), 99.0)
  TEST_EQUAL(DeconvolvedSpectrum::parseWindowMasses("").size(), 0)
  TEST_EQUAL(DeconvolvedSpectrum::parseWindowMasses("garbage,1:2").size(), 1)
}
END_SECTION

START_SECTION((FLASHTnTAlgorithm()))
{
  // the defaults of the FDR and mass options, and the values each of them takes
  const Param p = FLASHTnTAlgorithm().getDefaults();
  TEST_STRING_EQUAL(p.getValue("second_ranked").toString(), "drop")
  TEST_EQUAL(p.getValidStrings("second_ranked").size(), 2)
  TEST_STRING_EQUAL(p.getValue("terminal_ladder_class").toString(), "true")
  TEST_STRING_EQUAL(p.getValue("merge_small_classes").toString(), "kind")
  TEST_EQUAL(p.getValidStrings("merge_small_classes").size(), 2)
  TEST_STRING_EQUAL(p.getValue("protein_evidence").toString(), "proteoforms")
  TEST_EQUAL(p.getValidStrings("protein_evidence").size(), 2)
  TEST_REAL_SIMILAR((double)p.getValue("protein_evidence_min_mass"), 3000.0)
  TEST_STRING_EQUAL(p.getValue("precursor_reselect").toString(), "true")
  TEST_STRING_EQUAL(p.getValue("one_proteoform_per_feature").toString(), "fitted")
  TEST_EQUAL(p.getValidStrings("one_proteoform_per_feature").size(), 3)
  TEST_STRING_EQUAL(p.getValue("ex:skip_precursor_inference").toString(), "corroborated")
  TEST_EQUAL(p.getValidStrings("ex:skip_precursor_inference").size(), 3)
  TEST_STRING_EQUAL(p.getValue("ex:ladder_end_penalty").toString(), "false")
  TEST_EQUAL(p.getValidStrings("ex:ladder_end_penalty").size(), 2)
  TEST_EQUAL(p.exists("rescore"), false)
  TEST_EQUAL(p.exists("ex:mass_closure"), false)
}
END_SECTION

END_TEST
