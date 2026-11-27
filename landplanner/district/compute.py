"""Computed results: a dataset's content fed into the finance engine (finance.py, docs/district-finance.md) and
answered as {inputs_used, result, formula, missing}. The conventions that say where each input comes from (which
entity, which assumption id) are in docs/district-data-contract.md, section "Compute"; they are the tables here.

Nothing is saved: a what-if (POST) changes a copy of the content in memory. The answer is filtered for the caller's
audience on the way out by api.py (filter_answer below, then access.scrub).
"""
import copy
import re

from . import Problem
from . import finance as F
from . import register as R
from .jsonsafe import finite
from .schema import AUDIENCE_DENY, ENTITIES, field_tags, row_tags
from .validate import clean_record

TOOLS = ("landvalue", "proceeds", "proforma", "strategy", "scenarios", "funding", "fiscal", "reconcile")

# What each part of a tool's result is about. An audience that denies a tag never receives that part.
RESULT_TAGS = {
    "landvalue": {"by_parcel": {"rlv_parcel"}, "pricing_tiers": {"price_floor", "disposition"},
                  "blocks": {"price_floor", "disposition"}, "comparison": {"rlv_parcel", "disposition"}},
    "proceeds": {"waterfall": {"disposition"}, "capital_plan": {"disposition"}, "targets": {"disposition"},
                 "stated_plan": {"disposition"}, "by_basis": {"disposition"}},
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

BASIS = ("stated", "residual")
OPTIONS = {"landvalue": {"basis": BASIS}, "strategy": {"basis": BASIS},
           "proceeds": {"basis": BASIS,
                        "price_basis": ("target_market", "minimum_recommended", "upside_stretch", "economic_cost_floor")},
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


_SNAKE = re.compile(r"(?<![A-Za-z0-9])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![A-Za-z0-9])")
_ALONE_IN_BRACKETS = re.compile(r"\s*\(\s*" + _SNAKE.pattern + r"\s*\)")
_WORD_FOR = {"pct": "percent", "usd": "dollars", "sf": "square feet", "ac": "acres", "apns": "parcel numbers"}


def _field_words():
    """{field name: plain words} from the schema's field descriptions, where a short plain one exists."""
    out = {}
    for ent in ENTITIES.values():
        for name, f in ent["fields"].items():
            d = str(f.get("desc") or "").strip()
            if d and not d.lower().startswith(("compute:", "the id of", "short id")) and len(d) <= 48 and "," not in d:
                out.setdefault(name, d[:1].lower() + d[1:])
    return out


def plain(text, _words_for={}):
    """A sentence without raw field names: a name standing alone in brackets is dropped (the words before it already
    say it); any other snake_case name is written in plain words (the schema's description of the field when it
    has a short one, else the name with spaces)."""
    if not isinstance(text, str):
        return text
    if not _words_for:
        _words_for.update(_field_words())
    text = _ALONE_IN_BRACKETS.sub("", text)

    def say(m):
        name = m.group(0)
        if name in _words_for:
            return _words_for[name]
        return " ".join(_WORD_FOR.get(w, w) for w in name.split("_"))
    return _SNAKE.sub(say, text)


def _plain_whys(obj):
    """The same, for every `why` sentence anywhere inside a result."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "why" and isinstance(v, str):
                obj[k] = plain(v)
            else:
                _plain_whys(v)
    elif isinstance(obj, list):
        for v in obj:
            _plain_whys(v)


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

SF_PER_AC = 43560.0
_ID_IN_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,62}[A-Za-z0-9]")


def basis_for(inp, options):
    """('stated' or 'residual', whether stated prices exist). Stated: blocks' $/SF or parcels' target prices."""
    stated = bool(inp.rows("blocks")) or any(finite(p.get("target_price")) for p in inp.rows("parcels"))
    asked = options.get("basis")
    if asked == "stated" and not stated:
        inp._miss("No block has a stated price and no parcel has a target_price, so the residual basis was used.")
        return "residual", stated
    return asked or ("stated" if stated else "residual"), stated


def _cite(inp, entity, row):
    """Assumptions a row names in its cites, or by id in its note: they count as inputs used."""
    ids = list(row.get("cites") or [])
    ids += [w for w in _ID_IN_TEXT.findall(str(row.get("note") or "")) if w in inp.reg]
    for aid in dict.fromkeys(ids):
        if aid in inp.reg:
            inp.num(aid, default=None)
        else:
            inp._miss(f"{entity} {row.get('id')} cites {aid}, which is not in the register.")


def block_price(inp, b):
    """A block's stated price: net acres x 43,560 x $/SF (the middle of the range when only a range is given)."""
    net = inp.field("blocks", b, "net_acres")
    lo, mid, hi = (inp.field("blocks", b, k) for k in ("price_per_sf_low", "price_per_sf", "price_per_sf_high"))
    _cite(inp, "Block", b)
    how = "stated price per SF"
    if not finite(mid) and finite(lo) and finite(hi):
        mid, how = (lo + hi) / 2.0, "the middle of the stated range"
    sf = net * SF_PER_AC if finite(net) else None
    if sf is None or not finite(mid):
        inp._miss(f"Block {b.get('id')} has no stated price per SF (or no net acres), so it is not priced.")
    usd = (lambda per: round(per * sf, 2) if finite(per) and sf is not None else None)
    return {"id": b.get("id"), "name": b.get("name"), "net_acres": net, "net_sf": sf, "price_per_sf": mid,
            "gross_price_usd": usd(mid), "low_usd": usd(lo), "high_usd": usd(hi), "price_from": how,
            "phase": b.get("phase"), "close_month": inp.field("blocks", b, "close_month"), "intent": b.get("intent"),
            "core": bool(b.get("core")), "apns": list(b.get("apns") or [])}


def _residual_per_net_ac(by_parcel):
    """{parcel id or APN: (base residual per net acre, net acres)} from residual_land_value_by_parcel."""
    out = {}
    for r in (by_parcel or {}).get("parcels", []):
        chosen = ((r.get("uses") or {}).get(r.get("totalled_use")) or {}).get("base") or {}
        per = chosen.get("rlv_per_net_ac_usd")
        if finite(per):
            out[r.get("id")] = (per, r.get("net_ac") or 0.0)
    return out


def _block_residual(inp, block, per_ac):
    """Residual estimate for a block: its net acres x the acre-weighted residual per net acre of its parcels."""
    apn_to_id = {p.get("apn"): p.get("id") for p in inp.rows("parcels")}
    found = [per_ac[k] for k in (apn_to_id.get(a, a) for a in block["apns"]) if k in per_ac]
    weight = sum(w for _, w in found)
    if not found or not weight or not finite(block.get("net_acres")):
        return None
    return round(block["net_acres"] * sum(v * w for v, w in found) / weight, 2)


def _diff(stated, residual):
    if not finite(stated) or not finite(residual):
        return {"difference_usd": None, "difference_pct": None}
    d = stated - residual
    return {"difference_usd": round(d, 2), "difference_pct": round(d / abs(residual) * 100, 4) if residual else None}


def t_landvalue(inp, options):
    basis, has_stated = basis_for(inp, options)
    lib = inp.library() if inp.rows("land_uses") or not has_stated else {}
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
        stated = inp.field("parcels", p, "target_price") if basis == "stated" else None
        parcel = {"id": p.get("id"), "gross_ac": p.get("acres"), "net_ac": r.get("net_ac") or p.get("net_acres"),
                  "cost_items": costs.get(p.get("id"), {}),
                  "strategic_score": inp.field("parcels", p, "strategic_score")}
        tiers.append({"parcel": p.get("id"), "use": r.get("totalled_use"), "basis": "stated" if stated else "residual",
                      "residual_base_usd": base,
                      **F.pricing_tiers(parcel, base, high, sponsor_hurdle_pct=hurdle, strategic_premium_pct=premium,
                                        target_pct_of_rlv=target_pct, upside_pct=upside,
                                        target_price_usd=stated if finite(stated) else None)})
    per_ac = _residual_per_net_ac(by_parcel)
    blocks = []
    for b in inp.rows("blocks"):
        row = block_price(inp, b)
        row["residual_estimate_usd"] = _block_residual(inp, row, per_ac)
        row.update(_diff(row["gross_price_usd"], row["residual_estimate_usd"]))
        blocks.append(row)
    result = {"basis_used": basis, "by_use": by_use, "by_parcel": by_parcel, "pricing_tiers": tiers}
    if blocks:
        result["blocks"] = blocks
    comparison = None
    if has_stated and by_parcel:
        units = []
        for b in blocks:
            units.append({"kind": "block", "id": b["id"], "stated_usd": b["gross_price_usd"],
                          "residual_usd": b["residual_estimate_usd"], **_diff(b["gross_price_usd"],
                                                                               b["residual_estimate_usd"])})
        for tr in tiers:
            p = next((x for x in inp.rows("parcels") if x.get("id") == tr["parcel"]), {})
            if finite(p.get("target_price")):
                units.append({"kind": "parcel", "id": tr["parcel"], "stated_usd": p["target_price"],
                              "residual_usd": tr["residual_base_usd"], **_diff(p["target_price"], tr["residual_base_usd"])})
        priced = [u for u in units if finite(u["stated_usd"]) and finite(u["residual_usd"])]
        st, rs = sum(u["stated_usd"] for u in priced), sum(u["residual_usd"] for u in priced)
        comparison = {"units": units, "stated_total_usd": round(st, 2), "residual_total_usd": round(rs, 2),
                      **_diff(st, rs), "compared": len(priced), "not_compared": len(units) - len(priced),
                      "note": "Totals add only the units priced both ways."}
        result["comparison"] = comparison
    formula = _formula((by_use or {}).get("formula"), "Pricing tiers: cost floor = the parcel's cost items; minimum = "
                       "floor x (1 + sponsor hurdle) + strategic premium; target = the parcel's stated target_price "
                       "(stated basis) or base residual x target percent (residual basis); upside = high residual.",
                       "Block stated price = net acres x 43,560 x price per SF (the middle of the range when only "
                       "a range is stated). Residual estimate of a block = its net acres x the acre-weighted base "
                       "residual per net acre of the parcels it lies in." if blocks else None)
    return result, formula


def _price_basis(inp, tiers, basis):
    out = {}
    for t in tiers:
        price = ((t.get("tiers") or {}).get(basis) or {}).get("price_usd")
        out[t.get("parcel")] = price
    return out


def _sale_parcels(inp, prices, say=True):
    stubs = {}
    for it in inp.rows("infrastructure"):
        if it.get("parcel"):
            stubs.setdefault(it["parcel"], []).append({"name": it.get("item"),
                                                      "amount_usd": inp.field("infrastructure", it, "cost_usd")})
    out = []
    for p in inp.rows("parcels"):
        if prices.get(p.get("id")) is None:
            if say:
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
                    "do_not_sell_until_month": inp.field("parcels", p, "do_not_sell_until_month"),
                    "phase": p.get("phase"), "intent": {"ground lease": "ground_lease"}.get(p.get("hold_sell"),
                                                                                           p.get("hold_sell"))})
    return out


