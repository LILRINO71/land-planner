"""Hold vs sell vs joint venture vs ground lease: strategic scores, weighted economic criteria, 10- and 15-year NPV, and the
critical-strategic-asset conflict flags.

Every number in the strategy profiles and the default weights below is a starting assumption the caller can replace; none is
a market fact. NPVs are before tax and unlevered, and sale proceeds are not reinvested (the comparison is cash against cash
at the stated discount rate).
"""
from .finance_common import DISCLAIMER, cap_int, as_dict, as_list, div, frac, npv, num, public, rnd, usd
from .finance_proforma import absorption_schedule

STRATEGIES = ("fee_simple_sale", "hold_develop", "joint_venture", "ground_lease")
STRATEGY_LABELS = {"fee_simple_sale": "Fee-simple sale", "hold_develop": "Hold and develop", "joint_venture": "Joint venture (land as equity)",
                   "ground_lease": "NNN ground lease"}

DEFAULT_STRATEGIC_DIMENSIONS = (
    ("placemaking_gravity", "Placemaking gravity (does it anchor the district's identity?)"),
    ("frontage_visibility", "Frontage and visibility"),
    ("cotenancy_catalyst", "Co-tenancy and anchor catalyst effect"),
    ("design_and_brand_control", "Design, brand and CC&R control"),
    ("long_term_appreciation", "Long-term appreciation potential"),
    ("scarcity", "Scarcity (hard to replace)"),
    ("access_and_traffic", "Access and traffic"),
    ("entitlement_certainty", "Entitlement certainty"),
    ("infrastructure_readiness", "Infrastructure readiness"),
    ("buyer_liquidity", "Depth of buyers (liquidity)"),
    ("community_benefit", "Public benefit and civic value"),
    ("recurring_income_potential", "Recurring income potential"),
)
DEFAULT_ECONOMIC_CRITERIA = (
    ("npv_10_year", "NPV over the first horizon (10 years)", 12.0),
    ("npv_15_year", "NPV over the last horizon (15 years)", 18.0),
    ("upfront_cash", "Cash in the first 12 months", 12.0),
    ("capital_required", "Own capital the owner must put in (lower is better)", 10.0),
    ("recurring_income", "Recurring income per year", 10.0),
    ("time_to_first_cash", "Months to first cash (lower is better)", 8.0),
    ("execution_risk", "Execution risk (higher score = lower risk)", 14.0),
    ("control_retained", "Control of the land retained", 8.0),
    ("upside_retained", "Share of future land upside kept", 8.0),
)
LOWER_IS_BETTER = ("capital_required", "time_to_first_cash")
DEFAULT_PROFILES = {   # starting assumptions, 0-100 / percent; replace per project
    "fee_simple_sale": {"execution_risk_score": 90.0, "control_retained_pct": 0.0, "upside_retained_pct": 0.0},
    "hold_develop": {"execution_risk_score": 30.0, "control_retained_pct": 100.0, "upside_retained_pct": 100.0},
    "joint_venture": {"execution_risk_score": 60.0, "control_retained_pct": 60.0, "upside_retained_pct": 65.0},
    "ground_lease": {"execution_risk_score": 85.0, "control_retained_pct": 90.0, "upside_retained_pct": 100.0},
}
DEFAULT_DECISION = {"discount_rate_pct": 8.0, "horizons_years": (10, 15), "appreciation_pct": 3.0, "sale_cost_pct": 4.36,
                    "critical_threshold": 75.0, "strategic_influence": 0.3}


@public
def default_strategic_dimensions():
    """The 12 default strategic dimensions [{id, label, weight}] (equal weights). Replace or re-weight them per project."""
    return [{"id": i, "label": label, "weight": 1.0} for i, label in DEFAULT_STRATEGIC_DIMENSIONS]


@public
def default_economic_criteria():
    """The 9 default weighted economic criteria [{id, label, weight}]."""
    return [{"id": i, "label": label, "weight": w} for i, label, w in DEFAULT_ECONOMIC_CRITERIA]


