# GRNG benchmark session protocol

> **Current research workflow:** CPU frequency is configured manually in BIOS. Linux frequency control is out of scope. Use [CPU_ISOLATION_AND_MONITORING.md](CPU_ISOLATION_AND_MONITORING.md) for session-based CPU isolation, continuous housekeeping monitoring, quality reports and recovery. The software-frequency sections below describe retained legacy functionality and are not part of the new workflow; no frequency helper is called by isolation activation.

Infrastructure preparation only, 2026-10-19. No live frequency/governor/boost changes, no administrative deployment, no BIOS changes, no RNG benchmark invocation and no experiment schedule were performed in this task. Existing C timing, RNG/PRNG algorithms, YAML schedules, statistical methods and research results are unchanged.

## Architecture and modes

`tools/benchmark_session.py` is the unprivileged controller. `tools/cpu_benchmark.py` retains its old CLI/output format and supplies shared CPU validation, taskset argv construction, sysfs snapshots and coordination locking. No scheduler changes are needed; wrapping the Python harness later would pin its descendants, but that is not permission to launch its schedule now.

| Mode | Linux setting writes | Verification |
|---|---|---|
| baseline | None | Records current environment; CPU placement controlled by taskset |
| software | Only through the separately approved administrative supervisor | Requests userspace plus min=max=target, checks all readbacks; physical clock remains unverified |
| bios | None, including governor and boost | Records user-configured state, warns on reported-frequency mismatches; never configures firmware |

Target defaults to 3,200,000 kHz and is configurable. Baseline makes no frequency request (telemetry requested_khz is empty). BIOS target is a verification reference, not a Linux request. `physical_clock_verified` remains false in this implementation because no reliable effective-frequency collector is active. BIOS mode can still execute a supplied command with warnings; a successful process exit is not clock certification.

Read-only inspection found acpi-cpufreq, 16 separate policy masks, userspace available, and advertised 2.2/3.2/3.7 GHz states. CPUs 7/15 share physical core7, although policy7/policy15 each report only their own logical CPU. Policy masks do not establish every physical clock/power control domain. Software control therefore conservatively plans **all exposed policies**, including both SMT threads, with explicit whole-workstation scope. This can affect all CPUs. Live hardware acceptance and true shared-domain behavior remain untested.

## Read-only commands

Run from the repository root:

```bash
.venv/bin/python -B experiments/tools/benchmark_session.py --mode baseline --inspect
.venv/bin/python -B experiments/tools/benchmark_session.py --mode software --target-khz 3200000 --plan
.venv/bin/python -B experiments/tools/frequency_control.py --target-khz 3200000 --plan
.venv/bin/python -B experiments/tools/benchmark_session.py --mode bios --target-khz 3200000 --inspect
```

These do not execute a command, create a session, or change settings. Software planning rejects unsupported targets/drivers/governors and missing original state. Only acpi-cpufreq is supported by the current write planner. An existing userspace governor requires a readable numeric original setpoint so it can be restored.

## Unprivileged sessions

Future baseline example; not run during this task:

```bash
.venv/bin/python -B experiments/tools/benchmark_session.py --mode baseline --cpu 7 -- \
  ./c/benchmark --algorithm basic --layers 8 --seed 1 --samples 100000
```

Future BIOS-mode verification session, only after the user's manual firmware preparation:

```bash
.venv/bin/python -B experiments/tools/benchmark_session.py --mode bios --cpu 7 \
  --target-khz 3200000 --telemetry-interval 1 -- \
  ./c/benchmark --algorithm basic --layers 8 --seed 1 --samples 100000
```

All arguments are passed as arrays without a shell. Relative executable/output paths remain relative to the caller's cwd. Unique session directories are exclusive. Commands themselves are not sandboxed: choose new workload output destinations and use foreground commands that do not daemonize, launch background descendants or reset their own affinity. `--overwrite` is rejected. No wrapper can promise to restore affinity or contain arbitrary intentionally escaping workloads.

No warm-up is added implicitly. To use existing C warm-up, explicitly add `--warmup N` to the benchmark command; C performs it outside its sampling timer and resets to the same seed. Do not use a separate warm-up invocation that writes to the same destination. The Linux YAML currently exposes no warm-up setting and is unchanged. Workload sample counts, PRNG, seed and timed-loop definitions are likewise unchanged.

## Explicitly authorized future software control

