"""The state's housing target for a California city, and how far the city has come toward it.

Every California city is given a number of homes it must plan for in the current eight-year period (the sixth
cycle of the Regional Housing Needs Allocation, "RHNA"), split by income level. Each year the city reports to the
state's Department of Housing and Community Development (HCD) how many homes it gave building permits to. HCD
publishes both on data.ca.gov, and this file reads them through landplanner/sources/fetch.py with no key:

  * "RHNA Progress Report, 6th cycle": one row per city with the target and the permits counted so far,
    by income level (the state's own count, and the only place the target is published as data).
  * "Housing Element Annual Progress Report (APR) Data by Jurisdiction and Year", table A2: one row per project,
    added up here by year with the data portal's own SQL so only a few rows come back.

When a source does not answer, or has no row for the place, the function raises SourceError. A blank or
unreadable cell is left as None and left out of any sum; it is never turned into zero, and "notes" says what was
missing.
"""
import json
import math
import re

from ..cities import SourceError
from . import fetch

SQL_URL = "https://data.ca.gov/api/3/action/datastore_search_sql"
SEARCH_URL = "https://data.ca.gov/api/3/action/datastore_search"
RESOURCE_URL = "https://data.ca.gov/api/3/action/resource_show"
PROGRESS = "1e80a9cf-724c-432d-8374-e9708a6a92dc"      # "6th Cycle RHNA Progress Report", one row per city
PERMITS = "fe505d9b-8c36-42ba-ba30-08bc4f34e022"       # "APR Table A2", one row per project and year
CYCLE = "6th"
SOURCE = ("California Department of Housing and Community Development, 6th Cycle RHNA Progress Report and "
          "Housing Element Annual Progress Report data by jurisdiction and year (Table A2), on data.ca.gov")

# (our key, words for notes, the progress table's target field, its permits field)
LEVELS = (("very_low", "very low-income", "RHNA VLI", "VLI UNITS"),
          ("low", "low-income", "RHNA LI", "LI UNITS"),
          ("moderate", "moderate-income", "RHNA MOD", "MOD UNITS"),
          ("above_moderate", "above moderate-income", "RHNA ABOVE MOD", "ABOVE MOD UNITS"))
KEYS = tuple(k for k, *_ in LEVELS)

# the Table A2 columns that count permits for each level (the state counts acutely and extremely low-income
# homes inside "very low"); the two endings are deed-restricted and not
_PERMIT_COLUMNS = {"very_low": ["BP_ACUTELY_LOW_INCOME_DR", "BP_ACUTELY_LOW_INCOME_NDR",
                                "BP_EXTREMELY_LOW_INCOME_DR", "BP_EXTREMELY_LOW_INCOME_NDR",
                                "BP_VLOW_INCOME_DR", "BP_VLOW_INCOME_NDR"],
                   "low": ["BP_LOW_INCOME_DR", "BP_LOW_INCOME_NDR"],
                   "moderate": ["BP_MOD_INCOME_DR", "BP_MOD_INCOME_NDR"],
                   "above_moderate": ["BP_ABOVE_MOD_INCOME"]}
_ALL_COLUMNS = [c for cols in _PERMIT_COLUMNS.values() for c in cols]


def _count(value):
    """A whole number from a cell (a number, or text like "1,761"), or None when it is blank or not a number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    if not math.isfinite(x) or x < 0 or x != int(x):
        return None
    return int(x)


def _cell(value, what, notes):
    """`_count`, and a line in `notes` when a cell that should hold a number does not."""
    n = _count(value)
    if n is None:
        blank = value is None or not str(value).strip()
        notes.append(f"{what} was blank in the source" if blank else f"{what} was not a number ({value!r}) and is left out")
    return n


def _sum(parts):
    """The sum of the parts that are known, or None when none is."""
    known = [p for p in parts if p is not None]
    return sum(known) if known else None


def _names(place):
    """The spellings to look for in the state's tables (which write names in capitals, "MENIFEE"), best first."""
    name = re.sub(r"[.]", "", " ".join(str(place or "").split())).upper()
    name = re.sub(r"^(CITY|TOWN) OF ", "", name)
    out = [name]
    short = re.sub(r" (CITY|TOWN)$", "", name)
    if short != name:
        out.append(short)                  # "MENIFEE CITY" -> "MENIFEE", but "CULVER CITY" is tried first as it is
    if not name:
        raise SourceError("no place name was given")
    return out


