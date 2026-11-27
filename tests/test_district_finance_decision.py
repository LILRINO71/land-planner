"""The district finance engine, part 3: hold / sell / joint venture / ground lease, critical-asset conflicts, infrastructure funding,
fiscal impact, and the whole-API checks (every function documented, nothing returns NaN or Infinity, no private names in tracked files).

Invented, round inputs; expected numbers are worked out by hand in the comments. See test_district_finance.py for part 1.
"""
import copy
import unittest
from pathlib import Path

import support  # noqa: F401  (puts the project folder on the import path)
from landplanner.district import finance as F
from test_district_finance import Near, finite_everywhere, library

ROOT = Path(__file__).resolve().parent.parent
DECIDE = {"discount_rate_pct": 10, "sale_cost_pct": 0, "appreciation_pct": 0}


def land_parcel(**kw):
    """Land worth 10,000,000 that does not appreciate; sold, it would bring 10,000,000 a year from now (no selling cost in these tests)."""
    p = {"id": "P", "net_ac": 5, "land_value_usd": 10000000, "appreciation_pct": 0,
         "ground_lease": {"rent_yield_pct": 6, "escalation_pct": 0, "leased_fee_cap_pct": 6, "start_year": 1},
         "develop": {"total_cost_usd": 30000000, "stabilized_noi_usd": 2400000, "exit_cap_pct": 6, "start_year": 1, "build_years": 2, "lease_up_years": 2},
         "jv": {"cash_out_pct": 20}}
    p.update(kw)
    return p


# ---------------------------------------------------------------- strategic scores

class StrategicScores(Near):
    def test_twelve_dimensions_and_nine_criteria_are_the_defaults(self):
        dims, crit = F.default_strategic_dimensions(), F.default_economic_criteria()
        self.assertEqual(len(dims), 12)
        self.assertEqual(len(crit), 9)
        self.assertEqual(len({d["id"] for d in dims}), 12)
        self.assertTrue(all(d["weight"] == 1.0 for d in dims))

    # (90 + 70) / 2 = 80; with the first weighted 3: (90 x 3 + 70 x 1) / 4 = 85. Ten of the twelve dimensions have no score.
    def test_the_score_is_a_weighted_average_of_what_is_scored(self):
        a = F.score_strategic_dimensions({"placemaking_gravity": 90, "scarcity": 70})
        self.near(a["strategic_score"], 80.0)
        self.assertEqual(a["dimensions_scored"], 2)
        self.assertEqual(len(a["dimensions_missing"]), 10)
        b = F.score_strategic_dimensions({"placemaking_gravity": 90, "scarcity": 70}, {"placemaking_gravity": 3})
        self.near(b["strategic_score"], 85.0)

    def test_scores_outside_the_range_are_held_to_it_and_nothing_scored_is_none(self):
        self.near(F.score_strategic_dimensions({"scarcity": 250, "placemaking_gravity": -40})["strategic_score"], 50.0)
        out = F.score_strategic_dimensions({})
        self.assertIsNone(out["strategic_score"])
        self.assertTrue(out["why"])

    def test_the_dimensions_are_an_input(self):
        out = F.score_strategic_dimensions({"a": 10, "b": 30}, dimensions=[{"id": "a"}, {"id": "b"}, {"id": "c"}])
        self.near(out["strategic_score"], 20.0)
        self.assertEqual(out["dimensions_missing"], ["c"])


# ---------------------------------------------------------------- the four strategies

