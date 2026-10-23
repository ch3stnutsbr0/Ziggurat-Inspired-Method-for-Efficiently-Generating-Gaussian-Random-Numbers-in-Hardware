# Experiment 10 — Classical vs Trapezoid H=0/T=0 vs Trapezoid H=2/T=4

Run from the repository root (Linux, gcc, `.venv` with psutil):

```sh
.venv/bin/python -B experiments/experiment10.py
```

Same format as Experiment 05 with a third configuration. xoshiro256+, seed 1, -O2, N=8,16,32,64,128,256,
2^25 samples per run, no Gaussian warmup. Configurations: Classical, Trapezoid H=0/T=0, Trapezoid H=2/T=4.
Performance: 5 shuffled repetitions, each run a separate process pinned to CPU 7 with `taskset`, cumulative
checkpoints at 100k, 1M, 10M, 2^25 (`experiment10_benchmark.c` takes head/tail as arguments).
Validation: all four existing tests (Chi-square with 100 interior bins, KS, CvM, AD) at alpha=0.05 against
fixed N(0,1) on the full 2^25 stream; samples go through a pipe into RAM and are discarded.
90 timing runs, 18 validation runs, 72 tests. Environment: BIOS cap 3.2 GHz, boost off, SMT off, no CPU isolation.

Outputs: `experiments/results/experiment10/` (artifacts, raw, processed, tables, figures, reports,
execution_order.json, verification.json). Report: `reports/experiment_report.md`.

Results (single seed, no multiple-testing correction):
- Both Trapezoid variants are faster than Classical: 1.33x/1.31x at N=8 (H0T0/H2T4), shrinking to 1.03x at N=256.
  H2T4 vs H0T0 speed differs by under 2%.
- Classical passes all 24 tests. H2T4 rejects 5 (mostly Chi-square at small N; all four tests pass at N=128, 256).
  H0T0 rejects 15, including KS/CvM/AD at N<=32 and Chi-square at every N.
