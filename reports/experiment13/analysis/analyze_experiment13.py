"""Experiment 13 figures and tables from experiments/results/experiment13/*.csv.

Compares the multi-seed results with Experiment 12's exact predictions and with Experiment 11 (seed 1).

    .venv/bin/python -B reports/experiment13/analysis/analyze_experiment13.py
"""
import sys
sys.dont_write_bytecode = True
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'experiments'))
import experiment12 as e12  # noqa: E402
DATA = REPO / 'experiments/results/experiment13'
EXP11 = REPO / 'experiments/results/experiment11'
EXP12 = REPO / 'experiments/results/experiment12'
OUT = Path(__file__).resolve().parents[1]
FIG, TAB = OUT / 'figures', OUT / 'tables'
N_COLORS = {8: '#440154', 16: '#3b528b', 32: '#21918c', 64: '#5ec962', 128: '#2369a8', 256: '#cf612c'}
CLASSICAL = '#333333'
TESTS = ['chi2', 'ks', 'cvm', 'ad']
plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.titleweight': 'bold', 'savefig.dpi': 200, 'savefig.bbox': 'tight'})
read = lambda p: pd.read_csv(p, float_precision='round_trip')


def load():
    perf = read(DATA / 'performance_runs.csv')
    perf_all = read(DATA / 'performance_summary_all_seeds.csv')
    valid = read(DATA / 'validation_results.csv')
    valid = valid[valid.status == 'ok'].drop_duplicates(['config_id', 'seed'], keep='last').copy()
    model = read(EXP12 / 'model_validation_all.csv')[['config_id', 'delta_exact', 'lambda_pred', 'p_reject_chi2']]
    return perf, perf_all, valid, model


# ---------------------------------------------------------------- integrity checks

def checks(perf, valid):
    out = {}
    out['timed_runs_total'] = len(perf)
    out['timed_runs_ok'] = int((perf.status == 'ok').sum())
    reps = perf[perf.status == 'ok'].groupby(['config_id', 'seed']).checksum.nunique()
    out['timed_config_seed_pairs'] = len(reps)
    out['timed_pairs_with_identical_checksums_across_repetitions'] = int((reps == 1).sum())
    out['validation_rows_ok'] = len(valid)
    m = valid.checksum_matches_performance.dropna()
    out['validation_rows_compared_with_timed_stream'] = len(m)
    out['validation_rows_matching_timed_stream'] = int((m == 1).sum())
    e11 = read(EXP11 / 'validation_results.csv')[['config_id', 'seed', 'stream_sha256']]
    both = valid.merge(e11, on=['config_id', 'seed'], suffixes=('', '_e11'))
    out['seed1_rows_compared_with_experiment11'] = len(both)
    out['seed1_rows_identical_to_experiment11'] = int((both.stream_sha256 == both.stream_sha256_e11).sum())
    out['chi2_degrees_of_freedom_values'] = sorted(int(v) for v in valid.chi2_degrees_of_freedom.unique())
    env = read(DATA / 'environment.csv')
    for key in ('boost', 'governor', 'scaling_max_khz', 'isolated_cpus'):
        out[f'environment_{key}'] = {f'{s}/{e}': v for s, e, v in env[env.key == key][['session', 'event', 'value']].values}
    clock = perf.cpu_scaling_khz_before.astype(float)
    out['timed_cpu_khz_before_run_min_median_max'] = [clock.min(), clock.median(), clock.max()]
    (TAB / 'integrity_checks.json').write_text(json.dumps(out, indent=2, default=str))
    return out


# ---------------------------------------------------------------- goodness

def exact_pearson_mean(g, samples):
    """E[X^2] - df for the multinomial Pearson statistic: (n-1)*delta + sum((p-q)/q).

    lambda = n*delta is only the leading term; sum((p-q)/q) is negative when the sampler puts too little
    mass in the low-q tail bins and amounts to tens of units at large lambda."""
    edges = np.r_[-np.inf, np.linspace(-5.0, 5.0, 101), np.inf]
    q = np.diff(stats.norm.cdf(edges))
    import tempfile
    out = {}
    with tempfile.TemporaryDirectory(prefix='experiment13-') as tmp:
        exe, _ = e12.build_exporter(Path(tmp))
        for r in g[g.algorithm == 'trapezoid'].itertuples():
            ents = e12.terminal_entries(exe, int(r.N), int(r.H), int(r.T))
            p = np.diff(np.r_[0.0, e12.cdf_x(edges[1:-1], ents), 1.0])
            out[r.config_id] = (samples - 1) * np.sum((p - q) ** 2 / q) + np.sum((p - q) / q)
    return g.config_id.map(out).fillna(0.0)


