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
./benchmark --samples 1000000 --output samples.csv
./benchmark --samples 1000000 --counters
```

Set `CC=gcc` to use GCC. Instrumentation is compiled out by default to keep the
timed loop lean; the debug target enables it. The current algorithm does not
have rejection-region candidates, so retry/rejection fields remain zero.
Initialization and table construction happen before timing. CSV export writes
one sample per line with a header. The benchmark also prints mean, sample
variance, and a checksum.

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
The default algorithm remains trapezoid, with N=8, H=2, T=4. Layer/head/tail
options apply only to trapezoid; the basic algorithm keeps the reference's
fixed 128-layer geometry.

```sh
make O2
./benchmark --algorithm trapezoid --samples 10000000 --seed 1
./benchmark --algorithm basic --samples 10000000 --seed 1
./benchmark --algorithm basic --samples 1000000 --output basic_samples.csv
make debug
./benchmark --algorithm basic --samples 1000000 --counters
```

Timing includes identical checksum and moment accumulation overhead. Export
mode also includes file I/O; omit `--output` when comparing performance.
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
