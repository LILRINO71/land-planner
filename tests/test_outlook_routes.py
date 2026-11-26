"""The wider picture through LandPlanner.outlook and the server's outlook route, and the city adapters' two methods that feed
it. Nothing here reaches the network: the made-up town answers from memory, and its two methods for the wider picture
(economy_part and outlook_part) are the ones a test changes; on Menifee the two adapter methods are replaced by recorders and the
state and national readers (landplanner.sources) by stand-ins that note how they were asked.

The planner reads a silent source as "did not answer": a part that raises is not asked again for a minute (the planner's
clock is moved by hand here), and every part that answered is kept for later (14 days for the city's figures, 7 days for the
facts around the site).
"""
import calendar
import copy
import http.client
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support
from support import EXAMPLE, Clock, Tinytown
from landplanner import outlook as O
from landplanner.cities import CityAdapter, SourceError
from landplanner.cities.menifee import Menifee
from landplanner.planner import ECONOMY_TTL, PART_TTL, RETRY_AFTER, LandPlanner, Problem
from landplanner.server import route
from landplanner.sources import economy as economy_source
from landplanner.sources import fetch
from landplanner.sources import place as place_source

import test_forecast_routes as forecast_routes

NOW = calendar.timegm((2026, 11, 25, 12, 0, 0))
DAY = 86400
PATH = "/api/cities/tinytown/outlook"
BLOCKS = ("economy", "housing", "climate", "hazards", "nearby", "resident", "todo")
# hazards and nearby places are always asked with the city's own map layers named, so no city borrows another's
THE_CITYS_OWN_MAPS = {"city_layers": place_source.MENIFEE_LAYERS}
ALL_PARTS = O.CITY_PARTS + O.PLACE_PARTS


def tearDownModule():
    forecast_routes.tearDownModule()      # the saved Menifee answers worked out once for the forecast tests, if this file warmed them


def q(*apns, **more):
    return {"apns": [",".join(apns)], **{k: [str(v)] for k, v in more.items()}}


# ---------------------------------------------------------------- the made-up parts

def made_up_economy():
    return {"population": {"rows": [{"year": 2020, "people": 1000, "homes": 400, "occupied_homes": 380},
                                    {"year": 2025, "people": 1100, "homes": 440, "occupied_homes": 420}], "source": "Tinytown state estimates"},
            "permits": {"rows": [{"year": y, "homes": 10 * i, "single_family": 10 * i, "multi_family": 0, "months_reported": 12}
                                 for i, y in enumerate(range(2021, 2026), 1)], "source": "Tinytown permits"},
            "sales": {"rows": [{"year": 2024, "sales_usd": 4_000_000, "quarters": 4}, {"year": 2025, "sales_usd": 4_200_000, "quarters": 4}],
                      "source": "Tinytown tax agency"},
            "work": {"rows": [{"year": 2025, "unemployment_pct": 4.5, "labour_force": 600, "employed": 573}], "county_rows": None, "source": "Tinytown jobs"},
            "borrowing": {"rows": [{"year": 2025, "rate_pct": 6.2, "weeks": 52}, {"year": 2026, "rate_pct": 6.5, "weeks": 46}],
                          "latest": {"date": "2026-11-20", "rate_pct": 6.9}, "source": "Tinytown loans"},
            "prices": {"rows": [{"year": 2024, "index": 100.0, "change_pct": 2.0}, {"year": 2025, "index": 103.0, "change_pct": 3.0}], "source": "Tinytown prices"},
            "housing": made_up_housing()}


def made_up_housing():
    """What the state housing reader gives for a town: the cycle's target, the permits so far, what is left, the years."""
    return {"cycle": "6th", "from_year": 2021, "to_year": 2029, "planning_period": "10/15/2021 - 10/15/2029", "jurisdiction": "TINYTOWN",
            "target": {"very_low": 100, "low": 60, "moderate": 40, "above_moderate": 200, "total": 400},
            "permitted": {"very_low": 10, "low": 20, "moderate": 30, "above_moderate": 250, "total": 310},
            "left": {"very_low": 90, "low": 40, "moderate": 10, "above_moderate": 0, "total": 140},
            "share_pct": {"very_low": 10.0, "low": 33.3, "moderate": 75.0, "above_moderate": 125.0, "total": 77.5},
            "by_year": [{"year": 2024, "very_low": 5, "low": 10, "moderate": 10, "above_moderate": 100, "total": 125},
                        {"year": 2025, "very_low": 5, "low": 10, "moderate": 20, "above_moderate": 150, "total": 185}],
            "through_year": 2025, "notes": [], "source": "Tinytown housing department", "as_of": "annual reports through 2025"}


def made_up_place():
    return {"climate": {"typical_year": {"mean_f": 61.4, "rain_in": 11.8}, "months": [{"month": "Jul", "high_f": 104.3}],
                        "trend": {"mean_f_per_decade": 0.4, "from_year": 1985, "to_year": 2025}},
            "hazards": {"flood": {"zone": "X", "meaning": "Minimal flood hazard.", "special_hazard_area": False},
                        "fire": {"level": "High", "levels_on_site": ["High"], "map_year": 2025}, "did_not_answer": []},
            "nearby": {"places": [{"kind": "park", "name": "Mosaic Park", "miles_away": 0.85}]},
            "residents": {"typical": {"median_age": 36.4, "household_size": 3.4}, "earlier": None, "tracts": []}}


def tract(name, households=1000, share=None, income=100000, **more):
    t = {"id": name, "name": name, "income": income, "households": households, "owners": None if households is None else households - 200, "renters": 200,
         "homes": None if households is None else households + 50, "built_2020_on": 40, "lat": 33.65, "lon": -117.17, "miles_away": 1.0, "direction": "north",
         "share_within": share}
    t.update(more)
    return t


def survey(*tracts):
    return {"within_miles": 5.0, "source": "Test survey", "survey": {"income": "2018-2022", "homes": "2018-2022"},
            "county": {"name": "Test County", "income": 100000}, "tracts": list(tracts)}


class Town(Tinytown):
    """Tinytown with a name for who to see, answers for the wider picture, a record of how it was asked, and parts that can be silenced."""
    place = {"name": "Tinytown", "planning": "Tinytown Planning Office", "water": "Tinytown Water District"}

    def __init__(self, tracts=None):
        super().__init__()
        self.economy = made_up_economy()
        self.here = made_up_place()
        self.survey = tracts
        self.silent = {}                      # part name -> the exception to raise when it is asked for
        self.economy_calls, self.here_calls = [], []

    def economy_part(self, part, year):
        self.economy_calls.append((part, year))
        if part in self.silent:
            raise self.silent[part]
        return copy.deepcopy(self.economy.get(part))

    def outlook_part(self, part, parcel, tracts=None):
        self.here_calls.append((part, parcel["apn"], copy.deepcopy(tracts)))
        if part in self.silent:
            raise self.silent[part]
        return copy.deepcopy(self.here.get(part))

    def site_part(self, part, parcel):
        if part == "tracts" and self.survey is not None:
            self._maybe_fail(part)
            return copy.deepcopy(self.survey)
        return super().site_part(part, parcel)

    def asked(self, part):
        """How many times a part (economy or around the site) was asked of the city."""
        return sum(1 for c in self.economy_calls + self.here_calls if c[0] == part)

    def silence(self, *parts, error=None):
        for part in parts:
            self.silent[part] = error or SourceError(f"(test) {part} is down")


