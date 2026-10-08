# C11 trapezoidal Ziggurat port

This ports the active MATLAB `trapzig_randn` implementation and helpers
`build_tables`, `compute_partitions`, `fit_trapezoid`, `sample_table`,
`build_recursive_table`, and `sample_recursive_table`. It is the table-based
algorithm: each selected entry samples its fitted trapezoid. It has no curve
rejection test in the active path. `basic_trapezoid.m` and
`ziggurat_gaussian_demo.m` are separate legacy/classical implementations and
are not silently substituted here.

The default is the refined configuration used by the main demos: N=8, two
recursive head levels, four recursive tail levels. Use `--head 0 --tail 0`
for the basic table. MATLAB's `rand`/`randi` stream is replaced by an explicitly
seeded PCG-XSH-RR 64/32 generator; exact sample sequences therefore differ.

Partition boundaries use the same decreasing area function
`G(x)=x*phi(x)+Q(x)` and equal-area targets as `compute_partitions.m`. C uses
bisection for scalar inversion instead of MATLAB `fzero`. Trapezoid coefficients use the same Legendre integrals over each density slice; C approximates them with 4096 panel composite Simpson quadrature. Only slices whose lower density is zero use the `t=2*s^2-1` substitution. This is a numerical rather than bitwise
reproduction of MATLAB's adaptive `integral` routine.

Build and run from this directory:

```sh
make clean && make O0       # no optimization
make clean && make O2       # recommended benchmark build
make clean && make O3
make clean && make debug    # counters enabled; adds counter overhead
./benchmark --samples 10000000 --seed 1
./benchmark --samples 1000000 --output samples.bin
./benchmark --samples 1000000 --counters
```

Set `CC=gcc` to use GCC. Instrumentation is compiled out by default to keep the
timed loop lean; the debug target enables it. The trapezoid algorithm has no rejection-region candidates, so its retry/rejection fields remain zero.
Initialization and table construction happen before timing. The benchmark
prints mean, sample variance, and a checksum. Use `--output <filename>` to
save every generated sample for statistical validation:

```sh
./benchmark --algorithm trapezoid --samples 1000000 --seed 1 --output samples.bin
```

The file contains exactly one IEEE 754 binary64 value (8 bytes) per sample,
in generation order and little endian byte order. It has no header or
metadata. Read it with NumPy:

```python
import numpy as np
samples = np.fromfile("samples.bin", dtype="<f8")
```

For a complete experiment, use `--output-dir` instead of `--output`:

```sh
./benchmark --algorithm trapezoid --samples 1000000 --seed 1 \
    --output-dir results/trapezoid_N8_H2_T4_seed1
```

The benchmark creates the directory and any missing parents. It writes
`samples.bin`, `summary.json`, and `config.json` from the same run.
`summary.json` records sampling time in seconds, throughput in samples per
second, time per sample in nanoseconds, checksum, mean, sample variance, and
sample count. `config.json` records algorithm, applicable N/H/T settings,
seed, sample count, and the compiler optimization label when built with this
Makefile. Initialization and total times are not currently measured. Existing
experiment files cause an error; use `--overwrite` to replace them deliberately.
`--output` and `--output-dir` cannot be combined.

```python
import json
from pathlib import Path
import numpy as np

run = Path("results/trapezoid_N8_H2_T4_seed1")
samples = np.fromfile(run / "samples.bin", dtype="<f8")
summary = json.loads((run / "summary.json").read_text())
config = json.loads((run / "config.json").read_text())
```

For a performance-only run, omit both output options:

```sh
./benchmark --algorithm trapezoid --samples 1000000 --seed 1
```

Output uses a 65,536-sample buffer (512 KiB). Generation and the existing
checksum and moment updates are timed per chunk; disk writes happen after
each chunk's timer stops. The reported throughput is still samples divided
by measured sampling time. Buffer writes and chunk timing add overhead, so
binary output mode is intended for statistical validation, not performance
benchmarking. Omit both output options for performance comparisons.

The table accessors expose main table index 0, head tables indices 1..H, and
tail tables indices 17..(16+T), with each boundary numbered 0..N. The reserved
gap keeps the fixed layout simple.


## Classical Ziggurat comparison

`ziggurat_basic.c/.h` ports `build_ziggurat` and `ziggurat_gaussian` from
`ziggurat_gaussian_demo.m`: 128 layers, R=3.442619855899, rectangle fast
acceptance, exact Gaussian boundary rejection, and exponential tail rejection.
Rejected boundary proposals restart layer selection. Tail logarithms use
`1-U` to exclude zero. The Gaussian tail integral is computed with `erfc`.
Both algorithms use the shared `pcg_rng.h`, the same seeding, 53-bit uniform
construction, and the same benchmark loop. No fast-math flags are enabled.
The default algorithm remains trapezoid, with N=8, H=2, T=4. The basic algorithm defaults to 128 layers; `--layers` selects a supported configuration for either algorithm. Head/tail refinement options apply only to trapezoid.

