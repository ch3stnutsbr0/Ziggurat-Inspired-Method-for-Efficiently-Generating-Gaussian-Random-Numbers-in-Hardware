"""Experiment 15 figures and tables from experiments/results/experiment15/*.csv.

    .venv/bin/python -B reports/experiment15/analysis/analyze_experiment15.py
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
from matplotlib.colors import LinearSegmentedColormap
from scipy import stats

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / 'experiments/results/experiment15'
OUT = Path(__file__).resolve().parents[1]
FIG, TAB = OUT / 'figures', OUT / 'tables'
CAT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300']        # fixed categorical order
N_COLORS = dict(zip([8, 16, 32, 64, 128, 256], CAT))
T_COLORS = dict(zip(range(5), CAT))
BLUES = LinearSegmentedColormap.from_list('blues', ['#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b'])
INK, MUTED = '#0b0b0b', '#52514e'
plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False, 'axes.grid': True,
                     'grid.color': '#e4e3df', 'grid.linewidth': 0.6, 'axes.edgecolor': MUTED, 'text.color': INK,
                     'axes.titleweight': 'bold', 'lines.linewidth': 2, 'savefig.dpi': 200, 'savefig.bbox': 'tight'})


def pivot(a, col, digits=None):
    p = a.pivot_table(index=['N', 'H'], columns='T', values=col)
    p.columns = [f'T{t}' for t in p.columns]
    return p.round(digits) if digits is not None else p


def fig_support_law(a, fits):
    """Support and 1% reach depend on N and T only through M = N^(T+1)."""
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    b = a[a.H == 0]
    for N, g in b.groupby('N'):
        ax.plot(g.log2M, g.support, 'o', color=N_COLORS[N], ms=8, mec='#fcfcfb', mew=1.5, label=f'N={N}')
        ax.plot(g.log2M, g['reach_survival_eps0.01'], 's', color=N_COLORS[N], ms=8, mfc='none', mew=1.5)
    m = np.linspace(b.log2M.min(), b.log2M.max(), 200)
    s = stats.norm.isf(10 ** (fits['support_law']['log10_c'] + fits['support_law']['slope'] * m * np.log10(2)) / 2)
    ax.plot(m, s, color=MUTED, lw=1, ls='--', label='fit: 2Q(s) = c·M^-k')
    ax.set_xlabel('log2 M,  M = N^(T+1)  (number of leaf strips on the tail path)')
    ax.set_ylabel('|x| (σ)')
    ax.set_title('Tail reach is a function of M = N^(T+1) only')
    ax.text(0.98, 0.04, 'filled: support edge\nopen: survival ratio within 1%', transform=ax.transAxes,
            ha='right', va='bottom', color=MUTED, fontsize=9)
    ax.legend(frameon=False, fontsize=8, ncol=2, loc='upper left')
    fig.savefig(FIG / 'fig1_tail_reach_law.png'); plt.close(fig)


def fig_divergence_heatmaps(a):
    fig, axes = plt.subplots(2, 3, figsize=(11, 6.6), constrained_layout=True)
    lg = np.log10(a.D_continuous); vmin, vmax = lg.min(), lg.max()
    for ax, (N, g) in zip(axes.flat, a.groupby('N')):
        m = np.log10(g.pivot(index='H', columns='T', values='D_continuous').values)
        im = ax.imshow(m, cmap=BLUES.reversed(), vmin=vmin, vmax=vmax, origin='upper')
        for (i, j), v in np.ndenumerate(m):
            ax.text(j, i, f'{v:.2f}', ha='center', va='center', fontsize=8,
                    color='#fcfcfb' if v < (vmin + vmax) / 2 else INK)
        ax.set_title(f'N={N}'); ax.set_xlabel('T'); ax.set_ylabel('H'); ax.grid(False)
        ax.set_xticks(range(5)); ax.set_yticks(range(5))
    fig.colorbar(im, ax=axes, shrink=0.8, label='log10 D  (continuous χ² divergence; darker = closer to N(0,1))')
    fig.suptitle('Exact χ² divergence from N(0,1) over the full grid', fontweight='bold')
    fig.savefig(FIG / 'fig2_divergence_heatmaps.png'); plt.close(fig)


def fig_refinement(a):
    """D and KS versus T for H=0 and H=1; H>=2 overlaps H=1."""
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=False)
    for N, g in a.groupby('N'):
        for H, ls in ((0, ':'), (1, '-')):
            h = g[g.H == H]
            axes[0].plot(h['T'], h.D_continuous, ls, marker='o', ms=6, color=N_COLORS[N],
                         label=f'N={N}' if H == 1 else None)
            axes[1].plot(h['T'], h.ks_exact, ls, marker='o', ms=6, color=N_COLORS[N])
    for ax, lab in zip(axes, ('D (continuous χ² divergence)', 'exact KS distance')):
        ax.set_yscale('log'); ax.set_xlabel('tail levels T'); ax.set_ylabel(lab); ax.set_xticks(range(5))
    axes[0].set_title('Divergence saturates at T=2 (H=1)')
    axes[1].set_title('KS is set by the head: H=1 needed')
    axes[0].plot([], [], ':', color=MUTED, label='H=0'); axes[0].plot([], [], '-', color=MUTED, label='H=1 (H=2–4 overlap)')
    axes[0].legend(frameon=False, fontsize=8, ncol=2)
    fig.savefig(FIG / 'fig3_refinement_gain.png'); plt.close(fig)


def fig_regions(a):
    regions = [c for c in a.columns if c.startswith('D_region_')]
    labels = [c.replace('D_region_', '').replace('_inf', '+').replace('_', '–') + 'σ' for c in regions]
    pick = ['H0_T0', 'H0_T1', 'H0_T2', 'H1_T0', 'H1_T1', 'H1_T2', 'H1_T4', 'H4_T4']
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.2), sharey=True)
    for ax, N in zip(axes, (64, 128)):
        g = a[a.N == N].set_index('config_id').loc[[f'trap_N{N}_{p}' for p in pick]]
        left = np.zeros(len(g)); tot = g[regions].sum(axis=1).values
        for col, lab, color in zip(regions, labels, CAT):
            v = 100 * g[col].values / tot
            ax.barh(range(len(g)), v, left=left, color=color, edgecolor='#fcfcfb', linewidth=2, label=lab, height=0.7)
            left += v
        for i, d in enumerate(g.D_continuous):
            ax.text(101, i, f'D={d:.1e}', va='center', fontsize=8, color=MUTED)
        ax.set_xlim(0, 100); ax.set_yticks(range(len(g)), [p.replace('_', '/') for p in pick])
        ax.invert_yaxis(); ax.set_title(f'N={N}: where the divergence lives', pad=8)
        ax.set_xlabel('share of D (%)'); ax.grid(axis='y', visible=False)
    fig.legend(*axes[0].get_legend_handles_labels(), frameon=False, fontsize=8, title='|x| region',
               loc='lower center', ncol=6, bbox_to_anchor=(0.5, -0.08))
    fig.subplots_adjust(wspace=0.35)
    fig.savefig(FIG / 'fig4_divergence_by_region.png'); plt.close(fig)


def fig_tail_curves(c):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, N in zip(axes, (64, 128)):
        for T, g in c[(c.N == N) & (c.H == 1) & (c.t >= 2)].groupby('T'):
            ax.plot(g.t, g.survival_ratio, color=T_COLORS[T], label=f'T={T}')
        ax.axhspan(0.99, 1.01, color='#e4e3df', zorder=0, lw=0)
        ax.set_ylim(0, 1.15); ax.set_xlim(2, 8.5); ax.set_xlabel('t (σ)')
        ax.set_ylabel('P(|X| > t) / P(|Z| > t)'); ax.set_title(f'N={N}, H=1: tail mass ratio')
    axes[0].text(2.1, 1.03, '±1% band', color=MUTED, fontsize=8)
    axes[1].legend(frameon=False, fontsize=8, loc='lower left')
    fig.savefig(FIG / 'fig5_tail_ratio_curves.png'); plt.close(fig)


def main():
    FIG.mkdir(parents=True, exist_ok=True); TAB.mkdir(parents=True, exist_ok=True)
    a = pd.read_csv(DATA / 'exact_theory_all.csv', float_precision='round_trip')
    c = pd.read_csv(DATA / 'tail_curves.csv', float_precision='round_trip')
    a['log2M'] = (a['T'] + 1) * np.log2(a.N)

    # fits: support law and the saturated body floor
    b = a[a.H == 0]
    k, lc = np.polyfit(b.log2M * np.log10(2), np.log10(2 * stats.norm.sf(b.support)), 1)
    same_M = a.groupby('log2M').support.agg(lambda s: s.max() - s.min()).max()
    sat = a[(a.H == 1) & (a['T'] == 4)].set_index('N')
    fl, fc = np.polyfit(np.log10(sat.index), np.log10(sat.D_continuous), 1)
    fits = dict(support_law=dict(slope=k, log10_c=lc, max_support_spread_at_equal_M=same_M),
                body_floor=dict(D_exponent_in_N=fl, log10_c=fc,
                                D_H1T4={int(n): v for n, v in sat.D_continuous.items()}))

    # tables
    pivot(a, 'D_continuous').to_csv(TAB / 'D_continuous_pivot.csv')
    pivot(a, 'ks_exact').to_csv(TAB / 'ks_exact_pivot.csv')
    t0 = a[a.H == 1].pivot(index='N', columns='T', values=['support', 'reach_survival_eps0.01', 'reach_survival_eps0.1',
                                                            'support_n_one_missing'])
    t0.to_csv(TAB / 'tail_reach_by_N_T.csv')
    g = a.set_index(['N', 'H', 'T']).D_continuous
    gain = []
    for (N, H, T), v in g.items():
        gain.append(dict(N=N, H=H, T=T, D=v,
                         gain_add_T=g.get((N, H, T - 1), np.nan) / v if T else np.nan,
                         gain_add_H=g.get((N, H - 1, T), np.nan) / v if H else np.nan))
    pd.DataFrame(gain).to_csv(TAB / 'refinement_gain_factors.csv', index=False)
    cols = ['N', 'H', 'T', 'table_values', 'D_continuous', 'delta_binned', 'chi2_n_detect_50', 'ks_exact',
            'ks_n_detect_approx', 'total_variation', 'variance_error', 'kurtosis_error', 'support',
            'reach_survival_eps0.01', 'tail_budget_log2', 'tail_budget_at_t'] + [x for x in a if x.startswith('R_n2^')]
    a[(a.H <= 2)][cols].to_csv(TAB / 'design_table_H0to2.csv', index=False)
    (TAB / 'fits.json').write_text(json.dumps(fits, indent=2))

    fig_support_law(a, fits); fig_divergence_heatmaps(a); fig_refinement(a); fig_regions(a); fig_tail_curves(c)
    print(json.dumps(fits, indent=2))


if __name__ == '__main__':
    main()
