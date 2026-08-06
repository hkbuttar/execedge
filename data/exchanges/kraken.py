"""Kraken public REST client (order book depth + OHLC).

Public endpoints, no auth required. One quirk worth noting: Kraken echoes
back an internal pair name in responses that differs from the pair you
request with (e.g. requesting "XBTUSD" returns results keyed "XXBTZUSD"),
so both clients below read the first (only) key of `result` rather than
assuming the request symbol round-trips unchanged.
"""

from datetime import datetime, timezone

import requests

from .base import ExchangeClient, Kline, OrderBookSnapshot

BASE_URL = "https://api.kraken.com/0/public"

# Kraken's native OHLC interval, in minutes -- also the valid `interval` values.
_VALID_INTERVALS = {1, 5, 15, 30, 60, 240, 1440, 10080, 21600}


class KrakenClient(ExchangeClient):
    venue = "kraken"

    def __init__(self, session: requests.Session = None, timeout: float = 10.0):
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch_order_book(self, symbol: str, depth: int = 100) -> OrderBookSnapshot:
        resp = self.session.get(
            f"{BASE_URL}/Depth",
            params={"pair": symbol, "count": depth},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if data["error"]:
            raise RuntimeError(f"Kraken error: {data['error']}")
        book = next(iter(data["result"].values()))
        return OrderBookSnapshot(
            venue=self.venue,
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            bids=[[float(p), float(q)] for p, q, _ts in book["bids"]],
            asks=[[float(p), float(q)] for p, q, _ts in book["asks"]],
        )

    def fetch_klines(self, symbol: str, interval_minutes: int, start, end) -> list:
        if interval_minutes not in _VALID_INTERVALS:
            raise ValueError(
                f"Kraken has no native interval for {interval_minutes} minutes; "
                f"supported: {sorted(_VALID_INTERVALS)}"
            )
        since = int(start.timestamp())
        end_ts = int(end.timestamp())

        klines = []
        while since < end_ts:
            resp = self.session.get(
                f"{BASE_URL}/OHLC",
                params={"pair": symbol, "interval": interval_minutes, "since": since},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if data["error"]:
                raise RuntimeError(f"Kraken error: {data['error']}")
            result = dict(data["result"])
            last = result.pop("last")
            rows = next(iter(result.values()))
            if not rows:
                break
            for row in rows:
                open_time_ts = row[0]
                if open_time_ts >= end_ts:
                    continue
                klines.append(
                    Kline(
                        venue=self.venue,
                        symbol=symbol,
                        open_time=datetime.fromtimestamp(open_time_ts, tz=timezone.utc),
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[6]),
                    )
                )
            if last <= since:
                break
            since = last
        return klines
