"""Read and write .xlsx workbooks and read .csv files, using only the standard library.

The older reader in landplanner/sources/economy.py is a small private helper for one government file (no dates,
no errors, no size limits), so this module is its own, fuller reader.

read_workbook(data)  -> {sheet name: [[cell, ...], ...]}   cells are str, int, float, bool or None
write_workbook(sheets, widths=None) -> bytes               bold frozen first row, text never runs as a formula
read_csv(data)       -> [[str, ...], ...]
"""
import csv
import datetime
import io
import re
import zipfile
import zlib
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

MAX_UNCOMPRESSED = 200 * 1024 * 1024     # all parts of a workbook added together, bytes
MAX_ROWS = 1_000_000                     # rows in one sheet
MAX_COLUMNS = 16384                      # Excel's own limit

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"      # old .xls files, and password-protected .xlsx files
_EXCEL_EPOCH = datetime.datetime(1899, 12, 30)
_EXCEL_EPOCH_1904 = datetime.datetime(1904, 1, 1)


# ---------------------------------------------------------------- reading

def _local(tag):
    return tag.rsplit("}", 1)[-1]


class _Limited:
    """A file-like wrapper that stops a part from growing past what is left of the size budget."""

    def __init__(self, f, budget):
        self.f, self.budget = f, budget

    def read(self, n=-1):
        chunk = self.f.read(n if n and n > 0 else 1 << 20)
        self.budget[0] -= len(chunk)
        if self.budget[0] < 0:
            raise ValueError("This workbook expands to far more data than a normal spreadsheet, so it was not opened.")
        return chunk


def _col_index(ref):
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _is_date_format(code):
    code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.', "", code).lower()
    return bool(re.search(r"[dmyhs]", code)) and code.strip() != "general"


_BUILTIN_DATE_IDS = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))


def _excel_date(serial, date1904):
    base = _EXCEL_EPOCH_1904 if date1904 else (_EXCEL_EPOCH if serial >= 61 else datetime.datetime(1899, 12, 31))
    try:
        when = base + datetime.timedelta(seconds=round(serial * 86400))
    except OverflowError:
        return serial
    if serial < 1 and not date1904:
        return when.strftime("%H:%M:%S")
    if when.hour == when.minute == when.second == 0:
        return when.strftime("%Y-%m-%d")
    return when.strftime("%Y-%m-%dT%H:%M:%S")


def _number(text):
    text = text.strip()
    if re.fullmatch(r"-?\d+", text) and len(text) < 16:
        return int(text)
    try:
        value = float(text)
    except ValueError:
        return text
    if value == int(value) and abs(value) < 1e15 and "e" not in text.lower():
        return int(value)
    return value


def _shared_strings(zf, budget):
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    out = []
    with zf.open("xl/sharedStrings.xml") as f:
        for _, el in ET.iterparse(_Limited(f, budget)):
            if _local(el.tag) != "si":
                continue
            out.append(_rich_text(el))
            el.clear()
    return out


def _date_styles(zf, budget):
    """The set of cell-format numbers (the `s` of a cell) whose number format is a date or time."""
    if "xl/styles.xml" not in zf.namelist():
        return set()
    with zf.open("xl/styles.xml") as f:
        root = ET.parse(_Limited(f, budget)).getroot()
    custom = {}
    for el in root.iter():
        if _local(el.tag) == "numFmt":
            custom[int(el.get("numFmtId", "-1"))] = el.get("formatCode", "")
    out = set()
    for el in root:
        if _local(el.tag) == "cellXfs":
            for i, xf in enumerate(x for x in el if _local(x.tag) == "xf"):
                fid = int(xf.get("numFmtId", "0"))
                if fid in custom:
                    if _is_date_format(custom[fid]):
                        out.add(i)
                elif fid in _BUILTIN_DATE_IDS:
                    out.add(i)
    return out


