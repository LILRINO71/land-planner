"""The workbook and CSV reader/writer in landplanner/district/xlsx.py, tried on small made-up sheets ("Sample
District", round numbers). Nothing here reaches the network."""
import io
import unittest
import zipfile
from xml.etree import ElementTree as ET

from support import ROOT  # noqa: F401  (puts the repo on sys.path)
from landplanner.district import xlsx

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def hand_made(sheet_xml, styles=None, shared=None, workbook_extra="", extra_parts=None):
    """A minimal workbook built by hand, the way Excel lays it out, to test what write_workbook never makes."""
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    parts = {
        "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "xl/workbook.xml": f'<workbook {ns} {rel}>{workbook_extra}<sheets><sheet name="Data" sheetId="1" r:id="rId1"/>'
                           f'</sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                                      'relationships"><Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/>'
                                      '</Relationships>',
        "xl/worksheets/sheet1.xml": f'<worksheet {ns}><sheetData>{sheet_xml}</sheetData></worksheet>',
    }
    if styles:
        parts["xl/styles.xml"] = f'<styleSheet {ns}>{styles}</styleSheet>'
    if shared is not None:
        parts["xl/sharedStrings.xml"] = f'<sst {ns}>{shared}</sst>'
    parts.update(extra_parts or {})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in parts.items():
            z.writestr(k, v)
    return buf.getvalue()


class RoundTrip(unittest.TestCase):
    def test_what_is_written_is_what_is_read(self):
        sheets = {
            "Enrollment": [["Grade", "Students", "Share", "Open"],
                           ["K", 100, 0.25, True],
                           ["1", 150, 0.375, False],
                           ["Total", 250, 1, None]],
            "Notes": [["Note"], ["Sample District, round numbers only"], [], ["after a gap", None, "third column"]],
        }
        back = xlsx.read_workbook(xlsx.write_workbook(sheets))
        self.assertEqual(list(back), ["Enrollment", "Notes"])
        self.assertEqual(back["Enrollment"][:3], sheets["Enrollment"][:3])
        self.assertEqual(back["Enrollment"][3], ["Total", 250, 1])
        self.assertEqual(back["Notes"], sheets["Notes"])
        self.assertIsInstance(back["Enrollment"][1][1], int)
        self.assertIs(back["Enrollment"][1][3], True)

    def test_text_with_markup_unicode_and_spaces_survives(self):
        rows = [["H"], ["a < b & c > d"], ['quote " and \' mark'], ["  padded  "], ["two\nlines"], ["café → €"]]
        self.assertEqual(xlsx.read_workbook(xlsx.write_workbook({"S": rows}))["S"], rows)

    def test_control_characters_are_dropped_not_fatal(self):
        back = xlsx.read_workbook(xlsx.write_workbook({"S": [["H"], ["bad\x00\x07char"]]}))
        self.assertEqual(back["S"][1], ["badchar"])

    def test_an_empty_workbook_still_opens(self):
        self.assertEqual(xlsx.read_workbook(xlsx.write_workbook({"Empty": []})), {"Empty": []})
        self.assertEqual(list(xlsx.read_workbook(xlsx.write_workbook({}))), ["Sheet1"])

    def test_dates_written_from_python_come_back_as_iso_text(self):
        import datetime
        data = xlsx.write_workbook({"S": [["When"], [datetime.date(2026, 1, 31)],
                                          [datetime.datetime(2026, 1, 31, 14, 30)]]})
        self.assertEqual(xlsx.read_workbook(data)["S"][1:], [["2026-01-31"], ["2026-01-31T14:30:00"]])

    def test_huge_integers_keep_every_digit(self):
        back = xlsx.read_workbook(xlsx.write_workbook({"S": [["H"], [12345678901234567890]]}))
        self.assertEqual(back["S"][1], ["12345678901234567890"])


