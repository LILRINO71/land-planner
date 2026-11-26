"""What a forecast starts from (tools/menifee.py, the functions under that heading), on recorded answers and on
small made-up answers. The recorded answers are for the example point lon -117.166542, lat 33.652383
(tests/record_fixtures.py). The pure geometry (shares_inside, compass, patient) needs no recording at all.
Nothing here uses the network, and nothing sleeps: time.sleep is replaced wherever a retry could happen.
"""
import json
import math
import unittest
from unittest import mock

from support import EXAMPLE, SourceError, Tinytown, offline, tool
from landplanner.cities import SITE_PARTS
from landplanner.cities.menifee import Menifee

LON, LAT = -117.166542, 33.652383
COMPASS = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")
MILES_PER_DEGREE = 69.17


def lonlat(x, y):
    """The longitude and latitude of a spot x miles east and y miles north of the example point."""
    return [LON + x / (MILES_PER_DEGREE * math.cos(math.radians(LAT))), LAT + y / MILES_PER_DEGREE]


def box(x0, y0, x1, y1, clockwise=False):
    """A closed outline of a rectangle, corners in miles east and north of the point."""
    corners = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)] if clockwise else [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    ring = [lonlat(x, y) for x, y in corners]
    return ring + [ring[0]]


def centred(x, y, side, clockwise=False):
    h = side / 2
    return box(x - h, y - h, x + h, y + h, clockwise)


def shares(rings, distances=(1, 3, 5)):
    return tool.shares_inside(rings, LON, LAT, distances)


class Replayed(unittest.TestCase):
    def setUp(self):
        patcher = offline()
        self.replay = patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = mock.patch.object(tool.time, "sleep")
        self.sleeps = sleeper.start()
        self.addCleanup(sleeper.stop)


# ---------------------------------------------------------------- the 2010 census

class PeopleBefore(Replayed):
    def test_there_are_three_rings_of_people_and_homes_counted_in_2010(self):
        out = tool.people_before(LON, LAT)
        self.assertEqual(out["year"], 2010)
        self.assertIn("2010 Census", out["source"])
        rings = out["rings"]
        self.assertEqual([r["miles"] for r in rings], [1, 3, 5])
        self.assertEqual(rings[0], {"miles": 1, "people": 6338, "homes": 2023})
        self.assertTrue(all(isinstance(r["people"], int) and isinstance(r["homes"], int) for r in rings))
        self.assertTrue(all(0 < r["homes"] < r["people"] for r in rings))

    def test_more_people_live_further_out(self):
        rings = tool.people_before(LON, LAT)["rings"]
        self.assertEqual([r["people"] for r in rings], sorted(r["people"] for r in rings))
        self.assertEqual(len({r["people"] for r in rings}), 3)
        self.assertEqual([r["homes"] for r in rings], sorted(r["homes"] for r in rings))

    def test_set_beside_the_2020_count_every_ring_has_grown(self):
        before, now = tool.people_before(LON, LAT)["rings"], tool.people_near(LON, LAT)["rings"]
        for old, new in zip(before, now):
            self.assertEqual(old["miles"], new["miles"])
            self.assertGreater(new["people"], old["people"])
            self.assertGreater(new["homes"], old["homes"])

    def test_it_asks_the_2010_blocks_with_a_circle_of_each_distance(self):
        tool.people_before(LON, LAT)
        asked = [u for u in self.replay.asked if "Census2010" in u]
        self.assertEqual(len(asked), 3)
        self.assertTrue(all(u.startswith(tool.BLOCKS_2010) for u in asked))

    def test_a_count_of_nothing_is_an_error_not_zero_people(self):
        with mock.patch.object(tool, "get_json", return_value={"features": [{"attributes": {"people": None, "homes": None}}]}):
            with self.assertRaises(tool.SourceError):
                tool.people_before(LON, LAT)
        with mock.patch.object(tool, "get_json", return_value={"features": []}):
            with self.assertRaises(tool.SourceError):
                tool.people_before(LON, LAT)

    def test_homes_that_are_not_given_count_as_none_and_people_given_as_text_are_read(self):
        with mock.patch.object(tool, "get_json", return_value={"features": [{"attributes": {"people": "120", "homes": None}}]}):
            rings = tool.people_before(LON, LAT)["rings"]
        self.assertEqual(rings, [{"miles": m, "people": 120, "homes": 0} for m in (1, 3, 5)])

    def test_other_distances_can_be_asked_for_and_keep_their_order(self):
        seen = []

        def fake(url, params=None, **kw):
            seen.append(json.loads(params["geometry"]))
            return {"features": [{"attributes": {"people": len(seen), "homes": 1}}]}

        with mock.patch.object(tool, "get_json", fake):
            out = tool.people_before(LON, LAT, rings=(2, 4))
        self.assertEqual([r["miles"] for r in out["rings"]], [2, 4])
        for geometry, miles in zip(sorted(seen, key=lambda g: max(p[0] for p in g["rings"][0])), (2, 4)):
            far = max(tool.miles_between(LON, LAT, lon, lat) for lon, lat in geometry["rings"][0])
            self.assertAlmostEqual(far, miles, delta=0.05)

    def test_the_service_being_down_is_an_error_of_the_tool(self):
        self.replay.down.append("Census2010")
        with self.assertRaises(tool.SourceError):
            tool.people_before(LON, LAT)

    def test_the_2020_service_being_down_does_not_stop_the_2010_count(self):
        self.replay.down.append("Tracts_Blocks")
        self.assertEqual(tool.people_before(LON, LAT)["rings"][0]["homes"], 2023)


# ---------------------------------------------------------------- the regional plan

class RegionalPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):          # worked out once: sharing 111 planning zones out is the slow part
        patcher = offline()
        cls.replay = patcher.start()
        cls.addClassCleanup(patcher.stop)
        cls.out = tool.regional_plan(LON, LAT)

    def test_it_has_the_adopted_plan_the_draft_and_the_citys_own_figures(self):
        out = self.out
        self.assertEqual(out["within_miles"], 5)
        self.assertIn("SCAG", out["source"])
        self.assertEqual(out["adopted"]["years"], [2019, 2035, 2050])
        self.assertEqual(out["draft"]["years"], [2024, 2035, 2050])
        self.assertIn("adopted", out["adopted"]["label"])
        self.assertIn("preliminary", out["draft"]["label"])
        self.assertEqual(out["city"]["name"], "Menifee")

    def test_each_plan_has_a_ring_for_each_distance_with_households_and_jobs_for_each_of_its_years(self):
        for key in ("adopted", "draft"):
            plan = self.out[key]
            self.assertGreater(plan["zones"], 0)
            self.assertEqual([r["miles"] for r in plan["rings"]], [1, 3, 5])
            for ring in plan["rings"]:
                self.assertEqual(sorted(ring["households"]), sorted(str(y) for y in plan["years"]))
                self.assertEqual(sorted(ring["jobs"]), sorted(str(y) for y in plan["years"]))
                self.assertTrue(all(isinstance(v, int) and v >= 0 for v in list(ring["households"].values()) + list(ring["jobs"].values())))

    def test_a_wider_ring_holds_more_households_and_more_jobs_in_every_year(self):
        for key in ("adopted", "draft"):
            rings = self.out[key]["rings"]
            for year in rings[0]["households"]:
                self.assertLess(rings[0]["households"][year], rings[1]["households"][year])
                self.assertLess(rings[1]["households"][year], rings[2]["households"][year])
                self.assertLess(rings[0]["jobs"][year], rings[1]["jobs"][year])
                self.assertLess(rings[1]["jobs"][year], rings[2]["jobs"][year])

    def test_the_plans_expect_more_households_later(self):
        for ring in self.out["adopted"]["rings"]:
            h = ring["households"]
            self.assertLess(h["2019"], h["2035"])
            self.assertLess(h["2035"], h["2050"])
        self.assertEqual(self.out["adopted"]["rings"][1]["households"]["2019"], 15399)

    def test_the_citys_own_figures_carry_both_years(self):
        city = self.out["city"]
        self.assertEqual(set(city["households"]), {"2019", "2050"})
        self.assertEqual(set(city["jobs"]), {"2019", "2050"})
        self.assertLess(city["households"]["2019"], city["households"]["2050"])

    def test_the_three_asked_layers_are_the_regions_adopted_plan_its_draft_and_its_cities(self):
        asked = " ".join(self.replay.asked)
        for word in ("SED_TAZTier2Estimates", "SED_TAZTier2_Prelim", "SED_CityEstimates"):
            self.assertIn(word, asked)

    def test_the_whole_answer_can_be_sent_as_json(self):
        json.dumps(self.out)


