"""Generic regime-stratified bootstrap experiment runner: given many real
historical windows and a set of named "scenarios" (each just a function
from a window to a resulting implementation-shortfall bps number), reports
a bootstrap CI per scenario, per regime.

Deliberately agnostic to what a "scenario" represents -- the caller
decides whether "scenario" means an algorithm, a venue-routing strategy,
a calibration source, or any combination, by writing the callable. This
is what lets one runner cover the whole "algorithm x regime x
venue-routing x calibration-source" cross-product without hardcoding any
particular axis: backtest/run_experiment.py wires up two concrete uses of
it (algorithm comparison, and venue-routing comparison) rather than a
single combinatorial grid across all four dimensions, which would
produce more rows than anyone could usefully read -- see
backtest/README.md for that scoping decision.
"""

from dataclasses import dataclass

import pandas as pd

from backtest.bootstrap import BootstrapResult, bootstrap_mean_ci

ALL_REGIME = "all"


@dataclass
class ScenarioResult:
    scenario: str
    regime: str
    bootstrap: BootstrapResult
    per_window_bps: list


def window_regime_labels(windows: list, regimes_df: pd.DataFrame) -> dict:
    """Maps each window's start_time to a regime label (calm/normal/
    volatile), via merge_asof against the regime CSV
    (data/analyze_regimes.py output, columns open_time, regime) -- the
    same join pattern as
    algos.impact_calibration.estimate_empirical_temporary_impact_per_regime.
    """
    regimes_df = regimes_df.sort_values("open_time")
    window_times = pd.DataFrame({"start_time": [w.start_time for w in windows]})
    merged = pd.merge_asof(
        window_times, regimes_df[["open_time", "regime"]],
        left_on="start_time", right_on="open_time", direction="backward",
    )
    return {window.start_time: label for window, label in zip(windows, merged["regime"])}


def run_bootstrap_experiment(
    windows: list,
    scenarios: dict,  # name -> callable(window) -> total_cost_bps
    window_regimes: dict = None,  # window.start_time -> regime label; None = no stratification
    regimes_to_report: list = None,  # default: ["all"] + every label seen in window_regimes
    n_resamples: int = 2000,
    confidence_level: float = 0.95,
    seed: int = None,
) -> list:
    if regimes_to_report is None:
        regimes_to_report = [ALL_REGIME]
        if window_regimes:
            seen = sorted({label for label in window_regimes.values() if label is not None})
            regimes_to_report += seen

    results = []
    for regime in regimes_to_report:
        if regime == ALL_REGIME:
            windows_in_regime = windows
        else:
            windows_in_regime = [w for w in windows if window_regimes.get(w.start_time) == regime]
        if len(windows_in_regime) < 2:
            continue

        for name, run_fn in scenarios.items():
            bps_values = [run_fn(window) for window in windows_in_regime]
            bootstrap = bootstrap_mean_ci(
                bps_values, n_resamples=n_resamples, confidence_level=confidence_level, seed=seed
            )
            results.append(
                ScenarioResult(scenario=name, regime=regime, bootstrap=bootstrap, per_window_bps=bps_values)
            )
    return results


def is_robust(result: ScenarioResult, relative_width_threshold: float = 0.5) -> bool:
    """A stated heuristic, not a formal significance test: "robust" means
    the CI's width is less than `relative_width_threshold` times the
    absolute point estimate -- tight relative to the effect size itself.
    Treat conclusions drawn from a "fragile" (not robust) row with real
    caution; a wide CI relative to its own point estimate means the sign
    of the effect, not just its magnitude, may not be reliable.
    """
    denom = abs(result.bootstrap.point_estimate)
    if denom == 0:
        return result.bootstrap.ci_width < 1e-9
    return result.bootstrap.ci_width < relative_width_threshold * denom
