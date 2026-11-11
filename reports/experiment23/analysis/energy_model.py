"""Experiment 23, part 2: energy model over the exact per-sample operation counts.

Inputs: experiments/results/experiment23/{op_vectors.csv, trap_paths.csv, config.yaml} and the
table sizes of Experiment 14 (experiments/results/experiment14/word_length.csv, bits at b*).

Distributions of the operation vector per sample:
  Trapezoid  every path is enumerated (trap_paths.csv). P(side, depth) is exact: each descent
             index is a uniform k-bit field, so a level is entered with probability 1/N.
             P(wedge | side, depth) is the observed fraction; a (side, depth) never observed is
             assigned wedge (the more expensive path), which can only raise Trapezoid's energy.
  Classical  attempts are independent: rejections ~ geometric(q), q = rejections / attempts; the
             accepted attempt's outcome has the observed distribution; tail candidates ~
             geometric(a). Every observed vector must equal k * c_reject + c_outcome
             (+ (j-1) * c_tail_iteration): this is checked, and the decomposition then extends the
             distribution past the sampled range.
Energy of a vector = sum(count * pJ per operation) + blocks * pJ per Philox block + reads * pJ per
table read (by table size) + leakage per attempt slot (by table size). Two Trapezoid structures:
  S (sequential)  only the taken path's operations
  P (pipelined)   rectangle and wedge datapaths both computed every clock: constant energy
Windows of W samples: the W-fold convolution of the per-sample distribution (samples are
independent), computed by FFT on an energy grid.

    .venv/bin/python -B reports/experiment23/analysis/energy_model.py [--results DIR] [--out DIR]
"""
import sys
sys.dont_write_bytecode = True
import argparse
import csv
import itertools
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import yaml
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parents[3]
OPS = ['blocks', 'attempts', 'reads', 'conv', 'fmul', 'fscale', 'fadd', 'fcmp', 'fdiv', 'iadd', 'icmp', 'exp', 'log']
LAYERS = [8, 16, 32, 64, 128, 256]
MAIN = (1, 2)                                              # Trapezoid H1/T2, the recommended configuration
BLUE, ORANGE, AQUA = '#2a78d6', '#eb6834', '#1baf7a'
INK, INK2, GRID, SURFACE = '#0b0b0b', '#52514e', '#e4e3df', '#fcfcfb'
WIN_COLORS = {1: '#9ec5f4', 16: '#5598e7', 256: '#1c5cab'}


# ---------------------------------------------------------------- loading and operation counts
def load(results):
    cfg = yaml.safe_load(open(results / 'config.yaml'))
    vecs = defaultdict(lambda: defaultdict(int))
    fields = None
    with open(results / 'op_vectors.csv') as f:
        r = csv.reader(f)
        head = next(r)
        fields = head[8:]
        for row in r:
            key = (row[1], int(row[2]), int(row[3] or 0), int(row[4] or 0))
            vecs[key][tuple(int(x) for x in row[8:])] += int(row[7])
    paths = defaultdict(list)
    for row in csv.DictReader(open(results / 'trap_paths.csv')):
        paths[(int(row['N']), int(row['H']), int(row['T']))].append(row)
    sizes = {}
    for row in csv.DictReader(open(REPO / 'experiments/results/experiment14/word_length.csv')):
        sizes[row['config_id']] = (int(row['b_star']), int(row['bits_at_b_star']) / 8192)
    return cfg, fields, vecs, paths, sizes


def opv(vector, fields):
    d = dict(zip(fields, vector))
    return np.array([d[o] for o in OPS], dtype=float), d


