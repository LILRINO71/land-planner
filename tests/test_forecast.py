"""The forecast engine (landplanner/forecast.py) on small hand-made facts. No fixtures, no network.

The facts are built here in the shapes cities/base.py documents. The standard set is "round" on purpose: in the 3 mile
ring there are 10,000 homes counted in 2020, none gained since 2010 (a 0% reading), the adopted regional plan adds
10% a year (2019 to 2021) and the draft one 21% a year (2024 to 2026). So the low line is 0%, the expected line 10% and
the high line 21%, and a year of the forecast can be worked out by hand: homes in year y = 10,000 x 1.1 ^ (y - 2020).
Wording is not tested, only behaviour and arithmetic; a few tests look for one key word where a sentence is the only
place a fact is stated.
"""
import copy
import json
import unittest

import support  # noqa: F401  (puts the project folder on the import path)
from landplanner import forecast as F

YEAR = 2026
YEARS = list(range(2025, 2037))          # last year for background, this year, ten more
FUTURE = YEARS[2:]
SIZES = ((1, 1000), (3, 10000), (5, 30000))


# ---------------------------------------------------------------- hand-made facts

def census(year, one, three, five):
    return {"year": year, "source": "Test census",
            "rings": [{"miles": m, "people": 3 * h, "homes": h} for m, h in ((1, one), (3, three), (5, five))]}


def region():
    return {"within_miles": 5, "source": "Test agency",
            "adopted": {"label": "Adopted plan", "years": [2019, 2021, 2050], "zones": 9,
                        "rings": [{"miles": m, "households": {"2019": h, "2021": round(h * 1.21), "2050": 3 * h},
                                   "jobs": {"2019": 1000, "2021": 1300, "2050": 3000}} for m, h in SIZES]},
            "draft": {"label": "Draft plan", "years": [2024, 2026, 2050], "zones": 9,
                      "rings": [{"miles": m, "households": {"2024": h, "2026": round(h * 1.4641), "2050": 4 * h},
                                 "jobs": {"2024": 1000, "2026": 1100, "2050": 2000}} for m, h in SIZES]},
            "city": {"name": "Testville", "households": {"2019": 50000.0, "2050": 90000.0},
                     "jobs": {"2019": 20000.0, "2050": 40000.0}}}


def tract(name="Tract 1", income=100000, households=1000, renters=200, miles=1.0, direction="north", share=None, **more):
    t = {"id": name, "name": name, "income": income, "households": households, "owners": households - renters,
         "renters": renters, "homes": households + 50, "built_2020_on": 40, "lat": 33.65, "lon": -117.17,
         "miles_away": miles, "direction": direction, "share_within": share or {"1": 1.0, "3": 1.0, "5": 1.0}}
    t.update(more)
    return t


def survey(*tracts, county_income=100000):
    return {"within_miles": 5.0, "source": "Test survey", "survey": {"income": "2018-2022", "homes": "2018-2022"},
            "county": {"name": "Test County", "income": county_income}, "tracts": list(tracts) or [tract()]}


def project(kind, status, homes=None, feet=None, miles=1.0, **more):
    stated = {}
    if homes is not None:
        stated["homes"] = homes
    if feet is not None:
        stated["building_sq_ft"] = feet
    p = {"title": f"{kind} {status}", "kind": kind, "status": status, "stated": stated, "miles_away": miles}
    p.update(more)
    return p


def projects(*rows, updated=None):
    return {"within_miles": 3.0, "projects": list(rows), "lists_updated": updated or {}, "source": "Test city"}


def make_parts():
    return {"people": census(2020, 1000, 10000, 30000), "people_before": census(2010, 1000, 10000, 30000),
            "regional_plan": region(), "tracts": survey(), "projects": projects(),
            "state_highway_traffic": {"stations": [{"route": "215", "where": "SCOTT ROAD", "vehicles_per_day_behind": "100000",
                                                    "vehicles_per_day_ahead": "90000", "miles_away": 2.0}]}}


def use(use_id, label, acres, homes=None, sq_ft=None):
    u = {"id": use_id, "label": label, "short": label, "colour": "#000", "acres": acres}
    if homes is not None:
        u["homes"] = homes
    if sq_ft is not None:
        u["sq_ft"] = sq_ft
    return u


def make_plans():
    return [{"uses": [use("retail", "Shops", 10.0, sq_ft=100000), use("office", "Offices", 5.0, sq_ft=60000),
                      use("apartments", "Apartments", 20.0, homes=400), use("homes", "Houses", 40.0, homes=200),
                      use("business", "Business park", 20.0, sq_ft=200000), use("park", "Parks", 5.0)],
             "traffic": {"by_use": {"retail": 5000, "office": 600, "apartments": 2400, "homes": 2000, "business": 800}}}]


def forecast(parts=None, plans=None, settings=None, year=YEAR):
    return F.make_forecast({"apns": ["1"]}, make_parts() if parts is None else parts,
                           make_plans() if plans is None else plans, settings, year)


def changed(change, **kw):
    parts = make_parts()
    change(parts)
    return forecast(parts, **kw)


def mine(**figures):
    return {"assumptions": figures}


def uses_by_id(out):
    return {u["id"]: u for u in out["programme"]["uses"]}


def check_order(test, obj, where="", found=None):
    """Every {low, expected, high} (and {value, low, high}) in an answer is in order. Returns how many were checked."""
    found = found if found is not None else [0]
    if isinstance(obj, dict):
        if {"low", "expected", "high"} <= obj.keys():
            test.assertLessEqual(obj["low"], obj["expected"], where)
            test.assertLessEqual(obj["expected"], obj["high"], where)
            found[0] += 1
        if {"value", "low", "high"} <= obj.keys():
            test.assertLessEqual(obj["low"], obj["value"], where)
            test.assertLessEqual(obj["value"], obj["high"], where)
            found[0] += 1
        for key, value in obj.items():
            check_order(test, value, f"{where}/{key}", found)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            check_order(test, value, f"{where}[{i}]", found)
    return found[0]


# ---------------------------------------------------------------- the small helpers

class Numbers(unittest.TestCase):
    def test_num_reads_numbers_and_numeric_text(self):
        self.assertEqual(F.num(3), 3.0)
        self.assertEqual(F.num("12.5"), 12.5)
        self.assertEqual(F.num(" 7 "), 7.0)

    def test_num_gives_none_for_anything_that_is_not_a_finite_number(self):
        for junk in (None, "", "abc", [], {}, (), float("nan"), float("inf"), float("-inf"), "inf", "nan"):
            with self.subTest(junk=junk):
                self.assertIsNone(F.num(junk))

    def test_yearly_is_the_steady_rate_that_turns_a_into_b(self):
        self.assertAlmostEqual(F.yearly(100, 121, 2), 0.10)
        self.assertAlmostEqual(F.yearly(100, 100, 5), 0.0)
        self.assertAlmostEqual(F.yearly(121, 100, 2), -1 + (100 / 121) ** 0.5)
        self.assertAlmostEqual(F.yearly(100, 200, 1), 1.0)
        self.assertLess(F.yearly(121, 100, 2), 0)

    def test_yearly_has_no_answer_without_two_positive_counts_and_a_span(self):
        for a, b, years in ((None, 5, 2), (5, None, 2), (0, 5, 2), (5, 0, 2), (-1, 5, 2), (5, -1, 2), (5, 6, 0), (5, 6, -3)):
            with self.subTest(a=a, b=b, years=years):
                self.assertIsNone(F.yearly(a, b, years))

    def test_three_is_the_lowest_the_middle_and_the_highest(self):
        self.assertEqual(F.three([3, 1, 2]), {"low": 1, "expected": 2, "high": 3})
        self.assertEqual(F.three([0.0, 0.1, 0.21]), {"low": 0.0, "expected": 0.1, "high": 0.21})

    def test_three_with_one_reading_has_no_range(self):
        self.assertEqual(F.three([4]), {"low": 4, "expected": 4, "high": 4})
        self.assertEqual(F.three([4, None]), {"low": 4, "expected": 4, "high": 4})

    def test_three_with_no_reading_has_no_answer(self):
        self.assertIsNone(F.three([]))
        self.assertIsNone(F.three([None, None]))

    def test_three_ignores_missing_readings(self):
        self.assertEqual(F.three([None, 1, 5, None, 3]), {"low": 1, "expected": 3, "high": 5})

    def test_with_two_readings_the_expected_line_is_their_average(self):
        # documented here because "the middle reading" is then a number neither reading gave
        self.assertEqual(F.three([1, 3]), {"low": 1, "expected": 2, "high": 3})
        self.assertEqual(F.three([1, 2, 3, 10]), {"low": 1, "expected": 2.5, "high": 10})

    def test_each_runs_a_function_for_every_scenario(self):
        self.assertEqual(F.each(lambda s: s.upper()), {"low": "LOW", "expected": "EXPECTED", "high": "HIGH"})

    def test_money_and_percent_words(self):
        self.assertEqual(F.money(1234567.8), "$1,234,568")
        self.assertEqual(F.money(0), "$0")
        self.assertEqual(F.pct(0.0123), "1.2%")
        self.assertEqual(F.pct(0.0123, 2), "1.23%")

    def test_ring_of_finds_a_ring_by_its_distance(self):
        part = census(2020, 1, 2, 3)
        self.assertEqual(F.ring_of(part, 3)["homes"], 2)
        self.assertEqual(F.ring_of(part, 5)["homes"], 3)
        self.assertIsNone(F.ring_of(part, 2))
        self.assertIsNone(F.ring_of(None, 3))
        self.assertIsNone(F.ring_of({}, 3))
        self.assertIsNone(F.ring_of({"rings": None}, 3))

    def test_the_stages_are_read_from_the_cities_own_words(self):
        for status, stage in (("Under Construction", 0), ("App Pln Ap - Final Engineering", 1), ("App - Approved Planning", 2),
                              ("Planning Application - Under Review", 3), ("", 4), (None, 4), ("Withdrawn", 4),
                              ("UNDER CONSTRUCTION", 0), ("  approved ", 2)):
            with self.subTest(status=status):
                self.assertEqual(F.stage_of(status), stage)

    def test_a_project_that_is_approved_and_already_under_construction_is_under_construction(self):
        self.assertEqual(F.stage_of("Approved - Under Construction"), 0)

    def test_the_last_stage_is_the_one_with_no_words(self):
        self.assertEqual(F.STAGES[-1][0], "")
        self.assertEqual(F.stage_of("something else"), len(F.STAGES) - 1)


class CleanSettings(unittest.TestCase):
    def test_nothing_or_junk_gives_no_changes(self):
        for junk in (None, [], "x", 5, True, {}, {"assumptions": None}, {"assumptions": []}, {"assumptions": "spend_pct"}):
            with self.subTest(junk=junk):
                self.assertEqual(F.clean_settings(junk), {"assumptions": {}})

    def test_a_figure_inside_its_limits_is_kept_as_a_number(self):
        self.assertEqual(F.clean_settings({"assumptions": {"spend_pct": 40}}), {"assumptions": {"spend_pct": 40.0}})
        self.assertIsInstance(F.clean_settings({"assumptions": {"ready_years": 4}})["assumptions"]["ready_years"], float)

    def test_a_number_written_as_text_is_read(self):
        self.assertEqual(F.clean_settings({"assumptions": {"spend_pct": "40"}})["assumptions"], {"spend_pct": 40.0})

    def test_a_figure_that_equals_its_starting_value_is_not_a_change(self):
        for key, spec in F.ASSUMPTIONS.items():
            with self.subTest(key=key):
                self.assertEqual(F.clean_settings({"assumptions": {key: spec[2]}}), {"assumptions": {}})
                self.assertEqual(F.clean_settings({"assumptions": {key: str(spec[2])}}), {"assumptions": {}})

    def test_every_figure_is_clamped_to_its_limits(self):
        for key, spec in F.ASSUMPTIONS.items():
            low, high = spec[4], spec[5]
            with self.subTest(key=key):
                got = F.clean_settings({"assumptions": {key: high + 1000}})["assumptions"]
                self.assertEqual(got, {key: float(high)})
                got = F.clean_settings({"assumptions": {key: low - 1000}})["assumptions"]
                self.assertEqual(got, {key: float(low)})
                self.assertEqual(F.clean_settings({"assumptions": {key: 1e300}})["assumptions"], {key: float(high)})
                self.assertEqual(F.clean_settings({"assumptions": {key: -1e300}})["assumptions"], {key: float(low)})

    def test_the_limits_themselves_are_allowed(self):
        for key, spec in F.ASSUMPTIONS.items():
            with self.subTest(key=key):
                self.assertEqual(F.clean_settings({"assumptions": {key: spec[4]}})["assumptions"], {key: float(spec[4])})
                self.assertEqual(F.clean_settings({"assumptions": {key: spec[5]}})["assumptions"], {key: float(spec[5])})

    def test_every_starting_value_lies_inside_its_limits(self):
        for key, (label, unit, start, group, low, high) in F.ASSUMPTIONS.items():
            with self.subTest(key=key):
                self.assertLessEqual(low, start)
                self.assertLessEqual(start, high)
                self.assertTrue(label and unit and group)

    def test_unknown_figures_are_ignored(self):
        got = F.clean_settings({"assumptions": {"made_up": 5, "spend_pct": 45, "__proto__": 1, "": 2, 7: 3}})
        self.assertEqual(got, {"assumptions": {"spend_pct": 45.0}})

    def test_junk_values_are_ignored_and_the_good_ones_kept(self):
        got = F.clean_settings({"assumptions": {"spend_pct": None, "local_pct": "abc", "sales_per_sq_ft": [], "sq_ft_per_job": {},
                                                "traffic_follow_pct": float("nan"), "capture_pct": float("inf"),
                                                "ready_years": 5, "built_review_pct": ""}})
        self.assertEqual(got, {"assumptions": {"ready_years": 5.0}})

    def test_other_settings_are_not_kept(self):
        got = F.clean_settings({"mode": "best", "acres": {"homes": 5}, "land_cost": 9, "assumptions": {"spend_pct": 45}})
        self.assertEqual(got, {"assumptions": {"spend_pct": 45.0}})

    def test_the_answer_does_not_change_what_was_sent_and_cleaning_twice_changes_nothing(self):
        sent = {"assumptions": {"spend_pct": "45", "capture_pct": 900, "bogus": 1}}
        before = copy.deepcopy(sent)
        once = F.clean_settings(sent)
        self.assertEqual(sent, before)
        self.assertEqual(F.clean_settings(once), once)


# ---------------------------------------------------------------- readings of growth

class HomeReadings(unittest.TestCase):
    def test_a_ring_has_the_counted_growth_and_each_regional_forecast(self):
        got = F.home_readings(make_parts(), 3)
        self.assertEqual([r["id"] for r in got], ["measured", "adopted", "draft"])
        self.assertEqual([r["kind"] for r in got], ["measured", "official forecast", "official forecast"])
        self.assertEqual([r["rate_pct"] for r in got], [0.0, 10.0, 21.0])

    def test_each_reading_names_where_it_starts_and_ends_and_its_source(self):
        measured, adopted, draft = F.home_readings(make_parts(), 3)
        self.assertEqual((measured["from"], measured["to"]), ({"year": 2010, "homes": 10000}, {"year": 2020, "homes": 10000}))
        self.assertEqual((adopted["from"], adopted["to"]), ({"year": 2019, "homes": 10000}, {"year": 2021, "homes": 12100}))
        self.assertEqual((draft["from"], draft["to"]), ({"year": 2024, "homes": 10000}, {"year": 2026, "homes": 14641}))
        self.assertIn("2010 to 2020", measured["label"])
        self.assertIn("2019 to 2021", adopted["label"])
        self.assertIn("2024 to 2026", draft["label"])
        self.assertEqual((adopted["source"], draft["source"]), ("Adopted plan", "Draft plan"))
        self.assertIn("Census", measured["source"])

    def test_the_rate_is_the_steady_yearly_rate_between_the_two_counts(self):
        parts = make_parts()
        parts["people_before"]["rings"][1]["homes"] = 8000        # 8,000 to 10,000 in ten years
        measured = F.home_readings(parts, 3)[0]
        self.assertAlmostEqual(measured["rate_pct"], round(100 * ((10000 / 8000) ** 0.1 - 1), 2))
        self.assertAlmostEqual(measured["rate_pct"], 2.26)

    def test_each_ring_has_its_own_readings(self):
        for miles in (1, 3, 5):
            with self.subTest(miles=miles):
                got = F.home_readings(make_parts(), miles)
                self.assertEqual([r["rate_pct"] for r in got], [0.0, 10.0, 21.0])

    def test_a_ring_the_sources_do_not_have_has_no_readings(self):
        self.assertEqual(F.home_readings(make_parts(), 2), [])

    def test_without_the_earlier_census_there_is_no_counted_reading(self):
        parts = make_parts()
        del parts["people_before"]
        self.assertEqual([r["id"] for r in F.home_readings(parts, 3)], ["adopted", "draft"])

    def test_without_the_regional_plan_only_the_counted_reading_is_left(self):
        parts = make_parts()
        del parts["regional_plan"]
        self.assertEqual([r["id"] for r in F.home_readings(parts, 3)], ["measured"])
        parts["regional_plan"] = None
        self.assertEqual([r["id"] for r in F.home_readings(parts, 3)], ["measured"])

    def test_a_plan_the_agency_did_not_answer_is_skipped(self):
        parts = make_parts()
        parts["regional_plan"]["adopted"] = None
        self.assertEqual([r["id"] for r in F.home_readings(parts, 3)], ["measured", "draft"])
        parts["regional_plan"]["draft"] = None
        self.assertEqual([r["id"] for r in F.home_readings(parts, 3)], ["measured"])

    def test_nothing_known_means_no_readings(self):
        self.assertEqual(F.home_readings({}, 3), [])

    def test_a_ring_with_no_homes_in_the_earlier_count_has_no_counted_reading(self):
        parts = make_parts()
        parts["people_before"]["rings"][1]["homes"] = 0
        self.assertEqual([r["id"] for r in F.home_readings(parts, 3)], ["adopted", "draft"])

    def test_a_plan_zone_with_no_households_at_its_start_gives_no_reading(self):
        parts = make_parts()
        parts["regional_plan"]["adopted"]["rings"][1]["households"]["2019"] = 0
        self.assertEqual([r["id"] for r in F.home_readings(parts, 3)], ["measured", "draft"])

    def test_a_plan_with_a_missing_year_gives_no_reading(self):
        parts = make_parts()
        del parts["regional_plan"]["draft"]["rings"][1]["households"]["2026"]
        self.assertEqual([r["id"] for r in F.home_readings(parts, 3)], ["measured", "adopted"])

    def test_fewer_homes_than_before_is_a_negative_rate(self):
        parts = make_parts()
        parts["people_before"]["rings"][1]["homes"] = 12000
        self.assertLess(F.home_readings(parts, 3)[0]["rate_pct"], 0)

    def test_the_census_years_come_from_the_counts(self):
        parts = make_parts()
        parts["people"]["year"], parts["people_before"]["year"] = 2022, 2012
        parts["people_before"]["rings"][1]["homes"] = 8000
        measured = F.home_readings(parts, 3)[0]
        self.assertEqual((measured["from"]["year"], measured["to"]["year"]), (2012, 2022))
        self.assertAlmostEqual(measured["rate_pct"], 2.26)


