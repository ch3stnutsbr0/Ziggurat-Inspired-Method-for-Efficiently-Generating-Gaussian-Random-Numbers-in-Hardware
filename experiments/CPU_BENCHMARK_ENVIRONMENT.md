# GRNG CPU benchmark environment

Inspection and one execution smoke test: 2026-10-19 UTC. No formal schedule, repeated RNG timings or parameter sweep was executed. Governor, frequency limits, boost, SMT, IRQs, kernel and system settings were left unchanged. No packages were installed; no sudo or other privilege escalation was attempted.

## Machine and topology

AMD Ryzen 7 2700X Eight-Core Processor, x86_64, one socket, eight physical cores, two SMT threads per core, 16 online logical CPUs. One NUMA node (node 0), containing CPUs 0–15. Initial shell/process allowed affinity: 0–15. The tables below were read from lscpu and sysfs, not inferred from adjacent CPU numbers.

| Physical core | Logical CPUs / SMT pair | Socket | NUMA node | Shared L3 group |
|---|---|---|---|---|
| 0 | 0, 8 | 0 | 0 | 0–3, 8–11 |
| 1 | 1, 9 | 0 | 0 | 0–3, 8–11 |
| 2 | 2, 10 | 0 | 0 | 0–3, 8–11 |
| 3 | 3, 11 | 0 | 0 | 0–3, 8–11 |
| 4 | 4, 12 | 0 | 0 | 4–7, 12–15 |
| 5 | 5, 13 | 0 | 0 | 4–7, 12–15 |
| 6 | 6, 14 | 0 | 0 | 4–7, 12–15 |
| 7 | 7, 15 | 0 | 0 | 4–7, 12–15 |

Each SMT pair shares 32 KiB L1 data, 64 KiB L1 instruction and 512 KiB unified L2. Each four-core group shares 8 MiB unified L3. Aggregate: 256 KiB L1d, 512 KiB L1i, 4 MiB L2, 16 MiB L3. All cores have the same reported hierarchy.

**Selected CPU: 7**, physical core 7, SMT sibling 15, socket/node 0. A one-second /proc/stat delta showed 0% busy on both 7 and 15; CPU0 was 6% busy. This was a transient selection aid, not a reservation or a claim of permanent idleness. CPU7 is online and within inherited affinity. Pin avoidable concurrent user workloads away from both 7 and 15 where practical; taskset alone does not reserve either CPU. Other tasks, interrupts and the SMT sibling can still interfere. Shared L3, memory bandwidth and package power remain shared with other cores.

## Frequency, temperature and software

Driver: `acpi-cpufreq`. All 16 policies, policy0–policy15, have one matching logical CPU in affected_cpus and related_cpus. All use `schedutil`; available governors on every policy: `conservative ondemand userspace powersave performance schedutil`. CPUFreq boost reports `1` (enabled). Every policy reports min/max hardware and scaling limits 2,200,000 / 3,700,000 kHz. These limits are not a measured fixed clock or a boost ceiling.

