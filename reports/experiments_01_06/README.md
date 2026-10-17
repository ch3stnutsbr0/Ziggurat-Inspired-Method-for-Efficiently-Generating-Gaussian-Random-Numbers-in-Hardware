# Experiments 01–06 research report

Start with [the PDF report](report.pdf) or [the complete Markdown report](report.md).

This package analyzes **existing results only**. No sampler or experiment was run, no Gaussian sample was generated, no additional goodness-of-fit test was performed, and no original source or result file was changed. The integrity record verifies 5,525 existing files by SHA-256 and modification time. The eight figures have vector PDF and 300-DPI PNG versions.

The report includes a full experiment inventory, seven principal tables plus supporting tables, all ten concluding research-question answers, and appendices containing all 137 saved validation datasets and all 166 timing aggregates. The consolidated tables contain 548 saved test records and 1,220 timing/checkpoint records. Timing checkpoints and repeated identical streams are explicitly distinguished from independent observations.

## Evidence and interpretation

The repository inspected is `/Users/liubenli/Documents/FALL 2026/Special Problem/Codes/Ziggurat-Trapezoid-GRNG`. The chat's initial `Codes/matlab` path does not exist; the actual MATLAB directory is inside this repository.

Sources, relative to that repository:

| Evidence | Original data |
| --- | --- |
| Experiment 01 | `experiments/results/experiment_01/raw/validation/*/validation_result.json`, `processed/performance_runs.csv`, `processed/tail_results.csv`, `processed/prng_results.csv` |
| Experiment 02 | `experiments/results/experiment_02/processed/validation_results.json` |
| Experiment 03 | `experiments/results/experiment03/raw/performance/performance_runs.json`, `processed/trapezoid_validation_vs_layers.json` |
| Experiment 04 | `experiments/results/experiment04/raw/performance/samples_*/performance_runs.json`, `processed/trapezoid_validation_vs_layers.json` |
| Experiment 05 | `experiments/results/experiment05/raw/performance/performance_runs.json`, `processed/validation_results.json` |
| Experiment 06 | `experiments/results/experiment06*/processed/validation_results.json`: seed 1, seed 2, seed 2026 and seed-2 H4/T6 directories |
| Dedicated PRNG study | `experiments/results/prng_comparison/runs.json`, `metadata.json` |
| Methodology and theory | Current and archived C sampler/PRNG/harness source, Python drivers/validation, YAML configurations, execution records and archived metadata |

`tables/source_manifest.csv` provides source hashes. `analysis/provenance.json` retains archived execution/environment metadata; normalized rows retain complete original records in JSON-valued `original_record` columns. No available metadata is discarded to make the display tables smaller. Missing or inapplicable fields use N/A.

Classical Ziggurat is theoretically exact under ideal assumptions. The inspected Trapezoidal implementation samples fitted geometry without Gaussian rejection correction. Non-rejection is not proof of exactness, and p-values are never accuracy scores. The report's default CPU recommendation is Classical N=256 with xoshiro256+, based on the matched Experiment 05 cohort. Later seed results qualify the provisional Trapezoidal recommendation. There is no certified application error tolerance or FPGA performance evidence.

## Regeneration

Run from this report directory. These commands **only read existing result files**; do not run the original experiment drivers.

```bash
python3 -B analysis/run_analysis.py --repo '/absolute/path/to/Ziggurat-Trapezoid-GRNG'
python3 -B analysis/generate_figures.py
python3 -B analysis/write_report.py
python3 -B analysis/render_report.py --font-dir '/path/to/matplotlib/mpl-data/fonts/ttf'
python3 -B analysis/verify_outputs.py --repo '/absolute/path/to/Ziggurat-Trapezoid-GRNG'
```

Consolidation uses Python's standard library. Plotting requires NumPy and Matplotlib. PDF rendering requires ReportLab and Pillow; verification requires pypdf. DejaVu font files come from Matplotlib. The rendering script has the actual font-directory default used for this report and also accepts `--font-dir` for portability. `run_analysis.py` accepts `--repo`; the derived cache makes later plotting/report generation independent of the repository path. Regeneration rewrites derived report outputs only. The original result data are never written.

The environment used here had these runtimes:

- Analysis, report and PDF: `/Users/liubenli/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`.
- Plotting: `/Users/liubenli/anaconda3/bin/python`, with `MPLCONFIGDIR=/private/tmp/ziggurat-mpl`.
- PDF visual review: bundled `pdftoppm`; inspection contact sheets were kept in temporary storage.

The original before/after verification additionally used a session-specific snapshot in `/private/tmp/ziggurat_original_manifest.json`. The delivered integrity record preserves its outcome; that temporary snapshot is not required for normal regeneration. Regenerated verification still checks the delivered input-source manifest. Future input changes will correctly cause verification to fail until intentionally reviewed.

## Aggregation and comparison policy

- Throughput is samples/elapsed_seconds, expressed in Msamples/s. Means, medians, sample SD and CV are computed across saved timing repetitions. Display precision is reduced; CSV precision is retained.
- Speedup is the ratio of matched median throughputs. Experiments, sample counts, PRNG, warmup, seed and harness remain distinct. Initialization and table construction are excluded from these saved timings.
- E05 prefixes come from the same five full streams and are dependent. They are not 20 independent repetitions.
- Repeated-seed summaries group compatible configurations/calibrations and exclude duplicate same-seed validation. E01/E04 duplicate PCG streams and E05/E06 repeated xoshiro streams are not counted as independent evidence.
- Rejection screening uses the saved alpha=0.05 decisions, without new multiplicity adjustment or new statistical tests. AD values below calibration resolution remain N/A with a valid critical-value decision.
- KS and moment errors are empirical discrepancies, not population approximation bounds. No rigorous population Pareto frontier is claimed.

## Output files

The complete generated-file list is in [FILES.md](FILES.md). It includes the report, figures, 13 CSV tables, reproducible scripts, compact derived data, provenance, numerical integrity checks and this documentation. All eight figures are referenced and discussed in the report.
