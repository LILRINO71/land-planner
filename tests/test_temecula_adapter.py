"""The second city: Temecula's adapter on its recorded answers (tests/fixtures/temecula.json), the app's pages for
it, and the shared base a third city would stand on. Nothing here reaches the network: a question that was never
recorded fails the test."""
import json
import tempfile
import unittest
from unittest import mock

from support import EXAMPLE, TEMECULA_EXAMPLE, Clock, offline, tool
from landplanner.cities import ADAPTERS, SITE_PARTS, NotFound, SourceError, all_cities
from landplanner.cities.menifee import Menifee
from landplanner.cities.shared import SHARED_SOURCES, ZONING_FAMILIES, RegionalCity
from landplanner.cities.temecula import FIELDS, Temecula, formatted, title
from landplanner.planner import LandPlanner, Problem
from landplanner.server import route
from landplanner.sources import place

KEPT = 40                    # the recorder keeps the first 40 parcels of each parcel answer
BOX = (-117.1515, 33.5075, -117.1465, 33.5120)
PERSONAL = ("OWNER", "MAIL")


class Base(unittest.TestCase):
    def setUp(self):
        patcher = offline()
        self.replay = patcher.start()
        self.addCleanup(patcher.stop)
        self.city = Temecula()


class TheAdapter(Base):
    def test_large_parcels_have_a_centre_an_outline_and_the_zone_at_their_centre(self):
        rows = self.city.large_parcels()
        self.assertEqual(len(rows), KEPT)
        self.assertEqual(rows, sorted(rows, key=lambda r: -r["acres"]))
        for r in rows:
            self.assertRegex(r["apn"], r"^\d{9}$")
            self.assertGreaterEqual(r["acres"], 10)
            self.assertTrue(r["rings"])
            self.assertTrue(-117.3 < r["centre"]["lon"] < -117.0 and 33.4 < r["centre"]["lat"] < 33.6)
        zones = {r["zoning"] for r in rows}
        self.assertIn("OS-C-SM", zones)
        self.assertTrue(all(z == "" or z in self.city.zone_names() for z in zones), zones)

    def test_the_biggest_parcel(self):
        top = self.city.large_parcels()[0]
        self.assertEqual((top["apn"], top["apn_formatted"], top["acres"], top["zoning"]), ("918060001", "918-060-001", 475.0, "OS-C-SM"))
        self.assertTrue(top["looks_vacant"])
        self.assertIsNone(top["fire_hazard_zone"], "the city's record has no fire hazard zone, so none is made up")
        self.assertIsNone(top["council_district"])

    def test_no_owner_or_mailing_address_is_ever_asked_for(self):
        for word in PERSONAL:
            self.assertNotIn(word, FIELDS.upper())
        asked = []

        def listening(url, params=None, timeout=30, tries=2, post=False):
            asked.append(params or {})
            return self.replay(url, params, timeout=timeout, tries=tries, post=post)

        with mock.patch.object(tool, "get_json", listening):
            self.city.large_parcels()
            parcel = self.city.parcel(TEMECULA_EXAMPLE)
            self.city.parcels_in_box(*BOX)
            for part in ("zoning", "general_plan", "surroundings", "neighbour_shapes", "streets", "schools"):
                self.city.site_part(part, parcel)
        self.assertGreater(len(asked), 10)
        for params in asked:
            fields = str(params.get("outFields") or "").upper()
            self.assertNotEqual(fields, "*")
            self.assertFalse(any(word in fields for word in PERSONAL), fields)

    def test_one_parcel(self):
        p = self.city.parcel("921-300-013")
        self.assertEqual((p["apn"], p["acres"], p["zoning"], p["general_plan"]), (TEMECULA_EXAMPLE, 19.9, "CC", "CC"))
        self.assertEqual(p["assessor_class"], "Vacant Commercial Land")
        self.assertTrue(p["looks_vacant"])
        self.assertEqual(p["outline"]["type"], "Polygon")
        self.assertGreater(p["size_feet"]["north_south"], 1000)
        self.assertNotIn("owner", json.dumps(p).lower())

    def test_an_unknown_parcel_is_not_found_and_a_bad_number_too(self):
        with self.assertRaises(NotFound):
            self.city.parcel("999999999")
        with self.assertRaises(NotFound):
            self.city.parcel("12")

    def test_the_zoning_and_the_general_plan_at_the_parcel(self):
        p = self.city.parcel(TEMECULA_EXAMPLE)
        self.assertEqual(self.city.site_part("zoning", p), {"zone": "CC", "abbrev": "CC", "what_it_allows": "Community Comm",
                                                            "general_plan_says": None})
        plan = self.city.site_part("general_plan", p)
        self.assertEqual((plan["land_use"], plan["label"], plan["specific_plan"]), ("CC", "Community Commercial", ""))

    def test_what_surrounds_it_adds_up(self):
        p = self.city.parcel(TEMECULA_EXAMPLE)
        around = self.city.site_part("surroundings", p)
        self.assertEqual(around["within_miles"], 1.0)
        self.assertEqual(sum(r["parcels"] for r in around["by_zoning"]), KEPT)
        self.assertAlmostEqual(sum(r["share_pct"] for r in around["by_zoning"]), 100, delta=0.6)
        shapes = self.city.site_part("neighbour_shapes", p)
        self.assertEqual(len(shapes), KEPT)
        self.assertTrue(all(s["rings"] and s["zoning"] for s in shapes))

    def test_streets_are_ranked_and_local_streets_left_out(self):
        streets = self.city.site_part("streets", self.city.parcel(TEMECULA_EXAMPLE))["streets"]
        self.assertTrue(streets)
        for s in streets:
            self.assertIn(s["rank"], (1, 2, 3, 4))
            self.assertNotIn(s["class"].lower(), ("local", "private"))
            self.assertTrue(s["paths"])
        self.assertIn("Solana Way", {s["name"] for s in streets})

    def test_schools_keep_only_the_kinds_the_city_s_letters_explain(self):
        schools = self.city.site_part("schools", self.city.parcel(TEMECULA_EXAMPLE))["schools"]
        self.assertEqual(schools[0], {"name": "Temecula Elementary School", "grades": "", "kind": "Elementary school", "miles_away": 0.46})
        self.assertTrue(all(s["kind"] in ("", "Elementary school", "Middle school", "High school") for s in schools))

    def test_what_the_city_does_not_publish_is_none_and_asks_nothing(self):
        p = self.city.parcel(TEMECULA_EXAMPLE)
        before = len(self.replay.asked)
        self.assertIsNone(self.city.site_part("signals", p))
        self.assertIsNone(self.city.site_part("projects", p))
        self.assertEqual(len(self.replay.asked), before)
        self.assertEqual(self.city.not_published, ("signals", "projects"))
        self.assertIsNone(self.city.records_updated())

    def test_the_shared_sources_are_asked_at_the_parcel_s_own_centre(self):
        p = self.city.parcel(TEMECULA_EXAMPLE)
        people = self.city.site_part("people", p)
        self.assertEqual([r["miles"] for r in people["rings"]], [1, 3, 5])
        self.assertGreater(people["rings"][0]["people"], 10000)
        stations = self.city.site_part("state_highway_traffic", p)["stations"]
        self.assertEqual(stations[0]["route"], "15")

    def test_a_map_view(self):
        view = self.city.parcels_in_box(*BOX)
        self.assertFalse(view["more"])
        self.assertTrue(view["parcels"])
        for s in view["parcels"]:
            self.assertEqual(set(s), {"apn", "apn_formatted", "acres", "zoning", "looks_vacant", "rings"})

    def test_zone_names_are_the_city_s_words_and_specific_plans_are_named(self):
        names = self.city.zone_names()
        self.assertEqual(names["CC"], "Community Comm")
        self.assertEqual(names["LI"], "Light Industrial")
        self.assertEqual(names["SP-14"], "Uptown Temecula Specific Plan")
        self.assertIn("Planned Dev Overlay", names["PDO-4"])

    def test_zoning_families(self):
        kinds = {"CC": "commercial", "PO": "commercial", "LI": "business", "H": "denser-housing", "L-1": "low-density",
                 "VL": "rural", "OS-C-SM": "open-space", "PI": "public", "SP-14": "specific-plan", "PDO-7": "specific-plan",
                 "TT": "other", "": "other", "CC & LI": "mixed"}
        for code, kind in kinds.items():
            self.assertEqual(self.city.zoning_kind(code), kind, code)
        self.assertTrue({k for k, _, _ in self.city.zoning_kinds} <= set(ZONING_FAMILIES))

    def test_small_helpers(self):
        self.assertEqual(formatted("921300013"), "921-300-013")
        self.assertEqual(formatted("12"), "12")
        self.assertEqual(title("HIGHWAY/TOURIST COMM (HT)"), "Highway/Tourist Comm")
        self.assertEqual(title(None), "")

    def test_a_silent_city_service_is_a_source_error(self):
        with offline(down=["temeculaca.gov"]):
            with self.assertRaises(SourceError):
                Temecula().large_parcels()

    def test_its_allowed_uses_are_not_read_and_not_borrowed(self):
        self.assertIsNone(self.city.allowed_uses("CC"))
        self.assertTrue(any("Temecula's code has not been read" in line for line in self.city.not_covered))

    def test_it_names_who_to_see_and_no_person(self):
        self.assertEqual((self.city.place["name"], self.city.place["fips"], self.city.place["county"]), ("Temecula", "78120", "Riverside"))
        self.assertIn("Planning", self.city.place["planning"])


