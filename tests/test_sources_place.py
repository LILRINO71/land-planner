"""Offline tests for landplanner/sources/place.py (weather, hazards, what is close by, the typical resident).

The network function landplanner.sources.fetch.get_json is replaced by a replay of trimmed real answers kept in
tests/fixtures/sources/place_answers.json (recorded at the test point on 2026-11-25). A question that was never
recorded fails the test instead of going out to the internet.

Re-record (needs the internet; takes about 20 seconds):  python -m tests.test_sources_place --record
"""
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from landplanner.cities import SourceError  # noqa: E402
from landplanner.sources import fetch, place  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sources" / "place_answers.json"
LON, LAT = -117.17793, 33.65238                       # a 74-acre site on Haun Rd, north of Scott Rd
BOX = (-117.1829, 33.6490, -117.1729, 33.6558)        # west, south, east, north of the site's outline
TRACTS = [{"id": "06065042743", "households": 1500, "share": 0.5},
          {"id": "06065042742", "households": 1200, "share": 0.3},
          {"id": "06065042739", "households": 1800, "share": 0.2}]
FIRST, LAST = 1985, 2025
MENIFEE_HOST = place.MENIFEE_LAYERS["host"]


def _key(url, params):
    """What identifies a question. A census question lists tracts; one recorded answer covers every list (the replay
    hands back only the tracts asked for), so the list is left out of the key."""
    where = (params or {}).get("where") or ""
    if where.startswith("GEOID IN"):
        params = {"census_fields": params["outFields"]}
    return hashlib.sha1((url + "?" + json.dumps(params or {}, sort_keys=True, default=str)).encode()).hexdigest()[:20]


class Replay:
    """Stands in for fetch.get_json. `down` is a list of words: a question whose address contains one of them fails
    the way a silent service does. `rewrite` maps an address start to the recorded one (for another city's host)."""

    def __init__(self, down=(), rewrite=None):
        self.down, self.rewrite, self.asked = list(down), dict(rewrite or {}), []
        self.answers = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def __call__(self, url, params=None, timeout=30, tries=2, post=False):
        self.asked.append(url)
        if any(word in url for word in self.down):
            raise SourceError(f"{url}: (test) the service is down")
        for new, old in self.rewrite.items():
            url = url.replace(new, old)
        found = self.answers.get(_key(url, params))
        if found is None:
            raise AssertionError(f"not recorded, and the tests must not use the network: {url} {params}")
        found = json.loads(json.dumps(found))
        where = (params or {}).get("where") or ""
        if where.startswith("GEOID IN"):
            wanted = set(re.findall(r"'(\d+)'", where))
            found["features"] = [f for f in found["features"] if f["attributes"].get("GEOID") in wanted]
        return found


def offline(down=(), rewrite=None):
    replay = Replay(down, rewrite)
    return mock.patch.object(fetch, "get_json", replay), replay


