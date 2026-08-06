import json

import pytest

from backtest.book_history import BookHistoryReader, open_book_history


def write_history(path, rows):
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def make_row(timestamp, bid_price=99.0, ask_price=100.0):
    return {
        "venue": "test",
        "symbol": "BTCUSD",
        "timestamp": timestamp,
        "bids": [[bid_price, 1.0]],
        "asks": [[ask_price, 1.0]],
    }


def test_book_at_or_before_returns_latest_snapshot_not_after(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(
        path,
        [
            make_row("2026-01-01T00:00:00+00:00", bid_price=99.0, ask_price=100.0),
            make_row("2026-01-01T00:01:00+00:00", bid_price=99.5, ask_price=100.5),
            make_row("2026-01-01T00:02:00+00:00", bid_price=99.8, ask_price=100.8),
        ],
    )
    reader = BookHistoryReader.from_file(str(path))

    from datetime import datetime, timezone

    book = reader.book_at_or_before(datetime(2026, 1, 1, 0, 1, 30, tzinfo=timezone.utc))
    assert book.best_bid() == 99.5  # the 00:01:00 snapshot, not 00:02:00


def test_book_at_or_before_exact_timestamp_match(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, [make_row("2026-01-01T00:00:00+00:00")])
    reader = BookHistoryReader.from_file(str(path))

    from datetime import datetime, timezone

    book = reader.book_at_or_before(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc))
    assert book.best_bid() == 99.0


def test_book_at_or_before_raises_for_timestamp_before_history(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, [make_row("2026-01-01T00:00:00+00:00")])
    reader = BookHistoryReader.from_file(str(path))

    from datetime import datetime, timezone

    with pytest.raises(ValueError):
        reader.book_at_or_before(datetime(2025, 12, 31, tzinfo=timezone.utc))


def test_empty_history_file_raises(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, [])
    with pytest.raises(ValueError):
        BookHistoryReader.from_file(str(path))


def test_start_and_end_time_properties(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(
        path,
        [
            make_row("2026-01-01T00:00:00+00:00"),
            make_row("2026-01-01T00:05:00+00:00"),
        ],
    )
    reader = BookHistoryReader.from_file(str(path))
    assert reader.start_time.isoformat() == "2026-01-01T00:00:00+00:00"
    assert reader.end_time.isoformat() == "2026-01-01T00:05:00+00:00"


def test_open_book_history_dispatches_plain_path_to_from_file(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, [make_row("2026-01-01T00:00:00+00:00")])
    reader = open_book_history(str(path))
    assert reader.venue == "test"


def test_open_book_history_dispatches_db_prefix_to_from_db(monkeypatch):
    # No real Postgres needed here -- this only checks that `open_book_history`
    # strips the "db:" prefix and routes to `from_db` correctly; the actual
    # DB round-trip is covered by tests/test_db_book_snapshots.py (which
    # needs a real reachable Postgres, unlike this offline dispatch check).
    calls = {}

    def fake_from_db(cls, venue, symbol=None, database_url=None):
        calls["venue"] = venue
        return "sentinel-reader"

    monkeypatch.setattr(BookHistoryReader, "from_db", classmethod(fake_from_db))
    result = open_book_history("db:binance")
    assert result == "sentinel-reader"
    assert calls["venue"] == "binance"