class CompareStrategies(Near):
    def compare(self, **kw):
        return F.compare_strategies(land_parcel(**kw), DECIDE)

    # Sold a year from now for 10,000,000 (no appreciation, no cost): 10,000,000 / 1.1 = 9,090,909.09 whatever the horizon.
    def test_sale_npv_by_hand(self):
        s = self.compare()["strategies"]["fee_simple_sale"]
        self.near(s["npv_by_horizon_usd"]["10"], 9090909.09)
        self.near(s["npv_by_horizon_usd"]["15"], 9090909.09)
        self.near(s["upfront_cash_usd"], 10000000.0)
        self.near(s["capital_required_usd"], 0.0)
        self.assertEqual(s["first_cash_month"], 12)

    def test_selling_cost_and_appreciation_change_the_sale(self):
        out = F.compare_strategies(land_parcel(appreciation_pct=5), {**DECIDE, "sale_cost_pct": 4})
        # 10,000,000 x 1.05 x 0.96 = 10,080,000 a year from now, discounted at 10%: 9,163,636.36
        self.near(out["strategies"]["fee_simple_sale"]["npv_by_horizon_usd"]["10"], 9163636.36)

    # Rent 600,000 a year (6% of 10,000,000), years 1..10, plus the leased fee sold at the end of year 10 for the next rent / 6% = 10,000,000.
    # Ten-year annuity factor at 10% is 6.1445671: 3,686,740.26 + 10,000,000 / 1.1^10 (3,855,432.89) = 7,542,173.16.
    # Fifteen years: annuity 7.6060795 -> 4,563,647.70 + 10,000,000 / 1.1^15 (2,393,920.49) = 6,957,568.20.
    def test_ground_lease_npv_by_hand(self):
        s = self.compare()["strategies"]["ground_lease"]
        self.near(s["npv_by_horizon_usd"]["10"], 7542173.16)
        self.near(s["npv_by_horizon_usd"]["15"], 6957568.20)
        self.near(s["recurring_income_usd_yr"], 600000.0)
        self.near(s["capital_required_usd"], 0.0)
        self.assertIn("NNN ground lease", s["basis"])

    # Escalation 2.5% a year: rent in year 3 is 600,000 x 1.025^2 = 630,375; a 10% bump every 5 years: year 6 rent is 660,000.
    def test_ground_lease_escalations(self):
        g = land_parcel()["ground_lease"]
        esc = F.compare_strategies(land_parcel(ground_lease={**g, "escalation_pct": 2.5, "include_terminal_value": False}), {**DECIDE, "horizons_years": [3]})
        # 600,000 / 1.1 + 615,000 / 1.21 + 630,375 / 1.331 = 545,454.55 + 508,264.46 + 473,610.07 = 1,527,329.08
        self.near(esc["strategies"]["ground_lease"]["npv_by_horizon_usd"]["3"], 1527329.08)
        bump = F.compare_strategies(land_parcel(ground_lease={**g, "escalation_pct": None, "bump_pct": 10, "bump_years": 5, "include_terminal_value": False}),
                                    {**DECIDE, "horizons_years": [6]})
        # years 1-5 at 600,000 (annuity 3.7907868 -> 2,274,472.07) and year 6 at 660,000 / 1.1^6 = 372,552.79: 2,647,024.86
        self.near(bump["strategies"]["ground_lease"]["npv_by_horizon_usd"]["6"], 2647024.86)

    def test_key_money_arrives_at_the_start(self):
        g = land_parcel()["ground_lease"]
        out = F.compare_strategies(land_parcel(ground_lease={**g, "key_money_pct": 5}), DECIDE)
        self.near(out["strategies"]["ground_lease"]["upfront_cash_usd"], 500000.0 + 600000.0)      # key money 5% of 10M, plus year 1 rent

    def test_a_ground_lease_term_outside_65_to_99_years_is_noted(self):
        g = land_parcel()["ground_lease"]
        out = F.compare_strategies(land_parcel(ground_lease={**g, "term_years": 40}), DECIDE)
        self.assertTrue(any("65-99" in n for n in out["strategies"]["ground_lease"]["notes"]))
        ok = F.compare_strategies(land_parcel(ground_lease={**g, "term_years": 99}), DECIDE)
        self.assertEqual(ok["strategies"]["ground_lease"]["notes"], [])

    # Develop: 30,000,000 spent as 15,000,000 in each of years 1 and 2; the owner must find that capital.
    def test_hold_and_develop_needs_the_capital(self):
        s = self.compare()["strategies"]["hold_develop"]
        self.near(s["capital_required_usd"], 30000000.0)
        self.assertIn("Develop and hold", s["basis"])
        self.assertLess(s["npv_by_horizon_usd"]["10"], self.compare()["strategies"]["fee_simple_sale"]["npv_by_horizon_usd"]["10"])

    # Land credit 80% of 10,000,000 = 8,000,000; partner cost 30,000,000: the land's share is 8 / 38 = 21.0526%; 2,000,000 cash at close.
    def test_joint_venture_share_and_cash_out_by_hand(self):
        s = self.compare()["strategies"]["joint_venture"]
        self.near(s["jv_equity_share_pct"], 21.0526, 3)
        self.near(s["upfront_cash_usd"], 2000000.0)
        self.near(s["capital_required_usd"], 0.0)

    def test_a_joint_venture_without_project_figures_is_unavailable_with_a_reason(self):
        out = F.compare_strategies(land_parcel(develop=None, jv=None), DECIDE)
        jv = out["strategies"]["joint_venture"]
        self.assertFalse(jv["available"])
        self.assertIn("project cost", jv["why"])

    def test_without_development_inputs_hold_is_a_land_hold_and_says_so(self):
        out = F.compare_strategies(land_parcel(develop=None, appreciation_pct=0, carry_cost_usd_per_year=100000), DECIDE)
        h = out["strategies"]["hold_develop"]
        # carry 100,000 a year for ten years (annuity 6.1445671 = 614,456.71) and the land sold at the end for 10,000,000 / 1.1^10 = 3,855,432.89
        self.near(h["npv_by_horizon_usd"]["10"], 3855432.89 - 614456.71)
        self.assertTrue(any("land hold" in n for n in h["notes"]))

    def test_ranking_is_by_npv_over_the_last_horizon(self):
        out = self.compare()
        self.assertEqual(out["ranking_by_npv"][0], "fee_simple_sale")
        npvs = [out["strategies"][s]["npv_by_horizon_usd"]["15"] for s in out["ranking_by_npv"]]
        self.assertEqual(npvs, sorted(npvs, reverse=True))

    def test_the_nine_criteria_are_scored_zero_to_one_hundred_for_each_strategy(self):
        s = self.compare()["strategies"]
        for name, r in s.items():
            self.assertEqual(len(r["criteria_scores"]), 9, name)
            self.assertTrue(all(0 <= v <= 100 for v in r["criteria_scores"].values() if v is not None), name)
            self.assertTrue(0 <= r["economic_score"] <= 100, name)
        # the sale pays the most in the first 12 months, so it is the best (100) on that criterion
        self.assertEqual(s["fee_simple_sale"]["criteria_scores"]["upfront_cash"], 100.0)
        self.assertEqual(s["fee_simple_sale"]["criteria_scores"]["capital_required"], 100.0)       # lower is better: zero capital
        self.assertEqual(s["hold_develop"]["criteria_scores"]["capital_required"], 0.0)

    def test_criteria_weights_are_inputs(self):
        only_risk = {c["id"]: 0 for c in F.default_economic_criteria()}
        only_risk["execution_risk"] = 1
        out = F.compare_strategies(land_parcel(), DECIDE, criteria_weights=only_risk)
        # risk scores 90 sale, 30 develop, 60 JV, 85 lease -> scaled across the four: sale 100, develop 0, JV 50, lease 91.67
        scores = {k: v["economic_score"] for k, v in out["strategies"].items()}
        self.near(scores["fee_simple_sale"], 100.0)
        self.near(scores["hold_develop"], 0.0)
        self.near(scores["joint_venture"], 50.0)
        self.near(scores["ground_lease"], 91.67)

    def test_the_two_horizons_can_be_changed_and_both_are_reported(self):
        out = F.compare_strategies(land_parcel(), {**DECIDE, "horizons_years": [5, 20]})
        self.assertEqual(set(out["strategies"]["ground_lease"]["npv_by_horizon_usd"]), {"5", "20"})

    def test_no_land_value_makes_every_strategy_unavailable_with_a_reason(self):
        out = F.compare_strategies({"id": "x"}, DECIDE)
        self.assertTrue(all(not s["available"] for s in out["strategies"].values()))
        self.assertTrue(finite_everywhere(out))


