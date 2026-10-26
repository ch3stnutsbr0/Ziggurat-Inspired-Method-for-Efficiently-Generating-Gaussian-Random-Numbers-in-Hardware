"""Experiment 11 analysis: figures and tables from the saved CSVs (no experiment is run).

    .venv/bin/python -B reports/experiment11/analysis/analyze_experiment11.py

Reads experiments/results/experiment11/*.csv and writes reports/experiment11/{figures,tables}/.
"""
import sys
sys.dont_write_bytecode = True
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from scipy import stats

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / 'experiments/results/experiment11'
OUT = Path(__file__).resolve().parents[1]
FIG, TAB = OUT / 'figures', OUT / 'tables'
LAYERS = [8, 16, 32, 64, 128, 256]
HS = TS = [0, 1, 2, 3, 4]
N_COLORS = dict(zip(LAYERS, plt.cm.viridis(np.linspace(0.05, 0.88, len(LAYERS)))))
H_COLORS = dict(zip(HS, plt.cm.plasma(np.linspace(0.05, 0.8, len(HS)))))
CLASSICAL, TRAP = '#2369a8', '#cf612c'

plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.titleweight': 'bold', 'figure.dpi': 100, 'savefig.dpi': 200, 'savefig.bbox': 'tight'})


def load():
    runs = pd.read_csv(DATA / 'performance_runs.csv', float_precision='round_trip')
    summary = pd.read_csv(DATA / 'performance_summary.csv', float_precision='round_trip')
    valid = pd.read_csv(DATA / 'validation_results.csv', float_precision='round_trip')
    assert (runs.status == 'ok').all() and (valid.status == 'ok').all() and (valid.checksum_matches_performance == 1).all()
    noise = runs.groupby('config_id').throughput_msamples_per_s.agg(lambda s: 100 * (s.max() - s.min()) / s.median())
    summary['range_percent'] = summary.config_id.map(noise)
    n = int(valid.samples.iloc[0])
    df = valid.chi2_degrees_of_freedom
    critical = stats.chi2.isf(valid.alpha, df)
    valid['chi2_z'] = (valid.chi2_statistic - df) / np.sqrt(2 * df)          # ~N(0,1) for an exact sampler
    valid['divergence'] = (valid.chi2_statistic - df).clip(lower=0) / n       # Pearson chi2 divergence estimate per bin set
    valid['detection_limit'] = (critical - df) / n
    valid['detectable'] = valid.chi2_statistic > critical
    valid['ks_sqrt_n_d'] = valid.ks_statistic * np.sqrt(n)
    trap = summary[summary.algorithm == 'trapezoid'].copy()
    trap[['H', 'T']] = trap[['H', 'T']].astype(int)
    trap = trap.merge(valid[['config_id', 'chi2_statistic', 'chi2_p_value', 'chi2_z', 'divergence', 'detection_limit',
                             'detectable', 'ks_sqrt_n_d', 'ks_p_value', 'cvm_p_value', 'ad_p_value', 'chi2_reject',
                             'ks_reject', 'cvm_reject', 'ad_reject', 'rejections']], on='config_id')
    trap['table_values'] = (1 + trap.H + trap['T']) * (5 * trap.N + 2)
    base = trap[(trap.H == 0) & (trap['T'] == 0)].set_index('N').median_throughput_msamples_per_s
    trap['delta_vs_H0T0_percent'] = 100 * (trap.median_throughput_msamples_per_s / trap.N.map(base) - 1)
    classical = summary[summary.algorithm == 'basic'].set_index('N')
    classical['table_values'] = 2 * classical.index
    return runs, classical, trap, n


def grid(trap, n, column):
    return trap[trap.N == n].pivot(index='H', columns='T', values=column).reindex(index=HS, columns=TS)


# ---------------------------------------------------------------- figures

