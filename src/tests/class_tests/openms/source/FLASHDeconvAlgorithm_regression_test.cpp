// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// --------------------------------------------------------------------------
// $Maintainer: OpenMS Team $
// $Authors: OpenMS Team $
// --------------------------------------------------------------------------

#include <OpenMS/ANALYSIS/TOPDOWN/FLASHDeconvAlgorithm.h>
#include <OpenMS/CONCEPT/ClassTest.h>
#include <OpenMS/FORMAT/MzMLFile.h>
#include <OpenMS/test_config.h>
#include <algorithm>
#include <string>
#include <utility>
#include <vector>
#ifdef _OPENMP
  #include <omp.h>
#endif

using namespace OpenMS;

namespace
{
// Exercise the linked private filter without adding a production test hook.
template<class Tag, typename Tag::Type Member>
struct Access
{
  friend typename Tag::Type member(Tag)
  { return Member; }
};
struct Filter
{
  using Type = void (*)(MSExperiment&);
  friend Type member(Filter);
};
template struct Access<Filter, &FLASHDeconvAlgorithm::filterLowPeaks_>;

void compareGroups(const PeakGroup& left, const PeakGroup& right, uint feature_index_offset)
{
  TEST_EQUAL(left.size(), right.size())
  TEST_EQUAL(left.getTargetDecoyType(), right.getTargetDecoyType())
  TEST_EQUAL(left.getMonoMass(), right.getMonoMass())
  TEST_EQUAL(left.getIntensity(), right.getIntensity())
  TEST_TRUE(left.getAbsChargeRange() == right.getAbsChargeRange())
  TEST_EQUAL(left.getSNR(), right.getSNR())
  TEST_EQUAL(left.getQscore(), right.getQscore())
  TEST_EQUAL(left.getQscore2D(), right.getQscore2D())
  TEST_EQUAL(left.getQvalue(), right.getQvalue())
  TEST_EQUAL(right.getFeatureIndex(), left.getFeatureIndex() == 0 ? 0 : left.getFeatureIndex() + feature_index_offset)
  TEST_EQUAL(left.getIsotopeCosine(), right.getIsotopeCosine())
  TEST_EQUAL(left.getAvgPPMError(), right.getAvgPPMError())
  TEST_TRUE(left.getIsotopeIntensities() == right.getIsotopeIntensities())
  for (Size i = 0; i < std::min(left.size(), right.size()); ++i)
  {
    TEST_EQUAL(left[i].mz, right[i].mz)
    TEST_EQUAL(left[i].intensity, right[i].intensity)
    TEST_EQUAL(left[i].abs_charge, right[i].abs_charge)
    TEST_EQUAL(left[i].isotopeIndex, right[i].isotopeIndex)
  }
}
} // namespace

START_TEST(FLASHDeconvAlgorithm_regression, "$Id$")

