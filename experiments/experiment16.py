"""Experiment 16: inline-PRNG throughput, Classical vs Trapezoid, xoshiro256+ vs bit-packed Philox2x64-10.

Casual timing (no CPU isolation). Builds experiments/experiment16_bench.c twice (timed and counted),
runs every variant at every N, and writes raw timings, PRNG calls per sample and a summary.

    .venv/bin/python -B experiments/experiment16.py [--config FILE] [--output-dir DIR]
"""
import sys
sys.dont_write_bytecode = True
import argparse
import csv
import io
import json
import platform
import statistics
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'experiments'))
from utils import load_config  # noqa: E402

SOURCES = ['ziggurat_basic_xoshiro256plus.c', 'ziggurat_trapezoid_xoshiro256plus.c', 'xoshiro256plus.c',
           'ziggurat_basic_philox.c', 'ziggurat_trapezoid_philox.c',
           'ziggurat_trapezoid_philox_2call.c']
FLAGS = ['gcc', '-std=c11', '-Wall', '-Wextra', '-pedantic', '-O2', '-I', str(REPO / 'c')]


def build(work):
    out = {}
    for name, extra in (('time', []), ('count', ['-DZT_TEST_PRNG_STEPS', '-DPHILOX_COUNT_BLOCKS'])):
        exe = work / f'bench_{name}'
        cmd = FLAGS + extra + [str(REPO / 'experiments/experiment16_bench.c'),
                               *[str(REPO / 'c' / s) for s in SOURCES], '-o', str(exe), '-lm']
        done = subprocess.run(cmd, capture_output=True, text=True)
        if done.returncode or done.stderr:
            raise RuntimeError(done.stderr)
        out[name] = (exe, cmd)
    kat = work / 'kat'
    subprocess.run(FLAGS + [str(REPO / 'c/tests/test_philox2x64.c'), '-o', str(kat)], check=True)
    print(subprocess.run([str(kat)], capture_output=True, text=True, check=True).stdout.strip())
    return out


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_suffix('.yaml'))
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    cfg = load_config(args.config)
    if cfg.get('experiment_id') != 'experiment16':
        raise ValueError('experiment_id must be experiment16')
    out = (args.output_dir or REPO / cfg['output_dir']).resolve()
    if out.exists():
        sys.exit(f'{out} already exists; use --output-dir for a fresh run')
    pin = ['taskset', '-c', str(cfg['cpu'])] if cfg.get('cpu') is not None else []
    H, T, seed = cfg['head'], cfg['tail'], cfg['seed']
    out.mkdir(parents=True)
    raw, counts = [], []
    with tempfile.TemporaryDirectory(prefix='experiment16-') as tmp:
        exes = build(Path(tmp))
        for N in cfg['layers']:
            for v in cfg['variants']:
                line = subprocess.run([str(exes['count'][0]), 'count', v, str(N), str(H), str(T),
                                       str(cfg['count_samples']), str(seed)], capture_output=True, text=True, check=True).stdout
                counts += list(csv.DictReader(io.StringIO(line), fieldnames=[
                    'variant', 'N', 'H', 'T', 'samples', 'prng_calls_per_sample', 'prng_bits_per_sample',
                    'mean', 'second_moment', 'fourth_moment']))
            for r in range(cfg['repeats']):
                for v in cfg['variants']:
                    line = subprocess.run(pin + [str(exes['time'][0]), 'time', v, str(N), str(H), str(T),
                                                 str(cfg['samples']), '1', str(seed)],
                                          capture_output=True, text=True, check=True).stdout
                    row = dict(zip(['variant', 'N', 'H', 'T', 'rep', 'samples', 'seconds', 'msamples_per_s'],
                                   line.strip().split(',')))
                    row['rep'] = r
                    raw.append(row)
            med = {v: statistics.median(float(x['msamples_per_s']) for x in raw if x['variant'] == v and int(x['N']) == N)
                   for v in cfg['variants']}
            print(f'N={N}: ' + '  '.join(f'{v} {m:.1f}' for v, m in med.items()) + '  (Msamples/s, median)', flush=True)
        build_cmds = {k: v[1] for k, v in exes.items()}

    summary = []
    for N in cfg['layers']:
        med = {}
        for v in cfg['variants']:
            xs = [float(x['msamples_per_s']) for x in raw if x['variant'] == v and int(x['N']) == N]
            c = next(x for x in counts if x['variant'] == v and int(x['N']) == N)
            med[v] = statistics.median(xs)
            summary.append(dict(variant=v, N=N, H=H, T=T, median_msamples_per_s=med[v],
                                min_msamples_per_s=min(xs), max_msamples_per_s=max(xs),
                                ns_per_sample=1e3 / med[v], prng_calls_per_sample=float(c['prng_calls_per_sample']),
                                prng_bits_per_sample=float(c['prng_bits_per_sample'])))
        for s in summary[-len(cfg['variants']):]:
            prng = s['variant'].split('_')[1]          # trapezoid_philox_2call -> philox
            s['speedup_vs_classical_same_prng'] = s['median_msamples_per_s'] / med[f'classical_{prng}']
            s['speedup_vs_classical_xoshiro'] = s['median_msamples_per_s'] / med['classical_xoshiro']

    def write(name, data):
        with (out / name).open('x', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(data[0]))
            w.writeheader(); w.writerows(data)

    write('timing_raw.csv', raw)
    write('prng_counts.csv', counts)
    write('summary.csv', summary)
    git = lambda *a: subprocess.run(['git', '-C', str(REPO), *a], capture_output=True, text=True).stdout.strip()
    (out / 'metadata.json').write_text(json.dumps(dict(
        experiment_id='experiment16', created_utc=datetime.now(timezone.utc).isoformat(), config=cfg,
        build_commands=build_cmds, pinning=pin, cpu_boost=read('/sys/devices/system/cpu/cpufreq/boost'),
        governor=read(f'/sys/devices/system/cpu/cpu{cfg.get("cpu") or 0}/cpufreq/scaling_governor'),
        cpu=next((l.split(':', 1)[1].strip() for l in open('/proc/cpuinfo') if l.startswith('model name')), None),
        git_commit=git('rev-parse', 'HEAD'), git_dirty_files=len(git('status', '--porcelain').splitlines()),
        gcc=subprocess.run(['gcc', '--version'], capture_output=True, text=True).stdout.splitlines()[0],
        python=platform.python_version(), isolation='none (casual run)'), indent=2))
    print(f'results in {out}')


if __name__ == '__main__':
    main()
