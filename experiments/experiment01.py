"""Experiment 01 orchestration; existing smoke-test runner remains available."""
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

import runner
from utils import sha256_file, validate_config, write_json


def paths(config, repository):
    raw = Path(config['output_dir'])
    raw = (Path(repository) / raw).resolve() if not raw.is_absolute() else raw.resolve()
    return raw.parent, raw


def _run(parameters, kind, repetition, samples, repository, raw, extra=()):
    name = parameters['parameter_id'] + f'_{kind}'
    if kind == 'performance':
        name += f'_rep{repetition}'
    mode = 'validation' if kind == 'validation' else 'performance'
    directory = raw / kind / name
    argv = [str(Path(repository) / 'c/benchmark'), '--algorithm', parameters['algorithm'],
            '--layers', str(parameters['N'])]
    if parameters.get('prng', 'pcg32') != 'pcg32':
        argv += ['--prng', parameters['prng']]
    if parameters['algorithm'] == 'trapezoid':
        argv += ['--head', str(parameters['H']), '--tail', str(parameters['T'])]
    argv += runner.uniform_arguments(parameters)
    argv += ['--samples', str(samples), '--seed', str(parameters['seed'])]
    argv += list(extra)
    if kind == 'validation':
        argv += ['--output-dir', str(directory)]
    return dict(**parameters, experiment_id=name, kind=kind, mode=mode,
                repetition=repetition, samples=samples, argv=argv,
                command=shlex.join(argv), output_directory=str(directory),
                output_handling='C binary output' if kind == 'validation' else 'Python captures C stdout')


def schedule(config, repository):
    configurations = runner.expand_configurations(config)
    root, raw = paths(config, repository)
    runs = []
    if config['performance']['enabled']:
        for rep in range(1, config['performance']['repetitions'] + 1):
            order = configurations.copy()
            random.Random(config.get('schedule_seed', 0) + rep).shuffle(order)
            for parameters in order:
                runs.append(_run(parameters, 'performance', rep,
                                 config['performance']['samples'], repository, raw))
    if config['profiling']['enabled']:
        for parameters in configurations:
            runs.append(_run(parameters, 'profiling', 1, config['profiling']['samples'],
                             repository, raw, ('--profile-prng', '--prng-iterations',
                                               str(config['profiling']['prng_iterations']))))
    if config['validation']['enabled']:
        for parameters in configurations:
            runs.append(_run(parameters, 'validation', 1,
                             config['validation']['samples'], repository, raw))
    for index, run in enumerate(runs, 1):
        run['execution_order'] = index
    return configurations, runs


def preflight(config, repository, *, resume=False):
    errors = validate_config(config)
    report = dict(status='invalid', errors=errors, warnings=[], configurations_per_algorithm={},
                  counts={}, resources={}, runs=[], first_10_commands=[])
    if errors:
        return report
    if config.get('experiment_id') != 'experiment_01':
        report['errors'].append('Use experiment_01.yaml for Experiment 01')
        return report
    configurations, runs = schedule(config, repository)
    report['configurations_per_algorithm'] = dict(Counter(c['algorithm_label'] for c in configurations))
    report['unique_configurations'] = len(configurations)
    report['counts'] = dict(Counter(r['kind'] for r in runs))
    report['counts']['total_benchmark_executions'] = len(runs)
    report['first_10_commands'] = [r['command'] for r in runs[:10]]
    report['runs'] = runs
    root, raw = paths(config, repository)
    report['output_root'] = str(root)
    report['errors'].extend(runner.inspect_paths((r['output_directory'] for r in runs), allow_existing=resume))
    if len({r['experiment_id'] for r in runs}) != len(runs):
        report['errors'].append('Duplicate experiment IDs')
    executable = Path(repository) / 'c/benchmark'
    if not executable.is_file() or not os.access(executable, os.X_OK):
        report['errors'].append('C benchmark is missing or not executable')
    else:
        report['benchmark_sha256'] = sha256_file(executable)
        for argument in ('--profile-prng', '--prng-iterations'):
            if argument not in (Path(repository) / 'c/benchmark.c').read_text():
                report['errors'].append(f'C source lacks {argument}')
    try:
        import numpy, scipy, matplotlib, yaml
        report['dependency_versions'] = dict(numpy=numpy.__version__, scipy=scipy.__version__,
                                             matplotlib=matplotlib.__version__, yaml=yaml.__version__)
    except ImportError as exc:
        report['errors'].append(f'Missing Python dependency: {exc}')
    samples = config['validation']['samples'] if config['validation']['enabled'] else 0
    per_file = 8 * samples
    total_binary = per_file * len(configurations) if config['validation']['enabled'] else 0
    retention = config['keep_validation_samples']
    needed_disk = (total_binary if retention else per_file) + 2 * 1024**3
    free_disk = shutil.disk_usage(root if root.exists() else Path(repository)).free
    # Chunked exact statistics retain one sorted copy plus a mapped input and
    # bounded work arrays. Allow three full arrays plus 1 GiB for the process.
    peak_memory = per_file * 3 + 1024**3 if samples else 0
    available_memory = None
    try:
        import psutil
        available_memory = psutil.virtual_memory().available
    except ImportError:
        report['errors'].append('Cannot determine available RAM; install psutil or use a smaller pilot')
    report['resources'] = dict(binary_bytes_per_validation=per_file,
        total_binary_bytes_if_retained=total_binary, estimated_peak_validation_memory_bytes=peak_memory,
        available_memory_bytes=available_memory, available_disk_bytes=free_disk,
        required_disk_bytes_with_safety=needed_disk, keep_validation_samples=retention,
        memory_estimate='3 float64-sized arrays plus 1 GiB for one sorted copy and chunked exact tests')
    if free_disk < needed_disk:
        report['errors'].append(f'Insufficient disk: need {needed_disk:,} bytes including safety, have {free_disk:,}')
    if available_memory is not None and available_memory < peak_memory:
        report['errors'].append(f'Insufficient available RAM for exact tests: estimated {peak_memory:,} bytes, have {available_memory:,}')
    # Exercise actual table initialization for every unique configuration without
    # allocating validation binaries. This also catches unsupported C settings.
    if not report['errors']:
        for parameters in configurations:
            argv = _run(dict(parameters, uniform_mode='inline'), 'performance', 0, 2, repository, raw)['argv']
            result = subprocess.run(argv, capture_output=True, text=True, cwd=repository)
            if result.returncode != 0:
                report['errors'].append(f"Unsupported {parameters['parameter_id']}: {result.stderr.strip()}")
                break
    report['status'] = 'valid' if not report['errors'] else 'invalid'
    return report


