"""Make the data file for the site report page. One command, then double-click report/index.html.

    python tools/build_report.py 372100001              (an example parcel: the page says so)
    python tools/build_report.py <APN> --confirmed      the parcel really is the owner's: no "example" banner

Everything comes from tools/menifee.py (`site`), plus three things only the page needs: the neighbouring parcels'
outlines (city GIS), the city's names for its zoning codes, and a grid of ground heights (USGS 3DEP).
Nothing is filled in by hand; whatever a source does not answer is left empty and the page says "not covered yet".
"""
import argparse
import datetime
import json
import math
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import menifee

OUT = Path(__file__).resolve().parent.parent / "report" / "data.js"
SAMPLES = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/getSamples"
FEET_PER_METRE = 3.280839895


def grid_points(rings, cells=44, margin=0.12):
    """A regular grid over the outline's bounding box (plus a margin), row by row from south to north."""
    pts = [p for r in rings for p in r]
    west, east = min(p[0] for p in pts), max(p[0] for p in pts)
    south, north = min(p[1] for p in pts), max(p[1] for p in pts)
    dx, dy = (east - west) * margin, (north - south) * margin
    west, east, south, north = west - dx, east + dx, south - dy, north + dy
    wide = (east - west) * 364000 * math.cos(math.radians((south + north) / 2))
    tall = (north - south) * 364000
    step = max(wide, tall) / cells
    nx, ny = max(2, round(wide / step) + 1), max(2, round(tall / step) + 1)
    points = [[round(west + (east - west) * i / (nx - 1), 7), round(south + (north - south) * j / (ny - 1), 7)]
              for j in range(ny) for i in range(nx)]
    return {"west": west, "east": east, "south": south, "north": north, "nx": nx, "ny": ny,
            "spacing_ft": round(step)}, points


def sample_feet(points, batch=250):
    """Ground height in feet for each point (None where USGS has no value). 3DEP answers in metres."""
    out = []
    for start in range(0, len(points), batch):
        chunk = points[start:start + batch]
        body = urllib.parse.urlencode({
            "geometry": json.dumps({"points": chunk, "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryMultipoint", "returnFirstValueOnly": "true", "f": "json"}).encode()
        try:
            req = urllib.request.Request(SAMPLES, data=body, headers={"User-Agent": menifee.AGENT})
            with urllib.request.urlopen(req, timeout=90) as r:  # noqa: S310 - fixed public https host
                data = json.loads(r.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            raise menifee.SourceError(f"USGS 3DEP: {type(e).__name__}: {e}") from e
        if "samples" not in data:
            raise menifee.SourceError(f"USGS 3DEP: {str(data.get('error') or data)[:200]}")
        found = {}
        for s in data["samples"]:
            try:
                metres = float(s["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if -500 < metres < 9000:
                found[s["locationId"]] = round(metres * FEET_PER_METRE, 1)
        out += [found.get(i) for i in range(len(chunk))]
    return out


def surface(rings):
    grid, points = grid_points(rings)
    grid["feet"] = sample_feet(points)
    if sum(v is not None for v in grid["feet"]) < 0.95 * len(points):
        raise menifee.SourceError("USGS 3DEP left too many gaps over this parcel")
    grid["source"] = "USGS 3D Elevation Program (3DEP)"
    return grid


def neighbour_shapes(lon, lat, miles):
    """Outlines of the parcels the search circle touches, thinned for drawing."""
    shapes, offset = [], 0
    while True:
        data = menifee.get_json(f"{menifee.PARCELS}/query", {
            "geometry": json.dumps(menifee.circle(lon, lat, miles)), "geometryType": "esriGeometryPolygon",
            "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": "APN,Zoning,Acres",
            "returnGeometry": "true", "outSR": 4326, "geometryPrecision": 5, "maxAllowableOffset": 0.00003,
            "orderByFields": "APN", "resultOffset": offset, "resultRecordCount": 1000, "f": "json"}, timeout=60)
        feats = data.get("features") or []
        for f in feats:
            a, rings = f["attributes"], (f.get("geometry") or {}).get("rings")
            if rings:
                shapes.append({"apn": a.get("APN"), "zoning": a.get("Zoning") or "(none)", "acres": a.get("Acres"),
                               "rings": rings})
        offset += len(feats)
        if not feats or not data.get("exceededTransferLimit") or offset >= 8000:
            return shapes


def zone_names():
    """The city's own short code -> name table, from its zoning layer."""
    data = menifee.get_json(f"{menifee.ZONING}/query", {
        "where": "1=1", "outFields": "ZoneAbbrev,ZoneDesc", "returnDistinctValues": "true",
        "returnGeometry": "false", "f": "json"})
    names = {}
    for f in data.get("features", []):
        code, name = f["attributes"].get("ZoneAbbrev"), f["attributes"].get("ZoneDesc")
        # "SP" and the "PDO" overlays have one name per project, so the code alone does not say which
        if code and name and code != "SP" and not code.startswith("PDO"):
            names[code] = name
    return names


def build(apn, miles=1.0, confirmed=False):
    data = menifee.site(apn, miles)
    lon, lat = data["parcel"]["centre"]["lon"], data["parcel"]["centre"]["lat"]
    rings = data["parcel"]["outline"]["coordinates"]
    extras = {"surface": lambda: surface(rings),
              "neighbour_shapes": lambda: neighbour_shapes(lon, lat, miles),
              "zone_names": zone_names}
    for name, fn in extras.items():
        try:
            data[name] = fn()
            data["sources"][name] = "ok" if data[name] else "nothing found there"
        except menifee.SourceError as e:
            data[name] = None
            data["sources"][name] = f"did not answer: {e}"
    data["example"] = not confirmed
    data["fetched"] = datetime.date.today().isoformat()
    return data


def write(data, out=OUT):
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, separators=(",", ":"))
    out.write_text("// Written by tools/build_report.py - do not edit by hand.\nwindow.SITE = " + text + ";\n",
                   encoding="utf-8", newline="\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch one parcel's facts into report/data.js")
    ap.add_argument("apn")
    ap.add_argument("--miles", type=float, default=1.0)
    ap.add_argument("--confirmed", action="store_true", help="the parcel is really the owner's (no example banner)")
    args = ap.parse_args(argv)
    try:
        data = build(args.apn, args.miles, args.confirmed)
    except menifee.SourceError as e:
        print(f"Nothing written. {e}")
        return 1
    write(data)
    print(f"Wrote {OUT}")
    for name, state in data["sources"].items():
        print(f"  {name}: {state}")
    print("Now open report/index.html (double-click).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
