// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// --------------------------------------------------------------------------
// $Maintainer: Kyowon Jeong, Jihyung Kim $
// $Authors: Kyowon Jeong, Jihyung Kim $
// --------------------------------------------------------------------------

#include <OpenMS/ANALYSIS/TOPDOWN/PeakGroup.h>
#include <OpenMS/ANALYSIS/TOPDOWN/PeakGroupScoring.h>
#include <OpenMS/ANALYSIS/TOPDOWN/SpectralDeconvolution.h>
#include <OpenMS/CONCEPT/Exception.h>
#include <algorithm>
#include <functional>
#include <array>
#include <limits>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <cstdlib>

namespace OpenMS
{
  namespace
  {
    /**
      round() and floor() of the quotient a / b, given inv_b = 1 / b, without the division. The product a * inv_b is
      within |a / b| * 6e-16 of the correctly rounded quotient, so whenever its fractional part is more than 1e-7 away
      from 0, 0.5 and 1 both functions give the same integers as for fl(a / b). Returns false otherwise (and for large
      quotients); the caller then divides.
    */
    inline bool roundedQuotient(double a, double inv_b, int& rounded, int& floored)
    {
      const double q = a * inv_b;
      if (! (std::fabs(q) < 1e8)) { return false; }
      const long long t = (long long)q;               // toward zero
      const long long f = t - (long long)(q < (double)t); // floor
      const double frac = q - (double)f;              // in [0, 1)
      if (! (frac > 1e-7 && frac < 1 - 1e-7 && std::fabs(frac - 0.5) > 1e-7)) { return false; }
      floored = (int)f;
      rounded = (int)(f + (long long)(frac > 0.5));
      return true;
    }
  } // namespace

  PeakGroup::PeakGroup(const int min_abs_charge, const int max_abs_charge, const bool is_positive):
      min_abs_charge_(min_abs_charge),
      max_abs_charge_(max_abs_charge),
      is_positive_(is_positive)
  {
  }

  bool PeakGroup::operator<(const PeakGroup& a) const
  {
    if (this->monoisotopic_mass_ == a.monoisotopic_mass_) { return this->intensity_ < a.intensity_; }
    return this->monoisotopic_mass_ < a.monoisotopic_mass_;
  }

  bool PeakGroup::operator>(const PeakGroup& a) const
  {
    if (this->monoisotopic_mass_ == a.monoisotopic_mass_) { return this->intensity_ > a.intensity_; }
    return this->monoisotopic_mass_ > a.monoisotopic_mass_;
  }

  bool PeakGroup::operator==(const PeakGroup& a) const
  {
    return this->monoisotopic_mass_ == a.monoisotopic_mass_ && this->intensity_ == a.intensity_;
  }

  std::vector<float> PeakGroup::getMassErrors(bool ppm) const
  {
    std::vector<float> errors;
    int i = 0;
    float i_cntr = 0;
    float i_error = .0f;
    for (const auto& p : *this)
    {
      if (i != p.getIsotopeIndex())
      {
        if (i_cntr > 0)
        {
          errors.push_back(i_error / i_cntr);
        }
        i = p.getIsotopeIndex();
        i_cntr = 0;
        i_error = 0;
      }
      i_cntr ++;
      i_error += ppm ? getPPMError_(p) : getDaError_(p);
    }
    if (i_cntr > 0)
    {
      errors.push_back(i_error / i_cntr);
    }
    return errors;
  }


  void PeakGroup::updateAvgMassError_()
  {
    avg_ppm_error_ = averageAbsMassError_(true);
    avg_da_error_ = averageAbsMassError_(false);
  }

  float PeakGroup::averageAbsMassError_(bool ppm) const
  {
    float sum = .0f;
    Size count = 0;
    int i = 0;
    float i_cntr = 0;
    float i_error = .0f;
    for (const auto& p : *this)
    {
      if (i != p.getIsotopeIndex())
      {
        if (i_cntr > 0)
        {
          sum += std::abs(i_error / i_cntr);
          ++count;
        }
        i = p.getIsotopeIndex();
        i_cntr = 0;
        i_error = 0;
      }
      i_cntr++;
      i_error += ppm ? getPPMError_(p) : getDaError_(p);
    }
    if (i_cntr > 0)
    {
      sum += std::abs(i_error / i_cntr);
      ++count;
    }
    return sum / (float)count;
  }

  float PeakGroup::getPPMError_(const LogMzPeak& p) const
  {
    auto mass = (float)(monoisotopic_mass_ + p.getIsotopeIndex() * iso_da_distance_);
    return (float)((mass / (float)p.getAbsCharge() + FLASHHelperClasses::getChargeMass(p.isPositive()) - p.getMZ()) / p.getMZ() * 1e6);
  }

  float PeakGroup::getDaError_(const LogMzPeak& p) const
  {
    auto mass = (float)(monoisotopic_mass_ + p.getIsotopeIndex() * iso_da_distance_);
    return (float)((mass - p.getUnchargedMass()));
  }

  int PeakGroup::getMinNegativeIsotopeIndex() const
  {
    return min_negative_isotope_index_;
  }

  void PeakGroup::updatePerChargeCos_(const FLASHHelperClasses::PrecalculatedAveragine& avg, double tol)
  {
    const auto& iso_dist = avg.getReference_(monoisotopic_mass_);
    thread_local std::vector<float> current_per_isotope_intensities; // per-worker scratch, refilled by getPerIsotopeIntensities_
    current_per_isotope_intensities.assign(getIsotopeIntensities().size(), .0f);

    if (min_abs_charge_ == max_abs_charge_) setChargeIsotopeCosine(min_abs_charge_, getIsotopeCosine());
    else
    {
      for (int abs_charge = min_abs_charge_; abs_charge <= max_abs_charge_; abs_charge++)
      {
        int min_isotope_index, max_isotope_index;
        getPerIsotopeIntensities_(current_per_isotope_intensities, min_isotope_index, max_isotope_index, abs_charge, 0, tol);
        float cos_score
          = SpectralDeconvolution::getCosine(current_per_isotope_intensities, min_isotope_index, max_isotope_index, iso_dist, 0,
                                             SpectralDeconvolution::min_iso_size);
        setChargeIsotopeCosine(abs_charge, cos_score); //
      }
    }
  }

