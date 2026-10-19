"""Aggregate Experiment 01 records without mixing executable builds."""
import csv
import json
from pathlib import Path
import statistics

import numpy as np


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _key(row):
    return (row['algorithm'], row['N'], row.get('H'), row.get('T'),
            row['seed'], row['benchmark_sha256'], row.get('prng', 'pcg32'), row.get('uniform_mode', 'inline'))


def analyze_experiment01(config, repository):
    from experiment01 import paths
    root, raw = paths(config, repository)
    processed, tables, reports = root / 'processed', root / 'tables', root / 'reports'
    for directory in (processed, tables, reports):
        directory.mkdir(parents=True, exist_ok=True)
    performance, profiling, validation, tails = [], [], [], []
    for kind in ('performance', 'profiling', 'validation'):
        directory = raw / kind
        if not directory.exists():
            continue
        for run_dir in sorted(directory.iterdir()):
            if not run_dir.is_dir() or run_dir.name.startswith(('.', '_')):
                continue
            execution = json.loads((run_dir / 'execution.json').read_text())
            if execution.get('status') != 'successful':
                raise ValueError(f'Incomplete run: {run_dir}')
            base = dict(experiment_id=run_dir.name,
                algorithm=execution['algorithm'], algorithm_label=execution['algorithm_label'],
                prng=execution.get('prng', 'pcg32'), uniform_mode=execution.get('uniform_mode', 'inline'),
                N=execution['N'], H=execution['H'], T=execution['T'], seed=execution['seed'],
                benchmark_sha256=execution['provenance']['benchmark_sha256'],
                git_commit=execution['provenance'].get('git_commit'),
                started_at=execution['started_at'], execution_order=execution['execution_order'],
                samples=execution['samples'])
            if kind == 'performance':
                summary = execution['benchmark_results']
                seconds = summary['sampling_time_seconds']
                performance.append(dict(base, repetition=execution['repetition'],
                    c_sampling_time_seconds=seconds,
                    throughput_samples_per_second=execution['samples'] / seconds,
                    time_per_sample_ns=seconds * 1e9 / execution['samples'],
                    python_wall_clock_seconds=execution['wall_clock_duration_seconds'],
                    initialization_time_seconds=None, status=execution['status']))
            elif kind == 'profiling':
                profile = json.loads((run_dir / 'profile_result.json').read_text())
                profiling.append(dict(base, **{k:v for k,v in profile.items() if k not in base}))
            else:
                result = json.loads((run_dir / 'validation_result.json').read_text())
                row = dict(base, sample_sha256=result['sample_sha256'],
                    mean=result['mean'], variance=result['variance'],
                    absolute_mean_error=result['absolute_mean_error'],
                    absolute_variance_error=result['absolute_variance_error'],
                    all_tests_pass=all(not test['reject'] for test in result['tests'].values()),
                    keep_validation_samples=result['keep_validation_samples'])
                for test_name, test in result['tests'].items():
                    for field in ('statistic', 'p_value', 'significance_level', 'reject',
                                  'decision', 'degrees_of_freedom', 'final_bins',
                                  'p_value_below_resolution', 'p_value_rounded_to_zero'):
                        if field in test:
                            row[f'{test_name}_{field}'] = test[field]
                validation.append(row)
                for tail in result['tails']:
                    probability=tail['theoretical_probability']
                    standard_error=(probability*(1-probability)/result['num_samples'])**0.5
                    tails.append(dict(base, **tail, binomial_standard_error=standard_error))
    grouped = {}
    for row in performance:
        grouped.setdefault(_key(row), []).append(row)
    performance_summary = []
    for key, rows in grouped.items():
        speeds = np.asarray([row['throughput_samples_per_second'] for row in rows])
        reference = rows[0]
        performance_summary.append(dict(algorithm=key[0], N=key[1], H=key[2], T=key[3],
            seed=key[4], benchmark_sha256=key[5], prng=key[6], uniform_mode=key[7], algorithm_label=reference['algorithm_label'],
            repetitions=len(rows), mean_throughput=float(np.mean(speeds)),
            median_throughput=float(np.median(speeds)),
            std_throughput=float(np.std(speeds, ddof=1)) if len(rows)>1 else 0.0,
            min_throughput=float(np.min(speeds)), max_throughput=float(np.max(speeds)),
            q1_throughput=float(np.percentile(speeds,25)), q3_throughput=float(np.percentile(speeds,75)),
            iqr_throughput=float(np.percentile(speeds,75)-np.percentile(speeds,25))))
    profile_map = {_key(row): row for row in profiling}
    validation_map = {_key(row): row for row in validation}
    summary = []
    for speed in performance_summary:
        key = _key(speed)
        profile = profile_map.get(key)
        test = validation_map.get(key)
        row = dict(speed)
        if profile:
            row.update(uniform_calls=profile['uniform_calls'], pcg32_calls=profile['pcg32_calls'],
                uniforms_per_gaussian_sample=profile['uniforms_per_gaussian_sample'],
                pcg32_calls_per_gaussian_sample=profile['pcg32_calls_per_gaussian_sample'],
                median_uniform_ns=profile['median_uniform_ns'],
                estimated_prng_ns_per_sample=profile['estimated_prng_ns_per_sample'],
                estimated_prng_fraction=profile['estimated_prng_fraction'],
                compiler=profile['compiler'],compiler_flags=profile['compiler_flags'],
                cpu_architecture=profile['cpu_architecture'])
        if test:
            row.update({field:value for field,value in test.items() if field not in row})
        summary.append(row)
    expected = len(performance_summary)
    if ((config.get('profiling', {}).get('enabled', False) and len(profile_map) != expected)
            or (config['validation']['enabled'] and len(validation_map) != expected)):
        raise ValueError('Missing profile or validation result for one or more configurations')
    if any(row['repetitions'] != config['performance']['repetitions'] for row in performance_summary):
        raise ValueError('Incomplete performance repetitions')
    for filename, rows in [('performance_runs.csv',performance),
                           ('performance_summary.csv',performance_summary),
                           ('prng_results.csv',profiling), ('validation_results.csv',validation),
                           ('experiment_summary.csv',summary), ('tail_results.csv',tails)]:
        _write_csv(processed / filename, rows)
    primary = []
    selected_prng = config.get('prng', {}).get('type', 'pcg32')
    selected_summary = [row for row in summary if row.get('prng', 'pcg32') == selected_prng
                        and row.get('uniform_mode', 'inline') == config.get('uniform_mode', 'inline')]
    for n in config['algorithms']['basic']['layers']:
        row = {'N':n, 'prng':selected_prng}
        for label in ('basic','trapezoid'):
            candidate = next((x for x in selected_summary if x['N']==n and x['algorithm_label']==label),None)
            row[label+'_speed_Msamples_s'] = candidate['median_throughput']/1e6 if candidate else None
            row[label+'_all_tests_pass'] = candidate['all_tests_pass'] if candidate else None
        refined = [x for x in selected_summary if x['N']==n and x['algorithm_label']=='trapezoid_refined'
                   and x['all_tests_pass']]
        best = max(refined,key=lambda x:x['median_throughput']) if refined else None
        row['best_refined_speed_Msamples_s'] = best['median_throughput']/1e6 if best else None
        row['best_refined_all_tests_pass'] = True if best else None
        row['best_refined_H'] = best['H'] if best else None
        row['best_refined_T'] = best['T'] if best else None
        primary.append(row)
    _write_csv(tables/'primary_comparison.csv',primary)
    _write_csv(tables/'detailed_comparison.csv',summary)
    report = ['# Experiment 01: Gaussian RNG Performance and Statistical Accuracy Comparison', '',
        f"Configurations: {len(summary)}; performance runs: {len(performance)}; validation seeds: {sorted({x['seed'] for x in summary})}.",
        'Validation conclusions are preliminary because only one seed was used.',
        'Failing to reject N(0,1) does not prove exact Gaussianity. P-values are decisions under a null model, not measures of approximation error.',
        'PRNG fractions are estimates from an isolated microbenchmark; they are not exact CPU attribution.', '',
        '## Primary comparison', '',
        '| N | Basic M/s, pass | Unrefined M/s, pass | Best refined M/s, pass (H,T) |',
        '|---:|---|---|---|']
    for row in primary:
        def cell(prefix):
            speed=row[prefix+'_speed_Msamples_s']
            passed=row[prefix+'_all_tests_pass']
            return 'None' if speed is None else f"{speed:.3f}, {'pass' if passed else 'fail'}"
        best=cell('best_refined')
        if row['best_refined_H'] is not None:
            best += f" ({row['best_refined_H']},{row['best_refined_T']})"
        report.append(f"| {row['N']} | {cell('basic')} | {cell('trapezoid')} | {best} |")
    report += ['', '## Observations', '']
    for n in sorted({x['N'] for x in selected_summary}):
        candidates=[x for x in selected_summary if x['N']==n]
        fastest=max(candidates,key=lambda x:x['median_throughput'])
        passing=[x for x in candidates if x['all_tests_pass']]
        best=max(passing,key=lambda x:x['median_throughput']) if passing else None
        report.append(f"- N={n}: fastest observed {fastest['algorithm_label']} H={fastest['H']} T={fastest['T']} at {fastest['median_throughput']/1e6:.3f} M/s; fastest passing: " +
                      (f"{best['algorithm_label']} H={best['H']} T={best['T']} at {best['median_throughput']/1e6:.3f} M/s." if best else 'none.'))
    report += ['', '## PRNG work and refinement', '']
    for label in ('basic','trapezoid','trapezoid_refined'):
        rows=[x for x in selected_summary if x['algorithm_label']==label]
        if rows:
            calls=statistics.median(x['uniforms_per_gaussian_sample'] for x in rows)
            fraction=statistics.median(x['estimated_prng_fraction'] for x in rows)
            report.append(f'- {label}: median {calls:.3f} uniform calls/sample and estimated PRNG fraction {fraction:.3f} across its configurations.')
    for n in sorted({x['N'] for x in selected_summary}):
        unref=next((x for x in selected_summary if x['N']==n and x['algorithm_label']=='trapezoid'),None)
        refined=[x for x in selected_summary if x['N']==n and x['algorithm_label']=='trapezoid_refined']
        if unref and refined:
            med=statistics.median(x['median_throughput'] for x in refined)
            change=(med/unref['median_throughput']-1)*100
            head_only=[x for x in refined if x['T']==0]
            tail_only=[x for x in refined if x['H']==0]
            head_text=f"{statistics.median(x['median_throughput'] for x in head_only)/1e6:.3f}" if head_only else 'n/a'
            tail_text=f"{statistics.median(x['median_throughput'] for x in tail_only)/1e6:.3f}" if tail_only else 'n/a'
            report.append(f'- N={n}: refined median throughput differs from unrefined by {change:+.1f}%; head-only median {head_text} M/s; tail-only median {tail_text} M/s.')
    report += ['', '## Accuracy and interpretation', '',
               'Compare KS and AD statistics in the detailed CSV and figures for empirical discrepancy; p-values determine the configured test decisions and are not error magnitudes.',
               'The three N values and the H/T grid are observational comparisons. CPU temperature, frequency, and background activity can contribute to speed differences despite interleaved repetitions.',
               'The tail plot includes a one-standard-error reference under N(0,1), and tail_results.csv records its value at each threshold. Very rare tail errors are not definitive algorithm accuracy measurements.',
               'These are observations from one executable build and one seed, not causal conclusions.']
    (reports/'experiment_report.md').write_text('\n'.join(report)+'\n')
    return dict(summary=summary, performance=performance, profiles=profiling,
                validation=validation, tails=tails, primary=primary)


