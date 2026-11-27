"""Capital target solver, retained-land value over time, paced land releases and the reconciliation helper."""
from .finance_common import DISCLAIMER, cap_int, as_dict, as_list, div, frac, num, pct4, public, rnd, usd
from .finance_land import gross_to_net_waterfall

STRATEGIES = ("max_cash", "balanced", "max_retention")
STRATEGY_TEXT = {
    "max_cash": "Max cash: sells the parcels that raise the most cash per acre first, ignoring strategic scores, so the fewest acres are sold.",
    "balanced": "Balanced: ranks parcels by a blend of cash per acre and low strategic score, then sells down the list.",
    "max_retention": "Max strategic retention: sells the lowest strategic scores first and never sells a critical or must-keep parcel.",
}
DEFAULT_TX_PCT = 3.5 + 0.75 + 0.11


# ---------------------------------------------------------------- capital target solver

def _prepare(parcels, rates, default_score, critical_threshold):
    rows, skipped = [], []
    for p in as_list(parcels):
        p = as_dict(p)
        net = num(p.get("net_proceeds_usd"))
        basis = "given net proceeds"
        if net is None and num(p.get("gross_price_usd")) is not None:
            w = gross_to_net_waterfall(p["gross_price_usd"], p.get("net_ac"), p.get("seller_note_usd") or 0.0, p.get("debt_release_usd") or 0.0,
                                       rates["brokerage_pct"], rates["closing_cost_pct"], rates["transfer_tax_pct"], rates["recording_fee_usd"],
                                       p.get("stub_per_net_ac_usd") or 0.0, p.get("infrastructure_stubs"))
            net, basis = w["net_cash_proceeds_usd"], "price less the gross-to-net waterfall"
        if net is None or net <= 0:
            skipped.append({"id": p.get("id"), "why": "No positive net proceeds (give net_proceeds_usd or gross_price_usd)."})
            continue
        score = num(p.get("strategic_score"))
        ac = num(p.get("net_ac"))
        rows.append({"id": p.get("id"), "name": p.get("name"), "net_proceeds_usd": net, "net_ac": ac, "price_usd": num(p.get("gross_price_usd"), net),
                     "strategic_score": score if score is not None else default_score, "score_was_given": score is not None,
                     "close_month": num(p.get("close_month"), 0.0), "must_keep": bool(p.get("must_keep")),
                     "do_not_sell_until_month": num(p.get("do_not_sell_until_month")), "basis": basis,
                     "critical": bool(p.get("must_keep") or p.get("critical") or (score is not None and score >= critical_threshold)),
                     "cash_per_ac": net / ac if ac and ac > 0 else net})
    return rows, skipped


def _keys(strategy, rows, cash_weight):
    top = max([r["cash_per_ac"] for r in rows] + [1.0])
    if strategy == "max_cash":
        return {r["id"]: (-r["cash_per_ac"], r["strategic_score"]) for r in rows}
    if strategy == "balanced":
        w = min(1.0, max(0.0, cash_weight))
        return {r["id"]: (-(w * r["cash_per_ac"] / top + (1.0 - w) * (1.0 - r["strategic_score"] / 100.0)), r["strategic_score"]) for r in rows}
    return {r["id"]: (r["strategic_score"], -r["cash_per_ac"]) for r in rows}


def _closed_by(picks, month):
    return sum(p["net_proceeds_usd"] for p in picks if p["close_month"] <= month)


def _requirements(targets, cumulative):
    reqs, running = [], 0.0
    for t in sorted((as_dict(t) for t in as_list(targets)), key=lambda t: num(t.get("month"), 0.0)):
        amt = num(t.get("amount_usd"))
        if amt is None:
            continue
        running = amt if cumulative else running + amt
        reqs.append({"month": num(t.get("month"), 0.0), "label": t.get("label"), "target_usd": amt, "cumulative_target_usd": running})
    return reqs


