"""Single source of truth: data URLs, month window, severity weights, level/zoom config.

All URLs verified live 2026-07-03. Everything downstream (pipeline, backend,
frontend via /api/meta) reads from here.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)


def _user_data_dir() -> Path:
    """Writable per-user location for frozen apps (the install dir may be read-only)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "uk-crime-heatmap"


# CRIME_RATE_ROOT overrides the repo root - set by desktop.py in frozen
# (PyInstaller) builds, where frontend/ and data/ are unpacked elsewhere.
_env_root = os.environ.get("CRIME_RATE_ROOT")
PROJECT_ROOT = Path(_env_root) if _env_root else Path(__file__).resolve().parents[1]

# Frozen apps read the shipped database from the bundle but write everything
# (downloads, updated databases) to the per-user dir.
BUNDLED_DB = PROJECT_ROOT / "data" / "crime.duckdb"
DATA_DIR = _user_data_dir() if FROZEN else PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CSV_DIR = RAW_DIR / "csv"          # extracted street CSVs, one subdir per month
BOUNDARY_DIR = RAW_DIR / "boundaries"
# CRIME_DB_PATH lets the refresh job build into a separate file while the
# server keeps serving the current one (DuckDB is single-writer).
DB_PATH = Path(os.environ.get("CRIME_DB_PATH") or (DATA_DIR / "crime.duckdb"))
WINDOW_FILE = RAW_DIR / "window.json"  # pinned month window so all stages agree


def active_db_path() -> Path:
    """The database to serve: a user-dir copy (from an in-app update) wins over
    the bundled one; dev setups only ever have DB_PATH."""
    if DB_PATH.exists():
        return DB_PATH
    if FROZEN and BUNDLED_DB.exists():
        return BUNDLED_DB
    return DB_PATH

# ---------------------------------------------------------------------------
# Crime data (data.police.uk)
# ---------------------------------------------------------------------------
POLICE_ARCHIVE_URL = "https://data.police.uk/data/archive/latest.zip"
CRIME_LAST_UPDATED_URL = "https://data.police.uk/api/crime-last-updated"
WINDOW_MONTHS = 12

# Mini mode: 1 month, 3 forces — proves the whole chain before the big download.
MINI_MODE = os.environ.get("MINI_MODE", "0") == "1"
MINI_FORCES = {"city-of-london", "metropolitan", "northern-ireland"}
MINI_WINDOW_MONTHS = 1

# British Transport Police crimes are geocoded to stations/track and can skew
# local counts; keep them by default but allow exclusion.
INCLUDE_BTP = os.environ.get("INCLUDE_BTP", "1") == "1"

# ---------------------------------------------------------------------------
# Boundaries — ONS Open Geography Portal (ArcGIS FeatureServer, GeoJSON pages)
# ---------------------------------------------------------------------------
ARCGIS_BASE = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services"

BOUNDARY_SERVICES = {
    # level -> (service name, expected feature count, code field, name field, parent field)
    "lad":  ("LAD_MAY_2025_UK_BUC",                361,   "LAD25CD",  "LAD25NM",  None),
    "ward": ("WD_MAY_2025_UK_BSC_V2",              8405,  "WD25CD",   "WD25NM",   "LAD25CD"),
    "lsoa": ("LSOA_2021_EW_BSC_V4_RUC",            35672, "LSOA21CD", "LSOA21NM", None),  # parent via lookup
}
LOOKUP_SERVICE = ("LSOA21_WD25_LAD25_EW_LU_v2", 35672)  # LSOA→Ward→LAD lookup table
ARCGIS_PAGE_SIZE = 2000

# ---------------------------------------------------------------------------
# Population — ONS mid-2024 estimates
# ---------------------------------------------------------------------------
POP_LSOA_URL = (
    "https://www.ons.gov.uk/file?uri=/peoplepopulationandcommunity/populationandmigration/"
    "populationestimates/datasets/lowersuperoutputareamidyearpopulationestimatesnationalstatistics/"
    "mid2022revisednov2025tomid2024/sapelsoabroadage20222024.xlsx"
)
POP_LAD_URL = (
    "https://www.ons.gov.uk/file?uri=/peoplepopulationandcommunity/populationandmigration/"
    "populationestimates/datasets/populationestimatesforukenglandandwalesscotlandandnorthernireland/"
    "mid2024/mye24tablesuk.xlsx"
)

