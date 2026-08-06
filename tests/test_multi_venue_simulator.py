import json
from datetime import datetime, timedelta, timezone

import pytest

from algos.twap import TWAPAlgorithm
from backtest.book_history import BookHistoryReader
from backtest.fill_model import FillModel
from backtest.order import ParentOrder
from venues.fees import FeeSchedule
from venues.multi_venue_simulator import MultiVenueSimulator
from venues.router import BestEffectivePriceRouter, SingleVenueRouter

START = datetime(2026, 1, 1, tzinfo=timezone.utc)

FEES = {
    "binance": FeeSchedule(venue="binance", maker_fee_bps=0.0, taker_fee_bps=2.0, source="test"),
    "coinbase": FeeSchedule(venue="coinbase", maker_fee_bps=0.0, taker_fee_bps=60.0, source="test"),
    "kraken": FeeSchedule(venue="kraken", maker_fee_bps=0.0, taker_fee_bps=80.0, source="test"),
}


def write_flat_history(path, ask_price, bid_price, n_snapshots=10, interval_seconds=10):
    with open(path, "w") as f:
        for i in range(n_snapshots):
            ts = START + timedelta(seconds=i * interval_seconds)
            row = {
                "venue": "test", "symbol": "BTCUSD", "timestamp": ts.isoformat(),
                "bids": [[bid_price, 100.0]], "asks": [[ask_price, 100.0]],
            }
            f.write(json.dumps(row) + "\n")


def make_book_histories(tmp_path):
    write_flat_history(tmp_path / "binance.jsonl", ask_price=100.05, bid_price=99.95)
    write_flat_history(tmp_path / "coinbase.jsonl", ask_price=100.00, bid_price=99.90)
    write_flat_history(tmp_path / "kraken.jsonl", ask_price=100.02, bid_price=99.92)
    return {
        "binance": BookHistoryReader(str(tmp_path / "binance.jsonl")),
        "coinbase": BookHistoryReader(str(tmp_path / "coinbase.jsonl")),
        "kraken": BookHistoryReader(str(tmp_path / "kraken.jsonl")),
    }


def make_parent(quantity=5.0, duration_minutes=1, venue="binance"):
    return ParentOrder(
        venue=venue, symbol="BTCUSD", side="buy", quantity=quantity,
        start_time=START, end_time=START + timedelta(minutes=duration_minutes),
    )


def test_single_venue_router_fills_only_on_that_venue(tmp_path):
    histories = make_book_histories(tmp_path)
    simulator = MultiVenueSimulator(histories, FEES, FillModel(0.0, 0.0), SingleVenueRouter("kraken"))
    result = simulator.run(make_parent(), TWAPAlgorithm(n_slices=5))

    assert result.fills_by_venue["binance"] == []
    assert result.fills_by_venue["coinbase"] == []
    assert len(result.fills_by_venue["kraken"]) > 0
    assert all(venue == "kraken" for _, venue in result.routing_decisions)


def test_fee_is_applied_to_fill_price(tmp_path):
    histories = make_book_histories(tmp_path)
    simulator = MultiVenueSimulator(histories, FEES, FillModel(0.0, 0.0), SingleVenueRouter("kraken"))
    result = simulator.run(make_parent(), TWAPAlgorithm(n_slices=5))

    kraken_fills = result.fills_by_venue["kraken"]
    assert kraken_fills
    expected_price = 100.02 * (1 + 80.0 / 1e4)  # ask price * (1 + taker fee)
    for fill in kraken_fills:
        assert fill.price == pytest.approx(expected_price)


def test_best_price_router_beats_worst_single_venue(tmp_path):
    histories = make_book_histories(tmp_path)

    best_result = MultiVenueSimulator(
        histories, FEES, FillModel(0.0, 0.0), BestEffectivePriceRouter()
    ).run(make_parent(), TWAPAlgorithm(n_slices=5))

    worst_result = MultiVenueSimulator(
        histories, FEES, FillModel(0.0, 0.0), SingleVenueRouter("kraken")
    ).run(make_parent(), TWAPAlgorithm(n_slices=5))

    assert best_result.shortfall.total_cost_bps < worst_result.shortfall.total_cost_bps
    # given binance's much lower fee dominates its slightly worse raw price here
    assert all(venue == "binance" for _, venue in best_result.routing_decisions)


def test_arrival_and_end_price_come_from_reference_venue(tmp_path):
    histories = make_book_histories(tmp_path)
    simulator = MultiVenueSimulator(histories, FEES, FillModel(0.0, 0.0), SingleVenueRouter("binance"))

    result_binance_ref = simulator.run(make_parent(venue="binance"), TWAPAlgorithm(n_slices=5))
    assert result_binance_ref.arrival_price == pytest.approx((100.05 + 99.95) / 2)

    result_kraken_ref = simulator.run(make_parent(venue="kraken"), TWAPAlgorithm(n_slices=5))
    assert result_kraken_ref.arrival_price == pytest.approx((100.02 + 99.92) / 2)