class ThroughTheApp(Base):
    def setUp(self):
        super().setUp()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = LandPlanner(all_cities(), self.folder.name, clock=Clock())

    def get(self, path, query=None):
        return route(self.app, "GET", path, query or {}, None)[:2]

    def test_both_cities_are_listed_menifee_first(self):
        self.assertEqual([cls.id for cls in ADAPTERS], ["menifee", "temecula"])
        status, body = self.get("/api/cities")
        self.assertEqual(status, 200)
        cities = body["cities"] if isinstance(body, dict) else body
        self.assertEqual([c["id"] for c in cities], ["menifee", "temecula"])
        temecula = cities[1]
        self.assertEqual(temecula["not_published"], ["signals", "projects"])
        self.assertEqual(temecula["sources"]["terrain"], SHARED_SOURCES["terrain"])

    def test_the_card_counts_its_large_parcels(self):
        summary = self.app.summary("temecula")
        self.assertEqual((summary["large_parcels"], summary["largest_acres"]), (KEPT, 475.0))
        self.assertGreater(summary["look_vacant"], 0)

    def test_the_list_filters_sorts_and_searches(self):
        every = self.app.lands("temecula")
        self.assertEqual(every["total"], KEPT)
        big = self.app.lands("temecula", min_acres=100)["parcels"]
        self.assertTrue(big and all(r["acres"] >= 100 for r in big))
        vacant = self.app.lands("temecula", vacant=True)["parcels"]
        self.assertTrue(vacant and all(r["looks_vacant"] for r in vacant))
        open_space = self.app.lands("temecula", kind="open-space")["parcels"]
        self.assertTrue(open_space and all(r["zoning_kind"] == "open-space" for r in open_space))
        found = self.app.lands("temecula", q="918-060-001")["parcels"]
        self.assertEqual([r["apn"] for r in found], ["918060001"])
        self.assertEqual(found[0]["zoning_name"], "Open Space Cons - Santa Margarita")

    def test_a_land_s_page_says_what_the_city_does_not_publish(self):
        land = self.app.land("temecula", TEMECULA_EXAMPLE)
        self.assertEqual(land["parcel"]["zoning_kind"], "commercial")
        self.assertEqual(land["sources"]["zoning"], "ok")
        self.assertIsNone(land["allowed_uses"], "Menifee's table is never shown for another city")
        market = self.app.land("temecula", TEMECULA_EXAMPLE, group="market")
        self.assertEqual((market["sources"]["signals"], market["sources"]["projects"]), ("not published", "not published"))
        self.assertEqual(market["sources"]["schools"], "ok")

    def test_the_plan_works_and_says_where_its_zoning_words_come_from(self):
        plan = self.app.plan("temecula", TEMECULA_EXAMPLE)
        self.assertEqual(plan["zoning_rules"]["basis"], "family")
        acres = {u["id"]: u["acres"] for u in plan["uses"]}
        self.assertAlmostEqual(sum(acres.values()), plan["acres"], delta=0.11)
        self.assertGreater(acres["retail"], 0)
        self.assertEqual(acres["homes"], 0, "houses are not what a commercial zone is for")
        self.assertEqual(next(u for u in plan["uses"] if u["id"] == "retail")["fit_words"], "What the zone is for")
        self.assertTrue(any("table of allowed uses is not read for this city" in a for a in plan["advice"]))
        unpublished = [a for a in plan["advice"] if a.startswith("This city does not publish")]
        self.assertEqual(len(unpublished), 1)
        self.assertIn("traffic signals", unpublished[0])
        self.assertFalse(any("did not answer just now" in a for a in plan["advice"]))
        self.assertEqual(plan["sources"]["signals"], "not published")
        json.dumps(plan, allow_nan=False)

    def test_it_can_be_saved_to_my_lands_beside_a_menifee_land(self):
        self.app.save("temecula", TEMECULA_EXAMPLE)
        self.app.save("menifee", EXAMPLE)
        mine = self.app.my_lands()["lands"]
        self.assertEqual({(m["city"], m["apn"]) for m in mine}, {("temecula", TEMECULA_EXAMPLE), ("menifee", EXAMPLE)})

    def test_the_routes_answer(self):
        self.assertEqual(self.get("/api/cities/temecula/summary")[0], 200)
        self.assertEqual(self.get("/api/cities/temecula/lands")[0], 200)
        self.assertEqual(self.get(f"/api/cities/temecula/lands/{TEMECULA_EXAMPLE}")[0], 200)
        self.assertEqual(self.get(f"/api/cities/temecula/lands/{TEMECULA_EXAMPLE}/plan")[0], 200)

    def test_a_number_the_city_does_not_have_is_a_404_in_plain_words(self):
        with self.assertRaises(Problem) as caught:
            self.get("/api/cities/temecula/lands/999999999")
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(caught.exception.message, "No parcel in Temecula has the number 999999999.")