class OnTown(unittest.TestCase):
    """A planner over the made-up town on a temporary data folder, with its own clock."""

    def make_town(self):
        return Town()

    def setUp(self):
        patcher = support.offline()           # a safety net: nothing here may reach the network
        patcher.start()
        self.addCleanup(patcher.stop)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.clock = Clock(NOW)
        self.city = self.make_town()
        self.app = self.make_app()

    def make_app(self):
        return LandPlanner({"tinytown": self.city}, self.folder.name, clock=self.clock)

    def get(self, *apns, app=None, **more):
        status, out = route(app or self.app, "GET", PATH, q(*apns or ("100000001",), **more))
        self.assertEqual(status, 200)
        return out

    def problem(self, *args, **kw):
        with self.assertRaises(Problem) as caught:
            route(*args, **kw)
        return caught.exception


# ---------------------------------------------------------------- the answer

class TheAnswer(OnTown):
    def test_it_has_the_seven_blocks_and_what_was_asked_and_when(self):
        out = self.get()
        for block in BLOCKS:
            self.assertIn(block, out)
        self.assertEqual((out["city"], out["city_name"], out["apns"], out["year"]), ("tinytown", "Tinytown", ["100000001"], 2026))
        self.assertEqual(set(out["answered"]), set(ALL_PARTS))
        self.assertEqual(set(out["fetched"]), set(ALL_PARTS))
        self.assertEqual(set(out["answered"].values()), {"ok"})
        self.assertEqual(set(out["fetched"].values()), {float(NOW)})

    def test_every_block_is_made_from_what_the_town_answered(self):
        out = self.get()
        self.assertTrue(all(out[b]["available"] for b in ("economy", "climate", "hazards", "nearby", "resident")))
        self.assertEqual(out["economy"]["place"], "Tinytown")
        self.assertTrue(out["economy"]["facts"][0].startswith("Tinytown had 1,000 people in 2020 and 1,100 in 2025"))
        self.assertEqual(out["climate"]["typical_year"]["mean_f"], 61.4)
        self.assertEqual([f["topic"] for f in out["hazards"]["findings"]], ["Flood", "Wildfire"])
        self.assertEqual(out["nearby"]["places"][0]["name"], "Mosaic Park")
        self.assertEqual(out["resident"]["typical"]["median_age"], 36.4)
        self.assertEqual(out["todo"]["steps"][0]["who"], "Tinytown Planning Office")
        self.assertIn("Fire protection plan: cleared space, fire-resistant building, two ways out", [s["what"] for s in out["todo"]["steps"]])

    def test_the_housing_block_is_made_from_what_the_town_answered_and_the_homes_of_the_plan(self):
        out = self.get()
        block = out["housing"]
        self.assertTrue(block["available"])
        self.assertEqual((block["target"], block["permitted"], block["left"], block["through_year"], block["to_year"]), (400, 310, 140, 2025, 2029))
        self.assertEqual(block["lower"]["left"], 140)
        self.assertEqual(block["source"], "Tinytown housing department")
        self.assertTrue(block["facts"][0].startswith("The state requires Tinytown to plan for 400 new homes between 2021 and 2029."))
        self.assertEqual(out["answered"]["housing"], "ok")
        self.assertEqual(out["fetched"]["housing"], float(NOW))

    def test_the_year_is_the_year_of_the_clock_and_goes_to_the_city_with_each_economy_part(self):
        self.clock.now = calendar.timegm((2031, 3, 1, 0, 0, 0))
        out = self.get()
        self.assertEqual(out["year"], 2031)
        self.assertEqual({y for _, y in self.city.economy_calls}, {2031})
        self.assertEqual(out["climate"]["ahead"]["year"], 2041)

    def test_it_can_be_sent_as_json_without_nan(self):
        json.dumps(self.get(), allow_nan=False)

    def test_the_parcel_number_may_be_written_with_dashes_and_other_ways(self):
        self.assertEqual(self.get("100-000-001")["apns"], ["100000001"])
        status, out = route(self.app, "GET", PATH, {"apns": [" 100000001+100000001 "]})
        self.assertEqual((status, out["apns"]), (200, ["100000001"]))

    def test_the_parcel_is_looked_up_once(self):
        out = self.get()
        self.assertEqual(self.city.calls.count("parcel"), 1)
        self.assertTrue(out["todo"]["steps"])

    def test_it_writes_no_figures_of_the_owners(self):
        self.get()
        self.assertFalse((Path(self.folder.name) / "plans.json").exists())

    def test_other_methods_are_not_found(self):
        for method in ("POST", "DELETE", "PUT"):
            with self.subTest(method=method):
                e = self.problem(self.app, method, PATH, q("100000001"), body={})
                self.assertEqual((e.status, e.code), (404, "not-found"))

    def test_a_longer_address_is_not_found(self):
        e = self.problem(self.app, "GET", PATH + "/more", q("100000001"))
        self.assertEqual((e.status, e.code), (404, "not-found"))


