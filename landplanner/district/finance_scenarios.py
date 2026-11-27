"""Scenario runner, one-at-a-time sensitivity (tornado rows) and the break-even solver.

All three work on the same `inputs` dict:
    {"library": {...land use library...}, "parcels": [...optional...], "phases": [...optional...], "assumptions": {...pro forma assumptions...}}
and re-run the same engine (residual land value, phase pro forma) with the inputs adjusted, so a number on a side-by-side
table and the number on its own screen can never disagree.
"""
import copy

from .finance_common import as_dict, as_list, num, public, rnd
from .finance_land import DEFAULT_SCENARIOS, residual_land_value_by_parcel
from .finance_proforma import full_buildout_pro_forma, phase_pro_forma
from .finance_uses import SALE_TYPES, adjust_library, use_program

DEFAULT_TORNADO_VARIABLES = (
    {"id": "density", "label": "Density (units per acre, floor area ratio)", "low": {"density_pct": -10.0}, "high": {"density_pct": 10.0},
     "unit": "% of density"},
    {"id": "rents", "label": "Rents, prices and ADR", "low": {"revenue_pct": -10.0}, "high": {"revenue_pct": 10.0}, "unit": "% of revenue"},
    {"id": "costs", "label": "Development costs", "low": {"cost_pct": -10.0}, "high": {"cost_pct": 10.0}, "unit": "% of cost"},
    {"id": "required_return", "label": "Required return (developer profit)", "low": {"required_return_delta_pct": -2.0},
     "high": {"required_return_delta_pct": 2.0}, "unit": "percentage points"},
    {"id": "cap_rate", "label": "Cap rate", "low": {"cap_rate_delta_pct": -0.5}, "high": {"cap_rate_delta_pct": 0.5}, "unit": "percentage points"},
)


def _scale_line(line, factor):
    line = dict(line)
    for k in ("net_ac", "units", "building_sf"):
        if num(line.get(k)) is not None:
            line[k] = num(line[k]) * factor
    return line


def _units_in(inputs, use_ids):
    lib = as_dict(inputs.get("library"))
    total = 0.0
    for ph in as_list(inputs.get("phases")):
        for ln in as_list(as_dict(ph).get("lines")):
            ln = as_dict(ln)
            if use_ids is not None and ln.get("use") not in use_ids:
                continue
            u = use_program(as_dict(lib.get(ln.get("use"))), net_ac=ln.get("net_ac"), units=ln.get("units"), building_sf=ln.get("building_sf"))["units"]
            total += u or 0.0
    return total


def apply_scenario(inputs, adjustment):
    """A copy of the inputs with a scenario applied: the adjustment keys of finance_uses.adjust_use, plus
    target_units {use_ids [..] (default: every use), total N} (scales the program lines so those uses hold N units in all)
    and quantity_factor_by_use {use_id: multiplier}."""
    adj = as_dict(adjustment)
    out = copy.deepcopy(as_dict(inputs))
    out["library"] = adjust_library(out.get("library"), adj)
    factors = dict(as_dict(adj.get("quantity_factor_by_use")))
    tu = as_dict(adj.get("target_units"))
    if num(tu.get("total")) is not None:
        ids = set(tu["use_ids"]) if tu.get("use_ids") else None
        current = _units_in(out, ids)
        if current > 0:
            for ph in as_list(out.get("phases")):
                for i, ln in enumerate(as_list(as_dict(ph).get("lines"))):
                    if ids is None or as_dict(ln).get("use") in ids:
                        ph["lines"][i] = _scale_line(ln, num(tu["total"]) / current)
    for ph in as_list(out.get("phases")):
        for i, ln in enumerate(as_list(as_dict(ph).get("lines"))):
            f = num(factors.get(as_dict(ln).get("use")))
            if f is not None and f != 1.0:
                ph["lines"][i] = _scale_line(ph["lines"][i], f)
    return out


