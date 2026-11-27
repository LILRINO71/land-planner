"""Infrastructure funding (cost register, who pays, funding gap by period) and the optional fiscal and economic impact.

The rule that runs through this file: an unknown stays unknown. A cost that is None is listed, counted and reported as
"not known"; it is never added to a total as zero, and every total says how many items it could not include.
"""
import re

from .finance_common import cap_int, as_dict, as_list, frac, known_total_text, npv, num, public, rnd, usd

PAYERS = ("owner", "builder", "city", "district_financing")
PAYER_LABELS = {"owner": "Owner (the landowner or sponsor)", "builder": "Builder or buyer of the parcel",
                "city": "City, agency or fee credit", "district_financing": "District financing (CFD, EIFD, bonds)",
                "not_known": "Not known who pays"}


def _norm_payer(v):
    text = re.sub(r"[^a-z]+", "_", str(v or "").lower()).strip("_")
    if text in PAYERS:
        return text
    aliases = {"sponsor": "owner", "developer": "owner", "legacy": "owner", "landowner": "owner", "builders": "builder", "buyer": "builder",
               "county": "city", "agency": "city", "public": "city", "cfd": "district_financing", "eifd": "district_financing",
               "district": "district_financing", "bond": "district_financing", "financing": "district_financing"}
    return aliases.get(text, "not_known")


def _items(items):
    rows = []
    for i, raw in enumerate(as_list(items), 1):
        raw = as_dict(raw)
        cost = num(raw.get("cost_usd"))
        due = num(raw.get("due_period"))
        rows.append({"code": raw.get("code") or f"item_{i}", "name": raw.get("name") or raw.get("code") or f"Item {i}", "phase": raw.get("phase"),
                     "cost_usd": cost, "cost_known": cost is not None, "payer": _norm_payer(raw.get("responsible")),
                     "due_period": None if due is None else int(due), "reimbursable": raw.get("reimbursable"), "note": raw.get("note")})
    return rows


def _group(rows):
    known = sum(r["cost_usd"] for r in rows if r["cost_known"])
    unknown = sum(1 for r in rows if not r["cost_known"])
    return {"item_count": len(rows), "known_usd": usd(known), "unknown_count": unknown, "complete": unknown == 0,
            "display": known_total_text(known, unknown)}


@public
def infrastructure_register(items, period_unit="month"):
    """The infrastructure cost register with totals by who pays and by phase.

    Inputs: items [{code, name, phase, cost_usd (None = not known), responsible (owner, builder, city, district_financing; anything
    else is 'not known'), due_period (a month or year number; None = timing not known), reimbursable, note}]; period_unit ('month' or 'year',
    echoed so a period number is never mistaken).
    Output: items, total, by_payer, by_phase. Every total is {known_usd, unknown_count, item_count, complete, display}: an item with no
    cost is counted as unknown and never added as $0; the display text says so ("$12,000,000 known; 2 items not known")."""
    rows = _items(items)
    by_payer = {p: _group([r for r in rows if r["payer"] == p]) for p in (*PAYERS, "not_known")}
    phases = []
    for r in rows:
        if r["phase"] not in phases:
            phases.append(r["phase"])
    return {"items": [{**r, "cost_usd": usd(r["cost_usd"]), "cost_label": "not known" if not r["cost_known"] else None,
                       "payer_label": PAYER_LABELS[r["payer"]]} for r in rows],
            "total": _group(rows), "by_payer": by_payer, "by_phase": {str(ph): _group([r for r in rows if r["phase"] == ph]) for ph in phases},
            "items_with_unknown_payer": by_payer["not_known"]["item_count"], "items_with_unknown_timing": sum(1 for r in rows if r["due_period"] is None),
            "period_unit": period_unit,
            "formula": "Total = sum of the costs that are known; the count of costs that are not known is reported next to every total."}


def _by_period(values, periods):
    """{period: amount} from a dict or from a list aligned with `periods`."""
    if isinstance(values, dict):
        return {int(num(k)): num(v, 0.0) for k, v in values.items() if num(k) is not None}
    return {p: num(v, 0.0) for p, v in zip(periods, as_list(values))}


