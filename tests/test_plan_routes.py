"""The land-use plan through LandPlanner.plan and the server's plan routes, on the recorded Menifee answers for the
example parcel (372-100-001, 142.1 acres, EDC-CC). Nothing here reaches the network: a question that was never recorded
fails the test, and a silent service is simulated with offline(down=[...])."""
import json
import tempfile
import unittest
from pathlib import Path

from support import EXAMPLE, Clock, offline, tool
from landplanner import plan as P
from landplanner.cities import SITE_PARTS
from landplanner.cities.menifee import Menifee
from landplanner.planner import LandPlanner, Problem
from landplanner.server import route

PLAN_PATH = f"/api/cities/menifee/lands/{EXAMPLE}/plan"
KEY = f"menifee/{EXAMPLE}"
# what plan() asks for: the quick and market parts, but not the neighbours' outlines (the map's business) or the slow ground heights
ASKED_PARTS = {p for p, g in SITE_PARTS.items() if g in ("quick", "market") and p != "neighbour_shapes"}
CENSUS, SIGNALS, STREETS = "TIGERweb", "Traffic_Signals", "Circulation_Element"


class Base(unittest.TestCase):
    down = ()

    def setUp(self):
        patcher = offline(down=self.down)
        self.replay = patcher.start()
        self.addCleanup(patcher.stop)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.clock = Clock()
        self.app = self.make_app()
        self.plans_file = Path(self.folder.name) / "plans.json"

    def make_app(self):
        return LandPlanner({"menifee": Menifee()}, self.folder.name, clock=self.clock)

    def saved(self):
        return json.loads(self.plans_file.read_text(encoding="utf-8"))["plans"]

    def problem(self, call, *args, **kw):
        with self.assertRaises(Problem) as caught:
            call(*args, **kw)
        return caught.exception

    def asked(self, word):
        return sum(1 for url in self.replay.asked if word in url)


def acres_of(plan):
    return {u["id"]: u["acres"] for u in plan["uses"]}


