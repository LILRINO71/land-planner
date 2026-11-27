"""District projects: who may do what, enforced on the server. The role matrix (each role against each route),
the city view's field filtering, the last-administrator rule, the audit log's hash chain, the idle time-out, the
NDA, Google sign-in (Google's answer replayed), no NaN in any answer, and the real HTTP server's cookie and
upload handling. Offline, in a temporary data folder, on the invented sample."""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from landplanner.district import access, chain, exports  # noqa: E402
from landplanner.district.api import DistrictAPI  # noqa: E402
from landplanner.district.store import Store  # noqa: E402

access.ITERATIONS = 1000
P = "/api/districts/projects/sample-district"
ROLES = ("administrator", "analyst", "consultant", "viewer_partner", "viewer_city")
CLIENT = "123456789-sample.apps.googleusercontent.com"
DENIED_KEYS = ("price_floor", "target_price", "rlv", "rlv_per_acre", "funding_target", "irr", "yield_on_cost")


class Clock:
    def __init__(self, now=1_790_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def strict(text):
    """json.loads that fails on NaN or Infinity."""
    def refuse(name):
        raise AssertionError(f"{name} in an answer")
    return json.loads(text, parse_constant=refuse)


class Base(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.clock = Clock()
        self.google = {}
        self.api = DistrictAPI(self.folder.name, self.clock, tokeninfo=lambda token: dict(self.google))
        self.tokens = {"administrator": self.sign_in("Admin", "admin-pass-1")}
        for role in ROLES[1:]:
            self.add_user(role.title(), role, ["sample-district"])
            self.tokens[role] = self.sign_in(role.title(), f"pass-{role}-1")

    def call(self, method, path, token=None, **kw):
        r = self.api.handle(method, path, {k: [str(v)] for k, v in (kw.pop("query", None) or {}).items()},
                            {**({"Cookie": f"lp_district={token}"} if token else {}),
                             **({"Content-Type": kw.get("kind", "application/json")} if "body" in kw or "raw" in kw else {})},
                            kw["raw"] if "raw" in kw else json.dumps(kw["body"]).encode() if "body" in kw else b"")
        if r.kind.startswith("application/json"):
            return r.status, strict(r.body.decode("utf-8")), r.headers
        return r.status, r.body, r.headers

    def sign_in(self, name, passcode, nda=True):
        s, b, h = self.call("POST", "/api/districts/session", body={"method": "passcode", "name": name,
                                                                    "passcode": passcode})
        self.assertEqual(s, 200, b)
        token = h["Set-Cookie"].split(";")[0].split("=", 1)[1]
        if nda:
            self.assertEqual(self.call("POST", "/api/districts/session/nda", token, body={"accept": True})[0], 200)
        return token

    def add_user(self, name, role, projects=(), **more):
        s, b, _ = self.call("POST", "/api/districts/users", self.tokens["administrator"],
                            body={"name": name, "role": role, "projects": list(projects),
                                  "passcode": f"pass-{role}-1", **more})
        self.assertEqual(s, 200, b)
        return b["user"]

    def audit(self, **query):
        return self.call("GET", "/api/districts/audit", self.tokens["administrator"], query=query)[1]


class RoleMatrix(Base):
    def consultant_dataset(self):
        return next(d["id"] for d in self.call("GET", P + "/datasets", self.tokens["administrator"])[1]["datasets"]
                    if d["kind"] == "consultant")

    def test_each_role_against_each_route(self):
        A, N, C, V, Y = ROLES
        everyone, workers, internal, admin = set(ROLES), {A, N, C}, {A, N}, {A}
        record = {"entity": "risks", "record": {"id": "r-new", "title": "New risk"}, "reason": "test"}
        sub = self.consultant_dataset()
        routes = [
            ("GET", "/api/districts/users", {}, admin),
            ("GET", "/api/districts/audit", {}, admin),
            ("GET", "/api/districts/settings", {}, admin),
            ("GET", "/api/districts/templates", {}, workers),
            ("GET", "/api/districts/projects", {}, everyone),
            ("GET", P, {}, everyone),
            ("GET", P + "/modules", {}, everyone),
            ("GET", P + "/datasets/baseline", {}, everyone),
            ("GET", P + "/datasets/baseline", {"query": {"version": "draft"}}, internal),
            ("GET", P + "/datasets/baseline/versions", {}, everyone),
            ("GET", f"{P}/datasets/{sub}", {"query": {"version": "draft"}}, internal),
            ("POST", P + "/datasets/baseline/records", {"body": record}, internal),
            ("POST", f"{P}/datasets/{sub}/records", {"body": record}, internal),
            ("POST", P + "/datasets/baseline/publish", {"body": {"note": "x"}}, admin),
            ("POST", P + "/datasets/baseline/rollback", {"body": {"version": 1, "reason": "x"}}, admin),
            ("POST", P + "/datasets", {"body": {"kind": "scenario", "label": "S"}}, internal),
            ("POST", P + "/datasets", {"body": {"kind": "consultant", "label": "C"}}, workers),
            ("GET", P + "/datasets/baseline/checks", {}, workers),
            ("GET", P + "/datasets/baseline/figures/A-RET-GLA", {}, everyone),
            ("GET", P + "/revisions", {}, internal),
            ("GET", P + "/compare", {"query": {"other": sub}}, internal),
            ("GET", P + "/notes", {}, workers),
            ("POST", P + "/notes", {"body": {"target": {"entity": "assumptions", "id": "A-RET-GLA"}, "text": "?"}},
             workers),
            ("GET", P + "/documents", {}, everyone),
            ("POST", P + "/documents", {"query": {"name": "a.pdf"}, "raw": b"%PDF-1.4 x",
                                        "kind": "application/octet-stream"}, workers),
            ("GET", P + "/gis", {}, everyone),
            ("GET", P + "/backups", {}, admin),
            ("GET", P + "/package.zip", {}, admin),
            ("POST", P + "/modules", {"body": {"modules": []}}, admin),
            ("POST", P, {"body": {"name": "Sample District"}}, admin),
            ("POST", "/api/districts/projects", {"body": {"name": "Another"}}, admin),
            ("GET", P + "/export/table.xlsx", {"query": {"entity": "risks"}}, everyone),
        ]
        for method, path, kw, allowed in routes:
            for role in ROLES:
                s, b, _ = self.call(method, path, self.tokens[role], **{k: v for k, v in kw.items()})
                want = 200 if role in allowed else 403
                if s == 501:                                  # a writer another worker owns is not there yet
                    continue
                self.assertEqual(s, want, f"{role} {method} {path}: {b}")
        self.assertGreater(self.audit(action="denied")["total"], 20)

    def test_a_consultant_edits_only_their_own_submission(self):
        t = self.tokens["consultant"]
        s, b, _ = self.call("POST", P + "/datasets", t, body={"kind": "consultant", "label": "Mine"})
        mine = b["dataset"]["id"]
        rec = {"entity": "risks", "record": {"id": "r-mine", "title": "Mine"}}
        self.assertEqual(self.call("POST", f"{P}/datasets/{mine}/records", t, body=rec)[0], 200)
        self.assertEqual(self.call("GET", f"{P}/datasets/{mine}", t, query={"version": "draft"})[0], 200)
        self.assertEqual(self.call("POST", f"{P}/datasets/{mine}/publish", t, body={})[0], 403)
        listed = [d["id"] for d in self.call("GET", P + "/datasets", t)[1]["datasets"]]
        self.assertEqual(sorted(listed), sorted(["baseline", mine]))

    def test_people_see_only_the_projects_they_are_assigned(self):
        self.add_user("Outsider", "viewer_partner", [])
        t = self.sign_in("Outsider", "pass-viewer_partner-1")
        self.assertEqual(self.call("GET", "/api/districts/projects", t)[1]["projects"], [])
        self.assertEqual(self.call("GET", P, t)[0], 403)
        self.assertIn("Outsider", [e["name"] for e in self.audit(action="denied")["entries"]])

    def test_viewer_exports_follow_the_project_setting(self):
        self.call("POST", P, self.tokens["administrator"], body={"settings": {"partner_export": False}})
        s, _, _ = self.call("GET", P + "/export/table.xlsx", self.tokens["viewer_partner"])
        self.assertEqual(s, 403)

    def test_a_viewer_cannot_widen_their_view(self):
        s, b, _ = self.call("GET", P + "/datasets/baseline", self.tokens["viewer_city"], query={"audience": "internal"})
        self.assertEqual(s, 403)


class CityView(Base):
    def walk(self, obj, path="", found=None):
        found = [] if found is None else found
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in DENIED_KEYS:
                    found.append(path + "/" + k)
                self.walk(v, path + "/" + k, found)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                self.walk(v, f"{path}[{i}]", found)
        return found

    def test_the_city_never_receives_returns_land_values_or_pricing(self):
        t = self.tokens["viewer_city"]
        content = self.call("GET", P + "/datasets/baseline", t)[1]["content"]
        self.assertEqual(self.walk(content), [])
        ids = {a["id"] for a in content["entities"]["assumptions"]}
        self.assertFalse({"A-IRR", "A-YOC", "A-RLV-RETAIL"} & ids)
        self.assertIn("A-RET-GLA", ids)
        sections = {s["id"] for s in content["entities"]["sections"]}
        self.assertNotIn("s-returns", sections)
        self.assertNotIn("s-disposition", sections)
        self.assertEqual(content["entities"]["parcels"][0]["acres"], 20)          # the parcel is still there
        mods = self.call("GET", P + "/modules", t)[1]["modules"]
        self.assertNotIn("returns", [m["id"] for m in mods])
        parcels = next(m for m in mods if m["id"] == "parcels")
        self.assertEqual(parcels["cards"], [])
        self.assertNotIn("price_floor", parcels["tables"][0]["columns"])
        layer = self.call("GET", P + "/gis", t)[1]["layers"][0]
        fc = self.call("GET", f"{P}/gis/{layer['id']}", t)[1]
        self.assertEqual(self.walk(fc), [])
        self.assertEqual(self.call("GET", P + "/datasets/baseline/figures/A-IRR", t)[1]["found"], False)
        self.assertEqual(self.walk(self.call("GET", P, t)[1]), [])

    def test_the_partner_and_the_administrator_still_see_them(self):
        content = self.call("GET", P + "/datasets/baseline", self.tokens["viewer_partner"])[1]["content"]
        self.assertIn("A-IRR", {a["id"] for a in content["entities"]["assumptions"]})
        self.assertIn("price_floor", content["entities"]["parcels"][0])
        city_preview = self.call("GET", P + "/datasets/baseline", self.tokens["administrator"],
                                 query={"audience": "city"})[1]
        self.assertEqual((city_preview["audience"], self.walk(city_preview["content"])), ("city", []))

    def test_an_untagged_figure_whose_words_are_sensitive_is_kept_from_the_city(self):
        a = self.tokens["administrator"]
        rec = {"id": "A-HIDDEN", "label": "Levered IRR, Phase 2", "value": 20, "unit": "pct", "status": "Baseline",
               "provenance": "CALCULATED"}
        self.call("POST", P + "/datasets/baseline/records", a, body={"entity": "assumptions", "record": rec})
        self.call("POST", P + "/datasets/baseline/publish", a, body={})
        ids = {x["id"] for x in self.call("GET", P + "/datasets/baseline", self.tokens["viewer_city"])[1]
               ["content"]["entities"]["assumptions"]}
        self.assertNotIn("A-HIDDEN", ids)
        checks = self.call("GET", P + "/datasets/baseline/checks", a)[1]
        self.assertIn("A-HIDDEN", [x["id"] for x in checks["untagged_sensitive"]])

    def test_exports_are_filtered_marked_and_carry_the_audience_disclaimer(self):
        seen = {}
        if True:
            def fake(name, func):
                def write(doc, widths=None):
                    seen[name] = doc
                    return b"file"
                return write
            with mock.patch.object(exports, "_writer", fake):
                s, _, h = self.call("GET", P + "/export/module.pdf", self.tokens["viewer_city"],
                                    query={"module": "parcels"})
                self.assertEqual(s, 200)
                doc = seen["pdf"]
                text = json.dumps(doc)
                self.assertEqual(doc["watermark"], "CONFIDENTIAL")
                self.assertIn("City-facing view", doc["disclaimer"])
                self.assertNotIn("Price floor", text)
                self.assertNotIn("10000000", text)
                s, _, _ = self.call("GET", P + "/export/table.xlsx", self.tokens["viewer_partner"],
                                    query={"entity": "parcels"})
                sheet = seen["xlsx"]["parcels"]
                self.assertEqual(sheet[2], ["Reg D disclaimer: wording to be supplied by counsel"])
                self.assertIn("price_floor", sheet[4])
                self.call("GET", P + "/export/table.xlsx", self.tokens["viewer_city"], query={"entity": "parcels"})
                self.assertNotIn("price_floor", seen["xlsx"]["parcels"][4])
        exported = self.audit(action="export")["entries"]
        self.assertEqual({e["detail"]["audience"] for e in exported}, {"city", "partner"})


class Directory(Base):
    def admin_id(self):
        return next(u["id"] for u in self.call("GET", "/api/districts/users", self.tokens["administrator"])[1]["users"]
                    if u["role"] == "administrator")

    def test_the_last_active_administrator_cannot_be_removed_deactivated_or_downgraded(self):
        a, uid = self.tokens["administrator"], self.admin_id()
        for body in ({"id": uid, "role": "analyst"}, {"id": uid, "status": "INACTIVE"}):
            s, b, _ = self.call("POST", "/api/districts/users", a, body=body)
            self.assertEqual((s, b["error"]["code"]), (409, "last-admin"))
        s, b, _ = self.call("DELETE", f"/api/districts/users/{uid}", a)
        self.assertEqual((s, b["error"]["code"]), (409, "last-admin"))
        second = self.add_user("Second", "administrator")
        self.assertEqual(self.call("POST", "/api/districts/users", a, body={"id": uid, "role": "analyst"})[0], 200)
        self.assertEqual(self.call("GET", "/api/districts/users", a)[0], 401, "a changed role ends the old session")
        t2 = self.sign_in("Second", "pass-administrator-1")
        s, b, _ = self.call("POST", "/api/districts/users", t2, body={"id": second["id"], "status": "INACTIVE"})
        self.assertEqual(s, 409)

    def test_the_first_person_to_sign_in_becomes_the_administrator_and_nobody_else_gets_in_by_name(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        api = DistrictAPI(folder.name, self.clock)
        s, b, _ = api.call("GET", "/api/districts/session")
        self.assertTrue(b["bootstrap"])
        s, b, _ = api.call("POST", "/api/districts/session", body={"method": "passcode", "name": "First",
                                                                   "passcode": "first-pass-1"})
        self.assertEqual((s, b["user"]["role"], b["nda"]["required"]), (200, "administrator", True))
        self.assertTrue(Store(folder.name).exists("sample-district"))
        s, b, _ = api.call("POST", "/api/districts/session", body={"method": "passcode", "name": "Second",
                                                                   "passcode": "second-pass-1"})
        self.assertEqual(s, 401)

    def test_wrong_passcodes_are_refused_logged_and_locked_out_after_five(self):
        for _ in range(5):
            s, b, _ = self.call("POST", "/api/districts/session", body={"method": "passcode", "name": "Analyst",
                                                                        "passcode": "wrong-wrong"})
            self.assertEqual(s, 401)
        s, _, _ = self.call("POST", "/api/districts/session", body={"method": "passcode", "name": "Analyst",
                                                                    "passcode": "pass-analyst-1"})
        self.assertEqual(s, 429)
        self.clock.now += 16 * 60
        self.sign_in("Analyst", "pass-analyst-1")
        self.assertGreaterEqual(self.audit(action="sign-in", outcome="denied")["total"], 6)

    def test_the_nda_is_needed_before_any_data_and_is_recorded(self):
        self.add_user("Newcomer", "viewer_city", ["sample-district"])
        t = self.sign_in("Newcomer", "pass-viewer_city-1", nda=False)
        s, b, _ = self.call("GET", P, t)
        self.assertEqual((s, b["error"]["code"]), (403, "nda-needed"))
        s, b, _ = self.call("POST", "/api/districts/session/nda", t, body={"accept": True})
        self.assertEqual((s, b["nda"]["required"], bool(b["user"]["nda_accepted_at"])), (200, False, True))
        self.assertEqual(self.call("GET", P, t)[0], 200)
        self.call("POST", "/api/districts/settings", self.tokens["administrator"], body={"nda_version": 2})
        self.assertEqual(self.call("GET", P, t)[1]["error"]["code"], "nda-needed")

    def test_passcodes_are_kept_as_salted_hashes(self):
        raw = (Path(self.folder.name) / "district-users.json").read_text(encoding="utf-8")
        self.assertNotIn("pass-analyst-1", raw)
        hashes = [u["passcode"] for u in json.loads(raw)["users"]]
        self.assertTrue(all(h.startswith("pbkdf2_sha256$") for h in hashes))
        self.assertEqual(len({h.split("$")[2] for h in hashes}), len(hashes))
        users = self.call("GET", "/api/districts/users", self.tokens["administrator"])[1]["users"]
        self.assertNotIn("passcode", json.dumps(users).replace("has_passcode", ""))


class Sessions(Base):
    def test_an_idle_session_ends_and_the_time_out_can_be_set(self):
        t = self.tokens["analyst"]
        self.clock.now += 29 * 60
        self.assertEqual(self.call("GET", P, t)[0], 200)
        self.clock.now += 29 * 60
        self.assertEqual(self.call("GET", P, t)[0], 200, "each request resets the clock")
        self.clock.now += 31 * 60
        s, b, h = self.call("GET", P, t)
        self.assertEqual((s, b["error"]["code"]), (401, "session-expired"))
        self.assertIn("Max-Age=0", h["Set-Cookie"])
        self.tokens["administrator"] = self.sign_in("Admin", "admin-pass-1")     # idle too: signed out as well
        self.assertGreaterEqual(self.audit(action="session-expired")["total"], 1)
        self.call("POST", "/api/districts/settings", self.tokens["administrator"], body={"idle_minutes": 5})
        t = self.sign_in("Analyst", "pass-analyst-1")
        self.clock.now += 6 * 60
        self.assertEqual(self.call("GET", P, t)[0], 401)

    def test_sign_out_ends_the_session(self):
        t = self.tokens["consultant"]
        s, b, h = self.call("DELETE", "/api/districts/session", t)
        self.assertEqual((s, b["signed_in"]), (200, False))
        self.assertEqual(self.call("GET", P, t)[0], 401)
        self.assertEqual(self.call("GET", P)[1]["error"]["code"], "sign-in-needed")


class Google(Base):
    def claims(self, **more):
        return {"aud": CLIENT, "iss": "https://accounts.google.com", "exp": str(int(self.clock.now) + 600),
                "email": "partner@example.com", "email_verified": "true", **more}

    def sign(self):
        return self.call("POST", "/api/districts/session", body={"method": "google",
                                                                 "id_token": "header.payload.signature-long-enough"})

    def test_google_sign_in_is_not_faked_when_no_client_id_is_set(self):
        s, b, _ = self.sign()
        self.assertEqual((s, b["error"]["code"]), (501, "google-not-set-up"))

    def test_only_an_active_directory_entry_gets_in_and_every_refusal_is_logged(self):
        a = self.tokens["administrator"]
        self.assertEqual(self.call("POST", "/api/districts/settings", a, body={"google_client_id": CLIENT})[0], 200)
        self.google = self.claims()
        s, b, _ = self.sign()
        self.assertEqual((s, b["error"]["code"]), (403, "not-authorized"))
        self.assertIn("partner@example.com", b["error"]["message"])
        user = self.add_user("Pat Partner", "viewer_partner", ["sample-district"], email="partner@example.com")
        s, b, h = self.sign()
        self.assertEqual((s, b["user"]["id"]), (200, user["id"]))
        for bad in (self.claims(aud="someone-else.apps.googleusercontent.com"), self.claims(email_verified="false"),
                    self.claims(exp=str(int(self.clock.now) - 1)), self.claims(iss="evil.example.com")):
            self.google = bad
            self.assertEqual(self.sign()[0], 401)
        self.call("POST", "/api/districts/users", a, body={"id": user["id"], "status": "INACTIVE"})
        self.google = self.claims()
        self.assertEqual(self.sign()[0], 403)
        denied = self.audit(action="sign-in", outcome="denied")["entries"]
        self.assertGreaterEqual(len([e for e in denied if e["detail"].get("method") == "google"]), 6)


class AuditChain(Base):
    def test_every_kind_of_event_is_logged_with_who_and_when_and_the_chain_shows_tampering(self):
        a = self.tokens["administrator"]
        self.call("POST", P + "/datasets/baseline/publish", a, body={"note": "n"})
        self.call("GET", P + "/export/table.xlsx", a)
        log = self.audit(limit=2000)
        actions = {e["action"] for e in log["entries"]}
        self.assertTrue({"sign-in", "nda", "user-add", "publish", "sample", "backup"} <= actions, actions)
        self.assertTrue(all(e["at"] and e["user"] for e in log["entries"] if e["action"] != "sign-in"))
        self.assertTrue(log["chain"]["ok"])
        path = Path(self.folder.name) / "district-audit.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[3] = lines[3].replace('"outcome": "ok"', '"outcome": "denied"')
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertEqual(chain.verify(path)["broken_at"], 4)
        self.assertFalse(self.audit()["chain"]["ok"])

    def test_the_audit_log_is_searchable(self):
        found = self.audit(q="Consultant", action="sign-in")
        self.assertTrue(found["total"] >= 1 and all(e["action"] == "sign-in" for e in found["entries"]))


class NoNaN(Base):
    def test_a_nan_cannot_get_in_and_one_already_on_disk_never_gets_out(self):
        a = self.tokens["administrator"]
        bad = {"id": "A-N", "label": "N", "value": "NaN", "unit": "sf", "status": "Baseline", "provenance": "CALCULATED"}
        self.assertEqual(self.call("POST", P + "/datasets/baseline/records", a,
                                   body={"entity": "assumptions", "record": bad})[0], 400)
        draft = Path(self.folder.name) / "projects" / "sample-district" / "datasets" / "baseline" / "draft.json"
        text = draft.read_text(encoding="utf-8").replace('"value": 180000', '"value": NaN', 1)
        draft.write_text(text, encoding="utf-8")
        for path, q in ((P + "/datasets/baseline", {"version": "draft"}), (P + "/datasets/baseline/checks",
                                                                            {"version": "draft"}),
                        (P + "/datasets/baseline/figures/A-RET-GLA", {"version": "draft"}),
                        (P + "/compare", {"base_version": "draft", "other": "baseline"})):
            s, b, _ = self.call("GET", path, a, query=q)          # strict() fails on NaN
            self.assertEqual(s, 200, b)

    def test_no_answer_on_any_read_route_holds_nan(self):
        for role, t in self.tokens.items():
            for path in ("/api/districts", "/api/districts/session", "/api/districts/projects", P, P + "/modules",
                         P + "/datasets", P + "/datasets/baseline", P + "/datasets/baseline/checks", P + "/gis",
                         P + "/documents", P + "/notes", P + "/revisions"):
                self.call("GET", path, t)                       # strict() raises on NaN or Infinity


class Landing(Base):
    BRAND = {"title": "RIDGE DISTRICT", "subtitle": "Invented Strategy Platform", "location": "Nowhere, California",
             "badge": "Private Sample Badge", "notice": "Invited Guests Only", "footer": ["Invented footer", "Line two"]}

    def landing(self):
        s, b, _ = self.call("GET", "/api/districts")          # no sign-in
        self.assertEqual(s, 200)
        return b

    def test_the_one_real_projects_branding_is_shown_before_sign_in_and_nothing_else(self):
        self.assertNotIn("landing", self.landing(), "only the sample: no landing")
        a = self.tokens["administrator"]
        self.assertEqual(self.call("POST", "/api/districts/projects", a, body={
            "id": "secret-ridge", "name": "Secret Ridge Holdings", "branding": self.BRAND,
            "site": {"gross_acres": 777}})[0], 200)
        b = self.landing()
        self.assertEqual(b["landing"], {"title": "RIDGE DISTRICT", "subtitle": "Invented Strategy Platform",
                                        "place": "Nowhere, California", "badge": "Private Sample Badge",
                                        "notice": "Invited Guests Only", "footer": "Invented footer · Line two"})
        text = json.dumps(b)
        for secret in ("secret-ridge", "Secret Ridge", "777", "sample-district"):
            self.assertNotIn(secret, text)
        self.call("POST", "/api/districts/projects", a, body={"id": "second-one", "name": "Second", "branding": self.BRAND})
        self.assertNotIn("landing", self.landing(), "two real projects: which one is not known")

    def test_the_settings_own_landing_wins_and_only_an_administrator_sets_it(self):
        mine = {"title": "SET BY HAND", "subtitle": "s", "place": "p", "badge": "b", "notice": "n", "footer": "a · b"}
        self.assertEqual(self.call("POST", "/api/districts/settings", self.tokens["analyst"],
                                   body={"landing": mine})[0], 403)
        self.assertEqual(self.call("POST", "/api/districts/settings", self.tokens["administrator"],
                                   body={"landing": {"title": "x", "figures": 1}})[0], 400)
        self.assertEqual(self.call("POST", "/api/districts/settings", self.tokens["administrator"],
                                   body={"landing": mine})[0], 200)
        self.assertEqual(self.landing()["landing"], mine)
        self.call("POST", "/api/districts/settings", self.tokens["administrator"], body={"landing": None})
        self.assertNotIn("landing", self.landing())


class RealServer(unittest.TestCase):
    """The district routes through the app's own HTTP server, beside the routes that need no sign-in."""

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

    def ask(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            c.request(method, path, body=body, headers=headers or {})
            r = c.getresponse()
            return r.status, r.read(), dict(r.getheaders())
        finally:
            c.close()

    def test_sign_in_sets_a_strict_http_only_cookie_and_files_go_up_as_bytes(self):
        s, _, _ = self.ask("GET", "/api/health")
        self.assertEqual(s, 200, "the app's own pages stay open without signing in")
        s, b, h = self.ask("POST", "/api/districts/session",
                           json.dumps({"method": "passcode", "name": "Owner", "passcode": "owner-pass-1"}),
                           {"Content-Type": "application/json"})
        self.assertEqual(s, 200, b)
        cookie = h["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        jar = {"Cookie": cookie.split(";")[0]}
        self.assertEqual(self.ask("POST", "/api/districts/session/nda", '{"accept": true}',
                                  {**jar, "Content-Type": "application/json"})[0], 200)
        s, b, _ = self.ask("GET", "/api/districts/projects", headers=jar)
        self.assertEqual((s, strict(b)["projects"][0]["id"]), (200, "sample-district"))
        s, b, _ = self.ask("POST", P + "/documents?name=memo.pdf", b"%PDF-1.4 memo",
                           {**jar, "Content-Type": "application/octet-stream"})
        self.assertEqual(s, 200, b)
        self.assertEqual(self.ask("POST", P + "/documents?name=memo.pdf", b"%PDF-1.4 memo",
                                  {**jar, "Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.ask("POST", "/api/districts/session", "{}",
                                  {"Content-Type": "application/json", "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.ask("GET", P)[0], 401)
        s, data, h = self.ask("GET", P + "/package.zip", headers=jar)
        self.assertEqual((s, data[:2]), (200, b"PK"))
        self.assertIn("attachment", h["Content-Disposition"])


if __name__ == "__main__":
    unittest.main()
