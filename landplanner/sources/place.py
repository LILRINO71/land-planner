"""The place around a site: weather, hazards, what is close by and who lives nearby.

Four readers, each returning plain data that can be written as JSON:

    climate(lon, lat)     the weather there and how it has changed since 1985 (NASA POWER, no key)
    hazards(lon, lat)     flood, fire, faults, ground, wetlands, habitat and fire service (public map services)
    nearby(lon, lat)      the closest parks, fire stations, police, libraries, colleges, hospitals, bus stops
    residents(tracts)     the typical person in the census tracts around the site (Census survey, served by Esri)

Rules of the app: every number is read from a public source that needs no key, and a source that does not answer
is reported as not answering ("did_not_answer"), never filled in. All network access goes through fetch.get_json,
so the tests replace that one function. Requests are light: a few at a time, 30 second limits.
"""
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

from ..cities import SourceError
from . import fetch

WORKERS = 6                      # requests in flight at once, at most
TIMEOUT = 30
_PAUSE = 0.8                     # seconds to wait before asking a census service again (the tests set it to 0)

MILES_PER_DEGREE = 69.17
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

# ---- where each source lives ------------------------------------------------------------------------------------
POWER = "https://power.larc.nasa.gov/api/temporal"
NFHL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"
CGS = "https://gis.conservation.ca.gov/server/rest/services"
AP_TRACES = f"{CGS}/CGS_Earthquake_Hazard_Zones/SHP_Fault_Traces/MapServer/0"
Q_FAULTS = f"{CGS}/CGS/FAM_QFaults/MapServer/0"
LIQUEFACTION_ZONES = "https://services2.arcgis.com/zr3KAIbsRSUyARHG/ArcGIS/rest/services/CGS_Liquefaction_Zones/FeatureServer/0"
LANDSLIDE_ZONES = "https://services2.arcgis.com/zr3KAIbsRSUyARHG/ArcGIS/rest/services/CGS_Landslide_Zones/FeatureServer/0"
UNEVALUATED = "https://services.gis.ca.gov/arcgis/rest/services/GeoscientificInformation/Liquefaction/MapServer/4"
NWI = "https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0"
RCA = "https://gis.conserveriverside.com/arcgis/rest/services/PublicServices"
RCA_BOUNDARY = f"{RCA}/MSHCP_Boundary/MapServer/0"
RCA_AREA_PLAN = f"{RCA}/AreaPlan/MapServer/0"
RCA_CELLS = f"{RCA}/Criteria_Cells/FeatureServer/0"
RCA_SURVEY = f"{RCA}/SurveyArea/MapServer"
# survey area layers: id, a plain name for it, and the attribute that names the species when there is one
RCA_SURVEY_LAYERS = ((0, "Amphibians", "amphibian_name"), (1, "Burrowing owl", "species"), (2, "Mammals", "mammal_name"),
                     (5, "Delhi Sands flower-loving fly", None), (6, "Criteria area species", "species_name"),
                     (7, "Narrow endemic plants", "plant_name"))
USGS_STRUCTURES = "https://carto.nationalmap.gov/arcgis/rest/services/structures/MapServer/14"   # hospitals
HIFLD_HOSPITALS = "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/Hospitals_hifld/FeatureServer/0"
ACS = "https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services"

# The city's own layers. To add a city, give hazards() and nearby() another dict of this shape.
MENIFEE_LAYERS = {
    "name": "City of Menifee public GIS",
    "host": "https://services.arcgis.com/RjTKod25O4b8SbZx/arcgis/rest/services",
    "fire_map_year": 2025,                                   # the layer below is the city's 2025 fire hazard map
    "layers": {
        "fire_hazard": ("Fire_Hazard_Severity_Zone_Comparison", 4),
        "dam": ("Dam_Inundation", 0),
        "evacuation": ("Evacuation_Zones_2025", 23),
        "fossils": ("Paleontological_Sensitivity", 13),
        "fire_gaps": ("Existing_Fire_Coverage_Gaps_2024", 13),
        "fire_stations": ("Fire_Stations_Existing_and_Proposed", 0),
        "parks": ("Menifee_Parks", 3),
        "facilities": ("Public_Facilities_Point_Layer", 0),   # police stations and libraries
        "education": ("Public_Facilities__Points_", 0),       # colleges
        "transit": ("RTA_Routes_and_Stops", 1),               # Riverside Transit bus stops
    },
}

FAULT_SEARCH_MILES = 3.1          # 5 km
FAULT_ZONE_MILES = 0.1            # the state draws its earthquake fault zones about 500 feet each side of a fault
WETLAND_SEARCH_MILES = 0.5
HABITAT_CELL_MILES = 1.9          # 3 km
FIRE_STATION_SEARCH_MILES = 6.0


# ---- small helpers ----------------------------------------------------------------------------------------------
def _get(url, params=None, post=False, timeout=TIMEOUT):
    return fetch.get_json(url, params, timeout=timeout, post=post)


def _layer_url(city, key):
    service, layer = city["layers"][key]
    return f"{city['host']}/{service}/FeatureServer/{layer}"


def _quote(text):
    return "'" + str(text).replace("'", "''") + "'"


def _envelope(box):
    west, south, east, north = (float(v) for v in box)
    return f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}"


def _circle(lon, lat, miles, points=24):
    """A circle of `miles` around the point as a polygon (sent explicitly: services draw their own "distance" circle
    wrong now and then)."""
    dlat, dlon = miles / MILES_PER_DEGREE, miles / (MILES_PER_DEGREE * math.cos(math.radians(lat)))
    ring = [[round(lon + dlon * math.cos(2 * math.pi * i / points), 6), round(lat + dlat * math.sin(2 * math.pi * i / points), 6)]
            for i in range(points)]
    return {"rings": [ring + [ring[0]]], "spatialReference": {"wkid": 4326}}


