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
    from utils import result_paths
    paths = result_paths(config, repository)
    raw, output = paths["raw"], paths["processed"]
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


def run_tests_chunked(values, settings, tail_thresholds, *, block_size=1_000_000):
    """Full-data fixed-N(0,1) tests with one sorted copy and bounded work arrays.

    Statistics and calibrations match run_tests. No histogram approximation is
    used for KS, AD, or CvM. SciPy's CvM calibration helper is the same function
    called by scipy.stats.cramervonmises in the pinned SciPy release.
    """
    from scipy.stats import _hypotests
    values = np.asarray(values, dtype=np.float64)
    n = values.size
    if n < 2:
        raise ValueError('At least two samples are required')
    alpha = settings['significance_level']
    chi_settings = settings['chi_square']
    edges = np.r_[-np.inf, np.linspace(*chi_settings['range'], chi_settings['bins'] + 1), np.inf]
    observed = np.zeros(len(edges) - 1, dtype=np.int64)
    total = np.longdouble(0)
    tail_counts = {float(threshold): 0 for threshold in tail_thresholds}
    for begin in range(0, n, block_size):
        block = values[begin:begin + block_size]
        if not np.all(np.isfinite(block)):
            raise ValueError('Non-finite Gaussian sample')
        total += np.sum(block, dtype=np.longdouble)
        observed += np.histogram(block, bins=edges)[0]
        absolute = np.abs(block)
        for threshold in tail_counts:
            tail_counts[threshold] += int(np.count_nonzero(absolute >= threshold))
    mean = float(total / n)
    squares = np.longdouble(0)
    for begin in range(0, n, block_size):
        centered = values[begin:begin + block_size] - mean
        squares += np.sum(centered * centered, dtype=np.longdouble)
    variance = float(squares / (n - 1))

    left, right = edges[:-1], edges[1:]
    probabilities = np.where(left >= 0, stats.norm.sf(left) - stats.norm.sf(right),
                             stats.norm.cdf(right) - stats.norm.cdf(left))
    expected = n * probabilities / probabilities.sum()
    expected[np.argmax(expected)] += n - expected.sum()
    merged_o, merged_e, merged_edges = merge_adjacent_bins(
        observed, expected, edges, chi_settings['minimum_expected_count'])
    merged_e[np.argmax(merged_e)] += n - merged_e.sum()
    df = len(merged_e) - 1
    chi_stat = float(np.sum((merged_o - merged_e) ** 2 / merged_e))
    chi_p = float(stats.chi2.sf(chi_stat, df))
    chi = _test_result(chi_stat, chi_p, alpha, critical_value=stats.chi2.isf(alpha, df),
        degrees_of_freedom=df, configured_interior_bins=chi_settings['bins'],
        initial_bins=len(observed), final_bins=len(merged_e),
        observed_total=int(observed.sum()), expected_total=float(merged_e.sum()),
        outside_range_count=int(observed[0] + observed[-1]),
        method='Pearson Chi-square; fixed N(0,1), two unbounded tails and expected-count bin merging')

    ordered = np.array(values, copy=True)
    ordered.sort()
    d_plus = d_minus = 0.0
    cvm_sum = np.longdouble(0)
    ad_sum = np.longdouble(0)
    for begin in range(0, n, block_size):
        end = min(begin + block_size, n)
        x = ordered[begin:end]
        rank = np.arange(begin + 1, end + 1, dtype=np.float64)
        cdf = special.ndtr(x)
        d_plus = max(d_plus, float(np.max(rank / n - cdf)))
        d_minus = max(d_minus, float(np.max(cdf - (rank - 1) / n)))
        cvm_sum += np.sum(((rank - .5) / n - cdf) ** 2, dtype=np.longdouble)
        log_left = special.log_ndtr(x)
        # Match the original AD expression: the reverse-ordered survival term.
        reverse_x = ordered[n - end:n - begin][::-1]
        log_right = special.log_ndtr(-reverse_x)
        ad_sum += np.sum((2 * rank - 1) * (log_left + log_right), dtype=np.longdouble)
    del ordered
    ks_stat = max(d_plus, d_minus)
    ks_p = float(stats.kstwo.sf(ks_stat, n))
    cvm_stat = float(np.longdouble(1) / (12 * n) + cvm_sum)
    cvm_p = float(max(0.0, 1.0 - _hypotests._cdf_cvm(cvm_stat, n)))
    ad_stat = max(0.0, float(-n - ad_sum / n))
    ad_critical = optimize.brentq(lambda z: _ad_cdf(z, n) - (1 - alpha), 0, 50)
    ad_p = 1 - _ad_cdf(ad_stat, n)
    below_resolution = ad_p < AD_RESOLUTION
    tests = dict(
        chi_square=chi,
        kolmogorov_smirnov=_test_result(ks_stat, ks_p, alpha,
            method='Full-data two-sided KS; fixed N(0,1); scipy.stats.kstwo.sf calibration'),
        anderson_darling=_test_result(ad_stat, None if below_resolution else ad_p, alpha,
            critical_value=ad_critical, p_value_below_resolution=below_resolution,
            p_value_resolution=AD_RESOLUTION,
            method='Full-data AD; fixed N(0,1); Marsaglia-Marsaglia finite-n approximation'),
        cramer_von_mises=_test_result(cvm_stat, cvm_p, alpha,
            method='Full-data CvM; fixed N(0,1); SciPy finite-sample calibration'),
    )
    tails = []
    for threshold, count in tail_counts.items():
        empirical = count / n
        theoretical = float(2 * stats.norm.sf(threshold))
        tails.append(dict(threshold=threshold, observed_count=count,
                          empirical_probability=empirical, theoretical_probability=theoretical,
                          absolute_error=abs(empirical - theoretical),
                          relative_error=abs(empirical - theoretical) / theoretical))
    return dict(mean=mean, variance=variance, absolute_mean_error=abs(mean),
                absolute_variance_error=abs(variance - 1.0), tests=tests, tails=tails)


