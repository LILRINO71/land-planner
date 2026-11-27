"""Absorption and lease-up schedules, phasing triggers, and the phase pro forma (phases 1-4 and full buildout).

The pro forma is unlevered and annual: year index t = 0 is the phase's first year, money at the end of each year.
It is an economic model under the caller's assumptions, not an appraisal and not a forecast the numbers are promised.
"""
import math

from .finance_common import (DISCLAIMER, MONTHS_PER_YEAR, cap_int, as_dict, as_list, equity_multiple, frac, irr, npv, num, pct_of, public,
                             rnd, usd)
from .finance_uses import line_item_costs, use_economics, use_program

# ---------------------------------------------------------------- absorption and lease-up


def _schedule(quantity, rate, start_month, occ_frac, pre_qty, deliveries, horizon):
    """The monthly arithmetic. Returns (rows, delivered_total)."""
    rows, cum = [], min(pre_qty, quantity * occ_frac)
    for m in range(1, horizon + 1):
        delivered = sum(d["quantity"] for d in deliveries if d["month"] <= m)
        cap = delivered * occ_frac
        absorbed = 0.0
        if m >= start_month and delivered > 0:
            new = min(cap, cum + rate)
            absorbed = max(0.0, new - cum)
            cum = max(cum, new)
        rows.append({"month": m, "delivered": delivered, "absorbed_in_month": absorbed, "cumulative": cum,
                     "occupancy_pct": (cum / delivered * 100.0) if delivered > 0 else None})
    return rows


@public
def absorption_schedule(quantity, absorption_per_month=None, absorption_per_year=None, start_month=1, stabilized_occupancy_pct=100.0,
                        pre_leased_pct=0.0, deliveries=None, horizon_months=120, unit_label="units", include_monthly=True):
    """Lease-up or sales absorption by month and by year, with the stabilisation month.

    Inputs: quantity (units, keys or SF; the same unit as the absorption rate); exactly one of absorption_per_month or
    absorption_per_year (quantity absorbed per month, or per year: give one, never both); start_month (first month units are
    delivered and absorption begins, default 1); stabilized_occupancy_pct (the share of the quantity that fills, default 100;
    use 95 for a 5% vacancy); pre_leased_pct (% of the quantity already committed when the first units open); deliveries
    [{month, quantity}] if the quantity is delivered in stages (default: all at start_month); horizon_months (default 120).
    Output: monthly rows {month, delivered, absorbed_in_month, cumulative, occupancy_pct}; yearly rows {year, absorbed_in_year,
    end_cumulative, average_occupancy_pct, average_fraction_of_quantity}; stabilization_month and stabilization_year
    (None and a `why` if it is not reached inside the horizon)."""
    q = num(quantity)
    out = {"unit_label": unit_label, "quantity": q, "monthly": [], "yearly": [], "stabilization_month": None, "stabilization_year": None,
           "target_quantity": None, "absorption_per_month": None, "why": None,
           "assumptions": {"start_month": start_month, "stabilized_occupancy_pct": num(stabilized_occupancy_pct),
                           "pre_leased_pct": num(pre_leased_pct), "horizon_months": horizon_months},
           "formula": ["Each month, cumulative absorbed = min(delivered x stabilised occupancy, previous cumulative + monthly rate).",
                       "Monthly rate = absorption per month, or absorption per year / 12.",
                       "Stabilisation month = first month the cumulative reaches the target and every delivery has arrived."]}
    if q is None or q <= 0:
        out["why"] = "The quantity must be above zero."
        return out
    pm, py = num(absorption_per_month), num(absorption_per_year)
    if pm is not None and py is not None:
        out["why"] = "Give the absorption per month or per year, not both."
        return out
    rate = pm if pm is not None else (py / MONTHS_PER_YEAR if py is not None else None)
    occ = frac(stabilized_occupancy_pct)
    pre = (frac(pre_leased_pct) or 0.0) * q
    start = cap_int(start_month, 1, 1, 1200)
    horizon = cap_int(horizon_months, 120, 1, 1200)
    if rate is None or rate < 0 or occ is None or occ <= 0 or occ > 1.0000001:
        out["why"] = "Give a monthly or yearly absorption (zero or more) and an occupancy between 0 and 100%."
        return out
    dels = [{"month": cap_int(d.get("month"), 1, 1, 1200), "quantity": num(d.get("quantity"), 0.0)} for d in as_list(deliveries) if isinstance(d, dict)]
    dels = dels or [{"month": start, "quantity": q}]
    total_delivered = sum(d["quantity"] for d in dels)
    rows = _schedule(q, rate, start, occ, pre, dels, horizon)
    target = total_delivered * occ
    out["target_quantity"], out["absorption_per_month"] = target, rate
    last_delivery = max(d["month"] for d in dels)
    for r in rows:
        if r["cumulative"] >= target - 1e-9 and r["month"] >= last_delivery:
            out["stabilization_month"] = r["month"]
            out["stabilization_year"] = int(math.ceil(r["month"] / MONTHS_PER_YEAR))
            break
    if out["stabilization_month"] is None:
        out["why"] = f"Not stabilised inside {horizon} months at {rate:,.2f} per month."
    years = int(math.ceil(horizon / MONTHS_PER_YEAR))
    for y in range(1, years + 1):
        chunk = rows[(y - 1) * 12:y * 12]
        if not chunk:
            break
        avg = sum(r["cumulative"] for r in chunk) / len(chunk)
        out["yearly"].append({"year": y, "absorbed_in_year": rnd(sum(r["absorbed_in_month"] for r in chunk), 4),
                              "end_cumulative": rnd(chunk[-1]["cumulative"], 4),
                              "average_occupancy_pct": rnd(pct_of(avg, total_delivered), 4),
                              "average_fraction_of_quantity": avg / q})
    out["monthly"] = [{"month": r["month"], "delivered": rnd(r["delivered"], 4), "absorbed_in_month": rnd(r["absorbed_in_month"], 4),
                       "cumulative": rnd(r["cumulative"], 4), "occupancy_pct": rnd(r["occupancy_pct"], 4)} for r in rows] if include_monthly else []
    return out


