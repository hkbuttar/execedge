# Order book reconstruction

Each venue ships incremental order book updates over its own websocket
protocol, with a genuinely different mechanism for detecting/recovering
from a missed message. `lob/order_book.py` is the shared, venue-agnostic
book (bids/asks keyed by price, best-bid/ask, mid, spread, imbalance);
`lob/reconcile/{venue}.py` translates each venue's specific wire format
and gap-detection scheme into calls against it.

## Per-venue reconciliation semantics

| Venue    | Gap detection                                   | Recovery                                       |
|----------|---------------------------------------------------|--------------------------------------------------|
| Binance  | REST snapshot `lastUpdateId` + diff events' `U`/`u` sequence bounds; a live event's `U` must equal the previous event's `u + 1` | Re-fetch REST snapshot, drain buffered events against its `lastUpdateId` |
| Coinbase | None needed — single ordered websocket stream, `snapshot` message then ordered `l2update` messages | Reconnect + resubscribe; the fresh `snapshot` message replaces local state |
| Kraken   | CRC32 `checksum` of top-10 levels shipped on every `update` message, recomputed locally and compared | Checksum mismatch is logged (`checksum_mismatches` counter); resubscribing gets a fresh `snapshot` |

Binance's scheme is the most involved because REST (snapshot) and
websocket (diffs) are two separate connections that need to be stitched
together in time; Coinbase sidesteps this entirely by sending the
snapshot down the same ordered stream; Kraken sidesteps sequence-ID
bookkeeping in favor of a content checksum, which catches drift instead
of dropped messages per se.

The Kraken checksum implementation (`lob/reconcile/kraken.py`,
`compute_checksum`) is verified against Kraken's own published worked
example in `tests/test_kraken_checksum.py`.

**Binance's REST+websocket stitching had four real, live bugs**, found
only by actually running it against a live feed -- review alone missed
all four, and each fix alone was insufficient until the next one landed:

1. The original code called `requests.get()` for the REST snapshot
   directly inside the websocket's `on_message` callback.
   `websocket-client` delivers all messages on a single callback thread,
   so while that HTTP call blocked, no new events could be buffered --
   by the time the snapshot arrived, the buffer held only the single
   event that triggered the fetch, which essentially never straddles the
   snapshot's `lastUpdateId`. Sync never completed, and a 3-minute
   recording produced a 0-row output file with no error. Fixed by moving
   the fetch to a background thread.
2. That fix alone still failed silently: every failed resync attempt
   *discarded* the buffered backlog, so each retry restarted with only
   ~1 fresh event again -- the same race as bug 1, just spread across
   many silent attempts instead of one. A second 5-minute recording,
   after fix 1, still produced only the original 41 rows from before the
   fix. Fixed: buffered-but-unconfirmed events are now only ever cleared
   on a fresh connection or a successful reconciliation, never on
   failure, so the backlog can only grow between retries. Found while
   testing this fix: the leftover-event computation misclassified
   genuinely stale events (already covered by the snapshot, correctly
   dropped) as unapplied leftovers, replaying them and immediately
   detecting a false gap right after successfully syncing -- fixed by
   computing leftover from the applied run's position in the buffer
   rather than by set difference.
3. Confirmed live with 1+2 fixed and logging now visible: every retry
   re-fetched a *fresh* snapshot -- a new `lastUpdateId` reflecting "now"
   on every attempt. Binance.US's real book advances by 10s-200s of
   internal update IDs per second while the plain diff stream delivers
   only ~1 message/second, so a freshly-fetched target was *always*
   already ahead of everything buffered -- confirmed live as 16 retries,
   buffer correctly growing to 33 events (proving fix 2 worked), zero
   straddles found, because the target kept moving faster than the
   buffer could catch up. Fixed: the snapshot is now fetched once per
   resync episode and *reused* across retries, only replaced if it goes
   unmatched for `snapshot_max_age_seconds` (default 20s -- a real
   connection hiccup, not the everyday case). Verified by simulation with
   realistic variable-width update-ID spans matching the observed live
   growth rate: converges within a handful of buffered messages.

