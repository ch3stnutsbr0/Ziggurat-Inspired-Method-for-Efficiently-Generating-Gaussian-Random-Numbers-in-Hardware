# Manual BIOS fixed-frequency preparation for GRNG

All firmware changes remain manual. No BIOS access, firmware writes, overclocking, voltage tuning or CPU setting changes were performed by this task. The initial research target is 3.2 GHz, subject to actual hardware/firmware support and verification; it is not a claim of stability or a recommendation to overclock.

## Identify the platform first

Read-only Linux inventory:

```bash
for name in board_vendor board_name board_version bios_vendor bios_version bios_date; do
    printf '%s: ' "$name"
    cat "/sys/class/dmi/id/$name"
done
lscpu
uname -r
```

Observed on this workstation: ASRock X570 Pro4; board_version empty; American Megatrends Inc. firmware P1.70; reported BIOS date 09/10/2019. Confirm motherboard revision, exact firmware build and CPU support against the physical board and its official manual before giving menu-specific advice. These DMI strings alone do not justify guessing firmware paths. No motherboard-specific menu instructions are supplied here.

Collect the exact board revision, CPU SKU/stepping, firmware version/date, relevant official manual, current CPU/boost/multiplier/idle settings, memory profile, cooling configuration and recovery instructions. Keep serial numbers and unrelated identifiers out of shared benchmark reports. No firmware update is part of this task.

## Record the current configuration

Before manual changes, photograph/write down relevant screens and export a firmware settings profile if the board supports it. Record boot mode/order, storage/controller mode, memory settings and security settings as well as CPU settings so recovery does not unintentionally prevent Linux from booting. Keep a paper/off-machine copy. A saved settings profile is not necessarily portable across firmware versions. Learn the board's documented recovery method before changing anything; no generic jumper/pin procedure is safe to invent.

## Concepts to review with the exact board manual

Core frequency is influenced by reference clock and multiplier, but a fixed multiplier alone does not prove constant effective execution frequency. Idle states, boost, thermal/power constraints and firmware control can still change active residency or delivered performance. Do not change reference clocks or voltages for this project.

Precision Boost dynamically chooses performance according to factors including temperature, power, current and workload; [AMD's Precision Boost description](https://www.amd.com/en/resources/support-articles/faqs/CPU-PB2.html) explains the adaptive behavior. Core Performance Boost is a firmware control related to boost behavior; its naming and interaction with manual ratios must be confirmed in the specific firmware. Precision Boost Overdrive is a separate tuning concept and is not required or recommended here. Record existing settings instead of assuming identically named options behave identically across boards.

C-states control idle behavior. Changing them can alter power use and latency and does not itself establish a constant active clock. Do not disable them automatically or mix their settings across comparison blocks without a separately justified protocol. Keep safety/thermal protections intact. The benchmark controller never changes any BIOS or C-state option.

Avoid manual voltage adjustments without hardware-specific justification; an arbitrary multiplier/voltage combination can create instability, excessive power or heating. Even a below-boost research target is not a guarantee that every firmware's manual mode is benign. Keep changes conservative, documented and reversible; obtain hardware-specific advice rather than trying unreviewed tuning instructions.

## Return to Linux and verify

After any user-approved manual firmware preparation, recheck core/SMT/NUMA topology, CPU7 and sibling15, driver, every policy, boost and temperature. BIOS changes can alter what Linux exposes; previous software-control assumptions may no longer apply. Do not combine automatic software mode with BIOS mode.

```bash
lscpu -e=CPU,CORE,SOCKET,NODE,ONLINE
taskset -pc $$
cat /sys/devices/system/cpu/cpu7/topology/thread_siblings_list
.venv/bin/python -B experiments/tools/benchmark_session.py --mode bios --cpu 7 --target-khz 3200000 --inspect
sensors
```

For a later separately authorized foreground workload, use BIOS mode as documented in [BENCHMARK_SESSION_PROTOCOL.md](BENCHMARK_SESSION_PROTOCOL.md). It never writes governor, limits or boost. It logs initial/periodic/final reported frequencies and temperature, detects obvious reported-target discrepancies and warns when effective-frequency verification is unavailable. Do not use an idle snapshot or a performance-governor label as a stability certificate. The current perf executable and reliable effective-frequency collector are unavailable, and cpuinfo_cur_freq is permission denied; APERF/MPERF event names alone are not measurements.

Before publication, independently validate delivered frequency under the actual workload with a reviewed CPU-compatible effective-frequency instrument, verify its privilege requirements/calibration and record thermal conditions and sampling overhead. Distinguish idle time and reference clock ticks from active hardware core cycles. No long stress test or formal experiment is authorized by this setup guide.

## Restore and assess long-term use

First restore the individually recorded original settings using the board's official procedure. If defaults are required, follow the exact board manual's supported restore-defaults/recovery method and restore necessary boot/storage/memory configuration afterward. Do not assume defaults reproduce the previous research environment or prescribe a CMOS-clear action without board-specific instructions. Reboot and verify Linux behavior and temperatures before resuming work.

Long-term manual-frequency operation can increase idle power, temperature, fan noise or decrease energy efficiency, and can create stability issues depending on firmware behavior. Excess heating and instability can undermine data integrity. Prefer a documented research-session configuration with an explicit return to normal settings rather than assuming a manual mode is appropriate for unattended daily operation. No overclocking, thermal-limit changes or manual voltage recipe is recommended.
