"""District projects: the security review's findings, each as an attack that must fail. Offline, in a temporary data
folder, on the invented Sample District only (the repo is public: no real project's figures here).

Part 1 (fixed): a project zip cannot write outside its folder (F01), a document version cannot name a file outside the
library (F08), the city cannot work out hidden figures from compute answers (F03), a what-if gives the same answer for
a hidden record and a missing one (F16), and the hash-chained logs show lines cut off their end or written again (F15).
The tests marked "part 2" are the findings still open in api.py, access.py and server.py: they are expected to fail
until those are fixed, and then the marker comes off.
"""
import copy
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from landplanner.district import Problem, access, chain, compute  # noqa: E402
from landplanner.district import sample as S  # noqa: E402
from landplanner.district.api import DistrictAPI  # noqa: E402
from landplanner.district.schema import AUDIENCE_DENY, field_tags  # noqa: E402
from landplanner.district.store import Store, safe_relative  # noqa: E402

access.ITERATIONS = 1000
P = "/api/districts/projects/sample-district"
ROLES = ("administrator", "analyst", "consultant", "viewer_partner", "viewer_city")
CITY_DENY = AUDIENCE_DENY["city"]


class Clock:
    def __init__(self, now=1_790_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class Base(unittest.TestCase):
    """A workspace with the sample installed and one signed-in user of each role (all assigned to the sample)."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.data = Path(self.folder.name)
        self.api = DistrictAPI(self.folder.name, Clock())
        self.tokens = {"administrator": self.sign_in("Admin", "admin-pass-1")}
        for role in ROLES[1:]:
            self.add_user(role.title(), role, ["sample-district"])
            self.tokens[role] = self.sign_in(role.title(), f"pass-{role}-1")

    def call(self, method, path, token=None, query=None, body=None, raw=None, kind=None, headers=None):
        h = dict(headers or {})
        if token:
            h["Cookie"] = f"lp_district={token}"
        data = b""
        if raw is not None:
            h["Content-Type"], data = kind or "application/octet-stream", raw
        elif body is not None:
            h["Content-Type"], data = "application/json", json.dumps(body).encode()
        r = self.api.handle(method, path, {k: [str(v)] for k, v in (query or {}).items()}, h, data)
        if r.kind.startswith("application/json"):
            return r.status, json.loads(r.body.decode("utf-8")), r.headers
        return r.status, r.body, r.headers

    def sign_in(self, name, passcode):
        s, b, h = self.call("POST", "/api/districts/session", body={"method": "passcode", "name": name,
                                                                    "passcode": passcode})
        self.assertEqual(s, 200, b)
        token = h["Set-Cookie"].split(";")[0].split("=", 1)[1]
        self.assertEqual(self.call("POST", "/api/districts/session/nda", token, body={"accept": True})[0], 200)
        return token

    def add_user(self, name, role, projects=()):
        s, b, _ = self.call("POST", "/api/districts/users", self.tokens["administrator"],
                            body={"name": name, "role": role, "projects": list(projects), "passcode": f"pass-{role}-1"})
        self.assertEqual(s, 200, b)
        return b["user"]


def package(files, project_id="crafted"):
    """A project zip as export_package makes it, with the manifest's hashes right (they are not a signature)."""
    files = {"project.json": json.dumps({"id": project_id, "name": "Crafted package", "settings": {}}).encode(),
             **files}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for rel, blob in files.items():
            z.writestr("project/" + rel, blob)
        z.writestr("manifest.json", json.dumps({"format": "landplanner-district-project", "project_id": project_id,
                                                "files": {r: hashlib.sha256(b).hexdigest() for r, b in files.items()}}))
    return buf.getvalue()


# ---------------------------------------------------------------- F01: zip-slip

class ZipSlip(Base):
    def test_a_drive_letter_after_the_project_prefix_writes_nothing_outside(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)
        target = (outside / "planted.txt").resolve().as_posix()
        s, b, _ = self.call("POST", "/api/districts/projects/import", self.tokens["administrator"],
                            raw=package({target: b"planted"}))
        self.assertEqual(s, 400, b)
        self.assertFalse((outside / "planted.txt").exists())
        self.assertFalse(Store(self.data).exists("crafted"))

    def test_unsafe_member_names_are_refused(self):
        for name in ("../x", "a/../../x", "/etc/x", "C:/x", "c:x", "a/C:/x", "a\\..\\x", "datasets/x/meta.json:stream",
                     "CON", "documents/nul.txt", "a/com1", "trailing.", "trailing ", "a//b", "./a", "a/\x01b", ""):
            self.assertFalse(safe_relative(name), name)
        for name in ("project.json", "datasets/baseline/v0001.json", "documents/brief/v1.pdf", "gis/trade-area.geojson",
                     "notes.json", "con-tract/x.json", "console.json"):
            self.assertTrue(safe_relative(name), name)

    def test_an_ordinary_package_still_round_trips(self):
        a = self.tokens["administrator"]
        s, data, _ = self.call("GET", P + "/package.zip", a)
        self.assertEqual(s, 200)
        s, b, _ = self.call("POST", "/api/districts/projects/import", a, raw=data, query={"replace": "1"})
        self.assertEqual((s, b["replaced"]), (200, True), b)


# ---------------------------------------------------------------- F08: document files stay in the library

class DocumentPaths(Base):
    def test_a_library_entry_naming_a_file_elsewhere_is_not_read(self):
        secret = self.data / "outside-the-project.txt"
        secret.write_text("not a document", encoding="utf-8")
        lib = {"documents": [
            {"id": "abs", "title": "a", "kind": "pdf", "audiences": ["internal", "city"], "created_by": "x",
             "versions": [{"version": 1, "filename": "a.pdf", "file": secret.resolve().as_posix()}]},
            {"id": "up", "title": "b", "kind": "pdf", "audiences": ["internal", "city"], "created_by": "x",
             "versions": [{"version": 1, "filename": "b.pdf", "file": "../../../outside-the-project.txt"}]},
            {"id": "../..", "title": "c", "kind": "pdf", "audiences": ["internal", "city"], "created_by": "x",
             "versions": [{"version": 1, "filename": "c.pdf", "file": "v1.pdf"}]}]}
        a = self.tokens["administrator"]
        s, b, _ = self.call("POST", "/api/districts/projects/import", a,
                            raw=package({"documents/library.json": json.dumps(lib).encode()}))
        self.assertEqual(s, 200, b)
        for doc in ("abs", "up"):
            s, body, _ = self.call("GET", f"/api/districts/projects/crafted/documents/{doc}/latest", a)
            self.assertEqual(s, 404, doc)
            self.assertNotIn(b"not a document", body if isinstance(body, bytes) else json.dumps(body).encode())
        store = Store(self.data)
        with self.assertRaises(Problem):
            store.document_file("crafted", "../..", "latest")

    def test_an_uploaded_document_still_downloads(self):
        a = self.tokens["administrator"]
        s, b, _ = self.call("POST", P + "/documents", a, raw=b"%PDF-1.4\n%%EOF\n", query={"name": "brief.pdf"})
        self.assertEqual(s, 200, b)
        s, body, _ = self.call("GET", P + f"/documents/{b['document']['id']}/latest", a)
        self.assertEqual((s, body), (200, b"%PDF-1.4\n%%EOF\n"))


# ---------------------------------------------------------------- F03: no city-derivable hidden figures

def _perturb(content):
    """The same content with every figure the city may not see changed (fields tagged, and denied assumptions)."""
    out = copy.deepcopy(content)
    for name, rows in out["entities"].items():
        for r in rows:
            for k, v in list(r.items()):
                if field_tags(name, k) & CITY_DENY and isinstance(v, (int, float)) and not isinstance(v, bool):
                    r[k] = v * 1.37 + 1
    for a in out["entities"]["assumptions"]:
        v = a.get("value")
        if access._record_denied(a, CITY_DENY) and isinstance(v, (int, float)) and not isinstance(v, bool):
            a["value"] = v * 1.37 + 1
    return out


def _city_answer(tool, content, options):
    """What api._compute sends the city: the tool on the full content, then filter_answer, then scrub."""
    answer = compute.run(tool, content, options, reconcile_content=access.filter_content(content, "city"))
    return access.scrub(compute.filter_answer(answer, "city"), "city")


def _differences(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in sorted(set(a) | set(b), key=str) for d in _differences(a.get(k), b.get(k), f"{path}/{k}")]
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in _differences(x, y, f"{path}[{i}]")]
    return [] if a == b else [path]


