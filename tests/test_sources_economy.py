"""The economy readers (landplanner/sources/economy.py), tested offline.

The network functions in landplanner/sources/fetch.py are replaced by small recorded answers kept in
tests/fixtures/sources/ (files starting with econ_). One extra test reads the real saved Department of Finance
workbook, and is skipped when that file is not on this computer.
"""
import os
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from landplanner.cities import SourceError  # noqa: E402
from landplanner.sources import economy  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sources"
REAL_E5 = Path(os.environ.get("LANDPLANNER_REAL_E5") or "no-saved-copy.xlsx")   # a saved copy of the state's real workbook
GET_BYTES = "landplanner.sources.fetch.get_bytes"
GET_JSON = "landplanner.sources.fetch.get_json"


def fixture(name):
    return (FIXTURES / name).read_bytes()


def fixture_json(name):
    return json.loads(fixture(name).decode("utf-8"))


def down(*args, **kwargs):
    raise SourceError("(test) the service is down")


# ---------------------------------------------------------------- a small workbook laid out like the real one

HEADER = ["County/City/State", "Total", "Household", "Group Quarters", "Total", "Single Detached",
          "Single Attached", "Two to Four", "Five Plus", "Mobile Homes", "Occupied", "Vacancy Rate",
          "Persons per Household"]
MENIFEE = {2025: ["115813", "115608", "205", "42096", "36789", "1163", "506", "1097", "2541", "40127",
                  "4.6774040288863561E-2", "2.8810526578114488"],
           2026: ["117847", "117642", "205", "43213", "37453", "1167", "506", "1542", "2545", "41192",
                  "4.6768333603313783E-2", "2.8559429015342785"]}
OTHER = ["1000", "990", "10", "400", "300", "10", "20", "30", "40", "380", "5E-2", "2.5"]
# (county header, [(city name as the file spells it, numbers)])
LAYOUT = [("Los Angeles County", [("Glendora             ", OTHER)]),
          ("Riverside County", [("Menifee", None), ("Riverside           ", OTHER)]),
          ("San Diego County", [("Glendora", OTHER)])]


def _col(i):
    return "ABCDEFGHIJKLM"[i]


def make_workbook(years=(2025, 2026)):
    """An xlsx with the sheets E5CountyState<year> and E5CityCounty<year>, headers on row 4, a county title row
    before each county's cities, and shared strings, as in the real file (made with zipfile only)."""
    strings = []

    def s(text):
        if text not in strings:
            strings.append(text)
        return strings.index(text)

    def sheet(year, city_sheet):
        rows = [f'<row r="1"><c r="A1" t="s"><v>{s("Table 2: E-5 estimates")}</v></c></row>', '<row r="2"/>',
                f'<row r="3"><c r="B3" t="s"><v>{s("POPULATION")}</v></c></row>']
        rows.append('<row r="4">' + "".join(f'<c r="{_col(i)}4" t="s"><v>{s(h)}</v></c>' for i, h in enumerate(HEADER))
                    + "</row>")
        n = 5
        for county, cities in LAYOUT:
            rows.append(f'<row r="{n}"><c r="A{n}" t="s"><v>{s(county)}</v></c><c r="L{n}" t="s"><v>{s(" ")}</v></c></row>')
            n += 1
            for name, numbers in cities:
                numbers = numbers or MENIFEE[year]
                cells = f'<c r="A{n}" t="s"><v>{s(name)}</v></c>' + "".join(
                    f'<c r="{_col(i + 1)}{n}"><v>{v}</v></c>' for i, v in enumerate(numbers))
                rows.append(f'<row r="{n}">{cells}</row>')
                n += 1
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        return f'<worksheet xmlns="{ns}"><sheetData>{"".join(rows)}</sheetData></worksheet>'

    names, files = [], {}
    for year in years:
        for kind in ("CountyState", "CityCounty"):
            names.append(f"E5{kind}{year}")
            files[f"xl/worksheets/sheet{len(names)}.xml"] = sheet(year, kind == "CityCounty")
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    book = (f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets>'
            + "".join(f'<sheet name="{n}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names))
            + "</sheets></workbook>")
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i + 1}" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(names)))
            + "</Relationships>")
    shared = f'<sst xmlns="{ns}">' + "".join(f"<si><t>{t}</t></si>" for t in strings) + "</sst>"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/workbook.xml", book)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/sharedStrings.xml", shared)
        for path, xml in files.items():
            z.writestr(path, xml)
    return out.getvalue()


