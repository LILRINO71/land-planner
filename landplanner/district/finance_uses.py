"""The land use library and the arithmetic every other finance module shares: what a use builds, what it costs, what it earns.

A "land use library" is a dict {use_id: use definition}. Nothing about a project is hard-coded: every revenue, cost,
cap rate and required return comes from the library the caller passes. A use definition looks like:

    {"label": "Apartments",
     "density": {"units_per_net_ac": 30, "sf_per_unit": 900},          # or {"far": 0.25} for shops, offices
     "revenue": {"type": "rent_per_unit_mo", "rent_per_unit_mo": 2500, "vacancy_pct": 5, "other_income_pct": 3,
                 "opex_pct_of_income": 35},
     "cost_line_items": [{"id": "site_work", "amount": 150000}, ...],  # or {"site_work": 150000}
     "sales_cost_pct": 2, "cap_rate_pct": 5.5, "required_return_pct": 15}

Revenue types: per_unit_sale (price_per_unit), per_sf_sale (price_per_sf), rent_per_unit_mo (rent_per_unit_mo),
rent_per_sf_yr (rent_per_sf_yr or rent_per_sf_mo, plus efficiency_pct), room_revenue (adr, occupancy_pct).
"""
import copy

from .finance_common import SF_PER_AC, as_dict, as_list, div, frac, mul, num, public, usd

REVENUE_TYPES = ("per_unit_sale", "per_sf_sale", "rent_per_unit_mo", "rent_per_sf_yr", "room_revenue")
SALE_TYPES = ("per_unit_sale", "per_sf_sale")
BASES = ("per_unit", "per_building_sf", "per_net_ac", "lump_sum", "pct_of_hard", "pct_of_prior")
PCT_BASES = ("pct_of_hard", "pct_of_prior")

# (id, label, category, basis): the 15 line items every use is costed on unless the caller supplies its own list.
DEFAULT_LINE_ITEM_TEMPLATE = (
    ("site_work", "Site work and grading", "hard", "per_net_ac"),
    ("onsite_utilities", "On-site utilities, streets and landscaping", "hard", "per_net_ac"),
    ("building_shell", "Building shell and core", "hard", "per_building_sf"),
    ("interiors_finishes", "Interiors, finishes and tenant improvements", "hard", "per_building_sf"),
    ("parking", "Parking (surface and structured)", "hard", "per_building_sf"),
    ("ff_and_e", "Furniture, fixtures and equipment", "hard", "per_unit"),
    ("hard_contingency", "Hard cost contingency", "hard", "pct_of_hard"),
    ("design_engineering", "Architecture and engineering", "soft", "pct_of_hard"),
    ("permits_impact_fees", "Permits and impact fees", "soft", "per_unit"),
    ("legal_insurance", "Legal, accounting and insurance", "soft", "pct_of_hard"),
    ("marketing_leasing", "Marketing and leasing commissions", "soft", "per_building_sf"),
    ("developer_fee", "Development management fee", "soft", "pct_of_hard"),
    ("carry_taxes", "Property taxes and carry during construction", "soft", "per_net_ac"),
    ("other_soft", "Other soft costs and soft contingency", "soft", "pct_of_hard"),
    ("construction_interest", "Construction interest and loan fees", "financing", "pct_of_prior"),
)
_TEMPLATE = {row[0]: row for row in DEFAULT_LINE_ITEM_TEMPLATE}


@public
def default_cost_line_items():
    """The default list of 15 development cost line items, each with basis and category and amount None (fill it in).

    Bases: per_unit ($ per unit or key), per_building_sf ($ per building SF), per_net_ac ($ per net acre),
    lump_sum ($), pct_of_hard (% of the direct hard cost items), pct_of_prior (% of every item listed above it)."""
    return [{"id": i, "label": label, "category": cat, "basis": basis, "amount": None}
            for i, label, cat, basis in DEFAULT_LINE_ITEM_TEMPLATE]


