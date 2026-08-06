# Multi-venue fragmentation & real transaction costs

Binance, Coinbase, and Kraken as three genuinely distinct real venues —
different real order books (already true from order book reconstruction)
and, new here, different real published fee schedules. Every algorithm
gets a venue-routing decision *alongside* slicing, without any algorithm
needing to change.

## Real fee schedules — verified 2026-08-06 (see `fees.py` docstring for full citations)

| Venue    | Maker | Taker | Source |
|----------|-------|-------|--------|
| Binance  | 0%    | 0.02% | Primary, fetched directly: blog.binance.us (fee change effective 2026-04-22) |
| Coinbase | 0.40% | 0.60% | Coinbase's own fee pages returned HTTP 403 to direct fetch (bot-blocked) — cross-verified across two independent secondary sources instead |
| Kraken   | 0.40% | 0.80% | Primary, fetched directly: kraken.com/features/fee-schedule, Tier 1 (full 17-tier table retrieved and checked for monotonicity) |

**The headline finding, and it's real, not a modeling artifact**:
Binance.US's taker fee is roughly **30-40x lower** than Coinbase's or
Kraken's base retail tier. That's large enough to dominate most routing
decisions outright — see below.

These are each venue's *base* (lowest, no-volume-history) retail tier.
Real trading desks with meaningful 30-day volume land in far lower tiers
on all three (Kraken's own table runs from 0.80% taker at Tier 1 down to
0.05% at $500M+) — this project has no real trading history to justify
assuming any particular higher tier, so it uses the tier every account
starts at. This project's fill model always crosses the spread
(`backtest/fill_model.py` walks the book, never rests as a maker order),
so every simulated fill is charged the **taker** fee; maker fees are
recorded for completeness but never applied.

## Architecture: routing is layered alongside slicing, not into it

`ExecutionAlgorithm.slice()` (TWAP/VWAP/Almgren-Chriss/RL) stays exactly
as it was — venue-agnostic, deciding size and timing only.
`venues/router.py`'s `VenueRouter` asks, for each already-sized,
already-timed child order, which of the three venues to send it to;
`venues/multi_venue_simulator.py`'s `MultiVenueSimulator` is the thing
that actually asks the router and executes against whichever venue's
real book was chosen, at that venue's real taker fee. This mirrors the
risk layer: a cross-cutting wrapper around the simulator, not a rewrite
of every algorithm.

**This is why the RL policy slots in with zero code changes.**
`rl.policy_algorithm.TrainedPolicyAlgorithm` still decides *how much to
trade when*, using its own venue's real signals exactly as trained;
`MultiVenueSimulator` decides *where* to actually execute those
already-decided child orders, using all three venues' real quotes and
fees. RL doesn't need to know routing exists for this to work — it's the
same `.slice(parent)` call every other algorithm gets, then routed the
same way.

Two routers ship here:

- **`SingleVenueRouter`** — always the same venue. Not really "routing"
  at all; the three naive baselines (`always_binance`/`always_coinbase`/
  `always_kraken`) this project compares smart routing against.
- **`BestEffectivePriceRouter`** — at each child order's own real
  timestamp, compares real quoted touch price *plus* that venue's real
  taker fee across all three venues, picks the lowest all-in cost. "Smart"
  as this project defines it: real quotes and real fees at the same real
  moment, not a forecast of anything.

Implementation shortfall's arrival/end price benchmark comes from a
single **reference venue** (`--reference-venue`, default binance), even
when child orders route elsewhere — mirroring how a real desk benchmarks
against one reference price regardless of which venue actually filled the
order. The alternative (a synthetic consolidated "best of all venues"
reference price) would make the benchmark depend on the same routing
question being evaluated, muddying exactly what's being measured.

## Usage

```
python3 -m lob.run_reconstruction --venues binance coinbase kraken --record-depth-levels 50 --minutes 30

python3 -m venues.run_multi_venue_backtest \
    --binance-book-history lob/raw/binance_book_snapshots.jsonl \
    --coinbase-book-history lob/raw/coinbase_book_snapshots.jsonl \
    --kraken-book-history lob/raw/kraken_book_snapshots.jsonl \
    --side buy --quantity 1.0 --algorithm twap --n-slices 10 \
    --start-offset-seconds 0 --duration-seconds 300 \
    --temporary-impact-coef 0.0 --permanent-impact-coef 0.0
```

