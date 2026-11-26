"""The wider picture around a site, and what has to be done: the city's economy by year, the weather and how it
is changing, hazards and limits on building, what is close by, the typical resident, and a checklist of steps.

Like forecast.py this is plain arithmetic on facts other modules read (landplanner/sources). It invents nothing:
a block whose source did not answer is marked not available, and every sentence carries the figure it rests on.
The checklist is a starting list drawn from those facts by simple rules. The city decides what it requires.
"""
from .forecast import HORIZON, SCENARIOS, money, yearly

ECONOMY_PARTS = ("population", "permits", "sales", "work", "borrowing", "prices")
PLACE_PARTS = ("climate", "hazards", "nearby", "residents")
WET_ZONES = ("A", "V")     # FEMA zone letters for land a 1-in-100-year flood covers


def _rows(part):
    return {r["year"]: r for r in (part or {}).get("rows") or [] if r.get("year") is not None}


def _avg(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


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
                     "prices_change_pct": (prices.get(y) or {}).get("change_pct")})
    facts = []
    if len(people) >= 2:
        a, b = people[min(people)], people[max(people)]
        r = yearly(a.get("people"), b.get("people"), max(people) - min(people))
        if r is not None:
            facts.append(f"{place_name} had {a['people']:,} people in {min(people)} and {b['people']:,} in {max(people)}: "
                         f"{100 * r:.1f}% more each year. Homes went from {a['homes']:,} to {b['homes']:,}.")
    whole = [r for r in permits.values() if (r.get("months_reported") or 12) >= 12 and r.get("homes") is not None]
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
    ahead = []
    ring = next((r for r in forecast.get("rings") or [] if r.get("miles") == max(x["miles"] for x in forecast["rings"]) and r.get("rows")), None) \
        if forecast.get("rings") else None
    if full and ring:
        base_sales, base_year = full[-1]["sales_usd"], full[-1]["year"]
        at = {r["year"]: r["homes"] for r in ring["rows"]}
        start = at.get(base_year) or at.get(forecast["year"])
        if start:
            for y in forecast["years"][2:]:
                ahead.append({"year": y, "shop_sales_usd": {s: round(base_sales * at[y][s] / start[s], -5) for s in SCENARIOS}})
    return {"available": True, "place": place_name, "rows": rows, "facts": facts, "sales_ahead": ahead,
            "sales_ahead_basis": ("The city's last full year of shop and restaurant sales, grown with the homes the forecast "
                                  f"expects within {ring['miles']} miles. Today's prices; no inflation added.") if ahead else None,
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
        out["facts"].append(f"A typical year averages {t['mean_f']:.0f} degrees F with about {t.get('rain_in', 0):.1f} inches of rain"
                            + (f"; the hottest month is {hot['month']}, with afternoons around {hot['high_f']:.0f} degrees." if hot and hot.get("high_f") else "."))
    if trend.get("mean_f_per_decade") is not None:
        ten = trend["mean_f_per_decade"] * HORIZON / 10
        out["ahead"] = {"year": year + HORIZON, "mean_f_change": round(ten, 1),
                        "basis": f"The straight-line trend of the yearly averages from {trend.get('from_year')} to {trend.get('to_year')}, carried on."}
        out["facts"].append(f"The yearly average has moved {trend['mean_f_per_decade']:+.1f} degrees F each ten years since {trend.get('from_year')}. "
                            f"If that simply continues, {year + HORIZON} is about {ten:+.1f} degrees from today: more cooling load, more shade "
                            "and water-wise planting to plan for.")
    if trend.get("rain_in_per_decade") is not None and t.get("rain_in"):
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
        zones = [z for z in ([flood.get("zone")] + list(flood.get("zones_on_site") or [])) if z]
        wet = flood.get("special_hazard_area") or any(str(z).upper().startswith(WET_ZONES) for z in zones)
        add("Flood", "work" if wet else "clear",
            (f"Part of the site is in FEMA flood zone {', '.join(sorted(set(map(str, zones))))}: building there needs a flood study and raised pads."
             if wet else f"FEMA flood zone {flood.get('zone')}: "
                         f"{str(flood.get('meaning') or 'outside the mapped flood areas').strip().rstrip('.').lower()}.")
            + (f" Map panel {flood['panel']}, in force since {flood['effective']}." if flood.get("panel") and flood.get("effective") else ""),
            "FEMA National Flood Hazard Layer")
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
            + (f"; the nearest station is {near['name']}, {near['miles_away']:g} miles away" if near.get("name") else "")
            + (f". A new station is planned {planned.get('miles_away'):g} miles away ({planned.get('name')})." if planned and planned.get("miles_away") is not None else "."),
            "City fire coverage maps")
    faults = part.get("faults")
    if faults:
        add("Earthquake faults", "work" if faults.get("in_fault_zone") else "clear",
            "The site is inside a state earthquake fault zone: a fault study is required before building."
            if faults.get("in_fault_zone") else
            (f"No mapped fault zone on the site; the nearest mapped fault is {faults['nearest_miles']:g} miles away."
             if faults.get("nearest_miles") is not None else
             f"No mapped fault or fault zone within {faults.get('searched_miles', 3):g} miles."), "California Geological Survey")
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
             if on else f"None mapped on the site. The nearest is a {str(near.get('type')).lower()} feature of {near.get('acres'):g} acres, "
                        f"{near.get('miles_away'):g} miles away." if near else
             f"None mapped on the site or within {wet.get('searched_miles', 0.3):g} miles."), "U.S. Fish and Wildlife Service, National Wetlands Inventory")
    habitat = part.get("habitat")
    if habitat and habitat.get("in_plan"):
        surveys = habitat.get("survey_areas") or []
        add("Protected habitat", "work" if habitat.get("in_criteria_cell") or surveys else "note",
            f"The site is inside the Western Riverside County habitat plan ({habitat.get('area_plan') or 'area plan not named'}). "
            + ("It lies in a cell the plan marks for possible conservation: the project is reviewed with the conservation authority. "
               if habitat.get("in_criteria_cell") else "It is not in a cell marked for conservation. ")
            + (f"Surveys asked for here: {', '.join(surveys).lower()}. They are done in season, before any grading." if surveys else ""),
            "Western Riverside County Regional Conservation Authority")
    if part.get("dam_flooding"):
        add("Dam failure flooding", "note", "The city maps the site inside the area a dam failure would flood.", "City dam inundation map")
    if part.get("fossils") and str(part["fossils"]).lower() not in ("low", "none"):
        add("Fossils", "note", f"The city rates the chance of fossils in the ground here as {str(part['fossils']).lower()}: "
                               "a monitor may be asked for during grading.", "City paleontological map")
    return {"available": True, "findings": found, "evacuation_zone": part.get("evacuation_zone"),
            "work": sum(1 for f in found if f["level"] == "work"), "did_not_answer": part.get("did_not_answer") or [],
            "not_covered": ["Airport noise and height zones (March Air Reserve Base): only the county serves them, behind a robot check",
                            "Water, sewer and power capacity"]}


