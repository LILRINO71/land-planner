"""The flat-ground geometry (landplanner/geometry.py): pure maths, no fixtures, no network."""
import math
import unittest

from support import ROOT  # noqa: F401 - puts the project on the import path
from landplanner import geometry as G

SQUARE = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]              # 10,000 sq ft
RECT = [(10.0, 20.0), (50.0, 20.0), (50.0, 50.0), (10.0, 50.0)]                # 40 x 30 = 1,200
TRIANGLE = [(0.0, 0.0), (100.0, 0.0), (0.0, 100.0)]                            # 5,000
L_SHAPE = [(0.0, 0.0), (100.0, 0.0), (100.0, 40.0), (40.0, 40.0), (40.0, 100.0), (0.0, 100.0)]   # 4,000 + 2,400 = 6,400
DIRECTIONS = [(0.0, 1.0), (1.0, 0.0), (0.6, 0.8), (-0.8, 0.6), (1.0, -1.0)]


def close(test, a, b, rel):
    test.assertAlmostEqual(a / b, 1.0, delta=rel, msg=f"{a} is not within {rel:.2%} of {b}")


class Frames(unittest.TestCase):
    def test_a_point_goes_to_feet_and_back_to_the_same_longitude_and_latitude(self):
        frame = G.Frame(-117.166542, 33.652383)
        for lon, lat in [(-117.166542, 33.652383), (-117.17, 33.65), (-117.16, 33.66), (-117.1631, 33.6711)]:
            x, y = frame.xy(lon, lat)
            back = frame.ll(x, y)
            self.assertAlmostEqual(back[0], lon, places=6)
            self.assertAlmostEqual(back[1], lat, places=6)

    def test_the_centre_of_the_frame_is_the_origin(self):
        self.assertEqual(G.Frame(-117.1, 33.6).xy(-117.1, 33.6), (0.0, 0.0))

    def test_a_hundredth_of_a_degree_square_near_latitude_33_65_has_the_expected_size_in_feet(self):
        frame = G.Frame(-117.165, 33.655)
        x0, y0 = frame.xy(-117.17, 33.65)
        x1, y1 = frame.xy(-117.16, 33.66)
        self.assertAlmostEqual(y1 - y0, 3640.0, delta=0.01)                       # 364,000 ft per degree of latitude
        expected_east_west = 3640.0 * math.cos(math.radians(33.655))             # a degree of longitude is shorter here
        self.assertAlmostEqual(x1 - x0, expected_east_west, delta=0.01)
        self.assertAlmostEqual(x1 - x0, 3030.0, delta=15)                        # about 3,030 ft, narrower than it is tall
        self.assertLess(x1 - x0, y1 - y0)

    def test_north_is_up_and_east_is_right(self):
        frame = G.Frame(-117.0, 33.0)
        x, y = frame.xy(-116.999, 33.001)
        self.assertGreater(x, 0)
        self.assertGreater(y, 0)

    def test_a_ring_loses_its_closing_point_and_comes_back_closed(self):
        frame = G.Frame(-117.165, 33.655)
        ring = [[-117.17, 33.65], [-117.16, 33.65], [-117.16, 33.66], [-117.17, 33.66], [-117.17, 33.65]]
        poly = frame.ring(ring)
        self.assertEqual(len(poly), 4)
        closed = frame.ring_ll(poly)
        self.assertEqual(len(closed), 5)
        self.assertEqual(closed[0], closed[-1])
        for got, want in zip(closed, ring):
            self.assertAlmostEqual(got[0], want[0], places=6)
            self.assertAlmostEqual(got[1], want[1], places=6)

    def test_a_ring_that_is_not_closed_keeps_all_its_points(self):
        frame = G.Frame(-117.165, 33.655)
        self.assertEqual(len(frame.ring([[-117.17, 33.65], [-117.16, 33.65], [-117.16, 33.66]])), 3)


