"""Binance.US diff-depth stream reconciliation.

Binance's documented procedure for building a correct local book from its
partial-depth diff stream (this is the standard algorithm published for
`<symbol>@depth`, applies unchanged on Binance.US):

  1. Open the diff-stream websocket and buffer every event (don't apply
     anything yet).
  2. Fetch a REST order book snapshot; note its `lastUpdateId`.
  3. Drop any buffered event whose `u` (final update ID) is <=
     `lastUpdateId` -- it's already reflected in the snapshot.
  4. The first event you apply must satisfy
     `U <= lastUpdateId + 1 <= u` (it "covers" the snapshot's point in time).
  5. Every event after that must have `U == previous event's u + 1`. Any
     gap means a message was missed -- stop applying, drop the local book,
     and resync from step 2.

Three real bugs were found here by actually running this against a live
feed (not by review), each fix alone insufficient until the next one:

  Bug 1: the original code called the REST snapshot fetch (a real HTTP
  round trip) directly inside the websocket's `on_message` callback.
  `websocket-client` delivers all messages on one callback thread, so
  while that HTTP call blocked, no new events could be buffered -- by the
  time the snapshot arrived, the buffer held only the single event that
  triggered the fetch, which essentially never straddles the snapshot's
  `lastUpdateId`. Fixed by moving the fetch to a background thread
  (`_attempt_resync` runs via `threading.Timer`, never on the WS thread).

  Bug 2 (found after fixing bug 1, still silent): each resync attempt
  *drained* the buffer into a local list even when the attempt failed to
  find a straddling event, discarding whatever had been buffered. Fixed:
  buffered-but-unconfirmed events (`self._pending`) are only ever cleared
  on a fresh connection or a successful reconciliation -- never on a
  failed attempt.

  Bug 3 (found running live with bug 1+2 fixed, logging now visible):
  every retry re-fetched a *fresh* snapshot, i.e. a new `lastUpdateId`
  reflecting "now" at each attempt. Binance.US's real book advances by
  10s-200s of internal update IDs per second, while the plain
  (non-`@100ms`) diff stream only delivers ~1 message/second -- so a
  freshly-fetched `lastUpdateId` is *already* ahead of everything
  buffered so far, every single time, forever. The buffer's own `u`
  values could never catch up to a target that re-advances faster than
  message arrival on every check. Confirmed live: 16 retries, buffer
  correctly growing to 33 events (bug 2's fix working), zero straddles
  found. Fixed: the snapshot is now fetched *once* per resync episode;
  retries recheck the growing buffer against that *same fixed*
  `lastUpdateId` instead of a new one each time. Since buffered `u`
  values increase monotonically over real time and the target no longer
  moves, this is guaranteed to converge once the buffer's tip passes the
  fixed point -- a fresh snapshot is only re-fetched if the current one
  goes unmatched for `snapshot_max_age_seconds` (a real connection
  hiccup, not the everyday case).

This is meaningfully different from Coinbase (single ordered TCP stream,
no separate REST call, no explicit sequence gap detection needed) and
from Kraken (v2 book channel ships a CRC32 checksum of the top-10 levels
instead of update-ID continuity, also no separate REST call). See
lob/README.md for the side-by-side.
"""

import json
import threading
import time
from datetime import datetime, timezone

import requests
import websocket

from lob.order_book import OrderBook

REST_URL = "https://api.binance.us/api/v3/depth"
STREAM_URL = "wss://stream.binance.us:9443/ws/{symbol}@depth"


