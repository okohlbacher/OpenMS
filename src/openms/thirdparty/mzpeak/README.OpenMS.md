# Vendored mzPeak C++ library

Source: https://github.com/okohlbacher/mzpeak-openms, branch `feature/cmake-build`, commit
`a1e9ea260d9f7ac8798db924aef0340ebc30f1d1` (3 Nov 2026), a fork of the upstream
https://github.com/OpenMS/mzpeak (`trunk`, `d70ce3ac21ff885efb23bb3b49f148907e7a5e3b`,
14 Sep 2026, the fork's merge base; the fork is 281 commits ahead, upstream has no
commits the fork lacks). License: BSD-3-Clause (`LICENSE`); the third-party notes of the
library are in `THIRD_PARTY.upstream.md`.

The library implements the mzPeak format of HUPO-PSI (https://github.com/HUPO-PSI/mzPeak):
`metadata.version` `0.9.0`, audited against `HUPO-PSI/mzPeak-specification` up to
commit `840ba4a` (29 Sep 2026) per the fork's `docs/spec-compliance.md`, and reading the
array index of `e4ab6d5` (24 Oct 2026: `index`-format entries for the key columns, the
`polynomial_delta_coordinate_interpolation` delta model). The reader reads both metadata
layouts (nested and split facets), point and chunked signals (delta, MS-Numpress), Bruker
ims-compact, per-peak ion mobility; retention times are returned in seconds. The writer
emits the split-metadata layout.

Vendored: `include/` and `src/` of the library (not its tests, tools, examples, docs, meson
or CMake files). Built by `CMakeLists.txt` here as the static library `OpenMS_mzpeak`,
linked PRIVATE into libOpenMS when `OPENMS_ENABLE_MZPEAK` is ON;
`OpenMS/FORMAT/MzPeakFile.h` is the OpenMS interface.

The changes made to the previous copy (`1d487a3`) for OpenMS#10771 and OpenMS#10803 are in
the library since `c85080e` and `4fb1f56`, with two differences: `SpectrumData`'s
`ion_mobility` / `ion_mobility_type` are its last members (inserted before `polarity`, they
moved positional initialisers), and `Util::minutes_from_seconds()` is gone (it returned
`s / 60.0` for every input, so it changed no stored value).

## Local changes (keep when updating)

- `src/util/numpress.cpp`: includes `OpenMS/FORMAT/MSNUMPRESS/MSNumpress.h` (the copy that
  libOpenMS compiles) instead of the meson subproject's `MSNumpress.hpp`.
- `src/boost_json_src.cpp` (new): Boost.JSON compiled header-only, so libOpenMS links no
  compiled Boost library.
- `sources.cmake`, `CMakeLists.txt`, this file.

## Updating

Copy `include/` and `src/` from the library, re-apply the changes above, regenerate
`sources.cmake` from the `lib_sources` list of its `meson.build`, and record the commit here.
