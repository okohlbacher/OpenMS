// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// --------------------------------------------------------------------------
// $Maintainer: Kyowon Jeong, Jihyung Kim $
// $Authors: Kyowon Jeong, Jihyung Kim $
// --------------------------------------------------------------------------

#include <OpenMS/CONCEPT/ClassTest.h>
#include <OpenMS/test_config.h>

///////////////////////////

#include <OpenMS/ANALYSIS/TOPDOWN/DeconvolvedSpectrum.h>
#include <OpenMS/ANALYSIS/TOPDOWN/FLASHHelperClasses.h>
#include <OpenMS/CHEMISTRY/ISOTOPEDISTRIBUTION/CoarseIsotopePatternGenerator.h>
#include <OpenMS/CONCEPT/Constants.h>
#include <bit>
#include <cmath>
#include <exception>
#include <limits>
#include <type_traits>
#include <unordered_set>

///////////////////////////

START_TEST(FLASHHelperClasses, "$Id$")

/////////////////////////////////////////////////////////////
/////////////////////////////////////////////////////////////

using namespace OpenMS;
using namespace std;

typedef FLASHHelperClasses::LogMzPeak LogMzPeak;
typedef FLASHHelperClasses::MassFeature MassFeature;
typedef FLASHHelperClasses::IsobaricQuantities IsobaricQuantities;
typedef FLASHHelperClasses::PrecalculatedAveragine PrecalculatedAveragine;

/////////////////////////////////////////////////////////////
// Static utility function tests
/////////////////////////////////////////////////////////////

START_SECTION(static float getChargeMass(bool positive_ioniziation_mode))
{
  // Positive mode should return proton mass
  float pos_mass = FLASHHelperClasses::getChargeMass(true);
  TEST_REAL_SIMILAR(pos_mass, Constants::PROTON_MASS_U)

  // Negative mode should return negative proton mass
  float neg_mass = FLASHHelperClasses::getChargeMass(false);
  TEST_REAL_SIMILAR(neg_mass, -Constants::PROTON_MASS_U)
}
END_SECTION

START_SECTION(static double getLogMz(double mz, bool positive))
{
  // Test positive mode
  double mz = 500.0;
  double log_mz_pos = FLASHHelperClasses::getLogMz(mz, true);
  double expected_pos = std::log(mz - Constants::PROTON_MASS_U);
  TEST_REAL_SIMILAR(log_mz_pos, expected_pos)

  // Test negative mode
  double log_mz_neg = FLASHHelperClasses::getLogMz(mz, false);
  double expected_neg = std::log(mz + Constants::PROTON_MASS_U);
  TEST_REAL_SIMILAR(log_mz_neg, expected_neg)

  // Test with different m/z values
  double mz2 = 1000.0;
  double log_mz2 = FLASHHelperClasses::getLogMz(mz2, true);
  TEST_REAL_SIMILAR(log_mz2, std::log(mz2 - Constants::PROTON_MASS_U))
}
END_SECTION

/////////////////////////////////////////////////////////////
// LogMzPeak tests
/////////////////////////////////////////////////////////////

LogMzPeak* lmp_ptr = nullptr;
LogMzPeak* lmp_null_ptr = nullptr;

START_SECTION(LogMzPeak())
{
  lmp_ptr = new LogMzPeak();
  TEST_NOT_EQUAL(lmp_ptr, lmp_null_ptr)

  // Check default values
  TEST_REAL_SIMILAR(lmp_ptr->getMZ(), 0.0)
  TEST_REAL_SIMILAR(lmp_ptr->getIntensity(), 0.0f)
  TEST_REAL_SIMILAR(lmp_ptr->getLogMz(), -1000.0)
  TEST_REAL_SIMILAR(lmp_ptr->getMass(), 0.0)
  TEST_EQUAL(lmp_ptr->getAbsCharge(), 0)
  TEST_EQUAL(lmp_ptr->isPositive(), true)
  TEST_EQUAL(lmp_ptr->getIsotopeIndex(), -1)
}
END_SECTION

START_SECTION([Compact facade] layout and independent packed fields)
{
  static_assert(std::is_trivially_copyable_v<LogMzPeak>);
  TEST_EQUAL(sizeof(LogMzPeak), 32)
  TEST_EQUAL(alignof(LogMzPeak), alignof(double))
  LogMzPeak value;
  for (int charge = 0; charge <= 200; ++charge)
  {
    for (bool positive : {false, true})
    {
      for (int isotope : {-65535, -32768, -2, -1, 0, 1, 32768, 65535})
      {
        // Deliberately change each shared-word component after its neighbours.
        value.setPositive(! positive);
        value.setIsotopeIndex(-isotope);
        value.setAbsCharge(charge);
        value.setIsotopeIndex(isotope);
        value.setPositive(positive);
        TEST_EQUAL(value.getAbsCharge(), charge)
        TEST_EQUAL(value.isPositive(), positive)
        TEST_EQUAL(value.getIsotopeIndex(), isotope)
        value.setAbsCharge(200 - charge);
        TEST_EQUAL(value.isPositive(), positive)
        TEST_EQUAL(value.getIsotopeIndex(), isotope)
      }
    }
  }
}
END_SECTION

START_SECTION([Compact facade] invalid writes preserve the value)
{
  LogMzPeak value;
  value.setAbsCharge(200);
  value.setPositive(false);
  value.setIsotopeIndex(-65535);
  for (int invalid : {-1, 201, std::numeric_limits<int>::min(), std::numeric_limits<int>::max()})
  {
    TEST_EXCEPTION(Exception::InvalidValue, value.setAbsCharge(invalid))
    TEST_EQUAL(value.getAbsCharge(), 200)
    TEST_EQUAL(value.isPositive(), false)
    TEST_EQUAL(value.getIsotopeIndex(), -65535)
  }
  for (int invalid : {-65536, 65536, std::numeric_limits<int>::min(), std::numeric_limits<int>::max()})
  {
    TEST_EXCEPTION(Exception::InvalidValue, value.setIsotopeIndex(invalid))
    TEST_EQUAL(value.getAbsCharge(), 200)
    TEST_EQUAL(value.isPositive(), false)
    TEST_EQUAL(value.getIsotopeIndex(), -65535)
  }
}
END_SECTION

