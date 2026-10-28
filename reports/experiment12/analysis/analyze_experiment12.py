"""Experiment 12 figures and tables from experiments/results/experiment12/*.csv.

    .venv/bin/python -B reports/experiment12/analysis/analyze_experiment12.py
"""
import sys
sys.dont_write_bytecode = True
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LogNorm
from matplotlib.lines import Line2D
from scipy import stats

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / 'experiments/results/experiment12'
OUT = Path(__file__).resolve().parents[1]
FIG, TAB = OUT / 'figures', OUT / 'tables'
N_COLORS = {8: '#440154', 16: '#3b528b', 32: '#21918c', 64: '#5ec962', 128: '#2369a8', 256: '#cf612c'}
CLASSICAL = '#333333'
plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.titleweight': 'bold', 'savefig.dpi': 200, 'savefig.bbox': 'tight'})


def load():
    allrows = pd.read_csv(DATA / 'model_validation_all.csv', float_precision='round_trip')
    passing = pd.read_csv(DATA / 'exact_metrics_passing.csv', float_precision='round_trip')
    entries = pd.read_csv(DATA / 'terminal_entries_passing.csv', float_precision='round_trip')
    trap = passing[passing.algorithm == 'trapezoid'].copy()
    trap[['H', 'T']] = trap[['H', 'T']].astype(int)
    return allrows, passing, trap, entries


def density_abs(x, ents):
    f = np.zeros_like(x)
    for w, d, p in zip(ents.w, ents.d, ents.weight):
        k = 2 / (2 * w + d)
        f += p * k * np.where(x <= w, 1.0, np.clip((w + d - x) / d, 0, None))
    return f


def tail_abs(x, ents):
    F = np.zeros_like(x)
    for w, d, p in zip(ents.w, ents.d, ents.weight):
        k = 2 / (2 * w + d)
        Fk = np.where(x <= w, k * x, np.where(x < w + d, k * (x - (x - w) ** 2 / (2 * d)), 1.0))
        F += p * Fk
    return 1 - F


def fig_validation(allrows):
    fig, ax = plt.subplots(figsize=(7.2, 6.2))
    t = allrows[allrows.algorithm == 'trapezoid']
    c = allrows[allrows.algorithm == 'classical']
    lim = np.array([1e-1, 2e5])
    xx = np.logspace(-1, 5.4, 300)
    sd = np.sqrt(2 * (101 + 2 * xx))
    ax.fill_between(xx, xx - 2 * sd, xx + 2 * sd, color='0.88', label='prediction ± 2 sd (sampling noise)')
    ax.plot(xx, xx, color='0.3', lw=1, label='observed = predicted')
    for n in sorted(t.N.unique()):
        s = t[t.N == n]
        ax.scatter(s.lambda_pred, s.observed_excess_seed1, s=22, color=N_COLORS[n], label=f'Trapezoid N={n}', zorder=3)
    ax.scatter(np.full(len(c), 0.15), c.observed_excess_seed1, marker='D', s=40, color=CLASSICAL,
               label='Classical (predicted 0, drawn at left edge)', zorder=3)
    ax.set_xscale('log'); ax.set_yscale('symlog', linthresh=30)
    ax.set(xlim=lim, xlabel='Predicted χ² excess λ = n·δ (exact model, n = 2^25)',
           ylabel='Observed χ² excess X² − df (seed 1)',
           title='Model validation: exact prediction vs seed-1 measurement')
    ax.legend(frameon=False, fontsize=8, loc='upper left')
    ax.grid(alpha=.25)
    fig.savefig(FIG / 'fig1_model_validation.png'); plt.close(fig)


def fig_heatmaps(trap):
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 8.2), constrained_layout=True)
    for row, (col, label, fmt) in enumerate((('delta_exact', 'Exact χ² divergence δ', '{:.2e}'),
                                             ('ks_exact', 'Exact KS distance D', '{:.1e}'))):
        vals = trap[col]
        norm = LogNorm(vals.min(), vals.max())
        for ax, n in zip(axes[row], (128, 256)):
            s = trap[trap.N == n]
            m = s.pivot(index='H', columns='T', values=col).reindex(index=range(5), columns=range(1, 5))
            im = ax.imshow(m.values, cmap='magma_r', norm=norm, origin='lower')
            for (i, j), v in np.ndenumerate(m.values):
                ax.text(j, i, fmt.format(v), ha='center', va='center', fontsize=8,
                        color='white' if norm(v) > .55 else 'black')
            ax.set(title=f'{label}, N = {n}', xticks=range(4), xticklabels=range(1, 5), yticks=range(5),
                   xlabel='Tail levels T', ylabel='Head levels H')
            ax.spines[:].set_visible(False)
        fig.colorbar(im, ax=axes[row], shrink=.85, label=label + ' (log; lower is better; Classical = 0)')
    fig.suptitle('Exact goodness of the 40 passing configurations', fontweight='bold')
    fig.savefig(FIG / 'fig2_exact_goodness_heatmaps.png'); plt.close(fig)