  int PeakGroup::updateQscore(const std::vector<LogMzPeak>& noisy_peaks,
                              const FLASHHelperClasses::PrecalculatedAveragine& avg,
                              const double min_cos,
                              const double tol,
                              const bool is_low_charge,
                              const std::vector<double>& excluded_masses,
                              const bool is_last)
  {
    qscore_ = 0;

    if (empty()) { return 0; }
    updatePerChargeInformation_(noisy_peaks, tol, is_last);
    updateChargeRange_();
    updateChargeFitScoreAndChargeIntensities_(is_low_charge);
    if (charge_score_ < .7f) //
    {
      return 0;
    }
    updateMonoMassAndIsotopeIntensities(tol); //
    if (per_isotope_int_.empty() || max_abs_charge_ < min_abs_charge_) { return 0; }
    int h_offset;
    int window_width = is_last ? 0 : -1;

    isotope_cosine_score_ = SpectralDeconvolution::getIsotopeCosineAndIsoOffset(
      monoisotopic_mass_, per_isotope_int_, h_offset, avg,
      -min_negative_isotope_index_, // change if to select cosine calculation and if to get second best hits
      window_width, excluded_masses);
    if (!is_last && h_offset != 0) return h_offset;

    if (isotope_cosine_score_ < min_cos) { return 0; }
    updatePerChargeCos_(avg, tol);
    updateAvgMassError_();
    updateSNR_((float)avg.getSNRMultiplicationFactor(monoisotopic_mass_));
    //if (target_decoy_type_ == PeakGroup::signal_decoy) isotope_cosine_score_ = std::min(1.0f, isotope_cosine_score_ + .02f); // the smaller

    for (int abs_charge = min_abs_charge_; abs_charge <= max_abs_charge_; abs_charge++)
    {
      if (getChargeSNR(abs_charge) > getChargeSNR(max_snr_abs_charge_)) { max_snr_abs_charge_ = abs_charge; }
    }

    qscore_ = PeakGroupScoring::getQscore(this);
    return h_offset;
  }

