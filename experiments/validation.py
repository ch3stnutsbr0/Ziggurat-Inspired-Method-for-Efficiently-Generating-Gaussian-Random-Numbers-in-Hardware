"""Goodness-of-fit tests for a fully specified standard normal distribution.

All tests assume independent observations. No location/scale parameters are fitted.
See VALIDATION.md for calibration, binning, multiple-testing and RNG limitations.
"""

import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import tempfile

import numpy as np
import scipy
from scipy import optimize, special, stats

from utils import sha256_file, validate_config, validation_settings

AD_REFERENCE = "https://www.jstatsoft.org/article/view/v009i02"
AD_RESOLUTION = 1e-4
ASSUMPTIONS = [
    "Null hypothesis: independent, identically distributed N(0,1) observations; no parameters estimated.",
    "These marginal-distribution tests do not establish independence, period length, unpredictability or RNG quality in general.",
    "Fail-to-reject is not proof of normality. Large samples can detect small, practically unimportant deviations.",
    "All decisions use the configured per-test alpha, without multiple-testing correction. The four tests and common-seed datasets are not independent.",
    "Chi-square uses fixed equal-width interior bins and two unbounded tails. Merging depends only on null expected counts, not observed counts.",
    "Chi-square and Cramer-von Mises calibrations are approximations. KS uses SciPy's exact finite-sample distribution method with numerical evaluation.",
    "Anderson-Darling uses the Marsaglia-Marsaglia (2004) finite-n CDF approximation after the probability integral transform; approximate p-values below 1e-4 are omitted, not reported as exact zero.",
    "Anderson-Darling calibration is less accurate for n<7; no fitted-normal Stephens correction is applied.",
    "Very small SciPy p-values can round to zero; such values are explicitly flagged and must not be interpreted as exact zero probabilities.",
    "Variance is the descriptive sample variance (ddof=1); it is not used to standardize data for any test.",
    "IEEE 754 rounding makes the data discrete; the reference distributions assume a continuous null. Data are not jittered or filtered.",
]


def _samples(values):
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 1 or values.size < 2 or not np.all(np.isfinite(values)):
        raise ValueError("Require at least two finite, one-dimensional samples; NaN/infinity are rejected")
    return values


def merge_adjacent_bins(observed, expected, edges, minimum_expected_count):
    """Pool left-to-right using expected counts only; merge the last remainder back."""
    observed = np.asarray(observed)
    expected = np.asarray(expected, dtype=float)
    edges = np.asarray(edges, dtype=float)
    if (observed.ndim != 1 or expected.shape != observed.shape or len(edges) != len(expected) + 1
            or not np.all(np.isfinite(observed)) or np.any(observed < 0)
            or not np.all(observed == np.floor(observed))
            or not np.all(np.isfinite(expected)) or np.any(expected < 0)
            or not np.all(np.diff(edges) > 0) or not math.isfinite(minimum_expected_count)
            or minimum_expected_count <= 0):
        raise ValueError("Invalid bin counts, boundaries or expected-count threshold")
    merged_o, merged_e, merged_edges = [], [], [float(edges[0])]
    count, expectation = 0, 0.0
    for index, (obs, exp) in enumerate(zip(observed, expected)):
        count += int(obs)
        expectation += float(exp)
        if expectation >= minimum_expected_count:
            merged_o.append(count)
            merged_e.append(expectation)
            merged_edges.append(float(edges[index + 1]))
            count, expectation = 0, 0.0
    if merged_edges[-1] != edges[-1]:
        if not merged_e:
            raise ValueError("Insufficient total expected count for the configured threshold")
        merged_o[-1] += count
        merged_e[-1] += expectation
        merged_edges[-1] = float(edges[-1])
    if len(merged_e) < 2:
        raise ValueError("Chi-square requires at least two final bins (positive degrees of freedom)")
    return np.asarray(merged_o, dtype=np.int64), np.asarray(merged_e), np.asarray(merged_edges)


def _test_result(statistic, p_value, alpha, *, critical_value=None, **details):
    statistic = float(statistic)
    if not math.isfinite(statistic) or statistic < 0:
        raise ValueError("Non-finite or negative test statistic")
    if p_value is not None:
        p_value = float(p_value)
        if not math.isfinite(p_value) or not 0 <= p_value <= 1:
            raise ValueError("Invalid test p-value")
    reject = statistic > critical_value if critical_value is not None else p_value < alpha
    return dict(statistic=statistic, p_value=p_value,
                critical_value=float(critical_value) if critical_value is not None else None,
                significance_level=alpha, reject=bool(reject),
                decision="reject" if reject else "fail-to-reject",
                p_value_rounded_to_zero=p_value == 0.0,
                numerical_note="Computed p-value rounded to zero; it is not mathematically zero" if p_value == 0.0 else None,
                **details)