@public
def schedule_status_at_month(schedule, month, pre_leased_pct=0.0):
    """The trigger metrics of an absorption schedule at a month: units_delivered, units_absorbed, occupancy_pct,
    pre_leasing_pct (the input, as it was before opening), absorption_per_month (average of the last 6 months).
    Inputs: a schedule from absorption_schedule (with monthly rows) and the month."""
    rows = as_list(as_dict(schedule).get("monthly"))
    m = cap_int(month, 0, 0, 1200)
    if not rows or m < 1:
        return {"month": m, "metrics": {}, "why": "The schedule has no monthly rows (or the month is below 1)."}
    upto = [r for r in rows if r["month"] <= m]
    if not upto:
        return {"month": m, "metrics": {}, "why": "The month is beyond the schedule."}
    last = upto[-1]
    recent = upto[-6:]
    return {"month": m, "why": None,
            "metrics": {"units_delivered": last["delivered"], "units_absorbed": last["cumulative"], "occupancy_pct": last["occupancy_pct"],
                        "pre_leasing_pct": num(pre_leased_pct), "absorption_per_month": rnd(sum(r["absorbed_in_month"] for r in recent) / len(recent), 4)}}


_OPS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b,
        "==": lambda a, b: abs(a - b) < 1e-9}


@public
def evaluate_phasing_triggers(triggers, status):
    """Checks phasing triggers against the current status.

    Inputs: triggers [{id, label, metric, operator (>=, >, <=, <, ==), threshold}] e.g. metric units_delivered >= 200;
    status {metric: value}. A metric with no value is reported as unknown ("not known"), never as met or not met.
    Output: per trigger {state: met | not_met | unknown, value, threshold, gap}; counts; all_met (True only if every trigger is met)."""
    st = as_dict(status)
    rows, counts = [], {"met": 0, "not_met": 0, "unknown": 0}
    for t in as_list(triggers):
        t = as_dict(t)
        op, thr, val = t.get("operator", ">="), num(t.get("threshold")), num(st.get(t.get("metric")))
        if op not in _OPS or thr is None:
            state, gap, why = "unknown", None, "The trigger needs an operator and a threshold."
        elif val is None:
            state, gap, why = "unknown", None, "Not known: no value for " + str(t.get("metric")) + "."
        else:
            met = _OPS[op](val, thr)
            state, gap, why = ("met" if met else "not_met"), (0.0 if met else thr - val), None
        counts[state] += 1
        rows.append({"id": t.get("id"), "label": t.get("label") or t.get("metric"), "metric": t.get("metric"), "operator": op,
                     "threshold": thr, "value": val, "state": state, "gap": rnd(gap, 4), "why": why})
    n = len(rows)
    return {"triggers": rows, "counts": counts, "all_met": bool(n) and counts["met"] == n, "any_unknown": counts["unknown"] > 0,
            "summary": f"{counts['met']} of {n} met, {counts['not_met']} not met, {counts['unknown']} not known",
            "formula": "Each trigger compares the current value of its metric with the threshold; a missing value stays unknown."}


