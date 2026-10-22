# Precomputed-uniform sweep: Classical vs Trapezoid H2/T4

How to run the throughput sweeps and how to run them under CPU 7 isolation.
All paths are relative to the repository root unless stated otherwise.

## What the sweeps do

| Script | Algorithm | Output directory |
|---|---|---|
| `experiments/tools/classical_precomputed_sweep.py` | Classical Ziggurat | `experiments/results/linux_ryzen2700x/classical_precomputed/<label>-<utc>/` |
| `experiments/tools/trapezoid_h2t4_precomputed_sweep.py` | Trapezoid, H=2, T=4 | `experiments/results/linux_ryzen2700x/trapezoid_precomputed/<label>-<utc>/` |

Defaults: N = 8, 16, 32, 64, 128, 256; seed 1; xoshiro256+; precomputed uniforms
(1 GiB buffer); 10,000,000 samples after a 100,000-sample warm-up; 5 repetitions.
Every run is a separate process, and the order is shuffled within each repetition round.
Each sweep is about 30 runs and takes roughly 30–60 seconds.

Each run writes three files to a new directory (an existing one is an error):

- `summary.csv`: median/mean throughput (Msamples/s), CV%, uniforms per sample, per N.
- `runs.json`: every individual run.
- `metadata.json`: binary SHA-256, git commit and dirty flag, kernel, and start/end snapshots of
  affinity, governor, frequency, boost, load and cgroup.

The scripts exit non-zero if any run fails or exhausts its buffer.

## 0. One-time prerequisites

```bash
cd ~/projects/Ziggurat-Inspired-Method-for-Efficiently-Generating-Gaussian-Random-Numbers-in-Hardware
make -C c CC=gcc O2          # builds c/benchmark
sha256sum c/benchmark         # note the hash; do NOT rebuild between baseline and isolated runs
```

Use the same binary for all four sweeps so the comparison is valid. Close the browser, IDE
and any other heavy programs first.

## 1. Baseline (no isolation, `taskset` only)

Safe to run any time. No privileges needed.

```bash
.venv/bin/python -B experiments/tools/classical_precomputed_sweep.py --label baseline --pin-cpu 7
.venv/bin/python -B experiments/tools/trapezoid_h2t4_precomputed_sweep.py --label baseline --pin-cpu 7
```

`--pin-cpu 7` wraps each benchmark process in `taskset -c 7`. Optional: add
`--seeds 1 2 2026` for more seeds, or `--repetitions 10` for tighter medians.

## 2. Isolated run (single activation per algorithm)

CPU 7 isolation works by constraining every top-level systemd unit to CPUs 0–6, 8–14 and
running the workload in its own unit on CPU 7 only. It does **not** isolate hardware
interrupts, kernel threads or CPU 15 (the SMT sibling of 7), and it does not fix the CPU
frequency (see "What isolation does and does not give you").

### 2a. Read-only checks (as your normal user)

```bash
.venv/bin/python -B experiments/tools/isolation_manager.py plan
```

Expect `"status": "ready_for_explicit_approval"` and `"errors": []`. If not, stop and read the
errors; do not activate.

Confirm the root-owned supervisor is the current version (no output from `cmp` means identical):

```bash
cmp /usr/local/lib/grng-benchmark/isolation_manager.py experiments/tools/isolation_manager.py
ls -l experiments/results/linux_ryzen2700x/sessions/.controller.lock
```

If the supervisor is missing or differs, review the repo copy, then install it (admin terminal):

```bash
sudo install -d -o root -g root -m 0755 /usr/local/lib/grng-benchmark
sudo install -o root -g root -m 0644 experiments/tools/isolation_manager.py \
    /usr/local/lib/grng-benchmark/isolation_manager.py
```

If the lock file is missing (as your normal user):

```bash
mkdir -p experiments/results/linux_ryzen2700x/sessions
touch experiments/results/linux_ryzen2700x/sessions/.controller.lock
```

### 2b. Optional: stop `irqbalance` for the session

`irqbalance` may move device interrupts onto CPU 7. The isolation manager does not control it.
This is a system change, so it is your call.

```bash
sudo systemctl stop irqbalance      # remember to start it again afterwards (step 2e)
```

### 2c. Keep a second terminal open

Have a second admin terminal ready, with the repo as working directory, in case you need to
recover (section 3).

### 2d. Activate and run

From an **admin terminal**, with the repo root as the working directory. One `activate` call
wraps one foreground workload. Run it once per algorithm.

Classical:

```bash
REPO="$PWD"
sudo /usr/bin/python3 -I /usr/local/lib/grng-benchmark/isolation_manager.py activate \
  --approve-isolation --user newuser \
  --controller "$REPO/experiments/tools/benchmark_session.py" \
  --python "$REPO/.venv/bin/python" \
  --session-root "$REPO/experiments/results/linux_ryzen2700x/sessions" \
  --monitor-mode lightweight --interval 1 --session-timeout 300 \
  -- /usr/bin/timeout --signal=TERM --kill-after=5s 240s \
  "$REPO/.venv/bin/python" -B "$REPO/experiments/tools/classical_precomputed_sweep.py" \
  --label isolated --expect-affinity 7
```

Trapezoid H2/T4: the same command, with the last script replaced:

