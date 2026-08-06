from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from backtest.bootstrap import BootstrapResult
from backtest.experiment import ScenarioResult, is_robust, run_bootstrap_experiment, window_regime_labels
from rl.episodes import EpisodeWindow

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_windows(n, spacing_seconds=3600):
    return [
        EpisodeWindow(
            start_time=START + timedelta(seconds=i * spacing_seconds),
            end_time=START + timedelta(seconds=i * spacing_seconds + 60),
        )
        for i in range(n)
    ]


def test_window_regime_labels_assigns_backward_looking_label():
    windows = make_windows(3, spacing_seconds=3600)  # hours 0, 1, 2
    regimes_df = pd.DataFrame({
        "open_time": [START, START + timedelta(hours=1), START + timedelta(hours=2)],
        "regime": ["calm", "volatile", "normal"],
    })
    labels = window_regime_labels(windows, regimes_df)
    assert labels[windows[0].start_time] == "calm"
    assert labels[windows[1].start_time] == "volatile"
    assert labels[windows[2].start_time] == "normal"


def test_window_regime_labels_uses_most_recent_prior_label():
    windows = make_windows(1, spacing_seconds=0)
    late_window = [EpisodeWindow(start_time=START + timedelta(minutes=90), end_time=START + timedelta(minutes=91))]
    regimes_df = pd.DataFrame({
        "open_time": [START, START + timedelta(hours=1)],
        "regime": ["calm", "volatile"],
    })
    labels = window_regime_labels(late_window, regimes_df)
    # 90 minutes in -> most recent regime bar is the hour-1 one ("volatile")
    assert labels[late_window[0].start_time] == "volatile"


def test_run_bootstrap_experiment_without_regime_stratification():
    windows = make_windows(10)
    scenarios = {"a": lambda w: 5.0, "b": lambda w: 10.0}
    results = run_bootstrap_experiment(windows, scenarios, n_resamples=200, seed=0)

    assert {r.regime for r in results} == {"all"}
    assert {r.scenario for r in results} == {"a", "b"}
    a_result = next(r for r in results if r.scenario == "a")
    assert a_result.bootstrap.point_estimate == pytest.approx(5.0)


def test_run_bootstrap_experiment_with_regime_stratification():
    windows = make_windows(6, spacing_seconds=3600)
    # first 3 windows calm, last 3 volatile
    window_regimes = {
        windows[i].start_time: ("calm" if i < 3 else "volatile") for i in range(6)
    }

    def scenario_fn(window):
        return 1.0 if window_regimes[window.start_time] == "calm" else 100.0

    results = run_bootstrap_experiment(
        windows, {"x": scenario_fn}, window_regimes=window_regimes, n_resamples=200, seed=0
    )

    regimes_seen = {r.regime for r in results}
    assert regimes_seen == {"all", "calm", "volatile"}

    calm_result = next(r for r in results if r.regime == "calm")
    volatile_result = next(r for r in results if r.regime == "volatile")
    assert calm_result.bootstrap.point_estimate == pytest.approx(1.0)
    assert volatile_result.bootstrap.point_estimate == pytest.approx(100.0)
    assert calm_result.bootstrap.n_samples == 3
    assert volatile_result.bootstrap.n_samples == 3


def test_run_bootstrap_experiment_skips_regimes_with_too_few_windows():
    windows = make_windows(3, spacing_seconds=3600)
    window_regimes = {windows[0].start_time: "calm", windows[1].start_time: "calm", windows[2].start_time: "rare"}
    results = run_bootstrap_experiment(
        windows, {"x": lambda w: 1.0}, window_regimes=window_regimes,
        regimes_to_report=["all", "calm", "rare"], n_resamples=200, seed=0,
    )
    regimes_seen = {r.regime for r in results}
    assert "rare" not in regimes_seen  # only 1 window in "rare" -- can't bootstrap
    assert "calm" in regimes_seen


def make_result(point_estimate, ci_low, ci_high):
    return ScenarioResult(
        scenario="x", regime="all",
        bootstrap=BootstrapResult(
            point_estimate=point_estimate, ci_low=ci_low, ci_high=ci_high,
            n_samples=10, n_resamples=1000, confidence_level=0.95,
        ),
        per_window_bps=[],
    )


def test_is_robust_true_for_tight_ci():
    result = make_result(point_estimate=10.0, ci_low=9.0, ci_high=11.0)  # width=2, 20% of |mean|
    assert is_robust(result) is True


def test_is_robust_false_for_wide_ci():
    result = make_result(point_estimate=10.0, ci_low=-5.0, ci_high=25.0)  # width=30, 300% of |mean|
    assert is_robust(result) is False


def test_is_robust_handles_zero_point_estimate():
    assert is_robust(make_result(point_estimate=0.0, ci_low=0.0, ci_high=0.0)) is True
    assert is_robust(make_result(point_estimate=0.0, ci_low=-1.0, ci_high=1.0)) is False
