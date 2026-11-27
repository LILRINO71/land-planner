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

    def call(self, method, path, token=None, query=None, body=None, raw=None, kind=None, headers=None, client=None):
        h = dict(headers or {})
        if token:
            h["Cookie"] = f"lp_district={token}"
        data = b""
        if raw is not None:
            h["Content-Type"], data = kind or "application/octet-stream", raw
        elif body is not None:
            h["Content-Type"], data = "application/json", json.dumps(body).encode()
        r = self.api.handle(method, path, {k: [str(v)] for k, v in (query or {}).items()}, h, data, client=client)
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


# ---------------------------------------------------------------- F02: the first run

def _sign_in_raw(api, name, passcode, client=None, host=None):
    headers = {"Content-Type": "application/json", **({"Host": host} if host else {})}
    r = api.handle("POST", "/api/districts/session", {}, headers,
                   json.dumps({"method": "passcode", "name": name, "passcode": passcode}).encode(), client=client)
    return r.status, json.loads(r.body.decode("utf-8"))


class FirstRun(Base):
    def test_an_emptied_or_deleted_users_file_does_not_reopen_the_first_run(self):
        users = self.data / "district-users.json"
        for damage in ('{"version": 1, "users": []}', None, '{"users": [{"name": "no id"}]}'):
            with self.subTest(damage=damage):
                if damage is None:
                    users.unlink(missing_ok=True)
                else:
                    users.write_text(damage, encoding="utf-8")
                s, b = _sign_in_raw(self.api, "Intruder", "intruder-pass")
                self.assertEqual((s, b["error"]["code"]), (500, "unreadable"), b)
                status = json.loads(self.api.handle("GET", "/api/districts", {}, {}, b"").body)
                self.assertFalse(status["bootstrap"])
        for shape in ("null", "[]", '{"users": "nobody"}'):
            users.write_text(shape, encoding="utf-8")
            self.assertEqual(_sign_in_raw(self.api, "Intruder", "intruder-pass")[0], 500, shape)

    def test_first_run_makes_one_administrator_however_many_sign_in_at_once(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        api = DistrictAPI(folder.name, Clock())
        gate, answers = threading.Barrier(6), []

        def go(i):
            gate.wait()
            answers.append(_sign_in_raw(api, f"Person {i}", "first-pass-1")[0])
        threads = [threading.Thread(target=go, args=(i,)) for i in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        users = json.loads((Path(folder.name) / "district-users.json").read_text(encoding="utf-8"))["users"]
        self.assertEqual(len(users), 1)
        self.assertEqual(sorted(answers), [200] + [401] * 5)

    def test_the_first_run_is_only_on_this_computer(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        api = DistrictAPI(folder.name, Clock())
        far = api.handle("GET", "/api/districts", {}, {"Host": "planner.example.org"}, b"", client="203.0.113.9")
        self.assertFalse(json.loads(far.body)["bootstrap"])
        self.assertEqual(_sign_in_raw(api, "Far", "far-pass-12", client="203.0.113.9")[1]["error"]["code"],
                         "first-run-here")
        # behind a reverse proxy the caller is 127.0.0.1 but asks for the public name
        self.assertEqual(_sign_in_raw(api, "Proxied", "proxied-pass", client="127.0.0.1",
                                      host="planner.example.org")[0], 403)
        near = api.handle("GET", "/api/districts", {}, {"Host": "127.0.0.1:8777"}, b"", client="127.0.0.1")
        self.assertTrue(json.loads(near.body)["bootstrap"])
        s, b = _sign_in_raw(api, "Owner", "owner-pass-1", client="127.0.0.1", host="127.0.0.1:8777")
        self.assertEqual((s, b["user"]["role"]), (200, "administrator"))

    def test_a_directory_made_before_the_marker_is_marked(self):
        settings = self.data / "district-settings.json"
        box = json.loads(settings.read_text(encoding="utf-8"))
        box.pop("bootstrapped_at")
        settings.write_text(json.dumps(box), encoding="utf-8")
        api = DistrictAPI(self.folder.name, Clock())
        self.assertTrue(api.settings.get()["bootstrapped_at"])


# ---------------------------------------------------------------- F04 and the site facts: what the city may read

class CityText(Base):
    def test_a_note_or_publish_note_naming_a_price_floor_is_not_sent_to_the_city(self):
        a = self.tokens["administrator"]
        _, d, _ = self.call("GET", P + "/datasets/baseline", a, query={"version": "draft"})
        parcel = d["content"]["entities"]["parcels"][0]
        self.call("POST", P + "/datasets/baseline/records", a,
                  body={"entity": "parcels", "record": {**parcel, "note": "Price floor 4,200,000 (invented)"}})
        self.call("POST", P + "/datasets/baseline/publish", a, body={"note": "Target price raised (invented)"})
        _, city, _ = self.call("GET", P + "/datasets/baseline", self.tokens["viewer_city"])
        self.assertNotIn("Price floor", json.dumps(city))
        self.assertTrue(city["content"]["entities"]["parcels"])
        for who in ("viewer_city", "viewer_partner", "consultant"):
            _, metas, _ = self.call("GET", P + "/datasets", self.tokens[who])
            self.assertNotIn("Target price", json.dumps(metas), who)
        _, inside, _ = self.call("GET", P + "/datasets", a)
        self.assertIn("Target price", json.dumps(inside))

    def test_a_table_row_naming_a_denied_subject_is_left_out_for_the_city(self):
        content = Store(self.data).content("sample-district", "baseline", "published")
        content["entities"]["sections"].append({"id": "s-x", "module": "overview", "heading": "Sites",
                                                "columns": ["Site", "Comment"],
                                                "rows": [["A", "good access"], ["B", "residual land value 9 (invented)"]]})
        shown = next(x for x in access.filter_content(content, "city")["entities"]["sections"] if x["id"] == "s-x")
        self.assertEqual(shown["rows"], [["A", "good access"]])

    def test_gis_properties_go_outside_the_team_by_an_allow_list(self):
        a = self.tokens["administrator"]
        fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {
            "apn": "1", "zoning": "C-1", "gross_acres": 4, "asking_price": 5, "ResidualValue": 9, "walk_away": 3,
            "notes": "IRR 22% (invented)", "label": "Price floor parcel"},
            "geometry": {"type": "Point", "coordinates": [-117.1, 33.6]}}]}
        s, b, _ = self.call("POST", P + "/gis", a, raw=json.dumps(fc).encode(), query={"name": "deal.geojson"})
        lid = b["layer"]["id"]
        self.call("POST", P + f"/gis/{lid}/share", a, body={"audiences": ["city", "partner"]})
        _, layer, _ = self.call("GET", P + f"/gis/{lid}", self.tokens["viewer_city"])
        self.assertEqual(layer["features"][0]["properties"], {"apn": "1", "zoning": "C-1", "gross_acres": 4})
        self.assertEqual(layer["features"][0]["geometry"]["type"], "Point")
        self.call("POST", P + f"/gis/{lid}/share", a, body={"audiences": ["city"], "public_properties": ["apn"]})
        _, layer, _ = self.call("GET", P + f"/gis/{lid}", self.tokens["viewer_city"])
        self.assertEqual(layer["features"][0]["properties"], {"apn": "1"})
        _, inside, _ = self.call("GET", P + f"/gis/{lid}", a)
        self.assertIn("asking_price", inside["features"][0]["properties"])

    def test_the_project_site_goes_outside_the_team_by_an_allow_list(self):
        a = self.tokens["administrator"]
        site = {"gross_acres": 120, "location": "Sample place", "zoning": "SP", "apns": ["1"],
                "pre_development_basis_usd": {"land_acquisition": 1, "total": 2}, "core_retained_net_acres": 30,
                "paced_release": "5 acres every 2 years", "mandate": "keep the core",
                "assumption_ids": {"basis": "A-1", "retained_core": "A-2"},
                "parcel_details": {"111-222-333": {"parcel": "Parcel 1", "gross_acres": 10, "price_note": "x"}}}
        self.assertEqual(self.call("POST", P, a, body={"site": site})[0], 200)
        for who in ("viewer_city", "viewer_partner", "consultant"):
            _, b, _ = self.call("GET", P, self.tokens[who])
            self.assertEqual(b["project"]["site"], {"gross_acres": 120, "location": "Sample place", "zoning": "SP",
                                                    "apns": ["1"], "parcel_details": {"111-222-333": {
                                                        "parcel": "Parcel 1", "gross_acres": 10}}}, who)
        _, b, _ = self.call("GET", P, a)
        self.assertEqual(b["project"]["site"]["core_retained_net_acres"], 30)


