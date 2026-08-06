# Order book reconstruction (Step 2)

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
example in `tests/test_kraken_checksum.py`. The Binance and Coinbase
reconciliation *logic* has not been exercised against a live feed yet —
that requires actually holding a websocket connection open, which is on
you to run (see below), not something to fire off from here.

## Microstructure features (`lob/features.py`)

Per book update: mid-price, spread, order book imbalance (top-N levels,
configurable), and a rolling realized volatility of mid-price log returns
(`RealizedVolTracker`). Realized vol here is per-observation, not
annualized to a fixed time unit — update arrival rate differs across
venues and isn't evenly spaced, so a fixed annualization factor would be
misleading. Step 3 will need to resample this to comparable time buckets
before comparing regimes across venues.

## Running it

This is a long-lived process (holds open websocket connections) — you
run it, for as long as you want a real feature history:

```
python3 -m lob.run_reconstruction --venues binance coinbase kraken --minutes 30
```

Drop `--minutes` to run until Ctrl-C. Output: `lob/raw/{venue}_features.jsonl`,
one line per book update, feeding Step 3 (regime identification) and
later joins against Step 6's volume data.

## Known limitations / not yet done

- No persistence of raw depth diffs, only derived features — if you want
  to replay exact book states later (e.g. for Step 12's replay-based
  correctness tests), the diff messages themselves aren't being saved
  yet.
- No automatic reconnect/backoff on websocket drop for any of the three
  clients — `run_forever()` will end the thread on a connection error
  rather than retry.
- Tick/lot size rounding for order-slicing (Step 4) isn't handled here;
  each venue's minimum increment still needs to be pulled from its own
  exchange-info endpoint before that step.