class AreaAndCentroid(unittest.TestCase):
    def test_area_of_a_rectangle(self):
        self.assertAlmostEqual(G.area(RECT), 1200.0)
        self.assertAlmostEqual(G.area(list(reversed(RECT))), 1200.0, msg="the winding direction does not matter")

    def test_area_of_an_l_shape(self):
        self.assertAlmostEqual(G.area(L_SHAPE), 6400.0)

    def test_area_of_a_triangle(self):
        self.assertAlmostEqual(G.area(TRIANGLE), 5000.0)

    def test_less_than_three_points_has_no_area(self):
        self.assertEqual(G.area([]), 0.0)
        self.assertEqual(G.area([(0, 0), (5, 5)]), 0.0)

    def test_centroid_of_a_rectangle_is_its_middle(self):
        cx, cy = G.centroid(RECT)
        self.assertAlmostEqual(cx, 30.0)
        self.assertAlmostEqual(cy, 35.0)

    def test_centroid_of_the_other_winding_is_the_same(self):
        cx, cy = G.centroid(list(reversed(RECT)))
        self.assertAlmostEqual(cx, 30.0)
        self.assertAlmostEqual(cy, 35.0)

    def test_centroid_of_an_l_shape_is_pulled_toward_its_two_arms(self):
        # arm along the bottom: 100 x 40 centred (50, 20); arm up the left: 40 x 60 centred (20, 70)
        want_x = (4000 * 50 + 2400 * 20) / 6400
        want_y = (4000 * 20 + 2400 * 70) / 6400
        cx, cy = G.centroid(L_SHAPE)
        self.assertAlmostEqual(cx, want_x)
        self.assertAlmostEqual(cy, want_y)

    def test_centroid_of_a_triangle(self):
        cx, cy = G.centroid(TRIANGLE)
        self.assertAlmostEqual(cx, 100 / 3)
        self.assertAlmostEqual(cy, 100 / 3)

    def test_a_flat_shape_falls_back_to_the_average_of_its_points(self):
        self.assertEqual(G.centroid([(0, 0), (10, 0), (20, 0)]), (10.0, 0.0))


class Inside(unittest.TestCase):
    def test_points_inside_and_outside_a_square(self):
        self.assertTrue(G.inside(SQUARE, (50, 50)))
        self.assertTrue(G.inside(SQUARE, (1, 99)))
        self.assertFalse(G.inside(SQUARE, (150, 50)))
        self.assertFalse(G.inside(SQUARE, (-1, 50)))
        self.assertFalse(G.inside(SQUARE, (50, 101)))

    def test_the_notch_of_an_l_shape_is_outside(self):
        self.assertTrue(G.inside(L_SHAPE, (70, 20)))
        self.assertTrue(G.inside(L_SHAPE, (20, 80)))
        self.assertFalse(G.inside(L_SHAPE, (70, 70)), "the empty corner of the L")

    def test_a_triangle(self):
        self.assertTrue(G.inside(TRIANGLE, (20, 20)))
        self.assertFalse(G.inside(TRIANGLE, (60, 60)))


class Clipping(unittest.TestCase):
    def test_clip_halves_a_square(self):
        top = G.clip(SQUARE, (0.0, 1.0), 50.0)
        bottom = G.clip(SQUARE, (0.0, -1.0), -50.0)
        self.assertAlmostEqual(G.area(top), 5000.0)
        self.assertAlmostEqual(G.area(bottom), 5000.0)
        self.assertTrue(all(p[1] >= 50 - 1e-9 for p in top))
        self.assertTrue(all(p[1] <= 50 + 1e-9 for p in bottom))

    def test_clip_through_a_diagonal_gives_a_triangle(self):
        half = G.clip(SQUARE, G.unit((1.0, 1.0)), 100.0 / math.sqrt(2))
        self.assertAlmostEqual(G.area(half), 5000.0)
        self.assertTrue(all(G.dot(p, G.unit((1.0, 1.0))) >= 100.0 / math.sqrt(2) - 1e-9 for p in half))

    def test_clip_beyond_the_shape_gives_nothing_or_everything(self):
        self.assertEqual(G.clip(SQUARE, (0.0, 1.0), 500.0), [])
        self.assertAlmostEqual(G.area(G.clip(SQUARE, (0.0, 1.0), -500.0)), 10000.0)

    def test_extent_is_how_far_the_shape_reaches_along_a_direction(self):
        self.assertEqual(G.extent(SQUARE, (1.0, 0.0)), (0.0, 100.0))
        low, high = G.extent(SQUARE, G.unit((1.0, 1.0)))
        self.assertAlmostEqual(low, 0.0)
        self.assertAlmostEqual(high, 200 / math.sqrt(2))


