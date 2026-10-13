# Layer-count throughput and Trapezoid validation comparison

Run from the repository root:

```sh
python3 -B experiments/layers_comparison.py
```

The driver compiles the existing C implementations with `-O2` into a temporary
executable, preserving `c/benchmark`. It measures N=8,16,32,64,128,256 with five
separate process runs per algorithm and 10 million samples per run. Each run
warms up 100,000 Gaussian values, resets to seed 1, then uses the existing
unbuffered timed loop. Initialization, table construction, warm-up, seed reset,
and reporting are excluded. The checksum and moment accumulation remain part
of the identical timed loops for both algorithms. Algorithms are reproducibly
shuffled within each repetition round. All repetitions use the same seeded
stream; their timing measurements are separate, not independent random streams.

Trapezoid validation uses H=2,T=4,seed=1 and 10 million values for each N. C writes
binary64 values only to an OS pipe; Python reads them into an 80 MB NumPy array.
No raw Gaussian sample file, preview, or subset is saved. The existing chunked
full-data tests create one sorted copy and bounded work arrays. Their settings
come from `experiments/config.yaml` (alpha 0.05, 100 interior bins over [-5,5],
two unbounded tails, minimum expected count 5). There is no standardization or
parameter fitting. PASS means fail-to-reject, not proof of normality. AD uses
its existing approximate calibration and critical value; omitted p-values
are written as NA with the resolution flag in the numerical JSON.

Outputs are the requested CSV tables and 300-DPI PNG in `experiments/results/experiment03/processed/`
and `experiments/results/experiment03/figures/`, plus numerical JSON results and minimal metadata under
`experiments/results/experiment03/artifacts/`. Existing named outputs cause a refusal rather than an
overwrite. For another run use `--output-root experiments/results/another-layer-comparison`.
No previous experiment results, MATLAB files, sampling algorithms, or PRNG
implementations are changed by execution. Validation timings are excluded
from the performance table.

Warm-up and pipe-transfer regression checks (hold samples only in RAM):

```sh
python3 -B c/tests/test_benchmark_warmup.py /path/to/new/benchmark c/benchmark experiments/layers_comparison.py
```

The completed run is organized under `experiments/results/experiment03/`, with
`raw/`, `processed/`, `tables/`, `figures/`, `reports/`, and `artifacts/` like the
previous experiments. Comparison tables and the report are saved from the
completed numerical results; reorganization does not repeat sampling.
