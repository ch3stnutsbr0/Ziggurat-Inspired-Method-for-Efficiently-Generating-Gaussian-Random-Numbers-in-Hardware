"""Experiment 15: exact theory of the Trapezoid sampler over the full N x H x T grid.

No random numbers are generated. The tables are exported from c/ziggurat_trapezoid.c (Experiment 12
exporter) and the exact output law (mixture of trapezoid densities) is analysed for every configuration
N in {8..256}, H, T in {0..4}. Key questions:
  1. Tail reach: how far into the tails is the output reliable (deterministic tolerance and sample-size
     dependent reach)?
  2. Refinement: how much do head (H) and tail (T) levels improve goodness, and where (|x| regions)?

The |X| density f is continuous and piecewise linear, so it is evaluated exactly at its breakpoints as a
sum of non-negative terms (no cancellation in the far tail) and interpolated linearly in between. Tail
masses are integrated from the right, so they stay accurate down to the support edge.

    .venv/bin/python -B experiments/experiment15.py [--config FILE] [--output-dir DIR]
"""
import sys
sys.dont_write_bytecode = True
import argparse
import csv
import json
import math
import platform
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'experiments'))
from utils import load_config  # noqa: E402
from experiment12 import build_exporter, terminal_entries, chi2_prediction, sha256  # noqa: E402


class ExactLaw:
    """Exact law of |X| for one configuration (piecewise-linear density on [0, support])."""

    def __init__(self, ents):
        self.ents = ents
        w = np.array([e['w'] for e in ents]); d = np.array([e['d'] for e in ents])
        c = np.array([e['weight'] for e in ents]) * 2.0 / (2 * w + d)        # height of each trapezoid
        self.w, self.d, self.c = w, d, c
        self.support = float(np.max(w + d))
        b = np.unique(np.r_[0.0, w, w + d])
        self.b = b
        self.fb = self._density_direct(b)
        # survival at breakpoints, integrated from the right (sum of positive pieces)
        piece = 0.5 * (self.fb[:-1] + self.fb[1:]) * np.diff(b)
        self.Sb = np.r_[np.cumsum(piece[::-1])[::-1], 0.0]
        self.mass = float(self.Sb[0])

    def _density_direct(self, x):
        out = np.empty_like(x)
        for k in range(0, len(x), 2048):
            xx = x[k:k + 2048, None]
            lin = np.where(self.d > 0, (self.w + self.d - xx) / np.where(self.d > 0, self.d, 1.0), 0.0)
            part = np.where(xx <= self.w, 1.0, np.where(xx < self.w + self.d, lin, 0.0))
            out[k:k + 2048] = part @ self.c
        return out

    def density(self, x):
        """f_|X|(x); exact (f is linear between breakpoints)."""
        x = np.asarray(x, float)
        return np.interp(x, self.b, self.fb, left=0.0, right=0.0)

    def survival(self, x):
        """P(|X| > x), exact."""
        x = np.asarray(x, float)
        j = np.clip(np.searchsorted(self.b, x, side='right') - 1, 0, len(self.b) - 2)
        fx = self.density(x)
        s = self.Sb[j + 1] + 0.5 * (fx + self.fb[j + 1]) * (self.b[j + 1] - x)
        return np.where(x >= self.support, 0.0, np.where(x <= 0, 1.0, s))


def gauss_nodes(law, cfg):
    """Quadrature nodes/weights on [0, support], each linear piece split to max_width."""
    xg, wg = np.polynomial.legendre.leggauss(cfg['quadrature']['order'])
    lo, hi = law.b[:-1], law.b[1:]
    k = np.maximum(1, np.ceil((hi - lo) / cfg['quadrature']['max_width']).astype(int))
    a = np.concatenate([lo[i] + (hi[i] - lo[i]) * np.arange(k[i]) / k[i] for i in range(len(lo))])
    h = np.concatenate([np.full(k[i], (hi[i] - lo[i]) / k[i]) for i in range(len(lo))])
    x = (a[:, None] + 0.5 * h[:, None] * (xg[None, :] + 1)).ravel()
    wt = (0.5 * h[:, None] * wg[None, :]).ravel()
    return x, wt