START_SECTION([EXTRA] serial and parallel public runs preserve positive results and input metadata)
{
#ifdef _OPENMP
  const int saved_threads = omp_get_max_threads();
  const int saved_dynamic = omp_get_dynamic();
  omp_set_dynamic(0);
#endif
  MSExperiment source;
  MzMLFile().load(OPENMS_GET_TEST_DATA_PATH("FLASHDeconv_sample_input1.mzML"), source);
  const auto rich = std::find_if(source.begin(), source.end(), [](const MSSpectrum& s) { return ! s.empty() && s.getMSLevel() == 1; });
  TEST_TRUE(rich != source.end())
  if (rich != source.end())
  {
    const auto highest
      = std::max_element(rich->begin(), rich->end(), [](const Peak1D& a, const Peak1D& b) { return a.getIntensity() < b.getIntensity(); });
    MSExperiment input;
    input.getSourceFiles() = source.getSourceFiles();
    if (input.getSourceFiles().empty()) { input.getSourceFiles().emplace_back(); }
    for (auto& file : input.getSourceFiles())
    {
      file.setNativeIDTypeAccession("MS:1000768");
      file.setNativeIDType("Thermo nativeID format");
    }
    const UInt levels[] = {1, 2, 1, 3, 1, 2, 1, 2, 3, 1, 2, 1};
    const int scans[] = {1, 2, 2, 3, 4, 5, 6, 7, 8, 2, 9, 10};
    for (Size i = 0; i < 12; ++i)
    {
      MSSpectrum spectrum = *rich;
      spectrum.setMSLevel(levels[i]);
      spectrum.setType(SpectrumSettings::SpectrumType::CENTROID);
      spectrum.setRT(i == 9 ? 4.0 : 2.0 * i);
      const int controller = i == 2 ? 2 : (i == 9 ? 3 : 1);
      spectrum.setNativeID("controllerType=0 controllerNumber=" + std::to_string(controller) + " scan=" + std::to_string(scans[i]));
      spectrum.setName("regression-" + std::to_string(i));
      spectrum.setMetaValue("filter string", i == 5 ? "cv=45 " : "cv=0 ");
      spectrum.setMetaValue("regression-index", int(i));
      spectrum.getPrecursors().clear();
      if (levels[i] > 1)
      {
        Precursor precursor;
        precursor.setMZ(i == 7 || i == 8 ? highest->getMZ() : 100000.0);
        precursor.setIsolationWindowLowerOffset(2.5);
        precursor.setIsolationWindowUpperOffset(2.5);
        spectrum.getPrecursors().push_back(precursor);
      }
      if (i == 4 || i == 10) { spectrum.clear(false); }
      spectrum.updateRanges();
      input.addSpectrum(spectrum);
      TEST_EQUAL(FLASHDeconvAlgorithm::getScanNumber(input, i), scans[i])
    }
    for (const bool fdr : {false, true})
    {
      std::vector<DeconvolvedSpectrum> reference;
      std::vector<FLASHHelperClasses::MassFeature> reference_features;
      MSExperiment reference_input;
      for (const int threads : {1, 4})
      {
#ifdef _OPENMP
        omp_set_num_threads(threads);
#endif
        FLASHDeconvAlgorithm algorithm;
        Param parameters = algorithm.getDefaults();
        TEST_EQUAL(int(parameters.getValue("precursor_MS1_window")), 1)
        parameters.setValue("SD:tol", DoubleList {10.0, 10.0, 10.0});
        parameters.setValue("SD:min_cos", DoubleList {0.85, 0.85, 0.85});
        parameters.setValue("SD:min_snr", DoubleList {0.5, 0.5, 0.5});
        parameters.setValue("report_FDR", fdr ? "true" : "false");
        algorithm.setParameters(parameters);
        MSExperiment filtered = input;
        std::vector<DeconvolvedSpectrum> spectra;
        std::vector<FLASHHelperClasses::MassFeature> features;
        algorithm.run(filtered, spectra, features);
        TEST_EQUAL(filtered.size(), input.size())
        TEST_TRUE(filtered.getSourceFiles() == input.getSourceFiles())
        TEST_EQUAL(spectra.size(), 10)
        Size groups = 0;
        bool empty_lower_fallback = false, third_level_fallback = false;
        for (Size i = 0; i < spectra.size(); ++i)
        {
          const auto& result = spectra[i];
          groups += result.size();
          if (i > 0) { TEST_TRUE(result.getScanNumber() >= spectra[i - 1].getScanNumber()) }
          const auto& id = result.getOriginalSpectrum().getNativeID();
          if (id == "controllerType=0 controllerNumber=1 scan=5")
          {
            empty_lower_fallback = result.getPrecursorPeakGroup().empty() && result.getPrecursorScanNumber() == 4;
          }
          if (id == "controllerType=0 controllerNumber=1 scan=3")
          {
            third_level_fallback = result.getPrecursorPeakGroup().empty() && result.getPrecursorScanNumber() == 2;
          }
        }
        TEST_TRUE(groups > 0)
        TEST_TRUE(empty_lower_fallback)
        TEST_TRUE(third_level_fallback)
        for (Size i = 0; i < std::min(filtered.size(), input.size()); ++i)
        {
          TEST_TRUE(static_cast<const SpectrumSettings&>(filtered[i]) == static_cast<const SpectrumSettings&>(input[i]))
          TEST_EQUAL(filtered[i].getName(), input[i].getName())
          TEST_EQUAL(filtered[i].getRT(), input[i].getRT())
          TEST_EQUAL(filtered[i].getMSLevel(), input[i].getMSLevel())
          TEST_TRUE(filtered[i].size() <= input[i].size() && filtered[i].size() <= 30000)
          TEST_TRUE(filtered[i].isSorted())
          for (const auto& peak : filtered[i])
          {
            TEST_TRUE(peak.getMZ() >= input[i].getMinMZ() && peak.getMZ() <= input[i].getMaxMZ())
            TEST_TRUE(peak.getIntensity() > highest->getIntensity() / 1000.0)
          }
        }
        if (threads == 1)
        {
          reference.swap(spectra);
          reference_features.swap(features);
          reference_input = std::move(filtered);
          continue;
        }
        // MassFeatureTrace intentionally advances a process-global counter.
        // Require the exact expected advance, including zero-valued sentinels.
        const uint feature_index_offset = static_cast<uint>(reference_features.size());
        TEST_TRUE(filtered == reference_input)
        TEST_EQUAL(spectra.size(), reference.size())
        for (Size i = 0; i < std::min(spectra.size(), reference.size()); ++i)
        {
          const auto& left = reference[i];
          const auto& right = spectra[i];
          TEST_TRUE(left.getOriginalSpectrum() == right.getOriginalSpectrum())
          TEST_EQUAL(left.getScanNumber(), right.getScanNumber())
          TEST_EQUAL(left.getPrecursorScanNumber(), right.getPrecursorScanNumber())
          TEST_EQUAL(left.getPrecursorCharge(), right.getPrecursorCharge())
          compareGroups(left.getPrecursorPeakGroup(), right.getPrecursorPeakGroup(), feature_index_offset);
          TEST_EQUAL(left.size(), right.size())
          for (Size j = 0; j < std::min(left.size(), right.size()); ++j)
          {
            compareGroups(left[j], right[j], feature_index_offset);
          }
        }
        TEST_EQUAL(features.size(), reference_features.size())
        for (Size i = 0; i < std::min(features.size(), reference_features.size()); ++i)
        {
          const auto& left = reference_features[i];
          const auto& right = features[i];
          TEST_EQUAL(right.index, left.index + feature_index_offset)
          TEST_EQUAL(left.avg_mass, right.avg_mass)
          TEST_EQUAL(left.scan_number, right.scan_number)
          TEST_EQUAL(left.min_scan_number, right.min_scan_number)
          TEST_EQUAL(left.max_scan_number, right.max_scan_number)
          TEST_EQUAL(left.rep_charge, right.rep_charge)
          TEST_EQUAL(left.isotope_score, right.isotope_score)
          TEST_EQUAL(left.qscore, right.qscore)
          TEST_EQUAL(left.is_decoy, right.is_decoy)
          TEST_EQUAL(left.ms_level, right.ms_level)
          TEST_TRUE(left.per_charge_intensity == right.per_charge_intensity)
          TEST_TRUE(left.per_isotope_intensity == right.per_isotope_intensity)
        }
      }
    }
  }
#ifdef _OPENMP
  omp_set_num_threads(saved_threads);
  omp_set_dynamic(saved_dynamic);
#endif
}
END_SECTION

