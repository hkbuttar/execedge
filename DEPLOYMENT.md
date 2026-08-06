# Deployment

Two web services plus a database, one image for the services:
`Dockerfile` installs `requirements-web.txt` (the lean subset of
`requirements.txt` that `backend/` and `frontend/` actually import — no
gymnasium/stable-baselines3/torch, see that file's header for why) and
`COPY . .`; `render.yaml` runs the image twice with different start
commands, plus a managed Postgres instance both services share.

| Service | Command | Purpose |
|---|---|---|
| `execedge-backend` | `uvicorn backend.main:app` | JSON API + `/docs` |
| `execedge-frontend` | `bokeh serve frontend/app.py` | the UI |
| `execedge-db` | (managed Postgres) | recorded book history, see `db/README.md` |

The frontend doesn't call the backend over HTTP — `frontend/data_access.py`
calls `backend.services` in-process — so `execedge-frontend` runs standalone;
`execedge-backend` exists to expose the API on its own for anyone who
wants to query it directly rather than through the UI. Both get
`DATABASE_URL` wired in automatically (`render.yaml`'s `fromDatabase`),
so both can serve book history read via `db:<venue>` (see `db/README.md`)
in addition to a committed JSONL file.

## Deploy to Render

1. Push this repo to GitHub (Render's Blueprint deploy reads from a
   connected git repo, not a local directory).
2. In the Render dashboard: **New +** → **Blueprint**, point it at the
   repo. Render reads `render.yaml` and creates both services and the
   database.
3. Free plan: web services spin down after 15 minutes idle (~30–60s
   cold start on the next request); the free Postgres instance expires
   after 30 days (Render's own limit, not something this project
   controls) — fine for a research/portfolio deployment, worth knowing
   before relying on it longer-term.

This step (pushing to GitHub, connecting the account, clicking through
Render's dashboard) needs your own GitHub/Render login — not something
that can be done from here.

## What was actually verified here, and how

Bokeh isn't installed in the environment this was built in (see
`frontend/README.md`), so it's never been reachable directly — but
Docker is, so the exact image `render.yaml` builds was built and run
locally end-to-end:

```
docker build -t execedge-web .
docker run -p 8000:8000 execedge-web
curl http://localhost:8000/health          # -> {"status":"ok"}
curl http://localhost:8000/venues/fees     # -> real fee schedules, matches TestClient output

docker run -p 5006:5006 execedge-web \
  bash -c "bokeh serve frontend/app.py --port 5006 --address 0.0.0.0 --allow-websocket-origin=localhost:5006"
curl -o /dev/null -w '%{http_code}' http://localhost:5006/app   # -> 200
```

Both confirmed working: the backend served real data identical to
`tests/test_backend.py`'s assertions, and the Bokeh server actually
started and served the page (the first real evidence in this project
that `frontend/`'s Bokeh code runs at all, not just `py_compile`-clean).

The database path was verified the same way, one level further: the
whole three-service `docker compose up` stack (db + backend + frontend,
`DATABASE_URL` wired between them exactly like `render.yaml` wires it on
Render) was brought up together, real book snapshots were inserted into
the compose network's Postgres, and `POST /backtest` on the
containerized backend with `"book_history_path": "db:binance"` returned
a real TWAP result computed from those DB-backed rows — the actual
deployed code path, not a shortcut around it. Full detail in
`db/README.md`.

What's still unverified: clicking through each tab's Run button in an
actual browser against a live Render deployment — the four tabs were
each confirmed working through `frontend/data_access.py`'s tests and
`backend/`'s API tests, but not by clicking the rendered UI itself.

## Known data gaps once deployed

- **Only Binance's book history exists anywhere** (`lob/raw/binance_book_snapshots.jsonl`,
  tracked in git). Coinbase and Kraken were never recorded
  (`lob.run_reconstruction` only run against Binance so far — see the
  main README's honest-gaps section), so their default paths in the
  "Venue routing" and "Cross-venue validation" tabs will 404 with
  `FileNotFoundError` regardless of source — nothing to read from a
  committed file *or* from `execedge-db` (empty database on first
  deploy) until those get recorded. `db:coinbase`/`db:kraken` don't
  magically have data; someone still has to run
  `lob.run_reconstruction --database-url <execedge-db URL>` for those
  venues first.
- **`data/raw/` is gitignored**, including `data/raw/regimes/binance_regimes.csv`
  — the "Algorithm comparison" tab's default regimes-CSV field. It
  won't exist in a deployed instance. Either clear that field (regime
  stratification is optional — `regimes_csv=None` still runs, just
  without the regime breakdown) or deliberately commit that one CSV if
  you want regime stratification available on the deployed instance.

## Local, non-Docker alternative

`README.md`'s Quickstart and `frontend/README.md`/`backend/README.md`
cover running both services directly with `uvicorn`/`bokeh serve` and
the full `requirements.txt` — useful for anything Docker doesn't cover
(training, live book recording), neither of which is part of this
deployment since both are long-running/blocking and deliberately not
exposed as web services (see `backend/README.md`).

Recording (`lob.run_reconstruction`) always runs this way regardless —
locally, or on any machine you control that can hold a live websocket
connection open, since neither a Render web service nor any container
in this deployment is shaped for that (no shell access on the free
plan, ephemeral disk, and Render expects a service to answer HTTP
requests, not block on a websocket for however many `--minutes` you
give it). What changed with `db/`: recording can now write straight
into `execedge-db` via `--database-url` instead of only a local file, so
the deployed instance sees new recordings immediately rather than
needing a commit-and-redeploy round trip. See `db/README.md` for exact
commands.
