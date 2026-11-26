"""Which uses each zone allows: the recorded Menifee table (landplanner/cities/records), the reader that fills it
(tools/record_allowed_uses.py, tried here on small made-up pages), the lookups (landplanner/uses.py), and how the
Plan, the Zoning page's answer and the steps use them. Nothing here reaches the network."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from support import EXAMPLE, ROOT, Clock, Tinytown, offline
from landplanner import outlook, plan as P, uses as U
from landplanner.cities import menifee_uses
from landplanner.cities.menifee import Menifee
from landplanner.planner import LandPlanner
from landplanner.server import route

_spec = importlib.util.spec_from_file_location("record_allowed_uses", ROOT / "tools" / "record_allowed_uses.py")
recorder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recorder)

# every zoning code Menifee's parcel and zoning layers returned when the table was recorded (2026-11-26), single
# zones only: a parcel with two zones ("RM & RR5") is answered zone by zone
TABLE_ZONES = ("RM", "RR5", "RR2", "RR1", "RR1/2", "LDR-1", "LDR-2", "LMDR", "MDR", "HDR", "CR", "CO", "BP", "HI",
               "EDC-NG", "EDC-MB", "EDC-CC", "EDC-NR", "EDC-SG", "OS-C", "OS-R", "OS-W", "PF", "PUC", "RX")
DISTRICTS = ("PDO-1", "PDO-2", "PDO-3", "PDO-4", "PDO-5", "PDO-6", "PDO-7")
PLAN_ZONES = ("Specific Plan", "Countryside SP", "Menifee North SP", "Menifee Village SP", "Menifee East SP")
BUILT = ("retail", "office", "apartments", "homes", "business")


def status(code, **more):
    return {u: a["status"] for u, a in menifee_uses.table().answer(code, **more)["uses"].items()}


class RecordedTable(unittest.TestCase):
    def setUp(self):
        self.table = menifee_uses.table()
        self.data = self.table.data

    def test_the_file_says_where_and_when_it_was_read(self):
        self.assertRegex(self.data["read_on"], r"^20\d\d-\d\d-\d\d$")
        self.assertIn("Title 9", self.data["code"])
        self.assertTrue(self.data["home"].startswith("https://online.encodeplus.com/regs/menifee-ca/"))
        for t in self.data["tables"]:
            self.assertRegex(t["table"], r"^Table 9\.1\d\d\.030-1$")
            self.assertRegex(t["section"], r"^9\.1\d\d\.030$")
            self.assertTrue(t["url"].startswith("https://"))
            self.assertRegex(t["read_on"], r"^20\d\d-\d\d-\d\d$")
            self.assertIn("conditional use permit", t["rules"]["letters"])
            self.assertIn("not permitted", t["rules"]["unlisted"])

    def test_every_zone_the_city_returns_has_an_answer(self):
        for zone in TABLE_ZONES:
            part = self.table.answer(zone)["parts"][0]
            self.assertEqual(part["kind"], "table", zone)
            self.assertTrue(part["outright"] or part["permit"], zone)
            self.assertTrue(part["not_allowed"], zone)
        for zone in DISTRICTS:
            self.assertEqual(self.table.answer(zone)["parts"][0]["kind"], "planned_development", zone)
        for zone in PLAN_ZONES:
            self.assertEqual(self.table.answer(zone)["parts"][0]["kind"], "specific_plan", zone)

    def test_no_row_was_left_unread_and_every_cell_is_a_letter_or_a_stated_gap(self):
        for t in self.data["tables"]:
            for r in t["rows"]:
                self.assertFalse(r.get("unread"), r["use"])
                self.assertEqual(set(r["cells"]), set(t["zones"]), r["use"])
                for value in r["cells"].values():
                    self.assertIn(value, ("P", "C", "--", "NA", ""), r["use"])

    def test_cells_checked_by_hand_against_the_city_s_page(self):
        def cell(zone, use, case=None):
            t = self.table.columns[zone]
            rows = [r for r in t["rows"] if r["use"] == use and r.get("case") == case]
            self.assertEqual(len(rows), 1, (zone, use, case))
            return rows[0]["cells"][zone]
        self.assertEqual(cell("CR", "General retail"), "P")
        self.assertEqual(cell("BP", "General retail"), "--")
        self.assertEqual(cell("CO", "Offices, professional and medical"), "P")
        self.assertEqual(cell("HI", "Manufacturing, Heavy-Intensity"), "P")
        self.assertEqual(cell("EDC-CC", "Multi-family dwellings"), "C")
        self.assertEqual(cell("EDC-MB", "Manufacturing, Light-Intensity"), "C")
        self.assertEqual(cell("EDC-NG", "Warehouse (except noxious, explosives, or dangerous materials)", "Fulfillment Center"), "P")
        self.assertEqual(cell("EDC-CC", "Warehouse (except noxious, explosives, or dangerous materials)", "Fulfillment Center"), "--")
        self.assertEqual(cell("HDR", "Multiple family"), "P")
        self.assertEqual(cell("LDR-2", "Multiple family"), "--")
        self.assertEqual(cell("HDR", "Single- family detached"), "--")
        self.assertEqual(cell("RR1", "Single- family detached"), "P")
        self.assertEqual(cell("RR5", "Event Facilities"), "C")
        self.assertEqual(cell("OS-R", "Golf course and clubhouse"), "C")
        self.assertEqual(cell("PF", "Library"), "P")
        self.assertEqual(cell("RX", "Railroad tracks, station, transportation hub, passenger terminal"), "C")
        self.assertEqual(cell("HI", "Car washes"), "")          # the city left this cell blank

    def test_a_blank_cell_is_said_as_blank(self):
        other = self.table.answer("HI")["parts"][0]["other"]
        self.assertIn("the city left this cell blank", [r["why"] for r in other if r["use"] == "Car washes"])

    def test_every_matched_name_is_a_real_row_of_the_code(self):
        names = set()
        for t in self.data["tables"]:
            for r in t["rows"]:
                names.add(U.same(r["use"]))
                names.add(U.same(r.get("case")))
        for use, m in menifee_uses.USE_MATCH.items():
            self.assertTrue(m["lead"] and m["why"], use)
            for name in m["lead"] + m["also"]:
                self.assertIn(U.same(name), names, f"{use}: the code has no row called {name!r}")
        self.assertEqual(set(menifee_uses.USE_MATCH), set(P.USE_IDS))

    def test_no_person_is_named_in_the_match(self):
        text = (ROOT / "landplanner" / "cities" / "menifee_uses.py").read_text(encoding="utf-8")
        self.assertNotIn("@", text)


class Lookups(unittest.TestCase):
    def test_the_corridor_core(self):
        self.assertEqual(status("EDC-CC"), {"retail": "outright", "office": "outright", "apartments": "permit",
                                            "homes": "permit", "business": "outright", "park": "unlisted"})

    def test_commercial_retail_prohibits_light_industry_and_lists_no_housing(self):
        s = status("CR")
        self.assertEqual((s["retail"], s["office"], s["business"]), ("outright", "outright", "no"))
        self.assertEqual((s["apartments"], s["homes"]), ("unlisted", "unlisted"))

    def test_the_state_law_route_for_housing_is_shown_beside_the_answer_and_does_not_decide_it(self):
        a = menifee_uses.table().answer("CR")["uses"]["apartments"]
        self.assertEqual(a["status"], "unlisted")
        self.assertIn("Unlisted", "Unlisted" if "not permitted" in a["why"] else "")
        self.assertIn("Multi-family dwellings in commercial zones per AB 2011 & SB 6", [r["use"] for r in a["related"]])

    def test_housing_zones(self):
        self.assertEqual(status("HDR")["apartments"], "outright")
        self.assertEqual(status("HDR")["homes"], "no")
        self.assertEqual(status("LDR-2")["homes"], "outright")
        self.assertEqual(status("LDR-2")["apartments"], "no")
        self.assertEqual(status("RR1")["retail"], "unlisted")

    def test_a_permit_names_the_permit_and_carries_the_table_s_condition(self):
        a = menifee_uses.table().answer("EDC-CC")["uses"]["homes"]
        self.assertEqual(a["permit"], "conditional use permit")
        self.assertEqual(a["table"], "Table 9.140.030-1")
        self.assertIn("tentative tract map", a["requirements"])
        self.assertEqual(a["read_from"][0]["use"], "Single-family residences")

    def test_open_space_and_public_land_allow_nothing_built(self):
        for zone in ("OS-C", "OS-R", "OS-W", "PF", "PUC", "RX"):
            s = status(zone)
            self.assertTrue(all(s[u] in ("unlisted", "no") for u in BUILT), zone)

    def test_parks_unlisted_is_not_called_a_zone_change(self):
        a = menifee_uses.table().answer("CR")["uses"]["park"]
        self.assertEqual(a["words"], "Not listed as a use of its own")
        self.assertIn("part of that project", a["why"])

    def test_a_specific_plan_is_named_and_never_answered_from_the_tables(self):
        a = menifee_uses.table().answer("Specific Plan", plan_name="Audie Murphy Ranch SP")
        part = a["parts"][0]
        self.assertEqual((part["kind"], part["plan"], part["plan_number"]), ("specific_plan", "Audie Murphy Ranch", "SP-1"))
        self.assertIn("Audie Murphy Ranch Specific Plan (SP-1)", part["says"])
        self.assertIn("has not read that plan's document", part["says"])
        self.assertTrue(all(u["status"] == "plan" for u in a["uses"].values()))
        self.assertNotIn("outright", part)

    def test_a_specific_plan_named_on_the_parcel_record(self):
        part = menifee_uses.table().answer("Countryside SP")["parts"][0]
        self.assertEqual((part["plan"], part["plan_number"]), ("Countryside", "SP-7"))

    def test_a_specific_plan_the_records_do_not_name(self):
        part = menifee_uses.table().answer("Specific Plan")["parts"][0]
        self.assertEqual(part["plan"], "")
        self.assertIn("did not name which one", part["says"])

    def test_a_planned_development_follows_the_zone_the_code_names(self):
        part = menifee_uses.table().answer("PDO-3")["parts"][0]
        self.assertEqual((part["kind"], part["same_as"], part["written_as"]), ("planned_development", "MDR", "PD-3"))
        self.assertIn("same as those allowed in the MDR zone", part["sentence"])
        self.assertEqual(status("PDO-3"), status("MDR"))

    def test_a_planned_development_split_between_two_zones_says_it_depends(self):
        a = menifee_uses.table().answer("PDO-5")
        self.assertEqual([c["column"] for c in a["parts"][0]["areas"]], ["LDR-2", "LMDR"])
        self.assertEqual(a["uses"]["homes"]["status"], "outright")          # both parts agree
        self.assertEqual(a["uses"]["apartments"]["status"], "depends")      # LDR-2 prohibits, LMDR permits
        self.assertIn("city's map", a["parts"][0]["says"])

    def test_a_code_with_no_column_is_unread_not_guessed(self):
        a = menifee_uses.table().answer("ZZ-9")
        self.assertEqual(a["parts"][0]["kind"], "unread")
        self.assertIn("no column for “ZZ-9”", a["parts"][0]["says"])
        self.assertTrue(all(u["status"] == "unread" and u["fit"] == "unknown" for u in a["uses"].values()))

    def test_a_record_code_without_a_column_uses_the_zone_the_city_s_map_gives(self):
        part = menifee_uses.table().answer("AO", layer_zone="EDC-CC")["parts"][0]
        self.assertEqual((part["kind"], part["read_as"]), ("table", "EDC-CC"))
        self.assertIn("The parcel record says “AO”", part["says"])

    def test_no_zone_listed(self):
        a = menifee_uses.table().answer(" ")
        self.assertEqual(a["parts"], [])
        self.assertIn("no zone", a["says"])
        self.assertTrue(all(u["fit"] == "unknown" for u in a["uses"].values()))

    def test_two_zones_on_one_parcel_are_answered_one_by_one(self):
        a = menifee_uses.table().answer("LDR - 1 & RM")
        self.assertEqual([p["column"] for p in a["parts"]], ["LDR-1", "RM"])
        self.assertEqual(a["uses"]["homes"]["status"], "outright")
        self.assertEqual(len(a["uses"]["homes"]["by_zone"]), 2)

    def test_two_zones_that_differ_say_which_part_allows_it(self):
        a = menifee_uses.table().answer("EDC-MB & RR5")
        self.assertEqual(a["uses"]["retail"]["status"], "outright")
        self.assertIn("on the part zoned EDC-MB", a["uses"]["retail"]["words"])

    def test_the_answer_carries_its_source_and_the_match(self):
        a = menifee_uses.table().answer("BP")
        self.assertEqual(a["basis"], "table")
        self.assertRegex(a["source"]["read_on"], r"^20\d\d-")
        self.assertEqual({m["use"] for m in a["matches"]}, set(P.USE_IDS))
        self.assertEqual(a["parts"][0]["section"], "9.135.030")


def page(body):
    return f"<html><body><h1>Chapter</h1>{body}</body></html>"


TABLE = """<table><tr><th colspan="4">Table 9.999.030-1 Test Zones - Allowed Uses and Approval Requirements</th></tr>
<tr class="sheading"><th>Allowed Use</th><th><img alt="01 - First (AA) Category" src="x.png"></th>
 <th><img alt="02 - Second - &#189;-acre (BB1/2) Category" src="y.png"></th><th>Additional Requirements</th></tr>
