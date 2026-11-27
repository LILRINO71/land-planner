"""The report writer in landplanner/district/pdf.py. The file is parsed back by hand here (xref table, page
streams), and opened with PyMuPDF only when that happens to be installed; it is never required. All data is made up."""
import re
import unittest
import zlib

from support import ROOT  # noqa: F401  (puts the repo on sys.path)
from landplanner.district import pdf


def objects(data):
    """{object number: bytes of its body}, found through the xref table; checks every offset on the way."""
    assert data.startswith(b"%PDF-")
    m = re.search(rb"startxref\n(\d+)\n%%EOF$", data)
    assert m, "no startxref before the end"
    pos = int(m.group(1))
    assert data[pos:pos + 5] == b"xref\n", "startxref does not point at the xref table"
    head = re.match(rb"xref\n0 (\d+)\n", data[pos:])
    count = int(head.group(1))
    table = data[pos + head.end():pos + head.end() + 20 * count]
    assert len(table) == 20 * count
    out = {}
    for num in range(count):
        entry = table[num * 20:(num + 1) * 20]
        assert re.fullmatch(rb"\d{10} \d{5} [nf] \n", entry), entry
        if entry[17:18] == b"f":
            continue
        off = int(entry[:10])
        assert data[off:].startswith(b"%d 0 obj\n" % num), f"object {num} is not at offset {off}"
        end = data.index(b"endobj", off)
        out[num] = data[off + len(b"%d 0 obj\n" % num):end]
    trailer = data[data.index(b"trailer"):]
    assert int(re.search(rb"/Size (\d+)", trailer).group(1)) == count
    return out


def page_streams(data):
    """The decompressed content stream of every page, in page order."""
    objs = objects(data)
    kids = re.search(rb"/Kids \[([^\]]*)\]", objs[2]).group(1)
    streams = []
    for pid in re.findall(rb"(\d+) 0 R", kids):
        page = objs[int(pid)]
        assert b"/Type /Page " in page
        cid = int(re.search(rb"/Contents (\d+) 0 R", page).group(1))
        body = objs[cid]
        length = int(re.search(rb"/Length (\d+)", body).group(1))
        raw = body[body.index(b"stream\n") + 7:][:length]
        assert body[body.index(b"stream\n") + 7 + length:].startswith(b"\nendstream")
        streams.append(zlib.decompress(raw).decode("cp1252"))
    assert int(re.search(rb"/Count (\d+)", objs[2]).group(1)) == len(streams)
    return streams


def strings(stream):
    """The text shown by every Tj, as plain text."""
    out = []
    for m in re.finditer(r"\(((?:[^()\\]|\\.)*)\) Tj", stream):
        s = re.sub(r"\\(\d{3})", lambda k: bytes([int(k.group(1), 8)]).decode("cp1252"), m.group(1))
        out.append(re.sub(r"\\(.)", r"\1", s))
    return out


def sample_doc(**over):
    rows = [[f"Sample School {i}", 100 * i, i * 0.5, "Open"] for i in range(1, 121)]
    doc = {
        "title": "Sample District Report", "subtitle": "Round numbers only", "as_of": "2026-01-31",
        "watermark": "CONFIDENTIAL", "disclaimer": "Made-up sample data for testing.", "header": "Sample District",
        "cover": True, "toc": True,
        "sections": [
            {"heading": "Overview", "paragraphs": ["Sample District has 12,500 students. " * 30],
             "bullets": ["First point", "Second point " * 20],
             "kpis": [{"label": "Students", "value": 12500, "note": "up 2%"}, {"label": "Schools", "value": 14},
                      {"label": "Budget", "value": "$120,000,000"}]},
            {"heading": "Schools", "tables": [{"title": "All schools", "columns": ["School", "Students", "Share", "Status"],
                                               "rows": rows}]},
            {"heading": "Closing", "paragraphs": ["The end."]},
        ],
    }
    doc.update(over)
    return doc