def resident(part):
    if not part or not part.get("typical"):
        return {"available": False}
    t, then = part["typical"], part.get("earlier") or {}
    out = {"available": True, **part, "facts": []}
    bits = []
    if t.get("median_age") is not None:
        bits.append(f"is about {t['median_age']:.0f} years old")
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
        out["facts"].append(f"The typical home is valued at {money(t['home_value_usd'])}, up from {money(then['home_value_usd'])} in the "
                            f"{then.get('years') or 'earlier'} survey (about {100 * r:.1f}% a year)"
                            + (f"; typical rent is {money(t['rent_usd'])} a month, up from {money(then['rent_usd'])}." if t.get("rent_usd") and then.get("rent_usd") else "."))
    return out


def steps(site, forecast, plans, hazard, place):
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
    add(1, 1, "city", "Meet the city's planners before applying", f"To hear early what the city will ask for on these {site.get('acres'):g} acres.", planning)
    if change:
        add(1, max(2, ready), "city", f"Ask for a general plan amendment and a zone change for: {', '.join(change).lower()}",
            f"The zoning today ({zoning}) is not meant for this use. The Planning Commission and the City Council decide.", planning)
    if review:
        add(1, 1, "city", f"Confirm that the zone allows: {', '.join(review).lower()}",
            f"In {zoning} this depends on the city's review; it may need a permit of its own.", planning)
    if len({u["id"] for u in uses}) > 1 or (site.get("acres") or 0) >= 5:
        add(1, max(1, ready), "city", "File the map that divides the land into the pieces to be sold",
            "Each piece sold to a builder has to be a legal lot with street access and utilities shown.", planning + " and the city engineer")
    add(1, max(1, ready), "study", "Environmental review under state law (the city leads it)",
        f"{site.get('acres'):g} acres" + (f" and about {trips:,} trips a day when built" if trips else "") + " is far past the size that is exempt.", planning)
    if trips >= 1000 or signals:
        add(1, max(1, ready), "study", "Traffic study",
            f"About {trips:,} trips a day at build-out" + (f", and {signals} new signal(s) to study at the entrances." if signals else "."),
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
    if homes:
        add(1, max(1, ready), "check", "Check school room and fees with the school district",
            f"The plan adds about {homes:,} homes.", "The school district(s) serving the site")
    for step in (forecast.get("programme") or {}).get("steps") or []:
        lines = [x for x in step.get("lines") or [] if ":" in x and "acres" in x]
        if lines:
            out.append({"from_year": step["from_year"], "to_year": step["to_year"], "kind": "sell",
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
    return {"economy": economy(parts, forecast, place.get("name") or "The city"),
            "climate": climate(parts.get("climate"), forecast["year"]),
            "hazards": hazard,
            "nearby": {"available": True, **near} if near else {"available": False},
            "resident": resident(parts.get("residents")),
            "todo": steps(site, forecast, plans, hazard, place)}