def trapezoid_paths(n, h, t, fields, paths, observed):
    """[(prob, ops vector, slots)] for model S, with checks; plus validation info."""
    seen = defaultdict(lambda: [0, 0])                     # (side, depth) -> [samples, wedge samples]
    enum = {}
    for p in paths[(n, h, t)]:
        vec = np.array([float(p[o]) for o in OPS])
        enum[(int(p['path_side']), int(p['path_depth']), int(p['path_wedge']))] = vec
    total = sum(observed.values())
    for vector, c in observed.items():
        v, d = opv(vector, fields)
        key = (d['side'], d['depth'], d['outcome'] - 1)
        if key not in enum or not np.array_equal(enum[key], v):
            raise SystemExit(f'Trapezoid N={n} H={h} T={t}: observed vector {d} is not an enumerated path')
        seen[(d['side'], d['depth'])][0] += c
        seen[(d['side'], d['depth'])][1] += c * (d['outcome'] == 2)
    inv = 1.0 / n
    probs = {(0, 0): 1 - (inv if h else 0) - (inv if t else 0)}
    for side, levels in ((1, h), (2, t)):
        for dpt in range(1, levels + 1):
            probs[(side, dpt)] = inv ** dpt * (1 - inv) if dpt < levels else inv ** dpt
    out, check = [], []
    for (side, dpt), p in probs.items():
        ns, nw = seen[(side, dpt)]
        pw = nw / ns if ns else 1.0                         # never observed: assume the wedge
        out.append((p * (1 - pw), enum[(side, dpt, 0)]))
        out.append((p * pw, enum[(side, dpt, 1)]))
        check.append(dict(N=n, H=h, T=t, side=side, depth=dpt, exact_probability=p,
                          observed_fraction=ns / total, observed_samples=ns, wedge_fraction=pw if ns else '',
                          assumed_wedge=not ns))
    out = [(p, v) for p, v in out if p > 0]
    assert abs(sum(p for p, _ in out) - 1) < 1e-12
    return out, check, enum


def classical_paths(observed, fields, eps_mass=1e-22):
    """Analytic per-sample distribution [(prob, ops vector, slots)] from the attempt decomposition."""
    total = sum(observed.values())
    att = rej = tail_it = 0
    final = defaultdict(int)
    base = {}
    for vector, c in observed.items():
        v, d = opv(vector, fields)
        att += c * d['attempts']; rej += c * d['rejections']; tail_it += c * d['tail_iter']
        final[d['outcome']] += c
        base[(d['outcome'], d['rejections'], d['tail_iter'])] = v
    q = rej / att
    pi = {o: final[o] / total for o in (1, 2, 3, 4)}
    a = final[3] / tail_it
    c = {o: base[(o, 0, 0)] for o in (1, 2, 4)}
    c3 = base[(3, 0, 1)]
    c_iter = base[(3, 0, 2)] - c3
    c_rej = base[(1, 1, 0)] - c[1]
    worst = 0.0
    for (o, k, j), v in base.items():                       # every observed vector must decompose exactly
        pred = k * c_rej + (c[o] if o != 3 else c3 + (j - 1) * c_iter)
        worst = max(worst, float(np.max(np.abs(pred - v))))
    kmax = int(math.ceil(math.log(eps_mass) / math.log(q))) + 1
    jmax = int(math.ceil(math.log(eps_mass) / math.log(1 - a))) + 1
    out = []
    for k in range(kmax + 1):
        pk = q ** k * (1 - q)
        for o in (1, 2, 4):
            out.append((pk * pi[o], k * c_rej + c[o]))
        for j in range(1, jmax + 1):
            out.append((pk * pi[3] * a * (1 - a) ** (j - 1), k * c_rej + c3 + (j - 1) * c_iter))
    # observed vs geometric P(rejections = k)
    obs_k = defaultdict(int)
    for vector, cnt in observed.items():
        obs_k[dict(zip(fields, vector))['rejections']] += cnt
    geo = [dict(rejections=k, observed=obs_k[k] / total, geometric=q ** k * (1 - q), observed_samples=obs_k[k])
           for k in range(max(obs_k) + 1)]
    # independence: outcome distribution after 0 vs >= 1 rejections
    o0, o1 = defaultdict(int), defaultdict(int)
    for vector, cnt in observed.items():
        d = dict(zip(fields, vector))
        (o0 if d['rejections'] == 0 else o1)[d['outcome']] += cnt
    s0, s1 = sum(o0.values()), sum(o1.values())
    info = dict(q_reject_per_attempt=q, tail_accept=a, decomposition_max_error=worst, kmax=kmax, jmax=jmax,
                **{f'outcome{o}_share': pi[o] for o in (1, 2, 3, 4)},
                **{f'outcome{o}_share_after_rejection': (o1[o] / s1 if s1 else '') for o in (1, 2, 3, 4)},
                **{f'outcome{o}_share_first_attempt': o0[o] / s0 for o in (1, 2, 3, 4)})
    return out, info, geo


