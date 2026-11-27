"""Who may sign in, what each role may do, and what each audience may see. Enforced on the server: a screen that
hides a button is a convenience, the check here is the rule (FR-04).

- The user directory is data/district-users.json; passcodes are PBKDF2-SHA256 with a salt per user.
- Sessions are kept in memory (a restart signs everyone out) behind an HttpOnly, SameSite=Strict cookie.
- PERMISSIONS is the one table of what each role may do; filter_content and scrub remove what an audience may not
  receive, driven by the tags in schema.py.
"""
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import Problem, SLUG, stamp
from .jsonsafe import dumps
from .schema import (AUDIENCE_DENY, AUDIENCES, ENTITIES, SENSITIVE_KEY_PHRASES, SENSITIVE_KEY_WORDS,
                     SENSITIVE_WORDS, field_tags)

ROLES = ("administrator", "analyst", "consultant", "viewer_partner", "viewer_city")
ROLE_AUDIENCE = {"administrator": "internal", "analyst": "internal", "consultant": "consultant",
                 "viewer_partner": "partner", "viewer_city": "city"}
ALL, ADMIN = frozenset(ROLES), frozenset({"administrator"})
INTERNAL = frozenset({"administrator", "analyst"})
WORKERS = frozenset({"administrator", "analyst", "consultant"})

PERMISSIONS = {
    "project.view": ALL,
    "project.create": ADMIN, "project.edit": ADMIN, "modules.edit": ADMIN, "settings.edit": ADMIN,
    "users.manage": ADMIN, "audit.read": ADMIN, "dataset.publish": ADMIN, "dataset.rollback": ADMIN,
    "backup.manage": ADMIN, "package.export": ADMIN, "package.import": ADMIN, "documents.share": ADMIN,
    "sample.install": ADMIN,
    "dataset.read_draft": WORKERS, "dataset.edit": WORKERS,          # a consultant only on their own submissions
    "dataset.create_scenario": INTERNAL,
    "dataset.create_submission": WORKERS, "import": WORKERS, "compare": WORKERS, "checks": WORKERS,
    "templates": WORKERS,
    "revisions.read": INTERNAL, "notes.resolve": INTERNAL, "gis.remove": INTERNAL,
    "notes.read": WORKERS, "notes.write": WORKERS, "documents.upload": WORKERS, "gis.upload": WORKERS,
    "documents.read": ALL, "gis.read": ALL,
    "export": ALL,                                                   # viewers only when the project allows it
}
EXPORT_SETTING = {"viewer_partner": "partner_export", "viewer_city": "city_export"}

ITERATIONS = 240_000
MIN_PASSCODE = 8
MAX_TRIES, TRY_WINDOW = 5, 15 * 60
DEFAULT_SETTINGS = {
    "google_client_id": "",
    "idle_minutes": 30,
    "nda_version": 1,
    "nda_text": "Confidentiality agreement (NDA): wording to be supplied by counsel.",
    "disclaimers": {
        "internal": "Internal working figures. Not for distribution.",
        "consultant": "Shared with the consultant for the assigned scope of work.",
        "partner": "Reg D disclaimer: wording to be supplied by counsel",
        "city": "City-facing view: returns, residual land value by parcel and disposition pricing are not included.",
    },
}
_EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}")


def _write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + ".tmp")
    scratch.write_text(dumps(obj, indent=1), encoding="utf-8")
    os.replace(scratch, path)


def _read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return copy.deepcopy(default)
    except (OSError, ValueError):
        raise Problem(500, "unreadable", f"{Path(path).name} could not be read. Nobody can sign in until it is "
                                         "mended or restored from a copy.") from None


# ---------------------------------------------------------------- passcodes

def hash_passcode(passcode, salt=None, iterations=None):
    salt = salt or secrets.token_hex(16)
    n = iterations or ITERATIONS
    digest = hashlib.pbkdf2_hmac("sha256", str(passcode).encode("utf-8"), bytes.fromhex(salt), n).hex()
    return f"pbkdf2_sha256${n}${salt}${digest}"