START_SECTION([Compact facade] independent values survive source destruction)
{
  LogMzPeak copy;
  {
    LogMzPeak source(Peak1D(1234.567890123, 987.5f), false);
    source.setAbsCharge(200);
    source.setIsotopeIndex(-42);
    source.setMass(246000.123456789);
    source.setLogMz(9.25);
    copy = source;
    source.setMZ(1);
    source.setMass(1);
  }
  TEST_EQUAL(copy.getMZ(), 1234.567890123)
  TEST_EQUAL(copy.getIntensity(), 987.5f)
  TEST_EQUAL(copy.getLogMz(), 9.25)
  TEST_EQUAL(copy.getMass(), 246000.123456789)
  TEST_EQUAL(copy.getUnchargedMass(), 246000.123456789)
  TEST_EQUAL(copy.getAbsCharge(), 200)
  TEST_EQUAL(copy.isPositive(), false)
  TEST_EQUAL(copy.getIsotopeIndex(), -42)
  copy.setMZ(2);
  TEST_EQUAL(copy.getLogMz(), 9.25)
  TEST_EQUAL(copy.getMass(), 246000.123456789)
  copy.setAbsCharge(0);
  TEST_EQUAL(copy.isPositive(), false)
  TEST_EQUAL(copy.getUnchargedMass(), 0)
  copy.setAbsCharge(2);
  copy.setMass(-1);
  const double derived = (copy.getMZ() - FLASHHelperClasses::getChargeMass(false)) * 2.0f;
  TEST_EQUAL(copy.getUnchargedMass(), derived)
  copy.setMass(0);
  TEST_EQUAL(copy.getUnchargedMass(), derived)
  LogMzPeak equal(copy);
  equal.setPositive(true);
  equal.setAbsCharge(200);
  equal.setIsotopeIndex(65535);
  TEST_EQUAL(copy == equal, true)
  TEST_EQUAL(std::hash<LogMzPeak> {}(copy), std::hash<LogMzPeak> {}(equal))
  copy.setIsotopeIndex(-1);
  copy.setIsotopeIndex(0);
  TEST_EQUAL(copy.getIsotopeIndex(), 0)
}
END_SECTION

START_SECTION(~LogMzPeak())
{
  delete lmp_ptr;
}
END_SECTION

START_SECTION(explicit LogMzPeak(const Peak1D& peak, bool positive))
{
  // Test with positive mode
  Peak1D peak;
  peak.setMZ(500.5);
  peak.setIntensity(10000.0f);

  LogMzPeak lmp_pos(peak, true);
  TEST_REAL_SIMILAR(lmp_pos.getMZ(), 500.5)
  TEST_REAL_SIMILAR(lmp_pos.getIntensity(), 10000.0f)
  TEST_EQUAL(lmp_pos.isPositive(), true)
  TEST_EQUAL(lmp_pos.getAbsCharge(), 0)
  TEST_EQUAL(lmp_pos.getIsotopeIndex(), 0)
  double expected_logMz = std::log(500.5 - Constants::PROTON_MASS_U);
  TEST_REAL_SIMILAR(lmp_pos.getLogMz(), expected_logMz)

  // Test with negative mode
  LogMzPeak lmp_neg(peak, false);
  TEST_REAL_SIMILAR(lmp_neg.getMZ(), 500.5)
  TEST_EQUAL(lmp_neg.isPositive(), false)
  double expected_logMz_neg = std::log(500.5 + Constants::PROTON_MASS_U);
  TEST_REAL_SIMILAR(lmp_neg.getLogMz(), expected_logMz_neg)
}
END_SECTION

START_SECTION(LogMzPeak(const LogMzPeak&))
{
  Peak1D peak;
  peak.setMZ(750.25);
  peak.setIntensity(5000.0f);
  LogMzPeak original(peak, true);
  original.setAbsCharge(3);
  original.setIsotopeIndex(2);
  original.setMass(2248.0);

  LogMzPeak copy(original);
  TEST_REAL_SIMILAR(copy.getMZ(), 750.25)
  TEST_REAL_SIMILAR(copy.getIntensity(), 5000.0f)
  TEST_EQUAL(copy.getAbsCharge(), 3)
  TEST_EQUAL(copy.getIsotopeIndex(), 2)
  TEST_REAL_SIMILAR(copy.getMass(), 2248.0)
  TEST_EQUAL(copy.isPositive(), true)
  TEST_REAL_SIMILAR(copy.getLogMz(), original.getLogMz())
}
END_SECTION

START_SECTION(double getUnchargedMass() const)
{
  Peak1D peak;
  peak.setMZ(500.5);
  peak.setIntensity(1000.0f);
  LogMzPeak lmp(peak, true);

  // With no charge set, should return 0
  TEST_REAL_SIMILAR(lmp.getUnchargedMass(), 0.0)

  // Set charge and mass = 0 (will calculate from mz)
  lmp.setAbsCharge(2);
  lmp.setMass(0);
  double expected_mass = (500.5 - Constants::PROTON_MASS_U) * 2;
  TEST_REAL_SIMILAR(lmp.getUnchargedMass(), expected_mass)

  // With mass already set > 0, should return that mass
  lmp.setMass(999.5);
  TEST_REAL_SIMILAR(lmp.getUnchargedMass(), 999.5)

  // Test negative mode
  Peak1D peak2;
  peak2.setMZ(500.5);
  peak2.setIntensity(1000.0f);
  LogMzPeak lmp_neg(peak2, false);
  lmp_neg.setAbsCharge(2);
  lmp_neg.setMass(0);
  double expected_neg = (500.5 + Constants::PROTON_MASS_U) * 2;
  TEST_REAL_SIMILAR(lmp_neg.getUnchargedMass(), expected_neg)
}
END_SECTION