# ---------------------------------------------------------------- cash flow metrics

@public
def cash_flow_metrics(flows, discount_rate_pct=10.0, base_year=None):
    """Return measures of one stream of yearly cash flows (flow 0 first; negative is money out).

    Inputs: flows [numbers], discount_rate_pct (for the NPV), base_year (labels the years if given).
    Output: irr {irr_pct, converged, method (newton or bisection), iterations, residual_npv_usd, sign_changes, why},
    npv_usd, equity_multiple, total_in_usd, total_out_usd, peak_cumulative_outflow_usd, payback_year_index, dated flows."""
    cf = [num(f, 0.0) for f in as_list(flows)]
    r = irr(cf)
    cum, low, payback = 0.0, 0.0, None
    for i, f in enumerate(cf):
        cum += f
        low = min(low, cum)
        if payback is None and cum >= 0 and any(c < 0 for c in cf[:i + 1]):
            payback = i
    return {"irr": {k: (rnd(v, 4) if k == "irr_pct" else v) for k, v in r.items() if k != "irr"},
            "npv_usd": usd(npv(frac(discount_rate_pct), cf)), "discount_rate_pct": num(discount_rate_pct),
            "equity_multiple": rnd(equity_multiple(cf), 4), "total_in_usd": usd(sum(c for c in cf if c > 0)),
            "total_out_usd": usd(-sum(c for c in cf if c < 0)), "peak_cumulative_outflow_usd": usd(-low), "payback_year_index": payback,
            "flows": [{"t": i, "year": (int(base_year) + i) if num(base_year) is not None else None, "net_usd": usd(f)} for i, f in enumerate(cf)],
            "formula": ["IRR: the rate that makes the present value of the flows zero (Newton-Raphson, bisection if Newton does not settle).",
                        "NPV = sum of flow_t / (1 + rate)^t. Equity multiple = money back / money put in."]}


# ---------------------------------------------------------------- the phase pro forma

DEFAULT_PROFORMA = {"discount_rate_pct": 10.0, "hold_years": 10, "build_years": 2, "lease_up_months": 24, "sellout_months": 24,
                    "noi_growth_pct": 0.0, "hurdle_yoc_pct": None, "hurdle_irr_pct": None, "base_year": None}


def _pick(key, *sources, default=None):
    for s in sources:
        v = as_dict(s).get(key)
        if v is not None:
            return v
    return default


def _spend_curve(curve, years):
    c = [num(x, 0.0) for x in as_list(curve)]
    if len(c) == years and years > 0 and abs(sum(c) - 100.0) <= 0.5 and all(x >= 0 for x in c):
        total = sum(c)
        return [x / total for x in c]
    return [1.0 / years] * years if years > 0 else []


def _add(arr, t, v):
    while len(arr) <= t:
        arr.append(0.0)
    arr[t] += v


