"""Read the City of Menifee Development Code's tables of allowed uses and keep them in the repository.

    python tools/record_allowed_uses.py        (needs the internet; rewrites landplanner/cities/records/menifee_allowed_uses.json)

The app never reads the city's code while it runs: it reads the file this writes. Run this again when the city
changes its code; the file says the day it was read.

What is read (Title 9 of the Menifee Municipal Code, "Planning and Zoning", Article 3 "Zones", as the city publishes
it on online.encodeplus.com):
  - the "Allowed Uses and Approval Requirements" table of each chapter, every row and every zone column, as written;
  - the list of adopted specific plans and what the code says about each planned development (Chapter 9.155).
Nothing is filled in. A cell the city left blank stays blank, and a row whose lines cannot be matched to its
letters is kept as written and marked "unread".
"""
import datetime
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

BASE = "https://online.encodeplus.com/regs/menifee-ca"
OUT = Path(__file__).resolve().parents[1] / "landplanner" / "cities" / "records" / "menifee_allowed_uses.json"
AGENT = "Mozilla/5.0 (land-planner; public code lookup)"
# chapter number -> the section id the city's code viewer uses for it
CHAPTERS = (("9.125", "Agricultural and Rural Residential Zones", 1326),
            ("9.130", "Residential Zones", 1331),
            ("9.135", "Commercial and Industrial Zones", 1336),
            ("9.140", "Economic Development Corridor Zones", 1341),
            ("9.145", "Open Space/Conservation Zones", 1346),
            ("9.150", "Public/Quasi-Public Facilities", 1351))
SPECIAL = ("9.155", "Special Planning Areas", 1356)
DASHES = ("--", "—", "–", "-", "——", "––")


def fetch(secid):
    req = urllib.request.Request(f"{BASE}/doc-view.aspx?secid={secid}", headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - one fixed public https host
        return r.read().decode("utf-8", "replace")


def viewer(secid):
    """The address a person opens to read the same chapter."""
    return f"{BASE}/doc-viewer.aspx?secid={secid}"


def lines_of(cell):
    """The lines of one table cell as the city wrote them, top to bottom, with blank lines dropped."""
    cell = re.sub(r"\s+", " ", cell)
    cell = re.sub(r'<img[^>]*alt="([^"]*)"[^>]*>', lambda m: m.group(1), cell)
    cell = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", cell)
    cell = html.unescape(re.sub(r"<[^>]+>", "", cell)).replace("\xa0", " ")
    return [re.sub(r" +", " ", line).strip() for line in cell.split("\n") if line.strip()]


def words(page):
    """A page's running text, tables left out."""
    page = re.sub(r"<(script|style)[\s\S]*?</\1>", "", page)
    page = re.sub(r"<table[\s\S]*?</table>", " ", page)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page))).replace(" .", ".").replace(" ,", ",")


def letter(text):
    """One cell value as written -> (letter, extra words). Letters: P, C, NA, "--" (prohibited), "" (left blank)."""
    raw = text.strip()
    if raw in DASHES:
        return "--", ""
    m = re.fullmatch(r"([PpCc]|NA)\s*(\*?)\s*(?:\((.*)\))?", raw)
    if not m:
        return None, raw
    extra = " ".join(x for x in ("see the note" if m.group(2) else "", m.group(3) or "") if x)
    return m.group(1).upper(), extra


def zone_code(heading):
    """"02 - Rural Mountainous (RM) Category" -> "RM"; "PF" -> "PF"."""
    m = re.search(r"\(([A-Z][A-Z0-9/½-]*)\)\s*Category", heading)
    return (m.group(1) if m else heading.strip()).replace("½", "1/2")


def read_table(page):
    """The first "Allowed Uses" table on a chapter's page: its number, its zone columns and its rows."""
    for found in re.finditer(r"<table[\s\S]*?</table>", page):
        rows = [[(lines_of(c.group(2)), c.group(1)) for c in re.finditer(r"<t[dh]([^>]*)>([\s\S]*?)</t[dh]>", r.group(0))]
                for r in re.finditer(r"<tr[\s\S]*?</tr>", found.group(0))]
        title = " ".join(rows[0][0][0]) if rows and rows[0] else ""
        if "Allowed Uses" not in title:
            continue
        number = re.search(r"Table\s+([\d.]+-\d+)", title)
        head = next(i for i, r in enumerate(rows) if r and r[0][0][:1] == ["Allowed Use"])
        zones = [zone_code(" ".join(c[0])) for c in rows[head][1:-1]]
        out, group, notes = [], "", []
        for r in rows[head + 1:]:
            if not r:
                continue
            if len(r) == 1:                        # a heading across the table, or the footnotes under it
                text = " ".join(r[0][0])
                if re.match(r"\d", text):
                    notes.append(text)
                else:
                    group = text
                continue
            if len(r) != len(zones) + 2:
                out.append({"use": " / ".join(r[0][0]), "group": group, "unread": True,
                            "as_written": [" / ".join(c[0]) for c in r[1:]], "requirements": ""})
                continue
            out.extend(read_row(r, zones, group))
        return {"table": "Table " + number.group(1) if number else title, "title": title, "zones": zones,
                "rows": out, "footnotes": notes}
    return None


