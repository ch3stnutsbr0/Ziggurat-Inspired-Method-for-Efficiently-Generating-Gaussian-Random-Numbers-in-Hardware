#!/usr/bin/env python3
"""Trapezoidal Ziggurat (H=2, T=4), precomputed-uniform throughput sweep.

Same protocol, options and outputs as classical_precomputed_sweep.py, with the
algorithm fixed to trapezoid H2/T4. Results go to
experiments/results/linux_ryzen2700x/trapezoid_precomputed/<label>-<timestamp>/.

    isolated (single activation):   ... -- .venv/bin/python -B <this file> \
                                        --label isolated --expect-affinity 7
    unisolated baseline:            .venv/bin/python -B <this file> \
                                        --label baseline --pin-cpu 7
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classical_precomputed_sweep import main  # noqa: E402

if __name__ == "__main__":
    main(["--algorithm", "trapezoid", "--head", "2", "--tail", "4", *sys.argv[1:]])