def _line(line, library, phase, ap, land_usd):
    """One program line: its cost, income or sales, and its cash flows by local year index."""
    line = as_dict(line)
    use_id = line.get("use")
    ud = as_dict(as_dict(library).get(use_id))
    out = {"use": use_id, "label": ud.get("label") or use_id, "net_ac": None, "units": None, "building_sf": None, "cost_usd": None,
           "cost_unknown_items": 0, "cost_is_partial": False, "land_cost_usd": land_usd, "stabilized_noi_usd": None,
           "implied_value_usd": None, "net_sales_usd": None, "is_sale": False, "flows": {}, "why": None}
    if not ud:
        out["why"] = f"The use '{use_id}' is not in the land use library."
        return out
    prog = use_program(ud, net_ac=line.get("net_ac"), units=line.get("units"), building_sf=line.get("building_sf"))
    out.update({"net_ac": prog["net_ac"], "units": prog["units"], "building_sf": prog["building_sf"]})
    econ = use_economics(ud, prog)
    costs = line_item_costs(ud.get("cost_line_items"), prog["net_ac"], prog["building_sf"], prog["units"])
    out.update({"cost_usd": costs["total_usd"], "cost_unknown_items": costs["unknown_items"], "cost_is_partial": costs["is_partial"],
                "is_sale": econ["is_sale"]})
    if econ["why"]:
        out["why"] = econ["why"]
    build = cap_int(_pick("build_years", line, phase, ap, default=2), 2, 1, 30)
    start = cap_int(_pick("start_offset_years", line, default=0), 0, 0, 100)
    curve = _spend_curve(_pick("spend_curve_pct", line, phase, ap), build)
    flows = {"land": [], "construction": [], "noi": [], "sales": [], "exit": []}
    if land_usd:
        _add(flows["land"], start, -land_usd)
    for i, share in enumerate(curve):
        _add(flows["construction"], start + i, -costs["total_usd"] * share)
    ops0 = start + build                                     # first operating year index
    growth = (num(_pick("noi_growth_pct", line, phase, ap, default=0.0), 0.0)) / 100.0
    sell = frac(ud.get("sales_cost_pct")) or 0.0
    if econ["is_sale"]:
        qty = prog["units"] if as_dict(ud.get("revenue")).get("type") == "per_unit_sale" else prog["building_sf"]
        months = cap_int(_pick("sellout_months", line, phase, ap, default=24), 24, 1, 1200)
        rate = num(line.get("absorption_per_month"), (qty or 0.0) / months)
        if econ["net_sales_usd"] is not None and qty:
            sched = absorption_schedule(qty, absorption_per_month=rate, horizon_months=max(months * 4, 24), include_monthly=False)
            per_q = econ["net_sales_usd"] / qty
            for y in sched["yearly"]:
                if y["absorbed_in_year"]:
                    _add(flows["sales"], ops0 + y["year"] - 1, per_q * y["absorbed_in_year"])
            out["net_sales_usd"] = econ["net_sales_usd"]
        return _finish(out, flows)
    noi = econ["noi_usd_yr"]
    out["stabilized_noi_usd"] = noi
    cap = frac(ud.get("exit_cap_pct") if ud.get("exit_cap_pct") is not None else ud.get("cap_rate_pct"))
    if noi is not None and cap and cap > 0:
        out["implied_value_usd"] = noi / cap * (1.0 - sell)
    if noi is None:
        return _finish(out, flows)
    hold = cap_int(_pick("hold_years", line, phase, ap, default=10), 10, 1, 100)
    qty = prog["building_sf"] if as_dict(ud.get("revenue")).get("type") == "rent_per_sf_yr" else prog["units"]
    months = cap_int(_pick("lease_up_months", line, phase, ap, default=24), 24, 1, 1200)
    if qty:
        rate = num(line.get("absorption_per_month"), qty / months)
        sched = absorption_schedule(qty, absorption_per_month=rate, horizon_months=hold * 12, include_monthly=False)
        fracs = [y["average_fraction_of_quantity"] for y in sched["yearly"]]
    else:
        fracs = []
    for j in range(1, hold + 1):
        f = fracs[j - 1] if j - 1 < len(fracs) else 1.0
        _add(flows["noi"], ops0 + j - 1, noi * f * ((1.0 + growth) ** (j - 1)))
    if cap and cap > 0:
        _add(flows["exit"], ops0 + hold - 1, noi * ((1.0 + growth) ** hold) / cap * (1.0 - sell))
    else:
        out["why"] = out["why"] or "No exit cap rate: the sale at the end of the hold is left out."
    return _finish(out, flows)


