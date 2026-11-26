"""Shared by the tests: recorded answers instead of the network, and a tiny made-up city.

Nothing in the tests may reach a public service. `offline()` swaps tools/menifee.py's one network function for a
replay of tests/fixtures/menifee.json; a question that was never recorded fails the test instead of going out.
"""
import hashlib
import json
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from landplanner.cities import CityAdapter, NotFound, SourceError  # noqa: E402
from landplanner.cities.menifee import tool  # noqa: E402

FIXTURES = json.loads((Path(__file__).resolve().parent / "fixtures" / "menifee.json").read_text(encoding="utf-8"))
EXAMPLE = "372100001"


def _key(url, params):
    return hashlib.sha1((url + "?" + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()[:16]


class Replay:
    """Stands in for tool.get_json. `down` is a list of words: a question whose address contains one of them
    fails the way a silent service does."""

    def __init__(self, down=()):
        self.down = list(down)
        self.asked = []

    def __call__(self, url, params=None, timeout=30, tries=2, post=False):
        self.asked.append(url)
        if any(word in url for word in self.down):
            raise tool.SourceError(f"{url}: (test) the service is down")
        found = FIXTURES.get(_key(url, params))
        if found is None:
            raise AssertionError(f"not recorded, and the tests must not use the network: {url} {params}")
        return json.loads(json.dumps(found["answer"]))  # a fresh copy each time


def offline(down=()):
    """with offline() as replay: ...   (also usable as a decorator-free patcher: p = offline(); p.start())"""
    return mock.patch.object(tool, "get_json", Replay(down))


SQUARE = [[[-117.17, 33.65], [-117.16, 33.65], [-117.16, 33.66], [-117.17, 33.66], [-117.17, 33.65]]]


def row(apn, acres, zoning, vacant=True, land=None, address="", rings=None):
    return {"apn": apn, "apn_formatted": f"{apn[:3]}-{apn[3:6]}-{apn[6:]}", "acres": acres, "zoning": zoning,
            "general_plan": "X", "assessor_class": "Vacant" if vacant else "Store", "looks_vacant": vacant,
            "address": address, "subdivision": "", "assessed_land_usd": land, "assessed_structures_usd": None if vacant else 5,
            "fire_hazard_zone": "none listed", "council_district": 1, "centre": {"lat": 33.655, "lon": -117.165},
            "rings": rings if rings is not None else SQUARE}


class Tinytown(CityAdapter):
    """A made-up city with four parcels, for testing the app without Menifee: what a second adapter looks like."""
    id = "tinytown"
    name = "Tinytown"
    region = "Nowhere"
    centre = {"lat": 33.655, "lon": -117.165}
    large_acres = 10.0
    sources = {"parcel": "Tinytown records"}
    zoning_kinds = (("homes", "Homes", "#ff0"), ("shops", "Shops", "#f00"), ("other", "Other", "#999"))

    def __init__(self):
        self.rows = [row("100000001", 50.0, "R-1", True, 900), row("100000002", 120.5, "C-1", False, 5000, "1 Main St"),
                     row("100000003", 12.0, "R-1 & C-1", True, None), row("100000004", 30.0, "", False, 100)]
        self.small = row("100000009", 2.5, "R-1", True, 10)
        self.down = set()        # names of calls that should fail: "large", "parcel", or a site part
        self.calls = []

    def _maybe_fail(self, name):
        self.calls.append(name)
        if name in self.down:
            raise SourceError(f"(test) {name} is down")

    def large_parcels(self):
        self._maybe_fail("large")
        return [dict(r) for r in self.rows]

    def parcel(self, apn):
        self._maybe_fail("parcel")
        for r in self.rows + [self.small]:
            if r["apn"] == apn:
                out = {k: v for k, v in r.items() if k != "rings"}
                out.update(outline={"type": "Polygon", "coordinates": r["rings"]}, size_feet={"east_west": 100, "north_south": 100})
                return out
        raise NotFound(f"no parcel {apn}")

    def site_part(self, part, parcel):
        self._maybe_fail(part)
        if part == "zoning":
            return {"zone": parcel["zoning"], "abbrev": parcel["zoning"], "what_it_allows": "Homes", "general_plan_says": "Homes"}
        if part == "neighbour_shapes":
            return [{"apn": "100000002", "zoning": "C-1", "acres": 120.5, "rings": SQUARE}]
        if part == "surroundings":
            return {"within_miles": 1.0, "total_acres": 10.0, "by_zoning": [{"zoning": "C-1", "acres": 10.0, "parcels": 1, "share_pct": 100.0}]}
        if part == "terrain":
            return {"feet_above_sea_level": {"centre": 10.0}, "fall_across_site_ft": 0.0, "rough_slope_pct": 0.0, "reading": "nearly flat"}
        return None   # general_plan, state_highway_traffic, surface: this city does not cover them

    def zone_names(self):
        self._maybe_fail("names")
        return {"R-1": "Single homes", "C-1": "Shops"}

    def zoning_kind(self, code):
        code = str(code or "")
        return "other" if not code or "&" in code else "homes" if code.startswith("R") else "shops"


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now