# ---------------------------------------------------------------- the decision and the critical-asset flag

def hold_or_sell(score, **kw):
    """Land with only two choices, sell now or hold (no ground lease, no JV, no development), where selling is clearly the better economics."""
    return {"id": "K", "land_value_usd": 10000000, "appreciation_pct": 0, "carry_cost_usd_per_year": 100000, "strategic_score": score, **kw}


class Decision(Near):
    # Selling beats holding on almost every economic criterion, so a parcel the strategy scores 30 is sold with no conflict.
    def test_an_ordinary_parcel_is_recommended_for_sale_without_a_conflict(self):
        out = F.decide_parcels([hold_or_sell(30)], DECIDE)
        row = out["parcels"][0]
        self.assertEqual(row["recommended_strategy"], "fee_simple_sale")
        self.assertEqual(row["guarded_recommendation"], "fee_simple_sale")
        self.assertFalse(row["critical_strategic_asset"])
        self.assertEqual(row["conflicts"], [])

    # The same economics for a parcel scored 90: the engine still sees the sale as best on economics (so it is flagged), but the guarded
    # recommendation moves to the best non-sale strategy.
    def test_a_critical_parcel_recommended_for_sale_is_flagged_and_guarded(self):
        out = F.decide_parcels([hold_or_sell(90)], DECIDE)
        row = out["parcels"][0]
        self.assertTrue(row["critical_strategic_asset"])
        self.assertEqual(row["recommended_strategy"], "fee_simple_sale")
        self.assertEqual(row["guarded_recommendation"], "hold_develop")
        self.assertEqual([c["kind"] for c in row["conflicts"]], ["recommendation_is_sale"])
        self.assertEqual(out["critical_asset_conflicts"]["conflict_count"], 1)

    def test_the_cash_plan_selling_a_critical_parcel_is_a_conflict(self):
        out = F.decide_parcels([hold_or_sell(90), {**hold_or_sell(20), "id": "L"}], DECIDE, sell_ids=["K", "L"])
        kinds = [(c["parcel_id"], c["kind"]) for c in out["critical_asset_conflicts"]["conflicts"]]
        self.assertIn(("K", "cash_plan_sells_critical_asset"), kinds)
        self.assertNotIn("L", [k[0] for k in kinds])

    def test_the_strategic_score_is_built_from_the_dimension_scores(self):
        p = hold_or_sell(None, strategic_scores={"placemaking_gravity": 90, "scarcity": 80, "buyer_liquidity": 100})
        del p["strategic_score"]
        row = F.decide_parcels([p], DECIDE)["parcels"][0]
        self.near(row["strategic_score"], 90.0)            # (90 + 80 + 100) / 3
        self.assertTrue(row["critical_strategic_asset"])

    def test_the_critical_threshold_and_the_flags_are_inputs(self):
        self.assertTrue(F.decide_parcels([hold_or_sell(60)], {**DECIDE, "critical_threshold": 50})["parcels"][0]["critical_strategic_asset"])
        self.assertFalse(F.decide_parcels([hold_or_sell(90)], {**DECIDE, "critical_threshold": 95})["parcels"][0]["critical_strategic_asset"])
        self.assertTrue(F.decide_parcels([hold_or_sell(10, critical=True)], DECIDE)["parcels"][0]["critical_strategic_asset"])

    def test_with_no_strategic_influence_the_economics_alone_decide(self):
        row = F.decide_parcels([hold_or_sell(90)], {**DECIDE, "strategic_influence": 0})["parcels"][0]
        self.assertEqual(row["combined_scores"]["fee_simple_sale"], row["comparison"]["strategies"]["fee_simple_sale"]["economic_score"])

    # combined = (1 - k) x economic + k x (strategic x control kept + (100 - strategic) x (1 - control kept)); the sale keeps 0% control,
    # so for strategic score 30 and k 0.3 the strategic part of the sale is 0.3 x (30 x 0 + 70 x 1) = 21.
    def test_the_combined_score_formula(self):
        row = F.decide_parcels([hold_or_sell(30)], DECIDE)["parcels"][0]
        econ = row["comparison"]["strategies"]["fee_simple_sale"]["economic_score"]
        self.near(row["combined_scores"]["fee_simple_sale"], 0.7 * econ + 21.0)

    def test_planned_sales_inside_a_do_not_sell_period_are_flagged(self):
        out = F.critical_asset_conflicts([{"id": "A", "strategic_score": 40, "do_not_sell_until_month": 36, "planned_sale_month": 12},
                                          {"id": "B", "strategic_score": 40, "do_not_sell_until_month": 36, "planned_sale_month": 40}])
        self.assertEqual([(c["parcel_id"], c["kind"]) for c in out["conflicts"]], [("A", "sold_inside_hold_period")])

    def test_recommendation_counts_and_no_input(self):
        out = F.decide_parcels([hold_or_sell(30), {**hold_or_sell(30), "id": "M"}], DECIDE)
        self.assertEqual(out["recommendation_counts"]["fee_simple_sale"], 2)
        self.assertTrue(finite_everywhere(F.decide_parcels(None)))
        self.assertTrue(finite_everywhere(F.decide_parcels([{}])))

    def test_a_full_parcel_with_all_four_strategies_gets_a_recommendation(self):
        row = F.decide_parcels([land_parcel(strategic_score=60)], DECIDE)["parcels"][0]
        self.assertIn(row["recommended_strategy"], ("fee_simple_sale", "hold_develop", "joint_venture", "ground_lease"))
        self.assertEqual(len(row["combined_scores"]), 4)


