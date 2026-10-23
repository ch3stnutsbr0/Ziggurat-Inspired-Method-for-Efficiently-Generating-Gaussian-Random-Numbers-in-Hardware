"""Experiment 10: Classical vs Trapezoid H=0/T=0 vs Trapezoid H=2/T=4 (xoshiro256+, 2^25 samples).
Speed versus samples and full-data goodness-of-fit at N=8..256; validation samples stream into RAM.
Run python3 -B experiments/experiment10.py from the repository root (Linux, gcc).
"""
import sys
sys.dont_write_bytecode = True
import argparse
import json
import math
import platform
import random
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import psutil
import scipy

import experiment05 as shared
import validation
from utils import load_config, sha256_file, validation_settings

LAYERS = shared.LAYERS
SAMPLES = shared.SAMPLES
TESTS = shared.TESTS
CONFIGS = [dict(key='basic', algorithm='basic', H=None, T=None, label='Classical Ziggurat', color='#2369a8', marker='o'),
           dict(key='trap_H0T0', algorithm='trapezoid', H=0, T=0, label='Trapezoid H=0, T=0', color='#3a9a5b', marker='^'),
           dict(key='trap_H2T4', algorithm='trapezoid', H=2, T=4, label='Trapezoid H=2, T=4', color='#cf612c', marker='s')]
BY_KEY = {c['key']: c for c in CONFIGS}


def key_of(record):
    return 'basic' if record['algorithm'] == 'basic' else f"trap_H{record['H']}T{record['T']}"


def check_config(config):
    expected = dict(experiment_id='experiment10', prng={'type': 'xoshiro256plus'}, layers=LAYERS,
                    samples_per_run=SAMPLES, seed=1,
                    configurations=[{'algorithm': 'basic'}, {'algorithm': 'trapezoid', 'head': 0, 'tail': 0},
                                    {'algorithm': 'trapezoid', 'head': 2, 'tail': 4}])
    if any(config.get(k) != v for k, v in expected.items()):
        raise ValueError('Experiment 10 requires xoshiro256plus, seed 1, N=8..256, 2^25 samples, '
                         'Classical + Trapezoid H0/T0 + Trapezoid H2/T4')
    performance = config['performance']
    checkpoints = performance['checkpoints']
    if (not checkpoints or len(checkpoints) > 32 or checkpoints[-1] != SAMPLES or checkpoints != sorted(set(checkpoints))
            or any(type(x) is not int or not 10000 <= x <= SAMPLES for x in checkpoints)):
        raise ValueError('Require increasing checkpoints ending at 2^25')
    if type(performance['repetitions']) is not int or not 1 <= performance['repetitions'] <= 20:
        raise ValueError('Require 1..20 timing repetitions')
    cpu = performance.get('pin_cpu')
    if cpu is not None and (type(cpu) is not int or not 0 <= cpu < psutil.cpu_count()):
        raise ValueError('pin_cpu must be an online CPU index')
    return validation_settings(config)


def sysfs(path):
    try: return Path(path).read_text().strip()
    except OSError as exc: return f'unavailable: {exc.strerror}'


def snapshot(cpu):
    base = f'/sys/devices/system/cpu/cpu{cpu}/cpufreq'
    return dict(time=shared.now(), governor=sysfs(f'{base}/scaling_governor'), scaling_cur_khz=sysfs(f'{base}/scaling_cur_freq'),
                scaling_max_khz=sysfs(f'{base}/scaling_max_freq'), boost=sysfs('/sys/devices/system/cpu/cpufreq/boost'),
                loadavg=sysfs('/proc/loadavg'))


def git_state(repo):
    def run(*args): return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True).stdout.strip()
    return dict(commit=run('rev-parse', 'HEAD'), dirty_files=run('status', '--porcelain').splitlines())


def aggregate(records, checkpoints):
    rows = []
    for n in LAYERS:
        for samples in checkpoints:
            medians = {}
            for cfg in CONFIGS:
                group = [r for r in records if key_of(r) == cfg['key'] and r['N'] == n and r['num_samples'] == samples]
                if len({r['checksum'] for r in group}) != 1:
                    raise ValueError('Repeated seed produced different streams')
                speeds = [r['throughput_samples_per_second'] / 1e6 for r in group]
                medians[cfg['key']] = statistics.median(speeds)
                rows.append(dict(experiment_id='experiment10', config=cfg['key'], algorithm=cfg['algorithm'], prng='xoshiro256plus',
                    N=n, H=cfg['H'], T=cfg['T'], measured_samples=samples, generated_samples=SAMPLES, repetitions=len(group),
                    median_Msamples_s=medians[cfg['key']], q1_Msamples_s=float(np.percentile(speeds, 25)),
                    q3_Msamples_s=float(np.percentile(speeds, 75)), min_Msamples_s=min(speeds), max_Msamples_s=max(speeds),
                    median_sampling_seconds=statistics.median(r['sampling_time_seconds'] for r in group)))
            for row in rows[-len(CONFIGS):]:
                row['speedup_vs_classical'] = row['median_Msamples_s'] / medians['basic']
                row['speedup_vs_H0T0'] = row['median_Msamples_s'] / medians['trap_H0T0']
    return rows


