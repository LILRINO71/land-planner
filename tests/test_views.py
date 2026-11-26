"""The map-view side of the app: the smallest-size floor, every parcel in view, the "updated" dates, My lands'
file location and the server routes that carry them. Uses the made-up Tinytown city; no network, no real server."""
import tempfile
import unittest
from pathlib import Path

from support import Clock, SQUARE, Tinytown, row
from landplanner.cities import SourceError
from landplanner.planner import FLOORS, MAX_VIEW_DEGREES, LandPlanner, Problem
from landplanner.server import route


class Town(Tinytown):
    """Tinytown, but listing parcels from a given size up, as the real adapters do (large_parcels(min_acres))."""

    def large_parcels(self, min_acres=None):
        self._maybe_fail("large")
        floor = self.large_acres if min_acres is None else min_acres
        return [dict(r) for r in self.rows + [self.small] if r["acres"] >= floor]


class TownWithAMap(Town):
    """A Tinytown that can search a map view, and knows its records and photo dates."""

    def __init__(self):
        super().__init__()
        self.box_calls, self.records_calls, self.photo_calls = [], 0, []
        self.box_answer = {"parcels": [row("100000001", 50.0, "R-1", True, 900)], "more": True}
        self.records, self.photo, self.fail = {"parcels": "2026-10-28"}, {"taken": "2022-04-15", "year": 2022}, None

    def parcels_in_box(self, west, south, east, north):
        self.box_calls.append((west, south, east, north))
        if self.fail:
            raise self.fail
        return self.box_answer

    def records_updated(self):
        self.records_calls += 1
        if self.fail:
            raise self.fail
        return self.records

    def photo_date(self, lon, lat):
        self.photo_calls.append((lon, lat))
        if self.fail:
            raise self.fail
        return self.photo