def serialisable(test, answer):
    test.assertEqual(json.loads(json.dumps(answer)), answer)


class PopulationTests(unittest.TestCase):
    def test_menifee_two_years(self):
        with mock.patch(GET_BYTES, return_value=make_workbook()) as got:
            answer = economy.population_by_year("Menifee", 2026)
        self.assertEqual(got.call_args[0][0], "https://dof.ca.gov/media/docs/forecasting/Demographics/estimates/"
                         "e-5-population-and-housing-estimates-for-cities-counties-and-the-state-2020-2026/"
                         "E-5_2026_InternetVersion.xlsx")
        self.assertEqual(answer["rows"], [
            {"year": 2025, "people": 115813, "homes": 42096, "occupied_homes": 40127, "vacancy_pct": 4.7,
             "single_family_homes": 37952, "multi_family_homes": 1603, "mobile_homes": 2541, "people_per_home": 2.88},
            {"year": 2026, "people": 117847, "homes": 43213, "occupied_homes": 41192, "vacancy_pct": 4.7,
             "single_family_homes": 38620, "multi_family_homes": 2048, "mobile_homes": 2545, "people_per_home": 2.86}])
        self.assertEqual(answer["latest_year"], 2026)
        self.assertIn("April 2020", answer["date"])
        self.assertIn("Department of Finance", answer["source"])
        serialisable(self, answer)

    def test_the_homes_add_up(self):
        with mock.patch(GET_BYTES, return_value=make_workbook()):
            row = economy.population_by_year("Menifee", 2026)["rows"][-1]
        self.assertEqual(row["single_family_homes"] + row["multi_family_homes"] + row["mobile_homes"], row["homes"])

    def test_newest_year_not_published_falls_back_to_the_year_before(self):
        def serve(url, *args, **kwargs):
            if "2027" in url:
                raise SourceError("(test) not published yet")
            return make_workbook()
        with mock.patch(GET_BYTES, side_effect=serve) as got:
            answer = economy.population_by_year("Menifee", 2027)
        self.assertEqual([c[0][0].rsplit("/", 1)[1] for c in got.call_args_list],
                         ["E-5_2027_InternetVersion.xlsx", "E-5_2026_InternetVersion.xlsx"])
        self.assertEqual(answer["latest_year"], 2026)

    def test_place_missing(self):
        with mock.patch(GET_BYTES, return_value=make_workbook()):
            with self.assertRaises(SourceError):
                economy.population_by_year("Atlantis", 2026)

    def test_same_name_in_two_counties_needs_the_county(self):
        with mock.patch(GET_BYTES, return_value=make_workbook()):
            with self.assertRaises(SourceError):
                economy.population_by_year("Glendora", 2026)
            row = economy.population_by_year("Glendora", 2026, county="San Diego")["rows"][0]
        self.assertEqual(row["people"], 1000)

    def test_service_down_and_unreadable_file(self):
        with mock.patch(GET_BYTES, side_effect=down):
            with self.assertRaises(SourceError):
                economy.population_by_year("Menifee", 2026)
        with mock.patch(GET_BYTES, return_value=b"<html>not a workbook</html>"):
            with self.assertRaises(SourceError):
                economy.population_by_year("Menifee", 2026)

    def test_a_blank_figure_is_an_error_not_a_zero(self):
        broken = {2025: MENIFEE[2025], 2026: MENIFEE[2026][:3] + [""] + MENIFEE[2026][4:]}
        with mock.patch.dict(MENIFEE, broken), mock.patch(GET_BYTES, return_value=make_workbook()):
            with self.assertRaises(SourceError):
                economy.population_by_year("Menifee", 2026)

    @unittest.skipUnless(REAL_E5.exists(), "set LANDPLANNER_REAL_E5 to a saved copy of the real workbook to run this")
    def test_the_real_saved_workbook(self):
        with mock.patch(GET_BYTES, return_value=REAL_E5.read_bytes()):
            answer = economy.population_by_year("Menifee", 2026)
        rows = {r["year"]: r for r in answer["rows"]}
        self.assertEqual(sorted(rows), [2020, 2021, 2022, 2023, 2024, 2025, 2026])
        self.assertEqual((rows[2020]["people"], rows[2020]["homes"]), (102383, 36526))
        self.assertEqual((rows[2026]["people"], rows[2026]["homes"]), (117847, 43213))
        self.assertEqual(rows[2026]["occupied_homes"], 41192)
        self.assertEqual(rows[2026]["vacancy_pct"], 4.7)