def _solve_one(strategy, rows, reqs, cash_weight):
    pool = [r for r in rows if not r["must_keep"] and (strategy != "max_retention" or not r["critical"])]
    keys = _keys(strategy, pool, cash_weight)
    order = sorted(pool, key=lambda r: keys[r["id"]])
    picks = []
    for rq in reqs:
        for r in order:
            if _closed_by(picks, rq["month"]) >= rq["cumulative_target_usd"]:
                break
            if r not in picks and r["close_month"] <= rq["month"]:
                picks.append(r)
    for r in sorted(list(picks), key=lambda x: keys[x["id"]], reverse=True):          # drop any pick that is not needed
        rest = [p for p in picks if p is not r]
        if all(_closed_by(rest, rq["month"]) >= rq["cumulative_target_usd"] - 1e-9 for rq in reqs):
            picks = rest
    return picks, order


def _period_rows(picks, reqs):
    out, prev = [], 0.0
    for rq in reqs:
        closed = _closed_by(picks, rq["month"])
        gap = rq["cumulative_target_usd"] - closed
        out.append({"month": rq["month"], "label": rq["label"], "target_usd": usd(rq["target_usd"]),
                    "cumulative_target_usd": usd(rq["cumulative_target_usd"]), "closed_in_period_usd": usd(closed - prev),
                    "cumulative_closed_usd": usd(closed), "shortfall_usd": usd(max(0.0, gap)), "surplus_usd": usd(max(0.0, -gap)), "met": gap <= 1e-9})
        prev = closed
    return out


