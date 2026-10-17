"""Plan experiments and explicitly execute them sequentially when requested."""

from collections import Counter
from itertools import product
from pathlib import Path
import os
import json
import math
import subprocess
import sys
import time
import tempfile
import uuid
import fcntl
from datetime import datetime, timezone
import re
import shlex
import shutil

from utils import binary_statistics, sha256_file, validate_config, write_json

MAX_PLANNED_RUNS = 100000


def expand_configurations(config):
    configurations = []
    prng = config.get("prng", {}).get("type", "pcg32")
    if prng not in ("pcg32", "xoshiro256plus"):
        raise ValueError("Unsupported prng.type")
    uniform_mode = config.get("uniform_mode", "inline")
    uniform_bytes = config.get("uniform_buffer_size_bytes", 2 * 1024**3)
    seen = set()
    for label, settings in config["algorithms"].items():
        if not settings["enabled"]:
            continue
        algorithm = "basic" if label == "basic" else "trapezoid"
        heads = [None] if algorithm == "basic" else settings["heads"]
        tails = [None] if algorithm == "basic" else settings["tails"]
        size = len(settings["layers"]) * len(heads) * len(tails) * len(settings["seeds"])
        if len(configurations) + size > MAX_PLANNED_RUNS:
            raise ValueError("Parameter matrix exceeds the 100,000-entry dry-run memory limit")
        for n, h, t, seed in product(settings["layers"], heads, tails, settings["seeds"]):
            if label == "trapezoid_refined" and h == 0 and t == 0:
                continue
            key = (algorithm, n, h, t, seed)
            if key in seen:
                raise ValueError(f"Duplicate effective configuration: {key}")
            seen.add(key)
            name = f"{algorithm}_N{n}"
            if algorithm != "basic":
                name += f"_H{h}_T{t}"
            configurations.append(dict(
                parameter_id=f"{name}_seed{seed}" + (f"_prng{prng}" if prng != "pcg32" else "") + ("_precomputed" if uniform_mode == "precomputed" else ""), algorithm_label=label,
                prng=prng, uniform_mode=uniform_mode, uniform_buffer_size_bytes=uniform_bytes,
                algorithm=algorithm, N=n, H=h, T=t, seed=seed,
            ))
    return configurations


def uniform_arguments(parameters):
    if parameters.get("uniform_mode", "inline") == "precomputed":
        return ["--uniform-mode", "precomputed", "--uniform-buffer-bytes",
                str(parameters["uniform_buffer_size_bytes"]), "--report-json"]
    return []


def build_runs(config, configurations, repository):
    """Performance output is a Python runner destination, not a C output flag."""
    repository = Path(repository).resolve()
    output = Path(config.get("output_dir", "experiments/results/raw"))
    if not output.is_absolute():
        output = repository / output
    output = output.resolve()
    runs = []
    count = len(configurations) * sum(
        (config[mode].get("repetitions", 1) if mode == "performance" else 1)
        for mode in ("performance", "validation") if config[mode]["enabled"]
    )
    if count > MAX_PLANNED_RUNS:
        raise ValueError(f"Schedule has {count:,} runs; dry-run limit is {MAX_PLANNED_RUNS:,}")
    for parameters in configurations:
        for mode in ("performance", "validation"):
            settings = config[mode]
            if not settings["enabled"]:
                continue
            repetitions = settings["repetitions"] if mode == "performance" else 1
            for repetition in range(1, repetitions + 1):
                experiment_id = f"{parameters['parameter_id']}_{mode}"
                if mode == "performance":
                    experiment_id += f"_rep{repetition}"
                directory = output / experiment_id
                argv = [str(repository / "c/benchmark"), "--algorithm", parameters["algorithm"],
                        "--layers", str(parameters["N"])]
                if parameters.get("prng", "pcg32") != "pcg32":
                    argv += ["--prng", parameters["prng"]]
                argv += uniform_arguments(parameters)
                if parameters["algorithm"] == "trapezoid":
                    argv += ["--head", str(parameters["H"]), "--tail", str(parameters["T"])]
                argv += ["--seed", str(parameters["seed"]), "--samples", str(settings["samples"])]
                if mode == "validation":
                    argv += ["--output-dir", str(directory)]
                runs.append(dict(
                    **parameters, experiment_id=experiment_id, repetition=repetition,
                    mode=mode, samples=settings["samples"], argv=argv,
                    command=shlex.join(argv), output_directory=str(directory),
                    output_handling=("C writes samples.bin, summary.json, config.json"
                                     if mode == "validation" else "Python runner captures stdout here; C creates no files"),
                ))
    return runs


