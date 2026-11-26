"""What a city has to provide. To add a city, write one file in this folder with a class that fills this in,
and list it in cities/__init__.py. The rest of the app (server, pages, cache, My lands) needs no change.

A city in Southern California should subclass shared.RegionalCity rather than CityAdapter: it already answers
everything cities share (ground heights, highway counts, the census, the regional forecasts, hazards, the city's
economy), so the city's own file only reads the city's own records. temecula.py is the example to copy, and the
README lists the steps ("How to add a city").

A city adapter answers three questions from that city's public records:

    large_parcels()            every parcel of `large_acres` or more
    parcel(apn)                one parcel, with its outline
    site_part(part, parcel)    one group of facts about a parcel's site (the names are in SITE_PARTS)

Rules for every adapter:
  - Real public records only. A value the source does not give is None; never a guess, never a zero.
  - When a source does not answer, raise SourceError. When the source answers and there is no such parcel,
    raise NotFound. The app turns both into plain messages.
  - No caching here: the app caches every answer itself (landplanner/cache.py).
"""


class SourceError(Exception):
    """A public source did not answer usefully. The message is for the log, not for the screen."""


class NotFound(SourceError):
    """The source answered: there is no such parcel in this city."""


# One parcel row, as large_parcels() and parcel() return it. Any value may be None when the city has none.
PARCEL_FIELDS = {
    "apn": "parcel number, digits only (the key used everywhere)",
    "apn_formatted": "the parcel number as people write it, e.g. 372-100-001",
    "acres": "size in acres",
    "zoning": "the city's zoning code, e.g. EDC-CC",
    "general_plan": "the city's general plan land use code",
    "assessor_class": "the county assessor's description of the property",
    "looks_vacant": "True when the assessor lists no buildings (a hint, not a site visit)",
    "address": "street address, or empty",
    "subdivision": "recorded map name, or empty",
    "assessed_land_usd": "assessed land value for property tax",
    "assessed_structures_usd": "assessed value of buildings for property tax",
    "fire_hazard_zone": "state fire hazard zone, or 'none listed'",
    "council_district": "city council district number",
    "centre": "{'lat': .., 'lon': ..}",
    # large_parcels() adds "rings": a thinned outline, [[[lon, lat], ...], ...]
    # parcel() adds "outline": {"type": "Polygon", "coordinates": rings} and
    #               "size_feet": {"east_west": .., "north_south": ..}
}

# The groups of site facts. `quick` ones are asked for as soon as a land is opened; the `ground` ones come from
# slower elevation services and are loaded after the page is already on screen.
SITE_PARTS = {
    "zoning": "quick",                  # {"zone", "abbrev", "what_it_allows", "general_plan_says"}
    "general_plan": "quick",            # {"land_use", "label", "specific_plan", "description"}
    "surroundings": "quick",            # {"within_miles", "total_acres", "by_zoning": [{"zoning", "acres", "parcels", "share_pct"}]}
    "neighbour_shapes": "quick",        # [{"apn", "zoning", "acres", "rings"}] for the map
    "state_highway_traffic": "quick",   # {"within_miles", "stations": [{"route", "where", "vehicles_per_day_behind",
                                        #   "vehicles_per_day_ahead", "peak_hour_ahead", "miles_away", "lat", "lon"}], "note"}
    "terrain": "ground",                # {"feet_above_sea_level": {"centre", "north", "south", "east", "west"},
                                        #   "fall_across_site_ft", "rough_slope_pct", "reading"}
    "surface": "ground",                # {"west", "east", "south", "north", "nx", "ny", "spacing_ft", "feet": [...],
                                        #   "source", "inside": {"low_ft", "high_ft", "range_ft", "typical_slope_pct", ...}}
    # What a land-use plan starts from; asked for when the Plan page is opened.
    "people": "market",                 # {"rings": [{"miles", "people", "homes"}], "year", "source"}
    "streets": "market",                # {"within_miles", "streets": [{"name", "class", "rank", "speed_mph", "paths"}]}
    "signals": "market",                # {"within_miles", "signals": [{"street", "cross_street", "lat", "lon", "miles_away"}]}
    "projects": "market",               # {"within_miles", "projects": [{"title", "kind", "status", "description", "builder",
                                        #   "stated": {"acres", "homes", "building_sq_ft"}, "lat", "lon", "miles_away"}], "lists_updated"}
    "schools": "market",                # {"within_miles", "schools": [{"name", "grades", "kind", "miles_away"}]}
    # What a forecast starts from; asked for when the Forecast page is opened.
    "people_before": "trend",           # like "people", from the census ten years earlier
    "regional_plan": "trend",           # {"adopted": {"label", "years", "rings": [{"miles", "households": {year: n},
                                        #   "jobs": {year: n}}]}, "draft": {...}, "city": {...}}
    "tracts": "trend",                  # {"tracts": [{"name", "income", "households", "owners", "renters", "homes",
                                        #   "built_2020_on", "miles_away", "direction", "share_within": {miles: 0..1}}],
                                        #   "county": {"name", "income"}, "survey": {...}}
}


