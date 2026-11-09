# Experiment 15 report: exact tail reach and refinement gains over the full grid

All 150 Trapezoid configurations (N = 8…256, H = 0…4, T = 0…4) were analysed exactly from the C tables,
with no sampling. The values agree with Experiment 12 to ≤ 1e-9 wherever both exist. Data:
`experiments/results/experiment15/`; tables and fits: `tables/`; figures: `figures/`.

## 1. Tail reach depends only on M = N^(T+1)

The support edge, and with it every tail metric, is a function of M = N^(T+1) alone. Configurations with
the same M have identical support to within 1.8e-15: for example, N=8/T=3, N=16/T=2 and N=64/T=1 all
stop at 4.923σ. This is exact, not approximate. The tail path descends T+1 levels and each level keeps
1/N of the remaining area, so the last leaf strip always holds a fraction 1/M of the Gaussian. The
fitted law (fig. 1) is

&nbsp;&nbsp;&nbsp;&nbsp;**2Q(support) ≈ 10^-2.16 · M^-1.07**

so each extra tail level pushes the expected out-of-support probability down by about a factor of N.

| N (H≥1) | T=0 | T=1 | T=2 | T=3 | T=4 |
|---|---|---|---|---|---|
| support, N=64 | 3.92 | 4.92 | 5.74 | 6.44 | 7.07 |
| 1%-reliable reach, N=64 | 3.18 | 4.35 | 5.25 | 6.01 | 6.68 |
| support, N=128 | 4.11 | 5.21 | 6.10 | 6.87 | 7.55 |
| 1%-reliable reach, N=128 | 3.41 | 4.67 | 5.64 | 6.47 | 7.19 |
| support, N=256 | 4.29 | 5.48 | 6.44 | 7.27 | 8.01 |
| 1%-reliable reach, N=256 | 3.62 | 4.97 | 6.01 | 6.89 | 7.67 |

(Full table, including tolerance 10%: `tables/tail_reach_by_N_T.csv`.)

**The reliable reach is about 0.4–0.5σ inside the support, not at it.** Just before the cliff, the tail
mass ratio overshoots by **+8.4% to +9.7%** in every configuration (fig. 5). The last leaf trapezoid
places the whole remaining tail mass inside [x_last, support], so mass that belongs beyond the support
shows up just before it. H has no effect on the tails.

## 2. Reach for a given sample count

A tail-count test compares the number of samples with |x| > t (t ≥ 2) with its normal expectation.
`tail_budget` is the smallest n at which any such test reaches 50% power; below it, no tail
deviation is detectable.

| N, H=1 | T=0 | T=1 | T=2 | T≥3 |
|---|---|---|---|---|
| 64 | 2^15.3 | 2^22.0 | 2^27.0 | 2^27.0 |
| 128 | 2^16.4 | 2^24.2 | **2^28.2** | 2^28.2 |
| 256 | 2^17.6 | 2^26.3 | 2^29.4 | 2^29.4 |

For T ≤ 1 the binding test is at the support edge, so the true tail limits the budget. From T=2 onward
(N ≥ 64) the binding test moves to about **3.2–3.6σ**, the bottom of the unrefined body layers, and stays
there for any further T. Past that budget, the reliable reach R(n) shrinks toward 3σ (N=128 H1/T2:
R = ∞ at 2^28, 3.19 at 2^32, 2.98 at 2^36). This happens because of the body error near 3.4σ, not the
tail. At N=128 H1/T2 the tail budget (2^28.2) is close to the χ² detection size (2^27.7), so this
configuration is balanced: neither the tail nor the body is the clear weak point.

## 3. What H and T refinement buy

D-reduction factors (D before / D after adding one level), from `tables/refinement_gain_factors.csv`:

| N | +T: 0→1 | +T: 1→2 | +T: 2→3 | +T: 3→4 | +H: 0→1 (at T=2) | +H: 1→2 |
|---|---|---|---|---|---|---|
| 32 (H=1) | 44.6× | 5.0× | 1.09× | 1.00× | 5.7× | 1.02× |
| 128 (H=1) | 114.7× | 2.2× | 1.01× | 1.00× | 4.2× | 1.00× |

- **T=1 is the big win** (45–115× in D): it removes the coarse bottom-strip error at 3–5σ.
  **T=2 saturates D** for N ≥ 32. Further levels change D by ≤ 9% (N=32), ≤ 2% (N=64) and ≤ 1% (N ≥ 128) but add 0.7–0.8σ of tail reach each,
  plus one table and one more uniform per tail sample.
- **H=1 is necessary and sufficient.** Without it, the top strip near x=0 holds 60–80% of D after the
  tail is refined (fig. 4), and the KS distance stays at its T=0 value (59e-6 for N=128 regardless of
  T). With H=1, KS drops 38× to 1.5e-6 at N=128 T≥1. H≥2 changes D by ≤ 2% for N ≥ 32 (up to 7% at N=16 and 23% at N=8) and never
  changes the tails.
- **Kurtosis** is a tail-sensitive moment check: T=0 has error −4.0e-3 at N=128, T=1 −3.9e-5, T=2 −8e-6.

## 4. The floor is the unrefined body, and only N lowers it

At H≥1, T≥3, about 98% of the remaining D sits at 2–4σ (N=128: 95% at 3–4σ). That is the trapezoid-fit
error of the root layers, which neither H nor T refine. The saturated floor follows

&nbsp;&nbsp;&nbsp;&nbsp;**D_floor ≈ 10^-3.64 · N^-1.37**  (H1/T4: 1.6e-5 at N=8 down to 1.3e-7 at N=256)

so doubling N divides the floor by about 2.6.

## 5. Design rules

1. Use **H = 1**. It removes the head error (KS) completely; more head levels do nothing.
2. Use **T = 2** for distribution quality. Add tail levels only to extend reach: each level adds about
   0.7–0.8σ and divides 2Q(support) by about N.
3. Choose **N** for the body floor (D ∝ N^-1.37) and the sample budget (2^27–2^29 for N = 64–256).
4. Quote the reliable reach as **support − about 0.45σ** (1% tail-mass tolerance), not the support itself.

For the recommended **N=128 H1/T2**: support 6.10σ, 1%-reliable reach 5.64σ, tail budget 2^28.2,
χ² detection 2^27.7, KS detection 2^39.5, table values 2568. With **T=4** the reach grows to 7.19σ
(support 7.55σ) at the cost of 2 more tables, with no change in D.

## Figures

1. `fig1_tail_reach_law.png`: support and 1% reach versus log2 N^(T+1); all N fall on one curve.
2. `fig2_divergence_heatmaps.png`: log10 D over H × T for each N.
3. `fig3_refinement_gain.png`: D and KS versus T for H=0 and H=1.
4. `fig4_divergence_by_region.png`: share of D by |x| region for selected H/T at N=64 and 128.
5. `fig5_tail_ratio_curves.png`: P(|X|>t)/P(|Z|>t) for T=0…4 at N=64 and 128 (H=1).
