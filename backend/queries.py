"""SQL + GeoJSON assembly for the API.

Choropleth responses are assembled by string concatenation around the stored
geometry text (never re-parsed), with rates baked into properties so the
client does no joining. Small LRU caches sit on the hot read-only queries.
"""
from __future__ import annotations

import json
from functools import lru_cache

from pipeline import config

from . import db

LEVEL_COLUMN = {"lad": "lad25cd", "ward": "wd25cd", "lsoa": "lsoa21cd"}


class BadRequest(ValueError):
    pass


class NotFound(KeyError):
    pass


def parse_bbox(raw: str) -> tuple[float, float, float, float]:
    try:
        w, s, e, n = (float(x) for x in raw.split(","))
    except Exception as exc:
        raise BadRequest(f"bbox must be 'w,s,e,n', got {raw!r}") from exc
    if not (w < e and s < n):
        raise BadRequest("bbox must satisfy w<e and s<n")
    return w, s, e, n


def _feature(geom_text: str, props: dict) -> str:
    return '{"type":"Feature","geometry":' + geom_text + ',"properties":' + json.dumps(props) + "}"


def _collection(features: list[str]) -> str:
    return '{"type":"FeatureCollection","features":[' + ",".join(features) + "]}"


@lru_cache(maxsize=1)
def runtime_window() -> dict:
    """Month window of the loaded build - from the DB itself (self-contained
    desktop/cloud artifact), falling back to window.json for older builds."""
    try:
        months_json, mini = db.conn().execute("SELECT months, mini FROM build_meta").fetchone()
        return {"months": json.loads(months_json), "mini": bool(mini)}
    except Exception:
        w = json.loads(config.WINDOW_FILE.read_text())
        return {"months": w["months"], "mini": w.get("mini", False)}


@lru_cache(maxsize=1)
def meta() -> dict:
    window = runtime_window()
    total, = db.conn().execute("SELECT count(*) FROM crimes").fetchone()
    return {
        "period": {"from": window["months"][0], "to": window["months"][-1],
                   "months": len(window["months"]), "mini": window["mini"]},
        "total_crimes": total,
        "severity": [
            {"category": c, "weight": w, "tier": t} for c, (w, t) in config.SEVERITY.items()
        ],
        "color_scale": config.COLOR_SCALE,
        "levels": config.LEVELS,
        "heatmap_min_zoom": config.HEATMAP_MIN_ZOOM,
        "circle_min_zoom": config.CIRCLE_MIN_ZOOM,
        "points_default_limit": config.POINTS_DEFAULT_LIMIT,
        "points_max_bbox_deg2": config.POINTS_MAX_BBOX_DEG2,
        "child_level": config.CHILD_LEVEL,
        "attribution": "Crime data & boundaries: OGL v3 (police.uk, ONS). Basemap: OpenFreeMap / OpenMapTiles / OSM.",
    }


@lru_cache(maxsize=128)
def choropleth(level: str, bbox_key: str | None) -> str:
    if level not in config.LEVELS:
        raise BadRequest(f"unknown level {level!r}")
    spec = config.LEVELS[level]
    params: list = [level]
    where = "b.level = ?"
    if bbox_key is not None:
        w, s, e, n = parse_bbox(bbox_key)
        if spec["max_bbox_deg2"] and (e - w) * (n - s) > spec["max_bbox_deg2"]:
            raise BadRequest(f"bbox too large for level {level}")
        where += " AND b.maxx >= ? AND b.minx <= ? AND b.maxy >= ? AND b.miny <= ?"
        params += [w, e, s, n]
    elif spec["bbox_required"]:
        raise BadRequest(f"level {level} requires a bbox")
    if level != "lad":
        # NI has no small-area population; it stays LAD-level (overlay covers all zooms)
        where += " AND b.code NOT LIKE 'N%'"

    rows = db.conn().execute(
        f"""
        SELECT b.code, b.name, b.geojson,
               a.crimes_12m, a.population, a.rate_per_1000,
               a.top_category, a.months_present
        FROM boundaries b
        LEFT JOIN agg_region a ON a.level = b.level AND a.code = b.code
        WHERE {where}
        """,
        params,
    ).fetchall()

    feats = []
    for code, name, geom, crimes, pop, rate, top_cat, months_present in rows:
        feats.append(_feature(geom, {
            "code": code, "name": name, "level": level, "country": code[0],
            "crimes_12m": crimes, "population": pop, "rate_per_1000": rate,
            "top_category": top_cat, "months_present": months_present,
        }))
    return _collection(feats)


