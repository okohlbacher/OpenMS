#include "common.h"
int main()
{
  std::atomic<long> sum{0};
#pragma omp parallel
#pragma omp single
  {
#pragma omp taskloop grainsize(16) shared(sum)
    for (long i = 0; i < 1000; ++i) sum += i;
#pragma omp taskloop num_tasks(8) shared(sum) if(true)
    for (long i = 0; i < 1000; ++i) sum += i;
  }
  report("taskloop", sum, 999000);
}
