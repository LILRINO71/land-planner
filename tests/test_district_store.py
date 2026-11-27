"""District projects: the store (datasets, versions, rollback, the revision log, notes, documents, GIS layers,
backups, the project zip), the invented sample, and the contract document kept equal to the schema. Offline, in a
temporary data folder."""
import io
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from landplanner.district import Problem, chain, gis, sample, schema  # noqa: E402
from landplanner.district.store import Store  # noqa: E402
from landplanner.district.validate import clean_record  # noqa: E402

ADMIN = {"id": "u-admin", "name": "Admin"}
DAY = 24 * 3600


class Clock:
    def __init__(self, now=1_790_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def a(id_, value, **more):
    return {"id": id_, "label": id_, "value": value, "unit": "sf", "status": "Baseline",
            "provenance": "OWNERSHIP ASSUMPTION", **more}


class Base(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.clock = Clock()
        self.store = Store(self.folder.name, self.clock)
        self.store.create_project({"id": "test-district", "name": "Test District"}, ADMIN)
        self.pid = "test-district"


class Versions(Base):
    def test_publish_makes_versions_that_never_change_and_rollback_republishes_an_old_one(self):
        self.store.put_record(self.pid, "baseline", "assumptions", a("A-1", 100), ADMIN, "first")
        self.assertEqual(self.store.publish(self.pid, "baseline", ADMIN, "one"), 1)
        v1_file = self.store.version_path(self.pid, "baseline", 1).read_bytes()
        self.store.put_record(self.pid, "baseline", "assumptions", a("A-1", 200), ADMIN, "raised")
        self.assertEqual(self.store.publish(self.pid, "baseline", ADMIN, "two"), 2)
        self.assertEqual(self.store.content(self.pid, "baseline", "published")["entities"]["assumptions"][0]["value"], 200)
        with self.assertRaises(Problem):
            self.store.rollback(self.pid, "baseline", 1, ADMIN, "")          # a reason is required
        n = self.store.rollback(self.pid, "baseline", 1, ADMIN, "the raise was a typo")
        self.assertEqual(n, 3)
        self.assertEqual(self.store.content(self.pid, "baseline", "published")["entities"]["assumptions"][0]["value"], 100)
        meta = self.store.dataset(self.pid, "baseline")
        self.assertEqual([p["version"] for p in meta["published"]], [1, 2, 3])
        self.assertEqual(meta["published"][-1]["from_version"], 1)
        self.assertEqual(self.store.version_path(self.pid, "baseline", 1).read_bytes(), v1_file)
        # the draft keeps the newer work unless asked
        self.assertEqual(self.store.content(self.pid, "baseline", "draft")["entities"]["assumptions"][0]["value"], 200)
        self.store.rollback(self.pid, "baseline", 1, ADMIN, "again", reset_draft=True)
        self.assertEqual(self.store.content(self.pid, "baseline", "draft")["entities"]["assumptions"][0]["value"], 100)

    def test_an_unpublished_dataset_has_no_published_content(self):
        with self.assertRaises(Problem) as caught:
            self.store.content(self.pid, "baseline", "published")
        self.assertEqual(caught.exception.status, 404)
        with self.assertRaises(Problem):
            self.store.content(self.pid, "baseline", 7)

    def test_every_change_is_in_the_revision_log_with_old_and_new_value_and_the_chain_holds(self):
        self.store.put_record(self.pid, "baseline", "assumptions", a("A-1", 100), ADMIN, "first")
        self.clock.now += 60
        self.store.put_record(self.pid, "baseline", "assumptions", a("A-1", 120, provenance="CONSULTANT INPUT"),
                              {"id": "u-2", "name": "Analyst"}, "consultant memo")
        self.store.remove_record(self.pid, "baseline", "assumptions", "A-1", ADMIN, "not needed")
        log = self.store.revisions(self.pid, dataset="baseline", entity="assumptions")
        value = next(r for r in log["revisions"] if r["field"] == "value")
        self.assertEqual((value["oldValue"], value["newValue"], value["user"], value["name"], value["reason"],
                          value["classification"]), (100, 120, "u-2", "Analyst", "consultant memo", "CONSULTANT INPUT"))
        self.assertEqual(log["revisions"][0]["field"], "*")          # newest first: the removal
        self.assertIsNone(log["revisions"][0]["newValue"])
        self.assertTrue(log["chain"]["ok"])

    def test_an_unchanged_record_writes_nothing(self):
        self.store.put_record(self.pid, "baseline", "assumptions", a("A-1", 100), ADMIN)
        before = self.store.revisions(self.pid)["total"]
        _, changes = self.store.put_record(self.pid, "baseline", "assumptions", a("A-1", 100), ADMIN)
        self.assertEqual((changes, self.store.revisions(self.pid)["total"]), ([], before))

    def test_scenarios_and_submissions_copy_from_a_version_and_get_their_own_ids(self):
        self.store.put_record(self.pid, "baseline", "assumptions", a("A-1", 100), ADMIN)
        self.store.publish(self.pid, "baseline", ADMIN)
        one = self.store.create_dataset(self.pid, "consultant", "Firm A", ADMIN, {"dataset": "baseline"})
        two = self.store.create_dataset(self.pid, "consultant", "Firm A", ADMIN)
        self.assertNotEqual(one["id"], two["id"])
        self.assertEqual(len(self.store.content(self.pid, one["id"], "draft")["entities"]["assumptions"]), 1)
        self.assertEqual(len(self.store.content(self.pid, two["id"], "draft")["entities"]["assumptions"]), 0)
        with self.assertRaises(Problem):
            self.store.create_dataset(self.pid, "baseline", "x", ADMIN)

    def test_import_replace_swaps_only_the_entities_given(self):
        self.store.put_records(self.pid, "baseline", {"assumptions": [a("A-1", 1), a("A-2", 2)],
                                                      "risks": [{"id": "r", "title": "R"}]}, ADMIN)
        self.store.put_records(self.pid, "baseline", {"assumptions": [a("A-3", 3)]}, ADMIN, mode="replace")
        ents = self.store.content(self.pid, "baseline", "draft")["entities"]
        self.assertEqual([x["id"] for x in ents["assumptions"]], ["A-3"])
        self.assertEqual(len(ents["risks"]), 1)


class NotesDocumentsLayers(Base):
    def test_notes_on_figures_are_resolved_and_reopened(self):
        note = self.store.add_note(self.pid, {"entity": "assumptions", "id": "A-1", "field": "value"}, "Why 100?", ADMIN)
        self.store.reply_note(self.pid, note["id"], "From the memo.", {"id": "u-2", "name": "Analyst"})
        done = self.store.resolve_note(self.pid, note["id"], "resolved", "Memo attached.", ADMIN)
        self.assertEqual((done["status"], done["resolution"], len(done["replies"])), ("resolved", "Memo attached.", 1))
        self.assertEqual(self.store.notes(self.pid, status="open"), [])
        self.assertEqual(self.store.resolve_note(self.pid, note["id"], "open", "", ADMIN)["resolved_by"], None)
        with self.assertRaises(Problem):
            self.store.add_note(self.pid, {"entity": "nonsense", "id": "x"}, "x", ADMIN)

    def test_documents_keep_every_version(self):
        doc = self.store.add_document(self.pid, "study.pdf", b"%PDF-1.4 one", ADMIN, title="Market study", task="Task 1")
        self.store.add_document(self.pid, "study v2.pdf", b"%PDF-1.4 two", ADMIN, doc_id=doc["id"], note="revised")
        d, v, data = self.store.document_file(self.pid, doc["id"], 1)
        self.assertEqual((data, len(d["versions"])), (b"%PDF-1.4 one", 2))
        self.assertEqual(self.store.document_file(self.pid, doc["id"], "latest")[2], b"%PDF-1.4 two")
        for name, data in (("x.pdf", b"not a pdf"), ("x.exe", b"MZ"), ("x.xlsx", b"plain text")):
            with self.assertRaises(Problem):
                self.store.add_document(self.pid, name, data, ADMIN)

    def test_a_geojson_layer_is_kept_and_a_projected_one_is_warned_about(self):
        info, fc = gis.read_layer("ta.geojson", json.dumps(sample.GIS).encode())
        self.assertEqual((info["features"], info["warnings"]), (2, []))
        layer = self.store.add_layer(self.pid, fc, {"label": "Trade area", **info}, ADMIN)
        self.assertEqual(self.store.layer(self.pid, layer["id"])[1]["features"][0]["properties"]["name"],
                         "Primary trade area")
        far = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                                                          "geometry": {"type": "Point", "coordinates": [6500000, 2100000]}}]}
        self.assertTrue(gis.read_layer("x.geojson", json.dumps(far).encode())[0]["warnings"])
        with self.assertRaises(Problem):
            gis.read_layer("x.geojson", b'{"type": "Feature", "geometry": {"type": "Point", "coordinates": [NaN, 1]}}')
        self.store.remove_layer(self.pid, layer["id"], ADMIN)
        self.assertEqual(self.store.layers(self.pid), [])

    def test_a_zipped_shapefile_becomes_geojson(self):
        info, fc = gis.read_layer("parcels.zip", shapefile_zip(prj='PROJCS["NAD83 / California zone 6"]'))
        self.assertEqual(info["features"], 2)
        square = fc["features"][0]
        self.assertEqual(square["geometry"]["type"], "Polygon")
        self.assertEqual(square["properties"], {"NAME": "Lot A", "ACRES": 12.5, "PHASE": 1})
        ring = square["geometry"]["coordinates"][0]
        self.assertGreater(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:])), 0)   # outer CCW
        self.assertEqual(fc["features"][1]["geometry"], {"type": "Point", "coordinates": [-117.0, 34.0]})
        self.assertTrue(any("not reprojected" in w for w in info["warnings"]))
        with self.assertRaises(Problem):
            gis.read_layer("x.zip", zip_of({"a.dbf": b"x"}))


