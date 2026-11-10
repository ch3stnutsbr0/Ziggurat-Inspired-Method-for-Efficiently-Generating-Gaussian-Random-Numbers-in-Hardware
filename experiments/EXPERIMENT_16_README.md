# Experiment 16: bit-packed Philox2x64-10 uniforms, inline throughput (casual)

Compares Classical and Trapezoid (H2/T1, N = 8…256) with two uniform sources, both generated inline:

| Variant | Uniform source |
|---|---|
| `*_xoshiro` | xoshiro256+, one 64-bit call per uniform (the samplers of Experiments 10–14, unchanged) |
| `*_philox` | Philox2x64-10, one call = 128 bits, split into bit fields (new) |
| `trapezoid_philox_2call` | as `trapezoid_philox`, but the wedge draws a second block (earlier version) |

No CPU isolation and no statistical validation. The run only checks that mean, E[X²] and E[X⁴]
come out near 0, 1 and 3.

## Run

```bash
.venv/bin/python -B experiments/experiment16.py      # about 95 s; pins to the core in experiment16.yaml
.venv/bin/python -B reports/experiment16/analysis/wedge_precision.py   # exact 32-bit wedge effect vs Experiment 15
```

## New code

- `c/philox2x64.h`: Philox2x64-10 (Random123 algorithm), rounds written out (a round loop compiled
  worse under GCC -O2). `c/tests/test_philox2x64.c` checks the three
  Random123 known-answer vectors and the counter stream; it runs at the start of every Experiment 16 run.
- `c/ziggurat_trapezoid_philox.c`: Trapezoid with bit-packed uniforms. Common path: **one call**.
  Word A holds the index (top log2 N bits), the sign (next bit) and the rectangle/wedge decision
  (low 53 bits); word B holds the rectangle position or, on the wedge path, u1/u2 as its two 32-bit
  halves, so a non-descending sample costs **exactly one call**. A refinement descent takes a fresh call.
  Each strip is stored as one 32-byte entry {w, w·2⁻⁵³, d·2⁻³², ⌈a·2⁵³⌉}. The decision is an integer
  compare, |u1 − u2| is computed exactly in integers, and the sign is OR-ed in. The rectangle path is
  bit-identical to `zt_gaussian()`; the wedge lies on a d·2⁻³² grid (exact effect:
  `reports/experiment16/analysis/wedge_precision.py`). `-DZT_PHILOX_WEDGE_SECOND_CALL` (built as
  `c/ziggurat_trapezoid_philox_2call.c`) gives the earlier variant with a second call and 2 × 53 bits.
- `zt_gaussian_philox_base()` (same file): base case only (H = T = 0), straight-line code with exactly
  one Philox call per sample; bit-identical output to `zt_gaussian_philox()` at H = T = 0. Timed with
  `--config experiments/experiment16_base.yaml` (variant `trapezoid_philox_base`).
- `zt_gaussian_philox_fast()` (same file): base case inline, refinement in an out-of-line cold function;
  bit-identical output to `zt_gaussian_philox()` for every H and T. Timed with
  `--config experiments/experiment16_fast_H1T2.yaml` (and `_H2T1.yaml`), variant `trapezoid_philox_fast`.
  Pseudocode of both samplers: `reports/experiment16/pseudocode.md`.
- `zb_gaussian_philox_fast()` (`c/ziggurat_basic_philox.c`): Classical with the same layout (inner-rectangle
  accept inline; base strip, tail, `exp()` test and retries out of line); bit-identical to `zb_gaussian_philox()`.
  Fast against fast: `--config experiments/experiment16_fast_compare.yaml`.
- `zt_gaussian_philox_1call()` (`c/ziggurat_trapezoid_philox.c`): exactly one block per sample for every H
  and T. The descent indices are read from word A ([idx0..idx_L-1][sign][decision: D bits]), with
  D = min(53, 63 − k(1 + max(H, T))). The test is `c/tests/test_trapezoid_philox_1call.c` (against a
  plain reference); the exact effect of D is computed by `reports/experiment16/analysis/onecall_precision.py`.
  Timed with `--config experiments/experiment16_onecall.yaml`.
- Random-bit usage per step (Classical, Trapezoid base case, Trapezoid refinement): `reports/experiment16/bit_usage.md`.
- `c/ziggurat_basic_philox.c`: Classical with the same packing (one call per attempt: layer, sign and
  position in A; the strip or base test in B; one call per exponential-tail candidate), so the comparison
  isolates the algorithm rather than the PRNG.
- `experiments/experiment16_bench.c`: harness (`time` and `count` modes). `experiments/experiment16.py`
  drives it.

Both files include the unchanged `ziggurat_trapezoid.c` / `ziggurat_basic.c` for their tables and require
N to be a power of two.

## Outputs (`experiments/results/experiment16/`)

`timing_raw.csv` (every repeat), `prng_counts.csv` (PRNG calls and bits per sample, moments),
`summary.csv` (median throughput, ns/sample, speed-ups), `metadata.json` (build commands, boost, governor).