# ---------------------------------------------------------------- energy
def energy_fn(params, kib, word_bits):
    em = params
    pj = em['pj']
    w = np.zeros(len(OPS))
    for o in ('conv', 'fmul', 'fscale', 'fadd', 'fcmp', 'fdiv', 'iadd', 'icmp'):
        w[OPS.index(o)] = pj[o]
    w[OPS.index('exp')] = w[OPS.index('log')] = em['exp_log_in_fmul'] * pj['fmul']
    w[OPS.index('blocks')] = pj['prng_block'] * em.get('prng_scale', 1)
    w[OPS.index('reads')] = em['read_pj_8kb_64bit'] * word_bits / 64 * (kib / 8) ** em['read_size_exponent']
    leak = em['leakage_pj_per_kib_per_slot'] * kib

    def f(v, slots):
        return float(w @ v) + leak * slots
    return f


def distribution(paths, efn, slots_fn):
    e = np.array([efn(v, slots_fn(v)) for _, v in paths])
    p = np.array([p for p, _ in paths])
    order = np.argsort(e)
    e, p = e[order], p[order]
    # merge equal energies
    ue, idx = np.unique(np.round(e, 9), return_inverse=True)
    up = np.bincount(idx, weights=p)
    return ue, up


def stats(e, p):
    mean = float(p @ e)
    sd = math.sqrt(max(float(p @ (e - mean) ** 2), 0))
    cdf = np.cumsum(p)
    median = float(e[np.searchsorted(cdf, 0.5)])
    return mean, sd, median


def budget(e, p, eps):
    """Smallest x with P(E > x) <= eps."""
    tail = np.concatenate([np.cumsum(p[::-1])[::-1][1:], [0.0]])
    i = int(np.argmax(tail <= eps))
    return float(e[i])


def _logsumexp(a):
    m = np.max(a)
    return m + math.log(np.sum(np.exp(a - m)))