def _read_sheet(zf, path, shared, date_styles, date1904, budget, max_rows):
    rows = {}
    last_row = -1
    with zf.open(path) as f:
        row_no = -1
        for event, el in ET.iterparse(_Limited(f, budget), events=("end",)):
            if _local(el.tag) != "row":
                continue
            row_no = int(el.get("r")) - 1 if el.get("r") else row_no + 1
            if row_no >= max_rows:
                raise ValueError(f"This sheet has more than {max_rows:,} rows, which is more than this tool will open.")
            cells = {}
            col = -1
            for c in el:
                if _local(c.tag) != "c":
                    continue
                col = _col_index(c.get("r")) if c.get("r") else col + 1
                if col >= MAX_COLUMNS:
                    continue
                kind = c.get("t", "n")
                v = next((x for x in c if _local(x.tag) == "v"), None)
                text = v.text if v is not None else None
                value = None
                if kind == "inlineStr":
                    isel = next((x for x in c if _local(x.tag) == "is"), None)
                    if isel is not None:
                        value = _rich_text(isel)
                elif text is None or text == "":
                    value = None
                elif kind == "s":
                    idx = int(text)
                    value = shared[idx] if 0 <= idx < len(shared) else None
                elif kind in ("str", "e"):
                    value = text
                elif kind == "b":
                    value = text.strip() in ("1", "true")
                elif kind == "d":
                    value = text
                else:
                    value = _number(text)
                    if isinstance(value, (int, float)) and not isinstance(value, bool) \
                            and int(c.get("s", "0") or 0) in date_styles:
                        value = _excel_date(float(value), date1904)
                if value is not None:
                    cells[col] = value
            if cells:
                rows[row_no] = cells
                last_row = max(last_row, row_no)
            el.clear()
    out = []
    for r in range(last_row + 1):
        cells = rows.get(r)
        if not cells:
            out.append([])
            continue
        line = [None] * (max(cells) + 1)
        for col, value in cells.items():
            line[col] = value
        out.append(line)
    return out


def _rich_text(el):
    """The text of a shared or inline string: plain <t>, or <r> runs; phonetic hints (rPh) are left out."""
    parts = []
    for child in el:
        name = _local(child.tag)
        if name == "t":
            parts.append(child.text or "")
        elif name == "r":
            parts.extend(t.text or "" for t in child if _local(t.tag) == "t")
    return "".join(parts)


def _resolve(target):
    target = target.replace("\\", "/")
    if target.startswith("/"):
        return target.lstrip("/")
    parts = ("xl/" + target).split("/")
    out = []
    for p in parts:
        if p == "..":
            if out:
                out.pop()
        elif p and p != ".":
            out.append(p)
    return "/".join(out)