class Splitting(unittest.TestCase):
    def check_split(self, poly, want_front):
        total = G.area(poly)
        for direction in DIRECTIONS:
            n = G.unit(direction)
            front, back, c = G.split(poly, n, want_front)
            with self.subTest(direction=direction, front=want_front):
                close(self, G.area(front), want_front, 0.001)
                close(self, G.area(front) + G.area(back), total, 1e-9)
                self.assertTrue(all(G.dot(p, n) >= c - 1e-6 for p in front), "the front piece is on the + side")
                self.assertTrue(all(G.dot(p, n) <= c + 1e-6 for p in back), "the back piece is on the - side")

    def test_split_a_square_gives_the_asked_front_area_in_several_directions(self):
        for want in (1000.0, 2500.0, 5000.0, 9000.0):
            self.check_split(SQUARE, want)

    def test_split_a_triangle_gives_the_asked_front_area_in_several_directions(self):
        for want in (500.0, 2500.0, 4500.0):
            self.check_split(TRIANGLE, want)

    def test_split_a_concave_l_shape_gives_the_asked_front_area_in_several_directions(self):
        for want in (640.0, 3200.0, 5800.0):
            self.check_split(L_SHAPE, want)

    def test_asking_for_more_than_there_is_gives_all_of_it_in_front(self):
        front, back, _ = G.split(SQUARE, (0.0, 1.0), 99999.0)
        self.assertAlmostEqual(G.area(front), 10000.0, delta=1.0)
        self.assertAlmostEqual(G.area(back), 0.0, delta=1.0)

    def test_asking_for_nothing_gives_an_empty_front(self):
        front, back, _ = G.split(SQUARE, (0.0, 1.0), -5.0)
        self.assertAlmostEqual(G.area(front), 0.0, delta=1.0)
        self.assertAlmostEqual(G.area(back), 10000.0, delta=1.0)

    def test_the_cut_line_of_a_square_halved_sits_in_the_middle(self):
        _, _, c = G.split(SQUARE, (0.0, 1.0), 5000.0)
        self.assertAlmostEqual(c, 50.0, places=6)


class Chords(unittest.TestCase):
    def on_outline(self, poly, p):
        return G.near_on_edge(poly, p)[0]

    def test_chord_of_a_square_runs_from_side_to_side(self):
        a, b = G.chord(SQUARE, (0.0, 1.0), 30.0)
        self.assertEqual({a, b}, {(0.0, 30.0), (100.0, 30.0)})

    def test_chord_end_points_are_on_the_outline_for_a_diagonal_cut(self):
        n = G.unit((0.6, 0.8))
        for c in (20.0, 70.0, 100.0):
            a, b = G.chord(SQUARE, n, c)
            self.assertAlmostEqual(self.on_outline(SQUARE, a), 0.0, places=6)
            self.assertAlmostEqual(self.on_outline(SQUARE, b), 0.0, places=6)
            self.assertAlmostEqual(G.dot(a, n), c, places=6)
            self.assertAlmostEqual(G.dot(b, n), c, places=6)

    def test_chord_of_a_concave_shape_gives_the_two_outermost_points(self):
        a, b = G.chord(L_SHAPE, (0.0, 1.0), 70.0)       # only the tall arm is there at this height
        self.assertEqual({a, b}, {(0.0, 70.0), (40.0, 70.0)})
        a, b = G.chord(L_SHAPE, (0.0, 1.0), 20.0)       # the wide arm
        self.assertEqual({a, b}, {(0.0, 20.0), (100.0, 20.0)})

    def test_a_line_that_misses_the_shape_has_no_chord(self):
        self.assertIsNone(G.chord(SQUARE, (0.0, 1.0), 250.0))


