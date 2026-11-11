# Experiment 21: timing, one-block Trapezoid against Classical (21a inline, 21b precomputed)

Same grid, seeds and repetitions in both parts; analysed together.

| | 21a | 21b |
|---|---|---|
| PRNG | runs inside the timed loop | outputs generated into a buffer before timing; the timed loop reads them |
| What it measures | full cost of a sample | the sampler's own work, with PRNG cost removed |
| Processes | one per timing (24,300) | one per configuration and seed, 5 timings each (4,860); the buffer fill (0.7–1.2 s) is paid once |
| Runtime | about 6.4 h | about 4 h |

- **Configurations (162):** Trapezoid one-block (`zt_gaussian_philox_1call`) at N = 8…256, H, T = 0…4,
  plus Classical Philox fast (`zb_gaussian_philox_fast`) and Classical xoshiro256+ at every N.
- **Seeds and repetitions:** 30 seeds × 5 repetitions, 2^25 timed samples each.
- **Warm-up and stream:** 10^5 warm-up samples outside timing, then the stream is reset. Every
  repetition times the identical stream; its checksum equals the Experiment 20 validation stream.
- **Precomputed buffers (21b):** sized at 2 Philox blocks or 6 xoshiro outputs per sample and
  followed by an inaccessible page, so a read past the end crashes and is logged as a failure.
  Measured use is 1.000 / 1.013 / 3.06 per sample at N=128.

Harness: `experiments/experiment21_bench.c` (one source; 21b adds `-DPHILOX_PRECOMPUTED -DXOSHIRO_PRECOMPUTED`).
Driver: `experiments/experiment21.py`. Configs: `experiments/experiment21a.yaml`, `experiments/experiment21b.yaml`.
The precomputed mode is a compile-time switch in `c/philox2x64.h` and `c/xoshiro256plus.h`; default builds are unchanged.

## Before starting (sudo)

```bash
echo 0 | sudo tee /sys/devices/system/cpu/cpufreq/boost
echo performance | sudo tee /sys/devices/system/cpu/cpu7/cpufreq/scaling_governor
```

Close VS Code and the browser. The driver refuses to start unless CPU 7 is isolated, boost is 0
and the CPU 7 governor is `performance`.

## Run (both parts, one after the other, about 10.5 h)

```bash
.venv/bin/python -B experiments/experiment21.py --config experiments/experiment21a.yaml --dry-run
nohup sh -c '.venv/bin/python -B experiments/experiment21.py --config experiments/experiment21a.yaml && .venv/bin/python -B experiments/experiment21.py --config experiments/experiment21b.yaml' > experiment21.log 2>&1 &
tail -f experiment21.log
```

Progress is printed every 20 processes. If the run is interrupted, rerun the same command for the
unfinished part with `--resume`. Every row is written to disk immediately.

## Outputs

`experiments/results/experiment21a/` and `experiment21b/`: `timing_raw.csv` (one row per timing),
`metadata.json` (build, binary hash, machine state and temperatures at start and end), `config.yaml`.
