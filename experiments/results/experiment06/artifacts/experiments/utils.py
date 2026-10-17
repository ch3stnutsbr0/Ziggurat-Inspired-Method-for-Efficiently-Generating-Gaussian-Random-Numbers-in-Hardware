"""Strict YAML configuration parsing for the dry-run planner."""

from pathlib import Path
import math

import yaml

UINT64_MAX = (1 << 64) - 1
BASIC_LAYERS = {8, 16, 32, 64, 128, 256}
ALGORITHMS = {"basic", "trapezoid", "trapezoid_refined"}


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ValueError("YAML mapping keys must be scalar values") from exc
        if duplicate:
            raise ValueError(f"Duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping
)


def load_config(path):
    with Path(path).open(encoding="utf-8") as stream:
        return yaml.load(stream, Loader=UniqueKeyLoader)


def validate_config(config):
    """Return errors; never silently supply sample counts or repetitions.

    Required modes are performance: {enabled, samples, repetitions} and
    validation: {enabled, samples}. Disabled modes need only enabled: false.
    Optional output_dir is relative to the repository root (default:
    experiments/results/raw). Validation repetitions may only be 1.
    """
    errors = []

    def mapping(value, where, allowed):
        if not isinstance(value, dict):
            errors.append(f"{where}: required mapping")
            return False
        for key in value:
            if key not in allowed:
                errors.append(f"{where}: unknown field {key!r}")
        return True

    def integer(value, where, low, high=UINT64_MAX):
        if type(value) is not int or not low <= value <= high:
            errors.append(f"{where}: require an integer in [{low}, {high}]")
            return False
        return True

    def values(section, key, where, low, high, required=True):
        if key not in section and not required:
            return []
        items = section.get(key)
        if not isinstance(items, list) or not items:
            errors.append(f"{where}.{key}: require a nonempty list")
            return []
        good = []
        for value in items:
            if integer(value, f"{where}.{key}", low, high):
                if value in good:
                    errors.append(f"{where}.{key}: duplicate value {value}")
                good.append(value)
        return good

    if not mapping(config, "config", {"algorithms", "performance", "validation", "output_dir",
                                      "experiment_id", "profiling", "keep_validation_samples",
                                      "schedule_seed", "tail_thresholds", "normal_distribution", "prng"}):
        return errors
    if "prng" in config:
        section = config["prng"]
        if mapping(section, "prng", {"type"}):
            if section.get("type") not in ("pcg32", "xoshiro256plus"):
                errors.append("prng.type: require pcg32 or xoshiro256plus")
            if section.get("type") == "xoshiro256plus" and isinstance(config.get("profiling"), dict) and config["profiling"].get("enabled"):
                errors.append("profiling: existing PCG32 call profiling requires prng.type pcg32")
    if "experiment_id" in config and config["experiment_id"] != "experiment_01":
        errors.append("experiment_id: supported value is experiment_01")
    if "normal_distribution" in config:
        distribution=config["normal_distribution"]
        if not isinstance(distribution,dict) or distribution != {"mean":0,"standard_deviation":1}:
            errors.append("normal_distribution: Experiment 01 requires mean 0 and standard_deviation 1")
    if "keep_validation_samples" in config and type(config["keep_validation_samples"]) is not bool:
        errors.append("keep_validation_samples: require true or false")
    if "schedule_seed" in config:
        integer(config["schedule_seed"], "schedule_seed", 0)
    if "tail_thresholds" in config:
        thresholds=config["tail_thresholds"]
        if (not isinstance(thresholds,list) or not thresholds or
                any(type(x) not in (int,float) or not math.isfinite(x) or x<=0 for x in thresholds) or
                len(set(thresholds))!=len(thresholds)):
            errors.append("tail_thresholds: require distinct positive numbers")
    if "profiling" in config:
        section=config["profiling"]
        if mapping(section,"profiling",{"enabled","samples","prng_iterations"}):
            if type(section.get("enabled")) is not bool:
                errors.append("profiling.enabled: require true or false")
            if section.get("enabled") is True:
                integer(section.get("samples"),"profiling.samples",2)
                integer(section.get("prng_iterations"),"profiling.prng_iterations",1)
    algorithms = config.get("algorithms")
    if mapping(algorithms, "algorithms", ALGORITHMS):
        enabled_count = 0
        for name, section in algorithms.items():
            if name not in ALGORITHMS:
                continue
            where = f"algorithms.{name}"
            allowed = {"enabled", "layers", "seeds"}
            if name != "basic":
                allowed |= {"heads", "tails"}
            if not mapping(section, where, allowed):
                continue
            enabled = section.get("enabled")
            if type(enabled) is not bool:
                errors.append(f"{where}.enabled: require true or false")
            enabled_count += enabled is True
            required = enabled is True
            layers = values(section, "layers", where, 2, 256, required)
            if name == "basic" and any(n not in BASIC_LAYERS for n in layers):
                errors.append(f"{where}.layers: supported counts are {sorted(BASIC_LAYERS)}")
            values(section, "seeds", where, 0, UINT64_MAX, required)
            if name != "basic":
                heads = values(section, "heads", where, 0, 16, required)
                tails = values(section, "tails", where, 0, 16, required)
                if name == "trapezoid" and any(v != 0 for v in heads + tails):
                    errors.append(f"{where}: unrefined trapezoid requires heads/tails [0]")
            # The refined Cartesian product may contain 0/0; expansion excludes it.
        if not enabled_count:
            errors.append("algorithms: at least one algorithm must be enabled")
    enabled_modes = 0
    for mode in ("performance", "validation"):
        section = config.get(mode)
        allowed = {"enabled", "samples", "repetitions"}
        if mode == "validation":
            allowed |= {"significance_level", "chi_square"}
        if not mapping(section, mode, allowed):
            continue
        enabled = section.get("enabled")
        if type(enabled) is not bool:
            errors.append(f"{mode}.enabled: require true or false")
        enabled_modes += enabled is True
        if enabled is True or "samples" in section:
            integer(section.get("samples"), f"{mode}.samples", 2)
        if mode == "performance" and (enabled is True or "repetitions" in section):
            integer(section.get("repetitions"), f"{mode}.repetitions", 1)
        if mode == "validation" and "repetitions" in section:
            integer(section["repetitions"], "validation.repetitions", 1, 1)
    validation = config.get("validation")
    if isinstance(validation, dict) and ({"significance_level", "chi_square"} & validation.keys()):
        try:
            validation_settings(config)
        except ValueError as exc:
            errors.append(str(exc))
    if not enabled_modes:
        errors.append("modes: enable performance and/or validation explicitly")
    output = config.get("output_dir", "experiments/results/raw")
    if not isinstance(output, str) or not output.strip() or any(ord(c) < 32 for c in output):
        errors.append("output_dir: require a nonempty path without control characters")
    elif ".." in Path(output).parts:
        errors.append("output_dir: parent traversal '..' is not allowed")
    return errors


