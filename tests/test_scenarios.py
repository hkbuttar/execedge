import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from backtest.book_history import BookHistoryReader
from backtest.fill_model import FillModel
from backtest.scenarios import build_algorithm_scenarios

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def write_history(path, venue="binance", symbol="BTCUSD", n=20, step=5):
    with open(path, "w") as f:
        for i in range(n):
            ts = START + timedelta(seconds=step * i)
            row = {
                "venue": venue, "symbol": symbol, "timestamp": ts.isoformat(),
                "bids": [[99.9, 5.0]], "asks": [[100.0, 5.0]],
            }
            f.write(json.dumps(row) + "\n")


def test_naive_and_twap_always_included(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path)
    book_history = BookHistoryReader(str(path))
    scenarios = build_algorithm_scenarios(
        book_history, FillModel(0.0, 0.0), "buy", 1.0, n_slices=5, quiet=True
    )
    assert "naive" in scenarios
    assert "twap" in scenarios


def test_vwap_included_when_volume_csv_given(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path)
    book_history = BookHistoryReader(str(path))

    volume_csv = tmp_path / "volume.csv"
    pd.DataFrame({
        "open_time": pd.date_range(START, periods=48, freq="h", tz="UTC"),
        "volume": [100.0] * 48,
    }).to_csv(volume_csv, index=False)

    scenarios = build_algorithm_scenarios(
        book_history, FillModel(0.0, 0.0), "buy", 1.0, n_slices=5,
        volume_csv=str(volume_csv), quiet=True,
    )
    assert "vwap" in scenarios


def test_vwap_excluded_when_no_volume_data(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path)
    book_history = BookHistoryReader(str(path))
    scenarios = build_algorithm_scenarios(
        book_history, FillModel(0.0, 0.0), "buy", 1.0, n_slices=5,
        volume_csv=str(tmp_path / "does_not_exist.csv"), quiet=True,
    )
    assert "vwap" not in scenarios


def test_ac_scenarios_excluded_without_base_ac_args(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path)
    book_history = BookHistoryReader(str(path))
    scenarios = build_algorithm_scenarios(
        book_history, FillModel(0.0, 0.0), "buy", 1.0, n_slices=5, quiet=True
    )
    assert "ac_literature" not in scenarios
    assert "ac_empirical" not in scenarios


def test_ac_literature_included_with_full_args(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path)
    book_history = BookHistoryReader(str(path))
    scenarios = build_algorithm_scenarios(
        book_history, FillModel(0.0, 0.0), "buy", 1.0, n_slices=5,
        ac_volatility=0.001, ac_risk_aversion=0.1, ac_permanent_to_temporary_ratio=0.001,
        ac_sqrt_law_coefficient=1.0, ac_reference_participation_rate=0.1,
        quiet=True,
    )
    assert "ac_literature" in scenarios
    assert "ac_empirical" not in scenarios


def test_ac_empirical_included_with_order_sizes(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path)
    book_history = BookHistoryReader(str(path))
    scenarios = build_algorithm_scenarios(
        book_history, FillModel(0.0, 0.0), "buy", 1.0, n_slices=5,
        ac_volatility=0.001, ac_risk_aversion=0.1, ac_permanent_to_temporary_ratio=0.001,
        ac_empirical_order_sizes="0.5,1.0,2.0",
        quiet=True,
    )
    assert "ac_empirical" in scenarios


def test_scenario_callables_produce_a_finite_bps_number(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n=20, step=30)  # spans 10 minutes
    book_history = BookHistoryReader(str(path))
    scenarios = build_algorithm_scenarios(
        book_history, FillModel(0.0, 0.0), "buy", 1.0, n_slices=5, quiet=True
    )

    from rl.episodes import EpisodeWindow
    window = EpisodeWindow(start_time=book_history.start_time, end_time=book_history.start_time + timedelta(minutes=5))

    for name, run_fn in scenarios.items():
        bps = run_fn(window)
        assert bps == bps  # not NaN
        assert isinstance(bps, float)