@public
def infrastructure_funding_gap(items, periods, land_sale_proceeds=None, other_funding=None, period_unit="month"):
    """The gap, period by period, between what the owner must pay for infrastructure and the cash that arrives to pay for it.

    Inputs: items (as for infrastructure_register); periods [period numbers, ascending, each the END of a period, e.g. months 6, 12, 18];
    land_sale_proceeds {period: net proceeds} or a list aligned with periods (cash from land sales, applied to the owner's costs);
    other_funding [{period, amount_usd, source}] (bond proceeds, fee credits, builder cost-sharing); period_unit.
    An owner item falls in the first period that ends on or after its due period; one due after the last period is 'after the horizon';
    one with no due period is 'undated'. Items another party pays are listed but are not the owner's gap. An owner item with an unknown
    cost is counted in its period and the gap there is marked as a lower bound ('at least'); an item whose payer is unknown is counted
    separately and may add to the owner's burden.
    Output: rows per period {period, owner_cost_known_usd, owner_items_unknown_cost, land_sale_proceeds_usd, other_funding_usd,
    cumulative_cost_known_usd, cumulative_funding_usd, cumulative_gap_usd (positive = shortfall, negative = surplus), gap_is_lower_bound, status},
    summary with the peak gap and its period, after_horizon and undated owner items, and the unknown counts."""
    per = sorted({int(num(p)) for p in as_list(periods) if num(p) is not None})
    rows_in = _items(items)
    sales = _by_period(land_sale_proceeds, per) if land_sale_proceeds is not None else {}
    other = {}
    for f in as_list(other_funding):
        f = as_dict(f)
        if num(f.get("period")) is not None and num(f.get("amount_usd")) is not None:
            other[int(num(f["period"]))] = other.get(int(num(f["period"])), 0.0) + num(f["amount_usd"])
    owner = [r for r in rows_in if r["payer"] == "owner"]
    undated = [r for r in owner if r["due_period"] is None]
    after = [r for r in owner if r["due_period"] is not None and per and r["due_period"] > per[-1]]
    others_pay = {p: _group([r for r in rows_in if r["payer"] == p]) for p in PAYERS if p != "owner"}
    out_rows, cum_cost, cum_fund, peak, unk_so_far = [], 0.0, 0.0, None, 0
    for i, p in enumerate(per):
        lo = per[i - 1] if i else None
        here = [r for r in owner if r["due_period"] is not None and r["due_period"] <= p and (lo is None or r["due_period"] > lo)]
        cost = sum(r["cost_usd"] for r in here if r["cost_known"])
        unk = sum(1 for r in here if not r["cost_known"])
        sale, oth = sales.get(p, 0.0), other.get(p, 0.0)
        cum_cost += cost
        cum_fund += sale + oth
        unk_so_far += unk
        gap = cum_cost - cum_fund
        row = {"period": p, "owner_cost_known_usd": usd(cost), "owner_items_unknown_cost": unk, "land_sale_proceeds_usd": usd(sale),
               "other_funding_usd": usd(oth), "cumulative_cost_known_usd": usd(cum_cost), "cumulative_funding_usd": usd(cum_fund),
               "cumulative_gap_usd": usd(gap), "gap_is_lower_bound": unk_so_far > 0,
               "status": ("shortfall" if gap > 1e-6 else "covered") + (" (at least; some costs not known)" if unk_so_far and gap > 1e-6 else "")}
        out_rows.append(row)
        if peak is None or gap > peak[0]:
            peak = (gap, p)
    unknown_owner = sum(1 for r in owner if not r["cost_known"])
    unknown_payer = [r for r in rows_in if r["payer"] == "not_known"]
    return {"rows": out_rows, "period_unit": period_unit,
            "summary": {"owner_cost_known_usd": usd(sum(r["cost_usd"] for r in owner if r["cost_known"])), "owner_items_unknown_cost": unknown_owner,
                        "owner_items_after_horizon": len(after), "owner_cost_after_horizon_known_usd": usd(sum(r["cost_usd"] for r in after if r["cost_known"])),
                        "owner_items_undated": len(undated), "owner_cost_undated_known_usd": usd(sum(r["cost_usd"] for r in undated if r["cost_known"])),
                        "items_with_unknown_payer": len(unknown_payer),
                        "peak_gap_usd": usd(peak[0]) if peak else None, "peak_gap_period": peak[1] if peak else None,
                        "peak_gap_is_lower_bound": bool(unknown_owner or undated or unknown_payer),
                        "final_gap_usd": out_rows[-1]["cumulative_gap_usd"] if out_rows else None,
                        "headline": (f"Owner infrastructure cost: {known_total_text(sum(r['cost_usd'] for r in owner if r['cost_known']), unknown_owner)}")},
            "paid_by_others": others_pay,
            "formula": ["Owner cost by period = owner-paid items due in that period (known costs only; unknown costs are counted, not added as $0).",
                        "Cumulative gap = cumulative owner cost - cumulative (land sale proceeds + other funding). Positive is a shortfall.",
                        "Items another party pays are shown, not counted against the owner."]}


