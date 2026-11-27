"""A small report writer: build_pdf(doc) -> bytes of a real vector PDF, standard library only.

Text, lines and filled rectangles in the two built-in fonts Helvetica and Helvetica-Bold (WinAnsi encoding), so no
font or image is embedded. Page streams are zlib-compressed; the xref table is exact.

doc = {title, subtitle, as_of, watermark, disclaimer, header, cover: bool, toc: bool, page_size: "letter"|"a4",
       sections: [{heading, paragraphs: [str], bullets: [str], kpis: [{label, value, note}],
                   tables: [{title, columns: [str], rows: [[...]], align: ["l"|"r"|"c"], col_widths: [weights]}]}]}

Inside a section the order is: KPI cards, paragraphs, bullets, tables.
"""
import hashlib
import math
import unicodedata
import zlib

PAGE_SIZES = {"letter": (612.0, 792.0), "a4": (595.28, 841.89)}
MARGIN = 54.0
LEADING = 13.0
BODY = 10.0
NAVY = (0.12, 0.22, 0.38)
GREY = (0.40, 0.40, 0.40)
BLACK = (0, 0, 0)
HEAD_FILL = (0.86, 0.90, 0.95)
ZEBRA = (0.965, 0.97, 0.98)
RULE = (0.70, 0.72, 0.76)

# ---------------------------------------------------------------- character widths (Adobe Helvetica AFM, per 1000 em)

_H = dict(zip(" !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~", [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015,
    667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944,
    667, 667, 611, 278, 278, 278, 469, 556, 333,
    556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722,
    500, 500, 500, 334, 260, 334, 584]))
_B = dict(zip(" !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~", [
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975,
    722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944,
    667, 667, 611, 333, 278, 333, 584, 556, 333,
    556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778,
    556, 556, 500, 389, 280, 389, 584]))
# the non-ASCII characters of WinAnsi that are not just a letter with an accent
_H.update({"‘": 222, "’": 222, "“": 333, "”": 333, "‚": 222, "„": 333,
           "•": 350, "–": 556, "—": 1000, "…": 1000, "€": 556, "™": 1000, "°": 400,
           "±": 584, "×": 584, "÷": 584, "©": 737, "®": 737, "§": 556, "·": 278,
           " ": 278, "†": 556, "‡": 556, "‰": 1000, "¢": 556, "£": 556, "¥": 556,
           "¼": 834, "½": 834, "¾": 834, "µ": 556, "¶": 537, "¬": 584, "¿": 611,
           "¡": 333, "Æ": 1000, "æ": 889, "Œ": 1000, "œ": 944, "ß": 611, "Ø": 778,
           "ø": 611, "Ð": 722, "ð": 556, "Þ": 667, "þ": 556, "ª": 370, "º": 365,
           "²": 333, "³": 333, "¹": 333, "«": 556, "»": 556, "‹": 333, "›": 333})
_B.update({"‘": 278, "’": 278, "“": 500, "”": 500, "‚": 278, "„": 500,
           "•": 350, "–": 556, "—": 1000, "…": 1000, "€": 556, "™": 1000, "°": 400,
           "±": 584, "×": 584, "÷": 584, "©": 737, "®": 737, "§": 556, "·": 278,
           " ": 278, "†": 556, "‡": 556, "‰": 1000, "¢": 556, "£": 556, "¥": 556,
           "¼": 834, "½": 834, "¾": 834, "µ": 611, "¶": 556, "¬": 584, "¿": 611,
           "¡": 333, "Æ": 1000, "æ": 889, "Œ": 1000, "œ": 944, "ß": 611, "Ø": 778,
           "ø": 611, "Ð": 722, "ð": 611, "Þ": 667, "þ": 611, "ª": 370, "º": 365,
           "²": 333, "³": 333, "¹": 333, "«": 556, "»": 556, "‹": 333, "›": 333})


def _char_w(ch, bold):
    table = _B if bold else _H
    w = table.get(ch)
    if w is None:
        base = unicodedata.normalize("NFD", ch)[0]       # an accented letter is as wide as the plain one
        w = table.get(base, 556)
    return w


def text_width(s, bold=False, size=BODY):
    """Width in points of already-cleaned text."""
    return sum(_char_w(c, bold) for c in s) * size / 1000.0


