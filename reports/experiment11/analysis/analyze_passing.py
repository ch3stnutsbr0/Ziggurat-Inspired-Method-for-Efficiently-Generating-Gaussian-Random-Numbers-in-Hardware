"""Experiment 11, passing subset: performance of the Trapezoid configurations with no rejection in any of
the four goodness-of-fit tests, compared with Classical (which passed all tests on the same streams in
Experiment 10).

    .venv/bin/python -B reports/experiment11/analysis/analyze_passing.py

Writes reports/experiment11/figures/good_*.png and reports/experiment11/tables/good_*.csv.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_experiment11 import DATA, FIG, TAB, CLASSICAL, H_COLORS, load  # noqa: E402

plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.titleweight': 'bold', 'savefig.dpi': 200, 'savefig.bbox': 'tight'})
TESTS = ['chi2', 'ks', 'cvm', 'ad']


def passing_set():
    runs, classical, trap, n = load()
    good = trap[trap.rejections == 0].copy()
    layers = sorted(good.N.unique())
    speeds = runs.groupby('config_id').throughput_msamples_per_s
    good['run_min'] = good.config_id.map(speeds.min())
    good['run_max'] = good.config_id.map(speeds.max())
    good['min_p_value'] = good[[f'{t}_p_value' for t in ('chi2', 'ks', 'cvm')]].min(axis=1)
    good['speedup_vs_classical_N256'] = good.median_throughput_msamples_per_s / classical.loc[256, 'median_throughput_msamples_per_s']
    # Distinguishable from the fastest passing config at the same N: all 5 runs below all 5 of its runs
    # (exact two-sided permutation p = 2/252 = 0.008 for 5 vs 5).
    for n_layers in layers:
        m = good.N == n_layers
        top = good[m].loc[good[m].median_throughput_msamples_per_s.idxmax()]
        good.loc[m, 'delta_vs_fastest_percent'] = 100 * (good[m].median_throughput_msamples_per_s / top.median_throughput_msamples_per_s - 1)
        good.loc[m, 'distinguishable_from_fastest'] = good[m].run_max < top.run_min
    good['rank_in_N'] = good.groupby('N').median_throughput_msamples_per_s.rank(ascending=False).astype(int)
    classical['run_min'] = [speeds.min()[f'classical_N{i}'] for i in classical.index]
    classical['run_max'] = [speeds.max()[f'classical_N{i}'] for i in classical.index]
    return runs, classical, trap, good, layers


def fig_overview(classical, good, layers):
    fig, axes = plt.subplots(1, len(layers), figsize=(13, 6.6), sharex=True)
    lo = min(good.run_min.min(), classical.loc[layers, 'run_min'].min()) - 1
    hi = good.run_max.max() + .5
    for ax, n in zip(axes, layers):
        sub = good[good.N == n].sort_values('median_throughput_msamples_per_s')
        y = np.arange(len(sub))
        ax.hlines(y, sub.run_min, sub.run_max, color='0.75', lw=3, label='range of 5 runs')
        ax.scatter(sub.median_throughput_msamples_per_s, y, c=[H_COLORS[h] for h in sub.H], s=36, zorder=3)
        ax.set_yticks(y, [f'H{h}/T{t}' for h, t in zip(sub.H, sub['T'])], fontsize=8)
        for ref, style, label in ((classical.loc[n], '-', f'Classical N={n}'), (classical.loc[256], ':', 'Classical N=256')):
            ax.axvline(ref.median_throughput_msamples_per_s, color=CLASSICAL, ls=style, lw=1.6)
            ax.text(ref.median_throughput_msamples_per_s, len(sub) - .3, label, color=CLASSICAL, fontsize=8, ha='right', rotation=90, va='top')
        ax.set(title=f'N = {n}: {len(sub)} passing configurations', xlabel='Throughput (M samples/s)', xlim=(lo, hi))
        ax.grid(axis='x', alpha=.25)
    handles = [Line2D([0], [0], marker='o', color=H_COLORS[h], lw=0, label=f'H = {h}') for h in H_COLORS]
    handles.append(Line2D([0], [0], color='0.75', lw=3, label='min–max of 5 runs'))
    fig.legend(handles=handles, loc='lower center', ncol=6, frameon=False, bbox_to_anchor=(.5, -.04))
    fig.suptitle('Throughput of every configuration that passes all four goodness-of-fit tests', fontweight='bold')
    fig.tight_layout(rect=(0, .03, 1, 1))
    fig.savefig(FIG / 'good_fig1_throughput_ranking.png'); plt.close(fig)


def fig_heatmaps(good, layers):
    fig, axes = plt.subplots(1, len(layers), figsize=(11, 4.4), constrained_layout=True)
    ts = sorted(good['T'].unique()); hs = sorted(good.H.unique())
    limit = np.ceil(good.delta_vs_fastest_percent.abs().max() * 10) / 10
    for ax, n in zip(axes, layers):
        sub = good[good.N == n]
        m = sub.pivot(index='H', columns='T', values='delta_vs_fastest_percent').reindex(index=hs, columns=ts)
        d = sub.pivot(index='H', columns='T', values='distinguishable_from_fastest').reindex(index=hs, columns=ts)
        im = ax.imshow(m.values, cmap='Reds_r', vmin=-limit, vmax=0, origin='lower')
        for (i, j), value in np.ndenumerate(m.values):
            ax.text(j, i, f'{value:.2f}' + ('*' if d.values[i, j] else ''), ha='center', va='center', fontsize=9,
                    color='white' if value < -.6 * limit else 'black')
        ax.set(title=f'N = {n}', xticks=range(len(ts)), xticklabels=ts, yticks=range(len(hs)), yticklabels=hs,
               xlabel='Tail levels T', ylabel='Head levels H')
        ax.spines[:].set_visible(False)
    fig.colorbar(im, ax=axes, shrink=.8, label='Throughput vs fastest passing config at the same N (%)')
    fig.suptitle('Passing configurations: throughput gap to the fastest (* = all 5 runs slower than all 5 of the fastest)',
                 fontweight='bold', fontsize=10)
    fig.savefig(FIG / 'good_fig2_ht_heatmaps.png'); plt.close(fig)


def fig_tradeoff(classical, good, layers):
    fig, (a, b) = plt.subplots(1, 2, figsize=(12.5, 4.8))
    markers = {128: 'o', 256: 's'}
    for n in layers:
        sub = good[good.N == n]
        a.scatter(sub.median_throughput_msamples_per_s, sub.chi2_z, c=[H_COLORS[h] for h in sub.H], marker=markers[n], s=40)
        b.scatter(sub.table_values, sub.median_throughput_msamples_per_s, c=[H_COLORS[h] for h in sub.H], marker=markers[n], s=40)
    a.axhspan(-1.96, 1.96, color='0.9', zorder=0)
    a.axhline(1.80, color='0.35', ls='--', lw=1)
    a.text(a.get_xlim()[0], 1.85, ' rejection threshold, z ≈ 1.8', fontsize=8, color='0.3', va='bottom')
    a.set(xlabel='Median throughput (M samples/s)', ylabel='χ² z = (X² − df)/√(2·df)',
          title='Goodness among passing configurations (grey: ±1.96)')
    for n, color in ((128, '#7aa6cf'), (256, CLASSICAL)):
        b.scatter(classical.loc[n, 'table_values'], classical.loc[n, 'median_throughput_msamples_per_s'], marker='D', s=70,
                  color=color, edgecolor='black', lw=.5, zorder=3)
        b.annotate(f'Classical N={n}', (classical.loc[n, 'table_values'], classical.loc[n, 'median_throughput_msamples_per_s']),
                   textcoords='offset points', xytext=(6, -4), fontsize=8)
    b.set(xscale='log', xlabel='Logical table size, binary64 values', ylabel='Median throughput (M samples/s)',
          title='Throughput vs table storage')
    for ax in (a, b):
        ax.grid(alpha=.25)
    handles = [Line2D([0], [0], marker=markers[n], color='0.4', lw=0, label=f'N = {n}') for n in layers]
    handles += [Line2D([0], [0], marker='o', color=H_COLORS[h], lw=0, label=f'H = {h}') for h in H_COLORS]
    handles.append(Line2D([0], [0], marker='D', color=CLASSICAL, mec='black', lw=0, label='Classical'))
    fig.legend(handles=handles, loc='lower center', ncol=8, frameon=False, bbox_to_anchor=(.5, -.06))
    fig.tight_layout(rect=(0, .04, 1, 1))
    fig.savefig(FIG / 'good_fig3_goodness_storage.png'); plt.close(fig)


def tables(classical, trap, good, layers):
    cols = ['config_id', 'N', 'H', 'T', 'rank_in_N', 'median_throughput_msamples_per_s', 'run_min', 'run_max', 'cv_percent',
            'delta_vs_fastest_percent', 'distinguishable_from_fastest', 'speedup_vs_classical', 'speedup_vs_classical_N256',
            'prng_calls_per_sample', 'table_values', 'chi2_z', 'chi2_p_value', 'ks_p_value', 'cvm_p_value', 'ad_p_value', 'min_p_value']
    good.sort_values(['N', 'rank_in_N'])[cols].to_csv(TAB / 'good_configurations.csv', index=False)
    rows = []
    for n in sorted(trap.N.unique()):
        rows.append(dict(N=n, trapezoid_configs=int((trap.N == n).sum()), passing=int(((trap.N == n) & (trap.rejections == 0)).sum())))
    pd.DataFrame(rows).to_csv(TAB / 'good_counts_by_N.csv', index=False)
    rows = []
    for n in layers:
        s, c = good[good.N == n], classical.loc[n]
        fast, slow = s.loc[s.median_throughput_msamples_per_s.idxmax()], s.loc[s.median_throughput_msamples_per_s.idxmin()]
        small = s.loc[s.table_values.idxmin()]
        rows.append(dict(N=n, passing=len(s), classical_msps=c.median_throughput_msamples_per_s,
            classical_calls=c.prng_calls_per_sample, classical_table_values=c.table_values,
            trap_min_msps=slow.median_throughput_msamples_per_s, trap_median_msps=s.median_throughput_msamples_per_s.median(),
            trap_max_msps=fast.median_throughput_msamples_per_s, fastest=f'H{fast.H}/T{fast["T"]}', slowest=f'H{slow.H}/T{slow["T"]}',
            speedup_min=s.speedup_vs_classical.min(), speedup_max=s.speedup_vs_classical.max(),
            speedup_vs_N256_min=s.speedup_vs_classical_N256.min(), speedup_vs_N256_max=s.speedup_vs_classical_N256.max(),
            spread_percent=100 * (fast.median_throughput_msamples_per_s / slow.median_throughput_msamples_per_s - 1),
            distinguishable_from_fastest=int(s.distinguishable_from_fastest.sum()),
            calls_min=s.prng_calls_per_sample.min(), calls_max=s.prng_calls_per_sample.max(),
            smallest_table=f'H{small.H}/T{small["T"]}', smallest_table_values=small.table_values,
            smallest_table_msps=small.median_throughput_msamples_per_s, smallest_table_delta_percent=small.delta_vs_fastest_percent))
    summary = pd.DataFrame(rows); summary.to_csv(TAB / 'good_summary_by_N.csv', index=False)
    return summary


def identical_streams(good):
    """Configurations whose 2^25-sample output is byte-identical (deeper levels never reached). Their speed
    differences can only be measurement noise, which calibrates the H/T comparison."""
    v = pd.read_csv(DATA / 'validation_results.csv', float_precision='round_trip')[['config_id', 'stream_sha256']]
    g = good.merge(v, on='config_id')
    rows = []
    for (n, digest), grp in g.groupby(['N', 'stream_sha256']):
        speeds = grp.median_throughput_msamples_per_s
        smallest = grp.loc[grp.table_values.idxmin()]
        rows.append(dict(N=n, configs=' '.join(f'H{h}/T{t}' for h, t in zip(grp.H, grp['T'])), count=len(grp),
                         smallest_table_config=f'H{smallest.H}/T{smallest["T"]}', smallest_table_values=smallest.table_values,
                         median_msps=speeds.median(),
                         spread_percent=100 * (speeds.max() / speeds.min() - 1) if len(grp) > 1 else float('nan'),
                         chi2_z=grp.chi2_z.iloc[0], stream_sha256=digest))
    out = pd.DataFrame(rows).sort_values(['N', 'median_msps'], ascending=[True, False])
    out.to_csv(TAB / 'good_identical_streams.csv', index=False)
    return out


def main():
    runs, classical, trap, good, layers = passing_set()
    fig_overview(classical, good, layers)
    fig_heatmaps(good, layers)
    fig_tradeoff(classical, good, layers)
    summary = tables(classical, trap, good, layers)
    streams = identical_streams(good)
    print(streams.drop(columns='stream_sha256').round(3).to_string(index=False))
    pd.set_option('display.width', 250, 'display.max_columns', 40)
    print('passing:', len(good), 'of', len(trap), 'layers', layers)
    print(summary.round(4).T.to_string())
    print(good.groupby('N')[['chi2_z', 'min_p_value']].agg(['min', 'max']).round(3))
    print(good.groupby(['N', 'H']).median_throughput_msamples_per_s.mean().unstack().round(2))
    print(good.groupby(['N', 'T']).median_throughput_msamples_per_s.mean().unstack().round(2))
    print(good.sort_values(['N', 'rank_in_N'])[['config_id', 'median_throughput_msamples_per_s', 'run_min', 'run_max',
          'distinguishable_from_fastest', 'table_values', 'chi2_z']].to_string(index=False))


if __name__ == '__main__':
    main()
