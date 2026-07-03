"""FastAPI app: JSON/GeoJSON API + static frontend."""
from __future__ import annotations

from fastapi import FastAPI, Query, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from pipeline import config as pipeline_config

from . import queries

FRONTEND_DIR = pipeline_config.PROJECT_ROOT / "frontend"
GEOJSON = "application/geo+json"
CACHE = {"Cache-Control": "public, max-age=3600"}

app = FastAPI(title="UK Crime-Rate Heatmap", docs_url=None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.exception_handler(queries.BadRequest)
async def bad_request(_, exc: queries.BadRequest):
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.exception_handler(queries.NotFound)
async def not_found(_, exc: queries.NotFound):
    return JSONResponse({"error": str(exc)}, status_code=404)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/meta")
def meta():
    return JSONResponse(queries.meta(), headers=CACHE)


@app.get("/api/choropleth/{level}")
def choropleth(level: str, bbox: str | None = None):
    if bbox is not None:
        # quantise outward to a 0.02 deg grid: nearby pans hit the LRU cache
        # and features at the viewport edge are never clipped away
        import math

        w, s, e, n = queries.parse_bbox(bbox)
        q = 50.0
        bbox = (f"{math.floor(w * q) / q:.2f},{math.floor(s * q) / q:.2f},"
                f"{math.ceil(e * q) / q:.2f},{math.ceil(n * q) / q:.2f}")
    return Response(queries.choropleth(level, bbox), media_type=GEOJSON, headers=CACHE)


@app.get("/api/region/{level}/{code}")
def region(level: str, code: str):
    return JSONResponse(queries.region_detail(level, code), headers=CACHE)


@app.get("/api/points")
def points(bbox: str, limit: int = Query(default=queries.config.POINTS_DEFAULT_LIMIT)):
    return Response(queries.points(bbox, limit), media_type=GEOJSON, headers=CACHE)


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
