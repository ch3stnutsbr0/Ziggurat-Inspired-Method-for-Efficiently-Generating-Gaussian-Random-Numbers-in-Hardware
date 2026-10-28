# Experiment 12: exact output distribution of the Trapezoid sampler

Computes, without generating any random numbers, the exact distribution the Trapezoid sampler produces
with ideal uniforms, and compares it with N(0,1) and with the seed-1 test results of Experiments 10
and 11. The mathematics is in the manual `Trapezoid_Exact_Distribution_Manual.md` (sections 2–7).

## Run

From the repository root (needs gcc and the project `.venv`; about 3 minutes; no CPU isolation or
fixed frequency needed):

```bash
.venv/bin/python -B experiments/experiment12.py
.venv/bin/python -B reports/experiment12/analysis/analyze_experiment12.py     # figures and tables
```

An existing output directory is never overwritten; use `--output-dir DIR` for a fresh run.

## How it works

1. `experiment12_dump_tables.c` includes `c/ziggurat_trapezoid.c` directly, calls `zt_init`, and prints
   every table entry (w, d, a and the boundaries) as CSV. The tables are therefore exactly the ones the
   experiments used; no existing source file is modified.
2. `experiment12.py` applies the descent weights of `zt_gaussian()` (an entry at depth j has weight
   N^-(j+1)), builds the exact mixture CDF, and computes:
   - the exact χ² divergence δ in the experiments' bins (100 over [−5, 5] plus two tails, df = 101);
   - the predicted χ² excess λ = n·δ at n = 2^25, the rejection probability, and the samples needed for
     50% and 90% detection;
   - the exact KS distance, the support bound, the variance error, and tail mass ratios at 3–6σ.
3. All 150 Experiment 11 configurations get δ and λ, which are compared with their seed-1 χ² results to
   validate the model. The 40 configurations that passed all four tests get the full metrics. Classical
   rows (exact, δ = 0) carry the seed-1 Classical results from Experiment 10, which used the same streams
   and bins.

## Configuration (`experiments/experiment12.yaml`)

| Key | Meaning |
|---|---|
| `source_experiment` | Where configurations, seed-1 observations and throughput come from (Experiment 11) |
| `classical_reference` | Seed-1 Classical validation (Experiment 10) |
| `samples` | n used for predictions (2^25) |
| `chi_square` | Binning; must match the source experiment (checked) |
| `ks_grid` | \|x\| grid for the exact KS distance; every trapezoid breakpoint is added |
| `tail_points` | t values for P(\|X\| > t) / P(\|Z\| > t) |

## Outputs (`experiments/results/experiment12/`)

| File | Contents |
|---|---|
| `exact_metrics_passing.csv` | Full exact metrics for the 40 passing configurations plus Classical N=128 and N=256 |
| `model_validation_all.csv` | δ, λ, seed-1 observed excess and its distance from the prediction, for all 150 configurations and Classical at every N |
| `terminal_entries_passing.csv` | Every terminal trapezoid (weight, w, d, a, boundaries) for the 40 passing configurations, for re-analysis in MATLAB |
| `metadata.json` | Build command, source hashes, versions, git state |
