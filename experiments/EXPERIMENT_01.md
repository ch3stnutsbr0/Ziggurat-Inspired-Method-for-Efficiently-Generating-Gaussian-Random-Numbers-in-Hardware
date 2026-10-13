# Experiment 01

**Gaussian RNG Performance and Statistical Accuracy Comparison** runs Basic Ziggurat,
Unrefined Trapezoid, and the nonzero H/T refinement grid at N=8, 16, and 32.
The full profile is `experiment_01.yaml`. The original `config.yaml` remains the
smoke-test profile and its results are untouched.

## Run

From the repository root:

```sh
cd c && make O2 && cd ..
python3 -B experiments/main.py --config experiments/experiment_01.yaml --dry-run
python3 -B experiments/main.py --config experiments/experiment_01.yaml --run
```

If interrupted, continue with the **same executable build**:

```sh
python3 -B experiments/main.py --config experiments/experiment_01.yaml --run --resume
```

The full profile schedules 78 configurations, 780 unbuffered performance runs,
78 PRNG profiling runs, and 78 binary validation runs. The 858 performance and
validation executions in the specification exclude the 78 separate PRNG profiling
executions. Performance configurations are shuffled reproducibly within each of
ten repetition rounds; the schedule seed and execution order are saved. All C
processes run sequentially. C sampling time is used for throughput; Python wall
time is a separate field. Initialization time is null because the C benchmark
does not report it.

PRNG profiling uses the existing `--profile-prng` CLI with the same configured
microbenchmark iterations for every configuration. That CLI couples counts to a
five-repetition uniform microbenchmark, so the isolated calibration runs once
per configuration. This adds negligible work relative to the configured
100-million-sample Gaussian passes and preserves the C profiling implementation.
The PRNG cost and fraction are estimates; they are not exact CPU attribution.

## Data and resource policy

Each validation run generates all 100 million binary64 samples (800 MB), checks
the C summary against the complete binary, and applies Pearson Chi-square,
fixed-null two-sided KS, Anderson-Darling, and Cramér-von Mises to the complete
dataset. The full profile sets `keep_validation_samples: false`. After the four
results, moments, and tail counts are saved and their JSON and SHA-256 integrity
records pass readback checks, only that run's `samples.bin` is deleted. A failed
or interrupted validation retains its binary. No sample preview or subset is
saved. Set the option to `true` only when enough disk exists for 62.4 GB of
validation binaries plus working space.

For large datasets, the validation code memory maps the binary, creates one
sorted full-data copy, and computes statistics in bounded chunks. This changes
array handling, not test definitions. The chunked statistic and p-value paths
are regression-tested against the existing implementations. KS uses SciPy's
`kstwo.sf`, the same calibration as `kstest(..., method="exact")`; CvM uses the
same SciPy finite-sample CDF helper called by `cramervonmises`. AD retains the
previous Marsaglia-Marsaglia approximation and its explicit resolution flag.
Very small p-values that underflow are marked; none are assigned an invented
minimum. Binomial sampling noise limits interpretation of rare tail errors.

Preflight checks the executable, dependencies, all configurations through actual
C initialization, output collisions, free disk, and available RAM. The RAM
bound is three full-size float64 arrays plus 1 GiB. A per-validation check
repeats the memory and disk guards. If a guard fails, the full run stops and
can be resumed without discarding completed results.

## Outputs

`experiments/results/experiment_01/` contains:

- `raw/performance/`, `raw/profiling/`, and `raw/validation/` run records;
- `processed/` performance, PRNG, validation, tail, and combined CSV files;
- `tables/primary_comparison.csv` and `tables/detailed_comparison.csv`;
- `figures/` PDF and PNG exports for all seven requested figure types;
- `reports/experiment_report.md`;
- `artifacts/benchmark`, a byte-for-byte copy of the executable;
- `execution_order.json` with status and execution order.

Every run records its seed, configuration, sample count, timestamp, status,
executable SHA-256, Git commit (when available), and command. Compiler flags and
CPU architecture from the C profiling output are joined into the combined
summary. Build hashes are part of aggregation keys; different builds are not
pooled. A test failure means rejection at the configured per-test alpha. A
pass is failure to reject, not proof of exact Gaussianity. Conclusions from
one validation seed are preliminary.

## Verification

```sh
python3 -B -m unittest discover -s experiments/tests -v
cd c && make test
```

A reduced end-to-end pilot should use a separate YAML file and output directory;
never change the full profile's sample count or repetition count to create a
pilot. The pilot checks collection, profiling, full-data validation, deletion,
aggregation, figures, and resume without mixing with the full results.
