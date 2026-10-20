#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-libxml2-replacement-20261020-01a153cb
prefix="$root/dependencies/install"
contrib=/scratch/kohlbach/contrib/build
cd "$root"
export LD_LIBRARY_PATH="$prefix/lib:$contrib/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export OPENMS_TMPDIR="$root/tmp"
export LC_ALL=C.UTF-8 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 OMP_DYNAMIC=FALSE
mkdir -p source build tmp
cd source
git fetch "$root/staging/replacement-dom-version.bundle" '+refs/heads/*:refs/heads/*' > "$root/logs/bundle-fetch.log" 2>&1
git checkout -q --detach cbb180af857f1c89956db8ac5128e4182d9b9ea8
test "$(git rev-parse HEAD)" = cbb180af857f1c89956db8ac5128e4182d9b9ea8
git rev-parse HEAD HEAD^{tree} > "$root/results/source-identity.txt"
cmake -S "$root/source" -B "$root/build" \
 -DOPENMS_USE_VCPKG=OFF -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS_RELEASE='-O3 -DNDEBUG' \
 -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DCMAKE_CXX_FLAGS="-I$prefix/include -I$prefix/include/libxml2" \
 -DCMAKE_PREFIX_PATH="$prefix;$contrib" -DCMAKE_DISABLE_FIND_PACKAGE_XercesC=ON \
 -DLIBXML2_INCLUDE_DIR="$prefix/include/libxml2" -DLIBXML2_LIBRARY="$prefix/lib/libxml2.so" \
 -UCURL_INCLUDE_DIR -UCURL_LIBRARY_RELEASE -DCURL_NO_CURL_CMAKE=OFF -DCURL_DIR="$contrib/lib/cmake/CURL" \
 -DBUILD_TOPP_TOOLS=ON -DWITH_GUI=OFF -DPYOPENMS=OFF -DWITH_OPENTIMS=OFF -DWITH_THERMO_RAW=OFF \
 -DWITH_ONNX=OFF -DWITH_WNETALIGN=OFF -DENABLE_CWL_GENERATION=OFF \
 -DENABLE_DOCS=OFF -DENABLE_CLASS_TESTING=ON -DENABLE_TOPP_TESTING=OFF -DENABLE_UPDATE_CHECK=OFF \
 > "$root/logs/configure.log" 2>&1
cp "$root/build/CMakeCache.txt" "$root/results/build-cache.txt"
cmake --build "$root/build" -j24 > "$root/logs/build.log" 2>&1
cp "$root/build/compile_commands.json" "$root/results/compile_commands.json"
git diff --exit-code HEAD > "$root/results/source-diff.txt"
git status --porcelain --untracked-files=no > "$root/results/source-status.txt"
ctest --test-dir "$root/build" --show-only=json-v1 > "$root/results/test-inventory.json"
set +e
ctest --test-dir "$root/build" -j12 --output-on-failure > "$root/results/class-tests.log" 2>&1
status=$?
set -e
echo "$status" > "$root/results/CLASS_TEST_EXIT_STATUS"
cp "$root/build/Testing/Temporary/LastTest.log" "$root/results/LastTest.log"
if test -f "$root/build/Testing/Temporary/LastTestsFailed.log"; then cp "$root/build/Testing/Temporary/LastTestsFailed.log" "$root/results/LastTestsFailed.log"; fi
python3 tools/ci/check_no_xerces.py --build-dir "$root/build" > "$root/results/no-xerces-check.log" 2>&1
python3 -m unittest discover -s tools/ci/tests -p 'test_check_no_xerces.py' > "$root/results/ci-python-tests.log" 2>&1
ldd "$root/build/lib/libOpenMS.so" > "$root/results/linked-libraries.txt"
sha256sum "$root/build/lib/"libOpenMS.so* > "$root/results/openms-libraries.sha256"
touch "$root/results/VALIDATION_COMPLETE"
bash "$root/staging/run-dom-version-supplemental.sh"