def check_passcode(stored, passcode):
    try:
        kind, n, salt, digest = str(stored).split("$")
        if kind != "pbkdf2_sha256":
            return False
        again = hashlib.pbkdf2_hmac("sha256", str(passcode).encode("utf-8"), bytes.fromhex(salt), int(n)).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(again, digest)


# ---------------------------------------------------------------- settings

class Settings:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "district-settings.json"
        self._guard = threading.Lock()

    def get(self):
        found = _read(self.path, {})
        out = copy.deepcopy(DEFAULT_SETTINGS)
        if isinstance(found, dict):
            for k, v in found.items():
                if k == "disclaimers" and isinstance(v, dict):
                    out["disclaimers"].update({a: str(t) for a, t in v.items() if a in AUDIENCES})
                elif k in out:
                    out[k] = v
        try:
            out["idle_minutes"] = max(1, min(int(out["idle_minutes"]), 24 * 60))
        except (TypeError, ValueError):
            out["idle_minutes"] = 30
        out["google_client_id"] = str(out.get("google_client_id") or "").strip()
        return out

    def update(self, changes):
        if not isinstance(changes, dict):
            raise Problem(400, "bad-request", "Settings are a set of named values.")
        with self._guard:
            current = self.get()
            if "google_client_id" in changes:
                cid = str(changes["google_client_id"] or "").strip()
                if cid and not re.fullmatch(r"[0-9A-Za-z\-_.]{8,200}\.apps\.googleusercontent\.com", cid):
                    raise Problem(400, "bad-request", "That is not a Google OAuth client id (it ends in "
                                                      ".apps.googleusercontent.com).")
                current["google_client_id"] = cid
            if "idle_minutes" in changes:
                try:
                    m = int(changes["idle_minutes"])
                except (TypeError, ValueError):
                    m = 0
                if not 1 <= m <= 24 * 60:
                    raise Problem(400, "bad-request", "The idle time-out is from 1 to 1,440 minutes.")
                current["idle_minutes"] = m
            if "nda_text" in changes:
                current["nda_text"] = str(changes["nda_text"] or "")[:20000] or DEFAULT_SETTINGS["nda_text"]
            if "nda_version" in changes:
                try:
                    current["nda_version"] = max(1, int(changes["nda_version"]))
                except (TypeError, ValueError):
                    raise Problem(400, "bad-request", "The NDA version is a whole number.") from None
            if "disclaimers" in changes:
                d = changes["disclaimers"]
                if not isinstance(d, dict) or any(k not in AUDIENCES for k in d):
                    raise Problem(400, "bad-request", f"Disclaimers are given per audience: {', '.join(AUDIENCES)}.")
                current["disclaimers"].update({k: str(v or "")[:4000] for k, v in d.items()})
            _write(self.path, current)
            return current


# ---------------------------------------------------------------- the user directory

def public(user):
    return {k: user.get(k) for k in ("id", "name", "email", "role", "status", "projects", "created_at", "created_by",
                                     "updated_at", "nda_version", "nda_accepted_at", "last_sign_in")} | \
        {"has_passcode": bool(user.get("passcode"))}