This section contains **future administrative commands, not commands executed during setup**. Approval flags express the operator's explicit authorization; they do not grant privileges. Obtain permission before deployment, live control, or boost changes. No sudo is called by any tool, no passwords are stored, no privilege delegation/security restrictions are changed, and no root workload is permitted by the documented flow.

1. As the ordinary user, prepare the existing ignored sessions directory/coordination file (no CPU changes):

```bash
mkdir -p experiments/results/linux_ryzen2700x/sessions
touch experiments/results/linux_ryzen2700x/sessions/.controller.lock
```

2. After approval, in an **existing normal administrative terminal**, inspect the supervisor source and install only this standalone stdlib file into a root-owned, non-writable location. Never run an elevated Python script directly from the user-writable checkout.

```bash
install -d -o root -g root -m 0755 /usr/local/lib/grng-benchmark
install -o root -g root -m 0644 \
  /home/newuser/projects/Ziggurat-Inspired-Method-for-Efficiently-Generating-Gaussian-Random-Numbers-in-Hardware/experiments/tools/frequency_control.py \
  /usr/local/lib/grng-benchmark/frequency_control.py
```

The supervisor refuses live use unless its file and every parent are root-owned, not symlinks, and not group/world writable. Administrative invocation additionally requires Python isolated mode (`-I`). It uses only stdlib and fixed `/usr/sbin/runuser` and `/usr/bin/python3` administrative paths. It never imports code from the checkout while privileged. The workload and all writes into the user workspace run through runuser as the named non-root user. Persistent deployment of the reviewed tool is optional; CPU configuration changes remain temporary.

3. Review the plan, then, **only with explicit approval**, run the following in that administrative terminal from the repository root:

```bash
/usr/bin/python3 -I /usr/local/lib/grng-benchmark/frequency_control.py \
  --approve-temporary-control --target-khz 3200000 --user newuser \
  --session-root /home/newuser/projects/Ziggurat-Inspired-Method-for-Efficiently-Generating-Gaussian-Random-Numbers-in-Hardware/experiments/results/linux_ryzen2700x/sessions -- \
  /home/newuser/projects/Ziggurat-Inspired-Method-for-Efficiently-Generating-Gaussian-Random-Numbers-in-Hardware/.venv/bin/python -B \
  experiments/tools/benchmark_session.py --mode software --cpu 7 --target-khz 3200000 -- \
  ./c/benchmark --algorithm basic --layers 8 --seed 1 --samples 100000
```

Boost stays unchanged by default. Only if separately approved, add **both** `--disable-boost --approve-boost-change` before the supervisor's `--`. The unprivileged controller's software target must match the supervisor's target; otherwise it refuses execution. Do not set internal GRNG_* environment variables manually; their presence is coordination/provenance plumbing, not authentication or proof of hardware control. The root journal is the authority for what was actually changed/restored.

The exact planned privileged writes for each policy are:

- Temporarily lower scaling_min_freq if needed to safely adjust limits.
- Write scaling_max_freq=target and scaling_min_freq=target.
- Write scaling_governor=userspace and scaling_setspeed=target.
- Read back governor, min/max and setpoint; abort and restore if any differ.
- Only with separate boost approval: write cpufreq/boost=0 and check readback.

No voltage, BIOS, frequency-table, thermal-limit, service, boot, package, or network changes are made. Requests can fail on real hardware; userspace/min=max/performance never constitute a physical-clock guarantee. Original per-policy governor, limits, userspace setpoint where relevant, and original boost state are restored afterward; boost is written back only if this supervisor changed it.

## Lifecycle, locking and durable restoration

The user controller inspects CPU online/allowed status and records topology, mode, command, environment and verification. It reserves a UUID session directory, captures pre-state, starts a telemetry thread, launches a taskset argv and collects stdout/stderr. It stops telemetry, records final state and process status, and releases the coordination lock. No telemetry is inserted into C code.

The administrative supervisor holds a global flock in root-owned `/var/lib/grng-benchmark/control.lock`, as well as the workspace coordination lock **before applying any settings**. Its child inherits that same locked file descriptor; the controller verifies the file identity and retains a duplicate. Baseline/BIOS/legacy launcher sessions share this coordination mechanism. Locks prevent cooperating sessions from overlapping and keep settings/restoration serialized. They do not constrain other administrative tools, unrelated workloads or power daemons. Use a single workstation session root.

