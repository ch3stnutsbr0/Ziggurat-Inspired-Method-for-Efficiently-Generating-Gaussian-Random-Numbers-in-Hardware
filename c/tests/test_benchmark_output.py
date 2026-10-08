"""Check raw benchmark output against the unchanged summary statistics."""
import math
import pathlib
import re
import subprocess
import sys

import numpy as np

benchmark = sys.argv[1]
work = pathlib.Path(sys.argv[2])


def run(*args):
    return subprocess.run(
        [benchmark, *args], text=True, capture_output=True, check=True
    ).stdout


def field(log, name):
    match = re.search(rf"^{re.escape(name)}:\s*(.+)$", log, re.MULTILINE)
    assert match, (name, log)
    return match.group(1)


for algorithm, config in (
    ("basic", ("--layers", "16")),
    ("trapezoid", ("--layers", "16", "--head", "1", "--tail", "1")),
):
    for count in (1000, 65539):  # The latter crosses the output buffer boundary.
        args = ("--algorithm", algorithm, *config, "--samples", str(count), "--seed", "7")
        plain = run(*args)
        assert "Binary output mode:" not in plain
        assert "Output:" not in plain
        output = work / f"{algorithm}-{count}.bin"
        first = run(*args, "--output", str(output))
        data = output.read_bytes()
        assert len(data) == 8 * count
        samples = np.fromfile(output, dtype="<f8")
        assert len(samples) == count and np.isfinite(samples).all()
        assert math.isclose(float(samples.mean()), float(field(first, "Mean")), abs_tol=5e-9)
        assert math.isclose(float(samples.var(ddof=1)), float(field(first, "Variance")), abs_tol=5e-9)
        for name in ("Algorithm", "Configuration", "Seed", "Samples",
                     "Checksum", "Mean", "Variance"):
            assert field(first, name) == field(plain, name), (algorithm, name)
        second = run(*args, "--output", str(output))
        assert output.read_bytes() == data
        for name in ("Checksum", "Mean", "Variance"):
            assert field(second, name) == field(first, name)

for args in (
    ("--output", ""),
    ("--output", "--counters"),
    ("--output", str(work)),  # A directory cannot be opened as an output file.
):
    result = subprocess.run(
        [benchmark, "--samples", "2", *args], text=True, capture_output=True
    )
    assert result.returncode != 0, (args, result.stdout, result.stderr)

print("Binary output and NumPy validation PASS")
