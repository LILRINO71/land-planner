"""Offline checks for the report's data builder: python -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build_report  # noqa: E402
import menifee  # noqa: E402

SQUARE = [[[-117.17, 33.65], [-117.16, 33.65], [-117.16, 33.66], [-117.17, 33.66], [-117.17, 33.65]]]


class BuildReport(unittest.TestCase):
    def test_grid_covers_the_outline_south_to_north(self):
        grid, points = build_report.grid_points(SQUARE)
        self.assertEqual(len(points), grid["nx"] * grid["ny"])
        self.assertLess(points[0][0], -117.17)
        self.assertGreater(points[-1][1], 33.66)

    def test_a_silent_source_is_reported_not_invented(self):
        site = {"parcel": {"centre": {"lat": 33.655, "lon": -117.165}, "outline": {"coordinates": SQUARE}},
                "sources": {}}
        down = mock.Mock(side_effect=menifee.SourceError("down"))
        with mock.patch.object(menifee, "site", return_value=site), mock.patch.object(build_report, "surface", down), \
                mock.patch.object(build_report, "neighbour_shapes", return_value=[]), \
                mock.patch.object(build_report, "zone_names", return_value={}):
            data = build_report.build("372100001")
        self.assertIsNone(data["surface"])
        self.assertIn("did not answer", data["sources"]["surface"])
        self.assertTrue(data["example"])

    def test_data_file_is_a_script_the_page_can_load_from_disk(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "data.js"
            build_report.write({"a": 1}, out)
            text = out.read_text(encoding="utf-8")
        self.assertEqual(json.loads(text.split("window.SITE = ")[1].rstrip(";\n")), {"a": 1})


if __name__ == "__main__":
    unittest.main()
