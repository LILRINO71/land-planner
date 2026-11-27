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
HIDDEN_FROM_CITY = {"landvalue": ["blocks", "by_parcel", "comparison", "pricing_tiers"],
                    "proceeds": ["by_basis", "capital_plan", "stated_plan", "targets", "waterfall"],
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
        plan = self.compute("proceeds", basis="residual")[1]["result"]["capital_plan"]["strategies"]
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
        a = self.compute("proceeds", basis="residual", price_basis="minimum_recommended")[1]["result"]
        b = self.compute("proceeds", basis="residual")[1]["result"]
        self.assertLess(a["waterfall"]["gross_total_usd"], b["waterfall"]["gross_total_usd"])
        self.assertEqual(self.compute("proceeds", price_basis="whatever")[0], 400)
        self.assertEqual(self.compute("nonsense")[0], 404)
        s, body = self.compute("proforma", method="POST", body={"options": {"tornado_metric": "yoc_pct"}})
        self.assertEqual((s, body["result"]["tornado"]["metric"]), (200, "yoc_pct"))


class Blocks(Base):
    """The four invented sample blocks: B-1 10 ac at $25/SF (stub $250,000), B-2 30 ac at $15-20/SF (stub not
    known), both sold; B-3 8 ac at $40/SF held (core); B-4 12 ac at $20/SF in a JV."""
    RATE = 0.03 + 0.0075 + 0.001                     # brokerage 3%, closing 0.75%, transfer tax 0.1% (sample register)

    def test_stated_basis_proceeds_are_the_hand_sum(self):
        s, b = self.compute("proceeds")
        r = b["result"]
        self.assertEqual((s, r["basis_used"], r["sold_as"]), (200, "stated", "blocks"))
        b1_gross, b2_gross = 10 * 43560 * 25, 30 * 43560 * 17.5          # B-2 at the middle of its range
        b1_net = b1_gross * (1 - self.RATE) - 1000 - 250000               # less the recording fee and its stub
        b2_net = b2_gross * (1 - self.RATE) - 1000                        # its stub is not known: not taken off
        plan = r["stated_plan"]
        self.assertEqual((plan["sold"], plan["kept"]), (["B-1", "B-2"], ["B-3", "B-4"]))
        self.assertEqual((plan["net_acres_sold"], plan["net_acres_kept"]), (40.0, 20.0))
        self.assertAlmostEqual(plan["gross_usd"], b1_gross + b2_gross, places=2)
        self.assertAlmostEqual(plan["net_usd"], b1_net + b2_net, places=2)
        month18, month48 = plan["against_targets"]
        self.assertAlmostEqual(month18["cumulative_net_usd"], b1_net + b2_net, places=2)
        self.assertTrue(month18["met"])
        self.assertFalse(month48["met"])
        self.assertAlmostEqual(month48["shortfall_usd"], 35000000 - (b1_net + b2_net), places=2)
        self.assertEqual([x["phase"] for x in plan["by_phase"]], ["1"])
        self.assertEqual([m["month"] for m in plan["by_close_month"]], [12, 15])

    def test_an_unknown_stub_stays_unknown_in_the_totals(self):
        r = self.compute("proceeds")[1]["result"]
        self.assertTrue(r["stated_plan"]["net_is_upper_bound"])
        self.assertEqual(r["stated_plan"]["unknown_stubs"], 1)
        self.assertEqual(r["waterfall"]["unknown_deductions"], 1)
        self.assertTrue(r["waterfall"]["net_total_is_upper_bound"])
        s, b = self.compute("proceeds", method="POST", body={"records": {"blocks": [{"id": "B-2", "stub_cost_usd": 0}]}})
        self.assertEqual(s, 200, b)
        self.assertFalse(b["result"]["stated_plan"]["net_is_upper_bound"])

    def test_both_bases_side_by_side_when_both_exist(self):
        lv = self.compute("landvalue")[1]["result"]
        self.assertEqual(lv["basis_used"], "stated")
        units = {u["id"]: u for u in lv["comparison"]["units"]}
        self.assertEqual(set(units), {"B-1", "B-2", "B-3", "B-4", "PA-1", "PA-2"})    # blocks, and parcel target prices
        b1 = units["B-1"]
        self.assertEqual(b1["stated_usd"], 10 * 43560 * 25)
        self.assertAlmostEqual(b1["difference_usd"], b1["stated_usd"] - b1["residual_usd"], places=2)
        self.assertEqual(units["PA-1"]["stated_usd"], 12000000)
        tiers = {x["parcel"]: x for x in lv["pricing_tiers"]}
        self.assertEqual(tiers["PA-1"]["tiers"]["target_market"]["price_usd"], 12000000.0, "the stated target price")
        by = self.compute("proceeds")[1]["result"]["by_basis"]
        self.assertEqual((by["stated"]["sold_as"], by["residual"]["sold_as"]), ("blocks", "parcels"))
        self.assertAlmostEqual(by["difference_usd"], by["stated"]["gross_usd"] - by["residual"]["gross_usd"], places=2)
        res = self.compute("landvalue", basis="residual")[1]["result"]
        self.assertEqual(res["basis_used"], "residual")
        self.assertNotEqual({x["parcel"]: x for x in res["pricing_tiers"]}["PA-1"]["tiers"]["target_market"]["price_usd"],
                            12000000.0)

    def test_core_blocks_are_kept_by_max_retention_and_flagged_when_sold(self):
        plan = self.compute("proceeds")[1]["result"]["capital_plan"]["strategies"]
        self.assertNotIn("B-3", [x["id"] for x in plan["max_retention"]["picks"]])
        for name, s in plan.items():
            sold_core = [c["parcel_id"] for c in s["critical_asset_conflicts"]]
            self.assertEqual("B-3" in [x["id"] for x in s["picks"]], "B-3" in sold_core, name)
        self.assertIn("B-3", [x["id"] for x in plan["max_cash"]["picks"]], "the sample shows a flagged sale")

    def test_strategy_decides_per_block_and_inputs_cite_the_blocks_and_their_assumptions(self):
        st = self.compute("strategy")[1]
        self.assertEqual(st["result"]["decided_for"], "blocks")
        self.assertEqual([d["id"] for d in st["result"]["decisions"]["parcels"]], ["B-1", "B-2", "B-3", "B-4"])
        used = self.compute("proceeds")[1]["inputs_used"]
        fields = {u.get("field") for u in used} | {u.get("assumption_id") for u in used}
        self.assertTrue({"blocks/B-1/price_per_sf", "blocks/B-2/price_per_sf_low", "A-RET-RENT", "A-RES-UNITS"} <= fields)

    def test_the_city_never_sees_block_prices_or_proceeds(self):
        content = self.api.call("GET", P + "/datasets/baseline", token=self.t["viewer_city"])[1]["content"]
        blocks = content["entities"]["blocks"]
        self.assertEqual(len(blocks), 4)
        for b in blocks:
            self.assertFalse({"price_per_sf", "price_per_sf_low", "price_per_sf_high", "close_month",
                              "strategy_inputs"} & set(b), b)
        figures = {float(10 * 43560 * 25), 30 * 43560 * 17.5}
        for tool in ("landvalue", "proceeds", "strategy", "funding"):
            city = self.compute(tool, "viewer_city")[1]
            self.assertFalse(figures & numbers(city), tool)
            self.assertFalse([u for u in city["inputs_used"] if "price_per_sf" in str(u.get("field"))], tool)
        self.assertEqual(self.compute("proceeds", "viewer_city", "POST",
                                      {"records": {"blocks": [{"id": "B-1", "price_per_sf": 99}]}})[0], 403)

    def test_parcels_are_not_named_as_left_out_when_the_plan_runs_on_blocks(self):
        from landplanner.district import sample
        from landplanner.district.store import normal_content
        import copy
        c = normal_content(copy.deepcopy(sample.content()))
        c["entities"]["land_uses"] = [u for u in c["entities"]["land_uses"] if u["id"] not in ("res-mf", "res-sfd")]
        for x in c["entities"]["parcels"]:
            x.pop("target_price", None)
        left_out = lambda a: [m for m in a["missing"] if "left out of the sale plan" in m]          # noqa: E731
        on_blocks = compute.run("proceeds", c)
        self.assertEqual(on_blocks["result"]["sold_as"], "blocks")
        self.assertEqual(left_out(on_blocks), [])
        self.assertEqual(left_out(compute.run("funding", c)), [])
        on_parcels = compute.run("proceeds", c, {"basis": "residual"})
        self.assertEqual(on_parcels["result"]["sold_as"], "parcels")
        self.assertTrue(left_out(on_parcels), "a plan that really runs on parcels still names the unpriced ones")
        c["entities"]["blocks"] = []
        self.assertTrue(left_out(compute.run("proceeds", c)))

    def test_asking_for_stated_prices_where_there_are_none_falls_back_and_says_so(self):
        from landplanner.district import sample
        from landplanner.district.store import normal_content
        import copy
        c = normal_content(copy.deepcopy(sample.content()))          # never change the module's own lists
        c["entities"]["blocks"] = []
        for x in c["entities"]["parcels"]:
            x.pop("target_price", None)
        a = compute.run("proceeds", c, {"basis": "stated"})
        self.assertEqual((a["result"]["basis_used"], a["result"]["sold_as"]), ("residual", "parcels"))
        self.assertTrue(any("residual basis was used" in m for m in a["missing"]))
        self.assertNotIn("by_basis", a["result"])
        self.assertEqual(compute.run("landvalue", c)["result"]["basis_used"], "residual")


class PlainWords(Base):
    SNAKE = compute._SNAKE

    def sentences(self, obj, out=None):
        out = [] if out is None else out
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "why" and isinstance(v, str):
                    out.append(v)
                else:
                    self.sentences(v, out)
        elif isinstance(obj, list):
            for v in obj:
                self.sentences(v, out)
        return out

    def test_no_missing_or_why_sentence_shows_a_field_name(self):
        seen = 0
        for tool in compute.TOOLS:
            for role in ("administrator", "viewer_city"):
                b = self.compute(tool, role)[1]
                for text in b["missing"] + self.sentences(b["result"]):
                    seen += 1
                    self.assertIsNone(self.SNAKE.search(text), (tool, text))
        self.assertGreater(seen, 0, "the sample's ground lease sentences are checked")
        text = " ".join(self.sentences(self.compute("strategy")[1]["result"]))
        self.assertIn("A ground lease needs a rent yield on land value.", text)

    def test_missing_sentences_of_a_bare_dataset_are_plain_too(self):
        a = self.t["administrator"]
        self.api.call("POST", "/api/districts/projects", token=a, body={"id": "bare-district", "name": "Bare District"})
        for tool in compute.TOOLS:
            r = self.api.handle("GET", f"/api/districts/projects/bare-district/compute/{tool}",
                                {"version": ["draft"]}, {"Cookie": f"lp_district={a}"}, b"")
            for m in strict(r.body.decode("utf-8"))["missing"]:
                self.assertIsNone(self.SNAKE.search(m), (tool, m))
        self.assertEqual(compute.plain("Parcel PA-1 has no cost_items (its cost basis), see FIN-NET-TO-GROSS-PCT."),
                         "Parcel PA-1 has no cost items (its cost basis), see FIN-NET-TO-GROSS-PCT.")


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
