"""Experiment 23, part 1: exact operation counts per sample, Trapezoid one-block against Classical.

Builds experiments/experiment23_count.c with the operation counters
(-DZIGGURAT_COUNT_OPS -DPHILOX_COUNT_BLOCKS), then
  - enumerates every Trapezoid path for each (N, H, T) (trap_paths.csv), and
  - counts per-sample operation vectors over S samples per (configuration, seed) (op_vectors.csv:
    one row per distinct vector and run, with its count).
Nothing is timed; runs go on all listed CPUs in parallel.

    .venv/bin/python -B experiments/experiment23.py --dry-run
    .venv/bin/python -B experiments/experiment23.py

See experiments/EXPERIMENT_23_README.md. The energy model (part 2) is
reports/experiment23/analysis/energy_model.py.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import csv
import json
import multiprocessing as mp
import os
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'experiments'))
from utils import load_config  # noqa: E402
import experiment11 as e11  # noqa: E402

C = REPO / 'c'
SOURCES = [REPO / 'experiments/experiment23_count.c', C / 'ziggurat_basic_philox.c', C / 'ziggurat_trapezoid_philox.c']
FLAGS = ['-DZIGGURAT_COUNT_OPS', '-DPHILOX_COUNT_BLOCKS']


def _pin(queue):
    os.sched_setaffinity(0, {queue.get()})


def run(argv):
    p = subprocess.run(argv, capture_output=True, text=True)
    lines = [l for l in p.stdout.splitlines() if l.startswith(e11.MARKER)]
    if p.returncode or len(lines) != 1:
        return None, (p.stderr.strip() or 'no report')[-300:]
    return json.loads(lines[0][len(e11.MARKER):]), ''


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_suffix('.yaml'))
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    config_path = args.config.resolve()
    cfg = load_config(config_path)
    out = (args.output_dir or REPO / cfg['output_dir']).resolve()
    traps = [(n, h, t) for n in cfg['layers'] for h in cfg['heads'] for t in cfg['tails']]
    jobs = ([('classical_philox_fast', n, 0, 0, s) for n in cfg['layers'] for s in cfg['seeds']]
            + [('trapezoid_1call', n, h, t, s) for n, h, t in traps for s in cfg['seeds']])
    print(f"{cfg['experiment_id']}: {len(jobs)} counting runs of {cfg['samples']:,} samples, {len(traps)} path "
          f"enumerations; {cfg['workers']} workers on CPUs {cfg['cpus']}\noutput: {out}", flush=True)
    if args.dry_run:
        return
    if out.exists():
        sys.exit(f'{out} already exists; use --output-dir')
    (out / 'bin').mkdir(parents=True)
    (out / 'config.yaml').write_bytes(config_path.read_bytes())
    binary = out / 'bin/experiment23_count'
    build = ['gcc', '-std=c11', '-Wall', '-Wextra', '-pedantic', '-O2', '-I', str(C), *FLAGS, *map(str, SOURCES),
             '-o', str(binary), '-lm']
    subprocess.run(build, check=True)
    git = lambda *a: subprocess.run(['git', '-C', str(REPO), *a], capture_output=True, text=True).stdout.strip()
    meta = dict(experiment_id=cfg['experiment_id'], started_utc=e11.now(), build_command=' '.join(build),
                binary_sha256=e11.sha256(binary), git_commit=git('rev-parse', 'HEAD'),
                git_dirty_files=len(git('status', '--porcelain').splitlines()), config=cfg)
    started = time.monotonic()

    # structural support of the Trapezoid: every path once
    fields = None
    with open(out / 'trap_paths.csv', 'w', newline='') as f:
        w = None
        for n, h, t in traps:
            j, err = run([str(binary), 'enumerate', '--layers', str(n), '--head', str(h), '--tail', str(t)])
            if j is None:
                sys.exit(f'enumerate N={n} H={h} T={t} failed: {err}')
            fields = j['fields']
            if w is None:
                w = csv.writer(f)
                w.writerow(['N', 'H', 'T', 'decision_bits', 'path_side', 'path_depth', 'path_wedge', *fields])
            for p in j['paths']:
                w.writerow([n, h, t, j['decision_bits'], p['side'], p['depth'], p['wedge'], *p['vector']])
    print(f'[enumerate] {len(traps)} configurations', flush=True)

    queue = mp.Manager().Queue()
    for cpu in cfg['cpus'][:cfg['workers']]:
        queue.put(cpu)
    failed = 0
    with open(out / 'op_vectors.csv', 'w', newline='') as f, \
            ProcessPoolExecutor(max_workers=cfg['workers'], initializer=_pin, initargs=(queue,)) as pool:
        w = csv.writer(f)
        w.writerow(['config_id', 'variant', 'N', 'H', 'T', 'seed', 'samples', 'count', *fields])
        futures = {}
        for v, n, h, t, s in jobs:
            argv = [str(binary), 'count', '--variant', v, '--layers', str(n), '--samples', str(cfg['samples']),
                    '--seed', str(s)]
            if v == 'trapezoid_1call':
                argv += ['--head', str(h), '--tail', str(t)]
            futures[pool.submit(run, argv)] = (v, n, h, t, s)
        for count, fut in enumerate(as_completed(futures), 1):
            v, n, h, t, s = futures[fut]
            j, err = fut.result()
            cid = f'classical_N{n}' if v == 'classical_philox_fast' else f'trap1_N{n}_H{h}_T{t}'
            if j is None:
                failed += 1
                print(f'[{count}/{len(jobs)}] {cid} seed {s}: FAILED {err}', flush=True)
                continue
            if sum(x['count'] for x in j['vectors']) != cfg['samples']:
                sys.exit(f'{cid} seed {s}: vector counts do not add up to the sample count')
            for x in j['vectors']:
                w.writerow([cid, v, n, h if v == 'trapezoid_1call' else '', t if v == 'trapezoid_1call' else '', s,
                            cfg['samples'], x['count'], *x['vector']])
            f.flush()
            if count % 25 == 0 or count == len(jobs):
                print(f'[{count}/{len(jobs)}] {cid} seed {s}: {len(j["vectors"])} distinct vectors '
                      f'({(time.monotonic() - started) / 60:.0f} min)', flush=True)
    meta.update(finished_utc=e11.now(), elapsed_s=time.monotonic() - started, failed=failed)
    (out / 'metadata.json').write_text(json.dumps(meta, indent=2, default=str))
    print(f'\ndone in {(time.monotonic() - started) / 60:.1f} min; {failed} failed; results in {out}')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
