"""Experiment 06: trapezoid-only validation, 512 interior Chi-square bins.
Run python3 -B experiments/experiment06.py; raw samples remain in RAM.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import json
import math
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

import numpy as np
import psutil
import scipy
import experiment05 as shared
import validation
from utils import load_config, validation_settings, sha256_file


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path(__file__).with_suffix('.yaml'))
    parser.add_argument('--output-root',type=Path)
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1]
    config=load_config(args.config)
    expected=dict(experiment_id='experiment06',prng={'type':'xoshiro256plus'},
                  algorithms=['trapezoid'],layers=shared.LAYERS,
                  trapezoid={'head':2,'tail':4},samples_per_run=2**25)
    if any(config.get(k)!=v for k,v in expected.items()):
        raise ValueError('Experiment 06 requires trapezoid only, xoshiro256plus, N=8..256, H=2/T=4, 2^25 samples')
    seed=config.get('seed')
    if type(seed) is not int or not 0<=seed<=2**64-1:
        raise ValueError('seed must be an integer in [0, 2^64-1]')
    settings=validation_settings(config)
    if config['validation']!={'significance_level':.05,'chi_square':{'bins':512,'range':[-5.,5.],'minimum_expected_count':5}}:
        raise ValueError('Require 512 interior bins over [-5,5], minimum expected 5, alpha .05')
    root=args.output_root.resolve() if args.output_root else (repo/config['output_dir']).resolve()
    if root.exists(): raise ValueError('Output already exists; use a fresh --output-root')
    required_memory=2**25*16+24*1_000_000*8+1024**3
    if psutil.virtual_memory().available<required_memory: raise RuntimeError('Insufficient available RAM for in-memory validation')
    previous=shared.inventory(repo/'experiments/results',root)
    protected=list((repo/'c').glob('*.c'))+list((repo/'c').glob('*.h'))+[repo/'c/benchmark',repo/'c/Makefile',
        repo/'experiments/validation.py',repo/'experiments/experiment05.py',repo/'experiments/runner.py',repo/'experiments/utils.py']+list((repo/'matlab').glob('*.m'))
    hashes={str(p.relative_to(repo)):sha256_file(p) for p in protected}
    for folder in ('artifacts','raw/validation','processed','tables','reports'):
        (root/folder).mkdir(parents=True)
    for path in [Path(__file__),args.config,*protected]:
        relative=path.relative_to(repo) if path.is_relative_to(repo) else Path(path.name)
        dest=root/'artifacts'/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        if path.name!='benchmark': shutil.copy2(path,dest)
    prior_path=repo/'experiments/results/experiment05/processed/validation_results.json'
    prior={r['N']:r for r in json.loads(prior_path.read_text()) if r['algorithm']=='trapezoid' and r['seed']==seed and r['samples']==2**25} if prior_path.exists() else {}
    session=dict(experiment_id='experiment06',status='running',started_at=shared.now(),configuration=config,config_file=str(args.config.resolve()),
        source_sha256=hashes,platform=platform.platform(),numpy_version=np.__version__,scipy_version=scipy.__version__,
        executions=[],errors=[],performance_executions=0,classical_executions=0,raw_samples_saved=False)
    shared.save(root/'execution_order.json',session)
    results=[]
    try:
        with tempfile.TemporaryDirectory(prefix='experiment06-',dir='/private/tmp') as temporary:
            executable=Path(temporary)/'benchmark'
            names=('benchmark.c','ziggurat_basic.c','ziggurat_trapezoid.c','ziggurat_basic_profiled.c',
                'ziggurat_trapezoid_profiled.c','xoshiro256plus.c','prng.c',
                'ziggurat_basic_xoshiro256plus.c','ziggurat_trapezoid_xoshiro256plus.c')
            flags=['-std=c11','-Wall','-Wextra','-pedantic','-O2']
            build=['/usr/bin/clang',*flags,'-DBENCHMARK_OPTIMIZATION="O2"',
                *[str(repo/'c'/name) for name in names],'-o',str(executable),'-lm']
            compiled=subprocess.run(build,capture_output=True,text=True,check=True)
            if compiled.stderr: raise RuntimeError(compiled.stderr)
            session.update(compiler=subprocess.check_output(['/usr/bin/clang','--version'],text=True),
                compiler_flags=flags,build_command=build,executable_sha256=sha256_file(executable))
            shared.save(root/'execution_order.json',session)
            for n in config['layers']:
                if psutil.virtual_memory().available<required_memory: raise RuntimeError('Available RAM fell below validation estimate')
                run=dict(algorithm='trapezoid',N=n,H=2,T=4,prng='xoshiro256plus',seed=seed,samples=2**25)
                print(f'Validating trapezoid N={n}, H=2/T=4, seed={seed}, 2^25 samples, 512 interior bins',flush=True)
                values,c_summary,stream_hash=shared.collect(executable,run)
                try: numerical=validation.run_tests_chunked(values,settings,[])
                finally: del values
                if set(numerical['tests'])!=set(shared.TESTS): raise ValueError('Missing validation test')
                for field in ('mean','variance'):
                    if not math.isclose(numerical[field],c_summary[field],rel_tol=1e-10,abs_tol=1e-10):
                        raise ValueError('Python and C moments differ')
                chi=numerical['tests']['chi_square']
                if chi['configured_interior_bins']!=512 or chi['initial_bins']!=514 or chi['degrees_of_freedom']!=chi['final_bins']-1:
                    raise ValueError('Chi-square bins/degrees of freedom mismatch')
                same_stream=prior.get(n,{}).get('stream_sha256')==stream_hash if n in prior else None
                if same_stream:
                    for test in shared.TESTS:
                        if test!='chi_square' and numerical['tests'][test]!=prior[n]['tests'][test]:
                            raise ValueError('Unchanged test differs for identical sample stream')
                record=dict(experiment_id='experiment06',**run,stream_bytes=8*2**25,stream_sha256=stream_hash,
                    matches_experiment05_stream=same_stream,raw_samples_saved=False,**numerical)
                results.append(record)
                shared.save(root/'raw/validation'/f'trapezoid_N{n}_validation.json',record)
                shared.save(root/'processed/validation_results.json',results)
                session['executions'].append(dict(kind='validation',**run,tests=4,execution_order=len(results)))
                shared.save(root/'execution_order.json',session)
                print(f"  bins={chi['final_bins']}, df={chi['degrees_of_freedom']}; "+', '.join(
                    f"{shared.TESTS[t]}={'REJECT' if v['reject'] else 'PASS'}" for t,v in numerical['tests'].items()),flush=True)
        rows=[]
        for record in results:
            chi=record['tests']['chi_square']
            row={key:record[key] for key in ('algorithm','prng','N','H','T','seed','samples','mean','variance')}
            row.update(interior_bins=512,initial_bins=514,final_bins=chi['final_bins'],degrees_of_freedom=chi['degrees_of_freedom'])
            for test,label in shared.TESTS.items():
                value=record['tests'][test]
                row.update({label+'_statistic':value['statistic'],label+'_p_value':value['p_value'] if value['p_value'] is not None else 'NA',
                            label+'_decision':'REJECT' if value['reject'] else 'PASS'})
            rows.append(row)
        shared.save_csv(root/'processed/validation_results.csv',rows)
        shutil.copy2(root/'processed/validation_results.csv',root/'tables/validation_results.csv')
        lines=['# Experiment 06 — Trapezoid validation with 512 interior bins','',
            f'Ziggurat-Trapezoid only; xoshiro256+; N=8,16,32,64,128,256; H=2/T=4; seed {seed}; '
            '2^25 = 33,554,432 samples per dataset. Six validation runs and 24 statistical tests. '
            'No Classical Ziggurat or performance tests were executed.','',
            'The Chi-square test uses 512 equal-width interior bins over [-5,5] (width 0.01953125), '
            'plus two unbounded tail bins: 514 initial bins. The existing expected-count merging rule '
            'merges sparse bins until the minimum expected count is 5; the table gives the resulting '
            'bin counts and degrees of freedom. Tests use fixed N(0,1), without parameter fitting, '
            'at alpha=0.05. Degrees of freedom equal final bins minus one.','',
            '| N | Final bins | df | Chi-square statistic | Chi-square p | Chi-square | KS | CvM | AD |',
            '|---:|---:|---:|---:|---:|---|---|---|---|']
        for r in rows:
            lines.append(f"| {r['N']} | {r['final_bins']} | {r['degrees_of_freedom']} | {r['chi2_statistic']:.8g} | {r['chi2_p_value']:.8g} | "+
                ' | '.join(r[t+'_decision'] for t in ('chi2','ks','cvm','ad'))+' |')
        failures=[dict(N=r['N'],test=t,statistic=v['statistic'],p_value=v['p_value']) for r in results for t,v in r['tests'].items() if v['reject']]
        lines+=['',f'Rejections: {len(failures)} of 24 tests. PASS means failure to reject, not proof of Gaussianity. '
            'One seed is used; no multiple-testing adjustment is applied. AD retains its existing approximate '
            'calibration and critical-value decision.','',
            f"Streams matching Experiment 05: {[r['N'] for r in results if r['matches_experiment05_stream'] ]}. "
            'Where same-seed reference streams exist and match, KS, CvM and AD results are checked for exact agreement. No cross-seed equality is expected.',
            '', 'Raw samples were streamed through an OS pipe into RAM and discarded after validation. '
            'No sample files or subsets were saved. Existing experiment outputs and sampling/validation source '
            'were checked for changes. All statistics and p-values are retained in processed/validation_results.json '
            'and tables/validation_results.csv.','',
            f'Reproduce with `python3 -B experiments/experiment06.py --config {args.config.resolve()} --output-root NEW_DIRECTORY`. '
            f'Configuration: `{args.config.name}`. Existing output directories are never overwritten.']
        (root/'reports/experiment_report.md').write_text('\n'.join(lines)+'\n')
        if shared.inventory(repo/'experiments/results',root)!=previous: raise ValueError('Earlier experiment results changed')
        if {str(p.relative_to(repo)):sha256_file(p) for p in protected}!=hashes: raise ValueError('Protected sources changed')
        if len(results)!=6 or list(root.rglob('*.bin')): raise ValueError('Execution count or sample retention mismatch')
        session.update(status='successful',ended_at=shared.now(),validation_executions=6,statistical_tests_completed=24,
            validation_rejections=failures,previous_results_and_sources_unchanged=True)
        shared.save(root/'execution_order.json',session)
        shared.save(root/'verification.json',dict(status='successful',raw_sample_files=0,classical_executions=0,
            performance_executions=0,validation_executions=6,statistical_tests_completed=24,
            previous_results_and_sources_unchanged=True,
            output_sha256={str(p.relative_to(root)):sha256_file(p) for p in root.rglob('*') if p.is_file()}))
        print(json.dumps(dict(status='successful',output=str(root),rejections=failures),indent=2),flush=True)
    except (Exception,KeyboardInterrupt) as exc:
        session.update(status='failed',ended_at=shared.now());session['errors'].append(f'{type(exc).__name__}: {exc}')
        shared.save(root/'execution_order.json',session);raise


if __name__=='__main__': main()
