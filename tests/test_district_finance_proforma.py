"""The district finance engine, part 2: absorption and lease-up, phasing triggers, the phase pro forma, break-even and scenarios.

Invented, round inputs; the expected numbers are worked out by hand in the comments. See test_district_finance.py for part 1.
"""
import unittest

import support  # noqa: F401  (puts the project folder on the import path)
from landplanner.district import finance as F
from test_district_finance import Near, finite_everywhere, library


def mini_library():
    """One use: 20 units an acre, $2,000 a month, nothing empty, 40% of income spent on running it, one cost of $200,000 a unit, 5% cap.
    So one unit earns 2,000 x 12 x 0.6 = 14,400 a year and costs 200,000: 7.2% on cost."""
    return {"apts": {"label": "Apartments", "density": {"units_per_net_ac": 20, "sf_per_unit": 1000},
                     "revenue": {"type": "rent_per_unit_mo", "rent_per_unit_mo": 2000, "vacancy_pct": 0, "opex_pct_of_income": 40},
                     "cost_line_items": [{"id": "build", "basis": "per_unit", "amount": 200000}], "cap_rate_pct": 5, "required_return_pct": 15}}


def sale_library():
    """Homes: 10 an acre sold at $500,000, no selling cost, built for $300,000 each."""
    return {"homes": {"label": "Homes", "density": {"units_per_net_ac": 10, "sf_per_unit": 1600},
                      "revenue": {"type": "per_unit_sale", "price_per_unit": 500000},
                      "cost_line_items": [{"id": "build", "basis": "per_unit", "amount": 300000}], "required_return_pct": 15}}


def phase(units=100, land=0.0):
    return {"id": "p1", "label": "Phase 1", "land_cost_usd": land, "lines": [{"use": "apts", "units": units}]}


ASSUME = {"hurdle_yoc_pct": 6.75, "hold_years": 5, "discount_rate_pct": 10, "base_year": 2030}


# ---------------------------------------------------------------- absorption and lease-up

class Absorption(Near):
    # 120 units at 10 a month: 10, 20 ... 120 in month 12. Year 1 absorbs 120.
    def test_a_straight_lease_up_by_hand(self):
        s = F.absorption_schedule(120, absorption_per_month=10)
        self.assertEqual(s["stabilization_month"], 12)
        self.assertEqual(s["stabilization_year"], 1)
        self.assertEqual(s["monthly"][0]["cumulative"], 10.0)
        self.assertEqual(s["monthly"][11]["cumulative"], 120.0)
        self.near(s["yearly"][0]["absorbed_in_year"], 120.0)
        self.near(s["yearly"][0]["end_cumulative"], 120.0)
        # the average of 10, 20 ... 120 is 65: 65 / 120 = 54.1667% of the quantity during year 1
        self.near(s["yearly"][0]["average_fraction_of_quantity"], 65.0 / 120.0, 6)

    def test_a_yearly_rate_is_a_twelfth_a_month_and_never_mixed_with_a_monthly_one(self):
        s = F.absorption_schedule(120, absorption_per_year=60)             # 5 a month: 24 months
        self.assertEqual(s["stabilization_month"], 24)
        self.assertEqual(s["stabilization_year"], 2)
        both = F.absorption_schedule(120, absorption_per_month=5, absorption_per_year=60)
        self.assertIn("not both", both["why"])
        self.assertEqual(both["monthly"], [])

    # 95% occupancy: the target is 114 of 120. 10 a month reaches 110 in month 11 and is held to 114 in month 12.
    def test_stabilised_occupancy_caps_the_fill(self):
        s = F.absorption_schedule(120, absorption_per_month=10, stabilized_occupancy_pct=95)
        self.near(s["target_quantity"], 114.0)
        self.assertEqual(s["stabilization_month"], 12)
        self.assertEqual(s["monthly"][-1]["cumulative"], 114.0)

    # 25% pre-leased: 30 units are in place before the first month. 40, 50 ... 120 is month 9.
    def test_pre_leasing_gives_a_head_start(self):
        s = F.absorption_schedule(120, absorption_per_month=10, pre_leased_pct=25)
        self.assertEqual(s["stabilization_month"], 9)

    # 60 units are delivered in month 1 and 60 more in month 13. Month 1-6 fill the first 60 (10 a month), then it waits;
    # month 13 has 120 delivered and 60 in place: 70, 80, 90, 100, 110, 120 gives month 18.
    def test_staged_deliveries_limit_the_absorption(self):
        s = F.absorption_schedule(120, absorption_per_month=10, deliveries=[{"month": 1, "quantity": 60}, {"month": 13, "quantity": 60}])
        self.assertEqual(s["monthly"][5]["cumulative"], 60.0)
        self.assertEqual(s["monthly"][11]["cumulative"], 60.0)
        self.assertEqual(s["monthly"][12]["cumulative"], 70.0)
        self.assertEqual(s["stabilization_month"], 18)

    def test_a_late_start_shifts_everything(self):
        s = F.absorption_schedule(120, absorption_per_month=10, start_month=7)
        self.assertEqual(s["monthly"][5]["cumulative"], 0.0)
        self.assertEqual(s["stabilization_month"], 18)

    def test_not_stabilised_inside_the_horizon_says_so(self):
        s = F.absorption_schedule(1000, absorption_per_month=1, horizon_months=24)
        self.assertIsNone(s["stabilization_month"])
        self.assertIn("Not stabilised", s["why"])

    def test_zero_negative_and_missing_inputs_stay_finite(self):
        for args in ((0, 5), (-5, 5), (None, 5)):
            s = F.absorption_schedule(args[0], absorption_per_month=args[1])
            self.assertTrue(s["why"])
        s = F.absorption_schedule(100, absorption_per_month=0)
        self.assertIsNone(s["stabilization_month"])
        self.assertTrue(finite_everywhere(s))
        self.assertTrue(F.absorption_schedule(100)["why"])