@public
def solve_capital_targets(parcels, targets, strategies=STRATEGIES, targets_are_cumulative=True, brokerage_pct=3.5, closing_cost_pct=0.75,
                          transfer_tax_pct=0.11, recording_fee_usd=0.0, default_strategic_score=50.0, critical_threshold=75.0,
                          balanced_cash_weight=0.5):
    """Chooses which parcels to sell to reach cash targets, under three strategies.

    Inputs: parcels [{id, name, net_ac, net_proceeds_usd OR gross_price_usd (run through the gross-to-net waterfall with the rates below,
    plus the parcel's own stub_per_net_ac_usd, seller_note_usd, debt_release_usd), strategic_score 0-100, close_month (earliest month the
    cash arrives, default 0), must_keep (never sold), critical (treated as a critical asset), do_not_sell_until_month}];
    targets [{month, amount_usd, label}] (cumulative by that month, unless targets_are_cumulative is False, then each amount is added to the
    one before: "$22M by month 18, +$20M by month 36"); strategies (a subset of max_cash, balanced, max_retention);
    default_strategic_score (for a parcel with no score), critical_threshold (a score at or above this marks a critical asset),
    balanced_cash_weight (0-1, the weight of cash per acre in the balanced ranking).
    Output per strategy: picks, proceeds_by_period (target, closed, shortfall, surplus, met), total net proceeds and acres sold, shortfall
    or surplus at the last target, land retained (acres, parcels, value at price, acre-weighted strategic score), critical asset conflicts.
    It is a greedy ranking with a pruning step, not a proof of the global optimum; the ranking rule of each strategy is stated."""
    rates = {"brokerage_pct": num(brokerage_pct, 3.5), "closing_cost_pct": num(closing_cost_pct, 0.75),
             "transfer_tax_pct": num(transfer_tax_pct, 0.11), "recording_fee_usd": num(recording_fee_usd, 0.0)}
    crit = num(critical_threshold, 75.0)
    rows, skipped = _prepare(parcels, rates, num(default_strategic_score, 50.0), crit)
    reqs = _requirements(targets, bool(targets_are_cumulative))
    result = {}
    names = [s for s in as_list(strategies) if s in STRATEGIES] or list(STRATEGIES)
    for strategy in names:
        picks, order = _solve_one(strategy, rows, reqs, num(balanced_cash_weight, 0.5))
        periods = _period_rows(picks, reqs)
        sold_ids = {p["id"] for p in picks}
        kept = [r for r in rows if r["id"] not in sold_ids]
        kept_ac = sum(r["net_ac"] or 0.0 for r in kept)
        weighted = sum((r["net_ac"] or 0.0) * r["strategic_score"] for r in kept)
        conflicts = []
        for p in picks:
            if p["critical"]:
                conflicts.append({"parcel_id": p["id"], "kind": "critical_asset_sold", "strategic_score": p["strategic_score"],
                                  "why": "This plan sells a parcel marked critical (strategic score "
                                         f"{p['strategic_score']:g}, threshold {crit:g}, or flagged)."})
            if p["do_not_sell_until_month"] is not None and p["close_month"] < p["do_not_sell_until_month"]:
                conflicts.append({"parcel_id": p["id"], "kind": "sold_inside_hold_period", "strategic_score": p["strategic_score"],
                                  "why": f"Closes in month {p['close_month']:g}, before the do-not-sell date (month {p['do_not_sell_until_month']:g})."})
        last = periods[-1] if periods else None
        need = []
        if strategy == "max_retention" and last and not last["met"]:
            gap = last["shortfall_usd"]
            for r in sorted([r for r in rows if r["critical"] and not r["must_keep"] and r["id"] not in sold_ids], key=lambda r: r["strategic_score"]):
                if gap <= 0:
                    break
                need.append(r["id"])
                gap -= r["net_proceeds_usd"]
        result[strategy] = {
            "strategy": strategy, "rule": STRATEGY_TEXT[strategy],
            "picks": [{"id": p["id"], "name": p["name"], "net_proceeds_usd": usd(p["net_proceeds_usd"]), "net_ac": p["net_ac"],
                       "strategic_score": p["strategic_score"], "close_month": p["close_month"], "critical": p["critical"]} for p in picks],
            "proceeds_by_period": periods, "all_targets_met": bool(periods) and all(p["met"] for p in periods),
            "total_net_proceeds_usd": usd(sum(p["net_proceeds_usd"] for p in picks)), "acres_sold": rnd(sum(p["net_ac"] or 0.0 for p in picks), 4),
            "shortfall_usd": last["shortfall_usd"] if last else None, "surplus_usd": last["surplus_usd"] if last else None,
            "retained": {"acres": rnd(kept_ac, 4), "parcel_ids": [r["id"] for r in kept], "value_at_price_usd": usd(sum(r["price_usd"] for r in kept)),
                         "average_strategic_score": rnd(div(weighted, kept_ac), 2)},
            "critical_asset_conflicts": conflicts, "critical_parcels_that_would_close_the_gap": need,
            "why": None if reqs else "No usable targets were given."}
    return {"strategies": result, "targets": [{"month": r["month"], "label": r["label"], "target_usd": usd(r["target_usd"]),
                                               "cumulative_target_usd": usd(r["cumulative_target_usd"])} for r in reqs],
            "parcels_not_used": skipped, "net_proceeds_available_usd": usd(sum(r["net_proceeds_usd"] for r in rows)),
            "assumptions": {"rates": rates, "default_strategic_score": num(default_strategic_score), "critical_threshold": crit,
                            "targets_are_cumulative": bool(targets_are_cumulative), "balanced_cash_weight": num(balanced_cash_weight)},
            "formula": ["Net proceeds of a parcel = its price less the itemised waterfall (or the net figure given).",
                        "Rank the parcels by the strategy's rule; for each target month, in order, sell down the ranking until the cash "
                        "closed by that month reaches the cumulative target; then drop any sale that is not needed.",
                        "Shortfall = cumulative target - cash closed by the month (never below zero); surplus is the reverse."],
            "disclaimer": DISCLAIMER}


# ---------------------------------------------------------------- retained land over time

def _grow(base, years, a, lift, lift_year):
    try:
        f = (1.0 + a) ** years
        if lift_year is not None and years >= lift_year:
            f *= 1.0 + lift
        return base * f
    except OverflowError:
        return float("inf")             # shown as None by the output rounding