class Directory:
    def __init__(self, data_dir, clock):
        self.path = Path(data_dir) / "district-users.json"
        self.clock = clock
        self._guard = threading.RLock()

    def users(self):
        box = _read(self.path, {"version": 1, "users": []})
        rows = box.get("users") if isinstance(box, dict) else None
        return [u for u in rows or [] if isinstance(u, dict) and u.get("id")]

    def _save(self, users):
        _write(self.path, {"version": 1, "users": users})

    def empty(self):
        return not self.users()

    def get(self, uid):
        return next((u for u in self.users() if u["id"] == uid), None)

    def by_name(self, name):
        key = str(name or "").strip().lower()
        return next((u for u in self.users() if str(u.get("name", "")).strip().lower() == key), None)

    def by_email(self, email):
        key = str(email or "").strip().lower()
        return next((u for u in self.users() if key and str(u.get("email") or "").lower() == key), None)

    @staticmethod
    def _active_admins(users):
        return [u for u in users if u.get("role") == "administrator" and u.get("status") == "ACTIVE"]

    def save_user(self, data, actor):
        """Add (no id) or change a user. Refuses anything that would leave no active administrator."""
        if not isinstance(data, dict):
            raise Problem(400, "bad-request", "Send the user as a set of named values.")
        with self._guard:
            users = self.users()
            old = next((u for u in users if u["id"] == data.get("id")), None) if data.get("id") else None
            if data.get("id") and old is None:
                raise Problem(404, "not-found", "There is no such user.")
            user = copy.deepcopy(old) if old else {
                "id": "u-" + secrets.token_hex(4), "created_at": stamp(self.clock()),
                "created_by": (actor or {}).get("id"), "status": "ACTIVE", "projects": [], "passcode": None,
                "nda_version": None, "nda_accepted_at": None, "last_sign_in": None}
            if "name" in data or not old:
                name = str(data.get("name") or "").strip()
                if not 1 <= len(name) <= 80:
                    raise Problem(400, "bad-request", "A user needs a name (up to 80 characters).")
                clash = self.by_name(name)
                if clash and clash["id"] != user["id"]:
                    raise Problem(409, "conflict", f"There is already a user called “{name}”.")
                user["name"] = name
            if "email" in data:
                email = str(data.get("email") or "").strip().lower()
                if email and not _EMAIL.fullmatch(email):
                    raise Problem(400, "bad-request", f"“{email[:60]}” is not an e-mail address.")
                clash = self.by_email(email)
                if clash and clash["id"] != user["id"]:
                    raise Problem(409, "conflict", "Another user already has that e-mail address.")
                user["email"] = email or None
            if "role" in data or not old:
                if data.get("role") not in ROLES:
                    raise Problem(400, "bad-request", f"A role is one of: {', '.join(ROLES)}.")
                user["role"] = data["role"]
            if "status" in data:
                if data["status"] not in ("ACTIVE", "INACTIVE"):
                    raise Problem(400, "bad-request", "A user's status is ACTIVE or INACTIVE.")
                user["status"] = data["status"]
            if "projects" in data:
                p = data.get("projects") or []
                if not isinstance(p, list) or any(x != "*" and not SLUG.fullmatch(str(x)) for x in p):
                    raise Problem(400, "bad-request", "Projects are a list of project ids (or \"*\" for all).")
                user["projects"] = sorted(set(str(x) for x in p))
            if data.get("passcode"):
                user["passcode"] = self._new_passcode(data["passcode"])
            user["updated_at"] = stamp(self.clock())
            others = [u for u in users if u["id"] != user["id"]]
            if old and self._active_admins([old]) and not self._active_admins(others + [user]):
                raise Problem(409, "last-admin", "This is the last active administrator. Make another user an active "
                                                 "administrator first.")
            self._save(others + [user] if not old else [user if u["id"] == user["id"] else u for u in users])
            return user

    @staticmethod
    def _new_passcode(passcode):
        if len(str(passcode)) < MIN_PASSCODE:
            raise Problem(400, "bad-request", f"A passcode needs at least {MIN_PASSCODE} characters.")
        if len(str(passcode)) > 200:
            raise Problem(400, "bad-request", "That passcode is too long.")
        return hash_passcode(passcode)

    def remove(self, uid):
        with self._guard:
            users = self.users()
            old = next((u for u in users if u["id"] == uid), None)
            if old is None:
                raise Problem(404, "not-found", "There is no such user.")
            others = [u for u in users if u["id"] != uid]
            if self._active_admins([old]) and not self._active_admins(others):
                raise Problem(409, "last-admin", "This is the last active administrator and cannot be removed.")
            self._save(others)
            return old

    def touch(self, uid, **fields):
        with self._guard:
            users = self.users()
            for u in users:
                if u["id"] == uid:
                    u.update(fields)
            self._save(users)
            return self.get(uid)

    def set_passcode(self, uid, old, new):
        user = self.get(uid)
        if not user or (user.get("passcode") and not check_passcode(user["passcode"], old)):
            raise Problem(403, "forbidden", "The current passcode is not right.")
        return self.touch(uid, passcode=self._new_passcode(new))