def normalise_line_items(items):
    """A list of complete line item dicts from a list of dicts or a mapping {id: amount}. Items the caller did not list are not added."""
    rows = []
    if isinstance(items, dict):
        items = [{"id": k, "amount": v} for k, v in items.items()]
    for raw in as_list(items):
        raw = as_dict(raw)
        item_id = str(raw.get("id") or raw.get("label") or f"item_{len(rows) + 1}")
        base = _TEMPLATE.get(item_id)
        row = {"id": item_id,
               "label": raw.get("label") or (base[1] if base else item_id),
               "category": raw.get("category") or (base[2] if base else "hard"),
               "basis": raw.get("basis") or (base[3] if base else "lump_sum"),
               "amount": raw.get("amount")}
        if row["basis"] not in BASES:
            row["basis"] = "lump_sum"
        rows.append(row)
    return rows


def line_item_costs(items, net_ac=None, building_sf=None, units=None):
    """Prices every line item for a quantity. Returns {rows, total_usd, unknown_items, item_count, is_partial}.

    An item whose amount is None, or whose quantity is missing, is "not known": it is listed, counted, and left out of the total."""
    rows_in = normalise_line_items(items)
    qty = {"per_net_ac": num(net_ac), "per_building_sf": num(building_sf), "per_unit": num(units), "lump_sum": 1.0}
    out_rows = []
    direct_hard = 0.0
    for r in rows_in:                                    # pass 1: the base for pct_of_hard
        if r["category"] == "hard" and r["basis"] not in PCT_BASES:
            amt, q = num(r["amount"]), qty.get(r["basis"])
            if amt is not None and (amt == 0 or q is not None):
                direct_hard += 0.0 if amt == 0 else amt * q
    running = 0.0
    unknown = 0
    for r in rows_in:
        amt = num(r["amount"])
        value = None
        if amt is not None:
            if amt == 0:
                value = 0.0
            elif r["basis"] == "pct_of_hard":
                value = amt / 100.0 * direct_hard
            elif r["basis"] == "pct_of_prior":
                value = amt / 100.0 * running
            elif qty.get(r["basis"]) is not None:
                value = amt * qty[r["basis"]]
        if value is None:
            unknown += 1
        else:
            running += value
        out_rows.append({"id": r["id"], "label": r["label"], "category": r["category"], "basis": r["basis"],
                         "amount": amt, "cost_usd": None if value is None else usd(value)})
    return {"rows": out_rows, "total_usd": running, "unknown_items": unknown, "item_count": len(out_rows),
            "is_partial": unknown > 0}


# ---------------------------------------------------------------- what a use builds

def use_program(use_def, net_ac=None, units=None, building_sf=None, density_mult=1.0):
    """Net acres, units (or keys) and building SF for one use, from whichever one quantity is given and the use's density.

    Returns {net_ac, units, building_sf, why}; a value that cannot be derived is None."""
    d = as_dict(as_dict(use_def).get("density"))
    mult = num(density_mult, 1.0)
    upa = mul(d.get("units_per_net_ac"), mult)
    spu = num(d.get("sf_per_unit"))
    far = mul(d.get("far"), mult)
    net_ac, units, building_sf = num(net_ac), num(units), num(building_sf)
    if net_ac is not None:
        if units is None and upa is not None:
            units = net_ac * upa
        if building_sf is None:
            if units is not None and spu is not None:
                building_sf = units * spu
            elif far is not None:
                building_sf = net_ac * SF_PER_AC * far
    elif units is not None:
        net_ac = div(units, upa)
        if building_sf is None and spu is not None:
            building_sf = units * spu
    elif building_sf is not None:
        if far:
            net_ac = building_sf / (SF_PER_AC * far)
        elif spu and upa:
            units = building_sf / spu
            net_ac = units / upa
        if units is None and spu:
            units = building_sf / spu
    if net_ac is not None and units is None and upa is not None:
        units = net_ac * upa
    why = None
    if net_ac is None and units is None and building_sf is None:
        why = "Give net acres, units or building SF."
    elif net_ac is None:
        why = "Net acres cannot be derived: the use has no matching density."
    return {"net_ac": net_ac, "units": units, "building_sf": building_sf, "why": why}


