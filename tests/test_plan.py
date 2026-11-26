"""The land-use plan engine (landplanner/plan.py), on hand-built parcels and site facts. No fixtures, no network.

A parcel is a rectangle of a chosen number of acres around lon -117.17, lat 33.65. The site facts ("parts") are small
dictionaries in the shapes cities/base.py documents. Wording is not tested, only behaviour and arithmetic; a few
tests look for one key word in a sentence where the sentence is the only place a fact is stated.
"""
import math
import unittest

import support  # noqa: F401  (puts the project folder on the import path)
from landplanner import geometry as G
from landplanner import plan as P

LON, LAT = -117.17, 33.65
FRAME = G.Frame(LON, LAT)
ACRE = G.SQ_FT_PER_ACRE

CODES = {"EDC-CC": "edc", "EDC-NG": "edc", "LDR-2": "low-density", "RR2": "rural", "BP": "business", "CR": "commercial",
         "HDR": "denser-housing", "SP-1": "specific-plan", "OS-R": "open-space", "PF": "public",
         "RR1": "rural", "RR1/2": "rural", "RR5": "rural", "RM": "rural"}
ZONINGS = {"edc": "EDC-CC", "low-density": "LDR-2", "rural": "RR2", "business": "BP", "commercial": "CR",
           "denser-housing": "HDR", "specific-plan": "SP-1", "mixed": "LDR-2 & CR", "open-space": "OS-R", "public": "PF",
           "other": ""}
ALL_PARTS = ("zoning", "general_plan", "surroundings", "state_highway_traffic", "people", "streets", "signals",
             "projects", "schools", "surface", "terrain")


def kind_of(code):
    code = str(code or "").strip()
    return "mixed" if "&" in code else CODES.get(code, "other")


# ---------------------------------------------------------------- hand-built parcels and facts

def dims(acres, ratio=1.0):
    """Width and height in feet of a rectangle of this many acres (ratio = width / height)."""
    area = acres * ACRE
    width = math.sqrt(area * ratio)
    return width, area / width


def make_parcel(acres, zoning="EDC-CC", ratio=1.0, **extra):
    w, h = dims(acres, ratio)
    ring = [FRAME.ll(x, y) for x, y in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]
    parcel = {"acres": acres, "zoning": zoning, "zoning_kind": kind_of(zoning), "zoning_name": "", "fire_hazard_zone": "none listed",
              "centre": {"lon": LON, "lat": LAT}, "outline": {"type": "Polygon", "coordinates": [ring + ring[:1]]},
              "assessed_land_usd": None}
    parcel.update(extra)
    return parcel


def highway(miles, per_day, route="215"):
    lon, lat = FRAME.ll(miles * 5280, 0)
    return {"stations": [{"route": route, "where": "SCOTT ROAD", "vehicles_per_day_behind": str(per_day),
                          "vehicles_per_day_ahead": str(per_day), "miles_away": miles, "lat": lat, "lon": lon}]}


def census(p1=None, p3=None, p5=None, homes_share=0.4):
    rings = [{"miles": m, "people": p, "homes": round(p * homes_share)} for m, p in ((1, p1), (3, p3), (5, p5)) if p is not None]
    return {"rings": rings, "year": 2020}


def street(acres, name="Main St", cls="Major", rank=3, off=20.0, ratio=1.0, side="south"):
    """One classed street bowed slightly toward the parcel's south (or north) edge: its nearest point is `off` feet
    from the middle of that edge. A large `off` puts it well away from the parcel."""
    w, h = dims(acres, ratio)
    sign = -1 if side == "south" else 1
    pts = [(-w, sign * (h / 2 + 4 * off)), (0, sign * (h / 2 + off)), (w, sign * (h / 2 + 4 * off))]
    return {"streets": [{"name": name, "class": cls, "rank": rank, "speed_mph": 45, "paths": [[FRAME.ll(x, y) for x, y in pts]]}]}


def around(*rows, miles=1.0):
    return {"within_miles": miles, "by_zoning": [{"zoning": z, "zoning_kind": k, "acres": a} for z, k, a in rows]}


def housing_around():
    """Mostly houses around the parcel, so a best-use mix has both shops and houses."""
    return around(("LDR-2", "low-density", 400.0), ("CR", "commercial", 20.0))


def project(title, kind, acres=None, homes=None, feet=None, miles=1.0, builder=None, description="", number="PP-1"):
    stated = {k: v for k, v in (("acres", acres), ("homes", homes), ("building_sq_ft", feet)) if v is not None}
    return {"title": title, "kind": kind, "status": "Pending", "description": description, "builder": builder, "stated": stated,
            "lat": LAT, "lon": LON, "miles_away": miles, "number": number, "list": "development projects"}


def projects(*rows):
    return {"within_miles": 3.0, "projects": list(rows), "lists_updated": {"development projects": "2026-01-01"}}


def surface(slope, steep=None, reading="nearly flat", low=None):
    return {"inside": {"typical_slope_pct": slope, "steepest_tenth_pct": steep, "reading": reading, "range_ft": 10.0, "low_at": low}}


def make(parcel, parts=None, **settings):
    return P.make_plan(parcel, parts or {}, settings or None, kind_of)


def acres_of(plan):
    return {u["id"]: u["acres"] for u in plan["uses"]}


def use_of(plan, use_id):
    return next(u for u in plan["uses"] if u["id"] == use_id)


def gathered(parcel, parts=None):
    return P.gather(parcel, parts or {}, kind_of)[0]


def scored(parcel, parts=None, count_zoning=True):
    F = gathered(parcel, parts)
    return P.score_uses(F, count_zoning), F


def rich_parts(acres):
    """Every site fact present, so every rule that reads one has something to read."""
    return {
        "state_highway_traffic": highway(0.8, 126000), "people": census(8000, 45000, 90000), "streets": street(acres),
        "surroundings": around(("LDR-2", "low-density", 300.0), ("CR", "commercial", 40.0), ("PF", "public", 5.0)),
        "signals": {"signals": []}, "schools": {"schools": [{"name": "Oak School", "grades": "K-5", "kind": "public", "miles_away": 0.7}]},
        "projects": projects(project("Big Mall", "Commercial", 20, None, 180000, 1.2), project("Other Mall", "Commercial", 15, None, 150000, 1.5),
                             project("Tract A", "Residential", 10, 40, builder="Pardee"), project("Flats", "Residential", 5, 120, description="apartment homes"),
                             project("Sheds", "Industrial", 12, None, 100000, 1.8)),
        "surface": surface(2.0, 5.0, "nearly flat", {"lon": LON, "lat": LAT - 0.003}),
    }


class Plans(unittest.TestCase):
    """Base with a few shared checks."""

    def assertAddsUp(self, plan, msg=None):
        total = sum(acres_of(plan).values())
        self.assertAlmostEqual(total, plan["acres"], delta=0.1, msg=msg)


# ---------------------------------------------------------------- 1. the land is always all used

class EveryAcreIsUsed(Plans):
    def test_acres_of_all_uses_add_up_to_the_parcel_for_every_size_zoning_and_mode(self):
        for acres in (3, 12, 30, 142.1, 505):
            for kind, code in ZONINGS.items():
                for mode in ("zoning", "best"):
                    with self.subTest(acres=acres, kind=kind, mode=mode):
                        plan = make(make_parcel(acres, code), mode=mode)
                        self.assertEqual(plan["acres"], acres)
                        self.assertAddsUp(plan)
                        self.assertTrue(all(v >= 0 for v in acres_of(plan).values()))

    def test_acres_still_add_up_when_every_fact_is_known(self):
        for acres in (3, 12, 30, 142.1, 505):
            for kind, code in ZONINGS.items():
                for mode in ("zoning", "best"):
                    with self.subTest(acres=acres, kind=kind, mode=mode):
                        plan = make(make_parcel(acres, code), rich_parts(acres), mode=mode)
                        self.assertAddsUp(plan)

    def test_acres_add_up_on_a_long_thin_parcel_and_with_steep_ground(self):
        parts = {"surface": surface(12.0, 30.0, "steep")}
        for ratio in (0.25, 1.0, 4.0):
            with self.subTest(ratio=ratio):
                plan = make(make_parcel(60, "LDR-2", ratio), parts, mode="best")
                self.assertAddsUp(plan)

    def test_settle_rounds_to_a_tenth_and_gives_the_gap_to_the_biggest_use(self):
        out = P.settle({"homes": 10.04, "retail": 5.04, "park": 0.5}, 16.0)
        self.assertAlmostEqual(sum(out.values()), 16.0, places=6)
        self.assertEqual(out["homes"], 10.5)
        self.assertEqual((out["retail"], out["park"]), (5.0, 0.5))

    def test_settle_leaves_an_empty_answer_empty_and_never_goes_negative(self):
        self.assertEqual(sum(P.settle({}, 10.0).values()), 0.0)
        out = P.settle({"homes": -3, "retail": "abc", "park": 2.0}, 2.0)
        self.assertTrue(all(v >= 0 for v in out.values()))
        self.assertEqual(out["homes"], 0.0)


# ---------------------------------------------------------------- 2 and 3. zoning mode and best mode

class ZoningMode(Plans):
    def test_no_built_use_the_zoning_does_not_fit_gets_any_acres(self):
        for acres in (12, 30, 142.1):
            for kind, code in ZONINGS.items():
                fit = P.zoning_fit(kind_of(code), code, kind_of)
                for with_facts in (False, True):
                    with self.subTest(acres=acres, kind=kind, facts=with_facts):
                        plan = make(make_parcel(acres, code), rich_parts(acres) if with_facts else None, mode="zoning")
                        got = acres_of(plan)
                        for use in P.BUILT:
                            if fit[use] == "change":
                                self.assertEqual(got[use], 0.0, f"{use} does not fit {code or 'no zoning'}")
                                self.assertEqual(use_of(plan, use)["fit"], "change")

    def test_open_space_and_public_land_is_all_parks_with_nothing_built_spent_or_sold(self):
        for code in ("OS-R", "PF"):
            for acres in (3, 30, 142.1, 505):
                with self.subTest(code=code, acres=acres):
                    plan = make(make_parcel(acres, code, assessed_land_usd=1_000_000), rich_parts(acres), mode="zoning")
                    got = acres_of(plan)
                    self.assertEqual(got["park"], acres)
                    self.assertEqual(sum(v for k, v in got.items() if k != "park"), 0.0)
                    self.assertTrue(plan["nothing_to_build"])
                    self.assertEqual(plan["costs"]["total"], 0)
                    self.assertEqual(plan["money"]["revenue"], 0)
                    self.assertEqual(plan["money"]["land"], 0, "land is only counted when something is sold")
                    self.assertEqual(plan["traffic"]["per_day"], 0)
                    self.assertTrue(any("nothing to build" in line.lower() for line in plan["advice"]))

    def test_open_space_still_has_a_drawing_of_one_piece_of_parks(self):
        plan = make(make_parcel(30, "OS-R"), mode="zoning")
        self.assertEqual([p["use"] for p in plan["drawing"]["pieces"]], ["park"])

    def test_best_use_on_open_space_builds_something_and_calls_it_a_long_shot(self):
        plan = make(make_parcel(30, "OS-R"), mode="best")
        self.assertFalse(plan["nothing_to_build"])
        self.assertTrue(any("long shot" in line.lower() for line in plan["advice"]))