class ThePlanForTheExampleParcel(Base):
    def test_the_uses_add_up_to_the_parcels_acres(self):
        plan = self.app.plan("menifee", EXAMPLE)
        self.assertEqual((plan["city"], plan["apn"], plan["acres"]), ("menifee", EXAMPLE, 142.1))
        self.assertAlmostEqual(sum(acres_of(plan).values()), 142.1, delta=0.1)
        self.assertEqual([u["id"] for u in plan["uses"]], list(P.USE_IDS))
        self.assertEqual(plan["mode"], "zoning")
        self.assertFalse(plan["nothing_to_build"])

    def test_every_site_part_it_asked_for_answered(self):
        plan = self.app.plan("menifee", EXAMPLE)
        self.assertEqual(set(plan["sources"]), ASKED_PARTS)
        self.assertEqual(set(plan["sources"].values()), {"ok"})
        self.assertEqual(set(plan["fetched"]), ASKED_PARTS)
        self.assertTrue(all(plan["fetched"].values()))
        self.assertEqual(plan["facts"]["missing"], [])
        self.assertTrue(plan["parcel_fetched"])

    def test_the_street_it_fronts_and_the_entrances_are_found(self):
        plan = self.app.plan("menifee", EXAMPLE)
        front = plan["facts"]["frontage"]
        self.assertTrue(front)
        self.assertLessEqual(front["feet"], 150)
        self.assertGreaterEqual(front["rank"], 1)
        self.assertGreaterEqual(len(plan["traffic"]["entrances"]), 1)
        for e in plan["traffic"]["entrances"]:
            self.assertTrue(-118 < e["lon"] < -117 and 33 < e["lat"] < 34)
            self.assertIn(e["signal"], ("existing", "study", "none"))

    def test_the_drawing_has_a_closed_piece_for_every_use_with_acres(self):
        plan = self.app.plan("menifee", EXAMPLE)
        used = sorted(u for u, a in acres_of(plan).items() if a > 0)
        self.assertEqual(sorted(p["use"] for p in plan["drawing"]["pieces"]), used)
        for piece in plan["drawing"]["pieces"]:
            self.assertEqual(piece["ring"][0], piece["ring"][-1])

    def test_the_answer_can_be_sent_as_json(self):
        json.dumps(self.app.plan("menifee", EXAMPLE))

    def test_the_slow_ground_heights_are_not_asked_for_and_the_plan_says_so(self):
        plan = self.app.plan("menifee", EXAMPLE)
        self.assertFalse(plan["ground_read"])
        self.assertIsNone(plan["facts"]["ground"])
        self.assertNotIn(tool.SAMPLES, self.replay.asked)
        self.assertFalse(any("elevation" in url.lower() for url in self.replay.asked))

    def test_after_the_ground_heights_have_been_read_the_plan_says_so_and_uses_them(self):
        before = self.app.plan("menifee", EXAMPLE)
        ground = self.app.land("menifee", EXAMPLE, group="ground")
        self.assertEqual(set(ground["sources"].values()), {"ok"})
        after = self.app.plan("menifee", EXAMPLE)
        self.assertTrue(after["ground_read"])
        self.assertTrue(after["facts"]["ground"])
        self.assertIsNotNone(after["facts"]["ground"]["slope_pct"])
        self.assertAlmostEqual(sum(acres_of(after).values()), 142.1, delta=0.1)
        self.assertFalse(before["ground_read"])

    def test_a_second_plan_is_served_from_the_saved_answers(self):
        self.app.plan("menifee", EXAMPLE)
        asked = len(self.replay.asked)
        again = self.app.plan("menifee", EXAMPLE)
        self.assertEqual(len(self.replay.asked), asked, "nothing is asked of a public service twice in a row")
        self.assertEqual(set(again["sources"].values()), {"ok"})

    def test_the_parcel_number_may_be_written_with_dashes(self):
        plan = self.app.plan("menifee", "372-100-001")
        self.assertEqual(plan["apn"], EXAMPLE)

    def test_a_fresh_data_folder_has_no_kept_settings(self):
        plan = self.app.plan("menifee", EXAMPLE)
        self.assertFalse(plan["kept"])
        self.assertEqual(Path(plan["kept_in"]).resolve(), self.plans_file.resolve())
        self.assertFalse(self.plans_file.exists(), "asking for a plan writes nothing")