# ---------------------------------------------------------------- what a use earns

def use_economics(use_def, prog):
    """Revenue and net operating income at full operation for one use and one program.

    For a sale use: gross_sales_usd and net_sales_usd (after sales_cost_pct). For an income use: potential gross income,
    vacancy, other income, effective income, operating expenses and noi_usd, all per YEAR. Anything missing gives None and `why`."""
    ud = as_dict(use_def)
    rv = as_dict(ud.get("revenue"))
    rtype = rv.get("type")
    prog = as_dict(prog)
    units, sf = num(prog.get("units")), num(prog.get("building_sf"))
    out = {"type": rtype, "is_sale": rtype in SALE_TYPES, "gross_sales_usd": None, "net_sales_usd": None,
           "potential_income_usd_yr": None, "vacancy_loss_usd_yr": None, "other_income_usd_yr": None,
           "effective_income_usd_yr": None, "operating_expenses_usd_yr": None, "noi_usd_yr": None, "why": None}
    if rtype not in REVENUE_TYPES:
        out["why"] = f"Revenue type must be one of {', '.join(REVENUE_TYPES)}."
        return out
    if rtype in SALE_TYPES:
        gross = mul(units, rv.get("price_per_unit")) if rtype == "per_unit_sale" else mul(sf, rv.get("price_per_sf"))
        if gross is None:
            out["why"] = "Sale revenue needs the quantity and the price."
            return out
        cost = frac(ud.get("sales_cost_pct")) or 0.0
        out["gross_sales_usd"], out["net_sales_usd"] = gross, gross * (1.0 - cost)
        return out
    other_pct = frac(rv.get("other_income_pct")) or 0.0
    vac = frac(rv.get("vacancy_pct")) or 0.0
    if rtype == "rent_per_unit_mo":
        pgi = mul(units, rv.get("rent_per_unit_mo"), 12.0)
    elif rtype == "rent_per_sf_yr":
        rent = num(rv.get("rent_per_sf_yr"))
        if rent is None and num(rv.get("rent_per_sf_mo")) is not None:
            rent = num(rv.get("rent_per_sf_mo")) * 12.0
        eff = frac(rv.get("efficiency_pct")) if rv.get("efficiency_pct") is not None else 1.0
        pgi = mul(sf, rent, eff)
    else:                                                # room_revenue
        occ = frac(rv.get("occupancy_pct"))
        pgi = mul(units, rv.get("adr"), 365.0, occ)
        vac = 0.0                                        # occupancy already carries the empty rooms
    if pgi is None:
        out["why"] = "Income needs the quantity and the rent (or ADR and occupancy)."
        return out
    other = pgi * other_pct
    egi = pgi * (1.0 - vac) + other
    opex = egi * (frac(rv.get("opex_pct_of_income")) or 0.0)
    out.update({"potential_income_usd_yr": pgi, "vacancy_loss_usd_yr": pgi * vac, "other_income_usd_yr": other,
                "effective_income_usd_yr": egi, "operating_expenses_usd_yr": opex, "noi_usd_yr": egi - opex})
    return out


# ---------------------------------------------------------------- scenario adjustments

_PRICE_KEYS = {"per_unit_sale": ("price_per_unit",), "per_sf_sale": ("price_per_sf",),
               "rent_per_unit_mo": ("rent_per_unit_mo",), "rent_per_sf_yr": ("rent_per_sf_yr", "rent_per_sf_mo"),
               "room_revenue": ("adr",)}


