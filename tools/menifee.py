"""Real public data about land in Menifee, California, as JSON on stdout. Standard library only.

    python tools/menifee.py parcels --min-acres 80 [--zoning EDC] [--vacant] [--limit 25]
    python tools/menifee.py parcel 372100001            one parcel: facts, centre point, outline (GeoJSON)
    python tools/menifee.py site 372100001 [--miles 1]  the parcel plus what surrounds it
    python tools/menifee.py selfcheck                   every source answered just now? (exit 1 if one did not)

Where the numbers come from (each answer names its source and says when one did not answer):
  - City of Menifee's public GIS (ArcGIS Online, org RjTKod25O4b8SbZx): parcels (APN, acres, zoning, general plan
    land use, assessor class, assessed land and structure value, fire hazard zone), the zoning layer and the
    general plan layer with their descriptions.
  - U.S. Geological Survey elevation point service (epqs.nationalmap.gov): feet above sea level.
  - Caltrans annual average daily traffic counts on state highways (I-215, SR-74, SR-79).

What this is not: a survey, a title report or the city's decision. Zoning and the general plan say what is allowed
today; a change of use goes through the city (general plan amendment, zone change, specific plan). Parcel outlines
are the assessor's drawing, not a boundary survey.
"""
import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CITY = "https://services.arcgis.com/RjTKod25O4b8SbZx/arcgis/rest/services"
PARCELS = f"{CITY}/Menifee_Parcels/FeatureServer/0"
ZONING = f"{CITY}/Zoning_WEB/FeatureServer/9"
GENERAL_PLAN = f"{CITY}/General_Plan/FeatureServer/6"
ELEVATION = "https://epqs.nationalmap.gov/v1/json"
TRAFFIC = "https://caltrans-gis.dot.ca.gov/arcgis/rest/services/CHhighway/Traffic_AADT/FeatureServer/0"
PARCEL_FIELDS = ("APN,APNFormat,Acres,Zoning,LandUse,ClassCode,SitusStreet,SitusCity,SubdivisionName,Land,Structures,"
                 "FIRE_HAZARD_ZONE,CouncilDistrict")
AGENT = "land-planner/0.1 (public data lookup)"
VACANT_WORDS = ("vacant", "no imps")


class SourceError(Exception):
    """One source did not answer usefully; the message says which and why."""


def get_json(url, params=None, timeout=30, tries=2):
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    last = ""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed public https hosts above
                data = json.loads(r.read().decode("utf-8", "replace"))
            if isinstance(data, dict) and data.get("error"):
                raise SourceError(f"{url}: {data['error'].get('message') or data['error']}")
            return data
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            last = f"{url}: {type(e).__name__}: {e}"
            time.sleep(0.6 * (attempt + 1))
    raise SourceError(last[:300])


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def clean_apn(apn):
    digits = "".join(c for c in str(apn) if c.isdigit())
    if not 8 <= len(digits) <= 12:
        raise SourceError(f"{apn!r} is not a parcel number (9 digits, with or without dashes)")
    return digits


def parcel_row(a):
    land, built = a.get("Land") or 0, a.get("Structures") or 0
    cls = str(a.get("ClassCode") or "")
    return {"apn": a.get("APN"), "apn_formatted": a.get("APNFormat"), "acres": a.get("Acres"),
            "zoning": a.get("Zoning"), "general_plan": a.get("LandUse"), "assessor_class": cls,
            "looks_vacant": bool(not built and (not cls or any(w in cls.lower() for w in VACANT_WORDS) or "acres" in cls.lower())),
            "address": " ".join(x for x in (a.get("SitusStreet"), a.get("SitusCity")) if x).strip(),
            "subdivision": a.get("SubdivisionName") or "", "assessed_land_usd": land, "assessed_structures_usd": built,
            "fire_hazard_zone": a.get("FIRE_HAZARD_ZONE") or "none listed", "council_district": a.get("CouncilDistrict")}


