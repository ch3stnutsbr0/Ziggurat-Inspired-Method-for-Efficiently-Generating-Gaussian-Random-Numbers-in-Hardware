"""Experiment 21 joint analysis: 21a (PRNG inline) and 21b (PRNG precomputed), analysed together.

For every configuration: median throughput over all timings, IQR, ns and cycles per sample (CPU 7
fixed at 3.2 GHz). Speed-ups are paired by seed: for each seed, median Trapezoid timing / median
Classical timing at the same N; reported as the median over seeds with a 95% bootstrap interval
over seeds. Run-to-run noise is split into a between-seed part and a within-seed (repetition) part.

    .venv/bin/python -B reports/experiment21/analysis/analyze_experiment21.py [--a DIR --b DIR --out DIR]
"""
import sys
sys.dont_write_bytecode = True
import argparse
import csv
import statistics as st
from collections import defaultdict
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap

REPO = Path(__file__).resolve().parents[3]
GHZ = 3.2
LAYERS = [8, 16, 32, 64, 128, 256]
CLASSICAL = ['classical_philox_fast', 'classical_xoshiro']
# diverging blue (Trapezoid faster) <-> red (Classical faster), neutral gray midpoint
DIV_EDGES = [0.0, 0.8, 0.9, 0.97, 1.03, 1.1, 1.25, 99]
DIV_COLORS = ['#b02f2f', '#e66767', '#f4b9b8', '#f0efec', '#9ec5f4', '#5598e7', '#1c5cab']
SERIES = {'trap1_H1_T2': ('#2a78d6', 'Trapezoid one-call, H1/T2'),
          'classical_philox_fast': ('#eb6834', 'Classical, Philox (fast path)'),
          'classical_xoshiro': ('#1baf7a', 'Classical, xoshiro256+')}
INK, INK2, GRID = '#0b0b0b', '#52514e', '#e4e3df'


def load(path):
    return [r for r in csv.DictReader(open(path / 'timing_raw.csv')) if r['status'] == 'ok']


def summarize(rows):
    by = defaultdict(list)
    seed_runs = defaultdict(list)
    for r in rows:
        by[r['config_id']].append(float(r['throughput_msamples_per_s']))
        seed_runs[(r['config_id'], r['seed'])].append(float(r['throughput_msamples_per_s']))
    seed_med = {k: st.median(v) for k, v in seed_runs.items()}
    return by, seed_runs, seed_med


def bootstrap_ci(values, rng, reps=4000):
    a = np.asarray(values)
    meds = np.median(a[rng.integers(0, len(a), (reps, len(a)))], axis=1)
    return float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5))


