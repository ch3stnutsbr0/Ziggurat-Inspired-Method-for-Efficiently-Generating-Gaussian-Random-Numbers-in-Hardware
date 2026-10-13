"""Run Experiment 02's five seed-2 validations sequentially with Experiment 01 code.

Usage: python3 -B experiments/experiment02.py
Requires the same NumPy/SciPy versions and benchmark/validation hashes as seed 1.
No build, performance repetition, profiling, preview, or parallel execution.
"""
import sys
sys.dont_write_bytecode = True
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import platform

import numpy as np
import scipy
import psutil
import yaml

import runner
import validation
from experiment01 import _run
from utils import sha256_file, write_json, validation_settings

PARAMETERS = [('basic', 8, None, None), ('trapezoid', 8, 0, 0),
              ('trapezoid_refined', 8, 2, 4), ('trapezoid_refined', 16, 2, 4),
              ('trapezoid_refined', 32, 2, 4)]
TESTS = [('chi_square', 'Pearson Chi-square'), ('kolmogorov_smirnov', 'KS'),
         ('anderson_darling', 'AD'), ('cramer_von_mises', 'CvM')]
CATEGORIES = ['rejected under both seeds', 'rejected only under Seed 1',
              'rejected only under Seed 2', 'fail-to-reject under both seeds']
SAMPLES = 100_000_000


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text())


def checked_json(path, value):
    path = Path(path)
    write_json(path, value, replace=path.exists())
    if read(path) != value:
        raise ValueError(f'JSON readback failed: {path}')


def snapshot(root):
    # Content hashes plus timestamps detect edits, additions, removals, and touches.
    return {str(p.relative_to(root)): dict(sha256=sha256_file(p), size=p.stat().st_size,
                mtime_ns=p.stat().st_mtime_ns) for p in sorted(root.rglob('*')) if p.is_file()}


def parameter(label, n, h, t, seed):
    algorithm = 'basic' if label == 'basic' else 'trapezoid'
    pid = f'{algorithm}_N{n}' + ('' if algorithm == 'basic' else f'_H{h}_T{t}') + f'_seed{seed}'
    return dict(parameter_id=pid, algorithm_label=label, algorithm=algorithm,
                N=n, H=h, T=t, seed=seed)


def verify_result(result, expected, baseline, executable_hash, code_hash, settings):
    for key in ('algorithm', 'algorithm_label', 'N', 'H', 'T', 'seed'):
        if result.get(key) != expected[key]:
            raise ValueError(f'Result parameter mismatch: {key}')
    if (result['num_samples'] != SAMPLES or result['sample_size_bytes'] != SAMPLES * 8
            or result['benchmark_sha256'] != executable_hash
            or result['validation_code_sha256'] != code_hash
            or result['numpy_version'] != np.__version__ or result['scipy_version'] != scipy.__version__
            or set(result['tests']) != {key for key, _ in TESTS}):
        raise ValueError('Sample count, provenance, dependencies, or test set mismatch')
    if not math.isfinite(result['mean']) or not math.isfinite(result['variance']) or result['variance'] <= 0:
        raise ValueError('Invalid full-data moments')
    for key, _ in TESTS:
        test, reference = result['tests'][key], baseline['tests'][key]
        if test['method'] != reference['method'] or test['significance_level'] != settings['significance_level']:
            raise ValueError(f'Calibration or significance level changed: {key}')
        for field in ('statistic', 'critical_value', 'p_value'):
            value = test[field]
            if value is not None and not math.isfinite(value):
                raise ValueError(f'Non-finite test result: {key}.{field}')
        if test['statistic'] < 0 or (test['p_value'] is not None and not 0 <= test['p_value'] <= 1):
            raise ValueError(f'Invalid statistic or probability: {key}')
        if test['p_value'] is None and not (key == 'anderson_darling' and test['p_value_below_resolution']):
            raise ValueError(f'Unexpected omitted p-value: {key}')
        reject = (test['statistic'] > test['critical_value'] if test['critical_value'] is not None
                  else test['p_value'] < test['significance_level'])
        if test['reject'] != reject or test['decision'] != ('reject' if reject else 'fail-to-reject'):
            raise ValueError(f'Inconsistent decision: {key}')
    chi, old_chi = result['tests']['chi_square'], baseline['tests']['chi_square']
    for field in ('degrees_of_freedom', 'configured_interior_bins', 'initial_bins', 'final_bins', 'critical_value'):
        if chi[field] != old_chi[field]:
            raise ValueError(f'Chi-square binning or calibration changed: {field}')
    if chi['observed_total'] != SAMPLES or not math.isclose(chi['expected_total'], SAMPLES, abs_tol=1e-6):
        raise ValueError('Chi-square count totals changed')


