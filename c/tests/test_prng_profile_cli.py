import json
import math
import pathlib
import subprocess
import sys

binary, root = sys.argv[1:]
root = pathlib.Path(root)

cases = [
    ("basic", ["--algorithm", "basic", "--layers", "128"]),
    ("trapezoid", ["--algorithm", "trapezoid", "--layers", "8", "--head", "0", "--tail", "0"]),
    ("refined", ["--algorithm", "trapezoid", "--layers", "8", "--head", "2", "--tail", "4"]),
]
for name, args in cases:
    normal = root / (name + "_normal")
    profiled = root / (name + "_profiled")
    common = [binary, *args, "--samples", "10000", "--seed", "1"]
    plain_out = subprocess.check_output([*common, "--output-dir", str(normal)], text=True)
    profile_out = subprocess.check_output([
        *common, "--output-dir", str(profiled), "--profile-prng",
        "--prng-iterations", "100000"], text=True)
    assert "PRNG Profiling" not in plain_out
    assert not (normal / "prng_profile.json").exists()
    assert "PRNG Profiling" in profile_out
    assert "Instrumented Gaussian time per sample" in profile_out
    assert (normal / "samples.bin").read_bytes() == (profiled / "samples.bin").read_bytes()

    profile = json.loads((profiled / "prng_profile.json").read_text())
    summary = json.loads((profiled / "summary.json").read_text())
    config = json.loads((profiled / "config.json").read_text())
    assert summary["prng"] == config["prng"] == "pcg32"
    assert set(summary) == {"prng",
        "sampling_time_seconds", "throughput_samples_per_second", "time_per_sample_ns",
        "mean", "variance", "checksum", "num_samples"}
    assert "profile_prng" not in config
    assert profile["gaussian_samples"] == summary["num_samples"] == 10000
    assert profile["initialization_uniform_calls"] == 0
    assert profile["initialization_pcg32_calls"] == 2
    assert profile["uniform_calls"] > 0
    assert profile["pcg32_calls"] == 2 * profile["uniform_calls"]
    for key, value in profile.items():
        if isinstance(value, float):
            assert math.isfinite(value) and value > 0, (name, key, value)
    assert math.isclose(profile["uniforms_per_gaussian_sample"], profile["uniform_calls"] / 10000)
    assert math.isclose(profile["pcg32_calls_per_gaussian_sample"], profile["pcg32_calls"] / 10000)
    assert math.isclose(profile["baseline_gaussian_ns_per_sample"], summary["time_per_sample_ns"])
    assert math.isclose(profile["estimated_prng_ns_per_sample"],
                        profile["uniforms_per_gaussian_sample"] * profile["median_uniform_ns"])
    assert math.isclose(profile["estimated_prng_fraction"],
                        profile["estimated_prng_ns_per_sample"] / profile["baseline_gaussian_ns_per_sample"])

print("PRNG profile CLI, binary sequence, JSON, and estimates PASS")
