"""Point-in-polygon assignment for crimes with coordinates but no ward/LAD.

Mainly PSNI rows (their LSOA columns are empty in the CSVs), but the same pass
also rescues E+W/BTP rows whose LSOA code failed the lookup join. Uses a bulk
shapely STRtree query over all 8,405 ward polygons; ward gives us the parent
LAD for free.
"""
from __future__ import annotations

import json

import duckdb
import numpy as np
import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree

from . import config


def run(con: duckdb.DuckDBPyConnection) -> None:
    rows = con.execute(
        "SELECT rowid, lon, lat FROM crimes WHERE lad25cd IS NULL AND lon IS NOT NULL AND lat IS NOT NULL"
    ).fetchall()
    if not rows:
        print("assign_ni: nothing to assign")
        return

    wards = con.execute(
        "SELECT code, parent_code, geojson FROM boundaries WHERE level = 'ward'"
    ).fetchall()
    geoms = [shape(json.loads(gj)) for _, _, gj in wards]
    tree = STRtree(geoms)

    rowids = np.array([r[0] for r in rows], dtype=np.int64)
    pts = shapely.points(np.array([r[1] for r in rows]), np.array([r[2] for r in rows]))
    pt_idx, ward_idx = tree.query(pts, predicate="intersects")

    assigned: dict[int, tuple[str, str]] = {}
    for p, w in zip(pt_idx.tolist(), ward_idx.tolist()):
        if p not in assigned:  # boundary points can hit two wards; first wins
            assigned[p] = (wards[w][0], wards[w][1])

    con.execute("CREATE OR REPLACE TEMP TABLE pip_assign (rowid BIGINT, wd VARCHAR, lad VARCHAR)")
    con.executemany(
        "INSERT INTO pip_assign VALUES (?, ?, ?)",
        [(int(rowids[p]), wd, lad) for p, (wd, lad) in assigned.items()],
    )
    con.execute(
        "UPDATE crimes SET wd25cd = t.wd, lad25cd = t.lad "
        "FROM pip_assign t WHERE crimes.rowid = t.rowid"
    )

    ni_total, ni_assigned = con.execute(
        "SELECT count(*), count(lad25cd) FROM crimes WHERE force = 'northern-ireland'"
    ).fetchone()
    print(
        f"assign_ni: {len(assigned):,}/{len(rows):,} unassigned rows resolved by PIP; "
        f"NI coverage {ni_assigned:,}/{ni_total:,} ({100 * ni_assigned / max(ni_total, 1):.1f}%)"
    )


if __name__ == "__main__":
    with duckdb.connect(str(config.DB_PATH)) as con:
        run(con)
