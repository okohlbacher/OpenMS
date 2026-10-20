// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// --------------------------------------------------------------------------
// $Maintainer: OpenMS Team $
// $Authors: OpenMS Team $
// --------------------------------------------------------------------------

#include <OpenMS/CHEMISTRY/EmpiricalFormula.h>
#include <OpenMS/CHEMISTRY/ISOTOPEDISTRIBUTION/CoarseIsotopePatternGenerator.h>
#include <OpenMS/CONCEPT/ClassTest.h>
#include <OpenMS/CONCEPT/Constants.h>
#include <OpenMS/CONCEPT/Exception.h>
#include <OpenMS/FORMAT/FLASHDeconvSpectrumFile.h>
#include <OpenMS/SYSTEM/ExternalProcess.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <map>
#include <sstream>
#include <stdexcept>
#ifdef _OPENMP
  #include <omp.h>
#endif

using namespace OpenMS;
using Avg = FLASHHelperClasses::PrecalculatedAveragine;
using Spectrum = DeconvolvedSpectrum;

namespace
{
std::string environmentValue(const char* key)
{
  const char* value = std::getenv(key);
  return value == nullptr ? "" : value;
}

Spectrum spectrum(unsigned scan, unsigned level, bool positive, const Avg& avg)
{
  Spectrum result(scan);
  result.setQuantities(FLASHHelperClasses::IsobaricQuantities {});
  MSSpectrum raw;
  raw.setMSLevel(level);
  raw.setRT(scan * 1.23456789);
  raw.setNativeID("scan=" + std::to_string(scan));
  const double mass = 5000.123456;
  PeakGroup pg(2, 3, positive);
  pg.setScanNumber(scan);
  pg.setFeatureIndex(scan);
  pg.setRepAbsCharge(2);
  pg.setIsotopeCosine(.9876543);
  pg.setChargeIsotopeCosine(2, .8765432);
  pg.setChargeSNR(2, 8.765432);
  pg.setSNR(9.123456);
  pg.setChargeScore(.7654321);
  pg.setQscore(.9123456);
  pg.setQscore2D(.9234567);
  pg.setQvalue(.0123456);
  // Cover the actual model scan bounds rather than assuming four isotopes suffice.
  const int max_isotope = static_cast<int>(avg.getLastIndex(mass));
  const int first_noise_isotope
    = std::max(0, static_cast<int>(avg.getApexIndex(mass)) - static_cast<int>(avg.getLeftCountFromApex(mass)) + pg.getMinNegativeIsotopeIndex());
  if (max_isotope < first_noise_isotope) { throw std::runtime_error("Fixture model has no nonnegative isotope window"); }
  for (unsigned charge = 2; charge <= 3; ++charge)
  {
    for (int isotope = -1; isotope <= max_isotope; ++isotope)
    {
      const double mz = (mass + isotope * pg.getIsotopeDaDistance()) / charge + FLASHHelperClasses::getChargeMass(positive);
      Peak1D peak(mz, 101.12345 + charge * 10 + isotope * 3.14159);
      raw.push_back(peak);
      if (isotope >= 0)
      {
        FLASHHelperClasses::LogMzPeak log_peak(peak, positive);
        log_peak.abs_charge = charge;
        log_peak.isotopeIndex = isotope;
        pg.push_back(log_peak);
        // A quarter-isotope offset is outside 10ppm and avoids half-bin rounding ties.
        if (isotope == first_noise_isotope) { raw.emplace_back(mz + .25 * pg.getIsotopeDaDistance() / charge, 17.98765); }
      }
    }
  }
  pg.updateMonoMassAndIsotopeIntensities(1e-5);
  pg.setMonoisotopicMass(mass);
  result.push_back(pg);
  pg.setTargetDecoyType(PeakGroup::TargetDecoyType::signal_decoy);
  result.push_back(pg);
  raw.sortByPosition();
  result.setOriginalSpectrum(raw);
  if (level > 1)
  {
    Precursor precursor;
    precursor.setMZ(2501.13579);
    precursor.setIntensity(567.89123);
    precursor.setCharge(2);
    result.setPrecursor(precursor);
    result.setPrecursorScanNumber(scan - 1);
    result.setPrecursorPeakGroup(result[0]);
  }
  return result;
}

std::string state(const std::vector<Spectrum>& spectra)
{
  std::ostringstream out;
  out << std::hexfloat << std::setprecision(17);
  for (const auto& spec : spectra)
  {
    out << spec.getScanNumber() << '\t' << spec.getOriginalSpectrum().getMSLevel() << '\n';
    for (const auto& pg : spec)
    {
      out << pg.getTargetDecoyType() << '\t' << pg.getIndex() << '\t' << pg.getMonoMass() << '\t' << pg.getIntensity() << '\t' << pg.getQscore()
          << '\t' << pg.getQscore2D() << '\t' << pg.size();
      for (const auto& peak : pg)
      {
        out << '\t' << peak.mz << ',' << peak.intensity << ',' << peak.abs_charge << ',' << peak.isotopeIndex;
      }
      // Observe recruited negative peaks through their isotope effect on a copy.
      auto probe = pg;
      probe.updateMonoMassAndIsotopeIntensities(1e-5);
      for (float value : probe.getIsotopeIntensities())
      {
        out << '\t' << value;
      }
      out << '\n';
    }
  }
  return out.str();
}

void child(const std::string& method, const std::string& scenario, const Avg& avg, const Avg& decoy_avg)
{
  std::vector<Spectrum> spectra;
  // Four workers format a full 16-spectrum wave followed by a three-job tail.
  for (unsigned i = 1; i <= 19; ++i)
  {
    spectra.push_back(spectrum(i, 1 + i % 2, i % 2 == 0, avg));
  }
  auto empty = spectrum(20, 1, true, avg);
  empty.clear();
  spectra.insert(spectra.begin() + 5, empty);
  const auto before = state(spectra);
  const bool detail = scenario != "plain", fdr = scenario == "fdr";
  if (detail)
  {
    // The current baseline const noise getter is authoritative for byte parity.
    // Its inherited unqualified abs may truncate sub-unit isotope errors, so do
    // not require a returned noise count or fossilize an empty-result behavior.
    // Independently prove positive signal and deliberate off-pattern raw inputs.
    for (const auto& spec : spectra)
    {
      if (spec.empty()) { continue; }
      const auto& pg = spec[0];
      if (pg.empty() || pg.getIntensity() <= 0) { throw std::runtime_error("Fixture signal group would be vacuous"); }
      bool off_pattern = false;
      for (const auto& peak : spec.getOriginalSpectrum())
      {
        if (peak.getIntensity() != static_cast<float>(17.98765)) { continue; }
        for (int charge = 2; charge <= 3; ++charge)
        {
          const double center = pg.getMonoMass() / charge + FLASHHelperClasses::getChargeMass(pg.isPositive());
          const double delta = pg.getIsotopeDaDistance() / charge;
          const int isotope = static_cast<int>(std::round((peak.getMZ() - center) / delta));
          if (isotope >= 0 && isotope <= static_cast<int>(avg.getLastIndex(pg.getMonoMass()))
              && std::abs(peak.getMZ() - center - isotope * delta) > peak.getMZ() * 10 * 1e-6 * .8)
          {
            off_pattern = true;
          }
        }
      }
      if (! off_pattern) { throw std::runtime_error("Fixture off-pattern raw peaks would be vacuous"); }
    }
  }
  std::vector<std::string> names {environmentValue("OPENMS_WRITER_MS1"), environmentValue("OPENMS_WRITER_MS2")};
  std::vector<std::ofstream> streams(2);
  for (Size i = 0; i < streams.size(); ++i)
  {
    streams[i].open(names[i], std::ios::out | std::ios::binary);
    if (! streams[i]) { throw std::runtime_error("Cannot open writer test output"); }
    streams[i] << std::scientific << std::setprecision(7);
    FLASHDeconvSpectrumFile::writeDeconvolvedMassesHeader(streams[i], unsigned(i + 1), detail, fdr);
  }
  if (scenario == "bad-stream") { streams[1].setstate(std::ios::failbit); }
  if (method == "serial")
  {
    for (auto& spec : spectra)
    {
      FLASHDeconvSpectrumFile::writeDeconvolvedMasses(spec, streams[spec.getOriginalSpectrum().getMSLevel() - 1], "fixture.mzML", avg, decoy_avg, 10,
                                                      detail, fdr, 1.0);
    }
  }
  else
  {
    FLASHDeconvSpectrumFile::writeDeconvolvedMassesParallel(spectra, streams, names, "fixture.mzML", avg, decoy_avg, {10, 10}, detail, fdr, 1.0);
  }
  if (state(spectra) != before) { throw std::runtime_error("Const writer changed its input spectra"); }
  for (Size i = 0; i < streams.size(); ++i)
  {
    if (streams[i].precision() != 7 || (streams[i].flags() & std::ios::floatfield) != std::ios::scientific)
    {
      throw std::runtime_error("Caller formatting changed");
    }
    streams[i].close();
    if (streams[i].fail() != (scenario == "bad-stream" && i == 1)) { throw std::runtime_error("Stream failure state changed"); }
  }
  // Check literal per-MS indices and scan order independently of byte parity.
  for (Size level = 0; level < names.size(); ++level)
  {
    std::ifstream file(names[level]);
    std::string line;
    if (! std::getline(file, line) || line.empty()) { throw std::runtime_error("Missing TSV header"); }
    unsigned rows = 0;
    while (std::getline(file, line))
    {
      std::istringstream fields(line);
      std::string index, input_name, scan;
      std::getline(fields, index, '\t');
      std::getline(fields, input_name, '\t');
      std::getline(fields, scan, '\t');
      const unsigned expected_scan = 2 * (rows / (fdr ? 2 : 1)) + (level == 0 ? 2 : 1);
      if (std::stoul(index) != rows + 1 || std::stoul(scan) != expected_scan) { throw std::runtime_error("TSV order/index changed"); }
      ++rows;
    }
    const unsigned expected_rows = scenario == "bad-stream" && level == 1 ? 0 : (level == 0 ? 9 : 10) * (fdr ? 2 : 1);
    if (rows != expected_rows) { throw std::runtime_error("Incomplete writer output"); }
  }
  std::ofstream snapshot(environmentValue("OPENMS_WRITER_STATE"), std::ios::binary);
  snapshot << state(spectra);
  snapshot.close();
  if (! snapshot) { throw std::runtime_error("Cannot write post-state"); }
}
} // namespace

