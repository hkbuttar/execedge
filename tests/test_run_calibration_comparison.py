import json
import sys
from datetime import datetime, timedelta, timezone

from algos.run_calibration_comparison import main

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def write_history(path, n=10):
    with open(path, "w") as f:
        for i in range(n):
            ts = START + timedelta(hours=i)
            asks = [[100.0 + 0.02 * k, 3.0] for k in range(20)]
            bids = [[99.9, 1_000_000.0]]
            row = {
                "venue": "binance", "symbol": "BTCUSDT", "timestamp": ts.isoformat(),
                "bids": bids, "asks": asks,
            }
            f.write(json.dumps(row) + "\n")


def test_cli_runs_end_to_end_and_prints_a_report(tmp_path, monkeypatch, capsys):
    path = tmp_path / "history.jsonl"
    write_history(path)

    argv = [
        "run_calibration_comparison",
        "--book-history", str(path),
        "--side", "buy",
        "--ac-volatility", "0.001",
        "--ac-risk-aversion", "0.1",
        "--ac-permanent-to-temporary-ratio", "0.01",
        "--ac-sqrt-law-coefficient", "1.0",
        "--ac-reference-participation-rate", "0.1",
        "--ac-empirical-order-sizes", "0.5,1.0,2.0",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    main()

    out = capsys.readouterr().out
    assert "temporary_impact" in out
    assert "permanent_impact" in out
    assert "binance" in out
    assert "ratio" in out.lower()