@public
def evaluate_program(inputs):
    """The headline numbers of one set of inputs, flat: rlv_total_usd (base residual of the parcels), units_total, development_cost_usd,
    total_cost_incl_land_usd, stabilized_noi_usd_yr, implied_value_usd, net_sales_revenue_usd, yoc_pct, irr_pct, equity_multiple, npv_usd.
    A number that cannot be worked out is None. This is what run_scenarios and tornado compare."""
    inp = as_dict(inputs)
    lib = as_dict(inp.get("library"))
    m = {"rlv_total_usd": None, "units_total": None, "development_cost_usd": None, "total_cost_incl_land_usd": None,
         "stabilized_noi_usd_yr": None, "implied_value_usd": None, "net_sales_revenue_usd": None, "yoc_pct": None, "irr_pct": None,
         "equity_multiple": None, "npv_usd": None}
    if inp.get("parcels"):
        r = residual_land_value_by_parcel(inp["parcels"], lib, {"base": {}})
        m["rlv_total_usd"] = r["totals_usd"].get("base") if r["parcels_not_priced"] < len(r["parcels"]) else None
    if inp.get("phases"):
        fb = full_buildout_pro_forma(inp["phases"], lib, inp.get("assumptions"))["full_buildout"]
        t = fb["totals"]
        m.update({"units_total": rnd(_units_in(inp, None), 2), "development_cost_usd": t["development_cost_usd"],
                  "total_cost_incl_land_usd": t["total_cost_incl_land_usd"], "stabilized_noi_usd_yr": t["stabilized_noi_usd_yr"],
                  "implied_value_usd": t["implied_value_usd"], "net_sales_revenue_usd": t["net_sales_revenue_usd"],
                  "yoc_pct": fb["yield_on_cost"]["yoc_pct"], "irr_pct": fb["irr"]["irr_pct"], "equity_multiple": fb["equity_multiple"],
                  "npv_usd": fb["npv"]["npv_usd"]})
    return m


@public
def unit_count_scenarios(totals=(1500, 2000, 2500), use_ids=None):
    """Named scenarios that hold the program to a total unit count, e.g. 1,500 / 2,000 / 2,500 units: {"1500_units": {target_units...}}.
    Inputs: totals (unit counts), use_ids (the uses that count as units; default every use with units). Feed the result to run_scenarios."""
    return {f"{int(t)}_units": {"target_units": {"total": t, "use_ids": list(use_ids) if use_ids else None}} for t in totals}


@public
def run_scenarios(inputs, scenarios=None, base_name=None, evaluate=None):
    """The same inputs under several scenarios, side by side.

    Inputs: inputs {library, parcels, phases, assumptions}; scenarios {name: adjustment} (default low / base / high; see
    adjust_use for the adjustment keys, unit_count_scenarios for 1,500 / 2,000 / 2,500 units); base_name (the scenario the
    differences are measured from, default 'base' if present, else the first); evaluate (a function inputs -> metrics dict;
    default evaluate_program).
    Output: scenarios [{name, adjustments, metrics}], table {metric: {scenario: value}}, vs_base {scenario: {metric: difference}}."""
    scs = scenarios if isinstance(scenarios, dict) and scenarios else DEFAULT_SCENARIOS
    fn = evaluate or evaluate_program
    rows = []
    for name, adj in scs.items():
        rows.append({"name": name, "adjustments": as_dict(adj), "metrics": fn(apply_scenario(inputs, adj))})
    base = base_name if base_name in scs else ("base" if "base" in scs else (rows[0]["name"] if rows else None))
    keys = []
    for r in rows:
        keys += [k for k in r["metrics"] if k not in keys]
    table = {k: {r["name"]: r["metrics"].get(k) for r in rows} for k in keys}
    base_m = next((r["metrics"] for r in rows if r["name"] == base), {})
    vs = {r["name"]: {k: (rnd(r["metrics"][k] - base_m[k], 4) if num(r["metrics"].get(k)) is not None and num(base_m.get(k)) is not None else None)
                      for k in keys} for r in rows}
    return {"scenarios": rows, "table": table, "vs_base": vs, "base_name": base,
            "formula": "Each scenario adjusts the library (and program), then the same residual land value and pro forma engine is run."}


@public
def sensitivity_tornado(inputs, variables=None, metric=None, evaluate=None):
    """One-at-a-time sensitivity: each variable is moved to its low and its high setting alone, and the headline metric is re-run.

    Inputs: inputs; variables [{id, label, low: adjustment, high: adjustment, unit}] (default: density +/-10%, rents +/-10%, costs
    +/-10%, required return +/-2 points, cap rate +/-0.5 points); metric (a key of evaluate_program's answer; default
    rlv_total_usd if there are parcels, else irr_pct, else yoc_pct); evaluate (default evaluate_program).
    Output: base_value, rows sorted by swing, largest first [{rank, id, label, low_setting, high_setting, metric_at_low, metric_at_high,
    change_at_low, change_at_high, swing}], ready to draw as a tornado chart."""
    fn = evaluate or evaluate_program
    base_metrics = fn(copy.deepcopy(as_dict(inputs)))
    key = metric
    if key is None:
        key = next((k for k in ("rlv_total_usd", "irr_pct", "yoc_pct") if num(base_metrics.get(k)) is not None), None)
    base = num(base_metrics.get(key)) if key else None
    rows = []
    for v in (variables if variables else DEFAULT_TORNADO_VARIABLES):
        v = as_dict(v)
        lo = fn(apply_scenario(inputs, v.get("low"))).get(key) if key else None
        hi = fn(apply_scenario(inputs, v.get("high"))).get(key) if key else None
        lo, hi = num(lo), num(hi)
        d_lo = None if lo is None or base is None else lo - base
        d_hi = None if hi is None or base is None else hi - base
        swing = abs(hi - lo) if lo is not None and hi is not None else None
        rows.append({"id": v.get("id"), "label": v.get("label") or v.get("id"), "unit": v.get("unit"), "low_setting": as_dict(v.get("low")),
                     "high_setting": as_dict(v.get("high")), "metric_at_low": rnd(lo, 4), "metric_at_high": rnd(hi, 4),
                     "change_at_low": rnd(d_lo, 4), "change_at_high": rnd(d_hi, 4), "swing": rnd(swing, 4)})
    rows.sort(key=lambda r: (r["swing"] is None, -(r["swing"] or 0.0)))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return {"metric": key, "base_value": rnd(base, 4), "rows": rows,
            "why": None if key and base is not None else "The inputs give no number for the metric (add parcels or phases).",
            "formula": "Each variable is moved alone to its low and high setting; swing = |metric at high - metric at low|; rows are ranked by swing."}


