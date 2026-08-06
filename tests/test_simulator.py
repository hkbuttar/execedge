import json
from datetime import datetime, timedelta, timezone

from backtest.algorithm import NaiveMarketOrderAlgorithm
from backtest.book_history import BookHistoryReader
from backtest.fill_model import FillModel
from backtest.order import ParentOrder
from backtest.simulator import OrderSlicingSimulator

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def write_history(path, rows):
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def make_row(ts, bid_price, ask_price):
    return {
        "venue": "test",
        "symbol": "BTCUSD",
        "timestamp": ts.isoformat(),
        "bids": [[bid_price, 5.0]],
        "asks": [[ask_price, 5.0]],
    }


def test_naive_algorithm_end_to_end_no_impact(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(
        path,
        [
            make_row(START, 99.0, 100.0),
            make_row(START + timedelta(minutes=5), 99.0, 100.0),
        ],
    )
    book_history = BookHistoryReader(str(path))
    fill_model = FillModel(temporary_impact_coef=0.0, permanent_impact_coef=0.0)
    simulator = OrderSlicingSimulator(book_history, fill_model)

    parent = ParentOrder(
        venue="test", symbol="BTCUSD", side="buy", quantity=2.0,
        start_time=START, end_time=START + timedelta(minutes=5),
    )
    result = simulator.run(parent, NaiveMarketOrderAlgorithm())

    assert result.arrival_price == 99.5  # mid at start
    assert len(result.fills) == 1
    assert result.fills[0].price == 100.0  # walked the single ask level, no impact
    assert result.shortfall.executed_quantity == 2.0
    assert result.shortfall.unfilled_quantity == 0.0
    assert result.shortfall.total_cost == (100.0 - 99.5) * 2.0


def test_naive_algorithm_partial_fill_charges_opportunity_cost(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(
        path,
        [
            make_row(START, 99.0, 100.0),
            make_row(START + timedelta(minutes=5), 99.0, 102.0),  # price moved against a buy
        ],
    )
    book_history = BookHistoryReader(str(path))
    fill_model = FillModel(temporary_impact_coef=0.0, permanent_impact_coef=0.0)
    simulator = OrderSlicingSimulator(book_history, fill_model)

    parent = ParentOrder(
        venue="test", symbol="BTCUSD", side="buy", quantity=10.0,  # exceeds the 5.0 visible depth
        start_time=START, end_time=START + timedelta(minutes=5),
    )
    result = simulator.run(parent, NaiveMarketOrderAlgorithm())

    assert result.shortfall.executed_quantity == 5.0
    assert result.shortfall.unfilled_quantity == 5.0
    assert result.shortfall.opportunity_cost > 0  # end price (mid 100.5) rose above arrival (99.5)
