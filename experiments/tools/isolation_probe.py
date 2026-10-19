#!/usr/bin/env python3
"""Harmless bounded CPU work for an explicitly approved isolation test; no RNG."""
import argparse
import json
import math
import os
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=25)
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or not .01 <= args.duration <= 30:
        parser.error('duration must be finite and between 0.01 and 30 seconds')
    start = time.monotonic()
    iterations = 0
    while time.monotonic()-start < args.duration:
        # Frequent monotonic checks bound each chunk; no files or datasets.
        iterations += sum(range(1000))
    print(json.dumps({'kind': 'isolation_probe_not_rng', 'elapsed_seconds': time.monotonic()-start,
                      'pid': os.getpid(), 'affinity': sorted(os.sched_getaffinity(0)),
                      'checksum': iterations}))


if __name__ == '__main__':
    main()
