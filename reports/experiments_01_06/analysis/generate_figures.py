"""Plot existing, consolidated results. No sampling or statistical tests."""
import json,os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/private/tmp/ziggurat-report-mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

ROOT=Path(__file__).resolve().parents[1]
D=json.loads((ROOT/'analysis/derived_results.json').read_text())
P,V=D['performance'],D['validation']; OUT=ROOT/'figures';OUT.mkdir(exist_ok=True)
COL={'Classical':'#255f85','Trapezoidal':'#c36a32'}
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.spines.top':False,'axes.spines.right':False,
    'axes.titlesize':10,'axes.labelsize':9,'legend.fontsize':8,'pdf.fonttype':42,'savefig.dpi':300})
LAYERS=[8,16,32,64,128,256]

def save(fig,name):
    fig.savefig(OUT/(name+'.pdf'),bbox_inches='tight');fig.savefig(OUT/(name+'.png'),bbox_inches='tight');plt.close(fig)
def selected(exp,samples,algorithm=None):
    return sorted([r for r in P if r['experiment']==exp and r['samples']==samples and (algorithm is None or r['algorithm']==algorithm)],key=lambda r:r['N'])
def layers(ax):
    ax.set_xscale('log',base=2);ax.set_xticks(LAYERS,LAYERS);ax.set_xlabel('Layers, N');ax.grid(alpha=.2)
def valid(exp,n,algorithm='Trapezoidal',h=None,t=None):
    return [r for r in V if r['experiment']==exp and r['N']==n and r['algorithm']==algorithm and (h is None or r['H']==h) and (t is None or r['T']==t)]
def stat(exp,n,test='KS',algorithm='Trapezoidal',h=None,t=None):
    return next(r['statistic'] for r in valid(exp,n,algorithm,h,t) if r['test']==test)

