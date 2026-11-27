"""District projects: a whole market-intelligence package (program, market figures, competitors, parcels, the
assumptions register, narrative, documents, GIS layers, requirements) kept as data, versioned, compared, access
controlled and served under /api/districts. The contract is docs/district-data-contract.md.

Kept light on purpose: importing this package imports nothing else, so xlsx.py and pdf.py load on their own.
"""
import datetime
import re

ID = re.compile(r"[A-Za-z0-9._:\-]{1,64}")          # record ids
SLUG = re.compile(r"[a-z0-9][a-z0-9\-]{0,63}")       # project, dataset, layer and document ids


class Problem(Exception):
    """Something to tell the person, in plain words, with the HTTP status that fits."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def stamp(ts):
    """An ISO time in this computer's zone, to the second."""
    return datetime.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def day(ts):
    return datetime.datetime.fromtimestamp(ts).astimezone().date().isoformat()


def slug(text, fallback="item"):
    out = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:48]
    return out or fallback


def check_slug(value, what="id"):
    value = str(value or "")
    if not SLUG.fullmatch(value):
        raise Problem(400, "bad-request", f"“{value[:40]}” is not a usable {what}: use lower-case letters, digits and dashes.")
    return value


def check_id(value, what="id"):
    value = str(value if value is not None else "")
    if not ID.fullmatch(value):
        raise Problem(400, "bad-request", f"“{value[:40]}” is not a usable {what}: use letters, digits, “.”, “_”, “:” "
                                          "and “-”, up to 64 characters.")
    return value