class PermitTests(unittest.TestCase):
    @staticmethod
    def serve(years=(2023, 2024, 2025)):
        def get(url, *args, **kwargs):
            for year in years:
                if url.endswith(f"we{year}a.txt"):
                    return fixture(f"econ_permits_{year}.txt")
            raise SourceError("(test) no such file")
        return get

    def test_menifee_three_years(self):
        with mock.patch(GET_BYTES, side_effect=self.serve()) as got:
            answer = economy.permits_by_year("46842", 2023, 2025)
        self.assertEqual(got.call_args_list[0][0][0], "https://www2.census.gov/econ/bps/Place/West%20Region/we2023a.txt")
        self.assertEqual(answer["rows"], [
            {"year": 2023, "homes": 1000, "single_family": 875, "multi_family": 125, "months_reported": 11},
            {"year": 2024, "homes": 983, "single_family": 942, "multi_family": 41, "months_reported": 12},
            {"year": 2025, "homes": 1147, "single_family": 676, "multi_family": 471, "months_reported": 12}])
        self.assertEqual(answer["missing_years"], [])
        self.assertEqual(answer["place"], "Menifee")
        serialisable(self, answer)

    def test_a_short_year_keeps_its_month_count(self):
        with mock.patch(GET_BYTES, side_effect=self.serve()):
            rows = economy.permits_by_year("46842", 2023, 2023)["rows"]
        self.assertEqual(rows[0]["months_reported"], 11)

    def test_a_missing_year_file_is_skipped_and_listed(self):
        with mock.patch(GET_BYTES, side_effect=self.serve((2023, 2025))):
            answer = economy.permits_by_year("46842", 2023, 2026)
        self.assertEqual([r["year"] for r in answer["rows"]], [2023, 2025])
        self.assertEqual(answer["missing_years"], [2024, 2026])

    def test_state_and_place_code_together(self):
        with mock.patch(GET_BYTES, side_effect=self.serve()):
            answer = economy.permits_by_year("0646842", 2025, 2025)
        self.assertEqual(answer["rows"][0]["homes"], 1147)

    def test_place_missing(self):
        with mock.patch(GET_BYTES, side_effect=self.serve()):
            with self.assertRaises(SourceError):
                economy.permits_by_year("99999", 2023, 2025)

    def test_service_down(self):
        with mock.patch(GET_BYTES, side_effect=down):
            with self.assertRaises(SourceError):
                economy.permits_by_year("46842", 2023, 2025)


class SalesTests(unittest.TestCase):
    def test_menifee_by_year(self):
        with mock.patch(GET_JSON, return_value=fixture_json("econ_sales.json")) as got:
            answer = economy.shop_sales_by_year("Menifee")
        self.assertIn("City%20eq%20%27Menifee%27", got.call_args[0][0])
        rows = {r["year"]: r for r in answer["rows"]}
        self.assertEqual(rows[2019], {"year": 2019, "sales_usd": 688681654, "quarters": 4})
        self.assertEqual(rows[2023], {"year": 2023, "sales_usd": 943262435, "quarters": 4})
        self.assertEqual(rows[2025], {"year": 2025, "sales_usd": 986611130, "quarters": 4})
        self.assertEqual(answer["latest_quarter"], {"year": 2026, "quarter": 2, "sales_usd": 266855829})
        self.assertEqual(answer["as_of"], "2026 Q2")
        self.assertEqual(answer["county"], "Riverside")
        serialisable(self, answer)

    def test_a_year_with_fewer_than_four_quarters_says_so(self):
        with mock.patch(GET_JSON, return_value=fixture_json("econ_sales.json")):
            rows = {r["year"]: r for r in economy.shop_sales_by_year("Menifee")["rows"]}
        self.assertEqual(rows[2026], {"year": 2026, "sales_usd": 513704237, "quarters": 2})

    def test_a_withheld_quarter_is_not_counted(self):
        answer = fixture_json("econ_sales.json")
        for r in answer["value"]:
            if (r["CalendarYear"], r["Quarter"]) == (2025, "Q3"):
                r["RetailandFoodServicesTaxableTransactions"] = None
        with mock.patch(GET_JSON, return_value=answer):
            rows = {r["year"]: r for r in economy.shop_sales_by_year("Menifee")["rows"]}
        self.assertEqual(rows[2025], {"year": 2025, "sales_usd": 986611130 - 242438624, "quarters": 3})

    def test_place_missing(self):
        with mock.patch(GET_JSON, return_value={"value": []}):
            with self.assertRaises(SourceError):
                economy.shop_sales_by_year("Atlantis")

    def test_two_counties_is_an_error(self):
        answer = fixture_json("econ_sales.json")
        answer["value"][0]["County"] = "Orange"
        with mock.patch(GET_JSON, return_value=answer):
            with self.assertRaises(SourceError):
                economy.shop_sales_by_year("Menifee")

    def test_service_down_and_odd_answer(self):
        with mock.patch(GET_JSON, side_effect=down):
            with self.assertRaises(SourceError):
                economy.shop_sales_by_year("Menifee")
        with mock.patch(GET_JSON, return_value={"unexpected": 1}):
            with self.assertRaises(SourceError):
                economy.shop_sales_by_year("Menifee")