  float PeakGroup::getNoisePeakPower_(const LogMzPeak* noisy_begin, const LogMzPeak* noisy_end, const LogMzPeak* signal_begin,
                                      const LogMzPeak* signal_end, const int z, const double tol) const
  {
    if (noisy_begin == noisy_end) return 0;
    const Size max_noisy_peak_number
      = z == 0 ? std::min(200, 40 * (max_abs_charge_ - min_abs_charge_ + 1)) : 40; // too many noise peaks will slow down the process
    constexpr Size bin_number_margin = 8;
    constexpr Size max_bin_number = bin_number_margin + 12; // 12 bin + 8 extra bin
    float threshold = -1;

    // the ranges are already restricted to charge z (or to all charges for z == 0)
    const Size noise_peak_count = noisy_end - noisy_begin;
    // get intensity threshold: the (max_noisy_peak_number + 1)-th largest intensity, as a full descending sort would give
    if (noise_peak_count > max_noisy_peak_number)
    {
      thread_local std::vector<float> intensities;
      intensities.clear();
      intensities.reserve(noise_peak_count);
      for (const LogMzPeak* p = noisy_begin; p != noisy_end; ++p) { intensities.push_back(p->getIntensity()); }
      std::nth_element(intensities.begin(), intensities.begin() + max_noisy_peak_number, intensities.end(), std::greater<float>());
      threshold = intensities[max_noisy_peak_number];
    }

    // Peaks above the threshold as mass-sorted arrays (mass, intensity, is signal). Within one charge both ranges are
    // already sorted by mass, so they are merged; otherwise (z == 0, or equal masses whose order std::sort would decide)
    // the former sort is used.
    struct MassIntensity
    {
      double mass;
      float intensity;
    };
    thread_local std::vector<MassIntensity> noisy_kept, signal_kept;
    noisy_kept.clear();
    signal_kept.clear();
    for (const LogMzPeak* p = noisy_begin; p != noisy_end; ++p)
    {
      if (p->getIntensity() < threshold) continue;
      noisy_kept.push_back({p->getUnchargedMass(), p->getIntensity()});
    }
    if (noisy_kept.empty()) return 0;
    for (const LogMzPeak* p = signal_begin; p != signal_end; ++p)
    {
      if (p->getIntensity() < threshold) continue;
      signal_kept.push_back({p->getUnchargedMass(), p->getIntensity()});
    }
    thread_local std::vector<double> mass;
    thread_local std::vector<float> intensity;
    thread_local std::vector<char> is_signal;
    mass.clear();
    intensity.clear();
    is_signal.clear();
    const auto strictly_increasing = [](const std::vector<MassIntensity>& v) {
      for (Size i = 1; i < v.size(); ++i)
      {
        if (! (v[i - 1].mass < v[i].mass)) return false;
      }
      return true;
    };
    bool merged = strictly_increasing(noisy_kept) && strictly_increasing(signal_kept);
    for (Size a = 0, b = 0; merged && (a < noisy_kept.size() || b < signal_kept.size());)
    {
      if (b == signal_kept.size() || (a < noisy_kept.size() && noisy_kept[a].mass < signal_kept[b].mass))
      {
        mass.push_back(noisy_kept[a].mass);
        intensity.push_back(noisy_kept[a].intensity);
        is_signal.push_back(0);
        ++a;
      }
      else if (a == noisy_kept.size() || signal_kept[b].mass < noisy_kept[a].mass)
      {
        mass.push_back(signal_kept[b].mass);
        intensity.push_back(signal_kept[b].intensity);
        is_signal.push_back(1);
        ++b;
      }
      else { merged = false; }
    }
    if (! merged)
    {
      thread_local std::vector<std::pair<Peak1D, bool>> all_peaks; // peak + is signal?
      all_peaks.clear();
      for (const auto& p : noisy_kept) { all_peaks.emplace_back(Peak1D(p.mass, p.intensity), false); }
      for (const auto& p : signal_kept) { all_peaks.emplace_back(Peak1D(p.mass, p.intensity), true); }
      std::sort(all_peaks.begin(), all_peaks.end(),
                [](std::pair<Peak1D, bool>& left, std::pair<Peak1D, bool>& right) { return left.first.getMZ() < right.first.getMZ(); });
      mass.clear();
      intensity.clear();
      is_signal.clear();
      for (const auto& [p, s] : all_peaks)
      {
        mass.push_back(p.getMZ());
        intensity.push_back(p.getIntensity());
        is_signal.push_back(s);
      }
    }

    const Size peak_count = mass.size();
    if (peak_count >= std::numeric_limits<std::uint32_t>::max() / (max_bin_number + 1))
    {
      throw Exception::InvalidSize(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, peak_count, "Noise-peak graph exceeds the supported allocation size");
    }
    float charge_noise_pwr = 0;
    // successor of peak i in bin k at [k * peak_count + i] (0 = none); row max_bin_number is a dummy target for
    // updates that the reference would skip
    thread_local std::vector<std::uint32_t> per_bin_edges;
    per_bin_edges.assign((max_bin_number + 1) * peak_count, 0);
    std::array<int, max_bin_number + 1> per_bin_start_index;
    per_bin_start_index.fill(-2); // -2 means bin is empty. -1 means bin is used. zero or positive = edge index
    // (sum, bin) pairs; equal sums keep the last bin like the former std::map, visited by descending sum
    std::array<std::pair<float, Size>, max_bin_number> max_intensity_sum_to_bin;
    Size max_intensity_sum_count = 0;
    const std::array<double, 3> div_factors {1.0, 2.0, 3.0}; // allow two skips for each bin
    const std::array<double, 3> bins_per_divisor {(max_bin_number - bin_number_margin) / 1.0, (max_bin_number - bin_number_margin) / 2.0,
                                                  (max_bin_number - bin_number_margin) / 3.0};

    // The cutoff needs monotone, finite distances and defined legacy Size casts.
    // Unsupported spacing/mass domains retain the original pair traversal.
    bool monotone_cutoff = std::isfinite(iso_da_distance_) && iso_da_distance_ > 0
                           && std::all_of(mass.begin(), mass.end(), [](double m) { return std::isfinite(m); });
    if (monotone_cutoff)
    {
      const double max_normalized_dist = (mass.back() - mass.front()) / iso_da_distance_;
      const double max_distance = max_normalized_dist / div_factors[0] * (max_bin_number - bin_number_margin);
      monotone_cutoff = std::isfinite(max_distance) && max_distance >= 0 && round(max_distance) < (double)std::numeric_limits<Size>::max();
    }
    // first collect all possible edges. An edge means mass difference between two peaks. The per-bin update below is
    // done with bit masks instead of branches (its outcome is data-dependent and mispredicts); pairs and divisors the
    // former code skipped update the dummy row. Arithmetic and update order are unchanged.
    const auto to_bits = [](double x) {
      std::uint64_t u;
      std::memcpy(&u, &x, sizeof(u));
      return u;
    };
    const auto from_bits = [](std::uint64_t u) {
      double x;
      std::memcpy(&x, &u, sizeof(x));
      return x;
    };
    for (Size i = 0; i < peak_count; i++)
    {
      const double p1_mass = mass[i];
      const std::uint64_t p1_signal = (std::uint64_t)is_signal[i];
      std::array<double, max_bin_number + 1> per_bin_error;
      per_bin_error.fill(-1.0);
      std::uint32_t* edges_of_i = per_bin_edges.data() + i;
      for (Size j = i + 1; j < peak_count; j++)
      {
        const double normalized_dist = (mass[j] - p1_mass) / iso_da_distance_;
        // == (Size)round(distance) for the non-negative distances of a mass-sorted list, without the libm call
        const double distance1 = normalized_dist * bins_per_divisor[0];
        const Size bin1_floor = (Size)distance1;
        if (bin1_floor + (Size)(distance1 - (double)bin1_floor >= 0.5) >= max_bin_number)
        {
          if (monotone_cutoff) { break; }
          continue;
        }
        // if both are signals, and they are different from each other by more than .75 isotope distance, do not
        // connect. Otherwise, connect as they may a part of consecutive other noisy peaks.
        const std::uint64_t keep = 1u ^ (p1_signal & (std::uint64_t)is_signal[j] & (std::uint64_t)(normalized_dist >= .75));
        for (Size di = 0; di < div_factors.size(); di++)
        {
          const double distance = normalized_dist * bins_per_divisor[di];
          const Size bin_floor = (Size)distance;
          const Size bin = bin_floor + (Size)(distance - (double)bin_floor >= 0.5);
          const std::uint64_t valid = keep & (std::uint64_t)(bin != 0);
          const Size slot = max_bin_number ^ ((max_bin_number ^ bin) & (Size)(0 - valid));
          per_bin_start_index[slot] = -1;
          const double current_error = div_factors[di] * max_bin_number + std::abs((double)bin - distance); // larger when d gets larger
          const double previous_error = per_bin_error[slot];
          const std::uint64_t take = valid & (std::uint64_t)(! ((previous_error >= 0) & (previous_error < current_error)));
          const std::uint64_t mask = 0 - take;
          std::uint32_t& edge = edges_of_i[slot * peak_count];
          edge ^= (edge ^ (std::uint32_t)j) & (std::uint32_t)mask;
          per_bin_error[slot] = from_bits(to_bits(previous_error) ^ ((to_bits(previous_error) ^ to_bits(current_error)) & mask));
        }
      }
    }

    // then from each bin find the highest intensity path consisting of the same mass differences.
    thread_local std::vector<float> chain_sum;
    chain_sum.resize(peak_count);
    for (Size k = 0; k < max_bin_number; k++)
    {
      if (per_bin_start_index[k] == -2) { continue; }
      const std::uint32_t* edges = per_bin_edges.data() + k * peak_count;
      // Path intensity from each peak along its successor chain, computed once from the end (successors have larger
      // indices). A chain without a successor ends with peak 0, as the former walk did; chain_sum[0] holds that tail
      // until peak 0's own sum is computed. Summation order differs from a left-to-right walk (float reassociation).
      chain_sum[0] = intensity[0];
      for (Size i = peak_count - 1; i > 0; --i) { chain_sum[i] = intensity[i] + chain_sum[edges[i]]; }
      chain_sum[0] = intensity[0] + chain_sum[edges[0]];
      float max_sum_intensity = 0;
      int max_start = per_bin_start_index[k];
      for (Size i = 0; i < peak_count; i++)
      {
        if (edges[i] == 0) { break; }
        const bool better = max_sum_intensity < chain_sum[i]; // at least two edges should be there.
        max_sum_intensity = better ? chain_sum[i] : max_sum_intensity;
        max_start = better ? (int)i : max_start;
      }
      per_bin_start_index[k] = max_start;
      // how to deal with profile peaks?
      bool replaced = false;
      for (Size m = 0; m < max_intensity_sum_count; ++m)
      {
        if (max_intensity_sum_to_bin[m].first == max_sum_intensity)
        {
          max_intensity_sum_to_bin[m].second = k;
          replaced = true;
          break;
        }
      }
      if (! replaced) { max_intensity_sum_to_bin[max_intensity_sum_count++] = {max_sum_intensity, k}; }
    }

    thread_local std::vector<char> unused;
    unused.assign(peak_count, 1);
    std::sort(max_intensity_sum_to_bin.begin(), max_intensity_sum_to_bin.begin() + max_intensity_sum_count,
              [](const auto& l, const auto& r) { return l.first > r.first; });

    // Now from the highest intensity path to the lowest, sum up intensities excluding already used peaks or signal peaks.
    for (auto it = max_intensity_sum_to_bin.begin(); it != max_intensity_sum_to_bin.begin() + max_intensity_sum_count; ++it)
    {
      Size bin = it->second;
      int index = per_bin_start_index[bin];
      if (index < 0) { continue; }

      const std::uint32_t* edges = per_bin_edges.data() + bin * peak_count;
      const double ori_mass = mass[index];
      const int ori_index = index;
      float sum_intensity = .0;

      while (index < (int)peak_count)
      {
        if (mass[index] - ori_mass > tol / 2.0 * mass[index]) break;
        Size j = edges[index];
        if (j == 0) { break; }
        if (unused[index])
        {
          sum_intensity += intensity[index];
          unused[index] = false;
        }
        else { break; }
        for (; j < peak_count; j = edges[j])
        {
          if (j == 0) { break; }
          if (unused[j])
          {
            sum_intensity += intensity[j];
            unused[j] = false;
          }
          else
            break;
        }
        index++;
      }

      index = ori_index - 1;
      while (index >= 0)
      {
        if (ori_mass - mass[index] > tol / 2.0 * ori_mass) break;
        Size j = edges[index];
        if (j == 0) { break; }
        if (unused[index])
        {
          sum_intensity += intensity[index];
          unused[index] = false;
        }
        else { break; }
        for (; j < peak_count; j = edges[j])
        {
          if (j == 0) { break; }
          if (unused[j])
          {
            sum_intensity += intensity[j];
            unused[j] = false;
          }
          else
            break;
        }
        index--;
      }

      charge_noise_pwr += sum_intensity * sum_intensity;
    }

    // if still peaks are remaining, add their individual power.
    double prev_mass = .0;
    float tmp_int_sum = 0;
    for (Size index = 0; index < peak_count; ++index)
    {
      if (! unused[index] || is_signal[index]) { continue; }
      if (mass[index] - prev_mass > mass[index] * tol)
      {
        charge_noise_pwr += tmp_int_sum * tmp_int_sum;
        prev_mass = mass[index];
        tmp_int_sum = 0;
      }
      tmp_int_sum += intensity[index];
    }
    charge_noise_pwr += tmp_int_sum * tmp_int_sum;

    return charge_noise_pwr;
  }

