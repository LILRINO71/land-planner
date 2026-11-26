"""A year-by-year forecast for a site: the people, homes, shops, jobs and traffic around it over the next ten
years, and how fast the site's own land could be taken up. One parcel or several next to each other.

How it works, in order:
  1. Growth. Homes near the site have a measured past (2010 and 2020 Census) and two official forecasts (the
     region's adopted plan and its draft update). Each gives a yearly growth rate: a "reading". The expected
     line is the middle reading; the low and high lines are the lowest and the highest. Nothing is invented:
     with no reading there is no forecast, and the answer says so.
  2. Needs. New homes each year are that growth. New shop space is what the new households' income supports.
     New work space is what the forecast jobs need. Each is set beside what is already on the city's project
     lists, spread over the years those projects are likely to open.
  3. The site. Its own plan (plan.py, per parcel, added up) is taken up at the share of each year's need that one
     site can win.

Everything that is not measured or an official forecast is an assumption in ASSUMPTIONS, shown on the page with
its starting value, and the owner can change it. Money is in the survey's dollars; nothing is inflated.
"""
import math
import statistics

RINGS = (1, 3, 5)
MARKET_MILES = 3            # the ring the needs are worked out for (the city's project lists are read this far)
HORIZON = 10
SCENARIOS = ("low", "expected", "high")

ASSUMPTIONS = {
    # id: (label, unit, starting value, group, lowest, highest)
    "spend_pct": ("Share of household income spent in shops and restaurants", "%", 30, "Shops", 5, 60),
    "local_pct": ("Share of that spending done close to home", "%", 55, "Shops", 5, 100),
    "sales_per_sq_ft": ("Sales a shop needs each year for each square foot", "$ per sq ft", 400, "Shops", 100, 2000),
    "sq_ft_per_job": ("Floor space for each new job", "sq ft", 400, "Jobs", 100, 3000),
    "traffic_follow_pct": ("Highway traffic growth for each 1% more homes", "%", 70, "Traffic", 0, 200),
    "capture_pct": ("Share of each year's new need this site can win", "%", 20, "The site", 1, 100),
    "ready_years": ("Years before the first land can be handed over (approvals, map, streets)", "years", 2, "The site", 0, 8),
    "built_review_pct": ("Share of projects still under review that end up built", "%", 60, "Projects on the city's list", 0, 100),
}

# when a project on the city's list is likely to open, counted in years from now, by how far along it is:
# (words to look for in its status, label, first year, last year, still uncertain)
STAGES = (
    ("under construction", "Under construction", 1, 2, False),
    ("final engineering", "Approved, in final engineering", 2, 4, False),
    ("approved", "Approved by planning", 3, 6, False),
    ("review", "Application under review", 4, 8, True),
    ("", "Stage not given", 4, 9, True),
)
PROGRAMME = (("apartments", "homes", "homes"), ("homes", "homes", "homes"), ("retail", "sq_ft", "shops"),
             ("office", "sq_ft", "work"), ("business", "sq_ft", "work"))
HALVES = {"north": ("north", "north-east", "north-west"), "south": ("south", "south-east", "south-west"),
          "east": ("east", "north-east", "south-east"), "west": ("west", "north-west", "south-west")}


