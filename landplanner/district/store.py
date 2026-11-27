"""The district project store: data/projects/<project_id>/ (see docs/district-data-contract.md, section 1).

Datasets have one draft and published versions that never change; every change to a draft is written to the
project's revision log. Notes, the document library, GIS layers, daily backups and the whole-project zip live here
too. Everything is plain JSON files written atomically, so the folder can be copied, backed up and read by eye.
"""
import copy
import hashlib
import io
import json
import os
import re
import shutil
import threading
import time
import zipfile
from pathlib import Path, PureWindowsPath

from . import SLUG, Problem, check_id, check_slug, chain, day, slug, stamp
from .jsonsafe import dumps
from .schema import ENTITIES

FORMAT = 1
PACKAGE_FORMAT = "landplanner-district-project"
KEEP_BACKUPS = 14
DOCUMENT_TYPES = {
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".csv": "text/csv; charset=utf-8",
}
MAX_ZIP_FILES = 20000
MAX_ZIP_BYTES = 2 * 1024 ** 3
PREVIEW_HOURS = 24
_WRITE = threading.RLock()


def empty_content():
    return {"format": FORMAT, "entities": {name: [] for name in ENTITIES}}


def normal_content(content):
    """Content with every entity present as a list (unknown entities are kept out)."""
    ents = (content or {}).get("entities") or {}
    return {"format": FORMAT, "entities": {name: [r for r in (ents.get(name) or []) if isinstance(r, dict)]
                                           for name in ENTITIES}}


def _read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return copy.deepcopy(default)
    except (OSError, ValueError) as e:
        raise Problem(500, "unreadable", f"The file {Path(path).name} could not be read ({type(e).__name__}). "
                                         "Restore the project from a backup.") from None


def _write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + ".tmp")
    scratch.write_text(dumps(obj, indent=1), encoding="utf-8")
    os.replace(scratch, path)


def _who(user):
    user = user or {}
    return user.get("id") or "system", user.get("name") or user.get("id") or "system"


def _safe_name(name, limit=80):
    stem = re.sub(r"[^A-Za-z0-9._\- ]+", "_", Path(str(name or "file")).name).strip(" .")
    return (stem or "file")[:limit]


