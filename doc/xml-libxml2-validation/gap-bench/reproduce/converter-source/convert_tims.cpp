#include <OpenMS/FORMAT/BrukerTimsFile.h>
#include <OpenMS/FORMAT/DATAACCESS/MSDataWritingConsumer.h>
#include <OpenMS/FORMAT/OPTIONS/PeakFileOptions.h>
#include <iostream>
int main(int argc, char** argv)
{
  if (argc != 3) { return 2; }
  try
  {
    OpenMS::PlainMSDataWritingConsumer writer(argv[2]);
    OpenMS::PeakFileOptions options;
    options.setCompression(true);
    options.setWriteIndex(true);
    writer.setOptions(options);
    OpenMS::BrukerTimsFile::Config config;
    config.rt_min_sec = 600.0;
    config.rt_max_sec = 1200.0;
    config.rt_selects_spectra = true;
    config.tims_calibration_strategy = OpenMS::BrukerTimsFile::Config::TimsCalibrationStrategy::RATIONAL;
    OpenMS::BrukerTimsFile().transform(argv[1], &writer, config);
    return 0;
  }
  catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
