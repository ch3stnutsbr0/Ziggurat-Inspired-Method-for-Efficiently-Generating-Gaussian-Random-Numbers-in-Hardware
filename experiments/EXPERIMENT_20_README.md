# Experiment 20: one-block Trapezoid against Classical, repeated

## Phase 1: goodness of fit (done)

`zt_gaussian_philox_1call` on N = 8…256, H, T = 0…4, seeds 1–15 (two runs: `experiment20.yaml` seeds 1–5, `experiment20_seeds6_15.yaml` seeds 6–15), 2^25 samples per run, χ²/KS/CvM/AD.
All cores; no isolation needed. Classical is not validated (exact by construction).

```bash
.venv/bin/python -B experiments/experiment20.py --dry-run
nohup .venv/bin/python -B experiments/experiment20.py --phase validation > experiment20_validation.log 2>&1 &
tail -f experiment20_validation.log
.venv/bin/python -B reports/experiment20/analysis/analyze_validation.py
```

The driver builds the stream harness (`experiments/experiment20_bench.c`, with block counting) and
the C tests, runs them, reruns one Experiment 13 row as a pipeline check, then validates. Use
`--resume` to continue an interrupted run. Results: `experiments/results/experiment20/validation/`;
report: `reports/experiment20/report.md`.

## Phase 2: timing (not yet implemented)

Isolated CPU 7, boost 0, governor `performance`, 30 seeds. Trapezoid one-block against Classical
Philox fast and Classical xoshiro256+. Repetitions per seed still to be decided.