# ---------------------------------------------------------------- F05, F06, F07: notes and uploads between firms

class NotesAndUploads(Base):
    def test_a_consultant_does_not_read_notes_on_drafts_they_cannot_open(self):
        _, sc, _ = self.call("POST", P + "/datasets", self.tokens["analyst"], body={"kind": "scenario", "label": "S"})
        sid = sc["dataset"]["id"]
        _, n, _ = self.call("POST", P + "/notes", self.tokens["analyst"],
                            body={"target": {"dataset": sid, "entity": "assumptions", "id": "A-RET-GLA"},
                                  "text": "internal walk-away figure (invented)"})
        self.call("POST", P + "/notes", self.tokens["analyst"],
                  body={"target": {"entity": "assumptions", "id": "A-RET-GLA"}, "text": "on the baseline"})
        _, notes, _ = self.call("GET", P + "/notes", self.tokens["consultant"])
        self.assertEqual([x["text"] for x in notes["notes"]], ["on the baseline"])
        _, fig, _ = self.call("GET", P + "/datasets/baseline/figures/A-RET-GLA", self.tokens["consultant"])
        self.assertNotIn("walk-away", json.dumps(fig))
        self.assertEqual(self.call("POST", P + f"/notes/{n['note']['id']}/replies", self.tokens["consultant"],
                                   body={"text": "hi"})[0], 404)
        self.assertEqual(self.call("POST", P + "/notes", self.tokens["consultant"],
                                   body={"target": {"dataset": sid, "entity": "assumptions", "id": "A-RET-GLA"},
                                         "text": "x"})[0], 403)
        _, inside, _ = self.call("GET", P + "/notes", self.tokens["analyst"])
        self.assertEqual(len(inside["notes"]), 2)

    def test_a_consultant_cannot_replace_a_document_shared_with_the_city(self):
        a = self.tokens["administrator"]
        _, b, _ = self.call("POST", P + "/documents", a, raw=b"%PDF-1.4 official\n", query={"name": "b.pdf"})
        doc = b["document"]["id"]
        self.call("POST", P + f"/documents/{doc}/share", a, body={"audiences": ["consultant", "city"]})
        s, _, _ = self.call("POST", P + "/documents", self.tokens["consultant"], raw=b"%PDF-1.4 replaced\n",
                            query={"name": "b.pdf", "document": doc, "title": "Final"})
        self.assertEqual(s, 403)
        _, body, _ = self.call("GET", P + f"/documents/{doc}/latest", self.tokens["viewer_city"])
        self.assertEqual(body, b"%PDF-1.4 official\n")
        # a consultant still adds versions to their own document
        _, mine, _ = self.call("POST", P + "/documents", self.tokens["consultant"], raw=b"%PDF-1.4 v1\n",
                               query={"name": "m.pdf"})
        s, b, _ = self.call("POST", P + "/documents", self.tokens["consultant"], raw=b"%PDF-1.4 v2\n",
                            query={"name": "m.pdf", "document": mine["document"]["id"]})
        self.assertEqual((s, len(b["document"]["versions"])), (200, 2))

    def test_one_consultant_firm_does_not_see_another_firms_uploads(self):
        self.add_user("Second Firm", "consultant", ["sample-district"])
        other = self.sign_in("Second Firm", "pass-consultant-1")
        mine = self.tokens["consultant"]
        _, d, _ = self.call("POST", P + "/documents", mine, raw=b"%PDF-1.4\n",
                            query={"name": "fee.pdf", "title": "Firm A fee proposal"})
        fc = {"type": "FeatureCollection", "features": []}
        _, g, _ = self.call("POST", P + "/gis", mine, raw=json.dumps(fc).encode(), query={"name": "firm-a.geojson"})
        _, docs, _ = self.call("GET", P + "/documents", other)
        self.assertNotIn("Firm A fee proposal", json.dumps(docs))
        self.assertEqual(self.call("GET", P + f"/documents/{d['document']['id']}/latest", other)[0], 403)
        self.assertEqual(self.call("GET", P + f"/gis/{g['layer']['id']}", other)[0], 403)
        self.assertEqual(self.call("GET", P + f"/documents/{d['document']['id']}/latest", mine)[0], 200)
        self.assertEqual(self.call("GET", P + f"/gis/{g['layer']['id']}", mine)[0], 200)
        _, inside, _ = self.call("GET", P + "/documents", self.tokens["analyst"])
        self.assertIn("Firm A fee proposal", json.dumps(inside))