class WhatTheAddressMustHave(OnTown):
    def test_no_parcels_is_a_400(self):
        for query in ({}, {"apns": [""]}, {"apns": ["  "]}, {"apns": [", ,+ "]}, {"apns": ["abc"]}, {"apns": []}, {"other": ["1"]}, None):
            with self.subTest(query=query):
                e = self.problem(self.app, "GET", PATH, query)
                self.assertEqual((e.status, e.code), (400, "bad-request"))
        self.assertEqual(self.city.economy_calls + self.city.here_calls, [], "nothing was asked of any source")

    def test_an_unknown_city_is_a_404_with_or_without_parcels(self):
        for query in (q("100000001"), {}):
            with self.subTest(query=query):
                e = self.problem(self.app, "GET", "/api/cities/nowhere/outlook", query)
                self.assertEqual((e.status, e.code), (404, "no-such-city"))

    def test_an_unknown_parcel_is_a_404_and_nothing_else_is_asked(self):
        e = self.problem(self.app, "GET", PATH, q("999999999"))
        self.assertEqual((e.status, e.code), (404, "no-such-parcel"))
        self.assertEqual(self.city.economy_calls + self.city.here_calls, [])

    def test_one_unknown_parcel_among_good_ones_is_a_404(self):
        e = self.problem(self.app, "GET", PATH, q("100000001", "999999999"))
        self.assertEqual((e.status, e.code), (404, "no-such-parcel"))

    def test_a_number_with_the_wrong_number_of_digits_is_a_400(self):
        e = self.problem(self.app, "GET", PATH, q("12"))
        self.assertEqual((e.status, e.code), (400, "bad-request"))
        self.assertIn("not a parcel number", e.message)

    def test_thirteen_parcels_are_too_many(self):
        e = self.problem(self.app, "GET", PATH, q(*[f"3600000{i:02d}" for i in range(13)]))
        self.assertEqual((e.status, e.code), (400, "bad-request"))
        self.assertIn("12", e.message)

    def test_a_city_whose_parcel_records_are_silent_is_a_502_that_names_it(self):
        self.city.down.add("parcel")
        e = self.problem(self.app, "GET", PATH, q("100000001"))
        self.assertEqual((e.status, e.code), (502, "source-down"))
        self.assertIn("Tinytown", e.message)

    def test_a_city_that_has_nothing_for_the_wider_picture_still_answers(self):
        """The base adapter returns None for every part: every block but the checklist is not available."""
        class Bare(Tinytown):
            pass
        self.city = Bare()
        out = self.get(app=self.make_app())
        self.assertEqual(set(out["answered"].values()), {"nothing found there"})
        self.assertEqual(out["economy"], {"available": False, "did_not_answer": list(O.ECONOMY_PARTS)})
        self.assertEqual(out["housing"], {"available": False})
        for block in ("climate", "hazards", "nearby", "resident"):
            self.assertEqual(out[block], {"available": False})
        self.assertEqual(out["todo"]["steps"][0]["who"], "the city's planning department", "its adapter names no place")


# ---------------------------------------------------------------- a part that did not answer

