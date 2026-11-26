"""Which uses a zone allows: outright, with a permit, or not at all, read from a city's own table of allowed uses.

The table is a file kept in the repository (see tools/record_allowed_uses.py), never read from the internet while
the app runs. It holds every row and every zone column as the city wrote them, with the code section, the link
and the day it was read. This module only looks things up in it:

    table = UseTable(the recorded file, the city's match of Land Planner's uses to the code's use names)
    table.answer("EDC-CC")           one zone: every use by how it is allowed, and Land Planner's six uses
    table.answer("RM & RR5")         a parcel with two zones: one answer per zone
    table.answer("Specific Plan", plan_name="Audie Murphy Ranch SP")

Rules kept everywhere:
  - Nothing is guessed. A zone the code has no column for is "unread", a cell the city left blank is shown as blank.
  - A zone inside a specific plan is not answered from the tables: the plan's own document sets its uses, and the
    answer names that plan.
  - A use the table does not list is not allowed, because the code says so itself ("Unlisted Uses"); the answer
    quotes that sentence.
"""
import json
import re
from pathlib import Path

BUILT = ("retail", "office", "apartments", "homes", "business")
# how a use stands in a zone -> the short words shown beside it
WORDS = {
    "outright": "Allowed outright",
    "permit": "Allowed with a conditional use permit",
    "no": "Not allowed: needs a zone change",
    "unlisted": "Not in the zone's table: needs a zone change",
    "plan": "Set by the specific plan",
    "depends": "Depends on the part of the planned development",
    "unread": "Could not be read from the city's code",
}
LETTER = {"P": "outright", "C": "permit", "--": "no"}
BEST_FIRST = ("outright", "permit", "plan", "depends", "unread", "no", "unlisted")
# the same, as the Plan's scoring knows it
FIT = {"outright": "fits", "permit": "permit", "plan": "review", "depends": "unknown", "unread": "unknown",
       "no": "change", "unlisted": "change"}
PARK_NOTE = ("Not listed as a use of its own in this zone's table. The open space and drainage basins a project "
             "must provide are part of that project, not a separate use.")


def same(text):
    """A use name for matching: lower case, with stray spaces and closing punctuation dropped."""
    return re.sub(r"\s+", " ", str(text or "")).strip(" .;:").lower()


def row_name(row):
    """A table row's use as one line. Most stacked rows read "Use: case". Where the city stacked the cases without
    a heading of their own ("Batting cages – indoor" over "Outdoor"), the first case is the use itself and a later
    one is shown with the whole row beside it."""
    use, case = row["use"], row.get("case")
    if not case:
        return use
    if " / " in use:
        return case if use.startswith(case) else f"{use} (the line “{case}”)"
    return f"{use}: {case}"


def tidy_code(code):
    """"LDR - 1" -> "LDR-1"; spaces and case evened out."""
    return re.sub(r"\s*-\s*", "-", re.sub(r"\s+", " ", str(code or "")).strip()).upper()


