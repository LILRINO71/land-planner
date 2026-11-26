"""How the local economy is doing, one public source per function.

Every function reads one real public source with no key, through landplanner/sources/fetch.py, and returns plain
numbers that can go straight into a JSON answer. Each answer names its publisher ("source") and the newest period
it covers ("as_of"). When a source does not answer, or has no row for the place asked about, the function raises
SourceError. Nothing is guessed, filled in or rounded off to look complete: a year that is only partly reported
says so (months_reported, quarters, weeks), so nobody reads it as a full year.
"""
import csv
import datetime
import io
import json
import re
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET

from ..cities import SourceError
from . import fetch

DOF_FOLDER = ("https://dof.ca.gov/media/docs/forecasting/Demographics/estimates/"
              "e-5-population-and-housing-estimates-for-cities-counties-and-the-state-2020-{year}/")
PERMITS_FILE = "https://www2.census.gov/econ/bps/Place/West%20Region/we{year}a.txt"
SALES_URL = "https://cdtfa.ca.gov/dataportal/api/odata/Taxable_Sales_by_City"
WORK_URL = "https://data.ca.gov/api/3/action/datastore_search"
WORK_YEARLY = "0d49b0b6-a012-4041-82cb-acebd0d3e8b4"
WORK_MONTHLY = "b4bc4656-7866-420f-8d87-4eda4c9996ed"
RATES_URL = "https://www.freddiemac.com/pmms/docs/PMMS_history.csv"
PRICES_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
PRICES_SERIES = "CUURS49CSA0"

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def _this_year():
    return datetime.date.today().year


def _number(value, what):
    """A whole or decimal number from a cell or field; anything missing or odd is an error, never a zero."""
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        raise SourceError(f"{what}: expected a number, got {value!r}") from None


# ---------------------------------------------------------------- population and homes (State Department of Finance)

_SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _workbook_sheets(book, wanted):
    """Rows of every sheet whose name starts with `wanted`: {sheet name: [{column letter: text}, ...]}."""
    names = book.namelist()
    shared = []
    if "xl/sharedStrings.xml" in names:
        shared = ["".join(t.text or "" for t in si.iter(_SHEET + "t"))
                  for si in ET.fromstring(book.read("xl/sharedStrings.xml"))]
    paths = {r.get("Id"): r.get("Target") for r in ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))}
    out = {}
    for sheet in ET.fromstring(book.read("xl/workbook.xml")).iter(_SHEET + "sheet"):
        name = sheet.get("name", "")
        if not name.startswith(wanted):
            continue
        target = paths[sheet.get(_REL)].lstrip("/")
        root = ET.fromstring(book.read(target if target.startswith("xl/") else "xl/" + target))
        rows = []
        for row in root.iter(_SHEET + "row"):
            cells = {}
            for c in row.findall(_SHEET + "c"):
                v = c.find(_SHEET + "v")
                if c.get("t") == "inlineStr":
                    text = "".join(t.text or "" for t in c.iter(_SHEET + "t"))
                elif v is None or v.text is None:
                    continue
                else:
                    text = shared[int(v.text)] if c.get("t") == "s" else v.text
                cells[re.sub(r"\d+", "", c.get("r", ""))] = text
            rows.append(cells)
        out[name] = rows
    return out


def _city_row(rows, place, county=None):
    """The one row for `place` (and `county`, when given) in a city table, or an error."""
    here, found = "", []
    for cells in rows:
        name = (cells.get("A") or "").strip()
        if name.endswith(" County") and "B" not in cells:
            here = name[:-len(" County")]
        elif name.lower() == place.strip().lower() and "B" in cells and (not county or here.lower() == county.lower()):
            found.append(cells)
    if not found:
        raise SourceError(f"the State Department of Finance table has no row for {place}")
    if len(found) > 1:
        raise SourceError(f"{place} is in the Department of Finance table more than once; say which county")
    return found[0]