Before the first sysfs write, a root-only UUID journal is fsynced and its containing directory fsynced. It contains every policy's original state, target, boost decision, user/session-root identity, supervisor phase and workload PID. JSON updates use temporary files and atomic replacement. A partial apply or child failure enters try/finally restoration; restoration attempts every policy and checks original values, even after another policy failed. Governor restoration is still attempted when a limit write failed. Partial errors are recorded explicitly. Every new control session refuses to proceed while a prior root journal is unfinished.

INT/TERM/HUP forward to the workload process group in the user controller. Cancellation escalates after five seconds if the direct command does not stop. The supervisor also handles interruption, waits for the user process and attempts restoration in finally; an unresponsive user process is stopped before restoration. The benchmark's actual exit status is preserved (signal termination uses 128+signal), independent of restoration success. Thus **exit code zero alone is insufficient**: check restoration.json/final_status.json and the root journal. Telemetry failure is recorded as session failure while preserving the workload status.

SIGKILL, power loss, kernel failure, detached descendants and filesystem failures can defeat automatic cleanup. A crash between process creation and PID-journal update leaves an additional orphan-identification uncertainty. Do not claim guaranteed recovery. Root journal preparation plus explicit manual recovery makes the missing state visible; it cannot undo lost data or prove that no orphan workload exists.

## Outputs and recovery

New session outputs are isolated under `experiments/results/linux_ryzen2700x/sessions/<UUID>/`:

```text
journal.json          immutable user prepared record
session.json          execution status, exit code and warnings
environment.json      topology, software/build identity and initial state
cpu_telemetry.csv     before/running/after reported-state samples
stdout.txt
stderr.txt
restoration.json      no-change status or privileged restoration result
final_status.json     software supervisor's final combined outcome
```

Baseline/BIOS do not modify settings; their restoration file says not_needed. Software session.json initially says pending_restoration because the user process must finish before the supervisor restores state. Afterward the supervisor writes restoration.json and final_status.json **as the benchmark user**, using exclusive creation. The root journal remains authoritative if report delivery fails. Do not reuse the UUID or overwrite a prior record. Internal sources, untracked files and an independent physical-clock attestation are not archived automatically; retain those separately.

Inspect logs without rerunning the workload:

```bash
find experiments/results/linux_ryzen2700x/sessions -maxdepth 2 -type f
cat experiments/results/linux_ryzen2700x/sessions/SESSION_UUID/session.json
cat experiments/results/linux_ryzen2700x/sessions/SESSION_UUID/restoration.json
head experiments/results/linux_ryzen2700x/sessions/SESSION_UUID/cpu_telemetry.csv
```

Normal restoration is automatic. For interrupted/orphaned software control, first inspect the root journal and process tree in an administrative terminal, stop the identified foreground workload if necessary, and check that no related work remains. PID reuse is possible; a numeric PID is not sufficient identity proof. Recovery refuses a still-existing recorded workload PID and additionally requires an explicit confirmation that workloads have stopped.

```bash
# Administrative terminal, after explicit recovery approval:
cat /var/lib/grng-benchmark/JOURNAL_UUID.json
ps -eo pid,ppid,pgid,lstart,args
/usr/bin/python3 -I /usr/local/lib/grng-benchmark/frequency_control.py \
  --approve-temporary-control --recover JOURNAL_UUID --confirm-workload-stopped
```

Recovery accepts only UUIDs in the fixed root-owned state directory, validates policy names/governors/frequency ranges against current hardware, takes global and workspace locks, replays each original setting, verifies readbacks and updates the root journal. It never runs a benchmark. Reinspect root journal `restoration.verified` and each policy. Existing user restoration files are not overwritten during recovery; the updated root journal is the recovery record. A stranded `.tmp` journal after a crash needs manual administrative inspection; the last fully committed `.json` retains all original settings. Recovery is idempotent for committed original state, subject to policy availability and write permission.

## Telemetry and instrumentation limits

CSV records UTC/monotonic timestamps, session UUID, selected CPU, last-scheduled CPU of the direct child where observable, physical core/SMT siblings, per-policy governor/driver/current/min/max, target reference, boost, labelled hwmon temperatures/limits/alarms, effective-frequency availability, and final workload status. A nested harness's descendant CPUs are not individually observed; affinity inheritance controls them unless they override it.

