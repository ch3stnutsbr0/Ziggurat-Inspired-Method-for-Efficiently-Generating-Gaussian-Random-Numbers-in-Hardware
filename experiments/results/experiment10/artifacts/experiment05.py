"""Experiment 05: xoshiro256+ validation and speed versus samples at N=8..256.
Each run generates exactly 2^25 values; validation samples are streamed into RAM.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import shutil
import statistics
import subprocess
import tempfile

import numpy as np
import psutil
import scipy
from utils import load_config, sha256_file, validation_settings, write_json
import runner
import validation

LAYERS = [8, 16, 32, 64, 128, 256]
SAMPLES = 2**25
LABELS = {'basic': 'Classical Ziggurat', 'trapezoid': 'Ziggurat-Trapezoid'}
TESTS = {'chi_square': 'chi2', 'kolmogorov_smirnov': 'ks',
         'cramer_von_mises': 'cvm', 'anderson_darling': 'ad'}


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    write_json(path, value, replace=path.exists())
    if json.loads(path.read_text()) != value:
        raise ValueError(f'JSON readback failed: {path}')


def save_csv(path, rows):
    with path.open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def inventory(root, exclude):
    return {str(p.relative_to(root)): (sha256_file(p), p.stat().st_size, p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file() and not p.resolve().is_relative_to(exclude)}


def check_config(config):
    if config.get('experiment_id') != 'experiment05' or config.get('prng') != {'type': 'xoshiro256plus'}:
        raise ValueError('Experiment 05 requires xoshiro256plus only')
    if config.get('layers') != LAYERS or config.get('algorithms') != ['basic', 'trapezoid']:
        raise ValueError('Require both methods and N=8,16,32,64,128,256')
    if config.get('samples_per_run') != SAMPLES or config.get('trapezoid') != {'head': 2, 'tail': 4}:
        raise ValueError('Require 2^25 samples per run and H=2/T=4')
    performance = config['performance']
    checkpoints = performance['checkpoints']
    if (not checkpoints or len(checkpoints)>32 or checkpoints[-1] != SAMPLES or
            checkpoints != sorted(set(checkpoints)) or
            any(type(x) is not int or not 10000<=x<=SAMPLES for x in checkpoints)):
        raise ValueError('Require increasing checkpoints ending at 2^25')
    if type(performance['repetitions']) is not int or not 1<=performance['repetitions']<=20:
        raise ValueError('Require 1..20 timing repetitions')
    if type(config['seed']) is not int or not 0<=config['seed']<=2**64-1:
        raise ValueError('Invalid uint64 seed')
    return validation_settings(config)


def full_report(stdout, run):
    lines=[line.split(': ',1)[1] for line in stdout.splitlines() if line.startswith('BENCHMARK_JSON: ')]
    reports=[json.loads(line) for line in lines]
    if not reports:
        raise ValueError('Missing C benchmark report')
    for result in reports:
        runner.check_summary(result, dict(run, samples=result['num_samples']))
        if (result['prng']!='xoshiro256plus' or result['algorithm']!=run['algorithm'] or
                result['N']!=run['N'] or result['seed']!=run['seed'] or
                result['compiler_optimization']!='O2' or result['warmup_samples']!=0 or
                (run['algorithm']=='trapezoid' and (result['H'],result['T'])!=(run.get('H',2),run.get('T',4)))):
            raise ValueError('Incorrect benchmark configuration')
        if result['sampling_time_seconds']<=0:
            raise ValueError('Nonpositive timing')
    return reports


def collect(executable, run):
    """No sample files: pipe exactly 2^25 binary64 observations into one array."""
    values=np.empty(SAMPLES,dtype='<f8'); view=memoryview(values).cast('B')
    read_fd,write_fd=os.pipe();process=None
    argv=[str(executable),'--algorithm',run['algorithm'],'--layers',str(run['N']),
          '--prng','xoshiro256plus','--seed',str(run['seed']),'--samples',str(SAMPLES),
          '--report-json','--output',f'/dev/fd/{write_fd}']
    if run['algorithm']=='trapezoid': argv+=['--head',str(run.get('H',2)),'--tail',str(run.get('T',4))]
    try:
        process=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,pass_fds=(write_fd,))
        os.close(write_fd);write_fd=None
        with os.fdopen(read_fd,'rb',buffering=0) as pipe:
            read_fd=None;received=0
            while received<len(view):
                amount=pipe.readinto(view[received:])
                if not amount: break
                received+=amount
            extra=pipe.read(1)
        stdout,stderr=process.communicate()
        if process.returncode or received!=len(view) or extra:
            raise RuntimeError(f'Incomplete stream: {received}/{len(view)}; {stderr.decode()}')
        reports=full_report(stdout.decode(),run)
        if len(reports)!=1 or reports[0]['num_samples']!=SAMPLES:
            raise ValueError('Validation sample count mismatch')
        return values,reports[0],hashlib.sha256(view).hexdigest()
    finally:
        view.release()
        if read_fd is not None: os.close(read_fd)
        if write_fd is not None: os.close(write_fd)
        if process is not None and process.poll() is None: process.kill();process.wait()


def aggregate(records, checkpoints):
    rows=[]
    for n in LAYERS:
        for samples in checkpoints:
            pair={}
            for algorithm in LABELS:
                group=[r for r in records if r['algorithm']==algorithm and r['N']==n and r['num_samples']==samples]
                if len({r['checksum'] for r in group})!=1:
                    raise ValueError('Repeated seed produced different streams')
                speeds=[r['throughput_samples_per_second']/1e6 for r in group]
                median=statistics.median(speeds);pair[algorithm]=median
                rows.append(dict(experiment_id='experiment05',algorithm=algorithm,prng='xoshiro256plus',
                    N=n,H=None if algorithm=='basic' else 2,T=None if algorithm=='basic' else 4,
                    measured_samples=samples,generated_samples=SAMPLES,repetitions=len(group),
                    median_Msamples_s=median,q1_Msamples_s=float(np.percentile(speeds,25)),
                    q3_Msamples_s=float(np.percentile(speeds,75)),
                    median_sampling_seconds=statistics.median(r['sampling_time_seconds'] for r in group)))
            for row in rows[-2:]: row['speedup_vs_classical']=row['median_Msamples_s']/pair['basic']
    return rows


def plot(root, rows, checkpoints):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(2,3,figsize=(13.5,8.1),sharex=True,sharey=True)
    fig.subplots_adjust(left=.075,right=.985,bottom=.11,top=.79,hspace=.22,wspace=.12)
    upper=math.ceil(max(r['q3_Msamples_s'] for r in rows)/20)*20
    for ax,n in zip(axes.flat,LAYERS):
        for algorithm,color,marker in [('basic','#2369a8','o'),('trapezoid','#cf612c','s')]:
            group=[r for r in rows if r['N']==n and r['algorithm']==algorithm]
            med=np.array([r['median_Msamples_s'] for r in group])
            ax.plot(checkpoints,med,color=color,marker=marker,lw=2,ms=5)
            ax.fill_between(checkpoints,[r['q1_Msamples_s'] for r in group],
                            [r['q3_Msamples_s'] for r in group],color=color,alpha=.16)
        ax.set_title(f'N = {n} layers',fontweight='bold')
        ax.set_xscale('log');ax.set_ylim(0,upper);ax.grid(True,alpha=.2)
        ax.set_xticks(checkpoints, [f'{x/1e6:.3g}M' if x>=1e6 else f'{x/1e3:g}k' for x in checkpoints])
    fig.suptitle('Experiment 05 · xoshiro256+\nGaussian sampling speed versus measured sample count',fontsize=17,fontweight='bold',y=.99)
    fig.supxlabel('Samples measured from the start of each fixed 2^25-sample run (log scale)',y=.025)
    fig.supylabel('Throughput (million Gaussian samples / second)',x=.015)
    handles=[Line2D([0],[0],color='#2369a8',marker='o',lw=2,label='Classical Ziggurat'),
             Line2D([0],[0],color='#cf612c',marker='s',lw=2,label='Ziggurat-Trapezoid · H=2, T=4')]
    fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.5,.895),ncol=2,frameon=False)
    fig.savefig(root/'figures/speed_vs_samples.png',dpi=250)
    fig.savefig(root/'figures/speed_vs_samples.svg')
    plt.close(fig)


def report(root, config, performance, results, metadata):
    lines=['# Experiment 05 — xoshiro256+ only','',
        'Both methods use N=8,16,32,64,128,256, seed 1, and -O2. Trapezoid uses H=2/T=4. '
        'Each timing or validation run generates exactly 2^25 = 33,554,432 samples. No Gaussian warmup is generated. '
        'Performance uses five repetitions and cumulative checkpoints within each fixed-length run; '
        'checkpoints reuse a single stream rather than generating separate datasets.','',
        '![Speed versus samples](../figures/speed_vs_samples.png)','',
        'Curves show median cumulative throughput; shaded bands are the interquartile range of five repetitions. '
        'Earlier and later points from one run are dependent. Timings exclude initialization and table construction, '
        'and no validation/output buffering is included. The experiment-only C harness retains the original sampling loop’s '
        'generate/checksum/sum/sumsq work, with a volatile checksum. Clock reads and small checkpoint bookkeeping between '
        'prefixes contribute to subsequent cumulative timings. The existing C benchmark and Gaussian source are unchanged.','',
        '## Full-run median speed','',
        '| N | Classical M/s | Trapezoid M/s | Trapezoid / Classical |','|---:|---:|---:|---:|']
    for n in LAYERS:
        group={r['algorithm']:r for r in performance if r['N']==n and r['measured_samples']==SAMPLES}
        lines.append(f"| {n} | {group['basic']['median_Msamples_s']:.3f} | {group['trapezoid']['median_Msamples_s']:.3f} | {group['trapezoid']['speedup_vs_classical']:.3f}× |")
    lines+=['','## Full-data validation','',
        'Every dataset is tested against fixed N(0,1) using the existing Chi-square, KS, CvM and AD code. '
        'Alpha=0.05; no parameter fitting, standardization, or multiple-testing adjustment. '
        'PASS means failure to reject, not proof of Gaussianity. Chi-square retains 100 interior bins over [-5,5], '
        'two unbounded tails, and minimum-expected-count merging at 5. AD retains its existing finite-n approximation '
        'and critical-value decision; an unavailable p-value is recorded as NA. Results use one seed.','',
        '| Method | N | Mean | Variance | Chi-square | KS | CvM | AD |','|---|---:|---:|---:|---|---|---|---|']
    for row in results:
        decision=['REJECT' if row['tests'][test]['reject'] else 'PASS' for test in TESTS]
        lines.append(f"| {LABELS[row['algorithm']]} | {row['N']} | {row['mean']:.7g} | {row['variance']:.7g} | "+' | '.join(decision)+' |')
    failures=[dict(algorithm=r['algorithm'],N=r['N'],test=t,statistic=v['statistic'],p_value=v['p_value'])
              for r in results for t,v in r['tests'].items() if v['reject']]
    lines+=['',f'Rejections: {len(failures)} of {len(results)*4} tests.','',
        'Full statistics, p-values, critical values and degrees of freedom are in `../processed/validation_results.json` '
        'and `../tables/validation_results.csv`. Raw observations were transferred through a pipe into RAM and discarded '
        'after full-data validation; no sample binaries, previews or subsets were saved.','',
        '## Reproducibility','',f"Compiler: {metadata['compiler'].splitlines()[0]}; platform: {metadata['platform']}.",
        'Flags: `-std=c11 -Wall -Wextra -pedantic -O2`. Sources, configuration, hashes, commands and execution counts '
        'are retained under artifacts/ and execution_order.json. The validation code, previous experiment results '
        'and original C executable/sources were checked for changes. No commit was made.','']
    (root/'reports/experiment_report.md').write_text('\n'.join(lines))
    return failures


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path(__file__).with_suffix('.yaml'))
    parser.add_argument('--output-root',type=Path)
    args=parser.parse_args();repo=Path(__file__).resolve().parents[1]
    config=load_config(args.config);settings=check_config(config)
    root=args.output_root.resolve() if args.output_root else (repo/config['output_dir']).resolve()
    if root.exists(): raise ValueError('Experiment 05 output exists; use a fresh output-root')
    sources=sorted((repo/'c').glob('*.c'))+sorted((repo/'c').glob('*.h'))
    protected=sources+[repo/'c/Makefile',repo/'c/benchmark',repo/'experiments/validation.py']+list((repo/'matlab').glob('*.m'))
    protected_hashes={str(p.relative_to(repo)):sha256_file(p) for p in protected}
    previous=inventory(repo/'experiments/results',root)
    required_memory=SAMPLES*16+24*1_000_000*8+1024**3
    available=psutil.virtual_memory().available
    if available<required_memory: raise RuntimeError(f'RAM preflight: need {required_memory}, available {available}')
    for name in ('artifacts','processed','tables','figures','reports','raw/performance','raw/validation'):
        (root/name).mkdir(parents=True)
    for path in (Path(__file__),Path(__file__).with_suffix('.yaml'),Path(__file__).with_name('experiment05_benchmark.c')):
        shutil.copy2(path,root/'artifacts'/path.name)
    shutil.copy2(repo/'experiments/validation.py',root/'artifacts/validation.py')
    for path in sources:
        dest=root/'artifacts/c'/path.name;dest.parent.mkdir(exist_ok=True);shutil.copy2(path,dest)
    session=dict(experiment_id='experiment05',status='running',started_at=now(),configuration=config,
        platform=platform.platform(),numpy_version=np.__version__,scipy_version=scipy.__version__,
        memory_available_bytes=available,memory_estimate_bytes=required_memory,
        source_sha256=protected_hashes,raw_samples_saved=False,executions=[],errors=[])
    session_path=root/'execution_order.json';save(session_path,session)
    records=[];results=[];checkpoints=config['performance']['checkpoints'];repetitions=config['performance']['repetitions']
    try:
        with tempfile.TemporaryDirectory(prefix='experiment05-',dir='/private/tmp') as temporary:
            work=Path(temporary);normal=work/'benchmark';timing=work/'checkpoint_benchmark'
            flags=['-std=c11','-Wall','-Wextra','-pedantic','-O2']
            core=[repo/'c'/name for name in ('ziggurat_basic.c','ziggurat_trapezoid.c','xoshiro256plus.c',
                    'prng.c','ziggurat_basic_xoshiro256plus.c','ziggurat_trapezoid_xoshiro256plus.c')]
            builds=[['/usr/bin/clang',*flags,'-I',str(repo/'c'),'-DBENCHMARK_OPTIMIZATION="O2"',
                      *map(str,sorted((repo/'c').glob('*.c'))),'-o',str(normal),'-lm'],
                    ['/usr/bin/clang',*flags,'-I',str(repo/'c'),str(Path(__file__).with_name('experiment05_benchmark.c')),
                     *map(str,core),'-o',str(timing),'-lm']]
            session.update(compiler=subprocess.check_output(['/usr/bin/clang','--version'],text=True),
                           compiler_flags=flags,build_commands=builds)
            for build in builds:
                done=subprocess.run(build,capture_output=True,text=True,check=True)
                if done.stderr: raise ValueError(f'Compiler diagnostics: {done.stderr}')
            session.update(validation_executable_sha256=sha256_file(normal),timing_executable_sha256=sha256_file(timing))
            save(session_path,session)
            configurations=[dict(algorithm=a,N=n,prng='xoshiro256plus',seed=config['seed'],samples=SAMPLES)
                            for n in LAYERS for a in LABELS]
            for repetition in range(1,repetitions+1):
                order=configurations.copy();random.Random(config['seed']+repetition).shuffle(order)
                for run in order:
                    argv=[str(timing),run['algorithm'],str(run['N']),str(run['seed']),*map(str,checkpoints)]
                    done=subprocess.run(argv,capture_output=True,text=True,check=True)
                    points=full_report(done.stdout,run)
                    if [p['num_samples'] for p in points]!=checkpoints or any(p['generated_samples']!=SAMPLES for p in points):
                        raise ValueError('Checkpoint identity/count mismatch')
                    for point in points: records.append(dict(point,repetition=repetition))
                    session['executions'].append(dict(kind='performance',**run,repetition=repetition,
                        command=argv,execution_order=len(session['executions'])+1))
                save(root/'raw/performance/performance_runs.json',records);save(session_path,session)
                print(f'Performance round {repetition}/{repetitions}: 12 fixed 2^25-sample runs complete',flush=True)
            rows=aggregate(records,checkpoints)
            save_csv(root/'processed/performance_vs_samples.csv',rows)
            shutil.copy2(root/'processed/performance_vs_samples.csv',root/'tables/performance_vs_samples.csv')
            for run in configurations:
                if psutil.virtual_memory().available<required_memory:
                    raise RuntimeError('Available RAM fell below validation estimate')
                print(f"Validating {run['algorithm']} N={run['N']} at 2^25 samples",flush=True)
                values,c_summary,stream_hash=collect(normal,run)
                try: numerical=validation.run_tests_chunked(values,settings,[])
                finally: del values
                if set(numerical['tests'])!=set(TESTS): raise ValueError('Missing statistical test')
                for field in ('mean','variance'):
                    if not math.isclose(numerical[field],c_summary[field],rel_tol=1e-10,abs_tol=1e-10):
                        raise ValueError('Validation moments differ from C summary')
                timings=[r for r in records if r['algorithm']==run['algorithm'] and r['N']==run['N'] and r['num_samples']==SAMPLES]
                if len(timings)!=repetitions or any(r['checksum']!=c_summary['checksum'] for r in timings):
                    raise ValueError('Timing and validation streams differ')
                item=dict(run,H=None if run['algorithm']=='basic' else 2,T=None if run['algorithm']=='basic' else 4,
                          stream_bytes=SAMPLES*8,stream_sha256=stream_hash,raw_samples_saved=False,
                          validation_code_sha256=protected_hashes['experiments/validation.py'],**numerical)
                results.append(item)
                save(root/'raw/validation'/f"{run['algorithm']}_N{run['N']}_validation.json",item)
                save(root/'processed/validation_results.json',results)
                session['executions'].append(dict(kind='validation',**run,tests=4,execution_order=len(session['executions'])+1))
                save(session_path,session)
                print('  '+', '.join(f"{TESTS[t]}={'REJECT' if v['reject'] else 'PASS'}" for t,v in numerical['tests'].items()),flush=True)
        validation_rows=[]
        for item in results:
            row={key:item[key] for key in ('algorithm','prng','N','H','T','samples','seed','mean','variance')}
            for test,label in TESTS.items():
                result=item['tests'][test]
                row.update({label+'_statistic':result['statistic'],label+'_p_value':'NA' if result['p_value'] is None else result['p_value'],
                            label+'_decision':'REJECT' if result['reject'] else 'PASS'})
            validation_rows.append(row)
        save_csv(root/'tables/validation_results.csv',validation_rows)
        plot(root,rows,checkpoints)
        failures=report(root,config,rows,results,session)
        if inventory(repo/'experiments/results',root)!=previous: raise ValueError('Earlier experiment results changed')
        if {str(p.relative_to(repo)):sha256_file(p) for p in protected}!=protected_hashes:
            raise ValueError('Existing C, validation or MATLAB files changed')
        if len(session['executions'])!=12*repetitions+12 or list(root.rglob('*.bin')):
            raise ValueError('Execution count or sample-retention mismatch')
        session.update(status='successful',ended_at=now(),performance_executions=12*repetitions,
            validation_executions=12,statistical_tests_completed=48,validation_rejections=failures,
            previous_results_and_existing_sources_unchanged=True)
        save(session_path,session)
        save(root/'verification.json',dict(status='successful',verified_at=now(),raw_sample_files=0,
            statistical_tests_completed=48,validation_rejections=failures,
            previous_results_and_existing_sources_unchanged=True,
            output_sha256={str(p.relative_to(root)):sha256_file(p) for p in root.rglob('*') if p.is_file()}))
        print(json.dumps(dict(status='successful',output=str(root),validation_rejections=failures),indent=2),flush=True)
    except (Exception,KeyboardInterrupt) as exc:
        session.update(status='failed',ended_at=now());session['errors'].append(f'{type(exc).__name__}: {exc}')
        save(session_path,session);raise


if __name__=='__main__': main()
