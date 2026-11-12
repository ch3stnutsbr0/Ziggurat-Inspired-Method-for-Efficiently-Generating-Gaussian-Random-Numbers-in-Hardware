"""Experiment 15 addendum: per-bin errors of the exact Trapezoid law, for every N, H and T.

Uses only experiments/results/experiment15/tail_curves.csv: the exact survival P(|X| > t) on a 0.05
grid to t = 10 (computed from the C tables, integrated from the right). Bin probabilities are
differences of survivals, so they are exact; rebuilding the 100 chi-square bins this way reproduces
the stored delta_binned to all printed digits.

Bins are on |x| (the law is symmetric), width 0.1, from 0 to 8. Per bin:
  p, q            Trapezoid and N(0,1) probability of |X| in the bin
  rel_error       p/q - 1 (-1 beyond the support)
  chi2_term       (p - q)^2 / q: this bin's contribution to the chi-square delta (two signed bins)
  n_detect_bin    1.96^2 q (1 - q) / (p - q)^2: samples at which this one bin's count is off by
                  1.96 binomial standard deviations (a single-bin test at 50% power, alpha 0.05)
Zones: head |x| < 0.5, body 0.5-3, shoulder 3-4, tail 4 to the support, beyond the support. The
tail is also split into the inner tail (4 to support - 0.5) and the edge (the last 0.5 before the
support), where the last trapezoid holds all of the remaining tail mass and always overshoots.

    .venv/bin/python -B reports/experiment15/analysis/bin_errors.py
"""
import sys
sys.dont_write_bytecode = True
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / 'experiments/results/experiment15'
OUT = Path(__file__).resolve().parents[1]
FIG, TAB = OUT / 'figures', OUT / 'tables'
LAYERS = [8, 16, 32, 64, 128, 256]
CAT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300']        # same order as the report
N_COLORS = dict(zip(LAYERS, CAT))
SEQ = ['#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b']
BLUES = LinearSegmentedColormap.from_list('blues', SEQ)
UNDER, OVER, BEYOND = '#2a78d6', '#e0582a', '#52514e'                            # deficit, excess, no support
INK, MUTED, GRID = '#0b0b0b', '#52514e', '#e4e3df'
ZONES = [('head', 0.0, 0.5), ('body', 0.5, 3.0), ('shoulder', 3.0, 4.0), ('tail', 4.0, np.inf)]
ZONE_COLORS = {'head': '#e87ba4', 'body': '#86b6ef', 'shoulder': '#1c5cab', 'tail': '#eda100', 'beyond support': BEYOND}
Z2 = 1.959963984540054 ** 2
WIDTH, XMAX = 0.1, 8.0
plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False, 'axes.grid': True,
                     'grid.color': GRID, 'grid.linewidth': 0.6, 'axes.edgecolor': MUTED, 'text.color': INK,
                     'axes.titleweight': 'bold', 'lines.linewidth': 2, 'savefig.dpi': 200, 'savefig.bbox': 'tight'})


def load():
    curves = defaultdict(list)
    for r in pd.read_csv(DATA / 'tail_curves.csv').itertuples(index=False):
        curves[(r.N, r.H, r.T)].append((r.t, r.survival, r.normal_survival))
    exact = pd.read_csv(DATA / 'exact_theory_all.csv').set_index(['N', 'H', 'T'])
    return curves, exact


def bins_for(curve, support):
    t = np.round(np.array([c[0] for c in curve]), 9)
    S = np.array([c[1] for c in curve]); Sn = np.array([c[2] for c in curve])
    idx = {x: i for i, x in enumerate(t)}
    edges = np.round(np.arange(0, XMAX + WIDTH / 2, WIDTH), 9)
    s = np.array([S[idx[e]] for e in edges]); sn = np.array([Sn[idx[e]] for e in edges])
    p, q = s[:-1] - s[1:], sn[:-1] - sn[1:]
    with np.errstate(divide='ignore', invalid='ignore'):
        rel = p / q - 1
        n_det = np.where(p == q, np.inf, Z2 * q * (1 - q) / (p - q) ** 2)
    lo, hi = edges[:-1], edges[1:]
    return pd.DataFrame(dict(bin_lo=lo, bin_hi=hi, p=p, q=q, rel_error=rel, chi2_term=(p - q) ** 2 / q,
                             n_detect_bin=n_det, beyond_support=lo >= support, contains_support=(lo < support) & (hi > support)))