# ---------------------------------------------------------------- Google

TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"


def fetch_tokeninfo(id_token):
    """Google's own check of an ID token (server side). Returns its claims, or raises Problem."""
    url = TOKENINFO + "?" + urllib.parse.urlencode({"id_token": id_token})
    try:
        with urllib.request.urlopen(url, timeout=10) as r:  # noqa: S310 - Google's fixed https address
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500:
            raise Problem(401, "sign-in-refused", "Google did not accept that sign-in. Try again.") from None
        raise Problem(502, "google-unreachable", "Google's sign-in check did not answer just now. Try again.") from None
    except (urllib.error.URLError, OSError, ValueError):
        raise Problem(502, "google-unreachable", "Google's sign-in check did not answer just now. Check the "
                                                 "internet connection and try again.") from None


def google_email(id_token, client_id, now, fetch=fetch_tokeninfo):
    """The verified e-mail address in a Google ID token meant for this app, or a Problem saying why not."""
    if not client_id:
        raise Problem(501, "google-not-set-up", "Google sign-in is not set up: the owner must create a Google OAuth "
                                                "client id and enter it in the settings.")
    token = str(id_token or "")
    if not 20 <= len(token) <= 8000 or token.count(".") != 2:
        raise Problem(400, "bad-request", "That is not a Google sign-in token.")
    claims = fetch(token)
    if not isinstance(claims, dict):
        raise Problem(401, "sign-in-refused", "Google did not accept that sign-in.")
    if claims.get("aud") != client_id:
        raise Problem(401, "sign-in-refused", "That Google sign-in was made for another app.")
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise Problem(401, "sign-in-refused", "That sign-in token was not issued by Google.")
    try:
        if int(claims.get("exp", 0)) < now:
            raise Problem(401, "sign-in-refused", "That Google sign-in has expired. Sign in again.")
    except (TypeError, ValueError):
        raise Problem(401, "sign-in-refused", "That Google sign-in has no expiry time.") from None
    if claims.get("email_verified") not in (True, "true"):
        raise Problem(401, "sign-in-refused", "Google has not verified that account's e-mail address.")
    email = str(claims.get("email") or "").strip().lower()
    if not _EMAIL.fullmatch(email):
        raise Problem(401, "sign-in-refused", "That Google sign-in has no e-mail address.")
    return email


# ---------------------------------------------------------------- sessions and tries

class Sessions:
    def __init__(self, clock):
        self.clock = clock
        self._live = {}
        self._tries = {}
        self._guard = threading.Lock()

    @staticmethod
    def _key(token):
        return hashlib.sha256(str(token).encode("utf-8")).hexdigest()

    def start(self, uid):
        token = secrets.token_urlsafe(32)
        with self._guard:
            self._live[self._key(token)] = {"user": uid, "started": self.clock(), "last": self.clock()}
        return token

    def find(self, token, idle_minutes):
        """(user id, state) where state is 'ok', 'expired' or 'none'. A found session's clock is reset."""
        if not token:
            return None, "none"
        key = self._key(token)
        with self._guard:
            s = self._live.get(key)
            if not s:
                return None, "none"
            if self.clock() - s["last"] > idle_minutes * 60:
                del self._live[key]
                return s["user"], "expired"
            s["last"] = self.clock()
            return s["user"], "ok"

    def end(self, token):
        with self._guard:
            return self._live.pop(self._key(token), None) is not None

    def end_user(self, uid):
        with self._guard:
            for k in [k for k, s in self._live.items() if s["user"] == uid]:
                del self._live[k]

    def locked(self, name):
        key = str(name or "").strip().lower()
        with self._guard:
            recent = [t for t in self._tries.get(key, []) if self.clock() - t < TRY_WINDOW]
            self._tries[key] = recent
            return len(recent) >= MAX_TRIES

    def failed(self, name):
        key = str(name or "").strip().lower()
        with self._guard:
            self._tries.setdefault(key, []).append(self.clock())

    def cleared(self, name):
        with self._guard:
            self._tries.pop(str(name or "").strip().lower(), None)


