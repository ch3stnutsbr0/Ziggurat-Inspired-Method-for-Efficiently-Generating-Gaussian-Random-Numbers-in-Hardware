# Linux Ryzen 2700X benchmark workspace

This is an environment verification configuration, not a statistically comprehensive benchmark study. The configured schedule was NOT executed during setup. Future runs below generate millions of samples and require a separate decision to execute.

## Workstation and environment

- Linux Mint 21.3 (Virginia), x86_64; kernel 5.15.0-198-generic.
- AMD Ryzen 7 2700X: 8 cores, 16 threads, SMT, one socket; frequency policy 2.2–3.7 GHz, boost enabled.
- Aggregate caches: L1 data 256 KiB, L1 instruction 512 KiB, L2 4 MiB, L3 16 MiB.
- RAM approximately 62 GiB; disk approximately 3.3 TB available (dynamic snapshots).
- GCC 11.4.0; system Python 3.10.12.
- Observed scaling driver `acpi-cpufreq`, governor `schedutil`. CPU, power management, network, OS and kernel settings were not changed. No sudo or package installation was used.
- Repository: `~/projects/Ziggurat-Inspired-Method-for-Efficiently-Generating-Gaussian-Random-Numbers-in-Hardware`, branch `main`, setup base commit `843f7b2891de6fa56f48401028999aa31b4bcec2`.
- Existing `.venv`: NumPy 2.2.6, SciPy 1.15.3, Pandas 2.3.3, Matplotlib 3.10.9, PyYAML 6.0.3. Record transitive versions with `python -m pip freeze`.

Commands below run from the repository root:

```bash
cd ~/projects/Ziggurat-Inspired-Method-for-Efficiently-Generating-Gaussian-Random-Numbers-in-Hardware
source .venv/bin/activate
python -c 'import numpy, scipy, pandas, matplotlib, yaml'
python -m pip freeze
make -C c CC=gcc O2
```

Do not resolve the `.venv/bin/python` symlink when invoking Python: invoking its resolved system interpreter bypasses the virtual environment.

## Compiler flags and tests

The existing Makefile compiles the full benchmark (Classical/Trapezoid, PCG32/xoshiro256+, buffered and profiled variants) with:

```text
gcc -std=c11 -Wall -Wextra -pedantic -O2 \
  -DBENCHMARK_OPTIMIZATION='"O2"' \
  -DBENCHMARK_CFLAGS='"-std=c11 -Wall -Wextra -pedantic -O2"' \
  <Makefile SOURCES> -o benchmark -lm
```

No Makefile, optimization defaults, RNG implementations, PRNG implementations or constants were modified. O3 remains available through `make -C c CC=gcc O3` but was not used. No `-march=native` or `-ffast-math` was introduced.

Safe existing C/PRNG/buffer test targets (activation ensures their `python3` uses `.venv`):

```bash
PATH="$PWD/.venv/bin:$PATH" make -C c CC=gcc test-prng-selection test-uniform
(cd c && gcc -std=c11 -Wall -Wextra -pedantic -O2 -I. \
  tests/test_prng_profile.c ziggurat_basic.c ziggurat_trapezoid.c \
  ziggurat_basic_profiled.c ziggurat_trapezoid_profiled.c \
  -o test_prng_profile -lm && ./test_prng_profile)
```

These passed, including reference vectors, deterministic seed handling, both Gaussian samplers and PRNGs, buffer exhaustion and small session resume. GCC emitted existing `-Wclobbered` warnings for `basic`, `k`, and `buffered` in `test_uniform_buffer.c` around longjmp; no algorithm changes were made.

**`make CC=gcc test` was intentionally not executed:** `test_basic.c` generates one million Gaussian values for each of six layer counts, with additional legacy comparisons; both normal/counter builds run this. Its shell suite also invokes `test_benchmark_output_dir.py`, which uses prohibited `--overwrite` flags. Existing tests were preserved. Run the safe portion of the existing CLI suite as follows (only the prohibited script invocation is omitted in memory):

```bash
.venv/bin/python -B - <<'PY'
from pathlib import Path
import os, subprocess
script = Path('c/tests/test_benchmark.sh').read_text()
script = script.replace('python3 tests/test_benchmark_output_dir.py "$bin" "$work"', '')
env = dict(os.environ, PATH=str(Path('.venv/bin').absolute()) + ':' + os.environ['PATH'])
subprocess.run(['sh', '-s', str(Path('c/benchmark').resolve())],
               input=script, text=True, cwd='c', env=env, check=True)
PY
```

This passed: layer selection, 1,000-sample CLI checks, defaults, invalid parameter rejection, binary byte counts and little-endian float64 formatting, moments, seed reporting and profile metadata. Largest CLI subprocess: 65,539 samples. Its temporary files are cleaned by the existing shell trap.

Python tests, excluding the existing 20,000 × 64 AD calibration workload (1.28 million uniforms):

```bash
.venv/bin/python -B - <<'PY'
import unittest
suite = unittest.defaultTestLoader.discover('experiments/tests')
def lightweight(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from lightweight(test)
        elif test.id().endswith('.test_ad_null_calibration'):
            print('SKIP: AD null calibration generates 1.28 million uniforms')
        else:
            yield test
result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(lightweight(suite)))
raise SystemExit(not result.wasSuccessful())
PY
```