# ---------------------------------------------------------------- infrastructure

def items():
    """RD-1 owner, 4,200,000, due month 12; UT-1 owner, cost not known, due month 14; PK-1 builder, 9,500,000, month 30; X-1: who pays is not known."""
    return [{"code": "RD-1", "name": "Spine road", "phase": 1, "cost_usd": 4200000, "responsible": "owner", "due_period": 12},
            {"code": "UT-1", "name": "Sewer trunk", "phase": 1, "cost_usd": None, "responsible": "Owner", "due_period": 14},
            {"code": "PK-1", "name": "Parking", "phase": 2, "cost_usd": 9500000, "responsible": "builder", "due_period": 30},
            {"code": "X-1", "name": "Gateway", "phase": 2, "cost_usd": 800000, "responsible": "???", "due_period": None}]


class InfrastructureRegister(Near):
    def test_totals_say_how_many_costs_are_not_known_and_never_count_them_as_zero(self):
        reg = F.infrastructure_register(items())
        self.near(reg["total"]["known_usd"], 14500000.0)
        self.assertEqual(reg["total"]["unknown_count"], 1)
        self.assertFalse(reg["total"]["complete"])
        self.assertIn("1 item not known", reg["total"]["display"])
        sewer = next(i for i in reg["items"] if i["code"] == "UT-1")
        self.assertIsNone(sewer["cost_usd"])
        self.assertEqual(sewer["cost_label"], "not known")

    def test_by_payer_and_by_phase(self):
        reg = F.infrastructure_register(items())
        self.near(reg["by_payer"]["owner"]["known_usd"], 4200000.0)
        self.assertEqual(reg["by_payer"]["owner"]["unknown_count"], 1)
        self.near(reg["by_payer"]["builder"]["known_usd"], 9500000.0)
        self.assertEqual(reg["by_payer"]["not_known"]["item_count"], 1)
        self.assertEqual(reg["items_with_unknown_payer"], 1)
        self.assertEqual(reg["items_with_unknown_timing"], 1)
        self.assertEqual(reg["by_phase"]["1"]["unknown_count"], 1)
        self.assertEqual(reg["by_phase"]["2"]["unknown_count"], 0)

    def test_payer_words_are_understood(self):
        reg = F.infrastructure_register([{"cost_usd": 1, "responsible": "Sponsor"}, {"cost_usd": 1, "responsible": "CFD"}, {"cost_usd": 1, "responsible": "County"}])
        self.assertEqual(reg["by_payer"]["owner"]["item_count"], 1)
        self.assertEqual(reg["by_payer"]["district_financing"]["item_count"], 1)
        self.assertEqual(reg["by_payer"]["city"]["item_count"], 1)

    def test_an_empty_register(self):
        reg = F.infrastructure_register(None)
        self.assertEqual(reg["total"]["item_count"], 0)
        self.assertTrue(finite_everywhere(reg))


