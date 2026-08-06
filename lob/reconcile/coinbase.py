"""Coinbase Exchange `level2` channel reconciliation.

Unlike Binance, Coinbase doesn't expose an explicit sequence/update-ID for
gap detection on this channel: the feed is a single ordered websocket
connection that first sends one `snapshot` message (full book), then a
stream of `l2update` messages (changed levels only), and message order is
guaranteed by the connection itself. There is nothing to reconcile against
a separately-fetched REST snapshot -- the snapshot comes from the same
socket. The only failure mode worth handling is a dropped connection, in
which case we just resubscribe and take the fresh `snapshot` message that
arrives, discarding the old book.
"""

import json
import threading
import time
from datetime import datetime, timezone

import websocket

from lob.order_book import OrderBook

WS_URL = "wss://ws-feed.exchange.coinbase.com"


class CoinbaseBookReconciler:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.book = OrderBook("coinbase", symbol)
        self._ws: websocket.WebSocketApp | None = None
        self._on_update = None

    def _on_open(self, ws):
        ws.send(
            json.dumps(
                {"type": "subscribe", "product_ids": [self.symbol], "channels": ["level2"]}
            )
        )

    def _on_message(self, _ws, message):
        data = json.loads(message)
        msg_type = data.get("type")

        if msg_type == "snapshot":
            self.book.load_snapshot(
                bids=data["bids"], asks=data["asks"], timestamp=datetime.now(timezone.utc)
            )
        elif msg_type == "l2update":
            for side, price, qty in data["changes"]:
                self.book.apply_level(
                    "bid" if side == "buy" else "ask", float(price), float(qty)
                )
            self.book.last_update_time = datetime.now(timezone.utc)
        else:
            return  # subscription acks, heartbeats, etc.

        if self._on_update:
            self._on_update(self.book)

    def _on_close(self, _ws, close_status_code, close_msg):
        print(f"[coinbase] websocket closed (code={close_status_code}, msg={close_msg}); will reconnect")

    def _on_error(self, _ws, error):
        print(f"[coinbase] websocket error: {error}")

    def run_forever(self, on_update=None, reconnect_delay: float = 2.0) -> None:
        """Blocking; runs until the process exits (meant to be called from
        a daemon thread via `start()`). Reconnects on any disconnect --
        `_on_open`'s resubscribe plus the fresh `snapshot` message it
        triggers is what actually recovers state; this loop is what makes
        that happen automatically instead of leaving the recording
        silently stalled after the first drop."""
        self._on_update = on_update
        while True:
            self._ws = websocket.WebSocketApp(
                WS_URL, on_open=self._on_open, on_message=self._on_message,
                on_close=self._on_close, on_error=self._on_error,
            )
            self._ws.run_forever()
            print(f"[coinbase] reconnecting in {reconnect_delay}s...")
            time.sleep(reconnect_delay)

    def start(self, on_update=None) -> threading.Thread:
        thread = threading.Thread(
            target=self.run_forever, kwargs={"on_update": on_update}, daemon=True
        )
        thread.start()
        return thread