# ---------------------------------------------------------------- permissions

def assigned(user, pid):
    if user["role"] in INTERNAL:
        return True
    return "*" in (user.get("projects") or []) or pid in (user.get("projects") or [])


def can(user, action, project=None, dataset=None):
    """True when the user may do this, on this project and dataset."""
    if not user or user.get("status") != "ACTIVE":
        return False
    role = user.get("role")
    if role not in PERMISSIONS.get(action, ()):
        return False
    if project is not None and not assigned(user, project["id"]):
        return False
    if action == "export" and role in EXPORT_SETTING:
        if not (project or {}).get("settings", {}).get(EXPORT_SETTING[role]):
            return False
    if role == "consultant" and action in ("dataset.read_draft", "dataset.edit") and dataset is not None:
        return dataset.get("kind") == "consultant" and dataset.get("owner") == user["id"]
    return True


def versions_visible(user, dataset):
    """'all' (drafts and versions), 'published' or None, for one dataset."""
    role = user.get("role")
    if role in INTERNAL:
        return "all"
    if role == "consultant":
        if dataset.get("kind") == "consultant" and dataset.get("owner") == user["id"]:
            return "all"
        return "published" if dataset.get("kind") == "baseline" and dataset.get("current") else None
    if not dataset.get("current"):
        return None
    if role == "viewer_city":
        return "published" if dataset.get("kind") == "baseline" else None
    return "published"


def audience_for(user, asked=None):
    """The audience a user's answers are filtered for. Internal users may ask to see another audience's view."""
    own = ROLE_AUDIENCE.get(user.get("role"), "city")
    if asked in (None, "", own):
        return own
    if asked not in AUDIENCES:
        raise Problem(400, "bad-request", f"An audience is one of: {', '.join(AUDIENCES)}.")
    if own != "internal":
        raise Problem(403, "forbidden", "Your view cannot be widened or changed.")
    return asked


# ---------------------------------------------------------------- filtering by audience

_WORDS = [(re.compile(p, re.I), tag) for p, tag in SENSITIVE_WORDS.items()]
_TEXT_FIELDS = ("id", "label", "heading", "metric", "title", "name", "body", "question", "answer", "description",
                "item", "text")


def word_tags(*texts):
    found = set()
    for t in texts:
        if t:
            for rx, tag in _WORDS:
                if rx.search(str(t)):
                    found.add(tag)
    return found


def key_tags(key):
    k = re.sub(r"([a-z])([A-Z])", r"\1_\2", str(key)).lower()
    tokens = set(re.split(r"[^a-z0-9]+|_", k))
    found = {tag for word, tag in SENSITIVE_KEY_WORDS.items() if word in tokens}
    found |= {tag for phrase, tag in SENSITIVE_KEY_PHRASES.items() if phrase in k}
    return found


def _record_denied(record, deny):
    if not deny:
        return False
    if set(record.get("tags") or []) & deny:
        return True
    if record.get("city_safe"):
        return False
    return bool(word_tags(*(record.get(f) for f in _TEXT_FIELDS)) & deny)


