from datetime import datetime, timedelta, timezone

import pytest

from algos.twap import TWAPAlgorithm
from algos.vwap import VWAPAlgorithm
from backtest.order import ParentOrder

START = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)  # hour 0
FLAT_WEIGHTS = {h: 1 / 24 for h in range(24)}


def make_parent(duration_hours=4, quantity=24.0, side="buy"):
    return ParentOrder(
        venue="test", symbol="BTCUSD", side=side, quantity=quantity,
        start_time=START, end_time=START + timedelta(hours=duration_hours),
    )


def test_flat_weights_match_twap_exactly():
    parent = make_parent(duration_hours=4, quantity=24.0)
    vwap_children = VWAPAlgorithm(n_slices=4, hourly_weights=FLAT_WEIGHTS).slice(parent)
    twap_children = TWAPAlgorithm(n_slices=4).slice(parent)

    assert [c.quantity for c in vwap_children] == pytest.approx([c.quantity for c in twap_children])
    assert [c.timestamp for c in vwap_children] == [c.timestamp for c in twap_children]


def test_skewed_weights_produce_proportional_sizing():
    weights = dict(FLAT_WEIGHTS)
    weights[0] = 0.5  # hour 0 gets half of all volume
    remaining = 0.5 / 23
    for h in range(1, 24):
        weights[h] = remaining

    parent = make_parent(duration_hours=4, quantity=24.0)  # slices land on hours 0,1,2,3
    children = VWAPAlgorithm(n_slices=4, hourly_weights=weights).slice(parent)

    assert children[0].quantity > children[1].quantity
    assert children[0].quantity > children[2].quantity
    assert children[0].quantity > children[3].quantity


def test_quantities_sum_to_parent_quantity():
    weights = dict(FLAT_WEIGHTS)
    weights[2] = 0.3
    weights[0] = 0.05
    parent = make_parent(duration_hours=4, quantity=24.0)
    children = VWAPAlgorithm(n_slices=4, hourly_weights=weights).slice(parent)
    assert sum(c.quantity for c in children) == pytest.approx(24.0)


def test_within_single_hour_window_is_effectively_flat():
    weights = dict(FLAT_WEIGHTS)
    weights[0] = 0.9  # would matter if hour 0 vs other hours were in play
    weights_other = {h: (0.1 / 23 if h != 0 else 0.9) for h in range(24)}

    parent = ParentOrder(
        venue="test", symbol="BTCUSD", side="buy", quantity=10.0,
        start_time=START, end_time=START + timedelta(minutes=30),  # all within hour 0
    )
    children = VWAPAlgorithm(n_slices=5, hourly_weights=weights_other).slice(parent)
    # every slice lands in hour 0, so weights cancel out -> equal sizing
    assert all(c.quantity == pytest.approx(2.0) for c in children)


def test_rejects_incomplete_weight_mapping():
    incomplete = {h: 1 / 23 for h in range(23)}  # missing hour 23
    with pytest.raises(ValueError):
        VWAPAlgorithm(n_slices=4, hourly_weights=incomplete)


def test_rejects_non_positive_n_slices():
    with pytest.raises(ValueError):
        VWAPAlgorithm(n_slices=0, hourly_weights=FLAT_WEIGHTS)
