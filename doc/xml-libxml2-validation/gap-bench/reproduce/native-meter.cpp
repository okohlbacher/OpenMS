// Fork only after the small native supervisor has replaced Python's address space.
// The child therefore inherits a small RSS floor; wait4 reports the tool's peak.
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <fcntl.h>
#include <fstream>
#include <string>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>
int main(int argc, char** argv)
{
  if (argc == 3 && std::string(argv[1]) == "--residency")
  {
    const int fd = open(argv[2], O_RDONLY);
    struct stat st {};
    if (fd < 0 || fstat(fd, &st) != 0 || st.st_size == 0) return 2;
    const auto page = sysconf(_SC_PAGESIZE);
    const auto pages = (st.st_size + page - 1) / page;
    void* address = mmap(nullptr, st.st_size, PROT_NONE, MAP_SHARED, fd, 0);
    if (address == MAP_FAILED) return 2;
    std::vector<unsigned char> resident(pages);
    if (mincore(address, st.st_size, resident.data()) != 0) return 2;
    long long bytes = 0;
    for (long long i = 0; i < pages; ++i)
      if (resident[i] & 1) bytes += std::min<long long>(page, st.st_size - i * page);
    munmap(address, st.st_size);
    close(fd);
    std::printf("{\"resident_file_bytes\":%lld,\"file_bytes\":%lld}\n", bytes, (long long)st.st_size);
    return 0;
  }
  if (argc < 4) return 2;
  const auto begin = std::chrono::steady_clock::now();
  const auto child = fork();
  if (child < 0) return 125;
  if (child == 0)
  {
    execv(argv[3], argv + 3);
    std::perror("execv");
    _exit(127);
  }
  {
    std::ofstream f(argv[1]);
    f << child << '\n';
  }
  int status = 0;
  struct rusage usage {};
  while (wait4(child, &status, 0, &usage) < 0)
  {
    if (errno != EINTR) return 125;
  }
  const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
  const int result = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
  {
    std::ofstream f(argv[2]);
    f << "{\"native_wait4_peak_rss_bytes\":" << usage.ru_maxrss * 1024LL
      << ",\"native_user_seconds\":" << usage.ru_utime.tv_sec + usage.ru_utime.tv_usec / 1e6
      << ",\"native_system_seconds\":" << usage.ru_stime.tv_sec + usage.ru_stime.tv_usec / 1e6 << ",\"native_process_seconds\":" << seconds
      << ",\"native_inblock\":" << usage.ru_inblock << ",\"native_majflt\":" << usage.ru_majflt << ",\"native_minflt\":" << usage.ru_minflt
      << ",\"native_nvcsw\":" << usage.ru_nvcsw << ",\"native_nivcsw\":" << usage.ru_nivcsw << ",\"native_exit_code\":" << result << "}\n";
    if (! f) return 125;
  }
  return result;
}
