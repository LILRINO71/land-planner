"""The /api/districts routes (docs/district-data-contract.md, section 8). landplanner/server.py hands every request
under /api/districts to DistrictAPI.handle and sends back what it returns; nothing else in the app changes.

Order of checks on every request: a session (401), an active user (401), the NDA (403), the role and the project
assignment (403, logged as denied), then the dataset's visibility. Every answer and every export is filtered for
the caller's audience on the way out, and no answer can hold NaN or Infinity.
"""
import json
import time
import urllib.parse
from http.cookies import SimpleCookie
from pathlib import Path

from . import Problem, check_id, check_slug, day
from . import access as A
from . import compare as C
from . import exports as X
from . import gis as G
from . import importer as I
from . import register as R
from . import sample as S
from .audit import Audit
from .jsonsafe import dumps
from .schema import AUDIENCE_DENY, AUDIENCES, ENTITIES, UNITS
from .store import Store
from .validate import clean_record

COOKIE = "lp_district"
COOKIE_PATH = "/api/districts"
MAX_JSON = 2 * 1024 * 1024
MAX_FILE = 64 * 1024 * 1024


class Reply:
    def __init__(self, status, body, kind="application/json; charset=utf-8", headers=None):
        self.status, self.body, self.kind, self.headers = status, body, kind, dict(headers or {})


def _json(status, obj, headers=None):
    return Reply(status, dumps(obj, separators=(",", ":")).encode("utf-8"), headers=headers)


def _file(data, name, kind):
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:120]
    return Reply(200, data, kind, {"Content-Disposition": f'attachment; filename="{safe}"'})


