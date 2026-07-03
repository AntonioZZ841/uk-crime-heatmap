"""Run the full pipeline: download -> load -> assign -> aggregate -> verify."""
from __future__ import annotations

import sys
import time

import duckdb

import aggregate
import assign_ni
import config
import load_boundaries
import load_crimes
import load_reference
import verify


def main() -> None:
    skip_download = "--skip-download" in sys.argv
    t0 = time.time()
    if not skip_download:
        import download

        download.main()

    with duckdb.connect(str(config.DB_PATH)) as con:
        for step in (load_reference, load_crimes, load_boundaries, assign_ni, aggregate, verify):
            t = time.time()
            print(f"--- {step.__name__} ---")
            step.run(con)
            print(f"    ({time.time() - t:.1f}s)")
    print(f"pipeline complete in {time.time() - t0:.0f}s -> {config.DB_PATH}")


if __name__ == "__main__":
    main()
