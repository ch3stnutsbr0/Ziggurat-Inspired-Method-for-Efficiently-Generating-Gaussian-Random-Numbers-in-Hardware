# Experiment 23: operation counts and energy per sample

Part 1 counts, exactly, the operations each sample uses (Philox blocks, attempts, table reads,
conversions, multiplies, adds, compares, divisions, `exp`, `log`) for the Trapezoid one-block
sampler over the full H/T grid and for the Classical Philox fast-path sampler, N = 8..256.
Part 2 turns the counts into a distribution of energy per sample with a stated, swept
per-operation energy model, and derives energy budgets (the energy needed to cover all but a
fraction ε of samples or windows). Report: `reports/experiment23/report.md`.

## How the counts are taken

- `c/ziggurat_opcount.h` defines counter macros. They are compiled in only with
  `-DZIGGURAT_COUNT_OPS`; without it they expand to nothing, and the object code of
  `c/ziggurat_basic_philox.c` and `c/ziggurat_trapezoid_philox.c` is identical to before (checked
  with `objdump`).
- Operations are counted per algorithmic step. The Classical fast-path test that the CPU code
  repeats at the start of its out-of-line slow path is counted once.
- `experiments/experiment23_count.c`:
  - `count`: draws samples and prints the histogram of per-sample operation vectors.
  - `enumerate`: feeds crafted blocks to `zt_philox_1call_map()` so that every Trapezoid path
    (main, head, tail; every depth; rectangle and wedge) runs once. This gives the Trapezoid's
    operation counts on paths too rare to be sampled.

Nothing is timed, so isolation, boost and permissions do not matter.

## Run

```
.venv/bin/python -B experiments/experiment23.py --dry-run
.venv/bin/python -B experiments/experiment23.py                        # about 25 min on CPUs 0-6
.venv/bin/python -B reports/experiment23/analysis/energy_model.py       # about 1 min
```

## Output (`experiments/results/experiment23/`)

- `op_vectors.csv`: one row per distinct operation vector per (configuration, seed), with its count.
- `trap_paths.csv`: every Trapezoid path's operation vector, per (N, H, T).
- `metadata.json`, `config.yaml` (the energy-model assumptions are in the config).