class WhenAPartDoesNotAnswer(OnTown):
    def test_a_silent_place_part_shows_as_did_not_answer_and_its_block_is_not_available_while_the_rest_answer(self):
        for part, block in (("climate", "climate"), ("hazards", "hazards"), ("nearby", "nearby"), ("residents", "resident")):
            with self.subTest(part=part):
                self.setUp()
                self.city.silence(part)
                out = self.get()
                self.assertEqual(out["answered"][part], "did not answer")
                self.assertIsNone(out["fetched"][part])
                self.assertEqual(out[block], {"available": False})
                self.assertEqual({p: s for p, s in out["answered"].items() if p != part}, {p: "ok" for p in ALL_PARTS if p != part})
                self.assertTrue(all(out[b]["available"] for b in ("economy", "climate", "hazards", "nearby", "resident") if b != block))
                self.assertTrue(out["todo"]["steps"])

    def test_one_silent_economy_part_is_named_in_the_economy_block_and_the_rest_of_it_answers(self):
        for part in O.ECONOMY_PARTS:
            with self.subTest(part=part):
                self.setUp()
                self.city.silence(part)
                out = self.get()
                self.assertEqual(out["answered"][part], "did not answer")
                self.assertTrue(out["economy"]["available"])
                self.assertEqual(out["economy"]["did_not_answer"], [part])
                self.assertFalse(out["economy"]["sources"][O.ECONOMY_PARTS.index(part)]["answered"])
                self.assertTrue(all(out[b]["available"] for b in ("climate", "hazards", "nearby", "resident")))

    def test_a_silent_housing_part_is_a_block_that_is_not_available_and_the_other_blocks_still_answer(self):
        self.city.silence("housing")
        out = self.get()
        self.assertEqual(out["housing"], {"available": False})
        self.assertEqual(out["answered"]["housing"], "did not answer")
        self.assertIsNone(out["fetched"]["housing"])
        self.assertEqual({p: s for p, s in out["answered"].items() if p != "housing"}, {p: "ok" for p in ALL_PARTS if p != "housing"})
        self.assertTrue(all(out[b]["available"] for b in ("economy", "climate", "hazards", "nearby", "resident")))
        self.assertEqual(out["economy"]["did_not_answer"], [], "housing is not one of the economy's own parts")
        self.assertNotIn("Ask how the homes would count toward the city's state housing target", [s["what"] for s in out["todo"]["steps"]])
        self.assertTrue(out["todo"]["steps"])

    def test_a_housing_reader_that_is_silent_is_said_to_be_silent_and_nothing_is_logged(self):
        self.city.silence("housing")
        with self.assertNoLogs("landplanner", "WARNING"):
            out = self.get()
        self.assertEqual((out["housing"], out["answered"]["housing"]), ({"available": False}, "did not answer"))

    def test_a_housing_answer_that_could_not_be_read_is_said_so_and_logged_and_the_rest_answers(self):
        for error in (KeyError("x"), TypeError("x"), ValueError("x"), AttributeError("x")):
            with self.subTest(error=type(error).__name__):
                self.setUp()
                self.city.silence("housing", error=error)
                with self.assertLogs("landplanner", "WARNING") as logs:
                    out = self.get()
                self.assertEqual((out["housing"], out["answered"]["housing"]), ({"available": False}, "could not be read"))
                self.assertTrue(any("housing" in r.getMessage() for r in logs.records))
                self.assertTrue(all(out[b]["available"] for b in ("economy", "climate", "hazards", "nearby", "resident")))

    def test_a_housing_answer_without_a_target_is_a_block_that_is_not_available_and_the_rest_answers(self):
        self.city.economy["housing"]["target"]["total"] = 0
        out = self.get()
        self.assertEqual(out["housing"], {"available": False})
        self.assertEqual(out["answered"]["housing"], "ok", "the town answered; what it said had nothing to count")
        self.assertTrue(all(out[b]["available"] for b in ("economy", "climate", "hazards", "nearby", "resident")))

    def test_the_housing_step_is_on_the_checklist_when_the_town_answers(self):
        out = self.get()
        step = next((s for s in out["todo"]["steps"] if s["what"] == "Ask how the homes would count toward the city's state housing target"), None)
        if step is not None:                                  # the made-up town's plan may hold no homes
            self.assertIn("still has to permit 140 homes", step["why"])
            self.assertEqual(step["who"], "Tinytown Planning Office")

    def test_every_economy_part_silent_is_a_block_that_is_not_available_and_has_no_numbers(self):
        self.city.silence(*O.ECONOMY_PARTS)
        out = self.get()
        self.assertEqual(out["economy"], {"available": False, "did_not_answer": list(O.ECONOMY_PARTS)})
        self.assertTrue(all(out["answered"][p] == "did not answer" for p in O.ECONOMY_PARTS))
        self.assertTrue(all(out[b]["available"] for b in ("climate", "hazards", "nearby", "resident")))

    def test_every_part_silent_still_answers_with_the_checklist(self):
        self.city.silence(*ALL_PARTS)
        out = self.get()
        self.assertEqual(set(out["answered"].values()), {"did not answer"})
        self.assertEqual(set(out["fetched"].values()), {None})
        self.assertFalse(any(out[b]["available"] for b in ("economy", "housing", "climate", "hazards", "nearby", "resident")))
        self.assertTrue(out["todo"]["steps"])
        json.dumps(out, allow_nan=False)

    def test_every_kind_of_error_a_service_may_give_is_a_part_that_did_not_answer(self):
        for error in (KeyError("x"), TypeError("x"), ValueError("x"), IndexError("x"), AttributeError("x")):
            with self.subTest(error=type(error).__name__):
                self.setUp()
                self.city.silence("climate", "sales", error=error)
                with self.assertLogs("landplanner", "WARNING"):
                    out = self.get()
                # the page stays up, and says the answer could not be read: it is not passed off as a silent service
                self.assertEqual((out["answered"]["climate"], out["answered"]["sales"]), ("could not be read", "could not be read"))
                self.assertEqual(out["climate"], {"available": False})

    def test_a_service_that_is_silent_is_said_to_be_silent_and_nothing_is_logged(self):
        self.city.silence("climate", "sales")
        with self.assertNoLogs("landplanner", "WARNING"):
            out = self.get()
        self.assertEqual((out["answered"]["climate"], out["answered"]["sales"]), ("did not answer", "did not answer"))

    # a mistake in the code that reads a source used to look exactly like a service that was down, with no trace anywhere
    def test_an_answer_that_could_not_be_read_is_logged_with_its_part_and_where_it_happened(self):
        self.city.silence("climate", error=AttributeError("'NoneType' object has no attribute 'get'"))
        with self.assertLogs("landplanner", "WARNING") as logs:
            self.get()
        record = [r for r in logs.records if "climate" in r.getMessage()][0]
        self.assertIn("AttributeError", record.getMessage())
        self.assertIsNotNone(record.exc_info, "the log carries the traceback")

    def test_an_answer_that_could_not_be_read_keeps_saying_so_within_the_minute(self):
        self.city.silence("climate", error=TypeError("x"))
        with self.assertLogs("landplanner", "WARNING"):
            self.get()
        asked = self.city.asked("climate")
        out = self.get()
        self.assertEqual(self.city.asked("climate"), asked, "not asked again within the minute")
        self.assertEqual(out["answered"]["climate"], "could not be read")

    def test_an_older_copy_given_after_an_unreadable_answer_is_logged_too(self):
        self.get()
        self.clock.now += PART_TTL + DAY
        self.city.silence("climate", error=KeyError("x"))
        with self.assertLogs("landplanner", "WARNING"):
            out = self.get()
        self.assertEqual(out["answered"]["climate"], "older copy")

    # a reply cut short (http.client.IncompleteRead) is neither an OSError nor one of the planner's DOWN errors: sources/fetch.py must
    # turn it into a SourceError, so it is one part that did not answer and not a failure of the whole outlook
    def test_a_reply_cut_short_is_one_part_that_did_not_answer_not_a_failure_of_the_whole_outlook(self):
        real = self.city.outlook_part

        def ask(part, parcel, tracts=None):
            if part == "climate":
                return fetch.get_bytes("https://example.test/climate", tries=1)
            return real(part, parcel, tracts)

        cut = mock.MagicMock()
        cut.__enter__.return_value.read.side_effect = http.client.IncompleteRead(b"partial")
        with mock.patch.object(self.city, "outlook_part", ask), mock.patch("urllib.request.urlopen", return_value=cut),                 mock.patch("time.sleep"):
            out = self.get()
        self.assertEqual(out["answered"]["climate"], "did not answer")
        self.assertEqual(out["climate"], {"available": False})
        self.assertEqual(out["answered"]["hazards"], "ok", "the other parts answer")

    def test_a_part_with_nothing_there_is_nothing_found_and_not_a_failure(self):
        self.city.here["nearby"] = None
        self.city.economy["work"] = {}
        out = self.get()
        self.assertEqual((out["answered"]["nearby"], out["answered"]["work"]), ("nothing found there", "nothing found there"))
        self.assertEqual(out["nearby"], {"available": False})
        self.assertEqual(out["economy"]["did_not_answer"], ["work"])

    def test_the_failed_part_is_not_asked_again_within_a_minute_but_is_after_it(self):
        self.city.silence("climate")
        self.get()
        self.assertEqual(self.city.asked("climate"), 1)
        self.get()
        self.assertEqual(self.city.asked("climate"), 1, "not asked again at once")
        self.clock.now += RETRY_AFTER - 1
        out = self.get()
        self.assertEqual(self.city.asked("climate"), 1, "not asked again within the minute")
        self.assertEqual(out["answered"]["climate"], "did not answer")
        self.assertEqual(out["climate"], {"available": False})
        self.clock.now += 2
        self.city.silent.clear()
        out = self.get()
        self.assertEqual(self.city.asked("climate"), 2, "asked again after the minute")
        self.assertEqual(out["answered"]["climate"], "ok")
        self.assertTrue(out["climate"]["available"])

    def test_after_the_minute_a_part_that_is_still_silent_is_asked_and_waits_another_minute(self):
        self.city.silence("hazards")
        self.get()
        self.clock.now += RETRY_AFTER + 1
        self.get()
        self.assertEqual(self.city.asked("hazards"), 2)
        self.get()
        self.assertEqual(self.city.asked("hazards"), 2)
        self.clock.now += RETRY_AFTER - 1
        self.get()
        self.assertEqual(self.city.asked("hazards"), 2, "the minute counts from the last failure")
        self.clock.now += 2
        self.get()
        self.assertEqual(self.city.asked("hazards"), 3)

    def test_the_silent_part_does_not_keep_the_other_parts_from_being_kept(self):
        self.city.silence("climate")
        self.get()
        self.get()
        for part in ALL_PARTS:
            if part != "climate":
                self.assertEqual(self.city.asked(part), 1, part)

    def test_fresh_asks_a_silent_part_again_even_within_the_minute(self):
        self.city.silence("climate")
        self.get()
        out = self.get(fresh=1)
        self.assertEqual(self.city.asked("climate"), 2)
        self.assertEqual(out["answered"]["climate"], "did not answer")

    def test_a_kept_copy_is_still_served_when_the_source_is_silent_after_it_has_aged(self):
        self.get()
        self.clock.now += PART_TTL + DAY
        self.city.silence("climate")
        out = self.get()
        self.assertEqual(self.city.asked("climate"), 2, "the aged copy is asked for again")
        self.assertTrue(out["climate"]["available"], "and the old copy is better than nothing")
        self.assertEqual(out["answered"]["climate"], "older copy", "and it is not passed off as a fresh answer")
        self.assertEqual(out["fetched"]["climate"], float(NOW), "the answer says when the copy was made, not now")

    # the cache hands back the aged copy when the source raises; the failure used to go unnoticed, so with an aged copy the silent
    # source was asked on every request (4 asks for 1 + 3 requests) instead of once a minute
    def test_a_silent_source_with_an_aged_copy_is_not_asked_again_within_a_minute(self):
        self.get()
        self.clock.now += PART_TTL + DAY
        self.city.silence("climate")
        self.get()
        asked = self.city.asked("climate")
        self.get()
        self.get()
        self.assertEqual(self.city.asked("climate"), asked)
        self.clock.now += RETRY_AFTER + 1
        out = self.get()
        self.assertEqual(self.city.asked("climate"), asked + 1, "asked again after the minute")
        self.assertEqual(out["answered"]["climate"], "older copy", "and the old copy still serves meanwhile")
        self.city.silent.clear()
        self.clock.now += RETRY_AFTER + 1
        self.assertEqual(self.get()["answered"]["climate"], "ok", "once the source answers again, it is a fresh answer")


