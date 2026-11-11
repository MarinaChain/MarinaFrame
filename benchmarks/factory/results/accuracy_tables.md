
### Split: development (528 cases, 132 hulls)


By degradation level

| level | attempted | built | abstained | failed | correct / attempted | correct / built | station RMS median (mm) | RMS % of B/2 median | max % of B/2 median | volume error in range, % median / p90 | volume error full, % median | waterplane in range, % median | seconds median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 clean | 132 | 4 | 122 | 6 | 4/132 | 4/4 | 31.20 | 0.21 | 0.71 | 0.85 / 1.20 | 8.93 | 0.53 | 20.25 |
| 1 mild | 132 | 0 | 128 | 4 | 0/132 | 0/0 | - | - | - | - / - | - | - | 15.48 |
| 2 moderate | 132 | 0 | 131 | 1 | 0/132 | 0/0 | - | - | - | - / - | - | - | 14.47 |
| 3 heavy | 132 | 0 | 129 | 3 | 0/132 | 0/0 | - | - | - | - / - | - | - | 13.19 |

By layout

| layout | attempted | built | abstained | failed | correct / attempted | correct / built | station RMS median (mm) | RMS % of B/2 median | max % of B/2 median | volume error in range, % median / p90 | volume error full, % median | waterplane in range, % median | seconds median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| overlay | 96 | 0 | 95 | 1 | 0/96 | 0/0 | - | - | - | - / - | - | - | 15.88 |
| separate | 432 | 4 | 415 | 13 | 4/432 | 4/4 | 31.20 | 0.21 | 0.71 | 0.85 / 1.20 | 8.93 | 0.53 | 15.66 |

By level and layout

| level / layout | attempted | built | abstained | failed | correct / attempted | correct / built | station RMS median (mm) | RMS % of B/2 median | max % of B/2 median | volume error in range, % median / p90 | volume error full, % median | waterplane in range, % median | seconds median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 clean / overlay | 24 | 0 | 24 | 0 | 0/24 | 0/0 | - | - | - | - / - | - | - | 18.15 |
| 0 clean / separate | 108 | 4 | 98 | 6 | 4/108 | 4/4 | 31.20 | 0.21 | 0.71 | 0.85 / 1.20 | 8.93 | 0.53 | 23.45 |
| 1 mild / overlay | 24 | 0 | 24 | 0 | 0/24 | 0/0 | - | - | - | - / - | - | - | 12.59 |
| 1 mild / separate | 108 | 0 | 104 | 4 | 0/108 | 0/0 | - | - | - | - / - | - | - | 16.27 |
| 2 moderate / overlay | 24 | 0 | 24 | 0 | 0/24 | 0/0 | - | - | - | - / - | - | - | 15.06 |
| 2 moderate / separate | 108 | 0 | 107 | 1 | 0/108 | 0/0 | - | - | - | - / - | - | - | 13.77 |
| 3 heavy / overlay | 24 | 0 | 23 | 1 | 0/24 | 0/0 | - | - | - | - / - | - | - | 17.05 |
| 3 heavy / separate | 108 | 0 | 106 | 2 | 0/108 | 0/0 | - | - | - | - / - | - | - | 13.10 |
| **all** | 528 | 4 | 510 | 14 | 4/528 | 4/4 | 31.20 | 0.21 | 0.71 | 0.85 / 1.20 | 8.93 | 0.53 | 15.74 |

By family (named hulls individually; Ship-D clusters pooled per cluster in the JSON)

| family | attempted | built | abstained | failed | correct / attempted | correct / built | station RMS median (mm) | RMS % of B/2 median | max % of B/2 median | volume error in range, % median / p90 | volume error full, % median | waterplane in range, % median | seconds median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| dtmb5415 | 4 | 0 | 4 | 0 | 0/4 | 0/0 | - | - | - | - / - | - | - | 17.40 |
| series60 | 4 | 0 | 4 | 0 | 0/4 | 0/0 | - | - | - | - / - | - | - | 35.06 |
| wigley | 4 | 1 | 3 | 0 | 1/4 | 1/1 | 7.51 | 0.15 | 0.38 | 1.33 / 1.33 | 6.87 | 1.01 | 12.68 |
| Ship-D (26 clusters) | 516 | 3 | 499 | 14 | 3/516 | 3/3 | 31.58 | 0.23 | 0.96 | 0.81 / 0.88 | 10.02 | 0.40 | 15.68 |