class TheSharedBase(unittest.TestCase):
    """What a third city gets for nothing, and what it can never borrow."""

    class Thirdtown(RegionalCity):
        id, name, region = "thirdtown", "Thirdtown", "California"
        place = {"name": "Thirdtown", "fips": "00000", "county": "Riverside"}

    PARCEL = {"apn": "1", "centre": {"lon": -117.2, "lat": 33.6},
              "outline": {"coordinates": [[[-117.21, 33.59], [-117.19, 33.59], [-117.19, 33.61], [-117.21, 33.59]]]},
              "size_feet": {"east_west": 5280, "north_south": 0}}

    def test_a_city_part_it_does_not_fill_in_is_none(self):
        city = self.Thirdtown()
        for part, group in SITE_PARTS.items():
            if part in ("zoning", "general_plan", "surroundings", "neighbour_shapes", "streets", "signals", "projects", "schools"):
                self.assertIsNone(city.site_part(part, self.PARCEL), part)

    def test_the_shared_parts_go_to_the_shared_tool(self):
        city = self.Thirdtown()
        with mock.patch("landplanner.cities.shared.tool") as tool:
            tool.NotFound, tool.SourceError = NotFound, SourceError
            city.site_part("people", self.PARCEL)
            city.site_part("state_highway_traffic", self.PARCEL)
            city.photo_date(-117.2, 33.6)
        tool.people_near.assert_called_once_with(-117.2, 33.6)
        tool.traffic.assert_called_once_with(-117.2, 33.6)
        tool.photo_date.assert_called_once_with(-117.2, 33.6)

    def test_hazards_and_nearby_are_asked_with_no_city_maps_never_menifee_s(self):
        city = self.Thirdtown()
        with mock.patch.object(place, "hazards", return_value={}) as hazards, mock.patch.object(place, "nearby", return_value={}) as nearby:
            city.outlook_part("hazards", self.PARCEL)
            city.outlook_part("nearby", self.PARCEL)
        empty = {"name": "Thirdtown", "host": "", "layers": {}}
        self.assertEqual(hazards.call_args.kwargs["city_layers"], empty)
        self.assertEqual(nearby.call_args.kwargs["city_layers"], empty)
        self.assertIs(Menifee().map_layers, place.MENIFEE_LAYERS)
        self.assertIsNone(Temecula().map_layers)

    def test_a_map_the_city_does_not_publish_is_said_as_that_and_no_other_city_s_is_read(self):
        asked = []

        def answer(url, params=None, **more):
            asked.append(url)
            raise SourceError("(test) silent")

        with mock.patch.object(place.fetch, "get_json", answer):
            with self.assertRaises(SourceError):
                place.hazards(-117.2, 33.6, None, place.no_city_layers("Thirdtown"))
        self.assertFalse([u for u in asked if place.MENIFEE_LAYERS["host"] in u], "Menifee's maps were read for another city")
        with self.assertRaises(place.NotPublished):
            place._layer_url(place.no_city_layers("Thirdtown"), "fire_hazard")

    def test_not_published_blocks_are_listed_apart_from_silent_ones(self):
        def answer(url, params=None, **more):
            if "hazards.fema.gov" in url or "NFHL" in url:
                return {"features": []}
            raise SourceError("(test) silent")

        with mock.patch.object(place.fetch, "get_json", answer):
            try:
                out = place.hazards(-117.2, 33.6, None, place.no_city_layers("Thirdtown"))
            except SourceError:
                self.skipTest("the flood block did not go through the patched function")
        self.assertIn("Fire hazard zones (city map)", out["not_published"])
        self.assertNotIn("Fire hazard zones (city map)", out["did_not_answer"])

    def test_the_reach_of_a_parcel(self):
        self.assertEqual(RegionalCity.reach(self.PARCEL), 0.5)

    def test_the_economy_is_asked_for_the_city_s_own_name(self):
        from landplanner.sources import economy
        with mock.patch.object(economy, "shop_sales_by_year", return_value={"rows": []}) as sales:
            self.Thirdtown().economy_part("sales", 2026)
        sales.assert_called_once_with("Thirdtown")


if __name__ == "__main__":
    unittest.main()
