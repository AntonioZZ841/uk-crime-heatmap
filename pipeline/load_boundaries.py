"""Load boundary GeoJSON files into the boundaries table (geometry as text + bbox).

LSOA parent (ward) comes from the lookup file since the LSOA boundary service
has no parent field; ward parent (LAD) is baked into the ward service fields.
"""
from __future__ import annotations

import json

import duckdb
from shapely.geometry import shape

import config


def iter_rows():
    lookup = {
        r["LSOA21CD"]: r["WD25CD"]
        for r in json.loads((config.RAW_DIR / "lookup_lsoa.json").read_text())
    }
    for level, (_, expected, code_f, name_f, parent_f) in config.BOUNDARY_SERVICES.items():
        fc = json.loads((config.BOUNDARY_DIR / f"{level}.geojson").read_text())
        assert len(fc["features"]) == expected, (level, len(fc["features"]), expected)
        for feat in fc["features"]:
            props = feat["properties"]
            code = props[code_f]
            if parent_f:
                parent = props.get(parent_f)
            elif level == "lsoa":
                parent = lookup.get(code)
            else:
                parent = None
            geom = feat["geometry"]
            minx, miny, maxx, maxy = shape(geom).bounds
            yield (level, code, props.get(name_f) or code, parent,
                   json.dumps(geom, separators=(",", ":")), minx, miny, maxx, maxy)


def run(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        "CREATE OR REPLACE TABLE boundaries ("
        " level VARCHAR, code VARCHAR, name VARCHAR, parent_code VARCHAR,"
        " geojson VARCHAR, minx DOUBLE, miny DOUBLE, maxx DOUBLE, maxy DOUBLE)"
    )
    con.executemany("INSERT INTO boundaries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", list(iter_rows()))
    counts = dict(con.execute("SELECT level, count(*) FROM boundaries GROUP BY level").fetchall())
    print(f"boundaries: {counts}")


if __name__ == "__main__":
    with duckdb.connect(str(config.DB_PATH)) as con:
        run(con)
