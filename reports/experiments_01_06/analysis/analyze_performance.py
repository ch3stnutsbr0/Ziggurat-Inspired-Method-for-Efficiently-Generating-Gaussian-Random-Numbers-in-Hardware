"""Descriptive statistics only; no benchmarks executed."""
from collections import defaultdict
import statistics
from consolidate_results import save

def analyze(timings,out):
    groups=defaultdict(list)
    keys=['experiment','algorithm','N','H','T','PRNG','samples','seed','warmup_samples','harness']
    for r in timings:groups[tuple(r.get(k) for k in keys)].append(r)
    rows=[]
    for key,runs in groups.items():
        values=[r['throughput_Msamples_s'] for r in runs]; avg=statistics.mean(values)
        rows.append(dict(zip(keys,key),repetitions=len(values),mean_Msamples_s=avg,median_Msamples_s=statistics.median(values),
            std_Msamples_s=statistics.stdev(values) if len(values)>1 else None,CV_percent=100*statistics.stdev(values)/avg if len(values)>1 else None,
            min_Msamples_s=min(values),max_Msamples_s=max(values),source_file=runs[0]['source_file']))
    for r in rows:
        match=[b for b in rows if b['algorithm']=='Classical' and all(b[k]==r[k] for k in ['experiment','N','PRNG','samples','seed','warmup_samples','harness'])]
        r['relative_speedup']=r['median_Msamples_s']/match[0]['median_Msamples_s'] if len(match)==1 else None
        r['improvement_percent']=100*(r['relative_speedup']-1) if r['relative_speedup'] is not None else None
    save('throughput_summary.csv',rows,out)
    overhead=[]
    for r in rows:
        if r['experiment']!='experiment_01' or r['algorithm']!='Trapezoidal':continue
        b=next(x for x in rows if x['experiment']=='experiment_01' and x['algorithm']=='Trapezoidal' and x['N']==r['N'] and x['H']==x['T']==0)
        overhead.append(dict(r,refinement_overhead_percent=100*(1-r['median_Msamples_s']/b['median_Msamples_s'])))
    save('refinement_overhead.csv',overhead,out)
    return rows,overhead
