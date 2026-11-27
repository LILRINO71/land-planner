"""Baseline against a consultant submission (or any two dataset versions): what was added, removed and changed,
with every numeric change above the threshold flagged (FR-54, default plus or minus 10 percent)."""
from .jsonsafe import finite, pct
from .schema import ENTITIES

DEFAULT_THRESHOLD = 10.0


def compare(base, other, threshold_pct=DEFAULT_THRESHOLD):
    try:
        threshold = float(threshold_pct)
    except (TypeError, ValueError):
        threshold = DEFAULT_THRESHOLD
    if not finite(threshold) or threshold < 0:
        threshold = DEFAULT_THRESHOLD
    out, totals = {}, {"flagged": 0, "changed": 0, "added": 0, "removed": 0}
    for name, e in ENTITIES.items():
        a = {r.get("id"): r for r in base["entities"].get(name, [])}
        b = {r.get("id"): r for r in other["entities"].get(name, [])}
        added = sorted(k for k in b if k not in a)
        removed = sorted(k for k in a if k not in b)
        changed = []
        for rid in sorted(k for k in a if k in b):
            for field in e["fields"]:
                x, y = a[rid].get(field), b[rid].get(field)
                if x == y:
                    continue
                row = {"id": rid, "field": field, "base": x, "other": y, "change": None, "change_pct": None,
                       "flagged": False, "label": a[rid].get("label") or b[rid].get("label") or a[rid].get("name")}
                if finite(x) and finite(y):
                    row["change"] = y - x
                    row["change_pct"] = pct(y - x, abs(x)) if x != 0 else None
                    row["flagged"] = (x == 0 and y != 0) or (row["change_pct"] is not None
                                                            and abs(row["change_pct"]) >= threshold)
                else:
                    row["flagged"] = e["fields"][field]["type"] in ("number", "integer")   # appeared or went away
                changed.append(row)
        if added or removed or changed:
            out[name] = {"added": added, "removed": removed, "changed": changed}
        totals["added"] += len(added)
        totals["removed"] += len(removed)
        totals["changed"] += len(changed)
        totals["flagged"] += sum(1 for c in changed if c["flagged"])
    return {"threshold_pct": threshold, "entities": out, **totals}