def parcels(min_acres=0.0, max_acres=None, zoning="", vacant=False, limit=25):
    """Parcels by size (largest first), optionally by a zoning code that contains `zoning` and only vacant ones."""
    where = [f"Acres >= {float(min_acres)}"]
    if max_acres is not None:
        where.append(f"Acres <= {float(max_acres)}")
    if zoning:
        where.append(f"UPPER(Zoning) LIKE {quote('%' + zoning.upper() + '%')}")
    if vacant:
        where.append("(Structures = 0 OR Structures IS NULL)")
    data = get_json(f"{PARCELS}/query", {"where": " AND ".join(where), "outFields": PARCEL_FIELDS,
                                         "returnGeometry": "false", "orderByFields": "Acres DESC",
                                         "resultRecordCount": max(1, min(int(limit), 200)), "f": "json"})
    rows = [parcel_row(f["attributes"]) for f in data.get("features", [])]
    if vacant:
        rows = [r for r in rows if r["looks_vacant"]]
    return {"source": "City of Menifee parcels (public GIS)", "count": len(rows), "parcels": rows}


def parcel(apn):
    """One parcel with its centre point and outline in latitude/longitude."""
    apn = clean_apn(apn)
    data = get_json(f"{PARCELS}/query", {"where": f"APN = {quote(apn)}", "outFields": PARCEL_FIELDS,
                                         "returnGeometry": "true", "returnCentroid": "true", "outSR": 4326,
                                         "geometryPrecision": 6, "f": "json"})
    feats = data.get("features") or []
    if not feats:
        raise SourceError(f"no Menifee parcel has the number {apn}")
    f = feats[0]
    rings = (f.get("geometry") or {}).get("rings") or []
    c = f.get("centroid") or ring_centre(rings)
    out = parcel_row(f["attributes"])
    out.update(source="City of Menifee parcels (public GIS)", centre={"lat": c["y"], "lon": c["x"]},
               outline={"type": "Polygon", "coordinates": rings},
               size_feet=bounding_feet(rings))
    return out


def ring_centre(rings):
    pts = [p for r in rings for p in r] or [[0, 0]]
    return {"x": sum(p[0] for p in pts) / len(pts), "y": sum(p[1] for p in pts) / len(pts)}


def bounding_feet(rings):
    """Rough east-west and north-south extent of the outline in feet (flat-earth maths, fine at parcel size)."""
    pts = [p for r in rings for p in r]
    if not pts:
        return None
    lat = sum(p[1] for p in pts) / len(pts)
    ft_lat, ft_lon = 364000.0, 364000.0 * math.cos(math.radians(lat))
    return {"east_west": round((max(p[0] for p in pts) - min(p[0] for p in pts)) * ft_lon),
            "north_south": round((max(p[1] for p in pts) - min(p[1] for p in pts)) * ft_lat)}


def at_point(layer, lon, lat, fields):
    data = get_json(f"{layer}/query", {"geometry": json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}),
                                       "geometryType": "esriGeometryPoint", "inSR": 4326,
                                       "spatialRel": "esriSpatialRelIntersects", "outFields": fields,
                                       "returnGeometry": "false", "f": "json"})
    feats = data.get("features") or []
    return feats[0]["attributes"] if feats else None


def zoning_at(lon, lat):
    a = at_point(ZONING, lon, lat, "Zone,ZoneDesc,ZoneAbbrev,LandUseDesc")
    return a and {"zone": a.get("Zone"), "abbrev": a.get("ZoneAbbrev"), "what_it_allows": a.get("ZoneDesc"),
                  "general_plan_says": a.get("LandUseDesc")}


def general_plan_at(lon, lat):
    a = at_point(GENERAL_PLAN, lon, lat, "LandUse,Label,SpecificPlanName,LandUse_Desc")
    return a and {"land_use": a.get("LandUse"), "label": a.get("Label"), "specific_plan": a.get("SpecificPlanName") or "",
                  "description": a.get("LandUse_Desc")}


