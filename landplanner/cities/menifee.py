"""Menifee, California. Everything is read by tools/menifee.py (the same code the command-line tool runs), from
the City of Menifee's public GIS, the U.S. Geological Survey and Caltrans. This file only fits it to the app."""
import importlib.util
from pathlib import Path

from .base import CityAdapter, NotFound, SourceError

_TOOL = Path(__file__).resolve().parents[2] / "tools" / "menifee.py"
_spec = importlib.util.spec_from_file_location("menifee_tool", _TOOL)
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

CITY_GIS = "City of Menifee public GIS"

# The city's own wording for one zone, with where it was read. Only quotes that were actually read go here.
ZONE_NOTES = {
    "EDC-CC": [{
        "title": "What the city has in mind for the Community Core",
        "quote": "The Community Core is envisioned as the City’s primary activity center and gathering place. Civic "
                 "and entertainment uses are envisioned here that are complemented with commercial retail uses and "
                 "higher density housing options that encourage walkability and reduce the use of the automobile.",
        "source_name": "City development code wording, read from a third-party copy; confirm against the city’s own",
        "source_url": "https://www.zoneomics.com/code/menifee-CA/chapter_4",
        "plain": "The city pictures this area as a kind of downtown: public and entertainment places, shops and "
                 "closer-packed homes that people can walk between.",
    }],
}


def _ask(fn, *args):
    """Run one of the tool's functions, turning its errors into the app's."""
    try:
        return fn(*args)
    except tool.NotFound as e:
        raise NotFound(str(e)) from e
    except tool.SourceError as e:
        raise SourceError(str(e)) from e


