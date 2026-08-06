import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from algos.twap import TWAPAlgorithm
from backtest.book_history import BookHistoryReader
from backtest.fill_model import FillModel
from backtest.order import ParentOrder
from backtest.simulator import OrderSlicingSimulator
from risk.kill_switch import KillSwitch
from risk.participation_limit import ParticipationLimiter
from risk.triggers import shortfall_trigger
from risk.volume_lookup import HistoricalVolumeLookup

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def write_history(path, n_snapshots, interval_seconds, ask_price):
    with open(path, "w") as f:
        for i in range(n_snapshots):
            ts = START + timedelta(seconds=i * interval_seconds)
            row = {
                "venue": "test", "symbol": "BTCUSD", "timestamp": ts.isoformat(),
                "bids": [[ask_price - 1.0, 1000.0]], "asks": [[ask_price, 1000.0]],
            }
            f.write(json.dumps(row) + "\n")


def make_parent(quantity=10.0, duration_minutes=10):
    return ParentOrder(
        venue="test", symbol="BTCUSD", side="buy", quantity=quantity,
        start_time=START, end_time=START + timedelta(minutes=duration_minutes),
    )


def test_no_risk_controls_behaves_as_before(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n_snapshots=11, interval_seconds=60, ask_price=100.0)
    book_history = BookHistoryReader.from_file(str(path))
    simulator = OrderSlicingSimulator(book_history, FillModel(0.0, 0.0))

    result = simulator.run(make_parent(), TWAPAlgorithm(n_slices=5))
    assert result.halted_at is None
    assert result.shortfall.executed_quantity == pytest.approx(10.0)


def test_pretripped_kill_switch_halts_before_any_fill(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n_snapshots=11, interval_seconds=60, ask_price=100.0)
    book_history = BookHistoryReader.from_file(str(path))
    kill_switch = KillSwitch()
    kill_switch.trip("pre-tripped for this test", START)

    simulator = OrderSlicingSimulator(book_history, FillModel(0.0, 0.0), kill_switch=kill_switch)
    result = simulator.run(make_parent(), TWAPAlgorithm(n_slices=5))

    assert result.fills == []
    assert result.halted_at == START  # first child order's timestamp
    assert result.shortfall.unfilled_quantity == pytest.approx(10.0)


def test_shortfall_trigger_halts_remaining_children(tmp_path):
    path = tmp_path / "history.jsonl"
    # a real, meaningfully bad ask price so the first fill alone blows
    # past a tiny shortfall threshold
    write_history(path, n_snapshots=11, interval_seconds=60, ask_price=200.0)
    book_history = BookHistoryReader.from_file(str(path))
    kill_switch = KillSwitch()

    simulator = OrderSlicingSimulator(
        book_history, FillModel(0.0, 0.0),
        kill_switch=kill_switch,
        kill_switch_triggers=[shortfall_trigger(max_cumulative_cost_bps=0.01)],
    )
    result = simulator.run(make_parent(quantity=10.0, duration_minutes=10), TWAPAlgorithm(n_slices=5))

    assert kill_switch.is_tripped is True
    assert result.halted_at is not None
    assert len(result.fills) < 5  # not all 5 child orders got to execute
    assert result.shortfall.unfilled_quantity > 0


def test_participation_limiter_caps_executed_quantity(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n_snapshots=11, interval_seconds=60, ask_price=100.0)
    book_history = BookHistoryReader.from_file(str(path))

    volume_df = pd.DataFrame({"open_time": [START], "volume": [100.0]})  # thin real volume
    volume_lookup = HistoricalVolumeLookup(volume_df, bar_seconds=3600)
    limiter = ParticipationLimiter(max_participation_rate=0.01, volume_lookup=volume_lookup)

    simulator = OrderSlicingSimulator(book_history, FillModel(0.0, 0.0), participation_limiter=limiter)
    result = simulator.run(make_parent(quantity=10.0, duration_minutes=10), TWAPAlgorithm(n_slices=5))

    # cap per 2-minute (120s) child window: 0.01 * 100 * (120/3600) ≈ 0.0333 * 5 slices
    assert result.shortfall.executed_quantity < 1.0
    assert result.shortfall.unfilled_quantity > 9.0