def _region_row(level: str, code: str):
    row = db.conn().execute(
        """
        SELECT a.name, a.parent_code, a.crimes_12m, a.population, a.rate_per_1000,
               a.months_present, a.rank_by_rate,
               b.minx, b.miny, b.maxx, b.maxy
        FROM agg_region a JOIN boundaries b ON b.level = a.level AND b.code = a.code
        WHERE a.level = ? AND a.code = ?
        """,
        [level, code],
    ).fetchone()
    if row is None:
        raise NotFound(f"{level}/{code}")
    return row


def _clusters(level: str, code: str) -> list[dict]:
    col = LEVEL_COLUMN[level]
    rows = db.conn().execute(
        f"""
        WITH g AS (
            SELECT category, location,
                   round(lon, 4) AS rx, round(lat, 4) AS ry,
                   count(*) AS n, max(month) AS last_month,
                   any_value(lon) AS lon, any_value(lat) AS lat
            FROM crimes
            WHERE {col} = ? AND location IS NOT NULL
            GROUP BY 1, 2, 3, 4
        )
        SELECT * FROM (
            SELECT g.*, coalesce(s.weight, 1.0) AS weight, coalesce(s.tier, 3) AS tier,
                   row_number() OVER (PARTITION BY g.category ORDER BY g.n DESC) AS rn
            FROM g LEFT JOIN severity s ON s.category = g.category
        ) WHERE rn <= ?
        ORDER BY tier ASC, weight DESC, n DESC
        LIMIT ?
        """,
        [code, config.CLUSTER_TOP_PER_CATEGORY, config.CLUSTER_LIMIT],
    ).fetchall()

    clusters = []
    keys = []
    for category, location, rx, ry, n, last_month, lon, lat, weight, tier, _rn in rows:
        clusters.append({
            "category": category, "location": location, "n": n,
            "score": round(weight * n, 1), "tier": tier,
            "lat": lat, "lon": lon,
            "last_month": str(last_month)[:7] if last_month else None,
            "outcomes": [],
        })
        keys.append((category, location, rx, ry))

    if keys:
        # one scan fetching top outcomes for all chosen clusters
        preds = " OR ".join(
            "(category = ? AND location = ? AND round(lon,4) IS NOT DISTINCT FROM ? "
            "AND round(lat,4) IS NOT DISTINCT FROM ?)"
            for _ in keys
        )
        flat: list = [v for k in keys for v in k]
        out_rows = db.conn().execute(
            f"""
            SELECT category, location, round(lon,4), round(lat,4),
                   coalesce(outcome, 'No outcome recorded') AS outcome, count(*) AS n
            FROM crimes
            WHERE {LEVEL_COLUMN[level]} = ? AND ({preds})
            GROUP BY 1, 2, 3, 4, 5
            ORDER BY n DESC
            """,
            [code, *flat],
        ).fetchall()
        by_key: dict[tuple, list] = {}
        for cat, loc, rx, ry, outcome, n in out_rows:
            k = (cat, loc, rx, ry)
            if len(by_key.setdefault(k, [])) < 3:
                by_key[k].append({"outcome": outcome, "n": n})
        for cl, k in zip(clusters, keys):
            cl["outcomes"] = by_key.get(k, [])

    for rank, cl in enumerate(clusters, 1):
        cl["rank"] = rank
    return clusters


