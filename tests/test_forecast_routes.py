"""The year-by-year forecast through LandPlanner.forecast and the server's forecast route: one parcel of the recorded
Menifee example (372-100-001), and several parcels as one site on a made-up town. Nothing here reaches the network: a
question that was never recorded fails the test, and a silent service is simulated with offline(down=[...]).

The first forecast of the example takes about half a second (a planning agency's zones are shared out by area), so it
is worked out once; each test then starts from a copy of what that run saved, as a restarted app would. A test about a
silent service leaves its own part out of the copy so that part is asked for again.
"""
import calendar
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support
from support import EXAMPLE, Clock, Tinytown, row, tool
from landplanner import geometry as G
from landplanner import plan as P
from landplanner.cities import SourceError
from landplanner.cities.menifee import Menifee
from landplanner.sources import economy
from landplanner.planner import LandPlanner, Problem
from landplanner.server import route

NOW = calendar.timegm((2026, 11, 25, 12, 0, 0))
PATH = "/api/cities/menifee/forecast"
KEY = f"menifee/forecast/{EXAMPLE}"
TREND = ("people_before", "regional_plan", "tracts")
_warm = {}


class offline:
    """support.offline() (the recorded answers) and the state's yearly homes by city, which the app reads as a file and not
    through the recorded answers: `population` is what that file says (None: the service does not answer). Works as
    a context manager or with start() and stop(); start() gives the replay, as support.offline() does."""

    def __init__(self, down=(), population=None):
        def population_by_year(place, year, county=None):
            if population is None:
                raise SourceError("(test) the Department of Finance is down")
            return population
        self.patches = [support.offline(down=down), mock.patch.object(economy, "population_by_year", population_by_year)]

    def start(self):
        replay = self.patches[0].start()
        self.patches[1].start()
        return replay

    def stop(self):
        for p in reversed(self.patches):
            p.stop()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


def population_of(by_year, source="Test state estimates"):
    """What the Department of Finance reader answers: one row of homes for each year given as {year: homes}."""
    return {"rows": [{"year": y, "homes": h} for y, h in by_year.items()], "source": source}


def warm_cache():
    """The saved answers after one forecast of the example parcel (worked out once for the whole file)."""
    if "folder" not in _warm:
        _warm["folder"] = tempfile.TemporaryDirectory()
        with offline():
            LandPlanner({"menifee": Menifee()}, _warm["folder"].name, clock=Clock(NOW)).forecast("menifee", [EXAMPLE])
    return Path(_warm["folder"].name) / "cache"


def tearDownModule():
    if "folder" in _warm:
        _warm.pop("folder").cleanup()


def copy_of_warm_cache(into, without=()):
    """A copy of the saved answers, leaving out the site parts named in `without`."""
    shutil.copytree(warm_cache(), Path(into) / "cache")
    for path in (Path(into) / "cache").glob("*.json"):
        key = json.loads(path.read_text(encoding="utf-8"))["key"]
        if any(key.endswith("/" + part) for part in without):
            path.unlink()


def q(*apns):
    return {"apns": [",".join(apns)]}


class OnMenifee(unittest.TestCase):
    """A planner over the recorded Menifee answers on a temporary data folder."""
    down = ()
    cold = ()           # site parts to ask for again even though a copy was saved
    population = None   # what the state's yearly estimates of the city's homes answer (None: silent)

    def setUp(self):
        sleeper = mock.patch.object(tool.time, "sleep")      # the census survey is asked again after a pause when it refuses
        sleeper.start()
        self.addCleanup(sleeper.stop)
        patcher = offline(down=self.down, population=self.population)
        self.replay = patcher.start()
        self.addCleanup(patcher.stop)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        copy_of_warm_cache(self.folder.name, self.cold)
        self.clock = Clock(NOW)
        self.app = self.make_app()
        self.plans_file = Path(self.folder.name) / "plans.json"

    def make_app(self):
        return LandPlanner({"menifee": Menifee()}, self.folder.name, clock=self.clock)

    def saved(self):
        return json.loads(self.plans_file.read_text(encoding="utf-8"))["plans"] if self.plans_file.exists() else {}

    def problem(self, *args, **kw):
        with self.assertRaises(Problem) as caught:
            route(*args, **kw)
        return caught.exception

    def get(self, apns=EXAMPLE):
        status, out = route(self.app, "GET", PATH, q(apns))
        self.assertEqual(status, 200)
        return out


def figure(out, name):
    return next(f for f in out["figures"] if f["id"] == name)


# ---------------------------------------------------------------- the example parcel

