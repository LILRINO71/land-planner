"""Residual land value, the four pricing tiers and the gross-to-net waterfall.

Residual land value (RLV) here is an economic calculation under a stated use: what a buyer could pay for the land and
still earn the required return, given what the finished product is worth and what it costs to build. It is not an appraisal.
"""
from .finance_common import (DISCLAIMER, SF_PER_AC, as_dict, as_list, div, frac, known_total_text, mul, num, pct4, pct_of, public, rnd,
                             total_known, usd)
from .finance_uses import adjust_use, line_item_costs, use_economics, use_program

DEFAULT_SCENARIOS = {
    "low": {"revenue_pct": -10.0, "cost_pct": 10.0, "cap_rate_delta_pct": 0.5, "required_return_delta_pct": 2.0},
    "base": {},
    "high": {"revenue_pct": 10.0, "cost_pct": -5.0, "cap_rate_delta_pct": -0.5, "required_return_delta_pct": -2.0},
}

DEFAULT_TRANSACTION_RATES = {"brokerage_pct": 3.5, "closing_cost_pct": 0.75, "transfer_tax_pct": 0.11, "recording_fee_usd": 0.0}

RLV_FORMULA = ["Value on completion = net sale revenue (sale uses) or stabilised NOI / cap rate less selling costs (income uses).",
               "Development cost = the sum of the use's cost line items, land excluded.",
               "Residual land value = value on completion / (1 + required return) - development cost.",
               "Per net acre = residual / net acres; per net SF = per net acre / 43,560; per gross acre = residual / gross acres."]


# ---------------------------------------------------------------- residual land value

def rlv_calc(use_def, net_ac):
    """One use on `net_ac` net acres: every step of the residual, or None and `why`."""
    ud = as_dict(use_def)
    out = {"net_ac": num(net_ac), "units": None, "building_sf": None, "value_on_completion_usd": None, "noi_usd_yr": None,
           "cap_rate_pct": num(ud.get("cap_rate_pct")), "development_cost_usd": None, "cost_unknown_items": 0, "cost_is_partial": False,
           "required_return_pct": num(ud.get("required_return_pct")), "required_profit_usd": None, "rlv_usd": None,
           "rlv_per_net_ac_usd": None, "rlv_per_net_sf_usd": None, "yield_on_cost_pct": None, "feasible_now": None, "why": None}
    if out["net_ac"] is None or out["net_ac"] <= 0:
        out["why"] = "Net acres must be above zero."
        return out
    prog = use_program(ud, net_ac=out["net_ac"])
    out["units"], out["building_sf"] = prog["units"], prog["building_sf"]
    econ = use_economics(ud, prog)
    costs = line_item_costs(ud.get("cost_line_items"), net_ac=out["net_ac"], building_sf=prog["building_sf"], units=prog["units"])
    out["cost_unknown_items"], out["cost_is_partial"] = costs["unknown_items"], costs["is_partial"]
    if costs["item_count"] == 0 or costs["item_count"] == costs["unknown_items"]:
        out["why"] = "No development cost is known for this use."
        return out
    out["development_cost_usd"] = costs["total_usd"]
    ret = frac(ud.get("required_return_pct"))
    if ret is None or ret <= -1:
        out["why"] = "The use has no required return."
        return out
    sell = frac(ud.get("sales_cost_pct")) or 0.0
    if econ["is_sale"]:
        value = econ["net_sales_usd"]
    else:
        noi = econ["noi_usd_yr"]
        out["noi_usd_yr"] = noi
        cap = frac(ud.get("cap_rate_pct"))
        value = None if noi is None or not cap or cap <= 0 else noi / cap * (1.0 - sell)
        if value is None and econ["why"] is None:
            econ["why"] = "An income use needs a cap rate above zero."
    if value is None:
        out["why"] = econ["why"] or "Value on completion could not be worked out."
        return out
    out["value_on_completion_usd"] = value
    rlv = value / (1.0 + ret) - costs["total_usd"]
    out["rlv_usd"] = rlv
    out["required_profit_usd"] = value - costs["total_usd"] - rlv
    out["rlv_per_net_ac_usd"] = rlv / out["net_ac"]
    out["rlv_per_net_sf_usd"] = rlv / out["net_ac"] / SF_PER_AC
    out["yield_on_cost_pct"] = None if econ["is_sale"] else (div(out["noi_usd_yr"], costs["total_usd"]) or 0.0) * 100.0 \
        if div(out["noi_usd_yr"], costs["total_usd"]) is not None else None
    out["feasible_now"] = rlv > 0
    return out