def binned_delta(law, cfg):
    lo, hi = cfg['chi_square']['range']
    e = np.linspace(lo, hi, cfg['chi_square']['bins'] + 1)
    F = np.where(e >= 0, 1 - 0.5 * law.survival(np.abs(e)), 0.5 * law.survival(np.abs(e)))
    p = np.diff(np.r_[0.0, F, 1.0])
    q = np.diff(np.r_[0.0, stats.norm.cdf(e), 1.0])
    return float(np.sum((p - q) ** 2 / q)), len(p) - 1


def analyse(law, cfg, z2):
    x, wt = gauss_nodes(law, cfg)
    g, phi = law.density(x) / 2, stats.norm.pdf(x)          # density of X on one side, and N(0,1)
    integrand = 2 * (g - phi) ** 2 / phi                        # both sides
    out = {}
    edges = cfg['regions']
    for lo, hi in zip(edges, edges[1:] + [math.inf]):
        m = (x >= lo) & (x < hi)
        part = float(np.sum(wt[m] * integrand[m]))
        if hi == math.inf or hi > law.support:                  # region beyond the support: (0 - phi)^2/phi
            part += 2 * float(stats.norm.sf(max(lo, law.support)))
        name = f'D_region_{lo}_{"inf" if hi == math.inf else hi}'
        out[name] = part
    out['D_beyond_support'] = 2 * float(stats.norm.sf(law.support))
    out['D_continuous'] = math.fsum(v for k, v in out.items() if k.startswith('D_region_'))
    out['total_variation'] = float(np.sum(wt * np.abs(g - phi))) + float(stats.norm.sf(law.support))  # 0.5*int|.|, both sides
    out['hellinger2'] = float(np.sum(wt * (np.sqrt(g) - np.sqrt(phi)) ** 2)) + float(stats.norm.sf(law.support))
    m2 = float(np.sum(wt * x ** 2 * law.density(x))); m4 = float(np.sum(wt * x ** 4 * law.density(x)))
    out.update(mass=float(np.sum(wt * law.density(x))), variance_error=m2 - 1, kurtosis_error=m4 / m2 ** 2 - 3,
               fourth_moment_error=m4 - 3)

    # KS distance on a fine grid plus every breakpoint
    xs = np.unique(np.r_[np.linspace(0, cfg['ks_grid']['max_x'], cfg['ks_grid']['points']), law.b])
    diff = (0.5 - 0.5 * law.survival(xs)) - (stats.norm.cdf(xs) - 0.5)
    i = int(np.argmax(np.abs(diff)))
    out.update(ks_exact=float(abs(diff[i])), ks_argmax_abs_x=float(xs[i]),
               ks_n_detect_approx=(stats.kstwobign.isf(cfg['significance_level']) / abs(diff[i])) ** 2)

    # tail reach
    tc = cfg['tail_curve']
    t = np.round(np.arange(0, tc['max_t'] + tc['step'] / 2, tc['step']), 9)
    p, q = law.survival(t), 2 * stats.norm.sf(t)
    r_surv = p / q
    r_dens = (law.density(t) / 2) / stats.norm.pdf(t)
    with np.errstate(divide='ignore', invalid='ignore'):
        n_det = np.where(p == q, np.inf, z2 * q * (1 - q) / (p - q) ** 2)   # tail-count test, 50% power
    n_det[t < tc['tail_start']] = np.inf                    # body/head errors are covered by D and KS
    for eps in cfg['reach_tolerances']:
        for name, r in (('survival', r_surv), ('density', r_dens)):
            bad = np.nonzero(np.abs(r - 1) > eps)[0]
            out[f'reach_{name}_eps{eps:g}'] = float(t[bad[0] - 1]) if len(bad) else float(t[-1])
    k = int(np.argmin(n_det))                                   # tightest tail-count test at |x| >= tail_start
    out.update(tail_budget_n=float(n_det[k]), tail_budget_log2=math.log2(n_det[k]), tail_budget_at_t=float(t[k]))
    for lg in cfg['sample_budgets_log2']:
        bad = np.nonzero(n_det <= 2.0 ** lg)[0]
        out[f'R_n2^{lg}'] = float(t[bad[0] - 1]) if len(bad) else math.inf
    for tt in (3, 4, 5, 6, 7):
        out[f'tail_ratio_{tt}'] = float(law.survival(np.array([tt]))[0] / (2 * stats.norm.sf(tt)))
    curve = dict(t=t[::tc['save_every']], survival=p[::tc['save_every']], normal_survival=q[::tc['save_every']],
                 survival_ratio=r_surv[::tc['save_every']], density_ratio=r_dens[::tc['save_every']],
                 n_detect_tail=n_det[::tc['save_every']])
    return out, curve


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_suffix('.yaml'))
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    cfg = load_config(args.config)
    if cfg.get('experiment_id') != 'experiment15':
        raise ValueError('experiment_id must be experiment15')
    out = (args.output_dir or REPO / cfg['output_dir']).resolve()
    if out.exists():
        sys.exit(f'{out} already exists; use --output-dir for a fresh run')
    alpha = cfg['significance_level']
    z2 = stats.norm.isf(alpha / 2) ** 2
    out.mkdir(parents=True)
    rows, curves = [], []
    grid = [(n, h, t) for n in cfg['layers'] for h in cfg['heads'] for t in cfg['tails']]
    with tempfile.TemporaryDirectory(prefix='experiment15-') as tmp:
        exe, build_cmd = build_exporter(Path(tmp))
        for k, (N, H, T) in enumerate(grid, 1):
            law = ExactLaw(terminal_entries(exe, N, H, T))
            delta, df = binned_delta(law, cfg)
            m, curve = analyse(law, cfg, z2)
            if abs(m['mass'] - 1) > 1e-9 or abs(law.mass - 1) > 1e-9:
                raise ValueError(f'mass {m["mass"]} / {law.mass} for N={N} H={H} T={T}')
            cid = f'trap_N{N}_H{H}_T{T}'
            pred = chi2_prediction(delta, df, 2 ** 25, alpha)
            rows.append(dict(config_id=cid, N=N, H=H, T=T, terminal_entries=len(law.ents),
                             table_values=(1 + H + T) * (5 * N + 2), support=law.support,
                             support_n_one_missing=1 / (2 * stats.norm.sf(law.support)),
                             delta_binned=delta, chi2_df=df, chi2_n_detect_50=pred['n_detect_50'],
                             chi2_n_detect_90=pred['n_detect_90'], **m))
            curves += [dict(config_id=cid, N=N, H=H, T=T, **{kk: v[i] for kk, v in curve.items()})
                       for i in range(len(curve['t']))]
            print(f'[{k}/{len(grid)}] {cid}: D={m["D_continuous"]:.3e} support={law.support:.3f} '
                  f'reach(1%)={m["reach_survival_eps0.01"]:.3f} tail budget=2^{m["tail_budget_log2"]:.1f}', flush=True)

    def write(name, data):
        with (out / name).open('x', newline='') as f:
            wr = csv.DictWriter(f, fieldnames=list(data[0]))
            wr.writeheader(); wr.writerows(data)

    write('exact_theory_all.csv', rows)
    write('tail_curves.csv', curves)
    git = lambda *a: subprocess.run(['git', '-C', str(REPO), *a], capture_output=True, text=True).stdout.strip()
    (out / 'metadata.json').write_text(json.dumps(dict(
        experiment_id='experiment15', created_utc=datetime.now(timezone.utc).isoformat(), config=cfg,
        method='exact piecewise-linear |X| density from c/ziggurat_trapezoid.c tables; no sampling',
        random_numbers_generated=0, exporter_build_command=build_cmd,
        sampler_source_sha256=sha256(REPO / 'c/ziggurat_trapezoid.c'),
        exporter_source_sha256=sha256(REPO / 'experiments/experiment12_dump_tables.c'),
        git_commit=git('rev-parse', 'HEAD'), git_dirty_files=len(git('status', '--porcelain').splitlines()),
        gcc=subprocess.run(['gcc', '--version'], capture_output=True, text=True).stdout.splitlines()[0],
        python=platform.python_version(), numpy=np.__version__, scipy=__import__('scipy').__version__,
        configurations=len(rows)), indent=2))
    print(f'\n{len(rows)} configurations; results in {out}')


if __name__ == '__main__':
    main()