def inspect_paths(paths, *, allow_existing=False):
    errors = []
    resolved = set()
    for raw in paths:
        path = Path(raw)
        try:
            target = path.resolve()
            if target in resolved:
                errors.append(f"Output directory collision: {target}")
            resolved.add(target)
            if os.path.lexists(path):
                if not allow_existing:
                    errors.append(f"Output directory already exists; potential overwrite: {path}")
                elif path.is_symlink() or not path.is_dir():
                    errors.append(f"Resume requires a real output directory, not a link or file: {path}")
            ancestor = path.parent
            while not ancestor.exists() and not ancestor.is_symlink():
                ancestor = ancestor.parent
            if not ancestor.is_dir():
                errors.append(f"Output parent is not a directory: {ancestor}")
            elif not os.access(ancestor, os.W_OK | os.X_OK):
                errors.append(f"Output parent is not writable/searchable: {ancestor}")
            if any(len(os.fsencode(part)) > os.pathconf(ancestor, "PC_NAME_MAX") for part in path.parts):
                errors.append(f"Output path component is too long: {path}")
            if len(os.fsencode(path)) >= os.pathconf(ancestor, "PC_PATH_MAX"):
                errors.append(f"Output path is too long: {path}")
        except (OSError, ValueError, RuntimeError) as exc:
            errors.append(f"Invalid output path {path}: {exc}")
    return errors