@public
def retained_land_value(base_value_usd, appreciation_pct, placemaking_lift_pct=0.0, lift_year=1, years=15, milestones=(5, 10, 15), acres=None):
    """Value of retained land over time: today's value grown by an annual appreciation rate, plus a one-time placemaking lift.

    Inputs: base_value_usd (today's entitled value of the retained land); appreciation_pct (per year, compounded); placemaking_lift_pct
    (a one-time step up, e.g. 20); lift_year (the year the step up lands, default 1); years (length of the table, default 15);
    milestones (years to call out, default 5, 10 and 15); acres (optional, gives value per acre).
    Output: yearly rows {year, value_usd, gain_vs_today_usd, per_ac_usd}, milestones {year: value, gain, implied annual growth %},
    value at the end. Value in year t = base x (1 + appreciation)^t x (1 + lift if t >= lift_year). Land value only; no rent or NOI."""
    base, a = num(base_value_usd), frac(appreciation_pct)
    lift, ly = frac(placemaking_lift_pct) or 0.0, num(lift_year)
    out = {"yearly": [], "milestones": {}, "value_at_end_usd": None, "why": None,
           "assumptions": {"base_value_usd": base, "appreciation_pct": num(appreciation_pct), "placemaking_lift_pct": num(placemaking_lift_pct),
                           "lift_year": ly, "years": years, "acres": num(acres)},
           "formula": "value(t) = base x (1 + appreciation)^t, times (1 + lift) from the lift year on. Land only, before any rent."}
    if base is None or a is None or a <= -1:
        out["why"] = "Give today's value and a yearly appreciation rate."
        return out
    n = cap_int(years, 15, 0, 200)
    ac = num(acres)
    for t in range(0, n + 1):
        v = _grow(base, t, a, lift, ly)
        out["yearly"].append({"year": t, "value_usd": usd(v), "gain_vs_today_usd": usd(v - base), "per_ac_usd": usd(div(v, ac))})
    for m in as_list(milestones):
        m = cap_int(m, 0, 0, 200)
        if m > 0:
            v = _grow(base, m, a, lift, ly)
            cagr = ((v / base) ** (1.0 / m) - 1.0) * 100.0 if base > 0 and v > 0 else None
            out["milestones"][str(m)] = {"year": m, "value_usd": usd(v), "gain_vs_today_usd": usd(v - base), "implied_growth_pct_per_year": pct4(cagr)}
    out["value_at_end_usd"] = out["yearly"][-1]["value_usd"] if out["yearly"] else None
    return out


@public
def retained_land_value_scenarios(scenarios, milestones=(5, 10, 15)):
    """retained_land_value for several named scenarios side by side.

    Inputs: scenarios {name: {base_value_usd, appreciation_pct, placemaking_lift_pct, lift_year, acres}}; milestones.
    Output: rows [{name, acres, milestones {year: value}}] and a table {year: {name: value}}."""
    rows, table = [], {}
    for name, sc in as_dict(scenarios).items():
        sc = as_dict(sc)
        r = retained_land_value(sc.get("base_value_usd"), sc.get("appreciation_pct"), sc.get("placemaking_lift_pct", 0.0), sc.get("lift_year", 1),
                                max([cap_int(m, 0, 0, 200) for m in as_list(milestones)] + [0]), milestones, sc.get("acres"))
        rows.append({"name": name, "acres": num(sc.get("acres")), "milestones": r["milestones"], "why": r["why"]})
        for k, v in r["milestones"].items():
            table.setdefault(k, {})[name] = v["value_usd"]
    return {"scenarios": rows, "table": table, "formula": "Each scenario: retained_land_value(base, appreciation, lift) at each milestone year."}