START_TEST(FLASHDeconvSpectrumFile_parallel, "$Id$")
const std::string method = environmentValue("OPENMS_WRITER_METHOD");
#ifdef _OPENMP
omp_set_dynamic(0);
omp_set_num_threads(method == "batch4" ? 4 : 1);
#endif
CoarseIsotopePatternGenerator generator(100, false);
(void)generator.run(EmpiricalFormula("H2O"));
Avg avg(50, 10000, 25, generator, false);
Avg decoy_avg(50, 10000, 25, generator, false, Constants::ISOTOPE_MASSDIFF_55K_U * .9444);
avg.setMaxIsotopeIndex(99);
decoy_avg.setMaxIsotopeIndex(99);
if (! method.empty())
{
  child(method, environmentValue("OPENMS_WRITER_SCENARIO"), avg, decoy_avg);
  return 0;
}

START_SECTION((writeDeconvolvedMassesParallel : exact ordered bytes and PG state))
{
  // Counters live for the process, so each public writer starts in a fresh child.
  for (const std::string& scenario : {std::string("detail"), std::string("plain"), std::string("fdr"), std::string("bad-stream")})
  {
    std::array<std::array<std::string, 3>, 3> paths;
    for (Size run = 0; run < paths.size(); ++run)
    {
      const std::string mode = run == 0 ? "serial" : (run == 1 ? "batch1" : "batch4");
      for (Size output = 0; output < paths[run].size(); ++output)
      {
        NEW_TMP_FILE_EXT(paths[run][output], "." + scenario + "." + mode + "." + std::to_string(output));
      }
      const std::map<std::string, std::string> environment {{"OPENMS_WRITER_METHOD", mode},
                                                            {"OPENMS_WRITER_SCENARIO", scenario},
                                                            {"OPENMS_WRITER_MS1", paths[run][0]},
                                                            {"OPENMS_WRITER_MS2", paths[run][1]},
                                                            {"OPENMS_WRITER_STATE", paths[run][2]}};
      std::string output, error;
      ExternalProcess process([&](const std::string& text) { output += text; }, [&](const std::string& text) { output += text; });
      const auto result
        = process.run(std::filesystem::absolute(argv[0]).string(), {}, "", false, error, ExternalProcess::IO_MODE::READ_ONLY, environment);
      TEST_EQUAL(result == ExternalProcess::RETURNSTATE::SUCCESS, true)
      if (result != ExternalProcess::RETURNSTATE::SUCCESS) { STATUS(error + output) }
    }
    for (Size run = 1; run < paths.size(); ++run)
    {
      for (Size output = 0; output < paths[run].size(); ++output)
      {
        TEST_FILE_EQUAL(paths[run][output].c_str(), paths[0][output].c_str())
      }
    }
  }
}
END_SECTION

