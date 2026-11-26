"""My lands: the parcels the owner saved, in one small file that survives a restart.

The file is the owner's own data, so it lives in data/ (which git ignores). Each saved land keeps a copy of the
parcel's facts from the day it was saved, so the My lands page still opens when the city's service is down.
"""
import datetime
import json
import os
import threading
from pathlib import Path


class SavedPlans:
    """The owner's own changes to each land's plan (acres, figures, extra costs), one small file like My lands."""

    def __init__(self, path):
        self.path = Path(path)
        self._guard = threading.Lock()

    def _read(self):
        try:
            plans = json.loads(self.path.read_text(encoding="utf-8"))["plans"]
            return plans if isinstance(plans, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, KeyError, TypeError):
            try:
                os.replace(self.path, self.path.with_suffix(".unreadable.json"))
            except OSError:
                pass
            return {}

    def get(self, city, apn):
        with self._guard:
            found = self._read().get(f"{city}/{apn}")
            return found if isinstance(found, dict) else None

    def put(self, city, apn, settings):
        """Keep the settings; None forgets them (back to the suggested plan)."""
        with self._guard:
            plans = self._read()
            if settings is None:
                plans.pop(f"{city}/{apn}", None)
            else:
                plans[f"{city}/{apn}"] = settings
            self.path.parent.mkdir(parents=True, exist_ok=True)
            scratch = self.path.with_suffix(".tmp")
            scratch.write_text(json.dumps({"version": 1, "plans": plans}, indent=1), encoding="utf-8")
            os.replace(scratch, self.path)


class SavedLands:
    def __init__(self, path):
        self.path = Path(path)
        self._guard = threading.Lock()

    def _read(self):
        try:
            box = json.loads(self.path.read_text(encoding="utf-8"))
            lands = box["lands"]
            return [x for x in lands if isinstance(x, dict) and x.get("city") and x.get("apn")]
        except FileNotFoundError:
            return []
        except (OSError, ValueError, KeyError, TypeError):
            # Unreadable: keep it beside the new file instead of silently writing over the owner's list.
            try:
                os.replace(self.path, self.path.with_suffix(".unreadable.json"))
            except OSError:
                pass
            return []

    def _write(self, lands):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        scratch = self.path.with_suffix(".tmp")
        scratch.write_text(json.dumps({"version": 1, "lands": lands}, indent=1), encoding="utf-8")
        os.replace(scratch, self.path)

    def all(self):
        """Saved lands, most recently saved first."""
        with self._guard:
            return sorted(self._read(), key=lambda x: x.get("saved_at", ""), reverse=True)

    def has(self, city, apn):
        return any(x["city"] == city and x["apn"] == apn for x in self.all())

    def save(self, city, apn, parcel, now=None):
        """Add a land (or refresh the facts of one already saved). Returns the saved record."""
        now = now or datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        with self._guard:
            lands = self._read()
            for x in lands:
                if x["city"] == city and x["apn"] == apn:
                    x["parcel"] = parcel
                    record = x
                    break
            else:
                record = {"city": city, "apn": apn, "saved_at": now, "parcel": parcel}
                lands.append(record)
            self._write(lands)
            return record

    def remove(self, city, apn):
        """Take a land off the list. True when it was there."""
        with self._guard:
            lands = self._read()
            keep = [x for x in lands if not (x["city"] == city and x["apn"] == apn)]
            if len(keep) == len(lands):
                return False
            self._write(keep)
            return True