class WrittenFile(unittest.TestCase):
    def setUp(self):
        self.data = xlsx.write_workbook({"Sheet": [["Name", "Count"], ["Sample School", 100], ["=1+1", "@home"], ["-5", "+x"]]},
                                        widths={0: 30, "B": 12})
        self.zf = zipfile.ZipFile(io.BytesIO(self.data))

    def test_every_part_is_well_formed_and_declared(self):
        names = self.zf.namelist()
        self.assertEqual(names[0], "[Content_Types].xml")
        for n in names:
            ET.fromstring(self.zf.read(n))
        types = self.zf.read("[Content_Types].xml").decode()
        for part in ("/xl/workbook.xml", "/xl/worksheets/sheet1.xml", "/xl/styles.xml", "/xl/sharedStrings.xml"):
            self.assertIn(part, types)

    def test_first_row_is_bold_and_frozen(self):
        sheet = self.zf.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn('state="frozen"', sheet)
        self.assertIn('ySplit="1"', sheet)
        root = ET.fromstring(sheet)
        row1 = root.find(f".//{NS}row[@r='1']")
        self.assertTrue(all(c.get("s") == "1" for c in row1))
        self.assertIn("<b/>", self.zf.read("xl/styles.xml").decode())

    def test_numbers_are_numbers(self):
        root = ET.fromstring(self.zf.read("xl/worksheets/sheet1.xml"))
        cell = root.find(f".//{NS}c[@r='B2']")
        self.assertIsNone(cell.get("t"))
        self.assertEqual(cell.find(f"{NS}v").text, "100")

    def test_formula_looking_text_is_text_and_never_a_formula(self):
        sheet = self.zf.read("xl/worksheets/sheet1.xml").decode()
        self.assertNotIn("<f>", sheet)
        root = ET.fromstring(sheet)
        for ref in ("A3", "B3", "A4", "B4"):
            c = root.find(f".//{NS}c[@r='{ref}']")
            self.assertEqual(c.get("t"), "s", ref)
        back = xlsx.read_workbook(self.data)["Sheet"]
        self.assertEqual(back[2:], [["=1+1", "@home"], ["-5", "+x"]])

    def test_column_widths(self):
        sheet = self.zf.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn('<col min="1" max="1" width="30" customWidth="1"/>', sheet)
        self.assertIn('<col min="2" max="2" width="12" customWidth="1"/>', sheet)

    def test_widths_can_be_given_per_sheet(self):
        data = xlsx.write_workbook({"A": [["x"]], "B": [["y"]]}, widths={"B": {0: 40}})
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertNotIn("<cols>", z.read("xl/worksheets/sheet1.xml").decode())
        self.assertIn('width="40"', z.read("xl/worksheets/sheet2.xml").decode())


class SheetNames(unittest.TestCase):
    def names(self, given):
        return list(xlsx.read_workbook(xlsx.write_workbook({k: [["x"]] for k in given})))

    def test_excels_rules(self):
        got = self.names(["A/B:C*D?E[F]G\\H", "x" * 50, "'quoted'", ""])
        self.assertEqual(got[0], "A B C D E F G H")
        self.assertEqual(len(got[1]), 31)
        self.assertEqual(got[2], "quoted")
        self.assertEqual(got[3], "Sheet")
        for n in got:
            self.assertFalse(set(n) & set("[]:*?/\\"))

    def test_names_that_collide_after_cleaning_stay_distinct(self):
        got = self.names(["a/b", "a:b", "A?B", "y" * 40, "y" * 45])
        self.assertEqual(len({n.lower() for n in got}), 5)
        self.assertTrue(all(len(n) <= 31 for n in got))


class HandMadeWorkbooks(unittest.TestCase):
    def test_shared_inline_numbers_booleans_errors_and_gaps(self):
        sheet = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="inlineStr"><is><t>inline</t></is></c></row>'
                 '<row r="3"><c r="B3"><v>2.5</v></c><c r="D3" t="b"><v>1</v></c><c r="E3" t="e"><v>#DIV/0!</v></c>'
                 '<c r="F3" t="str"><f>A1</f><v>from formula</v></c><c r="G3"><v>1E+3</v></c></row>')
        rich = '<si><r><t>Sample </t></r><r><t>District</t></r><rPh><t>ignored</t></rPh></si>'
        back = xlsx.read_workbook(hand_made(sheet, shared=rich))["Data"]
        self.assertEqual(back[0], ["Sample District", None, "inline"])
        self.assertEqual(back[1], [])
        self.assertEqual(back[2], [None, 2.5, None, True, "#DIV/0!", "from formula", 1000])

    def test_dates_by_builtin_and_custom_format(self):
        styles = ('<numFmts count="2"><numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd hh:mm"/>'
                  '<numFmt numFmtId="165" formatCode="0.00&quot; m&quot;"/></numFmts>'
                  '<cellXfs count="4"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/><xf numFmtId="165"/></cellXfs>')
        sheet = ('<row r="1"><c r="A1" s="1"><v>46053</v></c><c r="B1" s="2"><v>46053.5</v></c>'
                 '<c r="C1" s="3"><v>46053</v></c><c r="D1" s="0"><v>46053</v></c><c r="E1" s="1"><v>0.5</v></c></row>')
        row = xlsx.read_workbook(hand_made(sheet, styles=styles))["Data"][0]
        self.assertEqual(row, ["2026-01-31", "2026-01-31T12:00:00", 46053, 46053, "12:00:00"])

    def test_the_1904_date_system(self):
        sheet = '<row r="1"><c r="A1" s="1"><v>0</v></c></row>'
        styles = '<cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs>'
        data = hand_made(sheet, styles=styles, workbook_extra='<workbookPr date1904="1"/>')
        self.assertEqual(xlsx.read_workbook(data)["Data"], [["1904-01-01"]])

    def test_sheets_come_back_in_workbook_order(self):
        names = ["Zebra", "Apple", "Mango"]
        data = xlsx.write_workbook({n: [[n]] for n in names})
        self.assertEqual(list(xlsx.read_workbook(data)), names)


