"""Real public data about land in Menifee, California, as JSON on stdout. Standard library only.

    python tools/menifee.py parcels --min-acres 80 [--zoning EDC] [--vacant] [--limit 25]
    python tools/menifee.py parcel 372100001            one parcel: facts, centre point, outline (GeoJSON)
    python tools/menifee.py site 372100001 [--miles 1]  the parcel plus what surrounds it
    python tools/menifee.py selfcheck                   every source answered just now? (exit 1 if one did not)

The Land Planner app (landplanner/cities/menifee.py) reads the same functions, so the app and this tool agree.

Where the numbers come from (each answer names its source and says when one did not answer):
  - City of Menifee's public GIS (ArcGIS Online, org RjTKod25O4b8SbZx): parcels (APN, acres, zoning, general plan
    land use, assessor class, assessed land and structure value, fire hazard zone), the zoning layer and the
    general plan layer with their descriptions.
  - U.S. Geological Survey 3D Elevation Program (3DEP): ground height in feet above sea level, as single points
    and as a grid over a parcel. The older point service (epqs.nationalmap.gov) is the fallback.
  - Caltrans annual average daily traffic counts on state highways (I-215, SR-74, SR-79).

What this is not: a survey, a title report or the city's decision. Zoning and the general plan say what is allowed
today; a change of use goes through the city (general plan amendment, zone change, specific plan). Parcel outlines
are the assessor's drawing, not a boundary survey.
"""
import argparse
import json
import math
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

CITY = "https://services.arcgis.com/RjTKod25O4b8SbZx/arcgis/rest/services"
PARCELS = f"{CITY}/Menifee_Parcels/FeatureServer/0"
ZONING = f"{CITY}/Zoning_WEB/FeatureServer/9"
GENERAL_PLAN = f"{CITY}/General_Plan/FeatureServer/6"
ELEVATION = "https://epqs.nationalmap.gov/v1/json"
SAMPLES = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/getSamples"
FEET_PER_METRE = 3.280839895
TRAFFIC = "https://caltrans-gis.dot.ca.gov/arcgis/rest/services/CHhighway/Traffic_AADT/FeatureServer/0"
STREETS = f"{CITY}/Circulation_Element_Updated/FeatureServer/3"
SIGNALS = f"{CITY}/Traffic_Signals/FeatureServer/20"
PROJECTS = f"{CITY}/Land_Development_Projects/FeatureServer/7"
ECON_PROJECTS = f"{CITY}/EconDevProjects_2025/FeatureServer/10"
SCHOOLS = f"{CITY}/Schools_Points_2025/FeatureServer/9"
BLOCKS = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/2"
NAIP = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer"
PARCEL_FIELDS = ("APN,APNFormat,Acres,Zoning,LandUse,ClassCode,SitusStreet,SitusCity,SubdivisionName,Land,Structures,"
                 "FIRE_HAZARD_ZONE,CouncilDistrict")
AGENT = "land-planner/0.1 (public data lookup)"
VACANT_WORDS = ("vacant", "no imps")


class SourceError(Exception):
    """One source did not answer usefully; the message says which and why."""


class NotFound(SourceError):
    """The source answered, and there is no such parcel."""


def get_json(url, params=None, timeout=30, tries=2, post=False):
    """Every request this tool makes goes through here (the offline tests replace this one function)."""
    query = urllib.parse.urlencode(params) if params else ""
    full = url if post or not query else url + "?" + query
    last = ""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(full, data=query.encode() if post else None,
                                         headers={"User-Agent": AGENT, "Accept": "application/json"})
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
        raise NotFound(f"{apn!r} is not a parcel number (9 digits, with or without dashes)")
    return digits


def tidy(text):
    """The city's text with stray and non-breaking spaces removed (and its broken apostrophes mended)."""
    return " ".join(str(text or "").replace("\ufffd", "'").split())


