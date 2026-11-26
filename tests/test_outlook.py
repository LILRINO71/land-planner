"""The wider-picture engine (landplanner/outlook.py) on small hand-made inputs. No fixtures, no network.

The inputs are built here in the shapes landplanner/sources/economy.py and place.py document. The standard economy is
"round" on purpose so that a sentence can be checked by hand: homes grow from 40,000 (2020) to 44,000 (2025), the
city's shops took in $500 million in 2020 and $660 million in 2025 while prices rose 20% (so the real gain is exactly
10%), and so on. Key sentences are compared whole, so that a change of wording is noticed; the rest is behaviour.

A comment above a test says what went wrong before it was fixed (each was an expected failure until the module was mended).
"""
import copy
import json
import re
import unittest

import support  # noqa: F401  (puts the project folder on the import path)
from landplanner import outlook as O

YEAR = 2026
YEARS = list(range(2025, 2037))          # last year for background, this year, ten more
SCENARIOS = ("low", "expected", "high")
BANNED = ("pipeline", "absorption", "entitlement")


# ---------------------------------------------------------------- hand-made inputs

def forecast(year=YEAR, ready=2, trips=0, steps=None, highway=None, rings="standard"):
    """What the steps and the economy read of a forecast: the year, the three growth lines of the 3 mile ring
    (10,000 homes in 2025; the low line gains 50 a year, the expected 100 and the high 200), the figures, the programme."""
    years = list(range(year - 1, year + 11))
    if rings == "standard":
        rings = [{"miles": 3, "rows": [{"year": y, "homes": {"low": 10000 + 50 * (y - years[0]), "expected": 10000 + 100 * (y - years[0]),
                                                              "high": 10000 + 200 * (y - years[0])}} for y in years]}]
    out = {"year": year, "years": years, "rings": rings, "figures": [{"id": "capture_pct", "value": 20}, {"id": "ready_years", "value": ready}],
           "programme": {"trips_at_build_out": trips, "steps": steps or []}}
    if highway:
        out["traffic"] = {"highway": highway}
    return out


def population():
    return {"rows": [{"year": 2020, "people": 100000, "homes": 40000, "occupied_homes": 38000},
                     {"year": 2025, "people": 110000, "homes": 44000, "occupied_homes": 42000}], "source": "Test state estimates"}


def permits():
    return {"rows": [{"year": y, "homes": 1000 + 200 * i, "single_family": 900 + 180 * i, "multi_family": 100 + 20 * i, "months_reported": 12}
                     for i, y in enumerate(range(2021, 2026))], "missing_years": [], "source": "Test permits"}


def sales(*rows):
    return {"rows": [{"year": y, "sales_usd": s, "quarters": q} for y, s, q in rows], "source": "Test tax agency"}


def standard_sales():
    return sales((2020, 500_000_000, 4), (2021, 540_000_000, 4), (2022, 580_000_000, 4), (2023, 600_000_000, 4),
                 (2024, 630_000_000, 4), (2025, 660_000_000, 4))


def work():
    return {"rows": [{"year": 2024, "unemployment_pct": 5.0, "labour_force": 50000, "employed": 47500},
                     {"year": 2025, "unemployment_pct": 5.4, "labour_force": 51936, "employed": 49000}],
            "county_rows": [{"year": 2025, "unemployment_pct": 5.5, "labour_force": 1000000}], "source": "Test jobs agency"}


def borrowing(weeks=47):
    return {"rows": [{"year": 2021, "rate_pct": 2.96, "weeks": 52}, {"year": 2025, "rate_pct": 6.2, "weeks": 52},
                     {"year": 2026, "rate_pct": 6.57, "weeks": weeks}], "latest": {"date": "2026-11-20", "rate_pct": 7.21},
            "source": "Test mortgage survey"}


def prices():
    return {"rows": [{"year": 2020, "index": 100.0, "change_pct": None}, {"year": 2025, "index": 120.0, "change_pct": 3.0}],
            "source": "Test price index"}


def economy_parts():
    return {"population": population(), "permits": permits(), "sales": standard_sales(), "work": work(), "borrowing": borrowing(),
            "prices": prices()}


def economy(parts=None, fc=None, name="Testville"):
    return O.economy(economy_parts() if parts is None else parts, fc or forecast(), name)


def climate_part():
    return {"typical_year": {"mean_f": 61.4, "rain_in": 11.8, "wind_mph": 5.5},
            "months": [{"month": "Jan", "mean_f": 48.7, "high_f": 74.2, "rain_in": 2.1}, {"month": "Jul", "mean_f": 77.7, "high_f": 104.3, "rain_in": 0.2},
                       {"month": "Aug", "mean_f": 77.8, "high_f": 103.9, "rain_in": 0.3}],
            "trend": {"mean_f_per_decade": 0.4, "rain_in_per_decade": -0.3, "from_year": 1985, "to_year": 2025}}


def resident_part():
    return {"typical": {"median_age": 36.4, "household_size": 3.39, "home_value_usd": 556728, "rent_usd": 2212, "bachelors_pct": 28.6,
                        "drive_alone_pct": 75.3, "work_from_home_pct": 14.8, "long_commute_pct": 28.6, "under_18_pct": 27.9, "over_65_pct": 12.1},
            "earlier": {"years": "2010-2014", "home_value_usd": 244032, "rent_usd": 1484, "tracts_matched": 14}, "tracts": []}


def finding(out, topic):
    return next((f for f in out["findings"] if f["topic"] == topic), None)


def haz(**blocks):
    return O.hazards(blocks)


def use(use_id, label, acres, fit="allowed", homes=None):
    u = {"id": use_id, "label": label, "acres": acres, "fit": fit}
    if homes is not None:
        u["homes"] = homes
    return u


def plan(*uses, signals=None):
    p = {"uses": list(uses)}
    if signals is not None:
        p["traffic"] = {"signals_to_study": signals}
    return p


def site(acres=100.0, *zonings):
    return {"acres": acres, "parcels": [{"zoning": z} for z in (zonings or ("R-1",))]}


def todo(site_=None, fc=None, plans="houses", hazard=None, place=None):
    plans = [plan(use("homes", "Houses", 100.0, homes=500))] if plans == "houses" else plans
    return O.steps(site_ or site(), fc or forecast(), plans, hazard, {} if place is None else place)


def whats(out):
    return [s["what"] for s in out["steps"]]