def _homes_row(cells, year):
    """One year of the Department of Finance table, in plain words."""
    n = lambda col, what: _number(cells.get(col), f"{what} in {year}")  # noqa: E731
    return {"year": year, "people": int(n("B", "people")), "homes": int(n("E", "homes")),
            "occupied_homes": int(n("K", "occupied homes")),
            "vacancy_pct": round(n("L", "empty homes") * 100, 1),
            "single_family_homes": int(n("F", "houses") + n("G", "attached houses")),
            "multi_family_homes": int(n("H", "small apartment buildings") + n("I", "large apartment buildings")),
            "mobile_homes": int(n("J", "mobile homes")),
            "people_per_home": round(n("M", "people per home"), 2)}


def population_by_year(place, year, county=None):
    """People and homes in a city, one row per year since 2020, from the State Department of Finance's yearly
    estimates (report E-5). `year` is the newest year to try; when that year's file is not published yet the year
    before is used. Give `county` only if two cities share a name."""
    last = None
    for y in (year, year - 1):
        try:
            data = fetch.get_bytes(DOF_FOLDER.format(year=y) + f"E-5_{y}_InternetVersion.xlsx")
            break
        except SourceError as e:
            last = e
    else:
        raise last
    try:
        sheets = _workbook_sheets(zipfile.ZipFile(io.BytesIO(data)), "E5CityCounty")
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise SourceError(f"the Department of Finance file could not be read: {e}") from e
    rows = []
    for name, cells in sheets.items():
        if re.fullmatch(r"E5CityCounty(\d{4})", name):
            rows.append(_homes_row(_city_row(cells, place, county), int(name[-4:])))
    if not rows:
        raise SourceError("the Department of Finance file has no city tables")
    rows.sort(key=lambda r: r["year"])
    latest = rows[-1]["year"]
    return {"rows": rows, "date": "1 January each year (April 2020 for the census count)",
            "latest_year": latest, "as_of": f"1 January {latest}",
            "source": "California Department of Finance, population and housing estimates (report E-5)"}


# ---------------------------------------------------------------- homes permitted (Census Bureau)

def _permit_row(text, state, place_fips, year):
    """The Menifee-style row of one year's permit file, or None when the place is not in it."""
    for line in text.splitlines():
        p = line.split(",")
        if len(p) >= 29 and p[1].strip() == state and p[5].strip() == place_fips and p[0].strip() == str(year):
            n = [int(_number(x, f"permits {year}")) for x in p[17:29]]
            single, multi = n[1], n[4] + n[7] + n[10]
            return {"year": year, "homes": single + multi, "single_family": single, "multi_family": multi,
                    "months_reported": int(_number(p[15], f"months reported {year}"))}, p[16].strip()
    return None, ""


def permits_by_year(place_fips, first_year, last_year):
    """Homes the city allowed to be built each year, from the Census Bureau's Building Permits Survey.
    `place_fips` is the 5-digit place code ("46842"), or the 7 digits with the state in front ("0646842");
    a plain 5-digit code means California. A year whose file cannot be read, or has no row for the place, is
    skipped and listed in "missing_years". A year with fewer than 12 months_reported is not a full year."""
    code = str(place_fips).strip()
    state, place = (code[:2], code[2:]) if len(code) == 7 else ("06", code.zfill(5))
    rows, missing, name = [], [], ""
    for year in range(first_year, last_year + 1):
        try:
            text = fetch.get_text(PERMITS_FILE.format(year=year), encoding="latin-1")
        except SourceError:
            missing.append(year)
            continue
        row, found = _permit_row(text, state, place, year)
        if row is None:
            missing.append(year)
            continue
        rows.append(row)
        name = name or found
    if not rows:
        raise SourceError(f"no building permit file answered with a row for place {place} ({first_year} to {last_year})")
    return {"rows": rows, "place": name, "missing_years": missing, "as_of": str(rows[-1]["year"]),
            "source": "U.S. Census Bureau, Building Permits Survey (yearly, by city)"}


# ---------------------------------------------------------------- shop and restaurant sales (State tax agency)

