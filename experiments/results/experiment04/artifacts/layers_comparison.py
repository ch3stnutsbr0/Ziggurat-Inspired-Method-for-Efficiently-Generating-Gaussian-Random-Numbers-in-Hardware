"""Six-layer O2 comparison: five warmed timings and in-memory Trapezoid validation.

Run: python3 -B experiments/layers_comparison.py [--samples N] [--output-root DIRECTORY]
Outputs default to experiments/results/experiment03; existing named outputs are never overwritten.
The original c/benchmark executable and previous experiment results are preserved.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import shutil
import subprocess
import tempfile
import time

import numpy as np
import scipy
import psutil

import runner
import validation
from utils import load_config, sha256_file, validation_settings, write_json

LAYERS = (8, 16, 32, 64, 128, 256)
SAMPLES = 10_000_000
REPETITIONS = 5
WARMUP = 100_000
SEED = 1
TEST_NAMES = {'chi_square': 'chi2', 'kolmogorov_smirnov': 'ks',
              'cramer_von_mises': 'cvm', 'anderson_darling': 'ad'}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def snapshot(root, *, exclude=None):
    return {str(p.relative_to(root)): (sha256_file(p), p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob('*')) if p.is_file()
            and (exclude is None or not p.resolve().is_relative_to(exclude))}


def checked_json(path, value):
    write_json(path, value, replace=path.exists())
    if json.loads(path.read_text()) != value:
        raise ValueError(f'JSON readback failed: {path}')


def save_csv(path, rows):
    with path.open('x', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with path.open(newline='') as f:
        readback = list(csv.DictReader(f))
    expected = [{k: str(v) for k, v in row.items()} for row in rows]
    if readback != expected:
        raise ValueError(f'CSV readback failed: {path}')


def parameters(algorithm, n, samples=SAMPLES):
    return dict(algorithm=algorithm, N=n, H=None if algorithm=='basic' else 2,
                T=None if algorithm=='basic' else 4, samples=samples, seed=SEED)


def command(executable, run, *, warmup=0):
    argv = [str(executable), '--algorithm', run['algorithm'], '--layers', str(run['N']),
            '--samples', str(run['samples']), '--seed', str(run['seed']), '--report-json']
    if run['algorithm'] == 'trapezoid':
        argv += ['--head', str(run['H']), '--tail', str(run['T'])]
    if warmup:
        argv += ['--warmup', str(warmup)]
    return argv


def parse(stdout, run, warmup):
    runner.parse_benchmark_stdout(stdout, run)  # existing identity/text checks
    lines = [line[len('BENCHMARK_JSON: '):] for line in stdout.splitlines()
             if line.startswith('BENCHMARK_JSON: ')]
    if len(lines) != 1:
        raise ValueError('Missing or duplicate full-precision benchmark result')
    result = json.loads(lines[0])
    runner.check_summary(result, run)
    if (result['algorithm'] != run['algorithm'] or result['N'] != run['N'] or
            result['seed'] != run['seed'] or result['warmup_samples'] != warmup or
            result['compiler_optimization'] != 'O2' or
            (run['algorithm']=='trapezoid' and (result['H'],result['T']) != (run['H'],run['T']))):
        raise ValueError('Benchmark configuration, warmup, or optimization mismatch')
    elapsed = result['sampling_time_seconds']
    if elapsed <= 0 or not math.isclose(result['throughput_samples_per_second'], run['samples']/elapsed, rel_tol=1e-14):
        raise ValueError('Throughput is not samples / elapsed_seconds')
    return result


def collect_samples(executable, run):
    """Transfer raw binary64 values only through an OS pipe into a NumPy array."""
    values = np.empty(run['samples'], dtype='<f8')
    view = memoryview(values).cast('B')
    read_fd, write_fd = os.pipe()
    process = None
    argv = command(executable, run) + ['--output', f'/dev/fd/{write_fd}']
    try:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   pass_fds=(write_fd,))
        os.close(write_fd)
        write_fd = None
        with os.fdopen(read_fd, 'rb', buffering=0) as pipe:
            read_fd = None
            received = 0
            while received < len(view):
                count = pipe.readinto(view[received:])
                if not count:
                    break
                received += count
            extra = pipe.read(1)
        stdout, stderr = process.communicate()
        if process.returncode != 0 or received != len(view) or extra:
            raise RuntimeError(f'Validation stream incomplete: {received}/{len(view)} bytes; '
                               f'exit={process.returncode}; {stderr.decode(errors="replace")}')
        result = parse(stdout.decode(), run, 0)
        sample_hash = hashlib.sha256(view).hexdigest()
        return values, result, sample_hash
    finally:
        if read_fd is not None:
            os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        view.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path)
    parser.add_argument('--samples', type=int, default=SAMPLES, help='Samples per performance/validation run')
    parser.add_argument('--quiet', action='store_true', help='Print final counts rather than full tables')
    args = parser.parse_args()
    samples = args.samples
    if not 2 <= samples <= 2**64-1:
        parser.error('--samples must be an integer from 2 through 2**64-1')
    repo = Path(__file__).resolve().parents[1]
    output = args.output_root.resolve() if args.output_root else repo/'experiments/results/experiment03'
    names = ['processed/performance_vs_layers.csv', 'processed/trapezoid_validation_vs_layers.csv',
             'raw/performance/performance_runs.json', 'processed/trapezoid_validation_vs_layers.json',
             'figures/throughput_vs_layers.png', 'artifacts/layers_experiment.json']
    if any((output/name).exists() for name in names):
        raise ValueError('A requested output exists; use a new output-root to preserve earlier results')
    # Reuse the established statistical settings without modifying their definitions.
    settings = validation_settings(load_config(repo/'experiments/config.yaml'))
    if settings['significance_level'] != .05:
        raise ValueError('Existing significance level does not match requested alpha=0.05')
    if not set(LAYERS) <= __import__('utils').BASIC_LAYERS:
        raise ValueError('Python infrastructure does not support all requested layer counts')
    old_results = snapshot(repo/'experiments/results', exclude=output)
    protected_files = [repo/'c/benchmark', repo/'c/ziggurat_basic.c', repo/'c/ziggurat_trapezoid.c',
                       repo/'c/pcg_rng.h', repo/'experiments/validation.py'] + list((repo/'matlab').glob('*.m'))
    protected = {str(p.relative_to(repo)): sha256_file(p) for p in protected_files}
    resources = dict(available_disk_bytes=shutil.disk_usage(repo).free,
                     available_memory_bytes=psutil.virtual_memory().available,
                     estimated_peak_memory_bytes=samples*8*2+24*1_000_000*8+1024**3,
                     memory_estimate='input plus sorted copy, 24 bounded one-million-value work vectors, and 1 GiB reserve')
    if resources['available_memory_bytes'] < resources['estimated_peak_memory_bytes']:
        raise RuntimeError(f'Insufficient available memory: {resources}')
    for directory in ('processed', 'figures', 'artifacts', 'raw/performance', 'raw/validation', 'tables', 'reports'):
        (output/directory).mkdir(parents=True, exist_ok=True)
    metadata_path = output/'artifacts/layers_experiment.json'
    metadata = dict(status='running', started_at=timestamp(), layers=list(LAYERS), H=2, T=4,
        seed=SEED, performance_samples=samples, performance_repetitions=REPETITIONS,
        warmup_samples=WARMUP, warmup_seed_reset=True, validation_samples=samples,
        validation_algorithms=['trapezoid'], validation_settings=settings,
        validation_code_sha256=sha256_file(validation.__file__),
        python_version=sys.version, numpy_version=np.__version__, scipy_version=scipy.__version__,
        platform=platform.platform(), resources=resources, executions=[],
        raw_samples_saved=False, driver_sha256=sha256_file(__file__),
        methodology='Same original unbuffered timed C loop for both algorithms: generate, volatile checksum, '
        'sum, sumsq. Initialization, warmup, seed reset, and reports are outside timing. '
        'Separate C subprocesses per repetition, fixed seed 1; identical random streams across repetitions. '
        'Validation streams into RAM, uses existing full-data chunked tests, and contributes no performance timings.')
    checked_json(metadata_path, metadata)
    performance, validation_results = [], []
    try:
        with tempfile.TemporaryDirectory(prefix='gaussian-layers-o2-', dir='/private/tmp') as temp:
            executable = Path(temp)/'benchmark'
            sources = [repo/'c'/name for name in ('benchmark.c', 'ziggurat_basic.c', 'ziggurat_trapezoid.c',
                      'ziggurat_basic_profiled.c', 'ziggurat_trapezoid_profiled.c')]
            flags = ['-std=c11', '-Wall', '-Wextra', '-pedantic', '-O2']
            build = ['/usr/bin/clang', *flags, '-DBENCHMARK_OPTIMIZATION="O2"',
                     '-DBENCHMARK_CFLAGS="'+ ' '.join(flags)+'"', *map(str,sources), '-o', str(executable), '-lm']
            compiler = subprocess.run(['/usr/bin/clang','--version'], capture_output=True, text=True, check=True).stdout
            compiled = subprocess.run(build, capture_output=True, text=True)
            if compiled.returncode:
                raise RuntimeError(compiled.stderr)
            metadata.update(compiler=compiler, compiler_flags=flags, build_command=build,
                compiler_messages=compiled.stderr, executable_sha256=sha256_file(executable),
                source_sha256={str(p.relative_to(repo)):sha256_file(p) for p in sources},
                original_benchmark_sha256=protected['c/benchmark'])
            checked_json(metadata_path, metadata)
            configurations = [parameters(algorithm,n,samples) for n in LAYERS for algorithm in ('basic','trapezoid')]
            for rep in range(1,REPETITIONS+1):
                order = configurations.copy()
                random.Random(SEED+rep).shuffle(order)
                for run in order:
                    started = timestamp()
                    result = subprocess.run(command(executable,run,warmup=WARMUP),
                                            capture_output=True,text=True,check=True)
                    record = parse(result.stdout,run,WARMUP)
                    record.update(repetition=rep, started_at=started, ended_at=timestamp())
                    performance.append(record)
                    metadata['executions'].append(dict(kind='performance',algorithm=run['algorithm'],N=run['N'],repetition=rep))
                checked_json(output/'raw/performance/performance_runs.json',performance)
                checked_json(metadata_path,metadata)
                print(f'Performance round {rep}/{REPETITIONS} complete (12 configurations)',flush=True)
            perf_rows=[]
            for n in LAYERS:
                row={'N':n}
                times={}
                rates={}
                for algorithm,label in [('basic','classical'),('trapezoid','trapezoid')]:
                    group=[r for r in performance if r['algorithm']==algorithm and r['N']==n]
                    if len(group)!=REPETITIONS or len({r['checksum'] for r in group})!=1:
                        raise ValueError('Repetition count or fixed-seed sequence mismatch')
                    times[label]=float(np.median([r['sampling_time_seconds'] for r in group]))
                    rates[label]=float(np.median([samples/r['sampling_time_seconds']/1e6 for r in group]))
                row.update(classical_throughput_M_per_s=rates['classical'],
                    trapezoid_throughput_M_per_s=rates['trapezoid'],speedup=rates['trapezoid']/rates['classical'],
                    classical_median_time_s=times['classical'],trapezoid_median_time_s=times['trapezoid'])
                perf_rows.append(row)
            save_csv(output/'processed/performance_vs_layers.csv',perf_rows)
            val_rows=[]
            for n in LAYERS:
                run=parameters('trapezoid',n,samples)
                values,c_summary,sample_hash=collect_samples(executable,run)
                try:
                    numerical=validation.run_tests_chunked(values,settings,[])  # same tests, no extra tail analysis
                finally:
                    del values
                if set(numerical['tests']) != set(TEST_NAMES):
                    raise ValueError('Missing validation test')
                for moment in ('mean','variance'):
                    if not math.isclose(numerical[moment],c_summary[moment],rel_tol=1e-10,abs_tol=1e-10):
                        raise ValueError('Full-data moments disagree with C summary')
                same=[r for r in performance if r['algorithm']=='trapezoid' and r['N']==n]
                if any(r['checksum'] != c_summary['checksum'] for r in same):
                    raise ValueError('Warmup changed measured sequence or validation stream')
                full=dict(N=n,H=2,T=4,seed=SEED,samples=samples,stream_bytes=samples*8,
                    stream_sha256=sample_hash,raw_samples_saved=False,
                    executable_sha256=metadata['executable_sha256'],
                    validation_code_sha256=metadata['validation_code_sha256'],**numerical)
                validation_results.append(full)
                row=dict(N=n,H=2,T=4,samples=samples,mean=numerical['mean'],variance=numerical['variance'],
                    chi2_final_bins=numerical['tests']['chi_square']['final_bins'],
                    chi2_df=numerical['tests']['chi_square']['degrees_of_freedom'])
                for test,label in TEST_NAMES.items():
                    r=numerical['tests'][test]
                    row[f'{label}_statistic']=r['statistic']
                    row[f'{label}_pvalue']='NA' if r['p_value'] is None else r['p_value']
                    row[f'{label}_result']='FAIL' if r['reject'] else 'PASS'
                # Required column order is Chi-square, KS, CvM, AD.
                val_rows.append(row)
                metadata['executions'].append(dict(kind='validation',algorithm='trapezoid',N=n,samples=samples,tests=4))
                checked_json(output/'processed/trapezoid_validation_vs_layers.json',validation_results)
                checked_json(metadata_path,metadata)
                print(f'Validation N={n}: '+', '.join(f"{label}={row[label+'_result']}" for label in ('chi2','ks','cvm','ad')),flush=True)
            save_csv(output/'processed/trapezoid_validation_vs_layers.csv',val_rows)
        # Plotting occurs after all timings and validation. One requested PNG only.
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig,ax=plt.subplots(figsize=(8.2,5.2),layout='constrained')
        ax.plot(LAYERS,[r['classical_throughput_M_per_s'] for r in perf_rows],'-o',label='Classical Ziggurat')
        ax.plot(LAYERS,[r['trapezoid_throughput_M_per_s'] for r in perf_rows],'-s',label='Ziggurat-Trapezoid (H=2, T=4)')
        ax.set_xscale('log',base=2)
        ax.set_xticks(LAYERS,[str(n) for n in LAYERS])
        ax.set(title='Gaussian RNG Throughput vs Number of Layers',xlabel='Number of Layers (N)',ylabel='Throughput (Million Samples/sec)')
        ax.grid(True,alpha=.3)
        ax.legend()
        fig.savefig(output/'figures/throughput_vs_layers.png',dpi=300)
        plt.close(fig)
        if snapshot(repo/'experiments/results', exclude=output) != old_results:
            raise ValueError('An earlier experiment result changed')
        if {str(p.relative_to(repo)):sha256_file(p) for p in protected_files} != protected:
            raise ValueError('An original executable, sampler, PRNG, validation, or MATLAB file changed')
        if len(performance)!=60 or len(validation_results)!=6:
            raise ValueError('Execution count mismatch')
        if list(output.rglob('*.bin')):
            raise ValueError('Unexpected raw sample file in results')
        metadata.update(status='successful',ended_at=timestamp(),performance_executions=60,
            validation_executions=6,statistical_tests_completed=24,earlier_experiment_results_unchanged=True,
            original_executable_samplers_prng_validation_matlab_unchanged=True,
            ad_pvalue_policy='NA when omitted below existing AD calibration resolution; decision uses existing critical value. '
            'PASS means fail-to-reject at alpha 0.05; no multiple-testing adjustment.',
            output_sha256={name:sha256_file(output/name) for name in names if not name.startswith('artifacts/')})
        checked_json(metadata_path,metadata)
        final = dict(status='successful', output=str(output), performance_runs=len(performance), validation_runs=len(validation_results))
        if not args.quiet:
            final.update(performance=perf_rows, validation=val_rows)
        print(json.dumps(final,indent=2),flush=True)
    except (Exception,KeyboardInterrupt) as exc:
        metadata.update(status='failed',ended_at=timestamp(),error=f'{type(exc).__name__}: {exc}')
        checked_json(metadata_path,metadata)
        raise


if __name__=='__main__':
    main()
