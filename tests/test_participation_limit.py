from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from backtest.order import ChildOrder
from risk.participation_limit import ParticipationLimiter
from risk.volume_lookup import HistoricalVolumeLookup

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_limiter(rate, bar_volume=3600.0, bar_seconds=3600):
    df = pd.DataFrame({"open_time": [START], "volume": [bar_volume]})
    lookup = HistoricalVolumeLookup(df, bar_seconds=bar_seconds)
    return ParticipationLimiter(max_participation_rate=rate, volume_lookup=lookup)


def test_child_within_limit_is_unchanged():
    limiter = make_limiter(rate=0.5)  # cap = 0.5 * 3600 = 1800
    child = ChildOrder(timestamp=START, quantity=100.0, side="buy")
    result = limiter.cap(child, window_end=START + timedelta(hours=1))
    assert result.quantity == 100.0
    assert result is child  # unchanged, not even a copy


def test_child_exceeding_limit_is_capped():
    limiter = make_limiter(rate=0.1)  # cap = 0.1 * 3600 = 360
    child = ChildOrder(timestamp=START, quantity=1000.0, side="buy")
    result = limiter.cap(child, window_end=START + timedelta(hours=1))
    assert result.quantity == pytest.approx(360.0)
    assert result.timestamp == child.timestamp
    assert result.side == child.side


def test_narrower_window_yields_lower_cap():
    limiter = make_limiter(rate=0.1)
    child = ChildOrder(timestamp=START, quantity=1000.0, side="buy")
    # only 10 minutes of the hour -> 1/6 of the bar's volume is in scope
    result = limiter.cap(child, window_end=START + timedelta(minutes=10))
    assert result.quantity == pytest.approx(0.1 * 3600 * (600 / 3600))


def test_zero_real_volume_caps_to_zero():
    limiter = make_limiter(rate=0.5, bar_volume=0.0)
    child = ChildOrder(timestamp=START, quantity=10.0, side="buy")
    result = limiter.cap(child, window_end=START + timedelta(hours=1))
    assert result.quantity == 0.0


def test_rejects_invalid_participation_rate():
    df = pd.DataFrame({"open_time": [START], "volume": [100.0]})
    lookup = HistoricalVolumeLookup(df, bar_seconds=3600)
    with pytest.raises(ValueError):
        ParticipationLimiter(max_participation_rate=0.0, volume_lookup=lookup)
    with pytest.raises(ValueError):
        ParticipationLimiter(max_participation_rate=1.5, volume_lookup=lookup)
