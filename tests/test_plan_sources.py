"""What a land-use plan starts from (tools/menifee.py, the functions under that heading), on recorded answers.

The recorded answers are for the example point lon -117.166542, lat 33.652383 (tests/record_fixtures.py). The pure
helpers (read_project, builder_of, day, miles_between) need no recording at all. Nothing here uses the network.
"""
import math
import re
import unittest
from unittest import mock

from support import offline, tool

LON, LAT = -117.166542, 33.652383
BOX = (-117.1715, 33.6500, -117.1615, 33.6550)
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Replayed(unittest.TestCase):
    def setUp(self):
        patcher = offline()
        self.replay = patcher.start()
        self.addCleanup(patcher.stop)


class Streets(Replayed):
    def test_streets_are_the_classified_ones_each_with_a_line_and_a_rank(self):
        out = tool.streets_near(LON, LAT)
        self.assertEqual(out["within_miles"], 0.75)
        self.assertIn("circulation map", out["source"])
        streets = out["streets"]
        self.assertEqual(len(streets), 27, "36 stretches are recorded; the 9 with no class are left out")
        for s in streets:
            self.assertIn(s["class"].lower(), tool.STREET_RANK)
            self.assertEqual(s["rank"], tool.STREET_RANK[s["class"].lower()])
            self.assertTrue(s["paths"], "every street has a line")
            self.assertTrue(all(len(point) == 2 for path in s["paths"] for point in path))
            self.assertTrue(s["name"])
        self.assertEqual({s["class"] for s in streets}, {"Urban Arterial", "Major", "Secondary"})

    def test_a_street_names_its_class_and_its_speed_when_the_city_lists_one(self):
        streets = tool.streets_near(LON, LAT)["streets"]
        haun = [s for s in streets if s["name"] == "Haun Rd"]
        self.assertTrue(haun)
        self.assertEqual({s["class"] for s in haun}, {"Major"})
        self.assertEqual({s["rank"] for s in haun}, {3})
        self.assertIn(55, [s["speed_mph"] for s in haun])
        self.assertTrue(any(s["speed_mph"] is None for s in streets), "a speed the city leaves empty stays empty")

    def test_the_lines_are_in_longitude_and_latitude_near_the_point(self):
        for s in tool.streets_near(LON, LAT)["streets"]:
            for path in s["paths"]:
                for lon, lat in path:
                    self.assertTrue(-117.2 < lon < -117.13 and 33.62 < lat < 33.69, (lon, lat))

    def test_a_street_with_no_name_is_called_unnamed_and_one_with_no_class_is_left_out(self):
        features = [
            {"attributes": {"ST_NAME": None, "Classification": "Collector", "mnfe_speeds": 25}, "geometry": {"paths": [[[1, 2], [3, 4]]]}},
            {"attributes": {"ST_NAME": "LOCAL ST", "Classification": "Local", "mnfe_speeds": 25}, "geometry": {"paths": [[[1, 2], [3, 4]]]}},
            {"attributes": {"ST_NAME": "NO LINE RD", "Classification": "Major", "mnfe_speeds": 45}, "geometry": {"paths": []}},
            {"attributes": {"ST_NAME": "MAIN ST", "Classification": "  expressway ", "mnfe_speeds": 65}, "geometry": {"paths": [[[1, 2], [3, 4]]]}},
        ]
        with mock.patch.object(tool, "get_json", return_value={"features": features}):
            streets = tool.streets_near(0, 0, 0.5)["streets"]
        self.assertEqual([(s["name"], s["rank"]) for s in streets], [("Unnamed street", 1), ("Main St", 5)])