class JobReadings(unittest.TestCase):
    def test_each_regional_plan_gives_new_jobs_a_year(self):
        got = F.job_readings(make_parts(), 3)
        self.assertEqual([r["id"] for r in got], ["adopted", "draft"])
        self.assertEqual([r["jobs_per_year"] for r in got], [150, 50])
        self.assertEqual(got[0]["from"], {"year": 2019, "jobs": 1000})
        self.assertEqual(got[0]["to"], {"year": 2021, "jobs": 1300})
        self.assertEqual(got[1]["source"], "Draft plan")
        self.assertIn("2024 to 2026", got[1]["label"])

    def test_no_regional_plan_means_no_jobs_readings(self):
        self.assertEqual(F.job_readings({}, 3), [])
        self.assertEqual(F.job_readings({"regional_plan": None}, 3), [])
        parts = make_parts()
        parts["regional_plan"].update(adopted=None, draft=None)
        self.assertEqual(F.job_readings(parts, 3), [])

    def test_a_ring_with_no_job_figures_gives_no_reading(self):
        parts = make_parts()
        parts["regional_plan"]["adopted"]["rings"][1]["jobs"] = {}
        self.assertEqual([r["id"] for r in F.job_readings(parts, 3)], ["draft"])

    def test_a_missing_year_of_jobs_gives_no_reading(self):
        parts = make_parts()
        parts["regional_plan"]["draft"]["rings"][1]["jobs"]["2024"] = None
        self.assertEqual([r["id"] for r in F.job_readings(parts, 3)], ["adopted"])

    def test_fewer_jobs_is_a_negative_pace(self):
        parts = make_parts()
        parts["regional_plan"]["adopted"]["rings"][1]["jobs"].update({"2019": 1300, "2021": 1000})
        self.assertEqual(F.job_readings(parts, 3)[0]["jobs_per_year"], -150)

    def test_zero_jobs_at_the_start_is_still_a_reading(self):
        parts = make_parts()
        parts["regional_plan"]["adopted"]["rings"][1]["jobs"].update({"2019": 0, "2021": 200})
        self.assertEqual(F.job_readings(parts, 3)[0]["jobs_per_year"], 100)

    def test_a_ring_the_plan_does_not_have_gives_nothing(self):
        self.assertEqual(F.job_readings(make_parts(), 2), [])


# ---------------------------------------------------------------- the city's project lists

class Pipeline(unittest.TestCase):
    A = {"built_review_pct": 60}

    def run_with(self, *rows, pct=60, **kw):
        return F.pipeline({"projects": projects(*rows, **kw)}, {"built_review_pct": pct}, YEARS)

    def test_a_project_under_construction_opens_in_years_one_and_two(self):
        out = self.run_with(project("Residential", "Under Construction", homes=100))
        self.assertEqual({y: v for y, v in out["per_year"]["homes"].items() if v}, {2027: 50.0, 2028: 50.0})
        stage = out["stages"][0]
        self.assertEqual((stage["label"], stage["from_year"], stage["to_year"], stage["uncertain"], stage["projects"], stage["homes"]),
                         ("Under construction", 2027, 2028, False, 1, 100))

    def test_every_status_lands_in_its_years(self):
        for status, first, last, label in (("Under Construction", 2027, 2028, "Under construction"),
                                           ("App Pln Ap - Final Engineering", 2028, 2030, "Approved, in final engineering"),
                                           ("App - Approved Planning", 2029, 2032, "Approved by planning")):
            with self.subTest(status=status):
                out = self.run_with(project("Residential", status, homes=120))
                years = [y for y, v in out["per_year"]["homes"].items() if v]
                self.assertEqual((years[0], years[-1]), (first, last))
                self.assertEqual(len(years), last - first + 1)
                self.assertAlmostEqual(sum(out["per_year"]["homes"].values()), 120)
                self.assertEqual(out["stages"][0]["label"], label)

    def test_a_project_under_review_is_scaled_by_the_share_that_ends_up_built(self):
        out = self.run_with(project("Residential", "Planning Application - Under Review", homes=500), pct=60)
        years = [y for y, v in out["per_year"]["homes"].items() if v]
        self.assertEqual((years[0], years[-1]), (2030, 2034))
        self.assertAlmostEqual(sum(out["per_year"]["homes"].values()), 300)
        for y in years:
            self.assertAlmostEqual(out["per_year"]["homes"][y], 60)
        stage = out["stages"][0]
        self.assertEqual((stage["label"], stage["uncertain"], stage["homes"]), ("Application under review", True, 300))

    def test_a_project_with_no_stage_is_uncertain_too_and_spread_over_the_longest_window(self):
        out = self.run_with(project("Residential", "", homes=600), pct=50)
        years = [y for y, v in out["per_year"]["homes"].items() if v]
        self.assertEqual((years[0], years[-1]), (2030, 2035))
        self.assertAlmostEqual(sum(out["per_year"]["homes"].values()), 300)
        self.assertEqual(out["stages"][0]["label"], "Stage not given")

    def test_the_share_built_changes_only_the_uncertain_projects(self):
        rows = (project("Residential", "Under Construction", homes=100),
                project("Residential", "Planning Application - Under Review", homes=100))
        for pct, expected in ((0, 100), (50, 150), (100, 200)):
            with self.subTest(pct=pct):
                out = self.run_with(*rows, pct=pct)
                self.assertAlmostEqual(sum(out["per_year"]["homes"].values()), expected)

    def test_a_project_beyond_three_miles_is_ignored_but_a_project_at_three_miles_counts(self):
        out = self.run_with(project("Residential", "Under Construction", homes=100, miles=3.01),
                            project("Residential", "Under Construction", homes=40, miles=3.0))
        self.assertEqual(out["projects_listed"], 2)
        self.assertEqual(out["projects_counted"], 1)
        self.assertAlmostEqual(sum(out["per_year"]["homes"].values()), 40)

    def test_a_project_far_away_that_states_no_size_is_not_counted_as_one_without_a_size(self):
        out = self.run_with(project("Residential", "Under Construction", miles=9.0))
        self.assertEqual((out["projects_without_sizes"], out["projects_counted"], out["projects_listed"]), (0, 0, 1))

    def test_a_project_without_a_stated_size_is_counted_apart(self):
        out = self.run_with(project("Residential", "Under Construction"), project("Commercial", "App - Approved Planning"),
                            project("Residential", "Under Construction", homes=10))
        self.assertEqual((out["projects_without_sizes"], out["projects_counted"], out["projects_listed"]), (2, 1, 3))
        self.assertEqual(sum(s["projects"] for s in out["stages"]), 1)

    def test_a_project_whose_stated_size_is_zero_or_empty_has_no_size(self):
        out = self.run_with(project("Residential", "Under Construction", homes=0), project("Industrial", "Under Construction", feet=0),
                            {"title": "x", "kind": None, "status": None, "stated": None})
        self.assertEqual((out["projects_without_sizes"], out["projects_counted"]), (3, 0))

    def test_the_kind_of_a_project_decides_which_need_it_meets(self):
        cases = (("Residential", dict(homes=50), "homes", 50), ("Mixed Use", dict(homes=50), "homes", 50),
                 ("Commercial", dict(feet=20000), "shops", 20000), ("Mixed Use", dict(feet=10000), "shops", 10000),
                 ("Industrial", dict(feet=300000), "work", 300000), ("Office Park", dict(feet=40000), "work", 40000),
                 ("Business Park", dict(feet=70000), "work", 70000))
        for kind, size, key, amount in cases:
            with self.subTest(kind=kind, size=size):
                out = self.run_with(project(kind, "Under Construction", **size))
                self.assertAlmostEqual(sum(out["per_year"][key].values()), amount)
                for other in {"homes", "shops", "work"} - {key}:
                    self.assertEqual(sum(out["per_year"][other].values()), 0, other)

    def test_a_mixed_project_meets_both_the_home_need_and_the_shop_need(self):
        out = self.run_with(project("Mixed Use", "Under Construction", homes=80, feet=16000))
        self.assertAlmostEqual(sum(out["per_year"]["homes"].values()), 80)
        self.assertAlmostEqual(sum(out["per_year"]["shops"].values()), 16000)
        self.assertEqual(out["stages"][0]["projects"], 1)
        self.assertEqual((out["stages"][0]["homes"], out["stages"][0]["shops_sq_ft"], out["stages"][0]["work_sq_ft"]), (80, 16000, 0))

    def test_house_sizes_of_a_housing_tract_are_not_shop_space(self):
        out = self.run_with(project("Residential", "Under Construction", feet=250000))
        self.assertEqual(out["projects_without_sizes"], 1)
        self.assertEqual(sum(out["per_year"]["shops"].values()) + sum(out["per_year"]["work"].values()), 0)

    def test_everything_listed_is_spread_without_loss(self):
        rows = [project("Residential", s, homes=h) for s, h in (("Under Construction", 70), ("App Pln Ap - Final Engineering", 90),
                                                               ("App - Approved Planning", 130), ("", 55), ("Review", 33))]
        out = self.run_with(*rows, pct=40)
        expected = 70 + 90 + 130 + 0.4 * (55 + 33)
        self.assertAlmostEqual(sum(out["per_year"]["homes"].values()), expected)

    def test_the_stage_list_only_has_stages_with_projects_and_counts_them(self):
        out = self.run_with(project("Residential", "Under Construction", homes=10), project("Residential", "Under Construction", homes=20),
                            project("Commercial", "App - Approved Planning", feet=5000))
        self.assertEqual([(s["label"], s["projects"]) for s in out["stages"]],
                         [("Under construction", 2), ("Approved by planning", 1)])
        self.assertEqual(out["stages"][0]["homes"], 30)
        self.assertEqual(out["stages"][1]["shops_sq_ft"], 5000)

    def test_years_follow_this_year(self):
        years = list(range(2030, 2042))
        out = F.pipeline({"projects": projects(project("Residential", "Under Construction", homes=100))}, self.A, years)
        self.assertEqual([y for y, v in out["per_year"]["homes"].items() if v], [2032, 2033])
        self.assertEqual(out["stages"][0]["from_year"], 2032)

    def test_every_year_is_present_even_with_nothing_on_the_lists(self):
        out = self.run_with()
        for key in ("homes", "shops", "work"):
            self.assertEqual(list(out["per_year"][key]), YEARS)
            self.assertEqual(sum(out["per_year"][key].values()), 0)
        self.assertEqual((out["available"], out["projects_listed"], out["projects_counted"], out["stages"]), (True, 0, 0, []))

    def test_a_list_that_did_not_answer_is_not_available(self):
        for parts in ({}, {"projects": None}):
            out = F.pipeline(parts, self.A, YEARS)
            self.assertFalse(out["available"])
            self.assertEqual((out["projects_listed"], out["projects_counted"], out["projects_without_sizes"]), (0, 0, 0))

    def test_the_dates_the_lists_were_updated_are_passed_on(self):
        out = self.run_with(updated={"development projects": "2023-09-14"})
        self.assertEqual(out["lists_updated"], {"development projects": "2023-09-14"})
        self.assertEqual(F.pipeline({"projects": {"projects": []}}, self.A, YEARS)["lists_updated"], {})

    def test_a_project_with_no_distance_is_counted(self):
        out = self.run_with(project("Residential", "Under Construction", homes=10, miles=None))
        self.assertEqual(out["projects_counted"], 1)


# ---------------------------------------------------------------- income around the site

