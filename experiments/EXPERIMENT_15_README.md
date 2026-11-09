# Experiment 15: exact theory over the full N × H × T grid

Extends the exact model of Experiment 12 from the 40 passing configurations to all 150
(N = 8…256, H = 0…4, T = 0…4). No random numbers are generated. It answers two questions:

1. **Tail reach:** how far into the tails is the output reliable, both for a fixed tolerance and for a
   given number of samples?
2. **Refinement:** how much do the head (H) and tail (T) levels improve goodness, and in which |x| region?

## Run

From the repository root (needs gcc and the project `.venv`; about 30 s; no CPU isolation needed):

```bash
.venv/bin/python -B experiments/experiment15.py
.venv/bin/python -B reports/experiment15/analysis/analyze_experiment15.py     # figures, tables, fits
```

An existing output directory is never overwritten; use `--output-dir DIR` for a fresh run.

## How it works

- Tables come from `c/ziggurat_trapezoid.c` through the Experiment 12 exporter
  (`experiment12_dump_tables.c`); the descent weights N^-(level+1) are the same as in Experiment 12.
- The |X| density is continuous and piecewise linear. It is evaluated exactly at every breakpoint as a
  sum of non-negative terms and interpolated linearly in between. Tail masses P(|X| > t) are integrated
  from the right, so they stay accurate right up to the support edge (Experiment 12 used 1 − F, which
  loses precision beyond about 6σ).
- Integrals (divergences, moments) use 12-point Gauss–Legendre on every linear piece, split to width
  ≤ 0.02. The region beyond the support is added analytically.
- Cross-check against Experiment 12: binned δ for all 150 configurations, and KS, support, variance
  and tail ratios for the 40 passing ones, agree to ≤ 1e-9 relative error. Every density integrates to 1
  within 1e-15.

## Metrics (`experiments/results/experiment15/exact_theory_all.csv`)

| Column | Meaning |
|---|---|
| `D_continuous` | χ² divergence ∫(g − φ)²/φ dx, with no binning |
| `D_region_a_b` | contribution of a ≤ \|x\| < b to D (`5_inf` includes everything beyond the support) |
| `delta_binned`, `chi2_n_detect_50/90` | Experiments 10/11 binned divergence and the samples needed for 50%/90% χ² detection |
| `ks_exact`, `ks_n_detect_approx` | exact KS distance and the approximate samples to detect it |
| `total_variation`, `hellinger2` | ½∫\|g − φ\|, ½∫(√g − √φ)² |
| `variance_error`, `kurtosis_error` | Var − 1, excess-kurtosis error |
| `support`, `support_n_one_missing` | largest \|x\| the sampler can output; 1/(2Q(support)) = samples per expected out-of-support normal event |
| `reach_survival_eps{ε}` | largest t with \|P(\|X\|>u)/P(\|Z\|>u) − 1\| ≤ ε for all u ≤ t |
| `reach_density_eps{ε}` | the same with the pointwise density ratio (stricter; limited by the body layers) |
| `tail_budget_n/log2`, `tail_budget_at_t` | smallest n at which a tail-count test P(\|X\| > t), t ≥ 2, reaches 50% power (two-sided, α = 0.05), and where it happens |
| `R_n2^k` | reliable reach at n = 2^k: largest t such that no tail-count test at 2 ≤ u ≤ t reaches 50% power. `inf` means none does; a value just below 2.0 means one fails already at 2σ |
| `tail_ratio_{3..7}` | P(\|X\|>t)/P(\|Z\|>t) |

`tail_curves.csv` holds the survival ratio, density ratio and tail-test sample count on a 0.05 grid for
every configuration, for MATLAB. Configuration keys are documented in `experiment15.yaml`.
