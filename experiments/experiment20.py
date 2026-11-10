"""Experiment 20: Trapezoid one-block sampler (zt_gaussian_philox_1call) over the full H/T grid.

Phase 1 (validation): full-data goodness of fit (chi-square, KS, CvM, AD against fixed N(0,1)),
5 seeds, all cores. Classical is not validated (its rejection step makes it exact). Samples go
through a pipe into RAM and are discarded; results are CSV only. The test, logging and pipe code
is that of experiment11.py, unchanged.

    .venv/bin/python -B experiments/experiment20.py --dry-run
    .venv/bin/python -B experiments/experiment20.py --phase validation
    .venv/bin/python -B experiments/experiment20.py --phase validation --resume

See experiments/EXPERIMENT_20_README.md.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import csv
import fcntl
import json
import math
import multiprocessing as mp
import os
import shutil
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'experiments'))
from utils import load_config, validation_settings  # noqa: E402
import experiment11 as e11  # noqa: E402

C = REPO / 'c'
CFLAGS = ['gcc', '-std=c11', '-Wall', '-Wextra', '-pedantic', '-O2', '-I', str(C)]
BENCH_SOURCES = [REPO / 'experiments/experiment20_bench.c', C / 'ziggurat_basic_xoshiro256plus.c', C / 'xoshiro256plus.c',
                 C / 'ziggurat_basic_philox.c', C / 'ziggurat_trapezoid_philox.c']
TESTS_C = {'test_philox2x64': [C / 'tests/test_philox2x64.c'],
           'test_trapezoid_philox_1call': [C / 'tests/test_trapezoid_philox_1call.c', C / 'ziggurat_trapezoid_philox.c']}
VALID_FIELDS = e11.VALID_FIELDS[:7] + ['decision_bits'] + e11.VALID_FIELDS[7:]


def build(bindir):
    """Stream binary with block counting (calls per sample are recorded), and the C test programs."""
    bindir.mkdir(parents=True, exist_ok=True)
    cmds = {'stream': CFLAGS + ['-DPHILOX_COUNT_BLOCKS', '-DZT_TEST_PRNG_STEPS', *map(str, BENCH_SOURCES),
                                '-o', str(bindir / 'experiment20_stream'), '-lm']}
    for name, src in TESTS_C.items():
        cmds[name] = CFLAGS + [*map(str, src), '-o', str(bindir / name), '-lm']
    for cmd in cmds.values():
        subprocess.run(cmd, check=True)
    tests = {}
    for name in TESTS_C:
        p = subprocess.run([str(bindir / name)], capture_output=True, text=True)
        tests[name] = dict(returncode=p.returncode, tail=p.stdout.strip().splitlines()[-1:])
        if p.returncode:
            sys.exit(f'{name} failed:\n{p.stdout}{p.stderr}')
        print(f'[check] {name}: {tests[name]["tail"][0] if tests[name]["tail"] else "ok"}', flush=True)
    return {k: ' '.join(v) for k, v in cmds.items()}, tests


def configurations(cfg):
    return [dict(config_id=f'trap1_N{n}_H{h}_T{t}', algorithm='trapezoid_1call', N=n, H=h, T=t)
            for n in cfg['layers'] for h in cfg['heads'] for t in cfg['tails']]


def stream_command(binary, c, seed, samples):
    return [str(binary), 'stream', '--variant', 'trapezoid_1call', '--layers', str(c['N']), '--head', str(c['H']),
            '--tail', str(c['T']), '--samples', str(samples), '--seed', str(seed)]


_CPU_QUEUE = None


def _pin_worker(queue):
    os.sched_setaffinity(0, {queue.get()})          # the stream process inherits this affinity


def pipeline_check(cfg, settings):
    """Rerun one Experiment 13 row through the same code: identical digest and p-values required."""
    pc = cfg['validation']['pipeline_check']
    ref = next(r for r in csv.DictReader(open(REPO / pc['reference']))
               if r['config_id'] == pc['config_id'] and r['seed'] == str(pc['seed']) and r['status'] == 'ok')
    argv = [str(REPO / pc['binary']), '--algorithm', 'trapezoid', '--layers', str(pc['N']), '--seed', str(pc['seed']),
            '--prng', 'xoshiro256plus', '--uniform-mode', 'inline', '--samples', str(cfg['samples']), '--warmup', '0',
            '--report-json', '--head', str(pc['H']), '--tail', str(pc['T'])]
    out = e11.validate_one(argv, cfg['samples'], settings)
    if out['status'] != 'ok':
        sys.exit(f"pipeline check failed to run: {out['error']}")
    same = out['digest'] == ref['stream_sha256']
    for test, label in e11.TESTS.items():
        p = out['result']['tests'][test]['p_value']
        same &= math.isclose(p, float(ref[f'{label}_p_value']), rel_tol=1e-9, abs_tol=1e-12)
    print(f"[check] pipeline vs Experiment 13 {pc['config_id']} seed {pc['seed']}: "
          f"{'identical digest and p-values' if same else 'MISMATCH'}", flush=True)
    if not same:
        sys.exit('pipeline check: stream digest or p-values differ from Experiment 13')
    return dict(config_id=pc['config_id'], seed=pc['seed'], stream_sha256=out['digest'], identical=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_suffix('.yaml'))
    parser.add_argument('--phase', choices=['validation'], default='validation')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    config_path = args.config.resolve()
    cfg = load_config(config_path)
    val = cfg['validation']
    settings = validation_settings({'validation': {k: val[k] for k in ('significance_level', 'chi_square')}})
    out = (args.output_dir or REPO / cfg['output_dir']).resolve()
    vdir = out / 'validation'
    configs = configurations(cfg)
    jobs_all = [(c, s) for c in configs for s in val['seeds']]
    print(f"validation: {len(configs)} configurations x {len(val['seeds'])} seeds = {len(jobs_all)} runs of "
          f"{cfg['samples']:,} samples; {val['workers']} workers on CPUs {val['cpus']}\noutput: {vdir}", flush=True)
    if args.dry_run:
        print('example:', ' '.join(stream_command(vdir / 'bin/experiment20_stream', configs[0], 1, cfg['samples'])))
        print(f"rough runtime: {len(jobs_all) * 8 / val['workers'] / 60:.0f} min")
        return
    if vdir.exists() and not args.resume:
        sys.exit(f'{vdir} already exists; use --resume or --output-dir')
    vdir.mkdir(parents=True, exist_ok=True)
    lock = (vdir / '.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(f'another process is using {vdir}')
    saved = vdir / 'config.yaml'
    if saved.exists() and saved.read_bytes() != config_path.read_bytes():
        sys.exit(f'{saved} differs from {config_path}; resume with the same config')
    shutil.copy2(config_path, saved)

    started = time.monotonic()
    commands, ctests = build(vdir / 'bin')
    binary = vdir / 'bin/experiment20_stream'
    check = pipeline_check(cfg, settings)
    env = {k: e11.read(p) for k, p in dict(
        boost='/sys/devices/system/cpu/cpufreq/boost', isolated='/sys/devices/system/cpu/isolated',
        governor_cpu0='/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor',
        scaling_max_khz='/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq', loadavg='/proc/loadavg',
        kernel_cmdline='/proc/cmdline').items()}
    git = lambda *a: subprocess.run(['git', '-C', str(REPO), *a], capture_output=True, text=True).stdout.strip()
    meta = dict(experiment_id='experiment20', phase='validation', started_utc=e11.now(), machine=env,
                git_commit=git('rev-parse', 'HEAD'), git_dirty_files=len(git('status', '--porcelain').splitlines()),
                build_commands=commands, c_tests=ctests, pipeline_check=check,
                stream_binary_sha256=e11.sha256(binary), config=cfg)

    log = e11.CsvLog(vdir / 'validation_raw.csv', VALID_FIELDS)
    done = {(r['config_id'], r['seed']) for r in log.rows if r['status'] == 'ok'}
    jobs = [(c, s) for c, s in jobs_all if (c['config_id'], str(s)) not in done]
    print(f'[valid] {len(jobs)} to run, {len(done)} already done', flush=True)
    queue = mp.Manager().Queue()
    for cpu in val['cpus'][:val['workers']]:
        queue.put(cpu)
    failed = 0
    try:
        with ProcessPoolExecutor(max_workers=val['workers'], initializer=_pin_worker, initargs=(queue,)) as pool:
            futures = {pool.submit(e11.validate_one, stream_command(binary, c, s, cfg['samples']), cfg['samples'],
                                   settings): (c, s) for c, s in jobs}
            for count, fut in enumerate(as_completed(futures), 1):
                c, seed = futures[fut]
                outcome = fut.result()
                row = e11.validation_row(c, seed, cfg, settings, outcome, {})
                if outcome['status'] == 'ok':
                    row['decision_bits'] = outcome['report']['decision_bits']
                    if outcome['report']['uniforms_per_sample'] != 1:
                        row.update(status='failed', error=f"calls per sample {outcome['report']['uniforms_per_sample']} != 1")
                failed += row['status'] != 'ok'
                log.write(row)
                verdict = (' '.join(f"{l}={'REJ' if row[f'{l}_reject'] else 'ok'}" for l in e11.TESTS.values())
                           if row['status'] == 'ok' else 'FAILED: ' + row['error'])
                print(f"[valid {count}/{len(jobs)}] {c['config_id']} seed {seed}: {verdict}", flush=True)
    finally:
        log.close()
        meta.update(finished_utc=e11.now(), elapsed_s=time.monotonic() - started,
                    machine_end={'boost': e11.read('/sys/devices/system/cpu/cpufreq/boost'),
                                 'loadavg': e11.read('/proc/loadavg')})
        (vdir / 'metadata.json').write_text(json.dumps(meta, indent=2, default=str))
    print(f'\ndone in {time.monotonic() - started:.0f} s; {failed} failed; results in {vdir}')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
