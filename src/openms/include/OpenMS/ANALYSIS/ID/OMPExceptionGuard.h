// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// --------------------------------------------------------------------------
// $Maintainer:  $
// $Authors: Oliver Kohlbacher $
// --------------------------------------------------------------------------

#pragma once

#include <atomic>
#include <exception>
#include <utility>

namespace OpenMS
{
  namespace Internal
  {
    /**
      @brief Carries the first exception thrown inside an OpenMP parallel region out of it.

      An exception must not leave an OpenMP structured block: if it does, the program calls std::terminate().
      The guard catches what the work of a thread throws, keeps the first exception and lets the caller rethrow it
      on the encountering thread once the region has ended. After the first exception the remaining iterations are
      skipped (they would be discarded anyway), but every thread still reaches the barriers of the region.

      Used by ProSEAlgorithm and FragmentIndex (internal; not part of the public API).

      @code
      OMPExceptionGuard guard;
      #pragma omp parallel for
      for (SignedSize i = 0; i < n; ++i)
      {
        if (guard.failed()) continue;
        try
        {
          work(i);
        }
        catch (...)
        {
          guard.capture();
        }
      }
      guard.rethrow(); // no-op if nothing was thrown
      @endcode

      A short piece of work can be passed to run() instead. Use it also inside an @c omp @c critical section: an
      exception must not leave a critical section either (the lock would stay held).

      @note The guard does not make the construction of the exception itself thread-safe. OpenMS exceptions set the
      process-wide GlobalExceptionHandler in their constructor, so two threads that construct one at the same time
      still race there.
    */
    class OMPExceptionGuard
    {
    public:
      OMPExceptionGuard() = default;
      OMPExceptionGuard(const OMPExceptionGuard&) = delete;
      OMPExceptionGuard& operator=(const OMPExceptionGuard&) = delete;

      /// True once some thread has captured an exception
      bool failed() const noexcept
      {
        return failed_.load(std::memory_order_acquire);
      }

      /// Keeps the exception being handled if it is the first one. Call it only from a catch handler.
      void capture() noexcept
      {
        bool expected = false;
        // only the first thread to fail writes first_; rethrow() reads it after the region (a barrier) has ended
        if (failed_.compare_exchange_strong(expected, true, std::memory_order_acq_rel))
        {
          first_ = std::current_exception();
        }
      }

      /// Calls f() unless an exception was captured before; captures what f() throws
      template<typename F>
      void run(F&& f) noexcept
      {
        if (failed()) return;
        try
        {
          std::forward<F>(f)();
        }
        catch (...)
        {
          capture();
        }
      }

      /// Rethrows the first captured exception, if any. Call it outside the parallel region, after it has ended.
      void rethrow() const
      {
        if (failed() && first_) std::rethrow_exception(first_);
      }

    private:
      std::atomic<bool> failed_{false};
      std::exception_ptr first_;
    };
  } // namespace Internal
} // namespace OpenMS