def _sale_blocks(inp, priced):
    """Blocks as sale pieces. A stub that is not known stays not known (the net is then an upper bound)."""
    out = []
    for b, row in priced:
        if not finite(row["gross_price_usd"]):
            continue
        stub = inp.field("blocks", b, "stub_cost_usd")
        out.append({"id": b.get("id"), "name": b.get("name"), "gross_price_usd": row["gross_price_usd"],
                    "net_ac": row["net_acres"], "infrastructure_stubs": [{"name": "stub", "amount_usd": stub}],
                    "strategic_score": inp.field("blocks", b, "strategic_score"), "close_month": row["close_month"],
                    "critical": bool(b.get("core")), "must_keep": False, "phase": b.get("phase"),
                    "intent": b.get("intent")})
    return out


def sale_units(inp, basis, price_basis="target_market", say=True):
    """(units, kind): blocks when the dataset has them and the basis is stated, else parcels. `say` False keeps the
    parcels left out of the plan quiet (a side calculation while the plan itself runs on blocks)."""
    if basis == "stated" and inp.rows("blocks"):
        priced = [(b, block_price(inp, b)) for b in inp.rows("blocks")]
        return _sale_blocks(inp, priced), "blocks"
    lv, _ = t_landvalue(inp, {"basis": basis})
    tier = "target_market" if basis == "stated" else price_basis
    return _sale_parcels(inp, _price_basis(inp, lv["pricing_tiers"], tier), say), "parcels"