START_SECTION((writeDeconvolvedMassesParallel : prevalidation preserves state and indices))
{
  std::string ms1, ms2;
  NEW_TMP_FILE(ms1)
  NEW_TMP_FILE(ms2)
  std::vector<std::string> names {ms1, ms2};
  std::vector<std::ofstream> streams(2);
  for (Size i = 0; i < streams.size(); ++i)
  {
    streams[i].open(names[i], std::ios::out);
    FLASHDeconvSpectrumFile::writeDeconvolvedMassesHeader(streams[i], unsigned(i + 1), true, false);
  }
  std::vector<Spectrum> spectra {spectrum(1, 1, true, avg), spectrum(2, 2, false, avg)};
  const auto before = state(spectra);
  const auto position = streams[0].tellp();
  TEST_EXCEPTION(Exception::InvalidParameter, FLASHDeconvSpectrumFile::writeDeconvolvedMassesParallel(spectra, streams, {}, "fixture.mzML", avg,
                                                                                                      decoy_avg, {10, 10}, true, false, 1.0))
  TEST_EXCEPTION(Exception::InvalidParameter, FLASHDeconvSpectrumFile::writeDeconvolvedMassesParallel(spectra, streams, names, "fixture.mzML", avg,
                                                                                                      decoy_avg, {}, true, false, 1.0))
  TEST_EQUAL(state(spectra), before)
  TEST_EQUAL(streams[0].tellp() == position, true)
  FLASHDeconvSpectrumFile::writeDeconvolvedMassesParallel(spectra, streams, names, "fixture.mzML", avg, decoy_avg, {10, 10}, true, false, 1.0);
  TEST_EQUAL(state(spectra), before)
  for (auto& stream : streams)
  {
    stream.close();
    TEST_EQUAL(stream.fail(), false)
  }
  for (const auto& name : names)
  {
    std::ifstream file(name);
    std::string line;
    std::getline(file, line);
    std::getline(file, line);
    TEST_EQUAL(line.substr(0, 2), "1\t")
  }
}
END_SECTION
END_TEST
