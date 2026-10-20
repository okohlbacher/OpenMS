#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-libxml2-scaling-20261020-01a153cb
cd "$root"
prefix="$root/dependencies/install"
contrib=/scratch/kohlbach/contrib/build
export LD_LIBRARY_PATH="$prefix/lib:$contrib/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export OPENMS_TMPDIR="$root/tmp" LC_ALL=C.UTF-8 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 OMP_DYNAMIC=FALSE
cp staging/benchmark-source/run_benchmarks.py "$root/run_benchmarks.py"
python3 staging/verify-inputs.py
bash staging/prepare-dependencies.sh
existing=(OnDiscMSExperiment ConsensusXMLFile FeatureXMLFile IndexedMzMLDecoder IndexedMzMLFile IndexedMzMLFileLoader MzMLFile MzMLSpectrumDecoder TransformationXMLFile XMLFile XMLHandler XMLValidator CVMappingFile IdXMLFile MzDataFile MzIdentMLFile MzDataValidator MzMLValidator MzXMLFile ParamXMLFile PepXMLFile ProtXMLFile SemanticValidator TraMLFile UnimodXMLFile)
targets=(); regex='^('
for name in "${existing[@]}"; do targets+=("${name}_test"); regex+="${name}|"; done
regex="${regex%|})_test$"
for backend in xerces libxml2-full; do
 source="$root/source-$backend"
 mkdir -p "$source" "$root/snapshots/$backend/lib"
 tar xf "$root/staging/$backend.tar.gz" -C "$source"
 extra=()
 if [[ "$backend" == xerces ]]; then
  extra=(-DCMAKE_CXX_FLAGS="-I$root/dependencies/header-priority" -DXercesC_INCLUDE_DIR="$prefix/include" -DXercesC_LIBRARY_RELEASE="$prefix/lib/libxerces-c.so" -DXercesC_LIBRARY_DEBUG="$prefix/lib/libxerces-c.so")
 else
  extra=(-DCMAKE_CXX_FLAGS="-I$prefix/include -I$prefix/include/libxml2" -DCMAKE_DISABLE_FIND_PACKAGE_XercesC=ON)
 fi
 cmake -S "$source" -B "$root/build-$backend" -DOPENMS_USE_VCPKG=OFF -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS_RELEASE='-O3 -DNDEBUG' -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DCMAKE_PREFIX_PATH="$prefix;$contrib" \
 -DLIBXML2_INCLUDE_DIR="$prefix/include/libxml2" -DLIBXML2_LIBRARY="$prefix/lib/libxml2.so" \
 -UCURL_INCLUDE_DIR -UCURL_LIBRARY_RELEASE -DCURL_NO_CURL_CMAKE=OFF -DCURL_DIR="$contrib/lib/cmake/CURL" \
 -DBUILD_TOPP_TOOLS=OFF -DWITH_GUI=OFF -DPYOPENMS=OFF -DWITH_OPENTIMS=OFF -DWITH_THERMO_RAW=OFF -DWITH_ONNX=OFF -DWITH_WNETALIGN=OFF -DENABLE_CWL_GENERATION=OFF \
 -DENABLE_DOCS=OFF -DENABLE_CLASS_TESTING=ON -DENABLE_TOPP_TESTING=OFF -DENABLE_UPDATE_CHECK=OFF "${extra[@]}" > "$root/logs/$backend-configure.log" 2>&1
 focused=(); testregex="$regex"
 if [[ "$backend" == libxml2-full ]]; then focused=(XMLParserBackend_test StringManager_test ImzMLFile_test);testregex+='|^(XMLParserBackend|StringManager|ImzMLFile)_test$'; fi
 cmake --build "$root/build-$backend" --target "${targets[@]}" "${focused[@]}" -j24 > "$root/logs/$backend-build.log" 2>&1
 ctest --test-dir "$root/build-$backend" -R "$testregex" --output-on-failure -j4 > "$root/results/$backend-tests.log" 2>&1
 cp -a "$root/build-$backend/lib/"libOpenMS.so* "$root/build-$backend/lib/"libOpenSwathAlgo.so* "$root/snapshots/$backend/lib/"
 cp "$root/build-$backend/CMakeCache.txt" "$root/results/$backend-build-cache.txt"
 gzip -c "$root/build-$backend/compile_commands.json" > "$root/results/$backend-compile_commands.json.gz"
 sha256sum "$root/snapshots/$backend/lib/"* > "$root/results/$backend-libraries.sha256"
 ldd "$root/snapshots/$backend/lib/libOpenMS.so" > "$root/results/$backend-linked-libraries.txt"
 if [[ "$backend" == libxml2-full ]]; then
  python3 "$source/tools/ci/check_no_xerces.py" --build-dir "$root/build-$backend" > "$root/results/no-xerces-check.log" 2>&1
 fi
 if [[ "$backend" == xerces ]]; then
  cmake -S "$root/staging/benchmark-source" -B "$root/benchmark-build" -DOpenMS_DIR="$root/build-$backend" -DCMAKE_BUILD_TYPE=Release > "$root/logs/benchmark-configure.log" 2>&1
  cmake --build "$root/benchmark-build" --target xml_parser_benchmark xml_benchmark_launcher -j8 > "$root/logs/benchmark-build.log" 2>&1
 fi
 LD_LIBRARY_PATH="$root/snapshots/$backend/lib:$LD_LIBRARY_PATH" ctest --test-dir "$root/benchmark-build" --output-on-failure > "$root/results/$backend-benchmark-tests.log" 2>&1
 LD_LIBRARY_PATH="$root/snapshots/$backend/lib:$LD_LIBRARY_PATH" "$root/benchmark-build/xml_benchmark_launcher" "$root/benchmark-build/xml_parser_benchmark" verify "$root/data/huge-array.mzML" 1 2048 > "$root/results/$backend-huge-array.json" 2> "$root/logs/$backend-huge-array.log"
 touch "$root/results/$backend-BUILD_TEST_COMPLETE"
done
touch "$root/results/ALL_BUILDS_COMPLETE"
taskset -c 0-95 bash staging/run-matrices.sh
