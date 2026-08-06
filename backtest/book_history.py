"""Replay real, previously-recorded order book snapshots as a lookup by
timestamp, for the order-slicing simulator to "submit" hypothetical
child orders against. Two sources, one reader: `lob/run_reconstruction.py
--record-depth-levels` output, either as JSONL (`from_file`, the
original/default) or Postgres (`from_db`, added so a deployed instance's
book history survives an ephemeral filesystem -- see DEPLOYMENT.md and
db/README.md). Every query method below (`book_at_index`,
`book_at_or_before`, etc.) is identical either way; only construction
differs.
"""

import bisect
import json
from datetime import datetime

from lob.order_book import OrderBook


class BookHistoryReader:
    def __init__(self, rows: list[dict]):
        self.venue = None
        self.symbol = None
        self._timestamps: list[datetime] = []
        self._records: list[dict] = []

        rows = sorted(rows, key=lambda r: r["timestamp"])

        for row in rows:
            ts = datetime.fromisoformat(row["timestamp"])
            self._timestamps.append(ts)
            self._records.append(row)
            self.venue = row.get("venue", self.venue)
            self.symbol = row.get("symbol", self.symbol)

        if not self._records:
            raise ValueError("no snapshot records found")

    @classmethod
    def from_file(cls, path: str) -> "BookHistoryReader":
        with open(path) as f:
            rows = [json.loads(line) for line in f if line.strip()]
        if not rows:
            raise ValueError(f"no snapshot records found in {path}")
        return cls(rows)

    @classmethod
    def from_db(cls, venue: str, symbol: str | None = None, database_url: str | None = None) -> "BookHistoryReader":
        from db.book_snapshots import fetch_snapshots
        from db.connection import get_connection

        with get_connection(database_url) as conn:
            rows = fetch_snapshots(conn, venue, symbol)
        if not rows:
            raise ValueError(f"no snapshot records found in DB for venue={venue!r}")
        return cls(rows)

    @property
    def start_time(self) -> datetime:
        return self._timestamps[0]

    @property
    def end_time(self) -> datetime:
        return self._timestamps[-1]

    @property
    def timestamps(self) -> list[datetime]:
        return list(self._timestamps)

    def __len__(self) -> int:
        return len(self._records)

    def book_at_index(self, idx: int) -> OrderBook:
        row = self._records[idx]
        book = OrderBook(row["venue"], row["symbol"])
        book.load_snapshot(bids=row["bids"], asks=row["asks"], timestamp=self._timestamps[idx])
        return book

    def book_at_or_before(self, timestamp: datetime) -> OrderBook:
        """Real book state as of the latest recorded snapshot at or before
        `timestamp`. Raises if `timestamp` is earlier than any recorded
        history -- there's no real data to fill against, and silently
        returning an empty book would hide that instead of surfacing it."""
        idx = bisect.bisect_right(self._timestamps, timestamp) - 1
        if idx < 0:
            raise ValueError(
                f"no recorded book snapshot at or before {timestamp} "
                f"(history starts at {self.start_time})"
            )
        return self.book_at_index(idx)


def open_book_history(source: str) -> BookHistoryReader:
    """Every CLI `--book-history`/`--*-book-history` flag and every
    `*book_history_path` request field in this project accepts a plain
    filesystem path -- unchanged. Prefix it with `db:` (e.g. `db:binance`)
    and this reads that venue from Postgres instead, via `DATABASE_URL`.
    One string, one dispatch point, so every existing call site opts into
    DB-backed history with no schema/flag changes."""
    if source.startswith("db:"):
        return BookHistoryReader.from_db(venue=source[len("db:"):])
    return BookHistoryReader.from_file(source)
