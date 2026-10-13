# Experiment 01: Gaussian RNG Performance and Statistical Accuracy Comparison

Configurations: 78; performance runs: 780; validation seeds: [1].
Validation conclusions are preliminary because only one seed was used.
Failing to reject N(0,1) does not prove exact Gaussianity. P-values are decisions under a null model, not measures of approximation error.
PRNG fractions are estimates from an isolated microbenchmark; they are not exact CPU attribution.

## Primary comparison

| N | Basic M/s, pass | Unrefined M/s, pass | Best refined M/s, pass (H,T) |
|---:|---|---|---|
| 8 | 58.555, pass | 101.165, fail | None |
| 16 | 85.388, pass | 115.058, fail | None |
| 32 | 114.167, pass | 129.618, fail | None |

## Observations

- N=8: fastest observed trapezoid H=0 T=0 at 101.165 M/s; fastest passing: basic H=None T=None at 58.555 M/s.
- N=16: fastest observed trapezoid H=0 T=0 at 115.058 M/s; fastest passing: basic H=None T=None at 85.388 M/s.
- N=32: fastest observed trapezoid H=0 T=0 at 129.618 M/s; fastest passing: basic H=None T=None at 114.167 M/s.

## PRNG work and refinement

- basic: median 3.385 uniform calls/sample and estimated PRNG fraction 0.445 across its configurations.
- trapezoid: median 4.093 uniform calls/sample and estimated PRNG fraction 0.771 across its configurations.
- trapezoid_refined: median 4.178 uniform calls/sample and estimated PRNG fraction 0.700 across its configurations.
- N=8: refined median throughput differs from unrefined by -23.0%; head-only median 91.784 M/s; tail-only median 83.877 M/s.
- N=16: refined median throughput differs from unrefined by -12.1%; head-only median 111.975 M/s; tail-only median 104.554 M/s.
- N=32: refined median throughput differs from unrefined by -8.0%; head-only median 125.480 M/s; tail-only median 120.398 M/s.

## Accuracy and interpretation

Compare KS and AD statistics in the detailed CSV and figures for empirical discrepancy; p-values determine the configured test decisions and are not error magnitudes.
The three N values and the H/T grid are observational comparisons. CPU temperature, frequency, and background activity can contribute to speed differences despite interleaved repetitions.
The tail plot includes a one-standard-error reference under N(0,1), and tail_results.csv records its value at each threshold. Very rare tail errors are not definitive algorithm accuracy measurements.
These are observations from one executable build and one seed, not causal conclusions.
