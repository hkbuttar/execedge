from datetime import datetime, timezone

import pytest

from risk.kill_switch import KillSwitch

NOW = datetime.now(timezone.utc)


def test_starts_untripped():
    ks = KillSwitch()
    assert ks.is_tripped is False
    assert ks.event is None


def test_trip_sets_state():
    ks = KillSwitch()
    ks.trip("too volatile", NOW)
    assert ks.is_tripped is True
    assert ks.event.reason == "too volatile"
    assert ks.event.timestamp == NOW


def test_first_trip_wins():
    ks = KillSwitch()
    ks.trip("first reason", NOW)
    ks.trip("second reason", NOW)
    assert ks.event.reason == "first reason"


def test_reset_requires_explicit_confirm():
    ks = KillSwitch()
    ks.trip("halted", NOW)
    with pytest.raises(ValueError):
        ks.reset()
    with pytest.raises(ValueError):
        ks.reset(confirm=False)
    assert ks.is_tripped is True  # unchanged by the failed reset attempts


def test_reset_with_confirm_clears_state():
    ks = KillSwitch()
    ks.trip("halted", NOW)
    ks.reset(confirm=True)
    assert ks.is_tripped is False
    assert ks.event is None