def dry_run(config, repository, *, resume=False, refresh_performance=False):
    repository = Path(repository).resolve()
    errors = validate_config(config)
    report = dict(
        status="invalid" if errors else "valid", errors=errors, warnings=[],
        configurations=[], configurations_per_algorithm={}, runs=[], first_10_commands=[],
        counts=None, resources=None, unsupported_cli_arguments=[],
        output_check="Not scheduled: configuration is incomplete or invalid",
    )
    warnings = report["warnings"]
    try:
        source = (repository / "c/benchmark.c").read_text()
        supported = set(re.findall(r'strcmp\(argv\[i\],"(--[a-z-]+)"\)', source))
        report["supported_cli_arguments"] = sorted(supported)
        report["cli_verification"] = "Static inspection of c/benchmark.c; executable was not invoked"
    except OSError as exc:
        errors.append(f"Cannot inspect C benchmark CLI: {exc}")
        supported = set()
    executable = repository / "c/benchmark"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        warnings.append("c/benchmark is missing or not executable; build it before a future real run")
    else:
        warnings.append("Existing executable was not invoked; its CLI/build provenance is unverified")
    # Keep the valid parameter matrix available when only mode settings are missing.
    if not any(error.startswith(("config:", "algorithms", "prng")) for error in errors):
        try:
            report["configurations"] = expand_configurations(config)
        except ValueError as exc:
            errors.append(str(exc))
    parameters = report["configurations"]
    report["configurations_per_algorithm"] = dict(Counter(p["algorithm_label"] for p in parameters))
    report["unique_configurations_including_seeds"] = len(parameters)
    report["unique_parameter_sets_excluding_seeds"] = len({
        (p["algorithm"], p["N"], p["H"], p["T"]) for p in parameters
    })
    report["distinct_seed_values"] = sorted({p["seed"] for p in parameters})
    if any(p["H"] is not None and max(p["H"], p["T"]) > 8 for p in parameters):
        warnings.append("Deep refinement can increase initialization cost and numerical sensitivity; CLI bounds do not prove numerical validity")
    if len(report["distinct_seed_values"]) == 1:
        warnings.append("Only one RNG seed is configured; timing repetitions repeat the same sample stream and are not independent validation datasets")
    warnings.append("Static checks cannot establish Gaussian accuracy or successful numerical table construction")
    if not errors:
        try:
            report["runs"] = build_runs(config, parameters, repository)
        except (ValueError, OSError, RuntimeError) as exc:
            errors.append(str(exc))
    runs = report["runs"]
    if runs:
        ids = [run["experiment_id"] for run in runs]
        if len(ids) != len(set(ids)):
            errors.append("Duplicate experiment IDs")
        errors.extend(inspect_paths((run["output_directory"] for run in runs), allow_existing=resume))
        report["output_check"] = "Checked IDs, resolved paths, existing directories, parent access and path length limits"
        flags = {arg for run in runs for arg in run["argv"][1:] if arg.startswith("--")}
        report["unsupported_cli_arguments"] = sorted(flags - supported)
        if flags - supported:
            errors.append(f"Unsupported C CLI arguments: {sorted(flags - supported)}")
        counts = Counter(run["mode"] for run in runs)
        validation = [run for run in runs if run["mode"] == "validation"]
        binary_bytes = sum(run["samples"] * 8 for run in validation)
        max_bytes = max((run["samples"] * 8 for run in validation), default=0)
        report["counts"] = dict(
            performance_runs=counts["performance"], validation_runs=counts["validation"],
            total_benchmark_executions=len(runs),
            total_generated_samples=sum(run["samples"] for run in runs),
            performance_samples=sum(run["samples"] for run in runs if run["mode"] == "performance"),
            validation_samples=sum(run["samples"] for run in validation),
        )
        report["resources"] = dict(
            binary_storage_bytes=binary_bytes, binary_storage_GiB=binary_bytes / 2**30,
            max_binary_file_bytes=max_bytes,
            max_C_sample_buffer_bytes=min(max_bytes, 65536 * 8),
            future_full_array_load_bytes=max_bytes,
            notes="Sequential execution assumed. C streams 65,536 doubles; table/state memory is additional. Future statistical tests may need several full-array copies. JSON/log/filesystem overhead is excluded.",
        )
        if max_bytes >= 2**30:
            warnings.append("At least one sample file is >=1 GiB; loading/sorting full arrays may strain laptop memory")
        if binary_bytes >= 10 * 2**30:
            warnings.append("Binary sample storage is >=10 GiB; review disk capacity and retention")
        if report["counts"]["total_generated_samples"] >= 10**9:
            warnings.append("Schedule generates >=1 billion samples; runtime may be substantial and is not estimated without measurements")
        ancestor = Path(runs[0]["output_directory"]).parent
        while not ancestor.exists():
            ancestor = ancestor.parent
        try:
            free = shutil.disk_usage(ancestor).free
            report["resources"]["available_disk_bytes"] = free
            if binary_bytes > free:
                errors.append("Estimated binary storage exceeds currently available disk space")
            elif binary_bytes > free * 0.8:
                warnings.append("Binary storage would consume over 80% of available disk space")
        except OSError as exc:
            warnings.append(f"Could not inspect free disk space: {exc}")
        report["first_10_commands"] = [run["command"] for run in runs[:10]]
        if counts["performance"] and counts["validation"]:
            warnings.append("Performance omits binary output; validation enables it and includes buffer-write overhead. Do not pool their timings")
        warnings.append("Validation runs once per parameter configuration and seed; performance repetitions do not multiply validation")
    if refresh_performance and not resume:
        errors.append("--refresh-performance requires --resume")
    if resume and runs and not errors:
        try:
            identity = benchmark_identity(executable)
            report["benchmark_build"] = identity
            report["resume_actions"] = [resume_action(run, identity, refresh_performance) for run in runs]
        except (OSError, ValueError, TypeError, KeyError) as exc:
            errors.append(f"Resume preflight: {exc}")
    report["status"] = "invalid" if errors else "valid"
    report["benchmark_executions_performed"] = 0
    report["sample_files_created"] = 0
    return report


