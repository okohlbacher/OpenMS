#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-libxml2-scaling-20261020-01a153cb
cd "$root/dependencies"
prefix="$root/dependencies/install"
curl --fail --location --retry 3 --connect-timeout 20 https://download.gnome.org/sources/libxml2/2.15/libxml2-2.15.4.tar.xz -o libxml2-2.15.4.tar.xz
curl --fail --location --retry 3 --connect-timeout 20 https://github.com/facebook/zstd/releases/download/v1.5.7/zstd-1.5.7.tar.gz -o zstd-1.5.7.tar.gz
cat > "$root/results/dependency-archives.sha256" <<'HASHES'
98087fd181d9070724f3fbc65c7377db03038eb92bd882374daff44940138821  libxml2-2.15.4.tar.xz
eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3  zstd-1.5.7.tar.gz
HASHES
sha256sum -c "$root/results/dependency-archives.sha256"
tar xf libxml2-2.15.4.tar.xz
tar xf zstd-1.5.7.tar.gz
cmake -S libxml2-2.15.4 -B libxml2-build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix" -DBUILD_SHARED_LIBS=ON -DLIBXML2_WITH_LEGACY=OFF -DLIBXML2_WITH_ZLIB=ON -DLIBXML2_WITH_PYTHON=OFF -DLIBXML2_WITH_PROGRAMS=OFF -DLIBXML2_WITH_TESTS=OFF > "$root/logs/libxml2-configure.log" 2>&1
cmake --build libxml2-build -j16 > "$root/logs/libxml2-build.log" 2>&1
cmake --install libxml2-build > "$root/logs/libxml2-install.log" 2>&1
cmake -S zstd-1.5.7/build/cmake -B zstd-build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix" -DZSTD_BUILD_PROGRAMS=OFF -DZSTD_BUILD_TESTS=OFF -DZSTD_BUILD_STATIC=OFF -DZSTD_BUILD_SHARED=ON > "$root/logs/zstd-configure.log" 2>&1
cmake --build zstd-build -j12 > "$root/logs/zstd-build.log" 2>&1
cmake --install zstd-build > "$root/logs/zstd-install.log" 2>&1
cp libxml2-build/CMakeCache.txt "$root/results/libxml2-build-cache.txt"
cp zstd-build/CMakeCache.txt "$root/results/zstd-build-cache.txt"
sha256sum "$prefix"/lib/libxml2.so* "$prefix"/lib/libzstd.so* > "$root/results/dependency-libraries.sha256"
touch "$root/results/DEPENDENCIES_COMPLETE"

cd "$root/dependencies"
curl --fail --location --retry 3 --connect-timeout 20 https://archive.apache.org/dist/xerces/c/3/sources/xerces-c-3.3.0.tar.gz -o xerces-c-3.3.0.tar.gz
echo '9555f1d06f82987fbb4658862705515740414fd34b4db6ad2ed76a2dc08d3bde  xerces-c-3.3.0.tar.gz' | sha256sum -c -
tar xf xerces-c-3.3.0.tar.gz
cmake -S xerces-c-3.3.0 -B xerces-build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix" -DBUILD_SHARED_LIBS=ON -Dnetwork-accessor=socket -Dtranscoder=gnuiconv -DBUILD_TESTING=OFF > "$root/logs/xerces-configure.log" 2>&1
cmake --build xerces-build -j24 > "$root/logs/xerces-build.log" 2>&1
cmake --install xerces-build > "$root/logs/xerces-install.log" 2>&1
mkdir -p header-priority
for name in xercesc zstd.h zstd_errors.h; do ln -s "$prefix/include/$name" "header-priority/$name"; done
sha256sum "$prefix"/lib/libxerces-c.so* >> "$root/results/dependency-libraries.sha256"