class KeptSettings(Base):
    SETTINGS = {"mode": "best", "assumptions": {"price_retail": 999000, "not_a_figure": 3}, "land_cost": 1_000_000,
                "extra_costs": [{"name": "Survey", "amount": 5000}]}

    def test_settings_sent_with_the_plan_are_kept_in_plans_json_in_the_data_folder(self):
        plan = self.app.plan("menifee", EXAMPLE, settings=self.SETTINGS)
        self.assertTrue(plan["kept"])
        self.assertEqual(Path(plan["kept_in"]).resolve(), self.plans_file.resolve())
        self.assertTrue(self.plans_file.is_file())
        kept = self.saved()[KEY]
        self.assertEqual(kept["mode"], "best")
        self.assertEqual(kept["assumptions"], {"price_retail": 999000.0}, "only what the page may set is kept")
        self.assertEqual(kept["land_cost"], 1_000_000.0)
        self.assertEqual(kept, plan["settings"])

    def test_the_next_plan_with_no_settings_uses_the_kept_ones(self):
        first = self.app.plan("menifee", EXAMPLE, settings=self.SETTINGS)
        again = self.app.plan("menifee", EXAMPLE)
        self.assertTrue(again["kept"])
        self.assertEqual(again["mode"], "best")
        self.assertEqual(again["settings"], first["settings"])
        figure = next(f for f in again["figures"] if f["id"] == "price_retail")
        self.assertEqual((figure["kind"], figure["value"]), ("yours", 999000.0))
        self.assertEqual(again["money"]["land"], 1_000_000)
        self.assertFalse(again["money"]["land_is_stand_in"])
        self.assertEqual(again["costs"]["extra"], [{"name": "Survey", "amount": 5000}])
        self.assertEqual(acres_of(again), acres_of(first))

    def test_the_kept_settings_survive_a_restart(self):
        self.app.plan("menifee", EXAMPLE, settings={"mode": "best"})
        restarted = self.make_app()
        self.assertEqual(restarted.plan("menifee", EXAMPLE)["mode"], "best")

    def test_the_settings_belong_to_one_parcel(self):
        self.app.plan("menifee", EXAMPLE, settings={"mode": "best"})
        self.assertEqual(set(self.saved()), {KEY})

    def test_new_settings_replace_the_old_ones_instead_of_adding_to_them(self):
        self.app.plan("menifee", EXAMPLE, settings=self.SETTINGS)
        self.app.plan("menifee", EXAMPLE, settings={"assumptions": {"homes_per_acre": 6}})
        kept = self.saved()[KEY]
        self.assertEqual((kept["mode"], kept["assumptions"], kept["land_cost"], kept["extra_costs"]), ("zoning", {"homes_per_acre": 6.0}, None, []))

    def test_settings_that_change_nothing_are_not_kept_and_clear_what_was_kept(self):
        self.app.plan("menifee", EXAMPLE, settings=self.SETTINGS)
        plan = self.app.plan("menifee", EXAMPLE, settings={"mode": "zoning"})
        self.assertFalse(plan["kept"])
        self.assertNotIn(KEY, self.saved())
        self.assertEqual(plan["mode"], "zoning")
        self.assertFalse(self.app.plan("menifee", EXAMPLE, settings={"bogus": 1, "assumptions": {"nonsense": 4}})["kept"])

    def test_forget_removes_them_and_the_plan_is_the_suggestion_again(self):
        suggested = self.app.plan("menifee", EXAMPLE)
        self.app.plan("menifee", EXAMPLE, settings=self.SETTINGS)
        self.assertIn(KEY, self.saved())
        forgotten = self.app.plan("menifee", EXAMPLE, forget=True)
        self.assertFalse(forgotten["kept"])
        self.assertNotIn(KEY, self.saved())
        self.assertEqual(forgotten["mode"], "zoning")
        self.assertEqual(acres_of(forgotten), acres_of(suggested))
        self.assertFalse(self.app.plan("menifee", EXAMPLE)["kept"])

    def test_forget_wins_over_settings_sent_with_it(self):
        plan = self.app.plan("menifee", EXAMPLE, settings={"mode": "best"}, forget=True)
        self.assertFalse(plan["kept"])
        self.assertEqual(plan["mode"], "zoning")
        self.assertFalse(self.saved())

    def test_forgetting_what_was_never_kept_is_harmless(self):
        plan = self.app.plan("menifee", EXAMPLE, forget=True)
        self.assertFalse(plan["kept"])

    def test_an_unreadable_plans_file_is_set_aside_and_the_plan_still_comes_back(self):
        self.plans_file.write_text("{not json", encoding="utf-8")
        plan = self.app.plan("menifee", EXAMPLE)
        self.assertFalse(plan["kept"])
        self.assertEqual(plan["mode"], "zoning")
        self.assertTrue(self.plans_file.with_suffix(".unreadable.json").exists())

    def test_changing_a_figure_changes_the_money_but_not_the_mix(self):
        base = self.app.plan("menifee", EXAMPLE)
        mine = self.app.plan("menifee", EXAMPLE, settings={"assumptions": {"price_retail": 970000}})
        retail = acres_of(base)["retail"]
        self.assertGreater(retail, 0)
        self.assertEqual(acres_of(mine), acres_of(base))
        self.assertEqual(mine["money"]["revenue"] - base["money"]["revenue"], round(retail * 970000) - round(retail * 870000))