### Split: validation (360 cases, 90 hulls)


By degradation level

| level | attempted | built | abstained | failed | correct / attempted | correct / built | station RMS median (mm) | RMS % of B/2 median | max % of B/2 median | volume error in range, % median / p90 | volume error full, % median | waterplane in range, % median | seconds median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 clean | 90 | 1 | 82 | 7 | 1/90 | 1/1 | 210.32 | 1.34 | 31.70 | 1.08 / 1.08 | 11.44 | 0.77 | 16.34 |
| 1 mild | 90 | 1 | 89 | 0 | 0/90 | 0/1 | 448.92 | 3.91 | 66.21 | 27.45 / 27.45 | 26.32 | 1.13 | 8.78 |
| 2 moderate | 90 | 0 | 90 | 0 | 0/90 | 0/0 | - | - | - | - / - | - | - | 12.17 |
| 3 heavy | 90 | 0 | 90 | 0 | 0/90 | 0/0 | - | - | - | - / - | - | - | 14.39 |

By layout

| layout | attempted | built | abstained | failed | correct / attempted | correct / built | station RMS median (mm) | RMS % of B/2 median | max % of B/2 median | volume error in range, % median / p90 | volume error full, % median | waterplane in range, % median | seconds median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| overlay | 76 | 0 | 74 | 2 | 0/76 | 0/0 | - | - | - | - / - | - | - | 12.96 |
| separate | 284 | 2 | 277 | 5 | 1/284 | 1/2 | 329.62 | 2.63 | 48.96 | 14.26 / 24.81 | 18.88 | 0.95 | 13.50 |

By level and layout

| level / layout | attempted | built | abstained | failed | correct / attempted | correct / built | station RMS median (mm) | RMS % of B/2 median | max % of B/2 median | volume error in range, % median / p90 | volume error full, % median | waterplane in range, % median | seconds median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 clean / overlay | 19 | 0 | 17 | 2 | 0/19 | 0/0 | - | - | - | - / - | - | - | 13.95 |
| 0 clean / separate | 71 | 1 | 65 | 5 | 1/71 | 1/1 | 210.32 | 1.34 | 31.70 | 1.08 / 1.08 | 11.44 | 0.77 | 17.83 |
| 1 mild / overlay | 19 | 0 | 19 | 0 | 0/19 | 0/0 | - | - | - | - / - | - | - | 9.63 |
| 1 mild / separate | 71 | 1 | 70 | 0 | 0/71 | 0/1 | 448.92 | 3.91 | 66.21 | 27.45 / 27.45 | 26.32 | 1.13 | 8.51 |
| 2 moderate / overlay | 19 | 0 | 19 | 0 | 0/19 | 0/0 | - | - | - | - / - | - | - | 10.18 |
| 2 moderate / separate | 71 | 0 | 71 | 0 | 0/71 | 0/0 | - | - | - | - / - | - | - | 14.13 |
| 3 heavy / overlay | 19 | 0 | 19 | 0 | 0/19 | 0/0 | - | - | - | - / - | - | - | 13.65 |
| 3 heavy / separate | 71 | 0 | 71 | 0 | 0/71 | 0/0 | - | - | - | - / - | - | - | 14.67 |
| **all** | 360 | 2 | 351 | 7 | 1/360 | 1/2 | 329.62 | 2.63 | 48.96 | 14.26 / 24.81 | 18.88 | 0.95 | 13.41 |

By family (named hulls individually; Ship-D clusters pooled per cluster in the JSON)

| family | attempted | built | abstained | failed | correct / attempted | correct / built | station RMS median (mm) | RMS % of B/2 median | max % of B/2 median | volume error in range, % median / p90 | volume error full, % median | waterplane in range, % median | seconds median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| dsyhs | 192 | 1 | 185 | 6 | 0/192 | 0/1 | 448.92 | 3.91 | 66.21 | 27.45 / 27.45 | 26.32 | 1.13 | 12.51 |
| Ship-D (9 clusters) | 168 | 1 | 166 | 1 | 1/168 | 1/1 | 210.32 | 1.34 | 31.70 | 1.08 / 1.08 | 11.44 | 0.77 | 14.43 |

