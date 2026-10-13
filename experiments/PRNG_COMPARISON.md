# xoshiro256+ PRNG integration and performance comparison

Completed October 13, 2026. No commit was made.

PCG32 remains the default. The two Gaussian algorithms, table geometry, refinements, sampling loop, timing, checksum, and throughput calculations are unchanged. Existing uncommitted work was preserved. This report and the source diff below describe only changes made for this task.

## Selection and endpoint behavior

`prng.type` accepts `pcg32` or `xoshiro256plus`; omitting it defaults to PCG32. The C CLI accepts `--prng` with the same values. Unsupported names fail rather than silently choosing a stream.

`zb_init_prng`/`zt_init_prng` initialize the chosen specialized sampler. `zb_generator`/`zt_generator` return its Gaussian function once before the benchmark loop. Each xoshiro wrapper compiles the original sampler source with renamed symbols and a compile-time uniform adapter. There is no PRNG branch or function-pointer dispatch for individual uniforms. The existing one function-pointer call per Gaussian sample remains. Original sampler entry points still use PCG32, and each specialized sampler has independent singleton state. The existing APIs remain non-thread-safe.

The xoshiro core follows [Blackman and Vigna’s xoshiro256+ 1.0 reference](https://prng.di.unimi.it/xoshiro256plus.c), with four uint64_t words, SplitMix64 seed expansion and a defensive nonzero-state guard. No dynamic memory is allocated by the PRNG. Upper 53 bits are converted with `(double)(r >> 11) * 0x1.0p-53`.

Both PCG32 and xoshiro uniforms occupy `[0,1)`. PCG32 still consumes two 32-bit words per uniform; xoshiro consumes one 64-bit word. The classical tail already evaluates `-log(1-u)`, with argument in `(0,1]`, so zero uniforms are safe and no rejection or remapping is needed. Trapezoid sampling uses the same bounded uniforms in its original arithmetic.

The repository’s PCG implementation is header-only (`pcg_rng.h`); there was no `pcg_rng.c` to preserve. The PCG header is byte-for-byte unchanged from the pre-task snapshot.

CLI text, full-precision BENCHMARK_JSON, summary.json and config.json record the PRNG. Python metadata carries it; xoshiro experiment IDs add `_prngxoshiro256plus`. Legacy PCG IDs/arguments remain unchanged. Missing PRNG fields in old metadata and analysis rows mean PCG32. Analysis grouping includes PRNG to prevent pooling distinct streams.

The existing PCG call-counter mode `--profile-prng` remains PCG32-specific. Selecting xoshiro with it fails clearly before sampling; YAML rejects this combination as well. Both PRNGs support normal performance and validation scheduling. No validation runs were scheduled for the comparison.

## Correctness and integration checks

- Eight fixed xoshiro reference outputs and final state from state {1,2,3,4}: pass.
- SplitMix64 seed-1 fixed state vector, seeds 0/1/2/UINT64_MAX, nonzero initialization, reproducibility and distinct seeds: pass.
- Exact upper-53-bit conversion, lattice resolution, endpoint cases 0 and 1-2^-53, and finite tail logarithms: pass.
- Both algorithms and both PRNGs at all supported classical layer counts (8,16,32,64,128,256), repeated initialization, finite outputs and independent sampler state: pass.
- 245,760 PCG Gaussian samples compared with separately compiled pre-task source across 120 configurations (four seeds, six layer counts, basic plus four trapezoid H/T combinations): exact bit-for-bit agreement. Samples stayed in scalar variables.
- Existing PCG profiling-counter/sequence regression: pass.
- Three new Python test methods covering configuration validation, legacy analysis keys, CLI errors, metadata and output ID separation: pass.
- Small real YAML runs through dry-run, execution and resume for both algorithms/PRNGs: pass. Warmup/reset checks preserve checksums. These runs stored only performance metadata/logs in temporary directories.
- New C deterministic tests with AddressSanitizer and UndefinedBehaviorSanitizer: pass.
- Warning-clean C11 -O2 build and git diff --check: pass.

Validation-scope deviation: the existing basic C regression was also run before its size was inspected. It contains 1,000,000-sample mean/variance/tail-count checks for each of six layer counts, plus its legacy-stream regressions; those passed. This exceeded the requested small deterministic scope. No Chi-square, KS, CvM or Anderson-Darling tests ran. No new raw Gaussian sample datasets were produced. Temporary copies of pre-existing results taken with the baseline source snapshot were removed.

## Focused performance results

Machine: macOS-26.2-arm64-arm-64bit. Compiler: Apple clang version 17.0.0 (clang-1700.6.3.2). Flags: `-std=c11 -Wall -Wextra -pedantic -O2`. All runs used the same executable (SHA256 `2726fc0af8c1ac36e4352fc1ae6819c39ed9f41ac109abfa0540ef7ba1a77efe`).

Each configuration used seed 1, 128 layers, 10,000,000 samples and five repetitions. Trapezoid used H=2/T=4; H/T do not apply to Classical Ziggurat. PRNG order alternated by repetition. No warmup was requested. Initialization and table construction are outside the existing C sampling timer, and the volatile checksum prevents loop elimination. No raw sample output was enabled.

| Gaussian algorithm | PRNG | Layers | H | T | Samples/run | Median M samples/s | Speedup vs PCG32 | Improvement |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Classical Ziggurat | pcg32 | 128 | — | — | 10,000,000 | 161.070 | 1.0000× | 0.00% |
| Classical Ziggurat | xoshiro256plus | 128 | — | — | 10,000,000 | 193.020 | 1.1984× | 19.84% |
| Ziggurat-Trapezoid | pcg32 | 128 | 2 | 4 | 10,000,000 | 136.173 | 1.0000× | 0.00% |
| Ziggurat-Trapezoid | xoshiro256plus | 128 | 2 | 4 | 10,000,000 | 175.451 | 1.2884× | 28.84% |

Speedup is the ratio of median throughputs for the same Gaussian algorithm. Percentage improvement is `(speedup - 1) * 100`. Classical speedup is 1.1984× (+19.84%); trapezoid speedup is 1.2884× (+28.84%).

All observed runs (M samples/s, in repetition order):

| Algorithm | PRNG | Rep 1 | Rep 2 | Rep 3 | Rep 4 | Rep 5 |
|---|---|---:|---:|---:|---:|---:|
| basic | pcg32 | 151.258 | 144.655 | 161.090 | 161.070 | 162.970 |
| basic | xoshiro256plus | 193.020 | 186.961 | 181.416 | 195.130 | 195.072 |
| trapezoid | pcg32 | 128.808 | 86.219 | 141.305 | 136.173 | 139.634 |
| trapezoid | xoshiro256plus | 178.186 | 146.421 | 174.697 | 178.177 | 175.451 |

Observed performance limitation: trapezoid + PCG32 ranged from 86.219 to 141.305 M/s, showing substantial short-run timing variation. Medians reduce sensitivity to that outlier but these are five observations on one machine, not a statistical confidence estimate. Remaining sampler/table/branch/arithmetic and checksum costs were not separately profiled, so the speedups are measured outcomes rather than precise CPU attribution. No added per-uniform dispatch exists.

A small integration check with only 128 samples occasionally measured zero elapsed time because of the existing timer/platform resolution and printed non-finite throughput. That check was repeated with 4096 samples and passed. The benchmark timer and calculations were preserved; the requested 10-million-sample measurements all had positive finite times.

## Files added

- `c/xoshiro256plus.h`
- `c/xoshiro256plus.c`
- `c/prng.h`
- `c/prng.c`
- `c/gaussian_prng.h`
- `c/ziggurat_basic_xoshiro256plus.c`
- `c/ziggurat_trapezoid_xoshiro256plus.c`
- `c/tests/test_prng_selection.c`
- `experiments/tests/test_prng_selection.py`
- `experiments/prng_comparison.py`
- `experiments/prng_comparison.yaml`
- `experiments/PRNG_COMPARISON.md`
- `experiments/results/prng_comparison/{runs.json,comparison.csv,metadata.json}` (summaries and metadata only)

## Files modified

- `c/Makefile`
- `c/benchmark.c`
- `c/ziggurat_basic.c`
- `c/ziggurat_trapezoid.c`
- `c/tests/test_prng_profile_cli.py`
- `experiments/analysis.py`
- `experiments/config.yaml`
- `experiments/main.py`
- `experiments/runner.py`
- `experiments/utils.py`
- `experiments/experiment01.py`

## Reproduce

```sh
make -C c O2
make -C c test-prng-selection
python3 experiments/prng_comparison.py
```

The comparison refuses an existing result directory to avoid overwriting measurements. For a rerun, use a copied configuration with a fresh output_dir. `python3 experiments/main.py --config experiments/prng_comparison.yaml --dry-run` plans the configured single PRNG; `--run` executes it. Change YAML prng.type to select xoshiro. The dedicated comparison script executes both PRNGs.

## Git diff summary

Task source/report scope: 11 modified files and 12 added files; three additional result artifacts. `experiments/experiment01.py` was already untracked at task start and was edited in place. Other pre-existing edits/untracked artifacts remain untouched. No staging or commit was performed. Counts below are relative to the pre-task working-tree snapshot, excluding result artifacts.

Source/report delta relative to that snapshot: **570 insertions, 41 deletions across 23 files**, excluding the three result artifacts.
