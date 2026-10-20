#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-context-memory-20261020-01a153cb
cd "$root"
bash staging/prepare-dependencies.sh
prefix="$root/dependencies/install"
contrib=/scratch/kohlbach/contrib/build
export LD_LIBRARY_PATH="$prefix/lib:$contrib/lib" OPENMS_TMPDIR="$root/tmp" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
mkdir -p source snapshots/baseline/lib
sha256sum staging/libxml2-full.tar.gz > results/source-archive.sha256
tar xf staging/libxml2-full.tar.gz -C source
cmake -S source -B build -DOPENMS_USE_VCPKG=OFF -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS_RELEASE='-O3 -DNDEBUG' -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
 -DCMAKE_PREFIX_PATH="$prefix;$contrib" -DCMAKE_CXX_FLAGS="-I$prefix/include -I$prefix/include/libxml2" \
 -DLIBXML2_INCLUDE_DIR="$prefix/include/libxml2" -DLIBXML2_LIBRARY="$prefix/lib/libxml2.so" -DCMAKE_DISABLE_FIND_PACKAGE_XercesC=ON \
 -DCURL_NO_CURL_CMAKE=OFF -DCURL_DIR="$contrib/lib/cmake/CURL" -DBUILD_TOPP_TOOLS=OFF -DWITH_GUI=OFF -DPYOPENMS=OFF -DWITH_OPENTIMS=OFF -DWITH_THERMO_RAW=OFF -DWITH_ONNX=OFF -DWITH_WNETALIGN=OFF \
 -DENABLE_CWL_GENERATION=OFF -DENABLE_DOCS=OFF -DENABLE_CLASS_TESTING=ON -DENABLE_TOPP_TESTING=OFF -DENABLE_UPDATE_CHECK=OFF > logs/baseline-configure.log 2>&1
cmake --build build --target IndexedMzMLDecoder_test IndexedMzMLFile_test IndexedMzMLFileLoader_test OnDiscMSExperiment_test MzMLSpectrumDecoder_test XMLFile_test XMLParserBackend_test -j24 > logs/baseline-build.log 2>&1
ctest --test-dir build -R '^(IndexedMzMLDecoder|IndexedMzMLFile|IndexedMzMLFileLoader|OnDiscMSExperiment|MzMLSpectrumDecoder|XMLFile|XMLParserBackend)_test$' --output-on-failure -j4 > results/baseline-tests.log 2>&1
cp -a build/lib/libOpenMS.so* build/lib/libOpenSwathAlgo.so* snapshots/baseline/lib/
cp build/CMakeCache.txt results/baseline-cache.txt
sha256sum snapshots/baseline/lib/* > results/baseline-libraries.sha256
cmake -S staging/benchmark-source -B benchmark-build -DOpenMS_DIR="$root/build" -DCMAKE_BUILD_TYPE=Release > logs/benchmark-configure.log 2>&1
cmake --build benchmark-build -j8 > logs/benchmark-build.log 2>&1
LD_LIBRARY_PATH="$root/snapshots/baseline/lib:$LD_LIBRARY_PATH" ctest --test-dir benchmark-build --output-on-failure > results/baseline-benchmark-tests.log 2>&1
touch results/BASELINE_BUILD_COMPLETE
