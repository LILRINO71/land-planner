"""The district finance engine (landplanner/district/finance*.py), part 1: shared helpers, residual land value, the four
pricing tiers, the gross-to-net waterfall, the capital target solver, retained land and the reconciliation helper.

Every input is invented and round, and every expected number is worked out by hand in the comment above its test. No
fixtures, no files, no network. Part 2 (test_district_finance_proforma.py) covers lease-up, the pro forma, break-even and
scenarios; part 3 (test_district_finance_decision.py) covers hold/sell/JV/ground lease, infrastructure and fiscal figures.
"""
import math
import unittest

import support  # noqa: F401  (puts the project folder on the import path)
from landplanner.district import finance as F
from landplanner.district import finance_common as C
from landplanner.district import finance_uses as U


# ---------------------------------------------------------------- hand-made inputs (shared with the other two files)

def apartments():
    """20 units a net acre, 1,000 SF each, $2,000 a month, 5% empty, 35% of income spent on running it, 5% cap, 15% profit on cost."""
    return {"label": "Apartments", "density": {"units_per_net_ac": 20, "sf_per_unit": 1000},
            "revenue": {"type": "rent_per_unit_mo", "rent_per_unit_mo": 2000, "vacancy_pct": 5, "opex_pct_of_income": 35},
            "cost_line_items": {"site_work": 100000, "building_shell": 200, "hard_contingency": 5}, "cap_rate_pct": 5, "required_return_pct": 15}


def townhomes():
    """16 homes a net acre, 1,600 SF each, sold at $500,000, 3% selling cost, 15% profit on cost."""
    return {"label": "Townhomes", "density": {"units_per_net_ac": 16, "sf_per_unit": 1600},
            "revenue": {"type": "per_unit_sale", "price_per_unit": 500000}, "sales_cost_pct": 3,
            "cost_line_items": {"site_work": 150000, "building_shell": 150}, "required_return_pct": 15}


def shops():
    """Floor area ratio 0.25, $40 per SF a year NNN, 3% of income not recovered, 6% cap, 15% profit on cost."""
    return {"label": "Shops", "density": {"far": 0.25},
            "revenue": {"type": "rent_per_sf_yr", "rent_per_sf_yr": 40, "vacancy_pct": 0, "opex_pct_of_income": 3},
            "cost_line_items": {"site_work": 200000, "building_shell": 250}, "cap_rate_pct": 6, "required_return_pct": 15}


def income_use(units_per_ac=10, rent=1500, cost_per_unit=150000, cap=5.5):
    """A small income use for the many-uses test."""
    return {"label": "Use", "density": {"units_per_net_ac": units_per_ac, "sf_per_unit": 1000},
            "revenue": {"type": "rent_per_unit_mo", "rent_per_unit_mo": rent, "vacancy_pct": 5, "opex_pct_of_income": 30},
            "cost_line_items": [{"id": "all_in", "basis": "per_unit", "amount": cost_per_unit}], "cap_rate_pct": cap, "required_return_pct": 12}


def library():
    return {"apartments": apartments(), "townhomes": townhomes(), "shops": shops()}