class RegionalPlanOnMadeUpZones(unittest.TestCase):
    """The planning zones are made-up squares at known distances, so every share can be reasoned out."""
    FIELDS = {"adopted": ("hh_19", "hh_35", "hh_50", "emp_19", "emp_35", "emp_50"),
              "draft": ("HH24", "HH35", "HH50", "EMP24", "EMP35", "EMP50")}

    def zone(self, ring, values, draft=False):
        names = self.FIELDS["draft" if draft else "adopted"]
        return {"attributes": dict(zip(names, values)), "geometry": {"rings": [ring]}}

    def run_with(self, adopted, draft, city=None, distances=(1, 3, 5)):
        def fake_circle(layer, lon, lat, miles, fields, **kw):
            found = adopted if layer == tool.SCAG_ADOPTED else draft
            if isinstance(found, Exception):
                raise found
            return found or []

        with mock.patch.object(tool, "in_circle", fake_circle), \
                mock.patch.object(tool, "at_point", return_value=city):
            return tool.regional_plan(LON, LAT, distances)

    def test_a_zone_is_shared_out_by_how_much_of_it_lies_inside_each_ring(self):
        near = self.zone(centred(0, 0, 0.04), (100, 200, 300, 10, 20, 30))
        east = self.zone(centred(2, 0, 0.04), (1000, 2000, 3000, 100, 200, 300))
        north = self.zone(centred(0, 4, 0.04), (10000, 20000, 30000, 1000, 2000, 3000))
        far = self.zone(centred(0, 9, 0.04), (777, 777, 777, 777, 777, 777))
        out = self.run_with([near, east, north, far], None)
        rings = {r["miles"]: r for r in out["adopted"]["rings"]}
        self.assertEqual(rings[1]["households"], {"2019": 100, "2035": 200, "2050": 300})
        self.assertEqual(rings[3]["households"], {"2019": 1100, "2035": 2200, "2050": 3300})
        self.assertEqual(rings[5]["households"], {"2019": 11100, "2035": 22200, "2050": 33300})
        self.assertEqual(rings[1]["jobs"], {"2019": 10, "2035": 20, "2050": 30})
        self.assertEqual(rings[5]["jobs"], {"2019": 1110, "2035": 2220, "2050": 3330})
        self.assertEqual(out["adopted"]["zones"], 4, "a zone the rings do not reach is still counted as read")

    def test_a_zone_half_inside_a_ring_gives_about_half(self):
        half = self.zone(box(0, -1, 2, 1), (1000, 0, 0, 0, 0, 0))
        out = self.run_with([half], None)
        # a quarter of the way: the half circle of a one mile ring is 0.39 of this 2 x 2 mile zone
        self.assertAlmostEqual(out["adopted"]["rings"][0]["households"]["2019"], 392, delta=4)
        self.assertEqual(out["adopted"]["rings"][1]["households"]["2019"], 1000)

    def test_the_years_of_each_plan_are_its_own(self):
        z = self.zone(centred(0, 0, 0.04), (5, 6, 7, 1, 2, 3))
        d = self.zone(centred(0, 0, 0.04), (50, 60, 70, 10, 20, 30), draft=True)
        out = self.run_with([z], [d])
        self.assertEqual(out["adopted"]["rings"][0]["households"], {"2019": 5, "2035": 6, "2050": 7})
        self.assertEqual(out["draft"]["rings"][0]["households"], {"2024": 50, "2035": 60, "2050": 70})
        self.assertEqual(out["draft"]["rings"][0]["jobs"], {"2024": 10, "2035": 20, "2050": 30})

    def test_a_figure_the_agency_left_empty_counts_as_nothing(self):
        z = self.zone(centred(0, 0, 0.04), (None, 6, "", 1, None, 3))
        out = self.run_with([z], None)
        self.assertEqual(out["adopted"]["rings"][0]["households"], {"2019": 0, "2035": 6, "2050": 0})
        self.assertEqual(out["adopted"]["rings"][0]["jobs"], {"2019": 1, "2035": 0, "2050": 3})

    def test_a_plan_with_no_zones_is_left_out_and_the_other_one_still_answers(self):
        d = self.zone(centred(0, 0, 0.04), (50, 60, 70, 10, 20, 30), draft=True)
        out = self.run_with([], [d])
        self.assertIsNone(out["adopted"])
        self.assertEqual(out["draft"]["zones"], 1)

    def test_a_plan_that_did_not_answer_is_left_out_and_the_other_one_still_answers(self):
        z = self.zone(centred(0, 0, 0.04), (5, 6, 7, 1, 2, 3))
        out = self.run_with([z], tool.SourceError("(test) down"))
        self.assertIsNotNone(out["adopted"])
        self.assertIsNone(out["draft"])

    def test_with_neither_plan_there_is_an_error_not_an_empty_answer(self):
        for adopted, draft in (([], []), (tool.SourceError("a"), tool.SourceError("b")), ([], tool.SourceError("b"))):
            with self.subTest(adopted=adopted, draft=draft):
                with self.assertRaises(tool.SourceError):
                    self.run_with(adopted, draft)

    def test_the_citys_figures_come_from_its_own_layer_and_are_none_when_it_has_no_name(self):
        z = self.zone(centred(0, 0, 0.04), (5, 6, 7, 1, 2, 3))
        city = {"city": " Menifee ", "hh_19": 34000, "hh_50": 49100, "emp_19": 17300, "emp_50": 31300}
        out = self.run_with([z], None, city)
        self.assertEqual(out["city"], {"name": "Menifee", "households": {"2019": 34000, "2050": 49100}, "jobs": {"2019": 17300, "2050": 31300}})
        self.assertIsNone(self.run_with([z], None, None)["city"])
        self.assertIsNone(self.run_with([z], None, {"city": ""})["city"])

    def test_the_citys_layer_not_answering_does_not_stop_the_rest(self):
        z = self.zone(centred(0, 0, 0.04), (5, 6, 7, 1, 2, 3))

        def fake_circle(layer, *a, **kw):
            return [z]

        with mock.patch.object(tool, "in_circle", fake_circle), mock.patch.object(tool, "at_point", side_effect=tool.SourceError("(test)")):
            out = tool.regional_plan(LON, LAT)
        self.assertIsNone(out["city"])
        self.assertEqual(out["adopted"]["zones"], 1)

    def test_other_distances_give_other_rings(self):
        z = self.zone(centred(1.5, 0, 0.04), (100, 0, 0, 0, 0, 0))
        out = self.run_with([z], None, distances=(1, 2))
        self.assertEqual([r["miles"] for r in out["adopted"]["rings"]], [1, 2])
        self.assertEqual([r["households"]["2019"] for r in out["adopted"]["rings"]], [0, 100])
        self.assertEqual(out["within_miles"], 2)

    def test_a_zone_with_no_outline_gives_no_share(self):
        z = {"attributes": dict(zip(self.FIELDS["adopted"], (5, 6, 7, 1, 2, 3))), "geometry": {}}
        out = self.run_with([z], None)
        self.assertEqual(out["adopted"]["rings"][0]["households"], {"2019": 0, "2035": 0, "2050": 0})


