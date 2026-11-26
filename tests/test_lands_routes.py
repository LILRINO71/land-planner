"""The lands list, the city card and the small edges of the web server, on the recorded Menifee records (345 large
parcels) and, for the HTTP edges, a real server on this computer answering from them. No network."""
import http.client
import json
import tempfile
import threading
import unittest

from support import EXAMPLE, Clock, offline
from landplanner import geometry as G
from landplanner.cities.menifee import Menifee
from landplanner.planner import LandPlanner, Problem, parcel_number
from landplanner.server import make_server, route

CITY = "/api/cities/menifee"


def q(**more):
    return {k: [str(v)] for k, v in more.items()}


class Base(unittest.TestCase):
    def setUp(self):
        patcher = offline()
        self.replay = patcher.start()
        self.addCleanup(patcher.stop)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = LandPlanner({"menifee": Menifee()}, self.folder.name, clock=Clock())

    def lands(self, **query):
        return route(self.app, "GET", CITY + "/lands", q(**query))[1]

    def problem(self, method, path, query=None, body=None):
        with self.assertRaises(Problem) as caught:
            route(self.app, method, path, query, body)
        return caught.exception


class SearchingTheList(Base):
    def test_words_that_are_not_in_any_row_find_nothing_whatever_digits_they_hold(self):
        for text in ("zzz 1", "zzz 372", "Garbani zzz 2"):
            self.assertEqual(self.lands(q=text)["count"], 0, text)

    def test_a_street_and_its_house_number_find_that_parcel_in_any_order(self):
        for text in ("Garbani 27875", "27875 Garbani", "garbani, 27875", "27875 GARBANI RD Menifee"):
            found = self.lands(q=text)["parcels"]
            self.assertEqual([p["address"] for p in found], ["27875 GARBANI RD MENIFEE  CA 92584"], text)

    def test_a_street_alone_finds_its_parcels_and_menifee_finds_the_ones_with_an_address(self):
        self.assertEqual(self.lands(q="Garbani, Menifee")["count"], 3)
        self.assertEqual(self.lands(q="Garbani 2")["count"], 3, "not the 203 parcels whose numbers hold a 2")

    def test_the_recorded_map_is_searched_the_way_the_list_writes_it(self):
        found = self.lands(q="Map TR 37668")["parcels"]
        self.assertTrue(found and all(p["subdivision"] == "TR 37668" for p in found))
        self.assertIn("372600034", [p["apn"] for p in found])

    def test_a_parcel_number_with_or_without_dashes_still_works(self):
        for text in (EXAMPLE, "372-100-001", "372 100 001"):
            self.assertEqual([p["apn"] for p in self.lands(q=text)["parcels"]], [EXAMPLE], text)

    def test_a_whole_number_of_a_parcel_outside_the_list_is_looked_up_but_words_never_are(self):
        out = self.lands(q="zzz 372100001")
        self.assertEqual((out["count"], out["direct"], out["direct_missing"]), (0, None, False))


class OneSizeOnTheCardAndInTheList(Base):
    def test_the_card_and_the_list_start_with_the_same_largest_parcel(self):
        card = route(self.app, "GET", CITY + "/summary")[1]
        listed = self.lands()
        top = listed["parcels"][0]
        self.assertEqual(card["largest_acres"], top["counted_acres"])
        self.assertEqual(card["largest_acres"], 149.84)
        self.assertNotEqual(top["apn"], "372600034", "the 505-acre record whose outline measures 5.1 does not lead")

    def test_the_total_counts_each_contradicted_record_at_its_outlines_size_and_says_how_many(self):
        card = route(self.app, "GET", CITY + "/summary")[1]
        rows, _ = self.app._large(self.app.city("menifee"))
        wrong = [r for r in rows if G.differs(r["acres"], G.rings_acres(r["rings"]))]
        expected = sum(r["acres"] for r in rows) - sum(r["acres"] for r in wrong) + sum(round(G.rings_acres(r["rings"]), 1) for r in wrong)
        self.assertEqual(card["corrected_records"], len(wrong))
        self.assertEqual(len(wrong), 5)
        self.assertAlmostEqual(card["total_acres"], expected, delta=0.06)
        self.assertLess(card["total_acres"], 8989.5, "the old total counted the 505 acres")
        self.assertEqual(card["large_parcels"], 345)

    def test_a_corrected_row_still_shows_both_sizes_and_sorts_by_the_one_it_counts(self):
        listed = self.lands()["parcels"]
        row = next(p for p in listed if p["apn"] == "372600034")
        self.assertEqual((row["acres"], row["outline_acres"], row["counted_acres"]), (505, 5.1, 5.1))
        sizes = [p["counted_acres"] for p in listed]
        self.assertEqual(sizes, sorted(sizes, reverse=True))

    def test_a_size_filter_uses_the_counted_size(self):
        self.assertNotIn("372600034", [p["apn"] for p in self.lands(min_acres=100)["parcels"]])


