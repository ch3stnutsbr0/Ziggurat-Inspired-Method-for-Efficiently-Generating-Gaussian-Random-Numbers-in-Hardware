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

## 5. Base case only (H = T = 0): one Philox call per sample

`zt_gaussian_philox_base()` (in `c/ziggurat_trapezoid_philox.c`) is the Trapezoid sampler without
refinement written as straight-line code: one Philox2x64-10 call, one table lookup, one branch
(rectangle or triangle), no loop. Its output is bit-identical to `zt_gaussian_philox()` at H = T = 0
(checked on 10⁵ samples for every N). Run: `experiments/experiment16.py --config
experiments/experiment16_base.yaml`; data: `experiments/results/experiment16_base/`. All variants use
H = T = 0, and every Trapezoid Philox variant makes exactly 1.000 call per sample.

| N | Classical xoshiro | Classical Philox | Trapezoid xoshiro | Trapezoid Philox (general) | **Trapezoid Philox, base** | base / best Classical | base / general |
|---|---|---|---|---|---|---|---|
| 8 | 32.9 | 31.2 | 43.7 | 45.5 | **63.9** | 1.94× | 1.40× |
| 16 | 42.5 | 41.4 | 50.8 | 52.4 | **72.4** | 1.70× | 1.38× |
| 32 | 50.1 | 50.0 | 55.6 | 56.9 | **78.1** | 1.56× | 1.37× |
| 64 | 55.4 | 56.3 | 58.5 | 59.5 | **81.7** | 1.45× | 1.37× |
| 128 | 58.8 | 60.4 | 60.2 | 60.9 | **83.9** | 1.39× | 1.38× |
| 256 | 60.8 | 63.0 | 61.1 | 61.8 | **85.1** | 1.35× | 1.38× |

**Why the same work runs 38% faster** (`perf stat`, N=128): 118 instead of 153 instructions per sample,
no stack accesses (the general function saves six registers and keeps the Philox round keys on the
stack), branch misses 0.023 instead of 0.037 per sample, IPC 3.03. At 39 cycles per sample the function
is faster than the 10-round Philox chain alone (about 50 cycles), so consecutive samples' Philox work
now overlaps; the general function's larger body prevented that.

**The base case is not a recommended configuration on its own.** Without refinement, the accuracy is
that of Experiment 15's H0/T0 row: at N=128 the exact KS is 5.9e-5, χ² detects the approximation at
about 3.5·10⁵ samples, and the tail stops at 4.11σ (1%-reliable to 3.41σ). These numbers are the
**speed ceiling** of the method. Classical cannot be written this way at all: its rejection loop and
exp/log tail are part of the algorithm.

**Next step this suggests:** keep the base case as the inline fast path and move refinement out of line.
At N=128 only 2/N ≈ 1.6% of samples hit the head or tail strip, so H1/T2 should run close to the base
speed while keeping the Experiment 15 H1/T2 accuracy.

## 6. Fast path with out-of-line refinement

`zt_gaussian_philox_fast()` inlines the base case and moves refinement into a separate cold function
(`refine()`), which runs only when the root index is a refined strip (0 with H > 0, N−1 with T > 0;
probability about 2/N). It consumes Philox blocks in the same order as `zt_gaussian_philox()`, and its
output is **bit-identical** to it (checked on 36 configurations: 6 N × H/T ∈ {0/0, 1/2, 2/1, 4/4, 0/3,
3/0}, 10⁶ samples each, no mismatch). Configs: `experiments/experiment16_fast_H1T2.yaml` and
`_H2T1.yaml`; data: `experiments/results/experiment16_fast_H1T2/` and `_H2T1/`.

H1/T2 (the recommended configuration), Msamples/s, median:

| N | best Classical | Trapezoid Philox, general | **Trapezoid Philox, fast** | base case (ceiling, H0/T0) | fast / best Classical | fast / general | fast / ceiling |
|---|---|---|---|---|---|---|---|
| 8 | 32.9 | 41.1 | **47.2** | 63.9 | **1.43×** | 1.15× | 74% |
| 16 | 42.5 | 49.8 | **60.6** | 72.4 | **1.43×** | 1.22× | 84% |
| 32 | 50.1 | 55.3 | **70.0** | 78.1 | **1.40×** | 1.27× | 90% |
| 64 | 56.3 | 58.6 | **76.0** | 81.7 | **1.35×** | 1.30× | 93% |
| 128 | 60.4 | 60.5 | **79.5** | 83.9 | **1.32×** | 1.31× | 95% |
| 256 | 63.0 | 61.5 | **81.6** | 85.1 | **1.30×** | 1.33× | 96% |

