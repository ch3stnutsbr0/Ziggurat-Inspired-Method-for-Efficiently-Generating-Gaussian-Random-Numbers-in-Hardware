# Experiment 05 — xoshiro256+ only

Run from the repository root:

```sh
MPLCONFIGDIR=/private/tmp/experiment05-matplotlib python3 -B experiments/experiment05.py
```

Both Classical Ziggurat and Ziggurat-Trapezoid use xoshiro256+ at N=8,16,32,64,128,256,
seed 1, and compiler optimization -O2. Trapezoid uses H=2/T=4.
Each run generates exactly 2^25 = 33,554,432 samples. There is no additional Gaussian warmup.
The performance harness records cumulative speed at 100,000, 1,000,000, 10,000,000,
and 33,554,432 observations within the same run; it never creates separate prefix datasets.
Five timing repetitions are interleaved across configurations. The figure shows median speed
with interquartile bands, in six panels for the layer counts. Checkpoints are dependent.
Initialization and table construction are outside timing. A volatile checksum prevents loop
elimination. Output occurs only after sampling; small checkpoint bookkeeping and clock reads
are included in subsequent cumulative times. Existing sampler and benchmark files are unchanged.

Both methods are validated using all 2^25 samples at every layer count. Existing Chi-square,
KS, CvM and AD tests retain alpha 0.05 and fixed N(0,1), with no fitting or standardization.
Validation observations pass through an OS pipe into RAM and are discarded after the tests;
no raw sample files or subsets are saved. PASS means failure to reject, not proof of Gaussianity.
The experiment uses one seed and applies no multiple-testing correction.

The saved configuration is experiment05.yaml. Results are under experiments/results/experiment05
in artifacts/, raw/ (numerical records only), processed/, tables/, figures/, and reports/.
The main figure is figures/speed_vs_samples.png, with an SVG copy. Full p-values and statistics
are in processed/validation_results.json and tables/validation_results.csv. The report is
reports/experiment_report.md; execution_order.json and verification.json record provenance
and integrity checks. The normal benchmark validates streams, while experiment05_benchmark.c
measures cumulative prefixes; their final checksums must match for every configuration.

Previous experiment results and C/validation/MATLAB sources are protected by hash checks.
An existing output directory is never overwritten. Reproduce with --output-root NEW_DIRECTORY.
A failed run preserves partial numerical results. There are 60 timing runs, 12 validation runs,
and 48 statistical tests. No changes are committed automatically.
