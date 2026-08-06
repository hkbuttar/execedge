# Order-slicing simulator (Step 4)

The core backtesting harness: given a parent order and an execution
algorithm, slice into child orders, submit each against the real
reconstructed order book at its real historical timestamp, and score the
result on implementation shortfall.

## Methodology — the fill model's full mechanics

A hypothetical parent order never actually existed in the historical
record. Everything else in this pipeline (the book itself, its prices,
its resting sizes) is real; the fill model is the one necessary,
disclosed simplification layered on top of it, and its mechanics are:

1. **Book walk against real resting liquidity.** A child order consumes
   real recorded price levels in order (best first) exactly as if it had
   rested against that book. This part isn't a modeling assumption, it's
   arithmetic against real depth: if the historical top-of-book ask was
   100.0 for 1.0 BTC and 100.5 for 2.0 BTC, a 1.5 BTC buy child order
   fills 1.0 @ 100.0 and 0.5 @ 100.5, using real recorded prices.

2. **Temporary impact**, applied on top of the walked price: every fill
   from a child order gets the same multiplicative adjustment,
   `temporary_impact_coef * sqrt(child_qty / visible_liquidity)`, in the
   direction that hurts the order (buys pay more, sells receive less).
   This is the square-root-law functional form flagged as the most
   literature-credible option in `data/README.md`'s impact-parameter
   placeholder (validated in equities research and at least one direct
   Bitcoin metaorder study). Applied once per child order rather than
   per individual price level consumed within it — a simplicity/
   auditability tradeoff, not a claim that per-level impact would be
   less realistic.

3. **Permanent impact**, tracked per parent-order execution
   (`FillModelRun.permanent_offset`): after each child order, a price
   offset accumulates and shifts every subsequent child order's fills
   within that *same run*, representing a lasting reference-price shift
   from cumulative footprint. It is never written back into the shared
   `OrderBook` — the real historical record stays untouched for other
   backtests replaying the same window.

4. **Unfilled quantity is reported, not fabricated.** If a child order's
   size exceeds every real level currently in the book, the remainder is
   returned as `unfilled_quantity` rather than assigning it an invented
   price beyond what the real record shows. The simulator charges this
   against the parent order via implementation shortfall's opportunity-
   cost term (see below), so an algorithm that routinely can't get filled
   doesn't look artificially cheap.

`temporary_impact_coef` and `permanent_impact_coef` have **no default
value** — `backtest/fill_model.py` and the `run_backtest` CLI both
require them explicitly. Step 1 deliberately didn't hardcode literature
impact numbers without a citation, and Step 7 is where literature-derived
and empirically-estimated Almgren-Chriss coefficients actually get
produced and compared. Pass `0.0` for both to see pure book-walk behavior
— that's a conscious choice made visible in the command, not a silent
default masking an uncalibrated model as if it were finished.

## Implementation shortfall (Perold, 1988)

```
total_cost = executed_cost + opportunity_cost
executed_cost    = sum((fill_price - arrival_price) * fill_qty * side_sign)
opportunity_cost = unfilled_qty * (end_price - arrival_price) * side_sign
```

`side_sign` is +1 for buy, -1 for sell, so `executed_cost` is positive
when a fill went against the order (paid more on a buy, received less on
a sell) and `opportunity_cost` charges (or credits — it can be negative)
any quantity never filled, marked against the price at the parent
order's window end versus its arrival price. This is what makes
shortfall comparable across algorithms that complete different fractions
of the order, which matters once Step 5+ starts comparing TWAP/VWAP/AC
against each other.

## Components

```
backtest/
├── order.py          # ParentOrder, ChildOrder, Fill
├── algorithm.py       # ExecutionAlgorithm interface + NaiveMarketOrderAlgorithm baseline
├── book_history.py    # replays lob/run_reconstruction.py's recorded depth snapshots by timestamp
├── fill_model.py       # the book-walk + impact mechanics described above
├── metrics.py         # implementation_shortfall
├── simulator.py        # OrderSlicingSimulator: ties the above together
└── run_backtest.py    # CLI
```

`NaiveMarketOrderAlgorithm` (dumps the whole parent order as one child
order at start_time) is a deliberately naive baseline that exists only to
exercise this harness end to end — maximum market impact, zero timing
risk. It is not TWAP. Step 5 implements TWAP as the actual control
algorithm this project benchmarks against.

## Prerequisite: a recorded book history

The simulator replays previously-recorded depth snapshots — it does not
connect to a venue itself. Record some first:

```
python3 -m lob.run_reconstruction --venues binance --record-depth-levels 50 --minutes 30
```

Then run a backtest against it:

```
python3 -m backtest.run_backtest \
    --book-history lob/raw/binance_book_snapshots.jsonl \
    --side buy --quantity 1.0 \
    --start-offset-seconds 0 --duration-seconds 300 \
    --temporary-impact-coef 0.0 --permanent-impact-coef 0.0
```

## Known limitations / not yet done

- No venue fees or tick/lot-size rounding on child order prices/sizes yet
  (Step 10, and noted as outstanding in `lob/README.md`).
- The impact model applies one adjustment per child order rather than
  per price level walked within it (see mechanics above) — a deliberate
  simplicity choice, revisit if Step 7's empirical calibration suggests
  it matters.
- `ExecutionAlgorithm.slice()` is static/up-front; no algorithm here
  re-slices dynamically based on fills so far.
- Tested entirely offline against synthetic book histories with known
  ground truth (`tests/test_fill_model.py`, `tests/test_metrics.py`,
  `tests/test_book_history.py`, `tests/test_simulator.py`) — running it
  against a real recorded book history (the command above) hasn't been
  done yet, that's on you to try.
