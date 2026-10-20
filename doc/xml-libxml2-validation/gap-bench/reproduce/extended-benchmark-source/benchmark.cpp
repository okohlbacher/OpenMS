// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
// $Maintainer: Timo Sachsenberg $
// $Authors: OpenMS contributors $

#include <OpenMS/FORMAT/DATAACCESS/MSDataWritingConsumer.h>
#include <OpenMS/FORMAT/MzMLFile.h>
#include <OpenMS/INTERFACES/IMSDataConsumer.h>
#include <OpenMS/KERNEL/MSExperiment.h>
#include <OpenMS/KERNEL/OnDiscMSExperiment.h>

#include <barrier>
#include <omp.h>
#include <array>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <random>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#if defined(__APPLE__)
#include <mach-o/dyld.h>
#include <mach/mach.h>
#elif defined(__linux__)
#include <link.h>
#include <unistd.h>
#endif

namespace
{
  using Clock = std::chrono::steady_clock;
  bool audit_auxiliary = false;
  std::uint64_t nativePeakRssBytes()
  {
    std::ifstream status("/proc/self/status");
    std::string line;
    while (std::getline(status, line))
    {
      if (line.starts_with("VmHWM:")) { return std::stoull(line.substr(6)) * 1024; }
    }
    return 0;
  }

  std::uint64_t currentRssBytes()
  {
#if defined(__APPLE__)
    mach_task_basic_info_data_t info{};
    mach_msg_type_number_t count = MACH_TASK_BASIC_INFO_COUNT;
    if (task_info(mach_task_self(), MACH_TASK_BASIC_INFO,
                  reinterpret_cast<task_info_t>(&info), &count) == KERN_SUCCESS)
    {
      return info.resident_size;
    }
#elif defined(__linux__)
    std::ifstream statm("/proc/self/statm");
    std::uint64_t virtual_pages = 0, resident_pages = 0;
    if (statm >> virtual_pages >> resident_pages)
    {
      return resident_pages * static_cast<std::uint64_t>(sysconf(_SC_PAGESIZE));
    }
#endif
    return 0;
  }

  std::string loadedLibrary()
  {
    std::string result;
#if defined(__APPLE__)
    for (std::uint32_t i = 0; i < _dyld_image_count(); ++i)
    {
      const std::string path(_dyld_get_image_name(i));
      if (std::filesystem::path(path).filename() == "libOpenMS.dylib") { result = path; }
    }
#elif defined(__linux__)
    dl_iterate_phdr([](dl_phdr_info* info, std::size_t, void* data)
    {
      const std::string path(info->dlpi_name);
      if (std::filesystem::path(path).filename().string().starts_with("libOpenMS.so"))
      {
        *static_cast<std::string*>(data) = path;
      }
      return 0;
    }, &result);
#endif
    return result;
  }

  // Hash every decoded coordinate/intensity, independently of XML text formatting.
  struct Digest final : OpenMS::Interfaces::IMSDataConsumer
  {
    std::uint64_t hash = 14695981039346656037ULL;
    std::uint64_t spectra = 0, chromatograms = 0, points = 0;
    std::uint64_t aux_hash = 14695981039346656037ULL, im_values = 0, im_scalars = 0;
    std::array<std::uint64_t, 4> ms_levels{};
    void auxWord(std::uint64_t value)
    {
      for (unsigned i = 0; i < 8; ++i) { aux_hash = (aux_hash ^ ((value >> (8 * i)) & 255)) * 1099511628211ULL; }
    }
    void auxText(const std::string& text)
    {
      auxWord(text.size());
      for (unsigned char c : text) { aux_hash = (aux_hash ^ c) * 1099511628211ULL; }
    }


    void word(std::uint64_t value)
    {
      for (unsigned i = 0; i < 8; ++i)
      {
        hash = (hash ^ ((value >> (8 * i)) & 255)) * 1099511628211ULL;
      }
    }

    void text(const std::string& value)
    {
      word(value.size());
      for (const unsigned char character : value) { hash = (hash ^ character) * 1099511628211ULL; }
    }