def uniform_speedups(executions):
    """Pair complete performance runs with identical conditions and executable hash.

    Missing pairs are omitted. Repetitions are aggregated by median throughput.
    """
    groups = {}
    for run in executions:
        result = run.get("benchmark_results", {})
        if (run.get("status") != "successful" or run.get("mode") != "performance"
                or result.get("complete", True) is not True or result.get("buffer_exhausted", False)):
            continue
        speed = result.get("throughput_samples_per_second")
        if not isinstance(speed, (int, float)) or not np.isfinite(speed) or speed <= 0:
            continue
        key = (run["algorithm"], run["N"], run.get("H"), run.get("T"),
               run["prng"], run["seed"], run["samples"], run["provenance"]["benchmark_sha256"])
        mode = run.get("uniform_mode", "inline")
        groups.setdefault(key, {}).setdefault(mode, []).append(speed)
    comparisons = []
    for key, modes in groups.items():
        if "inline" in modes and "precomputed" in modes:
            inline = statistics.median(modes["inline"])
            precomputed = statistics.median(modes["precomputed"])
            comparisons.append(dict(zip(("algorithm", "N", "H", "T", "prng", "seed", "samples", "benchmark_sha256"), key),
                inline_throughput=inline, precomputed_throughput=precomputed, speedup=precomputed/inline))
    return comparisons