class FileStructure(unittest.TestCase):
    def setUp(self):
        self.data = pdf.build_pdf(sample_doc())
        self.streams = page_streams(self.data)

    def test_starts_and_ends_like_a_pdf(self):
        self.assertTrue(self.data.startswith(b"%PDF-1."))
        self.assertTrue(self.data.endswith(b"%%EOF"))

    def test_xref_offsets_point_at_the_right_objects(self):
        objs = objects(self.data)         # raises if any offset is wrong
        self.assertIn(b"/Type /Catalog", objs[1])
        self.assertIn(b"/Helvetica-Bold", objs[4])

    def test_streams_are_compressed(self):
        self.assertIn(b"/FlateDecode", self.data)
        self.assertNotIn(b"Sample School 7", self.data)

    def test_page_count_matches_page_x_of_y(self):
        total = len(self.streams)
        self.assertGreater(total, 5)
        for i, s in enumerate(self.streams[1:], start=2):       # the cover has no number
            self.assertIn(f"Page {i} of {total}", strings(s))
        self.assertNotIn(f"Page 1 of {total}", strings(self.streams[0]))

    def test_the_as_of_date_is_in_every_footer(self):
        for s in self.streams[1:]:
            self.assertIn("As of 2026-01-31", strings(s))

    def test_running_header_on_every_numbered_page(self):
        for s in self.streams[1:]:
            self.assertIn("Sample District", strings(s))

    def test_watermark_is_on_every_page(self):
        for s in self.streams:
            self.assertIn("CONFIDENTIAL", strings(s))

    def test_disclaimer_is_at_the_foot_of_every_page(self):
        for s in self.streams:
            self.assertIn("Made-up sample data for testing.", strings(s))

    def test_no_watermark_when_none_is_given(self):
        for s in page_streams(pdf.build_pdf(sample_doc(watermark=""))):
            self.assertNotIn("CONFIDENTIAL", strings(s))
            self.assertNotIn("/GS1 gs", s)


class Layout(unittest.TestCase):
    def test_a_long_table_spans_pages_and_repeats_its_header(self):
        streams = page_streams(pdf.build_pdf(sample_doc(cover=False, toc=False)))
        with_header = [i for i, s in enumerate(streams) if "Students" in strings(s) and "Share" in strings(s)]
        self.assertGreaterEqual(len(with_header), 3)
        self.assertEqual(with_header, list(range(with_header[0], with_header[-1] + 1)))     # no page in between lacks it
        for i in with_header:
            self.assertGreaterEqual(sum(1 for t in strings(streams[i]) if t.startswith("Sample School")), 1)

    def test_every_row_is_whole_and_in_order(self):
        streams = page_streams(pdf.build_pdf(sample_doc(cover=False, toc=False)))
        names = [t for s in streams for t in strings(s) if t.startswith("Sample School")]
        self.assertEqual(names, [f"Sample School {i}" for i in range(1, 121)])

    def test_contents_page_numbers_are_the_real_ones(self):
        streams = page_streams(pdf.build_pdf(sample_doc()))
        toc = strings(streams[1])
        self.assertEqual(toc[0], "Contents")
        listed = {h: int(toc[toc.index(h) + 1]) for h in ("Overview", "Schools", "Closing")}
        for heading, number in listed.items():
            on_page = strings(streams[number - 1])
            self.assertIn(heading, on_page)
        self.assertLessEqual(listed["Overview"], listed["Schools"])
        self.assertLess(listed["Schools"], listed["Closing"])

    def test_cover_page_carries_title_subtitle_and_date(self):
        cover = strings(page_streams(pdf.build_pdf(sample_doc()))[0])
        for want in ("Sample District Report", "Round numbers only", "As of 2026-01-31"):
            self.assertIn(want, cover)

    def test_without_cover_or_toc_the_report_starts_on_page_one(self):
        streams = page_streams(pdf.build_pdf(sample_doc(cover=False, toc=False)))
        self.assertIn("Page 1 of %d" % len(streams), strings(streams[0]))
        self.assertIn("Overview", strings(streams[0]))

    def test_a_long_disclaimer_goes_on_a_closing_page(self):
        long_text = "This report is a made-up sample and is not advice. " * 20
        streams = page_streams(pdf.build_pdf(sample_doc(disclaimer=long_text)))
        notice = [i for i, s in enumerate(streams) if i > 1 and "Important notice" in strings(s)]
        self.assertEqual(notice, [len(streams) - 1])
        self.assertNotIn("Important notice", strings(streams[2]))
        toc = strings(streams[1])
        self.assertEqual(int(toc[toc.index("Important notice") + 1]), len(streams))

    def test_a4_page_size(self):
        data = pdf.build_pdf(sample_doc(page_size="a4"))
        self.assertIn(b"/MediaBox [0 0 595.28 841.89]", data)
        self.assertIn(b"/MediaBox [0 0 612 792]", pdf.build_pdf(sample_doc()))

    def test_a_long_toc_gets_more_pages_and_still_lines_up(self):
        sections = [{"heading": f"Part {i}", "paragraphs": ["x"]} for i in range(60)]
        streams = page_streams(pdf.build_pdf(sample_doc(sections=sections)))
        flat = [t for s in streams[1:4] for t in strings(s)]
        for i in (0, 59):
            number = int(flat[flat.index(f"Part {i}") + 1])
            self.assertIn(f"Part {i}", strings(streams[number - 1]))
            self.assertEqual(sum(t == f"Part {i}" for t in strings(streams[number - 1])), 1)

    def test_text_is_wrapped_inside_the_margins(self):
        lines = pdf.wrap("word " * 200, False, 10, 300)
        self.assertGreater(len(lines), 5)
        for ln in lines:
            self.assertLessEqual(pdf.text_width(ln, False, 10), 300.01)
        for ln in pdf.wrap("x" * 100, False, 10, 60):
            self.assertLessEqual(pdf.text_width(ln, False, 10), 60.01)

    def test_a_huge_cell_does_not_break_the_page(self):
        table = {"columns": ["A", "B"], "rows": [["word " * 3000, "ok"], ["next", "row"]]}
        streams = page_streams(pdf.build_pdf({"sections": [{"heading": "H", "tables": [table]}]}))
        self.assertTrue(any("next" in strings(s) for s in streams))

    def test_an_empty_document_is_still_a_valid_pdf(self):
        for doc in ({}, {"sections": []}, None):
            streams = page_streams(pdf.build_pdf(doc))
            self.assertGreaterEqual(len(streams), 1)