REPS = [('trap_N128_H0_T1', '#9ecae1', '--'), ('trap_N128_H1_T1', '#2369a8', '-'), ('trap_N128_H1_T3', '#08306b', ':'),
        ('trap_N256_H1_T1', '#fdae6b', '--'), ('trap_N256_H1_T2', '#cf612c', '-')]


def label(cid):
    _, n, h, t = cid.split('_')
    return f'N={n[1:]} {h}/{t}'


def fig_error_location(entries):
    fig, (a, b) = plt.subplots(1, 2, figsize=(13, 4.8))
    x = np.linspace(0, 5, 20001)
    target = 2 * stats.norm.pdf(x)
    for cid, color, ls in REPS:
        e = entries[entries.config_id == cid]
        a.plot(x, (density_abs(x, e) - target) * 1e4, color=color, ls=ls, lw=1.3, label=label(cid))
    a.axhline(0, color=CLASSICAL, lw=1.2, label='Classical (exact)')
    a.set(xlabel='|x|', ylabel='f_|X|(x) − 2φ(x)  (×10⁻⁴)', title='Density error by position: body and peak',
          ylim=(-6, 6))
    a.legend(frameon=False, fontsize=8, ncol=2); a.grid(alpha=.25)
    t = np.linspace(3, 8.2, 2001)
    true_tail = 2 * stats.norm.sf(t)
    for cid, color, ls in REPS:
        e = entries[entries.config_id == cid]
        ratio = tail_abs(t, e) / true_tail
        b.plot(t, np.where(ratio > 0, ratio, np.nan), color=color, ls=ls, lw=1.5, label=label(cid))
        supp = (e.w + e.d).max()
        b.axvline(supp, color=color, ls=ls, lw=.8, alpha=.7)
    b.axhline(1, color=CLASSICAL, lw=1.2, label='Classical (exact)')
    b.set(xlabel='t (σ)', ylabel='P(|X| > t) / P(|Z| > t)', yscale='log', ylim=(1e-2, 3),
          title='Tail mass relative to N(0,1); vertical lines = support bound')
    b.legend(frameon=False, fontsize=8); b.grid(alpha=.25, which='both')
    fig.savefig(FIG / 'fig3_error_location_and_tails.png'); plt.close(fig)


def fig_tradeoff(passing, trap):
    fig, (a, b) = plt.subplots(1, 2, figsize=(13, 4.9))
    floor = 2e-8
    markers = {0: 'X', 1: 'o', 2: 's', 3: '^', 4: 'D'}
    for n in (128, 256):
        s = trap[trap.N == n]
        for h in range(5):
            g = s[s.H == h]
            a.scatter(g.median_throughput_msps, g.delta_exact, color=N_COLORS[n], marker=markers[h], s=40, alpha=.85)
            b.scatter(g.table_values, g.delta_exact, color=N_COLORS[n], marker=markers[h], s=40, alpha=.85)
    for _, c in passing[passing.algorithm == 'classical'].iterrows():
        for ax, x in ((a, c.median_throughput_msps), (b, c.table_values)):
            ax.scatter(x, floor, marker='*', s=160, color=N_COLORS[c.N], edgecolor='black', zorder=4)
            ax.annotate(f'Classical N={c.N}\n(exact, δ = 0)', (x, floor), textcoords='offset points', xytext=(6, 6), fontsize=8)
    for ax in (a, b):
        ax.set_yscale('log'); ax.set_ylim(floor / 2, 1e-6); ax.grid(alpha=.25, which='both')
        ax.set_ylabel('Exact χ² divergence δ (log; lower is better)')
    a.set(xlabel='Median throughput, Experiment 11 (M samples/s)', title='Exact goodness vs speed')
    b.set(xscale='log', xlabel='Logical table size (binary64 values)', title='Exact goodness vs table storage')
    handles = [Line2D([0], [0], marker='o', color=N_COLORS[n], lw=0, label=f'N = {n}') for n in (128, 256)]
    handles += [Line2D([0], [0], marker=markers[h], color='0.4', lw=0, label=f'H = {h}') for h in range(5)]
    handles.append(Line2D([0], [0], marker='*', color='0.4', mec='black', lw=0, ms=12, label='Classical'))
    fig.legend(handles=handles, loc='lower center', ncol=8, frameon=False, bbox_to_anchor=(.5, -.06))
    fig.tight_layout(rect=(0, .04, 1, 1))
    fig.savefig(FIG / 'fig4_goodness_vs_performance.png'); plt.close(fig)