class Backups(Base):
    def test_the_first_use_each_day_makes_one_backup_and_only_fourteen_are_kept(self):
        self.assertIsNotNone(self.store.daily_backup(self.pid))
        self.assertIsNone(self.store.daily_backup(self.pid))
        for _ in range(20):
            self.clock.now += DAY
            self.store.daily_backup(self.pid)
        self.assertEqual(len(self.store.backups(self.pid)), 14)

    def test_restore_brings_back_the_backup_and_keeps_a_copy_of_what_it_replaced(self):
        self.store.put_record(self.pid, "baseline", "assumptions", a("A-1", 100), ADMIN)
        made = self.store.backup_now(self.pid)
        self.store.put_record(self.pid, "baseline", "assumptions", a("A-1", 999), ADMIN)
        self.clock.now += 5
        safety = self.store.restore(self.pid, made["name"])
        self.assertEqual(self.store.content(self.pid, "baseline", "draft")["entities"]["assumptions"][0]["value"], 100)
        self.assertIn(safety["name"], [b["name"] for b in self.store.backups(self.pid)])
        self.store.restore(self.pid, safety["name"])
        self.assertEqual(self.store.content(self.pid, "baseline", "draft")["entities"]["assumptions"][0]["value"], 999)
        with self.assertRaises(Problem):
            self.store.restore(self.pid, "../../etc.zip")