def _finish(out, flows):
    out["flows"] = flows
    return out


def _allocate_land(land_total, lines_in):
    """Phase land cost split across lines by net acres (equally if no line has acres)."""
    if not land_total:
        return [0.0] * len(lines_in)
    acres = [num(l.get("net_ac")) or 0.0 for l in lines_in]
    total = sum(acres)
    if total > 0:
        return [land_total * a / total for a in acres]
    return [land_total / len(lines_in)] * len(lines_in) if lines_in else []


def _sum_flows(lines):
    kinds = ("land", "construction", "noi", "sales", "exit")
    n = max([len(l["flows"].get(k, [])) for l in lines for k in kinds] + [0])
    by = {k: [0.0] * n for k in kinds}
    for l in lines:
        for k in kinds:
            for t, v in enumerate(l["flows"].get(k, [])):
                by[k][t] += v
    return by, n


def _dated(by, n, base_year, offset=0):
    rows = []
    for t in range(n):
        net = sum(by[k][t] for k in by)
        rows.append({"t": t, "year": (int(base_year) + offset + t) if num(base_year) is not None else None,
                     "land_usd": usd(by["land"][t]), "construction_cost_usd": usd(by["construction"][t]), "noi_usd": usd(by["noi"][t]),
                     "sales_net_usd": usd(by["sales"][t]), "exit_net_usd": usd(by["exit"][t]), "net_usd": usd(net)})
    return rows


def _summary(lines, by, n, ap, label_id):
    income = [l for l in lines if not l["is_sale"]]
    cost = sum(l["cost_usd"] or 0.0 for l in lines)
    land = sum(l["land_cost_usd"] or 0.0 for l in lines)
    inc_cost = sum((l["cost_usd"] or 0.0) + (l["land_cost_usd"] or 0.0) for l in income)
    inc_cost_ex = sum(l["cost_usd"] or 0.0 for l in income)
    noi = sum(l["stabilized_noi_usd"] or 0.0 for l in income)
    value = sum(l["implied_value_usd"] or 0.0 for l in income)
    yoc, yoc_ex = pct_of(noi, inc_cost) if income else None, pct_of(noi, inc_cost_ex) if income else None
    hurdle = num(ap.get("hurdle_yoc_pct"))
    spread = None if yoc is None or hurdle is None else yoc - hurdle
    net = [sum(by[k][t] for k in by) for t in range(n)]
    rate = num(ap.get("discount_rate_pct"), 10.0)
    metrics = cash_flow_metrics(net, rate, ap.get("base_year"))
    hirr = num(ap.get("hurdle_irr_pct"))
    irr_pct = metrics["irr"]["irr_pct"]
    unknown = sum(l["cost_unknown_items"] for l in lines)
    return {
        "totals": {"development_cost_usd": usd(cost), "land_cost_usd": usd(land), "total_cost_incl_land_usd": usd(cost + land),
                   "stabilized_noi_usd_yr": usd(noi), "implied_value_usd": usd(value) if income else None,
                   "net_sales_revenue_usd": usd(sum(l["net_sales_usd"] or 0.0 for l in lines)),
                   "development_margin_pct": rnd(pct_of(value - inc_cost, inc_cost), 4) if income and inc_cost else None,
                   "cost_unknown_items": unknown, "cost_is_partial": unknown > 0},
        "yield_on_cost": {"yoc_pct": rnd(yoc, 4), "yoc_excl_land_pct": rnd(yoc_ex, 4), "hurdle_pct": hurdle,
                          "spread_pct_points": rnd(spread, 4), "spread_bps": rnd(None if spread is None else spread * 100.0, 1),
                          "meets_hurdle": None if spread is None else spread >= 0,
                          "income_cost_basis_usd": usd(inc_cost),
                          "why": None if income else "The phase has no income-producing use, so no yield on cost."},
        "irr": {**metrics["irr"], "hurdle_pct": hirr, "spread_pct_points": rnd(None if irr_pct is None or hirr is None else irr_pct - hirr, 4)},
        "equity_multiple": metrics["equity_multiple"], "npv": {"discount_rate_pct": rate, "npv_usd": metrics["npv_usd"]},
        "peak_cumulative_outflow_usd": metrics["peak_cumulative_outflow_usd"], "payback_year_index": metrics["payback_year_index"],
        "phase_id": label_id}