def adjust_use(use_def, adj):
    """A copy of a use definition with an adjustment applied. Adjustment keys (all optional):
    revenue_pct (+/- % on every price, rent and ADR), revenue_factor_by_type ({revenue type: multiplier}),
    cost_pct (+/- % on every cost amount that is not itself a percent), cap_rate_delta_pct (percentage points added to the
    cap rate and the exit cap), cap_rate_set_pct (replaces them), required_return_delta_pct (points), density_pct (+/- % on density)."""
    ud = copy.deepcopy(as_dict(use_def))
    adj = as_dict(adj)
    rv = as_dict(ud.get("revenue"))
    rtype = rv.get("type")
    mult = 1.0 + (num(adj.get("revenue_pct"), 0.0) / 100.0)
    mult *= num(as_dict(adj.get("revenue_factor_by_type")).get(rtype), 1.0)
    if mult != 1.0:
        for key in _PRICE_KEYS.get(rtype, ()):
            if num(rv.get(key)) is not None:
                rv[key] = num(rv[key]) * mult
    cost_mult = 1.0 + num(adj.get("cost_pct"), 0.0) / 100.0
    if cost_mult != 1.0 and "cost_line_items" in ud:
        items = normalise_line_items(ud["cost_line_items"])
        for row in items:
            if row["basis"] not in PCT_BASES and num(row["amount"]) is not None:
                row["amount"] = num(row["amount"]) * cost_mult
        ud["cost_line_items"] = items
    for key in ("cap_rate_pct", "exit_cap_pct"):
        if num(ud.get(key)) is not None:
            if adj.get("cap_rate_set_pct") is not None:
                ud[key] = num(adj["cap_rate_set_pct"])
            else:
                ud[key] = num(ud[key]) + num(adj.get("cap_rate_delta_pct"), 0.0)
    if "cap_rate_pct" not in ud and adj.get("cap_rate_set_pct") is not None and rtype not in SALE_TYPES:
        ud["cap_rate_pct"] = num(adj["cap_rate_set_pct"])
    if num(ud.get("required_return_pct")) is not None:
        ud["required_return_pct"] = num(ud["required_return_pct"]) + num(adj.get("required_return_delta_pct"), 0.0)
    dens = num(adj.get("density_pct"), 0.0)
    if dens and isinstance(ud.get("density"), dict):
        for key in ("units_per_net_ac", "far"):
            if num(ud["density"].get(key)) is not None:
                ud["density"][key] = num(ud["density"][key]) * (1.0 + dens / 100.0)
    ud["revenue"] = rv
    return ud


def adjust_library(library, adj, use_ids=None):
    """adjust_use over every use in a library (or just the use_ids)."""
    out = {}
    for use_id, ud in as_dict(library).items():
        out[use_id] = adjust_use(ud, adj) if use_ids is None or use_id in use_ids else copy.deepcopy(ud)
    return out


def library_issues(library):
    """A list of plain-language problems with a land use library (empty when it is usable)."""
    issues = []
    lib = as_dict(library)
    if not lib:
        return ["The land use library is empty."]
    for use_id, ud in lib.items():
        ud = as_dict(ud)
        if as_dict(ud.get("revenue")).get("type") not in REVENUE_TYPES:
            issues.append(f"{use_id}: revenue type is missing or unknown.")
        if not ud.get("cost_line_items"):
            issues.append(f"{use_id}: no cost line items.")
        if as_dict(ud.get("revenue")).get("type") not in SALE_TYPES and num(ud.get("cap_rate_pct")) in (None, 0.0):
            issues.append(f"{use_id}: an income use needs a cap rate above zero.")
    return issues


@public
def check_land_use_library(library):
    """Reports what is missing from a land use library before any calculation. Returns {ok, uses, issues, formula}."""
    issues = library_issues(library)
    return {"ok": not issues, "uses": sorted(as_dict(library)), "issues": issues, "revenue_types": list(REVENUE_TYPES),
            "formula": "Each use needs a revenue type, cost line items, and (income uses) a cap rate above zero."}
