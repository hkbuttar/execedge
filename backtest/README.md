# Order-slicing simulator

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
require them explicitly. Real-data acquisition deliberately didn't
hardcode literature impact numbers without a citation, and the
Almgren-Chriss module is where literature-derived and
empirically-estimated coefficients actually get produced and compared.
Pass `0.0` for both to see pure book-walk behavior
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
of the order, which matters once TWAP/VWAP/AC are compared against each
other.

## Components

```
backtest/
├── order.py          # ParentOrder, ChildOrder, Fill
├── algorithm.py       # ExecutionAlgorithm interface + NaiveMarketOrderAlgorithm baseline
├── book_history.py    # replays lob/run_reconstruction.py's recorded depth snapshots by timestamp
│                          (from a file or, via open_book_history("db:<venue>"), Postgres -- see db/README.md)
├── fill_model.py       # the book-walk + impact mechanics described above
├── metrics.py         # implementation_shortfall
├── simulator.py        # OrderSlicingSimulator: ties the above together
├── bootstrap.py         # bootstrap_mean_ci
├── experiment.py         # generic regime-stratified scenario runner
├── scenarios.py         # naive/twap/vwap/ac_literature/ac_empirical scenario builder,
│                          shared with venues.cross_venue_validation
├── run_experiment.py    # statistical-rigor CLI
└── run_backtest.py    # CLI
```

`OrderSlicingSimulator` optionally takes a `participation_limiter` and/or
`kill_switch` (+ `kill_switch_triggers`) — the risk layer, see
`risk/README.md`. Both are cross-cutting: applied to whatever algorithm's
child orders are being walked through, at each child order's own point in
real time, since that's the only place in this project a genuinely
real-time control can hook in given `ExecutionAlgorithm.slice()`'s
static/up-front design (see below). Off by default.

`NaiveMarketOrderAlgorithm` (dumps the whole parent order as one child
order at start_time) is a deliberately naive baseline that exists only to
exercise this harness end to end — maximum market impact, zero timing
risk. It is not TWAP. TWAP (`algos/twap.py`) is the actual control
algorithm this project benchmarks against — see `algos/README.md`.

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

`--book-history` (every CLI here, and every `*book_history_path` field
in `backend/`) also accepts `db:<venue>` (e.g. `db:binance`) to read
from Postgres instead of a file — see `db/README.md` for why this
exists (a deployed instance's recorded history surviving a restart) and
exactly how `open_book_history()` dispatches between the two.

## Statistical rigor

Every backtest result so far has been a single run against a single real
window. This layer runs the same algorithm (or venue-routing strategy)
across *many* real historical windows — different real dates/sessions as
the source of variation, not a parametric assumption — and reports
implementation shortfall with a bootstrap confidence interval, optionally
stratified by the calm/normal/volatile regime labels (`data/regimes.py`).

`backtest/bootstrap.py`'s `bootstrap_mean_ci` is the primitive: resample
the observed per-window shortfall values with replacement many times
(default 2000), take the percentile bounds of the resulting distribution
of means. No assumption that per-window shortfall is normally
distributed, which it has no particular reason to be.

`backtest/experiment.py`'s `run_bootstrap_experiment` is deliberately
generic — a "scenario" is just a function from a real window to a
resulting shortfall bps number, so the same machinery covers algorithm
comparisons, venue-routing comparisons, or calibration-source
comparisons without hardcoding which axis is being compared.

**Scoping decision worth stating explicitly**: the goal here is "every
algorithm x regime x venue-routing x calibration-source combination."
`backtest/run_experiment.py` runs two separate comparisons
(algorithm-comparison, which already includes both AC calibration
sources as separate scenarios; and venue-routing-comparison, using TWAP
as a fixed representative algorithm) rather than one full combinatorial
grid across all four dimensions. A full cross-product would produce far
more rows than anyone could usefully read, and most of those cells would
have too few real windows to bootstrap meaningfully anyway — every cell
needs its *own* independent set of real historical windows, and
real windows are the one thing this project can't fabricate more of.

```
python3 -m lob.run_reconstruction --venues binance --record-depth-levels 50 --minutes 60
python3 -m data.fetch_volume --days 30 --interval 60
python3 -m data.analyze_regimes --interval 60 --vol-window 24
python3 -m backtest.run_experiment \
    --book-history lob/raw/binance_book_snapshots.jsonl \
    --side buy --quantity 1.0 --n-slices 5 \
    --episode-duration-seconds 60 --stride-seconds 60 \
    --temporary-impact-coef 0.0 --permanent-impact-coef 0.0 \
    --regimes-csv data/raw/regimes/binance_regimes.csv
```

Add `--binance-book-history`/`--coinbase-book-history`/`--kraken-book-history`
(all three) to also get the venue-routing comparison. Add
`--ac-volatility`/`--ac-risk-aversion`/`--ac-permanent-to-temporary-ratio`
(+ literature or empirical calibration flags, same as `run_backtest.py`)
to include `ac_literature`/`ac_empirical` scenarios.

Each printed row includes a `robust?` column — a stated heuristic
(`backtest/experiment.py`'s `is_robust`), not a formal significance test:
"robust" means the CI's width is less than half the absolute point
estimate. A "no" there means treat that row's conclusion, including its
sign, with real caution — this is the same "flag which findings are
robust vs. fragile" discipline the final results writeup needs, computed
here rather than left to eyeballing a table.

This module's algorithm-comparison scenarios (`backtest/scenarios.py`)
are reused one level up by `venues.cross_venue_validation`, which runs
the same comparison independently per venue and checks whether the
*ranking* of algorithms replicates across Binance/Coinbase/Kraken's real
data, rather than diverging — see `venues/README.md`.

## Known limitations / not yet done

- No tick/lot-size rounding on child order prices/sizes yet (noted as
  outstanding in `lob/README.md`); venue fees themselves are now handled
  separately by `venues/` for the multi-venue routing comparison.
- The impact model applies one adjustment per child order rather than
  per price level walked within it (see mechanics above) — a deliberate
  simplicity choice, revisit if the Almgren-Chriss empirical calibration
  suggests it matters.
- `ExecutionAlgorithm.slice()` is static/up-front; no algorithm here
  re-slices dynamically based on fills so far.
- The simulator replays independently-recorded real snapshots and does
  not deplete a level for a later child order just because an earlier
  one consumed it at a different timestamp — each timestamp's snapshot
  is real ground truth as recorded, not adjusted for the hypothetical
  order's own prior fills elsewhere in time. This can make time-sliced
  algorithms (TWAP, and later VWAP/AC) look better than they would in
  reality if the recorded history is coarse enough that the same
  liquidity appears to "reappear" verbatim across timestamps — see
  `algos/README.md`'s TWAP section and `tests/test_algorithm_comparison.py`
  for a concrete illustration of the effect and why it matters less
  against a real, finely-sampled recording.
- Tested entirely offline against synthetic book histories with known
  ground truth (`tests/test_fill_model.py`, `tests/test_metrics.py`,
  `tests/test_book_history.py`, `tests/test_simulator.py`) — running it
  against a real recorded book history (the command above) hasn't been
  done yet, that's on you to try. `open_book_history`'s `db:` dispatch
  path is additionally verified against a real Postgres instance —
  `tests/test_db_book_snapshots.py`, see `db/README.md`.
