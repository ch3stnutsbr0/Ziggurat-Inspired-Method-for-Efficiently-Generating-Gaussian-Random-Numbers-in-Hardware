"""Experiment 22: consistency of the time per sample, Trapezoid one-block sampler against Classical.

Every run times one (variant, N, uniform mode, window, seed) on the isolated CPU with the
core-cycle counter (experiments/experiment22_bench.c) and returns a histogram. Results:
  runs.csv   one row per run: mean, variance, SD, CV and quantiles of cycles per sample
  hist.csv   histograms pooled over seeds, per configuration (value = cycles per window)

    .venv/bin/python -B experiments/experiment22.py --dry-run
    .venv/bin/python -B experiments/experiment22.py

See experiments/EXPERIMENT_22_README.md.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import csv
import json
import math
import random
import subprocess
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'experiments'))
from utils import load_config  # noqa: E402
import experiment11 as e11  # noqa: E402

C = REPO / 'c'
SOURCES = [REPO / 'experiments/experiment22_bench.c', C / 'ziggurat_basic_philox.c', C / 'ziggurat_trapezoid_philox.c']
MODE_FLAGS = {'inline': [], 'precomputed': ['-DPHILOX_PRECOMPUTED']}
QUANTILES = [0.5, 0.9, 0.99, 0.999, 0.9999, 0.999999]
FIELDS = (['config_id', 'variant', 'N', 'H', 'T', 'uniform_mode', 'window', 'seed', 'run_order', 'status',
           'windows', 'samples', 'blocks_per_sample', 'overhead_cycles', 'below_overhead', 'overflow',
           'counter_moved', 'mean', 'variance', 'sd', 'cv_percent']
          + [f'p{q * 100:g}' for q in QUANTILES] + ['max', 'started_utc', 'error'])


def stats(hist, W):
    """Per-sample units (window cycles / W) from a [value, count] histogram."""
    n = sum(c for _, c in hist)
    mean = sum(v * c for v, c in hist) / n
    var = sum((v - mean) ** 2 * c for v, c in hist) / n
    out = dict(mean=mean / W, variance=var / W ** 2, sd=math.sqrt(var) / W,
               cv_percent=100 * math.sqrt(var) / mean if mean else '')
    cum, qi = 0, 0
    for v, c in hist:
        cum += c
        while qi < len(QUANTILES) and cum >= QUANTILES[qi] * n:
            out[f'p{QUANTILES[qi] * 100:g}'] = v / W
            qi += 1
    out['max'] = hist[-1][0] / W
    return out


def check_machine(perf):
    cpu, problems = perf['cpu'], []
    if perf['require_isolation'] and cpu not in e11.cpulist(e11.read('/sys/devices/system/cpu/isolated')):
        problems.append(f'CPU {cpu} is not isolated')
    gov = e11.read(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor')
    if perf.get('require_governor') and gov != perf['require_governor']:
        problems.append(f"governor is '{gov}'")
    boost = e11.read('/sys/devices/system/cpu/cpufreq/boost')
    if perf.get('require_boost') is not None and boost != str(perf['require_boost']):
        problems.append(f"boost is '{boost}'")
    if problems:
        sys.exit('machine not ready:\n  ' + '\n  '.join(problems))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_suffix('.yaml'))
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    config_path = args.config.resolve()
    cfg = load_config(config_path)
    perf = cfg['performance']
    out = (args.output_dir or REPO / cfg['output_dir']).resolve()
    runs = [(v, n, m, w, s) for v in cfg['variants'] for n in cfg['layers'] for m in cfg['uniform_modes']
            for w in cfg['windows'] for s in perf['seeds']]
    print(f"{cfg['experiment_id']}: {len(runs)} runs on CPU {perf['cpu']}; about "
          f"{len(runs) * perf['estimated_process_s'] / 60:.0f} min\noutput: {out}", flush=True)
    if args.dry_run:
        return
    check_machine(perf)
    if out.exists():
        sys.exit(f'{out} already exists; use --output-dir')
    (out / 'bin').mkdir(parents=True)
    (out / 'config.yaml').write_bytes(config_path.read_bytes())
    builds = {}
    for mode in cfg['uniform_modes']:
        binary = out / f'bin/experiment22_bench_{mode}'
        cmd = ['gcc', '-std=c11', '-Wall', '-Wextra', '-pedantic', '-O2', '-I', str(C), *MODE_FLAGS[mode],
               *map(str, SOURCES), '-o', str(binary), '-lm']
        subprocess.run(cmd, check=True)
        builds[mode] = dict(command=' '.join(cmd), sha256=e11.sha256(binary))
    git = lambda *a: subprocess.run(['git', '-C', str(REPO), *a], capture_output=True, text=True).stdout.strip()
    state = lambda: dict(utc=e11.now(), boost=e11.read('/sys/devices/system/cpu/cpufreq/boost'),
                         isolated=e11.read('/sys/devices/system/cpu/isolated'), loadavg=e11.read('/proc/loadavg'),
                         governor=e11.read(f"/sys/devices/system/cpu/cpu{perf['cpu']}/cpufreq/scaling_governor"),
                         temperatures=[l.strip() for l in subprocess.run(['sensors'], capture_output=True, text=True)
                                       .stdout.splitlines() if l.startswith(('Tctl', 'Tdie'))])
    meta = dict(experiment_id=cfg['experiment_id'], start=state(), git_commit=git('rev-parse', 'HEAD'),
                git_dirty_files=len(git('status', '--porcelain').splitlines()), builds=builds, config=cfg)

    order = runs[:]
    random.Random(perf['shuffle_seed']).shuffle(order)
    pooled = defaultdict(lambda: defaultdict(int))
    failed, started = 0, time.monotonic()
    with open(out / 'runs.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for index, (v, n, mode, win, seed) in enumerate(order, 1):
            h, t = v.get('head', ''), v.get('tail', '')
            cid = f"{v['name']}_N{n}"
            argv = ['taskset', '-c', str(perf['cpu']), str(out / f'bin/experiment22_bench_{mode}'),
                    '--variant', v['variant'], '--layers', str(n), '--samples', str(cfg['samples'][win]),
                    '--warmup', str(cfg['warmup']), '--seed', str(seed), '--window', str(win)]
            if v['variant'] == 'trapezoid_1call':
                argv += ['--head', str(h), '--tail', str(t)]
            row = dict(config_id=cid, variant=v['variant'], N=n, H=h, T=t, uniform_mode=mode, window=win, seed=seed,
                       run_order=index, started_utc=e11.now())
            p = subprocess.run(argv, capture_output=True, text=True, timeout=600)
            lines = [l for l in p.stdout.splitlines() if l.startswith(e11.MARKER)]
            if p.returncode or len(lines) != 1:
                failed += 1
                w.writerow(dict(row, status='failed', error=(p.stderr.strip() or 'no report')[-300:]))
                print(f'[{index}/{len(order)}] {cid} {mode} W{win} seed {seed}: FAILED', flush=True)
                continue
            j = json.loads(lines[0][len(e11.MARKER):])
            hist = j['hist']
            for value, count in hist:
                pooled[(cid, v['variant'], n, h, t, mode, win)][value] += count
            row.update(status='ok', windows=j['windows'], samples=j['samples'],
                       blocks_per_sample=j['blocks_used'] / j['samples'] if mode == 'precomputed' else '',
                       overhead_cycles=j['overhead_cycles'], below_overhead=j['below_overhead'],
                       overflow=j['overflow'], counter_moved=j['counter_moved'], **stats(hist, win))
            w.writerow(row)
            f.flush()
            if index % 20 == 0 or index == len(order):
                print(f"[{index}/{len(order)}] {cid} {mode} W{win} seed {seed}: mean {row['mean']:.1f} "
                      f"sd {row['sd']:.2f} cycles/sample ({(time.monotonic() - started) / 60:.0f} min)", flush=True)
    with open(out / 'hist.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['config_id', 'variant', 'N', 'H', 'T', 'uniform_mode', 'window', 'cycles_per_window', 'count'])
        for key, hist in sorted(pooled.items(), key=lambda kv: tuple(map(str, kv[0]))):
            for value in sorted(hist):
                w.writerow([*key, value, hist[value]])
    meta.update(end=state(), elapsed_s=time.monotonic() - started, failed=failed)
    (out / 'metadata.json').write_text(json.dumps(meta, indent=2, default=str))
    print(f'\ndone in {(time.monotonic() - started) / 60:.1f} min; {failed} failed; results in {out}')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