def _query(layer, geometry, geometry_type, fields="*", where=None, geometry_out=False, thin=0.0):
    """One ArcGIS "query" with a point, box or circle. Returns the list of features."""
    params = {"geometry": geometry if isinstance(geometry, str) else json.dumps(geometry), "geometryType": geometry_type,
              "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": fields,
              "returnGeometry": "true" if geometry_out else "false", "f": "json"}
    if where:
        params["where"] = where
    if geometry_out:
        params.update({"outSR": 4326, "geometryPrecision": 6})
        if thin:
            params["maxAllowableOffset"] = thin
    return _get(f"{layer}/query", params).get("features") or []


def _at_point(layer, lon, lat, fields="*", **more):
    return _query(layer, {"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}, "esriGeometryPoint", fields, **more)


def _in_box(layer, box, fields="*", **more):
    return _query(layer, _envelope(box), "esriGeometryEnvelope", fields, **more)


def _in_circle(layer, lon, lat, miles, fields="*", **more):
    return _query(layer, _circle(lon, lat, float(miles)), "esriGeometryPolygon", fields, **more)


def _attrs(features):
    return [f.get("attributes") or {} for f in features]


def _first(features):
    rows = _attrs(features)
    return rows[0] if rows else None


def miles_between(lon1, lat1, lon2, lat2):
    return math.hypot((lon2 - lon1) * MILES_PER_DEGREE * math.cos(math.radians(lat1)), (lat2 - lat1) * MILES_PER_DEGREE)


def _flat(lon, lat):
    kx = MILES_PER_DEGREE * math.cos(math.radians(lat))
    return lambda p: ((p[0] - lon) * kx, (p[1] - lat) * MILES_PER_DEGREE)


def _segment_distance(a, b):
    """Distance from the origin to the segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    t = 0.0 if not length else max(0.0, min(1.0, -(a[0] * dx + a[1] * dy) / length))
    return math.hypot(a[0] + t * dx, a[1] + t * dy)


def _inside(ring, point=(0.0, 0.0)):
    x, y = point
    hit = False
    for i in range(len(ring) - 1):
        (x1, y1), (x2, y2) = ring[i], ring[i + 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def geometry_miles(geometry, lon, lat):
    """Miles from the point to an ArcGIS geometry (a point, a line or a polygon, in degrees); 0 inside a polygon."""
    if not geometry:
        return None
    flat = _flat(lon, lat)
    if "x" in geometry and "y" in geometry:
        return math.hypot(*flat((geometry["x"], geometry["y"])))
    best = None
    for part in geometry.get("paths") or []:
        pts = [flat(p) for p in part]
        for i in range(len(pts) - 1):
            d = _segment_distance(pts[i], pts[i + 1])
            best = d if best is None else min(best, d)
        if len(pts) == 1:
            d = math.hypot(*pts[0])
            best = d if best is None else min(best, d)
    rings = [[flat(p) for p in ring] for ring in geometry.get("rings") or [] if len(ring) >= 3]
    if rings:
        if any(_inside(r) for r in rings):
            # a polygon with holes is rare here; an exact answer is not needed to say "on the site"
            return 0.0
        for ring in rings:
            for i in range(len(ring) - 1):
                d = _segment_distance(ring[i], ring[i + 1])
                best = d if best is None else min(best, d)
    return best


def geometry_centre(geometry):
    """A representative (lon, lat) of a geometry: the point itself, or the middle of the biggest ring or line."""
    if not geometry:
        return None
    if "x" in geometry and "y" in geometry:
        return geometry["x"], geometry["y"]
    parts = geometry.get("rings") or geometry.get("paths") or []
    parts = [p for p in parts if p]
    if not parts:
        return None
    pts = max(parts, key=len)
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def _day(ms):
    """An ArcGIS date (milliseconds since 1970, or text) as "2014-08-18"."""
    if isinstance(ms, (int, float)):
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    if isinstance(ms, str) and re.match(r"\d{4}-\d{2}-\d{2}", ms):
        return ms[:10]
    return None


def _run_all(jobs, workers=WORKERS):
    """Run {name: callable} in a small pool. Returns {name: (value, None)} or {name: (None, SourceError)}."""
    def one(fn):
        try:
            return fn(), None
        except SourceError as e:
            return None, e
    names = list(jobs)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(names) or 1))) as pool:
        results = list(pool.map(lambda n: one(jobs[n]), names))
    return dict(zip(names, results))


def _f(c):
    return round(c * 9 / 5 + 32, 1)


# ===================================================================================================================
# Weather
# ===================================================================================================================
CLIMATE_NOTE = ("The weather grid is coarse: these figures come from a satellite and weather-model grid with cells many "
                "miles wide, so they describe the area, not this exact spot. Use them for how things change over the years, not for exact "
                "day counts. The high and low for a month are the hottest and coldest readings of that month, averaged "
                "over the years; the summer high is the average of the June, July and August highs.")
CLIMATE_SOURCE = "NASA POWER (Prediction Of Worldwide Energy Resources), weather and sunshine grids, public and free"


def _month_values(series, year):
    """The twelve monthly values of one year from a POWER monthly series, or None if any is missing."""
    out = []
    for m in range(1, 13):
        v = (series or {}).get(f"{year}{m:02d}")
        if v is None or v <= -900:
            return None
        out.append(float(v))
    return out


def _least_squares(points):
    """Slope of the straight line that fits the (x, y) points best, or None when it cannot be drawn."""
    n = len(points)
    if n < 2:
        return None
    mx, my = sum(p[0] for p in points) / n, sum(p[1] for p in points) / n
    den = sum((p[0] - mx) ** 2 for p in points)
    if not den:
        return None
    return sum((p[0] - mx) * (p[1] - my) for p in points) / den


def _trend(by_year):
    """The straight-line change per ten years through the yearly mean temperature and the yearly rain."""
    out = {"mean_f_per_decade": None, "rain_in_per_decade": None,
           "from_year": by_year[0]["year"] if by_year else None, "to_year": by_year[-1]["year"] if by_year else None}
    for key, name in (("mean_f", "mean_f_per_decade"), ("rain_in", "rain_in_per_decade")):
        slope = _least_squares([(r["year"], r[key]) for r in by_year if r.get(key) is not None])
        out[name] = None if slope is None else round(slope * 10, 2)
    return out


def _decades(years, first, last):
    """Ten-year groups from `first`; leftover years (fewer than five) join the last group."""
    groups, start = [], first
    while start <= last:
        groups.append([start, min(start + 9, last)])
        start += 10
    if len(groups) > 1 and groups[-1][1] - groups[-1][0] + 1 < 5:
        groups[-2][1] = groups[-1][1]
        groups.pop()
    return groups


def climate(lon, lat, first_year=1985, last_year=None):
    """The weather at a point: a typical year, the twelve months, ten-year groups, every year, and the trend."""
    last_year = int(last_year) if last_year else date.today().year - 1
    jobs = {
        "normals": lambda: _get(f"{POWER}/climatology/point", {
            "parameters": "T2M,PRECTOTCORR,WS10M,ALLSKY_SFC_SW_DWN", "community": "RE", "longitude": lon,
            "latitude": lat, "format": "JSON"}),
        "monthly": lambda: _get(f"{POWER}/monthly/point", {
            "parameters": "T2M,T2M_MAX,T2M_MIN,PRECTOTCORR", "community": "RE", "longitude": lon, "latitude": lat,
            "start": int(first_year), "end": last_year, "format": "JSON"}, timeout=TIMEOUT),
    }
    got = _run_all(jobs)
    missing = []
    normals = monthly = None
    for name, label in (("normals", "Typical year (NASA POWER normals)"), ("monthly", "Yearly weather history (NASA POWER)")):
        value, error = got[name]
        if error:
            missing.append(label)
        elif name == "normals":
            normals = ((value.get("properties") or {}).get("parameter")) or {}
        else:
            monthly = ((value.get("properties") or {}).get("parameter")) or {}
    if normals is None and monthly is None:
        raise SourceError("NASA POWER did not answer: " + "; ".join(str(got[n][1]) for n in got)[:300])

    months, by_year, by_decade, years_ok = [], [], [], []
    if monthly:
        temp, high, low, rain = (monthly.get(k) or {} for k in ("T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR"))
        for year in range(int(first_year), last_year + 1):
            t, r = _month_values(temp, year), _month_values(rain, year)
            if t is None or r is None:
                continue
            years_ok.append(year)
            by_year.append({"year": year, "mean_f": _f(sum(t) / 12),
                            "rain_in": round(sum(r[i] * DAYS[i] for i in range(12)) / 25.4, 2)})
        # the twelve months: the latest 25 years, the same stretch NASA uses for its own normals
        recent = years_ok[-25:]
        for m in range(12):
            def avg(series, scale=1.0):
                vals = [(_month_values(series, y) or [None] * 12)[m] for y in recent]
                vals = [v for v in vals if v is not None]
                return sum(vals) / len(vals) * scale if vals else None
            t_m, hi_m, lo_m, r_m = avg(temp), avg(high), avg(low), avg(rain, DAYS[m] / 25.4)
            months.append({"month": MONTHS[m], "mean_f": None if t_m is None else _f(t_m),
                           "high_f": None if hi_m is None else _f(hi_m), "low_f": None if lo_m is None else _f(lo_m),
                           "rain_in": None if r_m is None else round(r_m, 2)})
        for lo, hi in (_decades(years_ok, years_ok[0], years_ok[-1]) if years_ok else []):
            ys = [y for y in years_ok if lo <= y <= hi]
            summer = [sum((_month_values(high, y) or [0] * 12)[5:8]) / 3 for y in ys if _month_values(high, y)]
            rows = [r for r in by_year if lo <= r["year"] <= hi]
            by_decade.append({"years": f"{ys[0]}-{ys[-1]}", "mean_f": round(sum(r["mean_f"] for r in rows) / len(rows), 1),
                              "summer_high_f": _f(sum(summer) / len(summer)) if summer else None,
                              "rain_in": round(sum(r["rain_in"] for r in rows) / len(rows), 2)})

    typical = None
    if normals:
        ann = lambda key: ((normals.get(key) or {}).get("ANN"))
        t, r, w, s = ann("T2M"), ann("PRECTOTCORR"), ann("WS10M"), ann("ALLSKY_SFC_SW_DWN")
        good = lambda v: v is not None and v > -900
        typical = {"mean_f": _f(t) if good(t) else None, "rain_in": round(r * 365 / 25.4, 1) if good(r) else None,
                   "wind_mph": round(w * 2.23694, 1) if good(w) else None, "sun_kwh_m2_day": round(s, 2) if good(s) else None}
    elif by_year:
        recent = by_year[-25:]
        typical = {"mean_f": round(sum(r["mean_f"] for r in recent) / len(recent), 1),
                   "rain_in": round(sum(r["rain_in"] for r in recent) / len(recent), 1), "wind_mph": None, "sun_kwh_m2_day": None}

    return {"typical_year": typical, "months": months, "by_decade": by_decade, "by_year": by_year,
            "trend": _trend(by_year), "note": CLIMATE_NOTE, "source": CLIMATE_SOURCE, "did_not_answer": missing}


# ===================================================================================================================
# Hazards
# ===================================================================================================================
FLOOD_WORDS = {
    "minimal": "Minimal flood hazard: outside the area the flood map expects to flood in a 1-in-500-year flood.",
    "moderate": "Moderate flood hazard: inside the area expected to flood in a 1-in-500-year flood but outside the "
                "1-in-100-year flood area.",
    "high": "High flood hazard: inside the area expected to flood in a 1-in-100-year flood (a 1 percent chance each "
            "year). A lender usually requires flood insurance here.",
    "coastal": "High flood hazard from the coast, with waves: inside the 1-in-100-year flood area.",
    "undetermined": "Flood hazard not determined: the flood map has not studied this area.",
}
FIRE_LEVELS = ("Moderate", "High", "Very High")
# The codes the city's paleontological layer uses (read from the layer 2026-11-26: Ha, Hb, L, U and "sea"). The layer
# carries no wording of its own; the four classes are Riverside County's: low, undetermined, and two high ones.
PALEO = {"l": "Low", "u": "Undetermined", "ha": "High (class A)", "hb": "High (class B)"}
_PALEO_WORDS = {"low", "none", "moderate", "high", "undetermined", "high (class a)", "high (class b)"}


def paleo_words(code):
    """A fossil rating in plain words. A known code is translated; a rating already in words is kept; anything else
    is said to be unexplained, with its code, and is never shown bare as if it were a level."""
    raw = str(code if code is not None else "").strip()
    if not raw:
        return None
    if raw.lower() in PALEO:
        return PALEO[raw.lower()]
    if raw.lower() in _PALEO_WORDS:
        return raw[0].upper() + raw[1:]
    return f"not rated in words by the city (code {raw})"


def _flood_meaning(zone, subtype):
    zone, sub = (zone or "").upper(), (subtype or "").upper()
    if zone in ("A", "AE", "AH", "AO", "AR", "A99") or zone.startswith("A"):
        text = FLOOD_WORDS["high"]
        return text + (" This part is the floodway, the channel that carries the water." if "FLOODWAY" in sub else "")
    if zone in ("V", "VE") or zone.startswith("V"):
        return FLOOD_WORDS["coastal"]
    if zone == "D":
        return FLOOD_WORDS["undetermined"]
    if zone in ("X", "B", "C"):
        if "0.2" in sub or "SHADED" in sub or zone == "B":
            return FLOOD_WORDS["moderate"]
        return FLOOD_WORDS["minimal"]
    return "FEMA's flood zone for this spot is " + (zone or "not listed") + "."


def _flood_label(zone, subtype):
    word = {"AREA OF MINIMAL FLOOD HAZARD": "minimal hazard", "0.2 PCT ANNUAL CHANCE FLOOD HAZARD": "moderate hazard"}.get(
        (subtype or "").upper())
    if word is None and (zone or "").upper().startswith(("A", "V")):
        word = "high hazard"
    return f"{zone} ({word})" if word else str(zone)


def _flood(lon, lat, box, miss):
    rows = _attrs(_at_point(f"{NFHL}/28", lon, lat, "FLD_ZONE,ZONE_SUBTY,SFHA_TF"))
    here = rows[0] if rows else {}
    out = {"zone": here.get("FLD_ZONE"), "meaning": _flood_meaning(here.get("FLD_ZONE"), here.get("ZONE_SUBTY")) if here
           else "FEMA has not published a flood map for this spot.",
           "special_hazard_area": here.get("SFHA_TF") == "T", "panel": None, "effective": None, "zones_on_site": None,
           "source": "FEMA National Flood Hazard Layer"}
    try:
        panel = _first(_at_point(f"{NFHL}/3", lon, lat, "FIRM_PAN,EFF_DATE"))
        if panel:
            out["panel"], out["effective"] = panel.get("FIRM_PAN"), _day(panel.get("EFF_DATE"))
    except SourceError:
        miss("Flood map panel number and date (FEMA)")
    if box:
        try:
            seen = _attrs(_in_box(f"{NFHL}/28", box, "FLD_ZONE,ZONE_SUBTY"))
            out["zones_on_site"] = sorted({_flood_label(r.get("FLD_ZONE"), r.get("ZONE_SUBTY")) for r in seen if r.get("FLD_ZONE")})
        except SourceError:
            miss("Flood zones across the whole site (FEMA)")
    elif here.get("FLD_ZONE"):
        out["zones_on_site"] = [_flood_label(here.get("FLD_ZONE"), here.get("ZONE_SUBTY"))]
    return out


def _level_order(name):
    return FIRE_LEVELS.index(name) if name in FIRE_LEVELS else len(FIRE_LEVELS)


def _level_name(text):
    """The city layer's own wording, with its one run-together label spelled out."""
    return "Non-wildland" if _clean(text).lower() == "nonwildland" else _clean(text)


def _fire(city, lon, lat, box, miss):
    layer = _layer_url(city, "fire_hazard")
    here = _first(_at_point(layer, lon, lat, "FHSZ,FHSZ_Description,SRA"))
    if here:
        level = _level_name(here.get("FHSZ_Description"))
        who = {"LRA": "The city (local responsibility area)", "SRA": "The state, CAL FIRE (state responsibility area)",
               "FRA": "The federal government (federal responsibility area)"}.get(here.get("SRA"), here.get("SRA"))
    else:
        level, who = "not in a mapped fire hazard zone", None
    levels = None
    if box:
        try:
            seen = _attrs(_in_box(layer, box, "FHSZ,FHSZ_Description"))
            levels = sorted({_level_name(r["FHSZ_Description"]) for r in seen if r.get("FHSZ_Description")}, key=_level_order)
        except SourceError:
            miss("Fire hazard levels across the whole site (city map)")
    elif here:
        levels = [level]
    return {"level": level, "levels_on_site": levels, "map_year": city.get("fire_map_year"), "responsibility": who,
            "source": city["name"] + " (its 2025 copy of the state fire hazard map)"}


def _faults(lon, lat):
    ap = _in_circle(AP_TRACES, lon, lat, FAULT_SEARCH_MILES, "FAULT_NAME", geometry_out=True, thin=0.0005)
    qf = _in_circle(Q_FAULTS, lon, lat, FAULT_SEARCH_MILES, "FLT_NAME", geometry_out=True, thin=0.0005)
    near_ap = [(geometry_miles(f.get("geometry"), lon, lat), (f.get("attributes") or {}).get("FAULT_NAME")) for f in ap]
    near_q = [(geometry_miles(f.get("geometry"), lon, lat), (f.get("attributes") or {}).get("FLT_NAME")) for f in qf]
    near_ap = [r for r in near_ap if r[0] is not None]
    near_q = [r for r in near_q if r[0] is not None]
    every = sorted(near_ap + near_q, key=lambda r: r[0])
    return {"in_fault_zone": any(d <= FAULT_ZONE_MILES for d, _ in near_ap),
            "nearest_miles": round(every[0][0], 2) if every else None,
            "nearest_name": every[0][1] if every else None, "searched_miles": FAULT_SEARCH_MILES,
            "source": "California Geological Survey (earthquake fault zone traces and the Fault Activity Map)"}


def _ground(lon, lat):
    liq = _at_point(LIQUEFACTION_ZONES, lon, lat, "*")
    slide = _at_point(LANDSLIDE_ZONES, lon, lat, "*")
    blank = _at_point(UNEVALUATED, lon, lat, "OBJECTID")
    state = lambda zone: "in a mapped zone" if zone else ("not mapped by the state here" if blank else "not in a zone")
    return {"liquefaction": state(liq), "landslide": state(slide),
            "source": "California Geological Survey seismic hazard zones (the state's \"unevaluated areas\" are places "
                      "it has not mapped)"}


def _wetland_row(a):
    acres = a.get("ACRES")
    return {"type": a.get("WETLAND_TYPE"), "code": a.get("ATTRIBUTE"), "acres": None if acres is None else round(acres, 2)}


def _wetlands(lon, lat, box):
    fields = "ATTRIBUTE,WETLAND_TYPE,ACRES"
    on = _in_box(NWI, box, fields) if box else _at_point(NWI, lon, lat, fields)
    near = _in_circle(NWI, lon, lat, WETLAND_SEARCH_MILES, fields, geometry_out=True, thin=0.0003)
    on_rows = [_wetland_row(a) for a in _attrs(on)]
    on_keys = {(r["code"], r["acres"]) for r in on_rows}
    others = []
    for f in near:
        row = _wetland_row(f.get("attributes") or {})
        d = geometry_miles(f.get("geometry"), lon, lat)
        if d is not None and (row["code"], row["acres"]) not in on_keys:
            others.append((d, row))
    others.sort(key=lambda r: r[0])
    nearest = None
    if others:
        d, row = others[0]
        nearest = {"type": row["type"], "acres": row["acres"], "miles_away": round(d, 2)}
    return {"on_site": [{"type": r["type"], "acres": r["acres"]} for r in on_rows], "nearest": nearest,
            "searched_miles": WETLAND_SEARCH_MILES, "source": "U.S. Fish and Wildlife Service, National Wetlands Inventory"}


def _habitat(lon, lat, miss):
    boundary = _at_point(RCA_BOUNDARY, lon, lat, "boundary_name")
    plan = _first(_at_point(RCA_AREA_PLAN, lon, lat, "name"))
    in_cell = _at_point(RCA_CELLS, lon, lat, "cell_label")
    near = _in_circle(RCA_CELLS, lon, lat, HABITAT_CELL_MILES, "cell_label,areaplan")
    cells = sorted({(a.get("cell_label") or "").strip() for a in _attrs(near) if a.get("cell_label")})

    def survey(entry):
        layer, label, field = entry
        try:
            rows = _attrs(_at_point(f"{RCA_SURVEY}/{layer}", lon, lat, field or "objectid"))
        except SourceError:
            return entry, None
        return entry, [str(r.get(field)).strip() if field and r.get(field) else label for r in rows]
    names, failed = [], 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        for entry, found in pool.map(survey, RCA_SURVEY_LAYERS):
            if found is None:
                failed += 1
            else:
                names.extend(found)
    if failed:
        miss(f"Habitat survey areas ({failed} of {len(RCA_SURVEY_LAYERS)} map layers)")
    return {"in_plan": bool(boundary), "area_plan": plan.get("name") if plan else None, "in_criteria_cell": bool(in_cell),
            "cells_near": cells, "survey_areas": sorted(set(names)) if not failed or names else None,
            "source": "Western Riverside County Regional Conservation Authority (habitat plan maps)"}


def _evacuation(city, lon, lat):
    row = _first(_at_point(_layer_url(city, "evacuation"), lon, lat, "zone_id,known_as"))
    if not row:
        return None
    if row.get("known_as"):
        return row["known_as"]
    parts = str(row.get("zone_id") or "").split("-")
    return "-".join(parts[-2:]) if len(parts) >= 4 else row.get("zone_id")


def _fossils(city, lon, lat):
    row = _first(_at_point(_layer_url(city, "fossils"), lon, lat, "Paleo"))
    if not row:
        return None
    return paleo_words(row.get("Paleo"))


def _dam(city, lon, lat, box):
    layer = _layer_url(city, "dam")
    return bool(_in_box(layer, box, "DAMNAME") if box else _at_point(layer, lon, lat, "DAMNAME"))


def _stations(city, lon, lat, miles=FIRE_STATION_SEARCH_MILES):
    """Fire stations the city's map knows within `miles`: [(miles, name, status, geometry)], nearest first. Status is
    "existing" or "proposed"."""
    out = []
    for f in _in_circle(_layer_url(city, "fire_stations"), lon, lat, miles, "Name,Label,Status", geometry_out=True):
        a = f.get("attributes") or {}
        name = _clean(a.get("Name") or a.get("Label"))
        d = geometry_miles(f.get("geometry"), lon, lat)
        if name and d is not None:
            out.append((d, name, _clean(a.get("Status")).lower(), f.get("geometry")))
    return sorted(out, key=lambda r: r[0])


def _fire_service(city, lon, lat):
    gap = _at_point(_layer_url(city, "fire_gaps"), lon, lat, "OBJECTID")
    stations = _stations(city, lon, lat)

    def pick(status):
        for d, name, st, _geometry in stations:
            if st == status:
                return {"name": name, "miles_away": round(d, 2)}
        return None
    return {"in_coverage_gap": bool(gap), "nearest_station": pick("existing"), "planned_station": pick("proposed"),
            "source": city["name"] + " (its 2024 map of places a fire engine cannot reach in 4 minutes)"}


HAZARD_BLOCKS = (
    ("flood", "Flood zones (FEMA)"), ("fire", "Fire hazard zones (city map)"),
    ("faults", "Earthquake faults (California Geological Survey)"),
    ("ground", "Liquefaction and landslide zones (California Geological Survey)"),
    ("wetlands", "Wetlands (U.S. Fish and Wildlife Service)"),
    ("habitat", "Western Riverside County habitat plan (Conservation Authority)"),
    ("dam_flooding", "Dam flooding area (city map)"), ("evacuation_zone", "Evacuation zone (city map)"),
    ("fossils", "Fossil sensitivity (city map)"), ("fire_service", "Fire service coverage (city map)"),
)


def hazards(lon, lat, box=None, city_layers=None):
    """What the public hazard maps say about the point (and the whole site, when `box` is given as
    west, south, east, north). Each block is asked for on its own: one that does not answer is None and named
    in "did_not_answer"."""
    city = city_layers or MENIFEE_LAYERS
    box = tuple(box) if box else None
    extra = []                                           # partial misses inside a block that otherwise answered
    jobs = {
        "flood": lambda: _flood(lon, lat, box, extra.append),
        "fire": lambda: _fire(city, lon, lat, box, extra.append),
        "faults": lambda: _faults(lon, lat),
        "ground": lambda: _ground(lon, lat),
        "wetlands": lambda: _wetlands(lon, lat, box),
        "habitat": lambda: _habitat(lon, lat, extra.append),
        "dam_flooding": lambda: _dam(city, lon, lat, box),
        "evacuation_zone": lambda: _evacuation(city, lon, lat),
        "fossils": lambda: _fossils(city, lon, lat),
        "fire_service": lambda: _fire_service(city, lon, lat),
    }
    got = _run_all(jobs)
    out, missing, errors = {}, [], []
    for key, label in HAZARD_BLOCKS:
        value, error = got[key]
        out[key] = value
        if error:
            missing.append(label)
            errors.append(str(error))
    if len(missing) == len(HAZARD_BLOCKS):
        raise SourceError("none of the hazard maps answered: " + "; ".join(errors)[:300])
    out["did_not_answer"] = missing + sorted(set(extra))
    return out


# ===================================================================================================================
# Close by
# ===================================================================================================================
KINDS = ("park", "fire station", "police", "library", "college", "hospital", "transit stop")
KEEP_PER_KIND = 5
NOT_COVERED = ["Grocery and big stores (no public list)"]


def _place(kind, name, miles, geometry, detail, source):
    centre = geometry_centre(geometry)
    return {"kind": kind, "name": name, "miles_away": round(miles, 2), "lat": round(centre[1], 5) if centre else None,
            "lon": round(centre[0], 5) if centre else None, "detail": detail, "source": source}


def _clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _near_parks(city, lon, lat, miles):
    out = []
    for f in _in_circle(_layer_url(city, "parks"), lon, lat, miles, "Name,Authority,Acreage", geometry_out=True, thin=0.0002):
        a = f.get("attributes") or {}
        d = geometry_miles(f.get("geometry"), lon, lat)
        if a.get("Name") and d is not None:
            bits = ([f"{a['Acreage']:g} acres"] if a.get("Acreage") else []) + ([a["Authority"]] if a.get("Authority") else [])
            out.append(_place("park", _clean(a["Name"]), d, f.get("geometry"), ", ".join(bits) or None, city["name"]))
    return _dedupe(out, key=lambda p: p["name"].lower())


def _near_fire_stations(city, lon, lat, miles):
    """Existing stations, nearest first. The city's layer lists some stations several times; rows with the same
    number and nearly the same spot (within 0.1 mile) count once."""
    kept = []
    for d, name, status, g in _stations(city, lon, lat, miles):
        if status != "existing":
            continue
        number = re.sub(r"\D", "", name)
        if any(re.sub(r"\D", "", k["name"]) == number and miles_between(k["lon"], k["lat"], *geometry_centre(g)) <= 0.1 for k in kept):
            continue
        kept.append(_place("fire station", name, d, g, None, city["name"]))
    return kept


def _dedupe(places, key):
    """The same place often has several rows; keep the nearest of each (by `key`)."""
    best = {}
    for p in sorted(places, key=lambda p: p["miles_away"]):
        best.setdefault(key(p), p)
    return list(best.values())


def _near_facilities(city, lon, lat, miles):
    kinds = {"police station": "police", "library": "library"}
    where = "Facility_Type IN ('Police Station','Library')"
    out = []
    for f in _in_circle(_layer_url(city, "facilities"), lon, lat, miles, "Name,Facility_Type", where=where, geometry_out=True):
        a = f.get("attributes") or {}
        kind = kinds.get(_clean(a.get("Facility_Type")).lower())
        d = geometry_miles(f.get("geometry"), lon, lat)
        if kind and a.get("Name") and d is not None:
            out.append(_place(kind, _clean(a["Name"]), d, f.get("geometry"), None, city["name"]))
    return _dedupe(out, key=lambda p: (p["kind"], p["name"].lower()))


def _near_colleges(city, lon, lat, miles):
    out = []
    where = "TYPE = 'Education'"
    for f in _in_circle(_layer_url(city, "education"), lon, lat, miles, "NAME,TYPE,ADDRESS", where=where, geometry_out=True):
        a = f.get("attributes") or {}
        name, d = _clean(a.get("NAME")), geometry_miles(f.get("geometry"), lon, lat)
        if name and d is not None and re.search(r"\b(college|university)\b", name, re.I):
            out.append(_place("college", name, d, f.get("geometry"), _clean(a.get("ADDRESS")) or None, city["name"]))
    return _dedupe(out, key=lambda p: p["name"].lower())


def _near_stops(city, lon, lat, miles):
    out = []
    for f in _in_circle(_layer_url(city, "transit"), lon, lat, miles, "stop_id,stop_name,stop_desc", geometry_out=True):
        a = f.get("attributes") or {}
        d = geometry_miles(f.get("geometry"), lon, lat)
        if a.get("stop_name") and d is not None:
            out.append(_place("transit stop", _clean(a["stop_name"]), d, f.get("geometry"), _clean(a.get("stop_desc")) or None,
                              "Riverside Transit Agency, served by " + city["name"]))
    return _dedupe(out, key=lambda p: p["name"].lower())      # a stop is often listed once for each side of the street


def _near_hospitals_usgs(lon, lat, miles):
    out = []
    for f in _in_circle(USGS_STRUCTURES, lon, lat, miles, "name,address,city", geometry_out=True):
        a = f.get("attributes") or {}
        d = geometry_miles(f.get("geometry"), lon, lat)
        if a.get("name") and d is not None:
            where = ", ".join(x for x in (_clean(a.get("address")), _clean(a.get("city"))) if x)
            out.append(_place("hospital", _clean(a["name"]), d, f.get("geometry"), where or None,
                              "U.S. Geological Survey, National Map structures"))
    return out


def _hospital_beds(lon, lat, miles):
    """Hospitals on the federal list: [(lon, lat, name, beds)]."""
    out = []
    for f in _in_circle(HIFLD_HOSPITALS, lon, lat, miles, "NAME,STATUS,BEDS", geometry_out=True):
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        if "x" in g and (a.get("STATUS") or "OPEN").upper() == "OPEN":
            beds = a.get("BEDS")
            out.append((g["x"], g["y"], _clean(a.get("NAME")).title(), beds if isinstance(beds, int) and beds > 0 else None))
    return out


def _merge_hospitals(listed, beds, lon, lat):
    """Add bed counts to the National Map's hospitals where the federal list has the same building (within 0.25
    mile); a federal-list hospital with no match is added as its own place."""
    used = set()
    for p in listed:
        for i, (x, y, name, count) in enumerate(beds):
            if i not in used and p["lon"] is not None and miles_between(p["lon"], p["lat"], x, y) <= 0.25:
                used.add(i)
                if count:
                    p["detail"] = (p["detail"] + "; " if p["detail"] else "") + f"{count} beds"
                    p["source"] += "; beds from the federal hospital list (HIFLD)"
                break
    for i, (x, y, name, count) in enumerate(beds):
        if i not in used:
            listed.append(_place("hospital", name, miles_between(lon, lat, x, y), {"x": x, "y": y},
                                 f"{count} beds" if count else None, "Federal hospital list (HIFLD)"))
    return listed


def nearby(lon, lat, miles=5.0, city_layers=None):
    """The closest of each kind of place within `miles`: at most five of each, nearest first overall."""
    city = city_layers or MENIFEE_LAYERS
    jobs = {
        "parks": lambda: _near_parks(city, lon, lat, miles),
        "fire stations": lambda: _near_fire_stations(city, lon, lat, miles),
        "police stations and libraries": lambda: _near_facilities(city, lon, lat, miles),
        "colleges": lambda: _near_colleges(city, lon, lat, miles),
        "hospitals": lambda: _near_hospitals_usgs(lon, lat, miles),
        "hospital beds": lambda: _hospital_beds(lon, lat, miles),
        "bus stops": lambda: _near_stops(city, lon, lat, miles),
    }
    got = _run_all(jobs)
    labels = {"parks": "Parks (city map)", "fire stations": "Fire stations (city map)",
              "police stations and libraries": "Police stations and libraries (city map)",
              "colleges": "Colleges (city map)", "hospitals": "Hospitals (U.S. Geological Survey)",
              "hospital beds": "Hospital beds (federal hospital list)", "bus stops": "Bus stops (Riverside Transit)"}
    missing = [labels[k] for k, (_, e) in got.items() if e]
    if len(missing) == len(jobs):
        raise SourceError("nothing close by could be looked up: " + "; ".join(str(e) for _, e in got.values())[:300])
    places = []
    for key in ("parks", "fire stations", "police stations and libraries", "colleges", "bus stops"):
        places += got[key][0] or []
    hospitals, beds = got["hospitals"][0], got["hospital beds"][0]
    if hospitals is not None:
        places += _merge_hospitals(hospitals, beds or [], lon, lat)
    elif beds:                                           # only the federal list answered
        places += _merge_hospitals([], beds, lon, lat)
    kept = []
    for kind in KINDS:
        group = sorted((p for p in places if p["kind"] == kind and p["miles_away"] <= miles), key=lambda p: p["miles_away"])
        kept += group[:KEEP_PER_KIND]
    kept.sort(key=lambda p: p["miles_away"])
    nearest = {}
    for p in kept:
        nearest.setdefault(p["kind"], p)
    return {"places": kept, "nearest": nearest, "not_covered": list(NOT_COVERED), "did_not_answer": missing}


# ===================================================================================================================
# The typical resident
# ===================================================================================================================
# (what to call it in the answer, plain name for "did_not_answer", service, fields to read, how to combine them)
RESIDENT_SERVICES = (
    ("Median age", "ACS_Median_Age_Boundaries", {"median_age": ("B01002_001E",)}),
    ("Household size", "ACS_Household_Size_Boundaries", {"household_size": ("B25010_001E",)}),
    ("Home value and rent", "ACS_Housing_Occupancy_and_Tenure_Unit_Value_Boundaries",
     {"home_value_usd": ("B25077_001E",), "rent_usd": ("B25058_001E",)}),
    ("Education", "ACS_Educational_Attainment_Boundaries", {"bachelors_pct": ("B15002_calc_pctGEBAE",)}),
    ("How people get to work", "ACS_Means_of_Transportation_to_Work_Boundaries",
     {"drive_alone_pct": ("B08301_calc_pctDroveAloneE",), "work_from_home_pct": ("B08301_calc_pctHomeE",)}),
    ("Time spent getting to work", "ACS_Travel_Time_to_Work_Boundaries",
     {"long_commute_pct": ("B08303_calc_pct60to89E", "B08303_calc_pctGE90E")}),
    ("Language at home", "ACS_Language_by_Age_Boundaries", {"spanish_at_home_pct": ("B16007_calc_pctSpanE",)}),
    ("Age groups", "ACS_Total_Population_Boundaries",
     {"under_18_pct": ("B01001_calc_pctLT18E",), "over_65_pct": ("B01001_calc_pctGE65E",)}),
)
EARLIER = ("ACS_10_14_Housing_Occupancy_and_Tenure_Unit_Value_Boundaries", {"home_value_usd": ("B25077_001E",), "rent_usd": ("B25058_001E",)})
EARLIER_YEARS = "2010-2014"
VINTAGE_TABLE = f"{ACS}/ACS_Vintage_Table/FeatureServer/0"
VINTAGE_IDS = ("MAGE", "HHSZ", "EDAT", "COMM")           # median age, household size, education, travel time
ROUND = {"median_age": 1, "household_size": 2, "home_value_usd": 0, "rent_usd": 0}   # everything else: one decimal
RESIDENT_SOURCE = "U.S. Census Bureau, American Community Survey 5-year estimates (served by Esri)"


def _patient(fn, tries=3):
    """Ask again when a census service refuses a good question, which it now and then does."""
    for attempt in range(tries):
        try:
            return fn()
        except SourceError:
            if attempt == tries - 1:
                raise
            time.sleep(_PAUSE * (attempt + 1))


def _ask_tracts(service, ids, fields):
    where = "GEOID IN (" + ",".join(_quote(i) for i in ids) + ")"
    answer = _patient(lambda: _get(f"{ACS}/{service}/FeatureServer/2/query", {
        "where": where, "outFields": "GEOID," + ",".join(fields), "returnGeometry": "false", "f": "json"}, post=True, timeout=40))
    return {a["GEOID"]: a for a in _attrs(answer.get("features") or []) if a.get("GEOID")}


def _combine(row, fields):
    vals = [row.get(f) for f in fields]
    return None if any(v is None for v in vals) else sum(vals)


def _round(key, value):
    if value is None:
        return None
    digits = ROUND.get(key, 1)
    return int(round(value)) if digits == 0 else round(float(value), digits)


def _weighted(rows, key, weights):
    """The average of key over the tracts that have it, weighted by households times share."""
    pairs = [(r[key], weights[i]) for i, r in enumerate(rows) if r.get(key) is not None]
    total = sum(w for _, w in pairs)
    if not pairs:
        return None
    if total <= 0:
        return sum(v for v, _ in pairs) / len(pairs)         # no usable weights at all: a plain average
    return sum(v * w for v, w in pairs) / total


def residents(tracts):
    """The typical person living around a site, from the census tracts that surround it. `tracts` is a list of
    {"id": GEOID, "households": n, "share": 0..1}; each tract counts as much as its households times its share."""
    tracts = [t for t in (tracts or []) if t.get("id")]
    if not tracts:
        raise SourceError("no census tracts were given")
    ids = [str(t["id"]) for t in tracts]
    weights = [max(0.0, float(t.get("households") or 0)) * max(0.0, float(t.get("share") if t.get("share") is not None else 1)) for t in tracts]
    jobs = {name: (lambda s=service, f=fields: _ask_tracts(s, ids, [c for cols in f.values() for c in cols]))
            for name, service, fields in RESIDENT_SERVICES}
    jobs["earlier"] = lambda: _ask_tracts(EARLIER[0], ids, [c for cols in EARLIER[1].values() for c in cols])
    jobs["vintage"] = lambda: _get(f"{VINTAGE_TABLE}/query", {
        "where": "featureLayerID IN (" + ",".join(_quote(i) for i in VINTAGE_IDS) + ")", "outFields": "featureLayerID,Vintage",
        "returnGeometry": "false", "f": "json"}, timeout=40)
    got = _run_all(jobs)
    answered = [n for n, (_, e) in got.items() if e is None]
    if not [n for n in answered if n not in ("earlier", "vintage")]:
        raise SourceError("the census survey did not answer: " + "; ".join(str(e) for _, e in got.values() if e)[:300])

    rows = [{"id": i, "households": t.get("households"), "share": t.get("share")} for i, t in zip(ids, tracts)]
    missing = []
    for name, _service, fields in RESIDENT_SERVICES:
        value, error = got[name]
        if error:
            missing.append(f"{name} (Census survey)")
            continue
        for row in rows:
            attrs = value.get(row["id"]) or {}
            for key, cols in fields.items():
                row[key] = _combine(attrs, cols)
    typical = {key: _round(key, _weighted(rows, key, weights)) for _, _, fields in RESIDENT_SERVICES for key in fields}
    for row in rows:
        for key in typical:
            row[key] = _round(key, row.get(key))

    earlier = {"years": EARLIER_YEARS, "home_value_usd": None, "rent_usd": None, "tracts_matched": 0}
    value, error = got["earlier"]
    if error:
        missing.append(f"Home value and rent, {EARLIER_YEARS} (Census survey)")
    else:
        old = [{key: _combine(value.get(i) or {}, cols) for key, cols in EARLIER[1].items()} for i in ids]
        for key in EARLIER[1]:
            earlier[key] = _round(key, _weighted(old, key, weights))
        earlier["tracts_matched"] = sum(1 for i in ids if i in value)

    survey = None
    value, error = got["vintage"]
    if error:
        missing.append("Survey years (Census survey)")
    else:
        years = sorted({str(a.get("Vintage")) for a in _attrs(value.get("features") or []) if a.get("Vintage")})
        survey = ", ".join(years) if years else None
    return {"typical": typical, "earlier": earlier, "tracts": rows, "survey": survey, "source": RESIDENT_SOURCE,
            "did_not_answer": missing}
