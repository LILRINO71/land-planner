"""The Menifee adapter and the data tool behind it, on recorded answers (no network)."""
import unittest

from support import EXAMPLE, SQUARE, offline, tool
from landplanner.cities import CityAdapter, NotFound, SITE_PARTS, SourceError, all_cities
from landplanner.cities.base import PARCEL_FIELDS
from landplanner.cities.menifee import Menifee


class MenifeeAdapter(unittest.TestCase):
    def setUp(self):
        patcher = offline()
        self.replay = patcher.start()
        self.addCleanup(patcher.stop)
        self.city = Menifee()

    def test_it_is_registered_and_fills_in_the_interface(self):
        self.assertIsInstance(all_cities()["menifee"], CityAdapter)
        about = self.city.describe()
        self.assertEqual((about["id"], about["name"], about["region"]), ("menifee", "Menifee", "California"))
        self.assertEqual(about["large_acres"], 10.0)
        self.assertTrue(all(len(k["colour"]) == 7 for k in about["zoning_kinds"]))
        self.assertEqual(set(SITE_PARTS) - set(about["sources"]), set(), "every site part names its source")

    def test_large_parcels_are_every_parcel_of_ten_acres_up_largest_first(self):
        rows = self.city.large_parcels()
        self.assertEqual(len(rows), 345)
        self.assertTrue(all(r["acres"] >= 10 for r in rows))
        self.assertEqual([r["acres"] for r in rows], sorted((r["acres"] for r in rows), reverse=True))
        first = rows[0]
        self.assertEqual(set(PARCEL_FIELDS) - set(first), set(), "a row has every documented field")
        self.assertTrue(first["rings"] and -118 < first["centre"]["lon"] < -117 and 33 < first["centre"]["lat"] < 34)
        self.assertEqual(len({r["apn"] for r in rows}), len(rows), "no parcel twice")

    def test_a_value_the_city_leaves_empty_stays_empty(self):
        rows = self.city.large_parcels()
        blank = [r for r in rows if r["assessed_land_usd"] is None]
        self.assertTrue(blank, "the recorded data has parcels with no assessed value")
        self.assertTrue(all(r["assessed_land_usd"] != 0 or r["assessed_land_usd"] is not None for r in rows))
        self.assertTrue(all(r["zoning"] == r["zoning"].strip() for r in rows), "stray spaces are tidied")

    def test_one_parcel(self):
        p = self.city.parcel(EXAMPLE)
        self.assertEqual((p["apn"], p["apn_formatted"], p["acres"], p["zoning"]), (EXAMPLE, "372-100-001", 142.1, "EDC-CC"))
        self.assertTrue(p["looks_vacant"])
        self.assertEqual(p["outline"]["type"], "Polygon")
        self.assertEqual(p["size_feet"], {"east_west": 2349, "north_south": 2635})
        self.assertEqual(self.city.parcel("372-100-001")["apn"], EXAMPLE, "dashes are fine")

    def test_unknown_and_malformed_parcel_numbers(self):
        with self.assertRaises(NotFound):
            self.city.parcel("999999999")
        with self.assertRaises(NotFound):
            self.city.parcel("12")
        self.assertTrue(issubclass(NotFound, SourceError))

    def test_site_parts_match_the_recorded_facts(self):
        p = self.city.parcel(EXAMPLE)
        part = {name: self.city.site_part(name, p) for name in SITE_PARTS}
        self.assertEqual(part["zoning"]["what_it_allows"], "EDC-Community Core")
        self.assertEqual(part["general_plan"]["description"], "Economic Development Corridor (EDC)")
        around = part["surroundings"]
        self.assertEqual(around["within_miles"], 1.0)
        self.assertEqual(around["by_zoning"][0]["zoning"], "EDC-CC")
        self.assertAlmostEqual(sum(r["share_pct"] for r in around["by_zoning"]), 100, delta=3)
        self.assertEqual(len(part["neighbour_shapes"]), 80)
        nearest = part["state_highway_traffic"]["stations"][0]
        self.assertEqual((nearest["route"], nearest["where"], nearest["miles_away"]), ("215", "SCOTT ROAD", 0.8))
        self.assertEqual((nearest["vehicles_per_day_behind"], nearest["vehicles_per_day_ahead"]), ("126000", "121000"))
        self.assertEqual(set(part["terrain"]["feet_above_sea_level"]), {"centre", "north", "south", "east", "west"})
        self.assertEqual(part["terrain"]["reading"], "nearly flat")
        self.assertIsNone(self.city.site_part("no-such-part", p))
        # what a land-use plan starts from
        self.assertEqual([r["miles"] for r in part["people"]["rings"]], [1, 3, 5])
        self.assertEqual(part["people"]["rings"][0]["people"], 8799)
        self.assertEqual(part["people"]["year"], 2020)
        streets = part["streets"]
        self.assertAlmostEqual(streets["within_miles"], 0.68, places=6, msg="the parcel's own reach (0.33) plus 0.35")
        self.assertEqual(len(streets["streets"]), 20)
        self.assertTrue(all(s["paths"] and s["rank"] >= 1 for s in streets["streets"]))
        signals = part["signals"]
        self.assertAlmostEqual(signals["within_miles"], 1.33, places=6, msg="the parcel's own reach plus 1 mile")
        self.assertEqual(len(signals["signals"]), 10)
        distances = [s["miles_away"] for s in signals["signals"]]
        self.assertEqual(distances, sorted(distances))
        self.assertTrue(all(d <= 1.4 for d in distances))
        self.assertEqual(part["projects"]["within_miles"], 3.0)
        self.assertEqual(len(part["projects"]["projects"]), 56)
        self.assertEqual(part["projects"]["lists_updated"]["development projects"], "2023-09-14")
        self.assertEqual(part["schools"]["within_miles"], 2.0)
        self.assertEqual(len(part["schools"]["schools"]), 8)
        self.assertEqual(part["schools"]["schools"][0]["name"], "Revival Christian Academy")

    def test_the_reach_of_a_parcel_is_half_its_corner_to_corner_distance_in_miles(self):
        self.assertEqual(Menifee._reach({"size_feet": {"east_west": 5280, "north_south": 0}}), 0.5)
        self.assertEqual(Menifee._reach({"size_feet": {"east_west": 3 * 5280, "north_south": 4 * 5280}}), 2.5)
        self.assertEqual(Menifee._reach({}), 0.0, "a parcel with no size reaches nowhere")
        self.assertEqual(Menifee._reach(self.city.parcel(EXAMPLE)), 0.33)

    def test_the_market_parts_ask_for_the_parcels_own_centre(self):
        p = self.city.parcel(EXAMPLE)
        self.replay.asked.clear()
        for name in ("people", "streets", "signals", "projects", "schools"):
            self.assertTrue(self.city.site_part(name, p))
        self.assertTrue(any("Circulation_Element" in u for u in self.replay.asked))
        self.assertTrue(any("Traffic_Signals" in u for u in self.replay.asked))
        self.assertTrue(any("TIGERweb" in u for u in self.replay.asked))

    def test_the_records_date_and_the_photo_date_come_through_the_adapter(self):
        p = self.city.parcel(EXAMPLE)
        self.assertEqual(self.city.records_updated()["parcels"], "2026-10-28")
        photo = self.city.photo_date(round(p["centre"]["lon"], 2), round(p["centre"]["lat"], 2))
        self.assertEqual((photo["taken"], photo["year"]), ("2022-04-15", 2022))

    def test_the_parcels_in_a_view_come_through_the_adapter(self):
        out = self.city.parcels_in_box(-117.1715, 33.6500, -117.1615, 33.6550)
        self.assertEqual(len(out["parcels"]), 5)
        self.assertFalse(out["more"])

    def test_a_silent_market_service_is_the_apps_error_and_the_others_still_answer(self):
        p = self.city.parcel(EXAMPLE)
        self.replay.down.append("Traffic_Signals")
        with self.assertRaises(SourceError):
            self.city.site_part("signals", p)
        self.assertTrue(self.city.site_part("streets", p))

    def test_the_height_grid_says_what_the_samples_say(self):
        p = self.city.parcel(EXAMPLE)
        grid = self.city.site_part("surface", p)
        self.assertEqual(len(grid["feet"]), grid["nx"] * grid["ny"])
        inside = grid["inside"]
        heights = [h for h in grid["feet"] if h is not None]
        self.assertGreaterEqual(inside["low_ft"], min(heights))
        self.assertLessEqual(inside["high_ft"], max(heights))
        self.assertEqual(inside["range_ft"], round(inside["high_ft"] - inside["low_ft"], 1))
        # the finer samples show about 35 ft of range on this parcel, more than the five spot heights' 20 ft
        self.assertAlmostEqual(inside["range_ft"], 34.7, delta=0.5)
        self.assertGreater(inside["range_ft"], self.city.site_part("terrain", p)["fall_across_site_ft"])
        self.assertLessEqual(inside["typical_slope_pct"], inside["steepest_tenth_pct"])

    def test_a_silent_service_is_an_error_not_a_made_up_value(self):
        p = self.city.parcel(EXAMPLE)
        self.replay.down.append("3DEPElevation")
        self.replay.down.append("epqs")
        for name in ("surface", "terrain"):
            with self.assertRaises(SourceError):
                self.city.site_part(name, p)
        self.assertTrue(self.city.site_part("zoning", p), "the other sources still answer")

    def test_zoning_names_and_families(self):
        names = self.city.zone_names()
        self.assertEqual(names["EDC-CC"], "EDC-Community Core")
        self.assertEqual(names["HDR"], "High Density Residential", "the city's non-breaking spaces are tidied")
        self.assertIn("Specific Plan", names)
        kinds = {k for k, _label, _colour in self.city.zoning_kinds}
        for code, kind in {"EDC-CC": "edc", "LDR-2": "low-density", "LMDR": "denser-housing", "RR5": "rural",
                           "RM & RR5": "mixed", "Specific Plan": "specific-plan", "Menifee East SP": "specific-plan",
                           "PDO-5": "specific-plan", "OS-R": "open-space", "PF": "public", "": "other", None: "other"}.items():
            self.assertEqual(self.city.zoning_kind(code), kind, code)
            self.assertIn(kind, kinds)
        self.assertTrue(all(self.city.zoning_kind(r["zoning"]) in kinds for r in self.city.large_parcels()))

    def test_zone_notes_only_where_wording_was_read(self):
        self.assertEqual(len(self.city.zoning_notes("EDC-CC")), 1)
        self.assertTrue(self.city.zoning_notes("EDC-CC")[0]["source_url"].startswith("https://"))
        self.assertEqual(self.city.zoning_notes("LDR-2"), [])