class BestMode(Plans):
    def test_a_use_that_needs_a_zoning_change_can_appear_and_the_advice_names_it(self):
        parcel = make_parcel(100, "LDR-2")
        today = make(parcel, mode="zoning")
        best = make(parcel, mode="best")
        self.assertEqual(acres_of(today)["retail"], 0.0)
        self.assertGreater(acres_of(best)["retail"], 0.0)
        self.assertEqual(use_of(best, "retail")["fit"], "change")
        advice = " ".join(best["advice"]).lower()
        self.assertIn(use_of(best, "retail")["label"].lower(), advice)
        self.assertIn("zoning change", advice)

    def test_the_advice_names_only_the_uses_that_are_in_the_mix_and_need_a_change(self):
        best = make(make_parcel(100, "LDR-2"), mode="best")
        in_mix = [u for u in best["uses"] if u["id"] in P.BUILT and u["acres"] and u["fit"] == "change"]
        advice = " ".join(best["advice"]).lower()
        for u in best["uses"]:
            if u["id"] in P.BUILT and u["fit"] == "change" and not u["acres"]:
                self.assertNotIn(u["label"].lower(), advice)
        self.assertTrue(in_mix)

    def test_no_zoning_change_advice_when_the_mix_all_fits(self):
        best = make(make_parcel(30, "LDR-2"), {"people": census(1000, 3000, 5000)}, mode="best")
        # whatever the mix is, the advice only talks of a change when some used land is marked as needing one
        needs = any(u["acres"] and u["fit"] == "change" for u in best["uses"] if u["id"] in P.BUILT)
        self.assertEqual(needs, any("zoning change" in line for line in best["advice"]))

    def test_best_use_leaves_the_zoning_out_of_every_score(self):
        scores, _ = scored(make_parcel(30, "LDR-2"), count_zoning=False)
        for use, s in scores.items():
            zoning_reasons = [r for r in s["reasons"] if r["source"] == "City zoning"]
            self.assertTrue(all(r["effect"] == 0 for r in zoning_reasons), use)
        counted, _ = scored(make_parcel(30, "LDR-2"), count_zoning=True)
        self.assertGreater(counted["homes"]["score"], scores["homes"]["score"])
        self.assertLess(counted["retail"]["score"], scores["retail"]["score"])


# ---------------------------------------------------------------- 4. shops and the ceiling

class ShopsCeiling(Plans):
    BANDS = {
        "under 10,000": (census(500, 6000, 12000), None, 4.0),
        "10,000 or more": (census(3000, 15000, 30000), None, 10.0),
        "40,000 or more": (census(9000, 45000, 90000), None, 25.0),
        "regional": (census(20000, 90000, 200000), highway(0.8, 126000), 40.0),
    }

    def ceiling(self, people, hw, extra=None):
        parts = {"people": people, **({"state_highway_traffic": hw} if hw else {}), **(extra or {})}
        scores, F = scored(make_parcel(100, "EDC-CC"), parts)
        return P.retail_ceiling(F, scores)

    def test_the_four_population_bands_give_the_four_ceilings(self):
        for name, (people, hw, cap) in self.BANDS.items():
            with self.subTest(band=name):
                got, text = self.ceiling(people, hw)
                self.assertEqual(got, cap)
                self.assertTrue(text)

    def test_the_regional_centre_needs_both_the_crowd_and_a_busy_highway_close_by(self):
        people = census(20000, 90000, 200000)
        self.assertEqual(self.ceiling(people, highway(1.5, 126000))[0], 25.0, "highway too far: community centre")
        self.assertEqual(self.ceiling(people, highway(0.8, 60000))[0], 25.0, "highway too quiet: community centre")
        self.assertEqual(self.ceiling(census(20000, 90000, 149000), highway(0.8, 126000))[0], 25.0, "under 150,000 within 5 miles")
        self.assertEqual(self.ceiling(people, None)[0], 25.0, "no highway count")

    def test_with_no_census_count_shops_are_held_to_a_neighbourhood_centre(self):
        scores, F = scored(make_parcel(100, "EDC-CC"))
        self.assertEqual(P.retail_ceiling(F, scores)[0], 12.0)

    def test_a_lot_of_competing_space_already_planned_cuts_the_ceiling_by_forty_percent(self):
        rivals = projects(project("Mall A", "Commercial", 20, None, 200000, 1.0), project("Mall B", "Commercial", 20, None, 160000, 1.5))
        got, text = self.ceiling(census(3000, 15000, 30000), None, {"projects": rivals})
        self.assertAlmostEqual(got, 6.0)
        some = projects(project("Mall A", "Commercial", 20, None, 60000, 1.0))
        self.assertEqual(self.ceiling(census(3000, 15000, 30000), None, {"projects": some})[0], 10.0, "only a little competing space")

    def test_shops_never_exceed_the_ceiling_in_a_mix_that_has_other_uses(self):
        for name, (people, hw, cap) in self.BANDS.items():
            for acres in (12, 30, 100):
                for mode in ("zoning", "best"):
                    for code in ("EDC-CC", "LDR-2", "BP", ""):
                        with self.subTest(band=name, acres=acres, mode=mode, code=code):
                            parts = {"people": people, **({"state_highway_traffic": hw} if hw else {})}
                            parcel = make_parcel(acres, code)
                            plan = make(parcel, parts, mode=mode)
                            scores, F = scored(parcel, parts, count_zoning=mode != "best")
                            ceiling = P.retail_ceiling(F, scores)[0]
                            self.assertLessEqual(acres_of(plan)["retail"], ceiling + 0.05)

    def test_a_big_new_neighbourhood_gets_its_own_shops_sized_by_its_residents_not_by_the_ceiling(self):
        # Best use, 505 acres, almost no one nearby: the ceiling is 4 acres, but the plan's own homes bring shops.
        plan = make(make_parcel(505, "LDR-2"), {"people": census(500, 6000, 12000)}, mode="best")
        retail = acres_of(plan)["retail"]
        homes = use_of(plan, "homes")
        residents = homes["people"] + use_of(plan, "apartments").get("people", 0)
        self.assertGreater(retail, 4.0)
        self.assertLessEqual(retail, 12.0)
        self.assertAlmostEqual(retail, min(12.0, round(residents / 1000, 1)), delta=0.6)
        self.assertTrue(any("corner of neighbourhood shops" in n for n in plan["notes"]))

    def test_land_zoned_only_for_shops_does_not_come_back_as_shops_beyond_the_ceiling(self):
        # CR on 100 acres with 15,000 people within 3 miles (ceiling 10 acres): shops stay at the ceiling, offices at theirs,
        # and the rest is held open as parks with a note saying so.
        parts = {"people": census(3000, 15000, 30000)}
        parcel = make_parcel(100, "CR")
        plan = make(parcel, parts, mode="zoning")
        scores, F = scored(parcel, parts)
        got = acres_of(plan)
        self.assertLessEqual(got["retail"], P.retail_ceiling(F, scores)[0] + 0.05)
        self.assertEqual(got["retail"], 10.0)
        self.assertEqual(got["office"], 8.0)
        self.assertGreater(got["park"], 50.0, "the rest is held open")
        self.assertTrue(any("held for later" in n for n in plan["notes"]))

    def test_with_no_census_count_the_same_land_keeps_shops_at_twelve_acres(self):
        plan = make(make_parcel(100, "CR"), mode="zoning")
        self.assertLessEqual(acres_of(plan)["retail"], 12.05)
        self.assertTrue(any("held for later" in n for n in plan["notes"]))

    def test_when_the_rest_can_go_to_apartments_or_business_it_does_not_go_to_shops(self):
        # EDC-CC fits shops, offices and apartments: apartments (a rule of proportion) take what the shops cannot
        plan = make(make_parcel(100, "EDC-CC"), {"people": census(3000, 15000, 30000)}, mode="zoning")
        got = acres_of(plan)
        self.assertLessEqual(got["retail"], 10.05)
        self.assertGreater(got["apartments"] + got["business"], 0)
        self.assertFalse(any("held for later" in n for n in plan["notes"]))

    def test_apartments_take_at_most_forty_percent_where_the_zoning_fits_them_and_a_quarter_elsewhere(self):
        for code, share in (("HDR", 0.40), ("EDC-CC", 0.40), ("LDR-2", 0.25)):
            with self.subTest(code=code):
                plan = make(make_parcel(100, code), mode="best")
                self.assertLessEqual(acres_of(plan)["apartments"], share * 100 + 0.1)

    def test_a_business_park_that_the_zoning_only_reviews_is_held_to_thirty_five_percent_in_zoning_mode(self):
        for code in ("EDC-CC", "CR", "SP-1"):
            # up to 100 acres: on bigger land the leftover the shops and offices cannot take is shared out to apartments and
            # business in proportion, which stretches their own proportions (EDC-CC 505 acres: business 197.3 = 39%)
            for acres in (12, 30, 100):
                with self.subTest(code=code, acres=acres):
                    plan = make(make_parcel(acres, code), mode="zoning")
                    if use_of(plan, "business")["fit"] == "review":
                        self.assertLessEqual(acres_of(plan)["business"], 0.35 * acres + 0.1)
                    self.assertAddsUp(plan)

    def test_land_zoned_only_for_shops_still_adds_up_and_leaves_out_the_uses_it_does_not_fit(self):
        plan = make(make_parcel(100, "CR"), {"people": census(3000, 15000, 30000)}, mode="zoning")
        self.assertAddsUp(plan)
        got = acres_of(plan)
        self.assertEqual((got["apartments"], got["homes"], got["business"]), (0.0, 0.0, 0.0))
        self.assertGreater(got["park"], 0.0)


