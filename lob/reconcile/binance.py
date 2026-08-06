"""Binance.US diff-depth stream reconciliation.

Binance's documented procedure for building a correct local book from its
partial-depth diff stream (this is the standard algorithm published for
`<symbol>@depth`, applies unchanged on Binance.US):

  1. Open the diff-stream websocket and buffer every event (don't apply
     anything yet).
  2. Fetch a REST order book snapshot; note its `lastUpdateId`.
  3. Drop any buffered event whose `u` (final update ID) is <=
     `lastUpdateId` -- it's already reflected in the snapshot.
  4. The first event you apply must satisfy
     `U <= lastUpdateId + 1 <= u` (it "covers" the snapshot's point in time).
  5. Every event after that must have `U == previous event's u + 1`. Any
     gap means a message was missed -- stop applying, drop the local book,
     and resync from step 2.

This is meaningfully different from Coinbase (single ordered TCP stream,
no explicit sequence gap detection needed) and from Kraken (v2 book
channel ships a CRC32 checksum of the top-10 levels instead of update-ID
continuity). See lob/README.md for the side-by-side.
"""

import json
import queue
import threading
from datetime import datetime, timezone

import requests
import websocket

from lob.order_book import OrderBook

REST_URL = "https://api.binance.us/api/v3/depth"
STREAM_URL = "wss://stream.binance.us:9443/ws/{symbol}@depth"


class BinanceBookReconciler:
    def __init__(self, symbol: str, depth_limit: int = 1000):
        self.symbol = symbol.upper()
        self.depth_limit = depth_limit
        self.book = OrderBook("binance", self.symbol)
        self._buffer: "queue.Queue[dict]" = queue.Queue()
        self._synced = False
        self._last_u: int | None = None
        self._ws: websocket.WebSocketApp | None = None
        self._on_update = None  # optional callback(book) invoked after each apply

    def _fetch_snapshot(self) -> dict:
        resp = requests.get(
            REST_URL, params={"symbol": self.symbol, "limit": self.depth_limit}, timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    def _apply_event(self, event: dict) -> None:
        for price, qty in event["b"]:
            self.book.apply_level("bid", float(price), float(qty))
        for price, qty in event["a"]:
            self.book.apply_level("ask", float(price), float(qty))
        self.book.last_update_time = datetime.fromtimestamp(
            event["E"] / 1000, tz=timezone.utc
        )
        if self._on_update:
            self._on_update(self.book)

    def _resync(self) -> None:
        """Steps 2-5 above: fetch a fresh snapshot and drain whatever's
        buffered against it. If no buffered event covers the snapshot yet,
        we simply wait -- the next message will retry via `_drain`."""
        snapshot = self._fetch_snapshot()
        last_update_id = snapshot["lastUpdateId"]
        self.book.load_snapshot(
            bids=snapshot["bids"], asks=snapshot["asks"], timestamp=datetime.now(timezone.utc)
        )

        pending = []
        while not self._buffer.empty():
            pending.append(self._buffer.get())

        applied_first = False
        for event in pending:
            if event["u"] <= last_update_id:
                continue  # already reflected in the snapshot
            if not applied_first:
                if event["U"] <= last_update_id + 1 <= event["u"]:
                    self._apply_event(event)
                    self._last_u = event["u"]
                    applied_first = True
                # else: this event arrived after the snapshot's coverage
                # window with a gap before it; drop it and wait for resync.
                continue
            if event["U"] != self._last_u + 1:
                # gap mid-drain: abort, we'll resync again on the next message
                applied_first = False
                break
            self._apply_event(event)
            self._last_u = event["u"]

        self._synced = applied_first

    def _drain(self) -> None:
        if not self._synced:
            self._resync()
            return
        while not self._buffer.empty():
            event = self._buffer.get()
            if event["U"] != self._last_u + 1:
                self._synced = False
                self._resync()
                return
            self._apply_event(event)
            self._last_u = event["u"]

    def _on_message(self, _ws, message):
        self._buffer.put(json.loads(message))
        self._drain()

    def run_forever(self, on_update=None) -> None:
        """Blocking. Call from a dedicated thread if running multiple venues."""
        self._on_update = on_update
        url = STREAM_URL.format(symbol=self.symbol.lower())
        self._ws = websocket.WebSocketApp(url, on_message=self._on_message)
        self._ws.run_forever()

    def start(self, on_update=None) -> threading.Thread:
        thread = threading.Thread(
            target=self.run_forever, kwargs={"on_update": on_update}, daemon=True
        )
        thread.start()
        return thread