def analyze_runs(config, repository):
    """Summarize generic-runner performance records using their saved schedule IDs.

    Validation results remain in validation_results.csv, produced by --validate.
    No samples are loaded and no statistical tests or benchmarks are executed.
    """
    from utils import result_paths, validate_config
    from runner import build_runs, expand_configurations, verify_success
    errors = validate_config(config)
    if errors:
        raise ValueError('; '.join(errors))
    paths = result_paths(config, repository)
    rows = []
    for run in build_runs(config, expand_configurations(config), repository):
        if run['mode'] != 'performance':
            continue
        record = json.loads((Path(run['output_directory']) / 'execution.json').read_text())
        verify_success(run, record)
        rows.append({**{key: run[key] for key in ('experiment_id', 'algorithm_label', 'N', 'H', 'T', 'seed', 'prng', 'repetition')},
                     'benchmark_sha256': record['provenance']['benchmark_sha256'],
                     **record['benchmark_results']})
    if not rows:
        raise ValueError('No scheduled performance results')
    destination = paths['processed'] / 'performance_results.csv'
    _write_csv(destination, rows)
    return destination


if __name__ == '__main__':
    import argparse
    from utils import load_config
    parser = argparse.ArgumentParser(description='Summarize performance records without executing benchmarks')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--config', type=Path, help='Generic-runner YAML configuration')
    mode.add_argument('--uniform-speedups', nargs='+', type=Path,
                      help='Directories containing execution.json records (searched recursively)')
    args = parser.parse_args()
    if args.config:
        print(analyze_runs(load_config(args.config), Path(__file__).resolve().parents[1]))
    else:
        records = []
        for directory in args.uniform_speedups:
            for path in directory.rglob('execution.json'):
                if '_attempts' not in path.parts:
                    records.append(json.loads(path.read_text()))
        print(json.dumps(uniform_speedups(records), indent=2, allow_nan=False))
