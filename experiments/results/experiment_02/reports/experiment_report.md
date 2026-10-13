# Experiment 02 — Seed 2 Validation

Exactly five configurations ran sequentially, each with 100,000,000 samples and seed 2. All four tests use fixed N(0,1), with no fitted parameters or sample standardization. No performance repetitions, PRNG profiling, or rebuild were performed.

## Seed 2 moments

| Algorithm | N | H | T | Mean | Sample variance (ddof=1) |
|---|---:|---:|---:|---:|---:|
| basic | 8 | — | — | -4.34205108677e-05 | 0.999947898671 |
| trapezoid | 8 | 0 | 0 | -5.4302185053e-05 | 0.996851061712 |
| trapezoid_refined | 8 | 2 | 4 | -1.49182004904e-05 | 0.999715791007 |
| trapezoid_refined | 16 | 2 | 4 | 0.00012271794556 | 0.999952130053 |
| trapezoid_refined | 32 | 2 | 4 | 7.5945418719e-05 | 0.999998366145 |

## Seed 1 versus Seed 2

R = reject; F = fail-to-reject. **Bold patterns** identify rejection under both seeds. Fail-to-reject corresponds to the requested “accepted” category; it does not establish normality.

| Algorithm | N | H | T | Test | Seed 1 statistic | Seed 1 p | Seed 2 statistic | Seed 2 p | Decisions (1 / 2) | Pattern |
|---|---:|---:|---:|---|---:|---:|---:|---:|---|---|
| basic | 8 | — | — | Pearson Chi-square | 85.580491 | 0.86391454 | 99.181675 | 0.53256275 | F / F | fail-to-reject under both seeds |
| basic | 8 | — | — | KS | 8.5650517e-05 | 0.4554655 | 7.5235522e-05 | 0.62317543 | F / F | fail-to-reject under both seeds |
| basic | 8 | — | — | AD | 1.0278997 | 0.34296561 | 0.57237706 | 0.67449211 | F / F | fail-to-reject under both seeds |
| basic | 8 | — | — | CvM | 0.18772473 | 0.29256765 | 0.095442733 | 0.60768106 | F / F | fail-to-reject under both seeds |
| trapezoid | 8 | 0 | 0 | Pearson Chi-square | 192084.52 | 0 | 192808.99 | 0 | R / R | **rejected under both seeds** |
| trapezoid | 8 | 0 | 0 | KS | 0.00086985297 | 3.7975119e-66 | 0.00086399954 | 2.8908825e-65 | R / R | **rejected under both seeds** |
| trapezoid | 8 | 0 | 0 | AD | 200.39618 | omitted (<1e-4 calibration resolution) | 200.50046 | omitted (<1e-4 calibration resolution) | R / R | **rejected under both seeds** |
| trapezoid | 8 | 0 | 0 | CvM | 14.868892 | 1.6649311e-09 | 14.6918 | 1.3541981e-09 | R / R | **rejected under both seeds** |
| trapezoid_refined | 8 | 2 | 4 | Pearson Chi-square | 975.4111 | 4.6756453e-143 | 1045.8491 | 7.4143944e-157 | R / R | **rejected under both seeds** |
| trapezoid_refined | 8 | 2 | 4 | KS | 8.3020172e-05 | 0.49584882 | 7.443542e-05 | 0.63664982 | F / F | fail-to-reject under both seeds |
| trapezoid_refined | 8 | 2 | 4 | AD | 1.2043325 | 0.26590316 | 1.0853497 | 0.3154346 | F / F | fail-to-reject under both seeds |
| trapezoid_refined | 8 | 2 | 4 | CvM | 0.13514693 | 0.43818507 | 0.078450822 | 0.70086339 | F / F | fail-to-reject under both seeds |
| trapezoid_refined | 16 | 2 | 4 | Pearson Chi-square | 327.38893 | 1.0601308e-25 | 296.40788 | 4.3180492e-21 | R / R | **rejected under both seeds** |
| trapezoid_refined | 16 | 2 | 4 | KS | 8.7402579e-05 | 0.42954969 | 6.57157e-05 | 0.7808184 | F / F | fail-to-reject under both seeds |
| trapezoid_refined | 16 | 2 | 4 | AD | 0.64881881 | 0.60308523 | 0.80381152 | 0.47830167 | F / F | fail-to-reject under both seeds |
| trapezoid_refined | 16 | 2 | 4 | CvM | 0.10554474 | 0.55836904 | 0.098422449 | 0.59266324 | F / F | fail-to-reject under both seeds |
| trapezoid_refined | 32 | 2 | 4 | Pearson Chi-square | 215.55197 | 2.7034727e-10 | 203.12474 | 7.5102698e-09 | R / R | **rejected under both seeds** |
| trapezoid_refined | 32 | 2 | 4 | KS | 8.6378679e-05 | 0.44459465 | 0.00011666773 | 0.13140297 | F / F | fail-to-reject under both seeds |
| trapezoid_refined | 32 | 2 | 4 | AD | 0.77205352 | 0.50163744 | 0.89748266 | 0.41580316 | F / F | fail-to-reject under both seeds |
| trapezoid_refined | 32 | 2 | 4 | CvM | 0.1153251 | 0.51484207 | 0.16390894 | 0.34984324 | F / F | fail-to-reject under both seeds |

