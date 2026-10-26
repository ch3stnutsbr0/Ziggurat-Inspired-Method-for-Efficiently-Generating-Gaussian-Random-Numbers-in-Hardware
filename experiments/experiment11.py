"""Experiment 11: Classical vs Trapezoid over a head/tail/layer grid.

Precomputed xoshiro256+ uniforms; every timed run is pinned to one isolated CPU.
Trapezoid configurations get full-data goodness-of-fit tests. Results are CSV
files only; raw Gaussian samples are never written to disk.

    .venv/bin/python -B experiments/experiment11.py                      # everything
    .venv/bin/python -B experiments/experiment11.py --phase performance  # timing only
    .venv/bin/python -B experiments/experiment11.py --phase validation --resume
    .venv/bin/python -B experiments/experiment11.py --dry-run            # print the plan

See experiments/EXPERIMENT_11_README.md.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import csv
import fcntl
import hashlib
import json
import math
import os
import platform
import random
import shutil
import statistics
import subprocess
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'experiments'))
from utils import load_config, validation_settings  # noqa: E402

TESTS = {'chi_square': 'chi2', 'kolmogorov_smirnov': 'ks', 'cramer_von_mises': 'cvm', 'anderson_darling': 'ad'}
MARKER = 'BENCHMARK_JSON: '
PERF_FIELDS = ['config_id', 'algorithm', 'N', 'H', 'T', 'seed', 'repetition', 'run_order', 'status', 'returncode',
               'samples', 'warmup', 'uniforms_consumed', 'prng_calls_per_sample', 'total_time_s',
               'throughput_samples_per_s', 'throughput_msamples_per_s', 'time_per_sample_ns', 'process_wall_s',
               'buffer_utilization', 'checksum', 'mean', 'variance', 'cpu', 'cpu_scaling_khz_before', 'started_utc', 'error']
SUMMARY_FIELDS = ['config_id', 'algorithm', 'N', 'H', 'T', 'seed', 'runs_ok', 'prng_calls_per_sample',
                  'median_throughput_msamples_per_s', 'mean_throughput_msamples_per_s', 'min_throughput_msamples_per_s',
                  'max_throughput_msamples_per_s', 'cv_percent', 'median_total_time_s', 'speedup_vs_classical',
                  'checksums_identical']
VALID_FIELDS = (['config_id', 'algorithm', 'N', 'H', 'T', 'seed', 'samples', 'status', 'mean', 'variance',
                 'prng_calls_per_sample', 'chi2_statistic', 'chi2_degrees_of_freedom', 'chi2_final_bins',
                 'chi2_p_value', 'chi2_reject']
                + [f'{t}_{k}' for t in ('ks', 'cvm') for k in ('statistic', 'p_value', 'reject')]
                + ['ad_statistic', 'ad_p_value', 'ad_critical_value', 'ad_reject', 'rejections', 'alpha',
                   'checksum', 'checksum_matches_performance', 'stream_sha256', 'wall_s', 'error'])
ENV_FIELDS = ['session', 'event', 'utc', 'key', 'value']


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError as exc:
        return f'unavailable: {exc.strerror}'


def cpulist(text):
    cpus = set()
    for part in filter(None, text.strip().split(',')):
        lo, _, hi = part.partition('-')
        if lo.isdigit() and (not hi or hi.isdigit()):
            cpus.update(range(int(lo), int(hi or lo) + 1))
    return cpus


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------- configuration

def check_config(cfg):
    def ints(name, values, lo, hi):
        if not isinstance(values, list) or not values or any(type(v) is not int or not lo <= v <= hi for v in values) \
                or len(set(values)) != len(values):
            raise ValueError(f'{name}: need a list of distinct integers in [{lo}, {hi}]')
    if cfg.get('experiment_id') != 'experiment11' or cfg.get('prng') != 'xoshiro256plus':
        raise ValueError('experiment_id must be experiment11 and prng must be xoshiro256plus')
    ints('layers', cfg['layers'], 1, 256)
    ints('heads', cfg['heads'], 0, 16)
    ints('tails', cfg['tails'], 0, 16)
    ints('seeds', cfg['seeds'], 0, 2**64 - 1)
    for name, lo in (('samples', 2), ('warmup', 0), ('uniform_buffer_bytes', 8)):
        if type(cfg.get(name)) is not int or cfg[name] < lo:
            raise ValueError(f'{name}: need an integer >= {lo}')
    if cfg['uniform_buffer_bytes'] % 8:
        raise ValueError('uniform_buffer_bytes must be a multiple of 8')
    perf, val = cfg['performance'], cfg['validation']
    if type(perf['repetitions']) is not int or not 1 <= perf['repetitions'] <= 50:
        raise ValueError('performance.repetitions: need 1..50')
    if type(perf['cpu']) is not int or perf['cpu'] not in cpulist(read('/sys/devices/system/cpu/online')):
        raise ValueError('performance.cpu must be an online CPU')
    if type(val['workers']) is not int or not 1 <= val['workers'] <= (os.cpu_count() or 1):
        raise ValueError('validation.workers: need 1..number of CPUs')
    return validation_settings({'validation': {k: val[k] for k in ('significance_level', 'chi_square')}})


def configurations(cfg):
    out = []
    for n in cfg['layers']:
        if cfg['include_classical']:
            out.append(dict(config_id=f'classical_N{n}', algorithm='basic', N=n, H='', T=''))
        for h in cfg['heads']:
            for t in cfg['tails']:
                out.append(dict(config_id=f'trap_N{n}_H{h}_T{t}', algorithm='trapezoid', N=n, H=h, T=t))
    return out


def command(cfg, binary, c, seed, cache, samples=None, warmup=None):
    argv = [str(binary), '--algorithm', c['algorithm'], '--layers', str(c['N']), '--seed', str(seed),
            '--prng', cfg['prng'], '--uniform-mode', 'precomputed',
            '--uniform-buffer-bytes', str(cfg['uniform_buffer_bytes']), '--uniform-buffer-cache', str(cache),
            '--samples', str(cfg['samples'] if samples is None else samples),
            '--warmup', str(cfg['warmup'] if warmup is None else warmup), '--report-json']
    if c['algorithm'] == 'trapezoid':
        argv += ['--head', str(c['H']), '--tail', str(c['T'])]
    return argv


def report(stdout):
    lines = [line[len(MARKER):] for line in stdout.splitlines() if line.startswith(MARKER)]
    return json.loads(lines[-1]) if lines else None


# ---------------------------------------------------------------- CSV logging

class CsvLog:
    """Append-only CSV, flushed and fsynced per row, so an interrupted run loses at most one row."""

    def __init__(self, path, fields):
        self.path, self.fields = path, fields
        if path.exists():
            data = path.read_bytes()
            if data and not data.endswith(b'\n'):          # drop a torn final row
                path.write_bytes(data[:data.rfind(b'\n') + 1])
            with path.open(newline='') as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and reader.fieldnames != fields:
                    raise ValueError(f'{path.name}: column layout differs from this script')
                self.rows = list(reader)
        else:
            self.rows = []
        new = not path.exists() or path.stat().st_size == 0
        self.stream = path.open('a', newline='')
        self.writer = csv.DictWriter(self.stream, fieldnames=fields)
        if new:
            self.writer.writeheader()
            self._sync()

    def _sync(self):
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def write(self, row):
        row = {k: row.get(k, '') for k in self.fields}
        self.writer.writerow(row)
        self._sync()
        self.rows.append({k: str(v) for k, v in row.items()})

    def close(self):
        self.stream.close()


def write_csv_atomic(path, fields, rows):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ---------------------------------------------------------------- environment

def environment(cfg, binary, config_path):
    cpu = cfg['performance']['cpu']
    freq = f'/sys/devices/system/cpu/cpu{cpu}/cpufreq'
    irqs_on_cpu = 0
    for path in Path('/proc/irq').glob('*/effective_affinity_list'):
        if cpu in cpulist(read(path)):
            irqs_on_cpu += 1
    git = lambda *a: subprocess.run(['git', '-C', str(REPO), *a], capture_output=True, text=True).stdout.strip()
    irqbalance = subprocess.run(['systemctl', 'is-active', 'irqbalance'], capture_output=True, text=True).stdout.strip()
    return {
        'kernel': platform.release(), 'kernel_cmdline': read('/proc/cmdline'),
        'isolated_cpus': read('/sys/devices/system/cpu/isolated'), 'nohz_full_cpus': read('/sys/devices/system/cpu/nohz_full'),
        'smt_control': read('/sys/devices/system/cpu/smt/control'), 'online_cpus': read('/sys/devices/system/cpu/online'),
        'benchmark_cpu': cpu, f'irqs_effective_on_cpu{cpu}': irqs_on_cpu, 'irqbalance': irqbalance,
        'governor': read(f'{freq}/scaling_governor'), 'scaling_driver': read(f'{freq}/scaling_driver'),
        'scaling_min_khz': read(f'{freq}/scaling_min_freq'), 'scaling_max_khz': read(f'{freq}/scaling_max_freq'),
        'scaling_cur_khz': read(f'{freq}/scaling_cur_freq'), 'boost': read('/sys/devices/system/cpu/cpufreq/boost'),
        'loadavg': read('/proc/loadavg'), 'python': platform.python_version(),
        'git_commit': git('rev-parse', 'HEAD'), 'git_dirty_files': len(git('status', '--porcelain').splitlines()),
        'binary': str(binary), 'binary_sha256': sha256(binary), 'config_sha256': sha256(config_path),
    }


def log_environment(env_log, session, event, cfg, binary, config_path):
    utc = now()
    for key, value in environment(cfg, binary, config_path).items():
        env_log.write(dict(session=session, event=event, utc=utc, key=key, value=value))


# ---------------------------------------------------------------- performance

def performance(cfg, binary, configs, cache_for, perf_log):
    cpu, reps = cfg['performance']['cpu'], cfg['performance']['repetitions']
    done = {(r['config_id'], r['seed'], r['repetition']) for r in perf_log.rows if r['status'] == 'ok'}
    jobs = [(c, s) for c in configs for s in cfg['seeds']]
    total, count = len(jobs) * reps, 0
    for rep in range(1, reps + 1):
        order = jobs[:]
        random.Random(cfg['performance']['shuffle_seed'] + rep).shuffle(order)
        for index, (c, seed) in enumerate(order, 1):
            count += 1
            if (c['config_id'], str(seed), str(rep)) in done:
                continue
            argv = ['taskset', '-c', str(cpu), *command(cfg, binary, c, seed, cache_for(seed))]
            row = dict(c, seed=seed, repetition=rep, run_order=index, samples=cfg['samples'], warmup=cfg['warmup'], cpu=cpu,
                       cpu_scaling_khz_before=read(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_cur_freq'),
                       started_utc=now())
            start = time.monotonic()
            try:
                proc = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
                rc, out, err = proc.returncode, proc.stdout, proc.stderr
            except subprocess.TimeoutExpired:
                rc, out, err = 'timeout', '', 'timeout after 1800 s'
            row.update(returncode=rc, process_wall_s=time.monotonic() - start)
            j = report(out)
            if j:
                row.update(uniforms_consumed=j['uniform_values_consumed'], prng_calls_per_sample=j['uniforms_per_sample'],
                           buffer_utilization=j['buffer_utilization'], total_time_s=j['sampling_time_seconds'])
            if rc == 0 and j and j['complete'] and j['num_samples'] == cfg['samples']:
                row.update(status='ok', throughput_samples_per_s=j['throughput_samples_per_second'],
                           throughput_msamples_per_s=j['throughput_million_samples_per_second'],
                           time_per_sample_ns=j['time_per_sample_ns'], checksum=repr(j['checksum']),
                           mean=j['mean'], variance=j['variance'])
            else:
                row.update(status='buffer_exhausted' if (j and j.get('buffer_exhausted')) or rc == 3 else 'failed',
                           error=err.strip()[-300:])
            perf_log.write(row)
            speed = f"{row['throughput_msamples_per_s']:.2f} Msamples/s" if row['status'] == 'ok' else row['status'].upper()
            print(f"[perf {count}/{total}] rep {rep} {c['config_id']} seed {seed}: {speed}", flush=True)


def summarize(cfg, configs, perf_rows, path):
    rows, classical = [], {}
    for c in configs:
        for seed in cfg['seeds']:
            group = [r for r in perf_rows if r['config_id'] == c['config_id'] and r['seed'] == str(seed) and r['status'] == 'ok']
            if not group:
                continue
            speeds = [float(r['throughput_msamples_per_s']) for r in group]
            row = dict(c, seed=seed, runs_ok=len(group), prng_calls_per_sample=group[0]['prng_calls_per_sample'],
                       median_throughput_msamples_per_s=statistics.median(speeds), mean_throughput_msamples_per_s=statistics.mean(speeds),
                       min_throughput_msamples_per_s=min(speeds), max_throughput_msamples_per_s=max(speeds),
                       cv_percent=100 * statistics.stdev(speeds) / statistics.mean(speeds) if len(speeds) > 1 else '',
                       median_total_time_s=statistics.median(float(r['total_time_s']) for r in group),
                       checksums_identical=int(len({r['checksum'] for r in group}) == 1))
            if c['algorithm'] == 'basic':
                classical[(c['N'], seed)] = row['median_throughput_msamples_per_s']
            rows.append(row)
    for row in rows:
        base = classical.get((row['N'], row['seed']))
        row['speedup_vs_classical'] = row['median_throughput_msamples_per_s'] / base if base else ''
    write_csv_atomic(path, SUMMARY_FIELDS, rows)


# ---------------------------------------------------------------- validation

def validate_one(argv, samples, settings):
    """Stream exactly `samples` binary64 values through a pipe into RAM, test, discard."""
    import numpy as np
    import validation
    values = np.empty(samples, dtype='<f8')
    view = memoryview(values).cast('B')
    read_fd, write_fd = os.pipe()
    process, start = None, time.monotonic()
    try:
        process = subprocess.Popen([*argv, '--output', f'/dev/fd/{write_fd}'], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, pass_fds=(write_fd,))
        os.close(write_fd)
        write_fd = None
        with os.fdopen(read_fd, 'rb', buffering=0) as pipe:
            read_fd, received = None, 0
            while received < len(view):
                amount = pipe.readinto(view[received:])
                if not amount:
                    break
                received += amount
            extra = pipe.read(1)
        stdout, stderr = process.communicate()
        j = report(stdout.decode())
        if process.returncode or received != len(view) or extra or not j or not j['complete']:
            raise RuntimeError(f'incomplete stream {received}/{len(view)} bytes, rc={process.returncode}: '
                               f'{stderr.decode().strip()[-300:]}')
        digest = hashlib.sha256(view).hexdigest()
        view.release()
        result = validation.run_tests_chunked(values, settings, [])
        del values
        for field in ('mean', 'variance'):
            if not math.isclose(result[field], j[field], rel_tol=1e-10, abs_tol=1e-10):
                raise RuntimeError(f'{field} differs between Python and C')
        return dict(status='ok', result=result, report=j, digest=digest, wall=time.monotonic() - start)
    except Exception as exc:  # recorded per configuration; the sweep continues
        return dict(status='failed', error=f'{type(exc).__name__}: {exc}', wall=time.monotonic() - start)
    finally:
        if read_fd is not None:
            os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()


def validation_row(c, seed, cfg, settings, outcome, perf_checksums):
    row = dict(c, seed=seed, samples=cfg['samples'], status=outcome['status'], wall_s=outcome['wall'],
               alpha=settings['significance_level'], error=outcome.get('error', ''))
    if outcome['status'] != 'ok':
        return row
    result, j = outcome['result'], outcome['report']
    row.update(mean=result['mean'], variance=result['variance'], prng_calls_per_sample=j['uniforms_per_sample'],
               checksum=repr(j['checksum']), stream_sha256=outcome['digest'])
    for test, label in TESTS.items():
        value = result['tests'][test]
        row[f'{label}_statistic'] = value['statistic']
        row[f'{label}_p_value'] = '' if value['p_value'] is None else value['p_value']
        row[f'{label}_reject'] = int(value['reject'])
    chi, ad = result['tests']['chi_square'], result['tests']['anderson_darling']
    row.update(chi2_degrees_of_freedom=chi['degrees_of_freedom'], chi2_final_bins=chi['final_bins'],
               ad_critical_value=ad.get('critical_value', ''), rejections=sum(row[f'{l}_reject'] for l in TESTS.values()))
    reference = perf_checksums.get((c['config_id'], str(seed)))
    row['checksum_matches_performance'] = '' if reference is None else int(reference == row['checksum'])
    return row


def validate(cfg, settings, binary, configs, cache_for, valid_log, perf_rows):
    done = {(r['config_id'], r['seed']) for r in valid_log.rows if r['status'] == 'ok'}
    wanted = [c for c in configs if c['algorithm'] == 'trapezoid' or cfg['validation']['include_classical']]
    jobs = [(c, s) for c in wanted for s in cfg['seeds'] if (c['config_id'], str(s)) not in done]
    perf_checksums = {(r['config_id'], r['seed']): r['checksum'] for r in perf_rows if r['status'] == 'ok'}
    print(f'[valid] {len(jobs)} validation(s) to run, {len(done)} already done, '
          f"{cfg['validation']['workers']} worker(s)", flush=True)
    with ProcessPoolExecutor(max_workers=cfg['validation']['workers']) as pool:
        futures = {pool.submit(validate_one, command(cfg, binary, c, s, cache_for(s)), cfg['samples'], settings): (c, s)
                   for c, s in jobs}
        for count, future in enumerate(as_completed(futures), 1):
            c, seed = futures[future]
            row = validation_row(c, seed, cfg, settings, future.result(), perf_checksums)
            valid_log.write(row)
            verdict = (', '.join(f"{l}={'REJECT' if row[f'{l}_reject'] else 'pass'}" for l in TESTS.values())
                       if row['status'] == 'ok' else 'FAILED: ' + row['error'])
            print(f"[valid {count}/{len(jobs)}] {c['config_id']} seed {seed}: {verdict}", flush=True)


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_suffix('.yaml'))
    parser.add_argument('--phase', choices=['all', 'performance', 'validation'], default='all')
    parser.add_argument('--resume', action='store_true', help='continue in an existing output directory, skipping finished work')
    parser.add_argument('--output-dir', type=Path, help='override output_dir from the config')
    parser.add_argument('--dry-run', action='store_true', help='print the plan and exit without running anything')
    args = parser.parse_args()

    config_path = args.config.resolve()
    cfg = load_config(config_path)
    settings = check_config(cfg)
    binary = (REPO / cfg['binary']).resolve()
    out = (args.output_dir or REPO / cfg['output_dir']).resolve()
    configs = configurations(cfg)
    run_perf = args.phase in ('all', 'performance') and cfg['performance']['enabled']
    run_valid = args.phase in ('all', 'validation') and cfg['validation']['enabled']
    n_valid = sum(c['algorithm'] == 'trapezoid' or cfg['validation']['include_classical'] for c in configs) * len(cfg['seeds'])
    print(f"configurations: {len(configs)}  seeds: {len(cfg['seeds'])}  samples/run: {cfg['samples']:,}\n"
          f"timed runs: {len(configs) * len(cfg['seeds']) * cfg['performance']['repetitions'] if run_perf else 0}"
          f" on CPU {cfg['performance']['cpu']}  validations: {n_valid if run_valid else 0}\noutput: {out}", flush=True)
    if args.dry_run:
        c = next(c for c in configs if c['algorithm'] == 'trapezoid')
        print('example timed command:', 'taskset -c', cfg['performance']['cpu'], ' '.join(command(cfg, binary, c, cfg['seeds'][0], '<cache>')))
        return

    if not binary.is_file():
        sys.exit(f'benchmark binary not found: {binary}\nbuild it with: make -C c CC=gcc O2')
    if run_perf and cfg['performance']['require_isolation']:
        cpu = cfg['performance']['cpu']
        if cpu not in cpulist(read('/sys/devices/system/cpu/isolated')):
            sys.exit(f'CPU {cpu} is not isolated (/sys/devices/system/cpu/isolated = '
                     f"'{read('/sys/devices/system/cpu/isolated')}').\nSee EXPERIMENT_11_README.md, or set "
                     'performance.require_isolation: false for an unisolated run.')
    if out.exists() and not args.resume:
        sys.exit(f'{out} already exists; use --resume to continue it or --output-dir for a fresh run')
    out.mkdir(parents=True, exist_ok=True)
    lock = (out / '.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(f'another experiment11 process is using {out}')
    saved = out / 'config.yaml'
    if saved.exists() and saved.read_bytes() != config_path.read_bytes():
        sys.exit(f'{saved} differs from {config_path}; resume with the same config or use a new --output-dir')
    if not saved.exists():
        shutil.copy2(config_path, saved)

    session = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    env_log = CsvLog(out / 'environment.csv', ENV_FIELDS)
    perf_log = CsvLog(out / 'performance_runs.csv', PERF_FIELDS)
    valid_log = CsvLog(out / 'validation_results.csv', VALID_FIELDS)
    cache_root = Path(tempfile.mkdtemp(prefix='experiment11-uniforms-', dir=cfg.get('cache_dir')))
    caches = {}

    def cache_for(seed):
        """One private uniform cache per seed: filled once (outside timing), then loaded by every run."""
        if seed not in caches:
            path = cache_root / f"{cfg['prng']}_seed{seed}_{cfg['uniform_buffer_bytes']}.bin"
            prime = command(cfg, binary, configs[0], seed, path, samples=1000, warmup=0)
            subprocess.run(prime, capture_output=True, text=True, check=True)
            caches[seed] = path
        return caches[seed]

    started = time.monotonic()
    try:
        log_environment(env_log, session, 'session_start', cfg, binary, config_path)
        if run_perf:
            performance(cfg, binary, configs, cache_for, perf_log)
            log_environment(env_log, session, 'performance_end', cfg, binary, config_path)
            summarize(cfg, configs, perf_log.rows, out / 'performance_summary.csv')
        if run_valid:
            for seed in cfg['seeds']:
                cache_for(seed)               # create caches before workers read them in parallel
            validate(cfg, settings, binary, configs, cache_for, valid_log, perf_log.rows)
        log_environment(env_log, session, 'session_end', cfg, binary, config_path)
        env_log.write(dict(session=session, event='session_end', utc=now(), key='session_elapsed_s',
                           value=time.monotonic() - started))
    finally:
        shutil.rmtree(cache_root, ignore_errors=True)
        for log in (env_log, perf_log, valid_log):
            log.close()

    def unresolved(rows, keys):  # failures with no later successful retry
        ok = {tuple(r[k] for k in keys) for r in rows if r['status'] == 'ok'}
        return len({tuple(r[k] for k in keys) for r in rows if r['status'] != 'ok'} - ok)
    bad_perf = unresolved(perf_log.rows, ('config_id', 'seed', 'repetition'))
    bad_valid = unresolved(valid_log.rows, ('config_id', 'seed'))
    print(f'\ndone in {time.monotonic() - started:.0f} s; results in {out}')
    if bad_perf or bad_valid:
        print(f'WARNING: {bad_perf} failed timed run(s), {bad_valid} failed validation(s); rerun with --resume to retry',
              file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
