from datetime import datetime, timedelta, timezone

import pytest

from algos.twap import TWAPAlgorithm
from backtest.order import ParentOrder

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_parent(duration_minutes=10, quantity=10.0, side="buy"):
    return ParentOrder(
        venue="test", symbol="BTCUSD", side=side, quantity=quantity,
        start_time=START, end_time=START + timedelta(minutes=duration_minutes),
    )


def test_slices_sum_to_parent_quantity():
    parent = make_parent(quantity=10.0)
    children = TWAPAlgorithm(n_slices=4).slice(parent)
    assert sum(c.quantity for c in children) == pytest.approx(10.0)


def test_slices_are_equal_size():
    parent = make_parent(quantity=10.0)
    children = TWAPAlgorithm(n_slices=4).slice(parent)
    assert all(c.quantity == pytest.approx(2.5) for c in children)


def test_slices_are_evenly_spaced_within_window():
    parent = make_parent(duration_minutes=10)
    children = TWAPAlgorithm(n_slices=5).slice(parent)

    assert children[0].timestamp == parent.start_time
    assert all(parent.start_time <= c.timestamp < parent.end_time for c in children)

    gaps = {children[i + 1].timestamp - children[i].timestamp for i in range(len(children) - 1)}
    assert gaps == {timedelta(minutes=2)}  # 10 minutes / 5 slices


def test_single_slice_matches_naive_style_single_order():
    parent = make_parent(quantity=10.0)
    children = TWAPAlgorithm(n_slices=1).slice(parent)
    assert len(children) == 1
    assert children[0].quantity == 10.0
    assert children[0].timestamp == parent.start_time


def test_child_orders_carry_parent_side():
    parent = make_parent(side="sell")
    children = TWAPAlgorithm(n_slices=3).slice(parent)
    assert all(c.side == "sell" for c in children)


def test_rejects_non_positive_n_slices():
    with pytest.raises(ValueError):
        TWAPAlgorithm(n_slices=0)
    with pytest.raises(ValueError):
        TWAPAlgorithm(n_slices=-1)