### Split: test (192 cases, 48 hulls)


By degradation level

| level | attempted | built | abstained | failed | correct / attempted | correct / built | station RMS median (mm) | RMS % of B/2 median | max % of B/2 median | volume error in range, % median / p90 | volume error full, % median | waterplane in range, % median | seconds median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 clean | 48 | 6 | 38 | 4 | 6/48 | 6/6 | 34.11 | 0.32 | 2.67 | 1.05 / 1.53 | 10.20 | 0.66 | 21.06 |
| 1 mild | 48 | 0 | 47 | 1 | 0/48 | 0/0 | - | - | - | - / - | - | - | 6.29 |
| 2 moderate | 48 | 0 | 48 | 0 | 0/48 | 0/0 | - | - | - | - / - | - | - | 9.43 |
| 3 heavy | 48 | 0 | 47 | 1 | 0/48 | 0/0 | - | - | - | - / - | - | - | 14.37 |

By layout

| layout | attempted | built | abstained | failed | correct / attempted | correct / built | station RMS median (mm) | RMS % of B/2 median | max % of B/2 median | volume error in range, % median / p90 | volume error full, % median | waterplane in range, % median | seconds median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| overlay | 44 | 0 | 44 | 0 | 0/44 | 0/0 | - | - | - | - / - | - | - | 8.88 |
| separate | 148 | 6 | 136 | 6 | 6/148 | 6/6 | 34.11 | 0.32 | 2.67 | 1.05 / 1.53 | 10.20 | 0.66 | 11.98 |

By level and layout

| level / layout | attempted | built | abstained | failed | correct / attempted | correct / built | station RMS median (mm) | RMS % of B/2 median | max % of B/2 median | volume error in range, % median / p90 | volume error full, % median | waterplane in range, % median | seconds median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 clean / overlay | 11 | 0 | 11 | 0 | 0/11 | 0/0 | - | - | - | - / - | - | - | 12.43 |
| 0 clean / separate | 37 | 6 | 27 | 4 | 6/37 | 6/6 | 34.11 | 0.32 | 2.67 | 1.05 / 1.53 | 10.20 | 0.66 | 22.96 |
| 1 mild / overlay | 11 | 0 | 11 | 0 | 0/11 | 0/0 | - | - | - | - / - | - | - | 6.24 |
| 1 mild / separate | 37 | 0 | 36 | 1 | 0/37 | 0/0 | - | - | - | - / - | - | - | 6.34 |
| 2 moderate / overlay | 11 | 0 | 11 | 0 | 0/11 | 0/0 | - | - | - | - / - | - | - | 9.18 |
| 2 moderate / separate | 37 | 0 | 37 | 0 | 0/37 | 0/0 | - | - | - | - / - | - | - | 9.65 |
| 3 heavy / overlay | 11 | 0 | 11 | 0 | 0/11 | 0/0 | - | - | - | - / - | - | - | 9.49 |
| 3 heavy / separate | 37 | 0 | 36 | 1 | 0/37 | 0/0 | - | - | - | - / - | - | - | 16.98 |
| **all** | 192 | 6 | 180 | 6 | 6/192 | 6/6 | 34.11 | 0.32 | 2.67 | 1.05 / 1.53 | 10.20 | 0.66 | 11.08 |

By family (named hulls individually; Ship-D clusters pooled per cluster in the JSON)

| family | attempted | built | abstained | failed | correct / attempted | correct / built | station RMS median (mm) | RMS % of B/2 median | max % of B/2 median | volume error in range, % median / p90 | volume error full, % median | waterplane in range, % median | seconds median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| kcs | 4 | 0 | 4 | 0 | 0/4 | 0/0 | - | - | - | - / - | - | - | 19.18 |
| kvlcc1 | 4 | 0 | 4 | 0 | 0/4 | 0/0 | - | - | - | - / - | - | - | 16.20 |
| kvlcc2 | 4 | 0 | 4 | 0 | 0/4 | 0/0 | - | - | - | - / - | - | - | 10.89 |
| Ship-D (9 clusters) | 180 | 6 | 168 | 6 | 6/180 | 6/6 | 34.11 | 0.32 | 2.67 | 1.05 / 1.53 | 10.20 | 0.66 | 10.45 |