# ---------------------------------------------------------------- 5. scores and their reasons

class Scores(Plans):
    def retail(self, parts=None, code="EDC-CC", count_zoning=True):
        return scored(make_parcel(100, code), parts, count_zoning)[0]["retail"]

    def test_a_busy_highway_close_by_raises_the_shops_score_and_a_distant_one_lowers_it(self):
        base = self.retail()["score"]
        close = self.retail({"state_highway_traffic": highway(0.5, 126000)})["score"]
        middle = self.retail({"state_highway_traffic": highway(2.0, 126000)})["score"]
        far = self.retail({"state_highway_traffic": highway(4.0, 126000)})["score"]
        self.assertGreater(close, middle)
        self.assertGreater(middle, base)
        self.assertGreater(base, far)

    def test_a_quiet_highway_helps_less_than_a_busy_one(self):
        busy = self.retail({"state_highway_traffic": highway(0.5, 100000)})["score"]
        quiet = self.retail({"state_highway_traffic": highway(0.5, 20000)})["score"]
        self.assertGreater(busy, quiet)
        self.assertGreater(quiet, self.retail()["score"])

    def test_a_fronting_street_of_rank_three_or_more_raises_the_score_and_no_street_lowers_it(self):
        base = self.retail({"people": census(1000, 15000, 30000)})["score"]
        big = self.retail({"people": census(1000, 15000, 30000), "streets": street(100, rank=4, cls="Urban Arterial")})["score"]
        small = self.retail({"people": census(1000, 15000, 30000), "streets": street(100, rank=2, cls="Secondary")})["score"]
        none = self.retail({"people": census(1000, 15000, 30000), "streets": street(100, rank=4, off=3000.0)})["score"]
        self.assertGreater(big, small)
        self.assertGreater(small, base)
        self.assertGreater(base, none)

    def test_a_street_further_than_150_feet_is_not_a_frontage(self):
        F = gathered(make_parcel(100), {"streets": street(100, off=400.0)})
        self.assertIsNone(F["frontage"])
        self.assertEqual(F["streets"][0]["name"], "Main St")
        self.assertGreater(F["streets"][0]["feet"], 150)

    def test_more_people_nearby_raises_the_shops_score(self):
        thin = self.retail({"people": census(500, 5000, 9000)})["score"]
        middle = self.retail({"people": census(500, 15000, 30000)})["score"]
        big = self.retail({"people": census(500, 30000, 60000)})["score"]
        huge = self.retail({"people": census(500, 60000, 120000)})["score"]
        self.assertLess(thin, middle)
        self.assertLess(middle, big)
        self.assertLess(big, huge)

    def test_every_reason_has_text_a_number_effect_and_a_source(self):
        for count_zoning in (True, False):
            for code in ("EDC-CC", "LDR-2", "BP", "HDR"):
                with self.subTest(code=code, count_zoning=count_zoning):
                    scores, _ = scored(make_parcel(60, code), rich_parts(60), count_zoning)
                    self.assertEqual(set(scores), set(P.BUILT))
                    for use, s in scores.items():
                        self.assertTrue(s["reasons"], use)
                        for r in s["reasons"]:
                            self.assertIsInstance(r["text"], str)
                            self.assertTrue(r["text"].strip())
                            self.assertIsInstance(r["effect"], (int, float))
                            self.assertNotIsInstance(r["effect"], bool)
                            self.assertTrue(r["source"].strip())

    def test_the_score_is_the_start_plus_the_reasons_cut_off_at_zero_and_a_hundred(self):
        for code in ZONINGS.values():
            for mode in (True, False):
                scores, _ = scored(make_parcel(60, code), rich_parts(60), mode)
                for use, s in scores.items():
                    self.assertTrue(0 <= s["score"] <= 100, (code, use, s["score"]))

    def test_a_pile_of_bad_news_stops_at_zero(self):
        parts = {"state_highway_traffic": highway(4.0, 126000), "people": census(500, 5000, 9000), "streets": street(100, off=3000.0)}
        s, _ = scored(make_parcel(100, "LDR-2"), parts)
        retail = s["retail"]
        self.assertEqual(retail["reasons"][-1]["effect"], -sum(r["effect"] for r in retail["reasons"][:-1]), "the points held back are listed")
        self.assertLess(sum(r["effect"] for r in retail["reasons"][:-1]), 0)
        self.assertEqual(retail["score"], 0)
        self.assertEqual(sum(r["effect"] for r in retail["reasons"]), retail["score"])

    def test_the_reasons_add_up_to_the_score_when_nothing_is_cut_off(self):
        parts = {"state_highway_traffic": highway(0.5, 126000), "people": census(500, 15000, 30000), "streets": street(100, rank=4)}
        s, _ = scored(make_parcel(100, "EDC-CC"), parts)
        retail = s["retail"]
        self.assertEqual(retail["score"], sum(r["effect"] for r in retail["reasons"]))
        self.assertEqual(retail["reasons"][0]["effect"], 30, "the starting score is the first reason, in words")

    def test_every_score_equals_the_sum_of_its_listed_reasons_for_every_kind_of_land(self):
        for kind, code in ZONINGS.items():
            for count_zoning in (True, False):
                for parts in ({}, rich_parts(100)):
                    s, _ = scored(make_parcel(100, code), parts, count_zoning)
                    for use, got in s.items():
                        with self.subTest(kind=kind, use=use, count_zoning=count_zoning):
                            self.assertEqual(got["score"], sum(r["effect"] for r in got["reasons"]))

    def test_the_fit_of_each_use_is_carried_with_its_score(self):
        s, _ = scored(make_parcel(100, "HDR"))
        self.assertEqual((s["apartments"]["fit"], s["homes"]["fit"], s["retail"]["fit"]), ("fits", "fits", "change"))

    def test_zoning_fit_by_family(self):
        self.assertEqual(P.zoning_fit("commercial", "CR", kind_of)["retail"], "fits")
        self.assertEqual(P.zoning_fit("business", "BP", kind_of)["retail"], "review")
        self.assertEqual(P.zoning_fit("specific-plan", "SP-1", kind_of)["homes"], "review")
        self.assertEqual(P.zoning_fit("edc", "EDC-NG", kind_of)["business"], "fits")
        self.assertEqual(P.zoning_fit("edc", "EDC-CC", kind_of)["apartments"], "fits")
        self.assertEqual(P.zoning_fit("other", "", kind_of)["retail"], "unknown")
        self.assertEqual(P.zoning_fit("open-space", "OS-R", kind_of)["homes"], "change")
        for kind in ("edc", "other", "public", "mixed", "low-density"):
            self.assertEqual(P.zoning_fit(kind, "LDR-2 & CR" if kind == "mixed" else "X", kind_of)["park"], "fits")

    def test_a_mixed_zone_fits_what_either_part_fits(self):
        fit = P.zoning_fit("mixed", "LDR-2 & CR", kind_of)
        self.assertEqual((fit["homes"], fit["retail"], fit["office"]), ("fits", "fits", "fits"))
        self.assertEqual(fit["business"], "change")


# ---------------------------------------------------------------- 6. frontage and where things are drawn

class Frontage(Plans):
    def test_a_classed_street_along_the_south_edge_is_found_as_the_frontage(self):
        plan = make(make_parcel(142.1), {"streets": street(142.1)}, mode="best")
        front = plan["facts"]["frontage"]
        self.assertEqual((front["name"], front["class"], front["rank"]), ("Main St", "Major", 3))
        self.assertLessEqual(front["feet"], 150)
        self.assertNotIn("at", front, "the plain facts leave the internal point out")
        self.assertIsNone(plan["facts"]["corner"])

    def test_shops_sit_nearer_the_street_edge_than_houses_on_the_south(self):
        parcel = make_parcel(142.1)
        plan = make(parcel, {"streets": street(142.1), "surroundings": housing_around()}, mode="best")
        got = acres_of(plan)
        self.assertGreater(got["retail"], 0)
        self.assertGreater(got["homes"], 0)
        where = {p["use"]: p["label_at"] for p in plan["drawing"]["pieces"]}
        south = FRAME.ll(0, -dims(142.1)[1] / 2)[1]
        self.assertLess(where["retail"][1], LAT, "shops are in the southern half")
        self.assertLess(where["retail"][1] - south, where["homes"][1] - south)

    def test_shops_sit_nearer_the_street_edge_than_houses_on_the_north_as_well(self):
        plan = make(make_parcel(142.1), {"streets": street(142.1, side="north"), "surroundings": housing_around()}, mode="best")
        where = {p["use"]: p["label_at"] for p in plan["drawing"]["pieces"]}
        self.assertGreater(where["retail"][1], LAT, "shops are in the northern half")
        self.assertGreater(where["retail"][1], where["homes"][1])

    def test_a_long_parcel_with_its_street_on_the_short_south_side_still_puts_shops_there(self):
        plan = make(make_parcel(142.1, ratio=0.25), {"streets": street(142.1, ratio=0.25), "surroundings": housing_around()}, mode="best")
        where = {p["use"]: p["label_at"] for p in plan["drawing"]["pieces"]}
        self.assertLess(where["retail"][1], where["homes"][1])

    def test_with_no_street_the_south_side_is_the_front_and_the_advice_says_to_settle_access(self):
        plan = make(make_parcel(60), {"streets": {"streets": []}}, mode="best")
        self.assertIsNone(plan["facts"]["frontage"])
        self.assertTrue(any("how people get in" in a.lower() for a in plan["advice"]))
        self.assertEqual(plan["traffic"]["entrances"], [])

    def test_two_classed_streets_make_a_corner_and_the_better_one_is_the_frontage(self):
        w, h = dims(60)
        south = street(60, name="South Rd", cls="Major", rank=3)["streets"][0]
        east_pts = [(w / 2 + 25, -h), (w / 2 + 25, 0), (w / 2 + 25, h)]
        east = {"name": "East Blvd", "class": "Urban Arterial", "rank": 4, "speed_mph": 45, "paths": [[FRAME.ll(x, y) for x, y in east_pts]]}
        plan = make(make_parcel(60), {"streets": {"streets": [south, east]}}, mode="best")
        self.assertEqual(plan["facts"]["frontage"]["name"], "East Blvd")
        self.assertEqual(plan["facts"]["corner"]["name"], "South Rd")


# ---------------------------------------------------------------- 7. the drawing

