"""Regenerate derived outputs exclusively from existing results."""
import argparse,json
from pathlib import Path
from consolidate_results import consolidate,HERE,DEFAULT_REPO
from analyze_performance import analyze as performance
from analyze_accuracy import analyze as accuracy

def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,default=DEFAULT_REPO);a=p.parse_args()
    v,t=consolidate(a.repo,HERE);perf,over=performance(t,HERE);seeds,trade=accuracy(v,perf,HERE)
    # Raw originals remain in CSV/provenance; compact cache is for report and figure generation.
    v=[{k:x for k,x in r.items() if k!='original_record'} for r in v]
    data=dict(repo=str(a.repo),validation=v,performance=perf,overhead=over,seeds=seeds,tradeoff=trade)
    (HERE/'analysis/derived_results.json').write_text(json.dumps(data,indent=2))
    print('Saved',len(v),'test records;',len(t),'timing/checkpoint records;',len(perf),'performance aggregates')

if __name__=='__main__':main()
