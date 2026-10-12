# Statistical validation

From `experiments/`, run:

```sh
python main.py --config config.yaml --validate
```

This entry point reads existing completed validation datasets. It never invokes the
C benchmark, generates samples, or modifies raw inputs. It checks execution status,
recorded SHA-256 hashes, float64 byte count, and finite values. It examines current
run directories only, excluding `_attempts` and `_reports`.

Results go to `results/processed/validation_results.json` and
`validation_results.csv`. The CSV has one row per dataset and test; JSON also
contains bin boundaries/counts, metadata, C-summary comparisons, methods,
assumptions, software versions, raw hashes, errors and skipped runs. Rerunning
validation replaces these processed reports. A rejected null is a valid test
outcome; a malformed dataset is a processing error and produces a nonzero exit.

## Configuration

The existing benchmark settings remain under `validation`; statistical settings
are added to that same mapping:

```yaml
validation:
  enabled: true
  samples: 1000000
  significance_level: 0.05
  chi_square:
    bins: 100
    range: [-5.0, 5.0]
    minimum_expected_count: 5
```

`bins` counts equal-width interior bins. Two additional bins extend to negative
and positive infinity. The range never truncates or discards observations.
The configured sample count schedules future benchmarks; existing datasets are
validated using the sample count saved in their own `config.json`.

## Fixed null and methods

Every test uses the fully specified distribution **N(0,1)**. Descriptive sample
means and variances are reported but never used to standardize data or fit a
reference distribution. Reported variance uses `ddof=1`, matching the C summary.

- **Pearson Chi-square:** expected probabilities come from differences of the
  standard normal CDF (equivalent survival differences in the positive tail).
  Adjacent bins are pooled left-to-right until the expected count reaches the
  configured threshold; a final remainder is pooled backward. Pooling depends
  only on expected counts and sample size. All observed samples are retained.
  Floating-point normalization makes expected and observed totals agree.
  `scipy.stats.chisquare(..., ddof=0)` uses `final_bins - 1` degrees of freedom.
  Fewer than two valid final bins is an error. Low observed counts or an expected
  threshold below 5 produce a warning about the asymptotic approximation.
- **Kolmogorov-Smirnov:** `scipy.stats.kstest(x, "norm", args=(0,1),
  alternative="two-sided", method="exact")`. SciPy numerically evaluates the
  finite-sample reference distribution; no fitted-normal/Lilliefors substitution.
- **Anderson-Darling:** the ordered-sample statistic is
  `A² = -n - sum((2i-1) * (log(Phi(x_i)) + log(1-Phi(x_(n+1-i)))))/n`.
  `scipy.special.log_ndtr(x)` and `log_ndtr(-x)` keep extreme-tail calculations
  stable. The probability integral transform gives the fully specified uniform
  null. Calibration uses Marsaglia and Marsaglia's (2004) short limiting-CDF
  approximation plus finite-n correction. The upper-tail p-value is **1-CDF**.
  Critical values are obtained by numerical inversion of that CDF. No
  estimated-normal parameter correction or `scipy.stats.anderson` is used.
  Calibration p-values are approximate, at roughly four-digit accuracy; values
  below `1e-4` are left blank/null with a resolution flag. This is not a rigorous
  probability bound. Decisions use the statistic and calibrated critical value.
  Supported alpha is `[1e-4, 0.9999]`; calibration is less accurate for `n < 7`.
- **Cramér-von Mises:** `scipy.stats.cramervonmises(x, "norm", args=(0,1))`, using
  SciPy's simple-null finite-sample p-value approximation.

## Interpretation and limitations

The tests assume independent observations from a continuous distribution. They
check marginal distributional fit, not serial independence, cryptographic
security, period, or all aspects of RNG quality. Finite-precision samples are
not strictly continuous. Values are not jittered, filtered, or winsorized.

Very small SciPy p-values can round to zero. JSON and CSV flag those values as
numerical zeros, not mathematically zero probabilities.

Each decision uses the configured per-test significance level. No adjustment is
made for the twelve comparisons, and tests on the same dataset are dependent.
Common seeds also do not create independent replicates across algorithms.
Failing to reject does not prove exact normality. With one million observations,
small distributional departures may become detectable. Differences between
recomputed moments and C summaries are checked with absolute/relative tolerance
`1e-10`; these checks are separate from the hypothesis tests.

## Verification

```sh
python -B -m unittest discover -s experiments/tests -v
```

Run this command from the repository root. Tests cover bin totals, tails,
zero-expected bins, exact thresholds, trailing remainders, insufficient bins,
nonfinite data, incomplete files, fixed-null shift/scale alternatives, extreme
AD tails, published-reference CDF values, a seeded uniform-null calibration
check, and validation-only CLI routing. The reference coefficients were also
checked directly against the authors' `AnDarl.c` supplement. No C benchmark is
run by this test suite.

## References

- [Marsaglia & Marsaglia (2004), Evaluating the Anderson-Darling Distribution](https://www.jstatsoft.org/article/view/v009i02)
- [SciPy 1.13.1: chisquare](https://docs.scipy.org/doc/scipy-1.13.1/reference/generated/scipy.stats.chisquare.html)
- [SciPy 1.13.1: kstest](https://docs.scipy.org/doc/scipy-1.13.1/reference/generated/scipy.stats.kstest.html)
- [SciPy 1.13.1: cramervonmises](https://docs.scipy.org/doc/scipy-1.13.1/reference/generated/scipy.stats.cramervonmises.html)