Default periodic interval is one second (minimum 0.2). The telemetry thread is restricted to allowed CPUs outside CPU7 and sibling15. If none exist, periodic monitoring is disabled with an error record, not silently placed on the benchmark core. Thread overhead still consumes shared memory/cache/package resources. CPU snapshots read all policies/temperature sensors; adjust the sampling interval before the study, document it, and quantify collector overhead in a separate approved study. No benchmark timing is extended inside the C loop. Short commands may yield only before/after rows and explicitly warn that no under-load report was collected.

Current findings: scaling_cur_freq readable; cpuinfo_cur_freq permission denied; sensors installed and k10temp Tctl/Tdie available; perf/cpupower/turbostat absent from PATH; perf_event_paranoid=4. APERF/MPERF/TSC event descriptions exist under `/sys/bus/event_source/devices/msr/events`, but event descriptions do not establish readable counters, correct model-specific calibration or permission. No perf permissions were changed, modules loaded, MSRs accessed, counters fabricated, or packages installed. Effective frequency and hardware cycles are therefore **unavailable** in current outputs. Enabling an appropriate collector later requires review/approval for any installation or privileged access and validation against this CPU.

The kernel distinguishes requested/reporting interfaces from actual hardware frequency; see [CPUFreq documentation](https://docs.kernel.org/admin-guide/pm/cpufreq.html). BIOS/software sessions warn about target deviations in initial and under-load sysfs reports but never promote those readings into physical-clock certification. Temperature snapshots cannot exclude transient throttling between samples.

## Recommended future study design — not executed

Agree on a protocol before running a formal schedule:

1. Compare Classical Ziggurat and unrefined/refined Trapezoid at documented matching N/H/T settings. Keep accuracy evaluation separate from throughput; do not modify algorithms based on timing results.
2. Pin to CPU7, keep SMT sibling15 free of avoidable work, and recheck topology/affinity after reboot. Taskset is placement, not exclusive CPU reservation.
3. Use one explicitly documented frequency mode/boost condition per comparison block. Prefer a manually verified 3.2 GHz condition if reliable effective-frequency instrumentation becomes available; otherwise label the study as requested-P-state control rather than fixed-clock control.
4. Predefine warm-up policy, thermal settling criteria, sample count, exclusions and run-order seed. Alternate or randomize algorithm order within paired blocks so drift is not confounded with algorithm identity. Do not silently reuse the grouped order of the existing YAML as a randomized design.
5. Retain GCC11.4 O2, exact flags, binary SHA256, Git commit/local diff, Python packages, PRNG/uniform mode and seed. Do not mix PCG32/xoshiro or inline/precomputed modes without explicit comparison blocks. No fast-math/native changes are implicit.
6. Choose counts/repetitions through a separately approved pilot that achieves adequate timer resolution without thermal drift dominating. The existing three repeats are an environment profile, not an established power/sample-size analysis. Retain all per-run data, report paired effects and uncertainty; use confidence intervals across timing replications/blocks rather than pretending individual Gaussian samples are independent timing experiments. Predefine interval method (for example paired-block bootstrap) and disclose autocorrelation/order effects.
7. Report sampling throughput and elapsed time independently from full-process wall time. C CLOCK_MONOTONIC includes scheduling delays; initialization and warm-up are outside sampling timing, while checksum/moment accumulation is inside. File output includes memory writes inside timed chunks, while fwrite happens outside them. Do not pool output/no-output timings.
8. If a reviewed perf collector is later available, collect task-scoped hardware core cycles, instructions, branches/branch misses and relevant cache events with event availability, privilege scope, counter multiplexing/time-running and PMU limitations recorded. Divide by the matching measured sample count only when the counters cover that same sampling region. Whole-process perf includes startup, initialization, optional warm-up, logging and teardown; its cycles/sample are not sampling-loop-only metrics. Cache event meanings are CPU-specific; generic cache-misses need not represent every cache level.
9. TSC ticks measure a reference-time domain and are not interchangeable with dynamic core cycles. APERF/MPERF deltas need documented CPU-specific reference calibration and active/idle interpretation; instructions/sample reflects executed work, not wall time. Never infer actual cycles by multiplying wall time by an unverified nominal 3.2 GHz. perf instrumentation can add overhead and counters may multiplex. See [perf stat documentation](https://man7.org/linux/man-pages/man1/perf-stat.1.html).

## Tests performed and remaining approval gates

```bash
.venv/bin/python -B -m unittest discover -s experiments/tests -p test_benchmark_session.py -v
```

16 focused tests pass: fixture planning/application/readback, both SMT policies, original userspace setpoint, partial apply rollback, partial restoration reporting, journal validation/recovery, supervisor finally on failure/interruption, BIOS warning semantics, software authorization refusal, harmless child affinity/exit status, inherited lock descriptor, legacy helper compatibility, overlap rejection and SIGINT/SIGTERM handling. All sysfs control writes in tests target temporary fixtures; administrative guards and runuser execution are mocked for supervisor tests. There was **no real hardware restoration test**, no root deployment test and no end-to-end privileged runuser/descriptor test. The real non-root inherited-descriptor path was tested. Tests reserve only temporary session directories.

Live approved deployment/control/readback/restoration on the workstation, optional boost disabling, any effective-frequency instrumentation installation/access, and manual BIOS preparation remain future steps. The infrastructure is ready for review and read-only use. The workstation is not yet certified as a physically fixed-frequency benchmark environment.


## Current isolation workflow

Read-only planning, without executing the YAML schedule:

```bash
.venv/bin/python -B experiments/tools/isolation_manager.py inspect
.venv/bin/python -B experiments/tools/isolation_manager.py plan
.venv/bin/python -B experiments/tools/benchmark_session.py --isolation plan
```

Use the single approved `isolation_manager.py activate` wrapper documented in CPU_ISOLATION_AND_MONITORING.md; it starts the existing controller in BIOS/read-only mode, verifies the housekeeping hierarchy, waits for monitor readiness, then launches the supplied argv in a distinct CPU7 transient service. CPU15 is excluded from ordinary workloads, but kernel/IRQ activity is not disabled. Follow its verify/status/deactivate/recover commands and check both final quality and restoration records. Lightweight /proc monitoring alone cannot produce PASS. Diagnostic scheduler tracing requires separate explicit authorization and reliable loss/coverage accounting.

The current restricted session cannot access the system bus or tracefs and cannot account for namespace-hidden root tasks, so its isolation plan is blocked. Runtime-property/affinity restoration remains fixture-tested only; administrator conflicts are reported rather than overwritten. No isolation, CPU-frequency change, new RNG smoke test or formal benchmark was activated during this extension.

## Live readiness gate — 2026-10-19

The latest review remains **NO-GO for live activation in this restricted session**.
See [CPU_ISOLATION_AND_MONITORING.md](CPU_ISOLATION_AND_MONITORING.md#live-readiness-review-and-first-hardware-test--2026-10-19)
for captured read-only evidence, blocker classifications, the exact proposed 25-second
harmless test command, acceptance criteria and manual recovery commands.
`CPU_ISOLATION_READINESS.json` records the actual observation; it is not a successful
isolation report. Historical CPU7/15 kernel TIDs are not visible here, so their names
and execution intervals remain unverified. Aggregate CPU/interrupt activity was
observed on both CPUs; affinity/last-CPU fields do not attribute that activity.

Before any activation: repeat `isolation_readiness.py --interval 2` from an authorized
unrestricted host terminal, review the manager plan, verify root/userspace/cgroup
coverage and the recovery terminal, and obtain explicit approval for reviewed
root-owned deployment and the harmless test. Optional scheduler tracing needs its
own separate approval. Nothing in this task authorizes isolation now.

The existing manager/controller architecture is preserved. New safeguards include
kernel-effective-cpuset precedence, descendant starvation checks, bounded metadata
and report subprocesses, broker heartbeat/timeouts, unexpected-monitor-exit handling,
and an optional `--session-timeout 60` for the proposed test. The service also receives
`RuntimeMaxSec=60`, startup 15 and stop 5 second limits; the harmless workload has its own
30-second timeout and two-second kill grace. No frequency helper is invoked.

A successful future first test requires correct placement, initial monitoring before
execution, bounded completion, verified owned-unit shutdown and verified semantic
restoration. Lightweight scheduling quality remains UNVERIFIED without continuous
trace evidence. Root kernel threads, IRQs, SMT, shared caches/memory, firmware, power
and thermal coupling remain outside managed-workload isolation. Do not infer formal
benchmark readiness from test exit status alone. No live isolation or RNG experiment
was run in this readiness task.