# LADs recoded in the May-2025 boundaries; ONS mid-2024 populations still use
# the old codes. Applied old->new only when the new code has no population row.
LAD_RECODES = {
    "E08000016": "E08000038",  # Barnsley
    "E08000019": "E08000039",  # Sheffield
}

# ---------------------------------------------------------------------------
# Severity weights for the 14 police.uk categories.
# Heuristic loosely informed by the ONS Crime Severity Score; tier 1 = serious.
# ---------------------------------------------------------------------------
SEVERITY = {
    # category: (weight, tier)
    "Violence and sexual offences": (10.0, 1),
    "Robbery": (8.0, 1),
    "Possession of weapons": (7.0, 1),
    "Burglary": (5.0, 2),
    "Vehicle crime": (4.0, 2),
    "Theft from the person": (4.0, 2),
    "Criminal damage and arson": (3.0, 2),
    "Drugs": (3.0, 2),
    "Public order": (2.5, 3),
    "Other theft": (2.0, 3),
    "Shoplifting": (1.5, 3),
    "Bicycle theft": (1.5, 3),
    "Other crime": (1.0, 3),
    "Anti-social behaviour": (0.5, 3),
}

# ---------------------------------------------------------------------------
# Level / zoom configuration (served to the frontend via /api/meta)
# ---------------------------------------------------------------------------
LEVELS = {
    "lad":  {"min_zoom": 0.0,  "max_zoom": 8.5,  "bbox_required": False, "max_bbox_deg2": None},
    "ward": {"min_zoom": 8.5,  "max_zoom": 11.0, "bbox_required": True,  "max_bbox_deg2": 35.0},
    "lsoa": {"min_zoom": 11.0, "max_zoom": 24.0, "bbox_required": True,  "max_bbox_deg2": 3.0},
}
HEATMAP_MIN_ZOOM = 13.0
CIRCLE_MIN_ZOOM = 14.5
POINTS_MAX_BBOX_DEG2 = 0.5
POINTS_DEFAULT_LIMIT = 5000

# Drill-down: clicking a region at one level drops into the next.
CHILD_LEVEL = {"lad": "ward", "ward": "lsoa", "lsoa": None}

# Blue -> red on log10(rate per 1,000 residents / year); identical at all levels.
COLOR_SCALE = {
    "type": "log",
    "attribute": "rate_per_1000",
    "stops": [
        [10, "#2166ac"],
        [25, "#4393c3"],
        [50, "#92c5de"],
        [100, "#f7f7f7"],
        [200, "#f4a582"],
        [400, "#d6604d"],
        [1000, "#b2182b"],
    ],
    "no_data": "#e0e0e0",
    "scotland": "#9aa0a6",
}

# Dashboard cluster ranking: top groups per category, merged, tier-then-weight sorted.
CLUSTER_TOP_PER_CATEGORY = 5
CLUSTER_LIMIT = 15

# A LAD rate below this is a force-publication gap, not safety (the quietest
# real LADs sit around 25/1,000; Greater Manchester's BTP-only residue is ~0.2).
# Such LADs - and their wards/LSOAs - are shown as "no data".
MIN_PLAUSIBLE_LAD_RATE = 5.0


def month_window() -> list[str]:
    """The pinned list of YYYY-MM months this build covers (oldest first).

    Written once by download.py after querying crime-last-updated, then reused
    by every later stage so a rerun never mixes windows.
    """
    if not WINDOW_FILE.exists():
        raise RuntimeError("window.json missing - run pipeline/download.py first")
    return json.loads(WINDOW_FILE.read_text())["months"]


def compute_window(latest: str, n_months: int | None = None) -> list[str]:
    """latest 'YYYY-MM' -> [latest-n+1 .. latest], oldest first."""
    if n_months is None:
        n_months = MINI_WINDOW_MONTHS if MINI_MODE else WINDOW_MONTHS
    year, month = int(latest[:4]), int(latest[5:7])
    out = []
    for i in range(n_months - 1, -1, -1):
        y, m = year, month - i
        while m <= 0:
            y, m = y - 1, m + 12
        out.append(f"{y:04d}-{m:02d}")
    return out
