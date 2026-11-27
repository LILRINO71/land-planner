"""District projects: the compute routes (/api/districts/projects/<p>/compute/<tool>) that feed a dataset into the
finance engine. Every tool answers in full on the invented sample, nothing is missing, what-ifs are never saved, a
dataset with nothing in it answers with what is missing instead of failing, and for every tool the city view never
receives returns, residual land value by parcel, price floors or disposition pricing. Offline, in a temporary folder."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from landplanner.district import access, compute  # noqa: E402
from landplanner.district.api import DistrictAPI  # noqa: E402
from landplanner.district.schema import AUDIENCE_DENY  # noqa: E402

access.ITERATIONS = 1000
P = "/api/districts/projects/sample-district"
CITY_DENY = AUDIENCE_DENY["city"]
HIDDEN_FROM_CITY = {"landvalue": ["by_parcel", "pricing_tiers"], "proceeds": ["capital_plan", "targets", "waterfall"],
                    "proforma": ["break_even", "tornado"],
                    "strategy": ["conflicts", "decisions", "paced_releases", "retained_parcels", "retained_value"],
                    "scenarios": [], "funding": ["funding_gap"], "fiscal": [], "reconcile": []}


def strict(text):
    def refuse(name):
        raise AssertionError(f"{name} in an answer")
    return json.loads(text, parse_constant=refuse)


def keys(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            keys(v, out)
    return out


def numbers(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for v in obj.values():
            numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            numbers(v, out)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool) and abs(obj) >= 100000:
        out.add(round(float(obj), 2))
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.api = DistrictAPI(self.folder.name)
        self.t = {"administrator": self.sign_in("Admin", "admin-pass-1")}
        for role in ("analyst", "consultant", "viewer_partner", "viewer_city"):
            s, b, _ = self.api.call("POST", "/api/districts/users", token=self.t["administrator"],
                                    body={"name": role, "role": role, "projects": ["sample-district"],
                                          "passcode": f"pass-{role}-1"})
            self.assertEqual(s, 200, b)
            self.t[role] = self.sign_in(role, f"pass-{role}-1")

    def sign_in(self, name, passcode):
        s, b, h = self.api.call("POST", "/api/districts/session", body={"method": "passcode", "name": name,
                                                                        "passcode": passcode})
        self.assertEqual(s, 200, b)
        token = h["Set-Cookie"].split(";")[0].split("=", 1)[1]
        self.api.call("POST", "/api/districts/session/nda", body={"accept": True}, token=token)
        return token

    def compute(self, tool, role="administrator", method="GET", body=None, **query):
        r = self.api.handle(method, f"{P}/compute/{tool}", {k: [str(v)] for k, v in query.items()},
                            {"Cookie": f"lp_district={self.t[role]}",
                             **({"Content-Type": "application/json"} if body is not None else {})},
                            json.dumps(body).encode() if body is not None else b"")
        return r.status, strict(r.body.decode("utf-8"))


class EveryTool(Base):
    def test_every_tool_answers_in_full_on_the_sample_with_nothing_missing(self):
        for tool in compute.TOOLS:
            s, b = self.compute(tool)
            self.assertEqual(s, 200, (tool, b))
            self.assertEqual(b["missing"], [], tool)
            self.assertTrue(b["inputs_used"] and b["formula"], tool)
            self.assertTrue(b["result"] and all(v not in (None, [], {}) for v in b["result"].values()), tool)
            self.assertEqual((b["tool"], b["dataset"], b["version"], b["audience"]), (tool, "baseline", 1, "internal"))
            for i in b["inputs_used"]:
                self.assertTrue(("assumption_id" in i) != ("field" in i), i)
                self.assertIn("provenance", i)
        self.assertEqual(self.api.call("GET", "/api/districts/audit", token=self.t["administrator"],
                                       query={"action": "compute"})[1]["total"], len(compute.TOOLS))

    def test_the_numbers_are_worked_out_not_empty(self):
        lv = self.compute("landvalue")[1]["result"]
        self.assertEqual(lv["by_parcel"]["parcels_not_priced"], 0)
        tiers = {t["parcel"]: t["tiers"] for t in lv["pricing_tiers"]}
        self.assertEqual(tiers["PA-1"]["economic_cost_floor"]["price_usd"], 5000000.0)        # 4,000,000 + 1,000,000
        self.assertEqual(tiers["PA-1"]["minimum_recommended"]["price_usd"], 6250000.0)        # x (1 + 20% + 5%)
        pf = self.compute("proforma")[1]["result"]["full_buildout"]
        self.assertTrue(pf["irr"]["converged"])
        self.assertIsNotNone(pf["equity_multiple"])
        plan = self.compute("proceeds")[1]["result"]["capital_plan"]["strategies"]
        self.assertEqual(set(plan), {"max_cash", "balanced", "max_retention"})
        self.assertNotIn("PA-1", [p["id"] for p in plan["max_retention"]["picks"]], "a critical asset is kept")
        st = self.compute("strategy")[1]["result"]
        self.assertEqual(len(st["decisions"]["parcels"]), 4)
        sc = self.compute("scenarios")[1]["result"]
        self.assertEqual(sorted(sc["unit_scenarios"]["table"]["units_total"]), ["1000_units", "1200_units", "1400_units"])
        self.assertEqual([t["all_met"] for t in sc["phase_triggers"]], [True, False, False])
        fu = self.compute("funding")[1]["result"]
        self.assertEqual(fu["unknown_cost_items"], 1)
        fi = self.compute("fiscal")[1]["result"]
        self.assertGreater(fi["eifd"]["total_increment_usd"], 0)
        rec = {r["id"]: r for r in self.compute("reconcile")[1]["result"]["reconciliations"]}
        self.assertEqual(rec["rec-gla"]["difference"], 10000.0)

    def test_options_and_unknown_tools(self):
        a = self.compute("proceeds", price_basis="minimum_recommended")[1]["result"]
        b = self.compute("proceeds")[1]["result"]
        self.assertLess(a["waterfall"]["gross_total_usd"], b["waterfall"]["gross_total_usd"])
        self.assertEqual(self.compute("proceeds", price_basis="whatever")[0], 400)
        self.assertEqual(self.compute("nonsense")[0], 404)
        s, body = self.compute("proforma", method="POST", body={"options": {"tornado_metric": "yoc_pct"}})
        self.assertEqual((s, body["result"]["tornado"]["metric"]), (200, "yoc_pct"))


class WhatIf(Base):
    def test_a_what_if_changes_the_answer_and_saves_nothing(self):
        before = self.api.call("GET", P + "/datasets/baseline", token=self.t["administrator"])[1]["content"]
        revisions = self.api.call("GET", P + "/revisions", token=self.t["administrator"])[1]["total"]
        base = self.compute("landvalue")[1]
        s, b = self.compute("landvalue", method="POST", body={
            "assumptions": {"FIN-TARGET-PCT-OF-RLV": 90},
            "records": {"land_uses": [{"id": "ret-shops", "rent_per_sf_yr": 44}]}})
        self.assertEqual(s, 200, b)
        self.assertEqual(b["what_if"], ["assumptions/FIN-TARGET-PCT-OF-RLV", "land_uses/ret-shops/rent_per_sf_yr"])
        flagged = [i for i in b["inputs_used"] if i["what_if"]]
        self.assertTrue(any(i.get("assumption_id") == "FIN-TARGET-PCT-OF-RLV" and i["value"] == 90 for i in flagged))
        self.assertNotEqual(b["result"]["pricing_tiers"], base["result"]["pricing_tiers"])
        self.assertEqual(self.api.call("GET", P + "/datasets/baseline", token=self.t["administrator"])[1]["content"],
                         before)
        self.assertEqual(self.api.call("GET", P + "/revisions", token=self.t["administrator"])[1]["total"], revisions)

    def test_a_bad_what_if_is_refused(self):
        for body in ({"assumptions": {"FIN-TARGET-PCT-OF-RLV": "NaN"}}, {"assumptions": {"NOT-A-THING": 1}},
                     {"records": {"land_uses": [{"id": "nope", "rent_per_sf_yr": 1}]}},
                     {"records": {"land_uses": [{"id": "ret-shops", "rent_per_sf_yr": -5}]}},
                     {"records": {"castles": [{"id": "x"}]}}):
            self.assertEqual(self.compute("landvalue", method="POST", body=body)[0], 400, body)
        s, b = self.compute("landvalue", method="POST", body={"assumptions": {"FIN-NET-TO-GROSS-PCT": 85}})
        self.assertEqual(s, 200, b)

    def test_the_city_cannot_change_what_it_cannot_see_nor_widen_its_view(self):
        for body in ({"assumptions": {"FIN-SPONSOR-HURDLE-PCT": 50}}, {"assumptions": {"A-IRR": 1}},
                     {"records": {"parcels": [{"id": "PA-1", "price_floor": 1}]}},
                     {"records": {"land_uses": [{"id": "res-mf", "required_return_pct": 1}]}}):
            self.assertEqual(self.compute("landvalue", "viewer_city", "POST", body)[0], 403, body)
        self.assertEqual(self.compute("fiscal", "viewer_city", "POST", {"assumptions": {"FISCAL-SALES-TAX-PCT": 2}})[0],
                         200)
        self.assertEqual(self.compute("proforma", "viewer_city", audience="internal")[0], 403)


class CityNeverSees(Base):
    def test_for_every_tool_the_city_gets_no_returns_land_values_floors_or_pricing(self):
        for tool in compute.TOOLS:
            s, city = self.compute(tool, "viewer_city")
            self.assertEqual(s, 200, (tool, city))
            self.assertEqual(city["audience"], "city")
            self.assertEqual(city["hidden_parts"], HIDDEN_FROM_CITY[tool], tool)
            bad = {k for k in keys(city) if access.key_tags(k) & CITY_DENY}
            self.assertEqual(bad, set(), tool)
            self.assertEqual([i for i in city["inputs_used"] if set(i.get("tags") or []) & CITY_DENY], [], tool)
            # the large figures the internal answer holds for the hidden parts are nowhere in the city's answer
            internal = self.compute(tool)[1]
            secret = set()
            for part in HIDDEN_FROM_CITY[tool]:
                secret |= numbers(internal["result"][part])
            secret -= self.city_dataset_numbers()          # inputs the city's own view of the dataset already holds
            for part, value in internal["result"].items():  # and figures shared with a part the city may see
                if part not in HIDDEN_FROM_CITY[tool]:
                    secret -= numbers(access.scrub(value, "city"))
            leaked = secret & numbers(city)
            self.assertEqual(leaked, set(), tool)

    def city_dataset_numbers(self):
        if not hasattr(self, "_city_numbers"):
            content = self.api.call("GET", P + "/datasets/baseline", token=self.t["viewer_city"])[1]["content"]
            self._city_numbers = numbers(content)
        return self._city_numbers

    def test_specific_figures_are_absent_and_the_admin_can_preview_the_city_view(self):
        city = json.dumps(self.compute("landvalue", "viewer_city"))
        for figure in ("6250000", "5000000.0", "required_return_pct", "rlv_per_net_ac_usd", "yield_on_cost"):
            self.assertNotIn(figure, city)
        pf = self.compute("proforma", "viewer_city")[1]["result"]["full_buildout"]
        self.assertFalse({"irr", "npv", "equity_multiple", "yield_on_cost"} & set(pf))
        self.assertIn("totals", pf)
        preview = self.compute("strategy", audience="city")[1]
        self.assertEqual((preview["audience"], preview["hidden_parts"]), ("city", HIDDEN_FROM_CITY["strategy"]))

    def test_the_partner_still_sees_returns(self):
        pf = self.compute("proforma", "viewer_partner")[1]["result"]["full_buildout"]
        self.assertIn("irr_pct", pf["irr"])
        self.assertIn("pricing_tiers", self.compute("landvalue", "viewer_partner")[1]["result"])


class Visibility(Base):
    def test_viewers_compute_on_published_versions_only_and_a_consultant_on_their_own_draft(self):
        self.assertEqual(self.compute("landvalue", "viewer_partner", version="draft")[0], 403)
        s, b, _ = self.api.call("POST", P + "/datasets", token=self.t["consultant"],
                                body={"kind": "consultant", "label": "Mine",
                                      "copy_from": {"dataset": "baseline", "version": "published"}})
        mine = b["dataset"]["id"]
        s, b = self.compute("proforma", "consultant", dataset=mine, version="draft")
        self.assertEqual((s, b["dataset"], b["version"]), (200, mine, "draft"))


class NothingToWorkWith(Base):
    def test_an_empty_dataset_answers_every_tool_with_what_is_missing(self):
        a = self.t["administrator"]
        self.assertEqual(self.api.call("POST", "/api/districts/projects", token=a,
                                       body={"id": "empty-district", "name": "Empty District"})[0], 200)
        for tool in compute.TOOLS:
            r = self.api.handle("GET", f"/api/districts/projects/empty-district/compute/{tool}",
                                {"version": ["draft"]}, {"Cookie": f"lp_district={a}"}, b"")
            b = strict(r.body.decode("utf-8"))
            self.assertEqual(r.status, 200, (tool, b))
            self.assertTrue(b["missing"], tool)

    def test_fiscal_names_the_rates_it_needs(self):
        a = self.t["administrator"]
        self.api.call("DELETE", P + "/datasets/baseline/records/assumptions/FISCAL-SALES-TAX-PCT", token=a)
        r = self.api.handle("GET", P + "/compute/fiscal", {"version": ["draft"]}, {"Cookie": f"lp_district={a}"}, b"")
        b = strict(r.body.decode("utf-8"))
        self.assertTrue(any("FISCAL-SALES-TAX-PCT" in m for m in b["missing"]), b["missing"])


if __name__ == "__main__":
    unittest.main()