`schedutil` uses scheduler utilization to adjust frequency, so load transitions can affect short runs. `performance` requests the highest frequency allowed by policy and can reduce governor ramp-up variability. It does **not** lock hardware frequency: boost, thermal constraints, firmware and package power still matter. `scaling_cur_freq` is not guaranteed to equal the instantaneous hardware clock. See [Linux CPUFreq documentation](https://docs.kernel.org/admin-guide/pm/cpufreq.html).

`cpupower` was not found in PATH; sysfs provides the inspection data without installing it. `cpuinfo_cur_freq` reads are permission denied in this session; no privileged reads were attempted. Some `scaling_cur_freq` snapshots are below nominal minimum; treat the interface as a report, not proof of hardware frequency or changed limits.

Temperature sensors are available through hwmon. Initial k10temp readings: Tctl 52.375°C and Tdie 42.375°C; these vary (later inspection was warmer). hwmon also exposes NVMe, AMD GPU and nouveau readings. Record sensor labels, not just hwmon numbers, because numbering can change after reboot. The helper captures before/after temperatures; it does not monitor peak temperature or effective frequency during sampling.

Linux Mint 21.3; kernel 5.15.0-198-generic; GCC 11.4.0; Python 3.10.12; RAM approximately 62 GiB. Existing benchmark build: GCC O2. Exact Makefile flags:

```text
-std=c11 -Wall -Wextra -pedantic -O2
-DBENCHMARK_OPTIMIZATION='"O2"'
-DBENCHMARK_CFLAGS='"-std=c11 -Wall -Wextra -pedantic -O2"'
-o benchmark -lm
```

All Makefile SOURCES are linked. No `-march=native`, `-ffast-math`, compiler or timing changes were introduced. The helper records binary SHA256; Makefile flags describe the current build procedure, not an independent binary attestation.

## Launcher and metadata

New helper: `experiments/tools/cpu_benchmark.py`. Python standard library plus existing `taskset`; no extra packages. Its default CPU7 is configurable with `--cpu`. It checks inherited affinity and online status and executes an argv array, never a shell string. It forwards INT/TERM/HUP to the child's process group and preserves normal exit codes; signal exits use shell convention 128+signal. No governor option is enabled or implemented in this launcher.

Every invocation reserves a UTC timestamp + UUID directory with exclusive mkdir/file creation:

```text
experiments/results/linux_ryzen2700x/sessions/<UTC>-<UUID>/
├── before.json
├── stdout.txt
├── stderr.txt
└── session.json
```

Sessions live in the already ignored Linux results subtree. The raw/processed/figure layout, historical directories and scheduler are untouched. Metadata includes command argv/cwd, selected core and SMT sibling, inherited affinity, kernel/OS/CPU inventory, compiler, Python and package versions, tracked Git diff/status/commit, command executable hash, before/after per-policy governor/limits/frequency, boost, thermal readings, load and proc/stat counters, and exit status. Untracked files appear in Git status but their content is not archived; retain source changes with your research records. If wrapping Python orchestration rather than the binary directly, the executable hash is the interpreter; the runner separately records the C binary hash.

Captures and file writes occur before/after child execution and do not add instrumentation inside the C timed loop. Metadata capture can itself affect cache/thermal state before launch, and before/after readings are not continuous monitoring. The helper records command output in logs rather than displaying it live. It rejects `--overwrite`, but cannot sandbox arbitrary supplied commands: choose fresh output paths and avoid commands that replace files. The selected task may change its own affinity; GRNG currently does not. All descendants inherit the mask unless they change it explicitly.

Example, from the repository root:

```bash
.venv/bin/python -B experiments/tools/cpu_benchmark.py --cpu 7 -- \
  ./c/benchmark --algorithm basic --layers 8 --seed 1 --samples 100000
```

That is the **only RNG invocation performed in this task**. It completed with status 0, PCG32 (current default), inline uniforms, N=8, seed=1, exactly 100,000 samples, complete=true and buffer_exhausted=false. No sample-output option was supplied and no binary sample files were produced. No warm-up was added. Throughput is retained only in its log and is not evidence of comparative performance or accuracy.

Additional launcher checks used a trivial Python process, not the RNG: observed child affinity `[7]`, propagated exit code 13, unique session paths, and invalid CPU999 rejection before directory creation.

## Timing and harness review

- C uses `clock_gettime(CLOCK_MONOTONIC)` elapsed wall time; scheduling delays count.
- Initialization/table construction and optional uniform-buffer generation are outside sampling timing.
- Inline performance loop includes RNG generation, volatile checksum, sum and squared-sum accumulation; it is not a pure RNG-only timer.
- With binary output, buffer writes are timed, while byte conversion and fwrite occur between timed chunks. Python subprocess wall time includes initialization and I/O. Keep these metrics separate.
- `--warmup N` already exists. Warm-up occurs outside timing and resets the PRNG/algorithm to the requested seed afterward. The generic Linux YAML does not expose warm-up and runner.build_runs adds no warm-up flag. Do not silently add one or mix profiles with different warm-up policies.
- Runner repetitions use fresh sequential subprocesses, so generator state is reinitialized. Repetitions with seed1 repeat the same random stream; they are not independent statistical datasets. The generic schedule groups repeats by configuration rather than interleaving/randomizing them, leaving ordering/thermal drift as a formal-study limitation.
- YAML controls sample count, seed, PRNG, uniform mode and repetition count. It is unchanged and was not executed.
- No C or generic-runner affinity setting exists; taskset around the launcher/scheduler provides inherited affinity without scheduler edits. Wrapping an entire future schedule also pins its Python analysis/provenance work, which can affect cache and thermal state between runs.
- Standard C result config and report-json record optimization level; PRNG profiling additionally records compiler version, flags and architecture. Normal raw records do not comprehensively identify CPU model/governor/affinity/temperature. Runner provenance adds binary hash, build identity, YAML and Python version. Retain the new session metadata alongside those records.

## Optional temporary performance governor — manual, approval required

**Not enabled, not executed, and not authorized by this setup task.** The restricted session has no usable administrative path; no escalation was attempted. Continue with schedutil if privilege or explicit approval is unavailable. After explicit approval, a user with an existing normal administrative terminal can save the following as a temporary Bash script and review it before use. It snapshots *every* policy before any change, records recovery data on disk, switches only the governor, runs the supplied command as the named unprivileged benchmark user, and attempts every restoration on failure or INT/TERM/HUP.

```bash
#!/usr/bin/env bash
# Manual administrative terminal only, after explicit approval.
set -euo pipefail
[[ ${GRNG_GOVERNOR_CHANGE_APPROVED:-} == yes ]] || exit 2
[[ $EUID -eq 0 ]] || { echo 'Administrative terminal required' >&2; exit 2; }
bench_user=$1; shift
[[ $bench_user != root && $# -gt 0 ]] || exit 2
policies=(/sys/devices/system/cpu/cpufreq/policy*)
[[ -d ${policies[0]} ]] || exit 2
state_dir=$(mktemp -d /tmp/grng-governors.XXXXXXXX)
declare -a original
for i in "${!policies[@]}"; do
    original[$i]=$(cat "${policies[$i]}/scaling_governor")
    printf '%s\t%s\n' "${policies[$i]}" "${original[$i]}" >> "$state_dir/original.tsv"
    grep -qw performance "${policies[$i]}/scaling_available_governors"
done
child_pid=
restore() {
    rc=$?
    trap - EXIT
    trap '' INT TERM HUP
    if [[ -n $child_pid ]]; then
        # runuser forwards TERM to its command; wait before restoring policy.
        kill -TERM "$child_pid" 2>/dev/null || true
        wait "$child_pid" 2>/dev/null || true
    fi
    failed=0
    for i in "${!policies[@]}"; do
        if ! printf '%s\n' "${original[$i]}" > "${policies[$i]}/scaling_governor"; then
            echo "RESTORE FAILED: ${policies[$i]} -> ${original[$i]}" >&2
            failed=1
        fi
    done
    echo "Recovery record retained: $state_dir/original.tsv" >&2
    if (( failed && rc == 0 )); then rc=1; fi
    exit "$rc"
}
trap restore EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
for policy in "${policies[@]}"; do
    printf 'performance\n' > "$policy/scaling_governor"
    [[ $(cat "$policy/scaling_governor") == performance ]]
done
runuser -u "$bench_user" -- "$@" &
child_pid=$!
wait "$child_pid"
child_pid=
```

Do not run the benchmark itself as root. Supply the project venv interpreter, affinity helper and benchmark command as separate arguments to the reviewed script, from the repository root. The approval environment flag alone does not constitute approval; obtain permission first. No sudo invocation is provided or required by the launcher. This manual recipe has not been tested against live governors. EXIT traps cannot handle SIGKILL, machine failure or power loss: use original.tsv for manual restoration in an administrative terminal if necessary. Recheck every policy afterward; concurrent power-management services can change governors independently. No reboot persistence, boost, frequency limits, voltages or BIOS changes are involved.

## Formal protocol and variance

Before formal measurements, recheck topology, CPU online status, inherited affinity, sibling load, temperature, policies and boost. Prefer a consistent, explicitly approved temporary performance-governor session; otherwise document schedutil as a separate environment condition. Do not compare runs across mixed governor/boost/build settings as if equivalent. Keep avoidable workloads away from both threads of the chosen core, and avoid running setup/compilation during measurements.

Agree in advance on warm-up, count, repetitions, run ordering, thermal settling, and reporting of distributions/outliers; retain raw timings and disclose exclusions. Do not infer fixed frequency from governor choice or use this one short run to select a statistically representative count. Interleaving algorithms and recording effective clocks/peak temperatures are possible future methodology improvements requiring a separate study decision, not implemented here. Preserve PRNG/seed and distinguish timing repeats from independent accuracy validation. Accuracy testing and performance measurement answer different questions.

Remaining variance: SMT contention, preemption, interrupts, shared caches/memory, background daemons, migration of other tasks, boost/power/thermal behavior, frequency-transition latency, cold versus warm caches and pages, process startup, timer overhead, ordering and ambient temperature. Affinity controls placement, not exclusivity. The workstation is ready to launch pinned experiments; formal reproducibility still requires an agreed protocol, session-state checks and (if desired) approval for temporary governor control.

## Reinspect after reboot

```bash
lscpu
lscpu -e=CPU,CORE,SOCKET,NODE,ONLINE
lscpu -C
taskset -pc $$
cat /sys/devices/system/cpu/online
for cpu in /sys/devices/system/cpu/cpu[0-9]*; do
    echo "$cpu"
    cat "$cpu/topology/core_id" "$cpu/topology/thread_siblings_list"
done
for policy in /sys/devices/system/cpu/cpufreq/policy*; do
    echo "$policy"
    cat "$policy/affected_cpus" "$policy/scaling_driver" \
        "$policy/scaling_governor" "$policy/scaling_available_governors" \
        "$policy/scaling_min_freq" "$policy/scaling_max_freq" "$policy/scaling_cur_freq"
done
cat /sys/devices/system/cpu/cpufreq/boost
command -v cpupower || true
for sensor in /sys/class/hwmon/hwmon*; do
    cat "$sensor/name"
    for file in "$sensor"/temp*_label "$sensor"/temp*_input; do
        test ! -r "$file" || { echo "$file"; cat "$file"; }
    done
done
uname -r
gcc --version
.venv/bin/python --version
# Optional existing tool, read-only one-second utilization snapshot:
command -v mpstat >/dev/null && mpstat -P ALL 1 1
# Direct affinity syntax (do not repeat the smoke test as part of inspection):
# taskset -c 7 ./c/benchmark <explicit approved benchmark arguments>
```

## Initial policy and utilization snapshot

All frequencies below are reported scaling_cur_freq in kHz, read sequentially and not during sampling. Policy i affects CPU i; governor is schedutil, driver acpi-cpufreq, limits 2,200,000–3,700,000 kHz for all rows.

| CPU / policy | Current frequency (kHz) | One-second busy (%) |
|---|---:|---:|
| 0 | 2040415 | 6.0 |
| 1 | 2199152 | 3.0 |
| 2 | 2049965 | 2.97 |
| 3 | 2200976 | 10.64 |
| 4 | 2057097 | 5.05 |
| 5 | 1890139 | 1.0 |
| 6 | 2055865 | 0.0 |
| 7 | 1893940 | 0.0 |
| 8 | 1919685 | 0.0 |
| 9 | 1892014 | 0.99 |
| 10 | 2132025 | 1.0 |
| 11 | 2198046 | 6.8 |
| 12 | 2197408 | 0.0 |
| 13 | 2021097 | 0.0 |
| 14 | 2005220 | 1.0 |
| 15 | 1892286 | 0.0 |

Smoke-test evidence: `experiments/results/linux_ryzen2700x/sessions/20261019T173137Z-6d2b7ae9ab7b45fdb63d85d6458d29c4/session.json` and adjacent stdout/stderr. This ignored generated evidence is kept locally.

## Session-controller extension (2026-10-19)

The original `tools/cpu_benchmark.py` CLI and its output format remain supported. Affinity validation/argv and the cooperative session lock are now shared with `tools/benchmark_session.py`; snapshots additionally include exposed thermal limits/alarms. Use [BENCHMARK_SESSION_PROTOCOL.md](BENCHMARK_SESSION_PROTOCOL.md) for baseline, requested-P-state software and manual-BIOS modes, telemetry limitations, explicit approval/deployment commands and journal recovery. It supersedes the earlier example governor shell recipe for new sessions. The optional `tools/frequency_control.py` source must never be elevated from this user-writable checkout; approved live control requires a reviewed root-owned deployment and isolated Python invocation.

Software planning confirms the advertised 3.2 GHz state and userspace governor but cannot test live acceptance without separate approval. The controller conservatively includes all 16 policies because single-logical-CPU policy masks do not prove physical core/domain independence; CPU7/15 are SMT siblings. No frequency, governor, limits or boost changes have occurred. BIOS mode is read-only and assumes manual firmware preparation; see [BIOS_FIXED_FREQUENCY_GUIDE.md](BIOS_FIXED_FREQUENCY_GUIDE.md).

`sensors` is present; perf/cpupower/turbostat executables are absent. Kernel MSR PMU APERF/MPERF/TSC event descriptions are exposed, but access/calibration are unverified; perf_event_paranoid is 4 and cpuinfo_cur_freq remains permission denied. Effective physical frequency is explicitly unavailable, never inferred from nominal P-state. No collector or permission changes were installed. This extension ran only unit tests, harmless subprocesses and read-only planning; no additional RNG smoke test or formal schedule was run. Privileged control/restoration remains fixture-tested only.
