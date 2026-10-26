# Experiment 11 — Classical vs Trapezoid over heads, tails and layers

Throughput and goodness of fit for Classical Ziggurat and every Trapezoid configuration
H = 0–4, T = 0–4, N = 8, 16, 32, 64, 128, 256 (150 Trapezoid + 6 Classical configurations).
H=0/T=0 is the unrefined Trapezoid, so the grid covers the full Classical-vs-Trapezoid comparison.

- **Uniform source:** precomputed xoshiro256+ (2 GiB buffer). PRNG work is excluded from timing.
- **Timing:** 2^25 samples per run after a 100,000-sample warm-up, 5 repetitions, shuffled
  order, each run a separate process pinned to isolated CPU 7.
- **Validation:** every Trapezoid configuration, full 2^25 stream, Chi-square / KS / CvM / AD
  against fixed N(0,1) at alpha = 0.05. Run after all timing is finished, in parallel on the
  other cores.
- **Output:** CSV files only. Raw Gaussian samples are never written to disk, and no report
  is generated.

Files: `experiments/experiment11.py` (driver), `experiments/experiment11.yaml` (configuration).

## 1. Prerequisites

From the repository root:

```bash
cd ~/projects/Ziggurat-Inspired-Method-for-Efficiently-Generating-Gaussian-Random-Numbers-in-Hardware
make -C c CC=gcc O2                                   # builds c/benchmark
.venv/bin/python -c 'import numpy, scipy, yaml'       # required Python packages
```

Do not rebuild `c/benchmark` in the middle of an experiment. Its SHA-256 is recorded in
`environment.csv` at every session start and end, so a mismatch is visible.

Machine state used so far (BIOS): CPU capped at 3.2 GHz, boost off, SMT off. Close the browser,
IDE and other heavy programs before timing.

## 2. Isolate CPU 7 (Linux)

The isolation uses kernel boot parameters: `isolcpus` takes CPU 7 out of the scheduler, so
nothing runs there unless it is explicitly pinned. `irqaffinity` keeps device interrupts on
CPUs 0–6. The script then pins every timed run to CPU 7 with `taskset`.

> The repository's `isolation_manager.py` (systemd cgroup method) is **not** used here.
> It expects the CPU 7 + CPU 15 SMT pair and refuses to run with SMT disabled.

### 2a. Check the current state

```bash
lscpu -e=CPU,CORE,ONLINE                  # expect CPUs 0-7, one per core (SMT off)
cat /sys/devices/system/cpu/isolated      # empty = nothing isolated yet
cat /proc/cmdline
```

### 2b. Add the boot parameters

```bash
sudo cp /etc/default/grub /etc/default/grub.backup
sudo nano /etc/default/grub
```

Change the `GRUB_CMDLINE_LINUX_DEFAULT` line to:

```text
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash isolcpus=domain,managed_irq,7 irqaffinity=0-6"
```

Then apply it and reboot:

```bash
sudo update-grub
sudo reboot
```

`nohz_full=7` and `rcu_nocbs=7` are often recommended as well, but this kernel
(5.15.0-198-generic) is built without `CONFIG_NO_HZ_FULL` and `CONFIG_RCU_NOCB_CPU`, so they
have no effect here. CPU 7 still receives the periodic timer tick. The tick is small and
regular, and it affects all configurations equally.

### 2c. Keep irqbalance off CPU 7

`irqbalance` can move interrupts back onto CPU 7. Use either option.

Stop it for the session (start it again afterwards):

```bash
sudo systemctl stop irqbalance
```

Or ban CPU 7 permanently, by adding this line to `/etc/default/irqbalance`:

```text
IRQBALANCE_BANNED_CPULIST=7
```

Then restart it:

```bash
sudo systemctl restart irqbalance
```

### 2d. Verify after the reboot

```bash
cat /sys/devices/system/cpu/isolated      # must print 7
taskset -pc $$                            # your shell: 0-6
grep -l '\b7\b' /proc/irq/*/effective_affinity_list 2>/dev/null | wc -l   # ideally 0
```

The script refuses to start the timing phase unless CPU 7 is listed in
`/sys/devices/system/cpu/isolated`. It also records the kernel command line, isolated CPUs,
irqbalance state, the number of IRQs on CPU 7, the governor, frequency limits and boost in
`environment.csv`.

### 2e. Undo the isolation

Restore `/etc/default/grub.backup`, or remove the two parameters, then run
`sudo update-grub` and reboot. If you stopped irqbalance, run `sudo systemctl start irqbalance`.
If you added the ban line, remove it and restart irqbalance.

## 3. Run

```bash
.venv/bin/python -B experiments/experiment11.py --dry-run        # print the plan, run nothing
.venv/bin/python -B experiments/experiment11.py                  # timing, then validation
```

Run it from a terminal, not inside the browser or IDE, so those programs can stay closed.
`nohup ... > experiment11.log 2>&1 &` is useful for long runs.

Options:

| Option | Meaning |
|---|---|
| `--config FILE` | Use another YAML file (default `experiments/experiment11.yaml`). |
| `--phase performance` | Timing only. |
| `--phase validation` | Validation only. Use with `--resume` on an existing output directory. |
| `--resume` | Continue in an existing output directory, skipping work already marked `ok` and retrying failures. |
| `--output-dir DIR` | Write somewhere other than `output_dir`, for example a second attempt. |
| `--dry-run` | Print the run counts and an example command, then exit. |

