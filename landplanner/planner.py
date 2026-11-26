"""What the app can do, as plain functions the server's routes call. No HTTP in here.

Every answer from a public service goes through the cache (cache.py):
    a city's large parcels      12 hours
    one parcel, one site part   7 days   (the city updates its parcel records about monthly)
    the city's zoning names     30 days
A site part that did not answer is not asked again for a minute, then the next visit to the page retries it.
"Check again" buttons in the app pass fresh=True, which asks the service even when a young copy exists.
"""
import hashlib
import logging
import math
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import lands as L
from .cache import Cache
from .cities import NotFound, SITE_PARTS, SourceError
from . import geometry as G
from . import forecast as F
from . import outlook as O
from . import plan as P
from .saved import SavedLands, SavedPlans

HOUR = 3600
LARGE_TTL, PARCEL_TTL, PART_TTL, NAMES_TTL, RETRY_AFTER = 12 * HOUR, 7 * 24 * HOUR, 7 * 24 * HOUR, 30 * 24 * HOUR, 60
UPDATED_TTL, PHOTO_TTL = 6 * HOUR, 30 * 24 * HOUR
ECONOMY_TTL = 14 * 24 * HOUR     # the city's yearly and monthly figures change slowly
FLOORS = (1.0, 2.0, 5.0)     # the list can start at these sizes as well as the city's own "large" size
MAX_VIEW_DEGREES = 0.09      # the widest map view the "every parcel in view" layer answers for (about 5 miles)


# A source can fail in two ways, and the pages say which. It did not answer (SourceError). Or it answered and the
# answer could not be read: a shape nobody expected, or a mistake in the code that reads it. The second kind never
# takes a page down, and it is never passed off as a silent service: it is named on the page and written to the log
# with where it happened, so it can be found and mended.
UNREADABLE = (KeyError, TypeError, ValueError, IndexError, AttributeError)
DOWN = (SourceError,) + UNREADABLE
LOG = logging.getLogger("landplanner")


def noted(what, error):
    """Writes an answer that could not be read to the log, with where it happened. Says whether it was one."""
    if error is None or isinstance(error, SourceError):
        return False
    LOG.warning("%s: the answer could not be read (%s: %s)", what, type(error).__name__, error, exc_info=error)
    return True