def plot(root, rows, checkpoints):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 8.1), sharex=True, sharey=True)
    fig.subplots_adjust(left=.075, right=.985, bottom=.11, top=.79, hspace=.22, wspace=.12)
    upper = math.ceil(max(r['q3_Msamples_s'] for r in rows) / 20) * 20
    for ax, n in zip(axes.flat, LAYERS):
        for cfg in CONFIGS:
            group = [r for r in rows if r['N'] == n and r['config'] == cfg['key']]
            ax.plot(checkpoints, [r['median_Msamples_s'] for r in group], color=cfg['color'], marker=cfg['marker'], lw=2, ms=5)
            ax.fill_between(checkpoints, [r['q1_Msamples_s'] for r in group], [r['q3_Msamples_s'] for r in group],
                            color=cfg['color'], alpha=.16)
        ax.set_title(f'N = {n} layers', fontweight='bold')
        ax.set_xscale('log'); ax.set_ylim(0, upper); ax.grid(True, alpha=.2)
        ax.set_xticks(checkpoints, [f'{x/1e6:.3g}M' if x >= 1e6 else f'{x/1e3:g}k' for x in checkpoints])
    fig.suptitle('Experiment 10 · xoshiro256+\nGaussian sampling speed versus measured sample count', fontsize=17, fontweight='bold', y=.99)
    fig.supxlabel('Samples measured from the start of each fixed 2^25-sample run (log scale)', y=.025)
    fig.supylabel('Throughput (million Gaussian samples / second)', x=.015)
    fig.legend(handles=[Line2D([0], [0], color=c['color'], marker=c['marker'], lw=2, label=c['label']) for c in CONFIGS],
               loc='upper center', bbox_to_anchor=(.5, .895), ncol=3, frameon=False)
    fig.savefig(root / 'figures/speed_vs_samples.png', dpi=250)
    fig.savefig(root / 'figures/speed_vs_samples.svg')
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 5))
    for cfg in CONFIGS:
        group = [r for r in rows if r['config'] == cfg['key'] and r['measured_samples'] == SAMPLES]
        ax.errorbar(LAYERS, [r['median_Msamples_s'] for r in group],
                    yerr=[[r['median_Msamples_s'] - r['q1_Msamples_s'] for r in group], [r['q3_Msamples_s'] - r['median_Msamples_s'] for r in group]],
                    color=cfg['color'], marker=cfg['marker'], lw=2, ms=6, capsize=3, label=cfg['label'])
    ax.set_xscale('log', base=2); ax.set_xticks(LAYERS, [str(n) for n in LAYERS]); ax.set_ylim(0, upper)
    ax.set_xlabel('Layers N'); ax.set_ylabel('Throughput at 2^25 samples (M samples/s)'); ax.grid(True, alpha=.2)
    ax.set_title('Experiment 10 · full-run throughput (median, IQR)', fontweight='bold'); ax.legend(frameon=False)
    fig.tight_layout(); fig.savefig(root / 'figures/throughput_vs_layers.png', dpi=250); fig.savefig(root / 'figures/throughput_vs_layers.svg')
    plt.close(fig)