def _one_row(records, names, place):
    """The one progress row for the place: the best-spelled match, with identical repeats collapsed."""
    for name in names:
        found = [r for r in records if isinstance(r, dict) and str(r.get("Jurisdiction", "")).strip().upper() == name]
        unique = []
        for r in found:
            body = {k: v for k, v in r.items() if k != "_id"}
            if body not in [{k: v for k, v in u.items() if k != "_id"} for u in unique]:
                unique.append(r)
        if len(unique) > 1:
            raise SourceError(f"the state's progress table has {len(unique)} different rows for {place}")
        if unique:
            return unique[0]
    raise SourceError(f"the state's progress table has no row for {place}")


def _years(text, notes):
    """(first year, last year) of a period written "10/15/2021 - 10/15/2029", or (None, None)."""
    dates = re.findall(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(text or ""))
    if len(dates) < 2:
        notes.append("the planning period was not given in a form that can be read")
        return None, None
    return int(dates[0][2]), int(dates[-1][2])


def _block(values, notes=None, what=""):
    """{"very_low": n, ..., "total": n} from four level values; the total leaves out any that are None."""
    out = {k: values.get(k) for k in KEYS}
    out["total"] = _sum(out.values())
    if notes is not None and out["total"] is not None and any(out[k] is None for k in KEYS):
        notes.append(f"the {what} total leaves out the levels that were missing")
    return out


def _left(target, permitted):
    """Homes still to go at each level (never below zero: extra homes at one level do not cover another)."""
    if target is None:
        return None
    out = {k: (None if target[k] is None or permitted[k] is None else max(target[k] - permitted[k], 0)) for k in KEYS}
    out["total"] = _sum(out[k] for k in KEYS)
    return out


def _share(target, permitted):
    """How much of the target the permits cover, in percent, per level; None where the target is missing or zero."""
    if target is None:
        return None
    out = {}
    for k in KEYS + ("total",):
        t, p = target[k], permitted[k]
        out[k] = round(p / t * 100, 1) if t and p is not None else None
    if any(target[k] is None or permitted[k] is None for k in KEYS):
        out["total"] = None                # a total over only some of the levels would not be comparable
    return out


def _yearly_sql(name, first_year):
    quoted = name.replace("'", "''")
    sums = ", ".join(f'SUM("{c}") AS "{c}"' for c in _ALL_COLUMNS)
    return (f'SELECT "YEAR" AS year, MIN("CNTY_NAME") AS county, COUNT(*) AS projects, {sums} FROM "{PERMITS}" '
            f"WHERE \"JURIS_NAME\" = '{quoted}' AND \"YEAR\" >= {int(first_year)} GROUP BY \"YEAR\" ORDER BY \"YEAR\"")


def _by_year(name, first_year, notes):
    """(rows, county named by the state) of permits per report year since the cycle began. Rows are the state's
    yearly reports added up: a project can be listed in later years too, but only its permits are counted."""
    answer = fetch.get_json(SQL_URL, {"sql": _yearly_sql(name, first_year)}, timeout=60)     # adds up ~1M project rows
    try:
        if not answer["success"]:
            raise KeyError
        records = answer["result"]["records"]
        if not isinstance(records, list):
            raise TypeError
    except (KeyError, TypeError):
        raise SourceError("the data portal did not give the yearly permit figures") from None
    years, county = {}, ""
    for r in records:
        year = _count(r.get("year"))
        if year is None:
            continue
        county = county or str(r.get("county") or "").strip()
        body = {k: v for k, v in r.items()}
        if year in years and years[year] != body:
            raise SourceError(f"the state's yearly permit figures list {year} twice with different numbers")
        years[year] = body
    rows = []
    for year in sorted(years):
        r = years[year]
        levels = {}
        for key, words, *_ in LEVELS:
            parts = [_count(r.get(c)) for c in _PERMIT_COLUMNS[key]]
            levels[key] = _sum(parts)
            if levels[key] is None:
                notes.append(f"{year}: the {words} permits were blank in the state's yearly report")
            elif None in parts and len(parts) > 1:
                notes.append(f"{year}: part of the {words} permits was not a number and is left out")
        rows.append({"year": year, **_block(levels)})
    return rows, county


