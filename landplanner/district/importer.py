"""Importing CSV and Excel files against the published templates (FR-50): every row is checked against the data
dictionary (required fields, types, units, ranges) BEFORE anything is written, and the answer is a preview of
which rows are fine and which are not, and why. Nothing reaches a dataset until the preview is committed.

A column header is the field name; it may carry its unit, as "sf [sf]" or "base_rent_usd_sf_yr (usd_per_sf_yr)".
A header whose unit is not the field's unit rejects the column (a figure in the wrong unit is worse than none).
In a workbook, each sheet named like an entity (its name or its label: "assumptions", "Assumption") is read as one.
"""
import csv
import io
import re

from . import Problem
from .schema import DICTIONARY_COLUMNS, ENTITIES, UNITS, dictionary_rows
from .validate import clean_record, empty

MAX_ROWS = 50000
_HEADER = re.compile(r"^\s*([A-Za-z0-9_ ]+?)\s*(?:[\[(]\s*([A-Za-z0-9_/$ ]+?)\s*[\])])?\s*$")


def columns(entity):
    return list(ENTITIES[entity]["fields"])


def template_csv(entity):
    if entity not in ENTITIES:
        raise Problem(404, "not-found", "There is no template by that name.")
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerow(
        [f"{f} [{ENTITIES[entity]['fields'][f]['unit']}]" if ENTITIES[entity]["fields"][f].get("unit") else f
         for f in columns(entity)])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def dictionary_csv():
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(DICTIONARY_COLUMNS)
    w.writerows(dictionary_rows())
    return ("﻿" + buf.getvalue()).encode("utf-8")


def template_sheets():
    """{sheet: rows} for the template workbook: one sheet per entity, then the dictionary and the units."""
    sheets = {}
    for name, e in ENTITIES.items():
        sheets[name] = [[f"{f} [{d['unit']}]" if d.get("unit") else f for f, d in e["fields"].items()]]
    sheets["Dictionary"] = [DICTIONARY_COLUMNS] + dictionary_rows()
    sheets["Units"] = [["unit", "meaning"]] + [[k, v] for k, v in UNITS.items()]
    return sheets


def _sheet_entity(sheet_name):
    key = re.sub(r"[^a-z]", "", str(sheet_name).lower())
    for name, e in ENTITIES.items():
        if key in (re.sub(r"[^a-z]", "", name), re.sub(r"[^a-z]", "", e["label"].lower()),
                   re.sub(r"[^a-z]", "", e["label"].lower()) + "s"):
            return name
    return None


