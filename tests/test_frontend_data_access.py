"""frontend/data_access.py has no Bokeh dependency (only backend/), so it
runs and is tested here even though frontend/plots.py and frontend/app.py
can't be (bokeh isn't installed in this environment -- see
frontend/README.md). These tests mirror tests/test_backend.py's
synthetic-data setup, calling the data-access functions directly instead
of through TestClient.
"""

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from frontend import data_access

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def write_history(path, venue="binance", symbol="BTCUSD", n=200, step=5, ask_base=100.0, bid_base=99.9):
    with open(path, "w") as f:
        for i in range(n):
            ts = START + timedelta(seconds=step * i)
            asks = [[ask_base + 0.02 * k, 3.0] for k in range(10)]
            bids = [[bid_base, 1_000_000.0]]
            row = {
                "venue": venue, "symbol": symbol, "timestamp": ts.isoformat(),
                "bids": bids, "asks": asks,
            }
            f.write(json.dumps(row) + "\n")


def write_regimes_csv(path, n_hours=6):
    pd.DataFrame({
        "open_time": [START + timedelta(hours=i) for i in range(n_hours)],
        "regime": ["calm"] * n_hours,
    }).to_csv(path, index=False)


def write_rewards_csv(path, rewards):
    pd.DataFrame({"episode": range(1, len(rewards) + 1), "total_reward": rewards}).to_csv(path, index=False)


def test_get_trajectory(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path)
    result = data_access.get_trajectory(
        book_history_path=str(path), side="buy", quantity=1.0, algorithm="twap", n_slices=5,
        duration_seconds=300, temporary_impact_coef=0.0, permanent_impact_coef=0.0,
    )
    assert len(result["points"]) == 6
    assert result["points"][0]["remaining_quantity"] == pytest.approx(1.0)


def test_get_backtest(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path)
    result = data_access.get_backtest(
        book_history_path=str(path), side="buy", quantity=1.0, algorithm="naive",
        duration_seconds=300, temporary_impact_coef=0.0, permanent_impact_coef=0.0,
    )
    assert result["executed_quantity"] == pytest.approx(1.0)


def test_get_experiment(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n=200, step=5)
    regimes_csv = tmp_path / "regimes.csv"
    write_regimes_csv(regimes_csv)
    results = data_access.get_experiment(
        book_history_path=str(path), side="buy", quantity=1.0, n_slices=4,
        episode_duration_seconds=60, stride_seconds=60,
        temporary_impact_coef=0.0, permanent_impact_coef=0.0,
        regimes_csv=str(regimes_csv), n_resamples=200, seed=1,
    )
    assert {"naive", "twap"}.issubset({r["scenario"] for r in results})


def test_get_calibration_comparison(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n=50, step=10)
    result = data_access.get_calibration_comparison(
        book_history_path=str(path), side="buy", ac_volatility=0.001, ac_risk_aversion=0.1,
        ac_permanent_to_temporary_ratio=0.001, ac_sqrt_law_coefficient=1.0,
        ac_reference_participation_rate=0.1, ac_empirical_order_sizes="0.1,0.5,1.0",
    )
    assert result["empirical_n_samples"] > 0


def test_get_fee_schedules():
    fees = data_access.get_fee_schedules()
    assert {f["venue"] for f in fees} == {"binance", "coinbase", "kraken"}


def test_get_venue_routing_comparison(tmp_path):
    binance_path = tmp_path / "binance.jsonl"
    coinbase_path = tmp_path / "coinbase.jsonl"
    kraken_path = tmp_path / "kraken.jsonl"
    write_history(binance_path, venue="binance", n=30, ask_base=100.05, bid_base=99.95)
    write_history(coinbase_path, venue="coinbase", n=30, ask_base=100.00, bid_base=99.90)
    write_history(kraken_path, venue="kraken", n=30, ask_base=100.02, bid_base=99.92)

    result = data_access.get_venue_routing_comparison(
        binance_book_history_path=str(binance_path),
        coinbase_book_history_path=str(coinbase_path),
        kraken_book_history_path=str(kraken_path),
        side="buy", quantity=2.0, algorithm="twap", n_slices=4,
        duration_seconds=80, temporary_impact_coef=0.0, permanent_impact_coef=0.0,
    )
    assert {s["strategy"] for s in result["strategies"]} == {
        "always_binance", "always_coinbase", "always_kraken", "best_price"
    }


def test_get_cross_venue_validation(tmp_path):
    binance_path = tmp_path / "binance.jsonl"
    coinbase_path = tmp_path / "coinbase.jsonl"
    kraken_path = tmp_path / "kraken.jsonl"
    write_history(binance_path, venue="binance", ask_base=100.05, bid_base=99.95)
    write_history(coinbase_path, venue="coinbase", ask_base=100.03, bid_base=99.93)
    write_history(kraken_path, venue="kraken", ask_base=100.02, bid_base=99.92)

    result = data_access.get_cross_venue_validation(
        binance_book_history_path=str(binance_path),
        coinbase_book_history_path=str(coinbase_path),
        kraken_book_history_path=str(kraken_path),
        side="buy", quantity=2.0, n_slices=4,
        episode_duration_seconds=60, stride_seconds=60,
        temporary_impact_coef=0.0, permanent_impact_coef=0.0,
        n_resamples=200, seed=1,
    )
    assert set(result["rankings"]) == {"binance", "coinbase", "kraken"}


def test_get_rl_diagnostics(tmp_path):
    path = tmp_path / "rewards.csv"
    write_rewards_csv(path, [-10, -8, -6, -4, -2, 0, 1, 2, 3, 4])
    result = data_access.get_rl_diagnostics(rewards_csv=str(path))
    assert result["n_episodes"] == 10
    assert result["improved"] is True


def test_missing_file_raises():
    # BookHistoryReader raises FileNotFoundError for a missing path;
    # backend.main catches (ValueError, FileNotFoundError) together and
    # turns both into HTTP 400 -- callers of data_access directly (like
    # frontend/app.py) need to catch both too.
    with pytest.raises((ValueError, FileNotFoundError)):
        data_access.get_backtest(
            book_history_path="does/not/exist.jsonl", side="buy", quantity=1.0,
            duration_seconds=300, temporary_impact_coef=0.0, permanent_impact_coef=0.0,
        )
