// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
// --------------------------------------------------------------------------
// $Maintainer: Oliver Kohlbacher $
// $Authors: Oliver Kohlbacher $
// --------------------------------------------------------------------------

#include <OpenMS/ANALYSIS/ID/PSMRescorer.h>

#include <OpenMS/CHEMISTRY/AASequence.h>
#include <OpenMS/CONCEPT/Constants.h>
#include <OpenMS/CONCEPT/Exception.h>
#include <OpenMS/CONCEPT/LogStream.h>

#include <Eigen/Dense>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <numeric>
#include <queue>

#ifdef _OPENMP
#include <omp.h>
#endif

namespace OpenMS
{
  namespace
  {
    using Clock = std::chrono::steady_clock;
    double since(Clock::time_point t) { return std::chrono::duration<double>(Clock::now() - t).count(); }

    std::uint64_t mix(std::uint64_t x)  // splitmix64 finaliser
    {
      x += 0x9e3779b97f4a7c15ULL;
      x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
      x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
      return x ^ (x >> 31);
    }

    using Pair = std::pair<double, std::uint32_t>;
    inline bool before(const Pair& a, const Pair& b) { return a.first > b.first || (a.first == b.first && a.second < b.second); }

    // Row-major standardized matrix with a trailing 1 for the bias.
    struct Matrix
    {
      std::size_t n = 0, d = 0;  // d includes the bias column
      std::vector<double> x;
      const double* row(std::size_t i) const { return x.data() + i * d; }
    };

    double dot(const double* a, const Eigen::VectorXd& w)
    {
      double s = 0;
      for (Eigen::Index j = 0; j < w.size(); ++j) s += a[j] * w[j];
      return s;
    }

    // min 0.5 w'w + sum_i C_i max(0, 1 - y_i w.x_i)^2 (Percolator's L2-SVM), explicit (d x d) Hessian.
    Eigen::VectorXd newton(const Matrix& X, const std::vector<std::uint32_t>& rows, const std::vector<signed char>& y,
                           double cp, double cn, const Eigen::VectorXd& w0)
    {
      const auto d = static_cast<Eigen::Index>(X.d);
      Eigen::VectorXd w = w0;
      auto objective = [&](const Eigen::VectorXd& v) {
        double f = 0.5 * v.squaredNorm();
        for (std::uint32_t r : rows)
        {
          const double m = 1.0 - y[r] * dot(X.row(r), v);
          if (m > 0) f += (y[r] > 0 ? cp : cn) * m * m;
        }
        return f;
      };
      double f = objective(w);
      Eigen::MatrixXd A;  // active rows scaled by sqrt(2 C)
      for (int it = 0; it < 30; ++it)
      {
        Eigen::VectorXd g = w;
        std::vector<std::uint32_t> act;
        act.reserve(rows.size());
        for (std::uint32_t r : rows)
        {
          const double m = 1.0 - y[r] * dot(X.row(r), w);
          if (m <= 0) continue;
          act.push_back(r);
          const double c = y[r] > 0 ? cp : cn;
          const double* xr = X.row(r);
          for (Eigen::Index j = 0; j < d; ++j) g[j] -= 2.0 * c * y[r] * m * xr[j];
        }
        if (g.norm() < 1e-6 * (1.0 + w.norm())) break;
        A.resize(static_cast<Eigen::Index>(act.size()), d);
        for (std::size_t k = 0; k < act.size(); ++k)
        {
          const double s = std::sqrt(2.0 * (y[act[k]] > 0 ? cp : cn));
          A.row(static_cast<Eigen::Index>(k)) = Eigen::Map<const Eigen::RowVectorXd>(X.row(act[k]), d) * s;
        }
        Eigen::MatrixXd H = Eigen::MatrixXd::Identity(d, d);
        H.selfadjointView<Eigen::Lower>().rankUpdate(A.transpose());
        const Eigen::VectorXd step = H.selfadjointView<Eigen::Lower>().ldlt().solve(-g);
        double a = 1.0, fn = f;
        bool accepted = false;
        for (; a > 1e-4; a *= 0.5)
        {
          fn = objective(w + a * step);
          if (fn <= f + 1e-4 * a * g.dot(step)) { accepted = true; break; }
        }
        if (!accepted) break;  // keep the last accepted iterate
        w += a * step;
        if (std::abs(f - fn) < 1e-10 * (1.0 + std::abs(f))) { f = fn; break; }
        f = fn;
      }
      return w;
    }