class Distances(unittest.TestCase):
    def test_distance_to_a_segment_from_beside_it(self):
        d, q = G.near_on_segment((0, 0), (10, 0), (5, 3))
        self.assertAlmostEqual(d, 3.0)
        self.assertEqual(q, (5.0, 0.0))

    def test_distance_to_a_segment_from_past_its_end_is_to_the_end(self):
        d, q = G.near_on_segment((0, 0), (10, 0), (-4, 3))
        self.assertAlmostEqual(d, 5.0)
        self.assertEqual(q, (0.0, 0.0))
        d, q = G.near_on_segment((0, 0), (10, 0), (13, -4))
        self.assertAlmostEqual(d, 5.0)
        self.assertEqual(q, (10.0, 0.0))

    def test_distance_to_a_segment_that_is_a_single_point(self):
        d, q = G.near_on_segment((2, 2), (2, 2), (5, 6))
        self.assertAlmostEqual(d, 5.0)
        self.assertEqual(q, (2.0, 2.0))

    def test_a_point_on_a_segment_is_zero_away(self):
        self.assertAlmostEqual(G.near_on_segment((0, 0), (10, 10), (4, 4))[0], 0.0)

    def test_distance_to_a_path_picks_the_nearest_stretch(self):
        path = [(0, 0), (10, 0), (10, 10)]
        d, q = G.near_on_path(path, (12, 6))
        self.assertAlmostEqual(d, 2.0)
        self.assertEqual(q, (10.0, 6.0))
        d, q = G.near_on_path(path, (6, -3))
        self.assertAlmostEqual(d, 3.0)
        self.assertEqual(q, (6.0, 0.0))

    def test_distance_to_the_edge_of_a_polygon_includes_the_closing_side(self):
        d, q = G.near_on_edge(SQUARE, (-5, 50))      # the left side is the closing side (0,100) -> (0,0)
        self.assertAlmostEqual(d, 5.0)
        self.assertEqual(q, (0.0, 50.0))

    def test_a_point_inside_is_measured_to_the_nearest_side(self):
        d, _ = G.near_on_edge(SQUARE, (90, 50))
        self.assertAlmostEqual(d, 10.0)

    def test_a_street_beside_a_parcel(self):
        d, on_edge, on_path = G.path_to_poly([(130, -20), (130, 120)], SQUARE)
        self.assertAlmostEqual(d, 30.0)
        self.assertAlmostEqual(on_edge[0], 100.0)
        self.assertAlmostEqual(on_path[0], 130.0)

    def test_a_street_ending_near_a_corner_is_measured_to_the_corner(self):
        d, on_edge, on_path = G.path_to_poly([(110, 110), (150, 150)], SQUARE)
        self.assertAlmostEqual(d, math.hypot(10, 10))
        self.assertEqual(on_edge, (100, 100))
        self.assertEqual(on_path, (110.0, 110.0))

    def test_a_street_whose_middle_is_nearest_a_corner(self):
        # the path runs past the corner (100, 100) with its end points far away on either side
        d, on_edge, on_path = G.path_to_poly([(80, 140), (140, 80)], SQUARE)
        self.assertAlmostEqual(d, 10 * math.sqrt(2))
        self.assertEqual(on_edge, (100, 100))
        self.assertAlmostEqual(on_path[0], 110.0)
        self.assertAlmostEqual(on_path[1], 110.0)

    def test_a_street_crossing_the_parcel_is_zero_away(self):
        d, _, _ = G.path_to_poly([(-50, 50), (150, 50)], SQUARE)
        self.assertAlmostEqual(d, 0.0)


