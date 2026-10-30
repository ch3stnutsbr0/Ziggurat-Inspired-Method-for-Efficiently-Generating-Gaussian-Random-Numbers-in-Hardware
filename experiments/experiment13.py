"""Experiment 13: multi-seed repeat of the Experiment 11 grid (Classical and Trapezoid, N x H x T).

Performance: a few seeds, precomputed xoshiro256+ uniforms, every timed run pinned to one isolated CPU. The 2 GiB
uniform cache exists for one seed at a time and is deleted when that seed is finished.
Validation: many seeds, inline xoshiro256+ (bit-identical stream, no cache), full-data goodness-of-fit tests for
every configuration, Classical included as the control. Results are CSV files only; raw samples are never written.

    .venv/bin/python -B experiments/experiment13.py --dry-run            # print the plan and a runtime estimate
    .venv/bin/python -B experiments/experiment13.py                      # everything
    .venv/bin/python -B experiments/experiment13.py --phase performance  # timing only
    .venv/bin/python -B experiments/experiment13.py --phase validation --resume

See experiments/EXPERIMENT_13_README.md. Reuses the run, logging and validation code of experiment11.py.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import fcntl
import os
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
import experiment11 as e11  # noqa: E402

ALL_SEEDS_FIELDS = ['config_id', 'algorithm', 'N', 'H', 'T', 'seeds', 'runs_ok', 'prng_calls_per_sample',
                    'median_throughput_msamples_per_s', 'mean_of_seed_medians_msamples_per_s',
                    'sd_of_seed_medians_msamples_per_s', 'min_seed_median_msamples_per_s',
                    'max_seed_median_msamples_per_s', 'speedup_vs_classical']


# ---------------------------------------------------------------- configuration

def check_config(cfg):
    def ints(name, values, lo, hi):
        if not isinstance(values, list) or not values or any(type(v) is not int or not lo <= v <= hi for v in values) \
                or len(set(values)) != len(values):
            raise ValueError(f'{name}: need a list of distinct integers in [{lo}, {hi}]')
    if cfg.get('experiment_id') != 'experiment13' or cfg.get('prng') != 'xoshiro256plus':
        raise ValueError('experiment_id must be experiment13 and prng must be xoshiro256plus')
    perf, val = cfg['performance'], cfg['validation']
    ints('layers', cfg['layers'], 1, 256)
    ints('heads', cfg['heads'], 0, 16)
    ints('tails', cfg['tails'], 0, 16)
    ints('performance.seeds', perf['seeds'], 0, 2**64 - 1)
    ints('validation.seeds', val['seeds'], 0, 2**64 - 1)
    for name, lo in (('samples', 2), ('warmup', 0), ('uniform_buffer_bytes', 8)):
        if type(cfg.get(name)) is not int or cfg[name] < lo:
            raise ValueError(f'{name}: need an integer >= {lo}')
    if cfg['uniform_buffer_bytes'] % 8:
        raise ValueError('uniform_buffer_bytes must be a multiple of 8')
    if type(perf['repetitions']) is not int or not 1 <= perf['repetitions'] <= 50:
        raise ValueError('performance.repetitions: need 1..50')
    if type(perf['cpu']) is not int or perf['cpu'] not in e11.cpulist(e11.read('/sys/devices/system/cpu/online')):
        raise ValueError('performance.cpu must be an online CPU')
    if val['uniform_mode'] not in ('inline', 'precomputed'):
        raise ValueError('validation.uniform_mode: inline or precomputed')
    if type(val['workers']) is not int or not 1 <= val['workers'] <= (os.cpu_count() or 1):
        raise ValueError('validation.workers: need 1..number of CPUs')
    return validation_settings({'validation': {k: val[k] for k in ('significance_level', 'chi_square')}})


def check_machine(cfg):
    """Refuse to time anything unless isolation, boost and governor are as configured."""
    perf = cfg['performance']
    cpu, problems = perf['cpu'], []
    isolated = e11.read('/sys/devices/system/cpu/isolated')
    if perf['require_isolation'] and cpu not in e11.cpulist(isolated):
        problems.append(f"CPU {cpu} is not isolated (isolated = '{isolated}')")
    boost = e11.read('/sys/devices/system/cpu/cpufreq/boost')
    if perf.get('require_boost') is not None and boost != str(perf['require_boost']):
        problems.append(f"boost is '{boost}', config requires {perf['require_boost']}")
    governor = e11.read(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor')
    if perf.get('require_governor') and governor != perf['require_governor']:
        problems.append(f"CPU {cpu} governor is '{governor}', config requires '{perf['require_governor']}'")
    if problems:
        sys.exit('machine not ready for timing:\n  ' + '\n  '.join(problems) + '\nSee EXPERIMENT_13_README.md.')


def validation_command(cfg, binary, c, seed, cache=None):
    if cfg['validation']['uniform_mode'] == 'precomputed':
        return e11.command(cfg, binary, c, seed, cache, warmup=0)
    argv = [str(binary), '--algorithm', c['algorithm'], '--layers', str(c['N']), '--seed', str(seed),
            '--prng', cfg['prng'], '--uniform-mode', 'inline', '--samples', str(cfg['samples']), '--warmup', '0',
            '--report-json']
    if c['algorithm'] == 'trapezoid':
        argv += ['--head', str(c['H']), '--tail', str(c['T'])]
    return argv


def prime_cache(cfg, binary, configs, seed, path):
    """Fill the per-seed uniform cache once, outside timing."""
    argv = e11.command(cfg, binary, configs[0], seed, path, samples=1000, warmup=0)
    subprocess.run(argv, capture_output=True, text=True, check=True)
    return path


# ---------------------------------------------------------------- performance

def performance(cfg, binary, configs, perf_log, env_log, session, config_path, cache_root):
    perf = cfg['performance']
    for k, seed in enumerate(perf['seeds'], 1):
        done = {(r['config_id'], r['repetition']) for r in perf_log.rows if r['status'] == 'ok' and r['seed'] == str(seed)}
        if len(done) == len(configs) * perf['repetitions']:
            print(f'[perf] seed {seed}: already complete', flush=True)
            continue
        print(f'[perf] seed {seed} ({k}/{len(perf["seeds"])}): priming the uniform cache', flush=True)
        path = prime_cache(cfg, binary, configs, seed,
                           cache_root / f"{cfg['prng']}_seed{seed}_{cfg['uniform_buffer_bytes']}.bin")
        try:
            one_seed = dict(cfg, seeds=[seed], performance=dict(perf, shuffle_seed=perf['shuffle_seed'] + 1000 * seed))
            e11.performance(one_seed, binary, configs, lambda _seed: path, perf_log)
        finally:
            path.unlink(missing_ok=True)
        e11.log_environment(env_log, session, f'performance_seed{seed}_end', cfg, binary, config_path)


def summarize_all_seeds(configs, perf_rows, path):
    """One row per configuration: pooled median and the spread of per-seed medians."""
    rows, classical = [], {}
    for c in configs:
        group = [r for r in perf_rows if r['config_id'] == c['config_id'] and r['status'] == 'ok']
        if not group:
            continue
        by_seed = {}
        for r in group:
            by_seed.setdefault(r['seed'], []).append(float(r['throughput_msamples_per_s']))
        medians = [statistics.median(v) for v in by_seed.values()]
        row = dict(c, seeds=len(by_seed), runs_ok=len(group), prng_calls_per_sample=group[0]['prng_calls_per_sample'],
                   median_throughput_msamples_per_s=statistics.median(float(r['throughput_msamples_per_s']) for r in group),
                   mean_of_seed_medians_msamples_per_s=statistics.mean(medians),
                   sd_of_seed_medians_msamples_per_s=statistics.stdev(medians) if len(medians) > 1 else '',
                   min_seed_median_msamples_per_s=min(medians), max_seed_median_msamples_per_s=max(medians))
        if c['algorithm'] == 'basic':
            classical[c['N']] = row['median_throughput_msamples_per_s']
        rows.append(row)
    for row in rows:
        base = classical.get(row['N'])
        row['speedup_vs_classical'] = row['median_throughput_msamples_per_s'] / base if base else ''
    e11.write_csv_atomic(path, ALL_SEEDS_FIELDS, rows)


# ---------------------------------------------------------------- validation

def validate(cfg, settings, binary, configs, valid_log, perf_rows, cache_root):
    val = cfg['validation']
    wanted = [c for c in configs if c['algorithm'] == 'trapezoid' or val['include_classical']]
    done = {(r['config_id'], r['seed']) for r in valid_log.rows if r['status'] == 'ok'}
    jobs = [(c, s) for s in val['seeds'] for c in wanted if (c['config_id'], str(s)) not in done]  # seed by seed
    perf_checksums = {(r['config_id'], r['seed']): r['checksum'] for r in perf_rows if r['status'] == 'ok'}
    print(f"[valid] {len(jobs)} validation(s) to run, {len(done)} already done, {val['workers']} worker(s), "
          f"{val['uniform_mode']} uniforms", flush=True)
    caches = {}
    if val['uniform_mode'] == 'precomputed':   # one cache per seed for the whole phase: needs 2 GiB x seeds of disk
        for s in {s for _, s in jobs}:
            caches[s] = prime_cache(cfg, binary, configs, s, cache_root / f'validation_seed{s}.bin')
    with ProcessPoolExecutor(max_workers=val['workers']) as pool:
        futures = {pool.submit(e11.validate_one, validation_command(cfg, binary, c, s, caches.get(s)), cfg['samples'],
                               settings): (c, s) for c, s in jobs}
        for count, future in enumerate(as_completed(futures), 1):
            c, seed = futures[future]
            row = e11.validation_row(c, seed, cfg, settings, future.result(), perf_checksums)
            valid_log.write(row)
            verdict = (', '.join(f"{l}={'REJECT' if row[f'{l}_reject'] else 'pass'}" for l in e11.TESTS.values())
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
    perf, val = cfg['performance'], cfg['validation']
    binary = (REPO / cfg['binary']).resolve()
    out = (args.output_dir or REPO / cfg['output_dir']).resolve()
    configs = e11.configurations(cfg)
    run_perf = args.phase in ('all', 'performance') and perf['enabled']
    run_valid = args.phase in ('all', 'validation') and val['enabled']
    n_perf = len(configs) * len(perf['seeds']) * perf['repetitions'] if run_perf else 0
    n_valid = (sum(c['algorithm'] == 'trapezoid' or val['include_classical'] for c in configs) * len(val['seeds'])
               if run_valid else 0)
    print(f"configurations: {len(configs)}  samples/run: {cfg['samples']:,}\n"
          f"timed runs: {n_perf} ({len(perf['seeds'])} seeds x {perf['repetitions']} reps) on CPU {perf['cpu']}\n"
          f"validations: {n_valid} ({len(val['seeds'])} seeds, {val['workers']} workers, {val['uniform_mode']} uniforms)\n"
          f"output: {out}", flush=True)
    if args.dry_run:
        # Experiment 11 at about 4.3 GHz: about 1.15 s per timed run, about 6.7 s per validation run.
        hours = (n_perf * 1.15 + n_valid * 6.7 / val['workers']) / 3600
        print(f'rough runtime: {hours:.1f} h at Experiment 11 speed; expect up to about {hours * 1.35:.1f} h at 3.2 GHz')
        c = next(c for c in configs if c['algorithm'] == 'trapezoid')
        print('example timed command:     taskset -c', perf['cpu'], ' '.join(e11.command(cfg, binary, c, perf['seeds'][0], '<cache>')))
        print('example validation command:', ' '.join(validation_command(cfg, binary, c, val['seeds'][0], '<cache>')))
        return

    if not binary.is_file():
        sys.exit(f'benchmark binary not found: {binary}\nbuild it with: make -C c CC=gcc O2')
    if run_perf:
        check_machine(cfg)
    if out.exists() and not args.resume:
        sys.exit(f'{out} already exists; use --resume to continue it or --output-dir for a fresh run')
    out.mkdir(parents=True, exist_ok=True)
    lock = (out / '.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(f'another experiment13 process is using {out}')
    saved = out / 'config.yaml'
    if saved.exists() and saved.read_bytes() != config_path.read_bytes():
        sys.exit(f'{saved} differs from {config_path}; resume with the same config or use a new --output-dir')
    if not saved.exists():
        shutil.copy2(config_path, saved)

    session = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    env_log = e11.CsvLog(out / 'environment.csv', e11.ENV_FIELDS)
    perf_log = e11.CsvLog(out / 'performance_runs.csv', e11.PERF_FIELDS)
    valid_log = e11.CsvLog(out / 'validation_results.csv', e11.VALID_FIELDS)
    cache_root = Path(tempfile.mkdtemp(prefix='experiment13-uniforms-', dir=cfg.get('cache_dir')))
    started = time.monotonic()
    try:
        e11.log_environment(env_log, session, 'session_start', cfg, binary, config_path)
        if run_perf:
            performance(cfg, binary, configs, perf_log, env_log, session, config_path, cache_root)
            e11.summarize(dict(cfg, seeds=perf['seeds']), configs, perf_log.rows, out / 'performance_summary.csv')
            summarize_all_seeds(configs, perf_log.rows, out / 'performance_summary_all_seeds.csv')
        if run_valid:
            validate(cfg, settings, binary, configs, valid_log, perf_log.rows, cache_root)
        e11.log_environment(env_log, session, 'session_end', cfg, binary, config_path)
        env_log.write(dict(session=session, event='session_end', utc=e11.now(), key='session_elapsed_s',
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
