#include <OpenMS/FORMAT/HANDLERS/IndexedMzMLDecoder.h>
#include <OpenMS/CONCEPT/Exception.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
using OpenMS::IndexedMzMLDecoder;
int main(int argc, char** argv)
{
  if (argc != 2) { return 2; }
  std::filesystem::create_directories(argv[1]);
  const auto path = std::filesystem::path(argv[1]) / "footer-extra.xml";
  const std::string valid = "<indexList><index name='spectrum'><offset idRef='one'>1</offset></index></indexList></indexedmzML>";
  int checked = 0;
  for (const size_t padding : {size_t(0), size_t(2 * 1024 * 1024)})
  {
    auto run = [&](const std::string& text, int expected, const std::string& expected_id = "")
    {
      { std::ofstream f(path, std::ios::binary); f << std::string(padding, ' ') << text; }
      IndexedMzMLDecoder::OffsetVector spectra{{"sentinel", 7}}, chroms{{"sentinel", 8}};
      int status;
      try { status = IndexedMzMLDecoder().parseOffsets(path.string(), 0, spectra, chroms); }
      catch (const OpenMS::Exception::ConversionError&) { status = 2; }
      if (status != expected) { throw std::runtime_error("Footer result mismatch at control " + std::to_string(checked)); }
      if (status != 0 && (spectra.size()!=1 || chroms.size()!=1 || spectra[0].first!="sentinel" || chroms[0].first!="sentinel"))
      { throw std::runtime_error("Failure modified outputs"); }
      if (status == 0 && (spectra.size()!=1 || spectra[0].second!=1 || spectra[0].first!=expected_id)) { throw std::runtime_error("Wrong complete offsets"); }
      ++checked;
    };
    run(valid, 0, "one");
    run("<indexList><foo name='spectrum'><bar>1</bar></foo></indexList></indexedmzML>", 0);
    run(valid + std::string(4096, ' ') + "<junk/>", -1);
    run(valid + std::string(4096, '\0'), -1);
    run("<indexList/><indexList/></indexedmzML>", -1);
    run("<indexList><index name='spectrum'><offset>abc</offset></index></indexList><indexList/></indexedmzML>", -1);
    run("<indexList><index name='spectrum'><offset>abc</offset></index><index name='unknown'/></indexList></indexedmzML>", 2);
    run("<indexList><index name='spectrum'><offset>1</index></indexList></indexedmzML>", -1);
    run("<indexList><index name='spectrum'><offset>1</offset></index></indexList>", -1);
    run("<n:indexList xmlns:n='urn:test'><n:foo name='spectrum'><n:bar idRef='a&amp;b'>0<![CDATA[0]]><value>1</value></n:bar></n:foo></n:indexList></indexedmzML>", 0, "a&b");
  }
  std::filesystem::remove(path);
  std::cout << "{\"footer_controls_passed\":" << checked << "}\n";
}
