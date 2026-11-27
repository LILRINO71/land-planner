"""District projects: CSV and Excel imports checked before anything is written (preview), consultant
submissions that never touch the baseline, the baseline-against-consultant comparison and its threshold, the
register checks and the reconciliation rules. Offline, in a temporary data folder, on the invented sample."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from landplanner.district import access, importer, register, sample  # noqa: E402
from landplanner.district.api import DistrictAPI  # noqa: E402
from landplanner.district.compare import compare  # noqa: E402
from landplanner.district.store import normal_content  # noqa: E402

access.ITERATIONS = 1000           # quick passcode hashing in tests (the real one is much slower on purpose)
P = "/api/districts/projects/sample-district"

GOOD = ("id,label,value,unit,status,provenance,as_of\r\n"
        "A-NEW,New figure,\"1,250\",sf,Baseline,OWNERSHIP ASSUMPTION,2026-05-01\r\n")
MIXED = ("id,label,value,unit,status,provenance,confidence,tags\r\n"
         "A-OK,Fine,100,pct,Consultant,CONSULTANT INPUT,high,\r\n"
         ",,5,sf,Baseline,CALCULATED,,\r\n"
         "A-BAD-NUM,Bad number,12x,sf,Baseline,CALCULATED,,\r\n"
         "A-NAN,Not a number,nan,sf,Baseline,CALCULATED,,\r\n"
         "A-UNIT,Unknown unit,5,furlongs,Baseline,CALCULATED,,\r\n"
         "A-STATUS,Bad status,5,sf,Approved,CALCULATED,,\r\n"
         "A-OK,Same id again,5,sf,Baseline,CALCULATED,,\r\n"
         "A-PCT,Percent,15%,pct,Baseline,MARKET ASSUMPTION,low,returns\r\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.api = DistrictAPI(self.folder.name)
        self.admin = self.sign_in("Admin", "admin-pass-1")
        self.add_user("Ana", "analyst")
        self.add_user("Cora", "consultant", ["sample-district"])
        self.analyst = self.sign_in("Ana", "pass-Ana-123")
        self.consultant = self.sign_in("Cora", "pass-Cora-123")

    def sign_in(self, name, passcode):
        s, b, h = self.api.call("POST", "/api/districts/session", body={"method": "passcode", "name": name,
                                                                        "passcode": passcode})
        self.assertEqual(s, 200, b)
        token = h["Set-Cookie"].split(";")[0].split("=", 1)[1]
        self.assertEqual(self.api.call("POST", "/api/districts/session/nda", body={"accept": True}, token=token)[0], 200)
        return token

    def add_user(self, name, role, projects=()):
        s, b, _ = self.api.call("POST", "/api/districts/users", body={"name": name, "role": role, "projects": list(projects),
                                                                      "passcode": f"pass-{name}-123"}, token=self.admin)
        self.assertEqual(s, 200, b)
        return b["user"]

    def get(self, path, token, **query):
        s, b, _ = self.api.call("GET", path, query=query, token=token)
        self.assertEqual(s, 200, b)
        return b

    def upload(self, token, data, name="a.csv", entity="assumptions"):
        q = {"name": name}
        if entity:
            q["entity"] = entity
        return self.api.call("POST", P + "/imports", query=q, raw=data if isinstance(data, bytes) else data.encode(),
                             token=token)


class Preview(Base):
    def test_every_row_is_checked_and_the_reasons_are_given_before_anything_is_written(self):
        before = self.get(P + "/datasets/baseline", self.admin, version="draft")["content"]
        s, report, _ = self.upload(self.analyst, MIXED)
        self.assertEqual(s, 200, report)
        a = report["entities"]["assumptions"]
        self.assertEqual((a["rows_ok"], a["rows_rejected"]), (2, 6))
        why = {r["row"]: " ".join(r["errors"]) for r in a["rejected"]}
        self.assertIn("label: is required", why[3])
        self.assertIn("“12x” is not a number", why[4])
        self.assertIn("not a number", why[5])
        self.assertIn("furlongs", why[6])
        self.assertIn("is not one of", why[7])
        self.assertIn("also on row 2", why[8])
        pct_row = next(r for r in a["sample"] if r["id"] == "A-PCT")
        self.assertEqual((pct_row["value"], pct_row["tags"]), (15.0, ["returns"]))
        self.assertTrue(report["can_commit"])
        self.assertEqual(self.get(P + "/datasets/baseline", self.admin, version="draft")["content"], before)

    def test_a_column_in_the_wrong_unit_is_refused_and_a_missing_required_column_is_named(self):
        s, report, _ = self.upload(self.analyst, "id,apn,acres [sf],use\r\nPA-9,999-1,20,ret-shops\r\n",
                                   entity="parcels")
        p = report["entities"]["parcels"]
        self.assertTrue(any("is in sf, but acres is kept in acres" in e for e in p["column_errors"]))
        self.assertEqual(p["missing_columns"], ["acres"])
        self.assertEqual((p["rows_ok"], report["can_commit"]), (0, False))
        ok = self.upload(self.analyst, "id,apn,acres [acres],price_floor [usd]\r\nPA-9,999-1,20,\"$1,000,000\"\r\n",
                         entity="parcels")[1]
        self.assertEqual(ok["entities"]["parcels"]["sample"][0]["price_floor"], 1000000.0)

    def test_a_csv_needs_its_template_named_and_rows_without_ids_get_one_from_their_key(self):
        s, b, _ = self.upload(self.analyst, GOOD, entity=None)
        self.assertEqual(s, 400)
        rows = "metric,geography,year,value,unit\r\npopulation,city,2030,120000,people\r\n"
        b = self.upload(self.analyst, rows, entity="market_metrics")[1]
        self.assertEqual(b["entities"]["market_metrics"]["sample"][0]["id"], "population-city-2030")

    def test_a_workbook_is_read_sheet_by_sheet_when_the_excel_reader_is_there(self):
        try:
            from landplanner.district import xlsx
            xlsx.write_workbook
        except (ImportError, AttributeError):
            self.skipTest("xlsx.py is not installed yet")
        data = xlsx.write_workbook({"Assumptions": [["id", "label", "value", "unit", "status", "provenance"],
                                                    ["A-X", "X", 10, "sf", "Baseline", "CALCULATED"]],
                                    "parcels": [["id", "apn", "acres [acres]"], ["PA-X", "999-9", 5]],
                                    "Notes to self": [["anything"]]})
        s, b, _ = self.upload(self.analyst, data, name="pkg.xlsx", entity=None)
        self.assertEqual(s, 200, b)
        self.assertEqual((b["format"], b["rows_ok"], b["skipped_sheets"]), ("xlsx", 2, ["Notes to self"]))
        s, data, h = self.api.call("GET", "/api/districts/templates/workbook.xlsx", token=self.analyst)
        self.assertEqual(s, 200)
        self.assertIn("Dictionary", xlsx.read_workbook(data))

    def test_the_templates_and_dictionary_can_be_downloaded(self):
        s, data, h = self.api.call("GET", "/api/districts/templates/program_lines.csv", token=self.consultant)
        self.assertEqual(s, 200)
        self.assertIn(b"sf [sf]", data)
        self.assertIn("attachment", h["Content-Disposition"])
        t = self.get("/api/districts/templates", self.consultant)
        self.assertIn("provenance", t["columns"]["assumptions"])
        self.assertTrue(any(r[0] == "parcels" and r[1] == "price_floor" and "price_floor" in r[7]
                            for r in t["dictionary"]["rows"]))
        s, data, _ = self.api.call("GET", "/api/districts/templates/dictionary.csv", token=self.analyst)
        self.assertEqual(s, 200)
        self.assertEqual(self.api.call("GET", "/api/districts/templates/nothing.csv", token=self.analyst)[0], 404)


class Commit(Base):
    def test_a_consultant_import_lands_in_its_own_submission_and_never_in_the_baseline(self):
        base_before = self.get(P + "/datasets/baseline", self.admin, version="draft")["content"]
        published_before = self.get(P + "/datasets/baseline", self.admin)["content"]
        iid = self.upload(self.consultant, GOOD)[1]["import_id"]
        s, b, _ = self.api.call("POST", f"{P}/imports/{iid}/commit", body={"target": "baseline"}, token=self.consultant)
        self.assertEqual(s, 403)
        s, b, _ = self.api.call("POST", f"{P}/imports/{iid}/commit", body={}, token=self.consultant)
        self.assertEqual(s, 200, b)
        sub = b["dataset"]
        self.assertEqual((sub["kind"], sub["owner"], b["imported"]), ("consultant", self.user_id("Cora"),
                                                                       {"assumptions": 1}))
        mine = self.get(f"{P}/datasets/{sub['id']}", self.consultant, version="draft")["content"]["entities"]
        self.assertIn("A-NEW", [x["id"] for x in mine["assumptions"]])
        self.assertGreater(len(mine["assumptions"]), 1, "the submission starts from the published baseline")
        self.assertEqual(self.get(P + "/datasets/baseline", self.admin, version="draft")["content"], base_before)
        self.assertEqual(self.get(P + "/datasets/baseline", self.admin)["content"], published_before)
        # used once
        self.assertEqual(self.api.call("POST", f"{P}/imports/{iid}/commit", body={}, token=self.consultant)[0], 404)

    def test_an_analyst_imports_into_the_baseline_draft_and_another_user_cannot_commit_their_preview(self):
        iid = self.upload(self.analyst, GOOD)[1]["import_id"]
        self.assertEqual(self.api.call("POST", f"{P}/imports/{iid}/commit", body={}, token=self.consultant)[0], 403)
        s, b, _ = self.api.call("POST", f"{P}/imports/{iid}/commit", body={"target": "baseline", "reason": "memo"},
                                token=self.analyst)
        self.assertEqual(s, 200, b)
        draft = self.get(P + "/datasets/baseline", self.admin, version="draft")["content"]["entities"]["assumptions"]
        self.assertIn("A-NEW", [x["id"] for x in draft])
        rev = self.get(P + "/revisions", self.admin, entity="assumptions", id="A-NEW")["revisions"][0]
        self.assertEqual((rev["reason"], rev["classification"], rev["name"]), ("memo", "OWNERSHIP ASSUMPTION", "Ana"))

    def user_id(self, name):
        return next(u["id"] for u in self.get("/api/districts/users", self.admin)["users"] if u["name"] == name)


class Comparison(Base):
    def other(self):
        return next(d["id"] for d in self.get(P + "/datasets", self.admin)["datasets"] if d["kind"] == "consultant")

    def test_changes_above_ten_percent_are_flagged_and_the_threshold_can_be_set(self):
        out = self.get(P + "/compare", self.analyst, other=self.other())
        values = {c["id"]: c for c in out["entities"]["assumptions"]["changed"] if c["field"] == "value"}
        self.assertTrue(values["A-RET-GLA"]["flagged"])             # 180,000 -> 200,000: +11.1%
        self.assertFalse(values["A-RET-RENT"]["flagged"])           # 36 -> 37: +2.8%
        self.assertAlmostEqual(values["A-RET-GLA"]["change_pct"], 11.111, places=2)
        self.assertEqual((out["threshold_pct"], out["flagged"]), (10.0, 1))
        self.assertEqual(self.get(P + "/compare", self.analyst, other=self.other(), threshold=2)["flagged"], 2)
        self.api.call("POST", P, body={"settings": {"compare_threshold_pct": 20}}, token=self.admin)
        self.assertEqual(self.get(P + "/compare", self.analyst, other=self.other())["flagged"], 0)

    def test_a_change_from_zero_is_flagged_and_never_divides_by_zero(self):
        base = normal_content({"entities": {"assumptions": [{"id": "A", "value": 0}, {"id": "B", "value": 5}]}})
        other = normal_content({"entities": {"assumptions": [{"id": "A", "value": 3}, {"id": "C", "value": 1}]}})
        out = compare(base, other)
        change = out["entities"]["assumptions"]["changed"][0]
        self.assertEqual((change["change_pct"], change["flagged"]), (None, True))
        self.assertEqual((out["entities"]["assumptions"]["added"], out["entities"]["assumptions"]["removed"]), (["C"], ["B"]))


class Register(unittest.TestCase):
    def content(self):
        return copy.deepcopy(sample.content())

    def test_a_figure_resolves_to_its_register_entry_in_its_unit(self):
        c = self.content()
        self.assertEqual(register.value(c, "A-RET-GLA"), 180000)
        self.assertEqual(register.display(register.figure(c, "A-RET-RENT")), "$36.00/SF/yr")
        self.assertEqual(register.display(register.figure(c, "A-RET-MARKET")), "220,000-240,000 SF")
        self.assertIsNone(register.figure(c, "A-NOPE"))

    def test_the_reconciliation_gives_the_difference_and_its_explanation(self):
        recs = {r["id"]: r for r in register.reconciliations(self.content())}
        gla = recs["rec-gla"]
        self.assertEqual((gla["total"], gla["parts_total"], gla["difference"]), (180000, 170000.0, 10000.0))
        self.assertAlmostEqual(gla["difference_pct"], 5.556, places=2)
        self.assertTrue(gla["explained"] and "pad buildings" in gla["explanation"])
        self.assertTrue(recs["rec-other"]["within_tolerance"])

    def test_checks_list_figures_with_no_register_entry_and_unexplained_differences(self):
        c = self.content()
        c["entities"]["reconciliations"][0]["explanation"] = ""
        c["entities"]["sections"].append({"id": "s-x", "module": "m", "kind": "narrative", "body": "About $5 million."})
        modules = copy.deepcopy(sample.MODULES)
        modules[0]["cards"].append({"id": "ghost", "label": "Ghost", "assumption": "A-GHOST"})
        out = register.checks(c, modules)
        self.assertIn("A-GHOST", [u["assumption"] for u in out["unregistered"]])
        self.assertIn("s-x", [u["id"] for u in out["uncited"]])
        self.assertEqual(out["unexplained_reconciliations"], ["rec-gla"])
        self.assertFalse(out["ok"])
        self.assertTrue(register.checks(self.content(), sample.MODULES)["ok"])

    def test_a_reconciliation_with_a_missing_total_says_so_and_holds_no_nan(self):
        c = self.content()
        c["entities"]["reconciliations"] = [{"id": "r", "label": "x", "total": "A-NONE", "parts": ["A-OFF-SF"]}]
        r = register.reconciliations(c)[0]
        self.assertEqual((r["difference"], r["difference_pct"], r["explained"]), (None, None, False))
        self.assertIn("A-NONE", r["missing"])


class ImporterUnits(unittest.TestCase):
    def test_header_units_are_read_in_brackets_or_parentheses(self):
        tables = {"program_lines": [["id", "use", "phase", "scenario", "sf (sf)", "base_rent_usd_sf_yr [usd_per_sf_yr]"],
                                    ["x", "ret", "1", "base", "1000", "$30"]]}
        report, clean = importer.preview_tables(tables)
        self.assertEqual(clean["program_lines"][0]["base_rent_usd_sf_yr"], 30.0)
        self.assertEqual(report["rows_rejected"], 0)


if __name__ == "__main__":
    unittest.main()
