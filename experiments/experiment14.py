"""Experiment 14: memory, per-sample cost consistency and a hardware throughput model.

    .venv/bin/python -B experiments/experiment14.py --phase memory     # A:  table memory and word length
    .venv/bin/python -B experiments/experiment14.py --phase uniforms   # B1: uniforms per sample (exact + check)
    .venv/bin/python -B experiments/experiment14.py --phase timing     # B2: rdtscp + perf on the isolated CPU
    .venv/bin/python -B experiments/experiment14.py --phase summarize  # B2 summary tables (run after timing)
    .venv/bin/python -B experiments/experiment14.py --phase model      # C:  hardware throughput model
    .venv/bin/python -B experiments/experiment14.py --phase timing --dry-run

Results are CSV files; raw Gaussian samples are never written. See experiments/EXPERIMENT_14_README.md.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import fcntl
import itertools
import json
import math
import random
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
from scipy import special, stats

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'experiments'))
from utils import load_config  # noqa: E402
import experiment11 as e11  # noqa: E402
import experiment12 as e12  # noqa: E402

S2 = math.sqrt(2.0)
CLASSICAL_R = {8: 2.3383716982472524, 16: 2.6755367657376140, 32: 2.9613001212640190,   # c/ziggurat_basic.c
               64: 3.2136576271588960, 128: 3.442619855899, 256: 3.6541528853610088}
EXP13_RUNS = REPO / 'experiments/results/experiment13/performance_runs.csv'
HARNESS_SOURCE = REPO / 'experiments/experiment14_timing.c'


# ---------------------------------------------------------------- configurations

def config(algorithm, n, h=0, t=0):
    cid = f'classical_N{n}' if algorithm == 'basic' else f'trap_N{n}_H{h}_T{t}'
    return dict(config_id=cid, algorithm=algorithm, N=n, H=h, T=t)


def shortlist(cfg):
    s = cfg['shortlist']
    return [config('basic', n) for n in s['classical']] + [config('trapezoid', *x) for x in s['trapezoid']]


def full_grid(cfg):
    g = cfg['grid']
    return [config('basic', n) for n in g['layers']] + \
        [config('trapezoid', n, h, t) for n, h, t in itertools.product(g['layers'], g['heads'], g['tails'])]


def check_config(cfg):
    if cfg.get('experiment_id') != 'experiment14':
        raise ValueError('experiment_id must be experiment14')
    for n in cfg['shortlist']['classical']:
        if n not in CLASSICAL_R:
            raise ValueError(f'Classical N={n} is not supported by c/ziggurat_basic.c')
    for n, h, t in cfg['shortlist']['trapezoid']:
        if n not in cfg['grid']['layers'] or h not in cfg['grid']['heads'] or t not in cfg['grid']['tails']:
            raise ValueError(f'shortlist entry {[n, h, t]} is not in the grid')


# ---------------------------------------------------------------- Trapezoid output law (general a)

class Exporter:
    """Experiment 12's table exporter, built once per session."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='experiment14-')
        self.exe, _ = e12.build_exporter(Path(self.tmp.name))
        return self

    def __exit__(self, *exc):
        self.tmp.cleanup()

    def entries(self, n, h, t):
        ents = e12.terminal_entries(self.exe, n, h, t)
        return {k: np.array([e[k] for e in ents], float) for k in ('weight', 'w', 'd', 'a', 'level')}


def quantize(v, b):
    return np.round(np.asarray(v, float) * 2.0 ** b) / 2.0 ** b


def trap_quantized(e, b):
    q = dict(e)
    q['a'] = np.clip(quantize(e['a'], b), 0.0, 1.0)
    q['w'], q['d'] = quantize(e['w'], b), quantize(e['d'], b)
    return q