def parcel_row(a):
    """One parcel's facts. A value the city leaves empty stays empty (None): nothing is filled in."""
    land, built = a.get("Land"), a.get("Structures")
    cls = str(a.get("ClassCode") or "")
    return {"apn": a.get("APN"), "apn_formatted": a.get("APNFormat"), "acres": a.get("Acres"),
            "zoning": tidy(a.get("Zoning")), "general_plan": a.get("LandUse"), "assessor_class": cls,
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


def large_parcels(min_acres=10.0):
    """Every parcel of `min_acres` or more, largest first, each with its centre point and a thinned outline
    (good enough to draw on a city map, not for measuring)."""
    rows, offset = [], 0
    while True:
        data = get_json(f"{PARCELS}/query", {
            "where": f"Acres >= {float(min_acres)}", "outFields": PARCEL_FIELDS, "returnGeometry": "true",
            "returnCentroid": "true", "outSR": 4326, "geometryPrecision": 5, "maxAllowableOffset": 0.00005,
            "orderByFields": "Acres DESC, APN", "resultOffset": offset, "resultRecordCount": 1000, "f": "json"}, timeout=60)
        feats = data.get("features") or []
        for f in feats:
            rings = (f.get("geometry") or {}).get("rings") or []
            c = f.get("centroid") or (ring_centre(rings) if rings else None)
            row = parcel_row(f["attributes"])
            row.update(centre=c and {"lat": round(c["y"], 6), "lon": round(c["x"], 6)}, rings=rings)
            rows.append(row)
        offset += len(feats)
        if not feats or not data.get("exceededTransferLimit") or offset >= 5000:
            return rows


def parcel(apn):
    """One parcel with its centre point and outline in latitude/longitude."""
    apn = clean_apn(apn)
    data = get_json(f"{PARCELS}/query", {"where": f"APN = {quote(apn)}", "outFields": PARCEL_FIELDS,
                                         "returnGeometry": "true", "returnCentroid": "true", "outSR": 4326,
                                         "geometryPrecision": 6, "f": "json"})
    feats = data.get("features") or []
    if not feats:
        raise NotFound(f"no Menifee parcel has the number {apn}")
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
    rows = sorted(({"zoning": tidy(f["attributes"].get("Zoning")) or "(none)", "acres": round(f["attributes"].get("acres") or 0, 1),
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


def sample_feet(points, batch=250, tries=3):
    """Ground height in feet for each [lon, lat] point (None where USGS has no value). 3DEP answers in metres.
    The service sometimes times out, so each batch is asked up to `tries` times; four batches run at a time."""
    def one(chunk):
        data = get_json(SAMPLES, {"geometry": json.dumps({"points": chunk, "spatialReference": {"wkid": 4326}}),
                                  "geometryType": "esriGeometryMultipoint", "returnFirstValueOnly": "true", "f": "json"},
                        timeout=45, tries=tries, post=True)
        if "samples" not in data:
            raise SourceError(f"USGS 3DEP: {str(data)[:200]}")
        found = {}
        for s in data["samples"]:
            try:
                metres = float(s["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if -500 < metres < 9000:
                found[s["locationId"]] = round(metres * FEET_PER_METRE, 1)
        return [found.get(i) for i in range(len(chunk))]

    chunks = [points[start:start + batch] for start in range(0, len(points), batch)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        return [height for part in pool.map(one, chunks) for height in part]


def terrain(rings, centre):
    """Elevation at the centre and the outline's extreme points, and the fall across the site: flat land is cheap
    to grade, a steep site is not. Five points only: `surface` below is the finer picture."""
    pts = [p for r in rings for p in r]
    if not pts:
        return None
    picks = {"centre": (centre["lon"], centre["lat"]), "north": max(pts, key=lambda p: p[1]),
             "south": min(pts, key=lambda p: p[1]), "east": max(pts, key=lambda p: p[0]), "west": min(pts, key=lambda p: p[0])}
    try:
        heights = sample_feet([[p[0], p[1]] for p in picks.values()], tries=2)
        if any(h is None for h in heights):
            raise SourceError("USGS 3DEP left a gap")
        feet = dict(zip(picks, heights))
    except SourceError:
        feet = {name: elevation_ft(p[0], p[1]) for name, p in picks.items()}
    size = bounding_feet(rings) or {}
    span = max(size.get("east_west", 0), size.get("north_south", 0)) or 1
    fall = round(max(feet.values()) - min(feet.values()), 1)
    slope = round(100 * fall / span, 1)
    return {"feet_above_sea_level": feet, "fall_across_site_ft": fall, "rough_slope_pct": slope,
            "reading": "nearly flat" if slope < 2 else "gentle" if slope < 5 else "moderate" if slope < 10 else "steep"}


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


def inside(rings, lon, lat):
    """Is the point inside the outline? (even-odd rule, so a hole in the outline counts as outside)"""
    hit = False
    for r in rings:
        for a, b in zip(r, r[1:] + r[:1]):
            if (a[1] > lat) != (b[1] > lat) and lon < (b[0] - a[0]) * (lat - a[1]) / (b[1] - a[1]) + a[0]:
                hit = not hit
    return hit


def surface_summary(grid, rings):
    """What the height grid says about the ground inside the outline: the lowest and highest sample and where
    they are, and how steep the ground is between neighbouring samples. Measured from the samples, nothing assumed."""
    nx, ny, feet = grid["nx"], grid["ny"], grid["feet"]

    def lon_of(i):
        return grid["west"] + (grid["east"] - grid["west"]) * i / (nx - 1)

    def lat_of(j):
        return grid["south"] + (grid["north"] - grid["south"]) * j / (ny - 1)

    step_x = (grid["east"] - grid["west"]) / (nx - 1) * 364000 * math.cos(math.radians((grid["south"] + grid["north"]) / 2))
    step_y = (grid["north"] - grid["south"]) / (ny - 1) * 364000
    spots = [(feet[j * nx + i], lon_of(i), lat_of(j)) for j in range(ny) for i in range(nx)
             if feet[j * nx + i] is not None and inside(rings, lon_of(i), lat_of(j))]
    if len(spots) < 4:
        return None
    slopes = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            z = [feet[j * nx + i], feet[j * nx + i + 1], feet[(j + 1) * nx + i], feet[(j + 1) * nx + i + 1]]
            if None in z or not inside(rings, (lon_of(i) + lon_of(i + 1)) / 2, (lat_of(j) + lat_of(j + 1)) / 2):
                continue
            east_west = (z[1] + z[3] - z[0] - z[2]) / (2 * step_x)
            north_south = (z[2] + z[3] - z[0] - z[1]) / (2 * step_y)
            slopes.append(100 * math.hypot(east_west, north_south))
    low, high = min(spots), max(spots)
    out = {"samples_inside": len(spots), "low_ft": low[0], "high_ft": high[0], "range_ft": round(high[0] - low[0], 1),
           "low_at": {"lat": round(low[2], 6), "lon": round(low[1], 6)},
           "high_at": {"lat": round(high[2], 6), "lon": round(high[1], 6)}}
    if len(slopes) >= 10:
        typical = statistics.median(slopes)
        out.update(typical_slope_pct=round(typical, 1), steepest_tenth_pct=round(statistics.quantiles(slopes, n=10)[-1], 1),
                   reading="nearly flat" if typical < 2 else "gentle" if typical < 5 else "moderate" if typical < 10 else "steep")
    return out


def surface(rings):
    """A grid of ground heights over the parcel (USGS 3DEP) and what it says about the ground inside the outline."""
    grid, points = grid_points(rings)
    grid["feet"] = sample_feet(points)
    if sum(v is not None for v in grid["feet"]) < 0.95 * len(points):
        raise SourceError("USGS 3DEP left too many gaps over this parcel")
    grid["source"] = "USGS 3D Elevation Program (3DEP)"
    grid["inside"] = surface_summary(grid, rings)
    return grid


def neighbour_shapes(lon, lat, miles=1.0):
    """Outlines of the parcels the search circle touches, thinned for drawing."""
    shapes, offset = [], 0
    while True:
        data = get_json(f"{PARCELS}/query", {
            "geometry": json.dumps(circle(lon, lat, miles)), "geometryType": "esriGeometryPolygon",
            "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": "APN,Zoning,Acres",
            "returnGeometry": "true", "outSR": 4326, "geometryPrecision": 5, "maxAllowableOffset": 0.00003,
            "orderByFields": "APN", "resultOffset": offset, "resultRecordCount": 1000, "f": "json"}, timeout=60)
        feats = data.get("features") or []
        for f in feats:
            a, rings = f["attributes"], (f.get("geometry") or {}).get("rings")
            if rings:
                shapes.append({"apn": a.get("APN"), "zoning": tidy(a.get("Zoning")) or "(none)", "acres": a.get("Acres"),
                               "rings": rings})
        offset += len(feats)
        if not feats or not data.get("exceededTransferLimit") or offset >= 8000:
            return shapes


def zone_names():
    """The city's own short code -> name table, from its zoning layer."""
    data = get_json(f"{ZONING}/query", {
        "where": "1=1", "outFields": "ZoneAbbrev,ZoneDesc", "returnDistinctValues": "true",
        "returnGeometry": "false", "f": "json"})
    names = {}
    for f in data.get("features", []):
        code, name = f["attributes"].get("ZoneAbbrev"), f["attributes"].get("ZoneDesc")
        # "SP" has one name per project, so the code alone does not say which
        if code and name and code != "SP":
            names[code] = tidy(name)
    return names


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
        rows.append({"route": str(a.get("RTE") or "").lstrip("0") or a.get("RTE"), "where": a.get("DESCRIPTION"), "vehicles_per_day_behind": a.get("BACK_AADT"),
                     "vehicles_per_day_ahead": a.get("AHEAD_AADT"), "peak_hour_ahead": a.get("AHEAD_PEAK_HOUR"),
                     "miles_away": round(d, 2), "lat": round(g["y"], 6), "lon": round(g["x"], 6)})
    rows.sort(key=lambda r: r["miles_away"])
    return {"within_miles": miles, "stations": rows[:limit],
            "note": "state highways only; city streets need Menifee's own traffic counts"}


# ---------------------------------------------------------------- what a land-use plan starts from

def in_circle(layer, lon, lat, miles, fields, geometry=True, extra=None, timeout=40):
    """The features of a layer that a circle around the point touches."""
    params = {"geometry": json.dumps(circle(lon, lat, float(miles))), "geometryType": "esriGeometryPolygon", "inSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "outFields": fields, "returnGeometry": "true" if geometry else "false",
              "outSR": 4326, "geometryPrecision": 6, "f": "json"}
    params.update(extra or {})
    return get_json(f"{layer}/query", params, timeout=timeout).get("features") or []


def miles_between(lon1, lat1, lon2, lat2):
    return math.hypot((lon2 - lon1) * 69.17 * math.cos(math.radians(lat1)), (lat2 - lat1) * 69.17)


def day(ms):
    """An ArcGIS date (milliseconds since 1970) as "2026-10-28", or None."""
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(float(ms) / 1000))
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def records_updated():
    """When the city last changed its parcel records (the layer's own last-edit date)."""
    info = get_json(PARCELS, {"f": "json"})
    edit = info.get("editingInfo") or {}
    return {"parcels": day(edit.get("dataLastEditDate") or edit.get("lastEditDate")),
            "source": "City of Menifee parcels (public GIS)"}


def photo_date(lon, lat):
    """When the aerial photo at this spot was taken (the newest National Agriculture Imagery Program flight USGS holds)."""
    data = get_json(f"{NAIP}/query", {"where": "Category = 1", "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
                                      "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
                                      "outFields": "Year,acquisition_date,resolution_value,resolution_units",
                                      "returnGeometry": "false", "f": "json"})
    flights = [f["attributes"] for f in data.get("features") or [] if f["attributes"].get("acquisition_date")]
    if not flights:
        return None
    a = max(flights, key=lambda x: x["acquisition_date"])
    return {"taken": day(a["acquisition_date"]), "year": a.get("Year"), "detail_metres": a.get("resolution_value"),
            "source": "USDA National Agriculture Imagery Program, served by USGS"}


def parcels_in_box(west, south, east, north, limit=6000):
    """Every parcel that a map view touches, any size, with a thinned outline. `more` is True when the view holds
    more parcels than `limit` (zoom in to see them all)."""
    shapes, offset, more = [], 0, False
    box = {"xmin": west, "ymin": south, "xmax": east, "ymax": north, "spatialReference": {"wkid": 4326}}
    while True:
        data = get_json(f"{PARCELS}/query", {
            "geometry": json.dumps(box), "geometryType": "esriGeometryEnvelope", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": "APN,APNFormat,Acres,Zoning,Structures,ClassCode",
            "returnGeometry": "true", "outSR": 4326, "geometryPrecision": 5, "maxAllowableOffset": 0.00002,
            "orderByFields": "APN", "resultOffset": offset, "resultRecordCount": 2000, "f": "json"}, timeout=60)
        feats = data.get("features") or []
        for f in feats:
            a, rings = f["attributes"], (f.get("geometry") or {}).get("rings")
            if rings and a.get("APN"):
                shapes.append({"apn": a.get("APN"), "apn_formatted": a.get("APNFormat"), "acres": a.get("Acres"),
                               "zoning": tidy(a.get("Zoning")), "looks_vacant": not a.get("Structures"), "rings": rings})
        offset += len(feats)
        if not feats or not data.get("exceededTransferLimit"):
            break
        if offset >= limit:
            more = True
            break
    return {"parcels": shapes, "more": more}


STREET_RANK = {"expressway": 5, "urban arterial": 4, "arterial": 4, "mountain arterial": 4, "major": 3, "secondary": 2,
               "collector": 1}


def streets_near(lon, lat, miles=0.75):
    """The city's planned street network near the point (its general plan circulation map): each stretch with its
    street class and line. Unclassified local streets are left out."""
    rows = []
    for f in in_circle(STREETS, lon, lat, miles, "ST_NAME,Classification,mnfe_speeds"):
        a, paths = f["attributes"], (f.get("geometry") or {}).get("paths") or []
        cls = tidy(a.get("Classification"))
        if not paths or not cls or cls.lower() not in STREET_RANK:
            continue
        rows.append({"name": tidy(a.get("ST_NAME")).title() or "Unnamed street", "class": cls,
                     "rank": STREET_RANK[cls.lower()], "speed_mph": a.get("mnfe_speeds"), "paths": paths})
    return {"within_miles": miles, "streets": rows, "source": "City of Menifee general plan circulation map"}


def signals_near(lon, lat, miles=1.5):
    """Traffic signals that exist today near the point, nearest first."""
    rows = []
    for f in in_circle(SIGNALS, lon, lat, miles, "Name,STATUS,SignalType,StreetName,CrossStreet"):
        a, g = f["attributes"], f.get("geometry") or {}
        if g.get("x") is None or tidy(a.get("SignalType")).lower() != "traffic signal":
            continue
        rows.append({"street": tidy(a.get("StreetName")).title(), "cross_street": tidy(a.get("CrossStreet")).title(),
                     "status": tidy(a.get("STATUS")), "lat": round(g["y"], 6), "lon": round(g["x"], 6),
                     "miles_away": round(miles_between(lon, lat, g["x"], g["y"]), 2)})
    rows.sort(key=lambda r: r["miles_away"])
    return {"within_miles": miles, "signals": rows, "source": "City of Menifee traffic signals"}


def schools_near(lon, lat, miles=2.0):
    rows = []
    for f in in_circle(SCHOOLS, lon, lat, miles, "Name,GradeLevel,SchoolType"):
        a, g = f["attributes"], f.get("geometry") or {}
        if g.get("x") is None:
            continue
        rows.append({"name": tidy(a.get("Name")), "grades": tidy(a.get("GradeLevel")), "kind": tidy(a.get("SchoolType")),
                     "miles_away": round(miles_between(lon, lat, g["x"], g["y"]), 2)})
    rows.sort(key=lambda r: r["miles_away"])
    return {"within_miles": miles, "schools": rows[:8], "source": "City of Menifee schools"}


def _number(text):
    try:
        return float(str(text).replace(",", ""))
    except ValueError:
        return None


def read_project(text):
    """The sizes a project description states, read from its own words: acres, homes (lots or units), building
    square feet. Only what is written is returned; a description that does not say stays empty."""
    text = tidy(text)
    out = {}
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*-?\s*(?:net\s+|gross\s+)?acres?\b", text, re.I)
    if m:
        out["acres"] = _number(m.group(1))
    homes = [_number(n) for n in re.findall(
        r"([\d,]+)\s*(?:-\s*)?(?:new\s+)?(?:single[- ]family\s+)?(?:res(?:idential)?\.?\s+)?"
        r"(?:condomin\w+\s+|apartment\s+)?(?:lots|units?|homes)\b", text, re.I)]
    homes = [n for n in homes if n]
    if len(homes) == 1:  # several counts in one description (phases, planning areas) are not added up by guesswork
        out["homes"] = homes[0]
    # building floor space; a lot size ("7,200 sq ft min", "5,000 sq ft lots") is not a building
    feet = [_number(n) for n, after in re.findall(
        r"([\d,]{4,})\s*(?:sq\.?\s*\.?\s*ft\.?|sqft|sf\b|square f\w*)\s*(min|lots?)?", text, re.I) if not after]
    feet = [n for n in feet if n and n >= 2000]
    if feet:
        out["building_sq_ft"] = sum(feet)
    return out


def builder_of(a):
    """Who the city's list names for a project: its applicant, or a company name in brackets in the title."""
    name = tidy(a.get("Applicant")).strip("() ")
    if not name or name.lower() == "none":
        m = re.search(r"\(([^)]+)\)", tidy(a.get("ProjectTitle")))
        name = m.group(1).strip() if m else ""
        if re.search(r"\d|&|corner|formerly|aka", name, re.I):  # a place or an old name, not a company
            name = ""
    return name


def projects_near(lon, lat, miles=3.0):
    """Development projects on the city's own lists near the point: what is being built or asked for, by whom.
    Two city lists are read (land development projects, and the 2025 economic development projects)."""
    rows, seen = [], set()
    lists = ((PROJECTS, "ProjectNum,ProjectTitle,ProjectType,ProjectStatus,ProjectDesc,Applicant,Acres", "development projects"),
             (ECON_PROJECTS, "ProjectNum,ProjectTitle,ProjectType,ProjectStatus,ProjectDesc,size,location", "economic development projects, 2025"))
    for layer, fields, label in lists:
        for f in in_circle(layer, lon, lat, miles, fields, geometry=False, extra={"returnCentroid": "true"}):
            a, c = f["attributes"], f.get("centroid") or {}
            title = tidy(a.get("ProjectTitle"))
            if not title or title.lower() in seen or c.get("x") is None:
                continue
            seen.add(title.lower())
            text = tidy(a.get("ProjectDesc"))
            stated = read_project(text)
            if tidy(a.get("ProjectType")).lower().startswith("residential"):
                stated.pop("building_sq_ft", None)   # house sizes are not what a housing tract is measured by
            if a.get("Acres") and "acres" not in stated:
                stated["acres"] = a.get("Acres")
            status = tidy(a.get("ProjectStatus"))
            rows.append({"title": title, "number": tidy(a.get("ProjectNum")), "kind": tidy(a.get("ProjectType")),
                         "status": "" if status.lower() == "none" else status, "description": text,
                         "builder": builder_of(a), "stated": stated, "where": tidy(a.get("location")),
                         "list": label, "lat": round(c["y"], 6), "lon": round(c["x"], 6),
                         "miles_away": round(miles_between(lon, lat, c["x"], c["y"]), 2)})
    rows.sort(key=lambda r: r["miles_away"])
    updated = {}
    for layer, _, label in lists:
        try:
            edit = get_json(layer, {"f": "json"}).get("editingInfo") or {}
            updated[label] = day(edit.get("dataLastEditDate") or edit.get("lastEditDate"))
        except SourceError:
            updated[label] = None
    return {"within_miles": miles, "projects": rows, "lists_updated": updated, "source": "City of Menifee project lists"}


def people_near(lon, lat, rings=(1, 3, 5)):
    """People and homes counted in the 2020 Census within each distance of the point. A census block the circle
    only touches counts whole."""
    stats = json.dumps([{"statisticType": "sum", "onStatisticField": "POP100", "outStatisticFieldName": "people"},
                        {"statisticType": "sum", "onStatisticField": "HU100", "outStatisticFieldName": "homes"}])

    def one(miles):
        data = get_json(f"{BLOCKS}/query", {"geometry": json.dumps(circle(lon, lat, float(miles))),
                                            "geometryType": "esriGeometryPolygon", "inSR": 4326,
                                            "spatialRel": "esriSpatialRelIntersects", "outStatistics": stats, "f": "json"},
                        timeout=60)
        a = ((data.get("features") or [{}])[0].get("attributes") or {})
        if a.get("people") is None:
            raise SourceError("the Census block service gave no count")
        return {"miles": miles, "people": int(a["people"]), "homes": int(a.get("homes") or 0)}

    with ThreadPoolExecutor(max_workers=3) as pool:
        return {"rings": list(pool.map(one, rings)), "year": 2020, "source": "U.S. Census Bureau, 2020 Census blocks"}


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