# ---------------------------------------------------------------- kept copies

class TheKeptCopies(OnTown):
    def test_a_second_call_uses_the_kept_copies_and_asks_nothing_of_the_city(self):
        first = self.get()
        economy_before, here_before = list(self.city.economy_calls), list(self.city.here_calls)
        again = self.get()
        self.assertEqual((self.city.economy_calls, self.city.here_calls), (economy_before, here_before))
        for block in BLOCKS:
            self.assertEqual(again[block], first[block], block)
        self.assertEqual(again["fetched"], first["fetched"])

    def test_each_part_is_asked_once_for_the_first_answer_the_population_too(self):
        self.get()
        self.assertEqual(sorted(p for p, _ in self.city.economy_calls), sorted(O.CITY_PARTS), "the forecast and the outlook share the city's homes")
        self.assertEqual(self.city.asked("housing"), 1)
        self.assertEqual(sorted(p for p, _, _ in self.city.here_calls), sorted(O.PLACE_PARTS))

    def test_the_housing_part_is_asked_once_and_the_kept_copy_is_reused(self):
        first = self.get()
        self.assertEqual(self.city.asked("housing"), 1)
        for _ in range(3):
            again = self.get()
        self.assertEqual(self.city.asked("housing"), 1)
        self.assertEqual(again["housing"], first["housing"])
        self.assertEqual(again["fetched"]["housing"], first["fetched"]["housing"])

    def test_the_housing_part_is_asked_with_the_year_of_the_clock_and_again_with_fresh(self):
        self.get()
        self.get(fresh=1)
        self.assertEqual([c for c in self.city.economy_calls if c[0] == "housing"], [("housing", 2026), ("housing", 2026)])

    def test_a_new_housing_answer_after_fresh_is_the_one_kept(self):
        self.get()
        self.city.economy["housing"]["target"]["total"] = 500
        self.assertEqual(self.get()["housing"]["target"], 400, "kept")
        self.assertEqual(self.get(fresh=1)["housing"]["target"], 500)
        self.assertEqual(self.get()["housing"]["target"], 500)

    def test_the_housing_part_is_kept_with_the_cities_figures_for_14_days(self):
        self.get()
        self.clock.now += 8 * DAY
        self.get()
        self.assertEqual(self.city.asked("housing"), 1, "kept as long as the economy parts, not as long as the site's parts")
        self.clock.now += 7 * DAY
        self.get()
        self.assertEqual(self.city.asked("housing"), 2)

    def test_a_silent_housing_part_is_asked_again_only_once_a_minute(self):
        self.city.silence("housing")
        self.get()
        self.get()
        self.assertEqual(self.city.asked("housing"), 1)
        self.clock.now += RETRY_AFTER + 1
        self.get()
        self.assertEqual(self.city.asked("housing"), 2)

    def test_fresh_asks_every_part_again(self):
        self.get()
        out = self.get(fresh=1)
        for part in ALL_PARTS:
            self.assertEqual(self.city.asked(part), 2, part)
        self.assertEqual(set(out["answered"].values()), {"ok"})

    def test_fresh_takes_the_words_the_page_sends(self):
        self.get()
        for i, word in enumerate(("1", "true", "yes", "on", "TRUE"), 2):
            with self.subTest(word=word):
                self.get(fresh=word)
                self.assertEqual(self.city.asked("climate"), i)
        for word in ("0", "no", "", "false"):
            with self.subTest(word=word):
                before = self.city.asked("climate")
                self.get(fresh=word)
                self.assertEqual(self.city.asked("climate"), before)

    def test_fresh_gives_the_new_answer_and_the_new_time(self):
        self.get()
        self.clock.now += 3 * DAY
        self.city.here["climate"]["typical_year"]["mean_f"] = 70.0
        out = self.get(fresh=1)
        self.assertEqual(out["climate"]["typical_year"]["mean_f"], 70.0)
        self.assertEqual(out["fetched"]["climate"], float(NOW + 3 * DAY))
        self.assertEqual(self.get()["climate"]["typical_year"]["mean_f"], 70.0, "and the new copy is the one kept")

    def test_the_cities_figures_are_kept_14_days_and_the_facts_around_the_site_7(self):
        self.get()
        self.clock.now += 8 * DAY
        self.get()
        self.assertEqual({p: self.city.asked(p) for p in O.PLACE_PARTS}, {p: 2 for p in O.PLACE_PARTS}, "7 days: asked again at 8")
        self.assertEqual({p: self.city.asked(p) for p in O.CITY_PARTS}, {p: 1 for p in O.CITY_PARTS}, "14 days: not yet")
        self.clock.now += 7 * DAY
        self.get()
        self.assertEqual({p: self.city.asked(p) for p in O.CITY_PARTS}, {p: 2 for p in O.CITY_PARTS}, "15 days: asked again")
        self.assertEqual((ECONOMY_TTL, PART_TTL), (14 * DAY, 7 * DAY))

    def test_the_kept_copies_survive_a_restart(self):
        first = self.get()
        again = self.make_app()
        out = self.get(app=again)
        self.assertEqual(sum(1 for _ in self.city.economy_calls + self.city.here_calls), len(ALL_PARTS), "nothing was asked a second time")
        for block in BLOCKS:
            self.assertEqual(out[block], first[block], block)

    def test_the_citys_figures_are_kept_for_the_city_and_the_rest_for_the_site(self):
        self.get()
        keys = {json.loads(p.read_text(encoding="utf-8"))["key"] for p in (Path(self.folder.name) / "cache").glob("*.json")}
        for part in O.CITY_PARTS:
            self.assertIn(f"tinytown/economy/{part}", keys)
        for part in O.PLACE_PARTS:
            self.assertIn(f"tinytown/site/100000001/outlook-{part}", keys)

    def test_another_site_in_the_same_city_asks_for_the_site_parts_only(self):
        self.get("100000001")
        self.get("100000002")
        for part in O.CITY_PARTS:
            self.assertEqual(self.city.asked(part), 1, part)
        self.assertEqual([(p, apn) for p, apn, _ in self.city.here_calls].count(("climate", "100000002")), 1)
        self.assertEqual({apn for _, apn, _ in self.city.here_calls}, {"100000001", "100000002"})

    def test_a_failed_part_is_kept_apart_for_each_site(self):
        self.city.silence("climate")
        self.get("100000001")
        self.get("100000002")
        self.assertEqual(self.city.asked("climate"), 2)

    def test_a_silent_economy_part_is_asked_again_by_the_forecast_and_the_outlook_only_once_a_minute(self):
        self.city.silence("population")
        self.get()
        self.assertEqual(self.city.asked("population"), 1, "the forecast asked; the outlook found it failed a moment ago")
        self.get()
        self.assertEqual(self.city.asked("population"), 1)


