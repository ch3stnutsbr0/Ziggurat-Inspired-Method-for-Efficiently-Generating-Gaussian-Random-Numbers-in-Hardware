"""Publication-ready figures generated from Experiment 01 processed CSV files."""
import csv
import math
import os
from pathlib import Path
import tempfile

os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir())/'experiment01-matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def _rows(path):
    with Path(path).open(newline='',encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def _number(value):
    if value in (None,'','None'):
        return None
    return float(value)


def _save(fig, path):
    path.parent.mkdir(parents=True,exist_ok=True)
    fig.tight_layout()
    fig.savefig(path.with_suffix('.pdf'),bbox_inches='tight')
    fig.savefig(path.with_suffix('.png'),dpi=300,bbox_inches='tight')
    plt.close(fig)


def plot_experiment01(root, analyzed=None):
    root=Path(root)
    processed=root/'processed'
    figures=root/'figures'
    figures.mkdir(parents=True,exist_ok=True)
    summary=_rows(processed/'experiment_summary.csv')
    tails=_rows(processed/'tail_results.csv')
    primary=_rows(root/'tables/primary_comparison.csv')
    plt.rcParams.update({'font.size':10,'axes.grid':False,'figure.dpi':130,
                         'savefig.facecolor':'white','axes.spines.top':False,
                         'axes.spines.right':False})
    layers=sorted({int(row['N']) for row in summary})
    colors={'basic':'#1f77b4','trapezoid':'#ff7f0e','trapezoid_refined':'#2ca02c'}

    # Figure 1: median speed and IQR for the primary comparison.
    fig,ax=plt.subplots(figsize=(7.2,4.6))
    for label,title in [('basic','Basic'),('trapezoid','Unrefined'),('trapezoid_refined','Best refined passing')]:
        selected=[]
        for n in layers:
            candidates=[r for r in summary if int(r['N'])==n and r['algorithm_label']==label]
            if label=='trapezoid_refined':
                candidates=[r for r in candidates if r['all_tests_pass']=='True']
                candidates=sorted(candidates,key=lambda r:float(r['median_throughput']),reverse=True)[:1]
            selected.extend(candidates[:1])
        if not selected:
            continue
        x=np.array([int(r['N']) for r in selected])
        y=np.array([float(r['median_throughput'])/1e6 for r in selected])
        lo=np.array([(float(r['median_throughput'])-float(r['q1_throughput']))/1e6 for r in selected])
        hi=np.array([(float(r['q3_throughput'])-float(r['median_throughput']))/1e6 for r in selected])
        ax.errorbar(x,y,yerr=[lo,hi],marker='o',capsize=4,label=title,color=colors[label])
    ax.set(xlabel='Number of layers N',ylabel='Median throughput (million samples/s)',
           title='Gaussian sampling throughput; error bars show IQR')
    ax.set_xticks(layers)
    ax.legend()
    if not any(r['algorithm_label']=='trapezoid_refined' and r['all_tests_pass']=='True' for r in summary):
        ax.text(.02,.02,'No refined configuration passed all four tests',
                transform=ax.transAxes,fontsize=9,va='bottom')
    _save(fig,figures/'figure_1_throughput_layers')

    # Figures 2-5: one heatmap per N, including H=T=0 unrefined cell.
    heat_fields=[('figure_2_throughput','median_throughput','Median throughput (million samples/s)',1e-6),
                 ('figure_3_ks','kolmogorov_smirnov_statistic','KS D statistic',1),
                 ('figure_4_ad','anderson_darling_statistic','AD statistic',1),
                 ('figure_5_prng_fraction','estimated_prng_fraction','Estimated PRNG fraction',1)]
    for n in layers:
        rows=[r for r in summary if int(r['N'])==n and r['algorithm']=='trapezoid']
        heads=sorted({int(r['H']) for r in rows if r['H']})
        tails_levels=sorted({int(r['T']) for r in rows if r['T']})
        for prefix,field,label,scale in heat_fields:
            matrix=np.full((len(heads),len(tails_levels)),np.nan)
            for r in rows:
                matrix[heads.index(int(r['H'])),tails_levels.index(int(r['T']))]=float(r[field])*scale
            fig,ax=plt.subplots(figsize=(6.3,5.2))
            im=ax.imshow(matrix,origin='lower',aspect='equal',cmap='viridis')
            ax.set_xticks(range(len(tails_levels)),tails_levels)
            ax.set_yticks(range(len(heads)),heads)
            ax.set(xlabel='Tail refinement T',ylabel='Head refinement H',title=f'{label}; N={n}')
            fig.colorbar(im,ax=ax,label=label)
            for i in range(len(heads)):
                for j in range(len(tails_levels)):
                    if math.isfinite(matrix[i,j]):
                        ax.text(j,i,f'{matrix[i,j]:.3g}',ha='center',va='center',
                                color='white' if matrix[i,j]<np.nanmean(matrix) else 'black',fontsize=8)
            _save(fig,figures/f'{prefix}_N{n}')

    # Figure 6: maximize speed while minimizing KS D.
    fig,ax=plt.subplots(figsize=(7.2,5.2))
    points=[(float(r['median_throughput'])/1e6,float(r['kolmogorov_smirnov_statistic'])) for r in summary]
    pareto=[]
    for i,(speed,ks) in enumerate(points):
        pareto.append(not any((other_speed>=speed and other_ks<=ks and
                               (other_speed>speed or other_ks<ks))
                              for j,(other_speed,other_ks) in enumerate(points) if j!=i))
    palette=plt.get_cmap('viridis',len(layers))
    for k,n in enumerate(layers):
        for passed,marker in [(True,'o'),(False,'x')]:
            indices=[i for i,r in enumerate(summary) if int(r['N'])==n and
                     (r['all_tests_pass']=='True')==passed]
            ax.scatter([points[i][0] for i in indices],[points[i][1] for i in indices],
                       color=palette(k),marker=marker,s=45,label=f'N={n}, {"pass" if passed else "fail"}')
    frontier=sorted([points[i] for i,value in enumerate(pareto) if value])
    if frontier:
        ax.plot([x for x,_ in frontier],[y for _,y in frontier],color='black',
                linewidth=1,linestyle='--',label='Pareto frontier')
    ax.set(xlabel='Median throughput (million samples/s)',ylabel='KS D statistic',
           title='Accuracy versus throughput; four-test decisions')
    ax.legend(fontsize=8,ncol=2)
    _save(fig,figures/'figure_6_accuracy_throughput_pareto')

    # Figure 7: absolute full-sample two-sided tail probability error.
    fig,ax=plt.subplots(figsize=(7.2,5.0))
    for n in layers:
        candidates=[r for r in summary if int(r['N'])==n]
        best=sorted([r for r in candidates if r['algorithm_label']=='trapezoid_refined' and
                     r['all_tests_pass']=='True'],key=lambda r:float(r['median_throughput']),reverse=True)
        chosen=[next((r for r in candidates if r['algorithm_label']==label),None)
                for label in ('basic','trapezoid')]
        chosen.append(best[0] if best else None)
        for r in chosen:
            if r is None:
                continue
            measured=sorted([t for t in tails if t['algorithm']==r['algorithm'] and
                             int(t['N'])==n and t['H']==r['H'] and t['T']==r['T']],
                            key=lambda t:float(t['threshold']))
            if not measured:
                continue
            x=np.array([float(t['threshold']) for t in measured])
            y=np.array([float(t['absolute_error']) for t in measured])
            theory=np.array([float(t['theoretical_probability']) for t in measured])
            ax.plot(x,y,marker='o',linewidth=1,
                        label=f"N={n} {r['algorithm_label']}" +
                        (f" H={r['H']} T={r['T']}" if r['algorithm_label']=='trapezoid_refined' else ''))
    reference=sorted({(float(t['threshold']),float(t['binomial_standard_error'])) for t in tails})
    if reference:
        by_threshold={}
        for threshold,se in reference:by_threshold[threshold]=se
        ax.plot(sorted(by_threshold),[by_threshold[x] for x in sorted(by_threshold)],
                color='gray',linestyle=':',linewidth=1.5,label='1 binomial SE under N(0,1)')
    if not any(r['algorithm_label']=='trapezoid_refined' and r['all_tests_pass']=='True' for r in summary):
        ax.text(.02,.02,'No refined configuration passed all four tests',
                transform=ax.transAxes,fontsize=9,va='bottom')
    ax.set_yscale('log')
    ax.set(xlabel='Absolute-value threshold |x|',ylabel='Absolute tail probability error',
           title='Two-sided Gaussian tail error and sampling noise reference')
    ax.legend(fontsize=7,ncol=2)
    _save(fig,figures/'figure_7_gaussian_tail_error')
    return sorted(str(path) for path in figures.glob('*.pdf'))
