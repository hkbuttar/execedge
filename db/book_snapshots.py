"""Insert/fetch for the `book_snapshots` table (see `db/schema.py`).
`fetch_snapshots` returns plain dicts shaped exactly like a parsed
`lob/raw/*_book_snapshots.jsonl` line -- `{"venue", "symbol", "timestamp"
(ISO string), "bids", "asks"}` -- so `backtest/book_history.py`'s
`BookHistoryReader` can build itself from either source through the same
row-processing code, with no branching downstream of construction.
"""

from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb


def insert_snapshot(
    conn: psycopg.Connection,
    venue: str,
    symbol: str,
    timestamp: datetime,
    bids: list,
    asks: list,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO book_snapshots (venue, symbol, timestamp, bids, asks) "
            "VALUES (%s, %s, %s, %s, %s)",
            (venue, symbol, timestamp, Jsonb(bids), Jsonb(asks)),
        )
    conn.commit()


def fetch_snapshots(conn: psycopg.Connection, venue: str, symbol: str | None = None) -> list[dict]:
    query = "SELECT venue, symbol, timestamp, bids, asks FROM book_snapshots WHERE venue = %s"
    params: list = [venue]
    if symbol is not None:
        query += " AND symbol = %s"
        params.append(symbol)
    query += " ORDER BY timestamp"

    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    return [
        {
            "venue": row[0],
            "symbol": row[1],
            "timestamp": row[2].isoformat(),
            "bids": row[3],
            "asks": row[4],
        }
        for row in rows
    ]