def goodness(valid, model):
    v = valid.copy()
    v['excess'] = v.chi2_statistic - v.chi2_degrees_of_freedom
    keys = ['config_id', 'algorithm', 'N', 'H', 'T']
    streams = (v.sort_values('seed').groupby('config_id').stream_sha256.agg(lambda s: '|'.join(s)))
    group_id = {k: i for i, k in enumerate(sorted(set(streams)))}
    g = v.groupby(keys, dropna=False).agg(
        seeds=('seed', 'nunique'), mean_excess=('excess', 'mean'), sd_excess=('excess', 'std'),
        df=('chi2_degrees_of_freedom', 'first'), **{f'{t}_reject_rate': (f'{t}_reject', 'mean') for t in TESTS},
        pass_all_rate=('rejections', lambda r: (r == 0).mean()), mean_rejections=('rejections', 'mean')).reset_index()
    g = g.merge(model, on='config_id', how='left')
    g.loc[g.algorithm == 'basic', ['delta_exact', 'lambda_pred']] = 0.0
    g.loc[g.algorithm == 'basic', 'p_reject_chi2'] = 0.05
    g['se_pred'] = np.sqrt(2 * (g.df + 2 * g.lambda_pred) / g.seeds)
    g['mean_pred_exact'] = exact_pearson_mean(g, int(v.samples.iloc[0]))
    g['consistency_z_lambda'] = (g.mean_excess - g.lambda_pred) / g.se_pred
    g['consistency_z'] = (g.mean_excess - g.mean_pred_exact) / g.se_pred
    g['chi2_rate_ci_lo'], g['chi2_rate_ci_hi'] = zip(*[wilson(r * n, n) for r, n in zip(g.chi2_reject_rate, g.seeds)])
    g['pred_rate_inside_ci'] = (g.p_reject_chi2 >= g.chi2_rate_ci_lo) & (g.p_reject_chi2 <= g.chi2_rate_ci_hi)
    g['stream_group'] = g.config_id.map(lambda c: group_id[streams[c]])
    g['seed1_passed_all'] = g.config_id.map(v[v.seed == 1].set_index('config_id').rejections.eq(0))
    return v, g


def wilson(k, n, z=1.96):
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(c - h, 0.0), min(c + h, 1.0)


def distinct(g):
    """One row per distinct stream group (configurations with identical streams for every seed)."""
    return g.sort_values(['N', 'H', 'T'], na_position='first').drop_duplicates('stream_group')


# ---------------------------------------------------------------- performance

def performance(perf_all):
    p = perf_all.copy()
    p['cv_across_seeds_percent'] = 100 * p.sd_of_seed_medians_msamples_per_s / p.mean_of_seed_medians_msamples_per_s
    e11 = read(EXP11 / 'performance_summary.csv')[['config_id', 'median_throughput_msamples_per_s', 'speedup_vs_classical']]
    e11.columns = ['config_id', 'exp11_median_msamples_per_s', 'exp11_speedup_vs_classical']
    return p.merge(e11, on='config_id', how='left')


# ---------------------------------------------------------------- figures

def trap_label(r):
    return f"N{int(r.N)} H{int(r.H)}/T{int(r.T)}"


def fig_speedup(p):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.6))
    t = p[p.algorithm == 'trapezoid']
    Ns = sorted(p.N.unique())
    for i, n in enumerate(Ns):
        s = t[t.N == n]
        a1.scatter(np.full(len(s), i) + np.random.default_rng(n).uniform(-0.18, 0.18, len(s)), s.speedup_vs_classical,
                   s=16, color=N_COLORS[n], alpha=0.8, label='Exp 13 (3.2 GHz, 5 seeds)' if i == 0 else None)
        a1.scatter(i + 0.32, s.exp11_speedup_vs_classical.median(), marker='D', facecolor='none', edgecolor=CLASSICAL,
                   s=40, label='Exp 11 median (boost on, seed 1)' if i == 0 else None)
    a1.axhline(1, color=CLASSICAL, lw=1, ls='--')
    a1.set(xticks=range(len(Ns)), xticklabels=[f'N={n}' for n in Ns], ylabel='speed-up vs Classical (same N)',
           title='Trapezoid speed-up over Classical (25 H/T per N)')
    a1.legend(frameon=False, fontsize=8)
    a2.hist(p.cv_across_seeds_percent.dropna(), bins=30, color='#2369a8')
    a2.set(xlabel='CV of per-seed median throughput across 5 seeds [%]', ylabel='configurations',
           title='Seed-to-seed throughput variation')
    fig.savefig(FIG / 'fig1_speedup_and_seed_stability.png'); plt.close(fig)


