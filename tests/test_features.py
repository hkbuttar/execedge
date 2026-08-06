from datetime import datetime, timezone

from lob.features import RealizedVolTracker, compute_features
from lob.order_book import OrderBook


def test_realized_vol_tracker_needs_two_observations():
    tracker = RealizedVolTracker()
    assert tracker.update(100.0) is None  # first observation, no return yet


def test_realized_vol_tracker_zero_for_constant_price():
    tracker = RealizedVolTracker()
    tracker.update(100.0)
    tracker.update(100.0)
    assert tracker.update(100.0) == 0.0


def test_realized_vol_tracker_positive_for_moving_price():
    tracker = RealizedVolTracker()
    for price in [100.0, 101.0, 99.0, 102.0, 98.0]:
        vol = tracker.update(price)
    assert vol is not None and vol > 0


def test_realized_vol_tracker_window_bound():
    tracker = RealizedVolTracker(window=3)
    for price in [100.0, 101.0, 102.0, 103.0, 104.0]:
        tracker.update(price)
    assert len(tracker._log_returns) == 3


def test_compute_features_matches_book_state():
    book = OrderBook("test", "BTCUSD")
    book.load_snapshot(
        bids=[(100.0, 1.0)], asks=[(100.5, 1.0)], timestamp=datetime.now(timezone.utc)
    )
    tracker = RealizedVolTracker()
    snapshot = compute_features(book, tracker)
    assert snapshot.mid_price == 100.25
    assert snapshot.spread == 0.5
    assert snapshot.imbalance == 0.0
    assert snapshot.realized_vol is None  # only one observation so far


def test_compute_features_none_on_empty_book():
    book = OrderBook("test", "BTCUSD")
    tracker = RealizedVolTracker()
    snapshot = compute_features(book, tracker)
    assert snapshot.mid_price is None
    assert snapshot.spread is None
    assert snapshot.imbalance is None