def num(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def clean_settings(settings):
    """Only what the page may set: the assumptions, each kept inside its limits."""
    s = settings if isinstance(settings, dict) else {}
    out = {"assumptions": {}}
    if isinstance(s.get("assumptions"), dict):
        for key, value in s["assumptions"].items():
            v = num(value)
            if key in ASSUMPTIONS and v is not None:
                low, high = ASSUMPTIONS[key][4], ASSUMPTIONS[key][5]
                v = min(high, max(low, v))
                if v != ASSUMPTIONS[key][2]:
                    out["assumptions"][key] = v
    return out


def yearly(a, b, years):
    """The steady yearly growth rate that turns a into b over that many years."""
    if not a or not b or a <= 0 or b <= 0 or years <= 0:
        return None
    return (b / a) ** (1.0 / years) - 1.0


def three(values):
    """Low, expected and high from a list of readings: the lowest, the middle and the highest."""
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {"low": min(values), "expected": statistics.median(values), "high": max(values)}


def each(fn):
    return {s: fn(s) for s in SCENARIOS}


def money(n):
    return f"${n:,.0f}"


def pct(rate, places=1):
    return f"{100 * rate:.{places}f}%"


def ring_of(part, miles):
    for r in (part or {}).get("rings") or []:
        if r.get("miles") == miles:
            return r
    return None


def home_readings(parts, miles):
    """Every reading of yearly growth in homes within this distance: measured, and the region's forecasts."""
    out = []
    now, before = ring_of(parts.get("people"), miles), ring_of(parts.get("people_before"), miles)
    if now and before:
        y0, y1 = (parts.get("people_before") or {}).get("year", 2010), (parts.get("people") or {}).get("year", 2020)
        r = yearly(before.get("homes"), now.get("homes"), y1 - y0)
        if r is not None:
            out.append({"id": "measured", "kind": "measured", "label": f"Counted growth, {y0} to {y1}",
                        "rate_pct": round(100 * r, 2), "from": {"year": y0, "homes": before["homes"]},
                        "to": {"year": y1, "homes": now["homes"]}, "source": "U.S. Census Bureau, Census blocks"})
    plan = parts.get("regional_plan") or {}
    for key, words in (("adopted", "The region's adopted plan"), ("draft", "The region's draft update")):
        ring = ring_of(plan.get(key), miles)
        if not ring:
            continue
        years = plan[key]["years"]
        a, b = ring["households"].get(str(years[0])), ring["households"].get(str(years[1]))
        r = yearly(a, b, years[1] - years[0])
        if r is not None:
            out.append({"id": key, "kind": "official forecast", "label": f"{words}, {years[0]} to {years[1]}",
                        "rate_pct": round(100 * r, 2), "from": {"year": years[0], "homes": a},
                        "to": {"year": years[1], "homes": b}, "source": plan[key]["label"]})
    return out


def job_readings(parts, miles):
    """New jobs a year within this distance, as the region's adopted plan and its draft update each expect."""
    out = []
    plan = parts.get("regional_plan") or {}
    for key, words in (("adopted", "The region's adopted plan"), ("draft", "The region's draft update")):
        ring = ring_of(plan.get(key), miles)
        if not ring:
            continue
        years = plan[key]["years"]
        a, b = ring["jobs"].get(str(years[0])), ring["jobs"].get(str(years[1]))
        if a is None or b is None:
            continue
        out.append({"id": key, "kind": "official forecast", "label": f"{words}, {years[0]} to {years[1]}",
                    "jobs_per_year": round((b - a) / (years[1] - years[0])), "from": {"year": years[0], "jobs": a},
                    "to": {"year": years[1], "jobs": b}, "source": plan[key]["label"]})
    return out


def stage_of(status):
    text = (status or "").lower()
    for i, (words, *_rest) in enumerate(STAGES[:-1]):
        if words in text:
            return i
    return len(STAGES) - 1


def pipeline(parts, A, years):
    """What is already on the city's project lists within the market distance, spread over the years each
    project is likely to open: homes, shop space and work space for each forecast year, and the lists by stage."""
    base = years[1]
    per_year = {k: {y: 0.0 for y in years} for k in ("homes", "shops", "work")}
    stages = [{"label": label, "from_year": base + a, "to_year": base + b, "uncertain": unsure, "projects": 0,
               "homes": 0, "shops_sq_ft": 0, "work_sq_ft": 0} for _, label, a, b, unsure in STAGES]
    unstated, counted = 0, 0
    listed = (parts.get("projects") or {}).get("projects") or []
    for p in listed:
        if (p.get("miles_away") or 0) > MARKET_MILES:
            continue
        kind, stated = (p.get("kind") or "").lower(), p.get("stated") or {}
        homes = stated.get("homes") or 0 if kind.startswith(("residential", "mixed")) or stated.get("homes") else 0
        feet = stated.get("building_sq_ft") or 0
        shops = feet if kind.startswith(("commercial", "mixed")) else 0
        work = feet if kind.startswith(("industrial", "office", "business")) else 0
        if not homes and not shops and not work:
            unstated += 1
            continue
        counted += 1
        i = stage_of(p.get("status"))
        _, _, a, b, unsure = STAGES[i]
        share = A["built_review_pct"] / 100 if unsure else 1.0
        stages[i]["projects"] += 1
        for key, amount, field in (("homes", homes, "homes"), ("shops", shops, "shops_sq_ft"), ("work", work, "work_sq_ft")):
            stages[i][field] += round(amount * share)
            for y in range(base + a, base + b + 1):
                if y in per_year[key]:
                    per_year[key][y] += amount * share / (b - a + 1)
    return {"per_year": per_year, "stages": [s for s in stages if s["projects"]], "projects_counted": counted,
            "projects_without_sizes": unstated, "projects_listed": len(listed),
            "lists_updated": (parts.get("projects") or {}).get("lists_updated") or {},
            "available": parts.get("projects") is not None}


def income_near(parts, miles=MARKET_MILES):
    """Household income around the site from the census survey's tracts: the typical figure within the market
    distance (tract medians weighted by the households inside it), where incomes run higher and lower, and
    how many households rent."""
    data = parts.get("tracts")
    if not data or not data.get("tracts"):
        return {"available": False}
    county = (data.get("county") or {}).get("income")
    rows, weight, total, renters, households = [], 0.0, 0.0, 0.0, 0.0
    for t in data["tracts"]:
        share = (t.get("share_within") or {}).get(miles) or (t.get("share_within") or {}).get(str(miles)) or 0.0
        far = (t.get("share_within") or {}).get(max(RINGS)) or (t.get("share_within") or {}).get(str(max(RINGS))) or 0.0
        hh, income = t.get("households") or 0, t.get("income")
        if share > 0 and hh:
            households += hh * share
            renters += (t.get("renters") or 0) * share
            if income:
                weight += hh * share
                total += hh * share * income
        if far <= 0 or not income:
            continue
        ratio = income / county if county else None
        rows.append({"name": t.get("name"), "income": income, "households": hh, "miles_away": t.get("miles_away"),
                     "direction": t.get("direction"), "lat": t.get("lat"), "lon": t.get("lon"),
                     "share_in_market": round(share, 2),
                     "against_county": None if ratio is None else "higher" if ratio >= 1.15 else "lower" if ratio <= 0.85 else "about the same"})
    if not weight:
        return {"available": False}
    halves = []
    for name, directions in HALVES.items():
        inside = [r for r in rows if r["direction"] in directions and r["households"]]
        w = sum(r["households"] for r in inside)
        if w:
            halves.append({"direction": name, "income": round(sum(r["households"] * r["income"] for r in inside) / w, -2),
                           "households": round(w), "tracts": len(inside)})
    halves.sort(key=lambda h: -h["income"])
    typical = round(total / weight, -2)
    out = {"available": True, "typical": typical, "county": county, "county_name": (data.get("county") or {}).get("name"),
           "survey": (data.get("survey") or {}).get("income"), "lowest": min(r["income"] for r in rows),
           "highest": max(r["income"] for r in rows), "renters_pct": round(100 * renters / households, 1) if households else None,
           "tracts": sorted(rows, key=lambda r: r["miles_away"]), "by_direction": halves, "source": data.get("source"),
           "built_since_2020": round(sum((t.get("built_2020_on") or 0) * ((t.get("share_within") or {}).get(miles)
                                                                          or (t.get("share_within") or {}).get(str(miles)) or 0)
                                         for t in data["tracts"])),
           "homes_survey": (data.get("survey") or {}).get("homes")}
    words = f"A typical household within {miles} miles earns about {money(typical)} a year"
    if county:
        gap = typical / county - 1
        words += (f", {abs(round(100 * gap))}% {'above' if gap > 0 else 'below'} the {out['county_name'] or 'county'} figure of {money(county)}"
                  if abs(gap) >= 0.03 else f", about the same as the {out['county_name'] or 'county'} figure")
    words += "."
    if len(halves) >= 2 and halves[0]["income"] - halves[-1]["income"] >= 0.08 * typical:
        words += (f" Incomes run higher to the {halves[0]['direction']} (about {money(halves[0]['income'])}) and lower to the "
                  f"{halves[-1]['direction']} (about {money(halves[-1]['income'])}).")
    out["summary"] = words
    return out


def programme_of(plans):
    """What the site's own plans add up to, use by use, with the trips each use brings at build-out."""
    uses = {}
    for plan in plans or []:
        trips = ((plan.get("traffic") or {}).get("by_use")) or {}
        for u in plan.get("uses") or []:
            row = uses.setdefault(u["id"], {"id": u["id"], "label": u["label"], "short": u.get("short"), "colour": u.get("colour"),
                                           "acres": 0.0, "amount": 0, "trips": 0})
            row["acres"] = round(row["acres"] + (u.get("acres") or 0), 1)
            row["amount"] += u.get("homes") or u.get("sq_ft") or 0
            row["trips"] += trips.get(u["id"]) or 0
    return uses


def take_up(uses, pools, A, years, known):
    """The site's land taken up year by year: each use wins the owner's share of that year's new need of its
    kind (homes, shop space, work space), starting once the land is ready. Uses of one kind share the need
    in proportion to their size. A kind whose need could not be worked out (`known`) is left out: the page
    says it is not forecast, instead of showing it as never selling."""
    base, ready = years[1], int(round(A["ready_years"]))
    out = []
    for kind in ("homes", "shops", "work"):
        if not known.get(kind):
            continue
        members = [(use, field) for use, field, k in PROGRAMME if k == kind and uses.get(use, {}).get("amount")]
        whole = sum(uses[use]["amount"] for use, _ in members)
        for use, field in members:
            u = uses[use]
            part = u["amount"] / whole
            left, cum, rows, done, last = float(u["amount"]), 0.0, [], None, 0.0
            for y in years[2:]:
                room = pools[kind]["expected"].get(y, 0.0) * A["capture_pct"] / 100 * part if y > base + ready else 0.0
                taken = min(left, max(0.0, room))
                left -= taken
                cum += taken
                last = room if room > 0 else last
                if done is None and left <= 1e-6 and u["amount"]:
                    done = y
                rows.append({"year": y, "taken": round(taken), "so_far": round(cum),
                             "acres_so_far": round(u["acres"] * cum / u["amount"], 1)})
            if done is None and last > 0:
                more = left / last
                done_later = years[-1] + math.ceil(more) if more < 60 else None
            else:
                done_later = None
            at5, at10 = rows[4], rows[-1]
            out.append({**u, "kind": kind, "unit": "homes" if field == "homes" else "sq ft", "by_year": rows,
                        "by_year_5": at5["so_far"], "by_year_10": at10["so_far"], "acres_by_year_5": at5["acres_so_far"],
                        "acres_by_year_10": at10["acres_so_far"], "pct_by_year_10": round(100 * at10["so_far"] / u["amount"]),
                        "filled_in": done, "filled_later_in": done_later,
                        "never_at_this_pace": done is None and done_later is None})
    order = [u for u, _, _ in PROGRAMME]
    out.sort(key=lambda r: order.index(r["id"]))
    return out


def periods_of(taken, uses, A, years):
    """The ten years in three steps, in words: what the site hands over in each."""
    base, ready = years[1], int(round(A["ready_years"]))
    steps = ((1, 2), (3, 5), (6, HORIZON))
    out = []
    for a, b in steps:
        lines = []
        if b <= ready:
            lines.append("Approvals from the city, the subdivision map and the first streets. No land is handed over yet.")
        elif a <= ready:
            lines.append(f"Approvals, the map and the first streets take until about {base + ready}; the first land follows.")
        for u in taken:
            before = u["by_year"][a - 2]["so_far"] if a > 1 else 0
            before_acres = u["by_year"][a - 2]["acres_so_far"] if a > 1 else 0.0
            got, acres = u["by_year"][b - 1]["so_far"] - before, round(u["by_year"][b - 1]["acres_so_far"] - before_acres, 1)
            if got > 0 and acres >= 0.1:
                amount = f"{got:,} homes" if u["unit"] == "homes" else f"{round(got, -2):,} sq ft"
                lines.append(f"{u['label']}: about {acres:g} acres ({amount}).")
        if len(lines) == 0:
            lines.append("Nothing more is taken up in these years at this pace.")
        out.append({"from_year": base + a, "to_year": base + b, "label": f"{base + a} to {base + b}",
                    "title": ("Years 1 and 2" if (a, b) == (1, 2) else f"Years {a} to {b}"), "lines": lines})
    left = [u for u in taken if u["pct_by_year_10"] < 100]
    after = []
    for u in left:
        rest = round(u["acres"] - u["acres_by_year_10"], 1)
        when = (f"filled around {u['filled_later_in']}" if u["filled_later_in"] else "not filled at this pace within a lifetime")
        after.append(f"{u['label']}: {rest:g} of {u['acres']:g} acres still unsold in {years[-1]}, {when}.")
    park = uses.get("park")
    if park and park["acres"]:
        after.append(f"Parks, open space and drainage ({park['acres']:g} acres) are built along with the uses around them.")
    return out, after


def make_forecast(site, parts, plans=None, settings=None, year=2026):
    """The forecast for a site. `site` is {"apns", "acres", "centre", ...}; `parts` the facts read around it
    (people, people_before, regional_plan, tracts, projects, state_highway_traffic); `plans` each parcel's
    plan from plan.py; `year` is this year. Returns plain data for the page."""
    settings = clean_settings(settings)
    A = {k: v[2] for k, v in ASSUMPTIONS.items()}
    A.update(settings["assumptions"])
    years = list(range(year - 1, year + HORIZON + 1))      # last year for background, this year, then ten more
    counted_year = (parts.get("people") or {}).get("year", 2020)
    limits, sources = [], []

    # ---- growth, ring by ring
    rings = []
    for miles in RINGS:
        now, before = ring_of(parts.get("people"), miles), ring_of(parts.get("people_before"), miles)
        readings = home_readings(parts, miles)
        rates = three([r["rate_pct"] / 100 for r in readings])
        row = {"miles": miles, "readings": readings, "counted": {}, "available": bool(now and rates)}
        if before:
            row["counted"][str((parts.get("people_before") or {}).get("year", 2010))] = {"people": before["people"], "homes": before["homes"]}
        if now:
            row["counted"][str(counted_year)] = {"people": now["people"], "homes": now["homes"]}
        if now and rates:
            per_home = now["people"] / now["homes"] if now.get("homes") else 0.0
            row["people_per_home"] = round(per_home, 2)
            row["rates_pct"] = {s: round(100 * rates[s], 2) for s in SCENARIOS}
            row["one_reading"] = len(readings) == 1
            row["rows"] = []
            for y in years:
                homes = each(lambda s: now["homes"] * (1 + rates[s]) ** (y - counted_year))
                row["rows"].append({"year": y, "homes": {s: round(homes[s]) for s in SCENARIOS},
                                    "people": {s: round(homes[s] * per_home, -1) for s in SCENARIOS}})
            row["_homes"] = {y: each(lambda s: now["homes"] * (1 + rates[s]) ** (y - counted_year)) for y in years}
        rings.append(row)
    market = next(r for r in rings if r["miles"] == MARKET_MILES)
    wide = next(r for r in rings if r["miles"] == max(RINGS))
    ok = market["available"]

    income = income_near(parts)
    pipe = pipeline(parts, A, years)
    future = years[2:]

    # ---- homes
    homes = {"available": ok, "rows": [], "pipeline": {k: v for k, v in pipe.items() if k != "per_year"}}
    need = {s: {} for s in SCENARIOS}
    if ok:
        cum, cum_pipe = {s: 0.0 for s in SCENARIOS}, 0.0
        for y in years[1:]:
            new = each(lambda s: market["_homes"][y][s] - market["_homes"][y - 1][s])
            row = {"year": y, "need": {s: round(new[s]) for s in SCENARIOS}, "pipeline": round(pipe["per_year"]["homes"][y])}
            if y in future:
                for s in SCENARIOS:
                    need[s][y] = new[s]
                    cum[s] += new[s]
                cum_pipe += pipe["per_year"]["homes"][y]
                row["need_so_far"] = {s: round(cum[s]) for s in SCENARIOS}
                row["pipeline_so_far"] = round(cum_pipe)
                if income.get("renters_pct") is not None:
                    row["rented"] = round(new["expected"] * income["renters_pct"] / 100)
                    row["owned"] = round(new["expected"]) - row["rented"]
            homes["rows"].append(row)
        ten, piped = cum["expected"], cum_pipe
        homes["need_10_years"] = {s: round(cum[s]) for s in SCENARIOS}
        homes["pipeline_10_years"] = round(piped)
        first = need["expected"][future[0]]
        homes["pipeline_covers_years"] = round(piped / (ten / HORIZON), 1) if ten > 0 else None
        homes["summary"] = (f"Within {MARKET_MILES} miles the expected need is about {round(first, -1):,.0f} new homes a year "
                            f"({round(need['low'][future[0]], -1):,.0f} to {round(need['high'][future[0]], -1):,.0f}), "
                            f"about {round(ten, -2):,.0f} over ten years. Projects already on the city's lists would add about "
                            f"{round(piped, -1):,.0f} homes in that time"
                            + (f", which covers about {homes['pipeline_covers_years']:g} years of the expected need." if ten > 0 else "."))

    # ---- shops
    shops = {"available": bool(ok and income.get("available")), "rows": []}
    shop_need = {s: {} for s in SCENARIOS}
    if shops["available"]:
        per_home = income["typical"] * A["spend_pct"] / 100 * A["local_pct"] / 100 / A["sales_per_sq_ft"]
        shops["sq_ft_per_home"] = round(per_home, 1)
        shops["supported_today_sq_ft"] = {s: round(market["_homes"][year][s] * per_home, -3) for s in SCENARIOS}
        cum, cum_pipe = {s: 0.0 for s in SCENARIOS}, 0.0
        for y in future:
            for s in SCENARIOS:
                shop_need[s][y] = need[s][y] * per_home
                cum[s] += shop_need[s][y]
            cum_pipe += pipe["per_year"]["shops"][y]
            shops["rows"].append({"year": y, "new_sq_ft": {s: round(shop_need[s][y], -2) for s in SCENARIOS},
                                  "pipeline_sq_ft": round(pipe["per_year"]["shops"][y], -2),
                                  "new_so_far": {s: round(cum[s], -2) for s in SCENARIOS}, "pipeline_so_far": round(cum_pipe, -2)})
        shops["new_10_years_sq_ft"] = {s: round(cum[s], -3) for s in SCENARIOS}
        shops["pipeline_10_years_sq_ft"] = round(cum_pipe, -3)
        more = cum_pipe > cum["high"]
        shops["summary"] = (f"Each new household supports about {per_home:.0f} sq ft of shops and restaurants close to home. "
                            f"Growth within {MARKET_MILES} miles supports about {round(shop_need['expected'][future[0]], -2):,.0f} sq ft "
                            f"more each year, about {round(cum['expected'], -3):,.0f} sq ft over ten years. Commercial projects already "
                            f"on the city's lists come to about {round(cum_pipe, -3):,.0f} sq ft"
                            + (", more than local growth alone supports even on the high line. New shops here would have to draw "
                               "from further away (the highway, a regional store) or serve a need today's shops do not."
                               if more else ", so there is room for more as the area grows." if cum_pipe < cum["expected"]
                               else ", close to what local growth supports."))

    # ---- jobs and work space
    jobs = {"readings": job_readings(parts, MARKET_MILES), "rows": []}
    pace = three([r["jobs_per_year"] for r in jobs["readings"]])
    jobs["available"] = pace is not None
    work_need = {s: {} for s in SCENARIOS}
    if pace:
        cum, cum_pipe = {s: 0.0 for s in SCENARIOS}, 0.0
        for y in future:
            for s in SCENARIOS:
                work_need[s][y] = max(0.0, pace[s]) * A["sq_ft_per_job"]
                cum[s] += work_need[s][y]
            cum_pipe += pipe["per_year"]["work"][y]
            jobs["rows"].append({"year": y, "new_jobs": {s: round(max(0.0, pace[s])) for s in SCENARIOS},
                                 "space_sq_ft": {s: round(work_need[s][y], -2) for s in SCENARIOS},
                                 "pipeline_sq_ft": round(pipe["per_year"]["work"][y], -2),
                                 "space_so_far": {s: round(cum[s], -2) for s in SCENARIOS}, "pipeline_so_far": round(cum_pipe, -2)})
        jobs["new_jobs_per_year"] = {s: round(max(0.0, pace[s])) for s in SCENARIOS}
        jobs["space_10_years_sq_ft"] = {s: round(cum[s], -3) for s in SCENARIOS}
        jobs["pipeline_10_years_sq_ft"] = round(cum_pipe, -3)
        jobs["summary"] = (f"The region's plans expect about {jobs['new_jobs_per_year']['expected']:,} new jobs a year within "
                           f"{MARKET_MILES} miles ({jobs['new_jobs_per_year']['low']:,} to {jobs['new_jobs_per_year']['high']:,}). "
                           f"At {A['sq_ft_per_job']:g} sq ft a job that is about {round(work_need['expected'][future[0]], -2):,.0f} sq ft of "
                           f"offices, clinics and business space a year. Industrial and office projects on the city's lists come to about "
                           f"{round(cum_pipe, -3):,.0f} sq ft over ten years.")

    # ---- the site's own land
    uses = programme_of(plans)
    pools = {"homes": need, "shops": shop_need, "work": work_need}
    known = {"homes": ok, "shops": shops["available"], "work": jobs["available"]}
    taken = take_up(uses, pools, A, years, known) if ok else []
    # the same take-up if growth runs along the low or the high line: the year each use is filled, or None when
    # that is after the last forecast year
    for line in ("low", "high"):
        other = take_up(uses, {k: {"expected": v[line]} for k, v in pools.items()}, A, years, known) if ok else []
        when = {u["id"]: u["filled_in"] for u in other}
        for u in taken:
            u[f"filled_in_if_{line}"] = when.get(u["id"])
    not_forecast = [{"id": use, "label": uses[use]["label"], "acres": uses[use]["acres"],
                     "why": ("Household income did not answer, so the shop space that growth supports cannot be worked out."
                             if kind == "shops" else "The regional plan's jobs forecast did not answer."
                             if kind == "work" else "No reading of growth answered.")}
                    for use, _, kind in PROGRAMME if uses.get(use, {}).get("amount") and not known.get(kind)]
    steps, after = periods_of(taken, uses, A, years) if taken else ([], [])
    site_trips = {}
    for y in future:
        site_trips[y] = round(sum(u["trips"] * u["by_year"][y - future[0]]["so_far"] / u["amount"] for u in taken if u["amount"]))
    programme = {"available": bool(taken), "uses": taken, "steps": steps, "after": after, "not_forecast": not_forecast,
                 "acres": round(sum(u["acres"] for u in uses.values()), 1),
                 "trips_at_build_out": sum(u["trips"] for u in uses.values())}

    # ---- traffic
    stations = ((parts.get("state_highway_traffic") or {}).get("stations")) or []
    traffic = {"available": False, "rows": []}
    if stations and wide["available"]:
        st = stations[0]
        today = max(num(st.get("vehicles_per_day_behind")) or 0, num(st.get("vehicles_per_day_ahead")) or 0)
        if today:
            rate = {s: wide["rates_pct"][s] / 100 * A["traffic_follow_pct"] / 100 for s in SCENARIOS}
            traffic.update(available=True, highway={"route": st.get("route"), "where": (st.get("where") or "").title(),
                                                    "miles_away": st.get("miles_away"), "today": round(today)})
            for y in years[1:]:
                traffic["rows"].append({"year": y, "highway": {s: round(today * (1 + rate[s]) ** (y - year), -2) for s in SCENARIOS},
                                        "site_trips": site_trips.get(y, 0)})
            five, ten = traffic["rows"][5]["highway"], traffic["rows"][-1]["highway"]
            traffic["summary"] = (f"Route {st.get('route')} at {traffic['highway']['where']} carries about {today:,.0f} vehicles a day "
                                  f"(Caltrans' latest count). If traffic follows the homes within {max(RINGS)} miles, that is about "
                                  f"{five['expected']:,.0f} a day by {year + 5} and {ten['expected']:,.0f} by {year + HORIZON} "
                                  f"({ten['low']:,.0f} to {ten['high']:,.0f})."
                                  + (f" The site itself adds about {programme['trips_at_build_out']:,} trips a day once everything is built."
                                     if programme["trips_at_build_out"] else ""))

    # ---- in words
    advice = []
    if ok:
        said = "; ".join(f"{r['label'].lower()}: {r['rate_pct']:g}% a year" for r in market["readings"])
        advice.append(f"Homes within {MARKET_MILES} miles: {said}. The forecast follows the middle reading, "
                      f"{market['rates_pct']['expected']:g}% a year, with the lowest and highest as its range."
                      if len(market["readings"]) > 1 else
                      f"Only one reading of growth answered ({said}), so the low and high lines are the same as the expected line.")
        if homes.get("pipeline_covers_years") is not None:
            c = homes["pipeline_covers_years"]
            advice.append("Homes already on the city's lists cover about "
                          f"{c:g} years of the expected need. "
                          + ("New housing land here competes with a full pipeline for the next few years; the opening is later in the decade."
                             if c >= 6 else "The pipeline is thinner than the need: housing land is likely to find a buyer early."
                             if c <= 3 else "Housing land should sell through the decade at a steady pace."))
        slow = [u for u in taken if u["pct_by_year_10"] < 60]
        quick = [u for u in taken if u["filled_in"]]
        if quick:
            def span(u):
                fast = f"{u['filled_in_if_high']} if growth runs high" if u["filled_in_if_high"] else ""
                slow = f"{u['filled_in_if_low']} if it runs low" if u["filled_in_if_low"] else f"after {years[-1]} if it runs low"
                return "; ".join(x for x in (fast, slow) if x)
            advice.append("First to sell: " + ", ".join(f"{u['label'].lower()} ({u['acres']:g} acres, filled by about {u['filled_in']}; {span(u)})"
                                                        for u in quick) + ".")
        for u in slow:
            when = f"around {u['filled_later_in']}" if u["filled_later_in"] else "not within a lifetime"
            advice.append(f"{u['label']}: only {u['pct_by_year_10']}% of the {u['acres']:g} acres is taken up by {years[-1]} at this pace "
                          f"(filled {when}). Either it draws on more than the growth nearby, or part of that land suits another use. "
                          "Worth raising with the city before fixing the mix.")
    else:
        limits.append("No reading of growth answered for this site (the Census and the regional plan), so there is no year-by-year forecast yet.")
    if income.get("available"):
        advice.append(income["summary"] + (f" About {income['renters_pct']:g}% of households rent." if income.get("renters_pct") is not None else ""))
    if traffic.get("summary"):
        advice.append(traffic["summary"])
    updated = pipe["lists_updated"]
    old = [f"{name} ({day})" for name, day in updated.items() if day and int(day[:4]) <= year - 2]
    if old:
        limits.append("The city's list of " + " and ".join(old) + " has not been updated lately: some projects on it may be finished, and newer ones are missing.")
    if pipe["projects_without_sizes"]:
        limits.append(f"{pipe['projects_without_sizes']} projects on the city's lists within {MARKET_MILES} miles do not state a number of homes or a building size, so they are not counted.")
    limits += [
        "Shops that exist today are not counted (no public list of them), so the forecast shows what growth adds, not whether the area is short of shops now.",
        "Traffic counts by year are not published as open data: highway traffic is today's count, grown with the homes around it.",
        "Census blocks and planning zones that a ring only partly covers are shared out by area, as if people were spread evenly.",
        "Growth is drawn as a steady yearly rate. Real building comes in waves with interest rates and the economy.",
        "Income is the Census Bureau's survey estimate, in the survey's dollars. Nothing is adjusted for inflation.",
    ]

    headline = []
    if ok:
        t0, t5, t10 = market["rows"][1], market["rows"][6], market["rows"][-1]
        headline = [
            {"label": f"People within {MARKET_MILES} miles, {year}", "value": t0["people"]["expected"], "unit": "people",
             "note": f"estimate; {market['counted'][str(counted_year)]['people']:,} counted in {counted_year}"},
            {"label": f"By {year + 5}", "value": t5["people"]["expected"], "unit": "people",
             "low": t5["people"]["low"], "high": t5["people"]["high"]},
            {"label": f"By {year + HORIZON}", "value": t10["people"]["expected"], "unit": "people",
             "low": t10["people"]["low"], "high": t10["people"]["high"]},
            {"label": "New homes needed a year", "value": round(need["expected"][future[0]], -1), "unit": "homes",
             "low": round(need["low"][future[0]], -1), "high": round(need["high"][future[0]], -1)},
        ]
        if shops["available"]:
            headline.append({"label": "New shop space supported a year", "value": round(shop_need["expected"][future[0]], -2), "unit": "sq ft",
                             "low": round(shop_need["low"][future[0]], -2), "high": round(shop_need["high"][future[0]], -2)})
        if income.get("available"):
            headline.append({"label": "Typical household income", "value": income["typical"], "unit": "$",
                             "note": f"census survey {income.get('survey') or ''}".strip()})

    for name, what, part in (("2020 Census", "People and homes counted", "people"), ("2010 Census", "People and homes ten years before", "people_before"),
                             ("Regional plan (SCAG)", "Households and jobs forecast to 2035 and 2050", "regional_plan"),
                             ("Census survey", "Income, renters and owners by census tract", "tracts"),
                             ("City project lists", "Homes and buildings on the way", "projects"),
                             ("Caltrans", "Highway traffic count", "state_highway_traffic")):
        sources.append({"name": name, "what": what, "answered": bool(parts.get(part))})
    for r in rings:
        r.pop("_homes", None)
    figures = [{"id": k, "label": v[0], "unit": v[1], "value": A[k], "start": v[2], "group": v[3], "lowest": v[4], "highest": v[5],
                "yours": k in settings["assumptions"]} for k, v in ASSUMPTIONS.items()]
    stages = [{"label": label, "from_year": year + a, "to_year": year + b, "uncertain": unsure} for _, label, a, b, unsure in STAGES]
    return {"site": site, "year": year, "years": years, "background_year": years[0], "market_miles": MARKET_MILES,
            "available": ok, "headline": headline, "advice": advice, "rings": rings, "income": income, "homes": homes,
            "shops": shops, "jobs": jobs, "traffic": traffic, "programme": programme, "figures": figures,
            "stages": stages, "sources": sources, "limits": limits, "settings": settings,
            "edited": bool(settings["assumptions"]),
            "city_forecast": (parts.get("regional_plan") or {}).get("city")}