class WorkTests(unittest.TestCase):
    @staticmethod
    def serve(monthly=True, city_empty=False):
        def get(url, params=None, **kwargs):
            area = json.loads(params["filters"])["Area Name"]
            if params["resource_id"] == economy.WORK_MONTHLY:
                if not monthly:
                    raise SourceError("(test) monthly figures down")
                return fixture_json("econ_work_monthly.json")
            if area == "Menifee City":
                data = fixture_json("econ_work_yearly_city.json")
                if city_empty:
                    data["result"]["records"] = []
                return data
            if area == "Riverside County":
                return fixture_json("econ_work_yearly_county.json")
            raise AssertionError(f"unexpected area {area}")
        return get

    def run_work(self, **options):
        with mock.patch(GET_JSON, side_effect=self.serve(**options)), \
                mock.patch.object(economy, "_this_year", return_value=2026):
            return economy.work_by_year("Menifee", "Riverside")

    def test_menifee(self):
        answer = self.run_work()
        rows = {r["year"]: r for r in answer["rows"]}
        self.assertEqual(rows[2025], {"year": 2025, "labour_force": 51936, "employed": 49127, "unemployment_pct": 5.4})
        self.assertEqual(rows[2021], {"year": 2021, "labour_force": 45500, "employed": 42200, "unemployment_pct": 7.2})
        county = {r["year"]: r for r in answer["county_rows"]}
        self.assertEqual(county[2025]["labour_force"], 1207200)
        self.assertEqual(answer["latest_month"], {
            "year": 2026, "labour_force": 51200, "employed": 48500, "unemployment_pct": 5.3,
            "month": "October", "month_number": 10, "status": "Preliminary"})
        self.assertEqual(answer["as_of"], "October 2026")
        serialisable(self, answer)

    def test_county_name_may_include_the_word_county(self):
        with mock.patch(GET_JSON, side_effect=self.serve()), mock.patch.object(economy, "_this_year", return_value=2026):
            self.assertEqual(economy.work_by_year("Menifee", "Riverside County")["county_rows"][-1]["year"], 2025)

    def test_monthly_figures_down_is_said_plainly(self):
        answer = self.run_work(monthly=False)
        self.assertIsNone(answer["latest_month"])
        self.assertIn("did not answer", answer["latest_month_note"])
        self.assertEqual(answer["rows"][-1]["year"], 2025)

    def test_a_blank_year_is_left_out(self):
        data = fixture_json("econ_work_yearly_city.json")
        for r in data["result"]["records"]:
            if r["Year"] == 2024:
                r["Labor Force"] = None
        with mock.patch(GET_JSON, side_effect=self.serve()) as got:
            got.side_effect = lambda url, params=None, **k: (data if params["resource_id"] == economy.WORK_YEARLY
                                                              and "Menifee" in params["filters"] else self.serve()(url, params))
            with mock.patch.object(economy, "_this_year", return_value=2026):
                years = [r["year"] for r in economy.work_by_year("Menifee", "Riverside")["rows"]]
        self.assertNotIn(2024, years)
        self.assertIn(2025, years)

    def test_place_missing(self):
        with mock.patch(GET_JSON, side_effect=self.serve(city_empty=True)):
            with self.assertRaises(SourceError):
                economy.work_by_year("Menifee", "Riverside")

    def test_service_down(self):
        with mock.patch(GET_JSON, side_effect=down):
            with self.assertRaises(SourceError):
                economy.work_by_year("Menifee", "Riverside")
        with mock.patch(GET_JSON, return_value={"success": False}):
            with self.assertRaises(SourceError):
                economy.work_by_year("Menifee", "Riverside")


