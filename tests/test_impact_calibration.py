import json
import math
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from algos.impact_calibration import (
    build_empirical_params,
    compare_calibrations,
    estimate_empirical_temporary_impact,
    estimate_empirical_temporary_impact_per_regime,
    literature_coefficients,
)
from backtest.book_history import BookHistoryReader

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def write_linear_impact_snapshot(path, n_snapshots, eta_true, mid=100.0, n_levels=20, level_size=1.0, side="ask"):
    """Each snapshot has `n_levels` equal-size levels whose price at level k
    is exactly what a continuous linear-impact ramp would be at that
    level's depth-interval midpoint. Consuming k whole levels then has a
    known closed-form average slippage of eta_true * (k/n_levels) / 2 --
    see tests/test_impact_calibration.py's module docstring derivation.

    The opposite side is placed symmetrically around `mid` (same distance
    below `mid` as the first level is above it) so book.mid_price() -- what
    estimate_empirical_temporary_impact actually measures slippage against
    -- comes out to exactly `mid`, matching the derivation below precisely
    rather than approximately.
    """
    total_depth = n_levels * level_size
    levels = [
        [mid * (1 + eta_true * (k + 0.5) * level_size / total_depth), level_size]
        for k in range(n_levels)
    ]
    first_level_offset = levels[0][0] - mid
    other_side_price = mid - first_level_offset
    other_side = [[other_side_price, 1_000_000.0]]  # deep, irrelevant far touch

    with open(path, "w") as f:
        for i in range(n_snapshots):
            ts = START + timedelta(hours=i)
            row = {
                "venue": "test", "symbol": "BTCUSD", "timestamp": ts.isoformat(),
                "bids": other_side if side == "ask" else levels,
                "asks": levels if side == "ask" else other_side,
            }
            f.write(json.dumps(row) + "\n")


def test_empirical_temporary_impact_recovers_known_linear_law(tmp_path):
    eta_true = 0.10
    path = tmp_path / "history.jsonl"
    write_linear_impact_snapshot(path, n_snapshots=3, eta_true=eta_true)
    book_history = BookHistoryReader.from_file(str(path))

    order_sizes = list(range(1, 11))  # exact multiples of level_size=1.0
    estimate = estimate_empirical_temporary_impact(book_history, order_sizes, side="buy")

    # closed-form: consuming k whole equal-size levels of a linear-ramp
    # book averages to eta_true * participation / 2 exactly (zero noise)
    assert estimate.temporary_impact == pytest.approx(eta_true / 2, rel=1e-9)
    assert estimate.r_squared == pytest.approx(1.0, abs=1e-9)
    assert estimate.n_samples == 3 * 10


def test_per_regime_estimation_separates_calm_and_volatile():
    import json as _json

    def write_mixed_history(path):
        calm_levels = [[100.0 * (1 + 0.02 * (k + 0.5) / 10), 1.0] for k in range(10)]
        volatile_levels = [[100.0 * (1 + 0.20 * (k + 0.5) / 10), 1.0] for k in range(10)]
        # symmetric bid around 100.0 so book.mid_price() == 100.0 exactly,
        # matching the closed-form derivation precisely (see
        # write_linear_impact_snapshot's docstring for why this matters)
        calm_bid = [[200.0 - calm_levels[0][0], 1_000_000.0]]
        volatile_bid = [[200.0 - volatile_levels[0][0], 1_000_000.0]]
        with open(path, "w") as f:
            for i in range(2):  # hours 0, 1 -> calm
                row = {
                    "venue": "test", "symbol": "BTCUSD",
                    "timestamp": (START + timedelta(hours=i)).isoformat(),
                    "bids": calm_bid, "asks": calm_levels,
                }
                f.write(_json.dumps(row) + "\n")
            for i in range(2, 4):  # hours 2, 3 -> volatile
                row = {
                    "venue": "test", "symbol": "BTCUSD",
                    "timestamp": (START + timedelta(hours=i)).isoformat(),
                    "bids": volatile_bid, "asks": volatile_levels,
                }
                f.write(_json.dumps(row) + "\n")

    import tempfile, os
    tmp_dir = tempfile.mkdtemp()
    path = os.path.join(tmp_dir, "history.jsonl")
    write_mixed_history(path)
    book_history = BookHistoryReader.from_file(path)

    regimes_df = pd.DataFrame({
        "open_time": [START, START + timedelta(hours=1), START + timedelta(hours=2), START + timedelta(hours=3)],
        "regime": ["calm", "calm", "volatile", "volatile"],
    })

    order_sizes = list(range(1, 11))
    results = estimate_empirical_temporary_impact_per_regime(book_history, regimes_df, order_sizes, side="buy")

    assert set(results) == {"calm", "volatile"}
    assert results["calm"].temporary_impact == pytest.approx(0.02 / 2, rel=1e-9)
    assert results["volatile"].temporary_impact == pytest.approx(0.20 / 2, rel=1e-9)
    assert results["volatile"].temporary_impact > results["calm"].temporary_impact


def test_literature_coefficients_formula():
    params = literature_coefficients(
        volatility=0.05, risk_aversion=0.1, sqrt_law_coefficient=1.0,
        reference_participation_rate=0.25, permanent_to_temporary_ratio=0.1,
    )
    expected_eta = 1.0 * 0.05 / math.sqrt(0.25)
    assert params.temporary_impact == pytest.approx(expected_eta)
    assert params.permanent_impact == pytest.approx(0.1 * expected_eta)
    assert params.volatility == 0.05
    assert params.risk_aversion == 0.1


def test_literature_coefficients_rejects_non_positive_reference_rate():
    with pytest.raises(ValueError):
        literature_coefficients(
            volatility=0.05, risk_aversion=0.1, sqrt_law_coefficient=1.0,
            reference_participation_rate=0.0, permanent_to_temporary_ratio=0.1,
        )


def test_build_empirical_params_uses_ratio_for_gamma(tmp_path):
    path = tmp_path / "history.jsonl"
    write_linear_impact_snapshot(path, n_snapshots=2, eta_true=0.10)
    book_history = BookHistoryReader.from_file(str(path))

    params, estimate = build_empirical_params(
        book_history, order_sizes=list(range(1, 11)), side="buy",
        volatility=0.05, risk_aversion=0.2, permanent_to_temporary_ratio=0.1,
    )
    assert params.temporary_impact == estimate.temporary_impact
    assert params.permanent_impact == pytest.approx(0.1 * estimate.temporary_impact)
    assert params.volatility == 0.05
    assert params.risk_aversion == 0.2


def test_compare_calibrations_ratios():
    from algos.almgren_chriss import AlmgrenChrissParams

    literature = AlmgrenChrissParams(
        temporary_impact=0.01, permanent_impact=0.001, volatility=0.05, risk_aversion=0.1
    )
    empirical = AlmgrenChrissParams(
        temporary_impact=0.02, permanent_impact=0.002, volatility=0.05, risk_aversion=0.1
    )
    comparison = compare_calibrations(literature, empirical)
    assert comparison["temporary_impact_ratio"] == pytest.approx(2.0)
    assert comparison["permanent_impact_ratio"] == pytest.approx(2.0)