def reconcile_events(buffered_events: list, last_update_id: int) -> list:
    """Pure logic, no I/O: given diff events buffered while (or before) a
    REST snapshot with `lastUpdateId` was fetched, return the ordered
    prefix of events that should be applied to bring that snapshot up to
    date, per steps 3-5 above. Returns `[]` if no buffered event straddles
    `lastUpdateId` yet -- the caller should keep buffering and retry with
    a fresh snapshot, not treat this as an error.
    """
    applicable = []
    for event in buffered_events:
        if event["u"] <= last_update_id:
            continue  # already reflected in the snapshot
        if not applicable:
            if event["U"] <= last_update_id + 1 <= event["u"]:
                applicable.append(event)
            # else: arrives after the snapshot's coverage window with a
            # gap before it -- drop it, wait for a later retry.
            continue
        if event["U"] != applicable[-1]["u"] + 1:
            break  # gap mid-sequence -- stop; this prefix is the most we can apply
        applicable.append(event)
    return applicable


class BinanceBookReconciler:
    def __init__(
        self,
        symbol: str,
        depth_limit: int = 1000,
        initial_buffer_seconds: float = 2.0,
        resync_recheck_seconds: float = 1.0,
        snapshot_max_age_seconds: float = 20.0,
    ):
        self.symbol = symbol.upper()
        self.depth_limit = depth_limit
        self.initial_buffer_seconds = initial_buffer_seconds
        # How often to recheck the (growing) buffer against the current
        # snapshot -- cheap, no network call, so this can be frequent.
        self.resync_recheck_seconds = resync_recheck_seconds
        # How long to keep rechecking against one fetched snapshot before
        # concluding it's gone stale (e.g. a long connection hiccup) and
        # fetching a new one -- see Bug 3 in the module docstring for why
        # this must NOT be "every recheck".
        self.snapshot_max_age_seconds = snapshot_max_age_seconds
        self.book = OrderBook("binance", self.symbol)

        self._pending: list[dict] = []  # buffered, not-yet-applied events; only
        # cleared on a fresh connection or a successful reconciliation --
        # never discarded just because one resync attempt failed (see Bug 2).
        self._pending_lock = threading.Lock()

        self._synced = False
        self._last_u: int | None = None
        self._resyncing = False
        self._resync_state_lock = threading.Lock()
        self._snapshot: dict | None = None
        self._snapshot_fetched_at: float | None = None

        self._ws: websocket.WebSocketApp | None = None
        self._on_update = None  # optional callback(book) invoked after each apply

    def _fetch_snapshot(self) -> dict:
        resp = requests.get(
            REST_URL, params={"symbol": self.symbol, "limit": self.depth_limit}, timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    def _apply_event(self, event: dict) -> None:
        for price, qty in event["b"]:
            self.book.apply_level("bid", float(price), float(qty))
        for price, qty in event["a"]:
            self.book.apply_level("ask", float(price), float(qty))
        self.book.last_update_time = datetime.fromtimestamp(event["E"] / 1000, tz=timezone.utc)
        if self._on_update:
            self._on_update(self.book)

    def _schedule_resync(self, delay: float = 0.0) -> None:
        with self._resync_state_lock:
            if self._resyncing:
                return
            self._resyncing = True
        threading.Timer(delay, self._attempt_resync).start()

    def _attempt_resync(self) -> None:
        # Only fetch a fresh snapshot if we don't already have one in
        # flight for this resync episode, or the one we have is old
        # enough to be considered stale (Bug 3: re-fetching a fresh
        # snapshot on every retry chases a moving target and can never
        # converge if the real update-ID growth rate outpaces message
        # arrival, which is the common case here).
        snapshot_age = (
            time.monotonic() - self._snapshot_fetched_at if self._snapshot_fetched_at else None
        )
        need_new_snapshot = self._snapshot is None or (
            snapshot_age is not None and snapshot_age >= self.snapshot_max_age_seconds
        )

        if need_new_snapshot:
            try:
                self._snapshot = self._fetch_snapshot()
                self._snapshot_fetched_at = time.monotonic()
            except Exception as exc:
                print(f"[binance] snapshot fetch failed ({exc}); retrying in {self.resync_recheck_seconds}s")
                with self._resync_state_lock:
                    self._resyncing = False
                self._schedule_resync(delay=self.resync_recheck_seconds)
                return

        snapshot = self._snapshot
        last_update_id = snapshot["lastUpdateId"]
        with self._pending_lock:
            buffered_snapshot = list(self._pending)

        applicable = reconcile_events(buffered_snapshot, last_update_id)

        if not applicable:
            print(
                f"[binance] no buffered event straddles lastUpdateId={last_update_id} yet "
                f"({len(buffered_snapshot)} buffered) -- rechecking in {self.resync_recheck_seconds}s"
            )
            with self._resync_state_lock:
                self._resyncing = False
            self._schedule_resync(delay=self.resync_recheck_seconds)
            return

        self.book.load_snapshot(
            bids=snapshot["bids"], asks=snapshot["asks"], timestamp=datetime.now(timezone.utc)
        )
        for event in applicable:
            self._apply_event(event)
        self._last_u = applicable[-1]["u"]

        # Anything in buffered_snapshot *before* the applied run was
        # genuinely stale (already covered by the snapshot) and must be
        # discarded, not replayed -- reconcile_events already dropped
        # those. Only what comes strictly *after* the applied run (either
        # because reconcile_events stopped at a real gap, or because it
        # arrived in self._pending after our copy was taken) still needs
        # to go through the normal live-continuity path.
        last_applied_index = next(
            idx for idx, event in enumerate(buffered_snapshot) if event is applicable[-1]
        )
        tail_from_snapshot = buffered_snapshot[last_applied_index + 1:]
        with self._pending_lock:
            newly_arrived = self._pending[len(buffered_snapshot):]
            self._pending = []
        leftover = tail_from_snapshot + newly_arrived

        self._synced = True
        self._snapshot = None
        self._snapshot_fetched_at = None
        with self._resync_state_lock:
            self._resyncing = False
        print(f"[binance] synced (applied {len(applicable)} buffered events)")

        for event in leftover:
            self._apply_live_event(event)

    def _apply_live_event(self, event: dict) -> None:
        """Apply one event while synced, enforcing U == last_u + 1 continuity."""
        if event["U"] != self._last_u + 1:
            print(f"[binance] gap detected (U={event['U']}, expected {self._last_u + 1}); resyncing")
            self._synced = False
            self._snapshot = None
            self._snapshot_fetched_at = None
            with self._pending_lock:
                self._pending = [event]
            self._schedule_resync()
            return
        self._apply_event(event)
        self._last_u = event["u"]

    def _on_open(self, _ws) -> None:
        self._synced = False
        self._snapshot = None
        self._snapshot_fetched_at = None
        with self._pending_lock:
            self._pending = []
        with self._resync_state_lock:
            self._resyncing = False
        self._schedule_resync(delay=self.initial_buffer_seconds)

    def _on_message(self, _ws, message):
        event = json.loads(message)
        if self._synced:
            self._apply_live_event(event)
        else:
            with self._pending_lock:
                self._pending.append(event)

    def _on_close(self, _ws, close_status_code, close_msg):
        print(f"[binance] websocket closed (code={close_status_code}, msg={close_msg}); will reconnect")

    def _on_error(self, _ws, error):
        print(f"[binance] websocket error: {error}")

    def run_forever(self, on_update=None, reconnect_delay: float = 2.0) -> None:
        """Blocking; runs until the process exits (meant to be called from
        a daemon thread via `start()`). Reconnects on any disconnect."""
        self._on_update = on_update
        url = STREAM_URL.format(symbol=self.symbol.lower())
        while True:
            self._ws = websocket.WebSocketApp(
                url, on_open=self._on_open, on_message=self._on_message,
                on_close=self._on_close, on_error=self._on_error,
            )
            self._ws.run_forever()
            print(f"[binance] reconnecting in {reconnect_delay}s...")
            time.sleep(reconnect_delay)

    def start(self, on_update=None) -> threading.Thread:
        thread = threading.Thread(
            target=self.run_forever, kwargs={"on_update": on_update}, daemon=True
        )
        thread.start()
        return thread