def _parents(level: str, code: str, parent_code: str | None) -> list[dict]:
    """Ancestor chain (outermost first) for the breadcrumb: lsoa -> ward -> lad."""
    chain = []
    lvl, parent = level, parent_code
    parent_of = {"lsoa": "ward", "ward": "lad"}
    while parent and lvl in parent_of:
        lvl = parent_of[lvl]
        row = db.conn().execute(
            "SELECT name, parent_code FROM boundaries WHERE level = ? AND code = ?",
            [lvl, parent],
        ).fetchone()
        if row is None:
            break
        chain.append({"level": lvl, "code": parent, "name": row[0]})
        parent = row[1]
    return list(reversed(chain))


@lru_cache(maxsize=256)
def region_detail(level: str, code: str) -> dict:
    if level not in LEVEL_COLUMN:
        raise BadRequest(f"unknown level {level!r}")
    name, parent, crimes, pop, rate, months_present, rank, minx, miny, maxx, maxy = _region_row(level, code)
    total_in_level, = db.conn().execute(
        "SELECT count(*) FROM agg_region WHERE level = ?", [level]
    ).fetchone()

    window = runtime_window()["months"]
    trend_rows = dict(db.conn().execute(
        "SELECT strftime(month, '%Y-%m'), n FROM agg_region_month WHERE level = ? AND code = ?",
        [level, code],
    ).fetchall())
    by_cat = db.conn().execute(
        f"""
        SELECT c.category, c.n, coalesce(s.weight, 1.0), coalesce(s.tier, 3),
               lm.last_month, lm.last_location
        FROM agg_region_category c
        LEFT JOIN severity s ON s.category = c.category
        LEFT JOIN (
            SELECT category, strftime(max(month), '%Y-%m') AS last_month,
                   max_by(location, month) AS last_location
            FROM crimes WHERE {LEVEL_COLUMN[level]} = ? GROUP BY category
        ) lm ON lm.category = c.category
        WHERE c.level = ? AND c.code = ? ORDER BY c.n DESC
        """,
        [code, level, code],
    ).fetchall()

    notes = []
    if code.startswith("N"):
        notes.append("Northern Ireland is shown at district level; PSNI does not publish outcomes or small-area codes.")
    if months_present == 0:
        notes.append(
            "The local police force published no data for this period (Greater Manchester "
            "Police has not published to data.police.uk since 2019). Any counts shown here "
            "are transport-police records; the map shows this area as 'no data'."
        )
    elif months_present < len(window):
        notes.append(
            f"The local force reported {months_present} of {len(window)} months; "
            "the rate is annualised from the reported months."
        )

    return {
        "level": level, "code": code, "name": name, "parent_code": parent,
        "parents": _parents(level, code, parent),
        "bbox": [minx, miny, maxx, maxy],
        "population": pop, "crimes_12m": crimes, "rate_per_1000": rate,
        "rank": {"position": rank, "of": total_in_level},
        "months_present": months_present,
        "by_category": [
            {"category": c, "n": n, "weight": w, "tier": t,
             "last_month": lm, "last_location": ll}
            for c, n, w, t, lm, ll in by_cat
        ],
        "trend": [{"month": m, "n": trend_rows.get(m, 0)} for m in window],
        "clusters": _clusters(level, code),
        "notes": notes,
    }


def points(bbox_raw: str, limit: int) -> str:
    w, s, e, n = parse_bbox(bbox_raw)
    if (e - w) * (n - s) > config.POINTS_MAX_BBOX_DEG2:
        raise BadRequest("bbox too large for points")
    limit = max(1, min(limit, 20_000))
    rows = db.conn().execute(
        """
        SELECT lon, lat, crimes.category, coalesce(s.weight, 1.0), location,
               strftime(month, '%Y-%m'), outcome
        FROM crimes LEFT JOIN severity s ON s.category = crimes.category
        WHERE lon >= ? AND lon <= ? AND lat >= ? AND lat <= ?
        ORDER BY coalesce(s.weight, 1.0) DESC
        LIMIT ?
        """,
        [w, e, s, n, limit],
    ).fetchall()
    feats = []
    for lon, lat, cat, weight, loc, month, outcome in rows:
        feats.append(_feature(
            f'{{"type":"Point","coordinates":[{lon:.5f},{lat:.5f}]}}',
            {"cat": cat, "w": weight, "loc": loc, "month": month, "outcome": outcome},
        ))
    return _collection(feats)