def _q(query, name, default=""):
    v = (query.get(name) or [default])[0] if isinstance(query.get(name), list) else query.get(name, default)
    return str(v if v is not None else default).strip()[:200]


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class DistrictAPI:
    def __init__(self, data_dir, clock=time.time, tokeninfo=None):
        self.data_dir = Path(data_dir)
        self.clock = clock
        self.store = Store(self.data_dir, clock)
        self.users = A.Directory(self.data_dir, clock)
        self.settings = A.Settings(self.data_dir)
        self.sessions = A.Sessions(clock)
        self.audit = Audit(self.data_dir, clock)
        self.tokeninfo = tokeninfo or A.fetch_tokeninfo

    # ---------------------------------------------------------------- the entry point

    def handle(self, method, path, query=None, headers=None, body=None):
        query = query or {}
        headers = headers or {}
        try:
            parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/")]
            if parts[:2] != ["api", "districts"]:
                raise Problem(404, "not-found", "Nothing here.")
            req = {"method": method, "parts": parts[2:], "query": query, "headers": headers, "raw": body or b"",
                   "kind": str(headers.get("Content-Type") or "").lower(), "token": self._token(headers)}
            return self._route(req)
        except Problem as e:
            extra = {"Set-Cookie": self._clear()} if e.code == "session-expired" else None
            return _json(e.status, {"error": {"code": e.code, "message": e.message}}, extra)

    def call(self, method, path, query=None, body=None, token=None, raw=None, kind=None):
        """For tests and other modules: (status, answer or bytes, headers)."""
        headers = {}
        if token:
            headers["Cookie"] = f"{COOKIE}={token}"
        if raw is not None:
            headers["Content-Type"] = kind or "application/octet-stream"
            data = raw
        elif body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        else:
            data = b""
        q = {k: [str(v)] for k, v in (query or {}).items()}
        r = self.handle(method, path, q, headers, data)
        if r.kind.startswith("application/json"):
            return r.status, json.loads(r.body.decode("utf-8")), r.headers
        return r.status, r.body, r.headers

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _token(headers):
        raw = headers.get("Cookie") or ""
        try:
            c = SimpleCookie()
            c.load(raw)
            return c[COOKIE].value if COOKIE in c else None
        except Exception:  # noqa: BLE001 - an unreadable cookie is no cookie
            return None

    @staticmethod
    def _cookie(token):
        return f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path={COOKIE_PATH}"

    @staticmethod
    def _clear():
        return f"{COOKIE}=; HttpOnly; SameSite=Strict; Path={COOKIE_PATH}; Max-Age=0"

    def _body(self, req):
        if req["method"] != "POST":
            return {}
        if not req["raw"]:
            return {}
        if "application/json" not in req["kind"]:
            raise Problem(415, "bad-request", "Send JSON.")
        if len(req["raw"]) > MAX_JSON:
            raise Problem(413, "too-large", "Too much data.")
        try:
            out = json.loads(req["raw"].decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise Problem(400, "bad-request", "That was not readable JSON.") from None
        if not isinstance(out, dict):
            raise Problem(400, "bad-request", "Send a JSON object.")
        return out

    @staticmethod
    def _bytes(req):
        if "application/octet-stream" not in req["kind"]:
            raise Problem(415, "bad-request", "Send the file's bytes as application/octet-stream, with ?name=.")
        if len(req["raw"]) > MAX_FILE:
            raise Problem(413, "too-large", "That file is larger than 64 MB.")
        if not req["raw"]:
            raise Problem(400, "bad-request", "The file is empty.")
        return req["raw"]

    def _need(self, ctx, action, project=None, dataset=None):
        if not A.can(ctx["user"], action, project, dataset):
            self.audit.log("denied", ctx["user"], "denied", (project or {}).get("id"), wanted=action,
                           dataset=(dataset or {}).get("id"))
            raise Problem(403, "forbidden", "Your role does not allow that here.")

    def _deny(self, ctx, project, wanted="item"):
        self.audit.log("denied", ctx["user"], "denied", (project or {}).get("id"), wanted=wanted)
        raise Problem(403, "forbidden", "Your role does not allow that here.")

    def _session_view(self, user):
        s = self.settings.get()
        return {"signed_in": True, "user": A.public(user), "audience": A.ROLE_AUDIENCE[user["role"]],
                "nda": {"required": user.get("nda_version") != s["nda_version"], "version": s["nda_version"],
                        "text": s["nda_text"]}, "idle_minutes": s["idle_minutes"]}

    def _signed_out_view(self):
        s = self.settings.get()
        return {"signed_in": False, "bootstrap": self.users.empty(),
                "google": {"enabled": bool(s["google_client_id"]), "client_id": s["google_client_id"] or None}}

    def _current(self, req, need_nda=True):
        s = self.settings.get()
        uid, state = self.sessions.find(req["token"], s["idle_minutes"])
        if state == "expired":
            self.audit.log("session-expired", self.users.get(uid) or {"id": uid}, "ok")
            raise Problem(401, "session-expired", "You were signed out after a time without use. Sign in again.")
        if state != "ok":
            raise Problem(401, "sign-in-needed", "Sign in first.")
        user = self.users.get(uid)
        if not user or user.get("status") != "ACTIVE":
            self.sessions.end(req["token"])
            raise Problem(401, "sign-in-needed", "This account is no longer active. Sign in again.")
        if need_nda and user.get("nda_version") != s["nda_version"]:
            raise Problem(403, "nda-needed", "Acknowledge the confidentiality agreement first.")
        return {"user": user, "token": req["token"]}

    def _project(self, ctx, pid):
        project = self.store.project(check_slug(pid, "project id"))
        self._need(ctx, "project.view", project)
        made = self.store.daily_backup(pid)
        if made:
            self.audit.log("backup", ctx["user"], "ok", pid, backup=made["name"], why="daily")
        return project

    def _dataset(self, ctx, project, did, version):
        """(meta, resolved version, content) when the user may read it, else a logged 403."""
        meta = self.store.dataset(project["id"], check_slug(did, "dataset id"))
        vis = A.versions_visible(ctx["user"], meta)
        v = version or ("draft" if vis == "all" and not meta.get("current") else "published")
        if vis is None or (v == "draft" and vis != "all"):
            self.audit.log("denied", ctx["user"], "denied", project["id"], wanted="dataset.read", dataset=did,
                           version=str(v))
            raise Problem(403, "forbidden", "Your role cannot open that dataset or version.")
        resolved = self.store.resolve_version(project["id"], did, v)
        return meta, resolved, self.store.content(project["id"], did, v)

    def _visible_datasets(self, ctx, pid):
        return [m for m in self.store.datasets(pid) if A.versions_visible(ctx["user"], m)]

    def _modules_for(self, ctx, project, audience):
        mods = self.store.modules(project["id"])
        if audience == "internal":
            return A.filter_modules(mods, audience)
        try:
            meta = self.store.dataset(project["id"], "baseline")
            content = self.store.content(project["id"], "baseline", "published") if meta.get("current") else None
        except Problem:
            content = None
        filtered = A.filter_content(content, audience) if content else {"entities": {"assumptions": []}}
        return A.filter_modules(mods, audience, filtered)

    # ---------------------------------------------------------------- routing

    def _route(self, req):
        m, p = req["method"], req["parts"]
        if p == [] and m == "GET":
            return _json(200, self._status(req))
        if p == ["session"]:
            if m == "GET":
                try:
                    ctx = self._current(req, need_nda=False)
                except Problem as e:
                    if e.code == "session-expired":
                        raise
                    return _json(200, self._signed_out_view())
                return _json(200, self._session_view(ctx["user"]))
            if m == "POST":
                return self._sign_in(self._body(req))
            if m == "DELETE":
                uid, state = self.sessions.find(req["token"], 10 ** 6)
                if state == "ok":
                    self.sessions.end(req["token"])
                    self.audit.log("sign-out", self.users.get(uid) or {"id": uid})
                return _json(200, self._signed_out_view(), {"Set-Cookie": self._clear()})
        if p == ["session", "nda"] and m == "POST":
            ctx = self._current(req, need_nda=False)
            if self._body(req).get("accept") is not True:
                raise Problem(400, "bad-request", "Send {\"accept\": true} to acknowledge the agreement.")
            v = self.settings.get()["nda_version"]
            user = self.users.touch(ctx["user"]["id"], nda_version=v, nda_accepted_at=self._now())
            self.audit.log("nda", user, version=v)
            return _json(200, self._session_view(user))
        if p == ["session", "passcode"] and m == "POST":
            ctx = self._current(req, need_nda=False)
            b = self._body(req)
            self.users.set_passcode(ctx["user"]["id"], b.get("old"), b.get("new"))
            self.audit.log("user-change", ctx["user"], target=ctx["user"]["id"], change="own passcode")
            return _json(200, {"ok": True})

        ctx = self._current(req)
        if p[:1] == ["users"]:
            return self._users(ctx, req)
        if p == ["settings"]:
            self._need(ctx, "settings.edit")
            if m == "GET":
                return _json(200, self.settings.get())
            if m == "POST":
                b = self._body(req)
                out = self.settings.update(b)
                self.audit.log("settings", ctx["user"], changed=sorted(b))
                return _json(200, out)
        if p == ["audit"] and m == "GET":
            self._need(ctx, "audit.read")
            q = req["query"]
            return _json(200, self.audit.search(_q(q, "q"), _q(q, "action"), _q(q, "user"), _q(q, "outcome"),
                                                _q(q, "project"), _int(_q(q, "limit", "200")), _int(_q(q, "offset", "0"))))
        if p[:1] == ["templates"] and m == "GET":
            return self._templates(ctx, p[1:])
        if p[:1] == ["projects"]:
            return self._projects(ctx, req, p[1:])
        raise Problem(404, "not-found", "Nothing here.")

    def _now(self):
        from . import stamp
        return stamp(self.clock())

    def _status(self, req):
        s = self.settings.get()
        feats = {}
        for name, func in (("excel", ("xlsx", "write_workbook")), ("pdf", ("pdf", "build_pdf"))):
            try:
                X._writer(*func)
                feats[name] = True
            except Problem:
                feats[name] = False
        uid, state = self.sessions.find(req["token"], s["idle_minutes"]) if req["token"] else (None, "none")
        out = {"available": True, "signed_in": state == "ok", "bootstrap": self.users.empty(),
               "google": {"enabled": bool(s["google_client_id"]), "client_id": s["google_client_id"] or None},
               "features": feats, "idle_minutes": s["idle_minutes"]}
        landing = self._landing(s)
        if landing:
            out["landing"] = landing
        return out

    def _landing(self, settings):
        """The sign-in page's lines, shown before anyone signs in: the settings' own, else the branding of the one
        real project when there is exactly one. Only those six lines; never an id, a name or a figure."""
        if settings.get("landing"):
            try:
                return A.landing_lines(settings["landing"], strict=False)
            except Problem:
                return None
        try:
            real = [self.store.project(pid) for pid in self.store.project_ids()]
        except Problem:
            return None
        real = [pr for pr in real if not pr.get("sample")]
        if len(real) != 1:
            return None
        b = real[0].get("branding") if isinstance(real[0].get("branding"), dict) else {}
        lines = A.landing_lines({"title": b.get("title"), "subtitle": b.get("subtitle"),
                                 "place": b.get("location") or b.get("place"), "badge": b.get("badge"),
                                 "notice": b.get("notice"), "footer": b.get("footer")}, strict=False)
        return lines if any(lines.values()) else None

    # ---------------------------------------------------------------- signing in

    def _start(self, user, how):
        user = self.users.touch(user["id"], last_sign_in=self._now())
        token = self.sessions.start(user["id"])
        self.audit.log("sign-in", user, method=how)
        return _json(200, self._session_view(user), {"Set-Cookie": self._cookie(token)})

    def _bootstrap(self, data, how):
        user = self.users.save_user({**data, "role": "administrator", "status": "ACTIVE", "projects": ["*"]}, None)
        self.audit.log("user-add", user, target=user["id"], role="administrator", why="first sign-in (bootstrap)")
        try:
            S.install(self.store, user, replace=False)
            self.audit.log("sample", user, project=S.PROJECT_ID)
        except Problem:
            pass
        return self._start(user, how + " (first administrator)")

    def _sign_in(self, b):
        how = b.get("method")
        if how == "passcode":
            name, passcode = str(b.get("name") or "").strip(), str(b.get("passcode") or "")
            if not name or not passcode:
                raise Problem(400, "bad-request", "Enter your name and passcode.")
            if self.sessions.locked(name):
                self.audit.log("sign-in", {"name": name}, "denied", method="passcode", why="too many tries")
                raise Problem(429, "too-many-tries", "Too many wrong tries for that name. Wait 15 minutes.")
            if self.users.empty():
                return self._bootstrap({"name": name, "passcode": passcode}, "passcode")
            user = self.users.by_name(name)
            ok = bool(user and user.get("status") == "ACTIVE" and user.get("passcode")
                      and A.check_passcode(user["passcode"], passcode))
            if not ok:
                self.sessions.failed(name)
                why = "unknown name" if not user else "inactive" if user.get("status") != "ACTIVE" else "wrong passcode"
                self.audit.log("sign-in", user or {"name": name}, "denied", method="passcode", why=why)
                raise Problem(401, "sign-in-refused", "That name and passcode do not match an active user.")
            self.sessions.cleared(name)
            return self._start(user, "passcode")
        if how == "google":
            s = self.settings.get()
            try:
                email = A.google_email(b.get("id_token"), s["google_client_id"], self.clock(), self.tokeninfo)
            except Problem as e:
                self.audit.log("sign-in", None, "denied", method="google", why=e.code)
                raise
            if self.users.empty():
                return self._bootstrap({"name": email, "email": email}, "google")
            user = self.users.by_email(email)
            if not user or user.get("status") != "ACTIVE":
                self.audit.log("sign-in", user or {"name": email}, "denied", method="google",
                               why="not in the directory" if not user else "inactive", email=email)
                raise Problem(403, "not-authorized", f"The Google account {email} is not on the list of people allowed "
                                                     "into this workspace. Ask the administrator to add it.")
            return self._start(user, "google")
        raise Problem(400, "bad-request", "Sign in with {\"method\": \"passcode\"} or {\"method\": \"google\"}.")

    # ---------------------------------------------------------------- users

    def _users(self, ctx, req):
        self._need(ctx, "users.manage")
        m, p = req["method"], req["parts"]
        if p == ["users"] and m == "GET":
            return _json(200, {"users": [A.public(u) for u in self.users.users()]})
        if p == ["users"] and m == "POST":
            b = self._body(req)
            before = self.users.get(b.get("id")) if b.get("id") else None
            user = self.users.save_user(b, ctx["user"])
            changes = {k: b[k] for k in ("name", "email", "role", "status", "projects") if k in b}
            if "passcode" in b:
                changes["passcode"] = "set"
            self.audit.log("user-change" if before else "user-add", ctx["user"], target=user["id"], **changes)
            if before and (user["role"] != before["role"] or user["status"] != "ACTIVE" or "passcode" in b):
                self.sessions.end_user(user["id"])
            return _json(200, {"user": A.public(user)})
        if len(p) == 2 and m == "DELETE":
            old = self.users.remove(p[1])
            self.sessions.end_user(old["id"])
            self.audit.log("user-remove", ctx["user"], target=old["id"], name_removed=old.get("name"))
            return _json(200, {"removed": True})
        raise Problem(404, "not-found", "Nothing here.")

    # ---------------------------------------------------------------- templates

    def _templates(self, ctx, p):
        self._need(ctx, "templates")
        if p == []:
            from .schema import DICTIONARY_COLUMNS, dictionary_rows
            return _json(200, {"entities": list(ENTITIES), "columns": {e: I.columns(e) for e in ENTITIES},
                               "dictionary": {"columns": DICTIONARY_COLUMNS, "rows": dictionary_rows()},
                               "units": UNITS})
        if p == ["dictionary.csv"]:
            return _file(I.dictionary_csv(), "district-data-dictionary.csv", "text/csv; charset=utf-8")
        if p == ["workbook.xlsx"]:
            write = X._writer("xlsx", "write_workbook")
            return _file(write(I.template_sheets()), "district-templates.xlsx", XLSX)
        if len(p) == 1 and p[0].endswith(".csv") and p[0][:-4] in ENTITIES:
            return _file(I.template_csv(p[0][:-4]), f"template-{p[0]}", "text/csv; charset=utf-8")
        raise Problem(404, "not-found", "There is no template by that name.")

    # ---------------------------------------------------------------- projects

    def _projects(self, ctx, req, p):
        m, user = req["method"], ctx["user"]
        if p == [] and m == "GET":
            out = []
            for pid in self.store.project_ids():
                if A.assigned(user, pid):
                    pr = self.store.project(pid)
                    out.append({"id": pid, "name": pr.get("name"), "place": pr.get("place"), "sample": pr.get("sample"),
                                "branding": pr.get("branding"), "role": user["role"]})
            return _json(200, {"projects": out})
        if p == [] and m == "POST":
            self._need(ctx, "project.create")
            project = self.store.create_project(self._body(req), user)
            self.audit.log("project-create", user, project=project["id"])
            return _json(200, {"project": project})
        if p == ["sample"] and m == "POST":
            self._need(ctx, "sample.install")
            project = S.install(self.store, user, replace=True)
            self.audit.log("sample", user, project=project["id"])
            return _json(200, {"project": project})
        if p == ["import"] and m == "POST":
            self._need(ctx, "package.import")
            data = self._bytes(req)
            project, replaced, safety = self.store.import_package(data, user, _q(req["query"], "replace") in ("1", "true"))
            self.audit.log("package-import", user, project=project["id"], replaced=replaced,
                           safety_backup=(safety or {}).get("name"), size=len(data))
            return _json(200, {"project": project, "replaced": replaced, "safety_backup": safety})
        if not p:
            raise Problem(404, "not-found", "Nothing here.")
        project = self._project(ctx, p[0])
        return self._in_project(ctx, req, project, p[1:])

    def _in_project(self, ctx, req, project, p):
        m, user, q, pid = req["method"], ctx["user"], req["query"], project["id"]
        audience = A.audience_for(user, _q(q, "audience") or None)
        if p == [] and m == "GET":
            can = {a: A.can(user, a, project) for a in A.PERMISSIONS}
            shown = dict(project) if A.can(user, "project.edit", project) else \
                {k: v for k, v in project.items() if k != "settings"}
            return _json(200, {"project": A.scrub(shown, audience), "is_sample": bool(project.get("sample")),
                               "datasets": self._visible_datasets(ctx, pid), "audience": audience,
                               "modules": self._modules_for(ctx, project, audience), "can": can})
        if p == [] and m == "POST":
            self._need(ctx, "project.edit", project)
            b = self._body(req)
            out = self.store.update_project(pid, b, user)
            self.audit.log("project-edit", user, project=pid, changed=sorted(b))
            return _json(200, {"project": out})
        if p == ["package.zip"] and m == "GET":
            self._need(ctx, "package.export", project)
            data = self.store.export_package(pid, user)
            self.audit.log("package-export", user, project=pid, size=len(data))
            return _file(data, f"{pid}-{day(self.clock())}.zip", "application/zip")
        if p[:1] == ["backups"]:
            self._need(ctx, "backup.manage", project)
            if p == ["backups"] and m == "GET":
                return _json(200, {"backups": self.store.backups(pid)})
            if p == ["backups"] and m == "POST":
                made = self.store.backup_now(pid, "manual")
                self.audit.log("backup", user, project=pid, backup=made["name"], why="manual")
                return _json(200, {"backup": made})
            if len(p) == 3 and p[2] == "restore" and m == "POST":
                safety = self.store.restore(pid, p[1])
                self.audit.log("restore", user, project=pid, backup=p[1], safety_backup=safety["name"])
                return _json(200, {"restored": p[1], "safety_backup": safety})
        if p == ["modules"]:
            if m == "GET":
                return _json(200, {"modules": self._modules_for(ctx, project, audience), "audience": audience})
            if m == "POST":
                self._need(ctx, "modules.edit", project)
                b = self._body(req)
                mods = self.store.set_modules(pid, b.get("modules"), user, b.get("reason", ""))
                self.audit.log("modules", user, project=pid, modules=len(mods))
                return _json(200, {"modules": mods})
        if p[:1] == ["datasets"]:
            return self._datasets(ctx, req, project, p[1:], audience)
        if p == ["revisions"] and m == "GET":
            self._need(ctx, "revisions.read", project)
            return _json(200, self.store.revisions(pid, _q(q, "dataset") or None, _q(q, "entity") or None,
                                                   _q(q, "id") or None, _int(_q(q, "limit", "500"))))
        if p == ["compare"] and m == "GET":
            self._need(ctx, "compare", project)
            bm, bv, base = self._dataset(ctx, project, _q(q, "base") or "baseline", _q(q, "base_version") or "published")
            other_id = _q(q, "other")
            if not other_id:
                raise Problem(400, "bad-request", "Say which dataset to compare with the baseline (other=).")
            om, ov, other = self._dataset(ctx, project, other_id, _q(q, "other_version") or None)
            t = _q(q, "threshold")
            threshold = _float(t) if t else project.get("settings", {}).get("compare_threshold_pct", C.DEFAULT_THRESHOLD)
            out = C.compare(A.filter_content(base, audience), A.filter_content(other, audience), threshold)
            return _json(200, {"base": {"dataset": bm["id"], "version": bv}, "other": {"dataset": om["id"], "version": ov},
                               **out})
        if p[:1] == ["imports"]:
            return self._imports(ctx, req, project, p[1:])
        if p[:1] == ["documents"]:
            return self._documents(ctx, req, project, p[1:], audience)
        if p[:1] == ["gis"]:
            return self._gis(ctx, req, project, p[1:], audience)
        if p[:1] == ["notes"]:
            return self._notes(ctx, req, project, p[1:])
        if p[:1] == ["compute"] and len(p) == 2 and m in ("GET", "POST"):
            return self._compute(ctx, req, project, p[1])
        if p[:1] == ["export"] and m == "GET" and len(p) == 2:
            return self._export(ctx, req, project, p[1], audience)
        raise Problem(404, "not-found", "Nothing here.")

    # ---------------------------------------------------------------- datasets

    def _datasets(self, ctx, req, project, p, audience):
        m, user, q, pid = req["method"], ctx["user"], req["query"], project["id"]
        if p == [] and m == "GET":
            return _json(200, {"datasets": self._visible_datasets(ctx, pid)})
        if p == [] and m == "POST":
            b = self._body(req)
            kind = b.get("kind")
            self._need(ctx, "dataset.create_scenario" if kind == "scenario" else "dataset.create_submission", project)
            src = b.get("copy_from")
            if src:
                if not isinstance(src, dict):
                    raise Problem(400, "bad-request", "copy_from is {dataset, version}.")
                self._dataset(ctx, project, src.get("dataset") or "baseline", src.get("version") or "published")
            meta = self.store.create_dataset(pid, kind, b.get("label"), user, src)
            self.audit.log("dataset-create", user, project=pid, dataset=meta["id"], kind=kind)
            return _json(200, {"dataset": meta})
        if not p:
            raise Problem(404, "not-found", "Nothing here.")
        did = check_slug(p[0], "dataset id")
        rest = p[1:]
        if rest == [] and m == "GET":
            meta, v, content = self._dataset(ctx, project, did, _q(q, "version") or None)
            return _json(200, {"dataset": meta, "version": v, "audience": audience,
                               "as_of": self.store.as_of(pid, did, v),
                               "content": A.filter_content(content, audience)})
        if rest == ["versions"] and m == "GET":
            meta, _, _ = self._dataset(ctx, project, did, "published" if self.store.dataset(pid, did).get("current")
                                       else None)
            vis = A.versions_visible(user, meta)
            return _json(200, {"draft": {"updated_at": meta.get("draft_updated_at"),
                                         "updated_by": meta.get("draft_updated_by")} if vis == "all" else None,
                               "published": meta.get("published", []), "current": meta.get("current")})
        meta = self.store.dataset(pid, did)
        if rest == ["records"] and m == "POST":
            self._need(ctx, "dataset.edit", project, meta)
            b = self._body(req)
            entity = b.get("entity")
            if entity not in ENTITIES:
                raise Problem(400, "bad-request", f"Say which kind of record: {', '.join(ENTITIES)}.")
            record, errors = clean_record(entity, b.get("record"))
            if errors:
                raise Problem(400, "bad-request", "The record was not saved: " + "; ".join(errors[:10]))
            klass = b.get("classification")
            if klass is not None:
                from .schema import PROVENANCE
                if klass not in PROVENANCE:
                    raise Problem(400, "bad-request", "The classification is one of the 9 provenance classes.")
            rec, changes = self.store.put_record(pid, did, entity, record, user, b.get("reason", ""), klass)
            if changes:
                self.audit.log("edit", user, project=pid, dataset=did, entity=entity, id=rec["id"],
                               fields=[c["field"] for c in changes])
            return _json(200, {"record": rec, "changes": changes})
        if len(rest) == 3 and rest[0] == "records" and m == "DELETE":
            self._need(ctx, "dataset.edit", project, meta)
            if rest[1] not in ENTITIES:
                raise Problem(404, "not-found", "There is no such kind of record.")
            self.store.remove_record(pid, did, rest[1], check_id(rest[2], "record id"), user, _q(q, "reason"))
            self.audit.log("edit", user, project=pid, dataset=did, entity=rest[1], id=rest[2], removed=True)
            return _json(200, {"removed": True})
        if rest == ["publish"] and m == "POST":
            self._need(ctx, "dataset.publish", project, meta)
            n = self.store.publish(pid, did, user, self._body(req).get("note", ""))
            self.audit.log("publish", user, project=pid, dataset=did, version=n)
            return _json(200, {"version": n})
        if rest == ["rollback"] and m == "POST":
            self._need(ctx, "dataset.rollback", project, meta)
            b = self._body(req)
            n = self.store.rollback(pid, did, b.get("version"), user, b.get("reason", ""), bool(b.get("reset_draft")))
            self.audit.log("rollback", user, project=pid, dataset=did, version=n, from_version=b.get("version"),
                           reason=str(b.get("reason", ""))[:200])
            return _json(200, {"version": n, "from_version": b.get("version")})
        if len(rest) == 2 and rest[0] == "figures" and m == "GET":
            meta, v, content = self._dataset(ctx, project, did, _q(q, "version") or None)
            shown = A.filter_content(content, audience)
            aid = check_id(rest[1], "assumption id")
            entry = R.figure(shown, aid)
            mods = self._modules_for(ctx, project, audience)
            notes = [n for n in self.store.notes(pid, entity="assumptions", rid=aid)] \
                if A.can(user, "notes.read", project) else []
            return _json(200, {"found": entry is not None,
                               "figure": {**entry, "display": R.display(entry)} if entry else None,
                               "used_by": R.used_by(shown, mods, aid) if entry else [], "notes": notes,
                               "dataset": did, "version": v})
        if rest == ["checks"] and m == "GET":
            self._need(ctx, "checks", project)
            meta, v, content = self._dataset(ctx, project, did, _q(q, "version") or None)
            out = R.checks(content, self.store.modules(pid), A.untagged_sensitive(content))
            return _json(200, {"dataset": did, "version": v, **out})
        raise Problem(404, "not-found", "Nothing here.")

    # ---------------------------------------------------------------- imports

    def _imports(self, ctx, req, project, p):
        m, user, q, pid = req["method"], ctx["user"], req["query"], project["id"]
        self._need(ctx, "import", project)
        if p == [] and m == "POST":
            data = self._bytes(req)
            entity = _q(q, "entity") or None
            report, clean = I.preview(_q(q, "name") or "upload", data, entity)
            iid = self.store.save_preview(pid, {"by": user["id"], "file": report["file"], "rows": clean})
            self.audit.log("import-preview", user, project=pid, file=report["file"], rows_ok=report["rows_ok"],
                           rows_rejected=report["rows_rejected"])
            return _json(200, {"import_id": iid, **report})
        if len(p) == 2 and p[1] == "commit" and m == "POST":
            box = self.store.load_preview(pid, p[0])
            if box.get("by") != user["id"] and user["role"] != "administrator":
                self._deny(ctx, project)
            b = self._body(req)
            target = str(b.get("target") or ("consultant" if user["role"] == "consultant" else "baseline"))
            rows = {e: r for e, r in (box.get("rows") or {}).items() if e in ENTITIES and r}
            if not rows:
                raise Problem(400, "bad-request", "No row in that file passed the checks, so there is nothing to import.")
            if target == "consultant":
                self._need(ctx, "dataset.create_submission", project)
                meta = self.store.create_dataset(pid, "consultant", b.get("label") or f"Consultant submission: {box['file']}",
                                                 user, {"dataset": "baseline", "version": "published"}
                                                 if self.store.dataset(pid, "baseline").get("current") else None)
                self.audit.log("dataset-create", user, project=pid, dataset=meta["id"], kind="consultant")
            else:
                meta = self.store.dataset(pid, check_slug(target, "dataset id"))
                self._need(ctx, "dataset.edit", project, meta)
            counts = self.store.put_records(pid, meta["id"], rows, user, b.get("mode") or "merge",
                                            b.get("reason") or f"import of {box['file']}")
            self.store.drop_preview(pid, p[0])
            self.audit.log("import", user, project=pid, dataset=meta["id"], file=box["file"], rows=counts)
            return _json(200, {"dataset": self.store.dataset(pid, meta["id"]), "imported": counts})
        raise Problem(404, "not-found", "Nothing here.")

    # ---------------------------------------------------------------- documents

    @staticmethod
    def _sees(user, audience, item):
        if audience == "internal":
            return True
        return audience in (item.get("audiences") or []) or item.get("created_by") == user["id"] \
            or item.get("uploaded_by") == user["id"]

    def _documents(self, ctx, req, project, p, audience):
        m, user, q, pid = req["method"], ctx["user"], req["query"], project["id"]
        if p == [] and m == "GET":
            self._need(ctx, "documents.read", project)
            return _json(200, {"documents": [d for d in self.store.documents(pid) if self._sees(user, audience, d)]})
        if p == [] and m == "POST":
            self._need(ctx, "documents.upload", project)
            data = self._bytes(req)
            doc_id = _q(q, "document") or None
            if doc_id:
                old = next((d for d in self.store.documents(pid) if d["id"] == doc_id), None)
                if old is None or not self._sees(user, audience, old):
                    raise Problem(404, "not-found", "There is no such document to add a version to.")
            auds = ["internal", "consultant"] if user["role"] == "consultant" else ["internal"]
            doc = self.store.add_document(pid, _q(q, "name"), data, user, _q(q, "title"), _q(q, "task"), doc_id,
                                          _q(q, "note"), auds)
            self.audit.log("upload-document", user, project=pid, document=doc["id"], version=len(doc["versions"]),
                           size=len(data))
            return _json(200, {"document": doc})
        if len(p) == 2 and p[1] == "share" and m == "POST":
            self._need(ctx, "documents.share", project)
            doc = self.store.share_document(pid, p[0], self._body(req).get("audiences"))
            self.audit.log("share-document", user, project=pid, document=p[0], audiences=doc["audiences"])
            return _json(200, {"document": doc})
        if len(p) == 2 and m == "GET":
            self._need(ctx, "documents.read", project)
            doc, v, data = self.store.document_file(pid, p[0], p[1])
            if not self._sees(user, audience, doc):
                self._deny(ctx, project)
            self.audit.log("download-document", user, project=pid, document=doc["id"], version=v["version"])
            from .store import DOCUMENT_TYPES
            ext = "." + doc["kind"]
            return _file(data, v["filename"], DOCUMENT_TYPES.get(ext, "application/octet-stream"))
        raise Problem(404, "not-found", "Nothing here.")

    # ---------------------------------------------------------------- GIS

    def _gis(self, ctx, req, project, p, audience):
        m, user, q, pid = req["method"], ctx["user"], req["query"], project["id"]
        if p == [] and m == "GET":
            self._need(ctx, "gis.read", project)
            return _json(200, {"layers": [x for x in self.store.layers(pid) if self._sees(user, audience, x)]})
        if p == [] and m == "POST":
            self._need(ctx, "gis.upload", project)
            data = self._bytes(req)
            info, fc = G.read_layer(_q(q, "name"), data)
            kind = _q(q, "kind") or "other"
            if kind not in ("trade_area", "competitors", "parcels", "other"):
                raise Problem(400, "bad-request", "A layer's kind is trade_area, competitors, parcels or other.")
            layer = self.store.add_layer(pid, fc, {"label": _q(q, "label") or _q(q, "name") or "Layer", "kind": kind,
                                                   "source_name": _q(q, "name"), **info,
                                                   "audiences": ["internal", "consultant"]}, user)
            self.audit.log("upload-gis", user, project=pid, layer=layer["id"], features=info["features"])
            return _json(200, {"layer": layer, "warnings": info["warnings"]})
        if len(p) == 2 and p[1] == "share" and m == "POST":
            self._need(ctx, "documents.share", project)
            auds = self._body(req).get("audiences")
            if not isinstance(auds, list) or any(a not in AUDIENCES for a in auds):
                raise Problem(400, "bad-request", f"Audiences are some of: {', '.join(AUDIENCES)}.")
            layer = self.store.share_layer(pid, p[0], auds)
            self.audit.log("share-gis", user, project=pid, layer=layer["id"], audiences=layer["audiences"])
            return _json(200, {"layer": layer})
        if len(p) == 1 and m == "GET":
            self._need(ctx, "gis.read", project)
            meta, fc = self.store.layer(pid, p[0])
            if not self._sees(user, audience, meta):
                self._deny(ctx, project)
            return _json(200, A.scrub(fc, audience))
        if len(p) == 1 and m == "DELETE":
            self._need(ctx, "gis.remove", project)
            self.store.remove_layer(pid, p[0], user)
            self.audit.log("remove-gis", user, project=pid, layer=p[0])
            return _json(200, {"removed": True})
        raise Problem(404, "not-found", "Nothing here.")

    # ---------------------------------------------------------------- notes

    def _notes(self, ctx, req, project, p):
        m, user, q, pid = req["method"], ctx["user"], req["query"], project["id"]
        if p == [] and m == "GET":
            self._need(ctx, "notes.read", project)
            return _json(200, {"notes": self.store.notes(pid, _q(q, "status") or None, _q(q, "entity") or None,
                                                         _q(q, "id") or None)})
        if p == [] and m == "POST":
            self._need(ctx, "notes.write", project)
            b = self._body(req)
            note = self.store.add_note(pid, b.get("target"), b.get("text"), user)
            self.audit.log("note", user, project=pid, note=note["id"], target=note["target"])
            return _json(200, {"note": note})
        if len(p) == 2 and p[1] == "replies" and m == "POST":
            self._need(ctx, "notes.write", project)
            note = self.store.reply_note(pid, p[0], self._body(req).get("text"), user)
            self.audit.log("note", user, project=pid, note=p[0], reply=True)
            return _json(200, {"note": note})
        if len(p) == 2 and p[1] == "resolve" and m == "POST":
            self._need(ctx, "notes.resolve", project)
            b = self._body(req)
            note = self.store.resolve_note(pid, p[0], b.get("status", "resolved"), b.get("resolution", ""), user)
            self.audit.log("note", user, project=pid, note=p[0], status=note["status"])
            return _json(200, {"note": note})
        raise Problem(404, "not-found", "Nothing here.")

    # ---------------------------------------------------------------- computed results

    def _compute(self, ctx, req, project, tool):
        """A tool of the finance engine on one dataset version; POST carries what-if changes that are not saved."""
        from . import compute as K
        user, q, pid = ctx["user"], req["query"], project["id"]
        self._need(ctx, "compute", project)
        b = self._body(req) if req["method"] == "POST" else {}
        if tool not in K.TOOLS:
            raise Problem(404, "not-found", f"There is no compute tool by that name. The tools are: {', '.join(K.TOOLS)}.")
        audience = A.audience_for(user, _q(q, "audience") or b.get("audience") or None)
        did = _q(q, "dataset") or str(b.get("dataset") or "") or "baseline"
        meta, v, content = self._dataset(ctx, project, did, _q(q, "version") or str(b.get("version") or "") or None)
        deny = AUDIENCE_DENY.get(audience, AUDIENCE_DENY["city"])
        visible = A.filter_content(content, audience) if deny else None
        changed = []
        if b.get("assumptions") or b.get("records"):
            content, changed = K.apply_overrides(content, b, visible, deny)
        options = b.get("options")
        if options is None:
            options = {k: _q(q, k) for k in K.OPTIONS.get(tool, {}) if _q(q, k)}
        answer = K.run(tool, content, options,
                       reconcile_content=A.filter_content(content, audience) if deny else content)
        answer = A.scrub(K.filter_answer(answer, audience), audience)
        self.audit.log("compute", user, project=pid, tool=tool, dataset=did, version=v, audience=audience,
                       what_if=changed[:50])
        return _json(200, {**answer, "dataset": did, "version": v, "audience": audience,
                           "as_of": self.store.as_of(pid, did, v), "what_if": changed})

    # ---------------------------------------------------------------- exports

    def _export(self, ctx, req, project, what, audience):
        user, q, pid = ctx["user"], req["query"], project["id"]
        self._need(ctx, "export", project)
        did = _q(q, "dataset") or "baseline"
        meta, v, content = self._dataset(ctx, project, did, _q(q, "version") or None)
        shown = A.filter_content(content, audience)
        as_of = self.store.as_of(pid, did, v)
        disclaimer = self.settings.get()["disclaimers"].get(audience, "")
        if what == "table.xlsx":
            entity = _q(q, "entity") or "all"
            data, name = X.table_xlsx(project, shown, entity, audience, as_of, disclaimer)
            self.audit.log("export", user, project=pid, kind="xlsx", what=entity, dataset=did, version=v,
                           audience=audience)
            return _file(data, name, XLSX)
        if what == "module.pdf":
            module = _q(q, "module")
            mods = self._modules_for(ctx, project, audience)
            data, name = X.module_pdf(project, mods, shown, module, audience, as_of, disclaimer)
            self.audit.log("export", user, project=pid, kind="pdf", what=module, dataset=did, version=v,
                           audience=audience)
            return _file(data, name, "application/pdf")
        raise Problem(404, "not-found", "Exports are table.xlsx and module.pdf.")


def _int(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return 0


def _float(text):
    try:
        v = float(text)
    except (TypeError, ValueError):
        raise Problem(400, "bad-request", "The threshold is a percent.") from None
    if not 0 <= v <= 1000:
        raise Problem(400, "bad-request", "The threshold is a percent from 0 to 1000.")
    return v