class IncomeNear(unittest.TestCase):
    def two_tracts(self):
        return {"tracts": survey(tract("North", 100000, 3000, 600, 1.0, "north", {"1": 0.5, "3": 1.0, "5": 1.0}, built_2020_on=100),
                                 tract("South", 60000, 2000, 1000, 2.0, "south", {"1": 0.0, "3": 0.5, "5": 1.0}, built_2020_on=50),
                                 county_income=80000)}

    def test_the_typical_income_is_each_tracts_income_weighted_by_its_households_inside_the_ring(self):
        got = F.income_near(self.two_tracts())
        self.assertTrue(got["available"])
        # 3,000 households x $100,000 and 1,000 (half of 2,000) x $60,000
        self.assertEqual(got["typical"], 90000.0)

    def test_the_typical_figure_is_rounded_to_a_hundred_dollars(self):
        got = F.income_near({"tracts": survey(tract(income=100049), tract("B", 100000, 1000, 100, 2.0))})
        self.assertEqual(got["typical"], round(got["typical"], -2))
        self.assertEqual(got["typical"], 100000.0)

    def test_renters_are_counted_for_the_households_inside_the_ring(self):
        got = F.income_near(self.two_tracts())
        self.assertEqual(got["renters_pct"], round(100 * (600 + 500) / 4000, 1))

    def test_homes_built_since_the_last_census_are_shared_out_the_same_way(self):
        self.assertEqual(F.income_near(self.two_tracts())["built_since_2020"], round(100 * 1.0 + 50 * 0.5))

    def test_each_tract_in_the_wide_ring_is_listed_nearest_first_with_how_it_compares(self):
        got = F.income_near(self.two_tracts())
        self.assertEqual([r["name"] for r in got["tracts"]], ["North", "South"])
        north, south = got["tracts"]
        self.assertEqual((north["against_county"], south["against_county"]), ("higher", "lower"))
        self.assertEqual((north["share_in_market"], south["share_in_market"]), (1.0, 0.5))
        self.assertEqual((got["lowest"], got["highest"]), (60000, 100000))

    def test_a_tract_within_fifteen_percent_of_the_county_is_about_the_same(self):
        got = F.income_near({"tracts": survey(tract("A", 90000), tract("B", 70000, miles=2.0), tract("C", 115000, miles=3.0),
                                              county_income=100000)})
        self.assertEqual([r["against_county"] for r in got["tracts"]], ["about the same", "lower", "higher"])

    def test_without_a_county_figure_nothing_is_compared(self):
        got = F.income_near({"tracts": survey(county_income=None)})
        self.assertIsNone(got["tracts"][0]["against_county"])
        self.assertTrue(got["available"])
        self.assertNotIn("above", got["summary"])
        self.assertNotIn("below", got["summary"])

    def test_the_halves_of_the_compass_say_where_incomes_run_higher(self):
        got = F.income_near(self.two_tracts())
        self.assertEqual([h["direction"] for h in got["by_direction"]], ["north", "south"])
        self.assertEqual(got["by_direction"][0]["income"], 100000)
        self.assertEqual(got["by_direction"][1]["income"], 60000)
        self.assertIn("higher to the north", got["summary"])
        self.assertIn("lower to the south", got["summary"])

    def test_a_diagonal_tract_counts_in_both_of_its_halves(self):
        got = F.income_near({"tracts": survey(tract("NE", 100000, 1000, 100, 1.0, "north-east"),
                                              tract("SW", 50000, 1000, 100, 2.0, "south-west"), county_income=75000)})
        halves = {h["direction"]: h["income"] for h in got["by_direction"]}
        self.assertEqual(halves, {"north": 100000, "east": 100000, "south": 50000, "west": 50000})

    def test_no_comparison_of_halves_when_incomes_are_alike(self):
        got = F.income_near({"tracts": survey(tract("N", 100000, 1000, 100, 1.0, "north"), tract("S", 101000, 1000, 100, 2.0, "south"))})
        self.assertNotIn("higher to the", got["summary"])

    def test_the_summary_says_how_the_typical_figure_compares_with_the_county(self):
        above = F.income_near({"tracts": survey(county_income=80000)})["summary"]
        below = F.income_near({"tracts": survey(county_income=125000)})["summary"]
        same = F.income_near({"tracts": survey(county_income=101000)})["summary"]
        self.assertIn("above", above)
        self.assertIn("below", below)
        self.assertIn("about the same", same)
        self.assertIn("$100,000", above)

    def test_a_tract_the_ring_does_not_reach_is_not_weighted(self):
        got = F.income_near({"tracts": survey(tract("In", 100000, 1000, 100), tract("Out", 10000, 5000, 100, 4.0, "east",
                                                                                      {"1": 0.0, "3": 0.0, "5": 1.0}))})
        self.assertEqual(got["typical"], 100000.0)
        self.assertEqual([r["name"] for r in got["tracts"]], ["In", "Out"])
        self.assertEqual(got["tracts"][1]["share_in_market"], 0.0)
        self.assertEqual(got["lowest"], 10000)

    def test_a_tract_outside_the_widest_ring_is_not_listed(self):
        got = F.income_near({"tracts": survey(tract("In"), tract("Far", 20000, 100, 10, 8.0, "east", {"1": 0.0, "3": 0.0, "5": 0.0}))})
        self.assertEqual([r["name"] for r in got["tracts"]], ["In"])

    def test_a_tract_with_no_income_is_left_out_of_the_typical_figure(self):
        got = F.income_near({"tracts": survey(tract("A", 100000, 1000, 100), tract("B", None, 9000, 100, 2.0, "south"))})
        self.assertEqual(got["typical"], 100000.0)
        self.assertEqual([r["name"] for r in got["tracts"]], ["A"])

    def test_a_tract_with_no_households_does_not_count(self):
        got = F.income_near({"tracts": survey(tract("A", 100000, 1000, 100), tract("B", 20000, 0, 0, 2.0, "south"))})
        self.assertEqual(got["typical"], 100000.0)

    def test_no_survey_means_not_available(self):
        for parts in ({}, {"tracts": None}, {"tracts": {}}, {"tracts": {"tracts": []}}):
            with self.subTest(parts=parts):
                self.assertEqual(F.income_near(parts), {"available": False})

    def test_nobody_with_an_income_inside_the_ring_means_not_available(self):
        self.assertEqual(F.income_near({"tracts": survey(tract(income=None))}), {"available": False})
        self.assertEqual(F.income_near({"tracts": survey(tract(households=0))}), {"available": False})
        self.assertEqual(F.income_near({"tracts": survey(tract(share={"1": 0.0, "3": 0.0, "5": 1.0}))}), {"available": False})

    def test_whole_number_keys_and_text_keys_for_the_shares_read_alike(self):
        as_text = {"tracts": survey(tract("A", 100000, 1000, 100, share={"1": 1.0, "3": 0.5, "5": 1.0}), tract("B", 50000, 1000, 100, 2.0))}
        as_numbers = copy.deepcopy(as_text)
        for t in as_numbers["tracts"]["tracts"]:
            t["share_within"] = {int(k): v for k, v in t["share_within"].items()}
        after_json = json.loads(json.dumps(as_numbers))          # numbers become text again
        self.assertEqual(F.income_near(as_text), F.income_near(as_numbers))
        self.assertEqual(F.income_near(as_text), F.income_near(after_json))
        self.assertEqual(F.income_near(as_text)["typical"], 66700.0)       # 500 x 100,000 and 1,000 x 50,000

    def test_the_distance_can_be_changed(self):
        parts = {"tracts": survey(tract("A", 100000, 1000, 100, share={"1": 1.0, "3": 1.0, "5": 1.0}),
                                  tract("B", 50000, 1000, 100, 2.0, "south", {"1": 0.0, "3": 1.0, "5": 1.0}))}
        self.assertEqual(F.income_near(parts, 1)["typical"], 100000.0)
        self.assertEqual(F.income_near(parts, 3)["typical"], 75000.0)

    def test_the_survey_years_county_name_and_source_are_passed_on(self):
        got = F.income_near({"tracts": survey()})
        self.assertEqual((got["survey"], got["county"], got["county_name"], got["source"]), ("2018-2022", 100000, "Test County", "Test survey"))
        self.assertEqual(got["homes_survey"], "2018-2022")


# ---------------------------------------------------------------- the site's own plan

class ProgrammeOf(unittest.TestCase):
    def test_uses_are_added_up_across_plans(self):
        a = {"uses": [use("homes", "Houses", 10.04, homes=50), use("retail", "Shops", 2.0, sq_ft=20000)],
             "traffic": {"by_use": {"homes": 500, "retail": 900}}}
        b = {"uses": [use("homes", "Houses", 5.06, homes=25), use("park", "Parks", 1.0)], "traffic": {"by_use": {"homes": 250}}}
        got = F.programme_of([a, b])
        self.assertEqual(list(got), ["homes", "retail", "park"])
        self.assertEqual((got["homes"]["acres"], got["homes"]["amount"], got["homes"]["trips"]), (15.1, 75, 750))
        self.assertEqual((got["retail"]["acres"], got["retail"]["amount"], got["retail"]["trips"]), (2.0, 20000, 900))
        self.assertEqual((got["park"]["acres"], got["park"]["amount"], got["park"]["trips"]), (1.0, 0, 0))

    def test_a_use_carries_its_words_and_colour(self):
        got = F.programme_of([{"uses": [use("homes", "Houses", 1.0, homes=3)]}])["homes"]
        self.assertEqual((got["id"], got["label"], got["short"], got["colour"]), ("homes", "Houses", "Houses", "#000"))

    def test_nothing_in_gives_nothing_out(self):
        for plans in (None, [], [{}], [{"uses": None}], [{"uses": []}]):
            with self.subTest(plans=plans):
                self.assertEqual(F.programme_of(plans), {})

    def test_a_plan_with_no_traffic_adds_no_trips(self):
        got = F.programme_of([{"uses": [use("homes", "Houses", 1.0, homes=3)], "traffic": None}])
        self.assertEqual(got["homes"]["trips"], 0)

    def test_a_use_with_no_acres_adds_none(self):
        row = use("homes", "Houses", None, homes=3)
        self.assertEqual(F.programme_of([{"uses": [row]}])["homes"]["acres"], 0.0)


# ---------------------------------------------------------------- how fast the site's land is taken up

def pool(amount, kind="homes", years=FUTURE):
    return {kind: {"expected": {y: amount for y in years}}}


def a_use(use_id, amount, acres=10.0, trips=0, label=None):
    return {"id": use_id, "label": label or use_id.title(), "short": use_id, "colour": "#000", "acres": acres, "amount": amount, "trips": trips}


def take(uses, pools, ready=2, capture=20, known=None, years=YEARS, pipeline=None):
    A = {"ready_years": ready, "capture_pct": capture}
    known = {"homes": True, "shops": True, "work": True} if known is None else known
    return F.take_up({u["id"]: u for u in uses}, pools, A, years, known, pipeline)


class TakeUp(unittest.TestCase):
    def test_the_land_is_taken_up_only_after_it_is_ready(self):
        got = take([a_use("homes", 1000)], pool(100.0))[0]
        rows = got["by_year"]
        self.assertEqual([r["year"] for r in rows], FUTURE)
        self.assertEqual([r["taken"] for r in rows], [0, 0] + [20] * 8)
        self.assertEqual([r["so_far"] for r in rows], [0, 0, 20, 40, 60, 80, 100, 120, 140, 160])

    def test_the_summary_figures_follow_from_the_rows(self):
        got = take([a_use("homes", 1000, acres=10.0)], pool(100.0))[0]
        self.assertEqual((got["by_year_5"], got["by_year_10"]), (60, 160))
        self.assertEqual((got["acres_by_year_5"], got["acres_by_year_10"]), (0.6, 1.6))
        self.assertEqual(got["pct_by_year_10"], 16)
        self.assertEqual((got["kind"], got["unit"]), ("homes", "homes"))

    def test_land_not_filled_in_ten_years_is_given_a_later_year(self):
        got = take([a_use("homes", 1000)], pool(100.0))[0]
        # 840 homes are left and the last year took 20 a year: 42 more years after 2036
        self.assertEqual((got["filled_in"], got["filled_later_in"], got["never_at_this_pace"]), (None, 2078, False))

    def test_a_use_never_takes_more_than_it_has(self):
        got = take([a_use("homes", 50)], pool(100.0))[0]
        self.assertEqual([r["taken"] for r in got["by_year"]], [0, 0, 20, 20, 10, 0, 0, 0, 0, 0])
        self.assertEqual(max(r["so_far"] for r in got["by_year"]), 50)
        self.assertEqual((got["filled_in"], got["filled_later_in"], got["pct_by_year_10"], got["never_at_this_pace"]), (2031, None, 100, False))
        self.assertEqual(got["acres_by_year_10"], 10.0)

    def test_even_a_huge_need_never_goes_past_the_amount(self):
        got = take([a_use("homes", 70)], pool(1e9), capture=100)[0]
        self.assertEqual([r["so_far"] for r in got["by_year"]][2:], [70] * 8)
        self.assertEqual(got["filled_in"], 2029)

    def test_the_share_of_the_need_won_scales_what_is_taken(self):
        for capture, per_year in ((10, 10), (20, 20), (40, 40), (100, 100)):
            with self.subTest(capture=capture):
                got = take([a_use("homes", 5000)], pool(100.0), capture=capture)[0]
                self.assertEqual({r["taken"] for r in got["by_year"][2:]}, {per_year})

    def test_the_share_is_taken_from_the_need_left_after_the_projects_already_on_the_lists(self):
        # a need of 100 a year, 20% won; projects supply 100 in 2029 (nothing left), 60 in 2030 (40 left), none after
        coming = {"homes": {2029: 100.0, 2030: 60.0}}
        got = take([a_use("homes", 1000)], pool(100.0), pipeline=coming)[0]
        self.assertEqual([r["taken"] for r in got["by_year"]], [0, 0, 0, 8] + [20] * 6)
        self.assertEqual(got["by_year_10"], 8 + 6 * 20)

    def test_projects_that_supply_more_than_is_needed_leave_nothing_and_never_a_debt(self):
        coming = {"homes": {2029: 250.0, 2030: 1e9}}
        got = take([a_use("homes", 1000)], pool(100.0), pipeline=coming)[0]
        self.assertEqual([r["taken"] for r in got["by_year"]], [0, 0, 0, 0] + [20] * 6, "later years are not charged for the surplus")

    def test_projects_of_one_kind_do_not_use_up_the_need_of_another(self):
        coming = {"shops": {y: 1e9 for y in FUTURE}}
        got = take([a_use("homes", 1000)], pool(100.0), pipeline=coming)[0]
        self.assertEqual([r["taken"] for r in got["by_year"]], [0, 0] + [20] * 8)

    def test_land_ready_at_once_is_taken_from_the_first_year(self):
        got = take([a_use("homes", 1000)], pool(100.0), ready=0)[0]
        self.assertEqual([r["taken"] for r in got["by_year"]], [20] * 10)
        self.assertEqual(got["by_year_10"], 200)

    def test_land_that_takes_eight_years_to_ready_is_taken_only_in_the_last_two(self):
        got = take([a_use("homes", 1000)], pool(100.0), ready=8)[0]
        self.assertEqual([r["taken"] for r in got["by_year"]], [0] * 8 + [20, 20])
        self.assertEqual(got["by_year_5"], 0)

    def test_a_later_start_never_takes_more_by_year_ten(self):
        previous = None
        for ready in range(0, 9):
            got = take([a_use("homes", 1000)], pool(100.0), ready=ready)[0]["by_year_10"]
            if previous is not None:
                self.assertLessEqual(got, previous)
            previous = got

    def test_a_fraction_of_a_year_is_rounded(self):
        a = take([a_use("homes", 1000)], pool(100.0), ready=2.4)[0]["by_year"]
        b = take([a_use("homes", 1000)], pool(100.0), ready=2)[0]["by_year"]
        self.assertEqual(a, b)

    def test_uses_of_one_kind_share_the_need_by_their_size(self):
        got = take([a_use("homes", 100), a_use("apartments", 300)], pool(100.0))
        self.assertEqual([u["id"] for u in got], ["apartments", "homes"])
        apartments, houses = got
        self.assertEqual([r["taken"] for r in apartments["by_year"]][2:], [15] * 8)
        self.assertEqual([r["taken"] for r in houses["by_year"]][2:], [5] * 8)
        for i in range(10):
            self.assertLessEqual(apartments["by_year"][i]["taken"] + houses["by_year"][i]["taken"], 20)

    def test_a_use_that_is_filled_does_not_hand_its_share_to_the_others(self):
        got = take([a_use("homes", 10), a_use("apartments", 90)], pool(100.0), capture=100)
        apartments, houses = got
        self.assertEqual(houses["filled_in"], 2029)
        self.assertEqual([r["taken"] for r in apartments["by_year"]][2:5], [90, 0, 0])

    def test_each_kind_has_its_own_need(self):
        pools = {"homes": {"expected": {y: 100.0 for y in FUTURE}}, "shops": {"expected": {y: 1000.0 for y in FUTURE}},
                 "work": {"expected": {y: 500.0 for y in FUTURE}}}
        got = {u["id"]: u for u in take([a_use("homes", 9999), a_use("retail", 99999), a_use("business", 99999)], pools)}
        self.assertEqual(got["homes"]["by_year"][2]["taken"], 20)
        self.assertEqual(got["retail"]["by_year"][2]["taken"], 200)
        self.assertEqual(got["business"]["by_year"][2]["taken"], 100)
        self.assertEqual((got["homes"]["unit"], got["retail"]["unit"], got["business"]["unit"]), ("homes", "sq ft", "sq ft"))
        self.assertEqual((got["retail"]["kind"], got["business"]["kind"]), ("shops", "work"))

    def test_offices_and_business_parks_share_the_need_for_work_space(self):
        got = take([a_use("office", 100000), a_use("business", 200000)], pool(900.0, "work"))
        office, business = got
        self.assertEqual([office["id"], business["id"]], ["office", "business"])
        self.assertEqual((office["by_year"][2]["taken"], business["by_year"][2]["taken"]), (60, 120))

    def test_the_order_of_uses_is_always_the_same(self):
        pools = {k: {"expected": {y: 100.0 for y in FUTURE}} for k in ("homes", "shops", "work")}
        names = ("business", "homes", "office", "retail", "apartments")
        got = take([a_use(n, 100) for n in names], pools)
        self.assertEqual([u["id"] for u in got], ["apartments", "homes", "retail", "office", "business"])

    def test_a_kind_whose_need_could_not_be_worked_out_is_left_out(self):
        pools = {k: {"expected": {y: 100.0 for y in FUTURE}} for k in ("homes", "shops", "work")}
        known = {"homes": True, "shops": False, "work": False}
        got = take([a_use("homes", 100), a_use("retail", 100), a_use("business", 100)], pools, known=known)
        self.assertEqual([u["id"] for u in got], ["homes"])
        self.assertEqual(take([a_use("homes", 100)], pools, known={}), [])

    def test_a_use_of_nothing_and_a_use_with_no_program_are_left_out(self):
        pools = {k: {"expected": {y: 100.0 for y in FUTURE}} for k in ("homes", "shops", "work")}
        got = take([a_use("homes", 0), a_use("park", 5), a_use("retail", 100), a_use("mystery", 100)], pools)
        self.assertEqual([u["id"] for u in got], ["retail"])
        self.assertEqual(take([], pools), [])

    def test_with_no_need_nothing_is_ever_taken_and_the_answer_says_so(self):
        got = take([a_use("homes", 1000)], pool(0.0))[0]
        self.assertEqual(got["by_year_10"], 0)
        self.assertEqual((got["filled_in"], got["filled_later_in"], got["never_at_this_pace"], got["pct_by_year_10"]), (None, None, True, 0))

    def test_a_need_so_small_it_would_take_a_lifetime_is_never_at_this_pace(self):
        got = take([a_use("homes", 1000)], pool(1.0))[0]
        self.assertEqual((got["filled_in"], got["filled_later_in"], got["never_at_this_pace"]), (None, None, True))

    def test_a_year_with_less_need_than_nothing_takes_nothing(self):
        pools = pool(100.0)
        for y in FUTURE[:5]:
            pools["homes"]["expected"][y] = -50.0
        got = take([a_use("homes", 1000)], pools, ready=0)[0]
        self.assertEqual([r["taken"] for r in got["by_year"]][:5], [0] * 5)
        self.assertEqual([r["taken"] for r in got["by_year"]][5:], [20] * 5)

    def test_acres_taken_follow_the_share_of_the_amount(self):
        got = take([a_use("homes", 400, acres=25.0)], pool(100.0), capture=50)[0]
        for r in got["by_year"]:
            self.assertAlmostEqual(r["acres_so_far"], 25.0 * r["so_far"] / 400, delta=0.06)
        self.assertEqual(got["acres_by_year_10"], round(25.0 * got["by_year_10"] / 400, 1))

    def test_the_rows_keep_the_use_it_came_from(self):
        got = take([a_use("homes", 1000, acres=12.5, trips=777, label="Houses")], pool(100.0))[0]
        self.assertEqual((got["id"], got["label"], got["acres"], got["amount"], got["trips"]), ("homes", "Houses", 12.5, 1000, 777))


