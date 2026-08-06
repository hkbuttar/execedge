"""Binance.US public REST client (order book depth + klines).

Note: global Binance (api.binance.com) blocks requests from the US with a
451 response ("restricted location" per its terms of service). Binance.US
(api.binance.us) is a legally separate, US-facing exchange with its own
public no-auth depth/klines endpoints -- it is used here as the accessible
substitute. It is NOT the same order book as global Binance: thinner
liquidity and a narrower pair listing. See data/README.md for why this
matters for the "Binance as primary venue" framing.
"""

from datetime import datetime, timezone

import requests

from .base import ExchangeClient, Kline, OrderBookSnapshot

BASE_URL = "https://api.binance.us/api/v3"

# Binance's native interval strings, keyed by interval length in minutes.
_INTERVAL_MAP = {
    1: "1m", 3: "3m", 5: "5m", 15: "15m", 30: "30m",
    60: "1h", 120: "2h", 240: "4h", 360: "6h", 480: "8h",
    720: "12h", 1440: "1d", 4320: "3d", 10080: "1w",
}


class BinanceClient(ExchangeClient):
    venue = "binance"

    def __init__(self, session: requests.Session = None, timeout: float = 10.0):
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch_order_book(self, symbol: str, depth: int = 100) -> OrderBookSnapshot:
        resp = self.session.get(
            f"{BASE_URL}/depth",
            params={"symbol": symbol, "limit": depth},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return OrderBookSnapshot(
            venue=self.venue,
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            bids=[[float(p), float(q)] for p, q in data["bids"]],
            asks=[[float(p), float(q)] for p, q in data["asks"]],
        )

    def fetch_klines(self, symbol: str, interval_minutes: int, start, end) -> list:
        if interval_minutes not in _INTERVAL_MAP:
            raise ValueError(
                f"Binance has no native interval for {interval_minutes} minutes; "
                f"supported: {sorted(_INTERVAL_MAP)}"
            )
        interval = _INTERVAL_MAP[interval_minutes]
        interval_ms = interval_minutes * 60_000
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        klines = []
        cursor = start_ms
        while cursor < end_ms:
            resp = self.session.get(
                f"{BASE_URL}/klines",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": 1000,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            for row in batch:
                open_time_ms = row[0]
                if open_time_ms >= end_ms:
                    break
                klines.append(
                    Kline(
                        venue=self.venue,
                        symbol=symbol,
                        open_time=datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc),
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                    )
                )
            last_open_time = batch[-1][0]
            if len(batch) < 1000:
                break
            cursor = last_open_time + interval_ms
        return klines
