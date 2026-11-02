# Experiment 14 — memory, per-sample cost consistency and a hardware throughput model

Experiments 10–13 measured speed and output quality. Experiment 14 looks at what a hardware
implementation would care about:

- **A. Memory and word length:** how many table bits each design needs, and how few fraction bits
  the tables can be rounded to before the output gets measurably worse.
- **B. Consistency:** how many uniforms each sample consumes (exactly), and how much the time per
  sample varies on the real C code.
- **C. Hardware throughput model:** samples per clock, PRNG bits per clock and the output FIFO needed
  to hide Classical's slow paths.

The sampler sources in `c/` are not modified. Parts A, B1 and C are calculations; only B2 needs the
isolated CPU.

## Configurations

| Part | Configurations |
|---|---|
| A (memory, δ) | The full Experiment 11 grid: 150 Trapezoid + 6 Classical |
| A (KS, uniform bits), B, C | The shortlist: Classical N = 8–256; Trapezoid H1/T2 at N = 8–256; N=128 H0/T0; N=128 H4/T4; N=256 H4/T4 |

## Files

| File | Role |
|---|---|
| `experiments/experiment14.py` | Driver: `--phase memory, uniforms, timing, summarize, model`. |
| `experiments/experiment14.yaml` | Configuration. |
| `experiments/experiment14_timing.c` | Timing harness. Built automatically to `c/experiment14_timing` (gitignored). |

## 1. Run

From the repository root:

```bash
.venv/bin/python -B experiments/experiment14.py --phase memory      # A, about 7 min
.venv/bin/python -B experiments/experiment14.py --phase uniforms    # B1, about 2 min
.venv/bin/python -B experiments/experiment14.py --phase timing --dry-run
nohup .venv/bin/python -B experiments/experiment14.py --phase timing > exp14_timing.log 2>&1 &   # B2
.venv/bin/python -B experiments/experiment14.py --phase model       # C, needs B1
```

**Ordering:**
- **Phase C (`model`)** reads `path_probabilities.csv` from B1 and `word_length.csv` from A. It does
  not need B2.
- **Phase `timing`** ends by running `summarize` automatically. Run `--phase summarize` again only to
  rebuild the summaries.

**Before `--phase timing`.** The script refuses to start unless all of these hold:

```bash
cat /sys/devices/system/cpu/isolated              # must include 7
cat /sys/devices/system/cpu/cpufreq/boost         # must be 0
cat /proc/sys/kernel/perf_event_paranoid          # must be 1 or less
sudo sysctl kernel.perf_event_paranoid=1          # if it is not (resets at reboot)
```

Close heavy programs before timing, as in Experiments 11 and 13.

**Interruptions.** `--phase timing` writes every run as soon as it finishes, so after an interruption
or reboot simply rerun the same command. Finished runs (status ok) are skipped and failed ones are
retried. The configuration must not change between runs; the script checks it against the saved
`config.yaml`.

**Runtime of B2.** 15 configurations × 2 uniform modes × 1 seed × 3 repetitions = 90 harness runs.
Each run generates a 2 GiB uniform buffer (precomputed mode only), then makes six passes over 2^25
samples: two `perf` passes and three block sizes. Expect about 15–20 minutes in total.

## 2. What each phase does

### A. `--phase memory`

**Table size** (`table_memory.csv`). Only the values used while sampling are counted:

- **Trapezoid:** (1+H+T) × N × 3 values (a, w, d). The x and y tables are used only during setup.
- **Classical:** x and y per layer, plus the base-layer rectangle probability. Classical also needs
  `exp()` and `log()` units in hardware; that is logic, not memory.

Fixed point is unsigned with b fraction bits. Integer bits: a and p 0; y 1; w, d and x 3. Every
value fits.

**Rounding the tables** (`quantization.csv`). The tables are rounded to b = 8–32 fraction bits, and
the exact output law is recomputed:

- **Trapezoid:** the same mixture of trapezoids as Experiment 12, with a rounded independently of w
  and d. Unrounded, it reproduces Experiment 12's δ, which the script checks.
- **Classical:** with rounded tables the layers no longer have equal area, so Classical stops being
  exact. Its exact law is computed as a rejection sampler over the rounded layers. The wedge test is
  integrated in closed form with `erfc`. Unrounded, it gives δ ≈ 10⁻²⁵ and KS ≈ 10⁻¹⁶, which confirms
  the model.

**Word length** (`word_length.csv`). `b_star` is the smallest b at which rounding is negligible:

- **Trapezoid:** rounding changes δ by less than 1%, and also KS for shortlist configurations, at b
  and at every larger b.
- **Classical:** rounding error (δ and KS) is below 1% of the same-N Trapezoid H1/T2 error.
  `b_match` is the smallest b at which it equals that error.

**Uniform word length** (`uniform_bits.csv`). Hardware uniforms are k-bit integers, so the output takes
discrete values:

