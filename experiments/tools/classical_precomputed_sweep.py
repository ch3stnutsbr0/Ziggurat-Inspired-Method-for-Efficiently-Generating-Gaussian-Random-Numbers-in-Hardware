#!/usr/bin/env python3
"""Classical or Trapezoidal Ziggurat, precomputed-uniform throughput sweep.

Designed to be the single foreground workload of one isolation activation:

    isolation_manager.py activate ... -- \
        .venv/bin/python -B experiments/tools/classical_precomputed_sweep.py \
        --label isolated --expect-affinity 7

or run directly with --pin-cpu 7 for the unisolated taskset baseline:

    .venv/bin/python -B experiments/tools/classical_precomputed_sweep.py \
        --label baseline --pin-cpu 7

Classical is the default. Use --algorithm trapezoid --head H --tail T, or the
trapezoid_h2t4_precomputed_sweep.py entry point, for the Trapezoidal sampler.

Every benchmark run is a separate process. Order is shuffled (seeded) within each
repetition round. Output goes to a new directory; an existing one is an error.
"""
import argparse
import hashlib
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_BINARY = REPO / "c" / "benchmark"
RESULTS = REPO / "experiments" / "results" / "linux_ryzen2700x"
DEFAULT_ROOTS = {"basic": RESULTS / "classical_precomputed",
                 "trapezoid": RESULTS / "trapezoid_precomputed"}