def parse_benchmark_stdout(stdout, run):
    """Parse the current C text format without claiming more than printed precision."""
    payloads = [line.split(": ", 1)[1] for line in stdout.splitlines() if line.startswith("BENCHMARK_JSON: ")]
    if len(payloads) > 1:
        raise ValueError("Duplicate BENCHMARK_JSON")
    if payloads:
        summary = json.loads(payloads[0])
        check_summary(summary, run)
        for key in ("algorithm", "N", "seed"):
            if summary.get(key) != run[key]:
                raise ValueError(f"JSON identity mismatch: {key}")
        if run["algorithm"] != "basic" and any(summary.get(key) != run[key] for key in ("H", "T")):
            raise ValueError("JSON refinement mismatch")
        return summary
    fields = {}
    for line in stdout.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            if key in fields:
                raise ValueError(f"Duplicate benchmark stdout field: {key}")
            fields[key] = value.strip()
    expected_configuration = f"N={run['N']}"
    if run["algorithm"] == "basic":
        expected_configuration += " (H/T not applicable)"
    else:
        expected_configuration += f" H={run['H']} T={run['T']}"
    if fields.get("Algorithm") != run["algorithm"] or fields.get("Configuration") != expected_configuration:
        raise ValueError("Benchmark stdout algorithm/configuration does not match the scheduled run")
    if fields.get("PRNG", "pcg32") != run.get("prng", "pcg32"):
        raise ValueError("Benchmark stdout PRNG does not match the scheduled run")
    if int(fields.get("Seed", "-1")) != run["seed"] or int(fields.get("Samples", "-1")) != run["samples"]:
        raise ValueError("Benchmark stdout seed/sample count does not match the scheduled run")
    mapping = {
        "sampling_time_seconds": ("Time", " s"),
        "throughput_samples_per_second": ("Samples/second", ""),
        "time_per_sample_ns": ("Time per sample", " ns"),
        "mean": ("Mean", ""), "variance": ("Variance", ""), "checksum": ("Checksum", ""),
    }
    summary = {"num_samples": run["samples"]}
    if "PRNG" in fields:
        summary["prng"] = fields["PRNG"]
    for name, (label, suffix) in mapping.items():
        value = fields.get(label)
        if value is None or (suffix and not value.endswith(suffix)):
            raise ValueError(f"Missing or malformed benchmark stdout field: {label}")
        summary[name] = float(value[:-len(suffix)] if suffix else value)
    summary.update(uniform_mode=fields.get("Uniform mode", "inline"), complete=True,
                   buffer_exhausted=False, buffer_size_bytes=0, buffer_utilization=0.0)
    if "Uniform values consumed" in fields:
        summary["uniform_values_consumed"] = int(fields["Uniform values consumed"])
        summary["uniforms_per_sample"] = summary["uniform_values_consumed"] / run["samples"]
    summary["gaussian_samples_generated"] = run["samples"]
    summary["throughput_million_samples_per_second"] = summary["throughput_samples_per_second"] / 1e6
    check_summary(summary, run)
    summary["source"] = "C stdout; values retain printed precision (time 6, moments 8 decimal places)"
    return summary


def check_summary(summary, run):
    if summary.get("complete", True) is not True or summary.get("buffer_exhausted", False):
        raise ValueError("Incomplete/exhausted benchmark is not a throughput measurement")
    if summary.get("uniform_mode", "inline") != run.get("uniform_mode", "inline"):
        raise ValueError("Summary uniform mode does not match scheduled run")
    if not isinstance(summary, dict) or type(summary.get("num_samples")) is not int or summary["num_samples"] != run["samples"]:
        raise ValueError("Invalid summary sample count")
    if summary.get("prng", "pcg32") != run.get("prng", "pcg32"):
        raise ValueError("Summary PRNG does not match the scheduled run")
    for name in ("sampling_time_seconds", "throughput_samples_per_second", "time_per_sample_ns",
                 "mean", "variance", "checksum"):
        value = summary.get(name)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"Missing or non-finite summary field: {name}")
        if name in ("sampling_time_seconds", "time_per_sample_ns", "variance") and value < 0:
            raise ValueError(f"Negative summary field: {name}")
    if summary["throughput_samples_per_second"] <= 0:
        raise ValueError("Non-positive benchmark throughput")


