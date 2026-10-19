> Current readiness review (2026-10-19): **NO-GO for activation from this session.**
> See “Live readiness review and first hardware test” below. No privileged activation,
> RNG workload, tracing enablement or frequency change was performed.

# Session CPU isolation and environmental monitoring

This is the current GRNG Linux-side workflow. **Frequency management is out of scope.** The user will manually configure BIOS frequency, provisionally 3.2 GHz across all cores. Every frequency, governor, limit and boost interface in this workflow is read-only. The old frequency-control tool is retained for compatibility, never invoked by isolation activation.

No privileged isolation, trace instance, CPU-setting change, package installation, RNG invocation, formal schedule, commit or push was performed during implementation. Privileged execution and actual hardware restoration remain untested; unit tests use temporary fixtures/mocks and harmless Python subprocesses.

## Observed workstation and cgroup hierarchy

Read-only inspection on 2026-10-19:

- Ryzen 7 2700X, 8 cores/16 logical CPUs; logical CPUs7/15 share physical core7/socket0. Online CPUs0–15; housekeeping CPUs0–6,8–14. Both sibling mappings and physical package/core IDs are checked before activation.
- Mint21.3, kernel5.15.0-198-generic, systemd249.11; cgroup2fs mounted at `/sys/fs/cgroup`.
- Root controllers include cpuset/cpu/io/memory/hugetlb/pids/rdma/misc, but root subtree_control contains only memory and pids. Non-root cgroups currently expose no cpuset effective/partition files.
- Top-level groups: system.slice, user.slice, init.scope, and dev-hugepages.mount, dev-mqueue.mount, proc-sys-fs-binfmt_misc.mount, sys-fs-fuse-connections.mount, sys-kernel-config.mount, sys-kernel-debug.mount and sys-kernel-tracing.mount.
- The current process is below user.slice/user-1001.slice/user@1001.service/app.slice/.../vte-spawn-....scope.
- System-bus access is denied in this execution environment. Root cgroup.procs includes namespace-hidden zero PIDs, preventing complete task accounting. Tracefs access is denied. **The current plan is blocked**, not an assertion that isolation is active or verified. Reinspect from a normal administrative terminal after approval.

