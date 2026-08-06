"""Tests for db/ (Postgres-backed book history) and
BookHistoryReader.from_db. Needs a real reachable Postgres -- unlike
lob/reconcile's websocket-client tests (excluded from the offline run
via --ignore), this file self-skips per-test if DATABASE_URL isn't set
or the server isn't reachable, so it's always safe to collect even in
an environment without psycopg installed or a DB running.

Run against a real local Postgres with:

    docker compose up -d db
    DATABASE_URL=postgresql://execedge:execedge@localhost:5434/execedge \
        python3 -m pytest tests/test_db_book_snapshots.py -v

(matches docker-compose.yml's db service, mapped to host port 5434)
"""

from datetime import datetime, timezone

import pytest

psycopg = pytest.importorskip("psycopg")

from backtest.book_history import BookHistoryReader, open_book_history
from db.book_snapshots import fetch_snapshots, insert_snapshot
from db.connection import get_connection
from db.schema import ensure_schema


@pytest.fixture
def conn():
    try:
        connection = get_connection()
    except RuntimeError:
        pytest.skip("DATABASE_URL not set -- no Postgres to test against")
    try:
        ensure_schema(connection)
    except psycopg.OperationalError as exc:
        pytest.skip(f"could not reach Postgres: {exc}")

    with connection.cursor() as cur:
        cur.execute("DELETE FROM book_snapshots")
    connection.commit()

    yield connection
    connection.close()


def test_insert_and_fetch_round_trip(conn):
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    insert_snapshot(conn, "binance", "BTCUSD", ts, [[100.0, 1.0]], [[100.1, 1.0]])

    rows = fetch_snapshots(conn, "binance")
    assert len(rows) == 1
    assert rows[0]["venue"] == "binance"
    assert rows[0]["symbol"] == "BTCUSD"
    assert rows[0]["timestamp"] == ts.isoformat()
    assert rows[0]["bids"] == [[100.0, 1.0]]
    assert rows[0]["asks"] == [[100.1, 1.0]]


def test_fetch_orders_by_timestamp(conn):
    ts1 = datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc)
    ts2 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    insert_snapshot(conn, "binance", "BTCUSD", ts1, [[1.0, 1.0]], [[2.0, 1.0]])
    insert_snapshot(conn, "binance", "BTCUSD", ts2, [[3.0, 1.0]], [[4.0, 1.0]])

    rows = fetch_snapshots(conn, "binance")
    assert [r["timestamp"] for r in rows] == [ts2.isoformat(), ts1.isoformat()]


def test_fetch_filters_by_venue(conn):
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    insert_snapshot(conn, "binance", "BTCUSD", ts, [[1.0, 1.0]], [[2.0, 1.0]])
    insert_snapshot(conn, "coinbase", "BTC-USD", ts, [[3.0, 1.0]], [[4.0, 1.0]])

    assert len(fetch_snapshots(conn, "binance")) == 1
    assert len(fetch_snapshots(conn, "coinbase")) == 1
    assert fetch_snapshots(conn, "binance")[0]["venue"] == "binance"


def test_fetch_filters_by_symbol(conn):
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    insert_snapshot(conn, "binance", "BTCUSD", ts, [[1.0, 1.0]], [[2.0, 1.0]])
    insert_snapshot(conn, "binance", "ETHUSD", ts, [[3.0, 1.0]], [[4.0, 1.0]])

    assert len(fetch_snapshots(conn, "binance")) == 2
    rows = fetch_snapshots(conn, "binance", symbol="ETHUSD")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "ETHUSD"


def test_ensure_schema_is_idempotent(conn):
    ensure_schema(conn)
    ensure_schema(conn)  # second call must not raise


def test_book_history_reader_from_db(conn):
    ts1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ts2 = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
    insert_snapshot(conn, "kraken", "BTC/USD", ts1, [[99.0, 1.0]], [[100.0, 1.0]])
    insert_snapshot(conn, "kraken", "BTC/USD", ts2, [[99.5, 1.0]], [[100.5, 1.0]])

    reader = BookHistoryReader.from_db("kraken")
    assert len(reader) == 2
    assert reader.venue == "kraken"
    assert reader.symbol == "BTC/USD"
    assert reader.start_time == ts1
    assert reader.end_time == ts2

    book = reader.book_at_or_before(ts2)
    assert book.best_bid() == 99.5


def test_book_history_reader_from_db_raises_for_empty_venue(conn):
    with pytest.raises(ValueError):
        BookHistoryReader.from_db("nonexistent_venue")


def test_open_book_history_db_prefix_round_trip(conn):
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    insert_snapshot(conn, "binance", "BTCUSD", ts, [[1.0, 1.0]], [[2.0, 1.0]])

    reader = open_book_history("db:binance")
    assert len(reader) == 1
    assert reader.venue == "binance"