class UseTable:
    def __init__(self, data, match):
        self.data, self.match = data, match
        self.columns = {}
        for table in data.get("tables") or []:
            for zone in table.get("zones") or []:
                self.columns[zone.upper()] = table
        special = data.get("special") or {}
        self.plans = special.get("specific_plans") or []
        self.districts = {d["number"].upper(): d for d in special.get("planned_developments") or []}
        self.special = special

    @classmethod
    def from_file(cls, path, match):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), match)

    # ---- what the file covers

    def zones(self):
        return sorted(self.columns)

    def source(self):
        d = self.data
        return {"name": d.get("code"), "publisher": d.get("publisher"), "url": d.get("home"), "read_on": d.get("read_on")}

    def matches(self):
        """The match of Land Planner's uses to the code's use names, for showing on the page."""
        return [{"use": use, "lead": list(m.get("lead") or ()), "also": list(m.get("also") or ()), "why": m.get("why", "")}
                for use, m in self.match.items()]

    # ---- one zone

    def _rows(self, table, zone):
        out = {"outright": [], "permit": [], "no": [], "other": []}
        for row in table.get("rows") or []:
            name = row_name(row)
            if row.get("unread"):
                out["other"].append({"use": name, "requirements": row.get("requirements") or "",
                                     "why": "the lines of this row could not be matched to its letters"})
                continue
            value = (row.get("cells") or {}).get(zone)
            item = {"use": name, "requirements": row.get("requirements") or ""}
            if (row.get("cell_notes") or {}).get(zone):
                item["note"] = row["cell_notes"][zone]
            if value in LETTER:
                out[LETTER[value]].append(item)
            else:
                item["why"] = ("the city left this cell blank" if value == "" else
                               "marked not applicable to this zone" if value == "NA" else
                               f"written as “{(row.get('as_written') or {}).get(zone, value)}”, which is not one of the table's letters")
                out["other"].append(item)
        return out

    def _use(self, table, zone, use):
        """How one of Land Planner's uses stands in one zone column, with the code rows it was read from."""
        m = self.match.get(use) or {}
        lead, also = {same(n) for n in m.get("lead") or ()}, {same(n) for n in m.get("also") or ()}
        read, related = [], []
        for row in table.get("rows") or []:
            if row.get("unread"):
                continue
            key, value = same(row["use"]), (row.get("cells") or {}).get(zone)
            name = row_name(row)
            item = {"use": name, "letter": value, "status": LETTER.get(value, "unread"),
                    "requirements": row.get("requirements") or ""}
            if key in lead:
                read.append(item)
            elif key in also or same(row.get("case")) in also:
                related.append(item)
        if read:
            best = min(read, key=lambda r: BEST_FIRST.index(r["status"]))
            status = best["status"]
        else:
            status = "unlisted"
        out = {"status": status, "words": WORDS[status], "fit": FIT[status], "read_from": read, "related": related,
               "zone": zone, "table": table.get("table")}
        if status == "permit":
            out["permit"] = "conditional use permit"
        if status == "unlisted" and use == "park":
            out["words"] = "Not listed as a use of its own"
        if status == "unlisted":
            out["why"] = (PARK_NOTE if use == "park" else
                          (table.get("rules") or {}).get("unlisted") or "The table does not list this use.")
        needs = [r["requirements"] for r in read if r["requirements"]]
        if needs:
            out["requirements"] = needs[0]
        return out

    def _column(self, zone, said_as=None):
        table = self.columns[zone]
        column = next(z for z in table["zones"] if z.upper() == zone)
        rows = self._rows(table, column)
        return {"zone": said_as or column, "kind": "table", "column": column, "table": table.get("table"),
                "section": table.get("section"), "chapter": table.get("chapter"), "chapter_name": table.get("chapter_name"),
                "url": table.get("url"), "read_on": table.get("read_on"), "rules": table.get("rules") or {},
                "outright": rows["outright"], "permit": rows["permit"], "not_allowed": rows["no"], "other": rows["other"],
                "uses": {use: self._use(table, column, use) for use in self.match}}

    def _plan_named(self, text):
        """The adopted specific plan a name points at ("Audie Murphy Ranch SP"), or None."""
        key = same(re.sub(r"\bSP\b|specific plan", "", str(text or ""), flags=re.I))
        if not key:
            return None
        for plan in self.plans:
            name = same(re.sub(r"\(.*?\)", "", plan["name"]))
            if name == key:
                return plan
        return None

    def _one(self, zone, plan_name="", layer_zone=""):
        code = tidy_code(zone)
        if code in self.columns:
            return self._column(code)
        if code in self.districts:
            return self._district(self.districts[code])
        if code == "SPECIFIC PLAN" or code.endswith(" SP") or code == "SP":
            named = zone if code not in ("SPECIFIC PLAN", "SP") else plan_name
            plan = self._plan_named(named)
            label = (plan["name"] if plan else re.sub(r"\s*\bSP\b\s*$", "", str(named or "")).strip()) or ""
            out = {"zone": zone, "kind": "specific_plan", "plan": label, "plan_number": plan["number"] if plan else "",
                   "chapter": self.special.get("chapter"), "chapter_name": self.special.get("chapter_name"),
                   "url": self.special.get("url"), "read_on": self.special.get("read_on"),
                   "wording": self.special.get("specific_plans_wording") or "",
                   "says": ((f"The uses here are set by the {label} Specific Plan" + (f" ({plan['number']})" if plan else "")
                             if label else "The uses here are set by a specific plan; the records read did not name which one")
                            + ". The Development Code adopts each specific plan by reference and does not repeat its uses, "
                              "and Land Planner has not read that plan's document. Ask the city's planners for it.")}
            out["uses"] = {use: {"status": "plan", "words": WORDS["plan"], "fit": FIT["plan"], "read_from": [], "related": [],
                                 "zone": zone, "why": out["says"]} for use in self.match}
            return out
        hint = tidy_code(layer_zone)
        if hint and hint != code and hint in self.columns:
            out = self._column(hint)
            out["zone"] = zone
            out["read_as"] = out["column"]
            out["says"] = (f"The parcel record says “{zone}”, which the Development Code's tables have no column for. "
                           f"The city's zoning map lists this spot as {out['column']}, so that column is shown.")
            return out
        out = {"zone": zone, "kind": "unread",
               "says": (f"The Development Code's tables of allowed uses have no column for “{zone}”, so what it allows "
                        "could not be read. Ask the city's planners.")}
        out["uses"] = {use: {"status": "unread", "words": WORDS["unread"], "fit": FIT["unread"], "read_from": [],
                             "related": [], "zone": zone, "why": out["says"]} for use in self.match}
        return out

    def _district(self, d):
        """A planned development: the code says in one sentence which zone's uses it follows."""
        named = [z for z in d.get("same_uses_as") or [] if z.upper() in self.columns]
        base = {"zone": d["number"], "kind": "planned_development", "district": d.get("name") or "",
                "written_as": d.get("written_as") or d["number"], "sentence": d.get("uses_sentence") or "",
                "chapter": self.special.get("chapter"), "chapter_name": self.special.get("chapter_name"),
                "url": self.special.get("url"), "read_on": self.special.get("read_on")}
        if len(named) == 1:
            column = self._column(named[0].upper())
            column.update(base, kind="planned_development", same_as=column["column"],
                          says=f"The code says this planned development follows the uses of the {column['column']} zone.")
            return column
        if not named:
            base["says"] = ("The code's section on this planned development does not say in a form this app could read "
                            "which uses it allows. Its conditions are kept by the city's planning department.")
            base["uses"] = {use: {"status": "unread", "words": WORDS["unread"], "fit": FIT["unread"], "read_from": [],
                                  "related": [], "zone": d["number"], "why": base["says"]} for use in self.match}
            return base
        columns = [self._column(z.upper()) for z in named]
        base["areas"] = columns
        base["says"] = ("The code gives different parts of this planned development the uses of different zones ("
                        + " and ".join(c["column"] for c in columns) + "). Which part a parcel is in is drawn on the "
                        "city's map of the development, which this app has not read.")
        uses = {}
        for use in self.match:
            found = [c["uses"][use] for c in columns]
            if len({f["status"] for f in found}) == 1:
                uses[use] = dict(found[0], zone=d["number"])
            else:
                uses[use] = {"status": "depends", "words": WORDS["depends"], "fit": FIT["depends"], "read_from": [],
                             "related": [], "zone": d["number"],
                             "why": " ".join(f"In the part that follows {c['column']}: {c['uses'][use]['words'].lower()}." for c in columns)}
        base["uses"] = uses
        return base

    # ---- a parcel's zoning as its record gives it

    def answer(self, code, plan_name="", layer_zone=""):
        """Everything the recorded code says about a parcel's zoning. `plan_name` is the specific plan the city's
        map names at the spot; `layer_zone` is the zone its zoning map gives there (used only when the parcel
        record's own code has no column)."""
        zones = [z.strip() for z in str(code or "").split("&") if z.strip()]
        out = {"basis": "table", "code": str(code or "").strip(), "source": self.source(),
               "letters": self.data.get("letters") or {}, "matches": self.matches()}
        if not zones:
            out.update(parts=[], uses={use: {"status": "unread", "words": "No zone listed", "fit": "unknown", "read_from": [],
                                             "related": [], "why": "The city's records list no zone for this parcel."}
                                       for use in self.match},
                       says="The city's records list no zone for this parcel, so there is no table to read.")
            return out
        parts = [self._one(z, plan_name, layer_zone if len(zones) == 1 else "") for z in zones]
        out["parts"] = parts
        uses = {}
        for use in self.match:
            found = [p["uses"][use] for p in parts]
            best = min(found, key=lambda f: BEST_FIRST.index(f["status"]))
            uses[use] = dict(best)
            if len(parts) > 1:
                uses[use]["by_zone"] = [{"zone": p["zone"], "status": f["status"], "words": f["words"]} for p, f in zip(parts, found)]
                if len({f["status"] for f in found}) > 1:
                    uses[use]["words"] = f"{best['words']} on the part zoned {best.get('zone') or ''}".strip()
        out["uses"] = uses
        return out