class PhasingTriggers(Near):
    TRIGGERS = [{"id": "units", "metric": "units_delivered", "operator": ">=", "threshold": 200},
                {"id": "pre", "metric": "pre_leasing_pct", "operator": ">=", "threshold": 50},
                {"id": "abs", "metric": "absorption_per_month", "operator": ">=", "threshold": 10}]

    def test_met_not_met_and_unknown_are_three_different_answers(self):
        out = F.evaluate_phasing_triggers(self.TRIGGERS, {"units_delivered": 250, "pre_leasing_pct": 40})
        states = {t["id"]: t["state"] for t in out["triggers"]}
        self.assertEqual(states, {"units": "met", "pre": "not_met", "abs": "unknown"})
        self.near(out["triggers"][1]["gap"], 10.0)
        self.assertFalse(out["all_met"])
        self.assertTrue(out["any_unknown"])
        self.assertEqual(out["counts"], {"met": 1, "not_met": 1, "unknown": 1})

    def test_all_met_only_when_every_one_is_met(self):
        out = F.evaluate_phasing_triggers(self.TRIGGERS, {"units_delivered": 250, "pre_leasing_pct": 60, "absorption_per_month": 12})
        self.assertTrue(out["all_met"])

    def test_operators(self):
        t = lambda op, thr, val: F.evaluate_phasing_triggers([{"id": "x", "metric": "m", "operator": op, "threshold": thr}], {"m": val})["triggers"][0]["state"]
        self.assertEqual(t("<=", 5, 5), "met")
        self.assertEqual(t("<", 5, 5), "not_met")
        self.assertEqual(t(">", 5, 5), "not_met")
        self.assertEqual(t("==", 5, 5), "met")
        self.assertEqual(t("~", 5, 5), "unknown")

    def test_nothing_given(self):
        out = F.evaluate_phasing_triggers(None, None)
        self.assertFalse(out["all_met"])
        self.assertTrue(finite_everywhere(out))

    # 120 units at 10 a month, 25% pre-leased: in month 6 there are 30 + 60 = 90 absorbed, and the last 6 months took 10 a month.
    def test_the_status_of_a_schedule_at_a_month_feeds_the_triggers(self):
        sched = F.absorption_schedule(120, absorption_per_month=10, pre_leased_pct=25)
        st = F.schedule_status_at_month(sched, 6, pre_leased_pct=25)
        self.assertEqual(st["metrics"]["units_absorbed"], 90.0)
        self.assertEqual(st["metrics"]["units_delivered"], 120.0)
        self.assertEqual(st["metrics"]["absorption_per_month"], 10.0)
        self.assertEqual(st["metrics"]["pre_leasing_pct"], 25.0)
        out = F.evaluate_phasing_triggers(self.TRIGGERS, st["metrics"])
        self.assertEqual([t["state"] for t in out["triggers"]], ["not_met", "not_met", "met"])
        self.assertTrue(F.schedule_status_at_month(sched, 0)["why"])