def _round_rlv(r):
    keys = ("value_on_completion_usd", "noi_usd_yr", "development_cost_usd", "required_profit_usd", "rlv_usd", "rlv_per_net_ac_usd",
            "rlv_per_net_sf_usd")
    out = dict(r)
    for k in keys:
        out[k] = usd(r[k])
    out["rlv_per_net_sf_usd"] = rnd(r["rlv_per_net_sf_usd"], 4)
    out["units"], out["building_sf"] = rnd(r["units"], 2), rnd(r["building_sf"], 0)
    out["yield_on_cost_pct"] = pct4(r["yield_on_cost_pct"])
    return out


def _scenario_defs(scenarios):
    sc = scenarios if isinstance(scenarios, dict) and scenarios else DEFAULT_SCENARIOS
    return {name: as_dict(adj) for name, adj in sc.items()}


@public
def residual_land_value_by_use(library, net_to_gross_pct=100.0, scenarios=None, net_ac=1.0):
    """Residual land value of every use in a land use library, for one net acre, under low / base / high scenarios.

    Inputs: library {use_id: use definition}; net_to_gross_pct (% of gross acres that are net acres; converts to per gross acre);
    scenarios {name: adjustment} (default low / base / high, see DEFAULT_SCENARIOS); net_ac (acres to price, default 1).
    Output: uses [{id, label, scenarios: {name: {rlv_usd, rlv_per_net_ac_usd, rlv_per_net_sf_usd, rlv_per_gross_ac_usd, ...}}}],
    a ranking by base residual per net acre, the assumptions echoed and the formula."""
    scs = _scenario_defs(scenarios)
    ntg = num(net_to_gross_pct)
    rows = []
    for use_id, ud in as_dict(library).items():
        per = {}
        for name, adj in scs.items():
            r = _round_rlv(rlv_calc(adjust_use(ud, adj), net_ac))
            r["rlv_per_gross_ac_usd"] = usd(mul(r["rlv_per_net_ac_usd"], ntg, 0.01)) if ntg else None
            per[name] = r
        rows.append({"id": use_id, "label": as_dict(ud).get("label") or use_id, "scenarios": per})
    ref = "base" if "base" in scs else next(iter(scs), None)
    ranked = sorted((r for r in rows if r["scenarios"].get(ref, {}).get("rlv_per_net_ac_usd") is not None),
                    key=lambda r: -r["scenarios"][ref]["rlv_per_net_ac_usd"])
    return {"uses": rows, "ranking": [r["id"] for r in ranked], "ranked_by": f"{ref} residual per net acre",
            "assumptions": {"net_to_gross_pct": ntg, "net_ac": num(net_ac), "scenarios": scs}, "formula": RLV_FORMULA,
            "disclaimer": DISCLAIMER}


def _parcel_acres(parcel):
    p = as_dict(parcel)
    gross, net = num(p.get("gross_ac")), num(p.get("net_ac"))
    ntg = num(p.get("net_to_gross_pct"))
    if net is None and gross is not None and ntg is not None:
        net = gross * ntg / 100.0
    if gross is None and net is not None and ntg:
        gross = net / (ntg / 100.0)
    return gross, net


