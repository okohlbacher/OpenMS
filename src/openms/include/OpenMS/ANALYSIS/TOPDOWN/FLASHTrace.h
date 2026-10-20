// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// Private performance experiment: opt-in phase tracer and runtime switches for FLASHDeconv.
// FD_TRACE=<file> records one line per scope (tid name wall0 wall1 cpu0 cpu1 a b).
// FD_OPT=<comma list> enables experimental code paths (see FLASHTrace::opt()).
#pragma once

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <mutex>
#include <string>
#include <vector>
#include <sys/syscall.h>
#include <unistd.h>

namespace OpenMS::FLASHTrace
{
  struct Event
  {
    const char* name;
    double w0, w1, c0, c1;
    int64_t a, b;
  };

  inline double wallNow()
  {
    timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
  }
  inline double cpuNow()
  {
    timespec ts;
    clock_gettime(CLOCK_THREAD_CPUTIME_ID, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
  }

  inline const char* tracePath()
  {
    static const char* p = std::getenv("FD_TRACE");
    return p;
  }
  inline bool enabled() { return tracePath() != nullptr; }

  /// FD_OPT feature switch, e.g. FD_OPT=pool,lpt
  inline bool opt(const char* name)
  {
    static const std::string s = [] { const char* e = std::getenv("FD_OPT"); return std::string(",") + (e ? e : "") + ","; }();
    return s.find(std::string(",") + name + ",") != std::string::npos;
  }

  struct Registry
  {
    std::mutex m;
    std::vector<std::pair<long, std::vector<Event>*>> bufs;
    bool dumped = false;
    void dump()
    {
      std::lock_guard<std::mutex> g(m);
      if (dumped || ! enabled()) return;
      dumped = true;
      FILE* f = std::fopen(tracePath(), "a"); // executable and library each own a registry
      if (! f) return;
      for (auto& [tid, v] : bufs)
        for (auto& e : *v)
          std::fprintf(f, "%ld\t%s\t%.6f\t%.6f\t%.6f\t%.6f\t%lld\t%lld\n", tid, e.name, e.w0, e.w1, e.c0, e.c1, (long long)e.a, (long long)e.b);
      std::fclose(f);
    }
    ~Registry() { dump(); }
  };
  inline Registry& registry()
  {
    static Registry r;
    return r;
  }

  inline std::vector<Event>& buffer()
  {
    thread_local std::vector<Event>* b = [] {
      auto* v = new std::vector<Event>(); // ponytail: leaked on purpose, OpenMP threads outlive main
      v->reserve(1 << 14);
      std::lock_guard<std::mutex> g(registry().m);
      registry().bufs.emplace_back((long)syscall(SYS_gettid), v);
      return v;
    }();
    return *b;
  }

  struct Scope
  {
    const char* name;
    double w0 = 0, c0 = 0;
    int64_t a, b;
    explicit Scope(const char* n, int64_t a_ = 0, int64_t b_ = 0) : name(n), a(a_), b(b_)
    {
      if (enabled())
      {
        w0 = wallNow();
        c0 = cpuNow();
      }
    }
    ~Scope()
    {
      if (enabled()) buffer().push_back({name, w0, wallNow(), c0, cpuNow(), a, b});
    }
    Scope(const Scope&) = delete;
    Scope& operator=(const Scope&) = delete;
  };
} // namespace OpenMS::FLASHTrace