class Problem(Exception):
    """Something to tell the person using the app, in plain words, with the HTTP status that fits."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def parcel_number(text):
    """A parcel number's digits. Dashes and spaces are fine ("372-100-001"); anything else (a letter, a stray mark)
    or a number of digits no parcel has is refused in words, never quietly tidied into a different number."""
    raw = str(text if text is not None else "").strip()
    number = L.digits(raw)
    if not raw or not L.is_number_search(raw) or not 8 <= len(number) <= 12:
        shown = raw[:40] or "nothing"
        raise Problem(400, "bad-request", f"“{shown}” is not a parcel number. A parcel number (APN) has 9 digits, "
                                          "for example 372-100-001.")
    return number


class LandPlanner:
    def __init__(self, cities, data_dir, clock=time.time):
        self.cities = cities
        self.data_dir = Path(data_dir)
        self.clock = clock
        self.cache = Cache(self.data_dir / "cache", clock)
        self.saved = SavedLands(self.data_dir / "my-lands.json")
        self.plans = SavedPlans(self.data_dir / "plans.json")
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
        noted(f"{city.id} {what}", sys.exc_info()[1])       # called while the failure is being handled
        return Problem(502, "source-down", f"{city.name}'s public {what} did not answer just now. "
                                           "Check the internet connection and try again.")

    def floor_for(self, city, min_acres=None):
        """The size the list has to start at to answer a "smallest size" filter: the city's own large size, or one
        of FLOORS when the person asks for smaller land. Never below the smallest floor (the map shows the rest)."""
        if min_acres is None or min_acres >= city.large_acres:
            return float(city.large_acres)
        fits = [f for f in FLOORS if f <= min_acres and f < city.large_acres]
        return max(fits) if fits else min(FLOORS + (float(city.large_acres),))

    def _large(self, city, fresh=False, floor=None):
        floor = float(city.large_acres if floor is None else floor)
        load = city.large_parcels if floor == city.large_acres else (lambda: city.large_parcels(floor))
        try:
            return self.cache.get(f"{city.id}/large-parcels/{floor:g}", LARGE_TTL, load, fresh)
        except DOWN as e:
            raise self._unreachable(city) from e

    def zone_names(self, city, fresh=False):
        """The city's zoning names, or an empty table when its service is down (codes are then shown as codes)."""
        try:
            return self.cache.get(f"{city.id}/zone-names", NAMES_TTL, city.zone_names, fresh)[0] or {}
        except DOWN as e:
            noted(f"{city.id} zoning names", e)
            return {}

    def _decorate(self, city, row, names):
        row = dict(row)
        row["zoning_kind"] = city.zoning_kind(row.get("zoning"))
        row["zoning_name"] = L.zone_name(row.get("zoning"), names)
        return row

    @staticmethod
    def _sized(row):
        """A list row without its outline; when the outline measures a very different size from the recorded
        acres, the measured size is added as "outline_acres" so the list can say so. "counted_acres" is the size
        the row counts as (lands.counted_acres): the outline's when the record contradicts it."""
        out = {k: v for k, v in row.items() if k != "rings"}
        measured = G.rings_acres(row.get("rings"))
        if G.differs(row.get("acres"), measured):
            out["outline_acres"] = round(measured, 1)
        out["counted_acres"] = L.counted_acres(out)
        return out

    def summary(self, city_id, fresh=False):
        city = self.city(city_id)
        rows, meta = self._large(city, fresh)
        # a record whose acres its own outline contradicts counts at the outline's size, here and in the list
        return {"city": city.id, "large_acres": city.large_acres, **L.summary([self._sized(r) for r in rows]), **meta}

    # ---- lands

    def lands(self, city_id, min_acres=None, max_acres=None, zoning="", kind="", vacant=False, q="",
              sort="acres", descending=True, fresh=False):
        city = self.city(city_id)
        if min_acres is not None and max_acres is not None and min_acres > max_acres:
            raise Problem(400, "bad-request", f"The smallest size ({min_acres:g} acres) is larger than the largest size "
                                              f"({max_acres:g} acres). Nothing can be that size.")
        floor = self.floor_for(city, min_acres)
        rows, meta = self._large(city, fresh, floor)
        names = self.zone_names(city)
        kinds = city.describe()["zoning_kinds"]
        rows = [self._decorate(city, self._sized(r), names) for r in rows]
        found = L.sort_parcels(L.filter_parcels(rows, min_acres, max_acres, zoning, kind, vacant, q), sort, descending)
        out = {"city": city.id, "large_acres": city.large_acres, "floor": floor,
               "smallest_floor": min(FLOORS + (float(city.large_acres),)), "total": len(rows), "count": len(found),
               "parcels": found, "zoning_options": L.zoning_options(rows, names, kinds), "direct": None,
               "direct_missing": False, **meta}
        number = L.digits(q)
        if not found and 8 <= len(number) <= 12 and L.is_number_search(str(q or "").strip()):
            # A whole parcel number that is not in the large-parcel list: look that one parcel up.
            try:
                out["direct"] = self._list_row(city, self._parcel(city, number)[0], names)
            except Problem as e:
                if e.status != 404:
                    raise
                out["direct_missing"] = True
        return out

    def shapes(self, city_id, min_acres=None):
        """Outlines for the city map: {parcel number: rings}, for the same list `lands` gives for that size."""
        city = self.city(city_id)
        floor = self.floor_for(city, min_acres)
        rows, meta = self._large(city, floor=floor)
        return {"city": city.id, "floor": floor, "shapes": {r["apn"]: r.get("rings") or [] for r in rows}, **meta}

    def parcels_in_view(self, city_id, west, south, east, north):
        """Every parcel a map view touches, whatever its size, for the map when it is zoomed in."""
        city = self.city(city_id)
        box = [west, south, east, north]
        if any(v is None for v in box) or not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise Problem(400, "bad-request", "That is not a map view.")
        if east - west > MAX_VIEW_DEGREES or north - south > MAX_VIEW_DEGREES:
            raise Problem(400, "zoom-in", "Zoom in to see every parcel.")
        try:
            found = city.parcels_in_box(west, south, east, north)
        except DOWN as e:
            raise self._unreachable(city) from e
        names = self.zone_names(city)
        return {"city": city.id, "parcels": [self._decorate(city, r, names) for r in found.get("parcels", [])],
                "more": bool(found.get("more"))}

    def updated(self, city_id, lat=None, lon=None):
        """When the city's parcel records last changed, and when the aerial photo at a spot was taken. A part
        whose source did not answer is None: the page says so instead of showing a date."""
        city = self.city(city_id)
        out = {"city": city.id, "records": None, "photo": None}
        try:
            out["records"] = self.cache.get(f"{city.id}/records-updated", UPDATED_TTL, city.records_updated)[0]
        except DOWN as e:
            noted(f"{city.id}/records-updated", e)
        if lat is None or lon is None:
            lat, lon = city.centre["lat"], city.centre["lon"]
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            spot = f"{round(lat, 2):.2f},{round(lon, 2):.2f}"     # one answer per spot of about half a mile
            try:
                out["photo"] = self.cache.get(f"{city.id}/photo-date/{spot}", PHOTO_TTL,
                                              lambda: city.photo_date(round(lon, 2), round(lat, 2)))[0]
            except DOWN as e:
                noted(f"{city.id}/photo-date/{spot}", e)
        return out

    def _list_row(self, city, parcel, names):
        row = {k: v for k, v in parcel.items() if k not in ("outline", "source")}
        row["rings"] = (parcel.get("outline") or {}).get("coordinates") or parcel.get("rings") or []
        return self._decorate(city, row, names)

    # ---- one land

    def _parcel(self, city, apn, fresh=False):
        number = parcel_number(apn)
        try:
            return self.cache.get(f"{city.id}/parcel/{number}", PARCEL_TTL, lambda: city.parcel(number), fresh)
        except NotFound as e:
            raise Problem(404, "no-such-parcel", f"No parcel in {city.name} has the number {number}.") from e
        except DOWN as e:
            raise self._unreachable(city) from e

    def _part(self, city, parcel, part, fresh):
        """(value, state, fetched) for one site part; the states are listed in _asked."""
        return self._asked(f"{city.id}/site/{parcel['apn']}/{part}", lambda: city.site_part(part, parcel), PART_TTL, fresh)

    def _asked(self, key, load, ttl=PART_TTL, fresh=False):
        """(value, state, fetched) for one answer kept under `key`, asked for with `load` when no young copy is
        kept. state is one of:
          "ok"                   it answered
          "nothing found there"  it answered, with nothing for this spot
          "did not answer"       it did not answer just now
          "could not be read"    it answered in a form this app could not read (the log says where)
          "older copy"           it failed just now, and the copy kept from before is given in its place
                                 (fetched says when that copy was read)
        A source that just failed is not asked again for a minute."""
        with self._guard:
            at, why = self._failed.get(key, (-1e12, ""))
        if self.clock() - at < RETRY_AFTER and not fresh:
            return None, why, None
        seen = []

        def asked():
            try:
                return load()
            except DOWN as e:
                seen.append(e)        # the cache may answer with its older copy: the failure is still noted
                raise

        try:
            value, meta = self.cache.get(key, ttl, asked, fresh, retry_after=RETRY_AFTER)
        except DOWN as e:
            why = "could not be read" if noted(key, e) else "did not answer"
            with self._guard:
                self._failed[key] = (self.clock(), why)
            return None, why, None
        if seen:
            noted(key, seen[0])
        if meta.get("stale") and value:
            return value, "older copy", meta["fetched"]
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
        if group not in ("quick", "ground", "market", "trend"):
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

    # ---- the plan for one land

    def plan(self, city_id, apn, settings=None, forget=False):
        """The suggested land-use plan with its reasons (plan.py). `settings` are the owner's own changes: given,
        they are kept for next time; left out, the kept ones are used. `forget` goes back to the suggestion.
        The ground heights are used when they have already been read (they are slow); the answer says if not."""
        city = self.city(city_id)
        parcel, meta = self._parcel(city, apn)
        number = parcel["apn"]
        if forget:
            self.plans.put(city.id, number, None)
            settings = None
        elif settings is not None:
            settings = P.clean_settings(settings)
            # settings that change nothing are not kept: the land simply shows the suggestion
            self.plans.put(city.id, number, None if settings == P.clean_settings({}) else settings)
        else:
            settings = self.plans.get(city.id, number)
        parts, sources, fetched = self._plan_facts(city, parcel)
        out = P.make_plan(self._decorate(city, parcel, self.zone_names(city)), parts, settings, city.zoning_kind)
        out.update(city=city.id, apn=number, sources=sources, fetched=fetched, parcel_fetched=meta["fetched"],
                   ground_read=bool(parts["surface"]), kept=self.plans.get(city.id, number) is not None,
                   kept_in=str(self.plans.path.resolve()))
        return out

    def _plan_facts(self, city, parcel):
        """The site facts a plan is worked out from: (parts, sources, fetched)."""
        names = self.zone_names(city)
        wanted = [p for p, g in SITE_PARTS.items() if g in ("quick", "market") and p != "neighbour_shapes"]
        with ThreadPoolExecutor(max_workers=len(wanted)) as pool:
            results = list(pool.map(lambda p: self._part(city, parcel, p, False), wanted))
        parts, sources, fetched = {}, {}, {}
        for part, (value, state, at) in zip(wanted, results):
            parts[part], sources[part], fetched[part] = self._labelled(city, part, value, names), state, at
        for part in ("surface", "terrain"):
            known = self.cache.peek(f"{city.id}/site/{parcel['apn']}/{part}")
            parts[part] = known[0] if known else None
        return parts, sources, fetched

    # ---- the forecast for one land, or for several as one site

    FORECAST_PARTS = ("people", "people_before", "regional_plan", "tracts", "projects", "state_highway_traffic")
    MOST_PARCELS = 12

    def forecast(self, city_id, apns, settings=None, forget=False):
        """The year-by-year forecast (forecast.py) for one parcel, or for several treated as one site. The owner's
        own figures are kept like a plan's. Each parcel's plan is the one the owner keeps for it."""
        return self._forecast(city_id, apns, settings, forget)[0]

    def outlook(self, city_id, apns, fresh=False):
        """The wider picture for the same site (outlook.py): the city's economy by year, weather, hazards, what
        is close by, the typical resident, and the steps to take. Asked for after the forecast is on screen,
        because some of these sources are slow the first time."""
        out, plans, parts, site, anchor = self._forecast(city_id, apns, None, False)
        city = self.city(city_id)
        year = time.gmtime(self.clock()).tm_year
        asked = {name: (f"{city.id}/economy/{name}", lambda name=name: city.economy_part(name, year), ECONOMY_TTL)
                 for name in O.ECONOMY_PARTS}
        tracts = [{"id": t.get("id"), "households": t.get("households"),
                   "share": (t.get("share_within") or {}).get(F.MARKET_MILES) or (t.get("share_within") or {}).get(str(F.MARKET_MILES)) or 0}
                  for t in (parts.get("tracts") or {}).get("tracts") or []]
        tracts = [t for t in tracts if t["id"] and t["share"]]
        for name in O.PLACE_PARTS:
            asked[name] = (f"{city.id}/site/{anchor['apn']}/outlook-{name}",
                           lambda name=name: city.outlook_part(name, anchor, tracts), PART_TTL)
        with ThreadPoolExecutor(max_workers=len(asked)) as pool:
            results = dict(zip(asked, pool.map(lambda a: self._asked(a[0], a[1], a[2], fresh), asked.values())))
        more = {name: r[0] for name, r in results.items()}
        more["population"] = more.get("population") or parts.get("population")
        answer = O.make_outlook(site, out, plans, more, city.place)
        answer.update(city=city.id, city_name=city.name, apns=out["apns"], year=out["year"],
                      answered={name: r[1] for name, r in results.items()},
                      fetched={name: r[2] for name, r in results.items()})
        return answer

    def ground(self, city_id, apns, fresh=False):
        """The ground heights under a site (one parcel or several as one block) and the plan drawn on it, for the
        3D view. The heights come from a slow service the first time, so this is asked for on its own."""
        out, plans, _, site, anchor = self._forecast(city_id, apns, None, False)
        city = self.city(city_id)
        surface, state, fetched = self._part(city, anchor, "surface", fresh)
        if surface and site["one_plan"] and len(site["apns"]) > 1:
            # the block's plan again, now that its ground is known (drainage goes to the low ground)
            facts, _, _ = self._plan_facts(city, anchor)
            plans = [P.make_plan(self._decorate(city, anchor, self.zone_names(city)), facts, None, city.zoning_kind)]
        whole = plans[0] if len(plans) == 1 else None
        return {"city": city.id, "apns": out["apns"], "answered": state, "fetched": fetched, "surface": surface,
                "one_plan": bool(whole),
                "parcel": {"apn": anchor["apn"], "acres": site["acres"], "centre": anchor["centre"],
                           "outline": anchor["outline"], "size_feet": anchor.get("size_feet")},
                "plan": {"uses": whole.get("uses"), "drawing": whole.get("drawing"), "acres": whole.get("acres"),
                         "street_lines": whole.get("street_lines")} if whole else None}

    def _forecast(self, city_id, apns, settings, forget):
        """(the forecast, the plans it used, the facts it read, the site, the parcel standing in for the site)."""
        city = self.city(city_id)
        numbers = []
        for apn in apns or []:
            number = parcel_number(apn)
            if number not in numbers:
                numbers.append(number)
        if not numbers:
            raise Problem(400, "bad-request", "A forecast needs at least one parcel number.")
        if len(numbers) > self.MOST_PARCELS:
            raise Problem(400, "bad-request", f"A forecast takes up to {self.MOST_PARCELS} parcels at a time.")
        parcels = [self._parcel(city, n)[0] for n in numbers]
        numbers = [p["apn"] for p in parcels]
        names = self.zone_names(city)
        site, anchor = self._site(city, parcels, names)
        kept_as = "forecast/" + "+".join(sorted(numbers))
        if forget:
            self.plans.put(city.id, kept_as, None)
            settings = None
        elif settings is not None:
            settings = F.clean_settings(settings)
            self.plans.put(city.id, kept_as, settings if settings["assumptions"] else None)
        else:
            settings = self.plans.get(city.id, kept_as)
        with ThreadPoolExecutor(max_workers=len(self.FORECAST_PARTS)) as pool:
            results = list(pool.map(lambda p: self._part(city, anchor, p, False), self.FORECAST_PARTS))
        parts = {p: r[0] for p, r in zip(self.FORECAST_PARTS, results)}
        year = time.gmtime(self.clock()).tm_year
        # the whole city's homes by year since the census (kept per city, not per site)
        parts["population"] = self._asked(f"{city.id}/economy/population",
                                          lambda: city.economy_part("population", year), ECONOMY_TTL)[0]
        if site["one_plan"] and len(parcels) > 1:
            # neighbours that make one block of land are planned as one: the area's need for shops is met once,
            # not once per parcel
            facts, _, _ = self._plan_facts(city, anchor)
            plans = [P.make_plan(self._decorate(city, anchor, names), facts, None, city.zoning_kind)]
        else:
            plans = []
            for parcel in parcels:
                facts, _, _ = self._plan_facts(city, parcel)
                plans.append(P.make_plan(self._decorate(city, parcel, names), facts,
                                         self.plans.get(city.id, parcel["apn"]), city.zoning_kind))
        out = F.make_forecast(site, parts, plans, settings, year=year)
        out["programme"]["basis"] = (
            "The plan each parcel has on its own Plan page." if len(parcels) == 1 else
            "One plan worked out for the whole block of land, under today's zoning." if site["one_plan"] else
            "Each parcel's own plan, added up (the parcels do not form one block, or are zoned differently).")
        # where each use sits on the land, for the site plan and the phasing map
        named = {u["id"]: u for u in P.USES}
        out["programme"]["drawings"] = [
            {"pieces": [{**piece, "label": named.get(piece.get("use"), {}).get("label"),
                         "short": named.get(piece.get("use"), {}).get("short"),
                         "colour": named.get(piece.get("use"), {}).get("colour")}
                        for piece in (p.get("drawing") or {}).get("pieces") or []],
             "streets": (p.get("drawing") or {}).get("streets") or [],
             "front": (p.get("drawing") or {}).get("front"),
             "why": (p.get("drawing") or {}).get("why") or [], "street_lines": p.get("street_lines") or []} for p in plans]
        # where traffic enters and leaves, and the signals around the site, from the plans
        moving = [p.get("traffic") or {} for p in plans]
        out["traffic"]["entrances"] = [e for m in moving for e in m.get("entrances") or []]
        out["traffic"]["signals_to_study"] = sum(m.get("signals_to_study") or 0 for m in moving)
        out["traffic"]["existing_signals"] = (moving[0].get("existing_signals") or []) if moving else []
        if not site["together"]:
            out["limits"].insert(0, "These parcels are not next to each other. The forecast is worked out around the point "
                                    "between them, so it fits each one less well than a forecast of its own.")
        out.update(city=city.id, city_name=city.name, apns=numbers,
                   answered={p: r[1] for p, r in zip(self.FORECAST_PARTS, results)},
                   fetched={p: r[2] for p, r in zip(self.FORECAST_PARTS, results)},
                   kept=self.plans.get(city.id, kept_as) is not None, kept_in=str(self.plans.path.resolve()))
        return out, plans, parts, site, anchor

    def _site(self, city, parcels, names):
        """Several parcels as one site: what the page shows about it, and a stand-in parcel at its middle that
        the facts around it are read (and saved) under."""
        rows = [self._decorate(city, p, names) for p in parcels]
        weights = [p.get("acres") or 1 for p in parcels]      # a parcel with no recorded size still counts
        lat = sum(w * p["centre"]["lat"] for w, p in zip(weights, parcels)) / sum(weights)
        lon = sum(w * p["centre"]["lon"] for w, p in zip(weights, parcels)) / sum(weights)
        k = 69.17 * math.cos(math.radians(lat))
        spread = max(math.hypot((p["centre"]["lon"] - lon) * k, (p["centre"]["lat"] - lat) * 69.17) for p in parcels)
        site = {"apns": [p["apn"] for p in parcels], "acres": round(sum(p.get("acres") or 0 for p in parcels), 2),
                "centre": {"lat": round(lat, 6), "lon": round(lon, 6)}, "spread_miles": round(spread, 2),
                "together": spread <= 0.75,
                "parcels": [{"apn": r["apn"], "apn_formatted": r.get("apn_formatted"), "acres": r.get("acres"),
                             "zoning": r.get("zoning"), "zoning_name": r.get("zoning_name"), "zoning_kind": r.get("zoning_kind"),
                             "address": r.get("address") or "", "centre": r["centre"], "outline": r["outline"]} for r in rows]}
        site["one_plan"] = len(parcels) == 1
        if len(parcels) == 1:
            return site, parcels[0]
        rings = [ring for p in parcels for ring in p["outline"]["coordinates"]]
        pts = [pt for ring in rings for pt in ring] or [(lon, lat)]
        around = G.hull(pts)
        block = [[list(p) for p in around + around[:1]]]
        zonings = {p.get("zoning") or "" for p in parcels}
        # one block of land: neighbours whose joint outline holds little but themselves, all in one zone
        site["one_plan"] = bool(site["together"] and len(zonings) == 1
                                and not G.differs(site["acres"], G.rings_acres(block), 0.12))
        size = {"east_west": round((max(x for x, _ in pts) - min(x for x, _ in pts)) * k * 5280),
                "north_south": round((max(y for _, y in pts) - min(y for _, y in pts)) * 69.17 * 5280)}
        name = "site-" + hashlib.sha1("+".join(sorted(site["apns"])).encode()).hexdigest()[:12]
        lands = [p.get("assessed_land_usd") for p in parcels]
        return site, {"apn": name, "apn_formatted": f"{len(parcels)} parcels", "acres": site["acres"],
                      "zoning": parcels[0].get("zoning") if len(zonings) == 1 else "",
                      "fire_hazard_zone": next((p.get("fire_hazard_zone") for p in parcels if p.get("fire_hazard_zone")), None),
                      "assessed_land_usd": sum(lands) if all(v is not None for v in lands) else None,
                      "looks_vacant": all(p.get("looks_vacant") for p in parcels), "centre": site["centre"],
                      "outline": {"coordinates": block if site["one_plan"] else rings}, "size_feet": size}

    def compare(self):
        """My lands side by side: for each saved land, the headline numbers of its plan as the owner keeps it
        (or the suggestion under today's zoning) and of the best-use suggestion. A land whose records did not
        answer is listed with the reason instead of numbers. Nothing is kept or changed by asking."""
        def one(record):
            row = {"city": record["city"], "apn": record["apn"], "saved_at": record.get("saved_at")}
            city = self.cities.get(record["city"])
            if not city:
                return {**row, "problem": "This city is no longer in Land Planner."}
            row["city_name"] = city.name
            try:
                parcel, _ = self._parcel(city, record["apn"])
                parts, sources, _ = self._plan_facts(city, parcel)
            except Problem as e:
                return {**row, "problem": e.message}
            decorated = self._decorate(city, parcel, self.zone_names(city))
            kept = self.plans.get(city.id, parcel["apn"])
            row.update(apn_formatted=parcel.get("apn_formatted"), acres=parcel.get("acres"), zoning=parcel.get("zoning"),
                       zoning_name=decorated.get("zoning_name"), address=parcel.get("address") or "",
                       has_own_plan=kept is not None,
                       did_not_answer=[k for k, v in sources.items() if v in ("did not answer", "could not be read")],
                       plans={"kept": P.headline(P.make_plan(decorated, parts, kept or {"mode": "zoning"}, city.zoning_kind)),
                              "best": P.headline(P.make_plan(decorated, parts, {"mode": "best"}, city.zoning_kind))})
            return row

        records = self.saved.all()
        if not records:
            return {"lands": []}
        with ThreadPoolExecutor(max_workers=min(4, len(records))) as pool:
            return {"lands": list(pool.map(one, records))}

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
        return {"lands": out, "kept_in": str(self.saved.path.resolve())}

    def save(self, city_id, apn):
        city = self.city(city_id)
        number = parcel_number(apn)
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
        if not self.saved.remove(city_id, parcel_number(apn)):
            raise Problem(404, "not-saved", "That land is not in My lands.")
        return self.my_lands()