class RegionalPlanDown(Replayed):
    def test_one_plan_down_leaves_the_other_and_says_nothing_for_it(self):
        self.replay.down.append("SED_TAZTier2_Prelim")
        out = tool.regional_plan(LON, LAT)
        self.assertIsNone(out["draft"])
        self.assertEqual(out["adopted"]["years"], [2019, 2035, 2050])
        self.assertEqual(out["city"]["name"], "Menifee")

    def test_the_adopted_plan_down_leaves_the_draft(self):
        self.replay.down.append("SED_TAZTier2Estimates")
        out = tool.regional_plan(LON, LAT)
        self.assertIsNone(out["adopted"])
        self.assertEqual(out["draft"]["years"], [2024, 2035, 2050])

    def test_both_plans_down_is_an_error_of_the_tool(self):
        self.replay.down.extend(["SED_TAZTier2Estimates", "SED_TAZTier2_Prelim"])
        with self.assertRaises(tool.SourceError):
            tool.regional_plan(LON, LAT)

    def test_the_whole_agency_down_is_an_error_of_the_tool(self):
        self.replay.down.append("rdp.scag.ca.gov")
        with self.assertRaises(tool.SourceError):
            tool.regional_plan(LON, LAT)

    def test_only_the_citys_figures_down_leaves_everything_else(self):
        self.replay.down.append("SED_CityEstimates")
        out = tool.regional_plan(LON, LAT)
        self.assertIsNone(out["city"])
        self.assertIsNotNone(out["adopted"])
        self.assertIsNotNone(out["draft"])


# ---------------------------------------------------------------- census tracts

class TractsNear(Replayed):
    def setUp(self):
        super().setUp()
        self.out = tool.tracts_near(LON, LAT)
        self.rows = self.out["tracts"]

    def test_the_answer_names_the_county_the_survey_years_and_the_source(self):
        out = self.out
        self.assertEqual(out["within_miles"], 5.0)
        self.assertEqual(out["county"], {"name": "Riverside County", "income": 89672})
        self.assertEqual(out["survey"], {"income": "2018-2022", "homes": "2018-2022", "households": "2018-2022"})
        self.assertIn("American Community Survey", out["source"])

    def test_every_tract_carries_income_households_owners_and_renters(self):
        self.assertEqual(len(self.rows), 36)
        for t in self.rows:
            self.assertTrue(t["id"].startswith("06065"), t["id"])
            self.assertTrue(t["name"].startswith("Census Tract"), t["name"])
            self.assertIsInstance(t["income"], (int, float))
            self.assertGreater(t["income"], 0)
            self.assertGreater(t["households"], 0)
            self.assertEqual(t["owners"] + t["renters"], t["households"])
            self.assertGreaterEqual(t["homes"], t["households"])
            self.assertTrue(0 <= t["built_2020_on"] <= t["homes"])
            self.assertTrue(0 <= t["built_2010s"] <= t["homes"])

    def test_the_tract_ids_are_unique_and_the_rows_run_nearest_first(self):
        self.assertEqual(len({t["id"] for t in self.rows}), len(self.rows))
        distances = [t["miles_away"] for t in self.rows]
        self.assertEqual(distances, sorted(distances))
        self.assertTrue(all(0 < d < 8 for d in distances))

    def test_every_tract_has_a_place_and_a_direction_from_the_point(self):
        for t in self.rows:
            self.assertIn(t["direction"], COMPASS)
            self.assertTrue(33.5 < t["lat"] < 33.8 and -117.4 < t["lon"] < -116.9, (t["lat"], t["lon"]))
            self.assertAlmostEqual(t["miles_away"], tool.miles_between(LON, LAT, t["lon"], t["lat"]), delta=0.01)
            self.assertEqual(t["direction"], tool.compass(LON, LAT, t["lon"], t["lat"]))

    def test_each_tract_carries_the_share_of_its_area_inside_each_ring(self):
        for t in self.rows:
            share = t["share_within"]
            self.assertEqual(set(share), {1, 3, 5})
            self.assertTrue(all(isinstance(v, float) and 0.0 <= v <= 1.0 for v in share.values()), share)
            self.assertLessEqual(share[1], share[3])
            self.assertLessEqual(share[3], share[5])
            self.assertGreater(share[5], 0, "a tract with no area in the widest ring would not have been kept")

    def test_some_tracts_lie_wholly_inside_and_some_only_touch_the_rings(self):
        self.assertTrue(any(t["share_within"][3] == 1.0 for t in self.rows))
        self.assertTrue(any(0 < t["share_within"][5] < 1 for t in self.rows))
        self.assertTrue(any(t["share_within"][1] > 0 for t in self.rows))
        self.assertTrue(any(t["share_within"][1] == 0 for t in self.rows))

    def test_the_homes_the_rings_share_out_are_about_the_homes_the_census_counted(self):
        # tract homes shared by area should be the same order of size as the block count in the 3 mile ring
        shared = sum(t["homes"] * t["share_within"][3] for t in self.rows)
        counted = tool.people_near(LON, LAT)["rings"][1]["homes"]
        self.assertGreater(shared, 0.6 * counted)
        self.assertLess(shared, 1.6 * counted)

    def test_the_answer_can_be_sent_as_json(self):
        json.dumps(self.out)

    def test_the_tracts_are_found_by_a_box_around_the_circle(self):
        tool_calls = [u for u in self.replay.asked if u.endswith("FeatureServer/2/query") and "Median_Income" in u]
        self.assertEqual(len(tool_calls), 1)

    def test_a_service_that_refuses_once_is_asked_again_after_a_pause(self):
        real = tool.get_json
        state = {"refused": 0}

        def flaky(url, params=None, **kw):
            if "Median_Income" in url and url.endswith("FeatureServer/2/query") and not state["refused"]:
                state["refused"] += 1
                raise tool.SourceError("(test) refused")
            return real(url, params, **kw)

        with mock.patch.object(tool, "get_json", flaky):
            again = tool.tracts_near(LON, LAT)
        self.assertEqual(again, self.out)
        self.sleeps.assert_called_with(0.8)