class PeriodsOf(unittest.TestCase):
    def periods(self, uses, pools, ready=2, capture=20):
        taken = take(uses, pools, ready, capture)
        return F.periods_of(taken, {u["id"]: u for u in uses}, {"ready_years": ready, "capture_pct": capture}, YEARS)

    def test_the_ten_years_come_in_three_steps(self):
        steps, _ = self.periods([a_use("homes", 1000)], pool(100.0))
        self.assertEqual([(s["from_year"], s["to_year"], s["label"], s["title"]) for s in steps],
                         [(2027, 2028, "2027 to 2028", "Years 1 and 2"), (2029, 2031, "2029 to 2031", "Years 3 to 5"),
                          (2032, 2036, "2032 to 2036", "Years 6 to 10")])

    def test_the_first_step_is_approvals_while_the_land_is_not_ready(self):
        steps, _ = self.periods([a_use("homes", 1000)], pool(100.0), ready=2)
        self.assertEqual(len(steps[0]["lines"]), 1)
        self.assertIn("No land is handed over yet", steps[0]["lines"][0])

    def test_a_step_that_straddles_the_ready_year_says_when_the_first_land_follows(self):
        steps, _ = self.periods([a_use("homes", 1000)], pool(100.0), ready=3)
        self.assertIn("No land is handed over yet", steps[0]["lines"][0])
        self.assertIn("about 2029", steps[1]["lines"][0])
        self.assertIn("first land follows", steps[1]["lines"][0])

    def test_land_ready_at_once_has_no_approvals_line(self):
        steps, _ = self.periods([a_use("homes", 1000)], pool(100.0), ready=0)
        for step in steps:
            self.assertFalse(any("Approvals" in line for line in step["lines"]), step["lines"])

    def test_each_step_says_how_much_each_use_hands_over(self):
        steps, _ = self.periods([a_use("homes", 1000, acres=10.0, label="Houses")], pool(100.0))
        # 2029 to 2031: 60 homes of 1,000 = 0.6 acres; 2032 to 2036: 100 more = 1 acre
        self.assertEqual(steps[1]["lines"], ["Houses: about 0.6 acres (60 homes)."])
        self.assertEqual(steps[2]["lines"], ["Houses: about 1 acre (100 homes)."])

    def test_floor_space_is_rounded_to_a_hundred_square_feet(self):
        steps, _ = self.periods([a_use("retail", 100000, acres=10.0, label="Shops")], pool(1234.0, "shops"))
        line = steps[1]["lines"][0]
        self.assertTrue(line.startswith("Shops: about "), line)
        self.assertIn("sq ft", line)
        self.assertNotIn("homes", line)

    def test_a_step_with_nothing_taken_says_so(self):
        steps, _ = self.periods([a_use("homes", 1000)], pool(0.0))
        self.assertEqual(steps[1]["lines"], ["Nothing more is taken up in these years at this pace."])
        self.assertEqual(steps[2]["lines"], ["Nothing more is taken up in these years at this pace."])

    def test_land_not_filled_is_listed_with_what_is_left_and_when_it_would_fill(self):
        _, after = self.periods([a_use("homes", 1000, acres=10.0, label="Houses")], pool(100.0))
        self.assertEqual(after, ["Houses: 8.4 of 10 acres still unsold in 2036, filled around 2078."])

    def test_land_that_never_fills_says_so(self):
        _, after = self.periods([a_use("homes", 1000, acres=10.0, label="Houses")], pool(0.0))
        self.assertEqual(len(after), 1)
        self.assertIn("not filled at this pace within a lifetime", after[0])

    def test_land_that_is_filled_is_not_listed_as_left(self):
        _, after = self.periods([a_use("homes", 50, acres=10.0, label="Houses")], pool(100.0))
        self.assertEqual(after, [])

    def test_parks_are_built_along_with_the_uses_around_them(self):
        uses = [a_use("homes", 50, label="Houses"), a_use("park", 0, acres=4.0, label="Parks")]
        taken = take(uses, pool(100.0))
        _, after = F.periods_of(taken, {u["id"]: u for u in uses}, {"ready_years": 2}, YEARS)
        self.assertEqual(len(after), 1)
        self.assertIn("4 acres", after[0])

    def test_no_park_line_without_park_acres(self):
        uses = [a_use("homes", 50), a_use("park", 0, acres=0.0)]
        _, after = F.periods_of(take(uses, pool(100.0)), {u["id"]: u for u in uses}, {"ready_years": 2}, YEARS)
        self.assertEqual(after, [])


# ---------------------------------------------------------------- the whole forecast

class Years(unittest.TestCase):
    def test_the_years_are_last_year_this_year_and_ten_more(self):
        out = forecast()
        self.assertEqual(out["years"], YEARS)
        self.assertEqual((out["year"], out["background_year"]), (2026, 2025))
        self.assertEqual(len(out["years"]), 12)

    def test_the_growth_table_covers_every_year_and_the_need_tables_only_the_ten_to_come(self):
        out = forecast()
        three = next(r for r in out["rings"] if r["miles"] == 3)
        self.assertEqual([r["year"] for r in three["rows"]], YEARS)
        self.assertEqual([r["year"] for r in out["homes"]["rows"]], YEARS[1:])
        self.assertEqual([r["year"] for r in out["shops"]["rows"]], FUTURE)
        self.assertEqual([r["year"] for r in out["jobs"]["rows"]], FUTURE)
        self.assertEqual([r["year"] for r in out["traffic"]["rows"]], YEARS[1:])
        for u in out["programme"]["uses"]:
            self.assertEqual([r["year"] for r in u["by_year"]], FUTURE)

    def test_this_years_row_is_not_part_of_the_ten_years_of_need(self):
        rows = forecast()["homes"]["rows"]
        self.assertEqual(rows[0]["year"], 2026)
        self.assertNotIn("need_so_far", rows[0])
        self.assertTrue(all("need_so_far" in r for r in rows[1:]))
        self.assertEqual(len(rows[1:]), 10)

    def test_another_year_moves_every_table(self):
        out = forecast(year=2031)
        self.assertEqual(out["years"], list(range(2030, 2042)))
        self.assertEqual(out["background_year"], 2030)
        self.assertEqual([r["year"] for r in out["shops"]["rows"]], list(range(2032, 2042)))
        self.assertEqual(out["stages"][0]["from_year"], 2032)
        self.assertEqual(out["headline"][0]["label"], "People within 3 miles, 2031")
        self.assertEqual(out["headline"][1]["label"], "By 2036")
        self.assertEqual(out["headline"][2]["label"], "By 2041")

    def test_a_later_year_has_more_homes_than_an_earlier_one_at_the_same_rate(self):
        a = forecast(year=2026)["headline"][0]["value"]
        b = forecast(year=2031)["headline"][0]["value"]
        self.assertGreater(b, a)

    def test_a_year_before_the_census_does_not_break_anything(self):
        out = forecast(year=2018)
        self.assertEqual(out["years"][0], 2017)
        json.dumps(out, allow_nan=False)

    def test_the_year_of_the_census_itself_works(self):
        out = forecast(year=2020)
        three = next(r for r in out["rings"] if r["miles"] == 3)
        this_year = next(r for r in three["rows"] if r["year"] == 2020)
        self.assertEqual(this_year["homes"], {"low": 10000, "expected": 10000, "high": 10000})


class Arithmetic(unittest.TestCase):
    """The round facts make every number checkable by hand."""

    def setUp(self):
        self.out = forecast()
        self.three = next(r for r in self.out["rings"] if r["miles"] == 3)

    def test_the_three_lines_are_the_lowest_middle_and_highest_reading(self):
        self.assertEqual(self.three["rates_pct"], {"low": 0.0, "expected": 10.0, "high": 21.0})
        self.assertEqual([r["id"] for r in self.three["readings"]], ["measured", "adopted", "draft"])
        self.assertFalse(self.three["one_reading"])
        self.assertTrue(self.three["available"])

    def test_homes_grow_from_the_census_count_at_each_rate(self):
        rows = {r["year"]: r for r in self.three["rows"]}
        for year in (2025, 2026, 2030, 2036):
            with self.subTest(year=year):
                for scenario, rate in (("low", 0.0), ("expected", 0.10), ("high", 0.21)):
                    self.assertAlmostEqual(rows[year]["homes"][scenario], 10000 * (1 + rate) ** (year - 2020), delta=1)

    def test_people_are_the_homes_times_the_people_in_each_home_rounded_to_ten(self):
        self.assertEqual(self.three["people_per_home"], 3.0)
        for r in self.three["rows"]:
            for s in F.SCENARIOS:
                self.assertAlmostEqual(r["people"][s], 3 * r["homes"][s], delta=15)
                self.assertEqual(r["people"][s] % 10, 0)

    def test_the_counted_numbers_are_kept_by_year(self):
        self.assertEqual(self.three["counted"], {"2010": {"people": 30000, "homes": 10000}, "2020": {"people": 30000, "homes": 10000}})

    def test_new_homes_each_year_are_the_growth_of_that_year(self):
        row = next(r for r in self.out["homes"]["rows"] if r["year"] == 2027)
        for scenario, rate in (("low", 0.0), ("expected", 0.10), ("high", 0.21)):
            self.assertAlmostEqual(row["need"][scenario], 10000 * ((1 + rate) ** 7 - (1 + rate) ** 6), delta=1)

    def test_the_need_so_far_adds_up_the_years_and_ends_at_the_ten_year_figure(self):
        rows = self.out["homes"]["rows"][1:]
        for s in F.SCENARIOS:
            self.assertAlmostEqual(rows[-1]["need_so_far"][s], sum(r["need"][s] for r in rows), delta=6)
            self.assertEqual(rows[-1]["need_so_far"][s], self.out["homes"]["need_10_years"][s])
        self.assertAlmostEqual(self.out["homes"]["need_10_years"]["expected"], 10000 * (1.1 ** 16 - 1.1 ** 6), delta=2)

    def test_homes_for_rent_and_for_sale_follow_the_renting_share(self):
        row = self.out["homes"]["rows"][1]
        self.assertAlmostEqual(row["rented"] / (row["rented"] + row["owned"]), 0.20, delta=0.01)
        self.assertNotIn("rented", self.out["homes"]["rows"][0])

    def test_shop_space_follows_income_spending_and_sales_per_square_foot(self):
        self.assertAlmostEqual(self.out["shops"]["sq_ft_per_home"], 100000 * 0.30 * 0.55 / 400, delta=0.06)
        row = self.out["shops"]["rows"][0]
        need = self.out["homes"]["rows"][1]["need"]["expected"]
        self.assertAlmostEqual(row["new_sq_ft"]["expected"], need * 41.25, delta=200)

    def test_what_the_area_supports_today_is_the_homes_this_year_times_the_shop_space_each(self):
        homes_today = 10000 * 1.1 ** 6
        self.assertAlmostEqual(self.out["shops"]["supported_today_sq_ft"]["expected"], homes_today * 41.25, delta=600)

    def test_work_space_is_the_new_jobs_times_the_space_each(self):
        self.assertEqual(self.out["jobs"]["new_jobs_per_year"], {"low": 50, "expected": 100, "high": 150})
        row = self.out["jobs"]["rows"][0]
        self.assertEqual(row["new_jobs"], {"low": 50, "expected": 100, "high": 150})
        self.assertEqual(row["space_sq_ft"], {"low": 20000, "expected": 40000, "high": 60000})
        self.assertEqual(self.out["jobs"]["rows"][-1]["space_so_far"]["expected"], 400000)
        self.assertEqual(self.out["jobs"]["space_10_years_sq_ft"], {"low": 200000, "expected": 400000, "high": 600000})

    def test_traffic_grows_with_the_homes_in_the_widest_ring(self):
        rows = {r["year"]: r for r in self.out["traffic"]["rows"]}
        self.assertEqual(self.out["traffic"]["highway"]["today"], 100000)
        self.assertEqual(rows[2026]["highway"], {"low": 100000.0, "expected": 100000.0, "high": 100000.0})
        self.assertAlmostEqual(rows[2031]["highway"]["expected"], 100000 * 1.07 ** 5, delta=100)
        self.assertAlmostEqual(rows[2036]["highway"]["high"], 100000 * (1 + 0.21 * 0.70) ** 10, delta=100)
        self.assertEqual(rows[2036]["highway"]["low"], 100000.0)

    def test_the_highway_count_is_the_busier_side(self):
        out = changed(lambda p: p["state_highway_traffic"]["stations"][0].update(vehicles_per_day_behind="80000", vehicles_per_day_ahead=120000))
        self.assertEqual(out["traffic"]["highway"]["today"], 120000)
        self.assertEqual(out["traffic"]["highway"]["where"], "Scott Road")

    def test_the_site_adds_trips_as_its_land_is_taken_up(self):
        rows = {r["year"]: r["site_trips"] for r in self.out["traffic"]["rows"]}
        self.assertEqual((rows[2025 + 1], rows[2027], rows[2028]), (0, 0, 0))
        self.assertGreater(rows[2036], rows[2029])
        taken = uses_by_id(self.out)
        full = sum(u["trips"] * u["by_year_10"] / u["amount"] for u in taken.values())
        self.assertAlmostEqual(rows[2036], full, delta=3)
        self.assertEqual(self.out["programme"]["trips_at_build_out"], 5000 + 600 + 2400 + 2000 + 800)

    def test_the_first_land_is_handed_over_after_the_ready_years(self):
        for u in self.out["programme"]["uses"]:
            by_year = {r["year"]: r["taken"] for r in u["by_year"]}
            self.assertEqual((by_year[2027], by_year[2028]), (0, 0), u["id"])
            self.assertGreater(by_year[2029], 0, u["id"])

    def test_houses_and_apartments_share_the_need_for_homes_by_size(self):
        taken = uses_by_id(self.out)
        year_one = {u: taken[u]["by_year"][2]["taken"] for u in ("apartments", "homes")}
        self.assertAlmostEqual(year_one["apartments"] / year_one["homes"], 400 / 200, delta=0.1)
        need = self.out["homes"]["rows"][3]["need"]["expected"]          # 2029
        self.assertAlmostEqual(year_one["apartments"] + year_one["homes"], min(need * 0.20, 600), delta=2)

    def test_land_that_fills_is_marked_and_the_rest_has_a_later_year(self):
        taken = uses_by_id(self.out)
        self.assertEqual((taken["homes"]["filled_in"], taken["apartments"]["filled_in"]), (2030, 2030))
        self.assertEqual(taken["retail"]["filled_in"], 2033)
        self.assertIsNone(taken["business"]["filled_in"])
        self.assertGreater(taken["business"]["filled_later_in"], 2036)
        self.assertLess(taken["business"]["pct_by_year_10"], 100)

    def test_the_headline_has_the_people_the_homes_and_the_income(self):
        head = {h["label"]: h for h in self.out["headline"]}
        self.assertEqual(head["People within 3 miles, 2026"]["value"], round(3 * 10000 * 1.1 ** 6, -1))
        self.assertEqual(head["By 2031"]["low"], 30000)
        self.assertIn("30,000 counted in 2020", head["People within 3 miles, 2026"]["note"])
        self.assertEqual(head["New homes needed a year"]["unit"], "homes")
        self.assertEqual(head["Typical household income"]["value"], 100000.0)
        self.assertIn("2018-2022", head["Typical household income"]["note"])
        self.assertIn("New shop space supported a year", head)

    def test_the_regional_city_figures_are_passed_on(self):
        self.assertEqual(self.out["city_forecast"]["name"], "Testville")
        self.assertIsNone(changed(lambda p: p["regional_plan"].update(city=None))["city_forecast"])
        self.assertIsNone(changed(lambda p: p.pop("regional_plan"))["city_forecast"])

    def test_the_site_is_passed_on_as_it_came(self):
        site = {"apns": ["x"], "acres": 1.5}
        self.assertIs(F.make_forecast(site, make_parts(), make_plans(), None, 2026)["site"], site)

    def test_the_sources_say_which_answered(self):
        out = changed(lambda p: (p.pop("tracts"), p.update(projects=None)))
        answered = {s["name"]: s["answered"] for s in out["sources"]}
        self.assertEqual(answered, {"2020 Census": True, "2010 Census": True, "Regional plan (SCAG)": True, "Census survey": False,
                                    "City project lists": False, "Caltrans": True})

    def test_the_stage_windows_follow_this_year(self):
        self.assertEqual([(s["from_year"], s["to_year"]) for s in self.out["stages"]],
                         [(2027, 2028), (2028, 2030), (2029, 2032), (2030, 2034), (2030, 2035)])
        self.assertEqual([s["uncertain"] for s in self.out["stages"]], [False, False, False, True, True])


