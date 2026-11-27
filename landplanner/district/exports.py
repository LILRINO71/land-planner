"""Exports (FR-60 to FR-62): any table to Excel and any module (page) to PDF, each marked CONFIDENTIAL with its
as-of date and the disclaimer for its audience. The content is already filtered for that audience when it gets
here. The Excel and PDF writers are other modules (xlsx.py, pdf.py); while one is missing, the export says so.
"""
from . import Problem
from .register import display, figure
from .schema import ENTITIES

WATERMARK = "CONFIDENTIAL"
AUDIENCE_NAMES = {"internal": "Internal", "consultant": "Consultant", "partner": "Investor / partner",
                  "city": "City-facing"}


def _writer(name, func):
    try:
        module = __import__(f"landplanner.district.{name}", fromlist=[func])
    except Exception:  # noqa: BLE001 - missing or half-written: say it is not ready
        module = None
    fn = getattr(module, func, None)
    if fn is None:
        what = "Excel" if name == "xlsx" else "PDF"
        raise Problem(501, "not-ready", f"{what} export is not available yet: landplanner/district/{name}.py "
                                        f"({func}) is not installed.")
    return fn


def _cell(v):
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v)
    if isinstance(v, dict):
        return ", ".join(f"{k}: {x}" for k, x in v.items())
    return v


def entity_rows(content, entity):
    """[header, rows...] for one entity, with only the columns that hold something."""
    fields = list(ENTITIES[entity]["fields"])
    rows = content["entities"][entity]
    used = [f for f in fields if any(r.get(f) not in (None, "", []) for r in rows)] or fields[:1]
    return [used] + [[_cell(r.get(f)) for f in used] for r in rows]


def _banner(project, audience, as_of, disclaimer):
    return [[f"{WATERMARK} - {project.get('name', '')}"],
            [f"{AUDIENCE_NAMES.get(audience, audience)} view - as of {as_of}"],
            [disclaimer], []]


def table_xlsx(project, content, what, audience, as_of, disclaimer):
    """(bytes, file name). `what` is an entity, 'all', or 'section:<id>'."""
    write = _writer("xlsx", "write_workbook")
    sheets = {}
    if what == "all":
        for name in ENTITIES:
            if content["entities"][name]:
                sheets[name] = _banner(project, audience, as_of, disclaimer) + entity_rows(content, name)
    elif what in ENTITIES:
        sheets[what] = _banner(project, audience, as_of, disclaimer) + entity_rows(content, what)
    elif str(what).startswith("section:"):
        sid = what.split(":", 1)[1]
        s = next((x for x in content["entities"]["sections"] if x.get("id") == sid), None)
        if s is None or s.get("kind") != "table":
            raise Problem(404, "not-found", "There is no such table section (for this audience).")
        rows = [[_cell(c) for c in r] for r in (s.get("rows") or []) if isinstance(r, list)]
        sheets[(s.get("heading") or sid)[:28]] = _banner(project, audience, as_of, disclaimer) + \
            [list(s.get("columns") or [])] + rows
    else:
        raise Problem(400, "bad-request", "Say which table to export: an entity, all, or section:<id>.")
    if not sheets:
        sheets["empty"] = _banner(project, audience, as_of, disclaimer) + [["(no rows)"]]
    sheets["About"] = [["Project", project.get("name", "")], ["Audience", AUDIENCE_NAMES.get(audience, audience)],
                       ["As of", as_of], ["Marking", WATERMARK], ["Disclaimer", disclaimer]]
    name = f"{project['id']}-{str(what).replace(':', '-')}-{audience}-{as_of}.xlsx"
    return write(sheets), name


def module_pdf(project, modules, content, module_id, audience, as_of, disclaimer):
    build = _writer("pdf", "build_pdf")
    mod = next((m for m in modules if m.get("id") == module_id), None)
    if mod is None:
        raise Problem(404, "not-found", "There is no such page (for this audience).")
    sections = []
    if mod.get("banner"):
        sections.append({"heading": "Read this first", "paragraphs": [mod["banner"]], "tables": []})
    cards = []
    for c in mod.get("cards") or []:
        ids = [c.get("assumption")] if c.get("assumption") else list(c.get("assumptions") or [])
        entries = [figure(content, i) for i in ids]
        shown = " to ".join(display(e) for e in entries if e) or "not in the register"
        src = ", ".join(c.get("source_tags") or []) or ", ".join(
            sorted({e.get("source_model") or e.get("source_doc") or "" for e in entries if e} - {""}))
        status = ", ".join(sorted({e.get("provenance", "") for e in entries if e} - {""}))
        cards.append([c.get("label", ""), shown, src, status, ", ".join(i for i in ids if i)])
    if cards:
        sections.append({"heading": "Key figures", "paragraphs": [mod.get("description", "")] if mod.get("description") else [],
                         "tables": [{"title": "", "columns": ["Figure", "Value", "Source", "Provenance", "Register id"],
                                     "rows": cards, "align": ["left", "right", "left", "left", "left"]}]})
    for s in sorted((x for x in content["entities"]["sections"] if x.get("module") == module_id),
                    key=lambda x: (x.get("order") or 0, x.get("id"))):
        paras = [s["body"]] if s.get("body") else []
        tables = []
        if s.get("kind") == "table" and s.get("columns"):
            tables.append({"title": "", "columns": [str(c) for c in s["columns"]],
                           "rows": [[_cell(c) for c in r] for r in s.get("rows") or [] if isinstance(r, list)],
                           "align": ["left"] + ["right"] * (len(s["columns"]) - 1)})
        if s.get("kind") == "qa":
            for i in s.get("items") or []:
                if isinstance(i, dict):
                    paras.append(f"Q: {i.get('question', '')}")
                    paras.append(f"A: {i.get('answer', '')}")
        if s.get("cites"):
            paras.append("Sources in the register: " + ", ".join(s["cites"]))
        if s.get("ai_assisted"):
            paras.append("AI-assisted text.")
        sections.append({"heading": s.get("heading") or "", "paragraphs": paras, "tables": tables})
    for t in mod.get("tables") or []:
        ent = t.get("entity")
        if ent not in ENTITIES:
            continue
        where = t.get("where") if isinstance(t.get("where"), dict) else {}
        rows = [r for r in content["entities"][ent] if all(str(r.get(k)) == str(v) for k, v in where.items())]
        cols = [c for c in (t.get("columns") or list(ENTITIES[ent]["fields"])) if c in ENTITIES[ent]["fields"]]
        sections.append({"heading": ENTITIES[ent]["label"], "paragraphs": [], "tables": [
            {"title": "", "columns": cols, "rows": [[_cell(r.get(c)) for c in cols] for r in rows],
             "align": ["left"] * len(cols)}]})
    b = project.get("branding") or {}
    doc = {"title": f"{project.get('name', '')}: {mod.get('label', module_id)}",
           "subtitle": b.get("subtitle") or "", "as_of": as_of, "watermark": WATERMARK, "disclaimer": disclaimer,
           "header": f"{project.get('name', '')} - {WATERMARK} - {AUDIENCE_NAMES.get(audience, audience)} view",
           "cover": True, "toc": len(sections) > 3, "sections": sections}
    return build(doc), f"{project['id']}-{module_id}-{audience}-{as_of}.pdf"
