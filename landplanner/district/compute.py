"""Computed results: a dataset's content fed into the finance engine (finance.py, docs/district-finance.md) and
answered as {inputs_used, result, formula, missing}. The conventions that say where each input comes from (which
entity, which assumption id) are in docs/district-data-contract.md, section "Compute"; they are the tables here.

Nothing is saved: a what-if (POST) changes a copy of the content in memory. The answer is filtered for the caller's
audience on the way out by api.py (filter_answer below, then access.scrub).
"""
import copy

from . import Problem
from . import finance as F
from . import register as R
from .jsonsafe import finite
from .schema import AUDIENCE_DENY, ENTITIES, field_tags, row_tags
from .validate import clean_record

TOOLS = ("landvalue", "proceeds", "proforma", "strategy", "scenarios", "funding", "fiscal", "reconcile")

# What each part of a tool's result is about. An audience that denies a tag never receives that part.
RESULT_TAGS = {
    "landvalue": {"by_parcel": {"rlv_parcel"}, "pricing_tiers": {"price_floor", "disposition"}},
    "proceeds": {"waterfall": {"disposition"}, "capital_plan": {"disposition"}, "targets": {"disposition"}},
    "proforma": {"break_even": {"returns"}, "tornado": {"returns"}},
    "strategy": {"decisions": {"returns", "disposition"}, "conflicts": {"disposition"},
                 "retained_value": {"disposition"}, "paced_releases": {"disposition"},
                 "retained_parcels": {"disposition"}},
    "scenarios": {},
    "funding": {"funding_gap": {"disposition"}},
    "fiscal": {},
    "reconcile": {},
}

NON_REVENUE_GROUPS = ("open space", "civic", "infrastructure", "parks")

# assumption id -> (label, unit, the engine's own starting figure or None, tags)
CONVENTIONS = {
    "PF-BASE-YEAR": ("first year of the pro forma", "count", None, ()),
    "PF-DISCOUNT-RATE-PCT": ("pro forma discount rate", "pct", 10.0, ("returns",)),
    "PF-HOLD-YEARS": ("years held after stabilisation", "years", 10, ()),
    "PF-BUILD-YEARS": ("years to build", "years", 2, ()),
    "PF-LEASE-UP-MONTHS": ("months to lease up", "months", 24, ()),
    "PF-SELLOUT-MONTHS": ("months to sell out", "months", 24, ()),
    "PF-NOI-GROWTH-PCT": ("NOI growth per year", "pct", 0.0, ()),
    "PF-HURDLE-YOC-PCT": ("hurdle yield on cost", "pct", None, ("returns",)),
    "PF-HURDLE-IRR-PCT": ("hurdle IRR", "pct", None, ("returns",)),
    "FIN-NET-TO-GROSS-PCT": ("net acres as a share of gross", "pct", 100.0, ()),
    "FIN-SPONSOR-HURDLE-PCT": ("sponsor hurdle on cost", "pct", 20.0, ("price_floor",)),
    "FIN-STRATEGIC-PREMIUM-PCT": ("strategic premium on cost", "pct", 0.0, ("price_floor",)),
    "FIN-TARGET-PCT-OF-RLV": ("target price as a share of residual value", "pct", 100.0, ("disposition",)),
    "FIN-UPSIDE-PCT": ("upside over the target price", "pct", 15.0, ("disposition",)),
    "FIN-BROKERAGE-PCT": ("brokerage commission", "pct", 3.5, ("disposition",)),
    "FIN-CLOSING-PCT": ("closing costs", "pct", 0.75, ("disposition",)),
    "FIN-TRANSFER-TAX-PCT": ("transfer tax", "pct", 0.11, ("disposition",)),
    "FIN-RECORDING-FEE-USD": ("recording fee per sale", "usd", 0.0, ("disposition",)),
    "FIN-CRITICAL-THRESHOLD": ("strategic score that makes a parcel critical", "count", 75.0, ()),
    "STR-DISCOUNT-RATE-PCT": ("strategy comparison discount rate", "pct", 8.0, ("returns",)),
    "STR-APPRECIATION-PCT": ("land appreciation per year", "pct", 3.0, ()),
    "STR-SALE-COST-PCT": ("selling cost of retained land", "pct", 4.36, ("disposition",)),
    "STR-PLACEMAKING-LIFT-PCT": ("placemaking lift on retained land", "pct", 0.0, ()),
    "STR-LIFT-YEAR": ("year the placemaking lift arrives", "count", 1, ()),
    "STR-RELEASE-ACRES": ("acres released in each tranche", "acres", None, ()),
    "STR-RELEASE-EVERY-YEARS": ("years between tranches", "years", None, ()),
    "STR-MIN-CORE-ACRES": ("core acres never released", "acres", 0.0, ()),
    "SCN-ABSORPTION-UNITS-PER-YEAR": ("home absorption per year", "units_per_yr", None, ()),
    "SCN-PRELEASING-PCT": ("pre-leasing today", "pct", None, ()),
    "FISCAL-CONSTRUCTION-JOBS-PER-MILLION": ("construction job-years per $1 million", "count", None, ()),
    "FISCAL-CONSTRUCTION-MULTIPLIER": ("construction output multiplier", "ratio", None, ()),
    "FISCAL-OPERATING-MULTIPLIER": ("operating output multiplier", "ratio", None, ()),
    "FISCAL-SALES-TAX-PCT": ("local sales tax rate", "pct", None, ()),
    "FISCAL-PROPERTY-TAX-PCT": ("property tax rate", "pct", None, ()),
    "FISCAL-CITY-SHARE-PCT": ("city share of property tax", "pct", None, ()),
    "FISCAL-HOTEL-TAX-PCT": ("hotel room tax", "pct", None, ()),
    "EIFD-PARTICIPATING-SHARE-PCT": ("share of the increment a district captures", "pct", None, ()),
    "EIFD-YEARS": ("years of increment shown", "years", 30, ()),
    "EIFD-GROWTH-PCT": ("assessed value growth per year", "pct", 2.0, ()),
}
# per use (or per use group, in capitals): FISCAL-JOBS-PER-1000SF-<x>, FISCAL-SALES-PER-SF-<x>; unit scenarios SCN-UNITS-<n>
PREFIXES = {"FISCAL-JOBS-PER-1000SF-": "jobs per 1,000 SF", "FISCAL-SALES-PER-SF-": "taxable sales per SF per year",
            "SCN-UNITS-": "a named unit-count scenario"}

