"""Answers from the public services, kept on disk so the app is quick and does not ask the same thing twice.

    value, meta = cache.get("menifee/large-parcels", max_age=12 * 3600, load=adapter.large_parcels)

  - A copy younger than `max_age` is returned without asking anyone.
  - Otherwise `load()` is called. If it fails and an older copy exists, the older copy is returned and
    meta["stale"] is True, so the page can say "showing the copy from <date>".
  - Two requests for the same thing at the same moment ask the service once, not twice.

meta is {"fetched": <seconds since 1970 when the answer was read>, "stale": bool}.
"""
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path


class Cache:
    def __init__(self, folder, clock=time.time):
        self.folder = Path(folder)
        self.clock = clock
        self._memory = {}
        self._locks = {}
        self._guard = threading.Lock()

    def _path(self, key):
        name = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")[:80]
        return self.folder / f"{name}-{hashlib.sha1(key.encode()).hexdigest()[:10]}.json"

    def _lock(self, key):
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def peek(self, key):
        """The saved copy as (value, fetched) or None. Never asks the source."""
        if key in self._memory:
            return self._memory[key]
        try:
            box = json.loads(self._path(key).read_text(encoding="utf-8"))
            entry = (box["value"], float(box["fetched"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None
        self._memory[key] = entry
        return entry

    def put(self, key, value):
        entry = (value, self.clock())
        self._memory[key] = entry
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            path = self._path(key)
            scratch = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
            scratch.write_text(json.dumps({"key": key, "fetched": entry[1], "value": value}, separators=(",", ":")),
                               encoding="utf-8")
            os.replace(scratch, path)
        except OSError:
            pass  # a cache that cannot be written is only slower, not wrong
        return entry

    def get(self, key, max_age, load, fresh=False):
        """(value, meta). `fresh=True` asks the source even when a young copy exists."""
        with self._lock(key):
            saved = self.peek(key)
            if saved and not fresh and self.clock() - saved[1] < max_age:
                return saved[0], {"fetched": saved[1], "stale": False}
            try:
                value = load()
            except Exception:
                if saved:
                    return saved[0], {"fetched": saved[1], "stale": True}
                raise
            value, fetched = self.put(key, value)
            return value, {"fetched": fetched, "stale": False}

    def forget(self, key):
        self._memory.pop(key, None)
        try:
            self._path(key).unlink()
        except OSError:
            pass