# ---------------------------------------------------------------- the phase pro forma

class PhaseProForma(Near):
    # 100 units cost 100 x 200,000 = 20,000,000, spent 10,000,000 in each of two build years. NOI = 100 x 14,400 = 1,440,000: 7.2% on cost.
    # Value = 1,440,000 / 0.05 = 28,800,000. A 24-month straight lease-up fills 100/24 units a month: the average share in year 1 is
    # (1 + 2 + ... + 12) / 24 / 12... = 6.5 / 24 = 0.270833 (NOI 390,000), in year 2 18.5 / 24 = 0.770833 (NOI 1,110,000), then 1.
    # Five operating years, then a sale at 1,440,000 / 0.05 = 28,800,000 at the end of the fifth.
    # Cash by year: -10M, -10M, 390,000, 1,110,000, 1,440,000, 1,440,000, 1,440,000 + 28,800,000 = 30,240,000.
    def test_cash_flows_by_hand(self):
        r = F.phase_pro_forma(phase(), mini_library(), ASSUME)
        self.assertEqual([c["year"] for c in r["cash_flows"]], list(range(2030, 2037)))
        nets = [c["net_usd"] for c in r["cash_flows"]]
        self.assertEqual(nets, [-10000000.0, -10000000.0, 390000.0, 1110000.0, 1440000.0, 1440000.0, 30240000.0])
        self.near(r["cash_flows"][6]["exit_net_usd"], 28800000.0)

    def test_totals_and_yield_on_cost_by_hand(self):
        r = F.phase_pro_forma(phase(), mini_library(), ASSUME)
        self.near(r["totals"]["development_cost_usd"], 20000000.0)
        self.near(r["totals"]["stabilized_noi_usd_yr"], 1440000.0)
        self.near(r["totals"]["implied_value_usd"], 28800000.0)
        self.near(r["totals"]["development_margin_pct"], 44.0)           # 28.8 / 20 - 1
        y = r["yield_on_cost"]
        self.near(y["yoc_pct"], 7.2, 4)
        self.near(y["spread_pct_points"], 0.45, 4)                       # 7.20 - 6.75
        self.near(y["spread_bps"], 45.0, 1)
        self.assertTrue(y["meets_hurdle"])

    # Equity multiple = money back / money in = (390,000 + 1,110,000 + 1,440,000 x 2 + 30,240,000) / 20,000,000 = 34,620,000 / 20,000,000 = 1.731.
    # NPV at 10% is the sum of each year's cash / 1.1^t = 1,012,722.11 (worked year by year in the comment of the next test).
    def test_equity_multiple_npv_and_irr(self):
        r = F.phase_pro_forma(phase(), mini_library(), ASSUME)
        self.near(r["equity_multiple"], 1.731, 4)
        self.near(r["npv"]["npv_usd"], 1012722.11)
        self.assertTrue(r["irr"]["converged"])
        self.assertEqual(r["irr"]["method"], "newton")
        self.near(r["irr"]["irr_pct"], 11.1009, 3)

    # The IRR is the rate that makes the present value zero: check that against an independent sum.
    def test_the_irr_really_zeroes_the_present_value(self):
        r = F.phase_pro_forma(phase(), mini_library(), ASSUME)
        rate = r["irr"]["irr_pct"] / 100.0
        pv = sum(c["net_usd"] / (1 + rate) ** t for t, c in enumerate(r["cash_flows"]))
        self.assertLess(abs(pv), 100.0)                                  # within $100 on $20 million: rounding of the printed rate

    def test_land_is_paid_up_front_and_lowers_the_yield_on_cost(self):
        r = F.phase_pro_forma(phase(land=5000000), mini_library(), ASSUME)
        self.near(r["cash_flows"][0]["land_usd"], -5000000.0)
        self.near(r["yield_on_cost"]["yoc_pct"], 5.76, 3)               # 1,440,000 / 25,000,000
        self.near(r["yield_on_cost"]["yoc_excl_land_pct"], 7.2, 3)
        self.assertFalse(r["yield_on_cost"]["meets_hurdle"])

    def test_a_sale_use_books_net_sales_as_homes_close(self):
        # 20 homes sold at 500,000 = 10,000,000; cost 20 x 300,000 = 6,000,000. Built over two years, sold evenly over 24 months:
        # 10 close in year 1 of sales, 10 in year 2: 5,000,000 each, in years index 2 and 3.
        r = F.phase_pro_forma({"id": "h", "lines": [{"use": "homes", "units": 20}]}, sale_library(), {"base_year": 2030})
        self.assertEqual([c["sales_net_usd"] for c in r["cash_flows"]], [0.0, 0.0, 5000000.0, 5000000.0])
        self.assertEqual([c["net_usd"] for c in r["cash_flows"]], [-3000000.0, -3000000.0, 5000000.0, 5000000.0])
        self.near(r["totals"]["net_sales_revenue_usd"], 10000000.0)
        self.assertIsNone(r["yield_on_cost"]["yoc_pct"])                  # no income use: no yield on cost
        self.assertTrue(r["yield_on_cost"]["why"])
        self.assertTrue(r["irr"]["converged"])
        self.near(r["equity_multiple"], 10000000 / 6000000.0, 4)

    def test_the_spend_curve_and_build_years_are_inputs(self):
        ph = phase()
        ph["lines"][0].update({"build_years": 3, "spend_curve_pct": [50, 30, 20]})
        r = F.phase_pro_forma(ph, mini_library(), ASSUME)
        self.assertEqual([c["construction_cost_usd"] for c in r["cash_flows"][:3]], [-10000000.0, -6000000.0, -4000000.0])

    def test_a_curve_that_does_not_add_to_one_hundred_is_spread_evenly(self):
        ph = phase()
        ph["lines"][0].update({"build_years": 2, "spend_curve_pct": [70, 70]})
        r = F.phase_pro_forma(ph, mini_library(), ASSUME)
        self.assertEqual([c["construction_cost_usd"] for c in r["cash_flows"][:2]], [-10000000.0, -10000000.0])

    def test_noi_growth_lifts_later_years_and_the_exit(self):
        r = F.phase_pro_forma(phase(), mini_library(), {**ASSUME, "noi_growth_pct": 3})
        # year 3 of operations (index 4) earns 1,440,000 x 1.03^2 = 1,527,696; the sale is 1,440,000 x 1.03^5 / 0.05
        self.near(r["cash_flows"][4]["noi_usd"], 1527696.0)
        self.near(r["cash_flows"][6]["exit_net_usd"], 1440000 * 1.03 ** 5 / 0.05)

    def test_the_hold_period_is_an_input(self):
        r = F.phase_pro_forma(phase(), mini_library(), {**ASSUME, "hold_years": 3})
        self.assertEqual(len(r["cash_flows"]), 5)

    def test_a_cost_item_with_no_amount_is_counted_and_marks_the_phase_partial(self):
        lib = mini_library()
        lib["apts"]["cost_line_items"].append({"id": "other_soft", "amount": None})
        r = F.phase_pro_forma(phase(), lib, ASSUME)
        self.assertEqual(r["totals"]["cost_unknown_items"], 1)
        self.assertTrue(r["totals"]["cost_is_partial"])
        self.near(r["totals"]["development_cost_usd"], 20000000.0)        # the unknown is left out, not made a number

    def test_an_unknown_use_is_reported(self):
        r = F.phase_pro_forma({"id": "x", "lines": [{"use": "castle", "units": 5}]}, mini_library(), ASSUME)
        self.assertIn("not in the land use library", r["lines"][0]["why"])
        self.assertTrue(finite_everywhere(r))

    def test_the_answer_echoes_its_assumptions_and_formula(self):
        r = F.phase_pro_forma(phase(), mini_library(), ASSUME)
        self.assertEqual(r["assumptions"]["hold_years"], 5)
        self.assertEqual(r["assumptions"]["discount_rate_pct"], 10)
        self.assertTrue(r["formula"])
        self.assertIn("not an appraisal", r["disclaimer"])

    def test_empty_and_degenerate_phases_do_not_raise(self):
        for ph in (None, {}, {"lines": []}, {"lines": [{"use": "apts", "units": 0}]}, {"lines": [{"use": "apts", "units": -5}]}):
            self.assertTrue(finite_everywhere(F.phase_pro_forma(ph, mini_library(), ASSUME)))

    def test_with_no_exit_cap_the_sale_is_left_out_and_says_so(self):
        lib = mini_library()
        del lib["apts"]["cap_rate_pct"]
        r = F.phase_pro_forma(phase(), lib, ASSUME)
        self.assertEqual(sum(c["exit_net_usd"] for c in r["cash_flows"]), 0.0)
        self.assertIn("exit cap", r["lines"][0]["why"])


