# Experiment 04 — Two sample counts

Run from the repository root:

```sh
python3 -B experiments/experiment04.py
```

This repeats Experiment 03 at 100,000,000 and 33,554,432 (=2^25) samples, sequentially.
Each profile measures both Classical Ziggurat and Trapezoid at N=8,16,32,64,128,256,
with seed 1, -O2, five separate performance repetitions, and 100,000 Gaussian
warm-up samples outside timing. Seed reset after warm-up preserves the measured
stream. Trapezoid uses H=2,T=4 and receives all four existing full-data N(0,1)
validation tests. There is no PRNG profiling or Classical statistical validation.

Raw observations pass through a pipe into RAM; no raw sample files, previews,
or subsets are saved. Available RAM is checked using the existing conservative
two full arrays, 24 bounded one-million-value work buffers, and 1 GiB reserve. Previous experiment results and sampling/validation
sources are checked for changes. Matching the existing 100-million-sample Seed 1
streams at N=8,16,32 provides an additional reproducibility check.

Outputs are under `experiments/results/experiment04/` in the usual `raw/`,
`processed/`, `tables/`, `figures/`, `reports/`, and `artifacts/` folders. Each
folder separates profiles into `samples_100000000` and `samples_33554432`.
Combined CSVs and JSON are at the top of `processed/`, with CSV copies in
`tables/`. The main report is `reports/experiment_report.md`. Root execution
and verification records describe all 132 C executions and 48 tests.

Existing output directories are never overwritten. Reproduce in a fresh
location with `--output-root NEW_DIRECTORY`. A failure preserves partial
numerical outputs and stops further work. PASS means fail-to-reject at the
unchanged alpha=0.05; AD decisions retain their existing critical-value method.
Only one seed is used, and there are no second-level uniformity tests.
