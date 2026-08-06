"""Almgren-Chriss closed-form sanity check (testing & validation):
literature and empirical calibration come from genuinely different
sources -- an equities-literature convention vs. this project's own real
book-walk regression -- and algos/README.md already documents that their
raw eta/gamma values can diverge substantially. That divergence is an
expected, disclosed finding. What must NOT happen regardless of how much
the raw coefficients diverge is either calibration producing an insane
trajectory: negative quantities, a schedule that doesn't sum to the
parent order's quantity, or one calibration front-loading execution by
orders of magnitude more than the other for no principled reason.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from algos.almgren_chriss import AlmgrenChrissAlgorithm
from algos.impact_calibration import build_empirical_params, literature_coefficients
from backtest.book_history import BookHistoryReader
from backtest.order import ParentOrder

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def write_book_history(path, n_snapshots=5, mid=100.0, n_levels=20, level_size=1.0):
    """A simple multi-level book with a mild real price ramp per level --
    enough real depth/price variation for empirical calibration to
    produce a non-degenerate (nonzero) eta estimate."""
    levels = [[mid + 0.02 * k, level_size] for k in range(n_levels)]
    other_side = [[mid - 0.02, 1_000_000.0]]
    with open(path, "w") as f:
        for i in range(n_snapshots):
            ts = START + timedelta(hours=i)
            row = {
                "venue": "test", "symbol": "BTCUSD", "timestamp": ts.isoformat(),
                "bids": other_side, "asks": levels,
            }
            f.write(json.dumps(row) + "\n")


def assert_sane_trajectory(children, expected_total_quantity):
    assert all(c.quantity >= 0 for c in children)
    assert sum(c.quantity for c in children) == pytest.approx(expected_total_quantity)
    assert all(c.quantity == c.quantity for c in children)  # NaN check: NaN != NaN


def test_literature_and_empirical_calibrations_both_produce_sane_trajectories(tmp_path):
    path = tmp_path / "history.jsonl"
    write_book_history(path)
    book_history = BookHistoryReader.from_file(str(path))

    shared = dict(volatility=0.02, risk_aversion=0.3, permanent_to_temporary_ratio=0.001)

    lit_params = literature_coefficients(
        sqrt_law_coefficient=1.0, reference_participation_rate=0.1, **shared
    )
    emp_params, estimate = build_empirical_params(
        book_history, order_sizes=[1.0, 2.0, 5.0, 10.0], side="buy", **shared
    )
    assert estimate.temporary_impact > 0  # a real, nonzero empirical estimate was produced

    parent = ParentOrder(
        venue="test", symbol="BTCUSD", side="buy", quantity=10.0,
        start_time=START, end_time=START + timedelta(minutes=10),
    )

    lit_children = AlmgrenChrissAlgorithm(n_slices=10, params=lit_params).slice(parent)
    emp_children = AlmgrenChrissAlgorithm(n_slices=10, params=emp_params).slice(parent)

    assert_sane_trajectory(lit_children, 10.0)
    assert_sane_trajectory(emp_children, 10.0)


def test_both_calibrations_front_load_within_a_comparable_order_of_magnitude(tmp_path):
    """Both use risk_aversion > 0, so both should front-load (first slice
    at least as large as an equal share); neither calibration's degree of
    front-loading should be wildly (>100x) more extreme than the other's
    -- a sanity bound, not a claim that they must be close."""
    path = tmp_path / "history.jsonl"
    write_book_history(path)
    book_history = BookHistoryReader.from_file(str(path))

    shared = dict(volatility=0.02, risk_aversion=0.3, permanent_to_temporary_ratio=0.001)
    lit_params = literature_coefficients(
        sqrt_law_coefficient=1.0, reference_participation_rate=0.1, **shared
    )
    emp_params, _ = build_empirical_params(
        book_history, order_sizes=[1.0, 2.0, 5.0, 10.0], side="buy", **shared
    )

    parent = ParentOrder(
        venue="test", symbol="BTCUSD", side="buy", quantity=10.0,
        start_time=START, end_time=START + timedelta(minutes=10),
    )
    n_slices = 10
    equal_share = 10.0 / n_slices

    lit_children = AlmgrenChrissAlgorithm(n_slices=n_slices, params=lit_params).slice(parent)
    emp_children = AlmgrenChrissAlgorithm(n_slices=n_slices, params=emp_params).slice(parent)

    lit_front_load_ratio = lit_children[0].quantity / equal_share
    emp_front_load_ratio = emp_children[0].quantity / equal_share

    assert lit_front_load_ratio >= 1.0  # risk_aversion > 0 -> front-loaded, not back-loaded
    assert emp_front_load_ratio >= 1.0

    ratio_of_ratios = max(lit_front_load_ratio, emp_front_load_ratio) / min(
        lit_front_load_ratio, emp_front_load_ratio
    )
    assert ratio_of_ratios < 100, (
        f"literature front-load ratio {lit_front_load_ratio:.3f} and empirical "
        f"{emp_front_load_ratio:.3f} differ by more than 100x -- one calibration "
        f"is producing a qualitatively broken trajectory shape"
    )


def test_calibrations_reduce_to_twap_identically_when_risk_neutral(tmp_path):
    """Regardless of how different the two calibrations' eta/gamma are,
    both must still hit the same, already-verified risk-neutral special
    case (see tests/test_almgren_chriss.py) -- risk_aversion=0 collapses
    both to TWAP's exact schedule."""
    path = tmp_path / "history.jsonl"
    write_book_history(path)
    book_history = BookHistoryReader.from_file(str(path))

    lit_params = literature_coefficients(
        volatility=0.02, risk_aversion=0.0, sqrt_law_coefficient=1.0,
        reference_participation_rate=0.1, permanent_to_temporary_ratio=0.001,
    )
    emp_params, _ = build_empirical_params(
        book_history, order_sizes=[1.0, 2.0, 5.0, 10.0], side="buy",
        volatility=0.02, risk_aversion=0.0, permanent_to_temporary_ratio=0.001,
    )

    parent = ParentOrder(
        venue="test", symbol="BTCUSD", side="buy", quantity=10.0,
        start_time=START, end_time=START + timedelta(minutes=10),
    )
    n_slices = 5
    lit_children = AlmgrenChrissAlgorithm(n_slices=n_slices, params=lit_params).slice(parent)
    emp_children = AlmgrenChrissAlgorithm(n_slices=n_slices, params=emp_params).slice(parent)

    for lit_child, emp_child in zip(lit_children, emp_children):
        assert lit_child.quantity == pytest.approx(2.0)
        assert emp_child.quantity == pytest.approx(2.0)
        assert lit_child.timestamp == emp_child.timestamp
