"""Experiment 04: repeat the six-layer comparison at 100 million and 2**25 samples.

Run: python3 -B experiments/experiment04.py [--output-root NEW_DIRECTORY]
Keeps only numerical results, PNG plots, reports, and reproducibility artifacts.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import subprocess

from utils import sha256_file, write_json

SAMPLE_COUNTS = (100_000_000, 2**25)
LAYERS = (8, 16, 32, 64, 128, 256)


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(path.read_text())


def checked_json(path, obj):
    write_json(path, obj, replace=path.exists())
    if read(path) != obj:
        raise ValueError(f'JSON readback failed: {path}')


def snapshot(root, exclude):
    return {str(p.relative_to(root)): (sha256_file(p), p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob('*')) if p.is_file() and not p.resolve().is_relative_to(exclude)}


def csv_rows(path):
    with path.open(newline='') as f:
        return list(csv.DictReader(f))


def save_csv(path, rows):
    with path.open('x', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    expected = [{k:str(v) for k,v in row.items()} for row in rows]
    if csv_rows(path) != expected:
        raise ValueError(f'CSV readback failed: {path}')


def make_report(profile, samples, performance, results, metadata):
    lines = [f'# Experiment 04 — {samples:,} samples', '',
        'N=8,16,32,64,128,256; Trapezoid H=2,T=4; seed=1; compiler -O2. '
        'Five separate performance repetitions per algorithm and N, each with 100,000 warm-up samples '
        'outside timing, followed by seed reset. Each Trapezoid validation processes the complete dataset '
        'using the existing fixed N(0,1) tests. No raw sample file or preview is saved.', '',
        '## Median performance', '',
        '| N | Classical M/s | Trapezoid M/s | Speedup | Classical time (s) | Trapezoid time (s) |',
        '|---:|---:|---:|---:|---:|---:|']
    for row in performance:
        lines.append('| '+row['N']+' | '+' | '.join(f"{float(row[k]):.8g}" for k in (
            'classical_throughput_M_per_s','trapezoid_throughput_M_per_s','speedup',
            'classical_median_time_s','trapezoid_median_time_s'))+' |')
    faster = [r['N'] for r in performance if float(r['speedup'])>1]
    lines += ['', f'Trapezoid has higher measured medians at N={", ".join(faster) or "none"}. '
        'Small differences should be interpreted with the saved repetition timings. '
        'Performance measurements do not establish statistical correctness.', '',
        f'![Throughput versus layers](../../figures/{profile}/throughput_vs_layers.png)', '',
        '## Trapezoid validation', '',
        'Alpha=0.05; no fitted parameters or standardization. PASS means fail-to-reject. '
        'Chi-square retains the existing 100 equal-width interior bins over [-5,5], two unbounded tails, '
        'and expected-count-only merging with minimum expected count 5. Changes in final bin count '
        'with sample size reflect this unchanged rule. AD uses its existing approximate calibration '
        'and critical-value decision; an unavailable p-value is shown as NA. Every test cell gives '
        'statistic / p-value / decision.', '',
        '| N | Mean | Variance | Chi2 bins / df | Chi-square | KS | CvM | AD |',
        '|---:|---:|---:|---|---|---|---|---|']
    for row in results:
        tests = ' | '.join(f"{float(row[t+'_statistic']):.9g} / {row[t+'_pvalue']} / {row[t+'_result']}"
                           for t in ('chi2','ks','cvm','ad'))
        lines.append(f"| {row['N']} | {row['mean']} | {row['variance']} | {row['chi2_final_bins']} / {row['chi2_df']} | {tests} |")
    failures = [(int(row['N']), test) for row in results for test in ('chi2','ks','cvm','ad') if row[test+'_result']=='FAIL']
    lines += ['', f'Rejections: {failures if failures else "none"}.', '',
        'These are results from one seed. Larger samples increase power against fixed approximation errors; '
        'passing does not prove exact Gaussianity. No second-level p-value uniformity tests were performed.', '',
        '## Reproducibility', '',
        f"Executable SHA-256: `{metadata['executable_sha256']}`.", '',
        f"Validation code SHA-256: `{metadata['validation_code_sha256']}`.", '',
        f"NumPy {metadata['numpy_version']}; SciPy {metadata['scipy_version']}.",
        f'Full-precision results and calibration details: `../../processed/{profile}/trapezoid_validation_vs_layers.json`. '
        f'All repetition records: `../../raw/performance/{profile}/performance_runs.json`.']
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root',type=Path)
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1]
    root=args.output_root.resolve() if args.output_root else repo/'experiments/results/experiment04'
    if root.exists():
        raise ValueError('Experiment 04 output exists; refusing to overwrite or rerun completed work')
    previous=snapshot(repo/'experiments/results',root)
    reference=read(repo/'experiments/results/experiment03/artifacts/layers_experiment.json')
    sources={name:sha256_file(repo/name) for name in reference['source_sha256']}
    if sources!=reference['source_sha256'] or sha256_file(repo/'experiments/validation.py')!=reference['validation_code_sha256']:
        raise ValueError('Sampling/benchmark/validation source differs from Experiment 03; experiment not started')
    root.mkdir(parents=True)
    for folder in ('artifacts','processed','tables','figures','reports','raw/performance','raw/validation','_staging'):
        (root/folder).mkdir(parents=True)
    config=dict(experiment_id='experiment04',sample_counts=list(SAMPLE_COUNTS),layers=list(LAYERS),H=2,T=4,
        seed=1,performance_repetitions=5,warmup_samples=100000,compiler_optimization='O2',
        validation_algorithms=['trapezoid'],raw_samples_saved=False,
        validation_settings=reference['validation_settings'])
    checked_json(root/'artifacts/experiment04_config.json',config)
    for p in (Path(__file__),repo/'experiments/layers_comparison.py'):
        shutil.copy2(p,root/'artifacts'/p.name)
    session=dict(experiment_id='experiment04',status='running',started_at=now(),planned=132,completed=[],
        sample_counts=list(SAMPLE_COUNTS),profiles=[],errors=[],raw_samples_saved=False,
        sampling_source_sha256=sources,validation_code_sha256=reference['validation_code_sha256'],
        driver_sha256=sha256_file(__file__),worker_sha256=sha256_file(repo/'experiments/layers_comparison.py'))
    checked_json(root/'execution_order.json',session)
    perf_combined=[]
    val_combined=[]
    full_combined=[]
    reports=[]
    matched_seed1=[]
    try:
        for samples in SAMPLE_COUNTS:
            profile=f'samples_{samples}'
            stage=root/'_staging'/profile
            print(f'\nStarting {profile}: 60 performance runs and six validations',flush=True)
            cmd=[sys.executable,'-B',str(repo/'experiments/layers_comparison.py'),
                 '--samples',str(samples),'--output-root',str(stage),'--quiet']
            done=subprocess.run(cmd,cwd=repo)
            if done.returncode:
                raise RuntimeError(f'{profile} worker failed with exit code {done.returncode}; saved partial results preserved')
            meta=read(stage/'artifacts/layers_experiment.json')
            runs=read(stage/'raw/performance/performance_runs.json')
            full=read(stage/'processed/trapezoid_validation_vs_layers.json')
            performance=csv_rows(stage/'processed/performance_vs_layers.csv')
            results=csv_rows(stage/'processed/trapezoid_validation_vs_layers.csv')
            if (meta['status']!='successful' or len(runs)!=60 or len(full)!=6 or
                    meta['performance_samples']!=samples or meta['validation_samples']!=samples or
                    meta['validation_settings']!=reference['validation_settings']):
                raise ValueError('Profile execution count, sample count, or statistical settings mismatch')
            for name,digest in meta['output_sha256'].items():
                if sha256_file(stage/name)!=digest:
                    raise ValueError(f'Worker output integrity failed: {profile}/{name}')
            for n in LAYERS:
                for algorithm in ('basic','trapezoid'):
                    group=[r for r in runs if r['N']==n and r['algorithm']==algorithm]
                    if len(group)!=5 or any(r['num_samples']!=samples or r['warmup_samples']!=100000 for r in group):
                        raise ValueError('Performance sample/repetition/warmup mismatch')
                r=next(v for v in full if v['N']==n)
                if r['samples']!=samples or r['stream_bytes']!=8*samples or len(r['tests'])!=4:
                    raise ValueError('Validation stream count or test set mismatch')
                if samples==100_000_000 and n in (8,16,32):
                    old=read(repo/f'experiments/results/experiment_01/raw/validation/trapezoid_N{n}_H2_T4_seed1_validation/validation_result.json')
                    if r['stream_sha256']!=old['sample_sha256']:
                        raise ValueError('Seed-1 sample sequence differs from Experiment 01')
                    for test in r['tests']:
                        for field in ('statistic','p_value'):
                            a,b=r['tests'][test][field],old['tests'][test][field]
                            if (a is None)!=(b is None) or (a is not None and not math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12)):
                                raise ValueError('Repeated fixed-seed validation differs from Experiment 01')
                    matched_seed1.append(n)
            # Place each sample profile inside the same top-level folder families.
            mapping={}
            for folder in ('processed','figures','artifacts','raw/performance'):
                destination=root/folder/profile
                (stage/folder).rename(destination)
                for p in destination.rglob('*'):
                    if p.is_file():
                        logical=str(p.relative_to(destination))
                        mapping[f'{folder}/{logical}']=f'{folder}/{profile}/{logical}'
            for folder in ('tables','reports','raw/validation'):
                (root/folder/profile).mkdir(parents=True)
            for name in ('performance_vs_layers.csv','trapezoid_validation_vs_layers.csv'):
                shutil.copy2(root/'processed'/profile/name,root/'tables'/profile/name)
            for r in full:
                checked_json(root/'raw/validation'/profile/f"trapezoid_N{r['N']}_H2_T4_seed1_validation.json",r)
            meta.update(experiment_id='experiment04',sample_profile=profile,output_root=str(root),
                        output_sha256={mapping[k]:v for k,v in meta['output_sha256'].items()})
            checked_json(root/'artifacts'/profile/'layers_experiment.json',meta)
            report=make_report(profile,samples,performance,results,meta)
            (root/'reports'/profile/'experiment_report.md').write_text(report)
            reports.append((profile,samples,report,results))
            perf_combined.extend(dict(samples=samples,**r) for r in performance)
            val_combined.extend(results)
            full_combined.extend(full)
            for item in meta['executions']:
                session['completed'].append(dict(item,samples=samples,sample_profile=profile,
                    execution_order=len(session['completed'])+1))
            session['profiles'].append(dict(sample_profile=profile,samples=samples,status='successful',
                executable_sha256=meta['executable_sha256'],performance_executions=60,
                validation_executions=6,statistical_tests_completed=24))
            # Remove only empty staging directories; never discard partial results.
            for p in sorted(stage.rglob('*'),key=lambda p:len(p.parts),reverse=True):
                if p.is_dir():
                    p.rmdir()
            stage.rmdir()
            checked_json(root/'execution_order.json',session)
            print(f'{profile} complete: tables, numerical records, figure, and report verified',flush=True)
        (root/'_staging').rmdir()
        save_csv(root/'processed/performance_vs_layers.csv',perf_combined)
        save_csv(root/'processed/trapezoid_validation_vs_layers.csv',val_combined)
        checked_json(root/'processed/trapezoid_validation_vs_layers.json',full_combined)
        for name in ('performance_vs_layers.csv','trapezoid_validation_vs_layers.csv'):
            shutil.copy2(root/'processed'/name,root/'tables'/name)
        failures=[dict(samples=int(r['samples']),N=int(r['N']),test=t,p_value=r[t+'_pvalue'])
                  for r in val_combined for t in ('chi2','ks','cvm','ad') if r[t+'_result']=='FAIL']
        overview=['# Experiment 04 — Sample-count comparison','',
            'Both sample sizes repeat Experiment 03 methodology: six layer counts, H=2,T=4, seed=1, '
            '-O2, five warmed timing repetitions for each algorithm, and Trapezoid-only full-data validation. '
            'There are 120 performance runs, 12 validation runs, and 48 statistical tests. '
            'No raw Gaussian samples, previews, or subsets were saved.', '',
            'Numerical results, individual records, tables, figures, and metadata are separated into '
            '`samples_100000000` and `samples_33554432` subfolders within the usual folder families. '
            'Combined numerical tables are also provided at the top of processed/ and tables/.', '',
            f'Rejections: {failures}.', '',
            'PASS means failure to reject, not proof of Gaussianity. This experiment uses one seed; '
            'no p-value uniformity testing was performed. Different sample counts change test power '
            'and can change the final Chi-square bin count under the same minimum-expected-count rule.', '',
            f'The 100-million-sample streams and test results at N={matched_seed1} match the existing '
            'Seed 1 results from Experiment 01. This is a reproducibility check, not an independent replicate.', '',
            'Previous experiments, original C executable, sampling algorithms, PRNG, validation code, '
            'and MATLAB files were verified unchanged.', '',
            'Reproduce using `python3 -B experiments/experiment04.py --output-root NEW_DIRECTORY`; '
            'the existing output directory is protected from overwrite.', '']
        for profile,samples,text,results in reports:
            overview += [f'## {samples:,} samples','',f'[Complete profile report]({profile}/experiment_report.md)','',
                text.split('## Median performance',1)[1].split('## Reproducibility',1)[0].replace(
                    f'../../figures/{profile}/',f'../figures/{profile}/'), '']
        (root/'reports/experiment_report.md').write_text('\n'.join(overview))
        if snapshot(repo/'experiments/results',root)!=previous:
            raise ValueError('An earlier experiment result changed')
        if {name:sha256_file(repo/name) for name in sources}!=sources:
            raise ValueError('C sampling or benchmark source changed during execution')
        if sha256_file(repo/'experiments/validation.py')!=reference['validation_code_sha256']:
            raise ValueError('Statistical validation code changed during execution')
        if len(session['completed'])!=132 or len(full_combined)!=12 or list(root.rglob('*.bin')):
            raise ValueError('Final execution, validation count, or sample-retention mismatch')
        session.update(status='successful',ended_at=now(),performance_executions=120,
            validation_executions=12,statistical_tests_completed=48,
            seed1_100m_reproducibility_verified_N=matched_seed1,validation_failures=failures,
            earlier_experiment_results_unchanged=True)
        checked_json(root/'execution_order.json',session)
        checked_json(root/'verification.json',dict(status='successful',verified_at=now(),
            sample_counts=list(SAMPLE_COUNTS),performance_executions=120,validation_executions=12,
            statistical_tests_completed=48,raw_sample_files=0,earlier_experiment_results_unchanged=True,
            validation_definitions_unchanged=True,seed1_100m_reproducibility_verified_N=matched_seed1,
            output_sha256={str(p.relative_to(root)):sha256_file(p) for p in sorted(root.rglob('*')) if p.is_file()}))
        print(json.dumps(dict(status='successful',output=str(root),validation_failures=failures),indent=2),flush=True)
    except (Exception,KeyboardInterrupt) as exc:
        session.update(status='failed',ended_at=now())
        session['errors'].append(f'{type(exc).__name__}: {exc}')
        checked_json(root/'execution_order.json',session)
        raise


if __name__=='__main__':
    main()
