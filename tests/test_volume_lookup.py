from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from risk.volume_lookup import HistoricalVolumeLookup

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_lookup(volumes, bar_seconds=3600):
    df = pd.DataFrame({
        "open_time": [START + timedelta(seconds=bar_seconds * i) for i in range(len(volumes))],
        "volume": volumes,
    })
    return HistoricalVolumeLookup(df, bar_seconds=bar_seconds)


def test_window_fully_inside_one_bar_prorates_by_fraction():
    lookup = make_lookup([3600.0], bar_seconds=3600)  # 1 unit/sec
    # a 10-minute (600s) window inside the 1-hour bar
    volume = lookup.volume_between(START + timedelta(minutes=10), START + timedelta(minutes=20))
    assert volume == pytest.approx(600.0)  # 600 seconds * 1 unit/sec


def test_window_spanning_two_bars_sums_prorated_contributions():
    lookup = make_lookup([3600.0, 7200.0], bar_seconds=3600)  # 1 unit/sec, then 2 units/sec
    # last 10 min of bar 0 + first 10 min of bar 1
    volume = lookup.volume_between(START + timedelta(minutes=50), START + timedelta(hours=1, minutes=10))
    expected = 600 * 1.0 + 600 * 2.0
    assert volume == pytest.approx(expected)


def test_window_outside_all_bars_returns_zero():
    lookup = make_lookup([3600.0], bar_seconds=3600)
    volume = lookup.volume_between(START - timedelta(hours=5), START - timedelta(hours=4))
    assert volume == 0.0


def test_zero_or_negative_duration_window_returns_zero():
    lookup = make_lookup([3600.0], bar_seconds=3600)
    assert lookup.volume_between(START, START) == 0.0
    assert lookup.volume_between(START + timedelta(minutes=10), START) == 0.0


def test_full_bar_window_returns_full_bar_volume():
    lookup = make_lookup([1234.5], bar_seconds=3600)
    volume = lookup.volume_between(START, START + timedelta(hours=1))
    assert volume == pytest.approx(1234.5)
