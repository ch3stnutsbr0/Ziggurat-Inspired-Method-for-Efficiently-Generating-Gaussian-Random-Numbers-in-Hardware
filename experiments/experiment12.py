"""Experiment 12: exact output distribution of the Trapezoid sampler (Method 1).

No random numbers are generated. The exact tables are exported from c/ziggurat_trapezoid.c by
experiment12_dump_tables.c; the output law is the weighted mixture of trapezoid densities
(see the manual's sections 2-7). Full metrics are computed for the Experiment 11 configurations that
passed all four tests; the exact chi-square divergence is computed for all 150 configurations to
validate the model against the seed-1 observations.

    .venv/bin/python -B experiments/experiment12.py [--config FILE] [--output-dir DIR]
"""
import sys
sys.dont_write_bytecode = True
import argparse
import csv
import hashlib
import io
import json
import math
import platform
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import optimize, stats

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'experiments'))
from utils import load_config  # noqa: E402

TAIL_SIDE = {'root': 0, 'head': 1, 'tail': 2}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_exporter(work):
    exe = work / 'dump_tables'
    cmd = ['gcc', '-std=c11', '-Wall', '-Wextra', '-pedantic', '-O2', '-I', str(REPO / 'c'),
           str(Path(__file__).with_name('experiment12_dump_tables.c')), '-o', str(exe), '-lm']
    done = subprocess.run(cmd, capture_output=True, text=True, check=True)
    if done.stderr:
        raise RuntimeError(done.stderr)
    return exe, cmd


def terminal_entries(exe, n, h, t):
    """Tables from the C code, with the descent weights of zt_gaussian() (manual section 5)."""
    rows = list(csv.DictReader(io.StringIO(subprocess.run([str(exe), str(n), str(h), str(t)],
                                                          capture_output=True, text=True, check=True).stdout)))
    out = []
    for r in rows:
        level, i = int(r['level']), int(r['index'])
        if r['side'] == 'root':
            if (i == 0 and h > 0) or (i == n - 1 and t > 0):
                continue
        elif r['side'] == 'head':
            if i == 0 and level < h:
                continue
        elif i == n - 1 and level < t:
            continue
        out.append(dict(side=r['side'], level=level, index=i, weight=float(n) ** -(level + 1),
                        w=float(r['w']), d=float(r['d']), a=float(r['a']), x_lo=float(r['x_lo']), x_hi=float(r['x_hi'])))
    total = math.fsum(e['weight'] for e in out)
    if abs(total - 1) > 1e-12:
        raise ValueError(f'weights sum to {total} for N={n} H={h} T={t}')
    return out


def cdf_abs(x, ents):
    """F_|X|(x), mixture of piecewise-quadratic trapezoid CDFs (manual section 4)."""
    x = np.asarray(x, float)
    F = np.zeros_like(x)
    for e in ents:
        w, d = e['w'], e['d']
        k = 2.0 / (2 * w + d)
        Fk = np.where(x <= w, k * x, np.where(x < w + d, k * (x - (x - w) ** 2 / (2 * d)), 1.0))
        F += e['weight'] * np.where(x <= 0, 0.0, Fk)
    return F


def cdf_x(x, ents):
    x = np.asarray(x, float)
    return 0.5 + 0.5 * np.sign(x) * cdf_abs(np.abs(x), ents)


def chi2_divergence(ents, cfg):
    lo, hi = cfg['chi_square']['range']
    edges = np.r_[-np.inf, np.linspace(lo, hi, cfg['chi_square']['bins'] + 1), np.inf]
    p = np.diff(np.r_[0.0, cdf_x(edges[1:-1], ents), 1.0])
    q = np.diff(stats.norm.cdf(edges))
    return float(np.sum((p - q) ** 2 / q)), len(p) - 1


