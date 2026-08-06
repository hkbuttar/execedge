import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.main import app

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def client():
    return TestClient(app)


def write_history(path, venue="binance", symbol="BTCUSD", n=200, step=5, ask_base=100.0, bid_base=99.9):
    with open(path, "w") as f:
        for i in range(n):
            ts = START + timedelta(seconds=step * i)
            asks = [[ask_base + 0.02 * k, 3.0] for k in range(10)]
            bids = [[bid_base - 0.02 * k, 1_000_000.0] for k in range(1)]
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


def write_volume_csv(path, n_hours=48):
    pd.DataFrame({
        "open_time": pd.date_range(START, periods=n_hours, freq="h", tz="UTC"),
        "volume": [100.0] * n_hours,
    }).to_csv(path, index=False)


def write_rewards_csv(path, rewards):
    pd.DataFrame({"episode": range(1, len(rewards) + 1), "total_reward": rewards}).to_csv(path, index=False)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_venues_fees(client):
    r = client.get("/venues/fees")
    assert r.status_code == 200
    fees = r.json()
    venues = {row["venue"] for row in fees}
    assert venues == {"binance", "coinbase", "kraken"}
    binance = next(row for row in fees if row["venue"] == "binance")
    assert binance["taker_fee_bps"] < 5.0  # the real, disclosed fee advantage