- **Trapezoid**, at k = 16, 24, 32 and 53 (53 is the C code's double uniforms):
  - δ: exact.
  - `ks_grid`: a lower bound evaluated on the grid.
  - `ks_upper_bound`: the continuous KS + 1.5·2⁻ᵏ.
  - largest lattice step and support.
- **Classical:** k limits the tail. `log()` of a k-bit uniform is bounded, so the largest output is
  r + min(k·ln2/r, √(2k·ln2)), about 9.9σ at k = 32.

### B1. `--phase uniforms`

**Exact pmf of uniforms per sample** (`uniforms_per_sample_exact.csv`, `path_probabilities.csv`):

- **Trapezoid:** levels descended + 1 index draw, then the a-test, then 1 (rectangle) or 2 (triangle)
  uniforms, then the sign. The maximum is 5 + max(H, T).
- **Classical:** a renewal process over attempts:
  - **Attempt outcomes:** fast accept (2 uniforms), base rectangle (3), wedge accept or reject (3), or
    tail with 2 per try.
  - **Then the sign:** 1 more uniform.
  - **Bounds:** there is no upper limit; the pmf is listed until the remaining probability is below
    10⁻¹⁵.

**Check** (`uniforms_summary.csv`). The harness counts the uniforms of every sample over 2^25 samples
(seed 1, not timed), using the precomputed buffer's position. Three things are checked:
- The counts are compared with the exact pmf by χ² (`count_p_value`).
- The mean is compared with Experiment 13's `prng_calls_per_sample`.
- The checksum is compared with Experiment 13's seed-1 checksum, which shows the harness runs
  exactly the same stream.

### B2. `--phase timing`

Each harness process runs on CPU 7 and makes these passes, every one from the seed so all see the
same stream:

1. **Two `perf` passes over the whole loop,** with counters enabled around the loop only:
   - group a: cycles, instructions, branches, branch misses
   - group b: cycles, L1-D loads, L1-D misses

   Two groups mean no counter multiplexing; `counters_multiplexed` confirms it.
2. **Timer overhead:** 10⁶ empty `rdtscp` blocks, whose median is subtracted.
3. **Block timing:** blocks of B = 1, 16 and 256 samples, timed with `lfence; rdtsc` … `rdtscp;
   lfence` and stored as an exact tick histogram.
4. **Precomputed mode, B = 1:** the uniforms used by each sample, giving a joint (uniforms, time)
   histogram.

**Uniform modes:**
- **`precomputed`:** sampler only. This matches Experiments 11 and 13.
- **`inline`:** sampler + xoshiro256+.

**Reading the timings:**
- **Timer granularity.** On this Ryzen the time-stamp counter advances in steps of 32 ticks (10 ns at
  3.2 GHz), and the timer itself costs about 20–30 ns. At B = 1 the resolution is therefore coarse
  and the time per sample is roughly the size of the overhead. Use B = 16 for per-sample variation
  and B = 1 for the rare long samples (the tail of the distribution).
- **L1 misses in precomputed mode** are dominated by streaming the uniform buffer, about 1 miss per
  8 uniforms. Read table cache behaviour from `inline` mode.

### C. `--phase model`

This is a cycle-level model, not synthesis. Every design produces one sample per clock on its fast
path.

| Design | Behaviour | PRNG bits per clock |
|---|---|---|
| `trapezoid_worst_case` | Draws enough bits for the deepest path every clock; one sample per clock, never stalls, no FIFO | (max(H,T)+1)·log2 N + 3k + 1 |
| `trapezoid_common_case` | Provisions for the main level; each descended level costs one extra clock | log2 N + 3k + 1 |
| `classical` | Fast path in 1 clock. A wedge test costs 1 + L clocks (`exp`). A tail try costs L + 1 clocks (two `log`s in parallel). A wedge rejection restarts. L = 10, 20, 40. | log2 N + 2k + 1 |

**Consumer and FIFO:**
- **Demand:** the consumer asks for one sample per clock with probability λ = u / E[cycles per sample],
  at utilization u = 0.5, 0.8, 0.9 and 0.95.
- **Required depth:** the FIFO depth is the smallest one at which the FIFO is empty for fewer than
  10⁻⁹ of demands.
- **Solver:** the exact stationary distribution of the producer–FIFO Markov chain, which was checked
  against a 3-million-cycle simulation.

**Outputs:**
- `hw_model.csv`: every design, latency and utilization.
- `hw_summary.csv`: one row per configuration at L = 20 and u = 0.9, combined with A's word length
  and table size.

## 3. Output files (`experiments/results/experiment14/`)

| File | Contents |
|---|---|
| `table_memory.csv` | Values and bits per configuration and word length. |
| `quantization.csv` | δ, KS, support and variance error per configuration and word length. |
| `word_length.csv` | `b_star` (and `b_match` for Classical) per configuration. |
| `uniform_bits.csv` | Effect of k-bit uniforms. |
| `path_probabilities.csv`, `uniforms_per_sample_exact.csv`, `uniforms_summary.csv` | B1. |
| `timing_runs.csv` | One row per harness run: `perf` counts, time, checksum and its match with Experiment 13, timer overhead. |
| `timing_histograms.csv` | Exact tick histograms (block 0 = timer overhead). |
| `timing_by_uniforms.csv` | Joint (uniforms, ticks) histogram, precomputed mode, B = 1. Ticks are capped at 4095. |
| `timing_summary.csv`, `perf_summary.csv`, `timing_by_uniforms_summary.csv` | B2 summaries. |
| `hw_model.csv`, `hw_summary.csv` | C. |
| `environment.csv`, `config.yaml` | Machine state at start and end of timing; configuration used. |