class Invariants(unittest.TestCase):
    def assert_in_order(self, out, at_least=1):
        self.assertGreaterEqual(check_order(self, out), at_least)

    def test_low_is_never_above_expected_and_expected_never_above_high(self):
        self.assert_in_order(forecast(), 50)

    def test_the_order_holds_when_the_area_is_shrinking(self):
        out = changed(lambda p: p["people"]["rings"][1].update(homes=7000, people=21000))
        self.assert_in_order(out, 50)

    def test_the_order_holds_with_projects_and_a_changed_set_of_figures(self):
        parts = make_parts()
        parts["projects"] = projects(project("Residential", "Under Construction", homes=300), project("Commercial", "App - Approved Planning", feet=50000),
                                     project("Industrial", "Planning Application - Under Review", feet=90000))
        self.assert_in_order(forecast(parts, settings=mine(spend_pct=45, capture_pct=80, ready_years=0)), 50)

    def test_the_order_holds_with_a_single_reading_and_with_two(self):
        one = changed(lambda p: p.pop("regional_plan"))
        two = changed(lambda p: p["regional_plan"].update(adopted=None))
        self.assert_in_order(one, 10)
        self.assert_in_order(two, 10)

    def test_the_order_holds_in_a_different_year(self):
        self.assert_in_order(forecast(year=2031), 50)

    def test_the_answer_is_plain_data_that_can_be_sent_as_json(self):
        for out in (forecast(), forecast(year=2031), forecast(settings=mine(spend_pct=45)), forecast(parts={}), forecast(plans=[])):
            text = json.dumps(out, allow_nan=False)
            self.assertIsInstance(json.loads(text), dict)

    def test_asking_does_not_change_what_was_given(self):
        parts, plans, settings = make_parts(), make_plans(), mine(spend_pct=45)
        before = copy.deepcopy((parts, plans, settings))
        F.make_forecast({"apns": ["1"]}, parts, plans, settings, 2026)
        self.assertEqual((parts, plans, settings), before)

    def test_the_same_facts_give_the_same_answer(self):
        self.assertEqual(forecast(), forecast())

    def test_no_working_figure_is_left_in_the_answer(self):
        text = json.dumps(forecast())
        self.assertNotIn("_homes", text)


class OneReading(unittest.TestCase):
    def check(self, out):
        three = next(r for r in out["rings"] if r["miles"] == 3)
        self.assertTrue(out["available"])
        self.assertTrue(three["one_reading"])
        self.assertEqual(len(three["readings"]), 1)
        self.assertEqual(len(set(three["rates_pct"].values())), 1)
        for r in three["rows"]:
            self.assertEqual(len(set(r["homes"].values())), 1)
            self.assertEqual(len(set(r["people"].values())), 1)
        for r in out["homes"]["rows"]:
            self.assertEqual(len(set(r["need"].values())), 1)
        for r in out["traffic"]["rows"]:
            self.assertEqual(len(set(r["highway"].values())), 1)
        self.assertTrue(any("one reading" in line.lower() for line in out["advice"]), out["advice"])

    def test_only_the_counted_growth(self):
        self.check(changed(lambda p: (p["people_before"]["rings"][1].update(homes=8000), p.pop("regional_plan"))))

    def test_only_one_regional_forecast(self):
        self.check(changed(lambda p: (p.pop("people_before"), p["regional_plan"].update(draft=None))))

    def test_the_range_of_the_headline_collapses_too(self):
        out = changed(lambda p: (p["people_before"]["rings"][1].update(homes=8000), p.pop("regional_plan")))
        for h in out["headline"]:
            if "low" in h:
                self.assertEqual((h["low"], h["high"]), (h["value"], h["value"]), h["label"])

    def test_with_more_than_one_reading_the_page_is_not_told_there_is_only_one(self):
        out = forecast()
        self.assertFalse(any("only one reading" in line.lower() for line in out["advice"]))
        self.assertTrue(any("middle reading" in line for line in out["advice"]))


class NoReadings(unittest.TestCase):
    def setUp(self):
        self.parts = make_parts()
        del self.parts["people_before"], self.parts["regional_plan"]
        self.out = forecast(self.parts)

    def test_there_is_no_forecast_and_the_answer_says_so(self):
        self.assertFalse(self.out["available"])
        self.assertTrue(any("no reading of growth" in line.lower() for line in self.out["limits"]), self.out["limits"])
        self.assertTrue(any("no year-by-year forecast" in line for line in self.out["limits"]))

    def test_no_row_and_no_number_is_made_up(self):
        out = self.out
        self.assertEqual(out["headline"], [])
        for ring in out["rings"]:
            self.assertFalse(ring["available"])
            self.assertNotIn("rows", ring)
            self.assertNotIn("rates_pct", ring)
        self.assertEqual((out["homes"]["available"], out["homes"]["rows"]), (False, []))
        self.assertEqual((out["shops"]["available"], out["shops"]["rows"]), (False, []))
        self.assertEqual((out["traffic"]["available"], out["traffic"]["rows"]), (False, []))
        self.assertEqual((out["programme"]["available"], out["programme"]["uses"], out["programme"]["steps"]), (False, [], []))
        self.assertNotIn("need_10_years", out["homes"])
        self.assertNotIn("sq_ft_per_home", out["shops"])

    def test_the_jobs_still_come_from_the_regional_plan_when_it_is_the_only_thing_missing(self):
        parts = make_parts()
        del parts["people_before"]
        parts["regional_plan"]["adopted"] = parts["regional_plan"]["draft"] = None
        out = forecast(parts)
        self.assertFalse(out["available"])
        self.assertFalse(out["jobs"]["available"])

    def test_every_use_is_listed_as_not_forecast_with_a_reason(self):
        rows = {r["id"]: r for r in self.out["programme"]["not_forecast"]}
        self.assertEqual(set(rows), {"retail", "office", "apartments", "homes", "business"})
        self.assertTrue(all(r["why"] and r["acres"] for r in rows.values()))
        self.assertEqual(rows["homes"]["why"], "No reading of growth answered.")

    def test_the_site_is_still_described_and_the_figures_still_listed(self):
        self.assertEqual(self.out["programme"]["acres"], 100.0)
        self.assertEqual(len(self.out["figures"]), len(F.ASSUMPTIONS))
        self.assertTrue(self.out["income"]["available"])

    def test_without_the_current_count_there_is_no_forecast_even_when_the_regional_plan_answered(self):
        parts = make_parts()
        del parts["people"]
        out = forecast(parts)
        self.assertFalse(out["available"])
        self.assertTrue(any("no reading of growth" in line.lower() for line in out["limits"]))

    def test_nothing_at_all_still_gives_an_answer(self):
        out = F.make_forecast({}, {}, [], None, 2026)
        self.assertFalse(out["available"])
        self.assertEqual(out["programme"]["uses"], [])
        self.assertEqual(out["income"], {"available": False})
        self.assertEqual([s["answered"] for s in out["sources"]], [False] * 6)

    def test_no_plans_at_all_still_gives_the_forecast_of_the_area(self):
        for plans in ([], [{}], [{"uses": []}]):
            out = forecast(plans=plans)
            self.assertTrue(out["available"])
            self.assertFalse(out["programme"]["available"])
            self.assertEqual(out["programme"]["acres"], 0)
        out = F.make_forecast({}, make_parts(), None, None, 2026)
        self.assertTrue(out["available"])
        self.assertFalse(out["programme"]["available"])


class OnlyTheMarketRingMatters(unittest.TestCase):
    def test_the_three_mile_ring_decides_whether_there_is_a_forecast(self):
        out = changed(lambda p: p["people"]["rings"].pop(1))
        self.assertFalse(out["available"])
        three = next(r for r in out["rings"] if r["miles"] == 3)
        self.assertFalse(three["available"])
        self.assertTrue(next(r for r in out["rings"] if r["miles"] == 1)["available"])

    def test_without_the_five_mile_ring_only_the_traffic_is_lost(self):
        out = changed(lambda p: p["people"]["rings"].pop(2))
        self.assertTrue(out["available"])
        self.assertFalse(out["traffic"]["available"])
        self.assertEqual(out["traffic"]["rows"], [])
        self.assertTrue(out["homes"]["available"])


class MissingIncome(unittest.TestCase):
    def check(self, out):
        self.assertTrue(out["available"])
        self.assertTrue(out["homes"]["available"])
        self.assertFalse(out["shops"]["available"])
        self.assertEqual(out["shops"]["rows"], [])
        self.assertEqual(out["income"], {"available": False})
        self.assertNotIn("retail", uses_by_id(out), "shops must not be shown as never selling")
        rows = {r["id"]: r for r in out["programme"]["not_forecast"]}
        self.assertEqual(set(rows), {"retail"})
        self.assertEqual(rows["retail"]["acres"], 10.0)
        self.assertIn("income", rows["retail"]["why"].lower())
        labels = [h["label"] for h in out["headline"]]
        self.assertNotIn("New shop space supported a year", labels)
        self.assertNotIn("Typical household income", labels)

    def test_no_survey(self):
        self.check(changed(lambda p: p.pop("tracts")))

    def test_a_survey_that_did_not_answer(self):
        self.check(changed(lambda p: p.update(tracts=None)))

    def test_a_survey_with_no_tracts(self):
        self.check(changed(lambda p: p.update(tracts={"tracts": []})))

    def test_a_survey_with_nobody_in_the_ring(self):
        self.check(changed(lambda p: p.update(tracts=survey(tract(share={"1": 0.0, "3": 0.0, "5": 1.0})))))

    def test_the_other_uses_are_still_forecast(self):
        out = changed(lambda p: p.pop("tracts"))
        self.assertEqual(set(uses_by_id(out)), {"homes", "apartments", "office", "business"})

    def test_without_income_there_are_no_renter_split_of_new_homes(self):
        out = changed(lambda p: p.pop("tracts"))
        self.assertNotIn("rented", out["homes"]["rows"][1])


class MissingJobs(unittest.TestCase):
    def check(self, out, why_word="jobs"):
        self.assertTrue(out["available"])
        self.assertFalse(out["jobs"]["available"])
        self.assertEqual(out["jobs"]["rows"], [])
        self.assertEqual(out["jobs"]["readings"], [])
        self.assertNotIn("new_jobs_per_year", out["jobs"])
        self.assertTrue({"office", "business"}.isdisjoint(uses_by_id(out)))
        rows = {r["id"]: r for r in out["programme"]["not_forecast"]}
        self.assertEqual(set(rows), {"office", "business"})
        self.assertIn(why_word, rows["office"]["why"].lower())
        self.assertEqual(rows["business"]["acres"], 20.0)

    def test_no_regional_plan_at_all(self):
        out = changed(lambda p: p.pop("regional_plan"))
        self.check(out)
        self.assertTrue(out["rings"][1]["one_reading"])

    def test_both_plans_did_not_answer(self):
        self.check(changed(lambda p: p["regional_plan"].update(adopted=None, draft=None)))

    def test_plans_that_have_no_job_figures(self):
        def drop(p):
            for key in ("adopted", "draft"):
                for ring in p["regional_plan"][key]["rings"]:
                    ring["jobs"] = {}
        self.check(changed(drop))

    def test_the_homes_and_shops_are_still_forecast(self):
        out = changed(lambda p: p["regional_plan"].update(adopted=None, draft=None))
        self.assertTrue(out["shops"]["available"])
        self.assertEqual(set(uses_by_id(out)), {"homes", "apartments", "retail"})

    def test_one_plan_with_jobs_is_a_single_reading_with_no_range(self):
        out = changed(lambda p: p["regional_plan"].update(adopted=None))
        self.assertTrue(out["jobs"]["available"])
        self.assertEqual(out["jobs"]["new_jobs_per_year"], {"low": 50, "expected": 50, "high": 50})

    def test_fewer_jobs_never_make_negative_work_space(self):
        def shrink(p):
            for key in ("adopted", "draft"):
                for ring in p["regional_plan"][key]["rings"]:
                    ring["jobs"] = {y: 2000 - 100 * i for i, y in enumerate(ring["jobs"])}
        out = changed(shrink)
        self.assertTrue(out["jobs"]["available"])
        self.assertEqual(out["jobs"]["new_jobs_per_year"], {"low": 0, "expected": 0, "high": 0})
        self.assertEqual(out["jobs"]["rows"][0]["space_sq_ft"], {"low": 0, "expected": 0, "high": 0})
        self.assertEqual(uses_by_id(out)["business"]["by_year_10"], 0)


class Projects(unittest.TestCase):
    def test_projects_on_the_lists_are_set_beside_the_need(self):
        out = changed(lambda p: p.update(projects=projects(project("Residential", "Under Construction", homes=1000),
                                                          project("Commercial", "Under Construction", feet=50000),
                                                          project("Industrial", "Under Construction", feet=30000))))
        rows = {r["year"]: r for r in out["homes"]["rows"]}
        self.assertEqual((rows[2027]["pipeline"], rows[2028]["pipeline"], rows[2029]["pipeline"]), (500, 500, 0))
        self.assertEqual(rows[2028]["pipeline_so_far"], 1000)
        self.assertEqual(out["homes"]["pipeline_10_years"], 1000)
        self.assertEqual(out["shops"]["pipeline_10_years_sq_ft"], 50000)
        self.assertEqual(out["jobs"]["pipeline_10_years_sq_ft"], 30000)
        self.assertEqual(out["homes"]["pipeline"]["projects_counted"], 3)

    def test_how_many_years_of_need_the_projects_cover(self):
        out = changed(lambda p: p.update(projects=projects(project("Residential", "Under Construction", homes=1000))))
        need = out["homes"]["need_10_years"]["expected"]
        self.assertAlmostEqual(out["homes"]["pipeline_covers_years"], 1000 / (need / 10), delta=0.06)

    def test_projects_beyond_the_market_distance_and_without_sizes_do_not_count_and_the_limits_say_so(self):
        out = changed(lambda p: p.update(projects=projects(project("Residential", "Under Construction", homes=1000, miles=4.0),
                                                          project("Residential", "Under Construction"),
                                                          project("Residential", "Under Construction"))))
        self.assertEqual(out["homes"]["pipeline_10_years"], 0)
        self.assertEqual(out["homes"]["pipeline"]["projects_without_sizes"], 2)
        self.assertTrue(any(line.startswith("2 projects") for line in out["limits"]), out["limits"])

    def test_no_such_limit_line_when_every_project_states_a_size(self):
        out = changed(lambda p: p.update(projects=projects(project("Residential", "Under Construction", homes=10))))
        self.assertFalse(any("do not state" in line for line in out["limits"]))

    def test_a_list_not_updated_for_two_years_is_a_limit(self):
        out = changed(lambda p: p.update(projects=projects(updated={"development projects": "2023-09-14", "fresh list": "2026-01-02",
                                                                    "never": None})))
        old = [line for line in out["limits"] if "not been updated" in line]
        self.assertEqual(len(old), 1)
        self.assertIn("development projects (2023-09-14)", old[0])
        self.assertNotIn("fresh list", old[0])

    def test_a_list_is_old_when_its_year_is_two_or_more_before_this_year(self):
        for day, old in (("2025-01-01", False), ("2025-12-31", False), ("2024-12-31", True), ("2024-01-01", True)):
            with self.subTest(day=day):
                out = changed(lambda p: p.update(projects=projects(updated={"x": day})))
                self.assertEqual(any("not been updated" in line for line in out["limits"]), old)

    def test_without_the_lists_the_homes_table_has_no_pipeline_and_says_it_is_not_available(self):
        out = changed(lambda p: p.pop("projects"))
        self.assertFalse(out["homes"]["pipeline"]["available"])
        self.assertEqual(out["homes"]["pipeline_10_years"], 0)

    def test_a_project_under_review_is_shown_at_the_share_that_gets_built(self):
        parts = make_parts()
        parts["projects"] = projects(project("Residential", "Planning Application - Under Review", homes=1000))
        for pct, built in ((0, 0), (60, 600), (100, 1000)):
            with self.subTest(pct=pct):
                out = forecast(parts, settings=mine(built_review_pct=pct) if pct != 60 else None)
                self.assertEqual(out["homes"]["pipeline_10_years"], built)