def report(root, performance, results, session):
    full = {(r['config'], r['N']): r for r in performance if r['measured_samples'] == SAMPLES}
    lines = ['# Experiment 10 — Classical vs Trapezoid (H=0/T=0 and H=2/T=4), xoshiro256+', '',
        'Three configurations at N=8,16,32,64,128,256, seed 1, -O2: Classical Ziggurat, Trapezoid H=0/T=0 (unrefined) and '
        'Trapezoid H=2/T=4. Each timing or validation run generates exactly 2^25 = 33,554,432 samples; no Gaussian warmup. '
        f"Performance uses {session['configuration']['performance']['repetitions']} interleaved repetitions (order shuffled per round), each run in its own "
        f"process pinned to CPU {session['configuration']['performance'].get('pin_cpu')} with taskset, and cumulative checkpoints within each fixed-length run "
        '(a single stream, no separate prefix datasets).', '',
        '![Speed versus samples](../figures/speed_vs_samples.png)', '',
        '![Throughput versus layers](../figures/throughput_vs_layers.png)', '',
        'Curves show median cumulative throughput; bands/bars are interquartile ranges. Checkpoints within a run are dependent. '
        'Timings exclude initialization and table construction; a volatile checksum prevents loop elimination.', '',
        '## Full-run median speed (2^25 samples)', '',
        '| N | Classical M/s | Trap H0/T0 M/s | Trap H2/T4 M/s | H0T0 / Classical | H2T4 / Classical | H2T4 / H0T0 |',
        '|---:|---:|---:|---:|---:|---:|---:|']
    for n in LAYERS:
        c, a, b = full[('basic', n)], full[('trap_H0T0', n)], full[('trap_H2T4', n)]
        lines.append(f"| {n} | {c['median_Msamples_s']:.3f} | {a['median_Msamples_s']:.3f} | {b['median_Msamples_s']:.3f} | "
                     f"{a['speedup_vs_classical']:.3f}× | {b['speedup_vs_classical']:.3f}× | {b['speedup_vs_H0T0']:.3f}× |")
    lines += ['', '## Full-data goodness of fit', '',
        'Every dataset is tested against fixed N(0,1) using the existing Chi-square, KS, CvM and AD code at alpha=0.05; '
        'no parameter fitting, standardization or multiple-testing adjustment. PASS means failure to reject, not proof of Gaussianity. '
        'Chi-square uses 100 interior bins over [-5,5], two unbounded tails, and minimum-expected-count merging at 5. '
        'AD retains its existing finite-n approximation and critical-value decision (p-value may be NA). One seed.', '',
        '| Method | N | Mean | Variance | χ² p | KS p | CvM p | AD p | χ² | KS | CvM | AD |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|']
    def p(v): return 'NA' if v['p_value'] is None else f"{v['p_value']:.4g}"
    for row in results:
        t = row['tests']
        lines.append(f"| {BY_KEY[key_of(row)]['label']} | {row['N']} | {row['mean']:.6g} | {row['variance']:.7g} | "
                     + ' | '.join(p(t[x]) for x in TESTS) + ' | ' + ' | '.join('REJECT' if t[x]['reject'] else 'PASS' for x in TESTS) + ' |')
    failures = [dict(config=key_of(r), N=r['N'], test=t, statistic=v['statistic'], p_value=v['p_value'])
                for r in results for t, v in r['tests'].items() if v['reject']]
    by_cfg = {c['key']: sum(f['config'] == c['key'] for f in failures) for c in CONFIGS}
    lines += ['', f'Rejections: {len(failures)} of {len(results) * 4} tests ({", ".join(f"{k}: {v}" for k, v in by_cfg.items())}). '
        'With 72 tests at alpha=0.05, about 3.6 rejections are expected by chance even for a perfect generator.', '',
        'Full statistics, p-values and degrees of freedom: `../processed/validation_results.json`, `../tables/validation_results.csv`. '
        'Raw observations went through a pipe into RAM and were discarded; no sample files were saved.', '',
        '## Reproducibility and environment', '',
        f"Compiler: {session['compiler'].splitlines()[0]}; platform: {session['platform']}.",
        'Flags: `-std=c11 -Wall -Wextra -pedantic -O2`. Sources, configuration, hashes and commands are under artifacts/ and execution_order.json. '
        f"Git commit {session['git']['commit'][:12]}; uncommitted files at start: {session['git']['dirty_files'] or 'none'}. "
        'BIOS cap 3.2 GHz, boost off, SMT off; governor and frequency snapshots (reported, not effective frequency) are in execution_order.json. '
        'No CPU isolation was active, so desktop activity can add occasional outliers; see the IQR and `min/max` columns in `tables/performance_vs_samples.csv`.', '']
    (root / 'reports/experiment_report.md').write_text('\n'.join(lines))
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_suffix('.yaml'))
    parser.add_argument('--output-root', type=Path)
    args = parser.parse_args(); repo = Path(__file__).resolve().parents[1]
    config = load_config(args.config); settings = check_config(config)
    root = args.output_root.resolve() if args.output_root else (repo / config['output_dir']).resolve()
    if root.exists(): raise ValueError('Experiment 10 output exists; use a fresh output-root')
    sources = sorted((repo / 'c').glob('*.c')) + sorted((repo / 'c').glob('*.h'))
    protected = sources + [repo / 'c/Makefile', repo / 'experiments/validation.py', repo / 'experiments/experiment05.py'] + list((repo / 'matlab').glob('*.m'))
    protected_hashes = {str(p.relative_to(repo)): sha256_file(p) for p in protected}
    previous = shared.inventory(repo / 'experiments/results', root)
    required_memory = SAMPLES * 16 + 24 * 1_000_000 * 8 + 1024 ** 3
    available = psutil.virtual_memory().available
    if available < required_memory: raise RuntimeError(f'RAM preflight: need {required_memory}, available {available}')
    cpu = config['performance'].get('pin_cpu')
    for name in ('artifacts', 'processed', 'tables', 'figures', 'reports', 'raw/performance', 'raw/validation'):
        (root / name).mkdir(parents=True)
    for path in (Path(__file__), args.config, Path(__file__).with_name('experiment10_benchmark.c'), Path(__file__).with_name('experiment05.py')):
        shutil.copy2(path, root / 'artifacts' / path.name)
    shutil.copy2(repo / 'experiments/validation.py', root / 'artifacts/validation.py')
    for path in sources:
        dest = root / 'artifacts/c' / path.name; dest.parent.mkdir(exist_ok=True); shutil.copy2(path, dest)
    session = dict(experiment_id='experiment10', status='running', started_at=shared.now(), configuration=config,
        platform=platform.platform(), numpy_version=np.__version__, scipy_version=scipy.__version__, git=git_state(repo),
        memory_available_bytes=available, memory_estimate_bytes=required_memory, source_sha256=protected_hashes,
        system_start=snapshot(cpu or 0), raw_samples_saved=False, executions=[], errors=[])
    session_path = root / 'execution_order.json'; shared.save(session_path, session)
    records = []; results = []
    checkpoints = config['performance']['checkpoints']; repetitions = config['performance']['repetitions']
    n_runs = len(CONFIGS) * len(LAYERS)
    try:
        with tempfile.TemporaryDirectory(prefix='experiment10-') as temporary:
            work = Path(temporary); normal = work / 'benchmark'; timing = work / 'checkpoint_benchmark'
            flags = ['-std=c11', '-Wall', '-Wextra', '-pedantic', '-O2']
            core = [repo / 'c' / name for name in ('ziggurat_basic.c', 'ziggurat_trapezoid.c', 'xoshiro256plus.c', 'prng.c',
                    'ziggurat_basic_xoshiro256plus.c', 'ziggurat_trapezoid_xoshiro256plus.c')]
            builds = [['gcc', *flags, '-I', str(repo / 'c'), '-DBENCHMARK_OPTIMIZATION="O2"', *map(str, sorted((repo / 'c').glob('*.c'))), '-o', str(normal), '-lm'],
                      ['gcc', *flags, '-I', str(repo / 'c'), str(Path(__file__).with_name('experiment10_benchmark.c')), *map(str, core), '-o', str(timing), '-lm']]
            session.update(compiler=subprocess.check_output(['gcc', '--version'], text=True), compiler_flags=flags, build_commands=builds)
            for build in builds:
                done = subprocess.run(build, capture_output=True, text=True, check=True)
                if done.stderr: raise ValueError(f'Compiler diagnostics: {done.stderr}')
            session.update(validation_executable_sha256=sha256_file(normal), timing_executable_sha256=sha256_file(timing))
            shared.save(session_path, session)
            runs = [dict(algorithm=c['algorithm'], N=n, H=c['H'], T=c['T'], prng='xoshiro256plus', seed=config['seed'], samples=SAMPLES)
                    for n in LAYERS for c in CONFIGS]
            for repetition in range(1, repetitions + 1):
                order = runs.copy(); random.Random(config['seed'] + repetition).shuffle(order)
                for run in order:
                    argv = [str(timing), run['algorithm'], str(run['N']), str(run['seed']), str(run['H'] or 0), str(run['T'] or 0), *map(str, checkpoints)]
                    if cpu is not None: argv = ['taskset', '-c', str(cpu), *argv]
                    done = subprocess.run(argv, capture_output=True, text=True, check=True)
                    points = shared.full_report(done.stdout, run)
                    if [p['num_samples'] for p in points] != checkpoints or any(p['generated_samples'] != SAMPLES for p in points):
                        raise ValueError('Checkpoint identity/count mismatch')
                    for point in points: records.append(dict(point, repetition=repetition))
                    session['executions'].append(dict(kind='performance', **run, repetition=repetition, command=argv,
                                                      execution_order=len(session['executions']) + 1))
                session.setdefault('system_rounds', []).append(dict(round=repetition, **snapshot(cpu or 0)))
                shared.save(root / 'raw/performance/performance_runs.json', records); shared.save(session_path, session)
                print(f'Performance round {repetition}/{repetitions}: {n_runs} fixed 2^25-sample runs complete', flush=True)
            rows = aggregate(records, checkpoints)
            shared.save_csv(root / 'processed/performance_vs_samples.csv', rows)
            shutil.copy2(root / 'processed/performance_vs_samples.csv', root / 'tables/performance_vs_samples.csv')
            for run in runs:
                if psutil.virtual_memory().available < required_memory: raise RuntimeError('Available RAM fell below validation estimate')
                label = f"{run['algorithm']} H={run['H']} T={run['T']}" if run['algorithm'] == 'trapezoid' else 'basic'
                print(f"Validating {label} N={run['N']} at 2^25 samples", flush=True)
                values, c_summary, stream_hash = shared.collect(normal, run)
                try: numerical = validation.run_tests_chunked(values, settings, [])
                finally: del values
                if set(numerical['tests']) != set(TESTS): raise ValueError('Missing statistical test')
                for field in ('mean', 'variance'):
                    if not math.isclose(numerical[field], c_summary[field], rel_tol=1e-10, abs_tol=1e-10):
                        raise ValueError('Validation moments differ from C summary')
                timings = [r for r in records if key_of(r) == key_of(run) and r['N'] == run['N'] and r['num_samples'] == SAMPLES]
                if len(timings) != repetitions or any(r['checksum'] != c_summary['checksum'] for r in timings):
                    raise ValueError('Timing and validation streams differ')
                item = dict(run, stream_bytes=SAMPLES * 8, stream_sha256=stream_hash, raw_samples_saved=False,
                            validation_code_sha256=protected_hashes['experiments/validation.py'], **numerical)
                results.append(item)
                fname = f"{key_of(run)}_N{run['N']}_validation.json"
                shared.save(root / 'raw/validation' / fname, item)
                shared.save(root / 'processed/validation_results.json', results)
                session['executions'].append(dict(kind='validation', **run, tests=4, execution_order=len(session['executions']) + 1))
                shared.save(session_path, session)
                print('  ' + ', '.join(f"{TESTS[t]}={'REJECT' if v['reject'] else 'PASS'}" for t, v in numerical['tests'].items()), flush=True)
        validation_rows = []
        for item in results:
            row = {key: item[key] for key in ('algorithm', 'prng', 'N', 'H', 'T', 'samples', 'seed', 'mean', 'variance')}
            chi = item['tests']['chi_square']
            row.update(chi_final_bins=chi['final_bins'], chi_degrees_of_freedom=chi['degrees_of_freedom'])
            for test, label in TESTS.items():
                result = item['tests'][test]
                row.update({label + '_statistic': result['statistic'], label + '_p_value': 'NA' if result['p_value'] is None else result['p_value'],
                            label + '_decision': 'REJECT' if result['reject'] else 'PASS'})
            validation_rows.append(row)
        shared.save_csv(root / 'processed/validation_results.csv', validation_rows)
        shutil.copy2(root / 'processed/validation_results.csv', root / 'tables/validation_results.csv')
        plot(root, rows, checkpoints)
        session['system_end'] = snapshot(cpu or 0)
        failures = report(root, rows, results, session)
        if shared.inventory(repo / 'experiments/results', root) != previous: raise ValueError('Earlier experiment results changed')
        if {str(p.relative_to(repo)): sha256_file(p) for p in protected} != protected_hashes:
            raise ValueError('Existing C, validation or MATLAB files changed')
        if len(session['executions']) != n_runs * repetitions + n_runs or list(root.rglob('*.bin')):
            raise ValueError('Execution count or sample-retention mismatch')
        tests_done = 4 * n_runs
        session.update(status='successful', ended_at=shared.now(), performance_executions=n_runs * repetitions, validation_executions=n_runs,
                       statistical_tests_completed=tests_done, validation_rejections=failures,
                       previous_results_and_existing_sources_unchanged=True)
        shared.save(session_path, session)
        shared.save(root / 'verification.json', dict(status='successful', verified_at=shared.now(), raw_sample_files=0,
            statistical_tests_completed=tests_done, validation_rejections=failures, previous_results_and_existing_sources_unchanged=True,
            output_sha256={str(p.relative_to(root)): sha256_file(p) for p in root.rglob('*') if p.is_file()}))
        print(json.dumps(dict(status='successful', output=str(root), validation_rejections=failures), indent=2), flush=True)
    except (Exception, KeyboardInterrupt) as exc:
        session.update(status='failed', ended_at=shared.now()); session['errors'].append(f'{type(exc).__name__}: {exc}')
        shared.save(session_path, session); raise


if __name__ == '__main__': main()
