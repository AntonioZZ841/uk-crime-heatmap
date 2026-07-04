"""Desktop entry point: run the FastAPI app locally and open it in a native window.

Works both from a source checkout and as a PyInstaller bundle (where the
frontend and database are unpacked next to the executable - CRIME_RATE_ROOT
must be set before backend/pipeline modules are imported).

Env knobs (used by CI smoke tests):
  CRIME_DESKTOP_NOGUI=1   start the server only, no window (headless check)
  CRIME_DESKTOP_PORT=n    fixed port instead of a random free one
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller: bundled data (frontend/, data/crime.duckdb) lives in _MEIPASS
    os.environ["CRIME_RATE_ROOT"] = str(Path(sys._MEIPASS))
    # Windowed (console=False) builds have no stdout/stderr; any print() or
    # logging StreamHandler would crash with AttributeError on None. Route to
    # devnull BEFORE uvicorn builds its logging handlers. (In worker mode the
    # parent gives us a real stdout pipe, so this guard is a no-op there.)
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

if "--run-pipeline" in sys.argv:
    # Worker mode: the in-app updater re-invokes this same executable to run
    # the data pipeline as a subprocess (CRIME_DB_PATH/MINI_MODE via env).
    from pipeline.run_all import main as pipeline_main

    pipeline_main()
    sys.exit(0)

import uvicorn

from backend.app import app

APP_TITLE = "UK Crime-Rate Heatmap"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_healthy(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/healthz", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def main() -> int:
    port = int(os.environ.get("CRIME_DESKTOP_PORT") or free_port())
    url = f"http://127.0.0.1:{port}"

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()

    if not wait_healthy(url):
        print("server failed to start", file=sys.stderr)
        return 1

    if os.environ.get("CRIME_DESKTOP_NOGUI") == "1":
        print(f"serving on {url} (no GUI); Ctrl+C to stop")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    import webview  # deferred: only the GUI path needs a webview backend

    webview.create_window(APP_TITLE, url, width=1320, height=880, min_size=(900, 600))
    webview.start()
    server.should_exit = True
    return 0


if __name__ == "__main__":
    sys.exit(main())