    void consumeSpectrum(OpenMS::MSSpectrum& spectrum) override
    {
      ++spectra;
      if (audit_auxiliary)
      {
        const auto level = spectrum.getMSLevel();
        ++ms_levels[std::min<unsigned>(level, 3)];
        auxWord(level);
        auxWord(std::bit_cast<std::uint64_t>(spectrum.getRT()));
        auxWord(static_cast<std::uint64_t>(spectrum.getDriftTimeUnit()));
        auxWord(std::bit_cast<std::uint64_t>(spectrum.getDriftTime()));
        if (std::isfinite(spectrum.getDriftTime()) && spectrum.getDriftTime() >= 0) { ++im_scalars; }
        for (const auto& array : spectrum.getFloatDataArrays())
        {
          auxText(array.getName()); auxWord(array.size());
          for (float value : array) { auxWord(std::bit_cast<std::uint32_t>(value)); }
        }
        if (spectrum.containsIMData())
        {
          const auto index = spectrum.getIMData().first;
          const auto& array = spectrum.getFloatDataArrays().at(index);
          if (array.size() != spectrum.size()) { throw std::runtime_error("IM array length differs from peak count"); }
          for (float value : array) { if (std::isfinite(value)) { ++im_values; } }
        }
      }
      points += spectrum.size();
      word(1);
      word(spectrum.size());
      text(spectrum.getNativeID());
      for (const auto& peak : spectrum)
      {
        word(std::bit_cast<std::uint64_t>(peak.getMZ()));
        word(std::bit_cast<std::uint64_t>(static_cast<double>(peak.getIntensity())));
      }
    }

    void consumeChromatogram(OpenMS::MSChromatogram& chromatogram) override
    {
      ++chromatograms;
      points += chromatogram.size();
      word(2);
      word(chromatogram.size());
      text(chromatogram.getNativeID());
      for (const auto& peak : chromatogram)
      {
        word(std::bit_cast<std::uint64_t>(peak.getRT()));
        word(std::bit_cast<std::uint64_t>(static_cast<double>(peak.getIntensity())));
      }
    }

    void setExpectedSize(std::size_t, std::size_t) override {}
    void setExperimentalSettings(const OpenMS::ExperimentalSettings&) override {}
    bool operator==(const Digest& other) const
    {
      return hash == other.hash && spectra == other.spectra &&
        chromatograms == other.chromatograms && points == other.points && aux_hash == other.aux_hash && im_values == other.im_values && im_scalars == other.im_scalars && ms_levels == other.ms_levels;
    }
  };

  struct Result
  {
    Digest digest;
    // Keep opened contexts alive until every worker has completed.
    std::shared_ptr<OpenMS::OnDiscMSExperiment> retained_context;
    std::shared_ptr<OpenMS::MSExperiment> retained_experiment;
    double open_seconds = 0;
    double read_seconds = 0;
    std::size_t index_spectra = 0, index_chromatograms = 0;
  };

  Result run(const std::string& mode, const std::string& path, std::size_t queries)
  {
    Result result;
    const auto begin = Clock::now();
    if (mode == "stream")
    {
      OpenMS::MzMLFile().transform(path, &result.digest, true, true);
    }
    else if (mode == "load")
    {
      result.retained_experiment = std::make_shared<OpenMS::MSExperiment>();
      auto& experiment = *result.retained_experiment;
      OpenMS::MzMLFile().load(path, experiment);
      for (auto& spectrum : experiment) { result.digest.consumeSpectrum(spectrum); }
      for (auto& chromatogram : experiment.getChromatograms()) { result.digest.consumeChromatogram(chromatogram); }
    }
    else if (mode == "idle")
    {
      // Warmup and worker creation are common; no input/context allocations.
    }
    else if (mode == "contexts" || mode == "contexts-metadata")
    {
      result.retained_context = std::make_shared<OpenMS::OnDiscMSExperiment>();
      if (!result.retained_context->openFile(path, mode != "contexts-metadata"))
      {
        throw std::runtime_error("Input has no usable mzML index");
      }
      result.open_seconds = std::chrono::duration<double>(Clock::now() - begin).count();
      result.index_spectra = result.retained_context->getNrSpectra();
      result.index_chromatograms = result.retained_context->getNrChromatograms();
    }
    else if (mode == "indexed" || mode == "index-open" || mode == "indexed-metadata")
    {
      OpenMS::OnDiscMSExperiment experiment;
      if (!experiment.openFile(path, mode != "indexed-metadata"))
      {
        throw std::runtime_error("Input has no usable mzML index");
      }
      const auto opened = Clock::now();
      result.open_seconds = std::chrono::duration<double>(opened - begin).count();
      result.index_spectra = experiment.getNrSpectra();
      result.index_chromatograms = experiment.getNrChromatograms();
      if (mode == "indexed" || mode == "indexed-metadata")
      {
        if (experiment.getNrSpectra() == 0)
        {
          throw std::runtime_error("Indexed input has no spectra");
        }
        std::mt19937_64 random(20261019);
        for (std::size_t i = 0; i < queries; ++i)
        {
          auto spectrum = experiment.getSpectrum(random() % experiment.getNrSpectra());
          result.digest.consumeSpectrum(spectrum);
        }
      }
      result.read_seconds = std::chrono::duration<double>(Clock::now() - opened).count();
    }
    else
    {
      throw std::runtime_error("Expected stream, load, indexed[-metadata], index-open, contexts[-metadata], or idle");
    }
    if (mode == "stream" || mode == "load" || mode == "idle")
    {
      result.read_seconds = std::chrono::duration<double>(Clock::now() - begin).count();
    }
    return result;
  }