# ---------------------------------------------------------------- several parcels as one site

class SeveralParcelsAsOneSite(OnTown):
    def make_town(self):
        from test_forecast_routes import HAUN
        self.haun = HAUN
        return TownOfLots(apns=HAUN)

    def test_four_lots_are_one_site_and_the_site_parts_are_read_once_for_a_stand_in_parcel(self):
        out = self.get(*self.haun)
        self.assertEqual(out["apns"], list(self.haun))
        self.assertEqual({apn for _, apn, _ in self.city.here_calls}.__len__(), 1)
        stand_in = self.city.here_calls[0][1]
        self.assertRegex(stand_in, r"^site-[0-9a-f]{12}$")
        self.assertEqual(sorted(p for p, _, _ in self.city.here_calls), sorted(O.PLACE_PARTS))
        self.assertEqual(set(out["answered"].values()), {"ok"})
        self.assertTrue(all(out[b]["available"] for b in ("economy", "climate", "hazards", "nearby", "resident")))

    def test_the_checklist_is_for_the_whole_site(self):
        out = self.get(*self.haun)
        first = out["todo"]["steps"][0]
        self.assertEqual(first["why"], "To hear early what the city will ask for on these 40.4 acres.")

    def test_the_order_and_the_spelling_of_the_parcels_do_not_matter(self):
        a = self.get(*self.haun)
        self.setUp()
        b = self.get(*reversed(self.haun))
        self.assertEqual(a["todo"], b["todo"])
        self.assertEqual({apn for _, apn, _ in self.city.here_calls}.__len__(), 1)

    def test_a_different_set_of_lots_is_a_different_site_with_its_own_kept_copies(self):
        self.get(*self.haun)
        self.get(*self.haun[:3])
        self.assertEqual(self.city.asked("climate"), 2)
        self.assertEqual({apn for _, apn, _ in self.city.here_calls}.__len__(), 2)

    def test_one_lot_alone_is_read_for_itself(self):
        self.get(self.haun[0])
        self.assertEqual({apn for _, apn, _ in self.city.here_calls}, {self.haun[0]})

    def test_the_same_lot_given_twice_is_one_lot(self):
        out = self.get(self.haun[0], self.haun[0])
        self.assertEqual(out["apns"], [self.haun[0]])
        self.assertEqual({apn for _, apn, _ in self.city.here_calls}, {self.haun[0]})

    def test_twelve_lots_are_allowed(self):
        apns = [f"3603500{i:02d}" for i in range(12)]
        self.city = TownOfLots(apns=apns)
        out = self.get(*apns, app=self.make_app())
        self.assertEqual(len(out["apns"]), 12)

    def test_lots_far_apart_are_asked_about_at_the_point_between_them(self):
        apns = ("360350001", "360350002")
        self.city = TownOfLots(apns=apns)
        from test_forecast_routes import lot, LAT0
        self.city.rows[1] = lot("360350002", 0, north=LAT0 + 0.03)
        out = self.get(*apns, app=self.make_app())
        self.assertEqual({apn for _, apn, _ in self.city.here_calls}.__len__(), 1)
        self.assertRegex(self.city.here_calls[0][1], r"^site-[0-9a-f]{12}$")
        self.assertTrue(out["todo"]["steps"])


class TownOfLots(Town):
    """The made-up town with lots stacked along one road (the forecast tests' Block), and the wider picture's answers."""

    def __init__(self, apns):
        super().__init__()
        from test_forecast_routes import lot
        self.rows = [lot(a, i, "R-1") for i, a in enumerate(apns)]

    def zoning_kind(self, code):
        return {"R-1": "low-density", "C-1": "commercial"}.get(str(code or ""), "other")


# ---------------------------------------------------------------- the residents part and the market ring

class TheResidentsPartIsAskedWithTheTractsInTheMarketRing(OnTown):
    def make_town(self):
        return Town(tracts=survey(
            tract("A", 1000, {"1": 1.0, "3": 1.0, "5": 1.0}),
            tract("B", 2000, {"1": 0.0, "3": 0.4, "5": 1.0}),
            tract("C", 3000, {"1": 0.0, "3": 0.0, "5": 0.5}),             # only in the 5 mile ring
            tract("D", 4000, None),                                       # no figure for any distance
            tract("E", 5000, {"1": 0.0, "5": 1.0}),                       # no figure for the 3 mile ring
            tract("", 6000, {"3": 1.0}),                                  # no name
            tract(None, 7000, {"3": 1.0}),
            tract("F", None, {"3": 0.25})))                               # no household count

    def tracts_sent(self):
        asked = [t for p, _, t in self.city.here_calls if p == "residents"]
        self.assertEqual(len(asked), 1)
        return asked[0]

    def test_only_the_tracts_that_lie_in_the_ring_are_sent_with_their_share(self):
        out = self.get()
        self.assertEqual(self.tracts_sent(), [{"id": "A", "households": 1000, "share": 1.0}, {"id": "B", "households": 2000, "share": 0.4},
                                              {"id": "F", "households": None, "share": 0.25}])
        self.assertEqual(out["answered"]["residents"], "ok")

    def test_the_ring_is_the_market_ring_of_the_forecast(self):
        from landplanner import forecast as F
        self.assertEqual(F.MARKET_MILES, 3)

    def test_numbers_or_text_as_the_distance_keys_both_work(self):
        self.city.survey = survey(tract("A", 1000, {1: 0.5, 3: 0.75, 5: 1.0}), tract("B", 2000, {"3": 0.1}), tract("C", 3000, {3: 0.0, "3": 0.9}))
        self.get()
        self.assertEqual(self.tracts_sent(), [{"id": "A", "households": 1000, "share": 0.75}, {"id": "B", "households": 2000, "share": 0.1},
                                              {"id": "C", "households": 3000, "share": 0.9}])

    def test_the_same_tracts_are_sent_after_the_survey_has_been_kept_on_disk_and_read_back(self):
        self.get()
        first = self.tracts_sent()
        again = self.make_app()                      # the kept survey now has text keys, whatever it had when it was first read
        self.get(app=again, fresh=1)
        sent = [t for p, _, t in self.city.here_calls if p == "residents"]
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[1], first)

    def test_with_no_survey_the_part_is_asked_with_no_tracts(self):
        self.city.survey = None
        self.get()
        self.assertEqual(self.tracts_sent(), [])

    def test_with_no_tract_in_the_ring_the_part_is_asked_with_no_tracts(self):
        self.city.survey = survey(tract("C", 3000, {"1": 0.0, "3": 0.0, "5": 0.5}), tract("D", 4000, {}))
        self.get()
        self.assertEqual(self.tracts_sent(), [])

    def test_a_silent_survey_means_no_tracts_and_a_residents_block_the_city_may_still_answer(self):
        self.city.down.add("tracts")
        out = self.get()
        self.assertEqual(self.tracts_sent(), [])
        self.assertIn("residents", out["answered"])

    def test_the_part_gets_the_site_parcel_to_read_around(self):
        self.get()
        self.assertEqual({apn for p, apn, _ in self.city.here_calls}, {"100000001"})


