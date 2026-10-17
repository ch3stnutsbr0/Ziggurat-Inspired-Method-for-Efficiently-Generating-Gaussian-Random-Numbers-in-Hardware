# Experiment 06 — Trapezoid validation with 512 interior bins

Ziggurat-Trapezoid only; xoshiro256+; N=8,16,32,64,128,256; H=2/T=4; seed 1; 2^25 = 33,554,432 samples per dataset. Six validation runs and 24 statistical tests. No Classical Ziggurat or performance tests were executed.

The Chi-square test uses 512 equal-width interior bins over [-5,5] (width 0.01953125), plus two unbounded tail bins: 514 initial bins. The existing expected-count merging rule merges sparse bins until the minimum expected count is 5; the table gives the resulting bin counts and degrees of freedom. Tests use fixed N(0,1), without parameter fitting, at alpha=0.05. Degrees of freedom equal final bins minus one.

| N | Final bins | df | Chi-square statistic | Chi-square p | Chi-square | KS | CvM | AD |
|---:|---:|---:|---:|---:|---|---|---|---|
| 8 | 492 | 491 | 969.66294 | 1.0659468e-33 | REJECT | REJECT | PASS | PASS |
| 16 | 492 | 491 | 609.20016 | 0.00021046331 | REJECT | PASS | PASS | PASS |
| 32 | 492 | 491 | 537.65008 | 0.071449212 | PASS | PASS | PASS | PASS |
| 64 | 492 | 491 | 552.3367 | 0.028562106 | REJECT | PASS | PASS | PASS |
| 128 | 492 | 491 | 478.13286 | 0.65281309 | PASS | PASS | PASS | PASS |
| 256 | 492 | 491 | 438.21935 | 0.95794033 | PASS | PASS | PASS | PASS |

Rejections: 4 of 24 tests. PASS means failure to reject, not proof of Gaussianity. One seed is used; no multiple-testing adjustment is applied. AD retains its existing approximate calibration and critical-value decision.

Streams matching Experiment 05: [8, 16, 32, 64, 128, 256]. Identical streams were checked for identical KS, CvM and AD results; only Chi-square binning changes.

Raw samples were streamed through an OS pipe into RAM and discarded after validation. No sample files or subsets were saved. Existing experiment outputs and sampling/validation source were checked for changes. All statistics and p-values are retained in processed/validation_results.json and tables/validation_results.csv.

Reproduce with `python3 -B experiments/experiment06.py --output-root NEW_DIRECTORY`. Configuration: experiments/experiment06.yaml. Existing output directories are never overwritten.