OPTIONS = {"proceeds": {"price_basis": ("target_market", "minimum_recommended", "upside_stretch", "economic_cost_floor")},
           "proforma": {"tornado_metric": ("irr_pct", "yoc_pct", "npv_usd", "rlv_total_usd", "equity_multiple")}}


class Inputs:
    """Reads the dataset for one tool, and keeps the list of what it used and what was missing."""

    def __init__(self, content):
        self.c = content
        self.used, self.missing, self._seen = [], [], set()
        self.reg = {a.get("id"): a for a in content["entities"]["assumptions"]}

    def rows(self, entity):
        return self.c["entities"].get(entity, [])

    def _note(self, key, entry):
        if key not in self._seen:
            self._seen.add(key)
            self.used.append(entry)

    def num(self, aid, label=None, unit=None, default="convention", tags=()):
        """A register figure by id; the engine's starting figure (said so in missing) when it is not there."""
        conv = CONVENTIONS.get(aid, (label or aid, unit, None, tags))
        label, unit = label or conv[0], unit or conv[1]
        fallback = conv[2] if default == "convention" else default
        tags = set(tags) | set(conv[3])
        a = self.reg.get(aid)
        if a and finite(a.get("value")):
            self._note(("a", aid), {"assumption_id": aid, "label": a.get("label"), "value": a["value"],
                                    "unit": a.get("unit"), "provenance": a.get("provenance"),
                                    "what_if": bool(a.get("what_if")), "tags": sorted(tags | set(a.get("tags") or []))})
            return a["value"]
        if fallback is None:
            self._miss(f"{label[:1].upper()}{label[1:]}: no figure in the register (assumption id {aid}).")
            return None
        self._note(("a", aid), {"assumption_id": aid, "label": label, "value": fallback, "unit": unit,
                                "provenance": "ENGINE STARTING FIGURE", "what_if": False, "tags": sorted(tags)})
        self._miss(f"{label[:1].upper()}{label[1:]}: no figure in the register (assumption id {aid}); the engine's "
                   f"starting figure {fallback} was used.")
        return fallback

    def field(self, entity, record, name, unit=None):
        v = record.get(name)
        if v is None or v == "" or v == []:
            return None
        tags = field_tags(entity, name) | row_tags(entity, record) | set(record.get("tags") or [])
        f = ENTITIES[entity]["fields"].get(name, {})
        self._note(("f", entity, record.get("id"), name), {
            "field": f"{entity}/{record.get('id')}/{name}", "value": v, "unit": unit or f.get("unit"),
            "provenance": record.get("provenance"), "what_if": bool(record.get("what_if")), "tags": sorted(tags)})
        return v

    def _miss(self, text):
        if text not in self.missing:
            self.missing.append(text)

    def prefixed(self, prefix):
        return {aid[len(prefix):]: a for aid, a in self.reg.items() if aid.startswith(prefix) and finite(a.get("value"))}

    # ---------------------------------------------------------------- shared pieces

    def uses(self):
        return {u.get("id"): u for u in self.rows("uses")}

    def library(self):
        """The land use library: one land_uses row per Use, with its cost_items."""
        lib = {}
        costs = [c for c in self.rows("cost_items") if c.get("use")]
        for row in self.rows("land_uses"):
            e = "land_uses"
            d = {}
            if row.get("units_per_net_ac") is not None:
                d = {"units_per_net_ac": self.field(e, row, "units_per_net_ac"),
                     "sf_per_unit": self.field(e, row, "sf_per_unit")}
            elif row.get("far") is not None:
                d = {"far": self.field(e, row, "far")}
            kind = row.get("revenue_type")
            rev = {"type": kind}
            for k in ("price_per_unit", "price_per_sf", "rent_per_unit_mo", "rent_per_sf_yr", "efficiency_pct", "adr",
                      "occupancy_pct", "vacancy_pct", "other_income_pct", "opex_pct_of_income"):
                if row.get(k) is not None:
                    rev[k] = self.field(e, row, k)
            items = []
            for c in costs:
                if c.get("use") == row.get("id"):
                    items.append({"id": c.get("item"), "label": c.get("label") or c.get("item"),
                                  "category": c.get("category") or "hard", "basis": c.get("basis") or "lump_sum",
                                  "amount": self.field("cost_items", c, "amount")})
            lib[row["id"]] = {"label": row.get("label"), "density": d, "revenue": rev, "cost_line_items": items,
                              **{k: self.field(e, row, k) for k in ("sales_cost_pct", "cap_rate_pct", "exit_cap_pct",
                                                                     "required_return_pct") if row.get(k) is not None}}
        if not lib:
            self._miss("There are no land_uses rows (the finance library: density, revenue, cap rate and required "
                       "return per use), so nothing can be valued.")
        else:
            for issue in F.check_land_use_library(lib).get("issues") or []:
                self._miss(_words(issue))
        return lib

    def library_gaps(self, lib, use_ids):
        """Uses in the program with no library row (parks and other non-revenue uses are left out quietly)."""
        uses = self.uses()
        for uid in sorted(set(use_ids)):
            if uid not in lib and str((uses.get(uid) or {}).get("use_group", "")).lower() not in NON_REVENUE_GROUPS:
                label = (uses.get(uid) or {}).get("label") or uid
                self._miss(f"{label} ({uid}) has no land_uses row, so it is left out.")

    def finance_parcels(self):
        net_to_gross = self.num("FIN-NET-TO-GROSS-PCT")
        out = []
        for p in self.rows("parcels"):
            e = "parcels"
            row = {"id": p.get("id"), "name": p.get("label") or p.get("apn"), "gross_ac": self.field(e, p, "acres"),
                   "use": p.get("use")}
            if p.get("net_acres") is not None:
                row["net_ac"] = self.field(e, p, "net_acres")
            else:
                row["net_to_gross_pct"] = net_to_gross
            if p.get("candidate_uses"):
                row["candidate_uses"] = self.field(e, p, "candidate_uses")
            out.append(row)
        if not out:
            self._miss("There are no parcels.")
        return out

    def pro_forma_assumptions(self):
        out = {}
        for aid, key in (("PF-BASE-YEAR", "base_year"), ("PF-DISCOUNT-RATE-PCT", "discount_rate_pct"),
                         ("PF-HOLD-YEARS", "hold_years"), ("PF-BUILD-YEARS", "build_years"),
                         ("PF-LEASE-UP-MONTHS", "lease_up_months"), ("PF-SELLOUT-MONTHS", "sellout_months"),
                         ("PF-NOI-GROWTH-PCT", "noi_growth_pct"), ("PF-HURDLE-YOC-PCT", "hurdle_yoc_pct"),
                         ("PF-HURDLE-IRR-PCT", "hurdle_irr_pct")):
            v = self.num(aid)
            if v is not None:
                out[key] = int(v) if key in ("base_year", "hold_years", "build_years") else v
        if "base_year" not in out:
            years = [ph.get("start_year") for ph in self.rows("phases") if finite(ph.get("start_year"))]
            if years:
                out["base_year"] = int(min(years))
        return out

    def phases(self, lib, scenario="base"):
        """Finance phases from the phases entity and the program lines of one scenario (the 'full' phase is the
        whole buildout and is not a phase of its own)."""
        lines = [pl for pl in self.rows("program_lines") if pl.get("scenario") == scenario]
        out = []
        for ph in sorted(self.rows("phases"), key=lambda x: (x.get("order") or 0, str(x.get("id")))):
            if str(ph.get("id")) == "full":
                continue
            mine = []
            for pl in lines:
                if str(pl.get("phase")) != str(ph.get("id")) or pl.get("use") not in lib:
                    continue
                line = {"use": pl["use"]}
                if pl.get("units") is not None:
                    line["units"] = self.field("program_lines", pl, "units")
                elif pl.get("keys") is not None:
                    line["units"] = self.field("program_lines", pl, "keys")
                elif pl.get("sf") is not None:
                    line["building_sf"] = self.field("program_lines", pl, "sf")
                elif pl.get("acres") is not None:
                    line["net_ac"] = self.field("program_lines", pl, "acres")
                else:
                    continue
                mine.append(line)
            row = {"id": str(ph.get("id")), "label": ph.get("label"), "lines": mine}
            if ph.get("land_cost_usd") is not None:
                row["land_cost_usd"] = self.field("phases", ph, "land_cost_usd")
            if ph.get("start_offset_years") is not None:
                row["start_offset_years"] = self.field("phases", ph, "start_offset_years")
            if mine:
                out.append(row)
        self.library_gaps(lib, [pl.get("use") for pl in lines])
        if not out:
            self._miss(f"No phase has {scenario}-case program lines whose use is in the finance library.")
        return out


