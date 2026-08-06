"""In-memory limit order book, rebuilt from a snapshot plus a stream of
incremental level updates. Venue-agnostic: each venue's reconciler
(lob/reconcile/) is responsible for translating its own wire format into
calls to `load_snapshot` and `apply_level`.
"""

from datetime import datetime


class OrderBook:
    def __init__(self, venue: str, symbol: str):
        self.venue = venue
        self.symbol = symbol
        self.bids: dict[float, float] = {}  # price -> qty
        self.asks: dict[float, float] = {}  # price -> qty
        self.last_update_time: datetime | None = None

    def load_snapshot(self, bids, asks, timestamp: datetime) -> None:
        """Replace book state wholesale. `bids`/`asks` are iterables of
        (price, qty) pairs; zero-qty levels are dropped on load."""
        self.bids = {float(p): float(q) for p, q in bids if float(q) > 0}
        self.asks = {float(p): float(q) for p, q in asks if float(q) > 0}
        self.last_update_time = timestamp

    def apply_level(self, side: str, price: float, qty: float) -> None:
        """Apply one incremental level update. qty == 0 removes the level
        (this is the standard L2 diff convention across all three venues)."""
        book = self.bids if side == "bid" else self.asks
        if qty == 0:
            book.pop(price, None)
        else:
            book[price] = qty

    def best_bid(self) -> float | None:
        return max(self.bids) if self.bids else None

    def best_ask(self) -> float | None:
        return min(self.asks) if self.asks else None

    def mid_price(self) -> float | None:
        bb, ba = self.best_bid(), self.best_ask()
        return (bb + ba) / 2 if bb is not None and ba is not None else None

    def spread(self) -> float | None:
        bb, ba = self.best_bid(), self.best_ask()
        return (ba - bb) if bb is not None and ba is not None else None

    def top_levels(self, side: str, n: int):
        """Return the top `n` (price, qty) levels for `side`, best first."""
        if side == "bid":
            return sorted(self.bids.items(), key=lambda kv: -kv[0])[:n]
        return sorted(self.asks.items(), key=lambda kv: kv[0])[:n]

    def imbalance(self, levels: int = 5) -> float | None:
        """Order book imbalance over the top `levels` per side, in
        [-1, 1]: positive means more resting bid volume than ask volume."""
        bid_vol = sum(q for _, q in self.top_levels("bid", levels))
        ask_vol = sum(q for _, q in self.top_levels("ask", levels))
        total = bid_vol + ask_vol
        return (bid_vol - ask_vol) / total if total > 0 else None