START_SECTION(bool operator<(const LogMzPeak& a) const)
{
  LogMzPeak lmp1, lmp2, lmp3;

  // Different logMz values
  lmp1.setLogMz(5.0);
  lmp1.setIntensity(100.0f);
  lmp2.setLogMz(6.0);
  lmp2.setIntensity(100.0f);

  TEST_EQUAL(lmp1 < lmp2, true)
  TEST_EQUAL(lmp2 < lmp1, false)

  // Same logMz, different intensity
  lmp3.setLogMz(5.0);
  lmp3.setIntensity(200.0f);
  TEST_EQUAL(lmp1 < lmp3, true)   // same logMz, but lmp1 has lower intensity
  TEST_EQUAL(lmp3 < lmp1, false)
}
END_SECTION

START_SECTION(bool operator>(const LogMzPeak& a) const)
{
  LogMzPeak lmp1, lmp2, lmp3;

  // Different logMz values
  lmp1.setLogMz(6.0);
  lmp1.setIntensity(100.0f);
  lmp2.setLogMz(5.0);
  lmp2.setIntensity(100.0f);

  TEST_EQUAL(lmp1 > lmp2, true)
  TEST_EQUAL(lmp2 > lmp1, false)

  // Same logMz, different intensity
  lmp3.setLogMz(6.0);
  lmp3.setIntensity(50.0f);
  TEST_EQUAL(lmp1 > lmp3, true)   // same logMz, but lmp1 has higher intensity
  TEST_EQUAL(lmp3 > lmp1, false)
}
END_SECTION

START_SECTION(bool operator==(const LogMzPeak& other) const)
{
  LogMzPeak lmp1, lmp2, lmp3;

  lmp1.setLogMz(5.5);
  lmp1.setIntensity(100.0f);
  lmp2.setLogMz(5.5);
  lmp2.setIntensity(100.0f);
  lmp3.setLogMz(5.5);
  lmp3.setIntensity(200.0f);

  TEST_EQUAL(lmp1 == lmp2, true)
  TEST_EQUAL(lmp1 == lmp3, false)  // same logMz but different intensity
}
END_SECTION

/////////////////////////////////////////////////////////////
// MassFeature tests
/////////////////////////////////////////////////////////////

START_SECTION([MassFeature] bool operator<(const MassFeature& a) const)
{
  MassFeature mf1, mf2;
  mf1.avg_mass = 10000.0;
  mf2.avg_mass = 15000.0;

  TEST_EQUAL(mf1 < mf2, true)
  TEST_EQUAL(mf2 < mf1, false)
}
END_SECTION

START_SECTION([MassFeature] bool operator>(const MassFeature& a) const)
{
  MassFeature mf1, mf2;
  mf1.avg_mass = 15000.0;
  mf2.avg_mass = 10000.0;

  TEST_EQUAL(mf1 > mf2, true)
  TEST_EQUAL(mf2 > mf1, false)
}
END_SECTION

START_SECTION([MassFeature] bool operator==(const MassFeature& other) const)
{
  MassFeature mf1, mf2, mf3;
  mf1.avg_mass = 10000.0;
  mf2.avg_mass = 10000.0;
  mf3.avg_mass = 10001.0;

  TEST_EQUAL(mf1 == mf2, true)
  TEST_EQUAL(mf1 == mf3, false)
}
END_SECTION

START_SECTION([MassFeature] member variables)
{
  MassFeature mf;

  // Test setting and accessing all member variables
  mf.index = 42;
  mf.iso_offset = 1;
  mf.scan_number = 100;
  mf.min_scan_number = 95;
  mf.max_scan_number = 105;
  mf.rep_charge = 10;
  mf.avg_mass = 15000.5;
  mf.min_charge = 5;
  mf.max_charge = 15;
  mf.charge_count = 11;
  mf.isotope_score = 0.95;
  mf.qscore = 0.85;
  mf.rep_mz = 1500.05;
  mf.is_decoy = false;
  mf.ms_level = 1;

  TEST_EQUAL(mf.index, 42)
  TEST_EQUAL(mf.iso_offset, 1)
  TEST_EQUAL(mf.scan_number, 100)
  TEST_EQUAL(mf.min_scan_number, 95)
  TEST_EQUAL(mf.max_scan_number, 105)
  TEST_EQUAL(mf.rep_charge, 10)
  TEST_REAL_SIMILAR(mf.avg_mass, 15000.5)
  TEST_EQUAL(mf.min_charge, 5)
  TEST_EQUAL(mf.max_charge, 15)
  TEST_EQUAL(mf.charge_count, 11)
  TEST_REAL_SIMILAR(mf.isotope_score, 0.95)
  TEST_REAL_SIMILAR(mf.qscore, 0.85)
  TEST_REAL_SIMILAR(mf.rep_mz, 1500.05)
  TEST_EQUAL(mf.is_decoy, false)
  TEST_EQUAL(mf.ms_level, 1)

  // Test per_charge_intensity and per_isotope_intensity vectors
  mf.per_charge_intensity.resize(20, 0.0f);
  mf.per_isotope_intensity.resize(10, 0.0f);
  mf.per_charge_intensity[10] = 5000.0f;
  mf.per_isotope_intensity[0] = 10000.0f;

  TEST_REAL_SIMILAR(mf.per_charge_intensity[10], 5000.0f)
  TEST_REAL_SIMILAR(mf.per_isotope_intensity[0], 10000.0f)
}
END_SECTION

/////////////////////////////////////////////////////////////
// IsobaricQuantities tests
/////////////////////////////////////////////////////////////

START_SECTION([IsobaricQuantities] bool empty() const)
{
  IsobaricQuantities iq;

  // Initially empty (no quantities)
  TEST_EQUAL(iq.empty(), true)

  // Add a quantity
  iq.quantities.push_back(100.0);
  TEST_EQUAL(iq.empty(), false)

  // Clear and verify empty again
  iq.quantities.clear();
  TEST_EQUAL(iq.empty(), true)
}
END_SECTION

