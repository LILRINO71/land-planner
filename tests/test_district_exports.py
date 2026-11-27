"""The Excel and PDF exports in landplanner/district/exports.py, run through the real writers on an invented
"Sample District" (round numbers). Nothing here reaches the network."""
import io
import re
import unittest
import zipfile

from test_district_pdf import page_streams, strings
from landplanner.district import exports, pdf, xlsx
from landplanner.district.schema import ENTITIES

PROJECT = {"id": "sample-district", "name": "Sample District", "branding": {"subtitle": "Invented numbers"}}
LONG_HEADING = "Districts along the corridor (page 5: Sample Parkway: Districts and Neighborhoods) and their long names"
LONG_ID = "A-SRS-LEAKAGE-ACTIONABLE-ITEM-WITH-A-VERY-LONG-REGISTER-IDENTIFIER-NUMBER-ONE-TWO-THREE-FOUR"


def content():
    ents = {name: [] for name in ENTITIES}
    ents["phases"] = [{"id": "p1", "label": "Phase 1", "order": 1, "land_cost_usd": 1000000, "note": "x" * 120},
                      {"id": "p2", "label": "Phase 2", "order": 2, "land_cost_usd": 2000000}]
    ents["assumptions"] = [{"id": "A-ACRES", "label": "Gross acres", "value": 100, "unit": "acres",
                            "provenance": "sample", "source_doc": "Sample doc"}]
    ents["sections"] = [
        {"id": "s1", "module": "overview", "order": 1, "kind": "text", "heading": LONG_HEADING,
         "body": "Plain text. " + LONG_ID, "note": "Invented note about this section.", "cites": ["A-ACRES"]},
        {"id": "s2", "module": "overview", "order": 2, "kind": "qa", "heading": "Questions",
         "items": [{"question": "How many acres?", "answer": "One hundred.", "cites": ["A-ACRES", "A-OTHER"]}]},
        {"id": "s3", "module": "overview", "order": 3, "kind": "table", "heading": "Table",
         "columns": ["Name", "Count"], "rows": [["Sample", 100]]},
    ]
    return {"entities": ents}


MODULES = [{"id": "overview", "label": "Overview", "banner": "Sample data only.",
            "cards": [{"label": "Gross acres", "assumption": "A-ACRES"}]}]


class Excel(unittest.TestCase):
    def setUp(self):
        self.data, _ = exports.table_xlsx(PROJECT, content(), "all", "internal", "2026-01-31", "Sample disclaimer.")
        self.zf = zipfile.ZipFile(io.BytesIO(self.data))
        self.sheets = re.findall(r'<sheet name="([^"]+)"', self.zf.read("xl/workbook.xml").decode())

    def sheet_xml(self, name):
        return self.zf.read(f"xl/worksheets/sheet{self.sheets.index(name) + 1}.xml").decode()

    def test_header_is_on_row_five_and_that_row_is_frozen_and_bold(self):
        xml = self.sheet_xml("phases")
        self.assertIn('ySplit="5"', xml)
        self.assertIn('topLeftCell="A6"', xml)
        row5 = re.search(r'<row r="5">(.*?)</row>', xml).group(1)
        self.assertTrue(all(' s="1"' in c for c in re.findall(r"<c [^>]*>", row5)))
        self.assertNotIn(' s="1"', re.search(r'<row r="1">(.*?)</row>', xml).group(1))

    def test_the_about_sheet_keeps_row_one_as_its_header(self):
        self.assertIn('ySplit="1"', self.sheet_xml("About"))

    def test_column_widths_follow_content_and_are_capped(self):
        widths = [float(w) for w in re.findall(r'<col [^>]*width="([\d.]+)"', self.sheet_xml("phases"))]
        self.assertTrue(widths)
        self.assertTrue(all(exports.MIN_WIDTH <= w <= exports.MAX_WIDTH for w in widths))
        self.assertEqual(max(widths), exports.MAX_WIDTH)          # the 120-character note is capped
        self.assertLess(min(widths), 20)

    def test_values_round_trip_and_the_banner_is_there(self):
        rows = xlsx.read_workbook(self.data)["phases"]
        self.assertIn("CONFIDENTIAL", rows[0][0])
        self.assertEqual(rows[4][:2], ["id", "label"])
        self.assertEqual(rows[5][0], "p1")
        self.assertEqual(rows[6][rows[4].index("land_cost_usd")], 2000000)


class Pdf(unittest.TestCase):
    def setUp(self):
        data, _ = exports.module_pdf(PROJECT, MODULES, content(), "overview", "partner", "2026-01-31",
                                     "Sample disclaimer.")
        self.streams = page_streams(data)
        self.text = [t for s in self.streams for t in strings(s)]

    def test_a_long_heading_wraps_inside_the_page(self):
        lines = pdf.wrap(LONG_HEADING, True, 15, 504)
        self.assertGreater(len(lines), 1)
        self.assertIn(lines[0], self.text)
        self.assertIn(lines[-1], self.text)
        for s in self.streams:
            for m in re.finditer(r"/F2 15 Tf [\d. ]+ rg ([\d.]+) [\d.]+ Td \(((?:[^()\\]|\\.)*)\)", s):
                self.assertLessEqual(float(m.group(1)) + pdf.text_width(m.group(2), True, 15), 558.5)

    def test_the_section_note_is_printed_in_small_type(self):
        self.assertIn("Invented note about this section.", self.text)
        page = next(s for s in self.streams if "Invented note" in s)
        self.assertRegex(page, r"/F1 7\.5 Tf [\d. ]+ rg [\d.]+ [\d.]+ Td \(Invented note")

    def test_qa_cites_appear_as_a_figures_line(self):
        self.assertIn("Figures: A-ACRES, A-OTHER", self.text)

    def test_long_ids_break_after_hyphens_and_nothing_is_lost(self):
        parts = [t for t in self.text if "-" in t and t == t.upper() and t.startswith(("A-SRS", "ACTIONABLE", "ITEM",
                                                                                      "WITH", "A-VERY", "VERY", "LONG",
                                                                                      "REGISTER", "IDENTIFIER", "NUMBER",
                                                                                      "ONE", "TWO", "THREE", "FOUR"))]
        self.assertTrue(parts)
        self.assertTrue(any(p.endswith("-") for p in parts))
        self.assertIn(LONG_ID.replace("-", ""), "".join(self.text).replace("-", "").replace(" ", ""))