class TractsOnMadeUpAnswers(unittest.TestCase):
    """A made-up survey service: three tracts and what each of the three tables says about them."""

    def setUp(self):
        sleeper = mock.patch.object(tool.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)
        self.asked = []

    def feature(self, geoid, name, income, ring):
        return {"attributes": {"GEOID": geoid, "NAME": name, "B19049_001E": income}, "geometry": {"rings": [ring]}}

    def survey(self, features, tenure=None, built=None, county=None, income_text="Source: ACS 2018-2022", fail=()):
        def fake(url, params=None, **kw):
            self.asked.append((url, params, kw))
            for word in fail:
                if word in url:
                    raise tool.SourceError(f"(test) {word} is down")
            if url == tool.ACS_INCOME:
                return {"copyrightText": income_text}
            if url in (tool.ACS_TENURE, tool.ACS_BUILT):
                return {"copyrightText": "ACS 2019-2023"}
            if url == f"{tool.ACS_INCOME}/{tool.ACS_TRACTS}/query":
                return {"features": features}
            if url == f"{tool.ACS_TENURE}/{tool.ACS_TRACTS}/query":
                return {"features": tenure or []}
            if url == f"{tool.ACS_BUILT}/{tool.ACS_TRACTS}/query":
                return {"features": built or []}
            if url == f"{tool.ACS_INCOME}/{tool.ACS_COUNTIES}/query":
                return {"features": [{"attributes": county}] if county else []}
            raise AssertionError(f"not expected: {url}")

        return mock.patch.object(tool, "get_json", fake)

    def three_tracts(self):
        return [self.feature("A1", "Census Tract 1.01, Riverside County, California", 100000, centred(0.4, 0, 0.6)),
                self.feature("B2", "Census Tract 2; Riverside", None, centred(1.8, 1.8, 0.6)),
                self.feature("C3", "Census Tract 3", 70000, centred(0, -3, 2.0))]

    def tenure(self):
        return [{"attributes": {"GEOID": "A1", "B25003_001E": 500, "B25003_002E": 400, "B25003_003E": 100}},
                {"attributes": {"GEOID": "B2", "B25003_001E": 300, "B25003_002E": 100, "B25003_003E": 200}},
                {"attributes": {"GEOID": "UNKNOWN", "B25003_001E": 9, "B25003_002E": 9, "B25003_003E": 0}}]

    def built(self):
        return [{"attributes": {"GEOID": "A1", "B25034_001E": 520, "B25034_002E": 30, "B25034_003E": 90}},
                {"attributes": {"GEOID": "C3", "B25034_001E": 800, "B25034_002E": 0, "B25034_003E": 10}}]

    def test_a_tract_is_shared_out_by_its_area_and_its_tables_are_joined_by_number(self):
        with self.survey(self.three_tracts(), self.tenure(), self.built(), {"NAME": "Riverside County", "B19049_001E": 89672}):
            out = tool.tracts_near(LON, LAT)
        rows = {t["id"]: t for t in out["tracts"]}
        self.assertEqual(set(rows), {"A1", "B2", "C3"})
        a, b, c = rows["A1"], rows["B2"], rows["C3"]
        self.assertEqual(a["share_within"], {1: 1.0, 3: 1.0, 5: 1.0})
        self.assertEqual(b["share_within"][1], 0.0)
        self.assertEqual(b["share_within"][3], 1.0)
        self.assertEqual(c["share_within"][1], 0.0)
        self.assertAlmostEqual(c["share_within"][3], 0.4715, delta=0.01)       # a 2 x 2 mile tract whose near edge is 2 miles south
        self.assertEqual(c["share_within"][5], 1.0)
        self.assertEqual((a["households"], a["owners"], a["renters"]), (500, 400, 100))
        self.assertEqual((a["homes"], a["built_2020_on"], a["built_2010s"]), (520, 30, 90))
        self.assertEqual((b["households"], b["owners"], b["renters"]), (300, 100, 200))
        self.assertNotIn("homes", b, "a table with no row for the tract leaves its figures out")
        self.assertNotIn("households", c)
        self.assertEqual(c["homes"], 800)

    def test_names_are_cut_at_the_first_comma_or_semicolon(self):
        with self.survey(self.three_tracts(), county={"NAME": "X", "B19049_001E": 1}):
            names = {t["id"]: t["name"] for t in tool.tracts_near(LON, LAT)["tracts"]}
        self.assertEqual(names, {"A1": "Census Tract 1.01", "B2": "Census Tract 2", "C3": "Census Tract 3"})

    def test_an_income_the_survey_leaves_empty_stays_empty(self):
        with self.survey(self.three_tracts(), county={"NAME": "X", "B19049_001E": 1}):
            rows = {t["id"]: t for t in tool.tracts_near(LON, LAT)["tracts"]}
        self.assertIsNone(rows["B2"]["income"])
        self.assertEqual(rows["A1"]["income"], 100000)

    def test_the_censuss_codes_for_not_worked_out_are_left_empty_never_kept_as_numbers(self):
        features = [self.feature("A1", "Tract A", -666666666, centred(0.4, 0, 0.6)),
                    self.feature("B2", "Tract B", 85000, centred(1.8, 1.8, 0.6)),
                    self.feature("C3", "Tract C", 0, centred(0, -3, 2.0))]
        tenure = [{"attributes": {"GEOID": "A1", "B25003_001E": -666666666, "B25003_002E": -666666666, "B25003_003E": -222222222}},
                  {"attributes": {"GEOID": "B2", "B25003_001E": 300, "B25003_002E": 0, "B25003_003E": 300}}]
        built = [{"attributes": {"GEOID": "A1", "B25034_001E": -666666666, "B25034_002E": -1, "B25034_003E": None}},
                 {"attributes": {"GEOID": "C3", "B25034_001E": 800, "B25034_002E": 0, "B25034_003E": 10}}]
        with self.survey(features, tenure, built, {"NAME": "X", "B19049_001E": -666666666}):
            out = tool.tracts_near(LON, LAT)
        rows = {t["id"]: t for t in out["tracts"]}
        self.assertEqual([rows["A1"][k] for k in ("income", "households", "owners", "renters")], [None] * 4)
        self.assertEqual([rows["A1"][k] for k in ("homes", "built_2020_on", "built_2010s")], [None] * 3)
        self.assertIsNone(rows["C3"]["income"], "an income of nothing is not an income")
        self.assertEqual((rows["B2"]["income"], rows["B2"]["households"], rows["B2"]["owners"], rows["B2"]["renters"]), (85000, 300, 0, 300))
        self.assertEqual((rows["C3"]["homes"], rows["C3"]["built_2020_on"]), (800, 0), "a count of none is a real count")
        self.assertIsNone(out["county"]["income"])

    def test_text_and_absurd_figures_are_not_kept_either_and_number_text_is_read(self):
        features = [self.feature("A1", "Tract A", "n/a", centred(0.4, 0, 0.6)),
                    self.feature("B2", "Tract B", "85000", centred(1.8, 1.8, 0.6)),
                    self.feature("C3", "Tract C", 10 ** 9, centred(0, -3, 2.0))]
        tenure = [{"attributes": {"GEOID": "A1", "B25003_001E": "many", "B25003_002E": 10 ** 9, "B25003_003E": float("nan")}}]
        with self.survey(features, tenure, None, {"NAME": "X", "B19049_001E": 89672.0}):
            out = tool.tracts_near(LON, LAT)
        rows = {t["id"]: t for t in out["tracts"]}
        self.assertEqual((rows["A1"]["income"], rows["C3"]["income"]), (None, None))
        self.assertEqual(rows["B2"]["income"], 85000)
        self.assertEqual([rows["A1"][k] for k in ("households", "owners", "renters")], [None] * 3)
        self.assertEqual(out["county"]["income"], 89672)
        json.dumps(out)

    def test_a_good_survey_is_unchanged_by_the_cleaning(self):
        with self.survey(self.three_tracts(), self.tenure(), self.built(), {"NAME": "Riverside County", "B19049_001E": 89672}):
            out = tool.tracts_near(LON, LAT)
        rows = {t["id"]: t for t in out["tracts"]}
        self.assertEqual((rows["A1"]["income"], rows["A1"]["households"], rows["A1"]["homes"]), (100000, 500, 520))
        self.assertIsInstance(rows["A1"]["income"], int)
        self.assertEqual(out["county"], {"name": "Riverside County", "income": 89672})

    def test_rows_run_nearest_first(self):
        with self.survey(self.three_tracts(), county={"NAME": "X", "B19049_001E": 1}):
            out = tool.tracts_near(LON, LAT)["tracts"]
        self.assertEqual([t["id"] for t in out], ["A1", "B2", "C3"])
        self.assertEqual([t["miles_away"] for t in out], sorted(t["miles_away"] for t in out))
        self.assertEqual([t["direction"] for t in out], ["east", "north-east", "south"])

    def test_a_tract_in_the_corner_of_the_box_outside_the_circle_is_left_out(self):
        corner = self.feature("CORNER", "Census Tract 9", 50000, centred(4.9, 4.9, 0.2))
        with self.survey([corner] + self.three_tracts(), county={"NAME": "X", "B19049_001E": 1}):
            ids = [t["id"] for t in tool.tracts_near(LON, LAT)["tracts"]]
        self.assertNotIn("CORNER", ids)
        self.assertEqual(len(ids), 3)

    def test_a_tract_with_no_number_or_no_outline_is_skipped(self):
        broken = [self.feature(None, "No number", 1, centred(0, 0, 1)), self.feature("NOOUT", "No outline", 1, [])]
        broken[1]["geometry"] = {}
        with self.survey(broken + self.three_tracts(), county={"NAME": "X", "B19049_001E": 1}):
            ids = {t["id"] for t in tool.tracts_near(LON, LAT)["tracts"]}
        self.assertEqual(ids, {"A1", "B2", "C3"})

    def test_no_tract_at_all_is_an_error(self):
        for features in ([], [self.feature("X", "x", 1, centred(8, 8, 0.1))]):
            with self.subTest(features=len(features)), self.survey(features):
                with self.assertRaises(tool.SourceError):
                    tool.tracts_near(LON, LAT)

    def test_the_tables_are_asked_for_by_tract_number_in_one_post_each(self):
        with self.survey(self.three_tracts(), self.tenure(), self.built(), {"NAME": "X", "B19049_001E": 1}):
            tool.tracts_near(LON, LAT)
        by_table = {url: (params, kw) for url, params, kw in self.asked}
        for service in (tool.ACS_TENURE, tool.ACS_BUILT):
            params, kw = by_table[f"{service}/{tool.ACS_TRACTS}/query"]
            self.assertEqual(params["where"], "GEOID IN ('A1','B2','C3')")
            self.assertTrue(kw.get("post"))
            self.assertEqual(params["returnGeometry"], "false")

    def test_the_first_question_is_a_box_that_holds_the_whole_circle(self):
        with self.survey(self.three_tracts(), county={"NAME": "X", "B19049_001E": 1}):
            tool.tracts_near(LON, LAT, miles=5.0)
        params = next(p for url, p, _ in self.asked if url == f"{tool.ACS_INCOME}/{tool.ACS_TRACTS}/query")
        west, south, east, north = (float(v) for v in params["geometry"].split(","))
        self.assertEqual(params["geometryType"], "esriGeometryEnvelope")
        self.assertAlmostEqual(tool.miles_between(LON, LAT, LON, north), 5.0, delta=0.01)
        self.assertAlmostEqual(tool.miles_between(LON, LAT, west, LAT), 5.0, delta=0.02)
        self.assertAlmostEqual(tool.miles_between(LON, LAT, east, LAT), 5.0, delta=0.02)
        self.assertAlmostEqual(tool.miles_between(LON, LAT, LON, south), 5.0, delta=0.01)

    def test_a_county_the_survey_does_not_have_leaves_its_name_and_income_empty(self):
        with self.survey(self.three_tracts(), county=None):
            out = tool.tracts_near(LON, LAT)
        self.assertEqual(out["county"], {"name": "", "income": None})

    def test_the_survey_years_are_read_from_each_services_own_words_or_left_empty(self):
        with self.survey(self.three_tracts(), county={"NAME": "X", "B19049_001E": 1}, income_text="ACS 2018 - 2022 estimates"):
            out = tool.tracts_near(LON, LAT)
        self.assertEqual(out["survey"], {"income": "2018-2022", "homes": "2019-2023", "households": "2019-2023"})
        with self.survey(self.three_tracts(), county={"NAME": "X", "B19049_001E": 1}, income_text="no years here"):
            self.assertIsNone(tool.tracts_near(LON, LAT)["survey"]["income"])

    def test_the_survey_years_not_answering_does_not_stop_the_rest(self):
        with self.survey(self.three_tracts(), self.tenure(), self.built(), {"NAME": "X", "B19049_001E": 1}) as fake:
            real = tool.get_json

            def survey_years_down(url, params=None, **kw):
                if url in (tool.ACS_INCOME, tool.ACS_TENURE, tool.ACS_BUILT):
                    raise tool.SourceError("(test) no description")
                return real(url, params, **kw)

            with mock.patch.object(tool, "get_json", survey_years_down):
                out = tool.tracts_near(LON, LAT)
        self.assertEqual(out["survey"], {"income": None, "homes": None, "households": None})
        self.assertEqual(len(out["tracts"]), 3)

    def test_each_table_that_is_down_is_an_error_after_three_tries(self):
        for word in (f"{tool.ACS_INCOME}/{tool.ACS_TRACTS}/query", f"{tool.ACS_TENURE}/{tool.ACS_TRACTS}/query",
                     f"{tool.ACS_BUILT}/{tool.ACS_TRACTS}/query", f"{tool.ACS_INCOME}/{tool.ACS_COUNTIES}/query"):
            with self.subTest(table=word.rsplit("/", 3)[-3]):
                self.asked.clear()
                with self.survey(self.three_tracts(), self.tenure(), self.built(), {"NAME": "X", "B19049_001E": 1}, fail=(word,)):
                    with self.assertRaises(tool.SourceError):
                        tool.tracts_near(LON, LAT)
                self.assertEqual(sum(1 for url, _, _ in self.asked if url == word), 3)


