"""An append-only JSON-lines log in which every line carries the hash of the line before it, so a changed, removed
or reordered line shows. Used for the audit log and each project's revision log.

Tamper-evident, not tamper-proof: someone who can write the file could rewrite the whole chain. The head hash is
also given in every read, so a copy of it kept elsewhere proves the log has not been rewritten since.
"""
import hashlib
import json
import threading
from pathlib import Path

from .jsonsafe import clean, dumps

GENESIS = "0" * 64
_locks = {}
_locks_guard = threading.Lock()


def _lock(path):
    with _locks_guard:
        return _locks.setdefault(str(Path(path).resolve()), threading.Lock())


def _hash(line):
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def _entry_hash(entry):
    body = {k: v for k, v in entry.items() if k != "hash"}
    return _hash(json.dumps(body, sort_keys=True, ensure_ascii=False, allow_nan=False))


def _last(path):
    """(seq, line) of the last line, or (0, None)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            back, data = 0, b""
            while back < size:
                back = min(size, back + 65536)
                f.seek(size - back)
                data = f.read(back)
                body = data.rstrip(b"\r\n")
                if back == size or b"\n" in body:      # the last whole line is in hand
                    break
            tail = data.decode("utf-8").splitlines()
    except FileNotFoundError:
        return 0, None
    except UnicodeDecodeError:
        tail = data[data.find(b"\n") + 1:].decode("utf-8", "replace").splitlines()
    for line in reversed(tail):
        if line.strip():
            try:
                return int(json.loads(line).get("seq", 0)), line
            except (ValueError, AttributeError):
                return 0, line
    return 0, None


def append(path, entry):
    """Add one entry; returns it with seq, prev and hash filled in."""
    path = Path(path)
    with _lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        seq, line = _last(path)
        record = clean({"seq": seq + 1, **{k: v for k, v in entry.items() if k not in ("seq", "prev", "hash")},
                        "prev": _hash(line) if line else GENESIS})
        record["hash"] = _entry_hash(record)
        text = dumps(record, sort_keys=False)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
            f.flush()
        return record


def read(path):
    """Every entry, oldest first (unreadable lines are skipped here; verify() reports them)."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
    except FileNotFoundError:
        pass
    return out


def verify(path):
    """{ok, lines, broken_at, reason, head}: walks the chain line by line."""
    prev, n = None, 0
    try:
        f = open(path, encoding="utf-8")
    except FileNotFoundError:
        return {"ok": True, "lines": 0, "broken_at": None, "reason": "", "head": GENESIS}
    with f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            n += 1
            try:
                entry = json.loads(line)
            except ValueError:
                return {"ok": False, "lines": n, "broken_at": n, "reason": "a line is not readable", "head": None}
            want = _hash(prev) if prev is not None else GENESIS
            if entry.get("prev") != want:
                return {"ok": False, "lines": n, "broken_at": n,
                        "reason": "this line does not follow the one before it (a line was changed, removed or moved)",
                        "head": None}
            if entry.get("hash") != _entry_hash(entry):
                return {"ok": False, "lines": n, "broken_at": n, "reason": "this line was changed after it was written",
                        "head": None}
            prev = line
    return {"ok": True, "lines": n, "broken_at": None, "reason": "", "head": _hash(prev) if prev else GENESIS}
