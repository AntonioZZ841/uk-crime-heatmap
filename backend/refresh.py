"""Background data-refresh job: run the pipeline into a fresh DB file, then hot-swap.

One job at a time. The pipeline runs as a subprocess (same interpreter, env
CRIME_DB_PATH pointing at a sibling file) so the served database is never
opened for writing; verify.py's non-zero exit on hard failure means a bad
build is discarded and the old data keeps serving.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time

import httpx

from pipeline import config

from . import db, queries

NEW_DB = config.DB_PATH.parent / (config.DB_PATH.stem + "_new" + config.DB_PATH.suffix)

STEP_LABELS = {
    "load_reference": "Loading reference data (lookup, population)",
    "load_crimes": "Loading crime records",
    "load_boundaries": "Loading boundary polygons",
    "assign_ni": "Locating Northern Ireland records",
    "aggregate": "Computing rates and rankings",
    "verify": "Verifying the new build",
}
LOG_TAIL_LINES = 50

_lock = threading.Lock()
_state: dict = {"state": "idle", "step": None, "log_tail": [],
                "started_at": None, "finished_at": None, "error": None}
_update_check: dict = {"at": 0.0, "result": None}


def status() -> dict:
    with _lock:
        return dict(_state, log_tail=list(_state["log_tail"]))


def check_for_update() -> dict:
    """Compare the served window's last month against police.uk (cached ~1h)."""
    now = time.time()
    with _lock:
        if _update_check["result"] is not None and now - _update_check["at"] < 3600:
            return _update_check["result"]
    current = queries.runtime_window()["months"][-1]
    try:
        latest = httpx.get(config.CRIME_LAST_UPDATED_URL, timeout=10).json()["date"][:7]
        result = {"current": current, "latest": latest, "update_available": latest > current}
    except Exception as exc:  # network down: allow refresh anyway, mark unknown
        result = {"current": current, "latest": None, "update_available": None,
                  "check_error": str(exc)[:120]}
    with _lock:
        _update_check.update(at=now, result=result)
    return result


def start(mini: bool = False) -> bool:
    """Kick off a refresh job. Returns False if one is already running."""
    with _lock:
        if _state["state"] == "running":
            return False
        _state.update(state="running", step="Downloading data", log_tail=[],
                      started_at=time.time(), finished_at=None, error=None)
    threading.Thread(target=_run, args=(mini,), daemon=True).start()
    return True


def _run(mini: bool) -> None:
    import os

    try:
        NEW_DB.parent.mkdir(parents=True, exist_ok=True)
        for stale in (NEW_DB, NEW_DB.with_suffix(NEW_DB.suffix + ".wal")):
            stale.unlink(missing_ok=True)

        # PYTHONUNBUFFERED: line-buffered pipe so step progress arrives live
        env = {**os.environ, "CRIME_DB_PATH": str(NEW_DB), "PYTHONUNBUFFERED": "1"}
        if mini:
            env["MINI_MODE"] = "1"
        # Frozen: re-invoke the app's own exe in worker mode (desktop.py handles
        # --run-pipeline); dev: run the pipeline package with the venv python.
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--run-pipeline"]
        else:
            cmd = [sys.executable, "-m", "pipeline.run_all"]
        proc = subprocess.Popen(
            cmd,
            cwd=str(config.PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            with _lock:
                _state["log_tail"] = (_state["log_tail"] + [line])[-LOG_TAIL_LINES:]
                if line.startswith("--- ") and line.endswith(" ---"):
                    module = line.strip("- ").strip()
                    _state["step"] = STEP_LABELS.get(module, module)
        code = proc.wait()

        if code != 0:
            raise RuntimeError(f"pipeline exited with code {code}")

        db.swap_database(NEW_DB)
        with _lock:
            _state.update(state="done", step="Done", finished_at=time.time())
            _update_check["result"] = None  # force re-check against the new window
    except Exception as exc:
        with _lock:
            _state.update(state="error", finished_at=time.time(), error=str(exc)[:300])
