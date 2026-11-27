"""Checking one record against the schema: types, units, ranges, choices and required fields. The same checks run
on an edit from a screen and on every row of an import, so a figure cannot get in one way that the other refuses.

clean_record(entity, record) -> (clean record, [errors in plain words])
"""
import datetime
import json
import math
import re

from . import ID
from .schema import ENTITIES

MAX_TEXT = 20000
_DATE = re.compile(r"\d{4}(-\d{2}(-\d{2})?)?")
_TRUE, _FALSE = {"true", "yes", "y", "1", "x"}, {"false", "no", "n", "0", ""}


class Bad(ValueError):
    pass


def _number(value, field, unit):
    if isinstance(value, bool):
        raise Bad("is true/false, not a number")
    if isinstance(value, (int, float)):
        out = float(value)
    else:
        text = str(value).strip()
        if unit == "pct" or text.endswith("%"):
            text = text.rstrip("%").strip()
        text = text.replace(",", "").replace("$", "").replace(" ", "")
        neg = text.startswith("(") and text.endswith(")")
        text = text.strip("()")
        if not re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?", text):
            raise Bad(f"“{str(value)[:30]}” is not a number")
        out = -float(text) if neg else float(text)
    if not math.isfinite(out):
        raise Bad("is not a finite number")
    lo, hi = field.get("min"), field.get("max")
    if lo is not None and out < lo:
        raise Bad(f"{_show(out)} is below the lowest allowed value, {_show(lo)}")
    if hi is not None and out > hi:
        raise Bad(f"{_show(out)} is above the highest allowed value, {_show(hi)}")
    return out


def _show(x):
    return f"{int(x):,}" if float(x).is_integer() else f"{x:,}"


def _value(value, field, name):
    kind = field["type"]
    if kind == "text":
        text = str(value).strip() if not isinstance(value, float) or not value.is_integer() else str(int(value))
        if len(text) > MAX_TEXT:
            raise Bad(f"is longer than {MAX_TEXT:,} characters")
        return text
    if kind == "number":
        return _number(value, field, field.get("unit"))
    if kind == "integer":
        out = _number(value, field, field.get("unit"))
        if not out.is_integer():
            raise Bad(f"{_show(out)} is not a whole number")
        return int(out)
    if kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise Bad(f"“{str(value)[:20]}” is not yes or no")
    if kind == "date":
        if isinstance(value, (datetime.date, datetime.datetime)):
            return value.isoformat()[:10]
        if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value).is_integer() \
                and 1900 <= value <= 2200:
            return str(int(value))
        text = str(value).strip()[:10]
        if not _DATE.fullmatch(text):
            raise Bad(f"“{str(value)[:20]}” is not a date (write 2026-11-26, 2026-11 or 2026)")
        try:
            if len(text) == 10:
                datetime.date.fromisoformat(text)
            elif len(text) == 7 and not 1 <= int(text[5:]) <= 12:
                raise ValueError
        except ValueError:
            raise Bad(f"“{text}” is not a real date") from None
        return text
    if kind == "choice":
        text = str(value).strip()
        for c in field["choices"]:
            if text.lower() == c.lower():
                return c
        shown = ", ".join(field["choices"]) if len(field["choices"]) <= 12 else "the units list"
        raise Bad(f"“{text[:30]}” is not one of: {shown}")
    if kind in ("list", "refs"):
        items = value if isinstance(value, list) else [x for x in re.split(r"[;\n]", str(value))]
        items = [str(x).strip() for x in items if str(x).strip()]
        if kind == "refs":
            for x in items:
                if not ID.fullmatch(x):
                    raise Bad(f"“{x[:30]}” is not an id")
        if len(items) > 500:
            raise Bad("has more than 500 items")
        return items
    if kind == "json":
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                raise Bad("is not readable JSON") from None
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError):
            raise Bad("holds something that is not plain data, or a number that is not finite") from None
        if len(json.dumps(value)) > 500000:
            raise Bad("is too large")
        return value
    raise Bad("has a type this app does not know")


def empty(value):
    return value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, list) and not value)


def natural_id(entity_name, record):
    """An id made from the entity's natural key, for rows that came without one."""
    e = ENTITIES[entity_name]
    parts = [str(record.get(k) or "").strip() for k in e["natural_key"]]
    if not any(parts):
        return None
    text = re.sub(r"[^A-Za-z0-9._:\-]+", "-", "-".join(p for p in parts if p)).strip("-")
    return text[:64] or None


def clean_record(entity_name, record):
    """(clean record, errors). Unknown keys are dropped (they are reported by the importer, not stored)."""
    e = ENTITIES.get(entity_name)
    if e is None:
        return None, [f"“{entity_name}” is not a kind of record this app keeps"]
    if not isinstance(record, dict):
        return None, ["a record must be a set of named fields"]
    out, errors = {}, []
    for name, field in e["fields"].items():
        raw = record.get(name)
        if empty(raw):
            if field.get("default") is not None:
                out[name] = field["default"]
            continue
        try:
            out[name] = _value(raw, field, name)
        except Bad as bad:
            errors.append(f"{name}: {bad}")
    if "id" not in out and "id" not in [x.split(":")[0] for x in errors]:
        made = out.get("apn") if entity_name == "parcels" and out.get("apn") else natural_id(entity_name, out)
        if made:
            out["id"] = made
    if "id" in out and not ID.fullmatch(out["id"]):
        errors.append(f"id: “{out['id'][:30]}” is not usable (letters, digits, “.”, “_”, “:” and “-”, up to 64)")
    for name, field in e["fields"].items():
        if field.get("required") and name not in out and not any(x.startswith(name + ":") for x in errors):
            errors.append(f"{name}: is required")
    one_of = e.get("require_one_of")
    if one_of and not any(k in out for k in one_of):
        errors.append(f"needs one of: {', '.join(one_of)}")
    for lo, hi in (("value_low", "value_high"),):
        if lo in out and hi in out and out[lo] > out[hi]:
            errors.append(f"{lo} is above {hi}")
        elif (lo in out) != (hi in out) and lo in e["fields"]:
            errors.append(f"a range needs both {lo} and {hi}")
    return out, errors