def _chunks(x, m):
    step = max(1, 20_000_000 // max(m, 1))
    for s in range(0, len(x), step):
        yield s, x[s:s + step, None]


def trap_cdf_abs(x, e):
    """P(|X| <= x): rectangle on [0, w] with probability a, else w + d*|U1-U2| (density 2(1-t) on [0, 1]).

    Equals Experiment 12's cdf_abs when a = 2w/(2w+d); here a may be rounded independently."""
    x = np.asarray(x, float)
    out = np.zeros_like(x)
    w, d, a, wt = e['w'], e['d'], e['a'], e['weight']
    for s, xs in _chunks(x, len(w)):
        with np.errstate(divide='ignore', invalid='ignore'):
            rect = np.where(w > 0, np.clip(xs / w, 0, 1), (xs >= 0) * 1.0)
            tt = np.where(d > 0, np.clip((xs - w) / d, 0, 1), (xs >= w) * 1.0)
        out[s:s + len(xs)] = ((a * rect + (1 - a) * (2 * tt - tt * tt)) * wt).sum(1)
    return out


def trap_cdf_abs_discrete(x, e, k):
    """Same law with k-bit uniforms j/2^k, j = 0..2^k-1 (the C code uses k = 53)."""
    x = np.asarray(x, float)
    out = np.zeros_like(x)
    K = 2.0 ** k
    w, d, wt = e['w'], e['d'], e['weight']
    a = np.minimum(np.ceil(e['a'] * K) / K, 1.0)              # P(u < a) for u on the k-bit grid
    for s, xs in _chunks(x, len(w)):
        with np.errstate(divide='ignore', invalid='ignore'):
            rect = np.where(w > 0, np.minimum(np.floor(xs * K / w) + 1, K) / K, 1.0)
            m = np.where(xs >= w, np.minimum(np.floor((xs - w) * K / np.where(d > 0, d, 1)), K - 1), -1)
            tp = m / K
            tri = np.where(m < 0, 0.0, np.where(d > 0, 1 / K + 2 * tp - tp * tp - tp / K, 1.0))
        out[s:s + len(xs)] = ((a * rect + (1 - a) * tri) * wt).sum(1)
    return out


def trap_second_moment(e):
    w, d, a = e['w'], e['d'], e['a']
    return float(np.sum(e['weight'] * (a * w * w / 3 + (1 - a) * (w * w + 2 * w * d / 3 + d * d / 6))))


def trap_breaks(e):
    return np.r_[e['w'], e['w'] + e['d']]


# ---------------------------------------------------------------- Classical output law (rounded tables)

def classical_tables(n):
    """The tables of c/ziggurat_basic.c build_tables(); y is exp(-x^2/2), unnormalized."""
    r = CLASSICAL_R[n]
    tail = math.sqrt(math.pi / 2) * math.erfc(r / S2)
    rect = r * math.exp(-r * r / 2)
    area = rect + tail
    x, y = [r], [math.exp(-r * r / 2)]
    for i in range(1, n):
        h = y[-1] + area / x[-1]
        if i == n - 1 and h > 1.0:
            h = 1.0
        y.append(h)
        x.append(math.sqrt(max(0.0, -2 * math.log(h))))
    return dict(r=r, p=rect / area, x=np.array(x), y=np.array(y))


def classical_quantized(tb, b):
    x = quantize(tb['x'], b)
    return dict(r=float(x[0]), p=float(np.clip(quantize(tb['p'], b), 0, 1)), x=x,
                y=np.clip(quantize(tb['y'], b), 0.0, 1.0))


def _gauss_int(a, b):
    """Integral of exp(-m^2/2) over [a, b], a <= b, via erfc (no cancellation in the tail)."""
    return math.sqrt(math.pi / 2) * (special.erfc(np.asarray(a) / S2) - special.erfc(np.asarray(b) / S2))


def wedge_int(s, t, lo, hi):
    """Integral over m in [s, t] of P(h <= exp(-m^2/2)) for h uniform on [lo, hi] (the wedge test)."""
    t = np.maximum(np.asarray(t, float), s)
    m_lo = math.sqrt(-2 * math.log(lo)) if lo > 0 else math.inf   # accept probability 0 beyond
    if hi <= lo:                                                   # rounded flat strip: accept iff f >= lo
        return np.clip(np.minimum(t, m_lo) - s, 0, None)
    m_hi = math.sqrt(-2 * math.log(hi)) if hi < 1 else 0.0         # accept probability 1 below
    ones = np.clip(np.minimum(t, m_hi) - s, 0, None)
    a = max(s, m_hi)
    b = np.maximum(np.minimum(t, m_lo), a)
    return ones + (_gauss_int(a, b) - lo * (b - a)) / (hi - lo)


def classical_layers(tb):
    """Per layer i >= 1: outer width x[i-1], inner edge, accepted wedge length."""
    x, y = tb['x'], tb['y']
    out = []
    for i in range(1, len(x)):
        xo = x[i - 1]
        inner = min(x[i], xo)
        lo, hi = sorted((y[i - 1], y[i]))
        out.append((xo, inner, lo, hi, float(wedge_int(inner, xo, lo, hi))))
    return out


def classical_cdf_abs(z, tb):
    """Exact P(|X| <= z) for c/ziggurat_basic.c with the given (possibly rounded) tables.

    One attempt picks a layer with probability 1/N; layer 0 returns a rectangle (prob p) or an exact tail
    sample beyond r; layer i >= 1 returns c ~ U[0, x[i-1]] if c <= x[i] or the wedge test accepts, and
    otherwise restarts. The output law is the accepted sub-density, renormalized."""
    z = np.asarray(z, float)
    r, p = tb['r'], tb['p']
    er = special.erfc(r / S2)
    num = p * np.clip(z / r, 0, 1) + (1 - p) * np.where(z > r, (er - special.erfc(np.maximum(z, r) / S2)) / er, 0.0)
    tot = 1.0
    for xo, inner, lo, hi, acc in classical_layers(tb):
        if xo <= 0:
            num, tot = num + (z >= 0), tot + 1.0
            continue
        num = num + (np.clip(np.minimum(z, inner), 0, None) + wedge_int(inner, np.minimum(z, xo), lo, hi)) / xo
        tot += (inner + acc) / xo
    return num / tot


# ---------------------------------------------------------------- distribution metrics

def chi2_edges(cfg):
    lo, hi = cfg['chi_square']['range']
    return np.r_[-np.inf, np.linspace(lo, hi, cfg['chi_square']['bins'] + 1), np.inf]


def delta_of(cdf_abs, cfg):
    edges = chi2_edges(cfg)
    inner = edges[1:-1]
    fx = 0.5 + 0.5 * np.sign(inner) * cdf_abs(np.abs(inner))
    p = np.diff(np.r_[0.0, fx, 1.0])
    q = np.diff(stats.norm.cdf(edges))
    return float(np.sum((p - q) ** 2 / q))


def ks_of(cdf_abs, breaks, cfg):
    g = cfg['memory']['ks_grid']
    breaks = np.asarray(breaks, float)
    xs = np.unique(np.r_[np.linspace(0.0, g['max_x'], g['points']), breaks[(breaks >= 0) & (breaks <= g['max_x'])]])
    diff = 0.5 * cdf_abs(xs) - (stats.norm.cdf(xs) - 0.5)
    i = int(np.argmax(np.abs(diff)))
    return float(abs(diff[i])), float(xs[i])


def rel(v, ref):
    return abs(v / ref - 1.0) if ref else math.nan


def smallest_ok(values):
    """Smallest b such that the criterion holds for b and every larger b in the list."""
    best = None
    for b, ok in sorted(values, reverse=True):
        if not ok:
            break
        best = b
    return best


# ---------------------------------------------------------------- A: memory and word length

def table_values(c):
    if c['algorithm'] == 'basic':
        return dict(a=0, w=0, d=0, x=c['N'], y=c['N'], p=1)
    m = (1 + c['H'] + c['T']) * c['N']
    return dict(a=m, w=m, d=m, x=0, y=0, p=0)


def table_bits(c, b, cfg):
    ib = cfg['memory']['integer_bits']
    return sum(n * (ib[k] + b) for k, n in table_values(c).items())


def phase_memory(cfg, out):
    bits = cfg['memory']['fraction_bits']
    tol = cfg['memory']['tolerance']
    short = {c['config_id'] for c in shortlist(cfg)}
    grid = full_grid(cfg)

    rows = []
    for c in grid:
        values = sum(table_values(c).values())
        rows.append(dict(c, frac_bits='double', values=values, bits=64 * values, kib=64 * values / 8192))
        for b in bits:
            tb = table_bits(c, b, cfg)
            rows.append(dict(c, frac_bits=b, values=values, bits=tb, kib=tb / 8192))
    e11.write_csv_atomic(out / 'table_memory.csv', list(rows[0]), rows)
    print(f'table_memory.csv: {len(rows)} rows')

    qrows, wl, ref = [], [], {}
    with Exporter() as ex:
        ents = {}
        for c in grid:
            if c['algorithm'] != 'trapezoid':
                continue
            e = ents[c['config_id']] = ex.entries(c['N'], c['H'], c['T'])
            full_ks = c['config_id'] in short
            d0 = delta_of(lambda z: trap_cdf_abs(z, e), cfg)
            k0, kx0 = ks_of(lambda z: trap_cdf_abs(z, e), trap_breaks(e), cfg) if full_ks else (math.nan, math.nan)
            m0 = trap_second_moment(e)
            base = dict(c, frac_bits='double', delta=d0, delta_rel_change=0.0, ks=k0, ks_argmax_abs_x=kx0,
                        ks_rel_change=0.0 if full_ks else math.nan, support=float(np.max(e['w'] + e['d'])),
                        variance_error=m0 - 1.0, accept_probability=1.0)
            qrows.append(base)
            okd, okk = [], []
            for b in bits:
                q = trap_quantized(e, b)
                d = delta_of(lambda z: trap_cdf_abs(z, q), cfg)
                k, kx = ks_of(lambda z: trap_cdf_abs(z, q), trap_breaks(q), cfg) if full_ks else (math.nan, math.nan)
                qrows.append(dict(c, frac_bits=b, delta=d, delta_rel_change=rel(d, d0), ks=k, ks_argmax_abs_x=kx,
                                  ks_rel_change=rel(k, k0) if full_ks else math.nan,
                                  support=float(np.max(q['w'] + q['d'])), variance_error=trap_second_moment(q) - 1.0,
                                  accept_probability=1.0))
                okd.append((b, rel(d, d0) < tol))
                if full_ks:
                    okk.append((b, rel(k, k0) < tol))
            bd, bk = smallest_ok(okd), smallest_ok(okk) if full_ks else None
            bstar = None if bd is None or (full_ks and bk is None) else max(bd, bk or 0)
            ref[c['config_id']] = (d0, k0)
            wl.append(dict(c, rule=f'rounding changes delta{" and KS" if full_ks else ""} by < {tol:.0%}',
                           reference_config='', delta_double=d0, ks_double=k0, b_star_delta=bd, b_star_ks=bk,
                           b_match=None, b_star=bstar, bits_at_b_star=table_bits(c, bstar, cfg) if bstar else None))
            if full_ks:
                print(f"{c['config_id']}: delta={d0:.3e} KS={k0:.3e} b*={bstar}")

    _check_against_experiment12(qrows)

    for c in grid:
        if c['algorithm'] != 'basic':
            continue
        tb = classical_tables(c['N'])
        tref = f"trap_N{c['N']}_H1_T2"
        dT, kT = ref[tref]
        crow = []
        for b in ['double'] + bits:
            q = tb if b == 'double' else classical_quantized(tb, b)
            breaks = np.r_[q['x'], q['r']]
            d = delta_of(lambda z: classical_cdf_abs(z, q), cfg)
            k, kx = ks_of(lambda z: classical_cdf_abs(z, q), breaks, cfg)
            acc = 1.0 / c['N'] * (1 + sum((inner + a) / xo for xo, inner, lo, hi, a in classical_layers(q) if xo > 0))
            row = dict(c, frac_bits=b, delta=d, delta_rel_change=math.nan, ks=k, ks_argmax_abs_x=kx,
                       ks_rel_change=math.nan, support=math.inf, variance_error=math.nan, accept_probability=acc)
            qrows.append(row)
            crow.append(row)
        match = smallest_ok([(r['frac_bits'], r['delta'] <= dT and r['ks'] <= kT) for r in crow[1:]])
        negl = smallest_ok([(r['frac_bits'], r['delta'] <= tol * dT and r['ks'] <= tol * kT) for r in crow[1:]])
        wl.append(dict(c, rule=f'rounding error < {tol:.0%} of {tref} (b_match: equal to it)', reference_config=tref,
                       delta_double=crow[0]['delta'], ks_double=crow[0]['ks'], b_star_delta=None, b_star_ks=None,
                       b_match=match, b_star=negl, bits_at_b_star=table_bits(c, negl, cfg) if negl else None))
        print(f"{c['config_id']}: unrounded delta={crow[0]['delta']:.2e} KS={crow[0]['ks']:.2e}; "
              f"b_match={match} b*={negl}")
    e11.write_csv_atomic(out / 'quantization.csv', list(qrows[0]), qrows)
    e11.write_csv_atomic(out / 'word_length.csv', list(wl[0]), wl)

    urows = []
    with Exporter() as ex:
        for c in shortlist(cfg):
            for k in cfg['memory']['uniform_bits']:
                if c['algorithm'] == 'trapezoid':
                    e = ex.entries(c['N'], c['H'], c['T'])
                    d0, k0 = ref[c['config_id']]
                    d = delta_of(lambda z: trap_cdf_abs_discrete(z, e, k), cfg)
                    kg, _ = ks_of(lambda z: trap_cdf_abs_discrete(z, e, k), trap_breaks(e), cfg)
                    support = float(np.max(e['w'] + e['d'] * (1 - 2.0 ** -k)))
                    urows.append(dict(c, uniform_bits=k, delta=d, delta_rel_change=rel(d, d0), ks_grid=kg,
                                      ks_upper_bound=k0 + 1.5 * 2.0 ** -k, max_lattice_step=float(np.max(np.r_[e['w'], e['d']])) / 2 ** k,
                                      support=support, mass_beyond_support=2 * stats.norm.sf(support)))
                else:
                    r = CLASSICAL_R[c['N']]
                    xt = min(k * math.log(2) / r, math.sqrt(2 * k * math.log(2)))
                    urows.append(dict(c, uniform_bits=k, delta=math.nan, delta_rel_change=math.nan, ks_grid=math.nan,
                                      ks_upper_bound=math.nan, max_lattice_step=r / 2 ** k, support=r + xt,
                                      mass_beyond_support=2 * stats.norm.sf(r + xt)))
    e11.write_csv_atomic(out / 'uniform_bits.csv', list(urows[0]), urows)
    print('quantization.csv, word_length.csv, uniform_bits.csv written')


def _check_against_experiment12(qrows):
    """The general-a law must reproduce Experiment 12's delta for the unrounded tables."""
    import csv
    ref = {r['config_id']: float(r['delta_exact'])
           for r in csv.DictReader(open(REPO / 'experiments/results/experiment12/model_validation_all.csv'))}
    worst = max(rel(r['delta'], ref[r['config_id']]) for r in qrows if r['frac_bits'] == 'double' and r['config_id'] in ref)
    if worst > 1e-6:                         # the Experiment 12 CSV stores about 10 significant digits
        raise RuntimeError(f'unrounded delta differs from Experiment 12 by {worst:.2e} (relative)')
    print(f'check: unrounded delta matches Experiment 12 (max relative difference {worst:.1e})')


# ---------------------------------------------------------------- B1: uniforms per sample (exact)

def trap_paths(e):
    levels = e['level'].astype(int)
    out = []
    for lv in range(levels.max() + 1):
        m = levels == lv
        pl = float(e['weight'][m].sum())
        out.append(dict(level=lv, probability=pl, rect_given_level=float((e['weight'][m] * e['a'][m]).sum() / pl)))
    return out


def classical_paths(tb):
    n = len(tb['x'])
    fast = wedge = wedge_acc = 0.0
    for xo, inner, lo, hi, acc in classical_layers(tb):
        fast += inner / xo / n
        wedge += (1 - inner / xo) / n
        wedge_acc += acc / xo / n
    r = tb['r']
    return dict(fast=fast, base_rect=tb['p'] / n, base_tail=(1 - tb['p']) / n, wedge_accept=wedge_acc,
                wedge_reject=wedge - wedge_acc, tail_try_accept=r * math.sqrt(math.pi / 2) * special.erfcx(r / S2))


def renewal_pmf(accept, reject_prob, reject_cost, extra, eps):
    """pmf of extra + reject_cost*K + C, with K rejections (prob reject_prob each) before an accepted attempt
    of cost C ~ accept (sub-pmf over cost, summing to 1 - reject_prob)."""
    accept = np.asarray(accept, float)
    kmax = 0 if reject_prob <= 0 else int(math.ceil(math.log(eps) / math.log(reject_prob))) + 1
    out = np.zeros(len(accept) + extra + reject_cost * kmax + 1)
    for k in range(kmax + 1):
        s = extra + reject_cost * k
        out[s:s + len(accept)] += reject_prob ** k * accept
    return out


def classical_cost_pmf(P, costs, eps):
    """costs: fast, rect, wedge (accepted or rejected attempt), tail_base, tail_per_try, extra."""
    q = P['tail_try_accept']
    tmax = int(math.ceil(math.log(eps) / math.log(1 - q))) + 1
    top = max(costs['fast'], costs['rect'], costs['wedge'], costs['tail_base'] + costs['tail_per_try'] * tmax)
    acc = np.zeros(top + 1)
    acc[costs['fast']] += P['fast']
    acc[costs['rect']] += P['base_rect']
    acc[costs['wedge']] += P['wedge_accept']
    for t in range(1, tmax + 1):
        acc[costs['tail_base'] + costs['tail_per_try'] * t] += P['base_tail'] * (1 - q) ** (t - 1) * q
    return renewal_pmf(acc, P['wedge_reject'], costs['wedge'], costs['extra'], eps)


def classical_mean(P, costs):
    q, R = P['tail_try_accept'], P['wedge_reject']
    e_acc = (P['fast'] * costs['fast'] + P['base_rect'] * costs['rect'] + P['wedge_accept'] * costs['wedge']
             + P['base_tail'] * (costs['tail_base'] + costs['tail_per_try'] / q))
    return costs['extra'] + (R * costs['wedge'] + e_acc) / (1 - R)


def trap_cost_pmf(paths, per_level, rect, tri, extra):
    top = extra + per_level * (len(paths) - 1) + max(rect, tri)
    pmf = np.zeros(top + 1)
    for p in paths:
        base = extra + per_level * p['level']
        pmf[base + rect] += p['probability'] * p['rect_given_level']
        pmf[base + tri] += p['probability'] * (1 - p['rect_given_level'])
    return pmf


UNIFORM_COSTS = dict(fast=2, rect=3, wedge=3, tail_base=2, tail_per_try=2, extra=1)   # Classical, incl. sign


def uniform_pmf(c, paths, eps):
    if c['algorithm'] == 'basic':
        return classical_cost_pmf(paths, UNIFORM_COSTS, eps), classical_mean(paths, UNIFORM_COSTS)
    pmf = trap_cost_pmf(paths, per_level=1, rect=3, tri=4, extra=1)    # index draws, a-test, 1 or 2, sign
    return pmf, float(np.dot(np.arange(len(pmf)), pmf))


def pmf_summary(pmf, mean):
    cdf = np.cumsum(pmf)
    q = lambda p: int(np.searchsorted(cdf, p - 1e-15))
    sd = math.sqrt(max(0.0, float(np.dot(np.arange(len(pmf)) ** 2, pmf)) - mean ** 2))
    return dict(mean=mean, sd=sd, min=int(np.argmax(pmf > 0)), p50=q(0.5), p99=q(0.99), p99_9999=q(1 - 1e-6),
                max_listed=int(np.nonzero(pmf)[0].max()))


def phase_uniforms(cfg, out, harness):
    import csv
    eps = cfg['uniforms']['truncation']
    exp13 = {}
    for r in csv.DictReader(open(EXP13_RUNS)):
        if r['seed'] == '1' and r['status'] == 'ok':
            exp13[r['config_id']] = (float(r['prng_calls_per_sample']), r['checksum'])
    path_rows, pmf_rows, summary = [], [], []
    with Exporter() as ex:
        for c in shortlist(cfg):
            if c['algorithm'] == 'basic':
                P = classical_paths(classical_tables(c['N']))
                for k, v in P.items():
                    path_rows.append(dict(config_id=c['config_id'], algorithm='basic', N=c['N'], H=0, T=0,
                                          quantity=k, level='', value=v))
            else:
                P = trap_paths(ex.entries(c['N'], c['H'], c['T']))
                for p in P:
                    for k in ('probability', 'rect_given_level'):
                        path_rows.append(dict(config_id=c['config_id'], algorithm='trapezoid', N=c['N'], H=c['H'],
                                              T=c['T'], quantity=k, level=p['level'], value=p[k]))
            pmf, mean = uniform_pmf(c, P, eps)
            for u in np.nonzero(pmf > 0)[0]:
                pmf_rows.append(dict(config_id=c['config_id'], uniforms=int(u), probability=float(pmf[u])))

            argv = [str(harness), '--algorithm', c['algorithm'], '--layers', str(c['N']), '--seed', str(cfg['uniforms']['seed']),
                    '--samples', str(cfg['samples']), '--uniform-mode', 'precomputed',
                    '--uniform-buffer-bytes', str(cfg['uniforms']['uniform_buffer_bytes']), '--counts']
            if c['algorithm'] == 'trapezoid':
                argv += ['--head', str(c['H']), '--tail', str(c['T'])]
            res = subprocess.run(argv, capture_output=True, text=True)
            if res.returncode:
                raise RuntimeError(f"harness failed for {c['config_id']}: {res.stderr.strip()}")
            counts = next(json.loads(l) for l in res.stdout.splitlines() if '"kind":"counts"' in l)
            obs = np.array(counts['hist'], float)
            n = obs.sum()
            exp = np.zeros_like(obs)
            m = min(len(pmf), len(obs))
            exp[:m] = pmf[:m] * n
            exp[-1] += max(0.0, 1 - pmf[:m].sum()) * n
            keep = exp >= 5                                   # pool cells with < 5 expected into one
            o = np.r_[obs[keep], obs[~keep].sum()]
            x = np.r_[exp[keep], exp[~keep].sum()]
            if x[-1] < 5:
                o, x = o[:-1], x[:-1]
                o[-1] += obs[~keep].sum()
                x[-1] += exp[~keep].sum()
            chi2 = float(np.sum((o - x) ** 2 / x))
            p_value = float(stats.chi2.sf(chi2, len(o) - 1))
            e13_mean, e13_sum = exp13.get(c['config_id'], (math.nan, ''))
            observed_mean = counts['uniforms_total'] / n
            row = dict(c, **pmf_summary(pmf, mean), observed_mean=observed_mean,
                       observed_max=int(np.nonzero(obs)[0].max()), exp13_prng_calls_per_sample=e13_mean,
                       count_chi2=chi2, count_chi2_df=len(o) - 1, count_p_value=p_value,
                       checksum=repr(counts['checksum']),
                       checksum_matches_exp13=int(e13_sum != '' and float(e13_sum) == counts['checksum']))
            summary.append(row)
            print(f"{c['config_id']}: uniforms/sample exact {mean:.6f}, observed {observed_mean:.6f} "
                  f"(Exp 13 {e13_mean:.6f}); count chi2 p={p_value:.3f}; checksum match={row['checksum_matches_exp13']}")
    e11.write_csv_atomic(out / 'path_probabilities.csv', list(path_rows[0]), path_rows)
    e11.write_csv_atomic(out / 'uniforms_per_sample_exact.csv', list(pmf_rows[0]), pmf_rows)
    e11.write_csv_atomic(out / 'uniforms_summary.csv', list(summary[0]), summary)


def read_paths(out, cfg):
    import csv
    raw = {}
    for r in csv.DictReader(open(out / 'path_probabilities.csv')):
        raw.setdefault(r['config_id'], []).append(r)
    paths = {}
    for cid, rows in raw.items():
        if rows[0]['algorithm'] == 'basic':
            paths[cid] = {r['quantity']: float(r['value']) for r in rows}
        else:
            lv = {}
            for r in rows:
                lv.setdefault(int(r['level']), {})[r['quantity']] = float(r['value'])
            paths[cid] = [dict(level=k, **v) for k, v in sorted(lv.items())]
    return paths


# ---------------------------------------------------------------- B2: timing

RUN_FIELDS = ['config_id', 'algorithm', 'N', 'H', 'T', 'uniform_mode', 'seed', 'repetition', 'run_order', 'status',
              'returncode', 'cpu_reported', 'tsc_hz', 'samples', 'time_s', 'ns_per_sample', 'msamples_per_s',
              'cycles', 'instructions', 'branches', 'branch_misses', 'cycles_b', 'l1d_loads', 'l1d_misses',
              'counters_multiplexed', 'uniforms', 'checksum', 'checksum_matches_exp13', 'overhead_median_ticks',
              'process_wall_s', 'cpu_scaling_khz_before', 'started_utc', 'error']
HIST_FIELDS = ['config_id', 'uniform_mode', 'seed', 'repetition', 'block', 'ticks', 'count']
JOINT_FIELDS = ['config_id', 'uniform_mode', 'seed', 'repetition', 'uniforms', 'ticks', 'count']


def build_harness(cfg):
    exe = REPO / cfg['harness']
    sources = [s for s in (REPO / 'c/Makefile').read_text().split('SOURCES = ', 1)[1].splitlines()[0].split()
               if s != 'benchmark.c']
    deps = [HARNESS_SOURCE] + list((REPO / 'c').glob('*.[ch]'))
    if exe.exists() and exe.stat().st_mtime >= max(p.stat().st_mtime for p in deps):
        return exe
    cmd = ['gcc', '-std=c11', '-Wall', '-Wextra', '-pedantic', '-O2', '-I', str(REPO / 'c'), str(HARNESS_SOURCE),
           *[str(REPO / 'c' / s) for s in sources], '-o', str(exe), '-lm']
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode or done.stderr:
        raise RuntimeError(f'harness build failed:\n{done.stderr}')
    print(f'built {exe.relative_to(REPO)}')
    return exe


def check_machine(cfg):
    t = cfg['timing']
    problems = []
    isolated = e11.read('/sys/devices/system/cpu/isolated')
    if t['require_isolation'] and t['cpu'] not in e11.cpulist(isolated):
        problems.append(f"CPU {t['cpu']} is not isolated (isolated = '{isolated}')")
    boost = e11.read('/sys/devices/system/cpu/cpufreq/boost')
    if t.get('require_boost') is not None and boost != str(t['require_boost']):
        problems.append(f"boost is '{boost}', config requires {t['require_boost']}")
    paranoid = e11.read('/proc/sys/kernel/perf_event_paranoid')
    if int(paranoid) > t['max_perf_event_paranoid']:
        problems.append(f"perf_event_paranoid is {paranoid}; run: sudo sysctl kernel.perf_event_paranoid=1")
    if problems:
        sys.exit('machine not ready for timing:\n  ' + '\n  '.join(problems) + '\nSee EXPERIMENT_14_README.md.')


def timing_jobs(cfg):
    t = cfg['timing']
    jobs = []
    for rep in range(1, t['repetitions'] + 1):
        order = [(c, m, s) for c in shortlist(cfg) for m in t['uniform_modes'] for s in t['seeds']]
        random.Random(t['shuffle_seed'] + rep).shuffle(order)
        jobs += [(c, m, s, rep, i) for i, (c, m, s) in enumerate(order, 1)]
    return jobs


def harness_argv(cfg, harness, c, mode, seed):
    t = cfg['timing']
    argv = ['taskset', '-c', str(t['cpu']), str(harness), '--algorithm', c['algorithm'], '--layers', str(c['N']),
            '--seed', str(seed), '--samples', str(cfg['samples']), '--uniform-mode', mode,
            '--uniform-buffer-bytes', str(t['uniform_buffer_bytes']), '--perf',
            '--blocks', ','.join(map(str, t['blocks']))]
    if mode == 'precomputed':
        argv.append('--counts')
    if c['algorithm'] == 'trapezoid':
        argv += ['--head', str(c['H']), '--tail', str(c['T'])]
    return argv


def hist_median(bins):
    v = np.array([b[0] for b in bins], float)
    n = np.array([b[1] for b in bins], float)
    return float(v[np.searchsorted(np.cumsum(n), n.sum() / 2)])


def phase_timing(cfg, out, harness, config_path):
    import csv
    check_machine(cfg)
    exp13 = {r['config_id']: r['checksum'] for r in csv.DictReader(open(EXP13_RUNS)) if r['seed'] == '1' and r['status'] == 'ok'}
    runs = e11.CsvLog(out / 'timing_runs.csv', RUN_FIELDS)
    hists = e11.CsvLog(out / 'timing_histograms.csv', HIST_FIELDS)
    joints = e11.CsvLog(out / 'timing_by_uniforms.csv', JOINT_FIELDS)
    env = e11.CsvLog(out / 'environment.csv', e11.ENV_FIELDS)
    session = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    env_cfg = dict(performance=dict(cpu=cfg['timing']['cpu']))
    log_env = lambda event: (e11.log_environment(env, session, event, env_cfg, harness, config_path),
                             env.write(dict(session=session, event=event, utc=e11.now(), key='perf_event_paranoid',
                                            value=e11.read('/proc/sys/kernel/perf_event_paranoid'))))
    log_env('session_start')
    done = {(r['config_id'], r['uniform_mode'], r['seed'], r['repetition']) for r in runs.rows if r['status'] == 'ok'}
    jobs = timing_jobs(cfg)
    cpu = cfg['timing']['cpu']
    start_all = time.monotonic()
    for k, (c, mode, seed, rep, order) in enumerate(jobs, 1):
        key = (c['config_id'], mode, str(seed), str(rep))
        if key in done:
            continue
        row = dict(c, uniform_mode=mode, seed=seed, repetition=rep, run_order=order, samples=cfg['samples'],
                   cpu_scaling_khz_before=e11.read(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_cur_freq'),
                   started_utc=e11.now())
        t0 = time.monotonic()
        res = subprocess.run(harness_argv(cfg, harness, c, mode, seed), capture_output=True, text=True)
        row.update(returncode=res.returncode, process_wall_s=round(time.monotonic() - t0, 3))
        try:
            if res.returncode:
                raise RuntimeError(res.stderr.strip() or f'exit {res.returncode}')
            lines = [json.loads(l) for l in res.stdout.splitlines() if l.startswith('{')]
            meta = next(l for l in lines if l['kind'] == 'meta')
            perf = {l['group']: l for l in lines if l['kind'] == 'perf'}
            if any('error' in p for p in perf.values()):
                raise RuntimeError('; '.join(p['error'] for p in perf.values() if 'error' in p))
            a, b = perf['a'], perf['b']
            sums = {a['checksum'], b['checksum']} | {l['checksum'] for l in lines if l['kind'] == 'blocks'}
            if len(sums) != 1:
                raise RuntimeError(f'checksums differ between passes: {sorted(sums)}')
            if meta['cpu'] != cpu:
                raise RuntimeError(f"harness ran on CPU {meta['cpu']}, expected {cpu}")
            n = cfg['samples']
            ovh = next(l for l in lines if l['kind'] == 'overhead')
            hrows = []
            for l in lines:
                if l['kind'] in ('overhead', 'blocks'):
                    vals = {}
                    for t, cnt in l['bins']:
                        vals[t] = vals.get(t, 0) + cnt
                    for t in l['overflow']:
                        vals[t] = vals.get(t, 0) + 1
                    hrows += [dict(config_id=c['config_id'], uniform_mode=mode, seed=seed, repetition=rep,
                                   block=l['block'], ticks=t, count=cnt) for t, cnt in sorted(vals.items())]
            jrows = [dict(config_id=c['config_id'], uniform_mode=mode, seed=seed, repetition=rep, uniforms=u, ticks=t, count=cnt)
                     for l in lines if l['kind'] == 'joint' for u, t, cnt in l['cells']]
            for h in hrows:
                hists.write(h)
            for j in jrows:
                joints.write(j)
            row.update(status='ok', cpu_reported=meta['cpu'], tsc_hz=meta['tsc_hz'], time_s=a['time_s'],
                       ns_per_sample=a['time_s'] * 1e9 / n, msamples_per_s=n / a['time_s'] / 1e6,
                       cycles=a['cycles'], instructions=a['instructions'], branches=a['branches'],
                       branch_misses=a['branch_misses'], cycles_b=b['cycles_b'], l1d_loads=b['l1d_loads'],
                       l1d_misses=b['l1d_misses'],
                       counters_multiplexed=int(a['time_enabled'] != a['time_running'] or b['time_enabled'] != b['time_running']),
                       uniforms=a['uniforms'], checksum=repr(a['checksum']),
                       checksum_matches_exp13=int(c['config_id'] in exp13 and float(exp13[c['config_id']]) == a['checksum']),
                       overhead_median_ticks=hist_median(ovh['bins']))
        except Exception as exc:  # noqa: BLE001 - every failure is logged and retried with --resume
            row.update(status='failed', error=str(exc)[:500])
        runs.write(row)
        el = time.monotonic() - start_all
        print(f"[timing {k}/{len(jobs)}] {c['config_id']} {mode} rep {rep}: {row['status']}"
              + (f", {row['ns_per_sample']:.2f} ns/sample" if row['status'] == 'ok' else f" ({row.get('error')})")
              + f"  [{el / 60:.1f} min]", flush=True)
    log_env('session_end')
    for log in (runs, hists, joints, env):
        log.close()
    phase_summarize(cfg, out)


def weighted_quantiles(values, counts, qs):
    order = np.argsort(values)
    v, c = np.asarray(values, float)[order], np.asarray(counts, float)[order]
    cum = np.cumsum(c)
    return [float(v[min(np.searchsorted(cum, q * cum[-1]), len(v) - 1)]) for q in qs]


def phase_summarize(cfg, out):
    import pandas as pd
    runs = pd.read_csv(out / 'timing_runs.csv')
    runs = runs[runs.status == 'ok'].drop_duplicates(['config_id', 'uniform_mode', 'seed', 'repetition'], keep='last')
    keys = ['config_id', 'uniform_mode', 'seed', 'repetition']
    hist = pd.read_csv(out / 'timing_histograms.csv').drop_duplicates(keys + ['block', 'ticks'], keep='last')
    hist = hist.merge(runs[keys + ['tsc_hz', 'overhead_median_ticks']], on=keys)
    qs = [0.5, 0.9, 0.99, 0.999, 0.9999]
    qname = lambda q: f'p{str(q * 100).rstrip("0").rstrip(".").replace(".", "_")}_ns_per_sample'
    rrows = []                                     # one row per run and block: a slow pass stays visible
    for (cid, mode, seed, rep, block), g in hist[hist.block > 0].groupby(keys + ['block']):
        ns = (g.ticks - g.overhead_median_ticks) / g.tsc_hz * 1e9 / block
        qv = weighted_quantiles(ns, g['count'], qs)
        rrows.append(dict(config_id=cid, uniform_mode=mode, seed=seed, repetition=rep, block=block,
                          blocks_timed=int(g['count'].sum()),
                          overhead_ns=float(g.overhead_median_ticks.iloc[0] / g.tsc_hz.iloc[0] * 1e9),
                          mean_ns_per_sample=float(np.average(ns, weights=g['count'])),
                          mean_raw_ns_per_sample=float(np.average(g.ticks / g.tsc_hz * 1e9 / block, weights=g['count'])),
                          **{qname(q): v for q, v in zip(qs, qv)}, max_ns_per_sample=float(ns.max()),
                          fraction_above_2x_median=float(g['count'][ns > 2 * qv[0]].sum() / g['count'].sum())))
    by_run = pd.DataFrame(rrows)
    by_run.to_csv(out / 'timing_summary_by_run.csv', index=False)
    stat_cols = [c for c in by_run.columns if c.endswith('ns_per_sample') or c in ('overhead_ns', 'fraction_above_2x_median')]
    s = by_run.groupby(['config_id', 'uniform_mode', 'block']).agg(
        runs=('repetition', 'count'), **{c: (c, 'median') for c in stat_cols},
        min_run_mean_ns_per_sample=('mean_ns_per_sample', 'min'),
        max_run_mean_ns_per_sample=('mean_ns_per_sample', 'max')).reset_index()
    meta = runs.drop_duplicates('config_id').set_index('config_id')[['algorithm', 'N', 'H', 'T']]
    s = s.merge(meta, left_on='config_id', right_index=True)
    s.to_csv(out / 'timing_summary.csv', index=False)

    n = cfg['samples']
    per = runs.copy()
    for col in ('cycles', 'instructions', 'branches', 'branch_misses', 'l1d_loads', 'l1d_misses', 'uniforms'):
        per[f'{col}_per_sample'] = per[col] / n
    per['ipc'] = per.instructions / per.cycles
    agg = per.groupby(['config_id', 'algorithm', 'N', 'H', 'T', 'uniform_mode']).agg(
        runs=('repetition', 'count'), median_ns_per_sample=('ns_per_sample', 'median'),
        min_ns_per_sample=('ns_per_sample', 'min'), max_ns_per_sample=('ns_per_sample', 'max'),
        cycles_per_sample=('cycles_per_sample', 'median'), instructions_per_sample=('instructions_per_sample', 'median'),
        ipc=('ipc', 'median'), branches_per_sample=('branches_per_sample', 'median'),
        branch_misses_per_sample=('branch_misses_per_sample', 'median'),
        l1d_loads_per_sample=('l1d_loads_per_sample', 'median'), l1d_misses_per_sample=('l1d_misses_per_sample', 'median'),
        uniforms_per_sample=('uniforms_per_sample', 'median'), any_multiplexed=('counters_multiplexed', 'max'),
        checksums_match_exp13=('checksum_matches_exp13', 'min')).reset_index()
    agg.to_csv(out / 'perf_summary.csv', index=False)

    j = pd.read_csv(out / 'timing_by_uniforms.csv').drop_duplicates(keys + ['uniforms', 'ticks'], keep='last')
    j = j.merge(runs[keys + ['tsc_hz', 'overhead_median_ticks']], on=keys)
    urows = []
    for (cid, u), g in j.groupby(['config_id', 'uniforms']):
        ns = (g.ticks - g.overhead_median_ticks) / g.tsc_hz * 1e9
        p50, p99 = weighted_quantiles(ns, g['count'], [0.5, 0.99])
        urows.append(dict(config_id=cid, uniforms=u, samples=int(g['count'].sum()),
                          mean_ns=float(np.average(ns, weights=g['count'])), p50_ns=p50, p99_ns=p99))
    u = pd.DataFrame(urows)
    if len(u):
        u['fraction'] = u.samples / u.groupby('config_id').samples.transform('sum')
    u.to_csv(out / 'timing_by_uniforms_summary.csv', index=False)
    print(f'timing_summary.csv ({len(s)} rows, median over runs), timing_summary_by_run.csv, perf_summary.csv ({len(agg)}), timing_by_uniforms_summary.csv ({len(u)})')


# ---------------------------------------------------------------- C: hardware throughput model

def fifo_empty_probability(service, lam, depth):
    """Stationary P(FIFO empty) for a producer with i.i.d. service times (pmf over cycles, service[0] = 0),
    a FIFO of `depth` samples and a consumer that demands one sample per cycle with probability lam.

    Each cycle the consumer takes a sample if one is waiting; then the producer counts down its current
    sample, completes it (pushing if there is room, otherwise holding it until a slot frees) or pushes a
    held sample. P(empty at a demand) = P(empty) because demands are independent of the state.

    Solved on the chain embedded at service starts (state = FIFO level, depth + 1 states): B ~ Bin(S, lam)
    demands arrive during a service of S cycles, the level falls to max(q - B, 0), then the new sample is
    pushed. Empty cycles per service from level q: sum over t < S of P(Bin(t, lam) >= q). This equals the
    cycle-level chain (checked to 12 digits) at a fraction of the size."""
    service = np.asarray(service, float)
    smax = len(service) - 1
    js = np.arange(depth + 1)
    pB = np.zeros(depth + 1)
    for s in np.nonzero(service)[0]:
        pB += service[s] * stats.binom.pmf(js, s, lam)
    T = np.zeros((depth + 1, depth + 1))
    for q in range(depth + 1):
        for j in range(q):
            T[q, min(q - j + 1, depth)] += pB[j]          # q = depth, j = 0: held, then pushed back to depth
        T[q, min(1, depth)] += 1 - pB[:q].sum()             # emptied during the service
    A = T.T - np.eye(depth + 1)
    A[0, :] = 1.0
    b = np.zeros(depth + 1)
    b[0] = 1.0
    pi = np.linalg.solve(A, b)
    surv = 1 - np.cumsum(service)                           # P(S > t)
    R = surv[:smax] @ stats.binom.sf(js[None, :] - 1, np.arange(smax)[:, None], lam)
    cycles = np.full(depth + 1, float(np.dot(np.arange(smax + 1), service)))
    cycles[depth] += pB[0] / lam                            # cycles spent holding a finished sample
    return float(max(np.dot(pi, R), 0.0) / np.dot(pi, cycles))


def fifo_depth(service, lam, target, dmax):
    if len(service) == 2:                               # deterministic 1 cycle: never empty once started
        return 1, 0.0
    d, val = 1, fifo_empty_probability(service, lam, 1)
    while val > target and d < dmax:
        d *= 2
        val = fifo_empty_probability(service, lam, d)
    if val > target:
        return None, val
    lo, hi = d // 2, d
    while hi - lo > 1:
        mid = (lo + hi) // 2
        v = fifo_empty_probability(service, lam, mid)
        if v > target:
            lo = mid
        else:
            hi, val = mid, v
    return hi, val


def phase_model(cfg, out):
    import pandas as pd
    m = cfg['model']
    k = m['uniform_bits']
    eps = cfg['uniforms']['truncation']
    paths = read_paths(out, cfg)
    rows = []
    for c in shortlist(cfg):
        P = paths[c['config_id']]
        ib = int(math.log2(c['N']))
        if c['algorithm'] == 'trapezoid':
            levels = len(P) - 1
            bits = trap_cost_pmf(P, per_level=ib, rect=k, tri=2 * k, extra=ib + k + 1)
            mean_bits = float(np.dot(np.arange(len(bits)), bits))
            designs = [('trapezoid_worst_case', np.array([0.0, 1.0]), (levels + 1) * ib + 3 * k + 1, None)]
            service = trap_cost_pmf(P, per_level=1, rect=0, tri=0, extra=1)
            designs.append(('trapezoid_common_case', service, ib + 3 * k + 1, None))
        else:
            bc = dict(fast=ib + k, rect=ib + 2 * k, wedge=ib + 2 * k, tail_base=ib + k, tail_per_try=2 * k, extra=1)
            mean_bits = classical_mean(P, bc)
            designs = []
            for lat in m['op_latency_cycles']:
                cc = dict(fast=1, rect=1, wedge=1 + lat, tail_base=1, tail_per_try=lat + 1, extra=0)
                designs.append(('classical', classical_cost_pmf(P, cc, eps), ib + 2 * k + 1, lat))
        for name, service, bits_clock, lat in designs:
            service = service / service.sum()
            mean_s = float(np.dot(np.arange(len(service)), service))
            sm = pmf_summary(service, mean_s)
            for u in m['utilization']:
                lam = u / mean_s
                if name == 'trapezoid_worst_case':
                    depth, empty = 0, 0.0
                else:
                    depth, empty = fifo_depth(service, lam, m['underflow_target'], m['max_fifo_depth'])
                rows.append(dict(c, design=name, op_latency_cycles=lat if lat is not None else '',
                                 uniform_bits=k, mean_cycles_per_sample=mean_s,
                                 samples_per_cycle=1 / mean_s, p_longer_than_1_cycle=float(service[2:].sum()),
                                 cycles_p99_9999=sm['p99_9999'], cycles_max_listed=sm['max_listed'],
                                 utilization=u, demand_per_cycle=lam, fifo_depth=depth, empty_probability=empty,
                                 prng_bits_per_clock=bits_clock, mean_prng_bits_per_sample=mean_bits))
                print(f"{c['config_id']} {name}{'' if lat is None else f' L={lat}'} u={u}: "
                      f"{1 / mean_s:.4f} samples/cycle, FIFO {depth}")
    e11.write_csv_atomic(out / 'hw_model.csv', list(rows[0]), rows)

    hw = pd.DataFrame(rows)
    wl = pd.read_csv(out / 'word_length.csv').set_index('config_id')
    q = pd.read_csv(out / 'quantization.csv')
    us = pd.read_csv(out / 'uniforms_summary.csv').set_index('config_id')
    sm = m['summary']
    summ = []
    for c in shortlist(cfg):
        cid = c['config_id']
        b = wl.loc[cid, 'b_star']
        b = int(b) if pd.notna(b) else None
        qb = q[(q.config_id == cid) & (q.frac_bits.astype(str) == (str(b) if b else 'double'))].iloc[0]
        h = hw[(hw.config_id == cid) & (hw.utilization == sm['utilization'])
               & ((hw.op_latency_cycles.astype(str) == str(sm['op_latency_cycles'])) | (hw.algorithm == 'trapezoid'))]
        row = dict(c, word_length_frac_bits=b, table_bits=table_bits(c, b, cfg) if b else None,
                   table_kib=table_bits(c, b, cfg) / 8192 if b else None, delta_at_word_length=qb.delta,
                   ks_at_word_length=qb.ks, uniforms_mean=us.loc[cid, 'mean'], uniforms_p99_9999=us.loc[cid, 'p99_9999'],
                   mean_prng_bits_per_sample=h.mean_prng_bits_per_sample.iloc[0])
        for _, r in h.iterrows():
            tag = r.design.replace('trapezoid_', '')
            row[f'{tag}_samples_per_cycle'] = r.samples_per_cycle
            row[f'{tag}_prng_bits_per_clock'] = r.prng_bits_per_clock
            row[f'{tag}_fifo_depth'] = r.fifo_depth
        summ.append(row)
    pd.DataFrame(summ).to_csv(out / 'hw_summary.csv', index=False)
    print(f'hw_model.csv ({len(rows)} rows), hw_summary.csv written')


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_suffix('.yaml'))
    parser.add_argument('--phase', required=True, choices=['memory', 'uniforms', 'timing', 'summarize', 'model'])
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--dry-run', action='store_true', help='print the timing plan and exit')
    args = parser.parse_args()
    cfg = load_config(args.config)
    check_config(cfg)
    out = (args.output_dir or REPO / cfg['output_dir']).resolve()

    if args.dry_run:
        jobs = timing_jobs(cfg)
        print(f'timing: {len(jobs)} harness runs ({len(shortlist(cfg))} configurations x '
              f"{len(cfg['timing']['uniform_modes'])} uniform modes x {len(cfg['timing']['seeds'])} seeds x "
              f"{cfg['timing']['repetitions']} repetitions); roughly {len(jobs) * 12 / 60:.0f} min")
        print('example:', ' '.join(harness_argv(cfg, REPO / cfg['harness'], *jobs[0][:3])))
        return

    out.mkdir(parents=True, exist_ok=True)
    saved = out / 'config.yaml'
    if saved.exists() and saved.read_bytes() != args.config.read_bytes():
        sys.exit(f'{saved} differs from {args.config}; use the same configuration or a new --output-dir')
    shutil.copyfile(args.config, saved)
    lock = (out / '.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(f'another experiment14.py is using {out}')

    start = time.monotonic()
    if args.phase == 'memory':
        phase_memory(cfg, out)
    elif args.phase == 'uniforms':
        phase_uniforms(cfg, out, build_harness(cfg))
    elif args.phase == 'timing':
        phase_timing(cfg, out, build_harness(cfg), args.config)
    elif args.phase == 'summarize':
        phase_summarize(cfg, out)
    else:
        phase_model(cfg, out)
    print(f'done in {time.monotonic() - start:.0f} s; results in {out}')


if __name__ == '__main__':
    main()