class TractsDown(Replayed):
    def test_the_income_table_down_is_an_error_of_the_tool_after_three_tries(self):
        self.replay.down.append("Median_Income_by_Race_and_Age_Selp_Emp_Boundaries/FeatureServer/2")
        with self.assertRaises(tool.SourceError):
            tool.tracts_near(LON, LAT)
        self.assertEqual(sum(1 for u in self.replay.asked if "Median_Income" in u and u.endswith("FeatureServer/2/query")), 3)
        self.assertEqual([c.args[0] for c in self.sleeps.call_args_list], [0.8, 1.6])

    def test_the_tenure_table_down_is_an_error_of_the_tool(self):
        self.replay.down.append("ACS_Housing_Tenure")
        with self.assertRaises(tool.SourceError):
            tool.tracts_near(LON, LAT)

    def test_the_homes_built_table_down_is_an_error_of_the_tool(self):
        self.replay.down.append("ACS_Housing_Units_by_Year_Built")
        with self.assertRaises(tool.SourceError):
            tool.tracts_near(LON, LAT)

    def test_the_county_layer_down_is_an_error_of_the_tool(self):
        self.replay.down.append("Boundaries/FeatureServer/1/query")
        with self.assertRaises(tool.SourceError):
            tool.tracts_near(LON, LAT)

    def test_the_whole_survey_host_down_is_an_error_of_the_tool(self):
        self.replay.down.append("P3ePLMYs2RVChkJx")
        with self.assertRaises(tool.SourceError):
            tool.tracts_near(LON, LAT)