def test_backtest_twap(client, tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path)
    r = client.post("/backtest", json={
        "book_history_path": str(path),
        "side": "buy", "quantity": 1.0, "algorithm": "twap", "n_slices": 5,
        "start_offset_seconds": 0, "duration_seconds": 300,
        "temporary_impact_coef": 0.0, "permanent_impact_coef": 0.0,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["venue"] == "binance"
    assert body["executed_quantity"] == pytest.approx(1.0)
    assert body["n_child_orders"] == 5


def test_backtest_naive_default_algorithm(client, tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path)
    r = client.post("/backtest", json={
        "book_history_path": str(path),
        "side": "buy", "quantity": 1.0, "algorithm": "naive",
        "duration_seconds": 300,
        "temporary_impact_coef": 0.0, "permanent_impact_coef": 0.0,
    })
    assert r.status_code == 200
    assert r.json()["n_child_orders"] == 1


def test_backtest_missing_file_returns_400(client):
    r = client.post("/backtest", json={
        "book_history_path": "does/not/exist.jsonl",
        "side": "buy", "quantity": 1.0, "duration_seconds": 300,
        "temporary_impact_coef": 0.0, "permanent_impact_coef": 0.0,
    })
    assert r.status_code == 400


def test_backtest_ac_without_required_args_returns_400(client, tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path)
    r = client.post("/backtest", json={
        "book_history_path": str(path),
        "side": "buy", "quantity": 1.0, "algorithm": "ac",
        "duration_seconds": 300,
        "temporary_impact_coef": 0.0, "permanent_impact_coef": 0.0,
    })
    assert r.status_code == 400


def test_backtest_ac_literature(client, tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n=50, step=10)
    r = client.post("/backtest", json={
        "book_history_path": str(path),
        "side": "buy", "quantity": 1.0, "algorithm": "ac", "n_slices": 5,
        "duration_seconds": 300,
        "temporary_impact_coef": 0.0, "permanent_impact_coef": 0.0,
        "ac_calibration": "literature", "ac_volatility": 0.001, "ac_risk_aversion": 0.1,
        "ac_permanent_to_temporary_ratio": 0.001,
        "ac_sqrt_law_coefficient": 1.0, "ac_reference_participation_rate": 0.1,
    })
    assert r.status_code == 200
    assert r.json()["algorithm"] == "ac"


def test_experiment(client, tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n=200, step=5)
    regimes_csv = tmp_path / "regimes.csv"
    write_regimes_csv(regimes_csv)

    r = client.post("/experiment", json={
        "book_history_path": str(path),
        "side": "buy", "quantity": 1.0, "n_slices": 4,
        "episode_duration_seconds": 60, "stride_seconds": 60,
        "temporary_impact_coef": 0.0, "permanent_impact_coef": 0.0,
        "regimes_csv": str(regimes_csv),
        "n_resamples": 200, "seed": 1,
    })
    assert r.status_code == 200
    rows = r.json()
    scenarios = {row["scenario"] for row in rows}
    assert {"naive", "twap"}.issubset(scenarios)
    assert all("robust" in row for row in rows)


def test_experiment_too_few_windows_returns_400(client, tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n=5, step=1)  # only a few seconds of history
    r = client.post("/experiment", json={
        "book_history_path": str(path),
        "side": "buy", "quantity": 1.0,
        "episode_duration_seconds": 3600, "stride_seconds": 3600,
        "temporary_impact_coef": 0.0, "permanent_impact_coef": 0.0,
    })
    assert r.status_code == 400


def test_calibration_compare(client, tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n=50, step=10)
    r = client.post("/calibration/compare", json={
        "book_history_path": str(path),
        "side": "buy", "ac_volatility": 0.001, "ac_risk_aversion": 0.1,
        "ac_permanent_to_temporary_ratio": 0.001, "ac_sqrt_law_coefficient": 1.0,
        "ac_reference_participation_rate": 0.1, "ac_empirical_order_sizes": "0.1,0.5,1.0",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["empirical_n_samples"] > 0
    assert "temporary_impact_ratio" in body


def test_backtest_trajectory(client, tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path)
    r = client.post("/backtest/trajectory", json={
        "book_history_path": str(path),
        "side": "buy", "quantity": 1.0, "algorithm": "twap", "n_slices": 5,
        "start_offset_seconds": 0, "duration_seconds": 300,
        "temporary_impact_coef": 0.0, "permanent_impact_coef": 0.0,
    })
    assert r.status_code == 200
    body = r.json()
    points = body["points"]
    assert len(points) == 6  # start point + 5 child orders
    assert points[0]["remaining_quantity"] == pytest.approx(1.0)
    assert points[-1]["remaining_quantity"] == pytest.approx(0.0, abs=1e-6)
    # remaining quantity should be non-increasing across the trajectory
    remaining = [p["remaining_quantity"] for p in points]
    assert all(a >= b - 1e-9 for a, b in zip(remaining, remaining[1:]))


def test_venue_routing_comparison(client, tmp_path):
    binance_path = tmp_path / "binance.jsonl"
    coinbase_path = tmp_path / "coinbase.jsonl"
    kraken_path = tmp_path / "kraken.jsonl"
    write_history(binance_path, venue="binance", n=30, ask_base=100.05, bid_base=99.95)
    write_history(coinbase_path, venue="coinbase", n=30, ask_base=100.00, bid_base=99.90)
    write_history(kraken_path, venue="kraken", n=30, ask_base=100.02, bid_base=99.92)

    r = client.post("/venues/routing", json={
        "binance_book_history_path": str(binance_path),
        "coinbase_book_history_path": str(coinbase_path),
        "kraken_book_history_path": str(kraken_path),
        "side": "buy", "quantity": 2.0, "algorithm": "twap", "n_slices": 4,
        "duration_seconds": 80,
        "temporary_impact_coef": 0.0, "permanent_impact_coef": 0.0,
    })
    assert r.status_code == 200
    body = r.json()
    strategies = {s["strategy"] for s in body["strategies"]}
    assert strategies == {"always_binance", "always_coinbase", "always_kraken", "best_price"}
    assert body["best_single_venue"] in strategies
    assert isinstance(body["smart_routing_improves"], bool)


def test_venue_routing_missing_file_returns_400(client, tmp_path):
    binance_path = tmp_path / "binance.jsonl"
    write_history(binance_path, venue="binance")
    r = client.post("/venues/routing", json={
        "binance_book_history_path": str(binance_path),
        "coinbase_book_history_path": "does/not/exist.jsonl",
        "kraken_book_history_path": "does/not/exist.jsonl",
        "side": "buy", "quantity": 2.0, "duration_seconds": 80,
        "temporary_impact_coef": 0.0, "permanent_impact_coef": 0.0,
    })
    assert r.status_code == 400


def test_cross_venue_validate_consistent(client, tmp_path):
    binance_path = tmp_path / "binance.jsonl"
    coinbase_path = tmp_path / "coinbase.jsonl"
    kraken_path = tmp_path / "kraken.jsonl"
    write_history(binance_path, venue="binance", ask_base=100.05, bid_base=99.95)
    write_history(coinbase_path, venue="coinbase", ask_base=100.03, bid_base=99.93)
    write_history(kraken_path, venue="kraken", ask_base=100.02, bid_base=99.92)

    r = client.post("/venues/cross-validate", json={
        "binance_book_history_path": str(binance_path),
        "coinbase_book_history_path": str(coinbase_path),
        "kraken_book_history_path": str(kraken_path),
        "side": "buy", "quantity": 2.0, "n_slices": 4,
        "episode_duration_seconds": 60, "stride_seconds": 60,
        "temporary_impact_coef": 0.0, "permanent_impact_coef": 0.0,
        "n_resamples": 200, "seed": 1,
    })
    assert r.status_code == 200
    body = r.json()
    assert set(body["rankings"]) == {"binance", "coinbase", "kraken"}
    assert isinstance(body["consistent"], bool)


def test_rl_diagnostics(client, tmp_path):
    path = tmp_path / "rewards.csv"
    write_rewards_csv(path, [-10, -8, -6, -4, -2, 0, 1, 2, 3, 4])
    r = client.post("/rl/diagnostics", json={"rewards_csv": str(path)})
    assert r.status_code == 200
    body = r.json()
    assert body["n_episodes"] == 10
    assert body["improved"] is True


def test_rl_diagnostics_missing_file_returns_400(client):
    r = client.post("/rl/diagnostics", json={"rewards_csv": "does/not/exist.csv"})
    assert r.status_code == 400


def test_results_endpoint_serves_results_md(client):
    r = client.get("/results")
    assert r.status_code == 200
    assert len(r.text) > 0
    assert "Results" in r.text or "results" in r.text.lower()