The kernel5.15 documentation describes partition states root/member, not the newer isolated partition state. The root partition interface is not expected on the root cgroup; its absence alone does not diagnose kernel support. There is no verified delegated hierarchy supporting safe isolated-partition creation here. This manager therefore does not write cpuset.cpus.partition or any systemd-owned cgroup file. [Kernel5.15 cgroup-v2 documentation](https://docs.kernel.org/5.15/admin-guide/cgroup-v2.html)

## Strategy and its limits

Activation uses supported `systemctl set-property --runtime UNIT AllowedCPUs=...` calls. It constrains every recognized top-level ordinary unit, including system.slice/user.slice/init.scope and root mount groups, to its original effective mask intersected with housekeeping. A group with an empty intersection causes a preflight refusal; essential services are never assigned an empty mask. Unknown/unmanaged root groups, incomplete topology/accounting or administrator changes cause refusal. Any new root group during the workload fails periodic verification and aborts the workload.

A unique root-level grng<UUID>.slice is assigned CPU7. The actual benchmark runs as the named non-root user in a transient service below that slice, with AllowedCPUs=7 and CPUAffinity=7, Restart=no, KillMode=control-group and a five-second stop timeout. A worker checks its real effective cpuset, process affinity and cgroup identity before exec'ing the unchanged benchmark argv via the shared taskset helper. No benchmark user process is assigned CPU15. Ordinary userspace is kept off both siblings as far as the verified hierarchy permits.

AllowedCPUs alone is not exclusivity. It is constrained by ancestors, so the manager reads actual cpuset.cpus.effective after applying properties and continuously rechecks it. `systemd-run` creates the benchmark service as a sibling of the restricted ordinary groups: the housekeeping-bound controller cannot escape its own inherited cpuset merely by calling taskset. The supervisor mediates exactly one approved argv over a descriptor-passing socket; the controller starts monitoring before that request. No caller-controlled privileged operation is accepted through the socket. [systemd249 resource-control documentation](https://www.freedesktop.org/software/systemd/man/249/systemd.resource-control.html)

Root-cgroup kernel threads, per-CPU kernel work and hardware interrupts remain outside the userspace constraints. Root userspace tasks that can use CPU7/15 cause a preflight block; their affinities are not silently changed. CPU15 cannot be guaranteed permanently idle because kernel activity can still run there. SMT, shared L3, memory bandwidth, package power, firmware and thermal coupling remain. No IRQ affinity, SMT, boot argument, GRUB, governor, frequency, voltage, BIOS or persistent service setting is changed.

## Components and privilege boundary

- `tools/isolation_manager.py`: standalone stdlib administrative supervisor and read-only inspect/plan/status/verify CLI; also supplies unprivileged broker/placement-worker commands.
- `tools/benchmark_session.py`: existing session controller, extended with `--isolation plan|active`, monitoring modes and quality limits. Original modes/CLI remain supported. Active isolation requires BIOS/read-only mode and a supervisor-provided broker; it cannot activate itself or call sudo.
- `tools/interference_monitor.py`: housekeeping-only observer, /proc counters, scheduler parser, quality rules and final trace-loss accounting.
- `tools/cpu_benchmark.py`: existing shared topology/affinity validation, taskset argv and coordination lock. No duplicate independent affinity launcher was added.

The supervisor runs from a reviewed root-owned non-writable deployment using isolated Python. It never imports checkout modules while privileged. The controller, benchmark worker and quality finalizer run as the benchmark user. All workspace writes are made as that user; the root supervisor writes only its private journal and supported systemd/own-trace-instance interfaces. It never executes shell strings. Socket requests carry the exact approved command array and pre-opened stdout/stderr descriptors, not arbitrary privileged API requests.

## Read-only commands — safe now

From the repository root:

```bash
.venv/bin/python -B experiments/tools/isolation_manager.py inspect
.venv/bin/python -B experiments/tools/isolation_manager.py plan
.venv/bin/python -B experiments/tools/isolation_manager.py verify
.venv/bin/python -B experiments/tools/isolation_manager.py status
# Equivalent plan through the existing controller:
.venv/bin/python -B experiments/tools/benchmark_session.py --isolation plan
```

JSON status fields, not a read-only command's shell exit code, state whether a plan/verification is valid. A blocked plan is useful diagnostic output and launches nothing. Read-only commands neither prepare cgroups nor enable cpuset/tracefs. Private journal status requires administrative read access; unavailable visibility is not reported as proof of no active sessions.

## Future deployment and one-command activation — explicit approval required

**None of the following administrative commands was executed during setup.** No sudo is requested or called. After explicit deployment/isolation approval, use an existing normal administrative terminal outside this restricted session. Review source first; do not elevate the user-writable checkout script. No packages are required.

As the benchmark user, prepare the existing ignored session directory and coordination file:

```bash
mkdir -p experiments/results/linux_ryzen2700x/sessions
touch experiments/results/linux_ryzen2700x/sessions/.controller.lock
```

In the administrative terminal, after approval:

```bash
install -d -o root -g root -m 0755 /usr/local/lib/grng-benchmark
install -o root -g root -m 0644 \
  /home/newuser/projects/Ziggurat-Inspired-Method-for-Efficiently-Generating-Gaussian-Random-Numbers-in-Hardware/experiments/tools/isolation_manager.py \
  /usr/local/lib/grng-benchmark/isolation_manager.py
```

Re-run inspect and plan from that terminal. If the plan has no errors, the following **future execution example** wraps the entire lifecycle; it is not permission to run it now:

```bash
cd /home/newuser/projects/Ziggurat-Inspired-Method-for-Efficiently-Generating-Gaussian-Random-Numbers-in-Hardware
/usr/bin/python3 -I /usr/local/lib/grng-benchmark/isolation_manager.py activate \
  --approve-isolation --user newuser \
  --controller "$PWD/experiments/tools/benchmark_session.py" \
  --python "$PWD/.venv/bin/python" \
  --session-root "$PWD/experiments/results/linux_ryzen2700x/sessions" \
  --monitor-mode lightweight --interval 1 -- \
  ./c/benchmark --algorithm basic --layers 8 --seed 1 --samples 100000
```

This snapshots state, takes locks, applies temporary constraints, verifies them, runs the unprivileged controller/monitor and exactly the supplied foreground workload, tears down owned units, restores properties, audits affinities, and records results. The benchmark is not run as root. The small worker's Python startup/placement checks are outside C timing but may affect pre-run cache/thermal state; use the same wrapper for every algorithm comparison. Warm-up/seed/PRNG/sample count are unchanged unless explicitly supplied as benchmark arguments. The YAML schedule is never automatically launched. Foreground workloads must not daemonize, escape their unit or manually alter the environment.

For diagnostic mode, replace `--monitor-mode lightweight` with `--monitor-mode diagnostic --approve-scheduler-tracing`, **only after separate explicit approval for private scheduler tracing**. No perf installation, perf_event_paranoid change, module loading or tracing-permission alteration is attempted. If private trace setup/configuration verification fails, the workload is not launched and restoration is attempted. Calling an unprivileged ordinary session with diagnostic mode but no approved trace descriptor records a clearly labelled /proc fallback; it cannot certify clean scheduling.

The controller may also wrap an explicitly approved experiment harness argv later without changing its scheduler. That includes the harness itself in CPU7's unit and changes environmental context relative to direct C invocation; document that choice. Do not execute the Linux YAML schedule during environment setup.

## Monitor contents and interference interpretation

One observer thread samples on housekeeping CPUs only. It verifies affinity and completes an initial observation before signalling readiness; only then can the controller launch its benchmark/proxy. Legacy cpu_telemetry.csv rows are generated from that same snapshot, avoiding a second frequency-polling thread.

Lightweight mode (default one-second interval, minimum0.2 seconds) records:

- Monotonic timestamps, selected CPU, controller/observer placement, per-CPU utilization from /proc/stat, global ctxt deltas, per-CPU7/15 interrupt and softirq deltas.
- Visible task PID/TID/name/state, last scheduled CPU and cumulative utime/stime tick deltas; benchmark placement/cgroup and migration observations.
- Read-only driver, governor, min/max, boost and reported scaling frequency; Tdie/Tctl and available thermal labels/limits/alarms via hwmon.
- hwmon temp*_input values are retained in their native millidegrees Celsius with sensor labels.
- Effective-frequency unavailable status, task-scan races/access errors, missed sample deadlines, trace-reader backlog/partial records and bounded-buffer losses.

A task's /proc stat CPU is its **last** CPU, not proof it is currently running there. Runnable snapshots or tick increases are possible-contamination warnings; tick differences may include time on another CPU. Short-lived tasks and interference between samples can be missed. Global context switches cannot be attributed to CPU7/15. Absence of sampled competitors never yields PASS. Normal interrupts within the wrapper window may precede/follow C's timed region; their deltas are conservative session observations, not exact timed-loop attribution.

Active isolation's cpu_telemetry.csv direct-child CPU can describe the housekeeping broker proxy. Use placement.json and interference records for the actual workload: the worker records its PID/start ticks, cgroup, effective mask and affinity before exec. Current unit thread IDs are cached, reused task IDs are checked where observable, and exit/reuse uncertainty is not presented as a clean certificate.

Diagnostic mode uses only the manager-created unique `/sys/kernel/tracing/instances/grng_<UUID>/` instance. It configures monotonic trace time, CPU mask8080 (CPUs7/15), sched_switch/sched_migrate_task and a256KiB per-CPU buffer, verifies readback, and passes a read-only trace_pipe descriptor to the unprivileged housekeeping observer. It does not change global tracing or IRQ affinity. Scheduler records and closed competing-task intervals are saved separately from RNG results. Migration events are captured on their emitting CPUs: events emitted only on housekeeping CPUs can be missed by the reserved-CPU mask; switch records/placement checks and conservative coverage requirements remain necessary.

Before/after per-CPU trace stats must explicitly contain zero overrun, commit-overrun and dropped-event counters. Missing fields, parser failures, read-budget exhaustion, incomplete interval/window coverage, or lost-event markers prevent reliable-loss-free certification. Intervals are clipped to the recorded observer window, not C's private timing boundaries; an idle CPU with no bracketing switches may remain UNVERIFIED. Diagnostic scheduling intervals are not hardware core cycles and do not measure IRQ execution time within a running task. Only unambiguous completed intervals are treated as observed durations; incomplete visibility remains uncertainty.

Raw diagnostic CSV can grow quickly. In-memory events/switches are capped at100,000 per collection; exceeding a cap or read budget is recorded and prevents a clean certificate, while CSV remains the raw record until I/O fails. Monitoring is not free: proc scans, sysfs/hwmon reads, JSON serialization and trace reads use shared cache/memory/package resources. sampling_work_ns measures scanner wall time, not causal benchmark slowdown. No numerical overhead claim or overhead calibration benchmark was made; assess overhead separately in a later approved pilot. Effective CPU frequency remains unavailable with current permissions/instrumentation; no nominal-P-state-to-clock inference is made.

## Files and quality classifications

All outputs remain below the existing ignored Linux session subtree, using an exclusive UUID directory:

```text
sessions/<UUID>/
  environment.json
  session.json
  journal.json
  cpu_telemetry.csv
  environment_samples.csv
  interference_events.csv
  placement.json                 active-isolation workload placement proof
  isolation_status.json          initial effective constraint verification
  benchmark_quality.json         observer's provisional result
  benchmark_quality_final.json   includes privileged trace-loss/restoration evidence
  restoration.json
  isolation_final.json           final privileged isolation journal copy
  stdout.txt
  stderr.txt
```

Startup failures can leave only the records that could safely be written; absence of a required final record means incomplete verification, never PASS. Root journals are independently fsynced under `/var/lib/grng-isolation/<UUID>.json`. `session.json` says pending_restoration until its supervisor finishes; final restoration/quality files are authoritative for the complete lifecycle. Workload exit status is preserved independently from environmental/restoration failure. A zero shell status is not sufficient evidence of a good research run.

Default quality limits (optional JSON via controller or supervisor `--quality-thresholds PATH`):

```json
{"max_competing_ns": 0, "max_irq_delta": 0, "max_frequency_variation_pct": 5.0}
```

Values must be finite, nonnegative and use only these keys or optional `max_tdie_c` (degrees Celsius). The thermal threshold is unset by default; no hardware-specific safe limit is invented. A configured Tdie excess is a WARNING, not a thermal-control action. Frequency variation is100×(max−min)/min for reported CPU7 frequencies, not effective-clock error. IRQ threshold counts the aggregate CPU7+15 interrupt delta, not service time. Competing threshold is traced, completed CPU15 non-idle execution or otherwise confirmed foreign execution. Out-of-allowlist CPU7 intervals without reliable membership evidence are recorded as unclassified durations and prevent PASS rather than being invented as confirmed competition; rapidly exiting legitimate descendants may remain unclassified. Sampled last-CPU/tick observations do not supply precise competing time.

- **FAIL:** monitor failure, effective-placement drift, benchmark migration, traced competing intervals above the limit, or failed final restoration.
- **WARNING:** sampled possible competitors, interrupt excess, read-only policy/boost changes, or reported-frequency variation above the limit; missing evidence is still listed.
- **UNVERIFIED:** no above-limit observation but incomplete isolation, visibility, bracketing/loss accounting or missed environmental sample deadlines. This is the expected best classification from snapshots alone.
- **PASS:** verified preconditions plus complete, sufficiently reliable/loss-accounted scheduler coverage and task visibility, within all configured limits, with no unresolved errors. It is limited environmental evidence, not proof of zero hardware interference, fixed frequency, RNG accuracy or algorithm superiority.

Priority is FAIL, then WARNING, then UNVERIFIED, then PASS; warning reports retain unresolved uncertainties. Threshold choices must be prespecified with the study, not relaxed after seeing results. Physical-frequency uncertainty is recorded separately from scheduling-quality scope.

## Restoration, conflicts and recovery

The root supervisor takes both a private global flock and the existing user workspace coordination lock before mutations. Its child inherits the locked descriptor, preventing overlapping cooperating sessions even if the supervisor unexpectedly disappears while the controller remains alive. Existing legacy frequency sessions use the same workspace lock but are not part of this workflow. Other administrators/services can still make changes independently; these cannot be globally prevented by an advisory lock.

Before modifying any resource property, the durable journal records all original AllowedCPUs/effective masks, configuration-file hashes/provenance, known userspace thread affinities/cgroup paths/start identities, root-task information and the supervisor's own original affinity. Userspace threads explicitly pinned exclusively to reserved CPUs cause refusal instead of silent widening. Kernel-thread affinities are never written. The supervisor changes only its own affinity to housekeeping and restores it on exit.

Each property has intent/applied/restoration phases fsynced around API operations. Restoration compares the current value and configuration provenance against the session's verified expected state. If another administrator changes a property or adds/edits related drop-ins, that unit is not overwritten. Restoration can proceed for unaffected units but reports a conflict. An interrupted API call without verified resulting provenance requires manual review rather than a guessed rollback. PID/TID start identities prevent treating reused IDs as original tasks.

Original resource-control values are restored via the supported systemd API and checked. Known surviving userspace affinities/cgroup paths are audited afterward. If a kernel update of the cpuset or an external administrator leaves a thread affinity different from its original value, the tool does **not** blindly write an ambiguous per-thread affinity: restoration is marked unverified/conflicted for review. New tasks have no original snapshot; their requested affinity is not invented. This conservative audit is intentionally stricter than merely resetting top-level masks and must be tested on the real kernel after approval.

Generated runtime property drop-ins/controller enablement may remain in `/run` after semantic restoration. This is explicitly reported by runtime_override_residue_possible; the tool does not erase broad administrator-owned runtime configuration with systemctl revert. No /etc configuration or boot-persistent state is installed by activation. If exact runtime-file cleanup is required, review the journal/provenance and plan a separate selective administrative cleanup; do not delete unrelated overrides. This implementation certifies original resource-property semantics when verified, not byte-for-byte absence of all runtime bookkeeping.

Ctrl+C/TERM/HUP are handled; monitor/benchmark failure terminates the owned workload and triggers teardown/restoration. The owned service uses control-group termination. Private trace instance configuration and owned-unit identity are checked before cleanup; conflicting changes are preserved and reported. A systemd failure, inability to stop the workload, partial apply or partial restore prevents a false restoration-success result. Every unfinished root journal blocks a new activation.

After SIGKILL, power loss or a crash, automatic restoration is **not guaranteed**. Runtime settings may outlive the process; a reboot normally clears runtime overrides, but always reinspect actual state rather than assuming that occurred. Never replay a stale journal onto changed hardware, rebooted processes or unrelated unit identities without reviewing it.

Read-only status/verification from the approved installed tool in a normal administrative terminal:

```bash
/usr/bin/python3 -I /usr/local/lib/grng-benchmark/isolation_manager.py status --journal SESSION_UUID
/usr/bin/python3 -I /usr/local/lib/grng-benchmark/isolation_manager.py verify --journal SESSION_UUID
```

For an active session, approved deactivation requests TERM from the identity-checked supervisor; normal teardown/restoration happens there. Check status afterward:

```bash
/usr/bin/python3 -I /usr/local/lib/grng-benchmark/isolation_manager.py deactivate \
  --approve-isolation --journal SESSION_UUID
```

For an orphan, first inspect the private journal, process tree and owned units. Stop if PIDs/unit/trace identities or configuration no longer match. Do not kill an unrelated process just because a numeric PID was reused. Recovery refuses an existing recorded controller PID, competing locks, changed property provenance or unknown trace ownership. After explicit recovery approval:

```bash
cat /var/lib/grng-isolation/SESSION_UUID.json
ps -eo pid,ppid,pgid,lstart,args
/usr/bin/python3 -I /usr/local/lib/grng-benchmark/isolation_manager.py recover \
  --approve-isolation --journal SESSION_UUID
/usr/bin/python3 -I /usr/local/lib/grng-benchmark/isolation_manager.py status --journal SESSION_UUID
```

Recovery takes both locks before changing anything, stops only the recorded owned units, validates/cleans its private trace instance, restores unconflicted properties and audits known thread state. It never runs a benchmark or frequency helper. If restoration was interrupted between a write and durable provenance capture, manual conflict review may still be required. Recovery updates the private root journal rather than overwriting existing research/session reports.

Boot IDs are journaled. **No stale settings or PID signals are replayed across boots.** After a reboot/power loss, inspect the current hierarchy and manually confirm the new environment. The following explicitly acknowledges the stale ledger only; it does not restore old settings, stop units, or signal reused PIDs:

```bash
/usr/bin/python3 -I /usr/local/lib/grng-benchmark/isolation_manager.py recover \
  --approve-isolation --journal SESSION_UUID --acknowledge-new-boot
```

A reconciled-new-boot record is not a claim that old process state was restored. A new activation still performs fresh preflight. For a same-boot ambiguous API intent, after manually confirming there is no outstanding API operation and the unit exactly matches its original value and configuration provenance, recovery may be explicitly authorized with `--acknowledge-unchanged-original`. That option acknowledges only already-original state; any differing value/hash remains a conflict and is never overwritten by acknowledgment. Other unconflicted restoration steps may still run. Do not use acknowledgment to bypass unresolved administrator changes.


## Verification completed and next approval gates

Focused test commands (all non-invasive):

```bash
.venv/bin/python -B -m unittest discover -s experiments/tests -p test_cpu_isolation.py -v
.venv/bin/python -B -m unittest discover -s experiments/tests -p test_benchmark_session.py -v
```

Verified: 45 focused tests passed (29 isolation/monitoring tests plus 16 existing session-controller regressions). Tests use temporary cgroup/topology/configuration fixtures, fake systemd backends, mocked administrative orchestration, mocked scheduling events, and harmless Python processes. They cover blocked topology/controller/root visibility, empty housekeeping rejection, explicit affinity constraints, apply/readback/restore/recovery, external admin conflicts, interrupted provenance, effective-mask drift/new groups, descriptor arrays, monitor readiness/affinity/serialization, monitor failures, quality classes/loss uncertainty, legacy compatibility, overlap rejection and signal cleanup. Real privileged systemd activation, tracefs collection, real-hardware cpuset/affinity restoration and live end-to-end broker execution have **not** been tested. This sandbox also denies Python reconstruction of inherited sockets; cancellation therefore uses bounded direct-descriptor I/O, while the proxy path requires verification from the approved normal host environment. No permissions were bypassed or changed. No formal or smoke RNG workload ran in this task.

Next steps require explicit permission: reviewed root-owned tool deployment, reinspection from an unrestricted administrative terminal, a harmless live activation/restoration test, and separately optional private scheduler tracing. Firmware configuration remains manual. The restricted current plan remains blocked; do not bypass that result or describe the workstation as completely isolated.

## Live readiness review and first hardware test — 2026-10-19

Evidence: `CPU_ISOLATION_READINESS.json`, captured 2026-10-19 19:06:07 UTC.
This is a restricted-session observation, not an administrator's complete host inventory.
`tools/isolation_readiness.py` adds a repeatable **read-only** two-snapshot inspection;
it neither activates the manager nor enables tracing. Redirect future reports to new
paths, rather than replacing the captured evidence:

```bash
report=$(mktemp /tmp/grng-readiness-XXXXXXXX.json)
timeout 60s .venv/bin/python -B experiments/tools/isolation_readiness.py --interval 2 > "$report"
cat "$report"
```

Run the same read-only inspector in an unrestricted host terminal to obtain current
kernel-thread names; if root visibility is necessary, a reviewed invocation from an
already authorized administrative terminal is required. This task did not invoke sudo
or open that terminal. The user-supplied successful administrator `systemctl show`
query is evidence that bus access may work outside this sandbox, not proof that this
controller's live administrative path or all required unit properties are verified.
Empty `AllowedCPUs`/`EffectiveCPUs` values do **not** establish isolation or absence of
CPUs. Preflight now prefers a readable kernel `cpuset.cpus.effective` over empty
systemd properties; it checks inherited masks and rejects descendant cgroups with no
housekeeping intersection before attempting any write.

### Kernel threads, execution evidence and monitoring

| Historical TIDs | Previous reported affinity | Current conclusion |
| --- | --- | --- |
| 186, 288, 15162, 16252 | CPU7 | Not visible in this process namespace; names/lifetimes not verified |
| 355, 15092, 15392 | CPU15 | Not visible in this process namespace; names/lifetimes not verified |

No host kernel thread was visible in the current `/proc` snapshot. This is **not**
evidence that the historical threads exited. Do not assign guessed names such as
`migration/7`, `ksoftirqd/7` or `kworker/7:*` to these IDs. The new inspector enumerates
current PID/task entries, records PID/TID/start ticks, PF_KTHREAD, state, name,
affinity, last-CPU field, PF_NO_SETAFFINITY, a clearly labelled per-CPU-name heuristic,
and CPU-time changes across the observation interval. A name or singleton affinity
does not establish migratability; the manager never migrates/stops kernel threads.
Deactivation now uses a PID descriptor after verifying start ticks, avoiding a
PID-reuse race between identity checking and signaling. Unsupported pidfd signaling
refuses the operation instead of falling back to a racy privileged kill.
IDs whose start ticks change are separate lifetimes, and read-time identity races
are discarded. CPU ticks establish execution **somewhere**, not on a particular CPU.
Affinity permits execution; the stat processor field records a last CPU. Neither
provides continuous scheduler history.

The approximately two-second, non-isolated development observation reported:

| Aggregate counter | CPU7 | CPU15 |
| --- | ---: | ---: |
| Utilization delta | 16.84% | 8.00% |
| Hardware interrupt delta | 5,718 | 305 |
| Softirq delta | 628 | 208 |

Global context switches increased by 89,254. These are aggregate host counter
changes, possibly including concurrent development/test activity, not thread
attribution or a benchmark measurement. Actual activity is established; thread-level
execution intervals remain **UNVERIFIED** without approved scheduler tracing.
Tdie was 46.125°C and Tctl 56.125°C at the metadata snapshot. These are observations,
not thermal stability criteria. All observed policy governors remained `schedutil`.

The existing monitor records frequency/governor/driver/limits/boost read-only,
Tdie/Tctl, CPU7/15 utilization, IRQ/softirq deltas, global context-switch deltas,
possible task observations and errors/missed samples. Its thread is constrained to
housekeeping CPUs before readiness, and readiness precedes workload launch. A new
controller check cancels the workload if that monitor thread exits unexpectedly,
even if it did not populate an exception list. Global context switches are not a
reserved-core-specific measure. Reported sysfs frequency is not effective frequency.
Lightweight clean snapshots cannot produce PASS. Scheduling absence remains
UNVERIFIED (or WARNING/FAIL when other evidence requires it). Diagnostic PASS still
requires coverage, verified loss accounting and all other quality gates; tracing has
not been enabled or validated on the real host.

### Hierarchy and readiness classification

Root exposes `cpuset cpu io memory hugetlb pids rdma misc`; subtree control is
`memory pids`, effective CPUs `0-15`. Immediate root groups are `system.slice`,
`user.slice`, `init.scope` and seven mount groups (`dev-hugepages.mount`,
`dev-mqueue.mount`, `proc-sys-fs-binfmt_misc.mount`, `sys-fs-fuse-connections.mount`,
`sys-kernel-config.mount`, `sys-kernel-debug.mount`, `sys-kernel-tracing.mount`).
Their cpuset files are currently absent because the parent has not enabled cpuset
for descendants. Root-cgroup task IDs contain namespace-hidden zero entries.
The mount is presented read-only and ownership appears as UID/GID65534 here; this
is the restricted namespace's view, **not** proof of host ownership/delegation.
Systemd provenance/delegation and existing host CPUAffinity restrictions remain
unverified because the system bus is denied. No direct cgroup write is proposed.

| Check | Classification | Meaning / next evidence |
| --- | --- | --- |
| CPU7/15 topology, online core7/socket0 | Resolved | Sibling pair verified; housekeeping CPUs remain available |
| Empty systemd property interpretation | Resolved | Unset/inherited is not an empty available CPU set |
| Bus denial | Requires administrative authorization | Current context denied; supplied admin query is outside this context |
| Hidden root/host tasks | Not yet verified | Full host `/proc` inventory and root userspace coverage required |
| Tracefs denial | Requires administrative authorization | Optional tracing requires separate approval; no permission change proposed |
| Descendant cpuset enablement | Not yet verified | Available controller; supported systemd runtime readback not live-tested |
| Isolated cpuset partition workflow | Unsupported on this environment | No established safe delegated workflow; retain managed-workload strategy |
| Timeout/monitor/descendant preflight gaps | Requires design modification — implemented | Regression tests cover corrections; real path untested |
| Real broker, service startup, affinity restoration | Not yet verified | Required first hardware-test gates, not certified by mocks |

Kernel5.15 documentation describes partition `root`/`member`, not the newer
`isolated` state. Root absence of a partition file alone is not a capability test.
There is no established systemd-owned isolated-partition deployment here, so do not
force one. The existing supported runtime API strategy is retained.
See [kernel5.15 cgroup documentation](https://docs.kernel.org/5.15/admin-guide/cgroup-v2.html)
and [systemd249 resource controls](https://www.freedesktop.org/software/systemd/man/249/systemd.resource-control.html).

Ordinary workloads under all inventoried top-level managed groups, including PID1's
`init.scope`, are intended to retain usable housekeeping CPUs. No service restart
or network/desktop change is requested. A separate root-level transient slice/service
receives CPU7; the benchmark is both cpuset-constrained and taskset-pinned to CPU7.
CPU15 is excluded from managed workloads, not guaranteed idle. Root kernel threads,
interrupts and unconstrained/new root work remain limitations. Root userspace with
reserved affinity, unknown groups, missing coverage and reserved-only userspace
masks block preflight. Descendant cgroup restrictions are now inspected too. Each verification also rechecks
root userspace coverage; new root userspace able to run on 7/15 or hidden/unreadable
root task identities fail verification. Per-CPU kernel threads remain unconstrained.

### Recovery audit and newly bounded operations

Existing write-ahead private journals, original property/provenance snapshots,
boot IDs, lifetime checks, two locks, owned-unit checks and conflict refusal are
retained. No stale lock file is deleted: `flock` ownership, not filename existence,
is authoritative. Inherited controller lock descriptors can remain held after a
supervisor crash; inspect and terminate only identified owned work, never remove a
lock file to bypass it. PID reuse and reboot cannot authorize signals or stale replay.
A reused/existing recorded controller PID conservatively blocks recovery for review.

Corrections in this review:

- Metadata subprocesses have a 15-second timeout; report delivery has 20 seconds.
- The proxy has a 20-second IPC timeout, with supervisor heartbeats every five seconds
  during execution. Startup without a request fails after 60 seconds. Socket
  reconstruction is still denied here and needs host-side verification.
- Optional `--session-timeout SECONDS` bounds controller startup plus supervised execution;
  the same limit is supplied as transient-service `RuntimeMaxSec`. Service startup
  has a 15-second limit. Stop uses control-group termination, `SendSIGKILL=yes`
  and a five-second stop limit. Post-kill waits are bounded. Unkillable processes
  produce failure/manual-recovery requirements, not a promise of successful cleanup.
- Cancellation is checked between property operations and before controller startup;
  the supervisor never accepts a new workload request after cancellation.
- Unexpected monitor exit triggers cancellation. A broker disconnect, systemd failure
  or deadline triggers owned-work teardown followed by conservative restoration.
- Invalid descriptor-passing requests close received descriptors before failing.

SIGINT/TERM/HUP reach the controller/workload and trigger normal cleanup. Benchmark
exit status stays separate from restoration and quality status: exit0 alone is not
success. Partial activation/restoration or changed administrator provenance refuses
ambiguous rollback and leaves an actionable journal. A failed/uncertain owned-unit
stop blocks restoring masks. An interrupted journal `.tmp` staging file is not
silently replaced; disk/write failure can require administrative journal review.
API timeouts leave potentially ambiguous intent; never acknowledge while an operation
may still be outstanding. Semantic property restoration can leave `/run` bookkeeping;
byte-identical runtime-file restoration is not claimed.

**Remaining live-test blockers:** actual host bus/provenance/task visibility,
least-privilege deployment review, real socket/runuser path, cpuset enablement and
restoration of thread affinities have not been exercised. These uncertainties must
be reviewed and explicitly accepted for a small hardware test, with a second
administrative terminal ready for recovery. They block unattended or formal runs.
Supervisor SIGKILL, kernel-uninterruptible tasks, disk failure, power loss and a crash
cannot guarantee automatic restoration. A workload deadline limits work, not journal
recovery. No claim of real hardware recovery testing is made.

### Proposed first test — do not execute until separately approved

First obtain unrestricted read-only evidence and a blocker-free manager plan;
review the current sources, then explicitly authorize root-owned deployment using
the earlier installation instructions. The new deployment must include the reviewed
updated `isolation_manager.py`; it has not been installed during this task.
Use an existing administrative terminal, with the repository root as working directory.
Prepare the user-owned sessions directory/coordination lock as `newuser` using the
existing documented preparation, and retain a second administrative terminal.
Do not deploy or run the following merely because the commands are documented.

```bash
# In the repository root, AFTER explicit live-test authorization and read-only review:
/usr/bin/python3 -I /usr/local/lib/grng-benchmark/isolation_manager.py activate \
  --approve-isolation --user newuser \
  --controller "$PWD/experiments/tools/benchmark_session.py" \
  --python "$PWD/.venv/bin/python" \
  --session-root "$PWD/experiments/results/linux_ryzen2700x/sessions" \
  --monitor-mode lightweight --interval 1 --session-timeout 60 \
  -- /usr/bin/timeout --signal=TERM --kill-after=2s 30s \
  "$PWD/.venv/bin/python" -B "$PWD/experiments/tools/isolation_probe.py" --duration 25
```

This performs harmless bounded Python integer work, not a GRNG benchmark and not
an RNG dataset. The workload normally lasts 25 seconds; activation/cleanup add time.
The workload timeout is 30 seconds plus a two-second kill grace; the controller/service
have a separate 60-second deadline and bounded shutdown. No high-priority scheduling,
frequency change, tracing or C timed-loop instrumentation is requested. The optional
session deadline does not change the existing experimental schedule or sample counts.

Verification criteria: journal written before any API mutation; no overlapping session;
full hierarchy preflight; live effective housekeeping masks; worker placement exactly
CPU7; monitor affinity excludes7/15 and its initial sample precedes worker placement;
probe stdout reports affinity `[7]`; continuous observations include CPU15 and errors;
normal workload exit0 (timeout/crash means failure); owned service inactive/collected;
restoration record and original property values verified; surviving task identities
and affinities audited; desktop/network still usable without restarting them.
A lightweight quality UNVERIFIED is expected even when placement/restoration succeeds.
Do not translate that into an uncontaminated-run PASS. Any restoration conflict,
monitor loss, missing root visibility, unknown cgroup, no usable housekeeping CPU,
boot mismatch, stale journal, lock conflict, privilege failure or owner mismatch
must block activation or fail/abort the test for review.

Manual recovery from the second authorized administrative terminal:

```bash
/usr/bin/python3 -I /usr/local/lib/grng-benchmark/isolation_manager.py status --journal SESSION_UUID
/usr/bin/python3 -I /usr/local/lib/grng-benchmark/isolation_manager.py verify --journal SESSION_UUID
# If the identity-checked supervisor is still active:
/usr/bin/python3 -I /usr/local/lib/grng-benchmark/isolation_manager.py deactivate --approve-isolation --journal SESSION_UUID
# If orphaned, first inspect journal, recorded boot/process/unit/provenance identities:
cat /var/lib/grng-isolation/SESSION_UUID.json
ps -eo pid,ppid,pgid,lstart,args
# Only after owned work is stopped/identities validated and recovery is authorized:
/usr/bin/python3 -I /usr/local/lib/grng-benchmark/isolation_manager.py recover --approve-isolation --journal SESSION_UUID
/usr/bin/python3 -I /usr/local/lib/grng-benchmark/isolation_manager.py status --journal SESSION_UUID
```

If the controller refuses recovery because a recorded PID exists or provenance changed,
stop and inspect; never kill a numeric PID or reset all masks blindly. Across reboot,
use the previously documented `--acknowledge-new-boot` procedure only after reviewing
current state; it acknowledges the old journal, not a restoration replay. No need to
change governors, frequency, network, tracing permissions, services or boot parameters.

### Focused regression commands

```bash
timeout 60s .venv/bin/python -B -m unittest discover -s experiments/tests -p test_isolation_readiness.py -v
timeout 60s .venv/bin/python -B -m unittest discover -s experiments/tests -p test_cpu_isolation.py -v
timeout 60s .venv/bin/python -B -m unittest discover -s experiments/tests -p test_benchmark_session.py -v
```

All tests remain fixture/mock/harmless-subprocess checks with bounded subprocess waits;
the 25-second probe is **not** run by the tests (only its help/parser is exercised).
The read-only diagnostic interval is not an isolation test. Current recommendation:
**NO-GO now; conditional first-test review after unrestricted evidence and explicit
administrative authorization. Formal RNG benchmarking remains out of scope.**

Files added in this readiness extension: `tools/isolation_readiness.py`,
`tools/isolation_probe.py`, `tests/test_isolation_readiness.py`, and the captured
`CPU_ISOLATION_READINESS.json`. Existing manager, monitor, session controller,
shared CPU helper, two prior test modules and the two protocol documents were
updated. `frequency_control.py`, RNG/PRNG sources, YAML schedules and historical
results were preserved. SHA256 verification found all 5,444 previously recorded
result files unchanged. The final focused suite contains 66 tests: 29 existing
isolation/monitor tests, 21 readiness regressions and 16 session-controller tests.
These results do not establish live privileged activation or restoration success.
