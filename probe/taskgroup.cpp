#include "common.h"
int main()
{
  std::atomic<long> sum{0};
#pragma omp parallel
#pragma omp single
  {
#pragma omp taskgroup
    {
      for (long i = 0; i < 100; ++i)
      {
#pragma omp task firstprivate(i) shared(sum)
        {
#pragma omp task firstprivate(i) shared(sum)
          sum += i;
        }
      }
    }
    report("taskgroup", sum, 4950);
  }
}