  void PeakGroup::updatePerChargeInformation_(const std::vector<LogMzPeak>& noisy_peaks, const double tol, const bool is_last)
  {
    per_charge_sum_signal_squared_.assign(1 + max_abs_charge_, .0f);
    per_charge_int_.assign(1 + max_abs_charge_, .0f);
    int max_iso = 0;

    // calculate per charge intensity, and per charge sum of signal intensity squared
    for (const auto& p : logMzpeaks_)
    {
      per_charge_int_[p.getAbsCharge()] += p.getIntensity();
      max_iso = std::max(max_iso, p.getIsotopeIndex());
    }
    // per-worker scratch replaces a fresh (charge x isotope) matrix per call; row-major, same summation order
    thread_local std::vector<float> per_charge_isotope_int;
    const Size iso_cols = 1 + (Size)max_iso;
    per_charge_isotope_int.assign((1 + (Size)max_abs_charge_) * iso_cols, .0f);
    for (const auto& p : logMzpeaks_)
    {
      per_charge_isotope_int[p.getAbsCharge() * iso_cols + p.getIsotopeIndex()] += p.getIntensity();
    }

    for (int z = min_abs_charge_; z <= max_abs_charge_; z++)
    {
      for (Size i = 0; i < iso_cols; i++)
      {
        float v = per_charge_isotope_int[z * iso_cols + i];
        per_charge_sum_signal_squared_[0] += v * v;
        per_charge_sum_signal_squared_[z] += v * v;
      }
    }

    // for each charge calculate signal and noise power
    per_charge_noise_pwr_.assign(1 + max_abs_charge_, .0f);

    if (is_last)
    {
      // Group noisy and signal peaks by charge once (stable, so each group keeps the original order) instead of
      // rescanning both lists for every charge.
      thread_local std::vector<LogMzPeak> noisy_by_charge, signal_by_charge; // per-worker scratch
      thread_local std::vector<Size> noisy_offset, signal_offset;
      const auto group_by_charge = [&](const std::vector<LogMzPeak>& peaks, std::vector<LogMzPeak>& grouped, std::vector<Size>& offset) {
        offset.assign(max_abs_charge_ + 2, 0);
        for (const auto& p : peaks)
        {
          if (p.getAbsCharge() >= min_abs_charge_ && p.getAbsCharge() <= max_abs_charge_) offset[p.getAbsCharge() + 1]++;
        }
        for (int z = 1; z <= max_abs_charge_ + 1; z++) offset[z] += offset[z - 1];
        grouped.resize(offset[max_abs_charge_ + 1]);
        thread_local std::vector<Size> fill;
        fill.assign(offset.begin(), offset.end());
        for (const auto& p : peaks)
        {
          if (p.getAbsCharge() >= min_abs_charge_ && p.getAbsCharge() <= max_abs_charge_) grouped[fill[p.getAbsCharge()]++] = p;
        }
      };
      group_by_charge(noisy_peaks, noisy_by_charge, noisy_offset);
      group_by_charge(logMzpeaks_, signal_by_charge, signal_offset);
      for (int z = min_abs_charge_; z <= max_abs_charge_; z++)
      {
        per_charge_noise_pwr_[z] = getNoisePeakPower_(noisy_by_charge.data() + noisy_offset[z], noisy_by_charge.data() + noisy_offset[z + 1],
                                                      signal_by_charge.data() + signal_offset[z], signal_by_charge.data() + signal_offset[z + 1], z, tol);
      }
      per_charge_noise_pwr_[0] = getNoisePeakPower_(noisy_peaks.data(), noisy_peaks.data() + noisy_peaks.size(), logMzpeaks_.data(),
                                                    logMzpeaks_.data() + logMzpeaks_.size(), 0, tol);
    }
    else
    {
      for (const auto& p : noisy_peaks)
      {
        float pwr = p.getIntensity() * p.getIntensity();
        if (p.getAbsCharge() < min_abs_charge_ || p.getAbsCharge() > max_abs_charge_) continue;
        per_charge_noise_pwr_[0] += pwr;
        per_charge_noise_pwr_[p.getAbsCharge()] += pwr;
      }
    }
  }

  void PeakGroup::updateChargeRange_()
  {
    int max_sig_charge = 0;
    double max_sig = 0;

    // first, find the maximum snr charge.
    for (int z = min_abs_charge_; z <= max_abs_charge_; z++)
    {
      double tmp_snr = per_charge_int_[z] * per_charge_int_[z] / (1 + per_charge_noise_pwr_[z]);
      if (max_sig < tmp_snr)
      {
        max_sig = tmp_snr;
        max_sig_charge = z;
      }
    }

    // determine the final charge ranges based on per charge power.
    // If more than two consecutive charges do not contain any signal peak, the charge range stops at that charge.

    int new_max_abs_charge;
    int new_min_abs_charge;

    new_max_abs_charge = new_min_abs_charge = max_sig_charge;
    double threshold = std::min(max_sig / 10, 1.0);
    for (int z = max_sig_charge; z <= max_abs_charge_; z++)
    {
      float per_charge_signal_power = per_charge_int_[z] * per_charge_int_[z];
      if ((per_charge_signal_power / (1 + per_charge_noise_pwr_[z])) < threshold) { break; }
      new_max_abs_charge = z;
    }

    for (int z = max_sig_charge; z >= min_abs_charge_; z--)
    {
      float per_charge_signal_power = per_charge_int_[z] * per_charge_int_[z];
      if ((per_charge_signal_power / (1 + per_charge_noise_pwr_[z])) < threshold) { break; }
      new_min_abs_charge = z;
    }

    // if the updated charge range is different from the original one, signal and noisy peaks are again updated
    if (max_abs_charge_ != new_max_abs_charge || min_abs_charge_ != new_min_abs_charge)
    {
      // now only take the signal and noise peaks within the new charge range (in place, order kept).
      logMzpeaks_.erase(std::remove_if(logMzpeaks_.begin(), logMzpeaks_.end(),
                                       [&](const LogMzPeak& p) { return p.getAbsCharge() < new_min_abs_charge || p.getAbsCharge() > new_max_abs_charge; }),
                        logMzpeaks_.end());
      max_abs_charge_ = new_max_abs_charge;
      min_abs_charge_ = new_min_abs_charge;
    }
    if (min_abs_charge_ > max_abs_charge_) { clear_(); }
    else { sort(); }
  }

