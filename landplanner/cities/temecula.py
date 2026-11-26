"""Temecula, California: the second city, and the pattern for a third. One file.

Everything here is read from the City of Temecula's own open-data map service (gis.temeculaca.gov, "OpenData"),
which needs no account or key: parcels, zoning, specific plans, the general plan, streets and schools. What a city
shares with its neighbours (ground heights, highway counts, the census, the regional forecasts, hazards, the
city's economy) comes from shared.RegionalCity and is not repeated here.

How Temecula's records differ from Menifee's, and what this file does about it:
  - A parcel record carries no zoning. The zone is the one the city's zoning map has at the parcel's centre point
    (for a list of parcels, the zoning map is read once and each centre is looked up in it).
  - The parcel layer reaches past the city limits. A parcel whose centre is outside the city boundary is left out
    of the list of lands; it can still be opened by its number, and then shows no city zoning.
  - The parcel layer also holds each owner's name and mailing address. They are never asked for: FIELDS below
    names every column that is read.
  - The city publishes no project lists, no traffic signals, no fire hazard map of its own and no date for its
    last change to the parcel records. Those parts answer None and the pages say "not covered".
  - The city's table of allowed uses has not been read (only Menifee's has), so allowed_uses() is not filled in
    and every page that would use it says so. Nothing is borrowed from Menifee.
"""
import json

from .base import NotFound
from .shared import SHARED_SOURCES, RegionalCity, ask, tool

OPEN_DATA = "https://gis.temeculaca.gov/arcgis/rest/services/OpenData/FeatureServer"
BOUNDARY, PARCELS, PLANS, ZONING = f"{OPEN_DATA}/0", f"{OPEN_DATA}/2", f"{OPEN_DATA}/3", f"{OPEN_DATA}/5"
GENERAL_PLAN, STREETS, SCHOOLS = f"{OPEN_DATA}/6", f"{OPEN_DATA}/8", f"{OPEN_DATA}/11"
CITY_GIS = "City of Temecula open data (public GIS)"
# the only parcel columns ever asked for (the layer's owner and mailing-address columns are left alone)
FIELDS = "APN,ACREAGE,LAND,STRUCTURES,CLASS_CODE,SITUS_STREET,SITUS_CITY,SUBDIVISION_NAME"
# The city's street classes (its general plan roadway types), ranked the way the Plan ranks Menifee's: 4 for the
# widest arterials down to 1 for collectors. Local and private streets are left out.
STREET_RANK = {"urban arterial": 4, "principal arterial": 4, "major arterial": 3, "secondary arterial": 2,
               "modified secondary arterial": 2, "limited secondary arterial": 2, "rural highway": 2, "collector": 1}
SCHOOL_KINDS = {"E": "Elementary school", "M": "Middle school", "H": "High school"}   # the layer's other letters are not explained
# zoning code -> the family the Plan's rules of thumb know (shared.ZONING_FAMILIES)
FAMILIES = {"BP": "business", "LI": "business", "CC": "commercial", "HT": "commercial", "NC": "commercial",
            "SC": "commercial", "PO": "commercial", "H": "denser-housing", "M": "denser-housing",
            "LM": "low-density", "L-1": "low-density", "L-2": "low-density", "VL": "rural", "HR-SM": "rural",
            "OS": "open-space", "OS-C": "open-space", "OS-C-SM": "open-space", "PR": "open-space", "PI": "public"}


def formatted(apn):
    apn = str(apn or "")
    return f"{apn[:3]}-{apn[3:6]}-{apn[6:]}" if len(apn) == 9 and apn.isdigit() else apn


def title(text):
    """The city writes its names in capitals: "COMMUNITY COMM (CC)" -> "Community Comm"."""
    text = tool.tidy(text)
    cut = text.rfind("(")
    if cut > 0 and text.endswith(")"):
        text = text[:cut].strip()
    return text.title()


def parcel_row(a):
    """One parcel's facts as the city records them. What the record does not hold stays empty (None)."""
    land, built = a.get("LAND"), a.get("STRUCTURES")
    cls = tool.tidy(a.get("CLASS_CODE"))
    return {"apn": a.get("APN"), "apn_formatted": formatted(a.get("APN")), "acres": a.get("ACREAGE"),
            "zoning": "", "general_plan": None, "assessor_class": cls,
            "looks_vacant": bool(not built and (not cls or "vacant" in cls.lower())),
            "address": tool.tidy(" ".join(x for x in (a.get("SITUS_STREET"), a.get("SITUS_CITY")) if x)),
            "subdivision": tool.tidy(a.get("SUBDIVISION_NAME")), "assessed_land_usd": land, "assessed_structures_usd": built,
            "fire_hazard_zone": None, "council_district": None}


