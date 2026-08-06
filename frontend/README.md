# Frontend (Bokeh)

A Bokeh server app with four tabs, each driving one of `backend/`'s
computations and rendering it as a figure. It does not talk to the
backend over HTTP — `frontend/data_access.py` calls straight into
`backend.services`, building the same Pydantic request models
`backend/main.py`'s routes use. One process to run or deploy, and any
drift between "the API" and "the app" would show up immediately as a
signature mismatch, not a subtle behavioral difference.

## Layout

- **`data_access.py`** — thin wrappers over `backend.services`, one per
  tab. No Bokeh import. Raises `ValueError`/`FileNotFoundError` on bad
  input, same as the backend.
- **`plots.py`** — pure functions, `dict`/`list` in, Bokeh `figure` out.
  No I/O, no document/server state.
- **`app.py`** — the Bokeh server document: widgets, `on_click`/
  `on_change` callbacks calling `data_access` then `plots`, wrapped in
  `try/except` so a bad path or bad input shows as a red error `Div`
  instead of crashing the server process.

## Tabs

| Tab | `data_access` function | `backend` route it mirrors | `plots` function |
|---|---|---|---|
| Execution trajectory | `get_trajectory` | `POST /backtest/trajectory` | `trajectory_figure` |
| Algorithm comparison | `get_experiment` | `POST /experiment` | `comparison_figure` |
| Venue routing | `get_venue_routing_comparison` | `POST /venues/routing` | `venue_routing_figure` |
| Cross-venue validation | `get_cross_venue_validation` | `POST /venues/cross-validate` | `cross_venue_figure` |

The trajectory tab runs both `naive` and `twap` on the same book history
and overlays them, so the "smoothing over time" story TWAP is supposed
to tell is visible directly, not just implied by an aggregate number.
The comparison tab's regime dropdown is populated after the first run,
from whatever regimes are actually present in the results (`sorted({r["regime"] for r in results})`)
rather than a hardcoded list, since which regimes exist depends on the
book history and regimes CSV given.

## Usage

```
bokeh serve frontend/app.py
```

then open the URL Bokeh prints (default `http://localhost:5006/app`).
Each tab defaults its book-history/regimes-CSV inputs to this project's
own real recorded data (`lob/raw/binance_book_snapshots.jsonl`,
`data/raw/regimes/binance_regimes.csv`) so the first click on each tab
works out of the box against genuine data, not a placeholder path.

## What's verified, and what isn't

`bokeh` is not installed in this environment, so nothing here has been
visually rendered or exercised through an actual Bokeh server process.
What was verified instead, matching the pattern used elsewhere in this
project for dependencies not installed here (`rl/README.md`'s
gymnasium/stable-baselines3, `lob/README.md`'s websocket-client):

- `data_access.py` has no Bokeh dependency and is fully covered by
  `tests/test_frontend_data_access.py` (9 tests), run against synthetic
  book histories/CSVs, plus a manual smoke test against this project's
  real recorded Binance data confirming genuine trajectory points, fee
  schedules, and experiment rows.
- `plots.py` and `app.py` were checked with `py_compile` (no syntax/
  import-order issues) and their non-Bokeh data-prep logic — the
  filter/sort in `comparison_figure`, the highlight-list construction in
  `venue_routing_figure`, the `FactorRange` tuple/values construction in
  `cross_venue_figure` — was independently re-run outside of Bokeh
  against known inputs and matched by hand.
- What's genuinely unverified: whether these figures actually render as
  intended once real Bokeh objects are built and served. Run
  `bokeh serve frontend/app.py` yourself and see.

## Not yet implemented

- No way to kick off long-running operations (recording a live book,
  training an RL policy) from the UI — consistent with `backend/README.md`'s
  reasoning for why those stay CLI-only.
- No deployment packaging yet (see the top-level README for status).