# ---------------------------------------------------------------- fiscal and economic impact (optional)

@public
def fiscal_impact(phases, rates):
    """Optional fiscal and economic impact by phase, from rates the caller supplies (nothing is assumed).

    Inputs: phases [{id, label, construction_cost_usd, permanent_jobs (given), building_sf_by_use {use: SF}, taxable_sales_usd_yr,
    hotel_room_revenue_usd_yr, assessed_value_usd}]; rates {construction_jobs_per_million_usd (job-years), jobs_per_1000_sf_by_use {use: jobs},
    construction_output_multiplier, operating_output_multiplier, sales_tax_rate_pct (the share of taxable sales that reaches the agency),
    property_tax_rate_pct (all agencies), city_property_tax_share_pct (the agency's share of that), hotel_tax_pct (on room revenue)}.
    Anything whose input or rate is missing is None with a reason; the totals say how many components could not be worked out.
    Output per phase: construction_job_years, permanent_jobs, construction_output_usd, annual_operating_output_usd,
    sales_tax_usd_yr, property_tax_usd_yr (all agencies), agency_property_tax_usd_yr, hotel_tax_usd_yr, annual_agency_revenue_usd and the missing list."""
    r = as_dict(rates)
    rows, tot, missing_total = [], {}, 0
    for p in as_list(phases):
        p = as_dict(p)
        miss = []

        def calc(name, fn, *needs):
            for label, val in needs:
                if num(val) is None:
                    miss.append(f"{name}: {label} not given")
                    return None
            return fn()
        cc = num(p.get("construction_cost_usd"))
        jobs_sf = None
        sf_use, jrate = as_dict(p.get("building_sf_by_use")), as_dict(r.get("jobs_per_1000_sf_by_use"))
        if sf_use and jrate:
            jobs_sf = sum(num(sf, 0.0) / 1000.0 * num(jrate.get(u), 0.0) for u, sf in sf_use.items() if num(jrate.get(u)) is not None)
        perm = num(p.get("permanent_jobs"), jobs_sf)
        if perm is None:
            miss.append("permanent jobs: give permanent_jobs, or building SF by use with jobs per 1,000 SF by use")
        con_jobs = calc("construction jobs", lambda: cc / 1e6 * num(r["construction_jobs_per_million_usd"]),
                        ("construction cost", cc), ("construction_jobs_per_million_usd", r.get("construction_jobs_per_million_usd")))
        con_out = calc("construction output", lambda: cc * num(r["construction_output_multiplier"]),
                       ("construction cost", cc), ("construction_output_multiplier", r.get("construction_output_multiplier")))
        sales, rooms = num(p.get("taxable_sales_usd_yr")), num(p.get("hotel_room_revenue_usd_yr"))
        op_base = None if sales is None and rooms is None else (sales or 0.0) + (rooms or 0.0)
        op_out = calc("operating output", lambda: op_base * num(r["operating_output_multiplier"]),
                      ("taxable sales or room revenue", op_base), ("operating_output_multiplier", r.get("operating_output_multiplier")))
        st = calc("sales tax", lambda: sales * num(r["sales_tax_rate_pct"]) / 100.0, ("taxable_sales_usd_yr", sales), ("sales_tax_rate_pct", r.get("sales_tax_rate_pct")))
        av = num(p.get("assessed_value_usd"))
        pt = calc("property tax", lambda: av * num(r["property_tax_rate_pct"]) / 100.0, ("assessed_value_usd", av), ("property_tax_rate_pct", r.get("property_tax_rate_pct")))
        apt = None
        if pt is not None:
            apt = calc("agency property tax", lambda: pt * num(r["city_property_tax_share_pct"]) / 100.0,
                       ("city_property_tax_share_pct", r.get("city_property_tax_share_pct")))
        ht = calc("hotel tax", lambda: rooms * num(r["hotel_tax_pct"]) / 100.0, ("hotel_room_revenue_usd_yr", rooms), ("hotel_tax_pct", r.get("hotel_tax_pct")))
        parts = [x for x in (st, apt, ht) if x is not None]
        row = {"id": p.get("id"), "label": p.get("label"), "construction_job_years": rnd(con_jobs, 1), "permanent_jobs": rnd(perm, 1),
               "construction_output_usd": usd(con_out), "annual_operating_output_usd": usd(op_out), "sales_tax_usd_yr": usd(st),
               "property_tax_usd_yr": usd(pt), "agency_property_tax_usd_yr": usd(apt), "hotel_tax_usd_yr": usd(ht),
               "annual_agency_revenue_usd": usd(sum(parts)) if parts else None, "not_worked_out": miss}
        rows.append(row)
        missing_total += len(miss)
        for k, v in row.items():
            if isinstance(v, (int, float)) and k not in ("id",):
                tot[k] = tot.get(k, 0.0) + v
    return {"phases": rows, "totals": {k: rnd(v, 2) for k, v in tot.items()}, "components_not_worked_out": missing_total,
            "assumptions": {k: (as_dict(v) if isinstance(v, dict) else num(v)) for k, v in r.items()},
            "formula": ["Construction job-years = construction cost / $1 million x jobs per $1 million. Output = cost (or taxable sales + room revenue) x multiplier.",
                        "Sales tax = taxable sales x rate. Property tax = assessed value x rate; the agency's part = that x its share.",
                        "Hotel tax = room revenue x hotel tax rate. A figure whose rate or input is missing is left out and listed."],
            "disclaimer": "An illustration from the rates entered, not a fiscal study and not a promise of public revenue or support."}