def read_workbook(data, max_uncompressed=MAX_UNCOMPRESSED, max_rows=MAX_ROWS):
    """Every sheet of an .xlsx file as {sheet name: rows}, in workbook order.

    A row is a list of str, int, float, bool or None; a gap in a row is None, so columns keep their place. Dates
    come back as ISO text (2026-01-31, or 2026-01-31T14:30:00 when there is a time). Raises ValueError, in plain
    words, for a file that is not a workbook, is password-protected, is the old .xls format or is absurdly big."""
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("The file could not be read as a spreadsheet.")
    data = bytes(data)
    if data.startswith(_OLE_MAGIC):
        if b"E\x00n\x00c\x00r\x00y\x00p\x00t\x00e\x00d\x00P\x00a\x00c\x00k\x00a\x00g\x00e\x00" in data:
            raise ValueError("This workbook is password-protected. Save a copy without a password and upload that.")
        raise ValueError("This is an old-format Excel file (.xls). Open it in Excel and use Save As, "
                         "choosing Excel Workbook (.xlsx), then upload that.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("This file is not an Excel workbook (.xlsx). If it is a .csv, upload it as a .csv.") from None
    with zf:
        names = set(zf.namelist())
        if "xl/workbook.xml" not in names:
            raise ValueError("This file is not an Excel workbook (.xlsx): it has no workbook inside.")
        if sum(i.file_size for i in zf.infolist()) > max_uncompressed:
            raise ValueError("This workbook expands to far more data than a normal spreadsheet, so it was not opened.")
        budget = [max_uncompressed]
        try:
            shared = _shared_strings(zf, budget)
            date_styles = _date_styles(zf, budget)
            with zf.open("xl/workbook.xml") as f:
                book = ET.parse(_Limited(f, budget)).getroot()
            date1904 = any(_local(e.tag) == "workbookPr" and e.get("date1904") in ("1", "true") for e in book.iter())
            rels = {}
            if "xl/_rels/workbook.xml.rels" in names:
                with zf.open("xl/_rels/workbook.xml.rels") as f:
                    for r in ET.parse(_Limited(f, budget)).getroot():
                        rels[r.get("Id")] = r.get("Target", "")
            out = {}
            for el in book.iter():
                if _local(el.tag) != "sheet":
                    continue
                rid = next((v for k, v in el.attrib.items() if _local(k) == "id"), None)
                path = _resolve(rels.get(rid, ""))
                if path not in names:
                    continue
                name = el.get("name", f"Sheet{len(out) + 1}")
                while name in out:
                    name += "_"
                out[name] = _read_sheet(zf, path, shared, date_styles, date1904, budget, max_rows)
        except ET.ParseError:
            raise ValueError("This workbook is damaged and could not be read. Open it in Excel, "
                             "save it again, and upload the new copy.") from None
        except (zipfile.BadZipFile, zlib.error):
            raise ValueError("This workbook is damaged and could not be read.") from None
    if not out:
        raise ValueError("This workbook has no sheets that could be read.")
    return out


# ---------------------------------------------------------------- writing

_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_FORMULA_START = ("=", "+", "-", "@")
_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font>\
<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="6">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="22" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" quotePrefix="1"/>
<xf numFmtId="49" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1" quotePrefix="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""

_S_NORMAL, _S_BOLD, _S_DATE, _S_DATETIME, _S_TEXT, _S_BOLD_TEXT = range(6)


def _xml_text(s):
    s = _ILLEGAL.sub("", str(s)).encode("utf-8", "replace").decode("utf-8")
    return escape(s)


def _col_letters(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _clean_sheet_name(name, taken):
    name = _BAD_SHEET_CHARS.sub(" ", str(name)).strip().strip("'").strip()
    name = name[:31].strip().strip("'").strip() or "Sheet"
    if name.lower() == "history":      # Excel reserves this name
        name = "History sheet"
    base, n = name, 2
    while name.lower() in taken:
        tail = f" ({n})"
        name = base[:31 - len(tail)] + tail
        n += 1
    taken.add(name.lower())
    return name


def _width_for(widths, sheet_name, original_name):
    if not widths:
        return {}
    for key in (original_name, sheet_name):
        if key in widths and isinstance(widths[key], dict):
            return widths[key]
    if any(isinstance(v, dict) for v in widths.values()):
        return {}
    return widths


def _sheet_xml(rows, strings, index, col_widths):
    ncols = max((len(r) for r in rows), default=0)
    if len(rows) > 1_048_576 or ncols > MAX_COLUMNS:
        raise ValueError("That is more rows or columns than an Excel sheet can hold.")
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
    if rows and ncols:
        out.append(f'<dimension ref="A1:{_col_letters(ncols - 1)}{len(rows)}"/>')
    out.append('<sheetViews><sheetView workbookViewId="0"%s>' % (' tabSelected="1"' if index == 0 else ""))
    if rows:
        out.append('<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                   '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>')
    out.append('</sheetView></sheetViews><sheetFormatPr defaultRowHeight="15"/>')
    cols = []
    for key, w in col_widths.items():
        i = _col_index(key) if isinstance(key, str) else int(key)
        try:
            w = float(w)
        except (TypeError, ValueError):
            continue
        if 0 <= i < MAX_COLUMNS and w > 0:
            cols.append((i, min(w, 255.0)))
    if cols:
        out.append("<cols>" + "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w:g}" customWidth="1"/>'
                                      for i, w in sorted(cols)) + "</cols>")
    out.append("<sheetData>")
    for r, row in enumerate(rows):
        header = r == 0
        cells = []
        for c, v in enumerate(row):
            if v is None or (isinstance(v, str) and v == ""):
                continue
            ref = f"{_col_letters(c)}{r + 1}"
            bold = _S_BOLD if header else _S_NORMAL
            if isinstance(v, bool):
                cells.append(f'<c r="{ref}" t="b"{_s(bold)}><v>{int(v)}</v></c>')
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
                    continue
                if isinstance(v, int) and abs(v) >= 10 ** 15:      # Excel keeps 15 digits; keep every digit as text
                    cells.append(_string_cell(ref, str(v), strings, _S_BOLD_TEXT if header else _S_TEXT))
                else:
                    cells.append(f'<c r="{ref}"{_s(bold)}><v>{repr(v)}</v></c>')
            elif isinstance(v, (datetime.datetime, datetime.date)):
                is_dt = isinstance(v, datetime.datetime)
                delta = (v if is_dt else datetime.datetime(v.year, v.month, v.day)) - _EXCEL_EPOCH
                serial = delta.days + delta.seconds / 86400
                cells.append(f'<c r="{ref}" s="{_S_DATETIME if is_dt else _S_DATE}"><v>{serial!r}</v></c>')
            else:
                text = str(v)
                style = bold
                if text.startswith(_FORMULA_START):
                    style = _S_BOLD_TEXT if header else _S_TEXT
                cells.append(_string_cell(ref, text, strings, style))
        out.append(f'<row r="{r + 1}">' + "".join(cells) + "</row>" if cells else f'<row r="{r + 1}"/>')
    out.append("</sheetData>")
    out.append('<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>')
    return "".join(out)


def _s(style):
    return f' s="{style}"' if style else ""


def _string_cell(ref, text, strings, style):
    idx = strings.setdefault(text, len(strings))
    return f'<c r="{ref}" t="s"{_s(style)}><v>{idx}</v></c>'


def write_workbook(sheets, widths=None):
    """A valid .xlsx as bytes. `sheets` is {name: rows}; the first row of each sheet is the bold, frozen header.

    Numbers are written as numbers. Text is always written as text, so a cell like "=1+1" or "@x" is shown, never
    run. `widths` is {column: width in characters} for every sheet, or {sheet name: {column: width}}; a column is
    a 0-based number or a letter. Sheet names are cut to Excel's rules (31 characters, none of [ ] : * ? / \\)."""
    if not sheets:
        sheets = {"Sheet1": []}
    taken, named = set(), []
    for original, rows in sheets.items():
        named.append((original, _clean_sheet_name(original, taken), [list(r) for r in rows]))
    strings = {}
    parts = {}
    for i, (original, name, rows) in enumerate(named):
        parts[f"xl/worksheets/sheet{i + 1}.xml"] = _sheet_xml(rows, strings, i, _width_for(widths, name, original))
    n = len(named)
    sst = "".join(f'<si><t xml:space="preserve">{_xml_text(s)}</t></si>' for s in strings)
    parts["xl/sharedStrings.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(strings)}" '
        f'uniqueCount="{len(strings)}">{sst}</sst>')
    parts["xl/styles.xml"] = _STYLES
    parts["xl/workbook.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<bookViews><workbookView xWindow="0" yWindow="0" windowWidth="24000" windowHeight="12000"/></bookViews><sheets>'
        + "".join(f'<sheet name="{_xml_text(name)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
                  for i, (_, name, _) in enumerate(named)) + "</sheets></workbook>")
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    parts["xl/_rels/workbook.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(f'<Relationship Id="rId{i + 1}" Type="{rel}/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                  for i in range(n))
        + f'<Relationship Id="rId{n + 1}" Type="{rel}/styles" Target="styles.xml"/>'
        f'<Relationship Id="rId{n + 2}" Type="{rel}/sharedStrings" Target="sharedStrings.xml"/></Relationships>')
    parts["_rels/.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    ct = "application/vnd.openxmlformats-officedocument.spreadsheetml"
    parts["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/xl/workbook.xml" ContentType="{ct}.sheet.main+xml"/>'
        + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="{ct}.worksheet+xml"/>'
                  for i in range(n))
        + f'<Override PartName="/xl/styles.xml" ContentType="{ct}.styles+xml"/>'
        f'<Override PartName="/xl/sharedStrings.xml" ContentType="{ct}.sharedStrings+xml"/></Types>')
    buf = io.BytesIO()
    order = ["[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels", "xl/styles.xml",
             "xl/sharedStrings.xml"] + [f"xl/worksheets/sheet{i + 1}.xml" for i in range(n)]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in order:
            info = zipfile.ZipInfo(path, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, parts[path].encode("utf-8"))
    return buf.getvalue()


# ---------------------------------------------------------------- csv

def read_csv(data):
    """Rows of a .csv file as lists of text. UTF-8 (with or without a BOM) first, then Windows-1252; the separator
    (comma, semicolon or tab) is worked out from the first lines."""
    if isinstance(data, str):
        text = data
    else:
        try:
            text = bytes(data).decode("utf-8-sig")
        except UnicodeDecodeError:
            text = bytes(data).decode("cp1252", errors="replace")
    text = text.replace("\x00", "")
    sample = "\n".join(text.splitlines()[:20])
    delim = _sniff(sample)
    return [row for row in csv.reader(io.StringIO(text, newline=""), delimiter=delim)]


def _sniff(sample):
    best, best_score = ",", (0, 0)
    for d in (",", ";", "\t"):
        counts = [len(r) for r in csv.reader(io.StringIO(sample), delimiter=d) if r]
        if not counts or max(counts) < 2:
            continue
        common = max(set(counts), key=counts.count)
        score = (counts.count(common), common)       # lines that agree, then how many columns they agree on
        if common > 1 and score > best_score:
            best, best_score = d, score
    return best