The core reconciliation math is a pure function (`reconcile_events`, no
I/O), covered by `tests/test_binance_reconcile.py` along with
class-level tests for the buffering/leftover/snapshot-reuse behavior
(mocking the network call, no live connection needed for these,
including an explicit regression test asserting `_fetch_snapshot` is
called exactly once across multiple retries). What's still genuinely
untested without a live connection is the websocket threading/timing
itself -- that's on you to run and confirm, again.

Coinbase's reconciliation *logic* is covered by
`tests/test_coinbase_reconcile.py`: a scripted, real-shaped sequence of
`snapshot`/`l2update` messages (Coinbase's own published `level2` channel
schema) replayed through `_on_message`, checking book state at
checkpoints — level additions, updates, zero-size removals, mixed-side
updates in one message, non-book message types being ignored, and a
fresh `snapshot` after a simulated reconnect fully replacing rather than
merging with prior state. What's still genuinely untested without a live
connection is the actual websocket behavior itself (subscribe timing,
real reconnect behavior) — same caveat as Binance, run it yourself to
find out (see below).

**All three clients also had a second, related gap**: none of them
reconnected on a dropped websocket connection, `run_forever()` just
returned and the recording silently stopped producing data for whatever
remained of the requested duration — with no error, no log line,
nothing. This surfaced in practice: a `--minutes 3` (180s) Binance
recording actually only captured 43 seconds before the connection
dropped, and nothing indicated that had happened until a downstream RL
step failed with "0 episode windows available." All three `run_forever()`
methods now loop and reconnect on any close/error, with a printed
message when it happens, rather than dying quietly.

## Microstructure features (`lob/features.py`)

Per book update: mid-price, spread, order book imbalance (top-N levels,
configurable), and a rolling realized volatility of mid-price log returns
(`RealizedVolTracker`). Realized vol here is per-observation, not
annualized to a fixed time unit — update arrival rate differs across
venues and isn't evenly spaced, so a fixed annualization factor would be
misleading. Regime identification (`data/regimes.py`) resamples this to
comparable time buckets before comparing regimes across venues.

## Running it

This is a long-lived process (holds open websocket connections) — you
run it, for as long as you want a real feature history:

```
python3 -m lob.run_reconstruction --venues binance coinbase kraken --minutes 30
```

Drop `--minutes` to run until Ctrl-C. Output: `lob/raw/{venue}_features.jsonl`,
one line per book update, feeding regime identification and later joins
against real volume data.

Add `--record-depth-levels N` to also persist the top-N real bid/ask
levels to `lob/raw/{venue}_book_snapshots.jsonl` — what `backtest/`
replays for hypothetical order fills. Add `--database-url <url>` (or set
`$DATABASE_URL`) alongside it to *also* write those same depth snapshots
to Postgres — lets a deployed instance's book history survive a restart
instead of only living on disk, and lets a local recording run write
straight into a shared/deployed database. Additive: the JSONL file is
still written either way. See `db/README.md`.

## Known limitations / not yet done

- Only top-N *levels* are persisted (`--record-depth-levels`), not the
  raw diff messages themselves — if you want to replay exact book states
  at arbitrary depth later (e.g. for replay-based correctness tests), the
  underlying diffs aren't saved, only the reconstructed top-N snapshot
  after each one is applied.
- Tick/lot size rounding for order-slicing isn't handled here; each
  venue's minimum increment still needs to be pulled from its own
  exchange-info endpoint before order slicing needs it.
- `book_at_or_before()` (`backtest/book_history.py`) silently returns the
  *last* recorded snapshot when asked for a timestamp past the end of
  the recorded history, rather than raising. Combined with a dropped
  connection cutting a recording short, this meant a `--minutes 3`
  recording that actually only captured 43 seconds before disconnecting
  still let downstream backtests "succeed" against a 120-second window,
  silently reusing the last real snapshot for the missing ~77 seconds
  instead of erroring. The disconnect itself is now fixed (see below) and
  logged loudly if it happens again, but the silent-clamp behavior on the
  *read* side is still there — worth tightening if this trips anyone up
  again.
