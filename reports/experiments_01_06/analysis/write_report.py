"""Compose the research report from saved derived tables and explicit source analysis."""
import csv,json
from collections import defaultdict
from pathlib import Path
from consolidate_results import HERE,save

D=json.loads((HERE/'analysis/derived_results.json').read_text());P=D['performance'];V=D['validation'];S=D['seeds'];O=D['overhead']
LAYERS=[8,16,32,64,128,256]
parts=[]
def text(t):parts.append(t.strip()+'\n')
def table(headers,rows):
    parts.append('| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(str(x).replace('|','/').replace('\n',' ') for x in row)+' |' for row in rows)+'\n')
def fig(name,caption):text(f'![{caption}](figures/{name}.png)\n\n{caption}')
def f(x,d=4):return 'N/A' if x is None else f'{x:.{d}g}'
def perf(e,n,a='Trapezoidal',samples=33554432,prng=None):return next(r for r in P if r['experiment']==e and r['N']==n and r['algorithm']==a and r['samples']==samples and (prng is None or r['PRNG']==prng))
def vv(e,n,a='Trapezoidal',h=None,t=None,samples=None):return [r for r in V if r['experiment']==e and r['N']==n and r['algorithm']==a and (h is None or r['H']==h) and (t is None or r['T']==t) and (samples is None or r['samples']==samples)]
def test(rr,k):return next(r for r in rr if r['test']==k)
def config(r):return f"{r['algorithm']} N{r['N']}"+('' if r['H'] is None else f" H{r['H']}/T{r['T']}")
def median(e,n,a='Trapezoidal',samples=33554432):return perf(e,n,a,samples)['median_Msamples_s']

inventory=[
dict(experiment='01',name='Refinement grid and PRNG profiling',objective='Map speed, validation and refinement cost',algorithms='Classical; Trapezoidal',configurations='N=8,16,32; Trapezoidal H,T=0..4; 78 unique configurations',samples='100,000,000 per run',seeds='1',repetitions='10 timing repetitions; one validation per configuration',PRNG='PCG32',metrics='Throughput; four GOF tests; moments; tails; uniform-call profiling',results_available='Complete: 780 timings, 78 validations, 78 profiling runs'),
dict(experiment='02',name='Selected seed replication',objective='Check whether selected E01 rejections persist',algorithms='Classical; Trapezoidal',configurations='Classical N8; Trapezoidal N8 H0/T0 and N8,16,32 H2/T4',samples='100,000,000',seeds='2; comparison with E01 seed 1',repetitions='One validation per configuration; no benchmark',PRNG='PCG32',metrics='Four GOF tests; moments',results_available='Complete: 5 validations'),
dict(experiment='03',name='Layer-count comparison',objective='Locate speed crossover and layer dependence',algorithms='Classical; Trapezoidal',configurations='N=8,16,32,64,128,256; H2/T4',samples='10,000,000',seeds='1',repetitions='5 timing repetitions; Trapezoidal validation only',PRNG='PCG32',metrics='Throughput; four GOF tests; moments',results_available='Complete: 60 timings, 6 validations'),
dict(experiment='04',name='Sample-count comparison',objective='Assess timing stability and validation power at longer runs',algorithms='Classical; Trapezoidal',configurations='N=8..256 powers of two; H2/T4',samples='100,000,000 and 33,554,432; separate cohorts',seeds='1',repetitions='5 timing repetitions in each cohort',PRNG='PCG32',metrics='Throughput; Trapezoidal GOF and moments',results_available='Complete: 120 timings, 12 validations'),
dict(experiment='05',name='xoshiro256+ checkpoint study',objective='Compare algorithms over cumulative timing prefixes',algorithms='Classical; Trapezoidal',configurations='N=8..256 powers of two; H2/T4; checkpoints 100k,1m,10m,2^25',samples='33,554,432 generated per run',seeds='1',repetitions='5 complete timing runs per configuration; four dependent checkpoints',PRNG='xoshiro256+',metrics='Cumulative throughput; full-data four GOF tests; moments',results_available='Complete: 60 timing runs / 240 checkpoint records; 12 validations'),
dict(experiment='06',name='Fine-bin and repeated-seed validation',objective='Assess binning sensitivity, seeds, deeper refinement',algorithms='Trapezoidal only',configurations='N=8..256; H2/T4 seeds 1,2,2026; H4/T6 seed 2',samples='33,554,432',seeds='1, 2, 2026; H4/T6 only seed 2',repetitions='One validation per configuration and seed; no benchmark',PRNG='xoshiro256+',metrics='Four GOF tests; 512 interior chi-square bins; moments',results_available='Complete: 24 validations in four result directories')]
save('experiment_inventory.csv',inventory)

text('''# Accuracy–Performance Trade-offs in Classical and Trapezoidal Ziggurat Gaussian Random Number Generators: An Experimental Study

Technical research report | Experiments 01–06 | Evidence reviewed 15 October 2026

## Abstract

This study evaluates whether a trapezoidal Gaussian sampler can exchange a controlled amount of distributional accuracy for useful computational speed relative to Classical Ziggurat. Existing C implementations, Python experiment drivers, archived configurations and saved numerical results were inspected without rerunning experiments or generating samples. Classical Ziggurat is treated as theoretically exact under ideal uniform inputs, exact arithmetic, correct tables and correct acceptance/rejection and tail rules. The implemented Trapezoidal sampler instead draws from first-order fitted geometry without an exact Gaussian correction. The evidence comprises 137 saved validation datasets, 548 test records and 1,220 timing/checkpoint records, with duplicate streams and dependent checkpoints retained but explicitly distinguished from independent evidence.

At small layer counts, Trapezoidal has higher matched median throughput, but persistent chi-square rejections undermine an accuracy-unconstrained recommendation. Refinement substantially reduces empirical discrepancies and tail deficits at a measurable speed cost; increasing refinement beyond H=2,T=4 does not reliably eliminate remaining rejections. In Experiment 05, Trapezoidal speedups decline from 1.465 at N=8 to 0.856 at N=256. Classical N=256 with xoshiro256+ reaches 211.280 Msamples/s and has no rejection in its matched single-seed validation. Trapezoidal N=256 reaches 180.896 Msamples/s and has no Experiment 05 rejection, but later seeds reject either its chi-square or KS test. No application tolerance for population distributional error is supplied, and no Trapezoidal configuration has a demonstrated combination of superior best-configured CPU throughput and robust validation support. Its rejection-free runtime remains a plausible hardware research direction, requiring fixed-point error analysis and direct FPGA measurements.

## 1. Introduction

### 1.1 Motivation

Gaussian random numbers support Monte Carlo simulation, communication-system noise models and stochastic engineering analysis. Generation speed matters when sampling consumes a substantial share of application runtime. Distributional approximation may be acceptable in some applications, but the permissible error must be established from application requirements. A faster generator that distorts rare events can be unsuitable even if its first two moments appear satisfactory.

### 1.2 Gaussian random number generation

The target is the fully specified standard normal distribution, with density phi(x)=exp(-x²/2)/sqrt(2*pi) and cumulative distribution Phi(x). Three distinct claims must be separated: mathematical distributional exactness, numerical fidelity of a finite implementation, and empirical agreement of observed samples with the null model. The saved tests address the third claim. They can help find numerical or implementation problems, but cannot prove the first.

### 1.3 Classical Ziggurat

Classical Ziggurat uses layered proposals and acceptance/rejection to preserve the target density. Finite layer count affects efficiency and table size, rather than inherently approximating the Gaussian distribution. The original Ziggurat publication provides the methodological background [R1]; the particular C implementation evaluated here uses floating-point uniforms and a separate random sign. Performance conclusions apply to this implementation, rather than every optimized Ziggurat implementation.

### 1.4 Proposed Trapezoidal Ziggurat

The project replaces curved horizontal regions with fitted trapezoids and optionally recursively subdivides extreme head and tail regions. Its sampling loop uses rectangle/triangle mixtures and table descent. There is no Gaussian density comparison to correct a proposed draw. Consequently, this implementation requires both approximation assessment and performance measurement.

### 1.5 Research questions

The central question is whether an approximate sampler can materially outperform a theoretically exact reference while satisfying application accuracy needs. The study examines layer count, head depth H, tail depth T and uniform PRNG choice. It distinguishes within-N speed gains from gains over the best tested Classical configuration; these are different deployment decisions. Ten explicit research-question answers are given in Section 10.

## 2. Algorithm overview

### 2.1 Standard normal distribution

Every saved goodness-of-fit test uses fixed N(0,1). Neither mean nor variance is fitted, and samples are not standardized before testing. Sample variance uses denominator m-1. Here m denotes the number of Gaussian samples, while N denotes the number of layers. Empirical moment errors are |sample mean| and |sample variance-1|. KS distance D is a sample-to-target CDF discrepancy; it contains sampling variation and is not a direct estimate of deterministic algorithmic bias.

### 2.2 Classical Ziggurat

In c/ziggurat_basic.c, a layer is selected uniformly. Interior rectangle candidates below the guaranteed interior boundary return immediately. Boundary-strip candidates are accepted only when a uniform height is below exp(-candidate²/2); rejection restarts layer selection. The base region mixes a rectangle with a tail procedure. The latter proposes xt=-log(1-U)/R and yt=-log(1-V), accepting when 2*yt>xt² and returning R+xt. A separate sign draw produces symmetry. Tables are built from an equal-area recurrence with precomputed cutoffs for N=8,16,32,64,128,256.

### 2.3 Theoretical exactness of Classical Ziggurat

Uniform proposals within equal-area covering regions, followed by exact under-density acceptance, give constant accepted joint density below the target curve. Marginalizing the accepted height therefore gives the Gaussian density. An exact conditional tail procedure completes the unbounded region. Changing a valid finite layer count changes proposal efficiency without changing the accepted target law. This statement assumes ideal independent uniform inputs, exact arithmetic and mathematical functions, correct table areas and correct boundary and tail conditions.

Practical software does not meet these assumptions literally. PCG32 and xoshiro256+ have finite state and period; uniforms have finite precision; tables and exp/log evaluations are rounded. This implementation preserves a rounded N=128 cutoff and permits a larger final-peak tolerance there (1e-10, versus 2e-12 otherwise). These are numerical implementation considerations, not evidence of inherent Classical approximation. A future isolated Classical rejection would require investigation of calibration, numerical behavior, PRNG effects, implementation defects and Type I error before assigning a cause.

### 2.4 Trapezoidal approximation

The inspected c/ziggurat_trapezoid.c partitions using G(x)=x*phi(x)+Q(x), where Q=1-Phi, and numerically inverts area targets with 100 bisection iterations. Each horizontal slice fits the inverse-density width x(y)=sqrt(-2*log(sqrt(2*pi)*y)) with a first-order orthonormal Legendre expansion. Composite Simpson quadrature uses 4,096 subintervals; a squared change of variables handles the tail singularity. The fitted endpoints define a rectangle width w and triangular increment d. The code selects the rectangle with probability 2w/(2w+d), returning w*U; otherwise it returns w+d*|U1-U2|. Since |U1-U2| has density 2(1-z), this produces the intended triangular component of the fitted geometry. These branches are component selections, not Gaussian rejection correction.

An ideal continuous projection preserves the constant width moment of its fitted slice; this area property alone does not preserve the pointwise Gaussian shape. Numerical quadrature and table construction add separate approximation sources. The implementation approximates the sampling region through inverse-PDF fitting, thereby changing the output density. No claim that every possible trapezoidal sampler is biased follows: a proposal-based trapezoidal design with a valid exact rejection correction could retain exactness. The conclusion here follows from this code's absence of that correction.

There is also a qualitative tail distinction. Each terminal fitted table has finite coefficients and each rectangle/triangle sample has bounded magnitude. For finite H and T, there are finitely many terminal entries, so this sampler has bounded output support under its fitted representation; a mathematical Gaussian has unbounded support. This establishes that the implemented geometric family is approximate even before finite uniform precision is considered. The support cutoff was not measured in the saved experiments, so no quantitative omitted-tail probability is asserted.

### 2.5 Head/tail refinement

The root table covers the positive half-density. Head descent replaces the first horizontal region with another N-way partition; tail descent replaces the last. Once descent has chosen a side, only that same extreme side can recurse further. The terminal layer is sampled from its fitted geometry, followed by a sign. Refinement targets extreme-region geometry rather than correcting every interior fit. Interior approximation can therefore remain after deeper head/tail refinement. Increasing H or T changes random-number consumption and subsequent stream alignment, so same seed does not provide paired identical observations across different depths.

The loop has no Gaussian rejection restarts. At most max(H,T) descents occur, followed by a component draw. Under ideal uniform layer selection, each next extreme descent has conditional probability 1/N, yielding a rapidly decaying frequency of deep paths. This structural observation explains why extra depth may add little average work, but it is not a measured latency distribution.

### 2.6 PRNG implementations

PCG-XSH-RR uses a 64-bit state update and 32-bit outputs. Each double uniform combines the upper 27 bits of one output and upper 26 bits of a second, yielding a 53-bit grid in [0,1). xoshiro256+ uses a four-word state and one 64-bit output per uniform, discarding its lower 11 bits and scaling the upper 53 bits by 2^-53. SplitMix64 initializes its state. Both tested paths therefore use the same nominal uniform precision, but different generator-call counts per uniform. The xoshiro specialization includes the same sampler source with symbol remapping. This comparison does not establish PRNG independence or long-stream statistical quality. The PRNG authors' source and discussion provide background [R3].

## 3. Experimental methodology

### 3.1 Software environment

Archived results identify Apple Clang 17.0.0 (clang-1700.6.3.2), optimization -O2 and flags -std=c11 -Wall -Wextra -pedantic -O2. Later metadata identify macOS-26.2-arm64-arm-64bit. Python numerical provenance includes Python 3.12.7, NumPy 1.26.4 and SciPy 1.13.1. The precise CPU model, core affinity, frequency policy and thermal state are not supplied sufficiently to reproduce hardware conditions; arm64 is an architecture identifier, not a processor model. No present-host hardware assumption is substituted for archived benchmark metadata.

Experiment 01's executable hash begins c6bfdc88; later temporary builds have other hashes. Full hashes, compiler/build commands, timestamps and source records are retained in analysis/provenance.json and normalized CSV original_record columns. Some later source snapshots differ from current uncommitted files, so saved metadata and archived artifacts take precedence when reconstructing measured conditions. The repository already contained uncommitted Experiment 06 work before this report. No original source or result file was modified.

### 3.2 Experiment configurations

PCG32 is used by Experiments 01–04. Experiments 05–06 use xoshiro256+. The dedicated prng_comparison results provide a separate, directly matched PRNG study at N=128. It is supplemental evidence, not an invented seventh numbered experiment. H/T do not apply to Classical and are recorded as N/A, even when a raw C record encodes zeros. Trapezoid and trapezoid_refined labels are normalized to Trapezoidal while preserving H/T and original labels in original_record.

Only saved data were read. No experiment driver was imported or executed, no sampler was rebuilt or run, and no additional goodness-of-fit test was performed. The report recomputes descriptive timing statistics and rejection summaries. Original JSON records, including numerical flags and available tail summaries, remain traceable through source paths and indexes.

### 3.3 Statistical validation methods

The per-test significance level is 0.05 throughout. Decisions are Rejected, Not rejected, Not tested or Inconclusive. A valid saved decision is retained even when AD omits a p-value below calibration resolution; its statistic and critical threshold still determine rejection. An underflowed p-value of zero is numerical rounding, not a mathematically zero event probability. No p-value is used as an accuracy score.

Pearson chi-square uses 100 equal-width interior bins on [-5,5] for Experiments 01–05, plus two unbounded tail bins. Experiment 06 uses 512 interior bins plus two tails. Expected counts are m*[Phi(right)-Phi(left)], evaluated with survival-function differences on the positive tail for stability. Bins are pooled left to right using expected counts only until each expected count reaches 5; the final remainder merges backward. Degrees of freedom are final bins minus one because no null parameters are fitted. Final bin counts are 98 at m=10 million with the 100-bin setting, 102 at 33,554,432 or 100 million with that setting, and 492 at 33,554,432 with the 512-bin setting. Raw chi-square values are compared only within the same m and bin calibration [R2].

KS uses the complete sorted sample and a fixed-null two-sided finite-sample calibration. CvM uses complete order statistics with a finite-sample approximation. AD uses a fixed-null probability transform with the saved Marsaglia-Marsaglia finite-n approximation and a critical-value decision; upper-tail p-values below 1e-4 are omitted. These approximations and test dependence limit interpretation. No multiple-testing adjustment was applied in the original experiments. Rejection of any test is used here only as an exploratory screening flag, not a proof of a defect.

Repeated-seed summaries retain sample count, PRNG, N/H/T, test and chi-square calibration. Duplicate same-configuration, same-seed results are not counted as additional independent runs. The 100-million PCG32 streams shared by Experiments 01 and 04, and xoshiro seed-1 streams shared by Experiments 05 and 06, are explicitly identified. Prefixes with different m can overlap; they are not independent datasets. No second-level uniformity test is defensible from only two or three comparable seeds per configuration. Under a calibrated continuous null and independent inputs, p-values are approximately uniform and the expected rejection rate is 5%; a small realized count need not equal 5%.

### 3.4 Performance benchmarking

Throughput is m/elapsed_seconds/10^6 in Msamples/s. Each cohort retains algorithm, N/H/T, PRNG, sample count, seed, warmup and harness. Reported mean, median and sample standard deviation are calculated across saved timing repetitions; coefficient of variation is 100*SD/mean. Medians are the primary point comparisons. Speedup is median Trapezoidal throughput divided by matched Classical throughput, not the median of paired ratios. Improvement is 100*(speedup-1). Refinement overhead is 100*(1-refined median/unrefined median) at fixed N and Experiment 01 conditions.

Experiments 01 and the dedicated PRNG comparison have no Gaussian warmup. Experiments 03–04 warm 100,000 samples outside timing and reset the seed. Experiment 05 has no warmup and uses cumulative checkpoints in one fixed 2^25-sample stream; its four checkpoints are dependent. The standard loop includes sample generation, checksum, sum and sum-of-squares work. Initialization and expensive table fitting are excluded. Checkpoint clock reads and intervening bookkeeping contribute to subsequent cumulative timings. Validation transfer/output timings are not substituted for benchmark timings. Timing repetitions measure runtime variation, not independent statistical validation: the seed is reused.

Different harnesses, warmups, PRNGs and sample counts are not pooled. Within-cohort ratios are primary evidence; cross-cohort patterns describe robustness without assigning all differences to one cause. Error bars in Figure 1 show repetition SD around the median for descriptive variability; they are not confidence intervals. No timing significance test or causal hardware attribution is claimed.

### 3.5 Experiment 01–06 inventory

Table 1 identifies the implemented objectives and completion coverage. All six numbered experiments have saved completed outputs for their planned scopes; absence of a measurement outside that scope is still a limitation. Existing output plots and reports were inspected as supporting context; numerical files determine quantitative claims. Input datasets are generated streams recorded during the original experiments, not external observational data. Raw Gaussian observations were discarded after validation; only numerical summaries and hashes remain. Report production does not regenerate them.

**Table 1. Experiment inventory.** Complete metadata and sources are in tables/experiment_inventory.csv. GOF denotes Chi-square, KS, CvM and AD.''')
table(['Exp. / name','Objective','Algorithms / variables','Samples / seeds','Metrics / saved results'],[[r['experiment']+' '+r['name'],r['objective'],r['algorithms']+'; '+r['configurations'],r['samples']+'; '+r['seeds'],r['metrics']+'; '+r['results_available']] for r in inventory])
text('''Experiments 01–06 all contribute accuracy evidence; 01,03,04,05 contribute timing and accuracy/performance comparisons. Experiment 01 profiles PRNG work; the dedicated PRNG study changes the uniform source under matched conditions. Refinement efficiency is addressed by the full Experiment 01 grid and the Experiment 06 same-seed H2/T4 versus H4/T6 validation. Experiment 06 has no throughput measurements. Original generated figures cover grid heatmaps, statistical comparisons and tails in 01, seed comparisons in 02, layer plots in 03, separate sample-count layer plots in 04 and cumulative speed curves in 05. Experiment 06 supplies validation tables/reports rather than a timing plot. The new eight figures consolidate this evidence without treating missing plots as missing experimental results.

**Table 2. Configuration summary.** This compact view gives the complete tested parameter ranges; per-configuration, seed and timing-prefix records are in tables/configuration_summary.csv.''')
table(['Exp.','Algorithm','N','H','T','PRNG','Samples'],[
['01','Classical','8,16,32','N/A','N/A','PCG32','100m'],['01','Trapezoidal','8,16,32','0..4','0..4','PCG32','100m'],
['02','Classical','8','N/A','N/A','PCG32','100m'],['02','Trapezoidal','8; 8,16,32','0; 2','0; 4','PCG32','100m'],
['03','Both','8..256','2 (T only)','4 (T only)','PCG32','10m'],['04','Both','8..256','2 (T only)','4 (T only)','PCG32','100m; 2^25'],
['05','Both','8..256','2 (T only)','4 (T only)','xoshiro256+','2^25'],['06','Trapezoidal','8..256','2; 4','4; 6','xoshiro256+','2^25'],
['PRNG','Both','128','2 (T only)','4 (T only)','Both','10m']])

text('''## 4. Statistical accuracy results

### 4.1 Theoretical accuracy baseline

Classical is theoretically exact under the ideal assumptions of Section 2.3. Experiment 01's three Classical configurations and Experiment 05's six Classical configurations show no rejection across their four saved tests; Experiment 02's Classical N=8 also has no rejection. These checks support the evaluated implementations over their tested streams, but do not establish PRNG quality, independence or correctness for all seeds.

### 4.2 Chi-square results

Every one of the 75 Experiment 01 Trapezoidal configurations rejects chi-square at 100 million samples. All three Classical configurations do not reject. This separates the observed benefit of refinement from complete recovery of Gaussian agreement. Experiment 02 confirms chi-square rejection for the four selected Trapezoidal cases under seed 2. Its unrefined N=8 case rejects all four tests under both seeds. Repeated very small chi-square p-values at low N are consistent with stable distributional discrepancy and the known uncorrected geometric approximation. They do not by themselves isolate fitting error from other numerical or implementation effects.

Table 3 gives fine-bin results at fixed m=2^25, H2/T4 and xoshiro256+. All final bin counts are 492 and df=491. The small-N rejections persist across all three seeds. Larger N has fewer rejections, but no N is free of all four test rejections over the three seeds. The individual p-values are presented for reproducibility, not for ranking closeness to Gaussianity.

**Table 3. Experiment 06 chi-square validation and repeated seeds.** All rows: Trapezoidal, H2/T4, xoshiro256+, m=33,554,432, 492 bins, df=491. R means rejected and NR means not rejected. Other test outcomes appear in Figure 3 and Appendix B.''')
table(['N','Seed 1 statistic / p','Seed 2 statistic / p','Seed 2026 statistic / p','Rejected seeds'],[[n]+[f"{f(test(vv(e,n),'Chi-square')['statistic'],7)} / {f(test(vv(e,n),'Chi-square')['p_value'],5)}" for e in ['experiment06','experiment06_seed2','experiment06_seed2026']]+[f"{sum(test(vv(e,n),'Chi-square')['outcome']=='Rejected' for e in ['experiment06','experiment06_seed2','experiment06_seed2026'])}/3"] for n in LAYERS])
text('''Experiment 03's 10-million PCG32 H2/T4 datasets reject chi-square only at N=8. At 100 million in Experiment 04, N=8,16,32,64,128 reject, while N=256 does not. For example, N=32 has chi-square 94.1327, df=97, p=0.563529 at 10 million, versus 215.5520, df=101, p=2.70347e-10 at 100 million. The raw statistics are not directly comparable because sample count and final bins change. These decisions demonstrate sensitivity to power and binning, rather than a contradiction in mathematical exactness.

### 4.3 Other goodness-of-fit tests

The Experiment 01 Trapezoidal grid has 27 KS, 16 CvM and 27 AD rejections in addition to 75 chi-square rejections. Refinement often removes the global CDF-test rejection while localized discrepancies remain detectable by the chosen histogram test. This is a plausible explanation based on the different statistics, not proof of a specific spatial error pattern: saved per-bin residuals are insufficient for that localization.

Experiment 05 rejects Trapezoidal chi-square at N=8,16,32,64 and KS at N=8. Its N=128 and N=256 configurations have no rejection in the four-test screen. In Experiment 06 seed 1, the same N=32 stream changes from chi-square rejection with 100 interior bins to non-rejection with 512 interior bins. KS, CvM and AD are unchanged for identical streams. More bins do not automatically increase power against every deviation: the degrees of freedom and alignment of departures with bin boundaries also change. Figure 3 presents the resulting decisions without converting them into accuracy grades.''')
fig('validation_heatmap','Figure 3. Statistical validation heatmaps. Each cell retains its saved per-test decision. Panels have distinct stream and calibration labels; H2/T4 applies except where marked H4/T6. Non-rejection does not prove exactness.')
text('''### 4.4 Accuracy versus layers

For Classical, empirical mean, variance and KS discrepancies fluctuate with N under one seed; none is evidence that increasing layers improves theoretical exactness. For Trapezoidal, Experiment 01 unrefined KS distance decreases from approximately 8.70e-4 at N=8 to 2.35e-4 at N=32, while chi-square remains rejected. Refinement and larger N generally reduce severe departures, but the resulting sample discrepancies are not monotonic. Figure 7 shows this directly in the xoshiro cohort; its noisy moment errors cannot be interpreted as a deterministic convergence rate.

### 4.5 Accuracy versus refinement

At fixed PCG32, N=8, seed 1 and 100 million samples, moving from H0/T0 to H2/T4 reduces KS D from 0.000869853 to 0.0000830202 and chi-square from 192084.523 to 975.411 with unchanged df=101. The latter still rejects. Head-only H2/T0 gives D=0.000632958; tail-only H0/T4 gives approximately D=0.0008751. Thus a large improvement from combined refinement cannot be assigned to either depth alone. Figure 5 compares single-variable slices with the other depth fixed.

The tail summaries provide a concrete distributional consequence. Table 3a shows the saved two-sided event P(|X|>z) at N=8, seed 1. The unrefined tail deficit at z=3 and complete absence beyond z=4 agree with the qualitative bounded-support concern. Refinement restores much of the observed tail mass. The refined z=2 error is larger than the unrefined error, illustrating that local improvements need not improve every tail threshold. No new tail test was run.

**Table 3a. Experiment 01 two-sided tail probabilities at N=8.** Each row uses 100 million samples. SE is the binomial standard error under the Gaussian null; it is a scale reference, not an adjusted confidence statement.''')
tails=list(csv.DictReader((HERE/'tables/tail_results.csv').open()))
tailrows=[r for r in tails if r['N']=='8' and (r['algorithm']=='basic' or (r['H'],r['T']) in [('0','0'),('2','4')])]
table(['Configuration','z','Observed count','Empirical probability','Absolute error','Null SE'],[[('Classical' if r['algorithm']=='basic' else 'Trapezoidal H'+r['H']+'/T'+r['T']),r['threshold'],r['observed_count'],f(float(r['empirical_probability']),7),f(float(r['absolute_error']),5),f(float(r['binomial_standard_error']),5)] for r in tailrows])
text('''Experiment 06's seed-2 H4/T6 comparison changes both depths together. Its chi-square rejections at N=8,16,32 persist, with nearly unchanged statistics relative to H2/T4. At N=8 the statistic changes from 964.795 to 962.554; at N=16 it changes from 620.507 to 621.305. KS rejection at N=16 disappears, while N=32's KS/CvM and N=256's KS rejections remain. This is evidence of diminishing returns for the measured combined depth increase, not an isolated estimate of either H or T's effect. No H4/T6 throughput was measured, so its runtime penalty cannot be quantified.

### 4.6 Repeated-seed consistency

The chi-square rejection frequencies across the three H2/T4 xoshiro seeds are 3/3,3/3,2/3,1/3,1/3,1/3 for N=8 through 256. With any-test screening, these become 3/3,3/3,2/3,1/3,1/3,2/3, because seed 2 also rejects KS at N=256. These are descriptive frequencies from three seeds, not stable population estimates. The three large-N cases may include Type I variation; the low-N repeated very small p-values are substantially more compelling evidence of persistent discrepancy. All p-value lists and rejection counts are retained in repeated_seed_summary.csv, grouped by compatible calibration. No uniformity claim or pooled p-value test is made.

## 5. Computational performance results

### 5.1 Throughput versus layers

Both algorithms generally gain throughput as N increases over the tested range. In Experiment 03 the Classical medians rise from 59.497 to 177.576 Msamples/s and Trapezoidal from 78.344 to 144.361. The 100-million Experiment 04 cohort has corresponding endpoints 58.934 to 177.072 and 77.652 to 143.325. Trapezoidal's gain flattens at high N; Classical continues to improve. The 2^25 PCG32 cohort shows an unusually low Classical N=64 median and Trapezoidal N=128 median relative to nearby cohorts. Those observations are retained, not smoothed away or assigned a cache explanation without hardware counters.''')
fig('throughput_vs_layers','Figure 1. Throughput versus layers in four distinct cohorts. Points are medians and bars show sample SD over five timing repetitions. All Trapezoidal curves use H2/T4. Warmup and harness differ between PCG and xoshiro panels, precluding direct attribution of cross-panel gains to the PRNG alone.')
text('''### 5.2 Classical versus Trapezoidal

Trapezoidal beats matched Classical at N=8,16,32 in Experiment 03 and the 100-million Experiment 04 cohort; the crossover lies between tested N=32 and N=64. Experiment 04's 2^25 cohort also has a Trapezoidal advantage at N=64, but this does not repeat in the other PCG32 cohort. Experiment 05 has a practical tie at N=64 (ratio 0.99935), with a Trapezoidal advantage at N<=32 and Classical advantage at N>=128. Exact crossover values between tested N are not measured.

Table 4 reports the directly matched Experiment 05 full-length measurements. Five timing repetitions reuse seed 1; their variation is not evidence from five independent Gaussian streams. The Trapezoidal N=8 CV exceeds 10%, so its median speedup should not be interpreted as a precisely stable hardware constant.

**Table 4. Experiment 05 full-run throughput.** All rows use xoshiro256+, m=33,554,432, seed 1, -O2, five repetitions, zero warmup. Trapezoidal uses H2/T4. SD and mean are across repetition throughputs. Full metadata and all other cohorts appear in tables/throughput_summary.csv.''')
table(['Algorithm','N','Mean','Median','SD','CV (%)','Speedup'],[[a,n,f((r:=perf('experiment05',n,a))['mean_Msamples_s'],7),f(r['median_Msamples_s'],7),f(r['std_Msamples_s'],5),f(r['CV_percent'],4),f(r['relative_speedup'],6)] for n in LAYERS for a in ['Classical','Trapezoidal']])
fig('relative_speedup','Figure 2. Trapezoidal/Classical median-throughput ratios within each cohort. The unity line distinguishes faster and slower configurations. Sample-count and harness differences remain visible as separate series.')
text('''### 5.3 Refinement overhead

Table 4a holds Experiment 01 timing conditions fixed. H2/T4 reduces throughput relative to H0/T0 by 23.63% at N=8, 12.87% at N=16 and 8.08% at N=32. These are throughput losses; corresponding increases in time per sample would be different percentages. Head-only and tail-only settings are also shown. Once most extreme-region error is reduced, deeper refinement changes throughput modestly and non-monotonically within observed run variability. It does not remove interior fitting error.

**Table 4a. Matched refinement throughput and overhead in Experiment 01.** PCG32, seed 1, 100 million samples; medians of ten repetitions.''')
table(['N','H','T','Median (Msamples/s)','Overhead (%)','KS D','Chi-square'],[[n,h,t,f((r:=next(r for r in O if (r['N'],r['H'],r['T'])==(n,h,t)))['median_Msamples_s'],7),f(r['refinement_overhead_percent'],5),f(test(vv('experiment_01',n,h=h,t=t),'KS')['statistic'],6),f(test(vv('experiment_01',n,h=h,t=t),'Chi-square')['statistic'],7)] for n in [8,16,32] for h,t in [(0,0),(2,0),(0,4),(2,4),(4,4)]])
fig('refinement_comparison','Figure 5. Refinement slices with the other depth fixed in Experiment 01. The throughput and KS panels show that an empirical discrepancy can fall substantially while measured throughput decreases. KS distances retain sampling variation; no new goodness-of-fit test is performed.')
text('''### 5.4 PRNG performance

The dedicated matched PRNG study at N=128, ten million samples and five repetitions gives Classical 161.070 Msamples/s with PCG32 and 193.020 with xoshiro256+, a 19.84% increase. Trapezoidal H2/T4 rises from 136.173 to 175.451, a 28.84% increase. Its relative speedup against Classical improves from approximately 0.8454 to 0.90898, yet remains below one. These data demonstrate a material change in measured cost, not a formal test of statistical significance or general superiority of the PRNG. Figure 6 restricts the comparison to this dedicated cohort; Experiment 05 is not compared causally with Experiment 04.

PCG32 spends two generator steps per 53-bit uniform, while xoshiro256+ spends one. Because the Trapezoidal sampling path consumes more uniforms, reducing uniform cost can improve its relative throughput. This mechanism is supported by the source and Experiment 01 call counts, while the exact attribution of runtime savings is unmeasured. The dedicated PRNG comparison has no statistical validation, so it cannot establish unchanged distributional quality after a PRNG substitution.''')
fig('prng_comparison','Figure 6. Dedicated PCG32 versus xoshiro256+ throughput comparison. Both supply nominally 53-bit double uniforms under the same harness, layer count and sample count. Bars are median throughput and error bars are sample SD.')
text('''### 5.5 Acceptance efficiency

Experiment 01 records uniform-call profiling. At N=8, Classical consumes 3.70114 uniforms per Gaussian sample, unrefined Trapezoidal 4.16853 and H2/T4 Trapezoidal 4.35919. Each PCG32 uniform consumes two PCG output calls. For these configurations the estimated PRNG fractions are 0.357726, 0.719197 and 0.558471, respectively. The fractions come from isolated uniform microbenchmark cost multiplied by call counts and divided by a baseline Gaussian timing; they are not exact CPU attribution and need not track the total benchmark speedup proportionally. Profiling timings are not pooled with ordinary timing runs.

Refinement adds layer-selection draws, comparisons and table accesses. It does not increase a Gaussian rejection frequency because this Trapezoidal implementation has no such rejection step. Rectangle and triangle branch names in the source must not be mistaken for acceptance probability against phi. The saved ordinary results do not supply a complete comparable rejection/attempt counter series. Thus no numerical explanation based on rejection frequencies or cache misses is asserted. Initialization, table-fitting cost, latency tails and memory traffic remain unbenchmarked here.

## 6. Accuracy–performance trade-offs

### 6.1 Accuracy-constrained performance

The desired optimization is to maximize throughput(theta), subject to population distributional error(theta)<=epsilon, where theta=(N,H,T,PRNG). Neither epsilon nor an application loss function is defined. This report therefore uses an exploratory screen: a configuration has supported validation in a cohort when all four available saved tests do not reject at alpha=0.05. An unavailable validation is Not tested; a missing decisive statistic would be Inconclusive. A single rejection raises a screening flag, but does not automatically prove systematic bias because multiple, correlated tests are involved.

Under the Experiment 05 screen, the fastest supported configuration is Classical N=256, xoshiro256+, with 211.280 Msamples/s. The fastest locally supported Trapezoidal configuration is N=256,H2/T4 with 180.896 Msamples/s, 14.38% below its matched Classical baseline. N=128 is also locally supported but slower at 177.162. Experiment 06 weakens both Trapezoidal recommendations: N=128 rejects chi-square at seed 2026, and N=256 rejects KS at seed 2 and chi-square at seed 2026. No evaluated Trapezoidal H2/T4 setting has zero rejections across every compatible Experiment 06 seed and test.

**Table 5. Accuracy–performance trade-off in Experiment 05.** Trapezoidal H2/T4 and xoshiro256+ throughout. Error is empirical KS D; speedup uses the same-N Classical median. E06 is a separate later validation screen, not an independent repeat of E05 seed 1.''')
table(['N','E05 validation','KS D','Median Msamples/s','Speedup','E06 any-test rejects'],[[n,'Rejected' if any(r['outcome']=='Rejected' for r in vv('experiment05',n)) else 'No rejection',f(test(vv('experiment05',n),'KS')['statistic'],6),f(median('experiment05',n),7),f(perf('experiment05',n)['relative_speedup'],6),str(sum(any(r['outcome']=='Rejected' for r in vv(e,n)) for e in ['experiment06','experiment06_seed2','experiment06_seed2026']))+'/3 seeds'] for n in LAYERS])
text('''Some earlier, weaker screens do coincide with a same-N speed advantage: Experiment 03 N=16 and N=32 H2/T4 have no rejection at ten million samples, with speedups 1.19545 and 1.02474. Experiment 04 N=32 at 2^25 samples also has no rejection and a 1.04044 ratio. These are legitimate locally supported results, but their PCG32 counterparts reject chi-square at 100 million samples under both available seeds for N=16 and N=32. They establish conditional single-seed gains, rather than a robust approximation guarantee.

A small-N speed advantage is not a global optimization win. In this layer range, increasing Classical N improves its own throughput without sacrificing ideal theoretical exactness. Even the fastest measured Trapezoidal setting in the comparable Experiment 05 cohort remains slower than the fastest Classical setting. Table 5 should therefore support application-specific decisions rather than a default recommendation to use an approximate small-N generator.

### 6.2 Accuracy versus throughput

Figure 4 uses empirical KS distance, not p-values, on its vertical axis. All points have the same PRNG, sample count, timing harness and seed, so the displayed comparison is internally meaningful as an observation. However, different configurations consume different random draws and D includes noise. A point with a smaller realized D has not been proved to have a smaller population approximation error. Moment errors and tail summaries supplement, rather than replace, full-distribution checks.''')
fig('accuracy_vs_throughput','Figure 4. Empirical KS discrepancy versus Experiment 05 throughput, with N labels. The Classical curve is a finite-sample implementation check of a theoretically exact algorithm. No statistical confidence region or rigorous population frontier is inferred.')
text('''### 6.3 Pareto analysis

A rigorous accuracy/performance Pareto frontier requires a common, well-defined population error objective or defensible error estimates with uncertainty. Existing results provide empirical discrepancies and hypothesis-test decisions, not a certified distributional-error bound. No population Pareto-optimal set is claimed. Figure 8 instead gives a validation-constrained ranking inside Experiment 05. Its single-seed criterion is deliberately visible, and later seed rejections are disclosed. Classical's theoretical exactness is additional information that the empirical scatter alone does not encode.''')
fig('validated_throughput_ranking','Figure 8. Throughput ranking under the matched Experiment 05 four-test screen. Green indicates no rejection for that saved seed, not mathematical exactness or robust multi-seed support. The fastest entry is Classical N=256.')
text('''### 6.4 Diminishing returns

The H2/T4 versus H4/T4 Experiment 01 comparisons and H2/T4 versus H4/T6 Experiment 06 comparisons show limited additional improvement in the remaining chi-square discrepancy. Increasing N over a wider range improves measured throughput for both methods and reduces the most severe Trapezoidal departures, but large-N validation is still seed-sensitive. Consequently, larger N appears more promising than indefinite refinement of the extreme regions, subject to table-size constraints. It is not a proved global optimum because no full factorial N/H/T grid exists above N=32, and H4/T6 has no timing evidence.

Figure 7 shows why no monotonic population-accuracy claim is justified: moment and KS errors fluctuate even where rejection counts decrease. The theoretical exactness of Classical does not vary with these observed fluctuations.''')
fig('accuracy_vs_layers','Figure 7. Empirical KS and variance errors versus N for Experiment 05. One seed and one sample count are used; the curves illustrate measured discrepancies, not theoretical error rates.')
text('''### 6.5 Comparison with theoretically exact Classical Ziggurat

Scenario A, faster Trapezoidal with application-acceptable approximation, remains possible but unestablished because no epsilon is specified and the small-N speed leaders reject available validation. Scenario B, slower Trapezoidal with locally supported validation, describes N=128 and N=256 in Experiment 05; these configurations offer no demonstrated CPU accuracy/performance benefit over matched Classical. Scenario C, faster Trapezoidal with persistent discrepancy, describes the small-N results, particularly the repeated low-N chi-square rejections. Such configurations should not be selected solely for speed.

The strongest supported conclusion is that the implementation offers an architectural alternative and measured same-N small-table speed gains, but no compelling default CPU advantage over the best tested Classical configuration when distributional fidelity is required. Whether a specific application can tolerate the small-N errors is unresolved.

### 6.6 Recommended configurations

Table 6 separates deployment advice from research hypotheses. There is no unique most accurate Trapezoidal configuration: the metrics, seeds and calibrations do not support that ranking. A provisional fastest Trapezoidal entry can be named only under the restricted Experiment 05 single-seed screen.

**Table 6. Evidence-based recommendations.** Throughputs refer to the indicated experiment rather than pooled environments.''')
recommendations=[
dict(use_case='Default CPU choice',configuration='Classical N256, H/T N/A, xoshiro256+',accuracy_evidence='E05 four tests not rejected; ideal algorithm exact',throughput_Msamples_s=median('experiment05',256,'Classical'),advantages='Highest E05 throughput; no algorithmic geometric approximation',limitations='One matched validation seed; CPU-specific',confidence='Strong within measured E05 cohort; limited cross-platform generality'),
dict(use_case='Fastest provisional Trapezoidal under E05 screen',configuration='Trapezoidal N256 H2/T4, xoshiro256+',accuracy_evidence='E05 no rejection; E06 seed 2 KS and seed 2026 chi-square reject',throughput_Msamples_s=median('experiment05',256),advantages='Fastest locally non-rejected Trapezoidal result',limitations='14.38% slower than same-N Classical; fails expanded screen',confidence='Tentative; not robust validation support'),
dict(use_case='Most accurate Trapezoidal',configuration='No unique supported selection',accuracy_evidence='Errors fluctuate; no population-error bound',throughput_Msamples_s=None,advantages='Avoids ranking by p-values',limitations='Only 2-3 comparable seeds; no specified epsilon',confidence='Insufficient evidence'),
dict(use_case='Pure throughput within evaluated E05 cohort',configuration='Classical N256, xoshiro256+',accuracy_evidence='E05 no rejection; ideal algorithm exact',throughput_Msamples_s=median('experiment05',256,'Classical'),advantages='Faster than all Trapezoidal E05 entries',limitations='Initialization and table memory not in objective',confidence='Strong within cohort'),
dict(use_case='FPGA research starting point',configuration='Trapezoidal N256 H2/T4, xoshiro256+ as software reference',accuracy_evidence='Best provisional Trapezoidal speed; mixed repeated-seed validation',throughput_Msamples_s=median('experiment05',256),advantages='Bounded table descent; no Gaussian rejection loop',limitations='Large tables; finite support; no FPGA data; compare N128 H2/T4 as area alternative',confidence='Hypothesis only; hardware PRNG choice remains open')]
save('recommendations.csv',recommendations)
table(['Use case','Configuration','Accuracy evidence','Msamples/s','Advantages / limitations','Confidence'],[[r['use_case'],r['configuration'],r['accuracy_evidence'],f(r['throughput_Msamples_s'],7),r['advantages']+'; '+r['limitations'],r['confidence']] for r in recommendations])
text('''## 7. Discussion

### 7.1 Interpretation of accuracy results

The large improvement from unrefined to refined sampling is supported by KS, moment and tail summaries, not merely by a change in p-values. Repeated low-N chi-square rejection is consistent with unresolved localized departures in the fitted density. Isolated large-N rejections have weaker causal interpretation because of multiplicity and few seeds. The absence of Classical rejections in the saved comparisons supports those streams; its exactness claim rests on acceptance/rejection theory, not successful tests.

### 7.2 Sources of approximation error

First-order width fitting approximates a curved inverse-density boundary. Extreme-region recursion improves the geometry there but leaves ordinary interior fitted slices. Simpson quadrature, bisection, floating-point arithmetic and finite uniform precision add separate numerical effects. The terminal tail fit has bounded support. These structural observations explain why exact Gaussianity should not be presumed. Available summaries cannot partition total discrepancy among these sources or quantify the population error at a particular tail threshold beyond the saved observations.

### 7.3 Performance bottlenecks

Uniform generation is material because each Trapezoidal sample uses layer selection, component selection, one or two component uniforms and a sign, plus any recursive selections. Classical incurs rejection and transcendental work on a minority of paths, and its layer geometry improves fast-path frequency as N grows. This provides a mechanism consistent with the measured crossover, but the report does not infer exact branch frequencies without counters. Cache effects, thermal effects and CPU scheduling are possible explanations for timing fluctuations, not measured findings. The PRNG swap offers direct evidence that uniform cost changes relative throughput.

### 7.4 Algorithmic complexity

Both algorithms use constant-time lookup/arithmetic on common paths. Classical has random-length rejection loops with finite expected cost, while Trapezoidal has a finite configured descent bound. Trapezoidal preprocessing is substantial: approximately N*(1+H+T) fitted slices, each with 4,097 quadrature points, plus partition inversions. None of this fitting cost appears in the throughput plots.

The C Trapezoidal table structure contains 1,282 doubles at the compile-time maximum N=256. Its static 33-table array therefore accounts for 338,448 bytes of double storage, independent of the chosen active H/T depths. This is a source-derived storage calculation, not a cache or FPGA resource measurement. An implementation that stores only active entries would scale differently. Classical uses two 256-entry double arrays plus scalar state. These details motivate explicit memory and initialization studies before calling the approximate method simpler overall.

### 7.5 Implications for FPGA implementation

A rejection-free, bounded-depth sampling graph may simplify latency budgeting or pipelining. This is the strongest reason to continue Trapezoidal research even without a CPU speed advantage. However, it still needs PRNG bandwidth, multipliers, absolute differences, table memories, branching/control and precision management. Recursive table addressing can complicate scheduling. Classical requires a policy for rejection restarts and transcendental tail evaluation, but hardware buffering or parallelism may mitigate these costs. CPU throughput does not predict FPGA throughput.

N=256,H2/T4 is a defensible software reference for a first architecture investigation because it combines the highest provisional Trapezoidal throughput with less severe validation evidence than small N, not because it is proven most accurate. N=128,H2/T4 should be an explicit alternative when memory is constrained. No LUT, flip-flop, BRAM, DSP, clock, power or FPGA throughput numbers are available. No hardware superiority is claimed, and the software PRNG choice is not a hardware recommendation.

**Table 7. Classical versus Trapezoidal summary.**''')
summary=[
('Theoretical exactness','Exact under ideal inputs, arithmetic, tables and acceptance/tail rules','Approximate fitted sampling geometry; no Gaussian correction'),
('Approximation error','No inherent layer-count error; practical numerical/PRNG effects remain','Fitting, finite terminal support, numerical construction and PRNG effects'),
('Acceptance/rejection','Gaussian boundary rejection and exact tail rejection','Rectangle/triangle component selection; no Gaussian rejection'),
('Layers N','Primarily efficiency and table size','Efficiency, table size and approximation resolution'),
('Head/tail refinement','Not applicable in evaluated implementation','Recursive extreme-region subdivision, bounded configured depth'),
('Complexity','Fast lookup path; variable rejection loops','Lookup/component arithmetic plus possible table descent; costly preprocessing'),
('PRNG requirements','53-bit uniforms; PCG32 or xoshiro256+','Same precision; more measured uniform calls/sample'),
('CPU throughput','Fastest E05: 211.280 Msamples/s at N256','Fastest E05: 180.896 Msamples/s at N256 H2/T4'),
('FPGA considerations','Tail math and restarts need hardware design','Bounded descent may help scheduling; memory/arithmetic/accuracy costs unmeasured')]
save('classical_vs_trapezoidal.csv',[dict(dimension=a,Classical=b,Trapezoidal=c) for a,b,c in summary])
table(['Dimension','Classical Ziggurat','Trapezoidal Ziggurat'],summary)
text('''## 8. Limitations

Finite samples impose noise and finite power. Increasing m can detect deviations too small for a smaller dataset; failure to reject is not evidence of zero error. Only one validation seed is available for most configurations, two for selected PCG cases and three for H2/T4 xoshiro cases. Timing repetitions reuse the seed. Distinct deterministic seeds are treated as nominally separate streams, without proof of independence.

Multiple hypotheses and correlated tests create false-rejection opportunities. No original familywise or false-discovery adjustment was used. The strict any-test screen is exploratory and can reject a correct implementation by chance. P-values cannot rank population accuracy. Approximate AD and CvM calibration and finite numerical precision create further uncertainty.

Different chi-square binning and expected-count merging produce different degrees of freedom. Raw statistics across incompatible calibrations cannot be compared as an error scale. Histograms and residual arrays needed to localize the discrepancy are not generally retained. Raw sample streams were deleted; new quantile error or independent tail diagnostics cannot be recovered without prohibited reruns. Available KS and moment errors are empirical, not certified population error bounds.

Both uniform generators have finite state, finite period and finite grid precision. This study is not a PRNG test suite and does not evaluate serial dependence, stream overlap or long-period behavior. Changes in PRNG and harness occur together across some numbered experiments, preventing causal attribution. The separate matched PRNG comparison remedies only one N and sample-count setting, with no accompanying validation.

Timing depends on CPU, compiler optimization, warmup, harness, thermal state and background load. Results are from one archived macOS arm64 environment without precise enough hardware controls to claim universality. Small crossover margins have no formal uncertainty test. The sample-count anomaly at N=64 in Experiment 04 and the sizable N=8 Trapezoidal timing CV in Experiment 05 reinforce this caution. Initialization and table-building cost are omitted.

All planned Experiment 01–06 scopes have numerical outputs, but coverage is incomplete for the research question: no Classical validation in 03–04, no timing in 02 or 06, no large-N full refinement grid and no H4/T6 throughput. Later seeds qualify earlier single-seed Trapezoidal claims. There is no defined application epsilon, FPGA implementation or hardware resource/latency/power measurement. Theoretical Classical exactness, practical numerical fidelity and empirical validation remain separate throughout.

## 9. Future work

Future work should first define an application-relevant error tolerance, including rare-tail requirements. Analytical bounds for inverse-density fitting and terminal tail truncation would connect approximation structure to that tolerance. Saved summary evidence suggests studying residual interior fit error after extreme refinement and testing higher-order or constrained fits that preserve useful density properties.

A preregistered repeated-seed validation matrix should include Classical and Trapezoidal at matched m, PRNG, precision and bin rules. It should preserve compact bin counts, edges, residuals, quantiles and tail summaries, permitting later analysis without retaining every sample. Independent-seed counts should be sufficient to characterize rejection variability, rather than interpreting two or three outcomes as a stable frequency. Multiple-testing policy should be specified in advance.

A focused large-N H/T factorial design could compare increased layers with increased refinement under matched conditions. H4/T6 requires throughput measurement before estimating its accuracy-per-cost benefit. The PRNG comparison should expand across N while controlling harness and uniform precision and including matching validation. Timing should record the CPU model, affinity, thermal/frequency controls, initialization cost and meaningful uncertainty on small differences.

An exact correction built around a valid trapezoidal proposal is a possible algorithmic direction, but would require a proven envelope and correct tail treatment; adding a rejection condition informally is insufficient. An FPGA comparison should implement both architectures using defined precision, equivalent random-bit quality and matched output requirements, then measure area, throughput, latency and power. N256 H2/T4 and N128 H2/T4 are starting design points, not established hardware optima. No future experiment was executed for this report.

## 10. Conclusion

**Q1. How does throughput change with N?** Both methods generally accelerate over N=8–256. Classical gains more at high N; Trapezoidal saturates earlier. PCG32 speed crossover is usually between tested N=32 and 64, with one sample-count cohort favoring Trapezoidal at 64. xoshiro Experiment 05 is essentially tied at 64 and favors Classical at 128 and 256.

**Q2. How do H and T affect statistical accuracy?** Combined H2/T4 dramatically improves the unrefined low-N CDF and extreme-tail behavior. It does not remove Experiment 01 chi-square rejection. Deeper H4/T6 has little effect on the persistent seed-2 chi-square discrepancy; head and tail effects cannot be separated in that combined comparison.

**Q3. What performance is sacrificed for better approximation?** In the matched PCG32 Experiment 01, H2/T4 loses 23.63%, 12.87% and 8.08% throughput relative to H0/T0 at N=8,16,32. H4/T6 has no measured speed. Better tail or CDF behavior is supported, but no formal epsilon is certified.

**Q4. Is Trapezoidal ever faster?** Yes. Same-N small-layer medians are higher across several cohorts. Experiment 05 gives ratios 1.465,1.333,1.114 at N=8,16,32. These cases reject at least one matched test; none is faster than the best tested Classical N256 in that cohort.

**Q5. What is fastest with available validation support?** Classical N256 with xoshiro256+ reaches 211.280 Msamples/s with no Experiment 05 rejection. Trapezoidal N256 H2/T4 reaches 180.896 and has no rejection in that one-seed screen, but expanded Experiment 06 seeds reject it. No Trapezoidal setting has robust zero-rejection support across the available three-seed screen.

**Q6. Are more layers preferable to more refinement?** Existing evidence favors investigating larger N after moderate refinement: throughput rises, severe low-N discrepancies diminish and deeper extreme refinement has diminishing returns. An optimal allocation is unresolved without a larger factorial design and explicit error/memory objectives.

**Q7. Does PRNG selection change relative performance?** Yes, materially in the dedicated N128 study: xoshiro256+ raises Classical throughput by 19.84% and Trapezoidal by 28.84%, improving the relative ratio while leaving Trapezoidal slower. A universal effect or formal significance claim is unsupported.

**Q8. What practical benefit is currently demonstrated?** Same-N small-table CPU speed gains and a sampling graph without Gaussian rejection loops. There is no demonstrated overall CPU accuracy/performance advantage over the best tested, theoretically exact Classical configuration when fidelity matters. Application-specific acceptance of approximation remains open.

**Q9. What should enter future FPGA investigation?** Trapezoidal N256 H2/T4 is a provisional software reference, with N128 H2/T4 as a memory-conscious comparison and Classical as the required exact baseline. The proposed benefit is bounded sampling control, not measured FPGA superiority.

**Q10. What remains unresolved?** Population approximation bounds, application tolerance, rare-tail cutoff effects, reliable large-N seed behavior, H4/T6 runtime, full layer/refinement trade-offs, PRNG quality and cross-platform timing generality. Direct, precision-controlled FPGA measurements are required for hardware claims.

The present recommendation is Classical N256 with xoshiro256+ for the tested CPU setting. Continued Trapezoidal work is scientifically justified as an approximation and hardware-architecture investigation, with its residual error and control-flow advantages evaluated explicitly.

## Appendix A. Complete experiment configuration tables

The full tables/configuration_summary.csv preserves experiment, algorithm, N, H, T, PRNG, sample count, seed and source path for every available measured configuration, including Experiment 05's dependent timing prefixes. Table 2 provides the compact complete parameter-domain view. Appendix B and C give the full validation dataset and timing-aggregate coverage below. N/A denotes unavailable or inapplicable information; no missing measurement is replaced by zero.

## Appendix B. Full statistical results

Every saved validation dataset appears below. Cells contain statistic; p-value; decision (R or NR). NA denotes an unavailable p-value; AD decisions still use critical values. All alpha values are 0.05. Table groups identify sample count, PRNG, seed and chi-square calibration. Each row contains the four saved tests, not new validation. Full precision, moments, critical values, numerical flags, source hashes and original records are in tables/validation_summary.csv. Repeated original streams remain visible but do not become extra independent seeds.''')

groups=defaultdict(list)
for r in V:
    key=(r['experiment'],r['samples'],r['PRNG'],r['seed']);groups[key].append(r)
for key,rr in groups.items():
    e,m,prng,seed=key
    bins=rr[0]['final_bins'];df=rr[0]['df'];text(f'### B. {e}; m={m:,}; {prng}; seed={seed}\n\nChi-square final bins={bins}, df={df}. Source: {rr[0]["source_file"]}.')
    configs=sorted(set((r['algorithm'],r['N'],r['H'],r['T']) for r in rr),key=lambda t:(t[0],t[1],-1 if t[2] is None else t[2],-1 if t[3] is None else t[3]))
    out=[]
    for a,n,h,t in configs:
        q=[r for r in rr if (r['algorithm'],r['N'],r['H'],r['T'])==(a,n,h,t)]
        cells=[('C' if a=='Classical' else 'T')+f' N{n}'+('' if h is None else f' H{h}/T{t}')]
        for k in ['Chi-square','KS','CvM','AD']:
            z=test(q,k);cells.append(f"{f(z['statistic'],6)}; {f(z['p_value'],5)}; "+('R' if z['outcome']=='Rejected' else 'NR'))
        out.append(cells)
    table(['Configuration','Chi-square: stat; p; result','KS: D; p; result','CvM: stat; p; result','AD: stat; p; result'],out)

text('''## Appendix C. Full throughput results

All 166 performance aggregates are listed below, with mean, median and sample SD in Msamples/s and CV in percent. Each aggregate retains a fixed seed reused across timing repetitions. Source files and raw run records are in tables/performance_runs.csv; complete grouping metadata and relative speedups are in tables/throughput_summary.csv. Experiment 05 prefix sample counts are distinct dependent checkpoints from five complete 2^25-sample runs. Standard and checkpoint harnesses, PRNGs and sample-count cohorts are never pooled.''')
pg=defaultdict(list)
for r in P:pg[(r['experiment'],r['samples'],r['PRNG'])].append(r)
for (e,m,prng),rr in pg.items():
    text(f'### C. {e}; measured samples={m:,}; {prng}\n\nWarmup={rr[0]["warmup_samples"]}; harness={rr[0]["harness"]}; repetitions={rr[0]["repetitions"]}; seed=1. Source: {rr[0]["source_file"]}.')
    table(['Configuration','Mean','Median','SD','CV (%)','Speedup'],[[config(r),f(r['mean_Msamples_s'],7),f(r['median_Msamples_s'],7),f(r['std_Msamples_s'],5),f(r['CV_percent'],5),f(r['relative_speedup'],6)] for r in sorted(rr,key=lambda r:(r['algorithm'],r['N'],r['H'] or 0,r['T'] or 0))])

text('''## Appendix D. Figure generation and provenance

analysis/consolidate_results.py reads saved validation JSON and timing JSON/CSV only. analyze_accuracy.py summarizes saved decisions and deduplicates same-configuration, same-seed statistical evidence; analyze_performance.py computes cohort-specific descriptive timing statistics. run_analysis.py orchestrates these read-only transformations and saves derived_results.json. generate_figures.py creates eight vector PDF figures and eight 300-DPI PNG counterparts; write_report.py creates this Markdown and its supporting inventory, recommendations and algorithm-comparison tables. render_report.py produces the PDF from this same Markdown. No script imports the experimental drivers or runs the C executable.

Figure 1 uses the raw timing repetitions aggregated by cohort; Figure 2 uses matched ratios of medians. Figure 3 reads saved decisions. Figures 4 and 7 use empirical KS and moment summaries at fixed sample count. Figure 5 uses matched Experiment 01 refinement slices. Figure 6 uses the dedicated PRNG study. Figure 8 ranks Experiment 05 medians using that experiment's saved four-test screen. No p-value is used as an error coordinate or a performance score.

The machine-readable tables preserve full precision rather than the rounded display values. Original fields retained in CSV JSON cells and analysis/provenance.json preserve metadata not normalized into dedicated columns. tables/source_manifest.csv gives SHA-256 hashes for inputs used by the analysis and interpretation. An independent before/after integrity check in analysis/integrity_check.json records source/result preservation during report generation.

## Appendix E. Additional analysis and unresolved measurements

tables/refinement_overhead.csv contains every Experiment 01 Trapezoidal configuration, rather than only the illustrative slices in Table 4a. tables/repeated_seed_summary.csv lists compatible rejection frequencies and full p-value lists with duplicate seed repetitions excluded. tables/tail_results.csv and tables/prng_profile.csv retain all original Experiment 01 numerical columns and source paths. They support the tail and uniform-cost discussion without claiming unavailable quantiles, residual histograms or rejection-loop counts.

No test of p-value uniformity, new significance test, Gaussian draw, benchmark, sampler modification or future experiment is part of this analysis. The fastest statistically screened configuration is an empirical designation within a specified cohort, not a mathematically certified solution of the epsilon-constrained problem.

## References and primary data sources

[R1] Marsaglia, G. and Tsang, W. W. (2000). The Ziggurat Method for Generating Random Variables. Journal of Statistical Software, 5(8), 1–7. https://doi.org/10.18637/jss.v005.i08. Primary methodological reference; no historical throughput figure is compared with this project's measurements.

[R2] SciPy 1.13.1 documentation. scipy.stats.chisquare. https://docs.scipy.org/doc/scipy-1.13.1/reference/generated/scipy.stats.chisquare.html. Used for the no-fitted-parameter degrees-of-freedom convention and calibration requirements.

[R3] Blackman, D. and Vigna, S. PRNG reference implementations and discussion. https://prng.di.unimi.it/ and https://prng.di.unimi.it/xoshiro256plus.c. The project's inspected source, not a generic PRNG label, determines bit precision and call counts in this report.

[D1] experiments/results/experiment_01/{raw/validation,processed,artifacts,execution_order.json}: 78-configuration grid, ten-repetition timing, tails and PRNG profiling.

[D2] experiments/results/experiment_02/processed/validation_results.json and archived configuration/source artifacts: five seed-2 validations.

[D3] experiments/results/experiment03/raw/performance/performance_runs.json; processed/trapezoid_validation_vs_layers.json; artifacts/layers_experiment.json: six-layer PCG32 study.

[D4] experiments/results/experiment04/raw/performance/samples_*/performance_runs.json; processed/trapezoid_validation_vs_layers.json and profile artifacts: two separate sample-count cohorts.

[D5] experiments/results/experiment05/raw/performance/performance_runs.json; processed/validation_results.json; execution_order.json: xoshiro256+ timing checkpoints and both-algorithm validation.

[D6] experiments/results/{experiment06,experiment06_seed2,experiment06_seed2026,experiment06_seed2_H4T6}/processed/validation_results.json and execution_order.json: fine-bin and repeated-seed validation.

[D7] experiments/results/prng_comparison/{runs.json,comparison.csv,metadata.json}: matched uniform-generator timing comparison at N128.

[C1] c/ziggurat_basic.c, c/ziggurat_trapezoid.c, c/pcg_rng.h, c/xoshiro256plus.h, c/prng.h, c/benchmark.c, c/Makefile and experiments/validation.py, together with archived measured drivers and configurations: algorithm and methodology inspection. All project paths are relative to the repository identified in README.md.
''')
(HERE/'report.md').write_text('\n'.join(parts))
print('Wrote report.md;',len(' '.join(parts).split()),'words including tables')
