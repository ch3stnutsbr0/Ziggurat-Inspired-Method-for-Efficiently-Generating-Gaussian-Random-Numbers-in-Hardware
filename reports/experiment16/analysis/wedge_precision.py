"""Exact effect of the 32-bit wedge grid (Philox word-B reuse) against the Experiment 15 exact law.

With word-B reuse the wedge position is w + d*K/M, M = 2^32, K = |I1 - I2| for independent I1, I2
uniform on {0..M-1}; Experiment 15 models the ideal continuous wedge w + d*|U1 - U2|.
Per wedge, with v = (x - w)/d, j = floor(v*M), theta = v*M - j (closed form, no cancellation):
    F_M(v) - G(v) = ((M - j)(1 - 2 theta) + theta^2) / M^2,   G(v) = 2v - v^2
    E[K/M] = 1/3 - 1/(3 M^2),   E[(K/M)^2] = 1/6 - 1/(6 M^2)
so the CDF of |X| moves by at most P(wedge)/M and the moments by O(M^-2).

    .venv/bin/python -B reports/experiment16/analysis/wedge_precision.py
"""
import sys
sys.dont_write_bytecode = True
import csv
import tempfile
from pathlib import Path

import numpy as np
from scipy import stats

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'experiments'))
from utils import load_config  # noqa: E402
from experiment12 import build_exporter, terminal_entries  # noqa: E402
from experiment15 import ExactLaw  # noqa: E402

M = 2.0 ** 32
CONFIGS = [(n, 2, 1) for n in (8, 16, 32, 64, 128, 256)] + [(128, 1, 2)]
EXP15 = REPO / 'experiments/results/experiment15/exact_theory_all.csv'
OUT = REPO / 'reports/experiment16/tables/wedge_precision_vs_exp15.csv'


def delta_cdf_abs(x, ents):
    """Exact change of P(|X| <= x) caused by the 32-bit wedge grid."""
    out = np.zeros_like(x)
    for e in ents:
        v = (x - e['w']) / e['d']
        m = (v >= 0) & (v < 1)
        if not m.any():
            continue
        vm = v[m] * M
        j = np.floor(vm); th = vm - j
        out[m] += e['weight'] * (1 - e['a']) * ((M - j) * (1 - 2 * th) + th ** 2) / M ** 2
    return out


def main():
    cfg = load_config(REPO / 'experiments/experiment15.yaml')
    e15 = {r['config_id']: r for r in csv.DictReader(open(EXP15))}
    lo, hi = cfg['chi_square']['range']
    edges = np.linspace(lo, hi, cfg['chi_square']['bins'] + 1)
    q = np.diff(np.r_[0.0, stats.norm.cdf(edges), 1.0])
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        exe, _ = build_exporter(Path(tmp))
        for N, H, T in CONFIGS:
            ents = terminal_entries(exe, N, H, T)
            law = ExactLaw(ents)
            p_wedge = sum(e['weight'] * (1 - e['a']) for e in ents)
            # binned chi-square divergence, continuous wedge vs 32-bit wedge
            Fc = np.where(edges >= 0, 1 - 0.5 * law.survival(np.abs(edges)), 0.5 * law.survival(np.abs(edges)))
            dF = 0.5 * np.sign(edges) * delta_cdf_abs(np.abs(edges), ents)
            pc = np.diff(np.r_[0.0, Fc, 1.0]); pd = np.diff(np.r_[0.0, Fc + dF, 1.0])
            dc, dd = float(np.sum((pc - q) ** 2 / q)), float(np.sum((pd - q) ** 2 / q))
            # largest CDF change: wedge starts (v = 0) plus a fine grid over the wedge range
            xs = np.unique(np.r_[[e['w'] for e in ents], np.linspace(0, law.support, 200001)])
            ks_shift = float(np.max(np.abs(0.5 * delta_cdf_abs(xs, ents))))
            var_shift = sum(e['weight'] * (1 - e['a']) * (2 * e['w'] * e['d'] * (-1 / (3 * M ** 2))
                            + e['d'] ** 2 * (-1 / (6 * M ** 2))) for e in ents)
            r15 = e15[f'trap_N{N}_H{H}_T{T}']
            rows.append(dict(N=N, H=H, T=T, p_wedge=p_wedge, wedge_grid_max=max(e['d'] for e in ents) / M,
                             delta_binned_exp15=float(r15['delta_binned']), delta_binned_check=dc,
                             delta_binned_wedge32=dd, delta_relative_change=(dd - dc) / dc,
                             ks_exact_exp15=float(r15['ks_exact']), max_cdf_shift_wedge32=ks_shift,
                             cdf_shift_bound=0.5 * p_wedge / M, ks_shift_over_ks_exp15=ks_shift / float(r15['ks_exact']),
                             variance_error_exp15=float(r15['variance_error']), variance_shift_wedge32=var_shift))
            r = rows[-1]
            print(f"N={N} H{H}/T{T}: P(wedge)={p_wedge:.4%}  delta {dc:.6e} -> {dd:.6e} ({r['delta_relative_change']:+.1e})  "
                  f"max CDF shift {ks_shift:.2e} vs Exp15 KS {r['ks_exact_exp15']:.2e}  var shift {var_shift:.1e}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(f'wrote {OUT.relative_to(REPO)}')


if __name__ == '__main__':
    main()