class ToolMaths(unittest.TestCase):
    def test_grid_covers_the_outline_south_to_north(self):
        grid, points = tool.grid_points(SQUARE)
        self.assertEqual(len(points), grid["nx"] * grid["ny"])
        self.assertLess(points[0][0], -117.17)
        self.assertGreater(points[-1][1], 33.66)

    def test_inside_the_outline(self):
        self.assertTrue(tool.inside(SQUARE, -117.165, 33.655))
        self.assertFalse(tool.inside(SQUARE, -117.18, 33.655))
        hole = SQUARE + [[[-117.168, 33.652], [-117.162, 33.652], [-117.162, 33.658], [-117.168, 33.658], [-117.168, 33.652]]]
        self.assertFalse(tool.inside(hole, -117.165, 33.655), "a hole is outside")

    def test_a_tilted_plane_has_the_slope_it_was_given(self):
        grid, points = tool.grid_points(SQUARE, cells=20, margin=0.1)
        step_y = (grid["north"] - grid["south"]) / (grid["ny"] - 1) * 364000
        grid["feet"] = [100 + 0.03 * step_y * (i // grid["nx"]) for i in range(len(points))]   # 3 % rise to the north
        s = tool.surface_summary(grid, SQUARE)
        self.assertAlmostEqual(s["typical_slope_pct"], 3.0, places=1)
        self.assertEqual(s["reading"], "gentle")
        self.assertGreater(s["high_at"]["lat"], s["low_at"]["lat"])
        self.assertAlmostEqual(s["range_ft"], s["high_ft"] - s["low_ft"], places=1)

    def test_gaps_in_the_heights_are_not_filled_in(self):
        grid, points = tool.grid_points(SQUARE, cells=6)
        grid["feet"] = [None] * len(points)
        self.assertIsNone(tool.surface_summary(grid, SQUARE))

    def test_a_circle_is_the_size_asked_for(self):
        ring = tool.circle(-117.165, 33.655, 1.0)["rings"][0]
        north = max(p[1] for p in ring)
        self.assertAlmostEqual((north - 33.655) * 69.17, 1.0, places=2)


if __name__ == "__main__":
    unittest.main()