class Store:
    def __init__(self, data_dir, clock=time.time):
        self.data_dir = Path(data_dir)
        self.root = self.data_dir / "projects"
        self.clock = clock
        self._backed_up = {}

    # ---------------------------------------------------------------- projects

    def _dir(self, pid):
        check_slug(pid, "project id")
        return self.root / pid

    def exists(self, pid):
        try:
            return (self._dir(pid) / "project.json").is_file()
        except Problem:
            return False

    def project_ids(self):
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and (p / "project.json").is_file()
                      and not p.name.startswith("."))

    def project(self, pid):
        if not self.exists(pid):
            raise Problem(404, "not-found", "There is no such project.")
        return _read(self._dir(pid) / "project.json", {})

    def create_project(self, meta, user, sample=False):
        name = str(meta.get("name") or "").strip()[:120]
        if not name:
            raise Problem(400, "bad-request", "A project needs a name.")
        pid = check_slug(meta.get("id") or slug(name, "project"), "project id")
        with _WRITE:
            if self.exists(pid):
                raise Problem(409, "conflict", f"There is already a project with the id “{pid}”.")
            uid, _ = _who(user)
            now = stamp(self.clock())
            project = {"id": pid, "name": name, "sample": bool(sample), "created_at": now, "created_by": uid,
                       **self._project_fields(meta),
                       "settings": {"partner_export": False, "city_export": False, "compare_threshold_pct": 10.0}}
            _write(self._dir(pid) / "project.json", project)
            _write(self._dir(pid) / "modules.json", {"modules": []})
            self._new_dataset(pid, "baseline", "baseline", "Baseline", user, empty_content())
            return project

    @staticmethod
    def _project_fields(meta):
        out = {}
        if "place" in meta:
            out["place"] = str(meta.get("place") or "")[:120]
        if "city" in meta:
            out["city"] = (str(meta["city"])[:40] or None) if meta.get("city") else None
        if "branding" in meta:
            b = meta.get("branding") or {}
            if not isinstance(b, dict):
                raise Problem(400, "bad-request", "Branding is a set of lines: title, subtitle, badge, footer.")
            out["branding"] = {k: (" · ".join(str(x).strip() for x in b[k] if str(x).strip())
                                   if isinstance(b.get(k), (list, tuple)) else str(b.get(k) or ""))[:200]
                               for k in ("title", "subtitle", "location", "badge", "notice", "footer", "model_label")}
        if "apns" in meta:
            apns = meta.get("apns") or []
            if not isinstance(apns, list) or len(apns) > 500:
                raise Problem(400, "bad-request", "APNs are a list of parcel numbers.")
            out["apns"] = [str(a).strip()[:20] for a in apns if str(a).strip()]
        if "site" in meta:
            site = meta.get("site") or {}
            if not isinstance(site, dict):
                raise Problem(400, "bad-request", "Site facts are a set of named values.")
            try:
                json.dumps(site, allow_nan=False)
            except (TypeError, ValueError):
                raise Problem(400, "bad-request", "Site facts must be plain values with finite numbers.") from None
            out["site"] = site
        return out

    def update_project(self, pid, changes, user):
        with _WRITE:
            project = self.project(pid)
            project.update(self._project_fields(changes))
            if changes.get("name"):
                project["name"] = str(changes["name"]).strip()[:120]
            s = changes.get("settings")
            if s is not None:
                if not isinstance(s, dict):
                    raise Problem(400, "bad-request", "Settings are a set of named values.")
                settings = project.setdefault("settings", {})
                for k in ("partner_export", "city_export"):
                    if k in s:
                        settings[k] = bool(s[k])
                if "compare_threshold_pct" in s:
                    try:
                        t = float(s["compare_threshold_pct"])
                    except (TypeError, ValueError):
                        t = -1
                    if not 0 <= t <= 1000:
                        raise Problem(400, "bad-request", "The comparison threshold is a percent from 0 to 1000.")
                    settings["compare_threshold_pct"] = t
            project["updated_at"], project["updated_by"] = stamp(self.clock()), _who(user)[0]
            _write(self._dir(pid) / "project.json", project)
            return project

    # ---------------------------------------------------------------- modules

    def modules(self, pid):
        self.project(pid)
        box = _read(self._dir(pid) / "modules.json", {"modules": []})
        mods = box.get("modules") if isinstance(box, dict) else None
        return mods if isinstance(mods, list) else []

    def set_modules(self, pid, modules, user, reason=""):
        if not isinstance(modules, list) or not all(isinstance(m, dict) and m.get("id") for m in modules):
            raise Problem(400, "bad-request", "Modules are a list, each with an id.")
        for m in modules:
            check_id(m["id"], "module id")
            if not isinstance(m.get("cards", []), list) or not isinstance(m.get("tables", []), list):
                raise Problem(400, "bad-request", f"Module “{m['id']}”: cards and tables are lists.")
        try:
            json.dumps(modules, allow_nan=False)
        except (TypeError, ValueError):
            raise Problem(400, "bad-request", "Modules must hold plain values with finite numbers.") from None
        with _WRITE:
            old = self.modules(pid)
            _write(self._dir(pid) / "modules.json", {"modules": modules})
            self._revise(pid, user, "modules", "modules", "*", "*", old, modules, reason, None)
        return modules

    # ---------------------------------------------------------------- datasets

    def _ddir(self, pid, did):
        check_slug(did, "dataset id")
        return self._dir(pid) / "datasets" / did

    def _new_dataset(self, pid, did, kind, label, user, content):
        uid, _ = _who(user)
        now = stamp(self.clock())
        meta = {"id": did, "kind": kind, "label": label, "owner": uid, "created_by": uid, "created_at": now,
                "draft_updated_at": now, "draft_updated_by": uid, "published": [], "current": None}
        _write(self._ddir(pid, did) / "draft.json", normal_content(content))
        _write(self._ddir(pid, did) / "meta.json", meta)
        return meta

    def datasets(self, pid):
        self.project(pid)
        base = self._dir(pid) / "datasets"
        if not base.is_dir():
            return []
        out = [_read(p / "meta.json", None) for p in sorted(base.iterdir()) if (p / "meta.json").is_file()]
        order = {"baseline": 0, "scenario": 1, "consultant": 2}
        return sorted([m for m in out if m], key=lambda m: (order.get(m.get("kind"), 9), m.get("created_at", "")))

    def dataset(self, pid, did):
        self.project(pid)
        meta = _read(self._ddir(pid, did) / "meta.json", None)
        if not meta:
            raise Problem(404, "not-found", "There is no such dataset in this project.")
        return meta

    def create_dataset(self, pid, kind, label, user, copy_from=None):
        if kind not in ("scenario", "consultant"):
            raise Problem(400, "bad-request", "A new dataset is a scenario or a consultant submission.")
        label = str(label or "").strip()[:120] or ("Scenario" if kind == "scenario" else "Consultant submission")
        with _WRITE:
            content = empty_content()
            if copy_from:
                content = self.content(pid, copy_from.get("dataset") or "baseline", copy_from.get("version") or "published")
            stem = f"{kind}-{slug(label, kind)}"[:52]
            did, n = stem, 1
            while (self._ddir(pid, did) / "meta.json").exists():
                n += 1
                did = f"{stem}-{n}"
            meta = self._new_dataset(pid, did, kind, label, user, content)
            return meta

    def version_path(self, pid, did, n):
        return self._ddir(pid, did) / f"v{int(n):04d}.json"

    def resolve_version(self, pid, did, version):
        """'draft', or the number of a published version ('published' = the current one). None when none."""
        meta = self.dataset(pid, did)
        v = "published" if version in (None, "") else version
        if v == "draft":
            return "draft"
        if v == "published":
            return meta.get("current")
        try:
            n = int(v)
        except (TypeError, ValueError):
            raise Problem(400, "bad-request", "A version is draft, published or a version number.") from None
        if not any(p["version"] == n for p in meta.get("published", [])):
            raise Problem(404, "not-found", f"This dataset has no version {n}.")
        return n

    def content(self, pid, did, version="published"):
        v = self.resolve_version(pid, did, version)
        if v is None:
            raise Problem(404, "not-found", "This dataset has not been published yet.")
        if v == "draft":
            return normal_content(_read(self._ddir(pid, did) / "draft.json", empty_content()))
        return normal_content(_read(self.version_path(pid, did, v), empty_content()))

    def as_of(self, pid, did, version):
        v = self.resolve_version(pid, did, version)
        if v in (None, "draft"):
            return day(self.clock())
        for p in self.dataset(pid, did).get("published", []):
            if p["version"] == v:
                return p["at"][:10]
        return day(self.clock())

    def _save_draft(self, pid, did, content, user):
        _write(self._ddir(pid, did) / "draft.json", normal_content(content))
        meta = self.dataset(pid, did)
        meta["draft_updated_at"], meta["draft_updated_by"] = stamp(self.clock()), _who(user)[0]
        _write(self._ddir(pid, did) / "meta.json", meta)

    def put_record(self, pid, did, entity, record, user, reason="", classification=None):
        """Add or change one record of the draft. Returns (record, [{field, old, new}])."""
        with _WRITE:
            content = self.content(pid, did, "draft")
            rows = content["entities"][entity]
            old = next((r for r in rows if r.get("id") == record["id"]), None)
            klass = classification or record.get("provenance") or (old or {}).get("provenance")
            if old is None:
                rows.append(record)
                changes = [{"field": "*", "old": None, "new": record}]
            else:
                changes = [{"field": k, "old": old.get(k), "new": record.get(k)}
                           for k in sorted(set(old) | set(record)) if old.get(k) != record.get(k)]
                rows[rows.index(old)] = record
            if not changes:
                return record, []
            self._save_draft(pid, did, content, user)
            for c in changes:
                self._revise(pid, user, did, entity, record["id"], c["field"], c["old"], c["new"], reason, klass)
            return record, changes

    def remove_record(self, pid, did, entity, rid, user, reason=""):
        with _WRITE:
            content = self.content(pid, did, "draft")
            rows = content["entities"][entity]
            old = next((r for r in rows if r.get("id") == rid), None)
            if old is None:
                raise Problem(404, "not-found", "There is no such record in this draft.")
            rows.remove(old)
            self._save_draft(pid, did, content, user)
            self._revise(pid, user, did, entity, rid, "*", old, None, reason, old.get("provenance"))
            return True

    def put_records(self, pid, did, entities, user, mode="merge", reason=""):
        """An import: {entity: [records]} into the draft. merge adds and changes by id; replace swaps whole
        entities (only the ones given). Returns {entity: rows written}."""
        if mode not in ("merge", "replace"):
            raise Problem(400, "bad-request", "An import either merges (add and change by id) or replaces.")
        with _WRITE:
            content = self.content(pid, did, "draft")
            counts, revs = {}, []
            for entity, records in entities.items():
                rows = content["entities"][entity]
                by_id = {r.get("id"): r for r in rows}
                if mode == "replace":
                    incoming = {x["id"] for x in records}
                    for r in rows:
                        if r.get("id") not in incoming:
                            revs.append((entity, r["id"], "*", r, None, r.get("provenance")))
                    by_id_new = {}
                else:
                    by_id_new = dict(by_id)
                for rec in records:
                    old = by_id.get(rec["id"])
                    klass = rec.get("provenance") or (old or {}).get("provenance")
                    if old is None:
                        revs.append((entity, rec["id"], "*", None, rec, klass))
                    else:
                        for k in sorted(set(old) | set(rec)):
                            if old.get(k) != rec.get(k):
                                revs.append((entity, rec["id"], k, old.get(k), rec.get(k), klass))
                    by_id_new[rec["id"]] = rec
                content["entities"][entity] = list(by_id_new.values())
                counts[entity] = len(records)
            self._save_draft(pid, did, content, user)
            for entity, rid, field, old, new, klass in revs:
                self._revise(pid, user, did, entity, rid, field, old, new, reason or "import", klass)
            return counts

    def publish(self, pid, did, user, note="", content=None, from_version=None, reason=""):
        with _WRITE:
            meta = self.dataset(pid, did)
            body = normal_content(content if content is not None else self.content(pid, did, "draft"))
            n = max([p["version"] for p in meta.get("published", [])] or [0]) + 1
            uid, _ = _who(user)
            now = stamp(self.clock())
            path = self.version_path(pid, did, n)
            if path.exists():
                raise Problem(409, "conflict", "That version already exists; try again.")
            _write(path, {**body, "published_at": now, "published_by": uid, "note": str(note or "")[:500]})
            meta.setdefault("published", []).append({"version": n, "at": now, "by": uid, "note": str(note or "")[:500],
                                                     "from_version": from_version, "reason": str(reason or "")[:500]})
            meta["current"] = n
            _write(self._ddir(pid, did) / "meta.json", meta)
            self._revise(pid, user, did, "*", "*", "published", from_version, n, reason or note or "publish", None)
            return n

    def rollback(self, pid, did, version, user, reason="", reset_draft=False):
        """Publish an older version's content again, as a new version. The draft is kept unless reset_draft."""
        if not str(reason or "").strip():
            raise Problem(400, "bad-request", "Say why the version is being rolled back.")
        with _WRITE:
            n = self.resolve_version(pid, did, version)
            if n in (None, "draft"):
                raise Problem(400, "bad-request", "Roll back to a published version number.")
            old = self.content(pid, did, n)
            new = self.publish(pid, did, user, f"rolled back to version {n}", old, from_version=n, reason=reason)
            if reset_draft:
                self._save_draft(pid, did, old, user)
            return new

    # ---------------------------------------------------------------- revision log

    def _revise(self, pid, user, did, entity, rid, field, old, new, reason, klass):
        uid, name = _who(user)
        chain.append(self._dir(pid) / "revisions.jsonl", {
            "at": stamp(self.clock()), "user": uid, "name": name, "dataset": did, "entity": entity, "id": rid,
            "field": field, "oldValue": old, "newValue": new, "reason": str(reason or "")[:500], "classification": klass})

    def revisions(self, pid, dataset=None, entity=None, rid=None, limit=500):
        self.project(pid)
        path = self._dir(pid) / "revisions.jsonl"
        rows = [r for r in chain.read(path) if (not dataset or r.get("dataset") == dataset)
                and (not entity or r.get("entity") == entity) and (not rid or r.get("id") == rid)]
        return {"revisions": list(reversed(rows))[:max(1, min(int(limit or 500), 5000))], "total": len(rows),
                "chain": chain.verify(path)}

    # ---------------------------------------------------------------- notes on figures

    def notes(self, pid, status=None, entity=None, rid=None):
        self.project(pid)
        rows = (_read(self._dir(pid) / "notes.json", {"notes": []}) or {}).get("notes") or []
        return [n for n in rows if (not status or n.get("status") == status)
                and (not entity or n.get("target", {}).get("entity") == entity)
                and (not rid or n.get("target", {}).get("id") == rid)]

    def _note_text(self, text):
        text = str(text or "").strip()
        if not text:
            raise Problem(400, "bad-request", "A note needs some text.")
        return text[:5000]

    def add_note(self, pid, target, text, user):
        if not isinstance(target, dict) or target.get("entity") not in ENTITIES and target.get("entity") != "modules":
            raise Problem(400, "bad-request", "Say which figure the note is on: {entity, id, field}.")
        check_id(target.get("id"), "record id")
        tgt = {"entity": target["entity"], "id": target["id"], "field": str(target.get("field") or "")[:64] or None,
               "dataset": str(target.get("dataset") or "")[:64] or None}
        with _WRITE:
            box = _read(self._dir(pid) / "notes.json", {"notes": []})
            uid, name = _who(user)
            note = {"id": f"n{len(box['notes']) + 1:04d}-{hashlib.sha1(str(self.clock()).encode()).hexdigest()[:4]}",
                    "target": tgt, "text": self._note_text(text), "by": uid, "by_name": name, "at": stamp(self.clock()),
                    "status": "open", "resolution": "", "resolved_by": None, "resolved_at": None, "replies": []}
            box["notes"].append(note)
            _write(self._dir(pid) / "notes.json", box)
            return note

    def _change_note(self, pid, nid, change):
        with _WRITE:
            box = _read(self._dir(pid) / "notes.json", {"notes": []})
            for note in box["notes"]:
                if note["id"] == nid:
                    change(note)
                    _write(self._dir(pid) / "notes.json", box)
                    return note
        raise Problem(404, "not-found", "There is no such note.")

    def reply_note(self, pid, nid, text, user):
        uid, name = _who(user)
        text = self._note_text(text)
        return self._change_note(pid, nid, lambda n: n["replies"].append(
            {"by": uid, "by_name": name, "at": stamp(self.clock()), "text": text}))

    def resolve_note(self, pid, nid, status, resolution, user):
        if status not in ("resolved", "open"):
            raise Problem(400, "bad-request", "A note is resolved or open.")
        uid, _ = _who(user)

        def change(n):
            n["status"] = status
            n["resolution"] = str(resolution or "")[:2000]
            n["resolved_by"] = uid if status == "resolved" else None
            n["resolved_at"] = stamp(self.clock()) if status == "resolved" else None
        return self._change_note(pid, nid, change)

    # ---------------------------------------------------------------- documents

    def documents(self, pid):
        self.project(pid)
        return (_read(self._dir(pid) / "documents" / "library.json", {"documents": []}) or {}).get("documents") or []

    def add_document(self, pid, filename, data, user, title="", task="", doc_id=None, note="", audiences=None):
        ext = Path(str(filename or "")).suffix.lower()
        if ext not in DOCUMENT_TYPES:
            raise Problem(400, "bad-request", "The library keeps PDF, PowerPoint (.pptx), Excel (.xlsx), Word (.docx) "
                                              "and .csv files.")
        if not data:
            raise Problem(400, "bad-request", "The file is empty.")
        if ext == ".pdf" and not data[:1024].lstrip().startswith(b"%PDF"):
            raise Problem(400, "bad-request", "That file does not look like a PDF.")
        if ext in (".pptx", ".xlsx", ".docx") and not data.startswith(b"PK\x03\x04"):
            raise Problem(400, "bad-request", f"That file does not look like a {ext} file.")
        if ext == ".csv" and b"\x00" in data[:65536]:
            raise Problem(400, "bad-request", "That file does not look like a .csv file.")
        uid, name = _who(user)
        with _WRITE:
            lib_path = self._dir(pid) / "documents" / "library.json"
            box = _read(lib_path, {"documents": []})
            if doc_id:
                doc = next((d for d in box["documents"] if d["id"] == doc_id), None)
                if doc is None:
                    raise Problem(404, "not-found", "There is no such document to add a version to.")
            else:
                base = slug(title or Path(filename).stem, "document")[:40]
                did, n = base, 1
                while any(d["id"] == did for d in box["documents"]):
                    n += 1
                    did = f"{base}-{n}"
                doc = {"id": did, "title": str(title or Path(filename).stem)[:200], "task": str(task or "")[:60],
                       "kind": ext.lstrip("."), "audiences": list(audiences or ["internal"]), "created_at":
                       stamp(self.clock()), "created_by": uid, "versions": []}
                box["documents"].append(doc)
            v = len(doc["versions"]) + 1
            stored = f"v{v}{ext}"
            target = self._dir(pid) / "documents" / doc["id"] / stored
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            doc["versions"].append({"version": v, "filename": _safe_name(filename), "file": stored, "size": len(data),
                                    "sha256": hashlib.sha256(data).hexdigest(), "uploaded_by": uid,
                                    "uploaded_by_name": name, "uploaded_at": stamp(self.clock()),
                                    "note": str(note or "")[:500]})
            if title and doc_id:
                doc["title"] = str(title)[:200]
            _write(lib_path, box)
            return doc

    def share_document(self, pid, doc_id, audiences):
        from .schema import AUDIENCES
        if not isinstance(audiences, list) or any(a not in AUDIENCES for a in audiences):
            raise Problem(400, "bad-request", f"Audiences are some of: {', '.join(AUDIENCES)}.")
        with _WRITE:
            lib_path = self._dir(pid) / "documents" / "library.json"
            box = _read(lib_path, {"documents": []})
            for d in box["documents"]:
                if d["id"] == doc_id:
                    d["audiences"] = sorted(set(audiences) | {"internal"})
                    _write(lib_path, box)
                    return d
        raise Problem(404, "not-found", "There is no such document.")

    def document_file(self, pid, doc_id, version):
        doc = next((d for d in self.documents(pid) if d["id"] == doc_id), None)
        if doc is None or not doc["versions"]:
            raise Problem(404, "not-found", "There is no such document.")
        if version in (None, "", "latest"):
            v = doc["versions"][-1]
        else:
            v = next((x for x in doc["versions"] if str(x["version"]) == str(version)), None)
            if v is None:
                raise Problem(404, "not-found", "That document has no such version.")
        folder = self._dir(pid) / "documents"
        if not SLUG.fullmatch(str(doc.get("id") or "")) or not _STORED_FILE.fullmatch(str(v.get("file") or "")):
            raise Problem(404, "not-found", "That version's file is not where the library keeps files.")
        path = folder / doc["id"] / v["file"]
        if not _inside(folder, path):
            raise Problem(404, "not-found", "That version's file is not where the library keeps files.")
        if not path.is_file():
            raise Problem(404, "not-found", "That version's file is missing. Restore the project from a backup.")
        return doc, v, path.read_bytes()

    # ---------------------------------------------------------------- GIS layers

    def layers(self, pid, include_removed=False):
        self.project(pid)
        rows = (_read(self._dir(pid) / "gis" / "layers.json", {"layers": []}) or {}).get("layers") or []
        return [x for x in rows if include_removed or not x.get("removed")]

    def add_layer(self, pid, geojson, info, user):
        uid, _ = _who(user)
        with _WRITE:
            path = self._dir(pid) / "gis" / "layers.json"
            box = _read(path, {"layers": []})
            base = slug(info.get("label") or info.get("source_name") or "layer", "layer")[:40]
            lid, n = base, 1
            while any(x["id"] == lid for x in box["layers"]):
                n += 1
                lid = f"{base}-{n}"
            layer = {"id": lid, **info, "uploaded_by": uid, "uploaded_at": stamp(self.clock()), "removed": False}
            _write(self._dir(pid) / "gis" / f"{lid}.geojson", geojson)
            box["layers"].append(layer)
            _write(path, box)
            return layer

    def layer(self, pid, lid):
        check_slug(lid, "layer id")
        meta = next((x for x in self.layers(pid) if x["id"] == lid), None)
        if meta is None:
            raise Problem(404, "not-found", "There is no such layer.")
        return meta, _read(self._dir(pid) / "gis" / f"{lid}.geojson", {"type": "FeatureCollection", "features": []})

    def share_layer(self, pid, lid, audiences):
        with _WRITE:
            path = self._dir(pid) / "gis" / "layers.json"
            box = _read(path, {"layers": []})
            for x in box["layers"]:
                if x["id"] == lid and not x.get("removed"):
                    x["audiences"] = sorted(set(audiences) | {"internal"})
                    _write(path, box)
                    return x
        raise Problem(404, "not-found", "There is no such layer.")

    def remove_layer(self, pid, lid, user):
        with _WRITE:
            path = self._dir(pid) / "gis" / "layers.json"
            box = _read(path, {"layers": []})
            for x in box["layers"]:
                if x["id"] == lid and not x.get("removed"):
                    x["removed"], x["removed_by"], x["removed_at"] = True, _who(user)[0], stamp(self.clock())
                    _write(path, box)
                    return True
        raise Problem(404, "not-found", "There is no such layer.")

    # ---------------------------------------------------------------- import previews

    def save_preview(self, pid, preview):
        iid = hashlib.sha256(f"{pid}{self.clock()}{os.urandom(8).hex()}".encode()).hexdigest()[:16]
        folder = self._dir(pid) / "imports"
        if folder.is_dir():
            for old in folder.glob("*.json"):
                try:
                    if self.clock() - old.stat().st_mtime > PREVIEW_HOURS * 3600:
                        old.unlink()
                except OSError:
                    pass
        _write(folder / f"{iid}.json", {**preview, "saved_at": self.clock()})
        return iid

    def load_preview(self, pid, iid):
        if not re.fullmatch(r"[0-9a-f]{16}", str(iid or "")):
            raise Problem(404, "not-found", "There is no such import waiting.")
        box = _read(self._dir(pid) / "imports" / f"{iid}.json", None)
        if not box or self.clock() - box.get("saved_at", 0) > PREVIEW_HOURS * 3600:
            raise Problem(404, "not-found", "That import preview has expired. Upload the file again.")
        return box

    def drop_preview(self, pid, iid):
        try:
            (self._dir(pid) / "imports" / f"{iid}.json").unlink()
        except OSError:
            pass

    # ---------------------------------------------------------------- backups

    def _files(self, pid):
        base = self._dir(pid)
        for path in sorted(base.rglob("*")):
            rel = path.relative_to(base).as_posix()
            if path.is_file() and not rel.startswith(("backups/", "imports/")) and not rel.endswith(".tmp"):
                yield rel, path

    def _zip_project(self, pid, manifest=False, user=None):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            files = {}
            for rel, path in self._files(pid):
                data = path.read_bytes()
                files[rel] = hashlib.sha256(data).hexdigest()
                z.writestr(("project/" if manifest else "") + rel, data)
            if manifest:
                z.writestr("manifest.json", dumps({
                    "format": PACKAGE_FORMAT, "format_version": 1, "project_id": pid,
                    "name": self.project(pid).get("name"), "exported_at": stamp(self.clock()),
                    "exported_by": _who(user)[0], "files": files}, indent=1))
        return buf.getvalue()

    def backups(self, pid):
        self.project(pid)
        folder = self._dir(pid) / "backups"
        if not folder.is_dir():
            return []
        return [{"name": p.name, "size": p.stat().st_size, "at": stamp(p.stat().st_mtime)}
                for p in sorted(folder.glob("*.zip"), reverse=True)]

    def backup_now(self, pid, label=""):
        with _WRITE:
            now = self.clock()
            name = day(now) + ".zip" if not label else f"{day(now)}T{time.strftime('%H%M%S', time.localtime(now))}-{label}.zip"
            folder = self._dir(pid) / "backups"
            folder.mkdir(parents=True, exist_ok=True)
            scratch = folder / (name + ".tmp")
            scratch.write_bytes(self._zip_project(pid))
            os.replace(scratch, folder / name)
            zips = sorted(folder.glob("*.zip"))
            for old in zips[:-KEEP_BACKUPS]:
                try:
                    old.unlink()
                except OSError:
                    pass
            return {"name": name, "size": (folder / name).stat().st_size, "at": stamp(now)}

    def daily_backup(self, pid):
        """The first use of a project each day makes that day's backup. Returns it, or None when already made."""
        today = day(self.clock())
        if self._backed_up.get(pid) == today:
            return None
        if not self.exists(pid):
            return None
        if (self._dir(pid) / "backups" / f"{today}.zip").exists():
            self._backed_up[pid] = today
            return None
        made = self.backup_now(pid)
        self._backed_up[pid] = today
        return made

    def restore(self, pid, name):
        if not re.fullmatch(r"[0-9A-Za-z\-]+\.zip", str(name or "")):
            raise Problem(400, "bad-request", "That is not the name of a backup.")
        src = self._dir(pid) / "backups" / name
        if not src.is_file():
            raise Problem(404, "not-found", "There is no such backup.")
        with _WRITE:
            files = _safe_members(src.read_bytes(), prefix="")
            if "project.json" not in files:
                raise Problem(400, "bad-request", "That backup has no project.json, so it was not restored.")
            safety = self.backup_now(pid, "before-restore")
            self._replace_files(pid, files)
            return safety

    def _replace_files(self, pid, files):
        """Put these files in place of the project's own (backups are kept)."""
        base = self._dir(pid)
        stage = self.root / f".stage-{pid}-{os.urandom(4).hex()}"
        try:
            for rel, data in files.items():
                target = stage / rel
                if not safe_relative(rel) or not _inside(stage, target) or target.resolve() == stage.resolve():
                    raise Problem(400, "bad-request", f"A file name in that zip is not safe: {str(rel)[:80]}.")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            trash = self.root / f".trash-{pid}-{os.urandom(4).hex()}"
            trash.mkdir(parents=True)
            if base.is_dir():
                for item in base.iterdir():
                    if item.name != "backups":
                        shutil.move(str(item), str(trash / item.name))
            base.mkdir(parents=True, exist_ok=True)
            for item in stage.iterdir():
                shutil.move(str(item), str(base / item.name))
            shutil.rmtree(trash, ignore_errors=True)
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    # ---------------------------------------------------------------- whole-project zip

    def export_package(self, pid, user):
        self.project(pid)
        return self._zip_project(pid, manifest=True, user=user)

    def import_package(self, data, user, replace=False):
        """Install a project zip made by export_package. Returns (project, replaced, safety backup or None)."""
        files = _safe_members(data, prefix=None)
        try:
            manifest = json.loads(files.pop("manifest.json").decode("utf-8"))
        except (KeyError, ValueError, UnicodeDecodeError):
            raise Problem(400, "bad-request", "That zip is not a Land Planner project (it has no readable manifest).") from None
        if manifest.get("format") != PACKAGE_FORMAT or not isinstance(manifest.get("files"), dict):
            raise Problem(400, "bad-request", "That zip is not a Land Planner project.")
        pid = check_slug(manifest.get("project_id"), "project id")
        inner = {}
        for name, blob in files.items():
            rel = name[len("project/"):]
            if not name.startswith("project/") or not safe_relative(rel):
                raise Problem(400, "bad-request", f"That zip holds a file outside the project: {name[:80]}.")
            inner[rel] = blob
        listed = manifest["files"]
        if set(inner) != set(listed):
            raise Problem(400, "bad-request", "That zip's files do not match its manifest, so it was not imported.")
        for rel, blob in inner.items():
            if hashlib.sha256(blob).hexdigest() != listed[rel]:
                raise Problem(400, "bad-request", f"The file {rel[:80]} was changed after the zip was made, so it was "
                                                  "not imported.")
        try:
            project = json.loads(inner["project.json"].decode("utf-8"))
        except (KeyError, ValueError, UnicodeDecodeError):
            raise Problem(400, "bad-request", "That zip has no readable project.json.") from None
        if project.get("id") != pid:
            raise Problem(400, "bad-request", "That zip's project.json names another project.")
        with _WRITE:
            safety, replaced = None, self.exists(pid)
            if replaced and not replace:
                raise Problem(409, "conflict", f"There is already a project “{pid}” here. Import it again with "
                                               "replace to put the zip's copy in its place (a backup is made first).")
            if replaced:
                safety = self.backup_now(pid, "before-import")
            self._replace_files(pid, inner)
            self._backed_up.pop(pid, None)
            return self.project(pid), replaced, safety