def _words(issue):
    if isinstance(issue, dict):
        return " ".join(str(v) for k, v in issue.items() if k in ("use", "why", "issue", "message", "text") and v) or \
            str(issue)
    return str(issue)


def _formula(*parts):
    out = []
    for p in parts:
        if isinstance(p, list):
            out.extend(str(x) for x in p if x)
        elif p:
            out.append(str(p))
    return out


# ---------------------------------------------------------------- the tools

def t_landvalue(inp, options):
    lib = inp.library()
    n2g = inp.num("FIN-NET-TO-GROSS-PCT")
    by_use = F.residual_land_value_by_use(lib, net_to_gross_pct=n2g) if lib else None
    parcels = inp.finance_parcels()
    by_parcel = F.residual_land_value_by_parcel(parcels, lib) if lib and parcels else None
    hurdle = inp.num("FIN-SPONSOR-HURDLE-PCT")
    premium = inp.num("FIN-STRATEGIC-PREMIUM-PCT")
    target_pct = inp.num("FIN-TARGET-PCT-OF-RLV")
    upside = inp.num("FIN-UPSIDE-PCT")
    tiers = []
    costs = {}
    for c in inp.rows("cost_items"):
        if c.get("parcel"):
            costs.setdefault(c["parcel"], {})[c.get("label") or c.get("item")] = inp.field("cost_items", c, "amount")
    rows = {r["id"]: r for r in (by_parcel or {}).get("parcels", [])}
    for p in inp.rows("parcels"):
        if p.get("id") not in costs:
            inp._miss(f"Parcel {p.get('id')} has no cost_items (its cost basis), so its price floor is not known.")
        r = rows.get(p.get("id")) or {}
        chosen = (r.get("uses") or {}).get(r.get("totalled_use")) or {}
        base = (chosen.get("base") or {}).get("rlv_usd")
        high = (chosen.get("high") or {}).get("rlv_usd")
        parcel = {"id": p.get("id"), "gross_ac": p.get("acres"), "net_ac": r.get("net_ac") or p.get("net_acres"),
                  "cost_items": costs.get(p.get("id"), {}),
                  "strategic_score": inp.field("parcels", p, "strategic_score")}
        tiers.append({"parcel": p.get("id"), "use": r.get("totalled_use"),
                      **F.pricing_tiers(parcel, base, high, sponsor_hurdle_pct=hurdle, strategic_premium_pct=premium,
                                        target_pct_of_rlv=target_pct, upside_pct=upside)})
    result = {"by_use": by_use, "by_parcel": by_parcel, "pricing_tiers": tiers}
    formula = _formula((by_use or {}).get("formula"), "Pricing tiers: cost floor = the parcel's cost items; minimum = "
                       "floor x (1 + sponsor hurdle) + strategic premium; target = base residual x target percent; "
                       "upside = high residual.")
    return result, formula