class Signals(Replayed):
    def test_signals_are_nearest_first_and_every_one_is_a_traffic_signal(self):
        out = tool.signals_near(LON, LAT)
        self.assertEqual(out["within_miles"], 1.5)
        signals = out["signals"]
        self.assertEqual(len(signals), 14)
        distances = [s["miles_away"] for s in signals]
        self.assertEqual(distances, sorted(distances))
        self.assertTrue(all(0 <= d <= 1.6 for d in distances))
        self.assertEqual((signals[0]["street"], signals[0]["cross_street"]), ("Antelope Rd", "Garbani Rd"))
        self.assertEqual(signals[0]["miles_away"], 0.34)
        self.assertEqual({s["status"] for s in signals}, {"Existing"})

    def test_the_distance_is_measured_from_the_asked_point(self):
        for s in tool.signals_near(LON, LAT)["signals"]:
            self.assertAlmostEqual(s["miles_away"], tool.miles_between(LON, LAT, s["lon"], s["lat"]), delta=0.01)

    def test_a_flasher_or_a_signal_with_no_place_is_left_out(self):
        features = [
            {"attributes": {"StreetName": "A RD", "CrossStreet": "B ST", "SignalType": "Flashing Beacon", "STATUS": "Existing"}, "geometry": {"x": LON, "y": LAT}},
            {"attributes": {"StreetName": "C RD", "CrossStreet": "D ST", "SignalType": "traffic signal", "STATUS": "Existing"}, "geometry": {}},
            {"attributes": {"StreetName": "E RD", "CrossStreet": "F ST", "SignalType": "Traffic Signal", "STATUS": "Planned"}, "geometry": {"x": LON, "y": LAT + 0.01}},
        ]
        with mock.patch.object(tool, "get_json", return_value={"features": features}):
            signals = tool.signals_near(LON, LAT)["signals"]
        self.assertEqual([(s["street"], s["status"]) for s in signals], [("E Rd", "Planned")])


class Schools(Replayed):
    def test_schools_are_the_nearest_eight_nearest_first(self):
        out = tool.schools_near(LON, LAT)
        self.assertEqual(out["within_miles"], 2.0)
        schools = out["schools"]
        self.assertEqual(len(schools), 8)
        distances = [s["miles_away"] for s in schools]
        self.assertEqual(distances, sorted(distances))
        self.assertTrue(all(0 <= d <= 2.1 for d in distances))
        self.assertTrue(all(s["name"] and s["grades"] and s["kind"] for s in schools))
        self.assertEqual(schools[0]["name"], "Revival Christian Academy")
        self.assertEqual((schools[0]["grades"], schools[0]["kind"], schools[0]["miles_away"]), ("K-12", "Private", 1.15))

    def test_no_more_than_eight_schools_are_given(self):
        features = [{"attributes": {"Name": f"School {i}", "GradeLevel": "High", "SchoolType": "Public"},
                     "geometry": {"x": LON + i * 0.001, "y": LAT}} for i in range(12)]
        with mock.patch.object(tool, "get_json", return_value={"features": features}):
            schools = tool.schools_near(LON, LAT)["schools"]
        self.assertEqual([s["name"] for s in schools], [f"School {i}" for i in range(8)])