def chi_square_test(values, settings, alpha):
    values = _samples(values)
    bins = settings["bins"]
    low, high = settings["range"]
    edges = np.r_[-np.inf, np.linspace(low, high, bins + 1), np.inf]
    observed, _ = np.histogram(values, bins=edges)
    left, right = edges[:-1], edges[1:]
    # Survival-function differences avoid cancellation in the positive tail.
    probabilities = np.where(left >= 0, stats.norm.sf(left) - stats.norm.sf(right),
                             stats.norm.cdf(right) - stats.norm.cdf(left))
    expected = values.size * probabilities / probabilities.sum()
    expected[np.argmax(expected)] += values.size - expected.sum()
    observed, expected, final_edges = merge_adjacent_bins(
        observed, expected, edges, settings["minimum_expected_count"]
    )
    expected[np.argmax(expected)] += int(observed.sum()) - expected.sum()
    if int(observed.sum()) != values.size or not np.isclose(expected.sum(), values.size, rtol=1e-14):
        raise ValueError("Chi-square bin totals do not include all samples")
    if np.any(expected < settings["minimum_expected_count"] * (1 - 1e-14)):
        raise ValueError("Merged expected counts do not satisfy the configured threshold")
    test = stats.chisquare(f_obs=observed, f_exp=expected, ddof=0)
    df = len(expected) - 1
    serial_edges = [float(x) if math.isfinite(x) else ("-inf" if x < 0 else "+inf") for x in final_edges]
    warnings = []
    if settings["minimum_expected_count"] < 5 or np.any(observed < 5):
        warnings.append("Some counts are below 5; interpret the asymptotic Chi-square calibration cautiously")
    return _test_result(test.statistic, test.pvalue, alpha,
        critical_value=stats.chi2.isf(alpha, df), degrees_of_freedom=df,
        configured_interior_bins=bins, initial_bins=bins + 2, final_bins=len(expected),
        initial_range=[low, high], minimum_expected_count=settings["minimum_expected_count"],
        observed_counts=observed.tolist(), expected_counts=expected.tolist(),
        observed_total=int(observed.sum()), expected_total=float(expected.sum()),
        final_edges=serial_edges, outside_range_count=int(np.count_nonzero((values < low) | (values > high))),
        method="scipy.stats.chisquare; df=final_bins-1; ddof=0; two explicit tail bins before merging",
        warnings=warnings)


def anderson_darling_statistic(values):
    ordered = np.sort(_samples(values))
    n = ordered.size
    weights = 2.0 * np.arange(1, n + 1) - 1.0
    # log_ndtr(-x) is log(1-Phi(x)) without subtracting rounded CDFs from 1.
    terms = weights * (special.log_ndtr(ordered) + special.log_ndtr(-ordered[::-1]))
    statistic = -n - float(np.sum(terms, dtype=np.longdouble) / n)
    if not math.isfinite(statistic):
        raise ValueError("Anderson-Darling statistic exceeds floating-point range")
    return max(0.0, statistic)


def _ad_cdf(statistic, n):
    """Marsaglia & Marsaglia (2004), short ADinf approximation plus errfix(n,x).

    Returns a lower-tail CDF, NOT an upper-tail goodness-of-fit p-value.
    Coefficients/formulas verified against the authors' AnDarl.c supplement.
    """
    z = float(statistic)
    if z <= 0:
        return 0.0
    if z > 50:
        return 1.0
    if z < 2:
        polynomial = np.polynomial.polynomial.polyval(z, [2.00012, .247105, -.0649821, .0347962, -.011672, .00168691])
        x = math.exp(-1.2337141 / z) * polynomial / math.sqrt(z)
    else:
        polynomial = np.polynomial.polynomial.polyval(z, [1.0776, -2.30695, .43424, -.082433, .008056, -.0003146])
        x = math.exp(-math.exp(polynomial))
    if x > .8:
        correction = np.polynomial.polynomial.polyval(x, [-130.2137, 745.2337, -1705.091, 1950.646, -1116.360, 255.7844]) / n
    else:
        boundary = .01265 + .1757 / n
        if x < boundary:
            t = x / boundary
            correction = math.sqrt(t) * (1 - t) * (49 * t - 102) * (.0037 / n**2 + .00078 / n + .00006) / n
        else:
            t = (x - boundary) / (.8 - boundary)
            correction = np.polynomial.polynomial.polyval(t, [-.00022633, 6.54034, -14.6538, 14.458, -8.259, 1.91864]) * (.04213 + .01365 / n) / n
    return float(np.clip(x + correction, 0, 1))


