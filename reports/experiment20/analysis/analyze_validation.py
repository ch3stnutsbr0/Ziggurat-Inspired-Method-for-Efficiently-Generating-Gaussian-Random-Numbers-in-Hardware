"""Experiment 20 validation analysis: rejection counts, Fisher-combined p-values, comparison with
Experiment 13 (30 seeds, original sampler) and Experiment 15 (exact chi-square detection size).

    .venv/bin/python -B reports/experiment20/analysis/analyze_validation.py
"""
import sys
sys.dont_write_bytecode = True
import csv
import math
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from scipy import stats

REPO = Path(__file__).resolve().parents[3]
RAWS = [REPO / 'experiments/results/experiment20/validation/validation_raw.csv',          # seeds 1-5
        REPO / 'experiments/results/experiment20_seeds6_15/validation/validation_raw.csv']  # seeds 6-15
E13 = REPO / 'reports/experiment13/tables/goodness_by_config.csv'
E15 = REPO / 'experiments/results/experiment15/exact_theory_all.csv'
OUT = REPO / 'reports/experiment20'
TESTS = ['chi2', 'ks', 'cvm', 'ad']
LAYERS = [8, 16, 32, 64, 128, 256]
# sequential, one hue (blue), light -> dark: 0 .. 5 rejections out of 5
RAMP = ['#f1f5fb', '#cfdcf0', '#9db8e0', '#6a92cc', '#3d6bb0', '#1d4585']


def label(k, s):
    """Per test: P(>= k of s rejections | Gaussian, alpha 0.05) < 0.001 -> rejected; < 0.05 -> borderline."""
    tail = stats.binom.sf(k - 1, s, 0.05)
    return 'rejected' if tail < 0.001 else 'borderline' if tail < 0.05 else 'consistent'


def main():
    rows = [r for raw in RAWS if raw.exists() for r in csv.DictReader(open(raw)) if r['status'] == 'ok']
    seeds = sorted({int(r['seed']) for r in rows})
    e13 = {r['config_id']: r for r in csv.DictReader(open(E13))}
    e15 = {r['config_id']: r for r in csv.DictReader(open(E15))}
    by = defaultdict(list)
    for r in rows:
        by[(int(r['N']), int(r['H']), int(r['T']))].append(r)
    table = []
    for (N, H, T), rs in sorted(by.items()):
        key = f'trap_N{N}_H{H}_T{T}'
        row = dict(N=N, H=H, T=T, seeds=len(rs), decision_bits=rs[0]['decision_bits'])
        for t in TESTS:
            row[f'{t}_rejections'] = sum(int(r[f'{t}_reject']) for r in rs)
            # AD p-values are blank where the statistic is beyond SciPy's table (always a rejection there)
            ps = [max(float(r[f'{t}_p_value']), 1e-300) if r[f'{t}_p_value'] else 1e-300 for r in rs]
            row[f'{t}_fisher_p'] = stats.combine_pvalues(ps, method='fisher').pvalue
            row[f'{t}_exp13_reject_rate'] = e13[key][f'{t}_reject_rate'] if key in e13 else ''
        row['max_rejections'] = max(row[f'{t}_rejections'] for t in TESTS)
        row['label'] = label(row['max_rejections'], len(rs))
        row['exp13_max_reject_rate'] = max(float(e13[key][f'{t}_reject_rate']) for t in TESTS) if key in e13 else ''
        row['exp15_chi2_detect50_log2'] = math.log2(float(e15[key]['chi2_n_detect_50']))
        table.append(row)
    (OUT / 'tables').mkdir(parents=True, exist_ok=True)
    with open(OUT / 'tables/goodness_by_config.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(table[0])); w.writeheader(); w.writerows(table)
    grid = {(r['N'], r['H'], r['T']): r for r in table}

    # color-coded grid: one panel per N, rows H, columns T, cell = max rejections over the 4 tests
    fig, axes = plt.subplots(2, 3, figsize=(11, 7.6), constrained_layout=True)
    S = len(seeds)
    edges = [0, 0.05, 0.15, 0.3, 0.5, 0.8, 1.0001]
    cmap, norm = ListedColormap(RAMP), BoundaryNorm(edges, 6)
    for ax, N in zip(axes.flat, LAYERS):
        m = [[grid[(N, h, t)]['max_rejections'] / grid[(N, h, t)]['seeds'] for t in range(5)] for h in range(5)]
        im = ax.imshow(m, cmap=cmap, norm=norm, origin='upper')
        for h in range(5):
            for t in range(5):
                k = grid[(N, h, t)]['max_rejections']
                ax.text(t, h, str(k), ha='center', va='center', fontsize=11,
                        color='#ffffff' if m[h][t] >= 0.3 else '#1f2937', fontweight='bold' if m[h][t] >= 0.3 else 'normal')
        ax.set_xticks(range(5), [f'T{t}' for t in range(5)])
        ax.set_yticks(range(5), [f'H{h}' for h in range(5)])
        ax.set_xticks([x - 0.5 for x in range(1, 5)], minor=True)
        ax.set_yticks([y - 0.5 for y in range(1, 5)], minor=True)
        ax.grid(which='minor', color='#ffffff', linewidth=2)
        ax.tick_params(which='both', length=0, labelsize=9, colors='#4b5563')
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_title(f'N = {N}', fontsize=12, color='#111827')
    cb = fig.colorbar(im, ax=axes, ticks=edges[:-1] + [1.0], shrink=0.7, pad=0.02)
    cb.set_label('rejection rate, worst of χ² / KS / CvM / AD (cell text: seeds rejected)', color='#374151')
    cb.outline.set_visible(False)
    fig.suptitle(f'Experiment 20: Trapezoid one-block sampler, seeds rejected of {S} at 2^25 samples (α = 0.05)',
                 fontsize=13, color='#111827')
    (OUT / 'figures').mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / 'figures/rejection_grid.png', dpi=160)
    fig.savefig(OUT / 'figures/rejection_grid.svg')
    counts = defaultdict(int)
    for r in table:
        counts[r['label']] += 1
    print(f'{S} seeds', dict(counts))


if __name__ == '__main__':
    main()