class InfrastructureGap(Near):
    # Periods end at months 6, 12, 18, 24. The spine road (4,200,000, owner) is due in month 12; the sewer trunk (owner, cost not known) in month 14,
    # so it falls in the period ending month 18. Land sales bring 5,000,000 in month 18; a district bond brings 1,000,000 in month 12.
    # Month 12: cost 4,200,000 - funding 1,000,000 = a shortfall of 3,200,000.
    # Month 18: funding 6,000,000 against 4,200,000 known cost: 1,800,000 ahead - but one cost is not known, so that is "at least".
    def test_the_gap_by_period_by_hand(self):
        g = F.infrastructure_funding_gap(items(), [6, 12, 18, 24], {18: 5000000}, [{"period": 12, "amount_usd": 1000000, "source": "bond"}])
        rows = {r["period"]: r for r in g["rows"]}
        self.near(rows[6]["cumulative_gap_usd"], 0.0)
        self.near(rows[12]["owner_cost_known_usd"], 4200000.0)
        self.near(rows[12]["cumulative_gap_usd"], 3200000.0)
        self.assertEqual(rows[12]["status"], "shortfall")
        self.assertFalse(rows[12]["gap_is_lower_bound"])
        self.near(rows[18]["cumulative_gap_usd"], -1800000.0)
        self.assertEqual(rows[18]["owner_items_unknown_cost"], 1)
        self.assertTrue(rows[18]["gap_is_lower_bound"])
        self.near(g["summary"]["peak_gap_usd"], 3200000.0)
        self.assertEqual(g["summary"]["peak_gap_period"], 12)
        self.assertTrue(g["summary"]["peak_gap_is_lower_bound"])
        self.assertEqual(g["summary"]["owner_items_unknown_cost"], 1)
        self.assertEqual(g["summary"]["items_with_unknown_payer"], 1)

    def test_items_another_party_pays_are_shown_but_not_counted_against_the_owner(self):
        g = F.infrastructure_funding_gap(items(), [36])
        self.near(g["summary"]["owner_cost_known_usd"], 4200000.0)
        self.near(g["paid_by_others"]["builder"]["known_usd"], 9500000.0)

    def test_items_after_the_last_period_and_undated_items_are_reported(self):
        its = items() + [{"code": "L", "cost_usd": 700000, "responsible": "owner", "due_period": 60}, {"code": "U", "cost_usd": 100000, "responsible": "owner"}]
        g = F.infrastructure_funding_gap(its, [12, 24])
        self.assertEqual(g["summary"]["owner_items_after_horizon"], 1)
        self.near(g["summary"]["owner_cost_after_horizon_known_usd"], 700000.0)
        self.assertEqual(g["summary"]["owner_items_undated"], 1)
        self.assertTrue(g["summary"]["peak_gap_is_lower_bound"])

    def test_land_sale_proceeds_can_be_a_list_aligned_with_the_periods(self):
        g = F.infrastructure_funding_gap(items(), [12, 24], [3000000, 2000000])
        self.near(g["rows"][0]["land_sale_proceeds_usd"], 3000000.0)
        self.near(g["rows"][1]["cumulative_funding_usd"], 5000000.0)

    def test_no_periods_or_items_do_not_raise(self):
        self.assertTrue(finite_everywhere(F.infrastructure_funding_gap(None, None)))
        self.assertEqual(F.infrastructure_funding_gap(items(), [])["rows"], [])


