"""Read-only DuckDB access with hot-swap support.

FastAPI runs sync endpoints in a threadpool; each worker thread gets its own
read_only connection. A refresh job builds a new database file and swaps it in
with os.replace() - on Linux, threads still holding the old inode keep working;
the generation counter makes each thread lazily reopen onto the new file on its
next query. No cross-thread connection wrangling needed.
"""
from __future__ import annotations

import os
import threading

import duckdb

from pipeline import config

_local = threading.local()
_generation = 0


def conn() -> duckdb.DuckDBPyConnection:
    entry = getattr(_local, "entry", None)
    if entry is None or entry[0] != _generation:
        if entry is not None:
            try:
                entry[1].close()
            except Exception:
                pass
        path = config.active_db_path()  # user-dir copy beats bundled DB when frozen
        if not path.exists():
            raise RuntimeError(f"{path} missing - run `make mini` or `make all` first")
        _local.entry = (_generation, duckdb.connect(str(path), read_only=True))
    return _local.entry[1]


def swap_database(new_path) -> None:
    """Atomically replace the served database with a freshly built one.

    Always lands on DB_PATH (the writable per-user location when frozen); the
    generation bump makes threads re-resolve, migrating serving off the
    bundled copy on a desktop app's first update.
    """
    global _generation
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    os.replace(new_path, config.DB_PATH)
    _generation += 1
    from . import queries

    queries.clear_caches()