class TheRoutes(Base):
    def test_get_returns_200_and_a_plan(self):
        status, plan = route(self.app, "GET", PLAN_PATH)
        self.assertEqual(status, 200)
        self.assertEqual((plan["apn"], plan["acres"]), (EXAMPLE, 142.1))
        self.assertFalse(plan["kept"])

    def test_get_with_the_number_written_with_dashes(self):
        status, plan = route(self.app, "GET", "/api/cities/menifee/lands/372-100-001/plan")
        self.assertEqual((status, plan["apn"]), (200, EXAMPLE))

    def test_post_with_a_dictionary_applies_and_keeps_the_settings(self):
        status, plan = route(self.app, "POST", PLAN_PATH, body={"mode": "best", "assumptions": {"homes_per_acre": 6}})
        self.assertEqual(status, 200)
        self.assertEqual(plan["mode"], "best")
        self.assertTrue(plan["kept"])
        self.assertEqual(self.saved()[KEY]["assumptions"], {"homes_per_acre": 6.0})
        status, later = route(self.app, "GET", PLAN_PATH)
        self.assertEqual((status, later["mode"], later["kept"]), (200, "best", True))
        self.assertEqual(later["settings"], plan["settings"])

    def test_post_with_something_that_is_not_a_dictionary_is_a_400_and_keeps_nothing(self):
        for body in (None, [], [1, 2], "best", 5, True):
            with self.subTest(body=body):
                e = self.problem(route, self.app, "POST", PLAN_PATH, body=body)
                self.assertEqual((e.status, e.code), (400, "bad-request"))
        self.assertFalse(self.plans_file.exists())

    def test_post_with_an_empty_dictionary_keeps_nothing_and_removes_what_was_kept(self):
        status, plan = route(self.app, "POST", PLAN_PATH, body={})
        self.assertEqual((status, plan["mode"], plan["kept"]), (200, "zoning", False))
        route(self.app, "POST", PLAN_PATH, body={"mode": "best"})
        self.assertIn(KEY, self.saved())
        status, plan = route(self.app, "POST", PLAN_PATH, body={})
        self.assertEqual((status, plan["mode"], plan["kept"]), (200, "zoning", False))
        self.assertNotIn(KEY, self.saved())

    def test_delete_forgets_the_settings(self):
        route(self.app, "POST", PLAN_PATH, body={"mode": "best"})
        status, plan = route(self.app, "DELETE", PLAN_PATH)
        self.assertEqual(status, 200)
        self.assertEqual((plan["mode"], plan["kept"]), ("zoning", False))
        self.assertNotIn(KEY, self.saved())
        self.assertEqual(route(self.app, "GET", PLAN_PATH)[1]["mode"], "zoning")

    def test_an_unknown_parcel_number_is_a_404_for_every_method_and_keeps_nothing(self):
        path = "/api/cities/menifee/lands/999999999/plan"
        for method, body in (("GET", None), ("POST", {"mode": "best"}), ("DELETE", None)):
            with self.subTest(method=method):
                e = self.problem(route, self.app, method, path, body=body)
                self.assertEqual((e.status, e.code), (404, "no-such-parcel"))
        self.assertFalse(self.plans_file.exists())

    def test_a_number_with_the_wrong_number_of_digits_is_a_400(self):
        e = self.problem(route, self.app, "GET", "/api/cities/menifee/lands/12/plan")
        self.assertEqual((e.status, e.code), (400, "bad-request"))
        self.assertIn("not a parcel number", e.message)

    def test_an_unknown_city_is_a_404_for_every_method(self):
        path = f"/api/cities/nowhere/lands/{EXAMPLE}/plan"
        for method, body in (("GET", None), ("POST", {"mode": "best"}), ("DELETE", None)):
            with self.subTest(method=method):
                e = self.problem(route, self.app, method, path, body=body)
                self.assertEqual((e.status, e.code), (404, "no-such-city"))
        self.assertFalse(self.plans_file.exists())

    def test_other_methods_and_a_longer_address_are_not_found(self):
        for method, path in (("PUT", PLAN_PATH), ("GET", PLAN_PATH + "/more"), ("PATCH", PLAN_PATH)):
            with self.subTest(method=method, path=path):
                e = self.problem(route, self.app, method, path, body={})
                self.assertEqual((e.status, e.code), (404, "not-found"))