def collect_outputs(run, directory, stdout, *, create=True):
    printed = parse_benchmark_stdout(stdout.decode("utf-8", errors="replace"), run)
    if run["mode"] == "performance":
        if (directory / "samples.bin").exists():
            raise ValueError("Performance run unexpectedly produced binary samples")
        if create:
            write_json(directory / "summary.json", printed)
            write_json(directory / "config.json", dict(run, num_samples=run["samples"]))
        else:
            saved_summary = json.loads((directory / "summary.json").read_text())
            saved_config = json.loads((directory / "config.json").read_text())
            if saved_summary != printed:
                raise ValueError("Saved performance summary differs from captured C stdout")
            check_run_identity(saved_config, run)
        summary = printed
        comparison = None
    else:
        # These two C files are read only; execution metadata belongs in the sidecar.
        with (directory / "summary.json").open(encoding="utf-8") as stream:
            summary = json.load(stream)
        with (directory / "config.json").open(encoding="utf-8") as stream:
            configuration = json.load(stream)
        check_summary(summary, run)
        if configuration.get("uniform_mode", "inline") != run.get("uniform_mode", "inline"):
            raise ValueError("C configuration uniform mode mismatch")
        if configuration.get("prng", "pcg32") != run.get("prng", "pcg32"):
            raise ValueError("C config.json PRNG does not match the scheduled run")
        expected = {key: run[key] for key in ("algorithm", "N", "seed")}
        expected["num_samples"] = run["samples"]
        if run["algorithm"] != "basic":
            expected.update(H=run["H"], T=run["T"])
        if not isinstance(configuration, dict) or any(
            type(configuration.get(key)) is not type(value) or configuration[key] != value
            for key, value in expected.items()
        ):
            raise ValueError("C config.json does not match the scheduled run")
        comparison = binary_statistics(directory / "samples.bin", run["samples"])
        comparison.update(
            c_mean=summary["mean"], c_variance=summary["variance"],
            mean_difference=comparison["mean"] - summary["mean"],
            variance_difference=comparison["variance"] - summary["variance"],
            comparison_relative_tolerance=1e-10, comparison_absolute_tolerance=1e-10,
        )
        comparison["matches_c_summary"] = all(
            math.isclose(comparison[key], summary[key], rel_tol=1e-10, abs_tol=1e-10)
            for key in ("mean", "variance")
        )
        if not comparison["matches_c_summary"]:
            raise ValueError(f"Binary moments disagree with C summary: {comparison}")
    required = ["summary.json", "config.json", "stdout.txt", "stderr.txt"]
    if run["mode"] == "validation":
        required.append("samples.bin")
    for name in required:
        if not (directory / name).is_file():
            raise ValueError(f"Missing output file: {directory / name}")
    files = {name: {"size_bytes": (directory / name).stat().st_size,
                    "sha256": sha256_file(directory / name)} for name in required}
    return summary, comparison, files


def execute_run(run, repository, provenance, *, history=None, cache_directory=None):
    """Reserve a new directory, capture one process, and persist its final status."""
    directory = Path(run["output_directory"])
    record = dict(run, status="running", returncode=None, started_at=None, ended_at=None,
                  wall_clock_duration_seconds=None, subprocess_invocation_attempted=False,
                  provenance=provenance, attempt_history=history or [])
    owned = False
    stdout = stderr = b""
    try:
        if sha256_file(run["argv"][0]) != provenance["benchmark_sha256"]:
            raise ValueError("Benchmark executable changed before execution")
        # exist_ok=False also protects against a race after dry-run preflight.
        directory.mkdir(parents=True, exist_ok=False)
        owned = True
        write_json(directory / "execution.json", record)
        with (directory / "stdout.txt").open("xb") as stdout_file, (directory / "stderr.txt").open("xb") as stderr_file:
            record["started_at"] = datetime.now(timezone.utc).isoformat()
            record["subprocess_invocation_attempted"] = True
            write_json(directory / "execution.json", record, replace=True)
            started = time.perf_counter()
            try:
                invocation = list(run["argv"])
                if run.get("uniform_mode", "inline") == "precomputed" and cache_directory:
                    cache = Path(cache_directory) / f"{run['prng']}_{run['seed']}_{run['uniform_buffer_size_bytes']}.bin"
                    invocation += ["--uniform-buffer-cache", str(cache)]
                record["actual_argv"] = invocation
                completed = subprocess.run(invocation, cwd=repository, capture_output=True, check=False)
                stdout, stderr = completed.stdout, completed.stderr
                record["returncode"] = completed.returncode
            finally:
                record["wall_clock_duration_seconds"] = time.perf_counter() - started
                record["ended_at"] = datetime.now(timezone.utc).isoformat()
                stdout_file.write(stdout)
                stderr_file.write(stderr)
        if record["returncode"] != 0:
            raise RuntimeError(f"Benchmark exited with status {record['returncode']}: {stderr.decode('utf-8', errors='replace').strip()}")
        if sha256_file(run["argv"][0]) != provenance["benchmark_sha256"]:
            raise ValueError("Benchmark executable changed during execution; result build is uncertain")
        summary, comparison, files = collect_outputs(run, directory, stdout)
        record.update(benchmark_results=summary, binary_statistics=comparison, output_files=files,
                      status="successful")
        write_json(directory / "execution.json", record, replace=True)
    except (Exception, KeyboardInterrupt) as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        if owned:
            try:
                write_json(directory / "execution.json", record, replace=True)
            except OSError as metadata_error:
                record["metadata_error"] = str(metadata_error)
        return record
    return record


