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

**Live demo**: [execedge-frontend.onrender.com/app](https://execedge-frontend.onrender.com/app)
— free-tier Render, so it spins down after 15 minutes idle (~30–60s cold
start on the first request). See `DEPLOYMENT.md` for known data gaps on
the deployed instance (e.g. Coinbase/Kraken book history not recorded
there yet).

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
├── backend/    FastAPI: serves backtest/calibration/training results as JSON
├── frontend/   Bokeh app: trajectory/comparison/routing/cross-venue tabs,
│                calls backend.services in-process (no separate HTTP hop)
├── db/         Postgres-backed book history (db:<venue>), alongside the
│                file-based recording/replay -- see db/README.md
└── tests/      227 tests (195 run offline in any environment; 8 need a
                 reachable Postgres, self-skip otherwise; 24 need
                 websocket-client installed to exercise the live
                 reconciliation classes)
```

`Dockerfile`, `docker-compose.yml`, and `render.yaml` at the repo root
deploy `backend/` and `frontend/` as two Render web services — see
[DEPLOYMENT.md](DEPLOYMENT.md).

Each module has its own README with full methodology, citations, and
disclosed limitations — start there for depth on any piece:
[data/README.md](data/README.md), [lob/README.md](lob/README.md),
[algos/README.md](algos/README.md), [rl/README.md](rl/README.md),
[backtest/README.md](backtest/README.md), [risk/README.md](risk/README.md),
[venues/README.md](venues/README.md), [backend/README.md](backend/README.md),
[frontend/README.md](frontend/README.md), [db/README.md](db/README.md).

[RESULTS.md](RESULTS.md) pulls all of the above together into the actual
comparison — algorithm × regime × venue-routing × calibration-source ×
exchange on implementation shortfall, the literature-vs-empirical
Almgren-Chriss divergence, and RL vs. TWAP/AC — run against real recorded
data already in this repo, with the honest gaps (what's not recorded yet)
stated plainly rather than filled with invented numbers.

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
- **Cross-venue validation** — the same algorithm ranking, checked
  independently against each venue's own real data, reporting whether it
  replicates or diverges by venue (this project's stand-in for a
  cross-asset-class robustness check, since it's crypto-only by design).
- **Backend (FastAPI)** — serves backtest, calibration, cross-venue, and
  training results as JSON; every route is a thin wrapper reusing the
  exact same functions the CLIs do, nothing reimplemented. Deliberately
  doesn't expose long-running operations (recording a live book, training
  RL) over HTTP — those stay CLI-only.
- **Frontend (Bokeh)** — trajectory, algorithm comparison (with bootstrap
  CIs), venue routing, and cross-venue tabs, calling `backend.services`
  in-process rather than over HTTP. `bokeh` isn't installed in the
  environment this was built in, so it was never reachable directly
  there — but confirmed running for real via Docker (see Deployment
  below): the server started and served the page. See
  `frontend/README.md` for exactly what was and wasn't verified.
- **Deployment** — `Dockerfile` + `render.yaml` deploy `backend/`,
  `frontend/`, and a managed Postgres (`execedge-db`) from one lean image
  (`requirements-web.txt`, no RL-training dependencies). Built and run
  locally with real Docker, including the full `docker compose` stack
  (db + backend + frontend together) — backend served real data matching
  `tests/test_backend.py`, frontend's Bokeh server actually started and
  served `/app` (`HTTP 200`), and a real `POST /backtest` against a
  `db:`-backed book history returned a genuine result. Pushing to Render
  itself needs a GitHub/Render login, which wasn't done here — see
  `DEPLOYMENT.md` for the exact steps and known data gaps (Coinbase/Kraken
  book history isn't recorded yet, so those tabs will 404 until it is).
- **Database (Postgres)** — `db/` persists recorded book history
  (`book_snapshots` table) as an alternative to `lob/raw/*.jsonl`, so a
  deployed instance's recordings survive an ephemeral filesystem instead
  of needing a commit-and-redeploy round trip. Opt-in via a `db:<venue>`
  prefix on any existing `--book-history` flag/API field — no schema or
  CLI changes elsewhere. Plain `psycopg`, no ORM; verified against a real
  local Postgres (Docker) since it's not installed in the environment
  this was built in — see `db/README.md`.

## What's not yet implemented

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