class FullBuildout(Near):
    # Two identical 100-unit phases, the second starting four years after the first. Each: -10M, -10M, 390,000, ... as above.
    # Together at year index 4 the second phase builds (-10M) while the first earns 1,440,000: net -8,560,000; the totals are twice one phase.
    def test_phases_are_shifted_and_added(self):
        p2 = {**phase(), "id": "p2", "start_offset_years": 4}
        r = F.full_buildout_pro_forma([phase(), p2], mini_library(), ASSUME)
        self.assertEqual(len(r["phases"]), 2)
        fb = r["full_buildout"]
        self.near(fb["totals"]["development_cost_usd"], 40000000.0)
        self.near(fb["totals"]["stabilized_noi_usd_yr"], 2880000.0)
        self.near(fb["yield_on_cost"]["yoc_pct"], 7.2, 4)
        self.near(fb["cash_flows"][4]["net_usd"], 1440000.0 - 10000000.0)
        self.assertEqual(fb["cash_flows"][0]["year"], 2030)
        self.assertTrue(fb["irr"]["converged"])

    def test_one_phase_rolls_up_to_itself(self):
        one = F.phase_pro_forma(phase(), mini_library(), ASSUME)
        fb = F.full_buildout_pro_forma([phase()], mini_library(), ASSUME)["full_buildout"]
        self.near(fb["irr"]["irr_pct"], one["irr"]["irr_pct"], 4)
        self.near(fb["npv"]["npv_usd"], one["npv"]["npv_usd"])

    def test_unknown_costs_are_added_across_phases(self):
        lib = mini_library()
        lib["apts"]["cost_line_items"].append({"id": "x", "amount": None})
        fb = F.full_buildout_pro_forma([phase(), phase()], lib, ASSUME)["full_buildout"]
        self.assertEqual(fb["totals"]["cost_unknown_items"], 2)

    def test_no_phases(self):
        self.assertTrue(finite_everywhere(F.full_buildout_pro_forma([], mini_library(), ASSUME)))