@public
def residual_land_value_by_parcel(parcels, library, scenarios=None):
    """Residual land value for each parcel under each of its candidate uses and each scenario.

    Inputs: parcels [{id, name, gross_ac, net_ac (or net_to_gross_pct), candidate_uses [use ids] (default every use), use (the use
    assigned to the parcel, optional)}]; library; scenarios. Output per parcel: for every candidate use and scenario the total
    residual and the figure per gross acre, per net acre and per net SF; the best use (highest base residual); the assigned use.
    Totals add up the assigned use (or the best use if none is assigned), and say how many parcels could not be priced."""
    scs = _scenario_defs(scenarios)
    lib = as_dict(library)
    ref = "base" if "base" in scs else next(iter(scs), None)
    out_parcels, totals, unpriced = [], {name: 0.0 for name in scs}, 0
    for p in as_list(parcels):
        p = as_dict(p)
        gross, net = _parcel_acres(p)
        cands = [u for u in (p.get("candidate_uses") or list(lib)) if u in lib]
        uses = {}
        for use_id in cands:
            per = {}
            for name, adj in scs.items():
                r = rlv_calc(adjust_use(lib[use_id], adj), net)
                rr = _round_rlv(r)
                rr["rlv_per_gross_ac_usd"] = usd(div(r["rlv_usd"], gross))
                per[name] = rr
            uses[use_id] = per
        priced = {u: v[ref] for u, v in uses.items() if v.get(ref, {}).get("rlv_usd") is not None}
        best = max(priced, key=lambda u: priced[u]["rlv_usd"]) if priced else None
        chosen = p.get("use") if p.get("use") in priced else best
        row = {"id": p.get("id"), "name": p.get("name"), "gross_ac": gross, "net_ac": net, "uses": uses, "best_use": best,
               "assigned_use": p.get("use"), "totalled_use": chosen,
               "why": None if chosen else "No candidate use could be priced (check the acres and the library)."}
        if chosen:
            for name in scs:
                v = uses[chosen].get(name, {}).get("rlv_usd")
                totals[name] += v or 0.0
        else:
            unpriced += 1
        out_parcels.append(row)
    return {"parcels": out_parcels, "totals_usd": {k: usd(v) for k, v in totals.items()}, "parcels_not_priced": unpriced,
            "assumptions": {"scenarios": scs, "total_basis": "the assigned use, else the best use by base residual"},
            "formula": RLV_FORMULA, "disclaimer": DISCLAIMER}


# ---------------------------------------------------------------- four pricing tiers

TIER_LABELS = {"economic_cost_floor": "Economic cost floor (what the owner has in it)",
               "minimum_recommended": "Minimum recommended disposition price (cost + sponsor hurdle + strategic premium)",
               "target_market": "Target market price (economic target, not a value opinion)",
               "upside_stretch": "Upside / stretch price"}


def _tier_row(label, total, gross, net, source):
    return {"label": label, "price_usd": usd(total), "per_gross_ac_usd": usd(div(total, gross)), "per_net_ac_usd": usd(div(total, net)),
            "per_net_sf_usd": rnd(div(total, mul(net, SF_PER_AC)), 4), "source": source}