class TheForecastForTheExampleParcel(OnMenifee):
    def test_get_gives_a_forecast_with_the_ten_years(self):
        out = self.get()
        self.assertEqual((out["city"], out["city_name"], out["apns"]), ("menifee", "Menifee", [EXAMPLE]))
        self.assertTrue(out["available"])
        self.assertEqual(out["year"], 2026, "this year follows the app's clock")
        self.assertEqual(out["years"], list(range(2025, 2037)))
        self.assertEqual((out["site"]["apns"], out["site"]["acres"], out["site"]["one_plan"], out["site"]["together"]),
                         ([EXAMPLE], 142.1, True, True))
        self.assertEqual(out["site"]["spread_miles"], 0.0)

    def test_every_part_it_started_from_answered(self):
        out = self.get()
        self.assertEqual(set(out["answered"]), set(LandPlanner.FORECAST_PARTS))
        self.assertEqual(set(out["answered"].values()), {"ok"})
        self.assertTrue(all(out["fetched"].values()))
        self.assertTrue(all(s["answered"] for s in out["sources"]))

    def test_the_three_readings_of_growth_are_there_and_the_lines_are_in_order(self):
        out = self.get()
        three = next(r for r in out["rings"] if r["miles"] == 3)
        self.assertEqual([r["id"] for r in three["readings"]], ["measured", "adopted", "draft"])
        rates = three["rates_pct"]
        self.assertLessEqual(rates["low"], rates["expected"])
        self.assertLessEqual(rates["expected"], rates["high"])
        self.assertFalse(three["one_reading"])
        for r in three["rows"]:
            self.assertLessEqual(r["homes"]["low"], r["homes"]["expected"])
            self.assertLessEqual(r["homes"]["expected"], r["homes"]["high"])

    def test_the_sites_own_plan_is_taken_up_year_by_year(self):
        out = self.get()
        self.assertTrue(out["programme"]["available"])
        self.assertEqual(out["programme"]["basis"], "The plan each parcel has on its own Plan page.")
        self.assertAlmostEqual(out["programme"]["acres"], 142.1, delta=0.2)
        for u in out["programme"]["uses"]:
            self.assertEqual(len(u["by_year"]), 10)
            self.assertLessEqual(u["by_year_10"], u["amount"])
            self.assertEqual([r["so_far"] for r in u["by_year"]], sorted(r["so_far"] for r in u["by_year"]))
        self.assertEqual(len(out["programme"]["steps"]), 3)
        self.assertEqual(out["programme"]["not_forecast"], [])

    def test_income_traffic_and_the_citys_project_lists_are_used(self):
        out = self.get()
        self.assertTrue(out["income"]["available"])
        self.assertGreater(out["income"]["typical"], 50000)
        self.assertTrue(out["shops"]["available"])
        self.assertTrue(out["jobs"]["available"])
        self.assertTrue(out["traffic"]["available"])
        self.assertEqual(out["traffic"]["highway"]["route"], "215")
        self.assertGreater(out["homes"]["pipeline"]["projects_counted"], 0)
        self.assertEqual(out["city_forecast"]["name"], "Menifee")

    def test_the_answer_can_be_sent_as_json(self):
        json.dumps(self.get(), allow_nan=False)

    def test_a_fresh_data_folder_has_no_kept_figures_and_asking_keeps_nothing(self):
        out = self.get()
        self.assertFalse(out["kept"])
        self.assertFalse(out["edited"])
        self.assertEqual(Path(out["kept_in"]).resolve(), self.plans_file.resolve())
        self.assertFalse(self.plans_file.exists(), "asking for a forecast writes nothing")
        self.assertEqual(set(f["yours"] for f in out["figures"]), {False})

    def test_a_second_forecast_is_served_from_the_saved_answers(self):
        self.get()
        asked = len(self.replay.asked)
        self.get()
        self.assertEqual(len(self.replay.asked), asked, "nothing is asked of a public service twice in a row")

    def test_the_parcel_number_may_be_written_with_dashes(self):
        self.assertEqual(self.get("372-100-001")["apns"], [EXAMPLE])

    def test_the_year_is_the_year_of_the_clock(self):
        self.clock.now = calendar.timegm((2031, 3, 1, 0, 0, 0))
        out = self.get()
        self.assertEqual((out["year"], out["years"][0], out["years"][-1]), (2031, 2030, 2041))

    def test_the_answer_after_a_restart_is_the_same_as_the_first(self):
        first = self.get()
        again = LandPlanner({"menifee": Menifee()}, self.folder.name, clock=self.clock)
        asked = len(self.replay.asked)
        status, second = route(again, "GET", PATH, q(EXAMPLE))
        self.assertEqual(status, 200)
        self.assertEqual(len(self.replay.asked), asked, "the saved answers on disk were enough")
        for key in ("headline", "income", "rings", "homes", "shops", "jobs", "traffic", "programme", "advice", "limits"):
            self.assertEqual(second[key], first[key], key)

    def test_a_fresh_run_and_a_run_from_the_saved_files_agree(self):
        """The first run holds whole-number keys (a tract's share_within {1: .., 3: ..}); a saved file turns them into text."""
        with offline():
            empty = tempfile.TemporaryDirectory()
            self.addCleanup(empty.cleanup)
            fresh = LandPlanner({"menifee": Menifee()}, empty.name, clock=self.clock).forecast("menifee", [EXAMPLE])
        from_disk = self.get()
        for key in ("income", "headline", "rings", "homes", "shops", "programme"):
            self.assertEqual(fresh[key], from_disk[key], key)


# ---------------------------------------------------------------- the owner's own figures

class KeptFigures(OnMenifee):
    SETTINGS = {"assumptions": {"capture_pct": 50, "spend_pct": 40, "not_a_figure": 3}, "mode": "best", "land_cost": 5}

    def post(self, body=None, apns=EXAMPLE):
        return route(self.app, "POST", PATH, q(apns), body=self.SETTINGS if body is None else body)

    def test_post_keeps_the_owners_figures_and_the_answer_uses_them(self):
        status, out = self.post()
        self.assertEqual(status, 200)
        self.assertTrue(out["kept"])
        self.assertTrue(out["edited"])
        self.assertEqual(out["settings"], {"assumptions": {"capture_pct": 50.0, "spend_pct": 40.0}})
        self.assertEqual((figure(out, "capture_pct")["value"], figure(out, "capture_pct")["yours"]), (50.0, True))
        self.assertEqual((figure(out, "spend_pct")["value"], figure(out, "spend_pct")["yours"]), (40.0, True))
        self.assertFalse(figure(out, "local_pct")["yours"])
        self.assertEqual(Path(out["kept_in"]).resolve(), self.plans_file.resolve())

    def test_a_later_get_returns_them(self):
        _, posted = self.post()
        status, later = route(self.app, "GET", PATH, q(EXAMPLE))
        self.assertEqual(status, 200)
        self.assertTrue(later["kept"])
        self.assertEqual(later["settings"], posted["settings"])
        self.assertEqual([f["yours"] for f in later["figures"]], [f["yours"] for f in posted["figures"]])
        self.assertEqual(later["programme"], posted["programme"])

    def test_only_what_the_page_may_set_is_kept_and_under_the_forecast_key(self):
        self.post()
        self.assertEqual(self.saved(), {KEY: {"assumptions": {"capture_pct": 50.0, "spend_pct": 40.0}}})

    def test_the_figures_change_the_answer_the_sensible_way(self):
        base = self.get()
        _, mine = self.post({"assumptions": {"capture_pct": 60}})
        for use_id in ("retail", "office", "business", "apartments"):
            a = next(u for u in base["programme"]["uses"] if u["id"] == use_id)
            b = next(u for u in mine["programme"]["uses"] if u["id"] == use_id)
            self.assertGreaterEqual(b["by_year_10"], a["by_year_10"], use_id)
        self.assertGreater(sum(u["by_year_10"] for u in mine["programme"]["uses"]), sum(u["by_year_10"] for u in base["programme"]["uses"]))

    def test_a_figure_outside_its_limits_is_kept_at_the_limit(self):
        _, out = self.post({"assumptions": {"capture_pct": 5000, "ready_years": "-4"}})
        self.assertEqual(self.saved()[KEY]["assumptions"], {"capture_pct": 100.0, "ready_years": 0.0})
        self.assertEqual(figure(out, "capture_pct")["value"], 100.0)

    def test_post_of_only_starting_values_keeps_nothing(self):
        starts = {k: figure(self.get(), k)["start"] for k in ("capture_pct", "spend_pct", "ready_years")}
        status, out = self.post({"assumptions": starts})
        self.assertEqual(status, 200)
        self.assertFalse(out["kept"])
        self.assertFalse(out["edited"])
        self.assertNotIn(KEY, self.saved())

    def test_post_of_starting_values_removes_what_was_kept(self):
        self.post()
        self.assertIn(KEY, self.saved())
        _, out = self.post({"assumptions": {"capture_pct": 20}})
        self.assertFalse(out["kept"])
        self.assertNotIn(KEY, self.saved())
        self.assertFalse(self.get()["kept"])

    def test_post_of_an_empty_dictionary_or_junk_figures_keeps_nothing(self):
        for body in ({}, {"assumptions": {}}, {"assumptions": {"capture_pct": "lots", "nope": 1}}, {"assumptions": "x"}, {"mode": "best"}):
            with self.subTest(body=body):
                _, out = self.post(body)
                self.assertFalse(out["kept"])
        self.assertEqual(self.saved(), {})

    def test_new_figures_replace_the_old_ones_instead_of_adding_to_them(self):
        self.post()
        self.post({"assumptions": {"ready_years": 5}})
        self.assertEqual(self.saved()[KEY], {"assumptions": {"ready_years": 5.0}})

    def test_delete_forgets_them(self):
        self.post()
        status, out = route(self.app, "DELETE", PATH, q(EXAMPLE))
        self.assertEqual(status, 200)
        self.assertFalse(out["kept"])
        self.assertFalse(out["edited"])
        self.assertEqual(figure(out, "capture_pct")["value"], figure(out, "capture_pct")["start"])
        self.assertNotIn(KEY, self.saved())
        self.assertFalse(self.get()["kept"])

    def test_delete_with_nothing_kept_is_harmless(self):
        status, out = route(self.app, "DELETE", PATH, q(EXAMPLE))
        self.assertEqual((status, out["kept"]), (200, False))

    def test_the_planner_forgets_even_when_figures_come_with_it(self):
        self.post()
        out = self.app.forecast("menifee", [EXAMPLE], settings=self.SETTINGS, forget=True)
        self.assertFalse(out["kept"])
        self.assertNotIn(KEY, self.saved())

    def test_the_kept_figures_survive_a_restart(self):
        self.post()
        again = self.make_app()
        out = again.forecast("menifee", [EXAMPLE])
        self.assertTrue(out["kept"])
        self.assertEqual(out["settings"]["assumptions"], {"capture_pct": 50.0, "spend_pct": 40.0})

    def test_the_forecasts_figures_are_not_the_plans_figures(self):
        self.post()
        self.assertFalse(self.app.plan("menifee", EXAMPLE)["kept"])
        self.app.plan("menifee", EXAMPLE, settings={"mode": "best"})
        self.assertEqual(self.get()["settings"]["assumptions"], {"capture_pct": 50.0, "spend_pct": 40.0})
        self.assertEqual(set(self.saved()), {KEY, f"menifee/{EXAMPLE}"})

    def test_an_unreadable_figures_file_is_set_aside_and_the_forecast_still_comes_back(self):
        self.plans_file.write_text("{not json", encoding="utf-8")
        out = self.get()
        self.assertFalse(out["kept"])
        self.assertTrue(out["available"])
        self.assertTrue(self.plans_file.with_suffix(".unreadable.json").exists())

    def test_post_with_something_that_is_not_a_dictionary_is_a_400_and_keeps_nothing(self):
        for body in (None, [], [1, 2], "capture_pct", 5, True, 1.5):
            with self.subTest(body=body):
                e = self.problem(self.app, "POST", PATH, q(EXAMPLE), body=body)
                self.assertEqual((e.status, e.code), (400, "bad-request"))
        self.assertFalse(self.plans_file.exists())