class WhenAMarketSourceIsSilent(unittest.TestCase):
    """One service does not answer: the plan still comes back, and says which part is missing."""

    def run_with(self, down, clock=None):
        patcher = offline(down=down)
        replay = patcher.start()
        self.addCleanup(patcher.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        app = LandPlanner({"menifee": Menifee()}, folder.name, clock=clock or Clock())
        return app, replay

    def test_with_the_census_service_silent_the_plan_names_the_missing_count(self):
        app, _ = self.run_with([CENSUS])
        plan = app.plan("menifee", EXAMPLE)
        self.assertEqual(plan["sources"]["people"], "did not answer")
        self.assertEqual({p: s for p, s in plan["sources"].items() if p != "people"}, {p: "ok" for p in ASKED_PARTS - {"people"}})
        self.assertTrue(any("census" in m for m in plan["facts"]["missing"]))
        self.assertIsNone(plan["fetched"]["people"])
        self.assertIsNone(plan["market"]["people"])
        self.assertAlmostEqual(sum(acres_of(plan).values()), 142.1, delta=0.1)
        self.assertTrue(any("did not answer" in a for a in plan["advice"]))

    def test_with_no_census_count_shops_fall_back_to_a_neighbourhood_centre(self):
        app, _ = self.run_with([CENSUS])
        plan = app.plan("menifee", EXAMPLE)
        self.assertLessEqual(acres_of(plan)["retail"], 12.05)
        self.assertTrue(any("neighbourhood centre" in n for n in plan["notes"]))

    def test_with_the_signals_layer_silent_the_plan_still_comes_back_and_the_sources_say_so(self):
        app, _ = self.run_with([SIGNALS])
        plan = app.plan("menifee", EXAMPLE)
        self.assertEqual(plan["sources"]["signals"], "did not answer")
        self.assertEqual(plan["traffic"]["existing_signals"], [])
        self.assertAlmostEqual(sum(acres_of(plan).values()), 142.1, delta=0.1)
        self.assertGreaterEqual(len(plan["traffic"]["entrances"]), 1)

    def test_with_the_street_map_silent_there_is_no_frontage_and_the_plan_says_so(self):
        app, _ = self.run_with([STREETS])
        plan = app.plan("menifee", EXAMPLE)
        self.assertEqual(plan["sources"]["streets"], "did not answer")
        self.assertTrue(any("street map" in m for m in plan["facts"]["missing"]))
        self.assertIsNone(plan["facts"]["frontage"])
        self.assertEqual(plan["street_lines"], [])
        self.assertAlmostEqual(sum(acres_of(plan).values()), 142.1, delta=0.1)
        self.assertTrue(plan["drawing"]["pieces"])

    def test_with_several_sources_silent_at_once_it_still_works_and_names_each(self):
        app, _ = self.run_with([CENSUS, SIGNALS, STREETS])
        plan = app.plan("menifee", EXAMPLE)
        silent = {p for p, s in plan["sources"].items() if s != "ok"}
        self.assertEqual(silent, {"people", "signals", "streets"})
        self.assertAlmostEqual(sum(acres_of(plan).values()), 142.1, delta=0.1)

    def test_a_silent_source_is_not_asked_again_within_a_minute_and_is_asked_again_after_it(self):
        clock = Clock()
        app, replay = self.run_with([CENSUS], clock)
        app.plan("menifee", EXAMPLE)
        asked = sum(1 for u in replay.asked if CENSUS in u)
        self.assertGreaterEqual(asked, 1)
        app.plan("menifee", EXAMPLE)
        self.assertEqual(sum(1 for u in replay.asked if CENSUS in u), asked)
        clock.now += 61
        app.plan("menifee", EXAMPLE)
        self.assertGreater(sum(1 for u in replay.asked if CENSUS in u), asked)

    def test_the_silent_source_is_reported_through_the_route_too(self):
        app, _ = self.run_with([CENSUS])
        status, plan = route(app, "GET", PLAN_PATH)
        self.assertEqual(status, 200)
        self.assertEqual(plan["sources"]["people"], "did not answer")

    def test_settings_still_apply_and_are_kept_when_a_source_is_silent(self):
        app, _ = self.run_with([CENSUS])
        status, plan = route(app, "POST", PLAN_PATH, body={"mode": "best"})
        self.assertEqual((status, plan["mode"], plan["kept"]), (200, "best", True))


if __name__ == "__main__":
    unittest.main()
