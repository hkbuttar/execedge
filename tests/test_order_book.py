from datetime import datetime, timezone

from lob.order_book import OrderBook


def make_book():
    book = OrderBook("test", "BTCUSD")
    book.load_snapshot(
        bids=[(100.0, 1.0), (99.5, 2.0), (99.0, 3.0)],
        asks=[(100.5, 1.5), (101.0, 2.5), (101.5, 3.5)],
        timestamp=datetime.now(timezone.utc),
    )
    return book


def test_best_bid_ask_and_mid():
    book = make_book()
    assert book.best_bid() == 100.0
    assert book.best_ask() == 100.5
    assert book.mid_price() == 100.25
    assert book.spread() == 0.5


def test_apply_level_updates_and_removes():
    book = make_book()
    book.apply_level("bid", 100.0, 0.5)  # update
    assert book.bids[100.0] == 0.5

    book.apply_level("bid", 100.0, 0)  # remove
    assert 100.0 not in book.bids
    assert book.best_bid() == 99.5


def test_apply_level_adds_new_level():
    book = make_book()
    book.apply_level("ask", 100.25, 4.0)
    assert book.best_ask() == 100.25


def test_empty_book_returns_none():
    book = OrderBook("test", "BTCUSD")
    assert book.best_bid() is None
    assert book.best_ask() is None
    assert book.mid_price() is None
    assert book.spread() is None
    assert book.imbalance() is None


def test_imbalance_sign_and_bounds():
    book = make_book()  # bid vol 6.0, ask vol 7.5 over top 3
    imbalance = book.imbalance(levels=3)
    assert -1 <= imbalance <= 1
    assert imbalance < 0  # more ask volume resting than bid volume

    book.load_snapshot(
        bids=[(100.0, 10.0)], asks=[(100.5, 1.0)], timestamp=datetime.now(timezone.utc)
    )
    assert book.imbalance(levels=1) > 0


def test_top_levels_ordering():
    book = make_book()
    assert [p for p, _ in book.top_levels("bid", 2)] == [100.0, 99.5]
    assert [p for p, _ in book.top_levels("ask", 2)] == [100.5, 101.0]