@public
def eifd_increment(phases, property_tax_rate_pct, participating_share_pct, years=30, assessed_growth_pct=2.0, discount_rate_pct=None):
    """Property-tax increment an EIFD-style district could capture, by phase and by year.

    Inputs: phases [{id, label, assessed_value_usd (after the phase is built), base_assessed_value_usd (before; default 0), delivery_year
    (1 = first year)}]; property_tax_rate_pct (all agencies, % of assessed value); participating_share_pct (the share of that tax the
    participating agencies put into the district); years (length, default 30); assessed_growth_pct (yearly growth of assessed value after
    delivery, default 2); discount_rate_pct (optional, for a present value).
    Output: by_phase rows {id, increment by year, total}, yearly totals and cumulative, total_increment_usd, present_value_usd (None without a
    discount rate). Increment in year t = (assessed value in t - base value) x tax rate x participating share. This is an illustration of the
    tax increment, not a bond sizing or a statement that any agency participates."""
    rate, share, g = frac(property_tax_rate_pct), frac(participating_share_pct), frac(assessed_growth_pct)
    n = cap_int(years, 30, 0, 200)
    out = {"by_phase": [], "yearly": [], "total_increment_usd": None, "present_value_usd": None, "why": None,
           "assumptions": {"property_tax_rate_pct": num(property_tax_rate_pct), "participating_share_pct": num(participating_share_pct), "years": n,
                           "assessed_growth_pct": num(assessed_growth_pct), "discount_rate_pct": num(discount_rate_pct)},
           "formula": "Increment(t) = (assessed value(t) - base value) x property tax rate x participating share; value grows from the delivery year.",
           "disclaimer": "An illustration of tax increment, not a bond sizing, and not a statement that any agency will participate."}
    if rate is None or share is None or g is None:
        out["why"] = "Give the property tax rate, the participating share and the assessed value growth."
        return out
    totals = [0.0] * (n + 1)
    for ph in as_list(phases):
        ph = as_dict(ph)
        av, base, d = num(ph.get("assessed_value_usd")), num(ph.get("base_assessed_value_usd"), 0.0), cap_int(ph.get("delivery_year"), 1, 1, 200)
        row = {"id": ph.get("id"), "label": ph.get("label"), "years": [], "total_usd": None, "why": None}
        if av is None:
            row["why"] = "No assessed value for this phase (not known)."
            out["by_phase"].append(row)
            continue
        total = 0.0
        for t in range(1, n + 1):
            inc = 0.0 if t < d else max(0.0, av * ((1.0 + g) ** (t - d)) - base) * rate * share
            totals[t] += inc
            total += inc
            row["years"].append({"year": t, "increment_usd": usd(inc)})
        row["total_usd"] = usd(total)
        out["by_phase"].append(row)
    cum = 0.0
    for t in range(1, n + 1):
        cum += totals[t]
        out["yearly"].append({"year": t, "increment_usd": usd(totals[t]), "cumulative_usd": usd(cum)})
    out["total_increment_usd"] = usd(cum)
    if num(discount_rate_pct) is not None:
        out["present_value_usd"] = usd(npv(frac(discount_rate_pct), totals))
    return out
