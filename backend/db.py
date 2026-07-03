"""Read-only DuckDB access, one connection per thread.

FastAPI runs sync endpoints in a threadpool; DuckDB allows many concurrent
read_only connections to the same file, so each worker thread gets its own.
The server must be restarted after a pipeline rebuild (single-writer rule).
"""
from __future__ import annotations

import threading

import duckdb

from pipeline import config

_local = threading.local()


def conn() -> duckdb.DuckDBPyConnection:
    c = getattr(_local, "conn", None)
    if c is None:
        if not config.DB_PATH.exists():
            raise RuntimeError(f"{config.DB_PATH} missing - run `make mini` or `make all` first")
        c = duckdb.connect(str(config.DB_PATH), read_only=True)
        _local.conn = c
    return c