# ---------------------------------------------------------------- break-even

BREAKEVEN_VARIABLES = {
    "apartment_rent": {"types": ("rent_per_unit_mo",), "keys": ("rent_per_unit_mo",), "unit": "$ per unit per month", "metric": "yoc"},
    "retail_nnn_rent": {"types": ("rent_per_sf_yr",), "keys": ("rent_per_sf_yr", "rent_per_sf_mo"), "unit": "$ per SF per year (NNN)", "metric": "yoc"},
    "hotel_adr": {"types": ("room_revenue",), "keys": ("adr",), "unit": "$ per room night", "metric": "yoc"},
    "for_sale_price": {"types": SALE_TYPES, "keys": ("price_per_unit", "price_per_sf"), "unit": "$ per unit (or per SF)", "metric": "irr"},
    "exit_cap_rate": {"types": None, "keys": (), "unit": "percent", "metric": "irr"},
}


def _metric(phase_or_phases, lib, ap, metric):
    """The pro forma metric at one setting (None when it cannot be worked out)."""
    if isinstance(phase_or_phases, list):
        fb = full_buildout_pro_forma(phase_or_phases, lib, ap)["full_buildout"]
        return fb["yield_on_cost"]["yoc_pct"] if metric == "yoc" else fb["irr"]["irr_pct"]
    r = phase_pro_forma(phase_or_phases, lib, ap)
    return r["yield_on_cost"]["yoc_pct"] if metric == "yoc" else r["irr"]["irr_pct"]


