"""What the app can do, as plain functions the server's routes call. No HTTP in here.

Every answer from a public service goes through the cache (cache.py):
    a city's large parcels      12 hours
    one parcel, one site part   7 days   (the city updates its parcel records about monthly)
    the city's zoning names     30 days
A site part that did not answer is not asked again for a minute, then the next visit to the page retries it.
"Check again" buttons in the app pass fresh=True, which asks the service even when a young copy exists.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import lands as L
from .cache import Cache
from .cities import NotFound, SITE_PARTS, SourceError
from .saved import SavedLands

HOUR = 3600
LARGE_TTL, PARCEL_TTL, PART_TTL, NAMES_TTL, RETRY_AFTER = 12 * HOUR, 7 * 24 * HOUR, 7 * 24 * HOUR, 30 * 24 * HOUR, 60


# A service that answers in a shape nobody expected is treated like one that did not answer.
DOWN = (SourceError, KeyError, TypeError, ValueError, IndexError)


class Problem(Exception):
    """Something to tell the person using the app, in plain words, with the HTTP status that fits."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class LandPlanner:
    def __init__(self, cities, data_dir, clock=time.time):
        self.cities = cities
        self.data_dir = Path(data_dir)
        self.clock = clock
        self.cache = Cache(self.data_dir / "cache", clock)
        self.saved = SavedLands(self.data_dir / "my-lands.json")
        self._failed = {}
        self._guard = threading.Lock()

    # ---- cities

    def city(self, city_id):
        if city_id not in self.cities:
            raise Problem(404, "no-such-city", "That city is not in Land Planner yet.")
        return self.cities[city_id]

    def city_list(self):
        return {"cities": [c.describe() for c in self.cities.values()]}

    def _unreachable(self, city, what="map service"):
        return Problem(502, "source-down", f"{city.name}'s public {what} did not answer just now. "
                                           "Check the internet connection and try again.")

    def _large(self, city, fresh=False):
        try:
            return self.cache.get(f"{city.id}/large-parcels/{city.large_acres:g}", LARGE_TTL, city.large_parcels, fresh)
        except DOWN as e:
            raise self._unreachable(city) from e

    def zone_names(self, city, fresh=False):
        """The city's zoning names, or an empty table when its service is down (codes are then shown as codes)."""
        try:
            return self.cache.get(f"{city.id}/zone-names", NAMES_TTL, city.zone_names, fresh)[0] or {}
        except DOWN:
            return {}

    def _decorate(self, city, row, names):
        row = dict(row)
        row["zoning_kind"] = city.zoning_kind(row.get("zoning"))
        row["zoning_name"] = L.zone_name(row.get("zoning"), names)
        return row

    def summary(self, city_id, fresh=False):
        city = self.city(city_id)
        rows, meta = self._large(city, fresh)
        return {"city": city.id, "large_acres": city.large_acres, **L.summary(rows), **meta}

    # ---- lands

    def lands(self, city_id, min_acres=None, max_acres=None, zoning="", kind="", vacant=False, q="",
              sort="acres", descending=True, fresh=False):
        city = self.city(city_id)
        rows, meta = self._large(city, fresh)
        names = self.zone_names(city)
        kinds = city.describe()["zoning_kinds"]
        rows = [self._decorate(city, {k: v for k, v in r.items() if k != "rings"}, names) for r in rows]
        found = L.sort_parcels(L.filter_parcels(rows, min_acres, max_acres, zoning, kind, vacant, q), sort, descending)
        out = {"city": city.id, "large_acres": city.large_acres, "total": len(rows), "count": len(found),
               "parcels": found, "zoning_options": L.zoning_options(rows, names, kinds), "direct": None,
               "direct_missing": False, **meta}
        number = L.digits(q)
        if not found and 8 <= len(number) <= 12 and number == "".join(c for c in str(q) if c not in " -"):
            # A whole parcel number that is not in the large-parcel list: look that one parcel up.
            try:
                out["direct"] = self._list_row(city, self._parcel(city, number)[0], names)
            except Problem as e:
                if e.status != 404:
                    raise
                out["direct_missing"] = True
        return out

    def shapes(self, city_id):
        """Outlines for the city map: {parcel number: rings}."""
        city = self.city(city_id)
        rows, meta = self._large(city)
        return {"city": city.id, "shapes": {r["apn"]: r.get("rings") or [] for r in rows}, **meta}

    def _list_row(self, city, parcel, names):
        row = {k: v for k, v in parcel.items() if k not in ("outline", "source")}
        row["rings"] = (parcel.get("outline") or {}).get("coordinates") or parcel.get("rings") or []
        return self._decorate(city, row, names)

    # ---- one land

    def _parcel(self, city, apn, fresh=False):
        number = L.digits(apn)
        if not 8 <= len(number) <= 12:
            raise Problem(404, "no-such-parcel", "That is not a parcel number. A parcel number (APN) has 9 digits, "
                                                 "for example 372-100-001.")
        try:
            return self.cache.get(f"{city.id}/parcel/{number}", PARCEL_TTL, lambda: city.parcel(number), fresh)
        except NotFound as e:
            raise Problem(404, "no-such-parcel", f"No parcel in {city.name} has the number {number}.") from e
        except DOWN as e:
            raise self._unreachable(city) from e

    def _part(self, city, parcel, part, fresh):
        """(value, state, fetched) for one site part; state is "ok", "nothing found there" or "did not answer"."""
        key = f"{city.id}/site/{parcel['apn']}/{part}"
        with self._guard:
            recent = self.clock() - self._failed.get(key, -1e12) < RETRY_AFTER
        if recent and not fresh:
            return None, "did not answer", None
        try:
            value, meta = self.cache.get(key, PART_TTL, lambda: city.site_part(part, parcel), fresh)
        except DOWN:
            with self._guard:
                self._failed[key] = self.clock()
            return None, "did not answer", None
        return value, "ok" if value else "nothing found there", meta["fetched"]

    def _labelled(self, city, part, value, names):
        """Rows that carry a zoning code also get its family and its name in words (on a copy: the saved
        answer stays exactly as the source gave it)."""
        if part == "neighbour_shapes" and value:
            return [self._decorate(city, row, names) for row in value]
        if part == "surroundings" and value:
            return {**value, "by_zoning": [self._decorate(city, row, names) for row in value.get("by_zoning", [])]}
        return value

    def land(self, city_id, apn, group="quick", fresh=False):
        """One land's facts. group "quick" is everything but the ground heights; "ground" is terrain and surface."""
        city = self.city(city_id)
        if group not in ("quick", "ground"):
            raise Problem(400, "bad-request", "Unknown group of facts.")
        parcel, meta = self._parcel(city, apn, fresh and group == "quick")
        names = self.zone_names(city)
        wanted = [p for p, g in SITE_PARTS.items() if g == group]
        with ThreadPoolExecutor(max_workers=len(wanted)) as pool:
            results = list(pool.map(lambda p: self._part(city, parcel, p, fresh), wanted))
        out = {"city": city.id, "apn": parcel["apn"], "group": group,
               "parcel": self._decorate(city, parcel, names), "parcel_fetched": meta["fetched"],
               "parcel_stale": meta["stale"], "parts": {}, "sources": {}, "fetched": {},
               "saved": self.saved.has(city.id, parcel["apn"])}
        for part, (value, state, fetched) in zip(wanted, results):
            out["parts"][part], out["sources"][part], out["fetched"][part] = self._labelled(city, part, value, names), state, fetched
        if group == "quick":
            out["zone_names"] = names
            out["zoning_notes"] = city.zoning_notes(parcel.get("zoning"))
        return out

    # ---- my lands

    def my_lands(self):
        out = []
        for record in self.saved.all():
            city = self.cities.get(record["city"])
            parcel = record.get("parcel") or {}
            if city:
                parcel = self._decorate(city, parcel, self.zone_names(city))
            out.append({"city": record["city"], "city_name": city.name if city else record["city"],
                        "apn": record["apn"], "saved_at": record.get("saved_at"), "parcel": parcel})
        return {"lands": out}

    def save(self, city_id, apn):
        city = self.city(city_id)
        number = L.digits(apn)
        row = None
        known = self.cache.peek(f"{city.id}/large-parcels/{city.large_acres:g}")
        if known:
            row = next((dict(r) for r in known[0] if r.get("apn") == number), None)
        if row is None:
            parcel = self._parcel(city, number)[0]
            row = {k: v for k, v in parcel.items() if k not in ("outline", "source")}
            row["rings"] = (parcel.get("outline") or {}).get("coordinates") or []
        self.saved.save(city.id, row["apn"], row)
        return self.my_lands()

    def remove(self, city_id, apn):
        if not self.saved.remove(city_id, L.digits(apn)):
            raise Problem(404, "not-saved", "That land is not in My lands.")
        return self.my_lands()
