"""Exact effect of the shorter decision field in the one-block sampler (zt_gaussian_philox_1call).

The one-block layout puts all descent indices in word A, so the rectangle/wedge decision has
D = min(53, 63 - k*(1 + max(H, T))) bits instead of 53. Per terminal entry the rectangle
probability is a_D = ceil(a * 2^D) / 2^D, against a_53 for zt_gaussian_philox() and the ideal a of
the Experiment 15 law. Changing a by delta moves the CDF of |X| by
    delta * (R(x) - W(x)),   R = clamp(x / w, 0, 1),   W = 0 (x < w), 2v - v^2 (v = (x - w)/d), 1 (x > w + d)
which is computed exactly here (no sampling). Descent weights are unchanged (disjoint index fields).

    .venv/bin/python -B reports/experiment16/analysis/onecall_precision.py
"""
import sys
sys.dont_write_bytecode = True
import csv
import math
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'experiments'))
from experiment12 import build_exporter, terminal_entries  # noqa: E402

CONFIGS = [(n, h, t) for n in (8, 16, 32, 64, 128, 256) for h, t in ((1, 2), (2, 1), (4, 4))]
EXP15 = REPO / 'experiments/results/experiment15/exact_theory_all.csv'
OUT = REPO / 'reports/experiment16/tables/onecall_precision_vs_exp15.csv'


def decision_bits(n, h, t):
    k = int(math.log2(n))
    return min(53, 63 - k * (1 + max(h, t)))


def cdf_shift(x, ents, dbits):
    """Exact change of P(|X| <= x): D-bit thresholds against the ideal a (and against 53 bits)."""
    out_ideal = np.zeros_like(x); out_53 = np.zeros_like(x)
    for e in ents:
        w, d, a = e['w'], e['d'], e['a']
        aD = math.ceil(a * 2.0 ** dbits) / 2.0 ** dbits
        a53 = math.ceil(a * 2.0 ** 53) / 2.0 ** 53
        R = np.clip(x / w, 0, 1)
        v = np.clip((x - w) / d, 0, 1) if d > 0 else (x >= w).astype(float)
        diff = R - (2 * v - v * v)
        out_ideal += e['weight'] * (aD - a) * diff
        out_53 += e['weight'] * (aD - a53) * diff
    return out_ideal, out_53


def main():
    e15 = {r['config_id']: r for r in csv.DictReader(open(EXP15))}
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        exe, _ = build_exporter(Path(tmp))
        for N, H, T in CONFIGS:
            D = decision_bits(N, H, T)
            ents = terminal_entries(exe, N, H, T)
            support = max(e['w'] + e['d'] for e in ents)
            xs = np.unique(np.r_[[e['w'] for e in ents], np.linspace(0, support, 200001)])
            s_ideal, s_53 = cdf_shift(xs, ents, D)
            r15 = e15[f'trap_N{N}_H{H}_T{T}']
            ks15 = float(r15['ks_exact'])
            rows.append(dict(N=N, H=H, T=T, decision_bits=D, threshold_step=2.0 ** -D,
                             max_cdf_shift_vs_ideal=float(np.max(np.abs(0.5 * s_ideal))),
                             max_cdf_shift_vs_53bit=float(np.max(np.abs(0.5 * s_53))),
                             ks_exact_exp15=ks15,
                             shift_over_ks_exp15=float(np.max(np.abs(0.5 * s_ideal))) / ks15))
            r = rows[-1]
            print(f"N={N} H{H}/T{T}: D={D}  max CDF shift {r['max_cdf_shift_vs_ideal']:.2e} "
                  f"(vs 53-bit {r['max_cdf_shift_vs_53bit']:.2e})  Exp15 KS {ks15:.2e}  ratio {r['shift_over_ks_exp15']:.1e}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(f'wrote {OUT.relative_to(REPO)}')


if __name__ == '__main__':
    main()
