// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// --------------------------------------------------------------------------
// $Maintainer: Kyowon Jeong, Jihyung Kim $
// $Authors: Kyowon Jeong, Jihyung Kim $
// --------------------------------------------------------------------------

#include <OpenMS/ANALYSIS/TOPDOWN/FLASHHelperClasses.h>
#include <OpenMS/CHEMISTRY/ModificationsDB.h>
#include <OpenMS/KERNEL/MSSpectrum.h>
#include <OpenMS/SYSTEM/BuildInfo.h>
#include <bit>
#include <exception>
#include <map>
#include <mutex>
#include <typeinfo>
#include <utility>
#ifdef _OPENMP
  #include <omp.h>
#endif

namespace OpenMS
{
  FLASHHelperClasses::PrecalculatedAveragine::PrecalculatedAveragine(const double min_mass,
                                                                     const double max_mass,
                                                                     const double delta,
                                                                     CoarseIsotopePatternGenerator& generator,
                                                                     const bool use_RNA_averagine,
                                                                     const double decoy_iso_distance):
      mass_interval_(delta),
      min_mass_(min_mass)
  {
    std::vector<double> masses;
    int i = 0;
    // Preserve the original mass grid, including non-aligned bounds.
    while (true)
    {
      double mass = i * mass_interval_;
      i++;
      if (mass < min_mass) { continue; }
      if (mass > max_mass) { break; }
      masses.push_back(mass);
    }

    const Size bin_count = masses.size();
    apex_index_.resize(bin_count);
    right_count_from_apex_.resize(bin_count);
    left_count_from_apex_.resize(bin_count);
    average_mono_mass_difference_.resize(bin_count);
    abundant_mono_mass_difference_.resize(bin_count);
    isotopes_.resize(bin_count);
    snr_mul_factor_.resize(bin_count);
    std::vector<std::exception_ptr> errors(bin_count);

    const auto calculate_bin = [&](const Size index, CoarseIsotopePatternGenerator& local_generator) {
      const double mass = masses[index];
      auto iso = use_RNA_averagine ? local_generator.estimateFromRNAMonoWeight(mass) : local_generator.estimateFromPeptideMonoWeight(mass);

      if (decoy_iso_distance > 0)
      {
        auto decoy_iso(iso);

        for (Size k = 0; k < iso.size(); k++)
        {
          decoy_iso[k].setMZ(iso[k].getMZ() * decoy_iso_distance);
        }
        decoy_iso.sortByMass();
        decoy_iso.renormalize();

        iso = decoy_iso;
      }

      const double min_pwr = .9999;
      const Size min_iso_length = 2;
      const int min_left_right_count = 2;
      double total_pwr = .0;
      size_t most_abundant_index_ = 0;
      double most_abundant_int = 0;

      /// sum of squared intensities to see the total power of isotope pattern. The range of isotope pattern is
      /// determined so those within range cover min_pwr of the total power.
      for (Size k = 0; k < iso.size(); k++)
      {
        total_pwr += iso[k].getIntensity() * iso[k].getIntensity();
        if (most_abundant_int >= iso[k].getIntensity()) { continue; }
        most_abundant_int = iso[k].getIntensity();
        most_abundant_index_ = k;
      }

      int left_count = 0;
      int right_count = (int)iso.size() - 1;
      int trim_count = 0;
      double pwr = 0;
      while (iso.size() - trim_count > min_iso_length && left_count < right_count)
      {
        double lint = iso[left_count].getIntensity();
        double rint = iso[right_count].getIntensity();

        bool trim_left = true;
        if (lint < rint) { pwr += lint * lint; }
        else
        {
          pwr += rint * rint;
          trim_left = false;
        }
        if (total_pwr - pwr < total_pwr * min_pwr) { break; }

        trim_count++;
        if (trim_left)
        {
          iso[left_count].setIntensity(0);
          left_count++;
        }
        else
        {
          iso[right_count].setIntensity(0); // for trimming
          right_count--;
        }
      }
      total_pwr -= pwr;

      left_count = (int)most_abundant_index_ - left_count;
      right_count = right_count - (int)most_abundant_index_;

      double intensity_sum = 0;
      for (auto& k : iso)
      {
        float ori_int = k.getIntensity();
        k.setIntensity(ori_int / (float)sqrt(total_pwr));
        intensity_sum += k.getIntensity();
      }
      left_count = left_count < min_left_right_count ? min_left_right_count : left_count;
      right_count = right_count < min_left_right_count ? min_left_right_count : right_count;

      apex_index_[index] = most_abundant_index_;
      right_count_from_apex_[index] = right_count;
      left_count_from_apex_[index] = left_count;
      average_mono_mass_difference_[index] = iso.averageMass() - iso[0].getMZ();
      abundant_mono_mass_difference_[index] = iso.getMostAbundant().getMZ() - iso[0].getMZ();
      isotopes_[index] = iso;
      snr_mul_factor_[index] = intensity_sum * intensity_sum;
    };

    // A concrete worker copy would slice an overridden generator::run().
    // Keep derived generators on the caller thread with their original state.
    if (typeid(generator) != typeid(CoarseIsotopePatternGenerator))
    {
      for (Size index = 0; index < bin_count; ++index)
      {
        calculate_bin(index, generator);
      }
    }
    else
    {
      int worker_count = 1;
#ifdef _OPENMP
      if (!Internal::OpenMSBuildInfo::isOpenMPParallelRegion())
      {
        worker_count = static_cast<int>(std::min(bin_count, static_cast<Size>(omp_get_max_threads())));
        worker_count = std::max(1, worker_count);
      }
#endif
      // Copy configurable generators on the caller: an allocation failure must
      // not escape an OpenMP region. Each worker then owns its generator state.
      std::vector<CoarseIsotopePatternGenerator> generators(worker_count, generator);
#pragma omp parallel for num_threads(worker_count) schedule(static) if (worker_count > 1)
      for (SignedSize index = 0; index < static_cast<SignedSize>(bin_count); ++index)
      {
        int worker = 0;
#ifdef _OPENMP
        worker = omp_get_thread_num();
#endif
        auto& local_generator = generators[worker];
        try
        {
          calculate_bin(static_cast<Size>(index), local_generator);
        }
        catch (...)
        {
          errors[index] = std::current_exception();
        }
      }
    }

    // Rethrow the first failing mass bin and retain the ordered prefix maxima.
    int max_left_count = 0;
    int max_right_count = 0;
    for (Size index = 0; index < bin_count; ++index)
    {
      if (errors[index]) { std::rethrow_exception(errors[index]); }
      max_left_count = std::max(max_left_count, left_count_from_apex_[index]);
      max_right_count = std::max(max_right_count, right_count_from_apex_[index]);
      left_count_from_apex_[index] = max_left_count;
      right_count_from_apex_[index] = max_right_count;
    }
  }