```sh
make O2
./benchmark --algorithm trapezoid --samples 10000000 --seed 1
./benchmark --algorithm basic --samples 10000000 --seed 1
./benchmark --algorithm basic --samples 1000000 --output basic_samples.bin
make debug
./benchmark --algorithm basic --samples 1000000 --counters
```

Timing includes identical checksum and moment accumulation overhead. In
binary output mode, disk I/O is excluded from the measured sampling time,
but in-memory buffering adds overhead.
Instrumentation is compiled out in O0/O2/O3 builds. The basic generator's
rectangle count includes bottom-rectangle and ordinary fast acceptances;
head hits count top-layer proposals; tail hits count entries into the
exponential sampler. Rejection tests/retries include both boundary and tail
attempts. Trapezoid refinement counters retain their previous semantics.

The earlier C port incorrectly integrated every slice from density zero,
which caused variance around 1.666. This translation error is now corrected:
finite slices use their actual lower and upper densities as in MATLAB.
The earlier suggestion that MATLAB needed a sampling interval offset was
incorrect; no offset was added. Direct MATLAB runtime comparison remains
outstanding. `performance_results.txt` records local compiler information,
five alternating trials per algorithm and optimization level, and moments.
These are scalar software implementations with different reference layer
counts, not a claim about all optimized Ziggurat variants.


## Configurable classical layers

The API is now `int zb_init(uint64_t seed, unsigned n)`. It returns 1 on
success and 0 for unsupported N or invalid numerical construction. Failure
invalidates the previous configuration; `zb_gaussian()` returns `NAN` until
successful initialization. Fixed arrays hold up to 256 entries, with no heap
allocation. Global generator state remains non-reentrant, as before.

| N | R |
|---|---|
| 8 | 2.3383716982472524 |
| 16 | 2.6755367657376140 |
| 32 | 2.9613001212640190 |
| 64 | 3.2136576271588960 |
| 128 | 3.442619855899 |
| 256 | 3.6541528853610088 |

Only these N values are supported. Other counts are rejected because no
verified cutoff is registered for them. Each N needs a different cutoff to
close the last layer at the Gaussian peak.

The convention matches `matlab/ziggurat_gaussian_demo.m`, using the
unnormalized Gaussian `f(x)=exp(-x*x/2)` and zero-based C indexing:

```
T(R) = sqrt(PI/2) * erfc(R/sqrt(2))
A(R) = R*f(R) + T(R)
x[0] = R; y[0] = f(R)
y[i] = y[i-1] + A(R)/x[i-1]      (i=1,...,N-1)
x[i] = sqrt(-2*log(y[i]))
```

R solves `y[N-1](R)-1=0`. Offline bisection on [1,5], with an early
peak crossing classified as R too small, produced the 8/16/32/64 cutoffs.
The 128 and 256 values are the supplied reference constants; all six were
checked against independently re-derived roots. `tests/test_basic.c` contains
the reproducible root derivation and prints the root and stored residual.
It uses long-double math, although long double has only double precision on
Apple ARM. No root finding occurs in initialization or sampling.

Initialization checks strictly increasing y, strictly decreasing x, finite
coordinates, valid rectangle/tail probability, and each rectangle's equal
area. Interior peak crossings fail. The raw final density must be within
2e-12 of 1 (1e-10 for the original truncated N=128 constant). Only after that
check may an overshoot be rounded down to 1; an undershoot is preserved.
The N=128 residual is approximately -4.36e-11 and its original cutoff and
sample stream are retained. Other verified residuals are about 1e-14 or
smaller on this machine. Initialization also rejects rectangle-area relative
errors above 1e-10; it fails if a platform's math library exceeds these bounds.

Both production implementations include `gaussian_constants.h`, which defines
`ZT_PI` once as `3.141592653589793238462643383279502884`. PCG is unchanged.

```sh
make O2
./benchmark --algorithm basic --layers 8 --samples 10000000 --seed 1
./benchmark --algorithm basic --layers 128 --samples 10000000 --seed 1
./benchmark --algorithm basic --layers 256 --samples 10000000 --seed 1
./benchmark --algorithm trapezoid --layers 8 --head 2 --tail 4 --samples 10000000
make test
```

The benchmark reports the selected N, seed, throughput and moments. H/T are
reported as not applicable for classical sampling. Omitting `--layers`
retains the old defaults (classical 128, trapezoid 8). Existing numeric seed
syntax, including hexadecimal seeds, remains supported.

`make test` runs construction/root/area checks, invalid and perturbed cutoff
checks, initialization guards, exact reproducibility, one million samples per
configuration with moment and tail-count checks, and CLI/binary output checks (which require Python 3 and NumPy). It
runs C tests both with and without counters. A frozen pre-change classical
implementation checks exact N=128 sample and counter equality across three
seeds (100,000 samples per seed); only its PI literal is replaced with the
identical shared double value. Numerical checks provide primary evidence of
valid tables; statistical checks are supplemental. No existing test suite
was present before these additions.