```bash
  "$REPO/.venv/bin/python" -B "$REPO/experiments/tools/trapezoid_h2t4_precomputed_sweep.py" \
  --label isolated --expect-affinity 7
```

Notes:

- Use absolute paths for everything after `--`.
- `--expect-affinity 7` makes the sweep abort unless it is really confined to CPU 7. Do not
  combine it with `--pin-cpu`.
- `--session-timeout 300` and the inner `timeout 240s` bound the session. A full sweep should
  take well under a minute; raise both if you add seeds or repetitions.
- Use `--monitor-mode lightweight`. Do not enable diagnostic or scheduler-tracing mode unless
  you have separately decided to; it needs `--approve-scheduler-tracing`.
- Do not rebuild `c/benchmark` between the baseline and isolated runs.

### 2e. After every session

1. Restoration succeeded. Find the newest session directory and check:
   ```bash
   S=$(ls -td experiments/results/linux_ryzen2700x/sessions/*/ | head -1)
   python3 -c "import json;print(json.load(open('$S/restoration.json'))['verified'])"      # True
   python3 -c "import json;print(json.load(open('$S/isolation_final.json'))['status'])"    # restored
   ```
2. Units are back to normal (`AllowedCPUs=` should be empty again, and the supervisor should
   report no active session):
   ```bash
   systemctl show system.slice user.slice -p AllowedCPUs
   sudo /usr/bin/python3 -I /usr/local/lib/grng-benchmark/isolation_manager.py status
   ```
   (Without `sudo`, `status` only prints "Administrative journal access required".)
   (`cpuset.cpus.effective` does not exist for these groups outside a session, so don't use it
   as a check.)
3. Read `$S/benchmark_quality_final.json`. Expect `WARNING` with scheduling interference
   `UNVERIFIED`. The thresholds are 0 for interrupts and competing tasks, so a real run trips
   them. Look at the numbers (`irq_delta`, `sampled_competitors`, `migration`) instead.
4. Restart `irqbalance` if you stopped it: `sudo systemctl start irqbalance`.

Some runtime drop-ins under `/run` may remain until reboot (`restoration.json` reports
`runtime_override_residue_possible`). This is harmless.

## 3. If something goes wrong

Use the second admin terminal, from the repo root. `SESSION_UUID` is the session directory name.

```bash
M=/usr/local/lib/grng-benchmark/isolation_manager.py
sudo /usr/bin/python3 -I $M status --journal SESSION_UUID
sudo /usr/bin/python3 -I $M verify --journal SESSION_UUID
# supervisor still alive:
sudo /usr/bin/python3 -I $M deactivate --approve-isolation --journal SESSION_UUID
# supervisor gone (orphaned): inspect first, then recover
sudo cat /var/lib/grng-isolation/SESSION_UUID.json
sudo /usr/bin/python3 -I $M recover --approve-isolation --journal SESSION_UUID
```

If recovery refuses because a recorded PID exists or provenance changed, stop and inspect.
Do not kill numeric PIDs or reset cgroup masks blindly. After a reboot, the old journal needs
`--acknowledge-new-boot`; see `CPU_ISOLATION_AND_MONITORING.md`. A reboot also clears runtime
systemd overrides.

## 4. Comparing results

Per-N median throughput from the four `summary.csv` files (adjust the directory names):

```bash
R=experiments/results/linux_ryzen2700x
python3 - <<'PY'
import csv, glob
def load(pattern):
    f = sorted(glob.glob(pattern))[-1]
    return {int(r["layers"]): r for r in csv.DictReader(open(f))}
R = "experiments/results/linux_ryzen2700x"
for mode in ("baseline", "isolated"):
    c = load(f"{R}/classical_precomputed/{mode}-*/summary.csv")
    t = load(f"{R}/trapezoid_precomputed/{mode}-*/summary.csv")
    print(mode)
    for n in sorted(c):
        if n in t:
            a, b = float(c[n]["median_msps"]), float(t[n]["median_msps"])
            print(f"  N={n:<4} classical {a:7.1f}  trapezoid {b:7.1f}  ratio {b/a:.2f}"
                  f"   CV% {c[n]['cv_percent']}/{t[n]['cv_percent']}")
PY
```

Interpretation:

- If baseline CV is already under about 1% and baseline and isolated ratios agree, isolation is not
  changing your conclusion.
- If isolated CV is clearly lower, isolation is helping.
- Compare ratios, not absolute numbers, until the CPU frequency is fixed in BIOS.

## What isolation does and does not give you

Gives you: all ordinary userspace kept off CPUs 7 and 15; the benchmark confined to CPU 7 (checked
before it starts); continuous monitoring from the housekeeping cores; verified restoration.

Does not give you: interrupt or timer-tick isolation (no `isolcpus`/`nohz_full`/`rcu_nocbs`), a quiet
SMT sibling (CPU 15 can still run kernel work), or a fixed frequency. The governor is `schedutil`
with boost on, so reported frequency varies a lot between runs. The quality report will say
`WARNING` / `UNVERIFIED`; that is the honest result for this setup, not a failure.

Related docs: `CPU_ISOLATION_AND_MONITORING.md`, `PRECOMPUTED_UNIFORMS.md`,
`LINUX_BENCHMARK_SETUP.md`, `BIOS_FIXED_FREQUENCY_GUIDE.md`.