  Size FLASHHelperClasses::PrecalculatedAveragine::massToIndex_(const double mass) const
  {
    Size i = (Size)round(std::max(.0, mass - min_mass_) / mass_interval_);
    i = std::min(i, isotopes_.size() - 1);
    return i;
  }

  IsotopeDistribution FLASHHelperClasses::PrecalculatedAveragine::get(const double mass) const
  {
    return isotopes_[massToIndex_(mass)];
  }

  size_t FLASHHelperClasses::PrecalculatedAveragine::getMaxIsotopeIndex() const
  {
    return max_isotope_index_;
  }

  Size FLASHHelperClasses::PrecalculatedAveragine::getLeftCountFromApex(const double mass) const
  {
    return (Size)left_count_from_apex_[massToIndex_(mass)];
  }

  double FLASHHelperClasses::PrecalculatedAveragine::getAverageMassDelta(const double mass) const
  {
    return average_mono_mass_difference_[massToIndex_(mass)];
  }

  double FLASHHelperClasses::PrecalculatedAveragine::getMostAbundantMassDelta(const double mass) const
  {
    return abundant_mono_mass_difference_[massToIndex_(mass)];
  }

  double FLASHHelperClasses::PrecalculatedAveragine::getSNRMultiplicationFactor(const double mass) const
  {
    return snr_mul_factor_[massToIndex_(mass)];
  }

