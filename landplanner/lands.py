"""Filtering, sorting and summing up a city's large parcels. Plain functions on lists of parcel rows: no network."""
import re

def counted_acres(row):
    """The size a parcel counts as everywhere (sorting, filtering, "largest", the total): its recorded acres, or,
    when the recorded size contradicts its own outline (the row then carries "outline_acres"), what the outline
    measures. One rule, so the city card and the list always agree."""
    measured = row.get("outline_acres")
    return measured if measured is not None else row.get("acres")


SORT_KEYS = {
    "acres": counted_acres,
    "apn": lambda r: r.get("apn"),
    "zoning": lambda r: (r.get("zoning") or "").upper() or None,
    "vacant": lambda r: 1 if r.get("looks_vacant") else 0,
    "land_value": lambda r: r.get("assessed_land_usd"),
}


def digits(text):
    return "".join(c for c in str(text or "") if c.isdigit())


def _words(text):
    """Lower-case words with every mark that is not a letter or a digit taken out: "Garbani, Menifee" -> "garbani menifee"."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", str(text or "").lower()).split())


def is_number_search(text):
    """A search is a parcel number only when it is nothing but digits, spaces and dashes."""
    return bool(re.fullmatch(r"[\d\s-]*", text)) and any(c.isdigit() for c in text)


def row_text(row):
    """What a list row shows about a parcel, as one run of words for searching: the parcel number, the street
    address, the recorded map (as "Map TR 37668", the way the list writes it), the zone and its name."""
    sub = str(row.get("subdivision") or "")
    return _words(" ".join([str(row.get("apn_formatted") or ""), str(row.get("apn") or ""), str(row.get("address") or ""),
                            ("Map " + sub) if sub else "", str(row.get("zoning") or ""), str(row.get("zoning_name") or "")]))


def zone_parts(code):
    """The single zones in a zoning value: "LDR - 1 & RM" -> ["LDR-1", "RM"]. The city writes some codes with
    spaces around the dash and some without; they are the same zone."""
    return [re.sub(r"\s*-\s*", "-", part.strip()) for part in str(code or "").split("&") if part.strip()]


def zone_name(code, names):
    """A zoning value in words, from the city's own table of names. Unknown codes are shown as they are."""
    parts = zone_parts(code)
    if not parts or parts == ["(none)"]:
        return "No zoning listed"
    return " + ".join(names.get(p, p) for p in parts)


def filter_parcels(rows, min_acres=None, max_acres=None, zoning="", kind="", vacant=False, q=""):
    """Rows that pass every filter that is set.
    zoning: one zone code; a parcel with several zones passes when any of them is that zone.
    kind:   a zoning family id (row["zoning_kind"]).
    q:      a parcel number (part of it, when the text is only digits, spaces and dashes), or else words: every word
            must be found in the row's own text (address, recorded map, zone and its name), in any order, with
            punctuation ignored."""
    want_zone = (zone_parts(zoning) or [""])[0].upper()
    text = str(q or "").strip()
    by_number = is_number_search(text)
    number = digits(text) if by_number else ""
    words = [] if by_number else _words(text).split()
    out = []
    for r in rows:
        acres = counted_acres(r)
        if min_acres is not None and (acres is None or acres < min_acres):
            continue
        if max_acres is not None and (acres is None or acres > max_acres):
            continue
        if want_zone and want_zone not in [p.upper() for p in zone_parts(r.get("zoning"))]:
            continue
        if kind and r.get("zoning_kind") != kind:
            continue
        if vacant and not r.get("looks_vacant"):
            continue
        if number and number not in digits(r.get("apn")):
            continue
        if words:
            found = row_text(r)
            if not all(w in found for w in words):
                continue
        out.append(r)
    return out


def sort_parcels(rows, key="acres", descending=True):
    """Sorted copy. Rows with no value for the key always come last, whichever way the sort runs.
    Ties are settled by parcel number so the order never jumps about."""
    value = SORT_KEYS.get(key, SORT_KEYS["acres"])
    have = [r for r in rows if value(r) is not None]
    lack = [r for r in rows if value(r) is None]
    have.sort(key=lambda r: str(r.get("apn") or ""))
    have.sort(key=value, reverse=bool(descending))
    lack.sort(key=lambda r: str(r.get("apn") or ""))
    return have + lack


def zoning_options(rows, names, kinds):
    """What the zoning filter offers: the families and the single zones that actually occur, with counts."""
    by_kind, by_zone = {}, {}
    for r in rows:
        by_kind[r.get("zoning_kind")] = by_kind.get(r.get("zoning_kind"), 0) + 1
        for part in set(zone_parts(r.get("zoning"))):
            by_zone[part] = by_zone.get(part, 0) + 1
    return {
        "kinds": [{"id": k["id"], "label": k["label"], "count": by_kind[k["id"]]} for k in kinds if by_kind.get(k["id"])],
        "zones": [{"code": z, "name": names.get(z, ""), "count": n}
                  for z, n in sorted(by_zone.items(), key=lambda kv: (-kv[1], kv[0]))],
    }


def summary(rows):
    """The numbers on a city card. A record whose size contradicts its outline counts at the outline's size (see
    counted_acres); "corrected_records" says how many were counted that way."""
    acres = [counted_acres(r) for r in rows if counted_acres(r) is not None]
    return {"large_parcels": len(rows), "look_vacant": sum(1 for r in rows if r.get("looks_vacant")),
            "largest_acres": max(acres) if acres else None, "total_acres": round(sum(acres), 1) if acres else None,
            "corrected_records": sum(1 for r in rows if r.get("outline_acres") is not None)}