@public
def score_strategic_dimensions(scores, weights=None, dimensions=None):
    """A parcel's strategic score: the weighted average of its 0-100 dimension scores.

    Inputs: scores {dimension id: 0-100}; weights {dimension id: weight} (default 1 each); dimensions (default the 12 of
    default_strategic_dimensions). A dimension with no score is left out and counted; a score outside 0-100 is held to the range.
    Output: strategic_score (None if nothing is scored), dimensions scored, missing, rows."""
    dims = [as_dict(d).get("id") for d in (as_list(dimensions) or default_strategic_dimensions())]
    w = {**{d: 1.0 for d in dims}, **{k: num(v, 0.0) for k, v in as_dict(weights).items()}}
    rows, tw, ts, missing = [], 0.0, 0.0, []
    for d in dims:
        s = num(as_dict(scores).get(d))
        if s is None:
            missing.append(d)
            continue
        s = max(0.0, min(100.0, s))
        wt = max(0.0, w.get(d, 1.0))
        rows.append({"id": d, "score": s, "weight": wt})
        tw += wt
        ts += s * wt
    score = div(ts, tw)
    return {"strategic_score": rnd(score, 2), "dimensions_scored": len(rows), "dimensions_missing": missing, "rows": rows,
            "why": None if score is not None else "No dimension has a score.",
            "formula": "Strategic score = sum(score x weight) / sum(weight) over the dimensions that have a score (each 0-100)."}


# ---------------------------------------------------------------- cash flows of each strategy

def _zeros(n):
    return [0.0] * (n + 1)


def _ramp(lease_up_years, n):
    """Average share of stabilised income in each operating year 1..n, for a straight-line lease-up."""
    L = num(lease_up_years, 2.0)
    if L is None or L <= 0:
        return [1.0] * n
    s = absorption_schedule(1.0, absorption_per_month=1.0 / (12.0 * L), horizon_months=12 * max(1, n), include_monthly=False)
    f = [y["average_fraction_of_quantity"] for y in s["yearly"]]
    return (f + [1.0] * n)[:n]


