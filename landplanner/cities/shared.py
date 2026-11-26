"""What every city in this region shares, so that a city's own file only has to read that city's own records.

A city in Southern California stands on the same national, state and regional sources as its neighbours:

    ground heights          U.S. Geological Survey (3D Elevation Program)
    highway traffic         Caltrans counts on state highways
    people and homes        U.S. Census Bureau (2010 and 2020 Census blocks, and the yearly survey by census tract)
    growth forecasts        Southern California Association of Governments (SCAG)
    aerial photo dates      USDA aerial photo programme, served by USGS
    the city's economy      state and national open data (landplanner/sources/economy.py and housing.py)
    hazards, places nearby  state and national maps (landplanner/sources/place.py)

`RegionalCity` answers all of those. A city's adapter subclasses it and adds only what comes from that city's own
records, in `city_part()`: the zoning and the general plan at a spot, what surrounds a parcel, the neighbours'
outlines, and, where the city publishes them, its streets, signals, project lists and schools.

The functions that read the shared sources live in tools/menifee.py (the app's one JSON network function is
there, so the offline tests replace a single function). Their names say nothing about one city.
"""
import importlib.util
from pathlib import Path

from .base import CityAdapter, NotFound, SourceError

_TOOL = Path(__file__).resolve().parents[2] / "tools" / "menifee.py"
_spec = importlib.util.spec_from_file_location("menifee_tool", _TOOL)
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

SHARED_SOURCES = {
    "terrain": "U.S. Geological Survey (3D Elevation Program)",
    "surface": "U.S. Geological Survey (3D Elevation Program)",
    "state_highway_traffic": "Caltrans traffic counts",
    "people": "U.S. Census Bureau, 2020 Census",
    "people_before": "U.S. Census Bureau, 2010 Census",
    "regional_plan": "Southern California Association of Governments (SCAG) growth forecasts",
    "tracts": "U.S. Census Bureau, American Community Survey (served by Esri)",
    "photo": "USDA aerial photo programme (NAIP), served by USGS",
}
# The zoning families the Plan's rules of thumb know (landplanner/plan.py). A city's `zoning_kind()` answers with
# one of these ids, and its `zoning_kinds` lists the ones it uses with a label and a colour of its own.
ZONING_FAMILIES = ("mixed", "edc", "commercial", "business", "denser-housing", "low-density", "rural", "specific-plan",
                   "open-space", "public", "other")


def ask(fn, *args):
    """Run one of the shared tool's functions, turning its errors into the app's."""
    try:
        return fn(*args)
    except tool.NotFound as e:
        raise NotFound(str(e)) from e
    except tool.SourceError as e:
        raise SourceError(str(e)) from e


class RegionalCity(CityAdapter):
    """A city whose nation-wide, state-wide and region-wide facts are answered here. Fill in `place` (with the
    city's name, its census place number "fips" and its county) and `city_part()`."""

    # the city's own hazard and nearby-place maps, in the shape landplanner/sources/place.py reads; None means the
    # city publishes none, and the pages then say which city maps are missing
    map_layers = None

    def city_part(self, part, parcel):
        """One of SITE_PARTS that comes from the city's own records, or None when the city does not publish it."""
        return None

    def site_part(self, part, parcel):
        lon, lat = parcel["centre"]["lon"], parcel["centre"]["lat"]
        rings = parcel["outline"]["coordinates"]
        if part == "state_highway_traffic":
            return ask(tool.traffic, lon, lat)
        if part == "terrain":
            return ask(tool.terrain, rings, parcel["centre"])
        if part == "surface":
            return ask(tool.surface, rings)
        if part == "people":
            return ask(tool.people_near, lon, lat)
        if part == "people_before":
            return ask(tool.people_before, lon, lat)
        if part == "regional_plan":
            return ask(tool.regional_plan, lon, lat)
        if part == "tracts":
            return ask(tool.tracts_near, lon, lat)
        return self.city_part(part, parcel)

    def photo_date(self, lon, lat):
        return ask(tool.photo_date, lon, lat)

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
        layers = self.map_layers or S.no_city_layers(self.name)
        if part == "climate":
            return S.climate(lon, lat)
        if part == "hazards":
            pts = [pt for ring in (parcel.get("outline") or {}).get("coordinates") or [] for pt in ring]
            box = (min(x for x, _ in pts), min(y for _, y in pts), max(x for x, _ in pts), max(y for _, y in pts)) if pts else None
            return S.hazards(lon, lat, box, city_layers=layers)
        if part == "nearby":
            return S.nearby(lon, lat, city_layers=layers)
        if part == "residents":
            if not tracts:
                # the census tracts did not answer: that is a source not answering, not an empty answer to keep
                raise SourceError("the census tracts did not answer, so the residents nearby cannot be described")
            return S.residents(tracts)
        return None

    @staticmethod
    def reach(parcel):
        """Miles from the parcel's centre to its far corner, so "near" is measured from the edge of big parcels."""
        size = parcel.get("size_feet") or {}
        return round(0.5 * (size.get("east_west", 0) ** 2 + size.get("north_south", 0) ** 2) ** 0.5 / 5280, 2)