class ProjectZip(Base):
    def test_a_project_moves_to_another_computer_as_one_zip(self):
        self.store.put_record(self.pid, "baseline", "assumptions", a("A-1", 100), ADMIN)
        self.store.publish(self.pid, "baseline", ADMIN)
        self.store.add_document(self.pid, "s.pdf", b"%PDF-1.4 x", ADMIN)
        data = self.store.export_package(self.pid, ADMIN)
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        there = Store(other.name, self.clock)
        project, replaced, _ = there.import_package(data, ADMIN)
        self.assertEqual((project["id"], replaced), (self.pid, False))
        self.assertEqual(there.content(self.pid, "baseline")["entities"], self.store.content(self.pid, "baseline")["entities"])
        self.assertEqual(there.document_file(self.pid, "s", 1)[2], b"%PDF-1.4 x")
        with self.assertRaises(Problem) as caught:
            there.import_package(data, ADMIN)
        self.assertEqual(caught.exception.status, 409)
        _, replaced, safety = there.import_package(data, ADMIN, replace=True)
        self.assertTrue(replaced and safety)

    def test_a_changed_or_unsafe_zip_is_refused(self):
        data = self.store.export_package(self.pid, ADMIN)
        files = {i.filename: zipfile.ZipFile(io.BytesIO(data)).read(i) for i in zipfile.ZipFile(io.BytesIO(data)).infolist()}
        files["project/project.json"] = files["project/project.json"].replace(b"Test District", b"Changed")
        other = Store(tempfile.mkdtemp(dir=self.folder.name), self.clock)
        for bad in (zip_of(files), zip_of({"manifest.json": b"{}"}), zip_of({"../evil.txt": b"x"}), b"not a zip"):
            with self.assertRaises(Problem):
                other.import_package(bad, ADMIN)