  Size FLASHHelperClasses::PrecalculatedAveragine::getRightCountFromApex(const double mass) const
  {
    return (Size)right_count_from_apex_[massToIndex_(mass)];
  }

  Size FLASHHelperClasses::PrecalculatedAveragine::getApexIndex(const double mass) const
  {
    return apex_index_[massToIndex_(mass)];
  }

  Size FLASHHelperClasses::PrecalculatedAveragine::getLastIndex(const double mass) const
  {
    Size index = massToIndex_(mass);
    return apex_index_[index] + right_count_from_apex_[index];
  }

  void FLASHHelperClasses::PrecalculatedAveragine::setMaxIsotopeIndex(const int index)
  {
    max_isotope_index_ = index;
  }

  FLASHHelperClasses::LogMzPeak::LogMzPeak(const Peak1D& peak, const bool positive):
      data_ {peak.getMZ(),        FLASHHelperClasses::getLogMz(peak.getMZ(), positive),        0,
             peak.getIntensity(), static_cast<std::int16_t>(positive ? 0 : NEGATIVE_POLARITY), 0}
  {
  }

  double FLASHHelperClasses::LogMzPeak::getUnchargedMass() const
  {
    if (getAbsCharge() == 0) { return .0; }
    if (getMass() <= 0) { return (getMZ() - getChargeMass(isPositive())) * (float)getAbsCharge(); }
    return getMass();
  }

  bool FLASHHelperClasses::LogMzPeak::operator<(const LogMzPeak& a) const
  {
    if (this->getLogMz() == a.getLogMz()) { return this->getIntensity() < a.getIntensity(); }
    return this->getLogMz() < a.getLogMz();
  }

  bool FLASHHelperClasses::LogMzPeak::operator>(const LogMzPeak& a) const
  {
    if (this->getLogMz() == a.getLogMz()) { return this->getIntensity() > a.getIntensity(); }
    return this->getLogMz() > a.getLogMz();
  }

  bool FLASHHelperClasses::LogMzPeak::operator==(const LogMzPeak& a) const
  { return this->getLogMz() == a.getLogMz() && this->getIntensity() == a.getIntensity(); }


  float FLASHHelperClasses::getChargeMass(const bool positive_ioniziation_mode)
  {
    return (float)(positive_ioniziation_mode ? Constants::PROTON_MASS_U : -Constants::PROTON_MASS_U);
  }

  double FLASHHelperClasses::getLogMz(const double mz, const bool positive)
  {
    return std::log(mz - getChargeMass(positive));
  }