def anderson_darling_test(values, alpha):
    values = _samples(values)
    if not AD_RESOLUTION <= alpha <= 1 - AD_RESOLUTION:
        raise ValueError("Anderson-Darling alpha is outside the supported calibration resolution [1e-4, 0.9999]")
    statistic = anderson_darling_statistic(values)
    critical = optimize.brentq(lambda z: _ad_cdf(z, values.size) - (1 - alpha), 0, 50)
    p_value = 1 - _ad_cdf(statistic, values.size)
    below_resolution = p_value < AD_RESOLUTION
    return _test_result(statistic, None if below_resolution else p_value, alpha,
        critical_value=critical, p_value_below_resolution=below_resolution,
        p_value_resolution=AD_RESOLUTION,
        p_value_note="Below approximation resolution; use the statistic/critical-value decision" if below_resolution else "Approximate upper-tail p-value, not an exact probability",
        method="Fully specified null via probability integral transform; Marsaglia-Marsaglia finite-n CDF approximation",
        reference=AD_REFERENCE, warnings=["Calibration less accurate for n<7"] if values.size < 7 else [])


def run_tests(values, settings):
    values = _samples(values)
    alpha = settings["significance_level"]
    ks = stats.kstest(values, "norm", args=(0.0, 1.0), alternative="two-sided", method="exact")
    cvm = stats.cramervonmises(values, "norm", args=(0.0, 1.0))
    return {
        "chi_square": chi_square_test(values, settings["chi_square"], alpha),
        "kolmogorov_smirnov": _test_result(ks.statistic, ks.pvalue, alpha,
            method="scipy.stats.kstest; fixed N(0,1); two-sided; method=exact"),
        "anderson_darling": anderson_darling_test(values, alpha),
        "cramer_von_mises": _test_result(cvm.statistic, cvm.pvalue, alpha,
            method="scipy.stats.cramervonmises; fixed N(0,1); finite-sample approximation"),
    }



def _read_object(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def load_completed_run(directory):
    directory = Path(directory)
    execution = _read_object(directory / "execution.json")
    if (execution.get("status") != "successful" or execution.get("returncode") != 0
            or execution.get("mode") != "validation"):
        raise ValueError("Only successfully completed validation runs may be processed")
    hashes = {}
    manifest = execution.get("output_files", {})
    for name in ("samples.bin", "summary.json", "config.json"):
        file = directory / name
        if file.is_symlink() or not file.is_file():
            raise ValueError(f"Missing or linked raw input: {file}")
        digest = sha256_file(file)
        if manifest.get(name) != {"size_bytes": file.stat().st_size, "sha256": digest}:
            raise ValueError(f"Raw input integrity check failed: {file}")
        hashes[name] = digest
    configuration = _read_object(directory / "config.json")
    summary = _read_object(directory / "summary.json")
    count = configuration.get("num_samples")
    if type(count) is not int or count < 2:
        raise ValueError("config.json has an invalid sample count")
    if execution.get("samples") != count or summary.get("num_samples") != count:
        raise ValueError("Sample counts disagree between config, execution and summary")
    if execution.get("experiment_id") != directory.name:
        raise ValueError("Execution ID does not match its directory")
    algorithm = configuration.get("algorithm")
    if algorithm not in ("basic", "trapezoid"):
        raise ValueError("Unknown C algorithm in config.json")
    for key in ("algorithm", "N", "seed") + (("H", "T") if algorithm == "trapezoid" else ()):
        if configuration.get(key) != execution.get(key):
            raise ValueError(f"Run metadata disagree: {key}")
    sample_path = directory / "samples.bin"
    if sample_path.stat().st_size != count * 8:
        raise ValueError("samples.bin size does not equal config num_samples * 8")
    values = _samples(np.fromfile(sample_path, dtype="<f8"))
    if values.size != count:
        raise ValueError("Loaded sample count does not match config.json")
    hashes["execution.json"] = sha256_file(directory / "execution.json")
    metadata = dict(experiment_id=directory.name, raw_directory=str(directory),
                    algorithm=algorithm, algorithm_label=execution.get("algorithm_label", algorithm),
                    N=configuration["N"], H=configuration.get("H"), T=configuration.get("T"),
                    seed=configuration["seed"], num_samples=count,
                    mean=float(np.mean(values)), variance=float(np.var(values, ddof=1)), variance_ddof=1,
                    benchmark_sha256=execution.get("provenance", {}).get("benchmark_sha256"),
                    raw_sha256=hashes)
    comparison = {}
    for field in ("mean", "variance"):
        value = summary.get(field)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"Non-finite/missing C summary {field}")
        comparison[f"c_{field}"] = value
        comparison[f"{field}_difference"] = metadata[field] - value
        if not math.isclose(metadata[field], value, rel_tol=1e-10, abs_tol=1e-10):
            raise ValueError(f"Binary {field} disagrees with the C summary")
    metadata["summary_comparison"] = dict(comparison, matches=True, relative_tolerance=1e-10, absolute_tolerance=1e-10)
    return values, metadata