def _keys(x):
    if isinstance(x, dict):
        return set(x) | {k for v in x.values() for k in _keys(v)}
    if isinstance(x, list):
        return {k for v in x for k in _keys(v)}
    return set()


class ComputeForTheCity(Base):
    def content(self):
        return Store(self.data).content("sample-district", "baseline", "published")

    def test_no_city_answer_changes_when_only_hidden_figures_change(self):
        """The rule behind F03: if the city's answer moves with a hidden figure, the figure can be worked out."""
        base = self.content()
        moved = _perturb(base)
        runs = [(tool, {}) for tool in compute.TOOLS]
        runs += [(tool, {k: v}) for tool, opts in compute.OPTIONS.items() for k, vals in opts.items() for v in vals]
        for tool, options in runs:
            with self.subTest(tool=tool, options=options):
                self.assertEqual(_differences(_city_answer(tool, base, options), _city_answer(tool, moved, options)), [])

    def test_residual_by_use_cannot_be_worked_out_by_the_city(self):
        s, ans, _ = self.call("GET", P + "/compute/landvalue", self.tokens["viewer_city"])
        self.assertEqual(s, 200, ans)
        keys = _keys(ans["result"])
        for k in ("required_profit_usd", "required_return_pct", "rlv_usd", "ranking", "ranked_by", "feasible_now"):
            self.assertNotIn(k, keys)
        # the internal view keeps them
        s, internal, _ = self.call("GET", P + "/compute/landvalue", self.tokens["administrator"])
        self.assertTrue({"required_profit_usd", "rlv_usd", "ranking"} <= _keys(internal["result"]))

    def test_a_hidden_discount_rate_is_not_echoed_to_the_city(self):
        hidden = {a["id"]: a["value"] for a in self.content()["entities"]["assumptions"]
                  if access._record_denied(a, CITY_DENY)}
        self.assertIn("PF-DISCOUNT-RATE-PCT", hidden)        # the sample tags it "returns"
        s, ans, _ = self.call("GET", P + "/compute/proforma", self.tokens["viewer_city"])
        self.assertEqual(s, 200, ans)
        for phase in ans["result"].get("phases") or []:
            self.assertNotIn("discount_rate_pct", phase.get("assumptions") or {})
        self.assertNotIn("PF-DISCOUNT-RATE-PCT", [i.get("assumption_id") for i in ans["inputs_used"]])
        s, internal, _ = self.call("GET", P + "/compute/proforma", self.tokens["administrator"])
        self.assertIn("discount_rate_pct", internal["result"]["phases"][0]["assumptions"])

    def test_an_input_named_like_a_hidden_subject_is_not_listed_for_the_city(self):
        answer = {"tool": "fiscal", "result": {}, "missing": [],
                  "inputs_used": [{"assumption_id": "X-IRR-TARGET", "label": "target IRR", "value": 21, "tags": []},
                                  {"assumption_id": "X-TAX", "label": "sales tax rate", "value": 1, "tags": []}]}
        self.assertEqual([i["assumption_id"] for i in compute.filter_answer(answer, "city")["inputs_used"]], ["X-TAX"])

    def test_a_what_if_answers_alike_for_a_hidden_record_and_a_missing_one(self):
        """F16: the error must not tell the city which hidden records exist."""
        targets = self.content()["entities"]["capital_targets"]
        self.assertTrue(targets)
        city = self.tokens["viewer_city"]
        hidden = self.call("POST", P + "/compute/proceeds", city,
                           body={"records": {"capital_targets": [{"id": targets[0]["id"]}]}})
        missing = self.call("POST", P + "/compute/proceeds", city,
                            body={"records": {"capital_targets": [{"id": "no-such-target"}]}})
        self.assertEqual((hidden[0], hidden[1]["error"]["message"].replace(targets[0]["id"], "?")),
                         (missing[0], missing[1]["error"]["message"].replace("no-such-target", "?")))


