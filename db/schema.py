"""Schema for the one table this project persists: real recorded order
book snapshots (the DB-backed alternative to `lob/raw/*_book_snapshots.jsonl`
-- see `lob/README.md` and `backtest/book_history.py`). Everything else
this project writes (volume/regime CSVs, RL reward logs, the trained
model checkpoint) stays flat files: small, one-shot/regenerable in
seconds from a public API or a training run, not worth a table.
"""

import psycopg

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS book_snapshots (
    id BIGSERIAL PRIMARY KEY,
    venue TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    bids JSONB NOT NULL,
    asks JSONB NOT NULL
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS book_snapshots_venue_timestamp_idx
    ON book_snapshots (venue, timestamp);
"""


def ensure_schema(conn: psycopg.Connection) -> None:
    """Idempotent -- safe to call on every connection (e.g. at the start
    of a recording run), same spirit as `lob.run_reconstruction`'s
    `os.makedirs(..., exist_ok=True)` for the file-based path."""
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
        cur.execute(CREATE_INDEX_SQL)
    conn.commit()
