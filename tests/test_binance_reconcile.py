"""Tests for lob.reconcile.binance -- both the pure reconcile_events()
function and BinanceBookReconciler's stateful buffering around it. Needs
websocket-client importable (only for the class-level tests further down;
reconcile_events itself has no I/O dependency, but importing anything
from this module loads the whole file, which does `import websocket`).

This is the logic that was silently broken in production, three times,
only caught by actually running it against a live feed rather than by
review -- each fix alone insufficient until the next one:

  1. The REST snapshot fetch ran on the websocket's own callback thread,
     blocking it and starving the event buffer (fixed: fetch moved to a
     background thread).
  2. Each failed resync attempt discarded the buffered backlog instead of
     preserving it, so every retry restarted with only ~1 fresh event --
     the same race as bug 1, just spread across attempts instead of one
     (fixed: `self._pending` is now only ever cleared on a fresh
     connection or a successful reconciliation). Caught while fixing
     this: the leftover-event computation misclassified genuinely stale
     events as unapplied leftovers, replaying them and triggering a false
     gap right after a successful sync (fixed by computing leftover from
     the applied run's position, not set difference).
  3. Confirmed live with 1+2 fixed and logging visible: every retry
     re-fetched a *fresh* snapshot -- a new `lastUpdateId` reflecting
     "now" each time. Binance.US's real book advances by 10s-200s of
     update IDs per second while the diff stream delivers ~1 message/sec,
     so a freshly-fetched target is always already ahead of everything
     buffered, forever -- observed live as 16 retries, buffer correctly
     growing to 33 events, zero straddles. Fixed: the snapshot is now
     fetched once per resync episode and reused across retries
     (`test_snapshot_is_fetched_once_and_reused_across_retries` below is
     the regression test for this).
"""

import json
from unittest.mock import MagicMock

from lob.reconcile.binance import BinanceBookReconciler, reconcile_events


def ev(u_start, u_end):
    """A minimal diff event: U (first update ID) and u (last update ID)."""
    return {"U": u_start, "u": u_end}


def test_no_buffered_events_returns_empty():
    assert reconcile_events([], last_update_id=100) == []


def test_all_events_already_reflected_in_snapshot():
    events = [ev(90, 95), ev(96, 100)]
    assert reconcile_events(events, last_update_id=100) == []


def test_no_event_straddles_snapshot_returns_empty():
    # first live event starts well after the snapshot's point in time --
    # a real gap, nothing to apply yet
    events = [ev(150, 160)]
    assert reconcile_events(events, last_update_id=100) == []


def test_single_straddling_event_is_applied():
    event = ev(95, 105)  # U=95 <= 101 <= u=105
    assert reconcile_events([event], last_update_id=100) == [event]


def test_straddle_boundary_conditions():
    # U == lastUpdateId+1 exactly
    boundary_low = ev(101, 110)
    assert reconcile_events([boundary_low], last_update_id=100) == [boundary_low]
    # u == lastUpdateId+1 exactly
    boundary_high = ev(90, 101)
    assert reconcile_events([boundary_high], last_update_id=100) == [boundary_high]


def test_continuous_run_after_straddle_all_applied():
    first = ev(95, 105)
    second = ev(106, 110)
    third = ev(111, 120)
    events = [first, second, third]
    assert reconcile_events(events, last_update_id=100) == events


def test_gap_after_straddle_truncates_to_contiguous_prefix():
    first = ev(95, 105)
    second = ev(106, 110)
    gapped = ev(115, 120)  # U != second['u']+1 (111) -- a message was missed
    fourth = ev(121, 125)  # would be fine if reached, but shouldn't be

    result = reconcile_events([first, second, gapped, fourth], last_update_id=100)
    assert result == [first, second]


def test_stale_events_before_straddle_are_skipped():
    stale1 = ev(80, 90)
    stale2 = ev(91, 100)
    straddle = ev(95, 105)  # u=105 > 100, and covers 101
    followup = ev(106, 110)

    result = reconcile_events([stale1, stale2, straddle, followup], last_update_id=100)
    assert result == [straddle, followup]


def test_gap_before_any_straddle_found_yet_returns_empty_not_partial():
    # a non-straddling event that arrives, followed later by one that
    # would straddle if we naively chained continuity -- but there's no
    # "first" event yet, so the second one must still independently
    # satisfy the straddle condition to start.
    non_straddle = ev(150, 160)
    later = ev(161, 170)
    assert reconcile_events([non_straddle, later], last_update_id=100) == []


# --- BinanceBookReconciler: stateful buffering around reconcile_events ---


def diff_event(update_id):
    """A minimal Binance diff-depth event: U == u == update_id, no book
    changes (irrelevant to the buffering/reconciliation logic tested
    here)."""
    return json.dumps({"U": update_id, "u": update_id, "b": [], "a": [], "E": 0})