# ---------------------------------------------------------------- F10 to F13: signing in

class SigningIn(Base):
    def test_a_stranger_cannot_lock_out_the_right_passcode(self):
        for _ in range(8):
            self.call("POST", "/api/districts/session", body={"method": "passcode", "name": "Admin", "passcode": "no"},
                      client="198.51.100.7")
        s, b, _ = self.call("POST", "/api/districts/session", body={"method": "passcode", "name": "Admin",
                                                                    "passcode": "admin-pass-1"}, client="198.51.100.7")
        self.assertEqual(s, 429, "the guessing caller is held back")
        s, b, _ = self.call("POST", "/api/districts/session", body={"method": "passcode", "name": "Admin",
                                                                    "passcode": "admin-pass-1"}, client="192.0.2.10")
        self.assertEqual(s, 200, b)

    def test_one_caller_guessing_many_names_is_held_back(self):
        for i in range(25):
            self.call("POST", "/api/districts/session", body={"method": "passcode", "name": f"Name {i}",
                                                              "passcode": "x"}, client="198.51.100.8")
        s, _, _ = self.call("POST", "/api/districts/session", body={"method": "passcode", "name": "Admin",
                                                                    "passcode": "admin-pass-1"}, client="198.51.100.8")
        self.assertEqual(s, 429)

    def test_a_huge_sign_in_name_is_not_written_to_the_audit_log(self):
        log = self.data / "district-audit.jsonl"
        before = log.stat().st_size
        self.call("POST", "/api/districts/session", body={"method": "passcode", "name": "N" * 200_000, "passcode": "x"})
        self.assertLess(log.stat().st_size - before, 5_000)
        self.api.audit.log("note", None, detail_text="x" * 100_000, many=list(range(10_000)))
        self.assertLess(log.stat().st_size - before, 15_000)

    def test_an_unknown_name_costs_the_same_passcode_work(self):
        from unittest import mock
        with mock.patch.object(access, "dummy_check", wraps=access.dummy_check) as dummy:
            self.call("POST", "/api/districts/session", body={"method": "passcode", "name": "Nobody", "passcode": "x"})
        self.assertEqual(dummy.call_count, 1)

    def test_changing_a_passcode_ends_the_other_sessions(self):
        first = self.tokens["viewer_partner"]
        second = self.sign_in("Viewer_Partner", "pass-viewer_partner-1")
        s, b, _ = self.call("POST", "/api/districts/session/passcode", second,
                            body={"old": "pass-viewer_partner-1", "new": "new-pass-partner-2"})
        self.assertEqual(s, 200, b)
        self.assertEqual(self.call("GET", "/api/districts/projects", first)[0], 401)
        self.assertEqual(self.call("GET", "/api/districts/projects", second)[0], 200)

    def test_wrong_current_passcodes_count_as_wrong_tries(self):
        t = self.tokens["viewer_partner"]
        for _ in range(5):
            self.assertEqual(self.call("POST", "/api/districts/session/passcode", t,
                                       body={"old": "wrong-one-1", "new": "new-pass-partner-2"})[0], 403)
        self.assertEqual(self.call("POST", "/api/districts/session/passcode", t,
                                   body={"old": "pass-viewer_partner-1", "new": "new-pass-partner-2"})[0], 429)