def fig_detection(trap):
    fig, ax = plt.subplots(figsize=(10, 4.6))
    s = trap.sort_values(['N', 'H', 'T'])
    xpos = np.arange(len(s))
    ax.bar(xpos, np.log2(s.n_detect_50), color=[N_COLORS[n] for n in s.N], alpha=.85, label='χ² test, 50% detection')
    ax.scatter(xpos, np.log2(s.ks_n_detect_approx), color='black', s=14, zorder=3, label='KS test, ≈ detection (D = critical value)')
    ax.axhline(25, color='0.3', ls='--', lw=1); ax.text(len(s) - .5, 25.2, 'Experiments 10/11: 2^25 samples', ha='right', fontsize=8)
    ax.set_xticks(xpos, [f'{h}/{t}' for h, t in zip(s.H, s['T'])], rotation=90, fontsize=7)
    ax.set(ylabel='log₂ samples needed to detect', xlabel='H/T   (left 20: N = 128, right 20: N = 256)', ylim=(22, 42),
           title='How many samples it takes for a test to notice the approximation')
    ax.legend(frameon=False, fontsize=8, loc='upper left'); ax.grid(axis='y', alpha=.25)
    fig.savefig(FIG / 'fig5_samples_to_detect.png'); plt.close(fig)


def tables(allrows, passing, trap):
    t = allrows[allrows.algorithm == 'trapezoid']
    big = t[t.lambda_pred > 1000]
    summary = pd.DataFrame([
        dict(group='Trapezoid, all 150', count=len(t), mean_consistency_sd=t.consistency_sd.mean(),
             sd_consistency_sd=t.consistency_sd.std(), beyond_2sd=int((t.consistency_sd.abs() > 2).sum()),
             beyond_3sd=int((t.consistency_sd.abs() > 3).sum())),
        dict(group='Trapezoid, λ > 1000 (43)', count=len(big), mean_consistency_sd=big.consistency_sd.mean(),
             sd_consistency_sd=big.consistency_sd.std(), beyond_2sd=int((big.consistency_sd.abs() > 2).sum()),
             beyond_3sd=int((big.consistency_sd.abs() > 3).sum()),
             max_rel_diff=(big.observed_excess_seed1 / big.lambda_pred - 1).abs().max()),
        dict(group='Classical, 6 N', count=6, mean_consistency_sd=allrows[allrows.algorithm == 'classical'].consistency_sd.mean(),
             sd_consistency_sd=allrows[allrows.algorithm == 'classical'].consistency_sd.std(),
             beyond_2sd=int((allrows[allrows.algorithm == 'classical'].consistency_sd.abs() > 2).sum()), beyond_3sd=0)])
    summary.to_csv(TAB / 'model_validation_summary.csv', index=False)
    cols = ['config_id', 'N', 'H', 'T', 'delta_exact', 'lambda_pred', 'p_reject_chi2', 'n_detect_50', 'n_detect_90',
            'ks_exact', 'ks_n_detect_approx', 'support', 'variance_error', 'tail_ratio_3', 'tail_ratio_4', 'tail_ratio_5',
            'tail_ratio_6', 'observed_excess_seed1', 'consistency_sd', 'median_throughput_msps', 'speedup_vs_classical',
            'table_values']
    passing[cols].sort_values(['N', 'H', 'T'], na_position='first').to_csv(TAB / 'exact_metrics_passing.csv', index=False)
    return summary


def main():
    FIG.mkdir(parents=True, exist_ok=True); TAB.mkdir(parents=True, exist_ok=True)
    allrows, passing, trap, entries = load()
    fig_validation(allrows)
    fig_heatmaps(trap)
    fig_error_location(entries)
    fig_tradeoff(passing, trap)
    fig_detection(trap)
    print(tables(allrows, passing, trap).round(3).to_string(index=False))
    for n in (128, 256):
        s = trap[trap.N == n]
        for name, g in (('H=0', s[s.H == 0]), ('H>=1', s[s.H >= 1])):
            for tt in range(1, 5):
                r = g[g['T'] == tt]
                print(n, name, f'T={tt}', 'delta %.3e  P(rej) %.3f  n50 2^%.1f  KS %.2e  supp %.2f  t5 %.3f t6 %.3f  M/s %.2f-%.2f  tables %d-%d' % (
                    r.delta_exact.iloc[0], r.p_reject_chi2.iloc[0], np.log2(r.n_detect_50.iloc[0]), r.ks_exact.iloc[0],
                    r.support.iloc[0], r.tail_ratio_5.iloc[0], r.tail_ratio_6.iloc[0], r.median_throughput_msps.min(),
                    r.median_throughput_msps.max(), r.table_values.min(), r.table_values.max()))
    print('KS n detect log2 range:', np.log2(trap.ks_n_detect_approx).round(1).agg(['min', 'max']).tolist())


if __name__ == '__main__':
    main()
