"""Filtering, sorting and summing up parcels: plain lists in, plain lists out."""
import unittest

from support import row
from landplanner import lands as L

ROWS = [
    dict(row("100000001", 50.0, "R-1", True, 900, "9 Oak Ave"), zoning_kind="homes"),
    dict(row("100000002", 120.5, "C-1", False, 5000, "1 Main St"), zoning_kind="shops"),
    dict(row("100000003", 12.0, "LDR - 1 & RM", True, None), zoning_kind="mixed"),
    dict(row("100000004", 30.0, "", False, 100), zoning_kind="other"),
    dict(row("372100001", 142.1, "EDC-CC", True, 2367454), zoning_kind="edc"),
]


def apns(rows):
    return [r["apn"] for r in rows]


class Filtering(unittest.TestCase):
    def test_no_filter_keeps_everything(self):
        self.assertEqual(len(L.filter_parcels(ROWS)), 5)

    def test_acres(self):
        self.assertEqual(apns(L.filter_parcels(ROWS, min_acres=50)), ["100000001", "100000002", "372100001"])
        self.assertEqual(apns(L.filter_parcels(ROWS, max_acres=30)), ["100000003", "100000004"])
        self.assertEqual(apns(L.filter_parcels(ROWS, min_acres=30, max_acres=120.5)), ["100000001", "100000002", "100000004"])
        self.assertEqual(L.filter_parcels(ROWS, min_acres=1000), [])
        self.assertEqual(L.filter_parcels([dict(ROWS[0], acres=None)], min_acres=1), [], "no size listed never passes a size filter")

    def test_zoning_code_matches_any_zone_on_the_parcel(self):
        self.assertEqual(apns(L.filter_parcels(ROWS, zoning="EDC-CC")), ["372100001"])
        self.assertEqual(apns(L.filter_parcels(ROWS, zoning="RM")), ["100000003"])
        self.assertEqual(apns(L.filter_parcels(ROWS, zoning="ldr-1")), ["100000003"], "spaces round the dash and case do not matter")
        self.assertEqual(L.filter_parcels(ROWS, zoning="R"), [], "a code is matched whole, not as a prefix")

    def test_zoning_family(self):
        self.assertEqual(apns(L.filter_parcels(ROWS, kind="homes")), ["100000001"])
        self.assertEqual(apns(L.filter_parcels(ROWS, kind="other")), ["100000004"])

    def test_vacant(self):
        self.assertEqual(apns(L.filter_parcels(ROWS, vacant=True)), ["100000001", "100000003", "372100001"])

    def test_search_by_parcel_number_with_or_without_dashes(self):
        self.assertEqual(apns(L.filter_parcels(ROWS, q="372-100-001")), ["372100001"])
        self.assertEqual(apns(L.filter_parcels(ROWS, q="372 100")), ["372100001"])
        self.assertEqual(apns(L.filter_parcels(ROWS, q="00000")), ["100000001", "100000002", "100000003", "100000004"])
        self.assertEqual(L.filter_parcels(ROWS, q="555"), [])

    def test_search_also_finds_an_address(self):
        self.assertEqual(apns(L.filter_parcels(ROWS, q="main")), ["100000002"])
        self.assertEqual(L.filter_parcels(ROWS, q="zzz"), [])

    def test_a_search_of_only_digits_spaces_and_dashes_is_a_parcel_number(self):
        for text in ("372-100-001", "372 100 001", " 372100001 ", "372-100"):
            self.assertEqual(apns(L.filter_parcels(ROWS, q=text)), ["372100001"], text)
        self.assertTrue(L.is_number_search("372 - 100") and not L.is_number_search("zzz 1") and not L.is_number_search("TR 37668"))
        self.assertFalse(L.is_number_search("") or L.is_number_search("- -"))

    def test_words_never_turn_into_a_parcel_number(self):
        # the digits of "zzz 1" or "Garbani 2" used to be matched against every parcel number
        self.assertEqual(L.filter_parcels(ROWS, q="zzz 1"), [])
        self.assertEqual(L.filter_parcels(ROWS, q="main 3"), [])
        self.assertEqual(apns(L.filter_parcels(ROWS, q="oak 9")), ["100000001"])

    def test_every_word_must_be_in_the_rows_own_text_in_any_order_and_punctuation_is_ignored(self):
        rows = [dict(row("100000001", 50.0, "RR2 & RR5", True, 900, "27875 GARBANI RD MENIFEE  CA 92584"), subdivision="TR 37668",
                     zoning_name="Rural Residential, 2-acre minimum + Rural Residential, 5-acre minimum"),
                dict(row("100000002", 40.0, "LDR-2", True, 900, "29903 GARBANI RD MENIFEE  CA 92584"), subdivision="PM 39197"),
                dict(row("100000003", 30.0, "OS-R", True, 900, ""), subdivision="TR 37668")]
        found = lambda q: apns(L.filter_parcels(rows, q=q))  # noqa: E731
        self.assertEqual(found("Map TR 37668"), ["100000001", "100000003"], "the list writes a recorded map as Map TR 37668")
        self.assertEqual(found("Garbani 27875"), ["100000001"])
        self.assertEqual(found("27875 Garbani"), ["100000001"])
        self.assertEqual(found("Garbani, Menifee"), ["100000001", "100000002"])
        self.assertEqual(found("garbani rd; menifee."), ["100000001", "100000002"])
        self.assertEqual(found("2-acre minimum"), ["100000001"], "the zone's name is part of the row's text")
        self.assertEqual(found("rr2"), ["100000001"])
        self.assertEqual(found("zzz 1"), [])
        self.assertEqual(found("Garbani 99999"), [])
        self.assertEqual(found("Garbani 2"), ["100000001", "100000002"], "words and numbers are all looked for in the text, not in the parcel numbers")
        self.assertEqual(found("tr 37668 garbani"), ["100000001"])
        self.assertEqual(found("..."), apns(rows), "a search of only marks narrows nothing")

    def test_filters_combine(self):
        self.assertEqual(apns(L.filter_parcels(ROWS, min_acres=40, vacant=True, kind="edc", q="372")), ["372100001"])
        self.assertEqual(L.filter_parcels(ROWS, min_acres=40, vacant=True, kind="shops"), [])


