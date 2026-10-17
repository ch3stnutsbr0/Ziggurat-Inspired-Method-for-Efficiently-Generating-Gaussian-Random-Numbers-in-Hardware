# Experiment 06 — Trapezoid-only validation

Run `python3 -B experiments/experiment06.py` from the repository root.

Uses xoshiro256+, seed 1, 2^25 samples, N=8,16,32,64,128,256 and H=2/T=4.
The experiment-specific configuration sets 512 interior Chi-square bins over [-5,5],
plus two unbounded tails. Sparse bins merge using the existing minimum expected count
of 5; actual final bins and degrees of freedom are recorded in every result.

All four existing fixed-N(0,1) tests run at alpha=0.05 for the trapezoid method only.
There are six validation runs, 24 tests, zero Classical runs and zero performance runs.
No raw sample files are saved. Existing test definitions and experiments are preserved.

Outputs: experiments/results/experiment06/{raw/validation,processed,tables,reports,artifacts},
plus execution_order.json and verification.json. Full p-values and statistics are in
processed/validation_results.json and tables/validation_results.csv. PASS means failure
to reject. Use --output-root NEW_DIRECTORY to reproduce without overwriting prior work.

Repeat with seed 2026 using `python3 -B experiments/experiment06.py --config experiments/experiment06_seed2026.yaml`. This saves separately to experiments/results/experiment06_seed2026 and preserves the seed-1 results. The driver reads and validates the uint64 seed from YAML.

For seed 2 with H=4/T=6, run `python3 -B experiments/experiment06.py --config experiments/experiment06_seed2_H4T6.yaml`. Results are saved separately to experiments/results/experiment06_seed2_H4T6. Refinements are now read from YAML and checked against the C report.
