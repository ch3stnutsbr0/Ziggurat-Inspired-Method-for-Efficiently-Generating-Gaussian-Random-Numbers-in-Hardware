"""Experiment 22 analysis: variance of the time per sample, Trapezoid one-block against Classical.

Tables
  consistency_by_config.csv  pooled over seeds: mean, SD, CV, quantiles, max (cycles per sample)
  tail_fractions.csv         window 1: P(time > 2x and 3x the median) per configuration, pooled
  variance_ratio.csv         Classical variance / Trapezoid variance, per seed paired, median and
                             95% bootstrap interval over seeds (against H1/T2 and H0/T0)
Figures
  variance_ratio.png/.svg    the ratio against N, per window size, one panel per uniform mode
  latency_tail.png/.svg      P(time per sample > x), window 1, at N = 8 and 128, both modes

    .venv/bin/python -B reports/experiment22/analysis/analyze_experiment22.py
"""
import sys
sys.dont_write_bytecode = True
import csv
import math
import statistics as st
from collections import defaultdict
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parents[3]
RES = REPO / 'experiments/results/experiment22'
OUT = REPO / 'reports/experiment22'
LAYERS = [8, 16, 32, 64, 128, 256]
QUANTILES = [0.5, 0.9, 0.99, 0.999, 0.9999, 0.999999]
TRAP, TRAP0, CLASSICAL = 'trap1_H1_T2', 'trap1_H0_T0', 'classical_philox_fast'
BLUE, ORANGE, AQUA = '#2a78d6', '#eb6834', '#1baf7a'
INK, INK2, GRID, SURFACE = '#0b0b0b', '#52514e', '#e4e3df', '#fcfcfb'
WIN_COLORS = {1: '#9ec5f4', 16: '#5598e7', 256: '#1c5cab'}   # sequential blue, light -> dark


def pooled_stats(hist, W):
    n = sum(hist.values())
    vals = sorted(hist)
    mean = sum(v * hist[v] for v in vals) / n
    var = sum((v - mean) ** 2 * hist[v] for v in vals) / n
    out = dict(samples_or_windows=n, mean=mean / W, sd=math.sqrt(var) / W, variance=var / W ** 2,
               cv_percent=100 * math.sqrt(var) / mean)
    cum, qi = 0, 0
    for v in vals:
        cum += hist[v]
        while qi < len(QUANTILES) and cum >= QUANTILES[qi] * n:
            out[f'p{QUANTILES[qi] * 100:g}'] = v / W
            qi += 1
    out['max'] = vals[-1] / W
    return out


def bootstrap(values, rng, reps=4000):
    a = np.asarray(values)
    meds = np.median(a[rng.integers(0, len(a), (reps, len(a)))], axis=1)
    return float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5))