PROFILE_LABELS = {
    'Gaussian samples': ('gaussian_samples', int),
    'Initialization uniform calls': ('initialization_uniform_calls', int),
    'Initialization PCG32 calls': ('initialization_pcg32_calls', int),
    'Uniform calls': ('uniform_calls', int),
    'PCG32 calls': ('pcg32_calls', int),
    'Uniforms per Gaussian sample': ('uniforms_per_gaussian_sample', float),
    'PCG32 calls per Gaussian sample': ('pcg32_calls_per_gaussian_sample', float),
    'Median uniform generation time': ('median_uniform_ns', float),
    'Estimated PRNG time per Gaussian sample': ('estimated_prng_ns_per_sample', float),
    'Baseline Gaussian sampling time per sample': ('baseline_gaussian_ns_per_sample', float),
    'Estimated PRNG fraction': ('estimated_prng_fraction', float),
    'Instrumented Gaussian time per sample': ('instrumented_gaussian_ns_per_sample', float),
}


def parse_profile(stdout, run):
    if 'PRNG Profiling\n--------------' not in stdout:
        raise ValueError('Missing dedicated PRNG profiling section')
    result = {}
    for line in stdout.splitlines():
        if ':' not in line:
            continue
        label, value = line.split(':', 1)
        if label not in PROFILE_LABELS:
            continue
        key, parser = PROFILE_LABELS[label]
        token = value.strip().split()[0]
        if key in result:
            raise ValueError(f'Duplicate profile field {label}')
        result[key] = parser(token)
    missing = set(key for key, _ in PROFILE_LABELS.values()) - set(result)
    if missing:
        raise ValueError(f'Missing profile fields: {sorted(missing)}')
    if result['gaussian_samples'] != run['samples'] or result['pcg32_calls'] != 2 * result['uniform_calls']:
        raise ValueError('Inconsistent PRNG counts')
    if any(not math.isfinite(v) or v <= 0 for key, v in result.items()
           if isinstance(v, float)):
        raise ValueError('Invalid profile numeric result')
    result['source'] = 'C stdout from --profile-prng; displayed numeric precision'
    compiler_line = next((line for line in stdout.splitlines() if line.startswith('Compiler: ')),None)
    if compiler_line is None or '; flags: ' not in compiler_line or '; CPU architecture: ' not in compiler_line:
        raise ValueError('Missing compiler flags or CPU architecture')
    result['compiler'], rest = compiler_line[len('Compiler: '):].split('; flags: ',1)
    result['compiler_flags'], result['cpu_architecture'] = rest.split('; CPU architecture: ',1)
    return result