class Sorting(unittest.TestCase):
    def test_acres_both_ways(self):
        self.assertEqual(apns(L.sort_parcels(ROWS)), ["372100001", "100000002", "100000001", "100000004", "100000003"])
        self.assertEqual(apns(L.sort_parcels(ROWS, "acres", False)), ["100000003", "100000004", "100000001", "100000002", "372100001"])

    def test_parcel_number_and_zoning(self):
        self.assertEqual(apns(L.sort_parcels(ROWS, "apn", False))[0], "100000001")
        self.assertEqual(apns(L.sort_parcels(ROWS, "apn", True))[0], "372100001")
        by_zone = L.sort_parcels(ROWS, "zoning", False)
        self.assertEqual([r["zoning"] for r in by_zone], ["C-1", "EDC-CC", "LDR - 1 & RM", "R-1", ""])

    def test_missing_values_always_come_last(self):
        for descending in (True, False):
            self.assertEqual(apns(L.sort_parcels(ROWS, "land_value", descending))[-1], "100000003")
            self.assertEqual(apns(L.sort_parcels(ROWS, "zoning", descending))[-1], "100000004")
        self.assertEqual(apns(L.sort_parcels(ROWS, "land_value", True))[0], "372100001")

    def test_vacant_first_then_ties_by_parcel_number(self):
        self.assertEqual(apns(L.sort_parcels(ROWS, "vacant", True)), ["100000001", "100000003", "372100001", "100000002", "100000004"])

    def test_unknown_sort_falls_back_to_acres_and_the_input_is_untouched(self):
        before = apns(ROWS)
        self.assertEqual(apns(L.sort_parcels(ROWS, "nonsense")), apns(L.sort_parcels(ROWS, "acres")))
        self.assertEqual(apns(ROWS), before)


class Counted(unittest.TestCase):
    """One rule for the size a parcel counts as, in the list and on the city card."""
    RECORDS = [dict(row("100000001", 505.0, "LDR-2", True), outline_acres=5.1), dict(row("100000002", 149.84, "RR2", True)),
               dict(row("100000003", 30.35, "RM", True), outline_acres=70.0), dict(row("100000004", 20.0, "RM", True))]

    def test_a_record_that_contradicts_its_outline_counts_at_the_outlines_size(self):
        self.assertEqual([L.counted_acres(r) for r in self.RECORDS], [5.1, 149.84, 70.0, 20.0])

    def test_the_card_and_the_list_agree_on_the_largest(self):
        card = L.summary(self.RECORDS)
        listed = L.sort_parcels(self.RECORDS)
        self.assertEqual(card["largest_acres"], 149.84)
        self.assertEqual(L.counted_acres(listed[0]), card["largest_acres"], "the list starts with the card's largest")
        self.assertEqual(card["total_acres"], round(5.1 + 149.84 + 70.0 + 20.0, 1))
        self.assertEqual(card["corrected_records"], 2)

    def test_size_filters_use_the_same_size(self):
        self.assertEqual(apns(L.filter_parcels(self.RECORDS, min_acres=100)), ["100000002"])
        self.assertEqual(apns(L.filter_parcels(self.RECORDS, max_acres=10)), ["100000001"])


class Words(unittest.TestCase):
    NAMES = {"LDR-1": "Low Density Residential-1", "RM": "Rural Mountainous"}

    def test_zone_parts(self):
        self.assertEqual(L.zone_parts("LDR - 1 & RM"), ["LDR-1", "RM"])
        self.assertEqual(L.zone_parts(" "), [])
        self.assertEqual(L.zone_parts(None), [])

    def test_zone_name(self):
        self.assertEqual(L.zone_name("LDR - 1 & RM", self.NAMES), "Low Density Residential-1 + Rural Mountainous")
        self.assertEqual(L.zone_name("XYZ", self.NAMES), "XYZ", "an unknown code is shown as it is, not explained away")
        self.assertEqual(L.zone_name("", self.NAMES), "No zoning listed")

    def test_zoning_options_count_what_occurs(self):
        kinds = [{"id": k, "label": k.title()} for k in ("homes", "shops", "mixed", "edc", "other", "unused")]
        o = L.zoning_options(ROWS, self.NAMES, kinds)
        self.assertEqual([k["id"] for k in o["kinds"]], ["homes", "shops", "mixed", "edc", "other"], "empty families are left out")
        zones = {z["code"]: z for z in o["zones"]}
        self.assertEqual(set(zones), {"R-1", "C-1", "LDR-1", "RM", "EDC-CC"})
        self.assertEqual(zones["RM"], {"code": "RM", "name": "Rural Mountainous", "count": 1})

    def test_summary(self):
        self.assertEqual(L.summary(ROWS), {"large_parcels": 5, "look_vacant": 3, "largest_acres": 142.1, "total_acres": 354.6,
                                              "corrected_records": 0})
        self.assertEqual(L.summary([]), {"large_parcels": 0, "look_vacant": 0, "largest_acres": None, "total_acres": None,
                                          "corrected_records": 0})


if __name__ == "__main__":
    unittest.main()