# ---------------------------------------------------------------- F15: the hash chain and its head

class ChainHead(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "log.jsonl"
        for i in range(6):
            chain.append(self.path, {"n": i})

    def lines(self):
        return self.path.read_text(encoding="utf-8").splitlines(True)

    def test_an_untouched_log_verifies(self):
        self.assertEqual((chain.verify(self.path)["ok"], chain.verify(self.path)["lines"]), (True, 6))

    def test_lines_cut_off_the_end_show(self):
        self.path.write_text("".join(self.lines()[:3]), encoding="utf-8")
        v = chain.verify(self.path)
        self.assertFalse(v["ok"])
        self.assertIn("cut off", v["reason"])

    def test_a_deleted_log_shows(self):
        self.path.unlink()
        self.assertFalse(chain.verify(self.path)["ok"])

    def test_a_log_written_again_from_the_start_shows(self):
        self.path.unlink()
        for i in range(6):
            chain.append(self.path.with_name("other.jsonl"), {"n": i, "forged": True})
        os.replace(self.path.with_name("other.jsonl"), self.path)
        self.assertFalse(chain.verify(self.path)["ok"])

    def test_cutting_the_end_still_shows_after_more_lines_are_added(self):
        self.path.write_text("".join(self.lines()[:3]), encoding="utf-8")
        chain.append(self.path, {"n": "after"})
        chain.append(self.path, {"n": "after again"})
        self.assertFalse(chain.verify(self.path)["ok"])

    def test_a_head_one_line_behind_is_not_damage(self):
        """A crash between writing the line and writing the head leaves the head one line behind."""
        head = chain.head_path(self.path)
        before = head.read_text(encoding="utf-8")
        chain.append(self.path, {"n": 6})
        head.write_text(before, encoding="utf-8")
        self.assertTrue(chain.verify(self.path)["ok"])
        chain.append(self.path, {"n": 7})
        v = chain.verify(self.path)
        self.assertEqual((v["ok"], v["lines"]), (True, 8))

    def test_a_log_kept_before_heads_existed_still_verifies_and_gets_one(self):
        chain.head_path(self.path).unlink()
        self.assertTrue(chain.verify(self.path)["ok"])
        chain.append(self.path, {"n": 6})
        self.assertEqual(json.loads(chain.head_path(self.path).read_text(encoding="utf-8"))["lines"], 7)
        self.assertTrue(chain.verify(self.path)["ok"])

    def test_the_audit_log_keeps_a_head(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        api = DistrictAPI(folder.name, Clock())
        api.handle("POST", "/api/districts/session", {}, {"Content-Type": "application/json"},
                   json.dumps({"method": "passcode", "name": "Admin", "passcode": "admin-pass-1"}).encode())
        log = Path(folder.name) / "district-audit.jsonl"
        self.assertTrue(chain.head_path(log).is_file())
        log.write_text("".join(log.read_text(encoding="utf-8").splitlines(True)[:1]), encoding="utf-8")
        self.assertFalse(chain.verify(log)["ok"])


# ---------------------------------------------------------------- part 2: still open in api.py / access.py / server.py

PART2 = "part 2: fixed in api.py / access.py / server.py after the network worker lands"


class StillOpen(Base):
    @unittest.expectedFailure
    def test_f02_an_emptied_users_file_does_not_reopen_the_first_run(self):
        (self.data / "district-users.json").write_text('{"version": 1, "users": []}', encoding="utf-8")
        s, b, _ = self.call("POST", "/api/districts/session", body={"method": "passcode", "name": "Intruder",
                                                                    "passcode": "intruder-pass"})
        self.assertNotEqual((s, (b.get("user") or {}).get("role")), (200, "administrator"))

    @unittest.expectedFailure
    def test_f02_first_run_makes_one_administrator_however_many_sign_in_at_once(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        api = DistrictAPI(folder.name, Clock())
        gate = threading.Barrier(4)

        def go(i):
            gate.wait()
            api.handle("POST", "/api/districts/session", {}, {"Content-Type": "application/json"},
                       json.dumps({"method": "passcode", "name": f"Person {i}", "passcode": "first-pass-1"}).encode())
        threads = [threading.Thread(target=go, args=(i,)) for i in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        users = json.loads((Path(folder.name) / "district-users.json").read_text(encoding="utf-8"))["users"]
        self.assertEqual(len([u for u in users if u["role"] == "administrator"]), 1)

    @unittest.expectedFailure
    def test_f04_a_parcel_note_naming_a_price_floor_is_not_sent_to_the_city(self):
        a = self.tokens["administrator"]
        _, d, _ = self.call("GET", P + "/datasets/baseline", a, query={"version": "draft"})
        parcel = d["content"]["entities"]["parcels"][0]
        self.call("POST", P + "/datasets/baseline/records", a,
                  body={"entity": "parcels", "record": {**parcel, "note": "Price floor 4,200,000 (invented)"}})
        self.call("POST", P + "/datasets/baseline/publish", a, body={"note": "Target price raised (invented)"})
        _, city, _ = self.call("GET", P + "/datasets/baseline", self.tokens["viewer_city"])
        self.assertNotIn("Price floor", json.dumps(city))
        _, metas, _ = self.call("GET", P + "/datasets", self.tokens["viewer_city"])
        self.assertNotIn("Target price", json.dumps(metas))

    @unittest.expectedFailure
    def test_f04_gis_properties_shared_with_the_city_are_filtered_by_meaning(self):
        a = self.tokens["administrator"]
        fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {
            "apn": "1", "asking_price": 5, "ResidualValue": 9, "notes": "IRR 22% (invented)"},
            "geometry": {"type": "Point", "coordinates": [-117.1, 33.6]}}]}
        s, b, _ = self.call("POST", P + "/gis", a, raw=json.dumps(fc).encode(), query={"name": "deal.geojson"})
        self.call("POST", P + f"/gis/{b['layer']['id']}/share", a, body={"audiences": ["city"]})
        _, layer, _ = self.call("GET", P + f"/gis/{b['layer']['id']}", self.tokens["viewer_city"])
        props = layer["features"][0]["properties"]
        self.assertFalse({"asking_price", "ResidualValue"} & set(props) or "IRR" in json.dumps(props))

    @unittest.expectedFailure
    def test_f05_a_consultant_does_not_read_notes_on_drafts_they_cannot_open(self):
        _, sc, _ = self.call("POST", P + "/datasets", self.tokens["analyst"], body={"kind": "scenario", "label": "S"})
        self.call("POST", P + "/notes", self.tokens["analyst"],
                  body={"target": {"dataset": sc["dataset"]["id"], "entity": "assumptions", "id": "A-RET-GLA"},
                        "text": "internal walk-away figure (invented)"})
        _, notes, _ = self.call("GET", P + "/notes", self.tokens["consultant"])
        self.assertNotIn("walk-away", json.dumps(notes))

    @unittest.expectedFailure
    def test_f06_a_consultant_cannot_replace_a_document_shared_with_the_city(self):
        a = self.tokens["administrator"]
        _, b, _ = self.call("POST", P + "/documents", a, raw=b"%PDF-1.4 official\n", query={"name": "b.pdf"})
        doc = b["document"]["id"]
        self.call("POST", P + f"/documents/{doc}/share", a, body={"audiences": ["consultant", "city"]})
        self.call("POST", P + "/documents", self.tokens["consultant"], raw=b"%PDF-1.4 replaced\n",
                  query={"name": "b.pdf", "document": doc})
        _, body, _ = self.call("GET", P + f"/documents/{doc}/latest", self.tokens["viewer_city"])
        self.assertEqual(body, b"%PDF-1.4 official\n")

    @unittest.expectedFailure
    def test_f07_one_consultant_firm_does_not_see_another_firms_uploads(self):
        self.add_user("Second Firm", "consultant", ["sample-district"])
        other = self.sign_in("Second Firm", "pass-consultant-1")
        self.call("POST", P + "/documents", self.tokens["consultant"], raw=b"%PDF-1.4\n",
                  query={"name": "fee.pdf", "title": "Firm A fee proposal"})
        _, docs, _ = self.call("GET", P + "/documents", other)
        self.assertNotIn("Firm A fee proposal", json.dumps(docs))

    @unittest.expectedFailure
    def test_f10_a_stranger_cannot_lock_out_the_right_passcode(self):
        for _ in range(6):
            self.call("POST", "/api/districts/session", body={"method": "passcode", "name": "Admin", "passcode": "no"},
                      headers={"X-Client": "stranger"})
        s, b, _ = self.call("POST", "/api/districts/session",
                            body={"method": "passcode", "name": "Admin", "passcode": "admin-pass-1"})
        self.assertEqual(s, 200, b)

    @unittest.expectedFailure
    def test_f11_a_huge_sign_in_name_is_not_written_to_the_audit_log(self):
        log = self.data / "district-audit.jsonl"
        before = log.stat().st_size
        self.call("POST", "/api/districts/session", body={"method": "passcode", "name": "N" * 200_000, "passcode": "x"})
        self.assertLess(log.stat().st_size - before, 10_000)

    @unittest.expectedFailure
    def test_f13_changing_a_passcode_ends_the_other_sessions(self):
        first = self.tokens["viewer_partner"]
        second = self.sign_in("Viewer_Partner", "pass-viewer_partner-1")
        self.call("POST", "/api/districts/session/passcode", second, body={"old": "pass-viewer_partner-1",
                                                                         "new": "new-pass-partner-2"})
        self.assertEqual(self.call("GET", "/api/districts/projects", first)[0], 401)

    @unittest.expectedFailure
    def test_f15_viewers_dataset_reads_are_in_the_audit_log(self):
        self.call("GET", P + "/datasets/baseline", self.tokens["viewer_city"])
        _, log, _ = self.call("GET", "/api/districts/audit", self.tokens["administrator"], query={"user": "Viewer_City"})
        self.assertIn("read", {e["action"] for e in log["entries"]})


if __name__ == "__main__":
    unittest.main()
