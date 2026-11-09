# Experiment 16 report: bit-packed Philox2x64-10, inline throughput (casual)

Ryzen 7 2700X, boost off, `schedutil` governor, pinned to core 3, no isolation, gcc -O2. H2/T1, seed 1,
7 interleaved repeats of 2^24 samples, medians (within-run interquartile spread ≤ 0.3%). Data:
`experiments/results/experiment16/`. Sanity only: E[X²] ≈ 1 and E[X⁴] ≈ 3 for every variant.

Variants: `*_xoshiro` = one xoshiro256+ call per 53-bit uniform (the unchanged samplers of Experiments
10–14). `*_philox` = one Philox2x64-10 call gives 128 bits, split into fields.
`trapezoid_philox` takes the wedge's u1/u2 from the 32-bit halves of word B, which the wedge path does
not otherwise use. `trapezoid_philox_2call` is the earlier version: the wedge draws a second block
(2 × 53 bits).

## 1. PRNG use per sample

| N | Classical xoshiro | Trapezoid xoshiro | Classical Philox | Trapezoid Philox, 2 calls | **Trapezoid Philox, word-B reuse** |
|---|---|---|---|---|---|
| 8 | 3.70 calls / 237 bits | 4.34 / 278 | 1.147 / 147 | 1.343 / 172 | **1.266 / 162** |
| 32 | 3.21 / 205 | 4.09 / 262 | 1.044 / 134 | 1.092 / 140 | **1.064 / 136** |
| 128 | 3.06 / 196 | 4.03 / 258 | 1.013 / 130 | 1.025 / 131 | **1.016 / 130** |
| 256 | 3.03 / 194 | 4.01 / 257 | 1.007 / 129 | 1.013 / 130 | **1.008 / 129** |

With word-B reuse, every sample that doesn't descend into a refinement table costs exactly one 128-bit
word, and the remaining extra calls are only descents (probability ≈ 2/N per level). The hard maximum is
1 + max(H,T) words (3 for H2/T1, down from 4). Trapezoid now uses the same number of PRNG bits as
Classical, and unlike Classical its maximum is bounded.

## 2. Exact effect of the 32-bit wedge grid (against Experiment 15)

The wedge position w + d·|U1 − U2| becomes w + d·K/2^32 with K = |I1 − I2|. Its exact CDF is in closed
form (`analysis/wedge_precision.py`, checked by brute force), and it was added to the Experiment 15 exact
law. Table: `tables/wedge_precision_vs_exp15.csv`.

| N (H2/T1) | P(wedge) | largest CDF shift | Experiment 15 exact KS | shift / KS | binned δ relative change | variance shift |
|---|---|---|---|---|---|---|
| 8 | 7.75% | 2.0e-12 | 5.5e-5 | 4e-8 | < 1e-8 | −1e-21 |
| 32 | 2.86% | 4.4e-13 | 8.2e-6 | 5e-8 | < 1e-8 | −2e-22 |
| 128 | 0.94% | 1.1e-13 | 1.5e-6 | 7e-8 | < 1e-8 | −2e-23 |
| 256 | 0.53% | 5.3e-14 | 8.0e-7 | 7e-8 | < 1e-8 | −9e-24 |

The grid moves the output distribution about 10⁷ times less than the trapezoid approximation that
Experiment 15 quantifies. The change in δ is at floating-point resolution, and the moments change at
O(2⁻⁶⁴). For any practical purpose the output law is the Experiment 15 law (N=128 H1/T2: same numbers).

## 3. Throughput (Msamples/s, median)

| N | Classical xoshiro | Trapezoid xoshiro | Classical Philox | Trapezoid Philox, 2 calls | Trapezoid Philox, B reuse | Trap/Class, Philox (B reuse) | best Trap / best Class |
|---|---|---|---|---|---|---|---|
| 8 | 32.9 | 43.3 | 31.4 | 40.4 | 41.2 | **1.31×** | 1.32× |
| 16 | 42.5 | 51.4 | 41.5 | 49.8 | 49.8 | **1.20×** | 1.21× |
| 32 | 50.1 | 56.5 | 50.1 | 56.1 | 55.3 | **1.10×** | 1.13× |
| 64 | 55.4 | 59.5 | 56.4 | 59.9 | 58.6 | **1.04×** | 1.06× |
| 128 | 58.8 | 61.1 | 60.5 | 62.1 | 60.4 | **1.00×** | 1.03× |
| 256 | 60.8 | 62.0 | 63.0 | 63.3 | 61.4 | **0.97×** | 1.00× |

## 4. Reading

- **Correction to the first Experiment 16 run.** The first version of `philox2x64.h` looped over the 10
  rounds. GCC compiled that loop worse inside Classical (Classical-Philox 53.9 Msamples/s at N=128) and,
  after word-B reuse, inside Trapezoid as well (+11 instructions per sample, found with `perf stat`).
  With the rounds written out, Classical-Philox gains 12% at N=128 and the earlier "Trapezoid
  1.11–1.28× faster at every N" no longer holds. The corrected same-PRNG result: **Trapezoid is faster
  for N ≤ 64 (1.31× at N=8, 1.10× at N=32) and level with Classical at N=128–256.**
- **Word-B reuse on a CPU:** about 2% faster at N=8, where 7.8% of samples hit the wedge, and 1.5–3%
  slower for N ≥ 32. The slowdown is code generation (about 1.3 more instructions per sample on the
  rectangle path; same branch misses), not PRNG work, and it is close to the run-to-run noise of this
  casual setup (±3% between separate runs). On a CPU the two Trapezoid variants are effectively equal.
- **Where reuse matters is hardware:** one 128-bit word per non-descending sample and a hard maximum of
  1 + max(H,T) words, with an output-distribution change about 10⁷ times smaller than the method's own
  approximation error.
- **Best vs best on this CPU:** Trapezoid leads clearly at small N (1.32× at N=8) and the two are equal at
  N=256. Classical's best here is unpacked xoshiro or Philox; a bit-packed xoshiro Classical has not been
  measured and could move this row.
- **Compiler sensitivity:** at -O3 Classical-Philox was within 1% of its -O2 value after the fix, but
  before the fix it moved by 12%. CPU throughput differences of a few percent between these samplers are
  dominated by code generation and should not be reported as algorithmic.