def fig_classical_vs_trapezoid(classical, trap):
    g = trap.groupby('N').median_throughput_msamples_per_s
    s = trap.groupby('N').speedup_vs_classical
    fig, (a, b) = plt.subplots(1, 2, figsize=(12, 4.4))
    a.plot(LAYERS, classical.median_throughput_msamples_per_s, color=CLASSICAL, marker='o', lw=2, label='Classical Ziggurat')
    a.fill_between(LAYERS, g.min(), g.max(), color=TRAP, alpha=.25, label='Trapezoid, range over 25 H/T')
    a.plot(LAYERS, g.median(), color=TRAP, marker='s', lw=2, label='Trapezoid, median over H/T')
    a.set(xscale='log', ylabel='Median throughput (M samples/s)', xlabel='Layers N', ylim=(0, 105),
          title='Throughput, 2^25 samples, precomputed uniforms')
    b.fill_between(LAYERS, s.min(), s.max(), color=TRAP, alpha=.25)
    b.plot(LAYERS, s.median(), color=TRAP, marker='s', lw=2)
    for n in LAYERS:
        b.annotate(f'{s.median()[n]:.2f}×', (n, s.median()[n]), textcoords='offset points', xytext=(0, 8), ha='center')
    b.axhline(1, color='0.4', lw=1, ls='--')
    b.set(xscale='log', ylabel='Trapezoid / Classical throughput', xlabel='Layers N', ylim=(0.9, 1.55),
          title='Speedup over Classical at the same N')
    for ax in (a, b):
        ax.set_xticks(LAYERS, [str(n) for n in LAYERS]); ax.minorticks_off(); ax.grid(alpha=.25)
    a.legend(frameon=False, loc='lower right')
    fig.savefig(FIG / 'fig1_classical_vs_trapezoid.png'); plt.close(fig)


def fig_ht_heatmaps(trap):
    fig, axes = plt.subplots(2, 3, figsize=(12.5, 7.6), constrained_layout=True)
    limit = np.ceil(trap.delta_vs_H0T0_percent.abs().max() * 2) / 2
    for ax, n in zip(axes.flat, LAYERS):
        m = grid(trap, n, 'delta_vs_H0T0_percent')
        im = ax.imshow(m.values, cmap='RdBu', vmin=-limit, vmax=limit, origin='lower')
        for (i, j), value in np.ndenumerate(m.values):
            ax.text(j, i, f'{value:+.2f}', ha='center', va='center', fontsize=8.5, color='white' if abs(value) > .6 * limit else 'black')
        base = trap[(trap.N == n) & (trap.H == 0) & (trap['T'] == 0)].median_throughput_msamples_per_s.iloc[0]
        ax.set(title=f'N = {n}  (H0/T0 = {base:.1f} M/s)', xticks=range(5), yticks=range(5), xlabel='Tail levels T', ylabel='Head levels H')
        ax.spines[:].set_visible(False)
    fig.colorbar(im, ax=axes, shrink=.7, label='Throughput change vs H=0/T=0 at the same N (%)')
    fig.suptitle('Effect of head/tail refinement on throughput (blue = faster, red = slower)', fontweight='bold')
    fig.savefig(FIG / 'fig2_ht_throughput_heatmaps.png'); plt.close(fig)


def fig_goodness_vs_t(trap):
    fig, axes = plt.subplots(2, 3, figsize=(12.5, 7.4), sharey=True, constrained_layout=True)
    floor = trap.detection_limit.min() / 3
    for ax, n in zip(axes.flat, LAYERS):
        sub = trap[trap.N == n]
        for h in HS:
            row = sub[sub.H == h].sort_values('T')
            y = row.divergence.where(row.detectable, floor)
            ax.plot(row['T'] + (h - 2) * .05, y, color=H_COLORS[h], marker='o', lw=1.6, ms=5, label=f'H={h}')
            ax.scatter(row['T'][~row.detectable] + (h - 2) * .05, y[~row.detectable], s=40, facecolor='white',
                       edgecolor=H_COLORS[h], zorder=3)
        ax.axhline(sub.detection_limit.iloc[0], color='0.35', ls='--', lw=1)
        ax.set(title=f'N = {n}', yscale='log', xticks=TS, xlabel='Tail levels T')
        ax.grid(alpha=.25)
    axes[0, 0].set_ylabel('Excess χ² per sample (log)'); axes[1, 0].set_ylabel('Excess χ² per sample (log)')
    axes[0, 0].text(4, trap.detection_limit.min() * 1.4, 'χ² detection limit (α=0.05)', ha='right', fontsize=8, color='0.3')
    handles = [Line2D([0], [0], color=H_COLORS[h], marker='o', lw=1.6, label=f'H = {h}') for h in HS]
    handles.append(Line2D([0], [0], color='0.4', marker='o', mfc='white', lw=0, label='not detectable (plotted at floor)'))
    fig.legend(handles=handles, loc='lower center', ncol=6, frameon=False, bbox_to_anchor=(.5, -.05))
    fig.suptitle('Goodness of fit versus refinement: (χ² − df)/n, lower is closer to N(0,1)', fontweight='bold')
    fig.savefig(FIG / 'fig3_goodness_vs_refinement.png'); plt.close(fig)