# ---------------------------------------------------------------- fiscal and EIFD

class Fiscal(Near):
    RATES = {"construction_jobs_per_million_usd": 5, "jobs_per_1000_sf_by_use": {"shops": 2, "office": 4}, "construction_output_multiplier": 1.5,
             "operating_output_multiplier": 1.2, "sales_tax_rate_pct": 1, "property_tax_rate_pct": 1, "city_property_tax_share_pct": 20, "hotel_tax_pct": 10}
    PHASE = {"id": "f1", "label": "Phase 1", "construction_cost_usd": 20000000, "building_sf_by_use": {"shops": 30000, "office": 10000},
             "taxable_sales_usd_yr": 30000000, "hotel_room_revenue_usd_yr": 5000000, "assessed_value_usd": 50000000}

    # Construction: 20 x 5 = 100 job-years; output 20,000,000 x 1.5 = 30,000,000. Permanent: 30 x 2 + 10 x 4 = 100 jobs.
    # Operating output (30,000,000 + 5,000,000) x 1.2 = 42,000,000. Sales tax 1% of 30,000,000 = 300,000. Property tax 1% of 50,000,000 = 500,000,
    # of which the agency's 20% is 100,000. Hotel tax 10% of 5,000,000 = 500,000. Agency revenue 300,000 + 100,000 + 500,000 = 900,000.
    def test_every_figure_by_hand(self):
        out = F.fiscal_impact([self.PHASE], self.RATES)
        p = out["phases"][0]
        self.near(p["construction_job_years"], 100.0, 1)
        self.near(p["permanent_jobs"], 100.0, 1)
        self.near(p["construction_output_usd"], 30000000.0)
        self.near(p["annual_operating_output_usd"], 42000000.0)
        self.near(p["sales_tax_usd_yr"], 300000.0)
        self.near(p["property_tax_usd_yr"], 500000.0)
        self.near(p["agency_property_tax_usd_yr"], 100000.0)
        self.near(p["hotel_tax_usd_yr"], 500000.0)
        self.near(p["annual_agency_revenue_usd"], 900000.0)
        self.assertEqual(out["components_not_worked_out"], 0)

    def test_a_rate_that_was_not_given_is_not_assumed(self):
        out = F.fiscal_impact([self.PHASE], {"sales_tax_rate_pct": 1})
        p = out["phases"][0]
        self.near(p["sales_tax_usd_yr"], 300000.0)
        self.assertIsNone(p["property_tax_usd_yr"])
        self.assertIsNone(p["hotel_tax_usd_yr"])
        self.assertIsNone(p["construction_job_years"])
        self.assertTrue(any("property_tax_rate_pct" in m for m in p["not_worked_out"]))
        self.assertGreater(out["components_not_worked_out"], 3)

    def test_two_phases_add_up(self):
        out = F.fiscal_impact([self.PHASE, {**self.PHASE, "id": "f2"}], self.RATES)
        self.near(out["totals"]["annual_agency_revenue_usd"], 1800000.0)
        self.near(out["totals"]["permanent_jobs"], 200.0, 1)

    def test_permanent_jobs_can_be_given_directly(self):
        out = F.fiscal_impact([{"id": "x", "permanent_jobs": 42}], {})
        self.assertEqual(out["phases"][0]["permanent_jobs"], 42.0)

    def test_nothing_given(self):
        self.assertTrue(finite_everywhere(F.fiscal_impact(None, None)))