START_SECTION([IsobaricQuantities] member variables)
{
  IsobaricQuantities iq;

  // Test setting and accessing all member variables
  iq.scan = 150;
  iq.rt = 600.5;
  iq.precursor_mz = 800.4;
  iq.precursor_mass = 7996.0;

  TEST_EQUAL(iq.scan, 150)
  TEST_REAL_SIMILAR(iq.rt, 600.5)
  TEST_REAL_SIMILAR(iq.precursor_mz, 800.4)
  TEST_REAL_SIMILAR(iq.precursor_mass, 7996.0)

  // Test quantities vectors
  iq.quantities = {100.0, 200.0, 300.0, 400.0};
  iq.merged_quantities = {150.0, 350.0};

  TEST_EQUAL(iq.quantities.size(), 4)
  TEST_REAL_SIMILAR(iq.quantities[0], 100.0)
  TEST_REAL_SIMILAR(iq.quantities[3], 400.0)
  TEST_EQUAL(iq.merged_quantities.size(), 2)
  TEST_REAL_SIMILAR(iq.merged_quantities[0], 150.0)
}
END_SECTION

/////////////////////////////////////////////////////////////
// PrecalculatedAveragine tests
/////////////////////////////////////////////////////////////

START_SECTION(PrecalculatedAveragine())
{
  PrecalculatedAveragine* pa_ptr = new PrecalculatedAveragine();
  TEST_NOT_EQUAL(pa_ptr, nullptr)
  delete pa_ptr;
}
END_SECTION

START_SECTION(PrecalculatedAveragine(double min_mass, double max_mass, double delta, CoarseIsotopePatternGenerator& generator, bool use_RNA_averagine, double decoy_iso_distance = -1))
{
  CoarseIsotopePatternGenerator generator(100);

  // Create PrecalculatedAveragine for peptide
  PrecalculatedAveragine pa(500.0, 5000.0, 100.0, generator, false);

  // Test that it was created and can return isotope distributions
  IsotopeDistribution iso = pa.get(1000.0);
  TEST_EQUAL(iso.size() > 0, true)

  // Test RNA averagine
  PrecalculatedAveragine pa_rna(500.0, 5000.0, 100.0, generator, true);
  IsotopeDistribution iso_rna = pa_rna.get(1000.0);
  TEST_EQUAL(iso_rna.size() > 0, true)
}
END_SECTION

START_SECTION(PrecalculatedAveragine(const PrecalculatedAveragine&))
{
  CoarseIsotopePatternGenerator generator(100);
  PrecalculatedAveragine original(500.0, 5000.0, 100.0, generator, false);

  PrecalculatedAveragine copy(original);
  IsotopeDistribution iso_orig = original.get(2000.0);
  IsotopeDistribution iso_copy = copy.get(2000.0);

  TEST_EQUAL(iso_orig.size(), iso_copy.size())
  if (iso_orig.size() > 0 && iso_copy.size() > 0)
  {
    TEST_REAL_SIMILAR(iso_orig[0].getIntensity(), iso_copy[0].getIntensity())
  }
}
END_SECTION

START_SECTION(PrecalculatedAveragine(PrecalculatedAveragine&& other) noexcept)
{
  CoarseIsotopePatternGenerator generator(100);
  PrecalculatedAveragine original(500.0, 5000.0, 100.0, generator, false);
  Size orig_apex = original.getApexIndex(2000.0);

  PrecalculatedAveragine moved(std::move(original));
  TEST_EQUAL(moved.getApexIndex(2000.0), orig_apex)
}
END_SECTION

START_SECTION(PrecalculatedAveragine& operator=(const PrecalculatedAveragine& pc))
{
  CoarseIsotopePatternGenerator generator(100);
  PrecalculatedAveragine original(500.0, 5000.0, 100.0, generator, false);
  PrecalculatedAveragine assigned;

  assigned = original;
  IsotopeDistribution iso_orig = original.get(2000.0);
  IsotopeDistribution iso_assigned = assigned.get(2000.0);

  TEST_EQUAL(iso_orig.size(), iso_assigned.size())
}
END_SECTION

START_SECTION(PrecalculatedAveragine& operator=(PrecalculatedAveragine&& pc) noexcept)
{
  CoarseIsotopePatternGenerator generator(100);
  PrecalculatedAveragine original(500.0, 5000.0, 100.0, generator, false);
  Size orig_apex = original.getApexIndex(2000.0);

  PrecalculatedAveragine moved_assigned;
  moved_assigned = std::move(original);
  TEST_EQUAL(moved_assigned.getApexIndex(2000.0), orig_apex)
}
END_SECTION

START_SECTION(IsotopeDistribution get(double mass) const)
{
  CoarseIsotopePatternGenerator generator(100);
  PrecalculatedAveragine pa(500.0, 10000.0, 100.0, generator, false);

  // Test various masses
  IsotopeDistribution iso1 = pa.get(1000.0);
  IsotopeDistribution iso2 = pa.get(5000.0);
  IsotopeDistribution iso3 = pa.get(9000.0);

  TEST_EQUAL(iso1.size() > 0, true)
  TEST_EQUAL(iso2.size() > 0, true)
  TEST_EQUAL(iso3.size() > 0, true)

  // Higher mass should have more isotopes with significant intensity
  // (apex moves to higher index)
  Size apex1 = pa.getApexIndex(1000.0);
  Size apex2 = pa.getApexIndex(5000.0);
  Size apex3 = pa.getApexIndex(9000.0);

  TEST_EQUAL(apex1 <= apex2, true)
  TEST_EQUAL(apex2 <= apex3, true)

  // Test mass exceeding max - should return distribution for max mass
  IsotopeDistribution iso_exceed = pa.get(20000.0);
  TEST_EQUAL(iso_exceed.size() > 0, true)
}
END_SECTION