class Drawing(Plans):
    def outline_area(self, parcel):
        ring = parcel["outline"]["coordinates"][0]
        return G.area(FRAME.ring(ring))

    def test_there_is_one_piece_for_every_use_with_acres_and_none_for_the_rest(self):
        cases = [(make_parcel(142.1, "EDC-CC"), "zoning"), (make_parcel(142.1, "LDR-2"), "best"), (make_parcel(12, "HDR"), "zoning"),
                 (make_parcel(505, "BP"), "best"), (make_parcel(3, "OS-R"), "zoning")]
        for parcel, mode in cases:
            with self.subTest(zoning=parcel["zoning"], acres=parcel["acres"], mode=mode):
                plan = make(parcel, rich_parts(parcel["acres"]), mode=mode)
                used = sorted(u for u, a in acres_of(plan).items() if a > 0)
                drawn = sorted(p["use"] for p in plan["drawing"]["pieces"])
                self.assertEqual(drawn, used)
                self.assertEqual(len(drawn), len(set(drawn)))
                for piece in plan["drawing"]["pieces"]:
                    self.assertEqual(piece["acres"], acres_of(plan)[piece["use"]])

    def test_every_ring_is_closed_and_the_pieces_fill_the_outline(self):
        for acres, ratio, code, mode in [(142.1, 1.0, "EDC-CC", "zoning"), (142.1, 3.0, "LDR-2", "best"), (30, 0.4, "HDR", "zoning"),
                                         (505, 1.0, "EDC-CC", "best"), (12, 2.0, "BP", "zoning")]:
            with self.subTest(acres=acres, ratio=ratio, code=code, mode=mode):
                parcel = make_parcel(acres, code, ratio)
                plan = make(parcel, {"streets": street(acres, ratio=ratio)}, mode=mode)
                total = 0.0
                for piece in plan["drawing"]["pieces"]:
                    ring = piece["ring"]
                    self.assertGreaterEqual(len(ring), 4)
                    self.assertEqual(ring[0], ring[-1], "closed: the first point is the last")
                    total += G.area(FRAME.ring(ring))
                self.assertAlmostEqual(total / self.outline_area(parcel), 1.0, delta=0.01)

    def test_each_piece_is_about_the_size_of_its_acres(self):
        parcel = make_parcel(142.1, "LDR-2")
        plan = make(parcel, {"streets": street(142.1)}, mode="best")
        for piece in plan["drawing"]["pieces"]:
            drawn = G.area(FRAME.ring(piece["ring"])) / ACRE
            self.assertAlmostEqual(drawn, piece["acres"], delta=max(0.5, 0.02 * piece["acres"]))

    def test_every_label_point_is_inside_the_parcel(self):
        parcel = make_parcel(142.1, "LDR-2")
        outline = FRAME.ring(parcel["outline"]["coordinates"][0])
        plan = make(parcel, {"streets": street(142.1)}, mode="best")
        for piece in plan["drawing"]["pieces"]:
            self.assertTrue(G.inside(outline, FRAME.xy(*piece["label_at"])), piece["use"])

    def test_the_plans_own_streets_lie_between_pieces_and_are_priced_by_their_length(self):
        plan = make(make_parcel(142.1), {"streets": street(142.1)}, mode="best")
        streets = plan["drawing"]["streets"]
        self.assertEqual(len(streets), len(plan["drawing"]["pieces"]) - 1)
        for s in streets:
            a, b = (FRAME.xy(*p) for p in s["line"])
            self.assertAlmostEqual(math.hypot(b[0] - a[0], b[1] - a[1]), s["feet"], delta=1.0)
        line = next(x for x in plan["costs"]["lines"] if x["id"] == "cost_street_per_ft")
        self.assertEqual(line["quantity"], round(float(sum(s["feet"] for s in streets)), 1))

    def test_the_internal_cut_ends_are_not_left_in_the_answer(self):
        plan = make(make_parcel(60), mode="best")
        self.assertNotIn("cut_ends", plan["drawing"])

    def test_a_parcel_with_no_outline_still_gets_a_plan_but_no_drawing(self):
        parcel = make_parcel(40, "LDR-2")
        parcel["outline"] = None
        plan = make(parcel, mode="best")
        self.assertIsNone(plan["drawing"])
        self.assertAddsUp(plan)
        self.assertEqual(plan["traffic"]["entrances"], [])
        self.assertTrue(plan["costs"]["total"] > 0, "costs fall back to one street across the parcel")

    def test_a_parcel_in_several_pieces_is_drawn_on_the_largest_and_says_so(self):
        parcel = make_parcel(40, "LDR-2")
        small = [FRAME.ll(x, y) for x, y in ((3000, 3000), (3100, 3000), (3100, 3100), (3000, 3100), (3000, 3000))]
        parcel["outline"]["coordinates"].append(small)
        plan = make(parcel, mode="best")
        self.assertTrue(plan["drawing"]["note"])
        self.assertAlmostEqual(plan["drawing"]["drawn_acres"], 40.0, delta=0.1)


# ---------------------------------------------------------------- 8. starting figures

class StartingFigures(Plans):
    def figures(self, parcel, parts=None):
        return P.starting_figures(gathered(parcel, parts))

    def test_with_nothing_nearby_every_figure_keeps_its_starting_assumption(self):
        figs = self.figures(make_parcel(40, "LDR-2"))
        self.assertEqual(set(figs), set(P.ASSUMPTIONS))
        for key, (label, unit, value, group) in P.ASSUMPTIONS.items():
            self.assertEqual((figs[key]["kind"], figs[key]["value"], figs[key]["start"]), ("assumption", value, value), key)
            self.assertEqual((figs[key]["label"], figs[key]["unit"], figs[key]["group"]), (label, unit, group))

    def test_two_or_more_nearby_housing_tracts_set_homes_per_acre_to_their_median(self):
        parts = {"projects": projects(project("A", "Residential", 10, 40), project("B", "Residential", 20, 100), project("C", "Residential", 8, 24))}
        fig = self.figures(make_parcel(40, "LDR-2"), parts)["homes_per_acre"]
        self.assertEqual((fig["kind"], fig["value"], fig["start"]), ("measured", 4.0, 4.0))
        parts = {"projects": projects(project("A", "Residential", 10, 30), project("B", "Residential", 10, 50))}
        self.assertEqual(self.figures(make_parcel(40, "LDR-2"), parts)["homes_per_acre"]["value"], 4.0)

    def test_one_housing_tract_is_not_enough_and_small_or_unstated_ones_are_ignored(self):
        cases = [projects(project("A", "Residential", 10, 40)),
                 projects(project("A", "Residential", 2, 10), project("B", "Residential", 2, 12)),
                 projects(project("A", "Residential", 10, None), project("B", "Residential", None, 40)),
                 projects(project("A", "Commercial", 10, 40), project("B", "Commercial", 20, 100))]
        for rows in cases:
            fig = self.figures(make_parcel(40, "LDR-2"), {"projects": rows})["homes_per_acre"]
            self.assertEqual((fig["kind"], fig["value"]), ("assumption", 4.5))

    def test_denser_projects_count_as_apartments_not_houses(self):
        parts = {"projects": projects(project("Flats A", "Residential", 5, 100), project("Flats B", "Residential", 10, 300))}
        figs = self.figures(make_parcel(40, "HDR"), parts)
        self.assertEqual((figs["apartments_per_acre"]["kind"], figs["apartments_per_acre"]["value"]), ("measured", 25.0))
        self.assertEqual(figs["homes_per_acre"]["kind"], "assumption")

    def test_census_rings_give_people_per_home_as_people_over_homes(self):
        figs = self.figures(make_parcel(40), {"people": census(1000, 31000, 60000, homes_share=0.4)})
        fig = figs["people_per_home"]
        self.assertEqual(fig["kind"], "measured")
        self.assertEqual(fig["value"], round(31000 / round(31000 * 0.4), 2))
        # without the 3-mile ring the 1-mile one is used
        one = self.figures(make_parcel(40), {"people": {"rings": [{"miles": 1, "people": 900, "homes": 300}]}})["people_per_home"]
        self.assertEqual((one["kind"], one["value"]), ("measured", 3.0))
        # a ring with no homes says nothing
        zero = self.figures(make_parcel(40), {"people": {"rings": [{"miles": 3, "people": 900, "homes": 0}]}})["people_per_home"]
        self.assertEqual((zero["kind"], zero["value"]), ("assumption", 3.0))

    def test_a_general_plan_range_on_low_density_land_gives_the_middle_of_the_range(self):
        parts = {"general_plan": {"description": "2.1-5 du/ac Residential (2.1-5 R)"}}
        fig = self.figures(make_parcel(40, "LDR-2"), parts)["homes_per_acre"]
        self.assertEqual(fig["kind"], "measured")
        self.assertEqual(fig["value"], 3.5, "(2.1 + 5) / 2 = 3.55, rounded to one place by the code")
        self.assertEqual(P.density_from_plan(parts["general_plan"], "")["homes_range"], (2.1, 5.0))

    def test_a_range_of_eight_or_more_homes_an_acre_sets_apartments_per_acre(self):
        parts = {"general_plan": {"description": "8-20 du/ac Residential"}}
        figs = self.figures(make_parcel(40, "HDR"), parts)
        self.assertEqual((figs["apartments_per_acre"]["value"], figs["apartments_per_acre"]["kind"]), (14.0, "measured"))
        self.assertEqual(figs["homes_per_acre"]["kind"], "assumption")

    def test_a_general_plan_range_is_ignored_on_land_that_is_not_housing(self):
        parts = {"general_plan": {"description": "2.1-5 du/ac Residential"}}
        for code in ("CR", "BP", "EDC-CC"):
            self.assertEqual(self.figures(make_parcel(40, code), parts)["homes_per_acre"]["kind"], "assumption")

    def test_rural_land_with_a_two_acre_minimum_lot_gives_a_little_under_half_a_home_an_acre(self):
        parts = {"general_plan": {"description": "Rural Residential 2 ac min (RR2)"}}
        fig = self.figures(make_parcel(40, "RR2"), parts)["homes_per_acre"]
        self.assertEqual(fig["kind"], "measured")
        self.assertEqual(fig["value"], 0.42, "0.85 / 2 = 0.425, rounded to two places by the code")
        self.assertAlmostEqual(fig["value"], 0.85 / 2, delta=0.006)

    def test_lot_sizes_written_as_fractions_and_other_spellings_are_read(self):
        self.assertEqual(P.density_from_plan({"description": "Residential 1/2 acre min"}, "")["lot_acres"], 0.5)
        self.assertEqual(P.density_from_plan({"label": "Estate 5-ac min"}, "")["lot_acres"], 5.0)
        self.assertEqual(P.density_from_plan({"description": "0.5-1.5 FAR Commercial"}, "")["far_range"], (0.5, 1.5))
        self.assertEqual(P.density_from_plan(None, "Nothing here"), {})

    def test_a_floor_area_range_on_commercial_land_sets_the_shop_figure(self):
        parts = {"general_plan": {"description": "0.2-0.4 FAR Commercial"}}
        fig = self.figures(make_parcel(40, "CR"), parts)["retail_far"]
        self.assertEqual((fig["kind"], fig["value"]), ("measured", 0.3))
        fig = self.figures(make_parcel(40, "BP"), parts)["business_far"]
        self.assertEqual((fig["kind"], fig["value"]), ("measured", 0.3))

    def test_nearby_commercial_and_industrial_projects_set_the_floor_space_figures(self):
        acre = ACRE
        parts = {"projects": projects(project("S1", "Commercial", 5, None, 0.2 * 5 * acre), project("S2", "Commercial", 10, None, 0.3 * 10 * acre),
                                      project("I1", "Industrial", 10, None, 0.5 * 10 * acre))}
        figs = self.figures(make_parcel(40, "CR"), parts)
        self.assertEqual((figs["retail_far"]["kind"], figs["retail_far"]["value"]), ("measured", 0.25))
        self.assertEqual((figs["business_far"]["kind"], figs["business_far"]["value"]), ("measured", 0.5))

    def test_a_measured_figure_is_what_the_plan_uses_until_the_owner_changes_it(self):
        parts = {"general_plan": {"description": "2.1-5 du/ac Residential"}}
        plan = make(make_parcel(40, "LDR-2"), parts)
        fig = next(f for f in plan["figures"] if f["id"] == "homes_per_acre")
        self.assertEqual((fig["kind"], fig["value"]), ("measured", 3.5))
        homes = use_of(plan, "homes")
        self.assertEqual(homes["homes"], round(homes["acres"] * 3.5))