class Refusals(unittest.TestCase):
    def refuses(self, data, *words, **limits):
        with self.assertRaises(ValueError) as cm:
            xlsx.read_workbook(data, **limits)
        msg = str(cm.exception).lower()
        for w in words:
            self.assertIn(w, msg)
        return msg

    def test_not_a_workbook(self):
        self.refuses(b"just some text, not a spreadsheet", "not an excel workbook")
        self.refuses(b"", "not an excel workbook")
        self.refuses(self._zip({"readme.txt": "hi"}), "not an excel workbook")

    def test_old_xls(self):
        self.refuses(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600, ".xls", "save as")

    def test_password_protected(self):
        marker = "EncryptedPackage".encode("utf-16-le")
        self.refuses(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100 + marker + b"\x00" * 100, "password")

    def test_damaged_sheet(self):
        data = hand_made("")
        z = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(z, "w") as out:
            for n in src.namelist():
                out.writestr(n, "<worksheet><sheetData><row" if n.endswith("sheet1.xml") else src.read(n))
        self.refuses(z.getvalue(), "damaged")

    def test_zip_bomb_guard_on_size(self):
        rows = [[f"{r}-{c}-" + "x" * 1000 for c in range(20)] for r in range(100)]
        data = xlsx.write_workbook({"S": rows})
        self.assertEqual(len(xlsx.read_workbook(data)["S"]), 100)
        self.refuses(data, "far more data", max_uncompressed=100_000)

    def test_row_cap(self):
        data = xlsx.write_workbook({"S": [[i] for i in range(50)]})
        self.assertEqual(len(xlsx.read_workbook(data, max_rows=50)["S"]), 50)
        self.refuses(data, "more than 10 rows", max_rows=10)

    @staticmethod
    def _zip(parts):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for k, v in parts.items():
                z.writestr(k, v)
        return buf.getvalue()


class Csv(unittest.TestCase):
    def test_comma_with_quotes(self):
        data = b'Name,Note\r\nSample,"has, comma"\r\nOther,"two ""quoted"" words"\r\n'
        self.assertEqual(xlsx.read_csv(data), [["Name", "Note"], ["Sample", "has, comma"], ["Other", 'two "quoted" words']])

    def test_semicolon_and_tab(self):
        self.assertEqual(xlsx.read_csv(b"a;b;c\n1,5;2;3\n"), [["a", "b", "c"], ["1,5", "2", "3"]])
        self.assertEqual(xlsx.read_csv(b"a\tb\n1\t2\n"), [["a", "b"], ["1", "2"]])

    def test_utf8_bom_is_removed(self):
        self.assertEqual(xlsx.read_csv("﻿name,city\nA,Zürich\n".encode("utf-8")),
                         [["name", "city"], ["A", "Zürich"]])

    def test_windows_1252_fallback(self):
        self.assertEqual(xlsx.read_csv("name,city\nA,Zürich €5\n".encode("cp1252")),
                         [["name", "city"], ["A", "Zürich €5"]])

    def test_one_column_and_empty(self):
        self.assertEqual(xlsx.read_csv(b"just\nwords\n"), [["just"], ["words"]])
        self.assertEqual(xlsx.read_csv(b""), [])


if __name__ == "__main__":
    unittest.main()