START_SECTION([PrecalculatedAveragine] public get preserves copy and mass-bin boundaries)
{
  CoarseIsotopePatternGenerator generator(100);
  const PrecalculatedAveragine pa(500.0, 1000.0, 100.0, generator, false);
  const auto original = pa.get(600.0);
  auto returned = pa.get(600.0);
  TEST_EQUAL(returned.size() > 0, true)
  if (returned.size() > 0)
  {
    // A public caller can modify its value without changing the scoring cache.
    returned[0].setIntensity(original[0].getIntensity() + 42.0f);
    returned[0].setMZ(original[0].getMZ() + 1.0);
    TEST_EQUAL(returned == original, false)
    TEST_EQUAL(pa.get(600.0) == original, true)
  }

  // Keep the existing lower/upper clamping and half-bin round-up convention.
  TEST_EQUAL(pa.get(-100.0) == pa.get(500.0), true)
  TEST_EQUAL(pa.get(549.9) == pa.get(500.0), true)
  TEST_EQUAL(pa.get(550.0) == pa.get(600.0), true)
  TEST_EQUAL(pa.get(649.9) == pa.get(600.0), true)
  TEST_EQUAL(pa.get(650.0) == pa.get(700.0), true)
  TEST_EQUAL(pa.get(2000.0) == pa.get(1000.0), true)
}
END_SECTION

START_SECTION(size_t getMaxIsotopeIndex() const)
{
  CoarseIsotopePatternGenerator generator(100);
  PrecalculatedAveragine pa(500.0, 5000.0, 100.0, generator, false);
  pa.setMaxIsotopeIndex(50);

  TEST_EQUAL(pa.getMaxIsotopeIndex(), 50)
}
END_SECTION

START_SECTION(void setMaxIsotopeIndex(int index))
{
  CoarseIsotopePatternGenerator generator(100);
  PrecalculatedAveragine pa(500.0, 5000.0, 100.0, generator, false);

  pa.setMaxIsotopeIndex(30);
  TEST_EQUAL(pa.getMaxIsotopeIndex(), 30)

  pa.setMaxIsotopeIndex(100);
  TEST_EQUAL(pa.getMaxIsotopeIndex(), 100)
}
END_SECTION

START_SECTION(Size getLeftCountFromApex(double mass) const)
{
  CoarseIsotopePatternGenerator generator(100);
  PrecalculatedAveragine pa(500.0, 10000.0, 100.0, generator, false);

  Size left1 = pa.getLeftCountFromApex(1000.0);
  Size left2 = pa.getLeftCountFromApex(5000.0);

  // Should return reasonable values (at least minimum of 2)
  TEST_EQUAL(left1 >= 2, true)
  TEST_EQUAL(left2 >= 2, true)
}
END_SECTION

START_SECTION(Size getRightCountFromApex(double mass) const)
{
  CoarseIsotopePatternGenerator generator(100);
  PrecalculatedAveragine pa(500.0, 10000.0, 100.0, generator, false);

  Size right1 = pa.getRightCountFromApex(1000.0);
  Size right2 = pa.getRightCountFromApex(5000.0);

  // Should return reasonable values (at least minimum of 2)
  TEST_EQUAL(right1 >= 2, true)
  TEST_EQUAL(right2 >= 2, true)
}
END_SECTION

START_SECTION(Size getApexIndex(double mass) const)
{
  CoarseIsotopePatternGenerator generator(100);
  PrecalculatedAveragine pa(500.0, 10000.0, 100.0, generator, false);

  Size apex1 = pa.getApexIndex(1000.0);
  Size apex5 = pa.getApexIndex(5000.0);
  Size apex9 = pa.getApexIndex(9000.0);

  // Apex should shift to higher indices for higher masses
  TEST_EQUAL(apex1 <= apex5, true)
  TEST_EQUAL(apex5 <= apex9, true)

  // For small mass, apex should be at or near 0
  Size apex_small = pa.getApexIndex(600.0);
  TEST_EQUAL(apex_small <= 2, true)
}
END_SECTION

START_SECTION(Size getLastIndex(double mass) const)
{
  CoarseIsotopePatternGenerator generator(100);
  PrecalculatedAveragine pa(500.0, 10000.0, 100.0, generator, false);

  Size last1 = pa.getLastIndex(1000.0);
  Size last5 = pa.getLastIndex(5000.0);

  // Last index should be apex + right count
  Size apex1 = pa.getApexIndex(1000.0);
  Size right1 = pa.getRightCountFromApex(1000.0);
  TEST_EQUAL(last1, apex1 + right1)

  Size apex5 = pa.getApexIndex(5000.0);
  Size right5 = pa.getRightCountFromApex(5000.0);
  TEST_EQUAL(last5, apex5 + right5)
}
END_SECTION

START_SECTION(double getAverageMassDelta(double mass) const)
{
  CoarseIsotopePatternGenerator generator(100);
  PrecalculatedAveragine pa(500.0, 10000.0, 100.0, generator, false);

  double delta1 = pa.getAverageMassDelta(1000.0);
  double delta5 = pa.getAverageMassDelta(5000.0);
  double delta9 = pa.getAverageMassDelta(9000.0);

  // Average mass should be greater than monoisotopic mass (delta > 0)
  TEST_EQUAL(delta1 > 0, true)
  TEST_EQUAL(delta5 > 0, true)
  TEST_EQUAL(delta9 > 0, true)

  // Delta should increase with mass
  TEST_EQUAL(delta1 < delta5, true)
  TEST_EQUAL(delta5 < delta9, true)
}
END_SECTION

START_SECTION(double getMostAbundantMassDelta(double mass) const)
{
  CoarseIsotopePatternGenerator generator(100);
  PrecalculatedAveragine pa(500.0, 10000.0, 100.0, generator, false);

  double delta1 = pa.getMostAbundantMassDelta(1000.0);
  double delta5 = pa.getMostAbundantMassDelta(5000.0);
  double delta9 = pa.getMostAbundantMassDelta(9000.0);

  // Most abundant mass delta should be non-negative
  TEST_EQUAL(delta1 >= 0, true)
  TEST_EQUAL(delta5 >= 0, true)
  TEST_EQUAL(delta9 >= 0, true)

  // For small masses, monoisotopic is often most abundant (delta ~ 0)
  // For larger masses, delta should increase
  TEST_EQUAL(delta1 <= delta5, true)
}
END_SECTION