def csv_save(path, rows):
    path = Path(path)
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with path.open(newline='') as stream:
        saved = list(csv.DictReader(stream))
    normalized = [{key: '' if value is None else str(value) for key, value in row.items()} for row in rows]
    if saved != normalized:
        raise ValueError(f'CSV readback failed: {path}')


def save_processed(root, results):
    checked_json(root / 'processed/validation_results.json', results)
    rows = []
    for result in results:
        base = {key: result[key] for key in ('algorithm', 'algorithm_label', 'N', 'H', 'T', 'seed',
                'num_samples', 'mean', 'variance', 'benchmark_sha256', 'validation_code_sha256',
                'sample_sha256', 'numpy_version', 'scipy_version')}
        for key, name in TESTS:
            test = result['tests'][key]
            rows.append(dict(base, test=key, test_name=name, statistic=test['statistic'],
                p_value=test['p_value'], critical_value=test['critical_value'],
                significance_level=test['significance_level'], reject=test['reject'],
                decision=test['decision'], p_value_rounded_to_zero=test['p_value_rounded_to_zero'],
                p_value_below_resolution=test.get('p_value_below_resolution', False),
                p_value_resolution=test.get('p_value_resolution'), method=test['method']))
    csv_save(root / 'processed/validation_results.csv', rows)


def comparison(results, baselines):
    rows = []
    for result, reference in zip(results, baselines):
        for key, name in TESTS:
            a, b = reference['tests'][key], result['tests'][key]
            category = CATEGORIES[0 if a['reject'] and b['reject'] else
                                  1 if a['reject'] else 2 if b['reject'] else 3]
            rows.append(dict(algorithm=result['algorithm_label'], N=result['N'], H=result['H'], T=result['T'],
                test=name, seed_1_statistic=a['statistic'], seed_1_p_value=a['p_value'],
                seed_2_statistic=b['statistic'], seed_2_p_value=b['p_value'],
                seed_1_decision=a['decision'], seed_2_decision=b['decision'], rejection_pattern=category,
                seed_1_p_value_below_resolution=a.get('p_value_below_resolution', False),
                seed_2_p_value_below_resolution=b.get('p_value_below_resolution', False),
                seed_1_p_value_rounded_to_zero=a['p_value_rounded_to_zero'],
                seed_2_p_value_rounded_to_zero=b['p_value_rounded_to_zero']))
    return rows


def fmt(value):
    return 'omitted (<1e-4 calibration resolution)' if value is None else f'{value:.8g}'