def shop_sales_by_year(place):
    """Taxable sales in shops and restaurants in a city, added up by year from the quarterly figures of the
    California Department of Tax and Fee Administration. "quarters" is how many of the four quarters are in a
    year's total; under 4 means the year is not finished (or a quarter was withheld)."""
    name = "'" + place.strip().replace("'", "''") + "'"
    query = ("?$filter=" + urllib.parse.quote("City eq " + name)
             + "&$orderby=" + urllib.parse.quote("CalendarYear desc,Quarter desc") + "&$top=200")
    answer = fetch.get_json(SALES_URL + query)
    try:
        found = answer["value"]
        counties = {r["County"] for r in found}
        quarters = [(int(r["CalendarYear"]), int(str(r["Quarter"]).lstrip("Qq")),
                     r["RetailandFoodServicesTaxableTransactions"]) for r in found]
    except (KeyError, TypeError, ValueError):
        raise SourceError("the tax agency's sales answer was not in the expected form") from None
    quarters = [q for q in quarters if q[2] is not None]
    if not quarters:
        raise SourceError(f"the tax agency has no sales figures for {place}")
    if len(counties) > 1:
        raise SourceError(f"{place} matches cities in more than one county ({', '.join(sorted(counties))})")
    years = {}
    for year, _, sales in quarters:
        total, count = years.get(year, (0, 0))
        years[year] = (total + sales, count + 1)
    year, quarter, sales = max(quarters)
    return {"rows": [{"year": y, "sales_usd": int(round(t)), "quarters": c} for y, (t, c) in sorted(years.items())],
            "latest_quarter": {"year": year, "quarter": quarter, "sales_usd": int(round(sales))},
            "as_of": f"{year} Q{quarter}", "county": next(iter(counties)),
            "source": "California Department of Tax and Fee Administration, taxable sales by city"}


# ---------------------------------------------------------------- jobs (State Employment Development Department)

def _work_records(resource, area, extra=None):
    """Rows of one State Employment Development Department table for one area, as the data portal gives them."""
    filters = {"Area Name": area, **(extra or {})}
    answer = fetch.get_json(WORK_URL, {"resource_id": resource, "filters": json.dumps(filters),
                                       "limit": 40, "sort": "Year desc"})
    if not isinstance(answer, dict) or not answer.get("success"):
        raise SourceError("the data portal did not give the jobs figures")
    return answer.get("result", {}).get("records", [])


def _work_row(r):
    """One record as plain numbers, or None when a figure is blank (a blank is never turned into zero)."""
    fields = (r.get("Labor Force"), r.get("Employment"), r.get("Unemployment Rate"))
    if any(f is None for f in fields):
        return None
    return {"year": int(r["Year"]), "labour_force": int(fields[0]), "employed": int(fields[1]),
            "unemployment_pct": float(fields[2])}


def _yearly(area):
    rows = [x for x in map(_work_row, _work_records(WORK_YEARLY, area)) if x]
    return sorted(rows, key=lambda x: x["year"])


def _latest_month(area):
    """The newest month with figures for the area (this year's or last year's), or None if neither has any."""
    for year in (_this_year(), _this_year() - 1):
        recs = [r for r in _work_records(WORK_MONTHLY, area, {"Year": year}) if _work_row(r)]
        if recs:
            r = max(recs, key=lambda r: int(str(r["Date_Numeric"]).split("/")[0]))
            month = int(str(r["Date_Numeric"]).split("/")[0])
            return {**_work_row(r), "month": MONTHS[month - 1], "month_number": month,
                    "status": r.get("Status")}
    return None


def work_by_year(place, county):
    """Workers and unemployment in a city and its county, by year, with the newest month when it is out. Reads the
    State Employment Development Department's local figures on data.ca.gov. The yearly figures for the city must
    answer; if only the monthly ones do not, "latest_month" is None and "latest_month_note" says so."""
    rows = _yearly(f"{place.strip()} City")
    if not rows:
        raise SourceError(f"the State Employment Development Department has no job figures for {place}")
    county_name = county.strip()
    county_rows = _yearly(county_name if county_name.endswith(" County") else county_name + " County")
    note, month = None, None
    try:
        month = _latest_month(f"{place.strip()} City")
        if month is None:
            note = "no monthly figures are published yet"
    except SourceError:
        note = "the monthly figures did not answer"
    latest = month or rows[-1]
    return {"rows": rows, "county_rows": county_rows, "latest_month": month, "latest_month_note": note,
            "as_of": f"{month['month']} {month['year']}" if month else f"{latest['year']} (yearly)",
            "source": "California Employment Development Department, local area unemployment statistics"}


# ---------------------------------------------------------------- mortgage rates (Freddie Mac)

