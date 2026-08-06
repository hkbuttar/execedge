"""Venue and symbol configuration for real-data acquisition.

Every venue here exposes public, unauthenticated REST endpoints for order
book depth and historical klines/candles -- no API keys are required for
anything in Step 1 (data acquisition) or the depth/volume pipeline that
depends on it.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class VenueSymbol:
    venue: str
    symbol: str  # symbol as passed to that venue's API


# BTC/USD across the three venues. Note the symbol spelling differs per
# venue's own convention (documented further in data/README.md).
BTC_USD = {
    "binance": VenueSymbol("binance", "BTCUSDT"),
    "coinbase": VenueSymbol("coinbase", "BTC-USD"),
    "kraken": VenueSymbol("kraken", "XBTUSD"),
}

VENUES = ("binance", "coinbase", "kraken")