@public
def pricing_tiers(parcel, rlv_base_usd=None, rlv_high_usd=None, sponsor_hurdle_pct=20.0, strategic_premium_pct=0.0,
                  strategic_premium_usd=None, score_premium=None, target_pct_of_rlv=100.0, upside_pct=15.0,
                  target_price_usd=None, upside_price_usd=None):
    """The four prices for one parcel: cost floor, minimum recommended, target, upside.

    Inputs: parcel {id, gross_ac, net_ac, cost_items {name: dollars or None} or cost_basis_usd, strategic_score 0-100};
    rlv_base_usd and rlv_high_usd (parcel residual, from residual_land_value_by_parcel); sponsor_hurdle_pct (default 20);
    strategic_premium_pct (% of cost added) or strategic_premium_usd (a flat amount, wins over the percent);
    score_premium {threshold, pct_per_point} (adds pct_per_point % of cost for each strategic score point above the threshold);
    target_pct_of_rlv (default 100) and upside_pct (default 15, used only when no upside price or high residual is given);
    target_price_usd / upside_price_usd (explicit prices that override the residual).
    Output: four tiers, each in total dollars, per gross acre, per net acre and per net SF, with where it came from; the
    cost items that are unknown (the floor is then a lower bound); whether the tiers are in order; the gaps between them."""
    p = as_dict(parcel)
    gross, net = _parcel_acres(p)
    items = as_dict(p.get("cost_items"))
    if items:
        known, unknown, _ = total_known(items.values())
        floor, floor_note = known, None
    elif num(p.get("cost_basis_usd")) is not None:
        floor, unknown, floor_note = num(p["cost_basis_usd"]), 0, None
    else:
        floor, unknown, floor_note = None, 0, "The parcel has no cost basis."
    hurdle = frac(sponsor_hurdle_pct)
    premium = None
    if floor is not None:
        if num(strategic_premium_usd) is not None:
            premium = num(strategic_premium_usd)
        else:
            pct = num(strategic_premium_pct, 0.0)
            sp = as_dict(score_premium)
            score = num(p.get("strategic_score"))
            if score is not None and num(sp.get("pct_per_point")) is not None:
                pct += max(0.0, score - num(sp.get("threshold"), 0.0)) * num(sp["pct_per_point"])
            premium = floor * pct / 100.0
    minimum = None if floor is None or hurdle is None else floor * (1.0 + hurdle) + (premium or 0.0)
    if num(target_price_usd) is not None:
        target, t_src = num(target_price_usd), "an explicit target price"
    elif num(rlv_base_usd) is not None:
        target, t_src = num(rlv_base_usd) * num(target_pct_of_rlv, 100.0) / 100.0, f"{num(target_pct_of_rlv, 100.0):g}% of the base residual"
    else:
        target, t_src = None, "not available: give a base residual or a target price"
    if num(upside_price_usd) is not None:
        upside, u_src = num(upside_price_usd), "an explicit upside price"
    elif num(rlv_high_usd) is not None:
        upside, u_src = num(rlv_high_usd), "the high-scenario residual"
    elif target is not None:
        upside, u_src = target * (1.0 + num(upside_pct, 0.0) / 100.0), f"target plus {num(upside_pct, 0.0):g}%"
    else:
        upside, u_src = None, "not available: no target to build on"
    tiers = {"economic_cost_floor": _tier_row(TIER_LABELS["economic_cost_floor"], floor, gross, net,
                                              "sum of the known cost items" if items else "cost basis"),
             "minimum_recommended": _tier_row(TIER_LABELS["minimum_recommended"], minimum, gross, net,
                                              "cost floor x (1 + hurdle) + strategic premium"),
             "target_market": _tier_row(TIER_LABELS["target_market"], target, gross, net, t_src),
             "upside_stretch": _tier_row(TIER_LABELS["upside_stretch"], upside, gross, net, u_src)}
    seq = [floor, minimum, target, upside]
    present = [v for v in seq if v is not None]
    ordered = all(a <= b for a, b in zip(present, present[1:]))
    notes = []
    if floor_note:
        notes.append(floor_note)
    if unknown:
        notes.append(f"{unknown} cost item{'s are' if unknown != 1 else ' is'} not known: the cost floor is a lower bound.")
    if minimum is not None and target is not None and target < minimum:
        notes.append("The target price is below the minimum recommended price: at this target the sponsor hurdle is not met.")
    if floor is not None and target is not None and target < floor:
        notes.append("The target price is below the economic cost floor: selling at the target loses money against cost.")
    return {"parcel_id": p.get("id"), "tiers": tiers, "tiers_in_order": ordered, "cost_items_unknown": unknown,
            "cost_floor_is_lower_bound": bool(unknown),
            "strategic_premium_usd": usd(premium),
            "headroom_target_over_minimum_usd": usd(None if minimum is None or target is None else target - minimum),
            "notes": notes,
            "assumptions": {"sponsor_hurdle_pct": num(sponsor_hurdle_pct), "strategic_premium_pct": num(strategic_premium_pct),
                            "strategic_premium_usd": num(strategic_premium_usd), "target_pct_of_rlv": num(target_pct_of_rlv),
                            "upside_pct": num(upside_pct), "strategic_score": num(p.get("strategic_score"))},
            "formula": ["Cost floor = sum of the parcel's cost items (land basis, entitlement, carry, stubs).",
                        "Minimum recommended = cost floor x (1 + sponsor hurdle) + strategic premium.",
                        "Target = base residual x target % (or an explicit target price).",
                        "Upside = high residual (or an explicit price, or target x (1 + upside %))."],
            "disclaimer": DISCLAIMER}


