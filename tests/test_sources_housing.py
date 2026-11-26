"""The housing target reader (landplanner/sources/housing.py), tested offline.

The network function in landplanner/sources/fetch.py is replaced by recorded answers kept in
tests/fixtures/sources/ (files starting with housing_): the real answers of data.ca.gov for Menifee and for San
Francisco (a second city, with a different cycle start), a real empty answer for a place that is not there, and the
portal's note of when the table was last updated.
"""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from landplanner.cities import SourceError  # noqa: E402
from landplanner.sources import housing  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sources"
GET_JSON = "landplanner.sources.fetch.get_json"
KEYS = ("very_low", "low", "moderate", "above_moderate")


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def down(*args, **kwargs):
    raise SourceError("(test) the service is down")


def serve(city="menifee", progress=None, yearly=None, resource=None, calls=None):
    """A stand-in for fetch.get_json: the three data.ca.gov questions, each answered from a fixture (or by the
    function/answer given). `calls` collects (address, params) of every question asked."""
    def pick(given, name):
        if callable(given):
            return given()
        return copy.deepcopy(given if given is not None else fixture(name))

    def get(url, params=None, **kwargs):
        if calls is not None:
            calls.append((url, params))
        if url == housing.SQL_URL:
            return pick(yearly, f"housing_yearly_{city}.json")
        if url == housing.SEARCH_URL:
            return pick(progress, f"housing_progress_{city}.json")
        if url == housing.RESOURCE_URL:
            return pick(resource, "housing_resource.json")
        raise AssertionError(f"unexpected question {url}")
    return get


def run(place="Menifee", county=None, **options):
    with mock.patch(GET_JSON, side_effect=serve(**options)):
        return housing.housing_target(place, county)


def with_row(**changes):
    """The Menifee progress answer with some cells of its one row changed."""
    answer = fixture("housing_progress_menifee.json")
    answer["result"]["records"][0].update(changes)
    return answer