@public
def paced_land_releases(retained_acres, value_per_ac_today_usd, release_acres, every_years, years=15, appreciation_pct=0.0,
                        placemaking_lift_pct=0.0, lift_year=1, first_release_year=1, min_core_acres=0.0, sale_cost_pct=DEFAULT_TX_PCT):
    """Sells retained land in tranches (for example 5 acres every 2 years) and shows proceeds, what is left and when the core floor binds.

    Inputs: retained_acres; value_per_ac_today_usd; release_acres (per release) and every_years; years (default 15); appreciation_pct and
    placemaking_lift_pct as in retained_land_value; first_release_year (default 1); min_core_acres (never sell below this; default 0);
    sale_cost_pct (default 4.36, the brokerage, closing and transfer rates of the waterfall).
    Output: events [{year, acres_sold, price_per_ac_usd, gross_usd, net_usd, acres_left}], total_net_proceeds_usd, acres_left,
    value_left_usd (at the end year), total_wealth_usd (net proceeds + value left, undiscounted), floor_reached_year (the year a release
    was cut short or skipped by min_core_acres), sold_out_year."""
    ac, v0 = num(retained_acres), num(value_per_ac_today_usd)
    rel, ev = num(release_acres), num(every_years)
    out = {"events": [], "total_net_proceeds_usd": None, "acres_left": None, "value_left_usd": None, "total_wealth_usd": None,
           "floor_reached_year": None, "sold_out_year": None, "why": None,
           "assumptions": {"retained_acres": ac, "value_per_ac_today_usd": v0, "release_acres": rel, "every_years": ev, "years": years,
                           "appreciation_pct": num(appreciation_pct), "placemaking_lift_pct": num(placemaking_lift_pct),
                           "min_core_acres": num(min_core_acres, 0.0), "sale_cost_pct": num(sale_cost_pct)},
           "formula": ["Release years = first release year, then every N years up to the end year.",
                       "Price per acre in year t = today's value per acre x (1 + appreciation)^t (x (1 + lift) from the lift year).",
                       "Acres sold = min(release acres, acres left - core floor); net = gross x (1 - sale cost %)."]}
    a = frac(appreciation_pct)
    if None in (ac, v0, rel, ev, a) or ac < 0 or rel <= 0 or ev <= 0:
        out["why"] = "Give acres, a value per acre, a release size above zero and a release interval above zero."
        return out
    lift, ly = frac(placemaking_lift_pct) or 0.0, num(lift_year)
    floor = num(min_core_acres, 0.0)
    cost = frac(sale_cost_pct) or 0.0
    n = cap_int(years, 15, 0, 200)
    left, net_total, year = ac, 0.0, cap_int(first_release_year, 1, 0, 200)
    while year <= n:
        room = left - floor
        sell = min(rel, room)
        if sell <= 1e-9:
            out["floor_reached_year"] = out["floor_reached_year"] or year
            break
        if sell < rel - 1e-9:
            out["floor_reached_year"] = out["floor_reached_year"] or year
        price = _grow(v0, year, a, lift, ly)
        gross = price * sell
        left -= sell
        net_total += gross * (1.0 - cost)
        out["events"].append({"year": year, "acres_sold": rnd(sell, 4), "price_per_ac_usd": usd(price), "gross_usd": usd(gross),
                              "net_usd": usd(gross * (1.0 - cost)), "acres_left": rnd(left, 4)})
        if left <= 1e-9:
            out["sold_out_year"] = year
            break
        year += cap_int(ev, 1, 1, 200)
    left_value = left * _grow(v0, n, a, lift, ly)
    out.update({"total_net_proceeds_usd": usd(net_total), "acres_left": rnd(left, 4), "value_left_usd": usd(left_value),
                "total_wealth_usd": usd(net_total + left_value)})
    return out