def _price_basis(inp, tiers, basis):
    out = {}
    for t in tiers:
        price = ((t.get("tiers") or {}).get(basis) or {}).get("price_usd")
        out[t.get("parcel")] = price
    return out


def _sale_parcels(inp, prices):
    stubs = {}
    for it in inp.rows("infrastructure"):
        if it.get("parcel"):
            stubs.setdefault(it["parcel"], []).append({"name": it.get("item"),
                                                      "amount_usd": inp.field("infrastructure", it, "cost_usd")})
    out = []
    for p in inp.rows("parcels"):
        if prices.get(p.get("id")) is None:
            inp._miss(f"Parcel {p.get('id')} has no price on the chosen basis, so it is left out of the sale plan.")
            continue
        out.append({"id": p.get("id"), "name": p.get("label"), "gross_price_usd": prices[p["id"]],
                    "net_ac": p.get("net_acres") or p.get("acres"),
                    "seller_note_usd": inp.field("parcels", p, "seller_note_usd") or 0.0,
                    "debt_release_usd": inp.field("parcels", p, "debt_release_usd") or 0.0,
                    "infrastructure_stubs": stubs.get(p.get("id"), []),
                    "strategic_score": inp.field("parcels", p, "strategic_score"),
                    "close_month": inp.field("parcels", p, "close_month"),
                    "must_keep": bool(p.get("must_keep")), "critical": bool(p.get("critical")),
                    "do_not_sell_until_month": inp.field("parcels", p, "do_not_sell_until_month")})
    return out


def t_proceeds(inp, options):
    basis = options.get("price_basis") or "target_market"
    tiers_result, _ = t_landvalue(inp, {})
    prices = _price_basis(inp, tiers_result["pricing_tiers"], basis)
    rates = {"brokerage_pct": inp.num("FIN-BROKERAGE-PCT"), "closing_cost_pct": inp.num("FIN-CLOSING-PCT"),
             "transfer_tax_pct": inp.num("FIN-TRANSFER-TAX-PCT"), "recording_fee_usd": inp.num("FIN-RECORDING-FEE-USD")}
    parcels = _sale_parcels(inp, prices)
    waterfall = F.waterfall_for_parcels(parcels, **rates) if parcels else None
    targets = []
    for t in inp.rows("capital_targets"):
        targets.append({"month": inp.field("capital_targets", t, "month"),
                        "amount_usd": inp.field("capital_targets", t, "amount_usd"), "label": t.get("label")})
    if not targets:
        inp._miss("There are no capital_targets (cash needed by month), so the capital target solver was not run.")
    cumulative = all(t.get("cumulative", True) is not False for t in inp.rows("capital_targets"))
    plan = F.solve_capital_targets(parcels, targets, targets_are_cumulative=cumulative,
                                   critical_threshold=inp.num("FIN-CRITICAL-THRESHOLD"), **rates) \
        if parcels and targets else None
    result = {"price_basis": basis, "waterfall": waterfall, "capital_plan": plan, "targets": targets}
    return result, _formula("Gross price per parcel = its " + basis.replace("_", " ") + " price from the landvalue tool.",
                            (waterfall or {}).get("formula"), (plan or {}).get("formula"))