def fig_excess(g):
    d = distinct(g)
    t, c = d[d.algorithm == 'trapezoid'], d[d.algorithm == 'basic']
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5))
    xx = np.logspace(-2, 5.5, 300)
    se = np.sqrt(2 * (101 + 2 * xx) / g.seeds.max())
    a1.fill_between(xx, xx - 2 * se, xx + 2 * se, color='#dddddd', label='prediction ± 2 SE (30 seeds)')
    a1.plot(xx, xx, color=CLASSICAL, lw=1, label='mean observed = predicted')
    for n in sorted(t.N.unique()):
        s = t[t.N == n]
        a1.errorbar(s.lambda_pred, s.mean_excess, yerr=2 * s.se_pred, fmt='o', ms=4, color=N_COLORS[n], lw=0.8,
                    label=f'N={n}')
    a1.errorbar(np.full(len(c), 0.0), c.mean_excess, yerr=2 * c.se_pred, fmt='s', ms=5, color=CLASSICAL, mfc='white',
                label='Classical (λ = 0)')
    a1.set(xscale='symlog', yscale='symlog', xlim=(-0.05, 3e5), ylim=(-20, 3e5),
           xlabel='predicted χ² excess λ = n·δ (Experiment 12, exact)',
           ylabel='mean observed χ² excess over seeds', title='Seed-averaged χ² excess vs exact prediction')
    a1.legend(frameon=False, fontsize=7, loc='upper left')
    z = d.consistency_z
    a2.hist(d.consistency_z_lambda, bins=np.arange(-4, 4.01, 0.5), histtype='step', color='#888888', lw=1.5,
            label='vs λ = n·δ only')
    a2.hist(z, bins=np.arange(-4, 4.01, 0.5), color='#2369a8', alpha=0.75, edgecolor='white',
            label=f'vs exact Pearson mean ({len(z)} distinct streams)')
    zz = np.linspace(-4, 4, 200)
    a2.plot(zz, stats.norm.pdf(zz) * len(z) * 0.5, color='#cf612c', label='N(0, 1)')
    a2.set(xlabel='(mean observed − predicted) / SE', ylabel='count',
           title='Leftover differences vs pure noise')
    a2.set_ylim(0, 75)
    a2.legend(frameon=False, fontsize=8, loc='upper left')
    fig.savefig(FIG / 'fig2_mean_excess_vs_prediction.png'); plt.close(fig)


def fig_rate_heatmaps(g, column, title, name, cmap='RdYlGn'):
    t = g[g.algorithm == 'trapezoid']
    Ns = sorted(t.N.unique())
    fig, axes = plt.subplots(1, len(Ns), figsize=(2.6 * len(Ns), 3.0), sharey=True)
    for ax, n in zip(np.atleast_1d(axes), Ns):
        m = t[t.N == n].pivot(index='H', columns='T', values=column)
        im = ax.imshow(m.values, vmin=0, vmax=1, cmap=cmap, origin='lower')
        for (i, j), v in np.ndenumerate(m.values):
            ax.text(j, i, f'{v:.2f}', ha='center', va='center', fontsize=7, color='black')
        ax.set(xticks=range(m.shape[1]), xticklabels=m.columns.astype(int), yticks=range(m.shape[0]), yticklabels=m.index.astype(int),
               xlabel='T', title=f'N = {n}')
    np.atleast_1d(axes)[0].set_ylabel('H')
    fig.colorbar(im, ax=axes, shrink=0.8)
    fig.suptitle(title, fontweight="bold", y=0.98)
    fig.savefig(FIG / name); plt.close(fig)


def fig_rejection_pred(g):
    d = distinct(g)
    fig, ax = plt.subplots(figsize=(6.6, 5.6))
    ax.plot([0, 1], [0, 1], color=CLASSICAL, lw=1)
    for n in sorted(d.N.unique()):
        s = d[(d.N == n) & (d.algorithm == 'trapezoid')]
        ax.errorbar(s.p_reject_chi2, s.chi2_reject_rate,
                    yerr=[s.chi2_reject_rate - s.chi2_rate_ci_lo, s.chi2_rate_ci_hi - s.chi2_reject_rate],
                    fmt='o', ms=4, lw=0.7, color=N_COLORS[n], label=f'N={n}')
    c = d[d.algorithm == 'basic']
    ax.scatter(c.p_reject_chi2, c.chi2_reject_rate, marker='s', facecolor='white', edgecolor=CLASSICAL, zorder=3,
               label='Classical')
    ax.set(xlabel='predicted P(χ² rejects) at 2^25 (Experiment 12)', ylabel='observed χ² rejection rate (95% CI)',
           title='χ² rejection rate: predicted vs observed')
    ax.legend(frameon=False, fontsize=8, loc='lower right')
    fig.savefig(FIG / 'fig5_rejection_rate_vs_prediction.png'); plt.close(fig)