class SmallEdgesOfTheApi(Base):
    def test_a_negative_size_is_refused_in_words(self):
        for name in ("min_acres", "max_acres"):
            e = self.problem("GET", CITY + "/lands", q(**{name: -5}))
            self.assertEqual(e.status, 400)
            self.assertIn("cannot be negative", e.message)
        e = self.problem("GET", CITY + "/shapes", q(min_acres=-1))
        self.assertIn("cannot be negative", e.message)

    def test_a_smallest_size_above_the_largest_is_a_400_that_says_so(self):
        e = self.problem("GET", CITY + "/lands", q(min_acres=50, max_acres=20))
        self.assertEqual(e.status, 400)
        self.assertIn("smallest size (50 acres) is larger than the largest size (20 acres)", e.message)
        self.assertGreaterEqual(self.lands(min_acres=20, max_acres=20)["count"], 0, "equal sizes are allowed")

    def test_a_number_that_is_not_a_number_of_acres_is_still_refused(self):
        for text in ("abc", "nan", "inf", "1e9"):
            self.assertEqual(self.problem("GET", CITY + "/lands", q(min_acres=text)).status, 400, text)

    def test_a_parcel_number_of_the_wrong_length_is_a_400(self):
        for text in ("12", "1234567", "1" * 13):
            e = self.problem("GET", f"{CITY}/lands/{text}")
            self.assertEqual((e.status, e.code), (400, "bad-request"), text)
            self.assertIn("not a parcel number", e.message)

    def test_a_parcel_number_with_letters_is_refused_not_tidied_into_another_number(self):
        calls = len(self.replay.asked)
        for text in ("37210000a", "372-100-00x", "abc372100001", "372100001!"):
            e = self.problem("GET", f"{CITY}/lands/{text}")
            self.assertEqual((e.status, e.code), (400, "bad-request"), text)
            self.assertIn("not a parcel number", e.message)
        self.assertEqual(len(self.replay.asked), calls, "nothing was asked of any service for a number that is not one")
        for path in (f"{CITY}/lands/37210000a/plan", f"{CITY}/forecast", f"{CITY}/outlook"):
            query = q(apns="37210000a") if "lands" not in path else None
            self.assertEqual(self.problem("GET", path, query).status, 400, path)

    def test_the_helper_accepts_dashes_and_spaces_only(self):
        self.assertEqual(parcel_number("372-100-001"), "372100001")
        self.assertEqual(parcel_number(" 372 100 001 "), "372100001")
        for bad in ("", None, "37210000a", "12", "372_100_001"):
            with self.assertRaises(Problem):
                parcel_number(bad)

    def test_saving_and_removing_refuse_a_number_with_letters_too(self):
        self.assertEqual(self.problem("POST", "/api/my-lands", None, {"city": "menifee", "apn": "37210000a"}).status, 400)
        self.assertEqual(self.problem("DELETE", "/api/my-lands/menifee/37210000a").status, 400)


class TheServerAnswers(unittest.TestCase):
    """A real server on this computer (any free port) with the recorded records behind it."""

    @classmethod
    def setUpClass(cls):
        cls.patch = offline()
        cls.patch.start()
        cls.folder = tempfile.TemporaryDirectory()
        cls.server = make_server(LandPlanner({"menifee": Menifee()}, cls.folder.name, clock=Clock()))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        cls.folder.cleanup()
        cls.patch.stop()

    def ask(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            res = conn.getresponse()
            return res.status, dict(res.getheaders()), res.read()
        finally:
            conn.close()

    def test_head_on_an_api_route_answers_like_get_without_a_body(self):
        for path in ("/api/health", f"{CITY}/summary", "/api/cities"):
            status, headers, body = self.ask("GET", path)
            h_status, h_headers, h_body = self.ask("HEAD", path)
            self.assertEqual((h_status, h_body), (status, b""), path)
            self.assertEqual(h_status, 200)
            self.assertEqual(h_headers["Content-Length"], str(len(body)), "the same length GET would send")
            self.assertTrue(h_headers["Content-Type"].startswith("application/json"))

    def test_head_on_a_missing_api_route_is_a_404_with_no_body(self):
        status, _, body = self.ask("HEAD", "/api/nothing-here")
        self.assertEqual((status, body), (404, b""))

    def test_other_methods_get_a_json_405_not_an_html_501(self):
        for method in ("OPTIONS", "PUT", "PATCH"):
            for path in ("/api/health", "/", "/api/my-lands"):
                status, headers, body = self.ask(method, path, body=b"{}" if method != "OPTIONS" else None,
                                                 headers={"Content-Type": "application/json"})
                self.assertEqual(status, 405, (method, path))
                self.assertTrue(headers["Content-Type"].startswith("application/json"), (method, path))
                answer = json.loads(body)
                self.assertEqual(answer["error"]["code"], "method-not-allowed")
                self.assertIn(method, answer["error"]["message"])
                self.assertIn("GET", headers["Allow"])

    def test_a_method_nobody_handles_is_json_too(self):
        status, headers, body = self.ask("TRACE", "/api/health")
        self.assertEqual(status, 501)
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        self.assertIn("error", json.loads(body))

    def test_api_alone_is_a_json_404(self):
        for path in ("/api", "/api/"):
            status, headers, body = self.ask("GET", path)
            self.assertEqual(status, 404, path)
            self.assertTrue(headers["Content-Type"].startswith("application/json"), path)
            self.assertEqual(json.loads(body)["error"]["code"], "not-found")

    def test_the_errors_over_http_carry_the_new_messages(self):
        status, _, body = self.ask("GET", f"{CITY}/lands?min_acres=-5")
        self.assertEqual(status, 400)
        self.assertIn("cannot be negative", json.loads(body)["error"]["message"])
        status, _, body = self.ask("GET", f"{CITY}/lands?min_acres=30&max_acres=10")
        self.assertEqual(status, 400)
        status, _, body = self.ask("GET", f"{CITY}/lands/12")
        self.assertEqual(status, 400)
        status, _, body = self.ask("GET", f"{CITY}/lands/37210000a")
        self.assertEqual(status, 400)
        self.assertIn("not a parcel number", json.loads(body)["error"]["message"])


if __name__ == "__main__":
    unittest.main()
