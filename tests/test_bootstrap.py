import numpy as np
import pytest

from backtest.bootstrap import bootstrap_mean_ci


def test_raises_with_fewer_than_two_samples():
    with pytest.raises(ValueError):
        bootstrap_mean_ci([1.0])
    with pytest.raises(ValueError):
        bootstrap_mean_ci([])


def test_point_estimate_is_sample_mean():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = bootstrap_mean_ci(values, n_resamples=500, seed=0)
    assert result.point_estimate == pytest.approx(3.0)


def test_ci_bounds_bracket_the_point_estimate():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 100.0]  # skewed
    result = bootstrap_mean_ci(values, n_resamples=1000, seed=1)
    assert result.ci_low <= result.point_estimate <= result.ci_high


def test_ci_recovers_a_known_true_mean():
    rng = np.random.default_rng(123)
    true_mean = 10.0
    sample = rng.normal(loc=true_mean, scale=2.0, size=200).tolist()
    result = bootstrap_mean_ci(sample, n_resamples=2000, seed=7)
    assert result.ci_low < true_mean < result.ci_high


def test_larger_sample_gives_narrower_ci():
    rng = np.random.default_rng(42)
    small_sample = rng.normal(loc=5.0, scale=3.0, size=10).tolist()
    large_sample = rng.normal(loc=5.0, scale=3.0, size=500).tolist()

    small_result = bootstrap_mean_ci(small_sample, n_resamples=2000, seed=1)
    large_result = bootstrap_mean_ci(large_sample, n_resamples=2000, seed=1)

    assert large_result.ci_width < small_result.ci_width


def test_lower_confidence_level_gives_narrower_ci():
    rng = np.random.default_rng(5)
    sample = rng.normal(loc=0.0, scale=1.0, size=200).tolist()

    ci_95 = bootstrap_mean_ci(sample, n_resamples=2000, confidence_level=0.95, seed=1)
    ci_50 = bootstrap_mean_ci(sample, n_resamples=2000, confidence_level=0.50, seed=1)

    assert ci_50.ci_width < ci_95.ci_width


def test_same_seed_is_reproducible():
    values = [1.0, 5.0, 3.0, 9.0, 2.0]
    a = bootstrap_mean_ci(values, n_resamples=500, seed=99)
    b = bootstrap_mean_ci(values, n_resamples=500, seed=99)
    assert a.ci_low == b.ci_low
    assert a.ci_high == b.ci_high


def test_zero_variance_sample_gives_degenerate_ci():
    result = bootstrap_mean_ci([7.0, 7.0, 7.0, 7.0], n_resamples=500, seed=0)
    assert result.point_estimate == 7.0
    assert result.ci_low == pytest.approx(7.0)
    assert result.ci_high == pytest.approx(7.0)