def window_budget(e, p, W, eps, max_bins=1 << 21):
    """Smallest x with P(sum of W independent samples > x) <= eps, divided by W (energy per sample).

    The W-fold convolution is computed by FFT on an energy grid. A plain FFT cannot resolve tail
    probabilities far below ~1e-10 (rounding errors of every bin add up in the tail sum), so the
    distribution is exponentially tilted first: weights p*exp(theta*e), with theta chosen so the
    tilted window mean sits at the budget being sought; there the convolution has full relative
    precision, and the tilt is divided out afterwards. Returns (budget per sample, grid step)."""
    if W == 1:
        return budget(e, p, eps), 0.0
    keep = p > 1e-40
    e, p = e[keep], p[keep]
    if len(e) == 1:
        return float(e[0]), 0.0
    step = max(0.05, W * e[-1] / max_bins)
    bins = np.rint(e / step).astype(np.int64)
    pmf = np.bincount(bins, weights=p)
    b = np.arange(len(pmf), dtype=float)
    lp = np.full(len(pmf), -np.inf)
    lp[pmf > 0] = np.log(pmf[pmf > 0])
    n = 1 << int(math.ceil(math.log2(W * (len(pmf) - 1) + 1)))

    def tilted(theta):
        lw = lp + theta * b
        lz = _logsumexp(lw[np.isfinite(lw)])
        w = np.exp(lw - lz)
        return lz, w, float(w @ b)

    def theta_for(target_mean):
        if tilted(0.0)[2] >= target_mean:
            return 0.0
        lo, hi = 0.0, 1e-6
        while tilted(hi)[2] < target_mean and hi < 50:
            hi *= 2
        for _ in range(80):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if tilted(mid)[2] < target_mean else (lo, mid)
        return (lo + hi) / 2

    # start from the window mean plus a generous margin; move the tilt until the budget is inside
    # the region where the tilted convolution is accurate
    x = W * float(pmf @ b) * 1.2
    for _ in range(12):
        theta = theta_for(x / W)
        lz, w, _ = tilted(theta)
        q = np.fft.irfft(np.fft.rfft(w, n) ** W, n)
        good = q > 1e-13 * q.max()                           # accurate region of the tilted result
        idx = np.nonzero(good)[0]
        lo_b, hi_b = idx[0], idx[-1]
        ls = np.full(n, -np.inf)
        ls[good] = W * lz - theta * np.arange(n)[good] + np.log(q[good])
        seg = np.exp(ls[lo_b:hi_b + 1])                       # P(sum = bin) on the accurate region
        tail = np.cumsum(seg[::-1])[::-1]                     # P(sum >= bin), bins beyond hi_b negligible
        above = np.concatenate([tail[1:], [0.0]])             # P(sum > bin)
        if above[0] <= eps:                                   # budget lies below the region: tilt less
            x = max(lo_b * 0.9, 1.0)
            if theta == 0.0:
                return lo_b * step / W, step
            continue
        if above[-1] > eps:                                   # budget lies above the region: tilt more
            x = hi_b * 1.1
            continue
        k = int(np.argmax(above <= eps))
        return (lo_b + k) * step / W, step
    raise RuntimeError('window budget did not converge')


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--results', type=Path, default=REPO / 'experiments/results/experiment23')
    ap.add_argument('--out', type=Path, default=REPO / 'reports/experiment23')
    args = ap.parse_args()
    cfg, fields, vecs, paths, sizes = load(args.results)
    em0 = cfg['energy_model']
    (args.out / 'tables').mkdir(parents=True, exist_ok=True)
    (args.out / 'figures').mkdir(parents=True, exist_ok=True)
    layers = sorted({k[1] for k in vecs})

    def write(name, rows):
        if rows:
            keys = list(dict.fromkeys(k for r in rows for k in r))
            with open(args.out / 'tables' / name, 'w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)

    # ---- part 1 tables: operation counts and model checks
    opcounts, descent, cinfo, geos = [], [], [], []
    tpaths, cpaths = {}, {}
    for (var, n, h, t), obs in sorted(vecs.items()):
        total = sum(obs.values())
        row = dict(variant=var, N=n, H=h if var.startswith('trap') else '', T=t if var.startswith('trap') else '',
                   samples=total)
        for o in OPS + ['rejections', 'tail_iter']:
            vals = defaultdict(int)
            for vector, c in obs.items():
                vals[dict(zip(fields, vector))[o]] += c
            row[f'{o}_mean'] = sum(v * c for v, c in vals.items()) / total
            row[f'{o}_max_observed'] = max(vals)
        row['p_more_than_one_block'] = sum(c for vct, c in obs.items() if dict(zip(fields, vct))['blocks'] > 1) / total
        row['p_any_exp_or_log'] = sum(c for vct, c in obs.items()
                                      if dict(zip(fields, vct))['exp'] + dict(zip(fields, vct))['log'] > 0) / total
        if var.startswith('trap'):
            tp, chk, enum = trapezoid_paths(n, h, t, fields, paths, obs)
            tpaths[(n, h, t)] = tp
            descent += chk
            for o in OPS:
                row[f'{o}_max_structural'] = max(v[OPS.index(o)] for v in enum.values())
        else:
            cp, info, geo = classical_paths(obs, fields)
            cpaths[n] = cp
            cinfo.append(dict(N=n, **info))
            geos += [dict(N=n, **g) for g in geo]
            for o in OPS:
                row[f'{o}_max_structural'] = 'unbounded' if o in ('blocks', 'attempts', 'reads', 'conv', 'fmul',
                                                                   'fscale', 'fadd', 'fcmp', 'icmp', 'exp', 'log',
                                                                   'fdiv') else 0
        opcounts.append(row)
    write('op_counts.csv', opcounts)
    write('check_trapezoid_descent.csv', descent)
    write('check_classical_decomposition.csv', cinfo)
    write('check_classical_geometric.csv', geos)

    # ---- part 2: energy
    def table(kind, n, h=0, t=0):
        cid = f'classical_N{n}' if kind == 'classical' else f'trap_N{n}_H{h}_T{t}'
        b, kib = sizes[cid]
        return kib, b + em0['word_bits_extra']

    def dists(em, n, h=MAIN[0], t=MAIN[1]):
        out = {}
        kib, wb = table('trap', n, h, t)
        ef = energy_fn(em, kib, wb)
        out['trap_S'] = distribution(tpaths[(n, h, t)], ef, lambda v: 1)
        flat = np.zeros(len(OPS))
        for o, val in dict(blocks=1, attempts=1, reads=4, conv=2, fmul=2, fadd=1, iadd=2,
                           icmp=2 + max(h, t) + 1).items():
            flat[OPS.index(o)] = val
        out['trap_P'] = (np.array([ef(flat, 1)]), np.array([1.0]))
        kib, wb = table('classical', n)
        ef = energy_fn(em, kib, wb)
        out['classical'] = distribution(cpaths[n], ef, lambda v: v[OPS.index('blocks')])   # one clock per block
        return out

    def scenario(**kw):
        em = {k: v for k, v in em0.items()}
        em['pj'] = dict(em0['pj'])
        em.update(kw)
        return em

    eps_list, wins = em0['epsilons'], em0['windows']
    # default scenario: full statistics, windows
    rows, budgets = [], []
    default = scenario()
    D = {n: dists(default, n) for n in layers}
    for n in layers:
        for name, (e, p) in D[n].items():
            mean, sd, med = stats(e, p)
            rows.append(dict(N=n, sampler=name, mean_pj=mean, sd_pj=sd, median_pj=med, cv_percent=100 * sd / mean,
                             max_pj=float(e[-1]) if name != 'classical' else 'unbounded',
                             max_over_median=float(e[-1]) / med if name != 'classical' else 'unbounded',
                             **{f'budget_eps{eps:g}_pj': budget(e, p, eps) for eps in eps_list}))
        for W in wins:
            for eps in eps_list:
                rec = dict(N=n, window=W, eps=eps)
                for k in D[n]:
                    rec[f'{k}_budget_per_sample_pj'], rec[f'{k}_grid_step_pj'] = window_budget(*D[n][k], W, eps)
                rec['trap_S_guaranteed_max_per_sample_pj'] = float(D[n]['trap_S'][0][-1])
                if True:
                    rec['ratio_classical_over_trap_S'] = rec['classical_budget_per_sample_pj'] / rec['trap_S_budget_per_sample_pj']
                    rec['ratio_classical_over_trap_P'] = rec['classical_budget_per_sample_pj'] / rec['trap_P_budget_per_sample_pj']
                    rec['ratio_classical_over_trap_guaranteed'] = rec['classical_budget_per_sample_pj'] / rec['trap_S_guaranteed_max_per_sample_pj']
                budgets.append(rec)
    write('energy_default.csv', rows)

    # check: model budgets against the observed (sampled) distribution, where the data can resolve them
    emp = []
    for n in layers:
        obs = vecs[('classical_philox_fast', n, 0, 0)]
        kib, wb = table('classical', n)
        ef = energy_fn(default, kib, wb)
        pairs = [(ef(opv(v, fields)[0], opv(v, fields)[0][OPS.index('blocks')]), c) for v, c in obs.items()]
        e = np.array([x for x, _ in pairs]); c = np.array([y for _, y in pairs], dtype=float)
        o = np.argsort(e); e, c = e[o], c[o]
        total = c.sum()
        for eps in (1e-3, 1e-4, 1e-5, 1e-6, 1e-7):
            if eps * total < 30:
                continue                                    # fewer than 30 samples beyond: not resolvable
            emp.append(dict(N=n, eps=eps, samples=int(total), samples_beyond=eps * total,
                            observed_budget_pj=budget(e, c / total, eps),
                            model_budget_pj=budget(*D[n]['classical'], eps)))
    write('check_classical_empirical_budget.csv', emp)
    write('budget_default.csv', budgets)

    # every Trapezoid configuration (default scenario): bounded maximum
    grid = []
    for (n, h, t), tp in sorted(tpaths.items()):
        kib, wb = table('trap', n, h, t)
        e, p = distribution(tp, energy_fn(default, kib, wb), lambda v: 1)
        mean, sd, med = stats(e, p)
        grid.append(dict(N=n, H=h, T=t, table_kib=kib, mean_pj=mean, sd_pj=sd, median_pj=med, max_pj=float(e[-1]),
                         max_over_median=float(e[-1]) / med))
    write('trapezoid_grid_default.csv', grid)

    # sensitivity: full factorial at window 1, eps 1e-9
    sw = em0['sweeps']
    sens = []
    for c, ps, ra, lk in itertools.product(sw['exp_log_in_fmul'], sw['prng_scale'], sw['read_size_exponent'],
                                           sw['leakage_pj_per_kib_per_slot']):
        em = scenario(exp_log_in_fmul=c, prng_scale=ps, read_size_exponent=ra, leakage_pj_per_kib_per_slot=lk)
        for n in layers:
            d = dists(em, n)
            ce, cp = d['classical']
            te, tp_ = d['trap_S']
            rec = dict(exp_log_in_fmul=c, prng_scale=ps, read_size_exponent=ra, leakage_pj_per_kib_per_slot=lk, N=n,
                       mean_ratio=stats(ce, cp)[0] / stats(te, tp_)[0])
            for eps in eps_list:
                rec[f'budget_ratio_eps{eps:g}'] = budget(ce, cp, eps) / float(te[-1])
            sens.append(rec)
    write('sensitivity_window1.csv', sens)

    # ---- figures
    fig, axes = plt.subplots(2, 3, figsize=(12, 7.2), constrained_layout=True, sharey=True)
    for ax, n in zip(axes.flat, layers):
        for name, color, label in (('classical', ORANGE, 'Classical'), ('trap_S', BLUE, 'Trapezoid H1/T2, sequential'),
                                   ('trap_P', AQUA, 'Trapezoid H1/T2, pipelined')):
            e, p = D[n][name]
            tail = np.concatenate([np.cumsum(p[::-1])[::-1], [0.0]])     # P(E >= e_i), then 0
            xs = np.concatenate([[0], e])
            ys = np.concatenate([[1], tail[1:]])
            keep = ys > 1e-16
            ax.step(xs[keep], ys[keep], where='post', color=color, lw=2, label=label)
            if name != 'classical':
                ax.axvline(e[-1], color=color, lw=1, ls=(0, (2, 2)))
        ax.set_yscale('log')
        ax.set_xscale('log')
        ax.set_ylim(1e-15, 2)
        ax.set_xlim(100, 1e4)
        ax.set_title(f'N = {n}', fontsize=12, color=INK)
        ax.grid(color=GRID, lw=1)
        ax.tick_params(colors=INK2, length=0)
        for s in ('top', 'right'):
            ax.spines[s].set_visible(False)
        for s in ('left', 'bottom'):
            ax.spines[s].set_color(GRID)
        if n >= 64:
            ax.set_xlabel('energy per sample (pJ, 45 nm model)', color=INK2)
    for ax in axes[:, 0]:
        ax.set_ylabel('P(energy per sample > x)', color=INK2)
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=3, frameon=False, fontsize=10, labelcolor=INK2,
               bbox_to_anchor=(0.5, -0.04))
    fig.suptitle('Experiment 23: energy per sample (default model). Trapezoid ends at a fixed maximum (dotted); '
                 'Classical has no maximum', fontsize=12, color=INK)
    fig.savefig(args.out / 'figures/energy_tail.png', dpi=160, bbox_inches='tight')
    fig.savefig(args.out / 'figures/energy_tail.svg', bbox_inches='tight')
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.6, 4.3), constrained_layout=True)
    for W in wins:
        rs = [r for r in budgets if r['window'] == W and r['eps'] == 1e-9 and 'ratio_classical_over_trap_S' in r]
        ax.plot([r['N'] for r in rs], [r['ratio_classical_over_trap_S'] for r in rs], color=WIN_COLORS[W], lw=2,
                marker='o', ms=7, mec=SURFACE, mew=1.5,
                label={1: 'per sample', 16: 'windows of 16', 256: 'windows of 256'}[W])
    ax.axhline(1, color=INK2, lw=1, ls=(0, (4, 3)))
    ax.set_xscale('log', base=2)
    ax.set_xticks(layers, [str(n) for n in layers])
    ax.set_ylim(bottom=0)
    ax.set_xlabel('layers N', color=INK2)
    ax.set_ylabel('energy budget per sample, 1 - 1e-9 coverage:\nClassical / Trapezoid H1/T2', color=INK2)
    ax.grid(axis='y', color=GRID, lw=1)
    ax.tick_params(colors=INK2, length=0)
    for s in ('top', 'right', 'left'):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK2)
    ax.set_title('Energy budget ratio (default model, sequential Trapezoid)', fontsize=11, color=INK)
    fig.savefig(args.out / 'figures/budget_ratio.png', dpi=160)
    fig.savefig(args.out / 'figures/budget_ratio.svg')
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), constrained_layout=True, sharey=True)
    base = dict(read_size_exponent=em0['read_size_exponent'], leakage_pj_per_kib_per_slot=em0['leakage_pj_per_kib_per_slot'])
    shades = ['#9ec5f4', '#5598e7', '#1c5cab', '#0b3a75']
    for ax, (param, values, fixed) in zip(axes, (('prng_scale', sw['prng_scale'], base),
                                                 ('leakage_pj_per_kib_per_slot', sw['leakage_pj_per_kib_per_slot'],
                                                  dict(prng_scale=1, read_size_exponent=em0['read_size_exponent'])))):
        for color, val in zip(shades, values):
            rs = [r for r in sens if r['N'] == 128 and r[param] == val
                  and all(r[k] == v for k, v in fixed.items() if k != param)]
            rs.sort(key=lambda r: r['exp_log_in_fmul'])
            ax.plot([r['exp_log_in_fmul'] for r in rs], [r['budget_ratio_eps1e-09'] for r in rs], color=color, lw=2,
                    marker='o', ms=6, mec=SURFACE, mew=1.2, label=(f'Philox x{val:g}' if param == 'prng_scale' else f'leakage {val:g}'))
        ax.axhline(1, color=INK2, lw=1, ls=(0, (4, 3)))
        ax.set_xscale('log')
        ax.set_xticks(sw['exp_log_in_fmul'], [str(c) for c in sw['exp_log_in_fmul']])
        ax.set_xlabel('cost of exp() / log() in FP multiplies', color=INK2)
        ax.set_title({'prng_scale': 'Philox block energy x scale',
                      'leakage_pj_per_kib_per_slot': 'table leakage, pJ per KiB per clock'}[param], fontsize=11, color=INK)
        ax.grid(axis='y', color=GRID, lw=1)
        ax.tick_params(colors=INK2, length=0)
        for s in ('top', 'right', 'left'):
            ax.spines[s].set_visible(False)
        ax.legend(frameon=False, fontsize=9, labelcolor=INK2)
        ax.set_ylim(bottom=0)
    axes[0].set_ylabel('Classical budget (1 - 1e-9) /\nTrapezoid guaranteed maximum, N = 128', color=INK2)
    fig.savefig(args.out / 'figures/sensitivity.png', dpi=160)
    fig.savefig(args.out / 'figures/sensitivity.svg')
    plt.close(fig)

    for r in rows:
        print('{N:>3} {sampler:9s} mean {mean_pj:7.1f} sd {sd_pj:6.1f} median {median_pj:7.1f} max {mx}'.format(
            mx=r['max_pj'] if isinstance(r['max_pj'], str) else f"{r['max_pj']:.1f}", **r))
    for r in budgets:
        if r['eps'] == 1e-9 and 'ratio_classical_over_trap_S' in r:
            print(f"N={r['N']:>3} W={r['window']:>3} eps=1e-9 classical {r['classical_budget_per_sample_pj']:.1f} "
                  f"trapS {r['trap_S_budget_per_sample_pj']:.1f} ratio S {r['ratio_classical_over_trap_S']:.2f} "
                  f"P {r['ratio_classical_over_trap_P']:.2f} guaranteed {r['ratio_classical_over_trap_guaranteed']:.2f}")
    br = [r['budget_ratio_eps1e-09'] for r in sens]
    print('sensitivity: budget ratio (eps 1e-9, vs Trapezoid max) min %.2f max %.2f over %d cases' % (min(br), max(br), len(br)))


if __name__ == '__main__':
    main()
