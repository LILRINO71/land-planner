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
    }
    not_covered = (
        "Population, income and spending around the site",
        "Traffic on city streets (only state highways are covered)",
        "Utilities, flood zones and protected habitat",
        "What the owner paid, and current market prices",
        "Which uses the zone allows outright, with a permit, or not at all",
        "Likely buyers, costs and returns",
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

    def large_parcels(self):
        return _ask(tool.large_parcels, self.large_acres)

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
        return None

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
