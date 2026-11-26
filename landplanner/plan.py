"""A first land-use plan for one parcel, worked out from its public facts by rules of thumb a planner would
recognise. Plain functions, no network: `make_plan(parcel, parts, settings, kind_of)` takes the facts the app
already holds and returns everything the Plan page shows.

Two kinds of numbers are kept apart all the way to the screen:
  measured     read from a public record (traffic counts, census counts, the city's project list, ground heights)
  assumption   a starting figure the owner is expected to replace (prices, costs, trip rates)
Every reason carries the source it rests on. Nothing here is the city's decision or an offer from a buyer.
"""
import math
import re
import statistics

from . import geometry as G
from .words import counted

USES = (
    {"id": "retail", "label": "Shops and restaurants", "short": "Shops", "colour": "#d9455f"},
    {"id": "office", "label": "Offices and medical", "short": "Offices", "colour": "#8a6bbd"},
    {"id": "apartments", "label": "Apartments and townhomes", "short": "Apartments", "colour": "#e08a2e"},
    {"id": "homes", "label": "Houses", "short": "Houses", "colour": "#f4d35e"},
    {"id": "business", "label": "Business park and light industry", "short": "Business park", "colour": "#5b8fb9"},
    {"id": "park", "label": "Parks, open space and drainage", "short": "Parks", "colour": "#3f9d68"},
)
USE_IDS = tuple(u["id"] for u in USES)
BUILT = ("retail", "office", "apartments", "homes", "business")
# How a use sits with today's zoning. With the city's own table of allowed uses (landplanner/uses.py) each use is
# allowed outright, allowed with a permit, or not allowed; the words then come from the table's answer. Without
# that table (a city whose code has not been read) only the family of the zone is known, and these words are used:
# "fits" then means "this is what the zone is for", which the page says.
FIT_WORDS = {"fits": "What the zone is for", "permit": "Allowed with a permit",
             "review": "Depends on the city's review", "change": "Needs a zoning change", "unknown": "Zoning not listed"}

# id: (label, unit, starting value, group). All of these are assumptions the owner can change.
ASSUMPTIONS = {
    "homes_per_acre": ("Houses per acre", "homes/acre", 4.5, "How much fits"),
    "apartments_per_acre": ("Apartments per acre", "homes/acre", 20.0, "How much fits"),
    "retail_far": ("Shop floor space, as a share of the land", "ratio", 0.22, "How much fits"),
    "office_far": ("Office floor space, as a share of the land", "ratio", 0.30, "How much fits"),
    "business_far": ("Business park floor space, as a share of the land", "ratio", 0.38, "How much fits"),
    "people_per_home": ("People per house", "people", 3.0, "People"),
    "people_per_apartment": ("People per apartment", "people", 2.3, "People"),
    "park_acres_per_1000": ("Park land per 1,000 new residents", "acres", 5.0, "Parks and drainage"),
    "drainage_share_pct": ("Land set aside for drainage basins", "% of the site", 6.0, "Parks and drainage"),
    "trips_home": ("Trips a day per house", "trips", 9.4, "Traffic"),
    "trips_apartment": ("Trips a day per apartment", "trips", 6.7, "Traffic"),
    "trips_retail": ("Trips a day per 1,000 sq ft of shops", "trips", 37.0, "Traffic"),
    "trips_office": ("Trips a day per 1,000 sq ft of offices", "trips", 10.8, "Traffic"),
    "trips_business": ("Trips a day per 1,000 sq ft of business park", "trips", 8.0, "Traffic"),
    "peak_share_pct": ("Share of a day's trips in the busiest hour", "%", 10.0, "Traffic"),
    "jobs_retail": ("Jobs per 1,000 sq ft of shops", "jobs", 2.0, "Jobs and taxes"),
    "jobs_office": ("Jobs per 1,000 sq ft of offices", "jobs", 3.3, "Jobs and taxes"),
    "jobs_business": ("Jobs per 1,000 sq ft of business park", "jobs", 1.2, "Jobs and taxes"),
    "value_home": ("Finished value of a house", "$", 600000.0, "Jobs and taxes"),
    "value_apartment": ("Finished value of an apartment", "$", 330000.0, "Jobs and taxes"),
    "value_retail_sqft": ("Finished value of shops", "$/sq ft", 350.0, "Jobs and taxes"),
    "value_office_sqft": ("Finished value of offices", "$/sq ft", 320.0, "Jobs and taxes"),
    "value_business_sqft": ("Finished value of business park buildings", "$/sq ft", 210.0, "Jobs and taxes"),
    "property_tax_pct": ("Property tax a year (California's base rate)", "% of value", 1.0, "Jobs and taxes"),
    "retail_sales_per_sqft": ("Shop sales a year", "$/sq ft", 350.0, "Jobs and taxes"),
    "sales_tax_city_pct": ("The city's share of sales tax", "% of sales", 1.0, "Jobs and taxes"),
    "price_retail": ("Sale price of shop land", "$/acre", 870000.0, "Land prices"),
    "price_office": ("Sale price of office land", "$/acre", 650000.0, "Land prices"),
    "price_apartments": ("Sale price of apartment land, for each apartment it is approved for", "$/apartment", 50000.0, "Land prices"),
    "price_homes": ("Sale price of house land, for each approved house lot", "$/lot", 135000.0, "Land prices"),
    "price_business": ("Sale price of business park land", "$/acre", 610000.0, "Land prices"),
    "cost_planning_per_acre": ("Planning, engineering and city approvals", "$/acre", 12000.0, "Costs"),
    "cost_grading_per_acre": ("Shaping the ground (mass grading)", "$/acre", 40000.0, "Costs"),
    "cost_street_per_ft": ("Main streets inside the site", "$/ft", 950.0, "Costs"),
    "cost_wet_per_ft": ("Water, sewer and storm drain in those streets", "$/ft", 480.0, "Costs"),
    "cost_dry_per_ft": ("Power, gas and communications in those streets", "$/ft", 220.0, "Costs"),
    "cost_basin_per_acre": ("Drainage basins", "$/acre", 160000.0, "Costs"),
    "cost_park_per_acre": ("Parks and landscaping", "$/acre", 280000.0, "Costs"),
    "cost_signal_each": ("A new traffic signal", "$ each", 550000.0, "Costs"),
    "contingency_pct": ("Allowance for surprises", "% of costs", 15.0, "Costs"),
    "fees_total": ("City and agency fees (not covered yet: type your figure)", "$", 0.0, "Costs"),
}
SLOPE_FACTOR = {"nearly flat": 1.0, "gentle": 1.25, "moderate": 1.7, "steep": 2.4}


def num(v, default=None):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if f == f and abs(f) < 1e15 else default


def reason(text, effect, source):
    return {"text": text, "effect": effect, "source": source}


def say(n, digits=0):
    """A number with thousands commas. digits may be negative to round to tens or hundreds: say(1234, -1) -> "1,230"."""
    return f"{round(n, digits):,.{max(digits, 0)}f}"


def a_class(name):
    """"an Urban Arterial street", "a Major street"."""
    name = str(name or "").strip() or "classed"
    return ("an " if name[0].lower() in "aeiou" else "a ") + name + " street"


# ---------------------------------------------------------------- the facts, tidied for the rules

def zoning_fit(kind, code, kind_of):
    """How each use sits with the zoning, from the family the zone belongs to. Only used for a city whose own
    table of allowed uses is not held (see gather): "fits" then means "this is what the zone is for", not "permitted"."""
    code = str(code or "").strip().upper()
    table = {
        "commercial": {"retail": "fits", "office": "fits"},
        "business": {"business": "fits", "office": "fits", "retail": "review"},
        "denser-housing": {"apartments": "fits", "homes": "fits"},
        "low-density": {"homes": "fits"},
        "rural": {"homes": "fits"},
        "specific-plan": {u: "review" for u in BUILT},
        "open-space": {}, "public": {},
    }
    if kind == "edc":
        if code.endswith(("NG", "SG")):
            fit = {"business": "fits", "retail": "fits", "office": "fits", "apartments": "review"}
        elif code.endswith("CC"):
            fit = {"retail": "fits", "office": "fits", "apartments": "fits", "business": "review"}
        else:
            fit = {"retail": "fits", "office": "fits", "apartments": "review", "business": "review"}
    elif kind == "mixed":
        order = ("fits", "review", "change")
        parts = [zoning_fit(kind_of(p), p, kind_of) for p in re.split(r"\s*&\s*", code) if p]
        fit = {u: min((p.get(u, "change") for p in parts), key=order.index, default="change") for u in BUILT}
    elif kind == "other":
        return {u: "unknown" for u in BUILT} | {"park": "fits"}
    else:
        fit = table.get(kind, {})
    return {u: fit.get(u, "change") for u in BUILT} | {"park": "fits"}


def density_from_plan(general_plan, zoning_name):
    """Homes per acre or floor-area ratio when the city's own general plan wording states a range."""
    text = " ".join(str(x or "") for x in ((general_plan or {}).get("description"), (general_plan or {}).get("label"), zoning_name))
    out = {}
    m = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*du/ac", text)
    if m:
        out["homes_range"] = (float(m.group(1)), float(m.group(2)))
    m = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*FAR", text)
    if m:
        out["far_range"] = (float(m.group(1)), float(m.group(2)))
    m = re.search(r"(\d+(?:/\d+)?)\s*-?\s*ac(?:re)?\s*min", text)
    if m:
        a, _, b = m.group(1).partition("/")
        out["lot_acres"] = float(a) / float(b) if b else float(a)
    return out