@public
def compare_release_cadences(cadences, retained_acres, value_per_ac_today_usd, **kwargs):
    """paced_land_releases for several cadences side by side, e.g. [{name: '5 acres every 2 years', release_acres: 5, every_years: 2},
    {name: '10 acres every 3 years', release_acres: 10, every_years: 3}]. kwargs are the other inputs of paced_land_releases
    (years, appreciation_pct, min_core_acres, ...). Output: rows with the totals of each, and the cadence with the most total wealth."""
    rows = []
    for c in as_list(cadences):
        c = as_dict(c)
        r = paced_land_releases(retained_acres, value_per_ac_today_usd, c.get("release_acres"), c.get("every_years"), **kwargs)
        rows.append({"name": c.get("name"), "release_acres": num(c.get("release_acres")), "every_years": num(c.get("every_years")),
                     "acres_per_year": rnd(div(c.get("release_acres"), c.get("every_years")), 4), "releases": len(r["events"]),
                     "total_net_proceeds_usd": r["total_net_proceeds_usd"], "acres_left": r["acres_left"], "value_left_usd": r["value_left_usd"],
                     "total_wealth_usd": r["total_wealth_usd"], "floor_reached_year": r["floor_reached_year"], "sold_out_year": r["sold_out_year"],
                     "why": r["why"]})
    ok = [r for r in rows if r["total_wealth_usd"] is not None]
    best = max(ok, key=lambda r: r["total_wealth_usd"])["name"] if ok else None
    return {"cadences": rows, "most_total_wealth": best,
            "formula": "Each cadence is run through paced_land_releases; total wealth = net proceeds + value of the land left (undiscounted)."}


# ---------------------------------------------------------------- reconciliation

@public
def reconcile_program(headline, components, tolerance_abs=None, tolerance_pct=None, label="total"):
    """Checks a headline total against the lines that should add up to it.

    Inputs: headline (the stated total); components [numbers or {label, value}] (a missing value is counted, not treated as zero);
    tolerance_abs (units; default 0) and/or tolerance_pct (% of the headline; default 0): the difference is within tolerance if it is
    inside either one; label (what is being reconciled, for the sentence).
    Output: headline, components_sum, difference (headline - sum), difference_pct, within_tolerance (True, False, or None when a
    component is not known so it cannot be confirmed), missing_components, explanation sentence."""
    head = num(headline)
    vals, missing, rows = [], 0, []
    for c in as_list(components):
        v = num(as_dict(c).get("value") if isinstance(c, dict) else c)
        name = as_dict(c).get("label") if isinstance(c, dict) else None
        rows.append({"label": name, "value": v})
        if v is None:
            missing += 1
        else:
            vals.append(v)
    total = sum(vals)
    diff = None if head is None else head - total
    diff_pct = None if diff is None else div(diff, head)
    ta, tp = num(tolerance_abs, 0.0), num(tolerance_pct, 0.0)
    within = None
    if diff is not None and not missing:
        within = bool(abs(diff) <= ta + 1e-9 or (diff_pct is not None and abs(diff_pct) * 100.0 <= tp + 1e-9) or (head == 0 and diff == 0))
    if head is None:
        text = f"The {label} headline is missing."
    elif missing:
        text = f"{missing} component{'s are' if missing != 1 else ' is'} not known: the lines add to at least {total:,.2f} against a {label} of {head:,.2f}."
    elif within:
        text = f"The lines add to {total:,.2f}; the {label} is {head:,.2f}: the difference of {diff:,.2f} is within tolerance."
    else:
        text = f"The lines add to {total:,.2f} but the {label} is {head:,.2f}: they differ by {diff:,.2f}."
    return {"headline": head, "components": rows, "components_sum": rnd(total, 4), "difference": rnd(diff, 4),
            "difference_pct": rnd(None if diff_pct is None else diff_pct * 100.0, 4), "within_tolerance": within, "missing_components": missing,
            "explanation": text, "assumptions": {"tolerance_abs": ta, "tolerance_pct": tp},
            "formula": "difference = headline - sum of the components; within tolerance if |difference| <= tolerance_abs or |difference| / headline <= tolerance_pct."}