class CityAdapter:
    """Fill in the class values and the three methods. See cities/menifee.py for a complete example."""

    id = ""                 # short name used in addresses, lower case, no spaces: "menifee"
    name = ""               # as shown on screen: "Menifee"
    region = ""             # "California"
    centre = {"lat": 0.0, "lon": 0.0}   # where the city map opens
    large_acres = 10.0      # what counts as a large parcel in this city
    site_miles = 1.0        # how far around a parcel "surroundings" looks
    # Who the facts come from, for the "Where the information comes from" tables: part -> plain source name.
    sources = {}
    # What is not covered for this city, in plain words.
    not_covered = ()
    # The SITE_PARTS this city does not publish at all (for example "signals", "projects"). The pages then say
    # "the city does not publish this" instead of treating the gap as a source that did not answer.
    not_published = ()
    # Zoning families for map colours, the legend and the zoning filter: (id, label, colour), most specific first.
    zoning_kinds = (("other", "Other", "#9aa0a6"),)

    def large_parcels(self, min_acres=None):
        """Every parcel of `min_acres` (default `large_acres`) or more: parcel rows, each with "centre" and "rings"."""
        raise NotImplementedError

    def parcels_in_box(self, west, south, east, north):
        """Every parcel a map view touches, any size: {"parcels": [{"apn", "apn_formatted", "acres", "zoning",
        "looks_vacant", "rings"}], "more": bool}. Optional: without it the map shows only the listed parcels."""
        return {"parcels": [], "more": False}

    def records_updated(self):
        """When the city last changed its parcel records: {"parcels": "2026-10-28"}. Optional."""
        return None

    def photo_date(self, lon, lat):
        """When the aerial photo at a spot was taken: {"taken": "2022-04-15", "year", "detail_metres"}. Optional."""
        return None

    def parcel(self, apn):
        """One parcel row with "centre", "outline" and "size_feet". Raises NotFound when there is none."""
        raise NotImplementedError

    def site_part(self, part, parcel):
        """One of SITE_PARTS for the parcel that parcel() returned, in the shape noted beside its name above.
        Return None for a part this city does not cover (the page then says "not covered yet")."""
        raise NotImplementedError

    # About the city itself, for the wider picture (outlook.py). `place` names who to see; the two methods read
    # the state's and the nation's open data (landplanner/sources). A city that has neither returns None.
    place = {}                          # {"name", "planning", "water"}

    def economy_part(self, part, year):
        """One of outlook.CITY_PARTS for the whole city (population, permits, sales, work, borrowing, prices, and
        housing: the state housing target and the permits counted toward it)."""
        return None

    def outlook_part(self, part, parcel, tracts=None):
        """One of outlook.PLACE_PARTS around a parcel (climate, hazards, nearby, residents)."""
        return None

    def zone_names(self):
        """The city's zoning codes in words: {"EDC-CC": "EDC-Community Core", ...}. Optional."""
        return {}

    def zoning_kind(self, code):
        """Which of `zoning_kinds` a zoning code belongs to (its id). Optional."""
        return "other"

    def zoning_notes(self, code):
        """Extra plain-words notes about one zone, each with where the wording comes from:
        [{"title", "quote", "source_name", "source_url", "plain"}]. Optional."""
        return []

    def allowed_uses(self, code, plan_name="", layer_zone=""):
        """What the city's own code allows in a parcel's zoning: for each use, allowed outright, with a permit, or
        not at all (the answer of uses.UseTable.answer, read from a table recorded in this repository). `plan_name`
        is the specific plan named at the spot and `layer_zone` the zone the city's zoning map gives there.
        Optional: None means this city's table of allowed uses has not been read, and the pages say so."""
        return None

    def describe(self):
        """The city card and page headers are drawn from this."""
        return {"id": self.id, "name": self.name, "region": self.region, "centre": self.centre,
                "large_acres": self.large_acres, "site_miles": self.site_miles, "sources": dict(self.sources),
                "not_covered": list(self.not_covered), "not_published": list(self.not_published),
                "zoning_kinds": [{"id": k, "label": label, "colour": colour} for k, label, colour in self.zoning_kinds],
                "links": dict(getattr(self, "links", {}))}