class Figures(unittest.TestCase):
    def test_every_figure_is_listed_with_its_start_and_limits(self):
        figures = forecast()["figures"]
        self.assertEqual([f["id"] for f in figures], list(F.ASSUMPTIONS))
        for f in figures:
            label, unit, start, group, low, high = F.ASSUMPTIONS[f["id"]]
            self.assertEqual((f["label"], f["unit"], f["value"], f["start"], f["group"], f["lowest"], f["highest"], f["yours"]),
                             (label, unit, start, start, group, low, high, False))

    def test_a_changed_figure_is_marked_yours_and_the_answer_says_it_was_edited(self):
        out = forecast(settings=mine(spend_pct=45, bogus=3))
        figures = {f["id"]: f for f in out["figures"]}
        self.assertEqual((figures["spend_pct"]["value"], figures["spend_pct"]["yours"], figures["spend_pct"]["start"]), (45.0, True, 30))
        self.assertFalse(figures["local_pct"]["yours"])
        self.assertTrue(out["edited"])
        self.assertEqual(out["settings"], {"assumptions": {"spend_pct": 45.0}})
        self.assertFalse(forecast()["edited"])
        self.assertEqual(forecast()["settings"], {"assumptions": {}})

    def test_a_figure_sent_outside_its_limits_is_shown_at_the_limit(self):
        out = forecast(settings=mine(spend_pct=1000, ready_years=-5, capture_pct="900"))
        figures = {f["id"]: f["value"] for f in out["figures"]}
        self.assertEqual((figures["spend_pct"], figures["ready_years"], figures["capture_pct"]), (60.0, 0.0, 100.0))

    def test_a_figure_sent_at_its_starting_value_is_not_an_edit(self):
        out = forecast(settings=mine(spend_pct=30))
        self.assertFalse(out["edited"])
        self.assertEqual(out["settings"], {"assumptions": {}})

    def test_junk_settings_change_nothing(self):
        base = forecast()
        for junk in (None, [], "x", {"assumptions": "x"}, {"assumptions": {"spend_pct": "lots", "nope": 1}}, {"mode": "best"}):
            with self.subTest(junk=junk):
                out = forecast(settings=junk)
                self.assertEqual(out["programme"], base["programme"])
                self.assertEqual(out["shops"], base["shops"])
                self.assertFalse(out["edited"])


