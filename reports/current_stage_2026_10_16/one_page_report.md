# Ziggurat-Trapezoid Gaussian RNG: Current Research Stage

Progress report | 16 October 2026 | Based on the completed Experiments 01-06 review

## Research objective and current stage

The project investigates whether a Trapezoidal Ziggurat Gaussian random number generator can offer useful computational savings while maintaining acceptable Gaussian approximation accuracy. The current stage is completed software experimentation and evidence consolidation, with algorithmic accuracy questions still open and FPGA implementation remaining future work. Classical Ziggurat provides a theoretically exact reference under ideal assumptions; the implemented Trapezoidal method samples fitted geometry without an exact Gaussian rejection correction.

## Work completed

C samplers and Python workflows have been implemented and evaluated through six experiments: refinement and profiling (01), selected seed replication (02), layer scaling (03), sample-count effects (04), xoshiro256+ timing and validation (05), and fine-bin/repeated-seed validation (06). The completed review consolidates 137 saved validation datasets, 548 statistical test records and 1,220 timing/checkpoint records. A 44-page technical report, eight figures, consolidated tables and reproducible analysis scripts are available. Duplicate streams and dependent timing checkpoints are identified rather than counted as independent evidence.

## Main findings

| Comparison | Existing evidence |
| --- | --- |
| Best tested CPU configuration | Classical, N=256, xoshiro256+: **211.280 Msamples/s**; no rejection in its four-test, single-seed Experiment 05 validation. |
| Provisional Trapezoidal configuration | N=256, H=2, T=4, xoshiro256+: **180.896 Msamples/s**, **14.38% slower** than matched Classical. It has no Experiment 05 rejection, but later seeds reject KS or chi-square. |
| Refinement cost | H2/T4 improves observed CDF and tail behavior, while reducing throughput versus H0/T0 by **23.63%, 12.87% and 8.08%** at N=8,16,32 in Experiment 01. |

Trapezoidal achieves higher same-N throughput at small layer counts, and some smaller-sample screens show no rejection. However, larger-sample and repeated-seed tests weaken these cases. Increasing N generally raises throughput for both algorithms; Classical becomes faster at larger N. Additional refinement offers limited improvement in persistent chi-square discrepancies, and H4/T6 throughput has not been measured.

## Current assessment and limitations

The strongest CPU recommendation is Classical N=256 with xoshiro256+ for the tested environment. The Trapezoidal implementation has not demonstrated a robust overall CPU accuracy-performance advantage over the best tested Classical configuration. Statistical non-rejection does not establish exactness. Evidence is limited by few independent seeds, multiple correlated tests, differing chi-square bins and platform-specific timings. No application error tolerance or certified approximation bound is available, and no FPGA performance or resource measurements have been obtained.

## Next research stage

Define acceptable distributional and tail errors; investigate residual interior fitting error and finite terminal-tail support; and plan matched repeated-seed and refinement-cost studies. For FPGA investigation, use Trapezoidal N256 H2/T4 as a provisional software reference, compare N128 H2/T4 for memory trade-offs, and retain Classical as the baseline. Evaluate precision, area, throughput, latency and power before claiming a hardware advantage. Bounded sampling control is a hypothesis worth testing, not a demonstrated FPGA benefit.

Source: experiments_01_06/report.md and its consolidated result tables, reviewed 15 October 2026. This summary introduces no new experiments or measurements.