  std::vector<FLASHHelperClasses::LogMzPeak> PeakGroup::recruitAllPeaksInSpectrum(const MSSpectrum& spec,
                                                                                  const double tol,
                                                                                  const FLASHHelperClasses::PrecalculatedAveragine& avg,
                                                                                  double mono_mass,
                                                                                  bool renew_signal_peaks)
  {
    std::vector<LogMzPeak> noisy_peaks;
    recruitAllPeaksInSpectrum(spec, tol, avg, mono_mass, noisy_peaks, renew_signal_peaks);
    return noisy_peaks;
  }

  void PeakGroup::recruitAllPeaksInSpectrum(const MSSpectrum& spec,
                                            const double tol,
                                            const FLASHHelperClasses::PrecalculatedAveragine& avg,
                                            double mono_mass,
                                            std::vector<LogMzPeak>& noisy_peaks,
                                            bool renew_signal_peaks,
                                            const double* log_mz)
  {
    const double mul_tol = .8; // not all peaks within tolerance are considered as signal peaks.
    noisy_peaks.clear();
    // Keep this group's own capacity (bounded by its real peak count) instead of freeing it and
    // reserving a worst-case size on every renewal.
    if (renew_signal_peaks) logMzpeaks_.clear();

    if (mono_mass < 0) { return; }

    if (max_abs_charge_ - min_abs_charge_ < max_abs_charge_ / 20) // if charge range is too small ...
    {
      return;
    }

    monoisotopic_mass_ = mono_mass;

    // int iso_margin = 3; // how many isotopes do we want to scan before the monoisotopic mass?
    int max_isotope = (int)avg.getLastIndex(mono_mass);
    int min_isotope = (int)(avg.getApexIndex(mono_mass) - avg.getLeftCountFromApex(mono_mass) + min_negative_isotope_index_);
    int max_signal_isotope = 0;
    min_isotope = std::max(min_negative_isotope_index_, min_isotope);

    negative_iso_peaks_.clear();


    // scan from the largest to the smallest charges and recruit the raw peaks for this monoisotopic_mass
    for (int c = max_abs_charge_; c >= min_abs_charge_; c--)
    {
      if (c <= 0) { break; }
      double cmz = (mono_mass) / c + FLASHHelperClasses::getChargeMass(is_positive_);
      double left_mz = (mono_mass - (1 - min_negative_isotope_index_) * iso_da_distance_) / c + FLASHHelperClasses::getChargeMass(is_positive_);
      Size index = spec.findNearest(left_mz * (1 - tol * mul_tol));
      double iso_delta = iso_da_distance_ / c;
      const double inv_iso_delta = 1.0 / iso_delta;

      for (; index < spec.size(); index++)
      {
        float pint = spec[index].getIntensity();
        if (pint <= 0) { continue; }
        double pmz = spec[index].getMZ();
        int iso_index, iso_floor;
        if (! roundedQuotient(pmz - cmz, inv_iso_delta, iso_index, iso_floor))
        {
          iso_index = (int)round((pmz - cmz) / iso_delta);
          iso_floor = (int)floor((pmz - cmz) / iso_delta);
        }
        if (iso_index > max_isotope) { break; }

        if (iso_index < min_isotope) { continue; }

        if (std::abs(pmz - cmz - iso_index * iso_delta) <= pmz * tol * mul_tol)
        {
          if (iso_index >= 0) { max_signal_isotope = std::max(max_signal_isotope, iso_index); }
          if (iso_index >= 0 && ! renew_signal_peaks) { continue; }
          auto& target = iso_index < 0 ? negative_iso_peaks_ : logMzpeaks_;
          auto& p = log_mz != nullptr ? target.emplace_back(spec[index], is_positive_, log_mz[index]) : target.emplace_back(spec[index], is_positive_);
          p.setIsotopeIndex(iso_index);
          p.setAbsCharge(c);
        }
        else if (iso_index >= 0)
        {
          int noise_iso_index = iso_floor;
          auto& p = log_mz != nullptr ? noisy_peaks.emplace_back(spec[index], is_positive_, log_mz[index]) : noisy_peaks.emplace_back(spec[index], is_positive_);
          p.setIsotopeIndex(noise_iso_index);
          p.setAbsCharge(c);
        }
      }

      if (index >= spec.size()) { break; }
    }

    noisy_peaks.erase(std::remove_if(noisy_peaks.begin(), noisy_peaks.end(), [max_signal_isotope](const LogMzPeak& p) { return p.getIsotopeIndex() > max_signal_isotope; }),
                      noisy_peaks.end());
  }

  std::vector<FLASHHelperClasses::LogMzPeak> PeakGroup::getNoisyPeaks(const MSSpectrum& spec,
                                                                       const double tol,
                                                                       const FLASHHelperClasses::PrecalculatedAveragine& avg) const
  {
    // Const version of recruitAllPeaksInSpectrum for use in output functions
    // Uses existing member values instead of modifying them
    const double mul_tol = 0.8;
    std::vector<LogMzPeak> noisy_peaks;

    const double mono_mass = monoisotopic_mass_;
    if (mono_mass < 0) { return noisy_peaks; }

    if (max_abs_charge_ - min_abs_charge_ < max_abs_charge_ / 20)
    {
      return noisy_peaks;
    }

    int max_isotope = static_cast<int>(avg.getLastIndex(mono_mass));
    int min_isotope = static_cast<int>(avg.getApexIndex(mono_mass) - avg.getLeftCountFromApex(mono_mass) + min_negative_isotope_index_);
    min_isotope = std::max(min_negative_isotope_index_, min_isotope);

    // Find max signal isotope from existing peaks (const access)
    int max_signal_isotope = 0;
    for (const auto& p : logMzpeaks_)
    {
      if (p.getIsotopeIndex() >= 0) { max_signal_isotope = std::max(max_signal_isotope, p.getIsotopeIndex()); }
    }

    noisy_peaks.reserve(max_isotope * (max_abs_charge_ - min_abs_charge_ + 1) * 2);

    for (int c = max_abs_charge_; c >= min_abs_charge_; c--)
    {
      if (c <= 0) { break; }
      double cmz = mono_mass / c + FLASHHelperClasses::getChargeMass(is_positive_);
      double left_mz = (mono_mass - (1 - min_negative_isotope_index_) * iso_da_distance_) / c + FLASHHelperClasses::getChargeMass(is_positive_);
      Size index = spec.findNearest(left_mz * (1 - tol * mul_tol));
      double iso_delta = iso_da_distance_ / c;
      const double inv_iso_delta = 1.0 / iso_delta;

      for (; index < spec.size(); index++)
      {
        float pint = spec[index].getIntensity();
        if (pint <= 0) { continue; }
        double pmz = spec[index].getMZ();
        int iso_index, iso_floor;
        if (! roundedQuotient(pmz - cmz, inv_iso_delta, iso_index, iso_floor))
        {
          iso_index = static_cast<int>(round((pmz - cmz) / iso_delta));
          iso_floor = static_cast<int>(floor((pmz - cmz) / iso_delta));
        }
        if (iso_index > max_isotope) { break; }
        if (iso_index < min_isotope) { continue; }

        // Only collect noisy peaks (those that don't match the isotope pattern tolerance)
        if (!(std::abs(pmz - cmz - iso_index * iso_delta) <= pmz * tol * mul_tol))
        {
          if (iso_index >= 0)
          {
            auto p = LogMzPeak(spec[index], is_positive_);
            int noise_iso_index = iso_floor;
            p.setIsotopeIndex(noise_iso_index);
            p.setAbsCharge(c);
            noisy_peaks.push_back(p);
          }
        }
      }

      if (index >= spec.size()) { break; }
    }

    // Filter noisy peaks to only include those within signal isotope range
    std::vector<LogMzPeak> filtered_noisy_peaks;
    filtered_noisy_peaks.reserve(noisy_peaks.size());
    for (const auto& p : noisy_peaks)
    {
      if (p.getIsotopeIndex() <= max_signal_isotope) { filtered_noisy_peaks.push_back(p); }
    }

    return filtered_noisy_peaks;
  }

