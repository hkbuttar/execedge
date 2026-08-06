"""Order book reconstruction correctness test for Coinbase: replay a
scripted, real-shaped sequence of `level2` channel messages (the exact
message schema Coinbase's docs publish: one `snapshot`, then ordered
`l2update` messages) through `CoinbaseBookReconciler._on_message`,
confirming expected book state at checkpoints along the way.

Needs websocket-client importable (only for the class -- the messages
themselves are plain JSON, no network involved in this test).
"""

import json

from lob.reconcile.coinbase import CoinbaseBookReconciler


def snapshot(bids, asks):
    return json.dumps({"type": "snapshot", "product_id": "BTC-USD", "bids": bids, "asks": asks})


def l2update(changes):
    return json.dumps({
        "type": "l2update", "product_id": "BTC-USD",
        "time": "2026-01-01T00:00:00.000000Z", "changes": changes,
    })


def make_reconciler():
    return CoinbaseBookReconciler("BTC-USD")


def test_snapshot_establishes_initial_book_state():
    reconciler = make_reconciler()
    reconciler._on_message(
        None,
        snapshot(
            bids=[["100.00", "1.5"], ["99.50", "2.0"]],
            asks=[["100.50", "1.0"], ["101.00", "3.0"]],
        ),
    )
    assert reconciler.book.best_bid() == 100.00
    assert reconciler.book.best_ask() == 100.50
    assert reconciler.book.bids[99.50] == 2.0
    assert reconciler.book.asks[101.00] == 3.0


def test_l2update_modifies_existing_level_size():
    reconciler = make_reconciler()
    reconciler._on_message(None, snapshot(bids=[["100.00", "1.5"]], asks=[["100.50", "1.0"]]))
    reconciler._on_message(None, l2update([["buy", "100.00", "3.25"]]))
    assert reconciler.book.bids[100.00] == 3.25


def test_l2update_adds_new_level():
    reconciler = make_reconciler()
    reconciler._on_message(None, snapshot(bids=[["100.00", "1.5"]], asks=[["100.50", "1.0"]]))
    reconciler._on_message(None, l2update([["sell", "100.75", "0.4"]]))
    assert reconciler.book.asks[100.75] == 0.4
    assert reconciler.book.best_ask() == 100.50  # still the best, new level is behind it


def test_l2update_zero_size_removes_level():
    reconciler = make_reconciler()
    reconciler._on_message(
        None, snapshot(bids=[["100.00", "1.5"], ["99.50", "2.0"]], asks=[["100.50", "1.0"]])
    )
    reconciler._on_message(None, l2update([["buy", "100.00", "0"]]))
    assert 100.00 not in reconciler.book.bids
    assert reconciler.book.best_bid() == 99.50  # falls back to the next real level


def test_single_l2update_message_with_mixed_side_changes():
    reconciler = make_reconciler()
    reconciler._on_message(None, snapshot(bids=[["100.00", "1.0"]], asks=[["100.50", "1.0"]]))
    reconciler._on_message(
        None,
        l2update([
            ["buy", "99.90", "0.5"],
            ["sell", "100.60", "0.7"],
            ["buy", "100.00", "0"],
        ]),
    )
    assert 100.00 not in reconciler.book.bids
    assert reconciler.book.bids[99.90] == 0.5
    assert reconciler.book.asks[100.60] == 0.7
    assert reconciler.book.best_bid() == 99.90


def test_non_book_message_types_are_ignored_without_error():
    reconciler = make_reconciler()
    reconciler._on_message(None, snapshot(bids=[["100.00", "1.0"]], asks=[["100.50", "1.0"]]))
    reconciler._on_message(None, json.dumps({"type": "subscriptions", "channels": []}))
    reconciler._on_message(None, json.dumps({"type": "heartbeat", "sequence": 123}))
    # book state unchanged by the ignored messages
    assert reconciler.book.best_bid() == 100.00
    assert reconciler.book.best_ask() == 100.50


def test_fresh_snapshot_after_reconnect_fully_replaces_book_state():
    reconciler = make_reconciler()
    reconciler._on_message(
        None, snapshot(bids=[["100.00", "1.0"], ["99.00", "5.0"]], asks=[["100.50", "1.0"]])
    )
    reconciler._on_message(None, l2update([["buy", "99.75", "0.2"]]))
    assert 99.75 in reconciler.book.bids

    # simulate a dropped connection + resubscribe: a brand new snapshot arrives
    reconciler._on_message(None, snapshot(bids=[["50.00", "9.0"]], asks=[["50.50", "9.0"]]))

    assert 99.75 not in reconciler.book.bids  # old state discarded, not merged
    assert 99.00 not in reconciler.book.bids
    assert reconciler.book.best_bid() == 50.00
    assert reconciler.book.best_ask() == 50.50


def test_on_update_callback_invoked_for_book_affecting_messages():
    reconciler = make_reconciler()
    calls = []
    reconciler._on_update = lambda book: calls.append(book.best_bid())

    reconciler._on_message(None, snapshot(bids=[["100.00", "1.0"]], asks=[["100.50", "1.0"]]))
    reconciler._on_message(None, l2update([["buy", "100.00", "2.0"]]))
    reconciler._on_message(None, json.dumps({"type": "heartbeat"}))

    assert calls == [100.00, 100.00]  # snapshot + l2update fire it; heartbeat doesn't
