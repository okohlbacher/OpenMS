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

using namespace OpenMS;

// The decisions of the FDR rules added for the entrapment benchmark: the protein evidence rule (option protein_evidence), the
// pair-wise protein-FDR gate (option protein_fdr_paired), the entry order that breaks candidate-cut ties, and the blind
// modification count the evidence rule reads.
START_TEST(FLASHTnTAlgorithm, "$Id$")

START_SECTION((static bool proteinEvidenceSupported(const String& protein_evidence, Size prsms, Size proteoforms, bool strong)))
{
  // none: every protein takes part
  TEST_EQUAL(FLASHTnTAlgorithm::proteinEvidenceSupported("none", 1, 1, false), true)
  // prsms: two PrSMs, or one strong proteoform
  TEST_EQUAL(FLASHTnTAlgorithm::proteinEvidenceSupported("prsms", 1, 1, false), false)
  TEST_EQUAL(FLASHTnTAlgorithm::proteinEvidenceSupported("prsms", 2, 1, false), true)
  TEST_EQUAL(FLASHTnTAlgorithm::proteinEvidenceSupported("prsms", 1, 1, true), true)
  // proteoforms: two distinct proteoforms; two PrSMs of one proteoform are not enough
  TEST_EQUAL(FLASHTnTAlgorithm::proteinEvidenceSupported("proteoforms", 2, 1, false), false)
  TEST_EQUAL(FLASHTnTAlgorithm::proteinEvidenceSupported("proteoforms", 2, 2, false), true)
  TEST_EQUAL(FLASHTnTAlgorithm::proteinEvidenceSupported("proteoforms", 1, 1, true), true)
  TEST_EQUAL(FLASHTnTAlgorithm::proteinEvidenceSupported("proteoforms", 0, 0, false), false)
}
END_SECTION

START_SECTION((static bool characterizeBeyondTop(bool passing, bool paired, long partner, bool partner_is_candidate)))
{
  TEST_EQUAL(FLASHTnTAlgorithm::characterizeBeyondTop(false, false, 3, true), false) // not passing the protein FDR: never
  TEST_EQUAL(FLASHTnTAlgorithm::characterizeBeyondTop(false, true, 3, true), false)
  TEST_EQUAL(FLASHTnTAlgorithm::characterizeBeyondTop(true, false, -1, false), true) // unpaired: passing suffices
  TEST_EQUAL(FLASHTnTAlgorithm::characterizeBeyondTop(true, false, 3, false), true)
  TEST_EQUAL(FLASHTnTAlgorithm::characterizeBeyondTop(true, true, 3, true), true)   // paired: the partner is a candidate too
  TEST_EQUAL(FLASHTnTAlgorithm::characterizeBeyondTop(true, true, 3, false), false) // paired: the partner is no candidate
  TEST_EQUAL(FLASHTnTAlgorithm::characterizeBeyondTop(true, true, -1, true), false) // paired: no partner at all
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

END_TEST