START_SECTION(double getSNRMultiplicationFactor(double mass) const)
{
  CoarseIsotopePatternGenerator generator(100);
  PrecalculatedAveragine pa(500.0, 10000.0, 100.0, generator, false);

  double snr1 = pa.getSNRMultiplicationFactor(1000.0);
  double snr5 = pa.getSNRMultiplicationFactor(5000.0);

  // SNR factor should be positive
  TEST_EQUAL(snr1 > 0, true)
  TEST_EQUAL(snr5 > 0, true)
}
END_SECTION

/////////////////////////////////////////////////////////////
// Test decoy isotope pattern generation
/////////////////////////////////////////////////////////////

START_SECTION([PrecalculatedAveragine] decoy isotope patterns)
{
  CoarseIsotopePatternGenerator generator(100);

  // Create normal and decoy averagine patterns
  PrecalculatedAveragine pa_normal(500.0, 5000.0, 100.0, generator, false, -1);
  PrecalculatedAveragine pa_decoy(500.0, 5000.0, 100.0, generator, false, 1.5);

  IsotopeDistribution iso_normal = pa_normal.get(2000.0);
  IsotopeDistribution iso_decoy = pa_decoy.get(2000.0);

  // Both should have distributions
  TEST_EQUAL(iso_normal.size() > 0, true)
  TEST_EQUAL(iso_decoy.size() > 0, true)

  // Decoy pattern should be different (scaled isotope distances)
  // The m/z values will be different
  if (iso_normal.size() > 1 && iso_decoy.size() > 1)
  {
    double normal_spacing = iso_normal[1].getMZ() - iso_normal[0].getMZ();
    double decoy_spacing = iso_decoy[1].getMZ() - iso_decoy[0].getMZ();
    // Decoy spacing should be approximately 1.5x normal spacing
    TEST_REAL_SIMILAR(decoy_spacing / normal_spacing, 1.5)
  }
}
END_SECTION

/////////////////////////////////////////////////////////////
// Integration tests: combining multiple classes
/////////////////////////////////////////////////////////////

START_SECTION([Integration] LogMzPeak with charge and mass calculations)
{
  // Create a peak and test full workflow
  Peak1D peak;
  peak.setMZ(857.0789);  // m/z for a +3 charged peptide
  peak.setIntensity(50000.0f);

  LogMzPeak lmp(peak, true);
  lmp.setAbsCharge(3);
  lmp.setIsotopeIndex(0);

  // Calculate uncharged mass
  double mass = lmp.getUnchargedMass();
  // Expected: (857.0789 - 1.007276) * 3 = 2568.2148
  double expected_mass = (857.0789 - Constants::PROTON_MASS_U) * 3;
  TEST_REAL_SIMILAR(mass, expected_mass)

  // Set mass directly and verify
  lmp.setMass(2568.0);
  TEST_REAL_SIMILAR(lmp.getUnchargedMass(), 2568.0)
}
END_SECTION

START_SECTION([Integration] MassFeature sorting)
{
  // Create multiple MassFeatures and test sorting
  std::vector<MassFeature> features;

  MassFeature mf1, mf2, mf3;
  mf1.avg_mass = 15000.0;
  mf1.index = 1;
  mf2.avg_mass = 10000.0;
  mf2.index = 2;
  mf3.avg_mass = 20000.0;
  mf3.index = 3;

  features.push_back(mf1);
  features.push_back(mf2);
  features.push_back(mf3);

  // Sort by mass using operator<
  std::sort(features.begin(), features.end());

  TEST_REAL_SIMILAR(features[0].avg_mass, 10000.0)
  TEST_REAL_SIMILAR(features[1].avg_mass, 15000.0)
  TEST_REAL_SIMILAR(features[2].avg_mass, 20000.0)
}
END_SECTION

START_SECTION([Integration] LogMzPeak sorting)
{
  // Create multiple LogMzPeaks and test sorting
  std::vector<LogMzPeak> peaks;

  LogMzPeak lmp1, lmp2, lmp3;
  lmp1.setLogMz(6.5);
  lmp1.setIntensity(1000.0f);
  lmp2.setLogMz(6.2);
  lmp2.setIntensity(2000.0f);
  lmp3.setLogMz(6.8);
  lmp3.setIntensity(1500.0f);

  peaks.push_back(lmp1);
  peaks.push_back(lmp2);
  peaks.push_back(lmp3);

  // Sort by logMz using operator<
  std::sort(peaks.begin(), peaks.end());

  TEST_REAL_SIMILAR(peaks[0].getLogMz(), 6.2)
  TEST_REAL_SIMILAR(peaks[1].getLogMz(), 6.5)
  TEST_REAL_SIMILAR(peaks[2].getLogMz(), 6.8)
}
END_SECTION

/////////////////////////////////////////////////////////////
// Hash tests
/////////////////////////////////////////////////////////////

START_SECTION([MassFeature] std::hash)
{
  std::hash<MassFeature> hasher;

  // Test that equal objects have equal hashes
  MassFeature mf1, mf2;
  mf1.avg_mass = 10000.0;
  mf2.avg_mass = 10000.0;

  TEST_EQUAL(mf1 == mf2, true)
  TEST_EQUAL(hasher(mf1), hasher(mf2))

  // Test that different objects have different hashes (not guaranteed, but likely)
  MassFeature mf3;
  mf3.avg_mass = 15000.0;
  TEST_EQUAL(mf1 == mf3, false)
  TEST_NOT_EQUAL(hasher(mf1), hasher(mf3))

  // Test usability in unordered_set
  std::unordered_set<MassFeature> feature_set;
  feature_set.insert(mf1);
  feature_set.insert(mf2);  // Should not be added (equal to mf1)
  feature_set.insert(mf3);

  TEST_EQUAL(feature_set.size(), 2)
  TEST_EQUAL(feature_set.count(mf1), 1)
  TEST_EQUAL(feature_set.count(mf3), 1)
}
END_SECTION