def report(root, results, rows, session):
    lines = ['# Experiment 02 — Seed 2 Validation', '',
        'Exactly five configurations ran sequentially, each with 100,000,000 samples and seed 2. '
        'All four tests use fixed N(0,1), with no fitted parameters or sample standardization. '
        'No performance repetitions, PRNG profiling, or rebuild were performed.', '',
        '## Seed 2 moments', '', '| Algorithm | N | H | T | Mean | Sample variance (ddof=1) |',
        '|---|---:|---:|---:|---:|---:|']
    for r in results:
        lines.append(f"| {r['algorithm_label']} | {r['N']} | {r['H'] if r['H'] is not None else '—'} | "
                     f"{r['T'] if r['T'] is not None else '—'} | {r['mean']:.12g} | {r['variance']:.12g} |")
    lines += ['', '## Seed 1 versus Seed 2', '',
        'R = reject; F = fail-to-reject. **Bold patterns** identify rejection under both seeds. '
        'Fail-to-reject corresponds to the requested “accepted” category; it does not establish normality.', '',
        '| Algorithm | N | H | T | Test | Seed 1 statistic | Seed 1 p | Seed 2 statistic | Seed 2 p | Decisions (1 / 2) | Pattern |',
        '|---|---:|---:|---:|---|---:|---:|---:|---:|---|---|']
    for row in rows:
        pattern = row['rejection_pattern']
        if pattern == CATEGORIES[0]:
            pattern = f'**{pattern}**'
        decisions = ' / '.join('R' if row[f'seed_{seed}_decision'] == 'reject' else 'F' for seed in (1, 2))
        lines.append(f"| {row['algorithm']} | {row['N']} | {row['H'] if row['H'] is not None else '—'} | "
                     f"{row['T'] if row['T'] is not None else '—'} | {row['test']} | "
                     f"{fmt(row['seed_1_statistic'])} | {fmt(row['seed_1_p_value'])} | "
                     f"{fmt(row['seed_2_statistic'])} | {fmt(row['seed_2_p_value'])} | {decisions} | {pattern} |")
    lines += ['', '## Rejection patterns by test', '',
        '| Test | Both reject | Seed 1 only | Seed 2 only | Both fail-to-reject |', '|---|---:|---:|---:|---:|']
    for _, name in TESTS:
        counts = [sum(r['test'] == name and r['rejection_pattern'] == category for r in rows) for category in CATEGORIES]
        lines.append('| ' + name + ' | ' + ' | '.join(map(str, counts)) + ' |')
    persisted = [r for r in rows if r['test'] == 'Pearson Chi-square' and r['rejection_pattern'] == CATEGORIES[0]]
    prior = [r for r in rows if r['test'] == 'Pearson Chi-square' and r['seed_1_decision'] == 'reject']
    lines += ['', f"Chi-square rejection persisted in {len(persisted)} of the {len(prior)} selected configurations "
        'that rejected under Seed 1. The comparison describes these five configurations and two seeds only. '
        'It does not establish a seed-independent defect, p-value uniformity, or the general quality of the RNG. '
        'No second-level uniformity tests were performed.', '', '## Calibration and numerical concerns', '',
        'Settings match Experiment 01: alpha = 0.05 per test, 100 equal-width interior bins from -5 to 5, '
        'two unbounded tail bins, expected-count-only merging with minimum expected count 5. '
        'The same KS finite-sample calibration, Marsaglia-Marsaglia AD approximation, and SciPy CvM '
        'calibration were used. All four tests process the complete dataset. Decisions have no '
        'multiple-testing correction and the tests are correlated.', '',
        'AD p-values below 1e-4 are omitted with an explicit resolution flag. A computed zero from '
        'SciPy is flagged as numerical rounding/underflow rather than a mathematically zero probability. '
        'Critical values, methods, flags, and full-precision numerical values are retained in JSON/CSV.']
    concerns = [(r['algorithm'], r['N'], r['test'], r['seed_2_p_value']) for r in rows
                if r['seed_2_p_value_below_resolution'] or r['seed_2_p_value_rounded_to_zero']]
    lines += ['', f'Seed 2 numerical flags: {concerns if concerns else "none"}.', '', '## Reproducibility and verification', '',
        f"Executable SHA-256: `{session['benchmark_sha256']}`.", '',
        f"Validation code SHA-256: `{session['validation_code_sha256']}`.", '',
        f'NumPy {np.__version__}; SciPy {scipy.__version__}; Python {platform.python_version()}. '
        'Executable and validation hashes and numerical dependency versions match the Seed 1 results. '
        'The configuration, executable, driver, and supporting Python sources are preserved in artifacts/.', '',
        'All five 800,000,000-byte binaries were generated, analyzed, hashed, and deleted only after '
        'saved per-run results, aggregated JSON/CSV, and integrity records passed readback. '
        'No previews or subsets were retained. All Experiment 01 file hashes and modification times '
        'match the snapshot taken before this experiment. Existing C summary timings are retained '
        'as ordinary validation provenance; no performance comparison was performed.', '',
        f"Started: {session['started_at']}; finished: {session['ended_at']}.", '',
        'Reproduce from the repository root with `python3 -B experiments/experiment02.py` '
        'using a fresh experiment_02 output location and the same executable/dependency versions. '
        'The driver refuses an existing output directory to protect saved results.']
    path = root / 'reports/experiment_report.md'
    path.write_text('\n'.join(lines) + '\n')
    if path.read_text() != '\n'.join(lines) + '\n':
        raise ValueError('Report readback failed')