class Base(unittest.TestCase):
    city_class = Town

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.city = self.city_class()
        self.app = LandPlanner({"tinytown": self.city}, self.folder.name, clock=Clock())

    def plain_app(self):
        """A planner over a plain Tinytown (no map search, no dates), with its own folder."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return LandPlanner({"tinytown": Town()}, folder.name)

    def problem(self, call, *args, **kw):
        with self.assertRaises(Problem) as caught:
            call(*args, **kw)
        return caught.exception

    def query(self, **values):
        return {k: [str(v)] for k, v in values.items()}


class SmallestSizeFloor(Base):
    def test_no_size_asked_starts_at_the_citys_large_size(self):
        self.assertEqual(self.app.floor_for(self.city, None), 10.0)
        self.assertEqual(self.app.floor_for(self.city), 10.0)

    def test_the_floor_is_the_biggest_floor_that_does_not_cut_off_what_was_asked_for(self):
        self.assertEqual(FLOORS, (1.0, 2.0, 5.0))
        for asked, floor in [(7, 5.0), (5, 5.0), (9.99, 5.0), (4.9, 2.0), (2, 2.0), (3, 2.0), (1.5, 1.0), (1, 1.0)]:
            with self.subTest(asked=asked):
                self.assertEqual(self.app.floor_for(self.city, asked), floor)

    def test_a_size_below_the_smallest_floor_still_starts_at_the_smallest_floor(self):
        self.assertEqual(self.app.floor_for(self.city, 0.2), 1.0)
        self.assertEqual(self.app.floor_for(self.city, 0), 1.0)

    def test_a_size_at_or_above_the_large_size_starts_at_the_large_size(self):
        for asked in (10, 10.5, 50, 1e6):
            with self.subTest(asked=asked):
                self.assertEqual(self.app.floor_for(self.city, asked), 10.0)

    def test_a_city_whose_large_size_is_small_never_goes_below_its_own_size(self):
        small = Town()
        small.large_acres = 2.0
        self.assertEqual(self.app.floor_for(small, 1.5), 1.0)
        self.assertEqual(self.app.floor_for(small, 3), 2.0)
        self.assertEqual(self.app.floor_for(small, None), 2.0)


class ParcelsInView(Base):
    city_class = TownWithAMap

    def test_a_city_that_cannot_search_a_view_gives_an_empty_list(self):
        plain = self.plain_app()
        out = plain.parcels_in_view("tinytown", -117.17, 33.65, -117.16, 33.66)
        self.assertEqual(out, {"city": "tinytown", "parcels": [], "more": False})

    def test_a_view_the_city_answers_comes_back_with_each_parcels_family_and_name(self):
        out = self.app.parcels_in_view("tinytown", -117.17, 33.65, -117.16, 33.66)
        self.assertEqual(self.city.box_calls, [(-117.17, 33.65, -117.16, 33.66)])
        self.assertTrue(out["more"])
        self.assertEqual(len(out["parcels"]), 1)
        parcel = out["parcels"][0]
        self.assertEqual((parcel["zoning_kind"], parcel["zoning_name"]), ("homes", "Single homes"))
        self.assertEqual(parcel["apn"], "100000001")

    def test_a_view_that_is_not_a_map_view_is_a_400_and_never_reaches_the_city(self):
        bad = [(None, 33.65, -117.16, 33.66), (-117.17, None, -117.16, 33.66),
               (-117.16, 33.65, -117.17, 33.66),          # west of east the wrong way round
               (-117.17, 33.66, -117.16, 33.65),          # south and north the wrong way round
               (-117.17, 33.65, -117.17, 33.66),          # no width
               (-200.0, 33.65, -199.99, 33.66), (-117.17, -91.0, -117.16, -90.5), (-117.17, 33.65, 181.0, 33.66)]
        for box in bad:
            with self.subTest(box=box):
                e = self.problem(self.app.parcels_in_view, "tinytown", *box)
                self.assertEqual((e.status, e.code), (400, "bad-request"))
        self.assertEqual(self.city.box_calls, [])

    def test_a_view_that_is_too_wide_asks_the_person_to_zoom_in(self):
        wide = MAX_VIEW_DEGREES + 0.01
        for box in [(-117.3, 33.6, -117.3 + wide, 33.65), (-117.3, 33.6, -117.25, 33.6 + wide)]:
            with self.subTest(box=box):
                e = self.problem(self.app.parcels_in_view, "tinytown", *box)
                self.assertEqual((e.status, e.code), (400, "zoom-in"))
        self.assertEqual(self.city.box_calls, [])

    def test_the_widest_allowed_view_is_answered(self):
        just_inside = MAX_VIEW_DEGREES - 0.001
        self.app.parcels_in_view("tinytown", -117.3, 33.6, -117.3 + just_inside, 33.6 + just_inside)
        self.assertEqual(len(self.city.box_calls), 1)

    def test_a_city_that_does_not_answer_is_a_502_in_plain_words(self):
        self.city.fail = SourceError("(test) down")
        e = self.problem(self.app.parcels_in_view, "tinytown", -117.17, 33.65, -117.16, 33.66)
        self.assertEqual((e.status, e.code), (502, "source-down"))
        self.assertIn("Tinytown", e.message)

    def test_an_answer_in_a_shape_nobody_expected_is_treated_like_no_answer(self):
        self.city.fail = KeyError("parcels")
        e = self.problem(self.app.parcels_in_view, "tinytown", -117.17, 33.65, -117.16, 33.66)
        self.assertEqual((e.status, e.code), (502, "source-down"))

    def test_an_unknown_city_is_a_404(self):
        e = self.problem(self.app.parcels_in_view, "nowhere", -117.17, 33.65, -117.16, 33.66)
        self.assertEqual((e.status, e.code), (404, "no-such-city"))


class Updated(Base):
    city_class = TownWithAMap

    def test_a_city_that_does_not_say_has_neither_date(self):
        plain = self.plain_app()
        self.assertEqual(plain.updated("tinytown"), {"city": "tinytown", "records": None, "photo": None})

    def test_both_dates_come_from_the_city(self):
        out = self.app.updated("tinytown", 33.6512, -117.1634)
        self.assertEqual(out, {"city": "tinytown", "records": {"parcels": "2026-10-28"},
                               "photo": {"taken": "2022-04-15", "year": 2022}})

    def test_the_photo_is_asked_for_a_spot_rounded_to_two_decimals(self):
        self.app.updated("tinytown", 33.6512, -117.1634)
        self.assertEqual(self.city.photo_calls, [(-117.16, 33.65)])

    def test_with_no_spot_given_the_city_centre_is_used(self):
        self.app.updated("tinytown")
        self.assertEqual(self.city.photo_calls, [(round(self.city.centre["lon"], 2), round(self.city.centre["lat"], 2))])

    def test_the_same_spot_and_the_records_are_not_asked_for_twice(self):
        self.app.updated("tinytown", 33.6512, -117.1634)
        self.app.updated("tinytown", 33.6499, -117.1601)          # the same half mile
        self.assertEqual((self.city.records_calls, len(self.city.photo_calls)), (1, 1))
        self.app.updated("tinytown", 33.70, -117.1634)            # another spot
        self.assertEqual((self.city.records_calls, len(self.city.photo_calls)), (1, 2))

    def test_a_spot_that_is_not_on_earth_gets_no_photo_date_and_no_question(self):
        out = self.app.updated("tinytown", 133.0, -117.16)
        self.assertIsNone(out["photo"])
        self.assertEqual(out["records"], {"parcels": "2026-10-28"})
        self.assertEqual(self.city.photo_calls, [])

    def test_a_source_that_does_not_answer_is_none_not_an_error(self):
        self.city.fail = SourceError("(test) down")
        self.assertEqual(self.app.updated("tinytown", 33.65, -117.16), {"city": "tinytown", "records": None, "photo": None})

    def test_an_unknown_city_is_a_404(self):
        self.assertEqual(self.problem(self.app.updated, "nowhere").status, 404)


class MyLands(Base):
    def test_my_lands_says_where_the_file_is_kept(self):
        out = self.app.my_lands()
        self.assertEqual(out["lands"], [])
        self.assertIn("kept_in", out)
        self.assertEqual(Path(out["kept_in"]), (Path(self.folder.name) / "my-lands.json").resolve())

    def test_it_still_says_so_after_a_land_is_saved(self):
        out = self.app.save("tinytown", "100000001")
        self.assertEqual([(r["city"], r["apn"]) for r in out["lands"]], [("tinytown", "100000001")])
        self.assertEqual(out["lands"][0]["city_name"], "Tinytown")
        self.assertTrue(Path(out["kept_in"]).exists(), "the file it names is really there")
        self.assertEqual(self.app.remove("tinytown", "100000001")["lands"], [])
        self.assertIn("kept_in", self.app.my_lands())


class Routes(Base):
    city_class = TownWithAMap

    def get(self, path, **query):
        return route(self.app, "GET", path, self.query(**query))

    def test_parcels_in_view_through_the_route(self):
        status, body = self.get("/api/cities/tinytown/parcels", west=-117.17, south=33.65, east=-117.16, north=33.66)
        self.assertEqual(status, 200)
        self.assertEqual((body["city"], len(body["parcels"]), body["more"]), ("tinytown", 1, True))
        self.assertEqual(self.city.box_calls, [(-117.17, 33.65, -117.16, 33.66)])

    def test_parcels_without_a_view_or_with_words_for_numbers_is_a_400(self):
        for query in ({}, {"west": "a", "south": 33.65, "east": -117.16, "north": 33.66},
                      {"west": -117.17, "south": 33.65, "east": -117.16}, {"west": 999, "south": 33.65, "east": 1000, "north": 33.66}):
            with self.subTest(query=query):
                e = self.problem(self.get, "/api/cities/tinytown/parcels", **query)
                self.assertEqual((e.status, e.code), (400, "bad-request"))

    def test_a_too_wide_view_through_the_route_says_zoom_in(self):
        e = self.problem(self.get, "/api/cities/tinytown/parcels", west=-118, south=33, east=-117, north=34)
        self.assertEqual((e.status, e.code), (400, "zoom-in"))

    def test_updated_through_the_route_with_and_without_a_spot(self):
        status, body = self.get("/api/cities/tinytown/updated", lat=33.65, lon=-117.16)
        self.assertEqual((status, body["records"], body["photo"]["taken"]), (200, {"parcels": "2026-10-28"}, "2022-04-15"))
        self.assertEqual(self.city.photo_calls[-1], (-117.16, 33.65))
        status, body = self.get("/api/cities/tinytown/updated")
        self.assertEqual(status, 200)
        self.assertEqual(body["city"], "tinytown")

    def test_a_spot_with_words_in_it_falls_back_to_the_city_centre(self):
        status, _ = self.get("/api/cities/tinytown/updated", lat="north", lon="east")
        self.assertEqual(status, 200)
        self.assertEqual(self.city.photo_calls[-1], (round(self.city.centre["lon"], 2), round(self.city.centre["lat"], 2)))

    def test_shapes_follow_the_smallest_size_asked(self):
        status, body = self.get("/api/cities/tinytown/shapes")
        self.assertEqual((status, body["floor"]), (200, 10.0))
        self.assertEqual(sorted(body["shapes"]), ["100000001", "100000002", "100000003", "100000004"])
        status, body = self.get("/api/cities/tinytown/shapes", min_acres=1.5)
        self.assertEqual((status, body["floor"]), (200, 1.0))
        self.assertIn("100000009", body["shapes"], "the 2.5 acre parcel shows once smaller land is asked for")
        self.assertTrue(all(rings for rings in body["shapes"].values()))
        status, body = self.get("/api/cities/tinytown/shapes", min_acres=7)
        self.assertEqual(body["floor"], 5.0)
        self.assertNotIn("100000009", body["shapes"], "7 acres and up does not include a 2.5 acre parcel in the list")

    def test_shapes_with_a_size_that_is_not_a_number_is_a_400(self):
        for bad in ("big", "-3", "nan", "1e9"):
            with self.subTest(bad=bad):
                e = self.problem(self.get, "/api/cities/tinytown/shapes", min_acres=bad)
                self.assertEqual((e.status, e.code), (400, "bad-request"))

    def test_the_routes_of_an_unknown_city_are_a_404(self):
        for path in ("parcels", "updated", "shapes"):
            with self.subTest(path=path):
                e = self.problem(self.get, f"/api/cities/nowhere/{path}", west=-117.17, south=33.65, east=-117.16, north=33.66)
                self.assertEqual((e.status, e.code), (404, "no-such-city"))

    def test_my_lands_through_the_route_says_where_it_is_kept(self):
        status, body = self.get("/api/my-lands")
        self.assertEqual(status, 200)
        self.assertIn("kept_in", body)


if __name__ == "__main__":
    unittest.main()
