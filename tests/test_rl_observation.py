from datetime import datetime, timezone

from lob.order_book import OrderBook
from rl.observation import OBSERVATION_DIM, build_observation


def make_book(bids=None, asks=None):
    book = OrderBook("test", "BTCUSD")
    book.load_snapshot(
        bids=bids or [(99.0, 2.0), (98.0, 3.0)],
        asks=asks or [(101.0, 1.0), (102.0, 4.0)],
        timestamp=datetime.now(timezone.utc),
    )
    return book


def test_observation_shape_and_dtype():
    book = make_book()
    obs = build_observation(book, remaining_fraction=0.5, time_fraction=0.3, realized_vol=0.01)
    assert obs.shape == (OBSERVATION_DIM,)
    assert obs.dtype.name == "float32"


def test_observation_values_match_book_state():
    book = make_book(bids=[(99.0, 1.0)], asks=[(101.0, 1.0)])
    obs = build_observation(book, remaining_fraction=0.75, time_fraction=0.2, realized_vol=0.02)
    remaining, time_frac, spread_frac, imbalance, vol = obs

    assert remaining == 0.75
    assert time_frac == 0.2
    assert spread_frac == (2.0 / 100.0)  # spread=2.0, mid=100.0
    assert imbalance == 0.0  # equal bid/ask volume at these levels
    assert vol == 0.02


def test_observation_handles_missing_vol_and_empty_book():
    empty_book = OrderBook("test", "BTCUSD")
    obs = build_observation(empty_book, remaining_fraction=1.0, time_fraction=0.0, realized_vol=None)
    assert obs[2] == 0.0  # spread_fraction falls back to 0 with no two-sided quote
    assert obs[3] == 0.0  # imbalance falls back to 0
    assert obs[4] == 0.0  # realized_vol falls back to 0