  void PeakGroup::updateChargeFitScoreAndChargeIntensities_(bool is_low_charge)
  {
    if (max_abs_charge_ == min_abs_charge_)
    {
      charge_score_ = 1;
      return;
    }
    float max_per_charge_intensity = .0;
    float summed_intensity = .0;
    int max_index = -1;
    int first_index = -1;
    int last_index = -1;

    for (int c = min_abs_charge_; c <= max_abs_charge_; c++)
    {
      summed_intensity += per_charge_int_[c];
      if (per_charge_int_[c] > 0)
      {
        if (first_index < 0) { first_index = c; }
        last_index = c;
      }

      if (max_per_charge_intensity > per_charge_int_[c]) { continue; }
      max_per_charge_intensity = per_charge_int_[c];
      max_index = c;
    }
    if (max_index < 0)
    {
      charge_score_ = 0;
      return;
    }

    first_index = first_index < 0 ? 0 : first_index;
    float p = .0f;
    const float factor = .3;
    for (int c = max_index; c < last_index; c++)
    {
      float diff = per_charge_int_[c + 1] - per_charge_int_[c];
      if (diff > 0) p += diff;
      else if (! is_low_charge && diff < -(per_charge_int_[c]) * factor)
        p -= diff + (per_charge_int_[c]) * factor;
    }
    for (int c = max_index; c > first_index; c--)
    {
      float diff = per_charge_int_[c - 1] - per_charge_int_[c];
      if (diff > 0) p += diff;
      else if (! is_low_charge && diff < -(per_charge_int_[c]) * factor)
        p -= diff + (per_charge_int_[c]) * factor;
    }
    charge_score_ = std::max(.0f, 1.0f - p / summed_intensity);
  }

  void PeakGroup::getPerIsotopeIntensities_(std::vector<float>& intensities,
                                            int& min_isotope_index,
                                            int& max_isotope_index,
                                            int abs_charge,
                                            int min_negative_isotope_index,
                                            double tol)
  {
    // Compute Da tolerance from ppm tolerance using the first peak's uncharged mass.
    // Assumption: all peaks in this group share similar mass, so the first peak is a
    // representative for tolerance calculation. Division by 2.0 converts from full-width
    // tolerance to half-width (radius) for the smoothing window.
    int da_tol = (int)(tol * logMzpeaks_[0].getUnchargedMass() / 2.0);

    min_isotope_index = 1e5;
    max_isotope_index = -1; // this is inclusive!!

    for (const auto& p : logMzpeaks_)
    {
      max_isotope_index = max_isotope_index < p.getIsotopeIndex() ? p.getIsotopeIndex() : max_isotope_index;
      min_isotope_index = min_isotope_index < p.getIsotopeIndex() ? min_isotope_index : p.getIsotopeIndex();
    }
    intensities.assign(max_isotope_index + 1 + da_tol - min_negative_isotope_index_, .0f);

    // Gaussian smoothing denominator derivation:
    // - Standard Gaussian: exp(-x²/(2σ²)), where FWHM = 2.355σ, so σ = FWHM/2.355
    // - Here da_tol is treated as FWHM, giving σ = da_tol/2.355
    // - The formula: denom = 2σ² / iso_da_distance_ = 2*(da_tol/2.355)² / iso_da_distance_
    // - This scales the Gaussian width by isotope spacing, producing broader smoothing
    //   that allows adjacent isotope peaks to blend together. This is intentional to
    //   handle mass calibration errors and improve isotope pattern matching robustness.
    // NOTE: This nonstandard scaling factor lacks formal validation. Consider adding
    // unit tests demonstrating its impact on isotope deconvolution accuracy.
    double denom = 2.0 * std::pow(da_tol / 2.355, 2.0) / iso_da_distance_;

    for (const auto& peak : logMzpeaks_)
    {
      if (abs_charge > 0 && peak.getAbsCharge() != abs_charge) { continue; }

      if (peak.getIsotopeIndex() - min_negative_isotope_index >= (int)intensities.size()) { continue; }

      if (peak.getIsotopeIndex() < 0) { continue; }

      for (int margin = -da_tol; margin <= da_tol; margin++)
      {
        int index = peak.getIsotopeIndex() + margin - min_negative_isotope_index;
        if (index < 0 || index >= (int)intensities.size()) continue;
        // Fallback when denom <= 0: can occur if da_tol is 0 (very small mass or tight tolerance)
        // or iso_da_distance_ is 0/negative (degenerate isotope spacing). In such edge cases,
        // skip Gaussian weighting and add raw intensity directly - safe because the smoothing
        // window collapses to a single bin anyway.
        intensities[index] += denom > 0 ? float(peak.getIntensity() * exp(-margin * margin / denom)) : peak.getIntensity();
      }
    }

    if (min_negative_isotope_index != 0)
    {
      for (const auto& peak : negative_iso_peaks_)
      {
        if (abs_charge > 0 && peak.getAbsCharge() != abs_charge) { continue; }

        if (peak.getIsotopeIndex() - min_negative_isotope_index >= (int)intensities.size()) { continue; }

        if (peak.getIsotopeIndex() - min_negative_isotope_index < 0) { continue; }

        for (int margin = -da_tol; margin <= da_tol; margin++)
        {
          int index = peak.getIsotopeIndex() + margin - min_negative_isotope_index;
          if (index < 0 || index >= (int)intensities.size()) continue;
          // Same denom > 0 fallback as above for negative isotope peaks
          intensities[index] += denom > 0 ? float(peak.getIntensity() * exp(-margin * margin / denom)) : peak.getIntensity();
        }
      }
    }
  }

  void PeakGroup::updateMonoMassAndIsotopeIntensities(double tol)
  {
    if (logMzpeaks_.empty()) { return; }
    int min_isotope_index, max_isotope_index;
    sortPeaks_();

    intensity_ = .0;
    double nominator = .0;

    getPerIsotopeIntensities_(per_isotope_int_, min_isotope_index, max_isotope_index, 0, min_negative_isotope_index_, tol);

    for (const auto& p : logMzpeaks_)
    {
      float pi = p.getIntensity();
      if (p.getIsotopeIndex() - min_negative_isotope_index_ < 0) { continue; }
      nominator += pi * (p.getUnchargedMass() - p.getIsotopeIndex() * iso_da_distance_);
      intensity_ += pi;
    }

    monoisotopic_mass_ = nominator / intensity_;
  }

