"""Read saved results only. Never import experiment drivers or execute samplers."""
import argparse, csv, hashlib, json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DEFAULT_REPO = Path('/Users/liubenli/Documents/FALL 2026/Special Problem/Codes/Ziggurat-Trapezoid-GRNG')
TESTS = {'chi_square':'Chi-square','kolmogorov_smirnov':'KS','cramer_von_mises':'CvM','anderson_darling':'AD'}
SOURCES = {}

def read(p, repo):
    raw=p.read_bytes(); rel=str(p.relative_to(repo))
    SOURCES[rel]={'source_file':rel,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    return json.loads(raw)

def save(name, rows, out=HERE):
    p=out/'tables'/name; p.parent.mkdir(parents=True,exist_ok=True)
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
        w.writerows({k:('N/A' if v is None else json.dumps(v,sort_keys=True) if isinstance(v,(dict,list)) else v) for k,v in r.items()} for r in rows)

def base(r,exp,prng,samples=None):
    classical=r.get('algorithm','trapezoid')=='basic'
    return dict(experiment=exp,algorithm='Classical' if classical else 'Trapezoidal',N=int(r['N']),
        H=None if classical else r.get('H'),T=None if classical else r.get('T'),
        PRNG='PCG32' if prng=='pcg32' else 'xoshiro256+',samples=samples or r.get('num_samples',r.get('samples')),seed=r.get('seed',1))

def consolidate(repo=DEFAULT_REPO,out=HERE):
    roots=repo/'experiments/results'; validations=[]; timings=[]; provenance=[]
    names=['experiment_01','experiment_02','experiment03','experiment04','experiment05','experiment06','experiment06_seed2','experiment06_seed2026','experiment06_seed2_H4T6']
    for exp in names+['prng_comparison']:
        root=roots/exp
        candidates=[root/'execution_order.json']+list((root/'artifacts').glob('*.json'))+[root/'metadata.json']
        for p in candidates:
            if p.exists(): provenance.append(dict(experiment=exp,source_file=str(p.relative_to(repo)),metadata=read(p,repo)))
    for exp in names:
        root=roots/exp; prng='xoshiro256plus' if exp.startswith(('experiment05','experiment06')) else 'pcg32'
        if exp=='experiment_01': paths=sorted((root/'raw/validation').glob('*/validation_result.json'))
        elif exp in ['experiment03','experiment04']: paths=[root/'processed/trapezoid_validation_vs_layers.json']
        else: paths=[root/'processed/validation_results.json']
        for p in paths:
            obj=read(p,repo); records=obj if isinstance(obj,list) else [obj]
            for index,r in enumerate(records):
                b=base(r,exp,prng); stream=r.get('stream_sha256',r.get('sample_sha256'))
                chi=r['tests']['chi_square']
                for test,t in r['tests'].items():
                    outcome='Rejected' if t.get('reject') is True else 'Not rejected' if t.get('reject') is False else 'Inconclusive'
                    validations.append(dict(b,test=TESTS[test],statistic=t.get('statistic'),p_value=t.get('p_value'),
                        outcome=outcome,alpha=t.get('significance_level'),critical_value=t.get('critical_value'),
                        mean=r.get('mean'),variance=r.get('variance'),absolute_mean_error=abs(r['mean']),absolute_variance_error=abs(r['variance']-1),
                        interior_bins=chi.get('configured_interior_bins'),final_bins=chi.get('final_bins'),df=chi.get('degrees_of_freedom'),
                        stream_sha256=stream,source_file=str(p.relative_to(repo)),source_index=index,
                        benchmark_sha256=r.get('benchmark_sha256',r.get('executable_sha256')),validation_code_sha256=r.get('validation_code_sha256'),
                        method=t.get('method'),original_record=r))
    p=roots/'experiment_01/processed/performance_runs.csv'; raw=p.read_bytes();SOURCES[str(p.relative_to(repo))]={'source_file':str(p.relative_to(repo)),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    for r in csv.DictReader(raw.decode().splitlines()):
        r.update(N=int(r['N']),H=int(r['H']) if r['H'] else None,T=int(r['T']) if r['T'] else None,seed=int(r['seed']),samples=int(r['samples']))
        timings.append(dict(base(r,'experiment_01','pcg32'),repetition=int(r['repetition']),elapsed_seconds=float(r['c_sampling_time_seconds']),
            saved_throughput=float(r['throughput_samples_per_second'])/1e6,warmup_samples=0,harness='standard',source_file=str(p.relative_to(repo)),original_record=r))
    for exp in ['experiment03','experiment04','experiment05']:
        for p in sorted((roots/exp/'raw/performance').rglob('performance_runs.json')):
            for i,r in enumerate(read(p,repo)):
                timings.append(dict(base(r,exp,r.get('prng','pcg32')),repetition=r['repetition'],elapsed_seconds=r['sampling_time_seconds'],
                    saved_throughput=r['throughput_samples_per_second']/1e6,warmup_samples=r['warmup_samples'],
                    generated_samples=r.get('generated_samples',r['num_samples']),harness='checkpoint' if exp=='experiment05' else 'standard',
                    source_file=str(p.relative_to(repo)),source_index=i,original_record=r))
    p=roots/'prng_comparison/runs.json'
    for i,r in enumerate(read(p,repo)):
        t=r['benchmark_results'];timings.append(dict(base(t,'prng_comparison',r['prng']),repetition=r['repetition'],elapsed_seconds=t['sampling_time_seconds'],
            saved_throughput=t['throughput_samples_per_second']/1e6,warmup_samples=0,harness='standard',source_file=str(p.relative_to(repo)),source_index=i,original_record=r))
    for r in timings:
        r['throughput_Msamples_s']=r['samples']/r['elapsed_seconds']/1e6
        assert abs(r['throughput_Msamples_s']-r['saved_throughput'])<1e-6
    for source,target in [('experiment_01/processed/tail_results.csv','tail_results.csv'),('experiment_01/processed/prng_results.csv','prng_profile.csv')]:
        p=roots/source;raw=p.read_bytes();rel=str(p.relative_to(repo));SOURCES[rel]={'source_file':rel,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
        save(target,[dict(r,source_file=rel) for r in csv.DictReader(raw.decode().splitlines())],out)
    # Trace all source/configuration files used to interpret the data, without running them.
    for folder,patterns in [('c',['*.c','*.h','Makefile','README.md']),('experiments',['*.py','*.yaml','*.md'])]:
        for pattern in patterns:
            for p in (repo/folder).glob(pattern):
                raw=p.read_bytes();rel=str(p.relative_to(repo));SOURCES[rel]={'source_file':rel,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    # Exact originals and environment records retained alongside normalized CSV columns.
    (out/'analysis').mkdir(parents=True,exist_ok=True)
    (out/'analysis/provenance.json').write_text(json.dumps(provenance,indent=2))
    save('validation_summary.csv',validations,out);save('performance_runs.csv',timings,out);save('source_manifest.csv',list(SOURCES.values()),out)
    cfg={}
    for r in validations+timings:
        key=tuple(r.get(k) for k in ['experiment','algorithm','N','H','T','PRNG','samples','seed'])
        cfg[key]={k:r.get(k) for k in ['experiment','algorithm','N','H','T','PRNG','samples','seed']}
        cfg[key].update(data_available='Saved numerical results; original fields retained',source_file=r['source_file'])
    save('configuration_summary.csv',list(cfg.values()),out)
    return validations,timings

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,default=DEFAULT_REPO);a=p.parse_args()
    v,t=consolidate(a.repo); print(f'{len(v)} saved test records; {len(t)} timing/checkpoint records')