def write_json(path, data, *, replace=False):
    """Create JSON exclusively, or atomically update an owned status file."""
    import json
    import os
    import tempfile

    path = Path(path)
    text = json.dumps(data, indent=2, allow_nan=False) + "\n"
    if not replace:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".execution-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def sha256_file(path):
    import hashlib

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binary_statistics(path, samples):
    """Check little-endian float64 output with bounded-memory, two-pass moments."""
    import math
    import numpy as np

    path = Path(path)
    expected = samples * 8
    if not path.is_file() or path.stat().st_size != expected:
        actual = path.stat().st_size if path.is_file() else None
        raise ValueError(f"Invalid sample file size: expected {expected}, found {actual}: {path}")

    mapped = np.memmap(path, dtype='<f8', mode='r', shape=(samples,))
    try:
        total = np.longdouble(0)
        for begin in range(0, samples, 1_000_000):
            block = mapped[begin:begin+1_000_000]
            if not np.all(np.isfinite(block)):
                raise ValueError(f"Non-finite sample in {path}")
            total += np.sum(block, dtype=np.longdouble)
        mean = float(total / samples)
        squares = np.longdouble(0)
        for begin in range(0, samples, 1_000_000):
            centered = mapped[begin:begin+1_000_000] - mean
            squares += np.sum(centered*centered, dtype=np.longdouble)
        variance = float(squares / (samples - 1))
    finally:
        mapped._mmap.close()
    if not math.isfinite(mean) or not math.isfinite(variance):
        raise ValueError(f"Non-finite binary moments in {path}")
    return dict(num_samples=samples, binary_size_bytes=expected, mean=mean,
                variance=variance, variance_ddof=1,
                method="Two-pass chunked long-double NumPy moments; no hypothesis tests")


def validation_settings(config):
    """Read explicit statistical settings without importing scientific packages."""
    import math

    section = config.get("validation") if isinstance(config, dict) else None
    if not isinstance(section, dict):
        raise ValueError("validation: required mapping")
    alpha = section.get("significance_level")
    if type(alpha) not in (int, float) or not math.isfinite(alpha) or not 1e-4 <= alpha <= 0.9999:
        raise ValueError("validation.significance_level: require a value in [0.0001, 0.9999] supported by the AD calibration")
    chi = section.get("chi_square")
    if not isinstance(chi, dict) or set(chi) != {"bins", "range", "minimum_expected_count"}:
        raise ValueError("validation.chi_square requires exactly bins, range and minimum_expected_count")
    if type(chi["bins"]) is not int or not 1 <= chi["bins"] <= 100000:
        raise ValueError("validation.chi_square.bins: require an integer in [1, 100000]")
    interval = chi["range"]
    if (not isinstance(interval, list) or len(interval) != 2
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in interval)
            or interval[0] >= interval[1] or not math.isfinite(interval[1] - interval[0])):
        raise ValueError("validation.chi_square.range: require two finite increasing bounds")
    minimum = chi["minimum_expected_count"]
    if type(minimum) not in (int, float) or not math.isfinite(minimum) or minimum <= 0:
        raise ValueError("validation.chi_square.minimum_expected_count: require a positive finite number")
    return {"significance_level": float(alpha), "chi_square": {
        "bins": chi["bins"], "range": [float(x) for x in interval], "minimum_expected_count": float(minimum)}}
