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

Rebuilding the database requires the server to be stopped (single-writer rule).

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