def test_failed_resync_preserves_backlog_instead_of_discarding_it():
    reconciler = BinanceBookReconciler("BTCUSDT")

    reconciler._on_message(None, diff_event(1000))
    # snapshot's lastUpdateId is already >= this event's u -> "stale", no straddle
    reconciler._fetch_snapshot = MagicMock(return_value={"lastUpdateId": 1000, "bids": [], "asks": []})
    reconciler._attempt_resync()

    assert reconciler._synced is False
    assert len(reconciler._pending) == 1, "the buffered event must NOT be discarded on a failed attempt"


def test_resync_converges_once_backlog_grows_past_a_stale_snapshot():
    reconciler = BinanceBookReconciler("BTCUSDT")
    fetch = MagicMock(return_value={"lastUpdateId": 1000, "bids": [], "asks": []})
    reconciler._fetch_snapshot = fetch

    reconciler._on_message(None, diff_event(1000))
    reconciler._attempt_resync()
    assert reconciler._synced is False

    for update_id in range(1001, 1006):
        reconciler._on_message(None, diff_event(update_id))
    assert len(reconciler._pending) == 6, "backlog should have grown across the failed attempt, not reset"

    reconciler._attempt_resync()  # rechecks the SAME cached snapshot (1000), now with a bigger buffer

    assert reconciler._synced is True
    assert reconciler._last_u == 1005
    assert reconciler._pending == []
    assert fetch.call_count == 1, "must not re-fetch a fresh snapshot on a retry (see Bug 3)"


def test_snapshot_is_fetched_once_and_reused_across_retries():
    """Regression test for Bug 3: re-fetching a fresh snapshot on every
    retry chases a moving target and can never converge if real update-ID
    growth outpaces message arrival, which is the normal case live. The
    snapshot must be fetched once per resync episode and rechecked
    against the growing buffer, not replaced every attempt."""
    reconciler = BinanceBookReconciler("BTCUSDT")
    fetch = MagicMock(return_value={"lastUpdateId": 5000, "bids": [], "asks": []})
    reconciler._fetch_snapshot = fetch

    reconciler._on_message(None, diff_event(4998))  # stale vs. lastUpdateId=5000
    reconciler._attempt_resync()
    assert fetch.call_count == 1
    assert reconciler._synced is False

    # several more failed rechecks -- still must not re-fetch
    for _ in range(5):
        reconciler._attempt_resync()
    assert fetch.call_count == 1, "repeated rechecks against an unexpired snapshot must not re-fetch"

    # buffer finally grows past the fixed target
    reconciler._on_message(None, diff_event(5001))
    reconciler._attempt_resync()
    assert fetch.call_count == 1, "the successful attempt still reuses the original snapshot"
    assert reconciler._synced is True
    assert reconciler._last_u == 5001


def test_snapshot_is_refetched_after_max_age_exceeded():
    reconciler = BinanceBookReconciler("BTCUSDT", snapshot_max_age_seconds=0.05)
    fetch = MagicMock(return_value={"lastUpdateId": 1000, "bids": [], "asks": []})
    reconciler._fetch_snapshot = fetch

    reconciler._on_message(None, diff_event(1000))  # stale, no straddle
    reconciler._attempt_resync()
    assert fetch.call_count == 1

    import time as _time
    _time.sleep(0.1)  # exceed snapshot_max_age_seconds

    reconciler._attempt_resync()
    assert fetch.call_count == 2, "a genuinely stale (too old) snapshot must eventually be refetched"


def test_stale_events_are_not_replayed_as_false_gaps_after_sync():
    """Regression test for the third bug found while fixing the second:
    stale (already-covered) events must be discarded permanently, not
    treated as leftover and replayed through the live path, which would
    trigger a false gap-detected resync immediately after syncing."""
    reconciler = BinanceBookReconciler("BTCUSDT")
    for update_id in range(1000, 1006):
        reconciler._on_message(None, diff_event(update_id))

    reconciler._fetch_snapshot = MagicMock(return_value={"lastUpdateId": 1003, "bids": [], "asks": []})
    reconciler._attempt_resync()

    assert reconciler._synced is True, "must stay synced -- no false gap from replaying stale events"
    assert reconciler._last_u == 1005
    assert reconciler._pending == []

    # a genuine subsequent live event should apply cleanly
    reconciler._on_message(None, diff_event(1006))
    assert reconciler._synced is True
    assert reconciler._last_u == 1006


def test_genuine_gap_in_tail_after_resync_re_triggers_resync():
    reconciler = BinanceBookReconciler("BTCUSDT")
    for update_id in [1000, 1001, 1002]:
        reconciler._on_message(None, diff_event(update_id))

    reconciler._fetch_snapshot = MagicMock(return_value={"lastUpdateId": 999, "bids": [], "asks": []})
    reconciler._attempt_resync()
    assert reconciler._synced is True
    assert reconciler._last_u == 1002

    # a live event arrives with a real gap (missed update 1003)
    reconciler._on_message(None, diff_event(1005))
    assert reconciler._synced is False
    assert reconciler._pending == [{"U": 1005, "u": 1005, "b": [], "a": [], "E": 0}]