# ---------------------------------------------------------------- 9. the owner's settings

class Settings(Plans):
    def test_unknown_figures_negative_numbers_and_text_are_dropped(self):
        out = P.clean_settings({"assumptions": {"price_retail": 900000, "nonsense": 5, "homes_per_acre": -2, "trips_home": "lots",
                                                "retail_far": "0.3", "people_per_home": None, "contingency_pct": float("nan"),
                                                "fees_total": 1e12}})
        self.assertEqual(out["assumptions"], {"price_retail": 900000.0, "retail_far": 0.3})

    def test_an_unknown_mode_becomes_zoning_and_best_stays_best(self):
        for given, want in (("best", "best"), ("zoning", "zoning"), ("everything", "zoning"), (None, "zoning"), (5, "zoning"), ("BEST", "zoning")):
            self.assertEqual(P.clean_settings({"mode": given})["mode"], want, given)

    def test_settings_that_are_not_a_dictionary_give_the_plain_defaults(self):
        for bad in (None, [], "text", 5):
            self.assertEqual(P.clean_settings(bad), {"mode": "zoning", "acres": None, "assumptions": {}, "extra_costs": [], "land_cost": None})

    def test_at_most_sixty_extra_costs_are_kept_and_ones_without_a_number_are_dropped(self):
        many = [{"name": f"Cost {i}", "amount": i} for i in range(70)]
        out = P.clean_settings({"extra_costs": many})
        self.assertEqual(len(out["extra_costs"]), 60)
        self.assertEqual(out["extra_costs"][59]["name"], "Cost 59")
        mixed = P.clean_settings({"extra_costs": [{"name": "ok", "amount": "12"}, {"name": "bad", "amount": "lots"}, "text", {"amount": 5}, {"amount": None}]})
        self.assertEqual([(x["name"], x["amount"]) for x in mixed["extra_costs"]], [("ok", 12.0), ("Other cost", 5.0)])
        self.assertEqual(len(P.clean_settings({"extra_costs": [{"name": "n" * 300, "amount": 1}]})["extra_costs"][0]["name"]), 80)

    def test_land_cost_needs_a_number_in_range(self):
        self.assertEqual(P.clean_settings({"land_cost": "250000"})["land_cost"], 250000.0)
        self.assertEqual(P.clean_settings({"land_cost": 0})["land_cost"], 0.0)
        for bad in (-1, "much", None, 1e12):
            self.assertIsNone(P.clean_settings({"land_cost": bad})["land_cost"])

    def test_custom_acres_keep_only_numbers_and_drop_negatives_to_zero(self):
        out = P.clean_settings({"acres": {"retail": 5, "homes": "x", "park": -3, "bogus": 9}})
        self.assertEqual(out["acres"]["retail"], 5.0)
        self.assertEqual(out["acres"]["homes"], 0.0)
        self.assertEqual(out["acres"]["park"], 0.0)
        self.assertNotIn("bogus", out["acres"])
        self.assertIsNone(P.clean_settings({"acres": {"homes": "x"}})["acres"])
        self.assertIsNone(P.clean_settings({"acres": [1, 2]})["acres"])

    def test_clean_settings_is_idempotent(self):
        once = P.clean_settings({"mode": "best", "assumptions": {"price_retail": 5}, "extra_costs": [{"name": "x", "amount": 3}],
                                 "land_cost": 7, "acres": {"retail": 2, "homes": 3}})
        self.assertEqual(P.clean_settings(once), once)

    def test_a_changed_figure_comes_back_as_yours_and_an_unchanged_one_does_not(self):
        plan = make(make_parcel(60, "EDC-CC"), assumptions={"price_retail": 970000, "price_office": 650000})
        by_id = {f["id"]: f for f in plan["figures"]}
        self.assertEqual((by_id["price_retail"]["kind"], by_id["price_retail"]["value"], by_id["price_retail"]["start"]), ("yours", 970000.0, 870000.0))
        self.assertEqual(by_id["price_office"]["kind"], "assumption", "the same as the starting figure")
        self.assertEqual(by_id["price_homes"]["kind"], "assumption")
        self.assertEqual(plan["settings"]["assumptions"], {"price_retail": 970000.0, "price_office": 650000.0})

    def test_raising_the_shop_land_price_raises_revenue_by_exactly_shop_acres_times_the_difference(self):
        parcel = make_parcel(60, "EDC-CC")
        before = make(parcel)
        after = make(parcel, assumptions={"price_retail": 970000})
        retail = acres_of(before)["retail"]
        self.assertGreater(retail, 0)
        self.assertEqual(acres_of(after), acres_of(before), "a price does not change the mix")
        self.assertEqual(after["money"]["revenue"] - before["money"]["revenue"], round(retail * 970000) - round(retail * 870000))
        self.assertEqual(after["money"]["revenue"] - before["money"]["revenue"], round(retail * 100000))

    def test_a_figure_that_changes_what_fits_changes_the_mix(self):
        parcel = make_parcel(60, "LDR-2")
        more = make(parcel, assumptions={"homes_per_acre": 9.0})
        self.assertEqual(use_of(more, "homes")["homes"], round(use_of(more, "homes")["acres"] * 9.0))
        self.assertGreater(use_of(more, "homes")["homes"], use_of(make(parcel), "homes")["homes"])

    def test_custom_acres_are_scaled_to_the_parcel_and_the_plan_says_it_was_edited(self):
        parcel = make_parcel(100, "EDC-CC")
        plan = make(parcel, acres={"retail": 10, "homes": 30})
        self.assertTrue(plan["edited"])
        got = acres_of(plan)
        self.assertEqual((got["retail"], got["homes"]), (25.0, 75.0))
        self.assertEqual(sum(got.values()), 100.0)
        for u in plan["uses"]:
            self.assertEqual(u["share_pct"], round(100 * u["acres"] / 100, 1))
        self.assertTrue(all(u["suggested_acres"] != u["acres"] for u in plan["uses"] if u["id"] in ("retail", "homes")))

    def test_custom_acres_that_match_the_suggestion_are_not_called_edited(self):
        parcel = make_parcel(100, "EDC-CC")
        base = make(parcel)
        same = make(parcel, acres=acres_of(base))
        self.assertFalse(same["edited"])
        self.assertEqual(acres_of(same), acres_of(base))

    def test_custom_acres_of_zero_are_ignored(self):
        plan = make(make_parcel(100, "EDC-CC"), acres={"retail": 0, "homes": 0})
        self.assertFalse(plan["edited"])
        self.assertAddsUp(plan)

    def test_custom_acres_work_in_a_zoning_that_does_not_fit(self):
        plan = make(make_parcel(100, "OS-R"), acres={"retail": 100})
        self.assertEqual(acres_of(plan)["retail"], 100.0)
        self.assertTrue(plan["edited"])
        self.assertTrue(plan["nothing_to_build"], "that flag describes the suggestion, not the owner's edit")

    def test_extra_costs_are_added_to_the_cost_total(self):
        parcel = make_parcel(60, "EDC-CC")
        base = make(parcel)
        extra = make(parcel, extra_costs=[{"name": "Soil clean-up", "amount": 250000}, {"name": "Survey", "amount": 15000.4}])
        self.assertEqual(extra["costs"]["total"] - base["costs"]["total"], 250000 + 15000)
        self.assertEqual([(x["name"], x["amount"]) for x in extra["costs"]["extra"]], [("Soil clean-up", 250000), ("Survey", 15000)])
        self.assertEqual(extra["money"]["costs"], extra["costs"]["total"])
        self.assertEqual(extra["costs"]["contingency"], base["costs"]["contingency"], "extra costs do not carry the allowance")

    def test_fees_are_added_after_the_allowance(self):
        parcel = make_parcel(60, "EDC-CC")
        base = make(parcel)
        fees = make(parcel, assumptions={"fees_total": 400000})
        self.assertEqual(fees["costs"]["total"] - base["costs"]["total"], 400000)
        self.assertEqual(fees["costs"]["fees"], 400000)

    def test_a_land_cost_replaces_the_assessed_stand_in(self):
        parcel = make_parcel(60, "EDC-CC", assessed_land_usd=800000)
        base = make(parcel)
        self.assertEqual((base["money"]["land"], base["money"]["land_is_stand_in"]), (800000, True))
        mine = make(parcel, land_cost=3_000_000)
        self.assertEqual((mine["money"]["land"], mine["money"]["land_is_stand_in"]), (3_000_000, False))
        self.assertEqual(base["money"]["profit"] - mine["money"]["profit"], 3_000_000 - 800000)
        self.assertEqual(mine["money"]["assessed_land"], 800000)

    def test_a_land_cost_of_zero_is_a_real_answer(self):
        mine = make(make_parcel(60, "EDC-CC", assessed_land_usd=800000), land_cost=0)
        self.assertEqual((mine["money"]["land"], mine["money"]["land_is_stand_in"]), (0, False))

    def test_with_no_assessed_value_and_no_land_cost_the_land_counts_as_nothing(self):
        plan = make(make_parcel(60, "EDC-CC"))
        self.assertEqual((plan["money"]["land"], plan["money"]["land_is_stand_in"]), (0, True))


