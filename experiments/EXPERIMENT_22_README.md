# Experiment 22: consistency of the time per sample

Measures the distribution of the time per sample (core cycles) of the Trapezoid one-block
sampler (H1/T2 and H0/T0) and the Classical Philox fast-path sampler, for N = 8..256, with the
PRNG inline and precomputed, per sample (fenced) and over windows of 16 and 256 samples.
Report: `reports/experiment22/report.md`.

## Requirements

- CPU 7 isolated (`isolcpus=...7`) and governor `performance`. Boost is recorded, not required.
- User-space access to the cycle counter: `/proc/sys/kernel/perf_event_paranoid` at most 2,
  and rdpmc enabled (the default `/sys/bus/event_source/devices/cpu/rdpmc` = 1).

## Run

```
.venv/bin/python -B experiments/experiment22.py --dry-run
.venv/bin/python -B experiments/experiment22.py            # about 5 min
.venv/bin/python -B reports/experiment22/analysis/analyze_experiment22.py
```

The driver refuses to overwrite an existing output directory (`--output-dir` for a new one).

## Output (`experiments/results/experiment22/`)

- `runs.csv`: one row per run: mean, variance, SD, CV, p50 … p99.9999 and max of cycles per
  sample (window cycles / W), calibrated counter overhead, `counter_moved`, blocks per sample
  (precomputed mode).
- `hist.csv`: histograms of cycles per window, pooled over seeds, per configuration.
- `metadata.json`: build commands, binary hashes, machine state at start and end, git commit.