# ---------------------------------------------------------------- break-even

class BreakEven(Near):
    # Cost 20,000,000 and a hurdle of 8% need NOI 1,600,000 = 16,000 a unit = 16,000 / 0.6 / 12 = 2,222.22 a month (today 2,000: x 1.1111).
    def test_apartment_rent_for_a_yield_on_cost_hurdle(self):
        out = F.break_even(phase(), mini_library(), {**ASSUME, "hurdle_yoc_pct": 8}, "apartment_rent")
        self.assertTrue(out["converged"])
        self.near(out["breakeven_value"], 2222.22, 1)
        self.near(out["breakeven_factor"], 1.111111, 4)
        self.near(out["metric_today_pct"], 7.2, 3)
        self.near(out["metric_at_breakeven_pct"], 8.0, 3)
        self.assertFalse(out["already_met_today"])
        self.assertEqual(out["unit"], "$ per unit per month")

    def test_a_hurdle_already_met_still_finds_the_lower_rent(self):
        out = F.break_even(phase(), mini_library(), {**ASSUME, "hurdle_yoc_pct": 6}, "apartment_rent")
        self.assertTrue(out["already_met_today"])
        self.near(out["breakeven_value"], 1666.67, 1)               # 6% x 20,000,000 = 1,200,000 = 12,000 a unit = 1,666.67 a month

    def test_retail_nnn_rent_and_hotel_adr_use_their_own_revenue_types(self):
        lib = {"shops": {"density": {"far": 0.25}, "revenue": {"type": "rent_per_sf_yr", "rent_per_sf_yr": 30, "vacancy_pct": 0, "opex_pct_of_income": 0},
                         "cost_line_items": [{"id": "b", "basis": "per_building_sf", "amount": 300}], "cap_rate_pct": 6, "required_return_pct": 10},
               "hotel": {"density": {"units_per_net_ac": 40, "sf_per_unit": 500},
                         "revenue": {"type": "room_revenue", "adr": 200, "occupancy_pct": 70, "other_income_pct": 0, "opex_pct_of_income": 60},
                         "cost_line_items": [{"id": "b", "basis": "per_unit", "amount": 300000}], "cap_rate_pct": 7, "required_return_pct": 10}}
        # shops: 10,000 SF cost 10,000 x 300 = 3,000,000. Rent 30 a SF gives 300,000 (10% on cost); a 12% hurdle needs 360,000 = $36 a SF a year.
        shops = F.break_even({"id": "s", "lines": [{"use": "shops", "building_sf": 10000}]}, lib, {"hurdle_yoc_pct": 12, "hold_years": 5}, "retail_nnn_rent")
        self.near(shops["breakeven_value"], 36.0, 2)
        self.assertEqual(shops["by_use"][0]["driver"], "rent_per_sf_yr")
        # hotel: 40 keys cost 12,000,000; revenue 40 x 200 x 365 x 0.7 = 2,044,000; NOI at 40% = 817,600 = 6.81%. A 9% hurdle needs
        # NOI 1,080,000 = revenue 2,700,000 = ADR 2,700,000 / (40 x 365 x 0.7) = 264.18.
        hotel = F.break_even({"id": "h", "lines": [{"use": "hotel", "units": 40}]}, lib, {"hurdle_yoc_pct": 9, "hold_years": 5}, "hotel_adr")
        self.near(hotel["breakeven_value"], 264.18, 1)

    def test_for_sale_price_and_exit_cap_round_trip_through_the_irr(self):
        lib = sale_library()
        base = F.phase_pro_forma({"id": "h", "lines": [{"use": "homes", "units": 20}]}, lib, {"base_year": 2030})
        target = base["irr"]["irr_pct"]
        lib["homes"]["revenue"]["price_per_unit"] = 450000
        out = F.break_even({"id": "h", "lines": [{"use": "homes", "units": 20}]}, lib, {"hurdle_irr_pct": target}, "for_sale_price")
        self.assertTrue(out["converged"])
        self.assertAlmostEqual(out["breakeven_value"], 500000.0, delta=5)       # the target IRR is rounded to 4 decimals
        self.assertEqual(out["metric"], "irr")
        # exit cap: the IRR of the apartments at a 6% exit cap is the hurdle; the solver must hand back 6%
        lib2 = mini_library()
        lib2["apts"]["cap_rate_pct"] = 6
        irr6 = F.phase_pro_forma(phase(), lib2, ASSUME)["irr"]["irr_pct"]
        lib2["apts"]["cap_rate_pct"] = 5
        cap = F.break_even(phase(), lib2, {**ASSUME, "hurdle_irr_pct": irr6}, "exit_cap_rate")
        self.assertTrue(cap["converged"])
        self.near(cap["breakeven_value"], 6.0, 2)

    def test_a_lower_cap_rate_makes_the_irr_higher_so_the_break_even_is_the_highest_cap_that_works(self):
        out = F.break_even(phase(), mini_library(), {**ASSUME, "hurdle_irr_pct": 10}, "exit_cap_rate")
        self.assertTrue(out["converged"])
        self.assertGreater(out["breakeven_value"], 5.0)
        self.near(out["metric_at_breakeven_pct"], 10.0, 2)

    def test_the_exit_cap_cannot_be_solved_on_yield_on_cost(self):
        out = F.break_even(phase(), mini_library(), ASSUME, "exit_cap_rate", metric="yoc")
        self.assertIsNone(out["breakeven_value"])
        self.assertIn("does not change yield on cost", out["why"])

    def test_missing_hurdle_unknown_variable_and_no_matching_use_each_say_why(self):
        self.assertIn("hurdle", F.break_even(phase(), mini_library(), {}, "apartment_rent")["why"])
        self.assertIn("must be one of", F.break_even(phase(), mini_library(), ASSUME, "bananas")["why"])
        self.assertIn("No use", F.break_even(phase(), mini_library(), ASSUME, "hotel_adr")["why"])

    def test_a_hurdle_that_cannot_be_reached_says_so_instead_of_returning_a_number(self):
        out = F.break_even(phase(), mini_library(), {**ASSUME, "hurdle_yoc_pct": 90}, "apartment_rent")
        self.assertIsNone(out["breakeven_value"])
        self.assertIn("not met even", out["why"])