Result: 26 tests passed, one expensive method excluded. New tests cover default-path compatibility, config preservation, unchanged IDs, invalid roots, collision rejection, resume preflight, small real resume/skip verification, validation destination, analysis and figure routing. The new integration fixture uses 128 samples per invocation; uniform tests use at most 256. Synthetic statistical unit fixtures are bounded at 100,000 values. All sample files and fixture figures are temporary and cleaned; the configured Linux schedule was not executed. Validation routing tests mock statistical computation; existing statistical methods have separate unit checks.

## Configuration and output isolation

`config_linux_ryzen2700x.yaml` preserves every original configuration field and adds only:

```yaml
results_root: experiments/results/linux_ryzen2700x
```

- Classical: N=8; unrefined Trapezoid: N=8 H=0 T=0; refined Trapezoid: N=8 H=2 T=4.
- Seed 1, PCG32, inline uniforms (no 2 GiB precomputed buffer allocation).
- Performance: 1,000,000 samples, three repetitions per configuration.
- Validation: 1,000,000 samples once per configuration; original significance/bin settings unchanged.
- Planned: nine performance + three validation = 12 executions, 12 million total generated samples, 24,000,000 binary sample bytes, only if explicitly run later.

Paths are resolved relative to the repository, independent of the caller's working directory. The optional generic-runner `results_root` selects raw/processed/figure paths together. It cannot be combined with legacy `output_dir` or the separate Experiment 01 layout. Existing `output_dir` users and the default configuration retain their prior paths. `config.yaml` was not edited.

```text
repository/
├── .venv/                              ignored, existing
├── c/benchmark                         ignored GCC O2 build
└── experiments/
    ├── config.yaml                     unchanged
    ├── config_linux_ryzen2700x.yaml
    ├── LINUX_BENCHMARK_SETUP.md
    └── results/
        ├── raw/                        historical, preserved
        ├── processed/                  historical, preserved
        ├── figures/                    historical, preserved
        ├── experiment*/                historical, preserved
        └── linux_ryzen2700x/            ignored generated outputs only
            ├── raw/                    empty after setup
            │   ├── <existing-format experiment IDs>/  future per-run metadata/logs
            │   ├── _reports/           future session reports
            │   └── _attempts/          future archived incomplete attempts
            ├── processed/              empty; future validation/analysis CSV/JSON
            └── figures/                empty; future PDF/PNG
```

The framework's `processed` and `raw/_reports` conventions replace the suggested `analysis` and `logs` folders. Per-run stdout/stderr and execution/provenance metadata remain in their existing locations. IDs are unchanged; only their parent root differs. Runtime uniform-cache files use temporary directories with automatic cleanup. `.gitignore` preserves the existing `.venv/` exclusion and ignores Python caches, generated C test executables and this Linux results subtree; historical research outputs remain tracked as before.

## Dry run and future commands

Verified commands (both valid, zero benchmarks and zero sample files):

```bash
.venv/bin/python -B experiments/main.py --config experiments/config_linux_ryzen2700x.yaml --dry-run
.venv/bin/python -B experiments/main.py --config experiments/config_linux_ryzen2700x.yaml --dry-run --resume
```

Every planned run is under the Linux raw directory. Dry run does not create run directories. Existing run directories remain errors without resume. Resume verifies successful outputs and build identity; incomplete attempts are archived according to existing behavior, never overwritten using a C flag. A different compiled binary can invalidate resume checks; record the executable hash and avoid rebuilding in mid-study.

Future execution commands — **not executed during setup**:

```bash
.venv/bin/python -B experiments/main.py --config experiments/config_linux_ryzen2700x.yaml --run
.venv/bin/python -B experiments/main.py --config experiments/config_linux_ryzen2700x.yaml --run --resume
.venv/bin/python -B experiments/main.py --config experiments/config_linux_ryzen2700x.yaml --validate
.venv/bin/python -B experiments/analysis.py --config experiments/config_linux_ryzen2700x.yaml
.venv/bin/python -B experiments/plotting.py --config experiments/config_linux_ryzen2700x.yaml
```

`--validate` only reads completed Linux raw datasets and writes Linux processed summaries; it does not execute the benchmark. It needs actual completed samples and has not been invoked against this empty workspace. Generic analysis verifies saved successful scheduled performance records and writes `processed/performance_results.csv`. Generic plotting reads it and writes `figures/performance_repetitions.pdf/png`; the existing Experiment 01 analysis/plot functions and schemas remain separate. Summary/figure regeneration follows existing derived-output replacement conventions; raw run overwrite protection remains unchanged.

## Reproducibility and interpretation

Record Git commit plus local diff, compiler and flags, binary SHA256, package versions, seed/PRNG, uniform mode, sample counts, repetitions and machine state. Existing per-run execution metadata captures configuration and binary identity. Seed reuse means timing repetitions use the same stream, not independent validation datasets. `schedutil`, boost, temperature and background load can affect timing; no power settings were tuned during setup.

Performance mode omits sample-file writes; validation mode includes their overhead. Do not pool those timings. Small correctness fixtures establish environment compatibility, not Gaussian accuracy or representative throughput. Classical Ziggurat's ideal acceptance/rejection construction targets the exact Gaussian; implementation/finite-randomness effects require separate assessment. Trapezoid approximations can introduce systematic errors. Statistical validation and CPU performance must be evaluated independently; no statistical methodology was changed.

## Preservation check

Before changes, 5,437 historical/config files were snapshotted by SHA256, byte size and nanosecond modification time. After verification, all matched; no historical files were added or removed. No sample files or result logs were generated in the Linux workspace. No commits or pushes were made.