# ---------------------------------------------------------------- the audit log: reads and refusals

class AuditMore(Base):
    def audit(self, **query):
        return self.call("GET", "/api/districts/audit", self.tokens["administrator"], query=query)[1]["entries"]

    def test_viewers_reads_of_data_are_in_the_audit_log(self):
        city = self.tokens["viewer_city"]
        self.call("GET", P + "/datasets/baseline", city)
        self.call("GET", P + "/datasets/baseline", city)          # the same read soon after is not logged again
        layers = self.call("GET", P + "/gis", self.tokens["consultant"])[1]["layers"]
        self.call("GET", P + f"/gis/{layers[0]['id']}", self.tokens["consultant"])
        self.call("GET", P + "/datasets/baseline", self.tokens["administrator"])
        reads = self.audit(action="read")
        self.assertEqual(sorted((e["name"], e["detail"]["what"]) for e in reads),
                         [("Consultant", "layer"), ("Viewer_City", "dataset")])

    def test_a_refused_last_administrator_change_is_logged(self):
        a = self.tokens["administrator"]
        admin = next(u for u in self.call("GET", "/api/districts/users", a)[1]["users"] if u["role"] == "administrator")
        self.assertEqual(self.call("POST", "/api/districts/users", a, body={"id": admin["id"], "role": "analyst"})[0], 409)
        self.assertEqual(self.call("POST", "/api/districts/users", a, body={"id": admin["id"], "status": "INACTIVE"})[0],
                         409)
        self.assertEqual(self.call("DELETE", f"/api/districts/users/{admin['id']}", a)[0], 409)
        refused = [e for e in self.audit(outcome="denied") if e["detail"].get("why") == "last administrator"]
        self.assertEqual(sorted(e["action"] for e in refused), ["user-change", "user-change", "user-remove"])


