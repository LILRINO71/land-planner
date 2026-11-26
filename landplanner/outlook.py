"""The wider picture around a site, and what has to be done: the city's economy by year, the weather and how it
is changing, hazards and limits on building, what is close by, the typical resident, and a checklist of steps.

Like forecast.py this is plain arithmetic on facts other modules read (landplanner/sources). It invents nothing:
a block whose source did not answer is marked not available, and every sentence carries the figure it rests on.
The checklist is a starting list drawn from those facts by simple rules. The city decides what it requires.
"""
import re

from .forecast import HORIZON, SCENARIOS, money, yearly
from .sources.place import paleo_words
from .words import counted

ECONOMY_PARTS = ("population", "permits", "sales", "work", "borrowing", "prices")
CITY_PARTS = ECONOMY_PARTS + ("housing",)       # asked once for the whole city: the economy, and the state housing target
PLACE_PARTS = ("climate", "hazards", "nearby", "residents")
BIG_SITE_ACRES = 10        # the state's quick exemption for infill sites stops at 5 acres; at twice that the review is certain
WET_ZONE = re.compile(r"[AV](E|H|O|R|\d{1,2}(-\d{1,2})?)?")   # FEMA zones A, AE, AH, AO, AR, A99, A1-30, V, VE...: land a 1-in-100-year flood covers
NOT_MAPPED_ZONES = ("AREA NOT INCLUDED",)                       # FEMA's word for land its flood map leaves out (not a flood zone)
MONTHS = {"Jan": "January", "Feb": "February", "Mar": "March", "Apr": "April", "Jun": "June", "Jul": "July", "Aug": "August",
          "Sep": "September", "Oct": "October", "Nov": "November", "Dec": "December"}


def _rows(part):
    return {r["year"]: r for r in (part or {}).get("rows") or [] if r.get("year") is not None}