START_SECTION([EXTRA] filtering handles the exact centroid bound and aligned arrays)
{
  MSExperiment input;
  MSSpectrum boundary;
  boundary.setType(SpectrumSettings::SpectrumType::CENTROID);
  for (Size i = 0; i < 30000; ++i)
  {
    boundary.emplace_back(1000.0 + 0.01 * i, 1000.0);
  }
  input.addSpectrum(boundary);
  member(Filter {})(input);
  TEST_EQUAL(input[0].size(), 30000)
  TEST_TRUE(input[0].isSorted())

  MSSpectrum arrays;
  arrays.setMSLevel(2);
  arrays.setRT(17.25);
  arrays.setNativeID("scan=41");
  arrays.setMetaValue("preserved", "array metadata");
  for (Size i = 0; i < 3; ++i)
  {
    arrays.emplace_back(100.0 + i, 10.0 + i);
  }
  arrays.getFloatDataArrays().emplace_back();
  arrays.getFloatDataArrays()[0].setName("float");
  arrays.getIntegerDataArrays().emplace_back();
  arrays.getIntegerDataArrays()[0].setName("integer");
  arrays.getStringDataArrays().emplace_back();
  arrays.getStringDataArrays()[0].setName("string");
  for (Size i = 0; i < 3; ++i)
  {
    arrays.getFloatDataArrays()[0].push_back(float(i));
    arrays.getIntegerDataArrays()[0].push_back(int(i));
    arrays.getStringDataArrays()[0].push_back(std::to_string(i));
  }
  arrays.updateRanges();
  input.clear(true);
  input.addSpectrum(arrays);
  member(Filter {})(input);
  TEST_TRUE(input[0] == arrays)
  input.clear(true);
  member(Filter {})(input);
  TEST_TRUE(input.empty())
}
END_SECTION

END_TEST
