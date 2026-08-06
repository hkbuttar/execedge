# Risk layer

Two controls, both cross-cutting: they wrap *any* algorithm's output
inside `backtest.simulator.OrderSlicingSimulator`, rather than being
baked into TWAP/VWAP/AC/RL individually. Off by default — nothing here
changes existing backtest behavior unless explicitly enabled.

## Why the simulator, not the algorithm

`ExecutionAlgorithm.slice()` is static/up-front (see
`backtest/algorithm.py`): it returns the whole child-order schedule
before any fills happen. A kill switch that reacts to real-time
conditions — this step's realized volatility, this run's cumulative cost
so far — needs a hook that sees each child order at its own moment in
time, not the whole schedule computed in advance. `OrderSlicingSimulator.run()`
is the only place in this project that walks child orders forward through
real time one at a time, so that's where both controls live.

## Participation-rate limit (`participation_limit.py`)

Caps each child order at `max_participation_rate` of real historical
volume in its own time window (`volume_lookup.py`, backed by
`data.fetch_volume`'s output). Quantity above the cap is **not**
resubmitted or rescheduled to a later slice — it's simply not executed,
same as any other under-filled order in this project, which means it
flows into the existing implementation-shortfall opportunity-cost
accounting (`backtest/metrics.py`). Exceeding the limit has a real,
visible cost in the report; that's what makes it a limit rather than a
suggestion.

**Disclosed simplification**: `data.fetch_volume`'s real data is hourly
(or whatever `--interval` it was fetched at), but child orders are sliced
far more finely. There's no real sub-hour volume in this project's
pipeline to check against directly, so `volume_between()` prorates each
overlapping bar's real volume by the fraction of the bar's duration a
query window covers — an assumption of uniform intra-bar volume, not a
measurement. The time-of-day findings (`data/time_of_day.py`) are
evidence real volume is *not* uniform across hours, so it's very
unlikely to be perfectly
uniform within one either. Treat participation estimates from this as
directionally right, not precise to the second.

## Kill switch (`kill_switch.py`, `triggers.py`)

Once tripped, no further child orders are submitted for the rest of that
run — the remainder is charged via opportunity cost, same mechanism as
the participation limit. **Manual reset only**: `reset()` refuses to run
without an explicit `confirm=True`, and nothing in this codebase calls it
automatically. There is no auto-resume.

Two trigger conditions, both computed from data the simulator already
tracks per step, no new data source needed:

- `volatility_trigger(max_realized_vol)` — halts if recent realized
  volatility (real book mid-price returns, `lob.features.RealizedVolTracker`)
  exceeds the threshold.
- `shortfall_trigger(max_cumulative_cost_bps)` — halts if cumulative
  implementation-shortfall cost so far exceeds the threshold, in bps of
  arrival notional.

The kill switch itself is trigger-agnostic — `OrderSlicingSimulator`
evaluates whatever trigger list you pass it and calls `.trip()` on the
first one that fires ("first trip wins": the reason and timestamp of the
*first* trigger to fire are kept, not overwritten by a later one in the
same run).

## Usage

```
python3 -m backtest.run_backtest \
    --book-history lob/raw/binance_book_snapshots.jsonl \
    --side buy --quantity 1.0 --algorithm twap --n-slices 10 \
    --start-offset-seconds 0 --duration-seconds 300 \
    --temporary-impact-coef 0.0 --permanent-impact-coef 0.0 \
    --participation-limit 0.1 \
    --kill-switch-max-vol 0.05 --kill-switch-max-shortfall-bps 25
```

`--participation-limit` reuses `--volume-csv`/`--volume-interval` (same
flags VWAP uses) since it's the same real volume data source. Either
kill-switch flag alone is enough to enable the kill switch; pass both to
combine them (first one to fire wins).

## Tests

`tests/test_volume_lookup.py`, `tests/test_participation_limit.py`,
`tests/test_kill_switch.py`, `tests/test_triggers.py` cover each module
in isolation; `tests/test_risk_simulator_integration.py` exercises both
controls through the actual simulator against synthetic book histories —
including a pre-tripped kill switch halting before any fill, a
trigger-based halt partway through a run, and a participation limit
visibly capping executed quantity.

## Not yet implemented

- No risk control is regime-aware (the calm/normal/volatile labels from
  `data/regimes.py` aren't consulted here) — a fixed `max_realized_vol`
  threshold applies uniformly regardless of what regime the market is
  actually in.
- No per-venue limits for multi-venue routing (`venues/`) yet — today's
  participation limiter and kill switch apply to a single simulator run
  against a single venue's book history.