class Layouts(unittest.TestCase):
    FRONT = (0.0, 1.0)

    def lay(self, poly, areas, pulls=None, front=None):
        pulls = pulls or [(0.0, 0.0)] * len(areas)
        items = [{"id": f"item{i}", "area": a, "pull": p} for i, (a, p) in enumerate(zip(areas, pulls))]
        pieces, cuts = G.layout(poly, items, front or self.FRONT)
        return items, pieces, cuts

    def by_id(self, pieces):
        return {p["id"]: p for p in pieces}

    def check_fills_polygon(self, poly, areas, pulls=None):
        items, pieces, cuts = self.lay(poly, areas, pulls)
        total = G.area(poly)
        want = [a * total / sum(areas) for a in areas]
        got = self.by_id(pieces)
        self.assertEqual(sorted(got), sorted(i["id"] for i in items), "every item gets exactly one piece")
        self.assertEqual(len(pieces), len(items))
        for item, w in zip(items, want):
            close(self, G.area(got[item["id"]]["poly"]), w, 0.005)
        close(self, sum(G.area(p["poly"]) for p in pieces), total, 1e-6)
        return pieces, cuts

    def test_pieces_match_the_asked_areas_on_a_square(self):
        self.check_fills_polygon(SQUARE, [1000.0, 2000.0, 3000.0, 4000.0], [(0, 1), (0, 0.3), (0, -0.3), (0, -1)])

    def test_pieces_match_the_asked_areas_on_a_triangle(self):
        self.check_fills_polygon(TRIANGLE, [500.0, 1500.0, 3000.0], [(1, 0), (0, 1), (-1, -1)])

    def test_pieces_match_the_asked_areas_on_a_concave_l_shape(self):
        self.check_fills_polygon(L_SHAPE, [1600.0, 1600.0, 3200.0], [(0, 1), (1, 0), (-1, -1)])

    def test_areas_that_do_not_add_up_to_the_polygon_are_scaled_to_fill_it(self):
        items, pieces, _ = self.lay(SQUARE, [1.0, 1.0, 2.0], [(0, 1), (0, 0), (0, -1)])
        got = {p["id"]: G.area(p["poly"]) for p in pieces}
        close(self, got["item0"], 2500.0, 0.005)
        close(self, got["item1"], 2500.0, 0.005)
        close(self, got["item2"], 5000.0, 0.005)
        close(self, sum(got.values()), 10000.0, 1e-6)
        self.assertEqual([i["area"] for i in items], [1.0, 1.0, 2.0], "the caller's own list is left alone")

    def test_areas_that_add_up_to_more_than_the_polygon_are_scaled_down(self):
        _, pieces, _ = self.lay(L_SHAPE, [10000.0, 30000.0], [(0, 1), (0, -1)])
        got = {p["id"]: G.area(p["poly"]) for p in pieces}
        close(self, got["item0"], 1600.0, 0.005)
        close(self, got["item1"], 4800.0, 0.005)

    def test_the_pieces_together_are_the_polygon_with_nothing_outside_it(self):
        pieces, _ = self.check_fills_polygon(SQUARE, [3000.0, 3000.0, 2000.0, 2000.0], [(0, 1), (1, 0), (0, -1), (-1, 0)])
        for piece in pieces:
            self.assertTrue(G.inside(SQUARE, G.centroid(piece["poly"])))
            for x, y in piece["poly"]:
                self.assertTrue(-1e-6 <= x <= 100 + 1e-6 and -1e-6 <= y <= 100 + 1e-6)

    def test_every_cut_runs_between_the_outline_or_another_cut_and_there_is_one_less_than_pieces(self):
        pieces, cuts = self.check_fills_polygon(SQUARE, [2500.0] * 4, [(0, 1), (1, 1), (0, -1), (-1, -1)])
        self.assertEqual(len(cuts), len(pieces) - 1)
        for i, cut in enumerate(cuts):
            others = [c for j, c in enumerate(cuts) if j != i]
            for end in cut:
                nearest = [G.near_on_edge(SQUARE, end)[0]] + [G.near_on_segment(a, b, end)[0] for a, b in others]
                self.assertAlmostEqual(min(nearest), 0.0, places=5, msg=f"cut end {end}")

    def test_the_first_cut_ends_on_the_outline_itself(self):
        _, cuts = self.check_fills_polygon(SQUARE, [5000.0, 5000.0], [(0, 1), (0, -1)])
        self.assertEqual(len(cuts), 1)
        for end in cuts[0]:
            self.assertAlmostEqual(G.near_on_edge(SQUARE, end)[0], 0.0, places=6)
        self.assertAlmostEqual(cuts[0][0][1], 50.0)

    def test_an_item_pulled_along_the_front_ends_up_further_along_it_than_one_pulled_the_other_way(self):
        for front in ((0.0, 1.0), (1.0, 0.0), (0.6, 0.8), (-1.0, 0.0)):
            f = G.unit(front)
            items, pieces, _ = self.lay(SQUARE, [4000.0, 6000.0], [f, (-f[0], -f[1])], front)
            got = self.by_id(pieces)
            toward = G.dot(G.centroid(got["item0"]["poly"]), f)
            away = G.dot(G.centroid(got["item1"]["poly"]), f)
            with self.subTest(front=front):
                self.assertGreater(toward, away)

    def test_the_pull_order_holds_for_three_items_on_a_concave_shape(self):
        _, pieces, _ = self.lay(L_SHAPE, [1000.0, 2400.0, 3000.0], [(0, -1), (0, 0), (0, 1)])
        got = self.by_id(pieces)
        ys = [G.centroid(got[f"item{i}"]["poly"])[1] for i in range(3)]
        self.assertLess(ys[0], ys[1])
        self.assertLess(ys[1], ys[2])

    def test_an_item_pulled_to_the_side_ends_up_on_that_side(self):
        # front is north; the side direction is west, so a pull to the east is a pull to the far side
        _, pieces, _ = self.lay(SQUARE, [5000.0, 5000.0], [(1, 0), (-1, 0)])
        got = self.by_id(pieces)
        self.assertGreater(G.centroid(got["item0"]["poly"])[0], G.centroid(got["item1"]["poly"])[0])

    def test_a_single_item_gets_the_whole_polygon_and_no_cuts(self):
        _, pieces, cuts = self.lay(L_SHAPE, [123.0], [(0, 1)])
        self.assertEqual(cuts, [])
        self.assertEqual(len(pieces), 1)
        self.assertEqual(pieces[0]["id"], "item0")
        self.assertEqual(pieces[0]["poly"], list(L_SHAPE))
        self.assertAlmostEqual(G.area(pieces[0]["poly"]), 6400.0)

    def test_an_item_with_no_area_is_left_out(self):
        _, pieces, _ = self.lay(SQUARE, [0.0, 5000.0, 5000.0], [(0, 1), (0, 1), (0, -1)])
        self.assertEqual(sorted(p["id"] for p in pieces), ["item1", "item2"])
        close(self, sum(G.area(p["poly"]) for p in pieces), 10000.0, 1e-6)

    def test_nothing_to_place_or_nowhere_to_place_it_gives_nothing(self):
        self.assertEqual(G.layout(SQUARE, [], (0, 1)), ([], []))
        self.assertEqual(G.layout([], [{"id": "a", "area": 5.0, "pull": (0, 1)}], (0, 1)), ([], []))

    def test_the_same_question_gives_the_same_answer(self):
        items = [{"id": "a", "area": 3000.0, "pull": (0, 1)}, {"id": "b", "area": 7000.0, "pull": (0, -1)}]
        self.assertEqual(G.layout(SQUARE, items, (0, 1)), G.layout(SQUARE, items, (0, 1)))


if __name__ == "__main__":
    unittest.main()
