"""Download everything the pipeline needs (idempotent - skips files already present).

1. Pin the month window (crime-last-updated API -> window.json)
2. Stream the window's *-street.csv members out of the police archive zip
3. Boundary GeoJSON (LAD / ward / LSOA) from ONS ArcGIS, paged
4. LSOA->Ward->LAD lookup table
5. Two ONS population xlsx files
"""
from __future__ import annotations

import json
import re
import sys

import httpx

from . import config
from .remotezip import RemoteZip

STREET_RE = re.compile(r"^(\d{4}-\d{2})/\1-([a-z0-9-]+)-street\.csv$")


def http_client() -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(300, connect=30),
        headers={"User-Agent": "uk-crime-heatmap-pipeline"},
    )


def pin_window(client: httpx.Client) -> list[str]:
    latest = client.get(config.CRIME_LAST_UPDATED_URL).json()["date"][:7]
    months = config.compute_window(latest)
    config.WINDOW_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.WINDOW_FILE.write_text(json.dumps({"latest": latest, "months": months, "mini": config.MINI_MODE}))
    print(f"window: {months[0]} .. {months[-1]} ({len(months)} months, mini={config.MINI_MODE})")
    return months


def wanted_member(name: str, months: list[str]) -> bool:
    m = STREET_RE.match(name)
    if not m:
        return False
    month, force = m.groups()
    if month not in months:
        return False
    if config.MINI_MODE and force not in config.MINI_FORCES:
        return False
    if not config.INCLUDE_BTP and force == "btp":
        return False
    return True


def download_crimes(months: list[str]) -> None:
    rz = RemoteZip(config.POLICE_ARCHIVE_URL)
    try:
        wanted = sorted(n for n in rz.members if wanted_member(n, months))
        print(f"archive: {len(rz.members)} members, {len(wanted)} street CSVs in window")
        if not wanted:
            raise RuntimeError("no matching street CSVs in archive - window/pattern mismatch?")
        done = skipped = 0
        for name in wanted:
            target = config.CSV_DIR / name
            if target.exists() and target.stat().st_size == rz.members[name].uncomp_size:
                skipped += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(rz.read_member(name))
            done += 1
            if done % 25 == 0:
                print(f"  {done + skipped}/{len(wanted)} CSVs")
        print(f"crimes: {done} downloaded, {skipped} already present")
    finally:
        rz.close()


def arcgis_query_url(service: str) -> str:
    return f"{config.ARCGIS_BASE}/{service}/FeatureServer/0/query"


def fetch_paged(client: httpx.Client, service: str, out_fields: str, fmt: str) -> list[dict]:
    """Page through an ArcGIS layer; returns features (geojson) or attribute rows (json)."""
    items: list[dict] = []
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": out_fields,
            "f": fmt,
            "resultOffset": offset,
            "resultRecordCount": config.ARCGIS_PAGE_SIZE,
        }
        if fmt == "geojson":
            params["outSR"] = 4326
        data = client.get(arcgis_query_url(service), params=params).json()
        if "error" in data:
            raise RuntimeError(f"{service}: {data['error']}")
        page = data.get("features", [])
        # servers may cap pages below what we asked for (tables cap at 1000),
        # so the only reliable stop signal is an empty page
        if not page:
            return items
        items.extend(page if fmt == "geojson" else [f["attributes"] for f in page])
        offset += len(page)
        if offset > 200_000:
            raise RuntimeError(f"{service}: pagination runaway ({offset} rows)")


def download_boundaries(client: httpx.Client) -> None:
    config.BOUNDARY_DIR.mkdir(parents=True, exist_ok=True)
    for level, (service, expected, code_f, name_f, parent_f) in config.BOUNDARY_SERVICES.items():
        target = config.BOUNDARY_DIR / f"{level}.geojson"
        if target.exists() and target.stat().st_size > 0:
            print(f"boundaries/{level}: already present")
            continue
        fields = ",".join(f for f in (code_f, name_f, parent_f) if f)
        features = fetch_paged(client, service, fields, "geojson")
        if len(features) != expected:
            raise RuntimeError(f"{level}: expected {expected} features, got {len(features)}")
        target.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
        print(f"boundaries/{level}: {len(features)} features")


def download_lookup(client: httpx.Client) -> None:
    target = config.RAW_DIR / "lookup_lsoa.json"
    if target.exists() and target.stat().st_size > 0:
        print("lookup: already present")
        return
    service, expected = config.LOOKUP_SERVICE
    rows = fetch_paged(client, service, "LSOA21CD,LSOA21NM,WD25CD,WD25NM,LAD25CD,LAD25NM", "json")
    if len(rows) != expected:
        raise RuntimeError(f"lookup: expected {expected} rows, got {len(rows)}")
    target.write_text(json.dumps(rows))
    print(f"lookup: {len(rows)} rows")


def download_population(client: httpx.Client) -> None:
    for url, fname in ((config.POP_LSOA_URL, "pop_lsoa.xlsx"), (config.POP_LAD_URL, "pop_lad.xlsx")):
        target = config.RAW_DIR / fname
        if target.exists() and target.stat().st_size > 0:
            print(f"{fname}: already present")
            continue
        r = client.get(url)
        r.raise_for_status()
        if not r.content[:4] == b"PK\x03\x04":
            raise RuntimeError(f"{fname}: response is not an xlsx (got {r.content[:100]!r})")
        target.write_bytes(r.content)
        print(f"{fname}: {len(r.content) / 1e6:.1f} MB")


def main() -> None:
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    with http_client() as client:
        months = pin_window(client)
        download_boundaries(client)
        download_lookup(client)
        download_population(client)
    download_crimes(months)
    print("download: all done")


if __name__ == "__main__":
    sys.exit(main())