def strings(obj):
    """Every text in an answer (not the names of keys)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from strings(v)


def rich_hazards():
    """Every kind of finding the module can make, the "work" version of each."""
    return {"flood": {"zone": "AE", "meaning": "High hazard.", "special_hazard_area": True, "panel": "06065C2070H", "effective": "2014-08-18",
                      "zones_on_site": None},
            "fire": {"level": "High", "levels_on_site": ["Very High", "High", "Moderate"], "map_year": 2025},
            "fire_service": {"in_coverage_gap": True, "nearest_station": {"name": "Station 68", "miles_away": 1.59},
                             "planned_station": {"name": "Station 70", "miles_away": 1.35}},
            "faults": {"in_fault_zone": True}, "ground": {"liquefaction": "in a mapped zone", "landslide": "not in a zone"},
            "wetlands": {"on_site": [{"type": "Riverine", "acres": 1.2}], "nearest": None},
            "habitat": {"in_plan": True, "area_plan": "Sun City", "in_criteria_cell": True, "survey_areas": ["Burrowing Owl"]},
            "dam_flooding": True, "fossils": "High", "evacuation_zone": "MN-407", "did_not_answer": []}


def mild_hazards():
    return {"flood": {"zone": "X", "meaning": "Minimal flood hazard.", "panel": "P1", "effective": "2014-08-18"},
            "fire": {"level": "Moderate", "levels_on_site": ["Moderate"], "map_year": None},
            "faults": {"in_fault_zone": False, "nearest_miles": 3.1}, "ground": {"liquefaction": "not mapped by the state here", "landslide": "not mapped by the state here"},
            "wetlands": {"on_site": [], "nearest": {"type": "Pond", "acres": 2.5, "miles_away": 0.2}},
            "habitat": {"in_plan": True, "area_plan": None, "in_criteria_cell": False}, "fossils": "Moderate", "did_not_answer": ["Dams"]}


# ---------------------------------------------------------------- the economy

class TheEconomyWithEveryInputPresent(unittest.TestCase):
    def setUp(self):
        self.out = economy()

    def test_it_is_available_and_every_part_answered(self):
        self.assertTrue(self.out["available"])
        self.assertEqual(self.out["place"], "Testville")
        self.assertEqual(self.out["did_not_answer"], [])
        self.assertEqual([(s["name"], s["answered"]) for s in self.out["sources"]], [(p, True) for p in O.ECONOMY_PARTS])
        self.assertEqual(self.out["sources"][0]["source"], "Test state estimates")

    def test_the_six_sentences_of_the_record_say_exactly_this(self):
        self.assertEqual(self.out["facts"], [
            "Testville had 100,000 people in 2020 and 110,000 in 2025: 1.9% more each year. Homes went from 40,000 to 44,000.",
            "Builders took out permits for about 1,400 homes a year in Testville from 2021 to 2025; about 10% of them apartments and other attached homes.",
            "Shops and restaurants in Testville took in $660 million in 2025, up from $500 million in 2020. "
            "Prices rose 20% in that time, so the real gain is about 10%.",
            "That is about $15,700 of shop and restaurant sales for each household in 2025 "
            "(measured: everything sold in the city, to residents and visitors).",
            "Unemployment in Testville was 5.4% in 2025 (the county: 5.5%), with 51,936 residents working or looking for work.",
            "A 30-year home loan cost 6.57% on average so far in 2026 (7.21% in the latest week); the low of the last years was 2.96% in 2021. "
            "Dearer loans slow home sales, which is why building comes in waves."])

    def test_the_rows_put_each_year_side_by_side(self):
        rows = {r["year"]: r for r in self.out["rows"]}
        self.assertEqual(sorted(rows), [2020, 2021, 2022, 2023, 2024, 2025], "years come from people, permits, sales and work, oldest first")
        self.assertEqual(rows[2025], {"year": 2025, "people": 110000, "homes": 44000, "homes_permitted": 1800, "permit_months": 12,
                                      "shop_sales_usd": 660_000_000, "sales_quarters": 4, "sales_per_home_usd": 15700.0,
                                      "unemployment_pct": 5.4, "labour_force": 51936, "mortgage_pct": 6.2, "mortgage_weeks": 52, "prices_change_pct": 3.0})
        self.assertEqual(rows[2021]["people"], None, "a year the census-based table does not have is empty, not zero")
        self.assertIsNone(rows[2021]["unemployment_pct"])
        self.assertEqual(rows[2020]["mortgage_pct"], None, "the loan survey has no 2020 row here")
        self.assertEqual(rows[2020]["prices_change_pct"], None)

    def test_each_row_carries_how_many_weeks_the_loan_rate_averages(self):
        rows = {r["year"]: r for r in self.out["rows"]}
        self.assertEqual(rows[2025]["mortgage_weeks"], 52)
        self.assertIsNone(rows[2020]["mortgage_weeks"])
        parts = economy_parts()
        parts["borrowing"] = None
        self.assertEqual({r["mortgage_weeks"] for r in economy(parts)["rows"]}, {None})

    def test_sales_per_household_uses_the_occupied_homes_and_is_rounded_to_a_hundred(self):
        rows = {r["year"]: r for r in self.out["rows"]}
        self.assertEqual(rows[2020]["sales_per_home_usd"], round(500_000_000 / 38000, -2))
        self.assertEqual(self.out["measured_sales_per_home_usd"], 15700.0)

    def test_shop_sales_ahead_follow_the_homes_of_the_largest_ring_year_by_year(self):
        ahead = self.out["sales_ahead"]
        self.assertEqual([a["year"] for a in ahead], list(range(2027, 2037)))
        for a in ahead:
            for s in SCENARIOS:
                step = {"low": 50, "expected": 100, "high": 200}[s]
                homes_then = 10000 + step * (a["year"] - 2025)
                self.assertAlmostEqual(a["shop_sales_usd"][s], 660_000_000 * homes_then / 10000, delta=50_000, msg=(a["year"], s))
        self.assertEqual(ahead[0]["shop_sales_usd"], {"low": 666_600_000.0, "expected": 673_200_000.0, "high": 686_400_000.0})
        self.assertEqual(self.out["sales_ahead_basis"], "The city's last full year of shop and restaurant sales, grown with the homes the forecast "
                                                         "expects within 3 miles. Today's prices; no inflation added.")

    def test_it_can_be_sent_as_json(self):
        json.dumps(self.out, allow_nan=False)


class TheEconomyWithAnInputMissing(unittest.TestCase):
    def test_nothing_answered_is_not_available_and_has_no_numbers(self):
        for parts in ({}, {p: None for p in O.ECONOMY_PARTS}, {p: {} for p in O.ECONOMY_PARTS}):
            with self.subTest(parts=parts):
                out = economy(parts)
                self.assertEqual(out, {"available": False, "did_not_answer": list(O.ECONOMY_PARTS)})

    def test_each_part_left_out_is_named_and_the_rest_still_speaks(self):
        for gone in O.ECONOMY_PARTS:
            with self.subTest(gone=gone):
                parts = economy_parts()
                parts[gone] = None
                out = economy(parts)
                self.assertTrue(out["available"])
                self.assertEqual(out["did_not_answer"], [gone])
                self.assertEqual({s["name"]: s["answered"] for s in out["sources"]}[gone], False)
                self.assertIsNone({s["name"]: s["source"] for s in out["sources"]}[gone])
                json.dumps(out, allow_nan=False)

    def test_without_the_census_based_table_there_is_no_growth_sentence_and_no_sales_per_home(self):
        parts = economy_parts()
        parts["population"] = None
        out = economy(parts)
        self.assertFalse(any("people in" in f for f in out["facts"]))
        self.assertIsNone(out["measured_sales_per_home_usd"])
        self.assertEqual({r["sales_per_home_usd"] for r in out["rows"]}, {None})
        self.assertTrue(any("Shops and restaurants" in f for f in out["facts"]))
        self.assertFalse(any("each household" in f for f in out["facts"]))

    def test_without_sales_there_are_no_sales_sentences_and_no_sales_ahead(self):
        parts = economy_parts()
        parts["sales"] = None
        out = economy(parts)
        self.assertEqual(out["sales_ahead"], [])
        self.assertIsNone(out["sales_ahead_basis"])
        self.assertFalse(any("Shops" in f or "shop" in f for f in out["facts"]))
        self.assertEqual({r["shop_sales_usd"] for r in out["rows"]}, {None})

    def test_without_the_forecast_rings_the_record_is_the_same_and_there_is_nothing_ahead(self):
        for rings in ([], None):
            with self.subTest(rings=rings):
                out = economy(fc=forecast(rings=rings))
                self.assertEqual(out["sales_ahead"], [])
                self.assertIsNone(out["sales_ahead_basis"])
                self.assertEqual(out["facts"], economy()["facts"])

    def test_a_ring_with_no_rows_gives_nothing_ahead(self):
        out = economy(fc=forecast(rings=[{"miles": 3, "rows": []}]))
        self.assertEqual(out["sales_ahead"], [])

    def test_only_the_biggest_ring_is_used(self):
        small = {"miles": 1, "rows": [{"year": y, "homes": {s: 1000 for s in SCENARIOS}} for y in YEARS]}
        big = forecast()["rings"][0]
        out = economy(fc=forecast(rings=[small, big]))
        self.assertIn("within 3 miles", out["sales_ahead_basis"])
        self.assertEqual(out["sales_ahead"], economy()["sales_ahead"])


class TheEconomyWithPartialYears(unittest.TestCase):
    def test_a_year_with_eleven_permit_months_is_left_out_of_the_yearly_average_and_marked(self):
        parts = economy_parts()
        parts["permits"] = {"rows": [{"year": 2022, "homes": 1000, "multi_family": 100, "months_reported": 12},
                                     {"year": 2023, "homes": 2000, "multi_family": 200, "months_reported": 12},
                                     {"year": 2024, "homes": 100, "multi_family": 90, "months_reported": 11}]}
        out = economy(parts)
        fact = next(f for f in out["facts"] if f.startswith("Builders"))
        self.assertEqual(fact, "Builders took out permits for about 1,500 homes a year in Testville from 2022 to 2023; "
                               "about 10% of them apartments and other attached homes.")
        row = next(r for r in out["rows"] if r["year"] == 2024)
        self.assertEqual((row["homes_permitted"], row["permit_months"]), (100, 11), "the part year is shown, with how many months it holds")

    def test_when_every_permit_year_is_partial_there_is_no_yearly_sentence(self):
        parts = economy_parts()
        parts["permits"] = {"rows": [{"year": 2024, "homes": 500, "multi_family": 50, "months_reported": 11}]}
        out = economy(parts)
        self.assertFalse(any(f.startswith("Builders") for f in out["facts"]))
        self.assertEqual(next(r for r in out["rows"] if r["year"] == 2024)["permit_months"], 11)

    def test_only_the_last_five_whole_years_are_averaged(self):
        parts = economy_parts()
        parts["permits"] = {"rows": [{"year": 2015 + i, "homes": 100 * (i + 1), "multi_family": 0, "months_reported": 12} for i in range(8)]}
        fact = next(f for f in economy(parts)["facts"] if f.startswith("Builders"))
        self.assertIn("about 600 homes a year in Testville from 2018 to 2022", fact)     # (400+500+600+700+800) / 5 = 600
        self.assertIn("about 0% of them", fact)

    def test_without_the_apartment_count_the_sentence_has_no_share(self):
        parts = economy_parts()
        parts["permits"] = {"rows": [{"year": y, "homes": 1000, "months_reported": 12} for y in (2023, 2024)]}
        fact = next(f for f in economy(parts)["facts"] if f.startswith("Builders"))
        self.assertEqual(fact, "Builders took out permits for about 1,000 homes a year in Testville from 2023 to 2024.")

    def test_a_year_with_two_of_four_sales_quarters_is_never_compared_as_a_full_year_and_has_no_per_home_figure(self):
        parts = economy_parts()
        parts["sales"] = sales((2020, 500_000_000, 4), (2024, 630_000_000, 4), (2025, 300_000_000, 2))
        out = economy(parts)
        row = next(r for r in out["rows"] if r["year"] == 2025)
        self.assertEqual((row["shop_sales_usd"], row["sales_quarters"], row["sales_per_home_usd"]), (300_000_000, 2, None))
        text = " ".join(out["facts"])
        self.assertNotIn("in 2025, up from", text)
        self.assertNotIn("$300 million", text)
        compare = next(f for f in out["facts"] if f.startswith("Shops and restaurants"))
        self.assertTrue(compare.startswith("Shops and restaurants in Testville took in $630 million in 2024, up from $500 million in 2020"), compare)
        self.assertEqual(out["measured_sales_per_home_usd"], 13200.0, "the newest whole year that has homes to divide by is 2020, and the sentence says so")
        self.assertIn("for each household in 2020 ", " ".join(out["facts"]))

    def test_the_per_home_sentence_names_the_last_whole_year_when_the_newest_is_partial(self):
        parts = economy_parts()
        parts["sales"] = sales((2020, 500_000_000, 4), (2025, 300_000_000, 2))
        parts["population"]["rows"].append({"year": 2024, "people": 108000, "homes": 43000, "occupied_homes": 41000})
        parts["sales"]["rows"].insert(1, {"year": 2024, "sales_usd": 615_000_000, "quarters": 4})
        out = economy(parts)
        self.assertEqual(out["measured_sales_per_home_usd"], 15000.0)
        self.assertIn("That is about $15,000 of shop and restaurant sales for each household in 2024 ", " ".join(out["facts"]))

    def test_one_whole_sales_year_alone_is_not_a_comparison(self):
        parts = economy_parts()
        parts["sales"] = sales((2025, 660_000_000, 4))
        out = economy(parts)
        self.assertFalse(any(f.startswith("Shops and restaurants") for f in out["facts"]))
        self.assertFalse(any("each household" in f for f in out["facts"]))
        self.assertIsNone(out["measured_sales_per_home_usd"], "the per-home sentence needs the comparison first")
        self.assertEqual(next(r for r in out["rows"] if r["year"] == 2025)["sales_per_home_usd"], 15700.0, "but the row still has it")

    def test_a_year_of_zero_sales_is_not_compared(self):
        parts = economy_parts()
        parts["sales"] = sales((2020, 0, 4), (2025, 660_000_000, 4))
        out = economy(parts)
        self.assertFalse(any(f.startswith("Shops and restaurants") for f in out["facts"]))

    def test_no_price_index_means_no_real_gain_claim(self):
        parts = economy_parts()
        parts["prices"] = None
        fact = next(f for f in economy(parts)["facts"] if f.startswith("Shops and restaurants"))
        self.assertEqual(fact, "Shops and restaurants in Testville took in $660 million in 2025, up from $500 million in 2020.")
        self.assertNotIn("real gain", fact)

    def test_an_index_for_only_one_of_the_two_years_means_no_real_gain_claim(self):
        parts = economy_parts()
        parts["prices"] = {"rows": [{"year": 2025, "index": 120.0, "change_pct": 3.0}]}
        text = " ".join(economy(parts)["facts"])
        self.assertNotIn("real gain", text)
        self.assertNotIn("Prices rose", text)

    def test_when_prices_cover_some_years_the_comparison_uses_the_years_that_have_them(self):
        parts = economy_parts()
        parts["prices"] = {"rows": [{"year": 2022, "index": 100.0}, {"year": 2024, "index": 110.0}]}
        fact = next(f for f in economy(parts)["facts"] if f.startswith("Shops and restaurants"))
        self.assertEqual(fact, "Shops and restaurants in Testville took in $630 million in 2024, up from $580 million in 2022. "
                               "Prices rose 10% in that time, so the real gain is about -1%.")

    def test_the_newest_home_loan_year_partly_done_says_so_far(self):
        for weeks in (1, 20, 47, 49):
            with self.subTest(weeks=weeks):
                fact = next(f for f in economy(dict(economy_parts(), borrowing=borrowing(weeks)))["facts"] if f.startswith("A 30-year"))
                self.assertIn("on average so far in 2026", fact)

    def test_a_whole_newest_home_loan_year_does_not_say_so_far(self):
        for weeks in (50, 51, 52, None):
            with self.subTest(weeks=weeks):
                b = borrowing()
                b["rows"][-1]["weeks"] = weeks
                fact = next(f for f in economy(dict(economy_parts(), borrowing=b))["facts"] if f.startswith("A 30-year"))
                self.assertIn("on average in 2026", fact)
                self.assertNotIn("so far", fact)

    def test_the_loan_sentence_leaves_out_the_latest_week_when_there_is_none_and_keeps_the_low(self):
        b = borrowing()
        b["latest"] = None
        fact = next(f for f in economy(dict(economy_parts(), borrowing=b))["facts"] if f.startswith("A 30-year"))
        self.assertNotIn("latest week", fact)
        self.assertIn("the low of the last years was 2.96% in 2021", fact)

    def test_the_county_figure_and_the_labour_force_are_left_out_when_missing(self):
        w = work()
        w["county_rows"] = None
        w["rows"][-1]["labour_force"] = None
        fact = next(f for f in economy(dict(economy_parts(), work=w))["facts"] if f.startswith("Unemployment"))
        self.assertEqual(fact, "Unemployment in Testville was 5.4% in 2025.")

    def test_unemployment_is_only_said_when_the_newest_year_has_it(self):
        w = work()
        w["rows"][-1]["unemployment_pct"] = None
        self.assertFalse(any(f.startswith("Unemployment") for f in economy(dict(economy_parts(), work=w))["facts"]))

    def test_a_county_year_that_is_not_the_cities_newest_is_not_quoted(self):
        w = work()
        w["county_rows"] = [{"year": 2024, "unemployment_pct": 9.9}]
        fact = next(f for f in economy(dict(economy_parts(), work=w))["facts"] if f.startswith("Unemployment"))
        self.assertNotIn("county", fact)

    def test_zero_unemployment_is_a_figure_not_a_gap(self):
        w = work()
        w["rows"][-1]["unemployment_pct"] = 0
        fact = next(f for f in economy(dict(economy_parts(), work=w))["facts"] if f.startswith("Unemployment"))
        self.assertIn("was 0% in 2025", fact)

    def test_a_single_year_of_population_gives_no_growth_sentence(self):
        parts = economy_parts()
        parts["population"]["rows"] = parts["population"]["rows"][:1]
        out = economy(parts)
        self.assertFalse(any("more each year" in f for f in out["facts"]))
        self.assertEqual([r["year"] for r in out["rows"] if r["people"]], [2020])

    def test_population_with_no_people_figures_gives_no_growth_sentence(self):
        parts = economy_parts()
        parts["population"]["rows"] = [{"year": 2020, "people": None, "homes": 5}, {"year": 2025, "people": None, "homes": 6}]
        self.assertFalse(any("more each year" in f for f in economy(parts)["facts"]))

    def test_an_answer_with_no_rows_is_answered_but_says_nothing(self):
        for rows in ([], None):
            with self.subTest(rows=rows):
                out = economy({"population": {"rows": rows, "source": "S"}})
                self.assertTrue(out["available"])
                self.assertEqual((out["rows"], out["facts"], out["sales_ahead"]), ([], [], []))

    def test_a_year_seen_only_by_the_loan_survey_or_the_price_index_has_no_row(self):
        out = economy({"borrowing": borrowing(), "prices": prices()})
        self.assertEqual(out["rows"], [])

    def test_at_most_the_last_nine_years_are_listed(self):
        parts = {"sales": sales(*[(y, 100_000_000 + y, 4) for y in range(2005, 2026)])}
        out = economy(parts)
        self.assertEqual([r["year"] for r in out["rows"]], list(range(2017, 2026)))
        fact = next(f for f in out["facts"] if f.startswith("Shops and restaurants"))
        self.assertIn("up from $100 million in 2017", fact, "a year older than the table is not quoted")

    def test_the_year_of_the_forecast_does_not_have_to_be_2026(self):
        fc = forecast(year=2031)
        out = economy(fc=fc)
        self.assertEqual([a["year"] for a in out["sales_ahead"]], list(range(2032, 2042)))
        self.assertEqual(out["facts"], economy()["facts"])

    # a ring with no homes at the start year used to divide by zero (a 500 from the route) instead of leaving the line out
    def test_a_ring_with_no_homes_at_the_start_gives_nothing_ahead_and_does_not_raise(self):
        empty = [{"miles": 3, "rows": [{"year": y, "homes": {s: 0 for s in SCENARIOS}} for y in YEARS]}]
        out = economy(fc=forecast(rings=empty))
        self.assertEqual(out["sales_ahead"], [])
        self.assertIn("no homes", out["sales_ahead_note"])

    # the newest whole sales year is not among the ring's rows: the sales are carried forward from the first year the ring counts,
    # and the basis says so (growth in between is missing, so the figures may run low)
    def test_sales_of_a_year_the_ring_has_no_homes_for_are_carried_forward_with_the_gap_said(self):
        parts = economy_parts()
        parts["sales"] = sales((2023, 600_000_000, 4), (2024, 630_000_000, 4))
        out = economy(parts)
        self.assertTrue(out["sales_ahead"])
        self.assertIn("from 2026, not from 2024", out["sales_ahead_basis"])
        self.assertIn("may run low", out["sales_ahead_basis"])
        self.assertNotIn("not from", economy()["sales_ahead_basis"], "no gap when the ring has the sales year")
        self.assertIsNone(economy()["sales_ahead_note"])

    def test_a_ring_with_no_rows_at_all_gives_no_sales_ahead(self):
        out = economy(fc=forecast(rings=[{"miles": 3, "rows": []}]))
        self.assertEqual(out["sales_ahead"], [])

    # a city that lost people used to read "-12.9% more each year"
    def test_a_city_that_lost_people_does_not_gain_a_negative_percent(self):
        parts = economy_parts()
        parts["population"]["rows"] = [{"year": 2020, "people": 200, "homes": 50}, {"year": 2025, "people": 100, "homes": 40}]
        fact = next(f for f in economy(parts)["facts"] if "people in" in f)
        self.assertNotIn("-12.9% more", fact)
        self.assertEqual(fact, "Testville had 200 people in 2020 and 100 in 2025: 12.9% fewer each year. Homes went from 50 to 40.")

    def test_a_city_with_the_same_people_says_about_the_same(self):
        parts = economy_parts()
        parts["population"]["rows"] = [{"year": 2020, "people": 100, "homes": 40}, {"year": 2025, "people": 100, "homes": 40}]
        fact = next(f for f in economy(parts)["facts"] if "people in" in f)
        self.assertIn("about the same from one year to the next", fact)

    # a year with months_reported 0 used to count as a whole year of zero homes ("0 or 12")
    def test_a_permit_year_with_no_months_reported_is_not_a_whole_year(self):
        parts = economy_parts()
        parts["permits"] = {"rows": [{"year": 2023, "homes": 1000, "multi_family": 0, "months_reported": 12},
                                     {"year": 2024, "homes": 0, "multi_family": 0, "months_reported": 0}]}
        fact = next(f for f in economy(parts)["facts"] if f.startswith("Builders"))
        self.assertIn("about 1,000 homes a year in Testville from 2023 to 2023", fact)


# ---------------------------------------------------------------- the weather

class TheClimate(unittest.TestCase):
    def test_every_input_present_says_exactly_this(self):
        out = O.climate(climate_part(), YEAR)
        self.assertTrue(out["available"])
        self.assertEqual(out["facts"], [
            "A typical year averages 61 degrees F with about 11.8 inches of rain; the hottest month is July, with afternoons around 104 degrees.",
            "The yearly average has moved +0.4 degrees F each ten years since 1985. If that simply continues, 2036 is about +0.4 degrees from today: "
            "more cooling load, more shade and water-wise planting to plan for.",
            "Rain has moved -0.3 inches each ten years; it swings far more from year to year than that trend, so drainage is sized for the wet years, "
            "not the average."])
        self.assertEqual(out["ahead"], {"year": 2036, "mean_f_change": 0.4,
                                        "basis": "The straight-line trend of the yearly averages from 1985 to 2025, carried on."})
        self.assertEqual(out["typical_year"]["mean_f"], 61.4, "the measured figures are passed on as they came")

    def test_the_part_is_not_changed(self):
        part = climate_part()
        before = copy.deepcopy(part)
        O.climate(part, YEAR)
        self.assertEqual(part, before)

    def test_no_answer_is_not_available_and_has_no_numbers(self):
        for part in (None, {}):
            with self.subTest(part=part):
                self.assertEqual(O.climate(part, YEAR), {"available": False})

    def test_the_look_ahead_follows_the_year_it_is_given(self):
        for year in (2026, 2031, 2040):
            with self.subTest(year=year):
                out = O.climate(climate_part(), year)
                self.assertEqual(out["ahead"]["year"], year + 10)
                self.assertIn(f"{year + 10} is about", out["facts"][1])

    def test_the_change_ahead_is_the_trend_times_the_horizon(self):
        part = climate_part()
        part["trend"]["mean_f_per_decade"] = -0.25
        out = O.climate(part, YEAR)
        self.assertEqual(out["ahead"]["mean_f_change"], -0.2)             # round(-0.25, 1)
        self.assertIn("moved -0.2 degrees F each ten years", out["facts"][1])

    def test_without_a_trend_there_is_no_look_ahead(self):
        part = climate_part()
        part["trend"] = None
        out = O.climate(part, YEAR)
        self.assertNotIn("ahead", out)
        self.assertEqual(len(out["facts"]), 1)

    def test_without_the_typical_year_only_the_trend_speaks(self):
        part = climate_part()
        part["typical_year"] = None
        out = O.climate(part, YEAR)
        self.assertEqual([f[:22] for f in out["facts"]], ["The yearly average has"])

    def test_a_trend_with_no_rain_figure_says_nothing_about_rain(self):
        part = climate_part()
        part["trend"]["rain_in_per_decade"] = None
        self.assertFalse(any("Rain has moved" in f for f in O.climate(part, YEAR)["facts"]))

    def test_the_hottest_month_is_the_one_with_the_highest_afternoon(self):
        part = climate_part()
        part["months"].append({"month": "Sep", "mean_f": 70, "high_f": 110.0})
        self.assertIn("the hottest month is September, with afternoons around 110 degrees", O.climate(part, YEAR)["facts"][0])

    def test_months_with_no_highs_do_not_name_a_hottest_month(self):
        part = climate_part()
        part["months"] = [{"month": "Jan", "high_f": None}, {"month": "Feb"}]
        self.assertEqual(O.climate(part, YEAR)["facts"][0], "A typical year averages 61 degrees F with about 11.8 inches of rain.")
        part["months"] = []
        self.assertEqual(O.climate(part, YEAR)["facts"][0], "A typical year averages 61 degrees F with about 11.8 inches of rain.")

    def test_a_trend_of_zero_is_a_figure(self):
        part = climate_part()
        part["trend"]["mean_f_per_decade"] = 0.0
        out = O.climate(part, YEAR)
        self.assertEqual(out["ahead"]["mean_f_change"], 0.0)
        self.assertIn("+0.0 degrees F each ten years", out["facts"][1])

    def test_it_can_be_sent_as_json(self):
        json.dumps(O.climate(climate_part(), YEAR), allow_nan=False)

    # "about 0.0 inches of rain" was said when the answer had no rain figure: a number that was never read
    def test_a_typical_year_without_a_rain_figure_does_not_say_zero_inches(self):
        part = {"typical_year": {"mean_f": 61.4}}
        self.assertNotIn("0.0 inches", O.climate(part, YEAR)["facts"][0])
        self.assertNotIn("rain", O.climate(part, YEAR)["facts"][0])


# ---------------------------------------------------------------- hazards

class TheHazards(unittest.TestCase):
    def test_nothing_answered_is_not_available_and_has_no_findings(self):
        for part in (None, {}):
            with self.subTest(part=part):
                self.assertEqual(O.hazards(part), {"available": False})

    def test_every_block_set_to_none_is_available_with_no_findings_and_keeps_what_did_not_answer(self):
        out = haz(flood=None, fire=None, fire_service=None, faults=None, ground=None, wetlands=None, habitat=None, dam_flooding=None,
                  fossils=None, did_not_answer=["Flood map", "Fire map"])
        self.assertTrue(out["available"])
        self.assertEqual((out["findings"], out["work"]), ([], 0))
        self.assertEqual(out["did_not_answer"], ["Flood map", "Fire map"])
        self.assertIsNone(out["evacuation_zone"])

    def test_the_answer_has_what_the_page_needs(self):
        out = O.hazards(rich_hazards())
        self.assertEqual(out["evacuation_zone"], "MN-407")
        self.assertEqual(out["work"], 6)
        self.assertEqual(out["did_not_answer"], [])
        self.assertTrue(all({"topic", "level", "text", "source"} <= set(f) for f in out["findings"]))
        self.assertEqual({f["level"] for f in out["findings"]}, {"work", "note"})
        self.assertEqual([f["topic"] for f in out["findings"]], ["Flood", "Wildfire", "Fire service", "Earthquake faults", "Soft ground and slides",
                                                                  "Streams and wetlands", "Protected habitat", "Dam failure flooding", "Fossils"])
        self.assertEqual(len(out["not_covered"]), 2)
        json.dumps(out, allow_nan=False)

    def test_the_work_count_counts_only_the_findings_that_add_a_study(self):
        out = O.hazards(mild_hazards())
        self.assertEqual(out["work"], 0)
        self.assertEqual(out["did_not_answer"], ["Dams"])

    # ---- flood

    def test_flood_zone_x_is_clear_and_says_the_map_panel(self):
        f = finding(haz(flood={"zone": "X", "meaning": "Minimal flood hazard: outside the 500-year flood.", "panel": "06065C2070H",
                               "effective": "2014-08-18"}), "Flood")
        self.assertEqual(f["level"], "clear")
        self.assertEqual(f["text"], "FEMA flood zone X, minimal flood hazard: outside the 500-year flood. Map panel 06065C2070H, in force since 2014-08-18.")
        self.assertEqual(f["source"], "FEMA National Flood Hazard Layer")

    def test_flood_zone_x_without_a_meaning_or_a_panel_says_the_plain_thing(self):
        f = finding(haz(flood={"zone": "X"}), "Flood")
        self.assertEqual((f["level"], f["text"]), ("clear", "FEMA flood zone X, outside the mapped flood areas."))

    def test_a_panel_without_its_date_is_left_out(self):
        self.assertNotIn("Map panel", finding(haz(flood={"zone": "X", "panel": "P1"}), "Flood")["text"])

    def test_the_wet_zones_are_work_with_the_same_sentence(self):
        for zone in ("A", "AE", "AH", "AO", "AR", "A99", "V", "VE", "ae"):
            with self.subTest(zone=zone):
                f = finding(haz(flood={"zone": zone, "meaning": "x"}), "Flood")
                self.assertEqual(f["level"], "work")
                self.assertEqual(f["text"], f"Part of the site is in FEMA flood zone {zone}: building there needs a flood study and raised pads.")

    def test_a_special_hazard_area_is_work_even_in_zone_x(self):
        f = finding(haz(flood={"zone": "X", "special_hazard_area": True}), "Flood")
        self.assertEqual(f["level"], "work")

    def test_a_wet_zone_anywhere_on_the_site_is_work_even_when_the_middle_is_zone_x(self):
        f = finding(haz(flood={"zone": "X", "zones_on_site": ["AE"]}), "Flood")
        self.assertEqual(f["level"], "work")
        self.assertIn("AE", f["text"])

    def test_zones_that_are_not_wet_are_clear(self):
        for zone in ("X", "B", "C", "D"):
            with self.subTest(zone=zone):
                self.assertEqual(finding(haz(flood={"zone": zone}), "Flood")["level"], "clear")

    def test_a_flood_answer_with_only_a_dry_zone_list_is_clear(self):
        self.assertEqual(finding(haz(flood={"zone": "X", "zones_on_site": ["X (minimal hazard)"]}), "Flood")["level"], "clear")

    # "zone starts with A or V" used to mean wet; FEMA's "AREA NOT INCLUDED" (a place the map leaves out) starts with an A
    def test_a_zone_called_area_not_included_is_not_taken_for_a_flood_zone(self):
        f = finding(haz(flood={"zone": "AREA NOT INCLUDED", "special_hazard_area": False}), "Flood")
        self.assertNotEqual(f["level"], "work")
        self.assertEqual(f["level"], "note", "a place the map leaves out is not known to be safe")

    # real inputs: the point's zone is "AE" and the site's zones come labelled ("AE (high hazard)", "X (minimal hazard)"); the sentence
    # used to say "AE, AE (high hazard), X (minimal hazard)": the same zone twice and a dry zone named as a flood zone
    def test_the_wet_sentence_names_each_zone_once_and_only_the_wet_ones(self):
        f = finding(haz(flood={"zone": "AE", "special_hazard_area": True, "zones_on_site": ["AE (high hazard)", "X (minimal hazard)"]}), "Flood")
        self.assertEqual(f["text"].count("AE"), 1, f["text"])
        self.assertNotIn("minimal", f["text"])
        self.assertEqual(f["text"], "Part of the site is in FEMA flood zone AE: building there needs a flood study and raised pads.")

    def test_two_wet_zones_are_each_named_once_and_the_dry_one_is_left_out(self):
        f = finding(haz(flood={"zone": "X", "special_hazard_area": True,
                               "zones_on_site": ["AE (high hazard)", "VE (coastal high hazard)", "X (minimal hazard)", "AE (high hazard)"]}), "Flood")
        self.assertEqual(f["text"], "Part of the site is in FEMA flood zones AE and VE: building there needs a flood study and raised pads.")

    def test_a_special_hazard_area_with_no_zone_named_says_so_without_naming_one(self):
        f = finding(haz(flood={"zone": None, "special_hazard_area": True}), "Flood")
        self.assertEqual((f["level"], f["text"]), ("work", "Part of the site is in a FEMA special flood hazard area: building there needs a flood study and raised pads."))

    # real input when FEMA has no map for the spot: zone None and meaning "FEMA has not published a flood map for this spot."
    # The sentence used to be "FEMA flood zone None: fema has not published a flood map for this spot." (and was called "clear")
    def test_no_flood_map_does_not_print_none_or_lowercase_fema(self):
        f = finding(haz(flood={"zone": None, "meaning": "FEMA has not published a flood map for this spot.", "special_hazard_area": False}), "Flood")
        self.assertNotIn("None", f["text"])
        self.assertIn("FEMA has not published", f["text"])
        self.assertEqual(f["text"], "FEMA has not published a flood map for this spot.")

    # "no map" is not "clear": the level is the same as for a mapped, dry site
    def test_no_flood_map_is_not_called_clear(self):
        f = finding(haz(flood={"zone": None, "meaning": "FEMA has not published a flood map for this spot.", "special_hazard_area": False}), "Flood")
        self.assertNotEqual(f["level"], "clear")

    # ---- fire

    def test_fire_high_and_very_high_are_work_moderate_is_a_note_and_none_is_clear(self):
        for level, want in (("Very High", "work"), ("High", "work"), ("Moderate", "note")):
            with self.subTest(level=level):
                self.assertEqual(finding(haz(fire={"level": level}), "Wildfire")["level"], want)
        for none in ({"level": None}, {"level": "not in a mapped fire hazard zone"}, {"level": "Non-wildland", "levels_on_site": ["Non-wildland"]}):
            with self.subTest(none=none):
                f = finding(haz(fire=none), "Wildfire")
                self.assertEqual((f["level"], f["text"]), ("clear", "The site is outside the mapped fire hazard zones."))

    def test_fire_sentence_with_one_level_for_the_middle_and_the_bounds(self):
        f = finding(haz(fire={"level": "High", "levels_on_site": ["High"], "map_year": 2025}), "Wildfire")
        self.assertEqual(f["text"], "The 2025 fire hazard map puts the middle of the site in a High zone. That brings fire-resistant building rules, "
                                    "cleared space around buildings and a close look at ways out.")
        self.assertEqual(f["source"], "City fire hazard severity map")

    def test_fire_sentence_when_the_middle_and_the_bounds_differ(self):
        f = finding(haz(fire={"level": "High", "levels_on_site": ["Very High", "High", "Moderate"], "map_year": 2025}), "Wildfire")
        self.assertEqual(f["level"], "work")
        self.assertEqual(f["text"], "The 2025 fire hazard map puts the middle of the site in a High zone; land within its bounds is also mapped "
                                    "Very High and Moderate. That brings fire-resistant building rules, cleared space around buildings and a close look at ways out.")

    def test_the_worst_level_on_the_site_sets_the_level_even_when_the_middle_is_milder(self):
        f = finding(haz(fire={"level": "Moderate", "levels_on_site": ["Moderate", "High"]}), "Wildfire")
        self.assertEqual(f["level"], "work")
        self.assertIn("middle of the site in a Moderate zone; land within its bounds is also mapped High.", f["text"])
        self.assertTrue(f["text"].startswith("The current fire hazard map"), "no map year: it says current")

    def test_when_only_the_bounds_are_mapped_the_sentence_says_so(self):
        f = finding(haz(fire={"level": "not in a mapped fire hazard zone", "levels_on_site": ["High"]}), "Wildfire")
        self.assertEqual(f["level"], "work")
        self.assertIn("puts land within the site's bounds in a High zone.", f["text"])
        self.assertNotIn("middle", f["text"])

    def test_an_empty_fire_block_gives_no_finding(self):
        self.assertIsNone(finding(haz(fire={}), "Wildfire"))

    # ---- fire stations

    def test_a_coverage_gap_with_a_nearest_and_a_planned_station(self):
        f = finding(haz(fire_service={"in_coverage_gap": True, "nearest_station": {"name": "Station 68", "miles_away": 1.59},
                                      "planned_station": {"name": "Station 70", "miles_away": 1.35}}), "Fire service")
        self.assertEqual(f["level"], "note")
        self.assertEqual(f["text"], "The site is in an area the city maps as a gap in fire station coverage; the nearest station is Station 68, "
                                    "1.59 miles away. A new station is planned 1.35 miles away (Station 70).")

    def test_a_coverage_gap_without_a_planned_station(self):
        f = finding(haz(fire_service={"in_coverage_gap": True, "nearest_station": {"name": "Station 68", "miles_away": 2}, "planned_station": None}),
                    "Fire service")
        self.assertEqual(f["text"], "The site is in an area the city maps as a gap in fire station coverage; the nearest station is Station 68, 2 miles away.")

    def test_a_coverage_gap_with_only_a_planned_station(self):
        f = finding(haz(fire_service={"in_coverage_gap": True, "planned_station": {"name": "Station 70", "miles_away": 1.35}}), "Fire service")
        self.assertEqual(f["text"], "The site is in an area the city maps as a gap in fire station coverage. A new station is planned 1.35 miles away (Station 70).")

    def test_a_coverage_gap_with_no_station_named(self):
        f = finding(haz(fire_service={"in_coverage_gap": True}), "Fire service")
        self.assertEqual(f["text"], "The site is in an area the city maps as a gap in fire station coverage.")

    def test_no_gap_is_no_finding(self):
        self.assertIsNone(finding(haz(fire_service={"in_coverage_gap": False, "nearest_station": {"name": "S", "miles_away": 1}}), "Fire service"))

    # ---- faults, ground

    def test_faults(self):
        inside = finding(haz(faults={"in_fault_zone": True}), "Earthquake faults")
        self.assertEqual((inside["level"], inside["text"]), ("work", "The site is inside a state earthquake fault zone: a fault study is required before building."))
        near = finding(haz(faults={"in_fault_zone": False, "nearest_miles": 3.1}), "Earthquake faults")
        self.assertEqual((near["level"], near["text"]), ("clear", "No mapped fault zone on the site; the nearest mapped fault is 3.1 miles away."))
        none = finding(haz(faults={"in_fault_zone": False, "nearest_miles": None, "searched_miles": 5}), "Earthquake faults")
        self.assertEqual((none["level"], none["text"]), ("clear", "No mapped fault or fault zone within 5 miles."))
        self.assertEqual(finding(haz(faults={"in_fault_zone": False}), "Earthquake faults")["text"], "No mapped fault or fault zone within 3 miles.")

    def test_ground_in_a_mapped_zone_is_work_when_either_hazard_is_mapped(self):
        for liq, slide in (("in a mapped zone", "not in a zone"), ("not in a zone", "in a mapped zone"), ("in a mapped zone", "in a mapped zone")):
            with self.subTest(liq=liq, slide=slide):
                f = finding(haz(ground={"liquefaction": liq, "landslide": slide}), "Soft ground and slides")
                self.assertEqual(f["level"], "work")
                self.assertEqual(f["text"], "The site is in a zone the state maps for soft ground in an earthquake or for landslides: the soils report must answer it.")

    def test_ground_the_state_has_not_mapped_is_a_note_and_ground_outside_the_zones_is_clear(self):
        unmapped = finding(haz(ground={"liquefaction": "not mapped by the state here", "landslide": "not mapped by the state here"}), "Soft ground and slides")
        self.assertEqual((unmapped["level"], unmapped["text"]),
                         ("note", "The state has not mapped this area for soft ground in an earthquake. A soils report settles it; "
                                  "one is needed for the subdivision map in any case."))
        clear = finding(haz(ground={"liquefaction": "not in a zone", "landslide": "not in a zone"}), "Soft ground and slides")
        self.assertEqual((clear["level"], clear["text"]), ("clear", "Outside the state's mapped zones for soft ground and landslides."))

    # ---- wetlands

    def test_wetlands_on_the_site(self):
        f = finding(haz(wetlands={"on_site": [{"type": "Riverine", "acres": 1.2}], "nearest": {"type": "Pond", "acres": 1, "miles_away": 0.1}}),
                    "Streams and wetlands")
        self.assertEqual(f["level"], "work")
        self.assertEqual(f["text"], "The national wetlands map shows 1 mapped water feature on the site or at its edge (riverine). A biologist maps it on the "
                                    "ground, and building in it needs state and federal permits.")

    def test_several_wetlands_are_counted_and_their_kinds_listed_once_each(self):
        on = [{"type": "Riverine", "acres": 1.2}, {"type": "riverine", "acres": 0.4}, {"type": "Pond", "acres": 2.0}]
        f = finding(haz(wetlands={"on_site": on}), "Streams and wetlands")
        self.assertIn("shows 3 mapped water features on the site or at its edge (pond, riverine).", f["text"])

    def test_wetlands_only_near(self):
        f = finding(haz(wetlands={"on_site": [], "nearest": {"type": "Pond", "acres": 2.5, "miles_away": 0.2}}), "Streams and wetlands")
        self.assertEqual((f["level"], f["text"]), ("note", "None mapped on the site. The nearest is a pond feature of 2.5 acres, 0.2 miles away."))

    def test_no_wetlands_at_all(self):
        f = finding(haz(wetlands={"on_site": [], "nearest": None, "searched_miles": 0.3}), "Streams and wetlands")
        self.assertEqual((f["level"], f["text"]), ("clear", "None mapped on the site or within 0.3 miles."))
        self.assertEqual(finding(haz(wetlands={"on_site": None, "nearest": None}), "Streams and wetlands")["level"], "clear")

    # ---- habitat

    def test_habitat_in_a_criteria_cell_is_work(self):
        f = finding(haz(habitat={"in_plan": True, "area_plan": "Sun City / Menifee", "in_criteria_cell": True, "survey_areas": []}), "Protected habitat")
        self.assertEqual(f["level"], "work")
        self.assertEqual(f["text"].rstrip(), "The site is inside the Western Riverside County habitat plan (Sun City / Menifee). It lies in a cell the plan marks "
                                             "for possible conservation: the project is reviewed with the conservation authority.")

    def test_habitat_outside_a_cell_with_survey_areas_is_still_work_and_lists_the_surveys(self):
        f = finding(haz(habitat={"in_plan": True, "area_plan": "Sun City", "in_criteria_cell": False,
                                 "survey_areas": ["Burrowing Owl", "Narrow Endemic Plants"]}), "Protected habitat")
        self.assertEqual(f["level"], "work")
        self.assertEqual(f["text"], "The site is inside the Western Riverside County habitat plan (Sun City). It is not in a cell marked for conservation. "
                                    "Surveys asked for here: burrowing owl, narrow endemic plants. They are done in season, before any grading.")

    def test_habitat_in_the_plan_with_no_cell_and_no_surveys_is_a_note(self):
        f = finding(haz(habitat={"in_plan": True, "area_plan": None, "in_criteria_cell": False, "survey_areas": None}), "Protected habitat")
        self.assertEqual(f["level"], "note")
        self.assertIn("(area plan not named)", f["text"])
        self.assertIn("It is not in a cell marked for conservation.", f["text"])

    def test_habitat_outside_the_plan_is_no_finding(self):
        self.assertIsNone(finding(haz(habitat={"in_plan": False, "in_criteria_cell": True, "survey_areas": ["x"]}), "Protected habitat"))

    # a sentence used to end in a space when there were no survey areas: "...conservation. "
    def test_habitat_sentences_have_no_trailing_space(self):
        for habitat in ({"in_plan": True, "in_criteria_cell": True}, {"in_plan": True, "in_criteria_cell": False}):
            with self.subTest(habitat=habitat):
                text = finding(haz(habitat=habitat), "Protected habitat")["text"]
                self.assertEqual(text, text.strip())

    # ---- dams, fossils

    def test_dam_failure_flooding_is_a_note(self):
        f = finding(haz(dam_flooding=True), "Dam failure flooding")
        self.assertEqual((f["level"], f["text"]), ("note", "The city maps the site inside the area a dam failure would flood."))
        self.assertIsNone(finding(haz(dam_flooding=False), "Dam failure flooding"))

    def test_fossils_low_or_none_is_no_finding_and_anything_higher_is_a_note(self):
        for rating in ("Low", "low", "None", "none", "", None):
            with self.subTest(rating=rating):
                self.assertIsNone(finding(haz(fossils=rating), "Fossils"))
        for rating in ("High", "Moderate"):
            with self.subTest(rating=rating):
                f = finding(haz(fossils=rating), "Fossils")
                self.assertEqual(f["level"], "note")
                self.assertEqual(f["text"], f"The city rates the chance of fossils in the ground here as {rating.lower()}: a monitor may be asked for during grading.")


    def test_a_rating_the_city_gives_as_a_code_is_put_in_words_and_never_shown_bare(self):
        for code, said in (("Hb", "high (class B)"), ("Ha", "high (class A)"), ("U", "undetermined")):
            with self.subTest(code=code):
                f = finding(haz(fossils=code), "Fossils")
                self.assertEqual(f["text"], f"The city rates the chance of fossils in the ground here as {said}: a monitor may be asked for during grading.")
        self.assertIsNone(finding(haz(fossils="L"), "Fossils"), "a saved answer that still holds the code L is low")

    def test_a_code_the_city_does_not_explain_is_reported_as_unexplained(self):
        f = finding(haz(fossils="sea"), "Fossils")
        self.assertEqual(f["level"], "note")
        self.assertIn("code sea", f["text"])
        self.assertIn("does not say in words", f["text"])
        self.assertNotIn("rates the chance of fossils in the ground here as sea", f["text"])


# ---------------------------------------------------------------- the typical resident

class TheResident(unittest.TestCase):
    def test_every_input_present_says_exactly_this(self):
        out = O.resident(resident_part())
        self.assertTrue(out["available"])
        self.assertEqual(out["facts"], [
            "The typical resident nearby is about 36 years old and lives in a household of 3.4. 29% of workers travel an hour or more to work, and 75% drive alone.",
            "28% are under 18 and 12% are 65 or older; 29% of adults have a college degree; 15% work from home.",
            "The typical home is valued at $556,728, up from $244,032 in the 2010-2014 survey (about 9.6% a year); "
            "typical rent is $2,212 a month, up from $1,484."])
        self.assertEqual(out["home_value_rise_pct_a_year"], 9.6)
        self.assertEqual(out["earlier"]["tracts_matched"], 14, "what the source said is passed on")

    def test_no_answer_or_no_typical_resident_is_not_available_and_has_no_numbers(self):
        for part in (None, {}, {"typical": None}, {"typical": {}}, {"typical": {}, "earlier": {"home_value_usd": 1}}):
            with self.subTest(part=part):
                self.assertEqual(O.resident(part), {"available": False})

    def test_without_the_earlier_survey_there_is_no_home_value_sentence(self):
        for earlier in (None, {}, {"home_value_usd": None, "rent_usd": 1000}, {"home_value_usd": 0}):
            with self.subTest(earlier=earlier):
                part = resident_part()
                part["earlier"] = earlier
                out = O.resident(part)
                self.assertEqual(len(out["facts"]), 2)
                self.assertNotIn("home_value_rise_pct_a_year", out)

    def test_without_the_current_home_value_there_is_no_home_value_sentence(self):
        part = resident_part()
        part["typical"]["home_value_usd"] = None
        self.assertEqual(len(O.resident(part)["facts"]), 2)

    def test_without_rent_the_sentence_stops_at_the_home_value(self):
        for typical_rent, earlier_rent in ((None, 1484), (2212, None), (None, None)):
            with self.subTest(typical_rent=typical_rent, earlier_rent=earlier_rent):
                part = resident_part()
                part["typical"]["rent_usd"], part["earlier"]["rent_usd"] = typical_rent, earlier_rent
                self.assertEqual(O.resident(part)["facts"][2], "The typical home is valued at $556,728, up from $244,032 in the 2010-2014 survey (about 9.6% a year).")

    def test_the_earlier_survey_without_its_years_is_called_the_earlier_survey(self):
        part = resident_part()
        part["earlier"]["years"] = None
        self.assertIn("in the earlier survey (about 9.6% a year)", O.resident(part)["facts"][2])

    def test_the_commute_sentence_without_the_drive_alone_share(self):
        part = resident_part()
        part["typical"]["drive_alone_pct"] = None
        self.assertIn("29% of workers travel an hour or more to work.", O.resident(part)["facts"][0])
        part["typical"]["long_commute_pct"] = None
        self.assertEqual(O.resident(part)["facts"][0], "The typical resident nearby is about 36 years old and lives in a household of 3.4.")

    def test_age_alone_or_household_alone(self):
        self.assertEqual(O.resident({"typical": {"median_age": 30}})["facts"], ["The typical resident nearby is about 30 years old."])
        self.assertEqual(O.resident({"typical": {"household_size": 2.0}})["facts"], ["The typical resident nearby lives in a household of 2.0."])

    def test_the_young_and_old_sentence_needs_both_shares(self):
        part = resident_part()
        part["typical"]["over_65_pct"] = None
        self.assertEqual(len(O.resident(part)["facts"]), 2)
        self.assertFalse(any("under 18" in f for f in O.resident(part)["facts"]))

    def test_degree_and_work_from_home_are_optional_endings(self):
        part = resident_part()
        part["typical"]["bachelors_pct"] = None
        self.assertEqual(O.resident(part)["facts"][1], "28% are under 18 and 12% are 65 or older; 15% work from home.")
        part["typical"]["work_from_home_pct"] = None
        self.assertEqual(O.resident(part)["facts"][1], "28% are under 18 and 12% are 65 or older.")

    def test_a_rising_value_rate_is_the_nine_year_yearly_rate(self):
        part = resident_part()
        part["earlier"]["home_value_usd"] = 100000
        part["typical"]["home_value_usd"] = 100000 * 1.05 ** 9
        self.assertEqual(O.resident(part)["home_value_rise_pct_a_year"], 5.0)

    def test_it_can_be_sent_as_json(self):
        json.dumps(O.resident(resident_part()), allow_nan=False)

    # a home worth less than before used to read "up from ... (about -1.2% a year)"
    def test_a_home_value_that_fell_does_not_say_up(self):
        part = {"typical": {"home_value_usd": 90000}, "earlier": {"home_value_usd": 100000, "years": "2010-2014"}}
        self.assertNotIn("up from", O.resident(part)["facts"][0])
        self.assertEqual(O.resident(part)["facts"][0],
                         "The typical home is valued at $90,000, down from $100,000 in the 2010-2014 survey (about 1.2% less each year).")

    # the same for rent
    def test_a_rent_that_fell_does_not_say_up(self):
        part = {"typical": {"home_value_usd": 150000, "rent_usd": 900}, "earlier": {"home_value_usd": 100000, "rent_usd": 1000, "years": "2010-2014"}}
        self.assertNotIn("a month, up from", O.resident(part)["facts"][0])
        self.assertIn("typical rent is $900 a month, down from $1,000.", O.resident(part)["facts"][0])


# ---------------------------------------------------------------- the checklist

class TheStepsAlwaysPresent(unittest.TestCase):
    def test_a_house_site_of_a_hundred_acres_gets_exactly_these_steps(self):
        out = todo()
        self.assertEqual([(s["from_year"], s["to_year"], s["kind"], s["what"]) for s in out["steps"]], [
            (2027, 2027, "city", "Meet the city's planners before applying"),
            (2027, 2028, "city", "File the map that divides the land into the pieces to be sold"),
            (2027, 2028, "study", "Environmental review under state law (the city leads it)"),
            (2027, 2028, "study", "Soils and geology report"),
            (2027, 2028, "check", "Ask for letters saying water, sewer and power can serve the site"),
            (2027, 2028, "check", "Check school room and fees with the school district")])
        self.assertTrue(out["note"].startswith("A starting checklist drawn from the facts on this page by simple rules."))

    def test_each_step_has_the_five_fields_and_a_reason_that_names_a_fact(self):
        for s in todo(site(74.34), forecast(trips=11240), place={"planning": "Planning Dept", "water": "Water District"})["steps"]:
            with self.subTest(s["what"]):
                self.assertEqual(set(s), {"from_year", "to_year", "kind", "what", "why", "who"})
                self.assertTrue(s["why"] and s["who"] and s["what"])
                self.assertLessEqual(s["from_year"], s["to_year"])

    def test_the_first_step_names_the_acres_and_the_planning_department(self):
        s = todo(site(74.34), place={"planning": "City Planning"})["steps"][0]
        self.assertEqual(s["why"], "To hear early what the city will ask for on these 74.34 acres.")
        self.assertEqual(s["who"], "City Planning")

    def test_with_no_place_the_planning_department_is_the_cities(self):
        self.assertEqual(todo(place={})["steps"][0]["who"], "the city's planning department")

    def test_water_and_the_school_step_name_who_to_ask(self):
        steps = {s["what"]: s for s in todo(place={"planning": "P", "water": "W"})["steps"]}
        self.assertEqual(steps["Ask for letters saying water, sewer and power can serve the site"]["who"], "W")
        self.assertEqual(todo(place={})["steps"][4]["who"], "The water and sewer district, and the power company")

    def test_the_environmental_review_step_says_the_acres_and_the_trips_only_when_there_are_trips(self):
        with_trips = next(s for s in todo(site(74.34), forecast(trips=11240))["steps"] if s["what"].startswith("Environmental"))
        self.assertEqual(with_trips["why"], "74.34 acres and about 11,240 trips a day when built is far past the size that is exempt.")
        without = next(s for s in todo(site(74.34), forecast(trips=0))["steps"] if s["what"].startswith("Environmental"))
        self.assertEqual(without["why"], "74.34 acres is far past the size that is exempt.")

    def test_a_site_with_no_plan_and_no_forecast_programme_still_gets_the_always_present_steps(self):
        for plans in ([], None):
            with self.subTest(plans=plans):
                out = todo(plans=plans, fc=forecast(trips=0))
                self.assertEqual(whats(out), ["Meet the city's planners before applying",
                                              "File the map that divides the land into the pieces to be sold",
                                              "Environmental review under state law (the city leads it)", "Soils and geology report",
                                              "Ask for letters saying water, sewer and power can serve the site"])

    def test_it_does_not_change_what_it_is_given(self):
        s, f, p = site(), forecast(), [plan(use("homes", "Houses", 100.0, "change", homes=500))]
        before = copy.deepcopy((s, f, p))
        O.steps(s, f, p, haz(**rich_hazards()), {})
        self.assertEqual((s, f, p), before)

    def test_it_can_be_sent_as_json(self):
        json.dumps(todo(hazard=haz(**rich_hazards())), allow_nan=False)

    # the environmental-review reason used to be the same for a one-acre lot: "1 acres ... is far past the size that is exempt"
    def test_a_small_site_is_not_said_to_be_far_past_the_exempt_size(self):
        step = next(s for s in todo(site(1.0), plans=[plan(use("homes", "Houses", 1.0, homes=4))])["steps"] if s["what"].startswith("Environmental"))
        self.assertNotIn("far past", step["why"])
        self.assertNotIn("1 acres", step["why"])
        self.assertTrue(step["why"].startswith("1 acre"), step["why"])


class TheStepsThatDependOnTheUses(unittest.TestCase):
    def test_a_zone_change_only_for_a_use_that_needs_one(self):
        out = todo(site(100, "R-1"), plans=[plan(use("homes", "Houses", 60.0, "allowed", homes=300), use("retail", "Shops", 10.0, "change"),
                                                  use("office", "Offices", 5.0, "change"))])
        step = next(s for s in out["steps"] if "zone change" in s["what"])
        self.assertEqual(step["what"], "Ask for a general plan amendment and a zone change for: offices, shops", "labels sorted, lower case")
        self.assertEqual(step["why"], "The zoning today (R-1) is not meant for this use. The Planning Commission and the City Council decide.")
        self.assertEqual((step["from_year"], step["to_year"], step["kind"]), (2027, 2028, "city"))

    def test_no_zone_change_when_every_use_is_allowed_or_only_needs_review(self):
        out = todo(plans=[plan(use("homes", "Houses", 60.0, "allowed", homes=300), use("retail", "Shops", 10.0, "review"))])
        self.assertFalse(any("zone change" in w for w in whats(out)))

    def test_a_use_with_no_acres_asks_for_nothing(self):
        out = todo(plans=[plan(use("retail", "Shops", 0, "change"), use("office", "Offices", 0, "review"), use("homes", "Houses", None, "change"))])
        self.assertFalse(any("zone change" in w or "Confirm that the zone" in w for w in whats(out)))
        self.assertFalse(any("school" in w for w in whats(out)))

    def test_the_zone_change_takes_at_least_two_years_and_as_long_as_the_land_takes_to_be_ready(self):
        for ready, end in ((0, 2028), (1, 2028), (2, 2028), (5, 2031), (8, 2034)):
            with self.subTest(ready=ready):
                out = todo(fc=forecast(ready=ready), plans=[plan(use("retail", "Shops", 10.0, "change"))])
                step = next(s for s in out["steps"] if "zone change" in s["what"])
                self.assertEqual((step["from_year"], step["to_year"]), (2027, end))

    def test_confirm_that_the_zone_allows_for_uses_that_depend_on_review(self):
        out = todo(site(100, "R-1"), plans=[plan(use("retail", "Shops", 10.0, "review"), use("office", "Offices", 5.0, "review"),
                                                  use("homes", "Houses", 50.0, "allowed", homes=100))])
        step = next(s for s in out["steps"] if s["what"].startswith("Confirm"))
        self.assertEqual(step["what"], "Confirm that the zone allows: offices, shops")
        self.assertEqual(step["why"], "In R-1 this depends on the city's review; it may need a permit of its own.")
        self.assertEqual((step["from_year"], step["to_year"], step["kind"]), (2027, 2027, "city"))

    def test_the_zoning_in_the_reason_lists_each_zone_once_and_falls_back_when_there_is_none(self):
        plans = [plan(use("retail", "Shops", 10.0, "review"))]
        both = next(s for s in todo(site(10, "R-1", "C-1", "R-1"), plans=plans)["steps"] if s["what"].startswith("Confirm"))
        self.assertIn("In C-1, R-1 this depends", both["why"])
        none = next(s for s in todo(site(10, "", None), plans=plans)["steps"] if s["what"].startswith("Confirm"))
        self.assertIn("In today's zoning this depends", none["why"])

    def test_uses_from_every_plan_of_the_site_count(self):
        out = todo(plans=[plan(use("homes", "Houses", 50.0, homes=10)), plan(use("retail", "Shops", 50.0, "change"))])
        self.assertIn("Ask for a general plan amendment and a zone change for: shops", whats(out))

    def test_the_map_step_needs_two_kinds_of_use_or_five_acres(self):
        one_use = [plan(use("homes", "Houses", 4.9, homes=20))]
        self.assertNotIn("File the map that divides the land into the pieces to be sold", whats(todo(site(4.9), plans=one_use)))
        self.assertIn("File the map that divides the land into the pieces to be sold", whats(todo(site(5.0), plans=one_use)))
        two = [plan(use("homes", "Houses", 2.0, homes=10), use("retail", "Shops", 2.0))]
        self.assertIn("File the map that divides the land into the pieces to be sold", whats(todo(site(4.0), plans=two)))
        self.assertIn("File the map that divides the land into the pieces to be sold", whats(todo(site(0.0), plans=two)), "two kinds of use, no acres")

    def test_the_school_step_only_when_there_are_homes(self):
        self.assertIn("Check school room and fees with the school district", whats(todo(plans=[plan(use("homes", "Houses", 5.0, homes=20))])))
        for plans in ([plan(use("homes", "Houses", 5.0, homes=0))], [plan(use("retail", "Shops", 5.0))], [plan(use("homes", "Houses", 5.0))],
                      [plan(use("homes", "Houses", 0.0, homes=300))], []):
            with self.subTest(plans=plans):
                self.assertNotIn("Check school room and fees with the school district", whats(todo(plans=plans)))

    def test_the_school_step_adds_the_homes_of_every_use_and_plan(self):
        out = todo(plans=[plan(use("homes", "Houses", 5.0, homes=1200), use("apartments", "Apartments", 5.0, homes=34)), plan(use("homes", "Houses", 5.0, homes=1000))])
        step = next(s for s in out["steps"] if "school" in s["what"])
        self.assertEqual(step["why"], "The plan adds about 2,234 homes.")


class TheTrafficStep(unittest.TestCase):
    def traffic(self, fc=None, plans="houses"):
        return [s for s in todo(fc=fc, plans=plans)["steps"] if s["what"] == "Traffic study"]

    def test_a_traffic_study_at_a_thousand_trips_a_day_and_not_at_999(self):
        self.assertEqual(len(self.traffic(forecast(trips=1000))), 1)
        self.assertEqual(self.traffic(forecast(trips=999)), [])
        self.assertEqual(self.traffic(forecast(trips=0)), [])

    def test_signals_to_study_call_for_a_traffic_study_at_any_trip_count(self):
        out = self.traffic(forecast(trips=10), plans=[plan(use("homes", "Houses", 100.0, homes=500), signals=2)])
        self.assertEqual(len(out), 1)
        self.assertIn("and 2 new signals to study at the entrances.", out[0]["why"])

    def test_signals_are_added_up_across_plans_and_zero_signals_do_not_count(self):
        plans = [plan(use("homes", "Houses", 50.0, homes=5), signals=1), plan(use("retail", "Shops", 50.0), signals=2)]
        self.assertIn("and 3 new signals", self.traffic(plans=plans)[0]["why"])
        self.assertEqual(self.traffic(plans=[plan(use("homes", "Houses", 5.0, homes=5), signals=0)]), [])
        self.assertEqual(self.traffic(plans=[plan(use("homes", "Houses", 5.0, homes=5), signals=None)]), [])

    def test_the_reason_and_who_for_a_big_site_with_a_highway(self):
        out = self.traffic(forecast(trips=11240, highway={"route": "215"}))[0]
        self.assertEqual(out["why"], "About 11,240 trips a day once everything is built.")
        self.assertEqual(out["who"], "The city's traffic engineer and Caltrans for the highway ramps")
        self.assertEqual(self.traffic(forecast(trips=11240))[0]["who"], "The city's traffic engineer")

    # trips are 0 (not read) and the sentence used to say "About 0 trips a day at build-out"
    def test_a_traffic_study_for_signals_alone_does_not_say_zero_trips(self):
        out = self.traffic(forecast(trips=0), plans=[plan(use("homes", "Houses", 100.0, homes=500), signals=2)])
        self.assertNotIn("About 0 trips", out[0]["why"])
        self.assertEqual(out[0]["why"], "The trips a day once everything is built are not known, and 2 new signals to study at the entrances.")


class TheHazardSteps(unittest.TestCase):
    TOPICS = {"Flood": "Flood study, and building pads above the flood level",
              "Wildfire": "Fire protection plan: cleared space, fire-resistant building, two ways out",
              "Earthquake faults": "Fault study", "Soft ground and slides": "Have the soils report answer the mapped ground hazard",
              "Streams and wetlands": "Have a biologist map the water features; ask which state and federal permits apply",
              "Protected habitat": "Habitat check and the seasonal surveys the habitat plan asks for"}

    def hazard(self, *pairs):
        return {"findings": [{"topic": t, "level": l, "text": f"{t} text", "source": "S"} for t, l in pairs]}

    def test_one_study_step_for_each_work_finding_and_its_reason_is_the_finding(self):
        base = whats(todo())
        for topic, what in self.TOPICS.items():
            with self.subTest(topic=topic):
                out = todo(hazard=self.hazard((topic, "work")))
                added = [s for s in out["steps"] if s["what"] not in base]
                self.assertEqual([(s["what"], s["kind"], s["why"]) for s in added], [(what, "study", f"{topic} text")])
                self.assertEqual((added[0]["from_year"], added[0]["to_year"]), (2027, 2028))

    def test_no_step_for_a_clear_or_note_finding(self):
        base = whats(todo())
        for level in ("clear", "note"):
            with self.subTest(level=level):
                self.assertEqual(whats(todo(hazard=self.hazard(*[(t, level) for t in self.TOPICS]))), base)

    def test_a_topic_with_no_study_of_its_own_adds_nothing_even_as_work(self):
        self.assertEqual(whats(todo(hazard=self.hazard(("Fossils", "work"), ("Dam failure flooding", "work"), ("Fire service", "work")))), whats(todo()))

    def test_who_does_each_study(self):
        out = todo(hazard=self.hazard(*[(t, "work") for t in self.TOPICS]))
        who = {s["what"]: s["who"] for s in out["steps"] if s["kind"] == "study"}
        self.assertEqual(who[self.TOPICS["Flood"]], "The city engineer and the county flood control district")
        self.assertEqual(who[self.TOPICS["Wildfire"]], "The fire department (fire marshal)")
        self.assertEqual(who[self.TOPICS["Earthquake faults"]], "A licensed specialist")
        self.assertEqual(who[self.TOPICS["Soft ground and slides"]], "A licensed specialist")
        self.assertEqual(who[self.TOPICS["Streams and wetlands"]], "A biologist; the Army Corps of Engineers, the regional water board and the state wildlife department")
        self.assertEqual(who[self.TOPICS["Protected habitat"]], "A biologist and the regional conservation authority")

    def test_a_hazard_answer_that_is_not_available_or_missing_adds_nothing(self):
        for hazard in (None, {"available": False}, {}, {"findings": None}, {"findings": []}):
            with self.subTest(hazard=hazard):
                self.assertEqual(whats(todo(hazard=hazard)), whats(todo()))

    def test_the_studies_from_the_real_hazards_function(self):
        out = todo(hazard=O.hazards(rich_hazards()))
        added = [s for s in out["steps"] if s["what"] in self.TOPICS.values()]
        self.assertEqual(sorted(s["what"] for s in added), sorted(self.TOPICS.values()))
        self.assertEqual({s["why"] for s in added}, {f["text"] for f in O.hazards(rich_hazards())["findings"] if f["level"] == "work"})


class TheSellingSteps(unittest.TestCase):
    PERIODS = [{"from_year": 2028, "to_year": 2029, "lines": ["Approvals, the map and the first streets take until about 2028; the first land follows.",
                                                              "Houses: about 20 acres (400 homes).", "Shops: about 5 acres (60,000 sq ft)."]},
               {"from_year": 2030, "to_year": 2032, "lines": ["Nothing more is taken up in these years at this pace."]},
               {"from_year": 2033, "to_year": 2036, "lines": ["Houses: about 10 acres (200 homes)."]}]

    def test_an_offer_step_for_each_period_that_hands_over_land_and_not_for_the_others(self):
        out = todo(fc=forecast(steps=self.PERIODS))
        sell = [s for s in out["steps"] if s["kind"] == "sell"]
        self.assertEqual([(s["from_year"], s["to_year"], s["what"]) for s in sell], [
            (2029, 2029, "Offer to builders: Houses: about 20 acres (400 homes). Shops: about 5 acres (60,000 sq ft)."),
            (2033, 2036, "Offer to builders: Houses: about 10 acres (200 homes).")])
        self.assertEqual(sell[0]["why"], "The pace the forecast's expected line supports.")
        self.assertEqual(sell[0]["who"], "Builders and developers (see each parcel's Plan page for likely buyers)")

    def test_land_is_not_offered_before_it_is_ready(self):
        """A period that ends by the time the first land is ready is no offer; one that starts earlier is offered from the year after."""
        for ready, want in ((0, [(2028, 2029), (2033, 2036)]), (2, [(2029, 2029), (2033, 2036)]), (3, [(2033, 2036)]),
                            (7, [(2034, 2036)]), (10, [])):
            with self.subTest(ready=ready):
                out = todo(fc=forecast(steps=self.PERIODS, ready=ready))
                self.assertEqual([(s["from_year"], s["to_year"]) for s in out["steps"] if s["kind"] == "sell"], want)

    def test_a_forecast_without_steps_adds_no_offers(self):
        for programme in ({"trips_at_build_out": 0, "steps": []}, {"trips_at_build_out": 0}, {"steps": None}, None):
            with self.subTest(programme=programme):
                fc = forecast()
                fc["programme"] = programme
                self.assertFalse([s for s in todo(fc=fc)["steps"] if s["kind"] == "sell"])


class TheOrderOfTheSteps(unittest.TestCase):
    def test_steps_are_ordered_by_year_then_by_kind(self):
        out = todo(fc=forecast(trips=5000, steps=TheSellingSteps.PERIODS),
                   plans=[plan(use("homes", "Houses", 100.0, "review", homes=500), use("retail", "Shops", 10.0, "change"))],
                   hazard=O.hazards(rich_hazards()))
        rank = {"city": 0, "study": 1, "check": 2, "sell": 3}
        keys = [(s["from_year"], rank[s["kind"]]) for s in out["steps"]]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual({s["kind"] for s in out["steps"]}, set(rank))
        self.assertEqual(out["steps"][0]["what"], "Meet the city's planners before applying")
        self.assertEqual(out["steps"][-1]["kind"], "sell")

    def test_steps_of_one_kind_and_year_keep_the_order_they_were_made_in(self):
        out = todo(hazard=haz(**rich_hazards()))
        studies = [s["what"] for s in out["steps"] if s["kind"] == "study"]
        self.assertEqual(studies[:2], ["Environmental review under state law (the city leads it)", "Soils and geology report"])
        self.assertEqual(studies[2:], [TheHazardSteps.TOPICS[t] for t in ("Flood", "Wildfire", "Earthquake faults", "Soft ground and slides",
                                                                           "Streams and wetlands", "Protected habitat")])

    def test_the_years_follow_this_year_and_the_ready_years_figure(self):
        for year, ready in ((2026, 0), (2026, 2), (2026, 5), (2031, 3), (2040, 8)):
            with self.subTest(year=year, ready=ready):
                out = todo(fc=forecast(year=year, ready=ready), plans=[plan(use("retail", "Shops", 10.0, "change"), use("homes", "Houses", 90.0, homes=1))])
                spans = {s["what"]: (s["from_year"], s["to_year"]) for s in out["steps"]}
                self.assertEqual(spans["Meet the city's planners before applying"], (year + 1, year + 1))
                self.assertEqual(spans["Soils and geology report"], (year + 1, year + max(1, ready)))
                self.assertEqual(spans["Environmental review under state law (the city leads it)"], (year + 1, year + max(1, ready)))
                self.assertEqual(spans["Ask for a general plan amendment and a zone change for: shops"], (year + 1, year + max(2, ready)))

    def test_ready_years_is_rounded_to_a_whole_year(self):
        for value, end in ((1.4, 2027), (1.6, 2028), (2.4, 2028), (2.6, 2029)):
            with self.subTest(value=value):
                out = todo(fc=forecast(ready=value))
                self.assertEqual(next(s for s in out["steps"] if s["what"] == "Soils and geology report")["to_year"], end)

    def test_without_a_ready_years_figure_it_is_two_years(self):
        fc = forecast()
        fc["figures"] = [{"id": "capture_pct", "value": 20}]
        self.assertEqual(next(s for s in todo(fc=fc)["steps"] if s["what"] == "Soils and geology report")["to_year"], 2028)
        fc.pop("figures")
        self.assertEqual(next(s for s in todo(fc=fc)["steps"] if s["what"] == "Soils and geology report")["to_year"], 2028)


# ---------------------------------------------------------------- the whole outlook

def parts_all():
    return dict(economy_parts(), climate=climate_part(), hazards=rich_hazards(), nearby={"places": [{"kind": "park", "name": "Mosaic Park", "miles_away": 0.85}]},
                residents=resident_part())


def made(parts=None, plans="houses", fc=None, place="Testville"):
    plans = [plan(use("homes", "Houses", 60.0, "review", homes=500), use("retail", "Shops", 10.0, "change"))] if plans == "houses" else plans
    return O.make_outlook(site(), fc or forecast(trips=5000, steps=TheSellingSteps.PERIODS), plans, parts_all() if parts is None else parts,
                          {"name": "Testville", "planning": "Testville Planning", "water": "Testville Water"} if place == "Testville" else place)


class TheWholeOutlook(unittest.TestCase):
    def test_it_has_the_six_blocks_and_nothing_else(self):
        out = made()
        self.assertEqual(sorted(out), ["climate", "economy", "hazards", "nearby", "resident", "todo"])
        for block in ("economy", "climate", "hazards", "nearby", "resident"):
            self.assertTrue(out[block]["available"], block)
        self.assertIn("steps", out["todo"])
        self.assertTrue(out["todo"]["steps"])

    def test_it_can_be_sent_as_json_without_nan(self):
        text = json.dumps(made(), allow_nan=False)
        self.assertEqual(json.loads(text)["economy"]["place"], "Testville")

    def test_nearby_is_passed_on_as_it_came(self):
        self.assertEqual(made()["nearby"], {"available": True, "places": [{"kind": "park", "name": "Mosaic Park", "miles_away": 0.85}]})

    def test_every_block_with_no_input_is_not_available_and_has_no_numbers(self):
        out = made(parts={})
        self.assertEqual(out["economy"], {"available": False, "did_not_answer": list(O.ECONOMY_PARTS)})
        self.assertEqual(out["climate"], {"available": False})
        self.assertEqual(out["hazards"], {"available": False})
        self.assertEqual(out["nearby"], {"available": False})
        self.assertEqual(out["resident"], {"available": False})
        self.assertTrue(out["todo"]["steps"], "the checklist does not depend on any source answering")
        json.dumps(out, allow_nan=False)

    def test_every_block_set_to_none_is_the_same_as_left_out(self):
        nones = {p: None for p in O.ECONOMY_PARTS + O.PLACE_PARTS}
        self.assertEqual(made(parts=nones), made(parts={}))

    def test_an_empty_nearby_is_not_available(self):
        self.assertEqual(made(parts={"nearby": {}})["nearby"], {"available": False})

    def test_one_block_missing_does_not_take_the_others_with_it(self):
        for gone in ("climate", "hazards", "nearby", "residents", "sales"):
            with self.subTest(gone=gone):
                parts = parts_all()
                parts[gone] = None
                out = made(parts=parts)
                self.assertEqual(sum(1 for b in ("climate", "hazards", "nearby", "resident") if not out[b]["available"]), 1 if gone != "sales" else 0)
                self.assertTrue(out["economy"]["available"])

    def test_the_hazards_it_found_feed_the_checklist(self):
        out = made()
        self.assertIn("Flood study, and building pads above the flood level", whats(out["todo"]))
        out = made(parts=dict(parts_all(), hazards=None))
        self.assertNotIn("Flood study, and building pads above the flood level", whats(out["todo"]))

    def test_a_city_with_no_name_is_called_the_city(self):
        out = made(place={})
        self.assertTrue(out["economy"]["facts"][0].startswith("The city had 100,000 people in 2020"))
        self.assertEqual(out["todo"]["steps"][0]["who"], "the city's planning department")

    def test_the_inputs_are_not_changed(self):
        parts, fc = parts_all(), forecast(trips=5000)
        before = copy.deepcopy((parts, fc))
        O.make_outlook(site(), fc, [plan(use("homes", "Houses", 100.0, homes=5))], parts, {"name": "T"})
        self.assertEqual((parts, fc), before)

    def test_a_year_other_than_2026_flows_through_every_block(self):
        out = made(fc=forecast(year=2031, trips=5000))
        self.assertEqual(out["climate"]["ahead"]["year"], 2041)
        self.assertEqual(out["todo"]["steps"][0]["from_year"], 2032)
        self.assertEqual(out["economy"]["sales_ahead"][0]["year"], 2032)

    def test_the_same_inputs_give_the_same_outlook(self):
        self.assertEqual(made(), made())


class TheWordsItUses(unittest.TestCase):
    """Sentences are plain: no em dash, and none of the planner's jargon the owner would not say."""

    def outlooks(self):
        yield made()
        yield made(parts=dict(parts_all(), hazards=mild_hazards()))
        yield made(parts={})
        yield made(parts=dict(parts_all(), prices=None, sales=sales((2020, 500_000_000, 4), (2025, 300_000_000, 2))), place={})
        yield made(plans=[plan(use("homes", "Houses", 3.0, "review", homes=10))], fc=forecast(year=2031, ready=0))
        for habitat in ({"in_plan": True, "in_criteria_cell": True}, {"in_plan": True, "area_plan": "Sun City", "survey_areas": ["Burrowing Owl"]}):
            yield made(parts=dict(parts_all(), hazards={"habitat": habitat}))

    def test_there_is_no_em_dash_in_any_sentence(self):
        for out in self.outlooks():
            for text in strings(out):
                self.assertNotIn("—", text)

    def test_none_of_the_jargon_words_is_in_any_sentence(self):
        count = 0
        for out in self.outlooks():
            for text in strings(out):
                count += 1
                for word in BANNED:
                    self.assertNotIn(word, text.lower(), text)
        self.assertGreater(count, 150, "a lot of sentences were looked at")

    def test_no_sentence_prints_none_or_nan(self):
        for out in self.outlooks():
            for text in strings(out):
                self.assertNotRegex(text, r"\bNone\b(?! mapped)|\bnan\b|\binf\b", text)    # "None mapped on the site" is a sentence


if __name__ == "__main__":
    unittest.main()
