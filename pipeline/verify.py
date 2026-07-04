"""Checkpoint report after a pipeline run: row counts, join coverage, rate sanity.

Prints warnings freely; exits non-zero only on hard failures (empty tables,
join coverage collapse) so `make all` stops before serving bad data.
"""
from __future__ import annotations

import sys

import duckdb

from . import config

HARD_FAILURES: list[str] = []


def check(ok: bool, label: str, detail: str, hard: bool = False) -> None:
    print(f"  [{'ok' if ok else 'FAIL' if hard else 'warn'}] {label}: {detail}")
    if not ok and hard:
        HARD_FAILURES.append(label)


def run(con: duckdb.DuckDBPyConnection) -> None:
    months = config.month_window()
    print(f"verify: window {months[0]} .. {months[-1]}")

    n = con.execute("SELECT count(*) FROM crimes").fetchone()[0]
    check(n > 0, "crimes rows", f"{n:,}", hard=True)

    # E+W LSOA join coverage (the >=99% checkpoint; PSNI/coordless excluded)
    ew_total, ew_lsoa, ew_lad = con.execute(
        "SELECT count(*), count(lsoa21cd), count(lad25cd) FROM crimes "
        "WHERE force NOT IN ('northern-ireland', 'btp')"
    ).fetchone()
    if ew_total:
        pct = 100 * ew_lsoa / ew_total
        check(pct >= 95, "E+W LSOA join", f"{pct:.2f}% (target >=99%)", hard=pct < 95)
        check(True, "E+W LAD incl. PIP", f"{100 * ew_lad / ew_total:.2f}%")

    ni_total, ni_lad = con.execute(
        "SELECT count(*), count(lad25cd) FROM crimes WHERE force = 'northern-ireland'"
    ).fetchone()
    if ni_total:
        pct = 100 * ni_lad / ni_total
        check(pct >= 98, "NI PIP coverage", f"{pct:.2f}% of {ni_total:,}")

    coords = con.execute("SELECT 100.0 * count(lon) / count(*) FROM crimes").fetchone()[0]
    check(True, "rows with coordinates", f"{coords:.2f}%")

    unknown = [r[0] for r in con.execute(
        "SELECT DISTINCT category FROM crimes WHERE category NOT IN (SELECT category FROM severity)"
    ).fetchall()]
    check(not unknown, "crime categories known", f"unknown: {unknown or 'none'}")

    # forces with missing months (known gap 2026-02..04)
    short = con.execute(
        "SELECT force, count(DISTINCT month) m FROM crimes GROUP BY 1 HAVING m < ? ORDER BY m",
        [len(months)],
    ).fetchall()
    check(not short, "forces with full window",
          f"{len(short)} short: {[(f, m) for f, m in short[:8]]}" if short else "all complete")

    nodata, names = con.execute(
        "SELECT count(*), coalesce(list(name ORDER BY name), []) FROM agg_region "
        "WHERE level = 'lad' AND rate_per_1000 IS NULL"
    ).fetchone()
    check(True, "LADs with no local-force data",
          f"{nodata} shown as no-data {names[:6]}{'...' if nodata > 6 else ''}")

    for level, expected in (("lad", 330), ("ward", 7900), ("lsoa", 35672)):
        got = con.execute("SELECT count(*) FROM agg_region WHERE level = ?", [level]).fetchone()[0]
        check(got >= expected * 0.95, f"agg_region/{level}", f"{got} regions", hard=got == 0)

    nopop = con.execute(
        "SELECT count(*) FROM boundaries b WHERE b.code NOT LIKE 'S%' "
        "AND NOT EXISTS (SELECT 1 FROM population p WHERE p.code = b.code AND p.level = b.level)"
    ).fetchone()[0]
    check(nopop == 0, "boundaries with population", f"{nopop} missing (excl. Scotland)")

    print("  top LAD rates (expect City of London / Westminster up top):")
    for code, name, rate, crimes in con.execute(
        "SELECT code, name, rate_per_1000, crimes_12m FROM agg_region "
        "WHERE level = 'lad' ORDER BY rate_per_1000 DESC LIMIT 5"
    ).fetchall():
        print(f"    {rate:8.1f}/1k  {name} ({code}, {crimes:,} crimes)")

    if HARD_FAILURES:
        print(f"verify: HARD FAILURES: {HARD_FAILURES}")
        sys.exit(1)
    print("verify: passed")


if __name__ == "__main__":
    with duckdb.connect(str(config.DB_PATH), read_only=True) as con:
        run(con)
