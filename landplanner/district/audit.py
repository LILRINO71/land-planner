"""The audit log (NFR-02, SEC-03): sign-ins, denied access, uploads, edits, publishes, exports and user changes,
each with who and when, in data/district-audit.jsonl. Append-only and hash-chained (chain.py)."""
import json
import time
from pathlib import Path

from . import chain, stamp


TEXT_LIMIT = 500        # any one string in an entry's detail
LIST_LIMIT = 100        # items of a list in the detail


def _cut(v, n):
    return v[:n] + "…" if isinstance(v, str) and len(v) > n else v


def _small(x, depth=0):
    """The detail with every string, list and nesting kept small: whatever a caller sends, an entry stays a line."""
    if isinstance(x, str):
        return _cut(x, TEXT_LIMIT)
    if depth > 4:
        return "…"
    if isinstance(x, dict):
        return {_cut(str(k), 80): _small(v, depth + 1) for k, v in list(x.items())[:LIST_LIMIT]}
    if isinstance(x, (list, tuple)):
        return [_small(v, depth + 1) for v in list(x)[:LIST_LIMIT]]
    return x


class Audit:
    def __init__(self, data_dir, clock=time.time):
        self.path = Path(data_dir) / "district-audit.jsonl"
        self.clock = clock

    def log(self, action, user=None, outcome="ok", project=None, **detail):
        user = user or {}
        return chain.append(self.path, {"at": stamp(self.clock()), "ts": self.clock(), "user": _cut(user.get("id"), 80),
                                        "name": _cut(user.get("name"), 80), "role": user.get("role"), "action": action,
                                        "outcome": outcome, "project": project, "detail": _small(detail)})

    def search(self, q="", action="", user="", outcome="", project="", limit=200, offset=0):
        rows = chain.read(self.path)
        q = str(q or "").lower()
        hits = [r for r in rows if (not action or r.get("action") == action) and (not outcome or r.get("outcome") == outcome)
                and (not user or user in (r.get("user"), r.get("name"))) and (not project or r.get("project") == project)
                and (not q or q in json.dumps(r, ensure_ascii=False).lower())]
        hits.reverse()
        limit = max(1, min(int(limit or 200), 2000))
        offset = max(0, int(offset or 0))
        return {"entries": hits[offset:offset + limit], "total": len(hits), "chain": chain.verify(self.path)}