<tr><td colspan="4">RESIDENTIAL USES</td></tr>
<tr><td>Single homes</td><td>P</td><td>&mdash;</td><td>Chapter 9.1 (Homes)</td></tr>
<tr><td><p>Batting cages</p><p>&nbsp;</p><p>Indoor</p><p>Outdoor</p></td><td>P<br><br>C</td><td>--</td><td></td></tr>
<tr><td>Car washes</td><td>C (indoor only)</td><td></td><td></td></tr>
<tr><td>Towing</td><td>p</td><td>C*</td><td>*see note</td></tr>
<tr><td>Odd row</td><td>maybe</td><td>NA</td><td></td></tr>
<tr><td><p>Stacked</p><p>One</p></td><td>P<br>C<br>P</td><td>P<br>C</td><td></td></tr>
<tr><td colspan="4">1 A footnote under the table</td></tr></table>"""


class Reader(unittest.TestCase):
    def setUp(self):
        self.table = recorder.read_table(page(TABLE))
        self.rows = {(r["use"], r.get("case")): r for r in self.table["rows"]}

    def test_the_table_number_and_the_zone_columns(self):
        self.assertEqual(self.table["table"], "Table 9.999.030-1")
        self.assertEqual(self.table["zones"], ["AA", "BB1/2"])
        self.assertEqual(self.table["footnotes"], ["1 A footnote under the table"])

    def test_a_plain_row_and_its_group(self):
        r = self.rows[("Single homes", None)]
        self.assertEqual(r["cells"], {"AA": "P", "BB1/2": "--"})
        self.assertEqual((r["group"], r["requirements"]), ("RESIDENTIAL USES", "Chapter 9.1 (Homes)"))

    def test_stacked_cases_become_one_row_each_and_a_single_letter_covers_them_all(self):
        self.assertEqual(self.rows[("Batting cages", "Indoor")]["cells"], {"AA": "P", "BB1/2": "--"})
        self.assertEqual(self.rows[("Batting cages", "Outdoor")]["cells"], {"AA": "C", "BB1/2": "--"})

    def test_a_blank_cell_stays_blank_and_words_in_brackets_are_kept(self):
        r = self.rows[("Car washes", None)]
        self.assertEqual(r["cells"], {"AA": "C", "BB1/2": ""})
        self.assertEqual(r["cell_notes"], {"AA": "indoor only"})

    def test_a_small_letter_and_a_starred_letter(self):
        r = self.rows[("Towing", None)]
        self.assertEqual(r["cells"], {"AA": "P", "BB1/2": "C"})
        self.assertEqual(r["cell_notes"], {"BB1/2": "see the note"})

    def test_a_value_that_is_not_a_letter_is_kept_as_written(self):
        r = self.rows[("Odd row", None)]
        self.assertEqual(r["cells"], {"AA": "?", "BB1/2": "NA"})
        self.assertEqual(r["as_written"], {"AA": "maybe"})

    def test_a_row_whose_lines_do_not_match_its_letters_is_unread(self):
        r = self.rows[("Stacked / One", None)]
        self.assertTrue(r["unread"])
        self.assertEqual(r["as_written"], ["P / C / P", "P / C"])

    def test_unread_and_odd_rows_show_as_could_not_be_read(self):
        data = {"tables": [dict(self.table, chapter="9.999", section="9.999.030", url="https://example.org", read_on="2026-01-01", rules={})]}
        part = U.UseTable(data, {"homes": {"lead": ("Single homes",)}}).answer("AA")["parts"][0]
        why = {r["use"]: r["why"] for r in part["other"]}
        self.assertIn("could not be matched", why["Stacked / One"])
        self.assertIn("“maybe”", why["Odd row"])
        self.assertEqual([r["use"] for r in part["outright"]], ["Single homes", "Batting cages: Indoor", "Towing"])

    def test_a_page_with_no_such_table(self):
        self.assertIsNone(recorder.read_table(page("<table><tr><td>Table 1 Development Standards</td></tr></table>")))

    def test_the_chapter_s_own_rules_are_quoted(self):
        text = page("<p>B. Approval Requirements. Where indicated with a letter “P” the use shall be a permitted use. A letter "
                    "“C” indicates the use shall be conditionally permitted subject to the approval of a conditional use permit. "
                    "Where indicated with a “--,” the use is prohibited within the zone.</p><p>C. Unlisted Uses. Uses not "
                    "specifically listed in this table shall be considered not permitted in all of the listed zones.</p>")
        rules = recorder.rules(text)
        self.assertTrue(rules["letters"].endswith("prohibited within the zone."))
        self.assertTrue(rules["unlisted"].startswith("Uses not specifically listed"))

    def test_specific_plans_and_planned_developments(self):
        text = page("<p>9.155.010 Purpose</p><p>9.155.010 Purpose This Chapter lists them.</p>"
                    "<p>9.155.020 Adopted Specific Plans The following specific plans have been approved by the City. They are "
                    "hereby incorporated into this Title in their entirety by reference.</p><p>SP-1 First Ranch</p><p>SP-2 Second (Shop)</p>"
                    "<p>A. Future specific plans shall be numbered.</p><p>9.155.030 Planned Development Districts The following.</p>"
                    "<p>A. PD-1: Under (TR 1)</p><p>1. The uses permitted in this PDO shall be the same as those allowed in the AA zone listed in 9.1.</p>"
                    "<p>2. Lots shall conform.</p><p>B. PD-2: Over (TR 2)</p><p>1. The minimum lot is large.</p><p>2. More.</p>")
        special = recorder.read_special(text)
        self.assertEqual(special["specific_plans"], [{"number": "SP-1", "name": "First Ranch"}, {"number": "SP-2", "name": "Second (Shop)"}])
        self.assertTrue(special["specific_plans_wording"].endswith("by reference."))
        first, second = special["planned_developments"]
        self.assertEqual((first["number"], first["name"], first["same_uses_as"]), ("PDO-1", "Under (TR 1)", ["AA"]))
        self.assertEqual((second["number"], second["same_uses_as"], second["uses_sentence"]), ("PDO-2", [], ""))

    def test_a_planned_development_whose_uses_sentence_is_missing_is_unread(self):
        data = {"tables": [], "special": {"planned_developments": [{"number": "PDO-2", "name": "Over", "same_uses_as": []}]}}
        a = U.UseTable(data, {"homes": {"lead": ("Single homes",)}}).answer("PDO-2")
        self.assertEqual(a["uses"]["homes"]["status"], "unread")
        self.assertIn("does not say", a["parts"][0]["says"])


def parcel(zoning, kind, acres=40.0):
    return {"apn": "1", "acres": acres, "zoning": zoning, "zoning_kind": kind, "zoning_name": zoning,
            "centre": {"lat": 33.655, "lon": -117.165},
            "outline": {"type": "Polygon", "coordinates": [[[-117.17, 33.65], [-117.165, 33.65], [-117.165, 33.6537],
                                                           [-117.17, 33.6537], [-117.17, 33.65]]]}}


def planned(zoning, kind, mode="zoning", rules=True, **more):
    parts = {"allowed_uses": menifee_uses.table().answer(zoning, **more)} if rules else {}
    return P.make_plan(parcel(zoning, kind), parts, {"mode": mode}, Menifee().zoning_kind)


class InThePlan(unittest.TestCase):
    def fits(self, plan):
        return {u["id"]: u["fit"] for u in plan["uses"]}

    def test_each_use_is_marked_outright_permit_or_change(self):
        plan = planned("EDC-CC", "edc")
        self.assertEqual(self.fits(plan), {"retail": "fits", "office": "fits", "apartments": "permit", "homes": "permit",
                                           "business": "fits", "park": "fits"})
        words = {u["id"]: u["fit_words"] for u in plan["uses"]}
        self.assertEqual(words["retail"], "Allowed outright")
        self.assertEqual(words["homes"], "Allowed with a conditional use permit")
        self.assertEqual(words["park"], "Part of any project")

    def test_follow_today_s_zoning_only_builds_what_the_table_allows(self):
        for zoning, kind in (("CR", "commercial"), ("BP", "business"), ("LDR-2", "low-density"), ("HDR", "denser-housing"),
                             ("EDC-NG", "edc"), ("RR1", "rural"), ("CO", "commercial"), ("HI", "business")):
            plan = planned(zoning, kind)
            for u in plan["uses"]:
                if u["id"] != "park" and u["acres"] > 0:
                    self.assertIn(u["fit"], ("fits", "permit"), f"{zoning}: {u['id']} is in the mix but the table does not allow it")

    def test_the_family_guess_no_longer_decides(self):
        # the kind of zone said offices "fit" a heavy industrial zone and shops "may" fit a business park;
        # the city's table prohibits both
        self.assertEqual(self.fits(planned("HI", "business"))["office"], "change")
        self.assertEqual(self.fits(planned("BP", "business"))["retail"], "change")
        self.assertEqual(self.fits(planned("HI", "business", rules=False))["office"], "fits")

    def test_best_use_marks_what_needs_a_zone_change(self):
        plan = planned("LDR-2", "low-density", mode="best")
        changed = [u for u in plan["uses"] if u["fit"] == "change"]
        self.assertTrue(changed)
        for u in changed:
            self.assertIn("needs a zone change", u["fit_words"])
        in_mix = [u["label"].lower() for u in changed if u["acres"] > 0]
        if in_mix:
            self.assertTrue(any("would need a zoning change" in a and "city's own table" in a for a in plan["advice"]))

    def test_the_reason_names_the_row_and_the_table(self):
        plan = planned("EDC-CC", "edc")
        homes = next(u for u in plan["uses"] if u["id"] == "homes")
        reason = next(r for r in homes["reasons"] if r["source"].startswith("City development code"))
        self.assertEqual(reason["source"], "City development code, Table 9.140.030-1")
        self.assertIn("only with a conditional use permit", reason["text"])
        self.assertIn("“Single-family residences”", reason["text"])
        self.assertIn("tentative tract map", reason["text"])
        self.assertEqual(homes["fit_read"]["read_from"][0]["letter"], "C")

    def test_a_permit_scores_between_outright_and_not_allowed(self):
        def zoning_points(zoning, kind, use):
            u = next(x for x in planned(zoning, kind)["uses"] if x["id"] == use)
            return next(r["effect"] for r in u["reasons"] if r["source"].startswith("City development code"))
        outright, permit, no = zoning_points("HDR", "denser-housing", "apartments"), zoning_points("EDC-CC", "edc", "apartments"), \
            zoning_points("LDR-2", "low-density", "apartments")
        self.assertGreater(outright, permit)
        self.assertGreater(permit, 0)
        self.assertLess(no, 0)

    def test_best_use_leaves_the_table_out_of_the_score_but_still_says_it(self):
        plan = planned("LDR-2", "low-density", mode="best")
        shops = next(u for u in plan["uses"] if u["id"] == "retail")
        reason = next(r for r in shops["reasons"] if r["source"].startswith("City development code"))
        self.assertEqual(reason["effect"], 0)
        self.assertIn("does not list this use", reason["text"])
        self.assertIn("Best use leaves zoning out of the score", reason["text"])

    def test_a_permit_in_the_mix_is_said_in_the_advice_and_the_headline(self):
        plan = planned("EDC-CC", "edc")
        need = [u["label"] for u in plan["uses"] if u["fit"] == "permit" and u["acres"] > 0]
        head = P.headline(plan)
        self.assertEqual(head["needs_permit"], need)
        if need:
            self.assertTrue(any("conditional use permit" in a for a in plan["advice"]))

    def test_the_plan_says_where_allowed_was_read(self):
        rules = planned("EDC-CC", "edc")["zoning_rules"]
        self.assertEqual(rules["basis"], "table")
        self.assertEqual(rules["zones"][0]["table"], "Table 9.140.030-1")
        self.assertRegex(rules["source"]["read_on"], r"^20\d\d-")

    def test_a_specific_plan_is_marked_set_by_the_plan(self):
        plan = planned("Specific Plan", "specific-plan", plan_name="Menifee North SP")
        for u in plan["uses"]:
            if u["id"] != "park":
                self.assertEqual((u["fit"], u["fit_words"]), ("review", "Set by the specific plan"))
        homes = next(u for u in plan["uses"] if u["id"] == "homes")
        self.assertTrue(any("Menifee North Specific Plan (SP-11)" in r["text"] for r in homes["reasons"]))

    def test_without_a_table_the_plan_says_so(self):
        plan = planned("CR", "commercial", rules=False)
        self.assertEqual(plan["zoning_rules"]["basis"], "family")
        self.assertEqual(next(u for u in plan["uses"] if u["id"] == "retail")["fit_words"], "What the zone is for")
        self.assertTrue(any("table of allowed uses is not read" in a for a in plan["advice"]))
        self.assertIsNone(plan["uses"][0]["fit_read"])

    def test_open_space_still_has_nothing_to_build(self):
        self.assertTrue(planned("OS-R", "open-space")["nothing_to_build"])


class InTheSteps(unittest.TestCase):
    def steps(self, uses):
        forecast = {"year": 2026, "figures": [{"id": "ready_years", "value": 2}], "programme": {}}
        site = {"acres": 40, "parcels": [{"zoning": "EDC-CC"}]}
        return outlook.steps(site, forecast, [{"uses": uses, "traffic": {}}], None, {"planning": "the planners"})["steps"]

    def test_a_permit_use_adds_the_permit_step(self):
        todo = self.steps([{"id": "homes", "label": "Houses", "acres": 10, "fit": "permit"},
                           {"id": "retail", "label": "Shops and restaurants", "acres": 5, "fit": "fits"}])
        step = [s for s in todo if s["what"].startswith("Apply for a conditional use permit")]
        self.assertEqual(len(step), 1)
        self.assertEqual(step[0]["what"], "Apply for a conditional use permit for: houses")
        self.assertIn("EDC-CC", step[0]["why"])

    def test_no_permit_use_no_permit_step(self):
        todo = self.steps([{"id": "retail", "label": "Shops and restaurants", "acres": 5, "fit": "fits"}])
        self.assertFalse([s for s in todo if "conditional use permit" in s["what"]])


class ThroughTheApp(unittest.TestCase):
    def setUp(self):
        patcher = offline()
        patcher.start()
        self.addCleanup(patcher.stop)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = LandPlanner({"menifee": Menifee(), "tinytown": Tinytown()}, self.folder.name, clock=Clock())

    def test_the_zoning_page_gets_the_table_for_the_example_parcel(self):
        land = self.app.land("menifee", EXAMPLE)
        A = land["allowed_uses"]
        self.assertEqual(A["basis"], "table")
        self.assertEqual(A["parts"][0]["table"], "Table 9.140.030-1")
        self.assertEqual(A["labels"]["retail"], "Shops and restaurants")
        self.assertEqual(A["uses"]["retail"]["status"], "outright")
        json.dumps(land)                       # everything sent to the page can be written as JSON

    def test_the_route_sends_it(self):
        status_code, body = route(self.app, "GET", f"/api/cities/menifee/lands/{EXAMPLE}", {}, None)[:2]
        self.assertEqual(status_code, 200)
        self.assertEqual(body["allowed_uses"]["source"]["name"],
                         "City of Menifee Development Code (Menifee Municipal Code, Title 9: Planning and Zoning)")

    def test_the_plan_is_marked_from_the_table(self):
        plan = self.app.plan("menifee", EXAMPLE)
        self.assertEqual(plan["zoning_rules"]["basis"], "table")
        fits = {u["id"]: u["fit"] for u in plan["uses"]}
        self.assertEqual((fits["retail"], fits["apartments"], fits["homes"]), ("fits", "permit", "permit"))

    def test_a_city_without_a_table_says_so_and_never_borrows_menifee_s(self):
        land = self.app.land("tinytown", "100000002")
        self.assertIsNone(land["allowed_uses"])
        plan = self.app.plan("tinytown", "100000002")
        self.assertEqual(plan["zoning_rules"]["basis"], "family")
        self.assertIn("not read for this city", plan["zoning_rules"]["says"])

    def test_a_broken_table_does_not_take_the_page_down(self):
        class Broken(Menifee):
            def allowed_uses(self, code, plan_name="", layer_zone=""):
                raise ValueError("the file is damaged")
        app = LandPlanner({"menifee": Broken()}, self.folder.name, clock=Clock())
        with self.assertLogs(level="WARNING") as log:       # and it is written to the log, so it can be mended
            self.assertIsNone(app.land("menifee", EXAMPLE)["allowed_uses"])
            self.assertEqual(app.plan("menifee", EXAMPLE)["zoning_rules"]["basis"], "family")
        self.assertTrue(any("allowed uses" in line for line in log.output))

    def test_the_forecast_carries_the_marking(self):
        forecast = self.app.forecast("menifee", [EXAMPLE])
        marked = [u for u in forecast["programme"]["uses"] if u.get("fit_words")]
        self.assertTrue(marked)
        for u in marked:
            self.assertIn(u["fit_words"], ("Allowed outright", "Allowed with a conditional use permit"))


if __name__ == "__main__":
    unittest.main()