# ---------------------------------------------------------------- what the route checks

class TheAddress(OnMenifee):
    def test_no_parcels_is_a_400_for_every_method_and_keeps_nothing(self):
        for query in ({}, {"apns": [""]}, {"apns": ["  "]}, {"apns": [", ,+ "]}, {"apns": ["abc"]}, {"apns": []}, {"other": ["1"]}, None):
            for method, body in (("GET", None), ("POST", {"assumptions": {"capture_pct": 50}}), ("DELETE", None)):
                with self.subTest(query=query, method=method):
                    e = self.problem(self.app, method, PATH, query, body=body)
                    self.assertEqual((e.status, e.code), (400, "bad-request"))
        self.assertFalse(self.plans_file.exists())

    def test_more_than_twelve_parcels_is_a_400_for_every_method_and_keeps_nothing(self):
        thirteen = [f"3600000{i:02d}" for i in range(13)]
        for method, body in (("GET", None), ("POST", {"assumptions": {"capture_pct": 50}}), ("DELETE", None)):
            with self.subTest(method=method):
                e = self.problem(self.app, method, PATH, q(*thirteen), body=body)
                self.assertEqual((e.status, e.code), (400, "bad-request"))
                self.assertIn("12", e.message)
        self.assertFalse(self.plans_file.exists())
        self.assertEqual(self.replay.asked, [], "the count is checked before any parcel is looked up")

    def test_an_unknown_parcel_is_a_404_for_every_method_and_keeps_nothing(self):
        for method, body in (("GET", None), ("POST", {"assumptions": {"capture_pct": 50}}), ("DELETE", None)):
            with self.subTest(method=method):
                e = self.problem(self.app, method, PATH, q("999999999"), body=body)
                self.assertEqual((e.status, e.code), (404, "no-such-parcel"))
        self.assertFalse(self.plans_file.exists())

    def test_one_unknown_parcel_among_good_ones_is_a_404_and_keeps_nothing(self):
        e = self.problem(self.app, "POST", PATH, q(EXAMPLE, "999999999"), body={"assumptions": {"capture_pct": 50}})
        self.assertEqual((e.status, e.code), (404, "no-such-parcel"))
        self.assertFalse(self.plans_file.exists())

    def test_a_number_with_the_wrong_number_of_digits_is_a_400(self):
        e = self.problem(self.app, "GET", PATH, q("12"))
        self.assertEqual((e.status, e.code), (400, "bad-request"))
        self.assertIn("not a parcel number", e.message)

    def test_an_unknown_city_is_a_404_for_every_method_with_or_without_parcels(self):
        for query in (q(EXAMPLE), {}):
            for method, body in (("GET", None), ("POST", {"assumptions": {"capture_pct": 50}}), ("DELETE", None)):
                with self.subTest(query=query, method=method):
                    e = self.problem(self.app, method, "/api/cities/nowhere/forecast", query, body=body)
                    self.assertEqual((e.status, e.code), (404, "no-such-city"))
        self.assertFalse(self.plans_file.exists())

    def test_other_methods_and_a_longer_address_are_not_found(self):
        for method, path in (("PUT", PATH), ("PATCH", PATH), ("GET", PATH + "/more"), ("GET", "/api/cities/forecast"),
                             ("GET", "/api/forecast")):
            with self.subTest(method=method, path=path):
                e = self.problem(self.app, method, path, q(EXAMPLE), body={})
                self.assertEqual((e.status, e.code), (404, "not-found"))

    def test_the_address_does_not_have_to_name_the_parcels_in_a_particular_way(self):
        for text in (EXAMPLE, "372-100-001", " 372100001 ", "372100001,", ",372100001", "372100001+372100001", "372100001 372-100-001"):
            with self.subTest(text=text):
                status, out = route(self.app, "GET", PATH, {"apns": [text]})
                self.assertEqual((status, out["apns"]), (200, [EXAMPLE]))

    def test_only_the_first_apns_in_the_address_is_read(self):
        status, out = route(self.app, "GET", PATH, {"apns": [EXAMPLE, "999999999"]})
        self.assertEqual((status, out["apns"]), (200, [EXAMPLE]))

    def test_a_very_long_list_of_parcels_is_cut_and_then_refused_not_looked_up(self):
        text = ",".join(f"3600000{i:02d}" for i in range(100))
        e = self.problem(self.app, "GET", PATH, {"apns": [text]})
        self.assertEqual((e.status, e.code), (400, "bad-request"))