class Menifee(CityAdapter):
    id = "menifee"
    name = "Menifee"
    region = "California"
    centre = {"lat": 33.69, "lon": -117.185}
    large_acres = 10.0
    site_miles = 1.0
    sources = {
        "parcel": CITY_GIS, "zoning": CITY_GIS, "general_plan": CITY_GIS, "surroundings": CITY_GIS,
        "neighbour_shapes": CITY_GIS, "zone_names": CITY_GIS,
        "terrain": "U.S. Geological Survey (3D Elevation Program)",
        "surface": "U.S. Geological Survey (3D Elevation Program)",
        "state_highway_traffic": "Caltrans traffic counts",
        "people": "U.S. Census Bureau, 2020 Census", "streets": "City of Menifee general plan circulation map",
        "signals": "City of Menifee traffic signals", "projects": "City of Menifee project lists",
        "schools": "City of Menifee schools", "photo": "USDA aerial photo programme (NAIP), served by USGS",
        "people_before": "U.S. Census Bureau, 2010 Census",
        "regional_plan": "Southern California Association of Governments (SCAG) growth forecasts",
        "tracts": "U.S. Census Bureau, American Community Survey (served by Esri)",
    }
    not_covered = (
        "The shops and offices that exist today (the Forecast shows what growth adds, not what is missing now)",
        "Traffic counts on city streets (only state highways are counted)",
        "Water, sewer and power capacity, and airport noise and height zones",
        "What the owner paid, and current market prices",
        "Which uses the zone allows outright, with a permit, or not at all",
        "Real quotes for costs and prices (the Plan page starts from editable figures)",
    )
    links = {"development_code": "https://online.encodeplus.com/regs/menifee-ca/doc-viewer.aspx?secid=1320"}
    zoning_kinds = (
        ("mixed", "More than one zone", "#b59a7a"),
        ("edc", "Economic Development Corridor", "#e0662f"),
        ("denser-housing", "Denser housing", "#c9852b"),
        ("low-density", "Low density housing", "#f4d35e"),
        ("rural", "Rural residential", "#c8d98a"),
        ("open-space", "Open space", "#3f9d68"),
        ("commercial", "Commercial", "#d9455f"),
        ("business", "Business park and industrial", "#8a6bbd"),
        ("public", "Public facilities and utilities", "#6f8fa8"),
        ("specific-plan", "Specific plan or planned development", "#4aa3c7"),
        ("other", "Other or none listed", "#9aa0a6"),
    )
    _PREFIXES = (("EDC", "edc"), ("HDR", "denser-housing"), ("MDR", "denser-housing"), ("LMDR", "denser-housing"),
                 ("LDR", "low-density"), ("RR", "rural"), ("RM", "rural"), ("OS", "open-space"), ("CR", "commercial"),
                 ("CO", "commercial"), ("BP", "business"), ("HI", "business"), ("PF", "public"), ("PUC", "public"),
                 ("PDO", "specific-plan"), ("SPECIFIC", "specific-plan"))

    def large_parcels(self, min_acres=None):
        return _ask(tool.large_parcels, self.large_acres if min_acres is None else float(min_acres))

    def parcels_in_box(self, west, south, east, north):
        return _ask(tool.parcels_in_box, west, south, east, north)

    def records_updated(self):
        return _ask(tool.records_updated)

    def photo_date(self, lon, lat):
        return _ask(tool.photo_date, lon, lat)

    def parcel(self, apn):
        return _ask(tool.parcel, apn)

    def site_part(self, part, parcel):
        lon, lat = parcel["centre"]["lon"], parcel["centre"]["lat"]
        rings = parcel["outline"]["coordinates"]
        if part == "zoning":
            return _ask(tool.zoning_at, lon, lat)
        if part == "general_plan":
            return _ask(tool.general_plan_at, lon, lat)
        if part == "surroundings":
            return _ask(tool.neighbours, lon, lat, self.site_miles)
        if part == "neighbour_shapes":
            return _ask(tool.neighbour_shapes, lon, lat, self.site_miles)
        if part == "state_highway_traffic":
            return _ask(tool.traffic, lon, lat)
        if part == "terrain":
            return _ask(tool.terrain, rings, parcel["centre"])
        if part == "surface":
            return _ask(tool.surface, rings)
        if part == "people":
            return _ask(tool.people_near, lon, lat)
        if part == "streets":
            return _ask(tool.streets_near, lon, lat, self._reach(parcel) + 0.35)
        if part == "signals":
            return _ask(tool.signals_near, lon, lat, self._reach(parcel) + 1.0)
        if part == "projects":
            return _ask(tool.projects_near, lon, lat)
        if part == "schools":
            return _ask(tool.schools_near, lon, lat)
        if part == "people_before":
            return _ask(tool.people_before, lon, lat)
        if part == "regional_plan":
            return _ask(tool.regional_plan, lon, lat)
        if part == "tracts":
            return _ask(tool.tracts_near, lon, lat)
        return None

    place = {"name": "Menifee", "fips": "46842", "county": "Riverside",
             "planning": "City of Menifee Community Development Department (Planning)",
             "water": "Eastern Municipal Water District (water and sewer) and Southern California Edison (power)"}

    def economy_part(self, part, year):
        from ..sources import economy as E
        p = self.place
        if part == "population":
            return E.population_by_year(p["name"], year, p["county"])
        if part == "permits":
            return E.permits_by_year(p["fips"], year - 8, year - 1)
        if part == "sales":
            return E.shop_sales_by_year(p["name"])
        if part == "work":
            return E.work_by_year(p["name"], p["county"])
        if part == "borrowing":
            return E.mortgage_rates()
        if part == "prices":
            return E.prices_by_year(year - 9)
        if part == "housing":
            from ..sources import housing as H
            return H.housing_target(p["name"], p["county"])
        return None

    def outlook_part(self, part, parcel, tracts=None):
        from ..sources import place as S
        lon, lat = parcel["centre"]["lon"], parcel["centre"]["lat"]
        if part == "climate":
            return S.climate(lon, lat)
        if part == "hazards":
            pts = [pt for ring in (parcel.get("outline") or {}).get("coordinates") or [] for pt in ring]
            box = (min(x for x, _ in pts), min(y for _, y in pts), max(x for x, _ in pts), max(y for _, y in pts)) if pts else None
            return S.hazards(lon, lat, box)
        if part == "nearby":
            return S.nearby(lon, lat)
        if part == "residents":
            if not tracts:
                # the census tracts did not answer: that is a source not answering, not an empty answer to keep
                raise SourceError("the census tracts did not answer, so the residents nearby cannot be described")
            return S.residents(tracts)
        return None

    @staticmethod
    def _reach(parcel):
        """Miles from the parcel's centre to its far corner, so "near" is measured from the edge of big parcels."""
        size = parcel.get("size_feet") or {}
        return round(0.5 * (size.get("east_west", 0) ** 2 + size.get("north_south", 0) ** 2) ** 0.5 / 5280, 2)

    def zone_names(self):
        names = _ask(tool.zone_names)
        # the parcel records say "Specific Plan" where the zoning layer names the plan itself
        names.setdefault("Specific Plan", "Area with its own city-approved specific plan")
        return names

    def zoning_kind(self, code):
        code = str(code or "").strip().upper()
        if not code or code == "(NONE)":
            return "other"
        if "&" in code:
            return "mixed"
        if code.endswith(" SP"):
            return "specific-plan"
        for prefix, kind in self._PREFIXES:
            if code.startswith(prefix):
                return kind
        return "other"

    def zoning_notes(self, code):
        return ZONE_NOTES.get(str(code or "").strip(), [])