# ---------------------------------------------------------------- scenarios and sensitivity

def program(units=100):
    return {"library": mini_library(), "phases": [phase(units)], "assumptions": ASSUME}


class Scenarios(Near):
    LOW_BASE_HIGH = {"low": {"revenue_pct": -10}, "base": {}, "high": {"revenue_pct": 10}}

    # Rents -10% / +10%: NOI 1,440,000 x 0.9 = 1,296,000 and x 1.1 = 1,584,000 (costs do not move); yield on cost 6.48% / 7.2% / 7.92%.
    def test_low_base_high_side_by_side(self):
        out = F.run_scenarios(program(), self.LOW_BASE_HIGH)
        t = out["table"]
        self.assertEqual(t["stabilized_noi_usd_yr"], {"low": 1296000.0, "base": 1440000.0, "high": 1584000.0})
        self.near(t["yoc_pct"]["low"], 6.48, 3)
        self.near(t["yoc_pct"]["high"], 7.92, 3)
        self.assertEqual(t["development_cost_usd"], {"low": 20000000.0, "base": 20000000.0, "high": 20000000.0})
        self.assertEqual(out["base_name"], "base")
        self.near(out["vs_base"]["low"]["stabilized_noi_usd_yr"], -144000.0)
        self.assertEqual(out["vs_base"]["base"]["yoc_pct"], 0.0)

    def test_the_default_three_scenarios_are_low_base_high(self):
        out = F.run_scenarios(program())
        self.assertEqual([s["name"] for s in out["scenarios"]], ["low", "base", "high"])
        irrs = [out["table"]["irr_pct"][n] for n in ("low", "base", "high")]
        self.assertLess(irrs[0], irrs[1])
        self.assertLess(irrs[1], irrs[2])

    # Holding the program to 50, 100 and 200 units scales the cost with it: 10M, 20M, 40M.
    def test_unit_count_scenarios(self):
        out = F.run_scenarios(program(), F.unit_count_scenarios((50, 100, 200)))
        self.assertEqual(out["table"]["units_total"], {"50_units": 50.0, "100_units": 100.0, "200_units": 200.0})
        self.assertEqual(out["table"]["development_cost_usd"], {"50_units": 10000000.0, "100_units": 20000000.0, "200_units": 40000000.0})
        self.assertEqual(out["table"]["yoc_pct"]["50_units"], out["table"]["yoc_pct"]["200_units"])        # per unit economics do not change

    def test_the_inputs_given_are_never_changed_by_a_scenario_run(self):
        inp = program()
        before = repr(inp)
        F.run_scenarios(inp, self.LOW_BASE_HIGH)
        F.sensitivity_tornado(inp)
        self.assertEqual(repr(inp), before)

    def test_a_custom_evaluator_can_be_plugged_in(self):
        out = F.run_scenarios({"x": 2}, {"a": {}, "b": {}}, evaluate=lambda inp: {"double": inp["x"] * 2})
        self.assertEqual(out["table"]["double"], {"a": 4, "b": 4})

    def test_cost_and_cap_rate_adjustments(self):
        out = F.run_scenarios(program(), {"base": {}, "dearer": {"cost_pct": 10}, "cap_up": {"cap_rate_delta_pct": 1}})
        self.near(out["table"]["development_cost_usd"]["dearer"], 22000000.0)
        self.near(out["table"]["implied_value_usd"]["cap_up"], 1440000 / 0.06 * 1.0)          # a 6% cap: 24,000,000

    def test_residual_value_is_in_the_table_when_parcels_are_given(self):
        inp = {"library": library(), "parcels": [{"id": "P", "net_ac": 10, "use": "apartments"}]}
        out = F.run_scenarios(inp, {"base": {}, "rents_up": {"revenue_pct": 10}})
        self.near(out["table"]["rlv_total_usd"]["base"], 8497826.09)
        self.near(out["table"]["rlv_total_usd"]["rents_up"], 13652608.70)        # 10 x 1,365,260.87