  bool FLASHHelperClasses::IsobaricQuantities::empty() const
  {
    return quantities.empty();
  }


#if OPENMS_FLASHDECONV_PEAK_LAYOUT == 17
  namespace
  {
    const Peak1D empty_source_peak;
    struct PeakSourceSpan
    {
      std::uintptr_t begin = 0, end = 0;
      std::uint32_t first_block = 0;
    };
    // The registry owns snapshots until process exit. This deliberately includes
    // all auxiliary storage in peak RSS and keeps detached peak copies valid.
    struct PeakSourceRegistry
    {
      std::mutex mutex;
      std::map<std::uintptr_t, PeakSourceSpan> spans;
      std::vector<std::shared_ptr<const MSSpectrum>> owners;
      std::vector<std::unique_ptr<Peak1D[]>> standalone_blocks;
      std::uint32_t next_block = 1, standalone_block = 0, standalone_used = 65536;
      std::uint64_t retained_points = 0, standalone_records = 0, tls_miss_locks = 0;
    };
    PeakSourceRegistry& peakSources()
    {
      static PeakSourceRegistry sources;
      return sources;
    }
    void checkSourceCapacity(std::uint32_t next, Size count)
    {
      if (count > 65536 - next)
      {
        throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "Indexed peak registry exceeds 65535 source-page capacity",
                                      std::to_string(count));
      }
    }
  } // namespace
  const Peak1D* FLASHHelperClasses::InternalLogMzPeak::source_blocks_[65536] = {&empty_source_peak};

  std::uint32_t FLASHHelperClasses::InternalLogMzPeak::sourceIndex_(const Peak1D& peak)
  {
    thread_local PeakSourceSpan cached;
    const auto address = reinterpret_cast<std::uintptr_t>(&peak);
    auto index = [&]() {
      const auto offset = (address - cached.begin) / sizeof(Peak1D);
      return static_cast<std::uint32_t>(((cached.first_block + offset / 65536) << 16) | (offset & 65535));
    };
    if (address >= cached.begin && address < cached.end) { return index(); }
    auto& registry = peakSources();
    std::lock_guard<std::mutex> lock(registry.mutex);
    ++registry.tls_miss_locks;
    auto it = registry.spans.upper_bound(address);
    if (it != registry.spans.begin())
    {
      --it;
      if (address < it->second.end)
      {
        cached = it->second;
        return index();
      }
    }
    // Standalone/public boundary values have no registered spectrum. Store one
    // immutable record in a bounded block, rather than borrowing stack storage.
    if (registry.standalone_used == 65536)
    {
      checkSourceCapacity(registry.next_block, 1);
      auto block = std::make_unique<Peak1D[]>(65536);
      registry.standalone_blocks.push_back(std::move(block));
      registry.standalone_block = registry.next_block++;
      registry.standalone_used = 0;
      source_blocks_[registry.standalone_block] = registry.standalone_blocks.back().get();
    }
    ++registry.standalone_records;
    const auto offset = registry.standalone_used++;
    registry.standalone_blocks.back()[offset] = peak;
    return (registry.standalone_block << 16) | offset;
  }
#endif

  void FLASHHelperClasses::InternalLogMzPeak::registerSource(const std::shared_ptr<const MSSpectrum>& source)
  {
#if OPENMS_FLASHDECONV_PEAK_LAYOUT == 17
    if (! source || source->empty()) { return; }
    auto& registry = peakSources();
    std::lock_guard<std::mutex> lock(registry.mutex);
    const auto begin = reinterpret_cast<std::uintptr_t>(&(*source)[0]);
    if (registry.spans.contains(begin)) { return; }
    const Size blocks = 1 + (source->size() - 1) / 65536;
    checkSourceCapacity(registry.next_block, blocks);
    registry.owners.push_back(source);
    registry.spans.emplace(begin, PeakSourceSpan {begin, begin + source->size() * sizeof(Peak1D), registry.next_block});
    registry.retained_points += source->size();
    for (Size i = 0; i < blocks; ++i)
    {
      source_blocks_[registry.next_block++] = &(*source)[i * 65536];
    }
#else
    (void)source;
#endif
  }

  int FLASHHelperClasses::InternalLogMzPeak::verifyLayout(std::integral_constant<int, OPENMS_FLASHDECONV_PEAK_LAYOUT>)
  {
    return OPENMS_FLASHDECONV_PEAK_LAYOUT;
  }

  std::array<std::uint64_t, 6> FLASHHelperClasses::InternalLogMzPeak::getSourceStatistics()
  {
#if OPENMS_FLASHDECONV_PEAK_LAYOUT == 17
    auto& registry = peakSources();
    std::lock_guard<std::mutex> lock(registry.mutex);
    return {registry.owners.size(), registry.next_block - 1, registry.retained_points,
            registry.standalone_records, registry.tls_miss_locks, registry.standalone_blocks.size()};
#else
    return {};
#endif
  }

  FLASHHelperClasses::InternalLogMzPeak::InternalLogMzPeak(const Peak1D& peak, bool positive)
  {
#if OPENMS_FLASHDECONV_PEAK_LAYOUT == 17
    source_index_ = sourceIndex_(peak);
#else
    mz_ = peak.getMZ();
    intensity_ = peak.getIntensity();
#endif
#if OPENMS_FLASHDECONV_PEAK_LAYOUT != 16
    log_mz_ = FLASHHelperClasses::getLogMz(peak.getMZ(), positive);
#endif
    charge_flags_ = positive ? 0 : (256 | LOG_NEGATIVE_POLARITY);
    isotope_magnitude_ = 0;
  }

  FLASHHelperClasses::InternalLogMzPeak::InternalLogMzPeak(const LogMzPeak& peak)
  {
    if (! (peak.getMass() <= 0))
    {
      throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "Internal peaks cannot store independent mass overrides",
                                    std::to_string(peak.getMass()));
    }
    if (peak.getLogMz() != -1000 && std::bit_cast<std::uint64_t>(peak.getLogMz()) != std::bit_cast<std::uint64_t>(FLASHHelperClasses::getLogMz(peak.getMZ(), peak.isPositive())))
    {
      throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
                                    "Raw-mz internal peaks require the derived logarithm or default sentinel", std::to_string(peak.getLogMz()));
    }