def fig_pvalues(v, g):
    """p-value histograms for Classical and for the low-lambda Trapezoid choice H1/T2 at N = 64, 128, 256.

    One configuration per N: H/T variants of the same N share almost every sample, so their p-values are
    not independent and pooling them would make the histogram clumpy and the uniformity test invalid."""
    reps = ['trap_N64_H1_T2', 'trap_N128_H1_T2', 'trap_N256_H1_T2']
    lam = g.set_index('config_id').lambda_pred.reindex(reps)
    sets = {'Classical (all N)': v[v.algorithm == 'basic'],
            f'Trapezoid H1/T2, N = 64/128/256 (λ = {lam.min():.1f}–{lam.max():.1f})': v[v.config_id.isin(reps)]}
    fig, axes = plt.subplots(2, 3, figsize=(12, 6), sharex=True)
    for row, (name, s) in zip(axes, sets.items()):
        for ax, t in zip(row, ['chi2', 'ks', 'cvm']):
            p = s[f'{t}_p_value'].dropna()
            ax.hist(p, bins=20, range=(0, 1), color='#2369a8', edgecolor='white')
            ax.axhline(len(p) / 20, color='#cf612c', lw=1.2)
            u = stats.kstest(p, 'uniform').pvalue if len(p) > 1 else np.nan
            ax.set(title=f'{name}\n{t}: n={len(p)}, uniformity p={u:.2f}')
            ax.title.set_fontsize(9)
    for ax in axes[-1]:
        ax.set_xlabel('p-value')
    fig.suptitle('p-values should be uniform when the output is indistinguishable from N(0,1)', fontweight='bold')
    fig.tight_layout()
    fig.savefig(FIG / 'fig6_pvalue_uniformity.png'); plt.close(fig)


def fig_tradeoff(g, p):
    m = g.merge(p[['config_id', 'speedup_vs_classical', 'median_throughput_msamples_per_s']], on='config_id')
    t = m[m.algorithm == 'trapezoid']
    fig, ax = plt.subplots(figsize=(8, 5.2))
    for n in sorted(t.N.unique()):
        s = t[t.N == n]
        ax.scatter(s.speedup_vs_classical, s.pass_all_rate, s=22, color=N_COLORS[n], label=f'N={n}', alpha=0.85)
    ax.axhline(0.95 ** 4, color=CLASSICAL, ls=':', lw=1)
    ax.text(ax.get_xlim()[1], 0.95 ** 4 + 0.015, 'all-4-pass rate of an exact generator ≈ 0.81 (if tests independent)',
            ha='right', fontsize=8)
    ax.set(xlabel='speed-up vs Classical (same N, 3.2 GHz)', ylabel='fraction of 30 seeds passing all 4 tests',
           title='Goodness (30 seeds) vs performance (5 seeds)', ylim=(-0.03, 1.05))
    ax.legend(frameon=False, fontsize=8, loc='center right')
    fig.savefig(FIG / 'fig7_goodness_vs_performance.png'); plt.close(fig)


# ---------------------------------------------------------------- main

def main():
    FIG.mkdir(parents=True, exist_ok=True)
    TAB.mkdir(parents=True, exist_ok=True)
    perf, perf_all, valid, model = load()
    info = checks(perf, valid)
    v, g = goodness(valid, model)
    p = performance(perf_all)
    order = ['algorithm', 'N', 'H', 'T']
    g.sort_values(order, na_position='first').to_csv(TAB / 'goodness_by_config.csv', index=False)
    p.sort_values(order, na_position='first').to_csv(TAB / 'performance_by_config.csv', index=False)
    fig_speedup(p)
    fig_excess(g)
    fig_rate_heatmaps(g, 'chi2_reject_rate', 'χ² rejection rate over seeds (Trapezoid)', 'fig3_chi2_rejection_heatmaps.png',
                      cmap='RdYlGn_r')
    fig_rate_heatmaps(g, 'pass_all_rate', 'Fraction of seeds passing all four tests (Trapezoid)',
                      'fig4_pass_all_heatmaps.png')
    fig_rejection_pred(g)
    fig_pvalues(v, g)
    fig_tradeoff(g, p)
    print(json.dumps(info, indent=1, default=str))
    print(f"seeds per config: {g.seeds.min()}–{g.seeds.max()}; distinct streams: {g.stream_group.nunique()}")


if __name__ == '__main__':
    main()