MIN_LOT = re.compile(r"(\d+(?:\.\d+)?(?:/\d+)?)\s*-?\s*ac(?:re)?s?\s*min", re.I)
RR_CODE = re.compile(r"RR(\d+(?:/\d+)?)")


def lot_in(text):
    """The smallest lot, in acres, that a piece of the city's wording states ("2-acre minimum", "1/2 ac min"), or None."""
    m = MIN_LOT.search(str(text or ""))
    if not m:
        return None
    top, _, bottom = m.group(1).partition("/")
    try:
        acres = float(top) / float(bottom) if bottom else float(top)
    except (ValueError, ZeroDivisionError):
        return None
    return acres if acres > 0 else None


def lot_rule(parcel, parts, kind, stated):
    """What the zones on a parcel say about the smallest lot, or None when no zone's lot size can be read.
    Read from the city's own description of each zone (the parcel's "zoning_name" has one piece per zone), from the
    zone code where the code itself carries the size (RR2, RR1/2), and from the city's wording for the zone at the
    parcel's middle. A zone whose size cannot be read is left out, never guessed. With several zones the larger lot
    is the one to use (fewer homes): {"acres": the larger lot, "zones": [(code, acres)], "unread": [codes]}."""
    codes = [re.sub(r"\s*-\s*", "-", c.strip()) for c in str(parcel.get("zoning") or "").split("&") if c.strip()]
    words = [w.strip() for w in str(parcel.get("zoning_name") or "").split(" + ")]
    if len(words) != len(codes):
        words = [""] * len(codes)
    point = parts.get("zoning") or {}
    found, unread = [], []
    for code, name in zip(codes, words):
        acres = lot_in(name)
        if acres is None and (m := RR_CODE.fullmatch(code.upper())):
            acres = lot_in(m.group(1) + " ac min")
        if acres is None and str(point.get("abbrev") or "").strip().upper() == code.upper():
            acres = lot_in(point.get("general_plan_says")) or lot_in(point.get("what_it_allows"))
        if acres is None and len(codes) == 1 and kind == "rural":
            acres = stated.get("lot_acres")
        if acres:
            found.append((code, acres))
        else:
            unread.append(code)
    if not found:
        return None
    return {"acres": max(a for _, a in found), "zones": found, "unread": unread}