# ---------------------------------------------------------------- gross-to-net waterfall

@public
def gross_to_net_waterfall(gross_price_usd, net_ac=None, seller_note_usd=0.0, debt_release_usd=0.0, brokerage_pct=3.5,
                           closing_cost_pct=0.75, transfer_tax_pct=0.11, recording_fee_usd=0.0, stub_per_net_ac_usd=0.0,
                           infrastructure_stubs=None, other_deductions=None):
    """What the seller keeps from one sale, every deduction listed.

    Inputs: gross_price_usd; net_ac (needed only for a per-acre stub or the per-acre result); seller_note_usd (seller note paid
    off from proceeds); debt_release_usd (loan paid off or release price for the parcel); brokerage_pct (default 3.5, of
    the price); closing_cost_pct (default 0.75); transfer_tax_pct (default 0.11, the county tax as a percent of the price)
    and recording_fee_usd (a flat amount: enter the county's fee, it defaults to 0); stub_per_net_ac_usd (parcel
    infrastructure stub, $ per net acre) and/or infrastructure_stubs [{name, amount_usd}] where an amount of None means the
    stub cost is not known; other_deductions [{name, amount_usd}].
    Output: deductions (id, label, basis, amount_usd, pct_of_gross), total_deductions_usd, net_cash_proceeds_usd, per net acre,
    the transaction cost % and the count of unknown deductions (net proceeds are then an upper bound, never a silent zero)."""
    gross = num(gross_price_usd)
    rows, unknown = [], 0

    def pct_row(rid, label, pct):
        amt = None if gross is None else gross * num(pct, 0.0) / 100.0
        rows.append({"id": rid, "label": label, "basis": f"{num(pct, 0.0):g}% of price", "amount_usd": usd(amt),
                     "pct_of_gross": rnd(num(pct, 0.0), 4)})

    def flat_row(rid, label, amount, basis="amount"):
        nonlocal unknown
        v = num(amount)
        if v is None:
            unknown += 1
        rows.append({"id": rid, "label": label, "basis": basis, "amount_usd": usd(v), "pct_of_gross": rnd(pct_of(v, gross), 4)})

    if num(seller_note_usd, 0.0):
        flat_row("seller_note", "Seller note paid off at closing", seller_note_usd)
    if num(debt_release_usd, 0.0):
        flat_row("debt_release", "Debt release / loan payoff", debt_release_usd)
    pct_row("brokerage", "Brokerage commission", brokerage_pct)
    pct_row("closing_costs", "Closing costs (escrow, title, legal)", closing_cost_pct)
    pct_row("transfer_tax", "County transfer tax", transfer_tax_pct)
    if num(recording_fee_usd, 0.0):
        flat_row("recording_fee", "Recording fee", recording_fee_usd)
    ac = num(net_ac)
    if num(stub_per_net_ac_usd, 0.0):
        flat_row("parcel_stub", "Parcel infrastructure stub", mul(stub_per_net_ac_usd, ac), f"${num(stub_per_net_ac_usd):,.0f} per net acre x net acres")
    for s in as_list(infrastructure_stubs):
        s = as_dict(s)
        flat_row("stub_" + str(s.get("name", "item")).lower().replace(" ", "_"), s.get("name", "Infrastructure stub"), s.get("amount_usd"))
    for s in as_list(other_deductions):
        s = as_dict(s)
        flat_row("other_" + str(s.get("name", "item")).lower().replace(" ", "_"), s.get("name", "Other deduction"), s.get("amount_usd"))
    known_total = sum(r["amount_usd"] for r in rows if r["amount_usd"] is not None)
    net = None if gross is None else gross - known_total
    tx_pct = num(brokerage_pct, 0.0) + num(closing_cost_pct, 0.0) + num(transfer_tax_pct, 0.0)
    return {"gross_price_usd": usd(gross), "deductions": rows, "total_deductions_usd": usd(known_total),
            "net_cash_proceeds_usd": usd(net), "net_proceeds_is_upper_bound": bool(unknown), "unknown_deductions": unknown,
            "net_per_net_ac_usd": usd(div(net, ac)), "net_pct_of_gross": rnd(pct_of(net, gross), 4),
            "transaction_cost_pct": rnd(tx_pct, 4),
            "summary": f"Net {known_total_text(net or 0.0, unknown)} from a price of ${gross or 0:,.0f}",
            "why": None if gross is not None else "A gross price is needed.",
            "assumptions": {"brokerage_pct": num(brokerage_pct), "closing_cost_pct": num(closing_cost_pct),
                            "transfer_tax_pct": num(transfer_tax_pct), "recording_fee_usd": num(recording_fee_usd),
                            "stub_per_net_ac_usd": num(stub_per_net_ac_usd), "net_ac": ac},
            "formula": ["Percent deductions = price x rate (brokerage, closing costs, transfer tax).",
                        "Flat deductions = seller note, debt release, recording fee, parcel stubs (per net acre x net acres).",
                        "Net cash proceeds = price - every deduction. An unknown deduction is listed and counted, not treated as zero."]}