def t_proforma(inp, options):
    lib = inp.library()
    a = inp.pro_forma_assumptions()
    phases = inp.phases(lib)
    full = F.full_buildout_pro_forma(phases, lib, a) if phases else None
    kinds = {lib[u]["revenue"]["type"] for ph in phases for u in [ln["use"] for ln in ph["lines"]]}
    variables = [v for v, k in (("apartment_rent", "rent_per_unit_mo"), ("retail_nnn_rent", "rent_per_sf_yr"),
                                ("hotel_adr", "room_revenue"), ("for_sale_price", "per_unit_sale"),
                                ("exit_cap_rate", None)) if k is None or k in kinds]
    breaks = {}
    if phases:
        for v in variables:
            breaks[v] = F.break_even(phases, lib, a, v)
    metric = options.get("tornado_metric") or "irr_pct"
    tornado = F.sensitivity_tornado({"library": lib, "phases": phases, "parcels": [], "assumptions": a},
                                    metric=metric) if phases else None
    result = {"phases": (full or {}).get("phases"), "full_buildout": (full or {}).get("full_buildout"),
              "break_even": breaks, "tornado": tornado}
    return result, _formula((full or {}).get("formula"), "Break-even: the driver value at which the buildout just "
                            "meets its hurdle.", (tornado or {}).get("formula"))


def t_strategy(inp, options):
    assumptions = {"discount_rate_pct": inp.num("STR-DISCOUNT-RATE-PCT"),
                   "appreciation_pct": inp.num("STR-APPRECIATION-PCT"),
                   "sale_cost_pct": inp.num("STR-SALE-COST-PCT"),
                   "critical_threshold": inp.num("FIN-CRITICAL-THRESHOLD")}
    parcels = []
    for p in inp.rows("parcels"):
        row = {"id": p.get("id"), "name": p.get("label"), "net_ac": p.get("net_acres") or p.get("acres"),
               "land_value_usd": inp.field("parcels", p, "land_value_usd"),
               "strategic_score": inp.field("parcels", p, "strategic_score"),
               "critical": bool(p.get("critical")), "must_keep": bool(p.get("must_keep")),
               "do_not_sell_until_month": inp.field("parcels", p, "do_not_sell_until_month")}
        if p.get("strategic_scores"):
            row["strategic_scores"] = inp.field("parcels", p, "strategic_scores")
        extra = inp.field("parcels", p, "strategy_inputs") or {}
        if isinstance(extra, dict):
            row.update(copy.deepcopy(extra))
        if row["land_value_usd"] is None:
            inp._miss(f"Parcel {p.get('id')} has no land_value_usd, so its strategies cannot be compared.")
        parcels.append(row)
    decisions = F.decide_parcels(parcels, assumptions) if parcels else None
    recs = {d.get("id"): d.get("guarded_recommendation") or d.get("recommended_strategy")
            for d in (decisions or {}).get("parcels", [])} if decisions else {}
    sell = [pid for pid, r in recs.items() if r and "sale" in str(r)]
    conflicts = F.critical_asset_conflicts(parcels, sell_ids=sell, assumptions=assumptions) if parcels else None
    kept = [p for p in parcels if p["id"] not in sell and finite(p.get("land_value_usd"))]
    base_value = sum(p["land_value_usd"] for p in kept)
    acres = sum(float(p.get("net_ac") or 0) for p in kept)
    lift, lift_year = inp.num("STR-PLACEMAKING-LIFT-PCT"), inp.num("STR-LIFT-YEAR")
    retained = F.retained_land_value(base_value, assumptions["appreciation_pct"], lift or 0.0, int(lift_year or 1),
                                     acres=acres) if kept else None
    release, every = inp.num("STR-RELEASE-ACRES"), inp.num("STR-RELEASE-EVERY-YEARS")
    paced = None
    if kept and release and every and acres:
        paced = F.paced_land_releases(acres, base_value / acres, release, int(every),
                                      appreciation_pct=assumptions["appreciation_pct"], placemaking_lift_pct=lift or 0.0,
                                      lift_year=int(lift_year or 1), min_core_acres=inp.num("STR-MIN-CORE-ACRES") or 0.0,
                                      sale_cost_pct=assumptions["sale_cost_pct"])
    result = {"decisions": decisions, "conflicts": conflicts, "retained_value": retained, "paced_releases": paced,
              "retained_parcels": [p["id"] for p in kept]}
    return result, _formula((decisions or {}).get("formula"), (retained or {}).get("formula"),
                            (paced or {}).get("formula"))