def circle(lon, lat, miles, points=24):
    """A circle of `miles` around the point as a polygon. The city's service draws its own "distance" search about
    four times too wide (measured 2026-11-25: a quarter mile around an empty 142-acre parcel returned 1,012
    parcels; this exact circle returns 3), so the shape is always sent explicitly."""
    dlat, dlon = miles / 69.17, miles / (69.17 * math.cos(math.radians(lat)))
    ring = [[round(lon + dlon * math.cos(2 * math.pi * i / points), 6), round(lat + dlat * math.sin(2 * math.pi * i / points), 6)]
            for i in range(points)]
    return {"rings": [ring + [ring[0]]], "spatialReference": {"wkid": 4326}}


def neighbours(lon, lat, miles=1.0):
    """Acres and parcel counts by zoning within `miles` of the point: what already surrounds the site. A parcel
    that the circle only touches counts whole."""
    stats = [{"statisticType": "sum", "onStatisticField": "Acres", "outStatisticFieldName": "acres"},
             {"statisticType": "count", "onStatisticField": "APN", "outStatisticFieldName": "parcels"}]
    data = get_json(f"{PARCELS}/query", {
        "geometry": json.dumps(circle(lon, lat, float(miles))), "geometryType": "esriGeometryPolygon", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "outStatistics": json.dumps(stats),
        "groupByFieldsForStatistics": "Zoning", "f": "json"})
    rows = sorted(({"zoning": f["attributes"].get("Zoning") or "(none)", "acres": round(f["attributes"].get("acres") or 0, 1),
                    "parcels": f["attributes"].get("parcels") or 0} for f in data.get("features", [])),
                  key=lambda r: -r["acres"])
    total = sum(r["acres"] for r in rows) or 1.0
    for r in rows:
        r["share_pct"] = round(100 * r["acres"] / total, 1)
    return {"within_miles": miles, "total_acres": round(total, 1), "by_zoning": rows[:15]}


def elevation_ft(lon, lat):
    data = get_json(ELEVATION, {"x": lon, "y": lat, "units": "Feet", "wkid": 4326, "includeDate": "false"}, timeout=25)
    v = data.get("value")
    if v in (None, "", -1000000):
        raise SourceError("USGS has no elevation for that point")
    return round(float(v), 1)


def terrain(rings, centre):
    """Elevation at the centre and the outline's extreme points, and the fall across the site: flat land is cheap
    to grade, a steep site is not."""
    pts = [p for r in rings for p in r]
    if not pts:
        return None
    picks = {"centre": (centre["lon"], centre["lat"]), "north": max(pts, key=lambda p: p[1]),
             "south": min(pts, key=lambda p: p[1]), "east": max(pts, key=lambda p: p[0]), "west": min(pts, key=lambda p: p[0])}
    feet = {name: elevation_ft(p[0], p[1]) for name, p in picks.items()}
    size = bounding_feet(rings) or {}
    span = max(size.get("east_west", 0), size.get("north_south", 0)) or 1
    fall = round(max(feet.values()) - min(feet.values()), 1)
    slope = round(100 * fall / span, 1)
    return {"feet_above_sea_level": feet, "fall_across_site_ft": fall, "rough_slope_pct": slope,
            "reading": "nearly flat" if slope < 2 else "gentle" if slope < 5 else "moderate" if slope < 10 else "steep"}


