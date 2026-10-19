# First live CPU isolation smoke test

Session `42a307c3-3897-4948-b717-1b593dfc3fb8` completed on the Ryzen 7 2700X host. This was a harmless Python probe, not an RNG benchmark or a performance comparison.

The placement record verifies the workload's effective cpuset and affinity were both `[7]`. The monitor was pinned to housekeeping CPUs `0-6,8-14`; it collected 27 environment samples with no reported monitor errors. The probe exited with status 0 after approximately 25.7 seconds.

The supervisor's `restoration.json` reports `verified: true`, no errors, and all 10 changed systemd units restored. The task-affinity audit is verified with no conflicts. The final isolation record reports `restored`. The controller's `session.json` records `pending_restoration` at its handoff to the root supervisor; the separate supervisor-produced restoration and final isolation records contain the completed restoration result.

Environmental quality is `WARNING`, and scheduling interference is `UNVERIFIED`. Periodic monitoring cannot prove that no short-lived task or interrupt ran on the reserved core. CPU frequency remained dynamically managed; reported frequency is not an effective-clock measurement, and no fixed frequency was verified. These results validate the basic placement and restoration path for an initial smoke test, not complete kernel/interrupt isolation or controlled-frequency benchmarking.

The original session artifacts remain under `results/linux_ryzen2700x/sessions/42a307c3-3897-4948-b717-1b593dfc3fb8/` and are intentionally not included in this commit.