LAYERS = [8, 16, 32, 64, 128, 256]


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError as exc:
        return f"unavailable: {exc.__class__.__name__}"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git(*args):
    try:
        return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def environment(cpu):
    cpufreq = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq"
    return {
        "utc": datetime.now(timezone.utc).isoformat(),
        "affinity": sorted(os.sched_getaffinity(0)),
        "governor": read(f"{cpufreq}/scaling_governor"),
        "scaling_cur_khz": read(f"{cpufreq}/scaling_cur_freq"),
        "scaling_min_khz": read(f"{cpufreq}/scaling_min_freq"),
        "scaling_max_khz": read(f"{cpufreq}/scaling_max_freq"),
        "boost": read("/sys/devices/system/cpu/cpufreq/boost"),
        "loadavg": read("/proc/loadavg"),
        "cgroup": read("/proc/self/cgroup"),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--label", required=True, help="e.g. isolated or baseline; becomes part of the output name")
    p.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    p.add_argument("--algorithm", choices=["basic", "trapezoid"], default="basic")
    p.add_argument("--head", type=int, default=2, help="trapezoid head refinement levels H")
    p.add_argument("--tail", type=int, default=4, help="trapezoid tail refinement levels T")
    p.add_argument("--output-root", type=Path, default=None,
                   help="default: <results>/classical_precomputed or trapezoid_precomputed")
    p.add_argument("--layers", type=int, nargs="+", default=LAYERS)
    p.add_argument("--seeds", type=int, nargs="+", default=[1])
    p.add_argument("--prng", choices=["pcg32", "xoshiro256plus"], default="xoshiro256plus")
    p.add_argument("--samples", type=int, default=10_000_000)
    p.add_argument("--warmup", type=int, default=100_000)
    p.add_argument("--repetitions", type=int, default=5)
    p.add_argument("--buffer-bytes", type=int, default=1 << 30)
    p.add_argument("--cpu", type=int, default=7, help="CPU whose cpufreq state is recorded")
    p.add_argument("--pin-cpu", type=int, default=None,
                   help="wrap each run in taskset -c CPU (baseline mode; omit inside isolation)")
    p.add_argument("--expect-affinity", type=int, nargs="+", default=None,
                   help="abort unless this script's affinity is exactly these CPUs (isolated mode)")
    p.add_argument("--shuffle-seed", type=int, default=0)
    args = p.parse_args(argv)
    trap = args.algorithm == "trapezoid"
    if args.output_root is None:
        args.output_root = DEFAULT_ROOTS[args.algorithm]

    if args.pin_cpu is not None and args.expect_affinity is not None:
        p.error("--pin-cpu and --expect-affinity are for different modes; use one")
    binary = args.binary.resolve()
    if not binary.is_file():
        p.error(f"benchmark binary not found: {binary} (build with: make -C c CC=gcc O2)")
    if args.expect_affinity is not None:
        actual = sorted(os.sched_getaffinity(0))
        if actual != sorted(args.expect_affinity):
            sys.exit(f"affinity {actual} != expected {sorted(args.expect_affinity)}; not running")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = (args.output_root / f"{args.label}-{stamp}").resolve()
    out.mkdir(parents=True, exist_ok=False)

    meta = {
        "script": str(Path(__file__).resolve()),
        "argv": sys.argv,
        "algorithm": "trapezoid" if trap else "classical (basic ziggurat)",
        "head": args.head if trap else None,
        "tail": args.tail if trap else None,
        "uniform_mode": "precomputed",
        "prng": args.prng,
        "layers": args.layers,
        "seeds": args.seeds,
        "samples": args.samples,
        "warmup": args.warmup,
        "repetitions": args.repetitions,
        "buffer_bytes": args.buffer_bytes,
        "pin_cpu": args.pin_cpu,
        "expect_affinity": args.expect_affinity,
        "binary": str(binary),
        "binary_sha256": sha256(binary),
        "git_commit": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain")),
        "uname": platform.uname()._asdict(),
        "start": environment(args.cpu),
    }

    jobs = [(n, s) for n in args.layers for s in args.seeds]
    rng = random.Random(args.shuffle_seed)
    records = []
    total = len(jobs) * args.repetitions
    done = 0
    t0 = time.monotonic()
    for rep in range(args.repetitions):
        order = jobs[:]
        rng.shuffle(order)
        for n, seed in order:
            cmd = [str(binary), "--algorithm", args.algorithm, "--layers", str(n), "--seed", str(seed),
                   "--prng", args.prng, "--uniform-mode", "precomputed",
                   "--uniform-buffer-bytes", str(args.buffer_bytes),
                   "--samples", str(args.samples), "--warmup", str(args.warmup), "--report-json"]
            if trap:
                cmd += ["--head", str(args.head), "--tail", str(args.tail)]
            if args.pin_cpu is not None:
                cmd = ["taskset", "-c", str(args.pin_cpu), *cmd]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            rec = {"algorithm": args.algorithm, "layers": n, "seed": seed, "repetition": rep, "returncode": proc.returncode,
                   "monotonic_s": time.monotonic() - t0}
            marker = "BENCHMARK_JSON: "
            if proc.returncode == 0 and marker in proc.stdout:
                j = json.loads(proc.stdout.split(marker, 1)[1].splitlines()[0])
                rec.update(complete=j["complete"], buffer_exhausted=j["buffer_exhausted"],
                           throughput_msps=j["throughput_million_samples_per_second"],
                           time_per_sample_ns=j["time_per_sample_ns"],
                           uniforms_per_sample=j["uniforms_per_sample"],
                           sampling_time_s=j["sampling_time_seconds"],
                           mean=j["mean"], variance=j["variance"], checksum=j["checksum"])
            else:
                rec.update(complete=False, stderr=proc.stderr[-500:])
            records.append(rec)
            done += 1
            print(f"[{done}/{total}] N={n} seed={seed} rep={rep} "
                  f"{rec.get('throughput_msps', float('nan')):.2f} Msamples/s", flush=True)

    meta["end"] = environment(args.cpu)
    meta["elapsed_s"] = time.monotonic() - t0
    bad = [r for r in records if not r.get("complete")]
    meta["failed_runs"] = len(bad)
    (out / "metadata.json").write_text(json.dumps(meta, indent=2))
    (out / "runs.json").write_text(json.dumps(records, indent=2))

    lines = ["layers,seed,runs,median_msps,mean_msps,cv_percent,uniforms_per_sample"]
    for n, seed in jobs:
        v = [r["throughput_msps"] for r in records
             if r["layers"] == n and r["seed"] == seed and r.get("complete")]
        if not v:
            continue
        u = next(r["uniforms_per_sample"] for r in records
                 if r["layers"] == n and r["seed"] == seed and r.get("complete"))
        cv = 100 * statistics.stdev(v) / statistics.mean(v) if len(v) > 1 else float("nan")
        lines.append(f"{n},{seed},{len(v)},{statistics.median(v):.3f},"
                     f"{statistics.mean(v):.3f},{cv:.2f},{u:.4f}")
    (out / "summary.csv").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nresults: {out}")
    if bad:
        print(f"WARNING: {len(bad)} run(s) failed or were incomplete; see runs.json", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