# ---------------------------------------------------------------- the city adapters

class TheBaseAdapter(unittest.TestCase):
    def test_a_city_with_nothing_for_the_wider_picture_returns_none_for_every_part(self):
        city = Tinytown()
        for part in O.ECONOMY_PARTS + ("nonsense",):
            self.assertIsNone(city.economy_part(part, 2026), part)
        for part in O.PLACE_PARTS + ("nonsense",):
            self.assertIsNone(city.outlook_part(part, {"apn": "1", "centre": {"lon": 0, "lat": 0}}), part)
            self.assertIsNone(city.outlook_part(part, {"apn": "1"}, [{"id": "x", "households": 1, "share": 1}]), part)

    def test_it_names_no_one_to_see(self):
        self.assertEqual(CityAdapter.place, {})
        self.assertEqual(Tinytown.place, {})

    def test_the_parts_the_engine_reads_are_the_parts_the_adapter_is_asked_for(self):
        self.assertEqual(O.ECONOMY_PARTS, ("population", "permits", "sales", "work", "borrowing", "prices"))
        self.assertEqual(O.CITY_PARTS, O.ECONOMY_PARTS + ("housing",))
        self.assertEqual(O.PLACE_PARTS, ("climate", "hazards", "nearby", "residents"))


class Recorder:
    """A stand-in for one of the state or national readers: it notes how it was asked and answers with a marker."""

    def __init__(self):
        self.calls = []

    def reader(self, name):
        def read(*args, **kw):
            self.calls.append((name, args, kw))
            return {"read": name}
        return read


class TheMenifeeAdapter(unittest.TestCase):
    PARCEL = {"apn": "1", "centre": {"lon": -117.165, "lat": 33.655},
              "outline": {"type": "Polygon", "coordinates": [[[-117.17, 33.65], [-117.16, 33.65], [-117.16, 33.66], [-117.17, 33.66], [-117.17, 33.65]]]}}

    def setUp(self):
        self.rec = Recorder()
        for module, names in ((economy_source, ("population_by_year", "permits_by_year", "shop_sales_by_year", "work_by_year", "mortgage_rates",
                                                 "prices_by_year")), (place_source, ("climate", "hazards", "nearby", "residents"))):
            for name in names:
                patcher = mock.patch.object(module, name, self.rec.reader(name))
                patcher.start()
                self.addCleanup(patcher.stop)
        self.city = Menifee()

    def asked(self):
        out, self.rec.calls = self.rec.calls, []
        return out

    def test_it_names_who_to_see(self):
        self.assertEqual(self.city.place["name"], "Menifee")
        self.assertIn("Planning", self.city.place["planning"])
        self.assertTrue(self.city.place["water"])

    def test_each_economy_part_is_read_from_its_own_source_for_menifee(self):
        year = 2026
        for part, want in (("population", ("population_by_year", ("Menifee", 2026, "Riverside"))),
                           ("permits", ("permits_by_year", ("46842", 2018, 2025))),
                           ("sales", ("shop_sales_by_year", ("Menifee",))),
                           ("work", ("work_by_year", ("Menifee", "Riverside"))),
                           ("borrowing", ("mortgage_rates", ())),
                           ("prices", ("prices_by_year", (2017,)))):
            with self.subTest(part=part):
                self.assertEqual(self.city.economy_part(part, year), {"read": want[0]})
                self.assertEqual(self.asked(), [(want[0], want[1], {})])

    def test_the_years_asked_for_follow_the_year_given(self):
        self.city.economy_part("permits", 2031)
        self.city.economy_part("prices", 2031)
        self.city.economy_part("population", 2031)
        self.assertEqual([(n, a) for n, a, _ in self.asked()], [("permits_by_year", ("46842", 2023, 2030)), ("prices_by_year", (2022,)),
                                                                   ("population_by_year", ("Menifee", 2031, "Riverside"))])

    def test_an_unknown_economy_part_is_none_and_asks_nothing(self):
        for part in ("nonsense", "", None, "Population"):
            with self.subTest(part=part):
                self.assertIsNone(self.city.economy_part(part, 2026))
        self.assertEqual(self.asked(), [])

    def test_climate_and_nearby_are_read_at_the_parcels_centre(self):
        self.assertEqual(self.city.outlook_part("climate", self.PARCEL), {"read": "climate"})
        self.assertEqual(self.city.outlook_part("nearby", self.PARCEL), {"read": "nearby"})
        self.assertEqual(self.asked(), [("climate", (-117.165, 33.655), {}), ("nearby", (-117.165, 33.655), THE_CITYS_OWN_MAPS)])

    def test_hazards_are_read_at_the_centre_and_over_the_box_round_the_outline(self):
        self.assertEqual(self.city.outlook_part("hazards", self.PARCEL), {"read": "hazards"})
        self.assertEqual(self.asked(), [("hazards", (-117.165, 33.655, (-117.17, 33.65, -117.16, 33.66)), THE_CITYS_OWN_MAPS)])

    def test_the_box_takes_every_ring_of_the_outline(self):
        parcel = dict(self.PARCEL, outline={"coordinates": [[[0.0, 1.0], [2.0, 3.0]], [[-4.0, -5.0], [6.0, 7.0]]]})
        self.city.outlook_part("hazards", parcel)
        self.assertEqual(self.asked()[0][1][2], (-4.0, -5.0, 6.0, 7.0))

    def test_hazards_with_no_outline_are_read_without_a_box(self):
        for outline in (None, {}, {"coordinates": []}, {"coordinates": None}):
            with self.subTest(outline=outline):
                parcel = {"apn": "1", "centre": self.PARCEL["centre"], "outline": outline}
                self.city.outlook_part("hazards", parcel)
                self.assertEqual(self.asked(), [("hazards", (-117.165, 33.655, None), THE_CITYS_OWN_MAPS)])
        parcel = {"apn": "1", "centre": self.PARCEL["centre"]}
        self.city.outlook_part("hazards", parcel)
        self.assertEqual(self.asked(), [("hazards", (-117.165, 33.655, None), THE_CITYS_OWN_MAPS)])

    def test_residents_are_read_for_the_tracts_given_and_not_at_all_without_any(self):
        tracts = [{"id": "06065042739", "households": 2356, "share": 1.0}]
        self.assertEqual(self.city.outlook_part("residents", self.PARCEL, tracts), {"read": "residents"})
        self.assertEqual(self.asked(), [("residents", (tracts,), {})])
        # without tracts the census did not answer: that is a silent source (retried next time), not an empty
        # answer to keep for a week
        for none in (None, []):
            with self.subTest(tracts=none):
                with self.assertRaises(SourceError):
                    self.city.outlook_part("residents", self.PARCEL, none)
        with self.assertRaises(SourceError):
            self.city.outlook_part("residents", self.PARCEL)
        self.assertEqual(self.asked(), [])

    def test_an_unknown_place_part_is_none_and_asks_nothing(self):
        for part in ("nonsense", "", None, "Climate"):
            with self.subTest(part=part):
                self.assertIsNone(self.city.outlook_part(part, self.PARCEL, [{"id": "x"}]))
        self.assertEqual(self.asked(), [])

    def test_an_error_from_a_reader_comes_out_as_it_went_in(self):
        with mock.patch.object(place_source, "climate", side_effect=SourceError("(test) down")):
            with self.assertRaises(SourceError):
                self.city.outlook_part("climate", self.PARCEL)