# ---------------------------------------------------------------- 10. the arithmetic, worked by hand

class Arithmetic(Plans):
    """100 acres, with the owner's own mix: 40 acres of houses, 20 of apartments, 10 of shops, 30 of parks. No site facts
    at all, so no entrances and no signals; the rest follows from the starting figures."""

    @classmethod
    def setUpClass(cls):
        cls.plan = make(make_parcel(100, "EDC-CC", assessed_land_usd=2_500_000),
                        acres={"homes": 40, "apartments": 20, "retail": 10, "park": 30})
        cls.feet = sum(s["feet"] for s in cls.plan["drawing"]["streets"])

    def test_the_mix_is_the_owners(self):
        self.assertEqual(acres_of(self.plan), {"retail": 10.0, "office": 0.0, "apartments": 20.0, "homes": 40.0, "business": 0.0, "park": 30.0})

    def test_homes_floor_space_people_and_jobs(self):
        homes, flats, shops = (use_of(self.plan, u) for u in ("homes", "apartments", "retail"))
        self.assertEqual(homes["homes"], 40 * 4.5)
        self.assertEqual(flats["homes"], 20 * 20)
        self.assertEqual(homes["people"], round(180 * 3.0))
        self.assertEqual(flats["people"], round(400 * 2.3))
        sq_ft = round(10 * 43560 * 0.22 / 100) * 100
        self.assertEqual(sq_ft, 95800)
        self.assertEqual(shops["sq_ft"], sq_ft)
        self.assertEqual(shops["jobs"], round(95.8 * 2.0))

    def test_trips_follow_from_homes_and_floor_space(self):
        total = 180 * 9.4 + 400 * 6.7 + 95.8 * 37.0
        traffic = self.plan["traffic"]
        self.assertEqual(traffic["per_day"], round(total))
        self.assertEqual(traffic["peak_hour"], round(total * 10 / 100))
        self.assertEqual(traffic["by_use"], {"homes": round(180 * 9.4), "apartments": round(400 * 6.7), "retail": round(95.8 * 37.0)})
        self.assertEqual(traffic["entrances"], [])
        self.assertEqual(traffic["signals_to_study"], 0)

    def test_costs_are_each_quantity_times_its_unit_cost_and_the_allowance_is_a_percent_of_the_subtotal(self):
        feet = self.feet
        self.assertGreater(feet, 0)
        want = {"cost_planning_per_acre": 100 * 12000, "cost_grading_per_acre": round(125 * 40000),
                "cost_street_per_ft": feet * 950, "cost_wet_per_ft": feet * 480, "cost_dry_per_ft": feet * 220,
                "cost_basin_per_acre": round(6 * 160000), "cost_park_per_acre": round(24 * 280000), "cost_signal_each": 0}
        got = {line["id"]: line["amount"] for line in self.plan["costs"]["lines"]}
        self.assertEqual(got, want)
        subtotal = sum(want.values())
        costs = self.plan["costs"]
        self.assertEqual(costs["subtotal"], subtotal)
        self.assertEqual(costs["contingency"], round(subtotal * 15 / 100))
        self.assertEqual(costs["total"], subtotal + round(subtotal * 15 / 100))

    def test_house_land_is_priced_per_lot_apartment_land_per_apartment_and_shop_land_per_acre(self):
        priced = {p["use"]: p for p in self.plan["money"]["priced"]}
        self.assertEqual(set(priced), {"retail", "apartments", "homes"})
        self.assertEqual((priced["homes"]["quantity"], priced["homes"]["quantity_unit"], priced["homes"]["amount"]), (180, "house lots", 180 * 135000))
        self.assertEqual((priced["apartments"]["quantity"], priced["apartments"]["quantity_unit"], priced["apartments"]["amount"]),
                         (400, "apartments", 400 * 50000))
        self.assertEqual((priced["retail"]["quantity"], priced["retail"]["quantity_unit"], priced["retail"]["amount"]), (10.0, "acres", 10 * 870000))

    def test_revenue_minus_costs_minus_land_is_the_profit(self):
        money = self.plan["money"]
        revenue = 180 * 135000 + 400 * 50000 + 10 * 870000
        self.assertEqual(money["revenue"], revenue)
        self.assertEqual(money["sales"], {"retail": 8_700_000, "apartments": 20_000_000, "homes": 24_300_000})
        self.assertEqual(money["costs"], self.plan["costs"]["total"])
        self.assertEqual((money["land"], money["land_is_stand_in"]), (2_500_000, True))
        self.assertEqual(money["profit"], revenue - self.plan["costs"]["total"] - 2_500_000)
        self.assertEqual(money["margin_pct"], round(100 * money["profit"] / revenue, 1))
        self.assertEqual(money["per_acre"], round(money["profit"] / 100))

    def test_the_economy_adds_up_value_taxes_and_jobs(self):
        eco = self.plan["economy"]
        value = 180 * 600000 + 400 * 330000 + 95800 * 350
        self.assertEqual((eco["homes"], eco["residents"]), (580, round(180 * 3.0) + round(400 * 2.3)))
        self.assertEqual((eco["jobs"], eco["floor_space_sq_ft"]), (round(95.8 * 2.0), 95800))
        self.assertEqual(eco["built_value"], value)
        self.assertEqual(eco["property_tax_year"], round(value * 1.0 / 100))
        self.assertEqual(eco["retail_sales_year"], 95800 * 350)
        self.assertEqual(eco["city_sales_tax_year"], round(95800 * 350 * 1.0 / 100))

    def test_an_expensive_ground_reading_multiplies_the_grading(self):
        base = make(make_parcel(100, "EDC-CC"), acres={"homes": 100})
        steep = make(make_parcel(100, "EDC-CC"), {"surface": surface(15.0, 30.0, "steep")}, acres={"homes": 100})
        grading = lambda plan: next(x for x in plan["costs"]["lines"] if x["id"] == "cost_grading_per_acre")["amount"]  # noqa: E731
        self.assertEqual(grading(base), round(100 * 1.25 * 40000))
        self.assertEqual(grading(steep), round(100 * 2.4 * 40000))

    def test_a_signal_is_added_when_an_entrance_onto_a_big_street_is_busy_enough(self):
        parcel = make_parcel(100, "EDC-CC")
        plan = make(parcel, {"streets": street(100, rank=4, cls="Urban Arterial"), "signals": {"signals": []}}, acres={"apartments": 100})
        traffic = plan["traffic"]
        self.assertGreater(traffic["per_day"], 9000)
        self.assertGreaterEqual(traffic["signals_to_study"], 1)
        self.assertEqual(len(traffic["entrances"]), len({(round(e["lat"], 4), round(e["lon"], 4)) for e in traffic["entrances"]}))
        line = next(x for x in plan["costs"]["lines"] if x["id"] == "cost_signal_each")
        self.assertEqual(line["amount"], traffic["signals_to_study"] * 550000)
        self.assertAlmostEqual(sum(e["trips"] for e in traffic["entrances"]), traffic["per_day"], delta=len(traffic["entrances"]))

    def test_with_the_signals_map_silent_a_busy_entrance_says_unknown_and_no_signal_is_counted(self):
        parcel = make_parcel(100, "EDC-CC")
        plan = make(parcel, {"streets": street(100, rank=4, cls="Urban Arterial"), "signals": None}, acres={"apartments": 100})
        traffic = plan["traffic"]
        self.assertTrue(traffic["entrances"])
        self.assertEqual({e["signal"] for e in traffic["entrances"]}, {"unknown"})
        self.assertEqual(traffic["signals_to_study"], 0)
        self.assertTrue(any("signals" in m for m in plan["facts"]["missing"]))
        self.assertEqual(next(x for x in plan["costs"]["lines"] if x["id"] == "cost_signal_each")["amount"], 0)
        known = make(parcel, {"streets": street(100, rank=4, cls="Urban Arterial"), "signals": {"signals": []}}, acres={"apartments": 100})
        self.assertNotIn("signals", " ".join(known["facts"]["missing"]))

    def test_an_entrance_near_an_existing_signal_uses_it_instead_of_a_new_one(self):
        parcel = make_parcel(100, "EDC-CC")
        lon, lat = FRAME.ll(0, -dims(100)[1] / 2)
        signals = {"signals": [{"street": "Main St", "cross_street": "First St", "lat": lat, "lon": lon, "miles_away": 0.0}]}
        plan = make(parcel, {"streets": street(100, rank=4, cls="Urban Arterial"), "signals": signals}, acres={"apartments": 100})
        self.assertEqual(plan["traffic"]["signals_to_study"], 0)
        self.assertEqual({e["signal"] for e in plan["traffic"]["entrances"] if e["street"] == "Main St"}, {"existing"})


# ---------------------------------------------------------------- 11. missing facts

