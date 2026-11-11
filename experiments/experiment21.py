"""Experiment 21: timing of the one-block Trapezoid sampler against Classical.

21a: the PRNG runs inline, inside the timed loop.
21b: the PRNG outputs are generated into a buffer before timing (same stream); the timed loop
     only reads them, so the timing isolates the sampler's own work.
Both use the same harness source (experiments/experiment21_bench.c) and the same grid, seeds and
repetitions; the config's uniform_mode selects the build. Every timed process is pinned to the
isolated CPU; the script refuses to start unless isolation, boost and governor are as configured.
Results are CSV only.

    .venv/bin/python -B experiments/experiment21.py --config experiments/experiment21a.yaml --dry-run
    .venv/bin/python -B experiments/experiment21.py --config experiments/experiment21a.yaml
    .venv/bin/python -B experiments/experiment21.py --config experiments/experiment21a.yaml --resume

See experiments/EXPERIMENT_21_README.md.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import fcntl
import json
import random
import shutil
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'experiments'))
from utils import load_config  # noqa: E402
import experiment11 as e11  # noqa: E402

C = REPO / 'c'
SOURCES = [REPO / 'experiments/experiment21_bench.c', C / 'ziggurat_basic_xoshiro256plus.c', C / 'xoshiro256plus.c',
           C / 'ziggurat_basic_philox.c', C / 'ziggurat_trapezoid_philox.c']
MODE_FLAGS = {'inline': [], 'precomputed': ['-DPHILOX_PRECOMPUTED', '-DXOSHIRO_PRECOMPUTED']}
FIELDS = ['experiment', 'uniform_mode', 'config_id', 'variant', 'N', 'H', 'T', 'seed', 'repetition', 'process',
          'run_order', 'status', 'returncode', 'samples', 'warmup', 'decision_bits', 'sampling_time_s',
          'throughput_msamples_per_s', 'time_per_sample_ns', 'uniforms_per_sample', 'buffer_utilization',
          'buffer_fill_s', 'checksum', 'mean', 'variance', 'process_wall_s', 'cpu', 'cpu_khz_before',
          'started_utc', 'error']


def configurations(cfg):
    out = []
    for n in cfg['layers']:
        for v in cfg['classical_variants']:
            out.append(dict(config_id=f'{v}_N{n}', variant=v, N=n, H='', T=''))
        for h in cfg['heads']:
            for t in cfg['tails']:
                out.append(dict(config_id=f'trap1_N{n}_H{h}_T{t}', variant='trapezoid_1call', N=n, H=h, T=t))
    return out


def check_machine(cfg):
    perf, problems = cfg['performance'], []
    cpu = perf['cpu']
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
        sys.exit('machine not ready for timing:\n  ' + '\n  '.join(problems) + '\nSee EXPERIMENT_21_README.md.')


def machine_state(cpu):
    sensors = subprocess.run(['sensors'], capture_output=True, text=True).stdout
    temps = {l.split(':')[0].strip(): l.split(':')[1].split()[0] for l in sensors.splitlines()
             if l.startswith(('Tctl', 'Tdie'))}
    return dict(utc=e11.now(), boost=e11.read('/sys/devices/system/cpu/cpufreq/boost'),
                governor=e11.read(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor'),
                scaling_max_khz=e11.read(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_max_freq'),
                isolated=e11.read('/sys/devices/system/cpu/isolated'), loadavg=e11.read('/proc/loadavg'),
                kernel_cmdline=e11.read('/proc/cmdline'), temperatures=temps)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    config_path = args.config.resolve()
    cfg = load_config(config_path)
    perf, mode = cfg['performance'], cfg['uniform_mode']
    out = (args.output_dir or REPO / cfg['output_dir']).resolve()
    configs = configurations(cfg)
    reps, per_proc = perf['repetitions'], perf['repetitions_per_process']
    if reps % per_proc:
        sys.exit('repetitions must be a multiple of repetitions_per_process')
    procs = [(c, s, p) for c in configs for s in perf['seeds'] for p in range(reps // per_proc)]
    est = len(procs) * (perf['estimated_process_s'])
    print(f"{cfg['experiment_id']} ({mode}): {len(configs)} configurations x {len(perf['seeds'])} seeds x {reps} "
          f"repetitions = {len(configs) * len(perf['seeds']) * reps} timings in {len(procs)} processes "
          f"({per_proc} per process) on CPU {perf['cpu']}; about {est / 3600:.1f} h\noutput: {out}", flush=True)
    if args.dry_run:
        return
    check_machine(cfg)
    if out.exists() and not args.resume:
        sys.exit(f'{out} already exists; use --resume or --output-dir')
    out.mkdir(parents=True, exist_ok=True)
    lock = (out / '.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(f'another process is using {out}')
    saved = out / 'config.yaml'
    if saved.exists() and saved.read_bytes() != config_path.read_bytes():
        sys.exit(f'{saved} differs from {config_path}; resume with the same config')
    shutil.copy2(config_path, saved)

    # build once per output directory (a resumed run reuses the same binary)
    binary = out / 'bin/experiment21_bench'
    build = ['gcc', '-std=c11', '-Wall', '-Wextra', '-pedantic', '-O2', '-I', str(C), *MODE_FLAGS[mode],
             *map(str, SOURCES), '-o', str(binary), '-lm']
    if not binary.exists():
        binary.parent.mkdir(exist_ok=True)
        subprocess.run(build, check=True)
    meta_path = out / 'metadata.json'
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    git = lambda *a: subprocess.run(['git', '-C', str(REPO), *a], capture_output=True, text=True).stdout.strip()
    meta.setdefault('sessions', []).append(dict(start=machine_state(perf['cpu']), git_commit=git('rev-parse', 'HEAD'),
                                                git_dirty_files=len(git('status', '--porcelain').splitlines())))
    meta.update(experiment_id=cfg['experiment_id'], uniform_mode=mode, build_command=' '.join(build),
                binary_sha256=e11.sha256(binary), config=cfg)
    meta_path.write_text(json.dumps(meta, indent=2, default=str))

    log = e11.CsvLog(out / 'timing_raw.csv', FIELDS)
    done = {(r['config_id'], r['seed'], r['process']) for r in log.rows if r['status'] == 'ok'}
    order = procs[:]
    random.Random(perf['shuffle_seed']).shuffle(order)
    cpu, started, failed = perf['cpu'], time.monotonic(), 0
    try:
        for index, (c, seed, p) in enumerate(order, 1):
            if (c['config_id'], str(seed), str(p + 1)) in done:
                continue
            argv = ['taskset', '-c', str(cpu), str(binary), '--variant', c['variant'], '--layers', str(c['N']),
                    '--samples', str(cfg['samples']), '--warmup', str(cfg['warmup']), '--seed', str(seed),
                    '--repeats', str(per_proc)]
            if c['variant'] == 'trapezoid_1call':
                argv += ['--head', str(c['H']), '--tail', str(c['T'])]
            base = dict(c, experiment=cfg['experiment_id'], uniform_mode=mode, seed=seed, process=p + 1,
                        run_order=index, samples=cfg['samples'], warmup=cfg['warmup'], cpu=cpu,
                        cpu_khz_before=e11.read(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_cur_freq'),
                        started_utc=e11.now())
            t0 = time.monotonic()
            try:
                proc = subprocess.run(argv, capture_output=True, text=True, timeout=600)
                rc, stdout, err = proc.returncode, proc.stdout, proc.stderr
            except subprocess.TimeoutExpired:
                rc, stdout, err = 'timeout', '', 'timeout after 600 s'
            wall = time.monotonic() - t0
            reports = [json.loads(l[len(e11.MARKER):]) for l in stdout.splitlines() if l.startswith(e11.MARKER)]
            if rc != 0 or len(reports) != per_proc:
                failed += 1
                log.write(dict(base, repetition=p * per_proc + 1, status='failed', returncode=rc, process_wall_s=wall,
                               error=err.strip()[-300:] or f'{len(reports)} of {per_proc} reports'))
                print(f"[{index}/{len(order)}] {c['config_id']} seed {seed}: FAILED", flush=True)
                continue
            for j in reports:
                log.write(dict(base, repetition=p * per_proc + j['repeat'], status='ok', returncode=rc,
                               decision_bits=j['decision_bits'], sampling_time_s=j['sampling_time_seconds'],
                               throughput_msamples_per_s=j['throughput_million_samples_per_second'],
                               time_per_sample_ns=j['time_per_sample_ns'], uniforms_per_sample=j['uniforms_per_sample'],
                               buffer_utilization=j['buffer_utilization'], buffer_fill_s=j['buffer_fill_seconds'],
                               checksum=repr(j['checksum']), mean=j['mean'], variance=j['variance'],
                               process_wall_s=wall))
            speeds = ' '.join(f"{j['throughput_million_samples_per_second']:.1f}" for j in reports)
            if index % 20 == 0 or index == len(order):
                elapsed = time.monotonic() - started
                print(f"[{index}/{len(order)}] {c['config_id']} seed {seed}: {speeds} Msamples/s  "
                      f"({elapsed / 60:.0f} min elapsed)", flush=True)
    finally:
        log.close()
        meta['sessions'][-1].update(end=machine_state(cpu), elapsed_s=time.monotonic() - started, failed=failed)
        meta_path.write_text(json.dumps(meta, indent=2, default=str))
    print(f'\ndone in {(time.monotonic() - started) / 3600:.2f} h; {failed} failed; results in {out}')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