def finite_everywhere(obj):
    """True if no number anywhere in an answer is NaN or infinite."""
    if isinstance(obj, float):
        return math.isfinite(obj)
    if isinstance(obj, dict):
        return all(finite_everywhere(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return all(finite_everywhere(v) for v in obj)
    return True


class Near(unittest.TestCase):
    def near(self, a, b, places=2):
        self.assertIsNotNone(a)
        self.assertAlmostEqual(a, b, places=places)


# ---------------------------------------------------------------- helpers

class SafeNumbers(unittest.TestCase):
    def test_numbers_and_strings_are_read_and_junk_is_none(self):
        self.assertEqual(C.num("$1,200"), 1200.0)
        self.assertEqual(C.num("3.5%"), 3.5)
        for junk in (None, "abc", float("nan"), float("inf"), True, {}, []):
            self.assertIsNone(C.num(junk))

    def test_division_by_zero_or_a_missing_number_is_none_not_an_error(self):
        self.assertIsNone(C.div(1, 0))
        self.assertIsNone(C.div(None, 2))
        self.assertEqual(C.div(10, 4), 2.5)

    def test_clean_turns_infinity_into_none_everywhere(self):
        out = C.clean({"a": float("inf"), "b": [float("nan"), 1.0], "c": (1, float("-inf"))})
        self.assertEqual(out, {"a": None, "b": [None, 1.0], "c": [1, None]})

    def test_an_absurd_number_gives_a_failed_answer_not_a_crash(self):
        out = F.retained_land_value(1e308, 1e308, 0, 1, 15)
        self.assertTrue(finite_everywhere(out))


class RateOfReturn(Near):
    # -100 now and 110 in a year: 10% exactly.
    def test_one_year_ten_percent(self):
        r = C.irr([-100, 110])
        self.assertTrue(r["converged"])
        self.assertEqual(r["method"], "newton")
        self.near(r["irr_pct"], 10.0, 6)

    # -100, 0, 0, 133.1 : 100 x 1.1^3 = 133.1, so 10% over three years.
    def test_three_years_ten_percent(self):
        self.near(C.irr([-100, 0, 0, 133.1])["irr_pct"], 10.0, 6)

    def test_bisection_takes_over_when_newton_is_not_allowed_enough_steps(self):
        r = C.irr([-100, 110], guess=0.5, max_iter=1)
        self.assertTrue(r["converged"])
        self.assertEqual(r["method"], "bisection")
        self.near(r["irr_pct"], 10.0, 6)

    def test_all_outflows_cannot_have_a_rate_and_say_why(self):
        r = C.irr([-100, -5, -1])
        self.assertFalse(r["converged"])
        self.assertIsNone(r["irr"])
        self.assertIn("inflow", r["why"])

    # -100, +230, -132 has two answers, 10% and 20% (the 1.1 and 1.2 roots of 100x^2 - 230x + 132 = 0): the flag shows two sign changes.
    def test_two_sign_changes_are_reported_and_a_true_root_is_returned(self):
        r = C.irr([-100, 230, -132])
        self.assertEqual(r["sign_changes"], 2)
        self.assertTrue(r["converged"])
        self.assertTrue(abs(r["irr_pct"] - 10.0) < 1e-4 or abs(r["irr_pct"] - 20.0) < 1e-4)

    def test_empty_and_zero_flows_do_not_raise(self):
        self.assertFalse(C.irr([])["converged"])
        self.assertFalse(C.irr([0, 0, 0])["converged"])

    # 100 / 1.1 + 100 / 1.21 = 90.909 + 82.645 = 173.554
    def test_net_present_value(self):
        self.near(C.npv(0.10, [0, 100, 100]), 173.5537, 3)
        self.assertIsNone(C.npv(-1.0, [1, 2]))

    def test_equity_multiple_is_money_back_over_money_in(self):
        self.near(C.equity_multiple([-100, -50, 30, 270]), 2.0)
        self.assertIsNone(C.equity_multiple([10, 20]))

    def test_cash_flow_metrics_for_a_simple_stream(self):
        m = F.cash_flow_metrics([-100, 0, 0, 133.1], 10.0, base_year=2030)
        self.near(m["irr"]["irr_pct"], 10.0, 3)
        self.near(m["npv_usd"], 0.0, 2)
        self.assertEqual(m["flows"][3]["year"], 2033)
        self.assertEqual(m["payback_year_index"], 3)


# ---------------------------------------------------------------- the library and the line items

class CostLineItems(Near):
    def test_the_default_list_has_fifteen_items_with_no_amounts(self):
        items = F.default_cost_line_items()
        self.assertEqual(len(items), 15)
        self.assertTrue(all(i["amount"] is None for i in items))
        self.assertEqual(len({i["id"] for i in items}), 15)

    # One net acre of apartments: site work $100,000 (per net acre) + shell $200 x 20,000 SF = $4,000,000 (hard, direct)
    # + 5% contingency of the direct hard cost: 0.05 x 4,100,000 = 205,000. Total 4,305,000.
    def test_pricing_a_list_by_basis(self):
        r = U.line_item_costs(apartments()["cost_line_items"], net_ac=1, building_sf=20000, units=20)
        self.near(r["total_usd"], 4305000.0)
        self.assertEqual(r["unknown_items"], 0)

    # per_unit: 20 x 1,000 = 20,000; lump_sum: 5,000; pct_of_prior: 10% of everything above it (25,000) = 2,500.
    def test_percent_of_prior_items_use_what_is_above_them(self):
        items = [{"id": "a", "basis": "per_unit", "amount": 1000}, {"id": "b", "basis": "lump_sum", "amount": 5000},
                 {"id": "fin", "basis": "pct_of_prior", "amount": 10}]
        self.near(U.line_item_costs(items, units=20)["total_usd"], 27500.0)

    def test_an_unknown_amount_or_quantity_is_counted_and_never_made_zero(self):
        items = [{"id": "a", "basis": "per_unit", "amount": 1000}, {"id": "b", "basis": "per_building_sf", "amount": 10}, {"id": "c", "amount": None}]
        r = U.line_item_costs(items, units=5)             # no building SF is known, and c has no amount
        self.assertEqual(r["unknown_items"], 2)
        self.assertTrue(r["is_partial"])
        self.near(r["total_usd"], 5000.0)
        self.assertIsNone(r["rows"][1]["cost_usd"])

    def test_a_zero_amount_is_zero_even_when_the_quantity_is_not_known(self):
        r = U.line_item_costs([{"id": "a", "basis": "per_unit", "amount": 0}], units=None)
        self.assertEqual(r["unknown_items"], 0)

    def test_library_check_names_what_is_missing(self):
        out = F.check_land_use_library({"x": {"revenue": {"type": "rent_per_unit_mo"}}})
        self.assertFalse(out["ok"])
        self.assertTrue(any("cost" in i for i in out["issues"]))
        self.assertTrue(any("cap rate" in i for i in out["issues"]))
        self.assertTrue(F.check_land_use_library(library())["ok"])


# ---------------------------------------------------------------- residual land value

class ResidualLandValue(Near):
    # Apartments, 1 net acre: 20 units; income 20 x 2,000 x 12 = 480,000; less 5% empty = 456,000; less 35% costs = NOI 296,400;
    # value = 296,400 / 0.05 = 5,928,000; cost 4,305,000; RLV = 5,928,000 / 1.15 - 4,305,000 = 5,154,782.61 - 4,305,000 = 849,782.61.
    def test_apartment_residual_by_hand(self):
        out = F.residual_land_value_by_use({"apartments": apartments()})
        base = out["uses"][0]["scenarios"]["base"]
        self.near(base["noi_usd_yr"], 296400.0)
        self.near(base["value_on_completion_usd"], 5928000.0)
        self.near(base["development_cost_usd"], 4305000.0)
        self.near(base["rlv_usd"], 849782.61)
        self.near(base["rlv_per_net_ac_usd"], 849782.61)
        self.near(base["rlv_per_net_sf_usd"], 19.5083, 3)      # 849,782.61 / 43,560
        self.near(base["yield_on_cost_pct"], 6.885, 3)         # 296,400 / 4,305,000
        self.assertTrue(base["feasible_now"])

    # Townhomes: 16 x 500,000 = 8,000,000; 3% selling cost leaves 7,760,000; cost 150,000 + 150 x 25,600 SF = 3,990,000;
    # RLV = 7,760,000 / 1.15 - 3,990,000 = 6,747,826.09 - 3,990,000 = 2,757,826.09.
    def test_for_sale_residual_by_hand(self):
        base = F.residual_land_value_by_use({"townhomes": townhomes()})["uses"][0]["scenarios"]["base"]
        self.near(base["rlv_usd"], 2757826.09)
        self.assertIsNone(base["noi_usd_yr"])

    # Shops: FAR 0.25 gives 10,890 SF an acre; income 10,890 x 40 = 435,600; 3% not recovered: NOI 422,532; value 422,532 / 0.06 = 7,042,200;
    # cost 200,000 + 250 x 10,890 = 2,922,500; RLV = 7,042,200 / 1.15 - 2,922,500 = 6,123,652.17 - 2,922,500 = 3,201,152.17.
    def test_shops_on_a_floor_area_ratio_by_hand(self):
        base = F.residual_land_value_by_use({"shops": shops()})["uses"][0]["scenarios"]["base"]
        self.near(base["rlv_usd"], 3201152.17)
        self.near(base["building_sf"], 10890.0)

    def test_low_is_below_base_and_base_is_below_high(self):
        s = F.residual_land_value_by_use(library())["uses"][0]["scenarios"]
        self.assertLess(s["low"]["rlv_usd"], s["base"]["rlv_usd"])
        self.assertLess(s["base"]["rlv_usd"], s["high"]["rlv_usd"])

    # Gross acres: 100 net acres in 125 gross is 80%, so 849,782.61 per net acre is 679,826.09 per gross acre.
    def test_per_gross_acre_follows_the_net_to_gross_ratio(self):
        base = F.residual_land_value_by_use({"apartments": apartments()}, net_to_gross_pct=80)["uses"][0]["scenarios"]["base"]
        self.near(base["rlv_per_gross_ac_usd"], 679826.09)

    def test_eight_or_more_uses_are_supported_and_ranked_by_the_library_not_the_code(self):
        lib = {f"use_{i}": income_use(units_per_ac=10 + 2 * i, rent=1400 + 100 * i, cost_per_unit=150000) for i in range(9)}
        out = F.residual_land_value_by_use(lib)
        self.assertEqual(len(out["uses"]), 9)
        values = [out["uses"][int(i.split("_")[1])]["scenarios"]["base"]["rlv_per_net_ac_usd"] for i in out["ranking"]]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertTrue(finite_everywhere(out))

    def test_custom_scenarios_replace_the_default_three(self):
        out = F.residual_land_value_by_use({"apartments": apartments()}, scenarios={"base": {}, "rents_up": {"revenue_pct": 10}})
        self.assertEqual(set(out["uses"][0]["scenarios"]), {"base", "rents_up"})
        # rents +10%: NOI 326,040; value 6,520,800; RLV = 6,520,800 / 1.15 - 4,305,000 = 5,670,260.87 - 4,305,000 = 1,365,260.87
        self.near(out["uses"][0]["scenarios"]["rents_up"]["rlv_usd"], 1365260.87)

    def test_a_negative_residual_is_reported_not_hidden(self):
        weak = apartments()
        weak["revenue"]["rent_per_unit_mo"] = 1000
        base = F.residual_land_value_by_use({"x": weak})["uses"][0]["scenarios"]["base"]
        self.assertLess(base["rlv_usd"], 0)
        self.assertFalse(base["feasible_now"])

    def test_a_use_without_a_cap_rate_or_cost_gives_none_and_a_reason(self):
        bad = apartments()
        del bad["cap_rate_pct"]
        base = F.residual_land_value_by_use({"x": bad, "y": {"revenue": apartments()["revenue"]}})["uses"]
        self.assertIsNone(base[0]["scenarios"]["base"]["rlv_usd"])
        self.assertIn("cap rate", base[0]["scenarios"]["base"]["why"])
        self.assertIn("cost", base[1]["scenarios"]["base"]["why"])

    def test_an_unknown_cost_item_marks_the_residual_partial(self):
        ud = apartments()
        ud["cost_line_items"] = [{"id": "site_work", "amount": 100000}, {"id": "building_shell", "amount": None}]
        base = F.residual_land_value_by_use({"x": ud})["uses"][0]["scenarios"]["base"]
        self.assertTrue(base["cost_is_partial"])
        self.assertEqual(base["cost_unknown_items"], 1)

    def test_the_answer_carries_formula_assumptions_and_the_not_an_appraisal_note(self):
        out = F.residual_land_value_by_use({"apartments": apartments()})
        self.assertTrue(out["formula"])
        self.assertIn("net_to_gross_pct", out["assumptions"])
        self.assertIn("not an appraisal", out["disclaimer"])

    def test_zero_and_negative_acres_do_not_raise(self):
        for acres in (0, -3, None):
            out = F.residual_land_value_by_use({"apartments": apartments()}, net_ac=acres)
            self.assertIsNone(out["uses"][0]["scenarios"]["base"]["rlv_usd"])
            self.assertTrue(finite_everywhere(out))


class ResidualByParcel(Near):
    def parcels(self):
        return [{"id": "P1", "gross_ac": 12.5, "net_ac": 10, "candidate_uses": ["apartments", "townhomes"], "use": "apartments"},
                {"id": "P2", "gross_ac": 4, "net_ac": 2.5}]

    # P1 on apartments: 10 net acres x 849,782.61 = 8,497,826.09; per gross acre = 8,497,826.09 / 12.5 = 679,826.09.
    # Townhomes beat apartments on P1 (2,757,826.09 an acre) so the best use is townhomes, but the assigned use is apartments.
    def test_parcel_residual_best_and_assigned_use(self):
        out = F.residual_land_value_by_parcel(self.parcels(), library())
        p1 = out["parcels"][0]
        self.near(p1["uses"]["apartments"]["base"]["rlv_usd"], 8497826.09)
        self.near(p1["uses"]["apartments"]["base"]["rlv_per_gross_ac_usd"], 679826.09)
        self.near(p1["uses"]["apartments"]["base"]["rlv_per_net_sf_usd"], 19.5083, 3)
        self.assertEqual(p1["best_use"], "townhomes")
        self.assertEqual(p1["totalled_use"], "apartments")

    # Totals: P1 on its assigned apartments 8,497,826.09; P2 has no assigned use, so its best one, the shops (2.5 x 3,201,152.17 = 8,002,880.43,
    # ahead of townhomes at 2,757,826.09 an acre): sum 16,500,706.52.
    def test_totals_use_the_assigned_use_else_the_best_use(self):
        out = F.residual_land_value_by_parcel(self.parcels(), library())
        self.near(out["totals_usd"]["base"], 16500706.52)
        self.assertEqual(out["parcels"][1]["best_use"], "shops")

    def test_net_acres_come_from_gross_and_the_ratio_when_not_given(self):
        out = F.residual_land_value_by_parcel([{"id": "P", "gross_ac": 10, "net_to_gross_pct": 80}], {"apartments": apartments()})
        self.near(out["parcels"][0]["net_ac"], 8.0)

    def test_a_parcel_with_no_acres_is_counted_as_not_priced(self):
        out = F.residual_land_value_by_parcel([{"id": "P"}], library())
        self.assertEqual(out["parcels_not_priced"], 1)
        self.assertIsNotNone(out["parcels"][0]["why"])


# ---------------------------------------------------------------- four pricing tiers

class PricingTiers(Near):
    def parcel(self):
        return {"id": "P1", "gross_ac": 10, "net_ac": 8, "cost_items": {"land_basis": 2000000, "entitlement": 500000, "carry": 100000}}

    # Cost floor 2,600,000. Minimum = 2,600,000 x 1.20 + 5% premium (130,000) = 3,120,000 + 130,000 = 3,250,000.
    # Target = base residual 4,000,000; upside = high residual 5,000,000. Target per net acre 500,000; per net SF 500,000 / 43,560 = 11.4784.
    def test_the_four_tiers_by_hand(self):
        out = F.pricing_tiers(self.parcel(), rlv_base_usd=4000000, rlv_high_usd=5000000, strategic_premium_pct=5)
        t = out["tiers"]
        self.near(t["economic_cost_floor"]["price_usd"], 2600000.0)
        self.near(t["minimum_recommended"]["price_usd"], 3250000.0)
        self.near(t["target_market"]["price_usd"], 4000000.0)
        self.near(t["upside_stretch"]["price_usd"], 5000000.0)
        self.near(t["target_market"]["per_net_ac_usd"], 500000.0)
        self.near(t["target_market"]["per_gross_ac_usd"], 400000.0)
        self.near(t["target_market"]["per_net_sf_usd"], 11.4784, 3)
        self.assertTrue(out["tiers_in_order"])
        self.near(out["headroom_target_over_minimum_usd"], 750000.0)

    def test_the_hurdle_is_an_input_and_defaults_to_twenty_percent(self):
        a = F.pricing_tiers(self.parcel(), rlv_base_usd=4000000)
        b = F.pricing_tiers(self.parcel(), rlv_base_usd=4000000, sponsor_hurdle_pct=30)
        self.near(a["tiers"]["minimum_recommended"]["price_usd"], 3120000.0)
        self.near(b["tiers"]["minimum_recommended"]["price_usd"], 3380000.0)       # 2,600,000 x 1.30
        self.assertEqual(a["assumptions"]["sponsor_hurdle_pct"], 20.0)

    def test_a_flat_premium_beats_the_percent(self):
        out = F.pricing_tiers(self.parcel(), 4000000, strategic_premium_pct=50, strategic_premium_usd=100000)
        self.near(out["tiers"]["minimum_recommended"]["price_usd"], 3220000.0)

    # Score 90 against a threshold of 70 at 0.5% of cost a point: 20 x 0.5% = 10% of 2,600,000 = 260,000 premium.
    def test_the_premium_can_follow_the_strategic_score(self):
        p = self.parcel()
        p["strategic_score"] = 90
        out = F.pricing_tiers(p, 4000000, score_premium={"threshold": 70, "pct_per_point": 0.5})
        self.near(out["strategic_premium_usd"], 260000.0)
        self.near(out["tiers"]["minimum_recommended"]["price_usd"], 3380000.0)

    def test_upside_defaults_to_target_plus_fifteen_percent(self):
        out = F.pricing_tiers(self.parcel(), 4000000)
        self.near(out["tiers"]["upside_stretch"]["price_usd"], 4600000.0)

    def test_an_unknown_cost_item_makes_the_floor_a_lower_bound(self):
        p = self.parcel()
        p["cost_items"]["stubs"] = None
        out = F.pricing_tiers(p, 4000000)
        self.assertEqual(out["cost_items_unknown"], 1)
        self.assertTrue(out["cost_floor_is_lower_bound"])
        self.near(out["tiers"]["economic_cost_floor"]["price_usd"], 2600000.0)

    def test_a_target_below_the_minimum_is_said_in_plain_words_and_the_order_flag_drops(self):
        out = F.pricing_tiers(self.parcel(), rlv_base_usd=3000000)
        self.assertFalse(out["tiers_in_order"])
        self.assertTrue(any("hurdle is not met" in n for n in out["notes"]))

    def test_no_cost_basis_gives_none_for_the_two_cost_tiers(self):
        out = F.pricing_tiers({"id": "x", "gross_ac": 5, "net_ac": 4}, 1000000)
        self.assertIsNone(out["tiers"]["economic_cost_floor"]["price_usd"])
        self.assertIsNone(out["tiers"]["minimum_recommended"]["price_usd"])
        self.assertEqual(out["tiers"]["target_market"]["price_usd"], 1000000.0)

    def test_nothing_given_is_all_none_and_finite(self):
        out = F.pricing_tiers({})
        self.assertTrue(all(t["price_usd"] is None for t in out["tiers"].values()))
        self.assertTrue(finite_everywhere(out))


# ---------------------------------------------------------------- gross-to-net waterfall

class Waterfall(Near):
    # Price 10,000,000: brokerage 3.5% = 350,000; closing 0.75% = 75,000; transfer tax 0.11% = 11,000; recording 2,500;
    # seller note 1,000,000; stub 50,000 x 8 net acres = 400,000. Deductions 1,838,500; net 8,161,500.
    def test_every_deduction_is_listed_and_the_net_is_by_hand(self):
        w = F.gross_to_net_waterfall(10000000, net_ac=8, seller_note_usd=1000000, recording_fee_usd=2500, stub_per_net_ac_usd=50000)
        amounts = {r["id"]: r["amount_usd"] for r in w["deductions"]}
        self.assertEqual(amounts, {"seller_note": 1000000.0, "brokerage": 350000.0, "closing_costs": 75000.0, "transfer_tax": 11000.0,
                                   "recording_fee": 2500.0, "parcel_stub": 400000.0})
        self.near(w["total_deductions_usd"], 1838500.0)
        self.near(w["net_cash_proceeds_usd"], 8161500.0)
        self.near(w["net_per_net_ac_usd"], 1020187.5)
        self.near(w["transaction_cost_pct"], 4.36)
        self.assertFalse(w["net_proceeds_is_upper_bound"])

    def test_the_defaults_are_the_stated_rates(self):
        w = F.gross_to_net_waterfall(1000000)
        self.assertEqual(w["assumptions"]["brokerage_pct"], 3.5)
        self.assertEqual(w["assumptions"]["closing_cost_pct"], 0.75)
        self.assertEqual(w["assumptions"]["transfer_tax_pct"], 0.11)
        self.near(w["net_cash_proceeds_usd"], 956400.0)        # 1,000,000 x (1 - 0.0436)

    def test_debt_release_is_a_separate_line(self):
        w = F.gross_to_net_waterfall(5000000, debt_release_usd=2000000)
        self.assertIn("debt_release", [r["id"] for r in w["deductions"]])
        self.near(w["net_cash_proceeds_usd"], 5000000 * 0.9564 - 2000000)

    def test_an_unknown_stub_is_listed_counted_and_never_zero(self):
        w = F.gross_to_net_waterfall(1000000, infrastructure_stubs=[{"name": "Water stub", "amount_usd": None}, {"name": "Road stub", "amount_usd": 20000}])
        self.assertEqual(w["unknown_deductions"], 1)
        self.assertTrue(w["net_proceeds_is_upper_bound"])
        water = next(r for r in w["deductions"] if r["label"] == "Water stub")
        self.assertIsNone(water["amount_usd"])
        self.near(w["net_cash_proceeds_usd"], 956400.0 - 20000)
        self.assertIn("not known", w["summary"])

    def test_a_per_acre_stub_without_acres_is_unknown_not_zero(self):
        w = F.gross_to_net_waterfall(1000000, stub_per_net_ac_usd=50000)
        self.assertEqual(w["unknown_deductions"], 1)

    def test_other_deductions_are_added(self):
        w = F.gross_to_net_waterfall(1000000, other_deductions=[{"name": "Credit to buyer", "amount_usd": 10000}])
        self.near(w["net_cash_proceeds_usd"], 946400.0)

    def test_no_price_gives_none_and_a_reason(self):
        w = F.gross_to_net_waterfall(None)
        self.assertIsNone(w["net_cash_proceeds_usd"])
        self.assertTrue(w["why"])

    def test_zero_and_negative_prices_stay_finite(self):
        for price in (0, -1000):
            self.assertTrue(finite_everywhere(F.gross_to_net_waterfall(price, net_ac=0)))

    # Two parcels: 1,000,000 and 2,000,000, each at 4.36% costs; the second has a 30,000 stub.
    # Nets: 956,400 and 1,912,800 - 30,000 = 1,882,800; together 2,839,200.
    def test_several_parcels_add_up(self):
        out = F.waterfall_for_parcels([{"id": "A", "gross_price_usd": 1000000}, {"id": "B", "gross_price_usd": 2000000, "net_ac": 3, "stub_per_net_ac_usd": 10000}])
        self.near(out["net_total_usd"], 2839200.0)
        self.near(out["gross_total_usd"], 3000000.0)
        self.assertEqual(out["unknown_deductions"], 0)


# ---------------------------------------------------------------- capital target solver

def parcels_for_solver():
    """Five parcels. Net proceeds / acres / strategic score / closing month:
    A 10.0M / 10 / 20 / 12;  B 6.0M / 4 / 50 / 12;  C 5.0M / 2 / 90 / 15 (critical);  D 8.0M / 8 / 30 / 30;  E 3.0M / 3 / 60 / 30."""
    def p(pid, net, ac, score, month):
        return {"id": pid, "net_proceeds_usd": net, "net_ac": ac, "strategic_score": score, "close_month": month, "gross_price_usd": net * 1.1}
    return [p("A", 10e6, 10, 20, 12), p("B", 6e6, 4, 50, 12), p("C", 5e6, 2, 90, 15), p("D", 8e6, 8, 30, 30), p("E", 3e6, 3, 60, 30)]


TARGETS = [{"month": 18, "amount_usd": 12e6}, {"month": 36, "amount_usd": 8e6}]      # 12M by month 18, +8M by month 36 (20M in all)


class CapitalSolver(Near):
    def solve(self, **kw):
        return F.solve_capital_targets(parcels_for_solver(), TARGETS, targets_are_cumulative=False, **kw)

    # Cash per acre: C 2.5M, B 1.5M, then A, D, E at 1.0M (ties go to the lower strategic score: A 20, D 30, E 60).
    # Month 18 needs 12M: C (5M) + B (6M) = 11M is short, so A (10M) is added: 21M. Month 36 needs 20M: 21M is enough.
    # Dropping any one pick (worst-ranked first: A, then B, then C) would miss a target, so C, B, A are the picks.
    def test_max_cash_sells_the_most_cash_per_acre_first(self):
        s = self.solve()["strategies"]["max_cash"]
        self.assertEqual([p["id"] for p in s["picks"]], ["C", "B", "A"])
        self.near(s["total_net_proceeds_usd"], 21e6)
        self.near(s["acres_sold"], 16.0)
        self.assertTrue(s["all_targets_met"])
        self.near(s["surplus_usd"], 1e6)
        self.assertEqual(s["shortfall_usd"], 0.0)
        self.assertEqual(sorted(s["retained"]["parcel_ids"]), ["D", "E"])
        self.near(s["retained"]["acres"], 11.0)

    def test_max_cash_sells_the_critical_parcel_and_the_conflict_is_flagged(self):
        s = self.solve()["strategies"]["max_cash"]
        self.assertEqual([c["kind"] for c in s["critical_asset_conflicts"]], ["critical_asset_sold"])
        self.assertEqual(s["critical_asset_conflicts"][0]["parcel_id"], "C")

    # Retention: C is critical (90 >= 75) and is not in the pool. Lowest score first: A (20): 10M by month 18 (short of 12M), D cannot
    # close before month 30, so B (50) adds 6M: 16M. Month 36 needs 20M: D (30, closes month 30) adds 8M: 24M. Nothing can be dropped.
    def test_max_retention_sells_low_scores_first_and_never_the_critical_parcel(self):
        s = self.solve()["strategies"]["max_retention"]
        self.assertEqual(sorted(p["id"] for p in s["picks"]), ["A", "B", "D"])
        self.near(s["total_net_proceeds_usd"], 24e6)
        self.assertEqual(s["critical_asset_conflicts"], [])
        self.assertEqual(sorted(s["retained"]["parcel_ids"]), ["C", "E"])

    def test_a_parcel_that_closes_after_the_month_cannot_count_for_that_month(self):
        s = self.solve()["strategies"]["max_retention"]
        by_month = {p["month"]: p for p in s["proceeds_by_period"]}
        self.near(by_month[18.0]["cumulative_closed_usd"], 16e6)        # D (month 30) is not in it
        self.near(by_month[36.0]["cumulative_closed_usd"], 24e6)
        self.near(by_month[36.0]["cumulative_target_usd"], 20e6)

    def test_balanced_leans_to_cash_when_cash_is_all_the_weight_and_to_scores_when_it_is_none(self):
        cash = self.solve(balanced_cash_weight=1.0)["strategies"]["balanced"]
        self.assertEqual([p["id"] for p in cash["picks"]], ["C", "B", "A"])
        keep = self.solve(balanced_cash_weight=0.0)["strategies"]["balanced"]
        self.assertEqual(sorted(p["id"] for p in keep["picks"]), ["A", "B", "D"])

    def test_every_strategy_meets_the_targets_when_it_can(self):
        for name, s in self.solve()["strategies"].items():
            self.assertTrue(s["all_targets_met"], name)
            self.assertEqual(s["shortfall_usd"], 0.0, name)

    # Targets of 30M by month 36 with C protected: the others only raise 27M, so a 3M shortfall; C (5M) alone would close it.
    def test_a_target_that_needs_a_critical_parcel_shows_the_shortfall_and_names_the_parcel(self):
        out = F.solve_capital_targets(parcels_for_solver(), [{"month": 36, "amount_usd": 30e6}])
        s = out["strategies"]["max_retention"]
        self.assertFalse(s["all_targets_met"])
        self.near(s["shortfall_usd"], 3e6)
        self.assertEqual(s["critical_parcels_that_would_close_the_gap"], ["C"])
        self.assertTrue(out["strategies"]["max_cash"]["all_targets_met"])

    # All five parcels close by month 36 and raise 32M; without the critical parcel C (5M) the retention plan can raise only 27M.
    def test_a_target_nobody_can_reach_is_a_shortfall_against_everything(self):
        out = F.solve_capital_targets(parcels_for_solver(), [{"month": 36, "amount_usd": 99e6}])["strategies"]
        self.near(out["max_cash"]["shortfall_usd"], 67e6)
        self.near(out["balanced"]["shortfall_usd"], 67e6)
        self.near(out["max_retention"]["shortfall_usd"], 72e6)
        self.assertFalse(out["max_cash"]["all_targets_met"])

    def test_cumulative_targets_are_the_default(self):
        out = F.solve_capital_targets(parcels_for_solver(), [{"month": 18, "amount_usd": 12e6}, {"month": 36, "amount_usd": 20e6}])
        self.assertEqual([t["cumulative_target_usd"] for t in out["targets"]], [12e6, 20e6])
        self.assertEqual([t["cumulative_target_usd"] for t in self.solve()["targets"]], [12e6, 20e6])

    def test_must_keep_is_never_sold_by_any_strategy(self):
        ps = parcels_for_solver()
        ps[0]["must_keep"] = True                                    # A is kept
        out = F.solve_capital_targets(ps, [{"month": 36, "amount_usd": 10e6}])
        for s in out["strategies"].values():
            self.assertNotIn("A", [p["id"] for p in s["picks"]])

    def test_a_do_not_sell_date_is_flagged_when_a_plan_closes_earlier(self):
        ps = parcels_for_solver()
        ps[1]["do_not_sell_until_month"] = 24                         # B closes month 12
        s = F.solve_capital_targets(ps, TARGETS, targets_are_cumulative=False)["strategies"]["max_cash"]
        self.assertIn("sold_inside_hold_period", [c["kind"] for c in s["critical_asset_conflicts"]])

    # A parcel given only a price: 1,000,000 x (1 - 0.0436) = 956,400 net; with a 10,000 per acre stub on 4 acres: 916,400.
    def test_a_price_is_run_through_the_waterfall_when_no_net_is_given(self):
        out = F.solve_capital_targets([{"id": "Z", "gross_price_usd": 1000000, "net_ac": 4, "stub_per_net_ac_usd": 10000, "strategic_score": 10}],
                                      [{"month": 12, "amount_usd": 900000}])
        pick = out["strategies"]["max_cash"]["picks"][0]
        self.near(pick["net_proceeds_usd"], 916400.0)

    def test_parcels_without_proceeds_are_reported_not_silently_dropped(self):
        out = F.solve_capital_targets([{"id": "Q"}] + parcels_for_solver(), TARGETS)
        self.assertEqual(out["parcels_not_used"][0]["id"], "Q")

    def test_no_targets_is_not_an_error(self):
        out = F.solve_capital_targets(parcels_for_solver(), [])
        self.assertTrue(finite_everywhere(out))
        self.assertTrue(out["strategies"]["max_cash"]["why"])

    def test_nothing_in_nothing_out(self):
        self.assertTrue(finite_everywhere(F.solve_capital_targets(None, None)))
        self.assertTrue(finite_everywhere(F.solve_capital_targets([], [{"month": 1, "amount_usd": 5}])))


# ---------------------------------------------------------------- retained land and paced releases

class RetainedLand(Near):
    # 10,000,000 at 5% a year with a 20% lift from year 1: year 5 = 10,000,000 x 1.05^5 x 1.2 = 12,762,815.63 x 1.2 = 15,315,378.75.
    # Year 1 = 10,000,000 x 1.05 x 1.2 = 12,600,000; year 0 has no lift yet. Year 10 = 16,288,946.27 x 1.2 = 19,546,735.52.
    def test_value_over_time_with_a_lift(self):
        out = F.retained_land_value(10000000, 5, placemaking_lift_pct=20, lift_year=1, years=15)
        self.near(out["yearly"][0]["value_usd"], 10000000.0)
        self.near(out["yearly"][1]["value_usd"], 12600000.0)
        self.near(out["milestones"]["5"]["value_usd"], 15315378.75)
        self.near(out["milestones"]["10"]["value_usd"], 19546735.52)
        self.near(out["milestones"]["5"]["gain_vs_today_usd"], 5315378.75)
        self.assertEqual(len(out["yearly"]), 16)

    def test_without_a_lift_it_is_plain_compounding_and_the_implied_rate_matches(self):
        out = F.retained_land_value(10000000, 5, years=15)
        self.near(out["milestones"]["10"]["value_usd"], 16288946.27)
        self.near(out["milestones"]["10"]["implied_growth_pct_per_year"], 5.0, 3)

    def test_value_per_acre_when_acres_are_given(self):
        out = F.retained_land_value(10000000, 0, acres=20, years=2)
        self.near(out["yearly"][1]["per_ac_usd"], 500000.0)

    def test_scenarios_side_by_side(self):
        out = F.retained_land_value_scenarios(
            {"low": {"base_value_usd": 10e6, "appreciation_pct": 3}, "high": {"base_value_usd": 10e6, "appreciation_pct": 7}})
        self.assertLess(out["table"]["10"]["low"], out["table"]["10"]["high"])
        self.near(out["table"]["5"]["low"], 11592740.74)             # 10,000,000 x 1.03^5

    def test_missing_inputs_give_none_and_a_reason(self):
        out = F.retained_land_value(None, None)
        self.assertIsNone(out["value_at_end_usd"])
        self.assertTrue(out["why"])


class PacedReleases(Near):
    # 20 acres at 1,000,000 an acre, flat prices, no selling cost, 5 acres every 2 years for 6 years: years 1, 3, 5 = 15 acres = 15,000,000;
    # 5 acres left at 1,000,000 = 5,000,000; wealth 20,000,000.
    def test_flat_prices_by_hand(self):
        out = F.paced_land_releases(20, 1000000, 5, 2, years=6, sale_cost_pct=0)
        self.assertEqual([e["year"] for e in out["events"]], [1, 3, 5])
        self.near(out["total_net_proceeds_usd"], 15000000.0)
        self.near(out["acres_left"], 5.0)
        self.near(out["total_wealth_usd"], 20000000.0)
        self.assertIsNone(out["floor_reached_year"])

    # 10% a year: year 1 5 x 1,100,000 = 5,500,000; year 3 5 x 1,331,000 = 6,655,000; year 5 5 x 1,610,510 = 8,052,550 -> 20,207,550.
    # 5 acres left at 1,000,000 x 1.1^6 = 1,771,561 -> 8,857,805. Wealth 29,065,355.
    def test_rising_prices_by_hand(self):
        out = F.paced_land_releases(20, 1000000, 5, 2, years=6, appreciation_pct=10, sale_cost_pct=0)
        self.near(out["total_net_proceeds_usd"], 20207550.0)
        self.near(out["value_left_usd"], 8857805.0)
        self.near(out["total_wealth_usd"], 29065355.0)

    # A core floor of 8 acres: year 1 sells 5 (15 left), year 3 sells 5 (10 left), year 5 can sell only 10 - 8 = 2 (8 left): floor reached in year 5.
    def test_the_core_floor_cuts_the_last_release(self):
        out = F.paced_land_releases(20, 1000000, 5, 2, years=6, min_core_acres=8, sale_cost_pct=0)
        self.assertEqual([e["acres_sold"] for e in out["events"]], [5.0, 5.0, 2.0])
        self.near(out["acres_left"], 8.0)
        self.assertEqual(out["floor_reached_year"], 5)

    def test_selling_everything_is_noticed(self):
        out = F.paced_land_releases(10, 1000000, 10, 3, years=15, sale_cost_pct=0)
        self.assertEqual(out["sold_out_year"], 1)

    def test_the_default_selling_cost_is_the_waterfall_rate(self):
        out = F.paced_land_releases(10, 1000000, 10, 3, years=3)
        self.near(out["total_net_proceeds_usd"], 9564000.0)          # 10,000,000 x (1 - 0.0436)

    def test_two_cadences_side_by_side(self):
        out = F.compare_release_cadences([{"name": "slow", "release_acres": 5, "every_years": 2}, {"name": "fast", "release_acres": 10, "every_years": 3}],
                                         20, 1000000, years=9, min_core_acres=10, sale_cost_pct=0)
        slow, fast = out["cadences"]
        self.near(slow["acres_per_year"], 2.5)
        self.near(fast["acres_per_year"], 3.3333, 3)
        self.assertEqual(fast["releases"], 1)                          # 10 acres at once reaches the floor
        self.assertEqual(fast["floor_reached_year"], 4)
        self.assertIsNotNone(out["most_total_wealth"])

    def test_bad_inputs_give_none_and_a_reason(self):
        for args in ((0, 1, 0, 2), (10, 1, 5, 0), (None, 1, 5, 2)):
            out = F.paced_land_releases(*args)
            self.assertTrue(finite_everywhere(out))
        self.assertTrue(F.paced_land_releases(10, 1000000, 0, 2)["why"])


# ---------------------------------------------------------------- reconciliation

class Reconcile(Near):
    def test_a_total_that_adds_up_is_within_tolerance(self):
        out = F.reconcile_program(100, [40, 35, 25])
        self.assertEqual(out["difference"], 0.0)
        self.assertTrue(out["within_tolerance"])

    # 40 + 35 + 24 = 99, a difference of 1 (1% of 100).
    def test_a_small_difference_is_inside_a_tolerance_in_units_or_in_percent(self):
        lines = [40, 35, 24]
        self.assertFalse(F.reconcile_program(100, lines)["within_tolerance"])
        self.assertTrue(F.reconcile_program(100, lines, tolerance_abs=1)["within_tolerance"])
        self.assertTrue(F.reconcile_program(100, lines, tolerance_pct=1)["within_tolerance"])
        self.assertFalse(F.reconcile_program(100, lines, tolerance_pct=0.5)["within_tolerance"])
        self.near(F.reconcile_program(100, lines)["difference_pct"], 1.0)

    def test_a_missing_line_cannot_be_confirmed_and_is_counted(self):
        out = F.reconcile_program(100, [{"label": "a", "value": 60}, {"label": "b", "value": None}])
        self.assertIsNone(out["within_tolerance"])
        self.assertEqual(out["missing_components"], 1)
        self.assertIn("not known", out["explanation"])

    def test_no_headline_and_a_zero_headline_do_not_raise(self):
        self.assertIsNone(F.reconcile_program(None, [1, 2])["within_tolerance"])
        out = F.reconcile_program(0, [0, 0])
        self.assertTrue(out["within_tolerance"])
        self.assertTrue(finite_everywhere(F.reconcile_program(0, [5])))


if __name__ == "__main__":
    unittest.main()
