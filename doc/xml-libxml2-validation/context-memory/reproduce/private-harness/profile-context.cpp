#include <OpenMS/KERNEL/OnDiscMSExperiment.h>
#include <OpenMS/FORMAT/MzMLFile.h>
#include <OpenMS/KERNEL/MSExperiment.h>
#include <malloc.h>
#include <unistd.h>
#include <barrier>
#include <fstream>
#include <iostream>
#include <memory>
#include <thread>
#include <vector>

void sample(const char* phase)
{
  const auto m = mallinfo2();
  std::ifstream input("/proc/self/statm");
  size_t total = 0, resident = 0;
  input >> total >> resident;
  std::cout << "{\"phase\":\"" << phase << "\",\"resident_bytes\":" << resident * static_cast<size_t>(sysconf(_SC_PAGESIZE))
            << ",\"arena_bytes\":" << m.arena << ",\"in_use_bytes\":" << m.uordblks
            << ",\"free_arena_bytes\":" << m.fordblks << ",\"mmap_bytes\":" << m.hblkhd << "}\n";
}
int main(int argc, char** argv)
{
  if (argc != 3 && argc != 4) { return 2; }
  OpenMS::MzMLFile warmup;
  OpenMS::MSExperiment empty;
  std::string buffer;
  warmup.storeBuffer(buffer, empty);
  warmup.loadBuffer(buffer, empty);
  const size_t n = std::stoul(argv[2]);
  std::vector<std::shared_ptr<OpenMS::OnDiscMSExperiment>> contexts(n);
  std::vector<std::jthread> threads;
  std::barrier start(static_cast<std::ptrdiff_t>(n + 1));
  sample("before");
  for (size_t i = 0; i < n; ++i)
  {
    threads.emplace_back([&, i]
    {
      start.arrive_and_wait();
      auto context = std::make_shared<OpenMS::OnDiscMSExperiment>();
      if (!context->openFile(argv[1], true)) { std::terminate(); }
      contexts[i] = std::move(context);
    });
  }
  start.arrive_and_wait();
  threads.clear();
  sample("contexts_retained");
  // Diagnostic only: this is never called by OpenMS or timed benchmarks.
  if (argc == 3)
  {
    malloc_trim(0);
    sample("diagnostic_trim");
  }
  contexts.clear();
  sample("contexts_destroyed");
}