#if OPENMS_FLASHDECONV_PEAK_LAYOUT == 17
    Peak1D value;
    value.setMZ(peak.getMZ());
    value.setIntensity(peak.getIntensity());
    source_index_ = sourceIndex_(value);
#else
    mz_ = peak.getMZ();
    intensity_ = peak.getIntensity();
#endif
#if OPENMS_FLASHDECONV_PEAK_LAYOUT != 16
    log_mz_ = peak.getLogMz();
#endif
    charge_flags_ = static_cast<std::int16_t>(peak.isPositive() ? 0 : (256 | LOG_NEGATIVE_POLARITY));
    if (peak.getLogMz() == -1000) { charge_flags_ |= DEFAULT_LOG; }
    setAbsCharge(peak.getAbsCharge());
    setIsotopeIndex(peak.getIsotopeIndex());
  }

  void FLASHHelperClasses::InternalLogMzPeak::setAbsCharge(int value)
  {
    if (value < 0 || value > 200)
    {
      throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "Internal peak charge must be in [0, 200]", std::to_string(value));
    }
    charge_flags_ = static_cast<std::int16_t>((charge_flags_ & ~255) | value);
  }

  void FLASHHelperClasses::InternalLogMzPeak::setIsotopeIndex(int value)
  {
    if (value < -65535 || value > 65535)
    {
      throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "Internal peak isotope must be in [-65535, 65535]",
                                    std::to_string(value));
    }
    isotope_magnitude_ = static_cast<std::uint16_t>(value < 0 ? -value : value);
    charge_flags_ = static_cast<std::int16_t>(value < 0 ? charge_flags_ | 512 : charge_flags_ & ~512);
  }

  double FLASHHelperClasses::InternalLogMzPeak::getUnchargedMass() const
  {
    if (getAbsCharge() == 0) { return .0; }
    return (getMZ() - FLASHHelperClasses::getChargeMass(isPositive())) * (float)getAbsCharge();
  }

  bool FLASHHelperClasses::InternalLogMzPeak::operator<(const InternalLogMzPeak& other) const
  {
    const auto a = getLogMz(), b = other.getLogMz();
    return a == b ? getIntensity() < other.getIntensity() : a < b;
  }
  bool FLASHHelperClasses::InternalLogMzPeak::operator>(const InternalLogMzPeak& other) const
  {
    const auto a = getLogMz(), b = other.getLogMz();
    return a == b ? getIntensity() > other.getIntensity() : a > b;
  }
  bool FLASHHelperClasses::InternalLogMzPeak::operator==(const InternalLogMzPeak& other) const
  { return getLogMz() == other.getLogMz() && getIntensity() == other.getIntensity(); }

} // namespace OpenMS