  void PeakGroup::setSNR(const float snr)
  {
    snr_ = snr;
  }

  void PeakGroup::setChargeSNR(const int abs_charge, const float c_snr)
  {
    if (max_abs_charge_ < abs_charge) { return; }
    if (per_charge_snr_.empty()) { per_charge_snr_ = std::vector<float>(1 + max_abs_charge_, .0); }
    per_charge_snr_[abs_charge] = c_snr;
  }

  void PeakGroup::setTargeted()
  {
    is_targeted_ = true;
  }

  void PeakGroup::setChargeIsotopeCosine(const int abs_charge, const float cos)
  {
    if (max_abs_charge_ < abs_charge) { return; }
    if (per_charge_cos_.empty()) { per_charge_cos_ = std::vector<float>(1 + max_abs_charge_, .0); }
    per_charge_cos_[abs_charge] = cos;
  }

  void PeakGroup::setAbsChargeRange(const int min_abs_charge, const int max_abs_charge)
  {
    min_abs_charge_ = min_abs_charge;
    max_abs_charge_ = max_abs_charge;
  }

  void PeakGroup::setScanNumber(const int sn)
  {
    scan_number_ = sn;
  }

  void PeakGroup::setIsotopeCosine(const float cos)
  {
    isotope_cosine_score_ = cos;
  }

  void PeakGroup::setMonoisotopicMass(double mono_mass)
  {
    monoisotopic_mass_ = mono_mass;
  }

  void PeakGroup::setRepAbsCharge(const int max_snr_abs_charge)
  {
    max_snr_abs_charge_ = max_snr_abs_charge;
  }

  void PeakGroup::setChargeScore(const float score)
  {
    charge_score_ = score;
  }

  void PeakGroup::setAvgPPMError(const float error)
  {
    avg_ppm_error_ = error;
  }

  void PeakGroup::setQscore(const double qscore)
  {
    qscore_ = std::min(1.0, qscore);
  }

  std::tuple<double, double> PeakGroup::getRepMzRange() const
  {
    return getMzRange(getRepAbsCharge());
  }

  std::tuple<double, double> PeakGroup::getMzRange(int abs_charge) const
  {
    double mz_start = -1;
    double mz_end = -10;
    if (! (abs_charge > max_abs_charge_ || abs_charge < min_abs_charge_))
    {
      for (const auto& tmp_p : logMzpeaks_)
      {
        if (tmp_p.getAbsCharge() != abs_charge) { continue; }
        if (mz_start < 0) { mz_start = tmp_p.getMZ(); }
        else
        {
          mz_start = mz_start < tmp_p.getMZ() ? mz_start : tmp_p.getMZ();
        }
        mz_end = mz_end > tmp_p.getMZ() ? mz_end : tmp_p.getMZ();
      }
    }
    return std::tuple<double, double> {mz_start, mz_end};
  }

  std::tuple<int, int> PeakGroup::getAbsChargeRange() const
  {
    return std::tuple<int, int> {min_abs_charge_, max_abs_charge_};
  }

  const std::vector<float>& PeakGroup::getIsotopeIntensities() const
  {
    return per_isotope_int_;
  }

  int PeakGroup::getScanNumber() const
  {
    return scan_number_;
  }

  float PeakGroup::getPeakOccupancy() const
  {
    int min_i = -1, max_i = 0;
    for (const auto& p : *this)
    {
      int i = p.getIsotopeIndex();
      max_i = std::max(max_i, i);
      if (min_i < 0) min_i = i;

      min_i = std::min(min_i, i);
    }

    auto used = std::vector<bool>((max_abs_charge_ - min_abs_charge_ + 1) * (max_i - min_i + 1), false);
    for (const auto& p : *this)
    {
      used[(p.getAbsCharge() - min_abs_charge_ + 1) * (p.getIsotopeIndex() - min_i + 1) - 1] = true;
    }
    int count = 0;
    for (const auto& b : used)
      if (b) count++;

    return (float)count / (float)used.size();
  }


  double PeakGroup::getMonoMass() const
  {
    return monoisotopic_mass_;
  }

  float PeakGroup::getIntensity() const
  {
    return intensity_;
  }

  float PeakGroup::getIsotopeCosine() const
  {
    return isotope_cosine_score_;
  }

  int PeakGroup::getRepAbsCharge() const
  {
    return max_snr_abs_charge_;
  }

  double PeakGroup::getQscore() const
  {
    return qscore_;
  }

  double PeakGroup::getQscore2D() const
  {
    return std::max(qscore_, qscore2D_);
  }

  void PeakGroup::setFeatureIndex(uint findex)
  {
    findex_ = findex;
  }

  bool PeakGroup::isTargeted() const
  {
    return is_targeted_;
  }

  void PeakGroup::updateSNR_(float mul_factor)
  {
    per_charge_snr_.assign(1 + max_abs_charge_, .0f);
    float total_nom = 0;
    float total_denom = 0;
    for (size_t c = min_abs_charge_; (int)c < 1 + max_abs_charge_; ++c)
    {
      if (per_charge_cos_.size() > c)
      {
        float per_charge_cos_squared = per_charge_cos_[c] * per_charge_cos_[c];
        float sig_pwr = per_charge_sum_signal_squared_[c] * per_charge_cos_squared;
        float nom = 1e-6f * mul_factor + mul_factor * sig_pwr;
        float denom = 1e-6f * mul_factor + per_charge_noise_pwr_[c] + (1 - per_charge_cos_squared) * per_charge_sum_signal_squared_[c];

        per_charge_snr_[c] = denom <= 0 ? .0f : (nom / denom);

        total_denom += (1 - per_charge_cos_squared) * per_charge_sum_signal_squared_[c];
        total_nom += sqrt(sig_pwr);
      }
    }

    snr_ = mul_factor * (1e-6f + total_nom * total_nom) / (1e-6f * mul_factor + total_denom + per_charge_noise_pwr_[0]);

    per_charge_sum_signal_squared_.clear();
    per_charge_noise_pwr_.clear();
  }

  float PeakGroup::getQvalue() const
  {
    return qvalue_;
  }


  float PeakGroup::getSNR() const
  {
    return snr_;
  }

  float PeakGroup::getChargeScore() const
  {
    return charge_score_;
  }

  float PeakGroup::getAvgPPMError() const
  {
    return avg_ppm_error_;
  }

  float PeakGroup::getAvgDaError() const
  {
    return avg_da_error_;
  }

  float PeakGroup::getChargeSNR(const int abs_charge) const
  {
    if (abs_charge < 0 || (int)per_charge_snr_.size() <= abs_charge) { return 0; }
    return per_charge_snr_[abs_charge];
  }

  float PeakGroup::getChargeIsotopeCosine(const int abs_charge) const
  {
    if (abs_charge < 0 || (int)per_charge_cos_.size() <= abs_charge) { return 0; }
    return per_charge_cos_[abs_charge];
  }

