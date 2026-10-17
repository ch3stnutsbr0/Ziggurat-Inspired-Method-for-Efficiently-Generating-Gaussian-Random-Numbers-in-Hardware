# Precomputed uniform mode

The default remains `inline`. The original PCG32 and xoshiro256+ samplers and
conversions are retained, with the original timed inline loops and compiler flags.
Precomputed specializations include the same Classical and Trapezoid source files;
only `uniform()` changes. No acceptance, rejection, approximation, or refinement
logic changes. Every random input currently uses this function, including layer
selection, sign, rectangle/triangle candidates, rejection tests, and tail draws.
There are no independent integer/bit requests to translate or approximate.

## C commands (from the repository root)

Build once:

```sh
make -C c O2
```

Equivalent standalone benchmark commands (these are examples, not routine tests):

```sh
./c/benchmark --algorithm basic --layers 128 --prng pcg32 --seed 1 --samples 1000000 --uniform-mode inline --report-json
./c/benchmark --algorithm basic --layers 128 --prng pcg32 --seed 1 --samples 1000000 --uniform-mode precomputed --report-json
```

Use `--algorithm trapezoid --layers 8 --head 2 --tail 4` for refined Trapezoid,
and `--prng xoshiro256plus` for xoshiro256+. Omission of `--uniform-mode` means
inline. Both modes retain the existing output and warm-up options. Warm-up is
outside timing; buffered warm-up resets the read position before measurement.

The default dynamically allocated contiguous double buffer is exactly
`2 * 1024 * 1024 * 1024` bytes, or 268,435,456 binary64 values. Size calculations
use `size_t`; input overflow, invalid sizes and allocation failures are rejected.
Seeding and filling use the selected existing PRNG and its existing conversion.
Initialization, heap allocation, file-cache I/O, filling, warm-up, and cleanup
are all outside the monotonic-clock sampling timer.

During measurement, each draw reads `values[position++]`. A checked static inline
accessor avoids function-pointer dispatch per uniform and detects exhaustion
without wraparound. A single `setjmp` checkpoint per output batch (or per entire
no-output run) permits safe escape even from unbounded rejection loops. No PRNG
state is advanced in the buffered path. The Gaussian function pointer is selected
once, just as in the existing benchmark.

Exhaustion exits with status 3, reports consumed uniforms and completed samples,
and marks JSON results `complete: false`, `buffer_exhausted: true`. Throughput
fields are null. A partially generated Gaussian is excluded from the completed
sample count, but its uniform reads count toward consumption. Partial binary
output can remain for diagnostics. The Python runner marks the run failed;
analysis refuses to treat it as a valid performance result. Warm-up exhaustion
also stops safely before a measurement starts.

## Python configuration and session reuse

Add to the existing YAML structure:

```yaml
prng:
  type: xoshiro256plus
uniform_mode: precomputed
uniform_buffer_size_gib: 2
```

All existing algorithm, seed, sample, repetition, validation and output options
still apply. `uniform_buffer_size_gib` is constrained to exactly 2. For small
correctness tests only, `uniform_buffer_size_bytes: 65536` overrides that size.
Dry-run plans include the source mode, byte capacity, mode-specific experiment
IDs and exact C arguments. Existing inline IDs remain unchanged.

```sh
python3 -B experiments/main.py --config experiments/config.yaml --dry-run
python3 -B experiments/main.py --config experiments/config.yaml --run
```

Set `uniform_mode: inline` or `precomputed` in your chosen YAML before running.
Neither command above changes that configuration automatically. Existing inline
PCG profiling remains available. The distinct `--profile-prng` pass and
`--counters` are rejected for buffered benchmarks; they describe inline PRNG
computation or the original sampler instances. Disable `profiling.enabled` when
selecting precomputed mode in an Experiment 01 configuration.

The Python runner and Experiment 01 orchestrator use a private temporary session
cache keyed by PRNG, seed and size. The first subprocess fills the buffer and
writes the cache outside timing. Later subprocesses load the identical values
into their own heap buffer, also outside timing. The cache is deleted at session
exit. Allocation cannot be shared across the existing isolated subprocesses;
PRNG generation is shared. Cache storage therefore requires an additional 2 GiB
of temporary disk per distinct stream. Standalone C runs have no cache unless
`--uniform-buffer-cache FILE` is supplied. That optional cache is a local native
format with a checked version/PRNG/seed/count header; incompatible or truncated
caches fail instead of being silently used. Use only trusted, session-owned files.

Each run starts at buffer position zero. Repeated runs with the same seed therefore
reproduce the same Gaussian sequence and paths, as inline repetitions already do.
They measure timing variation, not statistically independent datasets. Use distinct
seeds for independent streams. There is never cyclic reuse within a run.

## Metrics and comparison

`summary.json` and `BENCHMARK_JSON` retain existing fields and add uniform mode,
completed Gaussian count, consumed uniforms, uniforms/sample, byte capacity,
utilization fraction, complete/exhausted flags and million-samples/second.
Capacity and utilization are zero for inline mode. Full precision JSON is opt-in
on the CLI and automatically requested by buffered harness runs. Text output also
reports mode, consumption, utilization and status. Inline consumption is measured
by a separate exact deterministic replay with counting enabled, after sampling
and outside timing; this increases total process time without changing throughput.
Python wall-clock duration thus includes work that C sampling time excludes.

Keep algorithm, layers, H/T, seed, sample count, PRNG, executable/compiler flags,
warm-up, output mode and machine conditions equal. Pair only complete results.
The analysis helper aggregates complete matching performance runs by median
throughput and calculates `precomputed / inline`; it also matches executable hash.
For results collected by the runner in separate inline/precomputed output roots:

```sh
python3 -B experiments/analysis.py --uniform-speedups /path/to/inline/results /path/to/precomputed/results
```

The buffer removes PRNG computation from timing but includes sequential memory
read costs, bounds checks, cache and memory-bandwidth effects. This is not
zero-cost uniform access and does not directly predict FPGA throughput. It is a
software baseline for FPGA-oriented Gaussian RNG architecture research.

## Small correctness tests

```sh
make -C c O2 test-uniform
python3 -B -m unittest discover -s experiments/tests -p test_prng_selection.py
```

The new tests allocate at most 64 KiB per uniform buffer. They compare exact
streams and sample sequences for both PRNGs, both algorithms, several layer counts,
and multiple seeds; exercise warm-up, exhaustion, output/JSON, cache reuse and
resume; and instrument both raw PRNG step functions to prove zero steps during
buffered sampling. The instrumentation exists only in the test build.
No production 2 GiB allocation or large experiment is needed to run these tests.