class MenifeeTests(unittest.TestCase):
    def test_the_normal_answer(self):
        calls = []
        answer = run(calls=calls)
        self.assertEqual(answer["cycle"], "6th")
        self.assertEqual((answer["from_year"], answer["to_year"]), (2021, 2029))
        self.assertEqual(answer["planning_period"], "10/15/2021 - 10/15/2029")
        self.assertEqual(answer["target"], {"very_low": 1761, "low": 1051, "moderate": 1106, "above_moderate": 2691,
                                            "total": 6609})
        self.assertEqual(answer["permitted"], {"very_low": 9, "low": 21, "moderate": 37, "above_moderate": 3819,
                                               "total": 3886})
        self.assertEqual(answer["left"], {"very_low": 1752, "low": 1030, "moderate": 1069, "above_moderate": 0,
                                          "total": 3851})
        self.assertEqual(answer["share_pct"], {"very_low": 0.5, "low": 2.0, "moderate": 3.3, "above_moderate": 141.9,
                                               "total": 58.8})
        self.assertEqual(answer["through_year"], 2025)
        self.assertEqual(answer["as_of"], "annual reports through 2025; table updated 2026-11-20")
        self.assertIn("Department of Housing and Community Development", answer["source"])
        self.assertEqual(answer["jurisdiction"], "MENIFEE")

    def test_totals_match_the_recorded_answer(self):
        record = fixture("housing_progress_menifee.json")["result"]["records"][0]
        answer = run()
        self.assertEqual(answer["target"]["total"],
                         record["RHNA VLI"] + record["RHNA LI"] + record["RHNA MOD"] + record["RHNA ABOVE MOD"])
        self.assertEqual(answer["permitted"]["total"],
                         record["VLI UNITS"] + record["LI UNITS"] + record["MOD UNITS"] + record["ABOVE MOD UNITS"])
        for key in KEYS:
            self.assertEqual(answer["left"][key], max(answer["target"][key] - answer["permitted"][key], 0))

    def test_the_years_match_the_recorded_answer(self):
        answer = run()
        rows = {r["year"]: r for r in answer["by_year"]}
        self.assertEqual(sorted(rows), [2021, 2022, 2023, 2024, 2025])
        self.assertEqual(rows[2022], {"year": 2022, "very_low": 4, "low": 4, "moderate": 5, "above_moderate": 892, "total": 905})
        self.assertEqual(rows[2025], {"year": 2025, "very_low": 3, "low": 11, "moderate": 8, "above_moderate": 736, "total": 758})
        for record in fixture("housing_yearly_menifee.json")["result"]["records"]:
            row = rows[record["year"]]
            self.assertEqual(row["total"], sum(row[k] for k in KEYS))
            self.assertEqual(row["above_moderate"], int(record["BP_ABOVE_MOD_INCOME"]))
            self.assertEqual(row["low"], int(record["BP_LOW_INCOME_DR"]) + int(record["BP_LOW_INCOME_NDR"]))
        # the state's count starts on its own date, so 2021 onward adds up to more, and the answer says so
        self.assertGreater(sum(r["above_moderate"] for r in answer["by_year"]), answer["permitted"]["above_moderate"])
        self.assertTrue(any("do not add up" in n for n in answer["notes"]))

    def test_the_questions_asked(self):
        calls = []
        run(calls=calls)
        by_url = {url: params for url, params in calls}
        progress = by_url[housing.SEARCH_URL]
        self.assertEqual(progress["resource_id"], "1e80a9cf-724c-432d-8374-e9708a6a92dc")
        self.assertEqual(json.loads(progress["filters"]), {"Jurisdiction": ["MENIFEE"]})
        sql = by_url[housing.SQL_URL]["sql"]
        self.assertIn("fe505d9b-8c36-42ba-ba30-08bc4f34e022", sql)
        self.assertIn("\"JURIS_NAME\" = 'MENIFEE'", sql)
        self.assertIn("\"YEAR\" >= 2021", sql)
        self.assertIn("GROUP BY", sql)
        self.assertEqual(by_url[housing.RESOURCE_URL], {"id": "1e80a9cf-724c-432d-8374-e9708a6a92dc"})

    def test_answer_is_plain_data(self):
        answer = run()
        self.assertEqual(json.loads(json.dumps(answer)), answer)
        self.assertEqual(set(answer["target"]), set(KEYS) | {"total"})

    def test_spellings_of_the_name(self):
        for spelling in ("Menifee", "MENIFEE", " menifee ", "Menifee City", "City of Menifee", "MENIFEE  CITY"):
            calls = []
            answer = run(spelling, calls=calls)
            self.assertEqual(answer["target"]["total"], 6609, spelling)
            asked = json.loads([p for u, p in calls if u == housing.SEARCH_URL][0]["filters"])["Jurisdiction"]
            self.assertEqual(asked[-1], "MENIFEE", spelling)

    def test_a_name_that_ends_in_city_is_tried_whole_first(self):
        calls = []
        with self.assertRaises(SourceError):
            run("Culver City", calls=calls, progress={"success": True, "result": {"records": []}})
        asked = json.loads(calls[0][1]["filters"])["Jurisdiction"]
        self.assertEqual(asked, ["CULVER CITY", "CULVER"])

    def test_the_county_may_be_given(self):
        self.assertEqual(run(county="Riverside")["target"]["total"], 6609)
        self.assertEqual(run(county="riverside county")["target"]["total"], 6609)
        with self.assertRaises(SourceError):
            run(county="San Diego")


class SecondCityTests(unittest.TestCase):
    def test_san_francisco(self):
        answer = run("San Francisco", city="san_francisco")
        self.assertEqual((answer["from_year"], answer["to_year"]), (2023, 2031))
        self.assertEqual(answer["target"], {"very_low": 20867, "low": 12014, "moderate": 13717, "above_moderate": 35471,
                                            "total": 82069})
        self.assertEqual(answer["permitted"], {"very_low": 1685, "low": 1215, "moderate": 971, "above_moderate": 2215,
                                               "total": 6086})
        self.assertEqual(answer["left"]["total"], 82069 - 6086)
        self.assertEqual([r["year"] for r in answer["by_year"]], [2023, 2024, 2025])
        rows = {r["year"]: r for r in answer["by_year"]}
        # acutely and extremely low-income homes count as very low-income, as the state counts them
        self.assertEqual(rows[2025]["very_low"], 258 + 451 + 53)
        self.assertEqual(sum(r["very_low"] for r in answer["by_year"]), 1685)
        self.assertEqual(sum(r["above_moderate"] for r in answer["by_year"]), 2215)
        self.assertEqual(answer["through_year"], 2025)

    def test_a_different_city_does_not_show_menifee_numbers(self):
        self.assertNotEqual(run("San Francisco", city="san_francisco")["target"], run()["target"])


