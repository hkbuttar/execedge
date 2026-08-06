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

## Not yet implemented

- **VWAP** (Step 6): slice proportional to the real historical volume
  curve from `data/fetch_volume.py`, shaped by whatever
  `data/time_of_day.py` finds (flat if no real intraday pattern, curved
  if there is one).
- **Almgren-Chriss** (Step 7): closed-form optimal trajectory, dual-
  calibrated (literature vs. empirically-estimated impact coefficients,
  compared directly).