Runs all four routing strategies in one command and prints a direct
comparison — "does smarter routing meaningfully reduce cost," answered
honestly either way: if `best_price` doesn't beat the
best single venue, that's exactly what gets printed, not hidden.
`--algorithm` also accepts `vwap`/`ac` with the same sub-flags as
`backtest.run_backtest` (`--volume-csv`, `--ac-calibration`, etc.).

## What the smoke test found

Against a synthetic setup where Binance had a *slightly worse* raw quote
than Coinbase/Kraken but its real fee advantage, `best_price` routing
correctly picked Binance on every single child order — its fee edge
(2 bps vs 60-80 bps) outweighed a few bps of raw-price disadvantage many
times over. In that case smart routing didn't improve on simply always
using Binance, because Binance's fee advantage alone already dominates.
Whether that holds on real recorded data (where raw-price gaps between
venues could plausibly be much smaller than the fee gap, or occasionally
larger) is a real empirical question this project hasn't run against live
data yet — that's on you to check with the command above once you have a
three-venue recording.

## Cross-venue validation: does the algorithm ranking replicate?

Different question from routing: instead of moving one execution across
venues, `cross_venue_validation.py` runs the *same algorithm comparison*
independently on each venue's own real data — Binance judged entirely on
Binance's book, Coinbase on Coinbase's, Kraken on Kraken's, no
cross-venue leakage — and checks whether the ranking (does Almgren-Chriss
beat VWAP, does VWAP beat TWAP) is consistent, or diverges by venue.

This is this project's stand-in for a cross-asset-class robustness check.
The original plan for a LOBSTER-based branch would have validated
findings against equities; since this project is crypto-only by design,
robustness gets checked across the one axis of real variation it
actually has — three genuinely different venues — instead.

`rank_scenarios` extracts one venue's ordering (best/lowest shortfall
first) from `backtest.experiment`'s bootstrap output; `compare_rankings_across_venues`
compares orderings across venues, restricted to whichever scenarios are
common to all of them (a venue missing real volume data, and therefore
missing `vwap`, shouldn't block comparing the scenarios it does have).
Reports honestly either way: `RANKING IS CONSISTENT` prints the shared
order; `RANKING DIVERGES` prints exactly which venue disagrees with
which, not just that something differs.

```
python3 -m venues.run_cross_venue_validation \
    --binance-book-history lob/raw/binance_book_snapshots.jsonl \
    --coinbase-book-history lob/raw/coinbase_book_snapshots.jsonl \
    --kraken-book-history lob/raw/kraken_book_snapshots.jsonl \
    --side buy --quantity 1.0 --n-slices 5 \
    --episode-duration-seconds 60 --stride-seconds 60 \
    --temporary-impact-coef 0.0 --permanent-impact-coef 0.0
```

Smoke-tested against synthetic three-venue data end to end (both the
consistent and divergent cases produce the expected report).

`backtest/scenarios.py`'s `build_algorithm_scenarios` (naive/twap/vwap/
ac_literature/ac_empirical, matching whatever real volume/AC-calibration
inputs are available for that venue) is shared between this and
`backtest.run_experiment` — refactored out so both tools build the
identical scenario set instead of drifting apart.

## Tests

`tests/test_venue_fees.py`, `tests/test_venue_router.py`,
`tests/test_multi_venue_simulator.py` — including a fee-vs-price
tradeoff test (`test_best_price_router_accounts_for_fee_outweighing_raw_price_buy`)
and confirmation that a fee is actually applied to fill prices, not just
computed and discarded. `tests/test_scenarios.py` and
`tests/test_cross_venue_validation.py` cover the cross-venue validation
pieces above, including the consistent-ranking, divergent-ranking, and
common-scenarios-only cases.

## Not yet implemented

- No venue-level participation limits or kill switches (the risk layer
  is single-venue; extending it across venues would need its own design
  pass, not done here).
- Withdrawal/deposit costs, network fees, or latency differences between
  venues aren't modeled — only trading (maker/taker) fees.
- The empirical Almgren-Chriss calibration (`--ac-calibration empirical`)
  still estimates impact from the reference venue's own book only, even
  when child orders route elsewhere.
