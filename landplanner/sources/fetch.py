"""The only two functions in landplanner/sources that touch the network.

get_json goes through tools/menifee.py's get_json, the app's one JSON network function, so the offline tests'
replay covers these readers too. get_bytes is for sources that publish a file (a spreadsheet, a text table):
it refuses anything bigger than `limit`, because the app must stay light on the computer it runs on.
"""
import http.client
import time
import urllib.error
import urllib.parse
import urllib.request

from ..cities import SourceError

AGENT = "land-planner/0.1 (public data lookup)"


def get_json(url, params=None, timeout=30, tries=2, post=False):
    from ..cities.menifee import tool      # the app's one JSON network function (the tests replace it)
    try:
        return tool.get_json(url, params, timeout=timeout, tries=tries, post=post)
    except tool.SourceError as e:
        raise SourceError(str(e)) from e


def get_bytes(url, params=None, timeout=30, tries=2, limit=6_000_000, first_bytes=None, data=None, headers=None):
    """The body of a public file. `first_bytes` asks for only the start of a big file (a ranged read); `data`
    (bytes) makes it a POST. Raises SourceError when the service does not answer or sends more than `limit`."""
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    head = {"User-Agent": AGENT, **(headers or {})}
    if first_bytes:
        head["Range"] = f"bytes=0-{int(first_bytes) - 1}"
    last = ""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(full, data=data, headers=head)
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed public https hosts
                body = r.read(limit + 1)
            if len(body) > limit:
                raise SourceError(f"{url}: the file is larger than {limit // 1_000_000} MB, so it is not read")
            return body
        # a reply cut short (IncompleteRead) or a broken one (BadStatusLine, RemoteDisconnected...) is an
        # http.client.HTTPException, which is not an OSError: it is a network failure like the rest
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, http.client.HTTPException) as e:
            last = f"{url}: {type(e).__name__}: {e}"
            time.sleep(0.6 * (attempt + 1))
    raise SourceError(last[:300])


def get_text(url, params=None, timeout=30, tries=2, limit=6_000_000, encoding="utf-8", **more):
    return get_bytes(url, params, timeout=timeout, tries=tries, limit=limit, **more).decode(encoding, "replace")
