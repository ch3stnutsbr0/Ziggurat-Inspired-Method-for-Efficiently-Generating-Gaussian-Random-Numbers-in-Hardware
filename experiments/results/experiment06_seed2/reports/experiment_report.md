# Experiment 06 — Trapezoid validation with 512 interior bins

Ziggurat-Trapezoid only; xoshiro256+; N=8,16,32,64,128,256; H=2/T=4; seed 2; 2^25 = 33,554,432 samples per dataset. Six validation runs and 24 statistical tests. No Classical Ziggurat or performance tests were executed.

The Chi-square test uses 512 equal-width interior bins over [-5,5] (width 0.01953125), plus two unbounded tail bins: 514 initial bins. The existing expected-count merging rule merges sparse bins until the minimum expected count is 5; the table gives the resulting bin counts and degrees of freedom. Tests use fixed N(0,1), without parameter fitting, at alpha=0.05. Degrees of freedom equal final bins minus one.

| N | Final bins | df | Chi-square statistic | Chi-square p | Chi-square | KS | CvM | AD |
|---:|---:|---:|---:|---:|---|---|---|---|
| 8 | 492 | 491 | 964.79523 | 3.5690504e-33 | REJECT | PASS | PASS | PASS |
| 16 | 492 | 491 | 620.50705 | 6.2126849e-05 | REJECT | REJECT | PASS | PASS |
| 32 | 492 | 491 | 550.2512 | 0.032830007 | REJECT | REJECT | REJECT | PASS |
| 64 | 492 | 491 | 514.59163 | 0.22294013 | PASS | PASS | PASS | PASS |
| 128 | 492 | 491 | 530.32827 | 0.10672613 | PASS | PASS | PASS | PASS |
| 256 | 492 | 491 | 469.62742 | 0.74883462 | PASS | REJECT | PASS | PASS |

Rejections: 7 of 24 tests. PASS means failure to reject, not proof of Gaussianity. One seed is used; no multiple-testing adjustment is applied. AD retains its existing approximate calibration and critical-value decision.

Streams matching Experiment 05: []. Where same-seed reference streams exist and match, KS, CvM and AD results are checked for exact agreement. No cross-seed equality is expected.

Raw samples were streamed through an OS pipe into RAM and discarded after validation. No sample files or subsets were saved. Existing experiment outputs and sampling/validation source were checked for changes. All statistics and p-values are retained in processed/validation_results.json and tables/validation_results.csv.

Reproduce with `python3 -B experiments/experiment06.py --config /Users/liubenli/Documents/FALL 2026/Special Problem/Codes/Ziggurat-Trapezoid-GRNG/experiments/experiment06_seed2.yaml --output-root NEW_DIRECTORY`. Configuration: `experiment06_seed2.yaml`. Existing output directories are never overwritten.