def chi2_prediction(delta, df, n, alpha):
    crit = stats.chi2.isf(alpha, df)
    lam = n * delta
    power = float(stats.ncx2.sf(crit, df, lam)) if lam > 0 else alpha
    def needed(target):
        if delta <= 0:
            return math.inf
        return optimize.brentq(lambda l: stats.ncx2.sf(crit, df, l) - target, 1e-9, 1e7) / delta
    return dict(lambda_pred=lam, z_pred=lam / math.sqrt(2 * df), p_reject_chi2=power,
                n_detect_50=needed(0.5), n_detect_90=needed(0.9))


def full_metrics(ents, cfg):
    grid = np.linspace(0.0, cfg['ks_grid']['max_x'], cfg['ks_grid']['points'])
    breaks = np.array([v for e in ents for v in (e['w'], e['w'] + e['d'])])
    xs = np.unique(np.r_[grid, breaks])
    diff = 0.5 * cdf_abs(xs, ents) - (stats.norm.cdf(xs) - 0.5)       # F_X - Phi for x >= 0 (symmetric)
    i = int(np.argmax(np.abs(diff)))
    m2 = 0.0
    for e in ents:
        w, d = e['w'], e['d']
        m2 += e['weight'] * (2 / (2 * w + d)) * (w ** 3 / 3 + ((w + d) ** 4 / 12 - (w + d) * w ** 3 / 3 + w ** 4 / 4) / d)
    out = dict(ks_exact=float(abs(diff[i])), ks_argmax_abs_x=float(xs[i]),
               support=max(e['w'] + e['d'] for e in ents), variance=m2, variance_error=m2 - 1.0,
               ks_n_detect_approx=(stats.kstwobign.isf(cfg['significance_level']) / abs(diff[i])) ** 2)
    for t in cfg['tail_points']:
        exact = float(1 - cdf_abs([t], ents)[0]); true = float(2 * stats.norm.sf(t))
        out[f'tail_P_abs_gt_{t}'] = exact
        out[f'tail_ratio_{t}'] = exact / true
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_suffix('.yaml'))
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    cfg = load_config(args.config)
    if cfg.get('experiment_id') != 'experiment12':
        raise ValueError('experiment_id must be experiment12')
    out = (args.output_dir or REPO / cfg['output_dir']).resolve()
    if out.exists():
        sys.exit(f'{out} already exists; use --output-dir for a fresh run')
    src, ref = REPO / cfg['source_experiment'], REPO / cfg['classical_reference']
    n, alpha = cfg['samples'], cfg['significance_level']

    valid = list(csv.DictReader(open(src / 'validation_results.csv')))
    perf = {r['config_id']: r for r in csv.DictReader(open(src / 'performance_summary.csv'))}
    classical_obs = {r['N']: r for r in json.loads((ref / 'processed/validation_results.json').read_text())
                     if r['algorithm'] == 'basic'}

    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='experiment12-') as tmp:
        exe, build_cmd = build_exporter(Path(tmp))
        rows, passing_rows, entry_rows = [], [], []
        for k, r in enumerate(valid, 1):
            N, H, T = int(r['N']), int(r['H']), int(r['T'])
            ents = terminal_entries(exe, N, H, T)
            delta, df = chi2_divergence(ents, cfg)
            if df != int(r['chi2_degrees_of_freedom']):
                raise ValueError('binning differs from Experiment 11')
            pred = chi2_prediction(delta, df, n, alpha)
            excess = float(r['chi2_statistic']) - df
            sd = math.sqrt(2 * (df + 2 * pred['lambda_pred']))
            p = perf[r['config_id']]
            row = dict(config_id=r['config_id'], algorithm='trapezoid', N=N, H=H, T=T, passed_all_4_seed1=int(r['rejections']) == 0,
                       terminal_entries=len(ents), table_values=(1 + H + T) * (5 * N + 2), chi2_df=df, delta_exact=delta, **pred,
                       observed_excess_seed1=excess, observed_z_seed1=excess / math.sqrt(2 * df),
                       consistency_sd=(excess - pred['lambda_pred']) / sd, observed_rejections_seed1=int(r['rejections']),
                       observed_ks_seed1=float(r['ks_statistic']), stream_sha256_seed1=r['stream_sha256'],
                       median_throughput_msps=float(p['median_throughput_msamples_per_s']),
                       speedup_vs_classical=float(p['speedup_vs_classical']))
            if row['passed_all_4_seed1']:
                row.update(full_metrics(ents, cfg))
                passing_rows.append(row)
                entry_rows += [dict(config_id=r['config_id'], **e) for e in ents]
            rows.append(row)
            print(f"[{k}/{len(valid)}] {r['config_id']}: delta={delta:.4e} lambda={pred['lambda_pred']:.2f} "
                  f"observed={excess:.1f} ({row['consistency_sd']:+.2f} sd)", flush=True)

    classical_rows = []
    for N in sorted({int(r['N']) for r in valid}):
        obs = classical_obs[N]
        chi = obs['tests']['chi_square']
        df = chi['degrees_of_freedom']
        excess = chi['statistic'] - df
        p = perf[f'classical_N{N}']
        classical_rows.append(dict(config_id=f'classical_N{N}', algorithm='classical', N=N, H='', T='', terminal_entries='',
            table_values=2 * N, chi2_df=df, delta_exact=0.0, lambda_pred=0.0, z_pred=0.0, p_reject_chi2=alpha,
            n_detect_50=math.inf, n_detect_90=math.inf, observed_excess_seed1=excess, observed_z_seed1=excess / math.sqrt(2 * df),
            consistency_sd=excess / math.sqrt(2 * df), observed_rejections_seed1=sum(v['reject'] for v in obs['tests'].values()),
            observed_ks_seed1=obs['tests']['kolmogorov_smirnov']['statistic'], ks_exact=0.0, support=math.inf, variance=1.0,
            variance_error=0.0, median_throughput_msps=float(p['median_throughput_msamples_per_s']), speedup_vs_classical=1.0,
            **{f'tail_ratio_{t}': 1.0 for t in cfg['tail_points']}))

    def write(name, data):
        fields = list(dict.fromkeys(k for d in data for k in d))
        with (out / name).open('x', newline='') as f:
            wr = csv.DictWriter(f, fieldnames=fields)
            wr.writeheader(); wr.writerows(data)

    write('model_validation_all.csv', rows + classical_rows)
    write('exact_metrics_passing.csv', passing_rows + [c for c in classical_rows if c['N'] in {r['N'] for r in passing_rows}])
    write('terminal_entries_passing.csv', entry_rows)
    git = lambda *a: subprocess.run(['git', '-C', str(REPO), *a], capture_output=True, text=True).stdout.strip()
    (out / 'metadata.json').write_text(json.dumps(dict(
        experiment_id='experiment12', created_utc=datetime.now(timezone.utc).isoformat(), config=cfg,
        method='exact mixture of trapezoid densities; tables exported from c/ziggurat_trapezoid.c',
        random_numbers_generated=0, exporter_build_command=build_cmd,
        sampler_source_sha256=sha256(REPO / 'c/ziggurat_trapezoid.c'),
        exporter_source_sha256=sha256(Path(__file__).with_name('experiment12_dump_tables.c')),
        experiment11_validation_sha256=sha256(src / 'validation_results.csv'),
        git_commit=git('rev-parse', 'HEAD'), git_dirty_files=len(git('status', '--porcelain').splitlines()),
        gcc=subprocess.run(['gcc', '--version'], capture_output=True, text=True).stdout.splitlines()[0],
        python=platform.python_version(), numpy=np.__version__, scipy=__import__('scipy').__version__,
        configurations_total=len(rows), configurations_passing=len(passing_rows)), indent=2))
    print(f'\n{len(passing_rows)} passing configurations with full metrics; {len(rows)} validated; results in {out}')


if __name__ == '__main__':
    main()