class Projects(Replayed):
    def setUp(self):
        super().setUp()
        self.out = tool.projects_near(LON, LAT)
        self.projects = self.out["projects"]

    def test_projects_are_nearest_first_and_each_says_what_it_is_and_how_far(self):
        self.assertEqual(self.out["within_miles"], 3.0)
        self.assertEqual(len(self.projects), 56)
        distances = [p["miles_away"] for p in self.projects]
        self.assertEqual(distances, sorted(distances))
        for p in self.projects:
            self.assertTrue(p["title"])
            self.assertTrue(p["kind"])
            self.assertIsInstance(p["miles_away"], float)
            self.assertIsInstance(p["stated"], dict)
            self.assertIn(p["list"], {"development projects", "economic development projects, 2025"})
            self.assertTrue(33 < p["lat"] < 34 and -118 < p["lon"] < -117)

    def test_both_city_lists_are_read_and_a_project_on_both_is_counted_once(self):
        self.assertEqual({p["list"] for p in self.projects}, {"development projects", "economic development projects, 2025"})
        titles = [p["title"].lower() for p in self.projects]
        self.assertEqual(len(titles), len(set(titles)))

    def test_the_last_edit_date_of_each_list_is_given(self):
        self.assertEqual(self.out["lists_updated"], {"development projects": "2023-09-14",
                                                      "economic development projects, 2025": "2025-08-04"})

    def test_the_nearest_project_is_read_as_the_city_describes_it(self):
        first = self.projects[0]
        self.assertEqual((first["title"], first["number"], first["kind"]), ("TTM 38372", "DEV2022-008", "Residential"))
        self.assertEqual(first["miles_away"], 0.35)
        self.assertEqual(first["stated"], {}, "three planning areas with their own counts are not added up by guesswork")
        self.assertEqual(first["builder"], "")

    def test_a_builder_in_the_title_or_the_applicant_is_named(self):
        by_title = {p["title"]: p for p in self.projects}
        self.assertEqual(by_title["Quartz Ranch (Lennar)"]["builder"], "Lennar")
        self.assertEqual(by_title["The Junction (PacTen)"]["builder"], "PacTen")
        self.assertEqual(by_title["Cantelena (Richland Communities)"]["builder"], "Richland Communities")

    def test_no_builder_is_made_up_when_the_city_names_none(self):
        for p in self.projects:
            if p["builder"]:
                self.assertNotIn(p["builder"].lower(), ("none", ""))
        self.assertTrue(any(not p["builder"] for p in self.projects))

    def test_sizes_come_only_from_the_description_or_the_cities_acres_field(self):
        stated = [p for p in self.projects if p["stated"]]
        self.assertTrue(stated and len(stated) < len(self.projects))
        for p in stated:
            for key, value in p["stated"].items():
                self.assertIn(key, {"acres", "homes", "building_sq_ft"})
                self.assertGreater(value, 0)

    def test_a_housing_tract_is_never_measured_in_building_square_feet(self):
        residential = [p for p in self.projects if p["kind"].lower().startswith("residential")]
        self.assertTrue(residential)
        self.assertTrue(all("building_sq_ft" not in p["stated"] for p in residential))

    def test_a_status_the_city_calls_none_is_empty(self):
        self.assertTrue(all(p["status"].lower() != "none" for p in self.projects))

    def test_one_list_with_an_old_date_does_not_stop_the_projects(self):
        real = tool.get_json

        def only_the_layer_info_fails(url, params=None, **kw):
            if url == tool.PROJECTS:               # the layer's own description, not a query on it
                raise tool.SourceError("(test) no description")
            return real(url, params, **kw)

        with mock.patch.object(tool, "get_json", only_the_layer_info_fails):
            out = tool.projects_near(LON, LAT)
        self.assertEqual(len(out["projects"]), 56)
        self.assertEqual(out["lists_updated"], {"development projects": None, "economic development projects, 2025": "2025-08-04"})


class People(Replayed):
    def test_there_are_three_rings_and_more_people_live_further_out(self):
        out = tool.people_near(LON, LAT)
        self.assertEqual(out["year"], 2020)
        self.assertIn("Census", out["source"])
        rings = out["rings"]
        self.assertEqual([r["miles"] for r in rings], [1, 3, 5])
        people = [r["people"] for r in rings]
        homes = [r["homes"] for r in rings]
        self.assertEqual(people, sorted(people))
        self.assertEqual(len(set(people)), 3)
        self.assertEqual(homes, sorted(homes))
        self.assertEqual(rings[0], {"miles": 1, "people": 8799, "homes": 2669})
        self.assertTrue(all(isinstance(r["people"], int) and isinstance(r["homes"], int) for r in rings))
        self.assertTrue(all(0 < r["homes"] < r["people"] for r in rings))

    def test_a_count_of_nothing_is_an_error_not_zero_people(self):
        with mock.patch.object(tool, "get_json", return_value={"features": [{"attributes": {"people": None, "homes": None}}]}):
            with self.assertRaises(tool.SourceError):
                tool.people_near(LON, LAT)


