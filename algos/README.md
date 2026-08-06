# Execution algorithms (Steps 5-7)

Concrete strategies against `backtest.algorithm.ExecutionAlgorithm` (see
`backtest/README.md` for the harness they run inside). This is
distinguished from `backtest.algorithm.NaiveMarketOrderAlgorithm`, which
is a harness-exercise baseline, not a real strategy.

## TWAP (`twap.py`) — Step 5, the control

Equal-size slices at regular time intervals: `parent.quantity / n_slices`
per child, spaced `duration / n_slices` apart, starting at
`parent.start_time`. It ignores everything -- the real volume profile,
current book depth, any impact model -- by design. Every other algorithm
in this project (VWAP, Almgren-Chriss, RL) is benchmarked against it;
outperforming TWAP means demonstrating a real edge from whatever
information that algorithm uses and TWAP doesn't.

```
python3 -m backtest.run_backtest \
    --book-history lob/raw/binance_book_snapshots.jsonl \
    --side buy --quantity 1.0 --algorithm twap --n-slices 10 \
    --start-offset-seconds 0 --duration-seconds 300 \
    --temporary-impact-coef 0.0 --permanent-impact-coef 0.0
```

`tests/test_algorithm_comparison.py` demonstrates concretely why slicing
matters: against a synthetic thin book, a single-shot order walks five
price levels for an average fill of 102.0, while TWAP's smaller slices
each fit inside the best level, averaging 100.0. That test also documents
a real caveat worth internalizing before reading too much into any
TWAP-vs-naive comparison against a *live* recorded history: the simulator
replays independently-recorded real snapshots and does not deplete a
level for a later child order just because an earlier one consumed it at
a different timestamp. Against a real recording the book moves between
snapshots for real reasons, so this isn't "free" liquidity in practice --
but it's worth being aware the mechanism exists.

## VWAP (`vwap.py`) — Step 6, built on the real volume curve

Same regular-interval slicing as TWAP (n_slices equal-duration buckets
across the window), but each bucket's size is weighted by its hour-of-
day's real historical volume share (`data/volume_profile.py`) instead of
1/n_slices. The weights come from `data.time_of_day`'s ANOVA (Step 3):

- **No significant time-of-day effect found** → the profile is flat
  (every hour weighted 1/24) → VWAP's sizing is mathematically identical
  to TWAP. Not a fallback bug: there's nothing in the real data to shape
  the curve around, so it shouldn't invent one.
- **Significant effect found** → the profile uses the real empirical
  per-hour volume shares, so slices scheduled in historically high-volume
  hours get proportionally larger child orders.

This is "let the data decide" enforced in code rather than assumed:
equities' well-known open/close volume spike is never hardcoded anywhere
in this path.

One resolution limit worth knowing: the profile is hourly. A parent
order whose entire window sits inside one hour gets flat weighting
regardless of the profile — there's no finer real signal to differentiate
slices within that hour (`tests/test_vwap.py::test_within_single_hour_window_is_effectively_flat`
demonstrates this directly).

```
python3 -m data.fetch_volume --days 30 --interval 60
python3 -m backtest.run_backtest \
    --book-history lob/raw/binance_book_snapshots.jsonl \
    --side buy --quantity 1.0 --algorithm vwap --n-slices 10 \
    --start-offset-seconds 0 --duration-seconds 300 \
    --temporary-impact-coef 0.0 --permanent-impact-coef 0.0
```

(`--volume-csv` defaults to `data/raw/volume/{venue}_{symbol}_{volume-interval}m.csv`,
matching `data.fetch_volume`'s default output naming.)

## Not yet implemented

- **Almgren-Chriss** (Step 7): closed-form optimal trajectory, dual-
  calibrated (literature vs. empirically-estimated impact coefficients,
  compared directly).
