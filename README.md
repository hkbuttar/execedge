# ExecEdge — Optimal Execution Algorithm Backtester

Optimal execution backtester for large crypto orders, built entirely on
real order book data from Binance, Coinbase, and Kraken. TWAP, VWAP (real
volume profiles), Almgren-Chriss (literature-calibrated + empirically
estimated impact), and an RL policy, benchmarked with statistical rigor.

## Why

Every trading desk with meaningful size to move faces the same problem:
how do you fill a large order without moving the market against
yourself? This project builds and rigorously benchmarks the standard
toolkit — TWAP, VWAP, Almgren-Chriss optimal execution, and a learned RL
policy — entirely on real historical order book data from crypto
exchanges, with every modeling assumption disclosed explicitly rather
than buried. Scoped to crypto specifically, both as the data source and
the asset class the findings speak to, not framed as a general equities
claim.

No API keys are required anywhere in this project — every venue
integration uses public, unauthenticated REST/websocket endpoints.

## Layout

```
execedge/
├── data/       real-data acquisition (Binance/Coinbase/Kraken depth + volume),
│                regime & time-of-day analysis, VWAP volume profiles
├── lob/        order book reconstruction from real exchange feeds,
│                microstructure features (spread, imbalance, realized vol)
├── algos/      TWAP, VWAP, Almgren-Chriss (dual-calibrated), impact calibration
├── rl/         gym environment, DQN execution policy, real historical episodes
├── backtest/   order-slicing simulator, fill model, implementation shortfall,
│                bootstrap confidence intervals, regime-stratified experiments
├── risk/       participation-rate limits, manual-reset-only kill switch
├── venues/     multi-venue routing, real fee schedules, cross-venue comparison
└── tests/      154 tests (138 run offline in any environment; 16 need
                 websocket-client installed to exercise the live reconciliation classes)
```

Each module has its own README with full methodology, citations, and
disclosed limitations — start there for depth on any piece:
[data/README.md](data/README.md), [lob/README.md](lob/README.md),
[algos/README.md](algos/README.md), [rl/README.md](rl/README.md),
[backtest/README.md](backtest/README.md), [risk/README.md](risk/README.md),
[venues/README.md](venues/README.md).

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# real depth snapshot + historical volume, no API keys needed
python3 -m data.fetch_depth
python3 -m data.fetch_volume --days 30 --interval 60
python3 -m data.analyze_regimes --interval 60 --vol-window 24

# record a live order book (long-running; holds a websocket open)
python3 -m lob.run_reconstruction --venues binance --record-depth-levels 50 --minutes 30

# backtest TWAP against the real recorded book
python3 -m backtest.run_backtest \
    --book-history lob/raw/binance_book_snapshots.jsonl \
    --side buy --quantity 1.0 --algorithm twap --n-slices 10 \
    --start-offset-seconds 0 --duration-seconds 300 \
    --temporary-impact-coef 0.0 --permanent-impact-coef 0.0
```

See each module's README for the rest of the pipeline: Almgren-Chriss
calibration, RL training/evaluation, the risk layer, multi-venue routing,
and the bootstrap-based statistical comparison.

## What's implemented

- **Real-data acquisition** — Binance, Coinbase, Kraken public depth and
  kline endpoints; regime (calm/normal/volatile) and time-of-day analysis
  on real volume.
- **Order book reconstruction** — per-venue diff/snapshot reconciliation
  (each venue's gap-detection scheme is genuinely different), microstructure
  features from the real reconstructed book.
- **TWAP, VWAP, Almgren-Chriss** — VWAP's profile shape and Almgren-Chriss's
  impact coefficients are both literally decided by what the real data
  shows, not assumed.
- **RL execution policy** — DQN trained on real historical episodes with a
  strict walk-forward train/test split, evaluated honestly against TWAP/AC
  on identical held-out episodes through the same harness (not a separate
  scoring path).
- **Backtesting core** — order-slicing simulator, a disclosed fill-model
  simplification layered on real book data, implementation shortfall, and
  bootstrap confidence intervals across many real historical windows.
- **Risk layer** — participation-rate limits against real volume, a
  kill switch that is genuinely manual-reset-only.
- **Multi-venue routing** — real, cited fee schedules per venue; smart
  routing compared honestly against always-using-one-venue baselines.

## What's not yet implemented

- Backend (FastAPI) and frontend (Bokeh) serving layers, and deployment.
- Tick/lot-size rounding on child order prices/sizes.
- Continuous-action RL (only size is discretized here).
- Venue-level risk limits for multi-venue routing (today's risk layer is
  single-venue).

## A few things worth knowing before trusting any number here

- **Binance.US, not global Binance**: `api.binance.com` is geo-blocked from
  US infrastructure, so this project uses Binance.US — a real but
  materially thinner/narrower venue. See `data/README.md`.
- **No fabricated literature coefficients**: where a real published number
  couldn't be verified (PDF extraction failures, bot-blocked fee pages),
  this project uses an explicitly labeled placeholder/convention rather
  than inventing a precise-looking figure. See `algos/README.md` and
  `venues/README.md` for exactly where and why.
- **Four real bugs in the Binance reconciliation logic** were found only
  by actually running it against a live feed — not by review. Documented
  in full in `lob/README.md`, including the fixes and how each was
  verified.