# ---------------------------------------------------------------- the city adapter's trend parts

class TrendPartsOfTheAdapter(Replayed):
    def setUp(self):
        super().setUp()
        self.city = Menifee()
        self.parcel = self.city.parcel(EXAMPLE)

    def test_the_trend_group_is_these_three_parts(self):
        self.assertEqual({p for p, g in SITE_PARTS.items() if g == "trend"}, {"people_before", "regional_plan", "tracts"})

    def test_the_city_names_a_source_for_each_trend_part(self):
        for part in ("people_before", "regional_plan", "tracts"):
            self.assertTrue(self.city.sources.get(part), part)

    def test_each_part_is_served_for_the_example_parcel(self):
        before = self.city.site_part("people_before", self.parcel)
        self.assertEqual((before["year"], [r["miles"] for r in before["rings"]]), (2010, [1, 3, 5]))
        plan = self.city.site_part("regional_plan", self.parcel)
        self.assertEqual((plan["adopted"]["years"], plan["draft"]["years"]), ([2019, 2035, 2050], [2024, 2035, 2050]))
        tracts = self.city.site_part("tracts", self.parcel)
        self.assertEqual(len(tracts["tracts"]), 36)

    def test_it_is_the_same_as_asking_the_tool_at_the_parcels_centre(self):
        lon, lat = self.parcel["centre"]["lon"], self.parcel["centre"]["lat"]
        self.assertEqual(self.city.site_part("people_before", self.parcel), tool.people_before(lon, lat))
        self.assertEqual(self.city.site_part("regional_plan", self.parcel), tool.regional_plan(lon, lat))

    def test_a_service_that_is_down_is_an_error_of_the_app_not_of_the_tool(self):
        for word, part in (("Census2010", "people_before"), ("rdp.scag.ca.gov", "regional_plan"), ("P3ePLMYs2RVChkJx", "tracts")):
            with self.subTest(part=part):
                self.replay.down[:] = [word]
                with self.assertRaises(SourceError) as caught:
                    self.city.site_part(part, self.parcel)
                self.assertNotIsInstance(caught.exception, tool.SourceError)

    def test_a_city_that_does_not_cover_a_trend_part_returns_nothing_for_it(self):
        town = Tinytown()
        for part in ("people_before", "regional_plan", "tracts"):
            self.assertIsNone(town.site_part(part, {"zoning": "R-1"}))


# ---------------------------------------------------------------- shares_inside: pure geometry