  float PeakGroup::getChargeIntensity(const int abs_charge) const
  {
    if (abs_charge < 0 || per_charge_int_.empty() || (int)per_charge_int_.size() <= abs_charge) { return 0; }
    return per_charge_int_[abs_charge];
  }

  bool PeakGroup::isPositive() const
  {
    return is_positive_;
  }

  PeakGroup::TargetDecoyType PeakGroup::getTargetDecoyType() const
  {
    return target_decoy_type_;
  }

  void PeakGroup::setTargetDecoyType(PeakGroup::TargetDecoyType index)
  {
    target_decoy_type_ = index;
  }

  void PeakGroup::setIsotopeDaDistance(const double d)
  {
    iso_da_distance_ = d;
  }

  double PeakGroup::getIsotopeDaDistance() const
  {
    return iso_da_distance_;
  }

  void PeakGroup::setIndex(const uint i)
  {
    index_ = i;
  }

  uint PeakGroup::getIndex() const
  {
    return index_;
  }

  uint PeakGroup::getFeatureIndex() const
  {
    return findex_;
  }

  void PeakGroup::setQscore2D(double fqscore)
  {
    qscore2D_ = fqscore;
  }

  std::vector<FLASHHelperClasses::LogMzPeak>::const_iterator PeakGroup::begin() const noexcept
  {
    return logMzpeaks_.begin();
  }

  std::vector<FLASHHelperClasses::LogMzPeak>::const_iterator PeakGroup::end() const noexcept
  {
    return logMzpeaks_.end();
  }

  std::vector<FLASHHelperClasses::LogMzPeak>::iterator PeakGroup::begin() noexcept
  {
    return logMzpeaks_.begin();
  }

  std::vector<FLASHHelperClasses::LogMzPeak>::iterator PeakGroup::end() noexcept
  {
    return logMzpeaks_.end();
  }

  const FLASHHelperClasses::LogMzPeak& PeakGroup::operator[](const Size i) const
  {
    return logMzpeaks_[i];
  }

  void PeakGroup::push_back(const FLASHHelperClasses::LogMzPeak& pg)
  {
    logMzpeaks_.push_back(pg);
  }

  FLASHHelperClasses::LogMzPeak& PeakGroup::back()
  {
    return logMzpeaks_.back();
  }

  Size PeakGroup::size() const noexcept
  {
    return logMzpeaks_.size();
  }

  void PeakGroup::clear_()
  {
    std::vector<LogMzPeak>().swap(logMzpeaks_);
  }

  void PeakGroup::reserve(Size n)
  {
    logMzpeaks_.reserve(n);
  }

  bool PeakGroup::empty() const
  {
    return logMzpeaks_.empty();
  }

  void PeakGroup::swap(std::vector<FLASHHelperClasses::LogMzPeak>& x)
  {
    logMzpeaks_.swap(x);
  }

  void PeakGroup::sort()
  {
    sortPeaks_();
  }

  void PeakGroup::sortPeaks_()
  {
    // A strictly increasing range has exactly one sorted order, so skipping std::sort gives the
    // identical sequence. Ranges with ties (equal log m/z and intensity) are still sorted as before.
    const auto first_not_strict = std::adjacent_find(logMzpeaks_.begin(), logMzpeaks_.end(),
                                                     [](const LogMzPeak& a, const LogMzPeak& b) { return ! (a < b); });
    if (first_not_strict != logMzpeaks_.end()) { std::sort(logMzpeaks_.begin(), logMzpeaks_.end()); }
  }

  void PeakGroup::setQvalue(double q)
  {
    qvalue_ = (float)q;
  }

  std::tuple<std::vector<double>, std::vector<double>> PeakGroup::getDLVector(const MSSpectrum& spec,
                                                                              const Size charge_count,
                                                                              const Size isotope_count,
                                                                              const FLASHHelperClasses::PrecalculatedAveragine& avg,
                                                                              double tol)
  {
    //assert(isotope_count > 3 && charge_count > 0);
    std::tuple<std::vector<double>, std::vector<double>> sig_noise;
    auto noisy_peaks = recruitAllPeaksInSpectrum(spec, tol * 1e-6, avg, getMonoMass(), false);

    const int apex_iso_index = avg.getApexIndex(getMonoMass());
    int apex_charge = -1;
    double z_intensity = 0;
    double max_s_intensity = 0, max_n_intensity = 0;
    for (int z = min_abs_charge_; z<= max_abs_charge_; z++)
    {
      double z_i = getChargeIntensity(z);
      if (z_intensity > z_i) continue;
      z_intensity = z_i;
      apex_charge = z;
    }

    int min_z = int(apex_charge - charge_count / 2);
    int max_z = int(apex_charge + charge_count / 2); // inclusive

    int min_iso_index = int(apex_iso_index - isotope_count / 2);
    int max_iso_index = int(apex_iso_index + isotope_count / 2); // inclusive

    auto& [sig, noise] = sig_noise;
    sig.resize(charge_count * isotope_count, .0);
    noise.resize(charge_count * isotope_count, .0);

    for (const auto& p : logMzpeaks_)
    {
      if (min_z > p.getAbsCharge() || max_z < p.getAbsCharge()) continue;
      if (min_iso_index > p.getIsotopeIndex() || max_iso_index < p.getIsotopeIndex()) continue;

      int z_index = int(p.getAbsCharge() - apex_charge + charge_count / 2);
      int iso_index = int(p.getIsotopeIndex() - apex_iso_index + isotope_count / 2);
      int v_index = int(z_index * isotope_count + iso_index);

      sig[v_index] += p.getIntensity();
      max_s_intensity = std::max(max_s_intensity, sig[v_index]);
    }

    for (const auto& p : noisy_peaks)
    {
      if (min_z > p.getAbsCharge() || max_z < p.getAbsCharge()) continue;
      if (min_iso_index > p.getIsotopeIndex() || max_iso_index < p.getIsotopeIndex()) continue;

      int z_index = int(p.getAbsCharge() - apex_charge + charge_count / 2);
      int iso_index = int(p.getIsotopeIndex() - apex_iso_index + isotope_count / 2);

      int v_index = int(z_index * isotope_count + iso_index);
      if (sig[v_index] > 0)
      {
        bool too_close = false;
        for (int off = -1; off < 2; off ++)
        {
          if (off + p.getIsotopeIndex() < 0) continue;
          double correct_mass = getMonoMass() + (off + p.getIsotopeIndex()) * iso_da_distance_;
          if (std::abs(p.getUnchargedMass() - correct_mass) < .2)
          {
            too_close = true;
            break;
          }
        }
        if (too_close) continue;
      }
      noise[v_index] += p.getIntensity();
      max_n_intensity = std::max(max_n_intensity, sig[v_index]);
    }

    if (max_s_intensity > 0)
    {
      for (auto& s : sig)
      {
        s /= max_s_intensity;
      }
    }

    if (max_n_intensity > 0)
    {
      for (auto& n : noise)
      {
        n /= max_n_intensity;
      }
    }

    return sig_noise;
  }
  } // namespace OpenMS
