"""The assumptions register: every figure on a page traces to one entry (FR-52, FR-53, acceptance "every displayed
figure traces to an assumptions-register entry"), and the checks that say where that is not so yet. Also the
reconciliation rules (FR-19): "these lines should add up to that figure", with the difference and its explanation.
"""
import re

from .jsonsafe import finite, pct
from .schema import ENTITIES

# a figure in words: a dollar amount, a number of three or more digits, or a percent ("Phase 1" is not a figure)
_NUMBER_IN_TEXT = re.compile(r"\$\s?\d|(?<![\w.])\d[\d,]{2,}|(?<![\w.])\d+(\.\d+)?\s?%")


def _index(content, entity):
    return {r.get("id"): r for r in content["entities"].get(entity, [])}


def figure(content, aid):
    """The register entry for an assumption id, or None."""
    return _index(content, "assumptions").get(aid)


def value(content, aid):
    f = figure(content, aid)
    v = f.get("value") if f else None
    return v if finite(v) else None


UNIT_WORDS = {"sf": "SF", "acres": "acres", "units": "units", "keys": "keys", "usd": "", "usd_per_yr": "/yr",
              "usd_per_sf_yr": "/SF/yr", "usd_per_sf_mo": "/SF/mo", "usd_per_sf": "/SF", "usd_per_acre": "/acre",
              "usd_per_unit": "/unit", "usd_per_unit_mo": "/unit/mo", "usd_per_night": "/night", "pct": "%",
              "ratio": "x", "people": "people", "households": "households", "jobs": "jobs", "count": "", "years": "years",
              "months": "months", "sf_per_yr": "SF/yr", "units_per_yr": "units/yr", "miles": "miles", "text": ""}


def _num(v, unit):
    if not finite(v):
        return ""
    money = unit.startswith("usd")
    if unit in ("usd_per_sf_yr", "usd_per_sf_mo", "usd_per_sf"):
        digits = 2                                   # rents are always shown to the cent ($36.00/SF/yr)
    else:
        digits = 2 if money and abs(v) < 1000 and not float(v).is_integer() else (1 if not float(v).is_integer() else 0)
    text = f"{v:,.{digits}f}"
    return ("$" + text) if money else text


def display(entry):
    """The figure in words with its unit: '$36.00/SF/yr', '120 acres', '300,000-400,000 SF'."""
    if not entry:
        return ""
    unit = entry.get("unit") or ""
    word = UNIT_WORDS.get(unit, unit)
    if entry.get("value_text") and not finite(entry.get("value")):
        return str(entry["value_text"])
    if finite(entry.get("value")):
        body = _num(entry["value"], unit)
    elif finite(entry.get("value_low")) and finite(entry.get("value_high")):
        body = f"{_num(entry['value_low'], unit)}-{_num(entry['value_high'], unit)}"
    else:
        return ""
    if unit == "pct":
        return body + "%"
    if unit.startswith("usd"):
        return body + word
    return f"{body} {word}".strip()


def used_by(content, modules, aid):
    """Where an assumption is shown or used: cards, sections, records and reconciliation rules."""
    out = []
    for m in modules or []:
        for c in m.get("cards") or []:
            if aid == c.get("assumption") or aid in (c.get("assumptions") or []):
                out.append({"kind": "card", "module": m.get("id"), "id": c.get("id")})
    for s in content["entities"]["sections"]:
        if aid in (s.get("cites") or []) or any(aid in (i.get("cites") or []) for i in (s.get("items") or [])
                                                if isinstance(i, dict)):
            out.append({"kind": "section", "module": s.get("module"), "id": s.get("id")})
    for name, e in ENTITIES.items():
        if "assumption" in e["fields"]:
            for r in content["entities"][name]:
                if r.get("assumption") == aid:
                    out.append({"kind": "record", "entity": name, "id": r.get("id")})
    for r in content["entities"]["reconciliations"]:
        if aid == r.get("total") or aid in (r.get("parts") or []):
            out.append({"kind": "reconciliation", "id": r.get("id")})
    return out


def _sum_parts(content, rule):
    """(total of the parts, [{id, value}], [missing ids])."""
    parts, missing, total = [], [], 0.0
    if rule.get("parts"):
        for aid in rule["parts"]:
            v = value(content, aid)
            if v is None:
                missing.append(aid)
            else:
                parts.append({"id": aid, "value": v})
                total += v
    elif rule.get("parts_entity") in ENTITIES and rule.get("parts_field"):
        where = rule.get("parts_where") if isinstance(rule.get("parts_where"), dict) else {}
        for r in content["entities"][rule["parts_entity"]]:
            if all(str(r.get(k)) == str(v) for k, v in where.items()):
                v = r.get(rule["parts_field"])
                if finite(v):
                    parts.append({"id": r.get("id"), "value": v})
                    total += v
    return total, parts, missing