def t_scenarios(inp, options):
    lib = inp.library()
    a = inp.pro_forma_assumptions()
    phases = inp.phases(lib)
    parcels = inp.finance_parcels()
    inputs = {"library": lib, "parcels": parcels, "phases": phases, "assumptions": a}
    side = F.run_scenarios(inputs) if lib and phases else None
    totals = sorted({int(v["value"]) for v in inp.prefixed("SCN-UNITS-").values()})
    for aid in sorted(k for k in inp.reg if k.startswith("SCN-UNITS-")):
        inp.num(aid, "a named unit-count scenario", "units", None)
    res_uses = [u for u in lib if str((inp.uses().get(u) or {}).get("use_group", "")).lower() == "residential"]
    units = None
    if totals and phases:
        units = F.run_scenarios(inputs, F.unit_count_scenarios(totals, res_uses or None))
    elif not totals:
        inp._miss("No unit-count scenarios in the register (assumptions SCN-UNITS-<number>).")
    homes = sum(float(ln.get("units") or 0) for ph in phases for ln in ph["lines"] if ln["use"] in res_uses)
    per_year = inp.num("SCN-ABSORPTION-UNITS-PER-YEAR")
    absorption = F.absorption_schedule(homes, absorption_per_year=per_year) if homes and per_year else None
    pre = inp.num("SCN-PRELEASING-PCT")
    base_year = a.get("base_year")
    triggers = []
    for ph in sorted(inp.rows("phases"), key=lambda x: x.get("order") or 0):
        rules = []
        if ph.get("residential_units_trigger") is not None:
            rules.append({"id": f"{ph['id']}-homes", "label": "Homes sold and occupied", "metric": "units_absorbed",
                          "operator": ">=", "threshold": inp.field("phases", ph, "residential_units_trigger")})
        if ph.get("preleasing_pct_trigger") is not None:
            rules.append({"id": f"{ph['id']}-prelease", "label": "Pre-leasing", "metric": "pre_leasing_pct",
                          "operator": ">=", "threshold": inp.field("phases", ph, "preleasing_pct_trigger")})
        if not rules:
            continue
        month = None
        if base_year and finite(ph.get("start_year")):
            month = max(1, int((ph["start_year"] - base_year) * 12))
        status = dict((F.schedule_status_at_month(absorption, month, pre or 0.0) if absorption and month
                       else {}).get("metrics") or {})
        if pre is not None:
            status["pre_leasing_pct"] = pre
        triggers.append({"phase": ph.get("id"), "label": ph.get("label"), "at_month": month, "status": status,
                         **F.evaluate_phasing_triggers(rules, status)})
    if absorption:
        absorption = {k: v for k, v in absorption.items() if k != "monthly"}      # the yearly rows are enough here
    result = {"low_base_high": side, "unit_scenarios": units, "absorption": absorption, "phase_triggers": triggers}
    return result, _formula((side or {}).get("formula"), (absorption or {}).get("formula"))