class EifdIncrement(Near):
    # Assessed value 50,000,000 delivered in year 3, no base value, 1% tax rate, half of it shared with the district, value growing 2% a year.
    # Year 3: 50,000,000 x 1% x 50% = 250,000. Year 4: x 1.02 = 255,000. Year 5: 260,100. Years 1-2: nothing. Five years: 765,100.
    def test_the_increment_by_hand(self):
        out = F.eifd_increment([{"id": "a", "assessed_value_usd": 50000000, "delivery_year": 3}], 1, 50, years=5, assessed_growth_pct=2)
        self.assertEqual([y["increment_usd"] for y in out["yearly"]], [0.0, 0.0, 250000.0, 255000.0, 260100.0])
        self.near(out["total_increment_usd"], 765100.0)
        self.near(out["yearly"][-1]["cumulative_usd"], 765100.0)
        self.assertIsNone(out["present_value_usd"])

    # A base value of 10,000,000 is not part of the increment: (50,000,000 - 10,000,000) x 1% x 50% = 200,000 in the first year of delivery.
    def test_a_base_value_is_taken_off(self):
        out = F.eifd_increment([{"id": "a", "assessed_value_usd": 50000000, "base_assessed_value_usd": 10000000, "delivery_year": 1}], 1, 50, years=1)
        self.near(out["total_increment_usd"], 200000.0)

    def test_phases_add_and_a_present_value_needs_a_discount_rate(self):
        ph = [{"id": "a", "assessed_value_usd": 50000000, "delivery_year": 1}, {"id": "b", "assessed_value_usd": 50000000, "delivery_year": 2}]
        out = F.eifd_increment(ph, 1, 50, years=2, assessed_growth_pct=0, discount_rate_pct=10)
        self.assertEqual([y["increment_usd"] for y in out["yearly"]], [250000.0, 500000.0])
        self.near(out["present_value_usd"], 250000 / 1.1 + 500000 / 1.21)

    def test_a_phase_with_no_assessed_value_is_reported_not_zeroed(self):
        out = F.eifd_increment([{"id": "a"}], 1, 50, years=3)
        self.assertIn("not known", out["by_phase"][0]["why"])
        self.assertIsNone(out["by_phase"][0]["total_usd"])

    def test_missing_rates_say_why(self):
        self.assertTrue(F.eifd_increment([{"id": "a", "assessed_value_usd": 1}], None, None)["why"])


# ---------------------------------------------------------------- the whole API

class WholeApi(unittest.TestCase):
    def test_every_public_function_is_listed_in_the_docs(self):
        docs = (ROOT / "docs" / "district-finance.md").read_text(encoding="utf-8")
        missing = [name for name in F.PUBLIC_FUNCTIONS if f"`{name}(" not in docs and f"### {name}" not in docs]
        self.assertEqual(missing, [])

    def test_there_are_the_functions_the_brief_asks_for(self):
        for name in ("residual_land_value_by_use", "residual_land_value_by_parcel", "pricing_tiers", "gross_to_net_waterfall", "solve_capital_targets",
                     "phase_pro_forma", "full_buildout_pro_forma", "break_even", "decide_parcels", "compare_strategies", "absorption_schedule",
                     "evaluate_phasing_triggers", "run_scenarios", "sensitivity_tornado", "retained_land_value", "paced_land_releases",
                     "infrastructure_register", "infrastructure_funding_gap", "fiscal_impact", "eifd_increment", "reconcile_program"):
            self.assertIn(name, F.PUBLIC_FUNCTIONS)

    def test_no_source_file_grows_past_about_nine_hundred_lines(self):
        for path in (ROOT / "landplanner" / "district").glob("finance*.py"):
            self.assertLess(len(path.read_text(encoding="utf-8").splitlines()), 900, path.name)

    def test_no_project_names_from_the_private_brief_are_in_the_tracked_files(self):
        words = ["Hill" + "top", "Leg" + "acy Asset", "Hoff" + "man", "HTD" + "-RFP", "APN 36" + "0", "Studio One" + " Eleven", "Sargent" + " Town"]
        paths = list((ROOT / "landplanner" / "district").glob("finance*.py")) + list((ROOT / "tests").glob("test_district_finance*.py")) \
            + [ROOT / "docs" / "district-finance.md"]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for w in words:
                self.assertNotIn(w, text, f"{w} in {path.name}")

    def test_no_output_says_market_value_opinion_as_a_claim(self):
        out = F.pricing_tiers({"gross_ac": 1, "net_ac": 1, "cost_basis_usd": 1000}, 2000)
        self.assertIn("not an appraisal", out["disclaimer"])
        self.assertIn("not a value opinion", out["tiers"]["target_market"]["label"])