def read_row(r, zones, group):
    """One table row. A row that stacks several cases ("Indoor" over "Outdoor", each with its own letter) becomes
    one row per case; a row whose cases and letters do not line up is kept as written and marked unread."""
    use, cells, needs = r[0][0], [c[0] for c in r[1:-1]], " ".join(r[-1][0])
    most = max((len(c) for c in cells), default=0)
    if most <= 1:
        row = {"use": " ".join(use), "group": group, "cells": {}, "requirements": needs}
        for z, c in zip(zones, cells):
            put(row, z, c[0] if c else "")
        return [row]
    if any(len(c) not in (0, 1, most) for c in cells) or len(use) < most:
        return [{"use": " / ".join(use), "group": group, "unread": True,
                 "as_written": [" / ".join(c) for c in cells], "requirements": needs}]
    whole = " ".join(use[:len(use) - most]) if len(use) > most else " / ".join(use)
    rows = []
    for i in range(most):
        row = {"use": whole.rstrip(":"), "case": use[len(use) - most + i], "group": group, "cells": {}, "requirements": needs}
        for z, c in zip(zones, cells):
            put(row, z, c[i] if len(c) == most else (c[0] if c else ""))
        rows.append(row)
    return rows


def put(row, zone, text):
    if not text:
        row["cells"][zone] = ""                    # the city left this cell blank
        return
    value, extra = letter(text)
    if value is None:
        row["cells"][zone] = "?"
        row.setdefault("as_written", {})[zone] = text
        return
    row["cells"][zone] = value
    if extra:
        row.setdefault("cell_notes", {})[zone] = extra


def read_special(page):
    """Chapter 9.155: the adopted specific plans, and for each planned development the code's own sentence about
    which zone's uses it follows (when it has one)."""
    text = words(page)
    start = text.find("9.155.020 Adopted Specific Plans", text.find("9.155.010 Purpose This"))
    middle = text.find("9.155.030 Planned Development Districts", start)
    plans = [{"number": m.group(1), "name": m.group(2).strip()}
             for m in re.finditer(r"(SP-\d+)\s+(.+?)(?=\s+SP-\d+\s|\s+A\.\s)", text[start:middle])]
    quote = re.search(r"The following specific plans have been approved.*?by reference\.", text[start:middle])
    districts = []
    for m in re.finditer(r"[A-Z]\.\s+PD-(\d+):\s*(.+?)\s+1\.\s+(.*?)(?=\s+2\.\s|\s+[A-Z]\.\s+PD-\d+:|$)", text[middle:]):
        sentence = m.group(3).strip()
        same = re.findall(r"\b([A-Z][A-Z0-9/-]+) zone\b", sentence) if "uses permitted in this PDO" in sentence else []
        districts.append({"number": "PDO-" + m.group(1), "written_as": "PD-" + m.group(1), "name": m.group(2).strip(),
                          "uses_sentence": sentence if "use" in sentence.lower() else "",
                          "same_uses_as": same})
    return {"specific_plans": plans, "specific_plans_wording": quote.group(0) if quote else "", "planned_developments": districts}


def rules(page):
    """The chapter's own words on what the letters mean and on uses the table does not list."""
    text = words(page)
    key = re.search(r"Where indicated with a letter .P. the use shall be a permitted use\..*?prohibited within the zone\.", text)
    unlisted = re.search(r"Uses not specifically listed in this table shall be considered not permitted in all of the listed zones\.", text)
    return {"letters": key.group(0) if key else "", "unlisted": unlisted.group(0) if unlisted else ""}


def main():
    today = datetime.date.today().isoformat()
    out = {"city": "Menifee", "code": "City of Menifee Development Code (Menifee Municipal Code, Title 9: Planning and Zoning)",
           "publisher": "City of Menifee, published on enCodePlus", "home": viewer(1320), "read_on": today,
           "letters": {"P": "permitted", "C": "conditional use permit", "--": "prohibited", "NA": "not applicable to the zone",
                       "": "left blank in the city's table"},
           "tables": []}
    for chapter, name, secid in CHAPTERS:
        page = fetch(secid)
        table = read_table(page)
        if not table:
            print(f"Chapter {chapter}: no allowed-use table found", file=sys.stderr)
            continue
        table.update(chapter=chapter, chapter_name=name, section=f"{chapter}.030", url=viewer(secid), read_on=today,
                     rules=rules(page))
        out["tables"].append(table)
        unread = sum(1 for r in table["rows"] if r.get("unread"))
        print(f"Chapter {chapter}: {table['table']}, zones {', '.join(table['zones'])}, {len(table['rows'])} rows, {unread} unread")
    chapter, name, secid = SPECIAL
    special = read_special(fetch(secid))
    special.update(chapter=chapter, chapter_name=name, url=viewer(secid), read_on=today)
    out["special"] = special
    print(f"Chapter {chapter}: {len(special['specific_plans'])} specific plans, {len(special['planned_developments'])} planned developments")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