def main():
    profiles=[('experiment03',10000000,'E03 / PCG32 / 10 million'),('experiment04',100000000,'E04 / PCG32 / 100 million'),('experiment04',33554432,'E04 / PCG32 / 2^25'),('experiment05',33554432,'E05 / xoshiro256+ / 2^25')]
    fig,axs=plt.subplots(2,2,figsize=(9.1,6.1),layout='constrained')
    for ax,(e,s,title) in zip(axs.flat,profiles):
        for a in COL:
            rr=selected(e,s,a);ax.errorbar([r['N'] for r in rr],[r['median_Msamples_s'] for r in rr],
                yerr=[r['std_Msamples_s'] for r in rr],label=a,color=COL[a],marker='o',capsize=2)
        layers(ax);ax.set_title(title);ax.set_ylabel('Throughput (Msamples/s)')
    axs[0,0].legend();fig.suptitle('Figure 1. Matched throughput; medians with repetition SD\nTrapezoidal H=2, T=4; panels retain distinct benchmark conditions',fontsize=11)
    save(fig,'throughput_vs_layers')
    fig,ax=plt.subplots(figsize=(8.3,3.8),layout='constrained')
    for e,s,title in profiles:
        rr=selected(e,s,'Trapezoidal');ax.plot([r['N'] for r in rr],[r['relative_speedup'] for r in rr],marker='o',label=title)
    ax.axhline(1,color='#444',ls='--');layers(ax);ax.set_ylabel('Trapezoidal / Classical throughput');ax.legend(ncol=2);ax.set_title('Figure 2. Relative performance within each benchmark cohort')
    save(fig,'relative_speedup')
    panels=[('experiment05','E05, seed 1, 100 bins',True),('experiment06','E06, seed 1, 512 bins',False),('experiment06_seed2','E06, seed 2, 512 bins',False),('experiment06_seed2026','E06, seed 2026, 512 bins',False),('experiment06_seed2_H4T6','E06, seed 2, H4/T6',False),('experiment03','E03, seed 1, 100 bins',False)]
    colors=['#c24b45','#83b6ac','#e2e2e2','#e7bd67'];mapping={'Rejected':0,'Not rejected':1,'Not tested':2,'Inconclusive':3}
    fig,axs=plt.subplots(2,3,figsize=(10.3,7),layout='constrained')
    for ax,(e,title,both) in zip(axs.flat,panels):
        configs=[(a,n) for a in (['Classical','Trapezoidal'] if both else ['Trapezoidal']) for n in LAYERS]
        tests=['Chi-square','KS','CvM','AD'];matrix=[];labels=[]
        for a,n in configs:
            rr=valid(e,n,a);matrix.append([mapping[next((r['outcome'] for r in rr if r['test']==t),'Not tested')] for t in tests]);labels.append(('C' if a=='Classical' else 'T')+f' N{n}')
        ax.imshow(matrix,cmap=ListedColormap(colors),vmin=0,vmax=3,aspect='auto');ax.set_xticks(range(4),tests,rotation=30,ha='right');ax.set_yticks(range(len(labels)),labels);ax.set_title(title)
    fig.legend(handles=[Patch(facecolor=c,label=k) for k,c in zip(mapping,colors)],loc='outside lower center',ncol=4)
    fig.suptitle('Figure 3. Saved test outcomes (alpha=0.05)\nH2/T4 except marked H4/T6; PRNG is xoshiro256+ except E03 PCG32',fontsize=11)
    save(fig,'validation_heatmap')
    fig,ax=plt.subplots(figsize=(8.3,4),layout='constrained')
    for a in COL:
        rr=selected('experiment05',33554432,a);xx=[r['median_Msamples_s'] for r in rr];yy=[stat('experiment05',r['N'],algorithm=a) for r in rr]
        ax.plot(xx,yy,'o-',color=COL[a],label=a)
        for x,y,r in zip(xx,yy,rr):ax.annotate(str(r['N']),(x,y),xytext=(4,5),textcoords='offset points',fontsize=8)
    ax.set_xlabel('Throughput (Msamples/s)');ax.set_ylabel('Empirical KS distance, D');ax.grid(alpha=.2);ax.legend();ax.set_title('Figure 4. E05 empirical CDF discrepancy versus throughput\nLabels give N; one seed, 2^25 samples; no population Pareto claim')
    save(fig,'accuracy_vs_throughput')
    fig,axs=plt.subplots(2,2,figsize=(9,6.3),layout='constrained')
    for n,c in zip([8,16,32],['#255f85','#c36a32','#498568']):
        for column,(vary,fixed) in enumerate([('H',4),('T',2)]):
            rr=sorted([r for r in D['overhead'] if r['N']==n and r['T' if vary=='H' else 'H']==fixed],key=lambda r:r[vary])
            depth=[r[vary] for r in rr];axs[0,column].plot(depth,[r['median_Msamples_s'] for r in rr],'o-',color=c,label=f'N={n}')
            axs[1,column].plot(depth,[stat('experiment_01',n,h=r['H'],t=r['T']) for r in rr],'o-',color=c)
            axs[0,column].set_title(('Head depth H (T=4)' if column==0 else 'Tail depth T (H=2)'))
    for ax in axs.flat:ax.set_xticks(range(5));ax.grid(alpha=.2)
    axs[0,0].legend();axs[0,0].set_ylabel('Throughput (Msamples/s)');axs[0,1].set_ylabel('Throughput (Msamples/s)')
    for ax in axs[1,:]:ax.set_ylabel('Empirical KS distance, D');ax.set_yscale('log')
    axs[1,0].set_xlabel('Head refinement H');axs[1,1].set_xlabel('Tail refinement T')
    fig.suptitle('Figure 5. Matched refinement slices from E01\nPCG32; 100 million samples; seed 1; ten timing repetitions',fontsize=11)
    save(fig,'refinement_comparison')
    fig,ax=plt.subplots(figsize=(7.5,3.8),layout='constrained')
    rr=[r for r in P if r['experiment']=='prng_comparison'];x=np.arange(2)
    for j,prng in enumerate(['PCG32','xoshiro256+']):
        q=[next(r for r in rr if r['algorithm']==a and r['PRNG']==prng) for a in COL]
        ax.bar(x+(j-.5)*.34,[r['median_Msamples_s'] for r in q],width=.34,label=prng,yerr=[r['std_Msamples_s'] for r in q],capsize=3,color=['#809db1','#b98b64'][j])
    ax.set_xticks(x,list(COL));ax.set_ylabel('Throughput (Msamples/s)');ax.legend();ax.set_title('Figure 6. Dedicated PRNG comparison: N=128, 10 million samples\nH2/T4; seed 1; five repetitions; 53-bit uniforms; no warmup')
    save(fig,'prng_comparison')
    fig,axs=plt.subplots(1,2,figsize=(9,3.6),layout='constrained')
    for a in COL:
        for ax,test in zip(axs,['KS','variance']):
            yy=[stat('experiment05',n,algorithm=a) if test=='KS' else valid('experiment05',n,a)[0]['absolute_variance_error'] for n in LAYERS]
            ax.plot(LAYERS,yy,'o-',color=COL[a],label=a);layers(ax)
    axs[0].set_ylabel('Empirical KS distance, D');axs[1].set_ylabel('|Sample variance - 1|');axs[0].legend()
    fig.suptitle('Figure 7. E05 empirical discrepancies versus N\nFinite-sample errors do not measure Classical algorithmic approximation',fontsize=11)
    save(fig,'accuracy_vs_layers')
    rr=sorted([r for r in D['tradeoff'] if r['experiment']=='experiment05'],key=lambda r:r['median_Msamples_s'])
    fig,ax=plt.subplots(figsize=(8.6,5),layout='constrained');y=np.arange(len(rr))
    ax.barh(y,[r['median_Msamples_s'] for r in rr],color=['#83b6ac' if r['validation_evidence']=='Supported validation' else '#c24b45' for r in rr])
    ax.set_yticks(y,[r['algorithm']+f" N{r['N']}" for r in rr]);ax.set_xlabel('Throughput (Msamples/s)');ax.grid(axis='x',alpha=.2)
    ax.legend(handles=[Patch(facecolor='#83b6ac',label='No rejection in matched E05 validation'),Patch(facecolor='#c24b45',label='At least one E05 rejection')],loc='lower right')
    ax.set_title('Figure 8. E05 validation-constrained throughput ranking\nSingle seed only; E06 later rejects each Trapezoidal N under at least one seed')
    save(fig,'validated_throughput_ranking')
    print('Generated eight vector PDFs and eight 300-DPI PNGs')

if __name__=='__main__':main()