H2/T1 gives the same numbers to within 0.1 Msamples/s; both refine about 2/N of samples. PRNG use is
unchanged: 1.016 calls per sample at N=128 (1.266 at N=8).

**Reading.** With refinement out of line, H1/T2 keeps 95% of the base-case speed at N=128 and the full
Experiment 15 H1/T2 accuracy (exact KS 1.5e-6, χ² detection at 2^27.7 samples, support 6.10σ). Against
the general Classical samplers measured here, Trapezoid is 1.30–1.43× faster at every N. The gap to the
ceiling at small N is the refinement rate: 2/N is 25% of samples at N=8 but 1.6% at N=128.

This comparison is not like for like: the speed-up over the general sampler is a code-layout
optimisation, and Classical had not received it. Section 7 gives Classical the same treatment; that is
the comparison to quote.

## 7. Fast path against fast path

`zb_gaussian_philox_fast()` (`c/ziggurat_basic_philox.c`) applies the same layout to Classical (the
Marsaglia–Tsang structure). Inline: one Philox block, an upper layer, and a candidate inside that strip's
inner rectangle (`cand <= x[layer]`), then the sign. Everything else goes to an out-of-line cold function:
the base strip (base rectangle and exponential tail with `log()`), the boundary test with `exp()`, and
the retries after a rejection. That function continues the attempt it receives and consumes blocks in
the same order, so the output is **bit-identical** to `zb_gaussian_philox()` (6 N × 3 seeds × 10⁶
samples, no mismatch). Config: `experiments/experiment16_fast_compare.yaml`; data:
`experiments/results/experiment16_fast_compare/`. H1/T2, Msamples/s, median of 7:

| N | Classical Philox, general | **Classical Philox, fast** | Trapezoid Philox, general | **Trapezoid Philox, fast** | fast / fast | Philox calls per sample (Classical / Trapezoid) |
|---|---|---|---|---|---|---|
| 8 | 31.4 | **34.7** | 41.1 | **47.2** | **1.36×** | 1.147 / 1.266 |
| 16 | 41.6 | **48.0** | 49.8 | **60.5** | **1.26×** | 1.081 / 1.129 |
| 32 | 50.1 | **60.2** | 55.3 | **69.8** | **1.16×** | 1.044 / 1.064 |
| 64 | 56.4 | **69.8** | 58.6 | **75.5** | **1.08×** | 1.024 / 1.032 |
| 128 | 60.5 | **76.4** | 60.4 | **78.6** | **1.03×** | 1.013 / 1.016 |
| 256 | 63.0 | **80.5** | 61.4 | **80.3** | **1.00×** | 1.007 / 1.008 |

The minimum and maximum of the 7 repeats lie within about ±1% of the median for every entry.

perf at N=128 (per sample, including the benchmark loop): Classical fast 121 instructions, 43.7 cycles;
Trapezoid fast 133 instructions, 44.7 cycles; Classical general 149 instructions, 55.1 cycles.

**Reading.**
- The layout gain is about the same for both: +26% for Classical and +30% for Trapezoid at N=128. The
  earlier "1.3× at large N" was a layout effect, not an algorithmic one.
- With equal effort, Trapezoid is faster at small N (1.36× at N=8, 1.16× at N=32). At N ≥ 128 the two
  run at the same speed on this CPU (1.03× and 1.00×, within run-to-run noise).
- At large N, both need few extra blocks (1.3% for Classical at N=128, 1.6% for Trapezoid). The cost is then the Philox block itself (about 44 cycles per sample against the
  about 40 of the H0/T0 ceiling), so the algorithms are indistinguishable. Trapezoid's fast path has
  slightly more instructions (the rectangle/wedge branch and wedge arithmetic run inline); Classical's
  is a single multiply and compare, but it pays `exp()`/`log()` on its rare slow path.
- At small N, Classical's slow path is entered more often and is expensive (`exp()` in the boundary
  test, `log()` in the tail, rejection retries). Trapezoid's slow path is only further table lookups.
- So on a CPU, Trapezoid's speed advantage is a small-N result. Its arguments at the recommended
  N=128 are those of the paper's hardware case: no `exp()`/`log()`, bounded worst case (at most H or T
  extra blocks against Classical's unbounded rejection loop), and a known output law (Experiment 15).
  Throughput parity on a CPU at N=128 is consistent with that argument; it is not evidence for it.

## 8. One Philox block per sample for every H and T (`zt_gaussian_philox_1call`)