def validate_one_experiment01(directory, config, benchmark_sha256):
    """Validate, persist and verify all statistics before optional binary deletion."""
    from utils import write_json
    directory = Path(directory)
    execution = _read_object(directory / 'execution.json')
    summary = _read_object(directory / 'summary.json')
    c_config = _read_object(directory / 'config.json')
    sample_path = directory / 'samples.bin'
    if execution.get('status') != 'successful' or execution.get('mode') != 'validation':
        raise ValueError('Validation benchmark did not complete successfully')
    if execution.get('provenance', {}).get('benchmark_sha256') != benchmark_sha256:
        raise ValueError('Validation executable SHA-256 mismatch')
    count = config['validation']['samples']
    if c_config.get('num_samples') != count or sample_path.stat().st_size != count * 8:
        raise ValueError('Validation binary count or size mismatch')
    sample_hash = sha256_file(sample_path)
    if execution.get('output_files', {}).get('samples.bin', {}).get('sha256') != sample_hash:
        raise ValueError('Validation binary hash differs from execution manifest')
    values = np.memmap(sample_path, dtype='<f8', mode='r', shape=(count,))
    try:
        numerical = run_tests_chunked(values, validation_settings(config), config['tail_thresholds'])
    finally:
        values._mmap.close()
        del values
    for key in ('mean', 'variance'):
        if not math.isclose(numerical[key], summary[key], rel_tol=1e-10, abs_tol=1e-10):
            raise ValueError(f'Full binary {key} disagrees with C summary')
    result = dict(experiment_id=directory.name, algorithm=c_config['algorithm'],
        algorithm_label=execution.get('algorithm_label'), N=c_config['N'],
        H=c_config.get('H'), T=c_config.get('T'), seed=c_config['seed'],
        num_samples=count, benchmark_sha256=benchmark_sha256,
        sample_sha256=sample_hash, sample_size_bytes=count * 8,
        summary_sha256=sha256_file(directory / 'summary.json'),
        config_sha256=sha256_file(directory / 'config.json'),
        keep_validation_samples=config['keep_validation_samples'],
        validation_code_sha256=sha256_file(__file__),
        scipy_version=scipy.__version__, numpy_version=np.__version__,
        c_sampling_time_seconds=summary['sampling_time_seconds'], **numerical)
    sidecar = directory / 'validation_result.json'
    write_json(sidecar, result, replace=sidecar.exists())
    saved = _read_object(sidecar)
    if saved != result:
        raise ValueError('Saved validation result failed readback')
    integrity = dict(validation_result_sha256=sha256_file(sidecar),
                     verified_at=datetime.now(timezone.utc).isoformat())
    integrity_path = directory / 'validation_integrity.json'
    write_json(integrity_path, integrity, replace=integrity_path.exists())
    if _read_object(integrity_path)['validation_result_sha256'] != sha256_file(sidecar):
        raise ValueError('Saved validation integrity record failed readback')
    if not config['keep_validation_samples']:
        sample_path.unlink()
    return result