# ---------------------------------------------------------------- text that WinAnsi can hold

_SWAPS = {"≤": "<=", "≥": ">=", "≠": "!=", "→": "->", "←": "<-", "↔": "<->",
          "⇒": "=>", "−": "-", "‑": "-", "‐": "-", "‒": "-", "―": "—",
          "≈": "~", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
          "∗": "*", "∙": "•", "●": "•", "▪": "•", "‣": "•",
          "⁃": "-", "­": "", "​": "", "‌": "", "‍": "", "️": "", "﻿": "",
          "\t": "    "}


def clean(value):
    """Text with every character WinAnsi (cp1252) can hold kept, common look-alikes swapped, the rest a '?'."""
    out = []
    for ch in str(value):
        if ch == "\n":
            out.append(ch)
            continue
        if ch in _SWAPS:
            out.append(_SWAPS[ch])
            continue
        if ch < " " or ch == "\x7f":
            out.append(" ")
            continue
        try:
            ch.encode("cp1252")
            out.append(ch)
            continue
        except UnicodeEncodeError:
            pass
        flat = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
        try:
            flat.encode("cp1252")
            out.append(flat if flat else "?")
        except UnicodeEncodeError:
            out.append("?")
    return "".join(out)


def _pdf_string(s):
    out = []
    for b in s.encode("cp1252", "replace"):
        if b in (0x28, 0x29, 0x5c):
            out.append("\\" + chr(b))
        elif 32 <= b < 127:
            out.append(chr(b))
        else:
            out.append("\\%03o" % b)
    return "(" + "".join(out) + ")"


def _n(x):
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _rgb(c):
    return " ".join(_n(v) for v in c)


def wrap(text, bold, size, width):
    """Lines of `text` that fit `width` points; long words are broken, blank lines are kept."""
    lines = []
    for para in str(text).split("\n"):
        words = para.split(" ")
        cur = ""
        for word in words:
            trial = word if not cur else cur + " " + word
            if text_width(trial, bold, size) <= width:
                cur = trial
                continue
            if cur:
                lines.append(cur)
                cur = ""
            while text_width(word, bold, size) > width and len(word) > 1:
                k = len(word) - 1
                while k > 1 and text_width(word[:k], bold, size) > width:
                    k -= 1
                lines.append(word[:k])
                word = word[k:]
            cur = word
        lines.append(cur)
    return lines


# ---------------------------------------------------------------- one page of drawing

class _Page:
    def __init__(self):
        self.ops = []
        self.body = True          # false for the cover: no running header or footer

    def text(self, x, y, s, bold=False, size=BODY, color=BLACK):
        if s:
            self.ops.append(f"BT /{'F2' if bold else 'F1'} {_n(size)} Tf {_rgb(color)} rg {_n(x)} {_n(y)} Td "
                            f"{_pdf_string(s)} Tj ET")

    def text_right(self, x, y, s, bold=False, size=BODY, color=BLACK):
        self.text(x - text_width(s, bold, size), y, s, bold, size, color)

    def text_center(self, cx, y, s, bold=False, size=BODY, color=BLACK):
        self.text(cx - text_width(s, bold, size) / 2, y, s, bold, size, color)

    def rect(self, x, y, w, h, fill):
        self.ops.append(f"{_rgb(fill)} rg {_n(x)} {_n(y)} {_n(w)} {_n(h)} re f")

    def box(self, x, y, w, h, color, width=0.5):
        self.ops.append(f"{_rgb(color)} RG {_n(width)} w {_n(x)} {_n(y)} {_n(w)} {_n(h)} re S")

    def line(self, x1, y1, x2, y2, color=RULE, width=0.5):
        self.ops.append(f"{_rgb(color)} RG {_n(width)} w {_n(x1)} {_n(y1)} m {_n(x2)} {_n(y2)} l S")


# ---------------------------------------------------------------- the layout

def _is_number_text(s):
    t = s.strip().replace(",", "").replace("$", "").replace("%", "").replace("(", "-").replace(")", "")
    t = t.replace("—", "").strip()
    if not t:
        return False
    try:
        float(t.rstrip("xX"))
        return True
    except ValueError:
        return False