    // Fisher LDA: w = Sw^-1 (mu_pos - mu_neg); one parallel pass for means, one for the scatter.
    Eigen::VectorXd lda(const Matrix& X, const std::vector<std::uint32_t>& rows, const std::vector<signed char>& y, int threads)
    {
      const auto d = static_cast<Eigen::Index>(X.d - 1);  // without bias
      Eigen::VectorXd sp = Eigen::VectorXd::Zero(d), sn = Eigen::VectorXd::Zero(d);
      Eigen::MatrixXd S = Eigen::MatrixXd::Zero(d, d);
      std::size_t np = 0, nn = 0;
#pragma omp parallel num_threads(threads)
      {
        Eigen::VectorXd lp = Eigen::VectorXd::Zero(d), ln = Eigen::VectorXd::Zero(d);
        std::size_t cp = 0, cn = 0;
#pragma omp for nowait
        for (std::size_t k = 0; k < rows.size(); ++k)
        {
          const Eigen::Map<const Eigen::VectorXd> x(X.row(rows[k]), d);
          if (y[rows[k]] > 0) { lp += x; ++cp; } else { ln += x; ++cn; }
        }
#pragma omp critical
        { sp += lp; sn += ln; np += cp; nn += cn; }
      }
      if (np == 0 || nn == 0) throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "LDA needs both classes", "");
      const Eigen::VectorXd mp = sp / double(np), mn = sn / double(nn);
#pragma omp parallel num_threads(threads)
      {
        Eigen::MatrixXd L = Eigen::MatrixXd::Zero(d, d);
        Eigen::MatrixXd B(256, d);
        Eigen::Index fill = 0;
#pragma omp for nowait
        for (std::size_t k = 0; k < rows.size(); ++k)
        {
          const Eigen::Map<const Eigen::RowVectorXd> x(X.row(rows[k]), d);
          B.row(fill++) = x - (y[rows[k]] > 0 ? mp : mn).transpose();
          if (fill == B.rows()) { L.selfadjointView<Eigen::Lower>().rankUpdate(B.transpose()); fill = 0; }
        }
        if (fill) L.selfadjointView<Eigen::Lower>().rankUpdate(B.topRows(fill).transpose());
#pragma omp critical
        S += L;
      }
      Eigen::MatrixXd Sw = S.selfadjointView<Eigen::Lower>();
      Sw /= double(np + nn);
      Sw.diagonal().array() += 1e-6;
      const Eigen::VectorXd w = Sw.ldlt().solve(mp - mn);
      Eigen::VectorXd out(d + 1);
      out.head(d) = w;
      out[d] = -w.dot(mp + mn) / 2.0;
      return out;
    }
  }

  PSMRescorer::PSMRescorer() : DefaultParamHandler("PSMRescorer")
  {
    defaults_.setValue("method", "newton", "Learner core: 'newton' (squared-hinge linear SVM) or 'lda' (Fisher LDA).");
    defaults_.setValidStrings("method", {"newton", "lda"});
    defaults_.setValue("train_cap", 500000, "About this many training rows (uniform random thinning after the decoy coin flip; the size is approximate).");
    defaults_.setMinInt("train_cap", 1000);
    defaults_.setValue("iterations", 5, "Semi-supervised iterations (RESET default).");
    defaults_.setMinInt("iterations", 1);
    defaults_.setValue("exclude_feature_prefixes", std::vector<std::string>{"ion_prior_"},
                       "rescoreRun(): leave out features whose names start with one of these. Default: ProSE's self-trained ion "
                       "priors, which are learned from the run's target/decoy labels before the decoy split and would leak the "
                       "labels of estimating decoys.");
    defaults_.setValue("train_fdr", 0.01, "FDR for selecting training positives (pseudo-targets).");
    defaults_.setValue("test_fdr", 0.01, "FDR at which accepted() is counted.");
    defaults_.setValue("seed", 1, "Salt for the decoy coin and the fold assignment. Record it; do not optimise over it.");
    defaults_.setValue("num_threads", 1, "Threads (OpenMP).");
    defaults_.setValue("c_scale", 1.0, "Factor applied to the (C+, C-) grid {0.1, 1, 10} of method 'newton'. The squared-hinge loss sums over the training rows, so the same C regularises less the more rows there are.");
    defaults_.setMinFloat("c_scale", 1e-9);
    defaults_.setValue("decoy_mode", "single", "'single': one decoy database, RESET coin per decoy key; 'two': two decoy databases (decoy_set 1 = training, 2 = estimating).");
    defaults_.setValidStrings("decoy_mode", {"single", "two"});
    defaultsToParam_();
  }

  void PSMRescorer::parallelSortDesc(std::vector<Pair>& v, int threads)
  {
    const std::size_t n = v.size();
    const std::size_t p = static_cast<std::size_t>(std::max(1, threads));
    if (p == 1 || n < (1u << 16)) { std::sort(v.begin(), v.end(), before); return; }
    std::vector<std::size_t> lo(p + 1);
    for (std::size_t j = 0; j <= p; ++j) lo[j] = n * j / p;
#pragma omp parallel for num_threads(threads) schedule(static, 1)
    for (std::size_t j = 0; j < p; ++j) std::sort(v.begin() + lo[j], v.begin() + lo[j + 1], before);
    // regular sampling -> p-1 splitters
    const std::size_t s = 32;
    std::vector<Pair> sample;
    sample.reserve(p * s);
    for (std::size_t j = 0; j < p; ++j)
      for (std::size_t k = 0; k < s; ++k)
      {
        const std::size_t len = lo[j + 1] - lo[j];
        if (len) sample.push_back(v[lo[j] + len * k / s]);
      }
    std::sort(sample.begin(), sample.end(), before);
    std::vector<Pair> split(p - 1);
    for (std::size_t t = 1; t < p; ++t) split[t - 1] = sample[sample.size() * t / p];
    // cut[j][t]: first position in chunk j that does not precede splitter t-1 (cut[j][0] = chunk begin)
    std::vector<std::vector<std::size_t>> cut(p, std::vector<std::size_t>(p + 1));
#pragma omp parallel for num_threads(threads)
    for (std::size_t j = 0; j < p; ++j)
    {
      cut[j][0] = lo[j];
      cut[j][p] = lo[j + 1];
      for (std::size_t t = 1; t < p; ++t)
        cut[j][t] = static_cast<std::size_t>(std::lower_bound(v.begin() + lo[j], v.begin() + lo[j + 1], split[t - 1], before) - v.begin());
    }
    std::vector<std::size_t> out_at(p + 1, 0);
    for (std::size_t t = 0; t < p; ++t)
    {
      out_at[t + 1] = out_at[t];
      for (std::size_t j = 0; j < p; ++j) out_at[t + 1] += cut[j][t + 1] - cut[j][t];
    }
    std::vector<Pair> out(n);
#pragma omp parallel for num_threads(threads) schedule(dynamic, 1)
    for (std::size_t t = 0; t < p; ++t)
    {
      using Head = std::pair<Pair, std::size_t>;  // value, chunk
      auto worse = [](const Head& a, const Head& b) { return before(b.first, a.first); };
      std::priority_queue<Head, std::vector<Head>, decltype(worse)> heap(worse);
      std::vector<std::size_t> pos(p);
      for (std::size_t j = 0; j < p; ++j)
      {
        pos[j] = cut[j][t];
        if (pos[j] < cut[j][t + 1]) heap.push({v[pos[j]], j});
      }
      std::size_t o = out_at[t];
      while (!heap.empty())
      {
        const auto [val, j] = heap.top();
        heap.pop();
        out[o++] = val;
        if (++pos[j] < cut[j][t + 1]) heap.push({v[pos[j]], j});
      }
    }
    v.swap(out);
  }

  std::vector<double> PSMRescorer::qValues(const std::vector<double>& score, const std::vector<char>& is_target,
                                           const std::vector<char>& use, double factor, int threads, double alpha,
                                           std::size_t* accepted)
  {
    if (is_target.size() != score.size() || use.size() != score.size() || score.size() >= (std::size_t(1) << 32))
      throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "qValues: inconsistent or oversized input", std::to_string(score.size()));
    std::vector<Pair> order;
    order.reserve(score.size());
    for (std::size_t i = 0; i < score.size(); ++i)
      if (use[i])
      {
        if (!std::isfinite(score[i])) throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "qValues: non-finite score", std::to_string(i));
        order.emplace_back(score[i], static_cast<std::uint32_t>(i));
      }
    parallelSortDesc(order, threads);
    // FDP is evaluated only at the end of each block of equal scores: a threshold cannot split a tie
    std::vector<double> fdp(order.size());
    double t = 0, dcy = 0;
    for (std::size_t k = 0; k < order.size();)
    {
      std::size_t e = k;
      while (e < order.size() && order[e].first == order[k].first) { (is_target[order[e].second] ? t : dcy) += 1; ++e; }
      const double f = factor * (dcy + 1) / std::max(t, 1.0);
      for (std::size_t m = k; m < e; ++m) fdp[m] = f;
      k = e;
    }
    std::vector<double> q(score.size(), 1.0);
    double run = 1.0;
    std::size_t acc = 0;
    for (std::size_t k = order.size(); k-- > 0;)
    {
      run = std::min(run, fdp[k]);
      q[order[k].second] = run;
      if (run <= alpha && is_target[order[k].second]) ++acc;
    }
    if (accepted) *accepted = acc;
    return q;
  }

  RescoreOutput PSMRescorer::rescore(const RescoreInput& in, const std::vector<std::uint64_t>& coin_keys,
                                     const std::vector<char>& decoy_set, const std::vector<std::uint32_t>& groups,
                                     const std::vector<double>& search_score)
  {
    const auto t0 = Clock::now();
    const int threads = std::max(1, static_cast<int>(param_.getValue("num_threads")));
    const std::size_t cap = static_cast<std::size_t>(static_cast<int>(param_.getValue("train_cap")));
    const int iterations = param_.getValue("iterations");
    const double train_fdr = param_.getValue("train_fdr");
    const std::uint64_t salt = mix(static_cast<std::uint64_t>(static_cast<int>(param_.getValue("seed"))));
    const bool use_lda = param_.getValue("method").toString() == "lda";
    const double c_scale = param_.getValue("c_scale");
    const bool two = param_.getValue("decoy_mode").toString() == "two";
    const double train_factor = two ? 2.0 : 3.0, final_factor = two ? 1.0 : 2.0;  // c/(1-c): 2/3 resp. 1/2 and 3/4 resp. 2/3
    const std::size_t n = in.features.size();
    if (two && decoy_set.size() != n)
      throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "decoy_mode 'two' needs decoy_set for every row", std::to_string(n));
    if (n == 0 || in.is_decoy.size() != n || n >= (std::size_t(1) << 32))
      throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "inconsistent rescoring input", std::to_string(n));
    if (!two && coin_keys.size() != n)
      throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "decoy_mode 'single' needs a coin key (peptide stem) per row", std::to_string(coin_keys.size()));
    if (!in.cv_group_keys.empty() && in.cv_group_keys.size() != n)
      throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "cv_group_keys must be empty or one per row", std::to_string(in.cv_group_keys.size()));
    const bool dynamic = !groups.empty();
    if (dynamic && (groups.size() != n || search_score.size() != n))
      throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "groups and search_score need one entry per row", std::to_string(groups.size()));
    // contiguous groups (all candidate hits of one spectrum next to each other): [gstart[g], gstart[g+1])
    std::vector<std::size_t> gstart;
    if (dynamic)
    {
      gstart.push_back(0);
      for (std::size_t i = 1; i < n; ++i)
      {
        if (groups[i] < groups[i - 1])
          throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "groups must be contiguous and non-decreasing", std::to_string(i));
        if (groups[i] != groups[i - 1]) gstart.push_back(i);
      }
      gstart.push_back(n);
    }
    const std::size_t d = in.features[0].size();
    {
      std::size_t sets[3] = {0, 0, 0};
      for (std::size_t i = 0; i < n; ++i)
      {
        if (in.features[i].size() != d)
          throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "feature rows of different width", std::to_string(i));
        for (double v : in.features[i])
          if (!std::isfinite(v)) throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "non-finite feature value", std::to_string(i));
        if (two && in.is_decoy[i])
        {
          if (decoy_set[i] != 1 && decoy_set[i] != 2)
            throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "decoy_set must be 1 or 2 for decoys", std::to_string(i));
          ++sets[int(decoy_set[i])];
        }
      }
      // with two decoy databases both sets win about equally often; a lopsided split means the database was not built for it
      if (two && (sets[1] == 0 || sets[2] == 0 || std::min(sets[1], sets[2]) * 3 < std::max(sets[1], sets[2])))
        throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
                                      "decoy_mode 'two' needs two decoy databases of equal size (found decoy winners " +
                                      std::to_string(sets[1]) + " / " + std::to_string(sets[2]) + ")", "");
    }

    // ---- standardize (parallel column moments), pack row-major with bias column
    Matrix X;
    X.n = n;
    X.d = d + 1;
    X.x.resize(n * X.d);
    std::vector<double> mean(d, 0), sd(d, 0);