class MortgageTests(unittest.TestCase):
    def test_yearly_averages_and_latest(self):
        with mock.patch(GET_BYTES, return_value=fixture("econ_rates.csv")):
            answer = economy.mortgage_rates()
        rows = {r["year"]: r for r in answer["rows"]}
        self.assertEqual(len(answer["rows"]), 12)
        self.assertEqual((answer["rows"][0]["year"], answer["rows"][-1]["year"]), (2015, 2026))
        self.assertEqual(rows[2021], {"year": 2021, "rate_pct": 2.96, "weeks": 52})
        self.assertEqual(rows[2025], {"year": 2025, "rate_pct": 6.6, "weeks": 53})
        self.assertEqual(rows[2026], {"year": 2026, "rate_pct": 6.57, "weeks": 47})      # a year not finished
        self.assertEqual(answer["latest"], {"date": "2026-11-25", "rate_pct": 7.21})
        serialisable(self, answer)

    def test_service_down_and_wrong_file(self):
        with mock.patch(GET_BYTES, side_effect=down):
            with self.assertRaises(SourceError):
                economy.mortgage_rates()
        with mock.patch(GET_BYTES, return_value=b"<html>a web page</html>"):
            with self.assertRaises(SourceError):
                economy.mortgage_rates()
        with mock.patch(GET_BYTES, return_value=b"date,pmms30\n"):
            with self.assertRaises(SourceError):
                economy.mortgage_rates()


class PriceTests(unittest.TestCase):
    @staticmethod
    def serve(calls):
        def get(url, *args, data=None, headers=None, **kwargs):
            asked = json.loads(data)
            calls.append(asked)
            return fixture("econ_prices_1.json" if asked["startyear"] == "2015" else "econ_prices_2.json")
        return get

    def test_riverside_area(self):
        calls = []
        with mock.patch(GET_BYTES, side_effect=self.serve(calls)), mock.patch.object(economy, "_this_year", return_value=2026):
            answer = economy.prices_by_year(2016)
        self.assertEqual([(c["startyear"], c["endyear"]) for c in calls], [("2015", "2024"), ("2025", "2026")])
        self.assertTrue(all(int(c["endyear"]) - int(c["startyear"]) < 10 for c in calls))
        self.assertEqual(calls[0]["seriesid"], ["CUURS49CSA0"])
        rows = {r["year"]: r for r in answer["rows"]}
        self.assertEqual(rows[2018], {"year": 2018, "index": 102.6, "change_pct": None})   # 2017 has no full year
        self.assertEqual(rows[2019], {"year": 2019, "index": 105.6, "change_pct": 2.9})
        self.assertEqual(rows[2022], {"year": 2022, "index": 123.6, "change_pct": 8.9})
        self.assertEqual(rows[2025], {"year": 2025, "index": 137.3, "change_pct": 3.3})
        self.assertNotIn(2026, rows)             # 2026 is not finished, so it is not listed as a year
        self.assertEqual(answer["latest"], {"year": 2026, "month": "September", "index": 142.969, "change_pct": 3.6})
        self.assertEqual(answer["as_of"], "September 2026")
        serialisable(self, answer)

    def test_a_request_is_a_post_with_json(self):
        with mock.patch(GET_BYTES, side_effect=self.serve([])) as got, mock.patch.object(economy, "_this_year", return_value=2026):
            economy.prices_by_year(2016)
        self.assertEqual(got.call_args.kwargs["headers"], {"Content-Type": "application/json"})

    def test_service_down(self):
        with mock.patch(GET_BYTES, side_effect=down):
            with self.assertRaises(SourceError):
                economy.prices_by_year(2016)

    def test_the_service_refuses_or_has_no_data(self):
        refused = json.dumps({"status": "REQUEST_NOT_PROCESSED", "message": ["daily limit reached"], "Results": {}})
        empty = json.dumps({"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": [{"data": []}]}})
        for body in (refused, empty, "not json"):
            with mock.patch(GET_BYTES, return_value=body.encode()), mock.patch.object(economy, "_this_year", return_value=2026):
                with self.assertRaises(SourceError):
                    economy.prices_by_year(2016)


class FixtureSizeTests(unittest.TestCase):
    def test_fixtures_stay_small(self):
        total = sum(p.stat().st_size for p in FIXTURES.glob("econ_*"))
        self.assertLess(total, 250_000)


if __name__ == "__main__":
    unittest.main()
