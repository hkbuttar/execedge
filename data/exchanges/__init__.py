from .base import ExchangeClient, Kline, OrderBookSnapshot
from .binance import BinanceClient
from .coinbase import CoinbaseClient
from .kraken import KrakenClient

CLIENTS = {
    "binance": BinanceClient,
    "coinbase": CoinbaseClient,
    "kraken": KrakenClient,
}

__all__ = [
    "ExchangeClient",
    "Kline",
    "OrderBookSnapshot",
    "BinanceClient",
    "CoinbaseClient",
    "KrakenClient",
    "CLIENTS",
]