class Dates(Replayed):
    def test_records_updated_gives_an_iso_date_and_names_the_source(self):
        out = tool.records_updated()
        self.assertRegex(out["parcels"], ISO)
        self.assertEqual(out["parcels"], "2026-10-28")
        self.assertIn("City of Menifee", out["source"])

    def test_the_photo_date_is_the_flight_over_the_spot(self):
        out = tool.photo_date(LON, LAT)
        self.assertEqual((out["taken"], out["year"], out["detail_metres"]), ("2022-04-15", 2022, 0.6))
        self.assertRegex(out["taken"], ISO)
        self.assertIn("National Agriculture Imagery Program", out["source"])

    def test_the_newest_flight_wins_and_a_flight_with_no_date_is_ignored(self):
        features = [{"attributes": {"Year": 2016, "acquisition_date": 1469404800000, "resolution_value": 1.0}},
                    {"attributes": {"Year": 2022, "acquisition_date": 1649980800000, "resolution_value": 0.6}},
                    {"attributes": {"Year": 2030, "acquisition_date": None, "resolution_value": 0.3}},
                    {"attributes": {"Year": 2018, "acquisition_date": 1532131200000, "resolution_value": 0.6}}]
        with mock.patch.object(tool, "get_json", return_value={"features": features}):
            out = tool.photo_date(LON, LAT)
        self.assertEqual((out["taken"], out["year"]), ("2022-04-15", 2022))

    def test_no_flights_means_no_date_not_a_made_up_one(self):
        for answer in ({"features": []}, {}, {"features": [{"attributes": {"Year": 2020, "acquisition_date": None}}]}):
            with self.subTest(answer=answer), mock.patch.object(tool, "get_json", return_value=answer):
                self.assertIsNone(tool.photo_date(LON, LAT))


class ParcelsInBox(Replayed):
    def test_every_parcel_the_view_touches_is_listed_with_its_outline(self):
        out = tool.parcels_in_box(*BOX)
        self.assertFalse(out["more"])
        parcels = out["parcels"]
        self.assertEqual([p["apn"] for p in parcels], ["360350007", "372100001", "372630004", "372630005", "372630006"])
        for p in parcels:
            self.assertEqual(set(p), {"apn", "apn_formatted", "acres", "zoning", "looks_vacant", "rings"})
            self.assertRegex(p["apn_formatted"], r"^\d{3}-\d{3}-\d{3}$")
            self.assertTrue(p["rings"] and all(len(pt) == 2 for ring in p["rings"] for pt in ring))
        big = next(p for p in parcels if p["apn"] == "372100001")
        self.assertEqual((big["acres"], big["zoning"], big["looks_vacant"]), (142.1, "EDC-CC", True))

    def test_a_view_with_more_parcels_than_the_limit_says_so(self):
        def page(offset):
            return {"features": [{"attributes": {"APN": f"{offset + i:09d}", "Zoning": " R-1 ", "Structures": 1},
                                  "geometry": {"rings": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}} for i in range(2)],
                    "exceededTransferLimit": True}

        def fake(url, params=None, **kw):
            return page(params["resultOffset"])

        with mock.patch.object(tool, "get_json", side_effect=fake) as asked:
            out = tool.parcels_in_box(*BOX, limit=4)
        self.assertTrue(out["more"])
        self.assertEqual(len(out["parcels"]), 4)
        self.assertEqual([c.args[1]["resultOffset"] for c in asked.call_args_list], [0, 2])
        self.assertEqual({p["zoning"] for p in out["parcels"]}, {"R-1"}, "stray spaces are tidied")
        self.assertEqual({p["looks_vacant"] for p in out["parcels"]}, {False})

    def test_a_row_with_no_outline_or_no_parcel_number_is_skipped(self):
        feats = [{"attributes": {"APN": "1"}, "geometry": {}}, {"attributes": {"APN": None}, "geometry": {"rings": [[[0, 0]]]}},
                 {"attributes": {"APN": "2"}, "geometry": {"rings": [[[0, 0], [1, 1], [1, 0]]]}}]
        with mock.patch.object(tool, "get_json", return_value={"features": feats}):
            out = tool.parcels_in_box(*BOX)
        self.assertEqual([p["apn"] for p in out["parcels"]], ["2"])
        self.assertFalse(out["more"])