def _read_csv(data):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", "replace")     # a spreadsheet saved as "CSV" on Windows
    if "\x00" in text[:65536]:
        raise Problem(400, "bad-request", "That file does not look like a .csv file.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)]


def _xlsx():
    try:
        from . import xlsx
        return xlsx
    except Exception:  # noqa: BLE001 - missing or half-written: say it is not ready
        raise Problem(501, "not-ready", "Excel files cannot be read yet: the workbook reader "
                                        "(landplanner/district/xlsx.py) is not installed.") from None


def read_tables(filename, data, entity=None):
    """{entity: rows} from a CSV (needs entity) or an XLSX (sheets matched by name). Unmatched sheets are listed."""
    name = str(filename or "").lower()
    if not data:
        raise Problem(400, "bad-request", "The file is empty.")
    if name.endswith((".xlsx", ".xlsm")) or data[:4] == b"PK\x03\x04":
        reader = _xlsx()
        if not hasattr(reader, "read_workbook"):
            raise Problem(501, "not-ready", "The workbook reader is not finished yet.")
        try:
            sheets = reader.read_workbook(data)
        except ValueError as e:
            raise Problem(400, "bad-request", str(e)) from None
        out, skipped = {}, []
        for sheet, rows in sheets.items():
            ent = entity if entity and len(sheets) == 1 else _sheet_entity(sheet)
            if ent:
                out[ent] = rows
            elif sheet not in ("Dictionary", "Units"):
                skipped.append(sheet)
        if not out:
            raise Problem(400, "bad-request", "No sheet in the workbook is named like a template "
                                              f"({', '.join(ENTITIES)}).")
        return "xlsx", out, skipped
    if entity not in ENTITIES:
        raise Problem(400, "bad-request", "Say which template the .csv file follows (entity=assumptions, parcels, ...).")
    return "csv", {entity: _read_csv(data)}, []


def _header(cells, entity):
    """[(field or None, header text, error or None)] for each column."""
    fields = ENTITIES[entity]["fields"]
    out = []
    for cell in cells:
        text = "" if cell is None else str(cell).strip()
        m = _HEADER.match(text)
        if not text:
            out.append((None, text, None))
            continue
        if not m:
            out.append((None, text, f"the column “{text[:40]}” is not a field of {entity}"))
            continue
        fname = re.sub(r"\s+", "_", m.group(1).strip().lower())
        unit = (m.group(2) or "").strip().lower().replace(" ", "_") or None
        if fname not in fields:
            out.append((None, text, None))
            continue
        want = fields[fname].get("unit")
        if unit and want and unit != want:
            out.append((None, text, f"the column “{text[:40]}” is in {unit}, but {fname} is kept in {want}: convert "
                                    "it first"))
            continue
        if unit and not want and unit not in UNITS:
            out.append((None, text, f"the column “{text[:40]}” names a unit this app does not know ({unit})"))
            continue
        out.append((fname, text, None))
    return out


def preview_tables(tables):
    """Check every row; returns {entities: {...}, rows_ok, rows_rejected, can_commit, errors} plus the clean rows."""
    report, clean = {}, {}
    errors = []
    for entity, rows in tables.items():
        rows = [r for r in rows if r and any(not empty(c) for c in r)]
        if not rows:
            report[entity] = {"rows_ok": 0, "rows_rejected": 0, "rejected": [], "sample": [], "unknown_columns": [],
                              "missing_columns": [], "column_errors": ["the sheet is empty"]}
            continue
        if len(rows) - 1 > MAX_ROWS:
            raise Problem(413, "too-large", f"{entity}: more than {MAX_ROWS:,} rows in one import.")
        head = _header(rows[0], entity)
        known = {f for f, _, _ in head if f}
        col_errors = [err for _, _, err in head if err]
        unknown = [t for f, t, err in head if not f and not err and t]
        required = [f for f, d in ENTITIES[entity]["fields"].items() if d.get("required") and f != "id"]
        missing = [f for f in required if f not in known]
        ok, rejected, seen = [], [], {}
        for n, cells in enumerate(rows[1:], start=2):
            record = {}
            for (fname, _, _), cell in zip(head, cells):
                if fname:
                    record[fname] = cell
            rec, errs = clean_record(entity, record)
            rid = (rec or {}).get("id")
            if rid and rid in seen:
                errs = errs + [f"id: “{rid}” is also on row {seen[rid]}"]
            if errs:
                rejected.append({"row": n, "id": rid, "errors": errs})
            else:
                seen[rid] = n
                ok.append(rec)
        report[entity] = {"rows_ok": len(ok), "rows_rejected": len(rejected), "rejected": rejected[:500],
                          "sample": ok[:5], "unknown_columns": unknown, "missing_columns": missing,
                          "column_errors": col_errors}
        if missing:
            errors.append(f"{entity}: the required column{'s' if len(missing) > 1 else ''} "
                          f"{', '.join(missing)} {'are' if len(missing) > 1 else 'is'} missing")
        errors.extend(f"{entity}: {e}" for e in col_errors)
        clean[entity] = ok
    total_ok = sum(r["rows_ok"] for r in report.values())
    total_bad = sum(r["rows_rejected"] for r in report.values())
    return {"entities": report, "rows_ok": total_ok, "rows_rejected": total_bad,
            "can_commit": total_ok > 0, "errors": errors}, clean


def preview(filename, data, entity=None):
    fmt, tables, skipped = read_tables(filename, data, entity)
    report, clean = preview_tables(tables)
    report["format"] = fmt
    report["file"] = str(filename or "")[:120]
    report["skipped_sheets"] = skipped
    return report, clean