An existing output directory is never overwritten without `--resume`. A resumed run must use the
identical configuration file; the script compares it with the saved `config.yaml`. Only one
process can use an output directory at a time.

**Runtime.** Measured for one configuration (N=8, H=4/T=4, unisolated): about 1.2 s per timed
process and about 6 s per validation. The default grid (780 timed runs, 150 validations with
4 workers) should therefore take roughly 20–30 minutes. Each timed process loads the 2 GiB
uniform cache before its timer starts. Peak memory is about 2.5 GiB per validation worker.

**Smoke test** (seconds, writes only to `/tmp`). Make a copy of the YAML with small values,
for example `layers: [8, 64]`, `heads: [0, 2]`, `tails: [0, 4]`, `samples: 20000`,
`warmup: 1000`, `uniform_buffer_bytes: 1048576`, `repetitions: 2` and
`require_isolation: false`. Then run:

```bash
.venv/bin/python -B experiments/experiment11.py --config /tmp/smoke.yaml --output-dir /tmp/e11smoke
```

## 4. Configure (`experiments/experiment11.yaml`)

| Key | Default | Meaning |
|---|---|---|
| `output_dir` | `experiments/results/experiment11` | Output location, relative to the repository root. |
| `binary` | `c/benchmark` | Benchmark executable. |
| `prng` | `xoshiro256plus` | Fixed for this experiment. |
| `uniform_buffer_bytes` | 2147483648 | Precomputed buffer size. 2 GiB holds 268M uniforms, about 8 per sample at 2^25 samples; the highest observed use is about 4.4. |
| `cache_dir` | `null` | Directory for the temporary 2 GiB uniform cache (null = system temp). The cache is deleted at exit. |
| `layers`, `heads`, `tails` | 8–256, 0–4, 0–4 | The grid. H and T may be 0–16. |
| `include_classical` | `true` | Classical reference at each N; used for `speedup_vs_classical`. |
| `seeds` | `[1]` | Seeds; each adds a full grid. Repeated runs with one seed reuse the same stream. |
| `samples` | 33554432 | Samples per run (2^25). |
| `warmup` | 100000 | Warm-up samples, outside timing. |
| `performance.repetitions` | 5 | Timed repetitions per configuration. |
| `performance.cpu` | 7 | CPU used by `taskset` for every timed run. |
| `performance.require_isolation` | `true` | Refuse to time unless that CPU is isolated. Set `false` only for a deliberate unisolated baseline. |
| `performance.shuffle_seed` | 2026 | Seeds the per-repetition random run order, which is reproducible. |
| `validation.include_classical` | `false` | Also validate Classical configurations. |
| `validation.workers` | 4 | Parallel validations, run on the non-isolated CPUs. |
| `validation.significance_level` | 0.05 | Alpha. |
| `validation.chi_square` | 100 bins over [-5, 5], minimum expected count 5 | Same settings as Experiments 05 and 10. |

## 5. Output files (`experiments/results/experiment11/`)

| File | Contents |
|---|---|
| `performance_runs.csv` | One row per timed process. |
| `performance_summary.csv` | One row per configuration and seed, from `ok` runs only. |
| `validation_results.csv` | One row per validated configuration and seed. |
| `environment.csv` | Machine and isolation state at session start, end of timing, and session end. |
| `config.yaml` | Copy of the configuration used. |

Main columns:

- **Throughput and time** (`performance_runs.csv`):
  - `prng_calls_per_sample`: uniforms consumed divided by samples. Every random input of both
    samplers is one uniform draw.
  - `throughput_samples_per_s` and `throughput_msamples_per_s`.
  - `total_time_s`: sampling time measured by the C timer. It excludes table setup, buffer
    loading and warm-up.
  - `process_wall_s`: the whole process, including loading the uniform cache.
  - Also `status` (`ok`, `failed` or `buffer_exhausted`), `checksum`, mean, variance, and the
    CPU frequency reported just before each run.
- **Summary** (`performance_summary.csv`): median, mean, minimum and maximum throughput,
  `cv_percent`, `median_total_time_s`, `speedup_vs_classical` (same N and seed), and
  `checksums_identical` (repetitions reproduced the same stream).
- **Validation** (`validation_results.csv`):
  - `<test>_statistic`, `<test>_p_value` and `<test>_reject` for `chi2`, `ks`, `cvm` and `ad`.
    `reject` is 1 for rejection and 0 for no rejection at `alpha`.
  - `chi2_degrees_of_freedom`, `chi2_final_bins`, `ad_critical_value`, and `rejections`
    (0–4 per row).
  - `checksum_matches_performance`: the validated stream is the stream that was timed.
  - `stream_sha256`: a digest of the samples, which were not saved.
  - The AD p-value can be empty, because its decision uses the critical value.

All files can be read directly in MATLAB, for example with `readtable`. No multiple-testing
correction is applied: with 600 tests at alpha = 0.05, about 30 rejections are expected by
chance alone.