class SharesInside(unittest.TestCase):
    def test_a_small_square_wholly_inside_every_ring_is_all_inside(self):
        self.assertEqual(shares([centred(0.3, 0.1, 0.2)]), {1: 1.0, 3: 1.0, 5: 1.0})

    def test_a_square_far_outside_every_ring_has_none_inside(self):
        self.assertEqual(shares([centred(10, 0, 1)]), {1: 0.0, 3: 0.0, 5: 0.0})
        self.assertEqual(shares([centred(0, -9, 2)]), {1: 0.0, 3: 0.0, 5: 0.0})

    def test_a_square_between_two_rings_is_inside_only_the_wider_ones(self):
        self.assertEqual(shares([centred(2.0, 0, 0.2)]), {1: 0.0, 3: 1.0, 5: 1.0})
        self.assertEqual(shares([centred(4.0, 0, 0.2)]), {1: 0.0, 3: 0.0, 5: 1.0})

    def test_a_square_centred_on_the_point_but_larger_than_the_circle_is_the_circles_share_of_it(self):
        got = shares([centred(0, 0, 20)])
        for miles in (1, 3, 5):
            self.assertAlmostEqual(got[miles], math.pi * miles ** 2 / 400, delta=0.001, msg=miles)

    def test_the_share_grows_with_the_distance(self):
        got = shares([centred(1.0, 0.5, 8)])
        self.assertLess(got[1], got[3])
        self.assertLess(got[3], got[5])
        self.assertLessEqual(got[5], 1.0)

    def test_a_square_cut_by_the_ring_gives_the_part_inside(self):
        # x from 0.5 to 2.5 and y from -1 to 1: the one mile circle cuts a segment 0.5 mile from its middle
        got = shares([box(0.5, -1, 2.5, 1)])
        segment = math.acos(0.5) - 0.5 * math.sqrt(0.75)
        self.assertAlmostEqual(got[1], segment / 4, delta=0.003)
        self.assertEqual((got[3], got[5]), (1.0, 1.0))

    def test_half_of_a_square_through_the_point_is_about_half_of_what_the_circle_covers(self):
        got = shares([box(0, -1, 2, 1)])
        self.assertAlmostEqual(got[1], (math.pi / 2) / 4, delta=0.003)

    def test_the_way_round_the_outline_is_drawn_makes_no_difference(self):
        outline = box(0.5, -1, 2.5, 1)
        self.assertEqual(shares([outline]), shares([list(reversed(outline))]))
        self.assertEqual(shares([box(0.5, -1, 2.5, 1, clockwise=True)]), shares([outline]))

    def test_the_same_shape_on_the_other_side_gives_the_same_share(self):
        east, west, north, south = (shares([centred(x, y, 1.0)]) for x, y in ((2, 0), (-2, 0), (0, 2), (0, -2)))
        self.assertEqual(east, west)
        self.assertEqual(north, south)
        for key in (1, 3, 5):
            self.assertAlmostEqual(east[key], north[key], delta=0.02)

    def test_a_ring_with_a_hole_loses_the_hole(self):
        outer = centred(0, 0, 20, clockwise=True)             # the outer outline one way round, the hole the other
        hole = centred(0, 0, 2)
        with_hole, without = shares([outer, hole]), shares([outer])
        self.assertEqual(with_hole[1], 0.0, "the one mile circle lies wholly inside the hole")
        self.assertAlmostEqual(with_hole[3], (3.1326 * 9 - 4) / 396, delta=0.001)
        self.assertAlmostEqual(with_hole[5], (3.1326 * 25 - 4) / 396, delta=0.001)
        self.assertLess(with_hole[1], without[1])
        self.assertLess(with_hole[3], without[3])
        self.assertLess(with_hole[5], without[5])

    def test_a_hole_works_whichever_way_the_outer_outline_runs(self):
        a = shares([centred(0, 0, 20, clockwise=True), centred(0, 0, 2)])
        b = shares([centred(0, 0, 20), centred(0, 0, 2, clockwise=True)])
        self.assertEqual(a, b)

    def test_a_ring_with_a_hole_is_not_the_same_as_two_pieces(self):
        pieces = shares([centred(0, 0, 20), centred(0, 0, 2)])         # both drawn the same way round: no hole
        hole = shares([centred(0, 0, 20), centred(0, 0, 2, clockwise=True)])
        self.assertGreater(pieces[3], hole[3])

    def test_two_separate_pieces_share_out_by_their_total_area(self):
        got = shares([centred(0.3, 0, 0.2), centred(4, 0, 0.2)])
        self.assertEqual(got, {1: 0.5, 3: 0.5, 5: 1.0})

    def test_nothing_to_measure_gives_zero_not_an_error(self):
        zeros = {1: 0.0, 3: 0.0, 5: 0.0}
        self.assertEqual(shares([]), zeros)
        self.assertEqual(shares(None), zeros)
        self.assertEqual(shares([[]]), zeros)
        three_points = [lonlat(0, 0), lonlat(1, 0), lonlat(0, 1)]
        self.assertEqual(shares([three_points]), zeros, "a ring needs four points to be closed around anything")
        flat = [lonlat(0, 0), lonlat(1, 0), lonlat(2, 0), lonlat(0, 0)]
        self.assertEqual(shares([flat]), zeros, "a line has no area")

    def test_the_distances_asked_for_are_the_keys_given_back(self):
        got = shares([centred(0, 0, 20)], (0.5, 2, 7.5))
        self.assertEqual(list(got), [0.5, 2, 7.5])
        self.assertEqual(shares([centred(0, 0, 20)], ()), {})
        self.assertEqual(list(shares([], (0.5, 2))), [0.5, 2])

    def test_every_share_is_between_nothing_and_everything(self):
        for rings in ([centred(0, 0, 0.001)], [centred(0, 0, 100)], [box(-50, -50, 50, 50)], [centred(1, 1, 3), centred(-2, 2, 4)]):
            with self.subTest(rings=len(rings)):
                for value in shares(rings).values():
                    self.assertTrue(0.0 <= value <= 1.0, value)

    def test_the_share_is_rounded_to_four_places(self):
        for value in shares([centred(0, 0, 7.77)]).values():
            self.assertEqual(value, round(value, 4))

    def test_it_does_not_change_the_rings_it_is_given(self):
        rings = [centred(0.5, 0, 1.0)]
        before = json.dumps(rings)
        shares(rings)
        self.assertEqual(json.dumps(rings), before)