class SampleAndContract(unittest.TestCase):
    def test_the_sample_fills_every_entity_and_every_record_passes_the_checks(self):
        ents = sample.content()["entities"]
        self.assertEqual(set(ents), set(schema.ENTITIES))
        for name, rows in ents.items():
            self.assertTrue(rows, f"the sample has no {name}")
            for r in rows:
                clean, errors = clean_record(name, r)
                self.assertEqual(errors, [], f"{name} {r.get('id')}")
        self.assertTrue(sample.PROJECT["name"].startswith("Sample"))

    def test_the_sample_installs_with_a_published_baseline_and_a_consultant_submission(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        store = Store(folder.name)
        project = sample.install(store, ADMIN)
        self.assertTrue(project["sample"])
        kinds = sorted(m["kind"] for m in store.datasets(sample.PROJECT_ID))
        self.assertEqual(kinds, ["baseline", "consultant"])
        self.assertEqual(store.dataset(sample.PROJECT_ID, "baseline")["current"], 1)
        self.assertTrue(store.modules(sample.PROJECT_ID) and store.layers(sample.PROJECT_ID))

    def test_the_contract_document_has_the_schema_tables(self):
        text = (ROOT / "docs" / "district-data-contract.md").read_text(encoding="utf-8")
        self.assertEqual(text, schema.fill_contract(text), "run schema.fill_contract on docs/district-data-contract.md")
        for route in ("/api/districts/session", "/export/module.pdf", "/imports/<i>/commit"):
            self.assertIn(route, text)

    def test_the_requirement_status_starts_open(self):
        rec, errors = clean_record("requirements", {"id": "X-1", "source_document": "Doc", "text": "Do it."})
        self.assertEqual((errors, rec["status"]), ([], "open"))

    def test_the_hash_chain_shows_a_changed_or_missing_line(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "log.jsonl"
        for i in range(4):
            chain.append(path, {"n": i, "big": "x" * (70000 if i == 1 else 1)})
        self.assertEqual(chain.verify(path)["lines"], 4)
        self.assertTrue(chain.verify(path)["ok"])
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join([lines[0], lines[1].replace('"n": 1', '"n": 7'), lines[2], lines[3]]) + "\n", encoding="utf-8")
        self.assertEqual(chain.verify(path)["broken_at"], 2)
        path.write_text("\n".join([lines[0], lines[2], lines[3]]) + "\n", encoding="utf-8")
        self.assertEqual(chain.verify(path)["broken_at"], 2)


# ---------------------------------------------------------------- helpers

def zip_of(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def shapefile_zip(prj=""):
    """A two-shape shapefile: a clockwise square (a polygon) and a point, with a .dbf of name, acres, phase."""
    square = [(-117.1, 33.9), (-117.1, 34.0), (-117.0, 34.0), (-117.0, 33.9), (-117.1, 33.9)]   # clockwise
    poly = struct.pack("<i4d2i", 5, -117.1, 33.9, -117.0, 34.0, 1, len(square)) + struct.pack("<i", 0) + \
        b"".join(struct.pack("<2d", x, y) for x, y in square)
    point = struct.pack("<i2d", 1, -117.0, 34.0)
    body = b""
    for i, rec in enumerate((poly, point), start=1):
        body += struct.pack(">2i", i, len(rec) // 2) + rec
    shp = struct.pack(">7i", 9994, 0, 0, 0, 0, 0, (100 + len(body)) // 2) + struct.pack("<2i4d4d", 1000, 5, -117.1, 33.9,
                                                                                         -117.0, 34.0, 0, 0, 0, 0) + body
    fields = [(b"NAME", b"C", 10, 0), (b"ACRES", b"N", 8, 2), (b"PHASE", b"N", 3, 0)]
    rec_len = 1 + sum(f[2] for f in fields)
    head = struct.pack("<4BIHH20x", 3, 126, 1, 1, 2, 32 + 32 * len(fields) + 1, rec_len)
    desc = b"".join(n.ljust(11, b"\x00") + t + b"\x00" * 4 + bytes([size, dec]) + b"\x00" * 14 for n, t, size, dec in fields)
    rows = b" " + b"Lot A".ljust(10) + b"12.50".rjust(8) + b"1".rjust(3) + \
           b" " + b"Spot".ljust(10) + b"".rjust(8) + b"2".rjust(3)
    dbf = head + desc + b"\x0d" + rows + b"\x1a"
    files = {"parcels/parcels.shp": shp, "parcels/parcels.dbf": dbf}
    if prj:
        files["parcels/parcels.prj"] = prj.encode()
    return zip_of(files)


if __name__ == "__main__":
    unittest.main()