def scrub(obj, audience):
    """A copy of any JSON value without the keys an audience may not receive (free-form objects, computed results)."""
    deny = AUDIENCE_DENY.get(audience, AUDIENCE_DENY["city"])
    if not deny:
        return copy.deepcopy(obj)

    def walk(x):
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items() if not (key_tags(k) & deny)}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x
    return walk(obj)


def filter_content(content, audience):
    """What an audience may receive of a dataset's content (section 5 of the contract)."""
    deny = AUDIENCE_DENY.get(audience, AUDIENCE_DENY["city"])
    if not deny:
        return copy.deepcopy(content)
    ents = content["entities"]
    removed = {a.get("id") for a in ents.get("assumptions", []) if _record_denied(a, deny)}
    out = {}
    for name in ENTITIES:
        keep = []
        for r in ents.get(name, []):
            if _record_denied(r, deny) or r.get("assumption") in removed:
                continue
            if name == "reconciliations" and ({r.get("total")} | set(r.get("parts") or [])) & removed:
                continue
            if set(r.get("cites") or []) & removed:
                continue
            rec = {k: v for k, v in r.items() if not (field_tags(name, k) & deny)}
            if name == "sections":
                rec = _filter_section(rec, deny, removed)
            keep.append(rec)
        out[name] = keep
    return scrub({**content, "entities": out}, audience)


def _filter_section(s, deny, removed):
    if isinstance(s.get("items"), list):
        s["items"] = [i for i in s["items"] if isinstance(i, dict) and not _record_denied(i, deny)
                      and not (set(i.get("cites") or []) & removed)]
    cols = s.get("columns")
    if isinstance(cols, list):
        tags = s.get("column_tags") if isinstance(s.get("column_tags"), list) else []
        drop = {i for i, c in enumerate(cols)
                if (i < len(tags) and isinstance(tags[i], list) and set(tags[i]) & deny)
                or (word_tags(c) & deny and not s.get("city_safe"))}
        if drop:
            s["columns"] = [c for i, c in enumerate(cols) if i not in drop]
            if isinstance(s.get("rows"), list):
                s["rows"] = [[c for i, c in enumerate(row) if i not in drop] if isinstance(row, list) else row
                             for row in s["rows"]]
            if tags:
                s["column_tags"] = [t for i, t in enumerate(tags) if i not in drop]
    return s


def filter_modules(modules, audience, content=None):
    """The modules and cards an audience may see; a card whose assumption was filtered out goes with it."""
    deny = AUDIENCE_DENY.get(audience, AUDIENCE_DENY["city"])
    known = None if content is None else {a.get("id") for a in content["entities"]["assumptions"]}
    out = []
    for m in modules:
        if m.get("audiences") and audience not in m["audiences"]:
            continue
        if _record_denied(m, deny):
            continue
        mod = copy.deepcopy(m)
        cards = []
        for c in mod.get("cards") or []:
            if _record_denied(c, deny):
                continue
            ids = [c.get("assumption")] if c.get("assumption") else list(c.get("assumptions") or [])
            if deny and known is not None and any(i not in known for i in ids if i):
                continue
            cards.append(c)
        mod["cards"] = cards
        tables = []
        for t in mod.get("tables") or []:
            if not isinstance(t, dict) or t.get("entity") not in ENTITIES:
                continue
            t = dict(t)
            if isinstance(t.get("columns"), list):
                t["columns"] = [c for c in t["columns"] if not (field_tags(t["entity"], c) & deny)]
            tables.append(t)
        mod["tables"] = tables
        out.append(scrub(mod, audience))
    return out


def untagged_sensitive(content):
    """Records whose words sound sensitive but carry no tag: hidden from the city by the words alone."""
    out = []
    for name in ENTITIES:
        for r in content["entities"].get(name, []):
            hit = word_tags(*(r.get(f) for f in _TEXT_FIELDS))
            if hit and not (set(r.get("tags") or []) & hit) and not r.get("city_safe"):
                out.append({"entity": name, "id": r.get("id"), "sounds_like": sorted(hit)})
    return out