def _rates(inp):
    return {"brokerage_pct": inp.num("FIN-BROKERAGE-PCT"), "closing_cost_pct": inp.num("FIN-CLOSING-PCT"),
            "transfer_tax_pct": inp.num("FIN-TRANSFER-TAX-PCT"), "recording_fee_usd": inp.num("FIN-RECORDING-FEE-USD")}


def _targets(inp):
    rows = sorted(inp.rows("capital_targets"), key=lambda x: x.get("month") or 0)
    out, running = [], 0.0
    cumulative = all(t.get("cumulative", True) is not False for t in rows)
    for t in rows:
        amount = inp.field("capital_targets", t, "amount_usd")
        running = amount if cumulative else running + (amount or 0)
        out.append({"label": t.get("label"), "month": inp.field("capital_targets", t, "month"), "amount_usd": amount,
                    "cumulative_target_usd": running})
    return out, cumulative


def stated_plan(inp, units, waterfall, targets):
    """The plan as stated: the units whose intent is sell, by phase and cumulative by close month, against the
    capital targets. Kept units (hold, JV, ground lease, hold and develop) are counted as kept acres."""
    net = {w.get("id"): w for w in (waterfall or {}).get("parcels", [])}
    sold = [u for u in units if u.get("intent") == "sell"]
    kept = [u for u in units if u.get("intent") != "sell"]
    by_phase, months, upper = {}, {}, False
    for u in sold:
        w = net.get(u["id"]) or {}
        n, g = w.get("net_cash_proceeds_usd"), u["gross_price_usd"]
        upper = upper or bool(w.get("net_proceeds_is_upper_bound"))
        ph = by_phase.setdefault(str(u.get("phase") or "none"), {"phase": u.get("phase"), "units": [], "net_acres": 0.0,
                                                                  "gross_usd": 0.0, "net_usd": 0.0})
        ph["units"].append(u["id"])
        ph["net_acres"] += float(u.get("net_ac") or 0)
        ph["gross_usd"] += g
        ph["net_usd"] += n or 0.0
        if finite(u.get("close_month")):
            m = months.setdefault(int(u["close_month"]), {"month": int(u["close_month"]), "units": [], "gross_usd": 0.0,
                                                           "net_usd": 0.0})
            m["units"].append(u["id"])
            m["gross_usd"] += g
            m["net_usd"] += n or 0.0
        else:
            inp._miss(f"{u['id']} has no close_month, so it is left out of the timeline.")
    timeline, cg, cn = [], 0.0, 0.0
    for m in sorted(months):
        cg += months[m]["gross_usd"]
        cn += months[m]["net_usd"]
        timeline.append({**months[m], "cumulative_gross_usd": round(cg, 2), "cumulative_net_usd": round(cn, 2)})
    against = []
    for tg in targets:
        upto = [r for r in timeline if r["month"] <= (tg["month"] or 0)]
        got = upto[-1]["cumulative_net_usd"] if upto else 0.0
        gross = upto[-1]["cumulative_gross_usd"] if upto else 0.0
        want = tg["cumulative_target_usd"]
        against.append({**tg, "cumulative_gross_usd": gross, "cumulative_net_usd": got,
                        "met": None if want is None else got >= want,
                        "shortfall_usd": None if want is None else round(max(0.0, want - got), 2),
                        "net_is_upper_bound": upper})
    return {"sold": [u["id"] for u in sold], "kept": [u["id"] for u in kept],
            "net_acres_sold": round(sum(float(u.get("net_ac") or 0) for u in sold), 4),
            "net_acres_kept": round(sum(float(u.get("net_ac") or 0) for u in kept), 4),
            "gross_usd": round(sum(u["gross_price_usd"] for u in sold), 2),
            "net_usd": round(sum((net.get(u["id"]) or {}).get("net_cash_proceeds_usd") or 0.0 for u in sold), 2),
            "net_is_upper_bound": upper,
            "unknown_stubs": sum(1 for u in sold for s in u.get("infrastructure_stubs") or [] if s.get("amount_usd") is None),
            "by_phase": [{**v, "net_acres": round(v["net_acres"], 4), "gross_usd": round(v["gross_usd"], 2),
                          "net_usd": round(v["net_usd"], 2)} for v in by_phase.values()],
            "by_close_month": timeline, "against_targets": against}