START_SECTION([LogMzPeak] std::hash)
{
  std::hash<LogMzPeak> hasher;

  // Test that equal objects have equal hashes
  LogMzPeak lmp1, lmp2;
  lmp1.setLogMz(5.5);
  lmp1.setIntensity(100.0f);
  lmp2.setLogMz(5.5);
  lmp2.setIntensity(100.0f);

  TEST_EQUAL(lmp1 == lmp2, true)
  TEST_EQUAL(hasher(lmp1), hasher(lmp2))

  // Test that different objects have different hashes
  LogMzPeak lmp3;
  lmp3.setLogMz(5.5);
  lmp3.setIntensity(200.0f); // Different intensity
  TEST_EQUAL(lmp1 == lmp3, false)
  TEST_NOT_EQUAL(hasher(lmp1), hasher(lmp3))

  LogMzPeak lmp4;
  lmp4.setLogMz(6.0); // Different logMz
  lmp4.setIntensity(100.0f);
  TEST_EQUAL(lmp1 == lmp4, false)
  TEST_NOT_EQUAL(hasher(lmp1), hasher(lmp4))

  // Test usability in unordered_set
  std::unordered_set<LogMzPeak> peak_set;
  peak_set.insert(lmp1);
  peak_set.insert(lmp2);  // Should not be added (equal to lmp1)
  peak_set.insert(lmp3);
  peak_set.insert(lmp4);

  TEST_EQUAL(peak_set.size(), 3)
  TEST_EQUAL(peak_set.count(lmp1), 1)
  TEST_EQUAL(peak_set.count(lmp3), 1)
  TEST_EQUAL(peak_set.count(lmp4), 1)
}
END_SECTION

/////////////////////////////////////////////////////////////
/////////////////////////////////////////////////////////////
START_SECTION((Experimental mass - free peak layouts preserve exact scientific fields))
{
  using InternalPeak = FLASHHelperClasses::InternalLogMzPeak;
  using PublicPeak = FLASHHelperClasses::LogMzPeak;
  static_assert(std::is_trivially_copyable_v<InternalPeak>);
  static_assert(std::is_standard_layout_v<InternalPeak>);
  static_assert(alignof(InternalPeak) == (OPENMS_FLASHDECONV_PEAK_LAYOUT == 8 ? 4 : 8));
  static_assert(sizeof(PublicPeak) == 32);
#if OPENMS_FLASHDECONV_PEAK_LAYOUT == 24
  static_assert(sizeof(InternalPeak) == 24);
#elif OPENMS_FLASHDECONV_PEAK_LAYOUT == 8
  static_assert(sizeof(InternalPeak) == 8);
#else
  static_assert(sizeof(InternalPeak) == 16);
#endif
  InternalPeak empty;
  TEST_EQUAL(empty.getMZ(), 0)
  TEST_EQUAL(empty.getLogMz(), -1000)
  TEST_EQUAL(empty.getIsotopeIndex(), -1)
  TEST_EQUAL(empty.getUnchargedMass(), 0)
  bool equal = true;
  std::vector<InternalPeak> compact;
  std::vector<PublicPeak> reference;
  for (int polarity = 0; polarity < 2; ++polarity)
  {
    for (int i = 0; i < 2048; ++i)
    {
      Peak1D source;
      source.setMZ(100.0 + (i % 503) * 0.123456789012345);
      source.setIntensity(static_cast<float>(i % 13));
      PublicPeak public_peak(source, polarity != 0);
      InternalPeak peak(source, polarity != 0);
      for (int z : {0, 1, 7, 200})
      {
        public_peak.setAbsCharge(z);
        peak.setAbsCharge(z);
        equal &= std::bit_cast<std::uint64_t>(peak.getUnchargedMass()) == std::bit_cast<std::uint64_t>(public_peak.getUnchargedMass());
      }
      for (int isotope : {-65535, -1, 0, 1, 65535})
      {
        peak.setIsotopeIndex(isotope);
        equal &= peak.getIsotopeIndex() == isotope && peak.getAbsCharge() == 200 && peak.isPositive() == (polarity != 0);
      }
      equal &= std::bit_cast<std::uint64_t>(peak.getMZ()) == std::bit_cast<std::uint64_t>(public_peak.getMZ());
      equal &= std::bit_cast<std::uint64_t>(peak.getLogMz()) == std::bit_cast<std::uint64_t>(public_peak.getLogMz());
      equal &= peak.getIntensity() == public_peak.getIntensity();
      equal &= std::hash<InternalPeak> {}(peak) == std::hash<PublicPeak> {}(public_peak);
      compact.push_back(peak);
      reference.push_back(public_peak);
    }
  }
  TEST_EQUAL(equal, true)
  std::sort(compact.begin(), compact.end());
  std::sort(reference.begin(), reference.end());
  bool sorted_equal = true;
  for (Size i = 0; i < compact.size(); ++i)
  {
    sorted_equal &= compact[i].getMZ() == reference[i].getMZ() && compact[i].getIntensity() == reference[i].getIntensity();
  }
  TEST_EQUAL(sorted_equal, true)
  TEST_EXCEPTION(Exception::InvalidValue, empty.setAbsCharge(201))
  TEST_EXCEPTION(Exception::InvalidValue, empty.setIsotopeIndex(65536))
  Peak1D carrier_source;
  carrier_source.setMZ(1125.5118055019082);
  PublicPeak carrier_reference(carrier_source, true);
  InternalPeak carrier_peak(carrier_source, true);
  carrier_reference.setPositive(false);
  carrier_peak.setPositive(false);
  TEST_EQUAL(std::bit_cast<std::uint64_t>(carrier_peak.getLogMz()), std::bit_cast<std::uint64_t>(carrier_reference.getLogMz()))
  TEST_EQUAL(std::bit_cast<std::uint64_t>(carrier_peak.getUnchargedMass()), std::bit_cast<std::uint64_t>(carrier_reference.getUnchargedMass()))
  PublicPeak inconsistent(carrier_source, true);
  inconsistent.setLogMz(1.234);
  TEST_EXCEPTION(Exception::InvalidValue, InternalPeak invalid(inconsistent))
  inconsistent.setLogMz(-1000);
  InternalPeak sentinel(inconsistent);
  TEST_EQUAL(sentinel.getLogMz(), -1000)
  PublicPeak overridden;
  overridden.setMass(1);
  TEST_EXCEPTION(Exception::InvalidValue, InternalPeak invalid(overridden))
  overridden.setMass(std::numeric_limits<double>::quiet_NaN());
  TEST_EXCEPTION(Exception::InvalidValue, InternalPeak invalid(overridden))
  overridden.setMass(-std::numeric_limits<double>::infinity());
  InternalPeak derived(overridden);
  TEST_EQUAL(derived.getUnchargedMass(), 0)

  // More than one source page; verify shared snapshots, caller isolation, source
  // destruction, detached copies and both sides of the 65536-element boundary.
  std::vector<InternalPeak> detached;
  {
    MSSpectrum source;
    source.setMSLevel(2);
    source.setRT(123.456);
    source.setNativeID("scan=42");
    for (Size i = 0; i < 65540; ++i)
    {
      Peak1D p;
      p.setMZ(400.0 + i * 0.000123456789);
      p.setIntensity(static_cast<float>(i));
      source.push_back(p);
    }
    DeconvolvedSpectrum ds;
    ds.setOriginalSpectrum(source);
    DeconvolvedSpectrum copy(ds);
    TEST_EQUAL(&ds.getOriginalSpectrum(), &copy.getOriginalSpectrum())
    TEST_EQUAL(copy.getOriginalSpectrum().getNativeID(), "scan=42")
    const auto before_standalone = InternalPeak::getSourceStatistics()[3];
    for (Size i : {Size(0), Size(65535), Size(65536), Size(65539)})
    {
      detached.emplace_back(copy.getOriginalSpectrum()[i], false);
#if OPENMS_FLASHDECONV_PEAK_LAYOUT == 17
      TEST_EQUAL(detached.back().getSourcePeak(), &copy.getOriginalSpectrum()[i])
#endif
    }
    TEST_EQUAL(InternalPeak::getSourceStatistics()[3], before_standalone)
#if OPENMS_FLASHDECONV_PEAK_LAYOUT == 8
    TEST_EQUAL(detached[1].getSourceMzAddress() + 1, detached[2].getSourceMzAddress())
    TEST_EQUAL(*detached[2].getSourceMzAddress(), copy.getOriginalSpectrum()[65536].getMZ())
#endif
    source[0].setMZ(99999);
    TEST_EQUAL(copy.getOriginalSpectrum()[0].getMZ(), 400)
    auto moved = std::move(ds);
    TEST_EQUAL(ds.getOriginalSpectrum().empty(), true)
    TEST_EQUAL(moved.getOriginalSpectrum().size(), 65540)
  }
  TEST_EQUAL(detached[0].getMZ(), 400)
  TEST_EQUAL(detached[1].getIntensity(), 65535)
  TEST_EQUAL(detached[2].getIntensity(), 65536)
  TEST_EQUAL(detached[3].getIntensity(), 65539)
  std::vector<InternalPeak> concurrent(512);
#pragma omp parallel for num_threads(4)
  for (int job = 0; job < 8; ++job)
  {
    MSSpectrum source;
    for (int j = 0; j < 64; ++j)
    {
      Peak1D p;
      p.setMZ(1000.0 + job * 10.0 + j * 0.0123456789);
      p.setIntensity(static_cast<float>(job * 64 + j));
      source.push_back(p);
    }
    DeconvolvedSpectrum ds;
    ds.setOriginalSpectrum(source);
    for (Size j = 0; j < 64; ++j)
    { concurrent[job * 64 + j] = InternalPeak(ds.getOriginalSpectrum()[j], true); }
  }
  bool concurrent_equal = true;
  for (Size i = 0; i < concurrent.size(); ++i)
  {
    const double mz = 1000.0 + (i / 64) * 10.0 + (i % 64) * 0.0123456789;
    concurrent_equal &= concurrent[i].getMZ() == mz && concurrent[i].getIntensity() == static_cast<float>(i);
    concurrent_equal &= std::bit_cast<std::uint64_t>(concurrent[i].getLogMz()) == std::bit_cast<std::uint64_t>(FLASHHelperClasses::getLogMz(mz, true));
  }
  TEST_EQUAL(concurrent_equal, true)

}
END_SECTION