def fig_rejections(trap):
    fig, axes = plt.subplots(1, 6, figsize=(15, 3.2), constrained_layout=True)
    cmap = matplotlib.colors.ListedColormap(['#e8f1e4', '#f6e7b4', '#f2c08c', '#e58b62', '#c4473a'])
    for ax, n in zip(axes, LAYERS):
        m = grid(trap, n, 'rejections')
        ax.imshow(m.values, cmap=cmap, vmin=-.5, vmax=4.5, origin='lower')
        for (i, j), value in np.ndenumerate(m.values):
            ax.text(j, i, int(value), ha='center', va='center', fontsize=9)
        ax.set(title=f'N = {n}', xticks=range(5), yticks=range(5), xlabel='T')
        ax.spines[:].set_visible(False)
    axes[0].set_ylabel('H')
    fig.suptitle('Rejected tests out of 4 (χ², KS, CvM, AD; α = 0.05, one seed)', fontweight='bold')
    fig.savefig(FIG / 'fig4_rejection_counts.png'); plt.close(fig)


def fig_tradeoff(trap, classical):
    fig, (a, b) = plt.subplots(1, 2, figsize=(13, 5.2))
    floor = trap.detection_limit.min() / 3
    y = trap.divergence.where(trap.detectable, floor)
    for n in LAYERS:
        m = trap.N == n
        for ax, x in ((a, trap.median_throughput_msamples_per_s), (b, trap.table_values)):
            ax.scatter(x[m & trap.detectable], y[m & trap.detectable], color=N_COLORS[n], s=28, alpha=.9)
            ax.scatter(x[m & ~trap.detectable], y[m & ~trap.detectable], facecolor='white', edgecolor=N_COLORS[n], s=34)
            h0 = m & (trap.H == 0) & (trap['T'] == 0)
            ax.scatter(x[h0], y[h0], marker='X', color=N_COLORS[n], s=80, edgecolor='black', lw=.5)
        a.axvline(classical.loc[n, 'median_throughput_msamples_per_s'], color=N_COLORS[n], ls=':', lw=1.2)
    for ax in (a, b):
        ax.axhline(trap.detection_limit.iloc[0], color='0.35', ls='--', lw=1)
        ax.set(yscale='log', ylabel='Excess χ² per sample (log; lower is better)')
        ax.grid(alpha=.25)
    a.set(xlabel='Median throughput (M samples/s)', title='Goodness vs speed (dotted: Classical at each N)')
    b.set(xscale='log', xlabel='Logical table size, binary64 values: (1+H+T)(5N+2)', title='Goodness vs table storage')
    handles = [Line2D([0], [0], marker='o', color=N_COLORS[n], lw=0, label=f'N = {n}') for n in LAYERS]
    handles += [Line2D([0], [0], marker='X', color='0.5', mec='black', lw=0, ms=9, label='H=0/T=0'),
                Line2D([0], [0], marker='o', mfc='white', mec='0.4', lw=0, label='not detectable')]
    fig.legend(handles=handles, loc='lower center', ncol=8, frameon=False, bbox_to_anchor=(.5, -.06))
    fig.savefig(FIG / 'fig5_goodness_tradeoff.png'); plt.close(fig)


# ---------------------------------------------------------------- tables

