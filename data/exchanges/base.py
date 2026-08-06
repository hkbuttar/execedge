"""Common interface implemented by each venue's real-data client.

Every method below hits a public, unauthenticated REST endpoint and
returns data normalized to a shared schema so downstream code (lob/,
algos/) doesn't need to know which venue it came from.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class OrderBookSnapshot:
    venue: str
    symbol: str
    timestamp: datetime  # UTC, when the snapshot was retrieved
    bids: list  # [[price: float, qty: float], ...] descending by price
    asks: list  # [[price: float, qty: float], ...] ascending by price


@dataclass
class Kline:
    venue: str
    symbol: str
    open_time: datetime  # UTC
    open: float
    high: float
    low: float
    close: float
    volume: float  # base-asset volume traded in the interval


class ExchangeClient(ABC):
    venue: str

    @abstractmethod
    def fetch_order_book(self, symbol: str, depth: int = 100) -> OrderBookSnapshot:
        """Fetch a full-depth order book snapshot for `symbol`."""

    @abstractmethod
    def fetch_klines(
        self, symbol: str, interval_minutes: int, start: datetime, end: datetime
    ) -> list:
        """Fetch historical OHLCV bars for `symbol` between start and end (UTC),
        paginating internally as needed. Returns a list[Kline] sorted by
        open_time ascending.
        """
