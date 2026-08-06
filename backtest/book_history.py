"""Replay real, previously-recorded order book snapshots (lob/run_reconstruction.py
--record-depth-levels output) as a lookup by timestamp, for the order-slicing
simulator to "submit" hypothetical child orders against.
"""

import bisect
import json
from datetime import datetime

from lob.order_book import OrderBook


class BookHistoryReader:
    def __init__(self, path: str):
        self.venue = None
        self.symbol = None
        self._timestamps: list[datetime] = []
        self._records: list[dict] = []

        with open(path) as f:
            rows = [json.loads(line) for line in f if line.strip()]
        rows.sort(key=lambda r: r["timestamp"])

        for row in rows:
            ts = datetime.fromisoformat(row["timestamp"])
            self._timestamps.append(ts)
            self._records.append(row)
            self.venue = row.get("venue", self.venue)
            self.symbol = row.get("symbol", self.symbol)

        if not self._records:
            raise ValueError(f"no snapshot records found in {path}")

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