class Tornado(Near):
    # Yield on cost today 7.2%. Costs -10% / +10%: 1,440,000 / 18,000,000 = 8.00% and 1,440,000 / 22,000,000 = 6.5455%: swing 1.4545.
    # Rents -10% / +10%: 6.48% and 7.92%: swing 1.44. Density does not move a program given in units; cap rate and required return do not
    # move the yield on cost: swing 0.
    def test_rows_are_ranked_by_swing_and_the_numbers_are_right(self):
        t = F.sensitivity_tornado(program(), metric="yoc_pct")
        rows = {r["id"]: r for r in t["rows"]}
        self.assertEqual(t["rows"][0]["id"], "costs")
        self.assertEqual([r["rank"] for r in t["rows"]], [1, 2, 3, 4, 5])
        self.near(rows["costs"]["swing"], 1.4545, 3)
        self.near(rows["rents"]["swing"], 1.44, 3)
        self.near(rows["costs"]["metric_at_low"], 8.0, 3)
        self.near(rows["costs"]["change_at_high"], 6.5455 - 7.2, 3)
        self.assertEqual(rows["cap_rate"]["swing"], 0.0)
        self.assertEqual(t["base_value"], 7.2)

    def test_the_five_standard_variables_are_present(self):
        ids = {r["id"] for r in F.sensitivity_tornado(program())["rows"]}
        self.assertEqual(ids, {"density", "rents", "costs", "required_return", "cap_rate"})

    # Residual land value of one net acre of apartments: rents +/-10%: 849,782.61 -> the swing is the difference of the two ends.
    def test_residual_land_value_is_the_default_metric_when_there_are_parcels(self):
        inp = {"library": library(), "parcels": [{"id": "P", "net_ac": 1, "use": "apartments"}]}
        t = F.sensitivity_tornado(inp)
        self.assertEqual(t["metric"], "rlv_total_usd")
        self.near(t["base_value"], 849782.61)
        rents = next(r for r in t["rows"] if r["id"] == "rents")
        # +10%: 1,365,260.87 ; -10%: NOI 266,760, value 5,335,200, RLV 5,335,200 / 1.15 - 4,305,000 = 334,... (4,639,304.35 - 4,305,000 = 334,304.35)
        self.near(rents["metric_at_high"], 1365260.87)
        self.near(rents["metric_at_low"], 334304.35)
        # density +/-10% changes both units and building SF, so the swing is large too, and the required return swings the value divisor
        self.assertTrue(all(r["swing"] is not None for r in t["rows"]))

    def test_custom_variables(self):
        t = F.sensitivity_tornado(program(), variables=[{"id": "rent_only", "low": {"revenue_pct": -5}, "high": {"revenue_pct": 5}}], metric="stabilized_noi_usd_yr")
        self.near(t["rows"][0]["swing"], 144000.0)

    def test_nothing_to_measure_gives_none_and_a_reason(self):
        t = F.sensitivity_tornado({"library": mini_library()})
        self.assertIsNone(t["metric"])
        self.assertTrue(t["why"])
        self.assertTrue(finite_everywhere(t))


if __name__ == "__main__":
    unittest.main()