class Base(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(place, "_PAUSE", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_with(self, fn, *args, down=(), rewrite=None, **kw):
        patcher, replay = offline(down, rewrite)
        with patcher:
            out = fn(*args, **kw)
        self.replay = replay
        return out

    def assertJson(self, value):
        self.assertEqual(json.loads(json.dumps(value)), value)


# ---- weather ----------------------------------------------------------------------------------------------------
class TrendMaths(unittest.TestCase):
    def test_straight_line_through_made_up_years(self):
        rows = [{"year": y, "mean_f": 60 + 0.5 * (y - 2000), "rain_in": 12 - 0.2 * (y - 2000)} for y in range(1990, 2021)]
        t = place._trend(rows)
        self.assertEqual(t, {"mean_f_per_decade": 5.0, "rain_in_per_decade": -2.0, "from_year": 1990, "to_year": 2020})

    def test_noise_around_a_line_is_averaged_out(self):
        wiggle = [0.4, -0.4, 0.3, -0.3, 0.0, 0.2, -0.2, 0.1, -0.1, 0.0]
        rows = [{"year": 2000 + i, "mean_f": 60 + 0.1 * i + wiggle[i], "rain_in": 10.0} for i in range(10)]
        t = place._trend(rows)
        self.assertAlmostEqual(t["mean_f_per_decade"], 1.0, delta=0.15)
        self.assertEqual(t["rain_in_per_decade"], 0.0)

    def test_flat_years_and_too_few_years(self):
        flat = [{"year": y, "mean_f": 61.0, "rain_in": 12.0} for y in range(2000, 2005)]
        self.assertEqual(place._trend(flat)["mean_f_per_decade"], 0.0)
        one = place._trend([{"year": 2000, "mean_f": 61.0, "rain_in": 12.0}])
        self.assertIsNone(one["mean_f_per_decade"])
        self.assertEqual(place._trend([]), {"mean_f_per_decade": None, "rain_in_per_decade": None,
                                            "from_year": None, "to_year": None})

    def test_ten_year_groups_and_leftovers(self):
        self.assertEqual(place._decades(None, 1985, 2025), [[1985, 1994], [1995, 2004], [2005, 2014], [2015, 2025]])
        self.assertEqual(place._decades(None, 1985, 2022), [[1985, 1994], [1995, 2004], [2005, 2014], [2015, 2022]])
        self.assertEqual(place._decades(None, 1985, 2017), [[1985, 1994], [1995, 2004], [2005, 2017]])
        self.assertEqual(place._decades(None, 1985, 1990), [[1985, 1990]])


class Climate(Base):
    def test_happy_path(self):
        c = self.run_with(place.climate, LON, LAT, FIRST, LAST)
        self.assertEqual(c["typical_year"], {"mean_f": 61.4, "rain_in": 11.8, "wind_mph": 5.5, "sun_kwh_m2_day": 5.42})
        self.assertEqual([m["month"] for m in c["months"]], list(place.MONTHS))
        aug, jan = c["months"][7], c["months"][0]
        self.assertGreater(aug["mean_f"], jan["mean_f"] + 20)
        self.assertGreater(aug["high_f"], aug["mean_f"])
        self.assertLess(aug["low_f"], aug["mean_f"])
        self.assertGreater(jan["rain_in"], 1.5)
        self.assertLess(aug["rain_in"], 0.6)
        self.assertEqual([d["years"] for d in c["by_decade"]], ["1985-1994", "1995-2004", "2005-2014", "2015-2025"])
        self.assertEqual(c["by_decade"][0]["mean_f"], 59.9)             # 15.52 C
        self.assertLess(c["by_decade"][0]["mean_f"], c["by_decade"][-1]["mean_f"])
        self.assertEqual(len(c["by_year"]), 41)
        self.assertEqual((c["by_year"][0]["year"], c["by_year"][-1]["year"]), (1985, 2025))
        self.assertEqual((c["trend"]["from_year"], c["trend"]["to_year"]), (1985, 2025))
        self.assertGreater(c["trend"]["mean_f_per_decade"], 0.3)        # it has been warming
        self.assertLess(c["trend"]["rain_in_per_decade"], 0)
        self.assertIn("coarse", c["note"])
        self.assertIn("grid", c["note"])
        self.assertIn("NASA POWER", c["source"])
        self.assertEqual(c["did_not_answer"], [])
        self.assertJson(c)
        self.assertEqual(len(self.replay.asked), 2)                     # two light requests, no daily data

    def test_trend_matches_the_yearly_values(self):
        c = self.run_with(place.climate, LON, LAT, FIRST, LAST)
        again = place._trend(c["by_year"])
        self.assertEqual(c["trend"], again)

    def test_normals_down_the_history_still_comes(self):
        c = self.run_with(place.climate, LON, LAT, FIRST, LAST, down=["climatology"])
        self.assertEqual(len(c["by_year"]), 41)
        self.assertIsNone(c["typical_year"]["wind_mph"])
        self.assertIsNone(c["typical_year"]["sun_kwh_m2_day"])
        self.assertAlmostEqual(c["typical_year"]["mean_f"], 61.4, delta=0.6)
        self.assertEqual(c["did_not_answer"], ["Typical year (NASA POWER normals)"])

    def test_history_down_the_normals_still_come(self):
        c = self.run_with(place.climate, LON, LAT, FIRST, LAST, down=["monthly"])
        self.assertEqual(c["typical_year"]["mean_f"], 61.4)
        self.assertEqual((c["months"], c["by_decade"], c["by_year"]), ([], [], []))
        self.assertIsNone(c["trend"]["mean_f_per_decade"])
        self.assertEqual(c["did_not_answer"], ["Yearly weather history (NASA POWER)"])
        self.assertJson(c)

    def test_everything_down(self):
        with self.assertRaises(SourceError):
            self.run_with(place.climate, LON, LAT, FIRST, LAST, down=["power.larc.nasa.gov"])


# ---- hazards ----------------------------------------------------------------------------------------------------
class Hazards(Base):
    def test_happy_path_with_the_site_outline(self):
        h = self.run_with(place.hazards, LON, LAT, BOX)
        self.assertEqual(h["did_not_answer"], [])
        f = h["flood"]
        self.assertEqual((f["zone"], f["special_hazard_area"], f["panel"], f["effective"]), ("X", False, "06065C2070H", "2014-08-18"))
        self.assertIn("Minimal", f["meaning"])
        self.assertEqual(f["zones_on_site"], ["X (minimal hazard)"])
        self.assertEqual(h["fire"]["level"], "High")
        self.assertEqual(h["fire"]["map_year"], 2025)
        self.assertTrue({"Moderate", "High", "Very High"} <= set(h["fire"]["levels_on_site"]))
        self.assertIn("city", h["fire"]["responsibility"].lower())
        self.assertIs(h["faults"]["in_fault_zone"], False)
        self.assertIsNone(h["faults"]["nearest_miles"])
        self.assertEqual(h["faults"]["searched_miles"], place.FAULT_SEARCH_MILES)
        self.assertEqual(h["ground"]["liquefaction"], "not mapped by the state here")
        self.assertEqual(h["ground"]["landslide"], "not mapped by the state here")
        self.assertEqual([w["type"] for w in h["wetlands"]["on_site"]], ["Riverine"])
        self.assertEqual(h["wetlands"]["on_site"][0]["acres"], 4.31)
        self.assertEqual(h["wetlands"]["searched_miles"], 0.5)
        self.assertTrue(h["habitat"]["in_plan"])
        self.assertEqual(h["habitat"]["area_plan"], "Sun City / Menifee")
        self.assertFalse(h["habitat"]["in_criteria_cell"])
        self.assertTrue({"5163", "5253"} <= set(h["habitat"]["cells_near"]))
        self.assertEqual(h["habitat"]["survey_areas"], ["Burrowing Owl"])
        self.assertIs(h["dam_flooding"], False)
        self.assertEqual(h["evacuation_zone"], "MN-407")
        self.assertEqual(h["fossils"], "Low")
        s = h["fire_service"]
        self.assertTrue(s["in_coverage_gap"])
        self.assertEqual(s["nearest_station"]["name"], "Menifee Fire Station #68")
        self.assertAlmostEqual(s["nearest_station"]["miles_away"], 1.59, places=2)
        self.assertIn("Garbani", s["planned_station"]["name"])
        for block in ("flood", "fire", "faults", "ground", "wetlands", "habitat", "fire_service"):
            self.assertTrue(h[block]["source"], block)                  # every block says where it came from
        self.assertJson(h)

    def test_happy_path_at_the_point_only(self):
        h = self.run_with(place.hazards, LON, LAT)
        self.assertEqual(h["did_not_answer"], [])
        self.assertEqual(h["flood"]["zones_on_site"], ["X (minimal hazard)"])
        self.assertEqual(h["fire"]["levels_on_site"], ["High"])
        self.assertEqual(h["wetlands"]["on_site"], [])
        self.assertEqual(h["wetlands"]["nearest"]["type"], "Riverine")
        self.assertEqual(h["wetlands"]["nearest"]["acres"], 4.31)
        self.assertLess(h["wetlands"]["nearest"]["miles_away"], 0.28)     # within 457 m
        self.assertGreater(h["wetlands"]["nearest"]["miles_away"], 0)
        self.assertJson(h)

    def test_a_second_wetland_is_not_counted_as_the_one_on_site(self):
        h = self.run_with(place.hazards, LON, LAT, BOX)
        self.assertEqual(h["wetlands"]["nearest"]["acres"], 1.53)

    def test_one_block_down_the_rest_still_answer(self):
        cases = {
            "NFHL": ("flood", "Flood zones (FEMA)"),
            "FAM_QFaults": ("faults", "Earthquake faults (California Geological Survey)"),
            "Liquefaction/MapServer": ("ground", "Liquefaction and landslide zones (California Geological Survey)"),
            "wetlandsmapservice": ("wetlands", "Wetlands (U.S. Fish and Wildlife Service)"),
            "conserveriverside": ("habitat", "Western Riverside County habitat plan (Conservation Authority)"),
            "Dam_Inundation": ("dam_flooding", "Dam flooding area (city map)"),
            "Evacuation_Zones_2025": ("evacuation_zone", "Evacuation zone (city map)"),
            "Paleontological": ("fossils", "Fossil sensitivity (city map)"),
            "Fire_Hazard_Severity": ("fire", "Fire hazard zones (city map)"),
            "Existing_Fire_Coverage_Gaps": ("fire_service", "Fire service coverage (city map)"),
        }
        for word, (block, label) in cases.items():
            with self.subTest(down=word):
                h = self.run_with(place.hazards, LON, LAT, BOX, down=[word])
                self.assertIsNone(h[block])
                self.assertEqual(h["did_not_answer"], [label])
                others = [k for k in h if k not in (block, "did_not_answer")]
                self.assertEqual(len(others), 9)
                self.assertTrue(all(h[k] is not None for k in others if k != "dam_flooding"))
                self.assertIs(h["dam_flooding"] if block != "dam_flooding" else False, False)
                self.assertJson(h)

    def test_a_missing_extra_keeps_the_block(self):
        h = self.run_with(place.hazards, LON, LAT, BOX, down=["NFHL/MapServer/3"])
        self.assertEqual(h["flood"]["zone"], "X")
        self.assertIsNone(h["flood"]["panel"])
        self.assertIsNone(h["flood"]["effective"])
        self.assertEqual(h["did_not_answer"], ["Flood map panel number and date (FEMA)"])

    def test_everything_down(self):
        with self.assertRaises(SourceError):
            self.run_with(place.hazards, LON, LAT, BOX, down=["http"])

    def test_another_city_can_be_asked(self):
        other = {**place.MENIFEE_LAYERS, "name": "Test City GIS", "host": "https://example.test/arcgis/rest/services"}
        h = self.run_with(place.hazards, LON, LAT, BOX, city_layers=other, rewrite={"https://example.test/arcgis/rest/services": MENIFEE_HOST})
        self.assertTrue(any(u.startswith("https://example.test/") for u in self.replay.asked))
        self.assertFalse(any(u.startswith(MENIFEE_HOST) for u in self.replay.asked))
        self.assertIn("Test City GIS", h["fire"]["source"])
        self.assertEqual(h["fire"]["level"], "High")

    def test_flood_words(self):
        self.assertIn("Minimal", place._flood_meaning("X", "AREA OF MINIMAL FLOOD HAZARD"))
        self.assertIn("1-in-500", place._flood_meaning("X", "0.2 PCT ANNUAL CHANCE FLOOD HAZARD"))
        self.assertIn("insurance", place._flood_meaning("AE", "FLOODWAY"))
        self.assertIn("floodway", place._flood_meaning("AE", "FLOODWAY"))
        self.assertIn("not determined", place._flood_meaning("D", None))

    def test_no_dashes_in_the_words_people_read(self):
        h = self.run_with(place.hazards, LON, LAT, BOX)
        text = json.dumps(h, ensure_ascii=False)
        self.assertNotIn(chr(0x2014), text)
        self.assertNotIn(chr(0x2013), text)


class FossilWords(unittest.TestCase):
    """The city's fossil layer holds the codes Ha, Hb, L and U (and "sea"); none is shown bare."""

    def test_each_code_the_layer_holds_is_put_in_words(self):
        self.assertEqual([place.paleo_words(c) for c in ("L", "U", "Ha", "Hb")],
                         ["Low", "Undetermined", "High (class A)", "High (class B)"])
        self.assertEqual(place.paleo_words("hb"), "High (class B)", "the case the city wrote it in does not matter")
        self.assertEqual(place.paleo_words(" HA "), "High (class A)")

    def test_a_code_nobody_explained_is_said_to_be_unexplained_with_its_code(self):
        self.assertEqual(place.paleo_words("sea"), "not rated in words by the city (code sea)")
        self.assertEqual(place.paleo_words("Zx"), "not rated in words by the city (code Zx)")

    def test_words_already_in_words_are_kept_and_nothing_is_nothing(self):
        for words in ("Low", "High", "Moderate", "None", "Undetermined", "High (class A)"):
            self.assertEqual(place.paleo_words(words), words)
        self.assertEqual(place.paleo_words("low"), "Low")
        self.assertIsNone(place.paleo_words(None))
        self.assertIsNone(place.paleo_words(" "))

    def test_the_fossil_reader_returns_words_for_every_code(self):
        for code, words in (("Hb", "High (class B)"), ("sea", "not rated in words by the city (code sea)")):
            with mock.patch.object(place, "_at_point", return_value=[{"attributes": {"Paleo": code}}]):
                self.assertEqual(place._fossils(place.MENIFEE_LAYERS, -117.17, 33.65), words)


class Geometry(unittest.TestCase):
    def test_distances(self):
        lon, lat = -117.0, 33.0
        east = lon + 1 / (place.MILES_PER_DEGREE * 0.8387)               # about one mile east
        self.assertAlmostEqual(place.geometry_miles({"x": east, "y": lat}, lon, lat), 1.0, delta=0.02)
        line = {"paths": [[[east, lat - 0.1], [east, lat + 0.1]]]}
        self.assertAlmostEqual(place.geometry_miles(line, lon, lat), 1.0, delta=0.02)
        square = {"rings": [[[lon - 0.01, lat - 0.01], [lon + 0.01, lat - 0.01], [lon + 0.01, lat + 0.01],
                             [lon - 0.01, lat + 0.01], [lon - 0.01, lat - 0.01]]]}
        self.assertEqual(place.geometry_miles(square, lon, lat), 0.0)
        far = {"rings": [[[east, lat - 0.01], [east + 0.01, lat - 0.01], [east + 0.01, lat + 0.01], [east, lat + 0.01], [east, lat - 0.01]]]}
        self.assertAlmostEqual(place.geometry_miles(far, lon, lat), 1.0, delta=0.02)
        self.assertIsNone(place.geometry_miles(None, lon, lat))
        self.assertEqual(place.geometry_centre({"x": 1, "y": 2}), (1, 2))


# ---- close by ---------------------------------------------------------------------------------------------------
class Nearby(Base):
    def test_happy_path(self):
        n = self.run_with(place.nearby, LON, LAT, 5.0)
        self.assertEqual(n["did_not_answer"], [])
        self.assertEqual(n["not_covered"], ["Grocery and big stores (no public list)"])
        distances = [p["miles_away"] for p in n["places"]]
        self.assertEqual(distances, sorted(distances))
        self.assertTrue(all(d <= 5.0 for d in distances))
        for kind in ("park", "fire station", "police", "library", "college", "hospital", "transit stop"):
            self.assertIn(kind, n["nearest"], kind)
            self.assertLessEqual(len([p for p in n["places"] if p["kind"] == kind]), 5)
        park, fire, hosp = n["nearest"]["park"], n["nearest"]["fire station"], n["nearest"]["hospital"]
        self.assertEqual((park["name"], park["miles_away"]), ("Mosaic Park", 0.85))
        self.assertEqual((fire["name"], fire["miles_away"]), ("Menifee Fire Station #68", 1.59))
        self.assertEqual((hosp["name"], hosp["miles_away"]), ("Loma Linda University Medical Center Murrieta", 2.65))
        self.assertIn("106 beds", hosp["detail"])
        self.assertEqual(n["nearest"]["college"]["name"], "Mt. San Jacinto College")
        self.assertEqual(n["nearest"]["library"]["name"], "Menifee Library")
        self.assertEqual(n["nearest"]["police"]["name"], "Menifee Police Department")
        for p in n["places"]:
            self.assertEqual(set(p), {"kind", "name", "miles_away", "lat", "lon", "detail", "source"})
            self.assertTrue(p["name"] and p["source"])
            self.assertTrue(33.5 < p["lat"] < 33.8 and -117.4 < p["lon"] < -117.0)
        self.assertEqual([p["name"] for p in n["places"] if p["kind"] == "hospital"],
                         ["Loma Linda University Medical Center Murrieta", "Menifee Global Medical Center"])
        self.assertJson(n)

    def test_each_station_is_listed_once(self):
        n = self.run_with(place.nearby, LON, LAT, 5.0)
        names = [p["name"] for p in n["places"] if p["kind"] == "fire station"]
        self.assertEqual(len(names), len(set(names)))
        self.assertNotIn("Proposed", " ".join(names))                    # a station that is only planned is not "near"

    def test_a_smaller_circle_keeps_fewer_places(self):
        n = self.run_with(place.nearby, LON, LAT, 1.0)
        self.assertTrue(all(p["miles_away"] <= 1.0 for p in n["places"]))
        self.assertEqual({p["kind"] for p in n["places"]}, {"park"})

    def test_one_service_down_the_rest_still_answer(self):
        cases = {
            "Menifee_Parks": ("park", "Parks (city map)"),
            "Fire_Stations_Existing": ("fire station", "Fire stations (city map)"),
            "Public_Facilities_Point_Layer": ("police", "Police stations and libraries (city map)"),   # also takes the libraries
            "Public_Facilities__Points_": ("college", "Colleges (city map)"),
            "RTA_Routes_and_Stops": ("transit stop", "Bus stops (Riverside Transit)"),
        }
        for word, (kind, label) in cases.items():
            with self.subTest(down=word):
                n = self.run_with(place.nearby, LON, LAT, 5.0, down=[word])
                self.assertEqual(n["did_not_answer"], [label])
                gone = {"police", "library"} if kind == "police" else {kind}
                self.assertFalse(gone & set(n["nearest"]))
                self.assertEqual(len(n["nearest"]), 7 - len(gone))              # every other kind still comes
                self.assertIn("hospital", n["nearest"])
                self.assertJson(n)

    def test_hospital_lists_down_one_at_a_time(self):
        n = self.run_with(place.nearby, LON, LAT, 5.0, down=["structures"])
        names = [p["name"] for p in n["places"] if p["kind"] == "hospital"]
        self.assertEqual(names, ["Loma Linda University Medical Center-Murrieta", "Menifee Valley Medical Center"])
        self.assertEqual(n["did_not_answer"], ["Hospitals (U.S. Geological Survey)"])
        n = self.run_with(place.nearby, LON, LAT, 5.0, down=["Hospitals_hifld"])
        self.assertEqual([p["name"] for p in n["places"] if p["kind"] == "hospital"],
                         ["Loma Linda University Medical Center Murrieta", "Menifee Global Medical Center"])
        self.assertNotIn("beds", n["nearest"]["hospital"]["detail"])
        self.assertEqual(n["did_not_answer"], ["Hospital beds (federal hospital list)"])

    def test_everything_down(self):
        with self.assertRaises(SourceError):
            self.run_with(place.nearby, LON, LAT, 5.0, down=["http"])

    def test_at_most_five_of_a_kind_nearest_first(self):
        stops = [place._place("transit stop", f"Stop {i}", 0.1 * i, {"x": -117.1, "y": 33.6}, None, "t") for i in range(1, 9)]
        with mock.patch.object(place, "_near_stops", return_value=stops):
            n = self.run_with(place.nearby, LON, LAT, 5.0)
        got = [p["name"] for p in n["places"] if p["kind"] == "transit stop"]
        self.assertEqual(got, ["Stop 1", "Stop 2", "Stop 3", "Stop 4", "Stop 5"])

    def test_beds_join_the_same_building(self):
        listed = [place._place("hospital", "General", 1.0, {"x": -117.100, "y": 33.600}, "1 Main St", "usgs")]
        beds = [(-117.1002, 33.6001, "General Hospital", 90), (-117.5, 33.9, "Faraway", 40)]
        out = place._merge_hospitals(listed, beds, -117.1, 33.5)
        self.assertEqual(out[0]["name"], "General")
        self.assertIn("90 beds", out[0]["detail"])
        self.assertEqual(out[1]["name"], "Faraway")
        self.assertEqual(out[1]["detail"], "40 beds")


# ---- the typical resident ---------------------------------------------------------------------------------------
class Residents(Base):
    def test_happy_path(self):
        r = self.run_with(place.residents, TRACTS)
        t = r["typical"]
        self.assertEqual(set(t), {"median_age", "household_size", "home_value_usd", "rent_usd", "bachelors_pct",
                                  "drive_alone_pct", "work_from_home_pct", "long_commute_pct", "spanish_at_home_pct",
                                  "under_18_pct", "over_65_pct"})
        self.assertEqual(t["median_age"], 35.1)
        self.assertEqual(t["household_size"], 3.52)
        self.assertEqual(t["home_value_usd"], 572492)
        self.assertEqual(t["rent_usd"], 2291)
        self.assertEqual(t["bachelors_pct"], 27.9)
        self.assertEqual(t["drive_alone_pct"], 78.0)
        self.assertEqual(t["work_from_home_pct"], 15.2)
        self.assertEqual(t["long_commute_pct"], 32.5)              # 60 to 89 minutes plus 90 or more
        self.assertEqual(t["spanish_at_home_pct"], 18.3)
        self.assertEqual(t["under_18_pct"], 27.5)
        self.assertEqual(t["over_65_pct"], 9.7)
        self.assertEqual(r["earlier"]["years"], "2010-2014")
        self.assertEqual((r["earlier"]["home_value_usd"], r["earlier"]["rent_usd"]), (252498, 1548))
        self.assertGreater(t["home_value_usd"], r["earlier"]["home_value_usd"] * 2)
        self.assertEqual(r["survey"], "2019-2023")
        self.assertEqual([x["id"] for x in r["tracts"]], [x["id"] for x in TRACTS])
        first = r["tracts"][0]
        self.assertEqual((first["median_age"], first["home_value_usd"], first["long_commute_pct"]), (34.9, 569700, 32.3))
        self.assertIn("Census", r["source"])
        self.assertEqual(r["did_not_answer"], [])
        self.assertJson(r)

    def test_the_weights_are_households_times_share(self):
        base = [{"id": "06065042743", "households": 1000, "share": 1.0},
                {"id": "06065042739", "households": 1000, "share": 1.0}]
        even = self.run_with(place.residents, base)["typical"]["home_value_usd"]
        self.assertEqual(even, round((569700 + 617400) / 2))
        heavy = [{"id": "06065042743", "households": 3000, "share": 1.0}, {"id": "06065042739", "households": 1000, "share": 1.0}]
        self.assertEqual(self.run_with(place.residents, heavy)["typical"]["home_value_usd"], round((569700 * 3 + 617400) / 4))
        half = [{"id": "06065042743", "households": 1000, "share": 0.25}, {"id": "06065042739", "households": 1000, "share": 1.0}]
        self.assertEqual(self.run_with(place.residents, half)["typical"]["home_value_usd"], round((569700 * 0.25 + 617400) / 1.25))
        none = [{"id": "06065042743", "households": 1000, "share": 0.0}, {"id": "06065042739", "households": 1000, "share": 1.0}]
        self.assertEqual(self.run_with(place.residents, none)["typical"]["home_value_usd"], 617400)

    def test_weighted_average_helper(self):
        rows = [{"v": 10.0}, {"v": 20.0}, {"v": None}, {"v": 40.0}]
        self.assertAlmostEqual(place._weighted(rows, "v", [1, 1, 100, 2]), (10 + 20 + 80) / 4)
        self.assertIsNone(place._weighted([{"v": None}], "v", [5]))
        self.assertEqual(place._weighted([{"v": 3.0}, {"v": 5.0}], "v", [0, 0]), 4.0)   # no usable weights: plain average

    def test_a_tract_the_survey_does_not_know_is_left_out(self):
        tracts = TRACTS + [{"id": "06065999999", "households": 5000, "share": 1.0}]
        r = self.run_with(place.residents, tracts)
        self.assertEqual(r["typical"]["home_value_usd"], 572492)
        self.assertIsNone(r["tracts"][-1]["median_age"])
        self.assertEqual(r["earlier"]["tracts_matched"], 3)

    def test_one_service_down_the_rest_still_answer(self):
        r = self.run_with(place.residents, TRACTS, down=["ACS_Median_Age_Boundaries"])
        self.assertIsNone(r["typical"]["median_age"])
        self.assertIsNone(r["tracts"][0]["median_age"])
        self.assertEqual(r["typical"]["household_size"], 3.52)
        self.assertEqual(r["typical"]["home_value_usd"], 572492)
        self.assertEqual(r["did_not_answer"], ["Median age (Census survey)"])
        r = self.run_with(place.residents, TRACTS, down=["ACS_10_14_"])
        self.assertEqual(r["earlier"]["home_value_usd"], None)
        self.assertEqual(r["typical"]["median_age"], 35.1)
        self.assertEqual(r["did_not_answer"], ["Home value and rent, 2010-2014 (Census survey)"])
        r = self.run_with(place.residents, TRACTS, down=["ACS_Vintage_Table"])
        self.assertIsNone(r["survey"])
        self.assertEqual(r["did_not_answer"], ["Survey years (Census survey)"])
        self.assertJson(r)

    def test_the_two_commute_shares_need_both(self):
        self.assertIsNone(place._combine({"a": 5.0, "b": None}, ("a", "b")))
        self.assertEqual(place._combine({"a": 5.0, "b": 2.5}, ("a", "b")), 7.5)

    def test_everything_down(self):
        with self.assertRaises(SourceError):
            self.run_with(place.residents, TRACTS, down=["arcgis.com"])

    def test_no_tracts_is_an_error(self):
        with self.assertRaises(SourceError):
            place.residents([])


# ---- recording --------------------------------------------------------------------------------------------------
KEEP_NEAREST = 15          # a long answer keeps its 15 nearest features
MIN_FIXTURE_NOTE = "trimmed real answers; see the top of tests/test_sources_place.py"


def _trim(url, answer):
    """Shrink a real answer without changing what place.py reads from it."""
    if "power.larc.nasa.gov" in url:
        return {"properties": {"parameter": answer["properties"]["parameter"]}}
    if not isinstance(answer, dict) or "features" not in answer:
        return answer
    feats = answer["features"]
    if len(feats) > KEEP_NEAREST:
        feats = sorted(feats, key=lambda f: place.geometry_miles(f.get("geometry"), LON, LAT) if f.get("geometry") else 1e9)[:KEEP_NEAREST]
    return {"features": feats}


def record():
    """Run the four readers for real at the test point and keep every answer, trimmed, in the fixture file."""
    store, real = {}, fetch.get_json

    def spy(url, params=None, timeout=30, tries=2, post=False):
        answer = real(url, params, timeout=timeout, tries=tries, post=post)
        store[_key(url, params)] = _trim(url, answer)
        return answer
    calls = (lambda: place.climate(LON, LAT, FIRST, LAST), lambda: place.hazards(LON, LAT, BOX), lambda: place.hazards(LON, LAT),
             lambda: place.nearby(LON, LAT, 5.0), lambda: place.nearby(LON, LAT, 1.0), lambda: place.residents(TRACTS))
    with mock.patch.object(fetch, "get_json", spy):
        for call in calls:
            for attempt in range(4):                   # the public services now and then refuse one question
                result = call()
                if not result["did_not_answer"]:
                    break
                print("retrying, did not answer:", result["did_not_answer"])
            else:
                raise SystemExit("a service still does not answer; try again later")
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(store, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    print(f"recorded {len(store)} answers, {FIXTURE.stat().st_size // 1024} KB, in {FIXTURE}")


if __name__ == "__main__":
    if "--record" in sys.argv:
        record()
    else:
        unittest.main()
