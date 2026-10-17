"""Read-only provenance and derived-output checks; no sampling or GOF testing."""
import argparse,csv,hashlib,json,math
from pathlib import Path
from pypdf import PdfReader
from consolidate_results import HERE,DEFAULT_REPO

def main(repo=DEFAULT_REPO,baseline=None):
    d=json.loads((HERE/'analysis/derived_results.json').read_text());checks={}
    source=list(csv.DictReader((HERE/'tables/source_manifest.csv').open()))
    changed=[r['source_file'] for r in source if hashlib.sha256((repo/r['source_file']).read_bytes()).hexdigest()!=r['sha256']]
    assert not changed,changed;checks['input_manifest_files_verified']=len(source)
    if baseline:
        original=json.loads(baseline.read_text());bad=[]
        for rel,r in original.items():
            p=repo/rel
            if not p.is_file() or p.stat().st_mtime_ns!=r['mtime_ns'] or hashlib.sha256(p.read_bytes()).hexdigest()!=r['sha256']:bad.append(rel)
        assert not bad,bad;checks['original_files_verified_hash_and_mtime']=len(original)
        checks['original_files_modified']=0
    assert len(d['validation'])==548
    assert len(d['performance'])==166
    checks['saved_validation_datasets']=len(d['validation'])//4;checks['saved_test_records']=len(d['validation'])
    runs=list(csv.DictReader((HERE/'tables/performance_runs.csv').open()));assert len(runs)==1220
    checks['timing_checkpoint_records']=len(runs)
    for r in runs:
        assert math.isclose(float(r['throughput_Msamples_s']),int(r['samples'])/float(r['elapsed_seconds'])/1e6,rel_tol=1e-14)
    for e in ['experiment03','experiment04']:
        with (repo/f'experiments/results/{e}/processed/performance_vs_layers.csv').open() as fh:
            for r in csv.DictReader(fh):
                m=int(r.get('samples',10000000))
                for a,col in [('Classical','classical_throughput_M_per_s'),('Trapezoidal','trapezoid_throughput_M_per_s')]:
                    p=next(x for x in d['performance'] if x['experiment']==e and x['N']==int(r['N']) and x['algorithm']==a and x['samples']==m)
                    assert math.isclose(p['median_Msamples_s'],float(r[col]),rel_tol=1e-12)
    for r in csv.DictReader((repo/'experiments/results/experiment05/processed/performance_vs_samples.csv').open()):
        p=next(x for x in d['performance'] if x['experiment']=='experiment05' and x['N']==int(r['N']) and x['algorithm']==('Classical' if r['algorithm']=='basic' else 'Trapezoidal') and x['samples']==int(r['measured_samples']))
        assert math.isclose(p['median_Msamples_s'],float(r['median_Msamples_s']),rel_tol=1e-12)
    checks['recomputed_medians_match_original_03_04_05']=True
    assert all(r['alpha']==.05 for r in d['validation'])
    assert all(r['df']==r['final_bins']-1 for r in d['validation'])
    checks['test_alpha_and_degrees_of_freedom_consistent']=True
    report=(HERE/'report.md').read_text()
    figures=sorted((HERE/'figures').glob('*.pdf'));assert len(figures)==8
    for p in figures:
        assert len(PdfReader(p).pages)==1
        assert ('figures/'+p.stem+'.png') in report
    checks['referenced_vector_figures']=8
    pdf=PdfReader(HERE/'report.pdf');checks['report_pdf_pages']=len(pdf.pages)
    assert all(len(p.extract_text())>100 for p in pdf.pages)
    checks['experiments_rerun']=False;checks['new_gaussian_samples_generated']=False
    checks['additional_statistical_tests_executed']=False;checks['status']='passed'
    (HERE/'analysis/integrity_check.json').write_text(json.dumps(checks,indent=2))
    print(json.dumps(checks,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,default=DEFAULT_REPO);p.add_argument('--baseline',type=Path);a=p.parse_args();main(a.repo,a.baseline)
