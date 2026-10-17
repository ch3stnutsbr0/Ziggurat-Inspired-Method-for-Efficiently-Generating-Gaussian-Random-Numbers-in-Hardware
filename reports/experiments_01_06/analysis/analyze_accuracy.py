"""Summarize saved test decisions; never run goodness-of-fit tests."""
from collections import defaultdict
from consolidate_results import save

def analyze(validations,performance,out):
    # Identical streams tested again under identical calibration are not new seeds.
    unique={}
    for r in validations:
        key=(r['algorithm'],r['N'],r['H'],r['T'],r['PRNG'],r['samples'],r['seed'],r['test'],r['interior_bins'])
        if key in unique:
            assert abs(unique[key]['statistic']-r['statistic'])<1e-8
        else:unique[key]=r
    groups=defaultdict(list)
    keys=['algorithm','N','H','T','PRNG','samples','test','interior_bins']
    for r in unique.values():groups[tuple(r[k] for k in keys)].append(r)
    rows=[]
    for k,rr in groups.items():
        pp=[r['p_value'] for r in rr if r['p_value'] is not None]
        rows.append(dict(zip(keys,k),validation_runs=len(rr),seeds=[r['seed'] for r in rr],rejections=sum(r['outcome']=='Rejected' for r in rr),
            rejection_frequency=sum(r['outcome']=='Rejected' for r in rr)/len(rr),p_values=pp,p_value_min=min(pp) if pp else None,p_value_max=max(pp) if pp else None))
    save('repeated_seed_summary.csv',rows,out)
    trades=[]
    for p in performance:
        if p['experiment'] in ['experiment06','prng_comparison'] or (p['experiment']=='experiment05' and p['samples']!=33554432):continue
        rr=[r for r in validations if r['experiment']==p['experiment'] and all(r[k]==p[k] for k in ['algorithm','N','H','T','PRNG','samples','seed'])]
        status='Rejected' if any(r['outcome']=='Rejected' for r in rr) else 'Supported validation' if len(rr)==4 and all(r['outcome']=='Not rejected' for r in rr) else 'Not tested'
        ks=next((r for r in rr if r['test']=='KS'),None)
        trades.append(dict(p,validation_evidence=status,KS_D=ks['statistic'] if ks else None,absolute_mean_error=ks['absolute_mean_error'] if ks else None,
            absolute_variance_error=ks['absolute_variance_error'] if ks else None,
            notes='Single saved seed; non-rejection is not exactness' if status=='Supported validation' else 'Review individual tests; empirical discrepancy is not algorithmic bias'))
    save('tradeoff_summary.csv',trades,out)
    return rows,trades