PROFORMA_FORMULA = [
    "Development cost = sum of the use's cost line items for the program (land excluded); spent over the build years on the spend curve.",
    "Stabilised NOI = effective income x (1 - operating expense share); income lease-up follows the absorption schedule.",
    "Implied value = stabilised NOI / exit cap rate x (1 - selling cost). Sale uses: net sales revenue arrives as units close.",
    "Yield on cost = stabilised NOI / (development cost + land cost); spread = yield on cost - hurdle yield.",
    "Net cash flow by year = land + construction + NOI + sales + exit sale. IRR is by Newton-Raphson with a bisection fallback.",
]


@public
def phase_pro_forma(phase, library, assumptions=None):
    """The pro forma of one phase: cost by line item, stabilised NOI, implied value, yield on cost vs a hurdle, dated yearly cash flows, IRR, NPV.

    Inputs: phase {id, label, land_cost_usd (split over the lines by net acres), start_offset_years (0), lines [{use (library id),
    net_ac OR units OR building_sf, land_cost_usd (this line's own), start_offset_years, build_years, spend_curve_pct [..],
    lease_up_months, absorption_per_month (units, or SF for rent_per_sf_yr uses), sellout_months, hold_years, noi_growth_pct}]};
    library (the land use library); assumptions {base_year, discount_rate_pct (10), hold_years (10, operating years before the
    sale), build_years (2), lease_up_months (24), sellout_months (24), noi_growth_pct (0), hurdle_yoc_pct, hurdle_irr_pct}.
    A line's own setting beats the phase's, which beats the assumptions'.
    Output: lines (program, cost line items, NOI, value), totals, yield_on_cost (with spread vs hurdle), irr (with converged flag,
    method and why), equity_multiple, npv, cash_flows (dated), unknown cost items counted, assumptions echoed, formula."""
    ph, ap = as_dict(phase), {**DEFAULT_PROFORMA, **as_dict(assumptions)}
    lines_in = [as_dict(l) for l in as_list(ph.get("lines"))]
    land_total = num(ph.get("land_cost_usd"), 0.0)
    prelim = [use_program(as_dict(as_dict(library).get(l.get("use"))), net_ac=l.get("net_ac"), units=l.get("units"), building_sf=l.get("building_sf"))
              for l in lines_in]
    shares = _allocate_land(land_total, prelim)
    lines = []
    for l, s in zip(lines_in, shares):
        own = num(l.get("land_cost_usd"))
        phase_for_line = {k: ph[k] for k in ("build_years", "spend_curve_pct", "lease_up_months", "sellout_months", "hold_years", "noi_growth_pct")
                          if k in ph}
        lines.append(_line(l, library, phase_for_line, ap, own if own is not None else s))
    by, n = _sum_flows(lines)
    summary = _summary(lines, by, n, ap, ph.get("id"))
    rows = [{"use": l["use"], "label": l["label"], "net_ac": rnd(l["net_ac"], 4), "units": rnd(l["units"], 2), "building_sf": rnd(l["building_sf"], 0),
             "development_cost_usd": usd(l["cost_usd"]), "land_cost_usd": usd(l["land_cost_usd"]),
             "cost_unknown_items": l["cost_unknown_items"], "stabilized_noi_usd_yr": usd(l["stabilized_noi_usd"]),
             "implied_value_usd": usd(l["implied_value_usd"]), "net_sales_usd": usd(l["net_sales_usd"]), "why": l["why"]} for l in lines]
    return {"phase_id": ph.get("id"), "label": ph.get("label"), "lines": rows, **{k: v for k, v in summary.items() if k != "phase_id"},
            "cash_flows": _dated(by, n, ap.get("base_year"), cap_int(ph.get("start_offset_years"), 0, 0, 100)),
            "assumptions": {k: ap.get(k) for k in DEFAULT_PROFORMA}, "formula": PROFORMA_FORMULA, "disclaimer": DISCLAIMER}


