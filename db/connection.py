"""Postgres connection for book history storage -- the one place that
knows about `DATABASE_URL`. Deliberately no ORM/connection pool: this
project has exactly one table (see `db/schema.py`), so a plain
`psycopg.connect()` per call is simple and fast enough; a pool would be
solving a scaling problem this project doesn't have.
"""

import os

import psycopg


def get_connection(database_url: str | None = None) -> psycopg.Connection:
    """Raises `RuntimeError` (not a bare KeyError) if neither an explicit
    URL nor `DATABASE_URL` is set, so a missing-DB-config error reads the
    same way `BookHistoryReader.from_file`'s missing-file error does --
    a clear message about what's absent, not a stack trace into stdlib."""
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "no database configured: pass database_url explicitly or set the "
            "DATABASE_URL environment variable (Render sets this automatically "
            "for services wired to a database in render.yaml)"
        )
    return psycopg.connect(url)