def main():
    repo = Path(__file__).resolve().parents[1]
    first = repo / 'experiments/results/experiment_01'
    root = repo / 'experiments/results/experiment_02'
    if root.exists():
        raise ValueError('Experiment 02 output exists; refusing to overwrite or repeat runs')
    archived_config = yaml.safe_load((first / 'artifacts/experiment_01.yaml').read_text())
    config = dict(experiment_id='experiment_02', name='Experiment 02 — Seed 2 Validation',
        output_dir='experiments/results/experiment_02/raw', keep_validation_samples=False,
        normal_distribution=archived_config['normal_distribution'], tail_thresholds=archived_config['tail_thresholds'],
        performance={'enabled': False}, profiling={'enabled': False},
        validation=dict(archived_config['validation']),
        configurations=[parameter(*args, 2) for args in PARAMETERS])
    if config['validation']['samples'] != SAMPLES:
        raise ValueError('Experiment 01 sample count differs')
    settings = validation_settings(config)
    identity = runner.benchmark_identity(repo / 'c/benchmark')
    code_hash = sha256_file(repo / 'experiments/validation.py')
    if identity['sha256'] != sha256_file(first / 'artifacts/benchmark'):
        raise ValueError('Executable differs from Experiment 01; experiment not started')
    baselines = []
    for args in PARAMETERS:
        p = parameter(*args, 1)
        directory = first / 'raw/validation' / (p['parameter_id'] + '_validation')
        baseline = read(directory / 'validation_result.json')
        if read(directory / 'validation_integrity.json')['validation_result_sha256'] != sha256_file(directory / 'validation_result.json'):
            raise ValueError('Seed 1 result integrity failed')
        verify_result(baseline, p, baseline, identity['sha256'], code_hash, settings)
        baselines.append(baseline)
    before = snapshot(first)
    memory_bound = SAMPLES * 8 * 3 + 1024**3
    disk_bound = SAMPLES * 8 + 2 * 1024**3
    resources = dict(available_disk_bytes=shutil.disk_usage(repo).free,
        available_memory_bytes=psutil.virtual_memory().available,
        required_disk_bytes=disk_bound, estimated_peak_memory_bytes=memory_bound)
    if resources['available_disk_bytes'] < disk_bound or resources['available_memory_bytes'] < memory_bound:
        raise RuntimeError(f'Insufficient resources: {resources}')
    root.mkdir(parents=True)
    for directory in ('artifacts', 'processed', 'tables', 'reports', 'raw/validation'):
        (root / directory).mkdir(parents=True)
    checked_json(root / 'artifacts/experiment_01_before.json', before)
    (root / 'artifacts/experiment_02.yaml').write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    checked_json(root / 'artifacts/seed_1_reference_results.json', baselines)
    for source in (repo / 'c/benchmark', Path(__file__), repo / 'experiments/validation.py',
                   repo / 'experiments/utils.py', repo / 'experiments/runner.py', repo / 'experiments/experiment01.py'):
        shutil.copy2(source, root / 'artifacts' / source.name)
    source_hashes = {p.name: sha256_file(p) for p in (root / 'artifacts').iterdir() if p.is_file()}
    session = dict(experiment='Experiment 02 — Seed 2 Validation', status='running', started_at=now(),
        planned=5, completed=[], errors=[], configurations=config['configurations'],
        benchmark_sha256=identity['sha256'], validation_code_sha256=code_hash,
        driver_sha256=sha256_file(__file__), dependencies=dict(numpy=np.__version__, scipy=scipy.__version__, yaml=yaml.__version__),
        python_version=sys.version, python_executable=sys.executable, platform=platform.platform(),
        resources=resources, keep_validation_samples=False, performance_enabled=False, profiling_enabled=False,
        artifact_hashes=source_hashes)
    checked_json(root / 'execution_order.json', session)
    results = []
    try:
        for index, (p, baseline) in enumerate(zip(config['configurations'], baselines), 1):
            if list(root.rglob('samples.bin')):
                raise RuntimeError('An earlier binary remains; stopping before another generation')
            if shutil.disk_usage(root).free < disk_bound or psutil.virtual_memory().available < memory_bound:
                raise RuntimeError('Resources fell below validation safety bounds')
            if sha256_file(validation.__file__) != code_hash:
                raise RuntimeError('Validation code changed')
            run = _run(p, 'validation', 1, SAMPLES, repo, root / 'raw')
            run['execution_order'] = index
            print(f"[{index}/5] generating {p['parameter_id']}: 100,000,000 samples", flush=True)
            execution = runner.execute_run(run, repo, dict(benchmark_sha256=identity['sha256'], benchmark=identity,
                validation_code_sha256=code_hash, experiment_name=config['name'], configuration=config))
            if execution['status'] != 'successful':
                raise RuntimeError(execution.get('error', 'C validation run failed'))
            directory = Path(run['output_directory'])
            # Reuse the unchanged validator, retaining the binary until the extra
            # Experiment 02 aggregate and decision checks have also completed.
            result = validation.validate_one_experiment01(directory, dict(config, keep_validation_samples=True), identity['sha256'])
            verify_result(result, p, baseline, identity['sha256'], code_hash, settings)
            result.update(keep_validation_samples=False, validation_settings=settings,
                driver_sha256=session['driver_sha256'], experiment_name=config['name'])
            checked_json(directory / 'validation_result.json', result)
            results.append(result)
            save_processed(root, results)
            integrity = dict(validation_result_sha256=sha256_file(directory / 'validation_result.json'),
                verified_at=now(), completed_tests=[key for key, _ in TESTS],
                processed_json_sha256=sha256_file(root / 'processed/validation_results.json'),
                processed_csv_sha256=sha256_file(root / 'processed/validation_results.csv'),
                deletion_authorized_after_full_validation=True)
            checked_json(directory / 'validation_integrity.json', integrity)
            if (read(directory / 'validation_result.json') != result
                    or sha256_file(directory / 'validation_result.json') != integrity['validation_result_sha256']):
                raise ValueError('Final per-run integrity verification failed')
            # Exactly this run's binary is deleted only after all analysis/readback.
            (directory / 'samples.bin').unlink()
            checked_json(directory / 'sample_retention.json', dict(sample_sha256=result['sample_sha256'],
                sample_size_bytes=result['sample_size_bytes'], deleted_at=now(),
                validation_integrity_sha256=sha256_file(directory / 'validation_integrity.json'),
                no_preview_or_subset_saved=True))
            session['completed'].append(dict(experiment_id=run['experiment_id'], execution_order=index,
                samples=SAMPLES, tests_completed=4, binary_deleted=True))
            checked_json(root / 'execution_order.json', session)
            print(f"[{index}/5] all four tests saved and verified; samples.bin deleted", flush=True)
        rows = comparison(results, baselines)
        if len(rows) != 20 or len(results) != 5 or len(session['completed']) != 5:
            raise ValueError('Final dataset/test count mismatch')
        csv_save(root / 'tables/seed_comparison.csv', rows)
        if list(root.rglob('samples.bin')) or len(list((root / 'raw/validation').glob('*/execution.json'))) != 5:
            raise ValueError('Unexpected binary or execution count')
        for p, result in zip(config['configurations'], results):
            directory = root / 'raw/validation' / (p['parameter_id'] + '_validation')
            saved_execution = read(directory / 'execution.json')
            if saved_execution['samples'] != SAMPLES or saved_execution['status'] != 'successful' or '--profile-prng' in saved_execution['argv']:
                raise ValueError('Unexpected execution mode or count')
            if read(directory / 'validation_integrity.json')['validation_result_sha256'] != sha256_file(directory / 'validation_result.json'):
                raise ValueError('Final per-run integrity failure')
            if read(directory / 'validation_result.json') != result:
                raise ValueError('Final aggregate differs from raw result')
        if read(root / 'processed/validation_results.json') != results:
            raise ValueError('Final aggregated JSON integrity failed')
        after = snapshot(first)
        if after != before:
            raise ValueError('Experiment 01 file inventory, content, or modification time changed')
        checked_json(root / 'verification.json', dict(status='successful', verified_at=now(),
            validation_configurations_executed=5, total_samples=5*SAMPLES, statistical_tests_completed=20,
            sample_binaries_remaining=0, experiment_01_unchanged=True, experiment_01_files_verified=len(before),
            benchmark_sha256_matches_experiment_01=True, validation_code_sha256_matches_experiment_01=True,
            performance_executions=0, profiling_executions=0,
            results_sha256=sha256_file(root / 'processed/validation_results.json'),
            comparison_sha256=sha256_file(root / 'tables/seed_comparison.csv')))
        session.update(status='successful', ended_at=now())
        report(root, results, rows, session)
        checked_json(root / 'execution_order.json', session)
    except (Exception, KeyboardInterrupt) as exc:
        session.update(status='failed', ended_at=now())
        session['errors'].append(f'{type(exc).__name__}: {exc}')
        session['preserved_sample_binaries'] = [str(p) for p in root.rglob('samples.bin')]
        checked_json(root / 'execution_order.json', session)
        print(json.dumps(session, indent=2), file=sys.stderr)
        raise
    print(json.dumps(dict(status=session['status'], completed=len(results), output=str(root)), indent=2), flush=True)


if __name__ == '__main__':
    main()