class EveryAssumptionMovesTheResult(unittest.TestCase):
    """Each figure pushes the answer the sensible way, and is held to its limits."""

    def setUp(self):
        self.base = forecast()

    def shop_space(self, out):
        return out["shops"]["new_10_years_sq_ft"]["expected"]

    def test_spending_more_of_income_in_shops_supports_more_shop_space(self):
        more, less = forecast(settings=mine(spend_pct=45)), forecast(settings=mine(spend_pct=15))
        self.assertGreater(more["shops"]["sq_ft_per_home"], self.base["shops"]["sq_ft_per_home"])
        self.assertLess(less["shops"]["sq_ft_per_home"], self.base["shops"]["sq_ft_per_home"])
        self.assertGreater(self.shop_space(more), self.shop_space(self.base))
        self.assertAlmostEqual(more["shops"]["sq_ft_per_home"], 100000 * 0.45 * 0.55 / 400, delta=0.06)

    def test_spending_closer_to_home_supports_more_shop_space(self):
        more, less = forecast(settings=mine(local_pct=80)), forecast(settings=mine(local_pct=20))
        self.assertGreater(self.shop_space(more), self.shop_space(self.base))
        self.assertLess(self.shop_space(less), self.shop_space(self.base))
        self.assertAlmostEqual(more["shops"]["sq_ft_per_home"], 100000 * 0.30 * 0.80 / 400, delta=0.06)

    def test_a_shop_that_needs_more_sales_a_square_foot_means_less_shop_space(self):
        more, less = forecast(settings=mine(sales_per_sq_ft=800)), forecast(settings=mine(sales_per_sq_ft=200))
        self.assertLess(self.shop_space(more), self.shop_space(self.base))
        self.assertGreater(self.shop_space(less), self.shop_space(self.base))
        self.assertAlmostEqual(more["shops"]["sq_ft_per_home"], self.base["shops"]["sq_ft_per_home"] / 2, delta=0.1)

    def test_more_floor_space_for_each_job_means_more_work_space(self):
        more, less = forecast(settings=mine(sq_ft_per_job=800)), forecast(settings=mine(sq_ft_per_job=200))
        key = "space_10_years_sq_ft"
        self.assertEqual(more["jobs"][key]["expected"], 2 * self.base["jobs"][key]["expected"])
        self.assertEqual(less["jobs"][key]["expected"], self.base["jobs"][key]["expected"] // 2)
        self.assertEqual(more["jobs"]["new_jobs_per_year"], self.base["jobs"]["new_jobs_per_year"])

    def test_traffic_that_follows_the_homes_more_closely_grows_faster(self):
        def last(out, scenario="expected"):
            return out["traffic"]["rows"][-1]["highway"][scenario]
        more, none, less = (forecast(settings=mine(traffic_follow_pct=v)) for v in (150, 0, 20))
        self.assertGreater(last(more), last(self.base))
        self.assertGreater(last(self.base), last(less))
        self.assertEqual(last(none), 100000.0)
        self.assertEqual(last(none, "high"), 100000.0)

    def test_winning_a_bigger_share_of_the_need_sells_the_land_faster(self):
        more, less = forecast(settings=mine(capture_pct=60)), forecast(settings=mine(capture_pct=5))
        self.assertGreater(uses_by_id(more)["business"]["by_year_10"], uses_by_id(self.base)["business"]["by_year_10"])
        for use_id in ("business", "retail"):
            self.assertGreaterEqual(uses_by_id(more)[use_id]["by_year_10"], uses_by_id(self.base)[use_id]["by_year_10"], use_id)
            self.assertLess(uses_by_id(less)[use_id]["by_year_10"], uses_by_id(self.base)[use_id]["by_year_10"], use_id)

    def test_all_of_the_need_is_taken_at_one_hundred_percent_but_never_more_than_the_land_has(self):
        out = forecast(settings=mine(capture_pct=100))
        for u in out["programme"]["uses"]:
            self.assertLessEqual(u["by_year_10"], u["amount"], u["id"])
            self.assertLessEqual(u["pct_by_year_10"], 100)
            self.assertLessEqual(u["acres_by_year_10"], u["acres"] + 0.05)
        business = uses_by_id(out)["business"]
        self.assertEqual(business["by_year"][2]["taken"], round(40000 * 200000 / 260000))      # the offices (60,000) take their share

    def test_a_slower_start_hands_over_less_land(self):
        quick, base, slow = (forecast(settings=mine(ready_years=v)) for v in (0, 2, 8))
        for use_id in ("business", "retail"):
            a, b, c = (uses_by_id(o)[use_id]["by_year_5"] for o in (quick, base, slow))
            self.assertGreater(a, b, use_id)
            self.assertGreater(b, c, use_id)
        self.assertEqual(uses_by_id(slow)["business"]["by_year_5"], 0)
        self.assertGreater(uses_by_id(quick)["business"]["by_year"][0]["taken"], 0)

    def test_a_longer_wait_moves_the_approvals_words(self):
        slow = forecast(settings=mine(ready_years=8))["programme"]["steps"]
        self.assertIn("No land is handed over yet", slow[0]["lines"][0])
        self.assertIn("about 2034", slow[2]["lines"][0])

    def test_a_larger_share_of_projects_that_get_built_adds_to_the_pipeline(self):
        parts = make_parts()
        parts["projects"] = projects(project("Residential", "Planning Application - Under Review", homes=1000),
                                     project("Commercial", "Planning Application - Under Review", feet=100000))
        low, mid, high = (forecast(parts, settings=mine(built_review_pct=v))["homes"]["pipeline_10_years"] for v in (10, 60, 100))
        self.assertLess(low, mid)
        self.assertLess(mid, high)

    def test_every_figure_is_clamped_on_its_way_in_and_the_answer_still_works(self):
        for key, spec in F.ASSUMPTIONS.items():
            for value in (spec[4] - 1000, spec[5] + 1000):
                with self.subTest(key=key, value=value):
                    out = forecast(settings=mine(**{key: value}))
                    shown = next(f["value"] for f in out["figures"] if f["id"] == key)
                    self.assertTrue(spec[4] <= shown <= spec[5])
                    json.dumps(out, allow_nan=False)

    def test_the_most_extreme_figures_at_once_still_give_an_ordered_answer(self):
        high = {k: spec[5] for k, spec in F.ASSUMPTIONS.items()}
        low = {k: spec[4] for k, spec in F.ASSUMPTIONS.items()}
        for figures in (high, low):
            out = forecast(settings=mine(**figures))
            self.assertGreater(check_order(self, out), 40)
            json.dumps(out, allow_nan=False)

    def test_a_changed_figure_changes_nothing_it_does_not_touch(self):
        out = forecast(settings=mine(spend_pct=45))
        self.assertEqual(out["homes"], self.base["homes"])
        self.assertEqual(out["jobs"], self.base["jobs"])
        self.assertEqual([r["highway"] for r in out["traffic"]["rows"]], [r["highway"] for r in self.base["traffic"]["rows"]])
        self.assertEqual(out["rings"], self.base["rings"])
        self.assertEqual(uses_by_id(out)["homes"], uses_by_id(self.base)["homes"])


# ---------------------------------------------------------------- surprising behaviour found while writing these

class Surprises(unittest.TestCase):
    """Edge cases a first pass over the engine found wrong, each now fixed: what each test expects is in its comment."""

    def test_a_ring_that_had_no_homes_at_the_last_count_has_no_growth_to_project(self):
        # 3 mile ring with 0 homes (and 0 people) at both counts, but the regional plan gave two readings of growth.
        # The forecast says available=True and projects 0 homes in every year.
        def empty(p):
            p["people"]["rings"][1].update(homes=0, people=0)
            p["people_before"]["rings"][1].update(homes=0, people=0)
        out = changed(empty)
        self.assertFalse(out["available"])

    def test_a_household_count_written_as_text_does_not_stop_the_forecast_working(self):
        # a tract whose "households" came as "1000" (text): TypeError "can't multiply sequence by non-int of type 'float'"
        out = changed(lambda p: p["tracts"]["tracts"][0].update(households="1000"))
        self.assertIsInstance(out, dict)

    def test_an_income_written_as_text_does_not_stop_the_forecast_working(self):
        out = changed(lambda p: p["tracts"]["tracts"][0].update(income="100000"))
        self.assertIsInstance(out, dict)

    def test_a_home_count_written_as_text_does_not_stop_the_forecast_working(self):
        # people_before.rings[3 mi].homes == "10000": TypeError "'<=' not supported between 'str' and 'int'" in yearly()
        out = changed(lambda p: p["people_before"]["rings"][1].update(homes="10000"))
        self.assertIsInstance(out, dict)

    def test_a_tract_with_a_share_for_the_market_ring_but_none_for_the_widest_does_not_stop_the_forecast(self):
        # share_within {"3": 1.0} (no "5"): rows stays empty, min() of an empty list raises ValueError
        out = changed(lambda p: p.update(tracts=survey(tract(share={"3": 1.0}))))
        self.assertIsInstance(out, dict)

    def test_a_negative_income_is_not_a_household_income(self):
        # the Census Bureau writes -666666666 where a median could not be worked out
        out = changed(lambda p: p.update(tracts=survey(tract("A", 100000), tract("B", -666666666, 1000, 100, 2.0))))
        self.assertGreater(out["income"].get("typical", 1), 0)

    def test_the_need_for_new_homes_is_never_negative_in_a_shrinking_area(self):
        # like the jobs (clamped at 0), the need shown should not be below zero: a low line of -90 "new homes needed" is odd
        out = changed(lambda p: p["people"]["rings"][1].update(homes=7000, people=21000))
        self.assertGreaterEqual(min(r["need"]["low"] for r in out["homes"]["rows"]), 0)

    def test_new_shop_space_is_never_negative_in_a_shrinking_area(self):
        out = changed(lambda p: p["people"]["rings"][1].update(homes=7000, people=21000))
        self.assertGreaterEqual(min(r["new_sq_ft"]["low"] for r in out["shops"]["rows"]), 0)

    def test_a_project_that_states_a_size_but_is_of_another_kind_is_not_reported_as_having_no_size(self):
        # kind "Institutional" with 50,000 sq ft: it meets none of the three needs, but it does state a size, so it is
        # counted on its own line and the limits do not say it "does not state a number of homes or a building size"
        out = changed(lambda p: p.update(projects=projects(project("Institutional", "Under Construction", feet=50000))))
        pipe = out["homes"]["pipeline"]
        self.assertEqual((pipe["projects_without_sizes"], pipe["projects_other_kinds"], pipe["projects_counted"]), (0, 1, 0))
        self.assertFalse(any("do not state" in line for line in out["limits"]))

    def test_a_negative_need_does_not_get_land_taken_up_below_zero(self):
        out = changed(lambda p: p["people"]["rings"][1].update(homes=7000, people=21000))
        for u in out["programme"]["uses"]:
            self.assertTrue(all(r["taken"] >= 0 for r in u["by_year"]), u["id"])


# ---------------------------------------------------------------- the edge cases above, from every side

def bad(t, **figures):
    """A tract with some of its figures replaced by what a source might hand over instead."""
    t.update(figures)
    return t


class NumbersFromTheSources(unittest.TestCase):
    """Whatever a source hands over, a number that cannot be used is missing for that row and never stops the forecast."""

    def test_count_reads_zero_or_more_and_whole_numbers_come_back_whole(self):
        self.assertEqual(F.count(12), 12)
        self.assertIsInstance(F.count(12.0), int)
        self.assertIsInstance(F.count("12"), int)
        self.assertEqual(F.count(0), 0)
        self.assertEqual(F.count(2.5), 2.5)

    def test_count_leaves_out_text_gaps_negative_codes_and_absurd_sizes(self):
        for value in (None, "", "many", "nan", float("inf"), -1, -666666666, 1e12, [], {}):
            with self.subTest(value=value):
                self.assertIsNone(F.count(value))

    def test_an_income_must_be_positive_and_a_size_a_median_could_be(self):
        self.assertEqual(F.income_of(85000), 85000)
        self.assertEqual(F.income_of("85000"), 85000)
        for value in (None, 0, -666666666, -1, "n/a", 10 ** 9, float("nan")):
            with self.subTest(value=value):
                self.assertIsNone(F.income_of(value))

    def test_a_tracts_share_is_found_under_a_number_or_a_text_key(self):
        for share in ({3: 0.4}, {"3": 0.4}):
            with self.subTest(share=share):
                self.assertEqual(F.share_of({"share_within": share}, 3), 0.4)

    def test_a_tract_with_no_share_for_a_distance_has_none_of_it_there(self):
        for t in ({}, {"share_within": None}, {"share_within": {}}, {"share_within": {"5": 1.0}}, {"share_within": {"3": "all"}},
                  {"share_within": [0.5]}):
            with self.subTest(tract=t):
                self.assertEqual(F.share_of(t, 3), 0.0)

    def test_a_share_stays_between_nothing_and_all_of_the_tract(self):
        self.assertEqual(F.share_of({"share_within": {"3": 1.7}}, 3), 1.0)
        self.assertEqual(F.share_of({"share_within": {"3": -0.2}}, 3), 0.0)

    def test_the_number_key_and_the_text_key_give_the_same_figures(self):
        by_number = changed(lambda p: p.update(tracts=survey(tract(share={1: 1.0, 3: 1.0, 5: 1.0}))))
        by_text = changed(lambda p: p.update(tracts=survey(tract(share={"1": 1.0, "3": 1.0, "5": 1.0}))))
        self.assertEqual(by_number["income"], by_text["income"])
        self.assertTrue(by_number["income"]["available"])


class TextWhereANumberIsExpected(unittest.TestCase):
    def test_a_household_count_that_is_a_number_in_text_is_read_as_the_number(self):
        out = changed(lambda p: p.update(tracts=survey(bad(tract("A", 100000, 1000, 100), households="1000"), tract("B", 60000, 1000, 100, 2.0))))
        self.assertEqual(out["income"]["typical"], 80000.0)

    def test_a_household_count_that_is_words_leaves_that_tract_out_of_the_average(self):
        out = changed(lambda p: p.update(tracts=survey(bad(tract("A", 100000, 1000, 100), households="lots"), tract("B", 60000, 1000, 100, 2.0))))
        self.assertEqual(out["income"]["typical"], 60000.0)

    def test_an_income_that_is_words_leaves_that_tract_out(self):
        out = changed(lambda p: p.update(tracts=survey(tract("A", "high", 1000, 100), tract("B", 60000, 1000, 100, 2.0))))
        self.assertEqual(out["income"]["typical"], 60000.0)
        self.assertEqual([r["name"] for r in out["income"]["tracts"]], ["B"])

    def test_renters_and_homes_built_since_that_are_words_count_as_none(self):
        out = changed(lambda p: p.update(tracts=survey(bad(tract("A", 100000, 1000, 100), renters="some", built_2020_on="few"))))
        self.assertEqual(out["income"]["renters_pct"], 0.0)
        self.assertEqual(out["income"]["built_since_2020"], 0)

    def test_a_distance_from_the_site_that_is_words_does_not_stop_the_list_of_tracts(self):
        out = changed(lambda p: p.update(tracts=survey(tract("A", 100000, 1000, 100, "near"), tract("B", 60000, 1000, 100, 2.0))))
        self.assertEqual([r["name"] for r in out["income"]["tracts"]], ["B", "A"])
        self.assertIsNone(out["income"]["tracts"][1]["miles_away"])

    def test_the_county_income_in_words_is_left_out(self):
        out = changed(lambda p: p.update(tracts=survey(tract(), county_income="unknown")))
        self.assertIsNone(out["income"]["county"])
        self.assertTrue(out["income"]["available"])

    def test_a_count_of_homes_in_the_2020_census_that_is_words_leaves_the_forecast_without_that_ring(self):
        out = changed(lambda p: p["people"]["rings"][1].update(homes="many"))
        self.assertFalse(out["available"])
        self.assertTrue(any("no reading of growth" in line.lower() for line in out["limits"]))

    def test_an_earlier_count_of_homes_that_is_words_leaves_out_only_the_counted_reading(self):
        out = changed(lambda p: p["people_before"]["rings"][1].update(homes="n/a"))
        three = ring3(out)
        self.assertEqual([r["id"] for r in three["readings"]], ["adopted", "draft"])
        self.assertTrue(out["available"])
        self.assertNotIn("2010", three["counted"], "an unusable count is not shown as a count")

    def test_an_earlier_count_of_homes_in_number_text_still_gives_the_counted_reading(self):
        out = changed(lambda p: p["people_before"]["rings"][1].update(homes="10000"))
        three = ring3(out)
        self.assertEqual([r["id"] for r in three["readings"]], ["measured", "adopted", "draft"])
        self.assertEqual(three["readings"][0]["from"], {"year": 2010, "homes": 10000})

    def test_households_in_the_regional_plan_that_are_words_leave_out_that_plan(self):
        def words(p):
            p["regional_plan"]["adopted"]["rings"][1]["households"]["2021"] = "x"
        self.assertEqual([r["id"] for r in ring3(changed(words))["readings"]], ["measured", "draft"])

    def test_jobs_in_the_regional_plan_that_are_words_leave_out_that_plan(self):
        def words(p):
            p["regional_plan"]["adopted"]["rings"][1]["jobs"]["2021"] = "x"
        out = changed(words)
        self.assertEqual([r["id"] for r in out["jobs"]["readings"]], ["draft"])
        self.assertTrue(out["jobs"]["available"])

    def test_project_sizes_that_are_words_are_not_sizes(self):
        out = changed(lambda p: p.update(projects=projects(project("Residential", "Under Construction", homes="lots"))))
        pipe = out["homes"]["pipeline"]
        self.assertEqual((pipe["projects_counted"], pipe["projects_without_sizes"]), (0, 1))

    def test_a_project_distance_that_is_words_does_not_stop_the_forecast(self):
        out = changed(lambda p: p.update(projects=projects(project("Residential", "Under Construction", homes=100, miles="close"))))
        self.assertEqual(out["homes"]["pipeline"]["projects_counted"], 1)


class ARingWithNoHomes(unittest.TestCase):
    def empty(self, index=1, before=True):
        def change(p):
            p["people"]["rings"][index].update(homes=0, people=0)
            if before:
                p["people_before"]["rings"][index].update(homes=0, people=0)
        return change

    def test_the_market_ring_with_none_has_no_forecast_and_the_limits_say_why(self):
        out = changed(self.empty())
        self.assertFalse(out["available"])
        self.assertFalse(ring3(out)["available"])
        self.assertEqual((out["headline"], out["homes"]["available"], out["shops"]["available"], out["programme"]["available"]),
                         ([], False, False, False))
        self.assertTrue(any("No homes were counted within 3 miles" in line for line in out["limits"]), out["limits"])
        self.assertFalse(any("no reading of growth" in line.lower() for line in out["limits"]), "the readings did answer")

    def test_it_still_shows_what_was_counted(self):
        three = ring3(changed(self.empty()))
        self.assertEqual(three["counted"]["2020"], {"people": 0, "homes": 0})
        self.assertNotIn("rows", three)

    def test_none_counted_in_2020_is_enough_even_if_some_were_counted_in_2010(self):
        self.assertFalse(changed(lambda p: p["people"]["rings"][1].update(homes=0, people=0))["available"])

    def test_none_counted_in_2010_does_not_stop_a_ring_that_has_homes_now(self):
        out = changed(lambda p: p["people_before"]["rings"][1].update(homes=0, people=0))
        self.assertTrue(out["available"])
        self.assertEqual([r["id"] for r in ring3(out)["readings"]], ["adopted", "draft"], "no growth can be measured from nothing")

    def test_homes_but_no_people_counted_is_not_a_ring_to_forecast_from(self):
        self.assertFalse(changed(lambda p: p["people"]["rings"][1].update(people=None))["available"])

    def test_a_wide_ring_with_none_leaves_the_traffic_out_and_the_rest_working(self):
        out = changed(self.empty(2))
        self.assertTrue(out["available"])
        self.assertFalse(out["traffic"]["available"])
        self.assertFalse(next(r for r in out["rings"] if r["miles"] == 5)["available"])

    def test_a_narrow_ring_with_none_leaves_everything_else_alone(self):
        base = forecast()
        out = changed(self.empty(0))
        self.assertEqual(out["homes"], base["homes"])
        self.assertEqual(out["programme"], base["programme"])
        self.assertFalse(next(r for r in out["rings"] if r["miles"] == 1)["available"])


class AnIncomeThatIsNotOne(unittest.TestCase):
    def test_the_censuss_code_for_not_worked_out_is_no_income(self):
        out = changed(lambda p: p.update(tracts=survey(tract("A", 100000), tract("B", -666666666, 1000, 100, 2.0))))
        income = out["income"]
        self.assertEqual((income["typical"], income["lowest"], income["highest"]), (100000.0, 100000, 100000))
        self.assertEqual([r["name"] for r in income["tracts"]], ["A"])

    def test_its_households_still_count_as_households_for_the_share_who_rent(self):
        out = changed(lambda p: p.update(tracts=survey(tract("A", 100000, 1000, 100), tract("B", -666666666, 1000, 400, 2.0))))
        self.assertEqual(out["income"]["renters_pct"], 25.0)

    def test_every_tract_without_an_income_means_no_income(self):
        for bad in (-666666666, 0, None, "none", 10 ** 10):
            with self.subTest(income=bad):
                out = changed(lambda p: p.update(tracts=survey(tract("A", bad), tract("B", bad, 1000, 100, 2.0))))
                self.assertEqual(out["income"], {"available": False})
                self.assertFalse(out["shops"]["available"])
                self.assertTrue(out["homes"]["available"])

    def test_the_county_figure_is_left_out_when_it_is_the_not_worked_out_code(self):
        out = changed(lambda p: p.update(tracts=survey(tract(), county_income=-666666666)))
        self.assertIsNone(out["income"]["county"])
        self.assertNotIn("the Test County figure", out["income"]["summary"])
        self.assertTrue(out["income"]["available"])

    def test_the_by_direction_lines_leave_it_out_too(self):
        out = changed(lambda p: p.update(tracts=survey(tract("A", 100000, direction="north"),
                                                       tract("B", -666666666, 1000, 100, 2.0, "south"))))
        self.assertEqual([h["direction"] for h in out["income"]["by_direction"]], ["north"])


class ATractThatDoesNotReachTheWidestRing(unittest.TestCase):
    def test_a_tract_with_a_share_only_for_the_market_ring_still_counts_there(self):
        out = changed(lambda p: p.update(tracts=survey(tract(share={"3": 1.0}))))
        self.assertTrue(out["income"]["available"])
        self.assertEqual(out["income"]["typical"], 100000.0)
        self.assertEqual(len(out["income"]["tracts"]), 1)

    def test_a_tract_with_no_share_in_the_market_ring_or_wider_has_no_income_to_give(self):
        for share in ({"1": 0.0}, {"3": 0.0, "5": 0.0}, {"1": 1.0}, {"x": 1.0}):
            with self.subTest(share=share):
                out = changed(lambda p: p.update(tracts=survey(tract(share=share))))
                self.assertEqual(out["income"], {"available": False})

    def test_a_tract_with_no_share_next_to_one_that_has_is_ignored(self):
        out = changed(lambda p: p.update(tracts=survey(tract("A", 100000), tract("B", 40000, 1000, 100, 2.0, share={"1": 1.0}))))
        self.assertEqual(out["income"]["typical"], 100000.0)


class ANeedIsNeverBelowZero(unittest.TestCase):
    def shrinking(self):
        return changed(lambda p: p["people"]["rings"][1].update(homes=7000, people=21000))

    def test_no_need_line_falls_below_zero_and_the_lines_stay_in_order(self):
        out = self.shrinking()
        for r in out["homes"]["rows"]:
            self.assertTrue(all(v >= 0 for v in r["need"].values()), r)
            self.assertTrue(all(v >= 0 for v in r.get("need_so_far", {}).values()), r)
        for r in out["shops"]["rows"]:
            self.assertTrue(all(v >= 0 for v in r["new_sq_ft"].values()), r)
            self.assertTrue(all(v >= 0 for v in r["new_so_far"].values()), r)
        self.assertTrue(all(v >= 0 for v in out["homes"]["need_10_years"].values()))
        self.assertTrue(all(v >= 0 for v in out["shops"]["new_10_years_sq_ft"].values()))
        check_order(self, out)

    def test_the_headline_never_asks_for_a_negative_number_of_homes_or_shops(self):
        for item in self.shrinking()["headline"]:
            if "needed" in item["label"] or "shop space" in item["label"]:
                self.assertGreaterEqual(min(item["value"], item["low"], item["high"]), 0, item)

    def test_the_homes_and_the_people_lines_themselves_still_fall(self):
        three = ring3(self.shrinking())
        self.assertGreater(three["rows"][0]["homes"]["low"], three["rows"][-1]["homes"]["low"])
        self.assertGreater(three["rows"][0]["people"]["low"], three["rows"][-1]["people"]["low"])
        self.assertLess(three["rates_pct"]["low"], 0)

    def test_the_homes_rented_and_owned_a_year_are_never_negative(self):
        for r in self.shrinking()["homes"]["rows"]:
            if "rented" in r:
                self.assertGreaterEqual(min(r["rented"], r["owned"]), 0)

    def test_a_growing_area_is_not_changed_by_the_rule(self):
        row = next(r for r in forecast()["homes"]["rows"] if r["year"] == 2028)
        self.assertEqual(row["need"], {"low": 0, "expected": round(10000 * 1.1 ** 7 * 0.1), "high": round(10000 * 1.21 ** 7 * 0.21)})


class ProjectsOfOtherKindsAndDroppedOnes(unittest.TestCase):
    def run_with(self, *rows, **kw):
        return F.pipeline({"projects": projects(*rows, **kw)}, {"built_review_pct": 60}, YEARS)

    def test_a_project_of_another_kind_that_states_a_size_is_its_own_count(self):
        out = self.run_with(project("Institutional", "Under Construction", feet=50000))
        self.assertEqual((out["projects_other_kinds"], out["projects_without_sizes"], out["projects_counted"]), (1, 0, 0))
        self.assertTrue(all(v == 0 for per in out["per_year"].values() for v in per.values()))
        self.assertEqual(out["stages"], [])

    def test_a_project_with_no_size_at_all_is_still_without_sizes_whatever_its_kind(self):
        out = self.run_with(project("Institutional", "Under Construction"), project("", "Under Construction"),
                            project("Residential", "Under Construction"), project("Commercial", "Under Construction"))
        self.assertEqual((out["projects_other_kinds"], out["projects_without_sizes"]), (0, 4))

    def test_a_known_kind_with_only_the_wrong_kind_of_size_is_without_sizes_not_another_kind(self):
        out = self.run_with(project("Residential", "Under Construction", feet=90000))
        self.assertEqual((out["projects_other_kinds"], out["projects_without_sizes"]), (0, 1))

    def test_a_project_of_another_kind_that_states_homes_is_still_counted_as_homes(self):
        out = self.run_with(project("Institutional", "Under Construction", homes=40))
        self.assertEqual((out["projects_counted"], out["projects_other_kinds"]), (1, 0))
        self.assertAlmostEqual(sum(out["per_year"]["homes"].values()), 40)

    def test_a_missing_kind_does_not_stop_the_count(self):
        self.assertEqual(self.run_with(project(None, "Under Construction", feet=1000))["projects_other_kinds"], 1)

    def test_the_limits_say_it_in_plain_words(self):
        out = changed(lambda p: p.update(projects=projects(project("Institutional", "Under Construction", feet=50000),
                                                           project("Public", "Approved", feet=2000))))
        self.assertEqual(out["homes"]["pipeline"]["projects_other_kinds"], 2)
        said = [line for line in out["limits"] if "not homes, shops or work space" in line]
        self.assertEqual(len(said), 1)
        self.assertTrue(said[0].startswith("2 projects"))
        self.assertNotIn("pipeline", " ".join(out["limits"]).lower())

    def test_one_project_gets_the_singular(self):
        out = changed(lambda p: p.update(projects=projects(project("Institutional", "Under Construction", feet=50000))))
        self.assertIn("1 project on the city's lists", " ".join(out["limits"]))

    def test_a_status_that_says_the_project_will_not_be_built_is_not_coming(self):
        for status in ("Withdrawn", "Denied", "Expired", "Cancelled", "Not approved", "WITHDRAWN BY APPLICANT", "Application Denied",
                       "Canceled", "Disapproved"):
            with self.subTest(status=status):
                out = self.run_with(project("Residential", status, homes=100))
                self.assertEqual((out["projects_dropped"], out["projects_counted"]), (1, 0))
                self.assertEqual(out["stages"], [])
                self.assertEqual(sum(out["per_year"]["homes"].values()), 0)

    def test_a_dropped_project_is_not_also_counted_as_without_a_size_or_another_kind(self):
        out = self.run_with(project("Residential", "Withdrawn"), project("Institutional", "Denied", feet=9000))
        self.assertEqual((out["projects_dropped"], out["projects_without_sizes"], out["projects_other_kinds"]), (2, 0, 0))

    def test_not_approved_is_not_the_approved_stage(self):
        self.assertNotEqual(F.stage_of("Not approved"), 2)
        self.assertNotEqual(F.stage_of("Disapproved"), 2)
        self.assertEqual(F.stage_of("Approved"), 2)
        self.assertEqual(F.stage_of("Approved - Under Construction"), 0)

    def test_words_that_only_look_like_a_dropped_status_are_not_dropped(self):
        for status in ("App - Approved Planning", "Planning Application - Under Review", "Under Construction", ""):
            with self.subTest(status=status):
                self.assertEqual(self.run_with(project("Residential", status, homes=10))["projects_dropped"], 0)

    def test_a_dropped_project_far_away_is_not_counted_anywhere(self):
        out = self.run_with(project("Residential", "Withdrawn", homes=100, miles=4.0))
        self.assertEqual((out["projects_dropped"], out["projects_listed"]), (0, 1))

    def test_the_live_projects_are_counted_as_before_beside_a_dropped_one(self):
        out = self.run_with(project("Residential", "Under Construction", homes=100), project("Residential", "Withdrawn", homes=500))
        self.assertEqual((out["projects_counted"], out["projects_dropped"]), (1, 1))
        self.assertAlmostEqual(sum(out["per_year"]["homes"].values()), 100)

    def test_the_limits_say_how_many_were_dropped_and_they_are_not_in_the_homes_coming(self):
        out = changed(lambda p: p.update(projects=projects(project("Residential", "Withdrawn", homes=100),
                                                           project("Residential", "Not approved", homes=100),
                                                           project("Residential", "Under Construction", homes=100))))
        pipe = out["homes"]["pipeline"]
        self.assertEqual((pipe["projects_dropped"], pipe["projects_counted"]), (2, 1))
        said = [line for line in out["limits"] if "withdrawn, denied, expired or cancelled" in line]
        self.assertEqual(len(said), 1)
        self.assertTrue(said[0].startswith("2 projects"))
        self.assertEqual(out["homes"]["pipeline_10_years"], 100)

    def test_the_output_only_gained_fields(self):
        self.assertTrue({"per_year", "stages", "projects_counted", "projects_without_sizes", "projects_listed", "lists_updated",
                         "available", "projects_other_kinds", "projects_dropped"} <= set(self.run_with()))

    def test_a_list_with_nothing_wrong_says_nothing_new(self):
        out = changed(lambda p: p.update(projects=projects(project("Residential", "Under Construction", homes=100))))
        self.assertFalse(any("withdrawn" in line or "not homes, shops" in line for line in out["limits"]))


# ---------------------------------------------------------------- the whole city's homes by year (the state's estimates)

CITY_2020 = 40000.0


def city_rows(first=2020, last=2026, rate=0.02, skip=()):
    return [{"year": y, "homes": CITY_2020 * (1 + rate) ** (y - 2020)} for y in range(first, last + 1) if y not in skip]


def with_city(rows, source="Test state estimates"):
    parts = make_parts()
    parts["population"] = {"rows": rows, "source": source}
    return parts


def ring3(out):
    return next(r for r in out["rings"] if r["miles"] == 3)


class TheCityHomesByYear(unittest.TestCase):
    def test_rows_become_homes_by_year(self):
        self.assertEqual(F.city_homes(with_city([{"year": 2020, "homes": 100}, {"year": 2021, "homes": 110.5}])), {2020: 100.0, 2021: 110.5})

    def test_no_answer_gives_nothing(self):
        for parts in ({}, {"population": None}, {"population": {}}, {"population": {"rows": None}}, {"population": {"rows": []}}):
            with self.subTest(parts=parts):
                self.assertEqual(F.city_homes(parts), {})

    def test_a_row_that_cannot_be_used_is_skipped(self):
        rows = [{"year": 2020, "homes": 100}, {"year": 2021, "homes": 0}, {"year": 2022, "homes": "n/a"}, {"year": 2023, "homes": None},
                {"year": 2024, "homes": -5}, {"year": 2025}, {"year": 2026, "homes": "120"}, {"year": "2027", "homes": 130},
                {"year": 2028.5, "homes": 140}, {"year": None, "homes": 150}, {"year": True, "homes": 160}, {"homes": 170}]
        self.assertEqual(F.city_homes(with_city(rows)), {2020: 100.0, 2026: 120.0})

    def test_a_year_given_twice_keeps_the_later_row(self):
        self.assertEqual(F.city_homes(with_city([{"year": 2020, "homes": 100}, {"year": 2020, "homes": 105}])), {2020: 105.0})


class TheCityReading(unittest.TestCase):
    def city_of(self, rows, miles=3):
        return next((r for r in F.home_readings(with_city(rows), miles) if r["id"] == "city"), None)

    def test_the_city_is_one_more_measured_reading_from_the_first_year_after_2020_to_the_latest(self):
        got = F.home_readings(with_city(city_rows()), 3)
        self.assertEqual([r["id"] for r in got], ["measured", "city", "adopted", "draft"])
        city = got[1]
        self.assertEqual((city["kind"], city["rate_pct"], city["whole_city"]), ("measured", 2.0, True))
        self.assertEqual((city["from"]["year"], city["to"]["year"]), (2021, 2026))
        self.assertEqual((city["from"]["homes"], city["to"]["homes"]), (round(CITY_2020 * 1.02), round(CITY_2020 * 1.02 ** 6)))
        self.assertIn("2021 to 2026", city["label"])
        self.assertIn("whole city", city["label"])
        self.assertEqual(city["source"], "Test state estimates")

    def test_it_is_there_for_every_ring(self):
        for miles in F.RINGS:
            with self.subTest(miles=miles):
                self.assertIsNotNone(self.city_of(city_rows(), miles))

    def test_without_a_source_name_the_state_is_named(self):
        parts = with_city(city_rows())
        parts["population"].pop("source")
        self.assertIn("Department of Finance", F.home_readings(parts, 3)[1]["source"])

    def test_only_the_census_year_gives_no_reading(self):
        self.assertIsNone(self.city_of([{"year": 2020, "homes": 100}]))

    def test_one_year_after_2020_is_not_a_rate_yet_and_two_are(self):
        self.assertIsNone(self.city_of(city_rows(last=2021)))
        self.assertEqual((self.city_of(city_rows(last=2022))["from"]["year"], self.city_of(city_rows(last=2022))["to"]["year"]), (2021, 2022))

    def test_a_gap_in_the_years_still_measures_between_the_first_and_the_last_found(self):
        city = self.city_of(city_rows(skip=(2022, 2023, 2024)))
        self.assertEqual((city["from"]["year"], city["to"]["year"], city["rate_pct"]), (2021, 2026, 2.0))

    def test_a_missing_2021_starts_at_the_next_year_found(self):
        city = self.city_of(city_rows(skip=(2021,)))
        self.assertEqual((city["from"]["year"], city["rate_pct"]), (2022, 2.0))

    def test_years_before_2020_are_not_part_of_it(self):
        self.assertEqual(self.city_of(city_rows() + [{"year": 2019, "homes": 1000.0}, {"year": 2015, "homes": 10.0}])["rate_pct"], 2.0)

    def test_a_year_that_is_not_a_whole_number_is_left_out(self):
        city = self.city_of(city_rows(last=2022) + [{"year": 2023.5, "homes": 1.0}, {"year": "2024", "homes": 1.0}])
        self.assertEqual((city["to"]["year"], city["rate_pct"]), (2022, 2.0))

    def test_a_year_with_zero_or_text_homes_is_left_out(self):
        city = self.city_of(city_rows(last=2022) + [{"year": 2023, "homes": 0}, {"year": 2024, "homes": "many"}, {"year": 2025, "homes": None}])
        self.assertEqual((city["to"]["year"], city["rate_pct"]), (2022, 2.0))

    def test_homes_in_number_text_are_read(self):
        rows = [{"year": y, "homes": str(h)} for y, h in ((2020, 100), (2021, 100), (2022, 121))]
        self.assertEqual(self.city_of(rows)["rate_pct"], 21.0)

    def test_a_city_that_shrank_is_a_negative_reading_and_one_that_did_not_change_is_zero(self):
        self.assertEqual(self.city_of(city_rows(rate=-0.01))["rate_pct"], -1.0)
        self.assertEqual(self.city_of(city_rows(rate=0.0))["rate_pct"], 0.0)

    def test_the_reading_can_be_sent_as_json(self):
        json.dumps(F.home_readings(with_city(city_rows()), 3))


class TheForecastWithTheCityHomes(unittest.TestCase):
    """The round facts again: 10,000 homes in the 3 mile ring in 2020 and a city of 40,000 homes growing 2% a year, so
    a year up to the latest count is 10,000 x 1.02 ^ (year - 2020) on every line."""

    def ratio(self, y, rate=0.02):
        return (1 + rate) ** (y - 2020)

    def rows(self, out, key="homes"):
        return {r["year"]: r[key] for r in ring3(out)["rows"]}

    def test_without_the_city_nothing_changes(self):
        base = forecast()
        for parts in ({**make_parts(), "population": None}, with_city([]), with_city([{"year": 2020, "homes": CITY_2020}])):
            with self.subTest(population=parts.get("population")):
                self.assertEqual(forecast(parts), base)
        self.assertEqual(ring3(base)["today_from"]["year"], 2020)
        self.assertEqual([r["id"] for r in ring3(base)["readings"]], ["measured", "adopted", "draft"])

    def test_years_up_to_the_latest_count_follow_the_citys_ratio_on_all_three_lines(self):
        out = forecast(with_city(city_rows()))
        for y in (2025, 2026):
            with self.subTest(year=y):
                self.assertEqual(self.rows(out)[y], {s: round(10000 * self.ratio(y)) for s in F.SCENARIOS})
        for y, row in self.rows(out, "people").items():
            if y <= 2026:
                self.assertEqual(len(set(row.values())), 1, "the three lines are one measured line up to the latest count")

    def test_later_years_follow_each_line_from_there(self):
        out = forecast(with_city(city_rows()))
        homes, rates = self.rows(out), ring3(out)["rates_pct"]
        for y in (2027, 2030, 2036):
            for s in F.SCENARIOS:
                with self.subTest(year=y, line=s):
                    self.assertAlmostEqual(homes[y][s], 10000 * self.ratio(2026) * (1 + rates[s] / 100) ** (y - 2026), delta=1)
        self.assertGreater(homes[2036]["high"], homes[2036]["expected"])
        self.assertGreater(homes[2036]["expected"], homes[2036]["low"])

    def test_four_readings_give_the_low_expected_and_high_lines(self):
        out = forecast(with_city(city_rows()))
        # 0% counted, 2% the city, 10% adopted plan, 21% draft plan: the middle of four is the average of the middle two
        self.assertEqual(ring3(out)["rates_pct"], {"low": 0.0, "expected": 6.0, "high": 21.0})
        self.assertFalse(ring3(out)["one_reading"])

    def test_the_needs_start_from_the_last_measured_year(self):
        first = next(r for r in forecast(with_city(city_rows()))["homes"]["rows"] if r["year"] == 2027)
        self.assertAlmostEqual(first["need"]["expected"], 10000 * self.ratio(2026) * 0.06, delta=1)
        self.assertAlmostEqual(first["need"]["low"], 0, delta=1)

    def test_the_page_is_told_where_the_forecast_starts(self):
        today = ring3(forecast(with_city(city_rows())))["today_from"]
        self.assertEqual(today["year"], 2026)
        self.assertIn("2026", today["words"])
        self.assertEqual(ring3(forecast())["today_from"]["year"], 2020)

    def test_the_other_rings_follow_the_city_too(self):
        out = forecast(with_city(city_rows()))
        for miles, size in ((1, 1000), (5, 30000)):
            ring = next(r for r in out["rings"] if r["miles"] == miles)
            with self.subTest(miles=miles):
                self.assertEqual(ring["rows"][1]["homes"]["low"], round(size * self.ratio(2026)))
                self.assertEqual(ring["today_from"]["year"], 2026)

    def test_people_follow_the_homes(self):
        out = forecast(with_city(city_rows()))
        self.assertEqual(ring3(out)["people_per_home"], 3.0)
        for row in ring3(out)["rows"]:
            self.assertAlmostEqual(row["people"]["expected"], 3 * row["homes"]["expected"], delta=10)

    def test_a_gap_in_the_years_holds_the_last_count_until_the_next(self):
        homes = self.rows(forecast(with_city(city_rows(skip=(2025,)))))
        self.assertEqual(homes[2025]["expected"], round(10000 * self.ratio(2024)))      # 2025 is not in the file: 2024 stands
        self.assertEqual(homes[2026]["expected"], round(10000 * self.ratio(2026)))

    def test_the_latest_year_can_be_after_this_year(self):
        out = forecast(with_city(city_rows(last=2028)))
        homes = self.rows(out)
        self.assertEqual(homes[2028], {s: round(10000 * self.ratio(2028)) for s in F.SCENARIOS})
        self.assertEqual(ring3(out)["today_from"]["year"], 2028)
        self.assertGreater(homes[2029]["high"], homes[2029]["low"])

    def test_the_latest_year_can_be_before_last_year(self):
        homes = self.rows(forecast(with_city(city_rows(last=2023))))
        self.assertAlmostEqual(homes[2025]["low"], 10000 * self.ratio(2023), delta=1)       # 0% from 2023 on the low line
        self.assertGreater(homes[2025]["high"], homes[2025]["low"])

    def test_one_year_after_2020_makes_the_ring_follow_the_city_to_that_year_with_the_old_rates(self):
        out = forecast(with_city(city_rows(last=2021)))
        self.assertEqual(ring3(out)["today_from"]["year"], 2021)
        self.assertEqual([r["id"] for r in ring3(out)["readings"]], ["measured", "adopted", "draft"])
        self.assertEqual(ring3(out)["rates_pct"], ring3(forecast())["rates_pct"])

    def test_without_the_census_year_in_the_file_the_ring_is_not_tied_to_the_city(self):
        out = forecast(with_city(city_rows(first=2021)))
        self.assertEqual(ring3(out)["today_from"]["year"], 2020)
        self.assertEqual([r["id"] for r in ring3(out)["readings"]], ["measured", "city", "adopted", "draft"])
        self.assertEqual(self.rows(out)[2026]["low"], 10000, "the low line (0%) carries the 2020 count forward")

    def test_a_year_that_is_not_a_whole_number_does_not_move_the_start(self):
        out = forecast(with_city(city_rows(last=2022) + [{"year": 2023.5, "homes": 99999.0}]))
        self.assertEqual(ring3(out)["today_from"]["year"], 2022)

    def test_zero_or_text_homes_for_a_year_are_ignored(self):
        base = forecast(with_city(city_rows()))
        for bad in (0, "many", None, -4):
            with self.subTest(homes=bad):
                self.assertEqual(forecast(with_city(city_rows() + [{"year": 2027, "homes": bad}])), base)

    def test_a_city_that_shrank_pulls_the_ring_down_but_the_need_stays_at_zero(self):
        out = forecast(with_city(city_rows(rate=-0.03)))
        self.assertEqual(self.rows(out)[2025]["expected"], round(10000 * 0.97 ** 5))
        self.assertTrue(all(r["need"][s] >= 0 for r in out["homes"]["rows"] for s in F.SCENARIOS))
        check_order(self, out)

    def test_the_lines_stay_in_order_and_the_answer_can_be_sent_as_json(self):
        out = forecast(with_city(city_rows()))
        self.assertGreater(check_order(self, out), 50)
        json.dumps(out)

    def test_the_city_alone_is_enough_for_a_forecast_and_it_says_one_reading(self):
        parts = with_city(city_rows())
        parts["people_before"] = None
        parts["regional_plan"] = None
        out = forecast(parts)
        self.assertTrue(out["available"])
        self.assertEqual([r["id"] for r in ring3(out)["readings"]], ["city"])
        self.assertTrue(ring3(out)["one_reading"])
        self.assertEqual(ring3(out)["rates_pct"], {"low": 2.0, "expected": 2.0, "high": 2.0})

    def test_the_city_cannot_help_a_ring_that_has_no_homes_counted(self):
        parts = with_city(city_rows())
        parts["people"]["rings"][1].update(homes=0, people=0)
        out = forecast(parts)
        self.assertFalse(out["available"])
        self.assertTrue(any("No homes were counted" in line for line in out["limits"]))


# ---------------------------------------------------------------- the advice and the take-up say the same thing

class AdviceAgreesWithTheTakeUp(unittest.TestCase):
    """Homes already on the city's lists must hold the site's housing back in the same years the advice says they do."""

    def housing(self, out):
        return [u for u in out["programme"]["uses"] if u["kind"] == "homes"]

    def test_with_many_homes_on_the_way_no_housing_land_is_taken_before_the_first_year_with_room(self):
        # 30,000 homes under review (60% expected to be built) fill 2030 to 2034 many times over
        out = changed(lambda p: p.update(projects=projects(project("Residential", "Application under review", homes=30000))))
        room = out["homes"]["room_from_year"]
        self.assertGreater(out["homes"]["pipeline_covers_years"], 6)
        self.assertEqual(room, 2029, "the land is ready after 2028; the projects arrive from 2030, so 2029 is the first year with room")
        # no room in 2030 to 2034: the need left is zero, so nothing is taken then
        for u in self.housing(out):
            took = {r["year"]: r["taken"] for r in u["by_year"]}
            for y in range(2030, 2035):
                self.assertEqual(took[y], 0, (u["id"], y))
        left = {r["year"]: r["left_after_projects"] for r in out["homes"]["rows"] if "left_after_projects" in r}
        self.assertTrue(all(left[y] == 0 for y in range(2030, 2035)))
        self.assertGreater(left[2029], 0)

    def test_when_the_opening_is_later_the_advice_gives_that_year_and_the_take_up_starts_there(self):
        out = changed(lambda p: p.update(projects=projects(project("Residential", "Under Construction", homes=60000),
                                                          project("Residential", "Approved by planning", homes=60000))),
                      settings=mine(ready_years=0))
        room = out["homes"]["room_from_year"]
        self.assertIsNotNone(room)
        words = " ".join(out["advice"])
        self.assertNotIn("steady pace", words)
        self.assertIn(f"first appears in {room}", words)
        for u in self.housing(out):
            first = next(r["year"] for r in u["by_year"] if r["taken"] > 0)
            self.assertGreaterEqual(first, room, u["id"])

    def test_with_no_projects_on_the_lists_the_first_year_the_land_is_ready_has_room(self):
        out = forecast()
        self.assertEqual(out["homes"]["room_from_year"], 2029)
        self.assertNotIn("first appears", " ".join(out["advice"]))
        self.assertTrue(all(r["left_after_projects"] == r["need"]["expected"] or abs(r["left_after_projects"] - r["need"]["expected"]) <= 1
                            for r in out["homes"]["rows"] if "left_after_projects" in r))

    def test_the_limits_say_the_site_is_offered_only_what_the_projects_leave(self):
        out = changed(lambda p: p.update(projects=projects(project("Residential", "Under Construction", homes=1000))))
        self.assertTrue(any("left after the projects already on the city's lists" in x for x in out["limits"]))
        self.assertFalse(any("left after the projects" in x for x in forecast()["limits"]), "no projects counted, nothing to say")

    def test_the_figure_that_sets_the_share_says_what_it_is_a_share_of(self):
        label = next(f["label"] for f in forecast()["figures"] if f["id"] == "capture_pct")
        self.assertIn("after the projects already on the city's lists", label)


if __name__ == "__main__":
    unittest.main()