class MissingAndFailingTests(unittest.TestCase):
    def test_a_city_with_no_rows(self):
        with self.assertRaises(SourceError):
            run("Atlantis", progress=fixture("housing_progress_none.json"))

    def test_no_name(self):
        for name in ("", "   ", None):
            with self.assertRaises(SourceError):
                housing.housing_target(name)

    def test_the_main_table_down_or_odd(self):
        with mock.patch(GET_JSON, side_effect=down):
            with self.assertRaises(SourceError):
                housing.housing_target("Menifee")
        for odd in ({"success": False}, {"unexpected": 1}, [], {"success": True, "result": {"records": "none"}}):
            with self.assertRaises(SourceError):
                run(progress=odd)

    def test_the_yearly_figures_down_leave_the_target(self):
        answer = run(yearly=down)
        self.assertEqual(answer["target"]["total"], 6609)
        self.assertEqual(answer["permitted"]["total"], 3886)
        self.assertEqual(answer["by_year"], [])
        self.assertIsNone(answer["through_year"])
        self.assertTrue(any("yearly permit figures did not answer" in n for n in answer["notes"]))
        self.assertEqual(answer["as_of"], "no annual report found; table updated 2026-11-20")

    def test_the_yearly_figures_odd(self):
        for odd in ({"success": False}, {"success": True, "result": {"records": None}}, "text"):
            answer = run(yearly=odd)
            self.assertEqual(answer["by_year"], [])
            self.assertEqual(answer["target"]["total"], 6609)

    def test_no_date_from_the_portal_is_said_plainly(self):
        answer = run(resource=down)
        self.assertEqual(answer["as_of"], "annual reports through 2025")
        self.assertTrue(any("last updated" in n for n in answer["notes"]))
        self.assertEqual(run(resource={"result": {}})["as_of"], "annual reports through 2025")

    def test_a_city_with_a_target_but_no_yearly_reports(self):
        answer = run(yearly={"success": True, "result": {"records": []}})
        self.assertEqual(answer["by_year"], [])
        self.assertTrue(any("no yearly permit reports" in n for n in answer["notes"]))


