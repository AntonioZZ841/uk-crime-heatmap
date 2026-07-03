"""Build the aggregate tables the API reads: per-region counts, rates, ranks.

Rates are annualised from the months the region's LOCAL FORCE actually
reported (crimes * 12/reported_months / population * 1000), so a force with a
publication gap (Gwent, Gloucestershire) is scaled truthfully rather than
looking artificially safe. Regions whose local force published nothing at all
(Greater Manchester - GMP has not published to data.police.uk since 2019) get
a NULL rate and render as "no data", not as deep blue. A region's force is
the modal non-BTP force of its own crimes, inherited from its parent LAD when
the region itself recorded none. Scotland is excluded (the API surfaces it as
nulls); NI wards/LSOAs are excluded (no NI small-area population - NI stays
at LAD level by design).
"""
from __future__ import annotations

import json

import duckdb

import config

LEVEL_COLUMN = {"lad": "lad25cd", "ward": "wd25cd", "lsoa": "lsoa21cd"}


def run(con: duckdb.DuckDBPyConnection) -> None:
    months = config.month_window()

    # months each (non-transport) force reported within the window
    con.execute(
        "CREATE OR REPLACE TEMP TABLE force_months AS "
        "SELECT force, count(DISTINCT month) AS m FROM crimes WHERE force <> 'btp' GROUP BY 1"
    )
    # dominant local force per LAD (fallback coverage for quiet child regions)
    con.execute(
        "CREATE OR REPLACE TEMP TABLE lad_force AS "
        "SELECT lad25cd AS code, mode(force) FILTER (force <> 'btp') AS force "
        "FROM crimes WHERE lad25cd IS NOT NULL GROUP BY 1"
    )
    # region -> parent LAD, for that fallback
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE region_lad AS
        SELECT 'lad' AS level, code, code AS lad_code FROM boundaries WHERE level = 'lad'
        UNION ALL
        SELECT 'ward', code, parent_code FROM boundaries WHERE level = 'ward'
        UNION ALL
        SELECT 'lsoa', lsoa21cd, lad25cd FROM lookup_lsoa
        """
    )

    con.execute(
        "CREATE OR REPLACE TEMP TABLE agg_tmp ("
        " level VARCHAR, code VARCHAR, name VARCHAR, parent_code VARCHAR,"
        " crimes_12m BIGINT, population BIGINT, rate_per_1000 DOUBLE,"
        " severity_sum DOUBLE, top_category VARCHAR, months_present INTEGER)"
    )
    for level, col in LEVEL_COLUMN.items():
        con.execute(
            f"""
            INSERT INTO agg_tmp
            WITH c AS (
                SELECT {col} AS code, count(*) AS n,
                       mode(crimes.force) FILTER (crimes.force <> 'btp') AS dom_force,
                       sum(coalesce(s.weight, 1.0)) AS sev, mode(crimes.category) AS top_cat
                FROM crimes LEFT JOIN severity s ON s.category = crimes.category
                WHERE {col} IS NOT NULL
                GROUP BY 1
            )
            SELECT '{level}', b.code, b.name, b.parent_code,
                   coalesce(c.n, 0), p.population,
                   CASE WHEN fm.m > 0 THEN
                       round(coalesce(c.n, 0) * (12.0 / fm.m) * 1000.0 / p.population, 2)
                   END,
                   coalesce(c.sev, 0), c.top_cat, coalesce(fm.m, 0)
            FROM boundaries b
            JOIN population p ON p.code = b.code AND p.level = '{level}'
            LEFT JOIN c ON c.code = b.code
            LEFT JOIN region_lad rl ON rl.level = '{level}' AND rl.code = b.code
            LEFT JOIN lad_force lf ON lf.code = rl.lad_code
            LEFT JOIN force_months fm ON fm.force = coalesce(c.dom_force, lf.force)
            WHERE b.level = '{level}' AND b.code NOT LIKE 'S%'
            """
        )
    # Implausibly low LAD rates are force-publication gaps (e.g. Greater
    # Manchester: only BTP + border-spillover rows), not low crime. Null them
    # out and cascade the verdict to their wards/LSOAs.
    con.execute(
        "CREATE OR REPLACE TEMP TABLE bad_lads AS SELECT code FROM agg_tmp "
        "WHERE level = 'lad' AND (rate_per_1000 IS NULL OR rate_per_1000 < ?)",
        [config.MIN_PLAUSIBLE_LAD_RATE],
    )
    con.execute(
        "UPDATE agg_tmp SET rate_per_1000 = NULL, months_present = 0 "
        "WHERE (level = 'lad' AND code IN (SELECT code FROM bad_lads)) "
        "   OR (level = 'ward' AND parent_code IN (SELECT code FROM bad_lads)) "
        "   OR (level = 'lsoa' AND code IN "
        "       (SELECT lsoa21cd FROM lookup_lsoa WHERE lad25cd IN (SELECT code FROM bad_lads)))"
    )
    con.execute(
        "CREATE OR REPLACE TABLE agg_region AS "
        "SELECT *, rank() OVER (PARTITION BY level ORDER BY rate_per_1000 DESC NULLS LAST) AS rank_by_rate "
        "FROM agg_tmp"
    )

    month_selects = " UNION ALL ".join(
        f"SELECT '{level}' AS level, {col} AS code, month, count(*) AS n "
        f"FROM crimes WHERE {col} IS NOT NULL GROUP BY 2, 3"
        for level, col in LEVEL_COLUMN.items()
    )
    con.execute(f"CREATE OR REPLACE TABLE agg_region_month AS {month_selects}")

    cat_selects = " UNION ALL ".join(
        f"SELECT '{level}' AS level, {col} AS code, category, count(*) AS n "
        f"FROM crimes WHERE {col} IS NOT NULL GROUP BY 2, 3"
        for level, col in LEVEL_COLUMN.items()
    )
    con.execute(f"CREATE OR REPLACE TABLE agg_region_category AS {cat_selects}")

    # bake the window into the DB so the runtime artifact is self-contained
    # (desktop bundles and cloud deploys ship only crime.duckdb, not data/raw)
    con.execute("CREATE OR REPLACE TABLE build_meta (months VARCHAR, mini BOOLEAN)")
    con.execute("INSERT INTO build_meta VALUES (?, ?)", [json.dumps(months), config.MINI_MODE])

    counts = dict(con.execute("SELECT level, count(*) FROM agg_region GROUP BY level").fetchall())
    nodata = con.execute(
        "SELECT count(*) FROM agg_region WHERE level = 'lad' AND rate_per_1000 IS NULL"
    ).fetchone()[0]
    print(f"agg_region: {counts} over a {len(months)}-month window; "
          f"{nodata} LADs with no local-force data (rendered as no-data)")


if __name__ == "__main__":
    with duckdb.connect(str(config.DB_PATH)) as con:
        run(con)