def _worlds():
    """Inputs for every kind of function, with one slot `x` that the test fills with a degenerate value."""
    parcels = [{"id": "A", "net_ac": 8, "gross_ac": 10, "gross_price_usd": 8000000, "strategic_score": 30, "close_month": 12, "stub_per_net_ac_usd": 50000, "use": "apartments"}]
    ph = {"id": "p1", "land_cost_usd": 1000000, "lines": [{"use": "apartments", "net_ac": 5}, {"use": "townhomes", "units": 40}]}
    ap = {"base_year": 2027, "hurdle_yoc_pct": 6.5, "hurdle_irr_pct": 12}
    dp = land_parcel(strategic_scores={"scarcity": 80})
    return parcels, ph, ap, dp


def _calls(x, parcels, ph, ap, dp, lib):
    return {
        "rlv_use": lambda: F.residual_land_value_by_use(lib),
        "rlv_parcel": lambda: F.residual_land_value_by_parcel(parcels, lib),
        "tiers": lambda: F.pricing_tiers({"gross_ac": 10, "net_ac": 8, "cost_items": {"a": x, "b": 5}}, x, x, x, x),
        "waterfall": lambda: F.gross_to_net_waterfall(x, x, x, x, x, x, x, x, x),
        "solver": lambda: F.solve_capital_targets(parcels, [{"month": x, "amount_usd": x}]),
        "pro_forma": lambda: F.full_buildout_pro_forma([ph], lib, ap),
        "break_even": lambda: F.break_even(ph, lib, ap, "apartment_rent"),
        "break_even_cap": lambda: F.break_even(ph, lib, ap, "exit_cap_rate"),
        "scenarios": lambda: F.run_scenarios({"library": lib, "parcels": parcels, "phases": [ph], "assumptions": ap}),
        "decide": lambda: F.decide_parcels([dp]),
        "absorption": lambda: F.absorption_schedule(x, x, None, x, x, x),
        "retained": lambda: F.retained_land_value(x, x, x, x),
        "paced": lambda: F.paced_land_releases(x, x, x, x, 15, x),
        "infra": lambda: F.infrastructure_funding_gap([{"cost_usd": x, "responsible": "owner", "due_period": x}], [x, 12]),
        "eifd": lambda: F.eifd_increment([{"assessed_value_usd": x, "delivery_year": x}], x, x, x, x, x),
        "irr": lambda: F.cash_flow_metrics([x, -5, x, 10], x),
        "fiscal": lambda: F.fiscal_impact([{"construction_cost_usd": x, "taxable_sales_usd_yr": x}], {"sales_tax_rate_pct": x, "construction_jobs_per_million_usd": x}),
        "reconcile": lambda: F.reconcile_program(x, [x, 1]),
    }


def has_failed(obj):
    if isinstance(obj, dict):
        return obj.get("failed") is True or any(has_failed(v) for v in obj.values())
    if isinstance(obj, list):
        return any(has_failed(v) for v in obj)
    return False


class Stability(unittest.TestCase):
    """Zero, negative, missing, tiny and enormous numbers never raise, never give NaN or Infinity."""

    def test_degenerate_values_in_every_slot(self):
        for x in (0, -1, None, 1e-12, 1e308, -0.5):
            parcels, ph, ap, dp = _worlds()
            for name, call in _calls(x, parcels, ph, ap, dp, library()).items():
                out = call()
                self.assertTrue(finite_everywhere(out), f"{name} with {x!r}")
                if x != 1e308:
                    self.assertFalse(has_failed(out), f"{name} with {x!r} failed")

    def test_each_number_of_each_input_set_to_zero_or_missing_in_turn(self):
        def leaves(o, path=()):
            if isinstance(o, dict):
                for k, v in o.items():
                    yield from leaves(v, path + (k,))
            elif isinstance(o, list):
                for i, v in enumerate(o):
                    yield from leaves(v, path + (i,))
            elif isinstance(o, (int, float)) and not isinstance(o, bool):
                yield path

        def put(o, path, v):
            for k in path[:-1]:
                o = o[k]
            o[path[-1]] = v

        parcels, ph, ap, dp = _worlds()
        base = {"lib": library(), "parcels": parcels, "ph": ph, "ap": ap, "dp": dp}
        for key in base:
            for path in list(leaves(base[key])):
                for bad in (0, None):
                    world = copy.deepcopy(base)
                    put(world[key], path, bad)
                    for name, call in _calls(1.0, world["parcels"], world["ph"], world["ap"], world["dp"], world["lib"]).items():
                        if name == "break_even_cap":            # the slow one; break_even itself is still run
                            continue
                        out = call()
                        self.assertTrue(finite_everywhere(out), f"{name}: {key}{path} = {bad!r}")
                        self.assertFalse(has_failed(out), f"{name}: {key}{path} = {bad!r}")


if __name__ == "__main__":
    unittest.main()