class Wrapping(unittest.TestCase):
    def test_long_ids_break_after_a_hyphen_underscore_or_slash(self):
        for sep in "-_/":
            word = sep.join(["SEGMENTONE", "SEGMENTTWO", "SEGMENTTHREE", "SEGMENTFOUR"])
            lines = pdf.wrap(word, False, 10, 110)
            self.assertEqual("".join(lines), word)
            self.assertTrue(all(ln.endswith(sep) for ln in lines[:-1]), lines)
            self.assertTrue(all(ln.startswith("SEGMENT") for ln in lines), lines)

    def test_a_word_with_no_break_point_is_still_split_to_fit(self):
        lines = pdf.wrap("W" * 60, False, 10, 100)
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(pdf.text_width(ln, False, 10) <= 100.01 for ln in lines))

    def test_long_headings_and_table_titles_wrap_inside_the_margins(self):
        long = "A very long heading about the corridor districts and neighborhoods of the sample area " * 2
        doc = {"sections": [{"heading": long, "tables": [{"title": long, "columns": ["A"], "rows": [["x"]]}]}]}
        streams = page_streams(pdf.build_pdf(doc))
        seen = 0
        for s in streams:
            for m in re.finditer(r"/F2 (15|10\.5) Tf [\d. ]+ rg ([\d.]+) [\d.]+ Td \(((?:[^()\\]|\\.)*)\)", s):
                seen += 1
                self.assertLessEqual(float(m.group(2)) + pdf.text_width(m.group(3), True, float(m.group(1))), 558.5)
        self.assertGreaterEqual(seen, 4)

    def test_small_notes_and_word_alignment(self):
        doc = {"sections": [{"heading": "H", "small": ["A small note."], "tables": [
            {"columns": ["A", "B"], "rows": [["x", 1]], "align": ["left", "right"]}]}]}
        self.assertIn("A small note.", strings(page_streams(pdf.build_pdf(doc))[0]))


class Widths(unittest.TestCase):
    def test_known_helvetica_widths(self):
        self.assertAlmostEqual(pdf.text_width("Hello", False, 10), 22.78, delta=0.01)      # H722 e556 l222 l222 o556
        self.assertEqual(sum(pdf._char_w(c, False) for c in "Hello"), 722 + 556 + 222 + 222 + 556)
        self.assertEqual(sum(pdf._char_w(c, True) for c in "Hello"), 722 + 556 + 278 + 278 + 611)
        self.assertEqual(pdf._char_w(" ", False), 278)
        self.assertEqual(pdf._char_w("\u00e9", False), 556)       # accented letters are as wide as the plain one

    def test_bold_is_wider_than_regular_for_text(self):
        self.assertGreater(pdf.text_width("Enrollment report", True, 10), pdf.text_width("Enrollment report", False, 10))


