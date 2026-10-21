One measurement per point; reductions are relative to the fresh 24-byte control at the same requested core count.

| Version / option | Cores | Wall (s) | Peak RSS (GiB) | Wall reduction (%) | RSS reduction (%) |
|---|---:|---:|---:|---:|---:|
| 24 B inline | 16 | 65.6595 | 4.314 | 0.00 | 0.00 |
| 24 B inline | 32 | 37.5096 | 7.166 | 0.00 | 0.00 |
| 24 B inline | 64 | 25.3907 | 12.709 | 0.00 | 0.00 |
| 24 B inline | 128 | 25.2266 | 15.298 | 0.00 | 0.00 |
| 24 B inline | 192 | 25.4464 | 17.625 | 0.00 | 0.00 |
| 16 B recompute log | 16 | 173.6149 | 3.332 | -164.42 | 22.77 |
| 16 B recompute log | 32 | 83.8444 | 5.366 | -123.53 | 25.11 |
| 16 B recompute log | 64 | 48.2091 | 9.256 | -89.87 | 27.17 |
| 16 B recompute log | 128 | 51.3518 | 11.572 | -103.56 | 24.35 |
| 16 B recompute log | 192 | 46.4961 | 13.551 | -82.72 | 23.11 |
| 16 B cached log + index | 16 | 61.0355 | 3.354 | 7.04 | 22.26 |
| 16 B cached log + index | 32 | 35.5293 | 5.359 | 5.28 | 25.21 |
| 16 B cached log + index | 64 | 23.2852 | 9.283 | 8.29 | 26.96 |
| 16 B cached log + index | 128 | 23.4235 | 11.832 | 7.15 | 22.65 |
| 16 B cached log + index | 192 | 23.3866 | 13.818 | 8.09 | 21.60 |
| 8 B shared arrays | 16 | 63.5306 | 3.013 | 3.24 | 30.16 |
| 8 B shared arrays | 32 | 35.9071 | 4.306 | 4.27 | 39.91 |
| 8 B shared arrays | 64 | 22.5680 | 6.849 | 11.12 | 46.11 |
| 8 B shared arrays | 128 | 22.6546 | 9.277 | 10.20 | 39.36 |
| 8 B shared arrays | 192 | 22.3085 | 11.355 | 12.33 | 35.57 |