def _verify_validation_after_deletion(run, identity):
    directory = Path(run['output_directory'])
    sidecar = directory / 'validation_result.json'
    if not sidecar.is_file():
        return None
    saved = json.loads(sidecar.read_text())
    execution = json.loads((directory / 'execution.json').read_text())
    if (saved.get('experiment_id') != run['experiment_id'] or
            saved.get('benchmark_sha256') != identity['sha256'] or
            execution.get('status') != 'successful' or
            execution.get('provenance', {}).get('benchmark_sha256') != identity['sha256'] or
            saved.get('summary_sha256') != sha256_file(directory / 'summary.json') or
            saved.get('config_sha256') != sha256_file(directory / 'config.json')):
        raise ValueError('Validated result or build provenance changed')
    integrity = json.loads((directory / 'validation_integrity.json').read_text())
    if integrity.get('validation_result_sha256') != sha256_file(sidecar):
        raise ValueError('Saved validation result integrity failed')
    sample = directory / 'samples.bin'
    if sample.exists() and saved.get('sample_sha256') != sha256_file(sample):
        raise ValueError('Retained sample integrity failed')
    if not sample.exists() and saved.get('keep_validation_samples'):
        raise ValueError('Validation sample unexpectedly missing')
    return execution


def execute(config, repository, *, resume=False):
    with tempfile.TemporaryDirectory(prefix="grng-uniform-") as cache_directory:
        return _execute(config, repository, resume=resume, cache_directory=cache_directory)


def _execute(config, repository, *, resume=False, cache_directory=None):
    report = preflight(config, repository, resume=resume)
    if report['status'] != 'valid':
        return report
    root, raw = paths(config, repository)
    raw.mkdir(parents=True, exist_ok=True)
    (root / 'processed').mkdir(exist_ok=True)
    identity = runner.benchmark_identity(Path(repository) / 'c/benchmark')
    artifacts = root / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    executable_copy = artifacts / 'benchmark'
    if not executable_copy.exists():
        shutil.copy2(repository / 'c/benchmark', executable_copy)
    if sha256_file(executable_copy) != identity['sha256']:
        raise ValueError('Saved executable differs from the selected build')
    provenance = dict(benchmark_sha256=identity['sha256'], benchmark=identity,
                      git_commit=_git_commit(repository))
    session = dict(status='running', started_at=datetime.now(timezone.utc).isoformat(),
                   benchmark_sha256=identity['sha256'], planned=len(report['runs']),
                   completed=[], errors=[])
    session_file = root / 'execution_order.json'
    write_json(session_file, session, replace=session_file.exists())
    for run in report['runs']:
        try:
            directory = Path(run['output_directory'])
            if run['kind'] == 'validation':
                import psutil
                per_file = run['samples'] * 8
                needed = 3 * per_file + 1024**3
                if psutil.virtual_memory().available < needed:
                    raise RuntimeError('Available RAM fell below the exact-test memory preflight bound')
                if shutil.disk_usage(root).free < per_file + 1024**3:
                    raise RuntimeError('Free disk fell below one validation binary plus safety margin')
            if run['kind'] == 'validation' and resume:
                prior = _verify_validation_after_deletion(run, identity)
                if prior is not None:
                    session['completed'].append(dict(experiment_id=run['experiment_id'], action='skip'))
                    write_json(session_file, session, replace=True)
                    continue
            action = runner.resume_action(run, identity) if resume else dict(action='run')
            if action['action'] == 'skip':
                record = json.loads((directory / 'execution.json').read_text())
            else:
                history = runner.archive_attempt(run, action, identity) if action['action'] in ('retry', 'refresh') else []
                record = runner.execute_run(run, repository, provenance, history=history, cache_directory=cache_directory)
            if record['status'] != 'successful':
                raise RuntimeError(record.get('error', 'Benchmark failed'))
            if run['kind'] == 'profiling':
                profile = parse_profile((directory / 'stdout.txt').read_text(), run)
                profile.update(experiment_id=run['experiment_id'], benchmark_sha256=identity['sha256'])
                sidecar = directory / 'profile_result.json'
                write_json(sidecar, profile, replace=sidecar.exists())
            if run['kind'] == 'validation':
                from validation import validate_one_experiment01
                validate_one_experiment01(directory, config, identity['sha256'])
            session['completed'].append(dict(experiment_id=run['experiment_id'], action=action['action'],
                                             execution_order=run['execution_order']))
            write_json(session_file, session, replace=True)
            print(f"[{run['execution_order']}/{len(report['runs'])}] {run['experiment_id']} complete", file=sys.stderr, flush=True)
        except (Exception, KeyboardInterrupt) as exc:
            session['status'] = 'failed'
            session['errors'].append(dict(experiment_id=run['experiment_id'], error=f'{type(exc).__name__}: {exc}'))
            write_json(session_file, session, replace=True)
            return session
    from analysis import analyze_experiment01
    from plotting import plot_experiment01
    analyzed = analyze_experiment01(config, repository)
    plot_experiment01(root, analyzed)
    session['status'] = 'successful'
    session['ended_at'] = datetime.now(timezone.utc).isoformat()
    write_json(session_file, session, replace=True)
    return session


def _git_commit(repository):
    result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repository, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None