class OddCellTests(unittest.TestCase):
    def test_text_blanks_and_commas_in_the_main_table(self):
        answer = run(progress=with_row(**{"RHNA LI": "1,051", "RHNA MOD": "", "VLI UNITS": "n/a", "LI UNITS": " 21 ",
                                          "RHNA VLI": "1761.0"}))
        self.assertEqual(answer["target"], {"very_low": 1761, "low": 1051, "moderate": None, "above_moderate": 2691,
                                            "total": 1761 + 1051 + 2691})
        self.assertEqual(answer["permitted"], {"very_low": None, "low": 21, "moderate": 37, "above_moderate": 3819,
                                               "total": 21 + 37 + 3819})
        self.assertIsNone(answer["left"]["moderate"])
        self.assertIsNone(answer["left"]["very_low"])
        self.assertEqual(answer["left"]["low"], 1030)
        self.assertEqual(answer["left"]["total"], 1030)
        self.assertIsNone(answer["share_pct"]["moderate"])
        self.assertIsNone(answer["share_pct"]["total"])         # a total over only some levels is not compared
        self.assertEqual(answer["share_pct"]["low"], 2.0)
        notes = " ".join(answer["notes"])
        self.assertIn("moderate-income target was blank", notes)
        self.assertIn("very low-income permits counted was not a number ('n/a')", notes)
        self.assertIn("leaves out the levels that were missing", notes)

    def test_nothing_is_turned_into_a_zero(self):
        answer = run(progress=with_row(**{"RHNA MOD": None, "MOD UNITS": None, "RHNA LI": -4, "LI UNITS": 2.5, "ABOVE MOD UNITS": True}))
        for block in ("target", "permitted"):
            self.assertIsNone(answer[block]["moderate"])
        self.assertIsNone(answer["target"]["low"])               # a negative count is not a count
        self.assertIsNone(answer["permitted"]["low"])            # nor is a part of a home
        self.assertIsNone(answer["permitted"]["above_moderate"])
        self.assertEqual(answer["target"]["total"], 1761 + 2691)

    def test_no_target_at_all(self):
        answer = run(progress=with_row(**{"RHNA VLI": None, "RHNA LI": "", "RHNA MOD": "x", "RHNA ABOVE MOD": None}))
        self.assertIsNone(answer["target"])
        self.assertIsNone(answer["left"])
        self.assertIsNone(answer["share_pct"])
        self.assertEqual(answer["permitted"]["total"], 3886)
        self.assertTrue(any("no target" in n for n in answer["notes"]))

    def test_a_target_of_zero_never_divides(self):
        answer = run(progress=with_row(**{"RHNA VLI": 0, "RHNA LI": "0"}))
        self.assertIsNone(answer["share_pct"]["very_low"])
        self.assertIsNone(answer["share_pct"]["low"])
        self.assertEqual(answer["left"]["very_low"], 0)
        self.assertEqual(answer["share_pct"]["moderate"], 3.3)
        self.assertEqual(answer["target"]["total"], 0 + 0 + 1106 + 2691)

    def test_a_planning_period_that_cannot_be_read(self):
        answer = run(progress=with_row(**{"Planning Period": "to be set"}))
        self.assertIsNone(answer["from_year"])
        self.assertIsNone(answer["to_year"])
        self.assertEqual(answer["by_year"], [])
        self.assertEqual(answer["target"]["total"], 6609)
        self.assertTrue(any("planning period" in n for n in answer["notes"]))

    def test_text_and_blanks_in_the_yearly_figures(self):
        yearly = fixture("housing_yearly_menifee.json")
        records = yearly["result"]["records"]
        records[1]["BP_ABOVE_MOD_INCOME"] = "892"                  # text where a number is expected
        records[2]["BP_ABOVE_MOD_INCOME"] = None                   # a whole year left blank
        records[3]["BP_LOW_INCOME_NDR"] = "six"                    # not a number: left out, not zero
        records[4]["BP_VLOW_INCOME_NDR"] = None                    # part of a level blank: the rest still counts
        answer = run(yearly=yearly)
        rows = {r["year"]: r for r in answer["by_year"]}
        self.assertEqual(rows[2022]["above_moderate"], 892)
        self.assertIsNone(rows[2023]["above_moderate"])
        self.assertEqual(rows[2023]["total"], 14)                  # the moderate homes only: the blank is left out
        self.assertEqual(rows[2024]["low"], int(records[3]["BP_LOW_INCOME_DR"]))        # only the readable part
        self.assertTrue(any("2024: part of the low-income permits was not a number" in n for n in answer["notes"]))
        self.assertEqual(rows[2025]["low"], 11)
        self.assertTrue(any("2023: the above moderate-income permits were blank" in n for n in answer["notes"]))

    def test_a_year_with_all_blank_levels_has_no_total(self):
        yearly = fixture("housing_yearly_menifee.json")
        for column in housing._ALL_COLUMNS:
            yearly["result"]["records"][0][column] = None
        row = run(yearly=yearly)["by_year"][0]
        self.assertEqual(row, {"year": 2021, "very_low": None, "low": None, "moderate": None, "above_moderate": None,
                               "total": None})

    def test_duplicated_rows(self):
        main = fixture("housing_progress_menifee.json")
        main["result"]["records"].append({**main["result"]["records"][0], "_id": 999})
        self.assertEqual(run(progress=main)["target"]["total"], 6609)          # an exact repeat counts once
        main["result"]["records"][1]["RHNA VLI"] = 5
        with self.assertRaises(SourceError):                                   # two different rows: not guessed
            run(progress=main)
        yearly = fixture("housing_yearly_menifee.json")
        yearly["result"]["records"].append(copy.deepcopy(yearly["result"]["records"][0]))
        self.assertEqual([r["year"] for r in run(yearly=yearly)["by_year"]], [2021, 2022, 2023, 2024, 2025])
        yearly["result"]["records"][-1]["BP_ABOVE_MOD_INCOME"] = 1
        self.assertEqual(run(yearly=yearly)["by_year"], [])                    # conflicting years: the yearly part is dropped
        self.assertEqual(run(yearly=yearly)["target"]["total"], 6609)

    def test_rows_of_other_places_are_ignored(self):
        main = fixture("housing_progress_menifee.json")
        main["result"]["records"].insert(0, fixture("housing_progress_san_francisco.json")["result"]["records"][0])
        self.assertEqual(run(progress=main)["target"]["total"], 6609)

    def test_an_apostrophe_cannot_break_the_question(self):
        calls = []
        record = fixture("housing_progress_menifee.json")
        record["result"]["records"][0]["Jurisdiction"] = "O'NEILL"
        run("O'Neill", progress=record, calls=calls)
        sql = [p for u, p in calls if u == housing.SQL_URL][0]["sql"]
        self.assertIn("'O''NEILL'", sql)


class FixtureSizeTests(unittest.TestCase):
    def test_fixtures_stay_small(self):
        total = sum(p.stat().st_size for p in FIXTURES.glob("housing_*"))
        self.assertLess(total, 40_000)


if __name__ == "__main__":
    unittest.main()
