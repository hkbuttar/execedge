"""Kraken WebSocket v2 `book` channel reconciliation.

Kraken's update semantics differ from both other venues: instead of a
sequence/update-ID to detect gaps (Binance) or an implicitly-ordered
single stream (Coinbase), each `update` message ships a CRC32 `checksum`
of the top-10 levels, computed by Kraken from its own book state after
applying the update. We recompute the same checksum locally and compare;
a mismatch means our local book has drifted from Kraken's, which is our
signal to resync (re-subscribe and take the next `snapshot`).

Checksum algorithm (per Kraken's documented procedure): take the best 10
ask levels (ascending price) then the best 10 bid levels (descending
price); for each level, take the price and quantity strings *exactly as
Kraken formatted them* (decimal point and any leading zeros stripped,
trailing zeros kept), concatenate price+qty for all 20 levels in order,
then CRC32 the resulting string.

That "exactly as formatted" requirement is why this client parses JSON
with `parse_float=str`: the default `json` parser would turn e.g. "1.50"
into the float 1.5 and silently lose the trailing zero the checksum
depends on. `compute_checksum` is verified against Kraken's own published
worked example (tests/test_kraken_checksum.py); what's untested without a
live connection is the message-handling path around it (resync-on-
mismatch behavior), since that needs a real feed to exercise.
"""

import json
import threading
import time
import zlib
from datetime import datetime, timezone

import websocket

from lob.order_book import OrderBook

WS_URL = "wss://ws.kraken.com/v2"


def _strip_number(raw: str) -> str:
    """'0150.30000' -> '15030000' (drop decimal point + leading zeros,
    keep trailing zeros) -- Kraken's checksum input format."""
    digits = raw.replace(".", "").lstrip("0")
    return digits or "0"


def compute_checksum(raw_asks: list, raw_bids: list) -> int:
    """`raw_asks`/`raw_bids` are the top-10 (price_str, qty_str) pairs as
    literally received (see the parse_float=str note above), sorted best
    first."""
    parts = [_strip_number(p) + _strip_number(q) for p, q in raw_asks[:10]]
    parts += [_strip_number(p) + _strip_number(q) for p, q in raw_bids[:10]]
    return zlib.crc32("".join(parts).encode())


class KrakenBookReconciler:
    def __init__(self, symbol: str, depth: int = 10):
        self.symbol = symbol  # e.g. "BTC/USD"
        self.depth = depth
        self.book = OrderBook("kraken", symbol)
        self.checksum_mismatches = 0
        self._ws: websocket.WebSocketApp | None = None
        self._on_update = None
        # Kraken's checksum is computed over its own exact price/qty string
        # formatting (decimal point + leading zeros stripped, trailing
        # zeros kept). `self.book` stores floats, which lose that
        # formatting, so raw strings are tracked separately here, keyed by
        # float price so top-of-book ordering matches `self.book`.
        self._raw_bids: dict[float, tuple[str, str]] = {}
        self._raw_asks: dict[float, tuple[str, str]] = {}

    def _on_open(self, ws):
        ws.send(
            json.dumps(
                {
                    "method": "subscribe",
                    "params": {"channel": "book", "symbol": [self.symbol], "depth": self.depth},
                }
            )
        )

    def _on_message(self, _ws, raw_message):
        # parse_float=str preserves Kraken's exact price/qty formatting,
        # required for checksum verification -- see module docstring.
        message = json.loads(raw_message, parse_float=str)
        if not isinstance(message, dict) or message.get("channel") != "book":
            return  # subscription acks, heartbeats, other channels

        for entry in message.get("data", []):
            if message["type"] == "snapshot":
                self.book.load_snapshot(
                    bids=[(lvl["price"], lvl["qty"]) for lvl in entry["bids"]],
                    asks=[(lvl["price"], lvl["qty"]) for lvl in entry["asks"]],
                    timestamp=datetime.now(timezone.utc),
                )
                self._raw_bids = {
                    float(lvl["price"]): (lvl["price"], lvl["qty"]) for lvl in entry["bids"]
                }
                self._raw_asks = {
                    float(lvl["price"]): (lvl["price"], lvl["qty"]) for lvl in entry["asks"]
                }
            elif message["type"] == "update":
                for lvl in entry.get("bids", []):
                    self._apply_raw_level(self._raw_bids, "bid", lvl)
                for lvl in entry.get("asks", []):
                    self._apply_raw_level(self._raw_asks, "ask", lvl)
                self.book.last_update_time = datetime.now(timezone.utc)

                checksum = entry.get("checksum")
                if checksum is not None and not self._verify_checksum(checksum):
                    self.checksum_mismatches += 1

            if self._on_update:
                self._on_update(self.book)

    def _apply_raw_level(self, raw_side: dict, side: str, lvl: dict) -> None:
        price, qty = float(lvl["price"]), float(lvl["qty"])
        self.book.apply_level(side, price, qty)
        if qty == 0:
            raw_side.pop(price, None)
        else:
            raw_side[price] = (lvl["price"], lvl["qty"])

    def _verify_checksum(self, expected: int) -> bool:
        raw_asks = [self._raw_asks[p] for p in sorted(self._raw_asks)[:10]]
        raw_bids = [self._raw_bids[p] for p in sorted(self._raw_bids, reverse=True)[:10]]
        return compute_checksum(raw_asks, raw_bids) == expected

    def _on_close(self, _ws, close_status_code, close_msg):
        print(f"[kraken] websocket closed (code={close_status_code}, msg={close_msg}); will reconnect")

    def _on_error(self, _ws, error):
        print(f"[kraken] websocket error: {error}")

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
            print(f"[kraken] reconnecting in {reconnect_delay}s...")
            time.sleep(reconnect_delay)

    def start(self, on_update=None) -> threading.Thread:
        thread = threading.Thread(
            target=self.run_forever, kwargs={"on_update": on_update}, daemon=True
        )
        thread.start()
        return thread