class PlaneAndClipping(unittest.TestCase):
    def test_the_plane_measures_miles_east_and_north_of_the_point(self):
        flat = tool._plane(LON, LAT)
        self.assertEqual(flat((LON, LAT)), (0.0, 0.0))
        east = flat(tuple(lonlat(1, 0)))
        north = flat(tuple(lonlat(0, 1)))
        self.assertAlmostEqual(east[0], 1.0, places=6)
        self.assertAlmostEqual(east[1], 0.0, places=6)
        self.assertAlmostEqual(north[0], 0.0, places=6)
        self.assertAlmostEqual(north[1], 1.0, places=6)

    def test_the_signed_area_of_a_square_is_plus_or_minus_its_area_by_direction(self):
        ccw = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
        self.assertEqual(tool._signed(ccw), 4.0)
        self.assertEqual(tool._signed(list(reversed(ccw))), -4.0)
        self.assertEqual(tool._signed([(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]), 0.0)
        self.assertEqual(tool._signed([]), 0.0)

    def test_clipping_a_polygon_that_is_wholly_inside_gives_it_back(self):
        poly = [(-0.1, -0.1), (0.1, -0.1), (0.1, 0.1), (-0.1, 0.1)]
        self.assertEqual(tool._clip_to_circle(poly, 1.0), poly)

    def test_clipping_a_polygon_wholly_outside_gives_nothing(self):
        self.assertEqual(tool._clip_to_circle([(5.0, 5.0), (6.0, 5.0), (6.0, 6.0), (5.0, 6.0)], 1.0), [])

    def test_clipping_a_big_polygon_leaves_the_circle_drawn_with_straight_sides(self):
        big = [(-9.0, -9.0), (9.0, -9.0), (9.0, 9.0), (-9.0, 9.0)]
        area = tool._signed(tool._clip_to_circle(big, 2.0))
        self.assertAlmostEqual(area, 24 * 4 * math.sin(2 * math.pi / 48), places=6)
        self.assertLess(area, math.pi * 4)
        self.assertAlmostEqual(area, math.pi * 4, delta=0.05)

    def test_clipping_keeps_the_direction_so_a_hole_is_still_a_hole(self):
        big = [(-9.0, -9.0), (9.0, -9.0), (9.0, 9.0), (-9.0, 9.0)]
        self.assertGreater(tool._signed(tool._clip_to_circle(big, 2.0)), 0)
        self.assertLess(tool._signed(tool._clip_to_circle(list(reversed(big)), 2.0)), 0)

    def test_fewer_sides_make_a_coarser_circle(self):
        big = [(-9.0, -9.0), (9.0, -9.0), (9.0, 9.0), (-9.0, 9.0)]
        coarse = tool._signed(tool._clip_to_circle(big, 2.0, sides=8))
        fine = tool._signed(tool._clip_to_circle(big, 2.0, sides=96))
        self.assertLess(coarse, fine)
        self.assertLess(fine, math.pi * 4)

    def test_a_polygon_with_fewer_than_three_points_gives_nothing(self):
        self.assertEqual(tool._clip_to_circle([], 1.0), [])
        self.assertEqual(tool._clip_to_circle([(0.0, 0.0), (0.5, 0.0)], 1.0), [])


# ---------------------------------------------------------------- compass

class Compass(unittest.TestCase):
    def toward(self, bearing, miles=1.0):
        rad = math.radians(bearing)
        lon, lat = lonlat(miles * math.sin(rad), miles * math.cos(rad))
        return tool.compass(LON, LAT, lon, lat)

    def test_the_eight_directions(self):
        for i, name in enumerate(COMPASS):
            with self.subTest(name=name):
                self.assertEqual(self.toward(45 * i), name)

    def test_a_bearing_a_little_off_a_direction_is_still_that_direction(self):
        for i, name in enumerate(COMPASS):
            for off in (-20, 20):
                with self.subTest(name=name, off=off):
                    self.assertEqual(self.toward(45 * i + off), name)

    def test_past_the_edge_of_a_sector_it_is_the_next_direction(self):
        self.assertEqual(self.toward(25), "north-east")
        self.assertEqual(self.toward(-25), "north-west")
        self.assertEqual(self.toward(340), "north")
        self.assertEqual(self.toward(335), "north-west")
        self.assertEqual(self.toward(115), "south-east")

    def test_the_distance_does_not_change_the_direction(self):
        for miles in (0.01, 0.5, 7.0):
            self.assertEqual(self.toward(135, miles), "south-east")

    def test_the_same_point_is_here(self):
        self.assertEqual(tool.compass(LON, LAT, LON, LAT), "here")
        self.assertEqual(tool.compass(LON, LAT, LON + 1e-10, LAT - 1e-10), "here")

    def test_a_tiny_but_real_step_is_a_direction(self):
        self.assertEqual(tool.compass(LON, LAT, LON, LAT + 1e-6), "north")
        self.assertEqual(tool.compass(LON, LAT, LON + 1e-6, LAT), "east")

    def test_east_is_corrected_for_how_narrow_a_degree_of_longitude_is(self):
        # 20 degrees east of north on the ground is 23.6 degrees if longitude and latitude were read as equal units
        # (north-east); it is north
        lon, lat = lonlat(math.sin(math.radians(20)), math.cos(math.radians(20)))
        self.assertAlmostEqual(math.degrees(math.atan2(lon - LON, lat - LAT)), 23.6, delta=0.1)
        self.assertEqual(tool.compass(LON, LAT, lon, lat), "north")


# ---------------------------------------------------------------- patient

class Patient(unittest.TestCase):
    def setUp(self):
        sleeper = mock.patch.object(tool.time, "sleep")
        self.sleeps = sleeper.start()
        self.addCleanup(sleeper.stop)

    def failing(self, times, answer="answer"):
        calls = []

        def fn():
            calls.append(1)
            if len(calls) <= times:
                raise tool.SourceError(f"(test) refused {len(calls)}")
            return answer

        return fn, calls

    def test_an_answer_at_once_is_returned_without_waiting(self):
        fn, calls = self.failing(0)
        self.assertEqual(tool.patient(fn), "answer")
        self.assertEqual(len(calls), 1)
        self.sleeps.assert_not_called()

    def test_a_refusal_is_asked_again_after_a_pause_and_the_answer_returned(self):
        fn, calls = self.failing(2)
        self.assertEqual(tool.patient(fn), "answer")
        self.assertEqual(len(calls), 3)
        self.assertEqual([c.args[0] for c in self.sleeps.call_args_list], [0.8, 1.6])

    def test_after_the_last_try_the_error_is_raised_with_no_pause_after_it(self):
        fn, calls = self.failing(99)
        with self.assertRaises(tool.SourceError) as caught:
            tool.patient(fn)
        self.assertIn("refused 3", str(caught.exception))
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.sleeps.call_count, 2)

    def test_the_number_of_tries_can_be_changed(self):
        fn, calls = self.failing(99)
        with self.assertRaises(tool.SourceError):
            tool.patient(fn, tries=5)
        self.assertEqual((len(calls), self.sleeps.call_count), (5, 4))
        self.sleeps.reset_mock()
        fn, calls = self.failing(99)
        with self.assertRaises(tool.SourceError):
            tool.patient(fn, tries=1)
        self.assertEqual((len(calls), self.sleeps.call_count), (1, 0))

    def test_the_answer_can_be_nothing(self):
        self.assertIsNone(tool.patient(lambda: None))

    def test_an_error_of_another_kind_is_not_retried(self):
        calls = []

        def fn():
            calls.append(1)
            raise ValueError("not a refusal")

        with self.assertRaises(ValueError):
            tool.patient(fn)
        self.assertEqual(len(calls), 1)
        self.sleeps.assert_not_called()

    def test_a_not_found_is_a_kind_of_refusal_and_is_asked_again(self):
        calls = []

        def fn():
            calls.append(1)
            raise tool.NotFound("gone")

        with self.assertRaises(tool.NotFound):
            tool.patient(fn)
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
