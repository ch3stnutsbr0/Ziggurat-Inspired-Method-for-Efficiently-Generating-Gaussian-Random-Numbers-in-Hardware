"""Experiment 14 figures and tables from experiments/results/experiment14/*.csv.

    .venv/bin/python -B reports/experiment14/analysis/analyze_experiment14.py
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

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / 'experiments/results/experiment14'
OUT = Path(__file__).resolve().parents[1]
FIG, TAB = OUT / 'figures', OUT / 'tables'
CLASSICAL, TRAP, ACCENT = '#333333', '#2369a8', '#cf612c'
STYLE = {'basic': dict(color=CLASSICAL, marker='s', ls='--', mfc='white'), 'trapezoid': dict(color=TRAP, marker='o', ls='-')}
NAME = {'basic': 'Classical', 'trapezoid': 'Trapezoid H1/T2'}
plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.titleweight': 'bold', 'savefig.dpi': 200, 'savefig.bbox': 'tight',
                     'axes.grid': True, 'grid.color': '#e6e6e6', 'grid.linewidth': 0.6})
read = lambda name: pd.read_csv(DATA / name)
NS = [8, 16, 32, 64, 128, 256]
cid = lambda alg, n: f'classical_N{n}' if alg == 'basic' else f'trap_N{n}_H1_T2'


# ---------------------------------------------------------------- A: word length and memory

def fig_rounding(q, wl, n=128):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, col, label in zip(axes, ['delta', 'ks'], ['χ² divergence δ', 'KS distance']):
        for alg in ('trapezoid', 'basic'):
            s = q[(q.config_id == cid(alg, n)) & (q.frac_bits != 'double')]
            b = s.frac_bits.astype(int)
            ax.plot(b, s[col].clip(lower=1e-30), lw=2, ms=4, label=NAME[alg], **STYLE[alg])
            bs = wl.set_index('config_id').loc[cid(alg, n), 'b_star']
            v = s[s.frac_bits.astype(int) == bs][col].iloc[0]
            ax.plot([bs], [v], marker='v', ms=9, color=STYLE[alg]['color'], ls='none', zorder=4)
            ax.annotate(f'b* = {bs}', (bs, v), xytext=(4, -16), textcoords='offset points', fontsize=8,
                        color=STYLE[alg]['color'])
        ref = q[(q.config_id == cid('trapezoid', n)) & (q.frac_bits == 'double')][col].iloc[0]
        ax.axhline(ref, color=ACCENT, lw=1, ls=':')
        ax.text(32, ref * 2.2, 'Trapezoid approximation error (unrounded)', ha='right', fontsize=8, color='#555555')
        ax.set(yscale='log', xlabel='fraction bits per table value', ylabel=label,
               title=f'{label} after rounding the tables (N={n})')
    axes[0].legend(frameon=False, fontsize=8, loc='upper right')
    fig.tight_layout()
    fig.savefig(FIG / 'fig1_rounding_error.png'); plt.close(fig)


def fig_memory(wl):
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    w = wl.set_index('config_id')
    x = np.arange(len(NS))
    for k, alg in enumerate(('basic', 'trapezoid')):
        bits = [w.loc[cid(alg, n), 'bits_at_b_star'] for n in NS]
        ax.bar(x + (k - 0.5) * 0.38, np.array(bits) / 8192, width=0.36, color=STYLE[alg]['color'],
               label=f"{NAME[alg]} (at its b*)", edgecolor='white', linewidth=2)
    for i, n in enumerate(NS):
        r = w.loc[cid('trapezoid', n), 'bits_at_b_star'] / w.loc[cid('basic', n), 'bits_at_b_star']
        ax.text(i, w.loc[cid('trapezoid', n), 'bits_at_b_star'] / 8192 * 1.15, f'{r:.1f}×', ha='center', fontsize=8)
    ax.set(xticks=x, xticklabels=[f'N={n}' for n in NS], yscale='log', ylabel='table memory [KiB]',
           title='Table memory at the word length where rounding is negligible')
    ax.legend(frameon=False, fontsize=8)
    fig.savefig(FIG / 'fig2_table_memory.png'); plt.close(fig)


# ---------------------------------------------------------------- B1: uniforms per sample

def fig_uniforms(pmf):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=True)
    for ax, n in zip(axes, (8, 128)):
        for k, alg in enumerate(('basic', 'trapezoid')):
            s = pmf[pmf.config_id == cid(alg, n)]
            ax.bar(s.uniforms + (k - 0.5) * 0.4, s.probability, width=0.38, color=STYLE[alg]['color'],
                   label=NAME[alg], log=True)
        ax.set(xlabel='uniforms consumed by one sample', title=f'N = {n}', xlim=(1.5, 30), ylim=(1e-16, 2))
    axes[0].set_ylabel('probability (exact)')
    axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle('Uniforms per sample: Trapezoid is bounded, Classical has a geometric tail', fontweight='bold')
    fig.tight_layout()
    fig.savefig(FIG / 'fig3_uniforms_per_sample.png'); plt.close(fig)


# ---------------------------------------------------------------- B2: timing

def median_run(hist, runs, config_id, mode, block):
    """Histogram of the repetition with the median mean time (one slow pass cannot distort the figure)."""
    g = hist[(hist.config_id == config_id) & (hist.uniform_mode == mode) & (hist.block == block)]
    means = g.groupby('repetition').apply(lambda x: np.average(x.ticks, weights=x['count']))
    rep = means.sort_values().index[len(means) // 2]
    g = g[g.repetition == rep]
    r = runs[(runs.config_id == config_id) & (runs.uniform_mode == mode) & (runs.repetition == rep)].iloc[0]
    return (g.ticks - r.overhead_median_ticks).to_numpy() / r.tsc_hz * 1e9 / block, g['count'].to_numpy()


def fig_timing(hist, runs):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    for ax, n in zip(axes, (8, 128)):
        for alg in ('basic', 'trapezoid'):
            ns, cnt = median_run(hist, runs, cid(alg, n), 'precomputed', 16)
            o = np.argsort(ns)
            ccdf = 1 - np.cumsum(cnt[o]) / cnt.sum()
            st = STYLE[alg]
            ax.step(ns[o], np.clip(ccdf, 1e-8, 1), where='post', color=st['color'], ls=st['ls'], lw=2, label=NAME[alg])
        ax.axhspan(1e-7, 2e-4, color='#f2f2f2', zorder=0)
        ax.text(110, 2e-5, 'shaded: OS timer interrupts\n(about 5e-5 of blocks, both algorithms)', ha='right',
                va='top', fontsize=8, color='#555555')
        ax.set(xscale='log', yscale='log', xlim=(8, 120), ylim=(1e-6, 1.5), xlabel='time per sample in a block of 16 [ns]',
               title=f'N = {n} (sampler only, 3.2 GHz)')
    axes[0].set_ylabel('fraction of blocks slower than this')
    axes[0].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG / 'fig4_timing_tail.png'); plt.close(fig)


def fig_perf(perf):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for alg in ('basic', 'trapezoid'):
        st = STYLE[alg]
        for mode, alpha, tag in (('precomputed', 1.0, 'sampler only'), ('inline', 0.45, 'sampler + PRNG')):
            s = perf[(perf.config_id.isin([cid(alg, n) for n in NS])) & (perf.uniform_mode == mode)].sort_values('N')
            axes[0].plot(s.N, s.cycles_per_sample, lw=2, ms=6, alpha=alpha, label=f'{NAME[alg]}, {tag}', **st)
            if mode == 'precomputed':
                axes[1].plot(s.N, s.branch_misses_per_sample, lw=2, ms=6, label=NAME[alg], **st)
    axes[0].set(xscale='log', xticks=NS, xticklabels=NS, xlabel='layers N', ylabel='CPU cycles per sample',
                title='Cost per sample (perf, CPU 7)')
    axes[1].set(xscale='log', xticks=NS, xticklabels=NS, xlabel='layers N', ylabel='branch misses per sample',
                title='Branch mispredictions per sample', ylim=(0, None))
    axes[1].axhline(0.5, color='#999999', lw=1, ls=':')
    axes[1].text(256, 0.47, 'random sign bit ≈ 0.5', ha='right', va='top', fontsize=8, color='#555555')
    axes[0].legend(frameon=False, fontsize=7)
    axes[1].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG / 'fig5_perf_counters.png'); plt.close(fig)


# ---------------------------------------------------------------- C: hardware model

def fig_model(hw):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    ax = axes[0]
    c = hw[hw.config_id == 'classical_N128']
    for lat, ls in ((10, ':'), (20, '--'), (40, '-.')):
        s = c[pd.to_numeric(c.op_latency_cycles, errors='coerce') == lat]
        ax.plot(s.utilization, s.fifo_depth, color=CLASSICAL, ls=ls, marker='s', mfc='white', lw=2, label=f'Classical, exp/log {lat} cycles')
    t = hw[(hw.config_id == 'trap_N128_H1_T2') & (hw.design == 'trapezoid_common_case')]
    ax.plot(t.utilization, t.fifo_depth, color=TRAP, marker='o', lw=2, label='Trapezoid H1/T2, common-case design')
    ax.set(yscale='log', xlabel='consumer demand / design mean rate', ylabel='FIFO depth [samples]',
           title='FIFO for empty < 1e-9 of demands (N=128)')
    ax.text(0.5, 0.012, 'Trapezoid worst-case design: no FIFO', transform=ax.transAxes, fontsize=8, color=TRAP)
    ax.legend(frameon=False, fontsize=8)
    ax = axes[1]
    for lat, ls in ((10, ':'), (20, '--'), (40, '-.')):
        s = hw[(hw.algorithm == 'basic') & (pd.to_numeric(hw.op_latency_cycles, errors='coerce') == lat) & (hw.utilization == 0.9)].sort_values('N')
        ax.plot(s.N, s.samples_per_cycle, color=CLASSICAL, ls=ls, marker='s', mfc='white', lw=2, label=f'Classical, {lat}-cycle exp/log')
    for design, ls, lab in (('trapezoid_worst_case', '-', 'worst-case'), ('trapezoid_common_case', '--', 'common-case')):
        s = hw[(hw.design == design) & (hw.utilization == 0.9) & hw.config_id.isin([cid('trapezoid', n) for n in NS])].sort_values('N')
        ax.plot(s.N, s.samples_per_cycle, color=TRAP, ls=ls, marker='o', lw=2, label=f'Trapezoid H1/T2, {lab}')
    ax.set(xscale='log', xticks=NS, xticklabels=NS, ylim=(0, 1.08), xlabel='layers N', ylabel='mean samples per clock',
           title='Throughput of one generator lane')
    ax.legend(frameon=False, fontsize=7, loc='lower right')
    fig.tight_layout()
    fig.savefig(FIG / 'fig6_hw_model.png'); plt.close(fig)


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    TAB.mkdir(parents=True, exist_ok=True)
    q, wl = read('quantization.csv'), read('word_length.csv')
    q['frac_bits'] = q.frac_bits.astype(str)
    hist, runs = read('timing_histograms.csv'), read('timing_runs.csv')
    runs = runs[runs.status == 'ok']
    perf, hw = read('perf_summary.csv'), read('hw_model.csv')
    fig_rounding(q, wl)
    fig_memory(wl)
    fig_uniforms(read('uniforms_per_sample_exact.csv'))
    fig_timing(hist, runs)
    fig_perf(perf)
    fig_model(hw)

    t = wl[wl.algorithm == 'trapezoid']
    key = dict(
        b_star_trapezoid_by_N=t.groupby('N').b_star.agg(['min', 'median', 'max']).to_dict('index'),
        timing_runs_ok=int(len(runs)), counters_multiplexed=int(runs.counters_multiplexed.sum()),
        checksums_match_exp13=int(runs.checksum_matches_exp13.sum()),
        cpus=sorted(int(c) for c in runs.cpu_reported.unique()),
        tsc_hz=float(runs.tsc_hz.median()), overhead_ticks=sorted(float(v) for v in runs.overhead_median_ticks.unique()))
    (TAB / 'key_numbers.json').write_text(json.dumps(key, indent=2, default=str))
    sel = [cid(a, n) for n in NS for a in ('basic', 'trapezoid')] + ['trap_N128_H0_T0', 'trap_N128_H4_T4', 'trap_N256_H4_T4']
    p = perf.set_index(['config_id', 'uniform_mode'])
    rows = []
    for c in sel:
        r = dict(config_id=c)
        for mode in ('precomputed', 'inline'):
            for col in ('median_ns_per_sample', 'cycles_per_sample', 'instructions_per_sample', 'ipc',
                        'branch_misses_per_sample', 'l1d_misses_per_sample'):
                r[f'{mode}_{col}'] = p.loc[(c, mode), col]
        rows.append(r)
    pd.DataFrame(rows).to_csv(TAB / 'perf_table.csv', index=False)
    print(json.dumps(key, indent=1, default=str))


if __name__ == '__main__':
    main()