def benchmark_identity(executable):
    executable = Path(executable)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError(f"Benchmark is missing or not executable: {executable}")
    stat = executable.stat()
    return dict(path=str(executable), sha256=sha256_file(executable),
                size_bytes=stat.st_size, modified_time_ns=stat.st_mtime_ns)


def check_run_identity(saved, run):
    if not isinstance(saved, dict):
        raise ValueError("Saved run metadata must be a JSON object")
    if saved.get("uniform_mode", "inline") != run.get("uniform_mode", "inline"):
        raise ValueError("Saved run does not match the schedule: uniform_mode")
    if saved.get("prng", "pcg32") != run.get("prng", "pcg32"):
        raise ValueError("Saved run does not match the schedule: prng")
    for key in ("experiment_id", "algorithm", "N", "H", "T", "seed", "samples",
                "repetition", "mode", "argv", "command", "output_directory"):
        if type(saved.get(key)) is not type(run[key]) or saved[key] != run[key]:
            raise ValueError(f"Saved run does not match the schedule: {key}")


def verify_success(run, record):
    """Read-only verification of every required artifact, not just a status flag."""
    check_run_identity(record, run)
    if record.get("status") != "successful" or record.get("returncode") != 0:
        raise ValueError("Run is not marked successfully completed with exit code zero")
    duration = record.get("wall_clock_duration_seconds")
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
        raise ValueError("Missing/invalid execution duration")
    if not record.get("started_at") or not record.get("ended_at"):
        raise ValueError("Missing execution timestamps")
    directory = Path(run["output_directory"])
    summary, comparison, files = collect_outputs(
        run, directory, (directory / "stdout.txt").read_bytes(), create=False
    )
    if files != record.get("output_files"):
        raise ValueError("Required output file sizes/hashes differ from the successful execution record")
    if summary != record.get("benchmark_results"):
        raise ValueError("Saved benchmark results differ from summary.json")
    if comparison != record.get("binary_statistics"):
        raise ValueError("Binary statistics differ from the successful execution record")
    return record


def resume_action(run, identity, refresh_performance=False):
    directory = Path(run["output_directory"])
    if not os.path.lexists(directory):
        return dict(action="run", reason="Not started", experiment_id=run["experiment_id"])
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"Refusing to resume a link or non-directory: {directory}")
    record = None
    try:
        record = json.loads((directory / "execution.json").read_text())
        if not isinstance(record, dict):
            raise ValueError("execution.json must be an object")
    except (OSError, ValueError) as exc:
        return dict(action="retry", reason=f"Unverifiable incomplete directory: {exc}",
                    experiment_id=run["experiment_id"], prior_status="unknown")
    status = record.get("status", "unknown")
    provenance = record.get("provenance")
    old_build = provenance.get("benchmark_sha256") if isinstance(provenance, dict) else None
    base = dict(experiment_id=run["experiment_id"], prior_status=status, prior_build_sha256=old_build)
    if status != "successful":
        return dict(base, action="retry", reason=f"Prior attempt status: {status}")
    if refresh_performance and run["mode"] == "performance":
        return dict(base, action="refresh", reason="Explicit --refresh-performance; archive and regenerate")
    if old_build != identity["sha256"]:
        raise ValueError(
            f"{run['experiment_id']}: successful result build {old_build} differs from current "
            f"{identity['sha256']}. Use --resume --refresh-performance for performance runs, "
            "or a separate output_dir for validation results from another build."
        )
    try:
        verify_success(run, record)
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        return dict(base, action="retry", reason=f"Successful marker failed integrity checks: {exc}")
    return dict(base, action="skip", reason="Successful outputs and build identity verified")


def archive_attempt(run, action, identity):
    """Move the entire old directory intact; retain a separate audit manifest."""
    directory = Path(run["output_directory"])
    prior_history = []
    try:
        previous = json.loads((directory / "execution.json").read_text())
        if isinstance(previous, dict) and isinstance(previous.get("attempt_history"), list):
            prior_history = previous["attempt_history"]
    except (OSError, ValueError):
        pass
    parent = directory.parent / "_attempts" / run["experiment_id"]
    parent.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-"), dir=parent))
    archived = destination / "outputs"
    event = dict(action, archived_at=datetime.now(timezone.utc).isoformat(),
                 original_directory=str(directory), archived_directory=str(archived),
                 current_build_sha256=identity["sha256"])
    write_json(destination / "archive.json", event)
    directory.rename(archived)
    return prior_history + [event]


