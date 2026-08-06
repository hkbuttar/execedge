"""Demonstrates why TWAP is a meaningfully different baseline from the
naive single-shot order, using a synthetic book history with the same
thin depth at every real timestamp.

Caveat this test also exposes (documented in backtest/README.md's Known
Limitations): the simulator replays independently-recorded real
snapshots, so it does not deplete a level for later child orders just
because an earlier one "consumed" it -- each timestamp's snapshot is
ground truth as recorded, not adjusted for the hypothetical order's own
prior fills at a different time. Repeating the identical snapshot at
every timestamp (as this test does, deliberately, to isolate the slicing
effect) is an extreme case of that: real recorded history will differ
between successive real snapshots because the market actually moved,
so this exact "free repeated liquidity" effect is a synthetic-test
artifact, not something to expect verbatim from a live recording.
"""

from datetime import datetime, timedelta, timezone

from algos.twap import TWAPAlgorithm
from backtest.algorithm import NaiveMarketOrderAlgorithm
from backtest.book_history import BookHistoryReader
from backtest.fill_model import FillModel
from backtest.order import ParentOrder
from backtest.simulator import OrderSlicingSimulator

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
THIN_ASKS = [[100.0 + i, 2.0] for i in range(5)]  # 5 levels, 2.0 depth each, 10.0 total


def write_repeated_snapshot(path, n_snapshots, interval_seconds):
    with open(path, "w") as f:
        for i in range(n_snapshots):
            ts = START + timedelta(seconds=i * interval_seconds)
            row = {
                "venue": "test", "symbol": "BTCUSD", "timestamp": ts.isoformat(),
                "bids": [[99.0, 10.0]], "asks": THIN_ASKS,
            }
            f.write(__import__("json").dumps(row) + "\n")


def test_twap_achieves_better_price_than_naive_against_thin_repeated_liquidity(tmp_path):
    path = tmp_path / "history.jsonl"
    write_repeated_snapshot(path, n_snapshots=6, interval_seconds=60)  # covers 5 minutes
    book_history = BookHistoryReader(str(path))
    fill_model = FillModel(temporary_impact_coef=0.0, permanent_impact_coef=0.0)
    simulator = OrderSlicingSimulator(book_history, fill_model)

    parent = ParentOrder(
        venue="test", symbol="BTCUSD", side="buy", quantity=10.0,
        start_time=START, end_time=START + timedelta(minutes=5),
    )

    naive_result = simulator.run(parent, NaiveMarketOrderAlgorithm())
    twap_result = simulator.run(parent, TWAPAlgorithm(n_slices=5))

    naive_avg_price = sum(f.price * f.quantity for f in naive_result.fills) / 10.0
    twap_avg_price = sum(f.price * f.quantity for f in twap_result.fills) / 10.0

    # naive walks all 5 levels of a single snapshot: avg = mean(100..104) = 102.0
    assert naive_avg_price == 102.0
    # TWAP's 2.0-sized slices each fit entirely within the top level (100.0)
    # of whichever snapshot they land on
    assert twap_avg_price == 100.0

    assert twap_result.shortfall.total_cost < naive_result.shortfall.total_cost
