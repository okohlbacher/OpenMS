// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
// --------------------------------------------------------------------------
// $Maintainer: Oliver Kohlbacher $
// $Authors: Oliver Kohlbacher $
// --------------------------------------------------------------------------

#pragma once

#include <OpenMS/ANALYSIS/ID/PercolatorTypes.h>
#include <OpenMS/DATASTRUCTURES/DefaultParamHandler.h>

#include <cstdint>
#include <utility>
#include <vector>

namespace OpenMS
{
  /**
    @brief Fast semi-supervised target/decoy rescoring with RESET-style FDR control.

    Drop-in alternative to Percolator::rescore(const RescoreInput&) with a linear core:
    - method "lda": closed-form Fisher LDA per iteration (one parallel pass over the training rows);
    - method "newton": squared-hinge linear SVM (Percolator's objective), explicit-Hessian Newton,
      3 folds x 3x3 (C+, C-) grid run as parallel tasks, C chosen by held-out pseudo-target discoveries.

    FDR control follows Percolator-RESET (Freestone et al. 2025): each decoy is assigned to training or
    estimation by an independent coin keyed by @p coin_keys (use the unmodified peptide sequence, so all
    rows of one stem share the coin). Training sees only training-decoy labels; estimating decoys are
    pseudo-targets. Training positives use FDP = 3(D_train+1)/T; the reported q-values use the estimating
    decoys only, FDP = 2(D_est+1)/T. The training set is capped (train_cap rows, uniform thinning after the
    coin flip); every row is scored.

    decoy_mode "two" (Percolator-RESET two-decoy mode): search against targets plus two decoy databases, keep the
    winner of the three-way competition, and pass @p decoy_set (1 or 2 for decoy rows). Set-1 winners are the
    training decoys, set-2 winners the estimating decoys; no coin is drawn. Training positives use
    FDP = 2(D_train+1)/T, reported q-values FDP = (D_est+1)/T. Costs a larger search, recovers the power the
    single-decoy split loses, and lowers run-to-run variance (Freestone et al. 2025).

    Rows must already be competition winners (one row per spectrum / hypothesis).
    Output: scores for all rows; q-values for targets and estimating decoys (training decoys get q = 1);
    peps are not computed (left empty).
  */
  class OPENMS_DLLAPI PSMRescorer : public DefaultParamHandler
  {
  public:
    struct Timing
    {
      double prep = 0, train = 0, score = 0, qvalue = 0;
    };

    PSMRescorer();

    RescoreOutput rescore(const RescoreInput& input, const std::vector<std::uint64_t>& coin_keys = {},
                          const std::vector<char>& decoy_set = {});

    const Timing& timing() const { return timing_; }
    /// targets with q <= 0.01 in the last rescore()
    std::size_t accepted() const { return accepted_; }
    /// number of training rows actually used (after the cap)
    std::size_t trainingRows() const { return training_rows_; }

    /// Sort (score, row) pairs by descending score, ties by ascending row: per-thread std::sort of p chunks,
    /// regular-sample splitters, then each thread k-way merges one output partition with a heap.
    static void parallelSortDesc(std::vector<std::pair<double, std::uint32_t>>& v, int threads);

    /// q-values over rows with use[i]: FDP = factor * (decoys + 1) / targets, monotonised. Others get 1.
    static std::vector<double> qValues(const std::vector<double>& score, const std::vector<char>& is_target,
                                       const std::vector<char>& use, double factor, int threads,
                                       double alpha = 0.01, std::size_t* accepted = nullptr);

  private:
    Timing timing_;
    std::size_t accepted_ = 0;
    std::size_t training_rows_ = 0;
  };
}