class WhenTheCitysParcelRecordsAreSilent(unittest.TestCase):
    def test_it_is_a_502_that_names_the_city_and_nothing_is_kept(self):
        patcher = offline(down=["Menifee_Parcels"])
        patcher.start()
        self.addCleanup(patcher.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        app = LandPlanner({"menifee": Menifee()}, folder.name, clock=Clock(NOW))
        for method, body in (("GET", None), ("POST", {"assumptions": {"capture_pct": 50}}), ("DELETE", None)):
            with self.subTest(method=method):
                with self.assertRaises(Problem) as caught:
                    route(app, method, PATH, q(EXAMPLE), body=body)
                self.assertEqual((caught.exception.status, caught.exception.code), (502, "source-down"))
                self.assertIn("Menifee", caught.exception.message)
        self.assertFalse((Path(folder.name) / "plans.json").exists())


# ---------------------------------------------------------------- the state's yearly estimates of the city's homes

class WithTheStatesYearlyEstimates(OnMenifee):
    population = population_of({y: 30000 * 1.03 ** (y - 2020) for y in range(2020, 2027)}, "Test state estimates")

    def three(self, out=None):
        return next(r for r in (out or self.get())["rings"] if r["miles"] == 3)

    def test_the_whole_city_is_one_more_measured_reading(self):
        three = self.three()
        self.assertEqual([r["id"] for r in three["readings"]], ["measured", "city", "adopted", "draft"])
        city = three["readings"][1]
        self.assertEqual((city["rate_pct"], city["from"]["year"], city["to"]["year"], city["source"]), (3.0, 2021, 2026, "Test state estimates"))

    def test_up_to_the_latest_count_the_three_lines_are_one_and_follow_the_city(self):
        three = self.three()
        self.assertEqual(three["today_from"]["year"], 2026)
        counted = three["counted"]["2020"]["homes"]
        by_year = {r["year"]: r["homes"] for r in three["rows"]}
        for y in (2025, 2026):
            self.assertEqual(len(set(by_year[y].values())), 1)
            self.assertAlmostEqual(by_year[y]["expected"], counted * 1.03 ** (y - 2020), delta=1)
        self.assertLess(by_year[2027]["low"], by_year[2027]["high"])

    def test_the_forecast_stays_in_order_and_can_be_sent_as_json(self):
        out = self.get()
        json.dumps(out)
        for r in self.three(out)["rows"]:
            self.assertLessEqual(r["homes"]["low"], r["homes"]["expected"])
            self.assertLessEqual(r["homes"]["expected"], r["homes"]["high"])

    def test_the_citys_homes_are_kept_for_the_city_and_not_for_the_site(self):
        self.get()
        keys = [json.loads(path.read_text(encoding="utf-8"))["key"] for path in (Path(self.folder.name) / "cache").glob("*.json")]
        self.assertIn("menifee/economy/population", keys)


# ---------------------------------------------------------------- a silent source

class WhenATrendSourceIsSilent(unittest.TestCase):
    """One service does not answer: the forecast still comes back and says which part is missing."""

    def run_with(self, down=(), cold=(), clock=None, population=None):
        sleeper = mock.patch.object(tool.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)
        patcher = offline(down=down, population=population)
        replay = patcher.start()
        self.addCleanup(patcher.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        copy_of_warm_cache(folder.name, cold)
        app = LandPlanner({"menifee": Menifee()}, folder.name, clock=clock or Clock(NOW))
        return app, replay

    def test_without_the_2010_count_the_counted_reading_is_missing_and_the_forecast_says_so(self):
        app, _ = self.run_with(["Census2010"], cold=["people_before"])
        status, out = route(app, "GET", PATH, q(EXAMPLE))
        self.assertEqual(status, 200)
        self.assertEqual(out["answered"]["people_before"], "did not answer")
        self.assertIsNone(out["fetched"]["people_before"])
        self.assertEqual({p: s for p, s in out["answered"].items() if p != "people_before"}, {p: "ok" for p in out["answered"] if p != "people_before"})
        self.assertTrue(out["available"])
        three = next(r for r in out["rings"] if r["miles"] == 3)
        self.assertEqual([r["id"] for r in three["readings"]], ["adopted", "draft"])
        self.assertEqual({s["name"]: s["answered"] for s in out["sources"]}["2010 Census"], False)

    def test_without_the_regional_plan_there_is_one_reading_and_no_jobs_and_the_offices_are_listed_as_not_forecast(self):
        app, _ = self.run_with(["rdp.scag.ca.gov"], cold=["regional_plan"])
        _, out = route(app, "GET", PATH, q(EXAMPLE))
        self.assertEqual(out["answered"]["regional_plan"], "did not answer")
        self.assertTrue(out["available"])
        three = next(r for r in out["rings"] if r["miles"] == 3)
        self.assertEqual([r["id"] for r in three["readings"]], ["measured"])
        self.assertTrue(three["one_reading"])
        self.assertFalse(out["jobs"]["available"])
        self.assertEqual(out["jobs"]["rows"], [])
        listed = {r["id"] for r in out["programme"]["not_forecast"]}
        self.assertTrue({"office", "business"} <= listed, listed)
        self.assertTrue(listed.isdisjoint(u["id"] for u in out["programme"]["uses"]))
        self.assertIsNone(out["city_forecast"])

    def test_without_the_survey_shops_are_not_forecast_instead_of_never_selling(self):
        app, _ = self.run_with(["P3ePLMYs2RVChkJx"], cold=["tracts"])
        _, out = route(app, "GET", PATH, q(EXAMPLE))
        self.assertEqual(out["answered"]["tracts"], "did not answer")
        self.assertEqual(out["income"], {"available": False})
        self.assertFalse(out["shops"]["available"])
        self.assertEqual([r["id"] for r in out["programme"]["not_forecast"]], ["retail"])
        self.assertNotIn("retail", [u["id"] for u in out["programme"]["uses"]])
        self.assertTrue(out["homes"]["available"])

    def test_with_every_trend_source_silent_there_is_no_forecast_and_the_answer_says_so(self):
        app, _ = self.run_with(["Census2010", "rdp.scag.ca.gov", "P3ePLMYs2RVChkJx"], cold=TREND)
        status, out = route(app, "GET", PATH, q(EXAMPLE))
        self.assertEqual(status, 200)
        self.assertEqual({p: out["answered"][p] for p in TREND}, {p: "did not answer" for p in TREND})
        three = next(r for r in out["rings"] if r["miles"] == 3)
        self.assertEqual(three["readings"], [], "the 2020 count alone is no growth")
        self.assertFalse(out["available"])
        self.assertEqual(out["headline"], [])
        self.assertTrue(any("no reading of growth" in line.lower() for line in out["limits"]))

    def test_with_every_trend_source_silent_but_the_states_yearly_estimates_the_city_alone_gives_one_reading(self):
        pop = population_of({y: 30000 * 1.03 ** (y - 2020) for y in range(2020, 2027)})
        app, _ = self.run_with(["Census2010", "rdp.scag.ca.gov", "P3ePLMYs2RVChkJx"], cold=TREND, population=pop)
        status, out = route(app, "GET", PATH, q(EXAMPLE))
        self.assertEqual(status, 200)
        three = next(r for r in out["rings"] if r["miles"] == 3)
        self.assertEqual([r["id"] for r in three["readings"]], ["city"])
        self.assertTrue(three["one_reading"])
        self.assertTrue(out["available"])
        self.assertEqual(three["rates_pct"], {"low": 3.0, "expected": 3.0, "high": 3.0})
        self.assertFalse(any("no reading of growth" in line.lower() for line in out["limits"]))

    def test_without_the_2020_count_there_is_no_forecast_at_all_and_the_limits_say_so(self):
        app, _ = self.run_with(["Tracts_Blocks"], cold=["people"])
        status, out = route(app, "GET", PATH, q(EXAMPLE))
        self.assertEqual(status, 200)
        self.assertEqual(out["answered"]["people"], "did not answer")
        self.assertFalse(out["available"])
        self.assertEqual(out["headline"], [])
        self.assertTrue(any("no reading of growth" in line.lower() for line in out["limits"]))
        self.assertFalse(out["programme"]["available"])
        self.assertTrue(out["programme"]["not_forecast"])

    def test_without_the_project_lists_the_pipeline_is_not_available(self):
        app, _ = self.run_with(["Land_Development_Projects"], cold=["projects"])
        _, out = route(app, "GET", PATH, q(EXAMPLE))
        self.assertEqual(out["answered"]["projects"], "did not answer")
        self.assertFalse(out["homes"]["pipeline"]["available"])
        self.assertEqual(out["homes"]["pipeline_10_years"], 0)
        self.assertTrue(out["available"])

    def test_without_the_highway_counts_there_is_no_traffic_forecast(self):
        app, _ = self.run_with(["caltrans"], cold=["state_highway_traffic"])
        _, out = route(app, "GET", PATH, q(EXAMPLE))
        self.assertEqual(out["answered"]["state_highway_traffic"], "did not answer")
        self.assertFalse(out["traffic"]["available"])
        self.assertEqual(out["traffic"]["rows"], [])
        self.assertTrue(out["available"])

    def test_a_silent_source_is_not_asked_again_within_a_minute_and_is_asked_again_after_it(self):
        clock = Clock(NOW)
        app, replay = self.run_with(["Census2010"], cold=["people_before"], clock=clock)
        app.forecast("menifee", [EXAMPLE])
        asked = sum(1 for u in replay.asked if "Census2010" in u)
        self.assertGreaterEqual(asked, 1)
        app.forecast("menifee", [EXAMPLE])
        self.assertEqual(sum(1 for u in replay.asked if "Census2010" in u), asked)
        clock.now += 61
        app.forecast("menifee", [EXAMPLE])
        self.assertGreater(sum(1 for u in replay.asked if "Census2010" in u), asked)

    def test_figures_still_apply_and_are_kept_when_a_source_is_silent(self):
        app, _ = self.run_with(["Census2010"], cold=["people_before"])
        status, out = route(app, "POST", PATH, q(EXAMPLE), body={"assumptions": {"capture_pct": 50}})
        self.assertEqual((status, out["kept"]), (200, True))
        self.assertTrue(out["available"])

    def odd_regional_plan(self, answer):
        """The forecast of an app whose planning agency answers every question with `answer`."""
        real = tool.get_json

        def odd(url, params=None, **kw):
            return answer if "SED_TAZTier2" in url else real(url, params, **kw)

        sleeper = mock.patch.object(tool.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)
        patcher = offline()
        patcher.start()
        self.addCleanup(patcher.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        copy_of_warm_cache(folder.name, ["regional_plan"])
        app = LandPlanner({"menifee": Menifee()}, folder.name, clock=Clock(NOW))
        with mock.patch.object(tool, "get_json", odd):
            return app.forecast("menifee", [EXAMPLE])

    def test_a_service_that_answers_in_a_shape_nobody_expected_is_said_to_be_unreadable(self):
        zone = {"geometry": {"rings": [[[-117.1, 33.6], [-117.0, 33.6], [-117.0, 33.7], [-117.1, 33.7], [-117.1, 33.6]]]}}   # no attributes
        with self.assertLogs("landplanner", "WARNING"):
            out = self.odd_regional_plan({"features": [zone]})
        self.assertEqual(out["answered"]["regional_plan"], "could not be read")
        self.assertTrue(out["available"], "the rest of the forecast still comes")

    def test_a_zone_with_empty_attributes_is_unreadable_too_and_the_log_says_where(self):
        # {"attributes": None} gives AttributeError ('NoneType' has no attribute 'get') inside regional_plan: the forecast
        # must still come, the page must say the answer could not be read, and the log must point at the line
        with self.assertLogs("landplanner", "WARNING") as logs:
            out = self.odd_regional_plan({"features": [{"attributes": None, "geometry": {"rings": []}}]})
        self.assertEqual(out["answered"]["regional_plan"], "could not be read")
        self.assertTrue(out["available"])
        record = [r for r in logs.records if "regional_plan" in r.getMessage()][0]
        self.assertIn("AttributeError", record.getMessage())
        self.assertIsNotNone(record.exc_info)


# ---------------------------------------------------------------- several parcels as one site, on a made-up town

H, W = 0.001, 0.004                 # a lot is 0.001 degrees of latitude tall (364 ft) and 0.004 of longitude wide (about 1,200 ft)
LAT0, LON0 = 33.655, -117.165
HAUN = ("360350024", "360350017", "360350011", "360350006")       # the user's real example, filed as a test case


def lot(apn, i, zoning="R-1", north=LAT0, gap=0.0):
    """A lot i lots south of `north`, its outline a rectangle (a real parcel's shape is not this regular)."""
    top = north - i * (H + gap)
    bottom = top - H
    ring = [[LON0, bottom], [LON0 + W, bottom], [LON0 + W, top], [LON0, top], [LON0, bottom]]
    out = row(apn, round(G.rings_acres([ring]), 1), zoning, True, 100, rings=[ring])
    out["centre"] = {"lat": (top + bottom) / 2, "lon": LON0 + W / 2}
    return out


def counted(year, one, three, five):
    return {"year": year, "source": "Test census", "rings": [{"miles": m, "people": 3 * h, "homes": h} for m, h in ((1, one), (3, three), (5, five))]}


def plan_of(label, years, ratio):
    return {"label": label, "years": years, "zones": 3,
            "rings": [{"miles": m, "households": {str(years[0]): h, str(years[1]): round(h * ratio), str(years[2]): 3 * h},
                       "jobs": {str(years[0]): 1000, str(years[1]): 1300, str(years[2]): 3000}} for m, h in ((1, 1000), (3, 10000), (5, 30000))]}


class Block(Tinytown):
    """Tinytown with lots stacked north to south, and a record of which parcel every site part was read for."""

    def __init__(self, apns=HAUN, zonings=None, gap=0.0, grows=False):
        super().__init__()
        zonings = zonings or ["R-1"] * len(apns)
        self.rows = [lot(a, i, z, gap=gap) for i, (a, z) in enumerate(zip(apns, zonings))]
        self.grows = grows
        self.read_for = []

    def zoning_kind(self, code):
        """The families the plan knows, so that "R-1" lots are planned for houses and "C-1" lots for shops."""
        return {"R-1": "low-density", "C-1": "commercial"}.get(str(code or ""), "other")

    def site_part(self, part, parcel):
        self.read_for.append((part, parcel["apn"]))
        if self.grows and part == "people":
            return counted(2020, 1000, 10000, 30000)
        if self.grows and part == "people_before":
            return counted(2010, 1000, 10000, 30000)
        if self.grows and part == "regional_plan":
            return {"within_miles": 5, "source": "Test agency", "adopted": plan_of("Adopted", [2019, 2021, 2050], 1.21),
                    "draft": plan_of("Draft", [2024, 2026, 2050], 1.4641), "city": None}
        return super().site_part(part, parcel)


class TownBase(unittest.TestCase):
    PATH = "/api/cities/tinytown/forecast"

    def town(self, **kw):
        self.city = Block(**kw)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder.name
        self.app = LandPlanner({"tinytown": self.city}, folder.name, clock=Clock(NOW))
        self.plans_file = Path(folder.name) / "plans.json"
        return self.city

    def saved(self):
        return json.loads(self.plans_file.read_text(encoding="utf-8"))["plans"] if self.plans_file.exists() else {}

    def get(self, *apns, method="GET", body=None):
        status, out = route(self.app, method, self.PATH, q(*apns), body=body)
        self.assertEqual(status, 200)
        return out

    def problem(self, *args, **kw):
        with self.assertRaises(Problem) as caught:
            route(*args, **kw)
        return caught.exception

    def plans_made(self, *apns):
        """The parcels make_plan was asked about while a forecast was worked out."""
        real = P.make_plan
        with mock.patch.object(P, "make_plan", side_effect=real) as spy:
            out = self.app.forecast("tinytown", list(apns))
        return out, spy.call_args_list


class FourLotsStackedAlongOneRoad(TownBase):
    """The user's real example: parcels 360-350-024, 017, 011 and 006 along Haun Rd, four lots one above the next in one zone."""

    def setUp(self):
        self.town()

    def test_the_four_lots_make_one_site_of_one_plan(self):
        out = self.get(*HAUN)
        site = out["site"]
        self.assertTrue(site["one_plan"])
        self.assertTrue(site["together"])
        self.assertEqual(site["apns"], list(HAUN))
        self.assertEqual(out["apns"], list(HAUN))
        self.assertEqual(len(site["parcels"]), 4)

    def test_the_total_acres_are_the_sum_of_the_lots(self):
        site = self.get(*HAUN)["site"]
        lots = [r["acres"] for r in self.city.rows]
        self.assertEqual(lots, [10.1] * 4)
        self.assertEqual(site["acres"], round(sum(lots), 2))
        self.assertEqual(sum(p["acres"] for p in site["parcels"]), sum(lots))

    def test_the_site_is_centred_between_the_lots_and_is_compact(self):
        site = self.get(*HAUN)["site"]
        self.assertAlmostEqual(site["centre"]["lat"], LAT0 - 2 * H, places=4)
        self.assertAlmostEqual(site["centre"]["lon"], LON0 + W / 2, places=4)
        self.assertLess(site["spread_miles"], 0.2)

    def test_a_single_combined_plan_is_made_for_the_whole_block(self):
        out, calls = self.plans_made(*HAUN)
        self.assertEqual(len(calls), 1, "one plan for the block, not one for each lot")
        whole = calls[0].args[0]
        self.assertAlmostEqual(whole["acres"], 40.4, places=1)
        self.assertRegex(whole["apn"], r"^site-[0-9a-f]{12}$")
        self.assertEqual(out["programme"]["basis"], "One plan worked out for the whole block of land, under today's zoning.")
        self.assertAlmostEqual(out["programme"]["acres"], 40.4, delta=0.2)

    def test_the_combined_plan_is_drawn_on_the_joint_outline(self):
        out, calls = self.plans_made(*HAUN)
        ring = calls[0].args[0]["outline"]["coordinates"][0]
        self.assertEqual(ring[0], ring[-1])
        self.assertEqual(len(ring), 5, "a rectangle: four corners, closed")
        self.assertAlmostEqual(G.rings_acres([ring]), 40.4, delta=0.2)
        self.assertEqual({tuple(p) for p in ring[:-1]}, {(LON0, LAT0), (LON0 + W, LAT0), (LON0, LAT0 - 4 * H), (LON0 + W, LAT0 - 4 * H)})

    def test_the_facts_around_the_site_are_read_once_for_a_stand_in_parcel_named_after_the_site(self):
        self.get(*HAUN)
        stand_in = {apn for part, apn in self.city.read_for if apn not in HAUN}
        self.assertEqual(len(stand_in), 1)
        self.assertRegex(stand_in.pop(), r"^site-[0-9a-f]{12}$")
        self.assertFalse({apn for _, apn in self.city.read_for} & set(HAUN), "no lot is read on its own")

    def test_the_stand_in_name_does_not_depend_on_the_order_the_lots_are_given_in(self):
        self.get(*HAUN)
        first = {apn for _, apn in self.city.read_for}
        self.town()                                    # a new app, so that nothing is served from the saved answers
        self.get(*reversed(HAUN))
        self.assertEqual({apn for _, apn in self.city.read_for}, first)

    def test_a_different_set_of_lots_has_a_different_stand_in(self):
        self.get(*HAUN)
        self.get(*HAUN[:3])
        names = {apn for _, apn in self.city.read_for}
        self.assertEqual(len(names), 2)

    def test_the_answer_has_no_limit_about_the_lots_being_apart(self):
        out = self.get(*HAUN)
        self.assertFalse(any("not next to each other" in line for line in out["limits"]))

    def test_the_answer_can_be_sent_as_json(self):
        json.dumps(self.get(*HAUN), allow_nan=False)

    def test_the_parcel_numbers_may_be_separated_by_commas_spaces_or_plus_signs(self):
        a, b, c, d = HAUN
        want = self.get(*HAUN)
        for text in (f"{a},{b},{c},{d}", f"{a} {b} {c} {d}", f"{a}+{b}+{c}+{d}", f"{a}, {b}, {c}, {d}", f" {a} ,+ {b}  {c}\t{d} ",
                     "360-350-024,360-350-017 360350011+360350006"):
            with self.subTest(text=text):
                status, out = route(self.app, "GET", self.PATH, {"apns": [text]})
                self.assertEqual(status, 200)
                self.assertEqual(out["apns"], list(HAUN))
                self.assertEqual(out["site"], want["site"])

    def test_duplicates_collapse(self):
        a, b, c, d = HAUN
        out = self.get(a, b, a, "360-350-024", b, c, d, d)
        self.assertEqual(out["apns"], list(HAUN))
        self.assertEqual(out["site"]["acres"], round(4 * 10.1, 2))
        self.assertEqual(len(out["site"]["parcels"]), 4)

    def test_the_same_parcel_given_twice_is_a_single_parcel_not_a_site_of_two(self):
        a = HAUN[0]
        out = self.get(a, a)
        self.assertEqual(out["apns"], [a])
        self.assertEqual(out["site"]["acres"], 10.1)
        self.assertEqual(out["programme"]["basis"], "The plan each parcel has on its own Plan page.")
        self.assertEqual({apn for _, apn in self.city.read_for}, {a}, "a single parcel is read for itself, with no stand-in")

    def test_exactly_twelve_known_parcels_are_allowed(self):
        apns = [f"3603500{i:02d}" for i in range(12)]
        self.town(apns=apns)
        out = self.get(*apns)
        self.assertEqual(len(out["apns"]), 12)
        self.assertEqual(out["site"]["acres"], round(12 * 10.1, 2))

    def test_thirteen_parcels_are_too_many_even_when_they_all_exist(self):
        apns = [f"3603500{i:02d}" for i in range(13)]
        self.town(apns=apns)
        e = self.problem(self.app, "GET", self.PATH, q(*apns))
        self.assertEqual((e.status, e.code), (400, "bad-request"))

    def test_nothing_is_known_about_the_trend_in_a_town_that_has_none_and_the_forecast_says_so(self):
        out = self.get(*HAUN)
        self.assertFalse(out["available"])
        self.assertEqual(set(out["answered"].values()), {"nothing found there"})
        self.assertTrue(any("no reading of growth" in line.lower() for line in out["limits"]))


class FourLotsInAGrowingTown(TownBase):
    def setUp(self):
        self.town(grows=True)

    def test_the_forecast_is_made_for_the_site_and_the_combined_plan_is_taken_up(self):
        out, calls = self.plans_made(*HAUN)
        self.assertTrue(out["available"])
        self.assertEqual(len(calls), 1)
        self.assertTrue(out["programme"]["available"])
        acres = sum(u["acres"] for u in out["programme"]["uses"]) + sum(r["acres"] for r in out["programme"]["not_forecast"])
        self.assertLessEqual(acres, out["site"]["acres"] + 0.2)
        for u in out["programme"]["uses"]:
            self.assertLessEqual(u["by_year_10"], u["amount"])
            self.assertEqual(len(u["by_year"]), 10)

    def test_the_need_for_shops_is_met_once_for_the_block_not_once_for_each_lot(self):
        def shop_acres(out):
            """The acres planned for shops, whether the forecast took them up or listed them as not forecast."""
            rows = out["programme"]["uses"] + out["programme"]["not_forecast"]
            return sum(r["acres"] for r in rows if r["id"] == "retail")

        self.town(grows=True, zonings=["C-1"] * 4)
        together = self.get(*HAUN)
        self.assertTrue(together["site"]["one_plan"])
        alone = []
        for apn in HAUN:
            city = Block(apns=(apn,), grows=True, zonings=["C-1"])
            alone.append(LandPlanner({"tinytown": city}, tempfile.mkdtemp(), clock=Clock(NOW)).forecast("tinytown", [apn]))
        self.assertGreater(shop_acres(together), 0)
        self.assertLess(shop_acres(together), sum(shop_acres(f) for f in alone))

    def test_figures_kept_for_the_block_are_kept_under_the_sorted_parcel_numbers(self):
        status, out = route(self.app, "POST", self.PATH, q(*reversed(HAUN)), body={"assumptions": {"capture_pct": 50}})
        self.assertEqual((status, out["kept"]), (200, True))
        self.assertEqual(list(self.saved()), ["tinytown/forecast/" + "+".join(sorted(HAUN))])
        later = self.get(*HAUN)
        self.assertTrue(later["kept"])
        self.assertEqual(later["settings"], {"assumptions": {"capture_pct": 50.0}})

    def test_figures_kept_for_the_block_are_not_the_figures_of_one_of_its_lots(self):
        route(self.app, "POST", self.PATH, q(*HAUN), body={"assumptions": {"capture_pct": 50}})
        self.assertFalse(self.get(HAUN[0])["kept"])
        self.assertFalse(self.get(*HAUN[:3])["kept"])
        self.assertTrue(self.get(*HAUN)["kept"])
        route(self.app, "DELETE", self.PATH, q(*HAUN))
        self.assertEqual(self.saved(), {})

    def test_one_lots_own_plan_is_the_one_its_owner_keeps_for_it(self):
        a = HAUN[0]
        base = self.get(a)
        self.app.plan("tinytown", a, settings={"acres": {"homes": 1}})
        mine = self.get(a)
        self.assertNotEqual(mine["programme"]["uses"], base["programme"]["uses"])
        self.assertEqual([u["id"] for u in mine["programme"]["uses"]], ["homes"])
        self.assertAlmostEqual(mine["programme"]["uses"][0]["acres"], 10.1, delta=0.1)


class LotsThatAreApart(TownBase):
    def test_lots_far_apart_do_not_make_one_site_and_the_limit_sentence_comes_first(self):
        apns = ("360350001", "360350002")
        self.town(apns=apns)
        # the second lot moved about 2 miles north: its centre is 1 mile from the middle of the two
        self.city.rows[1] = lot("360350002", 0, north=LAT0 + 0.03)
        out = self.get(*apns)
        site = out["site"]
        self.assertFalse(site["together"])
        self.assertFalse(site["one_plan"])
        self.assertGreater(site["spread_miles"], 0.75)
        self.assertTrue(out["limits"][0].startswith("These parcels are not next to each other."), out["limits"][0])
        self.assertEqual(sum(1 for line in out["limits"] if "not next to each other" in line), 1)
        self.assertTrue(out["programme"]["basis"].startswith("Each parcel's own plan, added up"))

    def test_far_apart_lots_each_get_their_own_plan(self):
        apns = ("360350001", "360350002")
        self.town(apns=apns)
        self.city.rows[1] = lot("360350002", 0, north=LAT0 + 0.03)
        out, calls = self.plans_made(*apns)
        self.assertEqual(sorted(c.args[0]["apn"] for c in calls), sorted(apns))
        self.assertEqual(sorted(c.args[0]["acres"] for c in calls), [10.1, 10.1])
        self.assertAlmostEqual(out["programme"]["acres"], 20.2, delta=0.2)

    def test_the_forecast_is_read_at_the_point_between_them(self):
        apns = ("360350001", "360350002")
        self.town(apns=apns)
        self.city.rows[1] = lot("360350002", 0, north=LAT0 + 0.03)
        out = self.get(*apns)
        self.assertGreater(out["site"]["centre"]["lat"], LAT0 - H)
        self.assertLess(out["site"]["centre"]["lat"], LAT0 + 0.03)

    def test_lots_with_a_gap_between_them_in_one_zone_are_together_but_not_one_block(self):
        apns = ("360350001", "360350002")
        self.town(apns=apns, gap=H)                  # a lot-sized gap between them: the joint outline holds a third as much again
        out = self.get(*apns)
        self.assertTrue(out["site"]["together"])
        self.assertFalse(out["site"]["one_plan"])
        self.assertFalse(any("not next to each other" in line for line in out["limits"]))
        self.assertTrue(out["programme"]["basis"].startswith("Each parcel's own plan, added up"))

    def test_neighbours_in_different_zones_are_not_one_plan(self):
        apns = ("360350001", "360350002", "360350003", "360350004")
        self.town(apns=apns, zonings=["R-1", "R-1", "C-1", "C-1"])
        out, calls = self.plans_made(*apns)
        self.assertTrue(out["site"]["together"])
        self.assertFalse(out["site"]["one_plan"])
        self.assertEqual(len(calls), 4)
        self.assertEqual(sorted(c.args[0]["zoning"] for c in calls), ["C-1", "C-1", "R-1", "R-1"])
        self.assertTrue(out["programme"]["basis"].startswith("Each parcel's own plan, added up"))
        self.assertFalse(any("not next to each other" in line for line in out["limits"]))
        self.assertEqual(out["site"]["acres"], round(4 * 10.1, 2))

    def test_two_zones_that_are_the_same_zone_written_differently_still_differ(self):
        apns = ("360350001", "360350002")
        self.town(apns=apns, zonings=["R-1", "r-1"])
        self.assertFalse(self.get(*apns)["site"]["one_plan"])

    def test_one_lot_with_no_zone_among_lots_with_one_is_not_one_plan(self):
        apns = ("360350001", "360350002")
        self.town(apns=apns, zonings=["R-1", ""])
        self.assertFalse(self.get(*apns)["site"]["one_plan"])

    def test_two_lots_that_touch_in_one_zone_are_one_plan(self):
        apns = ("360350001", "360350002")
        self.town(apns=apns)
        out = self.get(*apns)
        self.assertTrue(out["site"]["one_plan"])
        self.assertEqual(out["site"]["acres"], 20.2)

    def test_each_lots_own_kept_plan_is_used_when_they_are_planned_separately(self):
        apns = ("360350001", "360350002")
        self.town(apns=apns, zonings=["R-1", "C-1"], grows=True)
        self.app.plan("tinytown", apns[0], settings={"acres": {"homes": 1}})
        out, calls = self.plans_made(*apns)
        self.assertEqual(len(calls), 2)
        kept = next(c for c in calls if c.args[0]["apn"] == apns[0])
        other = next(c for c in calls if c.args[0]["apn"] == apns[1])
        self.assertEqual(kept.args[2]["acres"]["homes"], 1.0)
        self.assertIsNone(other.args[2])

    def test_the_kept_plan_of_a_lot_is_not_used_when_the_block_is_planned_as_one(self):
        apns = ("360350001", "360350002")
        self.town(apns=apns, grows=True)
        self.app.plan("tinytown", apns[0], settings={"acres": {"homes": 1}})
        out, calls = self.plans_made(*apns)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0].args[2])


class ParcelsWithNoOutline(TownBase):
    def test_several_parcels_the_city_has_no_outline_for_still_get_an_answer(self):
        # every rings list empty (the city's record has no geometry): _site takes max() of no points and raises
        # ValueError, which is not a Problem and not one of the planner's DOWN errors, so the route fails with a 500
        self.town(apns=HAUN[:2])
        for r in self.city.rows:
            r["rings"] = []
        out = self.get(*HAUN[:2])
        self.assertIsInstance(out, dict)

    def test_one_parcel_with_no_outline_among_others_is_not_part_of_the_joint_outline_and_so_not_one_block(self):
        self.town(apns=HAUN[:3])
        self.city.rows[2]["rings"] = []
        out = self.get(*HAUN[:3])
        self.assertFalse(out["site"]["one_plan"])
        self.assertEqual(out["site"]["acres"], round(3 * 10.1, 2))

    def test_a_single_parcel_with_no_outline_still_gets_an_answer(self):
        self.town(apns=HAUN[:1])
        self.city.rows[0]["rings"] = []
        out = self.get(HAUN[0])
        self.assertEqual(out["apns"], [HAUN[0]])


class Hull(unittest.TestCase):
    def test_a_square_with_points_inside_is_its_four_corners(self):
        corners = [(0, 0), (10, 0), (10, 10), (0, 10)]
        inner = [(5, 5), (1, 1), (9, 9), (2, 7), (5, 0.5)]
        got = G.hull(corners + inner)
        self.assertEqual(sorted(got), sorted(corners))
        self.assertEqual(len(got), 4)

    def test_it_goes_round_once_and_anticlockwise(self):
        got = G.hull([(0, 0), (10, 0), (10, 10), (0, 10), (5, 5)])
        self.assertGreater(G.signed_area(got), 0)
        self.assertEqual(G.area(got), 100.0)
        self.assertEqual(len(set(got)), len(got))

    def test_a_point_in_the_middle_of_an_edge_is_not_a_corner(self):
        got = G.hull([(0, 0), (5, 0), (10, 0), (10, 10), (0, 10)])
        self.assertEqual(sorted(got), [(0, 0), (0, 10), (10, 0), (10, 10)])

    def test_points_in_a_line_give_only_the_two_ends(self):
        self.assertEqual(G.hull([(0, 0), (1, 1), (2, 2), (3, 3)]), [(0, 0), (3, 3)])
        self.assertEqual(G.hull([(5, 1), (5, 9), (5, 4), (5, 2)]), [(5, 1), (5, 9)])
        self.assertEqual(G.hull([(3, 2), (1, 2), (2, 2)]), [(1, 2), (3, 2)])

    def test_fewer_than_three_points_come_back_as_they_are_sorted(self):
        self.assertEqual(G.hull([]), [])
        self.assertEqual(G.hull([(4, 4)]), [(4, 4)])
        self.assertEqual(G.hull([(5, 5), (1, 1)]), [(1, 1), (5, 5)])

    def test_repeated_points_count_once(self):
        self.assertEqual(G.hull([(1, 1), (1, 1), (1, 1)]), [(1, 1)])
        self.assertEqual(G.hull([(0, 0), (0, 0), (4, 0), (4, 0), (0, 3)]), [(0, 0), (4, 0), (0, 3)])

    def test_a_triangle_is_its_three_corners(self):
        self.assertEqual(sorted(G.hull([(0, 0), (6, 0), (0, 6), (1, 1)])), [(0, 0), (0, 6), (6, 0)])

    def test_a_dent_in_an_outline_is_filled(self):
        l_shape = [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)]
        got = G.hull(l_shape)
        self.assertNotIn((4, 4), got)
        self.assertEqual(G.area(got), 100 - 18)

    def test_lists_and_tuples_both_work_and_extra_values_are_ignored(self):
        self.assertEqual(sorted(G.hull([[0, 0, "x"], [4, 0], (4, 4, 9), [0, 4], [2, 2]])), [(0, 0), (0, 4), (4, 0), (4, 4)])

    def test_every_point_lies_inside_or_on_the_hull(self):
        import random
        rng = random.Random(7)
        points = [(rng.uniform(-50, 50), rng.uniform(-50, 50)) for _ in range(200)]
        got = G.hull(points)
        self.assertGreaterEqual(len(got), 3)
        for p in points:
            for a, b in zip(got, got[1:] + got[:1]):
                cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
                self.assertGreaterEqual(cross, -1e-9, (p, a, b))

    def test_the_corners_of_four_stacked_lots_are_the_corners_of_the_block(self):
        lots = [lot(a, i)["rings"][0] for i, a in enumerate(HAUN)]
        got = G.hull([tuple(p) for ring in lots for p in ring])
        self.assertEqual(len(got), 4)
        self.assertAlmostEqual(G.rings_acres([got + got[:1]]), 40.4, delta=0.2)


if __name__ == "__main__":
    unittest.main()
