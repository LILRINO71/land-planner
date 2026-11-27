"""An append-only JSON-lines log in which every line carries the hash of the line before it, so a changed, removed
or reordered line shows. Used for the audit log and each project's revision log.

Tamper-evident, not tamper-proof: someone who can write the file could rewrite the whole chain. The head hash is
also given in every read, so a copy of it kept elsewhere proves the log has not been rewritten since.

Every append also writes <log>.head ({lines, head}) beside the log. A log with lines cut off its end, or deleted, still
chains correctly by itself; against the head file it is shorter than it was, or its line at that count is another
one, and verify() says so.
"""
import hashlib
import json
import os
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


def head_path(path):
    return Path(path).with_name(Path(path).name + ".head")


def _read_head(path):
    """{lines, head} kept by the last append, or None (no file, or one that cannot be read)."""
    try:
        box = json.loads(head_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(box, dict) and isinstance(box.get("lines"), int) and isinstance(box.get("head"), str):
        return box
    return None


def _write_head(path, lines, line, broken=None):
    target = head_path(path)
    scratch = target.with_name(target.name + ".tmp")
    box = {"lines": lines, "head": _hash(line)}
    if broken:
        box["broken"] = broken
    scratch.write_text(json.dumps(box), encoding="utf-8")
    os.replace(scratch, target)


def _scan(path, at):
    """(number of lines, hash of line number `at` or None)."""
    n, found = 0, None
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip("\n")
                if line.strip():
                    n += 1
                    if n == at:
                        found = _hash(line)
    except FileNotFoundError:
        pass
    return n, found


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
        kept = _read_head(path)
        broken = (kept or {}).get("broken")
        if kept and line is not None and kept["head"] == _hash(line):
            lines = kept["lines"] + 1
        else:
            count, at_kept = _scan(path, kept["lines"] if kept else 0)
            lines = max(count, kept["lines"] if kept else 0) + 1
            if kept and kept["lines"] and (count < kept["lines"] or at_kept != kept["head"]) and not broken:
                # the log no longer holds what was written: keep saying so after this line is added, too
                broken = (f"before line {count + 1} was added, the log held {count} lines where {kept['lines']} "
                          "had been written, or other lines than those")
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
            f.flush()
        try:
            _write_head(path, lines, text, broken)
        except OSError:
            pass  # the log itself is written; the next append writes the head again
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
    """{ok, lines, broken_at, reason, head}: walks the chain line by line, then checks it against the head file."""
    prev, n, kept = None, 0, _read_head(path)
    at_kept = None
    try:
        f = open(path, encoding="utf-8")
    except FileNotFoundError:
        if kept and kept["lines"] > 0:
            return {"ok": False, "lines": 0, "broken_at": 1, "head": None,
                    "reason": f"the log is missing, but {kept['lines']} lines were written to it"}
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
            if kept and n == kept["lines"]:
                at_kept = _hash(line)
    if kept and kept.get("broken"):
        return {"ok": False, "lines": n, "broken_at": None, "head": None, "reason": str(kept["broken"])}
    if kept and n < kept["lines"]:
        return {"ok": False, "lines": n, "broken_at": n + 1, "head": None,
                "reason": f"the log ends after {n} lines, but {kept['lines']} were written (lines were cut off its end)"}
    if kept and kept["lines"] > 0 and at_kept != kept["head"]:
        return {"ok": False, "lines": n, "broken_at": kept["lines"], "head": None,
                "reason": "the log was written again from the start (its lines are not the ones first written)"}
    return {"ok": True, "lines": n, "broken_at": None, "reason": "", "head": _hash(prev) if prev else GENESIS}