@public
def break_even(phase, library, assumptions, variable, metric=None, target_pct=None, lower=None, upper=None):
    """The value of one driver at which the phase just meets its hurdle.

    Inputs: phase (a phase dict, or a list of phases for the whole buildout); library; assumptions (as for phase_pro_forma, with
    hurdle_yoc_pct and/or hurdle_irr_pct); variable: apartment_rent, retail_nnn_rent, hotel_adr, for_sale_price or exit_cap_rate;
    metric 'yoc' (yield on cost) or 'irr' (default: yoc for rents and ADR, irr for sale price and exit cap);
    target_pct (the hurdle to meet; default hurdle_yoc_pct or hurdle_irr_pct from the assumptions); lower and upper (search range,
    as multiples of today's value, default 0.2 to 4; for the exit cap, percent, default 1 to 25).
    Output: breakeven_value (when one use sets the driver) or by_use [{use, current, breakeven}], breakeven_factor (multiple of today's
    value), the metric today and at break-even, whether the hurdle is already met, converged, why."""
    spec = BREAKEVEN_VARIABLES.get(variable) if isinstance(variable, str) else None
    out = {"variable": variable, "unit": None, "metric": None, "target_pct": None, "breakeven_value": None, "breakeven_factor": None,
           "by_use": [], "metric_today_pct": None, "metric_at_breakeven_pct": None, "already_met_today": None, "converged": False, "why": None}
    if spec is None:
        out["why"] = f"The variable must be one of {', '.join(BREAKEVEN_VARIABLES)}."
        return out
    ap = as_dict(assumptions)
    m = metric or spec["metric"]
    out["unit"], out["metric"] = spec["unit"], m
    if variable == "exit_cap_rate" and m == "yoc":
        out["why"] = "The exit cap rate does not change yield on cost; use the irr metric."
        return out
    tgt = num(target_pct, num(ap.get("hurdle_yoc_pct" if m == "yoc" else "hurdle_irr_pct")))
    if tgt is None:
        out["why"] = f"Give target_pct or set {'hurdle_yoc_pct' if m == 'yoc' else 'hurdle_irr_pct'} in the assumptions."
        return out
    out["target_pct"] = tgt
    lib = as_dict(library)
    phases = phase if isinstance(phase, list) else [phase]
    used = []
    for ph in phases:
        for ln in as_list(as_dict(ph).get("lines")):
            uid = as_dict(ln).get("use")
            rv = as_dict(as_dict(lib.get(uid)).get("revenue"))
            if uid in lib and uid not in used and (spec["types"] is None and num(as_dict(lib[uid]).get("cap_rate_pct")) is not None
                                                   or spec["types"] is not None and rv.get("type") in spec["types"]):
                used.append(uid)
    if not used:
        out["why"] = "No use in the phase has that kind of revenue (or an exit cap rate)."
        return out
    arg = phases if isinstance(phase, list) else phase

    def adj_for(x):
        if variable == "exit_cap_rate":
            return {"cap_rate_set_pct": x}
        return {"revenue_factor_by_type": {t: x for t in spec["types"]}}

    def value_at(x):
        return _metric(arg, adjust_library(lib, adj_for(x)), ap, m)

    today = _metric(arg, lib, ap, m)
    out["metric_today_pct"] = rnd(today, 4)
    out["already_met_today"] = None if today is None else today >= tgt
    if variable == "exit_cap_rate":
        lo, hi = num(lower, 1.0), num(upper, 25.0)
        grid = [lo + (hi - lo) * i / 60.0 for i in range(61)]
        meets = lambda x: (lambda v: v is not None and v >= tgt)(value_at(x))            # a lower cap meets the hurdle
        idx = next((i for i in range(len(grid) - 1, -1, -1) if meets(grid[i])), None)    # the highest cap that still meets it
        if idx is None:
            out["why"] = f"The hurdle is not met at any exit cap rate from {lo:g}% to {hi:g}%."
            return out
        if idx == len(grid) - 1:
            out["why"] = f"The hurdle is still met at {hi:g}%: raise the upper bound."
            return out
        a, b = grid[idx], grid[idx + 1]
    else:
        lo, hi = num(lower, 0.2), num(upper, 4.0)
        grid = [lo * (hi / lo) ** (i / 60.0) for i in range(61)] if lo > 0 and hi > lo else []
        if not grid:
            out["why"] = "The search range must have 0 < lower < upper."
            return out
        meets = lambda x: (lambda v: v is not None and v >= tgt)(value_at(x))
        idx = next((i for i in range(len(grid)) if meets(grid[i])), None)                # the lowest multiple that meets it
        if idx is None:
            out["why"] = f"The hurdle is not met even at {hi:g} times today's value."
            return out
        if idx == 0:
            out["why"] = f"The hurdle is already met at {lo:g} times today's value: lower the lower bound."
            return out
        a, b = grid[idx - 1], grid[idx]
    for _ in range(50):                       # bisect between the last miss and the first hit
        mid = (a + b) / 2.0
        hit = meets(mid)
        if variable == "exit_cap_rate":       # a is the highest cap that meets, b the first that does not
            a, b = (mid, b) if hit else (a, mid)
        else:                                 # a is the last multiple that misses, b the first that meets
            a, b = (a, mid) if hit else (mid, b)
    x = a if variable == "exit_cap_rate" else b
    out["converged"] = True
    out["metric_at_breakeven_pct"] = rnd(value_at(x), 4)
    if variable == "exit_cap_rate":
        out["breakeven_value"], out["breakeven_factor"] = rnd(x, 4), None
        out["by_use"] = [{"use": u, "current": as_dict(lib[u]).get("exit_cap_pct", as_dict(lib[u]).get("cap_rate_pct")), "breakeven": rnd(x, 4)}
                         for u in used]
    else:
        out["breakeven_factor"] = rnd(x, 6)
        for u in used:
            rv = as_dict(as_dict(lib[u]).get("revenue"))
            key = next((k for k in spec["keys"] if num(rv.get(k)) is not None), None)
            cur = num(rv.get(key))
            out["by_use"].append({"use": u, "driver": key, "current": cur, "breakeven": rnd(cur * x, 4) if cur is not None else None})
        if len(out["by_use"]) == 1:
            out["breakeven_value"] = out["by_use"][0]["breakeven"]
    out["formula"] = ["Re-run the pro forma with the driver scaled (or the exit cap set) and find, by search and bisection, the value at which "
                      f"{'yield on cost' if m == 'yoc' else 'the IRR'} equals the hurdle ({tgt:g}%).",
                      "Break-even factor = break-even value / today's value (all uses of the same kind move together)."]
    return out
