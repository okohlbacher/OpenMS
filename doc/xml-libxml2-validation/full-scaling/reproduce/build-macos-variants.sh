#!/bin/bash
set -euo pipefail
root="$PWD/dependencies/libxml2-speed"
for variant in os o2 o3 ascii; do
 source="$root/libxml2-2.15.4";flag=-O3
 if [[ "$variant" == o2 ]]; then flag=-O2; fi
 if [[ "$variant" == os ]]; then flag=-Os; fi
 if [[ "$variant" == ascii ]]; then source="$root/libxml2-ascii"; fi
 cmake -S "$source" -B "$root/build-$variant" -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_FLAGS_RELEASE="$flag -DNDEBUG" -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DCMAKE_INSTALL_PREFIX="$root/install-$variant" -DBUILD_SHARED_LIBS=ON -DLIBXML2_WITH_LEGACY=OFF -DLIBXML2_WITH_SAX1=ON -DLIBXML2_WITH_PUSH=ON -DLIBXML2_WITH_SCHEMAS=ON -DLIBXML2_WITH_THREADS=ON -DLIBXML2_WITH_ICONV=ON -DLIBXML2_WITH_ZLIB=ON -DLIBXML2_WITH_PYTHON=OFF -DLIBXML2_WITH_PROGRAMS=OFF -DLIBXML2_WITH_TESTS=ON > "results/full-scaling/macos/$variant-configure.log" 2>&1
 cmake --build "$root/build-$variant" -j8 > "results/full-scaling/macos/$variant-build.log" 2>&1
 cmake --install "$root/build-$variant" > "results/full-scaling/macos/$variant-install.log" 2>&1
 ctest --test-dir "$root/build-$variant" --output-on-failure -j4 > "results/full-scaling/macos/$variant-tests.log" 2>&1
 done