def tables(runs, classical, trap, n_samples):
    trap.sort_values(['N', 'H', 'T']).to_csv(TAB / 'trapezoid_configurations.csv', index=False)
    rows = []
    for n in LAYERS:
        s, c = trap[trap.N == n], classical.loc[n]
        pick = lambda h, t: s[(s.H == h) & (s['T'] == t)].iloc[0]
        rows.append(dict(N=n, classical_msps=c.median_throughput_msamples_per_s, classical_calls=c.prng_calls_per_sample,
            trap_min_msps=s.median_throughput_msamples_per_s.min(), trap_median_msps=s.median_throughput_msamples_per_s.median(),
            trap_max_msps=s.median_throughput_msamples_per_s.max(), speedup_min=s.speedup_vs_classical.min(),
            speedup_median=s.speedup_vs_classical.median(), speedup_max=s.speedup_vs_classical.max(),
            speedup_H0T0=pick(0, 0).speedup_vs_classical, speedup_H2T4=pick(2, 4).speedup_vs_classical,
            calls_H0T0=pick(0, 0).prng_calls_per_sample, calls_H4T4=pick(4, 4).prng_calls_per_sample))
    t1 = pd.DataFrame(rows); t1.to_csv(TAB / 'table1_classical_vs_trapezoid.csv', index=False)

    rows = []
    for n in LAYERS:
        s = trap[trap.N == n]
        fast, slow = s.loc[s.median_throughput_msamples_per_s.idxmax()], s.loc[s.median_throughput_msamples_per_s.idxmin()]
        rows.append(dict(N=n, fastest=f'H{fast.H}/T{fast["T"]}', fastest_msps=fast.median_throughput_msamples_per_s,
            slowest=f'H{slow.H}/T{slow["T"]}', slowest_msps=slow.median_throughput_msamples_per_s,
            spread_percent=100 * (fast.median_throughput_msamples_per_s / slow.median_throughput_msamples_per_s - 1),
            mean_T0_vs_Tpos_percent=100 * (s[s['T'] == 0].median_throughput_msamples_per_s.mean() / s[s['T'] > 0].median_throughput_msamples_per_s.mean() - 1),
            mean_H0_vs_Hpos_percent=100 * (s[s.H == 0].median_throughput_msamples_per_s.mean() / s[s.H > 0].median_throughput_msamples_per_s.mean() - 1),
            median_within_config_range_percent=s.range_percent.median()))
    t2 = pd.DataFrame(rows); t2.to_csv(TAB / 'table2_ht_throughput_spread.csv', index=False)

    rows = []
    for n in LAYERS:
        s = trap[trap.N == n]
        h0 = s[(s.H == 0) & (s['T'] == 0)].iloc[0]
        fastest = s.median_throughput_msamples_per_s.max()
        clean = s[~s.detectable]
        best = s.loc[s.divergence.idxmin()] if clean.empty else clean.loc[clean.median_throughput_msamples_per_s.idxmax()]
        passing = s[s.rejections == 0]
        rows.append(dict(N=n, H0T0_chi2_z=h0.chi2_z, H0T0_divergence=h0.divergence, H0T0_rejections=h0.rejections,
            configs_chi2_not_detectable=len(clean), configs_passing_all_4=len(passing),
            best=f'H{best.H}/T{best["T"]}', best_chi2_z=best.chi2_z, best_divergence=best.divergence, best_rejections=best.rejections,
            best_cost_vs_fastest_percent=100 * (best.median_throughput_msamples_per_s / fastest - 1),
            best_cost_vs_H0T0_percent=best.delta_vs_H0T0_percent,
            divergence_reduction_factor=h0.divergence / best.divergence if best.divergence > 0 else np.inf,
            best_table_values=best.table_values, best_speedup_vs_classical=best.speedup_vs_classical))
    t3 = pd.DataFrame(rows); t3.to_csv(TAB / 'table3_goodness_tradeoff.csv', index=False)
    return t1, t2, t3


def crosscheck_experiment10(runs):
    """Experiment 10 (inline uniforms) and 11 (precomputed) should produce identical streams for shared configs."""
    import json
    path = REPO / 'experiments/results/experiment10'
    perf = [r for r in json.loads((path / 'raw/performance/performance_runs.json').read_text()) if r['num_samples'] == 2**25]
    valid = {(v['algorithm'], v['N'], v['H'] or 0, v['T'] or 0): v for v in json.loads((path / 'processed/validation_results.json').read_text())}
    rows = []
    for r in {(x['algorithm'], x['N'], x['H'], x['T']): x for x in perf}.values():
        cid = f"classical_N{r['N']}" if r['algorithm'] == 'basic' else f"trap_N{r['N']}_H{r['H']}_T{r['T']}"
        v10 = valid[(r['algorithm'], r['N'], r['H'], r['T'])]
        rows.append(dict(config_id=cid, checksum_identical=bool((runs[runs.config_id == cid].checksum == r['checksum']).all()),
                         exp10_rejections=sum(t['reject'] for t in v10['tests'].values())))
    out = pd.DataFrame(rows); out.to_csv(TAB / 'crosscheck_experiment10.csv', index=False)
    return out


def main():
    FIG.mkdir(parents=True, exist_ok=True); TAB.mkdir(parents=True, exist_ok=True)
    runs, classical, trap, n = load()
    fig_classical_vs_trapezoid(classical, trap)
    fig_ht_heatmaps(trap)
    fig_goodness_vs_t(trap)
    fig_rejections(trap)
    fig_tradeoff(trap, classical)
    t1, t2, t3 = tables(runs, classical, trap, n)
    x = crosscheck_experiment10(runs)
    print('Exp10 cross-check: identical streams', int(x.checksum_identical.sum()), '/', len(x),
          '; Exp10 Classical rejections', x[x.config_id.str.startswith('classical')].exp10_rejections.tolist())
    pd.set_option('display.width', 250, 'display.max_columns', 30)
    for name, t in (('T1', t1), ('T2', t2), ('T3', t3)):
        print(name); print(t.round(4).to_string(index=False)); print()
    print('detection limit', trap.detection_limit.iloc[0], 'chi2 df', trap.chi2_z.size)
    print('T-effect means of divergence by T (all N):'); print(trap.groupby(['N', 'T']).divergence.median().unstack().apply(lambda r: r.map('{:.2e}'.format)))


if __name__ == '__main__':
    main()