def t_proceeds(inp, options):
    basis, has_stated = basis_for(inp, options)
    price_basis = options.get("price_basis") or "target_market"
    rates = _rates(inp)
    units, kind = sale_units(inp, basis, price_basis)
    waterfall = F.waterfall_for_parcels(units, **rates) if units else None
    targets, cumulative = _targets(inp)
    if not targets:
        inp._miss("There are no capital_targets (cash needed by month), so the capital target solver was not run.")
    plan = F.solve_capital_targets(units, [{"month": t["month"], "amount_usd": t["amount_usd"]} for t in targets],
                                   targets_are_cumulative=cumulative,
                                   critical_threshold=inp.num("FIN-CRITICAL-THRESHOLD"), **rates) \
        if units and targets else None
    result = {"basis_used": basis, "sold_as": kind, "price_basis": price_basis if basis == "residual" else "stated",
              "waterfall": waterfall, "stated_plan": stated_plan(inp, units, waterfall, targets),
              "capital_plan": plan, "targets": targets}
    if has_stated and inp.rows("land_uses"):
        other = "residual" if basis == "stated" else "stated"
        o_units, o_kind = sale_units(inp, other, price_basis, say=kind != "blocks")
        o_fall = F.waterfall_for_parcels(o_units, **rates) if o_units else {}
        here = {"basis": basis, "sold_as": kind, "gross_usd": (waterfall or {}).get("gross_total_usd"),
                "net_usd": (waterfall or {}).get("net_total_usd")}
        there = {"basis": other, "sold_as": o_kind, "gross_usd": o_fall.get("gross_total_usd"),
                 "net_usd": o_fall.get("net_total_usd")}
        st, rs = (here, there) if basis == "stated" else (there, here)
        result["by_basis"] = {"stated": st, "residual": rs, **_diff(st["gross_usd"], rs["gross_usd"]),
                              "note": "Gross totals on each basis; the difference is stated minus residual."}
    what = "each block's stated price (net acres x 43,560 x price per SF)" if kind == "blocks" else (
        "each parcel's stated target_price" if basis == "stated" else
        "each parcel's " + price_basis.replace("_", " ") + " price from the landvalue tool")
    return result, _formula(f"Gross price = {what}.", (waterfall or {}).get("formula"),
                            "Stated plan: the pieces whose intent is sell, added up by phase and by close month "
                            "against the capital targets; a stub not known leaves the net an upper bound.",
                            (plan or {}).get("formula"))


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
    basis, _ = basis_for(inp, options)
    assumptions = {"discount_rate_pct": inp.num("STR-DISCOUNT-RATE-PCT"),
                   "appreciation_pct": inp.num("STR-APPRECIATION-PCT"),
                   "sale_cost_pct": inp.num("STR-SALE-COST-PCT"),
                   "critical_threshold": inp.num("FIN-CRITICAL-THRESHOLD")}
    lv = None
    if basis == "residual" or not inp.rows("blocks"):
        lv, _ = t_landvalue(inp, {"basis": basis})
    rows = []
    if inp.rows("blocks"):
        if lv is None:
            per_ac = {}
        else:
            per_ac = _residual_per_net_ac(lv.get("by_parcel"))
        for b in inp.rows("blocks"):
            priced = block_price(inp, b)
            value = priced["gross_price_usd"] if basis == "stated" else _block_residual(inp, priced, per_ac)
            row = {"id": b.get("id"), "name": b.get("name"), "net_ac": priced["net_acres"], "land_value_usd": value,
                   "strategic_score": inp.field("blocks", b, "strategic_score"), "critical": bool(b.get("core")),
                   "must_keep": False}
            extra = inp.field("blocks", b, "strategy_inputs") or {}
            if isinstance(extra, dict):
                row.update(copy.deepcopy(extra))
            if value is None:
                inp._miss(f"Block {b.get('id')} has no value on the {basis} basis, so its strategies cannot be compared.")
            rows.append(row)
        kind = "blocks"
    else:
        tiers = {t["parcel"]: t for t in (lv or {}).get("pricing_tiers", [])}
        for p in inp.rows("parcels"):
            value = inp.field("parcels", p, "land_value_usd")
            if value is None and basis == "stated":
                value = inp.field("parcels", p, "target_price")
            if value is None and basis == "residual":
                value = (tiers.get(p.get("id")) or {}).get("residual_base_usd")
            row = {"id": p.get("id"), "name": p.get("label"), "net_ac": p.get("net_acres") or p.get("acres"),
                   "land_value_usd": value, "strategic_score": inp.field("parcels", p, "strategic_score"),
                   "critical": bool(p.get("critical")), "must_keep": bool(p.get("must_keep")),
                   "do_not_sell_until_month": inp.field("parcels", p, "do_not_sell_until_month")}
            if p.get("strategic_scores"):
                row["strategic_scores"] = inp.field("parcels", p, "strategic_scores")
            extra = inp.field("parcels", p, "strategy_inputs") or {}
            if isinstance(extra, dict):
                row.update(copy.deepcopy(extra))
            if row["land_value_usd"] is None:
                inp._miss(f"Parcel {p.get('id')} has no land value, so its strategies cannot be compared.")
            rows.append(row)
        kind = "parcels"
    parcels = rows
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
    result = {"basis_used": basis, "decided_for": kind, "decisions": decisions, "conflicts": conflicts,
              "retained_value": retained, "paced_releases": paced, "retained_parcels": [p["id"] for p in kept]}
    return result, _formula(f"Land value of each {kind[:-1]} = " + (
        "its stated price" if basis == "stated" else "its residual land value") + ".",
        (decisions or {}).get("formula"), (retained or {}).get("formula"), (paced or {}).get("formula"))


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
    a = inp.pro_forma_assumptions()
    base_year = a.get("base_year")
    years = sorted({int(i["due_period"]) for i in items if finite(i.get("due_period"))})
    proceeds = {}
    basis, _ = basis_for(inp, {})
    units, _kind = sale_units(inp, basis)
    selling = [u for u in units if u.get("intent") == "sell"] if any(u.get("intent") for u in units) else units
    if base_year and selling:
        fall = {w.get("id"): w for w in F.waterfall_for_parcels(selling, **_rates(inp)).get("parcels", [])}
        for u in selling:
            net = (fall.get(u["id"]) or {}).get("net_cash_proceeds_usd")
            if finite(u.get("close_month")) and finite(net):
                y = int(base_year + (u["close_month"] - 1) // 12)
                proceeds[y] = proceeds.get(y, 0.0) + net
                years.append(y)
    periods = sorted(set(years))
    gap = F.infrastructure_funding_gap(items, periods, proceeds, period_unit="year") if items and periods else None
    if not periods:
        inp._miss("No infrastructure item has a due year, so the funding gap cannot be laid out by period.")
    result = {"register": register, "funding_gap": gap, "unknown_cost_items": sum(1 for i in items if i["cost_usd"] is None)}
    return result, _formula((register or {}).get("formula"), (gap or {}).get("formula"),
                            "Land sale proceeds by year: each piece sold (blocks with intent sell, else parcels) "
                            "through the gross-to-net waterfall, in the year its close_month falls.")


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
    _plain_whys(result)
    missing = list(dict.fromkeys(plain(m) for m in inp.missing))
    return {"tool": tool, "inputs_used": inp.used, "result": result, "formula": formula, "missing": missing,
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
