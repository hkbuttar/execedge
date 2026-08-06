# Database

One table: `book_snapshots` (`db/schema.py`) — a Postgres-backed
alternative to `lob/raw/*_book_snapshots.jsonl`, added so a deployed
instance's recorded book history survives Render's ephemeral filesystem
instead of needing a local-record-then-git-commit round trip on every
update. See `DEPLOYMENT.md` for why this exists and what it does and
doesn't solve, and `backtest/README.md`/`lob/README.md` for the file-based
recording/replay this sits alongside.

Nothing else in this project moved to a database — volume/regime CSVs,
RL reward logs, and the trained model checkpoint all stay flat files.
They're small, one-shot or full-overwrite writes from a short CLI run,
regenerable in seconds/minutes; book history is the one thing that's
continuously appended by a long-running process and expensive to lose.
See the design discussion that led to this scoping decision for the full
tradeoff if you're deciding whether to extend this further.

## Layout

```
db/
├── connection.py       get_connection(database_url=None) -- reads DATABASE_URL if not passed
├── schema.py            CREATE TABLE/INDEX for book_snapshots, ensure_schema() (idempotent)
└── book_snapshots.py    insert_snapshot(), fetch_snapshots(venue, symbol=None)
```

No ORM (plain `psycopg`, raw SQL) and no connection pool -- one table,
one query pattern, doesn't need either. `fetch_snapshots` returns plain
dicts shaped exactly like a parsed JSONL line (`venue`, `symbol`,
`timestamp` as an ISO string, `bids`, `asks`), so
`backtest/book_history.py`'s `BookHistoryReader` can build itself from
either source through identical row-processing code.

## How this plugs into the rest of the project

`backtest/book_history.py`'s `open_book_history(source)` is the one
dispatch point every CLI `--book-history` flag and every
`*book_history_path` backend/frontend field already goes through:

- a plain filesystem path reads a JSONL file (`BookHistoryReader.from_file`,
  unchanged behavior from before this existed)
- `db:<venue>` (e.g. `db:binance`) reads that venue from Postgres instead
  (`BookHistoryReader.from_db`)

No schema or CLI-flag changes anywhere else in the project — every
existing script, backend endpoint, and test that passes a real file path
behaves exactly as it did before.

`lob/run_reconstruction.py --record-depth-levels N --database-url <url>`
(or `$DATABASE_URL`) writes the same depth snapshots to Postgres
*in addition to* the JSONL file it already writes -- additive, not a
replacement, so a local recording still leaves a local file too.

## Usage

```bash
# local Postgres for development/testing (docker-compose.yml's db service)
docker compose up -d db
export DATABASE_URL=postgresql://execedge:execedge@localhost:5434/execedge

# record straight into it (in addition to the local JSONL file)
python3 -m lob.run_reconstruction --venues binance --record-depth-levels 50 --minutes 30 \
    --database-url $DATABASE_URL

# read it back through anything that accepts a book-history path
python3 -m backtest.run_backtest \
    --book-history db:binance \
    --side buy --quantity 1.0 --algorithm twap --n-slices 5 \
    --duration-seconds 300 --temporary-impact-coef 0.0 --permanent-impact-coef 0.0
```

Against a deployed Render instance, `DATABASE_URL` is wired to
`execedge-db` automatically (`render.yaml`'s `fromDatabase` env var) --
running the same `lob.run_reconstruction` command locally with
`--database-url` set to Render's Postgres external connection string
records straight into what the deployed app reads.

## What was verified here, and how

`psycopg` isn't installed in the offline test environment this was built
in (same situation as `bokeh`/`gymnasium` elsewhere in this project --
see `frontend/README.md`/`rl/README.md`), so `tests/test_db_book_snapshots.py`
self-skips (`pytest.importorskip("psycopg")`) rather than requiring
`--ignore` like the websocket-client tests do.

What was actually run, for real, against a real local Postgres (Docker,
which *is* available here):

- `tests/test_db_book_snapshots.py`'s 8 tests -- insert/fetch round trips,
  venue/symbol filtering, `ensure_schema` idempotency,
  `BookHistoryReader.from_db` (including its error path for an empty
  venue), and `open_book_history("db:...")` dispatch -- all passed
  against a real `postgres:16-alpine` container.
- `lob.run_reconstruction`'s `make_writer(..., database_url=...)` path,
  exercised directly against a real book update and confirmed the row
  landed in Postgres via `fetch_snapshots`.
- The full `docker compose up` stack (db + backend + frontend): real
  snapshots inserted into the compose network's Postgres, then
  `POST /backtest` on the containerized backend with
  `"book_history_path": "db:binance"` returned a real TWAP result
  computed from those DB-backed rows -- the actual deployed code path,
  not a shortcut around it.

What's still unverified: an actual live Render deployment (needs your
own GitHub/Render login, same caveat as the rest of `DEPLOYMENT.md`).