# ---------------------------------------------------------------- F09, F14 and the cookie name: through the HTTP server

class ThroughTheServer(unittest.TestCase):
    def setUp(self):
        from landplanner.planner import LandPlanner
        from landplanner.server import make_server
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.server = make_server(LandPlanner({}, self.folder.name), 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]
        self.own = f"http://127.0.0.1:{self.port}"
        s, _, h = self.ask("POST", "/api/districts/session", b'{"method":"passcode","name":"Owner","passcode":"owner-pass-1"}',
                           {"Content-Type": "application/json", "Origin": self.own})
        self.assertEqual(s, 200)
        self.cookie = h["Set-Cookie"]
        self.jar = {"Cookie": self.cookie.split(";")[0]}
        self.ask("POST", "/api/districts/session/nda", b'{"accept":true}',
                 {**self.jar, "Content-Type": "application/json", "Origin": self.own})

    def ask(self, method, path, body=None, headers=None, raw_headers=None):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            c.putrequest(method, path, skip_accept_encoding=True)
            for k, v in (headers or {}).items():
                c.putheader(k, v)
            for k, v in raw_headers or ():
                c.putheader(k, v)
            if body is not None and not any(k.lower() == "content-length" for k, _ in raw_headers or ()):
                c.putheader("Content-Length", str(len(body)))
            c.endheaders(body)
            r = c.getresponse()
            return r.status, r.read(), dict(r.getheaders())
        finally:
            c.close()

    def test_the_cookie_name_holds_the_port_on_plain_http(self):
        self.assertTrue(self.cookie.startswith(f"lp_district_{self.port}="), self.cookie)
        self.assertEqual(self.ask("GET", "/api/districts/projects", headers=self.jar)[0], 200)
        other = {"Cookie": f"lp_district_{self.port + 1}=" + self.cookie.split(";")[0].split("=", 1)[1]}
        self.assertEqual(self.ask("GET", "/api/districts/projects", headers=other)[0], 401)

    def test_an_empty_post_from_another_local_port_is_refused(self):
        backups = "/api/districts/projects/sample-district/backups"
        other = f"http://127.0.0.1:{self.port + 1}"
        for headers in ({**self.jar, "Origin": other}, {**self.jar}, {**self.jar, "Sec-Fetch-Site": "same-site"},
                        {**self.jar, "Origin": self.own, "Sec-Fetch-Site": "same-site"}):
            self.assertEqual(self.ask("POST", backups, b"", headers)[0], 403, headers)
        # this server's own page: no body still needs a type a plain fetch cannot send unasked
        self.assertEqual(self.ask("POST", backups, b"", {**self.jar, "Origin": self.own})[0], 415)
        self.assertEqual(self.ask("POST", backups, b"", {**self.jar, "Origin": self.own, "X-Land-Planner": "1"})[0], 200)
        self.assertEqual(self.ask("POST", backups, b"", {**self.jar, "Sec-Fetch-Site": "same-origin",
                                                         "Content-Type": "application/json"})[0], 200)
        self.assertEqual(self.ask("DELETE", "/api/districts/session", None, {**self.jar})[0], 403)

    def test_two_content_lengths_are_refused(self):
        s, _, _ = self.ask("POST", "/api/districts/session", b"{}", {"Content-Type": "application/json",
                                                                     "Origin": self.own},
                           raw_headers=[("Content-Length", "2"), ("Content-Length", "0")])
        self.assertEqual(s, 400)

    def test_a_silent_connection_is_closed_and_others_are_served(self):
        import socket
        self.server.request_timeout = 1
        s = socket.create_connection(("127.0.0.1", self.port))
        self.addCleanup(s.close)
        s.sendall(b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\n")
        self.assertEqual(self.ask("GET", "/api/health")[0], 200)
        s.settimeout(5)
        try:
            self.assertEqual(s.recv(100), b"")
        except ConnectionError:
            pass


if __name__ == "__main__":
    unittest.main()