def reconcile(content, rule):
    total_v = value(content, rule.get("total"))
    parts_v, parts, missing = _sum_parts(content, rule)
    if total_v is None:
        missing = [rule.get("total")] + missing
    diff = None if total_v is None else total_v - parts_v
    tol = rule.get("tolerance") if finite(rule.get("tolerance")) else 0.0
    within = diff is not None and abs(diff) <= tol
    explanation = str(rule.get("explanation") or "")
    return {"id": rule.get("id"), "label": rule.get("label"), "total": total_v, "total_id": rule.get("total"),
            "parts_total": parts_v, "difference": diff, "difference_pct": pct(diff, total_v) if diff is not None else None,
            "within_tolerance": within, "explanation": explanation, "explained": within or bool(explanation.strip()),
            "parts": parts, "missing": [m for m in missing if m]}


def reconciliations(content):
    return [reconcile(content, r) for r in content["entities"]["reconciliations"]]


def checks(content, modules, sensitive_untagged=None):
    """Every way a figure might be on a page without tracing to the register."""
    reg = _index(content, "assumptions")
    unregistered, uncited, superseded = [], [], []

    def need(aid, where):
        if not aid:
            return
        if aid not in reg:
            unregistered.append({"assumption": aid, **where})
        elif reg[aid].get("status") == "Superseded" or reg[aid].get("provenance") == "HISTORICAL / SUPERSEDED":
            superseded.append({"assumption": aid, **where})

    for m in modules or []:
        for c in m.get("cards") or []:
            ids = [c.get("assumption")] if c.get("assumption") else list(c.get("assumptions") or [])
            if not ids:
                unregistered.append({"assumption": None, "kind": "card", "module": m.get("id"), "id": c.get("id"),
                                     "why": "the card names no assumption"})
            for aid in ids:
                need(aid, {"kind": "card", "module": m.get("id"), "id": c.get("id")})
    for s in content["entities"]["sections"]:
        for aid in s.get("cites") or []:
            need(aid, {"kind": "section", "module": s.get("module"), "id": s.get("id")})
        for i, item in enumerate(s.get("items") or []):
            if isinstance(item, dict):
                for aid in item.get("cites") or []:
                    need(aid, {"kind": "section item", "module": s.get("module"), "id": f"{s.get('id')}#{i + 1}"})
                if not item.get("cites") and _NUMBER_IN_TEXT.search(str(item.get("answer") or "")):
                    uncited.append({"kind": "section item", "module": s.get("module"), "id": f"{s.get('id')}#{i + 1}",
                                    "why": "the answer holds a figure but cites no assumption"})
        has_figures = _NUMBER_IN_TEXT.search(str(s.get("body") or "")) or any(
            finite(c) for row in (s.get("rows") or []) if isinstance(row, list) for c in row)
        if has_figures and not s.get("cites") and s.get("kind") in ("narrative", "table", "banner"):
            uncited.append({"kind": "section", "module": s.get("module"), "id": s.get("id"),
                            "why": "it holds figures but cites no assumption"})
        if s.get("ai_assisted") and not s.get("cites"):
            uncited.append({"kind": "section", "module": s.get("module"), "id": s.get("id"),
                            "why": "AI-assisted text must cite the register entries it uses (NFR-09)"})
    for name, e in ENTITIES.items():
        if "assumption" in e["fields"]:
            for r in content["entities"][name]:
                need(r.get("assumption"), {"kind": "record", "entity": name, "id": r.get("id")})
    for r in content["entities"]["reconciliations"]:
        for aid in [r.get("total")] + list(r.get("parts") or []):
            need(aid, {"kind": "reconciliation", "id": r.get("id")})
    conflicts = [{"id": a.get("id"), "label": a.get("label"), "conflict_note": a.get("conflict_note", "")}
                 for a in content["entities"]["assumptions"] if a.get("conflict")]
    recs = reconciliations(content)
    return {"unregistered": unregistered, "uncited": uncited, "superseded_in_use": superseded,
            "conflicts": conflicts, "reconciliations": recs,
            "unexplained_reconciliations": [r["id"] for r in recs if not r["explained"]],
            "untagged_sensitive": sensitive_untagged or [],
            "ok": not unregistered and not uncited and not superseded and all(r["explained"] for r in recs)}
