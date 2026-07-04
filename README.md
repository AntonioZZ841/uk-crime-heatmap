# UK Crime-Rate Heatmap

Interactive map of street-level crime rates for England, Wales & Northern Ireland.
Blue = low, red = high (annualised crimes per 1,000 residents, log scale). Zoom from
country level down through local authorities → wards → neighbourhoods (LSOAs) → a
street-level incident heatmap. Click any region to zoom in and open a dashboard with
its severity-ranked "biggest incidents", crime-type breakdown, and monthly trend.

Scotland is greyed out — Police Scotland does not publish to
[data.police.uk](https://data.police.uk).

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

make mini    # ~5 min: 1 month, 3 forces - proves the whole chain
make serve   # http://localhost:8000
```

Full build (last 12 months, all forces — streams ~600 MB of CSVs out of the police
archive plus boundaries/population; allow disk space and time for the download):

```bash
make all
make serve
```

Rebuilding the database from the command line requires the server to be stopped
(single-writer rule). The app (web **and** desktop) also has an **Update data**
button in the legend: when police.uk publishes a new month it rebuilds the
database in the background (~15–25 min) into a separate file and hot-swaps it
without interrupting the running app — a popup then offers to refresh the
interface to the new version. If the rebuild fails, the current data keeps
serving. Desktop apps store updated data in a per-user directory
(`%LOCALAPPDATA%\uk-crime-heatmap` on Windows, `~/Library/Application Support/uk-crime-heatmap`
on macOS); delete it to revert to the dataset bundled with the app.

## Desktop app (Windows & macOS)

Grab the zip for your OS from the
[latest release](https://github.com/AntonioZZ841/uk-crime-heatmap/releases/latest) —
no Python needed, the 12-month database is bundled (internet still required for
basemap tiles):

- **Windows**: `uk-crime-heatmap-windows-x64.zip` → run `uk-crime-heatmap/uk-crime-heatmap.exe`.
  Past the SmartScreen warning: *More info → Run anyway* (unsigned binary).
- **macOS** (macOS 12+): `uk-crime-heatmap-macos-arm64.zip` for Apple Silicon (M1+),
  `uk-crime-heatmap-macos-x64.zip` for Intel Macs → `UK Crime Heatmap.app`. First launch
  is Gatekeeper-blocked (unsigned): right-click → Open, or **System Settings →
  Privacy & Security → "Open Anyway"**, or `xattr -cr "UK Crime Heatmap.app"`.

Releases are built by CI on every `v*` tag ([workflow](.github/workflows/release.yml)):
the dataset is built once from source on Linux, then Windows/macOS apps are frozen in
parallel with PyInstaller from the same database, smoke-tested headlessly, and attached
to the release. Build locally with:

```bash
pip install -r requirements-desktop.txt
pyinstaller desktop.spec        # needs data/crime.duckdb built first
# dev run without freezing:
python desktop.py               # opens a native window (CRIME_DESKTOP_NOGUI=1 for server only)
```

## Data sources

| What | Source |
|---|---|
| Street-level crimes | data.police.uk bulk archive (OGL v3) |
| Boundaries (LAD/ward/LSOA, generalised) | ONS Open Geography Portal (OGL v3) |
| Population (mid-2024) | ONS mid-year estimates |
| Basemap | OpenFreeMap (OpenMapTiles / OSM) |

The month window is pinned automatically from the police "crime last updated" API
into `data/raw/window.json`.

## Layout

```
pipeline/   download -> DuckDB -> aggregates (config.py = single source of truth)
backend/    FastAPI: /api/meta, /api/choropleth/{level}, /api/region/{level}/{code}, /api/points
frontend/   MapLibre GL JS + vanilla JS (no build step)
data/       raw downloads + crime.duckdb (gitignored)
```

## Notes & caveats

- Crime locations are anonymised snap-points ("on or near …"), not exact addresses.
- Rates use resident population, so commercial centres (City of London) rank very high.
- PSNI publishes coordinates but no small-area codes or outcomes → NI is mapped at
  district level (the street heatmap still works there).
- Severity weights (`pipeline/config.py`) are a heuristic informed by the ONS Crime
  Severity Score; see the in-app "i" panel.
- Some forces are missing recent months in the archive; affected regions carry a note
  in their dashboard.