  void generate(const std::string& path, std::size_t count, std::size_t points, bool compressed)
  {
    OpenMS::PlainMSDataWritingConsumer writer(path);
    OpenMS::PeakFileOptions options;
    options.setCompression(compressed);
    options.setWriteIndex(true);
    writer.setOptions(options);
    writer.setExpectedSize(count, 1);
    writer.setExperimentalSettings(OpenMS::ExperimentalSettings());
    std::mt19937 random(20261019);
    for (std::size_t i = 0; i < count; ++i)
    {
      OpenMS::MSSpectrum spectrum;
      spectrum.setNativeID("scan=" + std::to_string(i + 1));
      spectrum.setRT(static_cast<double>(i) * 0.5);
      spectrum.setMSLevel(1);
      spectrum.setType(OpenMS::SpectrumSettings::SpectrumType::CENTROID);
      spectrum.setMetaValue("xml_poc_note", std::string("Unicode \xCE\xB2 & <escaped> \"value\""));
      spectrum.reserve(points);
      for (std::size_t p = 0; p < points; ++p)
      {
        OpenMS::Peak1D peak;
        peak.setMZ(100.0 + static_cast<double>(p) * 0.01 + static_cast<double>(i % 17) * 0.00001);
        peak.setIntensity(static_cast<float>(random() % 1000000) / 8.0F);
        spectrum.push_back(peak);
      }
      writer.consumeSpectrum(spectrum);
    }
    OpenMS::MSChromatogram chromatogram;
    chromatogram.setNativeID("TIC");
    for (std::size_t i = 0; i < count; ++i)
    {
      OpenMS::ChromatogramPeak peak;
      peak.setRT(static_cast<double>(i) * 0.5);
      peak.setIntensity(static_cast<float>(i % 101));
      chromatogram.push_back(peak);
    }
    writer.consumeChromatogram(chromatogram);
  }

  void verify(const std::string& path)
  {
    OpenMS::MSExperiment loaded;
    OpenMS::MzMLFile().load(path, loaded);
    Digest expected;
    for (auto& spectrum : loaded) { expected.consumeSpectrum(spectrum); }
    for (auto& chromatogram : loaded.getChromatograms()) { expected.consumeChromatogram(chromatogram); }
    const auto streamed = run("stream", path, 0).digest;
    OpenMS::OnDiscMSExperiment indexed;
    if (!indexed.openFile(path)) { throw std::runtime_error("Index verification failed"); }
    Digest actual;
    for (std::size_t i = 0; i < indexed.getNrSpectra(); ++i)
    {
      auto spectrum = indexed.getSpectrum(i);
      const auto& original = loaded.getSpectra().at(i);
      if (spectrum.getRT() != original.getRT() || spectrum.getMSLevel() != original.getMSLevel() ||
          spectrum.getFloatDataArrays() != original.getFloatDataArrays() ||
          spectrum.getIntegerDataArrays() != original.getIntegerDataArrays() ||
          spectrum.getStringDataArrays() != original.getStringDataArrays() ||
          spectrum.getMetaValue("xml_poc_note") != original.getMetaValue("xml_poc_note"))
      {
        throw std::runtime_error("Indexed spectrum metadata differ from full load");
      }
      actual.consumeSpectrum(spectrum);
    }
    for (std::size_t i = 0; i < indexed.getNrChromatograms(); ++i)
    {
      auto chromatogram = indexed.getChromatogram(i);
      actual.consumeChromatogram(chromatogram);
    }
    if (!(expected == streamed) || !(expected == actual))
    {
      throw std::runtime_error("Decoded data differ between load, streaming and indexed access");
    }
    std::cout << "{\"verified\":true,\"spectra\":" << expected.spectra
              << ",\"points\":" << expected.points << ",\"hash\":\"" << expected.hash << "\"}\n";
  }
}