_RESERVED = re.compile(r"(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³]|conin\$|conout\$)(\..*)?", re.I)
_STORED_FILE = re.compile(r"v[0-9]{1,4}\.(pdf|pptx|xlsx|docx|csv)")


def safe_relative(name):
    """True when a zip member's name is a plain relative path that stays inside its folder on Windows and elsewhere:
    no drive, root, '..', ':' (drives and NTFS streams), reserved device name or trailing dot or space in any part."""
    name = str(name or "")
    if not name or "\\" in name or "\x00" in name:
        return False
    win = PureWindowsPath(name)
    if win.drive or win.root or name.startswith("/"):
        return False
    for part in name.split("/"):
        if part in ("", ".", "..") or ":" in part or part != part.rstrip(". ") or _RESERVED.fullmatch(part):
            return False
        if any(ord(c) < 32 for c in part):
            return False
    return True


def _inside(base, target):
    """True when target (once resolved) is inside base."""
    base, target = Path(base).resolve(), Path(target).resolve()
    return base == target or base in target.parents


def _safe_members(data, prefix=None):
    """{relative path: bytes} of a zip, refusing anything that could land outside its folder or is far too big."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError):
        raise Problem(400, "bad-request", "That file is not a zip file.") from None
    out, total = {}, 0
    with z:
        infos = z.infolist()
        if len(infos) > MAX_ZIP_FILES:
            raise Problem(413, "too-large", "That zip holds too many files.")
        for info in infos:
            if info.is_dir():
                continue
            name = info.filename
            if not safe_relative(name):
                raise Problem(400, "bad-request", f"That zip holds a file with an unsafe name: {name[:80]}.")
            if info.flag_bits & 0x1:
                raise Problem(400, "bad-request", "That zip is password-protected.")
            total += info.file_size
            if total > MAX_ZIP_BYTES:
                raise Problem(413, "too-large", "That zip expands to far too much data.")
            out[name] = z.read(info)
    return out