## Rejection patterns by test

| Test | Both reject | Seed 1 only | Seed 2 only | Both fail-to-reject |
|---|---:|---:|---:|---:|
| Pearson Chi-square | 4 | 0 | 0 | 1 |
| KS | 1 | 0 | 0 | 4 |
| AD | 1 | 0 | 0 | 4 |
| CvM | 1 | 0 | 0 | 4 |

Chi-square rejection persisted in 4 of the 4 selected configurations that rejected under Seed 1. The comparison describes these five configurations and two seeds only. It does not establish a seed-independent defect, p-value uniformity, or the general quality of the RNG. No second-level uniformity tests were performed.

## Calibration and numerical concerns

Settings match Experiment 01: alpha = 0.05 per test, 100 equal-width interior bins from -5 to 5, two unbounded tail bins, expected-count-only merging with minimum expected count 5. The same KS finite-sample calibration, Marsaglia-Marsaglia AD approximation, and SciPy CvM calibration were used. All four tests process the complete dataset. Decisions have no multiple-testing correction and the tests are correlated.

AD p-values below 1e-4 are omitted with an explicit resolution flag. A computed zero from SciPy is flagged as numerical rounding/underflow rather than a mathematically zero probability. Critical values, methods, flags, and full-precision numerical values are retained in JSON/CSV.

Seed 2 numerical flags: [('trapezoid', 8, 'Pearson Chi-square', 0.0), ('trapezoid', 8, 'AD', None)].

## Reproducibility and verification

Executable SHA-256: `c6bfdc8812497daf9de82febc0a216d4766ed35b76bac556ca37576c9f6f66a9`.

Validation code SHA-256: `3ee7f7d66ceadd12541b84eecf782d01b4d117d2305965993842a637a46c4bc9`.

NumPy 1.26.4; SciPy 1.13.1; Python 3.12.7. Executable and validation hashes and numerical dependency versions match the Seed 1 results. The configuration, executable, driver, and supporting Python sources are preserved in artifacts/.

All five 800,000,000-byte binaries were generated, analyzed, hashed, and deleted only after saved per-run results, aggregated JSON/CSV, and integrity records passed readback. No previews or subsets were retained. All Experiment 01 file hashes and modification times match the snapshot taken before this experiment. Existing C summary timings are retained as ordinary validation provenance; no performance comparison was performed.

Started: 2026-10-12T19:03:30.024144+00:00; finished: 2026-10-12T19:05:03.947184+00:00.

Reproduce from the repository root with `python3 -B experiments/experiment02.py` using a fresh experiment_02 output location and the same executable/dependency versions. The driver refuses an existing output directory to protect saved results.