int main(int argc, char** argv)
{
  std::cerr << "XML_BENCHMARK_MAIN_STARTED\n";
  try
  {
    if (argc < 3) { throw std::runtime_error("Usage: xml_parser_benchmark MODE FILE [WORKERS|SPECTRA] [QUERIES|POINTS] [ZLIB]"); }
    const std::string requested_mode(argv[1]), path(argv[2]);
    audit_auxiliary = requested_mode == "stream-audit";
    const std::string mode = audit_auxiliary ? "stream" : requested_mode;
    const std::size_t workers = argc > 3 ? std::stoull(argv[3]) : 1;
    const std::size_t queries = argc > 4 ? std::stoull(argv[4]) : 1000;
    if (workers == 0) { throw std::runtime_error("Worker/spectrum count must be positive"); }
    if (mode == "generate")
    {
      generate(path, workers, queries, argc > 5 && std::string(argv[5]) == "zlib");
      return 0;
    }
    if (mode == "verify") { verify(path); return 0; }

    // Warm shared initialization with one thread, then set each worker team explicitly.
    // This avoids retaining an unused N-thread main-thread team during fixed-work runs.
    const int requested_team = omp_get_max_threads();
    omp_set_num_threads(1);
    // Warm shared CV/parser initialization before independent worker jobs.
    OpenMS::MzMLFile warmup;
    OpenMS::MSExperiment empty;
    std::string warmup_xml;
    warmup.storeBuffer(warmup_xml, empty);
    warmup.loadBuffer(warmup_xml, empty);
    std::vector<Result> results(workers);
    std::vector<std::exception_ptr> errors(workers);
    std::barrier start(static_cast<std::ptrdiff_t>(workers + 1));
    std::vector<std::jthread> threads;
    for (std::size_t i = 0; i < workers; ++i)
    {
      threads.emplace_back([&, i]
      {
        omp_set_num_threads(requested_team);
        start.arrive_and_wait();
        try { results[i] = run(mode, path, queries); }
        catch (...) { errors[i] = std::current_exception(); }
      });
    }
    const auto begin = Clock::now();
    start.arrive_and_wait();
    threads.clear();
    const double seconds = std::chrono::duration<double>(Clock::now() - begin).count();
    for (const auto& error : errors) { if (error) { std::rethrow_exception(error); } }
    for (const auto& result : results)
    {
      if (!(result.digest == results.front().digest)) { throw std::runtime_error("Worker digest mismatch"); }
      if (result.index_spectra != results.front().index_spectra ||
          result.index_chromatograms != results.front().index_chromatograms)
      {
        throw std::runtime_error("Worker index count mismatch");
      }
    }
    // Query after joining, while retained contexts/experiments remain alive.
    const auto resident_rss = currentRssBytes();
    std::cout << std::setprecision(12) << "{\"mode\":\"" << mode << "\",\"workers\":" << workers
              << ",\"openms_library\":" << std::quoted(loadedLibrary())
              << ",\"resident_rss_bytes\":" << resident_rss
              << ",\"native_peak_rss_bytes\":" << nativePeakRssBytes()
              << ",\"requested_openmp_threads\":" << requested_team
              << ",\"auxiliary_audit\":" << (audit_auxiliary ? "true" : "false")
              << ",\"aux_hash_per_worker\":\"" << results.front().digest.aux_hash << "\""
              << ",\"im_array_values_per_worker\":" << results.front().digest.im_values
              << ",\"im_scalar_spectra_per_worker\":" << results.front().digest.im_scalars
              << ",\"ms1_per_worker\":" << results.front().digest.ms_levels[1]
              << ",\"ms2_per_worker\":" << results.front().digest.ms_levels[2]
              << ",\"ms3plus_per_worker\":" << results.front().digest.ms_levels[3]
              << ",\"seconds\":" << seconds << ",\"file_bytes\":" << std::filesystem::file_size(path)
              << ",\"spectra_per_worker\":" << results.front().digest.spectra
              << ",\"chromatograms_per_worker\":" << results.front().digest.chromatograms
              << ",\"points_per_worker\":" << results.front().digest.points
              << ",\"index_spectra\":" << results.front().index_spectra
              << ",\"index_chromatograms\":" << results.front().index_chromatograms
              << ",\"hash_per_worker\":\"" << results.front().digest.hash << "\",\"jobs\":[";
    for (std::size_t i = 0; i < workers; ++i)
    {
      if (i) { std::cout << ','; }
      std::cout << "{\"open_seconds\":" << results[i].open_seconds
                << ",\"read_seconds\":" << results[i].read_seconds << '}';
    }
    std::cout << "]}\n";
  }
  catch (const std::exception& error)
  {
    std::cerr << error.what() << '\n';
    return 1;
  }
  return 0;
}