def _save_results(report, output):
    output.mkdir(parents=True, exist_ok=True)
    json_path, csv_path = output / "validation_results.json", output / "validation_results.csv"
    report["output_files"] = [str(csv_path), str(json_path)]
    columns = ["experiment_id", "algorithm", "algorithm_label", "N", "H", "T", "seed",
               "num_samples", "mean", "variance", "variance_ddof", "benchmark_sha256", "test",
               "statistic", "p_value", "critical_value", "significance_level", "reject", "decision",
               "degrees_of_freedom", "p_value_below_resolution", "p_value_resolution", "p_value_rounded_to_zero", "numerical_note"]
    staged = []
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output, delete=False) as stream:
            staged.append((Path(stream.name), json_path))
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=output, delete=False) as stream:
            staged.append((Path(stream.name), csv_path))
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            for dataset in report["datasets"]:
                for name, result in dataset["tests"].items():
                    row = dict(dataset, test=name, **result)
                    writer.writerow({key: row.get(key) for key in columns})
        for temporary, target in staged:
            os.replace(temporary, target)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def validate_existing(config, repository):
    errors = validate_config(config)
    if errors:
        raise ValueError("; ".join(errors))
    settings = validation_settings(config)
    repository = Path(repository).resolve()
    raw = Path(config.get("output_dir", "experiments/results/raw"))
    raw = (repository / raw).resolve() if not raw.is_absolute() else raw.resolve()
    output = (repository / "experiments/results/processed").resolve()
    if output.is_relative_to(raw) or raw.is_relative_to(output):
        raise ValueError("Processed output must be separate from the raw data tree")
    if not raw.is_dir():
        raise ValueError(f"Raw results directory does not exist: {raw}")
    report = dict(status="successful", created_at=datetime.now(timezone.utc).isoformat(),
                  null_distribution={"name": "normal", "mean": 0.0, "std": 1.0, "estimated_parameters": 0},
                  settings=settings, versions={"numpy": np.__version__, "scipy": scipy.__version__},
                  validation_code_sha256=sha256_file(__file__), assumptions_and_limitations=ASSUMPTIONS,
                  references=[AD_REFERENCE,
                      "https://docs.scipy.org/doc/scipy-1.13.1/reference/generated/scipy.stats.chisquare.html",
                      "https://docs.scipy.org/doc/scipy-1.13.1/reference/generated/scipy.stats.kstest.html",
                      "https://docs.scipy.org/doc/scipy-1.13.1/reference/generated/scipy.stats.cramervonmises.html"],
                  datasets=[], skipped_runs=[], errors=[], benchmark_executions_performed=0)
    # Only current run directories are inspected; archives and reports are never recursed.
    for directory in sorted(raw.iterdir()):
        if not directory.is_dir() or directory.name.startswith(("_", ".")):
            continue
        try:
            if directory.is_symlink():
                raise ValueError("Linked raw run directories are not processed")
            execution = _read_object(directory / "execution.json")
            if execution.get("mode") != "validation":
                continue
            if execution.get("status") != "successful":
                report["skipped_runs"].append(dict(experiment_id=directory.name, status=execution.get("status")))
                continue
            print(f"Validating {directory.name}", file=sys.stderr, flush=True)
            values, metadata = load_completed_run(directory)
            metadata["tests"] = run_tests(values, settings)
            # Confirm inputs did not change while validation was in progress.
            if any(sha256_file(directory / name) != digest for name, digest in metadata["raw_sha256"].items()):
                raise ValueError("Raw inputs changed during validation")
            report["datasets"].append(metadata)
        except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
            report["errors"].append(dict(experiment_id=directory.name, error=str(exc)))
    if not report["datasets"]:
        report["errors"].append(dict(error="No completed validation datasets could be processed"))
    report["status"] = "failed" if report["errors"] else "successful"
    report["datasets_validated"] = len(report["datasets"])
    report["test_count"] = 4 * len(report["datasets"])
    _save_results(report, output)
    return report