def t_funding(inp, options):
    items = []
    for it in inp.rows("infrastructure"):
        items.append({"code": it.get("id"), "name": it.get("item"), "phase": it.get("phase"),
                      "cost_usd": inp.field("infrastructure", it, "cost_usd"),
                      "responsible": inp.field("infrastructure", it, "payer"),
                      "due_period": inp.field("infrastructure", it, "due_period"),
                      "reimbursable": bool(it.get("reimbursable"))})
    if not items:
        inp._miss("There are no infrastructure items.")
    register = F.infrastructure_register(items, period_unit="year") if items else None
    tiers_result, _ = t_landvalue(inp, {})
    prices = _price_basis(inp, tiers_result["pricing_tiers"], "target_market")
    a = inp.pro_forma_assumptions()
    base_year = a.get("base_year")
    years = sorted({int(i["due_period"]) for i in items if finite(i.get("due_period"))})
    proceeds = {}
    if base_year:
        for p in _sale_parcels(inp, prices):
            if finite(p.get("close_month")):
                y = int(base_year + (p["close_month"] - 1) // 12)
                w = F.gross_to_net_waterfall(p["gross_price_usd"], p.get("net_ac"),
                                             brokerage_pct=inp.num("FIN-BROKERAGE-PCT"),
                                             closing_cost_pct=inp.num("FIN-CLOSING-PCT"),
                                             transfer_tax_pct=inp.num("FIN-TRANSFER-TAX-PCT"))
                if finite(w.get("net_cash_proceeds_usd")):
                    proceeds[y] = proceeds.get(y, 0.0) + w["net_cash_proceeds_usd"]
                years.append(y)
    periods = sorted(set(years))
    gap = F.infrastructure_funding_gap(items, periods, proceeds, period_unit="year") if items and periods else None
    if not periods:
        inp._miss("No infrastructure item has a due year, so the funding gap cannot be laid out by period.")
    result = {"register": register, "funding_gap": gap, "unknown_cost_items": sum(1 for i in items if i["cost_usd"] is None)}
    return result, _formula((register or {}).get("formula"), (gap or {}).get("formula"),
                            "Land sale proceeds by year: each parcel's target price through the gross-to-net "
                            "waterfall, in the year its close_month falls.")


def t_fiscal(inp, options):
    lib = inp.library()
    a = inp.pro_forma_assumptions()
    phases = inp.phases(lib)
    full = F.full_buildout_pro_forma(phases, lib, a) if phases else {}
    uses = inp.uses()
    jobs, sales = inp.prefixed("FISCAL-JOBS-PER-1000SF-"), inp.prefixed("FISCAL-SALES-PER-SF-")

    def rate(table, prefix, use):
        group = str((uses.get(use) or {}).get("use_group", "")).upper().replace(" ", "-")
        for key in (use, group):
            if key in table:
                return inp.num(prefix + key, unit=table[key].get("unit"))
        return None
    rates = {"construction_jobs_per_million_usd": inp.num("FISCAL-CONSTRUCTION-JOBS-PER-MILLION"),
             "construction_output_multiplier": inp.num("FISCAL-CONSTRUCTION-MULTIPLIER"),
             "operating_output_multiplier": inp.num("FISCAL-OPERATING-MULTIPLIER"),
             "sales_tax_rate_pct": inp.num("FISCAL-SALES-TAX-PCT"),
             "property_tax_rate_pct": inp.num("FISCAL-PROPERTY-TAX-PCT"),
             "city_property_tax_share_pct": inp.num("FISCAL-CITY-SHARE-PCT"),
             "hotel_tax_pct": inp.num("FISCAL-HOTEL-TAX-PCT"), "jobs_per_1000_sf_by_use": {}}
    by_phase = {str(p.get("phase_id") or p.get("id")): p for p in (full.get("phases") or [])}
    fphases, eifd_phases = [], []
    for ph in phases:
        pf = by_phase.get(ph["id"]) or {}
        totals = pf.get("totals") or {}
        sf_by_use, taxable, rooms = {}, 0.0, 0.0
        for ln in pf.get("lines") or []:
            use = ln.get("use")
            sf = ln.get("building_sf")
            if finite(sf):
                sf_by_use[use] = sf_by_use.get(use, 0.0) + sf
            j = rate(jobs, "FISCAL-JOBS-PER-1000SF-", use)
            if j is not None:
                rates["jobs_per_1000_sf_by_use"][use] = j
            s = rate(sales, "FISCAL-SALES-PER-SF-", use)
            if s is not None and finite(sf):
                taxable += s * sf
            if lib.get(use, {}).get("revenue", {}).get("type") == "room_revenue":
                rev = lib[use]["revenue"]
                keys = ln.get("units")
                if finite(keys) and finite(rev.get("adr")) and finite(rev.get("occupancy_pct")):
                    rooms += keys * rev["adr"] * 365 * rev["occupancy_pct"] / 100
        parts = [v for v in (totals.get("implied_value_usd"), totals.get("net_sales_revenue_usd")) if finite(v)]
        value = sum(parts) if parts else None          # income uses at value on completion, homes at their sale price
        fphases.append({"id": ph["id"], "construction_cost_usd": totals.get("development_cost_usd"),
                        "building_sf_by_use": sf_by_use, "taxable_sales_usd_yr": taxable or None,
                        "hotel_room_revenue_usd_yr": rooms or None, "assessed_value_usd": value})
        # delivery_year counts from 1 = the first year of the district
        eifd_phases.append({"id": ph["id"], "assessed_value_usd": value, "base_assessed_value_usd": 0,
                            "delivery_year": 1 + int(ph.get("start_offset_years") or 0) + int(a.get("build_years") or 2)})
    impact = F.fiscal_impact(fphases, rates) if fphases else None
    share = inp.num("EIFD-PARTICIPATING-SHARE-PCT")
    eifd = None
    if fphases and rates["property_tax_rate_pct"] is not None and share is not None:
        eifd = F.eifd_increment(eifd_phases, rates["property_tax_rate_pct"], share,
                                years=int(inp.num("EIFD-YEARS") or 30), assessed_growth_pct=inp.num("EIFD-GROWTH-PCT"))
    for what in (impact or {}).get("not_worked_out") or []:
        inp._miss(f"Not worked out: {_words(what)}")
    result = {"impact": impact, "eifd": eifd}
    return result, _formula((impact or {}).get("formula"), (eifd or {}).get("formula"),
                            "Assessed value per phase = the pro forma's implied value on completion plus the sale "
                            "price of homes sold; taxable sales = retail SF x taxable sales per SF; room revenue = keys "
                            "x ADR x 365 x occupancy.")


def t_reconcile(inp, options):
    rows = []
    for rule in inp.rows("reconciliations"):
        r = R.reconcile(inp.c, rule)
        for aid in [rule.get("total")] + list(rule.get("parts") or []):
            if aid:
                inp.num(aid, default=None)
        comps = [{"label": p["id"], "value": p["value"]} for p in r["parts"]] + \
            [{"label": m, "value": None} for m in r["missing"] if m != rule.get("total")]
        check = F.reconcile_program(r["total"], comps, tolerance_abs=rule.get("tolerance"), label=rule.get("label"))
        rows.append({**r, "engine": check})
        if not r["explained"]:
            inp._miss(f"Reconciliation {rule.get('id')} differs by {r['difference']} and has no explanation.")
    if not rows:
        inp._miss("There are no reconciliation rules.")
    return {"reconciliations": rows, "all_explained": all(r["explained"] for r in rows)}, \
        ["Difference = the total's register figure - the sum of its parts; within tolerance counts as equal."]


RUN = {"landvalue": t_landvalue, "proceeds": t_proceeds, "proforma": t_proforma, "strategy": t_strategy,
       "scenarios": t_scenarios, "funding": t_funding, "fiscal": t_fiscal, "reconcile": t_reconcile}


# ---------------------------------------------------------------- what-if and the answer

def apply_overrides(content, body, visible=None, deny=frozenset()):
    """A copy of the content with the body's what-if changes: {"assumptions": {id: number}, "records": {entity:
    [{id, field: value}]}}. `visible` (the audience's filtered content) limits what may be changed to what it sees."""
    out = copy.deepcopy(content)
    changed = []
    ass = (body or {}).get("assumptions") or {}
    if not isinstance(ass, dict):
        raise Problem(400, "bad-request", "assumptions is {id: number}.")
    reg = {a.get("id"): a for a in out["entities"]["assumptions"]}
    seen = None if visible is None else {a.get("id") for a in visible["entities"]["assumptions"]}
    for aid, v in ass.items():
        if not finite(v):
            raise Problem(400, "bad-request", f"The what-if value for {str(aid)[:40]} is not a finite number.")
        if seen is not None and aid not in seen:
            raise Problem(403, "forbidden", f"{str(aid)[:40]} is not a figure your view can change.")
        if aid in reg:
            reg[aid] = {**reg[aid], "value": v, "what_if": True}
            out["entities"]["assumptions"] = [reg.get(a.get("id"), a) for a in out["entities"]["assumptions"]]
        else:
            if aid not in CONVENTIONS and not any(str(aid).startswith(p) for p in PREFIXES):
                raise Problem(400, "bad-request", f"{str(aid)[:40]} is neither in the register nor a compute convention.")
            new = {"id": aid, "label": aid, "value": v, "unit": (CONVENTIONS.get(aid) or ("", "count"))[1] or "count",
                   "status": "Baseline", "provenance": "REQUIRES VALIDATION", "what_if": True}
            out["entities"]["assumptions"].append(new)
            reg[aid] = new
        changed.append(f"assumptions/{aid}")
    recs = (body or {}).get("records") or {}
    if not isinstance(recs, dict):
        raise Problem(400, "bad-request", "records is {entity: [{id, field: value}]}.")
    for entity, rows in recs.items():
        if entity not in ENTITIES or not isinstance(rows, list):
            raise Problem(400, "bad-request", f"“{str(entity)[:40]}” is not a kind of record.")
        have = {r.get("id"): r for r in out["entities"][entity]}
        vis = None if visible is None else {r.get("id"): r for r in visible["entities"][entity]}
        for patch in rows:
            if not isinstance(patch, dict) or patch.get("id") not in have:
                raise Problem(400, "bad-request", f"A what-if {entity} row must name an existing id.")
            if vis is not None and (patch["id"] not in vis or any(
                    k != "id" and ((k in have[patch["id"]] and k not in vis[patch["id"]]) or field_tags(entity, k) & deny)
                    for k in patch)):
                raise Problem(403, "forbidden", f"{entity}/{patch['id']} is not something your view can change.")
            merged, errors = clean_record(entity, {**have[patch["id"]], **patch})
            if errors:
                raise Problem(400, "bad-request", f"{entity}/{patch['id']}: " + "; ".join(errors[:5]))
            merged["what_if"] = True
            if "provenance" in have[patch["id"]]:
                merged["provenance"] = have[patch["id"]]["provenance"]
            out["entities"][entity] = [merged if r.get("id") == patch["id"] else r for r in out["entities"][entity]]
            changed.extend(f"{entity}/{patch['id']}/{k}" for k in patch if k != "id")
    return out, changed


def check_options(tool, options):
    if not isinstance(options, dict):
        raise Problem(400, "bad-request", "options is a set of named values.")
    allowed = OPTIONS.get(tool, {})
    for k, v in options.items():
        if k not in allowed:
            raise Problem(400, "bad-request", f"The {tool} tool has no option “{str(k)[:30]}”.")
        if v not in allowed[k]:
            raise Problem(400, "bad-request", f"{k} is one of: {', '.join(allowed[k])}.")
    return options


def run(tool, content, options=None, reconcile_content=None):
    if tool not in RUN:
        raise Problem(404, "not-found", f"There is no compute tool “{str(tool)[:30]}”. The tools are: {', '.join(TOOLS)}.")
    inp = Inputs(reconcile_content if tool == "reconcile" and reconcile_content is not None else content)
    result, formula = RUN[tool](inp, check_options(tool, options or {}))
    return {"tool": tool, "inputs_used": inp.used, "result": result, "formula": formula, "missing": inp.missing,
            "disclaimer": F.DISCLAIMER}


def filter_answer(answer, audience):
    """Drop the result parts and the inputs an audience may not receive (access.scrub runs after this)."""
    deny = AUDIENCE_DENY.get(audience, AUDIENCE_DENY["city"])
    if not deny:
        return answer
    out = dict(answer)
    tags = RESULT_TAGS.get(answer["tool"], {})
    out["result"] = {k: v for k, v in (answer.get("result") or {}).items() if not (tags.get(k, set()) & deny)}
    out["hidden_parts"] = sorted(k for k in (answer.get("result") or {}) if tags.get(k, set()) & deny)
    out["inputs_used"] = [i for i in answer.get("inputs_used") or [] if not (set(i.get("tags") or []) & deny)]
    words = ("price", "proceeds", "floor", "residual", "rlv", "irr", "yield", "return", "value_usd", "land value",
             "strategy_inputs", "sale plan", "hurdle", "premium", "upside")
    out["missing"] = [m for m in answer.get("missing") or [] if not any(w in m.lower() for w in words)]
    return out
