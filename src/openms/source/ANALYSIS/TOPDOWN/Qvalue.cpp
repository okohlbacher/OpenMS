// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// --------------------------------------------------------------------------
// $Maintainer: Kyowon Jeong$
// $Authors: Kyowon Jeong$
// --------------------------------------------------------------------------

#include <OpenMS/ANALYSIS/TOPDOWN/PeakGroup.h>
#include <OpenMS/ANALYSIS/TOPDOWN/Qvalue.h>
#include <algorithm>
#include <OpenMS/DATASTRUCTURES/MatrixEigen.h>
#include <Eigen/QR>

namespace OpenMS
{
  /// simple function to generate distribution from input vector values
  Matrix<double> getDistVector(const std::vector<double>& values, Size num_bin, double minv, double maxv)
  {
    Matrix<double> ret(num_bin, 1, .0);
    for (const auto& v : values)
    {
      if (v >= maxv) continue;
      if (v < minv) continue;

      Size bin = Size((v - minv) / (maxv - minv) * num_bin);
      ret.setValue(bin, 0, ret.getValue(bin, 0) + 1);
    }
    return ret;
  }

  double Qvalue::updatePeakGroupQvalues(std::vector<DeconvolvedSpectrum>& deconvolved_spectra) // per ms level + precursor update as well.
  {
    double noise_weight = 1;
    std::map<uint, std::vector<double>> score_map_target; // target PeakGroupScoring vector per ms level
    std::map<uint, std::vector<double>> score_signal_decoy_map; // signal decoy PeakGroupScoring vector per ms level
    std::map<uint, std::vector<double>> score_noise_decoy_map; // noise decoy PeakGroupScoring vector per ms level
    // qscore -> qvalue per ms level as parallel arrays sorted by qscore (filled in descending order, then reversed)
    std::map<uint, std::pair<std::vector<double>, std::vector<double>>> qscore_qvalue_map;

    // to calculate qvalues per ms level, store Qscores per ms level
    std::vector<char> used_feature_indices; // indexed by feature index (0 = none)

    for (auto& deconvolved_spectrum : deconvolved_spectra)
    {
      if (deconvolved_spectrum.empty())
        continue;

      uint ms_level = deconvolved_spectrum.getOriginalSpectrum().getMSLevel();
      for (auto& pg : deconvolved_spectrum)
      {
        if (pg.getFeatureIndex() > 0)
        {
          const Size findex = pg.getFeatureIndex();
          if (findex >= used_feature_indices.size()) { used_feature_indices.resize(findex + 1, 0); }
          if (used_feature_indices[findex]) continue;
          used_feature_indices[findex] = 1;
        }

        if (pg.getTargetDecoyType() == PeakGroup::TargetDecoyType::target)
        {
          score_map_target[ms_level].push_back(pg.getQscore2D());
        }
        else if (pg.getTargetDecoyType() == PeakGroup::TargetDecoyType::signal_decoy)
        {
          score_signal_decoy_map[ms_level].push_back(pg.getQscore2D());
        }
        else if (pg.getTargetDecoyType() == PeakGroup::TargetDecoyType::noise_decoy)
        {
          score_noise_decoy_map[ms_level].push_back(pg.getQscore2D());
        }
      }
    }

    // per ms score, calculate Qvalues
    for (auto& [ms_level, scores_target] : score_map_target)
    {
      auto& scores_signal_decoy = score_signal_decoy_map[ms_level];
      auto& scores_noise_decoy = score_noise_decoy_map[ms_level];

      std::sort(scores_target.begin(), scores_target.end());
      std::sort(scores_signal_decoy.begin(), scores_signal_decoy.end());
      std::sort(scores_noise_decoy.begin(), scores_noise_decoy.end());

      double sum = 0;
      double max_score_for_weight_calculation = .7;
      double min_score_for_weight_calculation = .3;
      double iso_sum = std::accumulate(scores_signal_decoy.begin(), scores_signal_decoy.end(), .0);

      for (int i = scores_signal_decoy.size() - 1; i >= 0; i--)
      {
        sum += scores_signal_decoy[i];
        if (sum > iso_sum * .8 || scores_signal_decoy[i] < .5)
        {
          max_score_for_weight_calculation = std::min(max_score_for_weight_calculation, scores_signal_decoy[i]);
          break;
        }
      }

      Size num_bin = 6;
      // get the score distributions
      auto score_dist_target = getDistVector(scores_target, num_bin, min_score_for_weight_calculation, max_score_for_weight_calculation);
      auto score_dist_noise_decoy = getDistVector(scores_noise_decoy, num_bin, min_score_for_weight_calculation, max_score_for_weight_calculation);
      auto score_dist_signal_decoy = getDistVector(scores_signal_decoy, num_bin, min_score_for_weight_calculation, max_score_for_weight_calculation);

      // noise decoy weight calculation using Least Square
      Matrix<double> left(score_dist_target.rows(), 2, 1);
      for (int r = 0; r < score_dist_target.rows(); r++)
      {
        double v = score_dist_target.getValue(r, 0);
        v -= score_dist_signal_decoy.getValue(r, 0);
        score_dist_target.setValue(r, 0, v);
        left.setValue(r, 0, score_dist_noise_decoy.getValue(r, 0));
      }

      auto calculated_vec = eigenView(left).completeOrthogonalDecomposition().pseudoInverse() * eigenView(score_dist_target);
      noise_weight = calculated_vec.row(0)[0];

      if (calculated_vec.row(1)[0] < 0)
      {
        auto calculated_vec_non_negative = eigenView(score_dist_noise_decoy).completeOrthogonalDecomposition().pseudoInverse() * eigenView(score_dist_target);
        noise_weight = calculated_vec_non_negative.row(0)[0];
      }

      if (std::isnan(noise_weight)) noise_weight = 1.0;
      noise_weight = std::max(noise_weight, 0.01);
      std::sort(scores_target.rbegin(), scores_target.rend());
      std::sort(scores_signal_decoy.rbegin(), scores_signal_decoy.rend());
      std::sort(scores_noise_decoy.rbegin(), scores_noise_decoy.rend());

      // now get the qvalues
      auto& [qscore_keys, qvalue_values] = qscore_qvalue_map[ms_level];
      qscore_keys.reserve(scores_target.size());
      qvalue_values.reserve(scores_target.size());
      double nom_i = 0, nom_c = 0, nom_n = 0;
      Size j_i = 0, j_n = 0;

      for (Size i = 0; i < scores_target.size(); i++)
      {
        double ts = scores_target[i];
        double di = 0, dc = 0, dn = 0;
        while (i < scores_target.size() - 1 && scores_target[i + 1] == ts)
        {
          i++;
        }

        while (j_n < scores_noise_decoy.size() && scores_noise_decoy[j_n] >= ts)
        {
          dn += noise_weight;
          ++j_n;
        }
        while (j_i < scores_signal_decoy.size() && scores_signal_decoy[j_i] >= ts)
        {
          di++;
          ++j_i;
        }
        nom_n += dn;
        nom_i += di;
        nom_c += dc;
        double tmp_q = (nom_i + nom_c + nom_n) / double(1 + i);
        qscore_keys.push_back(ts); // ts values are unique and descending here
        qvalue_values.push_back(std::min(1.0, tmp_q));
      }
    }

    // refine qvalues to make them monotonic decreasing
    for (const auto& titem : score_map_target)
    {
      uint ms_level = titem.first;
      auto& [qscore_keys, qvalue_values] = qscore_qvalue_map[ms_level];
      std::reverse(qscore_keys.begin(), qscore_keys.end());
      std::reverse(qvalue_values.begin(), qvalue_values.end());
      double cummin = 1.0;
      for (auto& qvalue : qvalue_values) // ascending qscore order, as the former std::map iteration
      {
        cummin = std::min(qvalue, cummin);
        qvalue = cummin;
      }
      // Sorted arrays for the per-peak-group lookups; a score that is not a target score of this level maps to 0,
      // exactly what map_qvalue[score] used to return (and insert).
      const auto lookup = [&](double score) {
        const auto it = std::lower_bound(qscore_keys.begin(), qscore_keys.end(), score);
        return (it != qscore_keys.end() && *it == score) ? qvalue_values[it - qscore_keys.begin()] : 0.0;
      };

      for (auto& deconvolved_spectrum : deconvolved_spectra)
      {
        if (deconvolved_spectrum.empty() || deconvolved_spectrum.isDecoy())
          continue;

        // set precursor Qvalue here
        if (deconvolved_spectrum.getOriginalSpectrum().getMSLevel() == ms_level + 1 && !deconvolved_spectrum.getPrecursorPeakGroup().empty())
        {
          auto precursor_pg = deconvolved_spectrum.getPrecursorPeakGroup();
          double qs = precursor_pg.getQscore2D();

          precursor_pg.setQvalue(lookup(qs));
          deconvolved_spectrum.setPrecursorPeakGroup(precursor_pg);
        }

        if (deconvolved_spectrum.getOriginalSpectrum().getMSLevel() != ms_level)
        {
          continue;
        }

        for (auto& pg : deconvolved_spectrum)
        {
          pg.setQvalue(lookup(pg.getQscore2D()));
        }
      }
    }
    return noise_weight;
  }
} // namespace OpenMS