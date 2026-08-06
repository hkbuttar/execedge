"""Microstructure features computed from a reconstructed real order book:
spread, order book imbalance, mid-price, and short-term realized
volatility of the mid-price.
"""

import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from lob.order_book import OrderBook


@dataclass
class FeatureSnapshot:
    venue: str
    symbol: str
    timestamp: datetime
    mid_price: float | None
    spread: float | None
    imbalance: float | None
    realized_vol: float | None  # std dev of mid-price log returns over the window


class RealizedVolTracker:
    """Rolling realized volatility of log returns over the last `window`
    mid-price observations. Not annualized -- this is a per-observation
    volatility meant for regime comparison (`data/regimes.py`), not a
    risk metric calibrated to a fixed time unit, since update arrival isn't evenly
    spaced across venues.
    """

    def __init__(self, window: int = 100):
        self.window = window
        self._log_returns: deque[float] = deque(maxlen=window)
        self._last_mid: float | None = None

    def update(self, mid_price: float | None) -> float | None:
        if mid_price is None or mid_price <= 0:
            return self.value()
        if self._last_mid is not None and self._last_mid > 0:
            self._log_returns.append(math.log(mid_price / self._last_mid))
        self._last_mid = mid_price
        return self.value()

    def value(self) -> float | None:
        n = len(self._log_returns)
        if n < 2:
            return None
        mean = sum(self._log_returns) / n
        variance = sum((r - mean) ** 2 for r in self._log_returns) / (n - 1)
        return math.sqrt(variance)


def compute_features(
    book: OrderBook, vol_tracker: RealizedVolTracker, levels: int = 5
) -> FeatureSnapshot:
    mid = book.mid_price()
    return FeatureSnapshot(
        venue=book.venue,
        symbol=book.symbol,
        timestamp=book.last_update_time,
        mid_price=mid,
        spread=book.spread(),
        imbalance=book.imbalance(levels=levels),
        realized_vol=vol_tracker.update(mid),
    )
