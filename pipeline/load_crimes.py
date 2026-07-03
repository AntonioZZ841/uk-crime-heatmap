"""Load the extracted street CSVs into the crimes table.

E+W rows get ward/LAD assigned via the LSOA lookup here; NI (and any row whose
LSOA code fails the lookup) stays NULL and is picked up by assign_ni.py's
point-in-polygon pass. Requires lookup_lsoa (load_reference) to exist.
"""
from __future__ import annotations

import duckdb

import config

CSV_COLUMNS = """{
    'Crime ID': 'VARCHAR', 'Month': 'VARCHAR', 'Reported by': 'VARCHAR',
    'Falls within': 'VARCHAR', 'Longitude': 'DOUBLE', 'Latitude': 'DOUBLE',
    'Location': 'VARCHAR', 'LSOA code': 'VARCHAR', 'LSOA name': 'VARCHAR',
    'Crime type': 'VARCHAR', 'Last outcome category': 'VARCHAR', 'Context': 'VARCHAR'
}"""


def run(con: duckdb.DuckDBPyConnection) -> None:
    glob = config.CSV_DIR.as_posix() + "/*/*-street.csv"  # forward slashes: works on Windows too
    con.execute(
        f"""
        CREATE OR REPLACE TABLE crimes AS
        SELECT
            nullif(c."Crime ID", '')                AS crime_id,
            cast(c.Month || '-01' AS DATE)          AS month,
            regexp_extract(c.filename, '(\\d{{4}}-\\d{{2}})-([a-z0-9-]+)-street\\.csv$', 2) AS force,
            c.Longitude                             AS lon,
            c.Latitude                              AS lat,
            nullif(c.Location, '')                  AS location,
            c."Crime type"                          AS category,
            nullif(c."Last outcome category", '')   AS outcome,
            l.lsoa21cd                              AS lsoa21cd,
            l.wd25cd                                AS wd25cd,
            l.lad25cd                               AS lad25cd
        FROM read_csv('{glob}', header = true, filename = true, columns = {CSV_COLUMNS}) c
        LEFT JOIN lookup_lsoa l ON nullif(c."LSOA code", '') = l.lsoa21cd
        """
    )
    # a handful of rows per million have shifted columns from malformed quoting;
    # they surface as unknown categories and are unusable
    bad = con.execute(
        "DELETE FROM crimes WHERE category NOT IN (SELECT category FROM severity) RETURNING 1"
    ).fetchall()
    n, months, forces = con.execute(
        "SELECT count(*), count(DISTINCT month), count(DISTINCT force) FROM crimes"
    ).fetchone()
    print(f"crimes: {n:,} rows, {months} months, {forces} forces ({len(bad)} malformed rows dropped)")


if __name__ == "__main__":
    with duckdb.connect(str(config.DB_PATH)) as con:
        run(con)
