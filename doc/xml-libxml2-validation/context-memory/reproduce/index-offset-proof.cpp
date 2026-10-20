#include <OpenMS/FORMAT/HANDLERS/IndexedMzMLDecoder.h>
#include <iostream>
#include <cstdint>
int main(int argc, char** argv)
{
  if (argc != 2) { return 2; }
  OpenMS::IndexedMzMLDecoder decoder;
  OpenMS::IndexedMzMLDecoder::OffsetVector spectra, chromatograms;
  const auto pos = decoder.findIndexListOffset(argv[1]);
  if (decoder.parseOffsets(argv[1], pos, spectra, chromatograms) != 0) { return 1; }
  std::uint64_t hash = 1469598103934665603ULL;
  auto byte = [&](unsigned char b) { hash = (hash ^ b) * 1099511628211ULL; };
  for (const auto* offsets : {&spectra, &chromatograms})
  {
    byte(offsets == &spectra ? 1 : 2);
    for (const auto& [id, offset] : *offsets)
    {
      for (unsigned char c : id) { byte(c); }
      byte(0);
      const auto value = static_cast<std::uint64_t>(static_cast<std::streamoff>(offset));
      for (int i = 0; i < 8; ++i) { byte(static_cast<unsigned char>(value >> (8 * i))); }
    }
  }
  std::cout << "{\"spectra\":" << spectra.size() << ",\"chromatograms\":" << chromatograms.size()
            << ",\"complete_offset_digest\":\"" << hash << "\"}\n";
}