def _avg(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _and(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _zone_codes(zones):
    """The flood zone codes in a list of zones, each once, in order: "AE (high hazard)" and "AE" are the same zone."""
    out = []
    for z in zones:
        code = str(z).split(" (")[0].strip() if z is not None else ""
        if code and code.lower() != "none" and code.upper() not in {c.upper() for c in out}:
            out.append(code)
    return out


def _is_wet_zone(code):
    return bool(WET_ZONE.fullmatch(code.upper()))


def economy(parts, forecast, place_name):
    """The city's measured record by year, side by side, what it says in words, and shop sales carried forward
    with the forecast's three growth lines (in today's prices)."""
    people, permits, sales, work = _rows(parts.get("population")), _rows(parts.get("permits")), _rows(parts.get("sales")), _rows(parts.get("work"))
    rates, prices = _rows(parts.get("borrowing")), _rows(parts.get("prices"))
    answered = [p for p in ECONOMY_PARTS if parts.get(p)]
    if not answered:
        return {"available": False, "did_not_answer": list(ECONOMY_PARTS)}
    years = sorted(set(people) | set(permits) | set(sales) | set(work))[-9:]
    rows = []
    for y in years:
        s = sales.get(y) or {}
        full = s.get("quarters", 4) == 4
        homes = (people.get(y) or {}).get("occupied_homes") or (people.get(y) or {}).get("homes")
        rows.append({"year": y, "people": (people.get(y) or {}).get("people"), "homes": (people.get(y) or {}).get("homes"),
                     "homes_permitted": (permits.get(y) or {}).get("homes"),
                     "permit_months": (permits.get(y) or {}).get("months_reported"),
                     "shop_sales_usd": s.get("sales_usd"), "sales_quarters": s.get("quarters"),
                     "sales_per_home_usd": round(s["sales_usd"] / homes, -2) if full and s.get("sales_usd") and homes else None,
                     "unemployment_pct": (work.get(y) or {}).get("unemployment_pct"),
                     "labour_force": (work.get(y) or {}).get("labour_force"),
                     "mortgage_pct": (rates.get(y) or {}).get("rate_pct"),
                     "mortgage_weeks": (rates.get(y) or {}).get("weeks"),
                     "prices_change_pct": (prices.get(y) or {}).get("change_pct")})
    facts = []
    if len(people) >= 2:
        a, b = people[min(people)], people[max(people)]
        r = yearly(a.get("people"), b.get("people"), max(people) - min(people))
        if r is not None:
            rate = round(100 * abs(r), 1)
            move = ("about the same from one year to the next" if rate == 0
                    else f"{rate:.1f}% {'more' if r > 0 else 'fewer'} each year")
            facts.append(f"{place_name} had {a['people']:,} people in {min(people)} and {b['people']:,} in {max(people)}: {move}."
                         + (f" Homes went from {a['homes']:,} to {b['homes']:,}." if a.get("homes") is not None and b.get("homes") is not None else ""))
    # a permit year counts as whole only when all 12 months were reported; a year with no month reported (0) is not a whole year
    # (a year whose months_reported is missing altogether is taken as whole, as the source gives no partial-year marker then)
    whole = [r for r in permits.values() if (12 if r.get("months_reported") is None else r["months_reported"]) >= 12 and r.get("homes") is not None]
    if whole:
        recent = sorted(whole, key=lambda r: r["year"])[-5:]
        multi = _avg([100 * r["multi_family"] / r["homes"] for r in recent if r.get("homes") and r.get("multi_family") is not None])
        facts.append(f"Builders took out permits for about {round(_avg([r['homes'] for r in recent]), -1):,.0f} homes a year in "
                     f"{place_name} from {recent[0]['year']} to {recent[-1]['year']}"
                     + (f"; about {multi:.0f}% of them apartments and other attached homes." if multi is not None else "."))
    full = sorted((r for r in sales.values() if r.get("quarters", 4) == 4 and r.get("sales_usd") and r["year"] in years),
                  key=lambda r: r["year"])
    priced = [r for r in full if (prices.get(r["year"]) or {}).get("index")]
    if len(priced) >= 2:
        full = priced
    measured_per_home = None
    if len(full) >= 2:
        a, b = full[0], full[-1]
        words = (f"Shops and restaurants in {place_name} took in {money(b['sales_usd'] / 1e6)} million in {b['year']}, "
                 f"up from {money(a['sales_usd'] / 1e6)} million in {a['year']}")
        pa, pb = (prices.get(a["year"]) or {}).get("index"), (prices.get(b["year"]) or {}).get("index")
        if pa and pb:
            real = b["sales_usd"] / a["sales_usd"] / (pb / pa) - 1
            words += f". Prices rose {100 * (pb / pa - 1):.0f}% in that time, so the real gain is about {100 * real:.0f}%"
        facts.append(words + ".")
        last = next((r for r in reversed(rows) if r["sales_per_home_usd"]), None)
        if last:
            measured_per_home = last["sales_per_home_usd"]
            facts.append(f"That is about {money(measured_per_home)} of shop and restaurant sales for each household in {last['year']} "
                         "(measured: everything sold in the city, to residents and visitors).")
    if work:
        b = work[max(work)]
        county = _rows({"rows": (parts.get("work") or {}).get("county_rows")}).get(max(work)) or {}
        if b.get("unemployment_pct") is not None:
            facts.append(f"Unemployment in {place_name} was {b['unemployment_pct']:g}% in {max(work)}"
                         + (f" (the county: {county['unemployment_pct']:g}%)" if county.get("unemployment_pct") is not None else "")
                         + (f", with {b['labour_force']:,.0f} residents working or looking for work." if b.get("labour_force") else "."))
    if rates:
        latest = (parts.get("borrowing") or {}).get("latest") or {}
        low = min(rates.values(), key=lambda r: r["rate_pct"])
        part_year = (rates[max(rates)].get("weeks") or 52) < 50
        facts.append(f"A 30-year home loan cost {rates[max(rates)]['rate_pct']:g}% on average "
                     f"{'so far in' if part_year else 'in'} {max(rates)}"
                     + (f" ({latest['rate_pct']:g}% in the latest week)" if latest.get("rate_pct") is not None else "")
                     + f"; the low of the last years was {low['rate_pct']:g}% in {low['year']}. Dearer loans slow home sales, "
                       "which is why building comes in waves.")
    # shop sales ahead: this year's sales per home, times the homes the forecast expects in the city's market ring
    ahead, ahead_note, gap = [], None, ""
    ring = next((r for r in forecast.get("rings") or [] if r.get("miles") == max(x["miles"] for x in forecast["rings"]) and r.get("rows")), None) \
        if forecast.get("rings") else None
    if full and ring:
        base_sales, base_year = full[-1]["sales_usd"], full[-1]["year"]
        at = {r["year"]: r["homes"] for r in ring["rows"] if isinstance(r.get("homes"), dict)}
        # the sales are grown from the homes of the year they were measured in. When the forecast has no count for that year
        # (its rows begin later), the first year it does count is the start, and the basis says so: homes that grew in between
        # are not in the figures, so they may run low
        start_year = base_year if at.get(base_year) else forecast["year"] if at.get(forecast["year"]) else min(at, default=None)
        start = at.get(start_year) or {}
        if not all(isinstance(start.get(s), (int, float)) and start[s] > 0 for s in SCENARIOS):
            ahead_note = (f"Shop sales ahead are left out: the forecast counts no homes near the site in {start_year or base_year}, "
                          "so there is nothing to grow the sales from.")
        else:
            if start_year != base_year:
                gap = (f" The forecast counts homes from {start_year}, not from {base_year}, the year of these sales, so any growth in "
                       "homes between the two years is not in the figures and they may run low.")
            for y in forecast["years"][2:]:
                homes = at.get(y) or {}
                if all(isinstance(homes.get(s), (int, float)) for s in SCENARIOS):
                    ahead.append({"year": y, "shop_sales_usd": {s: round(base_sales * homes[s] / start[s], -5) for s in SCENARIOS}})
    return {"available": True, "place": place_name, "rows": rows, "facts": facts, "sales_ahead": ahead,
            "sales_ahead_note": ahead_note,
            "sales_ahead_basis": ("The city's last full year of shop and restaurant sales, grown with the homes the forecast "
                                  f"expects within {ring['miles']} miles. Today's prices; no inflation added." + gap) if ahead else None,
            "measured_sales_per_home_usd": measured_per_home,
            "sources": [{"name": p, "source": (parts.get(p) or {}).get("source"), "answered": bool(parts.get(p))} for p in ECONOMY_PARTS],
            "did_not_answer": [p for p in ECONOMY_PARTS if not parts.get(p)]}


def climate(part, year):
    """The weather as measured, and where the measured trend points if it simply continues."""
    if not part:
        return {"available": False}
    out = {"available": True, **part, "facts": []}
    t, trend = part.get("typical_year") or {}, part.get("trend") or {}
    months = part.get("months") or []
    if t.get("mean_f") is not None:
        hot = max(months, key=lambda m: m.get("high_f") or -99) if months else None
        rain = f" with about {t['rain_in']:.1f} inches of rain" if t.get("rain_in") is not None else ""
        out["facts"].append(f"A typical year averages {t['mean_f']:.0f} degrees F{rain}"
                            + (f"; the hottest month is {MONTHS.get(hot['month'], hot['month'])}, with afternoons around {hot['high_f']:.0f} degrees." if hot and hot.get("high_f") else "."))
    if trend.get("mean_f_per_decade") is not None:
        ten = trend["mean_f_per_decade"] * HORIZON / 10
        out["ahead"] = {"year": year + HORIZON, "mean_f_change": round(ten, 1),
                        "basis": f"The straight-line trend of the yearly averages from {trend.get('from_year')} to {trend.get('to_year')}, carried on."}
        out["facts"].append(f"The yearly average has moved {trend['mean_f_per_decade']:+.1f} degrees F each ten years since {trend.get('from_year')}. "
                            f"If that simply continues, {year + HORIZON} is about {ten:+.1f} degrees from today: more cooling load, more shade "
                            "and water-wise planting to plan for.")
    if trend.get("rain_in_per_decade") is not None and t.get("rain_in") is not None:
        out["facts"].append(f"Rain has moved {trend['rain_in_per_decade']:+.1f} inches each ten years; it swings far more from year to year "
                            "than that trend, so drainage is sized for the wet years, not the average.")
    return out


def hazards(part):
    """Each hazard as a finding: "clear", "note" (know about it) or "work" (it adds a study or a cost)."""
    if not part:
        return {"available": False}
    found = []

    def add(topic, level, text, source):
        found.append({"topic": topic, "level": level, "text": text, "source": source})

    flood = part.get("flood")
    if flood:
        # the point's zone and the site's zones (place.py labels these "AE (high hazard)"): each zone once, by its code
        codes = _zone_codes([flood.get("zone")] + list(flood.get("zones_on_site") or []))
        wet_codes = [c for c in codes if _is_wet_zone(c)]
        wet = bool(flood.get("special_hazard_area")) or bool(wet_codes)
        mapped = [c for c in codes if c.upper() not in NOT_MAPPED_ZONES]
        panel = (f" Map panel {flood['panel']}, in force since {flood['effective']}." if flood.get("panel") and flood.get("effective") else "")
        if wet:
            shown = wet_codes or mapped
            where = f"FEMA flood zone{'s' if len(shown) > 1 else ''} {_and(shown)}" if shown else "a FEMA special flood hazard area"
            add("Flood", "work", f"Part of the site is in {where}: building there needs a flood study and raised pads." + panel,
                "FEMA National Flood Hazard Layer")
        elif mapped:
            meaning = str(flood.get("meaning") or "outside the mapped flood areas").strip().rstrip(".").lower()
            at_point = flood.get("zone") and str(flood["zone"]).strip().upper() not in NOT_MAPPED_ZONES
            lead = f"FEMA flood zone {mapped[0]}" + ("" if at_point else " on the site")
            add("Flood", "clear", f"{lead}, {meaning}." + panel, "FEMA National Flood Hazard Layer")
        else:
            # no zone at all: FEMA has published no flood map here (or leaves the area out of it). That is "not known", not "no risk"
            meaning = str(flood.get("meaning") or "").strip() if not flood.get("zone") else ""
            meaning = meaning or ("FEMA's flood map leaves this spot out, so it names no flood zone for it." if flood.get("zone")
                                  else "FEMA has not published a flood map for this spot.")
            add("Flood", "note", (meaning if meaning.endswith(".") else meaning + ".") + panel, "FEMA National Flood Hazard Layer")
    fire = part.get("fire")
    if fire:
        levels = [x for x in ([fire.get("level")] + list(fire.get("levels_on_site") or [])) if x]
        order = ("Very High", "High", "Moderate")
        worst = next((w for w in order if w in levels), None)
        here = fire.get("level") if fire.get("level") in order else None
        others = [w for w in order if w in levels and w != here]
        add("Wildfire", "work" if worst in ("Very High", "High") else "note" if worst else "clear",
            (f"The {fire.get('map_year') or 'current'} fire hazard map puts "
             + (f"the middle of the site in a {here} zone" if here else f"land within the site's bounds in a {worst} zone")
             + (f"; land within its bounds is also mapped {' and '.join(others)}" if here and others else "")
             + ". That brings fire-resistant building rules, cleared space around buildings and a close look at ways out."
             if worst else "The site is outside the mapped fire hazard zones."), "City fire hazard severity map")
    service = part.get("fire_service")
    if service and service.get("in_coverage_gap"):
        near, planned = service.get("nearest_station") or {}, service.get("planned_station")
        add("Fire service", "note",
            "The site is in an area the city maps as a gap in fire station coverage"
            + (f"; the nearest station is {near['name']}, {counted(near['miles_away'], 'mile')} away" if near.get("name") else "")
            + (f". A new station is planned {counted(planned.get('miles_away'), 'mile')} away ({planned.get('name')})." if planned and planned.get("miles_away") is not None else "."),
            "City fire coverage maps")
    faults = part.get("faults")
    if faults:
        add("Earthquake faults", "work" if faults.get("in_fault_zone") else "clear",
            "The site is inside a state earthquake fault zone: a fault study is required before building."
            if faults.get("in_fault_zone") else
            (f"No mapped fault zone on the site; the nearest mapped fault is {counted(faults['nearest_miles'], 'mile')} away."
             if faults.get("nearest_miles") is not None else
             f"No mapped fault or fault zone within {counted(faults.get('searched_miles', 3), 'mile')}."), "California Geological Survey")
    ground = part.get("ground")
    if ground:
        unmapped = "not mapped" in str(ground.get("liquefaction") or "")
        inside = "in a mapped zone" in (str(ground.get("liquefaction")), str(ground.get("landslide")))
        add("Soft ground and slides", "work" if inside else "note" if unmapped else "clear",
            "The site is in a zone the state maps for soft ground in an earthquake or for landslides: the soils report must answer it."
            if inside else "The state has not mapped this area for soft ground in an earthquake. A soils report settles it; "
                           "one is needed for the subdivision map in any case." if unmapped else
            "Outside the state's mapped zones for soft ground and landslides.", "California Geological Survey")
    wet = part.get("wetlands")
    if wet:
        on, near = wet.get("on_site") or [], wet.get("nearest")
        add("Streams and wetlands", "work" if on else "note" if near else "clear",
            (f"The national wetlands map shows {len(on)} mapped water feature{'s' if len(on) != 1 else ''} on the site or at its edge "
             f"({', '.join(sorted(set(str(w.get('type')).lower() for w in on)))}). A biologist maps it on the ground, and building in it "
             "needs state and federal permits."
             if on else f"None mapped on the site. The nearest is a {str(near.get('type')).lower()} feature of {counted(near.get('acres'), 'acre')}, "
                        f"{counted(near.get('miles_away'), 'mile')} away." if near else
             f"None mapped on the site or within {counted(wet.get('searched_miles', 0.3), 'mile')}."), "U.S. Fish and Wildlife Service, National Wetlands Inventory")
    habitat = part.get("habitat")
    if habitat and habitat.get("in_plan"):
        surveys = habitat.get("survey_areas") or []
        text = (f"The site is inside the Western Riverside County habitat plan ({habitat.get('area_plan') or 'area plan not named'}). "
            + ("It lies in a cell the plan marks for possible conservation: the project is reviewed with the conservation authority. "
               if habitat.get("in_criteria_cell") else "It is not in a cell marked for conservation. ")
            + (f"Surveys asked for here: {', '.join(surveys).lower()}. They are done in season, before any grading." if surveys else ""))
        add("Protected habitat", "work" if habitat.get("in_criteria_cell") or surveys else "note", text.strip(),
            "Western Riverside County Regional Conservation Authority")
    if part.get("dam_flooding"):
        add("Dam failure flooding", "note", "The city maps the site inside the area a dam failure would flood.", "City dam inundation map")
    fossils = paleo_words(part.get("fossils"))     # an old saved answer may still hold the city's bare code
    if fossils and fossils.lower() not in ("low", "none"):
        if fossils.startswith("not rated"):
            code = fossils[fossils.index("(code ") + 6:-1]
            add("Fossils", "note", f"The city's fossil map marks this ground with the code {code} but does not say in words what it "
                                   "means. Ask the city's planning staff whether a monitor may be asked for during grading.",
                "City paleontological map")
        else:
            add("Fossils", "note", f"The city rates the chance of fossils in the ground here as {fossils[0].lower() + fossils[1:]}: "
                                   "a monitor may be asked for during grading.", "City paleontological map")
    return {"available": True, "findings": found, "evacuation_zone": part.get("evacuation_zone"),
            "work": sum(1 for f in found if f["level"] == "work"), "did_not_answer": part.get("did_not_answer") or [],
            "not_covered": ["Airport noise and height zones (March Air Reserve Base): only the county serves them, behind a robot check",
                            "Water, sewer and power capacity"]}


HOUSING_LEVELS = (("very_low", "Very low income"), ("low", "Low income"), ("moderate", "Moderate income"),
                  ("above_moderate", "Above moderate income"))
LOWER_LEVELS = ("very_low", "low", "moderate")


def housing(part, forecast, name):
    """The homes the state requires the city to plan for in this eight-year cycle, by income level, how many it has
    permitted so far, and this site's homes beside what is left. Every figure is the state housing department's;
    the site's homes are the forecast's. Nothing says which income level the site's homes would count toward, so
    this does not say it either."""
    target, permitted, left = ((part or {}).get(k) or {} for k in ("target", "permitted", "left"))
    if not isinstance(target.get("total"), (int, float)) or not isinstance(permitted.get("total"), (int, float)) or target["total"] <= 0:
        return {"available": False}
    share = part.get("share_pct") or {}
    levels = [{"id": k, "label": label, "target": target.get(k), "permitted": permitted.get(k), "left": left.get(k), "share_pct": share.get(k)}
              for k, label in HOUSING_LEVELS]
    start, end, through = part.get("from_year"), part.get("to_year"), part.get("through_year")
    out = {"available": True, "cycle": part.get("cycle"), "from_year": start, "to_year": end, "through_year": through,
           "planning_period": part.get("planning_period"), "levels": levels,
           "target": target["total"], "permitted": permitted["total"], "left": left.get("total"), "share_pct": share.get("total"),
           "by_year": part.get("by_year") or [], "notes": list(part.get("notes") or []),
           "source": part.get("source"), "as_of": part.get("as_of"), "facts": []}
    facts = out["facts"]
    span = f" between {start} and {end}" if start and end else ""
    by = f"By the end of {through}" if through else "So far"
    facts.append(f"The state requires {name} to plan for {target['total']:,} new homes{span}. {by} it had given building permits for "
                 f"{permitted['total']:,} of them" + (f" ({share['total']:g}%)." if isinstance(share.get("total"), (int, float)) else "."))

    def known(group, keys):
        return all(isinstance(group.get(k), (int, float)) for k in keys)

    lower = None
    if known(target, LOWER_LEVELS) and known(permitted, LOWER_LEVELS):
        lower = {"target": sum(target[k] for k in LOWER_LEVELS), "permitted": sum(permitted[k] for k in LOWER_LEVELS)}
        lower["left"] = sum(max(0, target[k] - permitted[k]) for k in LOWER_LEVELS)
        top_t, top_p = target.get("above_moderate"), permitted.get("above_moderate")
        if isinstance(top_t, (int, float)) and isinstance(top_p, (int, float)):
            facts.append(f"For homes at above moderate incomes it has permitted {top_p:,} against a target of {top_t:,}. For the very low, low "
                         f"and moderate income levels together it has permitted {lower['permitted']:,} of {lower['target']:,}, so "
                         f"{lower['left']:,} are still to come.")
        else:
            facts.append(f"For the very low, low and moderate income levels together it has permitted {lower['permitted']:,} of "
                         f"{lower['target']:,}, so {lower['left']:,} are still to come.")
        years = [r for r in out["by_year"] if isinstance(r.get("year"), int) and known(r, LOWER_LEVELS)]
        ahead = end - through if isinstance(end, int) and isinstance(through, int) else 0
        if years and ahead > 0 and lower["left"] > 0:
            now = _avg([sum(r[k] for k in LOWER_LEVELS) for r in years])
            lower.update(a_year_now=round(now), a_year_needed=round(lower["left"] / ahead), years_left=ahead,
                         counted_years=[years[0]["year"], years[-1]["year"]])
            facts.append(f"To reach those three targets by {end}, about {lower['a_year_needed']:,} such homes a year would need permits. "
                         f"From {years[0]['year']} to {years[-1]['year']} the city reported about {lower['a_year_now']:,} a year.")
    out["lower"] = lower
    homes = [u for u in (forecast.get("programme") or {}).get("uses") or [] if u.get("kind") == "homes" and (u.get("amount") or 0) > 0]
    count = round(sum(u["amount"] for u in homes))
    out["site"] = None
    if count:
        left_all = left.get("total")
        out["site"] = {"homes": count, "kinds": [u.get("label") for u in homes],
                       "pct_of_left": round(100 * count / left_all, 1) if isinstance(left_all, (int, float)) and left_all > 0 else None}
        kinds = ", ".join(str(u.get("label") or "").lower() for u in homes if u.get("label"))
        text = f"This site's plan holds {counted(count, 'home')}" + (f" ({kinds})" if kinds else "")
        if out["site"]["pct_of_left"] is not None:
            text += f": {out['site']['pct_of_left']:g}% of the {left_all:,} homes the city still has to permit"
        facts.append(text + ". Which income level they count toward depends on what they rent or sell for, which this plan does not "
                            "set: that is agreed with the city.")
    else:
        facts.append("This site's plan holds no homes, so it does not add to this count.")
    return out


def resident(part):
    if not part or not part.get("typical"):
        return {"available": False}
    t, then = part["typical"], part.get("earlier") or {}
    out = {"available": True, **part, "facts": []}
    bits = []
    if t.get("median_age") is not None:
        bits.append(f"is about {counted(round(t['median_age']), 'year')} old")
    if t.get("household_size") is not None:
        bits.append(f"lives in a household of {t['household_size']:.1f}")
    if bits:
        out["facts"].append("The typical resident nearby " + " and ".join(bits) + "."
                            + (f" {t['long_commute_pct']:.0f}% of workers travel an hour or more to work"
                               + (f", and {t['drive_alone_pct']:.0f}% drive alone." if t.get("drive_alone_pct") is not None else ".")
                               if t.get("long_commute_pct") is not None else ""))
    if t.get("under_18_pct") is not None and t.get("over_65_pct") is not None:
        out["facts"].append(f"{t['under_18_pct']:.0f}% are under 18 and {t['over_65_pct']:.0f}% are 65 or older"
                            + (f"; {t['bachelors_pct']:.0f}% of adults have a college degree" if t.get("bachelors_pct") is not None else "")
                            + (f"; {t['work_from_home_pct']:.0f}% work from home." if t.get("work_from_home_pct") is not None else "."))
    if t.get("home_value_usd") and then.get("home_value_usd"):
        years = 9      # between the middles of the two survey periods (2010-2014 and 2019-2023)
        r = yearly(then["home_value_usd"], t["home_value_usd"], years)
        out["home_value_rise_pct_a_year"] = round(100 * r, 1) if r is not None else None
        move = "up from" if t["home_value_usd"] >= then["home_value_usd"] else "down from"
        rate = (f"about {abs(100 * r):.1f}% " + ("a year" if r >= 0 else "less each year")) if r is not None else None
        out["facts"].append(f"The typical home is valued at {money(t['home_value_usd'])}, {move} {money(then['home_value_usd'])} in the "
                            f"{then.get('years') or 'earlier'} survey" + (f" ({rate})" if rate else "")
                            + (f"; typical rent is {money(t['rent_usd'])} a month, "
                               f"{'up from' if t['rent_usd'] >= then['rent_usd'] else 'down from'} {money(then['rent_usd'])}."
                               if t.get("rent_usd") and then.get("rent_usd") else "."))
    return out


def steps(site, forecast, plans, hazard, place, housing_block=None):
    """What needs to be done, in order: who to see, which studies, and when the land is offered. Each step says
    the fact that puts it on the list."""
    year = forecast["year"]
    ready = next((f["value"] for f in forecast.get("figures") or [] if f["id"] == "ready_years"), 2)
    ready = int(round(ready))
    planning = place.get("planning") or "the city's planning department"
    out = []

    def add(start, end, kind, what, why, who):
        out.append({"from_year": year + start, "to_year": year + end, "kind": kind, "what": what, "why": why, "who": who})

    uses = [u for p in plans or [] for u in p.get("uses") or [] if (u.get("acres") or 0) > 0]
    zoning = ", ".join(sorted({p.get("zoning") for p in site.get("parcels") or [] if p.get("zoning")})) or "today's zoning"
    change = sorted({u["label"] for u in uses if u.get("fit") == "change"})
    review = sorted({u["label"] for u in uses if u.get("fit") == "review"})
    trips = (forecast.get("programme") or {}).get("trips_at_build_out") or 0
    homes = sum(u.get("homes") or 0 for u in uses)
    signals = sum(((p.get("traffic") or {}).get("signals_to_study")) or 0 for p in plans or [])
    acres = site.get("acres") or 0
    size = counted(acres, "acre") if acres > 0 else "the site"
    add(1, 1, "city", "Meet the city's planners before applying",
        f"To hear early what the city will ask for on {'this' if counted(acres, 'acre').startswith('1 ') else 'these'} {counted(acres, 'acre')}." if acres > 0 else "To hear early what the city will ask for on this site.", planning)
    if change:
        add(1, max(2, ready), "city", f"Ask for a general plan amendment and a zone change for: {', '.join(change).lower()}",
            f"The zoning today ({zoning}) is not meant for this use. The Planning Commission and the City Council decide.", planning)
    if review:
        add(1, 1, "city", f"Confirm that the zone allows: {', '.join(review).lower()}",
            f"In {zoning} this depends on the city's review; it may need a permit of its own.", planning)
    if len({u["id"] for u in uses}) > 1 or (site.get("acres") or 0) >= 5:
        add(1, max(1, ready), "city", "File the map that divides the land into the pieces to be sold",
            "Each piece sold to a builder has to be a legal lot with street access and utilities shown.", planning + " and the city engineer")
    with_trips = size + (f" and about {counted(trips, 'trip')} a day when built" if trips else "")
    add(1, max(1, ready), "study", "Environmental review under state law (the city leads it)",
        f"{with_trips} is far past the size that is exempt." if acres >= BIG_SITE_ACRES else
        f"{with_trips}: the city decides whether a site this size can be exempt, so ask at the first meeting." if acres > 0 else
        "The city decides whether the site can be exempt, so ask at the first meeting.", planning)
    if trips >= 1000 or signals:
        add(1, max(1, ready), "study", "Traffic study",
            (f"About {counted(trips, 'trip')} a day once everything is built" if trips else "The trips a day once everything is built are not known")
            + (f", and {counted(signals, 'new signal')} to study at the entrances." if signals else "."),
            "The city's traffic engineer" + (" and Caltrans for the highway ramps" if (forecast.get("traffic") or {}).get("highway") else ""))
    add(1, max(1, ready), "study", "Soils and geology report", "Needed for the map and the grading plan on any site.", "A licensed soils engineer")
    for f in (hazard or {}).get("findings") or []:
        if f["level"] != "work":
            continue
        what = {"Flood": "Flood study, and building pads above the flood level",
                "Wildfire": "Fire protection plan: cleared space, fire-resistant building, two ways out",
                "Earthquake faults": "Fault study", "Soft ground and slides": "Have the soils report answer the mapped ground hazard",
                "Streams and wetlands": "Have a biologist map the water features; ask which state and federal permits apply",
                "Protected habitat": "Habitat check and the seasonal surveys the habitat plan asks for"}.get(f["topic"])
        who = {"Wildfire": "The fire department (fire marshal)", "Flood": "The city engineer and the county flood control district",
               "Streams and wetlands": "A biologist; the Army Corps of Engineers, the regional water board and the state wildlife department",
               "Protected habitat": "A biologist and the regional conservation authority"}.get(f["topic"], "A licensed specialist")
        if what:
            add(1, max(1, ready), "study", what, f["text"], who)
    add(1, max(1, ready), "check", "Ask for letters saying water, sewer and power can serve the site",
        "No public record this app reads shows utility capacity.", place.get("water") or "The water and sewer district, and the power company")
    lower_left = ((housing_block or {}).get("lower") or {}).get("left")
    if homes and lower_left:
        add(1, 1, "city", "Ask how the homes would count toward the city's state housing target",
            f"The city still has to permit {lower_left:,} homes for very low, low and moderate incomes by {housing_block.get('to_year')}. "
            f"The plan adds about {counted(homes, 'home')}; which level they count toward is agreed with the city.", planning)
    if homes:
        add(1, max(1, ready), "check", "Check school room and fees with the school district",
            f"The plan adds about {counted(homes, 'home')}.", "The school district that serves the site")
    for step in (forecast.get("programme") or {}).get("steps") or []:
        lines = [x for x in step.get("lines") or [] if ":" in x and "acre" in x]
        if lines and step["to_year"] > year + ready:
            out.append({"from_year": max(step["from_year"], year + ready + 1), "to_year": step["to_year"], "kind": "sell",
                        "what": "Offer to builders: " + " ".join(lines), "who": "Builders and developers (see each parcel's Plan page for likely buyers)",
                        "why": "The pace the forecast's expected line supports."})
    out.sort(key=lambda s: (s["from_year"], {"city": 0, "study": 1, "check": 2, "sell": 3}[s["kind"]]))
    return {"steps": out, "note": "A starting checklist drawn from the facts on this page by simple rules. The city decides what it "
                                  "requires, and a land-use lawyer or planner should confirm it."}


def make_outlook(site, forecast, plans, parts, place):
    """Everything this module adds for a site. `parts` holds the economy parts, climate, hazards, nearby and
    residents (any may be None); `place` is {"name", "planning", "water"} from the city adapter."""
    hazard = hazards(parts.get("hazards"))
    near = parts.get("nearby")
    homes_target = housing(parts.get("housing"), forecast, place.get("name") or "the city")
    return {"economy": economy(parts, forecast, place.get("name") or "The city"),
            "housing": homes_target,
            "climate": climate(parts.get("climate"), forecast["year"]),
            "hazards": hazard,
            "nearby": {"available": True, **near} if near else {"available": False},
            "resident": resident(parts.get("residents")),
            "todo": steps(site, forecast, plans, hazard, place, homes_target)}