class Characters(unittest.TestCase):
    def test_common_characters_are_mapped(self):
        self.assertEqual(pdf.clean("\u201cquote\u201d \u2018a\u2019 \u2013 \u2014 \u2022 \u00b1 \u00d7 \u00f7"),
                         "\u201cquote\u201d \u2018a\u2019 \u2013 \u2014 \u2022 \u00b1 \u00d7 \u00f7")
        self.assertEqual(pdf.clean("a \u2264 b \u2265 c \u2192 d \u2260 e"), "a <= b >= c -> d != e")

    def test_the_rest_become_question_marks(self):
        self.assertEqual(pdf.clean("ok \U0001F600 \u4e2d"), "ok ? ?")
        self.assertEqual(pdf.clean("\u2713 \u4e2d"), "yes ?")

    def test_latin_extended_letters_fall_back_to_their_base_letter(self):
        self.assertEqual(pdf.clean("Łódź ąę đ"), "Lódz ae d")
        self.assertEqual(pdf.clean("čř ě ő"), "cr e o")

    def test_control_characters_are_dropped_to_spaces(self):
        self.assertEqual(pdf.clean("a\x00b\x1fc"), "a b c")

    def test_unicode_everywhere_does_not_raise_or_corrupt(self):
        wild = "\u2192 \U0001F600 \u4e2d\u6587 \u2264 \u201cq\u201d (paren) \\ back\\slash \u00e9 \ud7ff \x00 \u202e"
        doc = {"title": wild, "subtitle": wild, "as_of": wild, "header": wild, "watermark": wild, "disclaimer": wild,
               "cover": True, "toc": True,
               "sections": [{"heading": wild, "paragraphs": [wild], "bullets": [wild],
                             "kpis": [{"label": wild, "value": wild, "note": wild}],
                             "tables": [{"title": wild, "columns": [wild, "b"], "rows": [[wild, None], [1.5, True]]}]}]}
        data = pdf.build_pdf(doc)
        streams = page_streams(data)       # raises when the file is malformed
        self.assertTrue(any("(paren)" in " ".join(strings(s)) for s in streams))
        self.assertTrue(any("back\\slash" in " ".join(strings(s)) for s in streams))
        for s in streams:
            s.encode("cp1252")


class Tables(unittest.TestCase):
    def test_numbers_are_right_aligned_and_text_left(self):
        table = {"columns": ["Name", "Count"], "rows": [["Sample A", 5], ["Sample B", 12000]]}
        stream = page_streams(pdf.build_pdf({"sections": [{"heading": "H", "tables": [table]}]}))[0]
        pos = {}
        for m in re.finditer(r"/F\d [\d.]+ Tf [\d. ]+ rg ([\d.]+) ([\d.]+) Td \(([^)]*)\) Tj", stream):
            pos[m.group(3)] = float(m.group(1))
        # the right edges of "5" and "12,000" line up; the two names start at the same x
        edge5 = pos["5"] + pdf.text_width("5", False, 8.5)
        edge12 = pos["12,000"] + pdf.text_width("12,000", False, 8.5)
        self.assertAlmostEqual(edge5, edge12, places=1)
        self.assertEqual(pos["Sample A"], pos["Sample B"])

    def test_explicit_alignment_and_weights_are_honoured(self):
        table = {"columns": ["A", "B"], "rows": [["x", "y"]], "align": ["r", "c"], "col_widths": [1, 3]}
        data = pdf.build_pdf({"sections": [{"heading": "H", "tables": [table]}]})
        page_streams(data)

    def test_short_rows_and_bad_cells_are_tolerated(self):
        table = {"columns": ["A", "B", "C"], "rows": [["only one"], [None, float("nan"), object()], []]}
        page_streams(pdf.build_pdf({"sections": [{"heading": "H", "tables": [table]}]}))


class OpenedByAReader(unittest.TestCase):
    """Only when PyMuPDF happens to be installed; it is not a dependency and these skip cleanly without it."""

    @classmethod
    def setUpClass(cls):
        try:
            import pymupdf
        except ImportError:
            raise unittest.SkipTest("PyMuPDF is not installed")
        cls.pymupdf = pymupdf

    def test_page_count_and_text(self):
        data = pdf.build_pdf(sample_doc())
        doc = self.pymupdf.open(stream=data, filetype="pdf")
        self.assertEqual(len(doc), len(page_streams(data)))
        last = len(doc)
        for i, page in enumerate(doc, start=1):
            text = page.get_text()
            self.assertIn("CONFIDENTIAL", text)
            if i > 1:
                self.assertIn(f"Page {i} of {last}", text)
        self.assertIn("Sample District Report", doc[0].get_text())
        self.assertIn("Sample School 120", "".join(p.get_text() for p in doc))

    def test_unicode_input_opens(self):
        data = pdf.build_pdf(sample_doc(title="Report \u2192 \U0001F600 \u201cq\u201d"))
        doc = self.pymupdf.open(stream=data, filetype="pdf")
        self.assertIn("Report -> ?", doc[0].get_text())


if __name__ == "__main__":
    unittest.main()
