#include <cstdio>
#include <omp.h>
#include <atomic>
static void report(const char* what, long got, long want)
{
  std::printf("%-10s %s (got %ld, want %ld, threads %d)\n", what, got == want ? "OK" : "WRONG", got, want, omp_get_max_threads());
}