class InACircle(unittest.TestCase):
    def test_the_question_is_a_circle_of_the_asked_radius_and_the_extra_words_are_added(self):
        with mock.patch.object(tool, "get_json", return_value={"features": [{"attributes": {"a": 1}}]}) as asked:
            found = tool.in_circle("http://layer", LON, LAT, 1.0, "A,B", geometry=False, extra={"returnCentroid": "true"})
        self.assertEqual(found, [{"attributes": {"a": 1}}])
        url, params = asked.call_args.args
        self.assertEqual(url, "http://layer/query")
        self.assertEqual((params["outFields"], params["returnGeometry"], params["returnCentroid"]), ("A,B", "false", "true"))
        import json
        ring = json.loads(params["geometry"])["rings"][0]
        self.assertEqual(ring[0], ring[-1], "the circle is closed")
        for lon, lat in ring:
            self.assertAlmostEqual(tool.miles_between(LON, LAT, lon, lat), 1.0, delta=0.01)

    def test_no_features_in_the_answer_is_an_empty_list(self):
        for answer in ({}, {"features": None}, {"features": []}):
            with self.subTest(answer=answer), mock.patch.object(tool, "get_json", return_value=answer):
                self.assertEqual(tool.in_circle("http://layer", LON, LAT, 1, "A"), [])


class ReadProject(unittest.TestCase):
    def test_acres_and_lots_of_a_housing_tract(self):
        got = tool.read_project("94.30 acres - 296 residential lots - 4,500-5,000 sq ft min.")
        self.assertEqual(got["acres"], 94.3)
        self.assertEqual(got["homes"], 296)
        self.assertNotIn("building_sq_ft", got, "a minimum lot size is not a building")

    def test_a_warehouse_has_floor_space_and_net_acres(self):
        got = tool.read_project("34.8 net acres, 700,037 sq ft warehouse building")
        self.assertEqual(got["acres"], 34.8)
        self.assertEqual(got["building_sq_ft"], 700037)
        self.assertNotIn("homes", got)

    def test_units_without_acres(self):
        got = tool.read_project("A 40 unit tract")
        self.assertEqual(got["homes"], 40)
        self.assertNotIn("acres", got)

    def test_several_buildings_of_light_industrial(self):
        got = tool.read_project("17.55-acres, 5 buildings, 283,000 sq ft light industrial and warehousing")
        self.assertEqual(got["acres"], 17.55)
        self.assertEqual(got["building_sq_ft"], 283000)
        self.assertNotIn("homes", got, "5 buildings is not a home count")

    def test_condominium_units_even_with_the_citys_spelling_and_a_trailing_space(self):
        got = tool.read_project("30.54 acres - 327 condominum units ")
        self.assertEqual(got["acres"], 30.54)
        self.assertEqual(got["homes"], 327)

    def test_two_counts_in_one_description_are_not_added_up(self):
        got = tool.read_project("TR28791: 22.2 acres - 80 res lots, 7,200sqft min, TR28792:23.8 acres - 85 res lots, 7,200sqft min.")
        self.assertEqual(got["acres"], 22.2)
        self.assertNotIn("homes", got)
        self.assertNotIn("building_sq_ft", got, "7,200sqft min is a lot size")

    def test_an_empty_description_states_nothing(self):
        self.assertEqual(tool.read_project(""), {})
        self.assertEqual(tool.read_project(None), {})
        self.assertEqual(tool.read_project("   "), {})

    def test_a_description_with_no_numbers_states_nothing(self):
        self.assertEqual(tool.read_project("Specific plan amendment for a mixed use village"), {})

    def test_several_buildings_are_added_up_for_floor_space(self):
        got = tool.read_project("9,000 sq ft office building and a 35,000 sq ft fitness center / museum")
        self.assertEqual(got["building_sq_ft"], 44000)