#if OPENMS_FLASHDECONV_PEAK_LAYOUT == 17
START_SECTION((Indexed source capacity failures preserve existing values and cross parallel joins))
{
  using InternalPeak = FLASHHelperClasses::InternalLogMzPeak;
  const auto free_pages = 65535 - InternalPeak::getSourceStatistics()[1];
  MSSpectrum source;
  source.push_back(Peak1D(500.123456789, 12.5f));
  DeconvolvedSpectrum last;
  InternalPeak first;
  for (std::uint64_t i = 0; i < free_pages; ++i)
  {
    last.setOriginalSpectrum(source);
    if (i == 0) { first = InternalPeak(last.getOriginalSpectrum()[0], true); }
  }
  TEST_EQUAL(InternalPeak::getSourceStatistics()[1], 65535)
  const auto* last_owner = &last.getOriginalSpectrum();
  TEST_EXCEPTION(Exception::InvalidValue, last.setOriginalSpectrum(source))
  TEST_EQUAL(&last.getOriginalSpectrum(), last_owner)
  TEST_EQUAL(first.getMZ(), 500.123456789)
  std::array<std::exception_ptr, 4> errors;
#pragma omp parallel for num_threads(4)
  for (int job = 0; job < 4; ++job)
  {
    try
    {
      DeconvolvedSpectrum ds;
      ds.setOriginalSpectrum(source);
    }
    catch (...) { errors[job] = std::current_exception(); }
  }
  for (const auto& error : errors)
  {
    TEST_EQUAL(static_cast<bool>(error), true)
    if (error) { TEST_EXCEPTION(Exception::InvalidValue, std::rethrow_exception(error)) }
  }
  TEST_EQUAL(first.getMZ(), 500.123456789)
}
END_SECTION
#endif

END_TEST