def mirror(v):
    """Values on |x| bins -> both sides, -7..7 (the law is symmetric: bin -x has the error of bin x)."""
    v = np.asarray(v)
    return np.concatenate([v[..., ::-1], v], axis=-1)


def zone_of(lo, hi, support):
    if lo >= support:
        return 'beyond support'
    for name, a, b in ZONES:
        if a <= lo < b:
            return name
    return 'tail'


def main():
    TAB.mkdir(exist_ok=True); FIG.mkdir(exist_ok=True)
    curves, exact = load()
    rows, summary = [], []
    B = {}
    for (N, H, T), curve in sorted(curves.items()):
        support = float(exact.loc[(N, H, T), 'support'])
        b = bins_for(curve, support)
        b['zone'] = [zone_of(lo, hi, support) for lo, hi in zip(b.bin_lo, b.bin_hi)]
        B[(N, H, T)] = b
        rows.append(b.assign(config_id=f'trap_N{N}_H{H}_T{T}', N=N, H=H, T=T))
        inside = b[~b.beyond_support & ~b.contains_support]
        rec = dict(N=N, H=H, T=T, support=support, delta_0_to_8=b.chi2_term.sum(),
                   bins_inside=len(inside), bins_abs_rel_over_1pct=int((inside.rel_error.abs() > 0.01).sum()),
                   bins_abs_rel_over_0p1pct=int((inside.rel_error.abs() > 0.001).sum()),
                   worst_bin_lo=float(inside.loc[inside.rel_error.abs().idxmax(), 'bin_lo']),
                   worst_bin_rel_error=float(inside.loc[inside.rel_error.abs().idxmax(), 'rel_error']),
                   min_n_detect_bin_log2=float(np.log2(b.n_detect_bin.min())),
                   min_n_detect_bin_at=float(b.loc[b.n_detect_bin.idxmin(), 'bin_lo']))
        inner = b[(b.bin_lo >= 4.0) & (b.bin_hi <= support - 0.5)]
        edge = b[(b.bin_hi > support - 0.5) & ~b.beyond_support]
        rec['inner_tail_max_abs_rel_error'] = float(inner.rel_error.abs().max()) if len(inner) else ''
        rec['edge_max_rel_error'] = float(edge.rel_error.max()) if len(edge) else ''
        rec['edge_min_n_detect_log2'] = float(np.log2(edge.n_detect_bin.min())) if len(edge) else ''
        for at in (4.0, 5.0, 6.0, 7.0):
            row = b[np.isclose(b.bin_lo, at)].iloc[0]
            rec[f'rel_error_bin_{at:g}'] = float(row.rel_error) if not row.beyond_support else -1.0
        for z in ['head', 'body', 'shoulder', 'tail', 'beyond support']:
            zz = b[b.zone == z]
            rec[f'{z}_max_abs_rel_error'] = float(zz.rel_error.abs().max()) if len(zz) else ''
            rec[f'{z}_share_of_delta'] = float(zz.chi2_term.sum() / b.chi2_term.sum())
            rec[f'{z}_min_n_detect_log2'] = float(np.log2(zz.n_detect_bin.min())) if len(zz) else ''
        summary.append(rec)
    pd.concat(rows)[['config_id', 'N', 'H', 'T', 'bin_lo', 'bin_hi', 'zone', 'p', 'q', 'rel_error', 'chi2_term',
                     'n_detect_bin']].to_csv(TAB / 'bin_errors_0p1.csv', index=False, float_format='%.10g')
    S = pd.DataFrame(summary)
    S.to_csv(TAB / 'bin_error_summary.csv', index=False, float_format='%.6g')

    # ---- fig 6: signed relative error per bin, H1/T2, one panel per N
    def bin_panel(ax, b, sup, title, xmax=7):
        """Signed per-bin error, mirrored to -xmax..xmax, symlog, with the N(0,1) bell behind it."""
        b = b[b.bin_lo < xmax]
        colors = [BEYOND if bs else (UNDER if r < 0 else OVER) for r, bs in zip(b.rel_error, b.beyond_support)]
        centers = (b.bin_lo + WIDTH / 2).values
        bg = ax.twinx()                                            # N(0,1) bell in the background, shape only
        xs = np.linspace(-xmax, xmax, 701)
        bg.fill_between(xs, np.exp(-xs ** 2 / 2), color=GRID, lw=0, alpha=0.8)
        bg.set_ylim(0, 1.05); bg.axis('off')
        ax.set_zorder(bg.get_zorder() + 1); ax.patch.set_visible(False)
        ax.bar(np.r_[-centers[::-1], centers], 100 * mirror(b.rel_error.values), width=WIDTH * 0.85,
               color=colors[::-1] + colors, lw=0)
        for sx in (-sup, sup):
            ax.axvline(sx, color=INK, lw=1, ls=(0, (3, 2)))
        ax.text(sup + 0.08, 30, f'support\n±{sup:.2f}σ', fontsize=8, color=MUTED, va='bottom')
        ax.set_yscale('symlog', linthresh=0.01, linscale=0.6)
        ax.set_ylim(-150, 150)
        ax.set_yticks([-100, -10, -1, -0.1, -0.01, 0, 0.01, 0.1, 1, 10, 100])
        ax.set_yticklabels(['-100%', '-10%', '-1%', '-0.1%', '-0.01%', '0', '0.01%', '0.1%', '1%', '10%', '100%'],
                           fontsize=8)
        ax.set_xlim(-xmax, xmax)
        ax.set_xticks(range(-xmax, xmax + 1))
        ax.set_title(title, fontsize=11)
        ax.grid(axis='x', visible=False)

    def legend_below(fig, y=-0.03):
        handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in (OVER, UNDER, BEYOND, GRID)]
        fig.legend(handles, ['too many samples', 'too few samples', 'beyond the support (none)',
                             'N(0,1) density (shape, for reference)'], loc='lower center',
                   ncol=4, frameon=False, bbox_to_anchor=(0.5, y))

    fig, axes = plt.subplots(3, 2, figsize=(11, 9.6), sharey=True, constrained_layout=True)
    for ax, N in zip(axes.flat, LAYERS):
        bin_panel(ax, B[(N, 1, 2)], float(exact.loc[(N, 1, 2), 'support']), f'N = {N}, H1/T2')
    for ax in axes[-1]:
        ax.set_xlabel('x (bins of 0.1σ)')
    for ax in axes[:, 0]:
        ax.set_ylabel('bin probability error, p/q − 1')
    legend_below(fig)
    fig.suptitle('Per-bin error of the exact Trapezoid law (H1/T2): signed, log scale', fontsize=13)
    fig.savefig(FIG / 'fig6_bin_error_by_N.png')
    plt.close(fig)

    # ---- fig 6b: N = 128, H/T = 0/0 ... 4/4, one histogram each
    fig, axes = plt.subplots(5, 1, figsize=(11, 13.5), sharex=True, sharey=True, constrained_layout=True)
    for ax, k in zip(axes, range(5)):
        r = S[(S.N == 128) & (S.H == k) & (S['T'] == k)].iloc[0]
        title = (f'N = 128, H{k}/T{k}: worst head bin {100 * r.head_max_abs_rel_error:.3g}%, '
                 f'shoulder {100 * r.shoulder_max_abs_rel_error:.3g}%, bins over 1%: '
                 f'{r.bins_abs_rel_over_1pct} of {r.bins_inside}')
        bin_panel(ax, B[(128, k, k)], float(exact.loc[(128, k, k), 'support']), title, xmax=8)
        ax.set_ylabel('p/q − 1')
    axes[-1].set_xlabel('x (bins of 0.1σ)')
    legend_below(fig, y=-0.02)
    fig.suptitle('Per-bin error at N = 128 as head and tail refinement are added together (H = T = 0 … 4)',
                 fontsize=13)
    fig.savefig(FIG / 'fig6b_bin_error_N128_HT.png')
    plt.close(fig)

    # ---- fig 11 / 12: the same histograms on a linear axis (bin_errors_linear.md)
    LIM = 2.0                                                      # percent; larger bars are clipped and marked

    def bin_panel_linear(ax, b, sup, title, xmax=7):
        b = b[(b.bin_lo < xmax) & ~b.beyond_support]
        centers = (b.bin_lo + WIDTH / 2).values
        y = 100 * b.rel_error.values
        xs = np.linspace(-xmax, xmax, 701)
        bg = ax.twinx()
        bg.fill_between(xs, np.exp(-xs ** 2 / 2), color=GRID, lw=0, alpha=0.8)
        bg.set_ylim(0, 1.05); bg.axis('off')
        ax.set_zorder(bg.get_zorder() + 1); ax.patch.set_visible(False)
        for sx in (-1, 1):                                         # beyond the support: no samples at all
            ax.axvspan(sx * sup, sx * xmax, color=BEYOND, alpha=0.18, lw=0)
            ax.axvline(sx * sup, color=INK, lw=1, ls=(0, (3, 2)))
        X = np.r_[-centers[::-1], centers]
        Y = np.r_[y[::-1], y]
        Yc = np.clip(Y, -LIM, LIM)
        ax.bar(X, Yc, width=WIDTH * 0.85, color=np.where(Y < 0, UNDER, OVER), lw=0)
        up, down = Y > LIM, Y < -LIM
        ax.scatter(X[up], np.full(up.sum(), LIM * 1.05), marker='^', s=16, lw=0, c=OVER, clip_on=False, zorder=3)
        ax.scatter(X[down], np.full(down.sum(), -LIM * 1.05), marker='v', s=16, lw=0, c=UNDER, clip_on=False,
                   zorder=3)
        parts = ([f'{Y.max():+.0f}%'] if up.any() else []) + ([f'{Y.min():+.0f}%'] if down.any() else [])
        if parts:
            title = f'{title}  (clipped bars reach {" / ".join(parts)})'
        ax.text(sup + 0.08, -LIM * 0.92, f'support ±{sup:.2f}σ', fontsize=8, color=MUTED, va='bottom')
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.set_ylim(-LIM * 1.12, LIM * 1.12)
        ax.set_yticks(np.arange(-LIM, LIM + 0.01, 0.5))
        ax.set_yticklabels([f'{v:+.1f}%' if v else '0' for v in np.arange(-LIM, LIM + 0.01, 0.5)], fontsize=8)
        ax.set_xlim(-xmax, xmax)
        ax.set_xticks(range(-xmax, xmax + 1))
        ax.set_title(title, fontsize=11)
        ax.grid(axis='x', visible=False)

    def legend_linear(fig, y=-0.03):
        handles = [plt.Rectangle((0, 0), 1, 1, color=c, alpha=a) for c, a in ((OVER, 1), (UNDER, 1), (BEYOND, 0.18),
                                                                              (GRID, 1))]
        handles.append(plt.Line2D([], [], marker='^', ls='', color=MUTED, ms=5))
        fig.legend(handles, ['too many samples', 'too few samples', 'beyond the support (no samples)',
                             'N(0,1) density (shape)', f'bar clipped at ±{LIM:g}%'], loc='lower center', ncol=5,
                   frameon=False, bbox_to_anchor=(0.5, y), fontsize=9)

    fig, axes = plt.subplots(3, 2, figsize=(11, 9.6), sharey=True, constrained_layout=True)
    for ax, N in zip(axes.flat, LAYERS):
        bin_panel_linear(ax, B[(N, 1, 2)], float(exact.loc[(N, 1, 2), 'support']), f'N = {N}, H1/T2')
    for ax in axes[-1]:
        ax.set_xlabel('x (bins of 0.1σ)')
    for ax in axes[:, 0]:
        ax.set_ylabel('bin probability error, p/q − 1')
    legend_linear(fig)
    fig.suptitle(f'Per-bin error (H1/T2), linear scale, ±{LIM:g}%', fontsize=13)
    fig.savefig(FIG / 'fig11_bin_error_linear_by_N.png')
    plt.close(fig)

    fig, axes = plt.subplots(5, 1, figsize=(11, 13.5), sharex=True, sharey=True, constrained_layout=True)
    for ax, k in zip(axes, range(5)):
        r = S[(S.N == 128) & (S.H == k) & (S['T'] == k)].iloc[0]
        bin_panel_linear(ax, B[(128, k, k)], float(exact.loc[(128, k, k), 'support']),
                         f'N = 128, H{k}/T{k}: bins over 1%: {r.bins_abs_rel_over_1pct} of {r.bins_inside}', xmax=8)
        ax.set_ylabel('p/q − 1')
    axes[-1].set_xlabel('x (bins of 0.1σ)')
    legend_linear(fig, y=-0.02)
    fig.suptitle(f'Per-bin error at N = 128, H = T = 0 … 4, linear scale, ±{LIM:g}%', fontsize=13)
    fig.savefig(FIG / 'fig12_bin_error_linear_N128_HT.png')
    plt.close(fig)

    # ---- fig 7: heatmap |error| per bin x N, for H0/T0 and H1/T2
    fig, axes = plt.subplots(2, 1, figsize=(11, 5.6), constrained_layout=True)
    for ax, (H, T) in zip(axes, ((0, 0), (1, 2))):
        m = np.array([[abs(r) if not bs else np.nan for r, bs in zip(B[(N, H, T)].rel_error, B[(N, H, T)].beyond_support)]
                      for N in LAYERS])[:, :70]
        m = mirror(m)
        im = ax.imshow(np.log10(np.maximum(m, 1e-7)), aspect='auto', cmap=BLUES, vmin=-6, vmax=0,
                       extent=(-7, 7, len(LAYERS) - 0.5, -0.5), interpolation='nearest')
        beyond = np.isnan(m)
        ax.imshow(np.where(beyond, 1.0, np.nan), aspect='auto', cmap=LinearSegmentedColormap.from_list('b', [BEYOND, BEYOND]),
                  extent=(-7, 7, len(LAYERS) - 0.5, -0.5), interpolation='nearest')
        ax.axvline(0, color='#ffffff', lw=0.8)
        ax.set_xticks(range(-7, 8))
        ax.set_yticks(range(len(LAYERS)), [f'N={n}' for n in LAYERS])
        ax.set_xlabel('x (bins of 0.1σ)')
        ax.set_title(f'H{H}/T{T}: |p/q − 1| per bin, centred at 0 (gray: beyond the support)', fontsize=11)
        ax.grid(False)
    cb = fig.colorbar(im, ax=axes, shrink=0.8)
    cb.set_ticks(range(-6, 1), labels=['1e-6', '1e-5', '1e-4', '0.1%', '1%', '10%', '100%'])
    cb.set_label('|relative error| of the bin probability')
    fig.savefig(FIG / 'fig7_bin_error_heatmap.png')
    plt.close(fig)

    # ---- fig 8: head and tail zoom: H effect in the head (T=2), T effect in the tail (H=1)
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.4), constrained_layout=True)
    for row, N in zip(axes, (32, 128)):
        ax = row[0]
        for H, c in zip(range(5), CAT):
            b = B[(N, H, 2)]; b = b[b.bin_lo < 1.5]
            c_ = (b.bin_lo + WIDTH / 2).values
            ax.plot(np.r_[-c_[::-1], c_], 100 * mirror(b.rel_error.values), color=c, marker='o', ms=4, lw=1.6,
                    label=f'H={H}')
        ax.axhline(0, color=MUTED, lw=1)
        ax.set_xlim(-1.5, 1.5)
        ax.set_title(f'Head (centred at 0), N = {N}, T=2: effect of H', fontsize=11)
        ax.set_xlabel('x'); ax.set_ylabel('p/q − 1 (%)')
        ax.legend(frameon=False, fontsize=8, ncol=1, loc='upper left')
        ax = row[1]
        for T, c in zip(range(5), CAT):
            b = B[(N, 1, T)]; b = b[(b.bin_lo >= 2.5) & (b.bin_lo < 8.0)]
            y = np.where(b.beyond_support, np.nan, 100 * b.rel_error)
            ax.plot(b.bin_lo + WIDTH / 2, y, color=c, marker='o', ms=3, lw=1.6, label=f'T={T}')
            sup = float(exact.loc[(N, 1, T), 'support'])
            ax.axvline(sup, color=c, lw=1, ls=(0, (2, 2)))
        ax.set_yscale('symlog', linthresh=0.1, linscale=0.5)
        ax.set_ylim(-110, 40)
        ax.set_yticks([-100, -10, -1, -0.1, 0, 0.1, 1, 10])
        ax.set_yticklabels(['-100%', '-10%', '-1%', '-0.1%', '0', '0.1%', '1%', '10%'], fontsize=8)
        ax.set_title(f'Tail, N = {N}, H=1: effect of T (dotted: support)', fontsize=11)
        ax.set_xlabel('x (positive tail; the negative tail is its mirror image)'); ax.set_ylabel('p/q − 1')
        ax.legend(frameon=False, fontsize=8, ncol=5, loc='lower left')
    fig.savefig(FIG / 'fig8_head_tail_zoom.png')
    plt.close(fig)

    # ---- fig 9: where the chi-square delta comes from, by zone
    configs = [(0, 0), (1, 0), (0, 2), (1, 1), (1, 2), (1, 4)]
    fig, ax = plt.subplots(figsize=(11, 4.6), constrained_layout=True)
    xpos, labels, k = [], [], 0
    for N in LAYERS:
        for H, T in configs:
            r = S[(S.N == N) & (S.H == H) & (S['T'] == T)].iloc[0]
            bottom = 0
            for z in ['head', 'body', 'shoulder', 'tail', 'beyond support']:
                v = r[f'{z}_share_of_delta']
                ax.bar(k, v, bottom=bottom, color=ZONE_COLORS[z], width=0.85, lw=0, label=z if k == 0 else None)
                bottom += v
            xpos.append(k); labels.append(f'H{H}T{T}')
            k += 1
        ax.text(k - 3.5, 1.04, f'N = {N}', ha='center', fontsize=10, fontweight='bold')
        k += 1.2
    ax.set_xticks(xpos, labels, rotation=90, fontsize=8)
    ax.set_ylim(0, 1.1)
    ax.set_ylabel('share of the per-bin divergence (0–8σ)')
    ax.grid(axis='x', visible=False)
    ax.legend(frameon=False, ncol=5, loc='upper center', bbox_to_anchor=(0.5, -0.2))
    ax.set_title('Which |x| zone the remaining error sits in, by N and H/T', fontsize=12, pad=18)
    fig.savefig(FIG / 'fig9_error_share_by_zone.png')
    plt.close(fig)

    # ---- fig 10: samples needed to expose each bin on its own, heatmap bins x N, for H0/T0 and H1/T2
    fig, axes = plt.subplots(2, 1, figsize=(11, 5.6), constrained_layout=True)
    rev = LinearSegmentedColormap.from_list('rev', SEQ[::-1])          # dark = few samples = weak bin
    for ax, (H, T) in zip(axes, ((0, 0), (1, 2))):
        m = np.array([[np.log2(n) if not bs else np.nan for n, bs in zip(B[(N, H, T)].n_detect_bin,
                                                                          B[(N, H, T)].beyond_support)]
                      for N in LAYERS])[:, :70]
        m = mirror(m)
        im = ax.imshow(np.clip(m, 10, 50), aspect='auto', cmap=rev, vmin=10, vmax=50,
                       extent=(-7, 7, len(LAYERS) - 0.5, -0.5), interpolation='nearest')
        ax.imshow(np.where(np.isnan(m), 1.0, np.nan), aspect='auto',
                  cmap=LinearSegmentedColormap.from_list('b', [BEYOND, BEYOND]),
                  extent=(-7, 7, len(LAYERS) - 0.5, -0.5), interpolation='nearest')
        ax.axvline(0, color='#ffffff', lw=0.8)
        for i, N in enumerate(LAYERS):                                   # mark the weakest bin in each row
            row = B[(N, H, T)]
            k = int(row.n_detect_bin.values[:70].argmin())
            for sgn in (-1, 1):
                ax.text(sgn * (row.bin_lo.values[k] + WIDTH / 2), i, '×', ha='center', va='center',
                        color='#ffffff', fontsize=9)
        ax.set_xticks(range(-7, 8))
        ax.set_yticks(range(len(LAYERS)), [f'N={n}' for n in LAYERS])
        ax.set_xlabel('x (bins of 0.1σ)')
        ax.set_title(f'H{H}/T{T}: log2 samples until this bin alone shows its error (×: weakest bin; gray: beyond support)',
                     fontsize=11)
        ax.grid(False)
    cb = fig.colorbar(im, ax=axes, shrink=0.8)
    cb.set_ticks([10, 20, 30, 40, 50], labels=['2^10', '2^20', '2^30', '2^40', '≥ 2^50'])
    cb.set_label('samples to detect (single-bin test)')
    fig.savefig(FIG / 'fig10_bin_detect_samples.png')
    plt.close(fig)

    # console summary
    for N in LAYERS:
        for H, T in ((0, 0), (1, 0), (0, 2), (1, 2), (1, 4)):
            r = S[(S.N == N) & (S.H == H) & (S['T'] == T)].iloc[0]
            pc = lambda v, d: f'{100 * v:.{d}f}%' if v != '' else '-'
            print(f"N={N:>3} H{H}T{T}: worst bin {100*r.worst_bin_rel_error:+.3f}% at {r.worst_bin_lo:.1f}; "
                  f"head max {pc(r.head_max_abs_rel_error, 4)}, shoulder {pc(r.shoulder_max_abs_rel_error, 3)}, "
                  f"inner tail {pc(r.inner_tail_max_abs_rel_error, 3)}, edge {pc(r.edge_max_rel_error, 1)} (2^{r.edge_min_n_detect_log2:.1f}), "
                  f"bins 4/5/6: {pc(r['rel_error_bin_4'], 3)}/{pc(r['rel_error_bin_5'], 3)}/{pc(r['rel_error_bin_6'], 3)}; bins >1%: {r.bins_abs_rel_over_1pct}/{r.bins_inside}; "
                  f"weakest bin 2^{r.min_n_detect_bin_log2:.1f} at {r.min_n_detect_bin_at:.1f}; shares head {r.head_share_of_delta:.2f} "
                  f"body {r.body_share_of_delta:.2f} sh {r.shoulder_share_of_delta:.2f} tail {r.tail_share_of_delta:.2f} "
                  f"beyond {r['beyond support_share_of_delta']:.2f}")


if __name__ == '__main__':
    main()