def main():
    rng = np.random.default_rng(2026)
    (OUT / 'tables').mkdir(parents=True, exist_ok=True)
    (OUT / 'figures').mkdir(parents=True, exist_ok=True)

    hists = defaultdict(dict)
    for r in csv.DictReader(open(RES / 'hist.csv')):
        hists[(r['config_id'].rsplit('_N', 1)[0], int(r['N']), r['uniform_mode'], int(r['window']))][
            int(r['cycles_per_window'])] = int(r['count'])
    table = []
    for (name, N, mode, W), h in sorted(hists.items(), key=lambda kv: (kv[0][2], kv[0][3], kv[0][0], kv[0][1])):
        table.append(dict(name=name, N=N, uniform_mode=mode, window=W, **pooled_stats(h, W)))
    with open(OUT / 'tables/consistency_by_config.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(table[0])); w.writeheader(); w.writerows(table)

    runs = [r for r in csv.DictReader(open(RES / 'runs.csv')) if r['status'] == 'ok']
    per = defaultdict(dict)
    for r in runs:
        per[(r['uniform_mode'], int(r['window']), int(r['N']), r['seed'])][r['config_id'].rsplit('_N', 1)[0]] = float(r['variance'])
    ratios = []
    for mode in ('precomputed', 'inline'):
        for W in (1, 16, 256):
            for N in LAYERS:
                keys = [k for k in per if k[:3] == (mode, W, N)]
                row = dict(uniform_mode=mode, window=W, N=N, seeds=len(keys))
                for ref in (TRAP, TRAP0):
                    v = [per[k][CLASSICAL] / per[k][ref] for k in keys]
                    lo, hi = bootstrap(v, rng)
                    row.update({f'ratio_vs_{ref}': st.median(v), f'ratio_vs_{ref}_ci_low': lo,
                                f'ratio_vs_{ref}_ci_high': hi, f'ratio_vs_{ref}_min': min(v)})
                ratios.append(row)
    with open(OUT / 'tables/variance_ratio.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(ratios[0])); w.writeheader(); w.writerows(ratios)

    # figure 1: variance ratio against N
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.3), constrained_layout=True, sharey=True)
    for ax, mode in zip(axes, ('inline', 'precomputed')):
        for W in (1, 16, 256):
            rs = [r for r in ratios if r['uniform_mode'] == mode and r['window'] == W]
            ax.fill_between(LAYERS, [r[f'ratio_vs_{TRAP}_ci_low'] for r in rs],
                            [r[f'ratio_vs_{TRAP}_ci_high'] for r in rs], color=WIN_COLORS[W], alpha=0.25, lw=0)
            ax.plot(LAYERS, [r[f'ratio_vs_{TRAP}'] for r in rs], color=WIN_COLORS[W], lw=2, marker='o', ms=7,
                    mec=SURFACE, mew=1.5, label={1: 'per sample (latency)', 16: 'windows of 16', 256: 'windows of 256'}[W])
        ax.axhline(1, color=INK2, lw=1, ls=(0, (4, 3)))
        ax.text(LAYERS[-1], 1.25, 'equal variance', ha='right', va='bottom', fontsize=9, color=INK2)
        ax.set_xscale('log', base=2)
        ax.set_xticks(LAYERS, [str(n) for n in LAYERS])
        ax.set_xlabel('layers N', color=INK2)
        ax.set_title('PRNG inline' if mode == 'inline' else 'PRNG precomputed (sampler work only)', fontsize=12, color=INK)
        ax.set_ylim(0, 18)
        ax.grid(axis='y', color=GRID, lw=1)
        ax.tick_params(colors=INK2, length=0)
        for s in ('top', 'right', 'left'):
            ax.spines[s].set_visible(False)
        ax.spines['bottom'].set_color(GRID)
    axes[0].set_ylabel('variance of time per sample:\nClassical / Trapezoid', color=INK2)
    axes[0].legend(frameon=False, fontsize=9, labelcolor=INK2, loc='lower left')
    fig.suptitle('Experiment 22: Classical (Philox, fast path) has 7–16x the timing variance of Trapezoid H1/T2',
                 fontsize=13, color=INK)
    fig.savefig(OUT / 'figures/variance_ratio.png', dpi=160)
    fig.savefig(OUT / 'figures/variance_ratio.svg')
    plt.close(fig)

    # figure 2: tail of the per-sample latency
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.4), constrained_layout=True, sharey=True)
    for row_ax, mode in zip(axes, ('inline', 'precomputed')):
        for ax, N in zip(row_ax, (8, 128)):
            for name, color, label in ((CLASSICAL, ORANGE, 'Classical, Philox fast path'),
                                       (TRAP, BLUE, 'Trapezoid one-block, H1/T2')):
                h = hists[(name, N, mode, 1)]
                vals = np.array(sorted(h))
                cnt = np.array([h[v] for v in vals], dtype=float)
                ccdf = 1 - np.cumsum(cnt) / cnt.sum()
                keep = ccdf > 0
                ax.step(vals[keep], ccdf[keep], where='post', color=color, lw=2, label=label)
            ax.axhspan(8e-6, 3e-5, color=GRID, alpha=0.6, lw=0)
            ax.text(690 if mode == 'inline' else 540, 3.3e-5,
                    'timer-interrupt floor (both samplers)', ha='right', va='bottom', fontsize=8.5, color=INK2)
            ax.set_yscale('log')
            ax.set_xlim(0, 700 if mode == 'inline' else 550)
            ax.set_ylim(1e-7, 1.5)
            ax.set_title(f"N = {N}, PRNG {mode}", fontsize=12, color=INK)
            ax.set_xlabel('core cycles for one sample (fenced, overhead removed)', color=INK2)
            ax.grid(color=GRID, lw=1)
            ax.tick_params(colors=INK2, length=0)
            for s in ('top', 'right'):
                ax.spines[s].set_visible(False)
            for s in ('left', 'bottom'):
                ax.spines[s].set_color(GRID)
        row_ax[0].set_ylabel('P(time per sample > x)', color=INK2)
    axes[0][1].legend(frameon=False, fontsize=9, labelcolor=INK2, loc='upper right')
    fig.suptitle('Experiment 22: tail of the time per sample (10 seeds pooled, 4.2 million samples each)',
                 fontsize=13, color=INK)
    fig.savefig(OUT / 'figures/latency_tail.png', dpi=160)
    fig.savefig(OUT / 'figures/latency_tail.svg')
    plt.close(fig)

    tails = []
    for (name, N, mode, W), h in sorted(hists.items(), key=lambda kv: (kv[0][2], kv[0][0], kv[0][1])):
        if W != 1:
            continue
        n = sum(h.values())
        med = pooled_stats(h, 1)['p50']
        tails.append(dict(name=name, N=N, uniform_mode=mode, samples=n, median_cycles=med,
                          p_over_2x_median=sum(c for v, c in h.items() if v > 2 * med) / n,
                          p_over_3x_median=sum(c for v, c in h.items() if v > 3 * med) / n))
    with open(OUT / 'tables/tail_fractions.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(tails[0])); w.writeheader(); w.writerows(tails)
    for t in tails:
        if t['name'] != TRAP0:
            print('tail', t['uniform_mode'], t['name'], t['N'], 'median %.0f  P>2x %.2e  P>3x %.2e' % (
                t['median_cycles'], t['p_over_2x_median'], t['p_over_3x_median']))
    for r in ratios:
        print(r['uniform_mode'], r['window'], r['N'], 'ratio %.1f [%.1f, %.1f]' % (
            r[f'ratio_vs_{TRAP}'], r[f'ratio_vs_{TRAP}_ci_low'], r[f'ratio_vs_{TRAP}_ci_high']))


if __name__ == '__main__':
    main()
