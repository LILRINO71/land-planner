"""Menifee, California. The city's own records are read by tools/menifee.py (the same code the command-line tool
runs) from the City of Menifee's public GIS. Everything a city shares with its neighbours (ground heights, highway
counts, the census, the regional forecasts, hazards) is answered by shared.RegionalCity."""
from .base import SourceError
from .shared import SHARED_SOURCES, RegionalCity, ask as _ask, tool  # noqa: F401 - `tool` is the app's one network module

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


class Menifee(RegionalCity):
    id = "menifee"
    name = "Menifee"
    region = "California"
    centre = {"lat": 33.69, "lon": -117.185}
    large_acres = 10.0
    site_miles = 1.0
    sources = {
        **SHARED_SOURCES,
        "parcel": CITY_GIS, "zoning": CITY_GIS, "general_plan": CITY_GIS, "surroundings": CITY_GIS,
        "neighbour_shapes": CITY_GIS, "zone_names": CITY_GIS,
        "streets": "City of Menifee general plan circulation map",
        "signals": "City of Menifee traffic signals", "projects": "City of Menifee project lists",
        "schools": "City of Menifee schools",
    }
    not_covered = (
        "The shops and offices that exist today (the Forecast shows what growth adds, not what is missing now)",
        "Traffic counts on city streets (only state highways are counted)",
        "Water, sewer and power capacity, and airport noise and height zones",
        "What the owner paid, and current market prices",
        "What each specific plan allows (the code adopts those plans by reference; their own documents are not read)",
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

    def parcel(self, apn):
        return _ask(tool.parcel, apn)

    @property
    def map_layers(self):
        from ..sources.place import MENIFEE_LAYERS   # the city's own hazard and nearby-place maps
        return MENIFEE_LAYERS

    def city_part(self, part, parcel):
        lon, lat = parcel["centre"]["lon"], parcel["centre"]["lat"]
        if part == "zoning":
            return _ask(tool.zoning_at, lon, lat)
        if part == "general_plan":
            return _ask(tool.general_plan_at, lon, lat)
        if part == "surroundings":
            return _ask(tool.neighbours, lon, lat, self.site_miles)
        if part == "neighbour_shapes":
            return _ask(tool.neighbour_shapes, lon, lat, self.site_miles)
        if part == "streets":
            return _ask(tool.streets_near, lon, lat, self._reach(parcel) + 0.35)
        if part == "signals":
            return _ask(tool.signals_near, lon, lat, self._reach(parcel) + 1.0)
        if part == "projects":
            return _ask(tool.projects_near, lon, lat)
        if part == "schools":
            return _ask(tool.schools_near, lon, lat)
        return None

    place = {"name": "Menifee", "fips": "46842", "county": "Riverside",
             "planning": "City of Menifee Community Development Department (Planning)",
             "water": "Eastern Municipal Water District (water and sewer) and Southern California Edison (power)"}

    _reach = staticmethod(RegionalCity.reach)

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

    def allowed_uses(self, code, plan_name="", layer_zone=""):
        """Read from the Development Code's tables kept in records/menifee_allowed_uses.json (see menifee_uses.py)."""
        from . import menifee_uses
        try:
            return menifee_uses.table().answer(code, plan_name, layer_zone)
        except (OSError, ValueError, KeyError) as e:
            raise SourceError(f"the recorded table of allowed uses could not be read: {e}") from e

    def zoning_notes(self, code):
        return ZONE_NOTES.get(str(code or "").strip(), [])