class MissingFacts(Plans):
    def test_with_every_part_none_the_plan_still_comes_back_and_names_what_is_missing(self):
        parts = {name: None for name in ALL_PARTS}
        for mode in ("zoning", "best"):
            with self.subTest(mode=mode):
                plan = make(make_parcel(60, "EDC-CC"), parts, mode=mode)
                self.assertAddsUp(plan)
                words = " ".join(plan["facts"]["missing"]).lower()
                for key in ("zoning around", "highway", "census", "street", "project"):
                    self.assertIn(key, words)
                self.assertTrue(plan["drawing"]["pieces"])
                self.assertTrue(any("did not answer" in a for a in plan["advice"]))
                self.assertIsNone(plan["facts"]["frontage"])
                self.assertIsNone(plan["facts"]["ground"])
                self.assertIsNone(plan["market"]["people"])

    def test_a_part_that_answered_is_not_listed_as_missing(self):
        parts = {name: None for name in ALL_PARTS}
        parts["people"] = census(500, 5000, 9000)
        parts["projects"] = projects()
        plan = make(make_parcel(60, "EDC-CC"), parts)
        words = " ".join(plan["facts"]["missing"]).lower()
        self.assertNotIn("census", words)
        self.assertNotIn("project", words)
        self.assertIn("highway", words)

    def test_a_highway_part_with_no_station_is_empty_not_missing(self):
        plan = make(make_parcel(60, "EDC-CC"), {"state_highway_traffic": {"stations": []}})
        self.assertNotIn("highway traffic counts", plan["facts"]["missing"])
        self.assertIsNone(plan["facts"]["highway"])

    def test_with_nothing_but_the_parcel_every_section_of_the_answer_is_present(self):
        plan = make(make_parcel(60, "EDC-CC"), {})
        for key in ("acres", "mode", "edited", "uses", "notes", "advice", "nothing_to_build", "left_out", "facts", "street_lines", "drawing",
                    "traffic", "costs", "money", "economy", "buyers", "market", "figures", "settings"):
            self.assertIn(key, plan)
        self.assertEqual([u["id"] for u in plan["uses"]], list(P.USE_IDS))

    def test_a_parcel_with_no_acres_gives_a_plan_of_nothing(self):
        parcel = make_parcel(1, "EDC-CC")
        parcel["acres"] = 0
        plan = make(parcel, {})
        self.assertEqual(sum(acres_of(plan).values()), 0.0)
        self.assertEqual(plan["money"]["revenue"], 0)
        self.assertEqual(plan["money"]["per_acre"], None)

    def test_unknown_zoning_is_said_aloud_and_checked_against_nothing(self):
        plan = make(make_parcel(60, ""), {})
        self.assertTrue(any("no zoning is listed" in a.lower() for a in plan["advice"]))
        self.assertEqual({u["fit"] for u in plan["uses"] if u["id"] in P.BUILT}, {"unknown"})

    def test_a_classed_street_is_always_called_a_street(self):
        self.assertEqual(P.a_class("Major"), "a Major street")
        self.assertEqual(P.a_class("Urban Arterial"), "an Urban Arterial street")
        self.assertEqual(P.a_class(""), "a classed street")

    def test_a_specific_plan_name_is_carried_into_the_advice(self):
        plan = make(make_parcel(60, "SP-1"), {"general_plan": {"specific_plan": "Heritage Lake"}})
        self.assertTrue(any("Heritage Lake" in a for a in plan["advice"]))

    def test_a_high_fire_zone_is_mentioned(self):
        plan = make(make_parcel(60, "LDR-2", fire_hazard_zone="Very High"), {})
        self.assertTrue(any("fire" in a.lower() for a in plan["advice"]))


# ---------------------------------------------------------------- 12. who buys

class Buyers(Plans):
    ROWS = (
        project("House tract far", "Residential", 20, 80, miles=1.5, builder="Pardee Homes", description="single family homes", number="1"),
        project("House tract near", "Residential", 20, 80, miles=0.5, builder=None, description="single family homes", number="2"),
        project("House tract mid", "Residential", 20, 80, miles=1.0, builder="Lennar", description="single family homes", number="3"),
        project("Flats", "Residential", 5, 100, miles=0.8, builder="Mega Builders", description="apartment complex", number="4"),
        project("Mixed block", "Mixed Use", 4, None, miles=0.9, builder="Mix Co", description="shops and condos", number="5"),
        project("Shops at Oak", "Commercial", 6, None, 60000, miles=0.3, builder=None, description="retail center", number="6"),
        project("Self storage", "Commercial", 2, None, 40000, miles=0.2, builder="Box Co", description="", number="7"),
        project("Valley Medical Clinic", "Commercial", 3, None, 30000, miles=1.1, builder="Health Group", description="medical office", number="8"),
        project("Distribution", "Industrial", 30, None, 300000, miles=1.7, builder="Shed Inc", description="warehouse", number="9"),
    )

    def entries(self, acres, rows=None):
        F = gathered(make_parcel(100), {"projects": projects(*(rows or self.ROWS))})
        return {e["use"]: e for e in P.buyers(F, {**{u: 0.0 for u in P.USE_IDS}, **acres})}

    def test_a_use_with_no_acres_has_no_entry_and_the_rest_come_in_the_usual_order(self):
        F = gathered(make_parcel(100), {"projects": projects(*self.ROWS)})
        out = P.buyers(F, {**{u: 0.0 for u in P.USE_IDS}, "homes": 5.0, "retail": 5.0, "business": 1.0})
        self.assertEqual([e["use"] for e in out], ["retail", "homes", "business"])
        self.assertEqual(P.buyers(F, {u: 0.0 for u in P.USE_IDS}), [])
        every = P.buyers(F, {u: 5.0 for u in P.USE_IDS})
        self.assertEqual([e["use"] for e in every], list(P.BUILT), "parks never have buyers")

    def test_every_entry_says_who_buys_this_kind_of_land(self):
        for entry in self.entries({u: 5.0 for u in P.BUILT}).values():
            self.assertTrue(entry["who"])

    def test_house_tracts_list_only_residential_projects_that_are_not_apartments(self):
        homes = self.entries({"homes": 5.0})["homes"]
        self.assertEqual({p["title"] for p in homes["projects"]}, {"House tract far", "House tract near", "House tract mid"})

    def test_apartment_land_lists_apartment_projects_and_mixed_use_but_not_house_tracts(self):
        flats = self.entries({"apartments": 5.0})["apartments"]
        self.assertEqual({p["title"] for p in flats["projects"]}, {"Flats", "Mixed block"})

    def test_shop_land_lists_shops_but_not_storage_clinics_or_industrial(self):
        retail = self.entries({"retail": 5.0})["retail"]
        titles = {p["title"] for p in retail["projects"]}
        self.assertEqual(titles, {"Shops at Oak", "Mixed block"}, "a medical clinic is an office, not a shop")
        self.assertNotIn("Self storage", titles)

    def test_office_land_lists_only_projects_that_say_office_medical_or_clinic(self):
        offices = self.entries({"office": 5.0})["office"]
        self.assertEqual({p["title"] for p in offices["projects"]}, {"Valley Medical Clinic"})

    def test_business_park_land_lists_industrial_projects_and_mixed_ones_that_say_so(self):
        business = self.entries({"business": 5.0})["business"]
        self.assertEqual({p["title"] for p in business["projects"]}, {"Distribution"}, "shops and condos are not industrial")
        rows = self.ROWS + (project("Light industrial and retail", "Mixed Use", 8, None, 120000, miles=2.0, description="light manufacturing and retail"),)
        self.assertEqual({p["title"] for p in self.entries({"business": 5.0}, rows)["business"]["projects"]},
                         {"Distribution", "Light industrial and retail"})

    def test_builders_named_by_the_city_come_first_then_the_nearest(self):
        homes = self.entries({"homes": 5.0})["homes"]
        self.assertEqual([p["title"] for p in homes["projects"]], ["House tract mid", "House tract far", "House tract near"])
        self.assertEqual(homes["named"], ["Lennar", "Pardee Homes"])

    def test_a_builder_is_named_once_and_at_most_eight_projects_are_listed(self):
        rows = [project(f"Tract {i}", "Residential", 10, 40, miles=0.1 * i, builder="Same Builder" if i % 2 else f"B{i}", number=str(i)) for i in range(1, 15)]
        homes = self.entries({"homes": 5.0}, rows)["homes"]
        self.assertLessEqual(len(homes["projects"]), 8)
        self.assertLessEqual(len(homes["named"]), 8)
        self.assertEqual(len(homes["named"]), len(set(homes["named"])))
        self.assertEqual(homes["named"].count("Same Builder"), 1)

    def test_a_project_row_keeps_what_the_page_needs_to_show_it(self):
        row = self.entries({"homes": 5.0})["homes"]["projects"][0]
        self.assertEqual(set(row), {"title", "builder", "status", "miles_away", "description", "number", "list", "lat", "lon"})

    def test_buyers_come_through_the_whole_plan_for_the_uses_in_it(self):
        plan = make(make_parcel(100, "LDR-2"), {"projects": projects(*self.ROWS)}, mode="zoning")
        used = [u for u in P.BUILT if acres_of(plan)[u] > 0]
        self.assertEqual([e["use"] for e in plan["buyers"]], used)

    def test_with_no_project_list_there_are_still_generic_buyers(self):
        plan = make(make_parcel(100, "LDR-2"), {})
        self.assertTrue(plan["buyers"])
        for entry in plan["buyers"]:
            self.assertEqual((entry["projects"], entry["named"]), ([], []))
            self.assertTrue(entry["who"])



# ---------------------------------------------------------------- 13. the zone's smallest lot caps the houses

NAMES = {"RR1": "Rural Residential, 1-acre minimum", "RR1/2": "Rural Residential, 1/2-acre minimum",
         "RR2": "Rural Residential, 2-acre minimum", "RR5": "Rural Residential, 5-acre minimum", "RM": "Rural Mountainous",
         "LDR-2": "Low Density Residential-2"}


def zoned(acres, code, names=NAMES):
    """A parcel with the city's wording for each of its zones, the way the app words it (" + " between zones)."""
    zones = [c.strip() for c in code.split("&")]
    return make_parcel(acres, code, zoning_name=" + ".join(names.get(z, z) for z in zones))