A descent only looks at the k index bits of the block; the other 121 bits are still unused,
uniform and independent of the event "index = 0 or N−1". The one-block sampler therefore reads the
descent indices from word A instead of drawing new blocks:

```
word A: [idx0: k][idx1: k] … [idx_L-1: k][sign: 1] … [decision: low D bits]
        L = 1 + max(H, T),  D = min(53, 63 − k·L)
word B: unchanged (rectangle position, or wedge u1 | u2)
```

Level j of a descent uses idx_j. The fields are disjoint bits, so the descent weights are exactly
N^-(level+1), as before. The only change of law is the decision threshold: ⌈a·2^D⌉/2^D instead of
⌈a·2^53⌉/2^53. The wedge path needs all of word B and 1 + 53 bits of word A, so the extra indices can
only come from the decision field. Every sample costs exactly **one block**, and the descent is a pure
table-address calculation with no loop over blocks.

**Checks.**
- `c/tests/test_trapezoid_philox_1call.c` compares the optimised map with a plain field-by-field
  reference, bit for bit. It covers 6 N × 9 H/T settings × 4·10⁵ blocks, with index fields forced onto
  refined strips so that every descent depth is reached: 0 mismatches.
- Philox blocks per sample: exactly 1.000000 at every N (count mode).
- E[X²] and E[X⁴] over 4 seeds × 2.5·10⁷ samples agree with the fast path within sampling error.
- Exact effect of the D-bit decision (`reports/experiment16/analysis/onecall_precision.py`,
  `tables/onecall_precision_vs_exp15.csv`), as the largest shift of the CDF:

| N | H1/T2: D | max CDF shift | / Exp 15 exact KS | H4/T4: D | max CDF shift | / Exp 15 exact KS |
|---|---|---|---|---|---|---|
| 8 | 53 | 4e-19 | 4e-15 | 48 | 3e-16 | 5e-12 |
| 32 | 48 | 4e-16 | 5e-11 | 38 | 4e-13 | 5e-8 |
| 128 | **42** | **2.6e-14** | **1.7e-8** | 28 | 4.4e-10 | 2.9e-4 |
| 256 | 39 | 2.3e-13 | 2.9e-7 | 23 | 1.5e-8 | 1.9e-2 |

At H1/T2 and H2/T1 the effect is negligible at every N. At N=256 H4/T4 it reaches 2% of the
sampler's own KS error, which is still small but no longer negligible. The layout is refused if
fewer than 20 decision bits remain.

**Throughput**, H1/T2, Msamples/s, median of 7 (`experiments/experiment16_onecall.yaml`,
`experiments/results/experiment16_onecall/`):

| N | Classical fast | Trapezoid fast | **Trapezoid 1call** | base ceiling (H0/T0) | 1call / Classical fast | 1call / Trapezoid fast | 1call / ceiling |
|---|---|---|---|---|---|---|---|
| 8 | 35.6 | 47.6 | **56.3** | 64.0 | **1.58×** | 1.18× | 88% |
| 16 | 49.2 | 60.8 | **67.2** | 72.5 | **1.37×** | 1.11× | 93% |
| 32 | 61.3 | 69.9 | **74.4** | 78.2 | **1.21×** | 1.06× | 95% |
| 64 | 70.6 | 75.4 | **78.8** | 81.8 | **1.12×** | 1.05× | 96% |
| 128 | 77.0 | 78.6 | **81.3** | 83.9 | **1.06×** | 1.03× | 97% |
| 256 | 81.0 | 80.3 | **82.7** | 85.1 | **1.02×** | 1.03× | 97% |

Classical fast ran 0.6–1.2 Msamples/s faster here than in section 7 (76.4 → 77.0 at N=128), which
is the size of the run-to-run variation.

**Reading.**
- Unlike sections 6 and 7, this is an algorithmic change, not a code-layout change: it removes the
  extra blocks a descent used to cost, so the PRNG work is now exactly one block per sample.
  Classical cannot do the same. After a rejection it must draw fresh bits, because the rejected
  attempt's bits are no longer independent of the outcome.
- On the CPU it gains 3% at N ≥ 128 and up to 18% at N=8, and keeps 97% of the base-case ceiling at
  N=128. Against Classical fast it is 1.58× at N=8, 1.21× at N=32 and 1.06× at N=128. At N=256 it
  is 1.02×, a tie within run-to-run variation.
- For hardware the larger point is determinism: one Philox block per output, always. Refinement
  becomes combinational logic on idx0, idx1 and idx2 in front of the table address, with a fixed
  pipeline depth. No refinement FIFO and no second random source are needed.