#pragma omp parallel for num_threads(threads)
    for (std::size_t j = 0; j < d; ++j)  // two-pass (centred) moments
    {
      double s = 0;
      for (std::size_t i = 0; i < n; ++i) s += in.features[i][j];
      mean[j] = s / n;
      double ss = 0;
      for (std::size_t i = 0; i < n; ++i) { const double c = in.features[i][j] - mean[j]; ss += c * c; }
      sd[j] = std::sqrt(ss / n);
    }
#pragma omp parallel for num_threads(threads)
    for (std::size_t i = 0; i < n; ++i)
    {
      double* r = X.x.data() + i * X.d;
      for (std::size_t j = 0; j < d; ++j) r[j] = sd[j] > 0 ? (in.features[i][j] - mean[j]) / sd[j] : 0.0;  // constant column -> 0
      r[d] = 1.0;
    }

    // ---- decoy coin (one per key), training pool cap, folds
    std::vector<char> train_dec(n, 0), is_target(n), pool_neg(n, 0);
    // winner of each group's target-decoy competition: by the search score (dynamic mode), else every row
    auto winners_by = [&](const std::vector<double>& s, std::uint64_t tie_salt) {
      std::vector<char> win(n, dynamic ? 0 : 1);
      if (!dynamic) return win;
      const std::size_t ng = gstart.size() - 1;
#pragma omp parallel for num_threads(threads) schedule(static)
      for (std::size_t g = 0; g < ng; ++g)
      {
        std::size_t b = gstart[g], tied = 1;
        for (std::size_t i = gstart[g] + 1; i < gstart[g + 1]; ++i)
        {
          if (s[i] > s[b]) { b = i; tied = 1; }
          else if (s[i] == s[b] && mix(tie_salt ^ i) % ++tied == 0) b = i;  // label-independent tie break
        }
        win[b] = 1;
      }
      return win;
    };
    const std::vector<char> win0 = winners_by(dynamic ? search_score : std::vector<double>(), salt + 11);
    std::size_t n_win = 0;
    for (char c : win0) n_win += c;
    std::vector<std::uint32_t> pool;
    const double keep = n_win > cap ? double(cap) / n_win : 1.0;
    for (std::size_t i = 0; i < n; ++i)
    {
      is_target[i] = !in.is_decoy[i];
      const std::uint64_t key = coin_keys.empty() ? std::uint64_t(i) : coin_keys[i];
      if (in.is_decoy[i]) train_dec[i] = two ? decoy_set[i] == 1 : (mix(salt ^ key) & 1) != 0;
      if (win0[i] && (keep >= 1.0 || double(mix(salt + 0x5bd1e995ULL + i) >> 11) * 0x1.0p-53 < keep)) pool.push_back(static_cast<std::uint32_t>(i));
    }
    training_rows_ = pool.size();
    std::vector<std::uint8_t> fold(n);
    for (std::size_t i = 0; i < n; ++i)  // folds by CV group if given (rows of one group share a fold), else by row
      fold[i] = static_cast<std::uint8_t>(mix(salt * 31 + (in.cv_group_keys.empty() ? std::uint64_t(i) : std::uint64_t(std::int64_t(in.cv_group_keys[i])))) % 3);
    // pool view used by the q-value helper: pseudo-targets are "targets", training decoys are "decoys"
    std::vector<char> pseudo(n), in_pool(n, 0);
    for (std::size_t i = 0; i < n; ++i) pseudo[i] = !train_dec[i];
    for (auto r : pool) in_pool[r] = 1;
    last_training_decoy_ = train_dec;
    timing_.prep = since(t0);

    // ---- initial direction: best single standardized feature (either sign) by training discoveries
    const auto t1 = Clock::now();
    std::vector<double> score(n, 0.0);
    {
      std::size_t best = 0;
      int best_j = 0, best_sign = 1;
      std::vector<double> col(n);
      for (std::size_t j = 0; j < d; ++j)
        for (int sign : {1, -1})
        {
          for (auto r : pool) col[r] = sign * X.row(r)[j];
          std::size_t acc = 0;
          qValues(col, pseudo, in_pool, train_factor, threads, train_fdr, &acc);
          if (acc > best) { best = acc; best_j = static_cast<int>(j); best_sign = sign; }
        }
      for (auto r : pool) score[r] = best_sign * X.row(r)[best_j];
    }

    static const double grid[3] = {0.1, 1.0, 10.0};
    Eigen::VectorXd w = Eigen::VectorXd::Zero(static_cast<Eigen::Index>(X.d));
    std::vector<signed char> y(n, 0);
    for (int it = 0; it < iterations; ++it)
    {
      // positives: pseudo-targets passing train_fdr against training decoys (factor 3)
      const std::vector<double> q = qValues(score, pseudo, in_pool, train_factor, threads, train_fdr);
      std::vector<std::uint32_t> use;
      for (auto r : pool)
      {
        y[r] = train_dec[r] ? -1 : (q[r] <= train_fdr ? 1 : 0);
        if (y[r]) use.push_back(r);
      }
      std::size_t n_pos = 0;
      for (auto r : use) n_pos += y[r] > 0;
      if (n_pos == 0 || n_pos == use.size())
        throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "no training positives or negatives", std::to_string(n_pos));
      if (use_lda)
      {
        w = lda(X, use, y, threads);
      }
      else
      {
        std::vector<std::uint32_t> train[3], held[3];
        for (auto r : use) for (int k = 0; k < 3; ++k) (fold[r] == k ? held[k] : train[k]).push_back(r);
        std::vector<Eigen::VectorXd> wt(27);
        std::vector<std::size_t> found(27, 0);
#pragma omp parallel for num_threads(threads) schedule(dynamic, 1)
        for (int task = 0; task < 27; ++task)
        {
          const int g = task / 3, k = task % 3;
          wt[task] = newton(X, train[k], y, c_scale * grid[g / 3], c_scale * grid[g % 3], w);
          const std::size_t m = held[k].size();  // held-out fold, compact
          std::vector<double> s(m);
          std::vector<char> h(m, 1), pos(m);
          for (std::size_t a = 0; a < m; ++a) { s[a] = dot(X.row(held[k][a]), wt[task]); pos[a] = y[held[k][a]] > 0; }
          qValues(s, pos, h, train_factor, 1, train_fdr, &found[task]);
        }
        int best = 0;
        std::size_t best_found = 0;
        for (int g = 0; g < 9; ++g)
        {
          const std::size_t f = found[3 * g] + found[3 * g + 1] + found[3 * g + 2];
          if (f > best_found) { best_found = f; best = g; }
        }
        w = (wt[3 * best] + wt[3 * best + 1] + wt[3 * best + 2]) / 3.0;
      }