def _updated(notes):
    """The day the state last updated the progress table (2026-11-20), or "" when the portal does not say."""
    try:
        answer = fetch.get_json(RESOURCE_URL, {"id": PROGRESS})
        stamp = str(answer["result"]["last_modified"] or "")
    except (SourceError, KeyError, TypeError, AttributeError):
        stamp = ""
    day = re.match(r"\d{4}-\d{2}-\d{2}", stamp)
    if not day:
        notes.append("the data portal did not say when the table was last updated")
        return ""
    return day.group(0)


def housing_target(place, county=None):
    """The state's housing target for a city in this eight-year cycle, the homes permitted toward it so far, and
    the permits by year. Both come from the Department of Housing and Community Development on data.ca.gov.

    "target" and "permitted" are the state's own figures per income level ("very_low" includes extremely and
    acutely low), with a "total" that leaves out any level the state left blank. "left" is what is still to go
    at each level, never below zero. "share_pct" is how much of each target the permits cover. "by_year" adds up
    the city's yearly reports from the year the cycle began; its first year can include permits issued before the
    cycle began, so the rows need not add up to "permitted", which the state counts itself (a note says when they
    differ). If the yearly figures do not answer, "by_year" is empty and "notes" says so. Give `county` ("Riverside")
    to check that the name is the city you mean; the state's table has no county for a city on its own."""
    names = _names(place)
    answer = fetch.get_json(SEARCH_URL, {"resource_id": PROGRESS, "limit": 20,
                                         "filters": json.dumps({"Jurisdiction": names})})
    try:
        if not answer["success"]:
            raise KeyError
        records = answer["result"]["records"]
        if not isinstance(records, list):
            raise TypeError
    except (KeyError, TypeError):
        raise SourceError("the data portal did not give the housing target") from None
    row = _one_row(records, names, place)
    notes = []
    from_year, to_year = _years(row.get("Planning Period"), notes)
    target = _block({k: _cell(row.get(t), f"the {words} target", notes) for k, words, t, _ in LEVELS}, notes, "target")
    permitted = _block({k: _cell(row.get(p), f"the {words} permits counted", notes) for k, words, _, p in LEVELS},
                       notes, "permitted")
    if target["total"] is None:
        target = None
        notes.append("the state gave no target for this city")
    by_year, through_year, found_county = [], None, ""
    if from_year is not None:
        try:
            by_year, found_county = _by_year(str(row["Jurisdiction"]).strip(), from_year, notes)
        except SourceError as e:
            notes.append(f"the yearly permit figures did not answer ({e})"[:200])
    if by_year:
        through_year = by_year[-1]["year"]
    else:
        notes.append("no yearly permit reports were found for this city in this cycle")
    if county and found_county and found_county.lower().removesuffix(" county") != str(county).strip().lower().removesuffix(" county"):
        raise SourceError(f"{place} in the state's tables is in {found_county} County, not {county}")
    if county and not found_county:
        notes.append(f"the county ({county}) could not be checked against the state's tables")
    if by_year and any(_sum(r[k] for r in by_year) not in (None, permitted[k]) and permitted[k] is not None for k in KEYS):
        notes.append("the yearly rows do not add up to the state's own count of permits for the cycle, because the state "
                     "starts counting on its own date and the first year can include earlier permits; use the state's total "
                     "for progress")
    updated = _updated(notes)
    as_of = (f"annual reports through {through_year}" if through_year else "no annual report found") \
        + (f"; table updated {updated}" if updated else "")
    return {"cycle": CYCLE, "from_year": from_year, "to_year": to_year,
            "planning_period": str(row.get("Planning Period") or "").strip() or None,
            "jurisdiction": str(row["Jurisdiction"]).strip(),
            "target": target, "permitted": permitted, "by_year": by_year,
            "left": _left(target, permitted), "share_pct": _share(target, permitted),
            "through_year": through_year, "notes": list(dict.fromkeys(notes)),
            "source": SOURCE, "as_of": as_of}