def info(config_id):
    p = config_id.split('_')
    if config_id.startswith('trap1'):
        return int(p[1][1:]), int(p[2][1:]), int(p[3][1:])
    return int(p[-1][1:]), '', ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--a', type=Path, default=REPO / 'experiments/results/experiment21a')
    ap.add_argument('--b', type=Path, default=REPO / 'experiments/results/experiment21b')
    ap.add_argument('--out', type=Path, default=REPO / 'reports/experiment21')
    args = ap.parse_args()
    rng = np.random.default_rng(2026)
    (args.out / 'tables').mkdir(parents=True, exist_ok=True)
    (args.out / 'figures').mkdir(parents=True, exist_ok=True)

    tput, speed, noise, checks = [], [], [], []
    data = {}
    for exp, path in (('21a', args.a), ('21b', args.b)):
        if not (path / 'timing_raw.csv').exists():
            print(f'{exp}: no data at {path}')
            continue
        rows = load(path)
        by, seed_runs, seed_med = summarize(rows)
        data[exp] = (by, seed_med)
        seeds = sorted({r['seed'] for r in rows}, key=int)
        sums = defaultdict(set)
        for r in rows:
            sums[(r['config_id'], r['seed'])].add(r['checksum'])
        checks.append(dict(experiment=exp, timings=len(rows), configurations=len(by), seeds=len(seeds),
                           checksum_identical_within_seed=all(len(s) == 1 for s in sums.values())))
        for cid, v in sorted(by.items()):
            N, H, T = info(cid)
            q1, q3 = np.percentile(v, [25, 75])
            med = st.median(v)
            uni = [float(r['uniforms_per_sample']) for r in rows if r['config_id'] == cid and float(r['uniforms_per_sample']) >= 0]
            tput.append(dict(experiment=exp, config_id=cid, N=N, H=H, T=T, timings=len(v), median_msamples_per_s=med,
                             q1=q1, q3=q3, iqr_percent=100 * (q3 - q1) / med, ns_per_sample=1e3 / med,
                             cycles_per_sample=GHZ * 1e3 / med,
                             uniforms_per_sample=st.mean(uni) if uni else ''))
            # noise split: SD of seed medians vs pooled within-seed SD (percent of the median)
            meds = [seed_med[(cid, s)] for s in seeds if (cid, s) in seed_med]
            within = [st.pstdev(seed_runs[(cid, s)]) for s in seeds if len(seed_runs.get((cid, s), [])) > 1]
            noise.append(dict(experiment=exp, config_id=cid, N=N, H=H, T=T,
                              between_seed_sd_percent=100 * st.stdev(meds) / med if len(meds) > 1 else '',
                              within_seed_sd_percent=100 * st.mean(within) / med if within else ''))
        for cid in by:
            if not cid.startswith('trap1'):
                continue
            N, H, T = info(cid)
            row = dict(experiment=exp, config_id=cid, N=N, H=H, T=T)
            for cl in CLASSICAL:
                ref = f'{cl}_N{N}'
                ratios = [seed_med[(cid, s)] / seed_med[(ref, s)] for s in seeds
                          if (cid, s) in seed_med and (ref, s) in seed_med]
                if ratios:
                    lo, hi = bootstrap_ci(ratios, rng)
                    row.update({f'speedup_vs_{cl}': st.median(ratios), f'speedup_vs_{cl}_ci_low': lo,
                                f'speedup_vs_{cl}_ci_high': hi, f'speedup_vs_{cl}_seeds': len(ratios)})
            speed.append(row)

    def write(name, rows):
        if rows:
            fields = list(dict.fromkeys(k for r in rows for k in r))
            with open(args.out / 'tables' / name, 'w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    write('throughput_by_config.csv', tput)
    write('speedup_by_config.csv', speed)
    write('noise_by_config.csv', noise)
    write('integrity.csv', checks)

    # speed-up grids (Trapezoid / Classical Philox fast), one figure per experiment
    sp = {(r['experiment'], r['N'], r['H'], r['T']): r for r in speed}
    for exp in data:
        fig, axes = plt.subplots(2, 3, figsize=(11, 7.6), constrained_layout=True)
        cmap, norm = ListedColormap(DIV_COLORS), BoundaryNorm(DIV_EDGES, len(DIV_COLORS))
        for ax, N in zip(axes.flat, LAYERS):
            m = [[sp[(exp, N, h, t)].get('speedup_vs_classical_philox_fast', np.nan) if (exp, N, h, t) in sp else np.nan
                  for t in range(5)] for h in range(5)]
            im = ax.imshow(m, cmap=cmap, norm=norm)
            for h in range(5):
                for t in range(5):
                    if not np.isnan(m[h][t]):
                        dark = m[h][t] >= 1.1 or m[h][t] < 0.9
                        ax.text(t, h, f'{m[h][t]:.2f}', ha='center', va='center', fontsize=10,
                                color='#ffffff' if dark else INK)
            ax.set_xticks(range(5), [f'T{t}' for t in range(5)])
            ax.set_yticks(range(5), [f'H{h}' for h in range(5)])
            ax.set_xticks([x - 0.5 for x in range(1, 5)], minor=True)
            ax.set_yticks([y - 0.5 for y in range(1, 5)], minor=True)
            ax.grid(which='minor', color='#fcfcfb', linewidth=2)
            ax.tick_params(which='both', length=0, labelsize=9, colors=INK2)
            for s in ax.spines.values():
                s.set_visible(False)
            ax.set_title(f'N = {N}', fontsize=12, color=INK)
        cb = fig.colorbar(im, ax=axes, ticks=DIV_EDGES[1:-1], shrink=0.7, pad=0.02)
        cb.set_label('Trapezoid / Classical (Philox, fast path); > 1: Trapezoid faster', color=INK2)
        cb.outline.set_visible(False)
        mode = 'PRNG inline' if exp == '21a' else 'PRNG precomputed'
        fig.suptitle(f'Experiment {exp} ({mode}): speed-up, median over seeds of paired ratios', fontsize=13, color=INK)
        fig.savefig(args.out / f'figures/speedup_grid_{exp}.png', dpi=160)
        fig.savefig(args.out / f'figures/speedup_grid_{exp}.svg')
        plt.close(fig)

    # throughput against N: one panel per experiment (own axis each), three series
    tp = {(r['experiment'], r['config_id']): r for r in tput}
    if data:
        fig, axes = plt.subplots(1, len(data), figsize=(5.6 * len(data), 4.4), constrained_layout=True, squeeze=False)
        for ax, exp in zip(axes[0], data):
            for key, (color, name) in SERIES.items():
                ids = [f'trap1_N{N}_H1_T2' if key == 'trap1_H1_T2' else f'{key}_N{N}' for N in LAYERS]
                pts = [(N, tp[(exp, i)]) for N, i in zip(LAYERS, ids) if (exp, i) in tp]
                if not pts:
                    continue
                xs = [p[0] for p in pts]
                ax.fill_between(xs, [p[1]['q1'] for p in pts], [p[1]['q3'] for p in pts], color=color, alpha=0.18, lw=0)
                ax.plot(xs, [p[1]['median_msamples_per_s'] for p in pts], color=color, lw=2, marker='o', ms=8,
                        mec='#fcfcfb', mew=2, label=name)
            ax.set_xscale('log', base=2)
            ax.set_xticks(LAYERS, [str(n) for n in LAYERS])
            ax.set_xlabel('layers N', color=INK2)
            ax.set_ylabel('Msamples/s (median, band = IQR)', color=INK2)
            ax.set_title('21a: PRNG inline' if exp == '21a' else '21b: PRNG precomputed', color=INK, fontsize=12)
            ax.grid(axis='y', color=GRID, lw=1)
            ax.set_ylim(bottom=0)
            ax.tick_params(colors=INK2, length=0)
            for s in ('top', 'right', 'left'):
                ax.spines[s].set_visible(False)
            ax.spines['bottom'].set_color(GRID)
        axes[0][0].legend(frameon=False, fontsize=9, labelcolor=INK2, loc='lower right')
        fig.savefig(args.out / 'figures/throughput_vs_N.png', dpi=160)
        fig.savefig(args.out / 'figures/throughput_vs_N.svg')
        plt.close(fig)
    for c in checks:
        print(c)
    for r in speed:
        if r['H'] == 1 and r['T'] == 2:
            print(r['experiment'], r['N'], {k: round(v, 3) for k, v in r.items() if k.startswith('speedup') and not k.endswith('seeds')})


if __name__ == '__main__':
    main()
