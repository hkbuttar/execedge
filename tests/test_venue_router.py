from datetime import datetime, timezone

import pytest

from backtest.order import ChildOrder
from lob.order_book import OrderBook
from venues.fees import FeeSchedule
from venues.router import BestEffectivePriceRouter, SingleVenueRouter

NOW = datetime.now(timezone.utc)


def make_book(bid, ask):
    book = OrderBook("test", "BTCUSD")
    book.load_snapshot(bids=[(bid, 10.0)], asks=[(ask, 10.0)], timestamp=NOW)
    return book


FEES = {
    "a": FeeSchedule(venue="a", maker_fee_bps=0.0, taker_fee_bps=2.0, source="test"),
    "b": FeeSchedule(venue="b", maker_fee_bps=0.0, taker_fee_bps=60.0, source="test"),
}


def test_single_venue_router_always_returns_configured_venue():
    router = SingleVenueRouter("b")
    child = ChildOrder(timestamp=NOW, quantity=1.0, side="buy")
    books = {"a": make_book(99, 100), "b": make_book(99, 100)}
    assert router.choose(child, books, FEES) == "b"


def test_best_price_router_picks_lower_fee_when_raw_prices_tie_buy():
    router = BestEffectivePriceRouter()
    child = ChildOrder(timestamp=NOW, quantity=1.0, side="buy")
    books = {"a": make_book(99, 100.0), "b": make_book(99, 100.0)}
    assert router.choose(child, books, FEES) == "a"  # same ask, lower fee


def test_best_price_router_accounts_for_fee_outweighing_raw_price_buy():
    router = BestEffectivePriceRouter()
    child = ChildOrder(timestamp=NOW, quantity=1.0, side="buy")
    # venue a: worse raw ask but much lower fee -> still cheaper all-in
    books = {"a": make_book(99, 100.05), "b": make_book(99, 100.00)}
    # effective a = 100.05 * 1.0002 = 100.0700...
    # effective b = 100.00 * 1.0060 = 100.60
    assert router.choose(child, books, FEES) == "a"


def test_best_price_router_sell_side_prefers_higher_effective_price():
    router = BestEffectivePriceRouter()
    child = ChildOrder(timestamp=NOW, quantity=1.0, side="sell")
    # selling: fee reduces what you effectively receive
    books = {"a": make_book(100.0, 101), "b": make_book(100.5, 101)}
    # effective a (bid=100.0, fee 2bps) = 100.0 * (1 - 0.0002) = 99.98
    # effective b (bid=100.5, fee 60bps) = 100.5 * (1 - 0.0060) = 99.897
    assert router.choose(child, books, FEES) == "a"


def test_best_price_router_skips_venues_with_no_touch_price():
    router = BestEffectivePriceRouter()
    child = ChildOrder(timestamp=NOW, quantity=1.0, side="buy")
    empty_book = OrderBook("test", "BTCUSD")  # no bids/asks loaded
    books = {"a": empty_book, "b": make_book(99, 100.0)}
    assert router.choose(child, books, FEES) == "b"


def test_best_price_router_raises_if_no_venue_has_a_quote():
    router = BestEffectivePriceRouter()
    child = ChildOrder(timestamp=NOW, quantity=1.0, side="buy")
    books = {"a": OrderBook("test", "BTCUSD"), "b": OrderBook("test", "BTCUSD")}
    with pytest.raises(ValueError):
        router.choose(child, books, FEES)