def _rent_at(rent0, t, start, g):
    """Ground rent in year t: escalation_pct a year, or bump_pct every bump_years."""
    if t < start:
        return 0.0
    n = t - start
    try:
        if g.get("bump_pct") is not None and num(g.get("bump_years")):
            return rent0 * ((1.0 + frac(g["bump_pct"])) ** (n // cap_int(g["bump_years"], 1, 1, 100)))
        return rent0 * ((1.0 + (frac(g.get("escalation_pct")) or 0.0)) ** n)
    except OverflowError:
        return float("inf")


def _flows(name, p, A, H):
    """One strategy for one horizon: components by year (income, capex, lump, terminal), a basis sentence, notes, availability."""
    land = num(p.get("land_value_usd"))
    a = frac(p.get("appreciation_pct") if p.get("appreciation_pct") is not None else A["appreciation_pct"])
    sc = frac(as_dict(p.get("sale")).get("sale_cost_pct") if as_dict(p.get("sale")).get("sale_cost_pct") is not None else A["sale_cost_pct"]) or 0.0
    out = {"income": _zeros(H), "capex": _zeros(H), "lump": _zeros(H), "terminal": _zeros(H), "basis": "", "notes": [], "available": True, "why": None}
    if land is None or land < 0 or a is None:
        out.update({"available": False, "why": "The parcel needs a land value (today's entitled value) and an appreciation rate."})
        return out
    dev = as_dict(p.get("develop"))
    if name == "fee_simple_sale":
        ts = cap_int(as_dict(p.get("sale")).get("sale_year"), 1, 0, 100)
        if ts <= H:
            out["lump"][ts] = land * ((1.0 + a) ** ts) * (1.0 - sc)
        out["basis"] = f"Sold in year {ts} at today's value grown {a * 100:g}% a year, less selling costs."
        return out
    if name == "hold_develop":
        cost, noi = num(dev.get("total_cost_usd")), num(dev.get("stabilized_noi_usd"))
        cap = frac(dev.get("exit_cap_pct"))
        if cost is None or noi is None or not cap:
            carry = num(p.get("carry_cost_usd_per_year"), 0.0)
            for t in range(1, H + 1):
                out["income"][t] -= carry
            out["terminal"][H] = land * ((1.0 + a) ** H) * (1.0 - sc)
            out["basis"] = "Land held and sold at the horizon (no development inputs given): appreciation only, less carry and selling costs."
            out["notes"].append("No development cost, NOI and exit cap given: this is a land hold, not a development.")
            return out
        s, b = cap_int(dev.get("start_year"), 1, 0, 100), cap_int(dev.get("build_years"), 2, 1, 30)
        g = frac(dev.get("noi_growth_pct")) or 0.0
        for i in range(b):
            if s + i <= H:
                out["capex"][s + i] -= cost / b
        n_ops = H - (s + b) + 1
        if n_ops > 0:
            ramp = _ramp(dev.get("lease_up_years", 2), n_ops)
            for j in range(1, n_ops + 1):
                out["income"][s + b + j - 1] += noi * ramp[j - 1] * ((1.0 + g) ** (j - 1))
            out["terminal"][H] = noi * ((1.0 + g) ** n_ops) / cap * (1.0 - sc)
        else:
            out["notes"].append("The development is not delivered inside this horizon: no sale value counted.")
        out["basis"] = "Develop and hold: construction cost, NOI after lease-up, sale of the finished asset at the horizon. The land itself is not charged."
        return out
    if name == "joint_venture":
        j = as_dict(p.get("jv"))
        cost = num(j.get("project_cost_usd"), num(dev.get("total_cost_usd")))
        noi = num(j.get("stabilized_noi_usd"), num(dev.get("stabilized_noi_usd")))
        cap = frac(j.get("exit_cap_pct") if j.get("exit_cap_pct") is not None else dev.get("exit_cap_pct"))
        if cost is None or noi is None or not cap:
            out.update({"available": False, "why": "A joint venture needs the project cost, stabilised NOI and exit cap rate."})
            return out
        cash_out = (frac(j.get("cash_out_pct")) if j.get("cash_out_pct") is not None else 0.15)
        credit = land * (1.0 - cash_out)
        share = div(credit, credit + cost)
        if share is None:
            out.update({"available": False, "why": "The land credit and project cost add to zero."})
            return out
        s = cap_int(j.get("start_year"), cap_int(dev.get("start_year"), 1, 0, 100), 0, 100)
        b = cap_int(j.get("build_years"), cap_int(dev.get("build_years"), 2, 1, 30), 1, 30)
        g = frac(j.get("noi_growth_pct") if j.get("noi_growth_pct") is not None else dev.get("noi_growth_pct")) or 0.0
        if s <= H:
            out["lump"][s] += land * cash_out
        n_ops = H - (s + b) + 1
        if n_ops > 0:
            ramp = _ramp(j.get("lease_up_years", dev.get("lease_up_years", 2)), n_ops)
            for k in range(1, n_ops + 1):
                out["income"][s + b + k - 1] += share * noi * ramp[k - 1] * ((1.0 + g) ** (k - 1))
            out["terminal"][H] = share * noi * ((1.0 + g) ** n_ops) / cap * (1.0 - sc)
        else:
            out["notes"].append("The project is not delivered inside this horizon: no sale value counted.")
        out["basis"] = (f"Land contributed as equity: {share * 100:.1f}% of project equity (land credit / (land credit + project cost)), "
                        f"{cash_out * 100:.0f}% of land value taken as cash at close; unlevered, before any promote.")
        out["jv_equity_share_pct"] = share * 100.0
        return out
    # ground lease
    g = as_dict(p.get("ground_lease"))
    y = frac(g.get("rent_yield_pct"))
    if y is None or y <= 0:
        out.update({"available": False, "why": "A ground lease needs a rent yield on land value (rent_yield_pct)."})
        return out
    start = cap_int(g.get("start_year"), 1, 0, 100)
    rent0 = land * y
    key = (frac(g.get("key_money_pct")) or 0.0) * land
    out["lump"][0] += key
    for t in range(0, H + 1):
        out["income"][t] += _rent_at(rent0, t, start, g)
    if g.get("include_terminal_value", True):
        cap_lf = frac(g.get("leased_fee_cap_pct") if g.get("leased_fee_cap_pct") is not None else g.get("rent_yield_pct"))
        if cap_lf:
            out["terminal"][H] = _rent_at(rent0, H + 1, start, g) / cap_lf * (1.0 - sc)
    term = num(g.get("term_years"), 99.0)
    if term < 65 or term > 99:
        out["notes"].append(f"A ground lease term of {term:g} years is outside the 65-99 year range this comparison is built for.")
    out["basis"] = (f"NNN ground lease: rent = {num(g.get('rent_yield_pct')):g}% of land value, "
                    + (f"bumped {num(g.get('bump_pct')):g}% every {cap_int(g.get('bump_years'), 1, 1, 100)} years" if g.get("bump_pct") is not None
                       else f"escalating {num(g.get('escalation_pct'), 0.0):g}% a year")
                    + "; the tenant builds and insures; the leased fee is sold at the horizon at the leased-fee cap rate.")
    out["term_years"] = term
    return out


def _total(f):
    return [f["income"][t] + f["capex"][t] + f["lump"][t] + f["terminal"][t] for t in range(len(f["income"]))]


def _measure(name, p, A, horizons):
    res = {"available": True, "why": None, "notes": [], "basis": "", "npv_by_horizon_usd": {}}
    rate = frac(A["discount_rate_pct"])
    last = None
    for H in horizons:
        f = _flows(name, p, A, H)
        if not f["available"]:
            return {**res, "available": False, "why": f["why"]}
        tot = _total(f)
        res["npv_by_horizon_usd"][str(H)] = usd(npv(rate, tot))
        last = (H, f, tot)
    H, f, tot = last
    res["basis"], res["notes"] = f["basis"], f["notes"]
    inc = f["income"][1:]
    cum, peak = 0.0, 0.0
    for t in range(H + 1):
        cum += f["income"][t] + f["capex"][t] + f["lump"][t]
        peak = min(peak, cum)
    first = next((t for t in range(H + 1) if f["income"][t] + f["lump"][t] > 0), None)
    res.update({"upfront_cash_usd": usd(sum(f["income"][t] + f["lump"][t] for t in (0, 1))),
                "capital_required_usd": usd(-peak), "recurring_income_usd_yr": usd(sum(inc) / H if H else None),
                "first_cash_month": None if first is None else first * 12, "cash_flows": [usd(x) for x in tot],
                "jv_equity_share_pct": rnd(f.get("jv_equity_share_pct"), 4), "term_years": f.get("term_years")})
    return res


def _scale(values, lower_better):
    """0-100 scores from a {strategy: number} map, min-max across the strategies that have one."""
    have = {k: v for k, v in values.items() if v is not None}
    if not have:
        return {k: None for k in values}
    lo, hi = min(have.values()), max(have.values())
    out = {}
    for k, v in values.items():
        if v is None:
            out[k] = None
        elif hi - lo < 1e-9:
            out[k] = 50.0
        else:
            s = (v - lo) / (hi - lo) * 100.0
            out[k] = 100.0 - s if lower_better else s
    return out


@public
def compare_strategies(parcel, assumptions=None, criteria_weights=None, strategy_profiles=None):
    """Fee-simple sale vs hold and develop vs institutional joint venture vs 65-99 year NNN ground lease for one parcel.

    Inputs: parcel {id, net_ac, land_value_usd (today's entitled value), appreciation_pct, sale {sale_year (1), sale_cost_pct},
    carry_cost_usd_per_year, develop {total_cost_usd (land excluded), stabilized_noi_usd, start_year (1), build_years (2), lease_up_years (2),
    exit_cap_pct, noi_growth_pct}, jv {cash_out_pct (15), project_cost_usd, stabilized_noi_usd, exit_cap_pct (default to develop's)},
    ground_lease {rent_yield_pct, escalation_pct or bump_pct + bump_years, key_money_pct, term_years (99), start_year (1),
    leased_fee_cap_pct (default = rent yield), include_terminal_value (True)}};
    assumptions {discount_rate_pct (8), horizons_years (10, 15), appreciation_pct (3), sale_cost_pct (4.36), strategic_influence (0.3)};
    criteria_weights {criterion id: weight} over the 9 default criteria; strategy_profiles {strategy: {execution_risk_score 0-100,
    control_retained_pct, upside_retained_pct}} (starting assumptions are in DEFAULT_PROFILES).
    Output per strategy: npv_by_horizon_usd (10 and 15 years), upfront cash, capital required, recurring income per year, months to first
    cash, the 9 criterion scores (0-100), the weighted economic score, and the basis sentence; a ranking by NPV over the last horizon."""
    p, A = as_dict(parcel), {**DEFAULT_DECISION, **as_dict(assumptions)}
    horizons = [cap_int(h, 0, 1, 100) for h in as_list(A["horizons_years"]) if num(h) and num(h) > 0] or [10, 15]
    prof = {s: {**DEFAULT_PROFILES[s], **as_dict(as_dict(strategy_profiles).get(s)), **as_dict(as_dict(p.get("strategy_profiles")).get(s))} for s in STRATEGIES}
    weights = {c[0]: c[2] for c in DEFAULT_ECONOMIC_CRITERIA}
    weights.update({k: num(v, 0.0) for k, v in as_dict(criteria_weights).items() if k in weights})
    meas = {s: _measure(s, p, A, horizons) for s in STRATEGIES}
    avail = [s for s in STRATEGIES if meas[s]["available"]]
    first_h, last_h = str(horizons[0]), str(horizons[-1])
    metrics = {
        "npv_10_year": {s: num(meas[s]["npv_by_horizon_usd"].get(first_h)) for s in avail},
        "npv_15_year": {s: num(meas[s]["npv_by_horizon_usd"].get(last_h)) for s in avail},
        "upfront_cash": {s: num(meas[s]["upfront_cash_usd"]) for s in avail},
        "capital_required": {s: num(meas[s]["capital_required_usd"]) for s in avail},
        "recurring_income": {s: num(meas[s]["recurring_income_usd_yr"]) for s in avail},
        "time_to_first_cash": {s: meas[s]["first_cash_month"] for s in avail},
        "execution_risk": {s: num(prof[s]["execution_risk_score"]) for s in avail},
        "control_retained": {s: num(prof[s]["control_retained_pct"]) for s in avail},
        "upside_retained": {s: num(prof[s]["upside_retained_pct"]) for s in avail},
    }
    scored = {cid: _scale(vals, cid in LOWER_IS_BETTER) for cid, vals in metrics.items()}
    for s in STRATEGIES:
        r = meas[s]
        if not r["available"]:
            r.update({"criteria_scores": {}, "economic_score": None})
            continue
        cs = {cid: rnd(scored[cid].get(s), 2) for cid in weights}
        tw = sum(weights[c] for c in weights if cs[c] is not None)
        r["criteria_scores"] = cs
        r["economic_score"] = rnd(div(sum(weights[c] * cs[c] for c in weights if cs[c] is not None), tw), 2)
    ranked = sorted((s for s in avail if num(meas[s]["npv_by_horizon_usd"].get(last_h)) is not None),
                    key=lambda s: -num(meas[s]["npv_by_horizon_usd"][last_h]))
    return {"parcel_id": p.get("id"), "strategies": {s: {"label": STRATEGY_LABELS[s], **meas[s]} for s in STRATEGIES},
            "ranking_by_npv": ranked, "ranked_by": f"NPV over {last_h} years",
            "criteria": [{"id": i, "label": label, "weight": weights[i]} for i, label, _ in DEFAULT_ECONOMIC_CRITERIA],
            "assumptions": {"discount_rate_pct": num(A["discount_rate_pct"]), "horizons_years": horizons,
                            "appreciation_pct": num(p.get("appreciation_pct"), num(A["appreciation_pct"])), "sale_cost_pct": num(A["sale_cost_pct"]),
                            "strategy_profiles": prof},
            "formula": ["Each strategy gives a cash flow by year; NPV = sum of flow / (1 + discount rate)^year to each horizon.",
                        "Sale: price grown at the appreciation rate less selling cost. Develop: -cost, + NOI after lease-up, + sale at the horizon.",
                        "Joint venture: cash-out at close + the land's share of NOI and sale; share = land credit / (land credit + project cost).",
                        "Ground lease: key money + rent (land value x yield, escalated) + the leased fee sold at the horizon.",
                        "Each criterion is scored 0-100 across the strategies (best = 100); economic score = weighted average."],
            "disclaimer": DISCLAIMER}


def _critical(p, score, A):
    return bool(p.get("critical") or p.get("must_keep") or (score is not None and score >= num(A["critical_threshold"], 75.0)))


@public
def critical_asset_conflicts(parcels, sell_ids=None, assumptions=None, recommendations=None):
    """Flags where a plan sells something the strategy says to keep.

    Inputs: parcels [{id, strategic_score or strategic_scores {dimension: 0-100}, critical, must_keep, do_not_sell_until_month,
    planned_sale_month}]; sell_ids (the parcel ids a cash plan sells, for example the picks of solve_capital_targets);
    recommendations {parcel id: recommended strategy}; assumptions {critical_threshold (75)}.
    A parcel is a critical strategic asset if flagged, or its strategic score is at or above the threshold.
    Output: conflicts [{parcel_id, kind (cash_plan_sells_critical_asset, recommendation_is_sale, sold_inside_hold_period), why}], critical ids."""
    A = {**DEFAULT_DECISION, **as_dict(assumptions)}
    sells = set(as_list(sell_ids))
    recs = as_dict(recommendations)
    conflicts, crit_ids = [], []
    for p in as_list(parcels):
        p = as_dict(p)
        score = num(p.get("strategic_score"))
        if score is None and p.get("strategic_scores"):
            score = score_strategic_dimensions(p["strategic_scores"], A.get("dimension_weights"))["strategic_score"]
        crit = _critical(p, score, A)
        pid = p.get("id")
        if crit:
            crit_ids.append(pid)
        if crit and pid in sells:
            conflicts.append({"parcel_id": pid, "kind": "cash_plan_sells_critical_asset", "strategic_score": score,
                              "why": f"The cash plan sells {pid}, which is a critical strategic asset (score {score if score is not None else 'n/a'}, "
                                     f"threshold {num(A['critical_threshold']):g})."})
        if crit and recs.get(pid) == "fee_simple_sale":
            conflicts.append({"parcel_id": pid, "kind": "recommendation_is_sale", "strategic_score": score,
                              "why": f"The economics favour selling {pid}, but it is a critical strategic asset."})
        until, when = num(p.get("do_not_sell_until_month")), num(p.get("planned_sale_month"))
        if until is not None and when is not None and when < until:
            conflicts.append({"parcel_id": pid, "kind": "sold_inside_hold_period", "strategic_score": score,
                              "why": f"{pid} is planned to sell in month {when:g}, before its do-not-sell date (month {until:g})."})
    return {"conflicts": conflicts, "critical_parcel_ids": crit_ids, "conflict_count": len(conflicts),
            "formula": "Critical = flagged, or strategic score >= threshold. A conflict is a critical parcel in the cash plan or recommended for sale, "
                       "or any parcel planned for sale before its do-not-sell month."}


@public
def decide_parcels(parcels, assumptions=None, criteria_weights=None, dimension_weights=None, strategy_profiles=None, sell_ids=None):
    """The hold / sell / joint venture / ground lease decision for each parcel, with the critical-asset conflicts.

    Inputs: parcels (each as for compare_strategies, plus strategic_scores {dimension: 0-100} over the 12 dimensions, or strategic_score,
    critical, must_keep, do_not_sell_until_month, planned_sale_month); assumptions (as compare_strategies, plus critical_threshold 75 and
    strategic_influence 0.3); criteria_weights; dimension_weights {dimension id: weight}; strategy_profiles; sell_ids (the parcels a cash plan sells).
    For each parcel: strategic score, the four strategies compared, the combined score of each, the recommendation, and a guarded
    recommendation that never selects a sale for a critical asset.
    combined score = (1 - k) x economic score + k x (strategic score x control kept + (100 - strategic score) x (1 - control kept)),
    with k = strategic_influence, so a high-scoring parcel is rewarded for keeping control and a low-scoring one for selling."""
    A = {**DEFAULT_DECISION, **as_dict(assumptions)}
    k = max(0.0, min(1.0, num(A["strategic_influence"], 0.3)))
    rows, recs = [], {}
    for p in as_list(parcels):
        p = as_dict(p)
        sd = score_strategic_dimensions(p.get("strategic_scores"), dimension_weights) if p.get("strategic_scores") else None
        score = num(p.get("strategic_score"), num(sd["strategic_score"]) if sd else None)
        cmp_ = compare_strategies(p, A, criteria_weights, strategy_profiles)
        if cmp_.get("failed"):
            rows.append({"id": p.get("id"), "name": p.get("name"), "net_ac": num(p.get("net_ac")), "strategic_score": rnd(score, 2),
                         "strategic_dimensions": sd, "critical_strategic_asset": _critical(p, score, A), "comparison": None, "combined_scores": {},
                         "recommended_strategy": None, "guarded_recommendation": None, "why": cmp_["why"]})
            continue
        combined = {}
        for s in STRATEGIES:
            r = cmp_["strategies"][s]
            ctrl = num(cmp_["assumptions"]["strategy_profiles"][s]["control_retained_pct"], 0.0) / 100.0
            if r["economic_score"] is None:
                r["combined_score"] = None
            elif score is None:
                r["combined_score"] = r["economic_score"]
            else:
                r["combined_score"] = rnd((1.0 - k) * r["economic_score"] + k * (score * ctrl + (100.0 - score) * (1.0 - ctrl)), 2)
            if r["combined_score"] is not None:
                combined[s] = r["combined_score"]
        best = max(combined, key=combined.get) if combined else None
        crit = _critical(p, score, A)
        guarded = best
        if crit and best == "fee_simple_sale":
            rest = {s: v for s, v in combined.items() if s != "fee_simple_sale"}
            guarded = max(rest, key=rest.get) if rest else None
        if best:
            recs[p.get("id")] = best
        rows.append({"id": p.get("id"), "name": p.get("name"), "net_ac": num(p.get("net_ac")), "strategic_score": rnd(score, 2),
                     "strategic_dimensions": sd, "critical_strategic_asset": crit, "comparison": cmp_, "combined_scores": combined,
                     "recommended_strategy": best, "guarded_recommendation": guarded,
                     "why": None if best else "No strategy could be scored: check the land value and strategy inputs."})
    conflicts = critical_asset_conflicts(parcels, sell_ids, A, recs)
    for r in rows:
        r["conflicts"] = [c for c in conflicts["conflicts"] if c["parcel_id"] == r["id"]]
    counts = {s: sum(1 for r in rows if r["guarded_recommendation"] == s) for s in STRATEGIES}
    return {"parcels": rows, "recommendation_counts": counts, "critical_asset_conflicts": conflicts,
            "assumptions": {**{kk: vv for kk, vv in A.items()}, "strategic_influence": k},
            "formula": ["Strategic score = weighted average of the 12 dimension scores (0-100).",
                        "Economic score = weighted average of the 9 criteria, each scored 0-100 across the four strategies.",
                        "Combined = (1 - k) x economic + k x (strategic x control kept + (100 - strategic) x (1 - control kept)).",
                        "A critical strategic asset is never given a sale as its guarded recommendation, and a cash plan that sells one is flagged."],
            "disclaimer": DISCLAIMER}