def box_of(rings):
    xs, ys = [p[0] for r in rings for p in r], [p[1] for r in rings for p in r]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


class Shapes:
    """A set of outlines with something attached to each, to ask "which one is this point in?"."""

    def __init__(self, features, value):
        self.items = []
        for f in features or []:
            rings = (f.get("geometry") or {}).get("rings") or []
            box = box_of(rings)
            if box:
                self.items.append((box, rings, value(f.get("attributes") or {})))

    def at(self, lon, lat):
        for (west, south, east, north), rings, value in self.items:
            if west <= lon <= east and south <= lat <= north and tool.inside(rings, lon, lat):
                return value
        return None


def zone_code(a):
    return tool.tidy(a.get("ZONING"))


class Temecula(RegionalCity):
    id = "temecula"
    name = "Temecula"
    region = "California"
    centre = {"lat": 33.503, "lon": -117.124}
    large_acres = 10.0
    site_miles = 1.0
    sources = {**SHARED_SOURCES, "parcel": CITY_GIS, "zoning": CITY_GIS, "general_plan": CITY_GIS, "surroundings": CITY_GIS,
               "neighbour_shapes": CITY_GIS, "zone_names": CITY_GIS, "streets": "City of Temecula streets (open data)",
               "schools": "City of Temecula schools (open data)"}
    not_covered = (
        "Which uses each zone allows outright, with a permit, or not at all (Temecula's code has not been read; "
        "nothing is borrowed from another city's)",
        "Projects being built or asked for nearby, and traffic signals (the city publishes neither as open data)",
        "The fire hazard zone and council district on each parcel record, and the city's own hazard maps",
        "When the city last changed its parcel records (its service does not say)",
        "Parcels outside the city limits (they are in the city's layer but left out of the list)",
        "The shops and offices that exist today, traffic counts on city streets, water, sewer and power capacity",
        "Real quotes for costs and prices (the Plan page starts from editable figures)",
    )
    not_published = ("signals", "projects")
    links = {}
    zoning_kinds = (
        ("denser-housing", "Medium and high density housing", "#c9852b"),
        ("low-density", "Low density housing", "#f4d35e"),
        ("rural", "Very low density and hillside housing", "#c8d98a"),
        ("open-space", "Open space and parks", "#3f9d68"),
        ("commercial", "Commercial and office", "#d9455f"),
        ("business", "Business park and light industrial", "#8a6bbd"),
        ("public", "Public institutional", "#6f8fa8"),
        ("specific-plan", "Specific plan or planned development", "#4aa3c7"),
        ("other", "Other or none listed", "#9aa0a6"),
    )
    place = {"name": "Temecula", "fips": "78120", "county": "Riverside",
             "planning": "City of Temecula Community Development Department (Planning)",
             "water": "the water and sewer district that serves the parcel (ask the city which) and Southern California Edison (power)"}

    # ---- reading the city's layers

    def _zones(self, where_shape=None):
        """The zoning map as outlines to look points up in: all of it, or the part a shape touches."""
        params = {"where": "1=1", "outFields": "ZONING", "returnGeometry": "true", "outSR": 4326,
                  "geometryPrecision": 5, "maxAllowableOffset": 0.00003, "f": "json"}
        params.update(where_shape or {})
        data = ask(tool.get_json, f"{ZONING}/query", params, 60)
        return Shapes(data.get("features"), zone_code)

    def _city_limits(self):
        data = ask(tool.get_json, f"{BOUNDARY}/query", {"where": "1=1", "outFields": "City_Name", "returnGeometry": "true",
                                                         "outSR": 4326, "geometryPrecision": 5, "f": "json"}, 60)
        return Shapes(data.get("features"), lambda a: True)

    @staticmethod
    def _touching(shape):
        kind = "esriGeometryEnvelope" if "xmin" in shape else "esriGeometryPolygon"
        return {"geometry": json.dumps(shape), "geometryType": kind, "inSR": 4326, "spatialRel": "esriSpatialRelIntersects"}

    def _parcels(self, where, shape=None, fields=FIELDS, outlines=True, thin=0.00005, limit=6000):
        """Parcel features with their centre points, page by page: (features, True when there were more than `limit`)."""
        found, offset = [], 0
        while True:
            params = {"where": where, "outFields": fields, "returnGeometry": "true" if outlines else "false",
                      "returnCentroid": "true", "outSR": 4326, "geometryPrecision": 5, "maxAllowableOffset": thin,
                      "orderByFields": "ACREAGE DESC, APN", "resultOffset": offset, "resultRecordCount": 1000, "f": "json"}
            params.update(self._touching(shape) if shape else {})
            data = ask(tool.get_json, f"{PARCELS}/query", params, 60)
            feats = data.get("features") or []
            found += feats
            offset += len(feats)
            if not feats or not data.get("exceededTransferLimit"):
                return found, False
            if offset >= limit:
                return found, True

    @staticmethod
    def _centre(f):
        rings = (f.get("geometry") or {}).get("rings") or []
        c = f.get("centroid") or (tool.ring_centre(rings) if rings else None)
        return c and (c["x"], c["y"])

    # ---- what the app asks for

    def large_parcels(self, min_acres=None):
        floor = self.large_acres if min_acres is None else float(min_acres)
        feats, _ = self._parcels(f"ACREAGE >= {floor}")
        zones, limits = self._zones(), self._city_limits()
        rows = []
        for f in feats:
            centre = self._centre(f)
            if not centre or not f["attributes"].get("APN") or not limits.at(*centre):
                continue                                   # outside the city limits (or a record with no shape)
            row = parcel_row(f["attributes"])
            row.update(zoning=zones.at(*centre) or "", centre={"lat": round(centre[1], 6), "lon": round(centre[0], 6)},
                       rings=(f.get("geometry") or {}).get("rings") or [])
            rows.append(row)
        return rows

    def parcels_in_box(self, west, south, east, north):
        box = {"xmin": west, "ymin": south, "xmax": east, "ymax": north, "spatialReference": {"wkid": 4326}}
        feats, more = self._parcels("1=1", box, "APN,ACREAGE,STRUCTURES,CLASS_CODE", thin=0.00002)
        zones = self._zones(self._touching(box))
        shapes = []
        for f in feats:
            a, rings, centre = f["attributes"], (f.get("geometry") or {}).get("rings"), self._centre(f)
            if rings and a.get("APN") and centre:
                row = parcel_row(a)
                shapes.append({"apn": a["APN"], "apn_formatted": row["apn_formatted"], "acres": a.get("ACREAGE"),
                               "zoning": zones.at(*centre) or "", "looks_vacant": row["looks_vacant"], "rings": rings})
        return {"parcels": shapes, "more": more}

    def parcel(self, apn):
        apn = ask(tool.clean_apn, apn)
        data = ask(tool.get_json, f"{PARCELS}/query", {
            "where": f"APN = {tool.quote(apn)}", "outFields": FIELDS, "returnGeometry": "true", "returnCentroid": "true",
            "outSR": 4326, "geometryPrecision": 6, "f": "json"})
        feats = data.get("features") or []
        if not feats:
            raise tool_not_found(apn)
        f = feats[0]
        rings = (f.get("geometry") or {}).get("rings") or []
        lon, lat = self._centre(f) or (None, None)
        if lon is None:
            raise tool_not_found(apn)
        out = parcel_row(f["attributes"])
        zone = ask(tool.at_point, ZONING, lon, lat, "ZONING") or {}
        plan = ask(tool.at_point, GENERAL_PLAN, lon, lat, "GPLU") or {}
        out.update(zoning=zone_code(zone), general_plan=plan.get("GPLU"), source=CITY_GIS,
                   centre={"lat": lat, "lon": lon}, outline={"type": "Polygon", "coordinates": rings},
                   size_feet=tool.bounding_feet(rings))
        return out

    def _specific_plan(self, lon, lat):
        a = ask(tool.at_point, PLANS, lon, lat, "SP_ID,SP_NAME,SP_STATUS") or {}
        return tool.tidy(a.get("SP_NAME")), tool.tidy(a.get("SP_ID"))

    def _around(self, lon, lat, outlines):
        """The parcels a circle around the point touches, each with the zone at its own centre."""
        circle = tool.circle(lon, lat, float(self.site_miles))
        feats, _ = self._parcels("1=1", circle, "APN,ACREAGE", outlines=outlines, thin=0.00003, limit=8000)
        zones = self._zones(self._touching(circle))
        for f in feats:
            centre = self._centre(f)
            if centre and f["attributes"].get("APN"):
                yield f, zones.at(*centre) or "(none)"

    def city_part(self, part, parcel):
        lon, lat = parcel["centre"]["lon"], parcel["centre"]["lat"]
        if part == "zoning":
            a = ask(tool.at_point, ZONING, lon, lat, "ZONING,ZONEDESC,TYPE")
            if not a or not zone_code(a):
                return None
            code, words = zone_code(a), title(a.get("ZONEDESC"))
            if code.upper().startswith("SP"):
                name, _ = self._specific_plan(lon, lat)
                words = f"{name} Specific Plan ({code})" if name else f"{words} ({code})"
            return {"zone": code, "abbrev": code, "what_it_allows": words, "general_plan_says": None}
        if part == "general_plan":
            a = ask(tool.at_point, GENERAL_PLAN, lon, lat, "GPLU,GPDESCRIPT,Type,LIMITS")
            if not a:
                return None
            name, _ = self._specific_plan(lon, lat)
            return {"land_use": a.get("GPLU"), "label": tool.tidy(a.get("GPDESCRIPT")), "specific_plan": name,
                    "description": tool.tidy(a.get("GPDESCRIPT"))}
        if part == "surroundings":
            sums = {}
            for f, zone in self._around(lon, lat, outlines=False):
                row = sums.setdefault(zone, {"zoning": zone, "acres": 0.0, "parcels": 0})
                row["acres"] += f["attributes"].get("ACREAGE") or 0.0
                row["parcels"] += 1
            rows = sorted(sums.values(), key=lambda r: -r["acres"])
            total = sum(r["acres"] for r in rows) or 1.0
            for r in rows:
                r.update(acres=round(r["acres"], 1), share_pct=round(100 * r["acres"] / total, 1))
            return {"within_miles": self.site_miles, "total_acres": round(total, 1), "by_zoning": rows[:15]}
        if part == "neighbour_shapes":
            return [{"apn": f["attributes"]["APN"], "zoning": zone, "acres": f["attributes"].get("ACREAGE"),
                     "rings": f["geometry"]["rings"]}
                    for f, zone in self._around(lon, lat, outlines=True) if (f.get("geometry") or {}).get("rings")]
        if part == "streets":
            miles, rows = self.reach(parcel) + 0.35, []
            for f in ask(tool.in_circle, STREETS, lon, lat, miles, "STNAME,CLASS,SPEEDLIMIT"):
                a, paths = f["attributes"], (f.get("geometry") or {}).get("paths") or []
                cls = tool.tidy(a.get("CLASS")).lower()
                if not paths or cls not in STREET_RANK:
                    continue
                speed = tool.tidy(a.get("SPEEDLIMIT"))
                rows.append({"name": tool.tidy(a.get("STNAME")).title() or "Unnamed street", "class": cls.title(),
                             "rank": STREET_RANK[cls], "speed_mph": int(speed) if speed.isdigit() else None, "paths": paths})
            return {"within_miles": miles, "streets": rows, "source": "City of Temecula streets (open data)"}
        if part == "schools":
            miles, rows = 2.0, []
            for f in ask(tool.in_circle, SCHOOLS, lon, lat, miles, "NAME,LABEL,TYPE"):
                a, rings = f["attributes"], (f.get("geometry") or {}).get("rings") or []
                if not rings:
                    continue
                c = tool.ring_centre(rings)
                rows.append({"name": tool.tidy(a.get("LABEL")) or tool.tidy(a.get("NAME")).title(), "grades": "",
                             "kind": SCHOOL_KINDS.get(tool.tidy(a.get("TYPE")).upper(), ""),
                             "miles_away": round(tool.miles_between(lon, lat, c["x"], c["y"]), 2)})
            rows.sort(key=lambda r: r["miles_away"])
            return {"within_miles": miles, "schools": rows[:8], "source": "City of Temecula schools (open data)"}
        return None          # signals and projects: the city publishes neither

    def zone_names(self):
        data = ask(tool.get_json, f"{ZONING}/query", {"where": "1=1", "outFields": "ZONING,ZONEDESC",
                                                       "returnDistinctValues": "true", "returnGeometry": "false", "f": "json"})
        names = {}
        for f in data.get("features") or []:
            code, words = zone_code(f["attributes"]), title(f["attributes"].get("ZONEDESC"))
            if code and words and code not in names:
                names[code] = words
        plans = ask(tool.get_json, f"{PLANS}/query", {"where": "1=1", "outFields": "SP_ID,SP_NAME", "returnGeometry": "false", "f": "json"})
        for f in plans.get("features") or []:
            code, name = tool.tidy(f["attributes"].get("SP_ID")), tool.tidy(f["attributes"].get("SP_NAME"))
            if code in names and name:      # the plans layer also names two of the planned development overlays
                names[code] = f"{name} Specific Plan" if code.upper().startswith("SP") else f"{name} ({names[code]})"
        return names

    def zoning_kind(self, code):
        code = str(code or "").strip().upper()
        if not code or code == "(NONE)":
            return "other"
        if "&" in code:
            return "mixed"
        if code.startswith(("SP-", "PDO-")):
            return "specific-plan"
        return FAMILIES.get(code, "other")


def tool_not_found(apn):
    return NotFound(f"no Temecula parcel has the number {apn}")
