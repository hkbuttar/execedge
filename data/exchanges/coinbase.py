"""Coinbase Exchange public REST client (order book depth + candles).

Uses api.exchange.coinbase.com, the public market-data API -- no auth
required for order book snapshots or historical candles.
"""

from datetime import datetime, timedelta, timezone

import requests

from .base import ExchangeClient, Kline, OrderBookSnapshot

BASE_URL = "https://api.exchange.coinbase.com"
HEADERS = {"User-Agent": "execedge-research/0.1"}

# Coinbase's native candle granularities, in seconds, keyed by minutes.
_GRANULARITY_MAP = {1: 60, 5: 300, 15: 900, 60: 3600, 360: 21600, 1440: 86400}

_MAX_CANDLES_PER_REQUEST = 300


class CoinbaseClient(ExchangeClient):
    venue = "coinbase"

    def __init__(self, session: requests.Session = None, timeout: float = 10.0):
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch_order_book(self, symbol: str, depth: int = 100) -> OrderBookSnapshot:
        # level=2 returns aggregated price levels, comparable to Binance's
        # depth endpoint. level=3 (full non-aggregated order-by-order book)
        # is available if per-order granularity is ever needed.
        resp = self.session.get(
            f"{BASE_URL}/products/{symbol}/book",
            params={"level": 2},
            headers=HEADERS,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return OrderBookSnapshot(
            venue=self.venue,
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            bids=[[float(p), float(q)] for p, q, *_ in data["bids"][:depth]],
            asks=[[float(p), float(q)] for p, q, *_ in data["asks"][:depth]],
        )

    def fetch_klines(self, symbol: str, interval_minutes: int, start, end) -> list:
        if interval_minutes not in _GRANULARITY_MAP:
            raise ValueError(
                f"Coinbase has no native granularity for {interval_minutes} minutes; "
                f"supported: {sorted(_GRANULARITY_MAP)}"
            )
        granularity = _GRANULARITY_MAP[interval_minutes]
        window = timedelta(seconds=granularity * _MAX_CANDLES_PER_REQUEST)

        klines = []
        window_start = start
        while window_start < end:
            window_end = min(window_start + window, end)
            resp = self.session.get(
                f"{BASE_URL}/products/{symbol}/candles",
                params={
                    "granularity": granularity,
                    "start": window_start.isoformat(),
                    "end": window_end.isoformat(),
                },
                headers=HEADERS,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            batch = resp.json()  # newest-first: [time, low, high, open, close, volume]
            for row in sorted(batch, key=lambda r: r[0]):
                open_time = datetime.fromtimestamp(row[0], tz=timezone.utc)
                if not (window_start <= open_time < window_end):
                    continue
                klines.append(
                    Kline(
                        venue=self.venue,
                        symbol=symbol,
                        open_time=open_time,
                        open=float(row[3]),
                        high=float(row[2]),
                        low=float(row[1]),
                        close=float(row[4]),
                        volume=float(row[5]),
                    )
                )
            window_start = window_end
        return klines
