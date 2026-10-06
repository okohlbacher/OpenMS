// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// --------------------------------------------------------------------------
// $Maintainer:  $
// $Authors: Oliver Kohlbacher $
// --------------------------------------------------------------------------

#include <OpenMS/CONCEPT/ClassTest.h>
#include <OpenMS/test_config.h>

///////////////////////////
#include <OpenMS/ANALYSIS/ID/OMPExceptionGuard.h>
///////////////////////////

#include <OpenMS/CONCEPT/Exception.h>
#include <OpenMS/CONCEPT/Types.h>

#include <atomic>
#include <stdexcept>
#include <string>

#ifdef _OPENMP
#include <omp.h>
#endif

using namespace OpenMS;
using namespace OpenMS::Internal;
using namespace std;

START_TEST(OMPExceptionGuard, "$Id$")

/////////////////////////////////////////////////////////////
/////////////////////////////////////////////////////////////

START_SECTION(OMPExceptionGuard())
{
  OMPExceptionGuard guard;
  TEST_EQUAL(guard.failed(), false)
  guard.rethrow(); // nothing captured: no-op
  TEST_EQUAL(guard.failed(), false)
}
END_SECTION

START_SECTION(void run(F&& f) noexcept)
{
  // a region without exceptions does all its work and rethrow() is a no-op
  OMPExceptionGuard guard;
  const SignedSize n = 1000;
  std::atomic<SignedSize> done{0};
#pragma omp parallel for num_threads(4)
  for (SignedSize i = 0; i < n; ++i)
  {
    guard.run([&] { ++done; });
  }
  guard.rethrow();
  TEST_EQUAL(done.load(), n)
  TEST_EQUAL(guard.failed(), false)

  // run() catches, keeps the first exception and skips the work after it
  OMPExceptionGuard serial;
  int calls = 0;
  serial.run([&] { ++calls; throw std::runtime_error("first"); });
  serial.run([&] { ++calls; throw std::runtime_error("second"); });
  TEST_EQUAL(calls, 1)
  TEST_EQUAL(serial.failed(), true)
  std::string what;
  try
  {
    serial.rethrow();
  }
  catch (const std::runtime_error& e)
  {
    what = e.what();
  }
  TEST_EQUAL(what, "first")
}
END_SECTION

START_SECTION(void capture() noexcept)
{
  // every iteration of a parallel loop throws: one exception reaches the caller, no std::terminate()
  OMPExceptionGuard guard;
  const SignedSize n = 256;
  std::atomic<SignedSize> thrown{0};
#pragma omp parallel for num_threads(8) schedule(dynamic, 1)
  for (SignedSize i = 0; i < n; ++i)
  {
    if (guard.failed()) continue;
    try
    {
      ++thrown;
      throw std::runtime_error("iteration " + std::to_string(i));
    }
    catch (...)
    {
      guard.capture();
    }
  }
  TEST_EQUAL(guard.failed(), true)
  TEST_EQUAL(thrown.load() >= 1, true)
  TEST_EQUAL(thrown.load() <= n, true)
  std::string what;
  try
  {
    guard.rethrow();
  }
  catch (const std::runtime_error& e)
  {
    what = e.what();
  }
  TEST_EQUAL(what.rfind("iteration ", 0), std::string::size_type(0))
  // the guard keeps the exception: a second rethrow() throws it again
  TEST_EXCEPTION(std::runtime_error, guard.rethrow())

  // the dynamic type of an OpenMS exception survives (only one iteration constructs one: the constructors write the
  // process-wide GlobalExceptionHandler and are not thread-safe)
  OMPExceptionGuard typed;
#pragma omp parallel for num_threads(4)
  for (SignedSize i = 0; i < 64; ++i)
  {
    if (typed.failed()) continue;
    try
    {
      if (i == 17) throw Exception::InvalidParameter(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "tolerance must be > 0");
    }
    catch (...)
    {
      typed.capture();
    }
  }
  TEST_EXCEPTION(Exception::InvalidParameter, typed.rethrow())

  // a parallel region with a worksharing loop: every thread throws in the loop and the region still completes
  // (the threads reach the implicit barrier); a run() inside a critical section releases the lock. The critical
  // section uses a guard of its own: with the loop's guard, failed() is already true there and run() would skip
  // the throwing work.
  OMPExceptionGuard region;
  OMPExceptionGuard in_critical;
  std::atomic<int> after_loop{0};
  int entered_critical_work = 0; // only changed inside the critical section
  int threads = 1;
#pragma omp parallel num_threads(6)
  {
#ifdef _OPENMP
#pragma omp single
    threads = omp_get_num_threads();
#endif
#pragma omp for schedule(static, 1)
    for (SignedSize i = 0; i < 6; ++i)
    {
      try
      {
        throw std::logic_error("thread work");
      }
      catch (...)
      {
        region.capture();
      }
    }
#pragma omp critical (OMPExceptionGuard_test)
    in_critical.run([&entered_critical_work] { ++entered_critical_work; throw std::logic_error("inside critical"); });
    ++after_loop;
  }
  TEST_EQUAL(after_loop.load(), threads) // every thread left the critical section: the lock was released
  TEST_EQUAL(entered_critical_work, 1)   // the first thread ran the work and threw; the others skipped it
  TEST_EXCEPTION_WITH_MESSAGE(std::logic_error, region.rethrow(), "thread work")
  TEST_EXCEPTION_WITH_MESSAGE(std::logic_error, in_critical.rethrow(), "inside critical")
}
END_SECTION

START_SECTION(bool failed() const noexcept)
{
  OMPExceptionGuard guard;
  TEST_EQUAL(guard.failed(), false)
  guard.run([] {});
  TEST_EQUAL(guard.failed(), false)
  guard.run([] { throw 42; }); // any type is carried
  TEST_EQUAL(guard.failed(), true)
  int value = 0;
  try
  {
    guard.rethrow();
  }
  catch (int v)
  {
    value = v;
  }
  TEST_EQUAL(value, 42)
}
END_SECTION

START_SECTION(void rethrow() const)
{
  NOT_TESTABLE // tested above
}
END_SECTION

/////////////////////////////////////////////////////////////
/////////////////////////////////////////////////////////////
END_TEST