#pragma omp parallel for num_threads(threads)
      for (std::size_t k = 0; k < pool.size(); ++k) score[pool[k]] = dot(X.row(pool[k]), w);
    }
    timing_.train = since(t1);

    // ---- score every row, RESET estimate on targets + estimating decoys
    const auto t2 = Clock::now();
    RescoreOutput out;
    out.scores.resize(n);
#pragma omp parallel for num_threads(threads)
    for (std::size_t i = 0; i < n; ++i) out.scores[i] = dot(X.row(i), w);
    timing_.score = since(t2);
    const auto t3 = Clock::now();
    // dynamic mode: re-run each spectrum's competition on the learned score; only its winner counts
    const std::vector<char> win1 = winners_by(out.scores, salt + 13);
    last_winner_ = win1;
    std::vector<char> estimating(n);
    for (std::size_t i = 0; i < n; ++i) estimating[i] = win1[i] && !train_dec[i];
    out.q_values = qValues(out.scores, is_target, estimating, final_factor, threads, param_.getValue("test_fdr"), &accepted_);
    timing_.qvalue = since(t3);
    return out;
  }

#ifndef PSMRESCORER_CORE_ONLY
  PSMRescorer::RunResult PSMRescorer::rescoreRun(std::vector<ProteinIdentification>& protein_ids,
                                                 PeptideIdentificationList& peptide_ids,
                                                 const std::string& second_decoy_prefix)
  {
    RunResult res;
    if (protein_ids.empty()) { res.skipped_reason = "No search run to rescore."; return res; }
    std::vector<std::string> extra;
    const auto& sp = protein_ids.front().getSearchParameters();
    const std::uint64_t tie_salt = mix(static_cast<std::uint64_t>(static_cast<int>(param_.getValue("seed"))) + 77);
    const std::vector<std::string> excluded = param_.getValue("exclude_feature_prefixes");
    // isotope_error follows report:isotope_error_convention: observed_minus_theoretical (default) is subtracted
    const double iso_sign = (sp.metaValueExists("isotope_error_convention") &&
                             sp.getMetaValue("isotope_error_convention").toString() == "theoretical_minus_observed") ? 1.0 : -1.0;
    const bool tryptic = sp.digestion_enzyme.getName().find("Trypsin") != std::string::npos;
    if (sp.metaValueExists("extra_features"))
    {
      const std::string all = sp.getMetaValue("extra_features").toString();
      for (std::size_t a = 0; a <= all.size();)
      {
        const std::size_t b = std::min(all.find(',', a), all.size());
        if (b > a)
        {
          const std::string name = all.substr(a, b - a);
          bool skip = false;
          for (const auto& e : excluded) skip = skip || name.rfind(e, 0) == 0;
          if (!skip) extra.push_back(name);
        }
        a = b + 1;
      }
    }
    else
    {
      extra.emplace_back("score");
    }
    RescoreInput in;
    std::vector<std::uint64_t> keys;
    std::vector<char> decoy_set;
    std::vector<std::size_t> winner(peptide_ids.size(), std::size_t(-1));
    std::size_t n_decoy = 0;
    for (std::size_t p = 0; p < peptide_ids.size(); ++p)
    {
      const auto& pid = peptide_ids[p];
      const auto& hits = pid.getHits();
      if (hits.empty()) continue;
      // target-decoy competition on the search score; ties broken by a label-independent random choice
      std::size_t b = 0, n_tied = 1;
      for (std::size_t h = 1; h < hits.size(); ++h)
      {
        const double s = hits[h].getScore(), sb = hits[b].getScore();
        if (pid.isHigherScoreBetter() ? s > sb : s < sb) { b = h; n_tied = 1; }
        else if (s == sb && mix(tie_salt ^ (p * 1315423911ULL + h)) % ++n_tied == 0) b = h;
      }
      winner[p] = b;
      const PeptideHit& hit = hits[b];
      const int z = hit.getCharge();
      const double calc = hit.getSequence().getMonoWeight();
      const double obs = (pid.getMZ() - Constants::PROTON_MASS_U) * z;
      const double iso = hit.metaValueExists("isotope_error") ? double(hit.getMetaValue("isotope_error")) : 0.0;
      const double dm = (obs + iso_sign * iso * Constants::C13C12_MASSDIFF_U - calc) / std::max(z, 1);
      const std::string plain = hit.getSequence().toUnmodifiedString();
      double enz_n = 0, enz_c = 0;
      if (tryptic && !hit.getPeptideEvidences().empty() && !plain.empty())  // enzN/enzC for trypsin only, else 0
      {
        const auto& ev = hit.getPeptideEvidences()[0];
        const char bf = ev.getAABefore(), af = ev.getAAAfter();
        enz_n = (bf == '[' || bf == '-' || ((bf == 'K' || bf == 'R') && plain.front() != 'P')) ? 1 : 0;
        enz_c = (af == ']' || af == '-' || ((plain.back() == 'K' || plain.back() == 'R') && af != 'P')) ? 1 : 0;
      }
      std::vector<double> f = {double(z == 2), double(z == 3), double(z == 4), double(z >= 5),
                               double(plain.size()), obs, dm, std::abs(dm), enz_n, enz_c};
      for (const auto& e : extra) f.push_back(e == "score" ? hit.getScore() : (hit.metaValueExists(e) ? double(hit.getMetaValue(e)) : 0.0));
      in.features.push_back(std::move(f));
      in.cv_group_keys.push_back(static_cast<int>(p));
      const bool decoy = hit.isDecoy();
      n_decoy += decoy;
      in.is_decoy.push_back(decoy);
      keys.push_back(std::hash<std::string>{}(plain));
      char set = 0;
      if (decoy)
      {
        set = 1;
        for (const auto& ev : hit.getPeptideEvidences())
          if (ev.getProteinAccession().rfind(second_decoy_prefix, 0) == 0) { set = 2; break; }
      }
      decoy_set.push_back(set);
    }
    res.rows = in.features.size();
    if (res.rows < 100) { res.skipped_reason = "Only " + std::to_string(res.rows) + " PSMs, rescoring needs at least 100."; return res; }
    if (n_decoy < 50) { res.skipped_reason = "Too few decoy PSMs (" + std::to_string(n_decoy) + ") for target-decoy rescoring."; return res; }
    RescoreOutput out;
    try { out = rescore(in, keys, decoy_set); }
    catch (const Exception::BaseException& e) { res.skipped_reason = std::string("PSMRescorer failed: ") + e.what(); return res; }
    std::size_t row = 0;
    for (std::size_t p = 0; p < peptide_ids.size(); ++p)
    {
      if (winner[p] == std::size_t(-1)) continue;
      auto& pid = peptide_ids[p];
      auto& hits = pid.getHits();
      PeptideHit hit = std::move(hits[winner[p]]);
      hit.setMetaValue("PSMRescorer_score", out.scores[row]);
      hit.setMetaValue("PSMRescorer_q", out.q_values[row]);
      if (last_training_decoy_[row]) hit.setMetaValue("PSMRescorer_training_decoy", "true");
      hit.setScore(out.q_values[row]);
      hits.assign(1, std::move(hit));
      pid.setScoreType("q-value");
      pid.setHigherScoreBetter(false);
      ++row;
    }
    for (ProteinIdentification& run : protein_ids)
    {
      run.setSearchEngine("PSMRescorer");
      auto run_sp = run.getSearchParameters();
      run_sp.setMetaValue("PSMRescorer:method", param_.getValue("method").toString());
      run_sp.setMetaValue("PSMRescorer:decoy_mode", param_.getValue("decoy_mode").toString());
      run_sp.setMetaValue("PSMRescorer:train_cap", static_cast<int>(param_.getValue("train_cap")));
      run_sp.setMetaValue("PSMRescorer:seed", static_cast<int>(param_.getValue("seed")));
      run.setSearchParameters(run_sp);
    }
    res.applied = true;
    return res;
  }
#endif
}