# ---------------------------------------------------------------- the recorded Menifee example

class OnMenifee(unittest.TestCase):
    """The recorded example parcel through the real forecast, with the wider picture's two adapter methods replaced."""
    PATH = "/api/cities/menifee/outlook"

    def setUp(self):
        sleeper = mock.patch.object(support.tool.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)
        patcher = forecast_routes.offline()
        self.replay = patcher.start()
        self.addCleanup(patcher.stop)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        forecast_routes.copy_of_warm_cache(self.folder.name)
        self.economy_calls, self.here_calls = [], []

        def economy_part(adapter, part, year):
            self.economy_calls.append((part, year))
            return copy.deepcopy(made_up_economy().get(part))

        def outlook_part(adapter, part, parcel, tracts=None):
            self.here_calls.append((part, parcel["apn"], copy.deepcopy(tracts), parcel))
            return copy.deepcopy(made_up_place().get(part))

        for name, fake in (("economy_part", economy_part), ("outlook_part", outlook_part)):
            patcher = mock.patch.object(Menifee, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = LandPlanner({"menifee": Menifee()}, self.folder.name, clock=Clock(forecast_routes.NOW))

    def get(self, **more):
        status, out = route(self.app, "GET", self.PATH, q(EXAMPLE, **more))
        self.assertEqual(status, 200)
        return out

    def test_the_example_parcel_has_all_seven_blocks(self):
        out = self.get()
        self.assertEqual((out["city"], out["city_name"], out["apns"], out["year"]), ("menifee", "Menifee", [EXAMPLE], 2026))
        self.assertEqual(set(out["answered"]), set(ALL_PARTS))
        self.assertEqual(set(out["answered"].values()), {"ok"})
        self.assertTrue(all(out[b]["available"] for b in ("economy", "housing", "climate", "hazards", "nearby", "resident")))
        self.assertTrue(out["todo"]["steps"])
        self.assertTrue(out["economy"]["facts"][0].startswith("Menifee had 1,000 people in 2020"))
        self.assertTrue(out["housing"]["facts"][0].startswith("The state requires Menifee to plan for 400 new homes"))
        json.dumps(out, allow_nan=False)

    def test_the_economy_grows_with_the_homes_of_the_forecast_ring(self):
        out = self.get()
        self.assertTrue(out["economy"]["sales_ahead"], "the example's forecast has rings, so the shop sales can be carried forward")
        self.assertEqual([a["year"] for a in out["economy"]["sales_ahead"]], list(range(2027, 2037)))
        self.assertIn("miles. Today's prices; no inflation added.", out["economy"]["sales_ahead_basis"])

    def test_the_residents_part_is_asked_with_only_the_real_tracts_in_the_market_ring(self):
        self.get()
        asked = [t for p, _, t, _ in self.here_calls if p == "residents"]
        self.assertEqual(len(asked), 1)
        survey_part = self.app.cache.peek(f"menifee/site/{EXAMPLE}/tracts")[0]
        every = survey_part["tracts"]
        inside = [t for t in every if (t["share_within"].get("3") or 0) > 0]
        self.assertTrue(0 < len(inside) < len(every), "the recorded survey has tracts both in and out of the ring")
        self.assertEqual([t["id"] for t in asked[0]], [t["id"] for t in inside])
        self.assertEqual([t["share"] for t in asked[0]], [t["share_within"]["3"] for t in inside])
        self.assertEqual([t["households"] for t in asked[0]], [t["households"] for t in inside])
        self.assertTrue(all(t["share"] > 0 for t in asked[0]))

    def test_the_place_parts_are_read_for_the_parcel_itself(self):
        self.get()
        self.assertEqual({apn for _, apn, _, _ in self.here_calls}, {EXAMPLE})
        parcel = self.here_calls[0][3]
        self.assertIn("outline", parcel)
        self.assertIn("centre", parcel)

    def test_a_second_call_asks_nothing_more_of_the_city_or_the_services(self):
        self.get()
        asked = (len(self.economy_calls), len(self.here_calls), len(self.replay.asked))
        self.get()
        self.assertEqual((len(self.economy_calls), len(self.here_calls), len(self.replay.asked)), asked)

    def test_the_example_does_not_reach_the_network_for_any_part(self):
        self.get(fresh=1)         # the recorded answers raise AssertionError for any question that was not recorded
        self.assertEqual(sorted(p for p, _ in self.economy_calls), sorted(O.CITY_PARTS + ("population",)),
                         "each part once, and the city's homes twice (the forecast asked, then fresh asked again)")


if __name__ == "__main__":
    unittest.main()