def mortgage_rates():
    """The usual 30-year home loan rate by year (the average of that year's weekly rates, last 12 years, the
    newest year being partly done: see "weeks"), plus the newest weekly rate, from Freddie Mac's weekly survey."""
    reader = csv.reader(io.StringIO(fetch.get_text(RATES_URL)))
    head = [h.strip().lower() for h in next(reader, [])]
    if "date" not in head or "pmms30" not in head:
        raise SourceError("the Freddie Mac file does not have the columns date and pmms30")
    d, r = head.index("date"), head.index("pmms30")
    weekly = []
    for line in reader:
        try:
            month, day, year = (int(x) for x in line[d].strip().split("/"))
            weekly.append((datetime.date(year, month, day), float(line[r])))
        except (ValueError, IndexError):
            continue          # a week with no rate is left out, not turned into zero
    if not weekly:
        raise SourceError("the Freddie Mac file has no weekly rates")
    by_year = {}
    for day, rate in weekly:
        by_year.setdefault(day.year, []).append(rate)
    last = max(by_year)
    rows = [{"year": y, "rate_pct": round(sum(v) / len(v), 2), "weeks": len(v)}
            for y, v in sorted(by_year.items()) if y > last - 12]
    day, rate = max(weekly)
    return {"rows": rows, "latest": {"date": day.isoformat(), "rate_pct": rate}, "as_of": day.isoformat(),
            "source": "Freddie Mac, Primary Mortgage Market Survey (30-year fixed rate, weekly)"}


# ---------------------------------------------------------------- prices (Bureau of Labor Statistics)

def _price_points(first, last):
    """Every published reading of the series from year `first` to `last`, asked for in blocks of at most 10 years."""
    points = []
    for start in range(first, last + 1, 10):
        body = json.dumps({"seriesid": [PRICES_SERIES], "startyear": str(start),
                           "endyear": str(min(start + 9, last))}).encode()
        raw = fetch.get_bytes(PRICES_URL, data=body, headers={"Content-Type": "application/json"})
        try:
            answer = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            raise SourceError("the Bureau of Labor Statistics answer was not readable") from None
        if answer.get("status") != "REQUEST_SUCCEEDED":
            raise SourceError("the Bureau of Labor Statistics did not answer: " + "; ".join(answer.get("message") or ["no reason given"]))
        try:
            for record in answer["Results"]["series"][0]["data"]:
                match = re.fullmatch(r"M(0[1-9]|1[0-2])", record["period"])
                if match and record["value"] not in ("-", ""):
                    points.append((int(record["year"]), int(match.group(1)), float(record["value"])))
        except (KeyError, IndexError, TypeError, ValueError):
            raise SourceError("the Bureau of Labor Statistics answer was not in the expected form") from None
    return points


def prices_by_year(first_year):
    """How much everyday prices rose in the Riverside area each year, from the Bureau of Labor Statistics'
    consumer price index (all items). The yearly figure is the average of that year's readings; only years that
    run from January or February to November or December are listed. "change_pct" compares with the year before
    and is None when that year is not complete. "latest" is the newest reading on its own."""
    points = _price_points(first_year - 1, _this_year())
    if not points:
        raise SourceError("the Bureau of Labor Statistics has no price readings for this area")
    by_year = {}
    for year, month, value in points:
        by_year.setdefault(year, {})[month] = value
    average = {y: sum(m.values()) / len(m) for y, m in by_year.items() if min(m) <= 2 and max(m) >= 11}
    rows = []
    for y in sorted(average):
        if y >= first_year:
            before = average.get(y - 1)
            rows.append({"year": y, "index": round(average[y], 1),
                         "change_pct": round((average[y] / before - 1) * 100, 1) if before else None})
    year, month, value = max(points)
    ago = dict(((y, m), v) for y, m, v in points).get((year - 1, month))
    return {"rows": rows, "area": "Riverside area, California", "as_of": f"{MONTHS[month - 1]} {year}",
            "latest": {"year": year, "month": MONTHS[month - 1], "index": value,
                       "change_pct": round((value / ago - 1) * 100, 1) if ago else None},
            "source": "U.S. Bureau of Labor Statistics, Consumer Price Index (all items, not seasonally adjusted)"}