@public
def waterfall_for_parcels(parcels, brokerage_pct=3.5, closing_cost_pct=0.75, transfer_tax_pct=0.11, recording_fee_usd=0.0,
                          stub_per_net_ac_usd=0.0):
    """gross_to_net_waterfall for every parcel {id, gross_price_usd, net_ac, seller_note_usd, debt_release_usd, stub_per_net_ac_usd,
    infrastructure_stubs} (a parcel's own stub rate wins over the shared one), plus the totals. Totals say how many parcels
    carry an unknown deduction."""
    rows, g_tot, n_tot, d_tot, unk = [], 0.0, 0.0, 0.0, 0
    for p in as_list(parcels):
        p = as_dict(p)
        w = gross_to_net_waterfall(p.get("gross_price_usd"), p.get("net_ac"), p.get("seller_note_usd") or 0.0, p.get("debt_release_usd") or 0.0,
                                   brokerage_pct, closing_cost_pct, transfer_tax_pct, recording_fee_usd,
                                   p.get("stub_per_net_ac_usd", stub_per_net_ac_usd) or 0.0, p.get("infrastructure_stubs"),
                                   p.get("other_deductions"))
        rows.append({"id": p.get("id"), **w})
        g_tot += w["gross_price_usd"] or 0.0
        n_tot += w["net_cash_proceeds_usd"] or 0.0
        d_tot += w["total_deductions_usd"] or 0.0
        unk += w["unknown_deductions"]
    return {"parcels": rows, "gross_total_usd": usd(g_tot), "deductions_total_usd": usd(d_tot), "net_total_usd": usd(n_tot),
            "unknown_deductions": unk, "net_total_is_upper_bound": unk > 0,
            "formula": "Each parcel: net = price - itemised deductions. Total = sum of the parcels."}