def gather(parcel, parts, kind_of):
    """Everything the rules look at, in one flat dictionary, plus the frame the layout is drawn in."""
    acres = num(parcel.get("acres"), 0.0) or 0.0
    centre = parcel["centre"]
    frame = G.Frame(centre["lon"], centre["lat"])
    rings = ((parcel.get("outline") or {}).get("coordinates")) or []
    polys = [frame.ring(r) for r in rings if len(r) >= 4]
    outline = max(polys, key=G.area) if polys else []
    measured = G.rings_acres(rings)
    recorded = acres
    if G.differs(recorded, measured):
        acres = round(measured, 1)
    F = {"acres": acres, "recorded_acres": recorded, "outline_acres": round(measured, 1) if measured else None,
         "zoning": parcel.get("zoning") or "", "zoning_kind": parcel.get("zoning_kind") or "other",
         "zoning_name": parcel.get("zoning_name") or "", "fire": str(parcel.get("fire_hazard_zone") or ""),
         "several_pieces": len(polys) > 1, "missing": []}
    F["fit"] = zoning_fit(F["zoning_kind"], F["zoning"], kind_of)
    # the city's own table of allowed uses, when the app holds it: each use is then allowed outright, allowed with
    # a permit, or not allowed, as the table says, and the family of the zone is no longer used
    rules = parts.get("allowed_uses")
    F["rules"] = rules if rules and rules.get("basis") == "table" and rules.get("uses") else None
    if F["rules"]:
        F["fit"] = {u: (F["rules"]["uses"].get(u) or {}).get("fit") or "unknown" for u in BUILT} | {"park": "fits"}
    F["stated"] = density_from_plan(parts.get("general_plan"), F["zoning_name"])
    F["lot_rule"] = lot_rule(parcel, parts, F["zoning_kind"], F["stated"])

    # what surrounds it, by zoning family, leaving this parcel out
    around = parts.get("surroundings")
    if around:
        by_kind, total = {}, 0.0
        for row in around.get("by_zoning", []):
            a = num(row.get("acres"), 0.0)
            if (row.get("zoning") or "") == F["zoning"]:
                a = max(0.0, a - acres)
            by_kind[row.get("zoning_kind") or "other"] = by_kind.get(row.get("zoning_kind") or "other", 0.0) + a
            total += a
        share = (lambda *kinds: 100 * sum(by_kind.get(k, 0.0) for k in kinds) / total) if total > 0 else (lambda *k: 0.0)
        F["around"] = {"miles": around.get("within_miles"), "housing_pct": round(share("low-density", "rural", "denser-housing"), 1),
                       "jobs_pct": round(share("edc", "commercial", "business"), 1),
                       "open_pct": round(share("open-space"), 1), "planned_pct": round(share("specific-plan"), 1)}
    else:
        F["around"] = None
        F["missing"].append("the zoning around the parcel")

    highway = parts.get("state_highway_traffic")
    station = (highway or {}).get("stations", [None])[0] if (highway or {}).get("stations") else None
    if station:
        counts = [num(station.get(k)) for k in ("vehicles_per_day_behind", "vehicles_per_day_ahead")]
        counts = [c for c in counts if c]
        F["highway"] = {"route": station.get("route"), "where": str(station.get("where") or "").title(),
                        "miles": num(station.get("miles_away"), 99.0), "per_day": max(counts) if counts else None,
                        "lat": station.get("lat"), "lon": station.get("lon")}
    else:
        F["highway"] = None
        if highway is None:
            F["missing"].append("highway traffic counts")

    people = parts.get("people")
    F["people"] = {int(r["miles"]): r for r in (people or {}).get("rings", [])} or None
    if not F["people"]:
        F["missing"].append("the census count of people nearby")

    # streets: how close each named street of the city's planned network comes to the parcel's edge
    F["streets"], F["street_lines"] = [], []
    streets = parts.get("streets")
    if streets and outline:
        best, middle = {}, G.centroid(outline)
        for s in streets.get("streets", []):
            for path in s.get("paths", []):
                line = [frame.xy(p[0], p[1]) for p in path]
                if len(line) < 2:
                    continue
                F["street_lines"].append({"name": s["name"], "class": s["class"], "rank": s["rank"], "path": path})
                d, on_edge, _ = G.path_to_poly(line, outline)
                if G.inside(outline, line[len(line) // 2]):
                    d = 0.0
                # "toward": the point of the street nearest the middle of the parcel, so "the side facing the
                # street" is square to the street and not pulled toward whichever corner happens to be closest
                reach, toward = G.near_on_path(line, middle)
                known = best.get(s["name"])
                if not known or d < known["feet"]:
                    best[s["name"]] = {"name": s["name"], "class": s["class"], "rank": s["rank"], "speed_mph": s.get("speed_mph"),
                                       "feet": round(d), "at": on_edge, "toward": toward, "reach": reach}
                elif d <= known["feet"] + 1 and reach < known["reach"]:
                    known.update(toward=toward, reach=reach)
        F["streets"] = sorted(best.values(), key=lambda s: (s["feet"] > 150, -s["rank"], s["feet"]))
    elif streets is None:
        F["missing"].append("the city's street map")
    fronting = [s for s in F["streets"] if s["feet"] <= 150]
    F["frontage"] = fronting[0] if fronting else None
    F["corner"] = next((s for s in fronting[1:] if s["name"] != fronting[0]["name"]), None) if fronting else None

    signals = parts.get("signals")
    F["signals"] = (signals or {}).get("signals", [])
    F["signals_known"] = signals is not None
    if signals is None:
        F["missing"].append("the city's map of traffic signals")
    projects = parts.get("projects")
    F["projects"] = (projects or {}).get("projects", [])
    F["projects_updated"] = (projects or {}).get("lists_updated") or {}
    if projects is None:
        F["missing"].append("the city's list of development projects")
    F["schools"] = (parts.get("schools") or {}).get("schools", [])

    surface = (parts.get("surface") or {}).get("inside") if parts.get("surface") else None
    five = parts.get("terrain")
    if surface and surface.get("typical_slope_pct") is not None:
        F["ground"] = {"slope_pct": surface["typical_slope_pct"], "steep_pct": surface.get("steepest_tenth_pct"),
                       "reading": surface.get("reading"), "range_ft": surface.get("range_ft"),
                       "low_at": surface.get("low_at"), "detail": "ground heights across the parcel"}
    elif five:
        F["ground"] = {"slope_pct": five.get("rough_slope_pct"), "steep_pct": None, "reading": five.get("reading"),
                       "range_ft": five.get("fall_across_site_ft"), "low_at": None, "detail": "five spot heights only"}
    else:
        F["ground"] = None

    # what nearby projects on the city's list say about how much gets built on an acre here
    houses, flats, shops, sheds = [], [], [], []
    for p in F["projects"]:
        st, kind = p.get("stated") or {}, str(p.get("kind") or "").lower()
        a, homes, feet = num(st.get("acres")), num(st.get("homes")), num(st.get("building_sq_ft"))
        if kind.startswith("residential") and a and homes and a >= 3:
            (flats if homes / a > 9 else houses).append((homes / a, p["title"]))
        elif kind == "commercial" and a and feet and a >= 2 and 0.05 <= feet / (a * G.SQ_FT_PER_ACRE) <= 0.6:
            shops.append((feet / (a * G.SQ_FT_PER_ACRE), p["title"]))
        elif kind == "industrial" and a and feet and 0.1 <= feet / (a * G.SQ_FT_PER_ACRE) <= 0.7:
            sheds.append((feet / (a * G.SQ_FT_PER_ACRE), p["title"]))
    F["local"] = {"houses": houses, "flats": flats, "shops": shops, "sheds": sheds}
    return F, frame, outline


STREET_SHARE = 0.85      # the share of rural land that is lots; the rest is streets


def lot_basis(lot):
    """The reason for a homes-an-acre figure that comes from the zones' smallest lots, in words."""
    top = lot["acres"]
    if len(lot["zones"]) == 1:
        ask = f"The zone ({lot['zones'][0][0]}) asks for lots of at least {counted(top, 'acre')}"
    else:
        sizes = " and ".join(f"{counted(a, 'acre')} ({c})" for c, a in lot["zones"])
        ask = (f"The zones on this parcel ask for lots of at least {sizes}. The larger lot, {counted(top, 'acre')}, "
               f"is used for all of the land")
    text = (f"{ask}, so at most {counted(round(1 / top, 2), 'home')} an acre. With {round((1 - STREET_SHARE) * 100):g}% of the "
            f"land left for streets, that comes to {round(STREET_SHARE / top, 2):g}.")
    if lot["unread"]:
        text += (f" The city's wording gives no lot size for {', '.join(lot['unread'])}, "
                 f"so {'that zone is' if len(lot['unread']) == 1 else 'those zones are'} not counted.")
    return text


def starting_figures(F):
    """The assumptions, with the ones this parcel's own records can replace already replaced (and marked)."""
    out = {}
    for key, (label, unit, value, group) in ASSUMPTIONS.items():
        out[key] = {"id": key, "label": label, "unit": unit, "value": value, "start": value, "group": group,
                    "kind": "assumption", "basis": "A common planning figure. Replace it with your own."}

    def measured(key, value, basis):
        out[key].update(value=value, start=value, kind="measured", basis=basis)

    def typical(rows):
        return statistics.median(v for v, _ in rows), ", ".join(t for _, t in rows[:3])

    local, stated = F["local"], F["stated"]
    if F["zoning_kind"] in ("low-density", "denser-housing") and "homes_range" in stated:
        lo, hi = stated["homes_range"]
        key = "apartments_per_acre" if lo >= 8 else "homes_per_acre"
        measured(key, round((lo + hi) / 2, 1), f"The middle of the city's general plan range for this land: {lo:g} to {hi:g} homes an acre.")
    if out["homes_per_acre"]["kind"] == "assumption" and len(local["houses"]) >= 2:
        v, names = typical(local["houses"])
        measured("homes_per_acre", round(v, 1), f"The typical figure for {counted(len(local['houses']), 'housing tract')} on the city's project list nearby ({names}).")
    lot = F.get("lot_rule")
    if lot:
        # a zone's smallest lot is a ceiling on houses, whatever the neighbours' tracts or the plan's range suggest
        cap = round(STREET_SHARE / lot["acres"], 2)
        if cap < out["homes_per_acre"]["value"]:
            measured("homes_per_acre", cap, lot_basis(lot))
            out["homes_per_acre"]["lot_acres"] = lot["acres"]
    if out["apartments_per_acre"]["kind"] == "assumption" and local["flats"]:
        v, names = typical(local["flats"])
        measured("apartments_per_acre", round(v, 1), f"From apartment and condominium projects on the city's list nearby ({names}).")
    if "far_range" in stated and F["zoning_kind"] in ("commercial", "business"):
        lo, hi = stated["far_range"]
        key = "business_far" if F["zoning_kind"] == "business" else "retail_far"
        measured(key, round((lo + hi) / 2, 2), f"The middle of the city's general plan range for this land: {lo:g} to {hi:g}.")
    if out["retail_far"]["kind"] == "assumption" and len(local["shops"]) >= 2:
        v, names = typical(local["shops"])
        measured("retail_far", round(v, 2), f"The typical figure for {counted(len(local['shops']), 'commercial project')} on the city's list nearby ({names}).")
    if out["business_far"]["kind"] == "assumption" and local["sheds"]:
        v, names = typical(local["sheds"])
        measured("business_far", round(v, 2), f"From industrial projects on the city's list nearby ({names}).")
    ring = (F["people"] or {}).get(3) or (F["people"] or {}).get(1)
    if ring and ring.get("homes"):
        measured("people_per_home", round(ring["people"] / ring["homes"], 2),
                 f"People divided by homes within {ring['miles']} miles in the 2020 Census.")
    return out


# ---------------------------------------------------------------- scoring each use

def score_uses(F, count_zoning=True):
    """For each use: a score from 0 to 100 and the reasons behind it, each tied to a fact and its source.
    With count_zoning False ("Best use") the zoning is still stated but gives and takes no points: the score is
    then what the location alone supports."""
    hw, people, around, front, ground = F["highway"], F["people"], F["around"], F["frontage"], F["ground"]
    p3 = (people or {}).get(3, {}).get("people")
    p5 = (people or {}).get(5, {}).get("people")
    near = [p for p in F["projects"] if p["miles_away"] <= 2.0]
    of_kind = lambda *kinds: [p for p in near if str(p.get("kind") or "").lower().startswith(kinds)]  # noqa: E731
    out = {}

    def start(use, base):
        # the starting score is a reason like any other, so the points listed always add up to the score
        out[use] = {"score": base, "fit": F["fit"][use], "reasons": [
            reason(f"Every piece of land starts from {base} points for this use before anything about it is counted. "
                   "Each reason below adds to or takes away from that.", base, "Land Planner's own starting figure")]}

    def add(use, points, text, source):
        out[use]["score"] += points
        out[use]["reasons"].append(reason(text, points, source))

    def zoning(use, fits, review, change):
        fit, name = F["fit"][use], F["zoning"] or "none listed"
        if F.get("rules"):
            # read from the city's table of allowed uses: say what the table says, and where
            read = F["rules"]["uses"].get(use) or {}
            status, source = read.get("status"), "City development code" + (f", {read['table']}" if read.get("table") else "")
            row = (read.get("read_from") or [{}])[0].get("use")
            where = f"the {read.get('zone') or name} zone" if "&" in name else f"this zone ({name})"
            needs = f" The table adds: {read['requirements']}" if read.get("requirements") else ""
            if needs and not needs.endswith("."):
                needs += "."
            tail = "" if count_zoning else " Best use leaves zoning out of the score."
            if status == "outright":
                text, points = f"The city's table of allowed uses permits this outright in {where} (its row “{row}”).{needs}", fits
            elif status == "permit":
                text = (f"The city's table allows this in {where} only with a conditional use permit (its row “{row}”): "
                        f"a public hearing, and conditions the city sets.{needs}")
                points = round((fits + review) / 2)
            elif status == "no":
                text, points = (f"The city's table prohibits this in {where} (its row “{row}”), so it would need a zone change "
                                "through the city."), change
            elif status == "unlisted":
                text, points = (f"The city's table for {where} does not list this use, and the code says an unlisted use is "
                                "not permitted. It would need a zone change through the city."), change
            elif status == "plan":
                text, points = str(read.get("why") or "The uses here are set by a specific plan."), review
            else:
                text, points = str(read.get("why") or "What this zone allows could not be read from the city's code."), 0
            add(use, points if count_zoning else 0, text + tail, source)
        elif not count_zoning:
            words = {"fits": "is meant for this", "review": "may allow this, depending on the city's review",
                     "unknown": "is not listed", "change": "is not meant for this, so it would need a zoning change through the city"}[fit]
            add(use, 0, f"The zoning today ({name}) {words}. Best use leaves zoning out of the score.", "City zoning")
        elif fit == "fits":
            add(use, fits, f"The zoning today ({name}) is meant for this.", "City zoning")
        elif fit == "review":
            add(use, review, f"The zoning today ({name}) may allow this, depending on the city's review or the area's own plan.", "City zoning")
        elif fit == "unknown":
            add(use, 0, "No zoning is listed for this parcel, so the zoning says nothing either way.", "City zoning")
        else:
            add(use, change, f"The zoning today ({name}) is not meant for this: it would need a zoning change through the city.", "City zoning")

    def highway(use, close, mid):
        if not hw or not hw["per_day"]:
            return
        text = f"Route {hw['route']} carries about {say(hw['per_day'])} vehicles a day at {hw['where']}, {counted(hw['miles'], 'mile')} away."
        scale = min(1.0, hw["per_day"] / 100000)
        if hw["miles"] <= 1.0:
            add(use, round(close * scale), text + " That is close enough to draw passing traffic.", "Caltrans")
        elif hw["miles"] <= 2.5:
            add(use, round(mid * scale), text + " Close enough to reach easily, not close enough to be seen from it.", "Caltrans")
        else:
            add(use, -5, text + " That is a long way from the nearest state highway.", "Caltrans")

    def street(use, big, small, none):
        if front and front["rank"] >= 3:
            add(use, big, f"The parcel fronts {front['name']}, which the city classes as {a_class(front['class'])}"
                + (f" (and {F['corner']['name']} as well: a corner)." if F["corner"] else "."), "City street map")
        elif front:
            add(use, small, f"The parcel fronts {front['name']}, {a_class(front['class'])}: a smaller street than shops and offices look for.", "City street map")
        elif F["streets"]:
            s = F["streets"][0]
            add(use, none, f"No street on the city's planned network touches the parcel; the nearest is {s['name']}, about {say(s['feet'])} ft away.", "City street map")

    # shops
    start("retail", 30)
    zoning("retail", 15, 5, -12)
    highway("retail", 20, 10)
    street("retail", 18, 6, -15)
    if p3 is not None:
        text = f"{say(p3)} people lived within 3 miles in the 2020 Census."
        add("retail", 15 if p3 >= 50000 else 8 if p3 >= 25000 else 0 if p3 >= 10000 else -10,
            text + (" Enough for a centre with a supermarket and more." if p3 >= 25000 else " A thin market for new shops."), "2020 Census")
    rivals = [p for p in of_kind("commercial", "mixed") if (p.get("stated") or {}).get("building_sq_ft", 0) >= 50000]
    if rivals:
        feet = sum(p["stated"]["building_sq_ft"] for p in rivals)
        add("retail", -6 if feet >= 300000 else -3,
            f"{counted(len(rivals), 'large commercial project')} {'is' if len(rivals) == 1 else 'are'} already on the city's list within 2 miles ({', '.join(p['title'] for p in rivals[:3])}): "
            f"about {say(feet)} sq ft of competing space.", "City project list")

    # offices and medical
    start("office", 22)
    zoning("office", 15, 5, -12)
    highway("office", 8, 6)
    street("office", 8, 3, -8)
    if p5 is not None:
        add("office", 10 if p5 >= 100000 else 4 if p5 >= 40000 else -5,
            f"{say(p5)} people lived within 5 miles in the 2020 Census: the patients and customers offices and clinics serve.", "2020 Census")

    # apartments and townhomes
    start("apartments", 30)
    zoning("apartments", 22, 8, -15)
    street("apartments", 10, 5, -5)
    if hw and hw["miles"] <= 2.5:
        add("apartments", 5, f"Route {hw['route']} is {counted(hw['miles'], 'mile')} away: an easy commute, which renters look for.", "Caltrans")
    if around and around["jobs_pct"] >= 5:
        add("apartments", 8, f"{around['jobs_pct']:g}% of the land within {around['miles']:g} mile is zoned for shops, offices or jobs: places to walk or drive a short way to.", "City zoning")
    flats = [p for p in of_kind("residential") if re.search(r"apartment|condo|multi", p.get("description") or "", re.I)]
    if flats:
        add("apartments", 6, f"Apartments or condominiums are already on the city's list within 2 miles ({', '.join(p['title'] for p in flats[:3])}).", "City project list")

    # houses
    start("homes", 35)
    zoning("homes", 20, 8, -12)
    if around:
        pct = around["housing_pct"]
        add("homes", 18 if pct >= 50 else 9 if pct >= 25 else 0,
            f"{pct:g}% of the land within {counted(around['miles'], 'mile')} is zoned for housing" + (": houses would sit among houses." if pct >= 25 else ", so houses would not have many neighbours."), "City zoning")
    tracts = [p for p in of_kind("residential") if p not in flats]
    if tracts:
        builders = sorted({p["builder"] for p in tracts if p.get("builder")})
        add("homes", 10 if len(tracts) >= 3 else 5,
            f"{counted(len(tracts), 'housing tract')} {'is' if len(tracts) == 1 else 'are'} on the city's list within 2 miles" + (f" (builders named: {', '.join(builders[:4])})." if builders else "."), "City project list")
    if ground and ground["slope_pct"] is not None:
        s = ground["slope_pct"]
        add("homes", 5 if s < 5 else 0 if s < 10 else -10,
            f"The ground's typical slope is about {s:g}% ({ground['reading']}), from {ground['detail']}." + ("" if s < 10 else " Sloping ground makes lots costly to build."), "USGS")
    if hw and hw["miles"] <= 0.25:
        add("homes", -10, f"Route {hw['route']} is only {counted(hw['miles'], 'mile')} away: noise that houses are usually kept back from.", "Caltrans")
    close = [s for s in F["schools"] if s["miles_away"] <= 1.5 and "higher" not in s["grades"].lower()]
    if close:
        add("homes", 4, f"{close[0]['name']} is {counted(close[0]['miles_away'], 'mile')} away.", "City schools list")

    # business park
    start("business", 25)
    zoning("business", 28, 8, -20)
    highway("business", 20, 10)
    if ground and ground["slope_pct"] is not None:
        s = ground["slope_pct"]
        add("business", 10 if s < 3 else 3 if s < 6 else -10,
            f"Large buildings need flat pads; the typical slope here is about {s:g}% ({ground['reading']}).", "USGS")
    if F["acres"] >= 20:
        add("business", 5, f"At {counted(F['acres'], 'acre')} the parcel is big enough for buildings with truck yards.", "City parcel records")
    sheds = of_kind("industrial")
    if sheds:
        add("business", 8, f"Industrial projects are already on the city's list within 2 miles ({', '.join(p['title'] for p in sheds[:3])}).", "City project list")
    if around and around["housing_pct"] >= 60:
        add("business", -10, f"{around['housing_pct']:g}% of the land within {counted(around['miles'], 'mile')} is zoned for housing: trucks beside homes draw objections.", "City zoning")

    for use in out:
        raw = out[use]["score"]
        held = max(0, min(100, raw))
        if held != raw:
            # a score stays between 0 and 100; the points that were held back are listed too
            out[use]["reasons"].append(reason("A score is kept between 0 and 100, so the points beyond that are not counted.",
                                              held - raw, "Land Planner's own rule"))
        out[use]["score"] = held
    return out


# ---------------------------------------------------------------- sizing the mix

def retail_ceiling(F, scores):
    """How many acres of shops the people nearby can keep busy, by the usual sizes of shopping centres."""
    people, hw = F["people"] or {}, F["highway"]
    p3, p5 = people.get(3, {}).get("people"), people.get(5, {}).get("people")
    if p3 is None:
        return 12.0, "No census count was available, so shops are held to a neighbourhood centre (about 12 acres)."
    if p5 and p5 >= 150000 and hw and hw["miles"] <= 1.0 and (hw["per_day"] or 0) >= 80000:
        cap, name = 40.0, f"a regional centre (150,000 or more people within 5 miles; here {say(p5)}, beside a busy highway)"
    elif p3 >= 40000:
        cap, name = 25.0, f"a community centre (40,000 or more people within 3 miles; here {say(p3)})"
    elif p3 >= 10000:
        cap, name = 10.0, f"a neighbourhood centre (10,000 or more people within 3 miles; here {say(p3)})"
    else:
        cap, name = 4.0, f"a small corner centre (fewer than 10,000 people within 3 miles; here {say(p3)})"
    text = f"Shops are sized as {name}: up to about {counted(cap, 'acre')}."
    rivals = [r for r in scores["retail"]["reasons"] if "competing space" in r["text"]]
    if rivals and rivals[0]["effect"] <= -6:
        cap *= 0.6
        text += f" Cut to {counted(cap, 'acre')} because so much competing space is already on the city's list nearby."
    return cap, text


def suggest(F, scores, A, mode):
    """Acres for each use, and the notes that explain the sizes."""
    acres, notes = F["acres"], []
    allowed = [u for u in BUILT if mode == "best" or scores[u]["fit"] in ("fits", "permit", "review", "unknown")]
    if not allowed:
        # open space or public land: under today's zoning there is nothing to build
        return {u: (acres if u == "park" else 0.0) for u in USE_IDS}, notes, list(BUILT)
    ranked = sorted(allowed, key=lambda u: -scores[u]["score"])
    keep = [u for u in ranked if scores[u]["score"] >= 45] or ranked[:2]
    most = 1 if acres < 6 else 2 if acres < 15 else 3 if acres < 40 else 5
    keep = keep[:most]
    cap_retail, cap_text = retail_ceiling(F, scores)
    # ceilings: shops by the people nearby, offices small, and a use the zoning only "may allow" never dominates
    caps = {"retail": min(cap_retail, max(1.5, 0.35 * acres)), "office": max(3.0, 0.08 * acres)}
    if F["zoning_kind"] != "denser-housing":
        caps["apartments"] = max(4.0, (0.4 if scores["apartments"]["fit"] == "fits" else 0.25) * acres)
    if mode != "best" and scores["business"]["fit"] in ("review", "permit"):
        caps["business"] = max(4.0, 0.35 * acres)
    hard = ("retail", "office")                   # these two ceilings come from the market and are never stretched
    if set(keep) <= set(caps) and sum(caps[u] for u in keep) < 0.9 * acres:
        # every chosen use has a ceiling and together they do not fill the land: bring in the next best use
        spare = [u for u in ranked if u not in keep]
        if spare:
            keep.append(spare[0])
    floor = max(1.5, 0.03 * acres)
    held = [0.0]

    def share(buildable, uses):
        left, give, free = buildable, {}, list(uses)
        while free:
            weight = {u: (scores[u]["score"] - 35) ** 1.3 if scores[u]["score"] > 35 else 1.0 for u in free}
            total = sum(weight.values())
            over = [u for u in free if u in caps and left * weight[u] / total > caps[u]]
            if not over:
                give.update({u: left * weight[u] / total for u in free})
                break
            for u in over:
                give[u] = caps[u]
                left -= caps[u]
                free.remove(u)
        held[0] = 0.0
        if not free and left > 0.05:
            # every use hit its ceiling: the rest goes to the uses whose ceiling is only a rule of proportion;
            # if there is none, the land is held open rather than filled with more than the market supports
            soft = [u for u in uses if u not in hard]
            if soft:
                total = sum(give[u] for u in soft) or 1.0
                for u in soft:
                    give[u] += left * give[u] / total
            else:
                held[0] = left
        return give

    park = acres * A["drainage_share_pct"] / 100
    tenth = (F["ground"] or {}).get("steep_pct") or 0
    steep = 0.10 if tenth >= 25 else 0.05 if tenth >= 15 else 0.0
    give = {}
    for _ in range(4):
        give = share(acres - park, keep)
        small = [u for u in keep if give[u] < floor and len(keep) > 1]
        if small:
            keep = [u for u in keep if u != min(small, key=lambda u: give[u])]
            continue
        residents = give.get("homes", 0) * A["homes_per_acre"] * A["people_per_home"] + \
            give.get("apartments", 0) * A["apartments_per_acre"] * A["people_per_apartment"]
        wanted = acres * A["drainage_share_pct"] / 100 + residents / 1000 * A["park_acres_per_1000"] + acres * steep
        wanted = min(wanted, 0.3 * acres)
        if abs(wanted - park) < 0.05:
            break
        park = wanted
    give = share(acres - park, keep)
    residents = give.get("homes", 0) * A["homes_per_acre"] * A["people_per_home"] + \
        give.get("apartments", 0) * A["apartments_per_acre"] * A["people_per_apartment"]
    local_shops = min(12.0, round(residents / 1000 * 1.0, 1))
    if (mode == "best" and "retail" not in keep and local_shops >= 2 and acres >= 40
            and (give.get("homes", 0) + give.get("apartments", 0)) > 0.5 * acres):
        # a large new neighbourhood keeps a small shopping centre of its own busy
        source = max((u for u in ("homes", "apartments") if u in give), key=lambda u: give[u])
        give[source] -= local_shops
        give["retail"] = local_shops
        keep.append("retail")
        notes.append(f"A corner of neighbourhood shops ({counted(local_shops, 'acre')}) is added because the plan's own homes bring about "
                     f"{say(residents)} residents: about one acre of everyday shops for every 1,000 people is a common planning figure.")
    elif "retail" in give:
        notes.append(cap_text)
    give["park"] = park + held[0]
    if held[0] > 0.05:
        notes.append(f"{counted(held[0], 'acre', digits=1)} {'is' if counted(held[0], 'acre', digits=1).startswith('1.0 ') else 'are'} left open and held for later: the uses today's zoning is meant for are already at the size "
                     "the people nearby can support. Best use shows what else the location could carry.")
    homes = give.get("homes", 0) * A["homes_per_acre"] + give.get("apartments", 0) * A["apartments_per_acre"]
    if homes >= 1500:
        notes.append(f"About {say(homes)} homes is enough that the school district will usually ask for a school site "
                     "(roughly 10 to 12 acres for an elementary school). None is drawn here: ask the district early.")
    basins = acres * A["drainage_share_pct"] / 100
    parkland = max(0.0, park - basins - acres * steep)
    notes.append(f"Parks and drainage: {counted(basins, 'acre', digits=1)} of drainage basins ({A['drainage_share_pct']:g}% of the site)"
                 + (f", {counted(parkland, 'acre', digits=1)} of parks ({counted(A['park_acres_per_1000'], 'acre')} for every 1,000 new residents, the standard California cities may ask for)" if parkland > 0.05 else "")
                 + (f", and {counted(acres * steep, 'acre', digits=1)} of the steepest ground left open" if steep else "") + ".")
    dropped = [u for u in BUILT if u not in give]
    return {u: round(give.get(u, 0.0), 1) for u in USE_IDS}, notes, dropped


def settle(acres, total):
    """Round to a tenth of an acre and make the pieces add up to the parcel exactly."""
    acres = {u: max(0.0, round(num(acres.get(u), 0.0) or 0.0, 1)) for u in USE_IDS}
    gap = round(total - sum(acres.values()), 1)
    if abs(gap) >= 0.05 and any(acres.values()):
        acres[max(acres, key=acres.get)] = round(max(0.0, acres[max(acres, key=acres.get)] + gap), 1)
    return acres


def amounts(acres, A):
    """What each use amounts to: homes, floor space, people, jobs."""
    out = {u: {"acres": acres[u]} for u in USE_IDS}
    out["homes"].update(homes=round(acres["homes"] * A["homes_per_acre"]))
    out["apartments"].update(homes=round(acres["apartments"] * A["apartments_per_acre"]))
    for use, far in (("retail", "retail_far"), ("office", "office_far"), ("business", "business_far")):
        out[use].update(sq_ft=round(acres[use] * G.SQ_FT_PER_ACRE * A[far] / 100) * 100)
    out["homes"]["people"] = round(out["homes"]["homes"] * A["people_per_home"])
    out["apartments"]["people"] = round(out["apartments"]["homes"] * A["people_per_apartment"])
    for use in ("retail", "office", "business"):
        out[use]["jobs"] = round(out[use]["sq_ft"] / 1000 * A["jobs_" + use])
    return out


# ---------------------------------------------------------------- drawing it on the parcel

def draw(F, frame, outline, acres):
    """Cut the parcel's outline into one piece per use. Returns pieces, streets and the reasons for the placing."""
    if len(outline) < 3:
        return None
    centre = G.centroid(outline)
    toward = lambda p: G.unit((p[0] - centre[0], p[1] - centre[1]))  # noqa: E731
    why = []
    if F["frontage"]:
        front = toward(F["frontage"]["toward"])
        why.append(f"Shops and offices are placed along {F['frontage']['name']}, the busiest street the parcel fronts.")
    elif F["highway"] and F["highway"]["lat"]:
        front = toward(frame.xy(F["highway"]["lon"], F["highway"]["lat"]))
        why.append("No classed street touches the parcel, so the front is taken as the side facing the nearest state highway.")
    else:
        front = (0.0, -1.0)
        why.append("Nothing says which side is the front, so the south side is used. Check this on the ground.")
    side = G.perp(front)
    corner = toward(F["corner"]["toward"]) if F["corner"] else None
    if corner:
        why.append(f"Shops take the corner toward {F['corner']['name']}, where two classed streets meet.")
    hw = toward(frame.xy(F["highway"]["lon"], F["highway"]["lat"])) if F["highway"] and F["highway"]["lat"] else None
    low = (F["ground"] or {}).get("low_at")
    low = toward(frame.xy(low["lon"], low["lat"])) if low else None
    # which way along the street: toward the corner if there is one, else toward the highway. Only the sideways
    # part counts, so it never pulls a use off the street it is meant to face.
    def sideways(v):
        return None if not v or abs(G.dot(v, side)) < 0.15 else (side if G.dot(v, side) > 0 else (-side[0], -side[1]))

    along = sideways(corner) or sideways(hw) or side
    hw_side = sideways(hw) or along
    mix = lambda *terms: (sum(w * v[0] for w, v in terms if v), sum(w * v[1] for w, v in terms if v))  # noqa: E731
    pulls = {
        "retail": mix((1.0, front), (0.5, along)),
        "office": mix((0.75, front), (-0.3, along)),
        "apartments": mix((0.35, front), (-0.55, hw_side)),
        "homes": mix((-0.7, front), (-0.3, hw_side)),
        "business": mix((-0.1, front), (0.9, hw_side)),
        "park": mix((-0.45, front), (0.9, low)) if low else mix((-0.9, front), (0.2, side)),
    }
    if acres.get("business") and hw:
        why.append(f"The business park is placed on the side toward Route {F['highway']['route']}, so trucks reach the highway without passing homes.")
    if acres.get("homes"):
        why.append("Houses are placed at the back, away from the busy street.")
    if acres.get("park"):
        why.append("Parks and drainage basins are placed toward the lowest ground, where rainwater runs to." if low
                   else "Parks and drainage are placed at the back until the ground heights are read (they belong at the lowest ground).")
    items = [{"id": u, "area": acres[u] * G.SQ_FT_PER_ACRE, "pull": pulls[u]} for u in USE_IDS if acres.get(u, 0) > 0]
    pieces, cuts = G.layout(outline, items, front, side)
    drawn = G.area(outline) / G.SQ_FT_PER_ACRE
    out = {"pieces": [], "streets": [], "why": why, "drawn_acres": round(drawn, 1), "front": list(front),
           "note": "The parcel has more than one piece on the map; the plan is drawn on its largest piece." if F["several_pieces"] else ""}
    for piece in pieces:
        if len(piece["poly"]) < 3:
            continue
        c = G.centroid(piece["poly"])
        if not G.inside(piece["poly"], c):
            c = max(piece["poly"], key=lambda p: G.near_on_edge(outline, p)[0])
        out["pieces"].append({"use": piece["id"], "acres": acres[piece["id"]], "ring": frame.ring_ll(piece["poly"]),
                              "label_at": frame.ll(*c)})
    for a, b in cuts:
        out["streets"].append({"line": [frame.ll(*a), frame.ll(*b)], "feet": round(math.hypot(b[0] - a[0], b[1] - a[1]))})
    out["cut_ends"] = [p for a, b in cuts for p in (a, b)]
    return out


# ---------------------------------------------------------------- traffic

def traffic(F, frame, outline, drawing, amount, A):
    trips = {
        "homes": amount["homes"]["homes"] * A["trips_home"], "apartments": amount["apartments"]["homes"] * A["trips_apartment"],
        "retail": amount["retail"]["sq_ft"] / 1000 * A["trips_retail"], "office": amount["office"]["sq_ft"] / 1000 * A["trips_office"],
        "business": amount["business"]["sq_ft"] / 1000 * A["trips_business"],
    }
    total = sum(trips.values())
    out = {"by_use": {u: round(v) for u, v in trips.items() if v}, "per_day": round(total),
           "peak_hour": round(total * A["peak_share_pct"] / 100), "entrances": [], "signals_to_study": 0,
           "existing_signals": F["signals"][:6], "highway": F["highway"], "notes": []}
    if F["highway"] and F["highway"]["per_day"]:
        out["notes"].append(f"For scale: Route {F['highway']['route']} at {F['highway']['where']} carries about {say(F['highway']['per_day'])} "
                            f"vehicles a day; this plan would add about {say(total)} trips a day to the streets around the parcel.")
    if not outline:
        return out
    classed = [s for s in F["streets"] if s["feet"] <= 200]
    spots = []
    for s in classed:                                   # where each fronting street meets the parcel
        spots.append({"at": s["at"], "street": s, "made_by": "frontage"})
    for end in (drawing or {}).get("cut_ends", []):     # where the plan's own streets reach the edge
        near = None
        for s in F["street_lines"]:
            d, _ = G.near_on_path([frame.xy(p[0], p[1]) for p in s["path"]], end)
            if d <= 220 and (near is None or s["rank"] > near[1]["rank"]):
                near = (d, s)
        if near:
            spots.append({"at": end, "street": {"name": near[1]["name"], "class": near[1]["class"], "rank": near[1]["rank"]}, "made_by": "plan street"})
    spots.sort(key=lambda s: (-s["street"]["rank"], s["made_by"] != "plan street"))
    chosen = []
    for s in spots:
        if all(math.hypot(s["at"][0] - c["at"][0], s["at"][1] - c["at"][1]) > 450 for c in chosen):
            chosen.append(s)
    wanted = max(1, min(4, math.ceil(total / 9000))) if total else 0
    chosen = chosen[:max(wanted, 1)] if chosen else []
    each = total / len(chosen) if chosen else 0
    for s in chosen:
        lon, lat = frame.ll(*s["at"])
        nearest = min(F["signals"], key=lambda g: math.hypot(*[a - b for a, b in zip(frame.xy(g["lon"], g["lat"]), s["at"])]), default=None)
        feet = math.hypot(*[a - b for a, b in zip(frame.xy(nearest["lon"], nearest["lat"]), s["at"])]) if nearest else None
        if nearest and feet <= 600:
            # the page puts the verdict ("Uses a signal that is already there") in front of this text, so this adds only the where
            signal, text = "existing", f"The signal is at {nearest['street']} and {nearest['cross_street']}, about {say(feet, -1)} ft away."
        elif not F["signals_known"]:
            signal, text = "unknown", "The city's map of traffic signals did not answer."
        elif s["street"]["rank"] >= 3 and each >= 4000:
            signal, text = "study", f"About {say(each)} trips a day would use this entrance onto {a_class(s['street']['class'])}, more than a stop sign handles well."
            out["signals_to_study"] += 1
        else:
            signal, text = "none", f"About {say(each)} trips a day would use this entrance, few enough for a stop sign."
        out["entrances"].append({"lat": lat, "lon": lon, "street": s["street"]["name"], "class": s["street"]["class"],
                                 "signal": signal, "trips": round(each), "text": text})
    if not chosen and total:
        out["notes"].append("No classed city street touches the parcel, so where the entrances go cannot be worked out from the records. "
                            "Access is the first thing to settle with the city.")
    out["notes"].append("A traffic engineer's study, which the city will ask for, decides entrances and signals. These are the places to start it.")
    return out


# ---------------------------------------------------------------- money, jobs and who buys

def costs(F, drawing, acres, traffic_out, A, extra, total_acres):
    ground = F["ground"]
    factor = SLOPE_FACTOR.get((ground or {}).get("reading"), 1.25)
    feet = sum(s["feet"] for s in (drawing or {}).get("streets", [])) or round(math.sqrt(total_acres * G.SQ_FT_PER_ACRE))
    basins = total_acres * A["drainage_share_pct"] / 100 if acres["park"] else 0.0
    basins = min(basins, acres["park"])
    rows = [
        ("cost_planning_per_acre", total_acres, "acres", "the whole parcel"),
        ("cost_grading_per_acre", total_acres * factor, "acres", f"the whole parcel, times {factor:g} because the ground is {(ground or {}).get('reading') or 'not read yet'}"),
        ("cost_street_per_ft", feet, "ft", "the main streets this plan draws inside the parcel" if (drawing or {}).get("streets") else "one street across the parcel"),
        ("cost_wet_per_ft", feet, "ft", "the same streets"),
        ("cost_dry_per_ft", feet, "ft", "the same streets"),
        ("cost_basin_per_acre", basins, "acres", "the drainage basins"),
        ("cost_park_per_acre", max(0.0, acres["park"] - basins), "acres", "parks and open space"),
        ("cost_signal_each", traffic_out["signals_to_study"], "signals", "the new signals worth studying"),
    ]
    if not any(acres[u] for u in BUILT):      # nothing is built, so nothing is spent
        rows = [(k, 0.0, unit, why) for k, _, unit, why in rows]
    lines = [{"id": k, "label": ASSUMPTIONS[k][0], "unit_cost": A[k], "unit": ASSUMPTIONS[k][1], "quantity": round(q, 1),
              "quantity_unit": unit, "quantity_from": why, "amount": round(A[k] * q)} for k, q, unit, why in rows]
    subtotal = sum(line["amount"] for line in lines)
    allowance = round(subtotal * A["contingency_pct"] / 100)
    added = [{"name": str(x.get("name") or "Other cost")[:80], "amount": round(num(x.get("amount"), 0.0) or 0.0)}
             for x in (extra or [])[:60] if isinstance(x, dict)]
    total = subtotal + allowance + round(A["fees_total"]) + sum(x["amount"] for x in added)
    return {"lines": lines, "subtotal": subtotal, "contingency": allowance, "fees": round(A["fees_total"]), "extra": added,
            "total": total, "not_counted": ["City and agency fees (until you type them in)", "Improvements to the existing streets along the parcel's edge",
                                            "Streets and utilities inside each builder's own tract", "Interest, sales costs and taxes"]}


def money(parcel, acres, amount, cost, A, land_cost):
    priced = []
    for u in BUILT:
        if not acres[u]:
            continue
        by_home = u in ("homes", "apartments")
        quantity = amount[u]["homes"] if by_home else acres[u]
        priced.append({"use": u, "figure": "price_" + u, "price": A["price_" + u], "unit": ASSUMPTIONS["price_" + u][1],
                       "quantity": quantity, "quantity_unit": ("house lots" if u == "homes" else "apartments") if by_home else "acres",
                       "amount": round(quantity * A["price_" + u])})
    sales = {p["use"]: p["amount"] for p in priced}
    revenue = sum(sales.values())
    assessed = num(parcel.get("assessed_land_usd"))
    land = num(land_cost)
    stand_in = land is None
    if stand_in:
        land = assessed or 0.0
    if not priced:
        land = 0.0
    profit = revenue - cost["total"] - land
    return {"sales": sales, "priced": priced, "revenue": revenue, "costs": cost["total"], "land": round(land), "land_is_stand_in": stand_in,
            "assessed_land": assessed, "profit": round(profit), "margin_pct": round(100 * profit / revenue, 1) if revenue else None,
            "per_acre": round(profit / sum(acres.values())) if sum(acres.values()) else None}


def economy(amount, A):
    homes, flats = amount["homes"]["homes"], amount["apartments"]["homes"]
    value = homes * A["value_home"] + flats * A["value_apartment"] + amount["retail"]["sq_ft"] * A["value_retail_sqft"] + \
        amount["office"]["sq_ft"] * A["value_office_sqft"] + amount["business"]["sq_ft"] * A["value_business_sqft"]
    sales = amount["retail"]["sq_ft"] * A["retail_sales_per_sqft"]
    return {"homes": homes + flats, "residents": amount["homes"]["people"] + amount["apartments"]["people"],
            "jobs": sum(amount[u]["jobs"] for u in ("retail", "office", "business")),
            "floor_space_sq_ft": sum(amount[u]["sq_ft"] for u in ("retail", "office", "business")),
            "built_value": round(value), "property_tax_year": round(value * A["property_tax_pct"] / 100),
            "retail_sales_year": round(sales), "city_sales_tax_year": round(sales * A["sales_tax_city_pct"] / 100)}


WHO_BUYS = {
    "retail": "Shopping centre developers, who buy the land and lease to a supermarket and smaller shops; restaurant and fuel chains buy single corner pads.",
    "office": "Medical groups and hospital systems building clinics, and developers of small office buildings.",
    "apartments": "Apartment developers and home builders with a townhome or condominium line.",
    "homes": "Home builders, who buy blocks of lots once the tract map is approved.",
    "business": "Industrial and business park developers, and companies building for their own use.",
}


# What each use needs to see in a project on the city's lists before that project counts as a buyer for it.
# BUYER_KINDS: the kinds of project (the list's own "kind", lower case, start of the word) that can count at all.
BUYER_KINDS = {
    "retail": ("commercial", "mixed"), "office": ("commercial", "mixed"), "apartments": ("residential", "mixed"),
    "homes": ("residential",), "business": ("industrial", "mixed"),
}
_AMENDMENT = re.compile(r"amend|general plan", re.I)
_SPLIT = re.compile(r"parcel map|\bpm\b|lot line|\binto \d+\b.{0,30}\bparcels", re.I)
_HOTEL = re.compile(r"hotel|\binn\b|suites|motel|lodging", re.I)
_STORAGE = re.compile(r"storage|warehouse", re.I)
_SCHOOL = re.compile(r"school|child ?care|day ?care|church|worship", re.I)
_FLATS = re.compile(r"apartment|condo|multi[- ]?family|town ?homes?", re.I)
_OFFICE = re.compile(r"office|medical|clinic|dental|health", re.I)
_SHOPS = re.compile(r"retail|shop|restaurant|store\b|commercial center|market|fitness|theat|diner|coffee|drive[- ]?thru|"
                    r"fast food|car ?wash|fuel|gas station|pharmacy|bank\b", re.I)
_MAKING = re.compile(r"industrial|manufactur|business park|distribution|logistics|warehous", re.I)
_COUNT = re.compile(r"([\d,]+)\s*(?:-\s*)?(?:new\s+)?(?:res\w*\s+|single[- ]family\s+)?(?:lots?|units?|homes?)\b", re.I)


def project_uses(p):
    """The uses a project on the city's lists is evidence of a buyer for, as a set of use ids. A project counts for a
    use only when it is that kind of project (the list's kind and what its own words state) and big enough to be a
    buyer of a piece of land. An amendment to a plan or a split of land into parcels is not building anything and
    counts for nothing. A size the list does not state is not held against a project of the plain kind, but a size
    that is stated and small is."""
    kind = str(p.get("kind") or "").lower().strip()
    text = f"{p.get('title') or ''} {p.get('description') or ''}"
    stated = p.get("stated") or {}
    acres, feet = num(stated.get("acres")), num(stated.get("building_sq_ft"))
    homes = num(stated.get("homes"))
    if homes is None and (m := _COUNT.search(str(p.get("description") or ""))):
        homes = num(m.group(1).replace(",", ""))
    pure = not kind.startswith("mixed")
    if not kind or _AMENDMENT.search(text) or (feet is None and _SPLIT.search(text)):
        return set()
    unstated = pure and acres is None and feet is None      # a plain project that states no size is not held against
    uses = set()
    if kind.startswith("residential") or (kind.startswith("mixed") and (_FLATS.search(text) or homes)):
        flat = bool(_FLATS.search(text)) or bool(homes and acres and homes / acres > 9)
        if flat:
            if (homes or 0) >= 40 or (homes is None and (acres or 0) >= 2):
                uses.add("apartments")
        elif kind.startswith("residential") and ((homes or 0) >= 25 or (acres or 0) >= 5 or (homes is None and acres is None)):
            uses.add("homes")
    if kind.startswith(("commercial", "mixed")):
        offices, shops = bool(_OFFICE.search(text)), bool(_SHOPS.search(text))
        not_shops = _HOTEL.search(text) or _STORAGE.search(text) or _SCHOOL.search(text)
        if offices and ((feet or 0) >= 5000 or (unstated and feet is None)):
            uses.add("office")
        # a plain commercial project that names no other kind of building is taken as shops
        kind_of_shops = shops or (pure and not offices and not not_shops)
        if kind_of_shops and not (not_shops and not shops) and ((feet or 0) >= 2000 or (acres or 0) >= 1 or unstated):
            uses.add("retail")
    if kind.startswith("industrial") or (kind.startswith("mixed") and _MAKING.search(text)):
        if (feet or 0) >= 20000 or (acres or 0) >= 3 or unstated:
            uses.add("business")
    return uses


NO_MATCH = "No project on the city's lists near here is the right kind and size to count as a buyer for this use."


def buyers(F, acres):
    """For each use in the plan: who is already building that kind of project nearby, from the city's own lists.
    Only projects that are really that kind of project and big enough count (see project_uses); fewer, right
    buyers beat many wrong ones. A use with none says so in "note"."""
    out = []
    for use in BUILT:
        if not acres[use]:
            continue
        rows = [{k: p.get(k) for k in ("title", "builder", "status", "miles_away", "description", "number", "list", "lat", "lon")}
                for p in F["projects"] if use in project_uses(p)]
        rows.sort(key=lambda r: (not r["builder"], r["miles_away"]))
        named = []
        for r in rows:
            if r["builder"] and r["builder"] not in named:
                named.append(r["builder"])
        out.append({"use": use, "who": WHO_BUYS[use], "named": named[:8], "projects": rows[:8],
                    "note": None if rows else (NO_MATCH if F["projects"] else None)})
    return out


def market(F):
    near = [p for p in F["projects"] if p["miles_away"] <= 2.0]
    count = lambda *kinds: [p for p in near if str(p.get("kind") or "").lower().startswith(kinds)]  # noqa: E731
    homes = sum((p.get("stated") or {}).get("homes") or 0 for p in count("residential"))
    feet = sum((p.get("stated") or {}).get("building_sq_ft") or 0 for p in count("commercial", "industrial", "mixed"))
    return {"people": [F["people"][m] for m in sorted(F["people"])] if F["people"] else None,
            "pipeline": {"within_miles": 2.0, "projects": len(near), "housing_projects": len(count("residential")),
                         "homes_stated": round(homes), "commercial_projects": len(count("commercial", "mixed")),
                         "industrial_projects": len(count("industrial")), "building_sq_ft_stated": round(feet)},
            "lists_updated": F["projects_updated"], "schools": F["schools"][:4]}


# ---------------------------------------------------------------- the whole plan

def advise(F, parts, mode, suggested):
    """The few things to say before anything else, in plain words."""
    out = []
    if F["outline_acres"] and F["acres"] != F["recorded_acres"]:
        out.append(f"The city's record gives this parcel {counted(F['recorded_acres'], 'acre')}, but its outline on the map measures about "
                   f"{counted(F['outline_acres'], 'acre')}. They cannot both be right, so this plan uses the {counted(F['outline_acres'], 'acre')} the outline shows. "
                   "Check the size with the county assessor before relying on either.")
    kind, zone = F["zoning_kind"], F["zoning"] or "none listed"
    if kind in ("open-space", "public"):
        what = "open space" if kind == "open-space" else "public facilities such as schools and utilities"
        if mode == "zoning":
            out.append(f"This land is zoned {zone}, which is for {what}. Under today's zoning there is nothing to build and sell here. "
                       "Choose Best use to see what the location could support if the city agreed to change the zoning; for this kind of land that is rare.")
        else:
            out.append(f"This land is zoned {zone}, which is for {what}. Everything below would need the city to change that, which is rare for this kind of land. Treat it as a long shot.")
    plan_name = (parts.get("general_plan") or {}).get("specific_plan") or ""
    if kind == "specific-plan":
        out.append(("This land is inside the " + plan_name + " specific plan" if plan_name else "This land is inside a specific plan")
                   + ": a plan the city has already approved that sets what goes where. Read that plan first. The mix below is what the location supports, not what that plan says.")
    if kind == "other":
        out.append("No zoning is listed for this parcel in the city's records, so nothing below is checked against zoning. Ask the city what applies.")
    if mode == "best" and kind not in ("open-space", "public", "other"):
        need = [u["label"].lower() for u in USES if u["id"] in BUILT and suggested[u["id"]] and F["fit"][u["id"]] == "change"]
        if need:
            out.append("Best use ignores today's zoning. In this mix, " + ", ".join(need) + " would need a zoning change through the city, with public hearings."
                       + (" That is read from the city's own table of allowed uses." if F.get("rules") else ""))
    permit = [u["label"].lower() for u in USES if u["id"] in BUILT and suggested[u["id"]] and F["fit"][u["id"]] == "permit"]
    if permit and kind not in ("open-space", "public", "other"):
        out.append("In this mix, " + ", ".join(permit) + (" is" if len(permit) == 1 else " are") + " allowed by today's zoning only with a "
                   "conditional use permit: an application to the city, a public hearing, and conditions the city sets.")
    if not F.get("rules") and kind != "other":
        out.append("The city's table of allowed uses is not read for this city, so “what the zone is for” comes from the kind "
                   "of zone alone. Check each use against the city's own code before relying on it.")
    if "very high" in F["fire"].lower() or "high" in F["fire"].lower():
        out.append(f"The parcel is in a state fire hazard zone ({F['fire']}). Expect fire-safe building rules, wider clearings and a second way out to be asked for.")
    if not F["frontage"] and F["acres"] and any(suggested[u] for u in BUILT):
        near = F["streets"][0] if F["streets"] else None
        out.append("No street on the city's planned street network touches this parcel" + (f" (the nearest is {near['name']}, about {say(near['feet'])} ft away)" if near else "")
                   + ". How people get in and out is the first thing to settle.")
    if F["missing"]:
        out.append("Some records did not answer just now, so the rules that need them were skipped: " + ", ".join(F["missing"]) + ".")
    return out


def clean_settings(settings):
    """Only what the page is allowed to set, with sane limits."""
    s = settings if isinstance(settings, dict) else {}
    out = {"mode": "best" if s.get("mode") == "best" else "zoning", "acres": None, "assumptions": {}, "extra_costs": [],
           "land_cost": None}
    if isinstance(s.get("acres"), dict):
        acres = {u: num(s["acres"].get(u)) for u in USE_IDS}
        if any(v is not None for v in acres.values()):
            out["acres"] = {u: max(0.0, v or 0.0) for u, v in acres.items()}
    if isinstance(s.get("assumptions"), dict):
        for key, value in s["assumptions"].items():
            v = num(value)
            if key in ASSUMPTIONS and v is not None and 0 <= v <= 1e10:
                out["assumptions"][key] = v
    if isinstance(s.get("extra_costs"), list):
        for x in s["extra_costs"][:60]:
            if isinstance(x, dict) and num(x.get("amount")) is not None:
                out["extra_costs"].append({"name": str(x.get("name") or "Other cost")[:80], "amount": num(x["amount"])})
    land = num(s.get("land_cost"))
    if land is not None and 0 <= land <= 1e11:
        out["land_cost"] = land
    return out


def fit_words(F, use, fit):
    """The short words beside a use: the table's own answer when the city's table is held, else the family's."""
    if F.get("rules"):
        return (F["rules"]["uses"].get(use) or {}).get("words") or FIT_WORDS[fit]
    return FIT_WORDS[fit]


def fit_read(F, use):
    """What the city's table says about one use, for the page: the rows it was read from and close relatives."""
    if not F.get("rules"):
        return None
    read = F["rules"]["uses"].get(use) or {}
    return {k: read.get(k) for k in ("status", "words", "permit", "zone", "table", "read_from", "related", "requirements",
                                     "why", "by_zone") if read.get(k)}


def zoning_rules(F):
    """Where "allowed" comes from on this plan: the city's recorded table (with its source and the day it was read),
    or only the kind of zone."""
    rules = F.get("rules")
    if not rules:
        return {"basis": "family", "says": "The city's table of allowed uses is not read for this city. “What the zone is for” "
                                           "comes from the kind of zone alone; it is not the city's list of permitted uses."}
    return {"basis": "table", "source": rules.get("source"), "says": rules.get("says") or "",
            "zones": [{k: p.get(k) for k in ("zone", "kind", "table", "section", "url", "read_on", "says", "plan", "same_as") if p.get(k)}
                      for p in rules.get("parts") or []]}


def make_plan(parcel, parts, settings=None, kind_of=lambda code: "other"):
    """The whole Plan page for one parcel. `parts` holds whichever site facts the app has (missing ones are named
    in the answer and the rules that need them are skipped)."""
    settings = clean_settings(settings)
    F, frame, outline = gather(parcel, parts, kind_of)
    figures = starting_figures(F)
    for key, value in settings["assumptions"].items():
        if abs(value - figures[key]["start"]) > 1e-9:
            figures[key].update(value=value, kind="yours", basis="Your own figure. The starting figure was " + f"{figures[key]['start']:,.10g}.")
    A = {k: v["value"] for k, v in figures.items()}
    scores = score_uses(F, count_zoning=settings["mode"] != "best")
    suggested, notes, dropped = suggest(F, scores, A, settings["mode"])
    advice = advise(F, parts, settings["mode"], suggested)
    suggested = settle(suggested, F["acres"])
    acres, edited = suggested, False
    if settings["acres"]:
        mine = settings["acres"]
        total = sum(mine.values())
        if total > 0:
            scale = F["acres"] / total
            acres = settle({u: mine[u] * scale for u in USE_IDS}, F["acres"])
            edited = acres != suggested
    amount = amounts(acres, A)
    drawing = draw(F, frame, outline, acres)
    moving = traffic(F, frame, outline, drawing, amount, A)
    cost = costs(F, drawing, acres, moving, A, settings["extra_costs"], F["acres"])
    if drawing:
        drawing.pop("cut_ends", None)
    uses = []
    for u in USES:
        s = scores.get(u["id"])
        uses.append({**u, "acres": acres[u["id"]], "suggested_acres": suggested[u["id"]],
                     "share_pct": round(100 * acres[u["id"]] / F["acres"], 1) if F["acres"] else 0.0,
                     "score": s["score"] if s else None, "fit": s["fit"] if s else "fits",
                     "fit_words": fit_words(F, u["id"], s["fit"]) if s else "Part of any project",
                     "fit_read": fit_read(F, u["id"]),
                     "reasons": s["reasons"] if s else [], **{k: v for k, v in amount[u["id"]].items() if k != "acres"}})
    return {
        "acres": F["acres"], "mode": settings["mode"], "edited": edited, "uses": uses, "notes": notes, "advice": advice,
        "nothing_to_build": not any(suggested[u] for u in BUILT),
        "left_out": [{"use": u, "label": next(x["label"] for x in USES if x["id"] == u), "score": scores[u]["score"],
                      "fit": scores[u]["fit"], "fit_words": fit_words(F, u, scores[u]["fit"])} for u in dropped],
        "zoning_rules": zoning_rules(F),
        "recorded_acres": F["recorded_acres"], "outline_acres": F["outline_acres"],
        "facts": {"zoning": F["zoning"], "zoning_name": F["zoning_name"], "zoning_kind": F["zoning_kind"], "frontage": _plain(F["frontage"]),
                  "corner": _plain(F["corner"]), "streets": [_plain(s) for s in F["streets"][:8]], "highway": F["highway"],
                  "around": F["around"], "ground": F["ground"], "missing": F["missing"],
                  "smallest_lot": {"acres": F["lot_rule"]["acres"], "zones": [{"code": c, "acres": a} for c, a in F["lot_rule"]["zones"]],
                                   "unread": F["lot_rule"]["unread"]} if F["lot_rule"] else None},
        "street_lines": F["street_lines"], "drawing": drawing, "traffic": moving, "costs": cost,
        "money": money(parcel, acres, amount, cost, A, settings["land_cost"]), "economy": economy(amount, A),
        "buyers": buyers(F, acres), "market": market(F), "figures": list(figures.values()),
        "settings": settings,
    }


def headline(plan):
    """The few numbers of a plan that fit in one row of a comparison."""
    uses = [{"id": u["id"], "label": u["label"], "short": u["short"], "colour": u["colour"], "acres": u["acres"],
             "share_pct": u["share_pct"], "fit": u["fit"]} for u in plan["uses"] if u["acres"]]
    built = [u for u in uses if u["id"] != "park"]
    return {"mode": plan["mode"], "edited": plan["edited"], "nothing_to_build": plan["nothing_to_build"], "uses": uses,
            "largest_use": max(built, key=lambda u: u["acres"])["label"] if built else None,
            "needs_zoning_change": [u["label"] for u in built if u["fit"] == "change"],
            "needs_permit": [u["label"] for u in built if u["fit"] == "permit"],
            "homes": plan["economy"]["homes"], "floor_space_sq_ft": plan["economy"]["floor_space_sq_ft"],
            "jobs": plan["economy"]["jobs"], "residents": plan["economy"]["residents"],
            "trips_per_day": plan["traffic"]["per_day"], "signals_to_study": plan["traffic"]["signals_to_study"],
            "revenue": plan["money"]["revenue"], "costs": plan["money"]["costs"], "land": plan["money"]["land"],
            "land_is_stand_in": plan["money"]["land_is_stand_in"], "profit": plan["money"]["profit"],
            "profit_per_acre": plan["money"]["per_acre"], "margin_pct": plan["money"]["margin_pct"],
            "advice": plan["advice"]}


def _plain(street):
    return {k: v for k, v in street.items() if k not in ("at", "toward", "reach")} if street else None
