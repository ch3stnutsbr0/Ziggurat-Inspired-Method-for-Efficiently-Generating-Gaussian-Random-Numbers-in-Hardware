"""Verify complete, reproducible benchmark experiment directories."""
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

import numpy as np

benchmark = str(Path(sys.argv[1]).resolve())
work = Path(sys.argv[2]).resolve()


def run(*args):
    return subprocess.run([benchmark, *args], cwd=work, text=True, capture_output=True)


def field(log, name):
    match = re.search(rf"^{re.escape(name)}:\s*(.+)$", log, re.MULTILINE)
    assert match, (name, log)
    return match.group(1)


for algorithm, config in (
    ("trapezoid", ("--layers", "8", "--head", "2", "--tail", "4")),
    ("basic", ("--layers", "16")),
):
    directory = work / "nested" / algorithm / "run"
    chosen_path = os.path.relpath(directory, work) if algorithm == "trapezoid" else str(directory)
    args = ("--algorithm", algorithm, *config, "--samples", "65539", "--seed", "7")
    plain = run(*args)
    assert plain.returncode == 0, plain.stderr
    assert not directory.exists()
    first = run(*args, "--output-dir", chosen_path)
    assert first.returncode == 0, first.stderr
    assert {p.name for p in directory.iterdir()} == {"samples.bin", "summary.json", "config.json"}
    data = (directory / "samples.bin").read_bytes()
    assert len(data) == 65539 * 8
    values = np.fromfile(directory / "samples.bin", dtype="<f8")
    assert values.size == 65539 and np.isfinite(values).all()
    summary = json.loads((directory / "summary.json").read_text())
    config_json = json.loads((directory / "config.json").read_text())
    assert summary["num_samples"] == config_json["num_samples"] == 65539
    assert config_json["algorithm"] == algorithm
    assert config_json["N"] == (8 if algorithm == "trapezoid" else 16)
    assert config_json["seed"] == 7
    assert config_json["compiler_optimization"] == "O2"
    if algorithm == "trapezoid":
        assert (config_json["H"], config_json["T"]) == (2, 4)
    else:
        assert "H" not in config_json and "T" not in config_json
    assert math.isclose(summary["mean"], float(values.mean()), abs_tol=1e-12)
    assert math.isclose(summary["variance"], float(values.var(ddof=1)), abs_tol=1e-12)
    assert math.isclose(summary["checksum"], float(values.sum()), abs_tol=1e-8)
    assert math.isclose(summary["sampling_time_seconds"], float(field(first.stdout, "Time").split()[0]), abs_tol=5e-7)
    assert math.isclose(summary["throughput_samples_per_second"], 65539 / summary["sampling_time_seconds"], rel_tol=1e-12)
    assert math.isclose(summary["time_per_sample_ns"], summary["sampling_time_seconds"] * 1e9 / 65539, rel_tol=1e-12)
    for name in ("Algorithm", "Configuration", "Seed", "Samples", "Checksum", "Mean", "Variance"):
        assert field(first.stdout, name) == field(plain.stdout, name), name
    assert field(first.stdout, "Output directory") == chosen_path

    again = run(*args, "--output-dir", chosen_path)
    assert again.returncode != 0 and "--overwrite" in again.stderr
    assert (directory / "samples.bin").read_bytes() == data
    overwritten = run(*args, "--output-dir", chosen_path, "--overwrite")
    assert overwritten.returncode == 0, overwritten.stderr
    assert (directory / "samples.bin").read_bytes() == data
    assert json.loads((directory / "summary.json").read_text())["num_samples"] == 65539

blocked = work / "not-a-directory"
blocked.write_text("x")
for args in (
    ("--output-dir", ""),
    ("--output-dir", str(blocked / "child")),
    ("--output-dir", str(work / "mixed"), "--output", str(work / "other.bin")),
    ("--overwrite",),
):
    result = run("--samples", "2", *args)
    assert result.returncode != 0, (args, result.stdout, result.stderr)
assert not (work / "mixed").exists()
assert not (work / "other.bin").exists()
print("Experiment directory and JSON validation PASS")