@public
def full_buildout_pro_forma(phases, library, assumptions=None):
    """Every phase (1-4) and the full buildout together.

    Inputs: phases [phase dicts as for phase_pro_forma, each with start_offset_years from the project's first year]; library; assumptions.
    Output: phases [each phase pro forma], full_buildout {totals, yield_on_cost, irr, equity_multiple, npv, cash_flows by project
    year} built from the phases' flows added together year by year, and unknown cost items counted across all phases."""
    ap = {**DEFAULT_PROFORMA, **as_dict(assumptions)}
    results = [phase_pro_forma(p, library, ap) for p in as_list(phases)]
    kinds = ("land", "construction", "noi", "sales", "exit")
    cols = {"land": "land_usd", "construction": "construction_cost_usd", "noi": "noi_usd", "sales": "sales_net_usd", "exit": "exit_net_usd"}
    horizon = max([cap_int(as_dict(p).get("start_offset_years"), 0, 0, 100) + len(r["cash_flows"]) for p, r in zip(as_list(phases), results)] + [0])
    by = {k: [0.0] * horizon for k in kinds}
    for p, r in zip(as_list(phases), results):
        off = cap_int(as_dict(p).get("start_offset_years"), 0, 0, 100)
        for row in r["cash_flows"]:
            for k in kinds:
                by[k][off + row["t"]] += row[cols[k]] or 0.0
    net = [sum(by[k][t] for k in kinds) for t in range(horizon)]
    metrics = cash_flow_metrics(net, ap.get("discount_rate_pct", 10.0), ap.get("base_year"))
    cost = sum(r["totals"]["development_cost_usd"] or 0.0 for r in results)
    land = sum(r["totals"]["land_cost_usd"] or 0.0 for r in results)
    noi = sum(r["totals"]["stabilized_noi_usd_yr"] or 0.0 for r in results)
    inc_basis = sum(r["yield_on_cost"]["income_cost_basis_usd"] or 0.0 for r in results)
    yoc = pct_of(noi, inc_basis) if inc_basis else None
    hurdle = num(ap.get("hurdle_yoc_pct"))
    return {"phases": results,
            "full_buildout": {"totals": {"development_cost_usd": usd(cost), "land_cost_usd": usd(land), "total_cost_incl_land_usd": usd(cost + land),
                                         "stabilized_noi_usd_yr": usd(noi),
                                         "implied_value_usd": usd(sum(r["totals"]["implied_value_usd"] or 0.0 for r in results)),
                                         "net_sales_revenue_usd": usd(sum(r["totals"]["net_sales_revenue_usd"] or 0.0 for r in results)),
                                         "cost_unknown_items": sum(r["totals"]["cost_unknown_items"] for r in results)},
                              "yield_on_cost": {"yoc_pct": rnd(yoc, 4), "hurdle_pct": hurdle,
                                                "spread_pct_points": rnd(None if yoc is None or hurdle is None else yoc - hurdle, 4),
                                                "spread_bps": rnd(None if yoc is None or hurdle is None else (yoc - hurdle) * 100.0, 1),
                                                "meets_hurdle": None if yoc is None or hurdle is None else yoc >= hurdle},
                              "irr": metrics["irr"], "equity_multiple": metrics["equity_multiple"],
                              "npv": {"discount_rate_pct": metrics["discount_rate_pct"], "npv_usd": metrics["npv_usd"]},
                              "peak_cumulative_outflow_usd": metrics["peak_cumulative_outflow_usd"],
                              "cash_flows": _dated(by, horizon, ap.get("base_year"))},
            "assumptions": {k: ap.get(k) for k in DEFAULT_PROFORMA},
            "formula": ["Each phase is modelled as in phase_pro_forma, then shifted to its start year and added.", *PROFORMA_FORMULA]}