class ZoneLotSize(Plans):
    def figure(self, parcel, parts=None):
        return next(f for f in make(parcel, parts)["figures"] if f["id"] == "homes_per_acre")

    def test_two_zones_use_the_larger_lot_and_say_so(self):
        # the live example: 372090016, zoned "RR2 & RR5", got 3.1 homes an acre from tracts nearby
        tracts = projects(*[project(f"Tract {i}", "Residential", 20, 62, number=str(i)) for i in range(3)])
        fig = self.figure(zoned(140, "RR2 & RR5"), {"projects": tracts})
        self.assertEqual((fig["kind"], fig["value"], fig["start"]), ("measured", 0.17, 0.17), "0.85 / 5 acres")
        self.assertEqual(fig["lot_acres"], 5.0)
        self.assertIn("The zones on this parcel ask for lots of at least 2 acres (RR2) and 5 acres (RR5)", fig["basis"])
        self.assertIn("The larger lot, 5 acres, is used", fig["basis"])
        self.assertIn("so at most 0.2 homes an acre", fig["basis"])

    def test_the_plan_gives_the_houses_that_lot_size_not_the_nearby_tracts(self):
        tracts = projects(*[project(f"Tract {i}", "Residential", 20, 62, number=str(i)) for i in range(3)])
        plan = make(zoned(140, "RR2 & RR5"), {"projects": tracts})
        homes = use_of(plan, "homes")
        self.assertEqual(homes["homes"], round(homes["acres"] * 0.17))
        self.assertLess(homes["homes"], homes["acres"] * 0.5)
        self.assertEqual(plan["facts"]["smallest_lot"],
                         {"acres": 5.0, "zones": [{"code": "RR2", "acres": 2.0}, {"code": "RR5", "acres": 5.0}], "unread": []})

    def test_one_zone_says_the_sentence_with_its_own_size(self):
        fig = self.figure(zoned(40, "RR2"))
        self.assertEqual(fig["value"], 0.42)
        self.assertIn("The zone (RR2) asks for lots of at least 2 acres, so at most 0.5 homes an acre.", fig["basis"])
        one = self.figure(zoned(40, "RR1"))
        self.assertEqual(one["value"], 0.85)
        self.assertIn("at least 1 acre, so at most 1 home an acre", one["basis"])

    def test_a_half_acre_zone_reads_as_a_fraction(self):
        fig = self.figure(zoned(40, "RR1/2"))
        self.assertEqual(fig["value"], 1.7)
        self.assertIn("at least 0.5 acres, so at most 2 homes an acre", fig["basis"])

    def test_the_code_carries_the_size_when_the_names_did_not_load(self):
        fig = self.figure(make_parcel(40, "RR5 & RR2"))      # zoning_name empty: the city's names did not answer
        self.assertEqual((fig["kind"], fig["value"]), ("measured", 0.17))

    def test_a_zone_whose_size_cannot_be_read_is_left_as_it_is(self):
        for code in ("LDR-2", "RM"):
            fig = self.figure(zoned(40, code))
            self.assertEqual((fig["kind"], fig["value"]), ("assumption", 4.5), code)
            self.assertIsNone(make(zoned(40, code))["facts"]["smallest_lot"])

    def test_the_cities_own_wording_for_the_zone_at_the_middle_gives_a_size_the_code_does_not(self):
        parts = {"zoning": {"abbrev": "RM", "what_it_allows": "Rural Mountainous", "general_plan_says": "Rural Mountainous 10 ac min (RM)"}}
        fig = self.figure(zoned(40, "RM"), parts)
        self.assertEqual((fig["kind"], fig["value"]), ("measured", 0.08), "0.85 / 10 acres")
        self.assertIn("at least 10 acres", fig["basis"])

    def test_a_zone_with_no_lot_size_beside_one_with_a_size_is_named_as_not_counted(self):
        fig = self.figure(zoned(40, "LDR-2 & RR2"))
        self.assertEqual(fig["value"], 0.42)
        self.assertIn("gives no lot size for LDR-2, so that zone is not counted", fig["basis"])

    def test_the_owner_can_still_change_the_figure(self):
        plan = make(zoned(140, "RR2 & RR5"), None, assumptions={"homes_per_acre": 1.0})
        fig = next(f for f in plan["figures"] if f["id"] == "homes_per_acre")
        self.assertEqual((fig["kind"], fig["value"], fig["start"]), ("yours", 1.0, 0.17))

    def test_a_cap_never_raises_a_figure_that_is_already_lower(self):
        tracts = projects(project("A", "Residential", 20, 4, number="1"), project("B", "Residential", 20, 6, number="2"))
        fig = self.figure(zoned(40, "RR1/2"), {"projects": tracts})
        self.assertEqual((fig["kind"], fig["value"]), ("measured", 0.2), "the nearby tracts (median 0.25, shown to one place) are lower than the zone's ceiling of 1.7")


# ---------------------------------------------------------------- 14. buyers are the right kind and size

def listed(title, kind, description="", acres=None, homes=None, feet=None, builder=None, number="1"):
    return project(title, kind, acres, homes, feet, miles=0.5, builder=builder, description=description, number=number)


class RightBuyers(Plans):
    def uses_of(self, **kw):
        return P.project_uses(listed(**kw))

    def test_a_small_car_wash_is_not_a_buyer_of_apartment_or_office_land(self):
        # recorded: "Washbank Express Carwash", Mixed Use, 1.65 acres, "a 2 story carwash and office development"
        got = self.uses_of(title="Washbank Express Carwash", kind="Mixed Use", acres=1.65,
                           description="A proposed 2 story carwash and office development on a 1.65 acre site.")
        self.assertEqual(got, {"retail"})

    def test_a_parcel_map_and_a_plan_amendment_are_buyers_of_nothing(self):
        self.assertEqual(self.uses_of(title="Menifee Village PM", kind="Mixed Use", acres=27.73,
                                      description="27.73 acres into 10 commericial parcels ranging in size from 1.09 acres - 12.24acres"), set())
        self.assertEqual(self.uses_of(title="Menifee Village SPA", kind="Mixed Use", acres=95.61,
                                      description="Amend SP158 PA 3-1, 3-2, 4-3 and 4-4 increase residential planning areas"), set())

    def test_a_big_store_that_is_split_into_parcels_still_counts_as_shops(self):
        self.assertEqual(self.uses_of(title="Walmart", kind="Commercial", acres=30.3, feet=263160,
                                      description="30.3 acres into 7 parcels: 240,980 sq ft major retail building"), {"retail"})

    def test_each_kind_of_project_is_evidence_for_its_own_use_only(self):
        self.assertEqual(self.uses_of(title="Tract", kind="Residential", description="94 acres - 296 residential lots", acres=94.3, homes=296), {"homes"})
        self.assertEqual(self.uses_of(title="Del Oro", kind="Residential", description="238 apartment units", acres=17.2, homes=238), {"apartments"})
        self.assertEqual(self.uses_of(title="Condos", kind="Residential", description="327 condominium units", acres=30.5, homes=327), {"apartments"})
        self.assertEqual(self.uses_of(title="Medical Office Building", kind="Commercial", description="2.47 acres, 33,800 sf medical office building",
                                      acres=2.47, feet=33800), {"office"})
        self.assertEqual(self.uses_of(title="Freedom Business Park", kind="Industrial", description="light industrial and warehousing",
                                      acres=17.55, feet=283000), {"business"})
        self.assertEqual(self.uses_of(title="Costco", kind="Commercial"), {"retail"})

    def test_hotels_storage_schools_and_tiny_projects_are_nobodys_buyers(self):
        self.assertEqual(self.uses_of(title="Home2Suites", kind="Commercial", description="4-story, 65,463 square foot hotel", feet=65463), set())
        self.assertEqual(self.uses_of(title="Menifee Self Storage", kind="Commercial",
                                      description="expansion of a self storage facility by 45,075 sq. ft.", feet=45075), set())
        self.assertEqual(self.uses_of(title="Montesori School", kind="Commercial", description="1.6 acres - 13,648 sf childcare center",
                                      acres=1.6, feet=13648), set())
        self.assertEqual(self.uses_of(title="Day Spa", kind="Commercial", description="Expansion of an existing 492 square foot barbershop", acres=0.65), set())
        self.assertEqual(self.uses_of(title="Boulder View Estates", kind="Residential", description="15 lot tract"), set(),
                         "15 lots is too few to buy a block")
        self.assertEqual(self.uses_of(title="Small flats", kind="Residential", description="12 apartment units", homes=12), set())

    def test_a_house_tract_is_not_apartments_and_flats_are_not_house_tracts(self):
        tract = listed("Tract", "Residential", "80 residential lots", acres=30, homes=80)
        flats = listed("Flats", "Residential", "300 residential units", acres=10, homes=300)       # 30 an acre
        self.assertEqual(P.project_uses(tract), {"homes"})
        self.assertEqual(P.project_uses(flats), {"apartments"})

    def test_a_mixed_use_project_counts_only_for_the_uses_its_own_words_state(self):
        self.assertEqual(self.uses_of(title="Office park", kind="Mixed Use", acres=8, description="8 acres office and shops"), {"retail"})

    def test_the_recorded_example_lists_no_amendment_parcel_map_or_car_wash_under_the_wrong_use(self):
        import support
        from landplanner.cities.menifee import Menifee
        with support.offline():
            city = Menifee()
            parcel = city.parcel(support.EXAMPLE)
            projs = city.site_part("projects", parcel)["projects"]
        rows = {u: [p["title"] for p in projs if u in P.project_uses(p)] for u in P.BUILT}
        everything = {t for titles in rows.values() for t in titles}
        for title in ("Menifee Village PM", "Menifee Village SPA"):
            self.assertNotIn(title, everything)
        self.assertEqual([u for u, titles in rows.items() if "Washbank Express Carwash" in titles], ["retail"])
        self.assertNotIn("Montesori School", everything)
        self.assertTrue(all(rows[u] for u in P.BUILT), "the example's lists have real buyers of every kind")

    def test_a_use_with_no_matching_project_says_so_in_words(self):
        rows = (listed("Hotel", "Commercial", "a hotel", feet=60000),)
        F = gathered(make_parcel(100), {"projects": projects(*rows)})
        entry = P.buyers(F, {**{u: 0.0 for u in P.USE_IDS}, "apartments": 5.0})[0]
        self.assertEqual((entry["projects"], entry["named"]), ([], []))
        self.assertIn("No project on the city's lists", entry["note"])
        none_listed = P.buyers(gathered(make_parcel(100), {}), {**{u: 0.0 for u in P.USE_IDS}, "apartments": 5.0})[0]
        self.assertIsNone(none_listed["note"], "no list at all is a missing source, not a finding")


# ---------------------------------------------------------------- 15. the entrance sentence says it once

class EntranceWords(Plans):
    def test_an_entrance_that_may_need_a_signal_does_not_repeat_the_pages_own_words(self):
        parts = {"streets": street(100, rank=4), "signals": {"signals": []}, "state_highway_traffic": highway(0.5, 126000),
                 "people": census(5000, 40000, 90000), "surroundings": around(("LDR-2", "low-density", 300.0))}
        plan = make(make_parcel(100, "EDC-CC"), parts)
        entrances = plan["traffic"]["entrances"]
        self.assertTrue(entrances)
        for e in entrances:
            self.assertNotIn("signal is worth studying", e["text"].lower())
            self.assertEqual(len(e["text"].split(". ")), 1, "one sentence")
        study = [e for e in entrances if e["signal"] == "study"]
        self.assertTrue(study, "this much traffic on a major street is a signal worth studying")
        self.assertIn("trips a day would use this entrance", study[0]["text"])


if __name__ == "__main__":
    unittest.main()