def traffic(lon, lat, miles=4.0, limit=6):
    """The nearest Caltrans count stations on state highways (vehicles per day, both directions summed by Caltrans)."""
    data = get_json(f"{TRAFFIC}/query", {
        "geometry": json.dumps(circle(lon, lat, float(miles))), "geometryType": "esriGeometryPolygon", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "outFields": "RTE,DESCRIPTION,BACK_AADT,AHEAD_AADT,AHEAD_PEAK_HOUR",
        "returnGeometry": "true", "outSR": 4326, "f": "json"}, timeout=40)
    rows, seen = [], set()
    for f in data.get("features", []):
        a, g = f["attributes"], f.get("geometry") or {}
        key = (a.get("RTE"), a.get("DESCRIPTION"))
        if g.get("x") is None or key in seen:  # one row per station (each direction is listed separately)
            continue
        seen.add(key)
        d = math.hypot((g["x"] - lon) * 69.17 * math.cos(math.radians(lat)), (g["y"] - lat) * 69.17)
        rows.append({"route": a.get("RTE"), "where": a.get("DESCRIPTION"), "vehicles_per_day_behind": a.get("BACK_AADT"),
                     "vehicles_per_day_ahead": a.get("AHEAD_AADT"), "peak_hour_ahead": a.get("AHEAD_PEAK_HOUR"),
                     "miles_away": round(d, 2)})
    rows.sort(key=lambda r: r["miles_away"])
    return {"within_miles": miles, "stations": rows[:limit],
            "note": "state highways only; city streets need Menifee's own traffic counts"}


def site(apn, miles=1.0):
    """Everything known about one parcel and its surroundings. A source that fails is listed, the rest still come."""
    p = parcel(apn)
    lon, lat = p["centre"]["lon"], p["centre"]["lat"]
    out = {"parcel": p, "sources": {"parcel": "ok"}}
    steps = {"zoning": lambda: zoning_at(lon, lat), "general_plan": lambda: general_plan_at(lon, lat),
             "surroundings": lambda: neighbours(lon, lat, miles),
             "terrain": lambda: terrain(p["outline"]["coordinates"], p["centre"]),
             "state_highway_traffic": lambda: traffic(lon, lat)}
    for name, fn in steps.items():
        try:
            out[name] = fn()
            out["sources"][name] = "ok" if out[name] else "nothing found there"
        except SourceError as e:
            out[name] = None
            out["sources"][name] = f"did not answer: {e}"
    out["not_included"] = ["population and income (the Census API now needs a free key)",
                           "city street traffic counts", "utilities, flood zones, environmental constraints",
                           "what the owner paid or current market prices"]
    return out


def selfcheck():
    apn = "372100001"  # a 142-acre parcel in the Economic Development Corridor
    checks = {"parcels": lambda: parcels(min_acres=100, limit=3)["count"] > 0,
              "parcel": lambda: abs(parcel(apn)["acres"] - 142.1) < 5,
              "zoning": lambda: bool(zoning_at(-117.166542, 33.652383)),
              "general_plan": lambda: bool(general_plan_at(-117.166542, 33.652383)),
              "surroundings": lambda: neighbours(-117.166542, 33.652383)["total_acres"] > 100,
              "elevation": lambda: 1000 < elevation_ft(-117.166542, 33.652383) < 2500,
              "state_highway_traffic": lambda: len(traffic(-117.166542, 33.652383)["stations"]) > 0}
    out = {}
    for name, fn in checks.items():
        try:
            out[name] = "ok" if fn() else "answered, but not what was expected"
        except SourceError as e:
            out[name] = f"did not answer: {e}"
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Public land data for Menifee, California (JSON on stdout).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("parcels")
    a.add_argument("--min-acres", type=float, default=50)
    a.add_argument("--max-acres", type=float)
    a.add_argument("--zoning", default="")
    a.add_argument("--vacant", action="store_true")
    a.add_argument("--limit", type=int, default=25)
    sub.add_parser("parcel").add_argument("apn")
    a = sub.add_parser("site")
    a.add_argument("apn")
    a.add_argument("--miles", type=float, default=1.0)
    sub.add_parser("selfcheck")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "parcels":
            out = parcels(args.min_acres, args.max_acres, args.zoning, args.vacant, args.limit)
        elif args.cmd == "parcel":
            out = parcel(args.apn)
        elif args.cmd == "site":
            out = site(args.apn, args.miles)
        else:
            out = selfcheck()
    except SourceError as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return 1
    print(json.dumps(out, indent=2))
    return 1 if args.cmd == "selfcheck" and any(v != "ok" for v in out.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