def execute_plan(plan, repository, config, *, resume=False, refresh_performance=False):
    """Execute or resume under an exclusive lock and persist a session report."""
    if plan["status"] != "valid":
        raise ValueError("Cannot execute an invalid dry-run plan")
    if refresh_performance and not resume:
        raise ValueError("--refresh-performance requires --resume")
    repository = Path(repository).resolve()
    output_root = Path(plan["runs"][0]["output_directory"]).parent
    output_root.mkdir(parents=True, exist_ok=True)
    with (output_root / ".runner.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another runner is active in this output directory") from exc
        with tempfile.TemporaryDirectory(prefix="grng-uniform-") as cache_directory:
            return _execute_locked(plan, repository, config, resume, refresh_performance, output_root, cache_directory)


def _execute_locked(plan, repository, config, resume, refresh_performance, output_root, cache_directory):
    identity = benchmark_identity(repository / "c/benchmark")
    # Recheck all resume decisions while holding the lock, before changing any result.
    actions = [resume_action(run, identity, refresh_performance) if resume else
               dict(action="run", reason="New execution", experiment_id=run["experiment_id"])
               for run in plan["runs"]]
    provenance = dict(benchmark_sha256=identity["sha256"], benchmark_build=identity,
                      configuration=config, python_version=sys.version,
                      working_directory=str(repository),
                      timing_note="Python wall-clock measures subprocess invocation including initialization and I/O; C sampling time is separate. Binary checks and Python file writes are outside subprocess timing.")
    report_dir = output_root / "_reports"
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex + ".json")
    report = dict(status="running", started_at=datetime.now(timezone.utc).isoformat(),
                  benchmark_build=identity, resume=resume, refresh_performance=refresh_performance,
                  scheduled_runs=len(plan["runs"]), runs=[], actions=[], errors=[],
                  warnings=[], report_file=str(report_path))
    write_json(report_path, report)
    for index, (run, planned_action) in enumerate(zip(plan["runs"], actions), 1):
        action = planned_action
        try:
            if sha256_file(repository / "c/benchmark") != identity["sha256"]:
                raise ValueError("Benchmark executable changed during this session")
            # Verify again immediately before skip/archive to detect intervening changes.
            if resume:
                action = resume_action(run, identity, refresh_performance)
            print(f"[{index}/{len(plan['runs'])}] {action['action']}: {run['experiment_id']} — {action['reason']}",
                  file=sys.stderr, flush=True)
            history = []
            if action["action"] in ("retry", "refresh"):
                history = archive_attempt(run, action, identity)
                action = dict(action, archived_directory=history[-1]["archived_directory"])
                report["warnings"].append(f"{run['experiment_id']}: {action['reason']}; preserved in {action['archived_directory']}")
            report["actions"].append(action)
            write_json(report_path, report, replace=True)
            if action["action"] == "skip":
                result = json.loads((Path(run["output_directory"]) / "execution.json").read_text())
                result["session_action"] = "skipped"
            else:
                result = execute_run(run, repository, provenance, history=history, cache_directory=cache_directory)
                result["session_action"] = "executed"
        except (Exception, KeyboardInterrupt) as exc:
            result = dict(run, status="failed", error=f"{type(exc).__name__}: {exc}", session_action="preparation_failed")
        report["runs"].append(result)
        if result["status"] != "successful":
            report["errors"].append(result["error"])
        write_json(report_path, report, replace=True)
        if result["status"] != "successful":
            break
    results = report["runs"]
    successful = sum(result["status"] == "successful" for result in results)
    failed = len(results) - successful
    report.update(status="failed" if failed else "successful", successful_runs=successful,
                  failed_runs=failed, skipped_runs=sum(r["session_action"] == "skipped" for r in results),
                  executed_runs=sum(r["session_action"] == "executed" for r in results),
                  not_started_runs=len(plan["runs"]) - len(results),
                  ended_at=datetime.now(timezone.utc).isoformat())
    report["performance_build_groups"] = {}
    for result in results:
        if result["status"] == "successful" and result["mode"] == "performance":
            build = result["provenance"]["benchmark_sha256"]
            report["performance_build_groups"].setdefault(build, []).append(result["experiment_id"])
    report["archived_failed_attempts"] = sum(
        event.get("prior_status") == "failed" for r in results for event in r.get("attempt_history", [])
    )
    write_json(report_path, report, replace=True)
    return report