class BuilderOf(unittest.TestCase):
    def test_the_applicant_is_the_builder_with_stray_brackets_removed(self):
        self.assertEqual(tool.builder_of({"Applicant": "(Lennar"}), "Lennar")

    def test_a_company_in_brackets_in_the_title_is_the_builder_when_there_is_no_applicant(self):
        self.assertEqual(tool.builder_of({"Applicant": None, "ProjectTitle": "Quartz Ranch (Lennar)"}), "Lennar")

    def test_a_place_in_brackets_is_not_a_builder(self):
        self.assertEqual(tool.builder_of({"Applicant": None, "ProjectTitle": "Haun and Garbani (SE corner)"}), "")

    def test_an_applicant_the_city_wrote_as_none_is_nobody(self):
        self.assertEqual(tool.builder_of({"Applicant": "None", "ProjectTitle": "Walmart"}), "")

    def test_an_old_name_or_a_number_in_brackets_is_not_a_builder(self):
        self.assertEqual(tool.builder_of({"Applicant": None, "ProjectTitle": "Estrella (formerly Rowland)"}), "")
        self.assertEqual(tool.builder_of({"Applicant": None, "ProjectTitle": "Tract (TTM 12345)"}), "")
        self.assertEqual(tool.builder_of({"Applicant": None, "ProjectTitle": "Plaza (Smith & Sons)"}), "")

    def test_an_applicant_wins_over_a_title(self):
        self.assertEqual(tool.builder_of({"Applicant": "Richland Communities", "ProjectTitle": "Golden Meadows (Other Co)"}),
                         "Richland Communities")

    def test_nothing_at_all_is_nobody(self):
        self.assertEqual(tool.builder_of({}), "")


class DaysAndMiles(unittest.TestCase):
    def test_a_city_date_in_milliseconds_is_a_plain_date(self):
        self.assertEqual(tool.day(1649980800000), "2022-04-15")
        self.assertEqual(tool.day(0), "1970-01-01")
        self.assertEqual(tool.day("1649980800000"), "2022-04-15")

    def test_no_date_or_a_bad_one_is_none(self):
        self.assertIsNone(tool.day(None))
        self.assertIsNone(tool.day("soon"))
        self.assertIsNone(tool.day(float("inf")))
        self.assertIsNone(tool.day(10 ** 30))

    def test_a_degree_of_latitude_is_about_69_miles(self):
        self.assertAlmostEqual(tool.miles_between(-117.0, 33.0, -117.0, 34.0), 69.17, places=2)
        self.assertAlmostEqual(tool.miles_between(-117.0, 34.0, -117.0, 33.0), 69.17, places=2, msg="either way round")

    def test_a_degree_of_longitude_is_shorter_by_the_cosine_of_the_latitude(self):
        self.assertAlmostEqual(tool.miles_between(-117.0, 33.65, -116.0, 33.65), 69.17 * math.cos(math.radians(33.65)), places=2)

    def test_the_same_place_is_zero_miles(self):
        self.assertEqual(tool.miles_between(LON, LAT, LON, LAT), 0.0)


class WhenAServiceIsSilent(Replayed):
    """Each function raises the tool's own error; none of them returns a made-up answer."""

    def silent(self, word, call, *args):
        self.replay.down.append(word)
        with self.assertRaises(tool.SourceError):
            call(*args)

    def test_records_updated(self):
        self.silent("Menifee_Parcels", tool.records_updated)

    def test_photo_date(self):
        self.silent("USGSNAIPImagery", tool.photo_date, LON, LAT)

    def test_parcels_in_box(self):
        self.silent("Menifee_Parcels", tool.parcels_in_box, *BOX)

    def test_streets_near(self):
        self.silent("Circulation_Element", tool.streets_near, LON, LAT)

    def test_signals_near(self):
        self.silent("Traffic_Signals", tool.signals_near, LON, LAT)

    def test_schools_near(self):
        self.silent("Schools_Points", tool.schools_near, LON, LAT)

    def test_projects_near_when_the_development_list_is_silent(self):
        self.silent("Land_Development_Projects", tool.projects_near, LON, LAT)

    def test_projects_near_when_the_economic_development_list_is_silent(self):
        self.silent("EconDevProjects_2025", tool.projects_near, LON, LAT)

    def test_people_near(self):
        self.silent("TIGERweb", tool.people_near, LON, LAT)

    def test_the_other_services_still_answer_when_one_is_silent(self):
        self.replay.down.append("Traffic_Signals")
        self.assertTrue(tool.streets_near(LON, LAT)["streets"])
        self.assertTrue(tool.schools_near(LON, LAT)["schools"])


if __name__ == "__main__":
    unittest.main()
