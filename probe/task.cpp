#include "common.h"
int main()
{
  std::atomic<long> sum{0};
#pragma omp parallel
#pragma omp single
  {
    for (long i = 0; i < 1000; ++i)
    {
#pragma omp task firstprivate(i) shared(sum)
      sum += i;
    }
#pragma omp taskwait
  }
  report("task", sum, 499500);
}