def _cell_text(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return ""
        return f"{v:,.0f}" if v == int(v) and abs(v) < 1e15 else f"{v:,.2f}"
    return clean(v)


class _Layout:
    TABLE_SIZE = 8.5
    TABLE_LEAD = 10.5
    PAD_X = 4.0
    PAD_Y = 3.0

    def __init__(self, doc):
        self.doc = doc
        self.W, self.H = PAGE_SIZES.get(str(doc.get("page_size", "letter")).lower(), PAGE_SIZES["letter"])
        self.left, self.right = MARGIN, self.W - MARGIN
        self.avail = self.right - self.left
        self.top = self.H - 62
        self.pages = []
        self.toc = []            # (heading, page number)
        self.y = 0.0
        self.first_body_page = 1
        # the disclaimer: short ones sit at the foot of every page, long ones get a closing page
        self.disclaimer = clean(doc.get("disclaimer") or "").strip()
        self.foot_lines = []
        self.closing = False
        if self.disclaimer:
            lines = wrap(self.disclaimer, False, 6.5, self.avail)
            if len(lines) <= 4:
                self.foot_lines = lines
            else:
                self.closing = True
        self.bottom = 50.0 + (len(self.foot_lines) * 8 + 8 if self.foot_lines else 0) + 12

    # -- pages
    def new_page(self):
        p = _Page()
        self.pages.append(p)
        self.y = self.top
        return p

    @property
    def page(self):
        return self.pages[-1]

    def need(self, h):
        if self.y - h < self.bottom:
            self.new_page()

    def page_number(self):
        return self.first_body_page + len(self.pages) - 1

    # -- pieces
    def heading(self, text, first_keep=40.0):
        self.need(30 + first_keep)
        if text:
            self.toc.append((text, self.page_number()))
            self.page.text(self.left, self.y - 16, text, True, 15, NAVY)
            self.page.line(self.left, self.y - 22, self.right, self.y - 22, NAVY, 0.8)
        self.y -= 34

    def paragraph(self, text):
        lines = wrap(clean(text), False, BODY, self.avail)
        for ln in lines:
            self.need(LEADING)
            self.page.text(self.left, self.y - 9, ln, False, BODY)
            self.y -= LEADING
        self.y -= 5

    def bullets(self, items):
        indent = 14.0
        for item in items:
            lines = wrap(clean(item), False, BODY, self.avail - indent)
            for i, ln in enumerate(lines):
                self.need(LEADING)
                if i == 0:
                    self.page.text(self.left + 3, self.y - 9, "•", False, BODY)
                self.page.text(self.left + indent, self.y - 9, ln, False, BODY)
                self.y -= LEADING
            self.y -= 1.5
        self.y -= 4

    def kpis(self, items):
        items = [k for k in items if isinstance(k, dict)]
        if not items:
            return
        cols = 4 if len(items) == 4 else min(3, len(items))
        gap = 8.0
        w = (self.avail - gap * (cols - 1)) / cols
        h = 62.0
        for start in range(0, len(items), cols):
            self.need(h + 6)
            for i, k in enumerate(items[start:start + cols]):
                x = self.left + i * (w + gap)
                self.page.rect(x, self.y - h, w, h, ZEBRA)
                self.page.box(x, self.y - h, w, h, RULE)
                self.page.rect(x, self.y - h, 3, h, NAVY)
                label = clean(k.get("label", ""))
                value = _cell_text(k.get("value", ""))
                size = 17.0
                while size > 8 and text_width(value, True, size) > w - 16:
                    size -= 1
                self.page.text(x + 10, self.y - 14, wrap(label, False, 8, w - 16)[0] if label else "", False, 8, GREY)
                self.page.text(x + 10, self.y - 34, value, True, size, NAVY)
                note = wrap(clean(k.get("note", "") or ""), False, 7.5, w - 16)[:2]
                for j, ln in enumerate(note):
                    self.page.text(x + 10, self.y - 46 - j * 9, ln, False, 7.5, GREY)
            self.y -= h + 8
        self.y -= 4

    def _column_widths(self, columns, rows, weights, aligns):
        n = len(columns)
        size = self.TABLE_SIZE
        pad = 2 * self.PAD_X
        if weights and len(weights) == n and all(isinstance(w, (int, float)) and w > 0 for w in weights):
            total = float(sum(weights))
            return [self.avail * w / total for w in weights]
        natural, minimum = [], []
        for c in range(n):
            texts = [(clean(columns[c]), True)] + [(row[c], False) for row in rows]
            nat = mn = 0.0
            for t, bold in texts:
                for line in t.split("\n"):
                    nat = max(nat, text_width(line, bold, size))
                    for word in line.split(" "):
                        mn = max(mn, text_width(word, bold, size))
            natural.append(nat + pad)
            minimum.append(min(mn + pad, nat + pad, self.avail / n * 1.5))
        if sum(natural) <= self.avail:
            scale = self.avail / sum(natural)
            return [w * scale for w in natural]
        room = self.avail - sum(minimum)
        if room <= 0:
            scale = self.avail / sum(minimum)
            return [w * scale for w in minimum]
        want = [nat - mn for nat, mn in zip(natural, minimum)]
        total_want = sum(want) or 1.0
        take = min(1.0, room / total_want)
        out = [mn + w * take for mn, w in zip(minimum, want)]
        spare = self.avail - sum(out)
        if spare > 0.01:
            out = [w + spare * w / sum(out) for w in out]
        return out

    def table(self, t):
        columns = [clean(c) for c in (t.get("columns") or [])]
        n = len(columns)
        if not n:
            return
        rows = []
        for r in t.get("rows") or []:
            r = list(r)[:n] + [None] * (n - len(r))
            rows.append([_cell_text(v) for v in r])
        given = list(t.get("align") or [])
        aligns = []
        for c in range(n):
            if c < len(given) and given[c] in ("l", "r", "c"):
                aligns.append(given[c])
                continue
            col = [row[c] for row in rows if row[c].strip()]
            aligns.append("r" if col and all(_is_number_text(v) for v in col) else "l")
        widths = self._column_widths(columns, rows, t.get("col_widths"), aligns)
        size, lead, px, py = self.TABLE_SIZE, self.TABLE_LEAD, self.PAD_X, self.PAD_Y
        max_lines = max(2, int((self.top - self.bottom - 2 * py - 30) / lead) - 2)

        def cell_lines(text, c, bold):
            lines = wrap(text, bold, size, max(widths[c] - 2 * px, 6))
            if len(lines) > max_lines:
                lines = lines[:max_lines - 1] + [lines[max_lines - 1][:-1].rstrip() + "..."]
            return lines

        head = [cell_lines(columns[c], c, True) for c in range(n)]
        head_h = max(len(h) for h in head) * lead + 2 * py
        title = clean(t.get("title") or "")
        if title:
            self.need(16 + head_h + 3 * lead)
            self.page.text(self.left, self.y - 11, title, True, 10.5, BLACK)
            self.y -= 18
        else:
            self.need(head_h + 3 * lead)

        def draw_header():
            top = self.y
            self.page.rect(self.left, top - head_h, self.avail, head_h, HEAD_FILL)
            x = self.left
            for c in range(n):
                self._draw_cell(x, top, widths[c], head[c], aligns[c], True)
                x += widths[c]
            self.page.line(self.left, top - head_h, self.right, top - head_h, NAVY, 0.8)
            self.y = top - head_h

        draw_header()
        for i, row in enumerate(rows):
            cells = [cell_lines(row[c], c, False) for c in range(n)]
            h = max(len(c) for c in cells) * lead + 2 * py
            if self.y - h < self.bottom:
                self.new_page()
                draw_header()
            if i % 2:
                self.page.rect(self.left, self.y - h, self.avail, h, ZEBRA)
            x = self.left
            for c in range(n):
                self._draw_cell(x, self.y, widths[c], cells[c], aligns[c], False)
                x += widths[c]
            self.page.line(self.left, self.y - h, self.right, self.y - h, RULE, 0.3)
            self.y -= h
        self.y -= 14

    def _draw_cell(self, x, top, w, lines, align, bold):
        size, lead, px, py = self.TABLE_SIZE, self.TABLE_LEAD, self.PAD_X, self.PAD_Y
        for k, ln in enumerate(lines):
            base = top - py - lead * k - size
            if align == "r":
                self.page.text_right(x + w - px, base, ln, bold, size)
            elif align == "c":
                self.page.text_center(x + w / 2, base, ln, bold, size)
            else:
                self.page.text(x + px, base, ln, bold, size)

    # -- the front pages
    def cover(self, cover_page):
        d = self.doc
        p = cover_page
        p.body = False
        p.rect(0, self.H - 230, self.W, 230, NAVY)
        lines = wrap(clean(d.get("title") or "Report"), True, 30, self.avail)[:4]
        y = self.H - 120 + (len(lines) - 1) * 18
        for ln in lines:
            p.text(self.left, y, ln, True, 30, (1, 1, 1))
            y -= 38
        sub = clean(d.get("subtitle") or "")
        yy = self.H - 270
        for ln in wrap(sub, False, 15, self.avail)[:4]:
            p.text(self.left, yy, ln, False, 15, NAVY)
            yy -= 21
        if d.get("as_of"):
            p.text(self.left, yy - 12, "As of " + clean(d["as_of"]), False, 11, GREY)

    def toc_pages(self, count, start_page, entries):
        pages = []
        per = self._toc_per_page()
        for k in range(count):
            p = _Page()
            y = self.top
            if k == 0:
                p.text(self.left, y - 16, "Contents", True, 15, NAVY)
                p.line(self.left, y - 22, self.right, y - 22, NAVY, 0.8)
                y -= 40
            for text, num in entries[k * per:(k + 1) * per]:
                label = wrap(text, False, 10.5, self.avail - 40)[0]
                p.text(self.left, y - 10, label, False, 10.5)
                num_s = str(num)
                p.text_right(self.right, y - 10, num_s, False, 10.5)
                dots_x = self.left + text_width(label, False, 10.5) + 6
                room = self.right - text_width(num_s, False, 10.5) - 6 - dots_x
                step = text_width(". ", False, 10.5)
                if room > step:
                    p.text(dots_x, y - 10, ". " * int(room / step), False, 10.5, GREY)
                y -= 19
            pages.append(p)
        return pages

    def _toc_per_page(self):
        return max(1, int((self.top - 40 - self.bottom) / 19))


# ---------------------------------------------------------------- assembling the file

def _watermark(layout, text):
    size = 90.0
    diag = math.hypot(layout.W, layout.H)
    while size > 20 and text_width(text, True, size) > diag * 0.62:
        size -= 4
    ang = math.atan2(layout.H, layout.W) * 0.9
    c, s = math.cos(ang), math.sin(ang)
    w = text_width(text, True, size)
    cx, cy = layout.W / 2, layout.H / 2
    x = cx - (w / 2) * c + (size * 0.35) * s
    y = cy - (w / 2) * s - (size * 0.35) * c
    return (f"q /GS1 gs 0.5 0.5 0.5 rg BT /F2 {_n(size)} Tf {_n(c)} {_n(s)} {_n(-s)} {_n(c)} {_n(x)} {_n(y)} Tm "
            f"{_pdf_string(text)} Tj ET Q")


def build_pdf(doc):
    """The report described by `doc` as the bytes of a PDF file (see the module note for the shape of `doc`)."""
    doc = dict(doc or {})
    lay = _Layout(doc)
    sections = [s for s in (doc.get("sections") or []) if isinstance(s, dict)]
    want_cover = bool(doc.get("cover"))
    want_toc = bool(doc.get("toc"))

    # how many contents pages: one entry per headed section, plus the closing notice
    entries_n = sum(1 for s in sections if s.get("heading")) + (1 if lay.closing else 0)
    toc_count = max(1, math.ceil(entries_n / lay._toc_per_page())) if want_toc and entries_n else 0
    lay.first_body_page = (1 if want_cover else 0) + toc_count + 1

    # pass 1: lay the body out, remembering which page each heading lands on
    lay.new_page()
    for sec in sections:
        lay.heading(clean(sec.get("heading") or ""))
        lay.kpis(sec.get("kpis") or [])
        for para in sec.get("paragraphs") or []:
            lay.paragraph(para)
        if sec.get("bullets"):
            lay.bullets(sec["bullets"])
        for t in sec.get("tables") or []:
            if isinstance(t, dict):
                lay.table(t)
        lay.y -= 6
    if lay.closing:
        lay.new_page()
        lay.heading("Important notice")
        lay.paragraph(lay.disclaimer)
    body = lay.pages
    if not any(p.ops for p in body) and not want_cover and not toc_count:
        body[0].text(lay.left, lay.top - 16, clean(doc.get("title") or "Report"), True, 15, NAVY)

    # pass 2: the front pages now that every heading has a page number, then the running header and footer
    front = []
    if want_cover:
        cp = _Page()
        lay.cover(cp)
        front.append(cp)
    if toc_count:
        front.extend(lay.toc_pages(toc_count, len(front) + 1, lay.toc))
    pages = front + body
    total = len(pages)
    as_of = clean(doc.get("as_of") or "")
    header = clean(doc.get("header") or doc.get("title") or "")
    watermark = clean(doc.get("watermark") or "").strip()
    streams = []
    for i, p in enumerate(pages, start=1):
        ops = list(p.ops)
        if p.body:
            ops.append(f"BT /F1 8 Tf {_rgb(GREY)} rg {_n(lay.left)} {_n(lay.H - 36)} Td {_pdf_string(header)} Tj ET")
            ops.append(f"{_rgb(RULE)} RG 0.5 w {_n(lay.left)} {_n(lay.H - 42)} m {_n(lay.right)} {_n(lay.H - 42)} l S")
            ops.append(f"{_rgb(RULE)} RG 0.5 w {_n(lay.left)} 42 m {_n(lay.right)} 42 l S")
            foot = f"Page {i} of {total}"
            fw = text_width(foot, False, 8)
            ops.append(f"BT /F1 8 Tf {_rgb(GREY)} rg {_n(lay.right - fw)} 30 Td {_pdf_string(foot)} Tj ET")
            if as_of:
                ops.append(f"BT /F1 8 Tf {_rgb(GREY)} rg {_n(lay.left)} 30 Td {_pdf_string('As of ' + as_of)} Tj ET")
        for k, ln in enumerate(lay.foot_lines):
            ops.append(f"BT /F1 6.5 Tf {_rgb(GREY)} rg {_n(lay.left)} {_n(50 + (len(lay.foot_lines) - 1 - k) * 8)} Td "
                       f"{_pdf_string(ln)} Tj ET")
        if watermark:
            ops.append(_watermark(lay, watermark))
        streams.append("\n".join(ops).encode("cp1252"))
    return _assemble(streams, lay.W, lay.H, clean(doc.get("title") or ""))


def _assemble(streams, w, h, title):
    n_pages = len(streams)
    page_ids = [6 + 2 * i for i in range(n_pages)]
    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: ("<< /Type /Pages /Kids [" + " ".join(f"{pid} 0 R" for pid in page_ids)
            + f"] /Count {n_pages} >>").encode(),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        5: b"<< /Font << /F1 3 0 R /F2 4 0 R >> /ExtGState << /GS1 << /ca 0.16 /CA 0.16 >> >> "
           b"/ProcSet [/PDF /Text] >>",
    }
    for i, data in enumerate(streams):
        pid, cid = page_ids[i], page_ids[i] + 1
        objs[pid] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_n(w)} {_n(h)}] /Resources 5 0 R "
                     f"/Contents {cid} 0 R >>").encode()
        comp = zlib.compress(data, 9)
        objs[cid] = f"<< /Length {len(comp)} /Filter /FlateDecode >>\nstream\n".encode() + comp + b"\nendstream"
    info_id = 6 + 2 * n_pages
    utf16 = ("﻿" + (title or "Report")).encode("utf-16-be").hex().upper()
    objs[info_id] = f"<< /Title <{utf16}> /Producer (Land Planner) >>".encode()
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for num in range(1, info_id + 1):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {info_id + 1}\n".encode() + b"0000000000 65535 f \n"
    for num in range(1, info_id + 1):
        out += b"%010d 00000 n \n" % offsets[num]
    ident = hashlib.md5(bytes(out)).hexdigest().upper()
    out += (f"trailer\n<< /Size {info_id + 1} /Root 1 0 R /Info {info_id} 0 R /ID [<{ident}> <{ident}>] >>\n"
            f"startxref\n{xref}\n%%EOF").encode()
    return bytes(out)
